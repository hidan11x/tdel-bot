from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    BigInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP as PG_TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _DateTime():
    from config import settings
    if "postgresql" in settings.database_url:
        return PG_TIMESTAMP(timezone=True)
    return DateTime


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    username: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    first_name: Mapped[str] = mapped_column(String)
    language_code: Mapped[str] = mapped_column(String, default="ar")
    plan: Mapped[str] = mapped_column(String, default="free")
    subscription_start: Mapped[Optional[datetime]] = mapped_column(_DateTime(), nullable=True)
    subscription_end: Mapped[Optional[datetime]] = mapped_column(_DateTime(), nullable=True)
    scans_today: Mapped[int] = mapped_column(Integer, default=0)
    last_scan_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    referral_code: Mapped[str] = mapped_column(String, unique=True)
    referred_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    daily_report: Mapped[bool] = mapped_column(Boolean, default=True)
    referral_days: Mapped[int] = mapped_column(Integer, default=0)
    language: Mapped[str] = mapped_column(String, default="ar")
    referrals_count: Mapped[int] = mapped_column(Integer, default=0)
    referral_reward_claimed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(_DateTime(), default=_utcnow)
    last_active: Mapped[datetime] = mapped_column(_DateTime(), default=_utcnow, onupdate=_utcnow)

    referred_by_user: Mapped[Optional["User"]] = relationship(
        "User", remote_side="User.id", backref="referrals"
    )
    payments: Mapped[list["Payment"]] = relationship("Payment", back_populates="user")
    watchlists: Mapped[list["Watchlist"]] = relationship("Watchlist", back_populates="user")
    alerts: Mapped[list["Alert"]] = relationship("Alert", back_populates="user")
    scan_logs: Mapped[list["ScanLog"]] = relationship("ScanLog", back_populates="user")
    notifications: Mapped[list["Notification"]] = relationship("Notification", back_populates="user")
    daily_usage: Mapped[list["DailyUsage"]] = relationship("DailyUsage", back_populates="user")


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    scans_daily: Mapped[int] = mapped_column(Integer, default=5)
    max_alerts: Mapped[int] = mapped_column(Integer, default=3)
    max_watchlist: Mapped[int] = mapped_column(Integer, default=5)
    price_sar: Mapped[float] = mapped_column(Float, default=0.0)
    price_usd: Mapped[float] = mapped_column(Float, default=0.0)
    duration_days: Mapped[int] = mapped_column(Integer, default=0)


class ActivationCode(Base):
    __tablename__ = "activation_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String, unique=True)
    plan: Mapped[str] = mapped_column(String)
    duration_days: Mapped[int] = mapped_column(Integer)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=0)
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(_DateTime(), nullable=True)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(_DateTime(), default=_utcnow)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    plan: Mapped[str] = mapped_column(String)
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String, default="SAR")
    method: Mapped[str] = mapped_column(String, default="manual")
    status: Mapped[str] = mapped_column(String, default="completed")
    activation_code_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("activation_codes.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(_DateTime(), default=_utcnow)

    user: Mapped["User"] = relationship("User", back_populates="payments")


class Watchlist(Base):
    __tablename__ = "watchlists"
    __table_args__ = (UniqueConstraint("user_id", "symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    symbol: Mapped[str] = mapped_column(String)
    market: Mapped[str] = mapped_column(String)
    note: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    added_at: Mapped[datetime] = mapped_column(_DateTime(), default=_utcnow)

    user: Mapped["User"] = relationship("User", back_populates="watchlists")


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    symbol: Mapped[str] = mapped_column(String)
    market: Mapped[str] = mapped_column(String)
    alert_type: Mapped[str] = mapped_column(String)
    value: Mapped[float] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    triggered: Mapped[bool] = mapped_column(Boolean, default=False)
    triggered_at: Mapped[Optional[datetime]] = mapped_column(_DateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(_DateTime(), default=_utcnow)

    user: Mapped["User"] = relationship("User", back_populates="alerts")


class ScanLog(Base):
    __tablename__ = "scan_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    symbol: Mapped[str] = mapped_column(String)
    market: Mapped[str] = mapped_column(String)
    timeframe: Mapped[str] = mapped_column(String, default="daily")
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    signal: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(_DateTime(), default=_utcnow)

    user: Mapped["User"] = relationship("User", back_populates="scan_logs")


class AdminLog(Base):
    __tablename__ = "admin_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String)
    details: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(_DateTime(), default=_utcnow)


class MarketSettings(Base):
    __tablename__ = "market_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market: Mapped[str] = mapped_column(String, unique=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    data_provider: Mapped[str] = mapped_column(String, default="yfinance")
    updated_at: Mapped[datetime] = mapped_column(_DateTime(), default=_utcnow, onupdate=_utcnow)


class FeatureAccess(Base):
    __tablename__ = "feature_access"
    __table_args__ = (UniqueConstraint("telegram_id", "feature_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger)
    feature_key: Mapped[str] = mapped_column(String)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(_DateTime(), default=_utcnow)


class SystemSettings(Base):
    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String, unique=True)
    value: Mapped[str] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(_DateTime(), default=_utcnow, onupdate=_utcnow)


class ErrorLog(Base):
    __tablename__ = "error_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String)
    message: Mapped[str] = mapped_column(String)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(_DateTime(), default=_utcnow)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String)
    body: Mapped[str] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(_DateTime(), default=_utcnow)

    user: Mapped["User"] = relationship("User", back_populates="notifications")


class DailyUsage(Base):
    __tablename__ = "daily_usage"
    __table_args__ = (UniqueConstraint("user_id", "date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    date: Mapped[date] = mapped_column(Date)
    scans: Mapped[int] = mapped_column(Integer, default=0)
    alerts_triggered: Mapped[int] = mapped_column(Integer, default=0)
    ai_messages: Mapped[int] = mapped_column(Integer, default=0)

    user: Mapped["User"] = relationship("User", back_populates="daily_usage")


class Coupon(Base):
    __tablename__ = "coupons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String, unique=True)
    discount_percent: Mapped[float] = mapped_column(Float)
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(_DateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(_DateTime(), default=_utcnow)


class Symbol(Base):
    __tablename__ = "symbols"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market: Mapped[str] = mapped_column(String)
    symbol: Mapped[str] = mapped_column(String)
    yahoo_symbol: Mapped[str] = mapped_column(String)
    name_ar: Mapped[str] = mapped_column(String)
    name_en: Mapped[str] = mapped_column(String)
    sector: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    exchange: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    currency: Mapped[str] = mapped_column(String, default="SAR")
    asset_type: Mapped[str] = mapped_column(String, default="stock")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_popular: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(_DateTime(), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(_DateTime(), default=_utcnow, onupdate=_utcnow)

    aliases: Mapped[list["SymbolAlias"]] = relationship("SymbolAlias", back_populates="symbol", cascade="all, delete-orphan")


class SymbolAlias(Base):
    __tablename__ = "symbol_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol_id: Mapped[int] = mapped_column(Integer, ForeignKey("symbols.id", ondelete="CASCADE"))
    alias: Mapped[str] = mapped_column(String)
    language: Mapped[str] = mapped_column(String, default="ar")
    created_at: Mapped[datetime] = mapped_column(_DateTime(), default=_utcnow)

    symbol: Mapped["Symbol"] = relationship("Symbol", back_populates="aliases")


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    subject: Mapped[str] = mapped_column(String)
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="open")
    admin_reply: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    replied_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(_DateTime(), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(_DateTime(), default=_utcnow, onupdate=_utcnow)

    user: Mapped["User"] = relationship("User", backref="support_tickets")


class DataProviderLog(Base):
    __tablename__ = "data_provider_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String)
    endpoint: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    response_time_ms: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(_DateTime(), default=_utcnow)


class PortfolioPosition(Base):
    __tablename__ = "portfolio_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    symbol: Mapped[str] = mapped_column(String)
    market: Mapped[str] = mapped_column(String)
    entry_price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    target_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    side: Mapped[str] = mapped_column(String, default="long")
    status: Mapped[str] = mapped_column(String, default="open")
    exit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(_DateTime(), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(_DateTime(), default=_utcnow)

    user: Mapped["User"] = relationship("User", backref="portfolio_positions")


class SavedOpportunity(Base):
    __tablename__ = "saved_opportunities"
    __table_args__ = (UniqueConstraint("user_id", "symbol", "market"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    symbol: Mapped[str] = mapped_column(String)
    market: Mapped[str] = mapped_column(String)
    name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    entry_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    support: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    resistance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="watching")
    created_at: Mapped[datetime] = mapped_column(_DateTime(), default=_utcnow)

    user: Mapped["User"] = relationship("User", backref="saved_opportunities")


class PriceTracker(Base):
    __tablename__ = "price_trackers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    symbol: Mapped[str] = mapped_column(String)
    market: Mapped[str] = mapped_column(String)
    target_price: Mapped[float] = mapped_column(Float)
    direction: Mapped[str] = mapped_column(String, default="above")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    triggered: Mapped[bool] = mapped_column(Boolean, default=False)
    triggered_at: Mapped[Optional[datetime]] = mapped_column(_DateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(_DateTime(), default=_utcnow)

    user: Mapped["User"] = relationship("User", backref="price_trackers")


class SharedAnalysis(Base):
    __tablename__ = "shared_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    symbol: Mapped[str] = mapped_column(String)
    market: Mapped[str] = mapped_column(String)
    share_token: Mapped[str] = mapped_column(String, unique=True)
    views: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(_DateTime(), default=_utcnow)

    user: Mapped["User"] = relationship("User", backref="shared_analyses")


class NewsItem(Base):
    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(String, unique=True)
    source: Mapped[str] = mapped_column(String, default="yahoo")
    market: Mapped[str] = mapped_column(String, default="general")
    published_at: Mapped[Optional[datetime]] = mapped_column(_DateTime(), nullable=True)
    sent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(_DateTime(), default=_utcnow)
