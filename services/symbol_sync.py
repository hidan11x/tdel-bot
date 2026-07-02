import asyncio
import csv
import html
import io
import re
from typing import Any

import requests
import yfinance as yf
from loguru import logger
from sqlalchemy import select

from config import settings
from database import get_session
from models import Symbol


NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
STOCKANALYSIS_SAUDI_URL = "https://stockanalysis.com/list/saudi-stock-exchange/"
SAUDI_CODE_RANGES = ((1000, 9999),)


def _get_text(url: str, timeout: int = 25) -> str:
    response = requests.get(url, timeout=timeout, headers={"User-Agent": "TDawlXBot/2.0 symbol-sync"})
    response.raise_for_status()
    return response.text


def _parse_pipe_table(text: str) -> list[dict[str, str]]:
    lines = [line for line in text.splitlines() if line and not line.startswith("File Creation Time")]
    reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter="|")
    return [dict(row) for row in reader if row]


def _clean_symbol(symbol: str) -> str:
    return (symbol or "").strip().upper().replace("$", "-")


def _clean_name(name: str | None, fallback: str) -> str:
    cleaned = re.sub(r"\s+", " ", name or "").strip()
    return cleaned or fallback


async def _upsert_symbols(items: list[dict[str, Any]]) -> int:
    if not items:
        return 0

    async with get_session() as session:
        existing_result = await session.execute(
            select(Symbol).where(Symbol.market.in_(list({item["market"] for item in items})))
        )
        existing = {(item.market, item.symbol): item for item in existing_result.scalars().all()}
        seen = set(existing)
        added = 0
        max_sort = len(existing) + 1

        for item in items:
            key = (item["market"], item["symbol"])
            current = existing.get(key)
            if current:
                name_en = _clean_name(item.get("name_en"), item["symbol"])[:180]
                name_ar = _clean_name(item.get("name_ar"), name_en)[:180]
                if name_en and name_en != item["symbol"]:
                    current.name_en = name_en
                if name_ar and name_ar != item["symbol"] and (
                    not current.name_ar or current.name_ar == current.symbol
                ):
                    current.name_ar = name_ar
                current.yahoo_symbol = item["yahoo_symbol"][:40]
                current.exchange = item.get("exchange") or current.exchange
                current.currency = item.get("currency") or current.currency
                current.asset_type = item.get("asset_type") or current.asset_type
                current.is_active = True
                continue
            if key in seen:
                continue

            session.add(
                Symbol(
                    market=item["market"],
                    symbol=item["symbol"],
                    yahoo_symbol=item["yahoo_symbol"],
                    name_ar=item["name_ar"][:180],
                    name_en=item["name_en"][:180],
                    sector=item.get("sector") or item.get("category"),
                    category=item.get("category"),
                    exchange=item.get("exchange"),
                    currency=item.get("currency", "USD"),
                    asset_type=item.get("asset_type", "stock"),
                    is_active=True,
                    is_popular=False,
                    sort_order=max_sort,
                )
            )
            seen.add(key)
            max_sort += 1
            added += 1

        await session.commit()
        return added


async def sync_us_symbols(limit: int = 7000) -> dict[str, Any]:
    def fetch() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for url, exchange_name in ((NASDAQ_LISTED_URL, "NASDAQ"), (OTHER_LISTED_URL, "US")):
            rows = _parse_pipe_table(_get_text(url))
            for row in rows:
                raw_symbol = row.get("Symbol") or row.get("ACT Symbol") or ""
                symbol = _clean_symbol(raw_symbol)
                name = (row.get("Security Name") or row.get("Company Name") or symbol).strip()
                if not symbol or symbol in {"TEST", "ZVZZT"} or "test stock" in name.lower():
                    continue
                if row.get("ETF", "").upper() == "Y":
                    asset_type = "fund"
                else:
                    asset_type = "stock"
                items.append(
                    {
                        "market": "US",
                        "symbol": symbol,
                        "yahoo_symbol": symbol,
                        "name_ar": name,
                        "name_en": name,
                        "sector": "US Listed",
                        "category": "US Listed",
                        "exchange": row.get("Listing Exchange") or exchange_name,
                        "currency": "USD",
                        "asset_type": asset_type,
                    }
                )
                if len(items) >= limit:
                    return items
        return items

    items = await asyncio.to_thread(fetch)
    added = await _upsert_symbols(items)
    return {"market": "US", "fetched": len(items), "added": added}


async def sync_crypto_symbols(limit: int = 1200) -> dict[str, Any]:
    def fetch() -> list[dict[str, Any]]:
        last_error: Exception | None = None
        for base in settings.binance_base_urls:
            try:
                response = requests.get(
                    f"{base.rstrip('/')}/api/v3/exchangeInfo",
                    timeout=25,
                    headers={"User-Agent": "TDawlXBot/2.0 symbol-sync"},
                )
                response.raise_for_status()
                data = response.json()
                items = []
                for row in data.get("symbols", []):
                    if row.get("status") != "TRADING" or row.get("quoteAsset") != "USDT":
                        continue
                    symbol = row.get("symbol", "").upper()
                    base_asset = row.get("baseAsset", symbol.replace("USDT", ""))
                    if not symbol:
                        continue
                    items.append(
                        {
                            "market": "CRYPTO",
                            "symbol": symbol,
                            "yahoo_symbol": f"{base_asset}-USD",
                            "name_ar": base_asset,
                            "name_en": base_asset,
                            "sector": "Crypto",
                            "category": "Crypto",
                            "exchange": "Binance",
                            "currency": "USDT",
                            "asset_type": "crypto",
                        }
                    )
                    if len(items) >= limit:
                        return items
                return items
            except Exception as exc:
                last_error = exc
                continue
        if last_error:
            raise last_error
        return []

    try:
        items = await asyncio.to_thread(fetch)
    except Exception as exc:
        logger.warning("Crypto symbol sync failed: {}", exc)
        items = []
    added = await _upsert_symbols(items)
    return {"market": "CRYPTO", "fetched": len(items), "added": added}


def _parse_stockanalysis_saudi(text: str, limit: int) -> list[dict[str, Any]]:
    row_pattern = re.compile(
        r'<a href="/quote/tadawul/(?P<symbol>\d{4})/">(?P=symbol)</a>.*?'
        r'<td class="slw[^"]*">(?P<name>.*?)</td>',
        re.IGNORECASE | re.DOTALL,
    )
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in row_pattern.finditer(text):
        symbol = match.group("symbol")
        if symbol in seen:
            continue
        name = re.sub(r"<.*?>", "", match.group("name"))
        name = _clean_name(html.unescape(name), symbol)
        items.append(
            {
                "market": "SAUDI",
                "symbol": symbol,
                "yahoo_symbol": f"{symbol}.SR",
                "name_ar": name,
                "name_en": name,
                "sector": "Saudi Listed",
                "category": "Saudi Listed",
                "exchange": "Saudi Exchange",
                "currency": "SAR",
                "asset_type": "stock",
            }
        )
        seen.add(symbol)
        if len(items) >= limit:
            break
    return items


def _probe_saudi_symbol(symbol: str) -> dict[str, Any] | None:
    yahoo_symbol = f"{symbol}.SR"
    try:
        history = yf.Ticker(yahoo_symbol).history(period="5d", interval="1d")
    except Exception:
        return None
    if history is None or history.empty:
        return None
    return {
        "market": "SAUDI",
        "symbol": symbol,
        "yahoo_symbol": yahoo_symbol,
        "name_ar": symbol,
        "name_en": symbol,
        "sector": "Saudi Listed",
        "category": "Saudi Listed",
        "exchange": "Saudi Exchange",
        "currency": "SAR",
        "asset_type": "stock",
    }


async def _probe_saudi_candidates(candidates: list[str], limit: int) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(24)

    async def check(symbol: str) -> dict[str, Any] | None:
        async with semaphore:
            return await asyncio.to_thread(_probe_saudi_symbol, symbol)

    found: list[dict[str, Any]] = []
    for start in range(0, len(candidates), 240):
        batch = candidates[start : start + 240]
        results = await asyncio.gather(*(check(symbol) for symbol in batch))
        found.extend(item for item in results if item)
        if len(found) >= limit:
            return found[:limit]
    return found[:limit]


async def sync_saudi_symbols(limit: int = 1200) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    try:
        text = await asyncio.to_thread(_get_text, STOCKANALYSIS_SAUDI_URL, 30)
        for item in _parse_stockanalysis_saudi(text, limit):
            items.append(item)
            seen.add(item["symbol"])
    except Exception as exc:
        logger.warning("Saudi stock list fetch failed: {}", exc)

    async with get_session() as session:
        result = await session.execute(select(Symbol).where(Symbol.market == "SAUDI"))
        existing_symbols = result.scalars().all()

    for current in existing_symbols:
        if current.symbol in seen:
            continue
        items.append(
            {
                "market": "SAUDI",
                "symbol": current.symbol,
                "yahoo_symbol": current.yahoo_symbol or f"{current.symbol}.SR",
                "name_ar": current.name_ar or current.name_en or current.symbol,
                "name_en": current.name_en or current.name_ar or current.symbol,
                "sector": current.sector or "Saudi Listed",
                "category": current.category or "Saudi Listed",
                "exchange": current.exchange or "Saudi Exchange",
                "currency": current.currency or "SAR",
                "asset_type": current.asset_type or "stock",
            }
        )
        seen.add(current.symbol)

    if len(items) < 250:
        candidates = sorted(
            {
                f"{code:04d}"
                for start, end in SAUDI_CODE_RANGES
                for code in range(start, end + 1)
            }
            - seen
        )
        for item in await _probe_saudi_candidates(candidates, limit - len(items)):
            items.append(item)
            seen.add(item["symbol"])

    added = await _upsert_symbols(items[:limit])
    return {"market": "SAUDI", "fetched": len(items[:limit]), "added": added}


async def sync_symbol_universe() -> list[dict[str, Any]]:
    saudi, us, crypto = await asyncio.gather(
        sync_saudi_symbols(),
        sync_us_symbols(limit=12000),
        sync_crypto_symbols(limit=5000),
    )
    return [saudi, us, crypto]
