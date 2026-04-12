"""
Tests for backend/auth.py — session management and password verification.

Run with:
    cd backend && runtime\\python\\python.exe run_tests.py tests/test_auth.py -v
"""
import sys
import os
import time
import unittest

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import auth


def _reset_auth():
    """Reset all auth module state between tests."""
    auth._password_hash = ""
    auth._session_secret = ""
    auth._sessions.clear()
    auth._login_attempts.clear()


class TestInitAuth(unittest.TestCase):

    def setUp(self):
        _reset_auth()

    def test_disabled_when_password_empty(self):
        auth.init_auth("", "some_secret")
        self.assertFalse(auth.is_enabled())

    def test_disabled_when_secret_empty(self):
        auth.init_auth("mypassword", "")
        self.assertFalse(auth.is_enabled())

    def test_enabled_with_valid_inputs(self):
        auth.init_auth("mypassword", "mysecret")
        self.assertTrue(auth.is_enabled())

    def test_non_string_password_ignored(self):
        """MagicMock or other non-string inputs must not enable auth (test safety)."""
        from unittest.mock import MagicMock
        auth.init_auth(MagicMock(), "mysecret")
        self.assertFalse(auth.is_enabled())

    def test_non_string_secret_ignored(self):
        from unittest.mock import MagicMock
        auth.init_auth("mypassword", MagicMock())
        self.assertFalse(auth.is_enabled())


class TestPasswordVerification(unittest.TestCase):

    def setUp(self):
        _reset_auth()
        auth.init_auth("correct_password", "stable_secret")

    def test_correct_password_accepted(self):
        self.assertTrue(auth.verify_password("correct_password"))

    def test_wrong_password_rejected(self):
        self.assertFalse(auth.verify_password("wrong_password"))

    def test_empty_password_rejected(self):
        self.assertFalse(auth.verify_password(""))

    def test_timing_safe(self):
        """verify_password must not raise on arbitrary input."""
        for pw in ["", "a" * 1000, "\x00\xff", "correct_password "]:
            result = auth.verify_password(pw)
            self.assertIsInstance(result, bool)

    def test_verify_without_init_returns_false(self):
        _reset_auth()
        self.assertFalse(auth.verify_password("anything"))


class TestSessionManagement(unittest.TestCase):

    def setUp(self):
        _reset_auth()
        auth.init_auth("pw", "secret")

    def test_create_session_returns_string(self):
        token = auth.create_session()
        self.assertIsInstance(token, str)
        self.assertGreater(len(token), 20)

    def test_created_session_is_valid(self):
        token = auth.create_session()
        self.assertTrue(auth.validate_session(token))

    def test_unknown_token_is_invalid(self):
        self.assertFalse(auth.validate_session("not_a_real_token"))

    def test_empty_token_is_invalid(self):
        self.assertFalse(auth.validate_session(""))

    def test_revoked_session_is_invalid(self):
        token = auth.create_session()
        auth.revoke_session(token)
        self.assertFalse(auth.validate_session(token))

    def test_expired_session_is_invalid(self):
        token = auth.create_session()
        # Force expiry
        auth._sessions[token] = time.time() - 1
        self.assertFalse(auth.validate_session(token))

    def test_expired_session_is_pruned(self):
        token = auth.create_session()
        auth._sessions[token] = time.time() - 1
        auth.validate_session(token)
        self.assertNotIn(token, auth._sessions)

    def test_each_session_has_unique_token(self):
        tokens = {auth.create_session() for _ in range(100)}
        self.assertEqual(len(tokens), 100)


class TestLoginRateLimit(unittest.TestCase):

    def setUp(self):
        _reset_auth()

    def test_allows_attempts_under_limit(self):
        for _ in range(auth._LOGIN_MAX):
            self.assertTrue(auth.check_login_rate_limit("1.2.3.4"))

    def test_blocks_after_limit_exceeded(self):
        for _ in range(auth._LOGIN_MAX):
            auth.check_login_rate_limit("5.6.7.8")
        self.assertFalse(auth.check_login_rate_limit("5.6.7.8"))

    def test_different_ips_are_independent(self):
        for _ in range(auth._LOGIN_MAX):
            auth.check_login_rate_limit("10.0.0.1")
        # Different IP should still be allowed
        self.assertTrue(auth.check_login_rate_limit("10.0.0.2"))

    def test_expired_attempts_are_pruned(self):
        """Attempts outside the window must not count."""
        old_time = time.time() - auth._LOGIN_WINDOW - 1
        auth._login_attempts["9.9.9.9"] = [old_time] * auth._LOGIN_MAX
        # All old — window has passed, new attempt should be allowed
        self.assertTrue(auth.check_login_rate_limit("9.9.9.9"))


class TestAuthEndpointsIntegration(unittest.TestCase):
    """Integration tests for /api/login, /api/logout, /api/auth/check via TestClient."""

    def setUp(self):
        _reset_auth()
        # Reset rate limit store for each test
        auth._login_attempts.clear()

    def _make_client(self):
        """Return a TestClient with auth fully disabled (password_hash = "")."""
        import sys
        from unittest.mock import patch, AsyncMock
        from fastapi.testclient import TestClient

        patchers = [
            patch("main.init_db",                   new_callable=AsyncMock),
            patch("main.init_agents",               new_callable=AsyncMock),
            patch("main.cleanup_token_log",         new_callable=AsyncMock),
            patch("main.prune_performance_table",   new_callable=AsyncMock),
            patch("main.prune_news_price_snapshots",new_callable=AsyncMock),
            patch("main._ensure_ollama_running",    new_callable=AsyncMock),
            patch("main.ws_broadcast_loop",         new_callable=AsyncMock),
            patch("main.trading_loop",              new_callable=AsyncMock),
            patch("main.auto_scan_loop",            new_callable=AsyncMock),
            patch("main.news_sentinel_loop",        new_callable=AsyncMock),
            patch("main.asyncio.create_task"),
            # Keep auth disabled so lifespan doesn't enable it with real .env password
            patch("auth._password_hash", ""),
        ]
        for p in patchers:
            p.start()
        self._patchers = patchers
        from main import app
        return TestClient(app, raise_server_exceptions=False)

    def tearDown(self):
        for p in self._patchers:
            try:
                p.stop()
            except RuntimeError:
                pass

    def _enable_auth_in_test(self):
        """Set a known password for tests that exercise the login flow."""
        auth.init_auth("testpass", "testsecret")

    def test_auth_check_returns_ok_when_disabled(self):
        client = self._make_client()
        with client:
            resp = client.get("/api/auth/check")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["authenticated"])
        self.assertFalse(resp.json()["auth_enabled"])

    def test_login_succeeds_when_auth_disabled(self):
        client = self._make_client()
        with client:
            resp = client.post("/api/login", json={"password": "anything"})
        self.assertEqual(resp.status_code, 200)

    def test_login_rejects_wrong_password_when_enabled(self):
        client = self._make_client()
        with client:
            self._enable_auth_in_test()
            resp = client.post("/api/login", json={"password": "wrong"})
        self.assertEqual(resp.status_code, 401)

    def test_login_sets_cookie_on_success(self):
        client = self._make_client()
        with client:
            self._enable_auth_in_test()
            resp = client.post("/api/login", json={"password": "testpass"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn(auth.SESSION_COOKIE, resp.cookies)

    def test_logout_clears_cookie(self):
        client = self._make_client()
        with client:
            self._enable_auth_in_test()
            login_resp = client.post("/api/login", json={"password": "testpass"})
            self.assertEqual(login_resp.status_code, 200)
            logout_resp = client.post("/api/logout")
        self.assertEqual(logout_resp.status_code, 200)

    def test_login_rate_limit_enforced(self):
        client = self._make_client()
        with client:
            self._enable_auth_in_test()
            # Exhaust the rate limit
            for _ in range(auth._LOGIN_MAX):
                client.post("/api/login", json={"password": "wrong"})
            resp = client.post("/api/login", json={"password": "wrong"})
        self.assertEqual(resp.status_code, 429)


if __name__ == "__main__":
    unittest.main()
