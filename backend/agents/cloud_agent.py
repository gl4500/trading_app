"""
CloudAgent: shared base class for AI agents that call a cloud (or Ollama)
inference API on a throttled schedule.

Extracts the boilerplate that ClaudeAgent and GeminiAgent previously
duplicated: interval-based cycle throttle, exponential backoff state,
hourly call-rate cap, and the api_lock pattern.

Subclasses supply:
  - open_interval / closed_interval  (cycles between live API calls)
  - hourly_call_limit                (hard cap on cloud calls per hour)
  - seed_from_history()              (restore token window after restart)
  - analyze()                        (generate signals — required by BaseAgent)
"""
import asyncio
import logging
from typing import Any, Dict, Optional

from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)


class CloudAgent(BaseAgent):
    """
    Intermediate base class for cloud-backed AI trading agents.

    Adds:
      - Cycle-based throttle: only calls the API every N cycles; replays
        cached decisions on skipped cycles.
      - Exponential backoff: doubles _backoff_seconds on repeated errors,
        capped at 300 s.
      - Hourly call-rate cap via BaseAgent._check_hourly_rate_limit().
      - asyncio.Lock to prevent duplicate concurrent API calls.
    """

    def __init__(
        self,
        name: str,
        strategy_description: str,
        open_interval: int,
        closed_interval: int,
        hourly_call_limit: int,
        initial_backoff_seconds: float = 60.0,
    ):
        super().__init__(name=name, strategy_description=strategy_description)
        self._client: Optional[Any] = None
        self._analysis_interval: int = open_interval   # overridden dynamically each cycle
        self._open_interval: int = open_interval
        self._closed_interval: int = closed_interval
        self._cycle_count: int = 0
        self._last_decisions: Dict = {}
        self._backoff_until: float = 0.0          # epoch seconds — skip API until this time
        self._backoff_seconds: float = initial_backoff_seconds
        self._api_lock = asyncio.Lock()           # prevents duplicate concurrent API calls
        self._hourly_call_limit: int = hourly_call_limit
