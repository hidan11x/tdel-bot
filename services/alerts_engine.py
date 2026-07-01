from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, date

from sqlalchemy import select, and_, update

from database import get_session
from models import Alert, User, DailyUsage
from services.market_data import get_close_prices, get_current_price_sync, get_ohlcv
from services.indicators import calculate_rsi, find_support_resistance
from config import settings


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
                async with get_session() as s:
                    alert_obj = await s.get(Alert, alert.id)
                    if alert_obj:
                        alert_obj.triggered = True
                        alert_obj.triggered_at = datetime.now(timezone.utc)
                    today = date.today()
                    dq = select(DailyUsage).where(
                        DailyUsage.user_id == alert.user_id,
                        DailyUsage.date == today,
                    )
                    dr = await s.execute(dq)
                    daily = dr.scalar_one_or_none()
                    if daily:
                        daily.alerts_triggered = DailyUsage.alerts_triggered + 1
                    await s.commit()
                triggered.append(triggered_alert)
        except Exception:
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
        return {
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
