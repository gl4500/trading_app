# trading_app R&D Pod — Claude Managed Agents (CMA) Design Spec

- **Date:** 2026-06-21
- **Status:** Approved design (brainstorming complete) — pending implementation plan
- **Scope:** `trading_app` ONLY. This crew must never touch `polymarket_app` files.
- **Author:** R&D-loop brainstorming session

---

## 1. Purpose

Stand up a **multi-agent R&D + build crew** on Claude Managed Agents (CMA) that runs the
operator's fail-fast model-improvement loop end to end, autonomously:

> hypothesis -> cheap probe on real data -> debate pros/cons -> log verdict -> (if it survives) build with TDD -> merge -> record outcome -> iterate.

The crew optimizes a single north-star metric: **realized PnL by regime** (bull / neutral /
bear / high_vol), measured against `trading.db` x SPY-derived regime labels — the same lens
that resolved the negative-WFE alarm (see `docs/model_improvement_ledger.md`).

It encodes the operator directive verbatim (`feedback_fail_fast_iterate`):

1. Probe cheaply **before** building infrastructure.
2. Every attempt logs its verdict to the persistent ledger (`docs/model_improvement_ledger.md`).
3. Consult prior outcomes (trial count N, live-vs-backtest deltas) before the next decision.
4. **Never loosen an honest falsifier when it says no.** A REJECT that prevents deploying
   noise is a success, not a failure.

---

## 2. North-star metric & success criteria

- **Primary:** realized PnL by regime from `trading.db` joined to SPY regime labels.
- **Supporting (diagnostic, never the gate by itself):** IC, WFE, calibration by fold/regime.
- A hypothesis "wins" only when it **improves realized PnL in the targeted regime without
  degrading the others**, survives the Skeptic's leakage/overfit attack, and ships behind a
  green test suite.
- WFE is explicitly a *diagnostic*, not a target — iter 1-6 of the ledger proved it can
  mis-measure a real edge. The crew must not chase WFE in isolation.

---

## 3. Architecture overview

```
                +----------------------------------------------+
                |  Self-hosted CMA Environment (operator's PC)  |
                |  worker sees: trading_app repo, runtime/python|
                |  /python.exe, trading.db (RO), parquets, GPU  |
                +----------------------------------------------+
                                     |  one Session per iteration
                                     v
   +--------------------------------------------------------------------+
   |  Coordinator agent: RESEARCH LEAD  (multiagent roster of 3)        |
   |  reads ledger -> picks hypothesis -> referees -> verifies ->       |
   |  merges -> writes verdict                                          |
   +-------+-------------------+-----------------------+----------------+
           | delegate          | delegate              | delegate
           v                   v                       v
   +---------------+   +------------------+   +------------------+
   | QUANT         |   | RED-TEAM         |   | BUILDER          |
   | RESEARCHER    |   | SKEPTIC          |   | (TDD, GO only)   |
   | (pro / probe) |   | (con / falsify)  |   |                  |
   +---------------+   +------------------+   +------------------+
```

- **1 self-hosted Environment** — worker runs on the operator's PC so probes hit real local
  data (`trading.db`, parquets, `runtime/python/python.exe`, GPU). A cloud sandbox cannot
  work here: the data and runtime are local and gitignored.
- **1 Coordinator agent (Research Lead)** with a `multiagent` roster of 3 subagents.
  `multiagent` is a **top-level field on the coordinator agent**, not a tool and not on the
  session.
- **1 Session per iteration** — one running container/filesystem shared by all four agents;
  each agent runs in its **own thread with isolated history**. The Lead must pass everything a
  subagent needs *inside the delegated message* (subagents do not see each other's or the
  Lead's history).
- **One level of delegation only** — subagents cannot spawn their own subagents.

### Roster (4 agents, all `claude-opus-4-8`, high reasoning effort)

| Agent | Role | Tools |
|-------|------|-------|
| **Research Lead** (coordinator) | Reads ledger; picks the next hypothesis; frames the debate; **referees GO/NO-GO** on realized-PnL terms; after a GO build, **independently verifies** (suite green + scope-isolation + `trading.db` untouched); merges to `main`; appends the verdict to the ledger. The Verifier role is folded in here. | agent_toolset_20260401 (+ `run_probe` custom tool, see section 6) |
| **Quant Researcher** (pro) | Proposes **ONE falsifiable hypothesis** and the **cheapest probe** that could kill it; runs the probe on real data; reports raw numbers (PnL-by-regime, IC, sample sizes) with no spin. | agent_toolset_20260401 (+ `run_probe`) |
| **Red-Team Skeptic** (con, independent) | Attacks every probe for leakage, look-ahead, overfit, selection bias, regime artifact, insufficient N. Issues an explicit **GO / NO-GO** ruling with reasons. Independent of the Builder. | agent_toolset_20260401 (+ `run_probe`) |
| **Builder** (TDD) | Only engages on a GO. Tests first (red -> green -> refactor), implements the change, runs the **full** suite. Reports evidence. | agent_toolset_20260401 |

---

## 4. Iteration flow (one Session = one hypothesis)

1. **Lead — orient.** Read `docs/model_improvement_ledger.md` (newest on top) + relevant
   memory. Pick the next hypothesis. Default first target: **H12** — non-gated rule agents
   (Momentum / MeanRev / Tech / HistTrends) bleed **-$19.3K in bear** (244 closes, 37% win);
   port the XGB agent's proven bear gate to them via a shared `BaseAgent` entry gate.
2. **Researcher — frame + probe.** Restate the hypothesis as a single falsifiable claim, name
   the cheapest probe that could falsify it, run it (read-only on `trading.db`), report numbers.
3. **Skeptic — attack.** Independently scrutinize for leakage / overfit / selection bias /
   regime artifact / small-N. Rule **GO** or **NO-GO** with explicit reasons.
4. **Lead — referee.**
   - **NO-GO** -> append verdict to the ledger (hypothesis, probe, numbers, why rejected) and
     **end the iteration**. A clean reject is a successful outcome.
   - **GO** -> continue to build.
5. **Builder — TDD.** Tests first, implement, run the full suite, report evidence.
6. **Lead — verify + merge.** Independently confirm: full suite green; scope-isolation held
   (no `polymarket_app` paths touched); `trading.db` untouched (read-only); change matches the
   approved hypothesis. If all pass -> merge to `main` (auto). Else -> bounce back to Builder.
7. **Lead — record.** Append the outcome (shipped / rejected, numbers, live-vs-backtest note)
   to `docs/model_improvement_ledger.md` and stop. Next iteration is a fresh Session.

---

## 5. Safety gates & autonomy

Operator chose **full autonomy including auto-merge to `main`.** Because this is a trading
system, autonomy is fenced by hard gates — **all** must pass before any merge:

1. **Honest-falsifier gate** — Skeptic must rule GO on the probe. The falsifier is never
   loosened to manufacture a GO (directive #4).
2. **Green-suite gate** — the full test suite passes (Builder runs it; Lead re-verifies).
3. **Scope-isolation gate** — no file outside `trading_app` is read or written; specifically
   **zero** `polymarket_app` paths. Enforced by the Lead's pre-merge diff inspection.
4. **Data-integrity gate** — `trading.db` is **read-only** to every probe. Probes open it
   read-only / copy-to-temp; any write attempt fails the iteration.
5. **Independent verification** — the Lead's verification is separate from the Builder's
   self-report (Verifier folded into Lead, but still a distinct check from the build step).
6. **Rollback** — every change is a normal commit on `main`; rollback = `git revert`. No
   force-push, no history rewrite.

**Residual risk (flagged):** auto-merge to `main` on a trading system means a bad change can
land without a human in the loop between Skeptic-GO and merge. The gate stack above is the
compensating control; the operator accepted this trade-off for iteration speed. Revisit if the
crew ever touches live-trading execution paths (today it operates on models/agents/backtests).

---

## 6. Infrastructure & Windows-worker plan

- **Environment config:** `{ "type": "self_hosted" }`. Worker runs on the operator's PC via
  the Python `EnvironmentWorker` (or `ant beta:worker poll`). Note CMA self-hosted constraints:
  **env-var vault credentials and memory-stores are NOT supported self-hosted** — pass any
  secrets via the worker's own process env, and keep cross-iteration memory in the in-repo
  ledger (which we already do).
- **Windows runtime risk — VALIDATE FIRST (implementation step 1).** The worker's `bash` tool
  needs a real POSIX shell on Windows, and probes must call the Windows-native
  `runtime/python/python.exe`. Plan:
  - **Primary:** run the worker under **Git Bash** (or WSL) so `bash`/`read`/`grep` work, and
    have probes invoke `runtime/python/python.exe` directly.
  - **Fallback:** a custom host-side tool **`run_probe`** that executes a probe script with the
    project's Python and returns stdout/exit code — bypasses any bash-on-Windows fragility.
  - This is the **first thing to prove** before building the roster, per "probe cheaply before
    infrastructure." A throwaway hello-world probe that reads `trading.db` read-only and prints
    a row count validates the whole worker -> python -> data path.
- **Kickoff:** on-demand (operator starts a Session when they want an iteration), not a cron.
- **Reusability:** the same 4-agent pattern is later cloned for the Coinbase / `polymarket_app`
  crew, pointed at that repo + its own ledger. Keep agent system prompts parameterized on
  {repo path, ledger path, north-star query} so the clone is config-only.

### CMA object creation order (must follow)

1. Create the **3 subagents** (Researcher, Skeptic, Builder) -> capture their IDs.
2. Create the **coordinator** (Research Lead) with `multiagent` listing the 3 subagent IDs.
3. Create the **self-hosted Environment** once.
4. Per iteration: create a **Session** referencing the coordinator `agent_id` + the
   environment; stream events; one hypothesis per session.

`model` / `system` / `tools` / `multiagent` live on the **agents**, created once and referenced
by ID. The **session** takes only the `agent_id` (+ environment) — never model/tools/system.

---

## 7. Out of scope (this spec)

- Any change to `polymarket_app` (separate future crew, separate repo/ledger).
- Live-trading execution-path changes (crew operates on models/agents/backtests only).
- Cloud sandbox execution (infeasible: local gitignored data + runtime).
- A cron / always-on schedule (kickoff is on-demand for v1).

---

## 8. Open questions to resolve in the implementation plan

1. Exact `run_probe` tool contract (args, cwd, timeout, read-only DB enforcement) vs. relying
   on Git Bash + `python.exe`. Decide after the step-1 validation probe.
2. How the Lead programmatically enforces the scope-isolation + `trading.db`-untouched gates
   (git diff inspection vs. a pre-merge hook script).
3. Whether iterations should write a machine-readable verdict record alongside the prose ledger
   entry, to feed directive #3 (trial count N, deflation as N grows).

---

## 9. Provenance

- Loop philosophy: `feedback_fail_fast_iterate` (operator directive, 2026-06-13).
- Current ledger state & H12 lever: `docs/model_improvement_ledger.md` (iter 6 resolution).
- Architecture grounding: `trading_app_architecture` memory (XGBReasoningAgent, WFE gate, W3
  blend, regime_detector).
- CMA mechanics: `managed-agents-2026-04-01` beta — Agent -> Environment -> Session flow,
  top-level `multiagent` coordinator, self-hosted worker constraints.
