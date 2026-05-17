"""Application state singleton.

Holds all mutable global state for the backend: agents dict, running flags,
background task handles, WebSocket connections, in-memory caches.

Extracted from main.py for issue #67. The AppState class and the `app_state`
singleton live here; main.py re-exports them so existing tests that do
`patch("main.app_state", ...)` continue to work.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import WebSocket


class AppState:
    """Global application state."""

    def __init__(self):
        self.agents: Dict[str, object] = {}
        self.is_running: bool = False
        self.trading_task: Optional[asyncio.Task] = None
        self.scan_task: Optional[asyncio.Task] = None
        self.sentinel_task: Optional[asyncio.Task] = None
        self.ws_task: Optional[asyncio.Task] = None
        self.ws_connections: Set["WebSocket"] = set()
        self.last_prices: Dict[str, float] = {}
        self.last_market_context: Dict = {}
        self.cycle_count: int = 0
        self.start_time: Optional[datetime] = None
        self.market_status: str = "unknown"          # "open" | "closed"
        self._prev_market_status: str = "unknown"    # for EOD roll-up transition detection
        self.gemini_news_agent = None                # GeminiAgent used as news source only
        self.force_trading: bool = False              # bypass market-hours gate for testing
        self.after_hours_catalysts: List[Dict] = []  # catalysts found by sentinel
        self.last_sentinel_poll: Optional[str] = None  # ISO timestamp of last sentinel poll
        self.news_price_snapshots: List[Dict] = []    # price at catalyst detection + later change
        self.ollama_only_until: Optional[datetime] = None  # expiry of Ollama-only mode
        self.pull_task: Optional[asyncio.Task] = None      # background Ollama model pull task

    def get_agents_list(self) -> list:
        return list(self.agents.values())


# Module-level singleton — imported by main.py and re-exported as main.app_state.
app_state = AppState()
