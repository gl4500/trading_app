"""
Unit tests for loops/trading_loop.py helpers.

X-2 (2026-10-10): per-symbol agent signals were attached to the *current*
cycle's market_context after every agent had already run, and the next cycle
built a fresh market_context, so XGBReasoningAgent never saw any peer signal
(183 of 207 live XGB BUYs were lone-wolf half-sized). The loop now hands the
collected signals to agents that declare `set_peer_signals`, for use next cycle.
They are deliberately NOT put into market_context: a dict-valued key there is
treated as a symbol by every agent's `isinstance(ctx, dict)` iteration.
"""
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class _Receiver:
    def __init__(self, name):
        self.name = name
        self.received = None

    def set_peer_signals(self, sigs):
        self.received = sigs


class _NonReceiver:
    name = "MomentumAgent"


class _Exploding:
    name = "Broken"

    def set_peer_signals(self, sigs):
        raise RuntimeError("boom")


class TestPublishPeerSignals(unittest.TestCase):
    SIGS = {"AAPL": {"MomentumAgent": ("BUY", 0.6)}}

    def test_hands_signals_to_agents_that_accept_them(self):
        from loops.trading_loop import _publish_peer_signals
        xgb = _Receiver("XGBReasoningAgent")
        _publish_peer_signals([_NonReceiver(), xgb], self.SIGS)
        self.assertEqual(xgb.received, self.SIGS)

    def test_one_failing_receiver_does_not_block_the_others(self):
        from loops.trading_loop import _publish_peer_signals
        xgb = _Receiver("XGBReasoningAgent")
        _publish_peer_signals([_Exploding(), xgb], self.SIGS)
        self.assertEqual(xgb.received, self.SIGS)



class _Sig:
    def __init__(self, action, confidence=0.6):
        self.action, self.confidence = action, confidence


class _Peer:
    """Stand-in agent with a last-signals map and freshness stamp."""
    def __init__(self, name, sigs, stamp):
        self.name = name
        self._last_signals = sigs
        self._last_signals_at = stamp


_CTX = {"AAPL": {"price": 100.0}, "__overnight_catalysts__": []}


class TestCollectAgentSignals(unittest.TestCase):

    def test_since_excludes_peers_that_did_not_produce_signals_this_cycle(self):
        """Inactive / daily-halted / erroring peers keep an old _last_signals map;
        it must not be republished as a current vote."""
        from loops.trading_loop import _collect_agent_signals
        fresh = _Peer("MomentumAgent", {"AAPL": _Sig("BUY")}, stamp=10.0)
        stale = _Peer("HistoricalTrendsAgent", {"AAPL": _Sig("BUY")}, stamp=5.0)
        out = _collect_agent_signals([fresh, stale], _CTX, since=9.0)
        self.assertEqual(out, {"AAPL": {"MomentumAgent": ("BUY", 0.6)}})

    def test_without_since_keeps_existing_all_signals_behaviour(self):
        from loops.trading_loop import _collect_agent_signals
        stale = _Peer("HistoricalTrendsAgent", {"AAPL": _Sig("BUY")}, stamp=5.0)
        out = _collect_agent_signals([stale], _CTX)
        self.assertEqual(out, {"AAPL": {"HistoricalTrendsAgent": ("BUY", 0.6)}})

    def test_skips_symbols_not_in_market_context_and_meta_agents(self):
        from loops.trading_loop import _collect_agent_signals
        ens = _Peer("EnsembleAgent", {"AAPL": _Sig("BUY")}, stamp=10.0)
        gone = _Peer("MomentumAgent", {"MSFT": _Sig("BUY")}, stamp=10.0)
        self.assertEqual(_collect_agent_signals([ens, gone], _CTX, since=9.0), {})


class TestRecordAndPublishAgentSignals(unittest.IsolatedAsyncioTestCase):

    async def test_publishes_even_when_score_refresh_fails(self):
        from loops.trading_loop import _record_and_publish_agent_signals
        peer = _Peer("MomentumAgent", {"AAPL": _Sig("HOLD")}, stamp=10.0)
        xgb = _Receiver("XGBReasoningAgent")
        tracker = MagicMock()
        tracker.get_scores = AsyncMock(side_effect=RuntimeError("db locked"))
        await _record_and_publish_agent_signals(
            [peer, xgb], _CTX, {"AAPL": 100.0}, cycle_start=9.0,
            tracker=tracker, history=MagicMock())
        self.assertEqual(xgb.received, {"AAPL": {"MomentumAgent": ("HOLD", 0.6)}})

    async def test_empty_cycle_publishes_empty_map_to_clear_cache(self):
        from loops.trading_loop import _record_and_publish_agent_signals
        stale = _Peer("MomentumAgent", {"AAPL": _Sig("BUY")}, stamp=1.0)
        xgb = _Receiver("XGBReasoningAgent")
        xgb.received = {"AAPL": {"MomentumAgent": ("BUY", 0.6)}}
        await _record_and_publish_agent_signals(
            [stale, xgb], _CTX, {"AAPL": 100.0}, cycle_start=9.0,
            tracker=MagicMock(get_scores=AsyncMock()), history=MagicMock())
        self.assertEqual(xgb.received, {})


if __name__ == "__main__":
    unittest.main()
