import time
from typing import List, Optional
from functools import wraps

import requests
import yfinance as yf

from config import settings

MAP_INTERVAL = {"15min": "15m", "30min": "30m", "1h": "60m", "4h": "4h", "1d": "1d", "1wk": "1wk"}
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/price"

MAX_RETRIES = 3
RETRY_DELAY = 1.5


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
                    time.sleep(RETRY_DELAY * attempt)
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
            if not s.endswith("USDT"):
                s = f"{s}USDT"
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
        import datetime
        now = datetime.datetime.now()
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
    @_retry
    def get_historical(symbol: str, interval: str, limit: int = 200) -> Optional[List[dict]]:
        sym = BinanceProvider._normalize_symbol(symbol)
        mapped = MAP_INTERVAL.get(interval, interval)
        params = {"symbol": sym, "interval": mapped, "limit": limit}
        resp = requests.get(BINANCE_KLINES_URL, params=params, timeout=15)
        resp.raise_for_status()
        klines = resp.json()
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
    @_retry
    def get_current_price(symbol: str) -> Optional[float]:
        sym = BinanceProvider._normalize_symbol(symbol)
        params = {"symbol": sym}
        resp = requests.get(BINANCE_TICKER_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return float(data["price"])


class DataProviderFactory:
    @staticmethod
    def get_provider(market: str):
        if market.upper() == "CRYPTO":
            return BinanceProvider()
        return YahooFinanceProvider()


def get_close_prices(symbol: str, market: str, interval: str, outputsize: int = 200) -> List[float]:
    provider = DataProviderFactory.get_provider(market)
    if isinstance(provider, BinanceProvider):
        data = provider.get_historical(symbol, interval, outputsize)
    else:
        result = provider.get_historical(symbol, interval, period="6mo", market=market)
        if result:
            data = result["data"][-outputsize:]
        else:
            data = None
    if not data:
        return []
    return [d["close"] for d in data]


def get_ohlcv(symbol: str, market: str, interval: str, outputsize: int = 200) -> Optional[List[dict]]:
    provider = DataProviderFactory.get_provider(market)
    if isinstance(provider, BinanceProvider):
        return provider.get_historical(symbol, interval, outputsize)
    result = provider.get_historical(symbol, interval, period="6mo", market=market)
    if result:
        return result["data"][-outputsize:]
    return None


def get_current_price_sync(symbol: str, market: str) -> Optional[float]:
    provider = DataProviderFactory.get_provider(market)
    if isinstance(provider, BinanceProvider):
        return provider.get_current_price(symbol)
    return provider.get_current_price(symbol, market)
