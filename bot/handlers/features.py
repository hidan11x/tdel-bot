from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from loguru import logger

from database import get_session
from models import User
from services.price_tracker import (
    create_price_tracker, get_user_price_trackers, deactivate_price_tracker,
)
from services.market_overview import get_market_overview
from services.news import get_recent_news, format_news_items
from services.social import (
    create_share_link, increment_share_view, process_referral,
    export_scan_history_csv, get_user_scan_history,
)
from services.symbols_service import get_symbol_info
from bot.keyboards.main import back_button

from . import _user_context

router = Router()


async def _get_user(telegram_id: int):
    async with get_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()


@router.callback_query(F.data == "market_overview")
async def cb_market_overview(callback: CallbackQuery):
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="📈 السوق السعودي", callback_data="mkt_ov:SAUDI")
    builder.button(text="🇺🇸 السوق الأمريكي", callback_data="mkt_ov:US")
    builder.button(text="₿ العملات الرقمية", callback_data="mkt_ov:CRYPTO")
    builder.button(text="↩️ رجوع", callback_data="main_menu")
    builder.adjust(2, 1)
    await callback.message.edit_text("📊 اختر السوق للنظرة الشاملة:", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("mkt_ov:"))
async def cb_market_overview_detail(callback: CallbackQuery):
    await callback.answer()
    market = callback.data.split(":")[1]
    await callback.message.edit_text("📊 جاري تحضير النظرة الشاملة...")
    overview = await get_market_overview(market)
    if overview:
        await callback.message.edit_text(overview[:4000], reply_markup=back_button("main_menu"))
    else:
        await callback.message.edit_text("❌ تعذر تحضير النظرة الشاملة.", reply_markup=back_button("main_menu"))


@router.callback_query(F.data == "price_trackers")
async def cb_price_trackers(callback: CallbackQuery):
    await callback.answer()
    user = await _get_user(callback.from_user.id)
    if not user:
        await callback.message.edit_text("المستخدم غير موجود.", reply_markup=back_button("main_menu"))
        return

    trackers = await get_user_price_trackers(user.id)
    if not trackers:
        await callback.message.edit_text(
            "🎯 لا توجد تتبعات أسعار نشطة.\n\nاستخدم زر 🎯 تتبع السعر من نتيجة التحليل لإضافة تتبع جديد.",
            reply_markup=back_button("main_menu"),
        )
        return

    lines = ["🎯 تتبعات الأسعار النشطة:\n"]
    builder = InlineKeyboardBuilder()
    for i, t in enumerate(trackers[:10], 1):
        info = await get_symbol_info(t.symbol, t.market)
        name = info["name_ar"] if info else t.symbol
        arrow = "📈" if t.direction == "above" else "📉"
        status = "✅" if t.triggered else "⏳"
        lines.append(f"{i}. {status} {name} ({t.symbol})")
        lines.append(f"   {arrow} الهدف: {t.target_price:,.4f}")
        lines.append("")
        if not t.triggered:
            builder.button(text=f"❌ {t.symbol}", callback_data=f"ptrk_del:{t.id}")

    builder.button(text="↩️ رجوع", callback_data="main_menu")
    builder.adjust(2, 1)
    await callback.message.edit_text("\n".join(lines)[:4000], reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("ptrk:"))
async def cb_ptrk_create(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":", 2)
    symbol = parts[1]
    market = parts[2]

    _user_context[callback.from_user.id] = {
        "context": "price_tracker",
        "symbol": symbol,
        "market": market,
    }

    info = await get_symbol_info(symbol, market)
    name = info["name_ar"] if info else symbol

    text = (
        f"🎯 تتبع سعر {name} ({symbol})\n\n"
        f"اكتب السعر المستهدف ورغبتك:\n"
        f"مثال: 150.50 فوق\n"
        f"مثال: 140.00 تحت\n\n"
        f"البوت يبعت لك رسالة فورية لما السعر يوصل للهدف."
    )
    await callback.message.edit_text(text, reply_markup=back_button("main_menu"))


@router.callback_query(F.data.startswith("ptrk_del:"))
async def cb_ptrk_delete(callback: CallbackQuery):
    await callback.answer()
    tracker_id = int(callback.data.split(":")[1])
    ok = await deactivate_price_tracker(tracker_id)
    if ok:
        await callback.message.edit_text("✅ تم إيقاف التتبع.", reply_markup=back_button("price_trackers"))
    else:
        await callback.message.edit_text("❌ التتبع غير موجود.", reply_markup=back_button("price_trackers"))


@router.callback_query(F.data.startswith("share:"))
async def cb_share(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":", 2)
    symbol = parts[1]
    market = parts[2]

    user = await _get_user(callback.from_user.id)
    if not user:
        await callback.message.edit_text("المستخدم غير موجود.", reply_markup=back_button("main_menu"))
        return

    token = await create_share_link(user.id, symbol, market)
    if token:
        info = await get_symbol_info(symbol, market)
        name = info["name_ar"] if info else symbol
        bot_username = (await callback.bot.get_me()).username
        share_url = f"https://t.me/{bot_username}?start=share_{token}"

        text = (
            f"📤 مشاركة تحليل {name} ({symbol})\n\n"
            f"رابط المشاركة:\n{share_url}\n\n"
            f"شارك هذا الرابط مع أي شخص ليتمكن من رؤية التحليل."
        )
        await callback.message.edit_text(text, reply_markup=back_button("main_menu"))
    else:
        await callback.message.edit_text("❌ تعذر إنشاء رابط المشاركة.", reply_markup=back_button("main_menu"))


@router.callback_query(F.data == "share_menu")
async def cb_share_menu(callback: CallbackQuery):
    await callback.answer()
    text = (
        "📤 مشاركة التحليل\n\n"
        "للمشاركة، قم بفحص أي رمز ثم اضغط زر '📤 مشاركة' من القائمة.\n"
        "البوت يعطيك رابط تقدر ترسله لأي شخص."
    )
    await callback.message.edit_text(text, reply_markup=back_button("main_menu"))


@router.callback_query(F.data == "export_history")
async def cb_export_history(callback: CallbackQuery):
    await callback.answer()
    user = await _get_user(callback.from_user.id)
    if not user:
        await callback.message.edit_text("المستخدم غير موجود.", reply_markup=back_button("main_menu"))
        return

    await callback.message.edit_text("📥 جاري تصدير سجلك...")

    csv_data = await export_scan_history_csv(user.id)
    if not csv_data:
        await callback.message.edit_text("❌ لا يوجد سجل فحوصات.", reply_markup=back_button("main_menu"))
        return

    import io
    from aiogram.types import BufferedInputFile

    buf = io.BytesIO(csv_data.encode("utf-8-sig"))
    buf.seek(0)
    doc = BufferedInputFile(buf.read(), filename=f"scan_history_{user.id}.csv")
    await callback.message.answer_document(doc, caption="📥 سجل الفحوصات (CSV)")
    await callback.message.edit_text("✅ تم تصدير السجل.", reply_markup=back_button("main_menu"))


@router.callback_query(F.data == "referral_menu")
async def cb_referral_menu(callback: CallbackQuery):
    await callback.answer()
    user = await _get_user(callback.from_user.id)
    if not user:
        await callback.message.edit_text("المستخدم غير موجود.", reply_markup=back_button("main_menu"))
        return

    bot_username = (await callback.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start=ref{user.telegram_id}"

    text = (
        f"🎁 دعوة صديق\n\n"
        f"رابط الدعوة الخاص بك:\n{ref_link}\n\n"
        f"📊 إحالاتك: {user.referrals_count or 0}\n"
        f"🎁 أيام مكافآت: {user.referral_days or 0} يوم\n\n"
        f"كل صديق يدخل عبر رابطك تحصل على 30 يوم اشتراك مجاني!"
    )
    await callback.message.edit_text(text, reply_markup=back_button("main_menu"))


@router.callback_query(F.data == "language_toggle")
async def cb_language_toggle(callback: CallbackQuery):
    await callback.answer()
    user = await _get_user(callback.from_user.id)
    if not user:
        await callback.message.edit_text("المستخدم غير موجود.", reply_markup=back_button("main_menu"))
        return

    new_lang = "en" if user.language == "ar" else "ar"
    async with get_session() as session:
        u = await session.get(User, user.id)
        if u:
            u.language = new_lang
            await session.commit()

    lang_name = "English" if new_lang == "en" else "العربية"
    await callback.message.edit_text(
        f"🌐 تم تبديل اللغة إلى {lang_name}",
        reply_markup=back_button("main_menu"),
    )


@router.callback_query(F.data == "news_menu")
async def cb_news_menu(callback: CallbackQuery):
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="🇸🇦 أخبار السعودية", callback_data="news:SAUDI")
    builder.button(text="🇺🇸 أخبار أمريكا", callback_data="news:US")
    builder.button(text="₿ أخبار الكريبتو", callback_data="news:CRYPTO")
    builder.button(text="📰 كل الأخبار", callback_data="news:ALL")
    builder.button(text="↩️ رجوع", callback_data="main_menu")
    builder.adjust(2, 2, 1)
    await callback.message.edit_text("📰 اختر السوق للأخبار:", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("news:"))
async def cb_news_detail(callback: CallbackQuery):
    await callback.answer()
    market = callback.data.split(":")[1]

    await callback.message.edit_text("📰 جاري جلب الأخبار...")

    if market == "ALL":
        items = await get_recent_news(limit=10)
        label = ""
    else:
        items = await get_recent_news(market=market, limit=8)
        label = {"SAUDI": "السعودي", "US": "الأمريكي", "CRYPTO": "الرقمية"}.get(market, market)

    if not items:
        await callback.message.edit_text("📰 لا توجد أخبار متاحة حالياً.", reply_markup=back_button("news_menu"))
        return

    text = format_news_items(items, label)
    await callback.message.edit_text(text[:4000], reply_markup=back_button("news_menu"))
