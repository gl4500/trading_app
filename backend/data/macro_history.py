"""
Persistent store for macro environment signal history.

Saves daily macro features (VIX, yields, ETF returns, regime) to a single
Parquet file: data/history/__MACRO__.parquet

Used by:
  - data/history_backfill.py  — seeds history from Alpaca/yfinance bars
  - data/cnn_model.py         — build_training_windows joins macro features
  - data/signal_history.py    — get_recent_window joins macro for inference

Schema
------
  date_ts       unix timestamp (float64) — bar date, used as the join key
  vix           VIX index level
  tnx           10-year Treasury yield (e.g. 4.3)
  vix_norm      VIX / 30.0  clipped to [0, 3]
  gld_1d        GLD 1-day forward return
  gld_5d        GLD 5-day forward return
  tlt_1d        TLT 1-day forward return
  tlt_5d        TLT 5-day forward return
  spy_1d        SPY 1-day forward return
  spy_5d        SPY 5-day forward return
  iwm_5d        IWM 5-day forward return
  qqq_5d        QQQ 5-day forward return
  uup_5d        UUP 5-day forward return
  uso_5d        USO 5-day forward return
  breadth_score (iwm_5d - spy_5d) clipped to [-1, 1]
  regime        string: RISK_ON | RISK_OFF | HIGH_VOL | NEUTRAL
  regime_score  float: RISK_ON→+1.0, RISK_OFF→-1.0, HIGH_VOL→-0.5, else 0.0

CNN Feature Channels (N_MACRO_CHANNELS = 5)
-------------------------------------------
  macro_vix_norm    channel 10
  macro_gld_5d      channel 11
  macro_tlt_5d      channel 12
  macro_spy_5d      channel 13
  macro_breadth     channel 14
"""
import asyncio
import logging
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── paths ─────────────────────────────────────────────────────────────────────

_HISTORY_DIR = os.path.join(os.path.dirname(__file__), "history")
_MACRO_FILE  = os.path.join(_HISTORY_DIR, "__MACRO__.parquet")

# ── schema ─────────────────────────────────────────────────────────────────────

MACRO_COLUMNS: List[str] = [
    "date_ts",
    "vix", "tnx",
    "vix_norm",
    "gld_1d", "gld_5d",
    "tlt_1d", "tlt_5d",
    "spy_1d", "spy_5d",
    "iwm_5d", "qqq_5d",
    "uup_5d", "uso_5d",
    "breadth_score",
    "regime",
    "regime_score",
]

# The 5 columns added as extra CNN input channels
MACRO_FEATURE_COLS: List[str] = [
    "macro_vix_norm",
    "macro_gld_5d",
    "macro_tlt_5d",
    "macro_spy_5d",
    "macro_breadth",
]

N_MACRO_CHANNELS: int = len(MACRO_FEATURE_COLS)  # 5

_REGIME_SCORES: Dict[str, float] = {
    "RISK_ON":   1.0,
    "RISK_OFF": -1.0,
    "HIGH_VOL": -0.5,
}

_LOCK = asyncio.Lock()


# ── file I/O ─────────────────────────────────────────────────────────────────

def _load() -> pd.DataFrame:
    """Load __MACRO__.parquet, returning an empty DataFrame on missing/corrupt."""
    # Read _MACRO_FILE from the module namespace each call so test patching works
    import data.macro_history as _mod
    path = _mod._MACRO_FILE
    if not os.path.exists(path):
        return pd.DataFrame(columns=MACRO_COLUMNS)
    try:
        return pd.read_parquet(path)
    except Exception as exc:
        logger.warning(f"macro_history: could not read {path}: {exc}")
        return pd.DataFrame(columns=MACRO_COLUMNS)


def _save(df: pd.DataFrame) -> None:
    import data.macro_history as _mod
    path = _mod._MACRO_FILE
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    df.to_parquet(path, compression="zstd", index=False)


# ── public store ──────────────────────────────────────────────────────────────

class MacroHistoryStore:
    """Records macro environment snapshots to __MACRO__.parquet."""

    async def record_snapshot(
        self,
        date_ts: float,
        vix: float,
        tnx: float,
        returns: Dict[str, float],
        regime: str,
    ) -> None:
        """
        Append one macro row to __MACRO__.parquet.

        Parameters
        ----------
        date_ts : unix timestamp of the bar date
        vix     : VIX level (e.g. 18.5); may be NaN when unavailable
        tnx     : 10-year yield (e.g. 4.3)
        returns : dict with keys gld_1d, gld_5d, tlt_1d, tlt_5d,
                  spy_1d, spy_5d, iwm_5d, qqq_5d, uup_5d, uso_5d
        regime  : RISK_ON | RISK_OFF | HIGH_VOL | NEUTRAL | ...
        """
        vix_f    = float(vix)
        # vix_norm = VIX / 30, clamped to [0, 3]
        vix_norm = float(np.clip(vix_f / 30.0, 0.0, 3.0)) if not np.isnan(vix_f) else float("nan")
        iwm_5d   = float(returns.get("iwm_5d", 0.0))
        spy_5d   = float(returns.get("spy_5d", 0.0))
        breadth  = float(np.clip(iwm_5d - spy_5d, -1.0, 1.0))
        r_score  = float(_REGIME_SCORES.get(regime, 0.0))

        row: Dict = {
            "date_ts":       float(date_ts),
            "vix":           vix_f,
            "tnx":           float(tnx),
            "vix_norm":      vix_norm,
            "gld_1d":        float(returns.get("gld_1d", 0.0)),
            "gld_5d":        float(returns.get("gld_5d", 0.0)),
            "tlt_1d":        float(returns.get("tlt_1d", 0.0)),
            "tlt_5d":        float(returns.get("tlt_5d", 0.0)),
            "spy_1d":        float(returns.get("spy_1d", 0.0)),
            "spy_5d":        spy_5d,
            "iwm_5d":        iwm_5d,
            "qqq_5d":        float(returns.get("qqq_5d", 0.0)),
            "uup_5d":        float(returns.get("uup_5d", 0.0)),
            "uso_5d":        float(returns.get("uso_5d", 0.0)),
            "breadth_score": breadth,
            "regime":        str(regime),
            "regime_score":  r_score,
        }

        async with _LOCK:
            df = _load()
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
            _save(df)

    def get_features_for_date(self, ts: float) -> np.ndarray:
        """
        Return the 5 CNN macro feature values for the date closest to ts.

        Feature order (matches MACRO_FEATURE_COLS):
          [vix_norm, gld_5d, tlt_5d, spy_5d, breadth_score]

        Returns a zero vector when no data is available within ±2 calendar days.

        Parameters
        ----------
        ts : unix timestamp to look up

        Returns
        -------
        np.ndarray of shape (N_MACRO_CHANNELS,) = (5,), dtype float32
        """
        zero = np.zeros(N_MACRO_CHANNELS, dtype=np.float32)
        df = _load()
        if df.empty or "date_ts" not in df.columns:
            return zero

        diffs = np.abs(df["date_ts"].values.astype(float) - float(ts))
        min_i = int(np.argmin(diffs))
        if diffs[min_i] > 2 * 86_400:
            return zero

        r = df.iloc[min_i]

        def _safe(col: str) -> float:
            v = r.get(col, 0.0)
            if v is None:
                return 0.0
            try:
                f = float(v)
                return 0.0 if np.isnan(f) else f
            except (TypeError, ValueError):
                return 0.0

        return np.array([
            _safe("vix_norm"),
            _safe("gld_5d"),
            _safe("tlt_5d"),
            _safe("spy_5d"),
            _safe("breadth_score"),
        ], dtype=np.float32)


# Module-level singleton
macro_history = MacroHistoryStore()
