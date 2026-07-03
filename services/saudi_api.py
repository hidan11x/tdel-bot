import asyncio
from dataclasses import asdict
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from config import settings
from database import get_session
from models import SaudiMarketQuote, Symbol
from services.cache import cache
from services.saudi_exchange import SaudiQuote, get_saudi_quote, normalize_saudi_symbol
from services.search_engine import auto_detect_symbol
from services.symbols_service import find_symbol_by_name_or_alias


class SaudiApiError(Exception):
    """Base error for the Saudi market mediator."""


class SaudiStockNotFound(SaudiApiError):
    """Raised when no matching Saudi stock can be resolved."""


class SaudiSourceUnavailable(SaudiApiError):
    """Raised when the symbol exists but no price source is available."""


SOURCE_LABELS = {
    "tadawul_web": "Saudi Exchange",
    "saudi_exchange": "Saudi Exchange",
    "file_cache": "Saudi Exchange Cache",
    "database": "Saudi Exchange Cache",
}

KNOWN_SAUDI_SYMBOLS = {
    "8010": {"name_ar": "التعاونية", "name_en": "Tawuniya", "sector": "التأمين"},
    "8020": {"name_ar": "ملاذ للتأمين", "name_en": "Malath Insurance", "sector": "التأمين"},
    "8050": {"name_ar": "سلامة للتأمين", "name_en": "Salama Cooperative Insurance", "sector": "التأمين"},
}


def _clean_symbol(symbol: str) -> str:
    return normalize_saudi_symbol(symbol)


def _yahoo_symbol(symbol: str) -> str:
    clean = _clean_symbol(symbol)
    return f"{clean}.SR" if clean and not clean.endswith(".SR") else clean


def _display_symbol(symbol: str) -> str:
    return _clean_symbol(symbol).replace(".SR", "")


def _now_text() -> str:
    return settings.now().strftime("%Y-%m-%d %H:%M:%S")


def _number(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return None


def _price_text(value: Any) -> str:
    number = _number(value)
    return "-" if number is None else f"{number:,.2f}"


def _plain_number_text(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "-"
    if abs(number) >= 1000:
        return f"{number:,.0f}"
    return f"{number:,.2f}"


def _signed_text(value: Any, suffix: str = "") -> str:
    number = _number(value)
    if number is None:
        return "-"
    sign = "+" if number > 0 else ""
    return f"{sign}{number:,.2f}{suffix}"


def _source_label(source: str) -> str:
    return SOURCE_LABELS.get(source or "", source or "Unknown")


def _source_label_ar(source: str) -> str:
    labels = {
        "Saudi Exchange": "Saudi Exchange",
        "Saudi Exchange Cache": "Saudi Exchange Cache",
    }
    return labels.get(source or "", source or "غير معروف")


def _quote_from_db_row(row: SaudiMarketQuote) -> SaudiQuote:
    return SaudiQuote(
        symbol=row.symbol,
        name_ar=row.name_ar or "",
        name_en=row.name_en or "",
        sector=row.sector or "",
        price=row.price,
        open_price=row.open_price,
        high_price=row.high_price,
        low_price=row.low_price,
        previous_close=row.previous_close,
        change_value=row.change_value,
        change_percent=row.change_percent,
        volume=row.volume,
        turnover=row.turnover,
        trades=row.trades,
        bid_price=row.bid_price,
        ask_price=row.ask_price,
        source=row.source or "database",
        source_updated_at=row.source_updated_at or "",
        fetched_at=row.fetched_at.isoformat() if row.fetched_at else "",
    )


async def _db_symbol_info(symbol: str) -> dict[str, Any]:
    clean = _clean_symbol(symbol)
    if clean in KNOWN_SAUDI_SYMBOLS:
        return {"symbol": f"{clean}.SR", **KNOWN_SAUDI_SYMBOLS[clean], "exchange": "Saudi Exchange"}
    candidates = [clean, f"{clean}.SR"]
    try:
        async with get_session() as session:
            result = await session.execute(
                select(Symbol)
                .where(Symbol.market == "SAUDI", Symbol.symbol.in_(candidates))
                .order_by(Symbol.is_popular.desc(), Symbol.sort_order)
                .limit(1)
            )
            item = result.scalar_one_or_none()
    except SQLAlchemyError:
        item = None
    if not item:
        return {}
    return {
        "symbol": item.symbol,
        "name_ar": item.name_ar,
        "name_en": item.name_en,
        "sector": item.sector or item.category or "",
        "exchange": item.exchange or "Saudi Exchange",
    }


async def _db_quote(symbol: str) -> Optional[SaudiQuote]:
    clean = _clean_symbol(symbol)
    candidates = [clean, f"{clean}.SR"]
    try:
        async with get_session() as session:
            result = await session.execute(select(SaudiMarketQuote).where(SaudiMarketQuote.symbol.in_(candidates)))
            row = result.scalar_one_or_none()
    except SQLAlchemyError:
        row = None
    legacy_blocked_sources = {"s" + "ahmk", "simple" + "scraper", "yfinance", "free_fallback"}
    if row and (row.source or "").lower() in legacy_blocked_sources:
        return None
    return _quote_from_db_row(row) if row else None


async def resolve_saudi_symbol(query: str) -> dict[str, Any]:
    raw = (query or "").strip()
    if not raw:
        raise SaudiStockNotFound("empty query")

    clean = _clean_symbol(raw)
    if clean.isdigit() and len(clean) == 4:
        info = await _db_symbol_info(clean)
        return {
            "symbol": f"{clean}.SR",
            "display_symbol": clean,
            "name_ar": info.get("name_ar") or clean,
            "name_en": info.get("name_en") or clean,
            "sector": info.get("sector") or "",
        }

    detected = await auto_detect_symbol(raw)
    if detected and detected.get("market") == "SAUDI":
        symbol = detected["symbol"]
        info = await _db_symbol_info(symbol)
        prefer_detected_name = detected.get("source") == "common_alias"
        return {
            "symbol": _yahoo_symbol(symbol),
            "display_symbol": _display_symbol(symbol),
            "name_ar": (
                detected.get("name_ar")
                if prefer_detected_name
                else info.get("name_ar") or detected.get("name_ar")
            )
            or _display_symbol(symbol),
            "name_en": (
                detected.get("name_en")
                if prefer_detected_name
                else info.get("name_en") or detected.get("name_en")
            )
            or _display_symbol(symbol),
            "sector": info.get("sector") or detected.get("sector") or "",
        }

    matches = await find_symbol_by_name_or_alias(raw, limit=12)
    for item in matches:
        if item.get("market") == "SAUDI":
            symbol = item["symbol"]
            return {
                "symbol": _yahoo_symbol(symbol),
                "display_symbol": _display_symbol(symbol),
                "name_ar": item.get("name_ar") or _display_symbol(symbol),
                "name_en": item.get("name_en") or item.get("name_ar") or _display_symbol(symbol),
                "sector": item.get("sector") or "",
            }

    raise SaudiStockNotFound(raw)


async def _fresh_quote(symbol: str, force: bool) -> Optional[SaudiQuote]:
    try:
        return await asyncio.wait_for(asyncio.to_thread(get_saudi_quote, symbol, force), timeout=25)
    except asyncio.TimeoutError:
        raise
    except Exception:
        return None


def _payload_from_quote(quote: SaudiQuote, resolved: dict[str, Any], cached: bool = False) -> dict[str, Any]:
    symbol = _display_symbol(quote.symbol or resolved["symbol"])
    known = KNOWN_SAUDI_SYMBOLS.get(symbol, {})
    price = _number(quote.price)
    previous_close = _number(quote.previous_close)
    change_value = _number(quote.change_value)
    if change_value is None and price is not None and previous_close:
        change_value = price - previous_close
    change_percent = _number(quote.change_percent)
    if change_percent is None and change_value is not None and previous_close:
        change_percent = change_value / previous_close * 100

    name_ar = known.get("name_ar") or quote.name_ar or resolved.get("name_ar") or symbol
    name_en = known.get("name_en") or quote.name_en or resolved.get("name_en") or name_ar
    source = quote.source or "unknown"

    payload = {
        "ok": True,
        "symbol": symbol,
        "yahooSymbol": _yahoo_symbol(symbol),
        "name": name_ar,
        "nameAr": name_ar,
        "nameEn": name_en,
        "sector": known.get("sector") or quote.sector or resolved.get("sector") or "",
        "price": _price_text(price),
        "priceValue": price,
        "change": _signed_text(change_value),
        "changeValue": change_value,
        "changePercent": _signed_text(change_percent, "%"),
        "changePercentValue": change_percent,
        "open": _price_text(quote.open_price),
        "openValue": _number(quote.open_price),
        "high": _price_text(quote.high_price),
        "highValue": _number(quote.high_price),
        "low": _price_text(quote.low_price),
        "lowValue": _number(quote.low_price),
        "previousClose": _price_text(previous_close),
        "previousCloseValue": previous_close,
        "volume": _plain_number_text(quote.volume),
        "volumeValue": _number(quote.volume),
        "turnover": _plain_number_text(quote.turnover),
        "turnoverValue": _number(quote.turnover),
        "trades": _plain_number_text(quote.trades),
        "tradesValue": int(quote.trades) if quote.trades is not None else None,
        "lastUpdate": quote.source_updated_at or quote.fetched_at or _now_text(),
        "source": _source_label(source),
        "sourceKey": source,
        "cached": cached,
        "disclaimer": "Market data only. No buy/sell recommendations.",
    }
    payload["raw"] = asdict(quote)
    return payload


async def get_saudi_stock_payload(query: str, force: bool = False) -> dict[str, Any]:
    resolved = await resolve_saudi_symbol(query)
    symbol = resolved["symbol"]
    cache_key = f"saudi-api-stock:{_display_symbol(symbol)}"
    if not force:
        cached = cache.get(cache_key)
        if cached:
            payload = dict(cached)
            payload["cached"] = True
            return payload

    quote = await _fresh_quote(symbol, force)
    if not quote:
        quote = await _db_quote(symbol)
    if not quote or quote.price is None:
        raise SaudiSourceUnavailable(symbol)

    payload = _payload_from_quote(quote, resolved, cached=False)
    cache.set(cache_key, payload, settings.saudi_api_cache_seconds)
    return payload


def _search_item_from_dict(item: dict[str, Any]) -> dict[str, Any]:
    symbol = _display_symbol(item.get("symbol") or "")
    return {
        "symbol": symbol,
        "yahooSymbol": _yahoo_symbol(symbol),
        "name": item.get("name_ar") or item.get("name_en") or symbol,
        "nameAr": item.get("name_ar") or symbol,
        "nameEn": item.get("name_en") or item.get("name_ar") or symbol,
        "sector": item.get("sector") or "",
        "market": "SAUDI",
        "score": item.get("score"),
        "source": item.get("source") or "search",
    }


async def search_saudi_stocks(query: str, limit: int = 10) -> list[dict[str, Any]]:
    raw = (query or "").strip()
    if not raw:
        return []
    limit = min(30, max(1, int(limit or 10)))
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    try:
        resolved = await resolve_saudi_symbol(raw)
        first = _search_item_from_dict(
            {
                "symbol": resolved["symbol"],
                "name_ar": resolved.get("name_ar"),
                "name_en": resolved.get("name_en"),
                "sector": resolved.get("sector"),
                "score": 100,
                "source": "resolved",
            }
        )
        items.append(first)
        seen.add(first["symbol"])
    except SaudiStockNotFound:
        pass

    matches = await find_symbol_by_name_or_alias(raw, limit=limit * 3)
    for item in matches:
        if item.get("market") != "SAUDI":
            continue
        row = _search_item_from_dict(item)
        if row["symbol"] in seen:
            continue
        items.append(row)
        seen.add(row["symbol"])
        if len(items) >= limit:
            break

    return items[:limit]


def format_saudi_stock_message(payload: dict[str, Any], details: bool = False) -> str:
    name = payload.get("name") or payload.get("nameAr") or payload.get("symbol")
    symbol = payload.get("symbol") or "-"
    lines = [
        f"📈 {name} — {symbol}",
        "",
        f"السعر: {payload.get('price', '-')} ريال",
        f"التغير: {payload.get('change', '-')} ريال",
        f"النسبة: {payload.get('changePercent', '-')}",
        f"الأعلى: {payload.get('high', '-')}",
        f"الأدنى: {payload.get('low', '-')}",
        f"الحجم: {payload.get('volume', '-')}",
        f"آخر تحديث: {payload.get('lastUpdate', '-')}",
        "",
        f"المصدر: {_source_label_ar(payload.get('source', 'Saudi Exchange'))}",
    ]
    if details:
        extra = [
            "",
            "تفاصيل إضافية:",
            f"الافتتاح: {payload.get('open', '-')}",
            f"الإغلاق السابق: {payload.get('previousClose', '-')}",
            f"قيمة التداول: {payload.get('turnover', '-')}",
            f"عدد الصفقات: {payload.get('trades', '-')}",
        ]
        if payload.get("sector"):
            extra.append(f"القطاع: {payload['sector']}")
        lines.extend(extra)
    return "\n".join(lines)
