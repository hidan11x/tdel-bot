import asyncio
from typing import Any, Dict, List, Optional

from aiogram.utils.keyboard import InlineKeyboardBuilder

from loguru import logger

from services.scanner import TOP_SYMBOLS, scan_symbol
from services.signal_engine import build_signal


MARKET_LABELS = {
    "SAUDI": "السوق السعودي",
    "US": "السوق الأمريكي",
    "CRYPTO": "الكريبتو",
}

MARKET_KEYS = {
    "SAUDI": "saudi",
    "US": "us",
    "CRYPTO": "crypto",
}


def _score(result: Dict[str, Any]) -> float:
    score = result.get("score")
    try:
        return float(score.overall)
    except Exception:
        return 0.0


def _fmt_price(value: Optional[float]) -> str:
    if value is None:
        return "غير متوفر"
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:.4f}"
    if value >= 0.01:
        return f"{value:.6f}"
    return f"{value:.8f}"


def _fmt_change(value: float) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def _trend_label(trend: str) -> str:
    return {
        "uptrend": "🟢 صاعد",
        "downtrend": "🔴 هابط",
        "sideways": "🟡 جانبي",
        "mixed": "🟠 متضارب",
    }.get((trend or "").lower(), "📊 غير واضح")


def _first_reason(signal) -> str:
    if signal.reasons:
        return signal.reasons[0].strip()
    return "قراءة فنية تحتاج متابعة."


async def get_market_opportunities(market: str, count: int = 3) -> List[Dict[str, Any]]:
    market_key = market.upper()
    scan_limit = 5 if count <= 1 else 8
    symbols = TOP_SYMBOLS.get(market_key, [])[:scan_limit]
    semaphore = asyncio.Semaphore(3)

    async def scan_one(symbol: str) -> Optional[Dict[str, Any]]:
        async with semaphore:
            try:
                return await scan_symbol(symbol, market_key, "1d")
            except Exception as exc:
                logger.warning("Opportunity scan failed for {} {}: {}", market_key, symbol, exc)
                return None

    scan_results = await asyncio.gather(*(scan_one(symbol) for symbol in symbols))
    results: List[Dict[str, Any]] = [item for item in scan_results if item]

    if len(results) < count:
        remaining = TOP_SYMBOLS.get(market_key, [])[scan_limit : scan_limit + 3]
        for symbol in remaining:
            if len(results) >= count:
                break
            try:
                result = await scan_symbol(symbol, market_key, "1d")
                if result:
                    results.append(result)
            except Exception as exc:
                logger.warning("Opportunity scan failed for {} {}: {}", market_key, symbol, exc)
    results.sort(key=_score, reverse=True)
    return results[:count]


async def get_radar_opportunities(vip: bool = False) -> Dict[str, List[Dict[str, Any]]]:
    per_market = 3 if vip else 1
    radar: Dict[str, List[Dict[str, Any]]] = {}
    for market in ["SAUDI", "US", "CRYPTO"]:
        radar[market] = await get_market_opportunities(market, per_market)
    return radar


async def get_opportunity_of_day() -> Optional[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for market in ["SAUDI", "US", "CRYPTO"]:
        candidates.extend(await get_market_opportunities(market, 2))
    if not candidates:
        return None
    candidates.sort(key=_score, reverse=True)
    return candidates[0]


def format_opportunity(result: Dict[str, Any], rank: int = 1, compact: bool = False) -> str:
    signal = build_signal(result)
    name = signal.name_ar if signal.name_ar and signal.name_ar != signal.symbol else signal.name_en
    if not name or name == signal.symbol:
        name = signal.symbol

    lines = [
        f"{rank}. {name} ({signal.symbol})",
        f"   {_trend_label(signal.trend)} | ⭐ {signal.score:.0f}/100 | 🎯 {signal.confidence}/100",
        f"   💰 {_fmt_price(signal.current_price)} | {_fmt_change(signal.change_percent)}",
    ]

    if not compact:
        lines.extend(
            [
                f"   🟢 دعم: {_fmt_price(signal.support)} | 🔴 مقاومة: {_fmt_price(signal.resistance)}",
                f"   السبب: {_first_reason(signal)}",
            ]
        )

    return "\n".join(lines)


def format_radar(radar: Dict[str, List[Dict[str, Any]]], vip: bool = False) -> str:
    lines = [
        "🚀 رادار الفرص",
        "",
        "أفضل القراءات الحالية حسب السوق:",
        "",
    ]
    for market, items in radar.items():
        lines.append(f"━━ {MARKET_LABELS.get(market, market)}")
        if not items:
            lines.append("لا توجد فرص كافية حالياً.\n")
            continue
        for idx, result in enumerate(items, 1):
            lines.append(format_opportunity(result, idx, compact=not vip))
        lines.append("")

    if not vip:
        lines.append("🔒 نسخة VIP تعرض 3 فرص لكل سوق مع الدعم والمقاومة وسبب الاختيار.")

    lines.append("هذا تحليل آلي تعليمي وليس توصية مالية.")
    return "\n".join(lines).strip()


def format_opportunity_of_day(result: Dict[str, Any]) -> str:
    signal = build_signal(result)
    market_label = MARKET_LABELS.get(signal.market, signal.market)
    return (
        "🔥 فرصة اليوم\n\n"
        f"{format_opportunity(result, 1, compact=False)}\n\n"
        f"🌍 السوق: {market_label}\n"
        f"⚠️ المخاطرة: {signal.risk_level}\n\n"
        "الفكرة: تابع السعر حول الدعم والمقاومة، ولا تعتمد على الإشارة وحدها.\n"
        "هذا تحليل آلي تعليمي وليس توصية مالية."
    )


def build_opportunity_keyboard(items: List[Dict[str, Any]], back_to: str = "menu:reports"):
    builder = InlineKeyboardBuilder()
    for result in items[:6]:
        symbol = result.get("symbol", "")
        market = result.get("market", "US")
        market_key = MARKET_KEYS.get(market, market.lower())
        short = symbol.replace(".SR", "").replace("USDT", "")
        builder.button(text=f"📈 شارت {short}", callback_data=f"chart:{symbol}:{market_key}")
        builder.button(text=f"⭐ متابعة {short}", callback_data=f"watch_add:{symbol}:{market_key}")
    builder.button(text="🔄 تحديث", callback_data="opportunity_radar")
    builder.button(text="↩️ رجوع", callback_data=back_to)
    builder.adjust(2)
    return builder.as_markup()


def flatten_radar(radar: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for market_items in radar.values():
        items.extend(market_items)
    return items
