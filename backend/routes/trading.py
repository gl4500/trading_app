"""Trading lifecycle endpoints: /api/start, /api/stop, /api/reset, /api/force-trading."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter

trading_router = APIRouter()


@trading_router.post("/api/start")
async def start_trading():
    """Start the trading competition."""
    import main
    app_state = main.app_state
    _config = main.config
    _logger = main.logger

    if app_state.is_running:
        return {"status": "already_running", "message": "Trading is already active"}

    if not _config.ALPACA_API_KEY:
        return {
            "status": "warning",
            "message": "Starting without Alpaca API key - market data will be unavailable. Set ALPACA_API_KEY in .env",
        }

    app_state.is_running = True
    app_state.start_time = main.datetime.utcnow()
    app_state.trading_task  = asyncio.create_task(main.trading_loop())
    app_state.scan_task     = asyncio.create_task(main.auto_scan_loop())
    app_state.sentinel_task = asyncio.create_task(main.news_sentinel_loop())

    _logger.info("Trading competition started!")
    return {
        "status": "started",
        "message": "Trading competition is now active",
        "agents": list(app_state.agents.keys()),
        "watchlist": _config.WATCHLIST,
        "interval_seconds": _config.TRADE_INTERVAL_SECONDS,
    }


@trading_router.post("/api/stop")
async def stop_trading():
    """Stop the trading competition."""
    import main
    app_state = main.app_state
    _logger = main.logger

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

    _logger.info("Trading competition stopped")
    return {"status": "stopped", "message": "Trading competition stopped", "cycles": app_state.cycle_count}


@trading_router.post("/api/reset")
async def reset_competition():
    """Reset all portfolios and trade history."""
    import main
    from data.market_data import market_data_service

    app_state = main.app_state
    _config = main.config
    _logger = main.logger

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
    await main.reset_database()

    # Re-register agents
    for agent in app_state.agents.values():
        agent_id = await main.upsert_agent(agent.name, agent.strategy_description)
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
            "timestamp": main.datetime.utcnow().isoformat() + "Z",
            "watchlist": _config.WATCHLIST,
        }
        dead = set()
        for ws in app_state.ws_connections.copy():
            try:
                await ws.send_text(main._json_dumps(reset_msg))
            except Exception:
                dead.add(ws)
        app_state.ws_connections -= dead

    _logger.info("Competition reset complete")
    return {"status": "reset", "message": "All portfolios reset to starting capital"}


@trading_router.post("/api/force-trading")
async def set_force_trading(enabled: bool = True):
    """Enable or disable forced trading mode (bypasses market-hours gate)."""
    import main
    main.app_state.force_trading = enabled
    state = "ENABLED" if enabled else "DISABLED"
    main.logger.warning(f"Force-trading mode {state}")
    return {"force_trading": enabled, "message": f"Force trading {state}"}
