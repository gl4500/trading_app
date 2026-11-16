"""15c-H fix round 2: delete one guard at a time in a SCRATCH copy (never the repo) and run the focused tests there;
a guard is pinned iff some test fails. Same mechanics as deletion_fix1.py."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(r"C:\Users\gl450\trading_app-s1")
T = REPO / "research/s1/s1_tests"
SCR = Path(__file__).resolve().parent.parent / "deletion_fix2"
PY = r"C:\Users\gl450\.coordination\trading_app\testenv\Scripts\python.exe"
FILES = ["cr_coord.py", "cr_reconcile.py", "cr_guard.py", "cr_launch.py", "conftest.py",
         "test_s1_a3_cr_guard.py", "test_s1_a3_cr_completion.py"]
NL = "\n"
M = {
    "D0_control": ("cr_coord.py", "IO_MARGIN_S = 15.0" + NL, "IO_MARGIN_S = 15.0" + NL),
    "G10_kill_short_circuit_clean": (
        "cr_coord.py",
        '        if attempts and attempts[-1]["label"] == "killed" and cr_reconcile.attempt_clean(attempts[-1]):',
        '        if attempts and attempts[-1]["label"] == "killed":'),
    "G14_batch_cap_identity_required": ("cr_coord.py", "    if not identity:" + NL + "        raise CoordError(",
                                        "    if False:" + NL + "        raise CoordError("),
    "G16b_read_cap_harness_recheck": (
        "cr_coord.py",
        '            or _sha(Path(cfg["cr_toml"])) != cfg.get("cr_toml_sha256")' + NL
        + '            or cfg.get("harness_sha256") != harness_hashes()):',
        '            or _sha(Path(cfg["cr_toml"])) != cfg.get("cr_toml_sha256")):'),
    "G21_single_argfile": ("cr_coord.py", "    if len(files) != 1:", "    if not files:"),
    "N2_completion_area_structure": ("cr_coord.py", '        if up.name == "completion":', '        if False:'),
    "N2_precise_not_any_segment": ("cr_coord.py", "    if _in_completion_area(work_root):",
                                   '    if "completion" in Path(work_root).resolve().parts:'),
    "N3_manifest_identity_test_command": (
        "cr_coord.py",
        '        if not tc or hashlib.sha256(tc.encode("utf-8")).hexdigest() != config.get("test_command_sha256"):',
        '        if False:'),
    "N4_control_equals_argfile": ("cr_coord.py", "        if control != set(nodes):", "        if False:"),
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
