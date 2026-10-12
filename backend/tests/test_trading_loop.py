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
    def __init__(self, name, sigs, stamp, cycle_sigs=None):
        self.name = name
        self._last_signals = sigs
        self._cycle_signals = sigs if cycle_sigs is None else cycle_sigs
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


class TestCollectUsesCycleSnapshot(unittest.TestCase):

    def test_fresh_peer_publishes_cycle_snapshot_not_retained_last_signals(self):
        from loops.trading_loop import _collect_agent_signals
        peer = _Peer("MomentumAgent", {"AAPL": _Sig("BUY")}, stamp=10.0,
                     cycle_sigs={"AAPL": _Sig("HOLD")})
        self.assertEqual(_collect_agent_signals([peer], _CTX, since=9.0),
                         {"AAPL": {"MomentumAgent": ("HOLD", 0.6)}})
        self.assertEqual(_collect_agent_signals([peer], _CTX),
                         {"AAPL": {"MomentumAgent": ("BUY", 0.6)}},
                         "history recording keeps reading _last_signals")


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



class _Holder:
    def __init__(self, name, held, picks=()):
        self.name = name
        self.portfolio = MagicMock()
        self.portfolio.positions = {s: object() for s in held}
        self._picks = list(picks)

    def get_pick_symbols(self):
        return list(self._picks)


class TestHeldPositionsArePriced(unittest.TestCase):
    """C-11: every held symbol must be fetched each cycle, not only the
    watchlist / scanner / picks, so a position that drops off the watchlist
    keeps its stops; any held symbol still unpriced is reported."""

    def test_held_symbols_not_in_context_are_fetched(self):
        from loops.trading_loop import _symbols_needing_prices
        agents = [_Holder("A", held=["LC", "AAPL"], picks=["NVDA"])]
        self.assertEqual(_symbols_needing_prices(agents, {"AAPL": {"price": 100.0}}), {"LC", "NVDA"})

    def test_held_symbols_with_unusable_context_price_are_refetched(self):
        """Context membership is not proof of a price: get_market_context emits
        price=0 when bars/quotes are missing, so held symbols with a zero,
        missing or NaN price must be retried; a valid held price is not."""
        from loops.trading_loop import _symbols_needing_prices
        agents = [_Holder("A", held=["LC", "NOPRICE", "NAN", "AAPL"])]
        ctx = {"LC": {"price": 0}, "NOPRICE": {}, "NAN": {"price": float("nan")},
               "AAPL": {"price": 100.0}}
        self.assertEqual(_symbols_needing_prices(agents, ctx), {"LC", "NOPRICE", "NAN"})

    def test_merge_keeps_valid_price_when_retry_returns_unusable(self):
        from loops.trading_loop import _merge_retry_prices
        prices = {"AAPL": 100.0, "LC": 0}
        _merge_retry_prices(prices, {"LC": {"price": 0}, "NEW": {"price": 12.5},
                                     "AAPL": {"price": 0}})
        self.assertEqual(prices, {"AAPL": 100.0, "LC": 0, "NEW": 12.5})

    def test_unpriced_held_symbols_reported_per_agent(self):
        from loops.trading_loop import _unpriced_held_symbols
        agents = [_Holder("MomentumAgent", held=["LC", "AAPL", "ZERO"])]
        self.assertEqual(
            _unpriced_held_symbols(agents, {"AAPL": 100.0, "ZERO": 0.0}),
            {"MomentumAgent": ["LC", "ZERO"]},
        )


class TestInactiveAgentStillCycles(unittest.IsolatedAsyncioTestCase):
    """C-10: run_agent_cycle must not skip a deactivated agent — run_cycle runs
    it in exit-only mode so its positions keep their stops."""

    async def test_run_cycle_called_for_inactive_agent(self):
        from unittest.mock import patch
        from loops.trading_loop import run_agent_cycle
        agent = MagicMock()
        agent.name, agent.agent_id, agent._is_active = "Halted", 1, False
        agent.portfolio.positions = {}
        agent.portfolio.trade_history = []
        agent.run_cycle = AsyncMock(return_value=[])
        with patch("main.save_trade", new_callable=AsyncMock),              patch("main.upsert_portfolio_position", new_callable=AsyncMock):
            await run_agent_cycle(agent, {}, {})
        agent.run_cycle.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()


class TestRetryNeverPublishesUnusablePrices(unittest.TestCase):
    """Review of d0d9486 (scenario matrix rows 1, 4, 6): an unusable retry value
    (NaN / inf / None / 0) is never written into the execution price map, and a
    valid existing price survives a failed retry."""

    def test_nan_retry_with_no_prior_price_is_not_published(self):
        from loops.trading_loop import _merge_retry_prices
        prices = {}
        _merge_retry_prices(prices, {"BAD": {"price": float("nan")}, "INF": {"price": float("inf")},
                                     "NONE": {"price": None}, "OK": {"price": 12.5}})
        self.assertEqual(prices, {"OK": 12.5})

    def test_existing_unusable_price_is_not_replaced_by_unusable_retry(self):
        import math
        from loops.trading_loop import _merge_retry_prices
        prices = {"BAD": float("nan")}
        _merge_retry_prices(prices, {"BAD": {"price": float("nan")}})
        self.assertFalse(math.isfinite(prices.get("BAD", float("nan"))) and prices.get("BAD", 0) > 0)

    def test_valid_price_survives_unusable_retry(self):
        from loops.trading_loop import _merge_retry_prices
        prices = {"AAPL": 100.0}
        _merge_retry_prices(prices, {"AAPL": {"price": float("nan")}})
        self.assertEqual(prices["AAPL"], 100.0)

    def test_infinite_price_counts_as_unpriced(self):
        from loops.trading_loop import _unpriced_held_symbols
        agents = [_Holder("MomentumAgent", held=["INF", "AAPL"])]
        self.assertEqual(_unpriced_held_symbols(agents, {"INF": float("inf"), "AAPL": 100.0}),
                         {"MomentumAgent": ["INF"]})
