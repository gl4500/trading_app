"""Tests for data/split_adjuster.py — Backlog 0.2 stock-split detection + apply."""
import unittest
from unittest.mock import AsyncMock, MagicMock

from data.split_adjuster import (
    needs_split_adjustment,
    detect_and_apply_splits,
)
from trading.portfolio import Portfolio


class TestNeedsSplitAdjustment(unittest.TestCase):
    def test_pre_split_avg_cost_needs_adjustment(self):
        # BKNG bought pre-split at $4060, current (split-adjusted) price $200,
        # 20-for-1 split: $4060 / 20 = $203 → matches current → needs adjustment
        self.assertTrue(needs_split_adjustment(
            avg_cost=4060.0, current_price=200.0, ratio=20.0
        ))

    def test_post_split_avg_cost_already_adjusted(self):
        # avg_cost $200 already matches current $210 → already adjusted → skip
        self.assertFalse(needs_split_adjustment(
            avg_cost=200.0, current_price=210.0, ratio=20.0
        ))

    def test_no_match_either_way_does_not_apply(self):
        # avg_cost $1000, current $50, ratio 20 → rescaled $50 matches!
        # That's a true split case so should return True
        self.assertTrue(needs_split_adjustment(
            avg_cost=1000.0, current_price=50.0, ratio=20.0
        ))
        # But avg_cost $5000, current $50, ratio 20 → rescaled $250 ≠ $50 → false
        self.assertFalse(needs_split_adjustment(
            avg_cost=5000.0, current_price=50.0, ratio=20.0
        ))

    def test_invalid_inputs_return_false(self):
        self.assertFalse(needs_split_adjustment(0, 100.0, 2.0))
        self.assertFalse(needs_split_adjustment(100.0, 0, 2.0))
        self.assertFalse(needs_split_adjustment(100.0, 100.0, 0))
        self.assertFalse(needs_split_adjustment(-50.0, 100.0, 2.0))


class TestDetectAndApplySplits(unittest.IsolatedAsyncioTestCase):

    def _portfolio_with(self, sym: str, shares: float, avg_cost: float) -> Portfolio:
        p = Portfolio(starting_capital=100_000)
        p.execute_buy(sym, shares, avg_cost)
        return p

    async def test_applies_split_to_stale_position(self):
        # MeanReversionAgent-style: bought BKNG pre-split, avg_cost stale at $4060
        p = self._portfolio_with("BKNG", 2, 4060.0)
        client = MagicMock()
        client.get_recent_splits = AsyncMock(return_value=[
            {"symbol": "BKNG", "ratio": 20.0, "ex_date": None, "payable_date": None,
             "old_rate": 1.0, "new_rate": 20.0, "sub_type": "stock_split"},
        ])
        client.get_latest_prices = AsyncMock(return_value={"BKNG": 200.0})

        applied = await detect_and_apply_splits([p], ["MeanReversionAgent"], client)

        self.assertEqual(applied, 1)
        pos = p.positions["BKNG"]
        self.assertAlmostEqual(pos.shares, 40.0)
        self.assertAlmostEqual(pos.avg_cost, 203.0)

    async def test_skips_already_adjusted_position(self):
        # TechAgent-style: bought BKNG post-split, avg_cost already $192 — skip
        p = self._portfolio_with("BKNG", 53, 191.96)
        client = MagicMock()
        client.get_recent_splits = AsyncMock(return_value=[
            {"symbol": "BKNG", "ratio": 20.0, "ex_date": None, "payable_date": None,
             "old_rate": 1.0, "new_rate": 20.0, "sub_type": "stock_split"},
        ])
        client.get_latest_prices = AsyncMock(return_value={"BKNG": 200.0})

        applied = await detect_and_apply_splits([p], ["TechAgent"], client)

        self.assertEqual(applied, 0)
        pos = p.positions["BKNG"]
        self.assertEqual(pos.shares, 53)
        self.assertAlmostEqual(pos.avg_cost, 191.96)

    async def test_idempotent_second_call_does_not_double_apply(self):
        """Once a split is applied, calling again must NOT apply it again."""
        p = self._portfolio_with("BKNG", 2, 4060.0)
        client = MagicMock()
        client.get_recent_splits = AsyncMock(return_value=[
            {"symbol": "BKNG", "ratio": 20.0, "ex_date": None, "payable_date": None,
             "old_rate": 1.0, "new_rate": 20.0, "sub_type": "stock_split"},
        ])
        client.get_latest_prices = AsyncMock(return_value={"BKNG": 200.0})

        first  = await detect_and_apply_splits([p], ["MeanReversionAgent"], client)
        second = await detect_and_apply_splits([p], ["MeanReversionAgent"], client)

        self.assertEqual(first, 1)
        self.assertEqual(second, 0, "second call must be no-op (idempotent)")
        self.assertAlmostEqual(p.positions["BKNG"].shares, 40.0)

    async def test_applies_across_multiple_agents(self):
        """One stale, one already-adjusted — only the stale one gets corrected."""
        p_stale  = self._portfolio_with("BKNG", 2, 4060.0)
        p_clean  = self._portfolio_with("BKNG", 53, 191.96)
        client = MagicMock()
        client.get_recent_splits = AsyncMock(return_value=[
            {"symbol": "BKNG", "ratio": 20.0, "ex_date": None, "payable_date": None,
             "old_rate": 1.0, "new_rate": 20.0, "sub_type": "stock_split"},
        ])
        client.get_latest_prices = AsyncMock(return_value={"BKNG": 200.0})

        applied = await detect_and_apply_splits(
            [p_stale, p_clean], ["MeanRev", "Tech"], client
        )
        self.assertEqual(applied, 1)
        # Stale agent fixed
        self.assertAlmostEqual(p_stale.positions["BKNG"].shares, 40.0)
        self.assertAlmostEqual(p_stale.positions["BKNG"].avg_cost, 203.0)
        # Clean agent untouched
        self.assertEqual(p_clean.positions["BKNG"].shares, 53)
        self.assertAlmostEqual(p_clean.positions["BKNG"].avg_cost, 191.96)

    async def test_returns_zero_when_no_splits_in_window(self):
        p = self._portfolio_with("AAPL", 10, 150.0)
        client = MagicMock()
        client.get_recent_splits = AsyncMock(return_value=[])
        client.get_latest_prices = AsyncMock(return_value={"AAPL": 155.0})

        applied = await detect_and_apply_splits([p], ["X"], client)
        self.assertEqual(applied, 0)

    async def test_skips_when_current_price_unavailable(self):
        """Without a current price anchor, we can't safely apply — skip."""
        p = self._portfolio_with("BKNG", 2, 4060.0)
        client = MagicMock()
        client.get_recent_splits = AsyncMock(return_value=[
            {"symbol": "BKNG", "ratio": 20.0, "ex_date": None, "payable_date": None,
             "old_rate": 1.0, "new_rate": 20.0, "sub_type": "stock_split"},
        ])
        client.get_latest_prices = AsyncMock(return_value={})  # no price

        applied = await detect_and_apply_splits([p], ["X"], client)
        self.assertEqual(applied, 0)
        # Position untouched
        self.assertEqual(p.positions["BKNG"].shares, 2)
        self.assertAlmostEqual(p.positions["BKNG"].avg_cost, 4060.0)


if __name__ == "__main__":
    unittest.main()
