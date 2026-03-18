"""
FastAPI backend for the AI Trading Competition.
Manages agents, trading loop, WebSocket broadcasts, and REST API.
"""
import asyncio
import json
import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict, List, Optional, Set

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import config
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
)
from trading.portfolio import Position, TradeRecord
from data.market_data import market_data_service
from data.watchlist_manager import watchlist_manager
from trading.alpaca_client import alpaca_client

from data.drift_detector import check_all_agents
from agents.tech_agent import TechAgent
from agents.momentum_agent import MomentumAgent
from agents.mean_reversion_agent import MeanReversionAgent
from agents.sentiment_agent import SentimentAgent
from agents.claude_agent import ClaudeAgent
from agents.gemini_agent import GeminiAgent
from agents.ensemble_agent import EnsembleAgent
from agents.scanner_portfolio_agent import ScannerPortfolioAgent
from agents.summary_agent import daily_summary

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


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


# ─── Application State ──────────────────────────────────────────────────────

class AppState:
    """Global application state."""

    def __init__(self):
        self.agents: Dict[str, object] = {}
        self.is_running: bool = False
        self.trading_task: Optional[asyncio.Task] = None
        self.scan_task: Optional[asyncio.Task] = None
        self.sentinel_task: Optional[asyncio.Task] = None
        self.ws_task: Optional[asyncio.Task] = None
        self.ws_connections: Set[WebSocket] = set()
        self.last_prices: Dict[str, float] = {}
        self.last_market_context: Dict = {}
        self.cycle_count: int = 0
        self.start_time: Optional[datetime] = None
        self.market_status: str = "unknown"          # "open" | "closed"
        self._prev_market_status: str = "unknown"    # for EOD roll-up transition detection
        self.force_trading: bool = False              # bypass market-hours gate for testing
        self.after_hours_catalysts: List[Dict] = []  # catalysts found by sentinel
        self.last_sentinel_poll: Optional[str] = None  # ISO timestamp of last sentinel poll
        self.news_price_snapshots: List[Dict] = []    # price at catalyst detection + later change

    def get_agents_list(self) -> list:
        return list(self.agents.values())


app_state = AppState()


# ─── Agent Initialization ────────────────────────────────────────────────────

async def init_agents() -> None:
    """Create and register all trading agents."""
    logger.info("Initializing trading agents...")

    # Create component agents
    tech = TechAgent()
    momentum = MomentumAgent()
    mean_rev = MeanReversionAgent()
    sentiment = SentimentAgent()
    claude = ClaudeAgent()
    gemini = GeminiAgent()

    # Create ensemble with references to other agents
    ensemble = EnsembleAgent(
        tech_agent=tech,
        momentum_agent=momentum,
        mean_reversion_agent=mean_rev,
        sentiment_agent=sentiment,
        claude_agent=claude,
        gemini_agent=gemini,
    )

    # Scanner portfolio: acts on cached scan results, no new API calls each cycle
    scanner_portfolio = ScannerPortfolioAgent()

    all_agents = [tech, momentum, mean_rev, sentiment, claude, gemini, ensemble, scanner_portfolio]

    # Register agents in DB and restore full portfolio state for continuity across restarts
    for agent in all_agents:
        agent_id = await upsert_agent(agent.name, agent.strategy_description)
        agent.agent_id = agent_id

        # Restore cash balance from last performance snapshot
        cash = await get_latest_cash(agent_id)
        if cash is not None:
            agent.portfolio.cash = cash

            # Restore open positions
            db_positions = await get_portfolio_positions(agent_id)
            for pos in db_positions:
                agent.portfolio.positions[pos["symbol"]] = Position(
                    symbol=pos["symbol"],
                    shares=pos["shares"],
                    avg_cost=pos["avg_cost"],
                )

            # Restore trade history for win_rate / total_trades
            db_trades = await get_agent_trades(agent_id, limit=500)
            db_trades.reverse()  # DB returns DESC; portfolio expects chronological order
            for t in db_trades:
                agent.portfolio.trade_history.append(TradeRecord(
                    symbol=t["symbol"],
                    action=t["action"],
                    shares=t["shares"],
                    price=t["price"],
                    timestamp=datetime.fromisoformat(t["timestamp"]),
                    reasoning=t.get("reasoning", ""),
                    pnl=t.get("pnl", 0.0),
                ))

        # Restore value history for portfolio chart
        history = await restore_value_history(agent_id)
        if history:
            agent.portfolio._value_history = history

        app_state.agents[agent.name] = agent
        logger.info(f"Registered agent: {agent.name} (id={agent_id})")

    logger.info(f"Initialized {len(all_agents)} agents")


# ─── News-Price Correlation ──────────────────────────────────────────────────

def _update_news_price_snapshots(prices: Dict[str, float]) -> None:
    """Fill price_open / price_1h fields on correlation snapshots as trading progresses."""
    now_iso = datetime.utcnow().isoformat() + "Z"
    for snap in app_state.news_price_snapshots:
        sym = snap["symbol"]
        if sym not in prices:
            continue
        current = prices[sym]
        base = snap["price_at"]
        if base and base > 0:
            pct = (current - base) / base * 100
            # First cycle after detection → price_open
            if snap["price_open"] is None:
                snap["price_open"] = current
                snap["change_open"] = round(pct, 2)
            # After price_open is set, keep updating price_1h with the latest
            else:
                snap["price_1h"] = current
                snap["change_1h"] = round(pct, 2)
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

            # Fetch market data once for all agents (fluid watchlist ranked by projected return)
            market_context = await market_data_service.get_market_context(
                watchlist_manager.get_active_watchlist()
            )
            prices = {sym: ctx.get("price", 0) for sym, ctx in market_context.items()}

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
                        prices.update({s: c.get("price", 0) for s, c in scanner_ctx.items()})
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
                    prices.update({s: c.get("price", 0) for s, c in picks_ctx.items()})
                    logger.info(f"Agent picks: added {len(pick_syms)} retained symbols to context: {sorted(pick_syms)}")
            except Exception as e:
                logger.warning(f"Could not augment market context with agent picks: {e}")

            # Inject overnight sentinel catalysts so agents see what happened after hours
            if app_state.after_hours_catalysts:
                market_context["__overnight_catalysts__"] = app_state.after_hours_catalysts

            app_state.last_prices = prices
            app_state.last_market_context = market_context

            # Update news-price correlation snapshots with live prices
            _update_news_price_snapshots(prices)

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

    AUTO_SCAN_INTERVAL_MIN = 30          # scan every 30 min during market hours
    PRE_MARKET_WARMUP_MIN  = 10         # run N minutes before open
    POLL_SLEEP_SEC         = 60         # how often to wake up and check the schedule

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

    # Run once at startup if cache is missing or stale
    cached = get_cached_scan(require_fresh=True)
    if not cached:
        await _do_scan("startup — no fresh cache")

    last_scan_triggered: float = time.time()

    while app_state.is_running:
        try:
            await asyncio.sleep(POLL_SLEEP_SEC)

            if not app_state.is_running:
                break

            now_ts = time.time()
            elapsed_min = (now_ts - last_scan_triggered) / 60

            session = _get_market_status()
            if session == "open":
                # Regular interval scan during market hours
                if elapsed_min >= AUTO_SCAN_INTERVAL_MIN:
                    await _do_scan(f"scheduled every {AUTO_SCAN_INTERVAL_MIN} min")
                    last_scan_triggered = now_ts
            else:
                # Market closed: fire a warmup scan before the open
                mins_to_open = _minutes_until_open()
                if 0 < mins_to_open <= PRE_MARKET_WARMUP_MIN:
                    if elapsed_min >= AUTO_SCAN_INTERVAL_MIN:
                        await _do_scan(
                            f"pre-open warmup ({mins_to_open:.0f} min before 9:30 AM)"
                        )
                        last_scan_triggered = now_ts

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Auto-scan loop error: {e}", exc_info=True)
            await asyncio.sleep(30)

    logger.info("Auto-scan loop stopped")


# ─── After-Hours News & Policy Sentinel ───────────────────────────────────────

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

    SENTINEL_POLL_MIN = 15      # poll every 15 min after hours
    TRIGGER_SCORE     = 2       # combined keyword score to trigger a scan

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

            # Persist (keep only latest 50, deduplicate by headline)
            all_headlines = {c["headline"] for c in app_state.after_hours_catalysts}
            for cat in new_catalysts:
                if cat["headline"] not in all_headlines:
                    app_state.after_hours_catalysts.append(cat)
                    all_headlines.add(cat["headline"])
                    # Record price snapshot for news-price correlation tracking
                    sym = cat.get("symbol")
                    if sym and sym in app_state.last_prices:
                        app_state.news_price_snapshots.append({
                            "symbol":       sym,
                            "headline":     cat["headline"][:120],
                            "score":        cat.get("score", 0),
                            "category":     cat.get("category", "news"),
                            "price_at":     app_state.last_prices[sym],
                            "detected_at":  cat.get("detected_at", datetime.utcnow().isoformat() + "Z"),
                            "price_open":   None,   # filled at next market open
                            "price_1h":     None,   # filled 1h after open
                            "change_open":  None,
                            "change_1h":    None,
                        })
            # Trim to most recent 50
            app_state.after_hours_catalysts = sorted(
                app_state.after_hours_catalysts,
                key=lambda c: c.get("score", 0),
                reverse=True,
            )[:50]

            # Log notable finds
            if new_catalysts:
                logger.warning(
                    f"Sentinel: {len(new_catalysts)} catalysts detected "
                    f"(max standard={max_standard_score}, policy={max_policy_score}). "
                    f"Top: {new_catalysts[0]['headline'][:100]}"
                )

            # Trigger scanner if any catalyst exceeds threshold
            combined_max = max(max_standard_score, max_policy_score)
            if combined_max >= TRIGGER_SCORE and not is_scan_in_progress():
                logger.warning(
                    f"Sentinel: triggering scanner — catalyst score={combined_max} "
                    f"(threshold={TRIGGER_SCORE})"
                )
                try:
                    result = await run_scan()
                    if result:
                        watchlist_manager.update_from_scan(result)
                except Exception as e:
                    logger.error(f"Sentinel: scanner run failed: {e}")

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
            )

    except Exception as e:
        logger.error(f"Error in agent cycle for {agent.name}: {e}", exc_info=True)


async def save_performance_snapshots(prices: Dict[str, float]) -> None:
    """Save performance snapshot for all agents."""
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
        except Exception as e:
            logger.error(f"Error saving performance for {agent.name}: {e}")


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
                        await ws.send_text(json.dumps(message))
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

    return {
        "type": "update",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "is_running": app_state.is_running,
        "cycle_count": app_state.cycle_count,
        "agents": agents_state,
        "prices": prices,
        "leaderboard": leaderboard,
        "watchlist": watchlist_manager.get_active_watchlist(),
        "summary_live": summary_live,
    }


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    # Startup
    logger.info("Starting AI Trading Competition backend...")
    await init_db()
    await init_agents()

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

    # Start WebSocket broadcast task
    app_state.ws_task = asyncio.create_task(ws_broadcast_loop())

    # Auto-start trading, scanning, and sentinel immediately on launch
    app_state.is_running = True
    app_state.start_time = datetime.utcnow()
    app_state.trading_task  = asyncio.create_task(trading_loop())
    app_state.scan_task     = asyncio.create_task(auto_scan_loop())
    app_state.sentinel_task = asyncio.create_task(news_sentinel_loop())
    logger.info("Trading competition auto-started on launch (trading + scanner + sentinel).")

    logger.info("Backend ready. Visit http://localhost:8000/docs for API documentation.")
    yield

    # Shutdown
    logger.info("Shutting down...")
    app_state.is_running = False

    for task in (app_state.trading_task, app_state.scan_task,
                 app_state.sentinel_task, app_state.ws_task):
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    await alpaca_client.close()
    logger.info("Shutdown complete")


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
    limit: int = Query(50, ge=1, le=200),
):
    """Get recent trades, optionally filtered by agent."""
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
                await ws.send_text(json.dumps(reset_msg))
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
        signals = {sym: ctx[sym].get("composite_signal", {}) for sym in ctx if isinstance(ctx[sym], dict)}
    else:
        active_wl = watchlist_manager.get_active_watchlist()
        news = await news_service.get_news_multi(active_wl)
        tasks = [get_composite_signal(sym, news.get(sym, [])) for sym in active_wl]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        signals = {sym: r for sym, r in zip(active_wl, results)
                   if not isinstance(r, Exception)}
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


@app.post("/api/scanner/run")
async def trigger_scanner(request: Request):
    """Trigger a new agentic stock scan (or return cached result if fresh)."""
    ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(f"scanner:{ip}"):
        raise HTTPException(status_code=429, detail="Too many requests. Please wait before scanning again.")
    from agents.scanner_agent import run_scan
    try:
        result = await run_scan()
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


# ─── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Real-time WebSocket endpoint for live updates."""
    await websocket.accept()
    app_state.ws_connections.add(websocket)
    client = websocket.client
    logger.info(f"WebSocket connected: {client}")

    try:
        # Send initial state immediately
        if app_state.last_prices or app_state.agents:
            try:
                initial_message = await build_ws_message()
                await websocket.send_text(json.dumps(initial_message))
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
