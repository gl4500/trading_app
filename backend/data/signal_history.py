"""
Parquet-backed store for composite signal snapshots and their future price outcomes.

Each symbol gets its own compressed Parquet file under data/history/.
Snapshots are recorded on every market data cycle; outcomes (1D / 5D returns)
are filled in lazily once the target time has elapsed.

This data drives the CNN weight learner in data/cnn_model.py.
"""
import asyncio
import logging
import os
import time
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── paths ─────────────────────────────────────────────────────────────────────

_HISTORY_DIR = os.path.join(os.path.dirname(__file__), "history")

# Source score column names (order must match cnn_model.SOURCE_NAMES)
SOURCE_COLUMNS = [
    "analyst_score",
    "earnings_score",
    "alpaca_score",
    "yahoo_score",
    "congress_score",
    "iv_rv_score",     # IV minus RV_20d spread, scored to [-1, +1]
]

_DTYPE_MAP = {
    "symbol":            "object",
    "snapshot_ts":       "float64",
    "analyst_score":     "float64",
    "earnings_score":    "float64",
    "alpaca_score":      "float64",
    "yahoo_score":       "float64",
    "congress_score":    "float64",
    "iv_rv_score":       "float64",  # IV/RV spread score [-1, +1]; NaN when options unavailable
    "composite_score":   "float64",
    "price":             "float64",
    "return_1d":         "float64",
    "return_5d":         "float64",
    # Agent consensus columns — filled after agents run each cycle
    "agent_consensus":   "float64",  # -1.0 to +1.0 performance-weighted vote
    "agent_agreement":   "float64",  # 0.0 to 1.0 fraction of agents that agree
    "top_agent_correct": "float64",  # NaN until 24h later; 1.0 = top agent was right
    # Realized volatility channels (annualized, 252-day basis)
    "rv_20d":            "float64",  # 20-day rolling realized vol
    "rv_60d":            "float64",  # 60-day rolling realized vol
}

# Agent feature columns used as extra CNN input channels
AGENT_COLUMNS = ["agent_consensus", "agent_agreement"]

# Realized volatility columns — CNN channels 8 & 9
RV_COLUMNS = ["rv_20d", "rv_60d"]

# Rolling cap: keep at most 90 days × ~12 snapshots/hour = ~26 000 rows/symbol
MAX_ROWS = 90 * 24 * 12

# One asyncio Lock per symbol — prevents concurrent reads/writes to the same file
_LOCKS: Dict[str, asyncio.Lock] = {}


def _get_lock(symbol: str) -> asyncio.Lock:
    if symbol not in _LOCKS:
        _LOCKS[symbol] = asyncio.Lock()
    return _LOCKS[symbol]


def _symbol_path(symbol: str) -> str:
    return os.path.join(_HISTORY_DIR, f"{symbol.upper()}.parquet")


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame({col: pd.Series(dtype=dt) for col, dt in _DTYPE_MAP.items()})


def _load(symbol: str) -> pd.DataFrame:
    path = _symbol_path(symbol)
    if not os.path.exists(path):
        return _empty_df()
    try:
        return pd.read_parquet(path)
    except Exception as exc:
        logger.warning(f"signal_history: could not read {path}: {exc}")
        return _empty_df()


def _save(symbol: str, df: pd.DataFrame) -> None:
    os.makedirs(_HISTORY_DIR, exist_ok=True)
    if len(df) > MAX_ROWS:
        df = df.tail(MAX_ROWS).reset_index(drop=True)
    df.to_parquet(_symbol_path(symbol), compression="zstd", index=False)


# ── public store ──────────────────────────────────────────────────────────────

class SignalHistoryStore:
    """Records per-symbol signal snapshots and fills in forward-return outcomes."""

    async def record_snapshot(
        self,
        symbol: str,
        scores: Dict[str, Optional[float]],
        composite_score: float,
        price: float,
        rv_20d: Optional[float] = None,
        rv_60d: Optional[float] = None,
    ) -> None:
        """
        Append one row to the symbol's Parquet file.

        scores keys must match the source names used in signal_aggregator:
          analyst_consensus, earnings_surprise, alpaca_news, yahoo_news,
          congressional_trades, iv_rv_spread

        rv_20d / rv_60d: annualized realized volatility (252-day basis) computed
          from the symbol's recent daily close prices.  Pass None when bars are
          unavailable (will be stored as NaN and zero-filled in get_recent_window).
        """
        row = {
            "symbol":          symbol,
            "snapshot_ts":     time.time(),
            "analyst_score":   scores.get("analyst_consensus"),
            "earnings_score":  scores.get("earnings_surprise"),
            "alpaca_score":    scores.get("alpaca_news"),
            "yahoo_score":     scores.get("yahoo_news"),
            "congress_score":  scores.get("congressional_trades"),
            "iv_rv_score":     scores.get("iv_rv_spread"),
            "composite_score": composite_score,
            "price":           price,
            "return_1d":       np.nan,
            "return_5d":       np.nan,
            "rv_20d":          rv_20d,
            "rv_60d":          rv_60d,
        }
        async with _get_lock(symbol):
            df = _load(symbol)
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
            _save(symbol, df)

    async def update_outcomes(self, symbol: str, current_price: float) -> int:
        """
        Fill in return_1d / return_5d for any snapshots whose outcome window
        has now elapsed.  Returns the number of rows updated.

        Uses wall-clock time: 1 day = 86 400 s, 5 days = 432 000 s.
        For true trading-day accuracy you would filter weekends, but the
        approximation is fine for the CNN training signal.
        """
        ONE_DAY   = 86_400
        FIVE_DAYS = 5 * ONE_DAY
        now       = time.time()
        updated   = 0

        async with _get_lock(symbol):
            df = _load(symbol)
            if df.empty:
                return 0

            age = now - df["snapshot_ts"]

            mask_1d = df["return_1d"].isna() & (age >= ONE_DAY)
            mask_5d = df["return_5d"].isna() & (age >= FIVE_DAYS)

            for idx in df.index[mask_1d]:
                snap_price = df.at[idx, "price"]
                if snap_price and snap_price > 0:
                    df.at[idx, "return_1d"] = (current_price - snap_price) / snap_price
                    updated += 1

            for idx in df.index[mask_5d]:
                snap_price = df.at[idx, "price"]
                if snap_price and snap_price > 0:
                    df.at[idx, "return_5d"] = (current_price - snap_price) / snap_price
                    updated += 1

            if updated:
                _save(symbol, df)

        return updated

    def get_training_data(self, symbol: Optional[str] = None) -> pd.DataFrame:
        """
        Return all rows that have a known 1D outcome.
        Pass symbol=None to aggregate across every stored symbol.
        """
        if symbol:
            df = _load(symbol)
            if "return_1d" not in df.columns:
                return _empty_df()
            return df.dropna(subset=["return_1d"]).reset_index(drop=True)

        parts: List[pd.DataFrame] = []
        if os.path.isdir(_HISTORY_DIR):
            for fname in os.listdir(_HISTORY_DIR):
                if fname.endswith(".parquet"):
                    sym = fname[:-8]
                    if sym.startswith("__"):
                        continue   # skip __MACRO__ and any other meta files
                    df  = _load(sym)
                    if "return_1d" not in df.columns:
                        continue
                    ready = df.dropna(subset=["return_1d"])
                    if not ready.empty:
                        parts.append(ready)

        if not parts:
            return _empty_df()
        return pd.concat(parts, ignore_index=True)

    async def record_agent_signals(
        self,
        symbol: str,
        agent_consensus: float,
        agent_agreement: float,
        max_age_secs: float = 120.0,
    ) -> bool:
        """
        Update the most recent snapshot for symbol with agent signal data.

        Looks back at most max_age_secs to find the row to update.
        Returns True if a qualifying row was found and updated.

        Called from main.py after all agents have run each cycle.
        """
        async with _get_lock(symbol):
            df = _load(symbol)
            if df.empty:
                return False

            now    = time.time()
            recent = df.index[df["snapshot_ts"] >= now - max_age_secs]
            if len(recent) == 0:
                return False

            last_idx = recent[-1]

            # Ensure new columns exist (backward-compat with old Parquet files)
            for col in ("agent_consensus", "agent_agreement", "top_agent_correct"):
                if col not in df.columns:
                    df[col] = np.nan

            df.at[last_idx, "agent_consensus"] = float(agent_consensus)
            df.at[last_idx, "agent_agreement"] = float(agent_agreement)
            _save(symbol, df)

        return True

    async def update_top_agent_correct(self, symbol: str, current_price: float) -> int:
        """
        Fill top_agent_correct for snapshots whose 1-day outcome is now known.

        top_agent_correct = 1.0 if the agent_consensus direction matched the
        actual 1D price return sign, else 0.0.

        Returns the number of rows updated.
        """
        ONE_DAY = 86_400
        now     = time.time()
        updated = 0

        async with _get_lock(symbol):
            df = _load(symbol)
            if df.empty or "agent_consensus" not in df.columns:
                return 0

            age = now - df["snapshot_ts"]
            mask = (
                df["top_agent_correct"].isna()
                & (age >= ONE_DAY)
                & df["agent_consensus"].notna()
            )

            for idx in df.index[mask]:
                snap_price = df.at[idx, "price"]
                if not snap_price or snap_price <= 0:
                    continue
                actual_return = (current_price - snap_price) / snap_price
                consensus     = df.at[idx, "agent_consensus"]
                # Correct if consensus direction matches actual return direction
                correct = (
                    1.0 if (consensus > 0 and actual_return > 0)
                         or (consensus < 0 and actual_return < 0)
                    else 0.0
                )
                df.at[idx, "top_agent_correct"] = correct
                updated += 1

            if updated:
                _save(symbol, df)

        return updated

    def get_recent_window(self, symbol: str, T: int = 10) -> Optional[np.ndarray]:
        """
        Return the most recent T snapshots as a (C, T) float array where
        C = 10 (6 source + 2 agent + 2 RV channels).

        Old Parquet files without agent/RV/iv_rv columns return zeros for those channels.
        Returns None if fewer than 3 snapshots exist (insufficient context).
        """
        df = _load(symbol)
        if len(df) < 3:
            return None

        recent = df.tail(T)

        # Source channels — zero-fill when a column is absent (old Parquet files)
        src_parts = []
        for col in SOURCE_COLUMNS:
            if col in df.columns:
                src_parts.append(recent[col].values.astype(float).reshape(-1, 1))
            else:
                src_parts.append(np.zeros((len(recent), 1)))
        source_data = np.hstack(src_parts)                           # (≤T, 6)

        # Agent channels — zero-fill when columns are absent (old files)
        agent_parts = []
        for col in AGENT_COLUMNS:
            if col in df.columns:
                agent_parts.append(recent[col].values.astype(float).reshape(-1, 1))
            else:
                agent_parts.append(np.zeros((len(recent), 1)))
        agent_data = np.hstack(agent_parts)                          # (≤T, 2)

        # RV channels — zero-fill when columns are absent (old files)
        rv_parts = []
        for col in RV_COLUMNS:
            if col in df.columns:
                rv_parts.append(recent[col].values.astype(float).reshape(-1, 1))
            else:
                rv_parts.append(np.zeros((len(recent), 1)))
        rv_data = np.hstack(rv_parts)                                # (≤T, 2)

        combined = np.hstack([source_data, agent_data, rv_data])     # (≤T, 9)

        if len(combined) < T:
            pad      = np.zeros((T - len(combined), combined.shape[1]))
            combined = np.vstack([pad, combined])

        combined = np.nan_to_num(combined, nan=0.0)
        return combined.T   # (9, T)

    def symbols_with_data(self) -> List[str]:
        """List all symbols that have at least one snapshot on disk."""
        if not os.path.isdir(_HISTORY_DIR):
            return []
        return [
            f[:-8] for f in os.listdir(_HISTORY_DIR)
            if f.endswith(".parquet") and not f.startswith("__")
        ]

    def sample_count(self, symbol: Optional[str] = None) -> int:
        """Total rows with a known 1D outcome (across one or all symbols)."""
        return len(self.get_training_data(symbol))


# Module-level singleton
signal_history = SignalHistoryStore()
