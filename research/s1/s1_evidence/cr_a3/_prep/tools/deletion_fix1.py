"""15c-H fix round 1 (ruling 5): delete one guard at a time in a SCRATCH copy (never the repo) and run the focused
tests there; a guard is pinned iff some test fails. Pattern models the reviewer's deletion_probe.py."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(r"C:\Users\gl450\trading_app-s1")
T = REPO / "research/s1/s1_tests"
SCR = Path(__file__).resolve().parent.parent / "deletion_fix1"
PY = r"C:\Users\gl450\.coordination\trading_app\testenv\Scripts\python.exe"
FILES = ["cr_coord.py", "cr_reconcile.py", "cr_guard.py", "cr_launch.py", "conftest.py",
         "test_s1_a3_cr_guard.py", "test_s1_a3_cr_completion.py"]
M = {
    "D0_control": ("cr_coord.py", "IO_MARGIN_S = 15.0\n", "IO_MARGIN_S = 15.0\n"),
    "D1_kill_guard_conjunct": ("cr_reconcile.py", '_CLEAN_PAIRS = {("killed", "killed"), ("survived", "survived")}',
                               '_CLEAN_PAIRS = {("killed", "killed"), ("survived", "survived"), '
                               '("killed", "error:junit_error")}'),
    "D2_survived_guard_conjunct": ("cr_reconcile.py",
                                   '_CLEAN_PAIRS = {("killed", "killed"), ("survived", "survived")}',
                                   '_CLEAN_PAIRS = {("killed", "killed"), ("survived", "survived"), '
                                   '("survived", "skip")}'),
    "D1b_guard_pair_check_removed": ("cr_reconcile.py",
                                     '            and (a.get("label"), a.get("guard_status")) in _CLEAN_PAIRS)',
                                     '            and a.get("label") in ("killed", "survived"))'),
    "D3_clean_not_stopped": ("cr_reconcile.py", '    return (not a.get("stopped") and a.get("exec_status") == "ok"',
                             '    return (a.get("exec_status") == "ok"'),
    "D4_clean_exec_ok": ("cr_reconcile.py", '    return (not a.get("stopped") and a.get("exec_status") == "ok"',
                         '    return (not a.get("stopped")'),
    "D5_clean_cleanup_verified": ("cr_reconcile.py", ' and a.get("cleanup_verified") is True\n', '\n'),
    "D6_pool_union_check": ("cr_coord.py", "        check_pool_union(pool, node_sets)\n", "        pass\n"),
    "D7_zero_shards": ("cr_coord.py", '        if not shards:\n            raise PartitionError("no completion shards declared")\n',
                       ''),
    "D8_refused_shard_resume": ("cr_coord.py", '''        if latest is None or (job not in latest.get("labels", {})
                              and _resolution_path(sroot, latest["batch_id"]).exists()):''',
                                '''        if latest is None:'''),
    "D9_cap_bare_dict": ("cr_coord.py", "    if not isinstance(cap_record, (str, Path)):\n        raise CoordError(",
                         "    if False:\n        raise CoordError("),
    "D10_cap_identity_bound": ("cr_coord.py", "    if identity is not None and cfg != identity:", "    if False:"),
    "D11_cap_state_config": ("cr_coord.py", '    if not identity or s.get("config") != identity:', "    if False:"),
    "D12_cap_state_sha": ("cr_coord.py",
                          '    if not cal.get("path") or not Path(cal["path"]).is_file() or _sha(Path(cal["path"])) '
                          '!= cal.get("sha256"):', "    if False:"),
    "D13_retry_parent_clock": ("cr_coord.py", "                     session_root=Path(session_root or work_root),\n"
                               "                     item_outer_s=rcfg",
                               "                     session_root=None,\n                     item_outer_s=rcfg"),
    "D14_retry_outer_in_fence": ("cr_coord.py",
                                 '                     item_outer_s=rcfg.timeout_s + BUDGETS["cleanup_reserve_s"],\n',
                                 ''),
    "D15_retry_refuses_completion_dir": ("cr_coord.py", '    if "completion" in Path(work_root).resolve().parts:',
                                         "    if False:"),
    "D16_merge_required_nonempty": ("cr_reconcile.py", "    if not required:\n        raise ValueError(",
                                    "    if False:\n        raise ValueError("),
    "D17_binding_helpers": ("cr_coord.py", "            helpers[_posix(p.relative_to(src_root))] = _sha(p)\n",
                            "            pass\n"),
    "D18_kill_short_circuit_clean": ("cr_coord.py",
                                     '        if attempts and attempts[-1]["label"] == "killed" and '
                                     'cr_reconcile.attempt_clean(attempts[-1]):',
                                     '        if attempts and attempts[-1]["label"] == "killed":'),
}
only = sys.argv[1:]
out = {}
for mid, (fname, old, new) in M.items():
    if only and mid not in only:
        continue
    d = SCR / mid
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    for f in FILES:
        shutil.copy2(T / f, d / f)
    txt = (d / fname).read_bytes().decode("utf-8")
    if txt.count(old) != 1:
        out[mid] = f"PATTERN COUNT {txt.count(old)}"
        print(mid, out[mid], flush=True)
        continue
    (d / fname).write_bytes(txt.replace(old, new).encode("utf-8"))
    env = dict(os.environ, PYTHONPATH=f"{d};{REPO / 'research/s1'}", S1_HYPOTHESIS_ROOT=str(d / "hyp"),
               PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([PY, "-m", "pytest", "-p", "conftest", "-p", "no:cacheprovider", "-q",
                        f"--basetemp={d / 'bt'}", "test_s1_a3_cr_completion.py", "test_s1_a3_cr_guard.py"],
                       cwd=d, env=env, capture_output=True, text=True, timeout=900)
    last = [ln for ln in r.stdout.splitlines() if ln.strip()][-1:]
    failed = [ln.split("::", 1)[-1] for ln in r.stdout.splitlines() if ln.startswith("FAILED")]
    caught = r.returncode != 0 and bool(failed)
    out[mid] = {"rc": r.returncode, "summary": last, "failed": failed, "caught": caught if mid != "D0_control"
                else None}
    print(mid, "caught" if caught else "NOT CAUGHT", last, failed[:3], flush=True)
(SCR / "results.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
