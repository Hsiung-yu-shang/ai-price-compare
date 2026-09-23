"""
SQLAlchemy 資料模型定義
使用 ORM Declarative Base，相容 SQLite / MySQL / PostgreSQL
"""
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Float, Text, DateTime,
    ForeignKey, UniqueConstraint, Index, create_engine,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def utcnow():
    return datetime.now(timezone.utc)


class Platform(Base):
    """平台基本資訊"""
    __tablename__ = "platforms"

    id = Column(Integer, primary_key=True, autoincrement=True)
    platform_id = Column(String(50), unique=True, nullable=False, comment="chatgpt / gemini / claude")
    platform_name = Column(String(100), nullable=False, comment="ChatGPT")
    vendor = Column(String(100), comment="OpenAI")
    official_url = Column(String(500))
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    plans = relationship("Plan", back_populates="platform", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Platform({self.platform_id}: {self.platform_name})>"


class Plan(Base):
    """方案與定價 (每個平台 × 國家 × 方案唯一)"""
    __tablename__ = "plans"
    __table_args__ = (
        UniqueConstraint("platform_id", "plan_id", "country_code", name="uq_plan_identity"),
        Index("ix_plans_platform_country", "platform_id", "country_code"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    platform_id = Column(Integer, ForeignKey("platforms.id"), nullable=False)
    plan_id = Column(String(50), nullable=False, comment="free / plus / pro")
    plan_name = Column(String(200), nullable=False, comment="ChatGPT Plus")
    country_code = Column(String(10), nullable=False, default="TW")
    monthly_price = Column(Float, nullable=False, default=0.0)
    annual_price = Column(Float, nullable=True, comment="年繳總價 (NULL 表示無年繳)")
    annual_monthly_price = Column(Float, nullable=True, comment="年繳平均月價")
    currency = Column(String(10), nullable=False, default="USD")
    billing_cycle = Column(String(20), nullable=False, default="monthly")
    tax_mode = Column(String(20), nullable=False, default="unknown")
    data_source = Column(String(30), default="parsed", comment="parsed / hardcoded_fallback / static")
    plan_type = Column(
        String(20), nullable=False, default="standard",
        comment="方案類型: standard / education / nonprofit (台灣教育版請標記 education)"
    )
    raw_payload = Column(Text, comment="原始 JSON 備份")
    fetched_at = Column(DateTime, nullable=False, default=utcnow, comment="最後爬取確認時間")
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    platform = relationship("Platform", back_populates="plans")
    features = relationship("PlanFeature", back_populates="plan", cascade="all, delete-orphan")
    price_history = relationship("PriceHistory", back_populates="plan", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Plan({self.plan_id} @ {self.country_code}: {self.currency} {self.monthly_price})>"


class PlanFeature(Base):
    """方案特色功能"""
    __tablename__ = "plan_features"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(Integer, ForeignKey("plans.id", ondelete="CASCADE"), nullable=False)
    feature = Column(Text, nullable=False)
    sort_order = Column(Integer, default=0)

    plan = relationship("Plan", back_populates="features")

    def __repr__(self):
        return f"<PlanFeature({self.feature[:30]})>"


class PriceHistory(Base):
    """價格異動歷史紀錄"""
    __tablename__ = "price_history"
    __table_args__ = (
        Index("ix_price_history_plan_time", "plan_id", "changed_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(Integer, ForeignKey("plans.id", ondelete="CASCADE"), nullable=False)
    old_monthly_price = Column(Float, nullable=True)
    new_monthly_price = Column(Float, nullable=False)
    old_annual_price = Column(Float, nullable=True)
    new_annual_price = Column(Float, nullable=True)
    change_type = Column(String(30), nullable=False, comment="price_change / new_plan / plan_removed")
    changed_at = Column(DateTime, default=utcnow, nullable=False)

    plan = relationship("Plan", back_populates="price_history")

    def __repr__(self):
        return f"<PriceHistory({self.change_type}: {self.old_monthly_price} → {self.new_monthly_price})>"


class CrawlLog(Base):
    """爬蟲執行紀錄"""
    __tablename__ = "crawl_logs"
    __table_args__ = (
        Index("ix_crawl_logs_platform_time", "platform_id", "executed_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    platform_id = Column(String(50), nullable=False)
    country_code = Column(String(10), nullable=False)
    status = Column(String(20), nullable=False, comment="success / failed")
    plan_count = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    executed_at = Column(DateTime, default=utcnow, nullable=False)

    def __repr__(self):
        return f"<CrawlLog({self.platform_id} @ {self.executed_at}: {self.status})>"
