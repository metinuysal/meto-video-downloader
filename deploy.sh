#!/usr/bin/env bash
set -e

# METO Bulk Video Downloader - Tak-Çalıştır Deploy
# Kullanım:
#   chmod +x deploy.sh
#   ./deploy.sh              # kur + başlat (tek komut)
#   ./deploy.sh logs         # log izle
#   ./deploy.sh ps           # durum
#   ./deploy.sh down         # durdur
#   ./deploy.sh update       # git pull + rebuild
#   ./deploy.sh clean        # her şeyi sil (volume dahil - DİKKAT)

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[HATA]${NC} $*"; }

check_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    error "Docker bulunamadı. Önce Docker kur:"
    echo "  Ubuntu/Debian: curl -fsSL https://get.docker.com | sh"
    echo "  Sonra: sudo usermod -aG docker \$USER && newgrp docker"
    exit 1
  fi
  if ! docker compose version >/dev/null 2>&1; then
    error "docker compose plugin bulunamadı (docker-compose değil, 'docker compose')."
    echo "  https://docs.docker.com/compose/install/"
    exit 1
  fi
}

gen_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    python3 -c "import secrets; print(secrets.token_hex(32))"
  fi
}

gen_pass() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 16
  else
    python3 -c "import secrets; print(secrets.token_hex(16))"
  fi
}

ensure_env() {
  if [ -f .env ]; then
    info ".env zaten var -> korunuyor"
    return
  fi
  info ".env oluşturuluyor (tak-çalıştır varsayılanları)..."
  if [ -f .env.example ]; then
    cp .env.example .env
  else
    cat > .env <<'ENVEOF'
PORT=5000
BULK_VIDEO_DEBUG=0
SECRET_KEY=replace-me
MYSQL_ROOT_PASSWORD=rootsecret
MYSQL_DATABASE=bulk_video
MYSQL_USER=bulkuser
MYSQL_PASSWORD=bulkpass
ENVEOF
  fi

  # Güçlü rastgele değerler üret ve yerleştir
  SECRET=$(gen_secret)
  # SECRET_KEY her zaman rastgele (MySQL volume'dan bağımsız)
  if grep -q "SECRET_KEY=" .env; then
    sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$SECRET/" .env
  else
    echo "SECRET_KEY=$SECRET" >> .env
  fi

  # MySQL şifreleri: mevcut volume varsa rastgele üretme (bağlantı kopar), varsayılanda bırak
  if docker volume ls --format '{{.Name}}' 2>/dev/null | grep -q "mysql_data"; then
    warn "Mevcut MySQL volume bulundu -> .env MySQL şifreleri varsayılanda bırakılıyor (rootsecret/bulkpass)."
    warn "Sıfırdan rastgele şifre istersen: ./deploy.sh clean && ./deploy.sh"
  else
    ROOTPASS=$(gen_pass)
    DBPASS=$(gen_pass)
    if grep -q "MYSQL_ROOT_PASSWORD=" .env; then
      sed -i "s/^MYSQL_ROOT_PASSWORD=.*/MYSQL_ROOT_PASSWORD=$ROOTPASS/" .env
    else
      echo "MYSQL_ROOT_PASSWORD=$ROOTPASS" >> .env
    fi
    if grep -q "^MYSQL_PASSWORD=" .env; then
      sed -i "s/^MYSQL_PASSWORD=.*/MYSQL_PASSWORD=$DBPASS/" .env
    else
      echo "MYSQL_PASSWORD=$DBPASS" >> .env
    fi
  fi

  # PORT ve DEBUG garantisi
  grep -q "^PORT=" .env || echo "PORT=5000" >> .env
  grep -q "BULK_VIDEO_DEBUG" .env || echo "BULK_VIDEO_DEBUG=0" >> .env

  info ".env oluşturuldu:"
  grep -E "^(PORT|MYSQL_|SECRET_KEY|BULK_VIDEO_DEBUG)" .env | sed 's/SECRET_KEY=.*/SECRET_KEY=***hidden***/; s/MYSQL.*PASSWORD=.*/&***hidden***/'
}

ensure_dirs() {
  mkdir -p ./data ./data/videos
  # Host perms'i container appuser (10001) için düzelt - tak-çalıştır garantisi
  # Container entrypoint root olarak chown yapacak ama host'ta da erişim için 777 fallback
  chmod -R 777 ./data 2>/dev/null || true
  chown -R 10001:10001 ./data 2>/dev/null || sudo chown -R 10001:10001 ./data 2>/dev/null || true
}

do_up() {
  check_docker
  ensure_env
  ensure_dirs
  info "İmaj build ediliyor ve servisler başlatılıyor..."
  docker compose up --build -d
  echo ""
  info "Durum:"
  docker compose ps
  echo ""
  # MySQL hazır olana kadar bekle (container_name yok, compose id ile bul)
  info "MySQL sağlık kontrolü bekleniyor..."
  for i in $(seq 1 30); do
    DB_CID=$(docker compose ps -q db 2>/dev/null)
    if [ -n "$DB_CID" ] && docker inspect --format='{{json .State.Health.Status}}' "$DB_CID" 2>/dev/null | grep -q "healthy"; then
      info "MySQL healthy"
      break
    fi
    sleep 2
  done
  echo ""
  info "Uygulama sağlık kontrolü bekleniyor..."
  sleep 5
  docker compose ps
  echo ""
  PORT_VAL=$(grep "^PORT=" .env | cut -d= -f2)
  PORT_VAL=${PORT_VAL:-5000}
  info "Tak-Çalıştır hazır!"
  echo -e "  ${GREEN}http://localhost:${PORT_VAL}${NC}  (sunucuda: http://SUNUCU_IP:${PORT_VAL})"
  echo ""
  echo "  Log izle : ./deploy.sh logs"
  echo "  Durdur   : ./deploy.sh down"
  echo "  Güncelle : ./deploy.sh update"
}

do_logs()  { docker compose logs -f; }
do_ps()    { docker compose ps; docker compose logs --tail=50; }
do_down()  { docker compose down; info "Durduruldu. Veriler saklandı (volume silinmedi)."; }
do_clean() {
  warn "TÜM VERİLER SİLİNECEK (mysql_data volume + ./data) - 5 sn içinde Ctrl+C ile iptal edebilirsin..."
  sleep 5
  docker compose down -v
  rm -rf ./data
  info "Temizlendi."
}
do_update() {
  check_docker
  if [ -d .git ]; then
    info "Git pull..."
    git pull || warn "git pull başarısız - manuel güncelle"
  fi
  ensure_dirs
  docker compose up --build -d
  docker compose ps
}

case "${1:-up}" in
  up|start|"") do_up ;;
  logs|log)     do_logs ;;
  ps|status)    do_ps ;;
  down|stop)    do_down ;;
  clean)        do_clean ;;
  update|upgrade) do_update ;;
  restart)      docker compose restart; docker compose ps ;;
  *)
    echo "Kullanım: $0 [up|logs|ps|down|restart|update|clean]"
    exit 1
    ;;
esac
