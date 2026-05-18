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


# === Routes (extracted to backend/routes/* for issue #67) ====================
# All FastAPI endpoint handlers (auth, trading, data, diagnostics, benchmarks,
# tax, ollama, error_logs, scanner, token_usage) now live in the routes package
# as APIRouter instances. main.py mounts them via app.include_router(...).
#
# _BENCHMARK_CACHE and _index_return_pct are re-exported because
# tests/test_main_endpoints.py imports them as main._BENCHMARK_CACHE.
from routes.benchmarks import _BENCHMARK_CACHE, _index_return_pct  # noqa: E402, F401
from routes import all_routers  # noqa: E402
for _router in all_routers:
    app.include_router(_router)



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
