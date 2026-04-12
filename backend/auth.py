"""
Session-based authentication for the trading app.

Set APP_PASSWORD and SESSION_SECRET in .env to enable authentication.
Leave APP_PASSWORD empty to disable auth (open access — local-only use).

Security properties:
  - Passwords hashed with PBKDF2-HMAC-SHA256 (200,000 iterations)
  - Session tokens are 32-byte cryptographically random URL-safe strings
  - Cookies: httpOnly (JS cannot read), Secure (HTTPS only), SameSite=lax
  - Login rate-limited: 5 attempts per 5 minutes per IP
  - Session TTL: 24 hours, verified on every request
"""
import hashlib
import hmac
import secrets
import time
from typing import Dict, List

SESSION_COOKIE = "trading_session"
SESSION_TTL = 24 * 3600  # 24 hours

_password_hash: str = ""
_session_secret: str = ""
_sessions: Dict[str, float] = {}   # token -> expiry timestamp

# Login rate limiting
_login_attempts: Dict[str, List[float]] = {}
_LOGIN_WINDOW = 300  # 5 minutes
_LOGIN_MAX = 5       # max attempts per window per IP


def init_auth(password: str, session_secret: str) -> None:
    """
    Called at startup.  Enables auth only if both args are non-empty strings.
    Non-string inputs (e.g. MagicMock in tests) are silently ignored — auth stays off.
    """
    global _password_hash, _session_secret
    if not isinstance(password, str) or not isinstance(session_secret, str):
        return
    if not password or not session_secret:
        return
    _session_secret = session_secret
    _password_hash = _pbkdf2(password, session_secret)


def is_enabled() -> bool:
    """Return True when a password hash has been loaded (auth is active)."""
    return bool(_password_hash)


def _pbkdf2(password: str, salt: str) -> str:
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        200_000,
    )
    return dk.hex()


def check_login_rate_limit(ip: str) -> bool:
    """Return True if this IP is allowed another login attempt."""
    now = time.time()
    cutoff = now - _LOGIN_WINDOW
    attempts = _login_attempts.setdefault(ip, [])
    attempts[:] = [t for t in attempts if t > cutoff]
    if len(attempts) >= _LOGIN_MAX:
        return False
    attempts.append(now)
    return True


def verify_password(password: str) -> bool:
    """Constant-time comparison to prevent timing attacks."""
    if not _password_hash or not _session_secret:
        return False
    candidate = _pbkdf2(password, _session_secret)
    return hmac.compare_digest(candidate, _password_hash)


def create_session() -> str:
    """Generate a new session token, store its expiry, and return the token."""
    token = secrets.token_urlsafe(32)
    _sessions[token] = time.time() + SESSION_TTL
    return token


def validate_session(token: str) -> bool:
    """Return True if the token exists and has not expired."""
    expiry = _sessions.get(token)
    if expiry is None:
        return False
    if time.time() > expiry:
        _sessions.pop(token, None)
        return False
    return True


def revoke_session(token: str) -> None:
    """Invalidate a session token immediately."""
    _sessions.pop(token, None)
