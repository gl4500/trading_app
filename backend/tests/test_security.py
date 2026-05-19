"""
Security tests for the trading app backend.

Covers the threat surface relevant to a locally-hosted trading app:
  1. Security headers — middleware must set all required headers on every response
  2. CORS enforcement — disallowed origins must be rejected; allowed origins pass
  3. Error sanitization — no stack traces, internal paths, or key names in responses
  4. SQL injection hardening — f-string SQL helpers must reject attacker field names
  5. Secrets not exposed — /api/status must not echo API keys
  6. Rate limiting — /api/scanner/run enforces 429 after limit exceeded
  7. Secret pattern scan — source files must not contain real API key strings

Run with:
    cd backend && runtime\\python\\python.exe run_tests.py tests/test_security.py -v
"""
import sys
import os
import re
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi.testclient import TestClient


# ── Shared helpers ────────────────────────────────────────────────────────────

def _mock_app_state(mock_state):
    mock_state.is_running       = False
    mock_state.market_status    = "closed"
    mock_state.cycle_count      = 0
    mock_state.start_time       = None
    mock_state.agents           = {}
    mock_state.ws_connections   = set()
    mock_state.after_hours_catalysts  = []
    mock_state.last_sentinel_poll     = None
    mock_state.news_price_snapshots   = []
    mock_state.last_prices            = {}


def _mock_config(mock_cfg):
    mock_cfg.WATCHLIST              = ["AAPL", "MSFT"]
    mock_cfg.STARTING_CAPITAL       = 100_000
    mock_cfg.TRADE_INTERVAL_SECONDS = 60


def _client_get(path, headers=None):
    """GET path through a fully mocked TestClient. Returns response."""
    from main import app
    with patch("main.init_db",     new_callable=AsyncMock), \
         patch("main.init_agents", new_callable=AsyncMock), \
         patch("main.app_state") as ms, \
         patch("main.config") as mc:
        _mock_app_state(ms)
        _mock_config(mc)
        with TestClient(app, raise_server_exceptions=False) as client:
            return client.get(path, headers=headers or {})


def _client_post(path, **kwargs):
    from main import app
    with patch("main.init_db",     new_callable=AsyncMock), \
         patch("main.init_agents", new_callable=AsyncMock), \
         patch("main.app_state") as ms, \
         patch("main.config") as mc:
        _mock_app_state(ms)
        _mock_config(mc)
        with TestClient(app, raise_server_exceptions=False) as client:
            return client.post(path, **kwargs)


def _client_options(path, headers=None):
    from main import app
    with patch("main.init_db",     new_callable=AsyncMock), \
         patch("main.init_agents", new_callable=AsyncMock), \
         patch("main.app_state") as ms, \
         patch("main.config") as mc:
        _mock_app_state(ms)
        _mock_config(mc)
        with TestClient(app, raise_server_exceptions=False) as client:
            return client.options(path, headers=headers or {})


# ─────────────────────────────────────────────────────────────────────────────
# 1. Security Headers
# ─────────────────────────────────────────────────────────────────────────────

def _start_lifespan_patches():
    """Patch all async functions called during the FastAPI lifespan startup."""
    patchers = [
        patch("main.init_db",                   new_callable=AsyncMock),
        patch("main.init_agents",               new_callable=AsyncMock),
        patch("main.cleanup_token_log",         new_callable=AsyncMock),
        patch("main.prune_news_price_snapshots",new_callable=AsyncMock),
        patch("main._ensure_ollama_running",    new_callable=AsyncMock),
        patch("main.ws_broadcast_loop",         new_callable=AsyncMock),
        patch("main.trading_loop",              new_callable=AsyncMock),
        patch("main.auto_scan_loop",            new_callable=AsyncMock),
        patch("main.news_sentinel_loop",        new_callable=AsyncMock),
        # Keep auth disabled so tests don't require session cookies,
        # even if APP_PASSWORD is set in the local .env file. The init_auth
        # patch is the load-bearing one — lifespan startup calls it, and
        # without this no-op it would re-populate _password_hash from the
        # real .env config and override the _password_hash patch below.
        patch("auth.init_auth"),
        patch("auth._password_hash", ""),
    ]
    for p in patchers:
        p.start()
    return patchers


def _stop_patchers(patchers):
    for p in patchers:
        try:
            p.stop()
        except RuntimeError:
            pass


class TestSecurityHeaders(unittest.TestCase):
    """Every non-Swagger response must carry the required security headers."""

    def setUp(self):
        self._patchers = _start_lifespan_patches()

    def tearDown(self):
        _stop_patchers(self._patchers)

    def _headers(self):
        from main import app
        with patch("main.app_state") as ms, patch("main.config") as mc:
            _mock_app_state(ms)
            _mock_config(mc)
            with TestClient(app, raise_server_exceptions=False) as c:
                return c.get("/api/status").headers

    def test_x_content_type_options(self):
        self.assertEqual(self._headers().get("x-content-type-options"), "nosniff")

    def test_x_frame_options(self):
        self.assertEqual(self._headers().get("x-frame-options"), "DENY")

    def test_x_xss_protection(self):
        self.assertEqual(self._headers().get("x-xss-protection"), "1; mode=block")

    def test_referrer_policy(self):
        self.assertEqual(
            self._headers().get("referrer-policy"),
            "strict-origin-when-cross-origin",
        )

    def test_csp_present_on_api_routes(self):
        csp = self._headers().get("content-security-policy", "")
        self.assertIn("default-src 'self'", csp)

    def test_csp_absent_on_swagger_docs(self):
        """Swagger UI exemption — CSP must not block cdn.jsdelivr.net assets."""
        from main import app
        with patch("main.app_state") as ms, patch("main.config") as mc:
            _mock_app_state(ms)
            _mock_config(mc)
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get("/docs")
        self.assertNotIn("content-security-policy", resp.headers)

    def test_csp_absent_on_openapi_json(self):
        from main import app
        with patch("main.app_state") as ms, patch("main.config") as mc:
            _mock_app_state(ms)
            _mock_config(mc)
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get("/openapi.json")
        self.assertNotIn("content-security-policy", resp.headers)

    def test_headers_present_on_404(self):
        """Security headers must appear even on error responses."""
        from main import app
        with patch("main.app_state") as ms, patch("main.config") as mc:
            _mock_app_state(ms)
            _mock_config(mc)
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get("/api/nonexistent-route-xyz")
        self.assertEqual(resp.headers.get("x-frame-options"), "DENY")
        self.assertEqual(resp.headers.get("x-content-type-options"), "nosniff")


# ─────────────────────────────────────────────────────────────────────────────
# 2. CORS Enforcement
# ─────────────────────────────────────────────────────────────────────────────

class TestCORSEnforcement(unittest.TestCase):
    """CORS must allow only the declared localhost origins."""

    def setUp(self):
        self._patchers = _start_lifespan_patches()

    def tearDown(self):
        _stop_patchers(self._patchers)

    def _get_with_origin(self, origin):
        from main import app
        with patch("main.app_state") as ms, patch("main.config") as mc:
            _mock_app_state(ms)
            _mock_config(mc)
            with TestClient(app, raise_server_exceptions=False) as c:
                return c.get("/api/status", headers={"Origin": origin})

    def _options_with_origin(self, origin, method="GET"):
        from main import app
        with patch("main.app_state") as ms, patch("main.config") as mc:
            _mock_app_state(ms)
            _mock_config(mc)
            with TestClient(app, raise_server_exceptions=False) as c:
                return c.options("/api/status", headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": method,
                })

    def test_allowed_origin_http_localhost(self):
        resp = self._get_with_origin("http://localhost:5173")
        self.assertEqual(
            resp.headers.get("access-control-allow-origin"),
            "http://localhost:5173",
        )

    def test_allowed_origin_https_localhost(self):
        resp = self._get_with_origin("https://localhost:5173")
        self.assertEqual(
            resp.headers.get("access-control-allow-origin"),
            "https://localhost:5173",
        )

    def test_disallowed_origin_not_echoed(self):
        """An attacker origin must not receive the CORS allow header."""
        resp = self._get_with_origin("https://evil-attacker.com")
        allow = resp.headers.get("access-control-allow-origin", "")
        self.assertNotEqual(allow, "https://evil-attacker.com")
        self.assertNotEqual(allow, "*")

    def test_credentials_not_allowed(self):
        """allow_credentials=False — cookies must not be sent cross-origin."""
        resp = self._get_with_origin("http://localhost:5173")
        self.assertNotEqual(
            resp.headers.get("access-control-allow-credentials", "").lower(), "true"
        )

    def test_disallowed_method_rejected(self):
        """PUT/DELETE are not in allow_methods and must be rejected pre-flight."""
        resp = self._options_with_origin("http://localhost:5173", method="DELETE")
        allowed = resp.headers.get("access-control-allow-methods", "")
        self.assertNotIn("DELETE", allowed)
        self.assertNotIn("PUT", allowed)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Error Sanitization
# ─────────────────────────────────────────────────────────────────────────────

class TestErrorSanitization(unittest.TestCase):
    """Error responses must not leak stack traces, file paths, or key names."""

    def setUp(self):
        self._patchers = _start_lifespan_patches()

    def tearDown(self):
        _stop_patchers(self._patchers)

    def _body(self, path, method="get", **kwargs):
        from main import app
        with patch("main.app_state") as ms, patch("main.config") as mc:
            _mock_app_state(ms)
            _mock_config(mc)
            with TestClient(app, raise_server_exceptions=False) as c:
                return getattr(c, method)(path, **kwargs).text

    def test_404_no_traceback(self):
        body = self._body("/api/does-not-exist")
        self.assertNotIn("Traceback", body)
        self.assertNotIn('File "', body)

    def test_404_no_internal_path(self):
        body = self._body("/api/does-not-exist")
        self.assertNotIn("C:\\Users", body)
        self.assertNotIn("/home/", body)
        self.assertNotIn("site-packages", body)

    def test_agent_not_found_generic_message(self):
        """Agent 404 must not reflect the requested agent name back."""
        body = self._body("/api/performance/EvilInjectedAgentName")
        self.assertNotIn("EvilInjectedAgentName", body)

    def test_status_no_api_key_patterns(self):
        """GET /api/status must not expose any real API key values."""
        key_patterns = [
            r"sk-ant-[A-Za-z0-9]{10,}",
            r"sk-[A-Za-z0-9]{20,}",
            r"AIzaSy[A-Za-z0-9_\-]{33}",
            r"AKIA[A-Z0-9]{16}",
            r"ALPACA_SECRET\s*=\s*\S+",
        ]
        body = self._body("/api/status")
        for pattern in key_patterns:
            self.assertIsNone(
                re.search(pattern, body, re.IGNORECASE),
                f"Potential secret pattern '{pattern}' found in /api/status response",
            )

    def test_malformed_json_post_no_traceback(self):
        body = self._body(
            "/api/start",
            method="post",
            content=b"{bad json{{",
            headers={"Content-Type": "application/json"},
        )
        self.assertNotIn("Traceback", body)
        self.assertNotIn("JSONDecodeError", body)


# ─────────────────────────────────────────────────────────────────────────────
# 4. SQL Injection Hardening
# ─────────────────────────────────────────────────────────────────────────────

class TestSQLHardening(unittest.TestCase):
    """
    The two f-string SQL helpers in database.py build WHERE/SET clauses
    dynamically. Verify the caller-side guards hold and cannot be bypassed
    with attacker-controlled field names.
    """

    def test_update_price_snapshot_rejects_unknown_fields(self):
        """
        update_price_snapshot() whitelists field names.
        Attacker-controlled keys must be silently dropped — no DB call fires.
        """
        import asyncio
        import database

        injected_fields = {
            "id=1 OR 1=1--":    999,
            "price_open; DROP TABLE news_price_snapshots--": 0.0,
            "__class__":        "evil",
            "valid_but_unknown_column": 1.0,
        }

        call_count = 0

        async def _run():
            nonlocal call_count
            import aiosqlite

            class _MockConn:
                async def __aenter__(self): return self
                async def __aexit__(self, *a): pass
                async def execute(self, *a, **kw):
                    nonlocal call_count
                    call_count += 1
                    return MagicMock()
                async def commit(self): pass

            with patch("aiosqlite.connect", return_value=_MockConn()):
                await database.update_price_snapshot(snap_id=1, **injected_fields)

        asyncio.run(_run())
        self.assertEqual(
            call_count, 0,
            "update_price_snapshot executed a query with unwhitelisted field names",
        )

    def test_update_price_snapshot_allows_valid_fields(self):
        """Whitelisted fields must still pass through correctly."""
        import asyncio
        import database

        executed_sql = []

        async def _run():
            import aiosqlite

            class _MockConn:
                async def __aenter__(self): return self
                async def __aexit__(self, *a): pass
                async def execute(self, sql, params=None):
                    executed_sql.append((sql, params))
                    return MagicMock()
                async def commit(self): pass

            with patch("aiosqlite.connect", return_value=_MockConn()):
                await database.update_price_snapshot(snap_id=42, price_open=123.45)

        asyncio.run(_run())
        self.assertEqual(len(executed_sql), 1)
        sql, params = executed_sql[0]
        self.assertIn("price_open = ?", sql)
        self.assertIn("WHERE id = ?", sql)
        self.assertEqual(params[-1], 42)
        self.assertNotIn("123.45", sql)   # value must be parameterised, not interpolated

    def test_token_log_no_raw_sql_parameter(self):
        """
        get_token_log_entries() must not expose a parameter that accepts
        raw SQL fragments (where_clause, sql, query, filter).
        """
        import inspect
        import database
        sig = inspect.signature(database.get_token_log)
        forbidden = {"where", "where_clause", "sql", "query", "filter"}
        exposed = forbidden & set(sig.parameters.keys())
        self.assertFalse(
            exposed,
            f"get_token_log_entries exposes raw SQL parameter(s): {exposed}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# 5. Rate Limiting
# ─────────────────────────────────────────────────────────────────────────────

class TestRateLimiting(unittest.TestCase):
    """Scanner endpoint must enforce 429 after the allowed request window."""

    def setUp(self):
        self._patchers = _start_lifespan_patches()

    def tearDown(self):
        _stop_patchers(self._patchers)

    def test_scanner_run_returns_429_when_rate_exceeded(self):
        from main import app, _rate_limit_store
        _rate_limit_store.clear()
        with patch("main.app_state") as ms, patch("main.config") as mc:
            _mock_app_state(ms)
            _mock_config(mc)
            with TestClient(app, raise_server_exceptions=False) as c:
                with patch("main._check_rate_limit", return_value=False):
                    resp = c.post("/api/scanner/run")
        self.assertEqual(resp.status_code, 429)

    def test_scanner_run_allowed_under_limit(self):
        from main import app, _rate_limit_store
        _rate_limit_store.clear()
        with patch("main.app_state") as ms, patch("main.config") as mc:
            _mock_app_state(ms)
            ms.is_running = True
            _mock_config(mc)
            with TestClient(app, raise_server_exceptions=False) as c:
                with patch("main._check_rate_limit", return_value=True), \
                     patch("agents.scanner_agent.run_scan",
                           new_callable=AsyncMock,
                           return_value={"status": "ok", "recommendations": [], "candidates": []}):
                    resp = c.post("/api/scanner/run")
        self.assertNotEqual(resp.status_code, 429)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Secret Pattern Scan (static)
# ─────────────────────────────────────────────────────────────────────────────

class TestSecretPatterns(unittest.TestCase):
    """
    Scan every .py / .ts source file for real API key patterns.
    Catches accidental credential commits before git push.
    """

    _SECRET_PATTERNS = [
        (r"sk-ant-[A-Za-z0-9\-_]{20,}", "Anthropic API key"),
        (r"sk-[A-Za-z0-9]{20,}",         "OpenAI API key"),
        (r"AIzaSy[A-Za-z0-9_\-]{33}",    "Google AI Studio key"),
        (r"AKIA[A-Z0-9]{16}",            "AWS access key"),
    ]

    _PROJECT_ROOT = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )

    _SKIP_DIRS = {
        "node_modules", "site-packages", "runtime", "__pycache__",
        ".git", "dist", "build", "packages",
    }

    def _iter_source_files(self):
        for root, dirs, files in os.walk(self._PROJECT_ROOT):
            dirs[:] = [d for d in dirs if d not in self._SKIP_DIRS]
            for fname in files:
                if fname.endswith((".py", ".ts", ".tsx", ".js")):
                    yield os.path.join(root, fname)

    def test_no_hardcoded_secrets_in_source(self):
        violations = []
        for fpath in self._iter_source_files():
            try:
                with open(fpath, encoding="utf-8", errors="ignore") as fh:
                    for lineno, line in enumerate(fh, 1):
                        for pattern, label in self._SECRET_PATTERNS:
                            for match in re.finditer(pattern, line):
                                rel = os.path.relpath(fpath, self._PROJECT_ROOT)
                                violations.append(
                                    f"{rel}:{lineno} — {label}: {match.group()[:12]}..."
                                )
            except OSError:
                pass
        self.assertFalse(
            violations,
            "Hardcoded secrets detected — remove before committing:\n"
            + "\n".join(violations),
        )

    def test_env_file_covered_by_gitignore(self):
        """.env must be listed in .gitignore."""
        gitignore = os.path.join(self._PROJECT_ROOT, ".gitignore")
        if not os.path.exists(gitignore):
            self.skipTest(".gitignore not found at project root")
        # encoding='utf-8' so Windows (cp1252) can read a .gitignore that
        # contains UTF-8 byte sequences (e.g. non-ASCII path comments).
        with open(gitignore, encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn(
            ".env", content,
            ".env is not listed in .gitignore — it could be committed accidentally",
        )


if __name__ == "__main__":
    unittest.main()
