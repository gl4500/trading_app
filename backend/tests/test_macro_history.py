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
                returns={"gld_1d": 0.005, "tlt_1d": -0.003, "spy_1d": 0.008,
                         "gld_5d_back":  0.012,
                         "tlt_5d_back": -0.008,
                         "spy_5d_back":  0.020,
                         "iwm_5d_back":  0.015,
                         "qqq_5d_back":  0.025,
                         "uup_5d_back":  0.002,
                         "uso_5d_back": -0.010},
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
                    "gld_1d","tlt_1d","spy_1d",
                    "gld_5d_back","tlt_5d_back","spy_5d_back",
                    "iwm_5d_back","qqq_5d_back","uup_5d_back","uso_5d_back"]},
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
                returns={"gld_1d": 0.0, "tlt_1d": 0.0, "spy_1d": 0.0,
                         "gld_5d_back": 0.0, "tlt_5d_back": 0.0,
                         "spy_5d_back": 0.01, "iwm_5d_back": 0.03,
                         "qqq_5d_back": 0.0, "uup_5d_back": 0.0,
                         "uso_5d_back": 0.0},
                regime="RISK_ON",
            )
            df = pd.read_parquet(os.path.join(tmpdir, "__MACRO__.parquet"))
        # breadth = 0.03 - 0.01 = 0.02, clamped to [-1, 1]
        self.assertAlmostEqual(df.iloc[0]["breadth_score_back"], 0.02, places=4)

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
                    "gld_1d","tlt_1d","spy_1d",
                    "gld_5d_back","tlt_5d_back","spy_5d_back",
                    "iwm_5d_back","qqq_5d_back","uup_5d_back","uso_5d_back"]},
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
                    "gld_1d","tlt_1d","spy_1d",
                    "gld_5d_back","tlt_5d_back","spy_5d_back",
                    "iwm_5d_back","qqq_5d_back","uup_5d_back","uso_5d_back"]},
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
                returns={"gld_1d": 0.002, "tlt_1d": -0.001, "spy_1d": 0.003,
                         "gld_5d_back":  0.008,
                         "tlt_5d_back": -0.004,
                         "spy_5d_back":  0.012,
                         "iwm_5d_back":  0.010,
                         "qqq_5d_back":  0.015,
                         "uup_5d_back":  0.001,
                         "uso_5d_back": -0.005},
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

    def test_n_channels_is_14(self):
        """N_CHANNELS must be 14: 5 source + 2 agent + 2 RV + 5 macro.
        Was 15 before Task #20 demoted congressional_trades from CNN inputs."""
        from data.cnn_model import N_CHANNELS
        self.assertEqual(N_CHANNELS, 14)

    def test_macro_channel_names_defined(self):
        """MACRO_CHANNEL_NAMES must be a list of 5 strings."""
        from data.cnn_model import MACRO_CHANNEL_NAMES
        self.assertEqual(len(MACRO_CHANNEL_NAMES), 5)

    def test_build_training_windows_degrades_without_macro(self):
        """build_training_windows must return 9 channels when macro absent
        (5 source + 2 agent + 2 RV). Was 10 before Task #20 demoted congress."""
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
        # No macro columns in df → degrades to 9 channels (5 source + 2 agent + 2 RV)
        self.assertEqual(X.shape[1], 9)

    def test_build_training_windows_uses_macro_when_present(self):
        """build_training_windows must return 14 channels when macro cols present.
        Was 15 before Task #20 demoted congressional_trades from CNN inputs."""
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
                # macro channels (Task #24: trailing _back)
                "macro_vix_norm": 0.6, "macro_gld_5d_back": 0.01,
                "macro_tlt_5d_back": -0.005, "macro_spy_5d_back": 0.02,
                "macro_breadth_back": 0.005,
            }
            rows.append(row)
        import pandas as pd
        df = pd.DataFrame(rows)
        X, y, w = build_training_windows(df, T=WINDOW_SIZE)
        self.assertEqual(X.shape[1], N_CHANNELS)  # 14


# ── Task #24: backward-looking macro returns (lookahead-leak fix) ─────────────

class TestRetNdTrailing(unittest.TestCase):
    """Task #24: `_ret_nd_trailing` computes 5-day TRAILING returns
    (closes[idx] vs closes[idx-n_back]) instead of forward — required to
    eliminate lookahead leakage in CNN training.

    The original `_ret_nd(closes, idx, n_ahead)` looks at closes[idx+n_ahead],
    which leaks future SPY/GLD/TLT direction into the input for predicting
    return_1d. Trailing returns use only past data — safe at inference time."""

    def test_trailing_return_uses_past_close(self):
        """closes[idx-n_back] is the denominator; result reflects past move only."""
        from data.history_backfill import _ret_nd_trailing
        closes = np.array([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0])
        # idx=5, n_back=5  →  (closes[5] - closes[0]) / closes[0]
        # = (105 - 100) / 100 = 0.05
        self.assertAlmostEqual(_ret_nd_trailing(closes, 5, 5), 0.05, places=6)

    def test_trailing_return_zero_when_history_short(self):
        """idx - n_back < 0 → 0.0 (cannot compute, no historical anchor)."""
        from data.history_backfill import _ret_nd_trailing
        closes = np.array([100.0, 101.0, 102.0])
        self.assertEqual(_ret_nd_trailing(closes, 1, 5), 0.0)
        self.assertEqual(_ret_nd_trailing(closes, 0, 5), 0.0)

    def test_trailing_return_zero_when_anchor_nonpositive(self):
        """closes[idx-n_back] <= 0 → 0.0 (avoid division by zero / sign flip)."""
        from data.history_backfill import _ret_nd_trailing
        closes = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
        # idx=5, n_back=5: closes[0] = 0.0 → must return 0.0
        self.assertEqual(_ret_nd_trailing(closes, 5, 5), 0.0)

    def test_trailing_return_negative_when_price_dropped(self):
        from data.history_backfill import _ret_nd_trailing
        closes = np.array([110.0, 109.0, 108.0, 107.0, 106.0, 100.0])
        # idx=5, n_back=5: (100 - 110) / 110 ≈ -0.0909
        self.assertAlmostEqual(_ret_nd_trailing(closes, 5, 5), -10.0 / 110.0, places=6)


class TestMacroBackwardLookingSchema(unittest.TestCase):
    """Task #24: macro 5d return columns must use `_back` suffix and carry
    trailing semantics. Forward `gld_5d`, `tlt_5d`, `spy_5d`, `iwm_5d`,
    `breadth_score` are removed from MACRO_COLUMNS (and therefore from CNN
    input). Old on-disk parquets are unreadable by the new schema → forces
    re-backfill, which is the intended migration step."""

    def test_macro_columns_use_back_suffix(self):
        from data.macro_history import MACRO_COLUMNS
        for col in (
            "gld_5d_back", "tlt_5d_back", "spy_5d_back",
            "iwm_5d_back", "qqq_5d_back", "uup_5d_back", "uso_5d_back",
            "breadth_score_back",
        ):
            self.assertIn(col, MACRO_COLUMNS, f"Missing trailing column: {col}")

    def test_old_forward_5d_columns_removed(self):
        """The old forward-looking 5d/breadth columns are gone — re-backfill
        regenerates the parquet with trailing semantics."""
        from data.macro_history import MACRO_COLUMNS
        for col in ("gld_5d", "tlt_5d", "spy_5d", "iwm_5d",
                    "qqq_5d", "uup_5d", "uso_5d", "breadth_score"):
            self.assertNotIn(
                col, MACRO_COLUMNS,
                f"Old forward column {col} must be removed (Task #24)",
            )

    def test_macro_feature_cols_use_back_suffix(self):
        """The 4 return-based CNN feature names must end in _back."""
        from data.macro_history import MACRO_FEATURE_COLS
        self.assertIn("macro_vix_norm",     MACRO_FEATURE_COLS)  # level, no _back
        self.assertIn("macro_gld_5d_back",  MACRO_FEATURE_COLS)
        self.assertIn("macro_tlt_5d_back",  MACRO_FEATURE_COLS)
        self.assertIn("macro_spy_5d_back",  MACRO_FEATURE_COLS)
        self.assertIn("macro_breadth_back", MACRO_FEATURE_COLS)


class TestMacroBackwardLookingRecord(unittest.IsolatedAsyncioTestCase):
    """Task #24: record_snapshot accepts trailing keys in `returns` and writes
    them into the new schema columns."""

    async def test_record_writes_back_columns(self):
        from data.macro_history import MacroHistoryStore
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.macro_history._MACRO_FILE",
                   os.path.join(tmpdir, "__MACRO__.parquet")):
            store = MacroHistoryStore()
            await store.record_snapshot(
                date_ts=time.time(), vix=18.0, tnx=4.3,
                returns={
                    "gld_1d": 0.0, "tlt_1d": 0.0, "spy_1d": 0.0,
                    "gld_5d_back":  0.012,
                    "tlt_5d_back": -0.008,
                    "spy_5d_back":  0.020,
                    "iwm_5d_back":  0.025,
                    "qqq_5d_back":  0.018,
                    "uup_5d_back":  0.001,
                    "uso_5d_back": -0.005,
                },
                regime="RISK_ON",
            )
            df = pd.read_parquet(os.path.join(tmpdir, "__MACRO__.parquet"))
        self.assertAlmostEqual(df.iloc[0]["gld_5d_back"],  0.012, places=5)
        self.assertAlmostEqual(df.iloc[0]["tlt_5d_back"], -0.008, places=5)
        self.assertAlmostEqual(df.iloc[0]["spy_5d_back"],  0.020, places=5)
        self.assertAlmostEqual(df.iloc[0]["iwm_5d_back"],  0.025, places=5)
        # breadth_score_back = (iwm_5d_back - spy_5d_back) clipped to [-1, 1]
        self.assertAlmostEqual(df.iloc[0]["breadth_score_back"], 0.005, places=5)

    def test_get_features_returns_back_values(self):
        """get_features_for_date must read the new _back columns."""
        from data.macro_history import MacroHistoryStore, MACRO_FEATURE_COLS
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.macro_history._MACRO_FILE",
                   os.path.join(tmpdir, "__MACRO__.parquet")):
            store = MacroHistoryStore()
            ts = time.time()
            asyncio.run(store.record_snapshot(
                date_ts=ts, vix=18.0, tnx=4.2,
                returns={
                    "gld_1d": 0.0, "tlt_1d": 0.0, "spy_1d": 0.0,
                    "gld_5d_back":  0.011,
                    "tlt_5d_back": -0.004,
                    "spy_5d_back":  0.013,
                    "iwm_5d_back":  0.020,
                    "qqq_5d_back":  0.0,
                    "uup_5d_back":  0.0,
                    "uso_5d_back":  0.0,
                },
                regime="NEUTRAL",
            ))
            vec = store.get_features_for_date(ts)
        # Order matches MACRO_FEATURE_COLS:
        # [vix_norm, gld_5d_back, tlt_5d_back, spy_5d_back, breadth_back]
        self.assertEqual(len(vec), len(MACRO_FEATURE_COLS))
        self.assertAlmostEqual(vec[1],  0.011, places=5)
        self.assertAlmostEqual(vec[2], -0.004, places=5)
        self.assertAlmostEqual(vec[3],  0.013, places=5)
        self.assertAlmostEqual(vec[4],  0.020 - 0.013, places=5)


class TestBackfillUsesTrailingReturns(unittest.IsolatedAsyncioTestCase):
    """Task #24: backfill_macro_history must compute 5d returns as TRAILING,
    not forward. The first row in the parquet (oldest day, idx=0) cannot have
    a 5-day trailing anchor → its 5d_back values must be 0.0."""

    def _macro_bars(self):
        syms = ["GLD", "TLT", "UUP", "USO", "SPY", "IWM", "QQQ"]
        return {s: _make_bars(s, n=120, seed=hash(s) % 1000) for s in syms}

    async def test_backfill_writes_back_columns(self):
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
            await backfill_macro_history(days=90)
            df = pd.read_parquet(os.path.join(tmpdir, "__MACRO__.parquet"))
        for col in ("gld_5d_back", "tlt_5d_back", "spy_5d_back",
                    "iwm_5d_back", "breadth_score_back"):
            self.assertIn(col, df.columns)

    async def test_backfill_first_row_has_zero_trailing_return(self):
        """The very first SPY bar (idx=0 in bars) cannot anchor a 5-day
        trailing window — its *_back values must be 0.0. This proves we
        compute backward (no anchor) rather than forward (5 days ahead exist)."""
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
            # days=200 > 120 bars → cutoff includes the very oldest bar (idx=0).
            # That bar has no 5-day historical anchor → spy_5d_back must be 0.0.
            # If returns were forward, the same bar would have spy_5d != 0.0
            # (5 future bars exist) — so this test catches forward/backward swap.
            await backfill_macro_history(days=200)
            df = pd.read_parquet(os.path.join(tmpdir, "__MACRO__.parquet"))
        df = df.sort_values("date_ts").reset_index(drop=True)
        self.assertEqual(float(df.iloc[0]["spy_5d_back"]), 0.0)
        self.assertEqual(float(df.iloc[0]["gld_5d_back"]), 0.0)
        self.assertEqual(float(df.iloc[0]["tlt_5d_back"]), 0.0)


class TestSignalHistoryMacroCoexistence(unittest.TestCase):
    """Verify signal_history ignores __MACRO__.parquet when listing symbols."""

    def test_symbols_with_data_excludes_macro_file(self):
        """symbols_with_data must not return __MACRO__ as a tradeable symbol."""
        from data.signal_history import SignalHistoryStore
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.signal_history._HISTORY_DIR", tmpdir):
            # Write a fake __MACRO__.parquet in the history dir
            import pandas as pd
            mac_path = os.path.join(tmpdir, "__MACRO__.parquet")
            pd.DataFrame({"date_ts": [1.0], "vix": [18.0]}).to_parquet(mac_path)
            store = SignalHistoryStore()
            syms = store.symbols_with_data()
        self.assertNotIn("__MACRO__", syms)

    def test_get_training_data_skips_macro_file(self):
        """get_training_data must not crash when __MACRO__.parquet is present."""
        from data.signal_history import SignalHistoryStore
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch("data.signal_history._HISTORY_DIR", tmpdir):
            import pandas as pd
            mac_path = os.path.join(tmpdir, "__MACRO__.parquet")
            pd.DataFrame({"date_ts": [1.0], "vix": [18.0]}).to_parquet(mac_path)
            store = SignalHistoryStore()
            df = store.get_training_data()   # must not raise KeyError
        self.assertIsNotNone(df)


if __name__ == "__main__":
    unittest.main()
