"""WebSocket broadcast loop + build_ws_message helper.

Extracted from main.py for issue #67. Sends real-time state updates to every
connected WebSocket client every `config.WS_UPDATE_INTERVAL` seconds.

Test-compatibility note: `app_state`, `config`, `datetime`, `logger`,
`watchlist_manager`, `_json_dumps`, and `build_ws_message` are looked up
through `main` so existing patch-based tests intercept them correctly.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict

logger = logging.getLogger(__name__)


async def ws_broadcast_loop() -> None:
    """Broadcast real-time updates to all connected WebSocket clients."""
    import main
    _logger = main.logger
    app_state = main.app_state
    _config = main.config

    while True:
        try:
            if app_state.ws_connections and app_state.last_prices:
                message = await main.build_ws_message()
                dead_connections = set()

                for ws in app_state.ws_connections.copy():
                    try:
                        await ws.send_text(main._json_dumps(message))
                    except Exception:
                        dead_connections.add(ws)

                app_state.ws_connections -= dead_connections

            await asyncio.sleep(_config.WS_UPDATE_INTERVAL)

        except asyncio.CancelledError:
            break
        except Exception as e:
            _logger.error(f"WebSocket broadcast error: {e}")
            await asyncio.sleep(1)


async def build_ws_message() -> Dict:
    """Build the WebSocket update message."""
    import main
    from agents.summary_agent import daily_summary

    _logger = main.logger
    app_state = main.app_state

    prices = app_state.last_prices or {}

    # Get agent states
    agents_state = []
    for agent in app_state.agents.values():
        try:
            state = agent.get_state(prices)
            agents_state.append(state)
        except Exception as e:
            _logger.error(f"Error getting state for {agent.name}: {e}")

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
        _logger.debug(f"build_ws_message: summary_live failed: {e}")

    # Build 1-day change % per symbol from market context stats
    price_changes: Dict[str, float] = {}
    for sym, ctx in app_state.last_market_context.items():
        if isinstance(ctx, dict):
            pct = ctx.get("stats", {}).get("price_change_1d")
            if pct is not None:
                price_changes[sym] = round(pct, 2)

    return {
        "type": "update",
        "timestamp": main.datetime.utcnow().isoformat() + "Z",
        "is_running": app_state.is_running,
        "cycle_count": app_state.cycle_count,
        "agents": agents_state,
        "prices": prices,
        "price_changes": price_changes,
        "leaderboard": leaderboard,
        "watchlist": main.watchlist_manager.get_active_watchlist(),
        "summary_live": summary_live,
    }
