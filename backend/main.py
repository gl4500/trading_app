"""
FastAPI backend for the AI Trading Competition.
Manages agents, trading loop, WebSocket broadcasts, and REST API.
"""
import sys
import os
# Self-bootstrap: ensure site-packages is on sys.path regardless of how the
# script is launched (launcher.py, start_backend.ps1, or direct invocation).
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_site_packages = os.path.join(_root, "site-packages")
if os.path.isdir(_site_packages) and _site_packages not in sys.path:
    sys.path.insert(0, _site_packages)

import asyncio
import json
import logging
import re
import subprocess
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, List, Optional, Set

import httpx
import uvicorn
try:
    import psutil
except ImportError:
    psutil = None  # type: ignore[assignment]
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import config
import auth as auth
from data.agent_performance_tracker import agent_performance_tracker
from data.signal_history import signal_history
from database import (
    init_db,
    upsert_agent,
    save_trade,
    save_performance,
    upsert_portfolio_position,
    get_agent_trades,
    get_performance_history,
    get_latest_cash,
    get_portfolio_positions,
    restore_value_history,
    reset_database,
    get_token_log,
    cleanup_token_log,
    get_daily_token_total,
    get_agent_calls_this_hour,
    save_price_snapshot,
    update_price_snapshot,
    get_price_snapshots,
    prune_news_price_snapshots,
    dump_trades_to_parquet,
)
from trading.portfolio import Position, TradeRecord
from data.market_data import market_data_service
from data.watchlist_manager import watchlist_manager
from trading.alpaca_client import alpaca_client
from data.tax_estimator import TaxEstimator

from data.drift_detector import check_all_agents
from data.risk_assessor import record_trade as record_risk_trade, run_periodic_assessment
from data.learning_manager import record_catalyst_outcome
from data.macro_context import get_macro_context_text
from agents.tech_agent import TechAgent
from agents.momentum_agent import MomentumAgent
from agents.mean_reversion_agent import MeanReversionAgent
from agents.sentiment_agent import SentimentAgent
from agents.claude_agent import ClaudeAgent
from agents.ollama_agent import OllamaAgent
from agents.gemini_agent import GeminiAgent
from agents.historical_trends_agent import HistoricalTrendsAgent
from agents.ensemble_agent import EnsembleAgent
from agents.scanner_portfolio_agent import ScannerPortfolioAgent
from agents.cnn_reasoning_agent import CNNReasoningAgent
from agents.summary_agent import daily_summary

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ─── JSON helpers ────────────────────────────────────────────────────────────
def _json_default(obj: Any) -> Any:
    """json.dumps default= hook: serialize PortfolioMetrics / PositionSummary /
    AgentState (which carry a dict shim via api.schemas._DictShim) by calling
    their ``to_dict()`` method. Anything else falls through to the standard
    TypeError so we don't silently mask serialization bugs."""
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _json_dumps(payload: Any) -> str:
    """json.dumps wrapper that handles api.schemas dataclasses via
    :func:`_json_default`. All WebSocket sends must go through this."""
    return json.dumps(payload, default=_json_default)


# ─── Crash Log (raw file — survives logging failures) ────────────────────────
# Written with open() so it works even if the RotatingFileHandler hasn't
# been initialised yet, and appears in the repo regardless of the launcher.

_CRASH_LOG_PATH = os.path.join(os.path.dirname(__file__), "logs", "crash.log")


def _write_crash(msg: str) -> None:
    """Append msg to crash.log with a UTC timestamp. Never raises."""
    try:
        os.makedirs(os.path.dirname(_CRASH_LOG_PATH), exist_ok=True)
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        with open(_CRASH_LOG_PATH, "a", encoding="utf-8") as _f:
            _f.write(f"{ts} {msg}\n")
    except Exception:
        pass


def _crash_excepthook(exc_type, exc_value, exc_tb) -> None:
    """sys.excepthook replacement — logs unhandled exceptions to crash.log."""
    import traceback
    tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    _write_crash(f"[UNHANDLED EXCEPTION]\n{tb_str}")
    # Also log via standard logging so it still appears in error.log
    logger.critical(f"Unhandled exception: {exc_value}", exc_info=(exc_type, exc_value, exc_tb))
    # Call the default handler so the process exits normally
    sys.__excepthook__(exc_type, exc_value, exc_tb)


sys.excepthook = _crash_excepthook

# Stamp the start of each process run so separate crashes are easy to distinguish
_write_crash(f"[PROCESS START] pid={os.getpid()}")


def _parse_ts(s: str) -> datetime:
    """Parse an ISO timestamp; treat naive strings as UTC so aware arithmetic works."""
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


# Ollama is the default primary model — always active unless explicitly disabled.
# Set before any agent or scanner code runs so the flag is visible to all modules.
os.environ.setdefault("OLLAMA_ONLY_MODE", "1")

# Off-hours scan interval in Ollama mode — scanner runs even when market is closed
# because local inference is free.  Cloud mode skips off-hours to avoid token cost.
OLLAMA_CLOSED_SCAN_MIN: int = 30

# Detect whether TLS certs exist (used to set the Secure cookie flag)
_CERTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'certs')
_HTTPS_ENABLED = os.path.isfile(os.path.join(_CERTS_DIR, 'cert.pem'))


# Suppress the Windows-specific "connection forcibly closed" asyncio noise.
# This fires whenever a browser tab closes/refreshes mid-connection and is harmless.
class _SuppressWin10054(logging.Filter):
    _NOISE = ("WinError 10054", "ConnectionResetError", "ConnectionAbortedError",
              "_call_connection_lost", "RemoteProtocolError")

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(n in msg for n in self._NOISE)

_win10054_filter = _SuppressWin10054()
logging.getLogger("asyncio").addFilter(_win10054_filter)
logging.getLogger("uvicorn.error").addFilter(_win10054_filter)
logging.getLogger("uvicorn.access").addFilter(_win10054_filter)
logging.root.addFilter(_win10054_filter)

# ─── Persistent Error Log File ──────────────────────────────────────────────

_LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
_ERROR_LOG_PATH       = os.path.join(_LOG_DIR, "error.log")        # WARNING+
_ERRORS_ONLY_LOG_PATH = os.path.join(_LOG_DIR, "errors_only.log")  # ERROR+ only

def _add_log_handler(path: str, level: int) -> None:
    """Add a RotatingFileHandler at `path` for `level`+, guarded against duplicates."""
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        handler = RotatingFileHandler(
            path,
            maxBytes=5 * 1024 * 1024,   # 5 MB per file
            backupCount=10,
            encoding="utf-8",
        )
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        handler.addFilter(_win10054_filter)
        already_added = any(
            isinstance(h, RotatingFileHandler)
            and os.path.abspath(getattr(h, "baseFilename", "")) == os.path.abspath(path)
            for h in logging.root.handlers
        )
        if not already_added:
            logging.root.addHandler(handler)
        else:
            handler.close()
    except OSError:
        pass  # Non-fatal

_add_log_handler(_ERROR_LOG_PATH,       logging.WARNING)  # warnings + errors
_add_log_handler(_ERRORS_ONLY_LOG_PATH, logging.ERROR)    # errors + critical only

_LOG_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[(\w+)\] ([^:]+): (.+)$"
)


def _parse_error_log(limit: int = 100, errors_only: bool = True) -> list:
    """Read and parse the log file, returning entries newest-first.

    errors_only=True  → reads errors_only.log (ERROR/CRITICAL, never polluted by warnings)
    errors_only=False → reads error.log       (WARNING/ERROR/CRITICAL, full log)
    """
    path = _ERRORS_ONLY_LOG_PATH if errors_only else _ERROR_LOG_PATH
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return []

    entries = []
    for line in reversed(lines):
        m = _LOG_LINE_RE.match(line.rstrip())
        if m:
            entries.append({
                "timestamp": m.group(1),
                "level":     m.group(2),
                "logger":    m.group(3).strip(),
                "message":   m.group(4),
            })
        if len(entries) >= limit:
            break
    return entries


# ─── Application State ──────────────────────────────────────────────────────
# AppState class + singleton extracted into backend/app_state.py (issue #67).
# Re-exported here so existing tests doing `from main import app_state, AppState`
# and `patch("main.app_state", ...)` continue to work.
from app_state import AppState, app_state  # noqa: E402


# ─── Lifespan + Agents (extracted to lifespan.py for #67) ────────────────────
# init_agents, _reconcile_cash_from_trades, lifespan, and the Ollama bootstrap
# helpers all live in backend/lifespan.py. They are imported back here so tests
# doing patch("main.init_agents", ...) and from main import lifespan continue to
# work without modification.
from lifespan import (  # noqa: E402
    _reconcile_cash_from_trades,
    init_agents,
    _add_ollama_to_path,
    _pull_ollama_model,
    _ensure_ollama_running,
    lifespan,
)



# ─── Loops + helpers (extracted to backend/loops/* for #67) ──────────────────
# Trading / auto-scan / news-sentinel / ws-broadcast loops, market-calendar
# helpers, news-price snapshot helpers, and per-cycle helpers all live in the
# loops package now. They are re-exported here so tests doing
#  and 
# continue to work unchanged.
from loops.market_calendar import (  # noqa: E402, F401
    _et_now,
    _nyse_holidays,
    _get_market_status,
    _market_is_open,
    _detect_close_transition,
    _minutes_until_open,
)
from loops.news_snapshots import (  # noqa: E402, F401
    _record_catalysts,
    _update_news_price_snapshots,
)
from loops.trading_loop import (  # noqa: E402, F401
    OLLAMA_CLOSED_SCAN_MIN,
    _refresh_summary,
    run_agent_cycle,
    save_performance_snapshots,
    trading_loop,
)
from loops.auto_scan_loop import auto_scan_loop  # noqa: E402, F401
from loops.news_sentinel_loop import (  # noqa: E402, F401
    _sentinel_log_catalysts,
    news_sentinel_loop,
)
from loops.ws_broadcast_loop import (  # noqa: E402, F401
    build_ws_message,
    ws_broadcast_loop,
)


# ─── FastAPI App ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="AI Trading Competition",
    description="Competitive paper trading with multiple AI agents",
    version="1.0.0",
    lifespan=lifespan,
)

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


# ─── Security Headers ─────────────────────────────────────────────────────────

@app.middleware("http")
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


# ─── Authentication Middleware ────────────────────────────────────────────────

# Paths that are always accessible without a session cookie.
_AUTH_EXEMPT = frozenset({
    "/api/login",
    "/api/logout",
    "/api/auth/check",
    "/docs",
    "/openapi.json",
    "/redoc",
})

@app.middleware("http")
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


# ─── Rate Limiter ─────────────────────────────────────────────────────────────

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


# ─── Auth Endpoints ───────────────────────────────────────────────────────────

@app.post("/api/login")
async def login(request: Request):
    """Verify password and issue a session cookie."""
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
        secure=_HTTPS_ENABLED,
        samesite="lax",
        max_age=auth.SESSION_TTL,
        path="/",
    )
    return response


@app.post("/api/logout")
async def logout(request: Request):
    """Revoke the current session and clear the cookie."""
    token = request.cookies.get(auth.SESSION_COOKIE)
    if token:
        auth.revoke_session(token)
    response = JSONResponse({"detail": "Logged out"})
    response.delete_cookie(key=auth.SESSION_COOKIE, path="/")
    return response


@app.get("/api/auth/check")
async def auth_check(request: Request):
    """
    Returns auth status.  Used by the frontend to decide whether to show the login page.
    Always accessible (no session required).
    """
    if not auth.is_enabled():
        return {"authenticated": True, "auth_enabled": False}
    token = request.cookies.get(auth.SESSION_COOKIE)
    if token and auth.validate_session(token):
        return {"authenticated": True, "auth_enabled": True}
    return JSONResponse({"authenticated": False, "auth_enabled": True}, status_code=401)


# ─── REST Endpoints ───────────────────────────────────────────────────────────

@app.get("/api/agents")
async def get_agents():
    """Get all agents with their current state."""
    prices = app_state.last_prices or {}

    if not prices and config.ALPACA_API_KEY:
        try:
            prices = await market_data_service.get_latest_prices(config.WATCHLIST)
            app_state.last_prices = prices
        except Exception:
            pass

    agents_state = []
    for agent in app_state.agents.values():
        try:
            state = agent.get_state(prices)
            agents_state.append(state)
        except Exception as e:
            logger.error(f"Error getting agent state for {agent.name}: {e}")

    return {"agents": agents_state, "count": len(agents_state)}


@app.get("/api/leaderboard")
async def get_leaderboard():
    """Get agents sorted by performance."""
    prices = app_state.last_prices or {}

    leaderboard = []
    for agent in app_state.agents.values():
        try:
            metrics = agent.get_performance_metrics(prices)
            leaderboard.append({
                "name": agent.name,
                "strategy": agent.strategy_description,
                "total_value": metrics["total_value"],
                "total_return_pct": metrics["total_return_pct"],
                "total_return": metrics["total_return"],
                "realized_pnl": metrics["realized_pnl"],
                "win_rate": metrics["win_rate"],
                "sharpe_ratio": metrics["sharpe_ratio"],
                "max_drawdown": metrics["max_drawdown"],
                "total_trades": metrics["total_trades"],
                "cash": metrics["cash"],
            })
        except Exception as e:
            logger.error(f"Error getting leaderboard for {agent.name}: {e}")

    leaderboard.sort(key=lambda x: x["total_return_pct"], reverse=True)
    for rank, entry in enumerate(leaderboard, 1):
        entry["rank"] = rank

    return {"leaderboard": leaderboard}


@app.get("/api/trades")
async def get_trades(
    agent_id: Optional[int] = Query(None, description="Filter by agent ID"),
    limit: int = Query(50, ge=1, le=5000),
):
    """Get recent trades, optionally filtered by agent.

    Upper bound raised 2026-05-16 from 200 to 5000: PR #57 bumped the
    frontend fetch to limit=500 for deeper trade-log history, but the
    server cap silently rejected it with 422 → blank trade log. 5000
    covers the longest-running agent (MomentumAgent currently 1,699
    trades) with headroom.
    """
    trades = await get_agent_trades(agent_id=agent_id, limit=limit)
    return {"trades": trades, "count": len(trades)}


@app.get("/api/market")
async def get_market():
    """Get current market prices and info for watchlist."""
    try:
        if app_state.last_prices and (time.time() - getattr(app_state, '_last_market_fetch', 0) < 10):
            prices = app_state.last_prices
        else:
            active_wl = watchlist_manager.get_active_watchlist()
            prices = await market_data_service.get_latest_prices(active_wl)
            app_state.last_prices = prices
            app_state._last_market_fetch = time.time()

        return {
            "prices": prices,
            "watchlist": watchlist_manager.get_active_watchlist(),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
    except Exception as e:
        logger.error(f"Error fetching market data: {e}")
        raise HTTPException(status_code=503, detail="Market data temporarily unavailable")


@app.get("/api/performance/{agent_name}")
async def get_agent_performance(agent_name: str):
    """Get performance history for a specific agent."""
    agent = app_state.agents.get(agent_name)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    history = []
    if agent.agent_id:
        history = await get_performance_history(agent.agent_id)

    # Also return in-memory value history for smoother charting
    value_history = agent.portfolio.get_value_history()

    return {
        "agent_name": agent_name,
        "db_history": history,
        "value_history": value_history,
    }


@app.post("/api/start")
async def start_trading():
    """Start the trading competition."""
    if app_state.is_running:
        return {"status": "already_running", "message": "Trading is already active"}

    if not config.ALPACA_API_KEY:
        return {
            "status": "warning",
            "message": "Starting without Alpaca API key - market data will be unavailable. Set ALPACA_API_KEY in .env",
        }

    app_state.is_running = True
    app_state.start_time = datetime.utcnow()
    app_state.trading_task  = asyncio.create_task(trading_loop())
    app_state.scan_task     = asyncio.create_task(auto_scan_loop())
    app_state.sentinel_task = asyncio.create_task(news_sentinel_loop())

    logger.info("Trading competition started!")
    return {
        "status": "started",
        "message": "Trading competition is now active",
        "agents": list(app_state.agents.keys()),
        "watchlist": config.WATCHLIST,
        "interval_seconds": config.TRADE_INTERVAL_SECONDS,
    }


@app.post("/api/stop")
async def stop_trading():
    """Stop the trading competition."""
    if not app_state.is_running:
        return {"status": "not_running", "message": "Trading is not active"}

    app_state.is_running = False

    for task in (app_state.trading_task, app_state.scan_task, app_state.sentinel_task):
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    logger.info("Trading competition stopped")
    return {"status": "stopped", "message": "Trading competition stopped", "cycles": app_state.cycle_count}


@app.post("/api/reset")
async def reset_competition():
    """Reset all portfolios and trade history."""
    # Stop trading first
    if app_state.is_running:
        app_state.is_running = False
        if app_state.trading_task and not app_state.trading_task.done():
            app_state.trading_task.cancel()
            try:
                await app_state.trading_task
            except asyncio.CancelledError:
                pass

    # Reset all agents
    for agent in app_state.agents.values():
        agent.reset()

    # Clear DB
    await reset_database()

    # Re-register agents
    for agent in app_state.agents.values():
        agent_id = await upsert_agent(agent.name, agent.strategy_description)
        agent.agent_id = agent_id

    # Clear market data cache and app state
    await market_data_service.clear_cache()

    app_state.cycle_count = 0
    app_state.last_prices = {}
    app_state.last_market_context = {}
    app_state.start_time = None
    app_state.after_hours_catalysts = []

    # Broadcast zeroed state immediately so UI updates without waiting for next WS cycle
    if app_state.ws_connections:
        reset_agents = [a.get_state({}) for a in app_state.agents.values()]
        reset_msg = {
            "type": "update",
            "agents": reset_agents,
            "leaderboard": reset_agents,
            "prices": {},
            "is_running": False,
            "cycle_count": 0,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "watchlist": config.WATCHLIST,
        }
        dead = set()
        for ws in app_state.ws_connections.copy():
            try:
                await ws.send_text(_json_dumps(reset_msg))
            except Exception:
                dead.add(ws)
        app_state.ws_connections -= dead

    logger.info("Competition reset complete")
    return {"status": "reset", "message": "All portfolios reset to starting capital"}


@app.get("/api/signals")
async def get_composite_signals():
    """Get multi-source composite signal for every watchlist symbol."""
    from data.signal_aggregator import get_composite_signal
    from data.news_service import news_service
    ctx = app_state.last_market_context
    if ctx:
        signals = {
            sym: sig
            for sym in ctx
            if isinstance(ctx[sym], dict)
            for sig in [ctx[sym].get("composite_signal", {})]
            if sig.get("verdict")  # skip empty/failed signals
        }
    else:
        active_wl = watchlist_manager.get_active_watchlist()
        news = await news_service.get_news_multi(active_wl)
        tasks = [get_composite_signal(sym, news.get(sym, [])) for sym in active_wl]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        signals = {sym: r for sym, r in zip(active_wl, results)
                   if not isinstance(r, Exception) and isinstance(r, dict) and r.get("verdict")}
    return {"signals": signals}


@app.get("/api/watchlist")
async def get_watchlist():
    """Get the current fluid watchlist with projected return scores for each symbol."""
    return {
        "watchlist": watchlist_manager.get_active_watchlist(),
        "scored_pool": watchlist_manager.scored_pool,
        "is_initialized": watchlist_manager.is_initialized,
        "anchors": config.WATCHLIST_ANCHORS,
        "seeds": config.WATCHLIST,
        "size": config.WATCHLIST_SIZE,
    }


@app.get("/api/scanner")
async def get_scanner_results():
    """Get the latest cached scanner recommendations (does not trigger a new scan)."""
    from agents.scanner_agent import get_cached_scan, is_scan_in_progress
    in_progress = is_scan_in_progress()
    cached = get_cached_scan()
    if cached:
        cached["is_scanning"] = in_progress
        return cached
    return {
        "status": "no_scan" if not in_progress else "scanning",
        "is_scanning": in_progress,
        "message": "No scan results yet. POST /api/scanner/run to trigger a scan.",
        "recommendations": [],
        "candidates": [],
    }


@app.get("/api/tax/estimate")
async def get_tax_estimate(year: Optional[int] = Query(None)):
    """
    Estimate realized capital gains and losses for the given calendar year.

    Returns short-term and long-term gain/loss figures, wash-sale count,
    and quarterly net breakdown. Federal only — caller applies their own rate.
    """
    if year is None:
        year = datetime.utcnow().year

    try:
        orders = await alpaca_client.get_filled_orders(year)
    except Exception as exc:
        logger.error("Tax estimate: Alpaca unavailable: %s", exc)
        raise HTTPException(status_code=503, detail={"error": "alpaca_unavailable"})

    estimator = TaxEstimator(orders)
    return estimator.summarize(year)


@app.post("/api/scanner/run")
async def trigger_scanner(request: Request):
    """Trigger a new agentic stock scan (or return cached result if fresh)."""
    ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(f"scanner:{ip}"):
        raise HTTPException(status_code=429, detail="Too many requests. Please wait before scanning again.")
    from agents.scanner_agent import run_scan
    try:
        # In Ollama-only mode manual triggers always run fresh (no 30-min cache block)
        force = os.environ.get("OLLAMA_ONLY_MODE") == "1"
        result = await run_scan(force=force)
        if result and result.get("status") == "ok":
            watchlist_manager.update_from_scan(result)
        return result
    except Exception as e:
        logger.error(f"Scanner run error: {e}")
        raise HTTPException(status_code=500, detail="Scanner encountered an error")


@app.get("/api/drift")
async def get_drift():
    """Check all agents for performance drift vs their historical baseline."""
    reports = check_all_agents(app_state.agents)
    drifting = [r for r in reports if r["is_drifting"]]
    return {
        "reports": reports,
        "drifting_agents": len(drifting),
        "all_clear": len(drifting) == 0,
    }


@app.get("/api/cnn-diagnostics")
async def get_cnn_diagnostics():
    """
    CNN model training diagnostics — overfitting / underfitting detection
    and Walk-Forward Efficiency (WFE) reporting.

    Diagnosis values:
      OK                  — healthy generalisation (ratio 1.0–2.5x)
      OVERFIT             — val MSE >> train MSE (ratio > 3x)
      OVERFIT_MEMORIZING  — train MSE < 1e-5 (memorised training data)
      UNDERFIT            — both MSEs > 0.005 (not learning signal)
      UNTRAINED           — model has not been trained yet

    Walk-Forward Efficiency (OOS R²):
      HEALTHY  — WFE >= 0.70 (model explains ≥ 70 % of OOS variance)
      DEGRADED — WFE 0.50–0.70 (partially predictive)
      POOR     — WFE < 0.50  (barely better than predicting the mean)
      UNTRAINED — not yet computed
    """
    # Use the selector so this endpoint reflects the *active* backend
    # (CNN or XGBoost) instead of always reading signal_cnn directly.
    # The fix that landed 2026-05-03 — before it, MODEL_BACKEND=xgboost
    # would still report CNN's frozen state to the frontend.
    import data.signal_model as _sm   # late import to pick up env-driven selector
    from data.cnn_model import load_training_history
    from data.regime_detector import regime_detector
    model = _sm.signal_model
    summary = model.training_summary()

    # backend_type: "cnn" | "xgboost". Derived from the selector's class name
    # so the frontend can label the diagnostics panel correctly.
    cls_name = type(model).__name__
    backend_type = "xgboost" if "XGBoost" in cls_name else "cnn"

    # Downsample loss curves to at most 40 points for the frontend.
    def _downsample(curve, n=40):
        if not curve or len(curve) <= n:
            return curve
        step = len(curve) / n
        return [curve[int(i * step)] for i in range(n)]

    return {
        "backend_type":     backend_type,
        "trained":          summary.get("trained", False),
        "device":           summary.get("device", "unknown"),
        "n_channels":       summary.get("n_channels", 0),
        "n_train":          summary.get("n_train", 0),
        "n_val":            summary.get("n_val", 0),
        "final_train_mse":  summary.get("final_train_mse"),
        "final_val_mse":    summary.get("final_val_mse"),
        # CNN-only fields — XGBoost summary doesn't carry them.
        "overfit_ratio":    summary.get("overfit_ratio"),
        "diagnosis":        summary.get("diagnosis"),
        # Walk-Forward Efficiency (both backends)
        "walk_forward_efficiency": summary.get("walk_forward_efficiency"),
        "wfe_status":              summary.get("wfe_status", "UNTRAINED"),
        # CNN-only loss curves
        "train_loss_curve": _downsample(summary.get("train_loss_curve", [])),
        "val_loss_curve":   _downsample(summary.get("val_loss_curve", [])),
        # Both backends
        "learned_weights":  summary.get("learned_weights", {}),
        # CNN-only delta-vs-prior-train; XGBoost recomputes from scratch each fit.
        "weight_delta":     summary.get("weight_delta", {}),
        "last_trained":     (
            __import__("datetime").datetime.fromtimestamp(
                summary["train_ts"],
                tz=__import__("datetime").timezone.utc,
            ).isoformat() if summary.get("train_ts") else None
        ),
        # Regime detector state
        "regime": regime_detector.summary(),
        # Last 30 retrains (oldest → newest) for day-over-day trajectory
        "training_history": load_training_history(limit=30),
        # Walk-forward CV metrics (added 2026-04-27)
        "fold_metrics":   summary.get("fold_metrics", []),
        "mean_ic":        summary.get("mean_ic", 0.0),
        "ir":             summary.get("ir", 0.0),
        "mean_wfe":       summary.get("mean_wfe"),
        "calibration":    summary.get("calibration", []),
    }


@app.post("/api/backfill")
async def trigger_backfill(days: int = 365):
    """
    Seed signal-history Parquet files with historical bar data.

    Fetches daily OHLCV bars for each watchlist symbol and computes
    return_1d, return_5d, rv_20d, and rv_60d for each bar.  Source
    scores are set to 0.0 (neutral prior — historical news is not
    reliably available).

    Use this to fast-seed the CNN training dataset without waiting
    days for live trading cycles to accumulate enough samples.

    Query params:
      days  — how many calendar days of history to backfill (default 365)
    """
    from data.history_backfill import backfill_signal_history, get_sample_counts
    symbols = watchlist_manager.get_active_watchlist()
    if not symbols:
        return {"status": "error", "message": "Watchlist is empty"}

    days = max(30, min(days, 1825))   # clamp 30d – 5yr
    results = await backfill_signal_history(symbols, days=days)
    counts  = await get_sample_counts()

    total_added = sum(results.values())
    return {
        "status":       "ok",
        "days":         days,
        "symbols":      len(symbols),
        "rows_added":   total_added,
        "per_symbol":   results,
        "sample_counts": counts,
    }


@app.get("/api/backfill/status")
async def get_backfill_status():
    """Return current sample counts per symbol (how much CNN training data exists)."""
    from data.history_backfill import get_sample_counts
    from data.cnn_model import MIN_TRAIN_SAMPLES
    counts = await get_sample_counts()
    total  = sum(counts.values())
    return {
        "sample_counts":      counts,
        "total_samples":      total,
        "min_train_samples":  MIN_TRAIN_SAMPLES,
        "ready_to_train":     total >= MIN_TRAIN_SAMPLES,
    }


@app.post("/api/backfill/macro")
async def trigger_macro_backfill(days: int = 365):
    """
    Seed __MACRO__.parquet with historical macro environment data.

    Fetches GLD/TLT/UUP/USO/SPY/IWM/QQQ from Alpaca and ^VIX/^TNX from
    yfinance, then computes per-day ETF returns, VIX normalisation,
    breadth score, and regime label.

    Query params:
      days — calendar days of history to backfill (default 365, max 1825)
    """
    from data.history_backfill import backfill_macro_history
    days = max(30, min(days, 1825))
    result = await backfill_macro_history(days=days)
    return {
        "status":     "ok",
        "days":       days,
        "rows_added": result.get("rows_added", 0),
    }


@app.get("/api/status")
async def get_status():
    """Get application status."""
    return {
        "is_running": app_state.is_running,
        "market_status": app_state.market_status,
        "cycle_count": app_state.cycle_count,
        "start_time": (app_state.start_time.isoformat() + "Z") if app_state.start_time else None,
        "agent_count": len(app_state.agents),
        "ws_connections": len(app_state.ws_connections),
        "watchlist": watchlist_manager.get_active_watchlist(),
        "starting_capital": config.STARTING_CAPITAL,
        "trade_interval_seconds": config.TRADE_INTERVAL_SECONDS,
    }


# ── benchmarks (Portfolio vs SPY vs DJIA) ─────────────────────────────────────
#
# 2026-05-09 (#83): every agent's percentage return since inception alongside
# the same-window SPY and DJIA returns. Renders as a dashboard widget so the
# user can glance-anchor portfolio performance vs the broad market and DOW.
#
# "Inception" = MIN(agents.created_at) — when this app first started running.
# All agents share that same reference because they're registered together
# in init_agents(). The indices are computed over the same window so the
# comparison is apples-to-apples.

# Cache benchmark fetches for a few minutes — calling yfinance on every UI
# refresh would be wasteful. The numbers don't change second-to-second.
_BENCHMARK_CACHE: Dict[str, Any] = {"as_of": 0.0, "data": None}
_BENCHMARK_CACHE_TTL = 300.0   # 5 min


def _index_return_pct(ticker: str, days: int) -> Optional[float]:
    """Fetch percentage return of `ticker` over the last `days` trading days
    via yfinance. Returns None on any failure (network, package missing,
    insufficient history) so callers can degrade gracefully.

    Uses period='Nd' with N a few days bigger than `days` (calendar slop
    around weekends/holidays), then takes (last_close − first_close) / first_close.
    """
    try:
        import yfinance as _yf
    except ImportError:
        logger.warning("benchmarks: yfinance not available — index returns unavailable")
        return None
    try:
        # Fetch slightly more calendar days than `days` to cover weekends.
        # yfinance returns business days only, so 1.5x is a safe buffer.
        df = _yf.download(ticker, period=f"{int(days * 1.5)}d", progress=False, auto_adjust=False)
        if df is None or df.empty:
            return None
        # Handle MultiIndex columns (yfinance >= 0.2 for single-ticker fetches)
        if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
            df = df.xs("Close", axis=1, level=0)
            close_col = df.columns[0]
            closes = df[close_col].dropna()
        else:
            closes = df["Close"].dropna() if "Close" in df.columns else df["close"].dropna()
        if len(closes) < 2:
            return None
        first = float(closes.iloc[0])
        last  = float(closes.iloc[-1])
        if first <= 0:
            return None
        return (last - first) / first * 100.0
    except Exception as exc:
        logger.warning(f"benchmarks: {ticker} fetch failed: {exc}")
        return None


@app.get("/api/benchmarks")
async def get_benchmarks():
    """Portfolio-vs-index benchmark data for the dashboard widget.

    Returns each agent's since-inception percentage return alongside the
    same-window SPY and DJIA returns. Inception = earliest agents.created_at.

    Schema:
      {
        "period_days": <int — days from inception to now>,
        "as_of": "<iso ts>",
        "spy_return_pct": <float | null>,
        "dji_return_pct": <float | null>,
        "agents": [{"name": str, "return_pct": float, "total_value": float}, ...]
      }

    Cached for 5 min so UI refresh doesn't hammer yfinance.
    """
    import time as _time
    now = _time.time()
    cached = _BENCHMARK_CACHE.get("data")
    if cached is not None and (now - _BENCHMARK_CACHE.get("as_of", 0)) < _BENCHMARK_CACHE_TTL:
        return cached

    # Inception window: earliest agent registration → today
    inception_iso: Optional[str] = None
    try:
        import aiosqlite as _aiosqlite
        from database import DB_PATH as _DB_PATH
        async with _aiosqlite.connect(_DB_PATH) as db:
            cur = await db.execute("SELECT MIN(created_at) FROM agents")
            row = await cur.fetchone()
            if row and row[0]:
                inception_iso = str(row[0])
    except Exception as exc:
        logger.warning(f"benchmarks: could not read agent inception: {exc}")

    period_days = 30   # default fallback if we can't determine inception
    if inception_iso:
        try:
            inception_dt = datetime.fromisoformat(inception_iso.replace("Z", "+00:00"))
            if inception_dt.tzinfo is None:
                inception_dt = inception_dt.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - inception_dt
            period_days = max(1, int(delta.total_seconds() / 86_400))
        except Exception as exc:
            logger.warning(f"benchmarks: could not parse inception '{inception_iso}': {exc}")

    spy_pct = _index_return_pct("SPY", period_days)
    dji_pct = _index_return_pct("DIA", period_days)

    # Per-agent return: total_value vs starting_capital (since-inception)
    agents_data: List[Dict[str, Any]] = []
    starting = float(config.STARTING_CAPITAL)
    for agent in app_state.agents.values():
        try:
            total = float(agent.portfolio.get_total_value(app_state.last_prices))
            ret_pct = (total - starting) / starting * 100.0 if starting > 0 else 0.0
            agents_data.append({
                "name": agent.name,
                "return_pct": round(ret_pct, 2),
                "total_value": round(total, 2),
            })
        except Exception as exc:
            logger.debug(f"benchmarks: skipping {agent.name}: {exc}")

    agents_data.sort(key=lambda r: r["return_pct"], reverse=True)

    result = {
        "period_days": period_days,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "spy_return_pct": round(spy_pct, 2) if spy_pct is not None else None,
        "dji_return_pct": round(dji_pct, 2) if dji_pct is not None else None,
        "agents": agents_data,
    }

    _BENCHMARK_CACHE["data"] = result
    _BENCHMARK_CACHE["as_of"] = now
    return result


@app.get("/api/summary")
async def get_daily_summary(force: bool = False):
    """
    Get the daily roll-up summary — agent decisions, consensus map, and
    Claude-authored narrative. Cached; use ?force=true to regenerate immediately.
    """
    prices = app_state.last_prices or {}
    from agents.scanner_agent import get_cached_scan
    scan = get_cached_scan()
    scanner_recs = scan.get("recommendations", []) if scan else []

    result = await daily_summary.generate(
        agents=app_state.agents,
        prices=prices,
        market_status=app_state.market_status,
        scanner_recs=scanner_recs,
        sentinel_catalysts=app_state.after_hours_catalysts,
        force=force,
    )
    return result


@app.get("/api/picks")
async def get_agent_picks():
    """Get each agent's current retained pick symbols and conviction data."""
    result = {}
    for name, agent in app_state.agents.items():
        picks = agent._picks
        if picks:
            result[name] = picks
    return {"picks": result, "total_agents_with_picks": len(result)}


@app.post("/api/force-trading")
async def set_force_trading(enabled: bool = True):
    """Enable or disable forced trading mode (bypasses market-hours gate)."""
    app_state.force_trading = enabled
    state = "ENABLED" if enabled else "DISABLED"
    logger.warning(f"Force-trading mode {state}")
    return {"force_trading": enabled, "message": f"Force trading {state}"}


@app.get("/api/sentinel")
async def get_sentinel_catalysts():
    """Get after-hours catalysts detected by the news and policy sentinel."""
    return {
        "market_status":       app_state.market_status,
        "market_is_open":      _market_is_open(),
        "minutes_until_open":  round(_minutes_until_open(), 1),
        "last_poll":           app_state.last_sentinel_poll,
        "catalyst_count":      len(app_state.after_hours_catalysts),
        "catalysts":           app_state.after_hours_catalysts,
    }


@app.get("/api/news-impact")
async def get_news_impact():
    """Return news-price correlation snapshots — shows how catalysts moved prices."""
    snapshots = app_state.news_price_snapshots
    # Sort: confirmed moves first (have price_1h), then pending
    confirmed = sorted(
        [s for s in snapshots if s["change_1h"] is not None],
        key=lambda x: abs(x["change_1h"]),
        reverse=True,
    )
    pending = [s for s in snapshots if s["change_1h"] is None]
    return {
        "total":     len(snapshots),
        "confirmed": confirmed,
        "pending":   pending,
    }


@app.get("/api/tokens")
async def get_token_usage():
    """
    Return AI token usage statistics for all agents.

    Per-agent breakdown:
    - daily_tokens: tokens consumed today (resets at midnight)
    - session_tokens: tokens consumed since last app restart
    - calls_this_hour: API calls made in the last 60 minutes
    - hourly_call_limit: maximum calls allowed per hour
    - daily_limit: daily token cap (only set for SentimentAgent)
    - daily_remaining: tokens remaining today (only when daily_limit set)

    Grand totals (daily and session) are summed across all agents.
    """
    import time as _time

    _TOKEN_AGENTS = ["ClaudeAgent", "GeminiAgent", "SentimentAgent"]

    def _agent_stats(agent) -> dict:
        now = _time.time()
        calls_this_hour = sum(1 for t in getattr(agent, "_call_timestamps", []) if now - t < 3600)
        daily = getattr(agent, "_daily_tokens", 0)
        limit = getattr(agent, "_daily_token_limit", None)
        entry = {
            "daily_tokens":       daily,
            "session_tokens":     getattr(agent, "_session_tokens", 0),
            "calls_this_hour":    calls_this_hour,
            "hourly_call_limit":  getattr(agent, "_hourly_call_limit", None),
        }
        if limit is not None:
            entry["daily_limit"]     = limit
            entry["daily_remaining"] = max(0, limit - daily)
        return entry

    agents_out: dict = {}

    # Trading agents that track tokens (in-memory stats + DB fallback for daily_tokens)
    for name, agent in app_state.agents.items():
        if name in _TOKEN_AGENTS:
            entry = _agent_stats(agent)
            # If in-memory daily_tokens is 0, fall back to DB so the panel reflects
            # any calls logged before this session (e.g. restart mid-day, Ollama mode)
            if entry["daily_tokens"] == 0:
                entry["daily_tokens"] = await get_daily_token_total(name, hours=24)
            agents_out[name] = entry

    # Gemini runs as news agent outside app_state.agents
    if app_state.gemini_news_agent and "GeminiAgent" not in agents_out:
        entry = _agent_stats(app_state.gemini_news_agent)
        if entry["daily_tokens"] == 0:
            entry["daily_tokens"] = await get_daily_token_total("GeminiAgent", hours=24)
        agents_out["GeminiAgent"] = entry

    # Agents that are standalone functions with no in-memory state — query the DB
    _DB_AGENTS = (
        "ScannerAgent/Claude",
        "ScannerAgent/Gemini",
        "ScannerAgent/OpenAI",
        "ScannerAgent/Ollama",
        "SummaryAgent",
    )
    for db_agent in _DB_AGENTS:
        daily = await get_daily_token_total(db_agent, hours=24)
        calls_hr = await get_agent_calls_this_hour(db_agent)
        agents_out[db_agent] = {
            "daily_tokens":      daily,
            "session_tokens":    daily,
            "calls_this_hour":   calls_hr,
            "hourly_call_limit": None,
        }

    totals = {
        "daily_tokens":   sum(v["daily_tokens"]   for v in agents_out.values()),
        "session_tokens": sum(v["session_tokens"] for v in agents_out.values()),
    }

    return {"agents": agents_out, "totals": totals}


@app.get("/api/token-log")
async def get_token_log_endpoint(
    agent: Optional[str] = Query(None, description="Filter by agent name"),
    hours: int = Query(24, description="Time window in hours"),
    limit_hit: bool = Query(False, description="Only return limit-hit events"),
    limit: int = Query(500, description="Max entries to return"),
):
    """Return DB token usage log, newest first. Searchable by agent, time window, and limit_hit."""
    entries = await get_token_log(
        agent=agent,
        hours=hours,
        limit_hit_only=limit_hit,
        limit=limit,
    )
    return {"entries": entries}


# ─── Error Log Endpoints ───────────────────────────────────────────────────────

@app.get("/api/errors")
async def get_error_log_endpoint(
    limit: int = Query(200, description="Max entries to return"),
    errors_only: bool = Query(True, description="True=ERROR/CRITICAL only; False=include WARNINGs"),
):
    """Return recent log entries newest-first.
    Default: errors_only=True reads errors_only.log (ERROR/CRITICAL, never diluted by warnings).
    Pass errors_only=false to include WARNING entries from the full error.log.
    """
    return {
        "entries": _parse_error_log(limit=limit, errors_only=errors_only),
        "source": "errors_only.log" if errors_only else "error.log",
    }


@app.post("/api/ollama-mode")
async def set_ollama_mode(
    enabled: bool = Query(..., description="true to activate, false to deactivate"),
    hours: float = Query(24.0, description="Duration in hours (default 24)"),
):
    """Enable or disable Ollama-only mode. While active, Claude, Gemini and OpenAI
    sentiment calls are skipped — only the local Ollama model is used."""
    from datetime import timedelta
    if enabled:
        app_state.ollama_only_until = datetime.utcnow() + timedelta(hours=hours)
        os.environ["OLLAMA_ONLY_MODE"] = "1"
        expires_iso = app_state.ollama_only_until.isoformat() + "Z"
        logger.info(f"Ollama-only mode ENABLED for {hours}h — expires {expires_iso}")
        return {
            "enabled": True,
            "expires_at": expires_iso,
            "message": f"Ollama-only mode active for {hours} hours. Claude, OpenAI and Gemini calls are paused.",
        }
    else:
        app_state.ollama_only_until = None
        os.environ.pop("OLLAMA_ONLY_MODE", None)
        logger.info("Ollama-only mode DISABLED")
        return {
            "enabled": False,
            "expires_at": None,
            "message": "Ollama-only mode disabled. All AI providers restored.",
        }


@app.get("/api/errors/analyze")
async def analyze_error_log():
    """Send recent ERROR/CRITICAL entries to Claude Haiku and return root-cause analysis."""
    import anthropic

    # Read from errors_only.log so warnings never dilute the analysis
    entries = _parse_error_log(limit=50, errors_only=True)
    error_entries = [e for e in entries if e["level"] in ("ERROR", "CRITICAL")]

    if not error_entries:
        return {"errors": [], "analysis": "No errors found in the log."}

    if not config.ANTHROPIC_API_KEY:
        return {
            "errors": [f"{e['timestamp']} [{e['level']}] {e['logger']}: {e['message']}" for e in error_entries],
            "analysis": "Anthropic API key not configured — cannot analyze.",
        }

    # Build chronological error text for the prompt
    error_text = "\n".join(
        f"{e['timestamp']} [{e['level']}] {e['logger']}: {e['message']}"
        for e in reversed(error_entries)
    )

    client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": (
                "Analyze these error log entries from an AI trading application "
                "and suggest specific fixes:\n\n"
                f"{error_text}\n\n"
                "Respond with:\n"
                "1. Root cause for each distinct error type\n"
                "2. Specific code or config change to fix it\n"
                "3. Priority: Critical / High / Medium\n\n"
                "Be concise and actionable."
            ),
        }],
    )

    analysis = response.content[0].text if response.content else "Analysis unavailable."
    return {
        "errors": [
            f"{e['timestamp']} [{e['level']}] {e['logger']}: {e['message']}"
            for e in error_entries
        ],
        "analysis": analysis,
    }


# ─── Telemetry ────────────────────────────────────────────────────────────────

@app.get("/api/telemetry")
async def get_telemetry():
    """Return system resource usage, Ollama model status, and scanner timing history."""
    from agents.scanner_agent import _scan_history, _ollama_is_available

    # ── System metrics ────────────────────────────────────────────────────────
    cpu_pct = 0.0
    mem_total_gb = 0.0
    mem_available_gb = 0.0
    mem_pct = 0.0
    process_memory_mb = 0.0

    if psutil is not None:
        try:
            cpu_pct = float(psutil.cpu_percent(interval=0.2))
            vm = psutil.virtual_memory()
            mem_total_gb    = round(vm.total    / 1024**3, 1)
            mem_available_gb = round(vm.available / 1024**3, 1)
            mem_pct          = float(vm.percent)
            proc = psutil.Process()
            process_memory_mb = round(proc.memory_info().rss / 1024**2, 1)
        except Exception as e:
            logger.debug(f"Telemetry: psutil error: {e}")

    # ── GPU metrics (nvidia-smi) ──────────────────────────────────────────────
    gpu_list: list = []
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) == 5:
                    name, util, mem_used, mem_total, temp = parts
                    gpu_list.append({
                        "name":          name,
                        "util_pct":      float(util),
                        "vram_used_mb":  float(mem_used),
                        "vram_total_mb": float(mem_total),
                        "temp_c":        float(temp),
                    })
    except Exception:
        pass  # No NVIDIA GPU or nvidia-smi not on PATH — degrade gracefully

    # ── Ollama model info ─────────────────────────────────────────────────────
    ollama_models = []
    ollama_online = False
    try:
        base = config.OLLAMA_BASE_URL.rstrip("/")
        ps_url = (base[:-3] if base.endswith("/v1") else base) + "/api/ps"
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(ps_url)
            if r.status_code == 200:
                ollama_online = True
                for m in r.json().get("models", []):
                    size_gb = round(m.get("size", 0) / 1024**3, 2)
                    vram    = m.get("size_vram", 0)
                    processor = "GPU" if vram and vram > 0 else "CPU"
                    ollama_models.append({
                        "name":       m.get("name", ""),
                        "size_gb":    size_gb,
                        "processor":  processor,
                        "expires_at": m.get("expires_at", ""),
                    })
    except Exception:
        pass

    # ── Scan history ──────────────────────────────────────────────────────────
    scan_durations = list(_scan_history)
    avg_scan_sec   = round(sum(scan_durations) / len(scan_durations), 1) if scan_durations else 0.0

    return {
        "cpu_pct":           cpu_pct,
        "memory": {
            "total_gb":     mem_total_gb,
            "available_gb": mem_available_gb,
            "used_pct":     mem_pct,
        },
        "process_memory_mb": process_memory_mb,
        "gpu":               gpu_list,
        "ollama": {
            "online":  ollama_online,
            "mode":    "local" if os.environ.get("OLLAMA_ONLY_MODE") == "1" else "off",
            "models":  ollama_models,
        },
        "scan_history": {
            "durations_sec": scan_durations,
            "avg_sec":       avg_scan_sec,
            "count":         len(scan_durations),
        },
    }


# ─── WebSocket ─────────────────────────────────────────────────────────────────
# /ws endpoint extracted to backend/ws.py for #67. The router is mounted on
# the FastAPI app below; websocket_endpoint is re-exported so tests that
# import `from main import websocket_endpoint` continue to work.
from ws import ws_router, websocket_endpoint  # noqa: E402, F401
app.include_router(ws_router)


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import subprocess as _sp, os as _os, time as _time, pathlib as _pl

    # Free port 8000 if another instance is running
    try:
        r = _sp.run(["netstat", "-ano"], capture_output=True, text=True)
        for _line in r.stdout.splitlines():
            if ":8000" in _line and "LISTENING" in _line:
                _pid = int(_line.strip().split()[-1])
                if _pid != _os.getpid():
                    _sp.run(["taskkill", "/F", "/PID", str(_pid)], capture_output=True)
                    _time.sleep(1)
                    break
    except Exception:
        pass

    # TLS cert paths (trading_app/certs/)
    _root = _pl.Path(__file__).parent.parent
    _cert = _root / "certs" / "cert.pem"
    _key  = _root / "certs" / "key.pem"
    _ssl_kwargs = {}
    if _cert.exists() and _key.exists():
        _ssl_kwargs = {"ssl_certfile": str(_cert), "ssl_keyfile": str(_key)}
        logger.info(f"TLS enabled — backend serving on https://localhost:{config.PORT}")
    else:
        logger.warning("No TLS cert found — serving HTTP. Run gen_certs.py to enable HTTPS.")

    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=config.PORT,
        reload=False,
        log_level="info",
        ws_ping_interval=20,
        ws_ping_timeout=20,
        **_ssl_kwargs,
    )
