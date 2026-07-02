from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select, delete

from database import get_session
from models import User, Watchlist
from services.market_data import get_current_price_sync
from services.scanner import scan_symbol
from services.subscriptions import can_add_watchlist_item
from utils.validators import is_valid_symbol
from utils.formatter import format_price, format_change
from bot.keyboards.main import (
    back_button, watchlist_actions, main_menu,
)
from bot.keyboards.main import InlineKeyboardBuilder

from . import _user_context

router = Router()

MARKET_MAP = {
    "saudi": "SAUDI",
    "us": "US",
    "crypto": "CRYPTO",
}
MARKET_KEY_MAP = {
    "SAUDI": "saudi",
    "US": "us",
    "CRYPTO": "crypto",
}


async def _get_user(telegram_id: int):
    async with get_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()


@router.callback_query(F.data == "my_watchlist")
async def cb_my_watchlist(callback: CallbackQuery):
    await callback.answer()
    telegram_id = callback.from_user.id
    user = await _get_user(telegram_id)
    if not user:
        await callback.message.edit_text("المستخدم غير موجود.")
        return

    async with get_session() as session:
        stmt = select(Watchlist).where(Watchlist.user_id == user.id).order_by(Watchlist.added_at.desc())
        result = await session.execute(stmt)
        items = result.scalars().all()

    if not items:
        text = "📋 قائمة المتابعة فارغة.\n\nأضف أصولاً إلى قائمة المتابعة من خلال فحص أي أصل واختيار ⭐ إضافة للمراقبة."
        await callback.message.edit_text(text, reply_markup=back_button("main_menu"))
        return

    lines = ["📋 قائمة المتابعة:\n"]
    for i, item in enumerate(items, 1):
        price = get_current_price_sync(item.symbol, item.market)
        price_str = format_price(price) if price else "غير متوفر"
        market_names = {"SAUDI": "🇸🇦 السعودي", "US": "🇺🇸 الأمريكي", "CRYPTO": "₿ كريبتو"}
        market_label = market_names.get(item.market, item.market)
        added = item.added_at.strftime("%Y-%m-%d") if item.added_at else ""
        lines.append(f"{i}. {item.symbol} - {market_label}")
        lines.append(f"   السعر: {price_str}")
        lines.append(f"   تاريخ الإضافة: {added}")
        lines.append("")

    text = "\n".join(lines)

    builder = InlineKeyboardBuilder()
    for item in items[:10]:
        builder.button(text=f"❌ {item.symbol}", callback_data=f"watch_remove:{item.symbol}:{MARKET_KEY_MAP.get(item.market, item.market.lower())}")
    builder.button(text="🔄 مسح الكل", callback_data="watchlist_scan_all")
    builder.button(text="↩️ رجوع", callback_data="main_menu")
    builder.adjust(2, repeat=True)

    await callback.message.edit_text(text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("watch_add:"))
async def cb_watch_add(callback: CallbackQuery):
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

    can = await can_add_watchlist_item(user.id)
    if not can:
        await callback.message.edit_text(
            "🔒 هذه الميزة متاحة للمشتركين فقط.\n\nتواصل مع الدعم: @hidanx11",
            reply_markup=back_button("my_watchlist"),
        )
        return

    async with get_session() as session:
        existing = await session.execute(
            select(Watchlist).where(
                Watchlist.user_id == user.id,
                Watchlist.symbol == symbol,
            )
        )
        if existing.scalar_one_or_none():
            await callback.message.edit_text(
                f"⚠️ {symbol} موجود بالفعل في قائمة المتابعة.",
                reply_markup=back_button("my_watchlist"),
            )
            return

        watchlist_item = Watchlist(
            user_id=user.id,
            symbol=symbol,
            market=market,
        )
        session.add(watchlist_item)
        await session.commit()

    try:
        from services.vip_engagement import award_points

        await award_points(user.id, "watchlist", note=symbol)
    except Exception:
        pass

    await callback.message.edit_text(
        f"✅ تمت إضافة {symbol} إلى قائمة المتابعة.",
        reply_markup=back_button("my_watchlist"),
    )


@router.callback_query(F.data.startswith("watch_remove:"))
async def cb_watch_remove(callback: CallbackQuery):
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

    async with get_session() as session:
        await session.execute(
            delete(Watchlist).where(
                Watchlist.user_id == user.id,
                Watchlist.symbol == symbol,
                Watchlist.market == market,
            )
        )
        await session.commit()

    await callback.message.edit_text(
        f"✅ تم حذف {symbol} من قائمة المتابعة.",
        reply_markup=back_button("my_watchlist"),
    )


@router.callback_query(F.data == "watchlist_scan_all")
async def cb_watchlist_scan_all(callback: CallbackQuery):
    await callback.answer()
    telegram_id = callback.from_user.id
    user = await _get_user(telegram_id)
    if not user:
        await callback.message.edit_text("المستخدم غير موجود.")
        return

    async with get_session() as session:
        stmt = select(Watchlist).where(Watchlist.user_id == user.id)
        result = await session.execute(stmt)
        items = result.scalars().all()

    if not items:
        await callback.message.edit_text("📋 قائمة المتابعة فارغة.", reply_markup=back_button("main_menu"))
        return

    from services.subscriptions import can_scan, increment_scan
    from services.scanner import log_scan_to_db
    from utils.formatter import format_technical_report

    await callback.message.edit_text("جاري مسح جميع العناصر... 🔍")

    results = []
    for item in items:
        can = await can_scan(user.id)
        if not can:
            break

        result = await scan_symbol(item.symbol, item.market)
        if result:
            await increment_scan(user.id)
            score_val = result.get("score")
            score_num = float(score_val.overall) if score_val else None
            await log_scan_to_db(user.id, item.symbol, item.market, "1d", score_num, result.get("current_price"))
            results.append(result)

    if not results:
        await callback.message.edit_text("❌ لم يتم العثور على نتائج صالحة.", reply_markup=back_button("my_watchlist"))
        return

    results.sort(key=lambda r: float(r["score"].overall) if r.get("score") else 0, reverse=True)
    top = results[:5]

    lines = ["📊 نتائج مسح قائمة المتابعة:\n"]
    for r in top:
        sym = r["symbol"]
        price = format_price(r.get("current_price"))
        change = format_change(r.get("change_percent"))
        score = r.get("score")
        score_str = f"{score.overall:.0f}/100" if score else "N/A"
        rating = r.get("rating", "")
        trend = {"uptrend": "📈", "downtrend": "📉", "sideways": "↔️"}.get(r.get("trend", ""), "")
        lines.append(f"{sym} {trend}")
        lines.append(f"   {price} | {change} | {score_str} | {rating}")
        lines.append("")

    text = "\n".join(lines).strip()
    await callback.message.edit_text(text, reply_markup=back_button("my_watchlist"))


@router.callback_query(F.data.startswith("watchlist_add:"))
async def cb_watchlist_add(callback: CallbackQuery):
    await callback.answer()
    market_key = callback.data.split(":")[1].lower()
    market = MARKET_MAP.get(market_key, market_key.upper())
    _user_context[callback.from_user.id] = {"context": "watchlist_add", "market": market}
    from utils.formatter import MARKET_NAMES
    market_name = MARKET_NAMES.get(market, market)
    text = (
        f"⭐ أضف إلى قائمة المتابعة في {market_name}\n\n"
        "اكتب اسم أو رمز الأصل المالي:\n"
        "مثال: الراجحي، أبل، بيتكوين، 1120.SR، AAPL"
    )
    await callback.message.edit_text(text, reply_markup=back_button("main_menu"))


async def handle_watchlist_symbol_input(message: Message):
    telegram_id = message.from_user.id
    ctx = _user_context.get(telegram_id)
    if not ctx or ctx.get("context") != "watchlist_add":
        return

    market = ctx.get("market", "US")
    symbol = message.text.strip().upper()

    if not is_valid_symbol(symbol):
        from services.search_engine import auto_detect_symbol
        detected = await auto_detect_symbol(message.text.strip())
        if detected:
            symbol = detected["symbol"]
            market = detected["market"]
            name = detected.get("name_ar") or detected.get("name_en") or symbol
            await message.answer(f"🔎 تم التعرف على: {name} ({symbol})")
        else:
            await message.answer("❌ ما قدرت أتعرف على الاسم أو الرمز. جرّب: الراجحي، أبل، بيتكوين، 1120.SR، AAPL")
            return

    user = await _get_user(telegram_id)
    if not user:
        await message.answer("المستخدم غير موجود.")
        _user_context.pop(telegram_id, None)
        return

    can = await can_add_watchlist_item(user.id)
    if not can:
        await message.answer(
            "🔒 هذه الميزة متاحة للمشتركين فقط.\n\nتواصل مع الدعم: @hidanx11",
            reply_markup=back_button("my_watchlist"),
        )
        _user_context.pop(telegram_id, None)
        return

    async with get_session() as session:
        existing = await session.execute(
            select(Watchlist).where(
                Watchlist.user_id == user.id,
                Watchlist.symbol == symbol,
            )
        )
        if existing.scalar_one_or_none():
            await message.answer(
                f"⚠️ {symbol} موجود بالفعل في قائمة المتابعة.",
                reply_markup=back_button("my_watchlist"),
            )
            _user_context.pop(telegram_id, None)
            return

        item = Watchlist(
            user_id=user.id,
            symbol=symbol,
            market=market,
        )
        session.add(item)
        await session.commit()

    try:
        from services.vip_engagement import award_points

        await award_points(user.id, "watchlist", note=symbol)
    except Exception:
        pass

    _user_context.pop(telegram_id, None)
    await message.answer(
        f"✅ تمت إضافة {symbol} إلى قائمة المتابعة.",
        reply_markup=back_button("my_watchlist"),
    )
