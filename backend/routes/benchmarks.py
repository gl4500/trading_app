"""Benchmarks endpoint: /api/benchmarks (Portfolio vs SPY vs DJIA).

2026-05-09 (#83): every agent's percentage return since inception alongside
the same-window SPY and DJIA returns. Renders as a dashboard widget so the
user can glance-anchor portfolio performance vs the broad market and DOW.

"Inception" = MIN(agents.created_at) — when this app first started running.
All agents share that same reference because they're registered together
in init_agents(). The indices are computed over the same window so the
comparison is apples-to-apples.
"""
from __future__ import annotations

from datetime import timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter

benchmarks_router = APIRouter()


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
    import main
    _logger = main.logger
    try:
        import yfinance as _yf
    except ImportError:
        _logger.warning("benchmarks: yfinance not available — index returns unavailable")
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
        _logger.warning(f"benchmarks: {ticker} fetch failed: {exc}")
        return None


@benchmarks_router.get("/api/benchmarks")
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
    import main
    import time as _time
    _logger = main.logger
    _config = main.config
    app_state = main.app_state

    now = _time.time()
    cached = main._BENCHMARK_CACHE.get("data")
    if cached is not None and (now - main._BENCHMARK_CACHE.get("as_of", 0)) < _BENCHMARK_CACHE_TTL:
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
        _logger.warning(f"benchmarks: could not read agent inception: {exc}")

    period_days = 30   # default fallback if we can't determine inception
    if inception_iso:
        try:
            inception_dt = main.datetime.fromisoformat(inception_iso.replace("Z", "+00:00"))
            if inception_dt.tzinfo is None:
                inception_dt = inception_dt.replace(tzinfo=timezone.utc)
            delta = main.datetime.now(timezone.utc) - inception_dt
            period_days = max(1, int(delta.total_seconds() / 86_400))
        except Exception as exc:
            _logger.warning(f"benchmarks: could not parse inception '{inception_iso}': {exc}")

    spy_pct = main._index_return_pct("SPY", period_days)
    dji_pct = main._index_return_pct("DIA", period_days)

    # Per-agent return: total_value vs starting_capital (since-inception)
    agents_data: List[Dict[str, Any]] = []
    starting = float(_config.STARTING_CAPITAL)
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
            _logger.debug(f"benchmarks: skipping {agent.name}: {exc}")

    agents_data.sort(key=lambda r: r["return_pct"], reverse=True)

    result = {
        "period_days": period_days,
        "as_of": main.datetime.now(timezone.utc).isoformat(),
        "spy_return_pct": round(spy_pct, 2) if spy_pct is not None else None,
        "dji_return_pct": round(dji_pct, 2) if dji_pct is not None else None,
        "agents": agents_data,
    }

    main._BENCHMARK_CACHE["data"] = result
    main._BENCHMARK_CACHE["as_of"] = now
    return result
