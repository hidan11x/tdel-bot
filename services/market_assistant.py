import asyncio
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from database import get_session
from models import Symbol
from services.indicators import calculate_rsi, find_support_resistance
from services.market_data import get_current_price_sync, get_ohlcv
from services.search_engine import auto_detect_symbol


MARKET_LABELS = {"SAUDI": "السعودي", "US": "الأمريكي", "CRYPTO": "الكريبتو"}


@dataclass
class MarketAssistantResult:
    kind: str
    text: str
    symbol: str | None = None
    market: str | None = None
    items: list[dict[str, Any]] | None = None


def _detect_market(text: str) -> str | None:
    lowered = text.lower()
    if any(word in lowered for word in ("السعودي", "تاسي", "نمو", "سعودي")):
        return "SAUDI"
    if any(word in lowered for word in ("امريكي", "أمريكي", "usa", "us", "nasdaq", "nyse")):
        return "US"
    if any(word in lowered for word in ("كريبتو", "بتكوين", "بيتكوين", "عملات", "crypto", "bitcoin", "btc")):
        return "CRYPTO"
    return None


def _extract_price_filter(text: str) -> tuple[str, float] | None:
    pattern = r"(تحت|اقل|أقل|below|under|فوق|اكثر|أكثر|above|over)\s+(\d+(?:\.\d+)?)"
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    word = match.group(1).lower()
    direction = "below" if word in {"تحت", "اقل", "أقل", "below", "under"} else "above"
    return direction, float(match.group(2))


def _query_token(text: str) -> str:
    cleaned = re.sub(r"(وش|وضع|حلل|تحليل|سهم|عملة|السعر|كم|عن|هل|اليوم|الان|الآن|مرتفع|نازل|صاعد|هابط)", " ", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"(السوق|الأمريكي|امريكي|السعودي|كريبتو|عملات|تحت|فوق|اقل|أقل|اكثر|أكثر)\s*\d*(?:\.\d+)?", " ", cleaned)
    parts = [p.strip(" ،,?؟") for p in cleaned.split() if p.strip(" ،,?؟")]
    return parts[0] if parts else text.strip()


def _direct_candidate(token: str, market_hint: str | None) -> dict[str, Any] | None:
    raw = token.strip().replace("$", "").upper()
    if not raw:
        return None
    if raw.isdigit() and len(raw) == 4:
        return {"symbol": raw, "market": "SAUDI", "name_ar": raw, "name_en": raw, "source": "direct"}
    if market_hint == "CRYPTO" or raw.endswith("USDT") or raw in {"BTC", "ETH", "SOL", "XRP", "DOGE"}:
        symbol = raw if raw.endswith("USDT") else f"{raw}USDT"
        return {"symbol": symbol, "market": "CRYPTO", "name_ar": symbol, "name_en": symbol, "source": "direct"}
    if re.fullmatch(r"[A-Z.]{1,8}", raw):
        return {"symbol": raw, "market": market_hint or "US", "name_ar": raw, "name_en": raw, "source": "direct"}
    return None


async def _resolve_symbol(text: str) -> dict[str, Any] | None:
    token = _query_token(text)
    for candidate_text in (token, text):
        detected = await auto_detect_symbol(candidate_text)
        if detected:
            return detected
    candidate = _direct_candidate(token, _detect_market(text))
    if not candidate:
        return None
    price = await asyncio.to_thread(get_current_price_sync, candidate["symbol"], candidate["market"])
    if price is None:
        return None
    return candidate


async def analyze_question(text: str) -> MarketAssistantResult:
    price_filter = _extract_price_filter(text)
    market = _detect_market(text)
    if price_filter and market:
        return await screen_by_price(market, price_filter[0], price_filter[1])

    detected = await _resolve_symbol(text)
    if not detected:
        return MarketAssistantResult(
            kind="not_found",
            text="ما قدرت أحدد الرمز. جرّب تكتب الرمز مباشرة مثل AAPL أو 1120 أو BTCUSDT.",
        )
    return await summarize_symbol(detected)


async def summarize_symbol(detected: dict[str, Any]) -> MarketAssistantResult:
    symbol = detected["symbol"].upper()
    market = detected["market"].upper()
    name = detected.get("name_ar") or detected.get("name_en") or symbol

    data = await asyncio.to_thread(get_ohlcv, symbol, market, "1d", 90)
    price = None
    change_pct = 0.0
    rsi = support = resistance = None
    trend = "غير واضح"

    if data:
        closes = [float(row["close"]) for row in data if row.get("close") is not None]
        if closes:
            price = closes[-1]
            prev = closes[-2] if len(closes) >= 2 else closes[-1]
            change_pct = ((price - prev) / prev * 100) if prev else 0.0
            support, resistance = find_support_resistance(closes[-60:], lookback=min(25, len(closes)))
            rsi = calculate_rsi(closes[-50:]) if len(closes) >= 15 else None
            if len(closes) >= 20:
                avg20 = sum(closes[-20:]) / 20
                trend = "صاعد" if price > avg20 else "هابط" if price < avg20 else "جانبي"

    if price is None:
        price = await asyncio.to_thread(get_current_price_sync, symbol, market)

    if price is None:
        return MarketAssistantResult(kind="not_found", text=f"تعذر جلب بيانات {symbol} حالياً.")

    direction = "مرتفع" if change_pct > 0 else "نازل" if change_pct < 0 else "بدون تغير واضح"
    mood = "إيجابية" if change_pct > 1 and trend == "صاعد" else "ضعيفة" if change_pct < -1 and trend == "هابط" else "محايدة"
    lines = [
        f"🔎 قراءة سريعة",
        "",
        f"🏷 {name}",
        f"🔢 {symbol} | {MARKET_LABELS.get(market, market)}",
        f"💰 السعر: {price:,.4f}",
        f"📊 التغير: {change_pct:+.2f}% | {direction}",
        f"🧭 الاتجاه: {trend}",
        f"🧪 القراءة: {mood}",
    ]
    if rsi is not None:
        lines.append(f"RSI: {rsi:.1f}")
    if support is not None and resistance is not None:
        lines.append(f"🟢 دعم: {support:,.4f} | 🔴 مقاومة: {resistance:,.4f}")
    lines.append("")
    lines.append("هذا تحليل آلي تعليمي وليس توصية مالية.")
    return MarketAssistantResult(kind="symbol", text="\n".join(lines), symbol=symbol, market=market)


async def screen_by_price(market: str, direction: str, threshold: float) -> MarketAssistantResult:
    async with get_session() as session:
        result = await session.execute(
            select(Symbol)
            .where(Symbol.market == market, Symbol.is_active == True)
            .order_by(Symbol.is_popular.desc(), Symbol.sort_order)
            .limit(140)
        )
        symbols = list(result.scalars().all())

    semaphore = asyncio.Semaphore(10)

    async def priced(item: Symbol) -> dict[str, Any] | None:
        async with semaphore:
            price = await asyncio.to_thread(get_current_price_sync, item.symbol, item.market)
        if price is None:
            return None
        if direction == "below" and price >= threshold:
            return None
        if direction == "above" and price <= threshold:
            return None
        return {
            "symbol": item.symbol,
            "market": item.market,
            "name": item.name_ar or item.name_en or item.symbol,
            "price": float(price),
        }

    items = [item for item in await asyncio.gather(*(priced(symbol) for symbol in symbols)) if item]
    items.sort(key=lambda x: x["price"], reverse=(direction == "below"))
    items = items[:10]

    label = "تحت" if direction == "below" else "فوق"
    lines = [f"🔎 نتائج {MARKET_LABELS.get(market, market)} {label} {threshold:g}", ""]
    if not items:
        lines.append("ما لقيت نتائج مناسبة حالياً من الرموز المتاحة.")
    else:
        for index, item in enumerate(items, start=1):
            lines.append(f"{index}. {item['name']} ({item['symbol']}) - {item['price']:,.4f}")
    lines.append("")
    lines.append("اضغط على رمز من الأزرار لتحليله. النتائج من الأسعار المتاحة حالياً وقد تتأخر حسب مزود البيانات.")
    return MarketAssistantResult(kind="screen", text="\n".join(lines), market=market, items=items)
