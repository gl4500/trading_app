"""15c-P (fix round 1 rerun, deletion_15cp_fix1): delete one new guard at a time in a SCRATCH copy (outside the repo) and run the focused tests there; a
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
           r"\scratchpad\p15\deletion_fix1")
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
    "P06_env_not_production": (PF, '    env = cr_coord._env(copy, cfg, job_dir, f"preflight-{k:03d}")',
        '    env = dict(cr_coord.os.environ)'),
    "P07_command_not_exact": (PF, "    cmd = shlex.split(cr_coord.test_command(cfg))",
                              "    cmd = shlex.split(cr_coord.test_command(cfg)) + [\"-x\"]"),
    "P08_deadline_not_cr_timeout": (PF, "job_dir=job_dir, deadline_s=cfg.timeout_s)",
                                    "job_dir=job_dir, deadline_s=cfg.guard_deadline_s)"),
    # ---- driver: write-once
    "P09_write_once_mode": (PF, "\"x\", encoding=\"utf-8\") as fh:", "\"w\", encoding=\"utf-8\") as fh:"),
    "P10_next_attempt_skips_records": (PF, '    while ((record_dir / f"preflight_{k:03d}.json").exists() or (record_dir / f"started_{k:03d}.json").exists()',
        '    while ((record_dir / f"started_{k:03d}.json").exists()'),
    "P11_status": (PF, '        if guard["status"] != "survived":',
        '        if False:'),
    "P12_nodes_vs_control": (PF, '        if set(guard["nodes"]) != set(control_nodes) or len(guard["nodes"]) != len(control_nodes):',
        '        if False:'),
    "P13_node_set_mismatch": (PF, "        if guard.get(\"node_set\"):", "        if False:"),
    "P14_guard_control_sha": (PF, "        if guard.get(\"control_sha256\") != expected_control:", "        if False:"),
    "P15_counts": (PF, '        if (c["failures"] or c["errors"] or c["skipped"] or not c["tests"]',
        '        if (False'),
    "P16_guard_cleanup": (PF, '        if not guard["cleanup"]["verified"]:',
        '        if False:'),
    "P17_guard_exit": (PF, '        if guard["exit_code"] != 0:',
        '        if False:'),
    "P18_outer_rc": (PF, '        if run["rc"] != 0 and "nonzero_exit" not in reasons:',
        '        if False:'),
    "P19_outer_timeout": (PF, '        if run["timed_out"]:',
        '        if False:'),
    "P20_outer_cleanup": (PF, '        if not run["cleanup"]["verified"] and "cleanup_unverified" not in reasons:',
        '        if False:'),
    "P21_source_after": (PF, '        if not info["source_unchanged"]:',
        '        if False:'),
    "P22_control_after": (PF, '        if not info["control_unchanged"]:',
        '        if False:'),
    "P23_budget": (PF, '        if info["wall_s"] > budget_s:',
        '        if False:'),
    "P24_budget_boundary": (PF, '        if info["wall_s"] > budget_s:',
        '        if info["wall_s"] >= budget_s:'),
    "P25_no_guard_sidecar": (PF, "        reasons.append(\"no_guard_sidecar\")", "        pass"),
    "P26_runner_exception": (PF, '            reasons.append(f"runner_exception:{type(e).__name__}")',
        '            pass'),
    "P27_skip_already_clean": (PF, "        if status == \"clean\":", "        if False:"),
    "P28_block_not_clean": (PF, "        if status == \"not_clean\":", "        if False:"),
    "P29_stop_on_not_clean": (PF, "        if rec[\"verdict\"] != \"clean\":" + NL + "            break",
                              "        if False:" + NL + "            break"),
    "P30_frozen_from_collect_only": (PF, '    expected = json.loads((d / "collect_only.json").read_text(encoding="utf-8"))["control_sha256"]',
        '    expected = cr_coord._sha(root / ctl)'),
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
    "R01_calibration_gated": (CC, '    if (not synthetic or config is not None or preflight_dir is not None',
        '    if (not synthetic or preflight_dir is not None'),
    "R02_calibration_needs_both": (CC, '        if cfg is None or (preflight_dir is None and preflight_ref is None):',
        '        if False:'),
    "R03_identity_vs_cfg": (CC, '        if config is not None and config.get("test_command_sha256") != _cmd_sha(cfg):',
        '        if False:'),
    "R04_run_batch_check_call": (CC, '        preflight = (check_preflight(preflight_dir, cfg, src_root=src_root, copy_paths=copy_paths,',
        '        preflight = ((lambda *a, **k: None)(preflight_dir, cfg, src_root=src_root, copy_paths=copy_paths,'),
    "M01_manifest_requires": (CC, "    if cfg is None or preflight_dir is None:" + NL
                              + "        raise CoordError(\"run_manifest needs",
                              "    if False:" + NL + "        raise CoordError(\"run_manifest needs"),
    "M02_manifest_cfg_vs_inventory": (CC, "    if inv.get(\"test_command\") != test_command(cfg):", "    if False:"),
    "M03_manifest_passes_through": (CC, "inventory_path=inventory_path, cfg=cfg, preflight_dir=preflight_dir,",
                                    "inventory_path=inventory_path,"),
    "C01_shard_needs_preflight": (CC, "        if not s.get(\"preflight_dir\"):", "        if False:"),
    "C02_shard_check_call": (CC, "    preflights = {spec[\"name\"]: check_preflight(",
                             "    preflights = {spec[\"name\"]: (lambda *a, **k: {\"sha256\": None})("),
    "C04_record_lists": (CC, "\"pending_shards\": pending, \"preflights\": preflights, ",
                         "\"pending_shards\": pending, "),
    "H01_driver_in_harness": (CC, ", \"cr_launch.py\", \"cr_preflight.py\")", ", \"cr_launch.py\")"),
    # ================================================================= 15c-P fix round 1 (new guards + reviewer M4)
    "M4_source_control_after_run": (PF, "\n                                     and cr_coord._sha(src_root / ctl) == expected_control_sha256)",
                                    ")"),
    "N01_sidecar_parse_guarded": (PF, "    except (OSError, ValueError, UnicodeDecodeError):\n"
                                      "        return None, [\"guard_sidecar_unreadable\"]",
                                  "    except ZeroDivisionError:\n        return None, [\"guard_sidecar_unreadable\"]"),
    "N02_sidecar_not_object": (PF, "    if not isinstance(g, dict):\n        return None, [\"guard_sidecar_unreadable\"]",
                               "    if False:\n        return None, [\"guard_sidecar_unreadable\"]"),
    "N03_sidecar_field_types": (PF, "    bad = [f for f in _GUARD_REQUIRED if f not in g] + [f for f, ok in "
                                    "_GUARD_TYPES.items() if f in g and not ok(g[f])]", "    bad = []"),
    "N04_runner_result_types": (PF, "    if (isinstance(run, dict) and _is_int(run.get(\"rc\"))",
                                "    if (True or isinstance(run, dict) and _is_int(run.get(\"rc\"))"),
    "N05_started_marker": (PF, "    _write_record(record_dir / f\"started_{k:03d}.json\",",
                           "    (lambda *a: None)(record_dir / f\"started_{k:03d}.json\","),
    "N06_record_in_finally": (PF, "    finally:\n        if not completed:",
                              "    if True:\n        if not completed:"),
    "N07_driver_exception_recorded": (PF, "    except Exception as e:                    # noqa: BLE001 - recorded, never an "
                                          "unrecorded attempt (fix 1, I1)",
                                      "    except ZeroDivisionError as e:"),
    "N08_hard_abort_reraised": (PF, "    if hard is not None:\n        raise hard", "    if False:\n        raise hard"),
    "N09_copy_pins_recorded": (PF, "            reasons.append(\"copy_differs_from_pins\")", "            pass"),
    "N10_copy_harness_recorded": (PF, "        reasons += [f\"copy_harness_drift:{n}\" for n in drift]", "        pass"),
    "N11_copy_vs_source_binding": (PF, "        if not info[\"copy_binding_matches\"] and \"copy_differs_from_pins\" not in "
                                       "reasons:", "        if False:"),
    "N12_copy_changed": (PF, "        if cr_coord.copied_map(copy, copy_paths) != copied:", "        if False:"),
    "N13_source_tree_changed": (PF, "        if cr_coord.copied_map(src_root, copy_paths) != src_before:",
                                "        if False:"),
    "N14_guard_rc": (PF, "        if guard.get(\"rc\") not in (0, None):", "        if False:"),
    "N15_passed_count": (PF, "\n                or c[\"passed\"] != c[\"tests\"] - c[\"failures\"] - c[\"errors\"] - c[\"skipped\"]):",
                         "):"),
    "N16_cli_orphan_attempt_dirs": (PF, "        if status == \"orphan\" or orphans:", "        if status == \"orphan\":"),
    "N17_gate_orphan_status": (CC, "        if mb == cur and not (d / f\"preflight_{k}.json\").exists():",
                               "        if False:"),
    "N18_next_attempt_markers": (PF, " or (record_dir / f\"started_{k:03d}.json\").exists()", ""),
    "N19_frozen_cross_check": (PF, "    if not any(k.startswith(\"baseline/\") for k in others) or bad:", "    if False:"),
    "N19b_baseline_required": (PF, "    if not any(k.startswith(\"baseline/\") for k in others) or bad:", "    if bad:"),
    "N19c_inventory_record": (PF, "    if conf[\"kind\"] == \"screening\":\n        others[\"inventory.copied\"]",
                              "    if False:\n        others[\"inventory.copied\"]"),
    "N20_write_control_refused": (CC, "    if any(a == \"--write-control\" or a.startswith(\"--write-control=\") for a in "
                                      "args):", "    if False:"),
    "C01_preflight_copied": (CC, "            \"copied_sha256\": map_sha256(copied_map(root, copy_paths)),       # fix 1 "
                                 "(I2): every copied file\n", ""),
    "C02_attempt_copied": (CC, "            \"copied_sha256\": map_sha256(copied_map(root, copy_paths)),       # 15c-P fix "
                               "1 (I2)\n", ""),
    "C03_copied_map_ignores": (CC, "                if f.is_file() and not any(fnmatch.fnmatch(x, pat) for x in parts for "
                                   "pat in _COPY_IGNORE_PATTERNS):", "                if f.is_file():"),
    "C04_screening_tree_check": (CC, "        if tree is None or tree != now:", "        if False:"),
    "C05_screening_tree_recorded": (CC, "        st[\"copied_tree_sha256\"][job] = map_sha256(copied)", "        pass"),
    "C06_gate_orphan_raise": (CC, "    if status == \"orphan\":", "    if False:"),
    "C07_record_unreadable": (CC, "        except (OSError, ValueError):\n            return \"not_clean\", p, "
                                  "{\"reasons\": [\"record_unreadable\"]}",
                              "        except ZeroDivisionError:\n            return \"not_clean\", p, "
                              "{\"reasons\": [\"record_unreadable\"]}"),
    "C08_real_never_synthetic": (CC, "    synthetic = getattr(exec_seam, \"synthetic\", False) is True and not "
                                     "getattr(exec_seam, \"cr_real_exec\", False)",
                                 "    synthetic = getattr(exec_seam, \"synthetic\", False) is True"),
    "C09_every_execution_gated": (CC, "    if (not synthetic or config is not None", "    if (config is not None"),
    "C10_seam_tag": (CC, "        if tag is not None and tag != _cmd_sha(retry_config(cfg) if retry else cfg):",
                     "        if False:"),
    "C11_seam_tag_retry": (CC, "tag != _cmd_sha(retry_config(cfg) if retry else cfg):", "tag != _cmd_sha(cfg):"),
    "C12a_ref_sha": (CC, "    if not path.is_file() or _sha(path) != (ref or {}).get(\"sha256\"):",
                     "    if not path.is_file():"),
    "C12b_ref_command": (CC, "            or b.get(\"test_command_sha256\") != _cmd_sha(cfg) or ", "            or "),
    "C12c_ref_clean": (CC, "    if (r.get(\"schema\") != PREFLIGHT_SCHEMA or r.get(\"verdict\") != \"clean\" or "
                           "r.get(\"reasons\")\n", "    if (r.get(\"schema\") != PREFLIGHT_SCHEMA\n"),
    "C13_retry_gate_condition": (CC, "    if preflight_dir is not None or not (getattr(seam, \"synthetic\", False) is True",
                                 "    if preflight_dir is not None or not (True"),
    "C14_retry_needs_dir": (CC, "        if preflight_dir is None:\n            raise CoordError(f\"retry of {job} needs",
                            "        if False:\n            raise CoordError(f\"retry of {job} needs"),
    "C15_retry_same_preflight": (CC, "        if ran != pf[\"sha256\"]:", "        if False:"),
    "C16_completion_ref": (CC, "                      cfg=cfg, preflight_ref=preflights[name],\n", ""),
    "C17a_real_exec_marked": (CC, "    seam.cr_real_exec, seam.synthetic = True, False", "    pass"),
    "C17b_real_exec_tagged": (CC, "    seam.test_command_sha256 = _cmd_sha(cfg)", "    pass"),
    "N21_interrupted_not_clean": (PF, "        if not completed:                     # an abort escaped", "        if False:  #"),
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
