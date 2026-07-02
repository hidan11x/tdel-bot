from typing import Any, Optional

from services.scanner import scan_symbol, scan_symbol_multi_timeframe
from services.search_engine import auto_detect_symbol
from services.signal_engine import build_signal


def _fmt_price(value: Optional[float]) -> str:
    if value is None:
        return "غير متوفر"
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:.4f}"
    if value >= 0.01:
        return f"{value:.6f}"
    return f"{value:.8f}"


def _pct_price(price: Optional[float], pct: float) -> Optional[float]:
    if price is None:
        return None
    return price * (1 + pct / 100)


def _market_label(market: str) -> str:
    return {
        "SAUDI": "السوق السعودي",
        "US": "السوق الأمريكي",
        "CRYPTO": "الكريبتو",
    }.get(market, market)


def _trend_label(trend: str) -> str:
    return {
        "uptrend": "صاعد",
        "downtrend": "هابط",
        "sideways": "جانبي",
        "mixed": "متضارب",
    }.get((trend or "").lower(), "غير واضح")


def _signal_label(trend: str, score: float, confidence: int, price: Optional[float], support: Optional[float], resistance: Optional[float]) -> str:
    trend = (trend or "").lower()
    if confidence >= 70 and score >= 65 and trend == "uptrend":
        return "شراء مشروط"
    if trend == "downtrend" and confidence >= 60:
        return "بيع احترازي"
    if score < 45 or confidence < 45:
        return "تجنب"
    if resistance and price and price >= resistance * 0.985:
        return "مراقبة اختراق"
    if support and price and price <= support * 1.025:
        return "مراقبة ارتداد"
    return "مراقبة قوية"


def _levels(signal) -> dict[str, Optional[float]]:
    price = signal.current_price
    support = signal.support
    resistance = signal.resistance
    trend = (signal.trend or "").lower()

    if trend == "downtrend":
        entry = support if support else _pct_price(price, -1.0)
        stop = resistance if resistance else _pct_price(price, 2.0)
        target1 = _pct_price(entry, -2.0) if entry else None
        target2 = _pct_price(entry, -4.0) if entry else None
        target3 = _pct_price(entry, -7.0) if entry else None
    else:
        entry = resistance if resistance and price and price < resistance else price
        stop = support if support else _pct_price(price, -2.5)
        target1 = resistance if resistance and price and resistance > price else _pct_price(price, 2.0)
        target2 = _pct_price(target1, 2.5) if target1 else None
        target3 = _pct_price(target1, 5.0) if target1 else None

    return {
        "entry": entry,
        "stop": stop,
        "target1": target1,
        "target2": target2,
        "target3": target3,
    }


def _scenario(signal, levels: dict[str, Optional[float]], mtf: Optional[dict[str, Any]]) -> str:
    trend = (signal.trend or "").lower()
    price = signal.current_price
    if trend == "downtrend":
        return (
            f"استمرار الضغط تحت {_fmt_price(levels.get('entry'))} يدعم الهبوط نحو الهدف الأول. "
            f"اختراق {_fmt_price(levels.get('stop'))} يضعف سيناريو البيع."
        )
    if trend == "uptrend":
        return (
            f"الثبات فوق {_fmt_price(levels.get('entry'))} يدعم الحركة نحو الأهداف. "
            f"كسر {_fmt_price(levels.get('stop'))} يلغي أفضلية الصعود."
        )
    if mtf and mtf.get("trend") == "mixed":
        return "الفريمات متضاربة؛ الأفضل انتظار اختراق واضح أو كسر دعم قبل اتخاذ قرار."
    return f"الحركة حول {_fmt_price(price)} تحتاج تأكيد؛ الاختراق أو الكسر هو مفتاح الإشارة."


async def build_private_prediction(raw_query: str) -> Optional[str]:
    detected = await auto_detect_symbol(raw_query)
    if not detected:
        return None

    symbol = detected["symbol"]
    market = detected["market"]
    result = await scan_symbol(symbol, market, "1d")
    if not result:
        return None

    mtf = await scan_symbol_multi_timeframe(symbol, market)
    signal = build_signal(result)
    levels = _levels(signal)
    label = _signal_label(
        signal.trend,
        signal.score,
        signal.confidence,
        signal.current_price,
        signal.support,
        signal.resistance,
    )

    mtf_confidence = mtf.get("confidence") if mtf else signal.confidence
    best_timeframe = mtf.get("best_timeframe") if mtf else "1d"
    direction = _trend_label(mtf.get("trend") if mtf else signal.trend)
    name = signal.name_ar if signal.name_ar and signal.name_ar != signal.symbol else signal.name_en
    reasons = signal.reasons[:3]
    warnings = signal.warnings[:3]

    lines = [
        "🔮 الإشارة الخاصة",
        "",
        f"الأصل: {name or signal.symbol}",
        f"الرمز: {signal.symbol}",
        f"السوق: {_market_label(signal.market)}",
        f"السعر الحالي: {_fmt_price(signal.current_price)}",
        "",
        f"الاتجاه: {direction}",
        f"الإشارة: {label}",
        f"الفريم الأقوى: {best_timeframe}",
        f"الثقة: {mtf_confidence}/100",
        f"المخاطرة: {signal.risk_level}",
        "",
        "المستويات:",
        f"منطقة الدخول: {_fmt_price(levels.get('entry'))}",
        f"وقف الخسارة: {_fmt_price(levels.get('stop'))}",
        f"الهدف 1: {_fmt_price(levels.get('target1'))}",
        f"الهدف 2: {_fmt_price(levels.get('target2'))}",
        f"الهدف 3: {_fmt_price(levels.get('target3'))}",
        "",
        "السيناريو:",
        _scenario(signal, levels, mtf),
    ]

    if reasons:
        lines.extend(["", "سبب الإشارة:"])
        lines.extend([f"- {reason}" for reason in reasons])

    if warnings:
        lines.extend(["", "تنبيهات:"])
        lines.extend([f"- {warning}" for warning in warnings])

    lines.extend(
        [
            "",
            "هذه قراءة آلية خاصة مبنية على البيانات المتاحة، وإدارة المخاطر تبقى أساسية.",
        ]
    )
    return "\n".join(lines)
