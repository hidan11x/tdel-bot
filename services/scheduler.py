import asyncio
from datetime import datetime, timezone, date
from typing import List, Dict, Any, Optional

from loguru import logger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from database import get_session
from models import User
from services.scanner import scan_symbol
from services.subscriptions import check_subscription_expiry
from utils.formatter import format_technical_report
from config import settings


TOP_SYMBOLS = {
    "SAUDI": ["2222.SR", "1180.SR", "2010.SR"],
    "US": ["AAPL", "MSFT", "NVDA"],
    "CRYPTO": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
}

MARKET_NAMES = {
    "SAUDI": "السعودي",
    "US": "الأمريكي",
    "CRYPTO": "الكريبتو",
}


class ReportScheduler:
    def __init__(self, bot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler()

    def start(self):
        saudi_h, saudi_m = map(int, settings.saudi_open.split(":"))
        us_h, us_m = map(int, settings.us_open.split(":"))

        self.scheduler.add_job(
            self.send_daily_saudi_report,
            CronTrigger(hour=saudi_h - 1, minute=saudi_m),
            id="saudi_daily",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.send_daily_us_report,
            CronTrigger(hour=us_h - 1, minute=us_m),
            id="us_daily",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.send_daily_crypto_report,
            CronTrigger(hour=7, minute=0),
            id="crypto_daily",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.check_expired_subscriptions,
            CronTrigger(hour=0, minute=0),
            id="sub_check",
            replace_existing=True,
        )
        self.scheduler.start()
        logger.info("Scheduler started")

    async def stop(self):
        self.scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

    async def send_daily_saudi_report(self):
        await self._send_market_report("SAUDI")

    async def send_daily_us_report(self):
        await self._send_market_report("US")

    async def send_daily_crypto_report(self):
        await self._send_market_report("CRYPTO")

    async def send_now(self, market: str, user_id: int):
        result = await self._build_report(market)
        if not result:
            return None
        try:
            await self.bot.send_message(user_id, result[:4000])
        except Exception:
            pass
        return result

    async def _build_report(self, market: str) -> Optional[str]:
        name = MARKET_NAMES.get(market, market)
        symbols = TOP_SYMBOLS.get(market, [])
        reports = []
        for sym in symbols:
            try:
                result = await scan_symbol(sym, market)
                if result:
                    reports.append(format_technical_report(result))
            except Exception:
                continue
        if not reports:
            return None
        header = f"📊 التقرير اليومي - السوق {name}\n{datetime.now().strftime('%Y-%m-%d')}\n\n"
        return header + "\n---\n".join(reports[:3])

    async def _send_market_report(self, market: str):
        report = await self._build_report(market)
        if not report:
            return
        users = await self._get_active_users()
        for user in users:
            try:
                await self.bot.send_message(user.telegram_id, report[:4000])
                await asyncio.sleep(0.05)
            except Exception:
                continue

    async def check_expired_subscriptions(self):
        expired = await check_subscription_expiry()
        for exp in expired:
            try:
                await self.bot.send_message(
                    exp["telegram_id"],
                    "⚠️ انتهت صلاحية اشتراكك. تم تحويلك إلى الباقة المجانية.",
                )
            except Exception:
                continue

    async def _get_active_users(self):
        async with get_session() as session:
            stmt = select(User).where(
                User.is_active == True,
                User.is_banned == False,
            )
            result = await session.execute(stmt)
            users = result.scalars().all()
            return [u for u in users if getattr(u, "daily_report", True)]
