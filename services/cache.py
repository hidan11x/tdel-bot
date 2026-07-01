import time
from threading import RLock
from typing import Any, Dict, Optional, Tuple


class TTLCache:
    def __init__(self) -> None:
        self._store: Dict[str, Tuple[float, Any]] = {}
        self._lock = RLock()

    def get(self, key: str) -> Optional[Any]:
        now = time.time()
        with self._lock:
            item = self._store.get(key)
            if not item:
                return None
            expires_at, value = item
            if expires_at <= now:
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            return
        expires_at = time.time() + ttl_seconds
        with self._lock:
            self._store[key] = (expires_at, value)


cache = TTLCache()


def market_cache_key(data_type: str, market: str, symbol: str, timeframe: str, outputsize: int) -> str:
    dt = (data_type or "data").lower()
    m = (market or "").upper()
    s = (symbol or "").upper()
    tf = (timeframe or "").lower()
    return f"{dt}:{m}:{s}:{tf}:{int(outputsize)}"
