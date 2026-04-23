import importlib


def _fresh_modules(monkeypatch, tmp_path):
    monkeypatch.setenv("BULK_VIDEO_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("BULK_VIDEO_VIDEO_DIR", str(tmp_path / "videos"))
    monkeypatch.setenv("BULK_VIDEO_DEBUG", "1")
    monkeypatch.setenv("BULK_VIDEO_USERNAME", "")
    monkeypatch.setenv("BULK_VIDEO_PASSWORD", "")

    import config
    import database

    importlib.reload(config)
    importlib.reload(database)
    database.init_db()
    return database


def test_update_project_settings_ignores_unknown_keys(monkeypatch, tmp_path):
    database = _fresh_modules(monkeypatch, tmp_path)

    database.update_project_settings(1, badcol="x")
    before = database.get_project_settings(1)

    database.update_project_settings(1, quality="worst", badcol="x")
    after = database.get_project_settings(1)

    assert before["quality"] != after["quality"]
    assert after["quality"] == "worst"


def test_get_video_tags_bulk(monkeypatch, tmp_path):
    database = _fresh_modules(monkeypatch, tmp_path)

    vid = database.insert_video(1, "https://example.com/v", video_id="v1", title="t1")
    tag = database.create_tag("tag1")
    database.add_video_tag(vid, tag["id"])

    tags_map = database.get_video_tags_bulk([vid])
    assert vid in tags_map
    assert tags_map[vid][0]["name"] == "tag1"


def test_get_distinct_values_is_allowlisted(monkeypatch, tmp_path):
    database = _fresh_modules(monkeypatch, tmp_path)
    assert database.get_distinct_values(1, "not_a_column") == []
