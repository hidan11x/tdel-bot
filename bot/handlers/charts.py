from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile

from services.chart_generator import generate_chart
from utils.validators import is_valid_symbol
from bot.keyboards.main import (
    market_menu, timeframe_menu, back_button, symbol_actions,
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


@router.callback_query(F.data == "chart_menu")
async def cb_chart_menu(callback: CallbackQuery):
    await callback.answer()
    _user_context[callback.from_user.id] = {"context": "chart"}
    text = "📉 اختر السوق لعرض الشارت:"
    await callback.message.edit_text(text, reply_markup=market_menu())


@router.callback_query(F.data.startswith("chart:"))
async def cb_chart_symbol(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) == 2:
        market_key = parts[1].lower()
        market = MARKET_MAP.get(market_key, market_key.upper())
        _user_context[callback.from_user.id] = {"context": "chart", "market": market}
        market_name = MARKET_DISPLAY.get(market, market)
        text = f"📉 أدخل رمز الأصل المالي للرسم البياني في {market_name}:\nمثال: 2222.SR للسعودي، AAPL للأمريكي، BTCUSDT للكريبتو"
        await callback.message.edit_text(text, reply_markup=back_button("chart_menu"))
    elif len(parts) == 3:
        symbol = parts[1].upper()
        market_key = parts[2].lower()
        market = MARKET_MAP.get(market_key, market_key.upper())
        kb = timeframe_menu(market_key, f"chart_gen:{symbol}:{market}")
        text = f"📉 اختر الإطار الزمني للرسم البياني لـ {symbol}:"
        await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data.startswith("chart_gen:"))
async def cb_chart_generate(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    symbol = parts[1]
    market = parts[2]
    timeframe = parts[3]

    await callback.message.edit_text(f"جاري إنشاء الرسم البياني لـ {symbol}... 📊")

    try:
        chart_path = generate_chart(symbol, market, timeframe)
    except Exception:
        chart_path = None

    if not chart_path:
        await callback.message.edit_text(
            f"❌ تعذر إنشاء الرسم البياني لـ {symbol}. تأكد من صحة الرمز أو حاول بإطار زمني مختلف.",
            reply_markup=back_button("chart_menu"),
        )
        return

    market_key = {"SAUDI": "saudi", "US": "us", "CRYPTO": "crypto"}.get(market, "us")
    kb = symbol_actions(symbol, market_key)

    caption = f"📉 {symbol} - {MARKET_DISPLAY.get(market, market)} ({timeframe})\nافتح الملف في المتصفح لرؤية الشارت التفاعلي"

    try:
        doc = FSInputFile(chart_path)
        await callback.message.delete()
        await callback.message.answer_document(doc, caption=caption, reply_markup=kb)
    except Exception:
        await callback.message.edit_text(
            f"{caption}\n\n⚠️ تعذر إرسال الشارت. حاول مرة أخرى.",
            reply_markup=back_button("chart_menu"),
        )


async def handle_chart_symbol_input(message: Message):
    telegram_id = message.from_user.id
    ctx = _user_context.get(telegram_id)
    if not ctx or ctx.get("context") != "chart":
        return

    market = ctx.get("market", "US")
    symbol = message.text.strip().upper()

    if not is_valid_symbol(symbol):
        await message.answer("❌ رمز الأصل غير صالح. أدخل رمزاً صحيحاً (مثال: 2222.SR، AAPL، BTCUSDT)")
        return

    market_key = {"SAUDI": "saudi", "US": "us", "CRYPTO": "crypto"}.get(market, "us")
    kb = timeframe_menu(market_key, f"chart_gen:{symbol}:{market}")

    text = f"📉 اختر الإطار الزمني للرسم البياني لـ {symbol}:"
    await message.answer(text, reply_markup=kb)

    _user_context[telegram_id] = {"context": "chart", "market": market, "symbol": symbol}
