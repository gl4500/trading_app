"""
Unit tests for lifespan.py — the active trading roster.

2026-07-05: six net-negative / idle models were deprecated
(EnsembleAgent, ClaudeAgent, TechAgent, GeminiAgent, OllamaAgent, OpenClawAgent).
Their code stays on disk but they are no longer constructed or registered for
trading. `_build_trading_agents()` is the single source of truth for which agents
trade; these tests pin the surviving roster so a future edit can't silently
re-introduce a deprecated model (or drop a survivor).

2026-10-10: three more deprecated for total return (realized + unrealized on
their $100K) at or below the 10% bar — MeanReversionAgent (+7.8%),
ScannerAgent (+5.1%), SentimentAgent (-0.8%). Survivors: HistoricalTrendsAgent,
MomentumAgent, XGBReasoningAgent.
"""
import os
import sys
import unittest

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_SURVIVORS = {
    "MomentumAgent",
    "HistoricalTrendsAgent",
    "XGBReasoningAgent",
}
_DEPRECATED = {
    "EnsembleAgent",
    "ClaudeAgent",
    "TechAgent",
    "GeminiAgent",
    "OllamaAgent",
    "OpenClawAgent",
    # 2026-10-10: total return (realized + unrealized on $100K) at or below 10%.
    "MeanReversionAgent",
    "SentimentAgent",
    "ScannerAgent",
}


class TestTradingRoster(unittest.TestCase):
    def test_build_trading_agents_returns_exactly_the_survivors(self):
        from lifespan import _build_trading_agents
        names = {a.name for a in _build_trading_agents()}
        self.assertEqual(names, _SURVIVORS)

    def test_no_deprecated_model_in_roster(self):
        from lifespan import _build_trading_agents
        names = {a.name for a in _build_trading_agents()}
        for dep in _DEPRECATED:
            self.assertNotIn(dep, names, f"deprecated model {dep} is still registered for trading")


if __name__ == "__main__":
    unittest.main()
