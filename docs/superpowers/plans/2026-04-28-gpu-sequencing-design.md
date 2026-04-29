# GPU Sequencing Across trading_app and polymarket_app — Design

**Status:** Design only. Queued for future implementation — picked up after the user wakes up to non-CNN priorities.
**Recommended approach:** Option H (dollar-at-risk priority) + Option E (per-app asyncio.Lock) + Option F (training mutex). See "Final recommendation" at the end.
**Author:** Claude (Layer 2.3)
**Date:** 2026-04-28
**Last updated:** 2026-04-28 (added Option H after user feedback that priority should be capital-weighted, not time-of-day)

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

## Final Recommendation (post user feedback, 2026-04-28)

User feedback rejected time-of-day priority: "depends on the dollar amount at stake." Recommendation revised to **Option H + Option E + Option F**, composed:

### Option H — Dollar-at-risk priority (replaces Option B)

Each app continuously publishes its current capital exposure to a shared coord file. Whichever app has more dollars at stake gets the next Ollama call.

**Coord file (`~/.ollama-coord/state.json`):**
```json
{
  "trading_app":   {"exposure_usd": 12500.00, "updated_at": 1714230050.0},
  "polymarket_app":{"exposure_usd":  3200.00, "updated_at": 1714230048.0}
}
```

**Acquisition logic per Ollama call:**
1. Read coord file. Treat any entry with `now - updated_at > 60s` as `exposure_usd = 0` (app is down or stuck — auto-yield).
2. If `self.exposure >= other.exposure` → fire immediately.
3. Else → wait `min(other.expected_ms, 1s)` and re-check. Bounded retry, 10s max. On timeout → skip cycle, return HOLD.

**Each app updates its own line** every 30s (or every cycle, whichever is shorter):
- trading_app: `exposure = sum(pos.shares × current_price for pos in portfolio.positions)`
- polymarket_app: equivalent against Coinbase positions

**Why this beats time-of-day priority:**
- Capital itself decides who's important right now — no human-set numbers, no calendar rules.
- Cash-heavy app yields to invested app naturally.
- One app crashes → its exposure stales out → other app gets full priority.

### Composed stack (full picture)

| Layer | Function | Why |
|---|---|---|
| Per-app `asyncio.Lock` (Option E) | At most 1 Ollama call in-flight per app | Prevents within-app self-contention |
| Dollar-at-risk priority (Option H) | Cross-app fairness | Capital-weighted, not time-weighted |
| Training mutex (Option F) | Only one app retrains at a time | The 30-min retrains can't both run |
| WFE BUY-gate (already shipped) | Skip cycles when LLM is slow | Last line of defense |

### Open Questions for Implementation

1. **Scope acknowledgment.** Implementing Option H requires changes in BOTH apps. Per `feedback_scope_restriction.md` we won't touch polymarket_app without explicit override. Implement trading_app side first, mirror later.
2. **Exposure definition.** Three options for what counts as "exposure":
   - **(a) Total notional** — `sum(|shares × price|)`. Simple. (Recommended starting point.)
   - **(b) Notional × volatility** — weights high-vol positions higher. More accurate.
   - **(c) Marginal-decision size** — `size_pct × portfolio` for the BUY about to fire. Most aggressive.
3. **Coord file location.** `~/.ollama-coord/state.json` (user-home, portable) vs `C:\ProgramData\ollama-coord\state.json` (Windows-native).
4. **Update cadence.** 30s feels right; faster increases I/O, slower lets exposures get stale during fast-moving markets.

### Implementation Effort

- trading_app side: ~1 day (module + integration into `_ollama_decision` call sites + 5 tests)
- polymarket_app side (mirror): same
- Once both ship, monitor for a week; fall back to Option B (time-priority) only if Option H produces unfair outcomes.

### Status

**Queued.** Pick up after current trading-app priorities clear.
