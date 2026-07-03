import json
import re
import time
import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import urljoin

import requests as std_requests
from loguru import logger
from sqlalchemy import select

from config import settings
from database import get_session
from models import SaudiMarketQuote, SaudiMarketSnapshot, Symbol

try:
    from curl_cffi import requests as chrome_requests
except Exception:  # pragma: no cover - standard requests remains a fallback.
    chrome_requests = None


DEFAULT_SAUDI_PAGE_URL = "https://www.saudiexchange.sa/wps/portal/saudiexchange/ourmarkets/main-market-watch?locale=ar"
DEFAULT_SAUDI_BASE_URL = "https://www.saudiexchange.sa/wps/portal/saudiexchange/ourmarkets/main-market-watch/"
DEFAULT_SAUDI_ENDPOINT = (
    DEFAULT_SAUDI_BASE_URL
    + "!ut/p/z1/04_Sj9CPykssy0xPLMnMz0vMAfIjo8ziTR3NDIw8LAz8LVxcnA0C3bwtPLwM_I0MzMz1w1EVGAQHmAIVBPga-xgEGbgbmOlHEaPfAAdwNCCsPwpNia-7mUGgn2Ogv5G5qYFBsBG6AixOBCvA44aC3NAIg0xPRQASFoSL/"
    + "p0/IZ7_IPG41I82KGASC06S67RB9A0080=CZ6_5A602H80O8DDC0QFK8HJ0O2067=NJgetMainNomucMarketDetails=/"
)
SAUDI_CACHE_FILE = Path("data") / "saudi_quotes_cache.json"


@dataclass
class SaudiQuote:
    symbol: str
    name_ar: str = ""
    name_en: str = ""
    sector: str = ""
    price: Optional[float] = None
    open_price: Optional[float] = None
    high_price: Optional[float] = None
    low_price: Optional[float] = None
    previous_close: Optional[float] = None
    change_value: Optional[float] = None
    change_percent: Optional[float] = None
    volume: Optional[float] = None
    turnover: Optional[float] = None
    trades: Optional[int] = None
    bid_price: Optional[float] = None
    ask_price: Optional[float] = None
    source: str = "tadawul_web"
    source_updated_at: str = ""
    fetched_at: str = ""


_quotes_cache: dict[str, SaudiQuote] = {}
_last_refresh = 0.0
_last_source = "empty"
_last_error = ""
_last_endpoint = ""


def normalize_saudi_symbol(symbol: str) -> str:
    raw = (symbol or "").strip().upper()
    digits = re.sub(r"\D", "", raw)
    if len(digits) >= 4:
        return digits[-4:]
    return raw.replace(".SR", "")


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text in {"-", "--", "null", "None"}:
        return None
    text = (
        text.replace(",", "")
        .replace("%", "")
        .replace("\u2212", "-")
        .replace("\u066b", ".")
        .replace("\u066c", "")
    )
    try:
        return float(text)
    except ValueError:
        return None


def _to_int(value: Any) -> Optional[int]:
    number = _to_float(value)
    return int(number) if number is not None else None


def _first(row: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _normalize_record(row: dict[str, Any], source: str) -> Optional[SaudiQuote]:
    symbol = normalize_saudi_symbol(str(_first(row, ("companySymbol", "symbol", "code", "ticker", "companyRef")) or ""))
    if not symbol:
        return None
    price = _to_float(_first(row, ("lastTradePrice", "last", "price", "close", "todayClosePrice", "last_price")))
    previous_close = _to_float(
        _first(row, ("previousClosePrice", "previousClose", "previous_close", "prevClose", "prev_close"))
    )
    change_value = _to_float(_first(row, ("netChange", "change", "changeValue", "change_value")))
    change_percent = _to_float(_first(row, ("precentChange", "percentChange", "changePercent", "change_percent")))
    return SaudiQuote(
        symbol=symbol,
        name_ar=str(_first(row, ("acrynomName", "companyName", "name_ar", "nameAr", "shortNameAr", "name")) or symbol).strip(),
        name_en=str(_first(row, ("companyNameEn", "name_en", "nameEn", "shortNameEn")) or "").strip(),
        sector=str(_first(row, ("sectorName", "sector", "sector_ar", "sectorNameAr")) or "Saudi Listed").strip(),
        price=price,
        open_price=_to_float(_first(row, ("todayOpen", "open", "openPrice", "open_price"))),
        high_price=_to_float(_first(row, ("highPrice", "high", "dayHigh", "high_price"))),
        low_price=_to_float(_first(row, ("lowPrice", "low", "dayLow", "low_price"))),
        previous_close=previous_close,
        change_value=change_value,
        change_percent=change_percent,
        volume=_to_float(_first(row, ("volumeTraded", "volume", "volume_traded"))),
        turnover=_to_float(_first(row, ("turnover", "valueTraded", "value_traded"))),
        trades=_to_int(_first(row, ("nuOfTrades", "numberOfTrades", "trades"))),
        bid_price=_to_float(_first(row, ("bidPrice", "bid", "bestBid"))),
        ask_price=_to_float(_first(row, ("askPrice", "ask", "bestAsk"))),
        source=source,
        source_updated_at=str(_first(row, ("lastUpdatetime", "updateTime", "transactionDate", "updatedAt", "updated_at")) or ""),
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "results", "items", "rows", "companies", "records"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
        if isinstance(value, dict):
            nested = _extract_rows(value)
            if nested:
                return nested
    return [payload] if any(key in payload for key in ("companySymbol", "symbol", "code", "companyRef")) else []


def _normalize_quotes(rows: list[dict[str, Any]], source: str) -> list[SaudiQuote]:
    quotes: dict[str, SaudiQuote] = {}
    for row in rows:
        quote = _normalize_record(row, source)
        if quote and quote.price is not None:
            quotes[quote.symbol] = quote
    return list(quotes.values())


def _headers(json_request: bool = False) -> dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ar-SA,ar;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": settings.saudi_exchange_page_url or DEFAULT_SAUDI_PAGE_URL,
    }
    if json_request:
        headers["Accept"] = "application/json, text/javascript, */*; q=0.01"
        headers["X-Requested-With"] = "XMLHttpRequest"
    else:
        headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    return headers


def _new_session():
    if chrome_requests is not None:
        return chrome_requests.Session(impersonate="chrome124")
    return std_requests.Session()


def _response_text(response: Any) -> str:
    if hasattr(response, "text"):
        return response.text
    content = getattr(response, "content", b"")
    return content.decode("utf-8", errors="ignore")


def _raise_for_status(response: Any) -> None:
    status = getattr(response, "status_code", 0)
    if status >= 400:
        raise RuntimeError(f"{status} from Saudi Exchange")


def _extract_endpoint(page_html: str) -> str:
    match = re.search(r"url\s*:\s*['\"]([^'\"]*NJgetMainNomucMarketDetails[^'\"]*)['\"]", page_html)
    if match:
        endpoint = unescape(match.group(1)).strip()
        if endpoint.startswith("http"):
            return endpoint
        if endpoint.startswith("p0/") or endpoint.startswith("/p0/"):
            return DEFAULT_SAUDI_ENDPOINT
        return urljoin(DEFAULT_SAUDI_BASE_URL, endpoint)
    return settings.saudi_exchange_endpoint or DEFAULT_SAUDI_ENDPOINT


def _loads_json_response(text: str) -> Any:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _fetch_tadawul_web_quotes(timeout: int = 30) -> list[SaudiQuote]:
    global _last_endpoint
    page_url = settings.saudi_exchange_page_url or DEFAULT_SAUDI_PAGE_URL
    session = _new_session()
    page_response = session.get(page_url, headers=_headers(False), timeout=timeout)
    _raise_for_status(page_response)
    page_html = _response_text(page_response)
    endpoint = settings.saudi_exchange_endpoint or _extract_endpoint(page_html)
    _last_endpoint = endpoint
    response = session.get(
        endpoint,
        params={
            "sectorParameter": "",
            "tableViewParameter": "1",
            "iswatchListSelected": "NO",
            "requestLocale": "ar",
            "_": str(int(time.time() * 1000)),
        },
        headers=_headers(True),
        timeout=timeout,
    )
    _raise_for_status(response)
    payload = _loads_json_response(_response_text(response))
    return _normalize_quotes(_extract_rows(payload), "tadawul_web")


def _load_file_cache() -> list[SaudiQuote]:
    try:
        if not SAUDI_CACHE_FILE.exists():
            return []
        payload = json.loads(SAUDI_CACHE_FILE.read_text(encoding="utf-8"))
        rows = payload.get("quotes", []) if isinstance(payload, dict) else payload
        quotes = []
        for row in rows:
            if isinstance(row, dict):
                quotes.append(SaudiQuote(**{k: row.get(k) for k in SaudiQuote.__dataclass_fields__}))
        blocked_sources = {"s" + "ahmk", "simple" + "scraper", "yfinance", "free_fallback"}
        return [
            quote
            for quote in quotes
            if quote.symbol and quote.price is not None and (quote.source or "").lower() not in blocked_sources
        ]
    except Exception as exc:
        logger.warning("Saudi cache file read failed: {}", exc)
        return []


def _save_file_cache(quotes: list[SaudiQuote]) -> None:
    try:
        SAUDI_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "source": _last_source,
            "endpoint": _last_endpoint,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "quotes": [asdict(quote) for quote in quotes],
        }
        SAUDI_CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        logger.warning("Saudi cache file write failed: {}", exc)


def refresh_saudi_quotes(force: bool = False) -> list[SaudiQuote]:
    global _last_error, _last_refresh, _last_source, _quotes_cache
    if not settings.saudi_exchange_enabled:
        _last_source = "disabled"
        return list(_quotes_cache.values())

    now = time.time()
    if not force and _last_refresh and now - _last_refresh < settings.saudi_prices_ttl_seconds:
        return list(_quotes_cache.values())

    try:
        quotes = _fetch_tadawul_web_quotes()
        if quotes:
            _quotes_cache = {quote.symbol: quote for quote in quotes}
            _last_refresh = now
            _last_source = "tadawul_web"
            _last_error = ""
            _save_file_cache(quotes)
            return quotes
        _last_error = "Tadawul page returned no quote rows"
    except Exception as exc:
        _last_error = f"tadawul_web: {exc}"[:500]
        logger.warning("Saudi quote fetch failed via Tadawul web: {}", exc)

    cached = _load_file_cache()
    if cached:
        _quotes_cache = {quote.symbol: quote for quote in cached}
        _last_refresh = now
        _last_source = "file_cache"
        return cached

    _last_refresh = now
    return list(_quotes_cache.values())


def get_saudi_quote(symbol: str, force_refresh: bool = False) -> Optional[SaudiQuote]:
    normalized = normalize_saudi_symbol(symbol)
    quote = _quotes_cache.get(normalized)
    if quote and not force_refresh and time.time() - _last_refresh < settings.saudi_prices_ttl_seconds:
        return quote

    quotes = refresh_saudi_quotes(force=force_refresh)
    return {quote.symbol: quote for quote in quotes}.get(normalized)


def get_saudi_current_price(symbol: str) -> Optional[float]:
    quote = get_saudi_quote(symbol)
    return quote.price if quote else None


def get_saudi_ohlcv(symbol: str, outputsize: int = 200) -> Optional[list[dict[str, float]]]:
    quote = get_saudi_quote(symbol)
    if not quote or quote.price is None:
        return None
    now = int(time.time())
    candles: list[dict[str, float]] = []
    if quote.previous_close:
        candles.append(
            {
                "timestamp": now - 86400,
                "open": float(quote.previous_close),
                "high": float(max(quote.previous_close, quote.high_price or quote.previous_close)),
                "low": float(min(quote.previous_close, quote.low_price or quote.previous_close)),
                "close": float(quote.previous_close),
                "volume": 0.0,
            }
        )
    candles.append(
        {
            "timestamp": now,
            "open": float(quote.open_price or quote.previous_close or quote.price),
            "high": float(quote.high_price or quote.price),
            "low": float(quote.low_price or quote.price),
            "close": float(quote.price),
            "volume": float(quote.volume or 0),
        }
    )
    return candles[-outputsize:]


def get_saudi_status() -> dict[str, Any]:
    quotes = refresh_saudi_quotes(force=False)
    return {
        "enabled": settings.saudi_exchange_enabled,
        "source": _last_source,
        "count": len(quotes),
        "last_error": _last_error,
        "endpoint": _last_endpoint,
        "page_url": settings.saudi_exchange_page_url or DEFAULT_SAUDI_PAGE_URL,
        "has_tadawul_web": True,
        "has_file_cache": SAUDI_CACHE_FILE.exists(),
    }


async def persist_saudi_quotes(quotes: list[SaudiQuote]) -> int:
    if not quotes:
        return 0
    async with get_session() as session:
        existing_result = await session.execute(select(SaudiMarketQuote))
        existing_quotes = {normalize_saudi_symbol(item.symbol): item for item in existing_result.scalars().all()}
        symbol_result = await session.execute(select(Symbol).where(Symbol.market == "SAUDI"))
        existing_symbols = {normalize_saudi_symbol(item.symbol): item for item in symbol_result.scalars().all()}
        inserted = 0
        for quote in quotes:
            clean_symbol = normalize_saudi_symbol(quote.symbol)
            current = existing_quotes.get(clean_symbol)
            if not current:
                current = SaudiMarketQuote(symbol=clean_symbol)
                session.add(current)
            current.name_ar = quote.name_ar or current.name_ar
            current.name_en = quote.name_en or current.name_en
            current.sector = quote.sector or current.sector
            current.price = quote.price
            current.open_price = quote.open_price
            current.high_price = quote.high_price
            current.low_price = quote.low_price
            current.previous_close = quote.previous_close
            current.change_value = quote.change_value
            current.change_percent = quote.change_percent
            current.volume = quote.volume
            current.turnover = quote.turnover
            current.trades = quote.trades
            current.bid_price = quote.bid_price
            current.ask_price = quote.ask_price
            current.source = quote.source
            current.source_updated_at = quote.source_updated_at

            session.add(
                SaudiMarketSnapshot(
                    symbol=clean_symbol,
                    price=quote.price,
                    open_price=quote.open_price,
                    high_price=quote.high_price,
                    low_price=quote.low_price,
                    previous_close=quote.previous_close,
                    volume=quote.volume,
                    source_updated_at=quote.source_updated_at,
                )
            )

            symbol_row = existing_symbols.get(clean_symbol)
            yahoo_symbol = f"{clean_symbol}.SR"
            if symbol_row:
                symbol_row.yahoo_symbol = yahoo_symbol
                symbol_row.name_ar = quote.name_ar or symbol_row.name_ar
                symbol_row.name_en = quote.name_en or quote.name_ar or symbol_row.name_en
                symbol_row.sector = quote.sector or symbol_row.sector
                symbol_row.exchange = "Saudi Exchange"
                symbol_row.currency = "SAR"
                symbol_row.asset_type = "stock"
                symbol_row.is_active = True
            else:
                session.add(
                    Symbol(
                        market="SAUDI",
                        symbol=yahoo_symbol,
                        yahoo_symbol=yahoo_symbol,
                        name_ar=quote.name_ar or clean_symbol,
                        name_en=quote.name_en or quote.name_ar or clean_symbol,
                        sector=quote.sector or "Saudi Listed",
                        category=quote.sector or "Saudi Listed",
                        exchange="Saudi Exchange",
                        currency="SAR",
                        asset_type="stock",
                        is_active=True,
                    )
                )
                inserted += 1
        await session.commit()
        return inserted


async def refresh_and_persist_saudi_quotes(force: bool = True) -> dict[str, Any]:
    quotes = await asyncio.to_thread(refresh_saudi_quotes, force)
    inserted = await persist_saudi_quotes(quotes)
    return {
        "count": len(quotes),
        "inserted_symbols": inserted,
        "source": _last_source,
        "endpoint": _last_endpoint,
        "last_error": _last_error,
    }
