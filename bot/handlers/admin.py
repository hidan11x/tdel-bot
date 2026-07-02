from typing import Any
from datetime import datetime, timedelta, timezone
import random
import string

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import settings
from database import get_session
from models import (
    User,
    ActivationCode,
    ActivationCodeRedemption,
    AffiliateCommission,
    AffiliatePartner,
    Coupon,
    AdminLog,
    Payment,
    ErrorLog,
    MarketSettings,
    SystemSettings,
    ScanLog,
    Symbol,
)
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from bot.keyboards import admin_menu, admin_users_actions, back_button, main_menu
from services.health import build_admin_health_report
from services.feature_access import (
    PREDICTION_FEATURE,
    grant_feature_access,
    list_feature_access,
    revoke_feature_access,
)
from services.symbols_service import (
    get_all_symbols_admin, toggle_symbol_active, toggle_symbol_popular,
    get_symbol_by_id, update_symbol, add_symbol,
)
from services.affiliates import create_affiliate_partner

router = Router()

from . import _user_context


class AdminStates(StatesGroup):
    broadcast_text = State()
    user_message = State()
    add_code_plan = State()
    add_code_duration = State()
    add_coupon_discount = State()
    add_coupon_max_uses = State()
    add_coupon_expiry = State()
    add_partner = State()
    extend_days = State()
    user_search = State()
    sym_edit_field = State()
    sym_edit_value = State()
    sym_add_market = State()
    sym_add_symbol = State()
    sym_add_yahoo = State()
    sym_add_name_ar = State()
    sym_add_name_en = State()
    sym_add_sector = State()
    sym_add_exchange = State()
    sym_add_currency = State()
    prediction_grant_id = State()
    prediction_revoke_id = State()


def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids


async def log_admin(admin_id: int, action: str, details: str = None):
    async with get_session() as session:
        async with session.begin():
            session.add(AdminLog(admin_id=admin_id, action=action, details=details))


def _code(length=10) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


def _activation_duration_label(code: ActivationCode) -> str:
    if code.duration_days >= 99999:
        return "permanent"
    minutes = int(getattr(code, "duration_minutes", 0) or 0)
    if minutes:
        if minutes % 1440 == 0:
            return f"{minutes // 1440}d"
        if minutes % 60 == 0:
            return f"{minutes // 60}h"
        return f"{minutes}m"
    if code.duration_days <= 0:
        return "1h"
    return f"{code.duration_days}d"


def _activation_code_status(code: ActivationCode) -> tuple[str, str]:
    if not code.is_active:
        return "🔴", "معطل"
    if code.max_uses > 0 and code.uses >= code.max_uses:
        return "⚫", "مستنفذ"
    expires_at = code.expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at and expires_at < datetime.now(timezone.utc):
        return "🟠", "منتهي"
    return "🟢", "جاهز"


def _activation_created_label(code: ActivationCode) -> str:
    created = code.created_at
    if not created:
        return "-"
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    created = created.astimezone(settings.timezone)
    return created.strftime("%Y-%m-%d %H:%M")


def _activation_plan_label(plan: str) -> str:
    return {
        "basic": "Basic",
        "pro": "Pro",
        "vip": "VIP",
        "lifetime": "Lifetime",
    }.get(plan, plan)


def _format_dt(value: datetime | None) -> str:
    if not value:
        return "-"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(settings.timezone).strftime("%Y-%m-%d %H:%M")


def _remaining_label(value: datetime | None) -> tuple[str, str]:
    if not value:
        return "غير محدد", "نشط"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if value <= now:
        return "منتهي", "منتهي"
    total_minutes = int((value - now).total_seconds() // 60)
    days, rem = divmod(total_minutes, 1440)
    hours, minutes = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days} يوم")
    if hours:
        parts.append(f"{hours} ساعة")
    if not days and minutes:
        parts.append(f"{minutes} دقيقة")
    return " و ".join(parts) or "أقل من دقيقة", "نشط"


@router.message(Command("admin"))
async def cmd_admin(msg: Message, state: FSMContext = None):
    if not is_admin(msg.from_user.id):
        return await msg.reply("⛔ غير مصرح لك بهذا الأمر.")
    if state:
        await state.clear()
    await msg.answer("🔧 لوحة التحكم", reply_markup=admin_menu())


@router.message(Command("health"))
async def cmd_health(msg: Message):
    if not is_admin(msg.from_user.id):
        return await msg.reply("⛔ غير مصرح لك بهذا الأمر.")
    text = await build_admin_health_report()
    await msg.answer(text, reply_markup=back_button("admin_panel"))


@router.message(Command("sync_symbols"))
async def cmd_sync_symbols(msg: Message):
    if not is_admin(msg.from_user.id):
        return await msg.reply("⛔ غير مصرح لك بهذا الأمر.")
    notice = await msg.answer("🌍 جاري تحديث رموز الأمريكي والكريبتو...")
    try:
        from services.symbol_sync import sync_symbol_universe

        results = await sync_symbol_universe()
        lines = ["✅ تم تحديث الرموز"]
        for item in results:
            lines.append(f"{item['market']}: تم جلب {item['fetched']} | جديد {item['added']}")
        await notice.edit_text("\n".join(lines), reply_markup=back_button("admin_panel"))
    except Exception as exc:
        await notice.edit_text(f"❌ تعذر تحديث الرموز:\n{str(exc)[:500]}", reply_markup=back_button("admin_panel"))


@router.callback_query(F.data == "admin_panel")
async def cb_admin_panel(cq: CallbackQuery):
    if not is_admin(cq.from_user.id):
        return await cq.answer("⛔ غير مصرح", show_alert=True)
    await cq.message.edit_text("🔧 لوحة التحكم", reply_markup=admin_menu())
    await cq.answer()


@router.callback_query(F.data.startswith("admin_"))
async def cb_admin_handler(cq: CallbackQuery, state: FSMContext = None):
    if not is_admin(cq.from_user.id):
        return await cq.answer("⛔ غير مصرح", show_alert=True)
    data = cq.data
    if data == "admin_users":
        await state.set_state(AdminStates.user_search)
        await _admin_users(cq)
    elif data == "admin_subs":
        await _admin_subs(cq)
    elif data == "admin_codes":
        await _admin_codes_menu(cq)
    elif data == "admin_affiliates":
        await _admin_affiliates(cq)
    elif data.startswith("admin_affiliate_paid:"):
        await _admin_affiliate_mark_paid(cq, int(data.split(":")[1]))
    elif data == "admin_stats":
        await _admin_stats(cq)
    elif data == "admin_settings":
        await _admin_settings(cq)
    elif data == "admin_broadcast":
        await state.set_state(AdminStates.broadcast_text)
        await cq.message.edit_text("📨 أرسل الرسالة التي تريد إرسالها لجميع المستخدمين:", reply_markup=back_button("admin_panel"))
        await cq.answer()
    elif data == "admin_markets":
        await _admin_markets(cq)
    elif data == "admin_logs":
        await _admin_logs(cq)
    elif data == "admin_maintenance":
        await _admin_maintenance(cq)
    elif data.startswith("admin_market_toggle:"):
        await _admin_market_toggle(cq, data.split(":")[1])
    elif data.startswith("admin_user_view:"):
        await _admin_user_view(cq, int(data.split(":")[1]))
    elif data.startswith("admin_user_ban:"):
        await _admin_user_ban(cq, int(data.split(":")[1]))
    elif data.startswith("admin_user_unban:"):
        await _admin_user_unban(cq, int(data.split(":")[1]))
    elif data.startswith("admin_user_extend:"):
        await state.update_data(target_user_id=int(data.split(":")[1]))
        await state.set_state(AdminStates.extend_days)
        await cq.message.edit_text("أدخل عدد الأيام للتمديد:", reply_markup=back_button("admin_panel"))
        await cq.answer()
    elif data == "admin_coupon_create":
        await state.set_state(AdminStates.add_coupon_discount)
        await cq.message.edit_text("أدخل نسبة الخصم (1-99):", reply_markup=back_button("admin_panel"))
        await cq.answer()
    elif data == "admin_affiliate_create":
        await state.set_state(AdminStates.add_partner)
        await cq.message.edit_text(
            "🤝 إنشاء شريك جديد\n\n"
            "اكتب البيانات بهذا الشكل:\n"
            "الاسم | نسبة العمولة | آيدي التليقرام اختياري\n\n"
            "مثال:\n"
            "قروب الأسهم | 30 | 123456789",
            reply_markup=back_button("admin_affiliates"),
        )
        await cq.answer()
    elif data == "admin_codes_create":
        await state.set_state(AdminStates.add_code_plan)
        text = (
            "➕ إنشاء كود تفعيل جديد\n\n"
            "اكتب كل البيانات في رسالة وحدة بهذا الشكل:\n\n"
            "الخطة المدة الاستخدامات\n\n"
            "أمثلة:\n"
            "basic 30d 1\n"
            "pro 12h 1\n"
            "vip permanent 1\n"
            "basic 7d 5\n\n"
            "الخطة: basic / pro / vip / lifetime\n"
            "المدة: رقم + d (أيام) أو h (ساعات) أو permanent (دايم)\n"
            "الاستخدامات: رقم (1 = لمرة وحدة)"
        )
        await cq.message.edit_text(text, reply_markup=back_button("admin_codes"))
        await cq.answer()
    elif data.startswith("admin_code_plan:"):
        plan = data.split(":")[1]
        await state.update_data(code_plan=plan)
        await state.set_state(AdminStates.add_code_duration)
        await cq.message.edit_text(f"أدخل مدة الكود بالأيام للخطة {plan}:", reply_markup=back_button("admin_codes"))
        await cq.answer()
    elif data.startswith("admin_code_details:"):
        await _admin_code_details(cq, int(data.split(":")[1]))
    elif data.startswith("admin_code_disable:"):
        await _admin_code_disable(cq, int(data.split(":")[1]))
    elif data == "admin_indicators":
        await _admin_indicators(cq)
    elif data == "admin_sync_symbols":
        await _admin_sync_symbols(cq)
    elif data == "admin_backup":
        await _admin_backup(cq)
    elif data == "admin_update_notify":
        await state.set_state(AdminStates.broadcast_text)
        await cq.message.edit_text(
            "📢 إشعار تحديث البوت\n\n"
            "أرسل نص التحديث ليصل لكل المستخدمين:\n\n"
            "مثال:\n"
            "✅ تم تحديث البوت!\n"
            "الميزات الجديدة:\n- ...\n- ...",
            reply_markup=back_button("admin_panel"),
        )
        await cq.answer()
    elif data == "admin_monthly_stats":
        await _admin_monthly_stats(cq)
    elif data == "admin_coupons":
        await _admin_coupons_menu(cq)
    elif data.startswith("admin_coupon_disable:"):
        await _admin_coupon_disable(cq, int(data.split(":")[1]))
    elif data.startswith("admin_user_page:"):
        await _admin_users_page(cq, int(data.split(":")[1]))
    elif data == "admin_health":
        await _admin_health(cq)
    elif data == "admin_prediction_access":
        await _admin_prediction_access(cq)
    elif data == "admin_prediction_grant":
        await state.set_state(AdminStates.prediction_grant_id)
        await cq.message.edit_text("🔮 أرسل Telegram ID لإضافته لصلاحية الإشارات الخاصة:", reply_markup=back_button("admin_prediction_access"))
        await cq.answer()
    elif data == "admin_prediction_revoke":
        await state.set_state(AdminStates.prediction_revoke_id)
        await cq.message.edit_text("🔮 أرسل Telegram ID لحذف صلاحية الإشارات الخاصة:", reply_markup=back_button("admin_prediction_access"))
        await cq.answer()
    elif data == "admin_symbols":
        await _admin_symbols_menu(cq)
    elif data.startswith("admin_sym_page:"):
        await _admin_symbols_page(cq, data.split(":")[1] if len(data.split(":")) > 1 else None, int(data.split(":")[-1]))
    elif data.startswith("admin_sym_toggle:"):
        await _admin_sym_toggle(cq, int(data.split(":")[1]))
    elif data.startswith("admin_sym_popular:"):
        await _admin_sym_popular(cq, int(data.split(":")[1]))
    elif data.startswith("admin_sym_market:"):
        parts = data.split(":")
        market = parts[1]
        page = int(parts[2]) if len(parts) > 2 else 1
        await _admin_symbols_page(cq, market, page)
    elif data.startswith("admin_sym_view:"):
        await _admin_sym_view(cq, int(data.split(":")[1]))
    elif data.startswith("admin_sym_edit_field:"):
        parts = data.split(":")
        await state.update_data(sym_id=int(parts[1]), sym_field=parts[2])
        await state.set_state(AdminStates.sym_edit_value)
        field_names = {"name_ar": "الاسم العربي", "name_en": "الاسم الإنجليزي", "sector": "القطاع", "symbol": "الرمز", "yahoo_symbol": "رمز ياهو"}
        fname = field_names.get(parts[2], parts[2])
        await cq.message.edit_text(f"✏️ أدخل القيمة الجديدة لـ {fname}:", reply_markup=back_button("admin_panel"))
        await cq.answer()
    elif data == "admin_sym_add":
        await state.set_state(AdminStates.sym_add_market)
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        builder.button(text="📈 السوق السعودي", callback_data="admin_sym_add_market:SAUDI")
        builder.button(text="🇺🇸 السوق الأمريكي", callback_data="admin_sym_add_market:US")
        builder.button(text="₿ العملات الرقمية", callback_data="admin_sym_add_market:CRYPTO")
        builder.button(text="↩️ رجوع", callback_data="admin_symbols")
        builder.adjust(2)
        await cq.message.edit_text("اختر السوق للرمز الجديد:", reply_markup=builder.as_markup())
        await cq.answer()
    elif data.startswith("admin_sym_add_market:"):
        market = data.split(":")[1]
        await state.update_data(sym_market=market)
        await state.set_state(AdminStates.sym_add_symbol)
        await cq.message.edit_text(f"أدخل الرمز (مثال: 2222.SR, AAPL, BTCUSDT):", reply_markup=back_button("admin_symbols"))
        await cq.answer()
    elif data.startswith("admin_sym_export:"):
        await _admin_sym_export(cq, data.split(":")[1])
    elif data == "admin_sym_import":
        text = "📥 **استيراد رموز من CSV**\n\nأرسل ملف CSV بالتنسيق:\n`symbol,yahoo_symbol,name_ar,name_en,sector,exchange,currency`\n\nيجب أن يكون السطر الأول عناوين الأعمدة."
        await cq.message.edit_text(text, reply_markup=back_button("admin_symbols"))
        _user_context[cq.from_user.id] = {"context": "admin_sym_import"}
        await cq.answer()
    else:
        await cq.answer("تحت التطوير", show_alert=True)


PAGE_SIZE = 10


async def _admin_users(cq: CallbackQuery):
    await _admin_users_page(cq, 1)


async def _admin_users_page(cq: CallbackQuery, page: int):
    async with get_session() as session:
        total = (await session.execute(select(func.count(User.id)))).scalar() or 0
        offset = (page - 1) * PAGE_SIZE
        result = await session.execute(
            select(User).order_by(User.id.desc()).offset(offset).limit(PAGE_SIZE)
        )
        users = result.scalars().all()

        text = f"👥 **المستخدمون** (صفحة {page}):\n\n"
        for u in users:
            status = "✅" if u.is_active else "⛔"
            ban = "🚫" if u.is_banned else ""
            text += f"{status}{ban} ID: {u.telegram_id} | {u.first_name[:15]} | {u.plan}\n"
        text += f"\nإجمالي: {total}\nللبحث أرسل ID المستخدم"

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    if page > 1:
        builder.button(text="⬅️ السابق", callback_data=f"admin_user_page:{page - 1}")
    if offset + PAGE_SIZE < total:
        builder.button(text="التالي ➡️", callback_data=f"admin_user_page:{page + 1}")
    builder.button(text="↩️ رجوع", callback_data="admin_panel")
    builder.adjust(2)
    await cq.message.edit_text(text, reply_markup=builder.as_markup())
    await cq.answer()


async def _admin_user_view(cq: CallbackQuery, telegram_id: int):
    async with get_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        u = result.scalar_one_or_none()
        if not u:
            return await cq.answer("المستخدم غير موجود", show_alert=True)
        text = (
            f"👤 معلومات المستخدم\n"
            f"ID: {u.telegram_id}\n"
            f"الاسم: {u.first_name}\n"
            f"اليوزر: @{u.username or '—'}\n"
            f"الخطة: {u.plan}\n"
            f"الاشتراك: {u.subscription_start} → {u.subscription_end}\n"
            f"الحالة: {'نشط' if u.is_active else 'غير نشط'}{' | محظور' if u.is_banned else ''}\n"
            f"الفحوصات اليوم: {u.scans_today}\n"
            f"آخر دخول: {u.last_active}"
        )
    await cq.message.edit_text(text, reply_markup=admin_users_actions(telegram_id))
    await cq.answer()


async def _admin_user_ban(cq: CallbackQuery, telegram_id: int):
    async with get_session() as session:
        async with session.begin():
            result = await session.execute(select(User).where(User.telegram_id == telegram_id))
            u = result.scalar_one_or_none()
            if u:
                u.is_banned = True
    await log_admin(cq.from_user.id, f"ban_{telegram_id}")
    await cq.answer("✅ تم الحظر", show_alert=True)
    await _admin_user_view(cq, telegram_id)


async def _admin_user_unban(cq: CallbackQuery, telegram_id: int):
    async with get_session() as session:
        async with session.begin():
            result = await session.execute(select(User).where(User.telegram_id == telegram_id))
            u = result.scalar_one_or_none()
            if u:
                u.is_banned = False
    await log_admin(cq.from_user.id, f"unban_{telegram_id}")
    await cq.answer("✅ تم فك الحظر", show_alert=True)
    await _admin_user_view(cq, telegram_id)


async def _admin_subs(cq: CallbackQuery):
    async with get_session() as session:
        total = (await session.execute(select(func.count(User.id)))).scalar()
        now_utc = datetime.now(timezone.utc)
        active = (await session.execute(select(func.count(User.id)).where(User.subscription_end > now_utc))).scalar()
        plan_counts = {}
        for p in ["free", "basic", "pro", "vip", "lifetime"]:
            cnt = (await session.execute(select(func.count(User.id)).where(User.plan == p))).scalar()
            plan_counts[p] = cnt
        rev_result = await session.execute(select(func.sum(Payment.amount)).where(Payment.status == "completed"))
        revenue = rev_result.scalar() or 0
    text = (
        "💳 **الاشتراكات**\n\n"
        f"إجمالي المستخدمين: {total}\n"
        f"الاشتراكات النشطة: {active}\n\n"
        f"Free: {plan_counts['free']}\n"
        f"Basic: {plan_counts['basic']}\n"
        f"Pro: {plan_counts['pro']}\n"
        f"VIP: {plan_counts['vip']}\n"
        f"Lifetime: {plan_counts['lifetime']}\n\n"
        f"إجمالي الإيرادات: {revenue:.2f} SAR"
    )
    await cq.message.edit_text(text, reply_markup=back_button("admin_panel"))
    await cq.answer()


async def _admin_codes_menu(cq: CallbackQuery):
    async with get_session() as session:
        result = await session.execute(select(ActivationCode).order_by(ActivationCode.id.desc()).limit(12))
        codes = result.scalars().all()
        total = (await session.execute(select(func.count(ActivationCode.id)))).scalar() or 0
        ready = (
            await session.execute(
                select(func.count(ActivationCode.id)).where(
                    ActivationCode.is_active == True,
                    ActivationCode.uses < ActivationCode.max_uses,
                )
            )
        ).scalar() or 0

    lines = [
        "🔑 <b>أكواد التفعيل</b>",
        f"الإجمالي: {total} | الجاهزة: {ready}",
        "",
    ]
    if not codes:
        lines.append("لا توجد أكواد حتى الآن.")
    else:
        for index, c in enumerate(codes, start=1):
            icon, status = _activation_code_status(c)
            remaining = "مفتوح" if c.max_uses <= 0 else max(0, c.max_uses - c.uses)
            lines.extend(
                [
                    f"{index}. {icon} <code>{c.code}</code>",
                    f"   الخطة: {_activation_plan_label(c.plan)} | المدة: {_activation_duration_label(c)}",
                    f"   الاستخدام: {c.uses}/{c.max_uses} | المتبقي: {remaining} | الحالة: {status}",
                    f"   الإنشاء: {_activation_created_label(c)}",
                    "",
                ]
            )
    lines.append("اختر إجراء:")

    from bot.keyboards.main import back_button
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ إنشاء كود", callback_data="admin_codes_create")
    for c in codes[:8]:
        label = "تعطيل" if c.is_active else "تفعيل"
        builder.button(text=f"تفاصيل {c.code}", callback_data=f"admin_code_details:{c.id}")
        builder.button(text=f"{label} {c.code}", callback_data=f"admin_code_disable:{c.id}")
    builder.button(text="↩️ رجوع", callback_data="admin_panel")
    builder.adjust(1, 2)
    await cq.message.edit_text("\n".join(lines)[:3900], reply_markup=builder.as_markup())
    await cq.answer()


async def _admin_code_disable(cq: CallbackQuery, code_id: int):
    async with get_session() as session:
        async with session.begin():
            result = await session.execute(select(ActivationCode).where(ActivationCode.id == code_id))
            c = result.scalar_one_or_none()
            if c:
                c.is_active = not c.is_active
    await cq.answer("✅ تم التحديث", show_alert=True)
    await _admin_codes_menu(cq)


async def _admin_code_details(cq: CallbackQuery, code_id: int):
    async with get_session() as session:
        code_result = await session.execute(select(ActivationCode).where(ActivationCode.id == code_id))
        code = code_result.scalar_one_or_none()
        if not code:
            await cq.answer("الكود غير موجود", show_alert=True)
            return

        result = await session.execute(
            select(ActivationCodeRedemption, User)
            .join(User, User.id == ActivationCodeRedemption.user_id)
            .where(ActivationCodeRedemption.activation_code_id == code_id)
            .order_by(ActivationCodeRedemption.created_at.desc())
            .limit(20)
        )
        rows = result.all()

    icon, status = _activation_code_status(code)
    lines = [
        f"🔑 <b>تفاصيل الكود</b>",
        f"{icon} <code>{code.code}</code>",
        f"الخطة: {_activation_plan_label(code.plan)} | المدة: {_activation_duration_label(code)}",
        f"الاستخدام: {code.uses}/{code.max_uses} | الحالة: {status}",
        "",
        "👥 المستخدمون:",
    ]

    if not rows:
        lines.append("لا توجد استخدامات مسجلة لهذا الكود حتى الآن.")
        if code.uses:
            lines.append("ملاحظة: قد يكون هذا الاستخدام قبل تحديث سجل التفاصيل.")
    else:
        for index, (redemption, user) in enumerate(rows, start=1):
            remaining, sub_status = _remaining_label(redemption.subscription_end)
            username = f"@{user.username}" if user.username else "بدون يوزر"
            name = user.first_name or str(user.telegram_id)
            lines.extend(
                [
                    f"{index}. {name} | {username}",
                    f"   ID: <code>{user.telegram_id}</code>",
                    f"   التفعيل: {_format_dt(redemption.created_at)}",
                    f"   الانتهاء: {_format_dt(redemption.subscription_end)}",
                    f"   المتبقي: {remaining} | {sub_status}",
                    "",
                ]
            )

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 تحديث", callback_data=f"admin_code_details:{code_id}")
    builder.button(text="↩️ رجوع للأكواد", callback_data="admin_codes")
    builder.adjust(1)
    await cq.message.edit_text("\n".join(lines)[:3900], reply_markup=builder.as_markup())
    await cq.answer()


async def _admin_affiliates(cq: CallbackQuery):
    bot_username = (await cq.bot.get_me()).username
    async with get_session() as session:
        result = await session.execute(select(AffiliatePartner).order_by(AffiliatePartner.id.desc()).limit(12))
        partners = result.scalars().all()

        rows = []
        for partner in partners:
            users_count = (
                await session.execute(select(func.count(User.id)).where(User.affiliate_partner_id == partner.id))
            ).scalar() or 0
            due = (
                await session.execute(
                    select(func.sum(AffiliateCommission.commission_amount)).where(
                        AffiliateCommission.partner_id == partner.id,
                        AffiliateCommission.status == "due",
                    )
                )
            ).scalar() or 0
            paid = (
                await session.execute(
                    select(func.sum(AffiliateCommission.commission_amount)).where(
                        AffiliateCommission.partner_id == partner.id,
                        AffiliateCommission.status == "paid",
                    )
                )
            ).scalar() or 0
            rows.append((partner, users_count, float(due or 0), float(paid or 0)))

    lines = ["🤝 <b>نظام الشركاء</b>", ""]
    if not rows:
        lines.append("لا يوجد شركاء حتى الآن.")
    else:
        for index, (partner, users_count, due, paid) in enumerate(rows, start=1):
            link = f"https://t.me/{bot_username}?start=aff_{partner.code}"
            status = "نشط" if partner.is_active else "متوقف"
            lines.extend(
                [
                    f"{index}. <b>{partner.name}</b> | {status}",
                    f"   الكود: <code>{partner.code}</code> | العمولة: {partner.commission_percent:.0f}%",
                    f"   المستخدمون: {users_count} | المستحق: {due:.2f} SAR | المدفوع: {paid:.2f} SAR",
                    f"   الرابط: {link}",
                    "",
                ]
            )

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    builder.button(text="➕ إنشاء شريك", callback_data="admin_affiliate_create")
    for partner, _users_count, due, _paid in rows[:6]:
        if due > 0:
            builder.button(text=f"✅ دفع {partner.name}", callback_data=f"admin_affiliate_paid:{partner.id}")
    builder.button(text="↩️ رجوع", callback_data="admin_panel")
    builder.adjust(1)
    await cq.message.edit_text("\n".join(lines)[:3900], reply_markup=builder.as_markup())
    await cq.answer()


async def _admin_affiliate_mark_paid(cq: CallbackQuery, partner_id: int):
    async with get_session() as session:
        result = await session.execute(
            select(AffiliateCommission).where(
                AffiliateCommission.partner_id == partner_id,
                AffiliateCommission.status == "due",
            )
        )
        items = result.scalars().all()
        total = sum(float(item.commission_amount or 0) for item in items)
        for item in items:
            item.status = "paid"
        await session.commit()
    await cq.answer(f"تم تحديد {total:.2f} SAR كمدفوعة", show_alert=True)
    await _admin_affiliates(cq)


async def _admin_stats(cq: CallbackQuery):
    async with get_session() as session:
        today = settings.today()
        scans_today = (await session.execute(
            select(func.count()).select_from(ScanLog).where(func.date(ScanLog.created_at) == today)
        )).scalar() or 0
        errors_today = (await session.execute(
            select(func.count()).select_from(ErrorLog).where(func.date(ErrorLog.created_at) == today)
        )).scalar() or 0
        total_scans = (await session.execute(select(func.count()).select_from(ScanLog))).scalar() or 0
        total_users = (await session.execute(select(func.count(User.id)))).scalar() or 0
    text = (
        "📊 **إحصائيات النظام**\n\n"
        f"إجمالي المستخدمين: {total_users}\n"
        f"إجمالي الفحوصات: {total_scans}\n"
        f"فحوصات اليوم: {scans_today}\n"
        f"أخطاء اليوم: {errors_today}\n"
    )
    await cq.message.edit_text(text, reply_markup=back_button("admin_panel"))
    await cq.answer()


async def _admin_health(cq: CallbackQuery):
    text = await build_admin_health_report()
    await cq.message.edit_text(text, reply_markup=back_button("admin_panel"))
    await cq.answer()


async def _admin_prediction_access(cq: CallbackQuery):
    access_items = await list_feature_access(PREDICTION_FEATURE)
    lines = [
        "🔮 صلاحيات الإشارات الخاصة",
        "",
        "المصرح لهم:",
    ]
    if access_items:
        for item in access_items[:30]:
            lines.append(f"• {item.telegram_id}")
    else:
        lines.append("لا يوجد مستخدمون مصرح لهم حالياً.")

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    builder.button(text="➕ إضافة مستخدم", callback_data="admin_prediction_grant")
    builder.button(text="➖ حذف مستخدم", callback_data="admin_prediction_revoke")
    builder.button(text="↩️ رجوع", callback_data="admin_panel")
    builder.adjust(2, 1)
    await cq.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())
    await cq.answer()


async def _admin_settings(cq: CallbackQuery):
    async with get_session() as session:
        result = await session.execute(select(SystemSettings))
        s = result.scalars().all()
        text = "⚙️ **الإعدادات**\n\n"
        for item in s:
            text += f"• {item.key}: {item.value}\n"
        text += "\nللحصول على الإعدادات الجديدة أعد تشغيل البوت"
    await cq.message.edit_text(text, reply_markup=back_button("admin_panel"))
    await cq.answer()


async def _admin_markets(cq: CallbackQuery):
    async with get_session() as session:
        result = await session.execute(select(MarketSettings))
        markets = result.scalars().all()
        if not markets:
            async with session.begin():
                for m in ["saudi", "us", "crypto"]:
                    session.add(MarketSettings(market=m, is_enabled=True))
                await session.flush()
            result = await session.execute(select(MarketSettings))
            markets = result.scalars().all()
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    for m in markets:
        status = "✅ مفعل" if m.is_enabled else "❌ معطل"
        builder.button(text=f"{m.market}: {status}", callback_data=f"admin_market_toggle:{m.market}")
    builder.button(text="↩️ رجوع", callback_data="admin_panel")
    builder.adjust(1)
    await cq.message.edit_text("📈 **الأسواق**\nاضغط للتبديل:", reply_markup=builder.as_markup())
    await cq.answer()


async def _admin_market_toggle(cq: CallbackQuery, market: str):
    async with get_session() as session:
        async with session.begin():
            result = await session.execute(select(MarketSettings).where(MarketSettings.market == market))
            m = result.scalar_one_or_none()
            if m:
                m.is_enabled = not m.is_enabled
    await log_admin(cq.from_user.id, f"toggle_market_{market}")
    await _admin_markets(cq)


async def _admin_logs(cq: CallbackQuery):
    async with get_session() as session:
        result = await session.execute(select(ErrorLog).order_by(ErrorLog.id.desc()).limit(20))
        logs = result.scalars().all()
        text = "📜 **السجلات** (آخر 20 خطأ)\n\n"
        if not logs:
            text += "لا توجد أخطاء"
        for log in logs:
            text += f"• [{log.created_at}] {log.source}: {log.message[:100]}\n"
    await cq.message.edit_text(text, reply_markup=back_button("admin_panel"))
    await cq.answer()


async def _admin_maintenance(cq: CallbackQuery):
    async with get_session() as session:
        async with session.begin():
            result = await session.execute(select(SystemSettings).where(SystemSettings.key == "maintenance"))
            s = result.scalar_one_or_none()
            if s:
                s.value = "false" if s.value == "true" else "true"
            else:
                session.add(SystemSettings(key="maintenance", value="true"))
    await log_admin(cq.from_user.id, "toggle_maintenance")
    await cq.answer("✅ تم التبديل", show_alert=True)
    await _admin_settings(cq)


@router.message(AdminStates.broadcast_text)
async def handle_broadcast_text(msg: Message, state: FSMContext):
    text = msg.text
    await state.update_data(broadcast_text=text)
    await msg.answer(
        f"📨 سيتم إرسال هذه الرسالة لجميع المستخدمين:\n\n{text}\n\nللتأكيد أرسل /confirm",
        reply_markup=back_button("admin_panel"),
    )
    await state.set_state(AdminStates.broadcast_text)


@router.message(Command("confirm"), StateFilter(AdminStates.broadcast_text))
async def confirm_broadcast(msg: Message, state: FSMContext):
    data = await state.get_data()
    text = data.get("broadcast_text", "")
    async with get_session() as session:
        result = await session.execute(select(User).where(User.is_banned == False))
        users = result.scalars().all()
    bot = Bot.get_current()
    sent = 0
    for u in users:
        try:
            await bot.send_message(u.telegram_id, f"📨 رسالة إدارية\n\n{text}")
            sent += 1
        except Exception:
            pass
    await msg.answer(f"✅ تم الإرسال لـ {sent} مستخدم")
    await log_admin(msg.from_user.id, f"broadcast_{sent}")
    await state.clear()


@router.message(AdminStates.extend_days)
async def handle_extend_days(msg: Message, state: FSMContext):
    try:
        days = int(msg.text)
    except ValueError:
        return await msg.answer("❌ الرجاء إدخال رقم صحيح")
    data = await state.get_data()
    telegram_id = data.get("target_user_id")
    async with get_session() as session:
        async with session.begin():
            result = await session.execute(select(User).where(User.telegram_id == telegram_id))
            u = result.scalar_one_or_none()
            if u:
                sub_end = u.subscription_end
                if sub_end:
                    if sub_end.tzinfo is None:
                        sub_end = sub_end.replace(tzinfo=timezone.utc)
                    if sub_end > datetime.now(timezone.utc):
                        u.subscription_end = sub_end + timedelta(days=days)
                    else:
                        u.subscription_end = datetime.now(timezone.utc) + timedelta(days=days)
                else:
                    u.subscription_end = datetime.now(timezone.utc) + timedelta(days=days)
    await log_admin(msg.from_user.id, f"extend_{telegram_id}_{days}d")
    await msg.answer(f"✅ تم تمديد اشتراك المستخدم {days} يوم")
    await state.clear()


@router.message(AdminStates.add_code_plan)
async def handle_create_code_all_in_one(msg: Message, state: FSMContext):
    text = msg.text.strip()

    if text.startswith("/"):
        await state.clear()
        if text == "/admin":
            if not is_admin(msg.from_user.id):
                return
            await msg.answer("🔧 لوحة التحكم", reply_markup=admin_menu())
        return

    parts = text.split()

    if len(parts) < 3:
        await msg.answer(
            "❌ الصيغة خاطئة.\n\nاكتب: الخطة المدة الاستخدامات\nمثال: basic 30d 1\n\n"
            "الخطة: basic / pro / vip / lifetime\n"
            "المدة: 30d (أيام) أو 12h (ساعات) أو permanent (دايم)\n"
            "الاستخدامات: رقم (1 = لمرة وحدة)\n\n"
            "أو أرسل /admin للرجوع للقائمة"
        )
        return

    plan = parts[0].lower()
    duration_str = parts[1].lower()
    uses_str = parts[2]

    valid_plans = ["basic", "pro", "vip", "lifetime"]
    if plan not in valid_plans:
        await msg.answer(f"❌ الخطة خاطئة. اختر واحدة: {', '.join(valid_plans)}")
        return

    try:
        max_uses = int(uses_str)
        if max_uses < 1:
            raise ValueError
    except ValueError:
        await msg.answer("❌ الاستخدامات لازم رقم (1 = لمرة وحدة)")
        return

    duration_minutes = 0
    if duration_str == "permanent" or duration_str == "دايم":
        duration_days = 99999
        duration_label = "دايم"
    elif duration_str.endswith("h"):
        try:
            hours = int(duration_str[:-1])
            if hours < 1:
                raise ValueError
            duration_days = 0
            duration_minutes = hours * 60
            duration_label = f"{hours} ساعة"
        except ValueError:
            await msg.answer("❌ المدة بالساعات خاطئة. مثال: 12h")
            return
    elif duration_str.endswith("d"):
        try:
            days = int(duration_str[:-1])
            if days < 1:
                raise ValueError
            duration_days = days
            duration_minutes = days * 24 * 60
            duration_label = f"{days} يوم"
        except ValueError:
            await msg.answer("❌ المدة بالأيام خاطئة. مثال: 30d")
            return
    else:
        await msg.answer("❌ المدة خاطئة. استخدم: 30d (أيام) أو 12h (ساعات) أو permanent (دايم)")
        return

    code = _code()
    async with get_session() as session:
        async with session.begin():
            result = await session.execute(select(User).where(User.telegram_id == msg.from_user.id))
            admin = result.scalar_one_or_none()
            ac = ActivationCode(
                code=code,
                plan=plan,
                duration_days=duration_days,
                duration_minutes=duration_minutes,
                max_uses=max_uses,
                uses=0,
                is_active=True,
                created_by=admin.id if admin else 0,
            )
            session.add(ac)

    await log_admin(msg.from_user.id, f"create_code_{plan}_{duration_label}")
    await msg.answer(
        f"✅ تم إنشاء الكود!\n\n"
        f"الكود: <code>{code}</code>\n"
        f"الخطة: {plan}\n"
        f"المدة: {duration_label}\n"
        f"الاستخدامات: {max_uses}\n\n"
        f"أرسل هذا الكود للمستخدم لتفعيل اشتراكه."
    )
    await state.clear()


@router.message(AdminStates.user_search)
async def handle_user_search(msg: Message, state: FSMContext):
    query = msg.text.strip()
    async with get_session() as session:
        try:
            tid = int(query)
            result = await session.execute(select(User).where(User.telegram_id == tid))
            u = result.scalar_one_or_none()
        except ValueError:
            result = await session.execute(
                select(User).where(
                    User.username.ilike(f"%{query}%")
                ).limit(10)
            )
            users = result.scalars().all()
            if len(users) == 0:
                return await msg.answer("❌ لا يوجد مستخدم بهذا الاسم.")
            u = users[0] if len(users) == 1 else None

        if not u:
            return await msg.answer("❌ المستخدم غير موجود.", reply_markup=back_button("admin_panel"))

    from bot.keyboards.main import admin_users_actions
    text = (
        f"👤 معلومات المستخدم\n"
        f"ID: {u.telegram_id}\n"
        f"الاسم: {u.first_name}\n"
        f"اليوزر: @{u.username or '—'}\n"
        f"الخطة: {u.plan}\n"
        f"الاشتراك: {u.subscription_start} → {u.subscription_end}\n"
        f"الحالة: {'نشط' if u.is_active else 'غير نشط'}{' | محظور' if u.is_banned else ''}\n"
        f"الفحوصات اليوم: {u.scans_today}\n"
        f"التقارير اليومية: {'مفعلة' if getattr(u, 'daily_report', True) else 'معطلة'}\n"
        f"آخر دخول: {u.last_active}"
    )
    await msg.answer(text, reply_markup=admin_users_actions(u.telegram_id))
    await state.clear()


@router.message(AdminStates.add_partner)
async def handle_add_partner(msg: Message, state: FSMContext):
    text = msg.text.strip()
    if text.startswith("/"):
        await state.clear()
        return await msg.answer("تم الإلغاء.", reply_markup=admin_menu())

    parts = [part.strip() for part in text.split("|")]
    if len(parts) < 2:
        await msg.answer("❌ الصيغة خاطئة. مثال:\nقروب الأسهم | 30 | 123456789")
        return

    name = parts[0]
    try:
        percent = float(parts[1])
        if percent <= 0 or percent > 100:
            raise ValueError
    except ValueError:
        await msg.answer("❌ نسبة العمولة لازم تكون رقم بين 1 و 100.")
        return

    telegram_id = None
    if len(parts) >= 3 and parts[2]:
        try:
            telegram_id = int(parts[2])
        except ValueError:
            await msg.answer("❌ آيدي التليقرام لازم يكون رقم.")
            return

    partner = await create_affiliate_partner(name, telegram_id, percent)
    bot_username = (await msg.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start=aff_{partner.code}"
    await state.clear()
    await msg.answer(
        "✅ تم إنشاء الشريك\n\n"
        f"الاسم: {partner.name}\n"
        f"النسبة: {partner.commission_percent:.0f}%\n"
        f"الكود: <code>{partner.code}</code>\n"
        f"الرابط:\n{link}",
        reply_markup=back_button("admin_affiliates"),
    )


async def _admin_indicators(cq: CallbackQuery):
    text = (
        "📋 **المؤشرات الفنية المتاحة:**\n\n"
        "• RSI (14) - القوة النسبية\n"
        "• MACD (12, 26, 9) - التقاطع\n"
        "• EMA (20, 50, 200) - المتوسطات\n"
        "• SMA (20, 50, 200) - المتوسطات البسيطة\n"
        "• Bollinger Bands (20, 2) - التذبذب\n"
        "• ATR (14) - التقلب\n"
        "• Volume (20) - الحجم النسبي\n"
        "• Support/Resistance - الدعم والمقاومة\n"
        "• Trend Detection - اكتشاف الاتجاه\n\n"
        "🔧 التحليل الفني يعمل تلقائياً على جميع الرموز."
    )
    await cq.message.edit_text(text, reply_markup=back_button("admin_panel"))
    await cq.answer()


async def _admin_sync_symbols(cq: CallbackQuery):
    await cq.answer("بدأ تحديث الرموز، قد يستغرق دقيقة...", show_alert=True)
    await cq.message.edit_text("🌍 جاري تحديث رموز الأمريكي والكريبتو...\n\nانتظر شوي.")
    try:
        from services.symbol_sync import sync_symbol_universe

        results = await sync_symbol_universe()
        lines = ["✅ تم تحديث الرموز\n"]
        for item in results:
            lines.append(
                f"{item['market']}: تم جلب {item['fetched']} | جديد {item['added']}"
            )
        lines.append("\nبعد التحديث جرّب: الأمريكي تحت 150 أو الكريبتو تحت 1")
        await cq.message.edit_text("\n".join(lines), reply_markup=back_button("admin_panel"))
    except Exception as exc:
        await cq.message.edit_text(
            f"❌ تعذر تحديث الرموز حالياً:\n{str(exc)[:500]}",
            reply_markup=back_button("admin_panel"),
        )


async def _admin_backup(cq: CallbackQuery):
    import csv
    import io
    from aiogram.types import BufferedInputFile

    try:
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow(["Type", "ID", "Telegram ID", "Username", "Name", "Plan", "Sub Start", "Sub End", "Active", "Banned", "Scans Today", "Referrals"])

        async with get_session() as session:
            result = await session.execute(select(User).order_by(User.id))
            users = result.scalars().all()

            for u in users:
                writer.writerow([
                    "USER", u.id, u.telegram_id, u.username or "",
                    u.first_name or "", u.plan,
                    str(u.subscription_start) if u.subscription_start else "",
                    str(u.subscription_end) if u.subscription_end else "",
                    u.is_active, u.is_banned, u.scans_today,
                    getattr(u, 'referrals_count', 0) or 0,
                ])

            result = await session.execute(select(ActivationCode).order_by(ActivationCode.id.desc()))
            codes = result.scalars().all()

            for c in codes:
                writer.writerow([
                    "CODE", c.id, "", "", "", c.plan,
                    "", "", c.is_active, "", c.uses, c.max_uses,
                ])

        csv_data = output.getvalue()
        buf = io.BytesIO(csv_data.encode("utf-8-sig"))
        buf.seek(0)

        doc = BufferedInputFile(buf.read(), filename=f"backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.csv")

        await cq.message.answer_document(doc, caption=f"💾 نسخة احتياطية\nالمستخدمين: {len(users)}\nالأكواد: {len(codes)}")
        await cq.answer("✅ تم إنشاء النسخة الاحتياطية", show_alert=True)

    except Exception as e:
        await cq.answer(f"❌ خطأ: {str(e)[:100]}", show_alert=True)


async def _admin_monthly_stats(cq: CallbackQuery):
    try:
        from datetime import timedelta
        now_utc = datetime.now(timezone.utc)
        month_ago = now_utc - timedelta(days=30)

        async with get_session() as session:
            total_users = (await session.execute(select(func.count(User.id)))).scalar() or 0

            new_users = (await session.execute(
                select(func.count(User.id)).where(User.created_at >= month_ago)
            )).scalar() or 0

            active_subs = (await session.execute(
                select(func.count(User.id)).where(
                    User.plan != "free",
                    User.subscription_end > now_utc,
                )
            )).scalar() or 0

            total_scans = (await session.execute(
                select(func.count(ScanLog.id)).where(ScanLog.created_at >= month_ago)
            )).scalar() or 0

            top_symbols = (await session.execute(
                select(ScanLog.symbol, func.count(ScanLog.id).label("cnt"))
                .where(ScanLog.created_at >= month_ago)
                .group_by(ScanLog.symbol)
                .order_by(func.count(ScanLog.id).desc())
                .limit(5)
            )).all()

            plan_counts = {}
            for p in ["free", "basic", "pro", "vip", "lifetime"]:
                cnt = (await session.execute(
                    select(func.count(User.id)).where(User.plan == p)
                )).scalar() or 0
                plan_counts[p] = cnt

        plan_names = {"free": "مجاني", "basic": "أساسي", "pro": "احترافي", "vip": "VIP", "lifetime": "مدى الحياة"}

        text = (
            "📊 إحصائيات آخر 30 يوم\n\n"
            f"👥 إجمالي المستخدمين: {total_users}\n"
            f"🆕 مستخدمين جدد: {new_users}\n"
            f"✅ اشتراكات نشطة: {active_subs}\n"
            f"📊 إجمالي الفحوصات: {total_scans}\n\n"
            "📋 توزيع الباقات:\n"
        )
        for p, cnt in plan_counts.items():
            text += f"  {plan_names.get(p, p)}: {cnt}\n"

        if top_symbols:
            text += "\n🏆 أكثر الرموز فحصاً:\n"
            for sym, cnt in top_symbols:
                text += f"  {sym}: {cnt} فحص\n"

        text += "\n💰 للمتابعة: @hidanx11"

        await cq.message.edit_text(text, reply_markup=back_button("admin_panel"))
        await cq.answer()

    except Exception as e:
        await cq.answer(f"خطأ: {str(e)[:100]}", show_alert=True)


async def _admin_coupons_menu(cq: CallbackQuery):
    async with get_session() as session:
        result = await session.execute(select(Coupon).order_by(Coupon.id.desc()).limit(10))
        coupons = result.scalars().all()
        text = "🎫 **كوبونات الخصم**\n\n"
        if not coupons:
            text += "لا توجد كوبونات."
        for c in coupons:
            status = "✅" if c.is_active else "❌"
            text += f"{status} {c.code} | خصم %{c.discount_percent:.0f} | {c.uses}/{c.max_uses}\n"
    text += "\nاختر إجراء:"
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ إنشاء كوبون", callback_data="admin_coupon_create")
    builder.button(text="↩️ رجوع", callback_data="admin_panel")
    builder.adjust(1)
    await cq.message.edit_text(text, reply_markup=builder.as_markup())
    await cq.answer()


async def _admin_coupon_disable(cq: CallbackQuery, coupon_id: int):
    async with get_session() as session:
        async with session.begin():
            result = await session.execute(select(Coupon).where(Coupon.id == coupon_id))
            c = result.scalar_one_or_none()
            if c:
                c.is_active = not c.is_active
    await cq.answer("✅ تم التحديث", show_alert=True)
    await _admin_coupons_menu(cq)


@router.message(AdminStates.add_coupon_discount)
async def handle_coupon_discount(msg: Message, state: FSMContext):
    try:
        discount = float(msg.text)
        if discount < 1 or discount > 99:
            raise ValueError
    except ValueError:
        return await msg.answer("❌ الرجاء إدخال رقم بين 1 و 99")
    await state.update_data(coupon_discount=discount)
    await state.set_state(AdminStates.add_coupon_max_uses)
    await msg.answer("أدخل الحد الأقصى للاستخدامات (1-1000):", reply_markup=back_button("admin_panel"))


@router.message(AdminStates.add_coupon_max_uses)
async def handle_coupon_max_uses(msg: Message, state: FSMContext):
    try:
        max_uses = int(msg.text)
        if max_uses < 1 or max_uses > 1000:
            raise ValueError
    except ValueError:
        return await msg.answer("❌ الرجاء إدخال رقم بين 1 و 1000")
    data = await state.get_data()
    code = _code(8)
    async with get_session() as session:
        async with session.begin():
            coupon = Coupon(
                code=code,
                discount_percent=data["coupon_discount"],
                max_uses=max_uses,
            )
            session.add(coupon)
    await log_admin(msg.from_user.id, f"create_coupon_%{data['coupon_discount']}")
    await msg.answer(
        f"✅ تم إنشاء الكوبون:\n\n`{code}`\n\nالخصم: %{data['coupon_discount']:.0f}\nالاستخدامات: {max_uses}"
    )
    await state.clear()


async def _admin_symbols_menu(cq: CallbackQuery):
    text = "🔣 **إدارة الرموز**\n\nاختر السوق للتصفح والإدارة:"
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="📈 السوق السعودي", callback_data="admin_sym_market:SAUDI")
    builder.button(text="🇺🇸 السوق الأمريكي", callback_data="admin_sym_market:US")
    builder.button(text="₿ العملات الرقمية", callback_data="admin_sym_market:CRYPTO")
    builder.button(text="➕ إضافة رمز", callback_data="admin_sym_add")
    builder.button(text="📥 استيراد CSV", callback_data="admin_sym_import")
    builder.button(text="↩️ رجوع", callback_data="admin_panel")
    builder.adjust(2, 2, 1)
    await cq.message.edit_text(text, reply_markup=builder.as_markup())
    await cq.answer()


async def _admin_symbols_page(cq: CallbackQuery, market: str, page: int):
    symbols, current_page, total_pages, total = await get_all_symbols_admin(market, page)
    text = f"🔣 **{market}** - صفحة {current_page}/{total_pages} (إجمالي: {total})\n\n"
    if not symbols:
        text += "لا توجد رموز."
    for s in symbols:
        active = "✅" if s.is_active else "❌"
        pop = "⭐" if s.is_popular else "  "
        text += f"{active}{pop} {s.symbol} - {s.name_ar[:15]} ({s.sector})\n"
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    nav_row = []
    if page > 1:
        nav_row.append(("⬅️ السابق", f"admin_sym_market:{market}:{page - 1}"))
    if page < total_pages:
        nav_row.append(("التالي ➡️", f"admin_sym_market:{market}:{page + 1}"))
    for text, cb in nav_row:
        builder.button(text=text, callback_data=cb)
    builder.button(text="📥 تصدير CSV", callback_data=f"admin_sym_export:{market}")
    builder.button(text="➕ إضافة رمز", callback_data="admin_sym_add")
    builder.button(text="↩️ رجوع", callback_data="admin_symbols")
    builder.adjust(2, 2)
    await cq.message.edit_text(text, reply_markup=builder.as_markup())
    await cq.answer()


async def _admin_sym_view(cq: CallbackQuery, symbol_id: int):
    s = await get_symbol_by_id(symbol_id)
    if not s:
        await cq.answer("الرمز غير موجود", show_alert=True)
        return
    text = (
        f"🔣 **{s.symbol}** - {s.name_ar}\n"
        f"{'─' * 20}\n"
        f"Name EN: {s.name_en}\n"
        f"رمز ياهو: {s.yahoo_symbol}\n"
        f"القطاع: {s.sector}\n"
        f"السوق: {s.market}\n"
        f"البورصة: {s.exchange or '—'}\n"
        f"العملة: {s.currency}\n"
        f"النوع: {s.asset_type}\n"
        f"الحالة: {'🟢 نشط' if s.is_active else '🔴 معطل'}\n"
        f"مشهور: {'⭐' if s.is_popular else '—'}\n"
        f"الترتيب: {s.sort_order}"
    )
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 تفعيل/تعطيل", callback_data=f"admin_sym_toggle:{s.id}")
    builder.button(text="⭐ مشهور/عادي", callback_data=f"admin_sym_popular:{s.id}")
    builder.button(text="✏️ تعديل الاسم العربي", callback_data=f"admin_sym_edit_field:{s.id}:name_ar")
    builder.button(text="✏️ تعديل الاسم الإنجليزي", callback_data=f"admin_sym_edit_field:{s.id}:name_en")
    builder.button(text="✏️ تعديل القطاع", callback_data=f"admin_sym_edit_field:{s.id}:sector")
    builder.button(text="✏️ تعديل الرمز", callback_data=f"admin_sym_edit_field:{s.id}:symbol")
    builder.button(text="✏️ تعديل رمز ياهو", callback_data=f"admin_sym_edit_field:{s.id}:yahoo_symbol")
    builder.button(text="↩️ رجوع", callback_data=f"admin_sym_market:{s.market}:1")
    builder.adjust(2, 2, 2, 1)
    await cq.message.edit_text(text, reply_markup=builder.as_markup())
    await cq.answer()


async def _admin_sym_toggle(cq: CallbackQuery, symbol_id: int):
    result = await toggle_symbol_active(symbol_id)
    await cq.answer("✅ تم التبديل" if result else "❌ الرمز غير موجود", show_alert=True)
    if result:
        await _admin_sym_view(cq, symbol_id)


async def _admin_sym_popular(cq: CallbackQuery, symbol_id: int):
    result = await toggle_symbol_popular(symbol_id)
    await cq.answer("✅ تم التبديل" if result else "❌ الرمز غير موجود", show_alert=True)
    if result:
        await _admin_sym_view(cq, symbol_id)


async def _admin_sym_export(cq: CallbackQuery, market: str):
    import csv, io
    async with get_session() as session:
        stmt = select(Symbol).where(Symbol.market == market).order_by(Symbol.id)
        result = await session.execute(stmt)
        symbols = result.scalars().all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["symbol", "yahoo_symbol", "name_ar", "name_en", "sector", "exchange", "currency", "asset_type", "is_active", "is_popular", "sort_order"])
    for s in symbols:
        writer.writerow([s.symbol, s.yahoo_symbol, s.name_ar, s.name_en, s.sector, s.exchange or "", s.currency, s.asset_type, str(s.is_active), str(s.is_popular), str(s.sort_order)])
    csv_bytes = output.getvalue().encode("utf-8-sig")
    from aiogram.types import BufferedInputFile
    file = BufferedInputFile(csv_bytes, filename=f"symbols_{market.lower()}.csv")
    await cq.message.answer_document(file, caption=f"📥 تصدير رموز {market}")
    await cq.answer()


@router.message(AdminStates.sym_edit_value)
async def handle_sym_edit_value(msg: Message, state: FSMContext):
    data = await state.get_data()
    symbol_id = data.get("sym_id")
    field = data.get("sym_field")
    value = msg.text.strip()
    field_map = {"name_ar": value, "name_en": value, "sector": value, "symbol": value, "yahoo_symbol": value}
    kw = {field: value}
    result = await update_symbol(symbol_id, **kw)
    if result:
        await log_admin(msg.from_user.id, f"edit_sym_{symbol_id}_{field}")
        await msg.answer(f"✅ تم تحديث {field} بنجاح.")
    else:
        await msg.answer("❌ فشل التحديث.")
    await state.clear()
    s = await get_symbol_by_id(symbol_id)
    if s:
        await msg.answer(f"🔣 {s.symbol} - {s.name_ar}", reply_markup=back_button(f"admin_sym_market:{s.market}:1"))


@router.message(AdminStates.prediction_grant_id)
async def handle_prediction_grant_id(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id):
        return
    try:
        telegram_id = int(msg.text.strip())
    except ValueError:
        await msg.answer("❌ أرسل Telegram ID صحيح.")
        return

    await grant_feature_access(telegram_id, PREDICTION_FEATURE, msg.from_user.id)
    await log_admin(msg.from_user.id, f"prediction_grant_{telegram_id}")
    await state.clear()
    await msg.answer(f"✅ تم تفعيل الإشارات الخاصة للمستخدم {telegram_id}.", reply_markup=back_button("admin_prediction_access"))


@router.message(AdminStates.prediction_revoke_id)
async def handle_prediction_revoke_id(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id):
        return
    try:
        telegram_id = int(msg.text.strip())
    except ValueError:
        await msg.answer("❌ أرسل Telegram ID صحيح.")
        return

    removed = await revoke_feature_access(telegram_id, PREDICTION_FEATURE)
    await log_admin(msg.from_user.id, f"prediction_revoke_{telegram_id}")
    await state.clear()
    if removed:
        await msg.answer(f"✅ تم حذف صلاحية الإشارات الخاصة من {telegram_id}.", reply_markup=back_button("admin_prediction_access"))
    else:
        await msg.answer("⚠️ المستخدم غير موجود في قائمة الصلاحيات.", reply_markup=back_button("admin_prediction_access"))


@router.message(AdminStates.sym_add_symbol)
async def handle_sym_add_symbol(msg: Message, state: FSMContext):
    await state.update_data(sym_symbol=msg.text.strip().upper())
    await state.set_state(AdminStates.sym_add_yahoo)
    await msg.answer("أدخل رمز ياهو المالي (مثال: 2222.SR, AAPL, BTCUSDT):", reply_markup=back_button("admin_symbols"))


@router.message(AdminStates.sym_add_yahoo)
async def handle_sym_add_yahoo(msg: Message, state: FSMContext):
    await state.update_data(sym_yahoo=msg.text.strip())
    await state.set_state(AdminStates.sym_add_name_ar)
    await msg.answer("أدخل الاسم العربي:", reply_markup=back_button("admin_symbols"))


@router.message(AdminStates.sym_add_name_ar)
async def handle_sym_add_name_ar(msg: Message, state: FSMContext):
    await state.update_data(sym_name_ar=msg.text.strip())
    await state.set_state(AdminStates.sym_add_name_en)
    await msg.answer("أدخل الاسم الإنجليزي:", reply_markup=back_button("admin_symbols"))


@router.message(AdminStates.sym_add_name_en)
async def handle_sym_add_name_en(msg: Message, state: FSMContext):
    await state.update_data(sym_name_en=msg.text.strip())
    await state.set_state(AdminStates.sym_add_sector)
    data = await state.get_data()
    market = data.get("sym_market", "")
    from services.symbols_service import get_sectors
    sectors = get_sectors(market)
    if sectors:
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        for sec in sectors:
            builder.button(text=sec, callback_data=f"admin_sym_pick_sector:{sec}")
        builder.button(text="✏️ إدخال يدوي", callback_data="admin_sym_manual_sector")
        builder.button(text="↩️ رجوع", callback_data="admin_symbols")
        builder.adjust(2)
        await msg.answer(f"اختر القطاع لـ {market}:", reply_markup=builder.as_markup())
    else:
        await msg.answer("أدخل اسم القطاع:", reply_markup=back_button("admin_symbols"))


@router.callback_query(F.data.startswith("admin_sym_pick_sector:"))
async def cb_admin_sym_pick_sector(cq: CallbackQuery, state: FSMContext):
    sector = cq.data.split(":", 1)[1]
    await state.update_data(sym_sector=sector)
    await state.set_state(AdminStates.sym_add_exchange)
    await cq.message.edit_text("أدخل اسم البورصة (مثل: Saudi, NASDAQ, Binance) - أو أرسل /skip:", reply_markup=back_button("admin_symbols"))
    await cq.answer()


@router.callback_query(F.data == "admin_sym_manual_sector")
async def cb_admin_sym_manual_sector(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.sym_add_sector)
    await cq.message.edit_text("أدخل اسم القطاع:", reply_markup=back_button("admin_symbols"))
    await cq.answer()


@router.message(AdminStates.sym_add_sector)
async def handle_sym_add_sector_text(msg: Message, state: FSMContext):
    await state.update_data(sym_sector=msg.text.strip())
    await state.set_state(AdminStates.sym_add_exchange)
    await msg.answer("أدخل اسم البورصة (أو أرسل /skip):", reply_markup=back_button("admin_symbols"))


@router.message(AdminStates.sym_add_exchange)
async def handle_sym_add_exchange(msg: Message, state: FSMContext):
    text = msg.text.strip()
    if text == "/skip":
        await state.update_data(sym_exchange=None)
    else:
        await state.update_data(sym_exchange=text)
    await state.set_state(AdminStates.sym_add_currency)
    await msg.answer("أدخل العملة (مثل: SAR, USD) أو /skip للافتراضي:", reply_markup=back_button("admin_symbols"))


@router.message(AdminStates.sym_add_currency)
async def handle_sym_add_currency(msg: Message, state: FSMContext):
    text = msg.text.strip()
    data = await state.get_data()
    currency = None if text == "/skip" else text.upper()
    s = await add_symbol(
        market=data["sym_market"],
        symbol=data["sym_symbol"],
        yahoo_symbol=data["sym_yahoo"],
        name_ar=data["sym_name_ar"],
        name_en=data["sym_name_en"],
        sector=data.get("sym_sector", ""),
        exchange=data.get("sym_exchange"),
        currency=currency,
    )
    await log_admin(msg.from_user.id, f"add_sym_{s.symbol}")
    await msg.answer(f"✅ تمت إضافة الرمز بنجاح:\n{s.symbol} - {s.name_ar}")
    await state.clear()


@router.message(F.document, F.from_user.id.in_(settings.admin_ids))
async def handle_admin_csv_import(msg: Message):
    ctx = _user_context.get(msg.from_user.id, {})
    if ctx.get("context") != "admin_sym_import":
        return
    import csv, io, tempfile, os
    from aiogram.types import BufferedInputFile
    file = await msg.bot.download(msg.document)
    content = file.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    count = 0
    errors = []
    async with get_session() as session:
        async with session.begin():
            for row in reader:
                try:
                    sym = Symbol(
                        market=row.get("market", "SAUDI").upper(),
                        symbol=row.get("symbol", "").strip().upper(),
                        yahoo_symbol=row.get("yahoo_symbol", row.get("symbol", "")).strip(),
                        name_ar=row.get("name_ar", row.get("symbol", "")).strip(),
                        name_en=row.get("name_en", row.get("symbol", "")).strip(),
                        sector=row.get("sector", "").strip(),
                        exchange=row.get("exchange", "").strip() or None,
                        currency=row.get("currency", "SAR").strip().upper(),
                        asset_type=row.get("asset_type", "stock").strip(),
                        is_active=row.get("is_active", "True").strip().lower() == "true",
                        is_popular=row.get("is_popular", "False").strip().lower() == "true",
                    )
                    session.add(sym)
                    count += 1
                except Exception as e:
                    errors.append(f"سطر {reader.line_num}: {e}")
    _user_context.pop(msg.from_user.id, None)
    text = f"✅ تم استيراد {count} رمز بنجاح."
    if errors:
        text += f"\n\n❌ أخطاء ({len(errors)}):\n" + "\n".join(errors[:5])
    await msg.answer(text)
