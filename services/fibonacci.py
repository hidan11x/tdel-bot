from typing import Dict, Optional, Tuple, List


FIB_LEVELS = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]

FIB_NAMES = {
    0.0: "0%",
    0.236: "23.6%",
    0.382: "38.2%",
    0.5: "50%",
    0.618: "61.8%",
    0.786: "78.6%",
    1.0: "100%",
}


def calculate_fibonacci(high: float, low: float, direction: str = "up") -> Dict[float, float]:
    diff = high - low
    levels = {}

    if direction == "up":
        for level in FIB_LEVELS:
            levels[level] = high - (diff * level)
    else:
        for level in FIB_LEVELS:
            levels[level] = low + (diff * level)

    return levels


def get_fibonacci_from_scan(scan_result: dict) -> Optional[Dict]:
    if not scan_result:
        return None

    closes = scan_result.get("closes")
    if not closes or len(closes) < 20:
        return None

    recent = closes[-50:] if len(closes) >= 50 else closes
    high = max(recent)
    low = min(recent)

    if high == low:
        return None

    trend = scan_result.get("trend", "sideways")
    direction = "up" if trend == "uptrend" else "down"

    levels = calculate_fibonacci(high, low, direction)
    current_price = scan_result.get("current_price", closes[-1])

    nearest_level = None
    nearest_distance = float("inf")
    for level, price in levels.items():
        dist = abs(current_price - price) / current_price * 100
        if dist < nearest_distance:
            nearest_distance = dist
            nearest_level = level

    return {
        "high": high,
        "low": low,
        "direction": direction,
        "levels": levels,
        "current_price": current_price,
        "nearest_level": nearest_level,
        "nearest_distance": nearest_distance,
    }


def format_fibonacci(fib_data: dict) -> str:
    if not fib_data:
        return ""

    levels = fib_data["levels"]
    current = fib_data["current_price"]
    direction = "صاعد" if fib_data["direction"] == "up" else "هابط"
    nearest = fib_data["nearest_level"]
    nearest_dist = fib_data["nearest_distance"]

    lines = [
        f"📐 مستويات فيبوناتشي ({direction})\n",
        f"أعلى نقطة: {fib_data['high']:,.4f}",
        f"أدنى نقطة: {fib_data['low']:,.4f}",
        f"السعر الحالي: {current:,.4f}\n",
        "المستويات:",
    ]

    for level in FIB_LEVELS:
        price = levels[level]
        name = FIB_NAMES[level]
        marker = " ◀️ أنت هنا" if level == nearest else ""
        lines.append(f"  {name}: {price:,.4f}{marker}")

    lines.append(f"\nأقرب مستوى: {FIB_NAMES.get(nearest, 'N/A')} ({nearest_dist:.1f}%)")

    return "\n".join(lines)
