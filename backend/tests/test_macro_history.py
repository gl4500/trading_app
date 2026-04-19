"""
Unit tests for data/macro_history.py and the macro backfill extension.

Covers: schema, RV/return computation, VIX normalization, regime scoring,
        idempotency, fallback, CNN channel integration.
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


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_bars(symbol: str, n: int = 120, start_price: float = 100.0,
               seed: int = 0) -> pd.DataFrame:
    np.random.seed(seed)
    closes = [start_price]
    for _ in range(n - 1):
        closes.append(closes[-1] * (1 + np.random.normal(0, 0.01)))
    closes = np.array(closes)
    now = pd.Timestamp.now("UTC")
    timestamps = [now - pd.Timedelta(days=n - 1 - i) for i in range(n)]
    return pd.DataFrame({
        "timestamp": timestamps,
        "open":  closes * 0.999,
        "high":  closes * 1.005,
        "low":   closes * 0.995,
        "close": closes,
        "volume": np.ones(n) * 1_000_000,
    })


def _make_vix_bars(n: int = 120, base: float = 18.0) -> pd.DataFrame:
    """VIX-like series: level (not price, no volume)."""
    np.random.seed(99)
    levels = [base + np.random.normal(0, 1) for _ in range(n)]
    now = pd.Timestamp.now("UTC")
    timestamps = [now - pd.Timedelta(days=n - 1 - i) for i in range(n)]
    return pd.DataFrame({
        "timestamp": timestamps,
        "close": np.array(levels),
    })


def _mock_alpaca(symbol_map: dict):
    """Returns an AsyncMock for alpaca_client.get_bars keyed by symbol."""
    async def _get_bars(symbol, **_kw):
        return symbol_map.get(symbol, pd.DataFrame())
    m = MagicMock()
    m.get_bars = AsyncMock(side_effect=_get_bars)
    return m


def _mock_yf(vix_df: pd.DataFrame, tnx_df: pd.DataFrame):
    """Minimal yfinance.download mock returning VIX or TNX data."""
    def _download(ticker, **_kw):
        if "VIX" in ticker:
            return vix_df
        if "TNX" in ticker:
            return tnx_df
        return pd.DataFrame()
    return _download


# ── MacroHistoryStore schema & persistence ────────────────────────────────────

class TestMacroHistoryStore(unittest.IsolatedAsyncioTestCase):

    async def test_record_creates_parquet(self):
        """record_snapshot must create __MACRO__.parquet on first call."""
        from data.macro_history import MacroHistoryStore, _MACRO_FILE
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.macro_history._MACRO_FILE",
                   os.path.join(tmpdir, "__MACRO__.parquet")):
            store = MacroHistoryStore()
            await store.record_snapshot(
                date_ts=time.time(),
                vix=18.5, tnx=4.3,
                returns={"gld_1d": 0.005, "gld_5d": 0.012,
                         "tlt_1d": -0.003, "tlt_5d": -0.008,
                         "spy_1d": 0.008, "spy_5d": 0.020,
                         "iwm_5d": 0.015, "qqq_5d": 0.025,
                         "uup_5d": 0.002, "uso_5d": -0.010},
                regime="RISK_ON",
            )
            self.assertTrue(os.path.exists(
                os.path.join(tmpdir, "__MACRO__.parquet")))

    async def test_row_has_required_columns(self):
        """Each recorded row must contain all required schema columns."""
        from data.macro_history import MacroHistoryStore, MACRO_COLUMNS
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.macro_history._MACRO_FILE",
                   os.path.join(tmpdir, "__MACRO__.parquet")):
            store = MacroHistoryStore()
            await store.record_snapshot(
                date_ts=time.time(),
                vix=20.0, tnx=4.0,
                returns={"gld_1d": 0.0, "gld_5d": 0.0,
                         "tlt_1d": 0.0, "tlt_5d": 0.0,
                         "spy_1d": 0.0, "spy_5d": 0.0,
                         "iwm_5d": 0.0, "qqq_5d": 0.0,
                         "uup_5d": 0.0, "uso_5d": 0.0},
                regime="NEUTRAL",
            )
            df = pd.read_parquet(os.path.join(tmpdir, "__MACRO__.parquet"))
        for col in MACRO_COLUMNS:
            self.assertIn(col, df.columns, f"Missing column: {col}")

    async def test_vix_norm_computed(self):
        """vix_norm = VIX / 30 (clipped 0–3)."""
        from data.macro_history import MacroHistoryStore
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.macro_history._MACRO_FILE",
                   os.path.join(tmpdir, "__MACRO__.parquet")):
            store = MacroHistoryStore()
            await store.record_snapshot(
                date_ts=time.time(), vix=30.0, tnx=4.0,
                returns={k: 0.0 for k in [
                    "gld_1d","gld_5d","tlt_1d","tlt_5d",
                    "spy_1d","spy_5d","iwm_5d","qqq_5d","uup_5d","uso_5d"]},
                regime="HIGH_VOL",
            )
            df = pd.read_parquet(os.path.join(tmpdir, "__MACRO__.parquet"))
        self.assertAlmostEqual(df.iloc[0]["vix_norm"], 1.0, places=4)

    async def test_breadth_score_computed(self):
        """breadth_score = (iwm_5d - spy_5d) clamped to [-1, 1]."""
        from data.macro_history import MacroHistoryStore
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.macro_history._MACRO_FILE",
                   os.path.join(tmpdir, "__MACRO__.parquet")):
            store = MacroHistoryStore()
            await store.record_snapshot(
                date_ts=time.time(), vix=15.0, tnx=4.0,
                returns={"gld_1d": 0.0, "gld_5d": 0.0,
                         "tlt_1d": 0.0, "tlt_5d": 0.0,
                         "spy_1d": 0.0, "spy_5d": 0.01,
                         "iwm_5d": 0.03, "qqq_5d": 0.0,
                         "uup_5d": 0.0, "uso_5d": 0.0},
                regime="RISK_ON",
            )
            df = pd.read_parquet(os.path.join(tmpdir, "__MACRO__.parquet"))
        # breadth = 0.03 - 0.01 = 0.02, clamped to [-1, 1]
        self.assertAlmostEqual(df.iloc[0]["breadth_score"], 0.02, places=4)

    async def test_regime_score_bullish(self):
        """RISK_ON → regime_score +1.0."""
        from data.macro_history import MacroHistoryStore
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.macro_history._MACRO_FILE",
                   os.path.join(tmpdir, "__MACRO__.parquet")):
            store = MacroHistoryStore()
            await store.record_snapshot(
                date_ts=time.time(), vix=14.0, tnx=4.0,
                returns={k: 0.0 for k in [
                    "gld_1d","gld_5d","tlt_1d","tlt_5d",
                    "spy_1d","spy_5d","iwm_5d","qqq_5d","uup_5d","uso_5d"]},
                regime="RISK_ON",
            )
            df = pd.read_parquet(os.path.join(tmpdir, "__MACRO__.parquet"))
        self.assertAlmostEqual(df.iloc[0]["regime_score"], 1.0, places=4)

    async def test_regime_score_bearish(self):
        """RISK_OFF → regime_score -1.0."""
        from data.macro_history import MacroHistoryStore
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.macro_history._MACRO_FILE",
                   os.path.join(tmpdir, "__MACRO__.parquet")):
            store = MacroHistoryStore()
            await store.record_snapshot(
                date_ts=time.time(), vix=35.0, tnx=4.0,
                returns={k: 0.0 for k in [
                    "gld_1d","gld_5d","tlt_1d","tlt_5d",
                    "spy_1d","spy_5d","iwm_5d","qqq_5d","uup_5d","uso_5d"]},
                regime="RISK_OFF",
            )
            df = pd.read_parquet(os.path.join(tmpdir, "__MACRO__.parquet"))
        self.assertAlmostEqual(df.iloc[0]["regime_score"], -1.0, places=4)

    def test_get_features_for_date_returns_vector(self):
        """get_features_for_date must return a 1-D array of length N_MACRO_CHANNELS."""
        from data.macro_history import MacroHistoryStore, N_MACRO_CHANNELS
        import asyncio
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.macro_history._MACRO_FILE",
                   os.path.join(tmpdir, "__MACRO__.parquet")):
            store = MacroHistoryStore()
            ts = time.time()
            asyncio.run(store.record_snapshot(
                date_ts=ts, vix=18.0, tnx=4.2,
                returns={"gld_1d": 0.002, "gld_5d": 0.008,
                         "tlt_1d": -0.001, "tlt_5d": -0.004,
                         "spy_1d": 0.003, "spy_5d": 0.012,
                         "iwm_5d": 0.010, "qqq_5d": 0.015,
                         "uup_5d": 0.001, "uso_5d": -0.005},
                regime="NEUTRAL",
            ))
            vec = store.get_features_for_date(ts)
        self.assertIsNotNone(vec)
        self.assertEqual(len(vec), N_MACRO_CHANNELS)

    def test_get_features_returns_zeros_for_missing_date(self):
        """Dates with no macro data must return a zero vector, not None."""
        from data.macro_history import MacroHistoryStore, N_MACRO_CHANNELS
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.macro_history._MACRO_FILE",
                   os.path.join(tmpdir, "__MACRO__.parquet")):
            store = MacroHistoryStore()
            vec = store.get_features_for_date(time.time() - 365 * 86_400)
        self.assertIsNotNone(vec)
        self.assertEqual(len(vec), N_MACRO_CHANNELS)
        self.assertTrue(np.all(vec == 0.0))


# ── Macro backfill ─────────────────────────────────────────────────────────────

class TestMacroBackfill(unittest.IsolatedAsyncioTestCase):

    def _macro_bars(self):
        """Symbol map covering all required macro instruments."""
        syms = ["GLD", "TLT", "UUP", "USO", "SPY", "IWM", "QQQ",
                "XLK", "XLF", "XLE", "XLU", "XLV", "XLI",
                "XLP", "XLY", "XLB", "XLRE", "XLC", "MDY"]
        return {s: _make_bars(s, n=120, seed=hash(s) % 1000) for s in syms}

    async def test_backfill_creates_macro_file(self):
        """backfill_macro_history must create __MACRO__.parquet."""
        from data.history_backfill import backfill_macro_history
        vix = _make_vix_bars(120)
        tnx = _make_vix_bars(120, base=4.3)
        bars = self._macro_bars()
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.macro_history._MACRO_FILE",
                   os.path.join(tmpdir, "__MACRO__.parquet")), \
             patch("data.history_backfill._HISTORY_DIR", tmpdir), \
             patch("data.history_backfill.alpaca_client",
                   _mock_alpaca(bars)), \
             patch("data.history_backfill.yf") as mock_yf:
            mock_yf.download.side_effect = _mock_yf(vix, tnx)
            result = await backfill_macro_history(days=90)
            # Check file existence inside the with block (tmpdir is cleaned up on exit)
            self.assertGreater(result["rows_added"], 0)
            self.assertTrue(os.path.exists(
                os.path.join(tmpdir, "__MACRO__.parquet")))

    async def test_backfill_rows_have_correct_columns(self):
        """Each macro backfill row must have all MACRO_COLUMNS."""
        from data.history_backfill import backfill_macro_history
        from data.macro_history import MACRO_COLUMNS
        vix = _make_vix_bars(120)
        tnx = _make_vix_bars(120, base=4.3)
        bars = self._macro_bars()
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.macro_history._MACRO_FILE",
                   os.path.join(tmpdir, "__MACRO__.parquet")), \
             patch("data.history_backfill._HISTORY_DIR", tmpdir), \
             patch("data.history_backfill.alpaca_client",
                   _mock_alpaca(bars)), \
             patch("data.history_backfill.yf") as mock_yf:
            mock_yf.download.side_effect = _mock_yf(vix, tnx)
            await backfill_macro_history(days=90)
            df = pd.read_parquet(os.path.join(tmpdir, "__MACRO__.parquet"))
        for col in MACRO_COLUMNS:
            self.assertIn(col, df.columns, f"Missing: {col}")

    async def test_macro_backfill_is_idempotent(self):
        """Re-running macro backfill must not add duplicate rows."""
        from data.history_backfill import backfill_macro_history
        vix = _make_vix_bars(120)
        tnx = _make_vix_bars(120, base=4.3)
        bars = self._macro_bars()
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.macro_history._MACRO_FILE",
                   os.path.join(tmpdir, "__MACRO__.parquet")), \
             patch("data.history_backfill._HISTORY_DIR", tmpdir), \
             patch("data.history_backfill.alpaca_client",
                   _mock_alpaca(bars)), \
             patch("data.history_backfill.yf") as mock_yf:
            mock_yf.download.side_effect = _mock_yf(vix, tnx)
            r1 = await backfill_macro_history(days=90)
            r2 = await backfill_macro_history(days=90)
        self.assertEqual(r2["rows_added"], 0, "Re-run must not add duplicates")

    async def test_macro_backfill_handles_missing_vix(self):
        """Missing VIX data must not crash — VIX stores NaN."""
        from data.history_backfill import backfill_macro_history
        bars = self._macro_bars()
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.macro_history._MACRO_FILE",
                   os.path.join(tmpdir, "__MACRO__.parquet")), \
             patch("data.history_backfill._HISTORY_DIR", tmpdir), \
             patch("data.history_backfill.alpaca_client",
                   _mock_alpaca(bars)), \
             patch("data.history_backfill.yf") as mock_yf:
            mock_yf.download.return_value = pd.DataFrame()  # VIX unavailable
            result = await backfill_macro_history(days=90)
        # Should still succeed; just VIX will be NaN
        self.assertGreaterEqual(result["rows_added"], 0)


# ── CNN channel integration ───────────────────────────────────────────────────

class TestMacroCNNChannels(unittest.TestCase):

    def test_n_channels_is_15(self):
        """N_CHANNELS must be 15 after adding 5 macro channels."""
        from data.cnn_model import N_CHANNELS
        self.assertEqual(N_CHANNELS, 15)

    def test_macro_channel_names_defined(self):
        """MACRO_CHANNEL_NAMES must be a list of 5 strings."""
        from data.cnn_model import MACRO_CHANNEL_NAMES
        self.assertEqual(len(MACRO_CHANNEL_NAMES), 5)

    def test_build_training_windows_degrades_without_macro(self):
        """build_training_windows must return 10 channels when macro absent."""
        import time
        from data.cnn_model import build_training_windows, WINDOW_SIZE
        n = 120
        now = time.time()
        rows = []
        for i in range(n):
            row = {
                "symbol": "AAPL",
                "snapshot_ts": now - (n - i) * 3600,
                "analyst_score": 0.0, "earnings_score": 0.0,
                "alpaca_score": 0.0, "yahoo_score": 0.0,
                "congress_score": 0.0, "iv_rv_score": 0.0,
                "composite_score": 0.0, "price": 100.0,
                "return_1d": 0.01, "return_5d": 0.02,
                "agent_consensus": 0.0, "agent_agreement": 0.5,
                "rv_20d": 0.15, "rv_60d": 0.18,
            }
            rows.append(row)
        import pandas as pd
        df = pd.DataFrame(rows)
        X, y, w = build_training_windows(df, T=WINDOW_SIZE)
        # No macro columns in df → degrades to 10 channels (no macro)
        self.assertEqual(X.shape[1], 10)

    def test_build_training_windows_uses_macro_when_present(self):
        """build_training_windows must return 15 channels when macro cols present."""
        import time
        from data.cnn_model import build_training_windows, WINDOW_SIZE, N_CHANNELS
        n = 120
        now = time.time()
        rows = []
        for i in range(n):
            row = {
                "symbol": "AAPL",
                "snapshot_ts": now - (n - i) * 3600,
                "analyst_score": 0.0, "earnings_score": 0.0,
                "alpaca_score": 0.0, "yahoo_score": 0.0,
                "congress_score": 0.0, "iv_rv_score": 0.0,
                "composite_score": 0.0, "price": 100.0,
                "return_1d": 0.01, "return_5d": 0.02,
                "agent_consensus": 0.0, "agent_agreement": 0.5,
                "rv_20d": 0.15, "rv_60d": 0.18,
                # macro channels
                "macro_vix_norm": 0.6, "macro_gld_5d": 0.01,
                "macro_tlt_5d": -0.005, "macro_spy_5d": 0.02,
                "macro_breadth": 0.005,
            }
            rows.append(row)
        import pandas as pd
        df = pd.DataFrame(rows)
        X, y, w = build_training_windows(df, T=WINDOW_SIZE)
        self.assertEqual(X.shape[1], N_CHANNELS)  # 15


if __name__ == "__main__":
    unittest.main()
