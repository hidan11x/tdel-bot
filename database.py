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
        if "referral_reward_claimed" not in columns:
            sync_conn.execute(text("ALTER TABLE users ADD COLUMN referral_reward_claimed BOOLEAN DEFAULT FALSE"))
