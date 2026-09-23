"""
Claude (Anthropic) 定價爬蟲
資料來源: 官方公開定價頁面 https://www.anthropic.com/pricing
透過 SSR HTML 解析方案卡片與價格數字

注意: Anthropic 官網為 SSR 渲染，價格寫在 HTML 中，
但 HTML 結構可能隨改版變動。若 regex 解析失敗，
本爬蟲會標記資料來源為 hardcoded fallback 並記錄警告，
而非靜默回傳假資料。
"""
import logging
import re
from typing import Any, Dict, List, Optional

from .base import BasePricingCrawler
from config.platform_config import PLATFORMS
from config.settings import REQUEST_TIMEOUT

logger = logging.getLogger(__name__)


class ClaudePricingCrawler(BasePricingCrawler):
    """
    Claude (Anthropic) 方案與定價爬蟲
    """
    platform_id: str = "claude"
    platform_name: str = "Claude (Anthropic)"
    min_expected_plans: int = 3  # 至少應有 Free / Pro / Max

    def __init__(self, country_code: str = "TW", headers: Optional[Dict[str, str]] = None):
        super().__init__(country_code=country_code, headers=headers)
        self.pricing_url = PLATFORMS["claude"]["pricing_url"]

    def fetch(self) -> str:
        """
        抓取 Anthropic 官網定價頁面 HTML
        """
        logger.info(f"[{self.platform_id}] 發送請求至: {self.pricing_url}")
        resp = self.session.get(self.pricing_url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.text

    def _clean_html_to_text(self, html: str) -> str:
        """移除 <script> 與 <style> 標籤並整理純文字"""
        clean_html = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.DOTALL)
        clean_text = re.sub(r'<[^>]+>', ' ', clean_html)
        return ' '.join(clean_text.split())

    def _extract_price_with_fallback(
        self,
        pattern: str,
        text: str,
        group_indices: list,
        fallback_values: list,
        label: str,
    ) -> tuple:
        """
        嘗試用 regex 從文字中提取價格，失敗時使用 fallback 並記錄警告。
        回傳 (values_tuple, is_from_fallback)
        """
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            values = tuple(float(match.group(i)) for i in group_indices)
            return values, False
        else:
            logger.warning(
                f"[{self.platform_id}] 無法從 HTML 解析 {label} 的價格 "
                f"(regex 未匹配)，使用硬編碼備用值: {fallback_values}"
            )
            return tuple(fallback_values), True

    def parse(self, raw_data: str) -> List[Dict[str, Any]]:
        """
        解析 Anthropic 官網定價頁面
        """
        clean_text = self._clean_html_to_text(raw_data)
        plans: List[Dict[str, Any]] = []
        has_any_fallback = False

        # 1. Claude Free — 價格固定為 0，不需要 regex
        plans.append({
            "plan_id": "free",
            "plan_name": "Claude Free",
            "monthly_price": 0.0,
            "annual_price": None,
            "annual_monthly_price": None,
            "currency": "USD",
            "billing_cycle": "monthly",
            "tax_mode": "tax_exclusive",
            "data_source": "static",
            "features": [
                "網頁版、桌面版與行動 App 存取",
                "生成程式碼、視覺化圖表與內容創作",
                "網頁搜尋能力",
                "跨對話記憶功能 (Memory)"
            ],
            "raw_payload": {"price": 0}
        })

        # 2. Claude Pro
        (pro_annual_mo, pro_monthly), pro_fallback = self._extract_price_with_fallback(
            pattern=r'\$(\d+)\s*Per month with annual[^\$]*\$\d+ billed[^\$]*\$(\d+)\s*if billed monthly',
            text=clean_text,
            group_indices=[1, 2],
            fallback_values=[17.0, 20.0],
            label="Claude Pro",
        )
        has_any_fallback = has_any_fallback or pro_fallback

        plans.append({
            "plan_id": "pro",
            "plan_name": "Claude Pro",
            "monthly_price": pro_monthly,
            "annual_price": pro_annual_mo * 12,
            "annual_monthly_price": pro_annual_mo,
            "currency": "USD",
            "billing_cycle": "both",
            "tax_mode": "tax_exclusive",
            "data_source": "hardcoded_fallback" if pro_fallback else "parsed",
            "features": [
                "包含 Free 全部功能",
                "5 倍以上日常使用額度",
                "支援 Claude Code、Claude Cowork 等延伸工具",
                "可自訂 Projects 專案管理對話與文檔",
                "優先存取最新頂級模型 (Opus / Sonnet)"
            ],
            "raw_payload": {"monthly": pro_monthly, "annual_monthly": pro_annual_mo}
        })

        # 3. Claude Max
        (max_price,), max_fallback = self._extract_price_with_fallback(
            pattern=r'Max[^\$]*From\s*\$(\d+)\s*Per month',
            text=clean_text,
            group_indices=[1],
            fallback_values=[100.0],
            label="Claude Max",
        )
        has_any_fallback = has_any_fallback or max_fallback

        plans.append({
            "plan_id": "max",
            "plan_name": "Claude Max",
            "monthly_price": max_price,
            "annual_price": None,
            "annual_monthly_price": None,
            "currency": "USD",
            "billing_cycle": "monthly",
            "tax_mode": "tax_exclusive",
            "data_source": "hardcoded_fallback" if max_fallback else "parsed",
            "features": [
                "包含 Pro 全部功能",
                "可選擇 5x 或 20x 超高使用額度",
                "更高 Token 輸出上限",
                "尖峰時段最高存取優先權"
            ],
            "raw_payload": {"from_price": max_price}
        })

        # 4. Claude Team (Standard & Premium)
        (team_annual_mo, team_monthly), team_fallback = self._extract_price_with_fallback(
            pattern=r'Standard seat[^\$]*\$(\d+)\s*Per seat[^\$]*annually[^\$]*\$(\d+)\s*if billed monthly',
            text=clean_text,
            group_indices=[1, 2],
            fallback_values=[20.0, 25.0],
            label="Claude Team Standard",
        )
        has_any_fallback = has_any_fallback or team_fallback

        plans.append({
            "plan_id": "team_standard",
            "plan_name": "Claude Team (Standard Seat)",
            "monthly_price": team_monthly,
            "annual_price": team_annual_mo * 12,
            "annual_monthly_price": team_annual_mo,
            "currency": "USD",
            "billing_cycle": "both",
            "tax_mode": "tax_exclusive",
            "data_source": "hardcoded_fallback" if team_fallback else "parsed",
            "features": [
                "2 至 150 人團隊協作",
                "包含 Pro 全功能與更高用量",
                "統一帳單與管理員控制台",
                "預設不使用團隊資料訓練模型",
                "支援 SSO 單一登入"
            ],
            "raw_payload": {"monthly": team_monthly, "annual_monthly": team_annual_mo}
        })

        # Team Premium — 可選，頁面上可能不存在
        m_team_prem = re.search(
            r'Premium seat[^\$]*\$(\d+)\s*Per seat[^\$]*annually[^\$]*\$(\d+)\s*if billed monthly',
            clean_text, re.IGNORECASE
        )
        if m_team_prem:
            prem_annual_mo = float(m_team_prem.group(1))
            prem_monthly = float(m_team_prem.group(2))
            plans.append({
                "plan_id": "team_premium",
                "plan_name": "Claude Team (Premium Seat)",
                "monthly_price": prem_monthly,
                "annual_price": prem_annual_mo * 12,
                "annual_monthly_price": prem_annual_mo,
                "currency": "USD",
                "billing_cycle": "both",
                "tax_mode": "tax_exclusive",
                "data_source": "parsed",
                "features": [
                    "包含 Standard 席位全部功能",
                    "5 倍標準席位使用額度 (5x more usage)"
                ],
                "raw_payload": {"monthly": prem_monthly, "annual_monthly": prem_annual_mo}
            })

        # 5. Claude Enterprise — 需聯繫銷售，價格從頁面解析
        (ent_price,), ent_fallback = self._extract_price_with_fallback(
            pattern=r'Enterprise[^\$]*\$(\d+)\s*Per seat',
            text=clean_text,
            group_indices=[1],
            fallback_values=[20.0],
            label="Claude Enterprise",
        )
        has_any_fallback = has_any_fallback or ent_fallback

        plans.append({
            "plan_id": "enterprise",
            "plan_name": "Claude Enterprise",
            "monthly_price": ent_price,
            "annual_price": None,
            "annual_monthly_price": None,
            "currency": "USD",
            "billing_cycle": "custom",
            "tax_mode": "tax_exclusive",
            "data_source": "hardcoded_fallback" if ent_fallback else "parsed",
            "features": [
                "包含 Team 全部功能",
                "更長上下文視窗 (高達 500k context)",
                "角色權限控管 (RBAC) 與 SCIM 自動化帳號同步",
                "稽核日誌 (Audit Logs) 與合規性 API",
                "支援 HIPAA 合規環境"
            ],
            "raw_payload": {"base_seat_price": ent_price, "billing": "seat + api usage"}
        })

        # 彙整 fallback 狀況
        if has_any_fallback:
            fallback_plans = [p["plan_id"] for p in plans if p.get("data_source") == "hardcoded_fallback"]
            logger.warning(
                f"[{self.platform_id}] 以下方案使用了硬編碼備用價格 (頁面格式可能已變更): "
                f"{fallback_plans}。請儘速檢查 Anthropic 定價頁面是否改版。"
            )

        return plans
