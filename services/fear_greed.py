import asyncio
from typing import Optional, Dict
from loguru import logger

import requests


FNG_API_URL = "https://api.alternative.me/fng/?limit=1"


async def get_fear_greed_index() -> Optional[Dict]:
    try:
        resp = await asyncio.to_thread(
            requests.get, FNG_API_URL, timeout=10
        )
        if resp.status_code != 200:
            return None

        data = resp.json()
        if not data or not data.get("data"):
            return None

        item = data["data"][0]
        value = int(item.get("value", 0))
        classification = item.get("value_classification", "Unknown")

        if value <= 25:
            emoji = "😱"
            ar_label = "خوف شديد"
            advice = "السوق في خوف شديد — قد يكون هناك فرص شرائية محتملة (تعليمي)"
        elif value <= 45:
            emoji = "😰"
            ar_label = "خوف"
            advice = "السوق في حالة خوف — الحذر مطلوب"
        elif value <= 55:
            emoji = "😐"
            ar_label = "محايد"
            advice = "السوق محايد — بانتظار اتجاه أوضح"
        elif value <= 75:
            emoji = "😊"
            ar_label = "طمع"
            advice = "السوق في حالة طمع — الحذر من التصرفات العاطفية"
        else:
            emoji = "🤑"
            ar_label = "طمع شديد"
            advice = "السوق في طمع شديد — قد يكون هناك تصحيح قريب (تعليمي)"

        return {
            "value": value,
            "classification_en": classification,
            "classification_ar": ar_label,
            "emoji": emoji,
            "advice": advice,
        }

    except Exception as e:
        logger.warning("Fear & Greed API error: {}", e)
        return None


def format_fear_greed(data: Dict) -> str:
    if not data:
        return "❌ تعذر جلب مؤشر الخوف والطمع."

    return (
        "😱📊 مؤشر الخوف والطمع (Crypto)\n\n"
        f"{data['emoji']} القيمة: {data['value']}/100\n"
        f"الحالة: {data['classification_ar']}\n"
        f"Classification: {data['classification_en']}\n\n"
        f"💡 {data['advice']}\n\n"
        "⚠️ هذا مؤشر تعليمي وليس توصية مالية."
    )
