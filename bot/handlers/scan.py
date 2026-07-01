from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from sqlalchemy import select

from database import get_session
from models import User
from services.scanner import scan_symbol, log_scan_to_db
from services.signal_engine import build_signal, format_signal_message, format_signal_message_with_patterns
from services.patterns import detect_all_patterns, format_patterns
from services.subscriptions import can_scan, increment_scan
from services.chart_generator import generate_chart
from services.pdf_generator import generate_pdf_report
from utils.validators import is_valid_symbol
from bot.keyboards.main import (
    timeframe_menu, symbol_actions, back_button,
)

from . import _user_context

router = Router()

MARKET_MAP = {
    "saudi": "SAUDI",
    "us": "US",
    "crypto": "CRYPTO",
}
MARKET_DISPLAY = {
    "SAUDI": "السوق السعودي",
    "US": "السوق الأمريكي",
    "CRYPTO": "العملات الرقمية",
}
MARKET_KEY_MAP = {
    "SAUDI": "saudi",
    "US": "us",
    "CRYPTO": "crypto",
}


async def _get_user(telegram_id: int):
    async with get_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()


async def _perform_scan_and_report(
    callback: CallbackQuery,
    user_id: int,
    symbol: str,
    market: str,
    timeframe: str,
):
    can = await can_scan(user_id)
    if not can:
        text = "🔒 هذه الميزة متاحة للمشتركين فقط.\n\nتواصل مع الدعم للحصول على اشتراك أو تجربة:\n👤 @hidanx11"
        await callback.message.edit_text(text, reply_markup=back_button("main_menu"))
        return

    await callback.message.edit_text("جاري المسح الضوئي... 🔍")

    try:
        result = await scan_symbol(symbol, market, timeframe)
    except Exception:
        result = None

    if not result:
        err_text = f"❌ تعذر الحصول على بيانات كافية لـ {symbol}. تأكد من صحة الرمز وحاول مرة أخرى."
        await callback.message.edit_text(err_text, reply_markup=back_button("main_menu"))
        return

    await increment_scan(user_id)

    score_val = result.get("score")
    score_num = float(score_val.overall) if score_val else None
    price_val = result.get("current_price")
    await log_scan_to_db(user_id, symbol, market, timeframe, score_num, price_val)

    signal = build_signal(result)
    report = format_signal_message(signal)

    closes = result.get("closes")
    if closes:
        patterns = detect_all_patterns(closes)
        if patterns:
            patterns_text = format_patterns(patterns)
            report = format_signal_message_with_patterns(signal, patterns_text)

    market_key = MARKET_KEY_MAP.get(market, market.lower())
    kb = symbol_actions(symbol, market_key)
    await callback.message.edit_text(report, reply_markup=kb)

    try:
        from services.chart_generator import generate_chart
        from aiogram.types import BufferedInputFile
        chart_result = generate_chart(symbol, market, timeframe, name=result.get("name_ar"))
        if chart_result:
            chart_bytes, caption = chart_result
            photo = BufferedInputFile(chart_bytes, filename=f"{symbol}_{timeframe}.png")
            name = result.get("name_ar") or symbol
            caption_text = f"📉 {name} — {symbol} ({timeframe})"
            await callback.message.answer_photo(photo, caption=caption_text)
    except Exception:
        pass


@router.callback_query(F.data.startswith("timeframe_scan:"))
async def cb_timeframe_scan(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    symbol = parts[1]
    market = parts[2]
    timeframe = parts[3]

    telegram_id = callback.from_user.id
    user = await _get_user(telegram_id)
    if not user:
        await callback.message.edit_text("المستخدم غير موجود.")
        return

    await _perform_scan_and_report(callback, user.id, symbol, market, timeframe)


@router.callback_query(F.data == "scan_quick")
async def cb_scan_quick(callback: CallbackQuery):
    await callback.answer()
    from bot.keyboards.main import market_menu
    text = "اختر السوق للمسح السريع:"
    await callback.message.edit_text(text, reply_markup=market_menu())


@router.callback_query(F.data.startswith("rescan:"))
async def cb_rescan(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    symbol = parts[1]
    market_key = parts[2].lower()
    market = MARKET_MAP.get(market_key, parts[2].upper())

    kb = timeframe_menu(market_key, f"timeframe_scan:{symbol}:{market}")
    text = f"🔄 اختر الإطار الزمني لإعادة فحص {symbol}:"
    await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data.startswith("export_pdf:"))
async def cb_export_pdf(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    symbol = parts[1]
    market = parts[2]

    await callback.message.edit_text("📄 جاري إنشاء ملف PDF...")

    result = await scan_symbol(symbol, market)
    if not result:
        await callback.message.edit_text(
            f"❌ تعذر الحصول على بيانات لـ {symbol}.",
            reply_markup=back_button("main_menu"),
        )
        return

    filepath = generate_pdf_report(result)
    if not filepath:
        await callback.message.edit_text(
            "❌ فشل إنشاء ملف PDF.",
            reply_markup=back_button("main_menu"),
        )
        return

    doc = FSInputFile(filepath)
    await callback.message.answer_document(
        doc,
        caption=f"📄 {symbol} - التقرير الفني",
    )

    market_key = MARKET_KEY_MAP.get(market, market.lower())
    signal = build_signal(result)
    report = format_signal_message(signal)
    kb = symbol_actions(symbol, market_key)
    await callback.message.answer(report, reply_markup=kb)


async def handle_symbol_input(message: Message):
    telegram_id = message.from_user.id
    ctx = _user_context.get(telegram_id)
    if not ctx:
        return

    context_type = ctx.get("context")
    if context_type not in ("scan", "full_analysis"):
        return

    market = ctx.get("market", "US")
    raw_text = message.text.strip()
    symbol = raw_text.upper()

    if not is_valid_symbol(symbol):
        from services.search_engine import auto_detect_symbol
        detected = await auto_detect_symbol(raw_text)
        if detected:
            symbol = detected["symbol"]
            market = detected["market"]
        else:
            await message.answer(
                "❌ تعذر التعرف على الرمز. أدخل رمزاً صحيحاً أو اسم الشركة\nمثال: 2222.SR، AAPL، BTCUSDT، الراجحي، Apple"
            )
            return

    user = await _get_user(telegram_id)
    if not user:
        await message.answer("المستخدم غير موجود.")
        _user_context.pop(telegram_id, None)
        return

    can = await can_scan(user.id)
    if not can:
        await message.answer(
            "🔒 هذه الميزة متاحة للمشتركين فقط.\n\nتواصل مع الدعم للحصول على اشتراك أو تجربة:\n👤 @hidanx11",
            reply_markup=back_button("main_menu"),
        )
        _user_context.pop(telegram_id, None)
        return

    market_key = MARKET_KEY_MAP.get(market, market.lower())
    kb = timeframe_menu(market_key, f"timeframe_scan:{symbol}:{market}")

    _user_context[telegram_id] = {"context": "scan", "market": market, "symbol": symbol}
    await message.answer(f"📊 اختر الإطار الزمني لفحص {symbol}:", reply_markup=kb)
