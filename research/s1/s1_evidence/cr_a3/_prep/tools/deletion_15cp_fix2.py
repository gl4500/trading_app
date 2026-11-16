"""15c-P (fix round 2, deletion_15cp_fix2): delete one new guard at a time in a SCRATCH copy (outside the repo) and run the focused tests there; a
guard is pinned iff some test fails. Fast path: the new test file first; if it does not catch the deletion, all three
focused files. Same mechanics as _prep/tools/deletion_fix1..4.py."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(r"C:\Users\gl450\trading_app-s1")
T = REPO / "research/s1/s1_tests"
SCR = Path(r"C:\Users\gl450\AppData\Local\Temp\claude\4a6d95c7011f8258\c661c7e7-0401-4122-9c4b-9345620dbebb"
           r"\scratchpad\p15\deletion_fix2")
PY = r"C:\Users\gl450\.coordination\trading_app\testenv\Scripts\python.exe"
FILES = ["cr_coord.py", "cr_reconcile.py", "cr_guard.py", "cr_launch.py", "cr_preflight.py", "conftest.py",
         "test_s1_a3_cr_guard.py", "test_s1_a3_cr_completion.py", "test_s1_a3_cr_preflight.py"]
NL = "\n"
PF, CC = "cr_preflight.py", "cr_coord.py"
M = {
    "D0_control": (CC, "IO_MARGIN_S = 15.0" + NL, "IO_MARGIN_S = 15.0" + NL),
    "Q1_ref_binding_compared": (CC, "    if b != cur:\n        raise CoordError(f\"pre-flight {path.name} is not bound",
                                "    if False:\n        raise CoordError(f\"pre-flight {path.name} is not bound"),
    "Q2_copy_paths_recorded": (PF, "            info.setdefault(\"changed_paths\", {})[\"copy\"] = _map_diff(copied, copy_after)",
                               "            pass  #"),
    "Q3_source_tree_paths_recorded": (PF, "            info.setdefault(\"changed_paths\", {})[\"source_tree\"] = "
                                          "_map_diff(src_before, src_after)", "            pass"),
    "Q4_cap": (PF, "    return {\"added\": added[:cap], ", "    return {\"added\": added, "),
    "Q5_truncated_flag": (PF, "            \"truncated\": any(len(x) > cap for x in (added, removed, modified))}",
                          "            \"truncated\": False}"),
    "Q6_modified": (PF, "    modified = sorted(k for k in set(before) & set(after) if before[k] != after[k])",
                    "    modified = []"),
    "Q7_removed": (PF, "    removed = sorted(set(before) - set(after))", "    removed = []"),
    "Q8_record_field": (PF, "               \"changed_paths\": info.get(\"changed_paths\"),\n", ""),
    "N18_next_attempt_markers": (PF, " or (record_dir / f\"started_{k:03d}.json\").exists()", ""),
}


def run(d, files):
    env = dict(os.environ, PYTHONPATH=f"{d};{REPO / 'research/s1'}", S1_HYPOTHESIS_ROOT=str(d / "hyp"),
               PYTHONDONTWRITEBYTECODE="1")
    shutil.rmtree(d / "bt", ignore_errors=True)
    r = subprocess.run([PY, "-B", "-m", "pytest", "-p", "conftest", "-p", "no:cacheprovider", "-q",
                        f"--basetemp={d / 'bt'}", *files], cwd=d, env=env, capture_output=True, text=True,
                       timeout=900)
    last = [ln for ln in r.stdout.splitlines() if ln.strip()][-1:]
    failed = [ln.split("::", 1)[-1] for ln in r.stdout.splitlines() if ln.startswith(("FAILED", "ERROR"))]
    return r.returncode, last, failed


only = sys.argv[1:]
if only == ["--dry"]:
    for mid, (fname, old, new) in M.items():
        n = (T / fname).read_text(encoding="utf-8").count(old)
        if n != 1:
            print("PATTERN COUNT", n, mid)
    print("dry done", len(M))
    sys.exit(0)
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
    files = ["test_s1_a3_cr_preflight.py"]
    rc, last, failed = run(d, files)
    if mid != "D0_control" and not (rc != 0 and failed):
        files = ["test_s1_a3_cr_preflight.py", "test_s1_a3_cr_completion.py", "test_s1_a3_cr_guard.py"]
        rc, last, failed = run(d, files)
    if mid == "D0_control":
        rc2, last2, failed2 = run(d, ["test_s1_a3_cr_preflight.py", "test_s1_a3_cr_completion.py",
                                      "test_s1_a3_cr_guard.py"])
        last, failed, rc = last + last2, failed + failed2, rc or rc2
    caught = rc != 0 and bool(failed)
    out[mid] = {"rc": rc, "files": files, "summary": last, "failed": failed,
                "caught": caught if mid != "D0_control" else None}
    print(mid, "caught" if caught else "NOT CAUGHT", last, failed[:3], flush=True)
(SCR / "results.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
