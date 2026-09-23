"""
FastAPI 主應用
啟動: python -m uvicorn api.main:app --reload --port 8000
Swagger UI: http://localhost:8000/docs
ReDoc:       http://localhost:8000/redoc
"""
import sys
import logging
import hmac
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, BackgroundTasks, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# 將專案根目錄加入 sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from storage import init_db, get_session, Platform, Plan, PlanFeature, PriceHistory
from storage.diff import save_crawl_results
from config.platform_config import PLATFORMS, TIER_ORDER
from config.settings import CRAWLER_ADMIN_TOKEN
from api.schemas import (
    PlatformOut,
    PlanOut,
    PriceHistoryOut,
    CompareOut,
    CompareGroup,
    ComparePlanItem,
    CrawlerTriggerRequest,
    CrawlerTriggerOut,
    ErrorOut,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


# ── 動態建立 Crawler 對照表 (從 platform_config 自動載入) ────────────
def _build_crawler_map() -> dict:
    """
    從 PLATFORMS[x]['crawler_module'] 動態 import 爬蟲類別
    新增平台只需在 platform_config.py 設定 crawler_module，無需修改此處
    """
    import importlib
    crawlers_module = importlib.import_module("crawlers")
    crawler_map = {}
    for platform_id, cfg in PLATFORMS.items():
        class_name = cfg.get("crawler_module")
        if class_name and hasattr(crawlers_module, class_name):
            crawler_map[platform_id] = getattr(crawlers_module, class_name)
        else:
            logger.warning(f"平台 '{platform_id}' 的爬蟲 '{class_name}' 找不到，已略過")
    return crawler_map


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


CRAWLER_MAP = _build_crawler_map()
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
- 或透過 `POST /api/crawler/trigger` 手動即時觸發

## 幣別說明
台灣市場：ChatGPT 與 Gemini 為 **TWD**，Claude 為 **USD**（Anthropic 目前僅提供 USD 定價）。
    """,
    version="1.0.0",
    contact={"name": "AI Price Compare"},
    lifespan=lifespan,
    responses={500: {"model": ErrorOut}},
)


@app.get("/api/health", tags=["系統"], summary="健康檢查")
def health_check():
    """供 systemd、反向代理與部署腳本確認服務可用。"""
    return {"status": "ok"}

# CORS — 允許本機前端 Vue dev server 呼叫
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        # 本機開發
        "http://localhost:5173",
        "http://localhost:18082",
        # 正式環境 — Cloudflare Tunnel domain
        "https://aiprice.hsiungyusheng.me",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    platform: Optional[str] = Query(None, examples=["chatgpt"], description="平台識別碼篩選"),
    country: str = Query("TW", examples=["TW"], description="國家代碼篩選"),
    plan_type: Optional[str] = Query(
        None,
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
            .order_by(PriceHistory.changed_at)
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
            for h in history
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
    country: str = Query("TW", examples=["TW"], description="國家代碼"),
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


# ══════════════════════════════════════════════════════════
# 爬蟲觸發 API
# ══════════════════════════════════════════════════════════

def _run_crawlers_background(platform: Optional[str], country: str):
    """背景任務: 觸發爬蟲並儲存結果"""
    targets = [platform] if platform else list(CRAWLER_MAP.keys())
    for pid in targets:
        crawler_cls = CRAWLER_MAP.get(pid)
        if not crawler_cls:
            logger.warning(f"未知平台: {pid}，跳過")
            continue
        try:
            logger.info(f"[背景任務] 開始爬取 {pid} ({country})...")
            result = crawler_cls(country_code=country).run()
            save_crawl_results(result)
            logger.info(f"[背景任務] {pid} 完成 — 狀態: {result['status']}")
        except Exception as e:
            logger.exception(f"[背景任務] {pid} 執行失敗: {e}")


@app.post(
    "/api/crawler/trigger",
    response_model=CrawlerTriggerOut,
    summary="手動觸發爬蟲 (非同步背景執行)",
    tags=["爬蟲管理"],
    responses={400: {"model": ErrorOut}},
)
def trigger_crawler(
    body: CrawlerTriggerRequest,
    background_tasks: BackgroundTasks,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
):
    """
    立即在背景啟動指定平台的爬蟲，API 本身立即回傳 `triggered` 不等待爬蟲完成。

    - `platform` 省略時跑全部四個平台
    - 爬蟲執行狀態可查詢資料庫的 `crawl_logs` 表
    """
    if CRAWLER_ADMIN_TOKEN and not (
        x_admin_token and hmac.compare_digest(x_admin_token, CRAWLER_ADMIN_TOKEN)
    ):
        raise HTTPException(status_code=403, detail="缺少或無效的管理權杖")

    if body.platform and body.platform.lower() not in CRAWLER_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"未知平台: '{body.platform}'，可用值: {list(CRAWLER_MAP.keys())}",
        )

    platform_label = body.platform or "全部平台"
    background_tasks.add_task(
        _run_crawlers_background,
        platform=body.platform.lower() if body.platform else None,
        country=body.country.upper(),
    )

    return CrawlerTriggerOut(
        status="triggered",
        message=f"已在背景啟動 [{platform_label}] 爬蟲 (國家: {body.country.upper()})，完成後結果將自動寫入資料庫",
    )


# API 路由宣告完畢後，最後才掛載前端，避免攔截 /api 與 /docs。
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
            "docs": "/docs",
            "message": "Frontend has not been built yet.",
        }
