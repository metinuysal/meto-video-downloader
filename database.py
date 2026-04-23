import os
import shutil
import sqlite3
import threading
from contextlib import contextmanager

import config

_local = threading.local()

PROJECT_SETTINGS_FIELDS = {
    "quality",
    "format",
    "audio_only",
    "subtitles",
    "thumbnail",
    "cookies_browser",
    "proxy",
    "rate_limit",
    "output_template",
    "embed_metadata",
    "max_concurrent",
}
VIDEO_FILTER_FIELDS = {
    "orientation",
    "length_category",
    "aspect_ratio",
    "custom_category",
    "favorite",
}


def is_mysql():
    return bool(config.DATABASE_URL and config.DATABASE_URL.startswith("mysql"))


def is_postgres():
    return bool(config.DATABASE_URL and config.DATABASE_URL.startswith("postgres"))


def get_integrity_error():
    if is_mysql():
        import pymysql

        return pymysql.err.IntegrityError
    if is_postgres():
        import psycopg2

        return psycopg2.IntegrityError
    return sqlite3.IntegrityError


class MySQLCursorWrapper:
    def __init__(self, cursor):
        self._cursor = cursor

    def _translate_query(self, query):
        return query.replace("?", "%s")

    def execute(self, query, params=None):
        return self._cursor.execute(self._translate_query(query), params)

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    def close(self):
        self._cursor.close()


class MySQLConnectionWrapper:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, query, params=None):
        cursor = self.cursor()
        cursor.execute(query, params)
        return cursor

    def executescript(self, script):
        cursor = self.cursor()
        statements = script.split(";")
        for stmt in statements:
            stmt = stmt.strip()
            if stmt:
                cursor.execute(stmt)

    def cursor(self):
        import pymysql.cursors

        return MySQLCursorWrapper(self._conn.cursor(pymysql.cursors.DictCursor))

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()


class PostgresCursorWrapper:
    def __init__(self, cursor):
        self._cursor = cursor

    def _translate_query(self, query):
        return query.replace("?", "%s")

    def execute(self, query, params=None):
        return self._cursor.execute(self._translate_query(query), params)

    def fetchone(self):
        row = self._cursor.fetchone()
        return dict(row) if row else None

    def fetchall(self):
        return [dict(r) for r in self._cursor.fetchall()]

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        # Postgres returns lastrowid usually as an object, but psycopg2 might not populate it on generic INSERTS without RETURNING.
        # However, for basic apps relying on sqlite lastrowid, we might need a workaround.
        # But wait, SQLite lastrowid only works for simple inserts anyway. Let's see if we can get by.
        return self._cursor.lastrowid

    def close(self):
        self._cursor.close()


class PostgresConnectionWrapper:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, query, params=None):
        cursor = self.cursor()
        # To simulate lastrowid since psycopg2 doesn't fill it nicely without RETURNING id:
        if query.strip().upper().startswith("INSERT INTO"):
            # Simple hack to get returning id if possible, otherwise rely on the limited support
            try:
                cursor.execute(query + " RETURNING id", params)
                res = cursor.fetchone()
                if res and "id" in res:
                    cursor._cursor.lastrowid = res["id"]
            except Exception:
                self._conn.rollback()
                cursor.execute(query, params)
        else:
            cursor.execute(query, params)
        return cursor

    def executescript(self, script):
        cursor = self.cursor()
        cursor._cursor.execute(script)

    def cursor(self):
        import psycopg2.extras

        return PostgresCursorWrapper(self._conn.cursor(cursor_factory=psycopg2.extras.DictCursor))

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()


def get_connection():
    if not hasattr(_local, "connection"):
        if is_mysql():
            from urllib.parse import urlparse

            import pymysql

            url = urlparse(config.DATABASE_URL)
            conn = pymysql.connect(
                host=url.hostname,
                user=url.username,
                password=url.password,
                database=url.path.lstrip("/"),
                port=url.port or 3306,
                charset="utf8mb4",
            )
            _local.connection = MySQLConnectionWrapper(conn)
        elif is_postgres():
            import psycopg2

            conn = psycopg2.connect(
                config.DATABASE_URL.replace("postgresql+psycopg2://", "postgresql://")
            )
            _local.connection = PostgresConnectionWrapper(conn)
        else:
            _local.connection = sqlite3.connect(config.DATABASE_PATH)
            _local.connection.row_factory = sqlite3.Row
            _local.connection.execute("PRAGMA journal_mode=WAL")
            _local.connection.execute("PRAGMA foreign_keys=ON")
    return _local.connection


@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db():
    with get_db() as conn:
        script = """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                slug TEXT UNIQUE NOT NULL,
                folder TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS project_settings (
                project_id INTEGER PRIMARY KEY,
                quality TEXT DEFAULT 'best',
                format TEXT DEFAULT 'mp4',
                audio_only INTEGER DEFAULT 0,
                subtitles INTEGER DEFAULT 0,
                thumbnail INTEGER DEFAULT 1,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER DEFAULT 1,
                url TEXT NOT NULL,
                video_id TEXT,
                title TEXT DEFAULT '',
                filepath TEXT DEFAULT '',
                duration INTEGER DEFAULT 0,
                width INTEGER DEFAULT 0,
                height INTEGER DEFAULT 0,
                aspect_ratio TEXT DEFAULT '',
                orientation TEXT DEFAULT '',
                length_category TEXT DEFAULT '',
                custom_category TEXT DEFAULT '',
                filesize INTEGER DEFAULT 0,
                thumbnail TEXT DEFAULT '',
                uploader TEXT DEFAULT '',
                upload_date TEXT DEFAULT '',
                downloaded_at DATETIME,
                status TEXT DEFAULT 'queued',
                favorite INTEGER DEFAULT 0,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            );

            CREATE TABLE IF NOT EXISTS video_tags (
                video_id INTEGER NOT NULL,
                tag_id INTEGER NOT NULL,
                PRIMARY KEY (video_id, tag_id),
                FOREIGN KEY (video_id) REFERENCES videos(id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_videos_project_downloaded ON videos(project_id, downloaded_at);
            CREATE INDEX IF NOT EXISTS idx_videos_project_status ON videos(project_id, status);
            CREATE INDEX IF NOT EXISTS idx_videos_project_favorite ON videos(project_id, favorite);
            CREATE INDEX IF NOT EXISTS idx_videos_project_orientation ON videos(project_id, orientation);
            CREATE INDEX IF NOT EXISTS idx_videos_project_length ON videos(project_id, length_category);
            CREATE INDEX IF NOT EXISTS idx_videos_project_aspect ON videos(project_id, aspect_ratio);
            CREATE INDEX IF NOT EXISTS idx_videos_project_category ON videos(project_id, custom_category);
            CREATE INDEX IF NOT EXISTS idx_video_tags_video_id ON video_tags(video_id);
            CREATE INDEX IF NOT EXISTS idx_video_tags_tag_id ON video_tags(tag_id);
        """
        if is_mysql():
            script = script.replace("AUTOINCREMENT", "AUTO_INCREMENT")
        elif is_postgres():
            script = script.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
            script = script.replace("DATETIME", "TIMESTAMP")

        conn.executescript(script)

    with get_db() as conn:
        exists = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO projects (name, slug, folder) VALUES (?, ?, ?)",
                ("Default", "default", "default"),
            )
            conn.execute("INSERT INTO project_settings (project_id) VALUES (1)")

        # Migrate existing project_settings
        columns = [
            ("cookies_browser", "TEXT DEFAULT ''"),
            ("proxy", "TEXT DEFAULT ''"),
            ("rate_limit", "TEXT DEFAULT ''"),
            ("output_template", "TEXT DEFAULT '%(id)s.%(ext)s'"),
            ("embed_metadata", "INTEGER DEFAULT 0"),
            ("max_concurrent", "INTEGER DEFAULT 1"),
        ]
        for col, col_def in columns:
            try:
                conn.execute(f"ALTER TABLE project_settings ADD COLUMN {col} {col_def}")
            except Exception:
                pass


def get_projects():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM projects ORDER BY name").fetchall()
        return [dict(r) for r in rows]


def create_project(name):
    slug = "".join(c.lower() if c.isalnum() else "-" for c in name).strip("-")
    if not slug:
        return None
    folder = slug
    with get_db() as conn:
        try:
            cursor = conn.execute(
                "INSERT INTO projects (name, slug, folder) VALUES (?, ?, ?)", (name, slug, folder)
            )
            conn.execute(
                "INSERT INTO project_settings (project_id) VALUES (?)", (cursor.lastrowid,)
            )
            return {"id": cursor.lastrowid, "name": name, "slug": slug, "folder": folder}
        except get_integrity_error():
            return None


def delete_project(project_id):
    with get_db() as conn:
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))


def get_project(project_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return dict(row) if row else None


def get_project_settings(project_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM project_settings WHERE project_id = ?", (project_id,)
        ).fetchone()
        return dict(row) if row else None


def update_project_settings(project_id, **kwargs):
    if not kwargs:
        return
    kwargs = {k: v for k, v in kwargs.items() if k in PROJECT_SETTINGS_FIELDS}
    if not kwargs:
        return
    fields = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [project_id]
    with get_db() as conn:
        conn.execute(f"UPDATE project_settings SET {fields} WHERE project_id = ?", values)


def video_exists_by_url(url, project_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM videos WHERE url = ? AND project_id = ?", (url, project_id)
        ).fetchone()
        return row is not None


def video_exists_by_video_id(video_id, project_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM videos WHERE video_id = ? AND project_id = ?", (video_id, project_id)
        ).fetchone()
        return row is not None


def insert_video(
    project_id,
    url,
    video_id="",
    title="",
    filepath="",
    duration=0,
    width=0,
    height=0,
    aspect_ratio="",
    orientation="",
    length_category="",
    filesize=0,
    thumbnail="",
    uploader="",
    upload_date="",
    status="queued",
):
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO videos
               (project_id, url, video_id, title, filepath, duration, width, height,
                aspect_ratio, orientation, length_category, filesize,
                thumbnail, uploader, upload_date, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                project_id,
                url,
                video_id,
                title,
                filepath,
                duration,
                width,
                height,
                aspect_ratio,
                orientation,
                length_category,
                filesize,
                thumbnail,
                uploader,
                upload_date,
                status,
            ),
        )
        return cursor.lastrowid


def update_video(vid, **kwargs):
    if not kwargs:
        return
    fields = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [vid]
    with get_db() as conn:
        conn.execute(f"UPDATE videos SET {fields} WHERE id = ?", values)


def update_video_by_url(url, **kwargs):
    if not kwargs:
        return
    fields = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [url]
    with get_db() as conn:
        conn.execute(f"UPDATE videos SET {fields} WHERE url = ?", values)


def get_video(video_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
        return dict(row) if row else None


def get_videos(
    project_id, filters=None, search=None, sort_by="downloaded_at", order="DESC", limit=50, offset=0
):
    query = "SELECT * FROM videos WHERE project_id = ?"
    params = [project_id]

    if filters:
        for key, value in filters.items():
            if key not in VIDEO_FILTER_FIELDS:
                continue
            if value and value != "all":
                query += f" AND {key} = ?"
                params.append(value)

    if search:
        query += " AND (LOWER(title) LIKE LOWER(?) OR LOWER(uploader) LIKE LOWER(?))"
        params.extend([f"%{search}%", f"%{search}%"])

    allowed_sort = {"downloaded_at", "title", "duration", "filesize", "upload_date"}
    if sort_by not in allowed_sort:
        sort_by = "downloaded_at"
    allowed_order = {"ASC", "DESC"}
    if order not in allowed_order:
        order = "DESC"

    query += f" ORDER BY {sort_by} {order} LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def count_videos(project_id, filters=None, search=None):
    query = "SELECT COUNT(*) FROM videos WHERE project_id = ?"
    params = [project_id]

    if filters:
        for key, value in filters.items():
            if key not in VIDEO_FILTER_FIELDS:
                continue
            if value and value != "all":
                query += f" AND {key} = ?"
                params.append(value)

    if search:
        query += " AND (LOWER(title) LIKE LOWER(?) OR LOWER(uploader) LIKE LOWER(?))"
        params.extend([f"%{search}%", f"%{search}%"])

    with get_db() as conn:
        return conn.execute(query, params).fetchone()[0]


def get_queue(project_id):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM videos WHERE project_id = ? AND status IN ('queued', 'downloading') ORDER BY id ASC",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def requeue_downloading(project_id):
    with get_db() as conn:
        conn.execute(
            "UPDATE videos SET status = 'queued' WHERE project_id = ? AND status = 'downloading'",
            (project_id,),
        )


def delete_video(video_id):
    with get_db() as conn:
        conn.execute("DELETE FROM videos WHERE id = ?", (video_id,))


def toggle_favorite(video_id):
    with get_db() as conn:
        row = conn.execute("SELECT favorite FROM videos WHERE id = ?", (video_id,)).fetchone()
        if row:
            new_val = 0 if row["favorite"] else 1
            conn.execute("UPDATE videos SET favorite = ? WHERE id = ?", (new_val, video_id))
            return new_val
    return None


def delete_videos_before_date(project_id, date_str):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, filepath FROM videos WHERE project_id = ? AND downloaded_at < ?",
            (project_id, date_str),
        ).fetchall()
        deleted = 0
        for row in rows:
            if row["filepath"] and os.path.exists(row["filepath"]):
                try:
                    os.remove(row["filepath"])
                except OSError:
                    pass
            conn.execute("DELETE FROM videos WHERE id = ?", (row["id"],))
            deleted += 1
        return deleted


def delete_videos_by_status(project_id, status):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, filepath FROM videos WHERE project_id = ? AND status = ?",
            (project_id, status),
        ).fetchall()
        deleted = 0
        for row in rows:
            if row["filepath"] and os.path.exists(row["filepath"]):
                try:
                    os.remove(row["filepath"])
                except OSError:
                    pass
            conn.execute("DELETE FROM videos WHERE id = ?", (row["id"],))
            deleted += 1
        return deleted


def reset_project(project_id):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, filepath FROM videos WHERE project_id = ?", (project_id,)
        ).fetchall()
        deleted = 0
        for row in rows:
            if row["filepath"] and os.path.exists(row["filepath"]):
                try:
                    os.remove(row["filepath"])
                except OSError:
                    pass
            conn.execute("DELETE FROM videos WHERE id = ?", (row["id"],))
            deleted += 1
        return deleted


def get_project_stats(project_id):
    with get_db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM videos WHERE project_id = ?", (project_id,)
        ).fetchone()[0]
        favorites = conn.execute(
            "SELECT COUNT(*) FROM videos WHERE project_id = ? AND favorite = 1", (project_id,)
        ).fetchone()[0]
        completed = conn.execute(
            "SELECT COUNT(*) FROM videos WHERE project_id = ? AND status = 'completed'",
            (project_id,),
        ).fetchone()[0]
        failed = conn.execute(
            "SELECT COUNT(*) FROM videos WHERE project_id = ? AND status = 'failed'", (project_id,)
        ).fetchone()[0]
        total_size = conn.execute(
            "SELECT COALESCE(SUM(filesize), 0) FROM videos WHERE project_id = ?", (project_id,)
        ).fetchone()[0]
        return {
            "total": total,
            "favorites": favorites,
            "completed": completed,
            "failed": failed,
            "total_size": total_size,
        }


def get_all_tags():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM tags ORDER BY name").fetchall()
        return [dict(r) for r in rows]


def create_tag(name):
    name = name.strip().lower()
    if not name:
        return None
    with get_db() as conn:
        try:
            cursor = conn.execute("INSERT INTO tags (name) VALUES (?)", (name,))
            return {"id": cursor.lastrowid, "name": name}
        except get_integrity_error():
            row = conn.execute("SELECT * FROM tags WHERE name = ?", (name,)).fetchone()
            return dict(row) if row else None


def delete_tag(tag_id):
    with get_db() as conn:
        conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))


def add_video_tag(video_id, tag_id):
    with get_db() as conn:
        try:
            conn.execute(
                "INSERT INTO video_tags (video_id, tag_id) VALUES (?, ?)", (video_id, tag_id)
            )
        except get_integrity_error():
            pass


def remove_video_tag(video_id, tag_id):
    with get_db() as conn:
        conn.execute("DELETE FROM video_tags WHERE video_id = ? AND tag_id = ?", (video_id, tag_id))


def get_video_tags(video_id):
    with get_db() as conn:
        rows = conn.execute(
            """SELECT t.* FROM tags t
               JOIN video_tags vt ON t.id = vt.tag_id
               WHERE vt.video_id = ?
               ORDER BY t.name""",
            (video_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_video_tags_bulk(video_ids):
    if not video_ids:
        return {}
    placeholders = ", ".join("?" for _ in video_ids)
    with get_db() as conn:
        rows = conn.execute(
            f"""SELECT vt.video_id AS video_id, t.id AS id, t.name AS name
                FROM video_tags vt
                JOIN tags t ON t.id = vt.tag_id
                WHERE vt.video_id IN ({placeholders})
                ORDER BY t.name""",
            video_ids,
        ).fetchall()
        out = {}
        for r in rows:
            vid = r["video_id"]
            out.setdefault(vid, []).append({"id": r["id"], "name": r["name"]})
        return out


def get_distinct_values(project_id, column):
    if column not in {"orientation", "length_category", "aspect_ratio", "custom_category"}:
        return []
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT DISTINCT {column} FROM videos WHERE project_id = ? AND {column} != '' ORDER BY {column}",
            (project_id,),
        ).fetchall()
        return [r[0] for r in rows]


def get_all_categories(project_id):
    return get_distinct_values(project_id, "custom_category")


def bulk_update_category(video_ids, category):
    if not video_ids:
        return 0
    placeholders = ", ".join("?" for _ in video_ids)
    with get_db() as conn:
        cursor = conn.execute(
            f"UPDATE videos SET custom_category = ? WHERE id IN ({placeholders})",
            [category] + list(video_ids),
        )
        return cursor.rowcount


def bulk_add_tag(video_ids, tag_name):
    if not video_ids:
        return 0
    tag = create_tag(tag_name)
    if not tag:
        return 0
    tag_id = tag["id"]
    added = 0
    with get_db() as conn:
        for vid in video_ids:
            try:
                conn.execute(
                    "INSERT INTO video_tags (video_id, tag_id) VALUES (?, ?)", (vid, tag_id)
                )
                added += 1
            except get_integrity_error():
                pass
    return added


def bulk_delete_videos(video_ids):
    if not video_ids:
        return 0
    placeholders = ", ".join("?" for _ in video_ids)
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT id, filepath FROM videos WHERE id IN ({placeholders})", list(video_ids)
        ).fetchall()
        deleted = 0
        for row in rows:
            if row["filepath"] and os.path.exists(row["filepath"]):
                try:
                    os.remove(row["filepath"])
                except OSError:
                    pass
            conn.execute("DELETE FROM videos WHERE id = ?", (row["id"],))
            deleted += 1
        return deleted


def bulk_move_project(video_ids, target_project_id):
    if not video_ids:
        return 0

    target_project = get_project(target_project_id)
    if not target_project:
        return 0

    target_folder = os.path.join(config.VIDEO_DIR, target_project["folder"])
    os.makedirs(target_folder, exist_ok=True)

    placeholders = ", ".join("?" for _ in video_ids)
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT id, filepath FROM videos WHERE id IN ({placeholders})", list(video_ids)
        ).fetchall()

        moved = 0
        for row in rows:
            old_path = row["filepath"]
            new_path = old_path

            if old_path and os.path.exists(old_path):
                filename = os.path.basename(old_path)
                new_path = os.path.join(target_folder, filename)
                try:
                    shutil.move(old_path, new_path)
                except Exception:
                    # If move fails, skip updating DB so they remain consistent
                    continue

            conn.execute(
                "UPDATE videos SET project_id = ?, filepath = ? WHERE id = ?",
                (target_project_id, new_path, row["id"]),
            )
            moved += 1

        return moved
