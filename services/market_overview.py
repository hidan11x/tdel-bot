import asyncio
from typing import Dict, List, Optional, Any
from loguru import logger

from services.scanner import scan_symbol, TOP_SYMBOLS
from services.symbols_service import get_symbol_info


MARKET_NAMES = {
    "SAUDI": "السعودي",
    "US": "الأمريكي",
    "CRYPTO": "الرقمية",
}


async def get_market_overview(market: str) -> Optional[str]:
    market_key = market.upper()
    symbols = TOP_SYMBOLS.get(market_key, [])[:10]

    if not symbols:
        return None

    results = []
    for sym in symbols:
        try:
            result = await scan_symbol(sym, market_key, "1d")
            if result:
                results.append(result)
        except Exception:
            continue

    if not results:
        return None

    up_count = sum(1 for r in results if r.get("trend") == "uptrend")
    down_count = sum(1 for r in results if r.get("trend") == "downtrend")
    sideways_count = sum(1 for r in results if r.get("trend") == "sideways")

    avg_change = sum(r.get("change_percent", 0) for r in results) / len(results)
    avg_score = 0
    for r in results:
        score = r.get("score")
        if score:
            try:
                avg_score += float(score.overall)
            except Exception:
                pass
    avg_score = avg_score / len(results) if results else 0

    top_gainer = max(results, key=lambda r: r.get("change_percent", -999))
    top_loser = min(results, key=lambda r: r.get("change_percent", 999))
    strongest = max(results, key=lambda r: float(r.get("score").overall) if r.get("score") else 0)

    market_name = MARKET_NAMES.get(market_key, market_key)

    async def get_name(symbol):
        info = await get_symbol_info(symbol, market_key)
        return info["name_ar"] if info else symbol

    gainer_name = await get_name(top_gainer["symbol"])
    loser_name = await get_name(top_loser["symbol"])
    strongest_name = await get_name(strongest["symbol"])

    def fmt_price(p):
        if p is None:
            return "N/A"
        if p >= 1000:
            return f"{p:,.2f}"
        if p >= 1:
            return f"{p:.4f}"
        return f"{p:.6f}"

    def fmt_change(c):
        sign = "+" if c >= 0 else ""
        return f"{sign}{c:.2f}%"

    lines = [
        f"📊 نظرة شاملة - السوق {market_name}\n",
        f"📈 صاعد: {up_count} | 📉 هابط: {down_count} | ↔️ جانبي: {sideways_count}",
        f"📊 متوسط التغير: {fmt_change(avg_change)}",
        f"⭐ متوسط التقييم: {avg_score:.0f}/100\n",
        f"━━━━━━━━━━━━━━━━",
        f"🟢 أقوى ارتفاع:",
        f"  {gainer_name} ({top_gainer['symbol']})",
        f"  {fmt_change(top_gainer.get('change_percent', 0))} | {fmt_price(top_gainer.get('current_price'))}\n",
        f"🔴 أقوى انخفاض:",
        f"  {loser_name} ({top_loser['symbol']})",
        f"  {fmt_change(top_loser.get('change_percent', 0))} | {fmt_price(top_loser.get('current_price'))}\n",
        f"⭐ أقوى قراءة فنية:",
        f"  {strongest_name} ({strongest['symbol']})",
    ]

    strongest_score = strongest.get("score")
    if strongest_score:
        lines.append(f"  التقييم: {float(strongest_score.overall):.0f}/100")

    lines.append(f"\nهذا تحليل آلي تعليمي وليس توصية مالية.")

    return "\n".join(lines)


async def get_daily_market_summary() -> Optional[str]:
    summaries = []
    for market in ["SAUDI", "US", "CRYPTO"]:
        overview = await get_market_overview(market)
        if overview:
            summaries.append(overview)

    if not summaries:
        return None

    header = "📊 الملخص اليومي للأسواق\n\n"
    return header + "\n\n".join(summaries)
