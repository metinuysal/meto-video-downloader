import os
from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for

import config
import database
import downloader
import video_utils

app = Flask(__name__)

database.init_db()

_secret_key = os.getenv("SECRET_KEY")
if not _secret_key:
    if config.DEBUG:
        _secret_key = "bulk-video-dev-secret"
    else:
        raise RuntimeError("SECRET_KEY environment variable must be set when BULK_VIDEO_DEBUG is false")
app.secret_key = _secret_key


@app.context_processor
def inject_config():
    return {"POLL_INTERVAL_MS": config.POLL_INTERVAL_MS}


@app.before_request
def load_current_project():
    from flask import session
    if "project_id" not in session:
        session["project_id"] = 1


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
    return render_template("settings.html", projects=projects, current=current, settings=settings)


@app.route("/about")
def about_page():
    projects = database.get_projects()
    current_id = request.args.get("project", type=int) or 1
    current = database.get_project(current_id) or projects[0]
    return render_template("about.html", projects=projects, current=current)


@app.route("/video/<int:video_id>")
def video_detail(video_id):
    video = database.get_video(video_id)
    if not video:
        return "Video not found", 404
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
            return jsonify({"error": "Name required"}), 400
        project = database.create_project(name)
        if not project:
            return jsonify({"error": "Project already exists"}), 400
        project_dir = os.path.join(config.VIDEO_DIR, project["folder"])
        os.makedirs(project_dir, exist_ok=True)
        return jsonify(project), 201
    return jsonify(database.get_projects())


@app.route("/api/projects/<int:project_id>", methods=["DELETE"])
def api_delete_project(project_id):
    if project_id == 1:
        return jsonify({"error": "Cannot delete default project"}), 400
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
            return jsonify({"error": "Invalid JSON body"}), 400
        allowed = database.PROJECT_SETTINGS_FIELDS
        unknown = set(data) - allowed
        if unknown:
            return jsonify({"error": f"Unknown settings: {', '.join(sorted(unknown))}"}), 400
        safe = {k: data[k] for k in data if k in allowed}
        database.update_project_settings(project_id, **safe)
        return jsonify({"ok": True})
    settings = database.get_project_settings(project_id) or {}
    return jsonify(settings)


@app.route("/api/queue", methods=["GET", "POST"])
def api_queue():
    project_id = request.args.get("project", type=int) or 1
    if request.method == "POST":
        data = request.get_json()
        raw_urls = data.get("urls", "")
        urls = [u.strip() for u in raw_urls.replace(",", "\n").split("\n") if u.strip()]
        if not urls:
            return jsonify({"error": "No URLs provided"}), 400
        added, skipped = downloader.add_to_queue(project_id, urls)
        return jsonify({"added": added, "skipped": skipped})

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
        project_id, filters=filters, search=search,
        sort_by=sort_by, order=order, limit=limit, offset=offset,
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
            return jsonify({"error": "Invalid tag name"}), 400
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
    return jsonify({"error": "Video not found"}), 404


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
            return jsonify({"error": "Date required"}), 400
        deleted = database.delete_videos_before_date(project_id, date_str)
        return jsonify({"deleted": deleted, "action": "before_date", "date": date_str})

    if action == "by_status":
        status = data.get("status", "failed")
        deleted = database.delete_videos_by_status(project_id, status)
        return jsonify({"deleted": deleted, "action": "by_status", "status": status})

    return jsonify({"error": "Unknown action"}), 400


@app.route("/api/stats")
def api_stats():
    project_id = request.args.get("project", type=int) or 1
    return jsonify(database.get_project_stats(project_id))


@app.route("/api/filters")
def api_filters():
    project_id = request.args.get("project", type=int) or 1
    return jsonify({
        "orientations": database.get_distinct_values(project_id, "orientation"),
        "length_categories": database.get_distinct_values(project_id, "length_category"),
        "aspect_ratios": database.get_distinct_values(project_id, "aspect_ratio"),
        "categories": database.get_all_categories(project_id),
        "tags": database.get_all_tags(),
    })


@app.route("/videos/<int:project_id>/<path:filename>")
def serve_video(project_id, filename):
    project = database.get_project(project_id)
    if not project:
        return "Project not found", 404
    folder = os.path.join(config.VIDEO_DIR, project["folder"])
    return send_from_directory(folder, filename)


if __name__ == "__main__":
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
