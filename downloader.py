import os
import threading
import time
import glob as glob_mod
import yt_dlp

import config
import database
import video_utils

_queue_lock = threading.Lock()
_processing = False

_progress_map = {}
_progress_lock = threading.Lock()


def _get_ydl_opts(project_folder, settings):
    outtmpl = os.path.join(config.VIDEO_DIR, project_folder, "%(id)s.%(ext)s")

    fmt = settings.get("quality", "best")
    fmt_ext = settings.get("format", "mp4")
    audio_only = settings.get("audio_only", 0)

    if audio_only:
        format_str = "bestaudio/best"
        merge_fmt = None
    elif fmt == "best":
        format_str = f"bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
        merge_fmt = fmt_ext
    elif fmt == "1080":
        format_str = f"bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]"
        merge_fmt = fmt_ext
    elif fmt == "720":
        format_str = f"bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]"
        merge_fmt = fmt_ext
    elif fmt == "480":
        format_str = f"bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]"
        merge_fmt = fmt_ext
    else:
        format_str = "best"
        merge_fmt = fmt_ext

    opts = {
        "outtmpl": outtmpl,
        "format": format_str,
        "quiet": True,
        "no_warnings": True,
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
        "quality": "best", "format": "mp4", "audio_only": 0,
        "subtitles": 0, "thumbnail": 1,
    }

    database.update_video(item["id"], status="downloading")
    ydl_opts = _get_ydl_opts(project_folder, settings)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            if "entries" in info:
                for entry in info["entries"]:
                    if not entry:
                        continue
                    entry_url = entry.get("webpage_url") or entry.get("url", "")
                    if not entry_url or database.video_exists_by_url(entry_url, project_id):
                        continue
                    meta = _extract_metadata(entry)
                    database.insert_video(project_id=project_id, url=entry_url, status="queued", **meta)
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
    global _processing
    with _queue_lock:
        if _processing:
            return
        _processing = True

    def _run():
        global _processing
        try:
            while True:
                queued = database.get_queue(project_id)
                if not queued:
                    break
                item = queued[0]
                _download_item(item)
                time.sleep(0.5)
        except Exception:
            pass
        finally:
            with _queue_lock:
                _processing = False

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
