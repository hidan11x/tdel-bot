import asyncio
from database import get_session, engine, init_db
from models import Symbol, SymbolAlias
from sqlalchemy import select

ALIASES = {
    "1120.SR": ["الراجحي", "راجحي", "مصرف الراجحي", "alrajhi", "al rajhi", "al rajhi bank", "1120"],
    "2222.SR": ["ارامكو", "أرامكو", "أرامكو السعودية", "aramco", "saudi aramco", "2222"],
    "1180.SR": ["الاهلي", "الأهلي", "البنك الأهلي", "ncb", "national commercial bank", "1180"],
    "1010.SR": ["الرياض", "بنك الرياض", "riyad bank", "riyad", "1010"],
    "2010.SR": ["سابك", "sabic", "2010"],
    "7010.SR": ["الاتصالات", "اس تي سي", "stc", "saudi telecom", "7010"],
    "7020.SR": ["زين", "zain", "7020"],
    "4020.SR": ["ينساب", "yanbu", "4020"],
    "2280.SR": ["المراعي", "almarai", "2280"],
    "1150.SR": ["سدافكو", "sadafc", "1150"],
    "6002.SR": ["العثيم", "اسواق العثيم", "othaim", "6002"],
    "4164.SR": ["ابو motashm", "4164"],
    "1211.SR": ["كيمانول", "chemanol", "1211"],
    "2380.SR": ["بترو رابغ", "رابغ", "petrorabigh", "2380"],
    "2020.SR": ["stcPay", "2020"],
    "AAPL": ["apple", "ابل", "آبل", "أبل"],
    "MSFT": ["microsoft", "مايكروسوفت", "ميكروسوفت"],
    "NVDA": ["nvidia", "نفيديا", "انفيديا"],
    "TSLA": ["tesla", "تسلا"],
    "AMZN": ["amazon", "امازون", "أمازون"],
    "GOOGL": ["google", "قوقل", "جوجل", "alphabet", "ألفابت"],
    "META": ["meta", "facebook", "فيسبوك", "ميتا"],
    "AMD": ["amd", "ام دي"],
    "JPM": ["jpmorgan", "جي بي مورجان", "jpm"],
    "BTCUSDT": ["bitcoin", "btc", "بيتكوين", "بتكوين", "بت كوين"],
    "ETHUSDT": ["ethereum", "eth", "ايثريوم", "إيثريوم", "اثريوم", "ايثر"],
    "SOLUSDT": ["solana", "sol", "سولانا"],
    "XRPUSDT": ["ripple", "xrp", "ريبل"],
    "DOGEUSDT": ["dogecoin", "doge", "دوجكوين", "دوج"],
    "ADAUSDT": ["cardano", "ada", "كاردانو"],
    "BNBUSDT": ["binance", "bnb", "بينانس", "بينانس كوين"],
    "LINKUSDT": ["chainlink", "link", "تشارت"],
    "MATICUSDT": ["polygon", "matic", "بوليجون"],
    "AVAXUSDT": ["avalanche", "avax", "افالانش"],
    "LTCUSDT": ["litecoin", "ltc", "ليتكوين"],
}


async def seed_aliases():
    await init_db()
    async with get_session() as session:
        count = 0
        for symbol_str, aliases in ALIASES.items():
            market = "SAUDI" if symbol_str.endswith(".SR") else ("CRYPTO" if symbol_str.endswith("USDT") else "US")
            stmt = select(Symbol).where(Symbol.symbol == symbol_str, Symbol.market == market)
            result = await session.execute(stmt)
            sym = result.scalar_one_or_none()
            if not sym:
                continue

            for alias in aliases:
                lang = "ar" if any(ord(c) > 127 for c in alias) else "en"
                existing = await session.execute(
                    select(SymbolAlias).where(
                        SymbolAlias.symbol_id == sym.id,
                        SymbolAlias.alias == alias,
                    )
                )
                if not existing.scalar_one_or_none():
                    session.add(SymbolAlias(symbol_id=sym.id, alias=alias, language=lang))
                    count += 1

        await session.commit()
        print(f"Seeded {count} aliases successfully!")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed_aliases())
