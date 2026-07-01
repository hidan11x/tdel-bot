from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.symbols_service import get_all_symbols_by_market, get_popular_symbols
from services.scanner import scan_symbol
from bot.keyboards.main import back_button

router = Router()

MARKET_NAMES = {
    "SAUDI": "📈 السوق السعودي",
    "US": "🇺🇸 السوق الأمريكي",
    "CRYPTO": "₿ العملات الرقمية",
}


def _signal_emoji(score: float) -> str:
    if score is None:
        return "⚪"
    if score >= 4:
        return "🟢"
    if score >= 3:
        return "🟡"
    if score >= 2:
        return "🟠"
    return "🔴"


def _change_arrow(change: float) -> str:
    if change is None:
        return ""
    if change > 0:
        return f"▲{change:.1f}%"
    if change < 0:
        return f"▼{abs(change):.1f}%"
    return "—"


@router.callback_query(F.data == "heatmap")
async def cb_heatmap_menu(callback: CallbackQuery):
    await callback.answer()
    text = "🗺️ **الخريطة الحرارية**\n\nاختر السوق لعرض الخريطة الحرارية لجميع الرموز:"
    builder = InlineKeyboardBuilder()
    builder.button(text="📈 السوق السعودي", callback_data="heatmap:SAUDI")
    builder.button(text="🇺🇸 السوق الأمريكي", callback_data="heatmap:US")
    builder.button(text="₿ العملات الرقمية", callback_data="heatmap:CRYPTO")
    builder.button(text="↩️ رجوع", callback_data="main_menu")
    builder.adjust(2)
    await callback.message.edit_text(text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("heatmap:"))
async def cb_heatmap_market(callback: CallbackQuery):
    await callback.answer()
    market = callback.data.split(":")[1]
    market_name = MARKET_NAMES.get(market, market)
    await callback.message.edit_text(f"🗺️ جاري تحليل {market_name}...")
    symbols, _, _ = await get_all_symbols_by_market(market, 1)
    if not symbols:
        symbols, _, _ = await get_popular_symbols(market)
        if isinstance(symbols, tuple):
            symbols = symbols[0]
    results = []
    for s in symbols[:20]:
        result = await scan_symbol(s.symbol, market)
        if result:
            score = result.get("score", 0)
            change = result.get("change_pct", result.get("change", None))
            emoji = _signal_emoji(score)
            arrow = _change_arrow(change)
            price = result.get("price", "—")
            results.append(f"{emoji} {s.symbol}: {price} {arrow} ({score}/5)")
    if not results:
        await callback.message.edit_text(
            "❌ تعذر تحليل الخريطة الحرارية حالياً.", reply_markup=back_button("heatmap")
        )
        return
    text = f"🗺️ **الخريطة الحرارية - {market_name}**\n"
    text += "🟢 قوي | 🟡 متوسط | 🟠 ضعيف | 🔴 سلبي\n" + "─" * 20 + "\n"
    text += "\n".join(results)
    if len(symbols) > 20:
        text += f"\n\n... وعرض أول 20 رمزاً من {len(symbols)}"
    text += "\n\n*للحصول على قراءة كاملة، استخدم التصفح والفحص الفردي.*"
    await callback.message.edit_text(text[:4000], reply_markup=back_button("heatmap"))
