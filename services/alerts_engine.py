from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, date, timedelta

from sqlalchemy import select
from loguru import logger

from database import get_session
from models import Alert, User, DailyUsage
from services.market_data import get_close_prices, get_current_price_sync, get_ohlcv
from services.indicators import calculate_rsi, find_support_resistance
from services.scanner import scan_symbol
from services.signal_engine import build_signal
from services.symbols_service import get_symbol_info
from config import settings


ALERT_TYPE_NAMES = {
    "price_above": "السعر أعلى من",
    "price_below": "السعر أدنى من",
    "rsi_above": "RSI أعلى من",
    "rsi_below": "RSI أدنى من",
    "volume_spike": "ارتفاع حاد في الحجم",
    "near_support": "اقتراب من الدعم",
    "near_resistance": "اقتراب من المقاومة",
    "price_change_percent": "نسبة تغير السعر",
}


_ALERT_DEDUP_WINDOW = timedelta(hours=6)
_ALERT_DEDUP_MEMORY: Dict[str, datetime] = {}


def _dedup_key(user_id: int, symbol: str, market: str) -> str:
    return f"{user_id}:{symbol.upper()}:{market.upper()}"


def _is_duplicate_recent(user_id: int, symbol: str, market: str, now_dt: datetime) -> bool:
    key = _dedup_key(user_id, symbol, market)
    previous = _ALERT_DEDUP_MEMORY.get(key)
    if not previous:
        return False
    return (now_dt - previous) < _ALERT_DEDUP_WINDOW


def _remember_alert(user_id: int, symbol: str, market: str, now_dt: datetime) -> None:
    key = _dedup_key(user_id, symbol, market)
    _ALERT_DEDUP_MEMORY[key] = now_dt


async def _enrich_with_signal(alert_payload: Dict[str, Any]) -> Dict[str, Any]:
    result = await scan_symbol(alert_payload["symbol"], alert_payload["market"], "1d")
    if not result:
        return alert_payload

    signal = build_signal(result)
    alert_payload["confidence"] = signal.confidence
    alert_payload["score"] = signal.score
    alert_payload["rating"] = signal.rating
    alert_payload["risk_level"] = signal.risk_level
    alert_payload["warnings"] = list(signal.warnings)

    if signal.risk_level in ("مرتفع", "عالي", "عالي جداً"):
        warning_text = "⚠️ المخاطرة مرتفعة، الإشارة للمتابعة فقط وتحتاج تاكيد."
        alert_payload["risk_warning"] = warning_text

    return alert_payload


def _is_signal_strong(alert_payload: Dict[str, Any]) -> bool:
    score = float(alert_payload.get("score") or 0.0)
    confidence = int(alert_payload.get("confidence") or 0)
    return score >= 60 or confidence >= 60


async def check_alerts() -> List[Dict[str, Any]]:
    triggered = []
    async with get_session() as session:
        stmt = select(Alert).where(
            Alert.is_active == True,
            Alert.triggered == False,
        )
        result = await session.execute(stmt)
        alerts = result.scalars().all()

    for alert in alerts:
        try:
            triggered_alert = await _check_single_alert(alert)
            if triggered_alert:
                now_dt = datetime.now(timezone.utc)
                triggered_alert = await _enrich_with_signal(triggered_alert)

                if not _is_signal_strong(triggered_alert):
                    logger.info(
                        "Skip weak alert user_id={} symbol={} market={}",
                        alert.user_id,
                        alert.symbol,
                        alert.market,
                    )
                    continue

                if _is_duplicate_recent(alert.user_id, alert.symbol, alert.market, now_dt):
                    logger.info(
                        "Skip duplicate alert in dedup window user_id={} symbol={} market={}",
                        alert.user_id,
                        alert.symbol,
                        alert.market,
                    )
                    continue

                async with get_session() as s:
                    alert_obj = await s.get(Alert, alert.id)
                    if alert_obj:
                        alert_obj.triggered = True
                        alert_obj.triggered_at = now_dt
                    today = date.today()
                    dq = select(DailyUsage).where(
                        DailyUsage.user_id == alert.user_id,
                        DailyUsage.date == today,
                    )
                    dr = await s.execute(dq)
                    daily = dr.scalar_one_or_none()
                    if daily:
                        daily.alerts_triggered = (daily.alerts_triggered or 0) + 1
                    await s.commit()
                _remember_alert(alert.user_id, alert.symbol, alert.market, now_dt)
                triggered.append(triggered_alert)
        except Exception:
            logger.exception("Failed while checking alert id={}", alert.id)
            continue

    return triggered


async def _check_single_alert(alert: Alert) -> Optional[Dict[str, Any]]:
    current_price = get_current_price_sync(alert.symbol, alert.market)
    if current_price is None:
        return None

    alert_type = alert.alert_type
    value = alert.value

    triggered = False
    extra = {}

    if alert_type == "price_above":
        triggered = current_price > value
    elif alert_type == "price_below":
        triggered = current_price < value
    elif alert_type in ("rsi_above", "rsi_below"):
        closes = get_close_prices(alert.symbol, alert.market, "1d", 50)
        if len(closes) >= 15:
            rsi = calculate_rsi(closes)
            if rsi is not None:
                if alert_type == "rsi_above":
                    triggered = rsi > value
                elif alert_type == "rsi_below":
                    triggered = rsi < value
                extra["rsi"] = rsi
    elif alert_type == "volume_spike":
        ohlcv = get_ohlcv(alert.symbol, alert.market, "1d", 30)
        if ohlcv and len(ohlcv) >= 20:
            volumes = [d["volume"] for d in ohlcv]
            avg_vol = sum(volumes[:-1]) / (len(volumes) - 1) if len(volumes) > 1 else 0
            current_vol = volumes[-1]
            if avg_vol > 0 and current_vol > avg_vol * 1.5:
                triggered = True
                extra["volume"] = current_vol
                extra["avg_volume"] = avg_vol
    elif alert_type == "near_support":
        closes = get_close_prices(alert.symbol, alert.market, "1d", 50)
        if closes:
            support, _ = find_support_resistance(closes, lookback=20)
            if support and support > 0:
                distance = abs(current_price - support) / current_price * 100
                triggered = distance <= 2.0
                extra["support"] = support
                extra["distance_pct"] = distance
    elif alert_type == "near_resistance":
        closes = get_close_prices(alert.symbol, alert.market, "1d", 50)
        if closes:
            _, resistance = find_support_resistance(closes, lookback=20)
            if resistance and resistance > 0:
                distance = abs(resistance - current_price) / current_price * 100
                triggered = distance <= 2.0
                extra["resistance"] = resistance
                extra["distance_pct"] = distance
    elif alert_type == "price_change_percent":
        closes = get_close_prices(alert.symbol, alert.market, "1d", 5)
        if len(closes) >= 2:
            change = ((closes[-1] - closes[-2]) / closes[-2]) * 100
            triggered = abs(change) > value
            extra["change_percent"] = change

    if triggered:
        payload = {
            "alert_id": alert.id,
            "user_id": alert.user_id,
            "symbol": alert.symbol,
            "market": alert.market,
            "alert_type": alert_type,
            "value": value,
            "current_price": current_price,
            "extra": extra,
            "triggered_at": datetime.now(timezone.utc).isoformat(),
        }
        return payload
    return None


async def create_alert(user_id: int, symbol: str, market: str, alert_type: str, value: float) -> Optional[Alert]:
    async with get_session() as session:
        alert = Alert(
            user_id=user_id,
            symbol=symbol.upper(),
            market=market.upper(),
            alert_type=alert_type,
            value=value,
        )
        session.add(alert)
        await session.commit()
        await session.refresh(alert)
        return alert


async def disable_alert(alert_id: int) -> bool:
    async with get_session() as session:
        alert = await session.get(Alert, alert_id)
        if not alert:
            return False
        alert.is_active = False
        await session.commit()
        return True


async def get_user_alerts(user_id: int) -> List[Alert]:
    async with get_session() as session:
        stmt = select(Alert).where(Alert.user_id == user_id).order_by(Alert.created_at.desc())
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def get_user_telegram_id(user_id: int) -> Optional[int]:
    async with get_session() as session:
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        return user.telegram_id if user else None


def _format_price_simple(value) -> str:
    if value is None:
        return "غير متوفر"
    try:
        v = float(value)
    except Exception:
        return str(value)
    if v >= 1000:
        return f"{v:,.2f}"
    if v >= 1:
        return f"{v:.4f}"
    return f"{v:.6f}"


def format_alert_message(alert_payload: Dict[str, Any], name_ar: str = None, sector: str = None) -> str:
    symbol = alert_payload.get("symbol", "")
    market = alert_payload.get("market", "")
    alert_type = alert_payload.get("alert_type", "")
    value = alert_payload.get("value")
    current_price = alert_payload.get("current_price")
    extra = alert_payload.get("extra", {})
    confidence = alert_payload.get("confidence")
    risk_level = alert_payload.get("risk_level", "")
    risk_warning = alert_payload.get("risk_warning")
    warnings = alert_payload.get("warnings", [])

    display_name = name_ar or symbol
    type_name = ALERT_TYPE_NAMES.get(alert_type, alert_type)
    market_label = {"SAUDI": "السعودي", "US": "الأمريكي", "CRYPTO": "الرقمية"}.get(market, market)

    lines = [
        "🔔 تنبيه نشط\n",
        f"🏷 الأصل: {display_name}",
        f"🔢 الرمز: {symbol}",
        f"🌍 السوق: {market_label}",
    ]
    if sector:
        lines.append(f"🏢 القطاع: {sector}")
    lines.append(f"{'─' * 22}")
    lines.append(f"📋 نوع التنبيه: {type_name}")
    lines.append(f"🎯 القيمة المستهدفة: {_format_price_simple(value)}")
    lines.append(f"💰 السعر الحالي: {_format_price_simple(current_price)}")

    if extra:
        if "rsi" in extra:
            lines.append(f"📊 RSI الحالي: {extra['rsi']:.1f}")
        if "change_percent" in extra:
            change = extra["change_percent"]
            sign = "+" if change >= 0 else ""
            lines.append(f"📈 نسبة التغير: {sign}{change:.2f}%")
        if "distance_pct" in extra:
            lines.append(f"📏 المسافة: {extra['distance_pct']:.1f}%")
        if "volume" in extra:
            lines.append(f"📦 الحجم: {_format_price_simple(extra['volume'])}")

    if confidence is not None:
        lines.append(f"🎯 الثقة: {confidence}/100")

    if risk_level:
        lines.append(f"⚠️ المخاطرة: {risk_level}")

    if risk_warning:
        lines.append(f"\n{risk_warning}")
    elif warnings:
        lines.append("\nتحذيرات:")
        for w in warnings[:3]:
            lines.append(f"* {w}")

    lines.append("\nهذا تنبيه آلي تعليمي وليس توصية مالية.")
    return "\n".join(lines)
