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
    if "portfolio_positions" not in tables:
        return

    columns = {col["name"] for col in inspector.get_columns("portfolio_positions")}
    dialect = sync_conn.dialect.name
    float_type = "DOUBLE PRECISION" if dialect == "postgresql" else "FLOAT"

    if "target_price" not in columns:
        sync_conn.execute(text(f"ALTER TABLE portfolio_positions ADD COLUMN target_price {float_type}"))
    if "stop_loss" not in columns:
        sync_conn.execute(text(f"ALTER TABLE portfolio_positions ADD COLUMN stop_loss {float_type}"))
