from typing import Dict, List, Optional, Any
from datetime import datetime, timezone, date

import pandas as pd
from sqlalchemy import select, func

from database import get_session
from models import User, Watchlist, Alert, DailyUsage, ScanLog
from services.market_data import get_close_prices, get_ohlcv, get_current_price_sync
from services.indicators import calculate_all, find_support_resistance, detect_trend
from services.scoring import calculate_score, get_rating, get_risk_level, generate_summary
from services.compliance import add_disclaimer, disclaimer
from config import settings


async def scan_symbol(symbol: str, market: str, timeframe: str = "1d") -> Optional[Dict[str, Any]]:
    try:
        closes = get_close_prices(symbol, market, timeframe, outputsize=250)
        if not closes or len(closes) < 30:
            return None

        ohlcv = get_ohlcv(symbol, market, timeframe, outputsize=250)
        current_price = get_current_price_sync(symbol, market)
        if current_price is None and closes:
            current_price = closes[-1]

        prev_close = closes[-2] if len(closes) >= 2 else closes[-1]
        change_percent = ((current_price - prev_close) / prev_close) * 100 if prev_close else 0.0

        if ohlcv and len(ohlcv) > 0:
            df = pd.DataFrame(ohlcv)
        else:
            df = pd.DataFrame({"close": closes})

        indicators = calculate_all(df)
        indicators["current_price"] = current_price

        trend = indicators.get("trend", "sideways")
        support, resistance = find_support_resistance(closes, lookback=20)

        score = calculate_score(indicators)
        rating = get_rating(score.overall)
        risk_level = get_risk_level(score.risk_score)
        summary = generate_summary(score, indicators, symbol)

        return {
            "symbol": symbol,
            "market": market,
            "timeframe": timeframe,
            "current_price": current_price,
            "change_percent": change_percent,
            "trend": trend,
            "support": support,
            "resistance": resistance,
            "indicators": indicators,
            "score": score,
            "rating": rating,
            "risk_level": risk_level,
            "summary": summary,
            "disclaimer": disclaimer(),
            "scanned_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        return None


async def scan_watchlist(user_id: int) -> List[Dict[str, Any]]:
    results = []
    async with get_session() as session:
        stmt = select(Watchlist).where(Watchlist.user_id == user_id)
        items = await session.execute(stmt)
        watchlist_items = items.scalars().all()

    for item in watchlist_items:
        result = await scan_symbol(item.symbol, item.market)
        if result:
            results.append(result)
    return results


TOP_SYMBOLS = {
    "SAUDI": ["2222.SR", "2010.SR", "1120.SR", "7010.SR", "2380.SR",
              "1211.SR", "2280.SR", "1150.SR", "4164.SR", "2020.SR"],
    "US": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
           "META", "TSLA", "AMD", "JPM", "XOM"],
    "CRYPTO": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
               "ADAUSDT", "DOGEUSDT", "MATICUSDT", "LINKUSDT", "AVAXUSDT"],
}


async def get_top_movers(market: str, count: int = 10) -> List[Dict[str, Any]]:
    market_key = market.upper()
    symbols = TOP_SYMBOLS.get(market_key, [])
    results = []
    for sym in symbols:
        try:
            result = await scan_symbol(sym, market_key)
            if result:
                results.append(result)
        except Exception:
            continue
    results.sort(key=lambda r: float(r["score"].overall) if r.get("score") else 0, reverse=True)
    return results[:count]


async def get_highest_volume(market: str, count: int = 10) -> List[Dict[str, Any]]:
    market_key = market.upper()
    symbols = TOP_SYMBOLS.get(market_key, [])
    results = []
    for sym in symbols:
        try:
            result = await scan_symbol(sym, market_key)
            if result:
                results.append(result)
        except Exception:
            continue
    results.sort(key=lambda r: r.get("indicators", {}).get("volume", 0) or 0, reverse=True)
    return results[:count]


async def log_scan_to_db(user_id: int, symbol: str, market: str, timeframe: str, score: Optional[float], price: Optional[float]) -> None:
    async with get_session() as session:
        scan_log = ScanLog(
            user_id=user_id,
            symbol=symbol,
            market=market,
            timeframe=timeframe,
            score=score,
            price=price,
        )
        session.add(scan_log)

        today = date.today()
        stmt = select(DailyUsage).where(
            DailyUsage.user_id == user_id,
            DailyUsage.date == today,
        )
        result = await session.execute(stmt)
        daily = result.scalar_one_or_none()
        if daily:
            daily.scans = DailyUsage.scans + 1
        else:
            daily = DailyUsage(user_id=user_id, date=today, scans=1)
            session.add(daily)

        stmt = select(User).where(User.id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if user:
            user.scans_today = User.scans_today + 1
            user.last_scan_date = today

        await session.commit()
