"""On-demand kickoff for one R&D iteration.

Setup (once):   python -m rnd_pod.kickoff setup
Run (per iter): python -m rnd_pod.kickoff run [--hypothesis next|H3|H4|...]

Run with the CMA venv: rnd_pod/.cma-venv/Scripts/python.exe
Requires ANTHROPIC_API_KEY in the environment, and a worker running on this PC
(see README). agents.create() runs only in `setup`, never in `run`.

NOTE: the plan's original default hypothesis was H12, but H12 was FALSIFIED in
docs/model_improvement_ledger.md (the "-$19.3K bear bleed" is a close-regime
accounting artifact; bear ENTRIES net +$34.8K). H1, H12, and H13 are all closed.
The default kickoff is therefore ledger-driven: the Lead reads the ledger and
picks the next OPEN hypothesis (e.g. H3 calibration map, H4 recency-weighted
training, H5 target transform, H6 last-fold feature selection). Pass an explicit
--hypothesis to target a specific one.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from rnd_pod.config import default_config
from rnd_pod.agents import create_pod
from rnd_pod.environment import ensure_environment
from rnd_pod.session_runner import run_iteration

# `anthropic` (the CMA SDK) lives only in rnd_pod/.cma-venv, not in the app
# runtime that runs the unit tests. Import it lazily inside the API commands so
# the pure helpers (and the test suite) import cleanly under either interpreter.

REPO = Path(__file__).resolve().parents[1]
IDS_FILE = REPO / "rnd_pod" / "pod_ids.json"
ENV_NAME = "trading-app-rnd"

DEFAULT_KICKOFF = (
    "Run one R&D iteration. Read docs/model_improvement_ledger.md (newest on top) and pick the "
    "next OPEN hypothesis to pursue — note that H1, H12, and H13 are already CLOSED (H1 fixed; "
    "H12 entry-gate and H13 exit-on-flip both falsified — do NOT re-litigate them). Strong "
    "candidates are H3 (post-hoc calibration map), H4 (recency-weighted training), H5 (target "
    "transform), and H6 (select on last-fold WFE). Have the Quant Researcher restate it as a "
    "single falsifiable claim and run the cheapest probe on trading.db (read-only) plus the "
    "per-symbol parquets; have the Red-Team Skeptic rule GO/NO-GO; referee on realized PnL by "
    "regime; on GO, build with TDD, verify the safety gates, merge, and log the verdict; on "
    "NO-GO, log the verdict and stop."
)


def _kickoff_text(hypothesis: str) -> str:
    if hypothesis in ("next", "auto", ""):
        return DEFAULT_KICKOFF
    return (
        f"Run one R&D iteration pursuing {hypothesis}. First read "
        f"docs/model_improvement_ledger.md to confirm {hypothesis} is still OPEN (H1/H12/H13 are "
        f"CLOSED — if it names one of those, stop and report). Then have the Quant Researcher "
        f"frame the falsifiable claim and run the cheapest probe on trading.db (read-only); have "
        f"the Red-Team Skeptic rule GO/NO-GO; referee on realized PnL by regime; on GO build with "
        f"TDD, verify the gates, merge, and log the verdict; on NO-GO log the verdict and stop."
    )


def cmd_setup() -> None:
    import anthropic
    cfg = default_config(REPO)
    client = anthropic.Anthropic()
    ids = create_pod(client, cfg)
    IDS_FILE.write_text(json.dumps(ids, indent=2), encoding="utf-8")
    print(f"created pod, wrote {IDS_FILE}: {ids}")


def cmd_run(hypothesis: str) -> None:
    import anthropic
    cfg = default_config(REPO)
    if not IDS_FILE.exists():
        raise SystemExit("pod_ids.json missing — run `setup` first")
    ids = json.loads(IDS_FILE.read_text(encoding="utf-8"))
    client = anthropic.Anthropic()
    env_id = ensure_environment(client, ENV_NAME)
    run_iteration(client, cfg, lead_id=ids["lead"], env_id=env_id,
                  kickoff_text=_kickoff_text(hypothesis))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    run_p = sub.add_parser("run")
    run_p.add_argument("--hypothesis", default="next")
    args = parser.parse_args()
    if args.cmd == "setup":
        cmd_setup()
    else:
        cmd_run(args.hypothesis)


if __name__ == "__main__":
    main()
