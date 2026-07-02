from typing import Optional

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import settings

PLAN_FEATURES = {
    "free": [
        "subscription", "support", "help",
    ],
    "basic": [
        "scan_quick", "symbol_browser", "market:saudi", "market:us", "market:crypto",
        "my_alerts", "my_watchlist", "chart_menu", "subscription", "support_ticket", "support", "help",
    ],
    "pro": [
        "scan_quick", "symbol_browser", "heatmap", "market:saudi", "market:us", "market:crypto",
        "market_overview", "news_menu", "daily_reports", "compare",
        "screener_menu", "fib_menu", "fear_greed",
        "sector_performance", "my_news_alerts", "my_stats", "dividends",
        "my_alerts", "price_trackers", "my_watchlist", "chart_menu", "top_readings",
        "share_menu", "export_history",
        "subscription", "support_ticket", "support", "help", "terms",
    ],
    "vip": [
        "scan_quick", "symbol_browser", "heatmap", "market:saudi", "market:us", "market:crypto",
        "market_overview", "news_menu", "daily_reports", "compare",
        "mtf_scan", "vip_signals", "screener_menu", "fib_menu", "risk_calc", "fear_greed",
        "sector_performance", "my_news_alerts", "my_stats", "dividends", "rs_compare",
        "my_alerts", "price_trackers", "my_watchlist", "chart_menu", "top_readings",
        "share_menu", "export_history", "referral_menu",
        "my_profile", "language_toggle",
        "subscription", "support_ticket", "support", "help", "terms",
    ],
}

ALL_BUTTONS: list[tuple[str, str]] = [
    ("📊 فحص سريع", "scan_quick"),
    ("🔍 تصفح الرموز", "symbol_browser"),
    ("🗺️ الخريطة الحرارية", "heatmap"),
    ("📈 السوق السعودي", "market:saudi"),
    ("🇺🇸 السوق الأمريكي", "market:us"),
    ("₿ العملات الرقمية", "market:crypto"),
    ("📊 حالة السوق", "market_overview"),
    ("📰 أخبار السوق", "news_menu"),
    ("🏢 أداء القطاعات", "sector_performance"),
    ("📢 أخبار رموزي", "my_news_alerts"),
    ("📊 إحصائياتي", "my_stats"),
    ("📅 توزيعات الأرباح", "dividends"),
    ("💪 مقارنة القوة", "rs_compare"),
    ("📅 التقارير اليومية", "daily_reports"),
    ("📊 مقارنة", "compare"),
    ("🔄 تحليل متعدد الفريمات", "mtf_scan"),
    ("🚀 إشارات VIP", "vip_signals"),
    ("🔍 فاحص السوق", "screener_menu"),
    ("📐 فيبوناتشي", "fib_menu"),
    ("📊 حاسبة المخاطر", "risk_calc"),
    ("😱 الخوف والطمع", "fear_greed"),
    ("🔔 تنبيهاتي", "my_alerts"),
    ("🎯 تتبع الأسعار", "price_trackers"),
    ("⭐ قائمتي", "my_watchlist"),
    ("📉 الشارت", "chart_menu"),
    ("🏆 أقوى القراءات", "top_readings"),
    ("📤 مشاركة تحليل", "share_menu"),
    ("📥 تصدير سجلي", "export_history"),
    ("🎁 دعوة صديق", "referral_menu"),
    ("👤 حسابي", "my_profile"),
    ("🌐 اللغة", "language_toggle"),
    ("💳 الاشتراك", "subscription"),
    ("🎫 تذكرة دعم", "support_ticket"),
    ("🛠 الدعم", "support"),
    ("📋 المساعدة", "help"),
    ("⚖️ الشروط والأحكام", "terms"),
]

MAIN_MENU_BUTTONS = ALL_BUTTONS


def main_menu(plan: str = "vip") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 التحليل والفحص", callback_data="menu:analysis")
    builder.button(text="🌍 الأسواق", callback_data="menu:markets")
    builder.button(text="🔔 المتابعة والتنبيهات", callback_data="menu:watch")
    builder.button(text="📈 التقارير والفرص", callback_data="menu:reports")
    builder.button(text="🧰 أدوات احترافية", callback_data="menu:tools")
    builder.button(text="👤 حسابي والدعم", callback_data="menu:account")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def section_menu(section: str, plan: str = "vip") -> InlineKeyboardMarkup:
    groups = {
        "analysis": [
            ("📊 فحص سريع", "scan_quick"),
            ("🔍 تصفح الرموز", "symbol_browser"),
            ("📉 الشارت", "chart_menu"),
            ("🔄 تحليل متعدد الفريمات", "mtf_scan"),
            ("🚀 إشارات VIP", "vip_signals"),
        ],
        "markets": [
            ("📈 السوق السعودي", "market:saudi"),
            ("🇺🇸 السوق الأمريكي", "market:us"),
            ("₿ العملات الرقمية", "market:crypto"),
            ("📊 حالة السوق", "market_overview"),
            ("🗺️ الخريطة الحرارية", "heatmap"),
            ("🏢 أداء القطاعات", "sector_performance"),
        ],
        "watch": [
            ("⭐ قائمتي", "my_watchlist"),
            ("🔔 تنبيهاتي", "my_alerts"),
            ("🎯 تتبع الأسعار", "price_trackers"),
            ("📢 أخبار رموزي", "my_news_alerts"),
        ],
        "reports": [
            ("🚀 رادار الفرص", "opportunity_radar"),
            ("🔥 فرصة اليوم", "opportunity_day"),
            ("📅 التقارير اليومية", "daily_reports"),
            ("🏆 أقوى القراءات", "top_readings"),
            ("📰 أخبار السوق", "news_menu"),
            ("📊 إحصائياتي", "my_stats"),
            ("📥 تصدير سجلي", "export_history"),
        ],
        "tools": [
            ("📊 مقارنة", "compare"),
            ("🔍 فاحص السوق", "screener_menu"),
            ("📐 فيبوناتشي", "fib_menu"),
            ("📊 حاسبة المخاطر", "risk_calc"),
            ("😱 الخوف والطمع", "fear_greed"),
            ("💪 مقارنة القوة", "rs_compare"),
        ],
        "account": [
            ("👤 حسابي", "my_profile"),
            ("💳 الاشتراك", "subscription"),
            ("🎫 تذكرة دعم", "support_ticket"),
            ("🛠 الدعم", "support"),
            ("📋 المساعدة", "help"),
            ("⚖️ الشروط والأحكام", "terms"),
        ],
    }

    builder = InlineKeyboardBuilder()
    for text, cb in groups.get(section, []):
        builder.button(text=text, callback_data=cb)
    builder.button(text="↩️ رجوع", callback_data="main_menu")
    builder.adjust(2)
    return builder.as_markup()


def market_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📈 السوق السعودي", callback_data="market:saudi")
    builder.button(text="🇺🇸 السوق الأمريكي", callback_data="market:us")
    builder.button(text="₿ العملات الرقمية", callback_data="market:crypto")
    builder.button(text="↩️ رجوع", callback_data="main_menu")
    builder.adjust(2)
    return builder.as_markup()


def chart_market_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📈 السعودي", callback_data="chart:saudi")
    builder.button(text="🇺🇸 الأمريكي", callback_data="chart:us")
    builder.button(text="₿ الكريبتو", callback_data="chart:crypto")
    builder.button(text="🔍 تصفح الرموز", callback_data="symbol_browser")
    builder.button(text="↩️ رجوع", callback_data="menu:analysis")
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def timeframe_menu(market: str, callback_prefix: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    items = [
        ("15 دقيقة", "15m"),
        ("ساعة", "1h"),
        ("4 ساعات", "4h"),
        ("يومي", "1d"),
        ("أسبوعي", "1w"),
    ]
    for text, tf in items:
        builder.button(text=text, callback_data=f"{callback_prefix}:{tf}")
    builder.button(text="↩️ رجوع", callback_data=f"market:{market}")
    builder.adjust(3, 2, 1)
    return builder.as_markup()


def scan_type_menu(market: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 فحص سريع", callback_data=f"quick_scan:{market}")
    builder.button(text="📋 تحليل كامل", callback_data=f"full_analysis:{market}")
    builder.button(text="📉 رسم شارت", callback_data=f"chart:{market}")
    builder.button(text="⭐ إضافة للمراقبة", callback_data=f"watchlist_add:{market}")
    builder.button(text="↩️ رجوع", callback_data="main_menu")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def symbol_actions(symbol: str, market: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 عرض الشارت", callback_data=f"chart:{symbol}:{market}")
    builder.button(text="⭐ إضافة للمراقبة", callback_data=f"watch_add:{symbol}:{market}")
    builder.button(text="🔔 إنشاء تنبيه", callback_data=f"alert_create:{symbol}:{market}")
    builder.button(text="🎯 تتبع السعر", callback_data=f"ptrk:{symbol}:{market}")
    builder.button(text="📤 مشاركة", callback_data=f"share:{symbol}:{market}")
    builder.button(text="📄 تصدير PDF", callback_data=f"export_pdf:{symbol}:{market}")
    builder.button(text="🔄 فحص فريم آخر", callback_data=f"rescan:{symbol}:{market}")
    builder.button(text="↩️ رجوع", callback_data=f"market:{market}")
    builder.adjust(2, 2, 2, 2)
    return builder.as_markup()


def admin_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    items = [
        ("👥 المستخدمون", "admin_users"),
        ("💳 الاشتراكات", "admin_subs"),
        ("🔑 الأكواد", "admin_codes"),
        ("🎫 الكوبونات", "admin_coupons"),
        ("📊 الإحصائيات", "admin_stats"),
        ("🩺 صحة النظام", "admin_health"),
        ("⚙️ الإعدادات", "admin_settings"),
        ("📨 رسائل جماعية", "admin_broadcast"),
        ("📈 الأسواق", "admin_markets"),
        ("🔣 الرموز", "admin_symbols"),
        ("📋 المؤشرات", "admin_indicators"),
        ("💾 نسخة احتياطية", "admin_backup"),
        ("📢 إشعار تحديث", "admin_update_notify"),
        ("📊 إحصائيات شهرية", "admin_monthly_stats"),
        ("📜 السجلات", "admin_logs"),
        ("🔧 الصيانة", "admin_maintenance"),
        ("↩️ رجوع", "main_menu"),
    ]
    for text, cb in items:
        builder.button(text=text, callback_data=cb)
    builder.adjust(2)
    return builder.as_markup()


def admin_users_actions(user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📄 عرض", callback_data=f"admin_user_view:{user_id}")
    builder.button(text="⛔ حظر", callback_data=f"admin_user_ban:{user_id}")
    builder.button(text="✅ فك حظر", callback_data=f"admin_user_unban:{user_id}")
    builder.button(text="💳 تفعيل اشتراك", callback_data=f"admin_user_sub:{user_id}")
    builder.button(text="📨 إرسال رسالة", callback_data=f"admin_user_message:{user_id}")
    builder.button(text="↩️ رجوع", callback_data="admin_users")
    builder.adjust(2, 2, 2)
    return builder.as_markup()


def subscription_plans() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"🥉 Basic - {settings.basic_price:.0f} SAR/شهر",
        callback_data="subscribe:basic",
    )
    builder.button(
        text=f"🥈 Pro - {settings.pro_price:.0f} SAR/شهر",
        callback_data="subscribe:pro",
    )
    builder.button(
        text=f"🥇 VIP - {settings.vip_price:.0f} SAR/شهر",
        callback_data="subscribe:vip",
    )
    builder.button(
        text=f"💎 Lifetime - {settings.lifetime_price:.0f} SAR",
        callback_data="subscribe:lifetime",
    )
    builder.button(text="↩️ رجوع", callback_data="main_menu")
    builder.adjust(1, 1, 1, 1, 1)
    return builder.as_markup()


def back_button(callback_data: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="↩️ رجوع", callback_data=callback_data)
    return builder.as_markup()


def confirm_cancel() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ تأكيد", callback_data="confirm")
    builder.button(text="❌ إلغاء", callback_data="cancel")
    builder.adjust(2)
    return builder.as_markup()


def alert_types(symbol: str, market: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    items = [
        ("📈 السعر فوق", "price_above"),
        ("📉 السعر تحت", "price_below"),
        ("📊 RSI فوق", "rsi_above"),
        ("📊 RSI تحت", "rsi_below"),
        ("📈 حجم التداول", "volume_spike"),
    ]
    for text, atype in items:
        builder.button(text=text, callback_data=f"alert_set:{symbol}:{market}:{atype}")
    builder.button(text="↩️ رجوع", callback_data=f"symbol_actions:{symbol}:{market}")
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


def watchlist_actions(symbol: str, market: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 عرض", callback_data=f"chart:{symbol}:{market}")
    builder.button(text="❌ حذف", callback_data=f"watch_remove:{symbol}:{market}")
    builder.button(text="📋 فحص", callback_data=f"quick_scan:{symbol}:{market}")
    builder.button(text="↩️ رجوع", callback_data="my_watchlist")
    builder.adjust(2, 2)
    return builder.as_markup()


def daily_report_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📈 السوق السعودي", callback_data="daily_report:saudi")
    builder.button(text="🇺🇸 السوق الأمريكي", callback_data="daily_report:us")
    builder.button(text="₿ العملات الرقمية", callback_data="daily_report:crypto")
    builder.button(text="↩️ رجوع", callback_data="main_menu")
    builder.adjust(2, 2)
    return builder.as_markup()


def support_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📧 تواصل معنا", callback_data="support_contact")
    builder.button(text="❓ الأسئلة الشائعة", callback_data="support_faq")
    builder.button(text="💬 مجموعة المستخدمين", callback_data="support_group")
    builder.button(text="↩️ رجوع", callback_data="main_menu")
    builder.adjust(2, 2)
    return builder.as_markup()


def symbol_browser_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📈 السوق السعودي", callback_data="browse:saudi")
    builder.button(text="🇺🇸 السوق الأمريكي", callback_data="browse:us")
    builder.button(text="₿ العملات الرقمية", callback_data="browse:crypto")
    builder.button(text="🔍 بحث", callback_data="symbol_search")
    builder.button(text="↩️ رجوع", callback_data="main_menu")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def sectors_menu(sectors: list, market: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for sec in sectors:
        builder.button(text=sec, callback_data=f"sector:{market}:{sec}:1")
    builder.button(text="📋 عرض الكل", callback_data=f"sym_list:{market}:1")
    builder.button(text="🔍 بحث", callback_data="symbol_search")
    builder.button(text="↩️ رجوع", callback_data="main_menu")
    builder.adjust(2, 2)
    return builder.as_markup()


def symbol_list_menu(symbols: list, page: int, total_pages: int, market: str, sector: str = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for s in symbols:
        name = s.name_ar or s.name_en or s.symbol
        short_sym = s.symbol.replace(".SR", "").replace("USDT", "")
        label = f"{name[:18]} | {short_sym}"
        builder.button(text=label, callback_data=f"symbol:{s.id}")
    nav_row = []
    if page > 1:
        nav_row.append(("⬅️ السابق", f"sector:{market}:{sector}:{page - 1}" if sector else f"sym_list:{market}:{page - 1}"))
    if page < total_pages:
        nav_row.append(("التالي ➡️", f"sector:{market}:{sector}:{page + 1}" if sector else f"sym_list:{market}:{page + 1}"))
    for text, cb in nav_row:
        builder.button(text=text, callback_data=cb)
    builder.button(text="🔍 بحث", callback_data="symbol_search")
    builder.button(text="↩️ رجوع", callback_data=f"browse:{market}")
    builder.adjust(2, 2)
    return builder.as_markup()


def symbol_detail_menu(symbol_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 فحص سريع", callback_data=f"scan_sym:{symbol_id}")
    builder.button(text="📉 الشارت", callback_data=f"chart_sym:{symbol_id}")
    builder.button(text="⭐ قائمة المتابعة", callback_data=f"watch_sym:{symbol_id}")
    builder.button(text="🔔 تنبيه", callback_data=f"alert_sym:{symbol_id}")
    builder.button(text="↩️ رجوع", callback_data="symbol_browser")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def profile_menu(daily_enabled: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="👤 معلوماتي", callback_data="profile_info")
    builder.button(text="💳 الاشتراك", callback_data="subscription")
    builder.button(text="📊 الاستخدام", callback_data="profile_usage")
    status = "✅" if daily_enabled else "❌"
    builder.button(text=f"📅 التقارير {status}", callback_data="toggle_daily_report")
    builder.button(text="↩️ رجوع", callback_data="main_menu")
    builder.adjust(2, 2, 1)
    return builder.as_markup()
