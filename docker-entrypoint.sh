#!/usr/bin/env sh
set -eu

if [ -n "${PORT:-}" ] && [ -z "${BULK_VIDEO_PORT:-}" ]; then
  export BULK_VIDEO_PORT="$PORT"
fi

if [ -z "${BULK_VIDEO_HOST:-}" ]; then
  export BULK_VIDEO_HOST="0.0.0.0"
fi

if [ -z "${BULK_VIDEO_DB_PATH:-}" ]; then
  export BULK_VIDEO_DB_PATH="/data/bulk_video.db"
fi

if [ -z "${BULK_VIDEO_VIDEO_DIR:-}" ]; then
  export BULK_VIDEO_VIDEO_DIR="/data/videos"
fi

debug_val="$(printf "%s" "${BULK_VIDEO_DEBUG:-0}" | tr '[:upper:]' '[:lower:]')"
debug_on=0
case "$debug_val" in
  1|true|yes|on) debug_on=1 ;;
esac

if [ "$debug_on" -eq 0 ] && [ -z "${SECRET_KEY:-}" ]; then
  export SECRET_KEY="$(python -c "import secrets; print(secrets.token_urlsafe(32))")"
fi

exec "$@"
