import time
from collections import defaultdict
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, rate_limit: float = 1.0, max_requests: int = 5) -> None:
        self.rate_limit = rate_limit
        self.max_requests = max_requests
        self._users: dict[int, list[float]] = defaultdict(list)

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

        now = time.monotonic()
        user_id = user.id
        timestamps = self._users[user_id]
        timestamps[:] = [t for t in timestamps if now - t < self.rate_limit]

        if len(timestamps) >= self.max_requests:
            if isinstance(event, Message):
                await event.answer("⚠️ الرجاء الانتظار قليلاً قبل إرسال أمر جديد")
            elif isinstance(event, CallbackQuery):
                await event.answer("⚠️ الرجاء الانتظار قليلاً", show_alert=True)
            return

        timestamps.append(now)
        return await handler(event, data)
