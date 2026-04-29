# GPU Sequencing Across trading_app and polymarket_app — Design

**Status:** Design only. No code change in either app yet — implementation pending review.
**Author:** Claude (Layer 2.3)
**Date:** 2026-04-28

## Problem

Both `trading_app` and `polymarket_app` (the "Coinbase app") share one GPU (RTX 2060, 6 GB VRAM) for Ollama inference. Symptoms observed in `trading_app/backend/logs/error.log`:

- `[OLLAMA_LATENCY] elapsed=15–39s (SLOW)` warnings throughout active trading hours
- `Ollama timed out (50s) — using rule-based fallback` clusters (5+ in 90s)
- Falls back to raw CNN signal when LLM safety net fails

When both apps hit Ollama at the same time, requests queue and degrade each other. If they use **different** model names, Ollama swaps the model — minutes of idle GPU time per swap.

## Constraints

1. **One physical GPU.** Cannot parallelize beyond what Ollama's internal queue allows.
2. **Same Ollama server** at `http://localhost:11434/v1` for both apps.
3. **No shared codebase.** Each app's Python runtime is independent (`trading_app/runtime/python/`, polymarket has its own).
4. **Must not require a daemon.** Adding a new long-running process to maintain doubles ops surface.
5. **Must be tolerant of one app crashing or being stopped.** A dead app must not permanently block the other.
6. **Must respect existing Ollama call sites.** Ideally a single-line wrapper, not a refactor.

## Non-goals

- Distributing across multiple GPUs (we have one).
- Cross-machine coordination.
- Strict scheduling guarantees (`hard real-time`). Soft fairness is enough.

## Design Options Considered

### Option A — Same model name, no coordination (status quo)
**Approach:** Both apps already use `llama3.1:8b`. Ollama keeps one model resident and queues requests serially.
**Pros:** Zero code, zero ops.
**Cons:** No fairness — whichever app dispatches faster wins. Trading windows get starved by polymarket scans. Long polymarket prompts head-of-line block trading_app's tighter latency budget.
**Verdict:** Already in place; symptom log shows it's not enough.

### Option B — Cooperative file-lock with priority + heartbeat (RECOMMENDED)
**Approach:** Shared coordination file at `C:\ProgramData\ollama-coord\state.json` (writable by both apps). Each app, before dispatching an Ollama call, atomically reads the file, decides whether to fire or back off, and records its activity.

**File schema:**
```json
{
  "active": {
    "app":         "trading_app",
    "started_at":  1714230000.0,
    "priority":    10,
    "expected_ms": 30000,
    "pid":         12345
  },
  "last_release_at": 1714229970.0
}
```

**Acquisition algorithm (each app):**
1. Open file with exclusive OS-level advisory lock (`msvcrt.locking` on Windows, `fcntl.flock` on POSIX).
2. Read current state.
3. If `active` is None or stale (`now - active.started_at > active.expected_ms × 2`), claim it: write own info, release lock, dispatch Ollama call, on completion clear `active` and stamp `last_release_at`.
4. If `active.app != self` and `active.priority >= self.priority`: release lock, sleep `min(remaining_expected_ms, 500ms)`, retry. Bounded by an overall timeout (e.g., 10s) — on timeout, skip the cycle and HOLD.
5. If `active.priority < self.priority`: pre-empt — write own info, dispatch. The other app's call still completes (Ollama doesn't cancel in-flight) but the next dispatch contention favours us.

**Priority schedule:**
| App | Priority during market hours (ET 09:30–16:00) | Priority off-hours |
|---|---:|---:|
| trading_app | 10 | 5 |
| polymarket_app | 5 | 10 |

This biases each app to "owning" its core trading window without starving the other.

**Stale-lock recovery:** if `pid` is set, a periodic janitor (or every acquire) checks `psutil.pid_exists(pid)`; if false, treat as released. This handles app crashes.

**Heartbeat:** for inference > 10s the holding app re-stamps `started_at` every 5s. Ollama timeouts are 50s — heartbeat lets the other app distinguish a slow legitimate call from a crashed lock holder.

**Pros:**
- No daemon — coordination state lives in a 200-byte JSON file
- Both apps degrade independently if the other is offline (stale-lock recovery)
- Priority is data, not code — easy to tune at runtime
- Two-line wrapper at the existing Ollama call sites

**Cons:**
- Needs symmetric implementation in both apps (out-of-scope for trading_app's CLAUDE.md scope rule)
- File-lock contention itself adds ~1ms per call (negligible)

**Verdict:** Recommended.

### Option C — Local FastAPI Ollama proxy
**Approach:** Tiny FastAPI service runs at `localhost:11500` and forwards to `localhost:11434`. Both apps point to the proxy. Proxy enforces FIFO + per-app rate limit + priority preemption.
**Pros:** Centralized — one place to tune, one place to log.
**Cons:** New process to start/monitor; adds a network hop (TLS optional but adds 1-2ms); single point of failure.
**Verdict:** Defer. Revisit if Option B shows fairness issues we can't fix from app-side.

### Option D — Token bucket per app via shared file
**Approach:** Each app refills its bucket (e.g., 6 calls/min) from a shared JSON. If bucket empty, wait. No priorities.
**Pros:** Simple, symmetric.
**Cons:** Doesn't capture the asymmetric "trading_app cares more during market hours" requirement. Still vulnerable to head-of-line blocking on long polymarket calls.
**Verdict:** Inferior to B for this case.

## Recommended Design (Option B): Implementation Plan (NOT executed)

**Per app, add a single module:**
- `backend/data/gpu_coord.py` (trading_app) — equivalent path in polymarket_app
- Public API:
  ```python
  with gpu_coord.acquire(app="trading_app", expected_ms=30_000, priority=None):
      response = await ollama_client.chat.completions.create(...)
  ```
  `priority` defaults to a function of current ET time and `app`.

**State file:**
- Path: `C:\ProgramData\ollama-coord\state.json` (or `~/.ollama-coord/state.json` on POSIX)
- Permissions: 0600 written by both apps' user account (single user OK on home machine)
- File created on first acquire if absent

**Wrapping points in trading_app:**
- `backend/agents/cnn_reasoning_agent.py:_ollama_decision` — wrap the `client.chat.completions.create` call
- `backend/agents/sentiment_agent.py` and `gemini_agent.py` if they go through Ollama in OLLAMA_ONLY_MODE
- `backend/agents/claude_agent.py` if RESEARCH_MODEL routes through Ollama

Each call site adds ~3 lines.

**Tests (TDD):**
- `test_gpu_coord_concurrent_acquire_serializes` — two coroutines call `acquire`; second waits for first
- `test_gpu_coord_higher_priority_preempts_lower`
- `test_gpu_coord_stale_lock_recovered` — write a state file with a dead pid; new acquire claims it
- `test_gpu_coord_heartbeat_keeps_lock_fresh`
- `test_gpu_coord_timeout_returns_false` — acquire with 100ms timeout when held by another app

## Open Questions for Approval

1. **Scope acknowledgment.** Implementing Option B requires changes in BOTH `trading_app` and `polymarket_app` to be effective. Per the `feedback_scope_restriction.md` rule I won't touch polymarket_app without explicit override. Do you want me to:
   - (a) Implement only the trading_app side and you mirror it manually in polymarket_app, OR
   - (b) Override the scope rule for this one cross-cutting change?
2. **Priority schedule.** Is `trading_app priority=10 during 09:30–16:00 ET` correct? Polymarket markets are 24/7 — should its off-hours priority be `8` instead of `10`?
3. **Coordination file location.** `C:\ProgramData\ollama-coord\state.json` works on Windows. Long-term portability — should it be in user-home (`~/.ollama-coord/`) instead?
4. **Heartbeat cadence.** 5-second heartbeat with 2× expected_ms staleness threshold is conservative. Faster heartbeat catches crashed apps sooner but adds file writes. Acceptable?

## Decision Required

Approve Option B and answer Q1–Q4. Implementation effort estimate:
- trading_app side: 1 module, ~150 lines, 5 tests, 1 day of work
- polymarket_app side (mirror): same scope
- Each call-site wrapping: 5 minutes per site, ~5 sites total per app

Once approved, this plan slots in as a follow-up to the Layer 2 work just shipped.
