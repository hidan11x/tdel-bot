import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from loguru import logger
from sqlalchemy import select

from database import get_session
from models import PriceTracker, User
from services.market_data import get_current_price_sync
from services.symbols_service import get_symbol_info


async def check_price_trackers(bot) -> int:
    triggered_count = 0
    try:
        async with get_session() as session:
            stmt = select(PriceTracker).where(
                PriceTracker.is_active == True,
                PriceTracker.triggered == False,
            )
            result = await session.execute(stmt)
            trackers = result.scalars().all()

        if not trackers:
            return 0

        for tracker in trackers:
            try:
                current_price = await asyncio.to_thread(
                    get_current_price_sync, tracker.symbol, tracker.market
                )
                if current_price is None:
                    continue

                trigger_reason = ""
                should_trigger = False
                if getattr(tracker, "tracker_type", "price") == "trade":
                    if tracker.target_price and current_price >= tracker.target_price:
                        should_trigger = True
                        trigger_reason = "target"
                    elif tracker.stop_price and current_price <= tracker.stop_price:
                        should_trigger = True
                        trigger_reason = "stop"
                elif tracker.direction == "above" and current_price >= tracker.target_price:
                    should_trigger = True
                    trigger_reason = "above"
                elif tracker.direction == "below" and current_price <= tracker.target_price:
                    should_trigger = True
                    trigger_reason = "below"

                if not should_trigger:
                    continue

                async with get_session() as s:
                    t = await s.get(PriceTracker, tracker.id)
                    if t:
                        t.triggered = True
                        t.triggered_at = datetime.now(timezone.utc)
                    await s.commit()

                user_stmt = select(User).where(User.id == tracker.user_id)
                async with get_session() as s:
                    user_result = await s.execute(user_stmt)
                    user = user_result.scalar_one_or_none()

                if not user:
                    continue

                info = await get_symbol_info(tracker.symbol, tracker.market)
                name = info["name_ar"] if info else tracker.symbol

                if getattr(tracker, "tracker_type", "price") == "trade":
                    change_pct = 0.0
                    if tracker.entry_price:
                        change_pct = ((current_price - tracker.entry_price) / tracker.entry_price) * 100
                    title = "🚀 وصل هدف الربح" if trigger_reason == "target" else "⚠️ وصل وقف الخسارة"
                    message = (
                        f"{title}\n\n"
                        f"🏷 {name}\n"
                        f"🔢 {tracker.symbol}\n"
                        f"💰 السعر الحالي: {current_price:,.4f}\n"
                        f"📍 سعر الدخول: {tracker.entry_price:,.4f}\n"
                        f"📊 التغير من الدخول: {change_pct:+.2f}%\n"
                        f"🎯 الهدف: {tracker.target_price:,.4f} (+{tracker.target_percent:g}%)\n"
                        f"🛑 الوقف: {tracker.stop_price:,.4f} (-{tracker.stop_percent:g}%)\n\n"
                        f"هذا تنبيه آلي تعليمي وليس توصية مالية."
                    )
                else:
                    arrow = "📈" if tracker.direction == "above" else "📉"
                    direction_text = "وصل إلى" if tracker.direction == "above" else "انخفض إلى"
                    message = (
                        f"🎯 تنبيه سعر\n\n"
                        f"🏷 {name}\n"
                        f"🔢 {tracker.symbol}\n"
                        f"{arrow} السعر {direction_text} هدفك\n"
                        f"💰 السعر الحالي: {current_price:,.4f}\n"
                        f"🎯 السعر المستهدف: {tracker.target_price:,.4f}\n\n"
                        f"هذا تنبيه آلي تعليمي وليس توصية مالية."
                    )

                try:
                    await bot.send_message(user.telegram_id, message)
                    triggered_count += 1
                    await asyncio.sleep(0.3)
                except Exception:
                    logger.exception("Failed to send price alert to user_id={}", tracker.user_id)

            except Exception:
                logger.exception("Failed to check price tracker id={}", tracker.id)
                continue

        if triggered_count:
            logger.info("Price trackers: {} notifications sent", triggered_count)

    except Exception:
        logger.exception("check_price_trackers failed")

    return triggered_count


async def create_price_tracker(
    user_id: int, symbol: str, market: str, target_price: float, direction: str = "above"
) -> Optional[PriceTracker]:
    async with get_session() as session:
        tracker = PriceTracker(
            user_id=user_id,
            symbol=symbol.upper(),
            market=market.upper(),
            target_price=target_price,
            direction=direction,
        )
        session.add(tracker)
        await session.commit()
        await session.refresh(tracker)
        return tracker


async def create_trade_tracker(
    user_id: int,
    symbol: str,
    market: str,
    entry_price: float,
    target_percent: float,
    stop_percent: float,
    quantity: float | None = None,
) -> Optional[PriceTracker]:
    target_price = entry_price * (1 + target_percent / 100)
    stop_price = entry_price * (1 - stop_percent / 100)
    async with get_session() as session:
        tracker = PriceTracker(
            user_id=user_id,
            symbol=symbol.upper(),
            market=market.upper(),
            target_price=target_price,
            stop_price=stop_price,
            entry_price=entry_price,
            target_percent=target_percent,
            stop_percent=stop_percent,
            quantity=quantity,
            tracker_type="trade",
            direction="above",
        )
        session.add(tracker)
        await session.commit()
        await session.refresh(tracker)
        return tracker


async def get_user_price_trackers(user_id: int) -> List[PriceTracker]:
    async with get_session() as session:
        stmt = (
            select(PriceTracker)
            .where(PriceTracker.user_id == user_id, PriceTracker.is_active == True)
            .order_by(PriceTracker.created_at.desc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def deactivate_price_tracker(tracker_id: int) -> bool:
    async with get_session() as session:
        tracker = await session.get(PriceTracker, tracker_id)
        if not tracker:
            return False
        tracker.is_active = False
        await session.commit()
        return True
