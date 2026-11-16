"""15c-P: delete one new guard at a time in a SCRATCH copy (outside the repo) and run the focused tests there; a
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
           r"\scratchpad\p15\deletion")
PY = r"C:\Users\gl450\.coordination\trading_app\testenv\Scripts\python.exe"
FILES = ["cr_coord.py", "cr_reconcile.py", "cr_guard.py", "cr_launch.py", "cr_preflight.py", "conftest.py",
         "test_s1_a3_cr_guard.py", "test_s1_a3_cr_completion.py", "test_s1_a3_cr_preflight.py"]
NL = "\n"
PF, CC = "cr_preflight.py", "cr_coord.py"
M = {
    "D0_control": (CC, "IO_MARGIN_S = 15.0" + NL, "IO_MARGIN_S = 15.0" + NL),
    # ---- driver: refusals before running
    "P01_frozen_control": (PF, "    if cr_coord._sha(src_root / ctl) != expected_control_sha256:", "    if False:"),
    "P02_source_pin": (PF, "    if cr_coord._sha(src_root / mod) != source_sha256:", "    if False:"),
    "P03_cr_toml_identity": (PF, "    ident = cr_coord.config_identity(cfg, cr_toml, config_id=config_id or "
                                 "_posix_rel(cr_toml, src_root))",
                             "    ident = {\"config_id\": config_id, \"cr_toml_sha256\": None}"),
    "P04_copy_vs_pins": (PF, "    if copied.get(mod) != source_sha256 or copied.get(ctl) != expected_control_sha256:",
                         "    if False:"),
    "P05_copy_harness_drift": (PF, "    if drift:" + NL + "        raise CoordError(f\"harness files",
                               "    if False:" + NL + "        raise CoordError(f\"harness files"),
    # ---- driver: execution context
    "P06_env_not_production": (PF, "    env = cr_coord._env(copy, cfg, job_dir, job_id)",
                               "    env = dict(cr_coord.os.environ)"),
    "P07_command_not_exact": (PF, "    cmd = shlex.split(cr_coord.test_command(cfg))",
                              "    cmd = shlex.split(cr_coord.test_command(cfg)) + [\"-x\"]"),
    "P08_deadline_not_cr_timeout": (PF, "job_dir=job_dir, deadline_s=cfg.timeout_s)",
                                    "job_dir=job_dir, deadline_s=cfg.guard_deadline_s)"),
    # ---- driver: write-once
    "P09_write_once_mode": (PF, "\"x\", encoding=\"utf-8\") as fh:", "\"w\", encoding=\"utf-8\") as fh:"),
    "P10_next_attempt_skips_records": (PF, "    while (record_dir / f\"preflight_{k:03d}.json\").exists() or "
                                           "(work_root / f\"attempt_{k:03d}\").exists():",
                                       "    while (work_root / f\"attempt_{k:03d}\").exists():"),
    # ---- driver: verdict
    "P11_status": (PF, "        if guard.get(\"status\") != \"survived\":", "        if False:"),
    "P12_nodes_vs_control": (PF, "        if set(guard.get(\"nodes\") or []) != set(control_nodes) or "
                                 "len(guard.get(\"nodes\") or []) != len(control_nodes):", "        if False:"),
    "P13_node_set_mismatch": (PF, "        if guard.get(\"node_set\"):", "        if False:"),
    "P14_guard_control_sha": (PF, "        if guard.get(\"control_sha256\") != expected_control:", "        if False:"),
    "P15_counts": (PF, "        if c.get(\"failures\") or c.get(\"errors\") or c.get(\"skipped\") or "
                       "not c.get(\"tests\"):", "        if False:"),
    "P16_guard_cleanup": (PF, "        if not (guard.get(\"cleanup\") or {}).get(\"verified\"):", "        if False:"),
    "P17_guard_exit": (PF, "        if guard.get(\"exit_code\") != 0:", "        if False:"),
    "P18_outer_rc": (PF, "    if run.get(\"rc\") != 0 and \"nonzero_exit\" not in reasons:", "    if False:"),
    "P19_outer_timeout": (PF, "    if run.get(\"timed_out\"):", "    if False:"),
    "P20_outer_cleanup": (PF, "    if not (run.get(\"cleanup\") or {}).get(\"verified\") and \"cleanup_unverified\" "
                              "not in reasons:", "    if False:"),
    "P21_source_after": (PF, "    if not after[\"source_unchanged\"]:", "    if False:"),
    "P22_control_after": (PF, "    if not after[\"control_unchanged\"]:", "    if False:"),
    "P23_budget": (PF, "    if wall_s > budget_s:", "    if False:"),
    "P24_budget_boundary": (PF, "    if wall_s > budget_s:", "    if wall_s >= budget_s:"),
    "P25_no_guard_sidecar": (PF, "        reasons.append(\"no_guard_sidecar\")", "        pass"),
    "P26_runner_exception": (PF, "        exc = f\"runner_exception:{type(e).__name__}\"", "        exc = None"),
    # ---- CLI
    "P27_skip_already_clean": (PF, "        if status == \"clean\":", "        if False:"),
    "P28_block_not_clean": (PF, "        if status == \"not_clean\":", "        if False:"),
    "P29_stop_on_not_clean": (PF, "        if rec[\"verdict\"] != \"clean\":" + NL + "            break",
                              "        if False:" + NL + "            break"),
    "P30_frozen_from_collect_only": (PF, "        expected = json.loads((conf[\"dir\"] / \"collect_only.json\")."
                                         "read_text(encoding=\"utf-8\"))[\"control_sha256\"]",
                                     "        expected = cr_coord._sha(root / cr_coord.control_rel(cfg))"),
    "P31_source_pins_agree": (PF, "    if len(pins) != 1:", "    if not pins:"),
    "P32_main_exit_code": (PF, "    return 0 if res and all(r[\"verdict\"] in (\"clean\", \"already_clean\") for r in "
                               "res) else 1", "    return 0"),
    "P33_screening_first": (PF, "for d in screen + comp]", "for d in comp + screen]"),
    # ---- gate
    "G01_source_pin": (CC, "    if source_sha256 is not None and cur[\"source_sha256\"] != source_sha256:",
                       "    if False:"),
    "G02_no_records": (CC, "    if not paths:" + NL + "        raise CoordError(f\"no pre-flight record",
                       "    if False:" + NL + "        raise CoordError(f\"no pre-flight record"),
    "G03_not_clean_raise": (CC, "    if status == \"not_clean\":", "    if False:"),
    "G04_not_same_raise": (CC, "    if status != \"clean\":" + NL + "        p, r = paths[-1]",
                           "    if False:" + NL + "        p, r = paths[-1]"),
    "G05_binding_equality": (CC, "if r.get(\"schema\") == PREFLIGHT_SCHEMA and r.get(\"binding\") == cur:",
                             "if r.get(\"schema\") == PREFLIGHT_SCHEMA:"),
    "G06_not_clean_detection": (CC, "            if r.get(\"verdict\") != \"clean\" or r.get(\"reasons\"):" + NL
                                + "                return \"not_clean\", p, r",
                                "            if False:" + NL + "                return \"not_clean\", p, r"),
    "B01_env": (CC, "\"pythonpath_rel\": list(cfg.pythonpath_rel), \"env\": _child_env_binding(root, cfg)}",
                "\"pythonpath_rel\": list(cfg.pythonpath_rel)}"),
    "B02_control": (CC, "\"control_rel\": ctl, \"control_sha256\": _sha(root / ctl), ", "\"control_rel\": ctl, "),
    "B03_argfiles": (CC, "\"argfiles_sha256\": argfiles,", ""),
    "B04_source": (CC, "\"source_sha256\": _sha(root / cfg.module_rel), \"harness_sha256\": harness_hashes(),",
                   "\"harness_sha256\": harness_hashes(),"),
    "B05_harness": (CC, "\"source_sha256\": _sha(root / cfg.module_rel), \"harness_sha256\": harness_hashes(),",
                    "\"source_sha256\": _sha(root / cfg.module_rel),"),
    "B06_helpers": (CC, "\"helpers_sha256\": _helpers(cfg, root, copy_paths), \"copy_paths\"", "\"copy_paths\""),
    "B07_copy_paths": (CC, ", \"copy_paths\": sorted(map(_posix, copy_paths)),", ","),
    "B08_command": (CC, "\"test_command_sha256\": hashlib.sha256(test_command(cfg).encode(\"utf-8\")).hexdigest(),"
                        + NL + "            \"control_rel\": ctl", "\"control_rel\": ctl"),
    # ---- gating call sites
    "R01_calibration_gated": (CC, "    if config is not None or preflight_dir is not None:     # 15c-P",
                              "    if preflight_dir is not None:     # 15c-P"),
    "R02_calibration_needs_both": (CC, "        if cfg is None or preflight_dir is None:" + NL
                                   + "            raise CoordError(\"a calibration",
                                   "        if False:" + NL + "            raise CoordError(\"a calibration"),
    "R03_identity_vs_cfg": (CC, "        if config is not None and config.get(\"test_command_sha256\") != "
                                "hashlib.sha256(",
                            "        if False and config.get(\"test_command_sha256\") != hashlib.sha256("),
    "R04_run_batch_check_call": (CC, "        preflight = check_preflight(preflight_dir, cfg, src_root=src_root, "
                                     "copy_paths=copy_paths,",
                                 "        preflight = (lambda *a, **k: None)(preflight_dir, cfg, src_root=src_root, "
                                 "copy_paths=copy_paths,"),
    "M01_manifest_requires": (CC, "    if cfg is None or preflight_dir is None:" + NL
                              + "        raise CoordError(\"run_manifest needs",
                              "    if False:" + NL + "        raise CoordError(\"run_manifest needs"),
    "M02_manifest_cfg_vs_inventory": (CC, "    if inv.get(\"test_command\") != test_command(cfg):", "    if False:"),
    "M03_manifest_passes_through": (CC, "inventory_path=inventory_path, cfg=cfg, preflight_dir=preflight_dir,",
                                    "inventory_path=inventory_path,"),
    "C01_shard_needs_preflight": (CC, "        if not s.get(\"preflight_dir\"):", "        if False:"),
    "C02_shard_check_call": (CC, "    preflights = {spec[\"name\"]: check_preflight(",
                             "    preflights = {spec[\"name\"]: (lambda *a, **k: {\"sha256\": None})("),
    "C03_attempt_persists": (CC, "\"planned_binding\": planned[name], \"preflight\": preflights[name]})",
                             "\"planned_binding\": planned[name]})"),
    "C04_record_lists": (CC, "\"pending_shards\": pending, \"preflights\": preflights, ",
                         "\"pending_shards\": pending, "),
    "H01_driver_in_harness": (CC, ", \"cr_launch.py\", \"cr_preflight.py\")", ", \"cr_launch.py\")"),
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
