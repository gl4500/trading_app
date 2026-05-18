"""Ollama-mode endpoint: /api/ollama-mode (enable/disable local-only inference)."""
from __future__ import annotations

import os
from datetime import timedelta

from fastapi import APIRouter, Query

ollama_router = APIRouter()


@ollama_router.post("/api/ollama-mode")
async def set_ollama_mode(
    enabled: bool = Query(..., description="true to activate, false to deactivate"),
    hours: float = Query(24.0, description="Duration in hours (default 24)"),
):
    """Enable or disable Ollama-only mode. While active, Claude, Gemini and OpenAI
    sentiment calls are skipped — only the local Ollama model is used."""
    import main
    app_state = main.app_state
    _logger = main.logger

    if enabled:
        app_state.ollama_only_until = main.datetime.utcnow() + timedelta(hours=hours)
        os.environ["OLLAMA_ONLY_MODE"] = "1"
        expires_iso = app_state.ollama_only_until.isoformat() + "Z"
        _logger.info(f"Ollama-only mode ENABLED for {hours}h — expires {expires_iso}")
        return {
            "enabled": True,
            "expires_at": expires_iso,
            "message": f"Ollama-only mode active for {hours} hours. Claude, OpenAI and Gemini calls are paused.",
        }
    else:
        app_state.ollama_only_until = None
        os.environ.pop("OLLAMA_ONLY_MODE", None)
        _logger.info("Ollama-only mode DISABLED")
        return {
            "enabled": False,
            "expires_at": None,
            "message": "Ollama-only mode disabled. All AI providers restored.",
        }
