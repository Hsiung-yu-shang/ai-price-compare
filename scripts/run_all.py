"""
排程主入口: 依序執行所有爬蟲 → 儲存結果到 DB → 印出摘要
用法:
    python scripts/run_all.py              # 跑所有平台 (預設 TW)
    python scripts/run_all.py --country US # 指定國家
"""
import argparse
import importlib
import logging
import sys
import time
from pathlib import Path

# 將專案根目錄加入 sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from config.settings import LOGS_DIR
from config.platform_config import PLATFORMS
from storage import save_crawl_results, init_db

# Logging: console + file
log_file = LOGS_DIR / "run_all.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_file, encoding="utf-8"),
    ]
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="AI 平台比價爬蟲 — 排程主入口")
    parser.add_argument("--country", default="TW", help="目標國家代碼 (預設: TW)")
    args = parser.parse_args()
    country = args.country.upper()

    logger.info(f"{'=' * 60}")
    logger.info(f"開始執行全平台爬蟲 (國家: {country})")
    logger.info(f"{'=' * 60}")

    init_db()

    crawlers_module = importlib.import_module("crawlers")
    total_start = time.time()
    results_summary = []

    for platform_id, cfg in PLATFORMS.items():
        class_name = cfg.get("crawler_module")
        if not class_name or not hasattr(crawlers_module, class_name):
            logger.warning(f"[{platform_id}] 找不到爬蟲 '{class_name}'，略過")
            continue

        logger.info(f"\n--- {platform_id} ---")
        start = time.time()

        try:
            crawler_cls = getattr(crawlers_module, class_name)
            result = crawler_cls(country_code=country).run()
            crawl_duration = time.time() - start

            summary = save_crawl_results(result)
            results_summary.append({
                "platform": platform_id,
                "status": "✅ success" if result["status"] == "success" else "⚠️ partial",
                "plans": len(result.get("plans", [])),
                "new": summary.get("new_plans", 0),
                "price_changed": summary.get("price_changed", 0),
                "duration": f"{crawl_duration:.1f}s",
            })
        except Exception as exc:
            logger.error(f"[{platform_id}] 爬蟲失敗: {exc}", exc_info=True)
            results_summary.append({
                "platform": platform_id,
                "status": "❌ failed",
                "plans": 0, "new": 0, "price_changed": 0,
                "duration": f"{time.time() - start:.1f}s",
                "error": str(exc)[:60],
            })

    total_duration = time.time() - total_start

    print(f"\n{'=' * 70}")
    print(f"  執行摘要 (總耗時: {total_duration:.1f}s)")
    print(f"{'=' * 70}")
    print(f"  {'平台':<12} {'狀態':<14} {'方案數':>6} {'新增':>6} {'價格變動':>8} {'耗時':>8}")
    print(f"  {'-' * 62}")
    for r in results_summary:
        print(
            f"  {r['platform']:<12} {r['status']:<14} {r['plans']:>6} "
            f"{r['new']:>6} {r['price_changed']:>8} {r['duration']:>8}"
        )
        if "error" in r:
            print(f"    └─ 錯誤: {r['error']}")
    print(f"{'=' * 70}")

    # 有失敗的平台時以非零退出碼結束，方便 cron 偵測
    if any(r["status"] == "❌ failed" for r in results_summary):
        sys.exit(1)


if __name__ == "__main__":
    main()
