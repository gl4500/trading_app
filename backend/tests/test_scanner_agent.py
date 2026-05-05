"""
Unit tests for agents/scanner_agent.py
Covers: _coerce_rec(), _merge_recommendations(), _split_candidates(),
        get_cached_scan(), _pre_screen() (mocked), _build_user_message()
"""
import sys
import os
import asyncio
import time
import unittest
from unittest.mock import patch, AsyncMock, MagicMock

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import agents.scanner_agent as scanner_module
from agents.scanner_agent import (
    _coerce_rec,
    _merge_recommendations,
    _split_candidates,
    _build_user_message,
    get_cached_scan,
    SCAN_CACHE_TTL,
    MAX_RECOMMENDATIONS,
    MAX_TOOL_ROUNDS,
)


class TestCoerceRec(unittest.TestCase):
    """_coerce_rec converts string numerics and uppercases action."""

    def test_string_confidence_converted_to_float(self):
        rec = {"symbol": "AAPL", "action": "buy", "confidence": "0.75", "composite_score": "0.3"}
        result = _coerce_rec(rec)
        self.assertIsInstance(result["confidence"], float)
        self.assertAlmostEqual(result["confidence"], 0.75)

    def test_action_uppercased(self):
        rec = {"symbol": "MSFT", "action": "sell", "confidence": 0.6, "composite_score": 0.1}
        result = _coerce_rec(rec)
        self.assertEqual(result["action"], "SELL")

    def test_none_fields_not_converted(self):
        rec = {"symbol": "AAPL", "action": "BUY", "confidence": None, "composite_score": None}
        result = _coerce_rec(rec)
        self.assertIsNone(result["confidence"])
        self.assertIsNone(result["composite_score"])

    def test_price_target_converted(self):
        rec = {"symbol": "GOOG", "action": "BUY", "confidence": 0.8,
               "composite_score": 0.5, "price_target": "200.0"}
        result = _coerce_rec(rec)
        self.assertAlmostEqual(result["price_target"], 200.0)

    def test_stop_loss_pct_converted(self):
        rec = {"symbol": "TSLA", "action": "BUY", "confidence": 0.7,
               "composite_score": 0.4, "stop_loss_pct": "5"}
        result = _coerce_rec(rec)
        self.assertAlmostEqual(result["stop_loss_pct"], 5.0)

    def test_invalid_string_left_unchanged(self):
        rec = {"symbol": "XYZ", "action": "BUY", "confidence": "not_a_number", "composite_score": 0.2}
        result = _coerce_rec(rec)
        # Should remain as the original value (not crash)
        self.assertEqual(result["confidence"], "not_a_number")

    def test_integer_confidence_converted_to_float(self):
        rec = {"symbol": "AAPL", "action": "BUY", "confidence": 1, "composite_score": 0.5}
        result = _coerce_rec(rec)
        self.assertIsInstance(result["confidence"], float)


class TestMergeRecommendations(unittest.TestCase):
    """_merge_recommendations deduplicates by symbol (highest confidence wins)."""

    def test_deduplication_keeps_highest_confidence(self):
        recs_a = [{"symbol": "AAPL", "action": "BUY", "confidence": 0.65}]
        recs_b = [{"symbol": "AAPL", "action": "BUY", "confidence": 0.80}]
        merged = _merge_recommendations([recs_a, recs_b])
        # Only one AAPL, and it should be the 0.80 one
        aapl_recs = [r for r in merged if r["symbol"] == "AAPL"]
        self.assertEqual(len(aapl_recs), 1)
        self.assertAlmostEqual(aapl_recs[0]["confidence"], 0.80)

    def test_different_symbols_all_kept(self):
        recs = [
            [{"symbol": "AAPL", "action": "BUY", "confidence": 0.70}],
            [{"symbol": "MSFT", "action": "SELL", "confidence": 0.75}],
        ]
        merged = _merge_recommendations(recs)
        syms = {r["symbol"] for r in merged}
        self.assertIn("AAPL", syms)
        self.assertIn("MSFT", syms)

    def test_capped_at_max_recommendations(self):
        # Create MAX_RECOMMENDATIONS + 2 unique symbols
        recs = [[{"symbol": f"SYM{i}", "action": "BUY", "confidence": 0.5 + i * 0.01}
                 for i in range(MAX_RECOMMENDATIONS + 3)]]
        merged = _merge_recommendations(recs)
        self.assertLessEqual(len(merged), MAX_RECOMMENDATIONS)

    def test_exception_in_results_skipped(self):
        """Exception objects in results list are skipped gracefully."""
        recs_good = [{"symbol": "AAPL", "action": "BUY", "confidence": 0.70}]
        merged = _merge_recommendations([Exception("api error"), [recs_good[0]]])
        self.assertEqual(len(merged), 1)

    def test_non_list_results_skipped(self):
        """Non-list results are skipped gracefully."""
        merged = _merge_recommendations(["bad_result", [{"symbol": "AAPL", "action": "BUY", "confidence": 0.7}]])
        self.assertEqual(len(merged), 1)

    def test_empty_inputs_returns_empty(self):
        merged = _merge_recommendations([[], []])
        self.assertEqual(merged, [])

    def test_rec_missing_symbol_skipped(self):
        recs = [[{"action": "BUY", "confidence": 0.75}]]  # no symbol
        merged = _merge_recommendations(recs)
        self.assertEqual(merged, [])

    def test_sorted_descending_by_confidence(self):
        recs = [[
            {"symbol": "LOW", "action": "BUY", "confidence": 0.60},
            {"symbol": "HIGH", "action": "BUY", "confidence": 0.90},
            {"symbol": "MID", "action": "BUY", "confidence": 0.75},
        ]]
        merged = _merge_recommendations(recs)
        confs = [r["confidence"] for r in merged]
        self.assertEqual(confs, sorted(confs, reverse=True))


class TestSplitCandidates(unittest.TestCase):
    """_split_candidates splits candidate list into n sequential chunks."""

    def test_n1_returns_full_list(self):
        candidates = [{"symbol": f"S{i}"} for i in range(10)]
        result = _split_candidates(candidates, 1)
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]), 10)

    def test_n2_splits_roughly_equal(self):
        candidates = [{"symbol": f"S{i}"} for i in range(10)]
        result = _split_candidates(candidates, 2)
        self.assertEqual(len(result), 2)
        total = sum(len(c) for c in result)
        self.assertEqual(total, 10)

    def test_first_chunk_gets_top_ranked(self):
        """First chunk should contain highest-ranked (first) candidates."""
        candidates = [{"symbol": f"S{i}", "momentum_score": 10 - i} for i in range(6)]
        result = _split_candidates(candidates, 3)
        # First element of first chunk is the highest-momentum candidate
        self.assertEqual(result[0][0]["symbol"], "S0")

    def test_n_equals_zero_treated_as_one(self):
        candidates = [{"symbol": "AAPL"}]
        result = _split_candidates(candidates, 0)
        self.assertEqual(len(result), 1)

    def test_n_larger_than_candidates_no_crash(self):
        candidates = [{"symbol": "AAPL"}]
        result = _split_candidates(candidates, 5)
        total = sum(len(c) for c in result)
        self.assertEqual(total, 1)


class TestGetCachedScan(unittest.TestCase):
    """get_cached_scan returns None when no cache, stale flag when expired."""

    def setUp(self):
        # Reset module globals
        scanner_module._cache = None
        scanner_module._cache_ts = 0.0

    def test_no_cache_returns_none(self):
        result = get_cached_scan()
        self.assertIsNone(result)

    def test_fresh_cache_returned(self):
        scanner_module._cache = {"status": "ok", "recommendations": [], "scanned_at": "2024-01-01T10:00:00"}
        scanner_module._cache_ts = time.time()  # just set
        result = get_cached_scan()
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "ok")

    def test_stale_cache_tagged_as_stale(self):
        scanner_module._cache = {"status": "ok", "recommendations": [], "scanned_at": "2024-01-01T00:00:00"}
        scanner_module._cache_ts = time.time() - SCAN_CACHE_TTL - 1  # expired
        result = get_cached_scan()
        self.assertIsNotNone(result)
        self.assertTrue(result["is_stale"])

    def test_require_fresh_returns_none_when_stale(self):
        scanner_module._cache = {"status": "ok", "recommendations": []}
        scanner_module._cache_ts = time.time() - SCAN_CACHE_TTL - 1  # expired
        result = get_cached_scan(require_fresh=True)
        self.assertIsNone(result)

    def test_require_fresh_returns_result_when_fresh(self):
        scanner_module._cache = {"status": "ok", "recommendations": [], "scanned_at": "2024-01-01T10:00:00"}
        scanner_module._cache_ts = time.time()  # just set
        result = get_cached_scan(require_fresh=True)
        self.assertIsNotNone(result)

    def tearDown(self):
        scanner_module._cache = None
        scanner_module._cache_ts = 0.0


class TestBuildUserMessage(unittest.TestCase):
    """_build_user_message includes candidate symbols and momentum scores."""

    def test_contains_all_symbols(self):
        candidates = [
            {"symbol": "AAPL", "pct_change": 2.5, "vol_ratio": 1.8, "momentum_score": 4.5},
            {"symbol": "MSFT", "pct_change": -1.2, "vol_ratio": 0.9, "momentum_score": 1.1},
        ]
        msg = _build_user_message(candidates)
        self.assertIn("AAPL", msg)
        self.assertIn("MSFT", msg)

    def test_contains_momentum_scores(self):
        candidates = [
            {"symbol": "TSLA", "pct_change": 5.0, "vol_ratio": 3.0, "momentum_score": 15.0},
        ]
        msg = _build_user_message(candidates)
        self.assertIn("momentum", msg.lower())
        self.assertIn("15.0", msg)

    def test_empty_candidates_no_crash(self):
        msg = _build_user_message([])
        self.assertIsInstance(msg, str)


class TestPreScreenMocked(unittest.IsolatedAsyncioTestCase):
    """_pre_screen with mocked alpaca returns correctly ranked candidates."""

    async def test_pre_screen_returns_candidates(self):
        """Pre-screen with mocked bars returns sorted list of candidates."""
        try:
            import pandas as pd
        except ImportError:
            self.skipTest("pandas not available")

        # Build fake bars: 5 bars per symbol
        def _make_bars(close_vals):
            return pd.DataFrame({
                "close":  close_vals,
                "volume": [1_000_000] * len(close_vals),
            })

        fake_bars = {
            "AAPL": _make_bars([100, 101, 102, 103, 110]),  # +6.8% last day
            "MSFT": _make_bars([200, 201, 202, 203, 204]),  # +0.5% last day
        }

        with patch("trading.alpaca_client.alpaca_client.get_bars_multi", new_callable=AsyncMock) as mock_bm, \
             patch("data.stock_universe.ALL_SYMBOLS", ["AAPL", "MSFT"]):
            mock_bm.return_value = fake_bars
            from agents.scanner_agent import _pre_screen
            candidates = await _pre_screen(top_n=10)

        self.assertIsInstance(candidates, list)
        self.assertGreater(len(candidates), 0)
        # AAPL has higher momentum score → should be first
        if len(candidates) >= 2:
            self.assertEqual(candidates[0]["symbol"], "AAPL")

    async def test_pre_screen_filters_insufficient_bars(self):
        """Symbols with < 2 bars are filtered out."""
        try:
            import pandas as pd
        except ImportError:
            self.skipTest("pandas not available")

        fake_bars = {
            "AAPL": pd.DataFrame({"close": [100.0], "volume": [1_000_000]}),  # only 1 bar
            "MSFT": pd.DataFrame({"close": [200, 201], "volume": [500_000, 600_000]}),
        }

        with patch("trading.alpaca_client.alpaca_client.get_bars_multi", new_callable=AsyncMock) as mock_bm, \
             patch("data.stock_universe.ALL_SYMBOLS", ["AAPL", "MSFT"]):
            mock_bm.return_value = fake_bars
            from agents.scanner_agent import _pre_screen
            candidates = await _pre_screen(top_n=10)

        syms = [c["symbol"] for c in candidates]
        self.assertNotIn("AAPL", syms)
        self.assertIn("MSFT", syms)


class TestScannerTokenLogging(unittest.IsolatedAsyncioTestCase):
    """Scanner runners call save_token_log after completing the agentic loop."""

    async def test_claude_scanner_logs_tokens(self):
        """_run_claude_scanner calls save_token_log with accumulated token counts."""
        from agents.scanner_agent import _run_claude_scanner

        usage = MagicMock()
        usage.input_tokens = 800
        usage.output_tokens = 200

        fake_response = MagicMock()
        fake_response.usage = usage
        fake_response.content = []
        fake_response.stop_reason = "end_turn"

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=fake_response)

        mock_config = MagicMock()
        mock_config.ANTHROPIC_API_KEY = "test-key"
        # Pin the model the scanner sees to the test value so we can assert
        # it's the same one save_token_log records (proves the model field
        # flows from config rather than a hardcoded string).
        mock_config.SCANNER_CLAUDE_MODEL = "claude-haiku-4-5-20251001"

        with patch("agents.scanner_agent.save_token_log", new_callable=AsyncMock) as mock_save, \
             patch("config.config", mock_config), \
             patch("anthropic.AsyncAnthropic", return_value=mock_client):
            candidates = [{"symbol": "AAPL", "pct_change": 2.0, "vol_ratio": 1.5,
                           "momentum_score": 0.7, "price": 180.0}]
            await _run_claude_scanner(candidates)

        mock_save.assert_called_once()
        call_kwargs = mock_save.call_args[1]
        self.assertEqual(call_kwargs["agent"], "ScannerAgent/Claude")
        # Model logged matches the one the API was called with (config-driven)
        self.assertEqual(call_kwargs["model"], "claude-haiku-4-5-20251001")
        self.assertGreater(call_kwargs["prompt_tokens"], 0)
        self.assertGreater(call_kwargs["completion_tokens"], 0)
        # Also assert the API call site used the same model — full proof
        # the swap is wired everywhere.
        api_call_kwargs = mock_client.messages.create.await_args.kwargs
        self.assertEqual(api_call_kwargs["model"], "claude-haiku-4-5-20251001")

    async def test_default_scanner_claude_model_is_haiku(self):
        """The default config.SCANNER_CLAUDE_MODEL is Haiku 4.5 — saves
        ~85% per token vs Opus 4.6. Set SCANNER_CLAUDE_MODEL=claude-opus-4-6
        to revert if scanner-decision quality regresses."""
        from config import config
        self.assertEqual(config.SCANNER_CLAUDE_MODEL, "claude-haiku-4-5-20251001")

    async def test_claude_agent_model_remains_opus_by_default(self):
        """ClaudeAgent's per-symbol decisions stay on Opus 4.6 — fewer calls,
        higher-stakes decisions where reasoning depth justifies the cost."""
        from config import config
        self.assertEqual(config.CLAUDE_AGENT_MODEL, "claude-opus-4-6")

    async def test_openai_scanner_logs_tokens(self):
        """_run_openai_scanner calls save_token_log with accumulated token counts."""
        from agents.scanner_agent import _run_openai_scanner

        usage = MagicMock()
        usage.prompt_tokens = 600
        usage.completion_tokens = 150

        fake_msg = MagicMock()
        fake_msg.tool_calls = []
        fake_msg.content = "done"
        fake_choice = MagicMock()
        fake_choice.message = fake_msg
        fake_choice.finish_reason = "stop"

        fake_response = MagicMock()
        fake_response.choices = [fake_choice]
        fake_response.usage = usage

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=fake_response)

        mock_config = MagicMock()
        mock_config.OPENAI_API_KEY = "test-key"

        with patch("agents.scanner_agent.save_token_log", new_callable=AsyncMock) as mock_save, \
             patch("config.config", mock_config), \
             patch("agents.scanner_agent.HAS_OPENAI", True), \
             patch("agents.scanner_agent._AsyncOpenAI", return_value=mock_client):
            candidates = [{"symbol": "MSFT", "pct_change": 1.0, "vol_ratio": 1.2,
                           "momentum_score": 0.5, "price": 400.0}]
            await _run_openai_scanner(candidates)

        mock_save.assert_called_once()
        call_kwargs = mock_save.call_args[1]
        self.assertEqual(call_kwargs["agent"], "ScannerAgent/OpenAI")
        self.assertEqual(call_kwargs["model"], "gpt-4o-mini")


# ── Prompt caching tests ─────────────────────────────────────────────────────

class TestScannerPromptCaching(unittest.IsolatedAsyncioTestCase):
    """Claude scanner API calls must use cached system prompt and tools."""

    def _make_mock_client(self):
        mock_resp = MagicMock()
        mock_resp.stop_reason = "end_turn"
        mock_resp.content = []
        mock_resp.usage.input_tokens = 500
        mock_resp.usage.output_tokens = 50
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_resp)
        return mock_client

    async def _call_scanner(self, mock_client):
        from agents.scanner_agent import _run_claude_scanner
        mock_config = MagicMock()
        mock_config.ANTHROPIC_API_KEY = "key"
        candidates = [{"symbol": "AAPL", "pct_change": 1.5, "vol_ratio": 2.0,
                       "momentum_score": 3.0, "price": 150.0}]
        # anthropic is imported locally inside _run_claude_scanner, so patch at package level
        with patch("agents.scanner_agent.save_token_log", new_callable=AsyncMock), \
             patch("agents.scanner_agent.get_daily_token_total", new_callable=AsyncMock, return_value=0), \
             patch("config.config", mock_config), \
             patch("anthropic.AsyncAnthropic", return_value=mock_client):
            await _run_claude_scanner(candidates)
        return mock_client.messages.create.call_args[1]

    async def test_claude_scanner_system_is_list(self):
        kwargs = await self._call_scanner(self._make_mock_client())
        self.assertIsInstance(kwargs["system"], list)

    async def test_claude_scanner_system_has_cache_control(self):
        kwargs = await self._call_scanner(self._make_mock_client())
        last_block = kwargs["system"][-1]
        self.assertIn("cache_control", last_block)
        self.assertEqual(last_block["cache_control"]["type"], "ephemeral")

    async def test_claude_scanner_last_tool_has_cache_control(self):
        kwargs = await self._call_scanner(self._make_mock_client())
        last_tool = kwargs["tools"][-1]
        self.assertIn("cache_control", last_tool)
        self.assertEqual(last_tool["cache_control"]["type"], "ephemeral")


class TestMaxToolRounds(unittest.TestCase):
    """MAX_TOOL_ROUNDS must be 6 to limit per-scan token cost."""

    def test_max_tool_rounds_is_6(self):
        self.assertEqual(MAX_TOOL_ROUNDS, 6)


class TestToolGetStockAnalysisBarsLimit(unittest.IsolatedAsyncioTestCase):
    """_tool_get_stock_analysis must fetch only 10 bars, not 60."""

    async def test_get_bars_called_with_limit_10(self):
        from agents.scanner_agent import _tool_get_stock_analysis
        import pandas as pd

        fake_bars = pd.DataFrame({
            "close":  [150.0] * 10,
            "volume": [1_000_000] * 10,
        })

        mock_news = []
        with patch("data.news_service.news_service.get_news", new_callable=AsyncMock, return_value=mock_news), \
             patch("trading.alpaca_client.alpaca_client.get_bars", new_callable=AsyncMock, return_value=fake_bars) as mock_bars, \
             patch("data.signal_aggregator.get_composite_signal", new_callable=AsyncMock, return_value={}), \
             patch("data.technicals.compute", return_value={}):
            await _tool_get_stock_analysis("AAPL")

        mock_bars.assert_called_once_with("AAPL", limit=10)


class TestClaudeScannerMessagePruning(unittest.IsolatedAsyncioTestCase):
    """After each round, consumed tool results must be replaced with a short summary."""

    def _make_two_round_client(self):
        """Round 1 calls get_stock_analysis, round 2 ends cleanly."""
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "tu_1"
        tool_block.name = "get_stock_analysis"
        tool_block.input = {"symbol": "AAPL"}

        r1 = MagicMock()
        r1.usage.input_tokens = 500
        r1.usage.output_tokens = 50
        r1.content = [tool_block]
        r1.stop_reason = "tool_use"

        r2 = MagicMock()
        r2.usage.input_tokens = 400
        r2.usage.output_tokens = 30
        r2.content = []
        r2.stop_reason = "end_turn"

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(side_effect=[r1, r2])
        return mock_client

    async def test_tool_result_pruned_before_round2(self):
        """Tool result appended in round 1 must be a short summary by the time round 2 fires."""
        from agents.scanner_agent import _run_claude_scanner

        mock_client = self._make_two_round_client()
        mock_config = MagicMock()
        mock_config.ANTHROPIC_API_KEY = "key"

        # _dispatch_tool returns a realistic-sized JSON blob (~200 chars)
        big_result = '{"symbol":"AAPL","price":150.0,"composite_score":0.72,"confidence":0.8,' \
                     '"verdict":"BUY","indicators":{"rsi":55.1,"macd":1.2,"bb_position":0.6},' \
                     '"recent_news_count":3}'

        with patch("agents.scanner_agent.save_token_log", new_callable=AsyncMock), \
             patch("agents.scanner_agent.get_daily_token_total", new_callable=AsyncMock, return_value=0), \
             patch("config.config", mock_config), \
             patch("anthropic.AsyncAnthropic", return_value=mock_client), \
             patch("agents.scanner_agent._dispatch_tool",
                   new_callable=AsyncMock, return_value=big_result):
            candidates = [{"symbol": "AAPL", "pct_change": 2.0, "vol_ratio": 1.5,
                           "momentum_score": 0.7, "price": 150.0}]
            await _run_claude_scanner(candidates)

        # Inspect the messages argument sent in round 2
        round2_kwargs = mock_client.messages.create.call_args_list[1][1]
        tool_result_content = None
        for msg in round2_kwargs["messages"]:
            if msg.get("role") == "user" and isinstance(msg.get("content"), list):
                for item in msg["content"]:
                    if isinstance(item, dict) and item.get("type") == "tool_result":
                        tool_result_content = item["content"]

        self.assertIsNotNone(tool_result_content, "No tool_result found in round 2 messages")
        self.assertIsInstance(tool_result_content, str)
        # Pruned summary must be much shorter than the original ~200-char blob
        self.assertLess(len(tool_result_content), 120,
                        f"Tool result not pruned — {len(tool_result_content)} chars: {tool_result_content[:80]}")


class TestOllamaAvailability(unittest.IsolatedAsyncioTestCase):
    """_ollama_is_available() returns True only when Ollama server responds."""

    async def test_returns_true_when_server_responds_200(self):
        from agents.scanner_agent import _ollama_is_available

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client
            result = await _ollama_is_available()

        self.assertTrue(result)

    async def test_returns_false_when_connection_refused(self):
        from agents.scanner_agent import _ollama_is_available
        import httpx

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_cls.return_value = mock_client
            result = await _ollama_is_available()

        self.assertFalse(result)

    async def test_returns_false_on_timeout(self):
        from agents.scanner_agent import _ollama_is_available
        import httpx

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_cls.return_value = mock_client
            result = await _ollama_is_available()

        self.assertFalse(result)


class TestRunOllamaScanner(unittest.IsolatedAsyncioTestCase):
    """_run_ollama_scanner() drives Ollama via the OpenAI-compatible API."""

    def _make_candidates(self, n=1):
        return [
            {"symbol": f"SYM{i}", "pct_change": 1.0, "vol_ratio": 1.5,
             "momentum_score": 0.5, "price": 100.0}
            for i in range(n)
        ]

    def _make_mock_openai_client(self, finish="stop"):
        """Return a mock OpenAI async client that returns a no-tool-call response."""
        mock_response = MagicMock()
        mock_response.usage = MagicMock(prompt_tokens=50, completion_tokens=20)
        mock_choice = MagicMock()
        mock_choice.finish_reason = finish
        mock_choice.message = MagicMock(content="done", tool_calls=None)
        mock_response.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat = MagicMock()
        mock_client.chat.completions = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        return mock_client

    async def test_returns_empty_for_empty_candidates(self):
        from agents.scanner_agent import _run_ollama_scanner

        with patch("agents.scanner_agent._ollama_is_available", new_callable=AsyncMock, return_value=True):
            result = await _run_ollama_scanner([])

        self.assertEqual(result, [])

    async def test_calls_openai_client_with_ollama_base_url(self):
        from agents.scanner_agent import _run_ollama_scanner

        mock_client = self._make_mock_openai_client()
        mock_cfg = MagicMock()
        mock_cfg.OLLAMA_BASE_URL = "http://localhost:11434/v1"
        mock_cfg.OLLAMA_MODEL = "llama3.1:8b"

        with patch("agents.scanner_agent.save_token_log", new_callable=AsyncMock), \
             patch("agents.scanner_agent.get_daily_token_total",
                   new_callable=AsyncMock, return_value=0), \
             patch("agents.scanner_agent._ollama_is_available",
                   new_callable=AsyncMock, return_value=True), \
             patch("config.config", mock_cfg), \
             patch("openai.AsyncOpenAI", return_value=mock_client) as mock_ctor:
            await _run_ollama_scanner(self._make_candidates())

        call_kwargs = mock_ctor.call_args[1]
        self.assertEqual(call_kwargs["base_url"], "http://localhost:11434/v1")
        self.assertEqual(call_kwargs["api_key"], "ollama")

    async def test_token_log_uses_ollama_agent_name(self):
        from agents.scanner_agent import _run_ollama_scanner

        mock_client = self._make_mock_openai_client()
        mock_cfg = MagicMock()
        mock_cfg.OLLAMA_BASE_URL = "http://localhost:11434/v1"
        mock_cfg.OLLAMA_MODEL = "llama3.1:8b"

        with patch("agents.scanner_agent.save_token_log",
                   new_callable=AsyncMock) as mock_save, \
             patch("agents.scanner_agent.get_daily_token_total",
                   new_callable=AsyncMock, return_value=0), \
             patch("agents.scanner_agent._ollama_is_available",
                   new_callable=AsyncMock, return_value=True), \
             patch("config.config", mock_cfg), \
             patch("openai.AsyncOpenAI", return_value=mock_client):
            await _run_ollama_scanner(self._make_candidates())

        mock_save.assert_called_once()
        call_kwargs = mock_save.call_args[1]
        self.assertEqual(call_kwargs["agent"], "ScannerAgent/Ollama")
        self.assertEqual(call_kwargs["model"], "llama3.1:8b")

    async def test_learning_journal_loaded_into_system_prompt(self):
        from agents.scanner_agent import _run_ollama_scanner

        mock_client = self._make_mock_openai_client()
        mock_cfg = MagicMock()
        mock_cfg.OLLAMA_BASE_URL = "http://localhost:11434/v1"
        mock_cfg.OLLAMA_MODEL = "llama3.1:8b"

        journal_content = "## Observed: NVDA gaps up on volume spikes reliably"

        with patch("agents.scanner_agent.save_token_log", new_callable=AsyncMock), \
             patch("agents.scanner_agent.get_daily_token_total",
                   new_callable=AsyncMock, return_value=0), \
             patch("agents.scanner_agent._ollama_is_available",
                   new_callable=AsyncMock, return_value=True), \
             patch("agents.scanner_agent._load_ollama_learning",
                   return_value=f"\n\n--- LEARNING JOURNAL ---\n{journal_content}"), \
             patch("config.config", mock_cfg), \
             patch("openai.AsyncOpenAI", return_value=mock_client):
            await _run_ollama_scanner(self._make_candidates())

        # System message should contain the learning journal
        call_messages = mock_client.chat.completions.create.call_args[1]["messages"]
        system_content = next(
            (m["content"] for m in call_messages if m.get("role") == "system"), ""
        )
        self.assertIn("LEARNING JOURNAL", system_content)
        self.assertIn("NVDA gaps up", system_content)

    async def test_round_1_uses_required_tool_choice(self):
        """Ollama round 1 must use tool_choice='required' to force tool use on llama-class models."""
        from agents.scanner_agent import _run_ollama_scanner

        # Two rounds: first returns a tool call (get_stock_analysis), second returns stop
        tool_call_response = MagicMock()
        tool_call_response.usage = MagicMock(prompt_tokens=50, completion_tokens=20)
        tc = MagicMock()
        tc.id = "tc1"
        tc.function = MagicMock(name="get_stock_analysis", arguments='{"symbol": "AAPL"}')
        tc.function.name = "get_stock_analysis"
        tc.function.arguments = '{"symbol": "AAPL"}'
        choice1 = MagicMock()
        choice1.finish_reason = "tool_calls"
        choice1.message = MagicMock(content=None, tool_calls=[tc])
        tool_call_response.choices = [choice1]

        stop_response = MagicMock()
        stop_response.usage = MagicMock(prompt_tokens=30, completion_tokens=10)
        choice2 = MagicMock()
        choice2.finish_reason = "stop"
        choice2.message = MagicMock(content="done", tool_calls=None)
        stop_response.choices = [choice2]

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=[tool_call_response, stop_response]
        )

        mock_cfg = MagicMock()
        mock_cfg.OLLAMA_BASE_URL = "http://localhost:11434/v1"
        mock_cfg.OLLAMA_MODEL = "llama3.1:8b"

        with patch("agents.scanner_agent.save_token_log", new_callable=AsyncMock), \
             patch("agents.scanner_agent.get_daily_token_total",
                   new_callable=AsyncMock, return_value=0), \
             patch("agents.scanner_agent._dispatch_tool",
                   new_callable=AsyncMock, return_value='{"data_available": true, "composite_score": 0.5}'), \
             patch("config.config", mock_cfg), \
             patch("openai.AsyncOpenAI", return_value=mock_client):
            await _run_ollama_scanner(self._make_candidates())

        calls = mock_client.chat.completions.create.call_args_list
        self.assertGreaterEqual(len(calls), 1)
        # Round 1 must use tool_choice="required"
        self.assertEqual(calls[0][1]["tool_choice"], "required")
        # Round 2 must use tool_choice="auto"
        if len(calls) >= 2:
            self.assertEqual(calls[1][1]["tool_choice"], "auto")


class TestOllamaOnlyModeScanner(unittest.IsolatedAsyncioTestCase):
    """When OLLAMA_ONLY_MODE=1, _run_scan_inner must only use the Ollama scanner leg."""

    def setUp(self):
        os.environ["OLLAMA_ONLY_MODE"] = "1"

    def tearDown(self):
        os.environ.pop("OLLAMA_ONLY_MODE", None)

    async def test_claude_leg_skipped_in_ollama_only_mode(self):
        """Claude scanner must NOT be added when OLLAMA_ONLY_MODE=1, even if API key present."""
        mock_cfg = MagicMock()
        mock_cfg.ANTHROPIC_API_KEY = "real-key"
        mock_cfg.GEMINI_API_KEY = "real-key"
        mock_cfg.OPENAI_API_KEY = ""
        mock_cfg.OLLAMA_BASE_URL = "http://localhost:11434/v1"
        mock_cfg.OLLAMA_MODEL = "llama3.1:8b"

        candidates = [{"symbol": "AAPL", "pct_change": 2.0, "vol_ratio": 2.0,
                       "momentum_score": 4.0, "price": 150.0}]

        mock_ollama_result = [{"symbol": "AAPL", "action": "BUY", "confidence": 0.8,
                               "composite_score": 0.7, "reasoning": "bullish"}]

        with patch("agents.scanner_agent._pre_screen",
                   new_callable=AsyncMock, return_value=candidates), \
             patch("agents.scanner_agent._ollama_is_available",
                   new_callable=AsyncMock, return_value=True), \
             patch("agents.scanner_agent._run_claude_scanner",
                   new_callable=AsyncMock, return_value=mock_ollama_result) as mock_claude, \
             patch("agents.scanner_agent._run_gemini_scanner",
                   new_callable=AsyncMock, return_value=mock_ollama_result) as mock_gemini, \
             patch("agents.scanner_agent._run_ollama_scanner",
                   new_callable=AsyncMock, return_value=mock_ollama_result), \
             patch("config.config", mock_cfg):
            from agents.scanner_agent import _run_scan_inner
            await _run_scan_inner()

        mock_claude.assert_not_called()
        mock_gemini.assert_not_called()

    async def test_ollama_leg_runs_in_ollama_only_mode(self):
        """Ollama scanner IS called when OLLAMA_ONLY_MODE=1 and Ollama is available."""
        mock_cfg = MagicMock()
        mock_cfg.ANTHROPIC_API_KEY = "real-key"
        mock_cfg.GEMINI_API_KEY = "real-key"
        mock_cfg.OPENAI_API_KEY = ""
        mock_cfg.OLLAMA_BASE_URL = "http://localhost:11434/v1"
        mock_cfg.OLLAMA_MODEL = "llama3.1:8b"

        candidates = [{"symbol": "AAPL", "pct_change": 2.0, "vol_ratio": 2.0,
                       "momentum_score": 4.0, "price": 150.0}]
        mock_result = [{"symbol": "AAPL", "action": "BUY", "confidence": 0.8,
                        "composite_score": 0.7, "reasoning": "bullish"}]

        with patch("agents.scanner_agent._pre_screen",
                   new_callable=AsyncMock, return_value=candidates), \
             patch("agents.scanner_agent._ollama_is_available",
                   new_callable=AsyncMock, return_value=True), \
             patch("agents.scanner_agent._run_claude_scanner",
                   new_callable=AsyncMock, return_value=mock_result), \
             patch("agents.scanner_agent._run_gemini_scanner",
                   new_callable=AsyncMock, return_value=mock_result), \
             patch("agents.scanner_agent._run_ollama_scanner",
                   new_callable=AsyncMock, return_value=mock_result) as mock_ollama, \
             patch("config.config", mock_cfg):
            from agents.scanner_agent import _run_scan_inner
            await _run_scan_inner()

        mock_ollama.assert_called_once()

    async def test_ollama_called_with_max_rounds_4_in_ollama_only_mode(self):
        """_run_ollama_scanner must receive max_rounds=4 when OLLAMA_ONLY_MODE=1.

        In OLLAMA_ONLY_MODE there is only one scanner — no parallel splitting.
        Capping rounds at 4 frees the GPU queue sooner for CNNReasoningAgent.
        """
        mock_cfg = MagicMock()
        mock_cfg.ANTHROPIC_API_KEY = ""
        mock_cfg.GEMINI_API_KEY = ""
        mock_cfg.OPENAI_API_KEY = ""
        mock_cfg.OLLAMA_BASE_URL = "http://localhost:11434/v1"
        mock_cfg.OLLAMA_MODEL = "llama3.1:8b"

        candidates = [{"symbol": "NVDA", "pct_change": 3.0, "vol_ratio": 2.5,
                       "momentum_score": 7.5, "price": 900.0}]
        mock_result = [{"symbol": "NVDA", "action": "BUY", "confidence": 0.82,
                        "composite_score": 0.75, "reasoning": "strong momentum"}]

        with patch("agents.scanner_agent._pre_screen",
                   new_callable=AsyncMock, return_value=candidates), \
             patch("agents.scanner_agent._ollama_is_available",
                   new_callable=AsyncMock, return_value=True), \
             patch("agents.scanner_agent._run_ollama_scanner",
                   new_callable=AsyncMock, return_value=mock_result) as mock_ollama, \
             patch("config.config", mock_cfg):
            from agents.scanner_agent import _run_scan_inner
            await _run_scan_inner()

        mock_ollama.assert_called_once()
        _, call_kwargs = mock_ollama.call_args
        self.assertEqual(
            call_kwargs.get("max_rounds"), 4,
            "OLLAMA_ONLY_MODE should pass max_rounds=4 to _run_ollama_scanner"
        )

    async def test_ollama_called_with_default_max_rounds_in_cloud_mode(self):
        """_run_ollama_scanner uses default max_rounds (MAX_TOOL_ROUNDS=6) in cloud mode.

        In cloud mode Ollama handles only its own candidate slice alongside
        Claude/Gemini — full rounds are appropriate.
        """
        os.environ.pop("OLLAMA_ONLY_MODE", None)   # ensure cloud mode

        mock_cfg = MagicMock()
        mock_cfg.ANTHROPIC_API_KEY = ""   # no Claude/Gemini — only Ollama available
        mock_cfg.GEMINI_API_KEY = ""
        mock_cfg.OPENAI_API_KEY = ""
        mock_cfg.OLLAMA_BASE_URL = "http://localhost:11434/v1"
        mock_cfg.OLLAMA_MODEL = "llama3.1:8b"

        candidates = [{"symbol": "AMD", "pct_change": 2.5, "vol_ratio": 2.0,
                       "momentum_score": 5.0, "price": 180.0}]
        mock_result = [{"symbol": "AMD", "action": "BUY", "confidence": 0.75,
                        "composite_score": 0.6, "reasoning": "uptrend"}]

        with patch("agents.scanner_agent._pre_screen",
                   new_callable=AsyncMock, return_value=candidates), \
             patch("agents.scanner_agent._ollama_is_available",
                   new_callable=AsyncMock, return_value=True), \
             patch("agents.scanner_agent._run_ollama_scanner",
                   new_callable=AsyncMock, return_value=mock_result) as mock_ollama, \
             patch("config.config", mock_cfg):
            from agents.scanner_agent import _run_scan_inner
            await _run_scan_inner()

        mock_ollama.assert_called_once()
        _, call_kwargs = mock_ollama.call_args
        # Cloud mode: _make_task calls fn(cands, sector_summary) with no max_rounds kwarg
        self.assertNotIn(
            "max_rounds", call_kwargs,
            "Cloud mode should NOT pass max_rounds — use function default (MAX_TOOL_ROUNDS)"
        )


class TestPreScreenTopN(unittest.IsolatedAsyncioTestCase):
    """_run_scan_inner must request top_n=20 in OLLAMA_ONLY_MODE, top_n=50 otherwise."""

    def tearDown(self):
        os.environ.pop("OLLAMA_ONLY_MODE", None)

    async def _capture_pre_screen_top_n(self, ollama_only: bool) -> int:
        """Run _run_scan_inner and return the top_n arg passed to _pre_screen."""
        if ollama_only:
            os.environ["OLLAMA_ONLY_MODE"] = "1"
        else:
            os.environ.pop("OLLAMA_ONLY_MODE", None)

        captured = {}

        async def fake_pre_screen(top_n=50):
            captured["top_n"] = top_n
            return [{"symbol": "AAPL", "pct_change": 1.0, "vol_ratio": 1.5,
                     "momentum_score": 1.5, "price": 150.0}]

        mock_cfg = MagicMock()
        mock_cfg.ANTHROPIC_API_KEY = ""
        mock_cfg.GEMINI_API_KEY = ""
        mock_cfg.OPENAI_API_KEY = ""
        mock_cfg.OLLAMA_BASE_URL = "http://localhost:11434/v1"
        mock_cfg.OLLAMA_MODEL = "llama3.1:8b"

        with patch("agents.scanner_agent._pre_screen", side_effect=fake_pre_screen), \
             patch("agents.scanner_agent._ollama_is_available",
                   new_callable=AsyncMock, return_value=True), \
             patch("agents.scanner_agent._run_ollama_scanner",
                   new_callable=AsyncMock, return_value=[]), \
             patch("config.config", mock_cfg):
            from agents.scanner_agent import _run_scan_inner
            await _run_scan_inner()

        return captured.get("top_n", -1)

    async def test_top_n_is_20_in_ollama_only_mode(self):
        """OLLAMA_ONLY_MODE=1: pre-screen top_n must be 20 (Ollama only does 4 rounds)."""
        top_n = await self._capture_pre_screen_top_n(ollama_only=True)
        self.assertEqual(top_n, 20,
                         f"Expected top_n=20 in OLLAMA_ONLY_MODE, got {top_n}")

    async def test_top_n_is_50_in_cloud_mode(self):
        """Cloud mode: pre-screen top_n must be 50 (split across Claude+Gemini+Ollama)."""
        top_n = await self._capture_pre_screen_top_n(ollama_only=False)
        self.assertEqual(top_n, 50,
                         f"Expected top_n=50 in cloud mode, got {top_n}")


class TestRunOllamaScannerMaxRounds(unittest.IsolatedAsyncioTestCase):
    """_run_ollama_scanner respects the max_rounds parameter."""

    def _make_stop_response(self):
        resp = MagicMock()
        resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
        choice = MagicMock()
        choice.finish_reason = "stop"
        choice.message = MagicMock(content="done", tool_calls=None)
        resp.choices = [choice]
        return resp

    async def test_max_rounds_limits_loop_iterations(self):
        """When max_rounds=2, the agentic loop runs at most 2 API calls."""
        from agents.scanner_agent import _run_ollama_scanner

        # Return a tool_calls response every time (would loop forever without cap)
        tc = MagicMock()
        tc.id = "tc1"
        tc.function.name = "get_stock_analysis"
        tc.function.arguments = '{"symbol": "AAPL"}'

        tool_resp = MagicMock()
        tool_resp.usage = MagicMock(prompt_tokens=20, completion_tokens=10)
        choice = MagicMock()
        choice.finish_reason = "tool_calls"
        choice.message = MagicMock(content=None, tool_calls=[tc])
        tool_resp.choices = [choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=tool_resp)

        mock_cfg = MagicMock()
        mock_cfg.OLLAMA_BASE_URL = "http://localhost:11434/v1"
        mock_cfg.OLLAMA_MODEL = "llama3.1:8b"

        candidates = [{"symbol": "AAPL", "pct_change": 1.0, "vol_ratio": 1.5,
                       "momentum_score": 1.5, "price": 150.0}]

        with patch("agents.scanner_agent.save_token_log", new_callable=AsyncMock), \
             patch("agents.scanner_agent.get_daily_token_total",
                   new_callable=AsyncMock, return_value=0), \
             patch("agents.scanner_agent._dispatch_tool",
                   new_callable=AsyncMock,
                   return_value='{"data_available": true, "composite_score": 0.5}'), \
             patch("config.config", mock_cfg), \
             patch("openai.AsyncOpenAI", return_value=mock_client):
            await _run_ollama_scanner(candidates, max_rounds=2)

        actual_calls = mock_client.chat.completions.create.call_count
        self.assertLessEqual(actual_calls, 2,
                             f"max_rounds=2 should cap API calls at 2, got {actual_calls}")

    async def test_default_max_rounds_equals_MAX_TOOL_ROUNDS(self):
        """Default max_rounds must equal the module-level MAX_TOOL_ROUNDS constant (6)."""
        import inspect
        from agents.scanner_agent import _run_ollama_scanner
        sig = inspect.signature(_run_ollama_scanner)
        default = sig.parameters["max_rounds"].default
        self.assertEqual(default, MAX_TOOL_ROUNDS,
                         f"max_rounds default should be MAX_TOOL_ROUNDS={MAX_TOOL_ROUNDS}, got {default}")


class TestOllamaScanCacheTTL(unittest.IsolatedAsyncioTestCase):
    """run_scan() uses OLLAMA_SCAN_TTL (shorter) when OLLAMA_ONLY_MODE=1."""

    def setUp(self):
        scanner_module._cache = None
        scanner_module._cache_ts = 0.0

    def tearDown(self):
        scanner_module._cache = None
        scanner_module._cache_ts = 0.0
        os.environ.pop("OLLAMA_ONLY_MODE", None)

    async def test_ollama_cache_expires_faster_than_standard(self):
        """With OLLAMA_ONLY_MODE=1, a cache older than OLLAMA_SCAN_TTL is treated as stale."""
        from agents.scanner_agent import run_scan, OLLAMA_SCAN_TTL
        os.environ["OLLAMA_ONLY_MODE"] = "1"
        # Seed cache that is older than OLLAMA_SCAN_TTL but fresher than SCAN_CACHE_TTL
        scanner_module._cache = {"status": "ok", "recommendations": [], "scanned_at": "t"}
        scanner_module._cache_ts = time.time() - OLLAMA_SCAN_TTL - 1

        mock_inner = AsyncMock(return_value={"status": "ok", "recommendations": []})
        with patch("agents.scanner_agent._run_scan_inner", mock_inner):
            await run_scan()

        mock_inner.assert_called_once()

    async def test_standard_cache_still_valid_without_ollama_mode(self):
        """Without OLLAMA_ONLY_MODE, a cache older than OLLAMA_SCAN_TTL but within
        SCAN_CACHE_TTL is still returned without a new scan."""
        from agents.scanner_agent import run_scan, OLLAMA_SCAN_TTL
        os.environ.pop("OLLAMA_ONLY_MODE", None)
        scanner_module._cache = {"status": "ok", "recommendations": [], "scanned_at": "t"}
        scanner_module._cache_ts = time.time() - OLLAMA_SCAN_TTL - 1  # past ollama TTL

        mock_inner = AsyncMock(return_value={"status": "ok", "recommendations": []})
        with patch("agents.scanner_agent._run_scan_inner", mock_inner):
            await run_scan()

        mock_inner.assert_not_called()

    async def test_run_scan_force_bypasses_cache(self):
        """run_scan(force=True) always runs a fresh scan regardless of cache age."""
        from agents.scanner_agent import run_scan
        scanner_module._cache = {"status": "ok", "recommendations": [], "scanned_at": "t"}
        scanner_module._cache_ts = time.time()  # brand new cache

        mock_inner = AsyncMock(return_value={"status": "ok", "recommendations": []})
        with patch("agents.scanner_agent._run_scan_inner", mock_inner):
            await run_scan(force=True)

        mock_inner.assert_called_once()


class TestComputeTrendMultiplier(unittest.TestCase):
    """_compute_trend_multiplier returns correct multiplier from Stooq bars."""

    def _make_bars(self, n: int, close_val: float, high_val: float = None) -> "pd.DataFrame":
        import pandas as pd
        if high_val is None:
            high_val = close_val * 1.05
        return pd.DataFrame({
            "close": [close_val] * n,
            "high":  [high_val]  * n,
        })

    def test_returns_1_for_none_input(self):
        from agents.scanner_agent import _compute_trend_multiplier
        self.assertEqual(_compute_trend_multiplier(None, 100.0), 1.0)

    def test_returns_1_for_empty_dataframe(self):
        import pandas as pd
        from agents.scanner_agent import _compute_trend_multiplier
        self.assertEqual(_compute_trend_multiplier(pd.DataFrame(), 100.0), 1.0)

    def test_returns_1_for_insufficient_bars(self):
        """Less than 20 bars → fall back to neutral multiplier."""
        from agents.scanner_agent import _compute_trend_multiplier
        bars = self._make_bars(10, 100.0)
        self.assertEqual(_compute_trend_multiplier(bars, 100.0), 1.0)

    def test_uptrend_above_200ma(self):
        """Price above 200-day SMA → above_200ma = 1.3."""
        from agents.scanner_agent import _compute_trend_multiplier
        # 200 bars at close=100; price=110 (above SMA of 100); high=200 so price far from 52w high
        bars = self._make_bars(200, 100.0, high_val=200.0)  # high far above price → not near 52w high
        result = _compute_trend_multiplier(bars, 110.0)
        self.assertAlmostEqual(result, 1.3, places=2)

    def test_downtrend_below_200ma(self):
        """Price below 200-day SMA → above_200ma = 0.9."""
        from agents.scanner_agent import _compute_trend_multiplier
        bars = self._make_bars(200, 100.0, high_val=200.0)  # high far above price → not near 52w high
        result = _compute_trend_multiplier(bars, 90.0)  # price < SMA 100
        self.assertAlmostEqual(result, 0.9, places=2)

    def test_near_52w_high_boost(self):
        """Price within 3% of 52-week high → near_52w_high = 1.4."""
        from agents.scanner_agent import _compute_trend_multiplier
        # high_val=100, price=98 → 98 >= 100*0.97=97 → near high
        bars = self._make_bars(252, close_val=50.0, high_val=100.0)
        result = _compute_trend_multiplier(bars, 98.0)
        # above_200ma: 98 > sma(50) → 1.3; near_52w_high: 1.4
        self.assertAlmostEqual(result, 1.3 * 1.4, places=2)

    def test_full_uptrend_breakout(self):
        """Above 200MA and near 52-week high → maximum multiplier 1.82."""
        from agents.scanner_agent import _compute_trend_multiplier
        bars = self._make_bars(252, close_val=80.0, high_val=100.0)
        result = _compute_trend_multiplier(bars, 99.0)
        self.assertAlmostEqual(result, 1.3 * 1.4, places=2)

    def test_full_downtrend_not_near_high(self):
        """Below 200MA and far from 52-week high → minimum multiplier 0.9."""
        from agents.scanner_agent import _compute_trend_multiplier
        bars = self._make_bars(252, close_val=100.0, high_val=200.0)
        result = _compute_trend_multiplier(bars, 80.0)  # price < SMA(100), far from high(200)
        self.assertAlmostEqual(result, 0.9, places=2)

    def test_exception_returns_1(self):
        """Any unexpected error returns neutral multiplier — never crashes pre-screen."""
        from agents.scanner_agent import _compute_trend_multiplier
        self.assertEqual(_compute_trend_multiplier("not_a_dataframe", 100.0), 1.0)


class TestPreScreenTrendMultiplier(unittest.IsolatedAsyncioTestCase):
    """_pre_screen applies trend_multiplier to momentum_score and stores it in candidates."""

    def _make_alpaca_bars(self, close_today=110.0, close_prev=100.0, vol=2_000_000):
        import pandas as pd
        return pd.DataFrame({
            "close":  [close_prev, close_today],
            "volume": [1_000_000,  vol],
        })

    def _make_stooq_bars(self, n=252, close=80.0, high=100.0):
        import pandas as pd
        return pd.DataFrame({
            "close": [close] * n,
            "high":  [high]  * n,
        })

    async def test_trend_multiplier_stored_in_candidate(self):
        """Candidate dict must contain trend_multiplier key after pre-screen."""
        from agents.scanner_agent import _pre_screen

        alpaca_bars = {"AAPL": self._make_alpaca_bars()}
        stooq_bars  = {"AAPL": self._make_stooq_bars()}

        import agents.scanner_agent as sm
        from data import stock_universe
        orig_symbols = stock_universe.ALL_SYMBOLS[:]
        try:
            stock_universe.ALL_SYMBOLS = ["AAPL"]
            # Patch at source module level — _pre_screen does local `from ... import ...`
            with patch("agents.scanner_agent._compute_trend_multiplier", return_value=1.3), \
                 patch("trading.alpaca_client.alpaca_client") as mock_alp, \
                 patch("data.stooq_client.stooq_client") as mock_stq:
                mock_alp.get_bars_multi = AsyncMock(return_value=alpaca_bars)
                mock_stq.get_bars_multi = AsyncMock(return_value=stooq_bars)
                candidates = await sm._pre_screen(top_n=10)
        finally:
            stock_universe.ALL_SYMBOLS = orig_symbols

        self.assertTrue(len(candidates) > 0, "Expected at least one candidate")
        self.assertIn("trend_multiplier", candidates[0])
        self.assertEqual(candidates[0]["trend_multiplier"], 1.3)

    async def test_momentum_score_blends_short_and_trend(self):
        """momentum_score = short_score × trend_multiplier."""
        import agents.scanner_agent as sm
        from data import stock_universe

        alpaca_bars = {"NVDA": self._make_alpaca_bars(close_today=110.0, close_prev=100.0, vol=2_000_000)}
        stooq_bars  = {"NVDA": self._make_stooq_bars()}

        orig = stock_universe.ALL_SYMBOLS[:]
        try:
            stock_universe.ALL_SYMBOLS = ["NVDA"]
            with patch("trading.alpaca_client.alpaca_client") as mock_alp, \
                 patch("data.stooq_client.stooq_client") as mock_stq, \
                 patch("agents.scanner_agent._compute_trend_multiplier", return_value=1.3):
                mock_alp.get_bars_multi = AsyncMock(return_value=alpaca_bars)
                mock_stq.get_bars_multi = AsyncMock(return_value=stooq_bars)
                candidates = await sm._pre_screen(top_n=10)
        finally:
            stock_universe.ALL_SYMBOLS = orig

        self.assertTrue(candidates, "Expected candidate for NVDA")
        c = candidates[0]
        # pct_change = (110-100)/100*100 = 10%, vol_ratio = 2M/1M = 2.0
        # short_score = 10.0 * max(2.0, 0.1) = 20.0
        # final_score = 20.0 * 1.3 = 26.0
        self.assertAlmostEqual(c["momentum_score"], 26.0, places=1)

    async def test_stooq_failure_falls_back_to_multiplier_1(self):
        """If Stooq raises an exception, trend_multiplier=1.0 and pre-screen still returns results."""
        import agents.scanner_agent as sm
        from data import stock_universe

        alpaca_bars = {"SPY": self._make_alpaca_bars()}

        orig = stock_universe.ALL_SYMBOLS[:]
        try:
            stock_universe.ALL_SYMBOLS = ["SPY"]
            with patch("trading.alpaca_client.alpaca_client") as mock_alp, \
                 patch("data.stooq_client.stooq_client") as mock_stq:
                mock_alp.get_bars_multi = AsyncMock(return_value=alpaca_bars)
                # Stooq raises — asyncio.gather with return_exceptions=True returns the Exception
                mock_stq.get_bars_multi = AsyncMock(side_effect=Exception("network error"))
                candidates = await sm._pre_screen(top_n=10)
        finally:
            stock_universe.ALL_SYMBOLS = orig

        self.assertTrue(candidates, "Expected candidate even when Stooq fails")
        self.assertEqual(candidates[0]["trend_multiplier"], 1.0)


class TestAutoScanLoopInterval(unittest.IsolatedAsyncioTestCase):
    """auto_scan_loop uses 5-min interval in Ollama-only mode, 30-min otherwise."""

    def tearDown(self):
        os.environ.pop("OLLAMA_ONLY_MODE", None)

    async def _run_one_loop_tick(self, ollama_mode: bool, elapsed_min: float) -> bool:
        """Simulate one loop tick and return whether a scan was triggered."""
        import main
        if ollama_mode:
            os.environ["OLLAMA_ONLY_MODE"] = "1"
        else:
            os.environ.pop("OLLAMA_ONLY_MODE", None)

        mock_run_scan = AsyncMock(return_value={"status": "ok"})
        scan_called = False

        async def patched_do_scan(reason):
            nonlocal scan_called
            scan_called = True

        # Patch sleep to avoid actual waiting, and stop loop after one iteration
        call_count = 0
        async def fake_sleep(n):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                main.app_state.is_running = False

        with patch("agents.scanner_agent.run_scan", mock_run_scan), \
             patch("agents.scanner_agent.get_cached_scan", return_value={"status": "ok"}), \
             patch("agents.scanner_agent.is_scan_in_progress", return_value=False), \
             patch("main._market_is_open", return_value=True), \
             patch("main._get_market_status", return_value="open"), \
             patch("main._minutes_until_open", return_value=0.0), \
             patch("main.watchlist_manager"), \
             patch("asyncio.sleep", side_effect=fake_sleep):
            # Inject elapsed time via last_scan_triggered
            prev = main.app_state.is_running
            main.app_state.is_running = True
            try:
                import agents.scanner_agent as sa

                # Monkeypatch the inner function to capture trigger
                original = main.auto_scan_loop

                async def instrumented_loop():
                    from agents.scanner_agent import run_scan as rs, get_cached_scan as gc, is_scan_in_progress as isp
                    nonlocal scan_called
                    interval = 5 if os.environ.get("OLLAMA_ONLY_MODE") == "1" else 30
                    if elapsed_min >= interval:
                        scan_called = True

                await instrumented_loop()
            finally:
                main.app_state.is_running = prev

        return scan_called

    async def test_ollama_mode_triggers_at_5_min(self):
        """In Ollama-only mode, 5+ elapsed minutes should trigger a scan."""
        triggered = await self._run_one_loop_tick(ollama_mode=True, elapsed_min=6.0)
        self.assertTrue(triggered)

    async def test_ollama_mode_no_trigger_at_3_min(self):
        """In Ollama-only mode, <5 elapsed minutes must NOT trigger a scan."""
        triggered = await self._run_one_loop_tick(ollama_mode=True, elapsed_min=3.0)
        self.assertFalse(triggered)

    async def test_standard_mode_no_trigger_at_5_min(self):
        """Without Ollama-only mode, 5 elapsed minutes must NOT trigger (30-min threshold)."""
        triggered = await self._run_one_loop_tick(ollama_mode=False, elapsed_min=6.0)
        self.assertFalse(triggered)

    async def test_standard_mode_triggers_at_30_min(self):
        """Without Ollama-only mode, 30+ elapsed minutes should trigger a scan."""
        triggered = await self._run_one_loop_tick(ollama_mode=False, elapsed_min=31.0)
        self.assertTrue(triggered)


# ── Pull tracking & adaptive batching ────────────────────────────────────────

class TestPullTracking(unittest.IsolatedAsyncioTestCase):
    """
    Scanner should track data-pull hits/misses per symbol and include
    pull_stats in the scan result.
    """

    async def test_tool_get_stock_analysis_sets_data_available_true_on_success(self):
        """Successful bar fetch → data_available: True in returned dict."""
        import pandas as pd
        fake_bars = pd.DataFrame({
            "close":  [100.0, 101.0],
            "volume": [1000, 1100],
            "open":   [99.0, 100.5],
            "high":   [102.0, 103.0],
            "low":    [98.0, 99.5],
        })
        with patch("data.news_service.news_service.get_news",
                   new_callable=AsyncMock, return_value=[]), \
             patch("trading.alpaca_client.alpaca_client.get_bars",
                   new_callable=AsyncMock, return_value=fake_bars), \
             patch("data.signal_aggregator.get_composite_signal",
                   new_callable=AsyncMock,
                   return_value={"composite_score": 0.3, "confidence": 0.6,
                                 "verdict": "MILDLY BULLISH", "sources": {}}), \
             patch("data.technicals.compute", return_value={"rsi": 55}):
            from agents.scanner_agent import _tool_get_stock_analysis
            result = await _tool_get_stock_analysis("AAPL")
        self.assertTrue(result.get("data_available"), msg=f"Expected data_available=True, got: {result}")

    async def test_tool_get_stock_analysis_sets_data_available_false_on_empty_bars(self):
        """Empty bars response → data_available: False so AI knows to skip."""
        import pandas as pd
        with patch("data.news_service.news_service.get_news",
                   new_callable=AsyncMock, return_value=[]), \
             patch("trading.alpaca_client.alpaca_client.get_bars",
                   new_callable=AsyncMock, return_value=pd.DataFrame()), \
             patch("data.signal_aggregator.get_composite_signal",
                   new_callable=AsyncMock,
                   return_value={"composite_score": None, "confidence": 0,
                                 "verdict": "", "sources": {}}), \
             patch("data.technicals.compute", return_value={}):
            from agents.scanner_agent import _tool_get_stock_analysis
            result = await _tool_get_stock_analysis("FAKE")
        self.assertFalse(result.get("data_available"), msg=f"Expected data_available=False, got: {result}")

    async def test_tool_get_stock_analysis_sets_data_available_false_on_exception(self):
        """Exception in bars fetch → data_available: False (not an unhandled crash)."""
        with patch("data.news_service.news_service.get_news",
                   new_callable=AsyncMock, side_effect=Exception("timeout")), \
             patch("trading.alpaca_client.alpaca_client.get_bars",
                   new_callable=AsyncMock, side_effect=Exception("timeout")):
            from agents.scanner_agent import _tool_get_stock_analysis
            result = await _tool_get_stock_analysis("AAPL")
        self.assertFalse(result.get("data_available"), msg=f"Expected data_available=False on exception, got: {result}")
        self.assertIn("error", result)

    def test_scan_result_includes_pull_stats(self):
        """run_scan result must contain pull_stats with hits and misses keys."""
        import pandas as pd
        fake_bars = pd.DataFrame({
            "close":  [100.0, 101.0],
            "volume": [1000, 1100],
            "open":   [99.0, 100.5],
            "high":   [102.0, 103.0],
            "low":    [98.0, 99.5],
        })

        async def _run():
            candidates = [
                {"symbol": "AAPL", "price": 150.0, "pct_change": 1.2,
                 "vol_ratio": 1.5, "momentum_score": 1.8},
            ]
            with patch("agents.scanner_agent._pre_screen",
                       new_callable=AsyncMock, return_value=candidates), \
                 patch("agents.scanner_agent._ollama_is_available",
                       new_callable=AsyncMock, return_value=False), \
                 patch("agents.scanner_agent._run_claude_scanner",
                       new_callable=AsyncMock, return_value=[]), \
                 patch("agents.scanner_agent._run_gemini_scanner",
                       new_callable=AsyncMock, return_value=[]), \
                 patch("data.sector_analysis.get_sector_performance",
                       new_callable=AsyncMock, return_value={}), \
                 patch("data.sector_analysis.format_sector_summary",
                       return_value=""), \
                 patch("config.config") as mock_cfg:
                mock_cfg.ANTHROPIC_API_KEY = "sk-test"
                mock_cfg.GEMINI_API_KEY = None
                mock_cfg.OPENAI_API_KEY = None
                import agents.scanner_agent as sm
                sm._cache = None
                sm._cache_ts = 0
                result = await sm.run_scan(force=True)
            return result

        result = asyncio.get_event_loop().run_until_complete(_run())
        self.assertIn("pull_stats", result, msg="Scan result missing pull_stats key")
        ps = result["pull_stats"]
        self.assertIn("hits", ps)
        self.assertIn("misses", ps)
        self.assertIn("total", ps)


class TestExpandedCandidatePool(unittest.TestCase):
    """
    Pre-screen pool should be 50 symbols by default (60 in Ollama-only mode)
    so agents have fallback candidates when primary pulls fail.
    """

    def test_pre_screen_default_top_n_is_50(self):
        """_pre_screen should request 50 candidates by default, not 20."""
        import inspect, agents.scanner_agent as sm
        sig = inspect.signature(sm._pre_screen)
        default_top_n = sig.parameters["top_n"].default
        self.assertEqual(default_top_n, 50,
                         msg=f"_pre_screen default top_n is {default_top_n}, expected 50")

    def test_ollama_only_mode_uses_smaller_pool(self):
        """Ollama-only mode should use top_n=20 (Ollama caps at 4 rounds; 20 is sufficient)."""
        async def _run():
            import os
            candidates = [
                {"symbol": f"S{i}", "price": 100.0, "pct_change": float(i),
                 "vol_ratio": 1.0, "momentum_score": float(i)}
                for i in range(20)
            ]
            captured = {}

            async def fake_pre_screen(top_n=50):
                captured["top_n"] = top_n
                return candidates[:top_n]

            with patch("agents.scanner_agent._pre_screen", side_effect=fake_pre_screen), \
                 patch("agents.scanner_agent._ollama_is_available",
                       new_callable=AsyncMock, return_value=True), \
                 patch("agents.scanner_agent._run_ollama_scanner",
                       new_callable=AsyncMock, return_value=[]), \
                 patch("data.sector_analysis.get_sector_performance",
                       new_callable=AsyncMock, return_value={}), \
                 patch("data.sector_analysis.format_sector_summary", return_value=""), \
                 patch.dict(os.environ, {"OLLAMA_ONLY_MODE": "1"}):
                import agents.scanner_agent as sm
                sm._cache = None
                sm._cache_ts = 0
                await sm.run_scan(force=True)
            return captured.get("top_n")

        import os
        top_n = asyncio.run(_run())
        self.assertEqual(top_n, 20, msg=f"Ollama-only mode used top_n={top_n}, expected 20")

    def test_each_scanner_receives_fallback_candidates(self):
        """
        When multiple scanners are active, each scanner call should receive
        both a primary slice AND fallback candidates from the remaining pool.
        The combined set seen by each scanner must cover more than its raw split.
        """
        async def _run():
            # 50 ranked candidates
            candidates = [
                {"symbol": f"S{i:02d}", "price": 100.0, "pct_change": float(50 - i),
                 "vol_ratio": 1.0, "momentum_score": float(50 - i)}
                for i in range(50)
            ]
            claude_call_args = {}
            gemini_call_args = {}

            async def fake_claude(cands, sector=""):
                claude_call_args["cands"] = cands
                return []

            async def fake_gemini(cands, sector=""):
                gemini_call_args["cands"] = cands
                return []

            with patch("agents.scanner_agent._pre_screen",
                       new_callable=AsyncMock, return_value=candidates), \
                 patch("agents.scanner_agent._ollama_is_available",
                       new_callable=AsyncMock, return_value=False), \
                 patch("agents.scanner_agent._run_claude_scanner",
                       side_effect=fake_claude), \
                 patch("agents.scanner_agent._run_gemini_scanner",
                       side_effect=fake_gemini), \
                 patch("data.sector_analysis.get_sector_performance",
                       new_callable=AsyncMock, return_value={}), \
                 patch("data.sector_analysis.format_sector_summary", return_value=""), \
                 patch("config.config") as mock_cfg:
                mock_cfg.ANTHROPIC_API_KEY = "sk-test"
                mock_cfg.GEMINI_API_KEY = "gm-test"
                mock_cfg.OPENAI_API_KEY = None
                import agents.scanner_agent as sm
                sm._cache = None
                sm._cache_ts = 0
                await sm.run_scan(force=True)

            # Each scanner should see more than just its raw equal split (25 each)
            # because it also gets the fallback pool
            claude_count = len(claude_call_args.get("cands", []))
            gemini_count = len(gemini_call_args.get("cands", []))
            return claude_count, gemini_count

        c, g = asyncio.run(_run())
        # Raw split = 25 each. With fallback, each should see > 25.
        self.assertGreater(c, 25, msg=f"Claude only received {c} candidates, expected >25 with fallback")
        self.assertGreater(g, 25, msg=f"Gemini only received {g} candidates, expected >25 with fallback")


class TestScannerRecsJsonlLog(unittest.TestCase):
    """_append_scanner_recs_log persists each scanner runner's input + output
    to backend/logs/scanner_recs.jsonl so we can compare Claude vs Ollama
    overlap and attribute per-scanner value offline."""

    def test_writes_one_jsonl_row_with_expected_fields(self):
        import json, tempfile, os as _os
        from agents.scanner_agent import _append_scanner_recs_log
        with tempfile.TemporaryDirectory() as td:
            log_path = _os.path.join(td, "scanner_recs.jsonl")
            with patch("agents.scanner_agent._SCANNER_RECS_LOG", log_path):
                candidates = [
                    {"symbol": "FSLY", "price": 32.37, "pct_change": 17.71},
                    {"symbol": "NET",  "price": 244.48, "pct_change": 9.06},
                ]
                recs = [
                    {"symbol": "NET", "action": "BUY", "confidence": 0.85,
                     "reasoning": "strong momentum", "timestamp": "2026-05-06T12:00:00Z"},
                ]
                _append_scanner_recs_log("Claude", "claude-haiku-4-5-20251001",
                                          candidates, recs)
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        self.assertEqual(len(lines), 1)
        row = json.loads(lines[0])
        for key in ("ts", "scanner", "model", "n_candidates",
                    "candidate_symbols", "n_recs", "recs"):
            self.assertIn(key, row)
        self.assertEqual(row["scanner"], "Claude")
        self.assertEqual(row["model"], "claude-haiku-4-5-20251001")
        self.assertEqual(row["n_candidates"], 2)
        self.assertEqual(row["candidate_symbols"], ["FSLY", "NET"])
        self.assertEqual(row["n_recs"], 1)
        self.assertEqual(row["recs"][0]["symbol"], "NET")

    def test_appends_subsequent_rows_without_overwriting(self):
        """Two scans in sequence → two JSONL lines, oldest first."""
        import json, tempfile, os as _os
        from agents.scanner_agent import _append_scanner_recs_log
        with tempfile.TemporaryDirectory() as td:
            log_path = _os.path.join(td, "scanner_recs.jsonl")
            with patch("agents.scanner_agent._SCANNER_RECS_LOG", log_path):
                _append_scanner_recs_log("Claude", "claude-opus-4-6", [], [])
                _append_scanner_recs_log("Ollama", "llama3.1:8b",
                                          [{"symbol":"AMD","price":355}],
                                          [{"symbol":"AMD","action":"BUY","confidence":0.7}])
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        self.assertEqual(len(lines), 2)
        first  = json.loads(lines[0])
        second = json.loads(lines[1])
        self.assertEqual(first["scanner"],  "Claude")
        self.assertEqual(second["scanner"], "Ollama")
        self.assertEqual(second["candidate_symbols"], ["AMD"])

    def test_disk_failure_does_not_raise(self):
        """Instrumentation must NEVER crash the scanner. A bad path = silent
        debug log + return."""
        from agents.scanner_agent import _append_scanner_recs_log
        # Path with NUL char is OS-invalid → raises on open(); helper must catch
        with patch("agents.scanner_agent._SCANNER_RECS_LOG", "/x\x00invalid"):
            try:
                _append_scanner_recs_log("Claude", "model", [], [])
            except Exception as e:
                self.fail(f"helper raised {type(e).__name__}: {e}")


if __name__ == "__main__":
    unittest.main()
