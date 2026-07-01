import os
import io
from typing import Optional, Tuple

import pandas as pd
import numpy as np
import mplfinance as mpf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

from loguru import logger
from services.market_data import get_ohlcv
from services.indicators import calculate_ema_series, find_support_resistance


CHART_DIR = os.path.join("data", "charts")


def _ensure_chart_dir():
    os.makedirs(CHART_DIR, exist_ok=True)


def _clean_ohlcv(ohlcv: list) -> list:
    cleaned = []
    for d in ohlcv:
        try:
            o = float(d.get("open", 0))
            h = float(d.get("high", 0))
            l = float(d.get("low", 0))
            c = float(d.get("close", 0))
            v = float(d.get("volume", 0))
            if h < l or h < o or h < c or l > o or l > c:
                h = max(o, h, c)
                l = min(o, l, c)
            if h <= 0 or l <= 0 or c <= 0:
                continue
            cleaned.append({
                "timestamp": int(d["timestamp"]),
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
            })
        except (ValueError, TypeError, KeyError):
            continue
    return cleaned


def _fmt_price(price: float) -> str:
    if price is None:
        return "N/A"
    if price >= 1000:
        return f"{price:,.2f}"
    elif price >= 1:
        return f"{price:.4f}"
    elif price >= 0.01:
        return f"{price:.6f}"
    return f"{price:.8f}"


def _fmt_change(change: float) -> str:
    if change is None:
        return "N/A"
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.2f}%"


def generate_chart(
    symbol: str,
    market: str,
    timeframe: str = "1d",
    name: str = None,
) -> Optional[Tuple[bytes, str]]:
    try:
        _ensure_chart_dir()

        ohlcv = get_ohlcv(symbol, market, timeframe, outputsize=200)
        if not ohlcv or len(ohlcv) < 30:
            logger.warning("Not enough OHLCV data for {} {} {}", symbol, market, timeframe)
            return None

        ohlcv = _clean_ohlcv(ohlcv)
        if len(ohlcv) < 30:
            logger.warning("Not enough valid OHLCV data after cleaning for {}", symbol)
            return None

        closes = [d["close"] for d in ohlcv]
        current_price = closes[-1]
        prev_close = closes[-2] if len(closes) >= 2 else closes[-1]
        change_pct = ((current_price - prev_close) / prev_close) * 100 if prev_close else 0.0
        change_val = current_price - prev_close

        df = pd.DataFrame(ohlcv)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
        df.set_index("timestamp", inplace=True)
        df.rename(columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }, inplace=True)

        for col in ["Open", "High", "Low", "Close", "Volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["Open", "High", "Low", "Close"])
        if len(df) < 30:
            return None

        ema20 = calculate_ema_series(closes, 20)
        ema50 = calculate_ema_series(closes, 50)

        df["EMA20"] = [v if v is not None else np.nan for v in ema20[:len(df)]]
        df["EMA50"] = [v if v is not None else np.nan for v in ema50[:len(df)]]

        if len(closes) >= 200:
            ema200 = calculate_ema_series(closes, 200)
            df["EMA200"] = [v if v is not None else np.nan for v in ema200[:len(df)]]
        else:
            df["EMA200"] = np.nan

        support, resistance = find_support_resistance(closes, lookback=20)

        vol_series = df["Volume"].dropna()
        avg_vol_20 = vol_series.rolling(20).mean().iloc[-1] if len(vol_series) >= 20 else vol_series.mean()
        current_vol = vol_series.iloc[-1] if len(vol_series) > 0 else 0
        vol_ratio = current_vol / avg_vol_20 if avg_vol_20 and avg_vol_20 > 0 else 0
        vol_status = "مرتفع" if vol_ratio > 1.5 else "طبيعي"

        vol_colors = []
        for i in range(len(df)):
            if df["Close"].iloc[i] >= df["Open"].iloc[i]:
                base_color = "#26a69a"
            else:
                base_color = "#ef5350"

            idx = vol_series.index.get_loc(df.index[i]) if df.index[i] in vol_series.index else None
            if idx is not None and idx < len(vol_series):
                rolling_avg = vol_series.rolling(20).mean().iloc[idx] if idx >= 19 else avg_vol_20
                if rolling_avg and rolling_avg > 0 and vol_series.iloc[idx] > rolling_avg * 1.5:
                    base_color = "#FFB74D" if base_color == "#26a69a" else "#FF7043"

            vol_colors.append(base_color)

        apds = []

        if not df["EMA20"].isna().all():
            apds.append(mpf.make_addplot(df["EMA20"], color="#FFD54F", width=2.0))
        if not df["EMA50"].isna().all():
            apds.append(mpf.make_addplot(df["EMA50"], color="#42A5F5", width=2.0))
        if not df["EMA200"].isna().all():
            apds.append(mpf.make_addplot(df["EMA200"], color="#CE93D8", width=1.5))

        hlines = []
        hlines_colors = []
        if support is not None and support > 0:
            hlines.append(support)
            hlines_colors.append("#66BB6A")
        if resistance is not None and resistance > 0:
            hlines.append(resistance)
            hlines_colors.append("#EF5350")

        mc = mpf.make_marketcolors(
            up="#26a69a",
            down="#ef5350",
            edge={"up": "#26a69a", "down": "#ef5350"},
            wick={"up": "#26a69a", "down": "#ef5350"},
            volume={"up": "#26a69a", "down": "#ef5350"},
        )

        style = mpf.make_mpf_style(
            base_mpf_style="nightclouds",
            marketcolors=mc,
            rc={
                "font.size": 9,
                "axes.labelsize": 9,
                "axes.labelcolor": "#cccccc",
                "xtick.color": "#888888",
                "ytick.color": "#aaaaaa",
                "axes.edgecolor": "#444444",
                "figure.facecolor": "#0d1117",
                "axes.facecolor": "#161b22",
                "font.family": "DejaVu Sans",
            },
        )

        display_name = name if name else symbol
        change_arrow = "▲" if change_pct >= 0 else "▼"
        change_color = "#26a69a" if change_pct >= 0 else "#ef5350"
        title_text = f"{display_name}  |  {_fmt_price(current_price)}\n{change_arrow} {_fmt_change(change_pct)}"

        kwargs = dict(
            type="candle",
            style=style,
            volume=True,
            figsize=(14, 8),
            tight_layout=True,
            ylabel="",
            ylabel_lower="",
            returnfig=True,
            datetime_format="%Y-%m-%d",
            scale_padding={"left": 0.1, "right": 1.0, "top": 1.5, "bottom": 0.3},
        )

        if apds:
            kwargs["addplot"] = apds

        if hlines:
            kwargs["hlines"] = dict(
                hlines=hlines,
                colors=hlines_colors,
                linestyle="--",
                linewidths=1.2,
            )

        try:
            fig, axes = mpf.plot(df, **kwargs)
        except Exception as e:
            logger.warning("mplfinance with addplot failed: {}, trying simple...", e)
            kwargs.pop("addplot", None)
            kwargs.pop("hlines", None)
            fig, axes = mpf.plot(df, **kwargs)

        axes[0].set_title(title_text, color="#ffffff", fontsize=13, fontweight="bold",
                          loc="left", pad=15)

        if support is not None and support > 0 and current_price > 0:
            s_dist = ((current_price - support) / current_price) * 100
            s_text = f"S: {_fmt_price(support)} ({s_dist:+.1f}%)"
            axes[0].text(
                0.99, 0.02, s_text,
                color="#66BB6A", fontsize=9, fontweight="bold",
                transform=axes[0].transAxes, ha="right", va="bottom",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="#0d1117", edgecolor="#66BB6A", alpha=0.85),
            )

        if resistance is not None and resistance > 0 and current_price > 0:
            r_dist = ((resistance - current_price) / current_price) * 100
            r_text = f"R: {_fmt_price(resistance)} ({r_dist:+.1f}%)"
            axes[0].text(
                0.99, 0.08, r_text,
                color="#EF5350", fontsize=9, fontweight="bold",
                transform=axes[0].transAxes, ha="right", va="bottom",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="#0d1117", edgecolor="#EF5350", alpha=0.85),
            )

        ema20_val = ema20[-1] if ema20 and ema20[-1] is not None else None
        ema50_val = ema50[-1] if ema50 and ema50[-1] is not None else None

        trend_label = "Up" if change_pct > 0.5 else ("Down" if change_pct < -0.5 else "Side")
        trend_color = "#26a69a" if trend_label == "Up" else ("#ef5350" if trend_label == "Down" else "#FFCA28")

        summary_lines = [
            f"Trend: {trend_label}",
            f"EMA20: {_fmt_price(ema20_val)}",
            f"EMA50: {_fmt_price(ema50_val)}",
            f"Support: {_fmt_price(support)}",
            f"Resist: {_fmt_price(resistance)}",
            f"Vol: {vol_status} ({vol_ratio:.1f}x)",
        ]

        summary_text = "\n".join(summary_lines)
        axes[0].text(
            0.01, 0.98, summary_text,
            color="#cccccc", fontsize=8, fontfamily="monospace",
            transform=axes[0].transAxes, ha="left", va="top",
            bbox=dict(boxstyle="round,pad=0.5", facecolor="#0d1117", edgecolor="#444444", alpha=0.9),
        )

        axes[0].legend(
            ["EMA 20", "EMA 50"] + (["EMA 200"] if not df["EMA200"].isna().all() else []),
            loc="upper left",
            fontsize=8,
            facecolor="#161b22",
            edgecolor="#444444",
            labelcolor=["#FFD54F", "#42A5F5"] + (["#CE93D8"] if not df["EMA200"].isna().all() else []),
            framealpha=0.85,
        )

        try:
            for i, bar in enumerate(axes[2].patches if len(axes) > 2 else []):
                if i < len(vol_colors):
                    bar.set_color(vol_colors[i])
        except Exception:
            pass

        if avg_vol_20 and avg_vol_20 > 0:
            axes[2].axhline(y=avg_vol_20, color="#888888", linestyle="--", linewidth=0.8, alpha=0.6)
            axes[2].text(
                0.99, avg_vol_20, f"Avg: {avg_vol_20/1e6:.1f}M",
                color="#888888", fontsize=7, va="bottom", ha="right",
                transform=axes[2].get_yaxis_transform(),
            )

        buf = io.BytesIO()
        fig.savefig(
            buf,
            format="png",
            dpi=150,
            bbox_inches="tight",
            pad_inches=0.15,
            facecolor="#0d1117",
            edgecolor="none",
        )
        plt.close(fig)

        buf.seek(0)
        chart_bytes = buf.getvalue()

        filename = f"{symbol}_{timeframe}.png".replace("/", "_").replace("\\", "_")
        filepath = os.path.join(CHART_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(chart_bytes)

        caption = f"{display_name} - {symbol}"
        return (chart_bytes, caption)

    except Exception as e:
        logger.exception("Chart generation failed for {} {}: {}", symbol, market, e)
        return None
