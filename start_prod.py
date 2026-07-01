import asyncio
import sys
from pathlib import Path

from loguru import logger


async def startup():
    BASE_DIR = Path(__file__).resolve().parent
    for d in ["data", "data/charts", "data/logs", "data/pdfs"]:
        (BASE_DIR / d).mkdir(parents=True, exist_ok=True)

    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> - <level>{message}</level>",
        level="INFO",
    )
    logger.add(
        BASE_DIR / "data" / "logs" / "bot_{time:YYYY-MM-DD}.log",
        rotation="1 day",
        retention="30 days",
        level="DEBUG",
    )

    from config import settings
    settings.validate()
    logger.info("Config validated")

    from database import init_db, engine
    from models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        logger.info("Dropped old tables (fresh schema)")
    await init_db()
    logger.info("Database initialized")

    try:
        import subprocess
        subprocess.run([sys.executable, "seed.py"], check=False, timeout=60)
        logger.info("Seed data inserted")
    except Exception as e:
        logger.warning("Seed skipped (may already exist): {}", e)

    try:
        subprocess.run([sys.executable, "seed_aliases.py"], check=False, timeout=60)
        logger.info("Aliases seeded")
    except Exception as e:
        logger.warning("Aliases seed skipped: {}", e)

    from aiogram import Bot, Dispatcher
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    from bot.handlers import (
        user_router, scan_router, watchlist_router, alerts_router,
        charts_router, subscriptions_router, top_router, admin_router,
        comparison_router, tickets_router, heatmap_router, features_router,
    )
    from bot.middlewares import ThrottlingMiddleware, UserCheckMiddleware
    from services.scheduler import ReportScheduler

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    for r in [
        user_router, scan_router, watchlist_router, alerts_router,
        charts_router, subscriptions_router, top_router, admin_router,
        comparison_router, tickets_router, heatmap_router,
    ]:
        dp.include_router(r)

    dp.message.middleware(ThrottlingMiddleware())
    dp.callback_query.middleware(ThrottlingMiddleware())
    dp.message.middleware(UserCheckMiddleware())
    dp.callback_query.middleware(UserCheckMiddleware())

    scheduler = ReportScheduler(bot)
    scheduler.start()

    from contextlib import suppress
    for admin_id in settings.admin_ids:
        with suppress(Exception):
            await bot.send_message(admin_id, "✅ Bot started on Railway. النظام يعمل.")

    logger.info("Bot started on Railway")
    try:
        await dp.start_polling(bot)
    finally:
        await scheduler.stop()
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(startup())
    except (KeyboardInterrupt, SystemExit):
        pass
