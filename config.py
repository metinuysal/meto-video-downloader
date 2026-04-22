import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATABASE_PATH = os.getenv("BULK_VIDEO_DB_PATH", os.path.join(BASE_DIR, "bulk_video.db"))
VIDEO_DIR = os.getenv("BULK_VIDEO_VIDEO_DIR", os.path.join(BASE_DIR, "videos"))

os.makedirs(VIDEO_DIR, exist_ok=True)

def _get_env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


HOST = os.getenv("BULK_VIDEO_HOST", "127.0.0.1")
PORT = int(os.getenv("BULK_VIDEO_PORT") or os.getenv("PORT") or "5000")
DEBUG = _get_env_bool("BULK_VIDEO_DEBUG", False)

POLL_INTERVAL_MS = 2000
