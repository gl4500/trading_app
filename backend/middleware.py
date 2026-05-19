"""HTTP middleware + rate limiter.

Extracted from main.py for issue #67. Contains:
  - `add_security_headers` middleware (X-Content-Type-Options, X-Frame-Options,
    X-XSS-Protection, Referrer-Policy, Content-Security-Policy)
  - `auth_middleware` (blocks unauthenticated requests when APP_PASSWORD set)
  - `_check_rate_limit` helper and the `_rate_limit_store` dict
  - `install_middleware(app)` — wires the two middlewares to the FastAPI app

main.py re-exports `_check_rate_limit`, `_rate_limit_store`, `_RATE_LIMIT_MAX`,
`_RATE_LIMIT_WINDOW`, `add_security_headers`, and `auth_middleware` so tests
that import / patch them via `main.X` continue to work.
"""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Dict, List

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import auth as auth


# ─── Rate Limiter ────────────────────────────────────────────────────────────

_rate_limit_store: Dict[str, List[float]] = defaultdict(list)
_RATE_LIMIT_WINDOW = 60   # seconds
_RATE_LIMIT_MAX     = 10  # max requests per window per IP


def _check_rate_limit(ip: str) -> bool:
    """Return True if request is allowed, False if rate limit exceeded."""
    now = time.time()
    window_start = now - _RATE_LIMIT_WINDOW
    calls = _rate_limit_store[ip]
    calls[:] = [t for t in calls if t > window_start]
    if len(calls) >= _RATE_LIMIT_MAX:
        return False
    calls.append(now)
    return True


# ─── Middleware ──────────────────────────────────────────────────────────────

# Paths that are always accessible without a session cookie.
_AUTH_EXEMPT = frozenset({
    "/api/login",
    "/api/logout",
    "/api/auth/check",
    "/docs",
    "/openapi.json",
    "/redoc",
})


async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Skip CSP for Swagger UI — it loads JS/CSS from cdn.jsdelivr.net
    if request.url.path not in ("/docs", "/openapi.json", "/redoc"):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "connect-src 'self' ws://localhost:8000 wss://localhost:8000 "
            "ws://localhost:5173 wss://localhost:5173"
        )
    return response


async def auth_middleware(request: Request, call_next):
    """Block unauthenticated requests when APP_PASSWORD is set."""
    # Auth disabled (no password configured) — pass everything through
    if not auth.is_enabled():
        return await call_next(request)

    # WebSocket upgrade requests are handled inside websocket_endpoint
    if request.url.path.startswith("/ws"):
        return await call_next(request)

    # Public paths never require a cookie
    if request.url.path in _AUTH_EXEMPT:
        return await call_next(request)

    token = request.cookies.get(auth.SESSION_COOKIE)
    if not token or not auth.validate_session(token):
        return JSONResponse({"detail": "Authentication required"}, status_code=401)

    return await call_next(request)


def install_middleware(app: FastAPI) -> None:
    """Wire CORS + auth + security-headers middlewares onto the given app.

    Target request flow (outermost → innermost):
        User → add_security_headers → CORSMiddleware → auth_middleware → route

    Why this order:
      - add_security_headers OUTERMOST so X-Content-Type-Options / X-Frame-Options
        / CSP / etc. land on every response, including auth-rejected 401s.
      - CORSMiddleware OUTSIDE auth_middleware so the Access-Control-Allow-Origin
        header is added to auth-rejected 401 responses too. Without this,
        browsers see a "CORS error" instead of the clean 401 and the frontend's
        401-→-login-redirect interceptor never gets a chance to run.
      - auth_middleware INNERMOST so it short-circuits unauthenticated requests
        before they hit any route handler.

    FastAPI / Starlette builds the stack by reversing the insert order, so
    we install in the order auth → CORS → security-headers.
    """
    app.middleware("http")(auth_middleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173", "https://localhost:5173",
            "http://127.0.0.1:5173", "https://127.0.0.1:5173",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Accept"],
    )
    app.middleware("http")(add_security_headers)
