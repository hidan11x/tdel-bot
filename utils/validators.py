import re
import time
from typing import Dict, Tuple
from collections import defaultdict

from config import settings

VALID_MARKETS = {"US", "SAUDI", "CRYPTO"}
VALID_TIMEFRAMES = {"15min", "30min", "1h", "4h", "1d", "1wk"}
VALID_ALERT_TYPES = {
    "price_above", "price_below",
    "rsi_above", "rsi_below",
    "volume_spike",
    "near_support", "near_resistance",
    "price_change_percent",
}

SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9.\-]{1,20}$")

_rate_limit_store: Dict[int, list] = defaultdict(list)
_RATE_LIMIT_WINDOW = 60
_RATE_LIMIT_MAX = 10


def is_valid_symbol(symbol: str) -> bool:
    if not symbol or not isinstance(symbol, str):
        return False
    return bool(SYMBOL_PATTERN.match(symbol.strip().upper()))


def is_valid_market(market: str) -> bool:
    return market.upper() in VALID_MARKETS


def is_valid_timeframe(tf: str) -> bool:
    return tf in VALID_TIMEFRAMES


def is_valid_alert_type(alert_type: str) -> bool:
    return alert_type in VALID_ALERT_TYPES


def is_valid_price(price: float) -> bool:
    if not isinstance(price, (int, float)):
        return False
    return 0 < price < 1_000_000


async def is_user_banned(user) -> bool:
    if hasattr(user, "is_banned"):
        return bool(user.is_banned)
    return False


def check_rate_limit(user_id: int) -> bool:
    now = time.time()
    window_start = now - _RATE_LIMIT_WINDOW
    timestamps = _rate_limit_store.get(user_id, [])
    timestamps = [t for t in timestamps if t > window_start]
    if len(timestamps) >= _RATE_LIMIT_MAX:
        return False
    timestamps.append(now)
    _rate_limit_store[user_id] = timestamps
    return True


async def validate_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids
