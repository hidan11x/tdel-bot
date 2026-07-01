from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from database import get_session
from models import User, MarketSettings
from bot.keyboards.main import (
    main_menu, market_menu, scan_type_menu, profile_menu, back_button, daily_report_menu,
    symbol_browser_menu, sectors_menu, symbol_list_menu, symbol_detail_menu,
)
from utils.formatter import format_profile, format_technical_report
from services.subscriptions import get_plan_limits
from services.scanner import scan_symbol, TOP_SYMBOLS
from services.signal_engine import build_signal, format_signal_message
from services.symbols_service import (
    get_sectors, get_popular_symbols, get_symbols_by_sector,
    get_all_symbols_by_market, search_symbols, get_symbol_by_id, get_sectors_count,
)
from services.search_engine import smart_search, format_search_results, build_search_keyboard, auto_detect_symbol

from . import _user_context
from .scan import handle_symbol_input
from .watchlist import handle_watchlist_symbol_input
from .alerts import handle_alert_value_input
from .charts import handle_chart_symbol_input
from .subscriptions import handle_activation_code

router = Router()

MARKET_MAP = {
    "saudi": "SAUDI",
    "us": "US",
    "crypto": "CRYPTO",
}
MARKET_DISPLAY = {
    "saudi": "السوق السعودي",
    "us": "السوق الأمريكي",
    "crypto": "العملات الرقمية",
}

MARKET_NAMES_REVERSE = {v: k for k, v in MARKET_MAP.items()}


async def _get_user(telegram_id: int):
    async with get_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()


@router.message(Command("start"))
async def cmd_start(message: Message, command=None):
    telegram_id = message.from_user.id

    ref_code = None
    share_token = None
    if command and command.args:
        arg = command.args.strip()
        if arg.startswith("ref"):
            ref_code = arg
        elif arg.startswith("share_"):
            share_token = arg.replace("share_", "")

    async with get_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                telegram_id=telegram_id,
                username=message.from_user.username,
                first_name=message.from_user.first_name or message.from_user.username or str(telegram_id),
                language_code=message.from_user.language_code or "ar",
                referral_code=f"ref{telegram_id}",
            )
            session.add(user)
            await session.commit()

            if ref_code:
                from services.social import process_referral
                await process_referral(ref_code, telegram_id)

    if share_token:
        from services.social import increment_share_view
        share_data = await increment_share_view(share_token)
        if share_data:
            from services.scanner import scan_symbol
            from services.signal_engine import build_signal, format_signal_message
            result = await scan_symbol(share_data["symbol"], share_data["market"], "1d")
            if result:
                signal = build_signal(result)
                report = format_signal_message(signal)
                await message.answer(f"📤 تحليل مشاركة (مشاهدات: {share_data['views']})\n\n{report[:3500]}")
                return

    from config import settings
    from bot.keyboards.main import subscription_plans, back_button

    is_new = user.plan == "free" and user.subscription_end is None

    if is_new:
        text = (
            "مرحباً بك في البوت التعليمي لمتابعة الأسواق المالية 🤖\n\n"
            "هذا البوت يقدم قراءات فنية تعليمية للأسواق:\n"
            "📈 السوق السعودي\n"
            "🇺🇸 السوق الأمريكي\n"
            "₿ العملات الرقمية\n\n"
            "💎 خطط الاشتراك:\n\n"
            f"🥉 Basic — {settings.basic_price:.0f} ريال / شهر\n"
            f"🥈 Pro — {settings.pro_price:.0f} ريال / شهر\n"
            f"🥇 VIP — {settings.vip_price:.0f} ريال / شهر\n"
            f"💎 Lifetime — {settings.lifetime_price:.0f} ريال\n\n"
            "للاشتراك، تواصل مع الدعم للحصول على كود التفعيل:\n"
            "👤 @hidanx11\n\n"
            "أو أدخل كود التفعيل إذا كان لديك:"
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="💳 أدخل كود التفعيل", callback_data="enter_code")
        builder.button(text="👤 تواصل مع الدعم", callback_data="support")
        builder.button(text="🏠 الدخول للقائمة", callback_data="main_menu")
        builder.adjust(1, 1, 1)
        await message.answer(text, reply_markup=builder.as_markup())
    else:
        text = (
            "مرحباً بك في البوت التعليمي لمتابعة الأسواق المالية 🤖\n\n"
            "اختر من القائمة أدناه:"
        )
        await message.answer(text, reply_markup=main_menu())


@router.message(Command("help"))
async def cmd_help(message: Message):
    text = (
        "📋 قائمة الأوامر المتاحة:\n\n"
        "/start - عرض القائمة الرئيسية\n"
        "/help - عرض المساعدة\n"
        "/daily - التقارير اليومية\n"
        "/status - حالة الأسواق\n"
        "/profile - ملفي الشخصي\n"
        "/plans - خطط الاشتراك\n"
        "/subscribe - الاشتراك\n\n"
        "يمكنك استخدام الأزرار أدناه للتنقل بين القوائم."
    )
    await message.answer(text, reply_markup=main_menu())


@router.message(Command("daily"))
async def cmd_daily(message: Message):
    text = "📅 التقارير اليومية:\n\nاختر السوق لعرض التقرير:"
    await message.answer(text, reply_markup=daily_report_menu())


@router.message(Command("ping"))
async def cmd_ping(message: Message):
    import time
    start = time.time()
    msg = await message.answer("🏓 Pong...")
    elapsed = round((time.time() - start) * 1000)
    await msg.edit_text(f"🏓 Pong! ⏱ {elapsed}ms")


@router.message(Command("version"))
async def cmd_version(message: Message):
    text = (
        "📦 **معلومات النظام**\n\n"
        "الإصدار: 2.0.0\n"
        "الاسم: TDawlX Bot\n"
        "اللغة: Python 3.12+\n"
        "الإطار: aiogram 3.x\n"
        "قاعدة البيانات: SQLite (SQLAlchemy async)\n"
        "مزود البيانات: Yahoo Finance + Binance\n"
        "آخر تحديث: 2026-07-01"
    )
    await message.answer(text, reply_markup=back_button("main_menu"))


@router.callback_query(F.data == "daily_reports")
async def cb_daily_reports(callback: CallbackQuery):
    await callback.answer()
    text = "📅 التقارير اليومية:\n\nاختر السوق لعرض التقرير:"
    await callback.message.edit_text(text, reply_markup=daily_report_menu())


@router.callback_query(F.data.startswith("daily_report:"))
async def cb_daily_report_market(callback: CallbackQuery):
    await callback.answer()
    market_key = callback.data.split(":")[1].upper()
    market_display = {"SAUDI": "السوق السعودي", "US": "السوق الأمريكي", "CRYPTO": "العملات الرقمية"}
    display = market_display.get(market_key, market_key)

    await callback.message.edit_text(f"📅 جاري تحضير التقرير اليومي لـ {display}...")

    symbols = TOP_SYMBOLS.get(market_key, [])[:5]
    reports = []
    for sym in symbols:
        result = await scan_symbol(sym, market_key)
        if result:
            reports.append(format_technical_report(result))

    if not reports:
        await callback.message.edit_text(
            f"❌ تعذر تحضير التقرير لـ {display} حالياً.",
            reply_markup=back_button("daily_reports"),
        )
        return

    text = f"📅 التقرير اليومي - {display}\n" + "\n---\n".join(reports)
    await callback.message.edit_text(text[:4000], reply_markup=back_button("daily_reports"))


@router.message(Command("status"))
async def cmd_status(message: Message):
    try:
        async with get_session() as session:
            stmt = select(MarketSettings)
            result = await session.execute(stmt)
            markets = result.scalars().all()
    except Exception:
        markets = []

    status_lines = ["📊 حالة الأسواق:\n"]
    market_map = {"saudi": "السوق السعودي", "us": "السوق الأمريكي", "crypto": "العملات الرقمية"}

    if markets:
        for m in markets:
            name = market_map.get(m.market, m.market)
            status = "🟢 مفتوح" if m.is_enabled else "🔴 مغلق"
            status_lines.append(f"{name}: {status}")
    else:
        for key, name in market_map.items():
            status_lines.append(f"{name}: 🟢 مفتوح")

    await message.answer("\n".join(status_lines), reply_markup=main_menu())


@router.message(Command("profile"))
async def cmd_profile(message: Message):
    telegram_id = message.from_user.id
    user = await _get_user(telegram_id)
    if not user:
        await message.answer("المستخدم غير موجود.")
        return

    limits = get_plan_limits(user.plan)
    async with get_session() as session:
        from models import Watchlist, Alert
        wl_count = (await session.execute(
            select(Watchlist).where(Watchlist.user_id == user.id)
        )).scalars().all()
        alerts_count = (await session.execute(
            select(Alert).where(Alert.user_id == user.id)
        )).scalars().all()

    info = {
        "scans_used": user.scans_today,
        "scans_limit": limits["scans_daily"] if limits["scans_daily"] != -1 else "∞",
        "alerts_count": len(alerts_count),
        "alerts_limit": limits["max_alerts"] if limits["max_alerts"] != -1 else "∞",
        "watchlist_count": len(wl_count),
        "watchlist_limit": limits["max_watchlist"] if limits["max_watchlist"] != -1 else "∞",
        "referral_count": len(user.referrals) if hasattr(user, "referrals") and user.referrals else 0,
    }

    text = format_profile(user, info)
    daily = getattr(user, "daily_report", True)
    await message.answer(text, reply_markup=profile_menu(daily))


@router.callback_query(F.data == "my_profile")
async def cb_my_profile(callback: CallbackQuery):
    await callback.answer()
    telegram_id = callback.from_user.id
    user = await _get_user(telegram_id)
    if not user:
        await callback.message.edit_text("المستخدم غير موجود.")
        return

    limits = get_plan_limits(user.plan)
    async with get_session() as session:
        from models import Watchlist, Alert
        wl_count = (await session.execute(
            select(Watchlist).where(Watchlist.user_id == user.id)
        )).scalars().all()
        alerts_count = (await session.execute(
            select(Alert).where(Alert.user_id == user.id)
        )).scalars().all()

    info = {
        "scans_used": user.scans_today,
        "scans_limit": limits["scans_daily"] if limits["scans_daily"] != -1 else "∞",
        "alerts_count": len(alerts_count),
        "alerts_limit": limits["max_alerts"] if limits["max_alerts"] != -1 else "∞",
        "watchlist_count": len(wl_count),
        "watchlist_limit": limits["max_watchlist"] if limits["max_watchlist"] != -1 else "∞",
        "referral_count": len(user.referrals) if hasattr(user, "referrals") and user.referrals else 0,
    }

    text = format_profile(user, info)
    daily = getattr(user, "daily_report", True)
    await callback.message.edit_text(text, reply_markup=profile_menu(daily))


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery):
    await callback.answer()
    _user_context.pop(callback.from_user.id, None)
    text = (
        "مرحباً بك في البوت التعليمي لمتابعة الأسواق المالية 🤖\n\n"
        "اختر من القائمة أدناه:"
    )
    await callback.message.edit_text(text, reply_markup=main_menu())


@router.callback_query(F.data.in_({"market:saudi", "market:us", "market:crypto"}))
async def cb_market_selected(callback: CallbackQuery):
    await callback.answer()
    market_key = callback.data.split(":")[1]
    market_name = MARKET_DISPLAY.get(market_key, market_key)

    ctx = _user_context.get(callback.from_user.id, {})
    context_type = ctx.get("context")

    if context_type == "chart":
        _user_context[callback.from_user.id] = {"context": "chart", "market": MARKET_MAP[market_key]}
        text = f"📉 أدخل رمز الأصل المالي للرسم البياني في {market_name}:\nمثال: 2222.SR للسعودي، AAPL للأمريكي، BTCUSDT للكريبتو"
        await callback.message.edit_text(text, reply_markup=back_button("chart_menu"))
    elif context_type == "watchlist_add":
        _user_context[callback.from_user.id] = {"context": "watchlist_add", "market": MARKET_MAP[market_key]}
        text = f"⭐ أدخل رمز الأصل المالي لإضافته إلى قائمة المتابعة في {market_name}:"
        await callback.message.edit_text(text, reply_markup=back_button("main_menu"))
    else:
        _user_context.pop(callback.from_user.id, None)
        text = f"📊 اختر نوع التحليل لـ {market_name}:"
        await callback.message.edit_text(text, reply_markup=scan_type_menu(market_key))


@router.callback_query(F.data.startswith("quick_scan:"))
async def cb_quick_scan(callback: CallbackQuery):
    await callback.answer()
    market_key = callback.data.split(":", 1)[1]
    market = MARKET_MAP.get(market_key, market_key.upper())
    _user_context[callback.from_user.id] = {"context": "scan", "market": market}
    text = "أدخل رمز الأصل المالي (مثال: 2222.SR للسعودي، AAPL للأمريكي، BTCUSDT للكريبتو)"
    await callback.message.edit_text(text, reply_markup=back_button("main_menu"))


@router.callback_query(F.data.startswith("full_analysis:"))
async def cb_full_analysis(callback: CallbackQuery):
    await callback.answer()
    market_key = callback.data.split(":", 1)[1]
    market = MARKET_MAP.get(market_key, market_key.upper())
    _user_context[callback.from_user.id] = {"context": "full_analysis", "market": market}
    text = "أدخل رمز الأصل المالي للتحليل الكامل (مثال: 2222.SR للسعودي، AAPL للأمريكي، BTCUSDT للكريبتو)"
    await callback.message.edit_text(text, reply_markup=back_button("main_menu"))


@router.callback_query(F.data == "help")
async def cb_help(callback: CallbackQuery):
    await callback.answer()
    text = (
        "📋 قائمة الأوامر المتاحة:\n\n"
        "/start - عرض القائمة الرئيسية\n"
        "/help - عرض المساعدة\n"
        "/daily - التقارير اليومية\n"
        "/status - حالة الأسواق\n"
        "/profile - ملفي الشخصي\n"
        "/plans - خطط الاشتراك\n"
        "/subscribe - الاشتراك\n\n"
        "يمكنك استخدام الأزرار أدناه للتنقل بين القوائم."
    )
    await callback.message.edit_text(text, reply_markup=main_menu())


@router.callback_query(F.data == "support")
async def cb_support(callback: CallbackQuery):
    await callback.answer()
    from bot.keyboards.main import support_menu
    text = "📧 تواصل مع الدعم الفني:\n👤 تيليقرام: @hidanx11"
    await callback.message.edit_text(text, reply_markup=support_menu())


@router.callback_query(F.data == "support_contact")
async def cb_support_contact(callback: CallbackQuery):
    await callback.answer("تواصل معي على تيليقرام: @hidanx11", show_alert=True)


@router.callback_query(F.data == "support_faq")
async def cb_support_faq(callback: CallbackQuery):
    await callback.answer()
    text = (
        "❓ الأسئلة الشائعة:\n\n"
        "س: كيف يمكنني الاشتراك؟\n"
        "ج: اختر خطة الاشتراك من قائمة الاشتراك ثم أدخل كود التفعيل.\n\n"
        "س: كم عدد المسحات المجانية؟\n"
        "ج: يمكنك إجراء 5 مسحات يومياً في الباقة المجانية.\n\n"
        "س: كيف أضيف أصل إلى قائمة المتابعة؟\n"
        "ج: من قائمة الأصل، اختر إضافة للمراقبة."
    )
    await callback.message.edit_text(text, reply_markup=back_button("main_menu"))


@router.callback_query(F.data == "support_group")
async def cb_support_group(callback: CallbackQuery):
    await callback.answer("تواصل معي مباشرة: @hidanx11", show_alert=True)


@router.callback_query(F.data.startswith("profile_info"))
async def cb_profile_info(callback: CallbackQuery):
    await cb_my_profile(callback)


@router.callback_query(F.data == "profile_usage")
async def cb_profile_usage(callback: CallbackQuery):
    await callback.answer()
    telegram_id = callback.from_user.id
    user = await _get_user(telegram_id)
    if not user:
        await callback.message.edit_text("المستخدم غير موجود.")
        return

    limits = get_plan_limits(user.plan)
    text = (
        f"📊 إحصائيات الاستخدام:\n\n"
        f"المسح اليومي: {user.scans_today}/{limits['scans_daily'] if limits['scans_daily'] != -1 else '∞'}\n"
        f"آخر مسح: {user.last_scan_date or 'لا يوجد'}"
    )
    daily = getattr(user, "daily_report", True)
    await callback.message.edit_text(text, reply_markup=profile_menu(daily))


@router.callback_query(F.data == "toggle_daily_report")
async def cb_toggle_daily_report(callback: CallbackQuery):
    await callback.answer()
    telegram_id = callback.from_user.id
    async with get_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if user:
            current = getattr(user, "daily_report", True)
            user.daily_report = not current
            await session.commit()
            status = "تفعيل" if user.daily_report else "إلغاء"
            await callback.message.edit_text(
                f"✅ تم {status} التقارير اليومية.",
                reply_markup=profile_menu(user.daily_report),
            )


@router.callback_query(F.data == "symbol_browser")
async def cb_symbol_browser(callback: CallbackQuery):
    await callback.answer()
    text = "🔍 تصفح الأسواق:\n\nاختر السوق لتصفح الرموز المتاحة:"
    await callback.message.edit_text(text, reply_markup=symbol_browser_menu())


@router.callback_query(F.data.startswith("browse:"))
async def cb_browse_market(callback: CallbackQuery):
    await callback.answer()
    market_key = callback.data.split(":")[1]
    market = MARKET_MAP.get(market_key, market_key.upper())
    sectors = get_sectors(market)
    market_name = MARKET_DISPLAY.get(market_key, market)
    text = f"📂 اختر القطاع في {market_name}:"
    await callback.message.edit_text(text, reply_markup=sectors_menu(sectors, market_key))


@router.callback_query(F.data.startswith("sector:"))
async def cb_sector_symbols(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":", 3)
    market_key = parts[1]
    sector = parts[2]
    page = int(parts[3]) if len(parts) > 3 else 1
    market = MARKET_MAP.get(market_key, market_key.upper())
    symbols, current_page, total_pages = await get_symbols_by_sector(market, sector, page)
    market_name = MARKET_DISPLAY.get(market_key, market)
    if not symbols:
        await callback.message.edit_text(
            f"⚠️ لا توجد رموز في قطاع {sector} حالياً.",
            reply_markup=back_button(f"browse:{market_key}"),
        )
        return
    text = f"📂 {market_name} - {sector}\n({current_page}/{total_pages})"
    await callback.message.edit_text(text, reply_markup=symbol_list_menu(symbols, current_page, total_pages, market_key, sector))


@router.callback_query(F.data.startswith("sym_list:"))
async def cb_all_symbols(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    market_key = parts[1]
    page = int(parts[2]) if len(parts) > 2 else 1
    market = MARKET_MAP.get(market_key, market_key.upper())
    symbols, current_page, total_pages = await get_all_symbols_by_market(market, page)
    market_name = MARKET_DISPLAY.get(market_key, market)
    if not symbols:
        await callback.message.edit_text(
            f"⚠️ لا توجد رموز متاحة في {market_name} حالياً.",
            reply_markup=back_button("main_menu"),
        )
        return
    text = f"📋 جميع الرموز - {market_name}\n({current_page}/{total_pages})"
    await callback.message.edit_text(text, reply_markup=symbol_list_menu(symbols, current_page, total_pages, market_key))


@router.callback_query(F.data.startswith("symbol:"))
async def cb_symbol_detail(callback: CallbackQuery):
    await callback.answer()
    symbol_id = int(callback.data.split(":")[1])
    sym = await get_symbol_by_id(symbol_id)
    if not sym:
        await callback.message.edit_text("⚠️ الرمز غير موجود.", reply_markup=back_button("symbol_browser"))
        return
    text = (
        f"🔍 {sym.name_ar}\n"
        f"{'─' * 20}\n"
        f"🏷 الاسم: {sym.name_ar}\n"
        f"Name: {sym.name_en}\n"
        f"🔢 الرمز: {sym.symbol}\n"
        f"🏢 القطاع: {sym.sector}\n"
        f"🌍 السوق: {sym.market}\n"
        f"{'─' * 20}\n"
        f"اختر الإجراء:"
    )
    await callback.message.edit_text(text, reply_markup=symbol_detail_menu(symbol_id))


@router.callback_query(F.data == "symbol_search")
async def cb_symbol_search(callback: CallbackQuery):
    await callback.answer()
    text = "🔍 **محرك البحث الذكي**\n\nاكتب اسم الشركة أو الرمز:\n\nمثال:\n• الراجحي\n• Apple\n• تسلا\n• بتكوين\n• 2222.SR"
    await callback.message.edit_text(text, reply_markup=back_button("symbol_browser"))


@router.callback_query(F.data.startswith("smart_result:"))
async def cb_smart_result(callback: CallbackQuery):
    await callback.answer()
    symbol_id = int(callback.data.split(":")[1])
    sym = await get_symbol_by_id(symbol_id)
    if not sym:
        await callback.message.edit_text("⚠️ الرمز غير موجود.", reply_markup=back_button("symbol_browser"))
        return

    market_label = MARKET_DISPLAY.get(sym.market.lower(), sym.market)
    sector_line = f"🏢 القطاع: {sym.sector}\n" if sym.sector else ""

    from bot.keyboards.main import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 فحص فني", callback_data=f"quick_scan_sym:{sym.symbol}:{sym.market}")
    builder.button(text="📈 عرض الشارت", callback_data=f"quick_chart:{sym.symbol}:{sym.market}")
    builder.button(text="🔔 إنشاء تنبيه", callback_data=f"alert_create:{sym.symbol}:{sym.market.lower()}")
    builder.button(text="⭐ إضافة للمراقبة", callback_data=f"watch_add:{sym.symbol}:{sym.market.lower()}")
    builder.button(text="↩️ رجوع", callback_data="main_menu")
    builder.adjust(2, 2, 1)

    card = (
        f"وجدت النتيجة التالية:\n\n"
        f"🏷 {sym.name_ar}\n"
        f"🔢 {sym.symbol}\n"
        f"🌍 السوق {market_label}\n"
        f"{sector_line}\n"
        f"اختر الإجراء:"
    )
    await callback.message.edit_text(card, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("quick_scan_sym:"))
async def cb_quick_scan_sym(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":", 2)
    symbol = parts[1]
    market = parts[2]

    await callback.message.edit_text(f"📊 جاري تحليل {symbol}...")

    try:
        result = await scan_symbol(symbol, market, "1d")
    except Exception:
        result = None

    if not result:
        await callback.message.edit_text(
            f"❌ تعذر الحصول على بيانات لـ {symbol}.",
            reply_markup=back_button("main_menu"),
        )
        return

    from services.subscriptions import can_scan, increment_scan
    from services.scanner import log_scan_to_db
    from bot.keyboards.main import symbol_actions

    user = await _get_user(callback.from_user.id)
    if user:
        can = await can_scan(user.id)
        if not can:
            await callback.message.edit_text(
                "🔒 هذه الميزة متاحة للمشتركين فقط.\n\nتواصل مع الدعم للحصول على اشتراك أو تجربة:\n👤 @hidanx11",
                reply_markup=back_button("main_menu"),
            )
            return
        await increment_scan(user.id)
        score_val = result.get("score")
        score_num = float(score_val.overall) if score_val else None
        price_val = result.get("current_price")
        await log_scan_to_db(user.id, symbol, market, "1d", score_num, price_val)

    signal = build_signal(result)
    report = format_signal_message(signal)

    market_key = market.lower()
    kb = symbol_actions(symbol, market_key)
    await callback.message.edit_text(report, reply_markup=kb)

    try:
        from services.chart_generator import generate_chart
        from aiogram.types import FSInputFile
        name = result.get("name_ar") or symbol
        chart_path = generate_chart(symbol, market, "1d", name=name)
        if chart_path:
            photo = FSInputFile(chart_path)
            await callback.message.answer_photo(photo, caption=f"📉 {name} — {symbol}")
    except Exception:
        pass


@router.callback_query(F.data.startswith("quick_chart:"))
async def cb_quick_chart(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":", 2)
    symbol = parts[1]
    market = parts[2]

    await callback.message.edit_text(f"📈 جاري إنشاء الشارت لـ {symbol}...")

    try:
        from services.chart_generator import generate_chart
        from services.symbols_service import get_symbol_info
        from aiogram.types import FSInputFile

        info = await get_symbol_info(symbol, market)
        name = info["name_ar"] if info else symbol
        chart_path = generate_chart(symbol, market, "1d", name=name)
        if chart_path:
            photo = FSInputFile(chart_path)
            await callback.message.answer_photo(photo, caption=f"📉 {name} — {symbol}")
            await callback.message.edit_text(f"📈 شارت {name} — {symbol}", reply_markup=back_button("main_menu"))
        else:
            await callback.message.edit_text(
                f"❌ تعذر إنشاء الشارت لـ {symbol}.",
                reply_markup=back_button("main_menu"),
            )
    except Exception:
        await callback.message.edit_text(
            f"❌ حدث خطأ أثناء إنشاء الشارت.",
            reply_markup=back_button("main_menu"),
        )


async def _auto_search(message: Message, query: str):
    msg = await message.answer(f"🔍 جاري البحث عن '{query}'...")

    detected = await auto_detect_symbol(query)

    if detected and detected.get("alternatives"):
        results = await smart_search(query)
        if results:
            text = format_search_results(results)
            kb = build_search_keyboard(results)
            await msg.edit_text(text, reply_markup=kb)
            return

    if detected and detected.get("source") in ("db", "crypto_map", "pattern"):
        symbol = detected["symbol"]
        market = detected["market"]
        name = detected.get("name_ar") or detected.get("name_en") or symbol
        sector = detected.get("sector")

        sector_line = f"🏢 القطاع: {sector}\n" if sector else ""
        market_label = MARKET_DISPLAY.get(market.lower(), market)

        from bot.keyboards.main import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        builder.button(text="📊 فحص فني", callback_data=f"quick_scan_sym:{symbol}:{market}")
        builder.button(text="📈 عرض الشارت", callback_data=f"quick_chart:{symbol}:{market}")
        builder.button(text="🔔 إنشاء تنبيه", callback_data=f"alert_create:{symbol}:{market.lower()}")
        builder.button(text="⭐ إضافة للمراقبة", callback_data=f"watch_add:{symbol}:{market.lower()}")
        builder.button(text="↩️ رجوع", callback_data="main_menu")
        builder.adjust(2, 2, 1)

        card = (
            f"وجدت النتيجة التالية:\n\n"
            f"🏷 {name}\n"
            f"🔢 {symbol}\n"
            f"🌍 السوق {market_label}\n"
            f"{sector_line}\n"
            f"اختر الإجراء:"
        )
        await msg.edit_text(card, reply_markup=builder.as_markup())
        return

    results = await smart_search(query)
    if not results:
        await msg.edit_text(
            f"⚠️ لا توجد نتائج لـ '{query}'.\nجرّب كتابة اسم الشركة أو الرمز بشكل مختلف.",
            reply_markup=back_button("main_menu"),
        )
        return
    text = format_search_results(results)
    kb = build_search_keyboard(results)
    await msg.edit_text(text, reply_markup=kb)


@router.message(F.text)
async def handle_text_input(message: Message):
    telegram_id = message.from_user.id
    ctx = _user_context.get(telegram_id)

    if ctx:
        context_type = ctx.get("context")
        if context_type in ("scan", "full_analysis"):
            await handle_symbol_input(message)
            return
        elif context_type == "chart":
            await handle_chart_symbol_input(message)
            return
        elif context_type == "watchlist_add":
            await handle_watchlist_symbol_input(message)
            return
        elif context_type == "alert_value":
            await handle_alert_value_input(message)
            return
        elif context_type == "activation_code":
            await handle_activation_code(message)
            return
        elif context_type in ("compare_first", "compare_second"):
            from bot.handlers.comparison import handle_compare_input
            await handle_compare_input(message)
            return
        elif context_type == "price_tracker":
            await handle_price_tracker_input(message)
            return

    query = message.text.strip()
    if len(query) < 2:
        return
    await _auto_search(message, query)


async def handle_price_tracker_input(message: Message):
    telegram_id = message.from_user.id
    ctx = _user_context.get(telegram_id)
    if not ctx or ctx.get("context") != "price_tracker":
        return

    symbol = ctx.get("symbol", "")
    market = ctx.get("market", "US")

    text = message.text.strip()
    parts = text.split()

    try:
        target_price = float(parts[0].replace(",", ""))
    except (ValueError, IndexError):
        await message.answer("❌ السعر غير صالح. مثال: 150.50 فوق")
        return

    direction = "above"
    if len(parts) > 1:
        dir_text = parts[1].lower()
        if dir_text in ("تحت", "below", "down", "نزول"):
            direction = "below"

    user = await _get_user(telegram_id)
    if not user:
        await message.answer("المستخدم غير موجود.")
        _user_context.pop(telegram_id, None)
        return

    from services.price_tracker import create_price_tracker
    tracker = await create_price_tracker(user.id, symbol, market, target_price, direction)
    _user_context.pop(telegram_id, None)

    arrow = "📈" if direction == "above" else "📉"
    dir_text = "فوق" if direction == "above" else "تحت"
    await message.answer(
        f"✅ تم إنشاء تتبع السعر\n\n"
        f"🔢 {symbol}\n"
        f"{arrow} الهدف: {target_price:,.4f} ({dir_text})\n\n"
        f"البوت يبعت لك رسالة فورية لما السعر يوصل للهدف.",
        reply_markup=back_button("main_menu"),
    )
