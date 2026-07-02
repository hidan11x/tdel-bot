import asyncio
import platform
import time
from datetime import datetime, timezone
from typing import Optional

import requests
from sqlalchemy import func, select

from config import settings
from database import get_session
from models import ErrorLog, ScanLog, User


def _ok(text: str) -> str:
    return f"✅ {text}"


def _warn(text: str) -> str:
    return f"⚠️ {text}"


def _fail(text: str) -> str:
    return f"❌ {text}"


def _short(value: Optional[str], limit: int = 120) -> str:
    if not value:
        return "لا يوجد"
    text = str(value).replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _safe_database_label() -> str:
    url = settings.database_url
    if url.startswith("sqlite"):
        return "SQLite"
    if "postgresql" in url:
        return "PostgreSQL"
    return "قاعدة بيانات"


async def _check_binance() -> str:
    if not settings.binance_enabled:
        return _warn("Binance معطل من الإعدادات")

    def ping() -> None:
        response = requests.get("https://api.binance.com/api/v3/ping", timeout=5)
        response.raise_for_status()

    try:
        await asyncio.to_thread(ping)
        return _ok("Binance متصل")
    except Exception as exc:
        return _fail(f"Binance غير متاح: {_short(str(exc), 80)}")


async def _check_yfinance() -> str:
    if not settings.yfinance_enabled:
        return _warn("Yahoo Finance معطل من الإعدادات")
    try:
        import yfinance

        version = getattr(yfinance, "__version__", "متاح")
        return _ok(f"Yahoo Finance متاح ({version})")
    except Exception as exc:
        return _fail(f"Yahoo Finance غير متاح: {_short(str(exc), 80)}")


async def build_admin_health_report() -> str:
    started = time.perf_counter()
    now_local = settings.now()
    now_utc = datetime.now(timezone.utc)

    db_line = _fail(f"{_safe_database_label()} غير متصلة")
    total_users = active_users = total_scans = scans_today = errors_today = 0
    last_error = None

    try:
        async with get_session() as session:
            await session.execute(select(1))
            total_users = (await session.execute(select(func.count(User.id)))).scalar() or 0
            active_users = (
                await session.execute(
                    select(func.count(User.id)).where(
                        User.is_active == True,
                        User.is_banned == False,
                    )
                )
            ).scalar() or 0
            total_scans = (await session.execute(select(func.count(ScanLog.id)))).scalar() or 0
            scans_today = (
                await session.execute(
                    select(func.count(ScanLog.id)).where(
                        func.date(ScanLog.created_at) == settings.today()
                    )
                )
            ).scalar() or 0
            errors_today = (
                await session.execute(
                    select(func.count(ErrorLog.id)).where(
                        func.date(ErrorLog.created_at) == settings.today()
                    )
                )
            ).scalar() or 0
            last_error = (
                await session.execute(
                    select(ErrorLog).order_by(ErrorLog.created_at.desc()).limit(1)
                )
            ).scalar_one_or_none()
        db_line = _ok(f"{_safe_database_label()} متصلة")
    except Exception as exc:
        db_line = _fail(f"{_safe_database_label()}: {_short(str(exc), 90)}")

    provider_lines = await asyncio.gather(_check_yfinance(), _check_binance())
    elapsed_ms = round((time.perf_counter() - started) * 1000)

    lines = [
        "🩺 صحة النظام",
        "",
        db_line,
        *provider_lines,
        _ok("APScheduler متاح"),
        "",
        "الوقت:",
        f"• توقيت البوت: {now_local.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"• UTC: {now_utc.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "الاستخدام:",
        f"• المستخدمون: {total_users}",
        f"• النشطون: {active_users}",
        f"• إجمالي الفحوصات: {total_scans}",
        f"• فحوصات اليوم: {scans_today}",
        f"• أخطاء اليوم: {errors_today}",
        "",
        "النظام:",
        f"• Python: {platform.python_version()}",
        f"• البيئة: {platform.system()} {platform.release()}",
        f"• زمن الفحص: {elapsed_ms}ms",
    ]

    if last_error:
        lines.extend(
            [
                "",
                "آخر خطأ:",
                f"• المصدر: {_short(last_error.source, 50)}",
                f"• الرسالة: {_short(last_error.message)}",
                f"• الوقت: {last_error.created_at}",
            ]
        )
    else:
        lines.extend(["", "آخر خطأ:", "• لا توجد أخطاء محفوظة"])

    return "\n".join(lines)
