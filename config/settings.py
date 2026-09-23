"""
全域設定檔
"""
__all__ = [
    "BASE_DIR", "DEFAULT_HEADERS", "REQUEST_TIMEOUT", "MAX_RETRIES",
    "SUPPORTED_COUNTRIES", "LOGS_DIR", "DATA_DIR", "DB_URL",
    "ENABLE_API_DOCS",
]
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# 爬蟲設定
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}

REQUEST_TIMEOUT = 15
MAX_RETRIES = 3

# 支援的目標國家/地區代碼
SUPPORTED_COUNTRIES = ["TW", "US"]

# 紀錄檔設定
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# 資料庫設定
# 本機與單機 LXC 都使用 SQLite；正式環境以 DB_URL 指向 /opt 下的持久化檔案。
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_URL = os.getenv(
    "DB_URL",
    f"sqlite:///{DATA_DIR / 'pricing.db'}",
)

# 公開服務預設關閉互動式文件；本機需要時可設 ENABLE_API_DOCS=1。
ENABLE_API_DOCS = os.getenv("ENABLE_API_DOCS", "0") == "1"
