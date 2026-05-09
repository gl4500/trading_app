"""
Unit tests for data/history_backfill.py

Covers: row generation, RV computation, return labelling,
        idempotency, Stooq fallback, and API endpoint.
"""
import asyncio
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# Disable yfinance for the whole module by default — it's the new primary
# data source in `_fetch_bars`, but tests should not hit the real Yahoo
# endpoint. Tests that need yfinance behavior patch `_fetch_bars_yfinance`
# directly (see TestBackfillFallback).
_yf_patcher = None

def setUpModule():
    global _yf_patcher
    _yf_patcher = patch("data.history_backfill._fetch_bars_yfinance",
                        new_callable=AsyncMock, return_value=pd.DataFrame())
    _yf_patcher.start()

def tearDownModule():
    if _yf_patcher is not None:
        _yf_patcher.stop()


def _make_bars(n: int = 120, start_price: float = 100.0) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame with realistic daily prices."""
    np.random.seed(42)
    closes = [start_price]
    for _ in range(n - 1):
        closes.append(closes[-1] * (1 + np.random.normal(0, 0.01)))
    closes = np.array(closes)
    now = pd.Timestamp.utcnow()
    timestamps = [now - pd.Timedelta(days=n - 1 - i) for i in range(n)]
    return pd.DataFrame({
        "timestamp": timestamps,
        "open":      closes * 0.999,
        "high":      closes * 1.005,
        "low":       closes * 0.995,
        "close":     closes,
        "volume":    np.random.randint(1_000_000, 10_000_000, size=n).astype(float),
    })


class TestBackfillRowGeneration(unittest.IsolatedAsyncioTestCase):

    async def test_returns_rows_added_per_symbol(self):
        """backfill_signal_history must return {symbol: rows_added} dict."""
        from data.history_backfill import backfill_signal_history
        bars = _make_bars(120)
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.history_backfill._HISTORY_DIR", tmpdir), \
             patch("data.history_backfill.alpaca_client") as mock_ac, \
             patch("data.history_backfill.stooq_client") as mock_sc:
            mock_ac.get_bars = AsyncMock(return_value=bars)
            result = await backfill_signal_history(["AAPL"], days=90)
        self.assertIn("AAPL", result)
        self.assertGreater(result["AAPL"], 0)

    async def test_parquet_file_created(self):
        """A Parquet file must be created for each symbol after backfill."""
        from data.history_backfill import backfill_signal_history
        bars = _make_bars(120)
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.history_backfill._HISTORY_DIR", tmpdir), \
             patch("data.history_backfill.alpaca_client") as mock_ac:
            mock_ac.get_bars = AsyncMock(return_value=bars)
            await backfill_signal_history(["AAPL"], days=90)
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "AAPL.parquet")))

    async def test_rows_have_required_columns(self):
        """Each backfill row must contain all CNN training columns."""
        from data.history_backfill import backfill_signal_history
        bars = _make_bars(120)
        required = {
            "symbol", "snapshot_ts", "price",
            "return_1d", "rv_20d", "rv_60d",
            "analyst_score", "earnings_score", "alpaca_score",
            "yahoo_score", "congress_score", "composite_score",
        }
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.history_backfill._HISTORY_DIR", tmpdir), \
             patch("data.history_backfill.alpaca_client") as mock_ac:
            mock_ac.get_bars = AsyncMock(return_value=bars)
            await backfill_signal_history(["AAPL"], days=90)
            df = pd.read_parquet(os.path.join(tmpdir, "AAPL.parquet"))
        self.assertTrue(required.issubset(set(df.columns)),
                        f"Missing columns: {required - set(df.columns)}")

    async def test_return_1d_computed_from_future_price(self):
        """return_1d = (close[t+1] - close[t]) / close[t] for each row."""
        from data.history_backfill import backfill_signal_history
        bars = _make_bars(60)
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.history_backfill._HISTORY_DIR", tmpdir), \
             patch("data.history_backfill.alpaca_client") as mock_ac:
            mock_ac.get_bars = AsyncMock(return_value=bars)
            await backfill_signal_history(["AAPL"], days=40)
            df = pd.read_parquet(os.path.join(tmpdir, "AAPL.parquet"))

        # All rows with a known next-bar should have non-NaN return_1d
        # (last row has no next bar → NaN is expected)
        non_last = df.iloc[:-1]
        self.assertTrue(non_last["return_1d"].notna().all(),
                        "return_1d should be filled for all rows except the last")

    async def test_return_1d_value_correct(self):
        """Spot-check a single return_1d value against manual calculation."""
        from data.history_backfill import backfill_signal_history
        bars = _make_bars(60)
        closes = bars["close"].values
        expected_ret = (closes[1] - closes[0]) / closes[0]

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.history_backfill._HISTORY_DIR", tmpdir), \
             patch("data.history_backfill.alpaca_client") as mock_ac:
            mock_ac.get_bars = AsyncMock(return_value=bars)
            await backfill_signal_history(["AAPL"], days=40)
            df = pd.read_parquet(os.path.join(tmpdir, "AAPL.parquet"))

        actual_ret = df.iloc[0]["return_1d"]
        self.assertAlmostEqual(actual_ret, expected_ret, places=6)

    async def test_rv_20d_is_annualized(self):
        """rv_20d must be annualized (√252 basis) and positive."""
        from data.history_backfill import backfill_signal_history
        bars = _make_bars(120)
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.history_backfill._HISTORY_DIR", tmpdir), \
             patch("data.history_backfill.alpaca_client") as mock_ac:
            mock_ac.get_bars = AsyncMock(return_value=bars)
            await backfill_signal_history(["AAPL"], days=90)
            df = pd.read_parquet(os.path.join(tmpdir, "AAPL.parquet"))

        # rv_20d should be annualized — for 1% daily vol: 0.01 * sqrt(252) ≈ 0.159
        # Check it's in a plausible range (0.05–2.0 for equities)
        valid = df["rv_20d"].dropna()
        self.assertTrue((valid > 0.0).all(), "rv_20d must be positive")
        self.assertTrue((valid < 5.0).all(), f"rv_20d unrealistically large: {valid.max()}")

    async def test_rv_20d_nan_when_insufficient_bars(self):
        """rv_20d must be NaN for early rows with < 20 prior bars."""
        from data.history_backfill import backfill_signal_history
        bars = _make_bars(30)   # only 30 bars total
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.history_backfill._HISTORY_DIR", tmpdir), \
             patch("data.history_backfill.alpaca_client") as mock_ac:
            mock_ac.get_bars = AsyncMock(return_value=bars)
            await backfill_signal_history(["AAPL"], days=20)
            df = pd.read_parquet(os.path.join(tmpdir, "AAPL.parquet"))

        # First 19 rows can't have rv_20d (need 20 prior closes)
        self.assertTrue(df.iloc[:19]["rv_20d"].isna().all(),
                        "rv_20d must be NaN for rows with < 20 prior bars")

    async def test_source_scores_are_zero_neutral(self):
        """Source scores set to 0.0 (neutral) since historical signals unavailable."""
        from data.history_backfill import backfill_signal_history
        bars = _make_bars(60)
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.history_backfill._HISTORY_DIR", tmpdir), \
             patch("data.history_backfill.alpaca_client") as mock_ac:
            mock_ac.get_bars = AsyncMock(return_value=bars)
            await backfill_signal_history(["AAPL"], days=40)
            df = pd.read_parquet(os.path.join(tmpdir, "AAPL.parquet"))

        for col in ("analyst_score", "earnings_score", "alpaca_score",
                    "yahoo_score", "congress_score"):
            self.assertTrue((df[col] == 0.0).all(),
                            f"{col} should be 0.0 for backfill rows")

    async def test_snapshot_ts_is_historical(self):
        """snapshot_ts must reflect the bar date, not time.time()."""
        from data.history_backfill import backfill_signal_history
        bars = _make_bars(60)
        one_year_ago = time.time() - 365 * 86_400
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.history_backfill._HISTORY_DIR", tmpdir), \
             patch("data.history_backfill.alpaca_client") as mock_ac:
            mock_ac.get_bars = AsyncMock(return_value=bars)
            await backfill_signal_history(["AAPL"], days=40)
            df = pd.read_parquet(os.path.join(tmpdir, "AAPL.parquet"))

        # All timestamps should be in the past (not time.time())
        self.assertTrue((df["snapshot_ts"] < time.time()).all())
        # And should be recent (within last 120 days based on bars fixture)
        self.assertTrue((df["snapshot_ts"] > one_year_ago).all())


class TestBackfillIdempotency(unittest.IsolatedAsyncioTestCase):

    async def test_no_duplicates_on_rerun(self):
        """Running backfill twice must not add duplicate rows for same dates."""
        from data.history_backfill import backfill_signal_history
        bars = _make_bars(60)
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.history_backfill._HISTORY_DIR", tmpdir), \
             patch("data.history_backfill.alpaca_client") as mock_ac:
            mock_ac.get_bars = AsyncMock(return_value=bars)
            r1 = await backfill_signal_history(["AAPL"], days=40)
            r2 = await backfill_signal_history(["AAPL"], days=40)
            df = pd.read_parquet(os.path.join(tmpdir, "AAPL.parquet"))

        # Second run should add 0 new rows
        self.assertEqual(r2["AAPL"], 0, "Re-run must not add duplicate rows")
        # Total rows unchanged
        self.assertEqual(len(df), r1["AAPL"])

    async def test_second_run_extends_with_new_data(self):
        """A second run with more days must only add the new rows."""
        from data.history_backfill import backfill_signal_history
        bars_short = _make_bars(60)
        bars_long  = _make_bars(120)
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.history_backfill._HISTORY_DIR", tmpdir), \
             patch("data.history_backfill.alpaca_client") as mock_ac:
            mock_ac.get_bars = AsyncMock(return_value=bars_short)
            r1 = await backfill_signal_history(["AAPL"], days=40)
            mock_ac.get_bars = AsyncMock(return_value=bars_long)
            r2 = await backfill_signal_history(["AAPL"], days=90)
            df = pd.read_parquet(os.path.join(tmpdir, "AAPL.parquet"))

        self.assertGreater(r2["AAPL"], 0, "Extended backfill should add new rows")
        self.assertEqual(len(df), r1["AAPL"] + r2["AAPL"])


class TestBackfillFallback(unittest.IsolatedAsyncioTestCase):

    async def test_skips_symbol_when_no_bars(self):
        """Symbol with empty bars from both Alpaca and Stooq must be skipped gracefully."""
        from data.history_backfill import backfill_signal_history
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.history_backfill._HISTORY_DIR", tmpdir), \
             patch("data.history_backfill.alpaca_client") as mock_ac, \
             patch("data.history_backfill.stooq_client") as mock_sc:
            mock_ac.get_bars = AsyncMock(return_value=pd.DataFrame())
            mock_sc.get_bars = AsyncMock(return_value=pd.DataFrame())
            result = await backfill_signal_history(["UNKNOWN"], days=30)

        self.assertEqual(result["UNKNOWN"], 0)

    async def test_uses_yfinance_first_for_full_market_volume(self):
        """yfinance is the PRIMARY source for backfill — Alpaca's IEX feed
        only captures ~2-3% of US equity volume, so we prefer yfinance for
        accurate full-market volume. Stooq + Alpaca are fallbacks."""
        from data.history_backfill import backfill_signal_history
        yf_bars     = _make_bars(60, start_price=100.0)
        stooq_bars  = _make_bars(60, start_price=500.0)  # different so we can tell them apart
        alpaca_bars = _make_bars(60, start_price=999.0)

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.history_backfill._HISTORY_DIR", tmpdir), \
             patch("data.history_backfill._fetch_bars_yfinance",
                   new_callable=AsyncMock, return_value=yf_bars), \
             patch("data.history_backfill.alpaca_client") as mock_ac, \
             patch("data.history_backfill.stooq_client") as mock_sc:
            mock_sc.get_bars = AsyncMock(return_value=stooq_bars)
            mock_ac.get_bars = AsyncMock(return_value=alpaca_bars)
            await backfill_signal_history(["AAPL"], days=40)
            df = pd.read_parquet(os.path.join(tmpdir, "AAPL.parquet"))

        # yfinance prices anchor at 100.0; Stooq at 500; Alpaca at 999.
        # yfinance-first means max price < 200.
        self.assertLess(df["price"].max(), 200.0,
                        "yfinance must be primary; higher price implies fallback was used")
        # Verify Stooq + Alpaca were NOT called (yfinance returned non-empty)
        mock_sc.get_bars.assert_not_awaited()
        mock_ac.get_bars.assert_not_awaited()

    async def test_falls_back_to_stooq_when_yfinance_empty(self):
        """Falls back to Stooq when yfinance returns empty bars."""
        from data.history_backfill import backfill_signal_history
        bars = _make_bars(60)
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.history_backfill._HISTORY_DIR", tmpdir), \
             patch("data.history_backfill._fetch_bars_yfinance",
                   new_callable=AsyncMock, return_value=pd.DataFrame()), \
             patch("data.history_backfill.alpaca_client") as mock_ac, \
             patch("data.history_backfill.stooq_client") as mock_sc:
            mock_sc.get_bars = AsyncMock(return_value=bars)
            mock_ac.get_bars = AsyncMock(return_value=pd.DataFrame())
            result = await backfill_signal_history(["AAPL"], days=40)
        self.assertGreater(result["AAPL"], 0, "Should have fallen back to Stooq")

    async def test_falls_back_to_alpaca_when_yf_and_stooq_empty(self):
        """Falls back to Alpaca/IEX when both yfinance and Stooq return empty bars."""
        from data.history_backfill import backfill_signal_history
        bars = _make_bars(60)
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.history_backfill._HISTORY_DIR", tmpdir), \
             patch("data.history_backfill._fetch_bars_yfinance",
                   new_callable=AsyncMock, return_value=pd.DataFrame()), \
             patch("data.history_backfill.alpaca_client") as mock_ac, \
             patch("data.history_backfill.stooq_client") as mock_sc:
            mock_sc.get_bars = AsyncMock(return_value=pd.DataFrame())
            mock_ac.get_bars = AsyncMock(return_value=bars)
            result = await backfill_signal_history(["AAPL"], days=40)
        self.assertGreater(result["AAPL"], 0, "Should have fallen back to Alpaca")

    async def test_multi_symbol_partial_failure(self):
        """One symbol failing must not prevent other symbols from being processed."""
        from data.history_backfill import backfill_signal_history
        bars = _make_bars(60)

        async def _side_effect(symbol, **_kw):
            if symbol == "FAIL":
                return pd.DataFrame()
            return bars

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.history_backfill._HISTORY_DIR", tmpdir), \
             patch("data.history_backfill.alpaca_client") as mock_ac, \
             patch("data.history_backfill.stooq_client") as mock_sc:
            mock_ac.get_bars = AsyncMock(side_effect=_side_effect)
            mock_sc.get_bars = AsyncMock(return_value=pd.DataFrame())
            result = await backfill_signal_history(["AAPL", "FAIL"], days=40)

        self.assertGreater(result["AAPL"], 0)
        self.assertEqual(result["FAIL"], 0)


class TestBackfillVolume(unittest.IsolatedAsyncioTestCase):
    """Volume column (#85) — populated from Alpaca/Stooq OHLCV bars."""

    async def test_volume_column_present_in_parquet(self):
        """Backfilled parquet must contain a 'volume' column."""
        from data.history_backfill import backfill_signal_history
        bars = _make_bars(60)
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.history_backfill._HISTORY_DIR", tmpdir), \
             patch("data.history_backfill.alpaca_client") as mock_ac:
            mock_ac.get_bars = AsyncMock(return_value=bars)
            await backfill_signal_history(["AAPL"], days=40)
            df = pd.read_parquet(os.path.join(tmpdir, "AAPL.parquet"))
        self.assertIn("volume", df.columns, "Parquet must include volume column")

    async def test_volume_values_match_input_bars(self):
        """Backfilled volumes must match the source bar volumes (minus dropped last row)."""
        from data.history_backfill import backfill_signal_history
        bars = _make_bars(60)
        expected_volumes = bars["volume"].values[:-1]  # last row dropped (no return_1d)

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.history_backfill._HISTORY_DIR", tmpdir), \
             patch("data.history_backfill.alpaca_client") as mock_ac:
            mock_ac.get_bars = AsyncMock(return_value=bars)
            await backfill_signal_history(["AAPL"], days=40)
            df = pd.read_parquet(os.path.join(tmpdir, "AAPL.parquet"))

        actual_volumes = df["volume"].values
        np.testing.assert_array_almost_equal(
            actual_volumes, expected_volumes, decimal=2,
            err_msg="Volume values should match source bars 1:1 (minus last row)"
        )

    async def test_volume_is_float_dtype(self):
        """Volume column dtype should be float (matches _DTYPE_MAP entry)."""
        from data.history_backfill import backfill_signal_history
        bars = _make_bars(60)
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.history_backfill._HISTORY_DIR", tmpdir), \
             patch("data.history_backfill.alpaca_client") as mock_ac:
            mock_ac.get_bars = AsyncMock(return_value=bars)
            await backfill_signal_history(["AAPL"], days=40)
            df = pd.read_parquet(os.path.join(tmpdir, "AAPL.parquet"))
        self.assertTrue(np.issubdtype(df["volume"].dtype, np.floating),
                        f"volume must be float, got {df['volume'].dtype}")

    async def test_volume_zero_fallback_when_column_missing(self):
        """If bars DataFrame lacks 'volume' column, backfill must fall back to 0.0 — never raise."""
        from data.history_backfill import _bars_to_backfill_rows
        # Build bars WITHOUT a volume column
        bars = _make_bars(60).drop(columns=["volume"])
        df = _bars_to_backfill_rows("AAPL", bars)
        self.assertIn("volume", df.columns)
        self.assertTrue((df["volume"] == 0.0).all(),
                        "Missing volume column → all-zero fallback")

    async def test_volume_nan_replaced_with_zero(self):
        """NaN values in source volume must be replaced with 0.0."""
        from data.history_backfill import _bars_to_backfill_rows
        bars = _make_bars(60)
        bars.loc[3:5, "volume"] = np.nan
        df = _bars_to_backfill_rows("AAPL", bars)
        # The first 3 of those NaN positions are still in df (only the very last
        # row gets dropped). They must be 0.0, not NaN.
        self.assertTrue(df["volume"].notna().all(),
                        "NaN volumes must be filled with 0.0, never persisted")
        self.assertEqual(df.iloc[3]["volume"], 0.0)
        self.assertEqual(df.iloc[4]["volume"], 0.0)
        self.assertEqual(df.iloc[5]["volume"], 0.0)


class TestRecordSnapshotAcceptsVolume(unittest.IsolatedAsyncioTestCase):
    """Live path: record_snapshot now takes optional volume kwarg (#85)."""

    async def test_record_snapshot_accepts_optional_volume(self):
        """record_snapshot must accept a volume keyword without raising."""
        from data.signal_history import SignalHistoryStore
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.signal_history._HISTORY_DIR", tmpdir):
            store = SignalHistoryStore()
            # Should not raise — signature now includes `volume: Optional[float]`
            await store.record_snapshot(
                symbol="TEST",
                scores={"analyst_consensus": 0.5},
                composite_score=0.5,
                price=100.0,
                rv_20d=0.20,
                rv_60d=0.18,
                volume=1_500_000.0,
            )
            df = pd.read_parquet(os.path.join(tmpdir, "TEST.parquet"))
        self.assertIn("volume", df.columns)
        self.assertEqual(df.iloc[-1]["volume"], 1_500_000.0)

    async def test_record_snapshot_volume_defaults_to_nan(self):
        """When volume kwarg is omitted, recorded value should be NaN (live path
        usually doesn't have per-snapshot volume)."""
        from data.signal_history import SignalHistoryStore
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.signal_history._HISTORY_DIR", tmpdir):
            store = SignalHistoryStore()
            await store.record_snapshot(
                symbol="TEST",
                scores={"analyst_consensus": 0.5},
                composite_score=0.5,
                price=100.0,
            )
            df = pd.read_parquet(os.path.join(tmpdir, "TEST.parquet"))
        # When volume not passed, the column entry should be NaN/None (not 0.0)
        self.assertTrue(pd.isna(df.iloc[-1]["volume"]),
                        "Omitted volume kwarg → NaN, not 0.0 (preserve missingness)")


class TestBackfillCNNCompatibility(unittest.IsolatedAsyncioTestCase):
    """Verify backfill output is usable by build_training_windows."""

    async def test_backfill_data_passes_build_training_windows(self):
        """build_training_windows must succeed on backfilled Parquet data."""
        from data.history_backfill import backfill_signal_history
        from data.cnn_model import build_training_windows, WINDOW_SIZE, MIN_TRAIN_SAMPLES
        bars = _make_bars(200)
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.history_backfill._HISTORY_DIR", tmpdir), \
             patch("data.history_backfill.alpaca_client") as mock_ac:
            mock_ac.get_bars = AsyncMock(return_value=bars)
            await backfill_signal_history(["AAPL"], days=180)
            df = pd.read_parquet(os.path.join(tmpdir, "AAPL.parquet"))

        # Drop rows without return_1d (last row has no next bar)
        df = df.dropna(subset=["return_1d"]).reset_index(drop=True)
        X, y, w, t = build_training_windows(df, T=WINDOW_SIZE)

        self.assertGreaterEqual(len(X), MIN_TRAIN_SAMPLES,
                                f"Expected ≥{MIN_TRAIN_SAMPLES} samples, got {len(X)}")
        self.assertEqual(len(X), len(y))
        self.assertFalse(np.isnan(X).any(), "No NaN in X after build_training_windows")
        self.assertFalse(np.isnan(y).any(), "No NaN in y after build_training_windows")


if __name__ == "__main__":
    unittest.main()
