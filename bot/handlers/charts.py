from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile

from services.chart_generator import generate_chart
from services.search_engine import auto_detect_symbol
from utils.validators import is_valid_symbol
from bot.keyboards.main import (
    chart_market_menu, timeframe_menu, back_button, symbol_actions,
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
    text = (
        "📉 مركز الشارت\n\n"
        "اختر السوق، ثم اكتب الرمز واختر الفريم. الشارت يعرض الشموع، المتوسطات، الدعم، المقاومة، والحجم."
    )
    await callback.message.edit_text(text, reply_markup=chart_market_menu())


@router.callback_query(F.data.startswith("chart:"))
async def cb_chart_symbol(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) == 2:
        market_key = parts[1].lower()
        market = MARKET_MAP.get(market_key, market_key.upper())
        _user_context[callback.from_user.id] = {"context": "chart", "market": market}
        market_name = MARKET_DISPLAY.get(market, market)
        text = (
            f"📉 شارت {market_name}\n\n"
            "أرسل رمز الأصل المالي:\n"
            "• السعودي: 2222.SR\n"
            "• الأمريكي: AAPL\n"
            "• الكريبتو: BTCUSDT"
        )
        await callback.message.edit_text(text, reply_markup=back_button("chart_menu"))
    elif len(parts) == 3:
        symbol = parts[1].upper()
        market_key = parts[2].lower()
        market = MARKET_MAP.get(market_key, market_key.upper())
        kb = timeframe_menu(market_key, f"chart_gen:{symbol}:{market}")
        text = f"📉 اختر الفريم المناسب لـ {symbol}:"
        await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data.startswith("chart_gen:"))
async def cb_chart_generate(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    symbol = parts[1]
    market = parts[2]
    timeframe = parts[3]

    await callback.message.edit_text(f"📊 جاري تجهيز شارت {symbol} على فريم {timeframe}...")

    try:
        import asyncio
        from services.chart_generator import generate_chart
        from services.symbols_service import get_symbol_info
        from aiogram.types import BufferedInputFile
        from loguru import logger

        info = await get_symbol_info(symbol, market)
        name = info["name_ar"] if info else symbol
        chart_result = await asyncio.to_thread(
            generate_chart, symbol, market, timeframe, name
        )

        if chart_result:
            chart_bytes, chart_caption = chart_result
            market_key = {"SAUDI": "saudi", "US": "us", "CRYPTO": "crypto"}.get(market, "us")
            kb = symbol_actions(symbol, market_key)
            caption = (
                f"📉 {name} — {symbol}\n"
                f"السوق: {MARKET_DISPLAY.get(market, market)} | الفريم: {timeframe}\n"
                "الخطوط: EMA20 / EMA50 / الدعم / المقاومة"
            )
            photo = BufferedInputFile(chart_bytes, filename=f"{symbol}_{timeframe}.png")
            await callback.message.delete()
            await callback.message.answer_photo(photo, caption=caption, reply_markup=kb)
        else:
            await callback.message.edit_text(
                f"❌ تعذر إنشاء الرسم البياني لـ {symbol}. تأكد من صحة الرمز أو حاول بإطار زمني مختلف.",
                reply_markup=back_button("chart_menu"),
            )
    except Exception:
        await callback.message.edit_text(
            f"⚠️ تعذر إرسال شارت {symbol}. حاول مرة أخرى أو جرّب فريم مختلف.",
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
        detected = await auto_detect_symbol(message.text.strip())
        if detected:
            symbol = detected["symbol"]
            market = detected["market"]
            detected_name = detected.get("name_ar") or detected.get("name_en") or symbol
            await message.answer(f"🔎 تم التعرف على: {detected_name} ({symbol})")
        else:
            await message.answer("❌ ما قدرت أتعرف على الاسم أو الرمز. جرّب: الراجحي، ابل، بيتكوين، 2222.SR، AAPL")
            return

    market_key = {"SAUDI": "saudi", "US": "us", "CRYPTO": "crypto"}.get(market, "us")
    kb = timeframe_menu(market_key, f"chart_gen:{symbol}:{market}")

    text = f"📉 اختر الفريم المناسب لـ {symbol}:"
    await message.answer(text, reply_markup=kb)

    _user_context[telegram_id] = {"context": "chart", "market": market, "symbol": symbol}
