from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.types import CallbackQuery, Message, TelegramObject

from sqlalchemy import select

from database import get_session
from models import User
from config import settings


class UserCheckMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)

        user = event.from_user
        if user is None:
            return await handler(event, data)

        telegram_id = user.id
        is_new_user = False

        async with get_session() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            db_user = result.scalar_one_or_none()

            if db_user is None:
                is_new_user = True
                db_user = User(
                    telegram_id=telegram_id,
                    username=user.username,
                    first_name=user.first_name or user.username or str(telegram_id),
                    language_code=user.language_code or "ar",
                    referral_code=f"ref{telegram_id}",
                )
                session.add(db_user)
                await session.commit()
                await session.refresh(db_user)

            if db_user.is_banned:
                if isinstance(event, Message):
                    await event.answer("🚫 حسابك محظور. يرجى التواصل مع الدعم.")
                elif isinstance(event, CallbackQuery):
                    await event.answer("🚫 حسابك محظور", show_alert=True)
                return

            if db_user.subscription_end is not None:
                sub_end = db_user.subscription_end
                if sub_end.tzinfo is None:
                    sub_end = sub_end.replace(tzinfo=timezone.utc)
                remaining = (sub_end - datetime.now(timezone.utc)).days
                if 0 < remaining <= 3:
                    msg = f"⚠️ تنتهي صلاحية اشتراكك خلال {remaining} يوم"
                    if isinstance(event, Message):
                        await event.answer(msg)
                    elif isinstance(event, CallbackQuery):
                        await event.answer(msg, show_alert=True)

            now = datetime.now(timezone.utc)
            db_user.last_active = now
            await session.commit()

        if is_new_user:
            bot: Bot = data.get("bot") or event.bot
            if bot:
                username_str = f"@{user.username}" if user.username else "بدون"
                lang = user.language_code or "غير محدد"
                mention = user.mention if user.username else user.first_name or str(telegram_id)

                notify_text = (
                    f"👤 مستخدم جديد دخل البوت\n\n"
                    f"📝 الاسم: {user.first_name or 'غير معروف'}\n"
                    f"👤 اليوزر: {username_str}\n"
                    f"🆔 المعرف: {telegram_id}\n"
                    f"🌐 اللغة: {lang}\n"
                )

                if isinstance(event, Message) and event.text:
                    msg_preview = event.text[:50] + "..." if len(event.text) > 50 else event.text
                    notify_text += f"💬 أول رسالة: {msg_preview}\n"

                try:
                    for admin_id in settings.admin_ids:
                        await bot.send_message(admin_id, notify_text)
                except Exception:
                    pass

        return await handler(event, data)
