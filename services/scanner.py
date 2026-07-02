import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

import pandas as pd
from loguru import logger
from sqlalchemy import select

from database import get_session
from models import User, Watchlist, DailyUsage, ScanLog
from services.market_data import get_close_prices, get_ohlcv, get_current_price_sync
from services.signal_engine import build_signal
from services.indicators import calculate_all, find_support_resistance
from services.scoring import calculate_score, get_rating, get_risk_level, generate_summary
from services.compliance import disclaimer
from config import settings


async def scan_symbol(symbol: str, market: str, timeframe: str = "1d") -> Optional[Dict[str, Any]]:
    try:
        from services.symbols_service import get_symbol_info
        sym_info = await get_symbol_info(symbol, market)

        closes = await asyncio.to_thread(get_close_prices, symbol, market, timeframe, 250)
        if not closes or len(closes) < 30:
            return None

        ohlcv = await asyncio.to_thread(get_ohlcv, symbol, market, timeframe, 250)
        current_price = await asyncio.to_thread(get_current_price_sync, symbol, market)
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
            "name_ar": sym_info["name_ar"] if sym_info else symbol,
            "name_en": sym_info["name_en"] if sym_info else symbol,
            "sector": sym_info["sector"] if sym_info else None,
            "current_price": current_price,
            "change_percent": change_percent,
            "trend": trend,
            "support": support,
            "resistance": resistance,
            "closes": closes,
            "indicators": indicators,
            "score": score,
            "rating": rating,
            "risk_level": risk_level,
            "summary": summary,
            "disclaimer": disclaimer(),
            "scanned_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        logger.exception("Failed to scan symbol={} market={} timeframe={}", symbol, market, timeframe)
        return None


async def scan_symbol_multi_timeframe(symbol: str, market: str) -> Optional[Dict[str, Any]]:
    timeframes = ["15min", "1h", "1d"]
    scans = await asyncio.gather(
        *(scan_symbol(symbol, market, tf) for tf in timeframes),
        return_exceptions=True,
    )

    valid_results: Dict[str, Dict[str, Any]] = {}
    signals: Dict[str, Any] = {}
    trend_counts: Dict[str, int] = {}
    confidence_values: List[int] = []
    reasons: List[str] = []
    warnings: List[str] = []

    for idx, item in enumerate(scans):
        tf = timeframes[idx]
        if isinstance(item, Exception):
            logger.warning("Multi-timeframe scan failed for {} {} {}", market, symbol, tf)
            warnings.append(f"تعذر جلب بيانات فريم {tf}.")
            continue
        if not item:
            warnings.append(f"بيانات فريم {tf} غير كافية.")
            continue

        valid_results[tf] = item
        signal = build_signal(item)
        signals[tf] = signal
        trend = str(item.get("trend", "sideways")).lower()
        trend_counts[trend] = trend_counts.get(trend, 0) + 1

        confidence_values.append(signal.confidence)
        reasons.extend(signal.reasons)
        warnings.extend(signal.warnings)

    if not valid_results:
        return None

    dominant_trend = "mixed"
    if trend_counts:
        trend, cnt = max(trend_counts.items(), key=lambda pair: pair[1])
        dominant_trend = trend if cnt >= 2 else "mixed"

    avg_confidence = int(round(sum(confidence_values) / len(confidence_values))) if confidence_values else 40
    if dominant_trend != "mixed" and len(valid_results) >= 2:
        avg_confidence = min(100, avg_confidence + 8)
        reasons.append("اتفاق جيد بين الفريمات يدعم الاتجاه.")
    else:
        avg_confidence = max(0, avg_confidence - 12)
        warnings.append("الفريمات متضاربة وتحتاج تاكيد.")

    best_timeframe = max(
        valid_results.keys(),
        key=lambda tf: signals[tf].confidence,
    )
    best_signal = signals[best_timeframe]

    unique_reasons = list(dict.fromkeys(reasons))[:6]
    unique_warnings = list(dict.fromkeys(warnings))[:6]

    return {
        "symbol": symbol,
        "market": market,
        "trend": dominant_trend,
        "confidence": avg_confidence,
        "rating": best_signal.rating,
        "risk_level": best_signal.risk_level,
        "timeframes": valid_results,
        "reasons": unique_reasons,
        "warnings": unique_warnings,
        "best_timeframe": best_timeframe,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


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
        except Exception as e:
            logger.warning("Failed to scan {} {}: {}", market, sym, e)
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
        except Exception as e:
            logger.warning("Failed to scan {} {}: {}", market, sym, e)
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

        today = settings.today()
        stmt = select(DailyUsage).where(
            DailyUsage.user_id == user_id,
            DailyUsage.date == today,
        )
        result = await session.execute(stmt)
        daily = result.scalar_one_or_none()
        if daily:
            daily.scans = (daily.scans or 0) + 1
        else:
            daily = DailyUsage(user_id=user_id, date=today, scans=1)
            session.add(daily)

        stmt = select(User).where(User.id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if user:
            user.scans_today = (user.scans_today or 0) + 1
            user.last_scan_date = today

        await session.commit()
