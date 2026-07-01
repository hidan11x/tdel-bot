from typing import List, Dict, Optional, Tuple

import pandas as pd
import pandas_ta as ta


def _to_series(closes: List[float], name: str = "close") -> pd.Series:
    return pd.Series(closes, name=name)


def calculate_all(df: pd.DataFrame) -> Dict[str, any]:
    result = {}
    closes = df["close"] if isinstance(df, pd.DataFrame) and "close" in df else df

    rsi = ta.rsi(closes, length=14)
    result["rsi"] = float(rsi.iloc[-1]) if rsi is not None and not rsi.isna().all() else None

    macd_obj = ta.macd(closes, fast=12, slow=26, signal=9)
    if macd_obj is not None and not macd_obj.empty:
        cols = [c for c in macd_obj.columns]
        result["macd_line"] = float(macd_obj[cols[0]].iloc[-1]) if len(cols) > 0 else None
        result["macd_signal"] = float(macd_obj[cols[1]].iloc[-1]) if len(cols) > 1 else None
        result["macd_histogram"] = float(macd_obj[cols[2]].iloc[-1]) if len(cols) > 2 else None
    else:
        result["macd_line"] = None
        result["macd_signal"] = None
        result["macd_histogram"] = None

    for period in [20, 50, 200]:
        ema = ta.ema(closes, length=period)
        result[f"ema_{period}"] = float(ema.iloc[-1]) if ema is not None and not ema.isna().all() else None

    for period in [20, 50, 200]:
        sma = ta.sma(closes, length=period)
        result[f"sma_{period}"] = float(sma.iloc[-1]) if sma is not None and not sma.isna().all() else None

    bb = ta.bbands(closes, length=20, std=2)
    if bb is not None and not bb.empty:
        cols = [c for c in bb.columns]
        result["bb_upper"] = float(bb[cols[0]].iloc[-1]) if len(cols) > 0 else None
        result["bb_middle"] = float(bb[cols[1]].iloc[-1]) if len(cols) > 1 else None
        result["bb_lower"] = float(bb[cols[2]].iloc[-1]) if len(cols) > 2 else None
    else:
        result["bb_upper"] = None
        result["bb_middle"] = None
        result["bb_lower"] = None

    atr_df = df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    if not atr_df.empty and all(c in atr_df.columns for c in ["high", "low", "close"]):
        atr_val = ta.atr(atr_df["high"], atr_df["low"], atr_df["close"], length=14)
        result["atr"] = float(atr_val.iloc[-1]) if atr_val is not None and not atr_val.isna().all() else None
    else:
        result["atr"] = None

    if "volume" in df.columns and not df["volume"].empty:
        vol = df["volume"]
        avg_vol = vol.rolling(20).mean()
        result["avg_volume"] = float(avg_vol.iloc[-1]) if not avg_vol.isna().all() else None
        current_vol = float(vol.iloc[-1])
        result["volume"] = current_vol
        avg_vol_val = result["avg_volume"]
        if avg_vol_val and avg_vol_val > 0:
            result["relative_volume"] = round(current_vol / avg_vol_val, 2)
        else:
            result["relative_volume"] = None
    else:
        result["volume"] = None
        result["avg_volume"] = None
        result["relative_volume"] = None

    close_list = closes.tolist() if isinstance(closes, pd.Series) else closes
    result["support"], result["resistance"] = find_support_resistance(close_list, lookback=20)
    result["trend"] = detect_trend(close_list)
    return result


def calculate_rsi(closes: List[float]) -> Optional[float]:
    if len(closes) < 15:
        return None
    series = _to_series(closes)
    rsi = ta.rsi(series, length=14)
    if rsi is None or rsi.isna().all():
        return None
    return float(rsi.iloc[-1])


def calculate_ema(closes: List[float], period: int) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    series = _to_series(closes)
    ema = ta.ema(series, length=period)
    if ema is None or ema.isna().all():
        return None
    return float(ema.iloc[-1])


def calculate_ema_series(closes: List[float], period: int) -> List[Optional[float]]:
    if len(closes) < period + 1:
        return [None] * len(closes)
    series = _to_series(closes)
    ema = ta.ema(series, length=period)
    return [float(v) if not pd.isna(v) else None for v in ema]


def calculate_macd(closes: List[float]) -> Dict[str, Optional[float]]:
    if len(closes) < 33:
        return {"line": None, "signal": None, "histogram": None}
    series = _to_series(closes)
    macd_obj = ta.macd(series, fast=12, slow=26, signal=9)
    if macd_obj is None or macd_obj.empty:
        return {"line": None, "signal": None, "histogram": None}
    cols = [c for c in macd_obj.columns]
    return {
        "line": float(macd_obj[cols[0]].iloc[-1]) if len(cols) > 0 else None,
        "signal": float(macd_obj[cols[1]].iloc[-1]) if len(cols) > 1 else None,
        "histogram": float(macd_obj[cols[2]].iloc[-1]) if len(cols) > 2 else None,
    }


def calculate_bollinger(closes: List[float]) -> Dict[str, Optional[float]]:
    if len(closes) < 21:
        return {"upper": None, "middle": None, "lower": None}
    series = _to_series(closes)
    bb = ta.bbands(series, length=20, std=2)
    if bb is None or bb.empty:
        return {"upper": None, "middle": None, "lower": None}
    cols = [c for c in bb.columns]
    return {
        "upper": float(bb[cols[0]].iloc[-1]) if len(cols) > 0 else None,
        "middle": float(bb[cols[1]].iloc[-1]) if len(cols) > 1 else None,
        "lower": float(bb[cols[2]].iloc[-1]) if len(cols) > 2 else None,
    }


def detect_trend(closes: List[float]) -> str:
    if len(closes) < 201:
        if len(closes) < 51:
            return "sideways"
        ema50 = calculate_ema_series(closes, 50)
        current_price = closes[-1]
        ema50_val = ema50[-1]
        if ema50_val is None:
            return "sideways"
        if current_price > ema50_val * 1.02:
            return "uptrend"
        elif current_price < ema50_val * 0.98:
            return "downtrend"
        return "sideways"

    ema50 = calculate_ema_series(closes, 50)
    ema200 = calculate_ema_series(closes, 200)
    current_price = closes[-1]
    ema50_val = ema50[-1]
    ema200_val = ema200[-1]

    if ema50_val is None or ema200_val is None:
        return "sideways"

    if ema50_val > ema200_val and current_price > ema50_val:
        return "uptrend"
    elif ema50_val < ema200_val and current_price < ema50_val:
        return "downtrend"
    return "sideways"


def find_support_resistance(closes: List[float], lookback: int = 20) -> Tuple[Optional[float], Optional[float]]:
    if len(closes) < lookback * 2:
        if not closes:
            return None, None
        return min(closes), max(closes)

    recent = closes[-lookback:]
    highs = []
    lows = []

    for i in range(1, len(recent) - 1):
        if recent[i] > recent[i - 1] and recent[i] > recent[i + 1]:
            highs.append(recent[i])
        if recent[i] < recent[i - 1] and recent[i] < recent[i + 1]:
            lows.append(recent[i])

    support = min(lows) if lows else min(recent)
    resistance = max(highs) if highs else max(recent)
    return support, resistance
