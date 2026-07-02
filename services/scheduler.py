import asyncio
from datetime import datetime, timezone, date, timedelta
from typing import List, Dict, Any, Optional

from loguru import logger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from database import get_session
from models import User, Watchlist
from services.scanner import scan_symbol
from services.subscriptions import check_subscription_expiry
from services.signal_engine import build_signal, format_signal_message
from services.alerts_engine import check_alerts, format_alert_message, get_user_telegram_id
from services.symbols_service import get_symbol_info
from services.price_tracker import check_price_trackers
from services.market_overview import get_daily_market_summary
from services.news import send_news_notifications, get_recent_news, format_news_items
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

_WATCHLIST_DEDUP_WINDOW = timedelta(hours=4)
_WATCHLIST_DEDUP_MEMORY: Dict[str, datetime] = {}


class ReportScheduler:
    def __init__(self, bot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler(timezone=settings.timezone)

    def _cron(self, hour: int, minute: int) -> CronTrigger:
        return CronTrigger(hour=hour % 24, minute=minute, timezone=settings.timezone)

    def start(self):
        saudi_h, saudi_m = map(int, settings.saudi_open.split(":"))
        us_h, us_m = map(int, settings.us_open.split(":"))

        self.scheduler.add_job(
            self.send_daily_saudi_report,
            self._cron(saudi_h - 1, saudi_m),
            id="saudi_daily",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.send_daily_us_report,
            self._cron(us_h - 1, us_m),
            id="us_daily",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.send_daily_crypto_report,
            self._cron(7, 0),
            id="crypto_daily",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.check_expired_subscriptions,
            self._cron(0, 0),
            id="sub_check",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.check_subscription_expiry_warning,
            self._cron(10, 0),
            id="sub_expiry_warning",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.check_and_send_alerts,
            "interval",
            minutes=5,
            id="alerts_check",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.monitor_watchlists,
            "interval",
            minutes=15,
            id="watchlist_monitor",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.check_price_trackers_job,
            "interval",
            minutes=3,
            id="price_tracker_check",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.send_daily_market_summary,
            self._cron(7, 0),
            id="daily_summary",
            replace_existing=True,
        )
        if settings.news_notifications_enabled:
            self.scheduler.add_job(
                self.send_news_notifications_job,
                "interval",
                hours=settings.news_interval_hours,
                id="news_notifications",
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
        header = f"📊 التقرير اليومي - السوق {name}\n{settings.now().strftime('%Y-%m-%d')}\n\n"
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
                    "⏰ انتهى اشتراكك في البوت.\n\n"
                    "لتجديد الاشتراك تواصل مع:\n"
                    "👤 @hidanx11\n\n"
                    "أو أدخل كود تفعيل جديد من القائمة.",
                )
            except Exception:
                continue

    async def check_subscription_expiry_warning(self):
        try:
            from datetime import timedelta
            now_utc = datetime.now(timezone.utc)

            async with get_session() as session:
                stmt = select(User).where(
                    User.is_active == True,
                    User.is_banned == False,
                    User.plan != "free",
                )
                result = await session.execute(stmt)
                users = result.scalars().all()

            for user in users:
                if user.subscription_end is None:
                    continue
                sub_end = user.subscription_end
                if sub_end.tzinfo is None:
                    sub_end = sub_end.replace(tzinfo=timezone.utc)

                days_left = (sub_end - now_utc).days

                if days_left == 2:
                    try:
                        await self.bot.send_message(
                            user.telegram_id,
                            f"⚠️ اشتراكك ينتهي بعد يومين!\n\n"
                            f"الخطة: {user.plan}\n"
                            f"تاريخ الانتهاء: {sub_end.strftime('%Y-%m-%d')}\n\n"
                            f"لتجديد الاشتراك تواصل مع:\n👤 @hidanx11",
                        )
                    except Exception:
                        continue
                elif days_left == 1:
                    try:
                        await self.bot.send_message(
                            user.telegram_id,
                            f"🔴 اشتراكك ينتهي غداً!\n\n"
                            f"الخطة: {user.plan}\n\n"
                            f"لتجديد الاشتراك تواصل مع:\n👤 @hidanx11",
                        )
                    except Exception:
                        continue

        except Exception:
            logger.exception("check_subscription_expiry_warning failed")

    async def send_update_notification(self, update_text: str):
        try:
            async with get_session() as session:
                stmt = select(User).where(
                    User.is_active == True,
                    User.is_banned == False,
                )
                result = await session.execute(stmt)
                users = result.scalars().all()

            sent = 0
            for user in users:
                try:
                    await self.bot.send_message(user.telegram_id, update_text[:4000])
                    sent += 1
                    await asyncio.sleep(0.05)
                except Exception:
                    continue

            logger.info("Update notification sent to {} users", sent)
            return sent
        except Exception:
            logger.exception("send_update_notification failed")
            return 0

    async def check_and_send_alerts(self):
        try:
            triggered = await check_alerts()
            if not triggered:
                return

            for alert_payload in triggered:
                try:
                    telegram_id = await get_user_telegram_id(alert_payload["user_id"])
                    if not telegram_id:
                        continue

                    info = await get_symbol_info(
                        alert_payload["symbol"],
                        alert_payload["market"],
                    )
                    name_ar = info["name_ar"] if info else alert_payload["symbol"]
                    sector = info["sector"] if info else None

                    message = format_alert_message(alert_payload, name_ar, sector)
                    await self.bot.send_message(telegram_id, message[:4000])
                    logger.info(
                        "Alert sent to user_id={} symbol={}",
                        alert_payload["user_id"],
                        alert_payload["symbol"],
                    )
                    await asyncio.sleep(0.3)
                except Exception:
                    logger.exception("Failed to send alert to user_id={}", alert_payload.get("user_id"))
                    continue
        except Exception:
            logger.exception("check_and_send_alerts failed")

    async def monitor_watchlists(self):
        try:
            async with get_session() as session:
                stmt = select(Watchlist).where(
                    Watchlist.user_id.in_(
                        select(User.id).where(User.is_active == True, User.is_banned == False)
                    )
                )
                result = await session.execute(stmt)
                items = result.scalars().all()

            if not items:
                return

            unique_symbols: Dict[str, Dict] = {}
            for item in items:
                key = f"{item.symbol}:{item.market}"
                if key not in unique_symbols:
                    unique_symbols[key] = {"symbol": item.symbol, "market": item.market}

            scans: Dict[str, Optional[Dict]] = {}
            for key, info in unique_symbols.items():
                try:
                    result = await scan_symbol(info["symbol"], info["market"], "1d")
                    scans[key] = result
                except Exception:
                    scans[key] = None

            now_dt = datetime.now(timezone.utc)
            sent_count = 0

            for item in items:
                key = f"{item.symbol}:{item.market}"
                result = scans.get(key)
                if not result:
                    continue

                change_pct = result.get("change_percent", 0)
                trend = result.get("trend", "sideways")
                score = result.get("score")
                score_val = float(score.overall) if score else 0

                should_notify = False
                reason = ""

                if abs(change_pct) >= 3.0:
                    should_notify = True
                    sign = "+" if change_pct >= 0 else ""
                    reason = f"تغير ملحوظ في السعر: {sign}{change_pct:.2f}%"

                if trend in ("uptrend", "downtrend") and score_val >= 65:
                    should_notify = True
                    trend_ar = "صاعد" if trend == "uptrend" else "هابط"
                    reason = f"الاتجاه {trend_ar} مع قراءة فنية قوية ({score_val:.0f}/100)"

                if not should_notify:
                    continue

                dedup_key = f"wl:{item.user_id}:{item.symbol}:{item.market}"
                last_sent = _WATCHLIST_DEDUP_MEMORY.get(dedup_key)
                if last_sent and (now_dt - last_sent) < _WATCHLIST_DEDUP_WINDOW:
                    continue

                try:
                    telegram_id = await get_user_telegram_id(item.user_id)
                    if not telegram_id:
                        continue

                    info = await get_symbol_info(item.symbol, item.market)
                    name_ar = info["name_ar"] if info else item.symbol
                    sector = info["sector"] if info else None
                    market_label = MARKET_NAMES.get(item.market, item.market)

                    signal = build_signal(result)
                    signal_msg = format_signal_message(signal)

                    message = (
                        f"⭐ تنبيه من قائمة المتابعة\n\n"
                        f"🏷 {name_ar}\n"
                        f"🔢 {item.symbol}\n"
                        f"🌍 السوق {market_label}\n"
                        f"📋 {reason}\n\n"
                        f"{'─' * 22}\n\n"
                        f"{signal_msg}"
                    )

                    await self.bot.send_message(telegram_id, message[:4000])
                    _WATCHLIST_DEDUP_MEMORY[dedup_key] = now_dt
                    sent_count += 1
                    await asyncio.sleep(0.3)
                except Exception:
                    logger.exception("Failed to send watchlist alert user_id={}", item.user_id)
                    continue

            if sent_count:
                logger.info("Watchlist monitor sent {} notifications", sent_count)
        except Exception:
            logger.exception("monitor_watchlists failed")

    async def check_price_trackers_job(self):
        try:
            count = await check_price_trackers(self.bot)
            if count:
                logger.info("Price trackers: {} triggered", count)
        except Exception:
            logger.exception("check_price_trackers_job failed")

    async def send_daily_market_summary(self):
        try:
            summary = await get_daily_market_summary()
            if not summary:
                return
            users = await self._get_active_users()
            for user in users:
                try:
                    await self.bot.send_message(user.telegram_id, summary[:4000])
                    await asyncio.sleep(0.05)
                except Exception:
                    continue
            logger.info("Daily market summary sent to {} users", len(users))
        except Exception:
            logger.exception("send_daily_market_summary failed")

    async def send_news_notifications_job(self):
        try:
            count = await send_news_notifications(self.bot)
            if count:
                logger.info("News notifications: {} sent", count)
        except Exception:
            logger.exception("send_news_notifications_job failed")

    async def _get_active_users(self):
        async with get_session() as session:
            stmt = select(User).where(
                User.is_active == True,
                User.is_banned == False,
            )
            result = await session.execute(stmt)
            users = result.scalars().all()
            return [u for u in users if getattr(u, "daily_report", True)]
