import asyncio
from typing import Optional, Dict
from loguru import logger

from services.scanner import scan_symbol
from services.symbols_service import get_symbol_info


async def compare_relative_strength(symbol1: str, symbol2: str, market: str = "SAUDI") -> Optional[str]:
    try:
        r1 = await scan_symbol(symbol1, market, "1d")
        r2 = await scan_symbol(symbol2, market, "1d")

        if not r1 or not r2:
            return None

        info1 = await get_symbol_info(symbol1, market)
        info2 = await get_symbol_info(symbol2, market)
        name1 = info1["name_ar"] if info1 else symbol1
        name2 = info2["name_ar"] if info2 else symbol2

        change1 = r1.get("change_percent", 0)
        change2 = r2.get("change_percent", 0)

        score1 = float(r1.get("score").overall) if r1.get("score") else 0
        score2 = float(r2.get("score").overall) if r2.get("score") else 0

        trend1 = r1.get("trend", "sideways")
        trend2 = r2.get("trend", "sideways")

        rsi1 = r1.get("indicators", {}).get("rsi")
        rsi2 = r2.get("indicators", {}).get("rsi")

        strength1 = 0
        strength2 = 0

        if change1 > change2:
            strength1 += 1
        else:
            strength2 += 1

        if score1 > score2:
            strength1 += 1
        else:
            strength2 += 1

        if trend1 == "uptrend" and trend2 != "uptrend":
            strength1 += 1
        elif trend2 == "uptrend" and trend1 != "uptrend":
            strength2 += 1

        if rsi1 and rsi2:
            if 30 < rsi1 < 70 and (rsi2 > 70 or rsi2 < 30):
                strength1 += 1
            elif 30 < rsi2 < 70 and (rsi1 > 70 or rsi1 < 30):
                strength2 += 1

        if strength1 > strength2:
            winner = name1
            winner_symbol = symbol1
            diff = strength1 - strength2
        elif strength2 > strength1:
            winner = name2
            winner_symbol = symbol2
            diff = strength2 - strength1
        else:
            winner = None
            diff = 0

        lines = [
            "📊 مقارنة القوة النسبية\n\n",
            f"🏷 {name1} ({symbol1})",
            f"  التغير: {change1:+.2f}%",
            f"  التقييم: {score1:.0f}/100",
            f"  الاتجاه: {trend1}",
            f"  RSI: {rsi1:.1f}" if rsi1 else "  RSI: N/A",
            "",
            f"🏷 {name2} ({symbol2})",
            f"  التغير: {change2:+.2f}%",
            f"  التقييم: {score2:.0f}/100",
            f"  الاتجاه: {trend2}",
            f"  RSI: {rsi2:.1f}" if rsi2 else "  RSI: N/A",
            "",
        ]

        if winner:
            lines.append(f"🏆 الأقوى: {winner} ({winner_symbol})")
            lines.append(f"   تفوق بـ {diff} نقاط")
        else:
            lines.append("🟡 كلاهما متقارب في القوة")

        lines.append("\n⚠️ هذا تحليل تعليمي وليس توصية مالية.")

        return "\n".join(lines)

    except Exception as e:
        logger.exception("Relative strength comparison failed: {}", e)
        return None
