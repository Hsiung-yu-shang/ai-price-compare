"""
ChatGPT (OpenAI) 定價爬蟲
資料來源: 官方公開匿名端點 https://chatgpt.com/backend-anon/checkout_pricing_config/configs/{country_code}
支援 curl_cffi (模擬 Chrome TLS 指紋) 與標準 requests 雙重模式
"""
import logging
from typing import Any, Dict, List, Optional

from .base import BasePricingCrawler
from config.platform_config import PLATFORMS
from config.settings import REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

# 嘗試載入 curl_cffi 進行 TLS 指紋偽裝 (繞過 Cloudflare Managed Challenge)
try:
    from curl_cffi import requests as curl_requests
    HAS_CURL_CFFI = True
except ImportError:
    curl_requests = None
    HAS_CURL_CFFI = False


class ChatGPTPricingCrawler(BasePricingCrawler):
    """
    ChatGPT 方案與定價爬蟲
    """
    platform_id: str = "chatgpt"
    platform_name: str = "ChatGPT"
    min_expected_plans: int = 3  # 至少應有 Free / Plus / Pro

    def __init__(self, country_code: str = "TW", headers: Optional[Dict[str, str]] = None):
        super().__init__(country_code=country_code, headers=headers)
        self.api_url = PLATFORMS["chatgpt"]["pricing_api"].format(
            country_code=self.country_code
        )

    def fetch(self) -> Dict[str, Any]:
        """
        請求官方匿名定價 API
        優先使用 curl_cffi 模擬 Chrome TLS 指紋，若未安裝則退回標準 requests session
        """
        logger.info(f"[{self.platform_id}] 發送請求至: {self.api_url}")

        req_headers = self.headers.copy()
        req_headers.update({
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://chatgpt.com/pricing",
            "Origin": "https://chatgpt.com",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        })

        if HAS_CURL_CFFI:
            logger.info(f"[{self.platform_id}] 使用 curl_cffi (impersonate='chrome124') 發送請求...")
            resp = curl_requests.get(
                self.api_url,
                headers=req_headers,
                impersonate="chrome124",
                timeout=REQUEST_TIMEOUT
            )
        else:
            logger.info(f"[{self.platform_id}] 使用標準 requests session 發送請求...")
            resp = self.session.get(self.api_url, headers=req_headers, timeout=REQUEST_TIMEOUT)

        if resp.status_code == 403:
            raise PermissionError(
                f"[{self.platform_id}] 遭到 Cloudflare 驗證阻擋 (HTTP 403)。"
                "建議在環境中安裝 curl_cffi (pip install curl_cffi) 或部署至 OpenSSL 環境運行。"
            )

        resp.raise_for_status()
        return resp.json()

    def parse(self, raw_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        解析 ChatGPT 價格 API 回傳結構
        """
        plans: List[Dict[str, Any]] = []
        curr_cfg = raw_data.get("currency_config", {})
        currency = curr_cfg.get("symbol_code", "USD")

        # 方案定義映射 (plan_id, 顯示名稱, 特色說明)
        plan_definitions = [
            (
                "free",
                "ChatGPT Free",
                [
                    "存取 GPT-4o mini 等基礎模型",
                    "基本網頁搜尋與分析功能",
                    "有限次數存取最新旗艦模型"
                ]
            ),
            (
                "go",
                "ChatGPT Go",
                [
                    "入門輕量付費方案",
                    "比 Free 方案提供更高頻率與穩定度"
                ]
            ),
            (
                "plus",
                "ChatGPT Plus",
                [
                    "無限制存取 GPT-4o",
                    "進階語音模式 (Advanced Voice Mode)",
                    "DALL·E 圖片生成、自訂 GPTs 建立與使用",
                    "搶先體驗新功能"
                ]
            ),
            (
                "prolite",
                "ChatGPT Pro Lite",
                [
                    "高階運算推理模型中度用量",
                    "比 Plus 方案擁有更高運算資源與優先權"
                ]
            ),
            (
                "pro",
                "ChatGPT Pro",
                [
                    "無限制存取所有頂級模型",
                    "計算密集模式 (o1 Pro mode)",
                    "頂級運算資源與最高存取優先權"
                ]
            ),
            (
                "business",
                "ChatGPT Business (Team)",
                [
                    "包含 Plus 全部功能",
                    "更高用量上限",
                    "專屬團隊工作區與管理後台",
                    "預設不使用團隊資料訓練模型"
                ]
            ),
            (
                "business_prolite",
                "ChatGPT Business Pro Lite",
                [
                    "團隊級 Pro Lite 高階推理方案",
                    "團隊管理與集中計費"
                ]
            ),
            (
                "business_non_profit",
                "ChatGPT Business (Non-Profit)",
                [
                    "非營利組織專屬折扣方案",
                    "完整團隊版協作與隱私保護功能"
                ]
            )
        ]

        for plan_id, plan_name, features in plan_definitions:
            item = curr_cfg.get(plan_id)
            if not item or not isinstance(item, dict):
                continue

            month_info = item.get("month", {})
            year_info = item.get("year", {})

            monthly_price = month_info.get("amount")
            annual_monthly_price = year_info.get("amount")
            annual_price = annual_monthly_price * 12 if annual_monthly_price is not None else None

            tax_mode_str = month_info.get("tax") or year_info.get("tax") or "inclusive"
            tax_mode = "tax_inclusive" if tax_mode_str == "inclusive" else "tax_exclusive"

            if monthly_price is not None:
                plans.append({
                    "plan_id": plan_id,
                    "plan_name": plan_name,
                    "monthly_price": float(monthly_price),
                    "annual_price": float(annual_price) if annual_price is not None else None,
                    "annual_monthly_price": float(annual_monthly_price) if annual_monthly_price is not None else None,
                    "currency": currency,
                    "billing_cycle": "both" if annual_price is not None else "monthly",
                    "tax_mode": tax_mode,
                    "features": features,
                    "raw_payload": item
                })

        return plans
