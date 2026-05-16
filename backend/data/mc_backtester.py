"""
MC strategy backtester — simulator, portfolio, replay, aggregator.

Compares candidate XGB filter variants by running each through K
bootstrapped alternate market histories. Loose-coupling boundary:
imports only narrow public surfaces of signal_model, signal_history,
cnn_decision, and BaseAgent — never CNNReasoningAgent or any I/O module.

See docs/superpowers/specs/2026-05-16-mc-strategy-design.md
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterator, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Path simulator (stationary block bootstrap, Politis-Romano 1994)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BootstrapConfig:
    """Hyperparameters for the simulator."""
    expected_block_size: int = 10        # L; mean of Geometric(1/L) block length
    n_paths: int = 1000                  # K; number of alternate histories
    path_length_days: int = 252          # T; trading days per path (1 year ≈ 252)
    seed: int = 42


class StationaryBlockBootstrap:
    """Stationary block bootstrap over (date × symbol)-indexed history.

    Bootstraps WHOLE ROWS jointly so a sampled block carries every symbol's
    every channel for the sampled dates — preserves cross-symbol AND
    cross-channel correlations within blocks. Block lengths are random
    (~Geometric(1/L)), so the path itself is a stationary process — no
    fixed seam pattern artefact.
    """

    def __init__(self, history: pd.DataFrame, cfg: BootstrapConfig):
        """history: long-format frame with MultiIndex (date, symbol)."""
        if not isinstance(history.index, pd.MultiIndex):
            raise ValueError("history must have a MultiIndex (date, symbol)")
        self._history = history.sort_index()
        self._cfg = cfg
        self._rng = np.random.default_rng(cfg.seed)
        # Unique sorted dates (the bootstrap unit)
        self._dates = list(self._history.index.get_level_values(0).unique())
        self._n_dates = len(self._dates)
        if self._n_dates < 1:
            raise ValueError("history must contain at least one date")

    def sample_path(self) -> pd.DataFrame:
        """Sample one bootstrapped path of length cfg.path_length_days.
        Returns long-format DataFrame with the same columns as `history`."""
        path_blocks: List[pd.DataFrame] = []
        days_remaining = self._cfg.path_length_days
        block_idx = 0
        while days_remaining > 0:
            start = int(self._rng.integers(0, self._n_dates))
            block_len = int(self._rng.geometric(1.0 / self._cfg.expected_block_size))
            block_len = max(1, min(block_len, days_remaining))
            # Wrap around so blocks near end of history stay full-length
            date_indices = [(start + offset) % self._n_dates for offset in range(block_len)]
            block_dates = [self._dates[i] for i in date_indices]
            block = self._history.loc[block_dates].copy()
            # Rewrite date index so the simulated path has unique, sequential
            # dates (block 0 starts at a synthetic day 0; subsequent blocks
            # follow). We use integers so callers don't infer real dates.
            synthetic_dates = list(range(block_idx, block_idx + block_len))
            # Note: block.loc[block_dates] returns rows in source-date order;
            # we re-key to synthetic_dates while preserving (date, symbol) shape
            block = block.reset_index()
            # Map original dates → synthetic dates row-by-row
            orig_date_order = block["date"].drop_duplicates().tolist()
            date_map = dict(zip(orig_date_order, synthetic_dates))
            block["date"] = block["date"].map(date_map)
            block = block.set_index(["date", "symbol"])
            path_blocks.append(block)
            block_idx += block_len
            days_remaining -= block_len
        return pd.concat(path_blocks)

    def simulate(self) -> Iterator[pd.DataFrame]:
        """Yield n_paths bootstrapped paths lazily (memory O(one path))."""
        for _ in range(self._cfg.n_paths):
            yield self.sample_path()
