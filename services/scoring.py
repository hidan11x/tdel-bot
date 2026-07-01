from typing import Dict, Optional
from dataclasses import dataclass


@dataclass
class TechnicalScore:
    trend_score: float = 0.0
    momentum_score: float = 0.0
    volume_score: float = 0.0
    volatility_score: float = 0.0
    risk_score: float = 0.0
    overall: float = 0.0


def calculate_score(indicators: Dict[str, any]) -> TechnicalScore:
    score = TechnicalScore()
    current_price = indicators.get("current_price") or 0

    ema20 = indicators.get("ema_20")
    ema50 = indicators.get("ema_50")
    ema200 = indicators.get("ema_200")
    trend = indicators.get("trend", "sideways")

    trend_score = 50.0
    if trend == "uptrend":
        trend_score = 75.0
        if ema20 and ema50 and ema200:
            if ema20 > ema50 > ema200:
                trend_score = 90.0
            elif current_price > ema20:
                trend_score = 80.0
    elif trend == "downtrend":
        trend_score = 25.0
        if ema20 and ema50 and ema200:
            if ema20 < ema50 < ema200:
                trend_score = 10.0
    score.trend_score = trend_score

    rsi = indicators.get("rsi")
    macd_line = indicators.get("macd_line")
    macd_signal = indicators.get("macd_signal")
    macd_histogram = indicators.get("macd_histogram")

    momentum_score = 50.0
    if rsi is not None:
        if 30 <= rsi <= 70:
            momentum_score = 50 + (50 - abs(rsi - 50)) * 0.5
        elif rsi < 30:
            momentum_score = 70.0
        elif rsi > 70:
            momentum_score = 30.0

    if macd_line is not None and macd_signal is not None:
        if macd_line > macd_signal and macd_histogram and macd_histogram > 0:
            momentum_score = min(100, momentum_score + 15)
        elif macd_line < macd_signal and macd_histogram and macd_histogram < 0:
            momentum_score = max(0, momentum_score - 15)
    score.momentum_score = momentum_score

    rel_volume = indicators.get("relative_volume")
    volume_score = 50.0
    if rel_volume is not None:
        if rel_volume > 2.0:
            volume_score = 90.0
        elif rel_volume > 1.5:
            volume_score = 75.0
        elif rel_volume > 1.0:
            volume_score = 60.0
        elif rel_volume > 0.5:
            volume_score = 40.0
        else:
            volume_score = 25.0
    score.volume_score = volume_score

    atr = indicators.get("atr")
    volatility_score = 50.0
    if atr and current_price > 0:
        atr_pct = (atr / current_price) * 100
        if atr_pct < 1.0:
            volatility_score = 80.0
        elif atr_pct < 2.0:
            volatility_score = 65.0
        elif atr_pct < 3.0:
            volatility_score = 50.0
        elif atr_pct < 5.0:
            volatility_score = 35.0
        else:
            volatility_score = 20.0
    score.volatility_score = volatility_score

    inverse_volatility = 100 - volatility_score
    trend_consistency = 50.0
    if trend == "uptrend":
        trend_consistency = 75.0
    elif trend == "downtrend":
        trend_consistency = 60.0
    else:
        trend_consistency = 50.0
    score.risk_score = (inverse_volatility * 0.5 + (100 - trend_consistency) * 0.5)

    score.overall = (
        score.trend_score * 0.30
        + score.momentum_score * 0.30
        + score.volume_score * 0.15
        + score.volatility_score * 0.10
        + (100 - score.risk_score) * 0.15
    )
    score.overall = max(0, min(100, score.overall))
    return score


def get_rating(score: float) -> str:
    if score >= 80:
        return "قراءة فنية قوية"
    elif score >= 65:
        return "قراءة فنية جيدة"
    elif score >= 50:
        return "قراءة فنية متوسطة"
    return "قراءة فنية ضعيفة"


def get_rating_label(score: float) -> str:
    if score >= 80:
        return "قوي"
    elif score >= 65:
        return "جيد"
    elif score >= 50:
        return "متوسط"
    return "ضعيف"


def get_risk_level(risk_score: float) -> str:
    if risk_score <= 25:
        return "منخفض"
    elif risk_score <= 50:
        return "متوسط"
    elif risk_score <= 75:
        return "مرتفع"
    return "عالي جداً"


def generate_summary(score: TechnicalScore, indicators: Dict[str, any], symbol: str) -> str:
    trend = indicators.get("trend", "sideways")
    rsi = indicators.get("rsi")
    rel_volume = indicators.get("relative_volume")
    current_price = indicators.get("current_price") or 0
    support = indicators.get("support")
    resistance = indicators.get("resistance")

    parts = []
    if trend == "uptrend":
        parts.append(f"الاتجاه العام لـ {symbol} صاعد والإشارات الفنية إيجابية.")
    elif trend == "downtrend":
        parts.append(f"الاتجاه العام لـ {symbol} هابط ويجب الحذر.")
    else:
        parts.append(f"الاتجاه العام لـ {symbol} جانبي بدون وضوح.")

    if rsi is not None:
        if rsi >= 70:
            parts.append(f"مؤشر القوة النسبية عند {rsi:.1f} يشير إلى تشبع شرائي.")
        elif rsi <= 30:
            parts.append(f"مؤشر القوة النسبية عند {rsi:.1f} يشير إلى تشبع بيعي.")
        else:
            parts.append(f"مؤشر القوة النسبية عند {rsi:.1f} في منطقة محايدة.")

    if rel_volume is not None:
        if rel_volume > 1.5:
            parts.append(f"حجم التداول أعلى من المتوسط ({rel_volume:.1f}x) مما يدعم الحركة.")
        elif rel_volume < 0.5:
            parts.append(f"حجم التداول ضعيف مقارنة بالمتوسط.")

    if support is not None and current_price > 0:
        distance_to_support = ((current_price - support) / current_price) * 100
        if distance_to_support < 2:
            parts.append(f"السعر قريب من الدعم ({support:.4f}).")

    if resistance is not None and current_price > 0:
        distance_to_resistance = ((resistance - current_price) / current_price) * 100
        if distance_to_resistance < 2:
            parts.append(f"السعر قريب من المقاومة ({resistance:.4f}).")

    if not parts:
        parts.append(f"لا تتوفر بيانات كافية لتحليل {symbol}.")

    return " ".join(parts)
