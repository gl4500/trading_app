"""HTTP route modules.

Each module exports a single APIRouter that main.py mounts onto the FastAPI
app via include_router. The `all_routers` list provides a single import point
for main.py to register every router at once.

Routers are intentionally grouped by concern, not by HTTP verb:

  auth.py         — /api/login, /api/logout, /api/auth/check
  trading.py      — /api/start, /api/stop, /api/reset, /api/force-trading
  data.py         — read endpoints for portfolio, watchlist, signals, etc.
  diagnostics.py  — /api/status, /api/cnn-diagnostics, /api/telemetry
  benchmarks.py   — /api/benchmarks
  tax.py          — /api/tax/estimate
  ollama.py       — /api/ollama-mode
  error_logs.py   — /api/errors, /api/errors/analyze
  scanner.py      — /api/scanner, /api/scanner/run
  token_usage.py  — /api/tokens, /api/token-log
"""
from .auth import auth_router
from .trading import trading_router
from .data import data_router
from .diagnostics import diagnostics_router
from .benchmarks import benchmarks_router
from .tax import tax_router
from .ollama import ollama_router
from .error_logs import error_logs_router
from .scanner import scanner_router
from .token_usage import token_usage_router

all_routers = [
    auth_router,
    trading_router,
    data_router,
    diagnostics_router,
    benchmarks_router,
    tax_router,
    ollama_router,
    error_logs_router,
    scanner_router,
    token_usage_router,
]
