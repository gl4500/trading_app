"""
Unit tests for trading/risk_manager.py
Covers: position size limits, concentration limits, daily loss halt,
        sell validation, max shares calculation.
"""
import sys
import os
import unittest

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from trading.portfolio import Portfolio
from trading.risk_manager import RiskManager


def _portfolio_with_position(symbol, shares, avg_cost, cash=50_000):
    p = Portfolio(starting_capital=cash + shares * avg_cost)
    p.execute_buy(symbol, shares, avg_cost)
    return p


class TestRiskManagerBuy(unittest.TestCase):

    def setUp(self):
        self.rm = RiskManager(max_position_size=0.15, daily_loss_limit=0.05)
        self.p = Portfolio(starting_capital=100_000)
        self.prices = {"AAPL": 100.0}

    def test_normal_buy_allowed(self):
        allowed, reason = self.rm.check_buy_allowed("AAPL", 10, 100.0, self.p, self.prices)
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_exceeds_max_position_size_denied(self):
        # 200 shares @ $100 = $20,000 = 20% of $100k portfolio → over 15% limit
        allowed, reason = self.rm.check_buy_allowed("AAPL", 200, 100.0, self.p, self.prices)
        self.assertFalse(allowed)
        self.assertIn("Position size limit", reason)

    def test_insufficient_cash_denied(self):
        # Build a portfolio with a large MSFT position to keep total value high, then
        # drain cash to $500 so the cash check fires before the position size check.
        p = Portfolio(starting_capital=100_000)
        p.execute_buy("MSFT", 900, 100.0)  # cash: $100k → $10k, MSFT position: $90k
        p.cash = 500  # only $500 cash remaining
        prices = {"AAPL": 100.0, "MSFT": 100.0}
        # 10 AAPL @ $100 = $1,000 ≈ 1.1% of ~$90.5k total → passes 15% position limit
        # but $1,000 > $500 cash → Insufficient cash fires
        allowed, reason = self.rm.check_buy_allowed("AAPL", 10, 100.0, p, prices)
        self.assertFalse(allowed)
        self.assertIn("Insufficient cash", reason)

    def test_short_selling_denied(self):
        allowed, reason = self.rm.check_buy_allowed("AAPL", -10, 100.0, self.p, self.prices)
        self.assertFalse(allowed)
        self.assertIn("Short selling not allowed", reason)

    def test_zero_portfolio_value_denied(self):
        p = Portfolio(starting_capital=0)
        p.cash = 0
        allowed, reason = self.rm.check_buy_allowed("AAPL", 1, 100.0, p, {"AAPL": 100.0})
        self.assertFalse(allowed)

    def test_trading_halted_buy_denied(self):
        self.rm._trading_halted = True
        self.rm._halt_reason = "daily loss"
        allowed, _ = self.rm.check_buy_allowed("AAPL", 10, 100.0, self.p, self.prices)
        self.assertFalse(allowed)

    def test_concentration_limit_denied(self):
        # Use max_position_size=0.20 so 16% passes the position-size check but
        # still fails the hardcoded 15% concentration limit that fires next.
        rm = RiskManager(max_position_size=0.20)
        # 16 shares @ $1,000 = $16,000 = 16% of $100k portfolio > 15% concentration
        allowed, reason = rm.check_buy_allowed("AAPL", 16, 1_000.0, self.p, {"AAPL": 1_000.0})
        self.assertFalse(allowed)
        self.assertIn("Concentration limit", reason)


class TestRiskManagerSell(unittest.TestCase):

    def setUp(self):
        self.rm = RiskManager()
        self.p = _portfolio_with_position("AAPL", 100, 100.0)

    def test_valid_sell_allowed(self):
        allowed, reason = self.rm.check_sell_allowed("AAPL", 50, self.p)
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_sell_full_position_allowed(self):
        allowed, _ = self.rm.check_sell_allowed("AAPL", 100, self.p)
        self.assertTrue(allowed)

    def test_no_position_denied(self):
        allowed, reason = self.rm.check_sell_allowed("MSFT", 10, self.p)
        self.assertFalse(allowed)
        self.assertIn("No position", reason)

    def test_oversell_denied(self):
        allowed, reason = self.rm.check_sell_allowed("AAPL", 200, self.p)
        self.assertFalse(allowed)
        self.assertIn("Cannot sell", reason)

    def test_zero_shares_denied(self):
        allowed, reason = self.rm.check_sell_allowed("AAPL", 0, self.p)
        self.assertFalse(allowed)
        self.assertIn("Invalid share count", reason)


class TestDailyLossLimit(unittest.TestCase):

    def setUp(self):
        self.rm = RiskManager(daily_loss_limit=0.05)

    def test_no_loss_allowed(self):
        p = Portfolio(starting_capital=100_000)
        result = self.rm.check_daily_loss(p, {})
        self.assertTrue(result)

    def test_small_loss_allowed(self):
        p = Portfolio(starting_capital=100_000)
        p.daily_starting_value = 100_000
        p.cash = 97_000  # 3% loss — within limit
        result = self.rm.check_daily_loss(p, {})
        self.assertTrue(result)

    def test_exceeds_loss_limit_halts(self):
        p = Portfolio(starting_capital=100_000)
        p.daily_starting_value = 100_000
        p.cash = 90_000  # 10% loss — exceeds 5% limit
        result = self.rm.check_daily_loss(p, {})
        self.assertFalse(result)
        self.assertTrue(self.rm._trading_halted)

    def test_reset_daily_halt(self):
        self.rm._trading_halted = True
        self.rm._halt_reason = "test"
        self.rm.reset_daily_halt()
        self.assertFalse(self.rm._trading_halted)
        allowed, _ = self.rm.is_trading_allowed()
        self.assertTrue(allowed)


class TestGetMaxBuyShares(unittest.TestCase):

    def test_max_shares_respects_position_limit(self):
        rm = RiskManager(max_position_size=0.10)
        p = Portfolio(starting_capital=100_000)
        # Max 10% of 100k = $10k / $100 = 100 shares at full confidence
        shares = rm.get_max_buy_shares("AAPL", 100.0, 1.0, p, {"AAPL": 100.0})
        self.assertAlmostEqual(shares, 100.0, places=0)

    def test_max_shares_scaled_by_confidence(self):
        rm = RiskManager(max_position_size=0.10)
        p = Portfolio(starting_capital=100_000)
        shares_full = rm.get_max_buy_shares("AAPL", 100.0, 1.0, p, {"AAPL": 100.0})
        shares_half = rm.get_max_buy_shares("AAPL", 100.0, 0.5, p, {"AAPL": 100.0})
        self.assertAlmostEqual(shares_half, shares_full * 0.5, places=0)

    def test_zero_price_returns_zero(self):
        rm = RiskManager()
        p = Portfolio(starting_capital=100_000)
        shares = rm.get_max_buy_shares("AAPL", 0, 1.0, p, {})
        self.assertEqual(shares, 0)


from datetime import datetime, timedelta, timezone


class TestChurnCooloff(unittest.TestCase):
    """Churn prevention: re-entry within cooloff window is blocked."""

    def setUp(self):
        self.rm = RiskManager()
        self.p = Portfolio(starting_capital=100_000)

    def test_reentry_blocked_after_recent_sell(self):
        self.p.execute_buy("AAPL", 10, 100.0)
        self.p.execute_sell("AAPL", 10, 105.0)
        allowed, reason = self.rm.check_buy_allowed("AAPL", 5, 100.0, self.p, {"AAPL": 100.0})
        self.assertFalse(allowed)
        self.assertIn("Churn", reason)

    def test_reentry_allowed_after_cooloff_expires(self):
        self.p.execute_buy("AAPL", 10, 100.0)
        self.p.execute_sell("AAPL", 10, 105.0)
        self.p._recent_exits["AAPL"] = datetime.now(timezone.utc) - timedelta(minutes=31)
        allowed, _ = self.rm.check_buy_allowed("AAPL", 5, 100.0, self.p, {"AAPL": 100.0})
        self.assertTrue(allowed)

    def test_first_buy_not_blocked(self):
        allowed, _ = self.rm.check_buy_allowed("AAPL", 5, 100.0, self.p, {"AAPL": 100.0})
        self.assertTrue(allowed)

    def test_different_symbol_not_affected_by_cooloff(self):
        self.p.execute_buy("AAPL", 10, 100.0)
        self.p.execute_sell("AAPL", 10, 105.0)
        allowed, _ = self.rm.check_buy_allowed("MSFT", 5, 100.0, self.p, {"MSFT": 100.0})
        self.assertTrue(allowed)


class TestSectorConcentration(unittest.TestCase):
    """Sector concentration: no single sector > 35% of portfolio."""

    def setUp(self):
        self.rm = RiskManager()
        self.p = Portfolio(starting_capital=100_000)
        self.prices = {"MU": 100.0, "NVDA": 200.0, "AMD": 150.0, "LRCX": 300.0}

    def test_sector_concentration_blocked(self):
        # MU + NVDA = 30% in Technology already
        self.p.execute_buy("MU", 150, 100.0)    # $15k = 15%
        self.p.execute_buy("NVDA", 75, 200.0)   # $15k = 15% → sector=30%
        # Adding LRCX (also Technology) would push sector to ~43%
        allowed, reason = self.rm.check_buy_allowed("LRCX", 43, 300.0, self.p, self.prices)
        self.assertFalse(allowed)
        self.assertIn("Sector", reason)

    def test_sector_concentration_allowed_below_limit(self):
        self.p.execute_buy("MU", 100, 100.0)   # $10k = 10%
        allowed, _ = self.rm.check_buy_allowed("NVDA", 50, 200.0, self.p, self.prices)
        self.assertTrue(allowed)

    def test_unknown_sector_not_blocked(self):
        allowed, _ = self.rm.check_buy_allowed("ZZZZ", 5, 100.0, self.p, {"ZZZZ": 100.0})
        self.assertTrue(allowed)


class TestCorrelationGate(unittest.TestCase):
    """Markowitz correlation gate: blocks BUY when adding a symbol raises
    average pairwise portfolio correlation above CORRELATION_LIMIT."""

    def setUp(self):
        self.rm = RiskManager()
        self.p = Portfolio(starting_capital=100_000)
        # Two existing positions with enough cash remaining
        self.p.execute_buy("AAPL", 10, 100.0)
        self.p.execute_buy("MSFT", 10, 100.0)
        self.prices = {"AAPL": 100.0, "MSFT": 100.0, "NVDA": 100.0}

        rng = __import__("numpy.random", fromlist=["default_rng"]).default_rng(42)
        base = rng.standard_normal(60)

        # Highly correlated series — correlation ≈ 0.99
        self.corr_aapl = base + rng.standard_normal(60) * 0.02
        self.corr_msft = base + rng.standard_normal(60) * 0.02
        self.corr_nvda = base + rng.standard_normal(60) * 0.02   # same factor → correlated

        # Uncorrelated series — independent noise
        self.uncorr_aapl = rng.standard_normal(60)
        self.uncorr_msft = rng.standard_normal(60)
        self.uncorr_nvda = rng.standard_normal(60)

    def test_no_returns_provided_skips_gate(self):
        """portfolio_returns=None → gate skipped, buy allowed."""
        allowed, reason = self.rm.check_buy_allowed(
            "NVDA", 5, 100.0, self.p, self.prices, portfolio_returns=None
        )
        self.assertTrue(allowed, reason)

    def test_target_not_in_returns_skips_gate(self):
        """Target symbol absent from returns dict → gate skipped, buy allowed."""
        returns = {"AAPL": self.corr_aapl, "MSFT": self.corr_msft}
        # NVDA not in returns
        allowed, reason = self.rm.check_buy_allowed(
            "NVDA", 5, 100.0, self.p, self.prices, portfolio_returns=returns
        )
        self.assertTrue(allowed, reason)

    def test_no_held_positions_with_returns_skips_gate(self):
        """No existing positions have returns data → gate skipped."""
        p = Portfolio(starting_capital=100_000)
        returns = {"NVDA": self.corr_nvda}   # only target in returns, no holdings
        allowed, reason = self.rm.check_buy_allowed(
            "NVDA", 5, 100.0, p, {"NVDA": 100.0}, portfolio_returns=returns
        )
        self.assertTrue(allowed, reason)

    def test_allows_uncorrelated_asset(self):
        """Adding a low-correlation asset → buy allowed."""
        returns = {
            "AAPL": self.uncorr_aapl,
            "MSFT": self.uncorr_msft,
            "NVDA": self.uncorr_nvda,
        }
        allowed, reason = self.rm.check_buy_allowed(
            "NVDA", 5, 100.0, self.p, self.prices, portfolio_returns=returns
        )
        self.assertTrue(allowed, reason)

    def test_blocks_highly_correlated_asset(self):
        """Adding a highly correlated asset raises avg portfolio corr → buy blocked."""
        returns = {
            "AAPL": self.corr_aapl,
            "MSFT": self.corr_msft,
            "NVDA": self.corr_nvda,
        }
        allowed, reason = self.rm.check_buy_allowed(
            "NVDA", 5, 100.0, self.p, self.prices, portfolio_returns=returns
        )
        self.assertFalse(allowed)
        self.assertIn("Correlation", reason)

    def test_correlation_reason_includes_value(self):
        """Rejection reason must include the computed correlation value."""
        returns = {
            "AAPL": self.corr_aapl,
            "MSFT": self.corr_msft,
            "NVDA": self.corr_nvda,
        }
        _, reason = self.rm.check_buy_allowed(
            "NVDA", 5, 100.0, self.p, self.prices, portfolio_returns=returns
        )
        # Reason should contain a correlation value like "0.99"
        self.assertRegex(reason, r"0\.\d+")

    def test_single_held_position_still_checked(self):
        """Even with one held position + new symbol, gate still fires if correlated."""
        p = Portfolio(starting_capital=100_000)
        p.execute_buy("AAPL", 10, 100.0)
        returns = {
            "AAPL": self.corr_aapl,
            "NVDA": self.corr_nvda,
        }
        prices = {"AAPL": 100.0, "NVDA": 100.0}
        allowed, reason = self.rm.check_buy_allowed(
            "NVDA", 5, 100.0, p, prices, portfolio_returns=returns
        )
        self.assertFalse(allowed)
        self.assertIn("Correlation", reason)


if __name__ == "__main__":
    unittest.main()
