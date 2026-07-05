# rnd_pod — Status & Resume Note

_Last updated: 2026-07-05_

## TL;DR

The trading_app R&D pod (Claude Managed Agents crew) is **fully implemented, tested, and pushed** — but **not merged to `main`** and **never run live yet**. Nothing to build; the only open items are operator-gated (merge decision + first live iteration).

## Where it lives

- **Branch:** `docs/rnd-pod-cma-spec` (pushed to `origin`; 10 commits ahead of `main`, unmerged by choice)
- **Code:** `rnd_pod/`
- **Design spec:** `docs/superpowers/specs/2026-06-21-trading-app-rnd-pod-cma-design.md`
- **Implementation plan:** `docs/superpowers/plans/2026-06-21-trading-app-rnd-pod-cma.md`
- **Memory:** `trading_app_rnd_pod_cma` · registered in `CLAUDE.md` ("R&D pod (`rnd_pod/`)")

## What's done (all 8 plan tasks, TDD)

| Task | Module | Commit |
|---|---|---|
| 1 | `validation/check_sdk.py`, `validation/hello_probe.py`, `.cma-venv`, requirements | `7fc31eb` |
| 2 | `config.py` (`PodConfig`, `default_config`) | `485a9db` |
| 3 | `gates.py` (`scope_violations`, `sha256_file`, `db_unchanged`) | `69965a9` |
| 4 | `ledger.py` (`format_verdict`, `append_verdict` newest-on-top) | `2f16a95` |
| 5 | `run_probe.py` (`build_probe_cmd`, `probe_env`, `run_probe`) | `132a43a` |
| 6 | `agents.py` (4-role builders + `create_pod`) | `5a4c32e` |
| 7 | `environment.py`, `session_runner.py` (`is_terminal`, `run_iteration`) | `75dc1dc` |
| 8 | `kickoff.py` (setup/run split), `README.md` | `8e39aae` |
| — | CLAUDE.md registration (memory-sync) | `b1fee68` |

**Tests:** 26/26 green via `./runtime/python/python.exe -m unittest discover -s rnd_pod/tests -v` (includes a bonus `test_kickoff.py` beyond the plan).

## What's still open (operator-gated — cannot be automated)

1. **Merge `docs/rnd-pod-cma-spec` → `main`.** Left unmerged on purpose. Use `superpowers:finishing-a-development-branch` when ready.
2. **First live iteration** (plan Task 1 Step 6 + Task 8 Step 5). Requires:
   - `ANTHROPIC_API_KEY` exported
   - a Console-generated environment key for env `trading-app-rnd` → `ANTHROPIC_ENVIRONMENT_KEY` + `ANTHROPIC_ENVIRONMENT_ID`
   - a worker running **from Git Bash** (needs `/bin/bash`), workdir = repo root
   - the live backend **idle** (never run the pod while it's trading/training)
   - Then: `rnd_pod/.cma-venv/Scripts/python.exe -m rnd_pod.kickoff setup` (once) → `... -m rnd_pod.kickoff run --hypothesis H12`
   - Full runbook: `rnd_pod/README.md`

## Hard constraints (do not violate)

- CMA SDK (`anthropic>=0.111.0`) lives ONLY in git-ignored `rnd_pod/.cma-venv`. **Never** `pip install anthropic` into `site-packages/` or `runtime/` (live app pins `anthropic==0.84.0`).
- Probes run under `runtime/python/python.exe` and open `trading.db` **read-only** (`file:...?mode=ro`).
- Scope: `trading_app` only — zero `polymarket_app` paths.
- First hypothesis is **H12**: port the XGB bear gate to the non-gated rule agents (Momentum/MeanRev/Tech/HistTrends) bleeding ~-$19.3K in bear.
