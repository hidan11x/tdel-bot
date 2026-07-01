import asyncio
import re
from datetime import datetime, timezone
from typing import List, Dict, Optional
from xml.etree import ElementTree

import requests
from loguru import logger
from sqlalchemy import select

from database import get_session
from models import NewsItem, User


RSS_FEEDS = {
    "SAUDI": [
        "https://news.google.com/rss/search?q=%D8%B3%D9%88%D9%82+%D8%A7%D9%84%D8%A3%D8%B3%D9%87%D9%85+%D8%A7%D9%84%D8%B3%D8%B9%D9%88%D8%AF%D9%8A+%D8%AA%D8%A7%D8%B3%D9%8A&hl=ar&gl=SA",
        "https://news.google.com/rss/search?q=%D8%A3%D8%B1%D8%A7%D9%85%D9%83%D9%88+%D8%B3%D8%B9%D9%88%D8%AF%D9%8A%D8%A9&hl=ar&gl=SA",
    ],
    "US": [
        "https://news.google.com/rss/search?q=%D8%A3%D8%B3%D9%87%D9%85+%D8%A3%D9%85%D8%B1%D9%8A%D9%83%D9%8A%D8%A9+%D9%88%D8%A7%D9%84+%D8%B3%D8%AA%D8%B1%D9%8A%D8%AA&hl=ar",
    ],
    "CRYPTO": [
        "https://news.google.com/rss/search?q=%D8%A8%D9%8A%D8%AA%D9%83%D9%88%D9%8A%D9%86+%D8%B9%D9%85%D9%84%D8%A7%D8%AA+%D8%B1%D9%82%D9%85%D9%8A%D8%A9&hl=ar",
    ],
}

SOURCE_NAMES = {
    "news.google.com": "Google News",
    "argaam.com": "Argaam",
    "tradingbelaraby.com": "تداول بالعربي",
    "hawamer.com": "هوامير البورصة",
    "mubasher.info": "مباشر",
    "alarabiya.net": "العربية",
    "aleqt.com": "الاقتصادية",
    "al-jazirah.com": "الجزيرة",
    "asharqbusiness.com": "الشرق بلومبرغ",
    "sabq.org": "سبق",
    "sayidaty.net": "سيدتي",
    "alaraby.co.uk": "العربي",
    "alhadath.net": "الحدث",
}

ARABIC_PATTERN = re.compile(r'[\u0600-\u06FF]')

MAX_NEWS_PER_FETCH = 5
MAX_TITLE_LENGTH = 200


def _is_arabic(text: str) -> bool:
    if not text:
        return False
    return bool(ARABIC_PATTERN.search(text))


def _is_stock_related(title: str) -> bool:
    stock_keywords = [
        "سهم", "أسهم", "سوق", "تداول", "بورصة", "شركة", "استثمار",
        "ارباح", "توزيعات", "اكتتاب", "مؤشر", "قطاع", "مالية",
        "اقتصاد", "بنك", "أرامكو", "سابك", "تاسي", " tadawul",
        "مرابحة", "صكوك", "اسناد", "ربح", "خسارة", "ميزانية",
        "قوائم مالية", "راجحي", "أمريكا", "بيتكوين", "عملة",
        "تأمين", "بتروكيماويات", "أسمنت", "ذهب", "نفط",
        "وال ستريت", "nasdaq", "مساهمة", "قيمة سوقية",
        "صندوق", "ريت", "ipO",
    ]
    title_lower = title.lower()
    for kw in stock_keywords:
        if kw.lower() in title_lower:
            return True
    return False


def _parse_rss(xml_text: str, market: str) -> List[Dict]:
    items = []
    try:
        root = ElementTree.fromstring(xml_text)
        for item in root.iter("item"):
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            pub_date = item.findtext("pubDate", "").strip()

            if not title or not link:
                continue

            if not _is_arabic(title):
                continue

            if not _is_stock_related(title):
                continue

            dt = None
            if pub_date:
                try:
                    from email.utils import parsedate_to_datetime
                    dt = parsedate_to_datetime(pub_date)
                    if dt and dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                except Exception:
                    dt = None

            source = "مصدر مالي"
            for src_key in SOURCE_NAMES:
                if src_key in link:
                    source = SOURCE_NAMES[src_key]
                    break

            items.append({
                "title": title[:MAX_TITLE_LENGTH],
                "url": link,
                "source": source,
                "market": market,
                "published_at": dt,
            })
    except Exception as e:
        logger.warning("RSS parse error: {}", e)

    return items


async def fetch_news(market: str) -> List[Dict]:
    feeds = RSS_FEEDS.get(market.upper(), [])
    all_items = []

    for feed_url in feeds:
        try:
            resp = await asyncio.to_thread(
                requests.get, feed_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"}
            )
            if resp.status_code == 200:
                items = _parse_rss(resp.text, market)
                all_items.extend(items)
        except Exception as e:
            logger.warning("Failed to fetch RSS from {}: {}", feed_url, e)

    seen_titles = set()
    unique = []
    for item in all_items:
        if item["title"] not in seen_titles:
            seen_titles.add(item["title"])
            unique.append(item)

    return unique[:MAX_NEWS_PER_FETCH * 2]


async def save_and_get_new_news(market: str) -> List[Dict]:
    items = await fetch_news(market)
    new_items = []

    async with get_session() as session:
        for item in items:
            stmt = select(NewsItem).where(NewsItem.url == item["url"])
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                continue

            news = NewsItem(
                title=item["title"],
                url=item["url"],
                source=item["source"],
                market=item["market"],
                published_at=item.get("published_at"),
                sent=False,
            )
            session.add(news)
            new_items.append(item)

        if new_items:
            await session.commit()

    return new_items[:MAX_NEWS_PER_FETCH]


async def get_recent_news(market: str = "general", limit: int = 10) -> List[NewsItem]:
    async with get_session() as session:
        stmt = (
            select(NewsItem)
            .order_by(NewsItem.created_at.desc())
            .limit(limit)
        )
        if market != "general":
            stmt = stmt.where(NewsItem.market == market.upper())

        result = await session.execute(stmt)
        return list(result.scalars().all())


def format_news_items(items: List[NewsItem], market_label: str = "") -> str:
    if not items:
        return "📰 لا توجد أخبار متاحة حالياً."

    header = f"📰 آخر أخبار السوق{f' - {market_label}' if market_label else ''}\n\n"
    lines = []

    for i, item in enumerate(items[:10], 1):
        lines.append(f"{i}. 📄 {item.title}")
        lines.append(f"   المصدر: {item.source}")
        lines.append(f"   🔗 {item.url}")
        lines.append("")

    return header + "\n".join(lines).strip()


async def send_news_notifications(bot) -> int:
    sent_count = 0
    try:
        for market in ["US", "CRYPTO", "SAUDI"]:
            new_items = await save_and_get_new_news(market)
            if not new_items:
                continue

            async with get_session() as session:
                stmt = select(User).where(
                    User.is_active == True,
                    User.is_banned == False,
                    User.daily_report == True,
                )
                result = await session.execute(stmt)
                users = list(result.scalars().all())

            if not users:
                continue

            market_label = {"US": "الأمريكي", "CRYPTO": "الرقمية", "SAUDI": "السعودي"}.get(market, market)

            for item in new_items:
                message = (
                    f"📰 خبر جديد - السوق {market_label}\n\n"
                    f"📄 {item['title']}\n"
                    f"المصدر: {item['source']}\n"
                    f"🔗 {item['url']}"
                )

                for user in users:
                    try:
                        await bot.send_message(user.telegram_id, message[:4000])
                        sent_count += 1
                        await asyncio.sleep(0.1)
                    except Exception:
                        continue

                await asyncio.sleep(1)

        if sent_count:
            logger.info("News notifications: {} sent", sent_count)

    except Exception:
        logger.exception("send_news_notifications failed")

    return sent_count
