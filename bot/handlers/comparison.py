from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import get_session
from models import Symbol
from services.symbols_service import get_symbol_by_id, search_symbols
from services.scanner import scan_symbol
from utils.formatter import format_technical_report
from bot.keyboards.main import back_button

from . import _user_context

router = Router()


@router.callback_query(F.data == "compare")
async def cb_compare_start(callback: CallbackQuery):
    await callback.answer()
    _user_context[callback.from_user.id] = {"context": "compare_first"}
    text = "📊 **المقارنة الفنية**\n\nأدخل اسم أو رمز الأصل الأول:\nمثال: الراجحي، أبل، بيتكوين، 1120.SR"
    await callback.message.edit_text(text, reply_markup=back_button("main_menu"))


@router.callback_query(F.data.startswith("compare_add:"))
async def cb_compare_add(callback: CallbackQuery):
    await callback.answer()
    symbol = callback.data.split(":", 1)[1]
    _user_context[callback.from_user.id] = {"context": "compare_second", "compare_first": symbol}
    text = f"📊 **المقارنة الفنية**\n\nالأصل الأول: {symbol}\nأدخل اسم أو رمز الأصل الثاني:"
    await callback.message.edit_text(text, reply_markup=back_button("main_menu"))


async def _do_compare(message: Message, symbol1: str, symbol2: str, market1: str = None, market2: str = None):
    await message.answer("🔄 جاري تحليل الأصول للمقارنة...")
    r1 = await scan_symbol(symbol1, market1 or "SAUDI")
    r2 = await scan_symbol(symbol2, market2 or market1 or "SAUDI")
    if not r1 and not r2:
        await message.answer("❌ تعذر تحليل كلا الأصلين.", reply_markup=back_button("main_menu"))
        return
    lines = ["📊 **المقارنة الفنية**\n", f"الأصل الأول: {symbol1} | الأصل الثاني: {symbol2}\n"]
    if r1 and r2:
        score1 = r1.get("score", 0)
        score2 = r2.get("score", 0)
        sig1 = r1.get("signal", "محايد")
        sig2 = r2.get("signal", "محايد")
        lines.append(f"**{symbol1}** | **{symbol2}**")
        lines.append(f"النقاط: {score1}/5 | النقاط: {score2}/5")
        lines.append(f"الإشارة: {sig1} | الإشارة: {sig2}")
        lines.append(f"السعر: {r1.get('price', '—')} | السعر: {r2.get('price', '—')}")
        rsi1 = r1.get("indicators", {}).get("RSI", "—")
        rsi2 = r2.get("indicators", {}).get("RSI", "—")
        lines.append(f"RSI: {rsi1} | RSI: {rsi2}")
        macd1 = r1.get("indicators", {}).get("MACD", {})
        macd2 = r2.get("indicators", {}).get("MACD", {})
        lines.append(f"MACD: {macd1.get('signal', '—')} | MACD: {macd2.get('signal', '—')}")
        lines.append(f"\n*ملاحظة: المقارنة لأغراض تعليمية، لا توصية بالشراء أو البيع.*")
    else:
        if r1:
            lines.append(f"✅ تم تحليل {symbol1} فقط.")
            lines.append(format_technical_report(r1))
        if r2:
            lines.append(f"✅ تم تحليل {symbol2} فقط.")
            lines.append(format_technical_report(r2))
    await message.answer("\n".join(lines)[:4000], reply_markup=back_button("main_menu"))


async def handle_compare_input(message: Message):
    ctx = _user_context.get(message.from_user.id, {})
    context_type = ctx.get("context")
    raw_input = message.text.strip()
    from services.search_engine import auto_detect_symbol
    detected = await auto_detect_symbol(raw_input)
    if detected:
        symbol_input = detected["symbol"]
        market_input = detected["market"]
        name = detected.get("name_ar") or detected.get("name_en") or symbol_input
    else:
        symbol_input = raw_input.upper()
        market_input = "SAUDI" if symbol_input.endswith(".SR") else ("CRYPTO" if symbol_input.endswith("USDT") else "US")
        name = symbol_input

    if context_type == "compare_first":
        _user_context[message.from_user.id] = {
            "context": "compare_second",
            "compare_first": symbol_input,
            "compare_first_market": market_input,
        }
        await message.answer(f"📊 الأصل الأول: {name} ({symbol_input})\nأدخل اسم أو رمز الأصل الثاني:", reply_markup=back_button("main_menu"))
    elif context_type == "compare_second":
        symbol1 = ctx.get("compare_first", "")
        market1 = ctx.get("compare_first_market", "SAUDI")
        symbol2 = symbol_input
        _user_context.pop(message.from_user.id, None)
        await _do_compare(message, symbol1, symbol2, market1, market_input)
