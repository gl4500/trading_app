"""
Unit tests for trading/portfolio.py
Covers: buy/sell execution, cash tracking, avg cost averaging,
        metrics calculation, Sharpe ratio, max drawdown.
"""
import sys
import os
import time
import unittest
from datetime import datetime, timedelta

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from trading.portfolio import Portfolio, Position, TradeRecord
from api.schemas import PositionSummary


PRICES = {"AAPL": 150.0, "MSFT": 300.0, "GOOGL": 2800.0}


class TestPortfolioInit(unittest.TestCase):

    def test_starting_cash(self):
        p = Portfolio(starting_capital=100_000)
        self.assertEqual(p.cash, 100_000)

    def test_no_positions_at_start(self):
        p = Portfolio(starting_capital=100_000)
        self.assertEqual(len(p.positions), 0)

    def test_total_value_all_cash(self):
        p = Portfolio(starting_capital=100_000)
        self.assertEqual(p.get_total_value(PRICES), 100_000)


class TestPortfolioBuy(unittest.TestCase):

    def setUp(self):
        self.p = Portfolio(starting_capital=100_000)

    def test_buy_reduces_cash(self):
        self.p.execute_buy("AAPL", 10, 150.0)
        self.assertAlmostEqual(self.p.cash, 100_000 - 1_500)

    def test_buy_creates_position(self):
        self.p.execute_buy("AAPL", 10, 150.0)
        self.assertIn("AAPL", self.p.positions)
        self.assertEqual(self.p.positions["AAPL"].shares, 10)

    def test_buy_sets_avg_cost(self):
        self.p.execute_buy("AAPL", 10, 150.0)
        self.assertEqual(self.p.positions["AAPL"].avg_cost, 150.0)

    def test_buy_avg_cost_averaging(self):
        # Buy 10 @ 100, then 10 @ 200 → avg = 150
        self.p.execute_buy("AAPL", 10, 100.0)
        self.p.execute_buy("AAPL", 10, 200.0)
        self.assertAlmostEqual(self.p.positions["AAPL"].avg_cost, 150.0)
        self.assertEqual(self.p.positions["AAPL"].shares, 20)

    def test_buy_insufficient_cash_returns_false(self):
        result = self.p.execute_buy("AAPL", 10_000, 150.0)  # costs $1.5M
        self.assertFalse(result)

    def test_buy_insufficient_cash_cash_unchanged(self):
        self.p.execute_buy("AAPL", 10_000, 150.0)
        self.assertEqual(self.p.cash, 100_000)

    def test_buy_appends_trade_record(self):
        self.p.execute_buy("AAPL", 10, 150.0)
        self.assertEqual(len(self.p.trade_history), 1)
        self.assertEqual(self.p.trade_history[0].action, "BUY")

    def test_total_value_includes_position(self):
        self.p.execute_buy("AAPL", 10, 150.0)
        # 98500 cash + 10 * 160 (current price) = 100100
        val = self.p.get_total_value({"AAPL": 160.0})
        self.assertAlmostEqual(val, 98_500 + 1_600)


class TestPortfolioSell(unittest.TestCase):

    def setUp(self):
        self.p = Portfolio(starting_capital=100_000)
        self.p.execute_buy("AAPL", 100, 100.0)   # cost $10,000; cash = $90,000

    def test_sell_increases_cash(self):
        self.p.execute_sell("AAPL", 50, 120.0)
        self.assertAlmostEqual(self.p.cash, 90_000 + 6_000)

    def test_sell_reduces_position(self):
        self.p.execute_sell("AAPL", 50, 120.0)
        self.assertEqual(self.p.positions["AAPL"].shares, 50)

    def test_full_sell_removes_position(self):
        self.p.execute_sell("AAPL", 100, 120.0)
        self.assertNotIn("AAPL", self.p.positions)

    def test_sell_pnl_recorded(self):
        self.p.execute_sell("AAPL", 100, 120.0)
        sell_trade = [t for t in self.p.trade_history if t.action == "SELL"][0]
        self.assertAlmostEqual(sell_trade.pnl, 2_000.0)   # (120-100)*100

    def test_sell_no_position_returns_false(self):
        result = self.p.execute_sell("GOOGL", 10, 2800.0)
        self.assertFalse(result)

    def test_sell_clamps_to_held_shares(self):
        # Request 200 shares, only 100 held — should sell 100
        self.p.execute_sell("AAPL", 200, 120.0)
        self.assertNotIn("AAPL", self.p.positions)


class TestPortfolioMetrics(unittest.TestCase):

    def setUp(self):
        self.p = Portfolio(starting_capital=100_000)

    def test_win_rate_no_trades(self):
        m = self.p.calculate_metrics(PRICES)
        self.assertEqual(m["win_rate"], 0.0)

    def test_win_rate_all_winners(self):
        self.p.execute_buy("AAPL", 100, 100.0)
        self.p.execute_sell("AAPL", 100, 110.0)   # profit
        m = self.p.calculate_metrics(PRICES)
        self.assertAlmostEqual(m["win_rate"], 100.0)

    def test_win_rate_mixed(self):
        self.p.execute_buy("AAPL", 50, 100.0)
        self.p.execute_sell("AAPL", 50, 110.0)    # winner
        self.p.execute_buy("MSFT", 10, 300.0)
        self.p.execute_sell("MSFT", 10, 280.0)    # loser
        m = self.p.calculate_metrics(PRICES)
        self.assertAlmostEqual(m["win_rate"], 50.0)

    def test_total_return_pct_positive(self):
        self.p.execute_buy("AAPL", 100, 100.0)
        self.p.execute_sell("AAPL", 100, 200.0)
        m = self.p.calculate_metrics(PRICES)
        self.assertGreater(m["total_return_pct"], 0)

    def test_total_return_pct_negative(self):
        self.p.execute_buy("AAPL", 100, 100.0)
        self.p.execute_sell("AAPL", 100, 50.0)
        m = self.p.calculate_metrics(PRICES)
        self.assertLess(m["total_return_pct"], 0)

    def test_positions_in_metrics(self):
        self.p.execute_buy("AAPL", 10, 150.0)
        m = self.p.calculate_metrics({"AAPL": 160.0})
        self.assertEqual(len(m["positions"]), 1)
        self.assertEqual(m["positions"][0]["symbol"], "AAPL")


# ──────────────────────────────────────────────────────────────────────────
# Issue #69 — Portfolio.calculate_metrics split into 3 focused helpers.
# Each helper returns only its own concern and is independently callable.
# ──────────────────────────────────────────────────────────────────────────

class TestPerformanceSummary(unittest.TestCase):
    """performance_summary(prices) returns aggregate scalars ONLY — no
    `positions` list and no `avg_mae`/`avg_mfe`/`avg_captured_pct` keys."""

    def setUp(self):
        self.p = Portfolio(starting_capital=100_000)

    def test_returns_aggregate_scalars_only(self):
        # Build some history so every scalar is non-trivial.
        self.p.execute_buy("AAPL", 100, 100.0)
        self.p.execute_sell("AAPL", 100, 110.0)  # winning trade
        self.p.execute_buy("MSFT", 10, 300.0)
        self.p.execute_sell("MSFT", 10, 280.0)   # losing trade
        self.p.execute_buy("GOOGL", 1, 2800.0)   # open position

        perf = self.p.performance_summary(PRICES)

        # Must be a plain dict (not a dataclass) — it's the "performance" slice.
        self.assertIsInstance(perf, dict)

        # Exact required scalar fields:
        expected_keys = {
            "total_value", "cash", "position_value",
            "total_return", "total_return_pct", "realized_pnl",
            "win_rate", "sharpe_ratio", "max_drawdown",
            "total_trades", "winning_trades", "losing_trades",
        }
        self.assertEqual(set(perf.keys()), expected_keys)

        # Must NOT contain the position list or excursion fields.
        self.assertNotIn("positions", perf)
        self.assertNotIn("avg_mae", perf)
        self.assertNotIn("avg_mfe", perf)
        self.assertNotIn("avg_captured_pct", perf)

        # Sanity-check a couple of values match calculate_metrics().
        m = self.p.calculate_metrics(PRICES)
        self.assertAlmostEqual(perf["total_value"], m["total_value"])
        self.assertAlmostEqual(perf["realized_pnl"], m["realized_pnl"])
        self.assertEqual(perf["winning_trades"], m["winning_trades"])


class TestPositionSummaries(unittest.TestCase):
    """position_summaries(prices) returns a list of PositionSummary
    dataclass instances (one per open position)."""

    def setUp(self):
        self.p = Portfolio(starting_capital=100_000)

    def test_returns_list_of_PositionSummary(self):
        self.p.execute_buy("AAPL", 10, 150.0)
        self.p.execute_buy("MSFT", 5, 300.0)

        summaries = self.p.position_summaries({"AAPL": 160.0, "MSFT": 310.0})

        self.assertIsInstance(summaries, list)
        self.assertEqual(len(summaries), 2)
        for s in summaries:
            self.assertIsInstance(s, PositionSummary)

        by_sym = {s.symbol: s for s in summaries}
        self.assertEqual(by_sym["AAPL"].shares, 10)
        self.assertEqual(by_sym["AAPL"].current_price, 160.0)
        self.assertAlmostEqual(by_sym["AAPL"].current_value, 1600.0)
        self.assertAlmostEqual(by_sym["AAPL"].unrealized_pnl, 100.0)


class TestExcursionStats(unittest.TestCase):
    """excursion_stats() takes no `prices` arg and returns ONLY the three
    MAE/MFE/captured fields — all derived from closed trade_history."""

    def setUp(self):
        self.p = Portfolio(starting_capital=100_000)

    def test_returns_three_fields(self):
        # No trades yet → all three fields should be zero, dict shape exact.
        stats = self.p.excursion_stats()
        self.assertIsInstance(stats, dict)
        self.assertEqual(set(stats.keys()), {"avg_mae", "avg_mfe", "avg_captured_pct"})
        self.assertEqual(stats["avg_mae"], 0.0)
        self.assertEqual(stats["avg_mfe"], 0.0)
        self.assertEqual(stats["avg_captured_pct"], 0.0)

    def test_values_match_calculate_metrics(self):
        # Build a trade that exercises MFE/MAE.
        self.p.execute_buy("AAPL", 10, 100.0)
        self.p.record_value({"AAPL": 130.0})   # MFE peak +30%
        self.p.record_value({"AAPL": 90.0})    # MAE dip -10%
        self.p.execute_sell("AAPL", 10, 120.0)  # exit +20%

        stats = self.p.excursion_stats()
        m = self.p.calculate_metrics({"AAPL": 120.0})
        self.assertAlmostEqual(stats["avg_mae"], m["avg_mae"])
        self.assertAlmostEqual(stats["avg_mfe"], m["avg_mfe"])
        self.assertAlmostEqual(stats["avg_captured_pct"], m["avg_captured_pct"])


class TestSharpeRatio(unittest.TestCase):

    def test_sharpe_too_few_records(self):
        p = Portfolio(starting_capital=100_000)
        # Only initial record — not enough
        self.assertEqual(p._calculate_sharpe(), 0.0)

    def test_sharpe_returns_float(self):
        p = Portfolio(starting_capital=100_000)
        # Manufacture enough value history entries with timestamps spread over time
        base_time = datetime.utcnow() - timedelta(hours=2)
        p._value_history = [
            (base_time + timedelta(seconds=i * 60), 100_000 + i * 10)
            for i in range(20)
        ]
        result = p._calculate_sharpe()
        self.assertIsInstance(result, float)

    def test_sharpe_constant_returns_zero(self):
        # Flat portfolio → log(1) = 0 every step → std_dev = 0 → Sharpe = 0
        p = Portfolio(starting_capital=100_000)
        base_time = datetime.utcnow() - timedelta(hours=2)
        p._value_history = [
            (base_time + timedelta(seconds=i * 60), 100_000)
            for i in range(20)
        ]
        self.assertEqual(p._calculate_sharpe(), 0.0)

    def test_sharpe_uses_log_returns_not_simple(self):
        """Log returns are additive: ln(0.5) + ln(2.0) = 0 (true break-even).
        Simple returns would give (-0.5 + 1.0)/2 = +0.25 — a false positive.
        With log returns the mean ≈ 0, so Sharpe should be near 0 or negative
        (after subtracting risk-free rate) for an alternating -50%/+100% cycle.
        """
        import math
        p = Portfolio(starting_capital=100_000)
        base_time = datetime.utcnow() - timedelta(hours=4)
        # Alternating: 100k → 50k → 100k → 50k → ...
        vals = []
        for i in range(20):
            vals.append(100_000 if i % 2 == 0 else 50_000)
        p._value_history = [
            (base_time + timedelta(minutes=i * 10), v) for i, v in enumerate(vals)
        ]
        result = p._calculate_sharpe()
        self.assertIsInstance(result, float)
        # Log mean return ≈ 0 → after subtracting risk-free rate, Sharpe should be <= 0
        self.assertLessEqual(result, 0.1)


class TestMAEMFETracking(unittest.TestCase):
    """Tests for Maximum Adverse/Favorable Excursion tracking."""

    def setUp(self):
        self.p = Portfolio(starting_capital=100_000)

    def test_buy_initialises_trackers(self):
        self.p.execute_buy("AAPL", 10, 150.0)
        self.assertIn("AAPL", self.p._position_high)
        self.assertIn("AAPL", self.p._position_low)
        self.assertEqual(self.p._position_high["AAPL"], 150.0)
        self.assertEqual(self.p._position_low["AAPL"], 150.0)

    def test_record_value_updates_high(self):
        self.p.execute_buy("AAPL", 10, 150.0)
        self.p.record_value({"AAPL": 170.0})
        self.assertEqual(self.p._position_high["AAPL"], 170.0)
        self.assertEqual(self.p._position_low["AAPL"], 150.0)  # low unchanged

    def test_record_value_updates_low(self):
        self.p.execute_buy("AAPL", 10, 150.0)
        self.p.record_value({"AAPL": 130.0})
        self.assertEqual(self.p._position_low["AAPL"], 130.0)
        self.assertEqual(self.p._position_high["AAPL"], 150.0)  # high unchanged

    def test_sell_records_mfe_on_trade(self):
        self.p.execute_buy("AAPL", 10, 100.0)
        self.p.record_value({"AAPL": 130.0})   # peak
        self.p.execute_sell("AAPL", 10, 120.0)  # sell before peak
        sell = [t for t in self.p.trade_history if t.action == "SELL"][0]
        self.assertAlmostEqual(sell.mfe_pct, 30.0, places=1)  # peak was 30% above entry

    def test_sell_records_mae_on_trade(self):
        self.p.execute_buy("AAPL", 10, 100.0)
        self.p.record_value({"AAPL": 85.0})    # dip
        self.p.record_value({"AAPL": 110.0})   # recover
        self.p.execute_sell("AAPL", 10, 110.0)
        sell = [t for t in self.p.trade_history if t.action == "SELL"][0]
        self.assertAlmostEqual(sell.mae_pct, 15.0, places=1)  # dipped 15% below entry

    def test_sell_clears_trackers(self):
        self.p.execute_buy("AAPL", 10, 100.0)
        self.p.execute_sell("AAPL", 10, 110.0)
        self.assertNotIn("AAPL", self.p._position_high)
        self.assertNotIn("AAPL", self.p._position_low)

    def test_metrics_include_avg_mae_mfe(self):
        # Trade 1: entry 100, peak 120 (MFE=20%), dip 90 (MAE=10%), exit 115
        self.p.execute_buy("AAPL", 10, 100.0)
        self.p.record_value({"AAPL": 90.0})
        self.p.record_value({"AAPL": 120.0})
        self.p.execute_sell("AAPL", 10, 115.0)
        m = self.p.calculate_metrics({"AAPL": 115.0})
        self.assertIn("avg_mae", m)
        self.assertIn("avg_mfe", m)
        self.assertIn("avg_captured_pct", m)
        self.assertAlmostEqual(m["avg_mae"], 10.0, places=1)
        self.assertAlmostEqual(m["avg_mfe"], 20.0, places=1)

    def test_avg_captured_pct(self):
        # Entry 100, peak 120 (MFE=20%), exit 110 (gain=10%) → captured = 10/20 = 50%
        self.p.execute_buy("AAPL", 10, 100.0)
        self.p.record_value({"AAPL": 120.0})
        self.p.execute_sell("AAPL", 10, 110.0)
        m = self.p.calculate_metrics({"AAPL": 110.0})
        self.assertAlmostEqual(m["avg_captured_pct"], 50.0, places=0)

    def test_metrics_zero_when_no_trades(self):
        m = self.p.calculate_metrics(PRICES)
        self.assertEqual(m["avg_mae"], 0.0)
        self.assertEqual(m["avg_mfe"], 0.0)
        self.assertEqual(m["avg_captured_pct"], 0.0)


class TestMaxDrawdown(unittest.TestCase):

    def test_no_drawdown(self):
        p = Portfolio(starting_capital=100_000)
        # Monotonically increasing — no drawdown
        p._value_history = [
            (datetime.utcnow(), 100_000 + i * 1_000) for i in range(10)
        ]
        self.assertAlmostEqual(p._calculate_max_drawdown(), 0.0)

    def test_drawdown_calculated(self):
        p = Portfolio(starting_capital=100_000)
        # Peak 120k, then drops to 90k → drawdown = 25%
        p._value_history = [
            (datetime.utcnow(), 100_000),
            (datetime.utcnow(), 120_000),
            (datetime.utcnow(), 90_000),
        ]
        dd = p._calculate_max_drawdown()
        self.assertAlmostEqual(dd, 25.0, places=1)

    def test_value_history_pruned_at_2000(self):
        p = Portfolio(starting_capital=100_000)
        prices = {"AAPL": 100.0}
        for _ in range(2010):
            p.record_value(prices)
        self.assertLessEqual(len(p._value_history), 2000)


# ── Fractional Kelly Sizing ───────────────────────────────────────────────────

def _make_portfolio_with_trades(
    n_wins: int,
    n_losses: int,
    avg_win_pnl: float = 500.0,
    avg_loss_pnl: float = -200.0,
    starting_capital: float = 100_000.0,
) -> Portfolio:
    """Build a Portfolio whose trade_history contains the requested win/loss records."""
    from trading.portfolio import TradeRecord
    from datetime import datetime, timezone
    p = Portfolio(starting_capital=starting_capital)
    now = datetime.now(timezone.utc)
    for _ in range(n_wins):
        p.trade_history.append(TradeRecord(
            symbol="AAPL", action="SELL", shares=10,
            price=150.0, timestamp=now, pnl=avg_win_pnl,
        ))
    for _ in range(n_losses):
        p.trade_history.append(TradeRecord(
            symbol="AAPL", action="SELL", shares=10,
            price=130.0, timestamp=now, pnl=avg_loss_pnl,
        ))
    return p


class TestKellyFraction(unittest.TestCase):

    def test_fallback_when_fewer_than_10_trades(self):
        """< 10 closed trades → default 10 % fraction."""
        p = _make_portfolio_with_trades(n_wins=3, n_losses=3)
        self.assertAlmostEqual(p.kelly_fraction(), 0.10)

    def test_fallback_at_exactly_9_trades(self):
        p = _make_portfolio_with_trades(n_wins=5, n_losses=4)
        self.assertAlmostEqual(p.kelly_fraction(), 0.10)

    def test_kelly_positive_with_positive_edge(self):
        """60 % win-rate, avg_win > avg_loss → positive Kelly fraction."""
        p = _make_portfolio_with_trades(
            n_wins=12, n_losses=8,
            avg_win_pnl=600.0, avg_loss_pnl=-200.0,
        )
        f = p.kelly_fraction()
        self.assertGreater(f, 0.0)

    def test_kelly_is_quarter_kelly(self):
        """kelly_fraction() applies a 0.25 multiplier (quarter-Kelly)."""
        # win_rate=0.6, avg_win=500, avg_loss=200 (abs)
        # full Kelly = (0.6*500 - 0.4*200) / 500 = (300-80)/500 = 0.44
        # quarter Kelly = 0.44 * 0.25 = 0.11
        p = _make_portfolio_with_trades(
            n_wins=12, n_losses=8,
            avg_win_pnl=500.0, avg_loss_pnl=-200.0,
        )
        f = p.kelly_fraction()
        self.assertAlmostEqual(f, 0.11, places=2)

    def test_kelly_clamped_to_max_position_size(self):
        """Very high win-rate → Kelly capped at MAX_POSITION_SIZE."""
        p = _make_portfolio_with_trades(
            n_wins=19, n_losses=1,
            avg_win_pnl=1000.0, avg_loss_pnl=-50.0,
        )
        from config import config
        f = p.kelly_fraction()
        self.assertLessEqual(f, config.MAX_POSITION_SIZE)

    def test_kelly_clamped_to_minimum_2pct(self):
        """Very negative edge → Kelly floor 2 %."""
        p = _make_portfolio_with_trades(
            n_wins=2, n_losses=18,
            avg_win_pnl=100.0, avg_loss_pnl=-800.0,
        )
        f = p.kelly_fraction()
        self.assertGreaterEqual(f, 0.02)

    def test_kelly_all_wins(self):
        """All winning trades → still bounded by MAX_POSITION_SIZE."""
        p = _make_portfolio_with_trades(n_wins=15, n_losses=0)
        from config import config
        f = p.kelly_fraction()
        self.assertLessEqual(f, config.MAX_POSITION_SIZE)
        self.assertGreaterEqual(f, 0.02)

    def test_kelly_all_losses(self):
        """All losing trades → avg_win=0 is undefined, returns 10% default."""
        p = _make_portfolio_with_trades(n_wins=0, n_losses=15)
        f = p.kelly_fraction()
        # avg_win = 0 → Kelly undefined → fall back to 10% default
        self.assertAlmostEqual(f, 0.10)

    def test_kelly_custom_half_kelly(self):
        """Passing half_kelly=0.5 gives exactly 2× quarter-Kelly when clamping doesn't interfere."""
        # win_rate=0.5, avg_win=200, avg_loss=150
        # full_kelly = (0.5*200 - 0.5*150)/200 = 25/200 = 0.125
        # quarter = 0.125*0.25 = 0.03125  (between 2% floor and 15% cap)
        # half    = 0.125*0.50 = 0.0625   (still within bounds)
        p = _make_portfolio_with_trades(
            n_wins=10, n_losses=10,
            avg_win_pnl=200.0, avg_loss_pnl=-150.0,
        )
        quarter = p.kelly_fraction(half_kelly=0.25)
        half    = p.kelly_fraction(half_kelly=0.50)
        self.assertAlmostEqual(half, quarter * 2, places=4)

    def test_kelly_zero_avg_win_returns_default(self):
        """Trades with zero pnl → avg_win could be 0 — return 10% default."""
        from trading.portfolio import TradeRecord
        from datetime import datetime, timezone
        p = Portfolio(starting_capital=100_000)
        now = datetime.now(timezone.utc)
        for _ in range(15):
            p.trade_history.append(TradeRecord(
                symbol="AAPL", action="SELL", shares=10,
                price=150.0, timestamp=now, pnl=0.0,
            ))
        f = p.kelly_fraction()
        self.assertAlmostEqual(f, 0.10)


# ── Bayesian Confidence Tracking ─────────────────────────────────────────────

class TestBayesianConfidence(unittest.TestCase):
    """Within-trade Bayesian confidence update via logit-linear formula."""

    def setUp(self):
        self.p = Portfolio(starting_capital=100_000)

    # --- entry_confidence storage ---

    def test_execute_buy_stores_entry_confidence(self):
        self.p.execute_buy("AAPL", 10, 100.0, entry_confidence=0.8)
        self.assertAlmostEqual(self.p.positions["AAPL"].entry_confidence, 0.8)

    def test_execute_buy_default_entry_confidence_is_half(self):
        """No confidence supplied → uninformed prior 0.5."""
        self.p.execute_buy("AAPL", 10, 100.0)
        self.assertAlmostEqual(self.p.positions["AAPL"].entry_confidence, 0.5)

    def test_bayes_confidence_initialised_to_entry_confidence(self):
        self.p.execute_buy("AAPL", 10, 100.0, entry_confidence=0.7)
        self.assertAlmostEqual(self.p.positions["AAPL"].bayes_confidence, 0.7)

    def test_add_to_position_does_not_change_entry_confidence(self):
        """Averaging into a position must not overwrite the original entry_confidence."""
        self.p.execute_buy("AAPL", 10, 100.0, entry_confidence=0.75)
        self.p.execute_buy("AAPL", 5, 90.0, entry_confidence=0.50)
        self.assertAlmostEqual(self.p.positions["AAPL"].entry_confidence, 0.75)

    # --- live update via record_value ---

    def test_bayes_confidence_increases_on_price_gain(self):
        """Price rises after entry → posterior confidence rises."""
        self.p.execute_buy("AAPL", 10, 100.0, entry_confidence=0.5)
        self.p.record_value({"AAPL": 102.0})   # +2% gain
        self.assertGreater(self.p.positions["AAPL"].bayes_confidence, 0.5)

    def test_bayes_confidence_decreases_on_price_drop(self):
        """Price falls after entry → posterior confidence drops."""
        self.p.execute_buy("AAPL", 10, 100.0, entry_confidence=0.5)
        self.p.record_value({"AAPL": 98.0})    # −2% loss
        self.assertLess(self.p.positions["AAPL"].bayes_confidence, 0.5)

    def test_bayes_confidence_unchanged_on_flat_price(self):
        """No price move → posterior stays at prior."""
        self.p.execute_buy("AAPL", 10, 100.0, entry_confidence=0.6)
        self.p.record_value({"AAPL": 100.0})   # no change
        self.assertAlmostEqual(self.p.positions["AAPL"].bayes_confidence, 0.6, places=6)

    def test_bayes_confidence_clamped_above(self):
        """Repeated price gains must not push confidence above 0.99."""
        self.p.execute_buy("AAPL", 10, 100.0, entry_confidence=0.5)
        price = 100.0
        for _ in range(200):
            price *= 1.05
            self.p.record_value({"AAPL": price})
        self.assertLessEqual(self.p.positions["AAPL"].bayes_confidence, 0.99)

    def test_bayes_confidence_clamped_below(self):
        """Repeated price drops must not push confidence below 0.01."""
        self.p.execute_buy("AAPL", 10, 100.0, entry_confidence=0.5)
        price = 100.0
        for _ in range(200):
            price *= 0.95
            self.p.record_value({"AAPL": price})
        self.assertGreaterEqual(self.p.positions["AAPL"].bayes_confidence, 0.01)

    def test_bayes_confidence_cleared_on_sell(self):
        """Selling the full position must clean up the last-price tracker."""
        self.p.execute_buy("AAPL", 10, 100.0)
        self.p.record_value({"AAPL": 105.0})
        self.p.execute_sell("AAPL", 10, 110.0)
        self.assertNotIn("AAPL", self.p._position_last_price)

    def test_metrics_include_bayes_confidence(self):
        """calculate_metrics positions list must include bayes_confidence."""
        self.p.execute_buy("AAPL", 10, 100.0, entry_confidence=0.65)
        m = self.p.calculate_metrics({"AAPL": 100.0})
        pos_entry = m["positions"][0]
        self.assertIn("bayes_confidence", pos_entry)
        self.assertAlmostEqual(pos_entry["bayes_confidence"], 0.65, places=2)

    def test_bayes_confidence_monotone_with_sustained_gains(self):
        """Sustained price appreciation must monotonically increase confidence."""
        self.p.execute_buy("AAPL", 10, 100.0, entry_confidence=0.5)
        prev = 0.5
        price = 100.0
        for _ in range(10):
            price *= 1.01
            self.p.record_value({"AAPL": price})
            cur = self.p.positions["AAPL"].bayes_confidence
            self.assertGreaterEqual(cur, prev)
            prev = cur


class TestPeakUnrealizedTracking(unittest.TestCase):
    """Trailing stop relies on peak_unrealized_pnl tracked per position."""

    def setUp(self):
        self.p = Portfolio(starting_capital=100_000)

    def test_buy_initialises_peak_to_zero(self):
        self.p.execute_buy("AAPL", 10, 150.0)
        self.assertEqual(self.p.get_peak_unrealized("AAPL"), 0.0)
        self.assertIn("AAPL", self.p._position_peak_unrealized)

    def test_peak_grows_with_price(self):
        self.p.execute_buy("AAPL", 10, 100.0)
        # +$50 unrealized (10 × $5)
        self.p.record_value({"AAPL": 105.0})
        self.assertEqual(self.p.get_peak_unrealized("AAPL"), 50.0)
        # +$200 unrealized (10 × $20)
        self.p.record_value({"AAPL": 120.0})
        self.assertEqual(self.p.get_peak_unrealized("AAPL"), 200.0)

    def test_peak_is_monotonic_does_not_decrease(self):
        self.p.execute_buy("AAPL", 10, 100.0)
        self.p.record_value({"AAPL": 120.0})  # peak = $200
        self.p.record_value({"AAPL": 110.0})  # gave back, peak unchanged
        self.assertEqual(self.p.get_peak_unrealized("AAPL"), 200.0)

    def test_peak_stays_zero_when_position_never_profits(self):
        self.p.execute_buy("AAPL", 10, 100.0)
        self.p.record_value({"AAPL": 95.0})   # underwater
        self.p.record_value({"AAPL": 90.0})   # deeper underwater
        # Peak never went positive; remains at the initialised 0.0
        self.assertEqual(self.p.get_peak_unrealized("AAPL"), 0.0)

    def test_sell_clears_peak_tracker(self):
        self.p.execute_buy("AAPL", 10, 100.0)
        self.p.record_value({"AAPL": 120.0})
        self.assertEqual(self.p.get_peak_unrealized("AAPL"), 200.0)
        self.p.execute_sell("AAPL", 10, 115.0)
        # After full close, tracker is gone
        self.assertEqual(self.p.get_peak_unrealized("AAPL"), 0.0)
        self.assertNotIn("AAPL", self.p._position_peak_unrealized)

    def test_peak_per_symbol_independent(self):
        self.p.execute_buy("AAPL", 10, 100.0)
        self.p.execute_buy("MSFT", 5, 200.0)
        self.p.record_value({"AAPL": 110.0, "MSFT": 195.0})
        self.assertEqual(self.p.get_peak_unrealized("AAPL"), 100.0)
        self.assertEqual(self.p.get_peak_unrealized("MSFT"), 0.0)  # never positive


class TestDailyMoveTracking(unittest.TestCase):
    """Daily-move risk gate (Backlog 0.5) needs today_open per position."""

    def setUp(self):
        self.p = Portfolio(starting_capital=100_000)

    def test_buy_initialises_today_open_to_entry(self):
        self.p.execute_buy("AAPL", 10, 150.0)
        self.assertEqual(self.p.get_today_open("AAPL"), 150.0)

    def test_daily_drawdown_returns_fraction(self):
        self.p.execute_buy("AAPL", 10, 100.0)
        # Today's open = 100 (entry), current = 95 → drawdown 5%
        drop = self.p.daily_drawdown_pct("AAPL", 95.0)
        self.assertAlmostEqual(drop, 0.05, places=4)

    def test_daily_drawdown_negative_when_position_up(self):
        self.p.execute_buy("AAPL", 10, 100.0)
        # Up 10% → drawdown is -0.10 (negative = up)
        drop = self.p.daily_drawdown_pct("AAPL", 110.0)
        self.assertAlmostEqual(drop, -0.10, places=4)

    def test_daily_drawdown_none_for_unknown_symbol(self):
        self.assertIsNone(self.p.daily_drawdown_pct("MSFT", 100.0))

    def test_reset_daily_tracking_snapshots_open_for_held_positions(self):
        from datetime import date, timedelta
        self.p.execute_buy("AAPL", 10, 100.0)
        # Force a date rollover so reset_daily_tracking takes the new-day path
        self.p.daily_start_date = date.today() - timedelta(days=1)
        # Open the next day at $108 (overnight gap up)
        self.p.reset_daily_tracking({"AAPL": 108.0})
        self.assertEqual(self.p.get_today_open("AAPL"), 108.0)
        # Mid-day drop to $102 → 5.5% drawdown from today's open
        drop = self.p.daily_drawdown_pct("AAPL", 102.0)
        self.assertAlmostEqual(drop, (108.0 - 102.0) / 108.0, places=4)

    def test_sell_clears_today_open_tracker(self):
        self.p.execute_buy("AAPL", 10, 100.0)
        self.p.execute_sell("AAPL", 10, 110.0)
        self.assertIsNone(self.p.get_today_open("AAPL"))


class TestApplySplit(unittest.TestCase):
    """Backlog 0.2 — stock-split adjustments."""

    def setUp(self):
        self.p = Portfolio(starting_capital=100_000)

    def test_forward_split_scales_shares_and_avg_cost(self):
        """20-for-1 split: shares ×20, avg_cost ÷20, total cost invariant."""
        self.p.execute_buy("BKNG", 2, 4060.00)
        ok = self.p.apply_split("BKNG", 20.0)
        self.assertTrue(ok)
        pos = self.p.positions["BKNG"]
        self.assertAlmostEqual(pos.shares, 40.0)
        self.assertAlmostEqual(pos.avg_cost, 203.00)
        # Total cost basis must be unchanged
        self.assertAlmostEqual(pos.shares * pos.avg_cost, 2 * 4060.00, places=2)

    def test_reverse_split_scales_shares_down_and_cost_up(self):
        """1-for-10 reverse: shares ÷10, avg_cost ×10."""
        self.p.execute_buy("XYZ", 100, 1.50)
        self.p.apply_split("XYZ", 0.1)
        pos = self.p.positions["XYZ"]
        self.assertAlmostEqual(pos.shares, 10.0)
        self.assertAlmostEqual(pos.avg_cost, 15.0)

    def test_split_rescales_price_trackers(self):
        """All price-based per-position trackers must be rescaled by 1/ratio."""
        self.p.execute_buy("AAPL", 10, 200.0)
        self.p.record_value({"AAPL": 220.0})  # high=220, peak=$200 unrealized
        self.p.apply_split("AAPL", 4.0)  # 4-for-1
        # Price trackers all scaled by 1/4
        self.assertAlmostEqual(self.p._position_high["AAPL"],       220.0 / 4)
        self.assertAlmostEqual(self.p._position_low["AAPL"],        200.0 / 4)
        self.assertAlmostEqual(self.p._position_last_price["AAPL"], 220.0 / 4)
        self.assertAlmostEqual(self.p._position_today_open["AAPL"], 200.0 / 4)
        # Peak unrealized PnL is dollar-denominated; total value invariant
        # so peak (= max value − cost) is also invariant. Leave it.

    def test_split_records_audit_trade(self):
        self.p.execute_buy("BKNG", 2, 4060.00)
        self.p.apply_split("BKNG", 20.0)
        splits = [t for t in self.p.trade_history if t.action == "SPLIT"]
        self.assertEqual(len(splits), 1)
        self.assertEqual(splits[0].symbol, "BKNG")
        self.assertIn("ratio=20", splits[0].reasoning)
        # SPLIT must NOT inflate win-rate (filter on action=="SELL")
        sells = [t for t in self.p.trade_history if t.action == "SELL"]
        self.assertEqual(sells, [])

    def test_split_returns_false_for_unknown_symbol(self):
        self.assertFalse(self.p.apply_split("NOPE", 2.0))

    def test_split_returns_false_for_invalid_ratio(self):
        self.p.execute_buy("AAPL", 10, 100.0)
        self.assertFalse(self.p.apply_split("AAPL", 0.0))
        self.assertFalse(self.p.apply_split("AAPL", -2.0))
        # Position untouched
        self.assertEqual(self.p.positions["AAPL"].shares, 10)
        self.assertEqual(self.p.positions["AAPL"].avg_cost, 100.0)

    def test_split_1_to_1_is_noop(self):
        self.p.execute_buy("AAPL", 10, 100.0)
        result = self.p.apply_split("AAPL", 1.0)
        self.assertFalse(result)
        # No SPLIT trade record either
        self.assertEqual([t for t in self.p.trade_history if t.action == "SPLIT"], [])

    def test_split_preserves_unrealized_pnl(self):
        """Pre- and post-split unrealized P&L at the SAME (rescaled) price must match."""
        self.p.execute_buy("BKNG", 2, 4060.00)
        # Pre-split: price $4500, unrealized = (4500-4060) × 2 = $880
        pre_pnl = self.p.positions["BKNG"].unrealized_pnl(4500.0)
        self.p.apply_split("BKNG", 20.0)
        # Post-split equivalent price = 4500 / 20 = 225
        post_pnl = self.p.positions["BKNG"].unrealized_pnl(225.0)
        self.assertAlmostEqual(pre_pnl, post_pnl, places=2)


class TestUnpnlFrac(unittest.TestCase):
    """Portfolio.unpnl_frac returns total uPnL / total_value, or None if no positions."""

    def test_returns_none_when_no_positions(self):
        from trading.portfolio import Portfolio
        p = Portfolio(starting_capital=100000.0)
        self.assertIsNone(p.unpnl_frac({}))

    def test_returns_zero_at_break_even(self):
        from trading.portfolio import Portfolio
        p = Portfolio(starting_capital=100000.0)
        p.execute_buy("AAPL", 10, 100.0)        # cost = $1000
        # price unchanged → uPnL = 0 → frac = 0 / 99000 = 0
        result = p.unpnl_frac({"AAPL": 100.0})
        self.assertEqual(result, 0.0)

    def test_positive_unpnl_returns_positive_frac(self):
        from trading.portfolio import Portfolio
        p = Portfolio(starting_capital=100000.0)
        p.execute_buy("AAPL", 10, 100.0)        # cost = $1000, cash = $99000
        # price = $110 → uPnL = $100; total_value = 99000 + 1100 = $100100
        result = p.unpnl_frac({"AAPL": 110.0})
        self.assertAlmostEqual(result, 100.0 / 100100.0, places=5)

    def test_negative_unpnl_returns_negative_frac(self):
        from trading.portfolio import Portfolio
        p = Portfolio(starting_capital=100000.0)
        p.execute_buy("AAPL", 10, 100.0)
        # price = $80 → uPnL = -$200; total_value = 99000 + 800 = $99800
        result = p.unpnl_frac({"AAPL": 80.0})
        self.assertAlmostEqual(result, -200.0 / 99800.0, places=5)

    def test_skips_positions_missing_price(self):
        from trading.portfolio import Portfolio
        p = Portfolio(starting_capital=100000.0)
        p.execute_buy("AAPL", 10, 100.0)
        p.execute_buy("MSFT", 5, 200.0)
        # MSFT has no price quote → treat as 0 contribution to uPnL
        result = p.unpnl_frac({"AAPL": 110.0})  # only AAPL priced
        self.assertIsNotNone(result)
        # AAPL uPnL = +$100, MSFT contributes 0 → uPnL = $100
        # total_value = cash (98000) + AAPL_value(1100) + MSFT_at_cost(1000) = 100100
        self.assertGreater(result, 0)


if __name__ == "__main__":
    unittest.main()
