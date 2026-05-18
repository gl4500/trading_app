"""Token usage endpoints: /api/tokens, /api/token-log."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

token_usage_router = APIRouter()


@token_usage_router.get("/api/tokens")
async def get_token_usage():
    """Return AI token usage statistics for all agents.

    Per-agent breakdown:
    - daily_tokens: tokens consumed today (resets at midnight)
    - session_tokens: tokens consumed since last app restart
    - calls_this_hour: API calls made in the last 60 minutes
    - hourly_call_limit: maximum calls allowed per hour
    - daily_limit: daily token cap (only set for SentimentAgent)
    - daily_remaining: tokens remaining today (only when daily_limit set)

    Grand totals (daily and session) are summed across all agents.
    """
    import main
    import time as _time
    app_state = main.app_state

    _TOKEN_AGENTS = ["ClaudeAgent", "GeminiAgent", "SentimentAgent"]

    def _agent_stats(agent) -> dict:
        now = _time.time()
        calls_this_hour = sum(1 for t in getattr(agent, "_call_timestamps", []) if now - t < 3600)
        daily = getattr(agent, "_daily_tokens", 0)
        limit = getattr(agent, "_daily_token_limit", None)
        entry = {
            "daily_tokens":       daily,
            "session_tokens":     getattr(agent, "_session_tokens", 0),
            "calls_this_hour":    calls_this_hour,
            "hourly_call_limit":  getattr(agent, "_hourly_call_limit", None),
        }
        if limit is not None:
            entry["daily_limit"]     = limit
            entry["daily_remaining"] = max(0, limit - daily)
        return entry

    agents_out: dict = {}

    # Trading agents that track tokens (in-memory stats + DB fallback for daily_tokens)
    for name, agent in app_state.agents.items():
        if name in _TOKEN_AGENTS:
            entry = _agent_stats(agent)
            # If in-memory daily_tokens is 0, fall back to DB so the panel reflects
            # any calls logged before this session (e.g. restart mid-day, Ollama mode)
            if entry["daily_tokens"] == 0:
                entry["daily_tokens"] = await main.get_daily_token_total(name, hours=24)
            agents_out[name] = entry

    # Gemini runs as news agent outside app_state.agents
    if app_state.gemini_news_agent and "GeminiAgent" not in agents_out:
        entry = _agent_stats(app_state.gemini_news_agent)
        if entry["daily_tokens"] == 0:
            entry["daily_tokens"] = await main.get_daily_token_total("GeminiAgent", hours=24)
        agents_out["GeminiAgent"] = entry

    # Agents that are standalone functions with no in-memory state — query the DB
    _DB_AGENTS = (
        "ScannerAgent/Claude",
        "ScannerAgent/Gemini",
        "ScannerAgent/OpenAI",
        "ScannerAgent/Ollama",
        "SummaryAgent",
    )
    for db_agent in _DB_AGENTS:
        daily = await main.get_daily_token_total(db_agent, hours=24)
        calls_hr = await main.get_agent_calls_this_hour(db_agent)
        agents_out[db_agent] = {
            "daily_tokens":      daily,
            "session_tokens":    daily,
            "calls_this_hour":   calls_hr,
            "hourly_call_limit": None,
        }

    totals = {
        "daily_tokens":   sum(v["daily_tokens"]   for v in agents_out.values()),
        "session_tokens": sum(v["session_tokens"] for v in agents_out.values()),
    }

    return {"agents": agents_out, "totals": totals}


@token_usage_router.get("/api/token-log")
async def get_token_log_endpoint(
    agent: Optional[str] = Query(None, description="Filter by agent name"),
    hours: int = Query(24, description="Time window in hours"),
    limit_hit: bool = Query(False, description="Only return limit-hit events"),
    limit: int = Query(500, description="Max entries to return"),
):
    """Return DB token usage log, newest first. Searchable by agent, time window, and limit_hit."""
    import main
    entries = await main.get_token_log(
        agent=agent,
        hours=hours,
        limit_hit_only=limit_hit,
        limit=limit,
    )
    return {"entries": entries}
