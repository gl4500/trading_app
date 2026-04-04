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

    def setUp(self):
        # Scanner agents query the DB; default to zero so existing tests are unaffected.
        self._p_daily = patch("main.get_daily_token_total", new_callable=AsyncMock, return_value=0)
        self._p_calls = patch("main.get_agent_calls_this_hour", new_callable=AsyncMock, return_value=0)
        self._p_daily.start()
        self._p_calls.start()

    def tearDown(self):
        self._p_daily.stop()
        self._p_calls.stop()

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

    def test_scanner_agents_included(self):
        """ScannerAgent/Claude, /Gemini, /OpenAI must appear in /api/tokens."""
        from main import app, app_state

        with patch.object(app_state, "agents", {}), \
             patch.object(app_state, "gemini_news_agent", None), \
             patch("main.get_daily_token_total", new_callable=AsyncMock, return_value=50000), \
             patch("main.get_agent_calls_this_hour", new_callable=AsyncMock, return_value=2):
            client = TestClient(app)
            data = client.get("/api/tokens").json()

        for name in ("ScannerAgent/Claude", "ScannerAgent/Gemini", "ScannerAgent/OpenAI"):
            self.assertIn(name, data["agents"], f"{name} missing from agents")

    def test_scanner_agent_fields(self):
        """Each scanner agent entry has daily_tokens, calls_this_hour, and hourly_call_limit."""
        from main import app, app_state

        with patch.object(app_state, "agents", {}), \
             patch.object(app_state, "gemini_news_agent", None), \
             patch("main.get_daily_token_total", new_callable=AsyncMock, return_value=123000), \
             patch("main.get_agent_calls_this_hour", new_callable=AsyncMock, return_value=3):
            client = TestClient(app)
            data = client.get("/api/tokens").json()

        entry = data["agents"]["ScannerAgent/Claude"]
        self.assertEqual(entry["daily_tokens"], 123000)
        self.assertEqual(entry["calls_this_hour"], 3)
        self.assertIsNone(entry["hourly_call_limit"])

    def test_scanner_tokens_included_in_totals(self):
        """Scanner daily_tokens must be included in totals.daily_tokens."""
        from main import app, app_state
        claude = self._make_ai_agent("ClaudeAgent", daily=10000, session=20000)

        with patch.object(app_state, "agents", {"ClaudeAgent": claude}), \
             patch.object(app_state, "gemini_news_agent", None), \
             patch("main.get_daily_token_total", new_callable=AsyncMock, return_value=5000), \
             patch("main.get_agent_calls_this_hour", new_callable=AsyncMock, return_value=1):
            client = TestClient(app)
            data = client.get("/api/tokens").json()

        # 10000 (Claude) + 3 × 5000 (three scanner agents)
        self.assertEqual(data["totals"]["daily_tokens"], 10000 + 3 * 5000)


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


class TestUpdateNewsPriceSnapshots(unittest.IsolatedAsyncioTestCase):
    """Unit tests for _update_news_price_snapshots — price_open / price_1h / DB persistence."""

    def _make_snap(self, symbol="AAPL", price_at=100.0, during_session=False,
                   detected_at="2024-01-02T09:30:00Z", db_id=None):
        snap = {
            "symbol":            symbol,
            "headline":          "Test headline",
            "score":             3,
            "category":          "catalyst",
            "price_at":          price_at,
            "detected_at":       detected_at,
            "during_session":    during_session,
            "price_open":        None,
            "price_1h":          None,
            "change_open":       None,
            "change_1h":         None,
            "open_recorded_at":  None,
        }
        if db_id is not None:
            snap["_db_id"] = db_id
        return snap

    async def _call(self, snaps, prices, now=None):
        import main
        from unittest.mock import patch as _patch, AsyncMock
        import datetime as dt
        fixed = now or dt.datetime(2024, 1, 2, 10, 0, 0)
        with _patch("main.datetime") as mock_dt, \
             _patch("main.update_price_snapshot", new_callable=AsyncMock), \
             _patch("main.record_catalyst_outcome"):
            mock_dt.utcnow.return_value = fixed
            mock_dt.fromisoformat = dt.datetime.fromisoformat
            mock_dt.side_effect = lambda *a, **kw: dt.datetime(*a, **kw)
            old = main.app_state.news_price_snapshots
            main.app_state.news_price_snapshots = snaps
            await main._update_news_price_snapshots(prices)
            result = list(main.app_state.news_price_snapshots)
            main.app_state.news_price_snapshots = old
        return result

    # ── After-hours catalysts ──────────────────────────────────────────────────

    async def test_afterhours_price_open_set_on_first_cycle(self):
        """After-hours catalysts: price_open captured immediately at market open."""
        snap = self._make_snap(price_at=100.0, during_session=False)
        result = await self._call([snap], {"AAPL": 102.0})
        self.assertAlmostEqual(result[0]["price_open"], 102.0)
        self.assertAlmostEqual(result[0]["change_open"], 2.0)
        self.assertIsNotNone(result[0]["open_recorded_at"])

    # ── Intraday catalysts ─────────────────────────────────────────────────────

    async def test_intraday_price_open_not_set_before_5_minutes(self):
        """Intraday catalysts: price_open NOT set until >= 5 min after detection."""
        import datetime as dt
        detected = "2024-01-02T10:00:00Z"
        snap = self._make_snap(price_at=100.0, during_session=True, detected_at=detected)
        three_min_later = dt.datetime(2024, 1, 2, 10, 3, 0)
        result = await self._call([snap], {"AAPL": 102.0}, now=three_min_later)
        self.assertIsNone(result[0]["price_open"])

    async def test_intraday_price_open_set_after_5_minutes(self):
        """Intraday catalysts: price_open captured once >= 5 min have elapsed."""
        import datetime as dt
        detected = "2024-01-02T10:00:00Z"
        snap = self._make_snap(price_at=100.0, during_session=True, detected_at=detected)
        six_min_later = dt.datetime(2024, 1, 2, 10, 6, 0)
        result = await self._call([snap], {"AAPL": 103.0}, now=six_min_later)
        self.assertAlmostEqual(result[0]["price_open"], 103.0)
        self.assertAlmostEqual(result[0]["change_open"], 3.0)
        self.assertIsNotNone(result[0]["open_recorded_at"])

    # ── Shared 1h freeze logic ─────────────────────────────────────────────────

    async def test_price_1h_not_set_before_60_minutes(self):
        import datetime as dt
        snap = self._make_snap(price_at=100.0)
        snap["price_open"] = 102.0
        snap["change_open"] = 2.0
        snap["open_recorded_at"] = dt.datetime(2024, 1, 2, 10, 0, 0)
        later = dt.datetime(2024, 1, 2, 10, 30, 0)
        result = await self._call([snap], {"AAPL": 105.0}, now=later)
        self.assertIsNone(result[0]["price_1h"])
        self.assertIsNone(result[0]["change_1h"])

    async def test_price_1h_set_after_60_minutes(self):
        import datetime as dt
        snap = self._make_snap(price_at=100.0)
        snap["price_open"] = 102.0
        snap["change_open"] = 2.0
        snap["open_recorded_at"] = dt.datetime(2024, 1, 2, 9, 0, 0)
        later = dt.datetime(2024, 1, 2, 10, 1, 0)
        result = await self._call([snap], {"AAPL": 103.0}, now=later)
        self.assertAlmostEqual(result[0]["price_1h"], 103.0)
        self.assertAlmostEqual(result[0]["change_1h"], 3.0)

    async def test_price_1h_frozen_after_first_set(self):
        import datetime as dt
        snap = self._make_snap(price_at=100.0)
        snap["price_open"] = 102.0
        snap["change_open"] = 2.0
        snap["open_recorded_at"] = dt.datetime(2024, 1, 2, 9, 0, 0)
        snap["price_1h"] = 103.0
        snap["change_1h"] = 3.0
        later = dt.datetime(2024, 1, 2, 12, 0, 0)
        result = await self._call([snap], {"AAPL": 110.0}, now=later)
        self.assertAlmostEqual(result[0]["price_1h"], 103.0)
        self.assertAlmostEqual(result[0]["change_1h"], 3.0)

    async def test_symbol_not_in_prices_skipped(self):
        snap = self._make_snap(symbol="TSLA", price_at=200.0)
        result = await self._call([snap], {"AAPL": 150.0})
        self.assertIsNone(result[0]["price_open"])

    async def test_snapshots_trimmed_to_100(self):
        snaps = [self._make_snap(price_at=100.0) for _ in range(110)]
        result = await self._call(snaps, {"AAPL": 102.0})
        self.assertEqual(len(result), 100)

    async def test_update_price_snapshot_called_when_price_open_set(self):
        """DB update is called when price_open is first recorded."""
        import main
        import datetime as dt
        from unittest.mock import AsyncMock
        snap = self._make_snap(price_at=100.0, db_id=42)
        fixed = dt.datetime(2024, 1, 2, 10, 0, 0)
        with patch("main.datetime") as mock_dt, \
             patch("main.update_price_snapshot", new_callable=AsyncMock) as mock_upd, \
             patch("main.record_catalyst_outcome"):
            mock_dt.utcnow.return_value = fixed
            mock_dt.fromisoformat = dt.datetime.fromisoformat
            old = main.app_state.news_price_snapshots
            main.app_state.news_price_snapshots = [snap]
            await main._update_news_price_snapshots({"AAPL": 102.0})
            main.app_state.news_price_snapshots = old
        mock_upd.assert_called_once()
        call_kwargs = mock_upd.call_args[1]
        self.assertAlmostEqual(call_kwargs["price_open"], 102.0)

    async def test_update_price_snapshot_called_when_price_1h_set(self):
        """DB update is called when price_1h is frozen."""
        import main
        import datetime as dt
        from unittest.mock import AsyncMock
        snap = self._make_snap(price_at=100.0, db_id=7)
        snap["price_open"] = 102.0
        snap["change_open"] = 2.0
        snap["open_recorded_at"] = dt.datetime(2024, 1, 2, 9, 0, 0)
        later = dt.datetime(2024, 1, 2, 10, 1, 0)
        with patch("main.datetime") as mock_dt, \
             patch("main.update_price_snapshot", new_callable=AsyncMock) as mock_upd, \
             patch("main.record_catalyst_outcome"):
            mock_dt.utcnow.return_value = later
            mock_dt.fromisoformat = dt.datetime.fromisoformat
            old = main.app_state.news_price_snapshots
            main.app_state.news_price_snapshots = [snap]
            await main._update_news_price_snapshots({"AAPL": 103.0})
            main.app_state.news_price_snapshots = old
        mock_upd.assert_called_once()
        call_kwargs = mock_upd.call_args[1]
        self.assertAlmostEqual(call_kwargs["price_1h"], 103.0)

    async def test_record_catalyst_outcome_called_when_price_1h_frozen(self):
        import main
        import datetime as dt
        from unittest.mock import AsyncMock
        snap = self._make_snap(price_at=100.0)
        snap["price_open"] = 102.0
        snap["change_open"] = 2.0
        snap["open_recorded_at"] = dt.datetime(2024, 1, 2, 9, 0, 0)
        later = dt.datetime(2024, 1, 2, 10, 1, 0)
        with patch("main.datetime") as mock_dt, \
             patch("main.update_price_snapshot", new_callable=AsyncMock), \
             patch("main.record_catalyst_outcome") as mock_record:
            mock_dt.utcnow.return_value = later
            mock_dt.fromisoformat = dt.datetime.fromisoformat
            old = main.app_state.news_price_snapshots
            main.app_state.news_price_snapshots = [snap]
            await main._update_news_price_snapshots({"AAPL": 103.0})
            main.app_state.news_price_snapshots = old
        mock_record.assert_called_once()
        call_kwargs = mock_record.call_args[1]
        self.assertEqual(call_kwargs["symbol"], "AAPL")
        self.assertAlmostEqual(call_kwargs["change_1h"], 3.0)

    async def test_record_catalyst_outcome_not_called_if_already_set(self):
        import main
        import datetime as dt
        from unittest.mock import AsyncMock
        snap = self._make_snap(price_at=100.0)
        snap["price_open"] = 102.0
        snap["change_open"] = 2.0
        snap["open_recorded_at"] = dt.datetime(2024, 1, 2, 9, 0, 0)
        snap["price_1h"] = 103.0
        snap["change_1h"] = 3.0
        later = dt.datetime(2024, 1, 2, 12, 0, 0)
        with patch("main.datetime") as mock_dt, \
             patch("main.update_price_snapshot", new_callable=AsyncMock), \
             patch("main.record_catalyst_outcome") as mock_record:
            mock_dt.utcnow.return_value = later
            mock_dt.fromisoformat = dt.datetime.fromisoformat
            old = main.app_state.news_price_snapshots
            main.app_state.news_price_snapshots = [snap]
            await main._update_news_price_snapshots({"AAPL": 107.0})
            main.app_state.news_price_snapshots = old
        mock_record.assert_not_called()


class TestAutoScanLoopStartup(unittest.IsolatedAsyncioTestCase):
    """auto_scan_loop startup scan must respect market hours."""

    async def _run_startup_only(self, market_open: bool, mins_to_open: float):
        """Run auto_scan_loop with is_running=False so only startup code executes."""
        import main
        mock_run_scan = AsyncMock(return_value=None)
        with patch("agents.scanner_agent.get_cached_scan", return_value=None), \
             patch("agents.scanner_agent.run_scan", mock_run_scan), \
             patch("agents.scanner_agent.is_scan_in_progress", return_value=False), \
             patch("main._market_is_open", return_value=market_open), \
             patch("main._minutes_until_open", return_value=mins_to_open), \
             patch("main.watchlist_manager"):
            prev = main.app_state.is_running
            main.app_state.is_running = False
            try:
                await main.auto_scan_loop()
            finally:
                main.app_state.is_running = prev
        return mock_run_scan

    async def test_startup_scan_skipped_when_market_closed_and_not_near_open(self):
        """No scan when market is closed and open is > 10 min away."""
        mock_run_scan = await self._run_startup_only(market_open=False, mins_to_open=60.0)
        mock_run_scan.assert_not_called()

    async def test_startup_scan_runs_when_market_is_open(self):
        """Scan fires at startup when market is open and cache is empty."""
        mock_run_scan = await self._run_startup_only(market_open=True, mins_to_open=0.0)
        mock_run_scan.assert_called_once()

    async def test_startup_scan_runs_during_pre_market_warmup(self):
        """Scan fires when market opens in <= 10 min (pre-market warmup window)."""
        mock_run_scan = await self._run_startup_only(market_open=False, mins_to_open=5.0)
        mock_run_scan.assert_called_once()

    async def test_startup_scan_skipped_when_cache_is_fresh(self):
        """No scan at startup when a fresh cached scan already exists."""
        import main
        mock_run_scan = AsyncMock(return_value=None)
        with patch("agents.scanner_agent.get_cached_scan", return_value={"results": []}), \
             patch("agents.scanner_agent.run_scan", mock_run_scan), \
             patch("agents.scanner_agent.is_scan_in_progress", return_value=False), \
             patch("main._market_is_open", return_value=True), \
             patch("main.watchlist_manager"):
            prev = main.app_state.is_running
            main.app_state.is_running = False
            try:
                await main.auto_scan_loop()
            finally:
                main.app_state.is_running = prev
        mock_run_scan.assert_not_called()


class TestRecordCatalysts(unittest.IsolatedAsyncioTestCase):
    """_record_catalysts deduplicates against both after_hours_catalysts and news_price_snapshots."""

    def _make_catalyst(self, headline, symbol="XOM", score=2):
        return {
            "headline":    headline,
            "summary":     "",
            "symbol":      symbol,
            "score":       score,
            "category":    "catalyst",
            "sectors":     [],
            "reason":      "",
            "detected_at": "2026-04-03T06:00:00Z",
        }

    async def test_new_catalyst_added_to_after_hours(self):
        """A brand-new catalyst is added to after_hours_catalysts."""
        import main
        main.app_state.after_hours_catalysts = []
        main.app_state.news_price_snapshots = []
        main.app_state.last_prices = {}

        with patch("main.save_price_snapshot", new_callable=AsyncMock):
            await main._record_catalysts([self._make_catalyst("Big earnings beat")])

        headlines = [c["headline"] for c in main.app_state.after_hours_catalysts]
        self.assertIn("Big earnings beat", headlines)

    async def test_duplicate_in_after_hours_not_re_added(self):
        """A catalyst already in after_hours_catalysts is not added again."""
        import main
        main.app_state.after_hours_catalysts = [self._make_catalyst("Old headline")]
        main.app_state.news_price_snapshots = []
        main.app_state.last_prices = {}

        with patch("main.save_price_snapshot", new_callable=AsyncMock):
            await main._record_catalysts([self._make_catalyst("Old headline")])

        count = sum(1 for c in main.app_state.after_hours_catalysts if c["headline"] == "Old headline")
        self.assertEqual(count, 1)

    async def test_catalyst_in_snapshots_not_re_added_after_restart(self):
        """If a headline is already in news_price_snapshots (DB-restored), don't re-add it.
        This is the post-restart duplicate bug: after_hours_catalysts is empty but the
        snapshot for this headline was already created in a prior session."""
        import main
        main.app_state.after_hours_catalysts = []   # reset on restart
        main.app_state.news_price_snapshots = [     # restored from DB
            {"headline": "XOM earnings beat", "symbol": "XOM", "price_at": 110.0,
             "change_1h": None, "change_open": None, "score": 2, "category": "catalyst",
             "detected_at": "2026-04-03T01:00:00Z", "during_session": False,
             "price_open": None, "price_1h": None, "open_recorded_at": None}
        ]
        main.app_state.last_prices = {"XOM": 111.0}

        with patch("main.save_price_snapshot", new_callable=AsyncMock) as mock_save:
            await main._record_catalysts([self._make_catalyst("XOM earnings beat")])

        # Must NOT create a new price snapshot
        mock_save.assert_not_called()
        # Must NOT add to after_hours_catalysts (or adds but does not create another snapshot)
        snap_count = sum(1 for s in main.app_state.news_price_snapshots
                         if s["headline"] == "XOM earnings beat")
        self.assertEqual(snap_count, 1)

    async def test_new_catalyst_snapshot_created_with_price(self):
        """When a new catalyst has a matching symbol price, a snapshot is saved to DB."""
        import main
        main.app_state.after_hours_catalysts = []
        main.app_state.news_price_snapshots = []
        main.app_state.last_prices = {"XOM": 115.0}

        with patch("main.save_price_snapshot", new_callable=AsyncMock, return_value=99) as mock_save:
            await main._record_catalysts([self._make_catalyst("FDA approval", symbol="XOM")])

        mock_save.assert_called_once()
        self.assertEqual(len(main.app_state.news_price_snapshots), 1)
        self.assertEqual(main.app_state.news_price_snapshots[0]["price_at"], 115.0)

    async def test_catalyst_without_symbol_price_no_snapshot(self):
        """A catalyst whose symbol has no current price does not create a snapshot."""
        import main
        main.app_state.after_hours_catalysts = []
        main.app_state.news_price_snapshots = []
        main.app_state.last_prices = {}   # XOM not in prices

        with patch("main.save_price_snapshot", new_callable=AsyncMock) as mock_save:
            await main._record_catalysts([self._make_catalyst("Some news", symbol="XOM")])

        mock_save.assert_not_called()
        self.assertEqual(len(main.app_state.news_price_snapshots), 0)

    async def test_after_hours_catalysts_trimmed_to_50(self):
        """after_hours_catalysts must not exceed 50 entries."""
        import main
        # Pre-load 49 existing catalysts
        main.app_state.after_hours_catalysts = [
            self._make_catalyst(f"headline {i}", symbol=None, score=1)
            for i in range(49)
        ]
        main.app_state.news_price_snapshots = []
        main.app_state.last_prices = {}

        new_cats = [self._make_catalyst(f"new headline {i}", symbol=None, score=3) for i in range(10)]
        with patch("main.save_price_snapshot", new_callable=AsyncMock):
            await main._record_catalysts(new_cats)

        self.assertLessEqual(len(main.app_state.after_hours_catalysts), 50)


class TestAddOllamaToPath(unittest.TestCase):
    """_add_ollama_to_path() injects the Ollama install dir into os.environ['PATH']."""

    def setUp(self):
        self._original_path = os.environ.get("PATH", "")

    def tearDown(self):
        os.environ["PATH"] = self._original_path

    def test_adds_ollama_dir_when_not_in_path(self):
        """Ollama install dir is appended to PATH when absent."""
        import main
        fake_local = "/fake/localappdata"
        ollama_dir = os.path.join(fake_local, "Programs", "Ollama")
        os.environ["PATH"] = "/some/other/dir"

        with patch.dict(os.environ, {"LOCALAPPDATA": fake_local}), \
             patch("os.path.isdir", return_value=True):
            main._add_ollama_to_path()
            self.assertIn(ollama_dir, os.environ["PATH"])

    def test_does_not_duplicate_when_already_present(self):
        """No duplicate entry added when Ollama dir is already in PATH."""
        import main
        fake_local = "/fake/localappdata"
        ollama_dir = os.path.join(fake_local, "Programs", "Ollama")
        os.environ["PATH"] = ollama_dir + os.pathsep + "/other"

        with patch.dict(os.environ, {"LOCALAPPDATA": fake_local}), \
             patch("os.path.isdir", return_value=True):
            main._add_ollama_to_path()

        # Count occurrences — must be exactly 1
        path_entries = os.environ["PATH"].split(os.pathsep)
        self.assertEqual(path_entries.count(ollama_dir), 1)

    def test_custom_ollama_path_from_config_added(self):
        """A custom OLLAMA_PATH in config is added to PATH."""
        import main
        custom = "/custom/ollama/bin"
        os.environ["PATH"] = "/some/dir"

        with patch("main.config") as mock_cfg, \
             patch("os.path.isdir", return_value=True):
            mock_cfg.OLLAMA_PATH = custom
            mock_cfg.OLLAMA_BASE_URL = "http://localhost:11434/v1"
            with patch.dict(os.environ, {"LOCALAPPDATA": ""}):
                main._add_ollama_to_path()
                self.assertIn(custom, os.environ["PATH"])

    def test_skips_nonexistent_directory(self):
        """Directories that don't exist on disk are not added to PATH."""
        import main
        fake_local = "/nonexistent/appdata"
        os.environ["PATH"] = "/some/dir"

        with patch.dict(os.environ, {"LOCALAPPDATA": fake_local}), \
             patch("os.path.isdir", return_value=False):
            main._add_ollama_to_path()

        ollama_dir = os.path.join(fake_local, "Programs", "Ollama")
        self.assertNotIn(ollama_dir, os.environ["PATH"])


class TestEnsureOllamaRunning(unittest.IsolatedAsyncioTestCase):
    """_ensure_ollama_running() starts Ollama when needed and pulls the model if missing."""

    async def test_does_nothing_when_already_running(self):
        """No subprocess calls when Ollama is already up."""
        import main
        with patch("agents.scanner_agent._ollama_is_available",
                   new_callable=AsyncMock, return_value=True) as mock_avail, \
             patch("subprocess.Popen") as mock_popen, \
             patch("subprocess.run") as mock_run:
            await main._ensure_ollama_running()

        mock_popen.assert_not_called()
        mock_run.assert_not_called()

    async def test_warns_and_returns_when_ollama_not_installed(self):
        """Logs a warning and returns cleanly if 'ollama' binary is not in PATH."""
        import main
        with patch("agents.scanner_agent._ollama_is_available",
                   new_callable=AsyncMock, return_value=False), \
             patch("subprocess.run", side_effect=FileNotFoundError("ollama not found")), \
             patch("subprocess.Popen") as mock_popen:
            await main._ensure_ollama_running()

        mock_popen.assert_not_called()

    async def test_starts_server_when_not_running_but_installed(self):
        """Popen called with 'ollama serve' when Ollama is installed but not running."""
        import main

        version_result = MagicMock(returncode=0)
        list_result    = MagicMock(returncode=0, stdout="llama3.1:8b  ...")

        with patch("agents.scanner_agent._ollama_is_available",
                   new_callable=AsyncMock, side_effect=[False, True]) as mock_avail, \
             patch("subprocess.run", return_value=version_result) as mock_run, \
             patch("subprocess.Popen") as mock_popen, \
             patch("asyncio.sleep", new_callable=AsyncMock):
            # Second call to subprocess.run is for 'ollama list'
            mock_run.side_effect = [version_result, list_result]
            with patch("main.config") as mock_cfg:
                mock_cfg.OLLAMA_MODEL = "llama3.1:8b"
                mock_cfg.OLLAMA_BASE_URL = "http://localhost:11434/v1"
                await main._ensure_ollama_running()

        mock_popen.assert_called_once()
        popen_args = mock_popen.call_args[0][0]
        self.assertEqual(popen_args[0], "ollama")
        self.assertEqual(popen_args[1], "serve")

    async def test_pulls_model_when_not_in_list(self):
        """Schedules _pull_ollama_model when model is absent from 'ollama list' output."""
        import main

        version_result = MagicMock(returncode=0)
        # Model is NOT in the list output
        list_result = MagicMock(returncode=0, stdout="some_other_model:latest  ...")

        with patch("agents.scanner_agent._ollama_is_available",
                   new_callable=AsyncMock, side_effect=[False, True]), \
             patch("subprocess.run") as mock_run, \
             patch("subprocess.Popen"), \
             patch("asyncio.sleep", new_callable=AsyncMock), \
             patch("asyncio.create_task") as mock_create_task:
            mock_run.side_effect = [version_result, list_result]
            with patch("main.config") as mock_cfg:
                mock_cfg.OLLAMA_MODEL = "llama3.1:8b"
                mock_cfg.OLLAMA_BASE_URL = "http://localhost:11434/v1"
                await main._ensure_ollama_running()

        mock_create_task.assert_called_once()


class TestFileHandlerDeduplication(unittest.TestCase):
    """_add_ollama_to_path and file handler must not create duplicates on re-import."""

    def test_rotating_file_handler_not_added_twice(self):
        """Adding the error log file handler twice must not result in duplicate handlers."""
        import logging
        import main
        from logging.handlers import RotatingFileHandler

        # Count how many RotatingFileHandlers point to _ERROR_LOG_PATH before
        target = os.path.abspath(main._ERROR_LOG_PATH)
        handlers_before = [
            h for h in logging.root.handlers
            if isinstance(h, RotatingFileHandler)
            and os.path.abspath(getattr(h, "baseFilename", "")) == target
        ]

        # Simulate re-running the module-level handler registration
        try:
            new_handler = RotatingFileHandler(
                main._ERROR_LOG_PATH, maxBytes=2 * 1024 * 1024, backupCount=5,
                encoding="utf-8",
            )
            already = any(
                isinstance(h, RotatingFileHandler)
                and os.path.abspath(getattr(h, "baseFilename", "")) == target
                for h in logging.root.handlers
            )
            if not already:
                logging.root.addHandler(new_handler)
            else:
                new_handler.close()
        except OSError:
            pass

        handlers_after = [
            h for h in logging.root.handlers
            if isinstance(h, RotatingFileHandler)
            and os.path.abspath(getattr(h, "baseFilename", "")) == target
        ]
        self.assertEqual(
            len(handlers_after), len(handlers_before),
            "Handler count changed — duplicate was added"
        )


class TestSentinelLoggingLevel(unittest.IsolatedAsyncioTestCase):
    """Sentinel log level: INFO for low-score detections, WARNING only when actionable."""

    def _make_catalyst(self, headline, score=1):
        return {
            "headline": headline, "summary": "", "source": "test",
            "date": "", "symbol": "AAPL", "score": score,
            "category": "catalyst", "sectors": [], "reason": "test",
            "detected_at": "2026-04-04T12:00:00Z",
        }

    async def test_info_logged_when_all_scores_below_trigger(self):
        """When max combined score is 0, sentinel logs INFO not WARNING."""
        import main

        catalysts = [self._make_catalyst(f"headline {i}", score=0) for i in range(5)]

        with patch.object(main.logger, "warning") as mock_warn, \
             patch.object(main.logger, "info") as mock_info:
            main._sentinel_log_catalysts(catalysts, max_standard=0, max_policy=0, trigger=2)

        mock_warn.assert_not_called()
        mock_info.assert_called_once()
        info_msg = mock_info.call_args[0][0]
        self.assertIn("5", info_msg)

    async def test_warning_logged_when_score_meets_trigger(self):
        """When combined score >= trigger, sentinel logs WARNING."""
        import main

        catalysts = [self._make_catalyst("Earnings beat", score=3)]

        with patch.object(main.logger, "warning") as mock_warn, \
             patch.object(main.logger, "info"):
            main._sentinel_log_catalysts(catalysts, max_standard=3, max_policy=0, trigger=2)

        mock_warn.assert_called_once()
        warn_msg = mock_warn.call_args[0][0]
        self.assertIn("Earnings beat", warn_msg)

    async def test_empty_catalysts_logs_nothing(self):
        """No log calls when catalyst list is empty."""
        import main

        with patch.object(main.logger, "warning") as mock_warn, \
             patch.object(main.logger, "info") as mock_info:
            main._sentinel_log_catalysts([], max_standard=0, max_policy=0, trigger=2)

        mock_warn.assert_not_called()
        mock_info.assert_not_called()


class TestErrorLogEndpoint(unittest.TestCase):
    """GET /api/errors returns structured log entries parsed from the error log file."""

    def _write_tmp_log(self, content: str) -> str:
        import tempfile
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".log", delete=False, encoding="utf-8"
        )
        f.write(content)
        f.close()
        return f.name

    def test_returns_empty_when_no_log_file(self):
        """Returns empty list when the log file does not exist."""
        from main import app
        import tempfile

        nonexistent = os.path.join(tempfile.gettempdir(), "nonexistent_trading_error.log")
        if os.path.exists(nonexistent):
            os.remove(nonexistent)

        with TestClient(app, raise_server_exceptions=True) as client:
            with patch("main._ERROR_LOG_PATH", nonexistent):
                response = client.get("/api/errors")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"entries": []})

    def test_returns_parsed_entries(self):
        """Log lines are parsed into timestamp/level/logger/message dicts."""
        from main import app

        log_content = (
            "2026-04-04 10:00:01 [ERROR] agents.scanner_agent: Connection failed\n"
            "2026-04-04 10:00:02 [WARNING] main: Market data timeout\n"
        )
        tmp = self._write_tmp_log(log_content)
        try:
            with TestClient(app, raise_server_exceptions=True) as client:
                with patch("main._ERROR_LOG_PATH", tmp):
                    response = client.get("/api/errors")
        finally:
            os.unlink(tmp)

        self.assertEqual(response.status_code, 200)
        entries = response.json()["entries"]
        self.assertEqual(len(entries), 2)
        # newest first
        self.assertEqual(entries[0]["timestamp"], "2026-04-04 10:00:02")
        self.assertEqual(entries[0]["level"], "WARNING")
        self.assertEqual(entries[0]["logger"], "main")
        self.assertEqual(entries[0]["message"], "Market data timeout")

    def test_returns_newest_first(self):
        """Entries are returned newest-first regardless of file order."""
        from main import app

        log_content = (
            "2026-04-04 09:00:00 [ERROR] main: Old error\n"
            "2026-04-04 11:00:00 [ERROR] main: New error\n"
        )
        tmp = self._write_tmp_log(log_content)
        try:
            with TestClient(app, raise_server_exceptions=True) as client:
                with patch("main._ERROR_LOG_PATH", tmp):
                    response = client.get("/api/errors")
        finally:
            os.unlink(tmp)

        entries = response.json()["entries"]
        self.assertEqual(entries[0]["message"], "New error")
        self.assertEqual(entries[1]["message"], "Old error")

    def test_limit_parameter_respected(self):
        """?limit=N caps the number of entries returned."""
        from main import app

        log_content = "\n".join(
            f"2026-04-04 10:00:0{i} [ERROR] main: Error {i}"
            for i in range(5)
        ) + "\n"
        tmp = self._write_tmp_log(log_content)
        try:
            with TestClient(app, raise_server_exceptions=True) as client:
                with patch("main._ERROR_LOG_PATH", tmp):
                    response = client.get("/api/errors?limit=2")
        finally:
            os.unlink(tmp)

        entries = response.json()["entries"]
        self.assertEqual(len(entries), 2)


class TestErrorAnalyzeEndpoint(unittest.TestCase):
    """GET /api/errors/analyze returns AI analysis of recent errors."""

    def _write_tmp_log(self, content: str) -> str:
        import tempfile
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".log", delete=False, encoding="utf-8"
        )
        f.write(content)
        f.close()
        return f.name

    def test_returns_no_errors_message_when_no_error_level_entries(self):
        """Returns 'No errors' when log contains only WARNING entries."""
        from main import app

        log_content = "2026-04-04 10:00:01 [WARNING] main: Minor warning\n"
        tmp = self._write_tmp_log(log_content)
        try:
            with TestClient(app, raise_server_exceptions=True) as client:
                with patch("main._ERROR_LOG_PATH", tmp):
                    response = client.get("/api/errors/analyze")
        finally:
            os.unlink(tmp)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["errors"], [])
        self.assertIn("No errors", data["analysis"])

    def test_calls_anthropic_and_returns_analysis(self):
        """Sends ERROR entries to Anthropic and returns the analysis text."""
        import anthropic
        from main import app

        log_content = (
            "2026-04-04 10:00:01 [ERROR] agents.scanner_agent: Connection refused\n"
        )
        tmp = self._write_tmp_log(log_content)

        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="Check your network connection.")]

        try:
            with TestClient(app, raise_server_exceptions=True) as client:
                with patch("main._ERROR_LOG_PATH", tmp):
                    with patch("main.config") as mock_cfg:
                        mock_cfg.ANTHROPIC_API_KEY = "fake-key"
                        with patch("anthropic.AsyncAnthropic") as mock_cls:
                            mock_instance = AsyncMock()
                            mock_instance.messages.create = AsyncMock(return_value=mock_msg)
                            mock_cls.return_value = mock_instance
                            response = client.get("/api/errors/analyze")
        finally:
            os.unlink(tmp)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("Check your network connection.", data["analysis"])
        self.assertEqual(len(data["errors"]), 1)


class TestOllamaModeEndpoint(unittest.TestCase):
    """POST /api/ollama-mode — enable/disable 24-hour Ollama-only mode."""

    def setUp(self):
        self.patcher_db = patch("main.init_db", new_callable=AsyncMock)
        self.patcher_agents = patch("main.init_agents", new_callable=AsyncMock)
        self.patcher_db.start()
        self.patcher_agents.start()

    def tearDown(self):
        self.patcher_db.stop()
        self.patcher_agents.stop()
        # Restore env after each test
        os.environ.pop("OLLAMA_ONLY_MODE", None)

    def test_enable_sets_env_flag(self):
        """POST enabled=true must set OLLAMA_ONLY_MODE=1 in os.environ."""
        from main import app
        with TestClient(app) as client:
            resp = client.post("/api/ollama-mode?enabled=true&hours=24")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(os.environ.get("OLLAMA_ONLY_MODE"), "1")

    def test_enable_response_has_expected_fields(self):
        """Response must include enabled, message, and expires_at."""
        from main import app
        with TestClient(app) as client:
            data = client.post("/api/ollama-mode?enabled=true&hours=24").json()
        self.assertTrue(data["enabled"])
        self.assertIn("expires_at", data)
        self.assertIn("message", data)

    def test_disable_clears_env_flag(self):
        """POST enabled=false must remove OLLAMA_ONLY_MODE from os.environ."""
        os.environ["OLLAMA_ONLY_MODE"] = "1"
        from main import app
        with TestClient(app) as client:
            resp = client.post("/api/ollama-mode?enabled=false")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("OLLAMA_ONLY_MODE", os.environ)

    def test_disable_response_shows_not_enabled(self):
        """Response on disable must show enabled=False and no expiry."""
        from main import app
        with TestClient(app) as client:
            data = client.post("/api/ollama-mode?enabled=false").json()
        self.assertFalse(data["enabled"])
        self.assertIsNone(data["expires_at"])

    def test_custom_hours(self):
        """hours parameter controls expiry window (default 24 if omitted)."""
        from main import app
        with TestClient(app) as client:
            data = client.post("/api/ollama-mode?enabled=true&hours=4").json()
        self.assertTrue(data["enabled"])
        self.assertIsNotNone(data["expires_at"])


if __name__ == "__main__":
    unittest.main()
