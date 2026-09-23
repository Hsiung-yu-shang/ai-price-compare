"""
Perplexity AI 定價爬蟲
資料來源: 官方公開定價頁面 https://www.perplexity.ai/pro

注意: Perplexity 定價頁需要 JavaScript 渲染，一般 HTTP 請求會被 403 擋住。
本爬蟲採用 Claude 爬蟲相同的「靜態備用值 + regex 嘗試」策略:
  - 先嘗試以 requests 抓取頁面，從 HTML/JSON 解析最新價格
  - 若請求失敗或解析失敗，使用硬編碼備用值並標記 data_source = 'hardcoded_fallback'
  - 永不靜默回傳假資料，所有備用值皆會記錄 WARNING

Perplexity 方案 (2026-08 確認):
  Free  $0          — 基本搜尋
  Pro   $20/月 / $200/年 ($16.67/月)
  Max   $200/月     — 頂級額度
  Pro (Education)   $10/月 — 需教育機構 email 驗證
  Enterprise Pro  $40/seat/月 / $400/year
  Enterprise Max  $325/seat/月
"""
import logging
import re
from typing import Any, Dict, List, Optional

from .base import BasePricingCrawler
from config.platform_config import PLATFORMS
from config.settings import REQUEST_TIMEOUT

logger = logging.getLogger(__name__)


class PerplexityPricingCrawler(BasePricingCrawler):
    """
    Perplexity AI 方案與定價爬蟲
    """
    platform_id: str = "perplexity"
    platform_name: str = "Perplexity AI"
    min_expected_plans: int = 3  # 至少 Free / Pro / Max

    def __init__(self, country_code: str = "TW", headers: Optional[Dict[str, str]] = None):
        super().__init__(country_code=country_code, headers=headers)
        cfg = PLATFORMS["perplexity"]
        self.pricing_url = cfg["pricing_url"]

    def fetch(self) -> str:
        """
        嘗試抓取 Perplexity 定價頁面 HTML
        頁面需要 JS 渲染，多數情況會拿到空內容或 403；
        parse() 會正確處理此情況並回退到靜態備用值
        """
        logger.info(f"[{self.platform_id}] 嘗試請求: {self.pricing_url}")
        try:
            resp = self.session.get(self.pricing_url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.text
        except Exception as exc:
            logger.warning(
                f"[{self.platform_id}] HTTP 請求失敗 ({exc})，"
                "將使用硬編碼備用值繼續"
            )
            return ""  # 空字串讓 parse() 判斷並全部使用備用值

    def _extract_price(
        self,
        pattern: str,
        text: str,
        group_indices: list,
        fallback_values: list,
        label: str,
    ) -> tuple:
        """
        嘗試用 regex 解析價格；失敗時回傳備用值並記錄警告。
        回傳 (values_tuple, is_fallback)
        """
        if text:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                values = tuple(float(match.group(i)) for i in group_indices)
                return values, False

        logger.warning(
            f"[{self.platform_id}] 無法解析 {label} 的價格，"
            f"使用硬編碼備用值: {fallback_values}"
        )
        return tuple(fallback_values), True

    def parse(self, raw_data: str) -> List[Dict[str, Any]]:
        """
        解析 Perplexity 定價資料
        raw_data 為空或無法解析時全部使用靜態備用值
        """
        # 去除 HTML 標籤，留純文字
        clean_text = ""
        if raw_data:
            text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', raw_data, flags=re.DOTALL)
            clean_text = re.sub(r'<[^>]+>', ' ', text)
            clean_text = ' '.join(clean_text.split())

        plans: List[Dict[str, Any]] = []
        any_fallback = False

        # ── 1. Free ─────────────────────────────────────────────────
        plans.append({
            "plan_id": "free",
            "plan_name": "Perplexity Free",
            "monthly_price": 0.0,
            "annual_price": None,
            "annual_monthly_price": None,
            "currency": "USD",
            "billing_cycle": "monthly",
            "tax_mode": "tax_exclusive",
            "data_source": "static",
            "features": [
                "每日 5 次 Pro Search (深度搜尋)",
                "存取 GPT-4o mini / Claude 3.5 Haiku 等基礎模型",
                "基本圖片上傳與分析",
                "Perplexity Spaces (個人知識庫)",
            ],
            "raw_payload": {"price": 0},
        })

        # ── 2. Pro ($20/月, $200/年) ─────────────────────────────────
        (pro_monthly,), pro_fb = self._extract_price(
            pattern=r'Pro[^$]*\$(\d+)\s*(?:per|/)\s*month',
            text=clean_text,
            group_indices=[1],
            fallback_values=[20.0],
            label="Pro monthly",
        )
        any_fallback = any_fallback or pro_fb

        plans.append({
            "plan_id": "pro",
            "plan_name": "Perplexity Pro",
            "monthly_price": pro_monthly,
            "annual_price": 200.0,
            "annual_monthly_price": round(200.0 / 12, 2),
            "currency": "USD",
            "billing_cycle": "both",
            "tax_mode": "tax_exclusive",
            "data_source": "hardcoded_fallback" if pro_fb else "parsed",
            "features": [
                "無限次 Pro Search (深度搜尋)",
                "每日 500 次 Deep Research",
                "存取 GPT-4o、Claude 3.7 Sonnet、Gemini 2.5 Pro 等頂級模型",
                "無限圖片上傳與分析",
                "無限圖片生成 (FLUX)",
                "$5/月 API 免費額度",
            ],
            "raw_payload": {"monthly": pro_monthly, "annual": 200.0},
        })

        # ── 3. Max ($200/月) ─────────────────────────────────────────
        (max_monthly,), max_fb = self._extract_price(
            pattern=r'Max[^$]*\$(\d+)\s*(?:per|/)\s*month',
            text=clean_text,
            group_indices=[1],
            fallback_values=[200.0],
            label="Max monthly",
        )
        any_fallback = any_fallback or max_fb

        plans.append({
            "plan_id": "max",
            "plan_name": "Perplexity Max",
            "monthly_price": max_monthly,
            "annual_price": None,
            "annual_monthly_price": None,
            "currency": "USD",
            "billing_cycle": "monthly",
            "tax_mode": "tax_exclusive",
            "data_source": "hardcoded_fallback" if max_fb else "parsed",
            "features": [
                "包含 Pro 全部功能",
                "10 倍以上 Pro 使用額度",
                "無限 Deep Research",
                "最高存取優先權與更長對話紀錄",
            ],
            "raw_payload": {"monthly": max_monthly},
        })

        # ── 4. Pro (Education) — 台灣教育版，$10/月 ──────────────────
        plans.append({
            "plan_id": "pro_edu",
            "plan_name": "Perplexity Pro (教育優惠)",
            "monthly_price": 10.0,
            "annual_price": None,
            "annual_monthly_price": None,
            "currency": "USD",
            "billing_cycle": "monthly",
            "tax_mode": "tax_exclusive",
            "data_source": "static",
            "plan_type": "education",   # 明確標記，由 diff.py 優先採用
            "features": [
                "包含 Pro 全部功能",
                "需以教育機構 email (.edu 或台灣大學域名) 驗證",
                "限學生與教職員使用",
                "每月 $10 — Pro 半價優惠",
            ],
            "raw_payload": {"monthly": 10.0, "requires_edu_verification": True},
        })

        # ── 5. Enterprise Pro ($40/seat/月) ──────────────────────────
        (ent_pro_monthly,), ent_pro_fb = self._extract_price(
            pattern=r'Enterprise\s*Pro[^$]*\$(\d+)\s*per\s*seat',
            text=clean_text,
            group_indices=[1],
            fallback_values=[40.0],
            label="Enterprise Pro",
        )
        any_fallback = any_fallback or ent_pro_fb

        plans.append({
            "plan_id": "enterprise_pro",
            "plan_name": "Perplexity Enterprise Pro",
            "monthly_price": ent_pro_monthly,
            "annual_price": 400.0,
            "annual_monthly_price": round(400.0 / 12, 2),
            "currency": "USD",
            "billing_cycle": "both",
            "tax_mode": "tax_exclusive",
            "data_source": "hardcoded_fallback" if ent_pro_fb else "parsed",
            "features": [
                "包含 Pro 全部功能",
                "SOC 2 Type II 企業安全認證",
                "資料不用於模型訓練",
                "組織知識庫 (Internal Knowledge Search)",
                "進階帳號管理與 SSO",
            ],
            "raw_payload": {"monthly": ent_pro_monthly, "annual_per_seat": 400.0},
        })

        # ── 6. Enterprise Max ($325/seat/月) ─────────────────────────
        plans.append({
            "plan_id": "enterprise_max",
            "plan_name": "Perplexity Enterprise Max",
            "monthly_price": 325.0,
            "annual_price": None,
            "annual_monthly_price": None,
            "currency": "USD",
            "billing_cycle": "monthly",
            "tax_mode": "tax_exclusive",
            "data_source": "static",
            "features": [
                "包含 Enterprise Pro 全部功能",
                "頂級運算優先權與最高 API 速率",
                "24/7 高級技術支援",
                "可客製化服務等級協議 (SLA)",
            ],
            "raw_payload": {"monthly": 325.0},
        })

        if any_fallback:
            fallback_ids = [p["plan_id"] for p in plans if p.get("data_source") == "hardcoded_fallback"]
            logger.warning(
                f"[{self.platform_id}] 以下方案使用硬編碼備用價格: {fallback_ids}。"
                "請確認 Perplexity 定價頁面格式是否已更新。"
            )

        return plans
