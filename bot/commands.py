from aiogram import Bot
from aiogram.types import BotCommand


BOT_COMMANDS = [
    BotCommand(command="start", description="🏠 القائمة الرئيسية"),
    BotCommand(command="help", description="📋 المساعدة"),
    BotCommand(command="status", description="📊 حالة البوت"),
    BotCommand(command="profile", description="👤 حسابي"),
    BotCommand(command="plans", description="💳 الخطط"),
    BotCommand(command="subscribe", description="💰 الاشتراك"),
    BotCommand(command="daily", description="📅 التقرير اليومي"),
    BotCommand(command="scan", description="📊 فحص سريع"),
    BotCommand(command="support", description="🛠 الدعم"),
]


async def setup_bot_commands(bot: Bot) -> None:
    await bot.set_my_commands(BOT_COMMANDS)
