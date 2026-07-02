from typing import List, Dict, Optional, Any
from difflib import SequenceMatcher

from sqlalchemy import select, or_
from rapidfuzz import fuzz, process

from database import get_session
from models import Symbol

SYNONYM_MAP: Dict[str, List[str]] = {
    # Saudi Banks
    "الراجحي": ["مصرف الراجحي", "بنك الراجحي", "الراجحي"],
    "البلاد": ["بنك البلاد", "مصرف البلاد"],
    "الاهلي": ["البنك الأهلي", "الأهلي", "البنك الاهلي السعودي"],
    "الانماء": ["مصرف الإنماء", "بنك الانماء"],
    "الرياض": ["بنك الرياض"],
    "ساب": ["بنك ساب", "البنك السعودي البريطاني"],
    "العربي": ["البنك العربي"],
    "الجزيرة": ["بنك الجزيرة"],
    "الاستثمار": ["البنك السعودي للاستثمار"],

    # Saudi Energy
    "أرامكو": ["ارامكو", "سaudi أرامكو", "Saudi Aramco"],
    "بترو رابغ": ["رابغ"],
    "الدريس": ["شركة الدريس"],

    # Saudi Petrochemicals
    "سابك": ["SABIC", "الصناعات الأساسية"],
    "كيمانول": [],
    "بتروكيم": [],
    "ينساب": ["ينبع"],
    "سبكيم": ["سبكيم العالمية"],
    "المجموعة السعودية": [],
    "كيما": ["الكيماوية"],
    "زجاج": ["شركة زجاج"],
    "المتقدمة": ["الشركة المتقدمة"],
    "الأسمدة": ["شركة الأسمدة"],
    "نماء": ["نماء للكيماويات"],
    "سافكو": ["الأسمدة العربية"],

    # Telecom
    "الاتصالات": ["stc", "اس تي سي", "شركة الاتصالات"],
    "زين": ["Zain"],
    "اتحاد": ["موبايلي", "Mobily", "اتحاد اتصالات"],

    # Healthcare
    "الحبيب": ["د. سليمان الحبيب", "مستشفى الحبيب"],
    "المواساة": [],
    "الحمادي": [],
    "دله": ["مستشفى دله"],
    "المستشفى": [],
    "الرعاية": [],

    # Real Estate
    "الرياض العقارية": [],
    "جبل عمر": [],
    "تعمير": [],
    "المملكة": ["شركة المملكة"],
    "إعمار": ["Emaar"],
    "سكن": [],  # shouldn't match "مساكن"

    # Food
    "المراعي": [],
    "سدافكو": [],
    "نادك": [],
    "كتشن": [],
    "هرفي": ["Herfy"],
    "العربية": [],
    "وفرة": [],
    "أسواق العثيم": ["العثيم", "أسواق عبد الله العثيم"],
    "الدواء": ["صيدلية الدواء"],

    # Insurance
    "التعاونية": [],
    "بوبا": ["Bupa"],
    "الدرع": [],
    "الاهلي تكافل": [],
    "ولاء": [],
    "أسيج": [],
    "العربية للتأمين": [],
    "أليانز": [],
    "ملاذ": [],
    "الخليجية": [],
    "الوطنية": [],
    "ساب تكافل": [],
    "سوليدرتي": [],
    "توبس": [],
    "أكسا": ["AXA"],
    "الصقر": [],
    "الأنماء": [],
    "ميدغلف": [],
    "أملاك": [],
    "جسر": [],
    "أبشر": [],
    "السعودية الهندية": [],
    "سند": [],
    "تكافل الراجحي": [],
    "عناية": [],
    "أمان": [],
    "أول": [],
    "أرباح": [],
    "العربية الأوروبية": [],

    # US Stocks
    "ابل": ["آبل", "Apple", "أpple"],
    "تسلا": ["Tesla"],
    "نفيديا": ["Nvidia", "انفيديا", "nVIDIA"],
    "مايكروسوفت": ["Microsoft", "ميكروسوفت"],
    "امازون": ["Amazon", "أمازون"],
    "قوقل": ["Google", "جوجل", "Alphabet", "ألفابت", "GOOGL"],
    "ميتا": ["Meta", "فيسبوك", "Facebook"],
    "تويتر": ["Twitter", "X"],
    "نتفلكس": ["Netflix", "نتفليكس"],
    "انفيديا": ["Nvidia", "نفيديا"],
    "ادوبي": ["Adobe"],
    "اوراكل": ["Oracle"],
    "انتل": ["Intel"],
    "ام دي": ["AMD", "Advanced Micro Devices"],
    "برودكوم": ["Broadcom", "AVGO"],
    "تسكو": ["Texas Instruments"],
    "كوالكوم": ["Qualcomm"],
    "سيسكو": ["Cisco"],
    "اي بي ام": ["IBM"],
    "بالانتير": ["Palantir"],
    "سنوفلايك": ["Snowflake"],
    "كرودسترايك": ["CrowdStrike"],
    "سيلزفورس": ["Salesforce"],
    "بايبال": ["PayPal"],
    "بنك اوف امريكا": ["Bank of America", "بوك أوف أمريكا"],
    "جولدمان": ["Goldman Sachs"],
    "جي بي مورجان": ["JPMorgan", "JPM"],
    "مورجان ستانلي": ["Morgan Stanley"],
    "وول مارت": ["Walmart"],
    "كوكاكولا": ["Coca-Cola", "كوكا كولا"],
    "بيبسي": ["Pepsi"],
    "ماكدونالدز": ["McDonald's", "ماك"],
    "نايك": ["Nike"],
    "ديزني": ["Disney"],
    "بوينج": ["Boeing"],
    "كاتربيلر": ["Caterpillar"],
    "يونايتد": ["United Airlines", "يونايتد إيرلاينز"],
    "دلتا": ["Delta Air Lines"],
    "أمريكان": ["American Airlines"],
    "اوبر": ["Uber"],
    "ليفت": ["Lyft"],
    "تيفا": ["Teva", "Teva Pharmaceutical"],

    # Crypto
    "بيتكوين": ["Bitcoin", "BTC", "bitcoin", "بتكوين", "بت كوين"],
    "ايثريوم": ["Ethereum", "ETH", "إيثريوم", "اثريوم", "ايثر"],
    "سولانا": ["Solana", "SOL"],
    "ريبل": ["Ripple", "XRP"],
    "دوجكوين": ["Dogecoin", "DOGE", "دوج"],
    "كاردانو": ["Cardano", "ADA"],
    "بولكادوت": ["Polkadot", "DOT"],
    "بينانس": ["Binance", "BNB", "بينانس كوين"],
    "تشارت": ["Chainlink", "LINK"],
    "افالانش": ["Avalanche", "AVAX"],
    "بوليجون": ["Polygon", "MATIC"],
    "ليتكوين": ["Litecoin", "LTC"],
    "ترون": ["TRON", "TRX"],
    "ستيلار": ["Stellar", "XLM"],
    "مونيرو": ["Monero", "XMR"],
    "إيوس": ["EOS"],
    "نيار": ["Near", "NEAR Protocol"],
    "أبتوس": ["Aptos", "APT"],
    "أربيوم": ["Arbitrum", "ARB"],
    "وب فاونديشن": ["Web3 Foundation"],
    "بيتفين": ["Bitfinex"],
    "وش": ["VeChain", "VET"],
    "الجراف": ["The Graph", "GRT"],
    "ساند": ["The Sandbox", "SAND"],
    "ديسنترالاند": ["Decentraland", "MANA"],
    "إثير": ["Aave", "AAVE"],
    "سوشي": ["SushiSwap", "SUSHI"],
    "يوني": ["Uniswap", "UNI"],
    "بينك": ["PancakeSwap", "CAKE"],
}


def _normalize(text: str) -> str:
    text = text.strip()
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ة", "ه")
    text = text.replace("ى", "ي")
    text = text.replace("ؤ", "و").replace("ئ", "ي")
    text = text.replace("گ", "ك")
    text = text.replace("  ", " ")
    return text.lower()


def _expand_query(query: str) -> List[str]:
    normalized = _normalize(query)
    expanded = {normalized, query.lower()}
    # Check against synonyms
    for keyword, aliases in SYNONYM_MAP.items():
        kw_norm = _normalize(keyword)
        if kw_norm in normalized or normalized in kw_norm:
            expanded.add(kw_norm)
            for alias in aliases:
                expanded.add(_normalize(alias))
                expanded.add(alias.lower())
        for alias in aliases:
            alias_norm = _normalize(alias)
            if alias_norm in normalized or normalized in alias_norm:
                expanded.add(alias_norm)
                expanded.add(kw_norm)
                for a2 in aliases:
                    expanded.add(_normalize(a2))
    # Also check each word of the query
    words = normalized.split()
    for word in words:
        if len(word) > 2:
            for keyword, aliases in SYNONYM_MAP.items():
                kw_norm = _normalize(keyword)
                if kw_norm == word:
                    expanded.add(kw_norm)
                    for alias in aliases:
                        expanded.add(_normalize(alias))
    return list(expanded)


async def smart_search(query: str, limit: int = 8) -> List[Dict[str, Any]]:
    expanded = _expand_query(query)
    results = []
    seen_ids = set()

    async with get_session() as session:
        # Step 1: Direct DB search with all expanded terms
        for term in expanded:
            if term in seen_ids:
                continue
            stmt = (
                select(Symbol)
                .where(
                    Symbol.is_active == True,
                    or_(
                        Symbol.name_ar.ilike(f"%{term}%"),
                        Symbol.name_en.ilike(f"%{term}%"),
                        Symbol.symbol.ilike(f"%{term}%"),
                    ),
                )
                .order_by(Symbol.is_popular.desc(), Symbol.sort_order)
                .limit(limit)
            )
            result = await session.execute(stmt)
            for sym in result.scalars().all():
                if sym.id not in seen_ids:
                    seen_ids.add(sym.id)
                    results.append({
                        "id": sym.id,
                        "symbol": sym.symbol,
                        "name_ar": sym.name_ar,
                        "name_en": sym.name_en,
                        "market": sym.market,
                        "sector": sym.sector,
                        "score": 100,
                    })

        # Step 2: If few/zero results, do fuzzy search on all symbols
        if len(results) < 3:
            fuzzy_results = await _fuzzy_search(query, session)
            for fr in fuzzy_results:
                if fr["id"] not in seen_ids:
                    seen_ids.add(fr["id"])
                    results.append(fr)

    # Step 3: Score and rank
    for r in results:
        r["score"] = _calculate_score(query, r)

    results.sort(key=lambda x: (-x["score"], x["market"] != _detect_market(query)))
    return results[:limit]


async def _fuzzy_search(query: str, session) -> List[Dict]:
    query_norm = _normalize(query)
    stmt = select(Symbol).where(Symbol.is_active == True).limit(200)
    result = await session.execute(stmt)
    all_symbols = list(result.scalars().all())

    candidates = []
    for sym in all_symbols:
        ar_score = fuzz.ratio(query_norm, _normalize(sym.name_ar)) if sym.name_ar else 0
        en_score = fuzz.ratio(query_norm, _normalize(sym.name_en)) if sym.name_en else 0
        sym_score = fuzz.ratio(query_norm, _normalize(sym.symbol)) if sym.symbol else 0
        best = max(ar_score, en_score, sym_score)
        if best > 60:
            candidates.append({
                "id": sym.id,
                "symbol": sym.symbol,
                "name_ar": sym.name_ar,
                "name_en": sym.name_en,
                "market": sym.market,
                "sector": sym.sector,
                "score": best,
            })

    candidates.sort(key=lambda x: -x["score"])
    return candidates[:5]


def _calculate_score(query: str, symbol: Dict) -> int:
    query_norm = _normalize(query)
    name_ar_norm = _normalize(symbol.get("name_ar", ""))
    name_en_norm = _normalize(symbol.get("name_en", ""))
    sym_norm = _normalize(symbol.get("symbol", ""))

    score = 0
    # Exact matches
    if query_norm == sym_norm:
        score += 100
    if query_norm == name_ar_norm:
        score += 95
    if query_norm == name_en_norm:
        score += 95

    # Contains matches
    if query_norm in sym_norm:
        score += 60
    if query_norm in name_ar_norm:
        score += 50
    if query_norm in name_en_norm:
        score += 50

    # Word-in-name matches
    query_words = query_norm.split()
    for word in query_words:
        if len(word) > 2:
            if word in sym_norm:
                score += 30
            if word in name_ar_norm:
                score += 25
            if word in name_en_norm:
                score += 25

    # Partial matches (at least 60%)
    if SequenceMatcher(None, query_norm, sym_norm).ratio() > 0.6:
        score += 20
    if SequenceMatcher(None, query_norm, name_ar_norm).ratio() > 0.6:
        score += 15
    if SequenceMatcher(None, query_norm, name_en_norm).ratio() > 0.6:
        score += 15

    return score


def _detect_market(query: str) -> str:
    query_lower = query.lower()
    crypto_words = ["btc", "bitcoin", "eth", "ethereum", "sol", "solana", "xrp", "doge",
                    "ada", "dot", "bnb", "crypto", "coin", "token", "دوج", "بيتكوين",
                    "ايثريوم", "سولانا", "ريبل", "عملات"]
    us_words = ["apple", "microsoft", "google", "amazon", "tesla", "nvidia",
                "us", "american", "dow", "nasdaq", "s&p"]
    for w in crypto_words:
        if w in query_lower:
            return "CRYPTO"
    for w in us_words:
        if w in query_lower:
            return "US"
    return "SAUDI"


CRYPTO_SYMBOL_MAP = {
    "btc": "BTCUSDT", "bitcoin": "BTCUSDT", "بيتكوين": "BTCUSDT", "بتكوين": "BTCUSDT",
    "eth": "ETHUSDT", "ethereum": "ETHUSDT", "ايثريوم": "ETHUSDT", "اثريوم": "ETHUSDT", "ايثر": "ETHUSDT",
    "sol": "SOLUSDT", "solana": "SOLUSDT", "سولانا": "SOLUSDT",
    "xrp": "XRPUSDT", "ripple": "XRPUSDT", "ريبل": "XRPUSDT",
    "doge": "DOGEUSDT", "dogecoin": "DOGEUSDT", "دوجكوين": "DOGEUSDT", "دوج": "DOGEUSDT",
    "ada": "ADAUSDT", "cardano": "ADAUSDT", "كاردانو": "ADAUSDT",
    "bnb": "BNBUSDT", "binance": "BNBUSDT", "بينانس": "BNBUSDT",
    "link": "LINKUSDT", "chainlink": "LINKUSDT",
    "matic": "MATICUSDT", "polygon": "MATICUSDT", "بوليجون": "MATICUSDT",
    "avax": "AVAXUSDT", "avalanche": "AVAXUSDT", "افالانش": "AVAXUSDT",
    "ltc": "LTCUSDT", "litecoin": "LTCUSDT", "ليتكوين": "LTCUSDT",
}

COMMON_SYMBOL_ALIASES = {
    "الراجحي": ("1120.SR", "SAUDI", "مصرف الراجحي"),
    "مصرف الراجحي": ("1120.SR", "SAUDI", "مصرف الراجحي"),
    "بنك الراجحي": ("1120.SR", "SAUDI", "مصرف الراجحي"),
    "الاهلي": ("1180.SR", "SAUDI", "البنك الأهلي السعودي"),
    "الأهلي": ("1180.SR", "SAUDI", "البنك الأهلي السعودي"),
    "ارامكو": ("2222.SR", "SAUDI", "أرامكو السعودية"),
    "أرامكو": ("2222.SR", "SAUDI", "أرامكو السعودية"),
    "سابك": ("2010.SR", "SAUDI", "سابك"),
    "stc": ("7010.SR", "SAUDI", "الاتصالات السعودية"),
    "الاتصالات": ("7010.SR", "SAUDI", "الاتصالات السعودية"),
    "ابل": ("AAPL", "US", "Apple"),
    "آبل": ("AAPL", "US", "Apple"),
    "apple": ("AAPL", "US", "Apple"),
    "تسلا": ("TSLA", "US", "Tesla"),
    "tesla": ("TSLA", "US", "Tesla"),
    "نفيديا": ("NVDA", "US", "Nvidia"),
    "nvidia": ("NVDA", "US", "Nvidia"),
    "مايكروسوفت": ("MSFT", "US", "Microsoft"),
    "microsoft": ("MSFT", "US", "Microsoft"),
    "امازون": ("AMZN", "US", "Amazon"),
    "amazon": ("AMZN", "US", "Amazon"),
    "قوقل": ("GOOGL", "US", "Alphabet"),
    "جوجل": ("GOOGL", "US", "Alphabet"),
    "google": ("GOOGL", "US", "Alphabet"),
    "ميتا": ("META", "US", "Meta"),
    "meta": ("META", "US", "Meta"),
    "بيتكوين": ("BTCUSDT", "CRYPTO", "Bitcoin"),
    "بتكوين": ("BTCUSDT", "CRYPTO", "Bitcoin"),
    "bitcoin": ("BTCUSDT", "CRYPTO", "Bitcoin"),
    "ايثريوم": ("ETHUSDT", "CRYPTO", "Ethereum"),
    "اثريوم": ("ETHUSDT", "CRYPTO", "Ethereum"),
    "ethereum": ("ETHUSDT", "CRYPTO", "Ethereum"),
    "سولانا": ("SOLUSDT", "CRYPTO", "Solana"),
    "solana": ("SOLUSDT", "CRYPTO", "Solana"),
}


async def auto_detect_symbol(query: str) -> Optional[Dict[str, Any]]:
    query = query.strip()
    if not query or len(query) < 1:
        return None

    query_lower = query.lower()
    query_norm = _normalize(query)

    alias = COMMON_SYMBOL_ALIASES.get(query_lower) or COMMON_SYMBOL_ALIASES.get(query_norm)
    if alias:
        symbol, market, name = alias
        return {
            "symbol": symbol,
            "market": market,
            "name_ar": name,
            "name_en": name,
            "source": "common_alias",
        }

    from services.symbols_service import find_symbol_by_name_or_alias
    db_results = await find_symbol_by_name_or_alias(query, limit=5)

    if db_results and db_results[0].get("score", 0) >= 80:
        return {
            "symbol": db_results[0]["symbol"],
            "market": db_results[0]["market"],
            "name_ar": db_results[0]["name_ar"],
            "name_en": db_results[0]["name_en"],
            "sector": db_results[0].get("sector"),
            "source": "db",
            "alternatives": db_results[1:5],
        }

    for key, symbol in CRYPTO_SYMBOL_MAP.items():
        if key == query_lower or _normalize(key) == _normalize(query):
            return {
                "symbol": symbol,
                "market": "CRYPTO",
                "name_ar": query,
                "name_en": query,
                "source": "crypto_map",
            }

    upper = query.upper().strip()
    if upper.endswith(".SR"):
        return {
            "symbol": upper,
            "market": "SAUDI",
            "name_ar": query,
            "name_en": query,
            "source": "pattern",
        }
    if upper.endswith("USDT"):
        return {
            "symbol": upper,
            "market": "CRYPTO",
            "name_ar": query,
            "name_en": query,
            "source": "pattern",
        }

    digits_only = upper.replace(".SR", "").replace(".", "")
    if digits_only.isdigit() and len(digits_only) == 4:
        return {
            "symbol": f"{digits_only}.SR",
            "market": "SAUDI",
            "name_ar": query,
            "name_en": query,
            "source": "pattern",
        }

    clean = upper.replace(".SR", "")
    if clean.isalpha() and clean.isascii() and 1 <= len(clean) <= 6:
        return {
            "symbol": clean,
            "market": "US",
            "name_ar": query,
            "name_en": query,
            "source": "pattern",
        }

    if db_results:
        return {
            "symbol": db_results[0]["symbol"],
            "market": db_results[0]["market"],
            "name_ar": db_results[0]["name_ar"],
            "name_en": db_results[0]["name_en"],
            "sector": db_results[0].get("sector"),
            "source": "db_fuzzy",
            "alternatives": db_results[1:5],
        }

    return None


MARKET_EMOJI = {
    "SAUDI": "📈",
    "US": "🇺🇸",
    "CRYPTO": "₿",
}

MARKET_ARABIC = {
    "SAUDI": "السعودي",
    "US": "الأمريكي",
    "CRYPTO": "الرقمية",
}


def format_search_results(results: List[Dict]) -> str:
    if not results:
        return "❌ لم يتم العثور على نتائج."
    lines = ["🔍 **نتائج البحث**:\n"]
    for i, r in enumerate(results, 1):
        emoji = MARKET_EMOJI.get(r["market"], "📊")
        market_name = MARKET_ARABIC.get(r["market"], r["market"])
        name = r.get("name_ar") or r.get("name_en") or r["symbol"]
        sector = r.get("sector", "")
        sector_line = f"🏢 القطاع: {sector}\n" if sector else ""
        lines.append(
            f"{i}. 🏷 {name}\n"
            f"   🔢 {r['symbol']}\n"
            f"   {emoji} {market_name}\n"
            f"{sector_line}"
        )
    return "\n".join(lines)


def build_search_keyboard(results: List[Dict]) -> 'InlineKeyboardMarkup':
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    for r in results:
        name = r.get("name_ar") or r.get("name_en") or r["symbol"]
        short_sym = r["symbol"].replace(".SR", "").replace("USDT", "")
        label = f"{name[:20]} | {short_sym}"
        builder.button(text=label, callback_data=f"smart_result:{r['id']}")
    builder.button(text="↩️ رجوع", callback_data="main_menu")
    builder.adjust(2)
    return builder.as_markup()
