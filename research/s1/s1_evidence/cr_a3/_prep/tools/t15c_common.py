"""T15c-prep shared constants/helpers (prep tooling; never mutates the worktree source).

Copies mirror the repo layout (copy root == repo root), so cr.toml module-path is "research/s1/<module>.py" exactly as
in the plan text, and every path in a test-command is relative to the copy root."""
import hashlib
import json
import sys
from pathlib import Path

WT = Path(r"C:\Users\gl450\trading_app-s1")
PY = Path(r"C:/Users/gl450/.coordination/trading_app/testenv/Scripts/python.exe")
WORK = Path(r"C:\Users\gl450\AppData\Local\Temp\claude\4a6d95c7011f8258\c661c7e7-0401-4122-9c4b-9345620dbebb"
            r"\scratchpad\t15c_work")
EVID = WT / "research/s1/s1_evidence/cr_a3"
A3 = WT / "research/s1/s1_evidence/a3"
HARNESS = WT / "research/s1/s1_tests"
sys.path.insert(0, str(HARNESS))

import cr_coord  # noqa: E402
import cr_guard  # noqa: E402

T = "research/s1/s1_tests/"
# R1: modules, priority order and plan test files (the starting selectors).
MODULES = {
    "s1_journal": ["test_s1_a3_journal.py", "test_s1_a3_precedence.py"],
    "s1_locks": ["test_s1_a3_locks.py"],
    "s1_trial": ["test_s1_a3_trial.py", "test_s1_a3_gate.py"],
    "s1_stage": ["test_s1_a3_stage.py"],
    "s1_slot": ["test_s1_a3_slots.py", "test_s1_a3_finalizer.py"],
    "s1_seal": ["test_s1_a3_stop.py", "test_s1_a3_score.py"],
    "s1_collect": ["test_s1_a3_audit.py", "test_s1_a3_final.py"],
}
PRIORITY = list(MODULES)
PYTEST_EXTRA = ["-p", "conftest"]          # the project's canonical S1 invocation (-p conftest)
PYTHONPATH_REL = ["research/s1", "research/s1/s1_tests"]


def source_copy_paths() -> list[str]:
    """Every S1 product module + e1 modules + research/s1/docs (s1_common.bundle_manifest hashes the pinned docs;
    test_bundle_pins_addendum3_and_lists_every_new_module reads them) + the whole s1_tests dir (harness included,
    byte-identity checked by the coordinator). s1_evidence is NOT copied (nothing in the selected tests reads it)."""
    s1 = WT / "research/s1"
    mods = sorted(f"research/s1/{p.name}" for p in s1.glob("*.py"))
    return mods + ["research/s1/docs", "research/s1/s1_tests"]


def sha(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def dump(p, obj):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(obj, indent=1, sort_keys=True), encoding="utf-8")


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def cfg_for(module: str, selector_args: list[str], control_rel: str) -> "cr_coord.CRConfig":
    return cr_coord.CRConfig(python=PY, module_rel=f"research/s1/{module}.py",
                             guard_args=["--control", control_rel, *PYTEST_EXTRA, *selector_args],
                             pythonpath_rel=list(PYTHONPATH_REL), target_module=module)
