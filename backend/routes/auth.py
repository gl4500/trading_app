"""Authentication endpoints: /api/login, /api/logout, /api/auth/check."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import auth as auth

auth_router = APIRouter()


@auth_router.post("/api/login")
async def login(request: Request):
    """Verify password and issue a session cookie."""
    import main  # for _HTTPS_ENABLED (may be patched in tests)
    if not auth.is_enabled():
        # Auth is disabled — auto-login
        return JSONResponse({"detail": "Auth disabled — open access"})

    ip = request.client.host if request.client else "unknown"
    if not auth.check_login_rate_limit(ip):
        return JSONResponse({"detail": "Too many login attempts. Try again in 5 minutes."}, status_code=429)

    try:
        body = await request.json()
        password = body.get("password", "")
    except Exception:
        return JSONResponse({"detail": "Invalid request body"}, status_code=400)

    if not auth.verify_password(password):
        return JSONResponse({"detail": "Invalid password"}, status_code=401)

    token = auth.create_session()
    response = JSONResponse({"detail": "Login successful"})
    response.set_cookie(
        key=auth.SESSION_COOKIE,
        value=token,
        httponly=True,
        secure=main._HTTPS_ENABLED,
        samesite="lax",
        max_age=auth.SESSION_TTL,
        path="/",
    )
    return response


@auth_router.post("/api/logout")
async def logout(request: Request):
    """Revoke the current session and clear the cookie."""
    token = request.cookies.get(auth.SESSION_COOKIE)
    if token:
        auth.revoke_session(token)
    response = JSONResponse({"detail": "Logged out"})
    response.delete_cookie(key=auth.SESSION_COOKIE, path="/")
    return response


@auth_router.get("/api/auth/check")
async def auth_check(request: Request):
    """Returns auth status. Used by the frontend to decide whether to show the
    login page. Always accessible (no session required).
    """
    if not auth.is_enabled():
        return {"authenticated": True, "auth_enabled": False}
    token = request.cookies.get(auth.SESSION_COOKIE)
    if token and auth.validate_session(token):
        return {"authenticated": True, "auth_enabled": True}
    return JSONResponse({"authenticated": False, "auth_enabled": True}, status_code=401)
