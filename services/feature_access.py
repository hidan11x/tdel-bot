from sqlalchemy import select

from config import settings
from database import get_session
from models import FeatureAccess


PREDICTION_FEATURE = "private_prediction"


async def has_feature_access(telegram_id: int, feature_key: str) -> bool:
    if telegram_id in settings.admin_ids:
        return True
    async with get_session() as session:
        result = await session.execute(
            select(FeatureAccess).where(
                FeatureAccess.telegram_id == telegram_id,
                FeatureAccess.feature_key == feature_key,
                FeatureAccess.enabled == True,
            )
        )
        return result.scalar_one_or_none() is not None


async def list_feature_access(feature_key: str) -> list[FeatureAccess]:
    async with get_session() as session:
        result = await session.execute(
            select(FeatureAccess)
            .where(FeatureAccess.feature_key == feature_key, FeatureAccess.enabled == True)
            .order_by(FeatureAccess.created_at.desc())
        )
        return list(result.scalars().all())


async def grant_feature_access(telegram_id: int, feature_key: str, created_by: int | None = None) -> None:
    async with get_session() as session:
        result = await session.execute(
            select(FeatureAccess).where(
                FeatureAccess.telegram_id == telegram_id,
                FeatureAccess.feature_key == feature_key,
            )
        )
        access = result.scalar_one_or_none()
        if access:
            access.enabled = True
            access.created_by = created_by
        else:
            session.add(
                FeatureAccess(
                    telegram_id=telegram_id,
                    feature_key=feature_key,
                    enabled=True,
                    created_by=created_by,
                )
            )
        await session.commit()


async def revoke_feature_access(telegram_id: int, feature_key: str) -> bool:
    async with get_session() as session:
        result = await session.execute(
            select(FeatureAccess).where(
                FeatureAccess.telegram_id == telegram_id,
                FeatureAccess.feature_key == feature_key,
            )
        )
        access = result.scalar_one_or_none()
        if not access:
            return False
        access.enabled = False
        await session.commit()
        return True
