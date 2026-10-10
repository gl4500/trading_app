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


if __name__ == "__main__":
    unittest.main()
