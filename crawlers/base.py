"""
爬蟲抽象基底類別 (BasePricingCrawler)
定義標準的 fetch -> parse -> validate 流程與回傳資料結構
"""
from abc import ABC, abstractmethod
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from config.settings import DEFAULT_HEADERS, REQUEST_TIMEOUT, MAX_RETRIES

logger = logging.getLogger(__name__)

# 驗證用的合法值域
VALID_BILLING_CYCLES = {"monthly", "annual", "both", "custom"}
VALID_TAX_MODES = {"tax_inclusive", "tax_exclusive", "unknown"}


class BasePricingCrawler(ABC):
    """
    所有平台定價爬蟲的基底抽象類別
    """
    platform_id: str = "base"
    platform_name: str = "Base Platform"
    min_expected_plans: int = 1  # 子類別應覆寫為合理的最小方案數量

    def __init__(self, country_code: str = "TW", headers: Optional[Dict[str, str]] = None):
        self.country_code = country_code.upper()
        self.headers = headers or DEFAULT_HEADERS.copy()
        self.session = self._build_session()

    def _build_session(self) -> requests.Session:
        """建立具備自動重試機制的 requests Session"""
        session = requests.Session()
        session.headers.update(self.headers)

        retry_strategy = Retry(
            total=MAX_RETRIES,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    @abstractmethod
    def fetch(self) -> Any:
        """
        取得原始資料 (HTML、JSON 等)
        若發生不可恢復錯誤需拋出例外
        """
        pass

    @abstractmethod
    def parse(self, raw_data: Any) -> List[Dict[str, Any]]:
        """
        將原始資料解析為標準方案格式列表
        標準 Plan 欄位包含:
        - plan_id: 方案唯一標識符 (如 'plus', 'pro')
        - plan_name: 方案名稱
        - monthly_price: 每月定價 (float 或 0)
        - annual_price: 年繳方案總價或平均每月價格 (float 或 None)
        - annual_monthly_price: 年繳平均每月價格 (float 或 None)
        - currency: 幣別 (如 'TWD', 'USD')
        - billing_cycle: 'monthly' | 'annual' | 'both' | 'custom'
        - tax_mode: 'tax_inclusive' | 'tax_exclusive' | 'unknown'
        - features: 特色功能列表 (list[str])
        - raw_payload: 原始資料備份
        """
        pass

    def validate(self, plans: List[Dict[str, Any]]) -> bool:
        """
        驗證解析出的方案資料有效性與完整性
        """
        if not plans or not isinstance(plans, list):
            logger.error(f"[{self.platform_id}] 解析結果為空或非列表格式")
            return False

        # 方案數量下限檢查
        if len(plans) < self.min_expected_plans:
            logger.error(
                f"[{self.platform_id}] 方案數量 ({len(plans)}) 低於預期下限 "
                f"({self.min_expected_plans})，疑似爬取不完整"
            )
            return False

        for plan in plans:
            if not plan.get("plan_id") or not plan.get("plan_name"):
                logger.error(f"[{self.platform_id}] 方案缺少必要識別名稱: {plan}")
                return False

            # 價格必須為數值且非負數 (Free 方案為 0)
            monthly_price = plan.get("monthly_price")
            if monthly_price is not None and (not isinstance(monthly_price, (int, float)) or monthly_price < 0):
                logger.error(f"[{self.platform_id}] 方案價格無效: {plan}")
                return False

            # 幣別檢查
            currency = plan.get("currency")
            if not currency or not isinstance(currency, str) or len(currency) != 3:
                logger.error(f"[{self.platform_id}] 方案幣別無效或缺失: {plan.get('plan_id')} -> {currency}")
                return False

            # billing_cycle 檢查
            billing_cycle = plan.get("billing_cycle")
            if billing_cycle not in VALID_BILLING_CYCLES:
                logger.error(
                    f"[{self.platform_id}] 方案 billing_cycle 無效: "
                    f"{plan.get('plan_id')} -> {billing_cycle} (允許值: {VALID_BILLING_CYCLES})"
                )
                return False

            # tax_mode 檢查
            tax_mode = plan.get("tax_mode")
            if tax_mode not in VALID_TAX_MODES:
                logger.error(
                    f"[{self.platform_id}] 方案 tax_mode 無效: "
                    f"{plan.get('plan_id')} -> {tax_mode} (允許值: {VALID_TAX_MODES})"
                )
                return False

        return True

    def run(self) -> Dict[str, Any]:
        """
        執行爬蟲完整流程: fetch -> parse -> validate
        回傳統整結果字典
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        result = {
            "platform": self.platform_id,
            "platform_name": self.platform_name,
            "country_code": self.country_code,
            "fetched_at": now_iso,
            "status": "failed",
            "currency": None,
            "plans": [],
            "error": None
        }

        try:
            logger.info(f"[{self.platform_id}] 開始抓取定價資料 (國家: {self.country_code})...")
            raw_data = self.fetch()

            logger.info(f"[{self.platform_id}] 解析資料...")
            plans = self.parse(raw_data)

            if not self.validate(plans):
                raise ValueError("資料驗證未通過")

            # 提取幣別，多幣別時記錄警告
            currencies = {p.get("currency") for p in plans if p.get("currency")}
            if len(currencies) > 1:
                logger.warning(
                    f"[{self.platform_id}] 偵測到多種幣別: {currencies}，使用第一個出現的幣別"
                )
            main_currency = sorted(currencies)[0] if currencies else "USD"

            result["status"] = "success"
            result["currency"] = main_currency
            result["plans"] = plans
            logger.info(f"[{self.platform_id}] 抓取成功，共解析出 {len(plans)} 個方案")

        except Exception as e:
            logger.exception(f"[{self.platform_id}] 爬蟲執行失敗: {e}")
            result["error"] = str(e)

        return result
