#!/usr/bin/env sh
set -eu

# Tak-Çalıştır: container root olarak başlar, /data bind mount perms'i host'tan geldiği için düzelt
# ve sonra appuser'a düşür. Böylece sunucuda chmod/chown unutulsa bile çalışır.
if [ "$(id -u)" = "0" ]; then
  mkdir -p "${BULK_VIDEO_VIDEO_DIR:-/data/videos}" /data 2>/dev/null || true
  chown -R appuser:appuser /data /app 2>/dev/null || true
  chmod -R u+rwX /data 2>/dev/null || true
  if command -v gosu >/dev/null 2>&1; then
    exec gosu appuser sh "$0" "$@"
  elif command -v runuser >/dev/null 2>&1; then
    exec runuser -u appuser -- sh "$0" "$@"
  elif command -v su >/dev/null 2>&1; then
    exec su appuser -s /bin/sh -c 'exec sh "$0" "$@"' -- "$0" "$@"
  else
    : # drop aracı yoksa root olarak devam et (tak-çalıştır garantisi)
  fi
fi

if [ -n "${PORT:-}" ]; then
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

# MySQL healthy olsa bile uygulama başlamadan önce DB'nin gerçekten hazır olmasını bekle
# (compose healthcheck + bu bekleme = race condition yok)
if [ -n "${BULK_VIDEO_DB_URL:-}" ]; then
  case "$BULK_VIDEO_DB_URL" in
    mysql*|*mysql*)
      echo "MySQL bekleniyor: $BULK_VIDEO_DB_URL (host db)..."
      for i in $(seq 1 30); do
        if python -c "import os, pymysql; from urllib.parse import urlparse; u=urlparse(os.getenv('BULK_VIDEO_DB_URL')); pymysql.connect(host=u.hostname, user=u.username, password=u.password, database=u.path.lstrip('/'), port=u.port or 3306, connect_timeout=2).close()" 2>/dev/null; then
          echo "MySQL hazır."
          break
        fi
        echo "  MySQL henüz hazır değil, yeniden denenecek ($i/30)..."
        sleep 2
      done
      ;;
  esac
fi

exec "$@"
