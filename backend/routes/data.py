"""Read endpoints for portfolio / market / sentinel / signals / picks / backfill.

These are all "data" endpoints — they read from app_state, the DB, or the
market data service. No mutations to the trading loop.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

data_router = APIRouter()


@data_router.get("/api/agents")
async def get_agents():
    """Get all agents with their current state."""
    import main
    from data.market_data import market_data_service

    app_state = main.app_state
    _config = main.config

    prices = app_state.last_prices or {}

    if not prices and _config.ALPACA_API_KEY:
        try:
            prices = await market_data_service.get_latest_prices(_config.WATCHLIST)
            app_state.last_prices = prices
        except Exception:
            pass

    agents_state = []
    for agent in app_state.agents.values():
        try:
            state = agent.get_state(prices)
            agents_state.append(state)
        except Exception as e:
            main.logger.error(f"Error getting agent state for {agent.name}: {e}")

    return {"agents": agents_state, "count": len(agents_state)}


@data_router.get("/api/leaderboard")
async def get_leaderboard():
    """Get agents sorted by performance."""
    import main
    app_state = main.app_state

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
            main.logger.error(f"Error getting leaderboard for {agent.name}: {e}")

    leaderboard.sort(key=lambda x: x["total_return_pct"], reverse=True)
    for rank, entry in enumerate(leaderboard, 1):
        entry["rank"] = rank

    return {"leaderboard": leaderboard}


@data_router.get("/api/trades")
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
    import main
    trades = await main.get_agent_trades(agent_id=agent_id, limit=limit)
    return {"trades": trades, "count": len(trades)}


@data_router.get("/api/market")
async def get_market():
    """Get current market prices and info for watchlist."""
    import main
    from data.market_data import market_data_service

    app_state = main.app_state

    try:
        if app_state.last_prices and (time.time() - getattr(app_state, '_last_market_fetch', 0) < 10):
            prices = app_state.last_prices
        else:
            active_wl = main.watchlist_manager.get_active_watchlist()
            prices = await market_data_service.get_latest_prices(active_wl)
            app_state.last_prices = prices
            app_state._last_market_fetch = time.time()

        return {
            "prices": prices,
            "watchlist": main.watchlist_manager.get_active_watchlist(),
            "timestamp": main.datetime.utcnow().isoformat() + "Z",
        }
    except Exception as e:
        main.logger.error(f"Error fetching market data: {e}")
        raise HTTPException(status_code=503, detail="Market data temporarily unavailable")


@data_router.get("/api/performance/{agent_name}")
async def get_agent_performance(agent_name: str):
    """Get performance history for a specific agent."""
    import main
    agent = main.app_state.agents.get(agent_name)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    history = []
    if agent.agent_id:
        history = await main.get_performance_history(agent.agent_id)

    # Also return in-memory value history for smoother charting
    value_history = agent.portfolio.get_value_history()

    return {
        "agent_name": agent_name,
        "db_history": history,
        "value_history": value_history,
    }


@data_router.get("/api/signals")
async def get_composite_signals():
    """Get multi-source composite signal for every watchlist symbol."""
    import main
    from data.signal_aggregator import get_composite_signal
    from data.news_service import news_service

    app_state = main.app_state
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
        active_wl = main.watchlist_manager.get_active_watchlist()
        news = await news_service.get_news_multi(active_wl)
        tasks = [get_composite_signal(sym, news.get(sym, [])) for sym in active_wl]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        signals = {sym: r for sym, r in zip(active_wl, results)
                   if not isinstance(r, Exception) and isinstance(r, dict) and r.get("verdict")}
    return {"signals": signals}


@data_router.get("/api/watchlist")
async def get_watchlist():
    """Get the current fluid watchlist with projected return scores for each symbol."""
    import main
    _config = main.config
    return {
        "watchlist": main.watchlist_manager.get_active_watchlist(),
        "scored_pool": main.watchlist_manager.scored_pool,
        "is_initialized": main.watchlist_manager.is_initialized,
        "anchors": _config.WATCHLIST_ANCHORS,
        "seeds": _config.WATCHLIST,
        "size": _config.WATCHLIST_SIZE,
    }


@data_router.get("/api/drift")
async def get_drift():
    """Check all agents for performance drift vs their historical baseline."""
    import main
    from data.drift_detector import check_all_agents

    reports = check_all_agents(main.app_state.agents)
    drifting = [r for r in reports if r["is_drifting"]]
    return {
        "reports": reports,
        "drifting_agents": len(drifting),
        "all_clear": len(drifting) == 0,
    }


@data_router.post("/api/backfill")
async def trigger_backfill(days: int = 365):
    """Seed signal-history Parquet files with historical bar data."""
    import main
    from data.history_backfill import backfill_signal_history, get_sample_counts

    symbols = main.watchlist_manager.get_active_watchlist()
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


@data_router.get("/api/backfill/status")
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


@data_router.post("/api/backfill/macro")
async def trigger_macro_backfill(days: int = 365):
    """Seed __MACRO__.parquet with historical macro environment data."""
    from data.history_backfill import backfill_macro_history
    days = max(30, min(days, 1825))
    result = await backfill_macro_history(days=days)
    return {
        "status":     "ok",
        "days":       days,
        "rows_added": result.get("rows_added", 0),
    }


@data_router.get("/api/summary")
async def get_daily_summary(force: bool = False):
    """Get the daily roll-up summary — agent decisions, consensus map, and
    Claude-authored narrative. Cached; use ?force=true to regenerate immediately.
    """
    import main
    from agents.scanner_agent import get_cached_scan
    from agents.summary_agent import daily_summary

    app_state = main.app_state
    prices = app_state.last_prices or {}
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


@data_router.get("/api/picks")
async def get_agent_picks():
    """Get each agent's current retained pick symbols and conviction data."""
    import main
    result = {}
    for name, agent in main.app_state.agents.items():
        picks = agent._picks
        if picks:
            result[name] = picks
    return {"picks": result, "total_agents_with_picks": len(result)}


@data_router.get("/api/sentinel")
async def get_sentinel_catalysts():
    """Get after-hours catalysts detected by the news and policy sentinel."""
    import main
    app_state = main.app_state
    return {
        "market_status":       app_state.market_status,
        "market_is_open":      main._market_is_open(),
        "minutes_until_open":  round(main._minutes_until_open(), 1),
        "last_poll":           app_state.last_sentinel_poll,
        "catalyst_count":      len(app_state.after_hours_catalysts),
        "catalysts":           app_state.after_hours_catalysts,
    }


@data_router.get("/api/news-impact")
async def get_news_impact():
    """Return news-price correlation snapshots — shows how catalysts moved prices."""
    import main
    snapshots = main.app_state.news_price_snapshots
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
