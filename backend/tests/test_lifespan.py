"""
Unit tests for lifespan.py — the active trading roster.

2026-07-05: six net-negative / idle models were deprecated
(EnsembleAgent, ClaudeAgent, TechAgent, GeminiAgent, OllamaAgent, OpenClawAgent).
Their code stays on disk but they are no longer constructed or registered for
trading. `_build_trading_agents()` is the single source of truth for which agents
trade; these tests pin the surviving roster so a future edit can't silently
re-introduce a deprecated model (or drop a survivor).

2026-10-10 (requirement ROSTER-R3, operator decision on the replicated R3
reconstruction): the roster is the agents whose split-corrected total return on
their $100K, valued at 2026-08-12 closes, clears 10% with full price coverage —
HistoricalTrendsAgent (+17.9%), MeanReversionAgent (+22.9%), XGBReasoningAgent
(+11.2%). Deprecated: MomentumAgent (+10.2% but one unpriced holding makes it
inconclusive; +7.3% with that holding at zero), ScannerAgent (+5.2%),
SentimentAgent (+0.0%).
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
    "MeanReversionAgent",
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
    # 2026-10-10 (ROSTER-R3): not confirmed above 10% total return on $100K.
    "MomentumAgent",
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
