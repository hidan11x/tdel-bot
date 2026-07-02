import asyncio
import os
import time
from datetime import date
from typing import Any

from aiohttp import web
from loguru import logger
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from config import settings
from database import get_session
from models import (
    AffiliateCommission,
    AffiliatePartner,
    Alert,
    ContestPrediction,
    ErrorLog,
    LoyaltyEvent,
    PortfolioPosition,
    SavedOpportunity,
    ScanLog,
    Symbol,
    User,
    Watchlist,
)
from services.dashboard_auth import verify_dashboard_token
from services.market_data import YahooFinanceProvider, get_current_price_sync, get_ohlcv
from services.scanner import TOP_SYMBOLS
from services.signal_engine import build_signal
from services.indicators import calculate_all, calculate_rsi, find_support_resistance
from services.scoring import calculate_score, get_rating, get_risk_level
from services.subscriptions import can_add_alert, can_add_watchlist_item


RADAR_TTL_SECONDS = 90
_radar_cache: dict[str, Any] = {"expires": 0.0, "items": []}


def _env_value(key: str, default: str = "") -> str:
    value = os.getenv(key, default).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def _json(data: dict[str, Any], status: int = 200) -> web.Response:
    return web.json_response(data, status=status, headers={"Cache-Control": "no-store"})


async def _request_json(request: web.Request) -> dict[str, Any]:
    try:
        data = await request.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _symbol_payload(item: Watchlist | Symbol) -> dict[str, Any]:
    if isinstance(item, Watchlist):
        return {
            "symbol": item.symbol,
            "market": item.market,
            "name_ar": item.note or item.symbol,
            "name_en": item.symbol,
            "sector": "",
            "popular": False,
        }
    return {
        "symbol": item.symbol,
        "market": item.market,
        "name_ar": item.name_ar,
        "name_en": item.name_en,
        "sector": item.sector or item.category or "",
        "popular": bool(item.is_popular),
    }


def _alert_payload(item: Alert) -> dict[str, Any]:
    return {
        "id": item.id,
        "symbol": item.symbol,
        "market": item.market,
        "alert_type": item.alert_type,
        "value": item.value,
        "is_active": bool(item.is_active),
        "triggered": bool(item.triggered),
    }


def _portfolio_payload(item: PortfolioPosition) -> dict[str, Any]:
    current = None
    try:
        current = get_current_price_sync(item.symbol, item.market)
    except Exception:
        current = None

    mark_price = current if current is not None else item.exit_price
    pnl = pnl_pct = value = target_distance_pct = stop_distance_pct = None
    if mark_price is not None:
        multiplier = -1 if item.side == "short" else 1
        pnl = (float(mark_price) - float(item.entry_price)) * float(item.quantity) * multiplier
        cost = abs(float(item.entry_price) * float(item.quantity))
        value = float(mark_price) * float(item.quantity)
        pnl_pct = (pnl / cost * 100) if cost else 0.0
        if item.target_price:
            target_distance_pct = ((float(item.target_price) - float(mark_price)) / float(mark_price)) * 100
        if item.stop_loss:
            stop_distance_pct = ((float(mark_price) - float(item.stop_loss)) / float(mark_price)) * 100

    return {
        "id": item.id,
        "symbol": item.symbol,
        "market": item.market,
        "entry_price": item.entry_price,
        "quantity": item.quantity,
        "target_price": item.target_price,
        "stop_loss": item.stop_loss,
        "side": item.side,
        "status": item.status,
        "exit_price": item.exit_price,
        "note": item.note or "",
        "current_price": current,
        "value": value,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "target_distance_pct": target_distance_pct,
        "stop_distance_pct": stop_distance_pct,
    }


def _saved_opportunity_payload(item: SavedOpportunity) -> dict[str, Any]:
    current = None
    try:
        current = get_current_price_sync(item.symbol, item.market)
    except Exception:
        current = None
    change_since_save = None
    if current is not None and item.entry_price:
        change_since_save = ((float(current) - float(item.entry_price)) / float(item.entry_price)) * 100
    return {
        "id": item.id,
        "symbol": item.symbol,
        "market": item.market,
        "name": item.name or item.symbol,
        "score": item.score,
        "entry_price": item.entry_price,
        "current_price": current,
        "change_since_save": change_since_save,
        "support": item.support,
        "resistance": item.resistance,
        "status": item.status,
        "created_at": item.created_at.isoformat() if item.created_at else "",
    }


def _is_vip(user: User) -> bool:
    return user.telegram_id in settings.admin_ids or user.plan in {"vip", "lifetime"}


async def _authorized_user(request: web.Request) -> User | web.Response:
    try:
        telegram_id = int(request.match_info["telegram_id"])
    except (KeyError, ValueError):
        return web.Response(text="رابط غير صالح", status=400)

    token = request.match_info.get("token", "")
    if not verify_dashboard_token(telegram_id, token):
        return web.Response(text="الرابط غير صالح أو منتهي", status=403)

    async with get_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()

    if not user:
        return web.Response(text="المستخدم غير موجود", status=404)
    if not _is_vip(user):
        return web.Response(text="هذه اللوحة مخصصة لمشتركي VIP فقط", status=403)
    return user


async def dashboard_page(request: web.Request) -> web.Response:
    user = await _authorized_user(request)
    if isinstance(user, web.Response):
        return user

    html = DASHBOARD_HTML.replace("__TG_ID__", str(user.telegram_id)).replace(
        "__TOKEN__", request.match_info["token"]
    )
    return web.Response(text=html, content_type="text/html", charset="utf-8")


async def dashboard_summary(request: web.Request) -> web.Response:
    user = await _authorized_user(request)
    if isinstance(user, web.Response):
        return user

    today = settings.today()
    async with get_session() as session:
        watchlist = (
            await session.execute(
                select(Watchlist).where(Watchlist.user_id == user.id).order_by(Watchlist.added_at.desc())
            )
        ).scalars().all()
        alerts_count = (
            await session.execute(
                select(func.count(Alert.id)).where(Alert.user_id == user.id, Alert.is_active == True)
            )
        ).scalar() or 0
        alerts = (
            await session.execute(
                select(Alert)
                .where(Alert.user_id == user.id)
                .order_by(Alert.created_at.desc())
                .limit(20)
            )
        ).scalars().all()
        positions = (
            await session.execute(
                select(PortfolioPosition)
                .where(PortfolioPosition.user_id == user.id)
                .order_by(PortfolioPosition.created_at.desc())
                .limit(50)
            )
        ).scalars().all()
        saved_opportunities = (
            await session.execute(
                select(SavedOpportunity)
                .where(SavedOpportunity.user_id == user.id)
                .order_by(SavedOpportunity.created_at.desc())
                .limit(30)
            )
        ).scalars().all()
        scans_today = (
            await session.execute(
                select(func.count(ScanLog.id)).where(
                    ScanLog.user_id == user.id,
                    func.date(ScanLog.created_at) == today,
                )
            )
        ).scalar() or 0
        total_scans = (
            await session.execute(select(func.count(ScanLog.id)).where(ScanLog.user_id == user.id))
        ).scalar() or 0
        last_scans = (
            await session.execute(
                select(ScanLog)
                .where(ScanLog.user_id == user.id)
                .order_by(ScanLog.created_at.desc())
                .limit(5)
            )
        ).scalars().all()
        errors_today = (
            await session.execute(
                select(func.count(ErrorLog.id)).where(func.date(ErrorLog.created_at) == today)
            )
        ).scalar() or 0
        loyalty_points = (
            await session.execute(
                select(func.coalesce(func.sum(LoyaltyEvent.points), 0)).where(LoyaltyEvent.user_id == user.id)
            )
        ).scalar() or 0
        contest_today = (
            await session.execute(
                select(ContestPrediction).where(
                    ContestPrediction.user_id == user.id,
                    ContestPrediction.prediction_date == today,
                )
            )
        ).scalar_one_or_none()

    market_status = YahooFinanceProvider.get_market_status()
    watchlist_symbols = [_symbol_payload(item) for item in watchlist[:30]]
    symbols = list(watchlist_symbols)
    if not symbols:
        symbols = [
            {"symbol": "1120.SR", "market": "SAUDI", "name_ar": "الراجحي", "name_en": "Al Rajhi", "sector": "", "popular": True},
            {"symbol": "AAPL", "market": "US", "name_ar": "Apple", "name_en": "Apple", "sector": "", "popular": True},
            {"symbol": "BTCUSDT", "market": "CRYPTO", "name_ar": "Bitcoin", "name_en": "Bitcoin", "sector": "", "popular": True},
        ]

    portfolio_items = [_portfolio_payload(item) for item in positions]
    open_positions = [item for item in portfolio_items if item["status"] == "open"]
    total_value = sum(float(item["value"] or 0) for item in open_positions)
    total_pnl = sum(float(item["pnl"] or 0) for item in open_positions)
    closed_positions = [item for item in portfolio_items if item["status"] == "closed"]
    winning_closed = [item for item in closed_positions if float(item["pnl"] or 0) > 0]
    win_rate = (len(winning_closed) / len(closed_positions) * 100) if closed_positions else None
    best_position = max(portfolio_items, key=lambda item: float(item["pnl"] or 0), default=None)
    worst_position = min(portfolio_items, key=lambda item: float(item["pnl"] or 0), default=None)
    saved_payload = [_saved_opportunity_payload(item) for item in saved_opportunities]
    saved_winners = [item for item in saved_payload if float(item["change_since_save"] or 0) > 0]

    return _json(
        {
            "user": {
                "name": user.first_name,
                "username": user.username or "",
                "plan": user.plan,
                "subscription_end": user.subscription_end.isoformat() if user.subscription_end else "",
            },
            "cards": {
                "watchlist": len(watchlist),
                "alerts": alerts_count,
                "scans_today": scans_today,
                "total_scans": total_scans,
                "errors_today": errors_today,
            },
            "markets": market_status,
            "symbols": symbols,
            "watchlist": watchlist_symbols,
            "alerts": [_alert_payload(item) for item in alerts],
            "portfolio": {
                "items": portfolio_items,
                "open_count": len(open_positions),
                "total_value": total_value,
                "total_pnl": total_pnl,
                "closed_count": len(closed_positions),
                "win_rate": win_rate,
                "best": best_position,
                "worst": worst_position,
            },
            "saved_opportunities": {
                "items": saved_payload,
                "count": len(saved_payload),
                "winners": len(saved_winners),
            },
            "engagement": {
                "loyalty_points": int(loyalty_points),
                "next_reward_points": max(0, 120 - (int(loyalty_points) % 120)),
                "contest_today": {
                    "symbol": contest_today.symbol,
                    "market": contest_today.market,
                    "target_price": contest_today.target_price,
                    "score_points": contest_today.score_points,
                }
                if contest_today
                else None,
            },
            "last_scans": [
                {
                    "symbol": scan.symbol,
                    "market": scan.market,
                    "score": scan.score,
                    "signal": scan.signal or "",
                    "created_at": scan.created_at.isoformat() if scan.created_at else "",
                }
                for scan in last_scans
            ],
            "server_time": settings.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    )


async def dashboard_radar(request: web.Request) -> web.Response:
    user = await _authorized_user(request)
    if isinstance(user, web.Response):
        return user

    now = time.time()
    if _radar_cache["expires"] > now:
        return _json({"items": _radar_cache["items"], "cached": True})

    from services.opportunities import flatten_radar, get_radar_opportunities

    radar = await get_radar_opportunities(vip=True)
    items = []
    for result in flatten_radar(radar)[:9]:
        signal = build_signal(result)
        items.append(
            {
                "symbol": signal.symbol,
                "market": signal.market,
                "name": signal.name_ar if signal.name_ar != signal.symbol else signal.name_en,
                "price": signal.current_price,
                "change": signal.change_percent,
                "score": round(signal.score),
                "confidence": signal.confidence,
                "trend": signal.trend,
                "risk": signal.risk_level,
                "support": signal.support,
                "resistance": signal.resistance,
            }
        )

    _radar_cache.update({"expires": now + RADAR_TTL_SECONDS, "items": items})
    return _json({"items": items, "cached": False})


async def dashboard_chart(request: web.Request) -> web.Response:
    user = await _authorized_user(request)
    if isinstance(user, web.Response):
        return user

    symbol = request.query.get("symbol", "BTCUSDT").strip().upper()
    market = request.query.get("market", "CRYPTO").strip().upper()
    interval = request.query.get("interval", "1d").strip()
    if interval not in {"15m", "1h", "4h", "1d", "1wk"}:
        interval = "1d"

    data = await asyncio.to_thread(get_ohlcv, symbol, market, interval, 160)
    if not data:
        return _json({"data": [], "message": "لا توجد بيانات كافية"}, status=404)

    closes = [float(row["close"]) for row in data if row.get("close") is not None]
    support = resistance = latest_rsi = score_value = None
    rating = risk = trend = None
    change_percent = 0.0
    if closes:
        support, resistance = find_support_resistance(closes[-80:], lookback=min(30, len(closes)))
        latest_rsi = calculate_rsi(closes[-50:]) if len(closes) >= 15 else None
        prev_close = closes[-2] if len(closes) >= 2 else closes[-1]
        change_percent = ((closes[-1] - prev_close) / prev_close * 100) if prev_close else 0.0
        try:
            import pandas as pd

            df = pd.DataFrame(data)
            indicators = calculate_all(df)
            indicators["current_price"] = closes[-1]
            score = calculate_score(indicators)
            score_value = round(float(score.overall), 1)
            rating = get_rating(score.overall)
            risk = get_risk_level(score.risk_score)
            trend = indicators.get("trend")
        except Exception:
            logger.exception("dashboard chart score failed for {} {}", symbol, market)

    return _json(
        {
            "symbol": symbol,
            "market": market,
            "interval": interval,
            "support": support,
            "resistance": resistance,
            "rsi": latest_rsi,
            "last_price": closes[-1] if closes else None,
            "change_percent": change_percent,
            "score": score_value,
            "rating": rating,
            "risk": risk,
            "trend": trend,
            "data": [
                {
                    "time": int(row["timestamp"]),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume", 0)),
                }
                for row in data[-160:]
            ],
        }
    )


async def dashboard_symbols(request: web.Request) -> web.Response:
    user = await _authorized_user(request)
    if isinstance(user, web.Response):
        return user

    market = request.query.get("market", "ALL").strip().upper()
    query = request.query.get("q", "").strip()
    try:
        limit = min(500, max(20, int(request.query.get("limit", "120"))))
    except ValueError:
        limit = 80

    stmt = select(Symbol).where(Symbol.is_active == True)
    if market in {"SAUDI", "US", "CRYPTO"}:
        stmt = stmt.where(Symbol.market == market)
    if query:
        like = f"%{query}%"
        stmt = stmt.where(
            (Symbol.symbol.ilike(like))
            | (Symbol.name_ar.ilike(like))
            | (Symbol.name_en.ilike(like))
        )
    stmt = stmt.order_by(Symbol.market, Symbol.is_popular.desc(), Symbol.sort_order, Symbol.symbol).limit(limit)

    async with get_session() as session:
        symbols = list((await session.execute(stmt)).scalars().all())

    items = [
        {
            "symbol": item.symbol,
            "market": item.market,
            "name_ar": item.name_ar,
            "name_en": item.name_en,
            "sector": item.sector or item.category or "",
            "popular": bool(item.is_popular),
        }
        for item in symbols
    ]

    if not items and not query:
        markets = ["SAUDI", "US", "CRYPTO"] if market == "ALL" else [market]
        for market_key in markets:
            if len(items) >= limit:
                break
            for symbol in TOP_SYMBOLS.get(market_key, [])[:limit]:
                if len(items) >= limit:
                    break
                items.append(
                    {
                        "symbol": symbol,
                        "market": market_key,
                        "name_ar": symbol,
                        "name_en": symbol,
                        "sector": "",
                        "popular": True,
                    }
                )

    return _json({"items": items[:limit], "market": market, "query": query})


async def dashboard_watchlist_action(request: web.Request) -> web.Response:
    user = await _authorized_user(request)
    if isinstance(user, web.Response):
        return user

    data = await _request_json(request)
    symbol = str(data.get("symbol", "")).strip().upper()
    market = str(data.get("market", "")).strip().upper()
    action = str(data.get("action", "add")).strip().lower()
    if not symbol or market not in {"SAUDI", "US", "CRYPTO"}:
        return _json({"ok": False, "message": "رمز أو سوق غير صالح"}, status=400)

    async with get_session() as session:
        if action == "remove":
            await session.execute(
                delete(Watchlist).where(
                    Watchlist.user_id == user.id,
                    Watchlist.symbol == symbol,
                    Watchlist.market == market,
                )
            )
            await session.commit()
            return _json({"ok": True, "message": "تم الحذف من قائمة المتابعة"})

        existing = (
            await session.execute(
                select(Watchlist).where(
                    Watchlist.user_id == user.id,
                    Watchlist.symbol == symbol,
                    Watchlist.market == market,
                )
            )
        ).scalar_one_or_none()
        if existing:
            return _json({"ok": True, "message": "الرمز موجود بالفعل في قائمتك"})

    if not await can_add_watchlist_item(user.id):
        return _json({"ok": False, "message": "وصلت للحد المسموح لقائمة المتابعة"}, status=403)

    async with get_session() as session:
        item = Watchlist(user_id=user.id, symbol=symbol, market=market)
        session.add(item)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return _json({"ok": True, "message": "الرمز موجود بالفعل في قائمتك"})

    return _json({"ok": True, "message": "تمت الإضافة إلى قائمة المتابعة"})


async def dashboard_alert_action(request: web.Request) -> web.Response:
    user = await _authorized_user(request)
    if isinstance(user, web.Response):
        return user

    data = await _request_json(request)
    symbol = str(data.get("symbol", "")).strip().upper()
    market = str(data.get("market", "")).strip().upper()
    alert_type = str(data.get("alert_type", "price_above")).strip()
    allowed_types = {
        "price_above",
        "price_below",
        "rsi_above",
        "rsi_below",
        "near_support",
        "near_resistance",
        "price_change_percent",
    }
    if not symbol or market not in {"SAUDI", "US", "CRYPTO"} or alert_type not in allowed_types:
        return _json({"ok": False, "message": "بيانات التنبيه غير صالحة"}, status=400)

    try:
        value = float(str(data.get("value", "")).replace(",", ""))
    except ValueError:
        return _json({"ok": False, "message": "قيمة التنبيه لازم تكون رقم"}, status=400)

    if not await can_add_alert(user.id):
        return _json({"ok": False, "message": "وصلت للحد المسموح للتنبيهات"}, status=403)

    async with get_session() as session:
        alert = Alert(
            user_id=user.id,
            symbol=symbol,
            market=market,
            alert_type=alert_type,
            value=value,
        )
        session.add(alert)
        await session.commit()
        await session.refresh(alert)

    return _json({"ok": True, "message": "تم إنشاء التنبيه", "alert": _alert_payload(alert)})


async def dashboard_portfolio_action(request: web.Request) -> web.Response:
    user = await _authorized_user(request)
    if isinstance(user, web.Response):
        return user

    data = await _request_json(request)
    action = str(data.get("action", "add")).strip().lower()

    if action == "close":
        try:
            position_id = int(data.get("id"))
        except (TypeError, ValueError):
            return _json({"ok": False, "message": "رقم الصفقة غير صالح"}, status=400)

        async with get_session() as session:
            position = await session.get(PortfolioPosition, position_id)
            if not position or position.user_id != user.id:
                return _json({"ok": False, "message": "الصفقة غير موجودة"}, status=404)
            current = get_current_price_sync(position.symbol, position.market)
            position.status = "closed"
            position.exit_price = current or position.entry_price
            position.closed_at = settings.now()
            await session.commit()
        return _json({"ok": True, "message": "تم إغلاق الصفقة"})

    symbol = str(data.get("symbol", "")).strip().upper()
    market = str(data.get("market", "")).strip().upper()
    side = str(data.get("side", "long")).strip().lower()
    note = str(data.get("note", "")).strip()[:180]
    if not symbol or market not in {"SAUDI", "US", "CRYPTO"} or side not in {"long", "short"}:
        return _json({"ok": False, "message": "بيانات الصفقة غير صالحة"}, status=400)

    try:
        entry_price = float(str(data.get("entry_price", "")).replace(",", ""))
        quantity = float(str(data.get("quantity", "")).replace(",", ""))
        target_price = data.get("target_price")
        stop_loss = data.get("stop_loss")
        target_price = float(str(target_price).replace(",", "")) if str(target_price or "").strip() else None
        stop_loss = float(str(stop_loss).replace(",", "")) if str(stop_loss or "").strip() else None
    except ValueError:
        return _json({"ok": False, "message": "سعر الدخول والكمية والهدف والوقف لازم تكون أرقام"}, status=400)

    if entry_price <= 0 or quantity <= 0:
        return _json({"ok": False, "message": "سعر الدخول والكمية لازم تكون أكبر من صفر"}, status=400)

    async with get_session() as session:
        position = PortfolioPosition(
            user_id=user.id,
            symbol=symbol,
            market=market,
            entry_price=entry_price,
            quantity=quantity,
            target_price=target_price,
            stop_loss=stop_loss,
            side=side,
            note=note,
        )
        session.add(position)
        await session.commit()
        await session.refresh(position)

    return _json({"ok": True, "message": "تمت إضافة الصفقة", "position": _portfolio_payload(position)})


async def dashboard_saved_opportunity_action(request: web.Request) -> web.Response:
    user = await _authorized_user(request)
    if isinstance(user, web.Response):
        return user

    data = await _request_json(request)
    action = str(data.get("action", "save")).strip().lower()
    if action == "remove":
        try:
            item_id = int(data.get("id"))
        except (TypeError, ValueError):
            return _json({"ok": False, "message": "رقم الفرصة غير صالح"}, status=400)
        async with get_session() as session:
            item = await session.get(SavedOpportunity, item_id)
            if not item or item.user_id != user.id:
                return _json({"ok": False, "message": "الفرصة غير موجودة"}, status=404)
            await session.delete(item)
            await session.commit()
        return _json({"ok": True, "message": "تم حذف الفرصة"})

    symbol = str(data.get("symbol", "")).strip().upper()
    market = str(data.get("market", "")).strip().upper()
    if not symbol or market not in {"SAUDI", "US", "CRYPTO"}:
        return _json({"ok": False, "message": "رمز أو سوق غير صالح"}, status=400)

    def _optional_float(key: str):
        value = data.get(key)
        if value in (None, ""):
            return None
        try:
            return float(str(value).replace(",", ""))
        except ValueError:
            return None

    async with get_session() as session:
        existing = (
            await session.execute(
                select(SavedOpportunity).where(
                    SavedOpportunity.user_id == user.id,
                    SavedOpportunity.symbol == symbol,
                    SavedOpportunity.market == market,
                )
            )
        ).scalar_one_or_none()
        if existing:
            return _json({"ok": True, "message": "الفرصة محفوظة بالفعل", "item": _saved_opportunity_payload(existing)})

        item = SavedOpportunity(
            user_id=user.id,
            symbol=symbol,
            market=market,
            name=str(data.get("name") or symbol)[:120],
            score=_optional_float("score"),
            entry_price=_optional_float("entry_price"),
            support=_optional_float("support"),
            resistance=_optional_float("resistance"),
            note=str(data.get("note") or "")[:180],
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)

    return _json({"ok": True, "message": "تم حفظ الفرصة", "item": _saved_opportunity_payload(item)})


async def dashboard_ai_action(request: web.Request) -> web.Response:
    user = await _authorized_user(request)
    if isinstance(user, web.Response):
        return user

    data = await _request_json(request)
    prompt = str(data.get("prompt") or "").strip()
    if len(prompt) < 2:
        return _json({"ok": False, "message": "اكتب سؤالك أولاً"}, status=400)
    if len(prompt) > 1200:
        prompt = prompt[:1200]

    try:
        from services.ai_assistant import build_ai_reply

        reply, remaining, limit = await build_ai_reply(user, user.telegram_id, prompt)
        return _json({"ok": True, "reply": reply, "remaining": remaining, "limit": limit})
    except Exception:
        logger.exception("dashboard AI action failed for {}", user.telegram_id)
        return _json({"ok": False, "message": "تعذر تشغيل مساعد الذكاء حالياً"}, status=500)


async def dashboard_affiliates(request: web.Request) -> web.Response:
    user = await _authorized_user(request)
    if isinstance(user, web.Response):
        return user
    if user.telegram_id not in settings.admin_ids:
        return _json({"ok": False, "message": "هذه الصفحة للأدمن فقط", "items": []}, status=403)

    async with get_session() as session:
        result = await session.execute(select(AffiliatePartner).order_by(AffiliatePartner.id.desc()).limit(50))
        partners = result.scalars().all()
        items = []
        total_due = total_paid = total_users = 0
        for partner in partners:
            users_count = (
                await session.execute(select(func.count(User.id)).where(User.affiliate_partner_id == partner.id))
            ).scalar() or 0
            due = (
                await session.execute(
                    select(func.sum(AffiliateCommission.commission_amount)).where(
                        AffiliateCommission.partner_id == partner.id,
                        AffiliateCommission.status == "due",
                    )
                )
            ).scalar() or 0
            paid = (
                await session.execute(
                    select(func.sum(AffiliateCommission.commission_amount)).where(
                        AffiliateCommission.partner_id == partner.id,
                        AffiliateCommission.status == "paid",
                    )
                )
            ).scalar() or 0
            sales = (
                await session.execute(
                    select(func.sum(AffiliateCommission.sale_amount)).where(
                        AffiliateCommission.partner_id == partner.id
                    )
                )
            ).scalar() or 0
            commissions = (
                await session.execute(
                    select(func.count(AffiliateCommission.id)).where(
                        AffiliateCommission.partner_id == partner.id
                    )
                )
            ).scalar() or 0
            total_due += float(due or 0)
            total_paid += float(paid or 0)
            total_users += int(users_count or 0)
            items.append(
                {
                    "id": partner.id,
                    "name": partner.name,
                    "code": partner.code,
                    "telegram_id": partner.telegram_id,
                    "commission_percent": partner.commission_percent,
                    "is_active": bool(partner.is_active),
                    "users": int(users_count or 0),
                    "sales": float(sales or 0),
                    "due": float(due or 0),
                    "paid": float(paid or 0),
                    "commissions": int(commissions or 0),
                }
            )

    return _json(
        {
            "ok": True,
            "items": items,
            "summary": {"users": total_users, "due": total_due, "paid": total_paid, "partners": len(items)},
        }
    )


async def dashboard_health(request: web.Request) -> web.Response:
    return _json({"ok": True, "service": "dashboard", "date": date.today().isoformat()})


def create_dashboard_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", dashboard_health)
    app.router.add_get("/dashboard/{telegram_id}/{token}", dashboard_page)
    app.router.add_get("/api/dashboard/{telegram_id}/{token}/summary", dashboard_summary)
    app.router.add_get("/api/dashboard/{telegram_id}/{token}/radar", dashboard_radar)
    app.router.add_get("/api/dashboard/{telegram_id}/{token}/chart", dashboard_chart)
    app.router.add_get("/api/dashboard/{telegram_id}/{token}/symbols", dashboard_symbols)
    app.router.add_post("/api/dashboard/{telegram_id}/{token}/watchlist", dashboard_watchlist_action)
    app.router.add_post("/api/dashboard/{telegram_id}/{token}/alerts", dashboard_alert_action)
    app.router.add_post("/api/dashboard/{telegram_id}/{token}/portfolio", dashboard_portfolio_action)
    app.router.add_post("/api/dashboard/{telegram_id}/{token}/opportunities", dashboard_saved_opportunity_action)
    app.router.add_post("/api/dashboard/{telegram_id}/{token}/ai", dashboard_ai_action)
    app.router.add_get("/api/dashboard/{telegram_id}/{token}/affiliates", dashboard_affiliates)
    return app


async def start_dashboard_server() -> web.AppRunner:
    app = create_dashboard_app()
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(_env_value("DASHBOARD_PORT") or _env_value("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("VIP dashboard started on port {}", port)
    return runner


DASHBOARD_HTML = r"""
<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <title>لوحة VIP | تداول بوت</title>
  <script src="https://unpkg.com/lightweight-charts@4.2.3/dist/lightweight-charts.standalone.production.js"></script>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0e1116;
      --panel: #171c23;
      --panel-2: #1e252e;
      --text: #f4f7fb;
      --muted: #96a2b4;
      --line: #2b3441;
      --teal: #27d3b2;
      --amber: #f4b860;
      --green: #39d98a;
      --red: #ff6b6b;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Tahoma, Arial, sans-serif;
    }
    .shell { display: grid; grid-template-columns: 248px 1fr; min-height: 100vh; }
    aside {
      border-left: 1px solid var(--line);
      background: #11161d;
      padding: 22px 18px;
      position: sticky;
      top: 0;
      height: 100vh;
    }
    .brand { font-size: 22px; font-weight: 800; margin-bottom: 24px; }
    .nav { display: grid; gap: 8px; }
    .nav button {
      width: 100%;
      border: 0;
      border-radius: 8px;
      padding: 12px 14px;
      color: var(--muted);
      background: transparent;
      text-align: right;
      font: inherit;
    }
    .nav button.active, .nav button:hover { color: var(--text); background: var(--panel-2); }
    main { padding: 22px; max-width: 1440px; width: 100%; margin: 0 auto; }
    header { display: flex; justify-content: space-between; gap: 12px; align-items: center; margin-bottom: 18px; }
    h1 { margin: 0; font-size: 24px; letter-spacing: 0; }
    .sub { color: var(--muted); font-size: 14px; margin-top: 6px; }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-height: 34px;
      padding: 7px 11px;
      border-radius: 8px;
      background: rgba(39, 211, 178, .12);
      color: var(--teal);
      border: 1px solid rgba(39, 211, 178, .25);
      white-space: nowrap;
    }
    .grid { display: grid; gap: 14px; }
    .cards { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .layout { grid-template-columns: 1.35fr .8fr; align-items: start; margin-top: 14px; }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      min-width: 0;
    }
    .metric .label { color: var(--muted); font-size: 13px; }
    .metric .value { font-size: 30px; font-weight: 800; margin-top: 8px; }
    .panel h2 { font-size: 17px; margin: 0 0 13px; }
    .market-row, .scan-row, .symbol-row {
      display: grid;
      gap: 8px;
      padding: 12px 0;
      border-top: 1px solid var(--line);
    }
    .market-row:first-of-type, .scan-row:first-of-type, .symbol-row:first-of-type { border-top: 0; }
    .row-top { display: flex; justify-content: space-between; gap: 12px; align-items: center; }
    .name { font-weight: 750; }
    .muted { color: var(--muted); }
    .score { color: var(--amber); font-weight: 800; }
    .up { color: var(--green); }
    .down { color: var(--red); }
    .status { color: var(--muted); min-height: 22px; }
    .chart-tools { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
    input, select, .seg button, .market-tabs button, .action-panel button, .portfolio-form button {
      border: 1px solid var(--line);
      background: var(--panel-2);
      color: var(--text);
      border-radius: 8px;
      padding: 9px 10px;
      font: inherit;
    }
    input { width: 100%; }
    .seg { display: inline-flex; gap: 6px; }
    .symbol-tools { display: grid; gap: 9px; margin-bottom: 10px; }
    .market-tabs { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
    .seg button.active, .market-tabs button.active { border-color: var(--teal); color: var(--teal); }
    .symbol-row { cursor: pointer; }
    .symbol-row:hover { background: rgba(255,255,255,.03); }
    .highlight {
      border: 1px solid rgba(244, 184, 96, .35);
      background: rgba(244, 184, 96, .08);
      border-radius: 8px;
      padding: 12px;
      margin-bottom: 10px;
      cursor: pointer;
    }
    .action-panel {
      display: grid;
      grid-template-columns: 1fr;
      gap: 10px;
      margin-top: 12px;
      border-top: 1px solid var(--line);
      padding-top: 12px;
    }
    .action-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
    .insight-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
    .insight-card { background: var(--panel-2); border: 1px solid var(--line); border-radius: 8px; padding: 10px; min-height: 70px; }
    .insight-card span { display: block; color: var(--muted); font-size: 12px; margin-bottom: 6px; }
    .insight-card strong { display: block; font-size: 18px; line-height: 1.25; overflow-wrap: anywhere; }
    .ai-chat {
      display: grid;
      gap: 10px;
      max-height: 360px;
      overflow: auto;
      padding: 4px;
      margin-bottom: 10px;
    }
    .ai-msg {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px 12px;
      white-space: pre-wrap;
      line-height: 1.65;
      background: var(--panel-2);
    }
    .ai-msg.user {
      margin-right: 18%;
      background: rgba(39, 211, 178, .1);
      border-color: rgba(39, 211, 178, .28);
    }
    .ai-msg.bot {
      margin-left: 12%;
      background: rgba(255,255,255,.035);
    }
    .ai-suggestions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-bottom: 10px; }
    .ai-suggestions button, .ai-form button {
      border: 1px solid var(--line);
      background: var(--panel-2);
      color: var(--text);
      border-radius: 8px;
      padding: 9px 10px;
      font: inherit;
    }
    .ai-form { display: grid; grid-template-columns: 1fr auto; gap: 8px; }
    button.primary, .action-panel button.primary { background: rgba(39, 211, 178, .14); border-color: rgba(39, 211, 178, .35); color: var(--teal); }
    .action-panel button.warn { background: rgba(244, 184, 96, .12); border-color: rgba(244, 184, 96, .32); color: var(--amber); }
    button:disabled { opacity: .55; cursor: not-allowed; }
    .feedback { color: var(--muted); min-height: 20px; }
    .mini-select { min-width: 170px; }
    .portfolio-form { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin-bottom: 12px; }
    .portfolio-form button { grid-column: 1 / -1; }
    .portfolio-summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 8px; }
    .portfolio-summary div { background: var(--panel-2); border-radius: 8px; padding: 10px; }
    .data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
    .data-table th, .data-table td { border-bottom: 1px solid var(--line); padding: 9px 7px; text-align: right; vertical-align: top; }
    .data-table th { color: var(--muted); font-weight: 650; }
    .table-wrap { overflow-x: auto; }
    .tiny-btn {
      border: 1px solid var(--line);
      background: transparent;
      color: var(--muted);
      border-radius: 8px;
      padding: 6px 8px;
      font: inherit;
    }
    #chart { width: 100%; height: 390px; }
    .health { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
    .health div { background: var(--panel-2); border-radius: 8px; padding: 12px; }
    .small { font-size: 13px; }
    #overview-section, #opportunities-section, #chart-section, #ai-section, #brief-section, #watch-section, #alerts-section,
    #affiliates-section,
    #system-section, #portfolio-section, #saved-section, #activity-section, #symbols-section {
      scroll-margin-top: 18px;
    }
    @media (max-width: 980px) {
      .shell { display: block; }
      aside { position: static; height: auto; border-left: 0; border-bottom: 1px solid var(--line); }
      .nav { grid-template-columns: repeat(3, 1fr); }
      .cards, .layout { grid-template-columns: 1fr; }
      main { padding: 16px; }
      header { align-items: flex-start; flex-direction: column; }
      #chart { height: 330px; }
    }
    @media (max-width: 560px) {
      .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .nav { grid-template-columns: repeat(2, 1fr); }
      .metric .value { font-size: 24px; }
      .health { grid-template-columns: 1fr; }
      .portfolio-form, .portfolio-summary { grid-template-columns: 1fr; }
      .insight-grid, .ai-suggestions, .ai-form { grid-template-columns: 1fr; }
      .ai-msg.user, .ai-msg.bot { margin-left: 0; margin-right: 0; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <aside>
      <div class="brand">تداول بوت VIP</div>
      <div class="nav">
        <button class="active" data-target="overview-section">لوحتي</button>
        <button data-target="opportunities-section">الفرص</button>
        <button data-target="chart-section">الشارت</button>
        <button data-target="ai-section">الذكاء</button>
        <button data-target="watch-section">المتابعة</button>
        <button data-target="alerts-section">التنبيهات</button>
        <button data-target="affiliates-section">الشركاء</button>
        <button data-target="system-section">النظام</button>
      </div>
    </aside>
    <main>
      <header>
        <div>
          <h1>لوحة المتداول</h1>
          <div class="sub" id="welcome">جاري تحميل بيانات الحساب...</div>
        </div>
        <div class="badge">متصل مباشر</div>
      </header>

      <section class="grid cards" id="overview-section">
        <div class="panel metric"><div class="label">قائمتي</div><div class="value" id="m-watch">-</div></div>
        <div class="panel metric"><div class="label">تنبيهاتي</div><div class="value" id="m-alerts">-</div></div>
        <div class="panel metric"><div class="label">فحوصات اليوم</div><div class="value" id="m-scans">-</div></div>
        <div class="panel metric"><div class="label">إجمالي الفحوصات</div><div class="value" id="m-total">-</div></div>
      </section>

      <section class="grid layout">
        <div class="grid">
          <div class="panel" id="opportunities-section">
            <h2>رادار الفرص</h2>
            <div id="radar" class="status">جاري تشغيل الرادار...</div>
          </div>
          <div class="panel" id="chart-section">
            <div class="row-top">
              <h2>الشارت الذكي</h2>
              <span class="muted small" id="chart-status">جاهز</span>
            </div>
            <div class="chart-tools">
              <select id="symbol-select"></select>
              <div class="seg" id="intervals">
                <button data-i="15m">15m</button>
                <button data-i="1h">1h</button>
                <button data-i="4h">4h</button>
                <button data-i="1d" class="active">1d</button>
              </div>
            </div>
            <div id="chart"></div>
            <div class="action-panel">
              <div class="row-top">
                <span class="name" id="selected-symbol">-</span>
                <span class="muted small" id="chart-meta">دعم ومقاومة وRSI تظهر بعد تحميل الشارت</span>
              </div>
              <div class="insight-grid" id="chart-insights">
                <div class="insight-card"><span>السكور</span><strong id="ins-score">-</strong></div>
                <div class="insight-card"><span>الاتجاه</span><strong id="ins-trend">-</strong></div>
                <div class="insight-card"><span>المخاطرة</span><strong id="ins-risk">-</strong></div>
                <div class="insight-card"><span>التغير</span><strong id="ins-change">-</strong></div>
              </div>
              <div class="action-row">
                <button class="primary" id="add-watch">إضافة للقائمة</button>
                <button class="warn" id="remove-watch">حذف من القائمة</button>
                <button id="save-opportunity">حفظ فرصة</button>
                <select class="mini-select" id="alert-type">
                  <option value="price_above">السعر فوق</option>
                  <option value="price_below">السعر تحت</option>
                  <option value="rsi_above">RSI فوق</option>
                  <option value="rsi_below">RSI تحت</option>
                  <option value="near_support">قرب الدعم</option>
                  <option value="near_resistance">قرب المقاومة</option>
                  <option value="price_change_percent">تغير يومي %</option>
                </select>
                <input class="mini-select" id="alert-value" inputmode="decimal" placeholder="القيمة" />
                <button class="primary" id="create-alert">إنشاء تنبيه</button>
              </div>
              <div class="action-row">
                <button id="smart-resistance">تنبيه اختراق المقاومة</button>
                <button id="smart-support">تنبيه كسر الدعم</button>
                <button id="smart-rsi-low">RSI أقل من 30</button>
                <button id="smart-rsi-high">RSI أعلى من 70</button>
              </div>
              <div class="feedback" id="action-feedback"></div>
            </div>
          </div>
        </div>

        <div class="grid">
          <div class="panel" id="system-section">
            <h2>حالة الأسواق</h2>
            <div class="health">
              <div><div class="muted small">السعودي</div><strong id="s-saudi">-</strong></div>
              <div><div class="muted small">الأمريكي</div><strong id="s-us">-</strong></div>
              <div><div class="muted small">الكريبتو</div><strong id="s-crypto">-</strong></div>
            </div>
          </div>
          <div class="panel" id="brief-section">
            <h2>ملخص VIP اليوم</h2>
            <div id="vip-brief" class="status">جاري تجهيز الملخص...</div>
          </div>
          <div class="panel" id="ai-section">
            <div class="row-top">
              <h2>مساعد VIP الذكي</h2>
              <span class="muted small" id="ai-limit">Gemini</span>
            </div>
            <div id="ai-chat" class="ai-chat">
              <div class="ai-msg bot">اختر رمز من الشارت واسألني عن القراءة، المخاطرة، الدعم والمقاومة، أو خطة متابعة بسيطة.</div>
            </div>
            <div class="ai-suggestions">
              <button data-ai-prompt="حلل الرمز الحالي باختصار واذكر أهم مستويات المتابعة">حلل الرمز</button>
              <button data-ai-prompt="وش أهم المخاطر في الرمز الحالي؟">المخاطر</button>
              <button data-ai-prompt="اعطني خطة متابعة للرمز الحالي مع دعم ومقاومة وتنبيه مناسب">خطة متابعة</button>
              <button data-ai-prompt="قارن قراءة الرمز الحالي مع السوق الحالي واذكر هل الانتظار أفضل">قرار سريع</button>
            </div>
            <div class="ai-form">
              <input id="ai-input" placeholder="اكتب سؤالك عن الرمز الحالي أو السوق" autocomplete="off" />
              <button class="primary" id="ai-send">إرسال</button>
            </div>
            <div class="feedback" id="ai-feedback"></div>
          </div>
          <div class="panel" id="affiliates-section">
            <div class="row-top">
              <h2>لوحة الشركاء</h2>
              <span class="muted small" id="affiliates-status">للأدمن</span>
            </div>
            <div class="portfolio-summary">
              <div><div class="muted small">الشركاء</div><strong id="af-count">-</strong></div>
              <div><div class="muted small">المستحق</div><strong id="af-due">-</strong></div>
              <div><div class="muted small">المدفوع</div><strong id="af-paid">-</strong></div>
            </div>
            <div id="affiliates" class="status">جاري تحميل الشركاء...</div>
          </div>
          <div class="panel" id="watch-section">
            <h2>قائمتي</h2>
            <div id="watchlist" class="status">جاري التحميل...</div>
          </div>
          <div class="panel" id="alerts-section">
            <h2>تنبيهاتي</h2>
            <div id="alerts" class="status">جاري التحميل...</div>
          </div>
          <div class="panel" id="portfolio-section">
            <h2>محفظتي التجريبية</h2>
            <div class="portfolio-summary">
              <div><div class="muted small">صفقات مفتوحة</div><strong id="pf-count">-</strong></div>
              <div><div class="muted small">القيمة</div><strong id="pf-value">-</strong></div>
              <div><div class="muted small">الربح/الخسارة</div><strong id="pf-pnl">-</strong></div>
            </div>
            <div class="portfolio-form">
              <input id="pf-entry" inputmode="decimal" placeholder="سعر الدخول" />
              <input id="pf-qty" inputmode="decimal" placeholder="الكمية" />
              <input id="pf-target" inputmode="decimal" placeholder="الهدف" />
              <input id="pf-stop" inputmode="decimal" placeholder="وقف الخسارة" />
              <select id="pf-side">
                <option value="long">شراء</option>
                <option value="short">بيع</option>
              </select>
              <input id="pf-note" placeholder="ملاحظة اختيارية" />
              <button class="primary" id="add-position">إضافة صفقة للرمز الحالي</button>
            </div>
            <div class="feedback" id="portfolio-feedback"></div>
            <div id="portfolio" class="status">جاري التحميل...</div>
          </div>
          <div class="panel" id="saved-section">
            <h2>سجل الفرص</h2>
            <div class="portfolio-summary">
              <div><div class="muted small">محفوظة</div><strong id="opp-count">-</strong></div>
              <div><div class="muted small">رابحة</div><strong id="opp-winners">-</strong></div>
              <div><div class="muted small">أفضل تغير</div><strong id="opp-best">-</strong></div>
            </div>
            <div id="saved-opportunities" class="status">جاري التحميل...</div>
          </div>
          <div class="panel" id="activity-section">
            <h2>آخر نشاط</h2>
            <div id="last-scans" class="status">لا توجد بيانات بعد</div>
          </div>
          <div class="panel" id="symbols-section">
            <h2>كل الرموز</h2>
            <div class="symbol-tools">
              <input id="symbol-search" type="search" placeholder="ابحث باسم الشركة أو الرمز" autocomplete="off" />
              <div class="market-tabs" id="market-tabs">
                <button class="active" data-market="ALL">الكل</button>
                <button data-market="SAUDI">السعودي</button>
                <button data-market="US">الأمريكي</button>
                <button data-market="CRYPTO">الكريبتو</button>
              </div>
            </div>
            <div id="symbols" class="status">جاري التحميل...</div>
          </div>
        </div>
      </section>
    </main>
  </div>

  <script>
    const TG_ID = "__TG_ID__";
    const TOKEN = "__TOKEN__";
    const root = `/api/dashboard/${TG_ID}/${TOKEN}`;
    let currentSymbol = { symbol: "BTCUSDT", market: "CRYPTO" };
    let currentInterval = "1d";
    let selectedMarket = "ALL";
    let searchTimer;
    let liveTimer;
    let latestChartData = {};
    let supportLine;
    let resistanceLine;
    let chart, candleSeries, volumeSeries;
    let chartRequestSeq = 0;

    const fmt = (n, d = 2) => {
      if (n === null || n === undefined || n === "" || Number.isNaN(Number(n))) return "-";
      return Number(n).toLocaleString("ar-SA", { maximumFractionDigits: d });
    };
    const marketName = (m) => ({SAUDI: "السعودي", US: "الأمريكي", CRYPTO: "الكريبتو"}[m] || m);
    const statusText = (v) => v === "open" ? "مفتوح" : "مغلق";

    async function getJson(url) {
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) throw new Error(await res.text());
      return res.json();
    }

    async function postJson(url, payload) {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.message || "تعذر تنفيذ العملية");
      return data;
    }

    function setFeedback(text) {
      document.getElementById("action-feedback").textContent = text || "";
    }

    function setPortfolioFeedback(text) {
      document.getElementById("portfolio-feedback").textContent = text || "";
    }

    function setAiFeedback(text) {
      document.getElementById("ai-feedback").textContent = text || "";
    }

    function currentSymbolTitle() {
      return `${currentSymbol.name_ar || currentSymbol.name_en || currentSymbol.symbol} (${currentSymbol.symbol} - ${marketName(currentSymbol.market)})`;
    }

    function pushAiMessage(role, text) {
      const chat = document.getElementById("ai-chat");
      const node = document.createElement("div");
      node.className = `ai-msg ${role}`;
      node.textContent = text;
      chat.appendChild(node);
      chat.scrollTop = chat.scrollHeight;
    }

    async function sendAiPrompt(prompt) {
      const text = String(prompt || document.getElementById("ai-input").value || "").trim();
      if (!text) {
        setAiFeedback("اكتب سؤالك أولاً");
        return;
      }
      const context = [
        `الرمز الحالي: ${currentSymbolTitle()}`,
        `الفريم: ${currentInterval}`,
        `السعر: ${fmt(latestChartData.last_price, 4)}`,
        `التغير: ${fmt(latestChartData.change_percent, 2)}%`,
        `السكور: ${latestChartData.score ? fmt(latestChartData.score, 1) + "/100" : "-"}`,
        `الدعم: ${fmt(latestChartData.support, 4)}`,
        `المقاومة: ${fmt(latestChartData.resistance, 4)}`,
        `RSI: ${latestChartData.rsi ? fmt(latestChartData.rsi, 1) : "-"}`,
      ].join("\n");
      pushAiMessage("user", text);
      document.getElementById("ai-input").value = "";
      setBusy("ai-send", true);
      setAiFeedback("جاري تجهيز الرد...");
      try {
        const data = await postJson(`${root}/ai`, { prompt: `${context}\n\nسؤال المستخدم: ${text}` });
        pushAiMessage("bot", data.reply || "ما وصل رد واضح حالياً");
        document.getElementById("ai-limit").textContent = data.limit > 0 ? `متبقي ${data.remaining}/${data.limit}` : "Gemini";
        setAiFeedback("");
      } catch (err) {
        pushAiMessage("bot", err.message || "تعذر تشغيل مساعد الذكاء حالياً");
        setAiFeedback("");
      } finally {
        setBusy("ai-send", false);
      }
    }

    function setBusy(id, busy) {
      const el = document.getElementById(id);
      if (el) el.disabled = Boolean(busy);
    }

    function sameSymbol(a, b) {
      return a && b && a.symbol === b.symbol && a.market === b.market;
    }

    function renderWatchlist(items) {
      const box = document.getElementById("watchlist");
      if (!items || !items.length) {
        box.textContent = "قائمتك فارغة";
        return;
      }
      box.innerHTML = items.slice(0, 10).map((s, idx) =>
        `<div class="symbol-row" data-idx="${idx}" data-kind="watch">
          <div class="row-top"><span class="name">${s.name_ar || s.symbol}</span><span class="muted">${marketName(s.market)}</span></div>
          <span class="muted">${s.symbol}</span>
        </div>`
      ).join("");
      [...box.querySelectorAll(".symbol-row")].forEach((row) => {
        row.addEventListener("click", () => {
          selectSymbol(items[Number(row.dataset.idx)]);
        });
      });
    }

    function renderAlerts(items) {
      const box = document.getElementById("alerts");
      if (!items || !items.length) {
        box.textContent = "لا توجد تنبيهات نشطة";
        return;
      }
      const typeLabel = {
        price_above: "فوق", price_below: "تحت", rsi_above: "RSI فوق", rsi_below: "RSI تحت",
        near_support: "قرب الدعم", near_resistance: "قرب المقاومة", price_change_percent: "تغير %",
      };
      box.innerHTML = items.slice(0, 8).map((a) =>
        `<div class="scan-row">
          <div class="row-top"><span class="name">${a.symbol}</span><span class="${a.is_active ? "up" : "muted"}">${a.is_active ? "نشط" : "متوقف"}</span></div>
          <span class="muted">${typeLabel[a.alert_type] || a.alert_type} | ${fmt(a.value, 4)}</span>
        </div>`
      ).join("");
    }

    function renderPortfolio(portfolio) {
      const box = document.getElementById("portfolio");
      const items = portfolio?.items || [];
      document.getElementById("pf-count").textContent = portfolio?.open_count ?? 0;
      document.getElementById("pf-value").textContent = fmt(portfolio?.total_value, 2);
      const pnlEl = document.getElementById("pf-pnl");
      pnlEl.textContent = fmt(portfolio?.total_pnl, 2);
      pnlEl.className = Number(portfolio?.total_pnl || 0) >= 0 ? "up" : "down";

      if (!items.length) {
        box.textContent = "لا توجد صفقات بعد";
        return;
      }

      box.innerHTML = items.slice(0, 12).map((p) => {
        const cls = Number(p.pnl || 0) >= 0 ? "up" : "down";
        const status = p.status === "open" ? "مفتوحة" : "مغلقة";
        const closeBtn = p.status === "open" ? `<button class="tiny-btn" data-close="${p.id}">إغلاق</button>` : "";
        return `<div class="scan-row">
          <div class="row-top"><span class="name">${p.symbol}</span><span class="${cls}">${fmt(p.pnl, 2)} (${fmt(p.pnl_pct, 2)}%)</span></div>
          <div class="row-top"><span class="muted">${marketName(p.market)} | دخول ${fmt(p.entry_price, 4)} | كمية ${fmt(p.quantity, 4)} | ${status}</span>${closeBtn}</div>
          <div class="muted small">هدف ${p.target_price ? fmt(p.target_price, 4) : "-"} | وقف ${p.stop_loss ? fmt(p.stop_loss, 4) : "-"}</div>
          ${p.note ? `<div class="muted small">${p.note}</div>` : ""}
        </div>`;
      }).join("");

      [...box.querySelectorAll("[data-close]")].forEach((btn) => {
        btn.addEventListener("click", () => closePosition(Number(btn.dataset.close)));
      });
    }

    function renderSavedOpportunities(saved) {
      const box = document.getElementById("saved-opportunities");
      const items = saved?.items || [];
      document.getElementById("opp-count").textContent = saved?.count ?? 0;
      document.getElementById("opp-winners").textContent = saved?.winners ?? 0;
      const best = items.length ? Math.max(...items.map(x => Number(x.change_since_save || 0))) : 0;
      const bestEl = document.getElementById("opp-best");
      bestEl.textContent = `${fmt(best, 2)}%`;
      bestEl.className = best >= 0 ? "up" : "down";

      if (!items.length) {
        box.textContent = "لا توجد فرص محفوظة";
        return;
      }

      box.innerHTML = items.slice(0, 10).map((item) => {
        const cls = Number(item.change_since_save || 0) >= 0 ? "up" : "down";
        return `<div class="symbol-row" data-opp="${item.id}" data-symbol="${item.symbol}" data-market="${item.market}" data-name="${item.name}">
          <div class="row-top"><span class="name">${item.name || item.symbol}</span><span class="${cls}">${fmt(item.change_since_save, 2)}%</span></div>
          <div class="row-top"><span class="muted">${item.symbol} | ${marketName(item.market)} | حفظ ${fmt(item.entry_price, 4)}</span><button class="tiny-btn" data-remove-opp="${item.id}">حذف</button></div>
        </div>`;
      }).join("");

      [...box.querySelectorAll("[data-symbol]")].forEach((row) => {
        row.addEventListener("click", (event) => {
          if (event.target.closest("[data-remove-opp]")) return;
          selectSymbol({
            symbol: row.dataset.symbol,
            market: row.dataset.market,
            name_ar: row.dataset.name,
            name_en: row.dataset.name,
          });
        });
      });
      [...box.querySelectorAll("[data-remove-opp]")].forEach((btn) => {
        btn.addEventListener("click", () => removeSavedOpportunity(Number(btn.dataset.removeOpp)));
      });
    }

    function renderVipBrief(summary, radarItems = []) {
      const box = document.getElementById("vip-brief");
      const portfolio = summary?.portfolio || {};
      const best = radarItems.slice(0, 3);
      const pnl = Number(portfolio.total_pnl || 0);
      const pnlClass = pnl >= 0 ? "up" : "down";
      const alertsCount = summary?.alerts?.filter(a => a.is_active).length || 0;
      const engagement = summary?.engagement || {};
      const contest = engagement.contest_today;
      box.innerHTML = `
        <div class="scan-row">
          <div class="row-top"><span class="name">أفضل الفرص</span><span class="score">${best.length}</span></div>
          <span class="muted">${best.map(x => x.symbol).join(" | ") || "تظهر بعد تشغيل الرادار"}</span>
        </div>
        <div class="scan-row">
          <div class="row-top"><span class="name">المحفظة</span><span class="${pnlClass}">${fmt(pnl, 2)}</span></div>
          <span class="muted">صفقات مفتوحة ${portfolio.open_count || 0} | تنبيهات نشطة ${alertsCount}</span>
        </div>
        <div class="scan-row">
          <span class="muted">افتح فرصة من الرادار، احفظها، ثم حط هدف ووقف للصفقة عشان تتابعها يومياً.</span>
        </div>
      `;
      box.innerHTML += `
        <div class="scan-row">
          <div class="row-top"><span class="name">نقاط الولاء</span><span class="score">${engagement.loyalty_points || 0}</span></div>
          <span class="muted">المتبقي للمكافأة ${engagement.next_reward_points ?? 120} | المسابقة ${contest ? `${contest.symbol} ${fmt(contest.target_price, 4)}` : "لم تشارك اليوم"}</span>
        </div>
      `;
    }

    function renderAffiliates(data) {
      const box = document.getElementById("affiliates");
      document.getElementById("af-count").textContent = data.summary?.partners ?? 0;
      document.getElementById("af-due").textContent = fmt(data.summary?.due, 2);
      document.getElementById("af-paid").textContent = fmt(data.summary?.paid, 2);
      const items = data.items || [];
      if (!items.length) {
        box.textContent = "لا توجد بيانات شركاء حالياً";
        return;
      }
      box.innerHTML = `<div class="table-wrap"><table class="data-table">
        <thead><tr><th>الشريك</th><th>الكود</th><th>المستخدمون</th><th>المبيعات</th><th>المستحق</th><th>المدفوع</th></tr></thead>
        <tbody>${items.map((item) => `<tr>
          <td>${item.name}<br><span class="muted small">${item.is_active ? "نشط" : "متوقف"} | ${fmt(item.commission_percent, 0)}%</span></td>
          <td>${item.code}</td>
          <td>${item.users}</td>
          <td>${fmt(item.sales, 2)}</td>
          <td class="score">${fmt(item.due, 2)}</td>
          <td>${fmt(item.paid, 2)}</td>
        </tr>`).join("")}</tbody>
      </table></div>`;
    }

    async function loadAffiliates() {
      const box = document.getElementById("affiliates");
      try {
        const data = await getJson(`${root}/affiliates`);
        renderAffiliates(data);
        document.getElementById("affiliates-status").textContent = "محدث";
      } catch (err) {
        box.textContent = "لوحة الشركاء متاحة للأدمن فقط";
        document.getElementById("affiliates-status").textContent = "للأدمن فقط";
      }
    }

    function selectSymbol(symbol) {
      currentSymbol = symbol;
      document.getElementById("selected-symbol").textContent = `${symbol.name_ar || symbol.name_en || symbol.symbol} | ${symbol.symbol}`;
      const select = document.getElementById("symbol-select");
      const option = [...select.options].find((item) => item.dataset.symbol === symbol.symbol && item.dataset.market === symbol.market);
      if (option) select.value = option.value;
      setFeedback("");
      loadChart();
    }

    function initChart() {
      if (!window.LightweightCharts) {
        document.getElementById("chart").innerHTML = "<div class='status'>تعذر تحميل مكتبة الشارت.</div>";
        return;
      }
      chart = LightweightCharts.createChart(document.getElementById("chart"), {
        layout: { background: { color: "#171c23" }, textColor: "#96a2b4" },
        grid: { vertLines: { color: "#242d38" }, horzLines: { color: "#242d38" } },
        rightPriceScale: { borderColor: "#2b3441" },
        timeScale: { borderColor: "#2b3441", timeVisible: true },
      });
      candleSeries = chart.addCandlestickSeries({
        upColor: "#39d98a", downColor: "#ff6b6b", borderVisible: false,
        wickUpColor: "#39d98a", wickDownColor: "#ff6b6b",
      });
      volumeSeries = chart.addHistogramSeries({
        color: "#27d3b2", priceFormat: { type: "volume" }, priceScaleId: "",
        scaleMargins: { top: 0.82, bottom: 0 },
      });
      window.addEventListener("resize", () => chart.applyOptions({ width: document.getElementById("chart").clientWidth }));
    }

    function setChartOptions(symbols, options = {}) {
      const select = document.getElementById("symbol-select");
      if (!symbols.length) return;
      const list = symbols.slice(0, 120);
      select.innerHTML = list.map((s, idx) => `<option value="${idx}" data-symbol="${s.symbol}" data-market="${s.market}">${s.name_ar || s.name_en || s.note || s.symbol} | ${s.symbol}</option>`).join("");
      select.onchange = () => {
        selectSymbol(list[Number(select.value)]);
      };
      const existingIndex = list.findIndex((item) => sameSymbol(item, currentSymbol));
      if (options.setCurrent || !currentSymbol?.symbol || existingIndex === -1 && options.forceFirst) {
        currentSymbol = list[0];
      }
      const selectedIndex = list.findIndex((item) => sameSymbol(item, currentSymbol));
      if (selectedIndex >= 0) select.value = String(selectedIndex);
      document.getElementById("selected-symbol").textContent = `${currentSymbol.name_ar || currentSymbol.name_en || currentSymbol.symbol} | ${currentSymbol.symbol}`;
    }

    async function loadSummary() {
      const data = await getJson(`${root}/summary`);
      document.getElementById("welcome").textContent = `أهلاً ${data.user.name} | ${data.user.plan.toUpperCase()} | آخر تحديث ${data.server_time}`;
      document.getElementById("m-watch").textContent = data.cards.watchlist;
      document.getElementById("m-alerts").textContent = data.cards.alerts;
      document.getElementById("m-scans").textContent = data.cards.scans_today;
      document.getElementById("m-total").textContent = data.cards.total_scans;
      document.getElementById("s-saudi").textContent = statusText(data.markets.saudi);
      document.getElementById("s-us").textContent = statusText(data.markets.us);
      document.getElementById("s-crypto").textContent = statusText(data.markets.crypto);
      renderWatchlist(data.watchlist);
      renderAlerts(data.alerts);
      renderPortfolio(data.portfolio);
      renderSavedOpportunities(data.saved_opportunities);
      renderVipBrief(data, []);

      document.getElementById("last-scans").innerHTML = data.last_scans.length ? data.last_scans.map(s =>
        `<div class="scan-row"><div class="row-top"><span class="name">${s.symbol}</span><span class="score">${fmt(s.score, 0)}/100</span></div><span class="muted">${s.signal || marketName(s.market)}</span></div>`
      ).join("") : "لا توجد فحوصات حديثة";
      setChartOptions(data.symbols, { setCurrent: true });
      await loadSymbols();
      loadChart();
    }

    async function loadRadar() {
      const box = document.getElementById("radar");
      try {
        const data = await getJson(`${root}/radar`);
        const summary = await getJson(`${root}/summary`).catch(() => null);
        if (summary) renderVipBrief(summary, data.items || []);
        const best = data.items[0];
        const bestHtml = best ? `<div class="highlight" data-symbol="${best.symbol}" data-market="${best.market}" data-name="${best.name || best.symbol}">
          <div class="row-top"><span class="name">فرصة اليوم: ${best.name || best.symbol}</span><span class="score">${best.score}/100</span></div>
          <div class="muted small">${best.symbol} | ${marketName(best.market)} | ثقة ${best.confidence}/100 | مخاطرة ${best.risk}</div>
        </div>` : "";
        box.innerHTML = bestHtml + data.items.map(item => {
          const cls = item.change >= 0 ? "up" : "down";
          return `<div class="market-row symbol-row" data-symbol="${item.symbol}" data-market="${item.market}" data-name="${item.name || item.symbol}">
            <div class="row-top"><span class="name">${item.name || item.symbol}</span><span class="score">${item.score}/100</span></div>
            <div class="row-top"><span class="muted">${item.symbol} | ${marketName(item.market)}</span><span class="${cls}">${fmt(item.change)}%</span></div>
            <div class="muted small">ثقة ${item.confidence}/100 | مخاطرة ${item.risk} | دعم ${fmt(item.support, 4)} | مقاومة ${fmt(item.resistance, 4)}</div>
          </div>`;
        }).join("");
        [...box.querySelectorAll(".symbol-row, .highlight")].forEach((row) => {
          row.addEventListener("click", () => selectSymbol({
            symbol: row.dataset.symbol,
            market: row.dataset.market,
            name_ar: row.dataset.name,
            name_en: row.dataset.name,
          }));
        });
      } catch (err) {
        box.textContent = "تعذر تحميل رادار الفرص حالياً";
      }
    }

    async function loadChart() {
      if (!chart) return;
      const seq = ++chartRequestSeq;
      document.getElementById("chart-status").textContent = "جاري التحميل...";
      try {
        const data = await getJson(`${root}/chart?symbol=${encodeURIComponent(currentSymbol.symbol)}&market=${encodeURIComponent(currentSymbol.market)}&interval=${currentInterval}`);
        if (seq !== chartRequestSeq) return;
        latestChartData = data;
        if (supportLine) { candleSeries.removePriceLine(supportLine); supportLine = null; }
        if (resistanceLine) { candleSeries.removePriceLine(resistanceLine); resistanceLine = null; }
        candleSeries.setData(data.data.map(x => ({ time: x.time, open: x.open, high: x.high, low: x.low, close: x.close })));
        volumeSeries.setData(data.data.map(x => ({ time: x.time, value: x.volume, color: x.close >= x.open ? "rgba(57,217,138,.35)" : "rgba(255,107,107,.35)" })));
        if (data.support) {
          supportLine = candleSeries.createPriceLine({ price: data.support, color: "#39d98a", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "دعم" });
        }
        if (data.resistance) {
          resistanceLine = candleSeries.createPriceLine({ price: data.resistance, color: "#ff6b6b", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "مقاومة" });
        }
        chart.timeScale().fitContent();
        document.getElementById("chart-status").textContent = `${data.symbol} | ${data.interval} | حي`;
        document.getElementById("chart-meta").textContent =
          `السعر ${fmt(data.last_price, 4)} | التغير ${fmt(data.change_percent, 2)}% | السكور ${data.score ? fmt(data.score, 1) + "/100" : "-"} | دعم ${fmt(data.support, 4)} | مقاومة ${fmt(data.resistance, 4)} | RSI ${data.rsi ? fmt(data.rsi, 1) : "-"}`;
        document.getElementById("ins-score").textContent = data.score ? `${fmt(data.score, 1)}/100` : "-";
        document.getElementById("ins-trend").textContent = data.trend || data.rating || "-";
        document.getElementById("ins-risk").textContent = data.risk || "-";
        const changeEl = document.getElementById("ins-change");
        changeEl.textContent = `${fmt(data.change_percent, 2)}%`;
        changeEl.className = Number(data.change_percent || 0) >= 0 ? "up" : "down";
        if (!document.getElementById("pf-entry").value && data.last_price) {
          document.getElementById("pf-entry").placeholder = `سعر الدخول - الحالي ${fmt(data.last_price, 4)}`;
        }
        document.getElementById("pf-target").placeholder = data.resistance ? `الهدف - مقاومة ${fmt(data.resistance, 4)}` : "الهدف";
        document.getElementById("pf-stop").placeholder = data.support ? `الوقف - دعم ${fmt(data.support, 4)}` : "وقف الخسارة";
      } catch (err) {
        if (seq !== chartRequestSeq) return;
        document.getElementById("chart-status").textContent = "تعذر تحميل الشارت";
        document.getElementById("chart-meta").textContent = err.message || "جرب رمزاً أو فريماً مختلفاً";
        ["ins-score", "ins-trend", "ins-risk", "ins-change"].forEach((id) => document.getElementById(id).textContent = "-");
      }
    }

    async function loadSymbols(options = {}) {
      const q = document.getElementById("symbol-search").value.trim();
      const box = document.getElementById("symbols");
      box.textContent = "جاري تحميل الرموز...";
      try {
        const data = await getJson(`${root}/symbols?market=${encodeURIComponent(selectedMarket)}&q=${encodeURIComponent(q)}&limit=500`);
        if (!data.items.length) {
          box.textContent = "لا توجد رموز مطابقة";
          return;
        }
        setChartOptions(data.items, { forceFirst: Boolean(options.forceFirst) });
        box.innerHTML = data.items.map((s, idx) =>
          `<div class="symbol-row" data-idx="${idx}">
            <div class="row-top"><span class="name">${s.name_ar || s.name_en || s.symbol}</span><span class="muted">${marketName(s.market)}</span></div>
            <div class="row-top"><span class="muted">${s.symbol}</span><span class="muted small">${s.sector || ""}</span></div>
          </div>`
        ).join("");
        [...box.querySelectorAll(".symbol-row")].forEach((row) => {
          row.addEventListener("click", () => {
            selectSymbol(data.items[Number(row.dataset.idx)]);
          });
        });
      } catch (err) {
        box.textContent = "تعذر تحميل الرموز حالياً";
      }
    }

    async function refreshSummaryPanels() {
      try {
        const data = await getJson(`${root}/summary`);
        document.getElementById("m-watch").textContent = data.cards.watchlist;
        document.getElementById("m-alerts").textContent = data.cards.alerts;
        renderWatchlist(data.watchlist);
        renderAlerts(data.alerts);
        renderPortfolio(data.portfolio);
        renderSavedOpportunities(data.saved_opportunities);
        renderVipBrief(data, []);
      } catch (err) {}
    }

    async function addCurrentToWatchlist() {
      setBusy("add-watch", true);
      setFeedback("جاري الإضافة...");
      try {
        const data = await postJson(`${root}/watchlist`, {
          action: "add",
          symbol: currentSymbol.symbol,
          market: currentSymbol.market,
        });
        setFeedback(data.message || "تمت الإضافة");
        await refreshSummaryPanels();
      } catch (err) {
        setFeedback(err.message);
      } finally {
        setBusy("add-watch", false);
      }
    }

    async function removeCurrentFromWatchlist() {
      setBusy("remove-watch", true);
      setFeedback("جاري الحذف...");
      try {
        const data = await postJson(`${root}/watchlist`, {
          action: "remove",
          symbol: currentSymbol.symbol,
          market: currentSymbol.market,
        });
        setFeedback(data.message || "تم الحذف");
        await refreshSummaryPanels();
      } catch (err) {
        setFeedback(err.message);
      } finally {
        setBusy("remove-watch", false);
      }
    }

    async function createCurrentAlert() {
      const alertType = document.getElementById("alert-type").value;
      const value = document.getElementById("alert-value").value.trim();
      if (!value) {
        setFeedback("اكتب قيمة التنبيه أولاً");
        return;
      }
      setBusy("create-alert", true);
      setFeedback("جاري إنشاء التنبيه...");
      try {
        const data = await postJson(`${root}/alerts`, {
          symbol: currentSymbol.symbol,
          market: currentSymbol.market,
          alert_type: alertType,
          value,
        });
        setFeedback(data.message || "تم إنشاء التنبيه");
        document.getElementById("alert-value").value = "";
        await refreshSummaryPanels();
      } catch (err) {
        setFeedback(err.message);
      } finally {
        setBusy("create-alert", false);
      }
    }

    function fillSmartAlert(type, value, label) {
      if (!value) {
        setFeedback("القيمة غير متاحة حالياً، انتظر تحميل الشارت");
        return;
      }
      document.getElementById("alert-type").value = type;
      document.getElementById("alert-value").value = Number(value).toFixed(type.startsWith("rsi") ? 1 : 4);
      setFeedback(label);
    }

    async function addPosition() {
      const entry = document.getElementById("pf-entry").value.trim() || latestChartData.last_price;
      const quantity = document.getElementById("pf-qty").value.trim();
      const target = document.getElementById("pf-target").value.trim();
      const stop = document.getElementById("pf-stop").value.trim();
      const side = document.getElementById("pf-side").value;
      const note = document.getElementById("pf-note").value.trim();
      if (!entry || !quantity) {
        setPortfolioFeedback("اكتب سعر الدخول والكمية");
        return;
      }
      setBusy("add-position", true);
      setPortfolioFeedback("جاري إضافة الصفقة...");
      try {
        const data = await postJson(`${root}/portfolio`, {
          action: "add",
          symbol: currentSymbol.symbol,
          market: currentSymbol.market,
          entry_price: entry,
          quantity,
          target_price: target,
          stop_loss: stop,
          side,
          note,
        });
        setPortfolioFeedback(data.message || "تمت إضافة الصفقة");
        document.getElementById("pf-entry").value = "";
        document.getElementById("pf-qty").value = "";
        document.getElementById("pf-target").value = "";
        document.getElementById("pf-stop").value = "";
        document.getElementById("pf-note").value = "";
        await refreshSummaryPanels();
      } catch (err) {
        setPortfolioFeedback(err.message);
      } finally {
        setBusy("add-position", false);
      }
    }

    async function closePosition(id) {
      setPortfolioFeedback("جاري إغلاق الصفقة...");
      try {
        const data = await postJson(`${root}/portfolio`, { action: "close", id });
        setPortfolioFeedback(data.message || "تم إغلاق الصفقة");
        await refreshSummaryPanels();
      } catch (err) {
        setPortfolioFeedback(err.message);
      }
    }

    async function saveCurrentOpportunity() {
      setBusy("save-opportunity", true);
      setFeedback("جاري حفظ الفرصة...");
      try {
        const data = await postJson(`${root}/opportunities`, {
          action: "save",
          symbol: currentSymbol.symbol,
          market: currentSymbol.market,
          name: currentSymbol.name_ar || currentSymbol.name_en || currentSymbol.symbol,
          score: latestChartData.score || "",
          entry_price: latestChartData.last_price || "",
          support: latestChartData.support || "",
          resistance: latestChartData.resistance || "",
        });
        setFeedback(data.message || "تم حفظ الفرصة");
        await refreshSummaryPanels();
      } catch (err) {
        setFeedback(err.message);
      } finally {
        setBusy("save-opportunity", false);
      }
    }

    async function removeSavedOpportunity(id) {
      setFeedback("جاري حذف الفرصة...");
      try {
        const data = await postJson(`${root}/opportunities`, { action: "remove", id });
        setFeedback(data.message || "تم الحذف");
        await refreshSummaryPanels();
      } catch (err) {
        setFeedback(err.message);
      }
    }

    document.querySelectorAll(".nav button[data-target]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const target = document.getElementById(btn.dataset.target);
        if (!target) return;
        document.querySelectorAll(".nav button").forEach((item) => item.classList.toggle("active", item === btn));
        target.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });

    document.getElementById("intervals").addEventListener("click", (event) => {
      const btn = event.target.closest("button");
      if (!btn) return;
      [...document.querySelectorAll("#intervals button")].forEach(b => b.classList.toggle("active", b === btn));
      currentInterval = btn.dataset.i;
      loadChart();
    });

    document.getElementById("market-tabs").addEventListener("click", (event) => {
      const btn = event.target.closest("button");
      if (!btn) return;
      selectedMarket = btn.dataset.market;
      [...document.querySelectorAll("#market-tabs button")].forEach(b => b.classList.toggle("active", b === btn));
      loadSymbols({ forceFirst: true });
    });

    document.getElementById("symbol-search").addEventListener("input", () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(loadSymbols, 250);
    });

    document.getElementById("add-watch").addEventListener("click", addCurrentToWatchlist);
    document.getElementById("remove-watch").addEventListener("click", removeCurrentFromWatchlist);
    document.getElementById("save-opportunity").addEventListener("click", saveCurrentOpportunity);
    document.getElementById("create-alert").addEventListener("click", createCurrentAlert);
    document.getElementById("add-position").addEventListener("click", addPosition);
    document.getElementById("ai-send").addEventListener("click", () => sendAiPrompt());
    document.getElementById("ai-input").addEventListener("keydown", (event) => {
      if (event.key === "Enter") sendAiPrompt();
    });
    document.querySelectorAll("[data-ai-prompt]").forEach((btn) => {
      btn.addEventListener("click", () => sendAiPrompt(btn.dataset.aiPrompt));
    });
    document.getElementById("smart-resistance").addEventListener("click", () =>
      fillSmartAlert("price_above", latestChartData.resistance, "تم تعبئة تنبيه اختراق المقاومة")
    );
    document.getElementById("smart-support").addEventListener("click", () =>
      fillSmartAlert("price_below", latestChartData.support, "تم تعبئة تنبيه كسر الدعم")
    );
    document.getElementById("smart-rsi-low").addEventListener("click", () =>
      fillSmartAlert("rsi_below", 30, "تم تعبئة تنبيه RSI أقل من 30")
    );
    document.getElementById("smart-rsi-high").addEventListener("click", () =>
      fillSmartAlert("rsi_above", 70, "تم تعبئة تنبيه RSI أعلى من 70")
    );

    initChart();
    loadSummary().catch(() => document.getElementById("welcome").textContent = "تعذر تحميل بيانات الحساب");
    loadRadar();
    loadAffiliates();
    liveTimer = setInterval(() => {
      if (document.visibilityState === "visible") loadChart();
    }, 30000);
  </script>
</body>
</html>
"""
