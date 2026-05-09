"""Tests for data/signal_history.py — return feature augmentation."""
import unittest

import numpy as np


class TestComputeReturnFeatures(unittest.TestCase):
    """Lagged log-return feature builder — Tier 1 from
    docs/equity_feature_engineering_audit.md."""

    def _make_df(self, prices, symbol="AAPL"):
        import pandas as pd
        return pd.DataFrame({
            "symbol":      [symbol] * len(prices),
            "snapshot_ts": np.arange(len(prices), dtype=np.float64) * 86400.0,
            "price":       np.asarray(prices, dtype=np.float64),
        })

    def test_adds_five_return_columns(self):
        from data.signal_history import _compute_return_features, RETURN_COLUMNS
        df = self._make_df([100.0] * 200)  # flat prices
        out = _compute_return_features(df)
        for col in RETURN_COLUMNS:
            self.assertIn(col, out.columns)

    def test_log_return_math_correct(self):
        """r_5 at row N = log(price[N] / price[N-5])."""
        from data.signal_history import _compute_return_features
        prices = np.linspace(100.0, 200.0, 200)
        df = self._make_df(prices)
        out = _compute_return_features(df)
        # Pick row 50 — five rows back is row 45
        expected = float(np.log(prices[50] / prices[45]))
        self.assertAlmostEqual(float(out["r_5"].iloc[50]), expected, places=6)

    def test_first_n_rows_have_nan(self):
        """For r_5, the first 5 rows can't compute a 5-row lookback."""
        from data.signal_history import _compute_return_features
        prices = np.linspace(100.0, 200.0, 200)
        df = self._make_df(prices)
        out = _compute_return_features(df)
        self.assertTrue(out["r_5"].iloc[:5].isna().all())
        self.assertFalse(out["r_5"].iloc[5:].isna().any())

    def test_per_symbol_isolation(self):
        """Returns for AAPL must not leak into MSFT and vice versa."""
        from data.signal_history import _compute_return_features
        import pandas as pd
        df = pd.concat([
            self._make_df(np.linspace(100, 200, 100), symbol="AAPL"),
            self._make_df(np.linspace(300, 400, 100), symbol="MSFT"),
        ], ignore_index=True)
        out = _compute_return_features(df)
        # MSFT row 0 must be NaN for r_1 — there's no prior MSFT row, even though
        # the AAPL block above it has prices.
        msft = out[out["symbol"] == "MSFT"].reset_index(drop=True)
        self.assertTrue(np.isnan(msft["r_1"].iloc[0]))

    def test_returns_copy_not_inplace(self):
        """The helper must not mutate the caller's df."""
        from data.signal_history import _compute_return_features, RETURN_COLUMNS
        df = self._make_df([100.0] * 50)
        before_cols = set(df.columns)
        _compute_return_features(df)
        self.assertEqual(set(df.columns), before_cols,
                         "caller's df must keep its original columns")

    def test_handles_zero_or_negative_prices_safely(self):
        """log(price/0) is undefined — must not crash."""
        from data.signal_history import _compute_return_features
        df = self._make_df([100.0, 110.0, 0.0, 120.0, 130.0, 140.0, 150.0])
        out = _compute_return_features(df)
        # No exception raised. Resulting NaN/inf is fine — downstream zero-fills.
        self.assertEqual(len(out), 7)


class TestGetTrainingDataIncludesReturns(unittest.TestCase):
    """get_training_data must yield the 5 lagged-return columns alongside
    the existing source/agent/rv/macro columns."""

    def test_returns_columns_present(self):
        from data.signal_history import (
            signal_history, RETURN_COLUMNS,
        )
        from unittest.mock import patch
        import pandas as pd

        # Synthesise a small per-symbol df with enough rows for r_5
        rows = 50
        synthetic = pd.DataFrame({
            "symbol":          ["AAPL"] * rows,
            "snapshot_ts":     np.arange(rows, dtype=np.float64) * 86400.0,
            "analyst_score":   np.zeros(rows),
            "earnings_score":  np.zeros(rows),
            "alpaca_score":    np.zeros(rows),
            "yahoo_score":     np.zeros(rows),
            "iv_rv_score":     np.zeros(rows),
            "price":           np.linspace(100, 150, rows),
            "return_1d":       np.full(rows, 0.001),
            "return_5d":       np.full(rows, 0.005),
        })

        # Use the symbol-scoped variant — the unscoped get_training_data()
        # iterates os.listdir(_HISTORY_DIR), which is empty in CI but holds
        # 212 real parquets locally. The "scoped" path goes _load(sym) →
        # compute_features → returns df with r_* attached, deterministically
        # in either environment.
        with patch("data.signal_history._load", return_value=synthetic):
            df = signal_history.get_training_data(symbol="AAPL")

        for col in RETURN_COLUMNS:
            self.assertIn(col, df.columns,
                          f"get_training_data must include {col}")


class TestComputeDailyReturnFeatures(unittest.TestCase):
    """Sprint 0: daily-resampled lagged log returns. Where _compute_return_features
    shifts on the raw hourly grid, this resamples per-symbol prices to one row
    per trading day and shifts there — so r_120d is exactly 120 calendar days
    back, not '120 hourly snapshots' (~20 trading days).
    """

    def _hourly_df(self, n_days: int, symbol: str = "AAPL", start_price: float = 100.0):
        """Build a multi-day df with ~5 hourly snapshots per trading day.
        Close-of-day price progresses linearly so daily returns are easy to
        verify by hand."""
        import pandas as pd
        rows = []
        base_ts = 1_704_067_200.0   # 2024-01-01 00:00 UTC
        for d in range(n_days):
            for hr in range(5):
                # Per-day: 5 snapshots, prices monotonic, last (hr=4) is the
                # "close" — that's what the daily-resampler will keep.
                rows.append({
                    "symbol": symbol,
                    "snapshot_ts": base_ts + d * 86400 + hr * 3600,
                    "price":  start_price + d + hr * 0.1,
                })
        return pd.DataFrame(rows)

    def test_adds_six_daily_return_columns(self):
        from data.signal_history import _compute_daily_return_features, DAILY_RETURN_COLUMNS
        df = self._hourly_df(30)
        out = _compute_daily_return_features(df)
        for col in DAILY_RETURN_COLUMNS:
            self.assertIn(col, out.columns)

    def test_r_5d_math_is_log_of_close_over_close_5d_back(self):
        """For row at day D close, r_5d should equal log(close[D] / close[D-5])."""
        from data.signal_history import _compute_daily_return_features
        df = self._hourly_df(20)
        out = _compute_daily_return_features(df)
        # Close of day 10 is start_price + 10 + 0.4 = 110.4
        # Close of day 5 is start_price + 5 + 0.4 = 105.4
        # Expected r_5d at any row in day 10: log(110.4 / 105.4)
        expected = float(np.log(110.4 / 105.4))
        # Pick the close-of-day-10 row (hr=4)
        day10_close_idx = 10 * 5 + 4
        self.assertAlmostEqual(out["r_5d"].iloc[day10_close_idx], expected, places=4)

    def test_first_n_days_have_nan_for_r_nd(self):
        """r_5d on the first 5 calendar days has no 5-day prior, so all
        rows in those days are NaN."""
        from data.signal_history import _compute_daily_return_features
        df = self._hourly_df(15)
        out = _compute_daily_return_features(df)
        # Day 0..4 are within the first 5 calendar days → r_5d is NaN
        first_25_rows = out["r_5d"].iloc[:25]   # 5 days × 5 snapshots
        self.assertTrue(first_25_rows.isna().all(),
                        "rows in days 0-4 must be NaN for r_5d (no 5-day-prior data)")

    def test_all_hourly_rows_in_a_day_share_the_same_daily_return(self):
        """The forward-fill from daily back to hourly: every snapshot in a
        given trading day gets that day's r_*d value (broadcast)."""
        from data.signal_history import _compute_daily_return_features
        df = self._hourly_df(15)
        out = _compute_daily_return_features(df)
        # Day 10 (rows 50..54): all 5 snapshots should share the same r_5d
        day10_r5d = out["r_5d"].iloc[50:55].values
        self.assertEqual(len(set(day10_r5d.tolist())), 1,
                         "all hourly rows in a day must share the same r_5d")

    def test_per_symbol_isolation(self):
        """AAPL's daily returns must not leak into MSFT and vice versa."""
        from data.signal_history import _compute_daily_return_features
        import pandas as pd
        # AAPL with rising prices, MSFT with FALLING prices — same dates
        aapl = self._hourly_df(15, symbol="AAPL", start_price=100.0)
        msft = self._hourly_df(15, symbol="MSFT", start_price=200.0)
        msft["price"] = 200.0 - msft["price"] + 200.0   # invert: now decreasing
        df = pd.concat([aapl, msft], ignore_index=True)
        out = _compute_daily_return_features(df)
        aapl_out = out[out["symbol"] == "AAPL"]
        msft_out = out[out["symbol"] == "MSFT"]
        # AAPL's r_5d should be positive (rising), MSFT's negative (falling)
        # Pick day 10's close row
        self.assertGreater(aapl_out["r_5d"].iloc[50 + 4], 0)
        self.assertLess(msft_out["r_5d"].iloc[50 + 4], 0)

    def test_returns_copy_not_inplace(self):
        from data.signal_history import _compute_daily_return_features, DAILY_RETURN_COLUMNS
        df = self._hourly_df(10)
        before_cols = set(df.columns)
        _compute_daily_return_features(df)
        self.assertEqual(set(df.columns), before_cols,
                         "caller's df must not gain daily-return columns")
        for col in DAILY_RETURN_COLUMNS:
            self.assertNotIn(col, df.columns)

    def test_handles_missing_price_column(self):
        """If df has no price column, return df unchanged (don't crash)."""
        from data.signal_history import _compute_daily_return_features
        import pandas as pd
        df = pd.DataFrame({"symbol": ["A"] * 5, "snapshot_ts": np.arange(5, dtype=float) * 86400})
        out = _compute_daily_return_features(df)
        # Should not raise — and not add daily-return cols
        self.assertNotIn("r_1d", out.columns)


class TestComputeMomentumFeatures(unittest.TestCase):
    """Sprint 2-B: 12-1 momentum factor — cumulative return over the last 12
    months SKIPPING the most recent month (the classic Jegadeesh-Titman
    factor). Avoids the well-known short-term reversal effect that
    contaminates plain 12-month momentum.

    Computed as r_252d - r_20d (≈ 12-month log-return minus 1-month
    log-return = log(P[t-20] / P[t-252])). Pure subtraction of two
    daily-resampled return channels — no new data dependency.
    """

    def _df_with_daily_returns(self, r_252d_value, r_20d_value, n=10, symbol="AAPL"):
        """Build a minimal df with the two input columns already populated.
        We test the subtraction in isolation; the daily-return computation
        itself is covered by TestComputeDailyReturnFeatures."""
        import pandas as pd
        return pd.DataFrame({
            "symbol":      [symbol] * n,
            "snapshot_ts": np.arange(n, dtype=float) * 3600.0,
            "r_20d":       [r_20d_value] * n,
            "r_252d":      [r_252d_value] * n,
        })

    def test_adds_mom_12_1_column(self):
        from data.signal_history import _compute_momentum_features, MOMENTUM_COLUMNS
        df = self._df_with_daily_returns(0.30, 0.05)
        out = _compute_momentum_features(df)
        for col in MOMENTUM_COLUMNS:
            self.assertIn(col, out.columns)

    def test_mom_12_1_equals_r_252d_minus_r_20d(self):
        """Per Jegadeesh-Titman (1993): cumulative return t-12mo to t-1mo,
        skipping the most recent month. In log-return space that's
        r_252d - r_20d for any row."""
        from data.signal_history import _compute_momentum_features
        df = self._df_with_daily_returns(0.30, 0.05)
        out = _compute_momentum_features(df)
        for v in out["mom_12_1"]:
            self.assertAlmostEqual(v, 0.30 - 0.05, places=6)

    def test_negative_mom_12_1_when_recent_month_outperformed(self):
        """If the last month outpaced the full year (a classic reversal
        setup), mom_12_1 should be negative."""
        from data.signal_history import _compute_momentum_features
        df = self._df_with_daily_returns(0.05, 0.30)
        out = _compute_momentum_features(df)
        self.assertLess(out["mom_12_1"].iloc[0], 0)

    def test_nan_propagation_when_r_252d_missing(self):
        """Subtraction propagates NaN — early-life rows (no 252d history)
        must produce NaN, never 0 or a stale broadcast value."""
        from data.signal_history import _compute_momentum_features
        df = self._df_with_daily_returns(np.nan, 0.05)
        out = _compute_momentum_features(df)
        self.assertTrue(out["mom_12_1"].isna().all())

    def test_nan_propagation_when_r_20d_missing(self):
        from data.signal_history import _compute_momentum_features
        df = self._df_with_daily_returns(0.30, np.nan)
        out = _compute_momentum_features(df)
        self.assertTrue(out["mom_12_1"].isna().all())

    def test_returns_copy_not_inplace(self):
        """Caller's df must not gain mom_12_1 — we add to a fresh frame."""
        from data.signal_history import _compute_momentum_features, MOMENTUM_COLUMNS
        df = self._df_with_daily_returns(0.30, 0.05)
        before_cols = set(df.columns)
        _compute_momentum_features(df)
        self.assertEqual(set(df.columns), before_cols)
        for col in MOMENTUM_COLUMNS:
            self.assertNotIn(col, df.columns)

    def test_handles_missing_input_columns(self):
        """If r_252d or r_20d are absent (df from before Sprint 0), return
        df unchanged — don't crash, don't fabricate data."""
        from data.signal_history import _compute_momentum_features
        import pandas as pd
        df = pd.DataFrame({"symbol": ["A"] * 3, "snapshot_ts": np.arange(3, dtype=float)})
        out = _compute_momentum_features(df)
        self.assertNotIn("mom_12_1", out.columns)

    def test_per_symbol_isolation(self):
        """One symbol's mom_12_1 must not leak into another symbol's row."""
        from data.signal_history import _compute_momentum_features
        import pandas as pd
        aapl = self._df_with_daily_returns(0.30, 0.05, n=5, symbol="AAPL")
        msft = self._df_with_daily_returns(0.10, 0.20, n=5, symbol="MSFT")
        df = pd.concat([aapl, msft], ignore_index=True)
        out = _compute_momentum_features(df)
        aapl_mom = out[out["symbol"] == "AAPL"]["mom_12_1"]
        msft_mom = out[out["symbol"] == "MSFT"]["mom_12_1"]
        self.assertTrue((aapl_mom == 0.25).all())   # 0.30 - 0.05
        self.assertTrue((msft_mom == -0.10).all())  # 0.10 - 0.20


class TestComputeSectorRelativeFeatures(unittest.TestCase):
    """Sprint 3: cross-sectional sector-relative 20-day return —
    r_20d_sector_rel = r_20d - mean(r_20d for all symbols in the SAME GICS
    sector on the SAME UTC trading day).

    Captures relative-strength: a symbol's 1-month return vs its sector
    peers' 1-month return that same day. Captures the cross-section a
    single-symbol channel structurally cannot — Energy stocks all up 5% on
    an oil day looks like a non-event in r_20d but is correctly zeroed
    out in r_20d_sector_rel.

    Symbol-equal-weight: dedupe to one r_20d per (symbol, trading_day)
    before averaging, so a symbol with more hourly snapshots than another
    doesn't pull the sector mean.
    """

    def _df_with_r20d(self, rows):
        """Build a df from list-of-dicts. Each dict needs symbol,
        snapshot_ts, r_20d at minimum."""
        import pandas as pd
        return pd.DataFrame(rows)

    def test_adds_r_20d_sector_rel_column(self):
        from data.signal_history import _compute_sector_relative_features
        from unittest.mock import patch
        df = self._df_with_r20d([
            {"symbol": "AAPL", "snapshot_ts": 1_704_067_200.0, "r_20d": 0.10},
            {"symbol": "MSFT", "snapshot_ts": 1_704_067_200.0, "r_20d": 0.20},
        ])
        with patch("data.signal_history.get_sectors",
                   return_value={"AAPL": "Tech", "MSFT": "Tech"}):
            out = _compute_sector_relative_features(df)
        self.assertIn("r_20d_sector_rel", out.columns)

    def test_sector_relative_equals_r20d_minus_sector_day_mean(self):
        """Math: rel = r_20d − mean(sector r_20d on that day).
        AAPL=+10%, MSFT=+20% in same Tech sector on day D →
        sector mean = +15% → AAPL_rel = −5%, MSFT_rel = +5%."""
        from data.signal_history import _compute_sector_relative_features
        from unittest.mock import patch
        df = self._df_with_r20d([
            {"symbol": "AAPL", "snapshot_ts": 1_704_067_200.0, "r_20d": 0.10},
            {"symbol": "MSFT", "snapshot_ts": 1_704_067_200.0, "r_20d": 0.20},
        ])
        with patch("data.signal_history.get_sectors",
                   return_value={"AAPL": "Tech", "MSFT": "Tech"}):
            out = _compute_sector_relative_features(df)
        aapl = out[out["symbol"] == "AAPL"]["r_20d_sector_rel"].iloc[0]
        msft = out[out["symbol"] == "MSFT"]["r_20d_sector_rel"].iloc[0]
        self.assertAlmostEqual(aapl, -0.05, places=6)
        self.assertAlmostEqual(msft, +0.05, places=6)

    def test_per_sector_isolation(self):
        """Different sectors must NOT cross-contaminate. AAPL+MSFT in Tech
        on day D, XOM in Energy on day D — Tech mean uses only Tech
        symbols, Energy mean uses only Energy."""
        from data.signal_history import _compute_sector_relative_features
        from unittest.mock import patch
        df = self._df_with_r20d([
            {"symbol": "AAPL", "snapshot_ts": 1_704_067_200.0, "r_20d": 0.10},
            {"symbol": "MSFT", "snapshot_ts": 1_704_067_200.0, "r_20d": 0.20},
            {"symbol": "XOM",  "snapshot_ts": 1_704_067_200.0, "r_20d": 0.50},
        ])
        with patch("data.signal_history.get_sectors",
                   return_value={"AAPL": "Tech", "MSFT": "Tech", "XOM": "Energy"}):
            out = _compute_sector_relative_features(df)
        # XOM is alone in Energy → its sector mean = its own r_20d → relative = 0
        xom = out[out["symbol"] == "XOM"]["r_20d_sector_rel"].iloc[0]
        self.assertAlmostEqual(xom, 0.0, places=6)
        # Tech symbols centered around 0.15 mean
        aapl = out[out["symbol"] == "AAPL"]["r_20d_sector_rel"].iloc[0]
        self.assertAlmostEqual(aapl, -0.05, places=6)

    def test_per_day_isolation(self):
        """Different trading days must NOT cross-contaminate. AAPL day1
        r_20d=+10%, day2 r_20d=+30% → day1 sector_rel uses day1 mean only."""
        from data.signal_history import _compute_sector_relative_features
        from unittest.mock import patch
        d1 = 1_704_067_200.0   # 2024-01-01 UTC
        d2 = d1 + 86_400.0     # 2024-01-02 UTC
        df = self._df_with_r20d([
            {"symbol": "AAPL", "snapshot_ts": d1, "r_20d": 0.10},
            {"symbol": "MSFT", "snapshot_ts": d1, "r_20d": 0.20},
            {"symbol": "AAPL", "snapshot_ts": d2, "r_20d": 0.30},
            {"symbol": "MSFT", "snapshot_ts": d2, "r_20d": 0.50},
        ])
        with patch("data.signal_history.get_sectors",
                   return_value={"AAPL": "Tech", "MSFT": "Tech"}):
            out = _compute_sector_relative_features(df)
        # Day 1: mean(0.10, 0.20)=0.15 → AAPL=−0.05, MSFT=+0.05
        # Day 2: mean(0.30, 0.50)=0.40 → AAPL=−0.10, MSFT=+0.10
        d1_mask = out["snapshot_ts"] == d1
        d2_mask = out["snapshot_ts"] == d2
        aapl_d1 = out[d1_mask & (out["symbol"] == "AAPL")]["r_20d_sector_rel"].iloc[0]
        aapl_d2 = out[d2_mask & (out["symbol"] == "AAPL")]["r_20d_sector_rel"].iloc[0]
        self.assertAlmostEqual(aapl_d1, -0.05, places=6)
        self.assertAlmostEqual(aapl_d2, -0.10, places=6)

    def test_symbol_equal_weight_under_uneven_sampling(self):
        """A symbol with MORE hourly snapshots in a day must NOT pull the
        sector mean more than a symbol with fewer. Dedupe to one r_20d per
        (symbol, day) before averaging."""
        from data.signal_history import _compute_sector_relative_features
        from unittest.mock import patch
        d1 = 1_704_067_200.0
        # AAPL has 5 hourly rows (all r_20d=+10%), MSFT has 1 row (r_20d=+30%)
        rows = [{"symbol": "AAPL", "snapshot_ts": d1 + i*3600, "r_20d": 0.10}
                for i in range(5)]
        rows.append({"symbol": "MSFT", "snapshot_ts": d1, "r_20d": 0.30})
        df = self._df_with_r20d(rows)
        with patch("data.signal_history.get_sectors",
                   return_value={"AAPL": "Tech", "MSFT": "Tech"}):
            out = _compute_sector_relative_features(df)
        # If equal-weight: mean = (0.10+0.30)/2 = 0.20 → AAPL_rel=−0.10, MSFT_rel=+0.10
        # If snapshot-count-weighted (BUG): mean = (5*0.10+0.30)/6 ≈ 0.133 →
        #     AAPL_rel ≈ −0.033 — FAILS the equal-weight assertion below.
        aapl_rel = out[out["symbol"] == "AAPL"]["r_20d_sector_rel"].iloc[0]
        self.assertAlmostEqual(aapl_rel, -0.10, places=6)

    def test_solo_symbol_in_sector_yields_zero(self):
        """When a symbol is the only one in its sector on a given day, its
        sector mean equals its own r_20d → relative = 0."""
        from data.signal_history import _compute_sector_relative_features
        from unittest.mock import patch
        df = self._df_with_r20d([
            {"symbol": "TLT", "snapshot_ts": 1_704_067_200.0, "r_20d": 0.05},
        ])
        with patch("data.signal_history.get_sectors",
                   return_value={"TLT": "Financials"}):
            out = _compute_sector_relative_features(df)
        rel = out[out["symbol"] == "TLT"]["r_20d_sector_rel"].iloc[0]
        self.assertAlmostEqual(rel, 0.0, places=6)

    def test_nan_r_20d_propagates_to_nan_relative(self):
        """A symbol with NaN r_20d (early-life, no 20-day history) must
        produce NaN sector_rel, not a stale 0 broadcast."""
        from data.signal_history import _compute_sector_relative_features
        from unittest.mock import patch
        df = self._df_with_r20d([
            {"symbol": "AAPL", "snapshot_ts": 1_704_067_200.0, "r_20d": np.nan},
            {"symbol": "MSFT", "snapshot_ts": 1_704_067_200.0, "r_20d": 0.20},
        ])
        with patch("data.signal_history.get_sectors",
                   return_value={"AAPL": "Tech", "MSFT": "Tech"}):
            out = _compute_sector_relative_features(df)
        aapl = out[out["symbol"] == "AAPL"]["r_20d_sector_rel"].iloc[0]
        self.assertTrue(np.isnan(aapl))
        # MSFT's sector_rel is also NaN since its sector mean (computed
        # over MSFT alone since AAPL is NaN) equals MSFT itself → 0,
        # OR NaN if we skip-NaN — we want skip-NaN behavior so MSFT's
        # signal isn't lost.
        msft = out[out["symbol"] == "MSFT"]["r_20d_sector_rel"].iloc[0]
        self.assertAlmostEqual(msft, 0.0, places=6)  # MSFT alone in its valid-sample sector

    def test_returns_copy_not_inplace(self):
        from data.signal_history import _compute_sector_relative_features
        from unittest.mock import patch
        df = self._df_with_r20d([
            {"symbol": "AAPL", "snapshot_ts": 1_704_067_200.0, "r_20d": 0.10},
            {"symbol": "MSFT", "snapshot_ts": 1_704_067_200.0, "r_20d": 0.20},
        ])
        before_cols = set(df.columns)
        with patch("data.signal_history.get_sectors",
                   return_value={"AAPL": "Tech", "MSFT": "Tech"}):
            _compute_sector_relative_features(df)
        self.assertEqual(set(df.columns), before_cols)
        self.assertNotIn("r_20d_sector_rel", df.columns)

    def test_handles_missing_r_20d_column(self):
        """Pre-Sprint-0 df has no r_20d → return df unchanged, don't crash."""
        from data.signal_history import _compute_sector_relative_features
        import pandas as pd
        df = pd.DataFrame({"symbol": ["A"], "snapshot_ts": [1.0]})
        out = _compute_sector_relative_features(df)
        self.assertNotIn("r_20d_sector_rel", out.columns)

    def test_handles_get_sectors_failure(self):
        """If get_sectors raises (network error, yfinance down), return
        df unchanged — don't crash the pipeline."""
        from data.signal_history import _compute_sector_relative_features
        from unittest.mock import patch
        df = self._df_with_r20d([
            {"symbol": "AAPL", "snapshot_ts": 1_704_067_200.0, "r_20d": 0.10},
        ])
        with patch("data.signal_history.get_sectors",
                   side_effect=RuntimeError("yfinance down")):
            out = _compute_sector_relative_features(df)
        self.assertNotIn("r_20d_sector_rel", out.columns)


class TestComputeSpyCorrelationFeatures(unittest.TestCase):
    """Sprint 4: rolling 20-day correlation between symbol's r_1d and SPY's
    r_1d. Captures inter-asset comovement — a stock that decouples from
    SPY (low |corr|) is structurally different from one that tracks SPY.

    Computed by joining each (symbol, trading_day) row to the SPY r_1d
    for that same day, then `groupby(symbol).rolling(20).corr(spy_r_1d)`.
    Forward-filled to all hourly rows within a trading day.
    """

    def _hourly_df_pair(self, n_days, sym_returns, spy_returns):
        """Build a df with two symbols (one user-named + 'SPY'), n_days
        trading days, 5 hourly snapshots per day. r_1d is pre-populated
        from sym_returns / spy_returns (one value per day, broadcast to
        all 5 hourly rows of that day)."""
        import pandas as pd
        rows = []
        base_ts = 1_704_067_200.0   # 2024-01-01 00:00 UTC
        for sym, returns in (("AAPL", sym_returns), ("SPY", spy_returns)):
            for d in range(n_days):
                for hr in range(5):
                    rows.append({
                        "symbol":      sym,
                        "snapshot_ts": base_ts + d * 86400 + hr * 3600,
                        "r_1d":        returns[d],
                    })
        return pd.DataFrame(rows)

    def test_adds_corr_spy_20d_column(self):
        from data.signal_history import _compute_spy_correlation_features
        rng = np.random.default_rng(0)
        df = self._hourly_df_pair(
            30,
            sym_returns=rng.standard_normal(30) * 0.01,
            spy_returns=rng.standard_normal(30) * 0.01,
        )
        out = _compute_spy_correlation_features(df)
        self.assertIn("corr_spy_20d", out.columns)

    def test_first_19_days_are_nan_then_value_at_day_20(self):
        """Need at least 20 paired daily observations to compute a 20d
        correlation. Days 0..18 must be NaN; day 19 onward populated."""
        from data.signal_history import _compute_spy_correlation_features
        rng = np.random.default_rng(0)
        df = self._hourly_df_pair(
            25,
            sym_returns=rng.standard_normal(25) * 0.01,
            spy_returns=rng.standard_normal(25) * 0.01,
        )
        out = _compute_spy_correlation_features(df)
        aapl = out[out["symbol"] == "AAPL"].sort_values("snapshot_ts")
        # Day 0 close (5 hourly rows) — definitely NaN
        self.assertTrue(np.isnan(aapl["corr_spy_20d"].iloc[0]))
        # Day 19 close (row 19*5+4=99) — should have a value
        self.assertFalse(np.isnan(aapl["corr_spy_20d"].iloc[99]))

    def test_corr_matches_numpy_pearson(self):
        """corr_spy_20d at any populated row must equal numpy's Pearson
        correlation of the last 20 paired daily returns."""
        from data.signal_history import _compute_spy_correlation_features
        rng = np.random.default_rng(42)
        sym_r = rng.standard_normal(30) * 0.01
        spy_r = rng.standard_normal(30) * 0.01
        df = self._hourly_df_pair(30, sym_returns=sym_r, spy_returns=spy_r)
        out = _compute_spy_correlation_features(df)
        aapl = out[out["symbol"] == "AAPL"].sort_values("snapshot_ts")
        # At day 25 (close), the 20d window is days 6..25 inclusive (20 days)
        day25_close_idx = 25 * 5 + 4
        actual = aapl["corr_spy_20d"].iloc[day25_close_idx]
        expected = float(np.corrcoef(sym_r[6:26], spy_r[6:26])[0, 1])
        self.assertAlmostEqual(actual, expected, places=4)

    def test_spy_correlation_with_self_is_one(self):
        """SPY's row's own corr_spy_20d must be ~1.0 (perfect correlation
        with itself, modulo numerical precision)."""
        from data.signal_history import _compute_spy_correlation_features
        rng = np.random.default_rng(0)
        spy_r = rng.standard_normal(30) * 0.01
        df = self._hourly_df_pair(30, sym_returns=spy_r, spy_returns=spy_r)
        out = _compute_spy_correlation_features(df)
        spy_rows = out[out["symbol"] == "SPY"].sort_values("snapshot_ts")
        # Day 25 close — should be 1.0
        day25 = spy_rows["corr_spy_20d"].iloc[25 * 5 + 4]
        self.assertAlmostEqual(day25, 1.0, places=4)

    def test_perfectly_anti_correlated_returns_yield_minus_one(self):
        """If sym = -spy on every day, rolling corr = -1 across all
        populated windows (modulo numerical precision)."""
        from data.signal_history import _compute_spy_correlation_features
        rng = np.random.default_rng(0)
        spy_r = rng.standard_normal(30) * 0.01
        sym_r = -spy_r
        df = self._hourly_df_pair(30, sym_returns=sym_r, spy_returns=spy_r)
        out = _compute_spy_correlation_features(df)
        aapl = out[out["symbol"] == "AAPL"].sort_values("snapshot_ts")
        day25 = aapl["corr_spy_20d"].iloc[25 * 5 + 4]
        self.assertAlmostEqual(day25, -1.0, places=4)

    def test_all_hourly_rows_in_a_day_share_the_same_corr(self):
        """corr_spy_20d is daily — every hourly snapshot in the same
        trading day must have the same value (no intraday change)."""
        from data.signal_history import _compute_spy_correlation_features
        rng = np.random.default_rng(0)
        df = self._hourly_df_pair(
            25,
            sym_returns=rng.standard_normal(25) * 0.01,
            spy_returns=rng.standard_normal(25) * 0.01,
        )
        out = _compute_spy_correlation_features(df)
        aapl = out[out["symbol"] == "AAPL"].sort_values("snapshot_ts")
        # Day 22 (rows 110..114) — all 5 should share the same value
        day22 = aapl["corr_spy_20d"].iloc[22 * 5 : 22 * 5 + 5].values
        self.assertEqual(len(set(day22.tolist())), 1)

    def test_returns_all_nan_column_when_spy_absent(self):
        """If df has no SPY rows, the column is added but all NaN. Why
        not omit the column? Train/serve consistency: both paths' tensor
        composition needs the column to exist (it's zero-filled downstream).
        Omitting would make train=N-1 channels while serve zero-pads to N."""
        from data.signal_history import _compute_spy_correlation_features
        import pandas as pd
        rng = np.random.default_rng(0)
        # Build only AAPL rows (no SPY)
        rows = []
        base_ts = 1_704_067_200.0
        for d in range(25):
            for hr in range(5):
                rows.append({
                    "symbol": "AAPL", "snapshot_ts": base_ts + d*86400 + hr*3600,
                    "r_1d": rng.standard_normal() * 0.01,
                })
        df = pd.DataFrame(rows)
        out = _compute_spy_correlation_features(df)
        self.assertIn("corr_spy_20d", out.columns)
        self.assertTrue(out["corr_spy_20d"].isna().all(),
                        "expected all-NaN column when SPY is absent — must not fabricate values")

    def test_returns_copy_not_inplace(self):
        from data.signal_history import _compute_spy_correlation_features
        rng = np.random.default_rng(0)
        df = self._hourly_df_pair(
            10,
            sym_returns=rng.standard_normal(10) * 0.01,
            spy_returns=rng.standard_normal(10) * 0.01,
        )
        before_cols = set(df.columns)
        _compute_spy_correlation_features(df)
        self.assertEqual(set(df.columns), before_cols)
        self.assertNotIn("corr_spy_20d", df.columns)

    def test_handles_missing_r_1d_column(self):
        """Pre-Sprint-0 df has no r_1d → return df unchanged, don't crash."""
        from data.signal_history import _compute_spy_correlation_features
        import pandas as pd
        df = pd.DataFrame({"symbol": ["A"], "snapshot_ts": [1.0]})
        out = _compute_spy_correlation_features(df)
        self.assertNotIn("corr_spy_20d", out.columns)

    def test_per_symbol_isolation(self):
        """A second non-SPY symbol's corr_spy_20d must be computed against
        SPY only — not against AAPL."""
        from data.signal_history import _compute_spy_correlation_features
        import pandas as pd
        rng = np.random.default_rng(7)
        spy_r = rng.standard_normal(30) * 0.01
        # MSFT perfectly anti-correlated with SPY → corr=-1
        # AAPL identical to SPY → corr=+1
        rows = []
        base_ts = 1_704_067_200.0
        for sym, ret in (("AAPL", spy_r), ("MSFT", -spy_r), ("SPY", spy_r)):
            for d in range(30):
                for hr in range(5):
                    rows.append({"symbol": sym, "snapshot_ts": base_ts + d*86400 + hr*3600,
                                 "r_1d": ret[d]})
        df = pd.DataFrame(rows)
        out = _compute_spy_correlation_features(df)
        day25 = 25 * 5 + 4
        aapl = out[out["symbol"] == "AAPL"].sort_values("snapshot_ts")["corr_spy_20d"].iloc[day25]
        msft = out[out["symbol"] == "MSFT"].sort_values("snapshot_ts")["corr_spy_20d"].iloc[day25]
        self.assertAlmostEqual(aapl, +1.0, places=4)
        self.assertAlmostEqual(msft, -1.0, places=4)

    def test_handles_single_symbol_df_where_symbol_is_spy(self):
        """REGRESSION: when compute_features is called on a single-symbol
        slice where the symbol IS SPY (e.g. signal_history.get_training_data("SPY")
        called by auto-backfill at startup), groupby.apply returns a
        DataFrame instead of a Series in newer pandas because there's only
        one group. Without explicit per-group handling, this raised:

            ValueError: Cannot set a DataFrame with multiple columns to
            the single column corr_spy_20d

        which broke the live auto-backfill path (and got logged as a
        non-fatal warning) — preventing scanner / signal flow on every
        restart. Pin: SPY-only df must succeed and produce a corr_spy_20d
        column with the symbol's self-correlation (≈ 1.0)."""
        from data.signal_history import _compute_spy_correlation_features
        rng = np.random.default_rng(0)
        spy_r = rng.standard_normal(30) * 0.01
        import pandas as pd
        rows = []
        base_ts = 1_704_067_200.0
        for d in range(30):
            for hr in range(5):
                rows.append({"symbol": "SPY", "snapshot_ts": base_ts + d*86400 + hr*3600,
                             "r_1d": spy_r[d]})
        df = pd.DataFrame(rows)
        # Must NOT raise
        out = _compute_spy_correlation_features(df)
        self.assertIn("corr_spy_20d", out.columns)
        # SPY's self-correlation at any populated row ≈ 1.0
        spy_rows = out.sort_values("snapshot_ts")
        day25_close = spy_rows["corr_spy_20d"].iloc[25 * 5 + 4]
        self.assertAlmostEqual(day25_close, 1.0, places=4)

    def test_handles_single_symbol_df_where_symbol_is_not_spy(self):
        """Companion to the SPY-self-correlation case: AAPL-only df (no
        SPY rows) must take the all-NaN graceful path and not raise."""
        from data.signal_history import _compute_spy_correlation_features
        rng = np.random.default_rng(0)
        import pandas as pd
        rows = []
        base_ts = 1_704_067_200.0
        for d in range(30):
            for hr in range(5):
                rows.append({"symbol": "AAPL", "snapshot_ts": base_ts + d*86400 + hr*3600,
                             "r_1d": rng.standard_normal() * 0.01})
        df = pd.DataFrame(rows)
        out = _compute_spy_correlation_features(df)
        self.assertIn("corr_spy_20d", out.columns)
        self.assertTrue(out["corr_spy_20d"].isna().all())


class TestComputeHistoricalFeatures(unittest.TestCase):
    """#85: import HistoricalTrendsAgent's 4 sub-scores into XGB as channels.

    Adds HISTORICAL category to the catalog so XGB can learn the seasonal /
    channel-position / momentum-alignment / volume-pattern signals that have
    made HistoricalTrendsAgent the top performer (+$25k unrealized as of
    2026-05-08). Channel count 29 → 33.

    Computed at read-time by signal_history._compute_historical_features.
    Mirrors the math from agents/historical_trends_agent.py exactly so XGB
    sees the SAME signals HT votes on, but as features it can combine
    non-linearly with its existing 8."""

    def _hourly_df(self, n_days, symbol="AAPL", start_price=100.0,
                   trend=0.0, with_volume=True, base_ts=None):
        """Build a multi-day df with 5 hourly snapshots per trading day.
        `trend` is per-day price drift; with_volume=False omits the column
        so we can test graceful-degrade behavior."""
        import pandas as pd
        rows = []
        if base_ts is None:
            base_ts = 1_704_067_200.0   # 2024-01-01 00:00 UTC (a Monday — January)
        for d in range(n_days):
            for hr in range(5):
                row = {
                    "symbol":      symbol,
                    "snapshot_ts": base_ts + d * 86400 + hr * 3600,
                    "price":       start_price + d * trend + hr * 0.05,
                }
                if with_volume:
                    # Volume rises on up-days (positive trend), falls on down
                    row["volume"] = 1_000_000 + (1 if trend >= 0 else -1) * 100_000
                rows.append(row)
        return pd.DataFrame(rows)

    # ── seasonal channel ──────────────────────────────────────────────

    def test_seasonal_channel_high_in_december(self):
        """Dec has +0.40 month bias; quarter-position bonus 0.0 mid-month
        and +0.15 in last half. Expect a clearly positive seasonal score."""
        from data.signal_history import _compute_historical_features
        # 2024-12-01 = Sunday. Use 2024-12-15 onwards (last half of Q4 → quarter bonus +0.15).
        # ts for 2024-12-15 00:00 UTC = 1734220800
        df = self._hourly_df(5, base_ts=1_734_220_800.0)
        out = _compute_historical_features(df)
        # December bias 0.40 + quarter bonus 0.15 = 0.55 (clipped to 1.0 if applicable)
        # Function output is in [-1, +1]; expect strongly positive.
        self.assertGreater(out["hist_seasonal"].iloc[0], 0.30)

    def test_seasonal_channel_low_in_september(self):
        """Sep has the most-negative month bias (−0.30). No quarter bonus
        in early September. Expect a clearly negative seasonal score."""
        from data.signal_history import _compute_historical_features
        # 2024-09-05 00:00 UTC = 1725494400 (early Sep, no quarter bonus)
        df = self._hourly_df(3, base_ts=1_725_494_400.0)
        out = _compute_historical_features(df)
        self.assertLess(out["hist_seasonal"].iloc[0], -0.20)

    def test_seasonal_channel_quarter_position_bonus(self):
        """Last 6 weeks of a quarter (third month, day >= 15) get +0.15
        quarter-position bonus on top of the month bias."""
        from data.signal_history import _compute_historical_features
        # 2024-03-25 = late March = month_in_quarter=3, day>=15 → +0.15 bonus
        # March base bias = +0.10; expect ~+0.25 total
        df1 = self._hourly_df(2, base_ts=1_711_324_800.0)   # 2024-03-25 00:00Z
        # 2024-03-05 = early March (no bonus); expect just +0.10 month bias
        df2 = self._hourly_df(2, base_ts=1_709_596_800.0)   # 2024-03-05 00:00Z
        out1 = _compute_historical_features(df1)
        out2 = _compute_historical_features(df2)
        self.assertGreater(out1["hist_seasonal"].iloc[0],
                           out2["hist_seasonal"].iloc[0],
                           "End-of-quarter window-dressing bonus must lift score")

    # ── channel-position channel ──────────────────────────────────────

    def test_channel_position_at_period_low_yields_positive(self):
        """When current price is at the period low (position=0), raw signal
        is (0.5 - 0) * 2 = +1.0. Expect strongly positive."""
        from data.signal_history import _compute_historical_features
        # Build a 60-day window where day-0 has the highest price and the
        # final day has the lowest (downtrend, last bar at the low)
        df = self._hourly_df(60, start_price=200.0, trend=-2.0)
        out = _compute_historical_features(df)
        # Final row should be at/near the channel low → positive channel score
        self.assertGreater(out["hist_channel_position"].iloc[-1], 0.5)

    def test_channel_position_at_period_high_yields_negative(self):
        """Mirror image: final price at period high → negative channel score."""
        from data.signal_history import _compute_historical_features
        df = self._hourly_df(60, start_price=100.0, trend=+2.0)
        out = _compute_historical_features(df)
        # Final row at the channel high → negative channel position score
        # (trend adjustment may moderate but not flip in this simple linear case)
        self.assertLess(out["hist_channel_position"].iloc[-1], 0.5)

    # ── momentum-alignment channel ────────────────────────────────────

    def test_momentum_alignment_all_bullish_yields_positive(self):
        """Strong sustained uptrend → all 4 timeframes (5d/10d/20d/40d) agree
        bullish → momentum score plus +0.20 alignment bonus."""
        from data.signal_history import _compute_historical_features
        df = self._hourly_df(60, start_price=100.0, trend=+1.5)   # +1.5/day, sustained
        out = _compute_historical_features(df)
        # Final row: all timeframes are looking back at lower prices → positive
        self.assertGreater(out["hist_momentum_alignment"].iloc[-1], 0.20)

    def test_momentum_alignment_all_bearish_yields_negative(self):
        """Sustained downtrend → all 4 timeframes agree bearish → negative
        score + −0.20 misalignment bonus."""
        from data.signal_history import _compute_historical_features
        df = self._hourly_df(60, start_price=200.0, trend=-1.5)
        out = _compute_historical_features(df)
        self.assertLess(out["hist_momentum_alignment"].iloc[-1], -0.20)

    def test_momentum_alignment_neutral_when_returns_split(self):
        """When 2 of 4 lookback windows are positive and 2 are negative,
        alignment is exactly 50% — neither +0.20 nor −0.20 bonus fires —
        and the score reflects only the small weighted ROC.

        (Note: an EXACT-zero-return fixture triggers HT's alignment
        penalty because the strict `r > 0` count comes out to 0/4 → −0.20.
        That's faithful to HT's existing math; this test instead exercises
        the 'mixed signals' case where alignment is balanced.)"""
        from data.signal_history import _compute_historical_features
        import pandas as pd
        # Build a series where the last bar (row 60) is HIGHER than the
        # 5- and 10-bars-ago prices (so r_5, r_10 > 0) but LOWER than the
        # 20- and 40-bars-ago prices (r_20, r_40 < 0). That's 2/4 positive
        # → alignment 50% → neither +0.20 nor −0.20 bonus fires.
        prices = []
        for i in range(61):
            if i < 30:        prices.append(110.0)   # earlier high range
            elif i < 50:      prices.append(100.0)   # mid trough
            else:             prices.append(105.0)   # recent recovery (above mid, below earlier)
        rows = [
            {"symbol": "AAPL", "snapshot_ts": 1_704_067_200.0 + i * 3600, "price": p}
            for i, p in enumerate(prices)
        ]
        df = pd.DataFrame(rows)
        out = _compute_historical_features(df)
        score = out["hist_momentum_alignment"].iloc[-1]
        # Score should be moderate — neither hit by the +0.20 alignment
        # bonus nor the −0.20 misalignment penalty.
        self.assertGreater(score, -0.20)
        self.assertLess(score, +0.20)

    # ── volume-pattern channel (graceful degrade) ─────────────────────

    def test_volume_pattern_zero_when_volume_column_absent(self):
        """The per-symbol parquet doesn't store volume historically. The
        helper must NOT crash — it should set hist_volume_pattern to 0
        and let the model treat it as a no-op signal."""
        from data.signal_history import _compute_historical_features
        df = self._hourly_df(20, with_volume=False)
        out = _compute_historical_features(df)
        self.assertIn("hist_volume_pattern", out.columns)
        self.assertTrue((out["hist_volume_pattern"] == 0.0).all(),
                        "missing volume column → channel must be all-zero, not NaN or omitted")

    # ── general invariants ────────────────────────────────────────────

    def test_all_four_columns_added(self):
        from data.signal_history import _compute_historical_features, HISTORICAL_COLUMNS
        df = self._hourly_df(60, trend=+1.0)
        out = _compute_historical_features(df)
        for col in HISTORICAL_COLUMNS:
            self.assertIn(col, out.columns)

    def test_returns_copy_not_inplace(self):
        from data.signal_history import _compute_historical_features, HISTORICAL_COLUMNS
        df = self._hourly_df(20, trend=+1.0)
        before_cols = set(df.columns)
        _compute_historical_features(df)
        self.assertEqual(set(df.columns), before_cols)
        for col in HISTORICAL_COLUMNS:
            self.assertNotIn(col, df.columns)

    def test_handles_missing_price_column(self):
        """If df has no price column, return df unchanged. Don't crash."""
        from data.signal_history import _compute_historical_features
        import pandas as pd
        df = pd.DataFrame({"symbol": ["A"] * 5,
                           "snapshot_ts": np.arange(5, dtype=float) * 86400.0})
        out = _compute_historical_features(df)
        self.assertNotIn("hist_seasonal", out.columns)

    def test_score_bounds_respected(self):
        """All 4 channels must produce values in [-1, +1] (the 4th
        is volume which is capped at ±0.15 per HT spec)."""
        from data.signal_history import _compute_historical_features
        df = self._hourly_df(60, start_price=100.0, trend=+5.0)   # extreme uptrend
        out = _compute_historical_features(df)
        for col in ("hist_seasonal", "hist_channel_position", "hist_momentum_alignment"):
            vals = out[col].dropna()
            self.assertTrue((vals >= -1.0).all() and (vals <= 1.0).all(),
                            f"{col} out of [-1, +1]: range={vals.min()} .. {vals.max()}")
        vol_vals = out["hist_volume_pattern"].dropna()
        self.assertTrue((vol_vals >= -0.15).all() and (vol_vals <= 0.15).all(),
                        f"hist_volume_pattern out of [-0.15, +0.15]: "
                        f"range={vol_vals.min()} .. {vol_vals.max()}")


class TestGetRecentWindowReturns33Channels(unittest.TestCase):
    """get_recent_window must return a (33, T) array matching training shape:
    5 source + 2 agent + 2 rv + 5 hourly returns + 6 macro + 6 daily returns
    + 1 momentum + 1 sector-relative + 1 SPY correlation + 4 historical
    (option C added HISTORICAL category from HistoricalTrendsAgent)."""

    def test_recent_window_has_33_rows(self):
        from data.signal_history import signal_history
        from unittest.mock import patch
        import pandas as pd

        # Need at least T+max_lag=10+120=130 rows for full r_120 coverage,
        # but the helper handles partial coverage with NaN→0 fill.
        rows = 130
        synthetic = pd.DataFrame({
            "symbol":          ["AAPL"] * rows,
            "snapshot_ts":     np.arange(rows, dtype=np.float64) * 86400.0,
            "analyst_score":   np.zeros(rows),
            "earnings_score":  np.zeros(rows),
            "alpaca_score":    np.zeros(rows),
            "yahoo_score":     np.zeros(rows),
            "iv_rv_score":     np.zeros(rows),
            "agent_consensus": np.zeros(rows),
            "agent_agreement": np.zeros(rows),
            "rv_20d":          np.full(rows, 0.20),
            "rv_60d":          np.full(rows, 0.20),
            "price":           np.linspace(100, 150, rows),
            "return_1d":       np.full(rows, 0.001),
            "return_5d":       np.full(rows, 0.005),
        })
        with patch("data.signal_history._load", return_value=synthetic):
            window = signal_history.get_recent_window("AAPL", T=10)

        self.assertIsNotNone(window, "window must not be None for 130-row symbol")
        self.assertEqual(window.shape, (33, 10),
                         f"expected (33, 10), got {window.shape}")


class TestReturn10dSchema(unittest.IsolatedAsyncioTestCase):
    """return_10d as a first-class outcome alongside return_1d and return_5d.
    Required for the 10d label-horizon switch (XGBoost ablation showed
    10d 8-channel produces mean_IC=+0.40, last_WFE=+0.25 vs 5d's +0.21/+0.07)."""

    def test_return_10d_in_dtype_map(self):
        """The persistence schema must declare return_10d so existing
        parquets pick up the column on next write/read."""
        from data.signal_history import _DTYPE_MAP
        self.assertIn("return_10d", _DTYPE_MAP,
                      "_DTYPE_MAP must declare return_10d alongside return_1d/return_5d")
        self.assertEqual(_DTYPE_MAP["return_10d"], "float64")

    async def test_record_snapshot_writes_return_10d_nan(self):
        """A freshly recorded snapshot has return_10d=NaN — we don't know
        the future yet."""
        import tempfile, os, pandas as pd
        from unittest.mock import patch
        from data.signal_history import SignalHistoryStore

        with tempfile.TemporaryDirectory() as td:
            with patch("data.signal_history._HISTORY_DIR", td):
                store = SignalHistoryStore()
                await store.record_snapshot(
                    symbol="AAPL",
                    scores={"analyst_recommendations": 0.5},
                    composite_score=0.3,
                    price=100.0,
                    rv_20d=0.20,
                    rv_60d=0.25,
                )
                df = pd.read_parquet(os.path.join(td, "AAPL.parquet"))
                self.assertIn("return_10d", df.columns,
                              "record_snapshot must persist return_10d column")
                self.assertTrue(pd.isna(df["return_10d"].iloc[0]),
                                "return_10d must be NaN at write time")

    async def test_update_outcomes_fills_return_10d_after_10_days(self):
        """update_outcomes must populate return_10d for any snapshot
        whose 10-day window has elapsed."""
        import tempfile, os, time, pandas as pd
        from unittest.mock import patch
        from data.signal_history import SignalHistoryStore, _DTYPE_MAP

        with tempfile.TemporaryDirectory() as td:
            with patch("data.signal_history._HISTORY_DIR", td):
                # Build a parquet with one snapshot 11 days old; price=100.
                # Return columns intentionally start NaN.
                eleven_days_ago = time.time() - 11 * 86_400
                # Use full _DTYPE_MAP columns so the round-trip preserves dtypes
                row = {col: pd.NA for col in _DTYPE_MAP}
                row.update({
                    "symbol":     "AAPL",
                    "snapshot_ts": eleven_days_ago,
                    "price":      100.0,
                })
                df = pd.DataFrame([row])
                df.to_parquet(os.path.join(td, "AAPL.parquet"), index=False)

                store = SignalHistoryStore()
                # Current price is 110 → 10% return
                updated = await store.update_outcomes(symbol="AAPL", current_price=110.0)
                self.assertGreater(updated, 0)

                df_after = pd.read_parquet(os.path.join(td, "AAPL.parquet"))
                self.assertIn("return_10d", df_after.columns)
                self.assertAlmostEqual(
                    float(df_after["return_10d"].iloc[0]), 0.10, places=4,
                    msg="11-day-old snapshot should have return_10d ≈ +10%",
                )


class TestComputeFeaturesSingleEntryPoint(unittest.TestCase):
    """Pipeline Stage 6 (per docs/feature_engineering_pipeline.md): training
    and serving must use the *same* feature computation. The doc names this
    as the highest-leverage architectural property — train-serve skew is
    the single most common silent failure mode in hobbyist quant systems.

    compute_features(df) is the single entry point. get_training_data and
    get_recent_window both delegate to it.
    """

    def test_compute_features_exists_and_is_callable(self):
        """The single entry point must exist with the canonical signature."""
        from data.signal_history import compute_features
        # Pure function — accepts a df, returns a df, no side effects
        import pandas as pd
        empty = pd.DataFrame({"symbol": [], "snapshot_ts": []})
        out = compute_features(empty)
        self.assertIsInstance(out, pd.DataFrame)

    def test_compute_features_applies_canonical_transforms(self):
        """compute_features applies all three transforms in fixed order:
            1. _apply_cnn_feature_transforms (abs(earnings_score))
            2. _compute_return_features (r_1..r_120)
            3. _attach_macro_features (macro_*)
        """
        import pandas as pd
        from data.signal_history import compute_features, RETURN_COLUMNS
        rows = 130   # enough for r_120
        df = pd.DataFrame({
            "symbol":          ["AAPL"] * rows,
            "snapshot_ts":     np.arange(rows, dtype=np.float64) * 86400.0,
            "earnings_score":  np.full(rows, -0.5),   # signed; expect abs after transform
            "price":           np.linspace(100, 150, rows),
        })
        out = compute_features(df)

        # 1. abs(earnings_score) was applied
        self.assertTrue((out["earnings_score"] >= 0).all(),
                        "compute_features must apply abs(earnings_score)")
        # 2. r_120 was added
        for col in RETURN_COLUMNS:
            self.assertIn(col, out.columns,
                          f"compute_features must add lagged return column {col}")
        # 3. r_120 has values past row 120 (and NaN before)
        self.assertTrue(out["r_120"].iloc[125:].notna().all())
        self.assertTrue(out["r_120"].iloc[:120].isna().all())

    def test_train_and_serve_paths_produce_identical_channel_values(self):
        """The headline test: run the SAME synthesized history through both
        the training path (get_training_data → build_training_windows → compose)
        and the serving path (get_recent_window) — for the same (symbol, ts)
        the 19 channel values must be identical.

        This pins train-serve consistency: any future refactor that diverges
        the two code paths will fail this test.
        """
        import pandas as pd
        from unittest.mock import patch
        from data.signal_history import signal_history
        from data.cnn_model import build_training_windows, ALL_CHANNEL_COLUMNS, WINDOW_SIZE

        rows = 130   # enough for r_120 lookback
        # Pre-fill all 5 macro columns. _attach_macro_features is a no-op
        # when __MACRO__.parquet doesn't exist (CI's bare _HISTORY_DIR);
        # without these prefilled, build_training_windows would produce 14
        # channels (no macro) while get_recent_window zero-pads to 19,
        # causing a shape mismatch in CI but not locally.
        # Sprint 4: corr_spy_20d would normally need SPY in the df, but
        # _compute_spy_correlation_features writes an all-NaN column when
        # SPY is absent — keeping shape consistent between train and serve.
        synthetic = pd.DataFrame({
            "symbol":             ["AAPL"] * rows,
            "snapshot_ts":        np.arange(rows, dtype=np.float64) * 86400.0,
            "analyst_score":      np.linspace(-0.1, 0.1, rows),
            "earnings_score":     np.linspace(-0.5, 0.5, rows),
            "alpaca_score":       np.linspace(-0.2, 0.2, rows),
            "yahoo_score":        np.linspace(-0.3, 0.3, rows),
            "iv_rv_score":        np.linspace(-0.05, 0.05, rows),
            "agent_consensus":    np.linspace(-0.4, 0.4, rows),
            "agent_agreement":    np.linspace(0.0, 1.0, rows),
            "rv_20d":             np.linspace(0.10, 0.30, rows),
            "rv_60d":             np.linspace(0.12, 0.28, rows),
            "price":              np.linspace(100.0, 150.0, rows),
            "return_1d":          np.full(rows, 0.001),
            "return_5d":          np.full(rows, 0.005),
            "return_10d":         np.full(rows, 0.010),
            # Macro cols — values deterministic per row so the train/serve
            # comparison is well-defined regardless of macro file presence.
            "macro_vix_norm":     np.linspace(0.5, 0.7, rows),
            "macro_gld_5d_back":  np.linspace(-0.01, 0.01, rows),
            "macro_tlt_5d_back":  np.linspace(-0.005, 0.005, rows),
            "macro_spy_5d_back":  np.linspace(0.0, 0.02, rows),
            "macro_breadth_back": np.linspace(-0.005, 0.005, rows),
            "macro_dji_5d_back":  np.linspace(0.0, 0.02, rows),  # 2026-05-09 (#84)
        })

        # Mock _load_macro_features to None so _attach_macro_features is a
        # no-op (otherwise it merges __MACRO__.parquet on top of our
        # pre-filled macro cols, producing _x/_y suffix collisions and
        # losing has_macro=True). With None, both paths use the synthetic
        # macros as-is.
        with patch("data.signal_history._load", return_value=synthetic), \
             patch("data.signal_history._load_macro_features", return_value=None):
            # ── Serving path: get_recent_window ────────────────────────
            window = signal_history.get_recent_window("AAPL", T=WINDOW_SIZE)
            self.assertIsNotNone(window)
            # option C: post-historical shape (29 + 4 hist sub-scores = 33)
            self.assertEqual(window.shape, (33, WINDOW_SIZE))

            # ── Training path: get_training_data → build_training_windows
            # Symbol-scoped variant — unscoped iterates os.listdir which is
            # 212 real files locally vs empty in CI.
            df_trained = signal_history.get_training_data(symbol="AAPL")
        X, _y, _w, _t = build_training_windows(df_trained, T=WINDOW_SIZE)
        self.assertGreater(len(X), 0)
        # The serving path's window corresponds to the LAST training window
        # for this symbol — same input rows, same transforms.
        last_train_window = X[-1]   # (19, T)

        # ── Compare channel-by-channel ────────────────────────────────
        np.testing.assert_allclose(
            window, last_train_window,
            atol=1e-6, equal_nan=True,
            err_msg=("TRAIN-SERVE SKEW: get_recent_window and "
                     "build_training_windows produced different values for the "
                     "same input rows. compute_features() is supposed to be "
                     "the single entry point — check that both paths delegate "
                     "to it in the same order."),
        )


if __name__ == "__main__":
    unittest.main()
