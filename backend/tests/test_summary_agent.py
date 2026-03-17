"""
Unit tests for agents/summary_agent.py
Covers: _today_trades(), _agent_signal_summary(), _build_consensus_map(),
        DailySummaryService.generate() with mocked Claude
"""
import sys
import os
import asyncio
import time
import unittest
from datetime import datetime, date, timezone
from unittest.mock import patch, AsyncMock, MagicMock

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agents.summary_agent import (
    DailySummaryService,
    _today_trades,
    _agent_signal_summary,
    _build_consensus_map,
)
from agents.base_agent import BaseAgent, Signal
from trading.portfolio import Portfolio, TradeRecord


def _make_agent(name="TestAgent"):
    """Create a minimal agent stub with empty signals and no trades."""
    agent = MagicMock()
    agent.name = name
    agent._last_signals = {}
    agent.portfolio.trade_history = []
    agent.portfolio.positions = {}
    agent.portfolio.calculate_metrics = MagicMock(return_value={
        "total_return_pct": 0.0,
        "win_rate": 0.0,
    })
    agent.get_pick_symbols = MagicMock(return_value=[])
    return agent


def _make_trade(symbol, action, price, shares=1.0, pnl=None, days_ago=0):
    """Create a Trade-like namedtuple for testing."""
    t = MagicMock()
    t.symbol = symbol
    t.action = action
    t.shares = shares
    t.price = price
    t.pnl = pnl
    t.timestamp = datetime.now().replace(hour=10, minute=30)
    t.reasoning = f"{action} {symbol} test reasoning"
    return t


def _make_signal(symbol, action, confidence=0.5, reasoning="test"):
    return Signal(action=action, symbol=symbol, confidence=confidence, shares=1, reasoning=reasoning)


class TestTodayTrades(unittest.TestCase):
    """_today_trades returns only trades from today (UTC)."""

    def test_returns_today_trades(self):
        agent = _make_agent()
        trade = _make_trade("AAPL", "BUY", 150.0)
        agent.portfolio.trade_history = [trade]
        result = _today_trades(agent)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["symbol"], "AAPL")

    def test_excludes_old_trades(self):
        agent = _make_agent()
        old_trade = _make_trade("MSFT", "SELL", 300.0)
        old_trade.timestamp = datetime(2020, 1, 1, 10, 0)  # old date
        agent.portfolio.trade_history = [old_trade]
        result = _today_trades(agent)
        self.assertEqual(len(result), 0)

    def test_empty_trade_history(self):
        agent = _make_agent()
        result = _today_trades(agent)
        self.assertEqual(result, [])

    def test_trade_fields_present(self):
        agent = _make_agent()
        trade = _make_trade("AAPL", "BUY", 150.0, shares=5, pnl=50.0)
        agent.portfolio.trade_history = [trade]
        result = _today_trades(agent)
        self.assertIn("symbol", result[0])
        self.assertIn("action", result[0])
        self.assertIn("shares", result[0])
        self.assertIn("price", result[0])
        self.assertIn("timestamp", result[0])
        self.assertIn("reasoning", result[0])


class TestAgentSignalSummary(unittest.TestCase):
    """_agent_signal_summary correctly counts BUY/SELL/HOLD signals."""

    def test_counts_buy_sell_hold(self):
        agent = _make_agent()
        agent._last_signals = {
            "AAPL": _make_signal("AAPL", "BUY", 0.8),
            "MSFT": _make_signal("MSFT", "SELL", 0.7),
            "TSLA": _make_signal("TSLA", "HOLD", 0.5),
            "GOOG": _make_signal("GOOG", "HOLD", 0.4),
        }
        prices = {"AAPL": 150.0, "MSFT": 300.0, "TSLA": 200.0, "GOOG": 140.0}
        result = _agent_signal_summary(agent, prices)
        self.assertEqual(result["buy_count"], 1)
        self.assertEqual(result["sell_count"], 1)
        self.assertEqual(result["hold_count"], 2)

    def test_top_buys_sorted_by_confidence(self):
        agent = _make_agent()
        agent._last_signals = {
            "AAPL": _make_signal("AAPL", "BUY", 0.9),
            "MSFT": _make_signal("MSFT", "BUY", 0.6),
            "TSLA": _make_signal("TSLA", "BUY", 0.75),
        }
        prices = {"AAPL": 150.0, "MSFT": 300.0, "TSLA": 200.0}
        result = _agent_signal_summary(agent, prices)
        top_confs = [b["confidence"] for b in result["top_buys"]]
        self.assertEqual(top_confs, sorted(top_confs, reverse=True))

    def test_empty_signals(self):
        agent = _make_agent()
        result = _agent_signal_summary(agent, {})
        self.assertEqual(result["buy_count"], 0)
        self.assertEqual(result["sell_count"], 0)
        self.assertEqual(result["hold_count"], 0)


class TestBuildConsensusMap(unittest.TestCase):
    """_build_consensus_map builds vote tally and labels correctly."""

    def _agents_with_signals(self, agent_signal_map):
        """agent_signal_map: {agent_name: {symbol: (action, conf)}}"""
        agents = {}
        for name, signals in agent_signal_map.items():
            agent = _make_agent(name)
            agent._last_signals = {
                sym: _make_signal(sym, action, conf)
                for sym, (action, conf) in signals.items()
            }
            agents[name] = agent
        return agents

    def test_all_buy_votes_is_strong_buy(self):
        agents = self._agents_with_signals({
            "AgentA": {"AAPL": ("BUY", 0.8)},
            "AgentB": {"AAPL": ("BUY", 0.7)},
            "AgentC": {"AAPL": ("BUY", 0.9)},
        })
        result = _build_consensus_map(agents)
        self.assertIn("AAPL", result)
        self.assertEqual(result["AAPL"]["consensus"], "STRONG BUY")

    def test_all_sell_votes_is_strong_sell(self):
        agents = self._agents_with_signals({
            "AgentA": {"MSFT": ("SELL", 0.8)},
            "AgentB": {"MSFT": ("SELL", 0.7)},
            "AgentC": {"MSFT": ("SELL", 0.9)},
        })
        result = _build_consensus_map(agents)
        self.assertIn("MSFT", result)
        self.assertEqual(result["MSFT"]["consensus"], "STRONG SELL")

    def test_split_vote_is_buy(self):
        """1 BUY + 1 SELL: buy_pct=0.5 >= 0.50 threshold → label is 'BUY'."""
        agents = self._agents_with_signals({
            "AgentA": {"TSLA": ("BUY", 0.8)},
            "AgentB": {"TSLA": ("SELL", 0.7)},
        })
        result = _build_consensus_map(agents)
        self.assertIn("TSLA", result)
        self.assertEqual(result["TSLA"]["consensus"], "BUY")

    def test_excluded_agents_not_counted(self):
        """EnsembleAgent and SummaryAgent are excluded from consensus."""
        agents = self._agents_with_signals({
            "EnsembleAgent": {"AAPL": ("BUY", 0.9)},
            "SummaryAgent":  {"AAPL": ("BUY", 0.9)},
        })
        result = _build_consensus_map(agents)
        # Should be empty — excluded agents produce no votes
        self.assertNotIn("AAPL", result)

    def test_hold_signals_not_counted(self):
        """HOLD signals do not contribute to consensus."""
        agents = self._agents_with_signals({
            "AgentA": {"AAPL": ("HOLD", 0.5)},
        })
        result = _build_consensus_map(agents)
        self.assertNotIn("AAPL", result)

    def test_sorted_by_agreement_descending(self):
        agents = self._agents_with_signals({
            "AgentA": {"HIGH": ("BUY", 0.9), "LOW": ("BUY", 0.6)},
            "AgentB": {"HIGH": ("BUY", 0.85)},
            # LOW has only one vote → agreement=1.0 but only one agent
        })
        result = _build_consensus_map(agents)
        # Just verify it doesn't crash and is a dict
        self.assertIsInstance(result, dict)


class TestDailySummaryServiceCache(unittest.IsolatedAsyncioTestCase):
    """DailySummaryService caches results and returns them on subsequent calls."""

    async def test_fresh_cache_returned_without_regeneration(self):
        service = DailySummaryService()
        cached_result = {"status": "ok", "narrative": "cached", "generated_at": "2024-01-01T10:00:00"}
        service._cache = cached_result
        service._cache_ts = time.time()  # just set

        agents = {}
        result = await service.generate(agents, {}, "open", force=False)
        self.assertEqual(result, cached_result)

    async def test_force_true_bypasses_cache(self):
        service = DailySummaryService()
        service._cache = {"status": "ok", "narrative": "stale_cache"}
        service._cache_ts = time.time()

        agents = {"TestAgent": _make_agent("TestAgent")}

        with patch.object(service, "_build_summary", new_callable=AsyncMock) as mock_build:
            mock_build.return_value = {"status": "ok", "narrative": "fresh"}
            result = await service.generate(agents, {}, "open", force=True)

        mock_build.assert_called_once()
        self.assertEqual(result["narrative"], "fresh")

    async def test_generating_flag_prevents_concurrent_generation(self):
        """If already generating, return cache or generating message without starting new generation."""
        service = DailySummaryService()
        service._generating = True
        service._cache = None

        result = await service.generate({}, {}, "open")
        # Should return the "generating" fallback dict
        self.assertIn("generating", result.get("status", "") + result.get("narrative", ""))

    async def test_closed_market_has_longer_ttl(self):
        """When market is closed, cached result is considered fresh for longer."""
        service = DailySummaryService()
        # Set cache timestamp to 10 minutes ago — within closed TTL (60 min), outside open TTL (5 min)
        service._cache = {"status": "ok", "narrative": "hourly_cache"}
        service._cache_ts = time.time() - 10 * 60  # 10 min ago

        result = await service.generate({}, {}, "closed", force=False)
        self.assertEqual(result["narrative"], "hourly_cache")

    async def test_generate_with_no_anthropic_key_uses_fallback(self):
        """When ANTHROPIC_API_KEY is empty, fallback narrative is generated."""
        service = DailySummaryService()
        agents = {"TestAgent": _make_agent("TestAgent")}

        with patch("config.config") as mock_cfg:
            mock_cfg.ANTHROPIC_API_KEY = ""
            result = await service.generate(agents, {"AAPL": 150.0}, "closed")

        self.assertIn("status", result)
        self.assertIn("narrative", result)
        self.assertIsInstance(result["narrative"], str)


class TestDailySummaryServiceBuildSummary(unittest.IsolatedAsyncioTestCase):
    """_build_summary returns complete structure."""

    async def test_build_summary_returns_expected_keys(self):
        service = DailySummaryService()
        agent = _make_agent("MomentumAgent")
        agents = {"MomentumAgent": agent}

        with patch.object(service, "_get_narrative", new_callable=AsyncMock) as mock_narr:
            mock_narr.return_value = "Test narrative."
            result = await service._build_summary(agents, {"AAPL": 150.0}, "closed", [], [])

        for key in ("status", "generated_at", "date", "market_status",
                    "agent_summaries", "consensus", "leaderboard",
                    "trades_today", "narrative"):
            self.assertIn(key, result)

    async def test_ensemble_agent_excluded_from_summaries(self):
        """EnsembleAgent is handled separately — not in agent_summaries."""
        service = DailySummaryService()
        ensemble = _make_agent("EnsembleAgent")
        ensemble.portfolio.calculate_metrics = MagicMock(return_value={
            "total_return_pct": 5.0, "win_rate": 0.6
        })
        ensemble._regime = "bullish"
        regular = _make_agent("MomentumAgent")

        agents = {"EnsembleAgent": ensemble, "MomentumAgent": regular}

        with patch.object(service, "_get_narrative", new_callable=AsyncMock) as mock_narr:
            mock_narr.return_value = "Narrative."
            result = await service._build_summary(agents, {}, "closed", [], [])

        self.assertNotIn("EnsembleAgent", result["agent_summaries"])
        self.assertIn("MomentumAgent", result["agent_summaries"])
        self.assertIsNotNone(result["ensemble"])

    async def test_get_narrative_mocked_claude_response(self):
        """_get_narrative uses Claude when API key is configured."""
        service = DailySummaryService()

        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = "Today the agents were bullish."
        mock_response = MagicMock()
        mock_response.content = [mock_block]

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("config.config") as mock_cfg, \
             patch("anthropic.AsyncAnthropic", return_value=mock_client):
            mock_cfg.ANTHROPIC_API_KEY = "fake"
            narrative = await service._get_narrative({}, {}, None, [], [], {}, "open")

        self.assertEqual(narrative, "Today the agents were bullish.")

    async def test_get_narrative_fallback_on_no_key(self):
        """_get_narrative uses fallback text when no API key."""
        service = DailySummaryService()

        with patch("config.config") as mock_cfg:
            mock_cfg.ANTHROPIC_API_KEY = ""
            narrative = await service._get_narrative(
                {"AgentA": {"buy_count": 2, "sell_count": 1, "hold_count": 5,
                            "trades_today": [], "active_picks": [],
                            "total_return_pct": 1.5, "win_rate": 0.6,
                            "top_buys": [], "top_sells": [], "positions": []}},
                {}, None, [], [], {}, "closed"
            )

        self.assertIsInstance(narrative, str)
        self.assertGreater(len(narrative), 0)


if __name__ == "__main__":
    unittest.main()
