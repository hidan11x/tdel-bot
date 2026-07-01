import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

load_dotenv()


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _int(key: str, default: int = 0) -> int:
    try:
        return int(_env(key, str(default)))
    except ValueError:
        return default


def _float(key: str, default: float = 0.0) -> float:
    try:
        return float(_env(key, str(default)))
    except ValueError:
        return default


def _list(key: str, default: str = "") -> List[int]:
    raw = _env(key, default)
    return [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]


@dataclass
class Settings:
    bot_token: str = field(default_factory=lambda: _env("BOT_TOKEN"))
    admin_ids: List[int] = field(default_factory=lambda: _list("ADMIN_IDS", "8601339909"))
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "sqlite+aiosqlite:///data/bot.db"))

    yfinance_enabled: bool = field(default_factory=lambda: _env("YFINANCE_ENABLED", "true").lower() == "true")
    binance_enabled: bool = field(default_factory=lambda: _env("BINANCE_ENABLED", "true").lower() == "true")

    saudi_open: str = field(default_factory=lambda: _env("SAUDI_MARKET_OPEN", "10:00"))
    saudi_close: str = field(default_factory=lambda: _env("SAUDI_MARKET_CLOSE", "15:00"))
    us_open: str = field(default_factory=lambda: _env("US_MARKET_OPEN", "15:30"))
    us_close: str = field(default_factory=lambda: _env("US_MARKET_CLOSE", "22:00"))

    free_scans_daily: int = field(default_factory=lambda: _int("FREE_SCANS_DAILY", 5))
    free_alerts: int = field(default_factory=lambda: _int("FREE_ALERTS", 3))
    free_watchlist: int = field(default_factory=lambda: _int("FREE_WATCHLIST", 5))
    basic_scans_daily: int = field(default_factory=lambda: _int("BASIC_SCANS_DAILY", 30))
    basic_alerts: int = field(default_factory=lambda: _int("BASIC_ALERTS", 15))
    basic_watchlist: int = field(default_factory=lambda: _int("BASIC_WATCHLIST", 20))
    pro_scans_daily: int = field(default_factory=lambda: _int("PRO_SCANS_DAILY", 100))
    pro_alerts: int = field(default_factory=lambda: _int("PRO_ALERTS", 50))
    pro_watchlist: int = field(default_factory=lambda: _int("PRO_WATCHLIST", 50))
    vip_scans_daily: int = field(default_factory=lambda: _int("VIP_SCANS_DAILY", -1))
    vip_alerts: int = field(default_factory=lambda: _int("VIP_ALERTS", -1))
    vip_watchlist: int = field(default_factory=lambda: _int("VIP_WATCHLIST", -1))

    basic_price: float = field(default_factory=lambda: _float("BASIC_PRICE", 29))
    pro_price: float = field(default_factory=lambda: _float("PRO_PRICE", 79))
    vip_price: float = field(default_factory=lambda: _float("VIP_PRICE", 199))
    lifetime_price: float = field(default_factory=lambda: _float("LIFETIME_PRICE", 499))
    trial_days: int = field(default_factory=lambda: _int("TRIAL_DAYS", 7))

    chart_theme: str = field(default_factory=lambda: _env("CHART_THEME", "dark"))


settings = Settings()
