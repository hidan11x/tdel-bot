from typing import List, Dict, Optional
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models import Symbol

PAGE_SIZE = 10

SAUDI_SECTORS = [
    "البنوك", "الطاقة", "المواد الأساسية", "الاتصالات", "التأمين",
    "الرعاية الصحية", "العقار", "الأغذية", "الخدمات", "التجزئة",
    "المرافق", "الاستثمار",
]

US_CATEGORIES = [
    "التقنية", "الذكاء الاصطناعي", "السيارات الكهربائية", "البنوك",
    "الطاقة", "الرعاية الصحية", "التجزئة", "المستهلك", "الصناعة", "النقل",
]

CRYPTO_CATEGORIES = [
    "العملات الرئيسية", "Layer 1", "Layer 2", "DeFi", "Meme Coins",
]


def get_sectors(market: str) -> List[str]:
    if market == "SAUDI":
        return SAUDI_SECTORS
    elif market == "US":
        return US_CATEGORIES
    elif market == "CRYPTO":
        return CRYPTO_CATEGORIES
    return []


async def get_popular_symbols(market: str) -> List[Symbol]:
    async with get_session() as session:
        stmt = (
            select(Symbol)
            .where(Symbol.market == market, Symbol.is_active == True)
            .order_by(Symbol.is_popular.desc(), Symbol.sort_order)
            .limit(20)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def get_symbols_by_sector(market: str, sector: str, page: int = 1) -> tuple:
    async with get_session() as session:
        stmt = (
            select(Symbol)
            .where(Symbol.market == market, Symbol.sector == sector, Symbol.is_active == True)
            .order_by(Symbol.sort_order)
        )
        total = len((await session.execute(stmt)).scalars().all())
        offset = (page - 1) * PAGE_SIZE
        stmt = stmt.offset(offset).limit(PAGE_SIZE)
        result = await session.execute(stmt)
        items = list(result.scalars().all())
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        return items, page, total_pages


async def get_all_symbols_by_market(market: str, page: int = 1) -> tuple:
    async with get_session() as session:
        stmt = (
            select(Symbol)
            .where(Symbol.market == market, Symbol.is_active == True)
            .order_by(Symbol.is_popular.desc(), Symbol.sort_order)
        )
        total = len((await session.execute(stmt)).scalars().all())
        offset = (page - 1) * PAGE_SIZE
        stmt = stmt.offset(offset).limit(PAGE_SIZE)
        result = await session.execute(stmt)
        items = list(result.scalars().all())
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        return items, page, total_pages


async def search_symbols(query: str, market: Optional[str] = None) -> List[Symbol]:
    async with get_session() as session:
        stmt = select(Symbol).where(
            Symbol.is_active == True,
            or_(
                Symbol.symbol.ilike(f"%{query}%"),
                Symbol.name_ar.ilike(f"%{query}%"),
                Symbol.name_en.ilike(f"%{query}%"),
            ),
        )
        if market:
            stmt = stmt.where(Symbol.market == market)
        stmt = stmt.order_by(Symbol.is_popular.desc(), Symbol.sort_order).limit(10)
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def get_symbol_by_id(symbol_id: int) -> Optional[Symbol]:
    async with get_session() as session:
        return await session.get(Symbol, symbol_id)


async def get_symbol(market: str, symbol: str) -> Optional[Symbol]:
    async with get_session() as session:
        result = await session.execute(
            select(Symbol).where(Symbol.market == market, Symbol.symbol == symbol)
        )
        return result.scalar_one_or_none()


async def get_symbol_info(symbol: str, market: str) -> Optional[Dict]:
    async with get_session() as session:
        result = await session.execute(
            select(Symbol).where(Symbol.market == market, Symbol.symbol == symbol)
        )
        sym = result.scalar_one_or_none()
        if not sym:
            return None
        return {
            "name_ar": sym.name_ar,
            "name_en": sym.name_en,
            "sector": sym.sector,
            "market": sym.market,
            "symbol": sym.symbol,
        }


async def find_symbol_by_name_or_alias(query: str, limit: int = 8) -> List[Dict]:
    from models import SymbolAlias
    norm = _normalize_text(query)
    results = []
    seen_ids = set()

    async with get_session() as session:
        stmt = (
            select(Symbol)
            .where(
                Symbol.is_active == True,
                or_(
                    Symbol.name_ar.ilike(f"%{query}%"),
                    Symbol.name_en.ilike(f"%{query}%"),
                    Symbol.symbol.ilike(f"%{query}%"),
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
                    "source": "direct",
                })

        if len(results) < limit:
            alias_stmt = (
                select(SymbolAlias, Symbol)
                .join(Symbol, SymbolAlias.symbol_id == Symbol.id)
                .where(Symbol.is_active == True, SymbolAlias.alias.ilike(f"%{query}%"))
                .limit(limit * 2)
            )
            alias_result = await session.execute(alias_stmt)
            for alias, sym in alias_result.all():
                if sym.id not in seen_ids:
                    seen_ids.add(sym.id)
                    results.append({
                        "id": sym.id,
                        "symbol": sym.symbol,
                        "name_ar": sym.name_ar,
                        "name_en": sym.name_en,
                        "market": sym.market,
                        "sector": sym.sector,
                        "score": 90,
                        "source": "alias",
                    })

    return results[:limit]


def _normalize_text(text: str) -> str:
    text = text.strip()
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ة", "ه").replace("ى", "ي")
    return text.lower()


async def get_sectors_count(market: str) -> List[Dict]:
    async with get_session() as session:
        sectors = get_sectors(market)
        result = []
        for sector in sectors:
            cnt = await session.execute(
                select(Symbol).where(
                    Symbol.market == market, Symbol.sector == sector, Symbol.is_active == True
                )
            )
            count = len(cnt.scalars().all())
            if count > 0:
                result.append({"sector": sector, "count": count})
        return result


async def add_symbol(
    market: str, symbol: str, yahoo_symbol: str,
    name_ar: str, name_en: str, sector: str,
    exchange: str = None, currency: str = None,
) -> Symbol:
    async with get_session() as session:
        s = Symbol(
            market=market.upper(),
            symbol=symbol.upper(),
            yahoo_symbol=yahoo_symbol,
            name_ar=name_ar,
            name_en=name_en,
            sector=sector,
            exchange=exchange,
            currency=currency or ("SAR" if market.upper() == "SAUDI" else "USD"),
            asset_type="crypto" if market.upper() == "CRYPTO" else "stock",
            is_active=True,
        )
        session.add(s)
        await session.commit()
        await session.refresh(s)
        return s


async def toggle_symbol_active(symbol_id: int) -> bool:
    async with get_session() as session:
        s = await session.get(Symbol, symbol_id)
        if not s:
            return False
        s.is_active = not s.is_active
        await session.commit()
        return True


async def toggle_symbol_popular(symbol_id: int) -> bool:
    async with get_session() as session:
        s = await session.get(Symbol, symbol_id)
        if not s:
            return False
        s.is_popular = not s.is_popular
        await session.commit()
        return True


async def update_symbol(
    symbol_id: int, name_ar: str = None, name_en: str = None,
    sector: str = None, symbol: str = None, yahoo_symbol: str = None,
) -> bool:
    async with get_session() as session:
        s = await session.get(Symbol, symbol_id)
        if not s:
            return False
        if name_ar is not None:
            s.name_ar = name_ar
        if name_en is not None:
            s.name_en = name_en
        if sector is not None:
            s.sector = sector
        if symbol is not None:
            s.symbol = symbol.upper()
        if yahoo_symbol is not None:
            s.yahoo_symbol = yahoo_symbol
        await session.commit()
        return True


async def get_all_symbols_admin(market: str = None, page: int = 1) -> tuple:
    async with get_session() as session:
        stmt = select(Symbol).order_by(Symbol.id.desc())
        if market:
            stmt = stmt.where(Symbol.market == market)
        total = len((await session.execute(stmt)).scalars().all())
        offset = (page - 1) * PAGE_SIZE
        stmt = stmt.offset(offset).limit(PAGE_SIZE)
        result = await session.execute(stmt)
        items = list(result.scalars().all())
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        return items, page, total_pages, total
