#!/usr/bin/env bash
# 單機 LXC 安裝／更新：Vue build + FastAPI + SQLite + systemd timer
set -euo pipefail

APP_DIR="/opt/ai-price-compare"
APP_USER="aiprice"
BUILD_USER="aipricebuild"
APP_PORT="${APP_PORT:-18080}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "$(id -u)" -ne 0 ]; then
  echo "請使用 root 執行：sudo bash deploy/install.sh"
  exit 1
fi
if ! [[ "$APP_PORT" =~ ^[0-9]+$ ]] || [ "$APP_PORT" -lt 1024 ] || [ "$APP_PORT" -gt 65535 ]; then
  echo "APP_PORT 必須介於 1024 到 65535。"
  exit 1
fi

install_packages() {
  if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y ca-certificates curl git rsync util-linux python3 python3-pip python3-venv nodejs npm
  elif command -v dnf >/dev/null 2>&1; then
    dnf module reset -y nodejs >/dev/null 2>&1 || true
    dnf module enable -y nodejs:20 >/dev/null 2>&1 || dnf module enable -y nodejs:18 >/dev/null 2>&1 || true
    dnf install -y ca-certificates curl git rsync util-linux python3 python3-pip nodejs npm
  else
    echo "僅支援 Debian/Ubuntu (apt) 或 Alma/Rocky (dnf)。"
    exit 1
  fi
}

echo "[1/7] 安裝系統套件"
install_packages

echo "[2/7] 建立服務帳號與目錄"
if ! getent group "$APP_USER" >/dev/null; then
  groupadd --system "$APP_USER"
fi
if ! id "$APP_USER" >/dev/null 2>&1; then
  useradd --system --gid "$APP_USER" --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi
if ! getent group "$BUILD_USER" >/dev/null; then
  groupadd --system "$BUILD_USER"
fi
if ! id "$BUILD_USER" >/dev/null 2>&1; then
  useradd --system --gid "$BUILD_USER" --create-home --home-dir /var/lib/ai-price-compare-build --shell /usr/sbin/nologin "$BUILD_USER"
fi
if [ -L "$APP_DIR" ] || [ -L "$APP_DIR/data" ] || [ -L "$APP_DIR/logs" ] || [ -L "$APP_DIR/data/pricing.db" ]; then
  echo "應用或資料路徑含符號連結，為避免覆寫其他檔案，已停止安裝。"
  exit 1
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
  --exclude='data/' \
  --exclude='logs/' \
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

mkdir -p "$APP_DIR/venv"
chown -R "$BUILD_USER:$BUILD_USER" "$APP_DIR/venv" "$APP_DIR/frontend"
runuser -u "$BUILD_USER" -- "$PYTHON_BIN" -m venv "$APP_DIR/venv"
runuser -u "$BUILD_USER" -- "$APP_DIR/venv/bin/pip" install --upgrade pip
runuser -u "$BUILD_USER" -- "$APP_DIR/venv/bin/pip" install --upgrade -r "$APP_DIR/requirements.txt"

echo "[5/7] 建置 Vue 前端"
cd "$APP_DIR/frontend"
NODE_MAJOR="$(node -p 'process.versions.node.split(`.`)[0]')"
if [ "$NODE_MAJOR" -lt 18 ]; then
  echo "Node.js 版本過舊（目前 $(node --version)，需要 18 以上）。"
  exit 1
fi
runuser -u "$BUILD_USER" -- npm ci
runuser -u "$BUILD_USER" -- npm run build

echo "[6/7] 安裝 systemd 服務"
cat > /etc/ai-price-compare.env <<EOF
DB_URL=sqlite:///$APP_DIR/data/pricing.db
APP_PORT=$APP_PORT
ENABLE_API_DOCS=0
EOF
chmod 0644 /etc/ai-price-compare.env
# 程式與依賴由 root 持有；服務只能修改資料庫與日誌。
chown -R root:root "$APP_DIR"
chown -R "$APP_USER:$APP_USER" "$APP_DIR/data" "$APP_DIR/logs"
chmod 0750 "$APP_DIR/data" "$APP_DIR/logs"
if [ -f "$APP_DIR/data/pricing.db" ]; then
  chmod 0640 "$APP_DIR/data/pricing.db"
fi

install -m 0644 "$APP_DIR/deploy/ai-price-compare.service" /etc/systemd/system/ai-price-compare.service
install -m 0644 "$APP_DIR/deploy/ai-price-compare-crawler.service" /etc/systemd/system/ai-price-compare-crawler.service
install -m 0644 "$APP_DIR/deploy/ai-price-compare-crawler.timer" /etc/systemd/system/ai-price-compare-crawler.timer

systemctl daemon-reload
systemctl enable ai-price-compare.service
systemctl restart ai-price-compare.service
systemctl enable --now ai-price-compare-crawler.timer

echo "[7/7] 驗證服務"
for attempt in $(seq 1 20); do
  if curl --fail --silent "http://127.0.0.1:$APP_PORT/api/health" >/dev/null \
      && curl --fail --silent "http://127.0.0.1:$APP_PORT/" | grep -q '<div id="app"></div>'; then
    LXC_IP="$(hostname -I | awk '{print $1}')"
    echo "安裝完成：http://$LXC_IP:$APP_PORT"
    systemctl --no-block start ai-price-compare-crawler.service || true
    exit 0
  fi
  sleep 1
done

echo "服務未在預期時間內啟動，最近日誌如下："
journalctl -u ai-price-compare.service -n 50 --no-pager
exit 1
