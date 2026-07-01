import os
import json
from typing import Optional

from loguru import logger
from services.market_data import get_ohlcv
from services.indicators import calculate_ema_series, find_support_resistance


CHART_DIR = os.path.join("data", "charts")


def _ensure_chart_dir():
    os.makedirs(CHART_DIR, exist_ok=True)


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<script src="https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ background: #1a1a2e; color: #fff; font-family: system-ui, -apple-system, sans-serif; }}
.header {{ padding: 15px 20px; background: #16213e; border-bottom: 1px solid #333; }}
.header h1 {{ font-size: 18px; color: #fff; }}
.header .info {{ font-size: 13px; color: #999; margin-top: 5px; }}
#chart {{ width: 100%; height: 400px; }}
#volume {{ width: 100%; height: 120px; }}
.footer {{ padding: 10px 20px; font-size: 11px; color: #666; text-align: center; }}
.levels {{ padding: 10px 20px; display: flex; gap: 20px; flex-wrap: wrap; }}
.level {{ padding: 5px 12px; border-radius: 6px; font-size: 12px; }}
.support {{ background: rgba(38,166,154,0.2); color: #26a69a; border: 1px solid #26a69a; }}
.resistance {{ background: rgba(239,83,80,0.2); color: #ef5350; border: 1px solid #ef5350; }}
.ema-badge {{ padding: 3px 8px; border-radius: 4px; font-size: 11px; margin-right: 8px; }}
</style>
</head>
<body>
<div class="header">
<h1>{name} ({symbol})</h1>
<div class="info">{market_label} | {tf_label} | آخر تحديث: {updated}</div>
<div style="margin-top:8px;">
<span class="ema-badge" style="background:#E8A838;color:#000;">EMA 20</span>
<span class="ema-badge" style="background:#E84A5F;color:#fff;">EMA 50</span>
<span class="ema-badge" style="background:#A855F7;color:#fff;">EMA 200</span>
</div>
</div>
<div class="levels">
{levels_html}
</div>
<div id="chart"></div>
<div id="volume"></div>
<div class="footer">
Powered by TradingView Lightweight Charts | هذا رسم بياني تعليمي وليس توصية مالية
</div>
<script>
const chartData = {chart_data};
const volumeData = {volume_data};
const emaData = {ema_data};

const chart = LightweightCharts.createChart(document.getElementById('chart'), {{
    layout: {{
        background: {{ color: '#1a1a2e' }},
        textColor: '#cccccc',
        fontSize: 11,
    }},
    grid: {{
        vertLines: {{ color: '#2a2a4e' }},
        horzLines: {{ color: '#2a2a4e' }},
    }},
    crosshair: {{
        mode: LightweightCharts.CrosshairMode.Normal,
    }},
    rightPriceScale: {{
        borderColor: '#555555',
    }},
    timeScale: {{
        borderColor: '#555555',
        timeVisible: true,
        secondsVisible: false,
    }},
}});

const volumeChart = LightweightCharts.createChart(document.getElementById('volume'), {{
    layout: {{
        background: {{ color: '#1a1a2e' }},
        textColor: '#999999',
        fontSize: 10,
    }},
    grid: {{
        vertLines: {{ color: '#2a2a4e' }},
        horzLines: {{ color: '#2a2a4e' }},
    }},
    rightPriceScale: {{
        borderColor: '#555555',
    }},
    timeScale: {{
        visible: false,
    }},
}});

const candleSeries = chart.addCandlestickSeries({{
    upColor: '#26a69a',
    downColor: '#ef5350',
    borderUpColor: '#26a69a',
    borderDownColor: '#ef5350',
    wickUpColor: '#26a69a',
    wickDownColor: '#ef5350',
}});
candleSeries.setData(chartData);

const volumeSeries = volumeChart.addHistogramSeries({{
    color: '#26a69a',
    priceFormat: {{ type: 'volume' }},
    priceScaleId: '',
}});
volumeSeries.priceScale().applyOptions({{
    scaleMargins: {{ top: 0.8, bottom: 0 }},
}});
volumeSeries.setData(volumeData);

if (emaData.ema20) {{
    const ema20Series = chart.addLineSeries({{ color: '#E8A838', lineWidth: 1, priceLineVisible: false, lastValueVisible: false }});
    ema20Series.setData(emaData.ema20);
}}
if (emaData.ema50) {{
    const ema50Series = chart.addLineSeries({{ color: '#E84A5F', lineWidth: 1, priceLineVisible: false, lastValueVisible: false }});
    ema50Series.setData(emaData.ema50);
}}
if (emaData.ema200) {{
    const ema200Series = chart.addLineSeries({{ color: '#A855F7', lineWidth: 1, priceLineVisible: false, lastValueVisible: false }});
    ema200Series.setData(emaData.ema200);
}}

chart.timeScale().fitContent();

chart.subscribeVisibleLogicalRangeChange(range => {{
    volumeChart.timeScale().setVisibleLogicalRange(range);
}});
volumeChart.subscribeVisibleLogicalRangeChange(range => {{
    chart.timeScale().setVisibleLogicalRange(range);
}});
</script>
</body>
</html>"""


def generate_chart_html(symbol: str, market: str, timeframe: str = "1d", name: str = None) -> Optional[str]:
    try:
        _ensure_chart_dir()
        ohlcv = get_ohlcv(symbol, market, timeframe, outputsize=200)
        if not ohlcv or len(ohlcv) < 30:
            return None

        closes = [d["close"] for d in ohlcv]

        from datetime import datetime, timezone
        def to_ts(t):
            dt = datetime.fromtimestamp(t, tz=timezone.utc)
            return dt.strftime("%Y-%m-%d")

        chart_data = []
        volume_data = []
        for d in ohlcv:
            ts = to_ts(d["timestamp"])
            chart_data.append({
                "time": ts,
                "open": round(d["open"], 6),
                "high": round(d["high"], 6),
                "low": round(d["low"], 6),
                "close": round(d["close"], 6),
            })
            volume_data.append({
                "time": ts,
                "value": d["volume"],
                "color": "#26a69a" if d["close"] >= d["open"] else "#ef5350",
            })

        ema20 = calculate_ema_series(closes, 20)
        ema50 = calculate_ema_series(closes, 50)
        ema200 = calculate_ema_series(closes, 200)

        ema_data = {}

        def build_ema(ema_list):
            data = []
            for i, v in enumerate(ema_list):
                if v is not None:
                    data.append({"time": to_ts(ohlcv[i]["timestamp"]), "value": round(v, 6)})
            return data if data else None

        ema_data["ema20"] = build_ema(ema20)
        ema_data["ema50"] = build_ema(ema50)
        ema_data["ema200"] = build_ema(ema200)

        support, resistance = find_support_resistance(closes, lookback=20)

        levels_html = ""
        if support:
            levels_html += f'<div class="level support">🟢 الدعم: {support:,.4f}</div>'
        if resistance:
            levels_html += f'<div class="level resistance">🔴 المقاومة: {resistance:,.4f}</div>'

        market_labels = {"SAUDI": "السوق السعودي", "US": "السوق الأمريكي", "CRYPTO": "العملات الرقمية"}
        tf_labels = {"1d": "يومي", "1h": "ساعي", "15m": "15 دقيقة", "4h": "4 ساعات", "1w": "أسبوعي"}

        html = HTML_TEMPLATE.format(
            title=f"{name or symbol} - {symbol}",
            name=name or symbol,
            symbol=symbol,
            market_label=market_labels.get(market.upper(), market),
            tf_label=tf_labels.get(timeframe, timeframe),
            updated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            levels_html=levels_html,
            chart_data=json.dumps(chart_data),
            volume_data=json.dumps(volume_data),
            ema_data=json.dumps(ema_data),
        )

        filename = f"{symbol}_{timeframe}.html".replace("/", "_").replace("\\", "_")
        filepath = os.path.join(CHART_DIR, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)

        return filepath

    except Exception as e:
        logger.exception("HTML chart generation failed for {} {}: {}", symbol, market, e)
        return None


def generate_chart(symbol: str, market: str, timeframe: str = "1d", name: str = None) -> Optional[str]:
    return generate_chart_html(symbol, market, timeframe, name)
