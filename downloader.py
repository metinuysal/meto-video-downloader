import concurrent.futures
import glob as glob_mod
import os
import shutil
import threading
import time

import yt_dlp

import config
import database
import video_utils


# Build a js_runtimes dict for yt-dlp (needed for YouTube signature solving).
# Any runtime found in PATH is enabled; node/nodejs → keyed as "node".
def _build_js_runtimes():
    runtimes = {}
    for binary, key in (("node", "node"), ("nodejs", "node"), ("deno", "deno"), ("bun", "bun")):
        path = shutil.which(binary)
        if path and key not in runtimes:
            runtimes[key] = {}
    return runtimes or None


_JS_RUNTIMES = _build_js_runtimes()

_queue_lock = threading.Lock()
_processing_projects = set()

_progress_map = {}
_progress_lock = threading.Lock()


def _parse_rate_limit(rate_str):
    if not rate_str:
        return None
    rate_str = rate_str.upper().strip()
    multiplier = 1
    if rate_str.endswith("K"):
        multiplier = 1024
        rate_str = rate_str[:-1]
    elif rate_str.endswith("M"):
        multiplier = 1024 * 1024
        rate_str = rate_str[:-1]
    elif rate_str.endswith("G"):
        multiplier = 1024 * 1024 * 1024
        rate_str = rate_str[:-1]
    try:
        return int(float(rate_str) * multiplier)
    except ValueError:
        return None


def _get_ydl_opts(project_folder, settings):
    template = settings.get("output_template") or "%(id)s.%(ext)s"
    outtmpl = os.path.join(config.VIDEO_DIR, project_folder, template)

    fmt = settings.get("quality", "best")
    fmt_ext = settings.get("format", "mp4")
    audio_only = settings.get("audio_only", 0)

    if audio_only:
        format_str = "bestaudio/best"
        merge_fmt = None
    elif fmt == "best":
        format_str = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
        merge_fmt = fmt_ext
    elif fmt == "1080":
        format_str = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]"
        merge_fmt = fmt_ext
    elif fmt == "720":
        format_str = "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]"
        merge_fmt = fmt_ext
    elif fmt == "480":
        format_str = "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]"
        merge_fmt = fmt_ext
    else:
        format_str = "best"
        merge_fmt = fmt_ext

    opts = {
        "outtmpl": outtmpl,
        "format": format_str,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
    }

    if merge_fmt and not audio_only:
        opts["merge_output_format"] = merge_fmt

    if settings.get("subtitles"):
        opts["writesubtitles"] = True
        opts["subtitleslangs"] = ["en"]

    if not settings.get("thumbnail", True):
        opts["writethumbnail"] = False
    else:
        opts["writethumbnail"] = True

    # Configure JS runtime so yt-dlp can solve YouTube signatures.
    if _JS_RUNTIMES:
        opts["js_runtimes"] = _JS_RUNTIMES

    if settings.get("proxy"):
        opts["proxy"] = settings["proxy"]

    if settings.get("cookies_browser"):
        opts["cookiesfrombrowser"] = (settings["cookies_browser"],)

    rate_limit = _parse_rate_limit(settings.get("rate_limit"))
    if rate_limit:
        opts["ratelimit"] = rate_limit

    if settings.get("embed_metadata"):
        opts.setdefault("postprocessors", []).append(
            {"key": "FFmpegMetadata", "add_metadata": True}
        )

    return opts


def _extract_metadata(info):
    width = info.get("width", 0) or 0
    height = info.get("height", 0) or 0
    duration = int(info.get("duration", 0) or 0)
    aspect_ratio = video_utils.compute_aspect_ratio(width, height)
    orientation = video_utils.compute_orientation(width, height)
    length_category = video_utils.compute_length_category(duration)

    return {
        "video_id": info.get("id", ""),
        "title": info.get("title", ""),
        "duration": duration,
        "width": width,
        "height": height,
        "aspect_ratio": aspect_ratio,
        "orientation": orientation,
        "length_category": length_category,
        "filesize": info.get("filesize") or info.get("filesize_approx", 0) or 0,
        "thumbnail": info.get("thumbnail", ""),
        "uploader": info.get("uploader", ""),
        "upload_date": info.get("upload_date", ""),
    }


def _find_downloaded_file(project_folder, video_id):
    base = os.path.join(config.VIDEO_DIR, project_folder)
    for ext in ("mp4", "mkv", "webm", "avi", "mov", "m4a", "opus"):
        path = os.path.join(base, f"{video_id}.{ext}")
        if os.path.exists(path):
            return path
    return ""


def _get_partial_files(project_folder, video_id):
    base = os.path.join(config.VIDEO_DIR, project_folder)
    files = []
    for pattern in (f"{video_id}*.part", f"{video_id}*.tmp", f"{video_id}*.ytdl"):
        files.extend(glob_mod.glob(os.path.join(base, pattern)))
    return files


def _start_progress_tracker(url, project_folder, video_id, total_size):
    def _track():
        prev_size = 0
        while True:
            partials = _get_partial_files(project_folder, video_id)
            if partials:
                current = sum(os.path.getsize(f) for f in partials if os.path.exists(f))
                if current > prev_size:
                    prev_size = current
                    pct = round((current / total_size * 100) if total_size else 0, 1)
                    with _progress_lock:
                        _progress_map[url] = {
                            "percent": min(pct, 99.9),
                            "speed": "",
                            "eta": "",
                        }
            elif _find_downloaded_file(project_folder, video_id):
                with _progress_lock:
                    _progress_map[url] = {
                        "percent": 100,
                        "speed": "Processing...",
                        "eta": "",
                    }
                break
            time.sleep(0.3)

    thread = threading.Thread(target=_track, daemon=True)
    thread.start()


def _format_speed(speed_bytes):
    if not speed_bytes:
        return ""
    units = ["B/s", "KB/s", "MB/s", "GB/s"]
    speed = float(speed_bytes)
    unit = 0
    while speed >= 1024 and unit < len(units) - 1:
        speed /= 1024
        unit += 1
    return f"{speed:.1f} {units[unit]}"


def _format_eta(seconds):
    if seconds is None:
        return ""
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return ""
    mins, secs = divmod(max(total, 0), 60)
    hrs, mins = divmod(mins, 60)
    if hrs:
        return f"{hrs:d}h {mins:02d}m"
    return f"{mins:d}m {secs:02d}s"


def _make_progress_hook(url):
    def _hook(data):
        status = data.get("status")
        if status == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            downloaded = data.get("downloaded_bytes") or 0
            pct = round((downloaded / total * 100), 1) if total else 0
            speed = _format_speed(data.get("speed"))
            eta = _format_eta(data.get("eta"))
            with _progress_lock:
                _progress_map[url] = {
                    "percent": min(max(pct, 0), 99.9),
                    "speed": speed,
                    "eta": eta,
                }
        elif status == "finished":
            with _progress_lock:
                _progress_map[url] = {
                    "percent": 100,
                    "speed": "Processing...",
                    "eta": "",
                }

    return _hook


def get_progress(url):
    with _progress_lock:
        return _progress_map.get(url)


def clear_progress(url):
    with _progress_lock:
        _progress_map.pop(url, None)


def _download_item(item):
    url = item["url"]
    project_id = item.get("project_id", 1)
    project = database.get_project(project_id)
    project_folder = project["folder"] if project else "default"
    settings = database.get_project_settings(project_id) or {
        "quality": "best",
        "format": "mp4",
        "audio_only": 0,
        "subtitles": 0,
        "thumbnail": 1,
    }

    database.update_video(item["id"], status="downloading")
    # Seed progress immediately so the UI shows activity right away.
    with _progress_lock:
        _progress_map[url] = {"percent": 0, "speed": "Connecting...", "eta": ""}

    ydl_opts = _get_ydl_opts(project_folder, settings)
    ydl_opts["progress_hooks"] = [_make_progress_hook(url)]
    ydl_opts["socket_timeout"] = 20
    ydl_opts["retries"] = 5
    ydl_opts["fragment_retries"] = 5
    ydl_opts["extractor_retries"] = 3

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            with _progress_lock:
                _progress_map[url]["speed"] = "Extracting..."
            info = ydl.extract_info(url, download=False)

            if "entries" in info:
                entries = [e for e in info["entries"] if e]
                total = len(entries)
                added = 0
                for i, entry in enumerate(entries, 1):
                    entry_url = entry.get("webpage_url") or entry.get("url", "")
                    if not entry_url or database.video_exists_by_url(entry_url, project_id):
                        continue
                    meta = _extract_metadata(entry)
                    database.insert_video(
                        project_id=project_id, url=entry_url, status="queued", **meta
                    )
                    added += 1
                    pct = round(i / total * 100, 1) if total else 0
                    with _progress_lock:
                        _progress_map[url] = {
                            "percent": pct,
                            "speed": f"Playlist: {i}/{total}",
                            "eta": "",
                        }
                database.update_video(
                    item["id"],
                    status="completed",
                    downloaded_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                )
                return

            meta = _extract_metadata(info)
            database.update_video(item["id"], **meta)

            video_id = meta.get("video_id", "")
            total_size = meta.get("filesize", 0)
            if total_size:
                _start_progress_tracker(url, project_folder, video_id, total_size)

            ydl.download([url])

        filepath = _find_downloaded_file(project_folder, video_id)
        if filepath and os.path.exists(filepath):
            database.update_video(
                item["id"],
                filepath=filepath,
                status="completed",
                downloaded_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            )
        else:
            database.update_video(
                item["id"],
                status="completed",
                downloaded_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            )
    except yt_dlp.utils.DownloadError as e:
        database.update_video(item["id"], status=f"failed: {str(e)[:100]}")
    except Exception as e:
        database.update_video(item["id"], status=f"failed: {str(e)[:100]}")
    finally:
        clear_progress(url)


def process_queue(project_id):
    with _queue_lock:
        if project_id in _processing_projects:
            return
        _processing_projects.add(project_id)

    # Recover items left as downloading after crashes/restarts.
    database.requeue_downloading(project_id)

    settings = database.get_project_settings(project_id) or {}
    max_concurrent = int(settings.get("max_concurrent") or 1)
    max_concurrent = max(1, min(10, max_concurrent))

    def _run():
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent) as executor:
                futures = set()
                while True:
                    queued = database.get_queue(project_id)
                    pending = [q for q in queued if q["status"] == "queued"]

                    if not pending and not futures:
                        break

                    for item in pending:
                        if len(futures) >= max_concurrent:
                            break
                        database.update_video(item["id"], status="downloading")
                        f = executor.submit(_download_item, item)
                        futures.add(f)

                    if futures:
                        done, _ = concurrent.futures.wait(
                            futures, return_when=concurrent.futures.FIRST_COMPLETED, timeout=1.0
                        )
                        futures.difference_update(done)
                    else:
                        time.sleep(1.0)
        except Exception:
            pass
        finally:
            with _queue_lock:
                _processing_projects.discard(project_id)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


def add_to_queue(project_id, urls):
    added = 0
    skipped = 0
    for url in urls:
        url = url.strip()
        if not url:
            continue
        if database.video_exists_by_url(url, project_id):
            skipped += 1
            continue
        database.insert_video(project_id=project_id, url=url, status="queued")
        added += 1

    if added > 0:
        process_queue(project_id)

    return added, skipped
