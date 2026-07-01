from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass
class SmartSignal:
    symbol: str
    market: str
    timeframe: str
    name_ar: str
    name_en: str
    sector: str
    current_price: Optional[float]
    change_percent: float
    trend: str
    support: Optional[float]
    resistance: Optional[float]
    score: float
    rating: str
    risk_level: str
    confidence: int
    reasons: list[str]
    warnings: list[str]
    summary: str
    generated_at: str
    adx: Optional[float]
    stoch_k: Optional[float]
    stoch_d: Optional[float]
    rsi: Optional[float]


def _to_score_value(score_obj: Any) -> float:
    if score_obj is None:
        return 50.0
    value = getattr(score_obj, "overall", score_obj)
    try:
        return float(value)
    except Exception:
        return 50.0


def _safe_pct_distance(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or a == 0:
        return None
    return abs(a - b) / abs(a) * 100


def calculate_confidence(scan_result: dict) -> int:
    indicators = scan_result.get("indicators", {}) or {}
    trend = (scan_result.get("trend") or "sideways").lower()
    current_price = scan_result.get("current_price")
    support = scan_result.get("support")
    score_value = _to_score_value(scan_result.get("score"))

    confidence = score_value

    if trend in ("uptrend", "downtrend"):
        confidence += 10
    elif trend in ("sideways", "mixed"):
        confidence -= 12

    dist_to_support = _safe_pct_distance(current_price, support)
    if trend == "uptrend" and dist_to_support is not None and dist_to_support <= 2.5:
        confidence += 8

    align_points = 0
    ema20 = indicators.get("ema_20")
    ema50 = indicators.get("ema_50")
    macd_line = indicators.get("macd_line")
    macd_signal = indicators.get("macd_signal")
    rsi = indicators.get("rsi")

    if trend == "uptrend":
        if ema20 is not None and ema50 is not None and ema20 > ema50:
            align_points += 1
        if macd_line is not None and macd_signal is not None and macd_line > macd_signal:
            align_points += 1
        if rsi is not None and 45 <= rsi <= 70:
            align_points += 1
    elif trend == "downtrend":
        if ema20 is not None and ema50 is not None and ema20 < ema50:
            align_points += 1
        if macd_line is not None and macd_signal is not None and macd_line < macd_signal:
            align_points += 1
        if rsi is not None and 30 <= rsi <= 55:
            align_points += 1

    if align_points >= 2:
        confidence += 8
    elif align_points == 1:
        confidence += 3
    else:
        confidence -= 5

    risk_level = (scan_result.get("risk_level") or "").strip()
    if risk_level in ("مرتفع", "عالي", "عالي جداً"):
        confidence -= 12
    elif risk_level == "متوسط":
        confidence -= 4
    elif risk_level == "منخفض":
        confidence += 4

    confidence = max(0, min(100, int(round(confidence))))
    return confidence


def extract_reasons(scan_result: dict) -> list[str]:
    reasons: list[str] = []
    indicators = scan_result.get("indicators", {}) or {}
    trend = (scan_result.get("trend") or "sideways").lower()
    current_price = scan_result.get("current_price")
    support = scan_result.get("support")
    score_value = _to_score_value(scan_result.get("score"))

    if trend == "uptrend":
        reasons.append("الاتجاه العام صاعد.")
    elif trend == "downtrend":
        reasons.append("الاتجاه العام هابط.")
    else:
        reasons.append("الحركة تحتاج تاكيد بسبب ضعف الاتجاه.")

    dist_to_support = _safe_pct_distance(current_price, support)
    if trend == "uptrend" and dist_to_support is not None and dist_to_support <= 2.5:
        reasons.append("السعر قريب من منطقة دعم.")

    if score_value >= 70:
        reasons.append("التقييم الفني قوي.")
    elif score_value >= 55:
        reasons.append("التقييم الفني جيد.")

    ema20 = indicators.get("ema_20")
    ema50 = indicators.get("ema_50")
    macd_line = indicators.get("macd_line")
    macd_signal = indicators.get("macd_signal")
    aligned = (
        ema20 is not None
        and ema50 is not None
        and macd_line is not None
        and macd_signal is not None
        and ((trend == "uptrend" and ema20 > ema50 and macd_line > macd_signal)
             or (trend == "downtrend" and ema20 < ema50 and macd_line < macd_signal))
    )
    if aligned:
        reasons.append("المؤشرات تعطي توافق جيد.")

    if not reasons:
        reasons.append("البيانات المتاحة محدودة وتحتاج متابعة.")
    return reasons


def extract_warnings(scan_result: dict) -> list[str]:
    warnings: list[str] = []
    trend = (scan_result.get("trend") or "sideways").lower()
    current_price = scan_result.get("current_price")
    resistance = scan_result.get("resistance")
    risk_level = (scan_result.get("risk_level") or "").strip()
    score_value = _to_score_value(scan_result.get("score"))

    if risk_level in ("مرتفع", "عالي", "عالي جداً"):
        warnings.append("المخاطرة مرتفعة.")

    if trend in ("sideways", "mixed"):
        warnings.append("الفريمات او الاتجاه العام متضارب.")

    dist_to_resistance = _safe_pct_distance(current_price, resistance)
    if dist_to_resistance is not None and dist_to_resistance <= 2.5:
        warnings.append("السعر قريب من مقاومة.")

    if score_value < 50:
        warnings.append("الاشارة ضعيفة وتحتاج متابعة.")

    indicators = scan_result.get("indicators", {}) or {}
    if not indicators:
        warnings.append("حجم البيانات غير كاف.")

    return warnings


def build_signal(scan_result: dict) -> SmartSignal:
    score_value = _to_score_value(scan_result.get("score"))
    confidence = calculate_confidence(scan_result)
    reasons = extract_reasons(scan_result)
    warnings = extract_warnings(scan_result)
    generated_at = datetime.now(timezone.utc).isoformat()

    return SmartSignal(
        symbol=str(scan_result.get("symbol", "")),
        market=str(scan_result.get("market", "")),
        timeframe=str(scan_result.get("timeframe", "1d")),
        name_ar=str(scan_result.get("name_ar", scan_result.get("symbol", ""))),
        name_en=str(scan_result.get("name_en", scan_result.get("symbol", ""))),
        sector=str(scan_result.get("sector", "") or ""),
        current_price=scan_result.get("current_price"),
        change_percent=float(scan_result.get("change_percent") or 0.0),
        trend=str(scan_result.get("trend", "sideways")),
        support=scan_result.get("support"),
        resistance=scan_result.get("resistance"),
        score=score_value,
        rating=str(scan_result.get("rating", "قراءة فنية متوسطة")),
        risk_level=str(scan_result.get("risk_level", "متوسط")),
        confidence=confidence,
        reasons=reasons,
        warnings=warnings,
        summary=str(scan_result.get("summary", "")),
        generated_at=generated_at,
        adx=indicators.get("adx"),
        stoch_k=indicators.get("stoch_k"),
        stoch_d=indicators.get("stoch_d"),
        rsi=indicators.get("rsi"),
    )


def _format_price(value: Optional[float]) -> str:
    if value is None:
        return "غير متوفر"
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:.4f}"
    if value >= 0.01:
        return f"{value:.6f}"
    return f"{value:.8f}"


def _format_change(value: float) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def _trend_label(trend: str) -> str:
    mapping = {
        "uptrend": "صاعد",
        "downtrend": "هابط",
        "sideways": "جانبي",
        "mixed": "متضارب",
    }
    return mapping.get((trend or "").lower(), trend or "غير محدد")


def _market_label(market: str) -> str:
    mapping = {"SAUDI": "السعودي", "US": "الأمريكي", "CRYPTO": "الرقمية"}
    return mapping.get((market or "").upper(), market or "")


def _timeframe_label(tf: str) -> str:
    mapping = {"1d": "يومي", "1h": "ساعي", "15m": "15 دقيقة", "4h": "4 ساعات", "1w": "أسبوعي"}
    return mapping.get((tf or "").lower(), tf or "")


def _display_name(signal: SmartSignal) -> str:
    if signal.name_ar and signal.name_ar != signal.symbol:
        return signal.name_ar
    if signal.name_en and signal.name_en != signal.symbol:
        return signal.name_en
    return signal.symbol


def format_signal_message(signal: SmartSignal) -> str:
    reasons = signal.reasons or ["لا توجد اسباب كافية حالياً."]
    warnings = signal.warnings or ["لا توجد تحذيرات خاصة حالياً."]

    reason_lines = "\n".join([f"* {r}" for r in reasons])
    warning_lines = "\n".join([f"* {w}" for w in warnings])

    name = _display_name(signal)
    market_label = _market_label(signal.market)
    tf_label = _timeframe_label(signal.timeframe)

    sector_line = f"🏢 القطاع: {signal.sector}\n" if signal.sector else ""

    extra_indicators = ""
    if signal.rsi is not None:
        extra_indicators += f"📊 RSI: {signal.rsi:.1f}\n"
    if signal.adx is not None:
        adx_label = "قوي" if signal.adx > 25 else ("متوسط" if signal.adx > 20 else "ضعيف")
        extra_indicators += f"📐 ADX: {signal.adx:.1f} ({adx_label})\n"
    if signal.stoch_k is not None:
        stoch_label = "تشبع شرائي" if signal.stoch_k > 80 else ("تشبع بيعي" if signal.stoch_k < 20 else "محايد")
        extra_indicators += f"🔄 Stoch: {signal.stoch_k:.1f} ({stoch_label})\n"

    if extra_indicators:
        extra_indicators = "\n" + extra_indicators

    return (
        f"📊 قراءة فنية تعليمية\n\n"
        f"🏷 الأصل: {name}\n"
        f"🔢 الرمز: {signal.symbol}\n"
        f"🌍 السوق: {market_label}\n"
        f"{sector_line}"
        f"⏱ الفريم: {tf_label}\n\n"
        f"💰 السعر: {_format_price(signal.current_price)}\n"
        f"📈 التغير: {_format_change(signal.change_percent)}\n\n"
        f"🧭 الاتجاه: {_trend_label(signal.trend)}\n"
        f"⭐ التقييم: {signal.rating} ({signal.score:.0f}/100)\n"
        f"🎯 الثقة: {signal.confidence}/100\n"
        f"⚠️ المخاطرة: {signal.risk_level}\n"
        f"{extra_indicators}"
        f"\n🟢 الدعم: {_format_price(signal.support)}\n"
        f"🔴 المقاومة: {_format_price(signal.resistance)}\n\n"
        f"أسباب الاشارة:\n"
        f"{reason_lines}\n\n"
        f"تحذيرات:\n"
        f"{warning_lines}\n\n"
        f"{signal.summary}\n\n"
        f"هذا تحليل آلي تعليمي وليس توصية مالية."
    )


def format_signal_message_with_patterns(signal: SmartSignal, patterns_text: str = "") -> str:
    base_msg = format_signal_message(signal)
    if patterns_text:
        return base_msg + "\n\n" + patterns_text
    return base_msg
