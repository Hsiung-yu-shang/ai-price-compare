"""
爬蟲模組快速驗證腳本 (Smoke Test)
直接呼叫真實 API，用於手動確認爬蟲功能正常
非 pytest/unittest 格式，不適合 CI 自動化
"""
import json
import logging
import sys
from pathlib import Path

# 將專案根目錄加入 sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from config.settings import LOGS_DIR
from crawlers import (
    ChatGPTPricingCrawler,
    GeminiPricingCrawler,
    ClaudePricingCrawler,
    PerplexityPricingCrawler,
)

# 設定 logging: 同時輸出到 console 和檔案
log_file = LOGS_DIR / "smoke_test.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_file, encoding="utf-8"),
    ]
)
logger = logging.getLogger(__name__)


def run_tests():
    logger.info(f"日誌同步寫入: {log_file}")

    print("=" * 60)
    print("1. 測試 Gemini (Google One AI) 爬蟲 (TW)")
    print("=" * 60)
    gemini_tw = GeminiPricingCrawler(country_code="TW")
    res_gemini_tw = gemini_tw.run()
    print("Gemini TW 結果狀態:", res_gemini_tw["status"])
    print("方案數量:", len(res_gemini_tw["plans"]))
    for p in res_gemini_tw["plans"]:
        print(f"  - {p['plan_name']} ({p['plan_id']}): {p['currency']} {p['monthly_price']}")

    print("=" * 60)
    print("2. 測試 Claude (Anthropic) 爬蟲")
    print("=" * 60)
    claude = ClaudePricingCrawler(country_code="TW")
    res_claude = claude.run()
    print("Claude 結果狀態:", res_claude["status"])
    print("方案數量:", len(res_claude["plans"]))
    for p in res_claude["plans"]:
        source = p.get("data_source", "unknown")
        suffix = f" ⚠️ [{source}]" if source == "hardcoded_fallback" else ""
        print(
            f"  - {p['plan_name']} ({p['plan_id']}): {p['currency']} {p['monthly_price']} "
            f"(年繳月均: {p.get('annual_monthly_price')}){suffix}"
        )

    print("=" * 60)
    print("3. 測試 ChatGPT 爬蟲 (含容錯狀態檢驗)")
    print("=" * 60)
    chatgpt = ChatGPTPricingCrawler(country_code="TW")
    res_chatgpt = chatgpt.run()
    print("ChatGPT 結果狀態:", res_chatgpt["status"])
    if res_chatgpt["status"] == "success":
        print("方案數量:", len(res_chatgpt["plans"]))
        for p in res_chatgpt["plans"]:
            print(f"  - {p['plan_name']}: {p['currency']} {p['monthly_price']}")
    else:
        print("錯誤訊息 (預期容錯捕捉):", res_chatgpt["error"])

    print("=" * 60)
    print("4. 測試 Perplexity 爬蟲")
    print("=" * 60)
    perplexity = PerplexityPricingCrawler(country_code="TW")
    res_perplexity = perplexity.run()
    print("Perplexity 結果狀態:", res_perplexity["status"])
    print("方案數量:", len(res_perplexity["plans"]))
    for p in res_perplexity["plans"]:
        print(f"  - {p['plan_name']}: {p['currency']} {p['monthly_price']}")

if __name__ == "__main__":
    run_tests()
