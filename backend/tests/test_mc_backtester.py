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
                         "price": 100.0,            # placeholder; matches signal_history schema
                         "feature_x": rng.normal()})
    return pd.DataFrame(rows).set_index(["date", "symbol"])


def _tiny_history():
    """30 days x 2 symbols of synthetic data with all required channels.

    Module-level so both TestSmokeE2E and TestAggregation can reuse it.
    Uses 'price' (matches signal_history.get_training_data schema), not
    'close' (the synthetic-only column the original fixture had).
    """
    rng = np.random.default_rng(0)
    rows = []
    for day in range(30):
        for sym in ("AAPL", "MSFT"):
            rows.append({
                "date": day, "symbol": sym,
                "price": 100.0 + rng.normal(0, 1),
                "return_1d": rng.normal(0, 0.01),
                "analyst_score": rng.uniform(),
                "earnings_score": rng.normal(),
                "alpaca_score": rng.normal(),
                "yahoo_score": rng.normal(),
                "iv_rv_score": rng.normal(),
            })
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


class TestBacktestPortfolio(unittest.TestCase):
    """BacktestPortfolio mirrors Portfolio's surface but with no DB/file I/O."""

    def test_kelly_fraction_defaults_to_10pct_with_no_history(self):
        from data.mc_backtester import BacktestPortfolio
        p = BacktestPortfolio(starting_capital=100000.0)
        self.assertAlmostEqual(p.kelly_fraction(), 0.10)

    def test_unpnl_frac_returns_none_when_no_positions(self):
        from data.mc_backtester import BacktestPortfolio
        p = BacktestPortfolio(starting_capital=100000.0)
        self.assertIsNone(p.unpnl_frac({}))

    def test_execute_buy_then_total_value_reflects_position(self):
        from data.mc_backtester import BacktestPortfolio
        p = BacktestPortfolio(starting_capital=100000.0)
        p.execute_buy("AAPL", 10, 100.0)
        # cash 99000 + 10x$110 = 100100
        self.assertAlmostEqual(p.total_value({"AAPL": 110.0}), 100100.0)

    def test_execute_sell_realises_pnl(self):
        from data.mc_backtester import BacktestPortfolio
        p = BacktestPortfolio(starting_capital=100000.0)
        p.execute_buy("AAPL", 10, 100.0)
        p.execute_sell("AAPL", 10, 120.0)
        # 99000 + 1200 proceeds = 100200; realised PnL = $200
        self.assertEqual(len(p.trade_history), 2)
        self.assertEqual(p.trade_history[1].pnl, 200.0)


class TestBacktestAgent(unittest.IsolatedAsyncioTestCase):
    """_BacktestAgent inherits BaseAgent SELL helpers; analyse is no-op."""

    async def test_check_trailing_stops_callable_against_backtest_portfolio(self):
        from data.mc_backtester import BacktestPortfolio, _BacktestAgent
        p = BacktestPortfolio(starting_capital=100000.0)
        agent = _BacktestAgent("backtest", "stripped", portfolio_override=p)
        # No positions -> no exits
        exits = await agent._check_trailing_stops({})
        self.assertEqual(exits, [])

    async def test_analyze_returns_empty_list(self):
        from data.mc_backtester import BacktestPortfolio, _BacktestAgent
        p = BacktestPortfolio(starting_capital=100000.0)
        agent = _BacktestAgent("backtest", "stripped", portfolio_override=p)
        result = await agent.analyze({})
        self.assertEqual(result, [])


class TestReplay(unittest.IsolatedAsyncioTestCase):
    """replay_one_path day-by-day simulation against a known synthetic path."""

    def _synthetic_one_symbol_path(self, n_days=30):
        """One symbol, monotonically rising → BUY signal should fire and profit.

        Uses 'price' (matches the column emitted by
        signal_history.get_training_data) — never 'close', which only ever
        existed in this synthetic fixture and masked Bug 1.
        """
        dates = list(range(n_days))
        rows = []
        for i, d in enumerate(dates):
            rows.append({
                "date": d, "symbol": "AAPL",
                "price": 100.0 * (1.0 + 0.001 * i),     # +0.1% per day
                "return_1d": 0.001,
                # Every channel cnn_model needs — for the smoke test, zeros suffice
                "analyst_score": 0.5, "earnings_score": 0.0,
                "alpaca_score": 0.0, "yahoo_score": 0.0,
                "iv_rv_score": 0.0,
            })
        return pd.DataFrame(rows).set_index(["date", "symbol"])

    async def test_replay_returns_pathoutcome(self):
        from data.mc_backtester import replay_one_path, PathOutcome, _FakeModel
        path = self._synthetic_one_symbol_path(n_days=30)
        model = _FakeModel(pred_return=0.05, direction="up", confidence=0.85)
        from config import config
        outcome = await replay_one_path(
            path=path, model=model, variant_name="test",
            sim_idx=0, starting_capital=100000.0, config=config,
        )
        self.assertIsInstance(outcome, PathOutcome)
        self.assertEqual(outcome.variant_name, "test")
        self.assertEqual(outcome.sim_idx, 0)
        self.assertGreater(outcome.n_trades, 0)   # at least one BUY fired

    async def test_replay_handles_zero_predictions(self):
        from data.mc_backtester import replay_one_path, _FakeModel
        from config import config
        path = self._synthetic_one_symbol_path(n_days=30)
        model = _FakeModel(pred_return=0.0, direction="neutral", confidence=0.10)
        outcome = await replay_one_path(
            path=path, model=model, variant_name="zero",
            sim_idx=0, starting_capital=100000.0, config=config,
        )
        self.assertEqual(outcome.n_trades, 0)   # no BUYs fired → no SELLs either
        self.assertAlmostEqual(outcome.final_return, 0.0)

    async def test_replay_uses_model_window_correctly(self):
        """Pins Bug 2 (1D vector) + Bug 3 (direction vocab) jointly.

        SignalXGBoost.predict returns "bull"/"bear"/"neutral" but decide_buy's
        Gate 1 requires "up". A _FakeModel emitting "bull" + high confidence on
        a path with >10 days of history MUST result in BUYs firing — proving
        both that the (C, T) window is being built (predict isn't shape-guarded
        out) and that direction is translated at the consumer boundary.

        Pre-fix this returned 0 trades because:
          - "bull" was passed through as-is → Gate 1 ("up") blocks (Bug 3), AND
          - real SignalXGBoost would have shape-guarded the 1D vector to
            (0.0, "neutral", 0.0) anyway (Bug 2).
        """
        from data.mc_backtester import replay_one_path, _FakeModel
        from config import config
        path = self._synthetic_one_symbol_path(n_days=30)  # >10 days
        # Use the production model's vocabulary ("bull") — translation must
        # convert this to "up" before passing to decide_buy.
        model = _FakeModel(pred_return=0.02, direction="bull", confidence=0.85)
        outcome = await replay_one_path(
            path=path, model=model, variant_name="bull",
            sim_idx=0, starting_capital=100000.0, config=config,
        )
        self.assertGreater(
            outcome.n_buys, 0,
            "BUYs failed to fire — direction translation or window shape broken",
        )


class TestAggregation(unittest.IsolatedAsyncioTestCase):
    # IsolatedAsyncioTestCase so the paired-comparison test can `await`.
    # Sync tests below still work — IsolatedAsyncioTestCase is a superset.

    def test_percentile_math_correct(self):
        from data.mc_backtester import PathOutcome, summarise
        outcomes = [
            PathOutcome(variant_name="A", sim_idx=i, sharpe=float(i)/10.0,
                        max_drawdown=-0.05*i, final_return=0.01*i,
                        n_trades=10, n_buys=5, n_sells=5, final_value=100000.0)
            for i in range(101)  # 0..100, so p5=5, p50=50, p95=95
        ]
        report = summarise(outcomes)
        self.assertIn("A", report.per_variant)
        stats = report.per_variant["A"]
        self.assertAlmostEqual(stats["sharpe_p5"],  0.5)
        self.assertAlmostEqual(stats["sharpe_p50"], 5.0)
        self.assertAlmostEqual(stats["sharpe_p95"], 9.5)

    def test_summarise_groups_by_variant(self):
        from data.mc_backtester import PathOutcome, summarise
        outcomes = (
            [PathOutcome("A", i, 0.5, -0.1, 0.05, 10, 5, 5, 105000.0) for i in range(20)] +
            [PathOutcome("B", i, 0.8, -0.08, 0.10, 12, 6, 6, 110000.0) for i in range(20)]
        )
        report = summarise(outcomes)
        self.assertEqual(set(report.per_variant.keys()), {"A", "B"})
        self.assertEqual(report.per_variant["A"]["n_simulations"], 20)
        self.assertEqual(report.per_variant["B"]["n_simulations"], 20)

    def test_render_markdown_produces_table(self):
        from data.mc_backtester import PathOutcome, summarise, render_markdown
        outcomes = [PathOutcome("A", i, 0.5, -0.1, 0.05, 10, 5, 5, 105000.0) for i in range(10)]
        report = summarise(outcomes)
        md = render_markdown(report)
        self.assertIn("| Variant ", md)         # header row
        self.assertIn("| A ", md)               # data row
        self.assertIn("Sharpe", md)             # has metric columns

    def test_write_jsonl_round_trip(self):
        import tempfile, json, os
        from data.mc_backtester import PathOutcome, write_jsonl
        outcomes = [PathOutcome("A", i, 0.5, -0.1, 0.05, 10, 5, 5, 105000.0) for i in range(3)]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            write_jsonl(outcomes, path)
            with open(path) as f:
                lines = [json.loads(line) for line in f]
            self.assertEqual(len(lines), 3)
            self.assertEqual(lines[0]["variant_name"], "A")
            self.assertEqual(lines[0]["sim_idx"], 0)
        finally:
            os.unlink(path)

    async def test_paired_comparison_same_path_for_all_variants(self):
        """run_variant_comparison must run every variant on the SAME bootstrap path.

        Two identical _FakeModels must produce identical PathOutcomes per sim —
        if not, the simulator is re-sampling per variant (paired comparison
        broken, kills statistical power for ranking variants).
        """
        from data.mc_backtester import (
            BootstrapConfig, FilterVariant, _FakeModel,
            run_variant_comparison,
        )
        from config import config
        hist = _tiny_history()
        variants = [
            FilterVariant(name="A", model=_FakeModel(0.02, "up", 0.80)),
            FilterVariant(name="B", model=_FakeModel(0.02, "up", 0.80)),  # identical
        ]
        cfg = BootstrapConfig(expected_block_size=5, n_paths=3, path_length_days=20, seed=0)
        _, outcomes = await run_variant_comparison(variants, hist, cfg, config=config)
        # Outcomes are ordered (sim 0 var A, sim 0 var B, sim 1 var A, ...)
        # Identical models on same path → identical outcomes
        for sim_idx in range(3):
            a = outcomes[sim_idx * 2 + 0]      # variant A
            b = outcomes[sim_idx * 2 + 1]      # variant B
            self.assertEqual(a.sim_idx, b.sim_idx)
            self.assertEqual(
                a.n_trades, b.n_trades,
                f"Sim {sim_idx}: variant A & B got DIFFERENT trade counts "
                f"({a.n_trades} vs {b.n_trades}) - paired comparison broken",
            )
            self.assertAlmostEqual(
                a.final_return, b.final_return, places=5,
                msg=f"Sim {sim_idx}: variants got different final returns - "
                "paired comparison broken",
            )


class TestSmokeE2E(unittest.IsolatedAsyncioTestCase):
    """End-to-end: 2 variants × 3 paths × 30 days × 2 symbols. Sanity check
    that everything wires up and produces a valid report."""

    async def test_full_pipeline_runs_to_completion(self):
        from data.mc_backtester import (
            BootstrapConfig, FilterVariant, _FakeModel,
            run_variant_comparison, render_markdown,
        )
        from config import config
        hist = _tiny_history()
        variants = [
            FilterVariant(name="A", model=_FakeModel(0.02, "up",   0.80)),
            FilterVariant(name="B", model=_FakeModel(0.01, "down", 0.30)),
        ]
        cfg = BootstrapConfig(
            expected_block_size=5, n_paths=3, path_length_days=20, seed=0,
        )
        report, outcomes = await run_variant_comparison(
            variants, hist, cfg, config=config,
        )
        # Sanity assertions
        self.assertEqual(report.n_variants, 2)
        self.assertEqual(report.n_simulations, 3)
        self.assertEqual(len(outcomes), 6)              # 2 variants × 3 paths
        self.assertIn("A", report.per_variant)
        self.assertIn("B", report.per_variant)
        md = render_markdown(report)
        self.assertIn("| A ", md)
        self.assertIn("| B ", md)


if __name__ == "__main__":
    unittest.main()
