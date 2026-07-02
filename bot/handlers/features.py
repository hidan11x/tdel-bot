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
    export_scan_history_csv, get_user_scan_history, REFERRAL_REWARD_HOURS,
)
from services.symbols_service import get_symbol_info
from services.feature_access import PREDICTION_FEATURE, has_feature_access
from services.private_prediction import build_private_prediction
from bot.keyboards.main import back_button
from config import settings

from . import _user_context

router = Router()


async def _get_user(telegram_id: int):
    async with get_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()


async def _is_vip_user(telegram_id: int) -> bool:
    if telegram_id in settings.admin_ids:
        return True
    user = await _get_user(telegram_id)
    return bool(user and user.plan in ("vip", "lifetime"))


async def _can_use_prediction(telegram_id: int) -> bool:
    return await has_feature_access(telegram_id, PREDICTION_FEATURE)


@router.callback_query(F.data == "private_prediction")
async def cb_private_prediction(callback: CallbackQuery):
    await callback.answer()
    if not await _can_use_prediction(callback.from_user.id):
        await callback.message.edit_text("الأمر غير متاح لحسابك.", reply_markup=back_button("menu:analysis"))
        return
    _user_context[callback.from_user.id] = {"context": "private_prediction"}
    await callback.message.edit_text(
        "🔮 الإشارات الخاصة\n\nاكتب اسم أو رمز الأصل المالي:\nمثال: الراجحي، AAPL، BTCUSDT",
        reply_markup=back_button("menu:analysis"),
    )


async def handle_private_prediction_input(message: Message):
    if not await _can_use_prediction(message.from_user.id):
        _user_context.pop(message.from_user.id, None)
        await message.answer("الأمر غير متاح لحسابك.")
        return

    query = message.text.strip()
    if len(query) < 2:
        await message.answer("اكتب اسم أو رمز صحيح.")
        return

    wait_msg = await message.answer(f"🔮 جاري تجهيز الإشارة الخاصة لـ {query}...")
    report = await build_private_prediction(query)
    _user_context.pop(message.from_user.id, None)
    if not report:
        await wait_msg.edit_text(
            "تعذر تجهيز الإشارة. تأكد من الاسم أو الرمز وحاول مرة ثانية.",
            reply_markup=back_button("menu:analysis"),
        )
        return
    await wait_msg.edit_text(report[:4000], reply_markup=back_button("menu:analysis"))


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


@router.callback_query(F.data == "opportunity_radar")
async def cb_opportunity_radar(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("🚀 جاري تشغيل رادار الفرص...")

    try:
        from services.opportunities import (
            build_opportunity_keyboard,
            flatten_radar,
            format_radar,
            get_radar_opportunities,
        )

        vip = await _is_vip_user(callback.from_user.id)
        radar = await get_radar_opportunities(vip=vip)
        items = flatten_radar(radar)
        text = format_radar(radar, vip=vip)
        await callback.message.edit_text(
            text[:4000],
            reply_markup=build_opportunity_keyboard(items, back_to="menu:reports"),
        )
    except Exception:
        logger.exception("opportunity_radar failed")
        await callback.message.edit_text(
            "❌ تعذر تشغيل رادار الفرص حالياً.",
            reply_markup=back_button("menu:reports"),
        )


@router.callback_query(F.data == "opportunity_day")
async def cb_opportunity_day(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("🔥 جاري اختيار فرصة اليوم...")

    try:
        from services.opportunities import (
            build_opportunity_keyboard,
            format_opportunity_of_day,
            get_opportunity_of_day,
        )

        result = await get_opportunity_of_day()
        if not result:
            await callback.message.edit_text(
                "❌ لا توجد فرصة واضحة حالياً.",
                reply_markup=back_button("menu:reports"),
            )
            return

        text = format_opportunity_of_day(result)
        await callback.message.edit_text(
            text[:4000],
            reply_markup=build_opportunity_keyboard([result], back_to="menu:reports"),
        )
    except Exception:
        logger.exception("opportunity_day failed")
        await callback.message.edit_text(
            "❌ تعذر اختيار فرصة اليوم حالياً.",
            reply_markup=back_button("menu:reports"),
        )


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
    reward_hours = int(user.referral_days or 0)
    reward_label = "ساعتين" if REFERRAL_REWARD_HOURS == 2 else f"{REFERRAL_REWARD_HOURS} ساعة"

    text = (
        f"🎁 دعوة صديق\n\n"
        f"رابط الدعوة الخاص بك:\n{ref_link}\n\n"
        f"📊 إحالاتك: {user.referrals_count or 0}\n"
        f"🎁 ساعات مكافآت: {reward_hours} ساعة\n\n"
        f"كل صديق يدخل عبر رابطك تحصل على {reward_label} اشتراك مجاني!"
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


@router.callback_query(F.data == "mtf_scan")
async def cb_mtf_scan(callback: CallbackQuery):
    await callback.answer()
    _user_context[callback.from_user.id] = {"context": "mtf_scan"}
    text = (
        "🔄 تحليل متعدد الفريمات\n\n"
        "اكتب اسم أو رمز الأصل (مثال: الراجحي، أبل، بيتكوين، AAPL، 2222.SR، BTCUSDT):\n"
        "البوت يفحص 3 فريمات (15min + 1h + 1d) ويعطيك تحليل شامل."
    )
    await callback.message.edit_text(text, reply_markup=back_button("main_menu"))


@router.callback_query(F.data == "vip_signals")
async def cb_vip_signals(callback: CallbackQuery):
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="🇸🇦 فرص السعودي", callback_data="vip_market:SAUDI")
    builder.button(text="🇺🇸 فرص الأمريكي", callback_data="vip_market:US")
    builder.button(text="₿ فرص الكريبتو", callback_data="vip_market:CRYPTO")
    builder.button(text="🌍 أفضل الفرص", callback_data="vip_market:ALL")
    builder.button(text="🔎 تحليل VIP لرمز", callback_data="vip_symbol")
    builder.button(text="↩️ رجوع", callback_data="menu:analysis")
    builder.adjust(2, 2, 1, 1)
    text = (
        "🚀 مركز إشارات VIP\n\n"
        "اختر سوقاً لعرض أقوى الفرص الحالية، أو اختر تحليل VIP لرمز واكتب اسم السهم أو رمزه.\n"
        "مثال: الراجحي، أبل، بيتكوين، 1120.SR، AAPL"
    )
    await callback.message.edit_text(text, reply_markup=builder.as_markup())


@router.callback_query(F.data == "vip_symbol")
async def cb_vip_symbol(callback: CallbackQuery):
    await callback.answer()
    _user_context[callback.from_user.id] = {"context": "vip_symbol"}
    text = (
        "🔎 تحليل VIP لرمز\n\n"
        "اكتب اسم أو رمز الأصل المالي:\n"
        "• الراجحي\n"
        "• أبل\n"
        "• بيتكوين\n"
        "• 1120.SR / AAPL / BTCUSDT"
    )
    await callback.message.edit_text(text, reply_markup=back_button("vip_signals"))


@router.callback_query(F.data.startswith("vip_market:"))
async def cb_vip_market(callback: CallbackQuery):
    await callback.answer()
    market = callback.data.split(":", 1)[1]
    await callback.message.edit_text("🚀 جاري البحث عن أقوى إشارات VIP...")

    try:
        from services.scanner import get_top_movers
        from services.signal_engine import build_signal

        markets = ["SAUDI", "US", "CRYPTO"] if market == "ALL" else [market]
        results = []
        for market_key in markets:
            market_results = await get_top_movers(market_key, count=3 if market == "ALL" else 5)
            results.extend(market_results)

        results.sort(key=lambda r: float(r["score"].overall) if r.get("score") else 0, reverse=True)
        if not results:
            await callback.message.edit_text("❌ تعذر الحصول على إشارات الآن.", reply_markup=back_button("vip_signals"))
            return

        market_label = {"SAUDI": "السعودي", "US": "الأمريكي", "CRYPTO": "الكريبتو", "ALL": "كل الأسواق"}.get(market, market)
        lines = [f"🚀 إشارات VIP — {market_label}\n"]
        for i, r in enumerate(results[:5], 1):
            signal = build_signal(r)
            name = signal.name_ar if signal.name_ar != signal.symbol else signal.symbol
            trend_emoji = {"uptrend": "🟢", "downtrend": "🔴", "sideways": "🟡"}.get(signal.trend, "📊")
            lines.append(
                f"{i}. {trend_emoji} {name} ({signal.symbol})\n"
                f"   ⭐ {signal.score:.0f}/100 | 🎯 ثقة {signal.confidence}/100\n"
                f"   💰 {signal.current_price:,.4f} | {'+' if signal.change_percent >= 0 else ''}{signal.change_percent:.2f}%\n"
            )

        lines.append("\nهذا تحليل آلي تعليمي وليس توصية مالية.")
        await callback.message.edit_text("\n".join(lines)[:4000], reply_markup=back_button("vip_signals"))
    except Exception:
        await callback.message.edit_text("❌ تعذر الحصول على إشارات.", reply_markup=back_button("vip_signals"))


@router.callback_query(F.data == "news:ALL")
async def cb_news_all(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("📰 جاري جلب الأخبار...")

    from services.news import get_recent_news, format_news_items
    items = await get_recent_news(limit=10)

    if not items:
        await callback.message.edit_text("📰 لا توجد أخبار متاحة حالياً.", reply_markup=back_button("news_menu"))
        return

    text = format_news_items(items)
    await callback.message.edit_text(text[:4000], reply_markup=back_button("news_menu"))


@router.callback_query(F.data == "terms")
async def cb_terms(callback: CallbackQuery):
    await callback.answer()
    from services.compliance import get_terms
    text = get_terms()
    await callback.message.edit_text(text[:4000], reply_markup=back_button("main_menu"))


@router.callback_query(F.data == "screener_menu")
async def cb_screener_menu(callback: CallbackQuery):
    await callback.answer()
    from services.screener import get_screener_list
    screeners = get_screener_list()

    builder = InlineKeyboardBuilder()
    for s in screeners:
        builder.button(text=s["name_ar"], callback_data=f"scr:{s['id']}")
    builder.button(text="↩️ رجوع", callback_data="main_menu")
    builder.adjust(2)
    await callback.message.edit_text("🔍 اختر نوع الفحص:", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("scr:"))
async def cb_screener_run(callback: CallbackQuery):
    await callback.answer()
    screener_id = callback.data.split(":")[1]

    builder = InlineKeyboardBuilder()
    builder.button(text="📈 السعودي", callback_data=f"scrrun:SAUDI:{screener_id}")
    builder.button(text="🇺🇸 الأمريكي", callback_data=f"scrrun:US:{screener_id}")
    builder.button(text="₿ الكريبتو", callback_data=f"scrrun:CRYPTO:{screener_id}")
    builder.button(text="↩️ رجوع", callback_data="screener_menu")
    builder.adjust(2, 1)
    await callback.message.edit_text("اختر السوق:", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("scrrun:"))
async def cb_screener_execute(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    market = parts[1]
    screener_id = parts[2]

    await callback.message.edit_text("🔍 جاري فحص السوق...")

    from services.screener import run_screener
    result = await run_screener(market, screener_id)

    if result:
        await callback.message.edit_text(result[:4000], reply_markup=back_button("screener_menu"))
    else:
        await callback.message.edit_text("❌ تعذر الفحص.", reply_markup=back_button("screener_menu"))


@router.callback_query(F.data == "fib_menu")
async def cb_fib_menu(callback: CallbackQuery):
    await callback.answer()
    _user_context[callback.from_user.id] = {"context": "fib_scan"}
    text = (
        "📐 مستويات فيبوناتشي\n\n"
        "اكتب اسم أو رمز الأصل (مثال: الراجحي، أبل، بيتكوين، AAPL، 2222.SR، BTCUSDT):\n"
        "البوت يحسب مستويات فيبوناتشي تلقائياً."
    )
    await callback.message.edit_text(text, reply_markup=back_button("main_menu"))


@router.callback_query(F.data == "risk_calc")
async def cb_risk_calc(callback: CallbackQuery):
    await callback.answer()
    _user_context[callback.from_user.id] = {"context": "risk_calc"}
    text = (
        "📊 حاسبة المخاطر\n\n"
        "اكتب البيانات بهذا الشكل:\n\n"
        "رأس_المال نسبة_المخاطرة سعر_الدخول وقف_الخسارة\n\n"
        "مثال: 10000 2 150 145\n"
        "(10000 ريال، 2% مخاطرة، دخول 150، وقف 145)\n\n"
        "أو مع الهدف:\n"
        "10000 2 150 145 160"
    )
    await callback.message.edit_text(text, reply_markup=back_button("main_menu"))


@router.callback_query(F.data == "fear_greed")
async def cb_fear_greed(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("😱 جاري جلب مؤشر الخوف والطمع...")

    from services.fear_greed import get_fear_greed_index, format_fear_greed
    data = await get_fear_greed_index()

    if data:
        text = format_fear_greed(data)
        await callback.message.edit_text(text, reply_markup=back_button("main_menu"))
    else:
        await callback.message.edit_text("❌ تعذر جلب المؤشر.", reply_markup=back_button("main_menu"))


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


@router.callback_query(F.data == "sector_performance")
async def cb_sector_performance(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("📊 جاري تحليل أداء القطاعات...")

    try:
        from services.scanner import scan_symbol, TOP_SYMBOLS
        from services.symbols_service import get_symbol_info
        import asyncio

        sector_data = {}

        for market in ["SAUDI"]:
            symbols = TOP_SYMBOLS.get(market, [])
            for sym in symbols:
                try:
                    r = await scan_symbol(sym, market, "1d")
                    if r:
                        info = await get_symbol_info(sym, market)
                        sector = info.get("sector") if info else None
                        if sector:
                            if sector not in sector_data:
                                sector_data[sector] = {"up": 0, "down": 0, "total": 0, "changes": []}
                            sector_data[sector]["total"] += 1
                            change = r.get("change_percent", 0)
                            sector_data[sector]["changes"].append(change)
                            if change > 0:
                                sector_data[sector]["up"] += 1
                            else:
                                sector_data[sector]["down"] += 1
                except Exception:
                    continue

        if not sector_data:
            await callback.message.edit_text("❌ تعذر تحليل القطاعات.", reply_markup=back_button("main_menu"))
            return

        lines = ["📊 أداء القطاعات — السوق السعودي\n"]

        sorted_sectors = sorted(sector_data.items(), key=lambda x: sum(x[1]["changes"]) / len(x[1]["changes"]) if x[1]["changes"] else 0, reverse=True)

        for sector, data in sorted_sectors:
            avg_change = sum(data["changes"]) / len(data["changes"]) if data["changes"] else 0
            up_pct = (data["up"] / data["total"] * 100) if data["total"] > 0 else 0
            emoji = "🟢" if avg_change > 0.5 else ("🔴" if avg_change < -0.5 else "🟡")
            lines.append(f"{emoji} {sector}: {avg_change:+.2f}% ({data['up']}▲ {data['down']}▼)")

        lines.append("\n⚠️ تحليل تعليمي وليس توصية مالية.")
        await callback.message.edit_text("\n".join(lines)[:4000], reply_markup=back_button("main_menu"))

    except Exception:
        await callback.message.edit_text("❌ تعذر تحليل القطاعات.", reply_markup=back_button("main_menu"))


@router.callback_query(F.data.startswith("rate_scan:"))
async def cb_rate_scan(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    rating = parts[1]
    symbol = parts[2] if len(parts) > 2 else ""

    if rating == "up":
        await callback.answer("👍 شكراً للتقييم!", show_alert=False)
    else:
        await callback.answer("👎 شكراً للملاحظة!", show_alert=False)


@router.callback_query(F.data == "my_news_alerts")
async def cb_my_news_alerts(callback: CallbackQuery):
    await callback.answer()
    from database import get_session
    from models import Watchlist

    user = await _get_user(callback.from_user.id)
    if not user:
        await callback.message.edit_text("المستخدم غير موجود.", reply_markup=back_button("main_menu"))
        return

    async with get_session() as session:
        stmt = select(Watchlist).where(Watchlist.user_id == user.id)
        result = await session.execute(stmt)
        items = result.scalars().all()

    if not items:
        await callback.message.edit_text(
            "📰 لا توجد رموز في قائمة متابعتك.\n\nأضف رموز لقائمة المتابعة لتصلك أخبارها.",
            reply_markup=back_button("main_menu"),
        )
        return

    from services.news import get_recent_news, format_news_items
    all_news = []
    for item in items:
        news = await get_recent_news(limit=3)
        all_news.extend(news)

    if not all_news:
        await callback.message.edit_text("📰 لا توجد أخبار متاحة حالياً.", reply_markup=back_button("main_menu"))
        return

    text = format_news_items(all_news[:8], "لرموزك المتابعة")
    await callback.message.edit_text(text[:4000], reply_markup=back_button("main_menu"))


@router.callback_query(F.data == "my_stats")
async def cb_my_stats(callback: CallbackQuery):
    await callback.answer()
    user = await _get_user(callback.from_user.id)
    if not user:
        await callback.message.edit_text("المستخدم غير موجود.", reply_markup=back_button("main_menu"))
        return

    from services.user_stats import get_user_statistics
    stats = await get_user_statistics(user.id)
    if stats:
        await callback.message.edit_text(stats[:4000], reply_markup=back_button("main_menu"))
    else:
        await callback.message.edit_text("❌ تعذر جلب إحصائياتك.", reply_markup=back_button("main_menu"))


@router.callback_query(F.data == "dividends")
async def cb_dividends(callback: CallbackQuery):
    await callback.answer()
    from services.user_stats import get_dividend_schedule
    text = await get_dividend_schedule()
    await callback.message.edit_text(text[:4000], reply_markup=back_button("main_menu"))


@router.callback_query(F.data == "rs_compare")
async def cb_rs_compare(callback: CallbackQuery):
    await callback.answer()
    _user_context[callback.from_user.id] = {"context": "rs_compare"}
    text = (
        "💪 مقارنة القوة النسبية\n\n"
        "اكتب رمزين للمقارنة:\n\n"
        "مثال: 2222.SR 2010.SR\n"
        "(أرامكو vs سابك)\n\n"
        "أو: AAPL MSFT"
    )
    await callback.message.edit_text(text, reply_markup=back_button("main_menu"))
