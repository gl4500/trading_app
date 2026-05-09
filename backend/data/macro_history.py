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
  date_ts            unix timestamp (float64) — bar date, used as the join key
  vix                VIX index level
  tnx                10-year Treasury yield (e.g. 4.3)
  vix_norm           VIX / 30.0  clipped to [0, 3]
  gld_1d             GLD 1-day forward return  (NOT a CNN input)
  tlt_1d             TLT 1-day forward return  (NOT a CNN input)
  spy_1d             SPY 1-day forward return  (NOT a CNN input)
  gld_5d_back        GLD 5-day TRAILING return (Task #24 — was forward; renamed
                     to _back to force re-backfill and document the fix)
  tlt_5d_back        TLT 5-day trailing return
  spy_5d_back        SPY 5-day trailing return
  iwm_5d_back        IWM 5-day trailing return
  qqq_5d_back        QQQ 5-day trailing return
  uup_5d_back        UUP 5-day trailing return
  uso_5d_back        USO 5-day trailing return
  breadth_score_back (iwm_5d_back - spy_5d_back) clipped to [-1, 1]
  regime             string: RISK_ON | RISK_OFF | HIGH_VOL | NEUTRAL
  regime_score       float: RISK_ON→+1.0, RISK_OFF→-1.0, HIGH_VOL→-0.5, else 0.0

CNN Feature Channels (N_MACRO_CHANNELS = 5)
-------------------------------------------
  macro_vix_norm        channel 10  (level — no lookahead concern)
  macro_gld_5d_back     channel 11  (trailing 5-day GLD return)
  macro_tlt_5d_back     channel 12  (trailing 5-day TLT return)
  macro_spy_5d_back     channel 13  (trailing 5-day SPY return)
  macro_breadth_back    channel 14  ((iwm - spy) trailing 5-day, clipped)
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
    "gld_1d", "tlt_1d", "spy_1d",
    # Task #24: 5d returns are now TRAILING (was forward) — `_back` suffix
    # documents the fix and forces re-backfill of any stale parquet.
    "gld_5d_back", "tlt_5d_back", "spy_5d_back",
    "iwm_5d_back", "qqq_5d_back", "uup_5d_back", "uso_5d_back",
    # 2026-05-09: DJIA (DIA ETF) trailing 5d return — added so the model has
    # a second broad-market index alongside SPY (95% correlated, mostly
    # redundant for AUC, but useful for the benchmark UI and as a sanity
    # check on regime signals).
    "dji_5d_back",
    "breadth_score_back",
    # Sprint 8 (#67, 2026-05-09): 10-day trailing returns aligned with the
    # 10d label horizon (LABEL_HORIZON_COL = "return_10d"). The 5d channels
    # above are kept for backwards-compat with the live XGB model that uses
    # macro_spy_5d_back + macro_breadth_back; the 10d channels are
    # pool-only until forward selection promotes them.
    "gld_10d_back", "tlt_10d_back", "spy_10d_back",
    "iwm_10d_back", "dji_10d_back",
    "breadth_score_10d_back",
    "regime",
    "regime_score",
]

# The macro columns added as extra CNN input channels
MACRO_FEATURE_COLS: List[str] = [
    "macro_vix_norm",
    "macro_gld_5d_back",
    "macro_tlt_5d_back",
    "macro_spy_5d_back",
    "macro_breadth_back",
    # 2026-05-09: appended at end so existing channel indices [14-18] are
    # preserved — production XGB feature_filter [0,1,2,4,13,14,17,18]
    # (all ≤ 18) keeps pointing at the same channels. Lands at index 19.
    "macro_dji_5d_back",
]

# Sprint 8 (#67): 10-day macro lookbacks aligned with LABEL_HORIZON_COL
# ("return_10d"). Kept SEPARATE from MACRO_FEATURE_COLS so they land at the
# very end of feature_catalog.ALL_CHANNEL_COLUMNS (after HISTORICAL),
# preserving every existing channel index. Pool-only until forward
# selection promotes them.
MACRO_FEATURE_COLS_10D: List[str] = [
    "macro_gld_10d_back",
    "macro_tlt_10d_back",
    "macro_spy_10d_back",
    "macro_breadth_10d_back",
    "macro_dji_10d_back",
]

N_MACRO_CHANNELS: int = len(MACRO_FEATURE_COLS)  # 6
N_MACRO_10D_CHANNELS: int = len(MACRO_FEATURE_COLS_10D)  # 5

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
        returns : dict with keys gld_1d, tlt_1d, spy_1d (forward 1-day, not
                  CNN inputs) and gld_5d_back, tlt_5d_back, spy_5d_back,
                  iwm_5d_back, qqq_5d_back, uup_5d_back, uso_5d_back,
                  dji_5d_back (trailing 5-day, used as CNN inputs — Task #24
                  established the trailing convention; #84 added DJIA)
        regime  : RISK_ON | RISK_OFF | HIGH_VOL | NEUTRAL | ...
        """
        vix_f    = float(vix)
        # vix_norm = VIX / 30, clamped to [0, 3]
        vix_norm = float(np.clip(vix_f / 30.0, 0.0, 3.0)) if not np.isnan(vix_f) else float("nan")
        iwm_5d_back = float(returns.get("iwm_5d_back", 0.0))
        spy_5d_back = float(returns.get("spy_5d_back", 0.0))
        breadth_back = float(np.clip(iwm_5d_back - spy_5d_back, -1.0, 1.0))

        # Sprint 8 (#67): 10-day trailing returns aligned with the 10d label
        # horizon. Default to 0.0 when caller doesn't supply (backwards-
        # compat with older callers). Same clip rule for breadth_10d.
        iwm_10d_back = float(returns.get("iwm_10d_back", 0.0))
        spy_10d_back = float(returns.get("spy_10d_back", 0.0))
        breadth_10d_back = float(np.clip(iwm_10d_back - spy_10d_back, -1.0, 1.0))

        r_score  = float(_REGIME_SCORES.get(regime, 0.0))

        row: Dict = {
            "date_ts":            float(date_ts),
            "vix":                vix_f,
            "tnx":                float(tnx),
            "vix_norm":           vix_norm,
            "gld_1d":             float(returns.get("gld_1d", 0.0)),
            "tlt_1d":             float(returns.get("tlt_1d", 0.0)),
            "spy_1d":             float(returns.get("spy_1d", 0.0)),
            "gld_5d_back":        float(returns.get("gld_5d_back", 0.0)),
            "tlt_5d_back":        float(returns.get("tlt_5d_back", 0.0)),
            "spy_5d_back":        spy_5d_back,
            "iwm_5d_back":        iwm_5d_back,
            "qqq_5d_back":        float(returns.get("qqq_5d_back", 0.0)),
            "uup_5d_back":        float(returns.get("uup_5d_back", 0.0)),
            "uso_5d_back":        float(returns.get("uso_5d_back", 0.0)),
            "dji_5d_back":        float(returns.get("dji_5d_back", 0.0)),
            "breadth_score_back": breadth_back,
            "gld_10d_back":           float(returns.get("gld_10d_back", 0.0)),
            "tlt_10d_back":           float(returns.get("tlt_10d_back", 0.0)),
            "spy_10d_back":           spy_10d_back,
            "iwm_10d_back":           iwm_10d_back,
            "dji_10d_back":           float(returns.get("dji_10d_back", 0.0)),
            "breadth_score_10d_back": breadth_10d_back,
            "regime":             str(regime),
            "regime_score":       r_score,
        }

        async with _LOCK:
            df = _load()
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
            _save(df)

    def get_features_for_date(self, ts: float) -> np.ndarray:
        """
        Return the CNN macro feature values for the date closest to ts.

        Feature order matches MACRO_FEATURE_COLS + MACRO_FEATURE_COLS_10D:
          [vix_norm, gld_5d_back, tlt_5d_back, spy_5d_back, breadth_score_back,
           dji_5d_back,
           gld_10d_back, tlt_10d_back, spy_10d_back, breadth_score_10d_back,
           dji_10d_back]

        Returns a zero vector when no data is available within ±2 calendar days.

        Parameters
        ----------
        ts : unix timestamp to look up

        Returns
        -------
        np.ndarray of shape (N_MACRO_CHANNELS + N_MACRO_10D_CHANNELS,) = (11,),
        dtype float32. Caller (signal_history._attach_macro_features) splits
        these into MACRO and MACRO_10D blocks per the catalog ordering.
        """
        total = N_MACRO_CHANNELS + N_MACRO_10D_CHANNELS
        zero = np.zeros(total, dtype=np.float32)
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
            # MACRO (6) — original 5d channels
            _safe("vix_norm"),
            _safe("gld_5d_back"),
            _safe("tlt_5d_back"),
            _safe("spy_5d_back"),
            _safe("breadth_score_back"),
            _safe("dji_5d_back"),
            # MACRO_10D (5) — Sprint 8 (#67) 10d channels aligned with label horizon
            _safe("gld_10d_back"),
            _safe("tlt_10d_back"),
            _safe("spy_10d_back"),
            _safe("breadth_score_10d_back"),
            _safe("dji_10d_back"),
        ], dtype=np.float32)


# Module-level singleton
macro_history = MacroHistoryStore()
