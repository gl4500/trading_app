"""
Unit tests for data/signal_history.py
Covers: record_snapshot, update_outcomes, get_training_data,
        get_recent_window, sample_count, symbols_with_data
"""
import asyncio
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import data.signal_history as sh


def _scores(analyst=0.5, earnings=0.3, alpaca=0.1, yahoo=-0.1, congress=0.2):
    return {
        "analyst_consensus":    analyst,
        "earnings_surprise":    earnings,
        "alpaca_news":          alpaca,
        "yahoo_news":           yahoo,
        "congressional_trades": congress,
    }


class TestSignalHistoryStore(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Redirect all I/O to a temp directory
        self._tmpdir = tempfile.mkdtemp()
        self._orig_dir = sh._HISTORY_DIR
        sh._HISTORY_DIR = self._tmpdir
        # Clear per-symbol locks so they use the new dir
        sh._LOCKS.clear()
        self.store = sh.SignalHistoryStore()

    def tearDown(self):
        sh._HISTORY_DIR = self._orig_dir
        sh._LOCKS.clear()

    # ── record_snapshot ───────────────────────────────────────────────────────

    async def test_record_snapshot_creates_parquet_file(self):
        await self.store.record_snapshot("AAPL", _scores(), 0.4, 150.0)
        path = sh._symbol_path("AAPL")
        self.assertTrue(os.path.exists(path))

    async def test_record_snapshot_row_count(self):
        await self.store.record_snapshot("AAPL", _scores(), 0.4, 150.0)
        await self.store.record_snapshot("AAPL", _scores(), 0.3, 151.0)
        df = sh._load("AAPL")
        self.assertEqual(len(df), 2)

    async def test_record_snapshot_columns_present(self):
        await self.store.record_snapshot("AAPL", _scores(), 0.4, 150.0)
        df = sh._load("AAPL")
        for col in sh._DTYPE_MAP:
            self.assertIn(col, df.columns)

    async def test_record_snapshot_return_columns_are_nan(self):
        await self.store.record_snapshot("AAPL", _scores(), 0.4, 150.0)
        df = sh._load("AAPL")
        self.assertTrue(df["return_1d"].isna().all())
        self.assertTrue(df["return_5d"].isna().all())

    async def test_record_snapshot_source_scores_stored(self):
        await self.store.record_snapshot("AAPL", _scores(analyst=0.7), 0.5, 200.0)
        df = sh._load("AAPL")
        self.assertAlmostEqual(df.iloc[0]["analyst_score"], 0.7)

    async def test_record_snapshot_none_scores_become_nan(self):
        scores = _scores()
        scores["analyst_consensus"] = None
        await self.store.record_snapshot("AAPL", scores, 0.0, 100.0)
        df = sh._load("AAPL")
        self.assertTrue(pd.isna(df.iloc[0]["analyst_score"]))

    async def test_record_snapshot_multiple_symbols_independent(self):
        await self.store.record_snapshot("AAPL", _scores(), 0.4, 150.0)
        await self.store.record_snapshot("MSFT", _scores(), 0.2, 300.0)
        df_aapl = sh._load("AAPL")
        df_msft = sh._load("MSFT")
        self.assertEqual(len(df_aapl), 1)
        self.assertEqual(len(df_msft), 1)

    # ── update_outcomes ───────────────────────────────────────────────────────

    async def test_update_outcomes_fills_1d_after_one_day(self):
        old_ts = time.time() - 90_000  # 25 hours ago
        row = {
            "symbol": "AAPL", "snapshot_ts": old_ts,
            "analyst_score": 0.5, "earnings_score": 0.3,
            "alpaca_score": 0.1, "yahoo_score": -0.1, "congress_score": 0.2,
            "composite_score": 0.4, "price": 100.0,
            "return_1d": float("nan"), "return_5d": float("nan"),
        }
        df = pd.DataFrame([row])
        sh._save("AAPL", df)

        updated = await self.store.update_outcomes("AAPL", 110.0)
        self.assertEqual(updated, 1)
        df2 = sh._load("AAPL")
        self.assertAlmostEqual(df2.iloc[0]["return_1d"], 0.10, places=5)

    async def test_update_outcomes_does_not_fill_before_one_day(self):
        row = {
            "symbol": "AAPL", "snapshot_ts": time.time() - 3600,  # 1 hour ago
            "analyst_score": 0.5, "earnings_score": 0.3,
            "alpaca_score": 0.1, "yahoo_score": -0.1, "congress_score": 0.2,
            "composite_score": 0.4, "price": 100.0,
            "return_1d": float("nan"), "return_5d": float("nan"),
        }
        df = pd.DataFrame([row])
        sh._save("AAPL", df)

        updated = await self.store.update_outcomes("AAPL", 110.0)
        self.assertEqual(updated, 0)

    async def test_update_outcomes_fills_5d_after_five_days(self):
        old_ts = time.time() - 5 * 86_400 - 3600  # 5 days + 1 hour ago
        row = {
            "symbol": "AAPL", "snapshot_ts": old_ts,
            "analyst_score": 0.5, "earnings_score": 0.3,
            "alpaca_score": 0.1, "yahoo_score": -0.1, "congress_score": 0.2,
            "composite_score": 0.4, "price": 200.0,
            "return_1d": float("nan"), "return_5d": float("nan"),
        }
        df = pd.DataFrame([row])
        sh._save("AAPL", df)

        await self.store.update_outcomes("AAPL", 220.0)
        df2 = sh._load("AAPL")
        self.assertAlmostEqual(df2.iloc[0]["return_5d"], 0.10, places=5)

    async def test_update_outcomes_returns_zero_for_empty_store(self):
        result = await self.store.update_outcomes("ZZZZ", 100.0)
        self.assertEqual(result, 0)

    async def test_update_outcomes_skips_already_filled_rows(self):
        old_ts = time.time() - 90_000
        row = {
            "symbol": "AAPL", "snapshot_ts": old_ts,
            "analyst_score": 0.5, "earnings_score": 0.3,
            "alpaca_score": 0.1, "yahoo_score": -0.1, "congress_score": 0.2,
            "composite_score": 0.4, "price": 100.0,
            "return_1d": 0.05,   # already filled
            "return_5d": float("nan"),
        }
        df = pd.DataFrame([row])
        sh._save("AAPL", df)

        updated = await self.store.update_outcomes("AAPL", 115.0)
        self.assertEqual(updated, 0)  # return_1d already set, return_5d not yet due

    # ── get_training_data ─────────────────────────────────────────────────────

    async def test_get_training_data_excludes_unlabelled_rows(self):
        await self.store.record_snapshot("AAPL", _scores(), 0.4, 150.0)
        df = self.store.get_training_data("AAPL")
        self.assertEqual(len(df), 0)   # return_1d is NaN → excluded

    async def test_get_training_data_includes_labelled_rows(self):
        old_ts = time.time() - 90_000
        row = {
            "symbol": "AAPL", "snapshot_ts": old_ts,
            "analyst_score": 0.5, "earnings_score": 0.3,
            "alpaca_score": 0.1, "yahoo_score": -0.1, "congress_score": 0.2,
            "composite_score": 0.4, "price": 100.0,
            "return_1d": 0.05, "return_5d": float("nan"),
        }
        sh._save("AAPL", pd.DataFrame([row]))
        df = self.store.get_training_data("AAPL")
        self.assertEqual(len(df), 1)

    async def test_get_training_data_all_symbols_aggregated(self):
        for sym, ret in [("AAPL", 0.03), ("MSFT", -0.02)]:
            old_ts = time.time() - 90_000
            row = {
                "symbol": sym, "snapshot_ts": old_ts,
                "analyst_score": 0.5, "earnings_score": 0.3,
                "alpaca_score": 0.1, "yahoo_score": -0.1, "congress_score": 0.2,
                "composite_score": 0.4, "price": 100.0,
                "return_1d": ret, "return_5d": float("nan"),
            }
            sh._save(sym, pd.DataFrame([row]))
        df = self.store.get_training_data()   # None → all symbols
        self.assertEqual(len(df), 2)

    # ── get_recent_window ─────────────────────────────────────────────────────

    async def test_get_recent_window_none_when_fewer_than_3_rows(self):
        await self.store.record_snapshot("AAPL", _scores(), 0.4, 150.0)
        result = self.store.get_recent_window("AAPL")
        self.assertIsNone(result)

    async def test_get_recent_window_shape(self):
        for _ in range(5):
            await self.store.record_snapshot("AAPL", _scores(), 0.4, 150.0)
        result = self.store.get_recent_window("AAPL", T=10)
        self.assertIsNotNone(result)
        # 10 channels: 6 source + 2 agent + 2 RV (zeros when not recorded)
        self.assertEqual(result.shape, (10, 10))

    async def test_get_recent_window_no_nans(self):
        scores = _scores()
        scores["analyst_consensus"] = None
        for _ in range(5):
            await self.store.record_snapshot("AAPL", scores, 0.4, 150.0)
        result = self.store.get_recent_window("AAPL", T=5)
        self.assertFalse(np.isnan(result).any())

    # ── sample_count + symbols_with_data ─────────────────────────────────────

    async def test_sample_count_zero_when_no_outcomes(self):
        await self.store.record_snapshot("AAPL", _scores(), 0.4, 150.0)
        self.assertEqual(self.store.sample_count("AAPL"), 0)

    async def test_symbols_with_data_lists_created_files(self):
        await self.store.record_snapshot("AAPL", _scores(), 0.4, 150.0)
        await self.store.record_snapshot("NVDA", _scores(), 0.2, 800.0)
        syms = set(self.store.symbols_with_data())
        self.assertIn("AAPL", syms)
        self.assertIn("NVDA", syms)

    async def test_symbols_with_data_empty_when_no_files(self):
        self.assertEqual(self.store.symbols_with_data(), [])

    # ── record_agent_signals ──────────────────────────────────────────────────

    async def test_record_agent_signals_updates_last_row(self):
        await self.store.record_snapshot("AAPL", _scores(), 0.4, 150.0)
        result = await self.store.record_agent_signals("AAPL", 0.65, 0.75)
        self.assertTrue(result)
        df = sh._load("AAPL")
        self.assertAlmostEqual(df.iloc[-1]["agent_consensus"], 0.65, places=5)
        self.assertAlmostEqual(df.iloc[-1]["agent_agreement"], 0.75, places=5)

    async def test_record_agent_signals_returns_false_for_unknown_symbol(self):
        result = await self.store.record_agent_signals("ZZZZ", 0.5, 0.5)
        self.assertFalse(result)

    async def test_record_agent_signals_returns_false_when_snapshot_too_old(self):
        # Write a row with an old snapshot_ts
        old_ts = __import__("time").time() - 200  # older than 120s default window
        import pandas as pd
        row = {
            "symbol": "AAPL", "snapshot_ts": old_ts,
            "analyst_score": 0.1, "earnings_score": 0.1,
            "alpaca_score": 0.1, "yahoo_score": 0.1, "congress_score": 0.1,
            "composite_score": 0.4, "price": 150.0,
            "return_1d": float("nan"), "return_5d": float("nan"),
        }
        sh._save("AAPL", pd.DataFrame([row]))
        result = await self.store.record_agent_signals("AAPL", 0.5, 0.5)
        self.assertFalse(result)

    async def test_agent_columns_persisted_in_parquet(self):
        await self.store.record_snapshot("MSFT", _scores(), 0.3, 300.0)
        await self.store.record_agent_signals("MSFT", -0.3, 0.6)
        df = sh._load("MSFT")
        self.assertIn("agent_consensus", df.columns)
        self.assertIn("agent_agreement", df.columns)
        self.assertIn("top_agent_correct", df.columns)

    async def test_get_recent_window_returns_10_channels(self):
        for _ in range(5):
            await self.store.record_snapshot("AAPL", _scores(), 0.4, 150.0,
                                             rv_20d=0.18, rv_60d=0.22)
        for _ in range(5):
            await self.store.record_agent_signals("AAPL", 0.5, 0.8)
        result = self.store.get_recent_window("AAPL", T=5)
        self.assertIsNotNone(result)
        # 10 channels: 6 source + 2 agent + 2 RV
        self.assertEqual(result.shape, (10, 5))

    async def test_get_recent_window_rv_values_stored_and_retrieved(self):
        await self.store.record_snapshot("AAPL", _scores(), 0.4, 150.0,
                                         rv_20d=0.18, rv_60d=0.22)
        for _ in range(4):
            await self.store.record_snapshot("AAPL", _scores(), 0.4, 150.0)
        result = self.store.get_recent_window("AAPL", T=5)
        self.assertIsNotNone(result)
        # Channel 7 = rv_20d, channel 8 = rv_60d (0-indexed)
        # Most recent row is last column; first row had rv values
        # Verify no NaN survived (nan_to_num converts to 0.0)
        self.assertFalse(np.isnan(result).any())

    async def test_get_recent_window_rv_zero_filled_when_absent(self):
        """Old snapshots without rv columns should produce zeros, not errors."""
        for _ in range(5):
            await self.store.record_snapshot("AAPL", _scores(), 0.4, 150.0)
        result = self.store.get_recent_window("AAPL", T=5)
        self.assertIsNotNone(result)
        self.assertEqual(result.shape, (10, 5))
        # RV channels (8 and 9) should be zeros when not recorded
        self.assertTrue(np.all(result[8] == 0.0))
        self.assertTrue(np.all(result[9] == 0.0))

    async def test_get_recent_window_10_channels_zeros_for_missing_optional_cols(self):
        """Old Parquet files without agent/RV columns return 10-ch window with zeros for those."""
        import pandas as pd, time as _time
        # Write a minimal old-style row (no agent or RV columns)
        for _ in range(5):
            row = {
                "symbol": "AAPL", "snapshot_ts": _time.time(),
                "analyst_score": 0.5, "earnings_score": 0.3,
                "alpaca_score": 0.1, "yahoo_score": -0.1, "congress_score": 0.2,
                "composite_score": 0.4, "price": 150.0,
                "return_1d": float("nan"), "return_5d": float("nan"),
            }
            df_old = sh._load("AAPL")
            df_old = pd.concat([df_old, pd.DataFrame([row])], ignore_index=True)
            sh._save("AAPL", df_old)

        result = self.store.get_recent_window("AAPL", T=5)
        self.assertIsNotNone(result)
        # 10 channels: old files without agent/RV columns get zeros for channels 6-9
        self.assertEqual(result.shape, (10, 5))
        # Agent channels (index 6 and 7) should be zero
        self.assertTrue((result[6] == 0.0).all())
        self.assertTrue((result[7] == 0.0).all())
        # RV channels (index 8 and 9) should be zero
        self.assertTrue((result[8] == 0.0).all())
        self.assertTrue((result[9] == 0.0).all())


class TestMacroJoinIntoTrainingData(unittest.IsolatedAsyncioTestCase):
    """get_training_data() must join the 5 macro CNN channels from __MACRO__.parquet.

    Why: without this join, build_training_windows can never assemble the 15-channel
    input the CNN was designed for — 5 macro channels stay zero, model degrades to 10ch.
    """

    _MACRO_CHANNELS = [
        "macro_vix_norm",
        "macro_gld_5d",
        "macro_tlt_5d",
        "macro_spy_5d",
        "macro_breadth",
    ]

    def setUp(self):
        self._tmpdir   = tempfile.mkdtemp()
        self._orig_dir = sh._HISTORY_DIR
        sh._HISTORY_DIR = self._tmpdir
        sh._LOCKS.clear()
        self.store = sh.SignalHistoryStore()

    def tearDown(self):
        sh._HISTORY_DIR = self._orig_dir
        sh._LOCKS.clear()

    def _write_macro(
        self,
        dates_ts,
        vix_norm=None,
        gld_5d=None,
        tlt_5d=None,
        spy_5d=None,
        breadth=None,
    ):
        n = len(dates_ts)
        df = pd.DataFrame({
            "date_ts":       list(dates_ts),
            "vix":           [18.0] * n,
            "tnx":           [4.3]  * n,
            "vix_norm":      vix_norm if vix_norm is not None else [0.6]   * n,
            "gld_1d":        [0.0]   * n,
            "gld_5d":        gld_5d  if gld_5d  is not None else [0.01]  * n,
            "tlt_1d":        [0.0]   * n,
            "tlt_5d":        tlt_5d  if tlt_5d  is not None else [0.005] * n,
            "spy_1d":        [0.0]   * n,
            "spy_5d":        spy_5d  if spy_5d  is not None else [0.012] * n,
            "iwm_5d":        [0.014] * n,
            "qqq_5d":        [0.011] * n,
            "uup_5d":        [0.001] * n,
            "uso_5d":        [0.02]  * n,
            "breadth_score": breadth if breadth is not None else [0.002] * n,
            "regime":        ["NEUTRAL"] * n,
            "regime_score":  [0.0] * n,
        })
        df.to_parquet(
            os.path.join(self._tmpdir, "__MACRO__.parquet"),
            compression="zstd",
            index=False,
        )

    def _write_full_labelled_row(self, symbol, snapshot_ts, return_1d=0.02):
        row = {
            "symbol":            symbol,
            "snapshot_ts":       float(snapshot_ts),
            "analyst_score":     0.5,
            "earnings_score":    0.3,
            "alpaca_score":      0.1,
            "yahoo_score":      -0.1,
            "congress_score":    0.2,
            "iv_rv_score":       0.05,
            "composite_score":   0.4,
            "price":             100.0,
            "return_1d":         return_1d,
            "return_5d":         float("nan"),
            "agent_consensus":   0.5,
            "agent_agreement":   0.7,
            "top_agent_correct": 1.0,
            "rv_20d":            0.18,
            "rv_60d":            0.22,
        }
        sh._save(symbol, pd.DataFrame([row]))

    async def test_macro_columns_attached_when_file_present(self):
        ts = time.time() - 90_000
        self._write_macro([ts])
        self._write_full_labelled_row("AAPL", ts)

        df = self.store.get_training_data()
        for col in self._MACRO_CHANNELS:
            self.assertIn(col, df.columns)

    async def test_macro_columns_take_values_from_macro_file(self):
        ts = time.time() - 90_000
        self._write_macro(
            [ts],
            vix_norm=[0.85],
            gld_5d=[0.03],
            tlt_5d=[-0.01],
            spy_5d=[0.02],
            breadth=[0.005],
        )
        self._write_full_labelled_row("AAPL", ts)

        df = self.store.get_training_data()
        self.assertAlmostEqual(df.iloc[0]["macro_vix_norm"],  0.85,  places=5)
        self.assertAlmostEqual(df.iloc[0]["macro_gld_5d"],    0.03,  places=5)
        self.assertAlmostEqual(df.iloc[0]["macro_tlt_5d"],   -0.01,  places=5)
        self.assertAlmostEqual(df.iloc[0]["macro_spy_5d"],    0.02,  places=5)
        self.assertAlmostEqual(df.iloc[0]["macro_breadth"],   0.005, places=5)

    async def test_macro_join_uses_backward_asof(self):
        """Snapshot at T joins to macro at T-1d, never to macro at T+1d."""
        snap_ts      = time.time() - 90_000
        macro_before = snap_ts - 86_400
        macro_after  = snap_ts + 86_400
        self._write_macro(
            [macro_before, macro_after],
            vix_norm=[0.7,  0.9],
            gld_5d  =[0.01, 0.05],
            tlt_5d  =[0.0,  0.0],
            spy_5d  =[0.0,  0.0],
            breadth =[0.0,  0.0],
        )
        self._write_full_labelled_row("AAPL", snap_ts)

        df = self.store.get_training_data()
        self.assertAlmostEqual(df.iloc[0]["macro_vix_norm"], 0.7,  places=5)
        self.assertAlmostEqual(df.iloc[0]["macro_gld_5d"],   0.01, places=5)

    async def test_macro_columns_absent_when_macro_file_missing(self):
        """No __MACRO__.parquet → no macro columns added (CNN degrades to 10ch)."""
        ts = time.time() - 90_000
        self._write_full_labelled_row("AAPL", ts)

        df = self.store.get_training_data()
        for col in self._MACRO_CHANNELS:
            self.assertNotIn(col, df.columns)

    async def test_macro_columns_zero_filled_outside_tolerance(self):
        """Snapshot 30 days from any macro row → macro values are 0.0, not NaN."""
        snap_ts   = time.time() - 90_000
        macro_far = snap_ts - 30 * 86_400
        self._write_macro(
            [macro_far],
            vix_norm=[0.85],
            gld_5d  =[0.03],
            tlt_5d  =[-0.01],
            spy_5d  =[0.02],
            breadth =[0.005],
        )
        self._write_full_labelled_row("AAPL", snap_ts)

        df = self.store.get_training_data()
        for col in self._MACRO_CHANNELS:
            self.assertEqual(df.iloc[0][col], 0.0)

    async def test_build_training_windows_yields_15_channels_after_macro_join(self):
        """End-to-end: get_training_data + build_training_windows → 15-channel X."""
        from data.cnn_model import build_training_windows
        ts0 = time.time() - 90_000
        self._write_macro([ts0])
        self._write_full_labelled_row("AAPL", ts0)

        df = self.store.get_training_data()
        X, _y, _w = build_training_windows(df)
        self.assertEqual(X.shape[1], 15)


if __name__ == "__main__":
    unittest.main()
