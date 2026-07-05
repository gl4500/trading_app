# rnd_pod — trading_app R&D crew (Claude Managed Agents)

4-agent fail-fast R&D loop (Research Lead + Quant Researcher + Red-Team Skeptic + Builder).
Design spec: `docs/superpowers/specs/2026-06-21-trading-app-rnd-pod-cma-design.md`.
Implementation plan: `docs/superpowers/plans/2026-06-21-trading-app-rnd-pod-cma.md`.

The crew optimizes **realized PnL by regime** (bull/neutral/bear/high_vol) and logs every
verdict to `docs/model_improvement_ledger.md`. The CMA SDK runs in an isolated venv
(`rnd_pod/.cma-venv`, `anthropic>=0.111.0`); the live app's pinned `anthropic==0.84.0` is never
touched. Probes run under the app runtime (`runtime/python/python.exe`), which has
pandas/xgboost/sqlite.

## One-time setup
1. `runtime/python/python.exe -m venv rnd_pod/.cma-venv`
2. `rnd_pod/.cma-venv/Scripts/python.exe -m pip install -r rnd_pod/requirements.txt`
3. `rnd_pod/.cma-venv/Scripts/python.exe rnd_pod/validation/check_sdk.py`  (expect `OK`)
4. `runtime/python/python.exe rnd_pod/validation/hello_probe.py`  (expect read-only `OK`)
5. Export `ANTHROPIC_API_KEY`. Create the env + pod:
   `rnd_pod/.cma-venv/Scripts/python.exe -m rnd_pod.kickoff setup`
   (writes `rnd_pod/pod_ids.json` — git-ignored; agent IDs are environment-specific.)
6. In the Console, generate an environment key for `trading-app-rnd`; export
   `ANTHROPIC_ENVIRONMENT_KEY` and `ANTHROPIC_ENVIRONMENT_ID`.

## Each iteration
1. Confirm the live backend is NOT trading/training (no pod runs during a trading/retrain cycle).
2. Start the worker **from a Git Bash shell** (its `bash` tool needs `/bin/bash`), workdir =
   repo root. Until a dedicated `rnd_pod/worker.py` exists, use the `EnvironmentWorker` snippet
   in the plan's Task 1 Step 6:
   ```bash
   export ANTHROPIC_ENVIRONMENT_KEY=sk-ant-oat01-...
   export ANTHROPIC_ENVIRONMENT_ID=env_...
   rnd_pod/.cma-venv/Scripts/python.exe - <<'PY'
   import asyncio, os
   from anthropic import AsyncAnthropic
   from anthropic.lib.environments import EnvironmentWorker
   async def main():
       key = os.environ["ANTHROPIC_ENVIRONMENT_KEY"]
       async with AsyncAnthropic(auth_token=key) as client:
           await EnvironmentWorker(
               client,
               environment_id=os.environ["ANTHROPIC_ENVIRONMENT_ID"],
               environment_key=key,
               workdir="/c/Users/gl450/trading_app",
           ).run()
   asyncio.run(main())
   PY
   ```
3. Kick off one iteration:
   `rnd_pod/.cma-venv/Scripts/python.exe -m rnd_pod.kickoff run [--hypothesis next|H3|H4|...]`
   - `next` (default): the Lead reads the ledger and picks the next OPEN hypothesis.
   - `H3`/`H4`/…: target a specific one (the Lead first confirms it is still open).
4. Watch the printed Console session URL. On a GO the Lead merges to `main` and logs the verdict
   to `docs/model_improvement_ledger.md`; on a NO-GO it logs and stops.

## ⚠️ Hypothesis status (read before the first run)
The plan's original default target, **H12** (port the XGB bear gate to the rule agents to recover
a "-$19.3K bear bleed"), was **FALSIFIED** — that bleed is a close-regime accounting artifact;
bear *entries* net +$34.8K, so a bear entry-gate would destroy edge. **H13** (exit-on-bear-flip)
and **H1** (walk-forward embargo, now fixed) are also CLOSED. The default kickoff is therefore
ledger-driven and explicitly tells the Lead to avoid re-litigating H1/H12/H13. Live candidates:
**H3** (post-hoc calibration map), **H4** (recency-weighted training), **H5** (target transform),
**H6** (select on last-fold WFE). See `docs/model_improvement_ledger.md`.

## Safety gates (all enforced before any merge)
Skeptic GO on an honest falsifier · full suite green · no `polymarket_app` paths in the diff ·
`trading.db` SHA-256 unchanged · Lead verification independent of the Builder · rollback =
`git revert`. Residual risk: auto-merge to `main` on a trading system has no human between
Skeptic-GO and merge; the gate stack is the compensating control (operator-accepted for speed).

## Tests
`runtime/python/python.exe -m unittest discover -s rnd_pod/tests -v`  (config, gates, ledger,
run_probe, agents, session_runner, kickoff — all green, no network/API needed).
