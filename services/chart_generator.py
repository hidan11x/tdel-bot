import os
import io
from typing import Optional, Tuple

import pandas as pd
import numpy as np
import mplfinance as mpf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

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

        apds = []

        if not df["EMA20"].isna().all():
            apds.append(mpf.make_addplot(df["EMA20"], color="#E8A838", width=1.0))
        if not df["EMA50"].isna().all():
            apds.append(mpf.make_addplot(df["EMA50"], color="#E84A5F", width=1.0))
        if not df["EMA200"].isna().all():
            apds.append(mpf.make_addplot(df["EMA200"], color="#A855F7", width=1.0))

        hlines = []
        if support is not None and support > 0:
            hlines.append(support)
        if resistance is not None and resistance > 0:
            hlines.append(resistance)

        mc = mpf.make_marketcolors(
            up="#26a69a",
            down="#ef5350",
            edge="inherit",
            wick="inherit",
            volume="inherit",
        )

        style = mpf.make_mpf_style(
            base_mpf_style="nightclouds",
            marketcolors=mc,
            rc={
                "font.size": 9,
                "axes.labelsize": 9,
                "axes.labelcolor": "#cccccc",
                "xtick.color": "#999999",
                "ytick.color": "#999999",
                "axes.edgecolor": "#555555",
                "figure.facecolor": "#1a1a2e",
                "axes.facecolor": "#16213e",
                "font.family": "DejaVu Sans",
            },
        )

        title_text = f"{name} - {symbol}" if name else symbol

        buf = io.BytesIO()

        kwargs = dict(
            type="candle",
            style=style,
            volume=True,
            figsize=(12, 7),
            tight_layout=True,
            ylabel="",
            ylabel_lower="",
            returnfig=True,
            datetime_format="%Y-%m-%d",
        )

        if apds:
            kwargs["addplot"] = apds

        if hlines:
            kwargs["hlines"] = dict(
                hlines=hlines,
                colors=["#4fc3f7"] * len(hlines),
                linestyle="--",
                linewidths=0.8,
            )

        try:
            fig, axes = mpf.plot(df, **kwargs)
        except Exception as e:
            logger.warning("mplfinance with addplot failed: {}, trying simple...", e)
            kwargs.pop("addplot", None)
            kwargs.pop("hlines", None)
            fig, axes = mpf.plot(df, **kwargs)

        axes[0].set_title(title_text, color="#ffffff", fontsize=12, fontweight="bold")

        if support is not None and support > 0:
            axes[0].text(
                0.99, support, f"  S: {support:.4f}",
                color="#4fc3f7", fontsize=8, va="center", ha="right",
                transform=axes[0].get_yaxis_transform(),
            )
        if resistance is not None and resistance > 0:
            axes[0].text(
                0.99, resistance, f"  R: {resistance:.4f}",
                color="#4fc3f7", fontsize=8, va="center", ha="right",
                transform=axes[0].get_yaxis_transform(),
            )

        fig.savefig(buf, format="png", dpi=100, bbox_inches="tight",
                     facecolor="#1a1a2e", edgecolor="none")
        plt.close(fig)

        buf.seek(0)

        filename = f"{symbol}_{timeframe}.png".replace("/", "_").replace("\\", "_")
        filepath = os.path.join(CHART_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(buf.getvalue())
        buf.seek(0)

        chart_name = name if name else symbol
        caption = f"{chart_name} - {symbol}"

        return (buf.getvalue(), caption)

    except Exception as e:
        logger.exception("Chart generation failed for {} {}: {}", symbol, market, e)
        return None
