from typing import List, Optional
from functools import wraps

import requests
from loguru import logger
import yfinance as yf

from config import settings
from services.cache import cache, market_cache_key

MAP_INTERVAL = {"15min": "15m", "30min": "30m", "1h": "60m", "4h": "4h", "1d": "1d", "1wk": "1wk"}
BINANCE_INTERVAL = {"15min": "15m", "30min": "30m", "1h": "1h", "4h": "4h", "1d": "1d", "1wk": "1w"}
BINANCE_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "TDawlXBot/2.0 market-data",
}

MAX_RETRIES = 3
RETRY_DELAY = 1.5
CLOSE_PRICES_TTL = 60
OHLCV_TTL = 60
CURRENT_PRICE_TTL = 30


def _retry(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    logger.warning("Retry {}/{} for {}: {}", attempt, MAX_RETRIES, func.__name__, e)
                    import time
                    time.sleep(RETRY_DELAY * attempt)
        logger.error("All {} retries failed for {}: {}", MAX_RETRIES, func.__name__, last_error)
        raise last_error
    return wrapper


class YahooFinanceProvider:
    @staticmethod
    def _normalize_symbol(symbol: str, market: str) -> str:
        s = symbol.strip().upper()
        if market.upper() == "SAUDI":
            if not s.endswith(".SR"):
                s = f"{s}.SR"
        elif market.upper() == "CRYPTO":
            s = _to_yahoo_crypto_symbol(s)
        return s

    @staticmethod
    @_retry
    def get_historical(symbol: str, interval: str, period: str = "6mo", market: str = "US") -> Optional[dict]:
        mapped = MAP_INTERVAL.get(interval, interval)
        sym = YahooFinanceProvider._normalize_symbol(symbol, market)
        ticker = yf.Ticker(sym)
        df = ticker.history(period=period, interval=mapped)
        if df.empty:
            return None
        data = []
        for idx, row in df.iterrows():
            data.append({
                "timestamp": int(idx.timestamp()),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row["Volume"]),
            })
        return {"symbol": sym, "interval": mapped, "data": data}

    @staticmethod
    @_retry
    def get_current_price(symbol: str, market: str = "US") -> Optional[float]:
        sym = YahooFinanceProvider._normalize_symbol(symbol, market)
        ticker = yf.Ticker(sym)
        data = ticker.history(period="1d", interval="1m")
        if data.empty:
            return None
        return float(data["Close"].iloc[-1])

    @staticmethod
    def get_market_status() -> dict:
        now = settings.now()
        hour = now.hour
        minute = now.minute
        current = hour * 60 + minute

        saudi_open_h, saudi_open_m = map(int, settings.saudi_open.split(":"))
        saudi_close_h, saudi_close_m = map(int, settings.saudi_close.split(":"))
        us_open_h, us_open_m = map(int, settings.us_open.split(":"))
        us_close_h, us_close_m = map(int, settings.us_close.split(":"))

        saudi_start = saudi_open_h * 60 + saudi_open_m
        saudi_end = saudi_close_h * 60 + saudi_close_m
        us_start = us_open_h * 60 + us_open_m
        us_end = us_close_h * 60 + us_close_m

        return {
            "saudi": "open" if saudi_start <= current <= saudi_end else "closed",
            "us": "open" if us_start <= current <= us_end else "closed",
            "crypto": "open",
        }


class BinanceProvider:
    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        s = symbol.strip().upper()
        if not s.endswith("USDT"):
            s = f"{s}USDT"
        return s

    @staticmethod
    def _base_urls() -> list[str]:
        urls = [url.rstrip("/") for url in settings.binance_base_urls if url.strip()]
        return urls or ["https://api.binance.com"]

    @staticmethod
    def _get_json(path: str, params: dict | None = None, timeout: int = 15):
        last_error: Exception | None = None
        for base_url in BinanceProvider._base_urls():
            url = f"{base_url}{path}"
            try:
                resp = requests.get(url, params=params, headers=BINANCE_HEADERS, timeout=timeout)
                if resp.status_code in (418, 429):
                    retry_after = resp.headers.get("Retry-After")
                    logger.warning(
                        "Binance rate limited status={} base={} retry_after={}",
                        resp.status_code,
                        base_url,
                        retry_after or "n/a",
                    )
                    last_error = requests.HTTPError(f"{resp.status_code} from {base_url}")
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:
                last_error = exc
                logger.warning("Binance endpoint failed base={} path={}: {}", base_url, path, exc)
                continue
        if last_error:
            raise last_error
        raise RuntimeError("No Binance endpoints configured")

    @staticmethod
    def get_historical(symbol: str, interval: str, limit: int = 200) -> Optional[List[dict]]:
        sym = BinanceProvider._normalize_symbol(symbol)
        mapped = BINANCE_INTERVAL.get(interval, interval)
        params = {"symbol": sym, "interval": mapped, "limit": limit}
        klines = BinanceProvider._get_json("/api/v3/klines", params=params, timeout=15)
        data = []
        for k in klines:
            data.append({
                "timestamp": int(k[0]) // 1000,
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
            })
        return data

    @staticmethod
    def get_current_price(symbol: str) -> Optional[float]:
        sym = BinanceProvider._normalize_symbol(symbol)
        params = {"symbol": sym}
        data = BinanceProvider._get_json("/api/v3/ticker/price", params=params, timeout=10)
        return float(data["price"])

    @staticmethod
    def ping() -> bool:
        BinanceProvider._get_json("/api/v3/ping", timeout=5)
        return True


class DataProviderFactory:
    @staticmethod
    def get_provider(market: str):
        if market.upper() == "CRYPTO":
            return BinanceProvider()
        return YahooFinanceProvider()


def _to_yahoo_crypto_symbol(symbol: str) -> str:
    s = symbol.strip().upper().replace("/", "-")
    if s.endswith("-USD"):
        return s
    if s.endswith("USDT"):
        return f"{s[:-4]}-USD"
    if s.endswith("USD"):
        return f"{s[:-3]}-USD"
    return f"{s}-USD"


def _crypto_historical(symbol: str, interval: str, outputsize: int) -> Optional[List[dict]]:
    if settings.binance_enabled:
        try:
            return BinanceProvider.get_historical(symbol, interval, outputsize)
        except Exception as exc:
            logger.warning("Binance crypto historical failed, falling back to Yahoo: {}", exc)

    result = YahooFinanceProvider.get_historical(symbol, interval, period="6mo", market="CRYPTO")
    if result:
        return result["data"][-outputsize:]
    return None


def _crypto_current_price(symbol: str) -> Optional[float]:
    if settings.binance_enabled:
        try:
            return BinanceProvider.get_current_price(symbol)
        except Exception as exc:
            logger.warning("Binance crypto price failed, falling back to Yahoo: {}", exc)
    return YahooFinanceProvider.get_current_price(symbol, "CRYPTO")


def _saudi_free_historical(symbol: str, interval: str, outputsize: int) -> Optional[List[dict]]:
    if not settings.saudi_free_fallback_enabled or not settings.yfinance_enabled:
        return None
    try:
        result = YahooFinanceProvider.get_historical(symbol, interval, period="6mo", market="SAUDI")
        if result:
            logger.warning("Saudi free fallback used for historical data: {}", symbol)
            return result["data"][-outputsize:]
    except Exception as exc:
        logger.warning("Saudi free fallback historical failed for {}: {}", symbol, exc)
    return None


def _saudi_free_current_price(symbol: str) -> Optional[float]:
    if not settings.saudi_free_fallback_enabled or not settings.yfinance_enabled:
        return None
    try:
        price = YahooFinanceProvider.get_current_price(symbol, "SAUDI")
        if price is not None:
            logger.warning("Saudi free fallback used for current price: {}", symbol)
        return price
    except Exception as exc:
        logger.warning("Saudi free fallback price failed for {}: {}", symbol, exc)
        return None


def get_close_prices(symbol: str, market: str, interval: str, outputsize: int = 200) -> List[float]:
    cache_key = market_cache_key("closes", market, symbol, interval, outputsize)
    cached = cache.get(cache_key)
    if cached is not None:
        return list(cached)

    market_key = market.upper()
    if market_key == "SAUDI":
        from services.saudi_exchange import get_saudi_ohlcv

        data = get_saudi_ohlcv(symbol, outputsize)
        if not data or len(data) < 30:
            data = _saudi_free_historical(symbol, interval, outputsize)
    elif market_key == "CRYPTO":
        data = _crypto_historical(symbol, interval, outputsize)
    else:
        provider = DataProviderFactory.get_provider(market)
        result = provider.get_historical(symbol, interval, period="6mo", market=market)
        if result:
            data = result["data"][-outputsize:]
        else:
            data = None
    if not data:
        return []
    closes = [d["close"] for d in data]
    cache.set(cache_key, list(closes), CLOSE_PRICES_TTL)
    return closes


def get_ohlcv(symbol: str, market: str, interval: str, outputsize: int = 200) -> Optional[List[dict]]:
    cache_key = market_cache_key("ohlcv", market, symbol, interval, outputsize)
    cached = cache.get(cache_key)
    if cached is not None:
        return list(cached)

    market_key = market.upper()
    if market_key == "SAUDI":
        from services.saudi_exchange import get_saudi_ohlcv

        data = get_saudi_ohlcv(symbol, outputsize)
        if not data or len(data) < 30:
            data = _saudi_free_historical(symbol, interval, outputsize)
    elif market_key == "CRYPTO":
        data = _crypto_historical(symbol, interval, outputsize)
    else:
        provider = DataProviderFactory.get_provider(market)
        result = provider.get_historical(symbol, interval, period="6mo", market=market)
        if result:
            data = result["data"][-outputsize:]
        else:
            data = None

    if data is not None:
        cache.set(cache_key, list(data), OHLCV_TTL)
    return data


def get_current_price_sync(symbol: str, market: str) -> Optional[float]:
    cache_key = market_cache_key("price", market, symbol, "spot", 1)
    cached = cache.get(cache_key)
    if cached is not None:
        return float(cached)

    market_key = market.upper()
    if market_key == "SAUDI":
        from services.saudi_exchange import get_saudi_current_price

        price = get_saudi_current_price(symbol)
        if price is None:
            price = _saudi_free_current_price(symbol)
    elif market_key == "CRYPTO":
        price = _crypto_current_price(symbol)
    else:
        provider = DataProviderFactory.get_provider(market)
        price = provider.get_current_price(symbol, market)

    if price is not None:
        cache.set(cache_key, float(price), CURRENT_PRICE_TTL)
    return price
