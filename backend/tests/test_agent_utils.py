"""
Unit tests for agents/agent_utils.py
Covers: format_bars_for_prompt, build_portfolio_context,
        parse_ai_decisions, fill_missing_symbols, get_fallback_signals.
Requires: pandas
"""
import sys
import os
import unittest
from datetime import datetime

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

from agents.base_agent import Signal
from agents.agent_utils import (
    format_bars_for_prompt,
    build_portfolio_context,
    parse_ai_decisions,
    fill_missing_symbols,
    get_fallback_signals,
)
from trading.portfolio import Portfolio, Position


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_bars(n=40, start_price=100.0):
    """Create a minimal OHLCV DataFrame."""
    if not HAS_PANDAS:
        return None
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    close = [start_price + i * 0.5 for i in range(n)]
    return pd.DataFrame({
        "timestamp": [d.isoformat() for d in dates],
        "open":   close,
        "high":   [c + 1 for c in close],
        "low":    [c - 1 for c in close],
        "close":  close,
        "volume": [1_000_000] * n,
    })


def _make_portfolio(cash=100_000, positions=None):
    p = Portfolio(starting_capital=100_000)
    p.cash = cash
    if positions:
        for sym, (shares, avg_cost) in positions.items():
            p.positions[sym] = Position(symbol=sym, shares=shares, avg_cost=avg_cost)
    return p


def _make_market_context(symbols, price=150.0, bars=None):
    """Build a minimal market_context dict."""
    ctx = {}
    for sym in symbols:
        ctx[sym] = {
            "price": price,
            "bars": bars,
            "stats": {},
            "news": [],
            "indicators": None,
            "composite_signal": {},
        }
    return ctx


# ── format_bars_for_prompt ────────────────────────────────────────────────────

@unittest.skipUnless(HAS_PANDAS, "pandas not available")
class TestFormatBarsForPrompt(unittest.TestCase):

    def test_none_bars_returns_no_data(self):
        result = format_bars_for_prompt(None)
        self.assertEqual(result, "No data available")

    def test_empty_dataframe_returns_no_data(self):
        result = format_bars_for_prompt(pd.DataFrame())
        self.assertEqual(result, "No data available")

    def test_valid_bars_has_header(self):
        bars = _make_bars(10)
        result = format_bars_for_prompt(bars)
        self.assertIn("Date,Open,High,Low,Close,Volume", result)

    def test_valid_bars_row_count_respects_limit(self):
        bars = _make_bars(50)
        result = format_bars_for_prompt(bars, limit=10)
        # Header + 10 data lines
        lines = [l for l in result.splitlines() if l.strip()]
        self.assertEqual(len(lines), 11)   # 1 header + 10 data

    def test_bars_contain_price_values(self):
        bars = _make_bars(5, start_price=200.0)
        result = format_bars_for_prompt(bars)
        self.assertIn("200.00", result)


# ── build_portfolio_context ───────────────────────────────────────────────────

class TestBuildPortfolioContext(unittest.TestCase):

    def test_empty_portfolio_shows_cash(self):
        p = _make_portfolio(cash=75_000)
        result = build_portfolio_context(p)
        self.assertIn("$75,000.00", result)

    def test_empty_portfolio_no_positions(self):
        p = _make_portfolio(cash=100_000)
        result = build_portfolio_context(p)
        self.assertIn("No current positions", result)

    def test_portfolio_with_positions(self):
        p = _make_portfolio(cash=50_000, positions={"AAPL": (10, 150.0)})
        result = build_portfolio_context(p)
        self.assertIn("AAPL", result)
        self.assertIn("10.00 shares", result)

    def test_shows_cost_basis(self):
        p = _make_portfolio(cash=50_000, positions={"AAPL": (10, 150.0)})
        result = build_portfolio_context(p)
        self.assertIn("Total portfolio cost basis", result)


# ── get_fallback_signals ──────────────────────────────────────────────────────

class TestGetFallbackSignals(unittest.TestCase):

    def test_returns_hold_for_all_symbols(self):
        ctx = _make_market_context(["AAPL", "MSFT", "GOOGL"])
        signals = get_fallback_signals(ctx, "TestAgent")
        self.assertEqual(len(signals), 3)
        for s in signals:
            self.assertEqual(s.action, "HOLD")

    def test_prefix_in_reasoning(self):
        ctx = _make_market_context(["AAPL"])
        signals = get_fallback_signals(ctx, "ClaudeAgent")
        self.assertIn("ClaudeAgent", signals[0].reasoning)

    def test_returns_signal_objects(self):
        ctx = _make_market_context(["AAPL"])
        signals = get_fallback_signals(ctx, "X")
        self.assertIsInstance(signals[0], Signal)


# ── parse_ai_decisions ────────────────────────────────────────────────────────

class TestParseAiDecisions(unittest.TestCase):

    def _make_response(self, decisions):
        return {"market_analysis": "Neutral market.", "decisions": decisions}

    def test_buy_creates_buy_signal(self):
        p = _make_portfolio(cash=100_000)
        ctx = _make_market_context(["AAPL"], price=100.0)
        response = self._make_response([
            {"symbol": "AAPL", "action": "BUY", "shares": 10, "confidence": 0.8, "reasoning": "Strong"}
        ])
        signals = parse_ai_decisions(response, ctx, {"AAPL": 100.0}, p, 0.15, "CLAUDE ANALYSIS")
        buy_signals = [s for s in signals if s.action == "BUY"]
        self.assertEqual(len(buy_signals), 1)
        self.assertEqual(buy_signals[0].symbol, "AAPL")

    def test_sell_without_position_becomes_hold(self):
        p = _make_portfolio(cash=100_000)   # no positions
        ctx = _make_market_context(["AAPL"], price=100.0)
        response = self._make_response([
            {"symbol": "AAPL", "action": "SELL", "shares": 10, "confidence": 0.8, "reasoning": "Bearish"}
        ])
        signals = parse_ai_decisions(response, ctx, {"AAPL": 100.0}, p, 0.15, "CLAUDE ANALYSIS")
        self.assertEqual(signals[0].action, "HOLD")

    def test_sell_with_position_creates_sell_signal(self):
        p = _make_portfolio(cash=50_000, positions={"AAPL": (20, 100.0)})
        ctx = _make_market_context(["AAPL"], price=110.0)
        response = self._make_response([
            {"symbol": "AAPL", "action": "SELL", "shares": 20, "confidence": 0.9, "reasoning": "Exit"}
        ])
        signals = parse_ai_decisions(response, ctx, {"AAPL": 110.0}, p, 0.15, "CLAUDE ANALYSIS")
        sell_signals = [s for s in signals if s.action == "SELL"]
        self.assertEqual(len(sell_signals), 1)

    def test_unknown_symbol_skipped(self):
        p = _make_portfolio(cash=100_000)
        ctx = _make_market_context(["AAPL"])
        response = self._make_response([
            {"symbol": "UNKN", "action": "BUY", "shares": 10, "confidence": 0.8, "reasoning": ""}
        ])
        signals = parse_ai_decisions(response, ctx, {"AAPL": 100.0}, p, 0.15, "TEST")
        self.assertEqual(len(signals), 0)   # UNKN not in context

    def test_zero_price_returns_hold(self):
        p = _make_portfolio(cash=100_000)
        ctx = _make_market_context(["AAPL"], price=0.0)
        response = self._make_response([
            {"symbol": "AAPL", "action": "BUY", "shares": 10, "confidence": 0.8, "reasoning": ""}
        ])
        signals = parse_ai_decisions(response, ctx, {"AAPL": 0.0}, p, 0.15, "TEST")
        self.assertEqual(signals[0].action, "HOLD")

    def test_hold_action_zero_shares(self):
        p = _make_portfolio(cash=100_000)
        ctx = _make_market_context(["AAPL"], price=100.0)
        response = self._make_response([
            {"symbol": "AAPL", "action": "HOLD", "shares": 0, "confidence": 0.5, "reasoning": "Neutral"}
        ])
        signals = parse_ai_decisions(response, ctx, {"AAPL": 100.0}, p, 0.15, "TEST")
        self.assertEqual(signals[0].action, "HOLD")
        self.assertEqual(signals[0].shares, 0)

    def test_buy_shares_capped_by_max_position(self):
        # 100k portfolio, 15% max position = $15k → 150 shares @ $100
        p = _make_portfolio(cash=100_000)
        ctx = _make_market_context(["AAPL"], price=100.0)
        response = self._make_response([
            # Request 10000 shares but max position limits to 150 (at confidence=1.0)
            {"symbol": "AAPL", "action": "BUY", "shares": 10_000, "confidence": 1.0, "reasoning": ""}
        ])
        signals = parse_ai_decisions(response, ctx, {"AAPL": 100.0}, p, 0.15, "TEST")
        buy_sig = next(s for s in signals if s.action == "BUY")
        self.assertLessEqual(buy_sig.shares, 150.01)

    def test_prefix_appears_in_reasoning(self):
        p = _make_portfolio(cash=100_000)
        ctx = _make_market_context(["AAPL"], price=100.0)
        response = self._make_response([
            {"symbol": "AAPL", "action": "HOLD", "shares": 0, "confidence": 0.5, "reasoning": "Wait"}
        ])
        signals = parse_ai_decisions(response, ctx, {"AAPL": 100.0}, p, 0.15, "MY PREFIX")
        self.assertIn("MY PREFIX", signals[0].reasoning)


# ── fill_missing_symbols ──────────────────────────────────────────────────────

class TestFillMissingSymbols(unittest.TestCase):

    def test_covered_symbols_not_duplicated(self):
        p = _make_portfolio(cash=100_000)
        ctx = _make_market_context(["AAPL", "MSFT"], price=100.0)
        existing = [
            Signal(action="BUY", symbol="AAPL", confidence=0.8, shares=10, reasoning=""),
            Signal(action="HOLD", symbol="MSFT", confidence=0.5, shares=0, reasoning=""),
        ]
        result = fill_missing_symbols(existing, ctx, {"AAPL": 100.0, "MSFT": 300.0},
                                      p, {}, 0.15, "TestAgent")
        syms = [s.symbol for s in result]
        self.assertEqual(syms.count("AAPL"), 1)
        self.assertEqual(syms.count("MSFT"), 1)

    def test_uncovered_symbol_gets_hold(self):
        p = _make_portfolio(cash=100_000)
        ctx = _make_market_context(["AAPL", "MSFT"], price=100.0)
        existing = [Signal(action="HOLD", symbol="AAPL", confidence=0.5, shares=0, reasoning="")]
        result = fill_missing_symbols(existing, ctx, {"AAPL": 100.0, "MSFT": 300.0},
                                      p, {}, 0.15, "TestAgent")
        msft_signals = [s for s in result if s.symbol == "MSFT"]
        self.assertEqual(len(msft_signals), 1)
        self.assertEqual(msft_signals[0].action, "HOLD")

    def test_buy_pick_replayed(self):
        p = _make_portfolio(cash=100_000)
        ctx = _make_market_context(["AAPL"], price=100.0)
        picks = {"AAPL": {"action": "BUY", "confidence": 0.7, "reasoning": "prior conviction"}}
        result = fill_missing_symbols([], ctx, {"AAPL": 100.0}, p, picks, 0.15, "TestAgent")
        buy_signals = [s for s in result if s.action == "BUY"]
        self.assertEqual(len(buy_signals), 1)
        self.assertIn("pick replay", buy_signals[0].reasoning)

    def test_non_dict_context_values_skipped(self):
        # __overnight_catalysts__ is a list, not dict — should be skipped
        p = _make_portfolio(cash=100_000)
        ctx = {"__overnight_catalysts__": [{"headline": "test"}]}
        existing = []
        result = fill_missing_symbols(existing, ctx, {}, p, {}, 0.15, "TestAgent")
        self.assertEqual(len(result), 0)


class TestIsMarketHours(unittest.TestCase):

    def _check(self, weekday, hour, minute, expected):
        from unittest.mock import patch
        from datetime import timezone, timedelta
        from agents.agent_utils import _is_market_hours
        et = timezone(timedelta(hours=-4))  # EDT
        dt = datetime(2026, 3, 18, hour, minute, tzinfo=et)  # Wednesday
        # Adjust weekday: 2026-03-18 is Wednesday (weekday=2). Shift by (weekday - 2) days.
        from datetime import timedelta as td
        dt = dt + td(days=weekday - 2)
        with patch("agents.agent_utils._et_now", return_value=dt):
            self.assertEqual(_is_market_hours(), expected)

    def test_open_at_930(self):
        self._check(weekday=2, hour=9, minute=30, expected=True)

    def test_open_at_1200(self):
        self._check(weekday=2, hour=12, minute=0, expected=True)

    def test_open_at_1559(self):
        self._check(weekday=2, hour=15, minute=59, expected=True)

    def test_closed_at_1600(self):
        self._check(weekday=2, hour=16, minute=0, expected=False)

    def test_closed_before_930(self):
        self._check(weekday=2, hour=9, minute=29, expected=False)

    def test_closed_on_saturday(self):
        self._check(weekday=5, hour=11, minute=0, expected=False)

    def test_closed_on_sunday(self):
        self._check(weekday=6, hour=11, minute=0, expected=False)


class TestExtractJson(unittest.TestCase):
    """extract_json parses JSON from clean text, prose-wrapped, and fails gracefully."""

    def setUp(self):
        from agents.agent_utils import extract_json
        self.extract_json = extract_json

    def test_clean_json_object(self):
        result = self.extract_json('{"action": "BUY", "confidence": 0.8}')
        self.assertEqual(result["action"], "BUY")
        self.assertAlmostEqual(result["confidence"], 0.8)

    def test_json_wrapped_in_prose(self):
        text = 'Based on analysis: {"action": "SELL", "symbol": "AAPL"} — recommended.'
        result = self.extract_json(text)
        self.assertEqual(result["action"], "SELL")

    def test_invalid_json_returns_none(self):
        self.assertIsNone(self.extract_json("not json at all"))

    def test_empty_string_returns_none(self):
        self.assertIsNone(self.extract_json(""))

    def test_nested_json_parsed(self):
        text = '{"decisions": [{"symbol": "NVDA", "action": "BUY"}]}'
        result = self.extract_json(text)
        self.assertEqual(result["decisions"][0]["symbol"], "NVDA")

    def test_broken_prose_no_json_returns_none(self):
        self.assertIsNone(self.extract_json("The market looks {bullish} today"))


if __name__ == "__main__":
    unittest.main()
