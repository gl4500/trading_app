# Trading App — Backlog & Checklist

Status key: `[ ]` open · `[x]` done · `[-]` deferred · `[!]` blocked

Last updated: 2026-04-11

---

## Priority 1 — Immediate (complete before next trading session)

### 1.1 Verify sentinel tab fix
**Why:** `CatalystCard` used `timeZone` from parent scope — crashes with
`ReferenceError` whenever catalysts > 0.  Fixed 2026-04-11 (prop added).

- [ ] Restart backend and wait for first sentinel poll (~15 min after start)
- [ ] Navigate to Sentinel tab — confirm catalyst cards render with correct timestamps
- [ ] Check browser console — confirm no React errors
- [ ] Confirm backend log shows `GET /api/sentinel HTTP/1.1" 200 OK` on tab visit

**Files:** `frontend/src/components/SentinelPanel.tsx:95`

---

### 1.2 Update test_scanner_agent.py for new max_rounds parameter
**Why:** `_run_ollama_scanner` signature changed — new `max_rounds` parameter,
and the dispatcher passes `max_rounds=4` in OLLAMA_ONLY_MODE via `_make_task`.
Existing tests may not cover this dispatch path.

- [ ] Open `backend/tests/test_scanner_agent.py`
- [ ] Add test: `OLLAMA_ONLY_MODE=1` → `_run_ollama_scanner` called with `max_rounds=4`
- [ ] Add test: cloud mode → `_run_ollama_scanner` called with default `max_rounds=6`
- [ ] Add test: `_make_task` returns correct coroutine type for each mode
- [ ] Run: `runtime\python\python.exe run_tests.py -v` → all GREEN

**Files:** `backend/tests/test_scanner_agent.py`, `backend/agents/scanner_agent.py:1218`

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

### 2.1 Add Stooq trend multiplier to scanner pre-screen
**Why:** Current pre-screen scores only on same-day price movement
(`abs(pct_change) × vol_ratio`). Stocks building multi-week momentum without
a single big day are missed.  Stooq 5-year data is already in the codebase.

**Proposed score formula:**
```
short_score      = abs(pct_change) × max(vol_ratio, 0.1)
above_200ma      = 1.3 if price > sma_200 else 0.9
near_52w_high    = 1.4 if price > high_52w × 0.97 else 1.0
trend_multiplier = above_200ma × near_52w_high
final_score      = short_score × trend_multiplier
```

- [ ] Read `backend/data/stooq_client.py` — confirm `get_bars_multi` signature
- [ ] Add `_compute_trend_multiplier(bars_df) -> float` helper in `scanner_agent.py`
      - Compute 200-day SMA from Stooq bars
      - Compute 52-week high from Stooq bars
      - Return multiplier (1.0 if Stooq data unavailable — graceful fallback)
- [ ] Modify `_pre_screen()`:
      - After Alpaca batch fetch, call `stooq_client.get_bars_multi(batch, days=252)` concurrently
      - Apply `_compute_trend_multiplier` per symbol
      - Store `trend_multiplier` and `sma_200` in candidate dict
      - Log top-5 candidates with their trend multipliers for visibility
- [ ] Add test: trend multiplier applied when Stooq data available
- [ ] Add test: graceful fallback (multiplier=1.0) when Stooq returns empty DataFrame
- [ ] Add test: score formula produces correct blended result
- [ ] Run full test suite → GREEN
- [ ] Monitor first live scan — confirm top-20 candidates include trend-aligned names

**Files:** `backend/agents/scanner_agent.py:463`, `backend/data/stooq_client.py`

**Impact warning:** First scan of each day fetches 260 Stooq bars concurrently
(HTTP). Cache warms in ~15-30 sec. Subsequent scans (within 4h TTL) are instant.

---

### 2.2 Fix / disable Unusual Whales API
**Why:** Logs show persistent `401 Unauthorized` and `404 Not Found` from
Unusual Whales endpoints. This is noise in the log and wastes network calls.

- [ ] Check if Unusual Whales subscription is active at unusualwhales.com
- [ ] **If subscription lapsed:** set `UNUSUAL_WHALES_API_KEY=` (empty) in `.env`
      and confirm `sentinel_sources.py` skips the source when key is absent
- [ ] **If subscription active:** check API docs for endpoint changes; update URLs
      in `backend/data/sentinel_sources.py`
- [ ] Confirm log no longer shows 401/404 from Unusual Whales after fix
- [ ] If permanently disabling: remove the source from `sentinel_sources.py`
      and update `SECURITY.md` data sources list

**Files:** `backend/data/sentinel_sources.py`, `.env`

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
| 2026-04-11 | Security gate: Bandit SAST + pre-commit hook + `test_security.py` (25 tests) | pending |
| 2026-04-11 | CNN agent: timeout 25→50s, temp 0.1→0.3, tokens 200→350, 3-step prompt | pending |
| 2026-04-11 | Scanner: `top_n` 60→20 in OLLAMA_ONLY_MODE, `max_rounds=4` cap | pending |
| 2026-04-11 | Database: fix migration order — `ALTER TABLE` before `CREATE INDEX` on date | pending |
| 2026-04-11 | Security: B104 HOST fix, B314 defusedxml, B608 nosec | pending |
| 2026-04-11 | Sentinel tab: `timeZone` prop missing in `CatalystCard` → blank screen | pending |
| 2026-04-11 | Docs: `CLAUDE.md` security gate section, `SECURITY.md` new file, `tests/README.md` rewrite | pending |
