"""WebSocket connection management and /ws endpoint.

Extracted from main.py for issue #67. Provides:

- `ws_router`: APIRouter with the `/ws` endpoint. main.py mounts this onto
  the FastAPI app via `app.include_router(ws_router)`.
- `websocket_endpoint`: the actual endpoint handler. Re-exported from main
  for tests that need to import it directly.

The endpoint accesses mutable state (`app_state.ws_connections`,
`app_state.last_prices`, etc.) and the patchable helpers `build_ws_message`
and `_json_dumps` via `main.X` lookups so existing patch-based tests
continue to work.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import auth as auth

logger = logging.getLogger(__name__)

ws_router = APIRouter()


@ws_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Real-time WebSocket endpoint for live updates."""
    import main  # late import — required for test patches against main.app_state

    # Authenticate before accepting the connection.
    # The session cookie is forwarded by the Vite proxy on WS upgrade.
    if auth.is_enabled():
        token = websocket.cookies.get(auth.SESSION_COOKIE)
        if not token or not auth.validate_session(token):
            await websocket.close(code=1008)  # 1008 = Policy Violation
            return

    await websocket.accept()
    main.app_state.ws_connections.add(websocket)
    client = websocket.client
    logger.info(f"WebSocket connected: {client}")

    try:
        # Send initial state immediately
        if main.app_state.last_prices or main.app_state.agents:
            try:
                initial_message = await main.build_ws_message()
                await websocket.send_text(main._json_dumps(initial_message))
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
                await websocket.send_text(json.dumps({
                    "type": "heartbeat",
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                }))

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {client}")
    except Exception as e:
        logger.error(f"WebSocket error for {client}: {e}")
    finally:
        main.app_state.ws_connections.discard(websocket)
