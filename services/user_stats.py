import asyncio
from typing import Optional, Dict, List
from datetime import datetime, timezone, date, timedelta
from loguru import logger
from sqlalchemy import select, func

from database import get_session
from models import User, ScanLog, Watchlist, Alert, PriceTracker


async def get_user_statistics(user_id: int) -> Optional[str]:
    try:
        now_utc = datetime.now(timezone.utc)
        month_ago = now_utc - timedelta(days=30)

        async with get_session() as session:
            user = await session.get(User, user_id)
            if not user:
                return None

            total_scans = (await session.execute(
                select(func.count(ScanLog.id)).where(ScanLog.user_id == user_id)
            )).scalar() or 0

            monthly_scans = (await session.execute(
                select(func.count(ScanLog.id)).where(
                    ScanLog.user_id == user_id,
                    ScanLog.created_at >= month_ago,
                )
            )).scalar() or 0

            top_symbols = (await session.execute(
                select(ScanLog.symbol, func.count(ScanLog.id).label("cnt"))
                .where(ScanLog.user_id == user_id)
                .group_by(ScanLog.symbol)
                .order_by(func.count(ScanLog.id).desc())
                .limit(5)
            )).all()

            watchlist_count = (await session.execute(
                select(func.count(Watchlist.id)).where(Watchlist.user_id == user_id)
            )).scalar() or 0

            active_alerts = (await session.execute(
                select(func.count(Alert.id)).where(
                    Alert.user_id == user_id,
                    Alert.is_active == True,
                )
            )).scalar() or 0

            active_trackers = (await session.execute(
                select(func.count(PriceTracker.id)).where(
                    PriceTracker.user_id == user_id,
                    PriceTracker.is_active == True,
                )
            )).scalar() or 0

            avg_score = (await session.execute(
                select(func.avg(ScanLog.score)).where(
                    ScanLog.user_id == user_id,
                    ScanLog.score is not None,
                )
            )).scalar()

            plan_names = {"free": "مجاني", "basic": "أساسي", "pro": "احترافي", "vip": "VIP", "lifetime": "مدى الحياة"}

            lines = [
                f"📊 إحصائياتك\n\n",
                f"👤 الاسم: {user.first_name}",
                f"💳 الباقة: {plan_names.get(user.plan, user.plan)}",
            ]

            if user.subscription_end:
                sub_end = user.subscription_end
                if sub_end.tzinfo is None:
                    sub_end = sub_end.replace(tzinfo=timezone.utc)
                days_left = (sub_end - now_utc).days
                if days_left > 0:
                    lines.append(f"⏰ المتبقي: {days_left} يوم")

            lines.extend([
                f"\n━━━━━━━━━━━━━━━━",
                f"📊 الفحوصات (هذا الشهر): {monthly_scans}",
                f"📊 إجمالي الفحوصات: {total_scans}",
                f"⭐ قائمة المتابعة: {watchlist_count}",
                f"🔔 التنبيهات النشطة: {active_alerts}",
                f"🎯 تتبعات الأسعار: {active_trackers}",
            ])

            if avg_score:
                lines.append(f"📈 متوسط تقييم تحليلاتك: {float(avg_score):.0f}/100")

            if top_symbols:
                lines.append("\n🏆 أكثر الرموز فحصاً:")
                for sym, cnt in top_symbols:
                    lines.append(f"  {sym}: {cnt} مرة")

            referrals = getattr(user, 'referrals_count', 0) or 0
            if referrals > 0:
                lines.append(f"\n🎁 الإحالات: {referrals}")

            lines.append("\n⚠️ إحصائيات تعليمية.")

        return "\n".join(lines)

    except Exception as e:
        logger.exception("User statistics failed: {}", e)
        return None


SAUDI_DIVIDENDS_2026 = [
    {"symbol": "2222.SR", "name": "أرامكو", "date": "2026-07-15", "amount": "متوقع"},
    {"symbol": "1120.SR", "name": "الراجحي", "date": "2026-07-20", "amount": "متوقع"},
    {"symbol": "1180.SR", "name": "البنك الأهلي", "date": "2026-08-01", "amount": "متوقع"},
    {"symbol": "1010.SR", "name": "بنك الرياض", "date": "2026-08-05", "amount": "متوقع"},
    {"symbol": "2010.SR", "name": "سابك", "date": "2026-08-10", "amount": "متوقع"},
    {"symbol": "7010.SR", "name": "stc", "date": "6-08-15", "amount": "متوقع"},
    {"symbol": "2280.SR", "name": "المراعي", "date": "2026-08-20", "amount": "متوقع"},
]


async def get_dividend_schedule() -> str:
    try:
        now = date.today()
        lines = ["📅 جدول توزيعات الأرباح القادمة\n\n"]

        upcoming = []
        for div in SAUDI_DIVIDENDS_2026:
            try:
                div_date = datetime.strptime(div["date"], "%Y-%m-%d").date()
                days_until = (div_date - now).days
                if 0 <= days_until <= 60:
                    upcoming.append((div, days_until))
            except ValueError:
                continue

        upcoming.sort(key=lambda x: x[1])

        if not upcoming:
            lines.append("لا توجد توزيعات قادمة في الفترة القريبة.")
        else:
            for div, days in upcoming:
                if days == 0:
                    lines.append(f"🔴 {div['name']} ({div['symbol']})")
                    lines.append(f"   اليوم! — {div['amount']}\n")
                elif days == 1:
                    lines.append(f"⚠️ {div['name']} ({div['symbol']})")
                    lines.append(f"   غداً — {div['amount']}\n")
                else:
                    lines.append(f"📅 {div['name']} ({div['symbol']})")
                    lines.append(f"   بعد {days} يوم — {div['amount']}\n")

        lines.append("⚠️ الجدول تقديري وقد يتغير. راجع مصادر رسمية.")
        lines.append("المصدر: تداول السعودية")

        return "\n".join(lines)

    except Exception as e:
        logger.exception("Dividend schedule failed: {}", e)
        return "❌ تعذر جلب جدول التوزيعات."
