"""15c-H fix round 3: delete one new guard at a time in a SCRATCH copy (never the repo) and run the focused tests
there; a guard is pinned iff some test fails. Same mechanics as deletion_fix1/2.py."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(r"C:\Users\gl450\trading_app-s1")
T = REPO / "research/s1/s1_tests"
SCR = Path(__file__).resolve().parent.parent / "deletion_fix3"
PY = r"C:\Users\gl450\.coordination\trading_app\testenv\Scripts\python.exe"
FILES = ["cr_coord.py", "cr_reconcile.py", "cr_guard.py", "cr_launch.py", "conftest.py",
         "test_s1_a3_cr_guard.py", "test_s1_a3_cr_completion.py"]
NL = "\n"
M = {
    "D0_control": ("cr_coord.py", "IO_MARGIN_S = 15.0" + NL, "IO_MARGIN_S = 15.0" + NL),
    "F1_cached_drift_raise": ("cr_coord.py",
                              "            drift.append(\"source_sha256(expected)\")" + NL + "        if drift:",
                              "            drift.append(\"source_sha256(expected)\")" + NL + "        if False:"),
    "F2_prepass_call_removed": ("cr_coord.py",
                                "        _check_cached_attempts(job, spec[\"name\"], croot / spec[\"name\"], "
                                "planned[spec[\"name\"]],",
                                "        (lambda *a: None)(job, spec[\"name\"], croot / spec[\"name\"], "
                                "planned[spec[\"name\"]],"),
    "F3_screening_source_check": ("cr_coord.py",
                                  "        if ran is None or ran != cur or (want is not None and ran != want):",
                                  "        if False:"),
    "F4_screening_harness_check": ("cr_coord.py",
                                   "        if s.get(\"harness_sha256\") != harness_hashes():" + NL
                                   + "            raise CoordError(f\"screening of",
                                   "        if False:" + NL + "            raise CoordError(f\"screening of"),
    "F5_env_from_parent_not_child": ("cr_coord.py", "    env = _env(root, cfg)" + NL,
                                     "    env = dict(os.environ)" + NL),
    "F6_merge_recomputes_binding": ("cr_coord.py",
                                    "        bound = (s.get(\"bindings\") or {}).get(job) or {}",
                                    "        bound = _attempt_binding(cfg, src_root, nodes, spec[\"copy_paths\"])"),
    "F7_binding_not_persisted": ("cr_coord.py",
                                 "                st[\"bindings\"][job] = binding_fn(item, copy_root, job_dir)",
                                 "                pass"),
    "F8_executed_vs_planned": ("cr_coord.py",
                               "                if drift:" + NL + "                    raise CoordError(f\"completion "
                               "attempt {name} ({ran['batch_id']}): the executed binding differs \"",
                               "                if False:" + NL + "                    raise CoordError(f\"completion "
                               "attempt {name} ({ran['batch_id']}): the executed binding differs \""),
    "F9_planned_binding_not_recorded": ("cr_coord.py", "                             \"planned_binding\": planned[name]})",
                                        "                             })"),
    "F11_explicit_source_vs_persisted": ("cr_coord.py",
                                         "        if want_source is not None and persisted.get(\"source_sha256\") != "
                                         "want_source:",
                                         "        if False:"),
    "F12_copied_source_not_recorded": ("cr_coord.py",
                                       "        st[\"copied_source_sha256\"][job] = copied[mod_rel]",
                                       "        pass"),
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
