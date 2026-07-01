from typing import Dict, Optional


def calculate_risk(
    capital: float,
    risk_percent: float,
    entry_price: float,
    stop_loss: float,
    take_profit: float = None,
) -> Optional[Dict]:
    if entry_price <= 0 or stop_loss <= 0:
        return None
    if risk_percent <= 0 or risk_percent > 100:
        return None
    if capital <= 0:
        return None

    risk_amount = capital * (risk_percent / 100)

    per_unit_risk = abs(entry_price - stop_loss)
    if per_unit_risk <= 0:
        return None

    position_size = risk_amount / per_unit_risk
    position_value = position_size * entry_price

    risk_reward = None
    if take_profit and take_profit > 0:
        reward_per_unit = abs(take_profit - entry_price)
        if reward_per_unit > 0:
            risk_reward = reward_per_unit / per_unit_risk

    potential_loss = position_size * per_unit_risk
    potential_profit = None
    if take_profit and take_profit > 0:
        potential_profit = position_size * abs(take_profit - entry_price)

    return {
        "capital": capital,
        "risk_percent": risk_percent,
        "risk_amount": risk_amount,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "position_size": position_size,
        "position_value": position_value,
        "per_unit_risk": per_unit_risk,
        "potential_loss": potential_loss,
        "potential_profit": potential_profit,
        "risk_reward_ratio": risk_reward,
    }


def format_risk_calc(calc: Dict) -> str:
    lines = [
        "📊 حاسبة المخاطر\n",
        f"💰 رأس المال: {calc['capital']:,.2f}",
        f"⚠️ نسبة المخاطرة: {calc['risk_percent']:.1f}%",
        f"💵 المبلغ المخاطر: {calc['risk_amount']:,.2f}\n",
        f"📥 سعر الدخول: {calc['entry_price']:,.4f}",
        f"🛑 مستوى إدارة المخاطر: {calc['stop_loss']:,.4f}",
    ]

    if calc.get("take_profit"):
        lines.append(f"🎯 مستوى الهدف: {calc['take_profit']:,.4f}")

    lines.append(f"\n📦 حجم الصفقة: {calc['position_size']:,.4f} وحدة")
    lines.append(f"💲 قيمة المركز: {calc['position_value']:,.2f}")
    lines.append(f"📉 الخسارة المحتملة: {calc['potential_loss']:,.2f}")

    if calc.get("potential_profit"):
        lines.append(f"📈 الربح المحتمل: {calc['potential_profit']:,.2f}")

    if calc.get("risk_reward_ratio"):
        rr = calc["risk_reward_ratio"]
        lines.append(f"⚖️ نسبة العائد/المخاطرة: 1:{rr:.2f}")

    lines.append(
        "\n⚠️ هذه حاسبة تعليمية لإدارة المخاطر فقط.\n"
        "هذا البوت لا يقدم توصيات مالية. القرار مسؤولية المستخدم."
    )

    return "\n".join(lines)
