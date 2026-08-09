"""Point-in-time daily bars for the re-selection backtest harness.

Reads the offline `data/history/*.parquet` snapshot cache and serves per-symbol
daily close/volume series sliced to an as-of date, with NO lookahead. The parquet
`price` column becomes daily `close` (last snapshot of the day); `volume` is that
day's last snapshot volume.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import pyarrow.parquet as pq

_REQUIRED_COLUMNS = {"snapshot_ts", "price", "volume"}

_DEFAULT_TRAILING_BARS = 504  # ~2 trading years; empirically reproduces live HistoricalTrendsAgent PnL to ~4% rel_err (Task 4 trust gate). 1260 (5yr) gave ~48%.


class BarsProvider:
    def __init__(self, history_dir: Path, trailing_bars: int = _DEFAULT_TRAILING_BARS):
        self._dir = Path(history_dir)
        self._trailing = trailing_bars
        self._cache: Dict[str, Optional[pd.DataFrame]] = {}

    def _daily(self, symbol: str) -> Optional[pd.DataFrame]:
        """Full daily close/volume series for a symbol (cached), ascending index."""
        if symbol not in self._cache:
            path = self._dir / f"{symbol}.parquet"
            # Stray/legacy cache files can predate the volume/return_10d schema
            # (e.g. a superseded INTEL.parquet alongside the live INTC.parquet).
            # Treat schema-incompatible files as "no data" rather than crashing
            # the whole directory-wide scan in trading_days().
            has_required_cols = (
                path.exists()
                and _REQUIRED_COLUMNS.issubset(pq.ParquetFile(path).schema_arrow.names)
            )
            if not has_required_cols:
                self._cache[symbol] = None
            else:
                raw = pd.read_parquet(path, columns=["snapshot_ts", "price", "volume"])
                raw = raw.dropna(subset=["price"])
                raw["dt"] = pd.to_datetime(raw["snapshot_ts"], unit="s")
                raw = raw.sort_values("dt")
                # Collapse to one row per calendar day: last snapshot wins.
                daily = raw.set_index("dt").resample("1D").last().dropna(subset=["price"])
                self._cache[symbol] = daily[["price", "volume"]].rename(columns={"price": "close"})
        return self._cache[symbol]

    def bars_asof(self, symbol: str, as_of: date) -> Optional[pd.DataFrame]:
        daily = self._daily(symbol)
        if daily is None:
            return None
        cutoff = pd.Timestamp(as_of) + pd.Timedelta(days=1)  # include all of as_of
        window = daily.loc[daily.index < cutoff]
        if window.empty:
            return None
        return window.iloc[-self._trailing:].copy()

    def close_asof(self, symbol: str, as_of: date) -> Optional[float]:
        window = self.bars_asof(symbol, as_of)
        if window is None or window.empty:
            return None
        return float(window["close"].iloc[-1])

    def trading_days(self, start: date, end: date) -> List[date]:
        days = set()
        for path in self._dir.glob("*.parquet"):
            symbol = path.stem
            if symbol.startswith("__"):        # skip __MACRO__ (invariant #8)
                continue
            daily = self._daily(symbol)
            if daily is None:
                continue
            for ts in daily.index:
                d = ts.date()
                if start <= d <= end:
                    days.add(d)
        return sorted(days)
