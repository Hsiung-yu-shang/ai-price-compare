"""
Pydantic Response Schemas
FastAPI 從這些型別自動產生 Swagger 文件與前端回傳格式驗證
"""
from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


# ── 平台 ─────────────────────────────────────────────────

class PlatformOut(BaseModel):
    platform_id: str = Field(examples=["chatgpt"], description="平台唯一識別碼")
    platform_name: str = Field(examples=["ChatGPT"], description="平台顯示名稱")
    vendor: Optional[str] = Field(None, examples=["OpenAI"], description="廠商名稱")
    official_url: Optional[str] = Field(None, description="官方定價頁連結")
    color_theme: str = Field(
        default="blue",
        examples=["emerald"],
        description="前端顏色主題 (emerald/amber/blue/purple/rose/indigo/teal)",
    )

    model_config = {"from_attributes": True}


# ── 價格歷史 ──────────────────────────────────────────────

class PriceHistoryOut(BaseModel):
    change_type: str = Field(
        examples=["price_change"],
        description="異動類型: new_plan / price_change / plan_removed",
    )
    old_monthly_price: Optional[float] = Field(None, description="變動前月費")
    new_monthly_price: float = Field(description="變動後月費")
    old_annual_price: Optional[float] = Field(None, description="變動前年費")
    new_annual_price: Optional[float] = Field(None, description="變動後年費")
    changed_at: datetime = Field(description="異動記錄時間 (UTC)")

    model_config = {"from_attributes": True}


# ── 方案 ─────────────────────────────────────────────────

class PlanOut(BaseModel):
    id: int = Field(description="方案 DB 主鍵")
    platform_id: str = Field(examples=["chatgpt"], description="所屬平台識別碼")
    plan_id: str = Field(examples=["plus"], description="方案唯一識別碼")
    plan_name: str = Field(examples=["ChatGPT Plus"], description="方案顯示名稱")
    country_code: str = Field(examples=["TW"], description="適用國家/地區")
    monthly_price: float = Field(examples=[690.0], description="月繳定價")
    annual_price: Optional[float] = Field(None, examples=[6900.0], description="年繳總價 (NULL 表示無年繳方案)")
    annual_monthly_price: Optional[float] = Field(None, examples=[575.0], description="年繳平均每月價格")
    currency: str = Field(examples=["TWD"], description="幣別 (3碼)")
    billing_cycle: str = Field(
        examples=["both"],
        description="計費週期: monthly / annual / both / custom",
    )
    tax_mode: str = Field(
        examples=["tax_inclusive"],
        description="稅務模式: tax_inclusive / tax_exclusive / unknown",
    )
    data_source: str = Field(
        examples=["parsed"],
        description="資料來源: parsed / hardcoded_fallback / static",
    )
    plan_type: str = Field(
        default="standard",
        examples=["standard"],
        description="方案類型: standard / education / nonprofit",
    )
    features: List[str] = Field(default=[], description="方案特色功能列表")
    fetched_at: datetime = Field(description="最後爬取確認時間 (UTC)")

    model_config = {"from_attributes": True}


# ── 比價矩陣 ──────────────────────────────────────────────

class ComparePlanItem(BaseModel):
    """比價矩陣中的單一方案欄位"""
    id: int
    plan_id: str
    plan_name: str
    monthly_price: float
    annual_monthly_price: Optional[float] = None
    currency: str
    tax_mode: str
    plan_type: str = "standard"
    features: List[str] = []
    fetched_at: datetime


class CompareGroup(BaseModel):
    """比價矩陣分組 (Free / Personal / Team / Enterprise)"""
    group_name: str = Field(examples=["個人進階方案"], description="分組名稱")
    platforms: Dict[str, Optional[ComparePlanItem]] = Field(
        description="各平台在此分組的方案，Key 為 platform_id，Value 為方案資訊 (None 表示該平台無此層級方案)"
    )


class CompareOut(BaseModel):
    country_code: str
    currency_note: str = Field(description="幣別說明 (台灣市場 ChatGPT/Gemini 為 TWD，Claude 為 USD)")
    groups: List[CompareGroup]


# ── 通用 ──────────────────────────────────────────────────

class ErrorOut(BaseModel):
    detail: str = Field(description="錯誤說明")
