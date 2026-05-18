"""Error log endpoints: /api/errors, /api/errors/analyze."""
from __future__ import annotations

from fastapi import APIRouter, Query

error_logs_router = APIRouter()


@error_logs_router.get("/api/errors")
async def get_error_log_endpoint(
    limit: int = Query(200, description="Max entries to return"),
    errors_only: bool = Query(True, description="True=ERROR/CRITICAL only; False=include WARNINGs"),
):
    """Return recent log entries newest-first.

    Default: errors_only=True reads errors_only.log (ERROR/CRITICAL, never diluted by warnings).
    Pass errors_only=false to include WARNING entries from the full error.log.
    """
    import main
    return {
        "entries": main._parse_error_log(limit=limit, errors_only=errors_only),
        "source": "errors_only.log" if errors_only else "error.log",
    }


@error_logs_router.get("/api/errors/analyze")
async def analyze_error_log():
    """Send recent ERROR/CRITICAL entries to Claude Haiku and return root-cause analysis."""
    import main
    import anthropic

    _config = main.config

    # Read from errors_only.log so warnings never dilute the analysis
    entries = main._parse_error_log(limit=50, errors_only=True)
    error_entries = [e for e in entries if e["level"] in ("ERROR", "CRITICAL")]

    if not error_entries:
        return {"errors": [], "analysis": "No errors found in the log."}

    if not _config.ANTHROPIC_API_KEY:
        return {
            "errors": [f"{e['timestamp']} [{e['level']}] {e['logger']}: {e['message']}" for e in error_entries],
            "analysis": "Anthropic API key not configured — cannot analyze.",
        }

    # Build chronological error text for the prompt
    error_text = "\n".join(
        f"{e['timestamp']} [{e['level']}] {e['logger']}: {e['message']}"
        for e in reversed(error_entries)
    )

    client = anthropic.AsyncAnthropic(api_key=_config.ANTHROPIC_API_KEY)
    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": (
                "Analyze these error log entries from an AI trading application "
                "and suggest specific fixes:\n\n"
                f"{error_text}\n\n"
                "Respond with:\n"
                "1. Root cause for each distinct error type\n"
                "2. Specific code or config change to fix it\n"
                "3. Priority: Critical / High / Medium\n\n"
                "Be concise and actionable."
            ),
        }],
    )

    analysis = response.content[0].text if response.content else "Analysis unavailable."
    return {
        "errors": [
            f"{e['timestamp']} [{e['level']}] {e['logger']}: {e['message']}"
            for e in error_entries
        ],
        "analysis": analysis,
    }
