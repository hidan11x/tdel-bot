import secrets
from typing import Optional
from sqlalchemy import select, func

from database import get_session
from models import SharedAnalysis, User, ScanLog

REFERRAL_REWARD_HOURS = 2


async def create_share_link(user_id: int, symbol: str, market: str) -> Optional[str]:
    token = secrets.token_urlsafe(16)
    async with get_session() as session:
        share = SharedAnalysis(
            user_id=user_id,
            symbol=symbol.upper(),
            market=market.upper(),
            share_token=token,
        )
        session.add(share)
        await session.commit()
    return token


async def increment_share_view(token: str) -> Optional[dict]:
    async with get_session() as session:
        stmt = select(SharedAnalysis).where(SharedAnalysis.share_token == token)
        result = await session.execute(stmt)
        share = result.scalar_one_or_none()
        if not share:
            return None
        share.views += 1
        await session.commit()
        return {
            "symbol": share.symbol,
            "market": share.market,
            "views": share.views,
        }


async def process_referral(referral_code: str, new_user_id: int) -> bool:
    if not referral_code or not referral_code.startswith("ref"):
        return False

    try:
        referrer_telegram_id = int(referral_code.replace("ref", ""))
    except ValueError:
        return False

    if referrer_telegram_id == new_user_id:
        return False

    async with get_session() as session:
        stmt = select(User).where(User.telegram_id == referrer_telegram_id)
        result = await session.execute(stmt)
        referrer = result.scalar_one_or_none()

        if not referrer:
            return False

        referrer.referrals_count = (referrer.referrals_count or 0) + 1
        referrer.referral_days = (referrer.referral_days or 0) + REFERRAL_REWARD_HOURS

        if referrer.subscription_end:
            from datetime import datetime, timezone, timedelta
            base = referrer.subscription_end
            if base.tzinfo is None:
                base = base.replace(tzinfo=timezone.utc)
            referrer.subscription_end = base + timedelta(hours=REFERRAL_REWARD_HOURS)
        else:
            from datetime import datetime, timezone, timedelta
            referrer.subscription_start = datetime.now(timezone.utc)
            referrer.subscription_end = datetime.now(timezone.utc) + timedelta(hours=REFERRAL_REWARD_HOURS)
            referrer.plan = "basic"

        await session.commit()
    return True


async def get_user_scan_history(user_id: int, limit: int = 50) -> list:
    async with get_session() as session:
        stmt = (
            select(ScanLog)
            .where(ScanLog.user_id == user_id)
            .order_by(ScanLog.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def export_scan_history_csv(user_id: int) -> Optional[str]:
    import csv
    import io

    logs = await get_user_scan_history(user_id)

    if not logs:
        return None

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Symbol", "Market", "Timeframe", "Score", "Price"])

    for log in logs:
        writer.writerow([
            log.created_at.strftime("%Y-%m-%d %H:%M"),
            log.symbol,
            log.market,
            log.timeframe,
            f"{log.score:.1f}" if log.score else "N/A",
            f"{log.price:.4f}" if log.price else "N/A",
        ])

    return output.getvalue()
