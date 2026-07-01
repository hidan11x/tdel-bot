from aiogram import Router, F
from aiogram.types import CallbackQuery

from services.scanner import get_top_movers, get_highest_volume
from utils.formatter import format_price, format_change
from bot.keyboards.main import back_button
from bot.keyboards.main import InlineKeyboardBuilder

router = Router()


@router.callback_query(F.data == "top_readings")
async def cb_top_readings(callback: CallbackQuery):
    await callback.answer()
    text = "🏆 أقوى القراءات الفنية:\n\nاختر السوق لعرض أفضل القراءات:"

    builder = InlineKeyboardBuilder()
    builder.button(text="🇸🇦 السوق السعودي", callback_data="top:saudi")
    builder.button(text="🇺🇸 السوق الأمريكي", callback_data="top:us")
    builder.button(text="₿ العملات الرقمية", callback_data="top:crypto")
    builder.button(text="↩️ رجوع", callback_data="main_menu")
    builder.adjust(2, 2)

    await callback.message.edit_text(text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("top:"))
async def cb_top_market(callback: CallbackQuery):
    await callback.answer()
    market_key = callback.data.split(":")[1].upper()
    market_lower = {"SAUDI": "saudi", "US": "us", "CRYPTO": "crypto"}
    market_display = {"SAUDI": "السوق السعودي", "US": "السوق الأمريكي", "CRYPTO": "العملات الرقمية"}

    display_name = market_display.get(market_key, market_key)
    await callback.message.edit_text(f"🏆 جاري تحليل أفضل القراءات في {display_name}... 🔍")

    results = await get_top_movers(market_key, count=10)

    if not results:
        await callback.message.edit_text(
            f"❌ تعذر الحصول على قراءات لـ {display_name} حالياً. حاول مرة أخرى لاحقاً.",
            reply_markup=back_button("top_readings"),
        )
        return

    top = results[:5]
    lines = [f"🏆 أفضل 5 قراءات فنية في {display_name}:\n"]
    for i, r in enumerate(top, 1):
        sym = r["symbol"]
        price = format_price(r.get("current_price"))
        change = format_change(r.get("change_percent"))
        score = r.get("score")
        score_val = f"{score.overall:.0f}" if score else "N/A"
        rating = r.get("rating", "")
        trend_icon = {"uptrend": "📈", "downtrend": "📉", "sideways": "↔️"}.get(r.get("trend", ""), "")
        lines.append(f"{i}. {sym} {trend_icon}")
        lines.append(f"   {price} | {change}")
        lines.append(f"   التقييم: {score_val}/100 | {rating}")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━\n")
    lines.append("📊 ملخص حركة السوق:\n")

    gainers = [r for r in results if (r.get("change_percent") or 0) > 0]
    losers = [r for r in results if (r.get("change_percent") or 0) < 0]
    by_volume = await get_highest_volume(market_key, count=1)

    if gainers:
        top_gainer = max(gainers, key=lambda r: r.get("change_percent", 0))
        lines.append(f"📈 الأكثر ارتفاعاً: {top_gainer['symbol']} ({format_change(top_gainer.get('change_percent', 0))})")

    if losers:
        top_loser = min(losers, key=lambda r: r.get("change_percent", 0))
        lines.append(f"📉 الأكثر انخفاضاً: {top_loser['symbol']} ({format_change(top_loser.get('change_percent', 0))})")

    if by_volume:
        top_vol = by_volume[0]
        vol_val = top_vol.get("indicators", {}).get("volume", 0)
        vol_str = f"{vol_val / 1_000_000:.2f}M" if vol_val >= 1_000_000 else f"{vol_val / 1_000:.1f}K" if vol_val >= 1_000 else f"{vol_val:.0f}"
        lines.append(f"📊 الأعلى فوليوم: {top_vol['symbol']} ({vol_str})")

    text = "\n".join(lines)

    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 تحديث", callback_data=f"top:{market_lower.get(market_key, 'saudi')}")
    builder.button(text="↩️ رجوع", callback_data="top_readings")
    builder.adjust(2)

    await callback.message.edit_text(text, reply_markup=builder.as_markup())
