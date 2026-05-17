"""
Tests for backend/api/schemas.py — typed dataclasses with dict-shim for
Portfolio.calculate_metrics, position summaries, and BaseAgent.get_state.

The shim must let existing dict-style callsites work unchanged:
  - m["key"]                           → __getitem__
  - m["key"] = value                   → __setitem__  (leaderboard `entry["rank"] = rank`)
  - "key" in m                         → __contains__ (test assertIn pattern)
  - m.get("key", default)              → .get
  - {**m, "extra": ...}                → keys() + __getitem__   (Portfolio.to_dict)
  - json/FastAPI serialization         → to_dict() returns a plain dict

These tests are pure shim tests — they don't reach into Portfolio or BaseAgent.
"""
import json
import unittest
from dataclasses import is_dataclass

from api.schemas import AgentState, PortfolioMetrics, PositionSummary


# ──────────────────────────────────────────────────────────────────────────
# PortfolioMetrics
# ──────────────────────────────────────────────────────────────────────────

def _make_metrics(**overrides) -> PortfolioMetrics:
    base = dict(
        total_value=100.0,
        cash=50.0,
        position_value=50.0,
        total_return_pct=0.0,
        total_return=0.0,
        realized_pnl=0.0,
        win_rate=0.0,
        sharpe_ratio=0.0,
        max_drawdown=0.0,
        total_trades=0,
        winning_trades=0,
        losing_trades=0,
        positions=[],
        avg_mae=0.0,
        avg_mfe=0.0,
        avg_captured_pct=0.0,
    )
    base.update(overrides)
    return PortfolioMetrics(**base)


class TestPortfolioMetricsShim(unittest.TestCase):

    def test_is_dataclass(self):
        self.assertTrue(is_dataclass(PortfolioMetrics))

    def test_getitem_returns_field_value(self):
        m = _make_metrics(total_value=123.4)
        self.assertEqual(m["total_value"], 123.4)

    def test_setitem_adds_dynamic_attribute(self):
        # leaderboard mutation pattern: entry["rank"] = rank
        m = _make_metrics()
        m["rank"] = 5
        self.assertEqual(m["rank"], 5)
        self.assertEqual(m.rank, 5)  # accessible as attribute too

    def test_setitem_updates_existing_field(self):
        m = _make_metrics(total_value=100.0)
        m["total_value"] = 250.0
        self.assertEqual(m.total_value, 250.0)

    def test_contains_existing_field(self):
        m = _make_metrics()
        self.assertIn("total_value", m)
        self.assertIn("avg_mae", m)

    def test_contains_missing_key(self):
        m = _make_metrics()
        self.assertNotIn("nonexistent_key", m)

    def test_get_returns_field_value(self):
        m = _make_metrics(avg_mae=4.2)
        self.assertEqual(m.get("avg_mae"), 4.2)

    def test_get_returns_default_for_missing(self):
        m = _make_metrics()
        self.assertEqual(m.get("nonexistent", "default"), "default")
        self.assertIsNone(m.get("nonexistent"))

    def test_to_dict_returns_plain_dict_with_all_fields(self):
        m = _make_metrics(total_value=999.0, win_rate=42.0)
        d = m.to_dict()
        self.assertIsInstance(d, dict)
        self.assertEqual(d["total_value"], 999.0)
        self.assertEqual(d["win_rate"], 42.0)
        # All 16 schema fields must be present
        for key in [
            "total_value", "cash", "position_value", "total_return_pct",
            "total_return", "realized_pnl", "win_rate", "sharpe_ratio",
            "max_drawdown", "total_trades", "winning_trades", "losing_trades",
            "positions", "avg_mae", "avg_mfe", "avg_captured_pct",
        ]:
            self.assertIn(key, d)

    def test_dict_unpacking_via_keys(self):
        # Portfolio.to_dict uses {**metrics, "recent_trades": ...}
        m = _make_metrics(total_value=42.0)
        merged = {**m, "extra": "added"}
        self.assertEqual(merged["total_value"], 42.0)
        self.assertEqual(merged["extra"], "added")

    def test_json_serializable_via_to_dict(self):
        m = _make_metrics()
        s = json.dumps(m.to_dict())
        self.assertIn("total_value", s)


# ──────────────────────────────────────────────────────────────────────────
# PositionSummary
# ──────────────────────────────────────────────────────────────────────────

def _make_position(**overrides) -> PositionSummary:
    base = dict(
        symbol="AAPL",
        shares=10,
        avg_cost=100.0,
        current_price=110.0,
        current_value=1100.0,
        unrealized_pnl=100.0,
        unrealized_pnl_pct=10.0,
        entry_confidence=0.6,
        bayes_confidence=0.65,
    )
    base.update(overrides)
    return PositionSummary(**base)


class TestPositionSummaryShim(unittest.TestCase):

    def test_is_dataclass(self):
        self.assertTrue(is_dataclass(PositionSummary))

    def test_getitem(self):
        # Existing test pattern: m["positions"][0]["symbol"]
        p = _make_position(symbol="MSFT")
        self.assertEqual(p["symbol"], "MSFT")

    def test_setitem(self):
        p = _make_position()
        p["custom_tag"] = "foo"
        self.assertEqual(p["custom_tag"], "foo")

    def test_contains(self):
        p = _make_position()
        self.assertIn("bayes_confidence", p)
        self.assertNotIn("absent", p)

    def test_get(self):
        p = _make_position(entry_confidence=0.7)
        self.assertEqual(p.get("entry_confidence"), 0.7)
        self.assertEqual(p.get("missing", 0.0), 0.0)

    def test_to_dict(self):
        p = _make_position()
        d = p.to_dict()
        self.assertIsInstance(d, dict)
        for key in [
            "symbol", "shares", "avg_cost", "current_price",
            "current_value", "unrealized_pnl", "unrealized_pnl_pct",
            "entry_confidence", "bayes_confidence",
        ]:
            self.assertIn(key, d)


# ──────────────────────────────────────────────────────────────────────────
# AgentState
# ──────────────────────────────────────────────────────────────────────────

def _make_agent_state(**overrides) -> AgentState:
    base = dict(
        id=1,
        name="TestAgent",
        strategy="test strategy",
        is_active=True,
        cash=50_000.0,
        total_value=100_000.0,
        position_value=50_000.0,
        total_return_pct=0.0,
        total_return=0.0,
        realized_pnl=0.0,
        win_rate=0.0,
        sharpe_ratio=0.0,
        max_drawdown=0.0,
        total_trades=0,
        positions=[],
        recent_trades=[],
        last_signals={},
        picks={},
        value_history=[],
        avg_mae=0.0,
        avg_mfe=0.0,
        avg_captured_pct=0.0,
    )
    base.update(overrides)
    return AgentState(**base)


class TestAgentStateShim(unittest.TestCase):

    def test_is_dataclass(self):
        self.assertTrue(is_dataclass(AgentState))

    def test_getitem(self):
        s = _make_agent_state(total_return_pct=15.5)
        self.assertEqual(s["total_return_pct"], 15.5)

    def test_setitem_adds_rank_dynamically(self):
        # CRITICAL: main.py:1440 does entry["rank"] = rank on leaderboard entries
        s = _make_agent_state()
        s["rank"] = 3
        self.assertEqual(s["rank"], 3)
        self.assertEqual(s.rank, 3)

    def test_contains(self):
        s = _make_agent_state()
        self.assertIn("name", s)
        self.assertIn("avg_captured_pct", s)

    def test_get_with_default(self):
        s = _make_agent_state()
        self.assertEqual(s.get("missing", -1), -1)

    def test_to_dict_includes_all_fields(self):
        s = _make_agent_state(name="X")
        d = s.to_dict()
        self.assertIsInstance(d, dict)
        self.assertEqual(d["name"], "X")
        for key in [
            "id", "name", "strategy", "is_active", "cash", "total_value",
            "position_value", "total_return_pct", "total_return", "realized_pnl",
            "win_rate", "sharpe_ratio", "max_drawdown", "total_trades",
            "positions", "recent_trades", "last_signals", "picks", "value_history",
            "avg_mae", "avg_mfe", "avg_captured_pct",
        ]:
            self.assertIn(key, d)

    def test_to_dict_includes_dynamic_rank(self):
        # If main.py sets entry["rank"] = N before serialization, the dict
        # must carry it through to the JSON payload.
        s = _make_agent_state()
        s["rank"] = 1
        d = s.to_dict()
        self.assertEqual(d.get("rank"), 1)


if __name__ == "__main__":
    unittest.main()
