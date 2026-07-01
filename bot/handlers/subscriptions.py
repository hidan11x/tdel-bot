from datetime import datetime, timezone

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from sqlalchemy import select

from database import get_session
from models import User, Plan
from services.subscriptions import activate_code, get_trial_end_date
from bot.keyboards.main import (
    subscription_plans, back_button, main_menu,
)

from . import _user_context

router = Router()

PLAN_NAMES = {
    "basic": "أساسي",
    "pro": "احترافي",
    "vip": "VIP",
    "lifetime": "Lifetime",
}


async def _get_user(telegram_id: int):
    async with get_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()


@router.callback_query(F.data == "subscription")
async def cb_subscription(callback: CallbackQuery):
    await callback.answer()
    from config import settings
    text = (
        "💎 خطط الاشتراك\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "🥉 Basic — {:.0f} ريال / شهر\n"
        "━━━━━━━━━━━━━━━━\n"
        "✅ فحص فني (30 يومياً)\n"
        "✅ 3 أسواق (سعودي/أمريكي/كريبتو)\n"
        "✅ تنبيهات (15)\n"
        "✅ قائمة متابعة (20)\n"
        "✅ الشارت\n"
        "✅ تصفح الرموز\n"
        "❌ الخريطة الحرارية\n"
        "❌ أخبار السوق\n"
        "❌ حالة السوق\n"
        "❌ مقارنة\n"
        "❌ تتبع الأسعار\n"
        "❌ تحليل متعدد الفريمات\n"
        "❌ إشارات VIP\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "🥈 Pro — {:.0f} ريال / شهر\n"
        "━━━━━━━━━━━━━━━━\n"
        "✅ كل ميزات Basic\n"
        "✅ فحص فني (100 يومياً)\n"
        "✅ تنبيهات (50)\n"
        "✅ قائمة متابعة (50)\n"
        "✅ الخريطة الحرارية\n"
        "✅ أخبار السوق\n"
        "✅ حالة السوق\n"
        "✅ تقارير يومية\n"
        "✅ مقارنة\n"
        "✅ تتبع الأسعار\n"
        "✅ أقوى القراءات\n"
        "✅ مشاركة التحليل\n"
        "✅ تصدير السجل\n"
        "❌ تحليل متعدد الفريمات\n"
        "❌ إشارات VIP\n"
        "❌ دعوة صديق\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "🥇 VIP — {:.0f} ريال / شهر\n"
        "━━━━━━━━━━━━━━━━\n"
        "✅ كل ميزات Pro\n"
        "✅ فحص فني (غير محدود ∞)\n"
        "✅ تنبيهات (غير محدود ∞)\n"
        "✅ قائمة متابعة (غير محدود ∞)\n"
        "✅ 🔄 تحليل متعدد الفريمات\n"
        "✅ 🚀 إشارات VIP\n"
        "✅ 🎁 دعوة صديق\n"
        "✅ 🌐 تبديل لغة\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "💎 Lifetime — {:.0f} ريال (مرة واحدة)\n"
        "━━━━━━━━━━━━━━━━\n"
        "✅ كل ميزات VIP مدى الحياة!\n\n"
        "للاشتراك أو للحصول على كود تفعيل:\n"
        "👤 @hidanx11\n\n"
        "أو أدخل كود التفعيل إذا كان لديك:"
    ).format(
        settings.basic_price,
        settings.pro_price,
        settings.vip_price,
        settings.lifetime_price,
    )
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 أدخل كود التفعيل", callback_data="enter_code")
    builder.button(text="👤 تواصل مع الدعم", callback_data="support")
    builder.button(text="↩️ رجوع", callback_data="main_menu")
    builder.adjust(1, 1, 1)
    await callback.message.edit_text(text[:4000], reply_markup=builder.as_markup())


@router.message(Command("plans"))
async def cmd_plans(message: Message):
    try:
        async with get_session() as session:
            stmt = select(Plan)
            result = await session.execute(stmt)
            plans = result.scalars().all()
    except Exception:
        plans = []

    if not plans:
        text = (
            "💎 خطط الاشتراك:\n\n"
            f"🥉 أساسي: {29:.0f} ريال/شهر\n"
            f"🥈 احترافي: {79:.0f} ريال/شهر\n"
            f"🥇 VIP: {199:.0f} ريال/شهر\n"
            f"💎 مدى الحياة: {499:.0f} ريال\n\n"
            "اختر خطة من القائمة."
        )
    else:
        from utils.formatter import format_plans
        text = format_plans([
            {"name": p.name, "price_sar": p.price_sar, "price_usd": p.price_usd,
             "scans_daily": p.scans_daily, "max_alerts": p.max_alerts, "max_watchlist": p.max_watchlist}
            for p in plans
        ])

    await message.answer(text, reply_markup=subscription_plans())


@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message):
    text = "💎 اختر خطة الاشتراك المناسبة لك:"
    await message.answer(text, reply_markup=subscription_plans())


@router.callback_query(F.data.startswith("subscribe:"))
async def cb_subscribe_plan(callback: CallbackQuery):
    await callback.answer()
    plan = callback.data.split(":")[1]
    plan_name = PLAN_NAMES.get(plan, plan)

    if plan == "trial":
        telegram_id = callback.from_user.id
        user = await _get_user(telegram_id)
        if not user:
            await callback.message.edit_text("المستخدم غير موجود.")
            return

        if user.plan != "free":
            await callback.message.edit_text(
                "⚠️ لديك بالفعل اشتراك نشط.",
                reply_markup=back_button("subscription"),
            )
            return

        async with get_session() as session:
            user_obj = await session.get(User, user.id)
            if user_obj:
                user_obj.plan = "basic"
                user_obj.subscription_start = datetime.now(timezone.utc)
                user_obj.subscription_end = get_trial_end_date(datetime.now(timezone.utc))
                await session.commit()

        await callback.message.edit_text(
            f"✅ تم تفعيل الفترة التجريبية لمدة 7 أيام! استمتع بميزات الباقة الأساسية.",
            reply_markup=main_menu("vip"),
        )
        return

    _user_context[callback.from_user.id] = {"context": "activation_code", "plan": plan}
    text = (
        f"💰 للاشتراك في خطة {plan_name}:\n\n"
        "يرجى إدخال كود التفعيل الخاص بك.\n"
        "إذا لم يكن لديك كود، يرجى التواصل مع الدعم الفني."
    )
    await callback.message.edit_text(text, reply_markup=back_button("subscription"))


async def handle_activation_code(message: Message):
    telegram_id = message.from_user.id
    ctx = _user_context.get(telegram_id)
    if not ctx or ctx.get("context") != "activation_code":
        return

    plan = ctx.get("plan", "")
    code = message.text.strip()

    user = await _get_user(telegram_id)
    if not user:
        await message.answer("المستخدم غير موجود.")
        _user_context.pop(telegram_id, None)
        return

    result = await activate_code(code, user.id)
    _user_context.pop(telegram_id, None)

    if "بنجاح" in result:
        await message.answer(
            f"✅ {result}\n\nتم تفعيل اشتراكك بنجاح! 🎉",
            reply_markup=main_menu("vip"),
        )
    else:
        await message.answer(f"❌ {result}\n\nتواصل مع الدعم: @hidanx11", reply_markup=back_button("main_menu"))


@router.callback_query(F.data == "enter_code")
async def cb_enter_code(callback: CallbackQuery):
    await callback.answer()
    _user_context[callback.from_user.id] = {"context": "activation_code", "plan": "any"}
    text = (
        "💳 أدخل كود التفعيل الخاص بك:\n\n"
        "إذا لم يكن لديك كود، تواصل مع الدعم:\n"
        "👤 @hidanx11"
    )
    await callback.message.edit_text(text, reply_markup=back_button("main_menu"))


@router.callback_query(F.data == "activate_trial")
async def cb_activate_trial(callback: CallbackQuery):
    await cb_subscribe_plan(callback)
