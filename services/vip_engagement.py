from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from config import settings
from database import get_session
from models import (
    Alert,
    ContestPrediction,
    LoyaltyEvent,
    PortfolioPosition,
    ScanLog,
    User,
    Watchlist,
)
from services.market_data import get_current_price_sync
from services.market_overview import get_daily_market_summary
from services.opportunities import flatten_radar, get_radar_opportunities
from services.search_engine import auto_detect_symbol


LOYALTY_VALUES = {
    "scan": 1,
    "watchlist": 3,
    "alert": 5,
    "portfolio": 8,
    "contest": 10,
    "referral": 30,
}


def _fmt(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "غير متوفر"
    if abs(value) >= 1000:
        return f"{value:,.{digits}f}"
    if abs(value) >= 1:
        return f"{value:.{digits}f}"
    return f"{value:.6f}"


async def award_points(user_id: int, event_type: str, points: int | None = None, note: str = "") -> int:
    value = int(points if points is not None else LOYALTY_VALUES.get(event_type, 1))
    if value == 0:
        return 0
    async with get_session() as session:
        session.add(LoyaltyEvent(user_id=user_id, event_type=event_type, points=value, note=note[:180]))
        await session.commit()
    return value


async def get_loyalty_summary(user_id: int) -> dict[str, Any]:
    async with get_session() as session:
        total = (
            await session.execute(
                select(func.coalesce(func.sum(LoyaltyEvent.points), 0)).where(LoyaltyEvent.user_id == user_id)
            )
        ).scalar() or 0
        events = (
            await session.execute(
                select(LoyaltyEvent)
                .where(LoyaltyEvent.user_id == user_id)
                .order_by(LoyaltyEvent.created_at.desc())
                .limit(8)
            )
        ).scalars().all()
    vip_hours = int(total // 120)
    return {
        "points": int(total),
        "vip_hours": vip_hours,
        "events": events,
        "next_reward_points": max(0, 120 - (int(total) % 120)),
    }


async def submit_contest_prediction(telegram_id: int, text: str) -> tuple[bool, str]:
    parts = text.replace("|", " ").split()
    if len(parts) < 2:
        return False, "اكتبها بهذا الشكل: الرمز السعر المتوقع\nمثال: الراجحي 67.5"

    raw_symbol = parts[0].strip()
    try:
        target_price = float(parts[1].replace(",", ""))
    except ValueError:
        return False, "السعر المتوقع لازم يكون رقم. مثال: AAPL 210"

    detected = await auto_detect_symbol(raw_symbol)
    if not detected:
        return False, "ما قدرت أتعرف على الرمز. جرب: الراجحي، AAPL، BTCUSDT"

    async with get_session() as session:
        user = (
            await session.execute(select(User).where(User.telegram_id == telegram_id))
        ).scalar_one_or_none()
        if not user:
            return False, "المستخدم غير موجود."

        prediction = ContestPrediction(
            user_id=user.id,
            symbol=detected["symbol"],
            market=detected["market"],
            target_price=target_price,
            prediction_date=settings.today(),
        )
        session.add(prediction)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return False, "شاركت اليوم بالفعل. تقدر تشارك مرة واحدة يومياً."

        await session.refresh(prediction)

    await award_points(user.id, "contest", LOYALTY_VALUES["contest"], f"{prediction.symbol} {_fmt(target_price)}")
    name = detected.get("name_ar") or detected.get("name_en") or prediction.symbol
    return True, (
        "تم تسجيل توقعك اليومي.\n\n"
        f"الأصل: {name} ({prediction.symbol})\n"
        f"السوق: {prediction.market}\n"
        f"توقعك: {_fmt(target_price, 4)}\n"
        f"نقاط المشاركة: +{LOYALTY_VALUES['contest']}\n\n"
        "بنهاية اليوم تقدر تقارن توقعك مع السعر الفعلي من صفحة المسابقة."
    )


async def get_contest_summary(user_id: int) -> str:
    today = settings.today()
    async with get_session() as session:
        my_prediction = (
            await session.execute(
                select(ContestPrediction)
                .where(ContestPrediction.user_id == user_id, ContestPrediction.prediction_date == today)
                .order_by(ContestPrediction.created_at.desc())
            )
        ).scalar_one_or_none()
        leaders = (
            await session.execute(
                select(User.first_name, func.coalesce(func.sum(ContestPrediction.score_points), 0).label("points"))
                .join(ContestPrediction, ContestPrediction.user_id == User.id)
                .group_by(User.id, User.first_name)
                .order_by(func.coalesce(func.sum(ContestPrediction.score_points), 0).desc())
                .limit(5)
            )
        ).all()

    lines = [
        "مسابقة التوقع اليومي",
        "",
        "اكتب رمز أو اسم السهم مع سعر الإغلاق المتوقع.",
        "مثال: الراجحي 67.5",
        "مثال: AAPL 210",
        "مثال: BTCUSDT 65000",
        "",
    ]
    if my_prediction:
        current = get_current_price_sync(my_prediction.symbol, my_prediction.market)
        diff = None
        if current:
            diff = abs(current - my_prediction.target_price) / current * 100
        lines.extend(
            [
                "توقعك اليوم:",
                f"{my_prediction.symbol} | المتوقع {_fmt(my_prediction.target_price, 4)}",
                f"السعر الحالي: {_fmt(current, 4)}",
            ]
        )
        if diff is not None:
            lines.append(f"الفرق الحالي: {diff:.2f}%")
        lines.append("")

    if leaders:
        lines.append("أفضل المشاركين:")
        for index, row in enumerate(leaders, 1):
            lines.append(f"{index}. {row.first_name}: {int(row.points)} نقطة")

    return "\n".join(lines).strip()


async def evaluate_contest_predictions(prediction_date: date | None = None) -> list[dict[str, Any]]:
    target_date = prediction_date or settings.today()
    async with get_session() as session:
        predictions = (
            await session.execute(
                select(ContestPrediction, User.telegram_id, User.first_name)
                .join(User, User.id == ContestPrediction.user_id)
                .where(
                    ContestPrediction.prediction_date == target_date,
                    ContestPrediction.actual_price.is_(None),
                )
            )
        ).all()

    results: list[dict[str, Any]] = []
    for prediction, telegram_id, first_name in predictions:
        actual = get_current_price_sync(prediction.symbol, prediction.market)
        if actual is None or actual <= 0:
            continue
        diff_pct = abs(actual - prediction.target_price) / actual * 100
        score_points = max(0, int(round(100 - (diff_pct * 20))))
        results.append(
            {
                "id": prediction.id,
                "user_id": prediction.user_id,
                "telegram_id": telegram_id,
                "first_name": first_name,
                "symbol": prediction.symbol,
                "market": prediction.market,
                "target_price": prediction.target_price,
                "actual_price": actual,
                "diff_pct": diff_pct,
                "score_points": score_points,
            }
        )

    if not results:
        return []

    async with get_session() as session:
        for item in results:
            prediction = await session.get(ContestPrediction, item["id"])
            if prediction:
                prediction.actual_price = item["actual_price"]
                prediction.score_points = item["score_points"]
        await session.commit()

    for item in results:
        if item["score_points"] >= 70:
            await award_points(
                item["user_id"],
                "contest_win",
                max(10, item["score_points"] // 2),
                f"{item['symbol']} diff {item['diff_pct']:.2f}%",
            )

    return sorted(results, key=lambda item: item["diff_pct"])


async def build_vip_center_text(user: User) -> str:
    today = settings.today()
    async with get_session() as session:
        watchlist_count = (
            await session.execute(select(func.count(Watchlist.id)).where(Watchlist.user_id == user.id))
        ).scalar() or 0
        alerts_count = (
            await session.execute(
                select(func.count(Alert.id)).where(Alert.user_id == user.id, Alert.is_active == True)
            )
        ).scalar() or 0
        positions = (
            await session.execute(
                select(PortfolioPosition).where(PortfolioPosition.user_id == user.id, PortfolioPosition.status == "open")
            )
        ).scalars().all()
        scans_today = (
            await session.execute(
                select(func.count(ScanLog.id)).where(ScanLog.user_id == user.id, func.date(ScanLog.created_at) == today)
            )
        ).scalar() or 0

    portfolio_value = 0.0
    portfolio_pnl = 0.0
    for position in positions:
        current = get_current_price_sync(position.symbol, position.market)
        if current is None:
            continue
        portfolio_value += current * position.quantity
        multiplier = -1 if position.side == "short" else 1
        portfolio_pnl += (current - position.entry_price) * position.quantity * multiplier

    loyalty = await get_loyalty_summary(user.id)
    radar = await get_radar_opportunities(vip=True)
    top_items = flatten_radar(radar)[:3]

    lines = [
        "مركز VIP",
        "",
        f"الخطة: {user.plan}",
        f"فحوصات اليوم: {scans_today}",
        f"قائمة المتابعة: {watchlist_count}",
        f"التنبيهات النشطة: {alerts_count}",
        f"الصفقات المفتوحة: {len(positions)}",
        f"قيمة المحفظة التقريبية: {_fmt(portfolio_value)}",
        f"ربح/خسارة المحفظة: {_fmt(portfolio_pnl)}",
        "",
        f"نقاط الولاء: {loyalty['points']} نقطة",
        f"المتبقي للمكافأة القادمة: {loyalty['next_reward_points']} نقطة",
        "",
        "أفضل فرص الآن:",
    ]
    if top_items:
        for index, item in enumerate(top_items, 1):
            score = item.get("score")
            score_value = float(score.overall) if score else 0
            lines.append(f"{index}. {item.get('symbol')} | {item.get('market')} | {score_value:.0f}/100")
    else:
        lines.append("لا توجد فرص واضحة الآن.")

    lines.append("")
    lines.append("كل الأرقام قراءة آلية تعليمية وليست توصية مالية.")
    return "\n".join(lines)


async def build_market_pulse_text() -> str:
    summary = await get_daily_market_summary()
    if not summary:
        return "نبض السوق غير متاح حالياً. جرب بعد قليل."
    return summary[:3900]
