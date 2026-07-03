# Telegram Trading Bot

بوت تليجرام لمتابعة الأسواق مع لوحة VIP وواجهة API وسيطة للسوق السعودي.

## المزايا الحالية

- بحث ذكي بالرمز أو اسم الشركة بالعربي/الإنجليزي.
- دعم السوق السعودي، الأمريكي، والعملات الرقمية.
- بطاقات أسعار مرتبة للأسهم السعودية.
- شارتات، تنبيهات، متابعة، فحص فني، ولوحة VIP.
- API وسيط للسوق السعودي مع كاش وحد طلبات.

## تشغيل محلي

```cmd
cd C:\Users\hidan\Desktop\telegram-trading-bot
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python start_prod.py
```

## Railway

Railway يشغل المشروع عبر:

```cmd
python start_prod.py
```

أهم المتغيرات:

```env
BOT_TOKEN="ضع توكن البوت"
ADMIN_IDS="8601339909"
DATABASE_URL="postgresql://..."
DASHBOARD_BASE_URL="https://your-service.up.railway.app"
DASHBOARD_PORT="8080"
MARKET_TIMEZONE="Asia/Riyadh"
YFINANCE_ENABLED="true"
BINANCE_ENABLED="true"
SAUDI_EXCHANGE_ENABLED="true"
SAUDI_EXCHANGE_PAGE_URL="https://www.saudiexchange.sa/wps/portal/saudiexchange/ourmarkets/main-market-watch?locale=ar"
SAUDI_API_CACHE_SECONDS="180"
SAUDI_API_RATE_LIMIT_PER_MINUTE="60"
SAUDI_API_KEY="اختياري-لجعل-api-خاص"
```

## Saudi Market Mediator API

الـ API يعمل داخل نفس رابط Railway. مصدر الأسهم السعودية هو صفحة تداول السعودية الرسمية، ويقرأ جدول السوق عبر جلسة Web ببصمة Chrome خفيفة ثم يخزن النتائج في الكاش وقاعدة البيانات. لا يوجد API مدفوع. النظام يعرض بيانات السوق فقط ولا يقدم أوامر شراء/بيع أو توصيات.

### جلب سهم

```http
GET /stock/{symbol}
```

أمثلة:

```cmd
curl "https://tdel-bot-production.up.railway.app/stock/1120"
curl "https://tdel-bot-production.up.railway.app/stock/الراجحي"
```

إذا فعلت `SAUDI_API_KEY`:

```cmd
curl -H "X-API-Key: YOUR_KEY" "https://tdel-bot-production.up.railway.app/stock/1120"
```

الاستجابة:

```json
{
  "ok": true,
  "symbol": "1120",
  "name": "مصرف الراجحي",
  "price": "xx.xx",
  "change": "+x.xx",
  "changePercent": "+x.xx%",
  "high": "xx.xx",
  "low": "xx.xx",
  "volume": "123,456",
  "lastUpdate": "2026-07-03 10:30:00",
  "source": "Saudi Exchange"
}
```

### البحث

```http
GET /search?q=الراجحي
GET /api/saudi/search?q=أرامكو&limit=10
```

يرجع قائمة مطابقة:

```json
{
  "ok": true,
  "query": "الراجحي",
  "items": [
    {
      "symbol": "1120",
      "yahooSymbol": "1120.SR",
      "name": "مصرف الراجحي",
      "market": "SAUDI"
    }
  ]
}
```

### المسارات البديلة

- `GET /api/saudi/stock/{symbol}`
- `GET /api/saudi/search?q=...`

## ربط البوت

عند كتابة المستخدم `1120` أو `الراجحي` أو `أرامكو`:

- يحاول البوت حذف رسالة الانتظار.
- يجلب أحدث بيانات متاحة من خدمة السوق السعودي.
- يرسل بطاقة مرتبة فيها السعر، التغير، النسبة، الأعلى، الأدنى، الحجم، آخر تحديث، والمصدر.
- يضيف أزرار: تحديث، تفاصيل، رسم بياني، متابعة، حذف من القائمة.

## ملاحظات مهمة

- بيانات تداول السعودية نفسها قد تكون متأخرة حسب تنويه الموقع.
- إذا تعذر تحديث صفحة تداول، يستخدم النظام آخر كاش محفوظ فقط.
- استخدم `SAUDI_API_KEY` إذا تبي الـ API خاص لك فقط.
- لا تضع التوكنات أو مفاتيح API في Git.
