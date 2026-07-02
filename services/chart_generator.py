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
from services.scoring import calculate_score, get_risk_level


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


def _rtl(text: str) -> str:
    return str(text)


def _score_label(score: float) -> str:
    if score >= 80:
        return "Strong"
    if score >= 65:
        return "Good"
    if score >= 50:
        return "Medium"
    return "Weak"


def _trend_ar(trend: str) -> str:
    return {
        "uptrend": "Up",
        "downtrend": "Down",
        "sideways": "Sideways",
    }.get(str(trend).lower(), "Sideways")


def _risk_ar(risk: str) -> str:
    if not risk:
        return "Medium"
    text = str(risk)
    if "low" in text.lower() or "منخفض" in text:
        return "Low"
    if "high" in text.lower() or "مرتفع" in text or "عالي" in text:
        return "High"
    return "Medium"


def _add_chip(ax, x: float, y: float, label: str, value: str, color: str) -> None:
    ax.text(
        x,
        y,
        _rtl(f"{label}\n{value}"),
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=8.5,
        color="#F4F7FA",
        fontweight="bold",
        linespacing=1.35,
        bbox=dict(
            boxstyle="round,pad=0.55,rounding_size=0.22",
            facecolor="#111827",
            edgecolor=color,
            linewidth=1.1,
            alpha=0.96,
        ),
        zorder=10,
    )


def _add_fig_chip(fig, x: float, y: float, label: str, value: str, color: str) -> None:
    fig.text(
        x,
        y,
        f"{label}\n{value}",
        ha="center",
        va="center",
        fontsize=8.2,
        color="#F4F7FA",
        fontweight="bold",
        linespacing=1.25,
        bbox=dict(
            boxstyle="round,pad=0.45,rounding_size=0.16",
            facecolor="#111827",
            edgecolor=color,
            linewidth=1.05,
            alpha=0.96,
        ),
        zorder=20,
    )


def _safe_last(series) -> Optional[float]:
    try:
        value = series.iloc[-1]
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


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

        raw_df = pd.DataFrame(ohlcv)
        try:
            from services.indicators import calculate_all

            indicators = calculate_all(raw_df.copy())
        except Exception:
            indicators = {}
        indicators["current_price"] = current_price
        indicators["trend"] = indicators.get("trend") or "sideways"
        score_obj = calculate_score(indicators)
        score_value = float(score_obj.overall)
        risk_label = _risk_ar(get_risk_level(score_obj.risk_score))

        df = raw_df.copy()
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

        try:
            import pandas_ta as pta
            bb = pta.bbands(pd.Series(closes), length=20, std=2)
            if bb is not None and not bb.isna().all().all():
                bb_cols = list(bb.columns)
                if len(bb_cols) >= 3:
                    df["BB_Upper"] = bb[bb_cols[0]].values[:len(df)]
                    df["BB_Middle"] = bb[bb_cols[1]].values[:len(df)]
                    df["BB_Lower"] = bb[bb_cols[2]].values[:len(df)]
                else:
                    df["BB_Upper"] = np.nan
                    df["BB_Middle"] = np.nan
                    df["BB_Lower"] = np.nan
            else:
                df["BB_Upper"] = np.nan
                df["BB_Middle"] = np.nan
                df["BB_Lower"] = np.nan
        except Exception:
            df["BB_Upper"] = np.nan
            df["BB_Middle"] = np.nan
            df["BB_Lower"] = np.nan

        try:
            import pandas_ta as pta
            rsi = pta.rsi(pd.Series(closes), length=14)
            df["RSI"] = rsi.values[:len(df)] if rsi is not None else np.nan
        except Exception:
            df["RSI"] = np.nan

        support, resistance = find_support_resistance(closes, lookback=20)

        vol_series = df["Volume"].dropna()
        avg_vol_20 = vol_series.rolling(20).mean().iloc[-1] if len(vol_series) >= 20 else vol_series.mean()
        current_vol = vol_series.iloc[-1] if len(vol_series) > 0 else 0
        vol_ratio = current_vol / avg_vol_20 if avg_vol_20 and avg_vol_20 > 0 else 0
        vol_status = "High" if vol_ratio > 1.5 else "Normal"

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

        if not df["BB_Upper"].isna().all():
            apds.append(mpf.make_addplot(df["BB_Upper"], color="#42A5F5", width=0.7, alpha=0.5))
        if not df["BB_Lower"].isna().all():
            apds.append(mpf.make_addplot(df["BB_Lower"], color="#42A5F5", width=0.7, alpha=0.5))

        if not df["RSI"].isna().all():
            apds.append(mpf.make_addplot(df["RSI"], panel=2, color="#FFA726", width=1.2, ylabel="RSI"))
            apds.append(mpf.make_addplot([70] * len(df), panel=2, color="#EF5350", width=0.7, linestyle="--"))
            apds.append(mpf.make_addplot([30] * len(df), panel=2, color="#66BB6A", width=0.7, linestyle="--"))

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
                "axes.labelcolor": "#B8C0CC",
                "xtick.color": "#7D8794",
                "ytick.color": "#AAB4C1",
                "axes.edgecolor": "#263241",
                "grid.color": "#263241",
                "grid.alpha": 0.35,
                "figure.facecolor": "#070B11",
                "axes.facecolor": "#0D141F",
                "font.family": "DejaVu Sans",
            },
        )

        display_name = name if name else symbol
        change_arrow = "▲" if change_pct >= 0 else "▼"
        change_color = "#26a69a" if change_pct >= 0 else "#ef5350"
        trend_text = _trend_ar(indicators.get("trend"))
        title_text = f"{symbol} | {market} | {timeframe.upper()}"

        kwargs = dict(
            type="candle",
            style=style,
            volume=True,
            figsize=(13.5, 8.8),
            tight_layout=True,
            ylabel="",
            ylabel_lower="",
            returnfig=True,
            datetime_format="%Y-%m-%d",
            scale_padding={"left": 0.08, "right": 1.0, "top": 1.9, "bottom": 0.35},
        )

        if not df["RSI"].isna().all():
            kwargs["panel_ratios"] = (5, 1.4, 1.2)

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

        price_ax = axes[0]
        volume_ax = axes[2] if len(axes) > 2 else None
        rsi_ax = axes[4] if len(axes) > 4 else None
        fig.subplots_adjust(top=0.875, bottom=0.105, left=0.055, right=0.985, hspace=0.05)

        fig.text(
            0.055,
            0.965,
            title_text,
            color="#F8FAFC",
            fontsize=14,
            fontweight="bold",
            ha="left",
            va="center",
        )
        fig.text(
            0.965,
            0.965,
            f"{change_arrow} {_fmt_change(change_pct)}  {_fmt_price(current_price)}",
            color=change_color,
            fontsize=12.5,
            fontweight="bold",
            ha="right",
            va="center",
        )
        price_ax.set_title("")

        score_color = "#22C55E" if score_value >= 70 else ("#FACC15" if score_value >= 50 else "#EF4444")
        _add_fig_chip(fig, 0.265, 0.965, "Price", _fmt_price(current_price), "#38BDF8")
        _add_fig_chip(fig, 0.385, 0.965, "Change", _fmt_change(change_pct), change_color)
        _add_fig_chip(fig, 0.520, 0.965, "Score", f"{score_value:.0f}/100 {_score_label(score_value)}", score_color)
        _add_fig_chip(fig, 0.650, 0.965, "Risk", risk_label, "#F59E0B")
        _add_fig_chip(fig, 0.780, 0.965, "Trend", trend_text, "#A78BFA")

        if support is not None and support > 0 and current_price > 0:
            s_dist = ((current_price - support) / current_price) * 100
            s_text = f"Support {_fmt_price(support)} ({s_dist:+.1f}%)"
            price_ax.text(
                0.99, 0.02, _rtl(s_text),
                color="#66BB6A", fontsize=9, fontweight="bold",
                transform=price_ax.transAxes, ha="right", va="bottom",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="#0d1117", edgecolor="#66BB6A", alpha=0.85),
            )

        if resistance is not None and resistance > 0 and current_price > 0:
            r_dist = ((resistance - current_price) / current_price) * 100
            r_text = f"Resistance {_fmt_price(resistance)} ({r_dist:+.1f}%)"
            price_ax.text(
                0.99, 0.08, _rtl(r_text),
                color="#EF5350", fontsize=9, fontweight="bold",
                transform=price_ax.transAxes, ha="right", va="bottom",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="#0d1117", edgecolor="#EF5350", alpha=0.85),
            )

        try:
            last_x = len(df) - 1
            last_low = float(df["Low"].iloc[-1])
            last_high = float(df["High"].iloc[-1])
            price_range = max(float(df["High"].max() - df["Low"].min()), current_price * 0.02)
            trend = str(indicators.get("trend") or "sideways").lower()
            if trend == "uptrend" and score_value >= 55:
                marker_text = "Watch Buy"
                marker_color = "#22C55E"
                y_point = last_low
                y_text = last_low - price_range * 0.11
                va = "top"
            elif trend == "downtrend" and score_value < 60:
                marker_text = "Watch Sell"
                marker_color = "#EF4444"
                y_point = last_high
                y_text = last_high + price_range * 0.11
                va = "bottom"
            else:
                marker_text = "Watch"
                marker_color = "#FACC15"
                y_point = current_price
                y_text = current_price + price_range * 0.10
                va = "bottom"

            price_ax.annotate(
                _rtl(marker_text),
                xy=(last_x, y_point),
                xytext=(max(0, last_x - 18), y_text),
                color="#0B1220",
                fontsize=9,
                fontweight="bold",
                ha="center",
                va=va,
                arrowprops=dict(arrowstyle="-|>", color=marker_color, lw=1.5, shrinkA=4, shrinkB=4),
                bbox=dict(boxstyle="round,pad=0.35", facecolor=marker_color, edgecolor=marker_color, alpha=0.96),
                zorder=12,
            )
        except Exception:
            pass

        ema20_val = ema20[-1] if ema20 and ema20[-1] is not None else None
        ema50_val = ema50[-1] if ema50 and ema50[-1] is not None else None

        bb_upper_val = df["BB_Upper"].iloc[-1] if not df["BB_Upper"].isna().all() else None
        bb_lower_val = df["BB_Lower"].iloc[-1] if not df["BB_Lower"].isna().all() else None

        summary_lines = [
            f"EMA20 {_fmt_price(ema20_val)}",
            f"EMA50 {_fmt_price(ema50_val)}",
            f"Support {_fmt_price(support)}",
            f"Resistance {_fmt_price(resistance)}",
            f"Volume {vol_status} {vol_ratio:.1f}x",
        ]

        if bb_upper_val and not np.isnan(bb_upper_val):
            summary_lines.append(f"BB Upper {_fmt_price(float(bb_upper_val))}")
        if bb_lower_val and not np.isnan(bb_lower_val):
            summary_lines.append(f"BB Lower {_fmt_price(float(bb_lower_val))}")

        summary_text = "  |  ".join(summary_lines[:5])
        price_ax.text(
            0.01, 0.985, _rtl(summary_text),
            color="#CBD5E1", fontsize=8.5,
            transform=price_ax.transAxes, ha="left", va="top",
            bbox=dict(boxstyle="round,pad=0.42", facecolor="#0B1220", edgecolor="#263241", alpha=0.92),
        )

        price_ax.legend(
            ["EMA 20", "EMA 50"] + (["EMA 200"] if not df["EMA200"].isna().all() else []),
            loc="upper left",
            fontsize=8,
            bbox_to_anchor=(0.01, 0.91),
            facecolor="#111827",
            edgecolor="#263241",
            labelcolor=["#FFD54F", "#42A5F5"] + (["#CE93D8"] if not df["EMA200"].isna().all() else []),
            framealpha=0.85,
        )

        try:
            if volume_ax is not None:
                for i, bar in enumerate(volume_ax.patches):
                    if i < len(vol_colors):
                        bar.set_color(vol_colors[i])
        except Exception:
            pass

        if volume_ax is not None:
            volume_ax.set_ylabel("Volume", color="#94A3B8", fontsize=8)
            if avg_vol_20 and avg_vol_20 > 0:
                volume_ax.axhline(y=avg_vol_20, color="#94A3B8", linestyle="--", linewidth=0.8, alpha=0.55)
                volume_ax.text(
                    0.99, avg_vol_20, f"Avg {avg_vol_20/1e6:.1f}M",
                    color="#94A3B8", fontsize=7, va="bottom", ha="right",
                    transform=volume_ax.get_yaxis_transform(),
                )

        if rsi_ax is not None:
            rsi_value = _safe_last(df["RSI"])
            rsi_ax.set_ylabel("RSI", color="#F59E0B", fontsize=8)
            rsi_ax.fill_between(range(len(df)), 30, 70, color="#1E293B", alpha=0.28)
            if rsi_value is not None:
                rsi_color = "#EF4444" if rsi_value >= 70 else ("#22C55E" if rsi_value <= 30 else "#F59E0B")
                rsi_ax.text(
                    0.99, 0.75, f"RSI {rsi_value:.1f}",
                    color=rsi_color,
                    fontsize=8,
                    fontweight="bold",
                    transform=rsi_ax.transAxes,
                    ha="right",
                    va="center",
                    bbox=dict(boxstyle="round,pad=0.25", facecolor="#0B1220", edgecolor=rsi_color, alpha=0.9),
                )

        fig.text(
            0.985,
            0.012,
            "Automated educational reading, not financial advice",
            ha="right",
            va="bottom",
            color="#64748B",
            fontsize=8,
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

        caption = (
            f"{display_name} - {symbol}\n"
            f"السعر: {_fmt_price(current_price)} | التغير: {_fmt_change(change_pct)}\n"
            f"السكور: {score_value:.0f}/100 | المخاطرة: {risk_label}"
        )
        return (chart_bytes, caption)

    except Exception as e:
        logger.exception("Chart generation failed for {} {}: {}", symbol, market, e)
        return None
