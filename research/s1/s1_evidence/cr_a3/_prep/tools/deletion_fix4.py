"""15c-H fix round 4: delete one guard at a time in a SCRATCH copy (outside the repo) and run the focused tests there;
a guard is pinned iff some test fails. Same mechanics as _prep/tools/deletion_fix1/2/3.py. Covers the new fix-4 guards
(G*) and re-deletes the six fix-3 guards re-review 3 found unpinned (X2, X6, X7, X9, X12, X15) plus the R3-N4 branch."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(r"C:\Users\gl450\trading_app-s1")
T = REPO / "research/s1/s1_tests"
SCR = Path(r"C:\Users\gl450\AppData\Local\Temp\claude\4a6d95c7011f8258\c661c7e7-0401-4122-9c4b-9345620dbebb"
           r"\scratchpad\fix4\deletion")
PY = r"C:\Users\gl450\.coordination\trading_app\testenv\Scripts\python.exe"
FILES = ["cr_coord.py", "cr_reconcile.py", "cr_guard.py", "cr_launch.py", "conftest.py",
         "test_s1_a3_cr_guard.py", "test_s1_a3_cr_completion.py"]
NL = "\n"
M = {
    "D0_control": ("cr_coord.py", "IO_MARGIN_S = 15.0" + NL, "IO_MARGIN_S = 15.0" + NL),
    # --- R3-I1
    "G1_scrub_removed": ("cr_coord.py",
                         "    env = {k: v for k, v in os.environ.items() if not _outcome_var(k) or k.upper() in "
                         "_ENV_PASS}",
                         "    env = dict(os.environ)"),
    "G2_binding_fixed_list": ("cr_coord.py",
                              "    out = {k: v for k, v in env.items() if _outcome_var(k) and k.upper() != "
                              "\"PYTHONPATH\"}",
                              "    out = {k: env.get(k) for k in (\"PYTHONHASHSEED\", \"PYTHONDONTWRITEBYTECODE\")}"),
    "G3_prefix_case_sensitive": ("cr_coord.py", "    return name.upper().startswith(_ENV_PREFIXES)",
                                 "    return name.startswith(_ENV_PREFIXES)"),
    "G4_pass_list_case_sensitive": ("cr_coord.py",
                                    "if not _outcome_var(k) or k.upper() in _ENV_PASS}",
                                    "if not _outcome_var(k) or k in _ENV_PASS}"),
    "G5_pass_list_emptied": ("cr_coord.py",
                             "_ENV_PASS = (\"PYTHONHASHSEED\", \"PYTHONUTF8\", \"PYTHONIOENCODING\")",
                             "_ENV_PASS = ()"),
    "G6_TZ_not_bound": ("cr_coord.py", "    out[\"TZ\"] = env.get(\"TZ\")" + NL, ""),
    # --- R3-N2
    "G7_old_remedy_text": ("cr_coord.py",
                           "    return f\"screen {job} again in a fresh work_root and complete it there\"",
                           "    return \"use a fresh completion root\""),
    # --- R3-N3
    "G8_run_batch_no_inventory_refusal": ("cr_coord.py",
                                          "        if inventory_path is None:" + NL
                                          + "            raise CoordError(f\"identity",
                                          "        if False:" + NL + "            raise CoordError(f\"identity"),
    "G9_run_batch_identity_check": ("cr_coord.py",
                                    "        _check_identity(config, json.loads(Path(inventory_path).read_text("
                                    "encoding=\"utf-8\")))",
                                    "        pass"),
    "G10_run_manifest_identity_check": ("cr_coord.py",
                                        "    if config is not None:" + NL + "        _check_identity(config, inv)"
                                        + NL,
                                        ""),
    # --- R3-N1: fix-3 guards that survived deletion alone in re-review 3
    "X2_screen_want": ("cr_coord.py",
                       "        if ran is None or ran != cur or (want is not None and ran != want):",
                       "        if ran is None or ran != cur:"),
    "X6_no_persisted_raise": ("cr_coord.py",
                              "        if not persisted:" + NL + "            raise CoordError(f\"completion attempt",
                              "        if False:" + NL + "            raise CoordError(f\"completion attempt"),
    "X7_explicit_want_source": ("cr_coord.py",
                                "        if want_source is not None and persisted.get(\"source_sha256\") != "
                                "want_source:",
                                "        if False:"),
    "X9_dump_before_exec": ("cr_coord.py",
                            "            _dump(state_path, st)" + NL + "            result = exec_seam(",
                            "            result = exec_seam("),
    "X12_in_copy_helpers": ("cr_coord.py",
                            "            if _in_copy(r, copy_paths):" + NL + "                helpers[r] = _sha(p)",
                            "            if True:" + NL + "                helpers[r] = _sha(p)"),
    "X15_binding_from_src": ("cr_coord.py", "_attempt_binding(_c, copy_root, _n, _p)",
                             "_attempt_binding(_c, src_root, _n, _p)"),
    # --- R3-N4
    "N4_completion_of_branch": ("cr_coord.py",
                                "            if json.loads(s.read_text(encoding=\"utf-8\")).get(\"completion_of\"):",
                                "            if False:"),
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
    failed = [ln.split("::", 1)[-1] for ln in r.stdout.splitlines() if ln.startswith(("FAILED", "ERROR"))]
    caught = r.returncode != 0 and bool(failed)
    out[mid] = {"rc": r.returncode, "summary": last, "failed": failed, "caught": caught if mid != "D0_control"
                else None}
    print(mid, "caught" if caught else "NOT CAUGHT", last, failed[:4], flush=True)
(SCR / "results.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
