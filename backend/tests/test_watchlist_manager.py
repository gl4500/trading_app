"""Tests for WatchlistManager — fluid watchlist ranked by projected return."""
import importlib
import unittest
from unittest.mock import patch


def _fresh_manager():
    """Return a fresh WatchlistManager with a reloaded module (avoids singleton bleed)."""
    import data.watchlist_manager as wm_mod
    importlib.reload(wm_mod)
    return wm_mod.WatchlistManager()


# ── Scoring ───────────────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    """Unit-test _score_rec in isolation."""

    def setUp(self):
        self.wm = _fresh_manager()

    def _rec(self, action, confidence, price_target=0.0):
        return {"symbol": "X", "action": action, "confidence": confidence,
                "price_target": price_target, "reasoning": ""}

    def test_buy_with_price_target_upside(self):
        # 20% upside → score = 0.8 × 1.20 = 0.96
        score = self.wm._score_rec(self._rec("BUY", 0.8, price_target=120.0), current_price=100.0)
        self.assertAlmostEqual(score, 0.96, places=5)

    def test_buy_no_price_target(self):
        # upside = 0 → score = 0.7 × 1.0 = 0.7
        score = self.wm._score_rec(self._rec("BUY", 0.7), current_price=100.0)
        self.assertAlmostEqual(score, 0.7, places=5)

    def test_buy_price_target_below_current_no_penalty(self):
        # Target below current price → upside clamped at 0
        score = self.wm._score_rec(self._rec("BUY", 0.5, price_target=80.0), current_price=100.0)
        self.assertAlmostEqual(score, 0.5, places=5)

    def test_sell_rec(self):
        score = self.wm._score_rec(self._rec("SELL", 0.9), current_price=100.0)
        self.assertAlmostEqual(score, -0.9, places=5)

    def test_watch_rec(self):
        # 0.3 × 0.6 = 0.18
        score = self.wm._score_rec(self._rec("WATCH", 0.6), current_price=100.0)
        self.assertAlmostEqual(score, 0.18, places=5)

    def test_buy_zero_current_price_no_crash(self):
        # No price available → upside stays 0, no ZeroDivisionError
        score = self.wm._score_rec(self._rec("BUY", 0.5, price_target=150.0), current_price=0.0)
        self.assertAlmostEqual(score, 0.5, places=5)


# ── update_from_scan ──────────────────────────────────────────────────────────

class TestUpdateFromScan(unittest.TestCase):

    def setUp(self):
        self.wm = _fresh_manager()

    def _scan(self, recs=None, candidates=None):
        return {"status": "ok", "recommendations": recs or [], "candidates": candidates or []}

    def test_ignores_error_status(self):
        self.wm.update_from_scan({"status": "error", "recommendations": [], "candidates": []})
        self.assertEqual(self.wm.scored_pool, [])

    def test_ignores_none_input(self):
        self.wm.update_from_scan(None)
        self.assertEqual(self.wm.scored_pool, [])

    def test_populates_pool_from_recs(self):
        scan = self._scan(
            recs=[
                {"symbol": "AAPL", "action": "BUY", "confidence": 0.8, "price_target": 0, "reasoning": ""},
                {"symbol": "TSLA", "action": "SELL", "confidence": 0.7, "price_target": 0, "reasoning": ""},
            ]
        )
        self.wm.update_from_scan(scan)
        syms = {e["symbol"] for e in self.wm.scored_pool}
        self.assertIn("AAPL", syms)
        self.assertIn("TSLA", syms)

    def test_pool_includes_candidates_not_in_recs(self):
        scan = self._scan(
            recs=[{"symbol": "AAPL", "action": "BUY", "confidence": 0.8, "price_target": 0, "reasoning": ""}],
            candidates=[
                {"symbol": "AAPL", "price": 190.0, "pct_change": 2.0, "vol_ratio": 1.5, "momentum_score": 3.0},
                {"symbol": "NVDA", "price": 800.0, "pct_change": 1.0, "vol_ratio": 1.2, "momentum_score": 1.5},
            ],
        )
        self.wm.update_from_scan(scan)
        syms = {e["symbol"] for e in self.wm.scored_pool}
        self.assertIn("NVDA", syms)  # candidate-only symbol included

    def test_pool_sorted_descending_by_score(self):
        scan = self._scan(
            recs=[
                {"symbol": "HIGH", "action": "BUY", "confidence": 0.9, "price_target": 0, "reasoning": ""},
                {"symbol": "MED",  "action": "BUY", "confidence": 0.4, "price_target": 0, "reasoning": ""},
                {"symbol": "NEG",  "action": "SELL","confidence": 0.8, "price_target": 0, "reasoning": ""},
            ]
        )
        self.wm.update_from_scan(scan)
        scores = [e["score"] for e in self.wm.scored_pool]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_is_initialized_after_update(self):
        self.assertFalse(self.wm.is_initialized)
        self.wm.update_from_scan(self._scan(
            recs=[{"symbol": "A", "action": "BUY", "confidence": 0.5, "price_target": 0, "reasoning": ""}]
        ))
        self.assertTrue(self.wm.is_initialized)

    def test_rec_takes_priority_over_candidate_for_same_symbol(self):
        """A symbol with both a rec and a candidate entry should use rec's score."""
        scan = self._scan(
            recs=[{"symbol": "AAPL", "action": "BUY", "confidence": 0.8, "price_target": 0, "reasoning": ""}],
            candidates=[{"symbol": "AAPL", "price": 190.0, "pct_change": 2.0, "vol_ratio": 1.5, "momentum_score": 3.0}],
        )
        self.wm.update_from_scan(scan)
        aapl_entries = [e for e in self.wm.scored_pool if e["symbol"] == "AAPL"]
        self.assertEqual(len(aapl_entries), 1)
        self.assertEqual(aapl_entries[0]["action"], "BUY")


# ── get_active_watchlist ──────────────────────────────────────────────────────

class TestGetActiveWatchlist(unittest.TestCase):

    def setUp(self):
        self.wm = _fresh_manager()

    def _populate(self, buy_syms, sell_syms=None):
        recs = [
            {"symbol": s, "action": "BUY", "confidence": 0.8, "price_target": 0, "reasoning": ""}
            for s in buy_syms
        ] + [
            {"symbol": s, "action": "SELL", "confidence": 0.8, "price_target": 0, "reasoning": ""}
            for s in (sell_syms or [])
        ]
        self.wm.update_from_scan({"status": "ok", "recommendations": recs, "candidates": []})

    @patch("data.watchlist_manager.config")
    def test_anchors_always_first(self, mock_cfg):
        mock_cfg.WATCHLIST_ANCHORS = ["SPY"]
        mock_cfg.WATCHLIST_SIZE = 5
        mock_cfg.WATCHLIST = ["AAPL", "MSFT"]
        self._populate(["AAPL", "MSFT", "NVDA"])
        wl = self.wm.get_active_watchlist()
        self.assertEqual(wl[0], "SPY")

    @patch("data.watchlist_manager.config")
    def test_size_limit_respected(self, mock_cfg):
        mock_cfg.WATCHLIST_ANCHORS = ["SPY"]
        mock_cfg.WATCHLIST_SIZE = 5
        mock_cfg.WATCHLIST = ["SEED1", "SEED2", "SEED3", "SEED4", "SEED5"]
        self._populate(["A", "B", "C", "D", "E", "F", "G", "H"])
        wl = self.wm.get_active_watchlist()
        self.assertLessEqual(len(wl), 5)

    @patch("data.watchlist_manager.config")
    def test_fallback_to_seeds_when_pool_empty(self, mock_cfg):
        mock_cfg.WATCHLIST_ANCHORS = ["SPY"]
        mock_cfg.WATCHLIST_SIZE = 5
        mock_cfg.WATCHLIST = ["AAPL", "MSFT", "GOOGL"]
        # No scan data — pool is empty
        wl = self.wm.get_active_watchlist()
        self.assertIn("AAPL", wl)
        self.assertIn("MSFT", wl)

    @patch("data.watchlist_manager.config")
    def test_no_duplicates(self, mock_cfg):
        mock_cfg.WATCHLIST_ANCHORS = ["SPY"]
        mock_cfg.WATCHLIST_SIZE = 10
        mock_cfg.WATCHLIST = ["SPY", "AAPL", "MSFT"]  # SPY in seeds AND anchors
        self._populate(["SPY", "AAPL"])                # SPY in recs too
        wl = self.wm.get_active_watchlist()
        self.assertEqual(len(wl), len(set(wl)), "Watchlist contains duplicates")

    @patch("data.watchlist_manager.config")
    def test_buy_ranked_above_sell(self, mock_cfg):
        mock_cfg.WATCHLIST_ANCHORS = []
        mock_cfg.WATCHLIST_SIZE = 2
        mock_cfg.WATCHLIST = []
        self._populate(buy_syms=["NVDA"], sell_syms=["TSLA"])
        wl = self.wm.get_active_watchlist()
        # NVDA (BUY 0.8) should rank above TSLA (SELL -0.8)
        self.assertIn("NVDA", wl)
        if "TSLA" in wl and "NVDA" in wl:
            self.assertLess(wl.index("NVDA"), wl.index("TSLA"))

    @patch("data.watchlist_manager.config")
    def test_returns_list_of_strings(self, mock_cfg):
        mock_cfg.WATCHLIST_ANCHORS = ["SPY"]
        mock_cfg.WATCHLIST_SIZE = 5
        mock_cfg.WATCHLIST = ["AAPL"]
        self._populate(["MSFT"])
        wl = self.wm.get_active_watchlist()
        self.assertIsInstance(wl, list)
        for sym in wl:
            self.assertIsInstance(sym, str)


if __name__ == "__main__":
    unittest.main()
