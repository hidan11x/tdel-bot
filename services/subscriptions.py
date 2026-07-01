from typing import Dict, Optional, List
from datetime import datetime, timedelta, timezone, date

from sqlalchemy import select, and_, update

from database import get_session
from models import User, Plan, ActivationCode, DailyUsage, Alert, Watchlist
from config import settings


def get_plan_limits(plan_name: str) -> Dict[str, int]:
    if plan_name == "free":
        return {
            "scans_daily": settings.free_scans_daily,
            "max_alerts": settings.free_alerts,
            "max_watchlist": settings.free_watchlist,
        }
    elif plan_name == "basic":
        return {
            "scans_daily": settings.basic_scans_daily,
            "max_alerts": settings.basic_alerts,
            "max_watchlist": settings.basic_watchlist,
        }
    elif plan_name == "pro":
        return {
            "scans_daily": settings.pro_scans_daily,
            "max_alerts": settings.pro_alerts,
            "max_watchlist": settings.pro_watchlist,
        }
    elif plan_name == "vip":
        return {
            "scans_daily": settings.vip_scans_daily,
            "max_alerts": settings.vip_alerts,
            "max_watchlist": settings.vip_watchlist,
        }
    return {"scans_daily": 5, "max_alerts": 3, "max_watchlist": 5}


async def can_scan(user_id: int) -> bool:
    async with get_session() as session:
        user = await session.get(User, user_id)
        if not user:
            return False
        if user.is_banned:
            return False
        if not user.is_active:
            return False

        if user.telegram_id in settings.admin_ids:
            return True

        limits = get_plan_limits(user.plan)
        daily_limit = limits["scans_daily"]

        if daily_limit == -1:
            return True

        today = date.today()
        if user.last_scan_date != today:
            return True

        return user.scans_today < daily_limit


async def increment_scan(user_id: int) -> None:
    async with get_session() as session:
        user = await session.get(User, user_id)
        if not user:
            return
        today = date.today()
        user.scans_today = (user.scans_today if user.last_scan_date == today else 0) + 1
        user.last_scan_date = today

        dq = select(DailyUsage).where(
            DailyUsage.user_id == user_id,
            DailyUsage.date == today,
        )
        dr = await session.execute(dq)
        daily = dr.scalar_one_or_none()
        if daily:
            daily.scans = (daily.scans or 0) + 1
        else:
            daily = DailyUsage(user_id=user_id, date=today, scans=1)
            session.add(daily)

        await session.commit()


async def can_add_alert(user_id: int) -> bool:
    async with get_session() as session:
        user = await session.get(User, user_id)
        if not user:
            return False

        if user.telegram_id in settings.admin_ids:
            return True

        limits = get_plan_limits(user.plan)
        max_alerts = limits["max_alerts"]
        if max_alerts == -1:
            return True

        stmt = select(Alert).where(
            Alert.user_id == user_id,
            Alert.is_active == True,
        )
        result = await session.execute(stmt)
        active_alerts = len(result.scalars().all())
        return active_alerts < max_alerts


async def can_add_watchlist_item(user_id: int) -> bool:
    async with get_session() as session:
        user = await session.get(User, user_id)
        if not user:
            return False

        if user.telegram_id in settings.admin_ids:
            return True

        limits = get_plan_limits(user.plan)
        max_watchlist = limits["max_watchlist"]
        if max_watchlist == -1:
            return True

        stmt = select(Watchlist).where(Watchlist.user_id == user_id)
        result = await session.execute(stmt)
        count = len(result.scalars().all())
        return count < max_watchlist


async def activate_code(code: str, user_id: int) -> str:
    async with get_session() as session:
        user = await session.get(User, user_id)
        if not user:
            return "المستخدم غير موجود."

        stmt = select(ActivationCode).where(ActivationCode.code == code.strip())
        result = await session.execute(stmt)
        ac = result.scalar_one_or_none()

        if not ac:
            return "رمز التفعيل غير صالح."
        if not ac.is_active:
            return "رمز التفعيل غير نشط."
        if ac.max_uses > 0 and ac.uses >= ac.max_uses:
            return "رمز التفعيل مستنفذ."
        if ac.expires_at and ac.expires_at < datetime.now(timezone.utc):
            return "رمز التفعيل منتهي الصلاحية."

        ac.uses = (ac.uses or 0) + 1

        user.plan = ac.plan
        user.subscription_start = datetime.now(timezone.utc)

        if ac.duration_days >= 99999:
            user.subscription_end = datetime.now(timezone.utc) + timedelta(days=36525)
        else:
            user.subscription_end = datetime.now(timezone.utc) + timedelta(days=ac.duration_days)

        await session.commit()
        return f"تم تفعيل الباقة {ac.plan} بنجاح!"


async def check_subscription_expiry() -> List[Dict[str, any]]:
    expired_users = []
    async with get_session() as session:
        now = datetime.now(timezone.utc)
        stmt = select(User).where(
            User.subscription_end < now,
            User.plan != "free",
            User.is_active == True,
        )
        result = await session.execute(stmt)
        users = result.scalars().all()

        for user in users:
            user.plan = "free"
            user.subscription_start = None
            user.subscription_end = None
            expired_users.append({
                "id": user.id,
                "telegram_id": user.telegram_id,
                "username": user.username,
                "old_plan": user.plan,
            })

        await session.commit()
    return expired_users


def get_subscription_end_date(plan_name: str, user: Optional[User] = None) -> datetime:
    durations = {
        "basic": 30,
        "pro": 30,
        "vip": 30,
        "lifetime": 36525,
    }
    days = durations.get(plan_name, 30)
    return datetime.now(timezone.utc) + timedelta(days=days)


def get_trial_end_date(start_date: datetime) -> datetime:
    return start_date + timedelta(days=settings.trial_days)
