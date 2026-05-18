"""Automatic scanner scheduler.

Extracted from main.py for issue #67. Runs the scanner agent at smart
intervals based on NYSE market hours.

Test-compatibility note: `_market_is_open`, `_minutes_until_open`,
`_get_market_status`, `watchlist_manager`, and `app_state` are all looked
up through the `main` module so existing `patch("main.X", ...)` tests
intercept them correctly.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

logger = logging.getLogger(__name__)


async def auto_scan_loop() -> None:
    """Automatically trigger the stock scanner at smart intervals.

    Schedule:
      • Run once immediately on start (if no fresh cached scan exists).
      • During market hours: every AUTO_SCAN_INTERVAL_MIN minutes.
      • Pre-market warm-up: run 10 minutes before open so results are ready at the bell.
      • Outside market hours: sleep until 10 min before next open — no wasted API calls.
      • Never runs while a scan is already in progress.
    """
    import main
    from agents.scanner_agent import run_scan, get_cached_scan, is_scan_in_progress

    _logger = main.logger
    app_state = main.app_state

    OLLAMA_SCAN_INTERVAL_MIN  = 5    # scan every 5 min during market hours (Ollama-only)
    STANDARD_SCAN_INTERVAL_MIN = 30  # scan every 30 min during market hours (cloud)
    PRE_MARKET_WARMUP_MIN     = 10   # run N minutes before open
    POLL_SLEEP_SEC             = 60  # how often to wake up and check the schedule

    _logger.info("Auto-scan loop started")

    async def _do_scan(reason: str) -> None:
        if is_scan_in_progress():
            _logger.info(f"Auto-scan: skipping ({reason}) — scan already in progress")
            return
        _logger.info(f"Auto-scan: triggering scan ({reason})")
        try:
            result = await run_scan()
            if result:
                main.watchlist_manager.update_from_scan(result)
        except Exception as e:
            _logger.error(f"Auto-scan error: {e}")

    # Run once at startup if cache is missing or stale — but only during market
    # hours or the pre-market warmup window to avoid expensive off-hours scans.
    cached = get_cached_scan(require_fresh=True)
    if not cached and (main._market_is_open() or main._minutes_until_open() <= PRE_MARKET_WARMUP_MIN):
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

            session = main._get_market_status()
            if session == "open":
                # Regular interval scan during market hours
                if elapsed_min >= interval_min:
                    await _do_scan(f"scheduled every {interval_min} min")
                    last_scan_triggered = now_ts
            else:
                # Market closed
                mins_to_open = main._minutes_until_open()
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
                    if elapsed_min >= main.OLLAMA_CLOSED_SCAN_MIN:
                        await _do_scan("off-hours Ollama scan (free, local)")
                        last_scan_triggered = now_ts

        except asyncio.CancelledError:
            break
        except Exception as e:
            _logger.error(f"Auto-scan loop error: {e}", exc_info=True)
            await asyncio.sleep(30)

    _logger.info("Auto-scan loop stopped")
