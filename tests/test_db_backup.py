import importlib
import shutil
import zipfile


def _fresh_modules(monkeypatch, tmp_path):
    monkeypatch.setenv("BULK_VIDEO_DB_PATH", str(tmp_path / "bulk_video.db"))
    monkeypatch.setenv("BULK_VIDEO_VIDEO_DIR", str(tmp_path / "videos"))
    monkeypatch.setenv("BULK_VIDEO_DEBUG", "1")
    monkeypatch.delenv("BULK_VIDEO_DB_URL", raising=False)

    import config
    import database
    import db_backup

    importlib.reload(config)
    importlib.reload(database)
    importlib.reload(db_backup)
    monkeypatch.setattr(db_backup, "DBBACKUP_DIR", str(tmp_path / "dbbackup"))
    return config, database, db_backup


def test_install_setup_creates_fresh_db(monkeypatch, tmp_path):
    _, database, db_backup = _fresh_modules(monkeypatch, tmp_path)

    result = db_backup.run_install_setup()

    assert result["action"] == "initialized"
    assert (tmp_path / "bulk_video.db").exists()
    assert database.get_projects()


def test_backup_and_restore_roundtrip(monkeypatch, tmp_path):
    _, database, db_backup = _fresh_modules(monkeypatch, tmp_path)
    db_backup.run_install_setup()

    database.create_project("Archive")
    payload = db_backup.build_backup_zip_bytes()
    assert payload.startswith(b"PK")

    restore_zip = tmp_path / "dbbackup" / "restore.zip"
    restore_zip.parent.mkdir(parents=True, exist_ok=True)
    restore_zip.write_bytes(payload)

    (tmp_path / "bulk_video.db").unlink()
    result = db_backup.run_install_setup()

    assert result["action"] == "restored"
    projects = database.get_projects()
    assert any(p["name"] == "Archive" for p in projects)


def test_install_setup_uses_bundled_seed_db(monkeypatch, tmp_path):
    _, database, db_backup = _fresh_modules(monkeypatch, tmp_path)

    seed_path = tmp_path / "dbbackup" / "bulk_video.db"
    seed_path.parent.mkdir(parents=True, exist_ok=True)
    db_backup.run_install_setup()
    shutil.copy2(tmp_path / "bulk_video.db", seed_path)
    (tmp_path / "bulk_video.db").unlink()

    result = db_backup.run_install_setup()

    assert result["action"] == "seeded"
    assert (tmp_path / "bulk_video.db").exists()
    assert database.get_projects()


def test_restore_zip_contains_db_file(monkeypatch, tmp_path):
    _, _, db_backup = _fresh_modules(monkeypatch, tmp_path)
    db_backup.run_install_setup()

    zip_path = tmp_path / "backup.zip"
    zip_path.write_bytes(db_backup.build_backup_zip_bytes())

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()

    assert db_backup.DB_FILENAME in names
