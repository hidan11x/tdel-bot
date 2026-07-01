from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select

from database import get_session
from models import User, Alert
from services.alerts_engine import create_alert, get_user_alerts, disable_alert
from services.subscriptions import can_add_alert
from bot.keyboards.main import alert_types, back_button, main_menu
from bot.keyboards.main import InlineKeyboardBuilder

from . import _user_context

router = Router()

MARKET_MAP = {
    "saudi": "SAUDI",
    "us": "US",
    "crypto": "CRYPTO",
}

ALERT_TYPE_NAMES = {
    "price_above": "السعر أعلى من",
    "price_below": "السعر أدنى من",
    "rsi_above": "RSI أعلى من",
    "rsi_below": "RSI أدنى من",
    "volume_spike": "ارتفاع حاد في الحجم",
    "near_support": "اقتراب من الدعم",
    "near_resistance": "اقتراب من المقاومة",
    "price_change_percent": "نسبة تغير السعر",
}


async def _get_user(telegram_id: int):
    async with get_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()


@router.callback_query(F.data == "my_alerts")
async def cb_my_alerts(callback: CallbackQuery):
    await callback.answer()
    telegram_id = callback.from_user.id
    user = await _get_user(telegram_id)
    if not user:
        await callback.message.edit_text("المستخدم غير موجود.")
        return

    alerts = await get_user_alerts(user.id)

    if not alerts:
        text = "🔔 لا توجد تنبيهات نشطة.\n\nقم بفحص أي أصل واختر إنشاء تنبيه لإضافة تنبيه جديد."
        await callback.message.edit_text(text, reply_markup=back_button("main_menu"))
        return

    lines = ["🔔 قائمة التنبيهات:\n"]
    for i, a in enumerate(alerts, 1):
        type_name = ALERT_TYPE_NAMES.get(a.alert_type, a.alert_type)
        status = "✅ نشط" if a.is_active else "❌ معطل"
        triggered = "⚡ تم التفعيل" if a.triggered else ""
        lines.append(f"{i}. {a.symbol} ({a.market})")
        lines.append(f"   النوع: {type_name} | القيمة: {a.value}")
        lines.append(f"   الحالة: {status} {triggered}")
        lines.append("")

    text = "\n".join(lines)

    builder = InlineKeyboardBuilder()
    for a in alerts[:10]:
        toggle_label = "تعطيل" if a.is_active else "تفعيل"
        builder.button(text=f"{toggle_label} {a.symbol}", callback_data=f"alert_toggle:{a.id}")
    builder.button(text="↩️ رجوع", callback_data="main_menu")
    builder.adjust(2, repeat=True)

    await callback.message.edit_text(text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("alert_create:"))
async def cb_alert_create(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    symbol = parts[1].upper()
    market_key = parts[2].lower()
    market = MARKET_MAP.get(market_key, market_key.upper())

    telegram_id = callback.from_user.id
    user = await _get_user(telegram_id)
    if not user:
        await callback.message.edit_text("المستخدم غير موجود.")
        return

    can = await can_add_alert(user.id)
    if not can:
        await callback.message.edit_text(
            "⚠️ لقد تجاوزت الحد الأقصى للتنبيهات. يرجى حذف بعض التنبيهات أو الترقية.",
            reply_markup=back_button("my_alerts"),
        )
        return

    _user_context[telegram_id] = {
        "context": "alert_type_selection",
        "symbol": symbol,
        "market": market,
    }

    kb = alert_types(symbol, market_key)
    text = f"🔔 اختر نوع التنبيه لـ {symbol}:"
    await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data.startswith("alert_set:"))
async def cb_alert_set(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    symbol = parts[1].upper()
    market_key = parts[2].lower()
    alert_type = parts[3]
    market = MARKET_MAP.get(market_key, market_key.upper())

    telegram_id = callback.from_user.id
    _user_context[telegram_id] = {
        "context": "alert_value",
        "symbol": symbol,
        "market": market,
        "alert_type": alert_type,
    }

    type_name = ALERT_TYPE_NAMES.get(alert_type, alert_type)
    text = f"🔔 أدخل القيمة للتنبيه ({type_name}) لـ {symbol}:\n\nمثال: 150.50"
    await callback.message.edit_text(text, reply_markup=back_button("my_alerts"))


async def handle_alert_value_input(message: Message):
    telegram_id = message.from_user.id
    ctx = _user_context.get(telegram_id)
    if not ctx or ctx.get("context") != "alert_value":
        return

    symbol = ctx.get("symbol", "")
    market = ctx.get("market", "US")
    alert_type = ctx.get("alert_type", "")

    try:
        value = float(message.text.strip().replace(",", ""))
    except ValueError:
        await message.answer("❌ القيمة غير صالحة. أدخل رقماً صحيحاً (مثال: 150.50)")
        return

    user = await _get_user(telegram_id)
    if not user:
        await message.answer("المستخدم غير موجود.")
        _user_context.pop(telegram_id, None)
        return

    can = await can_add_alert(user.id)
    if not can:
        await message.answer(
            "⚠️ لقد تجاوزت الحد الأقصى للتنبيهات.",
            reply_markup=back_button("my_alerts"),
        )
        _user_context.pop(telegram_id, None)
        return

    try:
        alert = await create_alert(user.id, symbol, market, alert_type, value)
        _user_context.pop(telegram_id, None)
        await message.answer(
            f"✅ تم إنشاء التنبيه بنجاح!\n\n{symbol}: {ALERT_TYPE_NAMES.get(alert_type, alert_type)} = {value}",
            reply_markup=back_button("my_alerts"),
        )
    except Exception:
        _user_context.pop(telegram_id, None)
        await message.answer(
            "❌ حدث خطأ أثناء إنشاء التنبيه. حاول مرة أخرى.",
            reply_markup=back_button("my_alerts"),
        )


@router.callback_query(F.data.startswith("alert_toggle:"))
async def cb_alert_toggle(callback: CallbackQuery):
    await callback.answer()
    alert_id = int(callback.data.split(":")[1])

    telegram_id = callback.from_user.id
    user = await _get_user(telegram_id)
    if not user:
        await callback.message.edit_text("المستخدم غير موجود.")
        return

    async with get_session() as session:
        alert = await session.get(Alert, alert_id)
        if not alert or alert.user_id != user.id:
            await callback.message.edit_text("⚠️ التنبيه غير موجود.")
            return

        alert.is_active = not alert.is_active
        if alert.is_active:
            alert.triggered = False
        await session.commit()

    status = "مفعل" if alert.is_active else "معطل"
    await callback.message.edit_text(
        f"✅ تم {status} التنبيه لـ {alert.symbol}.",
        reply_markup=back_button("my_alerts"),
    )


@router.callback_query(F.data.startswith("alert_delete:"))
async def cb_alert_delete(callback: CallbackQuery):
    await callback.answer()
    alert_id = int(callback.data.split(":")[1])

    telegram_id = callback.from_user.id
    user = await _get_user(telegram_id)
    if not user:
        await callback.message.edit_text("المستخدم غير موجود.")
        return

    async with get_session() as session:
        alert = await session.get(Alert, alert_id)
        if not alert or alert.user_id != user.id:
            await callback.message.edit_text("⚠️ التنبيه غير موجود.")
            return

        await session.delete(alert)
        await session.commit()

    await callback.message.edit_text(
        "✅ تم حذف التنبيه.",
        reply_markup=back_button("my_alerts"),
    )


@router.callback_query(F.data.startswith("symbol_actions:"))
async def cb_symbol_actions(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    symbol = parts[1].upper()
    market_key = parts[2].lower()

    from bot.keyboards.main import symbol_actions
    kb = symbol_actions(symbol, market_key)
    await callback.message.edit_text(
        f"📊 {symbol} - اختر إجراء:",
        reply_markup=kb,
    )
