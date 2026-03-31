"""
Shared technical indicator calculator.
Computes RSI, MACD, Bollinger Bands, ATR, and Volume metrics
from a bars DataFrame and returns a flat dict of current values.
"""
import math
import logging
import numpy as np
import pandas as pd
from typing import Dict, Optional

from config import config

logger = logging.getLogger(__name__)

try:
    import pandas_ta as ta
    HAS_TA = True
except ImportError:
    HAS_TA = False


def _manual_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _manual_macd(close: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line, macd_line - signal_line


def _manual_bb(close: pd.Series, period=20, std=2.0):
    sma = close.rolling(window=period).mean()
    std_dev = close.rolling(window=period).std()
    return sma + std_dev * std, sma, sma - std_dev * std


def _manual_atr(df: pd.DataFrame, period=14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def _manual_stoch(df: pd.DataFrame, k_period: int = 14, d_period: int = 3):
    """Compute Stochastic %K and %D. Returns (k_series, d_series)."""
    low_min = df["low"].rolling(k_period).min()
    high_max = df["high"].rolling(k_period).max()
    k = 100.0 * (df["close"] - low_min) / (high_max - low_min).replace(0, np.nan)
    d = k.rolling(d_period).mean()
    return k, d


def _manual_obv(df: pd.DataFrame) -> pd.Series:
    """Compute On-Balance Volume."""
    direction = np.sign(df["close"].diff()).fillna(0)
    return (direction * df["volume"]).cumsum()


def compute(df: pd.DataFrame) -> Optional[Dict]:
    """
    Compute technical indicators from a bars DataFrame.
    Returns a dict of current (latest row) values, or None if insufficient data.
    """
    min_rows = max(config.MACD_SLOW, config.BB_PERIOD, config.RSI_PERIOD) + 5
    if df is None or len(df) < min_rows:
        return None

    df = df.copy()
    close = df["close"]

    try:
        if HAS_TA:
            df.ta.rsi(length=config.RSI_PERIOD, append=True)
            df.ta.macd(fast=config.MACD_FAST, slow=config.MACD_SLOW,
                       signal=config.MACD_SIGNAL, append=True)
            df.ta.bbands(length=config.BB_PERIOD, std=config.BB_STD, append=True)

            rsi_col  = f"RSI_{config.RSI_PERIOD}"
            macd_col = f"MACD_{config.MACD_FAST}_{config.MACD_SLOW}_{config.MACD_SIGNAL}"
            macds_col= f"MACDs_{config.MACD_FAST}_{config.MACD_SLOW}_{config.MACD_SIGNAL}"
            macdh_col= f"MACDh_{config.MACD_FAST}_{config.MACD_SLOW}_{config.MACD_SIGNAL}"
            bbu_col  = f"BBU_{config.BB_PERIOD}_{float(config.BB_STD)}"
            bbm_col  = f"BBM_{config.BB_PERIOD}_{float(config.BB_STD)}"
            bbl_col  = f"BBL_{config.BB_PERIOD}_{float(config.BB_STD)}"

            rsi      = df[rsi_col].iloc[-1]  if rsi_col  in df.columns else _manual_rsi(close).iloc[-1]
            macd     = df[macd_col].iloc[-1] if macd_col in df.columns else _manual_macd(close)[0].iloc[-1]
            macd_sig = df[macds_col].iloc[-1]if macds_col in df.columns else _manual_macd(close)[1].iloc[-1]
            macd_hist= df[macdh_col].iloc[-1]if macdh_col in df.columns else _manual_macd(close)[2].iloc[-1]
            bb_upper = df[bbu_col].iloc[-1]  if bbu_col  in df.columns else _manual_bb(close)[0].iloc[-1]
            bb_mid   = df[bbm_col].iloc[-1]  if bbm_col  in df.columns else _manual_bb(close)[1].iloc[-1]
            bb_lower = df[bbl_col].iloc[-1]  if bbl_col  in df.columns else _manual_bb(close)[2].iloc[-1]
        else:
            rsi = _manual_rsi(close, config.RSI_PERIOD).iloc[-1]
            macd, macd_sig_s, macd_hist_s = _manual_macd(close)
            macd, macd_sig, macd_hist = macd.iloc[-1], macd_sig_s.iloc[-1], macd_hist_s.iloc[-1]
            bb_upper_s, bb_mid_s, bb_lower_s = _manual_bb(close)
            bb_upper, bb_mid, bb_lower = bb_upper_s.iloc[-1], bb_mid_s.iloc[-1], bb_lower_s.iloc[-1]

        # Volume
        vol_now  = float(df["volume"].iloc[-1])  if "volume" in df.columns else 0
        vol_sma20= float(df["volume"].rolling(20).mean().iloc[-1]) if "volume" in df.columns else 0
        vol_ratio= vol_now / vol_sma20 if vol_sma20 > 0 else 1.0

        # ATR (volatility)
        atr = None
        if "high" in df.columns and "low" in df.columns:
            atr = float(_manual_atr(df).iloc[-1])

        # SMA 20 / 50
        sma20 = float(close.rolling(20).mean().iloc[-1]) if len(close) >= 20 else None
        sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None

        # Price position within BB (0=at lower, 1=at upper)
        bb_range = bb_upper - bb_lower
        bb_position = (float(close.iloc[-1]) - bb_lower) / bb_range if bb_range > 0 else 0.5

        # Stochastic oscillator (%K / %D)
        stoch_k = stoch_d = stoch_k_prev = stoch_d_prev = None
        if "high" in df.columns and "low" in df.columns:
            if HAS_TA:
                df.ta.stoch(k=14, d=3, smooth_k=1, append=True)
                sk_col = "STOCHk_14_3_1"
                sd_col = "STOCHd_14_3_1"
                if sk_col in df.columns and sd_col in df.columns:
                    stoch_k = df[sk_col].iloc[-1]
                    stoch_d = df[sd_col].iloc[-1]
                    stoch_k_prev = df[sk_col].iloc[-2] if len(df) > 1 else stoch_k
                    stoch_d_prev = df[sd_col].iloc[-2] if len(df) > 1 else stoch_d
            if stoch_k is None:
                sk_s, sd_s = _manual_stoch(df)
                stoch_k = sk_s.iloc[-1]
                stoch_d = sd_s.iloc[-1]
                stoch_k_prev = sk_s.iloc[-2] if len(sk_s) > 1 else stoch_k
                stoch_d_prev = sd_s.iloc[-2] if len(sd_s) > 1 else stoch_d

        # OBV (On-Balance Volume)
        obv_val = obv_trend = None
        if "volume" in df.columns:
            obv_series = _manual_obv(df)
            obv_val = float(obv_series.iloc[-1])
            lookback = min(5, len(obv_series) - 1)
            if lookback > 0:
                obv_trend = 1 if obv_series.iloc[-1] > obv_series.iloc[-1 - lookback] else -1

        def _f(v):
            """Return float or None, treating NaN as None."""
            if v is None:
                return None
            try:
                return None if math.isnan(float(v)) else round(float(v), 4)
            except Exception:
                return None

        return {
            "rsi":          _f(rsi),
            "macd":         _f(macd),
            "macd_signal":  _f(macd_sig),
            "macd_hist":    _f(macd_hist),
            "bb_upper":     _f(bb_upper),
            "bb_mid":       _f(bb_mid),
            "bb_lower":     _f(bb_lower),
            "bb_position":  _f(bb_position),   # 0–1 within bands
            "sma20":        _f(sma20),
            "sma50":        _f(sma50),
            "atr":          _f(atr),
            "volume":       round(vol_now),
            "volume_sma20": round(vol_sma20),
            "volume_ratio": _f(vol_ratio),
            "stoch_k":      _f(stoch_k),        # 0–100, < 20 oversold, > 80 overbought
            "stoch_d":      _f(stoch_d),        # 3-period signal line
            "stoch_k_prev": _f(stoch_k_prev),   # previous bar %K (crossover detection)
            "stoch_d_prev": _f(stoch_d_prev),
            "obv":          _f(obv_val),         # cumulative on-balance volume
            "obv_trend":    obv_trend,           # 1=rising, -1=falling over last 5 bars
        }

    except Exception as e:
        logger.error(f"technicals.compute error: {e}")
        return None


def format_for_prompt(symbol: str, ind: Optional[Dict], price: float) -> str:
    """Format indicators as a compact text block for prompt injection."""
    if not ind:
        return f"{symbol}: Technical indicators unavailable (insufficient data)."

    rsi = ind.get("rsi")
    macd_hist = ind.get("macd_hist")
    bb_upper = ind.get("bb_upper")
    bb_lower = ind.get("bb_lower")
    bb_pos   = ind.get("bb_position")
    sma20    = ind.get("sma20")
    sma50    = ind.get("sma50")
    atr      = ind.get("atr")
    vol_ratio= ind.get("volume_ratio")

    # RSI interpretation
    if rsi is not None:
        if rsi < 30:   rsi_note = "OVERSOLD"
        elif rsi > 70: rsi_note = "OVERBOUGHT"
        elif rsi < 40: rsi_note = "weak"
        elif rsi > 60: rsi_note = "strong"
        else:          rsi_note = "neutral"
    else:
        rsi_note = "N/A"

    # MACD interpretation
    if macd_hist is not None:
        macd_note = "bullish momentum" if macd_hist > 0 else "bearish momentum"
    else:
        macd_note = "N/A"

    # BB interpretation
    if bb_pos is not None:
        if bb_pos < 0.15:   bb_note = "near LOWER band (oversold zone)"
        elif bb_pos > 0.85: bb_note = "near UPPER band (overbought zone)"
        else:               bb_note = f"{bb_pos*100:.0f}% through bands"
    else:
        bb_note = "N/A"

    # Trend via SMAs
    trend_note = ""
    if sma20 and sma50:
        if price > sma20 > sma50:
            trend_note = "Uptrend (price > SMA20 > SMA50)"
        elif price < sma20 < sma50:
            trend_note = "Downtrend (price < SMA20 < SMA50)"
        elif sma20 > sma50:
            trend_note = "Mixed (SMA20 > SMA50 but price below SMA20)"
        else:
            trend_note = "Mixed (SMA20 < SMA50)"

    vol_note = f"{vol_ratio:.1f}x avg volume" if vol_ratio else ""

    # Stochastic interpretation
    stoch_k   = ind.get("stoch_k")
    stoch_d   = ind.get("stoch_d")
    stoch_note = ""
    if stoch_k is not None:
        if stoch_k > 80:   stoch_zone = "OVERBOUGHT"
        elif stoch_k < 20: stoch_zone = "OVERSOLD"
        else:              stoch_zone = "neutral"
        stoch_note = f"  Stochastic: %K={stoch_k:.1f} / %D={stoch_d:.1f} [{stoch_zone}]" if stoch_d is not None else f"  Stochastic: %K={stoch_k:.1f} [{stoch_zone}]"

    # OBV interpretation
    obv_trend = ind.get("obv_trend")
    obv_note = ""
    if obv_trend is not None:
        obv_dir = "rising (accumulation)" if obv_trend == 1 else "falling (distribution)"
        obv_note = f"  OBV: {obv_dir}"

    lines = [
        f"  RSI({14}): {rsi:.1f} [{rsi_note}]" if rsi else "  RSI: N/A",
        f"  MACD Histogram: {macd_hist:+.4f} [{macd_note}]" if macd_hist is not None else "  MACD: N/A",
        stoch_note,
        f"  Bollinger Bands: ${bb_lower:.2f} / ${bb_upper:.2f} — {bb_note}" if bb_lower and bb_upper else "  BB: N/A",
        f"  SMA20: ${sma20:.2f} | SMA50: ${sma50:.2f} | {trend_note}" if sma20 and sma50 else "",
        f"  ATR(14): ${atr:.2f} (daily volatility range)" if atr else "",
        f"  Volume: {vol_note}" if vol_note else "",
        obv_note,
    ]
    return "\n".join(l for l in lines if l)
