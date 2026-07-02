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


@dataclass
class ScreenFilter:
    metric: str
    direction: str
    value: float | None = None


def _detect_market(text: str) -> str | None:
    lowered = text.lower()
    if any(word in lowered for word in ("السعودي", "تاسي", "نمو", "سعودي")):
        return "SAUDI"
    if any(word in lowered for word in ("امريكي", "أمريكي", "usa", "us", "nasdaq", "nyse")):
        return "US"
    if any(word in lowered for word in ("كريبتو", "بتكوين", "بيتكوين", "عملات", "crypto", "bitcoin", "btc")):
        return "CRYPTO"
    return None


def _money(value: float, market: str) -> str:
    if market == "US":
        return f"${value:,.4f}"
    if market == "CRYPTO":
        return f"{value:,.4f} USDT"
    if market == "SAUDI":
        return f"{value:,.4f} ريال"
    return f"{value:,.4f}"


def _extract_price_filter(text: str) -> tuple[str, float] | None:
    pattern = r"(تحت|اقل|أقل|below|under|فوق|اكثر|أكثر|above|over)\s+(\d+(?:\.\d+)?)"
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    word = match.group(1).lower()
    direction = "below" if word in {"تحت", "اقل", "أقل", "below", "under"} else "above"
    return direction, float(match.group(2))


def _extract_screen_filter(text: str) -> ScreenFilter | None:
    lowered = text.lower()

    rsi_match = re.search(r"rsi\s*(تحت|اقل|أقل|below|under|فوق|اكثر|أكثر|above|over)\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if not rsi_match:
        rsi_match = re.search(r"(تحت|اقل|أقل|below|under|فوق|اكثر|أكثر|above|over)\s*(\d+(?:\.\d+)?)\s*rsi", text, re.IGNORECASE)
    if rsi_match:
        word = rsi_match.group(1).lower()
        direction = "below" if word in {"تحت", "اقل", "أقل", "below", "under"} else "above"
        return ScreenFilter("rsi", direction, float(rsi_match.group(2)))

    price_filter = _extract_price_filter(text)
    if price_filter:
        return ScreenFilter("price", price_filter[0], price_filter[1])

    pct_match = re.search(r"(مرتفع|صاعد|رابح|نازل|هابط|خاسر)\s*(?:فوق|اكثر|أكثر|اقل|أقل|تحت)?\s*(\d+(?:\.\d+)?)?\s*%?", text, re.IGNORECASE)
    if pct_match:
        direction = "below" if pct_match.group(1).lower() in {"نازل", "هابط", "خاسر"} else "above"
        value = float(pct_match.group(2)) if pct_match.group(2) else 0.0
        return ScreenFilter("change_pct", direction, value)

    if any(word in lowered for word in ("حجم عالي", "حجم تداول عالي", "فوليوم عالي", "volume")):
        return ScreenFilter("volume_ratio", "above", 1.5)

    return None


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


async def _ensure_symbol(detected: dict[str, Any]) -> None:
    symbol = (detected.get("symbol") or "").upper()
    market = (detected.get("market") or "").upper()
    if not symbol or not market:
        return
    async with get_session() as session:
        existing = (
            await session.execute(select(Symbol).where(Symbol.symbol == symbol, Symbol.market == market))
        ).scalar_one_or_none()
        if existing:
            return
        currency = "SAR" if market == "SAUDI" else "USDT" if market == "CRYPTO" else "USD"
        asset_type = "crypto" if market == "CRYPTO" else "stock"
        yahoo_symbol = symbol
        if market == "SAUDI" and not yahoo_symbol.endswith(".SR"):
            yahoo_symbol = f"{symbol}.SR"
        elif market == "CRYPTO":
            yahoo_symbol = f"{symbol[:-4]}-USD" if symbol.endswith("USDT") else f"{symbol}-USD"
        session.add(
            Symbol(
                market=market,
                symbol=symbol,
                yahoo_symbol=yahoo_symbol,
                name_ar=detected.get("name_ar") or symbol,
                name_en=detected.get("name_en") or symbol,
                sector=detected.get("sector") or ("Crypto" if market == "CRYPTO" else "Auto"),
                category=detected.get("sector") or ("Crypto" if market == "CRYPTO" else "Auto"),
                exchange="Binance" if market == "CRYPTO" else market,
                currency=currency,
                asset_type=asset_type,
                is_active=True,
                is_popular=False,
                sort_order=9999,
            )
        )
        await session.commit()


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
    await _ensure_symbol(candidate)
    return candidate


async def analyze_question(text: str) -> MarketAssistantResult:
    screen_filter = _extract_screen_filter(text)
    market = _detect_market(text)
    if screen_filter and not market:
        return MarketAssistantResult(
            kind="need_market",
            text=(
                "حدد السوق أولاً عشان أطبق السعر بالعملة الصحيحة.\n\n"
                "أمثلة:\n"
                "• السعودي تحت 50\n"
                "• الأمريكي تحت 150\n"
                "• الكريبتو تحت 1"
            ),
        )
    if screen_filter and market:
        return await screen_market(market, screen_filter)

    detected = await _resolve_symbol(text)
    if not detected:
        return MarketAssistantResult(
            kind="not_found",
            text="ما قدرت أحدد الرمز. جرّب تكتب الرمز مباشرة مثل AAPL أو 1120 أو BTCUSDT.",
        )
    return await summarize_symbol(detected)


def _metrics_from_ohlcv(data: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    if not data:
        return None
    closes = [float(row["close"]) for row in data if row.get("close") is not None]
    if not closes:
        return None
    price = closes[-1]
    prev = closes[-2] if len(closes) >= 2 else closes[-1]
    change_pct = ((price - prev) / prev * 100) if prev else 0.0
    rsi = calculate_rsi(closes[-50:]) if len(closes) >= 15 else None
    volume_ratio = None
    volumes = [float(row.get("volume", 0) or 0) for row in data]
    if len(volumes) >= 21:
        avg_volume = sum(volumes[-21:-1]) / 20
        volume_ratio = (volumes[-1] / avg_volume) if avg_volume else None
    return {
        "price": price,
        "change_pct": change_pct,
        "rsi": rsi,
        "volume_ratio": volume_ratio,
    }


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

    await _ensure_symbol(detected)

    direction = "مرتفع" if change_pct > 0 else "نازل" if change_pct < 0 else "بدون تغير واضح"
    mood = "إيجابية" if change_pct > 1 and trend == "صاعد" else "ضعيفة" if change_pct < -1 and trend == "هابط" else "محايدة"
    lines = [
        f"🔎 قراءة سريعة",
        "",
        f"🏷 {name}",
        f"🔢 {symbol} | {MARKET_LABELS.get(market, market)}",
        f"💰 السعر: {_money(price, market)}",
        f"📊 التغير: {change_pct:+.2f}% | {direction}",
        f"🧭 الاتجاه: {trend}",
        f"🧪 القراءة: {mood}",
    ]
    if rsi is not None:
        lines.append(f"RSI: {rsi:.1f}")
    if support is not None and resistance is not None:
        lines.append(f"🟢 دعم: {_money(support, market)} | 🔴 مقاومة: {_money(resistance, market)}")
    lines.append("")
    lines.append("هذا تحليل آلي تعليمي وليس توصية مالية.")
    return MarketAssistantResult(kind="symbol", text="\n".join(lines), symbol=symbol, market=market)


async def screen_by_price(market: str, direction: str, threshold: float) -> MarketAssistantResult:
    return await screen_market(market, ScreenFilter("price", direction, threshold))


async def screen_market(market: str, screen_filter: ScreenFilter) -> MarketAssistantResult:
    async with get_session() as session:
        result = await session.execute(
            select(Symbol)
            .where(Symbol.market == market, Symbol.is_active == True)
            .order_by(Symbol.is_popular.desc(), Symbol.sort_order)
            .limit(260)
        )
        symbols = list(result.scalars().all())

    semaphore = asyncio.Semaphore(8)

    async def measured(item: Symbol) -> dict[str, Any] | None:
        async with semaphore:
            data = await asyncio.to_thread(get_ohlcv, item.symbol, item.market, "1d", 70)
        metrics = _metrics_from_ohlcv(data)
        if not metrics:
            async with semaphore:
                price = await asyncio.to_thread(get_current_price_sync, item.symbol, item.market)
            if price is None:
                return None
            metrics = {"price": float(price), "change_pct": 0.0, "rsi": None, "volume_ratio": None}

        value = metrics.get(screen_filter.metric)
        if value is None:
            return None
        threshold = screen_filter.value if screen_filter.value is not None else 0.0
        if screen_filter.direction == "below" and value >= threshold:
            return None
        if screen_filter.direction == "above" and value <= threshold:
            return None
        return {
            "symbol": item.symbol,
            "market": item.market,
            "name": item.name_ar or item.name_en or item.symbol,
            "price": float(metrics["price"]),
            "change_pct": float(metrics.get("change_pct") or 0.0),
            "rsi": metrics.get("rsi"),
            "volume_ratio": metrics.get("volume_ratio"),
        }

    items = [item for item in await asyncio.gather(*(measured(symbol) for symbol in symbols)) if item]
    sort_key = screen_filter.metric if screen_filter.metric in {"price", "change_pct", "rsi", "volume_ratio"} else "price"
    reverse = screen_filter.direction == "above" or (screen_filter.metric == "price" and screen_filter.direction == "below")
    items.sort(key=lambda x: x.get(sort_key) if x.get(sort_key) is not None else -999999, reverse=reverse)
    items = items[:10]

    filter_names = {
        "price": "السعر",
        "change": "التغير اليومي",
        "change_pct": "التغير اليومي",
        "rsi": "RSI",
        "volume": "حجم التداول",
        "volume_ratio": "حجم التداول",
    }
    metric_name = filter_names.get(screen_filter.metric, screen_filter.metric)
    label = "تحت" if screen_filter.direction == "below" else "فوق"
    if screen_filter.metric == "price" and screen_filter.value is not None:
        value_label = f" {_money(screen_filter.value, market)}"
    else:
        value_label = f" {screen_filter.value:g}" if screen_filter.value is not None else ""
    lines = [f"🔎 نتائج {MARKET_LABELS.get(market, market)} | {metric_name} {label}{value_label}", ""]
    if not items:
        lines.append("ما لقيت نتائج مناسبة حالياً من الرموز المتاحة.")
    else:
        for index, item in enumerate(items, start=1):
            rsi = f" | RSI {item['rsi']:.1f}" if item.get("rsi") is not None else ""
            vol = f" | حجم {item['volume_ratio']:.1f}x" if item.get("volume_ratio") is not None else ""
            lines.append(
                f"{index}. {item['name']} ({item['symbol']}) - {_money(item['price'], market)} | {item['change_pct']:+.2f}%{rsi}{vol}"
            )
    lines.append("")
    lines.append("اضغط على رمز من الأزرار لتحليله. النتائج من الأسعار المتاحة حالياً وقد تتأخر حسب مزود البيانات.")
    return MarketAssistantResult(kind="screen", text="\n".join(lines), market=market, items=items)
