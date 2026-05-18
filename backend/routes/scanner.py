"""Scanner endpoints: /api/scanner (get cached), /api/scanner/run (trigger)."""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request

scanner_router = APIRouter()


@scanner_router.get("/api/scanner")
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


@scanner_router.post("/api/scanner/run")
async def trigger_scanner(request: Request):
    """Trigger a new agentic stock scan (or return cached result if fresh)."""
    import main
    from agents.scanner_agent import run_scan

    _logger = main.logger

    ip = request.client.host if request.client else "unknown"
    if not main._check_rate_limit(f"scanner:{ip}"):
        raise HTTPException(status_code=429, detail="Too many requests. Please wait before scanning again.")
    try:
        # In Ollama-only mode manual triggers always run fresh (no 30-min cache block)
        force = os.environ.get("OLLAMA_ONLY_MODE") == "1"
        result = await run_scan(force=force)
        if result and result.get("status") == "ok":
            main.watchlist_manager.update_from_scan(result)
        return result
    except Exception as e:
        _logger.error(f"Scanner run error: {e}")
        raise HTTPException(status_code=500, detail="Scanner encountered an error")
