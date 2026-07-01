from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from sqlalchemy import select

from config import settings
from database import get_session
from models import User, SupportTicket
from bot.keyboards.main import back_button

from . import _user_context

router = Router()


class TicketStates(StatesGroup):
    subject = State()
    message_text = State()


def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids


@router.callback_query(F.data == "support_ticket")
async def cb_ticket_create(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(TicketStates.subject)
    await callback.message.edit_text(
        "📝 **إنشاء تذكرة دعم**\n\nأدخل عنوان التذكرة (مثال: مشكلة في الاشتراك):",
        reply_markup=back_button("main_menu"),
    )


@router.message(TicketStates.subject)
async def handle_ticket_subject(msg: Message, state: FSMContext):
    await state.update_data(ticket_subject=msg.text.strip())
    await state.set_state(TicketStates.message_text)
    await msg.answer("📝 أدخل تفاصيل التذكرة (وصف المشكلة بالتفصيل):", reply_markup=back_button("main_menu"))


@router.message(TicketStates.message_text)
async def handle_ticket_message(msg: Message, state: FSMContext):
    data = await state.get_data()
    subject = data.get("ticket_subject", "بدون عنوان")
    ticket_text = msg.text.strip()
    async with get_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == msg.from_user.id))
        user = result.scalar_one_or_none()
        if user:
            ticket = SupportTicket(user_id=user.id, subject=subject, message=ticket_text)
            session.add(ticket)
            await session.commit()
            await msg.answer("✅ تم إنشاء التذكرة بنجاح. سيقوم فريق الدعم بالرد عليك قريباً.", reply_markup=back_button("main_menu"))
        else:
            await msg.answer("❌ المستخدم غير موجود.", reply_markup=back_button("main_menu"))
    await state.clear()


@router.callback_query(F.data == "admin_tickets")
async def cb_admin_tickets(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ غير مصرح", show_alert=True)
        return
    await callback.answer()
    async with get_session() as session:
        result = await session.execute(
            select(SupportTicket).order_by(SupportTicket.id.desc()).limit(10)
        )
        tickets = result.scalars().all()
    text = "🎫 **تذاكر الدعم**\n\n"
    if not tickets:
        text += "لا توجد تذاكر."
    for t in tickets:
        status_emoji = {"open": "🟢", "replied": "🟡", "closed": "🔴"}
        emoji = status_emoji.get(t.status, "⚪")
        text += f"{emoji} #{t.id} - {t.subject[:30]} ({t.status})\n"
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 تحديث", callback_data="admin_tickets")
    builder.button(text="↩️ رجوع", callback_data="admin_panel")
    builder.adjust(2)
    await callback.message.edit_text(text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("admin_ticket_view:"))
async def cb_admin_ticket_view(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ غير مصرح", show_alert=True)
    ticket_id = int(callback.data.split(":")[1])
    async with get_session() as session:
        result = await session.execute(select(SupportTicket).where(SupportTicket.id == ticket_id))
        ticket = result.scalar_one_or_none()
        if not ticket:
            return await callback.answer("التذكرة غير موجودة", show_alert=True)
        user = await session.get(User, ticket.user_id)
        username = user.first_name if user else "غير معروف"
        text = (
            f"🎫 **تذكرة #{ticket.id}**\n"
            f"المستخدم: {username}\n"
            f"الحالة: {ticket.status}\n"
            f"العنوان: {ticket.subject}\n"
            f"الرسالة:\n{ticket.message}\n"
        )
        if ticket.admin_reply:
            text += f"\n**رد الإدارة:**\n{ticket.admin_reply}"
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    if ticket.status in ("open", "replied"):
        builder.button(text="✏️ رد", callback_data=f"admin_ticket_reply:{ticket.id}")
        builder.button(text="🔴 إغلاق", callback_data=f"admin_ticket_close:{ticket.id}")
    builder.button(text="↩️ رجوع", callback_data="admin_tickets")
    builder.adjust(2)
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("admin_ticket_reply:"))
async def cb_admin_ticket_reply(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ غير مصرح", show_alert=True)
    ticket_id = int(callback.data.split(":")[1])
    await state.update_data(reply_ticket_id=ticket_id)
    from aiogram.fsm.state import State
    await state.set_state("admin_ticket_reply_text")
    await callback.message.edit_text(f"✏️ أدخل ردك على التذكرة #{ticket_id}:", reply_markup=back_button("admin_tickets"))
    await callback.answer()


@router.message(StateFilter("admin_ticket_reply_text"))
async def handle_admin_ticket_reply(msg: Message, state: FSMContext):
    data = await state.get_data()
    ticket_id = data.get("reply_ticket_id")
    reply_text = msg.text.strip()
    async with get_session() as session:
        async with session.begin():
            result = await session.execute(select(SupportTicket).where(SupportTicket.id == ticket_id))
            ticket = result.scalar_one_or_none()
            if ticket:
                ticket.admin_reply = reply_text
                ticket.replied_by = msg.from_user.id
                ticket.status = "replied"
                user = await session.get(User, ticket.user_id)
                if user:
                    try:
                        await msg.bot.send_message(
                            user.telegram_id,
                            f"📬 **رد على تذكرتك #{ticket.id}**\n\n{ticket.subject}\n\n{reply_text}\n\nللمتابعة، تواصل مع الدعم.",
                        )
                    except Exception:
                        pass
    await msg.answer(f"✅ تم الرد على التذكرة #{ticket_id}.", reply_markup=back_button("admin_tickets"))
    await state.clear()


@router.callback_query(F.data.startswith("admin_ticket_close:"))
async def cb_admin_ticket_close(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ غير مصرح", show_alert=True)
    ticket_id = int(callback.data.split(":")[1])
    async with get_session() as session:
        async with session.begin():
            result = await session.execute(select(SupportTicket).where(SupportTicket.id == ticket_id))
            ticket = result.scalar_one_or_none()
            if ticket:
                ticket.status = "closed"
    await callback.answer("✅ تم إغلاق التذكرة", show_alert=True)
    await cb_admin_tickets(callback)
