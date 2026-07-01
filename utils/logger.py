import os
import sys
from typing import Optional

from loguru import logger
from sqlalchemy import select

from database import get_session
from models import AdminLog, ErrorLog


LOG_DIR = os.path.join("data", "logs")
LOG_FILE = os.path.join(LOG_DIR, "bot.log")


def setup_logger():
    os.makedirs(LOG_DIR, exist_ok=True)

    logger.remove()

    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{module}</cyan> | <level>{message}</level>",
        level="INFO",
        colorize=True,
    )

    logger.add(
        LOG_FILE,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {module} | {message}",
        level="DEBUG",
        rotation="10 MB",
        retention=7,
        compression="gz",
    )

    return logger


setup_logger()


async def log_error(source: str, message: str, details: Optional[str] = None) -> None:
    logger.error(f"[{source}] {message} | {details or ''}")
    async with get_session() as session:
        error_log = ErrorLog(
            source=source,
            message=message,
            details=details,
        )
        session.add(error_log)
        await session.commit()


async def log_admin_action(admin_id: int, action: str, details: Optional[str] = None) -> None:
    logger.info(f"[ADMIN {admin_id}] {action} | {details or ''}")
    async with get_session() as session:
        admin_log = AdminLog(
            admin_id=admin_id,
            action=action,
            details=details,
        )
        session.add(admin_log)
        await session.commit()


def log_scan(user_id: int, symbol: str, market: str, score: Optional[float]) -> None:
    logger.info(f"[SCAN] user={user_id} symbol={symbol} market={market} score={score}")
