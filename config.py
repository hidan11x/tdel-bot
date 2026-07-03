import os
from datetime import date, datetime
from dataclasses import dataclass, field
from typing import List
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from dotenv import load_dotenv

load_dotenv()


def _env(key: str, default: str = "") -> str:
    value = os.getenv(key, default).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


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


def _str_list(key: str, default: str = "") -> List[str]:
    raw = _env(key, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


@dataclass
class Settings:
    bot_token: str = field(default_factory=lambda: _env("BOT_TOKEN") or _env("TELEGRAM_BOT_TOKEN"))
    admin_ids: List[int] = field(default_factory=lambda: _list("ADMIN_IDS", "8601339909"))
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "sqlite+aiosqlite:///data/bot.db").replace("postgres://", "postgresql://", 1))

    yfinance_enabled: bool = field(default_factory=lambda: _env("YFINANCE_ENABLED", "true").lower() == "true")
    binance_enabled: bool = field(default_factory=lambda: _env("BINANCE_ENABLED", "true").lower() == "true")
    binance_base_urls: List[str] = field(
        default_factory=lambda: _str_list(
            "BINANCE_BASE_URLS",
            "https://api.binance.com,https://api1.binance.com,https://api2.binance.com,https://api3.binance.com,https://api4.binance.com",
        )
    )
    news_notifications_enabled: bool = field(default_factory=lambda: _env("NEWS_NOTIFICATIONS_ENABLED", "false").lower() == "true")
    news_interval_hours: int = field(default_factory=lambda: max(1, _int("NEWS_INTERVAL_HOURS", 12)))
    saudi_exchange_enabled: bool = field(default_factory=lambda: _env("SAUDI_EXCHANGE_ENABLED", "true").lower() == "true")
    saudi_prices_ttl_seconds: int = field(default_factory=lambda: max(60, _int("SAUDI_PRICES_TTL_SECONDS", 300)))
    saudi_free_fallback_enabled: bool = field(default_factory=lambda: _env("SAUDI_FREE_FALLBACK_ENABLED", "true").lower() == "true")
    saudi_exchange_endpoint: str = field(default_factory=lambda: _env("SAUDI_EXCHANGE_ENDPOINT"))
    sahmk_api_key: str = field(default_factory=lambda: _env("SAHMK_API_KEY"))
    sahmk_base_url: str = field(default_factory=lambda: _env("SAHMK_BASE_URL", "https://app.sahmk.sa/api/v1").rstrip("/"))
    sahmk_sync_limit: int = field(default_factory=lambda: max(1, _int("SAHMK_SYNC_LIMIT", 450)))
    simplescraper_api_key: str = field(default_factory=lambda: _env("SIMPLESCRAPER_API_KEY"))
    simplescraper_saudi_api_url: str = field(default_factory=lambda: _env("SIMPLESCRAPER_SAUDI_API_URL"))

    saudi_open: str = field(default_factory=lambda: _env("SAUDI_MARKET_OPEN", "10:00"))
    saudi_close: str = field(default_factory=lambda: _env("SAUDI_MARKET_CLOSE", "15:00"))
    us_open: str = field(default_factory=lambda: _env("US_MARKET_OPEN", "15:30"))
    us_close: str = field(default_factory=lambda: _env("US_MARKET_CLOSE", "22:00"))
    market_timezone: str = field(default_factory=lambda: _env("MARKET_TIMEZONE", "Asia/Riyadh"))

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

    ai_enabled: bool = field(default_factory=lambda: _env("AI_ENABLED", "true").lower() == "true")
    ai_provider: str = field(default_factory=lambda: _env("AI_PROVIDER", "gemini").lower())
    gemini_api_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    gemini_model: str = field(default_factory=lambda: _env("GEMINI_MODEL", "gemini-2.5-flash"))
    ai_daily_limit_basic: int = field(default_factory=lambda: _int("AI_DAILY_LIMIT_BASIC", 0))
    ai_daily_limit_pro: int = field(default_factory=lambda: _int("AI_DAILY_LIMIT_PRO", 0))
    ai_daily_limit_vip: int = field(default_factory=lambda: _int("AI_DAILY_LIMIT_VIP", 30))
    ai_daily_limit_admin: int = field(default_factory=lambda: _int("AI_DAILY_LIMIT_ADMIN", 200))
    ai_max_history: int = field(default_factory=lambda: max(2, _int("AI_MAX_HISTORY", 6)))

    @property
    def timezone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.market_timezone)
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")

    def now(self) -> datetime:
        return datetime.now(self.timezone)

    def today(self) -> date:
        return self.now().date()

    def validate(self) -> None:
        if not self.bot_token:
            raise ValueError(
                "BOT_TOKEN is not set. Set BOT_TOKEN or TELEGRAM_BOT_TOKEN in .env file."
            )
        if not self.database_url:
            raise ValueError(
                "DATABASE_URL is not set. Check your .env file."
            )
        try:
            ZoneInfo(self.market_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(
                f"MARKET_TIMEZONE is invalid: {self.market_timezone}"
            ) from exc


settings = Settings()
