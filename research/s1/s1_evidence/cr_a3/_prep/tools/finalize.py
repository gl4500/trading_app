"""Copy the prep tooling + split inputs into cr_a3/_prep/ (audit trail) and write a3/t15c_prep_hashes.txt (LF).

usage: finalize.py copy | finalize.py hashes"""
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from t15c_common import A3, EVID, WORK, WT, sha  # noqa: E402

TOOLS = ["t15c_common.py", "explore_timing.py", "junit_times.py", "scope_expand.py", "show_ranges.py", "t15c_reach.py",
         "reach_run.py", "split.py", "make_shards.py", "slot_groups.py", "baseline.py", "inventory.py", "summarize.py",
         "render_tables.py", "finalize.py", "selectors.json", "measure_io.py", "pool_check.py", "make_completion.py",
         "summarize2.py", "plan_sessions.py", "reinit.py", "reinit_copied_diff.py", "deletion_fix1.py",
         "deletion_fix2.py"]


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
              "reinit_compare.json", "reinit_compare_fix2.json"):
        shutil.copy2(WORK / n, dst / n)
    print("copied")


def hashes():
    extra = [A3 / n for n in ("t15c_prep.md", "t15c_h_red.txt", "t15c_h_green.txt", "t15c_h_fix1_red.txt",
                              "t15c_h_fix1_green.txt", "t15c_h_fix2_red.txt", "t15c_h_fix2_green.txt")]
    extra += [WT / "research/s1/s1_tests" / n for n in ("cr_coord.py", "cr_reconcile.py", "cr_guard.py", "cr_launch.py",
                                                        "test_s1_a3_cr_guard.py", "test_s1_a3_cr_completion.py")]
    files = sorted(p for p in EVID.rglob("*") if p.is_file()) + extra
    lines = [f"{sha(p)}  {p.relative_to(WT).as_posix()}" for p in files]
    (A3 / "t15c_prep_hashes.txt").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))   # LF (review N3)
    print(len(lines), "hashes")


if __name__ == "__main__":
    {"copy": copy, "hashes": hashes}[sys.argv[1]]()
