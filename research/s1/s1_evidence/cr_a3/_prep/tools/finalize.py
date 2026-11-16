"""Copy the prep tooling + split inputs into cr_a3/_prep/ (audit trail) and write a3/t15c_prep_hashes.txt (LF).

usage: finalize.py copy | finalize.py hashes   (run with the interpreter's -B: no __pycache__ in the tree)

15c-P (Codex N1 on 9330a64): generated caches (__pycache__/, *.pyc) are never copied or listed, and `hashes`
refuses unless every listed file is git-tracked or in the current `git status --porcelain` modified/untracked
set - an ignored file would make the list unreproducible from a commit."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from t15c_common import A3, EVID, WORK, WT, cr_coord, sha  # noqa: E402

TOOLS = ["t15c_common.py", "explore_timing.py", "junit_times.py", "scope_expand.py", "show_ranges.py", "t15c_reach.py",
         "reach_run.py", "split.py", "make_shards.py", "slot_groups.py", "baseline.py", "inventory.py", "summarize.py",
         "render_tables.py", "finalize.py", "selectors.json", "measure_io.py", "pool_check.py", "make_completion.py",
         "summarize2.py", "plan_sessions.py", "reinit.py", "reinit_copied_diff.py", "deletion_fix1.py",
         "deletion_fix2.py", "deletion_fix3.py", "deletion_fix4.py", "deletion_15cp.py",
         "deletion_15cp_fix1.py", "deletion_15cp_fix2.py",
         "deletion_15cp_fix3.py"]


def copy():
    dst = EVID / "_prep"
    (dst / "tools").mkdir(parents=True, exist_ok=True)
    for t in TOOLS:
        shutil.copy2(HERE / t, dst / "tools" / t)
    for g in (WORK / "groups").glob("*.json"):
        (dst / "groups").mkdir(exist_ok=True)
        shutil.copy2(g, dst / "groups" / g.name)
    for m in ("s1_journal", "s1_locks", "s1_trial", "s1_stage", "s1_slot", "s1_seal", "s1_collect"):
        d = dst / "explore" / m
        d.mkdir(parents=True, exist_ok=True)
        for n in ("junit.xml", "run.json"):
            shutil.copy2(WORK / "explore" / m / n, d / n)
    (dst / "reach_plan").mkdir(exist_ok=True)
    for n in ("seal_plan.json", "collect_plan.json", "collect_plan_v2.json", "slot_plan.json"):
        shutil.copy2(WORK / "reach" / n, dst / "reach_plan" / n)
    for n in ("budget.json", "budget_v2.json", "measure_io.json", "pool_check_pre.json", "pool_check_post.json",
              "reinit_compare.json", "reinit_compare_fix2.json", "reinit_compare_fix3.json",
              "reinit_compare_fix4.json", "reinit_compare_15cp.json",
              "reinit_compare_15cp_fix1.json", "reinit_compare_15cp_fix2.json",
              "reinit_compare_15cp_fix3.json"):
        shutil.copy2(WORK / n, dst / n)
    print("copied")


PLAN_KEYS = ("calibration_batch", "pending_after_calibration", "derived_cap", "derived_cap_rule", "scenario")


def check_plans():
    """15c-H fix round 5 (R4-I1): a re-init (inventory.py) writes a PLAIN batch plan; plan_sessions.py must run after
    it. Refuse to write the manifest unless all 12 screening plans are calibration-first, bound to their current
    inventory.json, and calibration + pending == the kept ids in cr_coord.order_items order."""
    plans = sorted(p for p in EVID.rglob("batch_plan.json") if "_superseded" not in p.parts and "_prep" not in p.parts)
    bad = []
    for p in plans:
        plan = json.loads(p.read_text(encoding="utf-8"))
        kept = [i["job_id"] for i in cr_coord.order_items(
            json.loads((p.parent / "inventory_filtered.json").read_text(encoding="utf-8"))["kept"])]
        if (any(k not in plan for k in PLAN_KEYS) or plan["inventory_sha256"] != sha(p.parent / "inventory.json")
                or plan["calibration_batch"] + plan["pending_after_calibration"] != kept
                or plan["calibration_batch"] != kept[:24]):
            bad.append(p.relative_to(WT).as_posix())
    if len(plans) != 12 or bad:
        raise SystemExit(f"batch plans not calibration-first / not bound ({len(plans)} found): {bad} - run "
                         f"plan_sessions.py after any re-init")
    print(len(plans), "calibration-first plans OK")


def hashes():
    check_plans()
    extra = [A3 / n for n in ("t15c_prep.md", "t15c_h_red.txt", "t15c_h_green.txt", "t15c_h_fix1_red.txt",
                              "t15c_h_fix1_green.txt", "t15c_h_fix2_red.txt", "t15c_h_fix2_green.txt",
                              "t15c_h_fix3_red.txt", "t15c_h_fix3_green.txt", "t15c_h_fix4_red.txt",
                              "t15c_h_fix4_green.txt", "t15c_h_fix5_check.txt", "t15c_p_red.txt",
                              "t15c_p_green.txt", "t15c_p_reinit_check.txt", "t15c_p_fix1_red.txt",
                              "t15c_p_fix1_green.txt", "t15c_p_fix1_reinit_check.txt", "t15c_p_fix2_red.txt",
                              "t15c_p_fix2_green.txt", "t15c_p_fix2_reinit_check.txt",
                              "t15c_prep_hashes_pre_15cp_fix2.txt", "t15c_p_fix3_red.txt", "t15c_p_fix3_green.txt",
                              "t15c_p_fix3_reinit_check.txt", "t15c_prep_hashes_at_52f2490.txt",
                              "t15c_prep_hashes_at_9330a64.txt")]
    extra += [WT / "research/s1/s1_tests" / n for n in ("cr_coord.py", "cr_reconcile.py", "cr_guard.py", "cr_launch.py",
                                                        "cr_preflight.py", "test_s1_a3_cr_guard.py",
                                                        "test_s1_a3_cr_completion.py",
                                                        "test_s1_a3_cr_preflight.py")]
    files = sorted(p for p in EVID.rglob("*") if p.is_file() and not _generated(p)) + extra
    archive_check(files)
    lines = [f"{sha(p)}  {p.relative_to(WT).as_posix()}" for p in files]
    (A3 / "t15c_prep_hashes.txt").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))   # LF (review N3)
    print(len(lines), "hashes")


def _generated(p: Path) -> bool:
    return "__pycache__" in p.parts or p.suffix == ".pyc"


def archive_check(files) -> None:
    """Every listed file must be git-tracked or in the porcelain modified/untracked set (never ignored)."""
    def git(*a):
        return subprocess.run(["git", *a], cwd=WT, capture_output=True, check=True).stdout.decode("utf-8")
    known = set(filter(None, git("ls-files", "-z").split("\0")))
    for e in filter(None, git("status", "--porcelain=v1", "-z", "--untracked-files=all").split("\0")):
        known.add(e[3:] if len(e) > 3 and e[2] == " " else e)
    bad = [p.relative_to(WT).as_posix() for p in files if p.relative_to(WT).as_posix() not in known
           or _generated(p)]
    if bad:
        raise SystemExit(f"{len(bad)} manifest entries are neither tracked nor modified/untracked "
                         f"(ignored or generated): {bad[:5]}")
    print(len(files), "entries archive-checked against git")


if __name__ == "__main__":
    {"copy": copy, "hashes": hashes}[sys.argv[1]]()
