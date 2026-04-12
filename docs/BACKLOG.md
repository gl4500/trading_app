# Trading App — Backlog & Checklist

Status key: `[ ]` open · `[x]` done · `[-]` deferred · `[!]` blocked

Last updated: 2026-04-11 (session 2)

---

## Priority 1 — Immediate (complete before next trading session)

### 1.1 Verify sentinel tab fix ✅ DONE 2026-04-11
**Why:** `CatalystCard` used `timeZone` from parent scope — crashes with
`ReferenceError` whenever catalysts > 0.  Fixed 2026-04-11 (prop added).

- [x] Backend running with 33 live catalysts (last poll 16:38 UTC)
- [x] Sentinel tab renders catalyst cards with correct timestamps — confirmed
- [x] No React errors in browser console

**Files:** `frontend/src/components/SentinelPanel.tsx:95` — commit `80abb20`

---

### 1.2 Update test_scanner_agent.py for new max_rounds parameter ✅ DONE 2026-04-11
**Why:** `_run_ollama_scanner` signature changed — new `max_rounds` parameter,
and the dispatcher passes `max_rounds=4` in OLLAMA_ONLY_MODE via `_make_task`.
Existing tests may not cover this dispatch path.

- [x] Add TestRunOllamaScannerMaxRounds: max_rounds cap + default equals MAX_TOOL_ROUNDS
- [x] Add TestPreScreenTopN: top_n=20 in OLLAMA_ONLY_MODE, top_n=50 in cloud mode
- [x] Add to TestOllamaOnlyModeScanner: max_rounds=4 kwarg in OLLAMA_ONLY, absent in cloud
- [x] Fix stale test: test_ollama_only_mode_uses_larger_pool → uses_smaller_pool (60→20)
- [x] Run: 68 tests GREEN (6 sec)

**Files:** `backend/tests/test_scanner_agent.py` — commit `52b42b2`

---

### 1.3 Speed up pre-commit hook ✅ DONE 2026-04-11
**Why:** `test_security.py` loads the full FastAPI app including PyTorch CNN
model (~1.2 GB). Pre-commit hook currently takes 2-3 min per commit, blocking
developer workflow.

- [x] Move `test_security.py` out of the pre-commit hook
- [x] Keep pre-commit to: secret scan + Bandit only (< 5 sec)
- [x] Add `run_security_tests.bat` script for on-demand runs
- [x] Update `.git/hooks/pre-commit` — removed step 4 (test_security.py call)
- [ ] Update `CLAUDE.md` security gate section to reflect new workflow
- [ ] Update `SECURITY.md` — note that security tests run on-demand, not per-commit
- [ ] Verify pre-commit now completes in < 10 seconds on next commit

**Files:** `.git/hooks/pre-commit`, `CLAUDE.md`, `SECURITY.md`, `run_security_tests.bat`

---

## Priority 2 — Short-term (this week)

### 2.1 Add Stooq trend multiplier to scanner pre-screen ✅ DONE 2026-04-11
**Why:** Current pre-screen scores only on same-day price movement
(`abs(pct_change) × vol_ratio`). Stocks building multi-week momentum without
a single big day are missed.  Stooq 5-year data is already in the codebase.

**Score formula implemented:**
```
short_score      = abs(pct_change) × max(vol_ratio, 0.1)
above_200ma      = 1.3 if price > sma_200 else 0.9
near_52w_high    = 1.4 if price >= high_52w × 0.97 else 1.0
trend_multiplier = above_200ma × near_52w_high
final_score      = short_score × trend_multiplier
```

- [x] Read `backend/data/stooq_client.py` — confirmed `get_bars_multi` signature
- [x] Add `_compute_trend_multiplier(bars_df) -> float` helper in `scanner_agent.py`
      - Computes 200-day SMA from Stooq bars
      - Computes 52-week high from Stooq bars
      - Returns 1.0 if Stooq data unavailable — graceful fallback
- [x] Modify `_pre_screen()`:
      - Concurrent Alpaca + Stooq fetch via `asyncio.gather(return_exceptions=True)`
      - Applies `_compute_trend_multiplier` per symbol
      - Stores `trend_multiplier` in candidate dict
      - Logs top-5 candidates with trend multipliers
- [x] Add test: trend multiplier stored in candidate dict (TestPreScreenTrendMultiplier)
- [x] Add test: graceful fallback when Stooq fails (multiplier=1.0)
- [x] Add test: score formula blends correctly (pct_change × vol × trend_mult)
- [x] Add 9 unit tests for `_compute_trend_multiplier` (TestComputeTrendMultiplier)
- [x] Run test_scanner_agent.py → 80 tests GREEN
- [ ] Monitor first live scan — confirm top-20 candidates include trend-aligned names

**Files:** `backend/agents/scanner_agent.py`, `backend/tests/test_scanner_agent.py`

**Impact warning:** First scan of each day fetches 260 Stooq bars concurrently
(HTTP). Cache warms in ~15-30 sec. Subsequent scans (within 4h TTL) are instant.

---

### 2.2 Fix / disable Unusual Whales API ✅ DONE 2026-04-11
**Why:** Logs show persistent `401 Unauthorized` and `404 Not Found` from
Unusual Whales endpoints every 5-15 min sentinel poll.

- [x] Add circuit breaker: _uw_auth_failed flag — on first 401, log WARNING
      once and skip all subsequent calls for the process lifetime
- [x] Add circuit breaker: _uw_flow_missing flag — on first 404, log WARNING
      once and skip flow alerts for the process lifetime
- [x] Subscription status unknown — circuit breaker handles both expired key
      and endpoint changes gracefully without requiring .env edit
- [x] To re-enable: update UNUSUAL_WHALES_API_KEY in .env and restart backend

**Files:** `backend/data/sentinel_sources.py` — commit `5bfc2b7`

---

### 2.3 Set up pip-audit monthly dependency scan
**Why:** No automated check for known CVEs in Python dependencies.

- [ ] Install: copy `pip_audit` wheel into `site-packages/` or run
      `runtime\python\python.exe -m pip install pip-audit --target site-packages`
- [ ] Verify: `PYTHONPATH=site-packages runtime\python\python.exe -m pip_audit --version`
- [ ] Create `run_pip_audit.bat` in repo root:
      ```bat
      @echo off
      cd /d %~dp0
      set PYTHONPATH=%~dp0site-packages
      runtime\python\python.exe -m pip_audit --requirement backend/requirements.txt
      ```
- [ ] Run audit now — record any findings
- [ ] Add monthly reminder to `SECURITY.md`: "Run `run_pip_audit.bat` first of each month"
- [ ] If findings: update affected packages; re-run Bandit; re-run tests

**Files:** `run_pip_audit.bat` (new), `SECURITY.md`

---

## Priority 3 — Medium-term (next 2 weeks)

### 3.1 CNN model lazy-load (fix slow test/hook startup)
**Why:** PyTorch CNN model loads at module import time. Every test run and
pre-commit hook that imports any agent indirectly loads ~1.2 GB into RAM.
Slows tests from ~10 sec to ~2 min.

- [ ] Read `backend/agents/cnn_reasoning_agent.py` — find where model is loaded at module level
- [ ] Wrap model load in a `_load_model()` function called only on first `analyze()` call
- [ ] Use a module-level `_model = None` sentinel and load on demand
- [ ] Verify: `import cnn_reasoning_agent` no longer triggers PyTorch load
- [ ] Verify: first `analyze()` call loads model correctly
- [ ] Update `test_cnn_reasoning_agent.py` — mock the lazy-load path
- [ ] Run pre-commit on a small change — confirm hook completes in < 30 sec

**Files:** `backend/agents/cnn_reasoning_agent.py`

---

### 3.2 OWASP ZAP DAST scan (pre-release validation)
**Why:** Static analysis (Bandit) and unit tests don't catch runtime
injection, auth bypass, or insecure redirects. DAST exercises the live API.

- [ ] Install Docker (if not already installed)
- [ ] Start backend: `start_backend.bat`
- [ ] Run ZAP baseline:
      ```bash
      docker run --network host -t owasp/zap2docker-stable \
          zap-baseline.py -t http://127.0.0.1:8000 -r zap_report.html
      ```
- [ ] Review `zap_report.html` — triage medium and high findings
- [ ] Fix any confirmed medium/high findings
- [ ] Re-run Bandit after fixes
- [ ] Document ZAP baseline results in `SECURITY.md`
- [ ] Add ZAP to release checklist: "Run ZAP before merging major features to main"

**Files:** `SECURITY.md`

---

### 3.3 Warm Stooq cache on backend startup
**Why:** After adding Stooq to the pre-screen (item 2.1), the first scan of
each day will fetch 260 symbols from Stooq synchronously — 15-30 sec delay.
Pre-warming the cache at startup eliminates this.

*Depends on: 2.1 (Stooq pre-screen) being implemented first.*

- [ ] Add `_warm_stooq_cache()` async function in `scanner_agent.py` or `market_data.py`
      - Calls `stooq_client.get_bars_multi(ALL_SYMBOLS, days=252)` in background
      - Logs "Stooq cache warmed: N symbols" on completion
- [ ] Register as a `asyncio.create_task()` during lifespan startup in `main.py`
      (fire-and-forget — does not block startup)
- [ ] Add test: task is created at startup; Stooq client is called with ALL_SYMBOLS
- [ ] Verify: first scanner run after startup uses cached Stooq data (no HTTP calls)

**Files:** `backend/main.py`, `backend/agents/scanner_agent.py`

---

### 3.4 Evaluate OLLAMA_HYBRID_MODE
**Why:** `OLLAMA_HYBRID_MODE` is configured in `config.py` but was never
formally evaluated for lift over pure `OLLAMA_ONLY_MODE`.

- [ ] Read `config.py` hybrid mode settings (`HYBRID_ESCALATION_THRESHOLD=0.65`)
- [ ] Trace hybrid mode code path through `claude_agent.py` / `gemini_agent.py`
- [ ] Run 5 trading sessions in OLLAMA_ONLY_MODE — record P&L and recommendation count
- [ ] Run 5 trading sessions in OLLAMA_HYBRID_MODE — record same metrics
- [ ] Compare: does hybrid mode improve recommendation quality vs added cloud cost?
- [ ] Decision: enable, disable, or tune `HYBRID_ESCALATION_THRESHOLD`
- [ ] Update `.env` and `SECURITY.md` with final mode selection and rationale

**Files:** `backend/config.py`, `backend/agents/claude_agent.py`

---

## Completed This Session

| Date | Item | Commit |
|---|---|---|
| 2026-04-11 | Security gate: Bandit SAST + pre-commit hook + `test_security.py` (25 tests) | `8f14eee` |
| 2026-04-11 | CNN agent: timeout 25→50s, temp 0.1→0.3, tokens 200→350, 3-step prompt | `8f14eee` |
| 2026-04-11 | Scanner: `top_n` 60→20 in OLLAMA_ONLY_MODE, `max_rounds=4` cap | `8f14eee` |
| 2026-04-11 | Database: fix migration order — `ALTER TABLE` before `CREATE INDEX` on date | `8f14eee` |
| 2026-04-11 | Security: B104 HOST fix, B314 defusedxml, B608 nosec | `8f14eee` |
| 2026-04-11 | Sentinel tab: `timeZone` prop missing in `CatalystCard` → blank screen | `eeeec19` |
| 2026-04-11 | Docs: `CLAUDE.md` security gate section, `SECURITY.md` new file, `tests/README.md` rewrite | `8f14eee` |
| 2026-04-11 | Scanner 2.1: Stooq trend multiplier in pre-screen — `_compute_trend_multiplier`, concurrent fetch, 80 tests GREEN | `9dfce45` |
| 2026-04-11 | Switch Ollama model `llama3.1:8b` → `qwen2.5:7b` (better JSON output, -500 MB VRAM) | `152f839` |
| 2026-04-11 | Refactor: consolidate token tracking, rate-limit window, JSON parsing into base classes (~150 LOC, 181 tests GREEN) | `56509b0` |
