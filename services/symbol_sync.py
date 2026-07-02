import asyncio
import csv
import io
from typing import Any

import requests
from loguru import logger
from sqlalchemy import select

from config import settings
from database import get_session
from models import Symbol


NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"


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
                current.name_en = item["name_en"][:180]
                current.name_ar = current.name_ar or item["name_ar"][:180]
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


async def sync_symbol_universe() -> list[dict[str, Any]]:
    us, crypto = await asyncio.gather(sync_us_symbols(), sync_crypto_symbols())
    return [us, crypto]
