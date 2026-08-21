import io
import os

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    url_for,
)

import config
import database
import db_backup
import downloader
import video_utils

_APP_START_TIME = __import__("time").time()

app = Flask(__name__)
app.config["BABEL_DEFAULT_LOCALE"] = config.BABEL_DEFAULT_LOCALE
app.config["BABEL_TRANSLATION_DIRECTORIES"] = config.BABEL_TRANSLATION_DIRECTORIES
app.config["LANGUAGES"] = config.LANGUAGES

# --- Babel (tr-en) ---
try:
    from flask_babel import Babel, gettext as _t, ngettext as _nt

    def _get_locale():
        # 1. ?lang=tr|en
        lang = request.args.get("lang")
        if lang in config.LANGUAGES:
            return lang
        # 2. session
        from flask import session as _sess

        sl = _sess.get("lang")
        if sl in config.LANGUAGES:
            return sl
        # 3. cookie
        cl = request.cookies.get("lang")
        if cl in config.LANGUAGES:
            return cl
        # 4. Accept-Language
        return request.accept_languages.best_match(config.LANGUAGES) or config.BABEL_DEFAULT_LOCALE

    babel = Babel(app, locale_selector=_get_locale)
except Exception as _e:
    # fallback if Flask-Babel not installed (dev)
    print(f"[babel] init failed: {_e}")

    def _t(s, **kw):
        return s % kw if kw else s

    def _nt(s, p, n, **kw):
        return (s if n == 1 else p) % kw if kw else (s if n == 1 else p)

    babel = None

database.init_db()

_secret_key = os.getenv("SECRET_KEY")
if not _secret_key:
    if config.DEBUG:
        _secret_key = "bulk-video-dev-secret"
    else:
        raise RuntimeError(
            "SECRET_KEY environment variable must be set when BULK_VIDEO_DEBUG is false"
        )
app.secret_key = _secret_key


@app.context_processor
def inject_config():
    from flask import g, session

    cur_lang = "tr"
    try:
        cur_lang = _get_locale()  # type: ignore
    except Exception:
        try:
            cur_lang = g.get("locale", config.BABEL_DEFAULT_LOCALE)  # type: ignore
        except Exception:
            cur_lang = session.get("lang", config.BABEL_DEFAULT_LOCALE)
    return {
        "POLL_INTERVAL_MS": config.POLL_INTERVAL_MS,
        "AUTH_ENABLED": bool(config.USERNAME and config.PASSWORD),
        "AUTHENTICATED": session.get("authenticated", False),
        "CURRENT_LANG": cur_lang,
        "LANGUAGES": config.LANGUAGES,
    }


@app.before_request
def _handle_lang_param():
    # ?lang=tr|en → session + cookie (dil birliği)
    from flask import g, session

    lang = request.args.get("lang")
    if lang in config.LANGUAGES:
        session["lang"] = lang
        g.locale = lang  # type: ignore
    else:
        try:
            g.locale = _get_locale()  # type: ignore
        except Exception:
            g.locale = config.BABEL_DEFAULT_LOCALE  # type: ignore


@app.route("/set-lang/<lang>")
def set_lang(lang):
    if lang not in config.LANGUAGES:
        lang = config.BABEL_DEFAULT_LOCALE
    from flask import g, make_response, session

    session["lang"] = lang
    g.locale = lang  # type: ignore
    # redirect back
    nxt = request.referrer or url_for("index")
    resp = make_response(redirect(nxt))
    resp.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return resp


@app.before_request
def load_current_project():
    from flask import redirect, request, session, url_for

    if config.USERNAME and config.PASSWORD:
        if request.endpoint and request.endpoint not in ("login_page", "static", "serve_video"):
            if not session.get("authenticated"):
                return redirect(url_for("login_page"))

    if "project_id" not in session:
        session["project_id"] = 1


@app.route("/login", methods=["GET", "POST"])
def login_page():
    from flask import session

    if not (config.USERNAME and config.PASSWORD):
        return redirect(url_for("index"))

    error = None
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == config.USERNAME and password == config.PASSWORD:
            session["authenticated"] = True
            return redirect(url_for("index"))
        error = _t("Invalid username or password.")

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    from flask import session

    session.pop("authenticated", None)
    return redirect(url_for("login_page"))


@app.route("/")
def index():
    projects = database.get_projects()
    current_id = request.args.get("project", type=int) or 1
    current = database.get_project(current_id) or projects[0]
    settings = database.get_project_settings(current["id"]) or {}
    return render_template("index.html", projects=projects, current=current, settings=settings)


@app.route("/library")
def library():
    projects = database.get_projects()
    current_id = request.args.get("project", type=int) or 1
    current = database.get_project(current_id) or projects[0]
    return render_template("library.html", projects=projects, current=current)


@app.route("/settings")
def settings_page():
    projects = database.get_projects()
    current_id = request.args.get("project", type=int) or 1
    current = database.get_project(current_id) or projects[0]
    settings = database.get_project_settings(current["id"]) or {}

    used_bytes = video_utils.get_directory_size(config.VIDEO_DIR)
    used_mb = used_bytes / (1024 * 1024)
    max_mb = config.STORAGE_MAX_MB

    storage_info = {
        "used_mb": used_mb,
        "max_mb": max_mb,
        "used_fmt": video_utils.format_filesize(used_bytes),
        "max_fmt": f"{max_mb} MB" if max_mb else _t("Limitsiz"),
        "percent": min(100, round((used_mb / max_mb * 100) if max_mb else 0, 1)),
    }

    return render_template(
        "settings.html",
        projects=projects,
        current=current,
        settings=settings,
        storage=storage_info,
        sqlite_backend=db_backup.uses_sqlite(),
    )


@app.route("/about")
def about_page():
    projects = database.get_projects()
    current_id = request.args.get("project", type=int) or 1
    current = database.get_project(current_id) or projects[0]

    # --- Sistem ve DB bilgileri (about sayfası) ---
    import platform
    import sys
    import time
    import shutil as _shutil
    import subprocess as _subprocess

    # Sistem bilgisi
    system_info = {}
    try:
        import importlib.metadata as _im

        flask_ver = _im.version("flask")
    except Exception:
        try:
            import flask as _flask

            flask_ver = getattr(_flask, "__version__", _t("unknown"))
        except Exception:
            flask_ver = _t("unknown")
    try:
        import importlib.metadata as _im2

        ytdlp_ver = _im2.version("yt-dlp")
    except Exception:
        try:
            from yt_dlp.version import __version__ as _v

            ytdlp_ver = _v
        except Exception:
            try:
                import yt_dlp as _yt

                ytdlp_ver = getattr(_yt, "version", getattr(_yt, "__version__", _t("unknown")))
                if hasattr(ytdlp_ver, "__version__"):
                    ytdlp_ver = ytdlp_ver.__version__
            except Exception:
                ytdlp_ver = _t("yok")
    # ffmpeg
    ffmpeg_ver = _t("yok")
    ffmpeg_available = False
    try:
        out = _subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=2)
        if out.returncode == 0 and out.stdout:
            ffmpeg_ver = out.stdout.splitlines()[0][:120]
            ffmpeg_available = True
    except Exception:
        pass
    # node / js runtimes (node/nodejs aynı, dedupe)
    js_runtimes = []
    seen_keys = set()
    for bin_name, key in (("node", "node"), ("nodejs", "node"), ("deno", "deno"), ("bun", "bun")):
        if key in seen_keys:
            continue
        p = _shutil.which(bin_name)
        if p:
            seen_keys.add(key)
            try:
                v = _subprocess.run([bin_name, "--version"], capture_output=True, text=True, timeout=1)
                ver = v.stdout.strip().splitlines()[0][:40] if v.stdout else "var"
            except Exception:
                ver = "var"
            js_runtimes.append(f"{key} ({ver})")
    # git / app version
    app_version = _t("unknown")
    git_commit = ""
    _base = None
    try:
        import pathlib as _pl

        _base = _pl.Path(__file__).parent
        # pyproject.toml
        _pp = _base / "pyproject.toml"
        if _pp.exists():
            txt = _pp.read_text()
            import re as _re

            m = _re.search(r'version\s*=\s*"([^"]+)"', txt)
            if m:
                app_version = m.group(1)
            else:
                # fallback: try without quotes
                m2 = _re.search(r"version\s*=\s*([^\s]+)", txt)
                if m2:
                    app_version = m2.group(1).strip('"').strip("'")
        # git
        if (_base / ".git").exists():
            out = _subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=1, cwd=str(_base))
            if out.returncode == 0:
                git_commit = out.stdout.strip()
    except Exception:
        pass
    # Fallback to importlib if still unknown
    if app_version == _t("unknown"):
        try:
            import importlib.metadata as _im3

            app_version = _im3.version("meto-video-downloader")
        except Exception:
            pass
    # uptime
    uptime_s = int(time.time() - _APP_START_TIME)
    def _fmt_uptime(s):
        h, r = divmod(s, 3600)
        m, sec = divmod(r, 60)
        if h:
            return _t("%(h)ssa %(m)sdk %(sec)ssn", h=h, m=m, sec=sec)
        if m:
            return _t("%(m)sdk %(sec)ssn", m=m, sec=sec)
        return _t("%(sec)ssn", sec=sec)
    # disk
    disk_total = disk_used = disk_free = 0
    try:
        du = _shutil.disk_usage(config.VIDEO_DIR)
        disk_total, disk_used, disk_free = du.total, du.used, du.free
    except Exception:
        pass
    is_docker = os.path.exists("/.dockerenv") or os.getenv("DOCKER") == "1"

    system_info = {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "flask_version": flask_ver,
        "ytdlp_version": str(ytdlp_ver),
        "ffmpeg_version": ffmpeg_ver,
        "ffmpeg_available": ffmpeg_available,
        "js_runtimes": ", ".join(js_runtimes) if js_runtimes else _t("yok"),
        "host": config.HOST,
        "port": config.PORT,
        "debug": config.DEBUG,
        "video_dir": config.VIDEO_DIR,
        "auth_enabled": bool(config.USERNAME and config.PASSWORD),
        "storage_max_mb": config.STORAGE_MAX_MB,
        "poll_interval_ms": config.POLL_INTERVAL_MS,
        "app_version": app_version,
        "git_commit": git_commit,
        "uptime": _fmt_uptime(uptime_s),
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(_APP_START_TIME)),
        "is_docker": is_docker,
        "disk_total_fmt": video_utils.format_filesize(disk_total) if disk_total else "—",
        "disk_used_fmt": video_utils.format_filesize(disk_used) if disk_used else "—",
        "disk_free_fmt": video_utils.format_filesize(disk_free) if disk_free else "—",
        "disk_percent": round(disk_used / disk_total * 100, 1) if disk_total else 0,
    }

    # DB bilgisi
    def _mask_url(url: str) -> str:
        if not url:
            return ""
        try:
            from urllib.parse import urlparse, urlunparse

            u = urlparse(url)
            if u.password:
                netloc = u.username or ""
                netloc += ":***@"
                if u.hostname:
                    netloc += u.hostname
                if u.port:
                    netloc += f":{u.port}"
                return urlunparse((u.scheme, netloc, u.path, u.params, u.query, u.fragment))
            return url
        except Exception:
            return "***"

    db_type = "SQLite"
    if database.is_mysql():
        db_type = "MySQL"
    elif database.is_postgres():
        db_type = "PostgreSQL"

    # DB host/user/name/port'u URL'den de parse et (Dokploy'da DB_HOST boşken URL dolu)
    _parsed_host = config.DB_HOST or ""
    _parsed_port = config.DB_PORT or ""
    _parsed_name = config.DB_NAME or ""
    _parsed_user = config.DB_USER or ""
    if config.DATABASE_URL and not _parsed_host:
        try:
            from urllib.parse import urlparse

            _u = urlparse(config.DATABASE_URL)
            _parsed_host = _u.hostname or _parsed_host
            _parsed_port = str(_u.port) if _u.port else _parsed_port
            _parsed_name = _u.path.lstrip("/") if _u.path else _parsed_name
            _parsed_user = _u.username or _parsed_user
        except Exception:
            pass

    db_info = {
        "type": db_type,
        "url_masked": _mask_url(config.DATABASE_URL or ""),
        "path": config.DATABASE_PATH if db_type == "SQLite" else "",
        "host": _parsed_host or ("—" if db_type == "SQLite" else "—"),
        "port": _parsed_port if db_type != "SQLite" else "",
        "name": _parsed_name if db_type != "SQLite" else "",
        "user": _parsed_user if db_type != "SQLite" else "",
        "status": _t("bilinmiyor"),
        "status_ok": False,
        "tables": [],
        "total_projects": 0,
        "total_videos": 0,
        "total_tags": 0,
        "total_size_fmt": "0 B",
        "video_dir_size_fmt": "0 B",
    }

    # Bağlantı testi ve istatistikler
    try:
        with database.get_db() as conn:
            # basit ping
            try:
                conn.execute("SELECT 1").fetchone()
                db_info["status"] = _t("bağlı ✓")
                db_info["status_ok"] = True
            except Exception as e:
                db_info["status"] = _t("hata: %(error)s", error=e)
                db_info["status_ok"] = False

            # tablolar
            try:
                if db_type == "SQLite":
                    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
                    db_info["tables"] = [r[0] if isinstance(r, (list, tuple)) else r["name"] for r in rows]
                elif db_type == "MySQL":
                    rows = conn.execute("SHOW TABLES").fetchall()
                    # pymysql DictCursor döner, key değişken
                    tbls = []
                    for r in rows:
                        if isinstance(r, dict):
                            tbls.append(list(r.values())[0])
                        else:
                            tbls.append(r[0])
                    db_info["tables"] = sorted(tbls)
                else:
                    rows = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()
                    db_info["tables"] = [r[0] if not isinstance(r, dict) else r["tablename"] for r in rows]
            except Exception:
                pass
    except Exception as e:
        db_info["status"] = _t("bağlanamadı: %(error)s", error=e)
        db_info["status_ok"] = False

    # sayımlar (bağlantı hatası olsa bile dene)
    try:
        db_info["total_projects"] = len(database.get_projects())
        db_info["total_tags"] = len(database.get_all_tags())
        # tüm projelerde video sayısı
        total_v = 0
        total_sz = 0
        for p in database.get_projects():
            st = database.get_project_stats(p["id"])
            total_v += st.get("total", 0)
            total_sz += st.get("total_size", 0)
        db_info["total_videos"] = total_v
        db_info["total_size_fmt"] = video_utils.format_filesize(total_sz)
        # video klasörü boyutu
        try:
            used = video_utils.get_directory_size(config.VIDEO_DIR)
            db_info["video_dir_size_fmt"] = video_utils.format_filesize(used)
        except Exception:
            db_info["video_dir_size_fmt"] = "—"
        # tablo satır sayıları
        try:
            with database.get_db() as _c:
                counts = {}
                for t in db_info.get("tables", [])[:12]:
                    try:
                        # tablo adı güvenli mi kontrol et (whitelist)
                        if t not in ("projects", "project_settings", "videos", "tags", "video_tags"):
                            continue
                        cnt = _c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()
                        # _first_value ile
                        from database import _first_value as _fv

                        counts[t] = _fv(cnt)
                    except Exception:
                        counts[t] = "—"
                db_info["table_counts"] = counts
        except Exception:
            db_info["table_counts"] = {}
        # DB dosya boyutu (SQLite) veya MySQL tahmini
        try:
            if db_type == "SQLite" and os.path.exists(config.DATABASE_PATH):
                sz = os.path.getsize(config.DATABASE_PATH)
                db_info["db_file_size_fmt"] = video_utils.format_filesize(sz)
            elif db_type == "MySQL":
                with database.get_db() as _c:
                    try:
                        row = _c.execute(
                            "SELECT ROUND(SUM(data_length + index_length)) AS sz FROM information_schema.tables WHERE table_schema = DATABASE()"
                        ).fetchone()
                        v = row["sz"] if isinstance(row, dict) else (row[0] if row else 0)
                        db_info["db_file_size_fmt"] = video_utils.format_filesize(int(v or 0))
                    except Exception:
                        db_info["db_file_size_fmt"] = "—"
            else:
                db_info["db_file_size_fmt"] = "—"
        except Exception:
            db_info["db_file_size_fmt"] = "—"
    except Exception:
        pass

    # Canlı kuyruk durumu
    live_info = {"queued": 0, "downloading": 0, "completed": 0, "failed": 0, "last_download": "—"}
    try:
        q = database.get_queue(current["id"])
        live_info["queued"] = len([x for x in q if x["status"] == "queued"])
        live_info["downloading"] = len([x for x in q if x["status"] == "downloading"])
        # completed/failed için stats'tan al
        st = database.get_project_stats(current["id"])
        live_info["completed"] = st.get("completed", 0)
        live_info["failed"] = st.get("failed", 0)
        # son indirme
        with database.get_db() as _c:
            row = _c.execute("SELECT downloaded_at FROM videos WHERE project_id = ? AND downloaded_at IS NOT NULL ORDER BY downloaded_at DESC LIMIT 1", (current["id"],)).fetchone()
            if row:
                v = row["downloaded_at"] if isinstance(row, dict) else row[0]
                live_info["last_download"] = str(v) if v else "—"
    except Exception:
        pass

    # Sistem çalışma akışı (statik)
    workflow = [
        {"step": "1", "title": _t("Linkleri Yapıştır"), "desc": _t("Download sayfasında video/playlist/kanal URL'lerini satır satır ekle. Kuyrukta duplicate kontrolü yapılır.")},
        {"step": "2", "title": _t("Kuyruk & yt-dlp"), "desc": _t("Arka planda `yt-dlp` + `ffmpeg` ile indirir. Canlı progress, rate-limit ve kalite ayarları `project_settings`’ten okunur.")},
        {"step": "3", "title": _t("Projeye Kaydet"), "desc": _t("Dosya `VIDEO_DIR/<project>/` altına yazılır, metadata (süre, boyut, thumbnail, uploader) DB’ye kaydedilir.")},
        {"step": "4", "title": _t("Kütüphane & Etiket"), "desc": _t("Library’de filtrele, ara, favorile, etiketle ve toplu taşı/sil. Tüm state DB’de tutulur.")},
    ]

    return render_template(
        "about.html",
        projects=projects,
        current=current,
        system_info=system_info,
        db_info=db_info,
        workflow=workflow,
        live_info=live_info,
    )


@app.route("/video/<int:video_id>")
def video_detail(video_id):
    video = database.get_video(video_id)
    if not video:
        return _t("Video not found"), 404
    tags = database.get_video_tags(video_id)
    all_tags = database.get_all_tags()
    categories = database.get_all_categories(video["project_id"])
    project = database.get_project(video["project_id"])

    if video["filepath"]:
        filename = os.path.basename(video["filepath"])
        video["video_url"] = f"/videos/{video['project_id']}/{filename}"
    else:
        video["video_url"] = ""

    return render_template(
        "video_detail.html",
        video=video,
        tags=tags,
        all_tags=all_tags,
        categories=categories,
        project=project,
    )


@app.route("/api/projects", methods=["GET", "POST"])
def api_projects():
    if request.method == "POST":
        data = request.get_json()
        name = data.get("name", "").strip()
        if not name:
            return jsonify({"error": _t("Name required")}), 400
        project = database.create_project(name)
        if not project:
            return jsonify({"error": _t("Project already exists")}), 400
        project_dir = os.path.join(config.VIDEO_DIR, project["folder"])
        os.makedirs(project_dir, exist_ok=True)
        return jsonify(project), 201
    return jsonify(database.get_projects())


@app.route("/api/projects/<int:project_id>", methods=["DELETE"])
def api_delete_project(project_id):
    if project_id == 1:
        return jsonify({"error": _t("Cannot delete default project")}), 400
    project = database.get_project(project_id)
    if project:
        folder = os.path.join(config.VIDEO_DIR, project["folder"])
        if os.path.exists(folder):
            import shutil

            shutil.rmtree(folder, ignore_errors=True)
    database.delete_project(project_id)
    return "", 204


@app.route("/api/settings", methods=["GET", "PUT"])
def api_settings():
    project_id = request.args.get("project", type=int) or 1
    if request.method == "PUT":
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify({"error": _t("Invalid JSON body")}), 400
        allowed = database.PROJECT_SETTINGS_FIELDS
        unknown = set(data) - allowed
        if unknown:
            return jsonify({"error": _t("Unknown settings: %(settings)s", settings=", ".join(sorted(unknown)))}), 400
        safe = {k: data[k] for k in data if k in allowed}
        database.update_project_settings(project_id, **safe)
        return jsonify({"ok": True})
    settings = database.get_project_settings(project_id) or {}
    return jsonify(settings)


@app.route("/api/queue", methods=["GET", "POST"])
def api_queue():
    project_id = request.args.get("project", type=int) or 1
    if request.method == "POST":
        if config.STORAGE_MAX_MB:
            used_mb = video_utils.get_directory_size(config.VIDEO_DIR) / (1024 * 1024)
            if used_mb >= config.STORAGE_MAX_MB:
                return jsonify(
                    {
                        "error": _t("Storage limit reached (%(limit)s MB). Cannot add more videos.", limit=config.STORAGE_MAX_MB)
                    }
                ), 400

        data = request.get_json()
        raw_urls = data.get("urls", "")
        urls = [u.strip() for u in raw_urls.replace(",", "\n").split("\n") if u.strip()]
        if not urls:
            return jsonify({"error": _t("No URLs provided")}), 400
        added, skipped = downloader.add_to_queue(project_id, urls)
        return jsonify({"added": added, "skipped": skipped})

    # Ensure queue processing recovers after app restarts.
    downloader.process_queue(project_id)
    queue = database.get_queue(project_id)
    for item in queue:
        prog = downloader.get_progress(item["url"])
        if prog:
            item["progress"] = prog
    return jsonify(queue)


@app.route("/api/videos")
def api_videos():
    project_id = request.args.get("project", type=int) or 1
    filters = {}
    for key in ("orientation", "length_category", "aspect_ratio", "custom_category"):
        val = request.args.get(key, "")
        if val:
            filters[key] = val

    favorite = request.args.get("favorite", "")
    if favorite:
        filters["favorite"] = favorite

    search = request.args.get("search", "")
    sort_by = request.args.get("sort", "downloaded_at")
    order = request.args.get("order", "DESC")
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))

    videos = database.get_videos(
        project_id,
        filters=filters,
        search=search,
        sort_by=sort_by,
        order=order,
        limit=limit,
        offset=offset,
    )
    total = database.count_videos(project_id, filters=filters, search=search)

    tags_map = database.get_video_tags_bulk([v["id"] for v in videos])
    for v in videos:
        v["tags"] = tags_map.get(v["id"], [])
        v["duration_fmt"] = video_utils.format_duration(v["duration"])
        v["filesize_fmt"] = video_utils.format_filesize(v["filesize"])

    return jsonify({"videos": videos, "total": total})


@app.route("/api/tags", methods=["GET", "POST"])
def api_tags():
    if request.method == "POST":
        data = request.get_json()
        name = data.get("name", "")
        tag = database.create_tag(name)
        if not tag:
            return jsonify({"error": _t("Invalid tag name")}), 400
        return jsonify(tag), 201
    return jsonify(database.get_all_tags())


@app.route("/api/tags/<int:tag_id>", methods=["DELETE"])
def api_delete_tag(tag_id):
    database.delete_tag(tag_id)
    return "", 204


@app.route("/api/video/<int:video_id>/tag", methods=["GET", "POST"])
def api_video_tags(video_id):
    if request.method == "GET":
        return jsonify(database.get_video_tags(video_id))
    data = request.get_json()
    tag_id = data.get("tag_id")
    tag_name = data.get("tag_name", "").strip().lower()
    if tag_id:
        database.add_video_tag(video_id, tag_id)
    elif tag_name:
        tag = database.create_tag(tag_name)
        if tag:
            database.add_video_tag(video_id, tag["id"])
    return jsonify(database.get_video_tags(video_id))


@app.route("/api/video/<int:video_id>/tag/<int:tag_id>", methods=["DELETE"])
def api_remove_tag(video_id, tag_id):
    database.remove_video_tag(video_id, tag_id)
    return "", 204


@app.route("/api/video/<int:video_id>/category", methods=["POST"])
def api_set_category(video_id):
    data = request.get_json()
    database.update_video(video_id, custom_category=data.get("category", ""))
    return jsonify({"custom_category": data.get("category", "")})


@app.route("/api/video/<int:video_id>", methods=["DELETE"])
def api_delete_video(video_id):
    video = database.get_video(video_id)
    if video and video.get("filepath") and os.path.exists(video["filepath"]):
        os.remove(video["filepath"])
    database.delete_video(video_id)
    return "", 204


@app.route("/api/video/<int:video_id>/favorite", methods=["POST"])
def api_toggle_favorite(video_id):
    result = database.toggle_favorite(video_id)
    if result is not None:
        return jsonify({"favorite": result})
    return jsonify({"error": _t("Video not found")}), 404


@app.route("/api/videos/bulk", methods=["POST"])
def api_videos_bulk():
    data = request.get_json()
    action = data.get("action")
    video_ids = data.get("video_ids", [])
    value = data.get("value")

    if not action or not video_ids:
        return jsonify({"error": _t("Invalid request")}), 400

    if action == "move_project":
        moved = database.bulk_move_project(video_ids, int(value))
        return jsonify({"moved": moved})
    elif action == "set_category":
        updated = database.bulk_update_category(video_ids, value)
        return jsonify({"updated": updated})
    elif action == "add_tag":
        added = database.bulk_add_tag(video_ids, value)
        return jsonify({"added": added})
    elif action == "delete":
        deleted = database.bulk_delete_videos(video_ids)
        return jsonify({"deleted": deleted})

    return jsonify({"error": _t("Unknown action")}), 400


@app.route("/api/reset", methods=["POST"])
def api_reset_project():
    project_id = request.args.get("project", type=int) or 1
    data = request.get_json() or {}
    action = data.get("action", "all")

    if action == "all":
        deleted = database.reset_project(project_id)
        return jsonify({"deleted": deleted, "action": "all"})

    if action == "before_date":
        date_str = data.get("date", "")
        if not date_str:
            return jsonify({"error": _t("Date required")}), 400
        deleted = database.delete_videos_before_date(project_id, date_str)
        return jsonify({"deleted": deleted, "action": "before_date", "date": date_str})

    if action == "by_status":
        status = data.get("status", "failed")
        deleted = database.delete_videos_by_status(project_id, status)
        return jsonify({"deleted": deleted, "action": "by_status", "status": status})

    return jsonify({"error": _t("Unknown action")}), 400


@app.route("/api/db/backup")
def api_db_backup_download():
    if not db_backup.uses_sqlite():
        return jsonify({"error": _t("Database backup is only available with SQLite.")}), 400
    if not os.path.exists(config.DATABASE_PATH):
        return jsonify({"error": _t("Database file not found.")}), 404
    try:
        payload = db_backup.build_backup_zip_bytes()
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    return send_file(
        io.BytesIO(payload),
        mimetype="application/zip",
        as_attachment=True,
        download_name=db_backup.backup_download_name(),
    )


@app.route("/api/db/backup/save", methods=["POST"])
def api_db_backup_save():
    if not db_backup.uses_sqlite():
        return jsonify({"error": _t("Database backup is only available with SQLite.")}), 400
    if not os.path.exists(config.DATABASE_PATH):
        return jsonify({"error": _t("Database file not found.")}), 404
    try:
        path = db_backup.save_backup_to_folder()
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify({"saved": os.path.basename(path), "path": path})


@app.route("/api/stats")
def api_stats():
    project_id = request.args.get("project", type=int) or 1
    return jsonify(database.get_project_stats(project_id))


@app.route("/api/filters")
def api_filters():
    project_id = request.args.get("project", type=int) or 1
    return jsonify(
        {
            "orientations": database.get_distinct_values(project_id, "orientation"),
            "length_categories": database.get_distinct_values(project_id, "length_category"),
            "aspect_ratios": database.get_distinct_values(project_id, "aspect_ratio"),
            "categories": database.get_all_categories(project_id),
            "tags": database.get_all_tags(),
        }
    )


@app.route("/videos/<int:project_id>/<path:filename>")
def serve_video(project_id, filename):
    project = database.get_project(project_id)
    if not project:
        return _t("Project not found"), 404
    folder = os.path.join(config.VIDEO_DIR, project["folder"])
    return send_from_directory(folder, filename)


if __name__ == "__main__":
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
