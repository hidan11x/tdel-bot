import asyncio
import os
import time
from datetime import date
from typing import Any

from aiohttp import web
from loguru import logger
from sqlalchemy import func, select

from config import settings
from database import get_session
from models import Alert, ErrorLog, ScanLog, Symbol, User, Watchlist
from services.dashboard_auth import verify_dashboard_token
from services.market_data import YahooFinanceProvider, get_ohlcv
from services.scanner import TOP_SYMBOLS
from services.signal_engine import build_signal


RADAR_TTL_SECONDS = 90
_radar_cache: dict[str, Any] = {"expires": 0.0, "items": []}


def _env_value(key: str, default: str = "") -> str:
    value = os.getenv(key, default).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def _json(data: dict[str, Any], status: int = 200) -> web.Response:
    return web.json_response(data, status=status, headers={"Cache-Control": "no-store"})


def _is_vip(user: User) -> bool:
    return user.telegram_id in settings.admin_ids or user.plan in {"vip", "lifetime"}


async def _authorized_user(request: web.Request) -> User | web.Response:
    try:
        telegram_id = int(request.match_info["telegram_id"])
    except (KeyError, ValueError):
        return web.Response(text="رابط غير صالح", status=400)

    token = request.match_info.get("token", "")
    if not verify_dashboard_token(telegram_id, token):
        return web.Response(text="الرابط غير صالح أو منتهي", status=403)

    async with get_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()

    if not user:
        return web.Response(text="المستخدم غير موجود", status=404)
    if not _is_vip(user):
        return web.Response(text="هذه اللوحة مخصصة لمشتركي VIP فقط", status=403)
    return user


async def dashboard_page(request: web.Request) -> web.Response:
    user = await _authorized_user(request)
    if isinstance(user, web.Response):
        return user

    html = DASHBOARD_HTML.replace("__TG_ID__", str(user.telegram_id)).replace(
        "__TOKEN__", request.match_info["token"]
    )
    return web.Response(text=html, content_type="text/html", charset="utf-8")


async def dashboard_summary(request: web.Request) -> web.Response:
    user = await _authorized_user(request)
    if isinstance(user, web.Response):
        return user

    today = settings.today()
    async with get_session() as session:
        watchlist = (
            await session.execute(
                select(Watchlist).where(Watchlist.user_id == user.id).order_by(Watchlist.added_at.desc())
            )
        ).scalars().all()
        alerts_count = (
            await session.execute(
                select(func.count(Alert.id)).where(Alert.user_id == user.id, Alert.is_active == True)
            )
        ).scalar() or 0
        scans_today = (
            await session.execute(
                select(func.count(ScanLog.id)).where(
                    ScanLog.user_id == user.id,
                    func.date(ScanLog.created_at) == today,
                )
            )
        ).scalar() or 0
        total_scans = (
            await session.execute(select(func.count(ScanLog.id)).where(ScanLog.user_id == user.id))
        ).scalar() or 0
        last_scans = (
            await session.execute(
                select(ScanLog)
                .where(ScanLog.user_id == user.id)
                .order_by(ScanLog.created_at.desc())
                .limit(5)
            )
        ).scalars().all()
        errors_today = (
            await session.execute(
                select(func.count(ErrorLog.id)).where(func.date(ErrorLog.created_at) == today)
            )
        ).scalar() or 0

    market_status = YahooFinanceProvider.get_market_status()
    symbols = [
        {"symbol": item.symbol, "market": item.market, "note": item.note or ""}
        for item in watchlist[:20]
    ]
    if not symbols:
        symbols = [
            {"symbol": "1120.SR", "market": "SAUDI", "note": "الراجحي"},
            {"symbol": "AAPL", "market": "US", "note": "Apple"},
            {"symbol": "BTCUSDT", "market": "CRYPTO", "note": "Bitcoin"},
        ]

    return _json(
        {
            "user": {
                "name": user.first_name,
                "username": user.username or "",
                "plan": user.plan,
                "subscription_end": user.subscription_end.isoformat() if user.subscription_end else "",
            },
            "cards": {
                "watchlist": len(watchlist),
                "alerts": alerts_count,
                "scans_today": scans_today,
                "total_scans": total_scans,
                "errors_today": errors_today,
            },
            "markets": market_status,
            "symbols": symbols,
            "last_scans": [
                {
                    "symbol": scan.symbol,
                    "market": scan.market,
                    "score": scan.score,
                    "signal": scan.signal or "",
                    "created_at": scan.created_at.isoformat() if scan.created_at else "",
                }
                for scan in last_scans
            ],
            "server_time": settings.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    )


async def dashboard_radar(request: web.Request) -> web.Response:
    user = await _authorized_user(request)
    if isinstance(user, web.Response):
        return user

    now = time.time()
    if _radar_cache["expires"] > now:
        return _json({"items": _radar_cache["items"], "cached": True})

    from services.opportunities import flatten_radar, get_radar_opportunities

    radar = await get_radar_opportunities(vip=True)
    items = []
    for result in flatten_radar(radar)[:9]:
        signal = build_signal(result)
        items.append(
            {
                "symbol": signal.symbol,
                "market": signal.market,
                "name": signal.name_ar if signal.name_ar != signal.symbol else signal.name_en,
                "price": signal.current_price,
                "change": signal.change_percent,
                "score": round(signal.score),
                "confidence": signal.confidence,
                "trend": signal.trend,
                "risk": signal.risk_level,
                "support": signal.support,
                "resistance": signal.resistance,
            }
        )

    _radar_cache.update({"expires": now + RADAR_TTL_SECONDS, "items": items})
    return _json({"items": items, "cached": False})


async def dashboard_chart(request: web.Request) -> web.Response:
    user = await _authorized_user(request)
    if isinstance(user, web.Response):
        return user

    symbol = request.query.get("symbol", "BTCUSDT").strip().upper()
    market = request.query.get("market", "CRYPTO").strip().upper()
    interval = request.query.get("interval", "1d").strip()
    if interval not in {"15m", "1h", "4h", "1d", "1wk"}:
        interval = "1d"

    data = await asyncio.to_thread(get_ohlcv, symbol, market, interval, 160)
    if not data:
        return _json({"data": [], "message": "لا توجد بيانات كافية"}, status=404)

    return _json(
        {
            "symbol": symbol,
            "market": market,
            "interval": interval,
            "data": [
                {
                    "time": int(row["timestamp"]),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume", 0)),
                }
                for row in data[-160:]
            ],
        }
    )


async def dashboard_symbols(request: web.Request) -> web.Response:
    user = await _authorized_user(request)
    if isinstance(user, web.Response):
        return user

    market = request.query.get("market", "ALL").strip().upper()
    query = request.query.get("q", "").strip()
    try:
        limit = min(500, max(20, int(request.query.get("limit", "120"))))
    except ValueError:
        limit = 80

    stmt = select(Symbol).where(Symbol.is_active == True)
    if market in {"SAUDI", "US", "CRYPTO"}:
        stmt = stmt.where(Symbol.market == market)
    if query:
        like = f"%{query}%"
        stmt = stmt.where(
            (Symbol.symbol.ilike(like))
            | (Symbol.name_ar.ilike(like))
            | (Symbol.name_en.ilike(like))
        )
    stmt = stmt.order_by(Symbol.market, Symbol.is_popular.desc(), Symbol.sort_order, Symbol.symbol).limit(limit)

    async with get_session() as session:
        symbols = list((await session.execute(stmt)).scalars().all())

    items = [
        {
            "symbol": item.symbol,
            "market": item.market,
            "name_ar": item.name_ar,
            "name_en": item.name_en,
            "sector": item.sector or item.category or "",
            "popular": bool(item.is_popular),
        }
        for item in symbols
    ]

    if not items and not query:
        markets = ["SAUDI", "US", "CRYPTO"] if market == "ALL" else [market]
        for market_key in markets:
            if len(items) >= limit:
                break
            for symbol in TOP_SYMBOLS.get(market_key, [])[:limit]:
                if len(items) >= limit:
                    break
                items.append(
                    {
                        "symbol": symbol,
                        "market": market_key,
                        "name_ar": symbol,
                        "name_en": symbol,
                        "sector": "",
                        "popular": True,
                    }
                )

    return _json({"items": items[:limit], "market": market, "query": query})


async def dashboard_health(request: web.Request) -> web.Response:
    return _json({"ok": True, "service": "dashboard", "date": date.today().isoformat()})


def create_dashboard_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", dashboard_health)
    app.router.add_get("/dashboard/{telegram_id}/{token}", dashboard_page)
    app.router.add_get("/api/dashboard/{telegram_id}/{token}/summary", dashboard_summary)
    app.router.add_get("/api/dashboard/{telegram_id}/{token}/radar", dashboard_radar)
    app.router.add_get("/api/dashboard/{telegram_id}/{token}/chart", dashboard_chart)
    app.router.add_get("/api/dashboard/{telegram_id}/{token}/symbols", dashboard_symbols)
    return app


async def start_dashboard_server() -> web.AppRunner:
    app = create_dashboard_app()
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(_env_value("DASHBOARD_PORT") or _env_value("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("VIP dashboard started on port {}", port)
    return runner


DASHBOARD_HTML = r"""
<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <title>لوحة VIP | تداول بوت</title>
  <script src="https://unpkg.com/lightweight-charts@4.2.3/dist/lightweight-charts.standalone.production.js"></script>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0e1116;
      --panel: #171c23;
      --panel-2: #1e252e;
      --text: #f4f7fb;
      --muted: #96a2b4;
      --line: #2b3441;
      --teal: #27d3b2;
      --amber: #f4b860;
      --green: #39d98a;
      --red: #ff6b6b;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Tahoma, Arial, sans-serif;
    }
    .shell { display: grid; grid-template-columns: 248px 1fr; min-height: 100vh; }
    aside {
      border-left: 1px solid var(--line);
      background: #11161d;
      padding: 22px 18px;
      position: sticky;
      top: 0;
      height: 100vh;
    }
    .brand { font-size: 22px; font-weight: 800; margin-bottom: 24px; }
    .nav { display: grid; gap: 8px; }
    .nav button {
      width: 100%;
      border: 0;
      border-radius: 8px;
      padding: 12px 14px;
      color: var(--muted);
      background: transparent;
      text-align: right;
      font: inherit;
    }
    .nav button.active, .nav button:hover { color: var(--text); background: var(--panel-2); }
    main { padding: 22px; max-width: 1440px; width: 100%; margin: 0 auto; }
    header { display: flex; justify-content: space-between; gap: 12px; align-items: center; margin-bottom: 18px; }
    h1 { margin: 0; font-size: 24px; letter-spacing: 0; }
    .sub { color: var(--muted); font-size: 14px; margin-top: 6px; }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-height: 34px;
      padding: 7px 11px;
      border-radius: 8px;
      background: rgba(39, 211, 178, .12);
      color: var(--teal);
      border: 1px solid rgba(39, 211, 178, .25);
      white-space: nowrap;
    }
    .grid { display: grid; gap: 14px; }
    .cards { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .layout { grid-template-columns: 1.35fr .8fr; align-items: start; margin-top: 14px; }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      min-width: 0;
    }
    .metric .label { color: var(--muted); font-size: 13px; }
    .metric .value { font-size: 30px; font-weight: 800; margin-top: 8px; }
    .panel h2 { font-size: 17px; margin: 0 0 13px; }
    .market-row, .scan-row, .symbol-row {
      display: grid;
      gap: 8px;
      padding: 12px 0;
      border-top: 1px solid var(--line);
    }
    .market-row:first-of-type, .scan-row:first-of-type, .symbol-row:first-of-type { border-top: 0; }
    .row-top { display: flex; justify-content: space-between; gap: 12px; align-items: center; }
    .name { font-weight: 750; }
    .muted { color: var(--muted); }
    .score { color: var(--amber); font-weight: 800; }
    .up { color: var(--green); }
    .down { color: var(--red); }
    .status { color: var(--muted); min-height: 22px; }
    .chart-tools { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
    input, select, .seg button, .market-tabs button {
      border: 1px solid var(--line);
      background: var(--panel-2);
      color: var(--text);
      border-radius: 8px;
      padding: 9px 10px;
      font: inherit;
    }
    input { width: 100%; }
    .seg { display: inline-flex; gap: 6px; }
    .symbol-tools { display: grid; gap: 9px; margin-bottom: 10px; }
    .market-tabs { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
    .seg button.active, .market-tabs button.active { border-color: var(--teal); color: var(--teal); }
    .symbol-row { cursor: pointer; }
    .symbol-row:hover { background: rgba(255,255,255,.03); }
    #chart { width: 100%; height: 390px; }
    .health { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
    .health div { background: var(--panel-2); border-radius: 8px; padding: 12px; }
    .small { font-size: 13px; }
    @media (max-width: 980px) {
      .shell { display: block; }
      aside { position: static; height: auto; border-left: 0; border-bottom: 1px solid var(--line); }
      .nav { grid-template-columns: repeat(3, 1fr); }
      .cards, .layout { grid-template-columns: 1fr; }
      main { padding: 16px; }
      header { align-items: flex-start; flex-direction: column; }
      #chart { height: 330px; }
    }
    @media (max-width: 560px) {
      .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .nav { grid-template-columns: repeat(2, 1fr); }
      .metric .value { font-size: 24px; }
      .health { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <aside>
      <div class="brand">تداول بوت VIP</div>
      <div class="nav">
        <button class="active">لوحتي</button>
        <button>الفرص</button>
        <button>الشارت</button>
        <button>المتابعة</button>
        <button>التنبيهات</button>
        <button>النظام</button>
      </div>
    </aside>
    <main>
      <header>
        <div>
          <h1>لوحة المتداول</h1>
          <div class="sub" id="welcome">جاري تحميل بيانات الحساب...</div>
        </div>
        <div class="badge">متصل مباشر</div>
      </header>

      <section class="grid cards">
        <div class="panel metric"><div class="label">قائمتي</div><div class="value" id="m-watch">-</div></div>
        <div class="panel metric"><div class="label">تنبيهاتي</div><div class="value" id="m-alerts">-</div></div>
        <div class="panel metric"><div class="label">فحوصات اليوم</div><div class="value" id="m-scans">-</div></div>
        <div class="panel metric"><div class="label">إجمالي الفحوصات</div><div class="value" id="m-total">-</div></div>
      </section>

      <section class="grid layout">
        <div class="grid">
          <div class="panel">
            <h2>رادار الفرص</h2>
            <div id="radar" class="status">جاري تشغيل الرادار...</div>
          </div>
          <div class="panel">
            <div class="row-top">
              <h2>الشارت الذكي</h2>
              <span class="muted small" id="chart-status">جاهز</span>
            </div>
            <div class="chart-tools">
              <select id="symbol-select"></select>
              <div class="seg" id="intervals">
                <button data-i="15m">15m</button>
                <button data-i="1h">1h</button>
                <button data-i="4h">4h</button>
                <button data-i="1d" class="active">1d</button>
              </div>
            </div>
            <div id="chart"></div>
          </div>
        </div>

        <div class="grid">
          <div class="panel">
            <h2>حالة الأسواق</h2>
            <div class="health">
              <div><div class="muted small">السعودي</div><strong id="s-saudi">-</strong></div>
              <div><div class="muted small">الأمريكي</div><strong id="s-us">-</strong></div>
              <div><div class="muted small">الكريبتو</div><strong id="s-crypto">-</strong></div>
            </div>
          </div>
          <div class="panel">
            <h2>آخر نشاط</h2>
            <div id="last-scans" class="status">لا توجد بيانات بعد</div>
          </div>
          <div class="panel">
            <h2>كل الرموز</h2>
            <div class="symbol-tools">
              <input id="symbol-search" type="search" placeholder="ابحث باسم الشركة أو الرمز" autocomplete="off" />
              <div class="market-tabs" id="market-tabs">
                <button class="active" data-market="ALL">الكل</button>
                <button data-market="SAUDI">السعودي</button>
                <button data-market="US">الأمريكي</button>
                <button data-market="CRYPTO">الكريبتو</button>
              </div>
            </div>
            <div id="symbols" class="status">جاري التحميل...</div>
          </div>
        </div>
      </section>
    </main>
  </div>

  <script>
    const TG_ID = "__TG_ID__";
    const TOKEN = "__TOKEN__";
    const root = `/api/dashboard/${TG_ID}/${TOKEN}`;
    let currentSymbol = { symbol: "BTCUSDT", market: "CRYPTO" };
    let currentInterval = "1d";
    let selectedMarket = "ALL";
    let searchTimer;
    let chart, candleSeries, volumeSeries;

    const fmt = (n, d = 2) => Number(n || 0).toLocaleString("ar-SA", { maximumFractionDigits: d });
    const marketName = (m) => ({SAUDI: "السعودي", US: "الأمريكي", CRYPTO: "الكريبتو"}[m] || m);
    const statusText = (v) => v === "open" ? "مفتوح" : "مغلق";

    async function getJson(url) {
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) throw new Error(await res.text());
      return res.json();
    }

    function initChart() {
      if (!window.LightweightCharts) {
        document.getElementById("chart").innerHTML = "<div class='status'>تعذر تحميل مكتبة الشارت.</div>";
        return;
      }
      chart = LightweightCharts.createChart(document.getElementById("chart"), {
        layout: { background: { color: "#171c23" }, textColor: "#96a2b4" },
        grid: { vertLines: { color: "#242d38" }, horzLines: { color: "#242d38" } },
        rightPriceScale: { borderColor: "#2b3441" },
        timeScale: { borderColor: "#2b3441", timeVisible: true },
      });
      candleSeries = chart.addCandlestickSeries({
        upColor: "#39d98a", downColor: "#ff6b6b", borderVisible: false,
        wickUpColor: "#39d98a", wickDownColor: "#ff6b6b",
      });
      volumeSeries = chart.addHistogramSeries({
        color: "#27d3b2", priceFormat: { type: "volume" }, priceScaleId: "",
        scaleMargins: { top: 0.82, bottom: 0 },
      });
      window.addEventListener("resize", () => chart.applyOptions({ width: document.getElementById("chart").clientWidth }));
    }

    function setChartOptions(symbols) {
      const select = document.getElementById("symbol-select");
      if (!symbols.length) return;
      select.innerHTML = symbols.slice(0, 120).map((s, idx) => `<option value="${idx}">${s.name_ar || s.name_en || s.note || s.symbol} | ${s.symbol}</option>`).join("");
      select.onchange = () => {
        currentSymbol = symbols[Number(select.value)];
        loadChart();
      };
      currentSymbol = symbols[0];
    }

    async function loadSummary() {
      const data = await getJson(`${root}/summary`);
      document.getElementById("welcome").textContent = `أهلاً ${data.user.name} | ${data.user.plan.toUpperCase()} | آخر تحديث ${data.server_time}`;
      document.getElementById("m-watch").textContent = data.cards.watchlist;
      document.getElementById("m-alerts").textContent = data.cards.alerts;
      document.getElementById("m-scans").textContent = data.cards.scans_today;
      document.getElementById("m-total").textContent = data.cards.total_scans;
      document.getElementById("s-saudi").textContent = statusText(data.markets.saudi);
      document.getElementById("s-us").textContent = statusText(data.markets.us);
      document.getElementById("s-crypto").textContent = statusText(data.markets.crypto);

      document.getElementById("last-scans").innerHTML = data.last_scans.length ? data.last_scans.map(s =>
        `<div class="scan-row"><div class="row-top"><span class="name">${s.symbol}</span><span class="score">${fmt(s.score, 0)}/100</span></div><span class="muted">${s.signal || marketName(s.market)}</span></div>`
      ).join("") : "لا توجد فحوصات حديثة";
      setChartOptions(data.symbols);
      await loadSymbols();
      loadChart();
    }

    async function loadRadar() {
      const box = document.getElementById("radar");
      try {
        const data = await getJson(`${root}/radar`);
        box.innerHTML = data.items.map(item => {
          const cls = item.change >= 0 ? "up" : "down";
          return `<div class="market-row">
            <div class="row-top"><span class="name">${item.name || item.symbol}</span><span class="score">${item.score}/100</span></div>
            <div class="row-top"><span class="muted">${item.symbol} | ${marketName(item.market)}</span><span class="${cls}">${fmt(item.change)}%</span></div>
            <div class="muted small">ثقة ${item.confidence}/100 | مخاطرة ${item.risk} | دعم ${fmt(item.support, 4)} | مقاومة ${fmt(item.resistance, 4)}</div>
          </div>`;
        }).join("");
      } catch (err) {
        box.textContent = "تعذر تحميل رادار الفرص حالياً";
      }
    }

    async function loadChart() {
      if (!chart) return;
      document.getElementById("chart-status").textContent = "جاري التحميل...";
      try {
        const data = await getJson(`${root}/chart?symbol=${encodeURIComponent(currentSymbol.symbol)}&market=${encodeURIComponent(currentSymbol.market)}&interval=${currentInterval}`);
        candleSeries.setData(data.data.map(x => ({ time: x.time, open: x.open, high: x.high, low: x.low, close: x.close })));
        volumeSeries.setData(data.data.map(x => ({ time: x.time, value: x.volume, color: x.close >= x.open ? "rgba(57,217,138,.35)" : "rgba(255,107,107,.35)" })));
        chart.timeScale().fitContent();
        document.getElementById("chart-status").textContent = `${data.symbol} | ${data.interval}`;
      } catch (err) {
        document.getElementById("chart-status").textContent = "تعذر تحميل الشارت";
      }
    }

    async function loadSymbols() {
      const q = document.getElementById("symbol-search").value.trim();
      const box = document.getElementById("symbols");
      box.textContent = "جاري تحميل الرموز...";
      try {
        const data = await getJson(`${root}/symbols?market=${encodeURIComponent(selectedMarket)}&q=${encodeURIComponent(q)}&limit=500`);
        if (!data.items.length) {
          box.textContent = "لا توجد رموز مطابقة";
          return;
        }
        setChartOptions(data.items);
        box.innerHTML = data.items.map((s, idx) =>
          `<div class="symbol-row" data-idx="${idx}">
            <div class="row-top"><span class="name">${s.name_ar || s.name_en || s.symbol}</span><span class="muted">${marketName(s.market)}</span></div>
            <div class="row-top"><span class="muted">${s.symbol}</span><span class="muted small">${s.sector || ""}</span></div>
          </div>`
        ).join("");
        [...box.querySelectorAll(".symbol-row")].forEach((row) => {
          row.addEventListener("click", () => {
            currentSymbol = data.items[Number(row.dataset.idx)];
            document.getElementById("chart-status").textContent = `${currentSymbol.symbol} | ${marketName(currentSymbol.market)}`;
            loadChart();
          });
        });
      } catch (err) {
        box.textContent = "تعذر تحميل الرموز حالياً";
      }
    }

    document.getElementById("intervals").addEventListener("click", (event) => {
      const btn = event.target.closest("button");
      if (!btn) return;
      [...document.querySelectorAll("#intervals button")].forEach(b => b.classList.toggle("active", b === btn));
      currentInterval = btn.dataset.i;
      loadChart();
    });

    document.getElementById("market-tabs").addEventListener("click", (event) => {
      const btn = event.target.closest("button");
      if (!btn) return;
      selectedMarket = btn.dataset.market;
      [...document.querySelectorAll("#market-tabs button")].forEach(b => b.classList.toggle("active", b === btn));
      loadSymbols();
    });

    document.getElementById("symbol-search").addEventListener("input", () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(loadSymbols, 250);
    });

    initChart();
    loadSummary().catch(() => document.getElementById("welcome").textContent = "تعذر تحميل بيانات الحساب");
    loadRadar();
  </script>
</body>
</html>
"""
