"""FastAPI lifespan + agent initialisation + Ollama bootstrap.

Extracted from main.py for issue #67. The lifespan async context manager,
``init_agents()``, the ``_reconcile_cash_from_trades()`` helper, and the Ollama
auto-start helpers all live here.

Test-compatibility note: all references to mutable state (`app_state`) and
patch-targeted functions (`init_db`, `cleanup_token_log`,
`prune_news_price_snapshots`, `init_agents`, `trading_loop`, `auto_scan_loop`,
`news_sentinel_loop`, `ws_broadcast_loop`, `_ensure_ollama_running`,
`dump_trades_to_parquet`) are accessed via `main.X` lookups inside functions
so that `patch("main.X", ...)` in tests continues to intercept them.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import logging
import os
import subprocess
import traceback as _traceback
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import FastAPI

import auth as auth
from config import config
from data.watchlist_manager import watchlist_manager
from data.learning_manager import record_catalyst_outcome  # noqa: F401 (kept for parity)

from trading.alpaca_client import alpaca_client
from trading.portfolio import Position, TradeRecord

from database import (
    upsert_agent,
    get_portfolio_positions,
    get_agent_trades,
    get_latest_cash,
    restore_value_history,
    get_price_snapshots,
)

logger = logging.getLogger(__name__)


# ─── Cash reconciliation helper ─────────────────────────────────────────────

def _reconcile_cash_from_trades(
    agent_name: str,
    db_trades: List[Dict],
    snapshot_cash: Optional[float],
    starting_capital: float,
) -> float:
    """Derive cash from trade-history replay (source of truth).

    The performance snapshot's cash column has historically drifted up across
    restarts (issue #64: HistoricalTrendsAgent silently accumulated $18,720.78
    of phantom cash). Replaying the trade ledger is unambiguous:

        derived_cash = starting_capital
                     - sum(BUY proceeds)
                     + sum(SELL proceeds)

    We always use ``derived_cash``. The snapshot is logged for visibility:
      * snapshot missing            -> use derived silently
      * snapshot within $1          -> log INFO ("reconciled within $1")
      * snapshot drift > $1         -> log CRITICAL with both values + drift
        (auto-repair: the drifted snapshot is discarded)
    """
    # Look up logger lazily through main so patch("main.logger") works.
    import main  # noqa: E402 (lazy import for test patchability)
    _logger = main.logger

    derived_cash = float(starting_capital)
    for t in db_trades:
        if t["action"] == "BUY":
            derived_cash -= t["shares"] * t["price"]
        elif t["action"] == "SELL":
            derived_cash += t["shares"] * t["price"]

    if snapshot_cash is None:
        # No performance snapshot yet (fresh agent, or save_performance was
        # crashing). Derived is the only signal we have — use it silently.
        return derived_cash

    drift = snapshot_cash - derived_cash
    if abs(drift) > 1.0:
        _logger.critical(
            f"{agent_name}: cash drift detected on restart — "
            f"snapshot=${snapshot_cash:,.2f} vs replay=${derived_cash:,.2f} "
            f"(drift ${drift:+,.2f}). Auto-repairing: using replay value as "
            f"source of truth (issue #64)."
        )
    else:
        _logger.info(
            f"{agent_name}: cash reconciled within $1 — "
            f"snapshot=${snapshot_cash:,.2f}, replay=${derived_cash:,.2f}"
        )
    return derived_cash


# ─── Agent Initialization ────────────────────────────────────────────────────

async def init_agents() -> None:
    """Create and register all trading agents."""
    # Late imports so that the agent classes are resolved at call time.
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
    from agents.xgb_reasoning_agent import XGBReasoningAgent

    import main  # lazy — required for test patches against main.app_state / main._write_crash

    logger.info("Initializing trading agents...")
    app_state = main.app_state

    # Create component agents
    tech = TechAgent()
    momentum = MomentumAgent()
    mean_rev = MeanReversionAgent()
    sentiment = SentimentAgent()
    claude = ClaudeAgent()
    ollama = OllamaAgent()   # 2026-05-08: extracted from ClaudeAgent so cloud + local
                             # vote independently; a local-Ollama failure can't break Claude.
    gemini = GeminiAgent()
    historical_trends = HistoricalTrendsAgent()
    # XGBReasoningAgent (renamed from CNNReasoningAgent in issue #75). The DB
    # migration v5 renames the existing agents row in place, so
    # upsert_agent("XGBReasoningAgent", ...) below finds the same row that
    # was previously named CNNReasoningAgent — trades / portfolios /
    # performance FK references stay valid across the rename.
    xgb_agent = XGBReasoningAgent()

    # Create ensemble (Gemini excluded — news/context source only, not a voter)
    ensemble = EnsembleAgent(
        tech_agent=tech,
        momentum_agent=momentum,
        mean_reversion_agent=mean_rev,
        sentiment_agent=sentiment,
        claude_agent=claude,
        xgb_reasoning_agent=xgb_agent,
        ollama_agent=ollama,
    )
    ensemble.component_agents["HistoricalTrendsAgent"] = historical_trends

    # Scanner portfolio: acts on cached scan results, no new API calls each cycle
    scanner_portfolio = ScannerPortfolioAgent()

    # Gemini is a news/context source only — not registered as a trading agent
    app_state.gemini_news_agent = gemini
    all_agents = [tech, momentum, mean_rev, sentiment, claude, ollama,
                  historical_trends, xgb_agent, ensemble, scanner_portfolio]

    # Register agents in DB and restore full portfolio state for continuity across restarts
    for agent in all_agents:
        try:
            agent_id = await upsert_agent(agent.name, agent.strategy_description)
            agent.agent_id = agent_id

            # Always restore open positions — saved independently of performance snapshots
            db_positions = await get_portfolio_positions(agent_id)
            for pos in db_positions:
                # entry_confidence: was historically dropped on restore (Backlog 0.1).
                # Now persisted in the portfolios table so Bayes early-exit retains
                # its calibration across backend restarts.
                ec = pos.get("entry_confidence")
                ec = float(ec) if ec is not None else 0.5
                agent.portfolio.positions[pos["symbol"]] = Position(
                    symbol=pos["symbol"],
                    shares=pos["shares"],
                    avg_cost=pos["avg_cost"],
                    entry_confidence=ec,
                    bayes_confidence=ec,  # bayes resets to entry on restart; will re-track from here
                )
                # Seed last_prices so first WS broadcast uses closing price, not avg_cost
                lp = pos.get("last_price", 0.0)
                if lp and lp > 0:
                    app_state.last_prices.setdefault(pos["symbol"], lp)

            # Always restore trade history for win_rate / total_trades.
            # limit=None — no cap. Previous limit=500 silently truncated
            # high-volume agents (MomentumAgent had 1,699 trades, in-memory
            # was capped at 500 → wrong total_trades and win_rate).
            db_trades = await get_agent_trades(agent_id, limit=None)
            db_trades.reverse()  # DB returns DESC; portfolio expects chronological order
            for t in db_trades:
                try:
                    agent.portfolio.trade_history.append(TradeRecord(
                        symbol=t["symbol"],
                        action=t["action"],
                        shares=t["shares"],
                        price=t["price"],
                        timestamp=main._parse_ts(t["timestamp"]),
                        reasoning=t.get("reasoning", ""),
                        pnl=t.get("pnl", 0.0),
                    ))
                except Exception as _te:
                    logger.warning(f"{agent.name}: skipping bad trade record: {_te} — row={t}")

            # Restore cash: always derive from trade-history replay (source of
            # truth). Cross-check against the last performance snapshot — when
            # they disagree by more than $1, log CRITICAL and auto-repair by
            # using the replay value (issue #64).
            snapshot_cash = await get_latest_cash(agent_id)
            derived_cash = main._reconcile_cash_from_trades(
                agent_name=agent.name,
                db_trades=db_trades,
                snapshot_cash=snapshot_cash,
                starting_capital=config.STARTING_CAPITAL,
            )
            agent.portfolio.cash = max(0.0, derived_cash)

            # Restore value history for portfolio chart
            history = await restore_value_history(agent_id)
            if history:
                agent.portfolio._value_history = history

            app_state.agents[agent.name] = agent
            logger.info(f"Registered agent: {agent.name} (id={agent_id})")
        except Exception as _agent_exc:
            import traceback as _tb_mod
            main._write_crash(f"[init_agents] CRASH restoring {agent.name}:\n{_tb_mod.format_exc()}")
            logger.error(f"Failed to restore agent {agent.name}: {_agent_exc}", exc_info=True)
            # Still register the agent with defaults so the app can start
            if not hasattr(agent, "agent_id") or agent.agent_id is None:
                try:
                    agent.agent_id = await upsert_agent(agent.name, agent.strategy_description)
                except Exception:
                    agent.agent_id = 0
            app_state.agents[agent.name] = agent

    logger.info(f"Initialized {len(all_agents)} agents")

    # ── Stock-split sweep (Backlog 0.2) ───────────────────────────────────
    # After all positions are restored from DB, detect any stock splits
    # within the last 90 days and apply proportional adjustments to held
    # positions whose avg_cost is still pre-split. Idempotent — if avg_cost
    # already matches the (split-adjusted) live price, the position is left
    # alone. Errors here must not block startup.
    try:
        from data.split_adjuster import detect_and_apply_splits
        applied = await detect_and_apply_splits(
            portfolios   = [a.portfolio for a in all_agents],
            agent_names  = [a.name      for a in all_agents],
            alpaca_client = alpaca_client,
            since_days   = 90,
        )
        if applied:
            logger.info(f"split_adjuster: applied {applied} stock-split adjustment(s) at startup")
    except Exception as _split_exc:
        logger.warning(f"split_adjuster: startup sweep failed: {_split_exc}", exc_info=True)

    # Restore news-price snapshots from DB so in-progress tracking
    # survives restarts (price_open / price_1h continue filling in)
    try:
        restored = await get_price_snapshots(limit=100)
        for snap in restored:
            # Re-parse open_recorded_at back to datetime for elapsed-time math
            raw = snap.get("open_recorded_at")
            if raw and isinstance(raw, str):
                try:
                    snap["open_recorded_at"] = _dt.datetime.fromisoformat(raw)
                except Exception:
                    snap["open_recorded_at"] = None
            snap["_db_id"] = snap.pop("id", None)
            # Only restore snapshots that still need work (price_1h not yet set)
            if snap.get("price_1h") is None:
                app_state.news_price_snapshots.append(snap)
        logger.info(f"Restored {len(app_state.news_price_snapshots)} pending price snapshots from DB")
    except Exception as _e:
        logger.warning(f"Could not restore price snapshots from DB: {_e}")

    # Seed rolling 24h token windows from DB after restart
    for _token_agent in [sentiment, claude, gemini]:
        try:
            await _token_agent.seed_from_history()
        except Exception as _e:
            logger.warning(f"seed_from_history failed for {_token_agent.name}: {_e}")


# ─── Ollama bootstrap helpers ────────────────────────────────────────────────

def _add_ollama_to_path() -> None:
    """Inject the Ollama binary directory into os.environ['PATH']."""
    import shutil
    import main  # for test patches: patch("main.config", ...)
    _config = main.config

    if shutil.which("ollama"):
        return  # already findable — nothing to inject

    candidates: list = []

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        candidates.append(os.path.join(local_app_data, "Programs", "Ollama"))

    # Also try the USERPROFILE-derived path in case LOCALAPPDATA isn't set
    user_profile = os.environ.get("USERPROFILE", "")
    if user_profile:
        candidates.append(os.path.join(user_profile, "AppData", "Local", "Programs", "Ollama"))

    if getattr(_config, "OLLAMA_PATH", ""):
        candidates.append(_config.OLLAMA_PATH)

    current_path = os.environ.get("PATH", "")
    additions = [
        d for d in candidates
        if os.path.isdir(d) and d not in current_path
    ]

    if additions:
        os.environ["PATH"] = os.pathsep.join(additions) + os.pathsep + current_path
        logger.info(f"Ollama: added to PATH → {', '.join(additions)}")


async def _pull_ollama_model() -> None:
    """Pull the configured Ollama model in the background (runs as an asyncio task)."""
    import main  # for test patches: patch("main.config", ...)
    _config = main.config

    logger.info(
        f"Ollama: pulling model '{_config.OLLAMA_MODEL}' — this may take several minutes..."
    )
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            "ollama", "pull", _config.OLLAMA_MODEL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await proc.communicate()
        except asyncio.CancelledError:
            proc.kill()
            await proc.wait()
            raise
        if proc.returncode == 0:
            logger.info(f"Ollama: model '{_config.OLLAMA_MODEL}' pulled successfully.")
        else:
            logger.warning(f"Ollama: pull failed — {stderr.decode()[:200]}")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning(f"Ollama: pull error: {e}")


async def _ensure_ollama_running() -> None:
    """Ensure the Ollama local model server is running at startup."""
    import main  # for app_state lookup AND test patches against main.config
    from agents.scanner_agent import _ollama_is_available
    _config = main.config

    # Ensure the Ollama binary is findable before any subprocess calls
    _add_ollama_to_path()

    server_was_running = await _ollama_is_available()
    if server_was_running:
        logger.info("Ollama: server already running.")
        # Still check the model — it may not have been pulled yet
        try:
            list_result = subprocess.run(
                ["ollama", "list"], capture_output=True, text=True, timeout=10
            )
            if _config.OLLAMA_MODEL not in list_result.stdout:
                logger.info(f"Ollama: model '{_config.OLLAMA_MODEL}' not found locally — pulling...")
                main.app_state.pull_task = asyncio.create_task(_pull_ollama_model())
            else:
                logger.info(f"Ollama: model '{_config.OLLAMA_MODEL}' already available.")
        except Exception as e:
            logger.debug(f"Ollama: could not check model list: {e}")
        return

    # Verify the binary exists
    try:
        result = subprocess.run(
            ["ollama", "--version"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0:
            logger.warning("Ollama: binary found but returned non-zero — skipping auto-start.")
            return
    except FileNotFoundError:
        logger.warning(
            "Ollama: not found in PATH. Install from https://ollama.com to enable "
            "zero-cost local scanning."
        )
        return
    except Exception as e:
        logger.warning(f"Ollama: could not verify installation: {e}")
        return

    # Start the server as a detached process so it outlives any parent shell
    logger.info("Ollama: starting server (ollama serve)...")
    try:
        kwargs: dict = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(["ollama", "serve"], **kwargs)
    except Exception as e:
        logger.warning(f"Ollama: failed to start server: {e}")
        return

    # Wait up to 10 s for the server to come up
    for _ in range(10):
        await asyncio.sleep(1)
        if await _ollama_is_available():
            logger.info("Ollama: server is up.")
            break
    else:
        logger.warning("Ollama: server started but did not respond within 10 s.")
        return

    # Pull the model if it hasn't been downloaded yet
    try:
        list_result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if _config.OLLAMA_MODEL not in list_result.stdout:
            logger.info(f"Ollama: model '{_config.OLLAMA_MODEL}' not found locally — pulling...")
            main.app_state.pull_task = asyncio.create_task(_pull_ollama_model())
        else:
            logger.info(f"Ollama: model '{_config.OLLAMA_MODEL}' already available.")
    except Exception as e:
        logger.debug(f"Ollama: could not check model list: {e}")


# ─── FastAPI Lifespan ────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown.

    All test-mockable functions (init_db, init_agents, cleanup_token_log,
    prune_news_price_snapshots, dump_trades_to_parquet, _ensure_ollama_running,
    ws_broadcast_loop, trading_loop, auto_scan_loop, news_sentinel_loop) are
    invoked via the `main` module so `patch("main.X", ...)` in tests works.
    """
    import main  # lazy — must be after main module is created

    # Startup
    logger.info("Starting AI Trading Competition backend...")
    main._write_crash("[LIFESPAN] startup begin")

    try:
        # Initialise authentication (no-op when APP_PASSWORD is empty)
        auth.init_auth(config.APP_PASSWORD, config.SESSION_SECRET)
        if auth.is_enabled():
            logger.info("Authentication ENABLED — password protection is active.")
        else:
            logger.warning(
                "Authentication DISABLED — set APP_PASSWORD and SESSION_SECRET in .env "
                "to restrict access."
            )

        await main.init_db()
        main._write_crash("[LIFESPAN] init_db OK")
        await main.cleanup_token_log(hours=config.TOKEN_LOG_RETENTION_DAYS * 24)
        # Performance table is intentionally NOT pruned — keep ALL trades for
        # week-over-week continuity (user policy 2026-05-16).
        await main.prune_news_price_snapshots(days=14)
        # First-of-day trades parquet snapshot — runs once at startup so a
        # fresh backup exists immediately even if the app exits before the
        # 24h cycle hook fires.
        try:
            _trade_dump_dir = os.path.join(
                os.path.dirname(os.path.abspath(main.__file__)),
                "data", "trade_history",
            )
            n, p = await main.dump_trades_to_parquet(_trade_dump_dir)
            logger.info(f"Startup trades parquet: {n} rows -> {p}")
        except Exception as _e:
            logger.warning(f"Startup trades parquet error: {_e}")
        await main.init_agents()
        main._write_crash("[LIFESPAN] init_agents OK")
    except Exception as _startup_exc:
        _tb = _traceback.format_exc()
        main._write_crash(f"[LIFESPAN] STARTUP CRASHED:\n{_tb}")
        logger.critical(f"Startup failed — see crash.log: {_startup_exc}", exc_info=True)
        raise

    # Bootstrap fluid watchlist from cached scan (if available)
    try:
        from agents.scanner_agent import get_cached_scan
        cached = get_cached_scan()
        if cached and cached.get("status") == "ok":
            watchlist_manager.update_from_scan(cached)
            logger.info("Fluid watchlist bootstrapped from cached scan.")
        else:
            logger.info("No cached scan — fluid watchlist will use seed symbols until first scan.")
    except Exception as e:
        logger.warning(f"Could not bootstrap fluid watchlist: {e}")

    # Ensure Ollama local model server is running before scans begin
    await main._ensure_ollama_running()
    main._write_crash("[LIFESPAN] Ollama check OK")

    # Start WebSocket broadcast task
    main.app_state.ws_task = asyncio.create_task(main.ws_broadcast_loop())

    # Auto-backfill signal history if the model has fewer than
    # MIN_TRAIN_SAMPLES rows. "CNN" label kept in log messages because
    # MIN_TRAIN_SAMPLES still lives in data.cnn_model — see issue #75 note
    # on keeping cnn_model.py's name (the file IS still a CNN, just
    # inactive in production).
    try:
        from data.history_backfill import backfill_signal_history, get_sample_counts
        from data.cnn_model import MIN_TRAIN_SAMPLES
        counts = await get_sample_counts()
        total  = sum(counts.values())
        if total < MIN_TRAIN_SAMPLES:
            logger.info(
                f"Signal-model training data: {total} samples (< {MIN_TRAIN_SAMPLES} minimum) — "
                f"auto-backfilling 365 days of history..."
            )
            symbols = watchlist_manager.get_active_watchlist() or config.WATCHLIST
            asyncio.create_task(backfill_signal_history(symbols, days=365))
        else:
            logger.info(f"Signal-model training data: {total} samples available — skipping auto-backfill.")
    except Exception as _bf_exc:
        logger.warning(f"Auto-backfill check failed (non-fatal): {_bf_exc}")

    # Auto-start trading, scanning, and sentinel immediately on launch
    main.app_state.is_running = True
    main.app_state.start_time = datetime.utcnow()
    main.app_state.trading_task  = asyncio.create_task(main.trading_loop())
    main.app_state.scan_task     = asyncio.create_task(main.auto_scan_loop())
    main.app_state.sentinel_task = asyncio.create_task(main.news_sentinel_loop())
    logger.info("Trading competition auto-started on launch (trading + scanner + sentinel).")

    logger.info("Backend ready. Visit http://localhost:8000/docs for API documentation.")
    main._write_crash("[LIFESPAN] startup complete — all tasks launched")
    yield

    # Shutdown
    main._write_crash("[LIFESPAN] shutdown begin")
    logger.info("Shutting down...")
    main.app_state.is_running = False

    for task in (main.app_state.trading_task, main.app_state.scan_task,
                 main.app_state.sentinel_task, main.app_state.ws_task,
                 main.app_state.pull_task):
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    await alpaca_client.close()
    logger.info("Shutdown complete")
