"""Unit tests for mc_backtester — simulator first; portfolio + replay + aggregator added in later tasks."""
import sys
import os
import unittest

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np
import pandas as pd

from data.mc_backtester import BootstrapConfig, StationaryBlockBootstrap


def _synthetic_history(n_days=500, n_symbols=3, seed=0):
    """Multi-symbol daily returns frame; long-format MultiIndex (date, symbol)."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n_days, freq="B")
    symbols = [f"S{i}" for i in range(n_symbols)]
    rows = []
    for d in dates:
        for s in symbols:
            rows.append({"date": d, "symbol": s,
                         "return_1d": rng.normal(0.0005, 0.012),
                         "close": 100.0,            # placeholder
                         "feature_x": rng.normal()})
    return pd.DataFrame(rows).set_index(["date", "symbol"])


class TestStationaryBlockBootstrap(unittest.TestCase):

    def setUp(self):
        self.hist = _synthetic_history(n_days=500, n_symbols=3, seed=42)
        self.cfg = BootstrapConfig(
            expected_block_size=10, n_paths=20, path_length_days=100, seed=123
        )

    def test_one_path_has_correct_length(self):
        sampler = StationaryBlockBootstrap(self.hist, self.cfg)
        path = sampler.sample_path()
        unique_dates = path.index.get_level_values(0).unique()
        self.assertEqual(len(unique_dates), self.cfg.path_length_days)

    def test_one_path_preserves_symbol_set(self):
        sampler = StationaryBlockBootstrap(self.hist, self.cfg)
        path = sampler.sample_path()
        path_symbols = set(path.index.get_level_values(1).unique())
        hist_symbols = set(self.hist.index.get_level_values(1).unique())
        self.assertEqual(path_symbols, hist_symbols)

    def test_one_path_preserves_column_set(self):
        sampler = StationaryBlockBootstrap(self.hist, self.cfg)
        path = sampler.sample_path()
        self.assertEqual(set(path.columns), set(self.hist.columns))

    def test_simulate_yields_n_paths(self):
        sampler = StationaryBlockBootstrap(self.hist, self.cfg)
        paths = list(sampler.simulate())
        self.assertEqual(len(paths), self.cfg.n_paths)

    def test_seed_reproducibility(self):
        s1 = StationaryBlockBootstrap(self.hist, self.cfg)
        s2 = StationaryBlockBootstrap(self.hist, self.cfg)
        p1 = list(s1.simulate())
        p2 = list(s2.simulate())
        for a, b in zip(p1, p2):
            pd.testing.assert_frame_equal(a, b)

    def test_different_seeds_produce_different_paths(self):
        s1 = StationaryBlockBootstrap(self.hist, BootstrapConfig(seed=1, n_paths=2, path_length_days=50, expected_block_size=10))
        s2 = StationaryBlockBootstrap(self.hist, BootstrapConfig(seed=2, n_paths=2, path_length_days=50, expected_block_size=10))
        p1 = next(s1.simulate())
        p2 = next(s2.simulate())
        # At least some rows must differ
        self.assertFalse(p1.equals(p2))

    def test_cross_symbol_correlation_preserved_within_blocks(self):
        """If symbols had perfect correlation in the original (same series),
        the sampled blocks should preserve that — within-block correlation ≈ 1.0."""
        # Force perfect correlation: all symbols share the same return series
        n_days = 300
        dates = pd.date_range("2020-01-01", periods=n_days, freq="B")
        rng = np.random.default_rng(0)
        common_returns = rng.normal(0, 0.015, n_days)
        rows = []
        for i, d in enumerate(dates):
            for s in ("S0", "S1", "S2"):
                rows.append({"date": d, "symbol": s, "return_1d": common_returns[i]})
        hist = pd.DataFrame(rows).set_index(["date", "symbol"])
        cfg = BootstrapConfig(expected_block_size=20, n_paths=1, path_length_days=200, seed=0)
        sampler = StationaryBlockBootstrap(hist, cfg)
        path = sampler.sample_path()
        # Pivot to wide and check S0 == S1 == S2 for every row
        wide = path["return_1d"].unstack()  # date × symbol
        self.assertTrue((wide["S0"] == wide["S1"]).all())
        self.assertTrue((wide["S1"] == wide["S2"]).all())


if __name__ == "__main__":
    unittest.main()
