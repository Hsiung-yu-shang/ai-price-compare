#!/usr/bin/env bash
# 單機 LXC 安裝／更新：Vue build + FastAPI + SQLite + systemd timer
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ai-price-compare}"
APP_USER="${APP_USER:-aiprice}"
APP_PORT="${APP_PORT:-18080}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "$(id -u)" -ne 0 ]; then
  echo "請使用 root 執行：sudo bash deploy/install.sh"
  exit 1
fi

install_packages() {
  if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y ca-certificates curl git rsync python3 python3-pip python3-venv nodejs npm
  elif command -v dnf >/dev/null 2>&1; then
    dnf module reset -y nodejs >/dev/null 2>&1 || true
    dnf module enable -y nodejs:20 >/dev/null 2>&1 || dnf module enable -y nodejs:18 >/dev/null 2>&1 || true
    dnf install -y ca-certificates curl git rsync python3 python3-pip nodejs npm
  else
    echo "僅支援 Debian/Ubuntu (apt) 或 Alma/Rocky (dnf)。"
    exit 1
  fi
}

echo "[1/7] 安裝系統套件"
install_packages

echo "[2/7] 建立服務帳號與目錄"
if ! id "$APP_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi
mkdir -p "$APP_DIR" "$APP_DIR/data" "$APP_DIR/logs"

FIRST_INSTALL=0
if [ ! -f "$APP_DIR/data/pricing.db" ]; then
  FIRST_INSTALL=1
fi

echo "[3/7] 同步應用程式"
rsync -a --delete \
  --exclude='.git/' \
  --exclude='.DS_Store' \
  --exclude='venv/' \
  --exclude='frontend/node_modules/' \
  --exclude='frontend/dist/' \
  --exclude='data/pricing.db' \
  --exclude='data/*.db-wal' \
  --exclude='data/*.db-shm' \
  --exclude='logs/*.log' \
  "$SOURCE_DIR/" "$APP_DIR/"

# 第一次部署帶入 repo 的公開價格快照；更新時絕不覆蓋正式 DB。
if [ "$FIRST_INSTALL" -eq 1 ] && [ -f "$SOURCE_DIR/data/pricing.db" ]; then
  install -m 0640 "$SOURCE_DIR/data/pricing.db" "$APP_DIR/data/pricing.db"
fi

echo "[4/7] 建立 Python 環境"
if command -v python3.11 >/dev/null 2>&1; then
  PYTHON_BIN=python3.11
elif command -v python3.9 >/dev/null 2>&1; then
  PYTHON_BIN=python3.9
else
  PYTHON_BIN=python3
fi

if ! "$PYTHON_BIN" -m venv "$APP_DIR/venv"; then
  "$PYTHON_BIN" -m pip install --upgrade virtualenv
  "$PYTHON_BIN" -m virtualenv "$APP_DIR/venv"
fi
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "[5/7] 建置 Vue 前端"
cd "$APP_DIR/frontend"
NODE_MAJOR="$(node -p 'process.versions.node.split(`.`)[0]')"
if [ "$NODE_MAJOR" -lt 18 ]; then
  echo "Node.js 版本過舊（目前 $(node --version)，需要 18 以上）。"
  exit 1
fi
npm ci
npm run build

echo "[6/7] 安裝 systemd 服務"
if [ -f /etc/ai-price-compare.env ]; then
  ADMIN_TOKEN="$(sed -n 's/^CRAWLER_ADMIN_TOKEN=//p' /etc/ai-price-compare.env | head -n 1)"
fi
if [ -z "${ADMIN_TOKEN:-}" ]; then
  ADMIN_TOKEN="$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')"
fi
cat > /etc/ai-price-compare.env <<EOF
DB_URL=sqlite:///$APP_DIR/data/pricing.db
APP_PORT=$APP_PORT
CRAWLER_ADMIN_TOKEN=$ADMIN_TOKEN
EOF
chmod 0640 /etc/ai-price-compare.env
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

install -m 0644 "$APP_DIR/deploy/ai-price-compare.service" /etc/systemd/system/ai-price-compare.service
install -m 0644 "$APP_DIR/deploy/ai-price-compare-crawler.service" /etc/systemd/system/ai-price-compare-crawler.service
install -m 0644 "$APP_DIR/deploy/ai-price-compare-crawler.timer" /etc/systemd/system/ai-price-compare-crawler.timer

systemctl daemon-reload
systemctl enable --now ai-price-compare.service
systemctl enable --now ai-price-compare-crawler.timer

echo "[7/7] 驗證服務"
for attempt in $(seq 1 20); do
  if curl --fail --silent "http://127.0.0.1:$APP_PORT/api/health" >/dev/null; then
    LXC_IP="$(hostname -I | awk '{print $1}')"
    echo "安裝完成：http://$LXC_IP:$APP_PORT"
    echo "API 文件：http://$LXC_IP:$APP_PORT/docs"
    systemctl --no-block start ai-price-compare-crawler.service || true
    exit 0
  fi
  sleep 1
done

echo "服務未在預期時間內啟動，最近日誌如下："
journalctl -u ai-price-compare.service -n 50 --no-pager
exit 1
