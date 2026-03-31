"""
Unit tests for main.py FastAPI endpoints.
Uses TestClient to test REST API without starting the real trading loop.
All agents, DB, market data, and scanner are mocked.
"""
import sys
import os
import asyncio
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# We import the app WITHOUT triggering lifespan (no startup/shutdown) by using
# fastapi.testclient.TestClient which does not invoke the lifespan by default.
from fastapi.testclient import TestClient


def _make_mock_agent(name="TestAgent"):
    agent = MagicMock()
    agent.name = name
    agent.strategy_description = "test strategy"
    agent.agent_id = 1
    agent._is_active = True
    agent._last_signals = {}
    agent._picks = {}
    agent.portfolio.positions = {}
    agent.get_state = MagicMock(return_value={
        "name": name,
        "total_value": 100000.0,
        "cash": 100000.0,
        "total_return_pct": 0.0,
        "positions": [],
    })
    agent.get_performance_metrics = MagicMock(return_value={
        "total_value": 100000.0,
        "cash": 100000.0,
        "total_return_pct": 0.0,
        "total_return": 0.0,
        "win_rate": 0.0,
        "sharpe_ratio": 0.0,
        "max_drawdown": 0.0,
        "total_trades": 0,
    })
    agent.get_pick_symbols = MagicMock(return_value=[])
    return agent


def _make_app_state(agents=None, is_running=False):
    """Patch app_state with controllable values."""
    from main import AppState
    state = AppState()
    state.is_running = is_running
    state.agents = agents or {}
    state.last_prices = {"AAPL": 150.0, "MSFT": 300.0}
    state.cycle_count = 5
    state.market_status = "closed"
    state.after_hours_catalysts = []
    state.last_sentinel_poll = None
    state.news_price_snapshots = []
    return state


class TestStatusEndpoint(unittest.TestCase):
    """GET /api/status returns 200 with expected fields."""

    def setUp(self):
        self.patcher_db = patch("main.init_db", new_callable=AsyncMock)
        self.patcher_agents = patch("main.init_agents", new_callable=AsyncMock)
        self.patcher_db.start()
        self.patcher_agents.start()

    def tearDown(self):
        self.patcher_db.stop()
        self.patcher_agents.stop()

    def test_get_status_returns_200(self):
        from main import app, app_state
        with TestClient(app, raise_server_exceptions=True) as client:
            with patch("main.app_state") as mock_state:
                mock_state.is_running = False
                mock_state.market_status = "closed"
                mock_state.cycle_count = 0
                mock_state.start_time = None
                mock_state.agents = {}
                mock_state.ws_connections = set()
                mock_state.after_hours_catalysts = []
                mock_state.last_sentinel_poll = None
                mock_state.news_price_snapshots = []
                mock_state.last_prices = {}

                with patch("main.config") as mock_cfg:
                    mock_cfg.WATCHLIST = ["AAPL", "MSFT"]
                    mock_cfg.STARTING_CAPITAL = 100000
                    mock_cfg.TRADE_INTERVAL_SECONDS = 60
                    response = client.get("/api/status")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("is_running", data)
        self.assertIn("market_status", data)
        self.assertIn("cycle_count", data)

    def test_status_fields_present(self):
        from main import app
        with TestClient(app, raise_server_exceptions=True) as client:
            with patch("main.app_state") as mock_state:
                mock_state.is_running = True
                mock_state.market_status = "open"
                mock_state.cycle_count = 42
                mock_state.start_time = None
                mock_state.agents = {}
                mock_state.ws_connections = set()
                mock_state.after_hours_catalysts = []
                mock_state.last_sentinel_poll = None
                mock_state.news_price_snapshots = []
                mock_state.last_prices = {}

                with patch("main.config") as mock_cfg:
                    mock_cfg.WATCHLIST = ["AAPL"]
                    mock_cfg.STARTING_CAPITAL = 100000
                    mock_cfg.TRADE_INTERVAL_SECONDS = 60
                    response = client.get("/api/status")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["is_running"], True)
        self.assertEqual(data["cycle_count"], 42)
        self.assertEqual(data["market_status"], "open")


class TestAgentsEndpoint(unittest.TestCase):
    """GET /api/agents returns list of agents."""

    def test_get_agents_returns_list(self):
        from main import app
        mock_agent = _make_mock_agent("TechAgent")

        with TestClient(app, raise_server_exceptions=True) as client:
            with patch("main.app_state") as mock_state:
                mock_state.agents = {"TechAgent": mock_agent}
                mock_state.last_prices = {"AAPL": 150.0}
                mock_state.is_running = False
                mock_state.market_status = "closed"
                mock_state.cycle_count = 0
                mock_state.start_time = None
                mock_state.ws_connections = set()
                mock_state.after_hours_catalysts = []
                mock_state.last_sentinel_poll = None
                mock_state.news_price_snapshots = []

                with patch("main.config") as mock_cfg:
                    mock_cfg.ALPACA_API_KEY = ""
                    mock_cfg.WATCHLIST = ["AAPL"]
                    response = client.get("/api/agents")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("agents", data)
        self.assertIn("count", data)
        self.assertIsInstance(data["agents"], list)

    def test_get_agents_count_matches_agents_dict(self):
        from main import app
        agents = {
            "TechAgent": _make_mock_agent("TechAgent"),
            "MomentumAgent": _make_mock_agent("MomentumAgent"),
        }

        with TestClient(app, raise_server_exceptions=True) as client:
            with patch("main.app_state") as mock_state:
                mock_state.agents = agents
                mock_state.last_prices = {}
                mock_state.is_running = False
                mock_state.market_status = "closed"
                mock_state.cycle_count = 0
                mock_state.start_time = None
                mock_state.ws_connections = set()
                mock_state.after_hours_catalysts = []
                mock_state.last_sentinel_poll = None
                mock_state.news_price_snapshots = []

                with patch("main.config") as mock_cfg:
                    mock_cfg.ALPACA_API_KEY = ""
                    mock_cfg.WATCHLIST = []
                    response = client.get("/api/agents")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 2)


class TestStartStopEndpoints(unittest.TestCase):
    """POST /api/start and /api/stop control trading state."""

    def test_start_when_already_running_returns_already_running(self):
        from main import app
        with TestClient(app, raise_server_exceptions=True) as client:
            with patch("main.app_state") as mock_state:
                mock_state.is_running = True
                mock_state.agents = {}
                mock_state.last_prices = {}
                mock_state.market_status = "closed"
                mock_state.cycle_count = 0
                mock_state.start_time = None
                mock_state.ws_connections = set()
                mock_state.after_hours_catalysts = []
                mock_state.last_sentinel_poll = None
                mock_state.news_price_snapshots = []

                with patch("main.config") as mock_cfg:
                    mock_cfg.ALPACA_API_KEY = "key"
                    mock_cfg.WATCHLIST = []
                    mock_cfg.TRADE_INTERVAL_SECONDS = 60
                    response = client.post("/api/start")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "already_running")

    def test_start_without_alpaca_key_returns_warning(self):
        from main import app
        with TestClient(app, raise_server_exceptions=True) as client:
            with patch("main.app_state") as mock_state:
                mock_state.is_running = False
                mock_state.agents = {}
                mock_state.last_prices = {}
                mock_state.market_status = "closed"
                mock_state.cycle_count = 0
                mock_state.start_time = None
                mock_state.ws_connections = set()
                mock_state.after_hours_catalysts = []
                mock_state.last_sentinel_poll = None
                mock_state.news_price_snapshots = []

                with patch("main.config") as mock_cfg:
                    mock_cfg.ALPACA_API_KEY = ""
                    mock_cfg.WATCHLIST = []
                    mock_cfg.TRADE_INTERVAL_SECONDS = 60
                    response = client.post("/api/start")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "warning")

    def test_stop_when_not_running_returns_not_running(self):
        from main import app
        with TestClient(app, raise_server_exceptions=True) as client:
            with patch("main.app_state") as mock_state:
                mock_state.is_running = False
                mock_state.agents = {}
                mock_state.last_prices = {}
                mock_state.market_status = "closed"
                mock_state.cycle_count = 3
                mock_state.start_time = None
                mock_state.ws_connections = set()
                mock_state.trading_task = None
                mock_state.scan_task = None
                mock_state.sentinel_task = None
                mock_state.after_hours_catalysts = []
                mock_state.last_sentinel_poll = None
                mock_state.news_price_snapshots = []

                response = client.post("/api/stop")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "not_running")


class TestScannerEndpoints(unittest.TestCase):
    """GET /api/scanner returns cached scan; POST /api/scanner/run with rate-limit."""

    def test_get_scanner_no_cache_returns_no_scan(self):
        from main import app
        with TestClient(app, raise_server_exceptions=True) as client:
            with patch("main.app_state") as mock_state:
                mock_state.is_running = False
                mock_state.agents = {}
                mock_state.last_prices = {}
                mock_state.market_status = "closed"
                mock_state.cycle_count = 0
                mock_state.start_time = None
                mock_state.ws_connections = set()
                mock_state.after_hours_catalysts = []
                mock_state.last_sentinel_poll = None
                mock_state.news_price_snapshots = []

                with patch("agents.scanner_agent.get_cached_scan", return_value=None), \
                     patch("agents.scanner_agent.is_scan_in_progress", return_value=False):
                    response = client.get("/api/scanner")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("status", data)
        # status should be "no_scan" or "scanning"
        self.assertIn(data["status"], ("no_scan", "scanning"))

    def test_get_scanner_with_cached_results(self):
        from main import app
        mock_scan = {
            "status": "ok",
            "recommendations": [{"symbol": "AAPL", "action": "BUY", "confidence": 0.75}],
            "candidates": [],
            "scanned_at": "2024-01-01T10:00:00",
        }

        with TestClient(app, raise_server_exceptions=True) as client:
            with patch("main.app_state") as mock_state:
                mock_state.is_running = False
                mock_state.agents = {}
                mock_state.last_prices = {}
                mock_state.market_status = "closed"
                mock_state.cycle_count = 0
                mock_state.start_time = None
                mock_state.ws_connections = set()
                mock_state.after_hours_catalysts = []
                mock_state.last_sentinel_poll = None
                mock_state.news_price_snapshots = []

                with patch("agents.scanner_agent.get_cached_scan", return_value=mock_scan), \
                     patch("agents.scanner_agent.is_scan_in_progress", return_value=False):
                    response = client.get("/api/scanner")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(len(data["recommendations"]), 1)

    def test_post_scanner_run_rate_limit(self):
        """POST /api/scanner/run returns 429 when rate limit exceeded."""
        from main import app, _rate_limit_store

        with TestClient(app, raise_server_exceptions=True) as client:
            with patch("main.app_state") as mock_state:
                mock_state.is_running = False
                mock_state.agents = {}
                mock_state.last_prices = {}
                mock_state.market_status = "closed"
                mock_state.cycle_count = 0
                mock_state.start_time = None
                mock_state.ws_connections = set()
                mock_state.after_hours_catalysts = []
                mock_state.last_sentinel_poll = None
                mock_state.news_price_snapshots = []

                # Exhaust the rate limit for the test client IP
                with patch("main._check_rate_limit", return_value=False):
                    response = client.post("/api/scanner/run")

        self.assertEqual(response.status_code, 429)

    def test_post_scanner_run_ok(self):
        """POST /api/scanner/run calls run_scan and returns result."""
        from main import app

        mock_result = {
            "status": "ok",
            "recommendations": [],
            "candidates": [],
            "scanned_at": "2024-01-01T10:00:00",
        }

        with TestClient(app, raise_server_exceptions=True) as client:
            with patch("main.app_state") as mock_state:
                mock_state.is_running = False
                mock_state.agents = {}
                mock_state.last_prices = {}
                mock_state.market_status = "closed"
                mock_state.cycle_count = 0
                mock_state.start_time = None
                mock_state.ws_connections = set()
                mock_state.after_hours_catalysts = []
                mock_state.last_sentinel_poll = None
                mock_state.news_price_snapshots = []

                with patch("main._check_rate_limit", return_value=True), \
                     patch("agents.scanner_agent.run_scan", new_callable=AsyncMock, return_value=mock_result):
                    response = client.post("/api/scanner/run")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")


class TestSentinelEndpoint(unittest.TestCase):
    """GET /api/sentinel returns catalyst list."""

    def test_get_sentinel_returns_200(self):
        from main import app

        with TestClient(app, raise_server_exceptions=True) as client:
            with patch("main.app_state") as mock_state:
                mock_state.is_running = False
                mock_state.agents = {}
                mock_state.last_prices = {}
                mock_state.market_status = "closed"
                mock_state.cycle_count = 0
                mock_state.start_time = None
                mock_state.ws_connections = set()
                mock_state.after_hours_catalysts = [
                    {"headline": "AAPL earnings beat", "score": 3, "category": "catalyst"}
                ]
                mock_state.last_sentinel_poll = "2024-01-01T09:00:00"
                mock_state.news_price_snapshots = []

                response = client.get("/api/sentinel")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("catalysts", data)
        self.assertIn("catalyst_count", data)
        self.assertEqual(data["catalyst_count"], 1)


class TestRateLimiter(unittest.TestCase):
    """_check_rate_limit blocks after MAX requests per window."""

    def test_allows_requests_under_limit(self):
        from main import _check_rate_limit, _rate_limit_store
        # Use a unique test IP
        ip = "test_rate_limit_ip_under"
        _rate_limit_store.pop(ip, None)
        for _ in range(5):
            result = _check_rate_limit(ip)
            self.assertTrue(result)

    def test_blocks_after_max_requests(self):
        from main import _check_rate_limit, _rate_limit_store, _RATE_LIMIT_MAX
        ip = "test_rate_limit_ip_over"
        _rate_limit_store.pop(ip, None)
        for _ in range(_RATE_LIMIT_MAX):
            _check_rate_limit(ip)
        # Next request should be blocked
        result = _check_rate_limit(ip)
        self.assertFalse(result)

    def tearDown(self):
        from main import _rate_limit_store
        for ip in ("test_rate_limit_ip_under", "test_rate_limit_ip_over"):
            _rate_limit_store.pop(ip, None)


class TestMarketStatusHelpers(unittest.TestCase):
    """_get_market_status, _market_is_open, _minutes_until_open."""

    def test_get_market_status_returns_string(self):
        from main import _get_market_status
        result = _get_market_status()
        self.assertIn(result, ("open", "closed"))

    def test_market_is_open_returns_bool(self):
        from main import _market_is_open
        result = _market_is_open()
        self.assertIsInstance(result, bool)

    def test_minutes_until_open_returns_non_negative(self):
        from main import _minutes_until_open
        result = _minutes_until_open()
        self.assertGreaterEqual(result, 0)

    def test_weekend_is_closed(self):
        from main import _get_market_status
        from datetime import datetime, timezone, timedelta
        # Find a Saturday
        # We'll mock _et_now to return a Saturday
        sat = datetime(2024, 1, 6, 12, 0, tzinfo=timezone(timedelta(hours=-5)))  # Saturday Jan 6 2024
        with patch("main._et_now", return_value=sat):
            result = _get_market_status()
        self.assertEqual(result, "closed")

    def test_market_open_during_trading_hours(self):
        from main import _get_market_status
        from datetime import datetime, timezone, timedelta
        # Wednesday Jan 10 2024, 10:30 AM EST — should be open
        weekday_open = datetime(2024, 1, 10, 10, 30, tzinfo=timezone(timedelta(hours=-5)))
        with patch("main._et_now", return_value=weekday_open):
            result = _get_market_status()
        self.assertEqual(result, "open")

    def test_market_closed_before_930(self):
        from main import _get_market_status
        from datetime import datetime, timezone, timedelta
        # Wednesday Jan 10 2024, 9:00 AM EST — before open
        before_open = datetime(2024, 1, 10, 9, 0, tzinfo=timezone(timedelta(hours=-5)))
        with patch("main._et_now", return_value=before_open):
            result = _get_market_status()
        self.assertEqual(result, "closed")


class TestRunAgentCyclePositionCleanup(unittest.IsolatedAsyncioTestCase):
    """run_agent_cycle must delete DB positions that were closed during a cycle."""

    async def test_closed_position_deleted_from_db(self):
        """When a cycle closes a position (removes from portfolio.positions),
        upsert_portfolio_position must be called with shares=0 to delete it."""
        from main import run_agent_cycle

        agent = MagicMock()
        agent.name = "TestAgent"
        agent.agent_id = 1
        # LYFT was open before the cycle
        from trading.portfolio import Position
        lyft_pos = Position(symbol="LYFT", shares=100.0, avg_cost=14.0)
        agent.portfolio.positions = {"LYFT": lyft_pos}
        agent.portfolio.trade_history = []

        # After run_cycle, LYFT is sold (removed from positions)
        async def mock_run_cycle(ctx, prices):
            agent.portfolio.positions = {}   # position closed
            return {}

        agent.run_cycle = mock_run_cycle

        with patch("main.save_trade", new_callable=AsyncMock), \
             patch("main.upsert_portfolio_position", new_callable=AsyncMock) as mock_upsert:
            await run_agent_cycle(agent, {}, {"LYFT": 13.90})

        # upsert_portfolio_position must be called with shares=0 for LYFT
        calls = mock_upsert.call_args_list
        lyft_calls = [c for c in calls if c.kwargs.get("symbol") == "LYFT" or
                      (c.args and "LYFT" in c.args)]
        self.assertTrue(
            any(
                (c.kwargs.get("shares") == 0 or (len(c.args) > 2 and c.args[2] == 0))
                for c in lyft_calls
            ),
            f"Expected upsert_portfolio_position called with shares=0 for LYFT, got: {calls}"
        )

    async def test_open_position_still_upserted(self):
        """Positions that remain open after a cycle are still written to DB."""
        from main import run_agent_cycle
        from trading.portfolio import Position

        agent = MagicMock()
        agent.name = "TestAgent"
        agent.agent_id = 1
        nvda_pos = Position(symbol="NVDA", shares=10.0, avg_cost=200.0)
        agent.portfolio.positions = {"NVDA": nvda_pos}
        agent.portfolio.trade_history = []

        async def mock_run_cycle(ctx, prices):
            return {}  # NVDA position unchanged

        agent.run_cycle = mock_run_cycle

        with patch("main.save_trade", new_callable=AsyncMock), \
             patch("main.upsert_portfolio_position", new_callable=AsyncMock) as mock_upsert:
            await run_agent_cycle(agent, {}, {"NVDA": 210.0})

        calls = mock_upsert.call_args_list
        nvda_calls = [c for c in calls if c.kwargs.get("symbol") == "NVDA" or
                      (c.args and "NVDA" in c.args)]
        self.assertTrue(len(nvda_calls) > 0, "Expected upsert_portfolio_position called for NVDA")
        # shares should be > 0
        for c in nvda_calls:
            shares = c.kwargs.get("shares") or (c.args[2] if len(c.args) > 2 else None)
            self.assertGreater(shares, 0)


class TestTokenUsageEndpoint(unittest.TestCase):
    """GET /api/tokens returns per-agent token stats and grand totals."""

    def _make_ai_agent(self, name, daily=1000, session=2500, calls_hour=1, limit=None):
        import time
        agent = MagicMock()
        agent.name = name
        agent._daily_tokens = daily
        agent._session_tokens = session
        agent._call_timestamps = [time.time() - 60]  # 1 call in last hour
        agent._hourly_call_limit = 2
        agent._daily_token_limit = limit  # None for Claude/Gemini, 10000 for Sentiment
        return agent

    def test_returns_200(self):
        from main import app, app_state
        claude = self._make_ai_agent("ClaudeAgent", daily=8000, session=16000)
        sentiment = self._make_ai_agent("SentimentAgent", daily=300, session=900, limit=10000)
        gemini = self._make_ai_agent("GeminiAgent", daily=7000, session=14000)

        with patch.object(app_state, "agents", {"ClaudeAgent": claude, "SentimentAgent": sentiment}), \
             patch.object(app_state, "gemini_news_agent", gemini):
            client = TestClient(app)
            resp = client.get("/api/tokens")
        self.assertEqual(resp.status_code, 200)

    def test_response_has_required_keys(self):
        from main import app, app_state
        claude = self._make_ai_agent("ClaudeAgent", daily=8000, session=16000)
        gemini = self._make_ai_agent("GeminiAgent", daily=7000, session=14000)

        with patch.object(app_state, "agents", {"ClaudeAgent": claude}), \
             patch.object(app_state, "gemini_news_agent", gemini):
            client = TestClient(app)
            data = client.get("/api/tokens").json()

        self.assertIn("agents", data)
        self.assertIn("totals", data)
        self.assertIn("daily_tokens", data["totals"])
        self.assertIn("session_tokens", data["totals"])

    def test_agent_entry_has_expected_fields(self):
        from main import app, app_state
        claude = self._make_ai_agent("ClaudeAgent", daily=8500, session=17000)

        with patch.object(app_state, "agents", {"ClaudeAgent": claude}), \
             patch.object(app_state, "gemini_news_agent", None):
            client = TestClient(app)
            data = client.get("/api/tokens").json()

        self.assertIn("ClaudeAgent", data["agents"])
        entry = data["agents"]["ClaudeAgent"]
        for field in ("daily_tokens", "session_tokens", "calls_this_hour", "hourly_call_limit"):
            self.assertIn(field, entry)

    def test_totals_sum_all_agents(self):
        from main import app, app_state
        claude = self._make_ai_agent("ClaudeAgent", daily=8000, session=16000)
        sentiment = self._make_ai_agent("SentimentAgent", daily=300, session=900, limit=10000)
        gemini = self._make_ai_agent("GeminiAgent", daily=7000, session=14000)

        with patch.object(app_state, "agents", {"ClaudeAgent": claude, "SentimentAgent": sentiment}), \
             patch.object(app_state, "gemini_news_agent", gemini):
            client = TestClient(app)
            data = client.get("/api/tokens").json()

        self.assertEqual(data["totals"]["daily_tokens"], 8000 + 300 + 7000)
        self.assertEqual(data["totals"]["session_tokens"], 16000 + 900 + 14000)

    def test_daily_limit_included_for_sentiment(self):
        from main import app, app_state
        sentiment = self._make_ai_agent("SentimentAgent", daily=300, session=900, limit=10000)

        with patch.object(app_state, "agents", {"SentimentAgent": sentiment}), \
             patch.object(app_state, "gemini_news_agent", None):
            client = TestClient(app)
            data = client.get("/api/tokens").json()

        entry = data["agents"]["SentimentAgent"]
        self.assertEqual(entry.get("daily_limit"), 10000)
        self.assertEqual(entry.get("daily_remaining"), 9700)

    def test_gemini_included_from_news_agent(self):
        from main import app, app_state
        gemini = self._make_ai_agent("GeminiAgent", daily=7000, session=14000)

        with patch.object(app_state, "agents", {}), \
             patch.object(app_state, "gemini_news_agent", gemini):
            client = TestClient(app)
            data = client.get("/api/tokens").json()

        self.assertIn("GeminiAgent", data["agents"])


class TestTokenLogEndpoint(unittest.TestCase):
    """GET /api/token-log returns DB token log entries with filtering."""

    def setUp(self):
        self.patcher_db = patch("main.init_db", new_callable=AsyncMock)
        self.patcher_agents = patch("main.init_agents", new_callable=AsyncMock)
        self.patcher_db.start()
        self.patcher_agents.start()

    def tearDown(self):
        self.patcher_db.stop()
        self.patcher_agents.stop()

    def _sample_entries(self):
        return [
            {
                "id": 1,
                "timestamp": "2026-03-20T10:00:00",
                "agent": "SentimentAgent",
                "model": "gpt-4o-mini",
                "prompt_tokens": 200,
                "completion_tokens": 100,
                "total_tokens": 300,
                "daily_total": 300,
                "daily_limit": 10000,
                "limit_hit": False,
            }
        ]

    def test_returns_200(self):
        from main import app
        with patch("main.get_token_log", new_callable=AsyncMock, return_value=self._sample_entries()):
            with TestClient(app) as client:
                resp = client.get("/api/token-log")
        self.assertEqual(resp.status_code, 200)

    def test_response_has_entries_key(self):
        from main import app
        with patch("main.get_token_log", new_callable=AsyncMock, return_value=self._sample_entries()):
            with TestClient(app) as client:
                data = client.get("/api/token-log").json()
        self.assertIn("entries", data)
        self.assertEqual(len(data["entries"]), 1)

    def test_entry_has_expected_fields(self):
        from main import app
        with patch("main.get_token_log", new_callable=AsyncMock, return_value=self._sample_entries()):
            with TestClient(app) as client:
                data = client.get("/api/token-log").json()
        entry = data["entries"][0]
        for field in ("timestamp", "agent", "model", "prompt_tokens", "completion_tokens", "total_tokens", "limit_hit"):
            self.assertIn(field, entry)

    def test_agent_query_param_forwarded(self):
        from main import app
        with patch("main.get_token_log", new_callable=AsyncMock, return_value=[]) as mock_fn:
            with TestClient(app) as client:
                client.get("/api/token-log?agent=SentimentAgent")
        call_kwargs = mock_fn.call_args[1]
        self.assertEqual(call_kwargs.get("agent"), "SentimentAgent")

    def test_hours_query_param_forwarded(self):
        from main import app
        with patch("main.get_token_log", new_callable=AsyncMock, return_value=[]) as mock_fn:
            with TestClient(app) as client:
                client.get("/api/token-log?hours=12")
        call_kwargs = mock_fn.call_args[1]
        self.assertEqual(call_kwargs.get("hours"), 12)

    def test_limit_hit_filter_forwarded(self):
        from main import app
        with patch("main.get_token_log", new_callable=AsyncMock, return_value=[]) as mock_fn:
            with TestClient(app) as client:
                client.get("/api/token-log?limit_hit=true")
        call_kwargs = mock_fn.call_args[1]
        self.assertTrue(call_kwargs.get("limit_hit_only"))

    def test_empty_returns_empty_list(self):
        from main import app
        with patch("main.get_token_log", new_callable=AsyncMock, return_value=[]):
            with TestClient(app) as client:
                data = client.get("/api/token-log").json()
        self.assertEqual(data["entries"], [])

    def test_hours_zero_forwarded_as_all_time(self):
        """hours=0 is forwarded to get_token_log — signals all-time query."""
        from main import app
        with patch("main.get_token_log", new_callable=AsyncMock, return_value=[]) as mock_fn:
            with TestClient(app) as client:
                client.get("/api/token-log?hours=0")
        call_kwargs = mock_fn.call_args[1]
        self.assertEqual(call_kwargs.get("hours"), 0)


class TestUpdateNewsPriceSnapshots(unittest.TestCase):
    """Unit tests for _update_news_price_snapshots — price_open / price_1h logic."""

    def _make_snap(self, symbol="AAPL", price_at=100.0):
        return {
            "symbol":            symbol,
            "headline":          "Test headline",
            "score":             3,
            "category":          "catalyst",
            "price_at":          price_at,
            "detected_at":       "2024-01-01T00:00:00Z",
            "price_open":        None,
            "price_1h":          None,
            "change_open":       None,
            "change_1h":         None,
            "open_recorded_at":  None,
        }

    def _call(self, snaps, prices, now=None):
        import main
        from unittest.mock import patch as _patch
        import datetime as dt
        fixed = now or dt.datetime(2024, 1, 2, 10, 0, 0)
        with _patch("main.datetime") as mock_dt:
            mock_dt.utcnow.return_value = fixed
            mock_dt.side_effect = lambda *a, **kw: dt.datetime(*a, **kw)
            old = main.app_state.news_price_snapshots
            main.app_state.news_price_snapshots = snaps
            main._update_news_price_snapshots(prices)
            result = list(main.app_state.news_price_snapshots)
            main.app_state.news_price_snapshots = old
        return result

    def test_price_open_set_on_first_call(self):
        snap = self._make_snap(price_at=100.0)
        result = self._call([snap], {"AAPL": 102.0})
        self.assertAlmostEqual(result[0]["price_open"], 102.0)
        self.assertAlmostEqual(result[0]["change_open"], 2.0)
        self.assertIsNotNone(result[0]["open_recorded_at"])

    def test_price_1h_not_set_before_60_minutes(self):
        """price_1h must stay None if fewer than 60 min have elapsed since price_open."""
        import datetime as dt
        snap = self._make_snap(price_at=100.0)
        snap["price_open"] = 102.0
        snap["change_open"] = 2.0
        snap["open_recorded_at"] = dt.datetime(2024, 1, 2, 10, 0, 0)  # exactly now
        # Call 30 minutes later — should not set price_1h
        later = dt.datetime(2024, 1, 2, 10, 30, 0)
        result = self._call([snap], {"AAPL": 105.0}, now=later)
        self.assertIsNone(result[0]["price_1h"])
        self.assertIsNone(result[0]["change_1h"])

    def test_price_1h_set_after_60_minutes(self):
        """price_1h is set once >= 60 min have elapsed since price_open."""
        import datetime as dt
        snap = self._make_snap(price_at=100.0)
        snap["price_open"] = 102.0
        snap["change_open"] = 2.0
        snap["open_recorded_at"] = dt.datetime(2024, 1, 2, 9, 0, 0)
        # Call 61 minutes later
        later = dt.datetime(2024, 1, 2, 10, 1, 0)
        result = self._call([snap], {"AAPL": 103.0}, now=later)
        self.assertAlmostEqual(result[0]["price_1h"], 103.0)
        self.assertAlmostEqual(result[0]["change_1h"], 3.0)

    def test_price_1h_frozen_after_first_set(self):
        """Once price_1h is set it must not be overwritten on subsequent cycles."""
        import datetime as dt
        snap = self._make_snap(price_at=100.0)
        snap["price_open"] = 102.0
        snap["change_open"] = 2.0
        snap["open_recorded_at"] = dt.datetime(2024, 1, 2, 9, 0, 0)
        snap["price_1h"] = 103.0
        snap["change_1h"] = 3.0
        # Call again with a different price — should not change price_1h
        later = dt.datetime(2024, 1, 2, 12, 0, 0)
        result = self._call([snap], {"AAPL": 110.0}, now=later)
        self.assertAlmostEqual(result[0]["price_1h"], 103.0)
        self.assertAlmostEqual(result[0]["change_1h"], 3.0)

    def test_symbol_not_in_prices_skipped(self):
        snap = self._make_snap(symbol="TSLA", price_at=200.0)
        result = self._call([snap], {"AAPL": 150.0})  # TSLA not in prices
        self.assertIsNone(result[0]["price_open"])

    def test_snapshots_trimmed_to_100(self):
        snaps = [self._make_snap(price_at=100.0) for _ in range(110)]
        result = self._call(snaps, {"AAPL": 102.0})
        self.assertEqual(len(result), 100)


if __name__ == "__main__":
    unittest.main()
