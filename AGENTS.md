# AGENTS.md — trading_app (AI Trading Competition)

This is the project contract for every agent working in this repository. Codex loads it automatically;
Claude Code loads it through the `@AGENTS.md` import in `CLAUDE.md`, which adds only Claude-specific
rules (the memory sync rule). Read all of it before your first task here. Where this file and
`CLAUDE.md` or a mandatory reference disagree, stop and ask the operator.

Reviews follow `C:\Users\gl450\.coordination\trading_app\PEER_REVIEW.md` (shared findings ledger,
requirements and testing standard). Multi-agent work also follows
`C:\Users\gl450\.agent-forum\AGENT_FORUM_FRAMEWORK.md`.

## Mandatory references

Moved out of this file verbatim to stay under Codex's 32 KiB project-instruction limit. They are part
of the contract, not background reading: read the file before the work in the right-hand column.

| File | Contains | Read before |
|---|---|---|
| `docs/agents/trading-policy-defaults.md` | Normative env-tunable trading policy defaults and opt-in knobs (trail stop, W3 blend, vol-target, term-structure gate, LLM decision mode, HistoricalTrends knobs) | Changing or reviewing anything under `backend/agents/`, `backend/trading/`, `backend/data/*model*`, `backend/config.py` or `.env` defaults |
| `docs/agents/test-coverage.md` | Module → test file coverage table | Adding or reviewing a test module (update the table in the same change) |

## Roles (assigned per task, not per agent)

Either agent can be author or reviewer. Roles are fixed here; who fills them is set per task.

| Role | Must | Must not |
|---|---|---|
| **Author** | Claim the task; work on its own branch or worktree; write the failing test first; request review with the head SHA, what changed and the evidence (PEER_REVIEW.md record) | Approve its own work; confirm its own finding; merge |
| **Reviewer** | Inspect the exact head SHA; check each decision-critical claim itself; give the strongest objection; reply APPROVE naming the SHA, or numbered defects, plus a forum status | Push to the author's branch (it proposes fixes instead); approve a SHA it did not inspect |
| **Operator** | Clicks merge; restarts the live app; approves test windows and anything irreversible; decides disputes, NO_CONSENSUS and role swaps | — |

**Assignment.** Each task has one record, set when it starts, at
`C:\Users\gl450\.coordination\trading_app\tasks\<task-id>.yaml` (next to the shared findings ledger):

```yaml
task: <id>          # also named in every review request and verdict
author: claude      # or codex
reviewer: codex     # always the other agent
operator: gl4500
scope: [paths]
branch: <branch>
```

- Default: whoever claims the task is the author. Swaps only by the operator or an explicit handoff message.
- **Codex as author:** Codex never edits Claude's memory folder. It records each change in the PR description
  and the findings ledger; the Claude reviewer updates memory after merge.
- Mailbox: `C:\Users\gl450\.coordination\trading_app\mailbox.py` only. Never the polymarket session link.
  Agents: Claude in the trading_app workspace, `ta-codex` (Herdr names).

---

## Scope

**Only modify files inside `C:\Users\gl450\trading_app\`.**
Never touch `radioconda\`, `.spyder-py3\`, or any other directory in the user's home folder.
Two exceptions: the shared Claude memory folder (`C:\Users\gl450\.claude\projects\C--Users-gl450\memory\`),
and cross-project work the operator has explicitly authorized for that task.

- For running tests, only use `C:\Users\gl450\trading_app\runtime\python\python.exe` — never fall back to radioconda or any system Python.
- pytest is not installed in that runtime; tests run through `backend/run_tests.py` (unittest discovery). Do not install pytest into it or switch runtimes without asking the operator.

### Fresh install infrastructure
- New-machine setup: `scripts/setup_fresh.bat` (double-click) or `scripts/setup_fresh.ps1`
- Downloads Python 3.12, Node.js 22 LTS, all packages, generates certs, creates `.env` automatically
- Offline wheel cache: `backend/packages/` (committed to git — excludes torch, which is downloaded by the script)
- Do NOT remove `.env.example` or `backend/requirements.txt` — they are the source of truth for the setup script

---

## Two-Agent Setup

Roles are assigned **per task**, not per agent: either Claude Code or Codex can be the author, and the
other agent is then the reviewer. The role definitions and the per-task assignment record live in
"Roles" below. In short (policy as of 2026-11-14):

| Role | Does |
|---|---|
| **Author** (either agent) | Writes the failing test, the code and the docs. May delegate test-writing to a subagent if it says so in the review request. |
| **Reviewer** (the other agent) | Reviews every change before merge under `~/.coordination/trading_app/PEER_REVIEW.md` and replies APPROVE naming the head SHA, or a numbered defect list. |
| **Operator** | Clicks merge, restarts the live app. |

The **File Ownership** section below applies only when a separate testing sub-agent session is used.

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
1. Write a failing test  →  backend/tests/test_<module>.py   (the task's author, or a delegate the author discloses)
2. Implement the code
3. Run tests from the backend\ of the checkout that holds your change (see "Running tests"):
   cd <your checkout>\backend && C:\Users\gl450\trading_app\runtime\python\python.exe run_tests.py -v
4. Verify GREEN before committing; the task's assigned reviewer (the other agent) signs off on the exact head SHA before merge
5. Commit:  git commit -m "<msg>" -- tests/<file> <module.py>
```

No code change is committed without a corresponding test. No exceptions for "small" fixes.
Documentation-only changes (markdown, comments, CLAUDE.md/AGENTS.md wording) need link and
consistency checks instead of behavioral tests.

---

## File Ownership

Applies only when a separate testing sub-agent session is used (see Two-Agent Setup).

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

- Framework: `unittest.TestCase`, run by `backend/run_tests.py` (unittest discovery; pytest is not installed in the runtime)
- Async tests: `unittest.IsolatedAsyncioTestCase`
- **No live API calls** — mock `anthropic`, `openai`, `alpaca`, `yfinance`, `httpx`
- **No real DB writes** — use `tempfile.mkstemp()` for database tests
- **No real file I/O** — mock `learning.json`, `agent_picks.json`, `scan_cache.json`
- Shared fixtures live in `tests/conftest.py` — don't duplicate setup across files
- One test file per module: `agents/foo.py` → `tests/test_foo.py`

### Running tests
Always use the installed interpreter by its absolute path, and run it from the `backend\` folder of
the checkout that holds the code under test:

```bash
cd <your checkout>\backend
C:\Users\gl450\trading_app\runtime\python\python.exe run_tests.py -v    # full suite (verbose)
C:\Users\gl450\trading_app\runtime\python\python.exe run_tests.py       # full suite (summary only)
```
Note: pytest is not installed in the self-contained runtime. Use `run_tests.py` (unittest discovery).

`run_tests.py` tests the code next to it: it puts its own `backend\` folder and `..\site-packages`
on the path. So the tested code is whichever checkout you `cd` into, and that checkout needs a
`site-packages` folder:

- **Main checkout** (`C:\Users\gl450\trading_app`): `site-packages\` is already there. Only work
  here when no other session is using this checkout; changes under review belong in a worktree.
- **Isolated worktree** (preferred for changes under review): `runtime\` and `site-packages\` are
  gitignored, so a new worktree has neither. Before running tests, link the installed packages in
  read-only use, and remove the link when done:
  ```bat
  mklink /J <worktree>\site-packages C:\Users\gl450\trading_app\site-packages
  rem ... run tests from <worktree>\backend as above ...
  rmdir <worktree>\site-packages
  ```
  Remove the link only with `rmdir` on that exact path. `rm -rf` or `Remove-Item -Recurse` can follow
  the junction and delete the real packages. Never install or upgrade packages through the link.
  The pre-commit hook needs the same link, because it scans with `<checkout>\site-packages` on the path.

Tests never touch the live `trading.db` or the broker (see Test Conventions).

### Shell cleanup — required after every test run

Running tests repeatedly causes background bash+python processes to stack up. After any test run,
clean up **only your own** test processes, identified by command line. Never a blanket sweep: it can
take down the live backend on port 8000, training workers and the Claude/Codex mailbox servers.
(The old `ps aux | grep python | ... | xargs kill -9` recipe was removed 2026-11-14; it was also
malformed, since `$1` in `ps aux` output is the user column, not the PID.)

```powershell
# 1. List and decide. 2. Kill only PIDs you can name as your own test run, as a separate step.
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Select ProcessId, ParentProcessId, CommandLine
```

Exclude at minimum: the live backend (`main.py` / uvicorn on 8000) and its parent or children,
anything under `rnd_pod\` or `.coordination\`, and anything whose path is outside this repository.

Rules:
- **Prefer per-module tests** (from `<your checkout>\backend`: `set PYTHONPATH=..\site-packages` then `C:\Users\gl450\trading_app\runtime\python\python.exe -m unittest tests.<module>`) over the full suite during development — faster, stays foreground, no stacking
- **Only run the full suite once** before committing, not repeatedly
- **Always clean up** after a test run completes or is interrupted

---

## Commit Standards

```
feat: short description of new feature
fix:  short description of bug fixed
test: add/update tests for X
docs: update README, AGENTS.md or CLAUDE.md
refactor: internal cleanup, no behavior change
security: security hardening, SAST fixes, secret scanning
```

Every commit that changes behavior includes both the implementation file and its test file;
`docs:` commits are exempt (see TDD Workflow). Commit with an explicit pathspec
(`git commit -m "<msg>" -- <paths>`), never `git commit -a`.
Co-Authored-By line required (added automatically by implementation agent).

---

## Security Gate — Pre-commit Hook

Every `git commit` runs `.git/hooks/pre-commit` automatically (3 steps, < 10 sec):

1. **Block staged env files** — prevents API keys reaching GitHub. Matches `.env`, `.env.local`, `.env.bak.YYYY-MM-DD`, `prod.env`, `backend/.env` — everything except the tracked `.env.example` template. Widened 2026-08-02 after an `.env.bak` written during a config change sat in the repo as an untracked file, outside both the old hook pattern and the old `.gitignore` rule.
2. **Secret pattern scan** — rejects Anthropic/OpenAI/Google/AWS/Alpaca key patterns in staged `.py/.ts/.js/.json` files
3. **Bandit SAST** — medium+/medium+ severity, excludes `tests/`, uses `site-packages/` runtime

**Operator rule — env files never enter the repo.** `.env` holds live API keys. Never commit it, never
copy it to a path inside the repo (`.env.bak`, `.env.save`, `.env.old` — all forbidden, even untracked,
because the next `git add -A` sweeps them up). When you need a backup before editing `.env`, write it
**outside the repo tree** (the session scratchpad). Two layers enforce this: the `.gitignore` block at the
top of the file, and step 1 of the pre-commit hook. `.env.example` is the one tracked exception and must
be kept.

**Secrets in logs (finding C-2, 2026-10-11).** Massive (`apiKey=`) and FRED (`api_key=`) authenticate with URL
query parameters, and httpx logs every request URL at INFO, so keys were written to `live.log` and
`backend_stderr.log`. `logging_setup._RedactSecrets` masks `*api_key*` / `*apikey*` / `*token*` / `*secret*`
query values; `install_logging()` attaches it to the `httpx`/`httpcore` loggers and to every root handler.
Never log a URL or header carrying a credential some other way, and never remove either layer.

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

## Architecture Quick Reference

- **Backend:** FastAPI + asyncio, port 8000
- **Frontend:** React + Vite + Tailwind, port 5173
- **DB:** SQLite via aiosqlite (`trading.db`)
- **Market data:** Alpaca Markets (paper trading)
- **Active trading roster (deprecations 2026-07-05 + 2026-10-10):** Only 3 models are registered for trading — HistoricalTrendsAgent (+17.9%), MeanReversionAgent (+22.9%), XGBReasoningAgent (+11.2%): the agents whose split-corrected total return on their $100K, valued at 2026-08-12 closes, clears 10% with full price coverage (R3 reconstruction, independently replicated; operator decision 2026-10-10). **Deprecated (unregister-only):** 2026-07-05 for net-negative/idle PnL — EnsembleAgent, ClaudeAgent, TechAgent, GeminiAgent, OllamaAgent, OpenClawAgent; 2026-10-10 for not being confirmed above 10% — MomentumAgent (+10.2% with one unpriced holding at cost, +7.3% at zero), ScannerAgent/ScannerPortfolioAgent (+5.2%), SentimentAgent (+0.0%). Earlier figures that put MeanReversion at +7.8% included a phantom −$7.8K loss from an unadjusted BKNG 25:1 split. Deprecation does NOT wind down a deprecated agent's open positions. Code + historical DB rows stay; they are just not built/registered. `lifespan._build_trading_agents()` is the single source of truth (re-enable = append the class there). `app_state.gemini_news_agent = None` (Gemini context injection + API calls off). See `trading_app_architecture.md` → "Active Trading Roster".
- **AI agents (cloud mode):** Claude Opus 4.6, Gemini 2.0 Flash, GPT-4o-mini (ClaudeAgent + GeminiAgent deprecated 2026-07-05 — see roster note above)
- **AI agents (Ollama mode):** All three above route to local Ollama when `OLLAMA_ONLY_MODE=1`; off-hours auto-scan runs every `OLLAMA_CLOSED_SCAN_MIN=30` min when market is closed (cloud mode is unchanged)
- **Local inference:** Ollama at `http://localhost:11434/v1` (OpenAI-compatible); `OLLAMA_MODEL` for Sentiment/Gemini/XGB; `RESEARCH_MODEL` for Claude (defaults to `OLLAMA_MODEL`)
- **Current Ollama model:** `llama3.1:8b` (~4.7 GB Q4) — reliable instruction following and structured JSON; fits RTX 2060 with headroom.
- **GPU constraint:** RTX 2060 = 6 GB VRAM — only one Q4 model fits at a time. Set `RESEARCH_MODEL=OLLAMA_MODEL` to share the single loaded model; never configure two different models simultaneously on this GPU.
- **Config:** `.env` → `backend/config.py` → `config` singleton
- **Agent context key:** `market_context["__overnight_catalysts__"]` is a `list` — all agents guard with `isinstance(ctx, dict)` when iterating
- **Leading-regime score (added 2026-06-08):** `data/regime_leading.py::compute_leading_score()` returns a score in `[-1, +1]` combining VIX term structure (VIX/^VIX3M), HYG 5d momentum, cyclical-vs-defensive sector spread, and IWM-vs-SPY breadth. Emitted as `[REGIME_LEAD]` log line every macro fast-cache refresh (~15 min). Read-only observation for now — wired into XGB feature / WFE gate only after ~1 trading day of data confirms it leads the reactive `regime_detector.get_regime()` flip. `^VIX3M` and `HYG` added to `MACRO_PROXIES` to feed it. Pure function — no imports from agents/main (loose-coupling invariant #10).

- **Tax estimate:** `GET /api/tax/estimate?year=YYYY` — federal capital gains summary (short/long-term, wash sales, quarterly) from real Alpaca trade history
- **R&D pod (`rnd_pod/`, added 2026-06-25):** 4-agent Claude Managed Agents crew (Research Lead coordinator + Quant Researcher / Red-Team Skeptic / Builder) that runs the fail-fast model-improvement loop autonomously, optimizing realized PnL by regime and logging verdicts to `docs/model_improvement_ledger.md`. **CMA SDK (`anthropic>=0.111.0`) lives ONLY in the git-ignored `rnd_pod/.cma-venv` — NEVER `pip install anthropic` into `site-packages/` or `runtime/` (the live app pins `anthropic==0.84.0`).** Probes run under `runtime/python/python.exe` and open `trading.db` read-only. On-demand only — never run the pod while the live backend is trading/training. Tests: `runtime/python/python.exe -m unittest discover -s rnd_pod/tests`. Runbook: `rnd_pod/README.md`; details in `trading_app_rnd_pod_cma.md` memory.

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
10. **`backend/data/mc_backtester.py` and `backend/agents/xgb_decision.py` may NOT import** `XGBReasoningAgent`, `OllamaAgent`, `EnsembleAgent`, `main`, or `database` (user policy 2026-05-16: "loosely coupled software, where the MC can consume the 8 channel but not combine them"). `xgb_decision.py` further restricts to `dataclasses` + `typing` only — config is passed as a parameter, not imported. These boundaries are why the same `decide_buy` helper drives production AND backtest with one source of truth — see `feedback_loose_coupling.md`. (Renamed from `cnn_decision.py` / `CNNReasoningAgent` in issue #75 — terminology now matches the XGBoost backend the code actually uses.)
10a. **Backtesting:** for a full-chassis re-selection A/B (not just the MC channel probe above), use `scripts/reselection_backtest.py` — drives the real `BaseAgent.run_cycle` over point-in-time bars via `backend/backtest/{bars_provider,reselection}.py`. Spec: `docs/superpowers/specs/2026-08-08-reselection-backtest-harness-design.md`.
11. **`config.DATABASE_URL` default must stay anchored to `backend/` via `__file__`** (added 2026-05-17). Relative-to-cwd defaults silently create empty stray `trading.db` files at whatever cwd the backend was started from → "data vanished" symptom. The DATABASE_URL env var override path still works for users who explicitly set it.
12. **Trade history has TWO persistent stores** (added 2026-05-17): authoritative `backend/trading.db` (SQLite, never date-pruned) AND a daily parquet snapshot at `backend/data/trade_history/trades-YYYY-MM-DD.parquet` (gitignored). The parquet is written by `database.dump_trades_to_parquet()` at lifespan startup + every 1440 cycles. Idempotent within a UTC day. For disaster recovery, load the most recent parquet via `pd.read_parquet(...)` and `to_sql('trades', ..., if_exists='append')`.
13. **Cash is always derived from trade-history replay on restart** (added 2026-05-17, issue #64). `init_agents` calls `_reconcile_cash_from_trades()` — the trade ledger is the source of truth; the `performance.cash` snapshot is only a cross-check. Snapshot vs replay drift > $1 logs CRITICAL and auto-repairs to the replay value. Additionally, `BaseAgent.run_cycle` asserts the per-cycle invariant `cash + cost_basis_open - realized_pnl == starting_capital` and logs CRITICAL on drift > $1 — surfaces future drift immediately instead of compounding silently (HistoricalTrendsAgent had silently accumulated $18,720.78 of phantom cash before this gate).
14. **W3 is co-trained with every XGB retrain** (added 2026-05-23). `XGBReasoningAgent._train_blocking` calls `signal_cnn.fit/save` **and** `signal_w3.fit/save` on the same data so the blend stays consistent. If only one is retrained the prediction blend mixes models trained on different vintages of the dataset. W3 failure inside `_train_blocking` is non-fatal and logs WARNING — the agent continues with stale-W3 blend or, if W3 was never loaded, XGB-only inference.
15. **Walk-forward CV must time-embargo the full label horizon** (added 2026-06-25, H1 fix). `data/cnn_evaluation.walkforward_folds` takes `embargo_days` (default `0.0` = backward compatible); the effective embargo is `max(embargo_bars rows, embargo_days calendar days)`. All three model `fit()` methods (`SignalCNN`, `SignalXGBoost`, `SignalW3`) pass `embargo_days=LABEL_HORIZON_DAYS` (=10, derived from `return_10d`). A row-count-only embargo silently leaks a multi-day forward label into validation under dense/intraday bars — never revert these calls to `embargo_bars`-only. See `trading_app_bugs_fixed.md` (2026-06-25 entry).

---

## Checklists by pause point

**Session start (both)**
1. Read the trading_app mailbox inbox; ack what you read.
2. `git status` and `git stash list`: unfamiliar changes are another agent's work. Don't touch them.
3. Confirm the task stays inside this repo (Scope).

**Before running anything that uses this machine (both)**
1. Use only `C:\Users\gl450\trading_app\runtime\python\python.exe`; run `backend\run_tests.py` from the
   checkout that holds the code under test, which needs a `site-packages` link if it is a worktree
   (Running tests).
2. Never test against the live `trading.db` or the broker; use temp DBs and mocks (Test Conventions).
3. Clean up only processes you can name as your own, by command line (Shell cleanup).

**Live-backend guard**
`tools/agent_guard/live_guard.py` is a PreToolUse hook for both agents (`.claude/settings.json`,
`.codex/hooks.json`). While port 8000 is listening (or its state can't be determined) it blocks test runs and
process kills. Test runs pass only during an operator test window: a gitignored `.agent-test-window` file at the
repo root holding an ISO-8601 expiry with timezone (e.g. `2026-11-14T22:00:00-05:00`). Kills always need the
operator.

- **Claude:** active whenever this checkout's `.claude/settings.json` loads; a failing hook blocks the command.
- **Codex:** active only after the operator trusts the project hooks (`/hooks`), in a project Codex trusts.
- **If the hook itself breaks** and blocks everything, only the operator restores it, for example by
  temporarily renaming `.claude/settings.json` locally (never committed). Agents never weaken the guard.
- It is a guardrail against mistakes, not a security boundary. Tests: `tools/agent_guard/test_live_guard.py`.

**Author: before requesting review**
1. Fresh branch off `main`; commit with `git commit -m "<msg>" -- <paths>`; check `git log -1 --stat`.
2. Evidence per PEER_REVIEW.md: requirement IDs, old-fail/new-pass, commands and outputs.
3. Send: PR link, head SHA, what changed, how it was verified, specific questions.

**Reviewer: each review**
1. Review the exact head SHA named in the request; read the diff against its merge base.
2. Check each decision-critical claim yourself; never confirm your own finding.
3. Give the strongest consequential objection before agreeing.
4. Reply APPROVE naming the SHA, or a numbered defect list. An acknowledgement is not approval.
5. End with a forum status: CONSENSUS, CONDITIONAL_CONSENSUS, NO_CONSENSUS or INSUFFICIENT_EVIDENCE.

**Before merge**
1. Every new commit or rebase goes back to the reviewer with the new SHA and delta.
2. Required checks green; findings fixed or explicitly waived by the operator.
3. Hand the operator the PR link and approved SHA; the operator clicks merge and restarts.
