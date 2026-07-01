from typing import List, Dict, Optional
from services.indicators import _ensure_list


def detect_double_bottom(closes: list, lookback: int = 20) -> Optional[Dict]:
    if len(closes) < lookback:
        return None
    recent = closes[-lookback:]
    lows = []
    for i in range(1, len(recent) - 1):
        if recent[i] < recent[i - 1] and recent[i] < recent[i + 1]:
            lows.append((i, recent[i]))

    if len(lows) >= 2:
        v1_idx, v1 = lows[-2]
        v2_idx, v2 = lows[-1]
        if abs(v1 - v2) / max(v1, v2) < 0.03:
            return {
                "pattern": "double_bottom",
                "name_ar": "قاع مزدوج",
                "name_en": "Double Bottom",
                "signal": "bullish",
                "description": "نمط قاع مزدوج يشير إلى احتمال ارتفاع.",
            }
    return None


def detect_double_top(closes: list, lookback: int = 20) -> Optional[Dict]:
    if len(closes) < lookback:
        return None
    recent = closes[-lookback:]
    highs = []
    for i in range(1, len(recent) - 1):
        if recent[i] > recent[i - 1] and recent[i] > recent[i + 1]:
            highs.append((i, recent[i]))

    if len(highs) >= 2:
        p1_idx, p1 = highs[-2]
        p2_idx, p2 = highs[-1]
        if abs(p1 - p2) / max(p1, p2) < 0.03:
            return {
                "pattern": "double_top",
                "name_ar": "قمة مزدوجة",
                "name_en": "Double Top",
                "signal": "bearish",
                "description": "نمط قمة مزدوجة يشير إلى احتمال انخفاض.",
            }
    return None


def detect_head_and_shoulders(closes: list, lookback: int = 30) -> Optional[Dict]:
    if len(closes) < lookback:
        return None
    recent = closes[-lookback:]
    highs = []
    for i in range(1, len(recent) - 1):
        if recent[i] > recent[i - 1] and recent[i] > recent[i + 1]:
            highs.append((i, recent[i]))

    if len(highs) >= 3:
        s1 = highs[-3][1]
        head = highs[-2][1]
        s2 = highs[-1][1]
        if head > s1 and head > s2 and abs(s1 - s2) / max(s1, s2) < 0.05:
            return {
                "pattern": "head_and_shoulders",
                "name_ar": "رأس وكتفين",
                "name_en": "Head and Shoulders",
                "signal": "bearish",
                "description": "نمط رأس وكتفين يشير إلى احتمال انعكاس هابط.",
            }
    return None


def detect_triangle(closes: list, lookback: int = 20) -> Optional[Dict]:
    if len(closes) < lookback:
        return None
    recent = closes[-lookback:]
    highs = [recent[i] for i in range(1, len(recent) - 1) if recent[i] > recent[i-1] and recent[i] > recent[i+1]]
    lows = [recent[i] for i in range(1, len(recent) - 1) if recent[i] < recent[i-1] and recent[i] < recent[i+1]]

    if len(highs) >= 2 and len(lows) >= 2:
        highs_trend = highs[-1] - highs[0]
        lows_trend = lows[-1] - lows[0]

        if highs_trend < 0 and lows_trend > 0:
            return {
                "pattern": "symmetric_triangle",
                "name_ar": "مثلث متماثل",
                "name_en": "Symmetric Triangle",
                "signal": "neutral",
                "description": "مثلث متماثل، الاتجاه غير محدد بانتظار الاختراق.",
            }
        elif highs_trend < 0 and abs(lows_trend) < abs(highs_trend) * 0.3:
            return {
                "pattern": "descending_triangle",
                "name_ar": "مثلث هابط",
                "name_en": "Descending Triangle",
                "signal": "bearish",
                "description": "مثلث هابط يشير إلى احتمال استمرار الانخفاض.",
            }
        elif lows_trend > 0 and abs(highs_trend) < abs(lows_trend) * 0.3:
            return {
                "pattern": "ascending_triangle",
                "name_ar": "مثلث صاعد",
                "name_en": "Ascending Triangle",
                "signal": "bullish",
                "description": "مثلث صاعد يشير إلى احتمال استمرار الارتفاع.",
            }
    return None


def detect_breakout(closes: list, lookback: int = 20) -> Optional[Dict]:
    if len(closes) < lookback + 5:
        return None
    recent = closes[-lookback:]
    resistance = max(recent[:-5])
    support = min(recent[:-5])
    current = closes[-1]

    if current > resistance * 1.02:
        return {
            "pattern": "breakout_up",
            "name_ar": "اختراق صاعد",
            "name_en": "Bullish Breakout",
            "signal": "bullish",
            "description": "السعر اخترق المقاومة صعوداً.",
        }
    elif current < support * 0.98:
        return {
            "pattern": "breakout_down",
            "name_ar": "اختراق هابط",
            "name_en": "Bearish Breakout",
            "signal": "bearish",
            "description": "السعر اخترق الدعم هبوطاً.",
        }
    return None


def detect_all_patterns(closes) -> List[Dict]:
    closes = _ensure_list(closes)
    if len(closes) < 20:
        return []

    patterns = []
    detectors = [
        detect_double_bottom,
        detect_double_top,
        detect_head_and_shoulders,
        detect_triangle,
        detect_breakout,
    ]

    for detector in detectors:
        result = detector(closes)
        if result:
            patterns.append(result)

    return patterns


def format_patterns(patterns: List[Dict]) -> str:
    if not patterns:
        return ""

    lines = ["📐 الأنماط الفنية المكتشفة:\n"]
    signal_emoji = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}

    for p in patterns:
        emoji = signal_emoji.get(p["signal"], "📊")
        lines.append(f"{emoji} {p['name_ar']}")
        lines.append(f"   {p['description']}")
        lines.append("")

    return "\n".join(lines).strip()
