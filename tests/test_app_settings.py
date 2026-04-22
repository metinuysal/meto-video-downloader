import importlib


def _fresh_app(monkeypatch, tmp_path):
    monkeypatch.setenv("BULK_VIDEO_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("BULK_VIDEO_VIDEO_DIR", str(tmp_path / "videos"))
    monkeypatch.setenv("BULK_VIDEO_DEBUG", "1")

    import config
    import database

    importlib.reload(config)
    importlib.reload(database)
    database.init_db()

    import app
    importlib.reload(app)
    return app


def test_api_settings_rejects_unknown_keys(monkeypatch, tmp_path):
    app = _fresh_app(monkeypatch, tmp_path)
    client = app.app.test_client()

    res = client.put("/api/settings?project=1", json={"quality": "best", "hax": 1})
    assert res.status_code == 400


def test_api_settings_accepts_allowed_keys(monkeypatch, tmp_path):
    app = _fresh_app(monkeypatch, tmp_path)
    client = app.app.test_client()

    res = client.put("/api/settings?project=1", json={"quality": "worst"})
    assert res.status_code == 200

    res2 = client.get("/api/settings?project=1")
    assert res2.status_code == 200
    assert res2.get_json()["quality"] == "worst"
