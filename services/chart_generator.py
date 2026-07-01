import os
from typing import Optional

import pandas as pd
import mplfinance as mpf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from loguru import logger
from services.market_data import get_ohlcv
from services.indicators import calculate_ema_series, find_support_resistance


CHART_DIR = os.path.join("data", "charts")


def _ensure_chart_dir():
    os.makedirs(CHART_DIR, exist_ok=True)


def _generate_simple_chart(symbol: str, market: str, timeframe: str, name: str, ohlcv: list, closes: list) -> Optional[str]:
    try:
        df = pd.DataFrame(ohlcv)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), gridspec_kw={"height_ratios": [3, 1]})
        fig.patch.set_facecolor("#1a1a2e")
        ax1.set_facecolor("#16213e")
        ax2.set_facecolor("#16213e")

        ax1.plot(df["timestamp"], df["close"], color="#26a69a", linewidth=1.5, label="Price")

        ema20 = calculate_ema_series(closes, 20)
        ema50 = calculate_ema_series(closes, 50)
        df["EMA20"] = [v if v is not None else float("nan") for v in ema20]
        df["EMA50"] = [v if v is not None else float("nan") for v in ema50]

        ax1.plot(df["timestamp"], df["EMA20"], color="#E8A838", linewidth=0.8, label="EMA 20")
        ax1.plot(df["timestamp"], df["EMA50"], color="#E84A5F", linewidth=0.8, label="EMA 50")

        support, resistance = find_support_resistance(closes, lookback=20)
        if support:
            ax1.axhline(y=support, color="#4fc3f7", linestyle="--", linewidth=0.8, alpha=0.7)
        if resistance:
            ax1.axhline(y=resistance, color="#ef5350", linestyle="--", linewidth=0.8, alpha=0.7)

        ax1.tick_params(colors="#cccccc", labelsize=8)
        ax1.spines["bottom"].set_color("#555555")
        ax1.spines["top"].set_visible(False)
        ax1.spines["left"].set_color("#555555")
        ax1.spines["right"].set_visible(False)

        title_text = f"{name} - {symbol}" if name else symbol
        ax1.set_title(title_text, color="#ffffff", fontsize=12)
        ax1.legend(loc="upper left", fontsize=8, facecolor="#16213e", edgecolor="#555555", labelcolor="#cccccc")

        ax2.bar(df["timestamp"], df["volume"], color="#26a69a", alpha=0.5)
        ax2.tick_params(colors="#cccccc", labelsize=7)
        ax2.spines["bottom"].set_color("#555555")
        ax2.spines["top"].set_visible(False)
        ax2.spines["left"].set_color("#555555")
        ax2.spines["right"].set_visible(False)
        ax2.set_ylabel("Volume", color="#999999", fontsize=8)

        plt.tight_layout()

        filename = f"{symbol}_{timeframe}.png".replace("/", "_").replace("\\", "_")
        filepath = os.path.join(CHART_DIR, filename)
        fig.savefig(filepath, dpi=100, facecolor="#1a1a2e")
        plt.close(fig)

        return filepath
    except Exception as e:
        logger.exception("Simple chart failed: {}", e)
        return None


def generate_chart(symbol: str, market: str, timeframe: str = "1d", name: str = None) -> Optional[str]:
    try:
        _ensure_chart_dir()
        ohlcv = get_ohlcv(symbol, market, timeframe, outputsize=200)
        if not ohlcv or len(ohlcv) < 30:
            logger.warning("Not enough data for chart: {} {} {}", symbol, market, timeframe)
            return None

        closes = [d["close"] for d in ohlcv]

        try:
            return _generate_mpf_chart(symbol, market, timeframe, name, ohlcv, closes)
        except Exception as e:
            logger.warning("mplfinance failed, trying simple chart: {}", e)
            return _generate_simple_chart(symbol, market, timeframe, name or symbol, ohlcv, closes)

    except Exception as e:
        from loguru import logger
        logger.exception("Chart generation failed for {} {}: {}", symbol, market, e)
        return None


def _generate_mpf_chart(symbol: str, market: str, timeframe: str, name: str, ohlcv: list, closes: list) -> Optional[str]:
    try:
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

        market_name = {"SAUDI": "Saudi", "US": "US", "CRYPTO": "Crypto"}.get(market.upper(), market)
        tf_name = {"1d": "Daily", "1h": "1H", "15m": "15min", "4h": "4H", "1w": "Weekly"}.get(timeframe, timeframe)
        display_name = name if name else symbol
        title_text = f"{display_name} - {symbol}"
        subtitle_text = f"{market_name} | {tf_name}"

        axes[0].set_title(title_text, color="#ffffff", fontsize=12)
        axes[0].text(0.5, -0.12, subtitle_text, transform=axes[0].transAxes,
                     color="#999999", fontsize=9, ha="center", va="top")

        fig.savefig(filepath, bbox_inches="tight", dpi=100)
        plt.close(fig)

        return filepath
    except Exception as e:
        logger.warning("mplfinance chart failed: {}", e)
        raise
