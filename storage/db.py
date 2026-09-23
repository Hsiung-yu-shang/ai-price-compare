"""
資料庫連線與 Session 管理
支援 SQLite (本機開發) 與 MySQL (正式環境)
切換方式: 修改 config/settings.py 的 DB_URL 即可
"""
import logging
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from config.settings import DB_URL
from .models import Base

logger = logging.getLogger(__name__)

# 建立 Engine (模組層級單例)
_engine = None
_SessionFactory = None


def get_engine():
    """取得或建立資料庫 Engine (Lazy Singleton)"""
    global _engine
    if _engine is None:
        # SQLite 需要額外設定以支援 FK 約束
        connect_args = {}
        if DB_URL.startswith("sqlite"):
            connect_args["check_same_thread"] = False

        _engine = create_engine(
            DB_URL,
            echo=False,  # 設為 True 可看到所有 SQL 語句 (debug 用)
            connect_args=connect_args,
        )
        logger.info(f"資料庫 Engine 已建立: {_mask_url(DB_URL)}")
    return _engine


def get_session_factory() -> sessionmaker:
    """取得 Session 工廠"""
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine())
    return _SessionFactory


def init_db():
    """
    初始化資料庫: 建立所有表格 (IF NOT EXISTS)
    SQLite 與 MySQL 共用同一套 ORM 模型，SQLAlchemy 自動處理差異
    """
    engine = get_engine()

    # SQLite: 啟用外鍵約束 (預設關閉)
    if DB_URL.startswith("sqlite"):
        from sqlalchemy import event

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    Base.metadata.create_all(engine)
    _apply_migrations(engine)
    logger.info("資料庫表格初始化完成")


def _apply_migrations(engine):
    """
    自動補齊新欄位 (SQLite / MySQL 皆相容)
    當既有 DB 缺少新增的欄位時自動執行 ALTER TABLE，
    避免需要手動遷移或刪除舊資料庫。
    """
    from sqlalchemy import text
    dialect = engine.dialect.name

    with engine.connect() as conn:
        # ── plan_type 欄位 (區分標準版 / 教育版 / 非營利版) ──────────
        if dialect == "sqlite":
            result = conn.execute(text("PRAGMA table_info(plans)"))
            columns = [row[1] for row in result.fetchall()]
            if "plan_type" not in columns:
                conn.execute(text(
                    "ALTER TABLE plans ADD COLUMN plan_type VARCHAR(20) NOT NULL DEFAULT 'standard'"
                ))
                conn.commit()
                logger.info("DB 遷移: plans.plan_type 欄位已新增")

        elif dialect == "mysql":
            result = conn.execute(text(
                "SELECT COUNT(*) FROM information_schema.columns "
                "WHERE table_schema = DATABASE() "
                "AND table_name = 'plans' AND column_name = 'plan_type'"
            ))
            if result.scalar() == 0:
                conn.execute(text(
                    "ALTER TABLE plans ADD COLUMN "
                    "plan_type VARCHAR(20) NOT NULL DEFAULT 'standard' "
                    "COMMENT '方案類型: standard / education / nonprofit'"
                ))
                conn.commit()
                logger.info("DB 遷移: plans.plan_type 欄位已新增")


@contextmanager
def get_session():
    """
    Context Manager: 自動管理 Session 生命週期
    用法:
        with get_session() as session:
            session.query(...)
    """
    factory = get_session_factory()
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _mask_url(url: str) -> str:
    """遮蔽連線字串中的密碼 (用於 log 輸出)"""
    if "@" in url and ":" in url:
        # mysql+pymysql://user:PASSWORD@host/db → mysql+pymysql://user:***@host/db
        try:
            prefix, rest = url.split("://", 1)
            creds, host_part = rest.split("@", 1)
            user = creds.split(":")[0]
            return f"{prefix}://{user}:***@{host_part}"
        except (ValueError, IndexError):
            pass
    return url
