from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import settings

if settings.database_url.startswith("postgresql"):
    _url = settings.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
else:
    _url = settings.database_url

engine = create_async_engine(_url, echo=False, future=True)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    session = async_session_factory()
    try:
        yield session
    finally:
        await session.close()


async def init_db():
    from models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_run_lightweight_migrations)


def _run_lightweight_migrations(sync_conn):
    from sqlalchemy import inspect, text

    inspector = inspect(sync_conn)
    tables = set(inspector.get_table_names())
    dialect = sync_conn.dialect.name

    if "app_migrations" not in tables:
        sync_conn.execute(
            text(
                "CREATE TABLE app_migrations ("
                "migration_key VARCHAR PRIMARY KEY, "
                "applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
        )
        tables.add("app_migrations")

    if "portfolio_positions" in tables:
        columns = {col["name"] for col in inspector.get_columns("portfolio_positions")}
        float_type = "DOUBLE PRECISION" if dialect == "postgresql" else "FLOAT"

        if "target_price" not in columns:
            sync_conn.execute(text(f"ALTER TABLE portfolio_positions ADD COLUMN target_price {float_type}"))
        if "stop_loss" not in columns:
            sync_conn.execute(text(f"ALTER TABLE portfolio_positions ADD COLUMN stop_loss {float_type}"))

    if "daily_usage" in tables:
        columns = {col["name"] for col in inspector.get_columns("daily_usage")}
        if "ai_messages" not in columns:
            sync_conn.execute(text("ALTER TABLE daily_usage ADD COLUMN ai_messages INTEGER DEFAULT 0"))

    if "activation_codes" in tables:
        columns = {col["name"] for col in inspector.get_columns("activation_codes")}
        if "duration_minutes" not in columns:
            sync_conn.execute(text("ALTER TABLE activation_codes ADD COLUMN duration_minutes INTEGER DEFAULT 0"))

    if "users" in tables:
        columns = {col["name"] for col in inspector.get_columns("users")}
        if "daily_report" not in columns:
            sync_conn.execute(text("ALTER TABLE users ADD COLUMN daily_report BOOLEAN DEFAULT FALSE"))
            columns.add("daily_report")
        if "referral_reward_claimed" not in columns:
            sync_conn.execute(text("ALTER TABLE users ADD COLUMN referral_reward_claimed BOOLEAN DEFAULT FALSE"))
        if "affiliate_partner_id" not in columns:
            sync_conn.execute(text("ALTER TABLE users ADD COLUMN affiliate_partner_id INTEGER"))
        if "preferred_market" not in columns:
            sync_conn.execute(text("ALTER TABLE users ADD COLUMN preferred_market VARCHAR"))
        if "experience_level" not in columns:
            sync_conn.execute(text("ALTER TABLE users ADD COLUMN experience_level VARCHAR"))
        if "onboarding_complete" not in columns:
            sync_conn.execute(text("ALTER TABLE users ADD COLUMN onboarding_complete BOOLEAN DEFAULT FALSE"))

        migration_key = "daily_report_requires_user_opt_in"
        marker = sync_conn.execute(
            text("SELECT migration_key FROM app_migrations WHERE migration_key = :key"),
            {"key": migration_key},
        ).fetchone()
        if not marker:
            sync_conn.execute(text("UPDATE users SET daily_report = FALSE WHERE daily_report = TRUE OR daily_report IS NULL"))
            sync_conn.execute(
                text("INSERT INTO app_migrations (migration_key) VALUES (:key)"),
                {"key": migration_key},
            )

    if "price_trackers" in tables:
        columns = {col["name"] for col in inspector.get_columns("price_trackers")}
        float_type = "DOUBLE PRECISION" if dialect == "postgresql" else "FLOAT"
        if "stop_price" not in columns:
            sync_conn.execute(text(f"ALTER TABLE price_trackers ADD COLUMN stop_price {float_type}"))
        if "entry_price" not in columns:
            sync_conn.execute(text(f"ALTER TABLE price_trackers ADD COLUMN entry_price {float_type}"))
        if "target_percent" not in columns:
            sync_conn.execute(text(f"ALTER TABLE price_trackers ADD COLUMN target_percent {float_type}"))
        if "stop_percent" not in columns:
            sync_conn.execute(text(f"ALTER TABLE price_trackers ADD COLUMN stop_percent {float_type}"))
        if "quantity" not in columns:
            sync_conn.execute(text(f"ALTER TABLE price_trackers ADD COLUMN quantity {float_type}"))
        if "tracker_type" not in columns:
            sync_conn.execute(text("ALTER TABLE price_trackers ADD COLUMN tracker_type VARCHAR DEFAULT 'price'"))

    if "symbols" in tables:
        corrections = [
            ("8010.SR", "SAUDI", "التعاونية", "Tawuniya"),
            ("8020.SR", "SAUDI", "ملاذ للتأمين", "Malath Insurance"),
            ("8050.SR", "SAUDI", "سلامة للتأمين", "Salama Cooperative Insurance"),
        ]
        for symbol, market, name_ar, name_en in corrections:
            sync_conn.execute(
                text(
                    "UPDATE symbols SET name_ar = :name_ar, name_en = :name_en, "
                    "sector = COALESCE(sector, :sector), category = COALESCE(category, :sector), "
                    "exchange = COALESCE(exchange, 'Saudi Exchange'), currency = 'SAR', "
                    "asset_type = 'stock', is_active = TRUE "
                    "WHERE symbol = :symbol AND market = :market"
                ),
                {
                    "symbol": symbol,
                    "market": market,
                    "name_ar": name_ar,
                    "name_en": name_en,
                    "sector": "التأمين",
                },
            )
