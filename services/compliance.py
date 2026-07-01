import re
from typing import List

DISCLAIMER_TEXT = (
    "هذه المعلومات لأغراض تعليمية ومتابعة السوق فقط، وليست توصية استثمارية "
    "أو دعوة للبيع أو الشراء. القرار مسؤولية المستخدم."
)

PROHIBITED_WORDS = [
    "اشترِ", "اشتر", "اشتري",
    "بع", "بيع",
    "هدف",
    "وقف خسارة",
    "دخول",
    "خروج",
    "فرصة",
    "مضمون", "مضمونة",
    "مكفول", "مكفولة",
    "أرباح مضمونة", "ارباح مضمونة",
]

PROHIBITED_PATTERNS = [
    (re.compile(r"\b" + re.escape(w) + r"\b", re.UNICODE), w)
    for w in PROHIBITED_WORDS
]


def disclaimer() -> str:
    return DISCLAIMER_TEXT


def add_disclaimer(text: str) -> str:
    return f"{text}\n\n{DISCLAIMER_TEXT}"


def validate_report(report_text: str) -> bool:
    for pattern, word in PROHIBITED_PATTERNS:
        if pattern.search(report_text):
            return False
    return True


def sanitize_report(text: str) -> str:
    for pattern, word in PROHIBITED_PATTERNS:
        if word in ["أرباح مضمونة", "ارباح مضمونة"]:
            text = pattern.sub("نتائج غير مضمونة", text)
        elif word in ["مضمون", "مضمونة"]:
            text = pattern.sub("غير مضمون", text)
        elif word in ["فرصة"]:
            text = pattern.sub("متابعة", text)
        elif word in ["دخول"]:
            text = pattern.sub("متابعة", text)
        elif word in ["خروج"]:
            text = pattern.sub("متابعة", text)
        elif word in ["هدف"]:
            text = pattern.sub("مستوى متوقع", text)
        elif word in ["وقف خسارة"]:
            text = pattern.sub("مستوى إدارة مخاطر", text)
        elif word in ["اشترِ", "اشتر", "اشتري"]:
            text = pattern.sub("متابعة", text)
        elif word in ["بع", "بيع"]:
            text = pattern.sub("متابعة", text)
    return text
