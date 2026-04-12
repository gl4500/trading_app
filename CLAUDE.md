# CLAUDE.md — AI Trading App Coordination Contract

This file is read by all Claude Code agents working on this repository.
It defines responsibilities, workflows, and rules that every agent must follow.

---

## Scope

**Only modify files inside `C:\Users\gl450\trading_app\`.**
Never touch `radioconda\`, `.spyder-py3\`, or any other directory in the user's home folder.

---

## Two-Agent Setup

| Agent | Role | Owns |
|---|---|---|
| **Implementation agent** (main Claude Code session) | Feature work, bug fixes, refactors | `backend/`, `frontend/`, `README.md` |
| **Testing sub-agent** (separate session) | Unit & component tests, test infrastructure | `backend/tests/`, `backend/pytest.ini`, `backend/tests/conftest.py` |

**Coordination via filesystem:** both agents read/write files — the contract below prevents conflicts.

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

---

## Architecture Quick Reference

- **Backend:** FastAPI + asyncio, port 8000
- **Frontend:** React + Vite + Tailwind, port 5173
- **DB:** SQLite via aiosqlite (`trading.db`)
- **Market data:** Alpaca Markets (paper trading)
- **AI agents (cloud mode):** Claude Opus 4.6, Gemini 2.0 Flash, GPT-4o-mini
- **AI agents (Ollama mode):** All three above route to local Ollama when `OLLAMA_ONLY_MODE=1`
- **Local inference:** Ollama at `http://localhost:11434/v1` (OpenAI-compatible); `OLLAMA_MODEL` for Sentiment/Gemini/CNN; `RESEARCH_MODEL` for Claude (defaults to `OLLAMA_MODEL`)
- **Current Ollama model:** `qwen2.5:7b` (~4.5 GB Q4) — stronger structured JSON output and reasoning than llama3.1:8b, fits RTX 2060 with headroom.
- **GPU constraint:** RTX 2060 = 6 GB VRAM — only one Q4 model fits at a time. Set `RESEARCH_MODEL=OLLAMA_MODEL` to share the single loaded model; never configure two different models simultaneously on this GPU.
- **Config:** `.env` → `backend/config.py` → `config` singleton
- **Agent context key:** `market_context["__overnight_catalysts__"]` is a `list` — all agents guard with `isinstance(ctx, dict)` when iterating

## Key invariants (never break these)
1. `market_context` values are `dict` per symbol, except `__overnight_catalysts__` which is a `list` — always use `isinstance(ctx, dict)` guard when iterating
2. All agents must handle `market_context` with non-dict values gracefully
3. Force-trading loop wakes within 10 seconds of `app_state.force_trading` being set
4. Sentinel polls every 5 min during market hours, 15 min overnight
5. NYSE regular hours only: 9:30–16:00 ET — no pre/after-hours trading
6. `OLLAMA_ONLY_MODE=1` must route ALL three AI agents (Claude, Gemini, Sentiment) through Ollama — never call cloud APIs in this mode; token logging is skipped (zero cost, no quota)
7. `Portfolio` has no `get_position()` method — always access positions via `portfolio.positions[sym]` (check with `sym in portfolio.positions`; read shares with `.shares`)
