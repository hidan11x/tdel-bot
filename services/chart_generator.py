import os
from typing import Optional

import pandas as pd
import mplfinance as mpf
import matplotlib
matplotlib.use("Agg")

from services.market_data import get_ohlcv
from services.indicators import calculate_ema_series, find_support_resistance


CHART_DIR = os.path.join("data", "charts")


def _ensure_chart_dir():
    os.makedirs(CHART_DIR, exist_ok=True)


def generate_chart(symbol: str, market: str, timeframe: str = "1d", name: str = None) -> Optional[str]:
    try:
        _ensure_chart_dir()
        ohlcv = get_ohlcv(symbol, market, timeframe, outputsize=200)
        if not ohlcv or len(ohlcv) < 30:
            return None

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

        closes = df["Close"].tolist()

        ema20 = calculate_ema_series(closes, 20)
        ema50 = calculate_ema_series(closes, 50)
        ema200 = calculate_ema_series(closes, 200)

        df["EMA20"] = [v if v is not None else float("nan") for v in ema20]
        df["EMA50"] = [v if v is not None else float("nan") for v in ema50]
        df["EMA200"] = [v if v is not None else float("nan") for v in ema200]

        support, resistance = find_support_resistance(closes, lookback=20)

        apds = []

        if ema20[-1] is not None:
            apds.append(mpf.make_addplot(df["EMA20"], color="#E8A838", width=0.8, label="EMA 20"))
        if ema50[-1] is not None:
            apds.append(mpf.make_addplot(df["EMA50"], color="#E84A5F", width=0.8, label="EMA 50"))
        if ema200[-1] is not None:
            apds.append(mpf.make_addplot(df["EMA200"], color="#A855F7", width=0.8, label="EMA 200"))

        hlines = []
        if support is not None:
            hlines.append(support)
        if resistance is not None:
            hlines.append(resistance)

        mc = mpf.make_marketcolors(
            up="#26a69a",
            down="#ef5350",
            edge="inherit",
            wick="inherit",
            volume="inherit",
        )
        s = mpf.make_mpf_style(
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
            },
        )

        filename = f"{symbol}_{timeframe}.png".replace("/", "_").replace("\\", "_")
        filepath = os.path.join(CHART_DIR, filename)

        fig, axes = mpf.plot(
            df,
            type="candle",
            style=s,
            volume=True,
            addplot=apds,
            hlines=dict(hlines=hlines, colors=["#4fc3f7"] * len(hlines), linestyle="--", linewidths=0.8),
            savefig=filepath,
            returnfig=True,
            figsize=(12, 7),
            tight_layout=True,
            ylabel="",
            ylabel_lower="",
        )

        if support is not None:
            axes[0].text(
                df.index[-1], support,
                f"  S {support:.4f}",
                color="#4fc3f7", fontsize=8, va="top",
            )
        if resistance is not None:
            axes[0].text(
                df.index[-1], resistance,
                f"  R {resistance:.4f}",
                color="#4fc3f7", fontsize=8, va="bottom",
            )

        market_name = {"SAUDI": "السعودي", "US": "الأمريكي", "CRYPTO": "الرقمية"}.get(market.upper(), market)
        tf_name = {"1d": "يومي", "1h": "ساعي", "15m": "15 دقيقة", "4h": "4 ساعات", "1w": "أسبوعي"}.get(timeframe, timeframe)
        display_name = name if name else symbol
        title_text = f"{display_name} — {symbol}"
        subtitle_text = f"{market_name} | {tf_name}"

        axes[0].set_title(title_text, color="#ffffff", fontsize=12)
        axes[0].text(0.5, -0.12, subtitle_text, transform=axes[0].transAxes,
                     color="#999999", fontsize=9, ha="center", va="top")

        fig.savefig(filepath, bbox_inches="tight", dpi=100)
        import matplotlib.pyplot as plt
        plt.close(fig)

        return filepath
    except Exception as e:
        from loguru import logger
        logger.exception("Chart generation failed for {} {}: {}", symbol, market, e)
        return None
