import html
from datetime import date
from typing import Any
from urllib.parse import quote

import aiohttp
from loguru import logger
from sqlalchemy import select

from config import settings
from database import get_session
from models import DailyUsage, User, Watchlist


AI_CHAT_CONTEXT = "ai_chat"

_history: dict[int, list[dict[str, str]]] = {}


def ai_daily_limit(plan: str, telegram_id: int) -> int:
    if telegram_id in settings.admin_ids:
        return settings.ai_daily_limit_admin
    if plan in ("vip", "lifetime"):
        return settings.ai_daily_limit_vip
    if plan == "pro":
        return settings.ai_daily_limit_pro
    if plan == "basic":
        return settings.ai_daily_limit_basic
    return 0


def is_ai_configured() -> bool:
    return bool(settings.ai_enabled and settings.ai_provider == "gemini" and settings.gemini_api_key)


async def get_ai_usage(user_id: int, day: date | None = None) -> int:
    day = day or settings.today()
    async with get_session() as session:
        result = await session.execute(
            select(DailyUsage).where(DailyUsage.user_id == user_id, DailyUsage.date == day)
        )
        usage = result.scalar_one_or_none()
        return int(getattr(usage, "ai_messages", 0) or 0)


async def increment_ai_usage(user_id: int, day: date | None = None) -> int:
    day = day or settings.today()
    async with get_session() as session:
        result = await session.execute(
            select(DailyUsage).where(DailyUsage.user_id == user_id, DailyUsage.date == day)
        )
        usage = result.scalar_one_or_none()
        if usage:
            usage.ai_messages = int(usage.ai_messages or 0) + 1
        else:
            usage = DailyUsage(user_id=user_id, date=day, scans=0, ai_messages=1)
            session.add(usage)
        await session.commit()
        return int(usage.ai_messages or 0)


async def can_use_ai(user: User | None, telegram_id: int) -> tuple[bool, str, int, int]:
    plan = user.plan if user else "free"
    limit = ai_daily_limit(plan, telegram_id)
    if limit <= 0:
        return False, "مساعد الذكاء متاح لمشتركي VIP فقط.", 0, limit
    if not is_ai_configured():
        return False, "مساعد الذكاء غير مفعّل. أضف GEMINI_API_KEY في Railway ثم أعد النشر.", 0, limit
    if not user:
        return False, "اضغط /start أولاً لتفعيل حسابك.", 0, limit

    used = await get_ai_usage(user.id)
    remaining = max(0, limit - used)
    if remaining <= 0:
        return False, "وصلت للحد اليومي لمساعد الذكاء. جرّب مرة ثانية بكرة.", 0, limit
    return True, "", remaining, limit


async def _watchlist_context(user: User) -> str:
    async with get_session() as session:
        result = await session.execute(
            select(Watchlist).where(Watchlist.user_id == user.id).limit(8)
        )
        items = result.scalars().all()
    if not items:
        return "قائمة المتابعة: لا توجد رموز محفوظة."
    symbols = ", ".join(f"{item.symbol} ({item.market})" for item in items)
    return f"قائمة متابعة المستخدم: {symbols}"


def _scan_context(result: dict[str, Any] | None) -> str:
    if not result:
        return ""
    score = result.get("score")
    score_value = getattr(score, "overall", None)
    indicators = result.get("indicators") or {}
    lines = [
        "بيانات فنية من البوت:",
        f"- الاسم: {result.get('name_ar') or result.get('name_en') or result.get('symbol')}",
        f"- الرمز: {result.get('symbol')} | السوق: {result.get('market')} | الفريم: {result.get('timeframe')}",
        f"- السعر الحالي: {result.get('current_price')}",
        f"- التغير: {result.get('change_percent', 0):.2f}%",
        f"- الاتجاه: {result.get('trend')}",
        f"- الدعم: {result.get('support')} | المقاومة: {result.get('resistance')}",
        f"- التقييم: {result.get('rating')} | المخاطرة: {result.get('risk_level')}",
    ]
    if score_value is not None:
        lines.append(f"- الدرجة الفنية: {float(score_value):.0f}/100")
    if indicators:
        for key in ("rsi", "macd", "sma_20", "sma_50", "volume_ratio"):
            value = indicators.get(key)
            if isinstance(value, (int, float)):
                lines.append(f"- {key}: {value:.2f}")
    return "\n".join(lines)


async def _build_market_context(user: User, question: str) -> str:
    parts = [await _watchlist_context(user)]

    try:
        from services.search_engine import auto_detect_symbol
        from services.scanner import scan_symbol

        detected = await auto_detect_symbol(question)
        if detected:
            symbol = detected["symbol"]
            market = detected["market"]
            scan = await scan_symbol(symbol, market, "1d")
            context = _scan_context(scan)
            if context:
                parts.append(context)
    except Exception:
        logger.exception("AI market context failed")

    return "\n\n".join(part for part in parts if part)


def _system_instruction() -> str:
    return (
        "أنت مساعد تداول ذكي داخل بوت تليقرام اسمه تداول بوت. "
        "جاوب بالعربية وبأسلوب سعودي واضح ومختصر. "
        "ساعد المستخدم في فهم الأسهم والعملات والمؤشرات وإدارة المخاطر. "
        "إذا توفرت بيانات من البوت فاعتمد عليها واذكر أنها قراءة آلية. "
        "لا تدّعي اليقين ولا تقدم ضمان ربح. عند ذكر شراء أو بيع اجعلها كسيناريو احتمالي مع وقف خسارة وإدارة مخاطرة. "
        "لا تستخدم HTML ولا Markdown ثقيل. لا تطلب مفاتيح أو بيانات حساسة."
    )


async def _call_gemini(telegram_id: int, prompt: str, context: str) -> str:
    model = settings.gemini_model.strip() or "gemini-2.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{quote(model, safe='')}:generateContent"
    params = {"key": settings.gemini_api_key}

    history = _history.get(telegram_id, [])[-settings.ai_max_history :]
    contents: list[dict[str, Any]] = []
    for item in history:
        role = "model" if item["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": item["text"][:1800]}]})

    full_prompt = (
        f"سؤال المستخدم:\n{prompt.strip()}\n\n"
        f"سياق من البوت:\n{context or 'لا يوجد سياق سوقي إضافي.'}"
    )
    contents.append({"role": "user", "parts": [{"text": full_prompt}]})

    payload = {
        "systemInstruction": {"parts": [{"text": _system_instruction()}]},
        "contents": contents,
        "generationConfig": {
            "temperature": 0.55,
            "maxOutputTokens": 900,
        },
    }

    timeout = aiohttp.ClientTimeout(total=45)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, params=params, json=payload) as response:
            data = await response.json(content_type=None)
            if response.status == 429:
                return "المساعد عليه ضغط حالياً أو انتهى الحد المجاني من Gemini. جرّب بعد شوي."
            if response.status >= 400:
                logger.warning("Gemini API failed status={} body={}", response.status, str(data)[:500])
                return "تعذر تشغيل مساعد الذكاء حالياً. تأكد من مفتاح Gemini أو جرّب لاحقاً."

    candidates = data.get("candidates") or []
    if not candidates:
        return "ما قدرت أجهز رد واضح حالياً. جرّب صياغة السؤال بطريقة أبسط."
    parts = (((candidates[0] or {}).get("content") or {}).get("parts") or [])
    text = "\n".join(str(part.get("text", "")).strip() for part in parts if part.get("text")).strip()
    return text or "ما قدرت أجهز رد واضح حالياً. جرّب مرة ثانية."


def _remember(telegram_id: int, user_text: str, assistant_text: str) -> None:
    items = _history.setdefault(telegram_id, [])
    items.append({"role": "user", "text": user_text.strip()[:1800]})
    items.append({"role": "assistant", "text": assistant_text.strip()[:1800]})
    max_items = settings.ai_max_history * 2
    if len(items) > max_items:
        del items[:-max_items]


def clear_ai_history(telegram_id: int) -> None:
    _history.pop(telegram_id, None)


async def build_ai_reply(user: User, telegram_id: int, question: str) -> tuple[str, int, int]:
    ok, message, remaining, limit = await can_use_ai(user, telegram_id)
    if not ok:
        return message, remaining, limit

    context = await _build_market_context(user, question)
    answer = await _call_gemini(telegram_id, question, context)
    used = await increment_ai_usage(user.id)
    remaining_after = max(0, limit - used)
    _remember(telegram_id, question, answer)
    return answer, remaining_after, limit


def safe_telegram_text(text: str) -> str:
    return html.escape(text or "").strip()[:3900]
