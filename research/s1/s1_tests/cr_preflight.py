"""A3 Task 15c-P: the pre-flight driver (t15c_prep.md v8, runbook step 3a; controller ruling after Codex 9330a64).

For ONE config, run ONE unmutated guard baseline in exactly the context the config's mutants will run in, and
record it write-once:

* a fresh copy of the config's copy paths (``make_copy``; never the worktree, never reused);
* the exact cr.toml test command (``cr_coord.test_command(cfg)``; the cr.toml must render ``cfg``), whose
  ``--control`` is the FROZEN control file: its sha256 must equal the value recorded when it was created
  (``collect_only.json`` ``control_sha256``, beside it) before anything runs; it is never written;
* the module source pinned to the inventory's ``source_sha256``;
* the production child env ``cr_coord._env(copy, cfg, job_dir, job_id)`` (fix-4 scrub), contained by
  ``cr_guard.run_contained`` with the CR timeout as the outer deadline.

The record ``<record_dir>/preflight_<k>.json`` (k = the next free attempt number; opened with "x", so never
overwritten) holds ``binding`` = ``cr_coord.preflight_binding`` (harness, helpers, command, control, argfiles,
source, copy paths, pythonpath and the BOUND child env only - the prefixed variables + TZ; never the full env), the
guard sidecar's sha256 and a field summary, the wall time, the budget and the verdict:
``clean`` iff the guard reports ``survived`` with exit 0, its node set equals the frozen control, no node-set
mismatch, zero failures/errors/skips, outer and guard cleanup verified, no outer timeout, the copy's source and
control unchanged after the run and the outer wall time <= the selector budget (BUDGETS
["selector_baseline_target_s"]). Anything else is ``not_clean`` with its reasons, and is kept as a failure.

``cr_coord.check_preflight`` is the gate that consumes these records (run_manifest, calibration run_batch,
run_completion). ``run_all`` / the CLI runs the 21 active configs (12 screening, then 9 completion) sequentially,
skips a config that already has a clean record for its current binding, and stops at the first not_clean (new or
already recorded). This module is part of the hash-bound harness (cr_coord.HARNESS_FILES).

15c-P fix round 1 (task review): every attempt first writes ``started_<k>.json`` and then, whatever happens
(malformed sidecar or runner result, refused copy, runner or driver exception), a ``preflight_<k>.json`` in a
try/finally; a marker or attempt dir without a record is an orphan that blocks the config like a not_clean record.
The binding covers every copied file (``copied_sha256``); the after-run checks require the whole copy and the
source tree's copy paths unchanged; a config asking for ``--write-control`` is refused; the CLI cross-checks the
frozen control value with the baseline guard sidecars and the screening inventory.

CLI (run by the testenv interpreter, by path):
    cr_preflight.py all --src-root <clean checkout> --work-root <scratch dir> [--modules s1_journal,s1_locks]
"""
import argparse
import datetime as _dt
import json
import shlex
import sys
import time
import tomllib
from pathlib import Path

import cr_coord
import cr_guard
from cr_coord import BUDGETS, CoordError, CRConfig

SCHEMA = cr_coord.PREFLIGHT_SCHEMA
EVID_REL = "research/s1/s1_evidence/cr_a3"
MODULES = ("s1_journal", "s1_locks", "s1_trial", "s1_stage", "s1_slot", "s1_seal", "s1_collect")   # runbook R1
PYTHONPATH_REL = ("research/s1", "research/s1/s1_tests")
_GUARD_FIELDS = ("status", "exit_code", "rc", "counts", "node_set", "control_sha256", "elapsed_s")


def default_runner(cmd, *, cwd, env, job_dir, deadline_s):
    """The production runner: the guard command, contained (Win32 Job Object), CR timeout as the outer deadline."""
    out = Path(job_dir).parent
    return cr_guard.run_contained(list(cmd), cwd=Path(cwd), env=env, stdout_path=out / "guard_stdout.txt",
                                  stderr_path=out / "guard_stderr.txt", deadline_s=deadline_s)


class _Refused(Exception):
    """Internal: a post-copy refusal, recorded as not_clean."""


def _next_attempt(record_dir: Path, work_root: Path) -> int:
    k = 0
    while ((record_dir / f"preflight_{k:03d}.json").exists() or (record_dir / f"started_{k:03d}.json").exists()
           or (work_root / f"attempt_{k:03d}").exists()):
        k += 1
    return k


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


# fix 1 (I1): every guard sidecar field the verdict reads, with the type cr_guard.main writes
_GUARD_TYPES = {"status": lambda v: isinstance(v, str), "exit_code": _is_int,
                "rc": lambda v: v is None or _is_int(v),
                "counts": lambda v: isinstance(v, dict) and all(_is_int(v.get(k)) for k in
                                                                ("tests", "failures", "errors", "skipped", "passed")),
                "nodes": lambda v: isinstance(v, list) and all(isinstance(n, str) for n in v),
                "node_set": lambda v: v is None or isinstance(v, (dict, list)),
                "control_sha256": lambda v: v is None or isinstance(v, str),
                "cleanup": lambda v: isinstance(v, dict) and isinstance(v.get("verified"), bool),
                "elapsed_s": lambda v: v is None or (isinstance(v, (int, float)) and not isinstance(v, bool))}
_GUARD_REQUIRED = ("status", "exit_code", "counts", "nodes", "cleanup")


def _read_guard(side: Path) -> tuple:
    """(guard dict or None, reasons): a missing sidecar is (None, []); an unreadable / non-object one, or one whose
    fields are missing or of the wrong type, is (None, [reason...]) - never an exception (fix 1, I1)."""
    if not side.is_file():
        return None, []
    try:
        g = json.loads(side.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None, ["guard_sidecar_unreadable"]
    if not isinstance(g, dict):
        return None, ["guard_sidecar_unreadable"]
    bad = [f for f in _GUARD_REQUIRED if f not in g] + [f for f, ok in _GUARD_TYPES.items() if f in g and not ok(g[f])]
    return (None, [f"guard_field_malformed:{f}" for f in sorted(set(bad))]) if bad else (g, [])


def _read_run(run) -> tuple:
    """(run dict or None, reasons) for the runner's result (rc int, timed_out bool, cleanup.verified bool)."""
    if (isinstance(run, dict) and _is_int(run.get("rc")) and isinstance(run.get("timed_out"), bool)
            and isinstance(run.get("cleanup"), dict) and isinstance(run["cleanup"].get("verified"), bool)):
        return run, []
    return None, ["runner_result_malformed"]


def _verdict(guard: dict | None, run: dict | None, control_nodes: list, expected_control: str) -> list:
    """The clean conditions on a well-formed guard sidecar and outer run (either may be None: no evidence)."""
    reasons = []
    if run is None:
        reasons.append("no_run")
    if guard is None:
        reasons.append("no_guard_sidecar")
    else:
        if guard["status"] != "survived":
            reasons.append(f"guard_status:{guard['status']}")
        if set(guard["nodes"]) != set(control_nodes) or len(guard["nodes"]) != len(control_nodes):
            reasons.append("node_set_differs_from_control")
        if guard.get("node_set"):
            reasons.append("node_set_mismatch")
        if guard.get("control_sha256") != expected_control:
            reasons.append("guard_control_sha_differs")
        c = guard["counts"]
        if (c["failures"] or c["errors"] or c["skipped"] or not c["tests"]
                or c["passed"] != c["tests"] - c["failures"] - c["errors"] - c["skipped"]):
            reasons.append("counts")
        if not guard["cleanup"]["verified"]:
            reasons.append("cleanup_unverified")
        if guard["exit_code"] != 0:
            reasons.append("nonzero_exit")
        if guard.get("rc") not in (0, None):
            reasons.append("guard_rc_nonzero")
    if run is not None:
        if run["rc"] != 0 and "nonzero_exit" not in reasons:
            reasons.append("nonzero_exit")
        if run["timed_out"]:
            reasons.append("outer_timeout")
        if not run["cleanup"]["verified"] and "cleanup_unverified" not in reasons:
            reasons.append("cleanup_unverified")
    return reasons


CHANGED_PATHS_CAP = 50


def _map_diff(before: dict, after: dict, cap: int = CHANGED_PATHS_CAP) -> dict:
    """fix 2 (R1-M3): the relative paths added / removed / modified between two copied maps (each list sorted and
    capped at ``cap``), the total count and whether anything was cut."""
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    modified = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    total = len(added) + len(removed) + len(modified)
    return {"added": added[:cap], "removed": removed[:cap], "modified": modified[:cap], "total": total,
            "truncated": any(len(x) > cap for x in (added, removed, modified))}


def _write_record(path: Path, rec: dict) -> None:
    """Write-once: opened with "x", never overwritten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, indent=1, sort_keys=True))


def run_preflight(cfg: CRConfig, *, src_root: Path, copy_paths, record_dir: Path, cr_toml: Path,
                  expected_control_sha256: str, source_sha256: str, work_root: Path, runner=None,
                  clock=time.monotonic, budget_s: float | None = None, config_id: str | None = None) -> dict:
    """One pre-flight of one config (see the module docstring).

    Refusals BEFORE anything is created (CoordError, no record): a cr.toml that does not render ``cfg``, a config
    asking for ``--write-control`` or without exactly one ``--control``, a control whose sha256 is not
    ``expected_control_sha256``, a module source other than ``source_sha256``.

    fix 1 (I1): then a ``started_<k>.json`` marker is written (write-once) and EVERY outcome after it ends in a
    written ``preflight_<k>.json`` (try/finally): a copy that differs from the pins or carries a non-reviewed harness
    file, a runner exception, an unreadable or malformed guard sidecar or runner result, or any other driver error
    is a not_clean record with its reason. A marker without a record (a hard kill) is an orphan, which
    cr_coord.preflight_status / check_preflight and run_all treat like a not_clean record."""
    runner = runner or default_runner
    budget_s = float(BUDGETS["selector_baseline_target_s"] if budget_s is None else budget_s)
    src_root, record_dir, work_root = Path(src_root), Path(record_dir), Path(work_root)
    ident = cr_coord.config_identity(cfg, cr_toml, config_id=config_id or _posix_rel(cr_toml, src_root))
    ctl = cr_coord.control_rel(cfg)
    if cr_coord._sha(src_root / ctl) != expected_control_sha256:
        raise CoordError(f"control {ctl} sha256 {cr_coord._sha(src_root / ctl)} is not the frozen value "
                         f"{expected_control_sha256}: the pre-flight is refused")
    mod = cr_coord._posix(cfg.module_rel)
    if cr_coord._sha(src_root / mod) != source_sha256:
        raise CoordError(f"source {mod} sha256 {cr_coord._sha(src_root / mod)} is not the inventory source_sha256 "
                         f"{source_sha256}: the pre-flight is refused")
    binding = cr_coord.preflight_binding(cfg, src_root, copy_paths)          # what this pre-flight certifies
    src_before = cr_coord.copied_map(src_root, copy_paths)
    k = _next_attempt(record_dir, work_root)
    att = work_root / f"attempt_{k:03d}"
    copy, job_dir = att / "copy", att / "job"
    _write_record(record_dir / f"started_{k:03d}.json",
                  {"schema": SCHEMA, "attempt": k, "binding": binding, "work_dir": str(att),
                   "at": _dt.datetime.now(_dt.timezone.utc).isoformat()})
    reasons, info, hard, completed = [], {}, None, False
    try:
        copied = cr_coord.make_copy(src_root, copy_paths, copy)
        if copied.get(mod) != source_sha256 or copied.get(ctl) != expected_control_sha256:
            reasons.append("copy_differs_from_pins")
        drift = sorted({n for n in cr_coord.HARNESS_FILES for p in copy.rglob(n)
                        if cr_coord._sha(p) != cr_coord._sha(cr_coord.HARNESS_DIR / n)})
        reasons += [f"copy_harness_drift:{n}" for n in drift]
        info["copy_binding_matches"] = cr_coord.preflight_binding(cfg, copy, copy_paths) == binding
        if not info["copy_binding_matches"] and "copy_differs_from_pins" not in reasons:
            reasons.append("copy_differs_from_source")
        if reasons:
            raise _Refused()                                      # recorded in finally; nothing ran
        job_dir.mkdir(parents=True)
        env = cr_coord._env(copy, cfg, job_dir, f"preflight-{k:03d}")
        cmd = shlex.split(cr_coord.test_command(cfg))
        control_nodes = json.loads((copy / ctl).read_text(encoding="utf-8"))["nodes"]
        t0 = clock()
        raw, raised = None, False
        try:
            raw = runner(cmd, cwd=copy, env=env, job_dir=job_dir, deadline_s=cfg.timeout_s)
        except BaseException as e:            # noqa: BLE001 - any runner failure is a recorded not_clean pre-flight
            reasons.append(f"runner_exception:{type(e).__name__}")
            raised = True
            if not isinstance(e, Exception):
                hard = e
        info["wall_s"] = round(clock() - t0, 3)
        run, run_r = (None, []) if raised else _read_run(raw)
        side = job_dir / "guard.json"
        guard, guard_r = _read_guard(side)
        reasons += run_r + guard_r
        if side.is_file():
            info["guard"] = {"sha256": cr_coord._sha(side)} if guard is None else dict(
                {f: guard.get(f) for f in _GUARD_FIELDS}, sha256=cr_coord._sha(side), node_count=len(guard["nodes"]),
                cleanup_verified=guard["cleanup"]["verified"])
        if run is not None:
            info["outer"] = {"rc": run["rc"], "timed_out": run["timed_out"],
                             "cleanup_verified": run["cleanup"]["verified"]}
        reasons += [r for r in _verdict(guard, run, control_nodes, expected_control_sha256)
                    if not (r == "no_run" and (run_r or raised)) and not (r == "no_guard_sidecar" and guard_r)]
        info["source_unchanged"] = (copy / mod).is_file() and cr_coord._sha(copy / mod) == source_sha256
        info["control_unchanged"] = ((copy / ctl).is_file() and cr_coord._sha(copy / ctl) == expected_control_sha256
                                     and cr_coord._sha(src_root / ctl) == expected_control_sha256)
        if not info["source_unchanged"]:
            reasons.append("source_changed")
        if not info["control_unchanged"]:
            reasons.append("control_changed")
        copy_after, src_after = cr_coord.copied_map(copy, copy_paths), cr_coord.copied_map(src_root, copy_paths)
        if copy_after != copied:                                          # fix 1 (M7): the whole copy
            reasons.append("copy_changed")
            info.setdefault("changed_paths", {})["copy"] = _map_diff(copied, copy_after)     # fix 2 (R1-M3)
        if src_after != src_before:                                       # fix 1 (M7): the source tree's copy paths
            reasons.append("source_tree_changed")
            info.setdefault("changed_paths", {})["source_tree"] = _map_diff(src_before, src_after)
        if info["wall_s"] > budget_s:
            reasons.append("over_budget")
        completed = True
    except _Refused:
        completed = True
    except Exception as e:                    # noqa: BLE001 - recorded, never an unrecorded attempt (fix 1, I1)
        reasons.append(f"driver_exception:{type(e).__name__}")
        completed = True
    finally:
        if not completed:                     # an abort escaped the attempt body: never a clean record
            reasons.append("interrupted")
        rec = {"schema": SCHEMA, "attempt": k, "config_id": ident["config_id"], "module_rel": mod,
               "cr_toml": str(Path(cr_toml)), "cr_toml_sha256": ident["cr_toml_sha256"],
               "test_command": cr_coord.test_command(cfg), "binding": binding,
               "copy_binding_matches": info.get("copy_binding_matches"),
               "control": {"rel": ctl, "sha256_before": expected_control_sha256,
                           "frozen_source": "expected_control_sha256 (the CLI: collect_only.json control_sha256, "
                                            "cross-checked with the baseline guard sidecars and the inventory)",
                           "unchanged_after": info.get("control_unchanged")},
               "source": {"rel": mod, "sha256": source_sha256, "unchanged_after": info.get("source_unchanged")},
               "harness_sha256": binding["harness_sha256"], "guard": info.get("guard"), "outer": info.get("outer"),
               "wall_s": info.get("wall_s"), "budget_s": budget_s, "deadline_s": cfg.timeout_s,
               "changed_paths": info.get("changed_paths"),
               "work_dir": str(att), "verdict": "not_clean" if reasons else "clean", "reasons": reasons,
               "at": _dt.datetime.now(_dt.timezone.utc).isoformat()}
        _write_record(record_dir / f"preflight_{k:03d}.json", rec)
    if hard is not None:
        raise hard
    return rec                                  # the copy and job dir stay in work_root (scratch) as evidence


def _posix_rel(p: Path, root: Path) -> str:
    try:
        return cr_coord._posix(Path(p).resolve().relative_to(Path(root).resolve()).parent)
    except ValueError:
        return cr_coord._posix(Path(p).parent)


# ------------------------------------------------------------------------------------------------ all 21 configs
def config_from_toml(cr_toml: Path, pythonpath_rel=PYTHONPATH_REL) -> CRConfig:
    """Rebuild a config from its committed cr.toml (the test command is parsed back; config_identity, called by
    run_preflight, then requires the toml to render exactly this config)."""
    doc = tomllib.loads(Path(cr_toml).read_text(encoding="utf-8"))["cosmic-ray"]
    parts = shlex.split(doc["test-command"])
    if parts[1:3] != ["-m", "cr_guard"] or parts[3] != "--deadline" or parts[5] != "--target":
        raise CoordError(f"{cr_toml}: not a cr_guard test command")
    return CRConfig(python=Path(parts[0]), module_rel=doc["module-path"], guard_args=parts[7:],
                    pythonpath_rel=list(pythonpath_rel), timeout_s=float(doc["timeout"]),
                    guard_deadline_s=float(parts[4]), target_module=parts[6])


def discover(root: Path, modules=MODULES) -> list:
    """The active configs under <root>/research/s1/s1_evidence/cr_a3, in runbook order: every module's screening
    config(s) first (R1 module order; shards sorted), then every module's completion shards (c1, c2, ...)."""
    ev = Path(root) / EVID_REL
    screen, comp = [], []
    for m in modules:
        d = ev / m
        if (d / "cr.toml").is_file():
            screen.append(d)
        else:
            screen += sorted(p.parent for p in d.glob("*/cr.toml") if p.parent.name != "completion")
        comp += sorted((p.parent for p in (d / "completion").glob("c*/cr.toml")), key=lambda q: int(q.name[1:]))
    return [{"rel": cr_coord._posix(d.relative_to(root)), "dir": d, "module": d.relative_to(ev).parts[0],
             "kind": "completion" if d.parent.name == "completion" else "screening"} for d in screen + comp]


def copy_paths_for(root: Path, cfg: CRConfig) -> list:
    """Runbook step 2: research/s1/*.py + research/s1/docs + research/s1/s1_tests + the control (+ @argfiles)."""
    mods = sorted(f"research/s1/{p.name}" for p in (Path(root) / "research/s1").glob("*.py"))
    extra = [cr_coord.control_rel(cfg)] + [cr_coord._posix(str(a)[1:]) for a in cfg.guard_args
                                           if str(a).startswith("@")]
    return mods + ["research/s1/docs", "research/s1/s1_tests"] + extra


def source_pin(root: Path, conf: dict, cfg: CRConfig) -> str:
    """The inventory source_sha256: the screening config's own inventory.json; for a completion shard, every
    screening inventory of its module (they must agree)."""
    ev = Path(root) / EVID_REL / conf["module"]
    invs = [conf["dir"] / "inventory.json"] if conf["kind"] == "screening" else \
        sorted([p for p in ev.glob("inventory.json")] + [p for p in ev.glob("*/inventory.json")])
    pins = set()
    for p in invs:
        inv = json.loads(p.read_text(encoding="utf-8"))
        if cr_coord._posix(inv["module_rel"]) != cr_coord._posix(cfg.module_rel):
            raise CoordError(f"{p}: inventory module {inv['module_rel']} is not {cfg.module_rel}")
        pins.add(inv["source_sha256"])
    if len(pins) != 1:
        raise CoordError(f"{conf['rel']}: no single inventory source_sha256 ({sorted(pins)})")
    return pins.pop()


def frozen_control_sha256(root: Path, conf: dict, cfg: CRConfig) -> str:
    """The frozen control value: collect_only.json control_sha256 (recorded when the control was created). fix 1
    (M5): it must equal every INDEPENDENT record of the same control - each historical baseline guard sidecar
    (baseline/run*/guard.json control_sha256; at least one) and, for a screening config, the inventory's copied
    map entry - or the config is refused. No git call: a clean checkout at the agreed head stays the operator's
    duty (t15c_prep.md)."""
    d, ctl = conf["dir"], cr_coord.control_rel(cfg)
    expected = json.loads((d / "collect_only.json").read_text(encoding="utf-8"))["control_sha256"]
    others = {f"baseline/{g.parent.name}": json.loads(g.read_text(encoding="utf-8")).get("control_sha256")
              for g in sorted(d.glob("baseline/run*/guard.json"))}
    if conf["kind"] == "screening":
        others["inventory.copied"] = (json.loads((d / "inventory.json").read_text(encoding="utf-8")).get("copied")
                                      or {}).get(ctl)
    bad = {k: v for k, v in others.items() if v != expected}
    if not any(k.startswith("baseline/") for k in others) or bad:
        raise CoordError(f"{conf['rel']}: the frozen control value {expected} disagrees with (or lacks) its "
                         f"independent records {bad or '(no baseline guard sidecar)'}: refused")
    return expected


def run_all(root: Path, *, work_root: Path, modules=MODULES, runner=None, clock=time.monotonic,
            pythonpath_rel=PYTHONPATH_REL) -> list:
    """Pre-flight every active config sequentially (discover order). A config whose records already hold a clean
    pre-flight for its current binding is skipped ("already_clean"); one with a not_clean record for that binding
    stops the run ("blocked_not_clean", not retried); otherwise one new attempt runs, and a not_clean verdict
    stops the run. Records are write-once, so a re-run is safe."""
    root, out = Path(root), []
    for conf in discover(root, modules):
        cfg = config_from_toml(conf["dir"] / "cr.toml", pythonpath_rel)
        cp = copy_paths_for(root, cfg)
        record_dir = conf["dir"] / "preflight"
        wr = Path(work_root) / conf["rel"].replace("/", "__")
        status, p, _ = cr_coord.preflight_status(record_dir, cr_coord.preflight_binding(cfg, root, cp))
        orphans = [a for a in sorted(wr.glob("attempt_*")) if not (record_dir / f"preflight_{a.name[8:]}.json")
                   .exists()] if wr.is_dir() else []
        if status == "orphan" or orphans:                       # fix 1 (I1): a crash is never retried past
            out.append({"rel": conf["rel"], "verdict": "blocked_orphan", "record": str(p or orphans[0])})
            break
        if status == "clean":
            out.append({"rel": conf["rel"], "verdict": "already_clean", "record": str(p)})
            continue
        if status == "not_clean":
            out.append({"rel": conf["rel"], "verdict": "blocked_not_clean", "record": str(p)})
            break
        expected = frozen_control_sha256(root, conf, cfg)
        rec = run_preflight(cfg, src_root=root, copy_paths=cp, record_dir=record_dir, cr_toml=conf["dir"] / "cr.toml",
                            expected_control_sha256=expected, source_sha256=source_pin(root, conf, cfg),
                            work_root=wr, runner=runner, clock=clock,
                            config_id=conf["rel"])
        out.append({"rel": conf["rel"], "verdict": rec["verdict"], "reasons": rec["reasons"],
                    "record": str(record_dir / f"preflight_{rec['attempt']:03d}.json")})
        if rec["verdict"] != "clean":
            break
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="cr_preflight.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("all", help="pre-flight the active configs in runbook order; stop at the first not_clean")
    a.add_argument("--src-root", required=True, type=Path)
    a.add_argument("--work-root", required=True, type=Path)
    a.add_argument("--modules", default=",".join(MODULES))
    args = ap.parse_args(argv)
    res = run_all(args.src_root, work_root=args.work_root, modules=[m for m in args.modules.split(",") if m])
    for r in res:
        print(json.dumps(r, sort_keys=True))
    return 0 if res and all(r["verdict"] in ("clean", "already_clean") for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
