import asyncio
import os
import sys
from pathlib import Path
from contextlib import suppress
from typing import Optional

from loguru import logger
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import settings
from database import init_db, engine
from bot.commands import setup_bot_commands
from bot.handlers import (
    user_router,
    scan_router,
    watchlist_router,
    alerts_router,
    charts_router,
    subscriptions_router,
    top_router,
    admin_router,
    comparison_router,
    tickets_router,
    heatmap_router,
    features_router,
)
from bot.middlewares import ThrottlingMiddleware, UserCheckMiddleware
from services.scheduler import ReportScheduler


BASE_DIR = Path(__file__).resolve().parent

scheduler: Optional[ReportScheduler] = None


def _env_value(key: str, default: str = "") -> str:
    value = os.getenv(key, default).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


async def _start_fallback_http_server(reason: str):
    from aiohttp import web

    async def health(_request):
        return web.json_response(
            {
                "ok": False,
                "service": "fallback",
                "message": "Dashboard failed to start, but Railway HTTP is online.",
                "reason": str(reason)[:500],
            }
        )

    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/{tail:.*}", health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(_env_value("DASHBOARD_PORT") or _env_value("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.warning("Fallback HTTP server started on port {}", port)
    return runner


async def on_startup(bot: Bot) -> None:
    global scheduler
    logger.info("Bot started")

    scheduler = ReportScheduler(bot)
    scheduler.start()

    for admin_id in settings.admin_ids:
        with suppress(Exception):
            await bot.send_message(
                admin_id,
                "✅ Bot started. النظام يعمل بنجاح.",
            )

    await setup_bot_commands(bot)


async def on_shutdown(bot: Bot) -> None:
    global scheduler
    logger.info("Bot stopped")
    if scheduler:
        await scheduler.stop()
    await engine.dispose()


async def main() -> None:
    logger.remove()

    (BASE_DIR / "data").mkdir(parents=True, exist_ok=True)
    (BASE_DIR / "data" / "charts").mkdir(parents=True, exist_ok=True)
    (BASE_DIR / "data" / "logs").mkdir(parents=True, exist_ok=True)

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

    settings.validate()

    dashboard_runner = None
    try:
        from webapp.dashboard import start_dashboard_server

        dashboard_runner = await start_dashboard_server()
    except Exception as e:
        logger.exception("Dashboard server failed to start: {}", e)
        dashboard_runner = await _start_fallback_http_server(str(e))

    from database import init_db, engine
    await init_db()
    logger.info("Database initialized (data preserved)")

    try:
        import subprocess
        subprocess.run([sys.executable, "seed.py"], check=False, timeout=60)
        subprocess.run([sys.executable, "seed_aliases.py"], check=False, timeout=60)
        logger.info("Seed data checked (existing data preserved)")
    except Exception as e:
        logger.warning("Seed skipped: {}", e)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    dp.include_router(admin_router)
    dp.include_router(user_router)
    dp.include_router(scan_router)
    dp.include_router(watchlist_router)
    dp.include_router(alerts_router)
    dp.include_router(charts_router)
    dp.include_router(subscriptions_router)
    dp.include_router(top_router)
    dp.include_router(comparison_router)
    dp.include_router(tickets_router)
    dp.include_router(heatmap_router)
    dp.include_router(features_router)

    dp.message.middleware(ThrottlingMiddleware())
    dp.callback_query.middleware(ThrottlingMiddleware())
    dp.message.middleware(UserCheckMiddleware())
    dp.callback_query.middleware(UserCheckMiddleware())

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    try:
        await dp.start_polling(bot)
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as exc:
        logger.exception("Unhandled exception: {}", exc)
    finally:
        if dashboard_runner:
            await dashboard_runner.cleanup()
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
