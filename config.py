import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATABASE_PATH = os.getenv("BULK_VIDEO_DB_PATH", os.path.join(BASE_DIR, "bulk_video.db"))
DATABASE_URL = os.getenv("BULK_VIDEO_DB_URL")  # e.g. mysql+pymysql://user:pass@host:3306/db

# Classic DB setup alternative
DB_HOST = os.getenv("BULK_VIDEO_DB_HOST")
DB_PORT = os.getenv("BULK_VIDEO_DB_PORT", "3306")
DB_USER = os.getenv("BULK_VIDEO_DB_USER", "")
DB_PASSWORD = os.getenv("BULK_VIDEO_DB_PASSWORD", "")
DB_NAME = os.getenv("BULK_VIDEO_DB_NAME", "")
DB_TYPE = os.getenv("BULK_VIDEO_DB_TYPE", "mysql").lower()

if not DATABASE_URL and DB_HOST and DB_NAME:
    user_pass = DB_USER
    if DB_PASSWORD:
        user_pass += f":{DB_PASSWORD}"
    if user_pass:
        user_pass += "@"

    if DB_TYPE in ("postgres", "postgresql", "pg"):
        DATABASE_URL = f"postgresql+psycopg2://{user_pass}{DB_HOST}:{DB_PORT}/{DB_NAME}"
    else:
        DATABASE_URL = f"mysql+pymysql://{user_pass}{DB_HOST}:{DB_PORT}/{DB_NAME}"

USERNAME = os.getenv("BULK_VIDEO_USERNAME")
PASSWORD = os.getenv("BULK_VIDEO_PASSWORD")

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

# i18n
LANGUAGES = ["tr", "en"]
BABEL_DEFAULT_LOCALE = os.getenv("BULK_VIDEO_LANG", "tr")
BABEL_TRANSLATION_DIRECTORIES = os.path.join(BASE_DIR, "translations")

# Storage limit in MB
_storage_max_str = os.getenv("BULK_VIDEO_STORAGE_MAX_MB")
STORAGE_MAX_MB = int(_storage_max_str) if _storage_max_str and _storage_max_str.isdigit() else None
