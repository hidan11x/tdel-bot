import asyncio
from typing import List, Dict, Optional, Any
from loguru import logger

from services.scanner import scan_symbol, TOP_SYMBOLS
from services.symbols_service import get_symbol_info
from services.indicators import _ensure_list


SCREENERS = {
    "oversold": {
        "name_ar": "تشبع بيعي (RSI < 30)",
        "name_en": "Oversold (RSI < 30)",
        "filter": lambda r: _get_rsi(r) is not None and _get_rsi(r) < 30,
    },
    "overbought": {
        "name_ar": "تشبع شرائي (RSI > 70)",
        "name_en": "Overbought (RSI > 70)",
        "filter": lambda r: _get_rsi(r) is not None and _get_rsi(r) > 70,
    },
    "bullish_macd": {
        "name_ar": "تقاطع MACD إيجابي",
        "name_en": "Bullish MACD Cross",
        "filter": lambda r: _macd_bullish(r),
    },
    "bearish_macd": {
        "name_ar": "تقاطع MACD سلبي",
        "name_en": "Bearish MACD Cross",
        "filter": lambda r: _macd_bearish(r),
    },
    "near_support": {
        "name_ar": "قريب من الدعم",
        "name_en": "Near Support",
        "filter": lambda r: _near_level(r, "support"),
    },
    "near_resistance": {
        "name_ar": "قريب من المقاومة",
        "name_en": "Near Resistance",
        "filter": lambda r: _near_level(r, "resistance"),
    },
    "volume_spike": {
        "name_ar": "ارتفاع حجم التداول",
        "name_en": "Volume Spike",
        "filter": lambda r: _volume_spike(r),
    },
    "strong_uptrend": {
        "name_ar": "اتجاه صاعد قوي",
        "name_en": "Strong Uptrend",
        "filter": lambda r: r and r.get("trend") == "uptrend" and _get_score(r) >= 65,
    },
    "strong_downtrend": {
        "name_ar": "اتجاه هابط قوي",
        "name_en": "Strong Downtrend",
        "filter": lambda r: r and r.get("trend") == "downtrend" and _get_score(r) >= 65,
    },
    "high_score": {
        "name_ar": "قراءة فنية قوية (70+)",
        "name_en": "High Score (70+)",
        "filter": lambda r: _get_score(r) >= 70,
    },
}


def _get_rsi(result) -> Optional[float]:
    if not result:
        return None
    ind = result.get("indicators", {})
    rsi = ind.get("rsi")
    return float(rsi) if rsi is not None else None


def _get_score(result) -> float:
    if not result:
        return 0
    score = result.get("score")
    if score:
        try:
            return float(score.overall)
        except Exception:
            return 0
    return 0


def _macd_bullish(result) -> bool:
    if not result:
        return False
    ind = result.get("indicators", {})
    macd_line = ind.get("macd_line")
    macd_signal = ind.get("macd_signal")
    if macd_line is not None and macd_signal is not None:
        return macd_line > macd_signal
    return False


def _macd_bearish(result) -> bool:
    if not result:
        return False
    ind = result.get("indicators", {})
    macd_line = ind.get("macd_line")
    macd_signal = ind.get("macd_signal")
    if macd_line is not None and macd_signal is not None:
        return macd_line < macd_signal
    return False


def _near_level(result, level_type: str) -> bool:
    if not result:
        return False
    price = result.get("current_price")
    level = result.get(level_type)
    if price and level and price > 0:
        distance = abs(price - level) / price * 100
        return distance <= 3.0
    return False


def _volume_spike(result) -> bool:
    if not result:
        return False
    ind = result.get("indicators", {})
    rel_vol = ind.get("relative_volume")
    if rel_vol is not None:
        return float(rel_vol) > 1.5
    return False


async def run_screener(market: str, screener_id: str, count: int = 20) -> Optional[str]:
    market_key = market.upper()
    symbols = TOP_SYMBOLS.get(market_key, [])

    if not symbols:
        return None

    screener = SCREENERS.get(screener_id)
    if not screener:
        return None

    results = []
    for sym in symbols[:count]:
        try:
            r = await scan_symbol(sym, market_key, "1d")
            if r and screener["filter"](r):
                results.append(r)
        except Exception:
            continue

    if not results:
        return f"🔍 فاحص: {screener['name_ar']}\n\nلا توجد نتائج مطابقة حالياً."

    market_name = {"SAUDI": "السعودي", "US": "الأمريكي", "CRYPTO": "الرقمية"}.get(market_key, market_key)

    lines = [f"🔍 فاحص السوق — {screener['name_ar']}\nالسوق: {market_name}\nالنتائج: {len(results)}\n"]

    for i, r in enumerate(results[:10], 1):
        info = await get_symbol_info(r["symbol"], market_key)
        name = info["name_ar"] if info else r["symbol"]

        score = _get_score(r)
        price = r.get("current_price", 0)
        change = r.get("change_percent", 0)
        trend = r.get("trend", "")
        trend_emoji = {"uptrend": "🟢", "downtrend": "🔴", "sideways": "🟡"}.get(trend, "📊")

        rsi = _get_rsi(r)
        rsi_str = f" | RSI: {rsi:.1f}" if rsi else ""

        lines.append(
            f"{i}. {trend_emoji} {name} ({r['symbol']})\n"
            f"   ⭐ {score:.0f}/100 | 💰 {price:,.4f} | {'+' if change >= 0 else ''}{change:.2f}%{rsi_str}"
        )

    lines.append("\n⚠️ هذا فحص تعليمي وليس توصية مالية.")

    return "\n".join(lines)[:4000]


def get_screener_list() -> List[Dict]:
    return [
        {"id": k, "name_ar": v["name_ar"], "name_en": v["name_en"]}
        for k, v in SCREENERS.items()
    ]
