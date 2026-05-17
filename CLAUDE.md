# CLAUDE.md — AI Trading App Coordination Contract

This file is read by all Claude Code agents working on this repository.
It defines responsibilities, workflows, and rules that every agent must follow.

---

## Scope

**Only modify files inside `C:\Users\gl450\trading_app\`.**
Never touch `radioconda\`, `.spyder-py3\`, or any other directory in the user's home folder.

- For running tests, only use `C:\Users\gl450\trading_app\runtime\python\python.exe` — never fall back to radioconda or any system Python.
- If pytest is missing from that runtime, flag it to the user — do NOT silently switch runtimes.

### Fresh install infrastructure
- New-machine setup: `scripts/setup_fresh.bat` (double-click) or `scripts/setup_fresh.ps1`
- Downloads Python 3.12, Node.js 22 LTS, all packages, generates certs, creates `.env` automatically
- Offline wheel cache: `backend/packages/` (committed to git — excludes torch, which is downloaded by the script)
- Do NOT remove `.env.example` or `backend/requirements.txt` — they are the source of truth for the setup script

---

## Two-Agent Setup

| Agent | Role | Owns |
|---|---|---|
| **Implementation agent** (main Claude Code session) | Feature work, bug fixes, refactors | `backend/`, `frontend/`, `README.md` |
| **Testing sub-agent** (separate session) | Unit & component tests, test infrastructure | `backend/tests/`, `backend/pytest.ini`, `backend/tests/conftest.py` |

**Coordination via filesystem:** both agents read/write files — the contract below prevents conflicts.

---

## Find-List-Fix Workflow — Required whenever issues are identified

Whenever bugs, test failures, stale assertions, or needed refactors are found during any task:

```
1. STOP — do not fix inline without listing first
2. Write a numbered task list of every issue found (all of them, not just the current one)
3. Fix each item in order, marking it complete as you go
4. Do not move to the next task until the current one is green and committed
```

**Rule:** No fix is made silently. Every issue gets listed before it gets fixed. This prevents
partial fixes, forgotten follow-ups, and scope creep mid-task.

Example — found 3 issues while working on a feature:
```
Found issues:
1. [ ] test_scanner_tokens assertion uses stale count (3 agents, now 5)
2. [ ] _hourly_call_limit hardcoded — should be in config.py
3. [ ] CORRELATION_LIMIT constant not exposed in config
→ Fix 1, commit. Fix 2, commit. Fix 3, commit.
```

---

## TDD Workflow — Required for every change

```
1. Testing sub-agent writes a failing test  →  backend/tests/test_<module>.py
2. Implementation agent implements the code
3. Run tests:  cd backend && python -m pytest tests/ -v
4. Both agents verify GREEN before committing
5. Commit:  git add tests/<file> <module.py> && git commit
```

No code change is committed without a corresponding test. No exceptions for "small" fixes.

---

## File Ownership

### Implementation agent writes:
```
backend/
  agents/*.py          (agent logic)
  data/*.py            (data services)
  trading/*.py         (portfolio, risk)
  main.py              (API + trading loop)
  config.py            (configuration)
  database.py          (persistence)
frontend/
  src/                 (React components)
README.md
```

### Testing sub-agent writes:
```
backend/
  tests/test_*.py      (unit & component tests)
  tests/conftest.py    (shared pytest fixtures)
  tests/README.md      (test documentation)
  pytest.ini           (pytest configuration)
```

### Both agents may read any file. Neither deletes the other's files.

---

## Test Conventions

- Framework: `unittest.TestCase` + `pytest` runner
- Async tests: `unittest.IsolatedAsyncioTestCase`
- **No live API calls** — mock `anthropic`, `openai`, `alpaca`, `yfinance`, `httpx`
- **No real DB writes** — use `tempfile.mkstemp()` for database tests
- **No real file I/O** — mock `learning.json`, `agent_picks.json`, `scan_cache.json`
- Shared fixtures live in `tests/conftest.py` — don't duplicate setup across files
- One test file per module: `agents/foo.py` → `tests/test_foo.py`

### Running tests
```bash
cd C:\Users\gl450\trading_app\backend
runtime\python\python.exe run_tests.py -v    # full suite (verbose)
runtime\python\python.exe run_tests.py       # full suite (summary only)
```
Note: pytest is not installed in the self-contained runtime. Use `run_tests.py` (unittest discovery).

### Shell cleanup — required after every test run

Running tests repeatedly causes background bash+python processes to stack up. After any test run:

```bash
# Kill leftover python processes
ps aux | grep python | grep -v grep | awk '{print $1}' | xargs kill -9 2>/dev/null
```

Rules:
- **Prefer per-module tests** (`python -m unittest tests.<module>`) over the full suite during development — faster, stays foreground, no stacking
- **Only run the full suite once** before committing, not repeatedly
- **Always clean up** after a test run completes or is interrupted

---

## Commit Standards

```
feat: short description of new feature
fix:  short description of bug fixed
test: add/update tests for X
docs: update README or CLAUDE.md
refactor: internal cleanup, no behavior change
security: security hardening, SAST fixes, secret scanning
```

All commits include both the implementation file and its test file.
Co-Authored-By line required (added automatically by implementation agent).

---

## Security Gate — Pre-commit Hook

Every `git commit` runs `.git/hooks/pre-commit` automatically (3 steps, < 10 sec):

1. **Block staged `.env`** — prevents API keys reaching GitHub
2. **Secret pattern scan** — rejects Anthropic/OpenAI/Google/AWS/Alpaca key patterns in staged `.py/.ts/.js/.json` files
3. **Bandit SAST** — medium+/medium+ severity, excludes `tests/`, uses `site-packages/` runtime

**Security tests run on-demand** (not per-commit — PyTorch import makes it ~2 min):
```bash
scripts\run_security_tests.bat  # Windows convenience script
```
Run before every merge to main.

**To suppress a known-safe Bandit finding:**
```python
result = some_call()  # nosec BXXX - brief reason why this is safe
```
The `# nosec` comment must be on the **flagged line itself** (not the line above).

**Bandit is installed at:** `C:\Users\gl450\trading_app\site-packages\bandit`
**defusedxml is installed at:** `C:\Users\gl450\trading_app\site-packages\defusedxml`

Run Bandit manually:
```bash
cd backend
PYTHONPATH=../site-packages ../runtime/python/python.exe -m bandit -r . -x ./tests/ --severity-level medium --confidence-level medium
```

---

## Current Test Coverage

| Module | Test File | Status |
|---|---|---|
| `trading/portfolio.py` | `test_portfolio.py` | ✅ covered |
| `trading/risk_manager.py` | `test_risk_manager.py` | ✅ covered |
| `data/technicals.py` | `test_technicals.py` | ✅ covered |
| `data/policy_monitor.py` | `test_policy_monitor.py` | ✅ covered |
| `data/signal_aggregator.py` | `test_signal_aggregator.py` | ✅ covered |
| `data/sentinel_sources.py` | `test_sentinel_sources.py` | ✅ covered |
| `data/learning_manager.py` | `test_learning_manager.py` | ✅ covered |
| `data/market_data.py` (cache) | `test_market_data_cache.py` | ✅ covered |
| `agents/ensemble_agent.py` | `test_ensemble_voting.py` | ✅ covered |
| `agents/momentum_agent.py` | `test_momentum_agent.py` | ✅ covered |
| `agents/agent_utils.py` | `test_agent_utils.py` | ✅ covered |
| `agents/base_agent.py` | `test_signals_and_drift.py` | ✅ covered |
| `database.py` | `test_database.py` | ✅ covered |
| `agents/mean_reversion_agent.py` | `test_mean_reversion_agent.py` | ✅ covered |
| `agents/tech_agent.py` | `test_tech_agent.py` | ✅ covered |
| `agents/claude_agent.py` | `test_claude_agent.py` | ✅ covered |
| `agents/gemini_agent.py` | `test_gemini_agent.py` | ✅ covered |
| `agents/sentiment_agent.py` | `test_sentiment_agent.py` | ✅ covered |
| `agents/scanner_agent.py` | `test_scanner_agent.py` | ✅ covered |
| `agents/scanner_portfolio_agent.py` | `test_scanner_portfolio_agent.py` | ✅ covered |
| `agents/cnn_reasoning_agent.py` | `test_cnn_reasoning_agent.py` | ✅ covered |
| `data/agent_performance_tracker.py` | `test_agent_performance_tracker.py` | ✅ covered |
| `agents/summary_agent.py` | `test_summary_agent.py` | ✅ covered |
| `agents/historical_trends_agent.py` | `test_historical_trends_agent.py` | ✅ covered |
| `data/stooq_client.py` | `test_stooq_client.py` | ✅ covered |
| `main.py` endpoints | `test_main_endpoints.py` | ✅ covered |
| security surface (headers, CORS, SQL, secrets) | `test_security.py` | ✅ covered |
| `data/regime_detector.py` | `test_regime_detector.py` | ✅ covered |
| `trading/portfolio.py` (Kelly sizing) | `test_portfolio.py::TestKellyFraction` | ✅ covered |
| `trading/portfolio.py` (Bayesian confidence) | `test_portfolio.py::TestBayesianConfidence` | ✅ covered |
| `data/cnn_model.py` (WFE) | `test_cnn_model.py::TestWalkForwardEfficiency` | ✅ covered |
| `data/cnn_model.py` (walk-forward CV) | `test_cnn_model.py::TestFitProducesWalkforwardMetrics`, `TestBuildTrainingWindowsReturnsTimestamps`, `TestTrainingHistoryRecordSchema` | ✅ covered |
| `data/xgboost_model.py` | `test_xgboost_model.py` | ✅ covered |
| `data/signal_model.py` | `test_signal_model_selector.py` | ✅ covered |
| `data/cnn_evaluation.py` | `test_cnn_evaluation.py` | ✅ covered |
| CNN random-feature sanity (one-off) | `test_cnn_random_feature.py` | ⚠️ expected-failure diagnostic |
| `data/macro_history.py` + `data/history_backfill.py` (macro) | `test_macro_history.py` | ✅ covered |
| `data/tax_estimator.py` | `test_tax_estimator.py` | ✅ covered |
| `trading/alpaca_client.py` (get_filled_orders) | `test_tax_estimator.py` | ✅ covered |
| `data/news_service.py` (retry, circuit breaker, timeout) | `test_news_service.py` | ✅ covered |

---

## CLAUDE.md ↔ Memory Sync Rule

**Both must always be updated together, and memory must be updated after every code change.**

`CLAUDE.md` (this file, in the repo) and the persistent memory files at
`C:\Users\gl450\.claude\projects\C--Users-gl450\memory\` are the two halves of the same contract.

### After every code change — required steps
1. If the change affects architecture, agents, endpoints, or file structure → update `trading_app_architecture.md`.
2. If the change fixes a bug → append the bug + fix to `trading_app_bugs_fixed.md`.
3. If the change adds or modifies a rule → update the matching memory file AND this `CLAUDE.md` section in the same response.
4. Never commit code without also committing any corresponding `CLAUDE.md` update in the same or immediately following commit.

### CLAUDE.md ↔ memory sync
- When you add or change a rule in `CLAUDE.md` → update the corresponding memory file in the same response.
- When you update a memory file that covers trading_app rules or feedback → reflect the change in `CLAUDE.md` in the same response.
- Never let a session end with the two out of sync.

Relevant memory files for this repo:
| Memory file | Mirrors |
|---|---|
| `feedback_tdd_workflow.md` | TDD Workflow section |
| `feedback_scope_restriction.md` | Scope section |
| `feedback_shell_cleanup.md` | Shell cleanup section |
| `feedback_sync_rule.md` | This section (memory update after every change) |
| `feedback_performance_history_retention.md` | Key invariant #9 (no date-based prune on performance table) |
| `trading_app_architecture.md` | Architecture Quick Reference + Key invariants |
| `trading_app_bugs_fixed.md` | Known bugs and fixes (not in CLAUDE.md — memory only) |
| `trading_app_thresholds.md` | Agent thresholds (not in CLAUDE.md — memory only) |

---

## Architecture Quick Reference

- **Backend:** FastAPI + asyncio, port 8000
- **Frontend:** React + Vite + Tailwind, port 5173
- **DB:** SQLite via aiosqlite (`trading.db`)
- **Market data:** Alpaca Markets (paper trading)
- **AI agents (cloud mode):** Claude Opus 4.6, Gemini 2.0 Flash, GPT-4o-mini
- **AI agents (Ollama mode):** All three above route to local Ollama when `OLLAMA_ONLY_MODE=1`; off-hours auto-scan runs every `OLLAMA_CLOSED_SCAN_MIN=30` min when market is closed (cloud mode is unchanged)
- **Local inference:** Ollama at `http://localhost:11434/v1` (OpenAI-compatible); `OLLAMA_MODEL` for Sentiment/Gemini/CNN; `RESEARCH_MODEL` for Claude (defaults to `OLLAMA_MODEL`)
- **Current Ollama model:** `llama3.1:8b` (~4.7 GB Q4) — reliable instruction following and structured JSON; fits RTX 2060 with headroom.
- **GPU constraint:** RTX 2060 = 6 GB VRAM — only one Q4 model fits at a time. Set `RESEARCH_MODEL=OLLAMA_MODEL` to share the single loaded model; never configure two different models simultaneously on this GPU.
- **Config:** `.env` → `backend/config.py` → `config` singleton
- **Agent context key:** `market_context["__overnight_catalysts__"]` is a `list` — all agents guard with `isinstance(ctx, dict)` when iterating

- **Tax estimate:** `GET /api/tax/estimate?year=YYYY` — federal capital gains summary (short/long-term, wash sales, quarterly) from real Alpaca trade history

## Key invariants (never break these)
1. `market_context` values are `dict` per symbol, except `__overnight_catalysts__` which is a `list` — always use `isinstance(ctx, dict)` guard when iterating
2. All agents must handle `market_context` with non-dict values gracefully
3. Force-trading loop wakes within 10 seconds of `app_state.force_trading` being set
4. Sentinel polls every 5 min during market hours, 15 min overnight
5. NYSE regular hours only: 9:30–16:00 ET — no pre/after-hours trading
6. `OLLAMA_ONLY_MODE=1` must route ALL three AI agents (Claude, Gemini, Sentiment) through Ollama — never call cloud APIs in this mode; token logging is skipped (zero cost, no quota)
7. `Portfolio` has no `get_position()` method — always access positions via `portfolio.positions[sym]` (check with `sym in portfolio.positions`; read shares with `.shares`)
8. `__MACRO__.parquet` uses a `__`-prefixed filename — `symbols_with_data()` and `get_training_data()` must filter out any `__`-prefixed entries to prevent KeyError on per-symbol signal history calls
9. **`performance` table is NEVER date-pruned** (user policy 2026-05-16: "continuity for all trades, not just days"). `prune_news_price_snapshots` still runs on its own 14-day window. Re-introducing `prune_performance_table` or any equivalent would silently lose week-over-week diagnostic visibility — see `feedback_performance_history_retention.md`.
10. **`backend/data/mc_backtester.py` and `backend/agents/cnn_decision.py` may NOT import** `CNNReasoningAgent`, `OllamaAgent`, `EnsembleAgent`, `main`, or `database` (user policy 2026-05-16: "loosely coupled software, where the MC can consume the 8 channel but not combine them"). `cnn_decision.py` further restricts to `dataclasses` + `typing` only — config is passed as a parameter, not imported. These boundaries are why the same `decide_buy` helper drives production AND backtest with one source of truth — see `feedback_loose_coupling.md`.

## Trading policy defaults (env-tunable; tightened 2026-05-16)
- `TRAIL_GIVEBACK_PCT=0.10` — trailing-stop fires when current unrealized PnL has fallen 10 % below peak (was 0.20 before 2026-05-16; loose default cost ~$30K of peak portfolio value in chop)
- `TRAIL_ARM_USD=100.0` — trailing arms only once peak unrealized PnL reaches $100 (was $25; raises arm noise floor)
- `TRAIL_COOLDOWN_HOURS=4.0` — after any trailing-stop SELL fires, new BUYs across the agent's portfolio are blocked for this many hours. SELLs are never blocked. `0` disables. State lives in `BaseAgent._last_trail_stop_ts` (in-memory, non-persistent across restart).
- `XGB_FEATURE_FILTER` — 8-channel production set (reverted from 16-ch on 2026-05-16; 16-ch had fold-2 IC ≈ 0 in current regime). Both `signal_xgb.json` (main) and `signal_xgb_b{0..9}.json` (ensemble) must train on the **same** filter — `scripts/train_xgb_ensemble.py` now reads the env so they stay aligned.
