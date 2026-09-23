"""
FastAPI 主應用
啟動: python -m uvicorn api.main:app --reload --port 8000
互動式文件預設關閉；本機可設定 ENABLE_API_DOCS=1。
"""
import sys
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# 將專案根目錄加入 sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from storage import init_db, get_session, Platform, Plan, PlanFeature, PriceHistory
from config.platform_config import PLATFORMS, TIER_ORDER
from config.settings import DATA_DIR, ENABLE_API_DOCS
from api.security import ResourceGuardMiddleware
from api.admin import AdminManager, valid_admin_origin
from api.schemas import (
    PlatformOut,
    PlanOut,
    PriceHistoryOut,
    CompareOut,
    CompareGroup,
    ComparePlanItem,
    ErrorOut,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


# ── 動態建立比價矩陣分組 (從各平台 compare_tiers 聚合) ────────────────
def _build_compare_groups() -> list:
    """
    聚合所有平台的 compare_tiers 成為 COMPARE_GROUPS 格式:
    [(tier_name, {platform_id: [plan_id, ...]}), ...]

    plan_id 只在單一平台內唯一（例如多個平台都有 pro），因此必須保留
    platform_id 維度，避免 Claude Pro 被誤歸到 ChatGPT Pro 的分級。
    依 TIER_ORDER 排序，新增平台/分級只需更新 platform_config.py
    """
    tier_plan_ids: dict = {}
    for platform_id, cfg in PLATFORMS.items():
        for plan_id, tier_name in cfg.get("compare_tiers", {}).items():
            platform_plans = tier_plan_ids.setdefault(tier_name, {}).setdefault(platform_id, [])
            if plan_id not in platform_plans:
                platform_plans.append(plan_id)

    return [
        (tier_name, tier_plan_ids[tier_name])
        for tier_name in TIER_ORDER
        if tier_name in tier_plan_ids
    ]


COMPARE_GROUPS = _build_compare_groups()


# ── App 生命週期 ──────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """啟動時初始化 DB，關閉時清理"""
    logger.info("FastAPI 啟動 — 初始化資料庫...")
    init_db()
    yield
    logger.info("FastAPI 關閉")


# ── FastAPI 應用設定 ──────────────────────────────────────
app = FastAPI(
    title="AI 平台比價 API",
    description="""
## 功能說明
爬取 ChatGPT / Claude / Gemini / Perplexity 的訂閱方案定價，提供比價資料給前端。

## 資料更新
- 每日自動排程爬取一次 (`scripts/run_all.py`)
- 管理者可在主機上執行 `systemctl start ai-price-compare-crawler.service`

## 幣別說明
台灣市場：ChatGPT 與 Gemini 為 **TWD**，Claude 為 **USD**（Anthropic 目前僅提供 USD 定價）。
    """,
    version="1.0.0",
    contact={"name": "AI Price Compare"},
    lifespan=lifespan,
    docs_url="/docs" if ENABLE_API_DOCS else None,
    redoc_url="/redoc" if ENABLE_API_DOCS else None,
    openapi_url="/openapi.json" if ENABLE_API_DOCS else None,
    responses={500: {"model": ErrorOut}},
)
app.state.admin_manager = AdminManager(
    os.getenv("ADMIN_PASSWORD_HASH", ""),
    DATA_DIR / "manual-refresh.request",
    DATA_DIR / "crawl_status.json",
)


@app.get("/api/health", tags=["系統"], summary="健康檢查")
def health_check():
    """供 systemd、反向代理與部署腳本確認服務可用。"""
    return {"status": "ok"}

# 前端和 API 同源，Vite 開發模式透過 proxy 呼叫後端。
app.add_middleware(ResourceGuardMiddleware)


class AdminLoginIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)


def _require_admin(request: Request) -> str:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not app.state.admin_manager.authorized(token):
        raise HTTPException(status_code=401, detail="請先登入管理員")
    return token


def _require_secure_origin(request: Request) -> None:
    if not valid_admin_origin(request.headers.get("origin"), request.headers.get("host")):
        raise HTTPException(status_code=403, detail="管理操作只能從同網域 HTTPS 頁面執行")


@app.post("/api/admin/login", include_in_schema=False)
def admin_login(payload: AdminLoginIn, request: Request):
    _require_secure_origin(request)
    status, token = app.state.admin_manager.login(payload.password)
    if status == 503:
        raise HTTPException(status_code=503, detail="管理功能尚未設定")
    if status == 429:
        raise HTTPException(status_code=429, detail="登入嘗試過多，請稍後再試")
    if status != 200:
        raise HTTPException(status_code=401, detail="密碼錯誤")
    return {"token": token, "expires_in": 900}


@app.get("/api/admin/status", include_in_schema=False)
def admin_status(request: Request):
    _require_admin(request)
    return app.state.admin_manager.status()


@app.post("/api/admin/refresh", status_code=202, include_in_schema=False)
def admin_refresh(request: Request):
    _require_secure_origin(request)
    _require_admin(request)
    status, retry_after = app.state.admin_manager.request_refresh()
    if status == 429:
        raise HTTPException(
            status_code=429, detail="同步過於頻繁，請稍後再試",
            headers={"Retry-After": str(retry_after)},
        )
    return {"status": "queued"}


@app.post("/api/admin/logout", include_in_schema=False)
def admin_logout(request: Request):
    _require_secure_origin(request)
    token = _require_admin(request)
    app.state.admin_manager.logout(token)
    return {"status": "ok"}


# ══════════════════════════════════════════════════════════
# 平台相關 API
# ══════════════════════════════════════════════════════════

@app.get(
    "/api/platforms",
    response_model=List[PlatformOut],
    summary="取得所有平台列表",
    tags=["平台"],
)
def get_platforms():
    """回傳目前資料庫中已有資料的所有 AI 平台基本資訊（含前端顏色主題）。"""
    with get_session() as session:
        platforms = session.query(Platform).order_by(Platform.platform_id).all()
        return [
            PlatformOut(
                platform_id=p.platform_id,
                platform_name=p.platform_name,
                vendor=p.vendor,
                official_url=p.official_url,
                # 從 platform_config 取前端顏色主題，找不到時 fallback 為 'blue'
                color_theme=PLATFORMS.get(p.platform_id, {}).get("color_theme", "blue"),
            )
            for p in platforms
        ]


# ══════════════════════════════════════════════════════════
# 方案相關 API
# ══════════════════════════════════════════════════════════

@app.get(
    "/api/plans",
    response_model=List[PlanOut],
    summary="取得方案列表 (支援篩選)",
    tags=["方案"],
)
def get_plans(
    platform: Optional[str] = Query(None, min_length=1, max_length=50, pattern=r"^[a-z0-9_-]+$", examples=["chatgpt"], description="平台識別碼篩選"),
    country: str = Query("TW", pattern=r"^(TW|US)$", examples=["TW"], description="國家代碼篩選"),
    plan_type: Optional[str] = Query(
        None,
        pattern=r"^(standard|education|nonprofit)$",
        examples=["education"],
        description="方案類型篩選: standard / education / nonprofit",
    ),
):
    """
    取得所有方案定價資訊，可依平台、國家、方案類型篩選。

    - `platform` 省略時回傳全部平台的方案
    - `country` 預設為 TW
    - `plan_type` 省略時回傳全部類型；`education` 只回傳台灣教育版方案
    """
    with get_session() as session:
        query = (
            session.query(Plan, Platform.platform_id)
            .join(Platform, Plan.platform_id == Platform.id)
            .filter(Plan.country_code == country.upper())
        )
        if platform:
            query = query.filter(Platform.platform_id == platform.lower())
        if plan_type:
            query = query.filter(Plan.plan_type == plan_type.lower())

        rows = query.order_by(Platform.platform_id, Plan.monthly_price).all()

        result = []
        for plan, platform_id_str in rows:
            features = [f.feature for f in sorted(plan.features, key=lambda x: x.sort_order)]
            result.append(
                PlanOut(
                    id=plan.id,
                    platform_id=platform_id_str,
                    plan_id=plan.plan_id,
                    plan_name=plan.plan_name,
                    country_code=plan.country_code,
                    monthly_price=plan.monthly_price,
                    annual_price=plan.annual_price,
                    annual_monthly_price=plan.annual_monthly_price,
                    currency=plan.currency,
                    billing_cycle=plan.billing_cycle,
                    tax_mode=plan.tax_mode,
                    data_source=plan.data_source,
                    plan_type=plan.plan_type,
                    features=features,
                    fetched_at=plan.fetched_at,
                )
            )
        return result


@app.get(
    "/api/plans/{plan_db_id}/history",
    response_model=List[PriceHistoryOut],
    summary="取得單一方案的歷史價格記錄",
    tags=["方案"],
    responses={404: {"model": ErrorOut}},
)
def get_plan_history(plan_db_id: int):
    """
    依方案的 DB 主鍵取得其歷史價格異動記錄，可用於繪製價格走勢圖。

    `plan_db_id` 可從 `GET /api/plans` 的回傳結果中的 `id` 欄位取得。
    """
    with get_session() as session:
        plan = session.query(Plan).filter_by(id=plan_db_id).first()
        if not plan:
            raise HTTPException(status_code=404, detail=f"找不到 plan_db_id={plan_db_id} 的方案記錄")

        history = (
            session.query(PriceHistory)
            .filter_by(plan_id=plan_db_id)
            .order_by(PriceHistory.changed_at.desc())
            .limit(100)
            .all()
        )
        return [
            PriceHistoryOut(
                change_type=h.change_type,
                old_monthly_price=h.old_monthly_price,
                new_monthly_price=h.new_monthly_price,
                old_annual_price=h.old_annual_price,
                new_annual_price=h.new_annual_price,
                changed_at=h.changed_at,
            )
            for h in reversed(history)
        ]


# ══════════════════════════════════════════════════════════
# 比價矩陣 API
# ══════════════════════════════════════════════════════════

@app.get(
    "/api/compare",
    response_model=CompareOut,
    summary="取得比價矩陣 (前端表格直接用)",
    tags=["比價"],
)
def get_compare(
    country: str = Query("TW", pattern=r"^(TW|US)$", examples=["TW"], description="國家代碼"),
):
    """
    回傳各平台方案按「免費 / 個人入門 / 個人進階 / 個人旗艦 / 頂級旗艦 / 團隊 / 企業」分組的比價矩陣。

    前端比價表格可直接依此結構渲染，Key 為 `platform_id`，Value 為各平台在此層級的方案。
    """
    with get_session() as session:
        rows = (
            session.query(Plan, Platform.platform_id)
            .join(Platform, Plan.platform_id == Platform.id)
            .filter(Plan.country_code == country.upper())
            .all()
        )

        # 建立 {platform_id: {plan_id: Plan}} 查找結構
        plan_lookup: dict[str, dict[str, Plan]] = {}
        for plan, platform_id_str in rows:
            plan_lookup.setdefault(platform_id_str, {})[plan.plan_id] = plan

        all_platforms = list(plan_lookup.keys())

        def plan_to_item(plan: Plan, platform_id_str: str) -> ComparePlanItem:
            features = [f.feature for f in sorted(plan.features, key=lambda x: x.sort_order)]
            return ComparePlanItem(
                id=plan.id,
                plan_id=plan.plan_id,
                plan_name=plan.plan_name,
                monthly_price=plan.monthly_price,
                annual_monthly_price=plan.annual_monthly_price,
                currency=plan.currency,
                tax_mode=plan.tax_mode,
                plan_type=plan.plan_type,
                features=features,
                fetched_at=plan.fetched_at,
            )

        groups = []
        for group_name, platform_plan_ids in COMPARE_GROUPS:
            # 該分組至少一個平台有方案才顯示
            group_plans: dict[str, Optional[ComparePlanItem]] = {}
            has_any = False

            for platform_id_str in all_platforms:
                matched = None
                for pid in platform_plan_ids.get(platform_id_str, []):
                    if pid in plan_lookup.get(platform_id_str, {}):
                        matched = plan_to_item(plan_lookup[platform_id_str][pid], platform_id_str)
                        has_any = True
                        break
                group_plans[platform_id_str] = matched

            if has_any:
                groups.append(CompareGroup(group_name=group_name, platforms=group_plans))

        return CompareOut(
            country_code=country.upper(),
            currency_note="ChatGPT/Gemini 台灣定價單位為 TWD；Claude 僅提供 USD 定價",
            groups=groups,
        )


# API 路由宣告完畢後，最後才掛載前端，避免攔截 /api。
# 開發環境尚未執行 npm build 時仍可單獨啟動 API。
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
else:
    logger.warning("找不到 frontend/dist，僅啟動 API；正式部署請先執行 npm run build")

    @app.get("/", include_in_schema=False)
    def api_root():
        return {
            "service": "AI Price Compare API",
            "message": "Frontend has not been built yet.",
        }
