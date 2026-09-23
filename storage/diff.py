"""
價格異動偵測 (Diff) 與爬蟲結果寫入
核心邏輯:
1. 接收 Crawler.run() 回傳的結果 dict
2. 與 DB 中現有資料比對，偵測價格變動
3. 新增/更新方案記錄，並在價格變動時寫入 price_history
4. 記錄本次爬蟲執行狀態到 crawl_logs
"""
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from .db import get_session, init_db
from .models import Platform, Plan, PlanFeature, PriceHistory, CrawlLog
from config.platform_config import PLATFORMS

logger = logging.getLogger(__name__)


def save_crawl_results(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    整合入口: 將 Crawler.run() 的結果存入資料庫

    Args:
        result: Crawler.run() 回傳的 dict，包含 platform, status, plans 等

    Returns:
        摘要 dict: {"saved": int, "updated": int, "price_changed": int, "new_plans": int}
    """
    start_time = time.time()
    platform_id_str = result.get("platform", "unknown")
    country_code = result.get("country_code", "TW")
    status = result.get("status", "failed")

    # 確保表已建立
    init_db()

    summary = {"saved": 0, "updated": 0, "price_changed": 0, "new_plans": 0}

    with get_session() as session:
        # 1. 記錄爬蟲執行狀態
        if status != "success":
            _log_crawl(session, platform_id_str, country_code, "failed",
                       error_message=result.get("error"),
                       duration=time.time() - start_time)
            logger.warning(f"[{platform_id_str}] 爬取失敗，僅記錄 crawl_log，不更新方案資料")
            return summary

        plans_data = result.get("plans", [])
        if not plans_data:
            _log_crawl(session, platform_id_str, country_code, "success",
                       plan_count=0, duration=time.time() - start_time)
            return summary

        # 2. 確保 platform 記錄存在
        platform = _upsert_platform(session, platform_id_str)

        # 3. 逐一處理方案
        for plan_data in plans_data:
            result_type = _upsert_plan(session, platform, plan_data, country_code)
            summary["saved"] += 1
            if result_type == "new":
                summary["new_plans"] += 1
            elif result_type == "updated":
                summary["updated"] += 1
            elif result_type == "price_changed":
                summary["price_changed"] += 1
                summary["updated"] += 1

        # 4. 記錄成功的 crawl log
        _log_crawl(session, platform_id_str, country_code, "success",
                   plan_count=len(plans_data),
                   duration=time.time() - start_time)

    logger.info(
        f"[{platform_id_str}] DB 寫入完成: "
        f"共 {summary['saved']} 個方案 "
        f"(新增 {summary['new_plans']}, 價格變動 {summary['price_changed']}, "
        f"無變動 {summary['saved'] - summary['new_plans'] - summary['price_changed']})"
    )
    return summary


def _upsert_platform(session: Session, platform_id_str: str) -> Platform:
    """新增或更新平台記錄"""
    platform = session.query(Platform).filter_by(platform_id=platform_id_str).first()

    platform_cfg = PLATFORMS.get(platform_id_str, {})

    if platform is None:
        platform = Platform(
            platform_id=platform_id_str,
            platform_name=platform_cfg.get("name", platform_id_str),
            vendor=platform_cfg.get("vendor"),
            official_url=platform_cfg.get("official_pricing_url"),
        )
        session.add(platform)
        session.flush()  # 取得 auto-generated ID
        logger.info(f"[{platform_id_str}] 新增平台記錄: {platform.platform_name}")
    else:
        platform.updated_at = datetime.now(timezone.utc)

    return platform


def _upsert_plan(
    session: Session,
    platform: Platform,
    plan_data: Dict[str, Any],
    country_code: str,
) -> str:
    """
    新增或更新方案記錄，偵測價格變動

    Returns:
        "new" / "unchanged" / "price_changed"
    """
    plan_id_str = plan_data["plan_id"]
    now = datetime.now(timezone.utc)

    # 查找現有方案
    existing = (
        session.query(Plan)
        .filter_by(
            platform_id=platform.id,
            plan_id=plan_id_str,
            country_code=country_code,
        )
        .first()
    )

    new_monthly = plan_data.get("monthly_price", 0.0)
    new_annual = plan_data.get("annual_price")
    raw_payload = json.dumps(plan_data.get("raw_payload", {}), ensure_ascii=False)
    plan_type = _infer_plan_type(platform.platform_id, plan_id_str, plan_data)

    if existing is None:
        # ---- 新方案 ----
        plan = Plan(
            platform_id=platform.id,
            plan_id=plan_id_str,
            plan_name=plan_data["plan_name"],
            country_code=country_code,
            monthly_price=new_monthly,
            annual_price=new_annual,
            annual_monthly_price=plan_data.get("annual_monthly_price"),
            currency=plan_data.get("currency", "USD"),
            billing_cycle=plan_data.get("billing_cycle", "monthly"),
            tax_mode=plan_data.get("tax_mode", "unknown"),
            data_source=plan_data.get("data_source", "parsed"),
            plan_type=plan_type,
            raw_payload=raw_payload,
            fetched_at=now,
        )
        session.add(plan)
        session.flush()

        # 寫入 features
        _sync_features(session, plan, plan_data.get("features", []))

        # 記錄歷史: 新方案
        session.add(PriceHistory(
            plan_id=plan.id,
            old_monthly_price=None,
            new_monthly_price=new_monthly,
            old_annual_price=None,
            new_annual_price=new_annual,
            change_type="new_plan",
        ))
        logger.info(f"  新增方案: {plan_id_str} ({plan_data['plan_name']})")
        return "new"

    else:
        # ---- 已存在: 檢查價格是否變動 ----
        price_changed = (
            _price_differs(existing.monthly_price, new_monthly)
            or _price_differs(existing.annual_price, new_annual)
        )

        if price_changed:
            # 記錄價格變動歷史
            session.add(PriceHistory(
                plan_id=existing.id,
                old_monthly_price=existing.monthly_price,
                new_monthly_price=new_monthly,
                old_annual_price=existing.annual_price,
                new_annual_price=new_annual,
                change_type="price_change",
            ))
            logger.warning(
                f"  💰 價格變動: {plan_id_str} "
                f"月費 {existing.monthly_price} → {new_monthly}, "
                f"年費 {existing.annual_price} → {new_annual}"
            )

        # 更新方案資料 (不論價格是否變動都更新 fetched_at)
        existing.plan_name = plan_data["plan_name"]
        existing.monthly_price = new_monthly
        existing.annual_price = new_annual
        existing.annual_monthly_price = plan_data.get("annual_monthly_price")
        existing.currency = plan_data.get("currency", "USD")
        existing.billing_cycle = plan_data.get("billing_cycle", "monthly")
        existing.tax_mode = plan_data.get("tax_mode", "unknown")
        existing.data_source = plan_data.get("data_source", "parsed")
        existing.plan_type = plan_type
        existing.raw_payload = raw_payload
        existing.fetched_at = now
        existing.updated_at = now

        # 同步 features
        _sync_features(session, existing, plan_data.get("features", []))

        return "price_changed" if price_changed else "unchanged"


def _sync_features(session: Session, plan: Plan, features: List[str]):
    """同步方案特色功能 (先刪後增)"""
    session.query(PlanFeature).filter_by(plan_id=plan.id).delete()
    for i, feat in enumerate(features):
        session.add(PlanFeature(
            plan_id=plan.id,
            feature=feat,
            sort_order=i,
        ))


def _price_differs(old_val: Optional[float], new_val: Optional[float]) -> bool:
    """比較兩個價格是否不同 (處理 None 與浮點精度)"""
    if old_val is None and new_val is None:
        return False
    if old_val is None or new_val is None:
        return True
    return abs(old_val - new_val) > 0.001


def _infer_plan_type(platform_id_str: str, plan_id_str: str, plan_data: Dict[str, Any]) -> str:
    """
    決定方案類型 (plan_type):
    1. 爬蟲若明確設定 plan_data['plan_type'] 則優先採用
    2. 否則從 platform_config.compare_tiers 查分級，
       分級為「教育優惠」→ education，其餘 → standard
    """
    # 爬蟲明確設定的優先
    if "plan_type" in plan_data:
        return plan_data["plan_type"]

    tier_name = PLATFORMS.get(platform_id_str, {}).get("compare_tiers", {}).get(plan_id_str, "")
    if tier_name == "教育優惠":
        return "education"
    return "standard"


def _log_crawl(
    session: Session,
    platform_id: str,
    country_code: str,
    status: str,
    plan_count: int = 0,
    error_message: Optional[str] = None,
    duration: Optional[float] = None,
):
    """記錄爬蟲執行紀錄"""
    session.add(CrawlLog(
        platform_id=platform_id,
        country_code=country_code,
        status=status,
        plan_count=plan_count,
        error_message=error_message,
        duration_seconds=round(duration, 3) if duration else None,
    ))
