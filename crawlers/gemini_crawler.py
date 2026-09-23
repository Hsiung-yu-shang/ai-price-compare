"""
Gemini (Google One AI 方案) 定價爬蟲
資料來源:
1. 方案頁: https://one.google.com/intl/zh-TW_{country_code}/about/google-ai-plans/
2. 定價 Feed: https://one.google.com/intl/ALL_{country_code}/about/feeds/{feed_filename}
動態透過 Web Component 腳本分析取得最新的 feed 檔名
"""
import logging
import re
from typing import Any, Dict, List, Optional

from .base import BasePricingCrawler
from config.platform_config import PLATFORMS
from config.settings import REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

# 國家代碼 → 頁面語言代碼映射 (用於組合方案頁 URL)
COUNTRY_LOCALE_MAP = {
    "TW": "zh-TW",
    "US": "en",
    "JP": "ja",
    "KR": "ko",
    "HK": "zh-HK",
}


class GeminiPricingCrawler(BasePricingCrawler):
    """
    Google One AI (Gemini) 方案與定價爬蟲
    """
    platform_id: str = "gemini"
    platform_name: str = "Gemini (Google One AI)"
    min_expected_plans: int = 3  # 至少應有 Free / Plus / Pro

    def __init__(self, country_code: str = "TW", headers: Optional[Dict[str, str]] = None):
        super().__init__(country_code=country_code, headers=headers)
        locale = COUNTRY_LOCALE_MAP.get(self.country_code, "en")
        self.plans_page_url = (
            f"https://one.google.com/intl/{locale}_{self.country_code.lower()}"
            f"/about/google-ai-plans/"
        )
        self.feed_template = PLATFORMS["gemini"]["feed_url_template"]

    def _discover_feed_filename(self) -> str:
        """
        動態從 Google One 頁面載入的 JS 模組中解析出當前生效的 pricing_YYYY_MM_DD.json 檔名
        """
        logger.info(f"[{self.platform_id}] 分析 HTML 頁面尋找 JS 資源: {self.plans_page_url}")
        resp = self.session.get(self.plans_page_url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        html = resp.text

        # 找出 /about/assets/d/ 下的 JS bundle
        script_paths = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html)
        candidate_scripts = [
            s if s.startswith("http") else f"https://one.google.com{s}"
            for s in script_paths
            if "/about/assets/d/" in s
        ]

        logger.info(f"[{self.platform_id}] 掃描 {len(candidate_scripts)} 個 JS 模組尋找 feed 檔名...")
        for script_url in candidate_scripts:
            try:
                s_resp = self.session.get(script_url, timeout=REQUEST_TIMEOUT)
                if s_resp.status_code == 200:
                    match = re.search(r'pricing_\d{4}_\d{2}_\d{2}\.json', s_resp.text)
                    if match:
                        filename = match.group(0)
                        logger.info(f"[{self.platform_id}] 成功找到 Feed 檔名: {filename} (來源: {script_url})")
                        return filename
            except Exception as e:
                logger.debug(f"[{self.platform_id}] 檢查 {script_url} 失敗: {e}")
                continue

        # 若動態發現失敗，使用近期已知的預設備用檔名
        fallback_name = "pricing_2026_07_28.json"
        logger.warning(f"[{self.platform_id}] 未能動態解析出 Feed 檔名，使用備用檔名: {fallback_name}")
        return fallback_name

    def fetch(self) -> Dict[str, Any]:
        """
        抓取特定國家/地區的 Gemini 價格 Feed JSON
        """
        feed_filename = self._discover_feed_filename()
        feed_url = self.feed_template.format(
            country_code=self.country_code.lower(),
            filename=feed_filename
        )
        logger.info(f"[{self.platform_id}] 抓取定價 JSON: {feed_url}")
        resp = self.session.get(feed_url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def parse(self, raw_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        解析 Google One AI 定價 Feed
        """
        plans: List[Dict[str, Any]] = []
        currency = raw_data.get("CURRENCY_CODE", "TWD" if self.country_code == "TW" else "USD")

        # 1. Gemini Free
        plans.append({
            "plan_id": "free",
            "plan_name": "Gemini Free",
            "monthly_price": 0.0,
            "annual_price": None,
            "annual_monthly_price": None,
            "currency": currency,
            "billing_cycle": "monthly",
            "tax_mode": "tax_inclusive",
            "features": [
                "存取 1.5 Flash 等基礎模型",
                "整合 Google 搜尋與即時資訊",
                "標準雲端儲存空間 15 GB"
            ],
            "raw_payload": {"price": raw_data.get("PRICE_FREE", 0)}
        })

        # 定價欄位映射
        ai_plan_mappings = [
            (
                "ai_plus",
                "Google One AI Plus (Gemini Plus)",
                "PRICE_GEN_AI_PLUS_MONTHLY",
                [
                    "含 200 GB Google 雲端儲存空間",
                    "在 Gmail、Docs、Slides 等日常工具中支援 Gemini",
                    "基本 AI 創作與摘要輔助"
                ]
            ),
            (
                "ai_pro",
                "Google One AI Premium (Gemini Advanced)",
                "PRICE_GEN_AI_PRO_MONTHLY",
                [
                    "存取最先進的 1.5 Pro / 2.0 等頂級 AI 模型",
                    "高達 100 萬 Token 的百萬級超長上下文視窗",
                    "包含 2 TB Google 雲端儲存空間",
                    "完整整合 Google Workspace (Gmail, Docs, Drive 等) 全功能"
                ]
            ),
            (
                "ai_ultra_100",
                "Google One AI Ultra 100",
                "PRICE_GEN_AI_ULTRA_100_MONTHLY",
                [
                    "最高運算優先權與最高額度",
                    "包含超大容量雲端儲存空間",
                    "旗艦級企業與專業開發模型體驗"
                ]
            ),
            (
                "ai_ultra_200",
                "Google One AI Ultra 200",
                "PRICE_GEN_AI_ULTRA_200_MONTHLY",
                [
                    "極致算力與專業工作負載支援",
                    "最高等級客製化支援與儲存配額"
                ]
            )
        ]

        for plan_id, name, field_key, features in ai_plan_mappings:
            price_val = raw_data.get(field_key)
            if price_val is not None and isinstance(price_val, (int, float)):
                plans.append({
                    "plan_id": plan_id,
                    "plan_name": name,
                    "monthly_price": float(price_val),
                    "annual_price": None,
                    "annual_monthly_price": None,
                    "currency": currency,
                    "billing_cycle": "monthly",
                    "tax_mode": "tax_inclusive",
                    "features": features,
                    "raw_payload": {field_key: price_val}
                })

        # 台灣學生教育方案 (靜態資料，需學生 email 驗證，無法從 feed 取得)
        # 資料來源: https://one.google.com/ai-student?hl=zh-TW
        if self.country_code == "TW":
            plans.append({
                "plan_id": "ai_pro_edu",
                "plan_name": "Google AI Pro (學生優惠)",
                "monthly_price": 160.0,
                "annual_price": None,
                "annual_monthly_price": None,
                "currency": "TWD",
                "billing_cycle": "monthly",
                "tax_mode": "tax_inclusive",
                "data_source": "static",
                "plan_type": "education",
                "features": [
                    "包含 AI Pro 全部功能 (含 Gemini Advanced)",
                    "2 TB Google 雲端儲存空間",
                    "享 75% 優惠，最多 4 年 (原價 $650/月)",
                    "需以學校 email 驗證學生身份",
                ],
                "raw_payload": {
                    "original_price": 650.0,
                    "discount": "75%",
                    "max_duration": "4 years",
                    "source_url": "https://one.google.com/ai-student?hl=zh-TW",
                },
            })
            plans.append({
                "plan_id": "ai_pro_edu_yt",
                "plan_name": "Google AI Pro + YouTube Premium (學生套組)",
                "monthly_price": 250.0,
                "annual_price": None,
                "annual_monthly_price": None,
                "currency": "TWD",
                "billing_cycle": "monthly",
                "tax_mode": "tax_inclusive",
                "data_source": "static",
                "plan_type": "education",
                "features": [
                    "包含 AI Pro 全部功能",
                    "附加 YouTube Premium (無廣告、離線播放、背景播放)",
                    "2 TB Google 雲端儲存空間",
                    "享 70% 優惠，最多 4 年 (原價 $849/月)",
                    "需以學校 email 驗證學生身份",
                ],
                "raw_payload": {
                    "original_price": 849.0,
                    "discount": "70%",
                    "max_duration": "4 years",
                    "source_url": "https://one.google.com/ai-student?hl=zh-TW",
                },
            })

        return plans
