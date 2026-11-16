"""15c-P (fix round 3, deletion_15cp_fix3): delete one new guard at a time in a SCRATCH copy (outside the repo) and run the focused tests there; a
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
           r"\scratchpad\p15\deletion_fix3")
PY = r"C:\Users\gl450\.coordination\trading_app\testenv\Scripts\python.exe"
FILES = ["cr_coord.py", "cr_reconcile.py", "cr_guard.py", "cr_launch.py", "cr_preflight.py", "conftest.py",
         "test_s1_a3_cr_guard.py", "test_s1_a3_cr_completion.py", "test_s1_a3_cr_preflight.py"]
NL = "\n"
PF, CC = "cr_preflight.py", "cr_coord.py"
M = {
    "D0_control": (CC, "IO_MARGIN_S = 15.0" + NL, "IO_MARGIN_S = 15.0" + NL),
    "S1_ref_is_the_accepted_record": (CC, "    if Path(now[\"record\"]).resolve() != path.resolve() or now[\"sha256\"] != "
                                          "ref[\"sha256\"]:", "    if False:"),
    "S2_directory_gate_rerun": (CC, "    now = check_preflight(path.parent, cfg, src_root=src_root, copy_paths=copy_paths)",
                                "    now = {\"record\": str(path), \"sha256\": ref[\"sha256\"]}"),
    "S3_sha_term": (CC, " or now[\"sha256\"] != ref[\"sha256\"]:", ":"),
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
