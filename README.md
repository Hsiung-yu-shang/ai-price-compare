# AI Price Compare

自動整理 ChatGPT、Claude、Gemini 與 Perplexity 的訂閱方案，提供跨平台比價、年繳換算與價格歷史。

正式部署採用單機架構，適合小型 LXC：

```text
瀏覽器 ── HTTP :18080 ── FastAPI
                         ├── /          Vue 靜態前端
                         ├── /api/*     REST API
                         └── SQLite     data/pricing.db
                                      ↑
                              systemd 每日執行爬蟲
```

不需要 MySQL、Nginx、Docker 或常駐的 Node.js 服務。Node.js 只在安裝時負責建置 Vue。

## 一行部署到全新 LXC

支援 Debian 12+、Ubuntu 24.04+、AlmaLinux 9+ 與 Rocky Linux 9+；LXC 需使用 systemd 並可連線到網際網路。

把下方的 GitHub URL 換成你的 repository：

```bash
git clone https://github.com/YOUR_ACCOUNT/ai-price-compare.git /tmp/ai-price-compare && sudo bash /tmp/ai-price-compare/deploy/install.sh
```

安裝腳本會自動：

1. 安裝 Python、Node.js、Git 與 rsync。
2. 將應用同步到 `/opt/ai-price-compare`。
3. 建立 Python virtualenv 並安裝依賴。
4. 建置 Vue 前端。
5. 建立獨立的建置帳號與執行帳號；執行帳號只能寫入資料庫與日誌。
6. 啟用 FastAPI systemd 服務與每日爬蟲 timer。
7. 驗證 `/api/health` 後顯示網站網址。

預設入口：

- 網站：`http://LXC_IP:18080`
- 健康檢查：`http://LXC_IP:18080/api/health`

自訂連接埠：

```bash
sudo APP_PORT=8080 bash deploy/install.sh
```

重跑同一支腳本即可更新程式；正式環境的 `data/pricing.db` 與 `logs/` 不會被覆蓋。

## Cloudflare Tunnel

Tunnel 只需要指向同一個服務：

```text
http://LXC_IP:18080
```

前端使用相對路徑 `/api`，不需要另外建立 API 子網域，也不需要重新編譯網域名稱。

## 服務管理

```bash
sudo systemctl status ai-price-compare
sudo journalctl -u ai-price-compare -f

sudo systemctl status ai-price-compare-crawler.timer
sudo systemctl start ai-price-compare-crawler.service
sudo journalctl -u ai-price-compare-crawler.service -n 100 --no-pager
```

每日爬蟲預設於伺服器時間 04:15 執行，並加入最多 30 分鐘的隨機延遲。
公開網站與 API 都無法啟動爬蟲；管理者透過上面的 systemd 指令手動執行。

## 防濫用設定

應用本身限制每個連線來源每分鐘最多 120 次、全站每分鐘最多 600 次請求，同時處理最多 32 個請求。超過速率回應 `429`，超過並發回應 `503`。這些計數只使用連線來源，不信任客戶端自行傳送的 IP 標頭。若 Tunnel 在同一台主機，應用看到的來源可能都是本機位址，因此每來源額度會由所有訪客共用。systemd 也限制服務的 CPU、記憶體及可寫目錄。這些限制保護 LXC 資源，但大量攻擊流量仍應由入口層處理。

若透過 Cloudflare Tunnel 對外，請在 Cloudflare 的「Security rules → Rate limiting rules」為 `/api/` 設定依訪客 IP 計數的規則，例如每分鐘 60 次後封鎖 10 分鐘。正式網域也應只透過 Tunnel 進入；在防火牆或 LXC 網路設定限制外部直接連到 `18080`。若 Tunnel 與應用在同一台 LXC，可讓 Tunnel 連 `http://127.0.0.1:18080`，再用區域網路規則限制其他來源。Cloudflare 方案可用的條件與處置方式可能不同，請依控制台提供的選項設定。

互動式 API 文件預設關閉。本機需要文件時可用 `ENABLE_API_DOCS=1 python3 -m uvicorn api.main:app --port 8000`；勿在公開服務啟用。

## 本機開發

後端：

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 -m uvicorn api.main:app --reload --port 8000
```

前端：

```bash
cd frontend
npm ci
npm run dev
```

Vite 會把 `/api` 代理到 `http://127.0.0.1:8000`。

若要測試正式整合模式：

```bash
cd frontend && npm ci && npm run build && cd ..
python3 -m uvicorn api.main:app --port 8000
```

開啟 `http://127.0.0.1:8000` 即可同時測試前端與 API。

## 專案結構

```text
api/            FastAPI 路由與回傳 schema
crawlers/       四個平台的價格爬蟲
storage/        SQLAlchemy model、SQLite 連線、價格 diff
config/         平台與方案分級設定
frontend/       Vue 3 + Vite + Tailwind CSS
scripts/        手動爬蟲與 smoke test
deploy/         單機安裝、systemd service 與 timer
data/           初始公開價格快照；正式 DB 會在 LXC 持續更新
```

## API

| 方法 | 路徑 | 用途 |
|---|---|---|
| `GET` | `/api/health` | 服務健康檢查 |
| `GET` | `/api/platforms` | 平台列表 |
| `GET` | `/api/plans` | 方案列表與篩選 |
| `GET` | `/api/compare` | 跨平台比價矩陣 |
| `GET` | `/api/plans/{id}/history` | 價格歷史 |

定價端點與官方頁面格式可能隨時變動。爬蟲失敗時不會覆寫既有方案，但部分平台具有明確標示的靜態備援價格；正式資料仍應以各平台結帳頁為準。
