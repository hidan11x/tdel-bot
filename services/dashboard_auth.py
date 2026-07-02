import base64
import hashlib
import hmac
import os

from config import settings


def _clean(value: str) -> str:
    value = (value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def _secret() -> bytes:
    raw = _clean(os.getenv("DASHBOARD_SECRET", "")) or settings.bot_token or "telegram-trading-bot"
    return raw.encode("utf-8")


def dashboard_token(telegram_id: int) -> str:
    message = f"vip-dashboard:{telegram_id}".encode("utf-8")
    digest = hmac.new(_secret(), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def verify_dashboard_token(telegram_id: int, token: str) -> bool:
    if not token:
        return False
    return hmac.compare_digest(dashboard_token(telegram_id), token)


def dashboard_base_url() -> str:
    configured = _clean(os.getenv("DASHBOARD_BASE_URL", "")).rstrip("/")
    if configured:
        return configured

    railway_domain = _clean(os.getenv("RAILWAY_PUBLIC_DOMAIN", ""))
    if railway_domain:
        return f"https://{railway_domain}".rstrip("/")

    return "http://localhost:8080"


def dashboard_url(telegram_id: int) -> str:
    return f"{dashboard_base_url()}/dashboard/{telegram_id}/{dashboard_token(telegram_id)}"
