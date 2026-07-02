import secrets
import string
from typing import Optional

from sqlalchemy import select

from config import settings
from database import get_session
from models import AffiliateCommission, AffiliatePartner, User


def _partner_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "AFF" + "".join(secrets.choice(alphabet) for _ in range(7))


def plan_price(plan: str) -> float:
    return {
        "basic": settings.basic_price,
        "pro": settings.pro_price,
        "vip": settings.vip_price,
        "lifetime": settings.lifetime_price,
    }.get(plan, 0.0)


async def create_affiliate_partner(name: str, telegram_id: Optional[int], commission_percent: float = 30.0) -> AffiliatePartner:
    async with get_session() as session:
        code = _partner_code()
        while (await session.execute(select(AffiliatePartner).where(AffiliatePartner.code == code))).scalar_one_or_none():
            code = _partner_code()
        partner = AffiliatePartner(
            name=name[:120],
            telegram_id=telegram_id,
            code=code,
            commission_percent=commission_percent,
        )
        session.add(partner)
        await session.commit()
        await session.refresh(partner)
        return partner


async def assign_affiliate(referral_arg: str, telegram_id: int) -> bool:
    code = referral_arg.replace("aff_", "", 1).strip().upper()
    if not code:
        return False

    async with get_session() as session:
        partner_result = await session.execute(
            select(AffiliatePartner).where(AffiliatePartner.code == code, AffiliatePartner.is_active == True)
        )
        partner = partner_result.scalar_one_or_none()
        if not partner:
            return False

        user_result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_result.scalar_one_or_none()
        if not user or user.affiliate_partner_id:
            return False
        if partner.telegram_id and partner.telegram_id == telegram_id:
            return False

        user.affiliate_partner_id = partner.id
        await session.commit()
        return True


async def record_affiliate_commission(session, user: User, activation_code_id: int | None, plan: str) -> AffiliateCommission | None:
    if not user.affiliate_partner_id:
        return None

    partner = await session.get(AffiliatePartner, user.affiliate_partner_id)
    if not partner or not partner.is_active:
        return None

    sale_amount = plan_price(plan)
    commission_amount = round(sale_amount * float(partner.commission_percent or 0) / 100, 2)
    commission = AffiliateCommission(
        partner_id=partner.id,
        user_id=user.id,
        activation_code_id=activation_code_id,
        plan=plan,
        sale_amount=sale_amount,
        commission_percent=partner.commission_percent,
        commission_amount=commission_amount,
        status="due",
    )
    session.add(commission)
    return commission
