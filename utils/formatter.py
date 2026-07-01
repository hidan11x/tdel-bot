from typing import Dict, Any, List, Optional
from datetime import datetime

from services.scoring import TechnicalScore, get_rating, get_rating_label, get_risk_level


MARKET_NAMES = {
    "US": "الأسهم الأمريكية",
    "SAUDI": "السوق السعودي",
    "CRYPTO": "العملات الرقمية",
}


def format_price(price: Optional[float]) -> str:
    if price is None:
        return "غير متوفر"
    if price >= 1000:
        return f"{price:,.2f}"
    elif price >= 1:
        return f"{price:.4f}"
    elif price >= 0.01:
        return f"{price:.6f}"
    return f"{price:.8f}"


def format_change(change: Optional[float]) -> str:
    if change is None:
        return "غير متوفر"
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.2f}%"


def format_technical_report(scan_result: Dict[str, Any]) -> str:
    sym = scan_result["symbol"]
    market = scan_result["market"]
    market_name = MARKET_NAMES.get(market, market)
    tf = scan_result["timeframe"]
    price = format_price(scan_result.get("current_price"))
    change = format_change(scan_result.get("change_percent"))

    ind = scan_result.get("indicators", {})
    trend_map = {"uptrend": "صاعد 📈", "downtrend": "هابط 📉", "sideways": "جانبي ↔️"}
    trend = trend_map.get(scan_result.get("trend", ""), "غير محدد")

    support = format_price(scan_result.get("support"))
    resistance = format_price(scan_result.get("resistance"))

    rsi = f"{ind.get('rsi', 'N/A')}"
    if ind.get("rsi") is not None:
        rsi = f"{ind['rsi']:.1f}"

    macd_line = ind.get("macd_line")
    macd_signal = ind.get("macd_signal")
    if macd_line is not None and macd_signal is not None:
        if macd_line > macd_signal:
            macd_status = "إيجابي ✅"
        else:
            macd_status = "سلبي ❌"
    else:
        macd_status = "غير متوفر"

    ema20 = format_price(ind.get("ema_20"))
    ema50 = format_price(ind.get("ema_50"))
    ema200 = format_price(ind.get("ema_200"))

    bb_upper = ind.get("bb_upper")
    bb_lower = ind.get("bb_lower")
    current_price_val = scan_result.get("current_price")
    if bb_upper is not None and bb_lower is not None and current_price_val:
        if current_price_val >= bb_upper:
            bb_status = "فوق الباند العلوي ⬆️"
        elif current_price_val <= bb_lower:
            bb_status = "تحت الباند السفلي ⬇️"
        else:
            bb_status = "ضمن النطاق ➖"
    else:
        bb_status = "غير متوفر"

    atr = f"{ind.get('atr', 'N/A')}" if ind.get("atr") is not None else "غير متوفر"

    volume = f"{ind.get('volume', 'N/A')}"
    if ind.get("volume") is not None:
        vol = ind["volume"]
        if vol >= 1_000_000:
            volume = f"{vol / 1_000_000:.2f}M"
        elif vol >= 1_000:
            volume = f"{vol / 1_000:.1f}K"
        else:
            volume = f"{vol:.0f}"

    avg_volume = f"{ind.get('avg_volume', 'N/A')}"
    if ind.get("avg_volume") is not None:
        av = ind["avg_volume"]
        if av >= 1_000_000:
            avg_volume = f"{av / 1_000_000:.2f}M"
        elif av >= 1_000:
            avg_volume = f"{av / 1_000:.1f}K"
        else:
            avg_volume = f"{av:.0f}"

    rel_volume = f"{ind.get('relative_volume', 'N/A')}"
    if ind.get("relative_volume") is not None:
        rel_volume = f"{ind['relative_volume']:.2f}x"

    score: TechnicalScore = scan_result.get("score", TechnicalScore())
    rating_text = scan_result.get("rating", get_rating(score.overall))
    risk_level = scan_result.get("risk_level", get_risk_level(score.risk_score))
    summary = scan_result.get("summary", "")
    disc = scan_result.get("disclaimer", "")

    return (
        f"📊 قراءة فنية تعليمية\n\n"
        f"الأصل: {sym}\n"
        f"السوق: {market_name}\n"
        f"الفريم: {tf}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"السعر الحالي: {price}\n"
        f"التغير: {change}\n"
        f"الاتجاه العام: {trend}\n"
        f"الدعم القريب: {support}\n"
        f"المقاومة القريبة: {resistance}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"RSI (14): {rsi}\n"
        f"MACD: {macd_status}\n"
        f"EMA 20: {ema20}\n"
        f"EMA 50: {ema50}\n"
        f"EMA 200: {ema200}\n"
        f"Bollinger Bands: {bb_status}\n"
        f"ATR: {atr}\n"
        f"الفوليوم: {volume}\n"
        f"متوسط الفوليوم: {avg_volume}\n"
        f"Relative Volume: {rel_volume}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📈 التقييم الفني:\n"
        f"• الترند: {score.trend_score:.0f}/100 ({get_rating_label(score.trend_score)})\n"
        f"• الزخم: {score.momentum_score:.0f}/100 ({get_rating_label(score.momentum_score)})\n"
        f"• الفوليوم: {score.volume_score:.0f}/100 ({get_rating_label(score.volume_score)})\n"
        f"• التذبذب: {score.volatility_score:.0f}/100 ({get_rating_label(score.volatility_score)})\n"
        f"• المخاطرة: {risk_level}\n\n"
        f"🎯 الدرجة الفنية: {score.overall:.0f}/100\n"
        f"التصنيف: {rating_text}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{summary}\n\n"
        f"{disc}"
    )


def format_watchlist(items: List[Dict[str, Any]]) -> str:
    if not items:
        return "📋 قائمة المتابعة فارغة."
    lines = ["📋 قائمة المتابعة:\n"]
    for i, item in enumerate(items, 1):
        sym = item.get("symbol", "N/A")
        market = MARKET_NAMES.get(item.get("market", ""), item.get("market", ""))
        price = format_price(item.get("current_price"))
        change = format_change(item.get("change_percent"))
        trend = item.get("trend", "")
        trend_icon = {"uptrend": "📈", "downtrend": "📉", "sideways": "↔️"}.get(trend, "")
        lines.append(f"{i}. {sym} ({market})")
        lines.append(f"   السعر: {price} | التغير: {change} {trend_icon}")
        score = item.get("score")
        if score:
            lines.append(f"   التقييم: {score.overall:.0f}/100")
        lines.append("")
    return "\n".join(lines).strip()


def format_alert(alert) -> str:
    from models import Alert
    alert_type_names = {
        "price_above": "السعر أعلى من",
        "price_below": "السعر أدنى من",
        "rsi_above": "RSI أعلى من",
        "rsi_below": "RSI أدنى من",
        "volume_spike": "ارتفاع حاد في الحجم",
        "near_support": "اقتراب من الدعم",
        "near_resistance": "اقتراب من المقاومة",
        "price_change_percent": "نسبة تغير السعر",
    }
    type_name = alert_type_names.get(alert.alert_type, alert.alert_type)
    status = "✅ نشط" if alert.is_active else "❌ معطل"
    return (
        f"🔔 تنبيه\n"
        f"الأصل: {alert.symbol} ({alert.market})\n"
        f"النوع: {type_name}\n"
        f"القيمة: {alert.value}\n"
        f"الحالة: {status}"
    )


def format_profile(user, subscription_info: Optional[Dict[str, Any]] = None) -> str:
    plan_names = {"free": "مجاني", "basic": "أساسي", "pro": "احترافي", "vip": "VIP"}
    plan_label = plan_names.get(user.plan, user.plan)

    lines = [
        f"👤 الملف الشخصي\n",
        f"المعرف: {user.first_name}",
        f"الباقة: {plan_label}",
    ]

    if user.subscription_end:
        remaining = (user.subscription_end.replace(tzinfo=None) - datetime.now()).days
        if remaining > 0:
            lines.append(f"المتبقي: {remaining} يوم")
        else:
            lines.append("⚠️ الباقة منتهية")

    if subscription_info:
        lines.append(f"المسح اليومي: {subscription_info.get('scans_used', 0)}/{subscription_info.get('scans_limit', '∞')}")
        lines.append(f"التنبيهات: {subscription_info.get('alerts_count', 0)}/{subscription_info.get('alerts_limit', '∞')}")
        lines.append(f"قائمة المتابعة: {subscription_info.get('watchlist_count', 0)}/{subscription_info.get('watchlist_limit', '∞')}")

    if subscription_info and subscription_info.get("referral_count", 0) > 0:
        lines.append(f"الإحالات: {subscription_info['referral_count']}")

    return "\n".join(lines)


def format_plans(plans: List[Dict[str, Any]]) -> str:
    lines = ["💎 خطط الاشتراك:\n"]
    for p in plans:
        name = p.get("name", "")
        price_sar = p.get("price_sar", 0)
        scans = p.get("scans_daily", "∞") if p.get("scans_daily", 0) == -1 else str(p.get("scans_daily", 0))
        alerts = p.get("max_alerts", "∞") if p.get("max_alerts", 0) == -1 else str(p.get("max_alerts", 0))
        watchlist = p.get("max_watchlist", "∞") if p.get("max_watchlist", 0) == -1 else str(p.get("max_watchlist", 0))

        lines.append(f"▸ {name.upper()}")
        lines.append(f"  💰 {price_sar:.0f} ريال / {p.get('price_usd', 0):.0f} دولار")
        lines.append(f"  📊 {scans} مسح يومي | {alerts} تنبيه | {watchlist} متابعة")
        lines.append("")
    return "\n".join(lines).strip()
