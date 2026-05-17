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



# ─── News-Price Correlation ──────────────────────────────────────────────────

_REACTION_WINDOW_SECS = 300   # 5 min initial reaction window for intraday catalysts
_SUSTAINED_WINDOW_SECS = 3600  # 60 min for the sustained (price_1h) reading


async def _record_catalysts(new_catalysts: List[Dict]) -> None:
    """Deduplicate and persist new sentinel catalysts into app_state.

    Deduplicates against BOTH after_hours_catalysts (in-memory) AND
    news_price_snapshots (DB-restored on startup) so that post-restart
    re-detection of already-seen headlines does not create duplicate entries.
    """
    # Build the full set of known headlines from both sources
    all_headlines: Set[str] = (
        {c["headline"] for c in app_state.after_hours_catalysts} |
        {s["headline"] for s in app_state.news_price_snapshots}
    )
    for cat in new_catalysts:
        headline = cat["headline"]
        if headline in all_headlines:
            continue
        app_state.after_hours_catalysts.append(cat)
        all_headlines.add(headline)
        # Record price snapshot for news-price correlation tracking
        sym = cat.get("symbol")
        if sym and sym in app_state.last_prices:
            app_state.news_price_snapshots.append({
                "symbol":         sym,
                "headline":       headline[:120],
                "score":          cat.get("score", 0),
                "category":       cat.get("category", "news"),
                "price_at":       app_state.last_prices[sym],
                "detected_at":    cat.get("detected_at", datetime.utcnow().isoformat() + "Z"),
                "during_session": _market_is_open(),
                "price_open":     None,
                "price_1h":       None,
                "change_open":    None,
                "change_1h":      None,
                "open_recorded_at": None,
            })
            try:
                new_snap = app_state.news_price_snapshots[-1]
                db_id = await save_price_snapshot(new_snap)
                new_snap["_db_id"] = db_id
            except Exception as _e:
                logger.debug(f"save_price_snapshot failed: {_e}")

    # Trim to top 50 by score
    app_state.after_hours_catalysts = sorted(
        app_state.after_hours_catalysts,
        key=lambda c: c.get("score", 0),
        reverse=True,
    )[:50]

async def _update_news_price_snapshots(prices: Dict[str, float]) -> None:
    """Fill price_open / price_1h fields on correlation snapshots as trading progresses.

    After-hours catalysts (during_session=False):
      price_open  — captured immediately on the first trading-cycle price read
                    (i.e. at market open the next morning).

    Intraday catalysts (during_session=True):
      price_open  — captured once >= 5 min have elapsed since detection
                    (gives the market time to react before we record).

    Both types:
      price_1h    — captured once, >= 60 min after price_open was recorded, then
                    frozen permanently so the UI shows a stable 1-hour outcome.
    """
    now = datetime.utcnow()
    for snap in app_state.news_price_snapshots:
        sym = snap["symbol"]
        if sym not in prices:
            continue
        current = prices[sym]
        base = snap["price_at"]
        if not base or base <= 0:
            continue
        pct = (current - base) / base * 100

        if snap["price_open"] is None:
            ready = True
            if snap.get("during_session"):
                # Intraday: wait for the 5-min reaction window to elapse
                try:
                    det = datetime.fromisoformat(snap["detected_at"].replace("Z", ""))
                    ready = (now - det).total_seconds() >= _REACTION_WINDOW_SECS
                except Exception:
                    ready = True
            if ready:
                snap["price_open"] = current
                snap["change_open"] = round(pct, 2)
                snap["open_recorded_at"] = now
                if snap.get("_db_id"):
                    try:
                        await update_price_snapshot(
                            snap["_db_id"],
                            price_open=current,
                            change_open=snap["change_open"],
                            open_recorded_at=now,
                        )
                    except Exception as _e:
                        logger.debug(f"DB update price_open failed: {_e}")

        elif snap["price_1h"] is None:
            # Wait until >= 60 min have elapsed since price_open was recorded
            recorded_at = snap.get("open_recorded_at")
            if recorded_at and (now - recorded_at).total_seconds() >= _SUSTAINED_WINDOW_SECS:
                change_1h = round(pct, 2)
                snap["price_1h"] = current
                snap["change_1h"] = change_1h
                if snap.get("_db_id"):
                    try:
                        await update_price_snapshot(
                            snap["_db_id"],
                            price_1h=current,
                            change_1h=change_1h,
                        )
                    except Exception as _e:
                        logger.debug(f"DB update price_1h failed: {_e}")
                # Record the confirmed outcome to learning.json so agents can
                # learn which catalyst types actually move prices
                try:
                    confirmed = abs(change_1h) >= 0.05
                    record_catalyst_outcome(
                        symbol=sym,
                        category=snap.get("category", "catalyst"),
                        score=snap.get("score", 0),
                        headline=snap.get("headline", ""),
                        change_open=snap.get("change_open") or 0.0,
                        change_1h=change_1h,
                        during_session=snap.get("during_session", False),
                        confirmed=confirmed,
                    )
                except Exception as _e:
                    logger.debug(f"catalyst outcome record failed: {_e}")
        # price_1h already set — leave it frozen, no further updates

    # Keep only the 100 most recent
    app_state.news_price_snapshots = app_state.news_price_snapshots[-100:]


# ─── Trading Loop ────────────────────────────────────────────────────────────

async def trading_loop() -> None:
    """Main trading loop that runs every TRADE_INTERVAL_SECONDS."""
    logger.info("Trading loop started")

    while app_state.is_running:
        try:
            # ── Session gate ─────────────────────────────────────────────────
            status = _get_market_status()
            just_closed = _detect_close_transition(app_state._prev_market_status, status)
            app_state._prev_market_status = status
            app_state.market_status = status

            if status == "closed" and not app_state.force_trading:
                mins = _minutes_until_open()
                # Wake up 5 min before open; minimum 60s poll
                sleep_secs = max(60, (mins - 5) * 60)
                logger.info(
                    f"Market closed (next open in {mins:.0f} min). "
                    f"Trading loop sleeping {sleep_secs/60:.0f} min."
                )
                # Sleep in 10-second chunks so force_trading toggle takes effect quickly
                slept = 0
                try:
                    while slept < sleep_secs and app_state.is_running and not app_state.force_trading:
                        await asyncio.sleep(min(10, sleep_secs - slept))
                        slept += 10
                except asyncio.CancelledError:
                    break
                if not app_state.is_running:
                    break
                if just_closed:
                    logger.info("Market closed — triggering end-of-day roll-up")
                    asyncio.create_task(
                        _refresh_summary(app_state.last_prices or {}, status)
                    )
                continue  # re-check status (may now be force_trading=True or market open)

            if app_state.force_trading and status == "closed":
                app_state.market_status = "open (test)"
                logger.debug("Trading session: FORCED (test mode)")
            else:
                logger.debug(f"Trading session: {status.upper()}")
            # ── End session gate ─────────────────────────────────────────────

            cycle_start = time.time()
            app_state.cycle_count += 1
            logger.info(f"=== Trading Cycle {app_state.cycle_count} ===")
            if app_state.cycle_count % 30 == 0:
                try:
                    run_periodic_assessment(app_state.agents, app_state.last_prices or {})
                except Exception as e:
                    logger.debug(f"Risk assessment error: {e}")

            # Daily DB prune — every 1440 cycles (~24 h at 60 s intervals).
            # Performance table is intentionally NOT pruned (user policy
            # 2026-05-16: continuity for all trades, not just days).
            if app_state.cycle_count % 1440 == 0:
                try:
                    await prune_news_price_snapshots(days=14)
                except Exception as e:
                    logger.warning(f"DB prune error: {e}")
                # Daily trades parquet snapshot for disaster recovery + analytics
                # (added 2026-05-17). Idempotent within the same UTC day.
                try:
                    _trade_dump_dir = os.path.join(
                        os.path.dirname(os.path.abspath(__file__)),
                        "data", "trade_history",
                    )
                    n, p = await dump_trades_to_parquet(_trade_dump_dir)
                    logger.info(f"Daily trades parquet: {n} rows -> {p}")
                except Exception as e:
                    logger.warning(f"Trades parquet dump error: {e}")

            # Fetch market data once for all agents (fluid watchlist ranked by projected return)
            market_context = await market_data_service.get_market_context(
                watchlist_manager.get_active_watchlist()
            )
            prices = {sym: ctx.get("price", 0) for sym, ctx in market_context.items() if isinstance(ctx, dict)}

            # Augment context with fresh scanner recommendations so every agent
            # can apply its own strategy to scanner-identified symbols
            try:
                from agents.scanner_agent import get_cached_scan
                scan = get_cached_scan(require_fresh=True)
                if scan and scan.get("status") == "ok":
                    scanner_syms = [
                        r["symbol"] for r in scan.get("recommendations", [])
                        if r["symbol"] not in market_context
                    ]
                    if scanner_syms:
                        scanner_ctx = await market_data_service.get_market_context(scanner_syms)
                        market_context.update(scanner_ctx)
                        prices.update({s: c.get("price", 0) for s, c in scanner_ctx.items() if isinstance(c, dict)})
                        logger.info(f"Scanner: added {len(scanner_syms)} symbols to market context: {scanner_syms}")
            except Exception as e:
                logger.warning(f"Could not augment market context with scanner symbols: {e}")

            # Inject each agent's retained picks so they always get fresh data
            # for symbols they have conviction on, even after scanner cache expires.
            try:
                pick_syms = set()
                for agent in app_state.agents.values():
                    for sym in agent.get_pick_symbols():
                        if sym not in market_context:
                            pick_syms.add(sym)
                if pick_syms:
                    picks_ctx = await market_data_service.get_market_context(list(pick_syms))
                    market_context.update(picks_ctx)
                    prices.update({s: c.get("price", 0) for s, c in picks_ctx.items() if isinstance(c, dict)})
                    logger.info(f"Agent picks: added {len(pick_syms)} retained symbols to context: {sorted(pick_syms)}")
            except Exception as e:
                logger.warning(f"Could not augment market context with agent picks: {e}")

            # Inject overnight sentinel catalysts so agents see what happened after hours
            if app_state.after_hours_catalysts:
                market_context["__overnight_catalysts__"] = app_state.after_hours_catalysts

            # Inject macro sector rotation context (15-min cache; Murphy + Bridgewater framework)
            # Refresh every 15 cycles (~15 min at 60s interval); also on first cycle
            if app_state.cycle_count % 15 == 1:
                try:
                    macro_text = await get_macro_context_text()
                    if macro_text:
                        market_context["__macro_context__"] = macro_text
                        logger.debug("MacroContext: injected into market_context")
                except Exception as _me:
                    logger.warning(f"MacroContext injection failed: {_me}")
            elif "__macro_context__" not in market_context and app_state.last_market_context:
                # Carry forward cached macro context from previous cycle
                prev = app_state.last_market_context.get("__macro_context__", "")
                if prev:
                    market_context["__macro_context__"] = prev

            # Fetch Gemini market view (rate-limited 2/hr) and inject as context
            if app_state.gemini_news_agent:
                try:
                    watchlist = [s for s in market_context if isinstance(market_context[s], dict)]
                    gemini_view = await app_state.gemini_news_agent.get_market_view(
                        market_context, watchlist
                    )
                    if gemini_view:
                        market_context["__gemini_market_view__"] = gemini_view
                        logger.debug(f"Gemini market view injected: {gemini_view[:80]}")
                except Exception as e:
                    logger.warning(f"Gemini news fetch failed: {e}")

            app_state.last_prices = prices
            app_state.last_market_context = market_context

            # Update news-price correlation snapshots with live prices
            await _update_news_price_snapshots(prices)

            # Filter out agents that are ensemble (it runs sub-agents internally)
            # Run all agents concurrently (excluding ensemble's sub-agents which it runs itself)
            non_ensemble_agents = [
                agent for name, agent in app_state.agents.items()
                if name != "EnsembleAgent"
            ]
            ensemble_agent = app_state.agents.get("EnsembleAgent")

            # Run non-ensemble agents first (ensemble uses them internally)
            agent_tasks = [
                run_agent_cycle(agent, market_context, prices)
                for agent in non_ensemble_agents
            ]

            # Also run ensemble
            if ensemble_agent:
                agent_tasks.append(run_agent_cycle(ensemble_agent, market_context, prices))

            await asyncio.gather(*agent_tasks, return_exceptions=True)

            # Collect per-symbol agent signals and inject into signal_history
            # (enables CNN training with agent consensus features)
            try:
                # Build {symbol: {agent_name: (action, confidence)}} from all non-ensemble agents
                sym_agent_sigs: Dict[str, Dict[str, tuple]] = {}
                for agent in non_ensemble_agents:
                    if agent.name in ("EnsembleAgent", "GeminiAgent"):
                        continue
                    for sym, sig in (agent._last_signals or {}).items():
                        if not isinstance(market_context.get(sym), dict):
                            continue
                        if sym not in sym_agent_sigs:
                            sym_agent_sigs[sym] = {}
                        sym_agent_sigs[sym][agent.name] = (sig.action, sig.confidence)

                if sym_agent_sigs:
                    # Refresh agent performance scores from DB (rate-limited to every 5 min)
                    await agent_performance_tracker.get_scores()

                    for sym, sigs in sym_agent_sigs.items():
                        consensus = agent_performance_tracker.consensus_score(sigs)
                        agreement = agent_performance_tracker.agreement_fraction(sigs)
                        asyncio.create_task(
                            signal_history.record_agent_signals(sym, consensus, agreement)
                        )
                        asyncio.create_task(
                            signal_history.update_top_agent_correct(sym, prices.get(sym, 0))
                        )

                    # Make current agent signals available to CNNReasoningAgent next cycle
                    market_context["__agent_signals__"] = sym_agent_sigs
            except Exception as _exc:
                logger.warning(f"Agent signal recording failed: {_exc}")

            # Save performance snapshots
            await save_performance_snapshots(prices)

            # Check for performance drift every 10 cycles
            if app_state.cycle_count % 10 == 0:
                drift_reports = check_all_agents(app_state.agents)
                drifting = [r for r in drift_reports if r["is_drifting"]]
                if drifting:
                    for r in drifting:
                        logger.warning(f"DRIFT [{r['agent_name']}]: {' | '.join(r['alerts'])}")
                else:
                    logger.info("Drift check passed — all agents performing within baseline")

            cycle_time = time.time() - cycle_start
            logger.info(f"Cycle {app_state.cycle_count} completed in {cycle_time:.2f}s")

            # Wait for next interval
            wait_time = max(0, config.TRADE_INTERVAL_SECONDS - cycle_time)
            await asyncio.sleep(wait_time)

        except asyncio.CancelledError:
            logger.info("Trading loop cancelled")
            break
        except Exception as e:
            logger.error(f"Trading loop error: {e}", exc_info=True)
            await asyncio.sleep(10)  # backoff on error

    logger.info("Trading loop stopped")
    _write_crash("[trading_loop] exited normally")


# ─── Auto-Scan Loop ───────────────────────────────────────────────────────────

def _et_now() -> datetime:
    """
    Return the current time as a timezone-aware datetime in US Eastern Time (EST/EDT).
    DST is computed from first principles — no pytz or tzdata required.

    US DST rule:
      EDT (UTC-4): 2nd Sunday of March at 02:00 local → 1st Sunday of November at 02:00 local
      EST (UTC-5): all other times
    """
    from datetime import timezone, timedelta

    utc_now = datetime.now(timezone.utc)

    def _nth_weekday(year: int, month: int, weekday: int, n: int) -> datetime:
        """Return the nth occurrence (1-based) of weekday (Mon=0…Sun=6) in the given month."""
        first = datetime(year, month, 1, tzinfo=timezone.utc)
        delta = (weekday - first.weekday()) % 7
        return first + timedelta(days=delta + (n - 1) * 7)

    y = utc_now.year
    # 2nd Sunday of March 02:00 EST = 07:00 UTC
    dst_start = _nth_weekday(y, 3, 6, 2).replace(hour=7)
    # 1st Sunday of November 02:00 EDT = 06:00 UTC
    dst_end   = _nth_weekday(y, 11, 6, 1).replace(hour=6)

    offset = timedelta(hours=-4) if dst_start <= utc_now < dst_end else timedelta(hours=-5)
    return utc_now.astimezone(timezone(offset))


def _nyse_holidays(year: int) -> set:
    """
    Return the set of (month, day) NYSE holidays for the given year.
    All floating holidays are computed exactly — no hardcoded dates.

    Holiday schedule:
      New Year's Day     — Jan 1 (observed Mon if Sun, Fri if Sat)
      MLK Day            — 3rd Monday of January
      Presidents Day     — 3rd Monday of February
      Good Friday        — Easter Sunday minus 2 days
      Memorial Day       — last Monday of May
      Juneteenth         — Jun 19 (observed Mon if Sun, Fri if Sat)
      Independence Day   — Jul 4  (observed Mon if Sun, Fri if Sat)
      Labor Day          — 1st Monday of September
      Thanksgiving       — 4th Thursday of November
      Christmas          — Dec 25 (observed Mon if Sun, Fri if Sat)
    """
    from datetime import timedelta

    def _nth_weekday(month: int, weekday: int, n: int) -> tuple:
        first = datetime(year, month, 1)
        delta = (weekday - first.weekday()) % 7
        d = first + timedelta(days=delta + (n - 1) * 7)
        return (d.month, d.day)

    def _last_weekday(month: int, weekday: int) -> tuple:
        """Last occurrence of weekday in month."""
        # Start from end of month and walk back
        import calendar
        last_day = calendar.monthrange(year, month)[1]
        d = datetime(year, month, last_day)
        delta = (d.weekday() - weekday) % 7
        d -= timedelta(days=delta)
        return (d.month, d.day)

    def _observed(month: int, day: int) -> tuple:
        """NYSE observance rule: if holiday falls on Sat → Fri; Sun → Mon."""
        d = datetime(year, month, day)
        if d.weekday() == 5:   # Saturday → Friday
            d -= timedelta(days=1)
        elif d.weekday() == 6: # Sunday → Monday
            d += timedelta(days=1)
        return (d.month, d.day)

    def _easter(y: int) -> datetime:
        """Anonymous Gregorian algorithm for Easter Sunday."""
        a = y % 19
        b, c = divmod(y, 100)
        d, e = divmod(b, 4)
        f = (b + 8) // 25
        g = (b - f + 1) // 3
        h = (19 * a + b - d - g + 15) % 30
        i, k = divmod(c, 4)
        l = (32 + 2 * e + 2 * i - h - k) % 7
        m = (a + 11 * h + 22 * l) // 451
        month = (h + l - 7 * m + 114) // 31
        day   = (h + l - 7 * m + 114) % 31 + 1
        return datetime(y, month, day)

    easter = _easter(year)
    good_friday = easter - timedelta(days=2)

    return {
        _observed(1, 1),                        # New Year's Day
        _nth_weekday(1, 0, 3),                  # MLK Day (3rd Mon Jan)
        _nth_weekday(2, 0, 3),                  # Presidents Day (3rd Mon Feb)
        (good_friday.month, good_friday.day),   # Good Friday
        _last_weekday(5, 0),                    # Memorial Day (last Mon May)
        _observed(6, 19),                       # Juneteenth
        _observed(7, 4),                        # Independence Day
        _nth_weekday(9, 0, 1),                  # Labor Day (1st Mon Sep)
        _nth_weekday(11, 3, 4),                 # Thanksgiving (4th Thu Nov)
        _observed(12, 25),                      # Christmas
    }


def _get_market_status() -> str:
    """
    Return 'open' during regular NYSE hours (09:30–15:59 ET on trading days),
    'closed' at all other times.
    """
    now = _et_now()
    if now.weekday() >= 5:
        return "closed"
    if (now.month, now.day) in _nyse_holidays(now.year):
        return "closed"
    h, m = now.hour, now.minute
    if (h == 9 and m >= 30) or (10 <= h <= 15):
        return "open"
    return "closed"


def _market_is_open() -> bool:
    """Return True only during regular NYSE trading hours."""
    return _get_market_status() == "open"


def _detect_close_transition(prev_status: str, current_status: str) -> bool:
    """Return True when the market has just transitioned from open to closed."""
    return "open" in prev_status and current_status == "closed"


def _minutes_until_open() -> float:
    """
    Minutes until the next regular market open (09:30 ET on the next trading day).
    Returns 0 if the market is currently open.
    """
    from datetime import timedelta
    if _market_is_open():
        return 0
    now = _et_now()
    for days_ahead in range(8):
        candidate = now + timedelta(days=days_ahead)
        if candidate.weekday() >= 5:
            continue
        if (candidate.month, candidate.day) in _nyse_holidays(candidate.year):
            continue
        opens = candidate.replace(hour=9, minute=30, second=0, microsecond=0)
        if opens > now:
            return (opens - now).total_seconds() / 60
    return 0


async def auto_scan_loop() -> None:
    """
    Automatically trigger the stock scanner at smart intervals.

    Schedule:
      • Run once immediately on start (if no fresh cached scan exists).
      • During market hours: every AUTO_SCAN_INTERVAL_MIN minutes.
      • Pre-market warm-up: run 10 minutes before open so results are ready at the bell.
      • Outside market hours: sleep until 10 min before next open — no wasted API calls.
      • Never runs while a scan is already in progress.
    """
    from agents.scanner_agent import run_scan, get_cached_scan, is_scan_in_progress

    OLLAMA_SCAN_INTERVAL_MIN  = 5    # scan every 5 min during market hours (Ollama-only)
    STANDARD_SCAN_INTERVAL_MIN = 30  # scan every 30 min during market hours (cloud)
    PRE_MARKET_WARMUP_MIN     = 10   # run N minutes before open
    POLL_SLEEP_SEC             = 60  # how often to wake up and check the schedule

    logger.info("Auto-scan loop started")

    async def _do_scan(reason: str) -> None:
        if is_scan_in_progress():
            logger.info(f"Auto-scan: skipping ({reason}) — scan already in progress")
            return
        logger.info(f"Auto-scan: triggering scan ({reason})")
        try:
            result = await run_scan()
            if result:
                watchlist_manager.update_from_scan(result)
        except Exception as e:
            logger.error(f"Auto-scan error: {e}")

    # Run once at startup if cache is missing or stale — but only during market
    # hours or the pre-market warmup window to avoid expensive off-hours scans.
    cached = get_cached_scan(require_fresh=True)
    if not cached and (_market_is_open() or _minutes_until_open() <= PRE_MARKET_WARMUP_MIN):
        await _do_scan("startup — no fresh cache")

    last_scan_triggered: float = time.time()

    while app_state.is_running:
        try:
            await asyncio.sleep(POLL_SLEEP_SEC)

            if not app_state.is_running:
                break

            now_ts = time.time()
            elapsed_min = (now_ts - last_scan_triggered) / 60

            interval_min = (
                OLLAMA_SCAN_INTERVAL_MIN
                if os.environ.get("OLLAMA_ONLY_MODE") == "1"
                else STANDARD_SCAN_INTERVAL_MIN
            )

            session = _get_market_status()
            if session == "open":
                # Regular interval scan during market hours
                if elapsed_min >= interval_min:
                    await _do_scan(f"scheduled every {interval_min} min")
                    last_scan_triggered = now_ts
            else:
                # Market closed
                mins_to_open = _minutes_until_open()
                if 0 < mins_to_open <= PRE_MARKET_WARMUP_MIN:
                    # Pre-open warmup window: scan so agents have fresh picks at open
                    if elapsed_min >= interval_min:
                        await _do_scan(
                            f"pre-open warmup ({mins_to_open:.0f} min before 9:30 AM)"
                        )
                        last_scan_triggered = now_ts
                elif os.environ.get("OLLAMA_ONLY_MODE") == "1":
                    # Ollama is free/local — keep scanning after hours so the model
                    # processes overnight news and has updated picks ready at open.
                    if elapsed_min >= OLLAMA_CLOSED_SCAN_MIN:
                        await _do_scan("off-hours Ollama scan (free, local)")
                        last_scan_triggered = now_ts

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Auto-scan loop error: {e}", exc_info=True)
            await asyncio.sleep(30)

    logger.info("Auto-scan loop stopped")


# ─── After-Hours News & Policy Sentinel ───────────────────────────────────────

def _sentinel_log_catalysts(
    catalysts: list,
    max_standard: int,
    max_policy: int,
    trigger: int,
) -> None:
    """
    Log sentinel detection results at the appropriate level.

    - WARNING: at least one score meets or exceeds the trigger threshold (actionable).
    - INFO:    catalysts found but none scored high enough to trigger a scan (noise).
    - Silent:  no catalysts detected.
    """
    if not catalysts:
        return
    combined_max = max(max_standard, max_policy)
    if combined_max >= trigger:
        logger.warning(
            f"Sentinel: {len(catalysts)} catalyst(s) detected — "
            f"score={combined_max} meets trigger ({trigger}). "
            f"Top: {catalysts[0]['headline'][:100]}"
        )
    else:
        logger.info(
            f"Sentinel: {len(catalysts)} low-score item(s) found "
            f"(max standard={max_standard}, policy={max_policy}) — "
            f"below trigger threshold ({trigger}), no scan triggered."
        )


async def news_sentinel_loop() -> None:
    """
    After-hours sentinel that monitors news for major market catalysts
    (earnings, M&A, FDA, Fed decisions, congressional laws, executive orders).

    Behaviour:
      • Sleeps while the market is open (trading loop handles intraday analysis).
      • Every SENTINEL_POLL_MIN minutes after hours, fetches news for the watchlist
        and broad-market proxies.
      • Scores headlines using two engines:
          1. Standard catalyst scoring (earnings, M&A, FDA, upgrades…)
          2. Policy monitor (congressional laws, executive orders, tariffs, Fed…)
      • If combined score ≥ TRIGGER_SCORE, triggers a fresh scanner run so agents
        have up-to-date picks ready at the next open.
      • Stores detected catalysts in app_state.after_hours_catalysts for the API.
    """
    from agents.scanner_agent import run_scan, is_scan_in_progress
    from data.policy_monitor import scan_policy_news

    SENTINEL_POLL_MIN    = 15   # poll every 15 min after hours
    TRIGGER_SCORE        = 3   # combined keyword score to trigger a scan (raised from 2 — prevents
                               # single low-weight headlines like RSS policy items from repeatedly
                               # triggering expensive Ollama scans every 15 min after restarts)
    SCAN_COOLDOWN_SECS   = 3600  # sentinel-triggered scans at most once per hour

    # Standard catalyst keyword scores (non-policy)
    _CATALYST_KEYWORDS = [
        ("earnings beat", 3), ("earnings miss", 3), ("eps beat", 3), ("eps miss", 3),
        ("raised guidance", 3), ("lowered guidance", 3), ("merger", 3), ("acquisition", 3),
        ("buyout", 3), ("takeover", 3), ("fda approval", 4), ("fda rejection", 4),
        ("clinical trial", 2), ("phase 3", 2), ("bankruptcy", 4), ("chapter 11", 4),
        ("dividend cut", 3), ("dividend increase", 2), ("stock split", 2),
        ("buyback", 2), ("layoffs", 2), ("ceo resign", 3), ("ceo fired", 3),
        ("upgrade", 2), ("downgrade", 2), ("price target raised", 2), ("price target cut", 2),
        ("revenue beat", 2), ("revenue miss", 2), ("profit warning", 3),
        ("data breach", 2), ("lawsuit", 1), ("recall", 2),
    ]

    def _score_standard(headline: str, summary: str = "") -> int:
        text = (headline + " " + summary).lower()
        return sum(pts for kw, pts in _CATALYST_KEYWORDS if kw in text)

    logger.info("News sentinel loop started")
    last_poll: float = 0.0
    last_sentinel_scan: float = 0.0   # timestamp of last sentinel-triggered scan

    while app_state.is_running:
        try:
            await asyncio.sleep(60)   # check every minute whether to poll

            if not app_state.is_running:
                break

            # Poll interval: every 15 min when closed, every 5 min during market hours
            market_open = _get_market_status() == "open" or app_state.force_trading
            SENTINEL_POLL_MIN = 5 if market_open else 15

            now_ts = time.time()
            elapsed_min = (now_ts - last_poll) / 60
            if elapsed_min < SENTINEL_POLL_MIN:
                continue

            last_poll = now_ts
            app_state.last_sentinel_poll = datetime.utcnow().isoformat() + "Z"
            logger.info("Sentinel: polling news for after-hours catalysts")

            # Gather watchlist + current scanner symbols
            watchlist_syms = list(config.WATCHLIST)
            try:
                from agents.scanner_agent import get_cached_scan
                scan = get_cached_scan()
                if scan and scan.get("status") == "ok":
                    for rec in scan.get("recommendations", []):
                        sym = rec.get("symbol")
                        if sym and sym not in watchlist_syms:
                            watchlist_syms.append(sym)
            except Exception:
                pass

            # Run standard catalyst scan (Alpaca news)
            from data.news_service import news_service
            from data.sentinel_sources import fetch_all_sources
            try:
                news_map = await news_service.get_news_multi(watchlist_syms)
            except Exception as e:
                logger.warning(f"Sentinel: news fetch failed: {e}")
                continue

            new_catalysts: List[Dict] = []
            seen = set()
            max_standard_score = 0

            for sym, articles in news_map.items():
                for art in articles:
                    headline = art.get("headline", "")
                    if not headline or headline in seen:
                        continue
                    seen.add(headline)
                    score = _score_standard(headline, art.get("summary", ""))
                    if score >= TRIGGER_SCORE:
                        max_standard_score = max(max_standard_score, score)
                        new_catalysts.append({
                            "headline":    headline,
                            "summary":     art.get("summary", "")[:200],
                            "source":      art.get("source", ""),
                            "date":        art.get("date", ""),
                            "symbol":      sym,
                            "score":       score,
                            "category":    "catalyst",
                            "sectors":     [],
                            "reason":      "earnings/M&A/FDA/upgrade keyword match",
                            "detected_at": datetime.utcnow().isoformat() + "Z",
                        })

            # Run policy / congressional / executive order scan
            try:
                policy_catalysts = await scan_policy_news(watchlist_syms, lookback_hours=12)
                new_catalysts.extend(policy_catalysts)
                max_policy_score = max((c["score"] for c in policy_catalysts), default=0)
            except Exception as e:
                logger.warning(f"Sentinel: policy monitor failed: {e}")
                max_policy_score = 0

            # Run additional sources: RSS, Yahoo Finance, EDGAR 8-K, Finnhub, Unusual Whales
            try:
                extra_catalysts = await fetch_all_sources(watchlist_syms)
                # Merge — deduplicate against headlines already collected
                existing_headlines = {c["headline"] for c in new_catalysts}
                added = 0
                for cat in extra_catalysts:
                    if cat["headline"] not in existing_headlines:
                        new_catalysts.append(cat)
                        existing_headlines.add(cat["headline"])
                        added += 1
                if added:
                    logger.info(f"Sentinel: +{added} catalysts from additional sources")
            except Exception as e:
                logger.warning(f"Sentinel: additional sources failed: {e}")

            # Deduplicate and persist — also checks news_price_snapshots (DB-restored)
            # to prevent re-adding catalysts seen in prior sessions after a restart
            await _record_catalysts(new_catalysts)

            # Log notable finds
            _sentinel_log_catalysts(
                new_catalysts, max_standard_score, max_policy_score, TRIGGER_SCORE
            )

            # Trigger scanner if any catalyst exceeds threshold — but at most once per hour.
            # Cooldown prevents a single persistent RSS headline from triggering a full
            # Ollama scan every 15 minutes and causing memory pressure / process crashes.
            combined_max = max(max_standard_score, max_policy_score)
            secs_since_last = now_ts - last_sentinel_scan
            if (combined_max >= TRIGGER_SCORE
                    and not is_scan_in_progress()
                    and secs_since_last >= SCAN_COOLDOWN_SECS):
                logger.warning(
                    f"Sentinel: triggering scanner — catalyst score={combined_max} "
                    f"(threshold={TRIGGER_SCORE})"
                )
                last_sentinel_scan = now_ts
                try:
                    result = await run_scan()
                    if result:
                        watchlist_manager.update_from_scan(result)
                except Exception as e:
                    logger.error(f"Sentinel: scanner run failed: {e}")
            elif combined_max >= TRIGGER_SCORE and secs_since_last < SCAN_COOLDOWN_SECS:
                mins_remaining = int((SCAN_COOLDOWN_SECS - secs_since_last) / 60)
                logger.info(
                    f"Sentinel: catalyst score={combined_max} meets threshold but scan "
                    f"cooldown active — next scan in {mins_remaining} min"
                )

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Sentinel loop error: {e}", exc_info=True)
            await asyncio.sleep(60)

    logger.info("News sentinel loop stopped")


async def _refresh_summary(prices: Dict[str, float], market_status: str) -> None:
    """Background task: regenerate the daily summary without blocking the trading loop."""
    try:
        from agents.scanner_agent import get_cached_scan
        scan = get_cached_scan()
        scanner_recs = (scan.get("recommendations", []) if scan else [])
        await daily_summary.generate(
            agents=app_state.agents,
            prices=prices,
            market_status=market_status,
            scanner_recs=scanner_recs,
            sentinel_catalysts=app_state.after_hours_catalysts,
        )
    except Exception as e:
        logger.warning(f"Summary refresh failed: {e}")


async def run_agent_cycle(agent, market_context: Dict, prices: Dict[str, float]) -> None:
    """Run one trading cycle for a single agent."""
    if not agent._is_active:
        return

    try:
        # Record trade history before cycle
        trades_before = set(id(t) for t in agent.portfolio.trade_history)
        positions_before = set(agent.portfolio.positions.keys())

        signals = await agent.run_cycle(market_context, prices)

        # Persist new trades
        new_trades = [t for t in agent.portfolio.trade_history if id(t) not in trades_before]
        for trade in new_trades:
            await save_trade(
                agent_id=agent.agent_id,
                symbol=trade.symbol,
                action=trade.action,
                shares=trade.shares,
                price=trade.price,
                reasoning=trade.reasoning[:500],
                pnl=trade.pnl,
            )
            try:
                record_risk_trade(agent.name, trade.symbol, trade.action)
            except Exception:
                pass

        # Delete positions that were fully closed this cycle
        positions_after = set(agent.portfolio.positions.keys())
        for sym in positions_before - positions_after:
            await upsert_portfolio_position(
                agent_id=agent.agent_id,
                symbol=sym,
                shares=0,
                avg_cost=0,
                current_value=0,
                unrealized_pnl=0,
            )

        # Update remaining open positions in DB
        for sym, pos in agent.portfolio.positions.items():
            price = prices.get(sym, pos.avg_cost)
            await upsert_portfolio_position(
                agent_id=agent.agent_id,
                symbol=sym,
                shares=pos.shares,
                avg_cost=pos.avg_cost,
                current_value=pos.current_value(price),
                unrealized_pnl=pos.unrealized_pnl(price),
                last_price=price if sym in prices else 0.0,
                entry_confidence=pos.entry_confidence,
            )

    except Exception as e:
        logger.error(f"Error in agent cycle for {agent.name}: {e}", exc_info=True)


async def save_performance_snapshots(prices: Dict[str, float]) -> None:
    """Save performance snapshot for all agents.

    Aggregates per-agent outcomes so a silent total failure becomes loud:
    - all-agent failure → CRITICAL (e.g., DB unreachable for an entire cycle)
    - partial failure   → WARNING summary
    - all success       → silent (default debug only)
    """
    successes = 0
    failures = 0
    for agent in app_state.agents.values():
        try:
            metrics = agent.get_performance_metrics(prices)
            await save_performance(
                agent_id=agent.agent_id,
                total_value=metrics["total_value"],
                cash=metrics["cash"],
                total_return_pct=metrics["total_return_pct"],
                sharpe_ratio=metrics["sharpe_ratio"],
                win_rate=metrics["win_rate"],
            )
            successes += 1
        except Exception as e:
            logger.error(f"Error saving performance for {agent.name}: {e}")
            failures += 1

    if failures and successes == 0:
        logger.critical(
            f"Performance snapshot save FAILED for ALL {failures} agents this cycle. "
            f"No DB rows persisted — leaderboard/history will go stale until fixed."
        )
    elif failures:
        logger.warning(
            f"Performance snapshot: {successes} saved, {failures} failed"
        )


# ─── WebSocket Broadcast ──────────────────────────────────────────────────────

async def ws_broadcast_loop() -> None:
    """Broadcast real-time updates to all connected WebSocket clients."""
    while True:
        try:
            if app_state.ws_connections and app_state.last_prices:
                message = await build_ws_message()
                dead_connections = set()

                for ws in app_state.ws_connections.copy():
                    try:
                        await ws.send_text(_json_dumps(message))
                    except Exception:
                        dead_connections.add(ws)

                app_state.ws_connections -= dead_connections

            await asyncio.sleep(config.WS_UPDATE_INTERVAL)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"WebSocket broadcast error: {e}")
            await asyncio.sleep(1)


async def build_ws_message() -> Dict:
    """Build the WebSocket update message."""
    prices = app_state.last_prices or {}

    # Get agent states
    agents_state = []
    for agent in app_state.agents.values():
        try:
            state = agent.get_state(prices)
            agents_state.append(state)
        except Exception as e:
            logger.error(f"Error getting state for {agent.name}: {e}")

    # Build leaderboard
    leaderboard = sorted(
        agents_state,
        key=lambda a: a.get("total_return_pct", 0),
        reverse=True,
    )
    for rank, entry in enumerate(leaderboard, 1):
        entry["rank"] = rank

    # Build live summary data (no Claude API call — safe to call every 5 s)
    summary_live = None
    try:
        from agents.scanner_agent import get_cached_scan
        scan = get_cached_scan()
        scanner_recs = scan.get("recommendations", []) if scan else []
        summary_live = daily_summary.get_live_data(
            agents=app_state.agents,
            prices=prices,
            market_status=app_state.market_status,
            scanner_recs=scanner_recs,
            sentinel_catalysts=app_state.after_hours_catalysts,
        )
    except Exception as e:
        logger.debug(f"build_ws_message: summary_live failed: {e}")

    # Build 1-day change % per symbol from market context stats
    price_changes: Dict[str, float] = {}
    for sym, ctx in app_state.last_market_context.items():
        if isinstance(ctx, dict):
            pct = ctx.get("stats", {}).get("price_change_1d")
            if pct is not None:
                price_changes[sym] = round(pct, 2)

    return {
        "type": "update",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "is_running": app_state.is_running,
        "cycle_count": app_state.cycle_count,
        "agents": agents_state,
        "prices": prices,
        "price_changes": price_changes,
        "leaderboard": leaderboard,
        "watchlist": watchlist_manager.get_active_watchlist(),
        "summary_live": summary_live,
    }




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

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Real-time WebSocket endpoint for live updates."""
    # Authenticate before accepting the connection.
    # The session cookie is forwarded by the Vite proxy on WS upgrade.
    if auth.is_enabled():
        token = websocket.cookies.get(auth.SESSION_COOKIE)
        if not token or not auth.validate_session(token):
            await websocket.close(code=1008)  # 1008 = Policy Violation
            return

    await websocket.accept()
    app_state.ws_connections.add(websocket)
    client = websocket.client
    logger.info(f"WebSocket connected: {client}")

    try:
        # Send initial state immediately
        if app_state.last_prices or app_state.agents:
            try:
                initial_message = await build_ws_message()
                await websocket.send_text(_json_dumps(initial_message))
            except Exception as e:
                logger.error(f"WebSocket: failed to send initial state: {e}", exc_info=True)

        # Keep connection alive
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                # Handle ping/pong
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                # Send heartbeat
                await websocket.send_text(json.dumps({"type": "heartbeat", "timestamp": datetime.utcnow().isoformat() + "Z"}))

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {client}")
    except Exception as e:
        logger.error(f"WebSocket error for {client}: {e}")
    finally:
        app_state.ws_connections.discard(websocket)


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
