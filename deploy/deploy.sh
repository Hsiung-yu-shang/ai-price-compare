#!/usr/bin/env bash
# 相容舊指令；新版單機部署統一交由 install.sh 處理。
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/install.sh"
