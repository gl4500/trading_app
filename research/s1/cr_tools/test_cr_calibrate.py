"""A3 Task 15c-E: the reviewed 15c execution driver for ONE screening config's calibration session (t15c_prep.md
runbook steps 1-4 and 6 without any retry; step 5, derive_cap, as a separate subcommand).

This file and the driver live in research/s1/cr_tools/, OUTSIDE every copy path (research/s1/*.py, research/s1/docs,
research/s1/s1_tests, the config's control / argfile), so they change no pre-flight binding and no inventory.

The library calls here pass the test-only ``_test_harness_anywhere`` (the worktree harness modules this test process
imported are byte-identical to each toy archive's); the CLI's archive-pinned import is tested on its own.

SYNTHETIC seams only, injected through the test-only ``_test_exec_factory`` parameter (the CLI cannot reach it), on
tmp toy trees shaped like research/s1; plus one tmp toy end-to-end with the REAL path (default runner pre-flights,
real_exec: real Cosmic Ray + the real guard) on a two-function toy module. No S1 module, no real config.
"""
import ast
import hashlib
import inspect
import json
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

import cr_coord
import cr_preflight
from test_s1_a3_cr_completion import CLEAN_KILL, CLEAN_SURV, CRERR_SURV, GUARD_ERROR, GUARD_TIMEOUT, UNCERTAIN_SURV

HARNESS_MODULES = ("cr_guard", "cr_reconcile", "cr_coord", "cr_launch", "cr_preflight")
from test_s1_a3_cr_guard import PY, sha
from test_s1_a3_cr_preflight import guard_runner

EVID_REL = "research/s1/s1_evidence/cr_a3"
MANIFEST_REL = "research/s1/s1_evidence/a3/t15c_prep_hashes.txt"
NODES = ["research/s1/s1_tests/test_x.py::test_a", "research/s1/s1_tests/test_x.py::test_b"]


def _drv():
    try:
        import cr_calibrate
    except ImportError:
        cr_calibrate = None
    assert cr_calibrate is not None, "the 15c execution driver cr_calibrate exists"
    return cr_calibrate


# ------------------------------------------------------------------------------------------------ the toy tree
def write_manifest(root):
    """a3/t15c_prep_hashes.txt over every file under cr_a3 and the s1_tests harness files (LF, sha256sum format)."""
    ev = root / EVID_REL
    files = sorted(p for p in ev.rglob("*") if p.is_file())
    files += [root / "research/s1/s1_tests" / n for n in cr_coord.HARNESS_FILES]
    m = root / MANIFEST_REL
    m.parent.mkdir(parents=True, exist_ok=True)
    m.write_bytes("".join(f"{sha(p)}  {p.relative_to(root).as_posix()}\n" for p in files).encode("utf-8"))
    return m


def _config(d, rel, guard_args, *, inventory=None):
    d.mkdir(parents=True, exist_ok=True)
    cfg = cr_coord.CRConfig(python=PY, module_rel="research/s1/s1_x.py", target_module="s1_x",
                            pythonpath_rel=["research/s1", "research/s1/s1_tests"],
                            guard_args=["--control", f"{rel}/control.json", *guard_args])
    cr_coord.write_cr_toml(d / "cr.toml", cfg)
    (d / "collect_only.json").write_text(json.dumps({"control_sha256": sha(d / "control.json")}), encoding="utf-8")
    (d / "baseline" / "run1").mkdir(parents=True)
    (d / "baseline" / "run1" / "guard.json").write_text(json.dumps({"control_sha256": sha(d / "control.json")}),
                                                        encoding="utf-8")
    return cfg


def toy(tmp_path, *, n_items=30, items=None, module_src="X = 1\n", test_src=None, runner="synthetic",
        completion=True, screens=("a",)):
    """A research/s1-shaped tree: module s1_x, one screening config cr_a3/s1_x/a (n_items synthetic WorkItems, or the
    given real ones), completion shards c1 (test_a) / c2 (test_b) with pool.json, clean pre-flights for all three
    configs, and the hash manifest written last. Returns (root, items)."""
    root = tmp_path / "repo"
    s1 = root / "research" / "s1"
    (s1 / "docs").mkdir(parents=True)
    (s1 / "docs" / "d.md").write_text("doc\n", encoding="utf-8")
    t = s1 / "s1_tests"
    t.mkdir()
    for n in cr_coord.HARNESS_FILES:                                  # byte-identical harness, as in a real archive
        shutil.copy2(cr_coord.HARNESS_DIR / n, t / n)
    (t / "test_x.py").write_text(test_src or "def test_a():\n    pass\n\n\ndef test_b():\n    pass\n", encoding="utf-8")
    (s1 / "s1_x.py").write_text(module_src, encoding="utf-8")
    ev = root / EVID_REL / "s1_x"
    if items is None:
        items = [{"job_id": f"j{i:02d}", "module_path": "research/s1/s1_x.py", "operator": "core/NumberReplacer",
                  "operator_args": {}, "occurrence": i, "start": [1, 4], "end": [1, 5]} for i in range(n_items)]
    items = cr_coord.order_items(items)
    for scr in screens:                                   # screening configs (shards a, b, ...), discover order
        rel = f"{EVID_REL}/s1_x/{scr}"
        (ev / scr).mkdir(parents=True)
        (ev / scr / "control.json").write_text(json.dumps({"nodes": sorted(NODES)}), encoding="utf-8")
        cfg = _config(ev / scr, rel, ["research/s1/s1_tests/test_x.py"])
        inv = ev / scr / "inventory.json"
        inv.write_text(json.dumps({"module_rel": "research/s1/s1_x.py", "source_sha256": sha(s1 / "s1_x.py"),
                                   "test_command": cr_coord.test_command(cfg), "items": items,
                                   "copied": {f"{rel}/control.json": sha(ev / scr / "control.json")}}),
                       encoding="utf-8")
        ids = [i["job_id"] for i in items]
        (ev / scr / "inventory_filtered.json").write_text(json.dumps({
            "kept": items, "post_filter_count": len(items), "inventory_sha256": sha(inv)}), encoding="utf-8")
        (ev / scr / "batch_plan.json").write_text(json.dumps({
            "inventory_sha256": sha(inv), "candidates": len(ids), "calibration_batch": ids[:24],
            "pending_after_calibration": ids[24:], "derived_cap": None, "derived_cap_rule": "toy", "scenario": {}}),
            encoding="utf-8")
    for k, node in ((("c1", NODES[0]), ("c2", NODES[1])) if completion else ()):
        d = ev / "completion" / k
        crel = f"{EVID_REL}/s1_x/completion/{k}"
        d.mkdir(parents=True)
        (d / "control.json").write_text(json.dumps({"nodes": [node]}), encoding="utf-8")
        (d / "nodes.txt").write_text(node + "\n", encoding="utf-8")
        _config(d, crel, [f"@{crel}/nodes.txt"])
    if completion:
        (ev / "completion" / "pool.json").write_text(json.dumps({"nodes": sorted(NODES),
                                                                 "nodes_sha256": cr_coord.pool_sha256(NODES)}),
                                                     encoding="utf-8")
    out = cr_preflight.run_all(root, work_root=tmp_path / "pfw", modules=["s1_x"],
                               runner=guard_runner() if runner == "synthetic" else None, clock=lambda: 0.0)
    assert [r["verdict"] for r in out] == ["clean"] * (len(screens) + (2 if completion else 0)), out
    write_manifest(root)
    return root, items


def factory(screen=None, comp=None, retry=None, calls=None, on_call=None):
    """A synthetic exec factory (declared synthetic). ``screen`` {job: record}, ``comp`` {(shard, job): record},
    ``retry`` {job: record}; default: screening killed, completion survived. ``on_call(kind, job)`` hook."""
    calls = calls if calls is not None else []

    def make(cfg):
        args = [str(a) for a in cfg.guard_args]
        ctl = args[args.index("--control") + 1]
        kind = ctl.split("/")[-2] if "/completion/" in ctl else ("retry" if cfg.timeout_s > 300 else "screen")

        def seam(item, copy_root, job_dir):
            calls.append((kind, item["job_id"]))
            if on_call:
                on_call(kind, item["job_id"])
            if kind == "screen":
                r = (screen or {}).get(item["job_id"], CLEAN_KILL)
            elif kind == "retry":
                r = (retry or {}).get(item["job_id"], CLEAN_KILL)
            else:
                r = (comp or {}).get((kind, item["job_id"]), CLEAN_SURV)
            if isinstance(r, BaseException):
                raise r
            return dict(r) if isinstance(r, dict) else r          # None / a non-record pass through raw
        seam.synthetic = True
        return seam
    return make


def _run(root, work, config, **kw):
    """A library session call; the test process imported the worktree harness (byte-identical to the toy's)."""
    kw.setdefault("_test_harness_anywhere", True)
    kw.setdefault("_test_allow_git_src_root", True)
    kw.setdefault("_test_long_paths_reader", lambda: 1)
    return _drv().session(root, work, config, **kw)


def _session(root, tmp_path, **kw):
    return _run(root, tmp_path / "work", "s1_x/a", **kw)


@pytest.fixture(autouse=True)
def _no_real_registry(monkeypatch):
    """Fix round 2: no test may read the real Windows registry - the driver's real reader is replaced by one that
    fails the test; tests inject their own reader (or a fake winreg module)."""
    def forbidden(*a, **k):
        raise AssertionError("a test reached the REAL registry reader")
    REAL_READER.setdefault("fn", getattr(_drv(), "_read_long_paths", None))
    monkeypatch.setattr(_drv(), "_read_long_paths", forbidden, raising=False)


REAL_READER = {}


def _dcap(session_root, config, **kw):
    kw.setdefault("_test_harness_anywhere", True)
    kw.setdefault("_test_allow_git_src_root", True)
    return _drv().derive_cap(session_root, config, **kw)


def _no_resolutions(tmp_path):
    return not list((tmp_path / "work").rglob("batch_*_resolution.json"))


# --------------------------------------------------------------------------------------------- the happy path
def test_E_session_runs_exactly_the_calibration_batch_then_completes_each_survivor(tmp_path):
    root, items = toy(tmp_path)
    calls = []
    rep = _session(root, tmp_path, _test_exec_factory=factory(screen={"j03": CLEAN_SURV, "j07": CLEAN_SURV},
                                                              calls=calls))
    ids = [i["job_id"] for i in items]
    croot = tmp_path / "work" / "s1_x__a"
    man = json.loads((croot / "batch_000.json").read_text(encoding="utf-8"))
    assert man["items"] == ids[:24] and not (croot / "batch_001.json").exists(), "the calibration batch only"
    assert [j for k, j in calls if k == "screen"] == ids[:24]
    assert [c for c in calls if c[0] != "screen"] == [("c1", "j03"), ("c2", "j03"), ("c1", "j07"), ("c2", "j07")]
    assert rep["stop"] is None and rep["screening"]["labels"]["j03"] == "survived"
    assert {j: c["label"] for j, c in rep["completions"].items()} == {"j03": "survived", "j07": "survived"}
    assert rep["screening"]["preflight"]["sha256"] == sha(root / EVID_REL / "s1_x/a/preflight/preflight_000.json")
    assert set(rep["completions"]["j03"]["preflights"]) == {"c1", "c2"}
    assert rep["manifest"]["verified"] is True and rep["manifest"]["entries"] > 0
    assert rep["config_id"] == "s1_x/a" and rep["src_root"] == str(root)
    assert rep["screening"]["fence_s"] and rep["screening"]["item_s"] and rep["wall_s"] >= 0
    on_disk = json.loads((croot / "report_session-000.json").read_text(encoding="utf-8"))
    assert on_disk == rep and _no_resolutions(tmp_path)


def test_E_a_whole_module_selector_has_no_completion_stage(tmp_path):
    """journal / locks / trial / stage: the screening selector IS the full plan pool (t15c_prep.md), so a
    module without completion shards and without pool.json settles its survivors at screening."""
    root, _ = toy(tmp_path, completion=False)
    calls = []
    rep = _session(root, tmp_path, _test_exec_factory=factory(screen={"j03": CLEAN_SURV}, calls=calls))
    assert rep["stop"] is None and rep["completion_stage"] == "none: whole-module selector", rep
    assert rep["completions"] == {} and all(k == "screen" for k, _ in calls)


def test_E_a_completion_stage_without_its_pool_is_refused(tmp_path):
    root, _ = toy(tmp_path)
    (root / EVID_REL / "s1_x/completion/pool.json").unlink()
    write_manifest(root)
    calls = []
    with pytest.raises(cr_coord.CoordError, match=r"completion shards without pool\.json"):
        _session(root, tmp_path, _test_exec_factory=factory(calls=calls))
    assert calls == []


def test_E_a_pool_without_completion_shards_is_refused(tmp_path):
    root, _ = toy(tmp_path, completion=False)
    (root / EVID_REL / "s1_x/completion").mkdir(parents=True)
    (root / EVID_REL / "s1_x/completion/pool.json").write_text(json.dumps({"nodes": NODES}), encoding="utf-8")
    write_manifest(root)
    with pytest.raises(cr_coord.CoordError, match=r"pool\.json without completion shards"):
        _session(root, tmp_path, _test_exec_factory=factory())


def test_E_a_work_root_too_long_for_the_copies_is_refused_before_anything(tmp_path):
    """A completion copy sits at <work>/<tag>/session-000/completion/<job>/<shard>/copies/<job>; Windows refuses a
    child working directory near MAX_PATH (WinError 267), so the driver refuses such a work root up front."""
    root, _ = toy(tmp_path, items=[{"job_id": "f" * 32, "module_path": "research/s1/s1_x.py",
                                    "operator": "core/NumberReplacer", "operator_args": {}, "occurrence": 0,
                                    "start": [1, 4], "end": [1, 5]}])
    deep = tmp_path / ("w" * 60) / ("v" * 60)
    calls = []
    with pytest.raises(cr_coord.CoordError, match=r"the work root is too long"):
        _run(root, deep, "s1_x/a", _test_exec_factory=factory(calls=calls))
    assert calls == [] and not deep.exists()


def test_E_the_report_holds_no_environment_values(tmp_path, monkeypatch):
    monkeypatch.setenv("S1_CE_SECRET_TOKEN", "ce-secret-value-4471")
    root, _ = toy(tmp_path)
    _session(root, tmp_path, _test_exec_factory=factory(screen={"j03": CLEAN_SURV}))
    text = (tmp_path / "work" / "s1_x__a" / "report_session-000.json").read_text(encoding="utf-8")
    assert "S1_CE_SECRET_TOKEN" not in text and "ce-secret-value-4471" not in text and '"env"' not in text


# ------------------------------------------------------------------------------------------------- refusals
def test_E_a_config_root_that_exists_is_refused(tmp_path):
    root, _ = toy(tmp_path)
    (tmp_path / "work" / "s1_x__a").mkdir(parents=True)
    calls = []
    with pytest.raises(cr_coord.CoordError, match=r"config root .* already exists: one fresh session root"):
        _session(root, tmp_path, _test_exec_factory=factory(calls=calls))
    assert calls == []


@pytest.mark.parametrize("config", ["s1_x/completion/c1", "s1_x/zzz", "s1_y"])
def test_E_only_a_screening_config_can_be_calibrated(tmp_path, config):
    root, _ = toy(tmp_path)
    with pytest.raises(cr_coord.CoordError, match=r"not a screening config"):
        _run(root, tmp_path / "work", config, _test_exec_factory=factory())


@pytest.mark.parametrize("case", ["tampered", "missing_file", "no_manifest", "malformed_line", "empty_manifest"])
def test_E_the_src_root_must_verify_against_its_hash_manifest(tmp_path, case):
    root, _ = toy(tmp_path)
    ctl = root / EVID_REL / "s1_x/completion/pool.json"
    m = root / MANIFEST_REL
    if case == "tampered":
        ctl.write_text(ctl.read_text(encoding="utf-8") + " ", encoding="utf-8")
    elif case == "missing_file":
        ctl.unlink()
    elif case == "malformed_line":                   # a line that names nothing verifiable is refused, never skipped
        m.write_bytes(m.read_bytes() + b"not-a-sha256 research/s1/s1_x.py\n")
    elif case == "empty_manifest":
        m.write_bytes(b"\n")
    else:
        m.unlink()
    calls = []
    with pytest.raises(cr_coord.CoordError, match=r"t15c_prep_hashes\.txt"):
        _session(root, tmp_path, _test_exec_factory=factory(calls=calls))
    assert calls == [] and not (tmp_path / "work").exists()


def test_E_the_running_harness_must_be_the_src_roots(tmp_path):
    root, _ = toy(tmp_path)
    g = root / "research/s1/s1_tests/cr_guard.py"
    g.write_text(g.read_text(encoding="utf-8") + "\n# other\n", encoding="utf-8")
    write_manifest(root)
    with pytest.raises(cr_coord.CoordError, match=r"harness module cr_guard .* is not the bytes the --src-root's "
                                                  r"t15c_prep_hashes\.txt approves"):
        _session(root, tmp_path, _test_exec_factory=factory())


def test_E_the_plan_must_be_the_calibration_first_plan(tmp_path):
    root, _ = toy(tmp_path)
    p = root / EVID_REL / "s1_x/a/batch_plan.json"
    plan = json.loads(p.read_text(encoding="utf-8"))
    plan["calibration_batch"] = plan["calibration_batch"][1:] + plan["pending_after_calibration"][:1]
    p.write_text(json.dumps(plan), encoding="utf-8")
    write_manifest(root)
    with pytest.raises(cr_coord.CoordError, match=r"calibration_batch is not the first 24 kept ids"):
        _session(root, tmp_path, _test_exec_factory=factory())


def test_E_the_plan_must_be_bound_to_its_inventory(tmp_path):
    root, _ = toy(tmp_path)
    p = root / EVID_REL / "s1_x/a/batch_plan.json"
    plan = json.loads(p.read_text(encoding="utf-8"))
    p.write_text(json.dumps(dict(plan, inventory_sha256="0" * 64)), encoding="utf-8")
    write_manifest(root)
    with pytest.raises(cr_coord.CoordError, match=r"batch_plan\.json is not bound to its inventory\.json"):
        _session(root, tmp_path, _test_exec_factory=factory())


def test_E_a_stale_preflight_is_refused_by_the_gates(tmp_path):
    root, _ = toy(tmp_path)
    (root / "research/s1/s1_tests/test_new.py").write_text("def test_z():\n    pass\n", encoding="utf-8")
    calls = []
    rep = _session(root, tmp_path, _test_exec_factory=factory(calls=calls))
    assert calls == [] and rep["stop"]["kind"] == "exception", rep["stop"]
    assert "no clean pre-flight bound to the current context" in rep["stop"]["detail"]


# ------------------------------------------------------------------------------------------------ stop rules
@pytest.mark.parametrize("record,kind", [(UNCERTAIN_SURV, "cleanup_uncertain"), (CRERR_SURV, "error"),
                                         (OSError("launcher vanished"), "error")])
def test_E_a_screening_stop_ends_the_session_with_no_further_candidate(tmp_path, record, kind):
    root, items = toy(tmp_path)
    calls = []
    rep = _session(root, tmp_path, _test_exec_factory=factory(screen={"j02": CLEAN_SURV, "j05": record},
                                                              calls=calls))
    assert rep["stop"]["kind"] == kind, rep["stop"]
    assert [j for _, j in calls] == [i["job_id"] for i in items[:6]], "nothing after the stopping item"
    assert rep["completions"] == {} and _no_resolutions(tmp_path)
    raw = json.loads((tmp_path / "work/s1_x__a/session-000/jobs/j05/policy_result.json").read_text(encoding="utf-8"))
    if isinstance(record, BaseException):     # the policy seam keeps the fact of an inner exception, then re-raises
        assert raw["exception"] == "OSError: launcher vanished" and raw["halt"] is True, raw
    else:                                     # halting, but run_batch stops on it by itself: returned untouched
        assert raw["raw"] == record and raw["halt"] is True, raw
        assert raw["returned_exec_status"] == record["exec_status"], raw


def test_E_a_guard_error_label_ends_the_session_before_any_completion(tmp_path):
    """Amended for X26: the policy seam halts AT the error item (zero next call)."""
    root, items = toy(tmp_path)
    calls = []
    rep = _session(root, tmp_path, _test_exec_factory=factory(screen={"j02": CLEAN_SURV, "j05": GUARD_ERROR},
                                                              calls=calls))
    assert rep["stop"]["kind"] == "policy_halt" and "j05" in rep["stop"]["detail"], rep["stop"]
    assert [j for _, j in calls] == [i["job_id"] for i in items[:6]] and rep["completions"] == {}


def test_E_a_screening_fence_refusal_ends_the_session(tmp_path):
    root, _ = toy(tmp_path)
    now = [0.0]

    def clock():
        v = now[0]
        now[0] = 1e9                                   # after the session start, everything is past the fence
        return v
    calls = []
    rep = _session(root, tmp_path, clock=clock, _test_exec_factory=factory(calls=calls))
    assert calls == [] and rep["stop"]["kind"] == "fence", rep["stop"]


def test_E_a_screening_timeout_stops_the_session_with_no_retry(tmp_path):
    """Codex X26 disposition item 1: a timeout stops and is reported; no run_retry, no resolve, no resume."""
    root, items = toy(tmp_path)
    calls = []
    rep = _session(root, tmp_path, _test_exec_factory=factory(screen={"j02": CLEAN_SURV, "j05": GUARD_TIMEOUT},
                                                              retry={"j05": CLEAN_KILL}, calls=calls))
    assert [j for _, j in calls] == [i["job_id"] for i in items[:6]], "no retry and nothing after j05"
    assert "retry" not in rep and not (tmp_path / "work/s1_x__a/session-000/retries").exists()
    assert rep["screening"]["stop_reason"] == "timeout: j05"
    assert rep["stop"]["kind"] == "timeout" and rep["completions"] == {} and _no_resolutions(tmp_path)
    assert cr_coord.unresolved_stops(tmp_path / "work/s1_x__a/session-000"), "the stop stays unresolved"


@pytest.mark.parametrize("record,kind", [(UNCERTAIN_SURV, "cleanup_uncertain"),
                                         (OSError("launcher vanished"), "error")])
def test_E_a_completion_stop_ends_the_session_and_later_survivors_wait(tmp_path, record, kind):
    root, _ = toy(tmp_path)
    calls = []
    rep = _session(root, tmp_path, _test_exec_factory=factory(
        screen={"j03": CLEAN_SURV, "j07": CLEAN_SURV}, comp={("c1", "j03"): record}, calls=calls))
    assert rep["stop"]["kind"] == kind, rep["stop"]
    assert [c for c in calls if c[0] != "screen"] == [("c1", "j03")], "j03's c2 and j07 never start"
    assert "j07" not in rep["completions"] and _no_resolutions(tmp_path)


def test_E_a_coordinator_exception_ends_the_session(tmp_path, monkeypatch):
    root, _ = toy(tmp_path)

    def boom(*a, **k):
        raise cr_coord.CoordError("synthetic coordinator refusal")
    monkeypatch.setattr(cr_coord, "run_completion", boom)
    rep = _session(root, tmp_path, _test_exec_factory=factory(screen={"j03": CLEAN_SURV, "j07": CLEAN_SURV}))
    assert rep["stop"]["kind"] == "exception" and "synthetic coordinator refusal" in rep["stop"]["detail"]


def test_E_a_completion_record_with_pending_shards_is_a_stop_even_without_a_stopped_attempt():
    """Defence in depth: a completion record that still has pending shards never counts as settled, whatever its
    attempts say (run_completion normally also reports such a shard as refused or stopped)."""
    stop = _drv()._completion_stop({"label": None, "attempts": [{"shard": "c1", "stopped": False}],
                                    "pending_shards": ["c2"]})
    assert stop == {"kind": "unresolved_stop", "detail": "completion pending ['c2']"}, stop
    assert _drv()._completion_stop({"label": "survived", "attempts": [], "pending_shards": []}) is None


# --------------------------------------------------------------------- no retry, no resolve, no resume (Codex X26)
def test_E_the_driver_has_no_retry_resolve_or_resume_path():
    drv = _drv()
    params = inspect.signature(drv.session).parameters
    assert "resume" not in params and "retry" not in params, params
    tree = ast.parse(Path(drv.__file__).read_text(encoding="utf-8"))
    used = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    banned = used & {"run_retry", "resolve_stop", "retry_config"}
    assert not banned, banned
    for flag in ("--resume-completions", "--retry"):
        with pytest.raises(SystemExit):
            drv.main(["session", "--src-root", "R", "--work-root", "W", "--config", "s1_x/a", flag])


# --------------------------------------------------------------------------------------------- derive-cap + CLI
def test_E_derive_cap_writes_the_record_once_and_never_runs_anything(tmp_path):
    root, _ = toy(tmp_path)
    _session(root, tmp_path, _test_exec_factory=factory())
    croot = tmp_path / "work" / "s1_x__a"
    rec = _dcap(croot / "session-000", "s1_x/a")
    assert rec["measured_items"] == 24 and (croot / "derived_cap.json").is_file()
    assert rec["config"]["config_id"] == "s1_x/a"
    with pytest.raises(cr_coord.CoordError, match=r"derived_cap\.json already exists"):
        _dcap(croot / "session-000", "s1_x/a")
    with pytest.raises(cr_coord.CoordError, match=r"session .* is not a calibration session of s1_x/b"):
        _dcap(croot / "session-000", "s1_x/b")


def test_E_derive_cap_re_verifies_the_src_root(tmp_path):
    root, _ = toy(tmp_path)
    _session(root, tmp_path, _test_exec_factory=factory())
    pool = root / EVID_REL / "s1_x/completion/pool.json"
    pool.write_text(pool.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(cr_coord.CoordError, match=r"t15c_prep_hashes\.txt does not verify"):
        _dcap(tmp_path / "work" / "s1_x__a" / "session-000", "s1_x/a")
    assert not (tmp_path / "work" / "s1_x__a" / "derived_cap.json").exists()


def test_E_the_report_is_write_once(tmp_path):
    root, _ = toy(tmp_path)
    rep = _session(root, tmp_path, _test_exec_factory=factory())
    croot = tmp_path / "work" / "s1_x__a"
    before = (croot / "report_session-000.json").read_bytes()
    with pytest.raises(FileExistsError):
        _drv()._finish(dict(rep, stop={"kind": "x"}), croot, croot / "session-000", 0.0)
    assert (croot / "report_session-000.json").read_bytes() == before


def test_E_the_cli_cannot_reach_the_test_seams_and_pins_the_harness_first(tmp_path, monkeypatch):
    drv = _drv()
    seen, order = {}, []

    def fake_load(src_root, *, fresh, **kw):
        order.append(("load", str(src_root), fresh, dict(kw)))

    def fake_session(src_root, work_root, config, **kw):
        order.append(("session",))
        seen.update(kw, src_root=src_root, work_root=work_root, config=config)
        return {"stop": None}
    monkeypatch.setattr(drv, "load_harness", fake_load)
    monkeypatch.setattr(drv, "session", fake_session)
    rc = drv.main(["session", "--src-root", "R", "--work-root", "W", "--config", "s1_x/a"])
    assert rc == 0 and order == [("load", "R", True, {}), ("session",)], order
    assert not [k for k in seen if k.startswith("_test")], seen
    monkeypatch.setattr(drv, "session", lambda *a, **k: {"stop": {"kind": "policy_halt"}})
    assert drv.main(["session", "--src-root", "R", "--work-root", "W", "--config", "s1_x/a"]) == 1, "a stop: rc 1"
    for bad in ("--test-exec-factory", "--test-harness-anywhere"):
        with pytest.raises(SystemExit):
            drv.main(["session", "--src-root", "R", "--work-root", "W", "--config", "s1_x/a", bad, "x"])


def test_E_the_cli_derive_cap_pins_the_reports_archive_harness_first(tmp_path, monkeypatch):
    drv = _drv()
    sroot = tmp_path / "c" / "session-000"
    sroot.mkdir(parents=True)
    (tmp_path / "c" / "report_session-000.json").write_text(json.dumps({"src_root": "ARCH"}), encoding="utf-8")
    order = []
    monkeypatch.setattr(drv, "load_harness", lambda src, *, fresh, **kw: order.append(("load", str(src), fresh, kw)))
    monkeypatch.setattr(drv, "derive_cap", lambda s, c, **kw: order.append(("derive", kw)) or {})
    assert drv.main(["derive-cap", "--session-root", str(sroot), "--config", "s1_x/a"]) == 0
    assert order == [("load", "ARCH", True, {}), ("derive", {})], order


# ------------------------------------------------------------------- the harness comes from the approved archive
class _Isolated:
    """Forget the five harness modules (and sys.path) for one test, then put back exactly what was there - including
    the driver's own module attributes of those names."""

    def __init__(self):
        self.saved = {m: sys.modules.get(m) for m in HARNESS_MODULES}
        self.path = list(sys.path)
        self.drv = {m: getattr(_drv(), m, None) for m in HARNESS_MODULES}

    def __enter__(self):
        for m in HARNESS_MODULES:
            sys.modules.pop(m, None)
        return self

    def __exit__(self, *exc):
        for m, mod in self.saved.items():
            if mod is None:
                sys.modules.pop(m, None)
            else:
                sys.modules[m] = mod
        sys.path[:] = self.path
        for m, mod in self.drv.items():
            setattr(_drv(), m, mod)


def test_H_the_cli_imports_every_harness_module_from_the_archive(tmp_path):
    root, _ = toy(tmp_path)
    drv = _drv()
    arch = (root / "research/s1/s1_tests").resolve()
    with _Isolated():
        h = drv.load_harness(root, fresh=True, _test_allow_git_src_root=True)
        files = {m: sys.modules[m].__file__ for m in HARNESS_MODULES}
        hdir = drv.cr_coord.HARNESS_DIR
    assert h["pinned_to_src_root"] is True and set(h["modules"]) == set(HARNESS_MODULES), h
    assert "pinned_to_archive" not in h, "no claim beyond what was verified"
    from pathlib import Path
    assert {m: Path(f).resolve().parent for m, f in files.items()} == {m: arch for m in HARNESS_MODULES}, files
    assert Path(hdir).resolve() == arch
    assert all(v["sha256"] == sha(arch / f"{m}.py") for m, v in h["modules"].items())


def test_H_the_cli_refuses_when_a_harness_module_is_already_imported(tmp_path):
    root, _ = toy(tmp_path)
    with pytest.raises(_drv().HarnessRefused, match=r"already imported.*only from the --src-root"):
        _drv().load_harness(root, fresh=True, _test_allow_git_src_root=True)


def test_H_the_cli_refuses_an_archive_whose_harness_does_not_verify(tmp_path):
    root, _ = toy(tmp_path)
    g = root / "research/s1/s1_tests/cr_guard.py"
    g.write_text(g.read_text(encoding="utf-8") + "\n# other\n", encoding="utf-8")
    with _Isolated():
        with pytest.raises(_drv().HarnessRefused, match=r"t15c_prep_hashes\.txt does not verify"):
            _drv().load_harness(root, fresh=True, _test_allow_git_src_root=True)
        assert not [m for m in HARNESS_MODULES if m in sys.modules], "nothing imported from a failing archive"


def test_H_the_cli_refuses_a_module_whose_bytes_are_not_the_manifests(tmp_path):
    """The archive's file verifies but the manifest's entry for the harness is another sha: refused."""
    root, _ = toy(tmp_path)
    m = root / MANIFEST_REL
    lines = m.read_text(encoding="utf-8").splitlines()
    m.write_bytes(("\n".join(ln for ln in lines if not ln.endswith("s1_tests/cr_launch.py")) + "\n").encode("utf-8"))
    with _Isolated():
        with pytest.raises(Exception, match=r"harness module cr_launch .* is not the bytes the --src-root's "
                                            r"t15c_prep_hashes\.txt approves") as ei:
            _drv().load_harness(root, fresh=True, _test_allow_git_src_root=True)
    assert type(ei.value).__name__ == "CoordError", "the archive's own CoordError, once it is bound"


def test_H_library_use_imports_a_missing_module_from_the_archive_and_leaves_sys_path_alone(tmp_path):
    root, _ = toy(tmp_path)
    arch = (root / "research/s1/s1_tests").resolve()
    with _Isolated():
        before = list(sys.path)
        h = _drv().load_harness(root, fresh=False, _test_allow_git_src_root=True)
        after = list(sys.path)
    assert h["pinned_to_src_root"] is True and after == before, (after[:3], before[:3])
    assert all(v["src_root"] for v in h["modules"].values()) and str(arch) == h["dir"]


@pytest.mark.parametrize("what", ["harness_files", "evid_rel"])
def test_H_the_harness_must_be_the_one_the_driver_was_written_for(tmp_path, monkeypatch, what):
    root, _ = toy(tmp_path)
    if what == "harness_files":
        monkeypatch.setattr(cr_coord, "HARNESS_FILES", cr_coord.HARNESS_FILES + ("cr_extra.py",))
        pat = r"the harness file set .* is not the driver's"
    else:
        monkeypatch.setattr(cr_preflight, "EVID_REL", "research/s1/s1_evidence/other")
        pat = r"the harness evidence root .* is not research/s1/s1_evidence/cr_a3"
    with pytest.raises(cr_coord.CoordError, match=pat):
        _drv().load_harness(root, fresh=False, _test_harness_anywhere=True, _test_allow_git_src_root=True)


def test_H_library_use_refuses_a_harness_not_imported_from_the_archive(tmp_path):
    root, _ = toy(tmp_path)
    calls = []
    with pytest.raises(cr_coord.CoordError, match=r"imported from .*, not from the --src-root"):
        _drv().session(root, tmp_path / "work", "s1_x/a", _test_exec_factory=factory(calls=calls),
                       _test_allow_git_src_root=True)
    assert calls == [] and not (tmp_path / "work").exists()


# --------------------------------------------------------------------- the driver and its tests are not copied
def test_E_the_driver_and_its_tests_live_outside_every_copy_path():
    drv = _drv()
    from pathlib import Path
    wt = Path(drv.__file__).resolve().parents[3]
    rels = [Path(f).resolve().relative_to(wt).as_posix() for f in (drv.__file__, __file__)]
    for conf in cr_preflight.discover(wt):
        cp = cr_preflight.copy_paths_for(wt, cr_preflight.config_from_toml(conf["dir"] / "cr.toml"))
        for rel in rels:
            assert not cr_coord._in_copy(rel, cp), (rel, conf["rel"])


# ---------------------------------------------------------------------- the REAL path on a toy (no S1 module)
TOY_MODULE = "def f():\n    return 3\n\n\ndef g():\n    return 7\n"
TOY_TESTS = "from s1_x import f\n\n\ndef test_a():\n    assert f() == 3\n\n\ndef test_b():\n    assert True\n"


def test_E_real_path_end_to_end_on_a_toy(tmp_path):
    """Real pre-flights (default runner: the real guard), real_exec (real Cosmic Ray + the real guard) behind the
    policy seam for screening and completion, on a tmp toy whose g() mutants survive (test_b asserts nothing)."""
    stage = tmp_path / "stage"
    s1 = stage / "research" / "s1"
    (s1 / "s1_tests").mkdir(parents=True)
    (s1 / "s1_x.py").write_text(TOY_MODULE, encoding="utf-8")
    cfg = cr_coord.CRConfig(python=PY, module_rel="research/s1/s1_x.py", target_module="s1_x",
                            pythonpath_rel=["research/s1", "research/s1/s1_tests"], guard_args=["x"])
    real_items = cr_coord.inventory(stage, ["research/s1/s1_x.py"], cfg, tmp_path / "inv")
    assert 2 <= len(real_items) <= 8, real_items
    root, items = toy(tmp_path, items=real_items, module_src=TOY_MODULE, test_src=TOY_TESTS, runner="real")
    before = sha(root / "research/s1/s1_x.py")
    work = Path(tempfile.gettempdir()) / "cw" / uuid.uuid4().hex[:8]         # short: the 250-char path budget
    try:
        rep = _run(root, work, "s1_x/a")
    finally:
        keep = {p.relative_to(work).as_posix(): p.read_bytes() for p in work.rglob("policy_result.json")}
        shutil.rmtree(work, ignore_errors=True)
    labels = rep["screening"]["labels"]
    assert rep["stop"] is None, rep["stop"]
    assert set(labels.values()) == {"killed", "survived"}, labels
    surv = [j for j, lab in labels.items() if lab == "survived"]
    assert sorted(rep["completions"]) == sorted(surv)
    assert {c["label"] for c in rep["completions"].values()} == {"survived"}
    assert sha(root / "research/s1/s1_x.py") == before, "the source tree is never mutated"
    assert rep["screening"]["preflight"]["sha256"] == hashlib.sha256(
        (root / EVID_REL / "s1_x/a/preflight/preflight_000.json").read_bytes()).hexdigest()
    for j in labels:                                     # the real results went through the policy seam
        rec = json.loads(keep[f"s1_x__a/session-000/jobs/{j}/policy_result.json"].decode("utf-8"))
        assert rec["halt"] is False and rec["raw"]["label"] == labels[j], rec


# =================================================================== Codex X26: the field-aware policy seam
# cr_coord._stop_reason never stops on a reconciled label "error" / guard "error:*" when exec_status is ok and
# cleanup is verified. The driver's policy seam continues ONLY on a dict whose (label, guard_status) is
# (killed, killed) / (survived, survived) with exec_status exactly "ok", cleanup_verified exactly True and
# raw_timeout exactly False; anything else halts BEFORE the next candidate.
def _without(rec, field):
    return {k: v for k, v in rec.items() if k != field}


# case: (record, policy reason, the batch state's stop reason prefix)
HALTS = {
    "error": (GUARD_ERROR, "label:error/error:collection", "policy_halt:label:error/error:collection"),
    "error_setup": (dict(GUARD_ERROR, guard_status="error:setup"), "label:error/error:setup",
                    "policy_halt:label:error/error:setup"),
    "survived_guard_error": (dict(CLEAN_SURV, guard_status="error:collection"),
                             "label_guard_mismatch:survived/error:collection",
                             "policy_halt:label_guard_mismatch:survived/error:collection"),
    "killed_guard_survived": (dict(CLEAN_KILL, guard_status="survived"), "label_guard_mismatch:killed/survived",
                              "policy_halt:label_guard_mismatch:killed/survived"),
    "untested": (dict(CLEAN_SURV, label="untested", guard_status="untested"), "label:untested/untested",
                 "policy_halt:label:untested/untested"),
    "crash": (dict(CLEAN_SURV, label="crash", guard_status="crash"), "label:crash/crash",
              "policy_halt:label:crash/crash"),
    "not_installed_canonical": (dict(CLEAN_SURV, label="not-installed", guard_status=None), "not-installed",
                                "policy_halt:not-installed"),
    "not_installed_alias": (dict(CLEAN_SURV, label="not_installed", guard_status=None),
                            "unexpected_label:not_installed", "policy_halt:unexpected_label:not_installed"),
    "unknown_label": (dict(CLEAN_SURV, label="weird", guard_status="weird"), "unexpected_label:weird",
                      "policy_halt:unexpected_label:weird"),
    "label_not_a_string": (dict(CLEAN_SURV, label=3), "malformed_field:label", "policy_halt:malformed_field:label"),
    "guard_not_a_string": (dict(CLEAN_SURV, guard_status=7), "malformed_field:guard_status",
                           "policy_halt:malformed_field:guard_status"),
    "missing_label": (_without(CLEAN_SURV, "label"), "missing_field:label", "policy_halt:missing_field:label"),
    "missing_guard_status": (_without(CLEAN_SURV, "guard_status"), "missing_field:guard_status",
                             "policy_halt:missing_field:guard_status"),
    "missing_exec_status": (_without(CLEAN_SURV, "exec_status"), "missing_field:exec_status",
                            "policy_halt:missing_field:exec_status"),
    "missing_cleanup_verified": (_without(CLEAN_SURV, "cleanup_verified"), "missing_field:cleanup_verified",
                                 "cleanup_uncertain"),
    "missing_raw_timeout": (_without(CLEAN_SURV, "raw_timeout"), "missing_field:raw_timeout",
                            "policy_halt:missing_field:raw_timeout"),
    "exec_status_error": (dict(GUARD_ERROR, exec_status="error:cr_exit_1"), "exec_status:error:cr_exit_1",
                          "error:cr_exit_1"),
    "exec_status_not_exactly_ok": (dict(CLEAN_SURV, exec_status="OK"), "exec_status:OK", "OK"),
    "cleanup_verified_not_exactly_true": (dict(CLEAN_SURV, cleanup_verified="true"), "cleanup_verified:'true'",
                                          "policy_halt:cleanup_verified:'true'"),
    "raw_timeout_none": (dict(CLEAN_SURV, raw_timeout=None), "raw_timeout:None", "policy_halt:raw_timeout:None"),
    "raw_timeout_not_exactly_false": (dict(CLEAN_SURV, raw_timeout="false"), "raw_timeout:'false'", "timeout"),
    "timeout": (GUARD_TIMEOUT, "label:timeout/timeout", "timeout"),
    "missing_record": (None, "malformed_result", "cleanup_uncertain"),
    "unparseable": ("not a record", "malformed_result", "cleanup_uncertain"),
}


def _first_state(tmp_path):
    p = tmp_path / "work" / "s1_x__a" / "session-000" / "batch_000_state.json"
    return p, json.loads(p.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", sorted(HALTS))
def test_X26_anything_but_a_clean_kill_or_survival_halts_with_zero_next_call(tmp_path, case, monkeypatch):
    record, reason, stop = HALTS[case]
    root, items = toy(tmp_path)
    raw_p = tmp_path / "work" / "s1_x__a" / "session-000" / "jobs" / "j00" / "policy_result.json"
    dumps, real_dump = [], cr_coord._dump

    def watch(path, st):                     # the raw result is on disk BEFORE the stop is recorded
        if st.get("stopped"):
            dumps.append(raw_p.is_file())
        real_dump(path, st)
    monkeypatch.setattr(cr_coord, "_dump", watch)
    calls = []
    rep = _session(root, tmp_path, _test_exec_factory=factory(screen={"j00": record}, calls=calls))
    assert calls == [("screen", "j00")], "the seam is never called for the next candidate"
    sp, st = _first_state(tmp_path)
    assert st["stopped"] is True and st["stop_reason"] == f"{stop}: j00", st["stop_reason"]
    assert st["pending"] == [i["job_id"] for i in items[1:24]] and st["done"] == []
    assert rep["stop"]["kind"] == _drv()._kind(st["stop_reason"]) and rep["completions"] == {}, rep["stop"]
    assert dumps and all(dumps), "raw result persisted before the halt"
    rec = json.loads(raw_p.read_text(encoding="utf-8"))
    assert rec["halt"] is True and rec["reason"] == reason, rec
    assert rec["raw"] == (record if isinstance(record, dict) else repr(record))
    if isinstance(record, dict):
        assert st["labels"]["j00"] == record.get("label"), "the real label is recorded by run_batch, unchanged"
        assert st["results"]["j00"]["policy"]["reason"] == reason and st["results"]["j00"]["policy"]["halt"] is True
        assert {k: v for k, v in st["results"]["j00"].items() if k not in ("policy", "exec_status")} == \
            {k: v for k, v in record.items() if k != "exec_status"}, "no field but exec_status is touched"
    with pytest.raises(FileExistsError):                  # write-once
        _drv()._write_once(raw_p, {"overwrite": True})
    assert cr_coord.unresolved_stops(sp.parent), "an ordinary unresolved stop"
    with pytest.raises(cr_coord.CoordError, match=r"derive-cap needs a calibration session that ended without"):
        _dcap(sp.parent, "s1_x/a")
    cr_coord.resolve_stop(sp.parent, "000", by="test-controller", note="policy halt reviewed")   # a human's action
    assert cr_coord.unresolved_stops(sp.parent) == []


@pytest.mark.parametrize("record", [CLEAN_KILL, CLEAN_SURV])
def test_X26_only_a_clean_kill_or_survival_continues(tmp_path, record):
    root, items = toy(tmp_path, completion=False)
    calls = []
    rep = _session(root, tmp_path, _test_exec_factory=factory(screen={i["job_id"]: record for i in items},
                                                              calls=calls))
    sp, st = _first_state(tmp_path)
    assert rep["stop"] is None and len(calls) == 24 and st["done"] == [i["job_id"] for i in items[:24]]
    assert all(r["policy"] == {"halt": False, "reason": None, "original_exec_status": "ok"} and r["exec_status"] == "ok"
               for r in st["results"].values())


def test_X26_the_policy_check_is_field_aware(tmp_path):
    root, _ = toy(tmp_path)
    drv = _drv()
    drv.load_harness(root, fresh=False, _test_harness_anywhere=True, _test_allow_git_src_root=True)
    assert drv.policy_check(dict(CLEAN_KILL)) is None and drv.policy_check(dict(CLEAN_SURV)) is None
    for case, (record, reason, _) in HALTS.items():
        assert drv.policy_check(record) == reason, case


def test_X26_a_completion_result_that_is_not_kill_or_survival_halts_its_shard(tmp_path):
    root, _ = toy(tmp_path)
    calls = []
    setup_error = dict(GUARD_ERROR, guard_status="error:setup")
    rep = _session(root, tmp_path, _test_exec_factory=factory(
        screen={"j03": CLEAN_SURV, "j07": CLEAN_SURV}, comp={("c1", "j03"): setup_error}, calls=calls))
    assert [c for c in calls if c[0] != "screen"] == [("c1", "j03")], "c2 / j07 never start"
    assert rep["stop"]["kind"] == "policy_halt", rep["stop"]
    rec = json.loads(next((tmp_path / "work/s1_x__a/session-000/completion/j03").rglob("policy_result.json"))
                     .read_text(encoding="utf-8"))
    assert rec["reason"] == "label:error/error:setup"


def test_X26_the_policy_seam_keeps_the_real_command_tag_and_says_what_it_is(tmp_path):
    drv = _drv()
    c = cr_coord.CRConfig(python=PY, module_rel="pkg/m.py", target_module="pkg.m", guard_args=["--control", "c.json"])
    inner = cr_coord.real_exec(c)
    seam = drv.policy_seam(inner)
    assert seam.test_command_sha256 == inner.test_command_sha256 and seam.cr_real_exec is True
    assert seam.synthetic is False and seam.cr_policy_wrapper is True and seam.inner is inner


# --- protocol C1 / C7: one config at a time, in discover order; a stop needs review before the next config -------
def test_C1_C7_configs_run_in_discover_order_and_a_stop_blocks_the_next_config(tmp_path):
    root, _ = toy(tmp_path, screens=("a", "b"))
    with pytest.raises(cr_coord.CoordError, match=r"earlier config s1_x/a has no clean calibration report"):
        _run(root, tmp_path / "work", "s1_x/b", _test_exec_factory=factory())
    _run(root, tmp_path / "work", "s1_x/a",
         _test_exec_factory=factory(screen={"j03": CLEAN_SURV}, comp={("c1", "j03"): UNCERTAIN_SURV}))
    with pytest.raises(cr_coord.CoordError, match=r"earlier config s1_x/a has no clean calibration report"):
        _run(root, tmp_path / "work", "s1_x/b", _test_exec_factory=factory())
    rep = _run(root, tmp_path / "work", "s1_x/b", review_ref="review-1", _test_exec_factory=factory())
    assert rep["order"] == {"earlier": {"s1_x/a": "missing or stopped"}, "review_ref": "review-1"}


def test_C1_the_next_config_runs_once_the_earlier_one_is_clean(tmp_path):
    root, _ = toy(tmp_path, screens=("a", "b"))
    assert _run(root, tmp_path / "work", "s1_x/a", _test_exec_factory=factory())["stop"] is None
    assert _run(root, tmp_path / "work", "s1_x/b", _test_exec_factory=factory())["stop"] is None


# --- protocol C6: the source tree is re-verified after the session --------------------------------------------
def test_C6_a_manifest_change_during_the_session_is_reported_as_a_stop(tmp_path):
    root, items = toy(tmp_path)
    pool = root / EVID_REL / "s1_x/completion/pool.json"

    def tamper(kind, job):
        if (kind, job) == ("screen", items[23]["job_id"]):
            pool.write_text(pool.read_text(encoding="utf-8") + " ", encoding="utf-8")
    rep = _session(root, tmp_path, _test_exec_factory=factory(on_call=tamper))
    assert (rep.get("manifest_after") or {}).get("verified") is False, rep.get("manifest_after")
    assert rep["stop"]["kind"] == "manifest_changed", rep["stop"]


# --- protocol C7: the cap is derived only from a clean, complete calibration session --------------------------
def test_C7_derive_cap_refuses_a_session_that_stopped(tmp_path):
    root, _ = toy(tmp_path)
    _session(root, tmp_path, _test_exec_factory=factory(screen={"j05": UNCERTAIN_SURV}))
    with pytest.raises(cr_coord.CoordError, match=r"derive-cap needs a calibration session that ended without a stop"):
        _dcap(tmp_path / "work" / "s1_x__a" / "session-000", "s1_x/a")
    assert not (tmp_path / "work" / "s1_x__a" / "derived_cap.json").exists()


def test_C_the_report_lists_the_protocol_checks_and_the_harness_import(tmp_path):
    root, _ = toy(tmp_path)
    rep = _session(root, tmp_path, _test_exec_factory=factory())
    assert {"C1", "C2", "C3", "C4", "C5", "C6", "C7"} <= set(rep.get("protocol", {})), rep.get("protocol")
    assert rep["policy"]["halts_on"] and "killed" in rep["policy"]["continues_on"] and rep["policy"]["no_retry"]
    assert set(rep["harness"]["modules"]) == set(HARNESS_MODULES)
    assert rep["harness"]["pinned_to_src_root"] is False, "library test use: worktree modules, byte-identical"
    assert rep["src_root_verified"] == {
        "realpath": str(root.resolve()), "manifest_sha256": sha(root / MANIFEST_REL),
        "is_git_checkout": _drv().git_checkout_of(root) is not None,
        "git_marker": (str(_drv().git_checkout_of(root)) if _drv().git_checkout_of(root) else None)}


# ===================================================================================== 15c-E fix round 1 (review)
# --- m6: derive-cap refuses when the session report recorded a stop, or a later-stage stop is unresolved --------
def _completion_halted(tmp_path):
    root, _ = toy(tmp_path)
    rep = _session(root, tmp_path, _test_exec_factory=factory(
        screen={"j03": CLEAN_SURV}, comp={("c1", "j03"): dict(CLEAN_SURV, label="error", guard_status="error:setup")}))
    sroot = tmp_path / "work/s1_x__a/session-000"
    st = json.loads((sroot / "batch_000_state.json").read_text(encoding="utf-8"))
    assert not st["stopped"] and not st["pending"] and st["done"] == st["batch"], "screening itself is clean"
    assert rep["stop"]["kind"] == "policy_halt", rep["stop"]
    return root, sroot


def test_m6_derive_cap_refuses_after_a_completion_only_stop(tmp_path):
    """Reviewer probe R12: screening clean, a survivor's completion halted (report stop + unresolved stop)."""
    _, sroot = _completion_halted(tmp_path)
    with pytest.raises(cr_coord.CoordError, match=r"derive-cap needs a calibration session that ended without a stop"):
        _dcap(sroot, "s1_x/a")
    assert not (sroot.parent / "derived_cap.json").exists()


def test_m6_derive_cap_refuses_a_recorded_stop_even_after_a_human_resolved_it(tmp_path):
    _, sroot = _completion_halted(tmp_path)
    for u in cr_coord.unresolved_stops(sroot):
        cr_coord.resolve_stop(u["_root"], u["batch_id"], by="test-controller", note="reviewed")
    assert cr_coord.unresolved_stops(sroot) == []
    with pytest.raises(cr_coord.CoordError, match=r"derive-cap needs a calibration session that ended without a stop"):
        _dcap(sroot, "s1_x/a")


def test_m6_derive_cap_refuses_an_unresolved_later_stage_stop_the_report_does_not_show(tmp_path, monkeypatch):
    root, _ = toy(tmp_path)
    rep = _session(root, tmp_path, _test_exec_factory=factory())
    assert rep["stop"] is None
    sroot = tmp_path / "work/s1_x__a/session-000"
    monkeypatch.setattr(cr_coord, "unresolved_stops", lambda w: [{"batch_id": "c1", "_root": str(w)}])
    with pytest.raises(cr_coord.CoordError, match=r"derive-cap needs a calibration session that ended without a stop"):
        _dcap(sroot, "s1_x/a")


# --- m1: a --src-root inside a git checkout / worktree is refused; the report says exactly what was verified -----
@pytest.mark.parametrize("where", ["dir_at_root", "file_at_root", "in_a_parent"])
def test_m1_a_src_root_inside_a_git_checkout_is_refused(tmp_path, where):
    root, _ = toy(tmp_path)
    if where == "dir_at_root":
        (root / ".git").mkdir()
        marker = root
    elif where == "file_at_root":                    # a git worktree: .git is a file
        (root / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
        marker = root
    else:
        (tmp_path / ".git").mkdir()
        marker = tmp_path
    drv = _drv()
    assert drv.git_checkout_of(root) == marker.resolve()
    calls = []
    with pytest.raises(cr_coord.CoordError, match=r"is inside a git checkout or worktree"):
        drv.session(root, tmp_path / "work", "s1_x/a", _test_exec_factory=factory(calls=calls),
                    _test_harness_anywhere=True)
    assert calls == [] and not (tmp_path / "work").exists()
    with _Isolated():                                # the CLI path: refused before any harness import
        with pytest.raises(drv.HarnessRefused, match=r"is inside a git checkout or worktree"):
            drv.main(["session", "--src-root", str(root), "--work-root", str(tmp_path / "w2"), "--config", "s1_x/a"])
        assert not [m for m in HARNESS_MODULES if m in sys.modules]
    assert not (tmp_path / "w2").exists()


def test_m1_the_git_probe_walks_up_to_the_drive_root(tmp_path):
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    (tmp_path / "a" / ".git").write_text("gitdir: x\n", encoding="utf-8")
    assert _drv().git_checkout_of(deep) == (tmp_path / "a").resolve()
    assert _drv().git_checkout_of(deep) == _drv().git_checkout_of(deep / "missing-child-is-fine")


# --- m2: the raw result is persisted even when the policy, or the encoding, fails; never a 0-byte record --------
def test_m2_an_unserialisable_result_halts_and_its_raw_result_is_persisted(tmp_path):
    root, items = toy(tmp_path)
    rec = dict(CLEAN_KILL, raw={("tuple", "key"): 1})
    calls = []
    _session(root, tmp_path, _test_exec_factory=factory(screen={"j00": rec}, calls=calls))
    sp, st = _first_state(tmp_path)
    raw_p = sp.parent / "jobs/j00/policy_result.json"
    assert calls == [("screen", "j00")] and st["stop_reason"] == "policy_halt:unserialisable_result: j00", st
    assert st["labels"]["j00"] == "killed", "the real label is still recorded"
    body = json.loads(raw_p.read_text(encoding="utf-8"))
    assert body["halt"] is True and body["reason"] == "unserialisable_result" and "tuple" in json.dumps(body)


def test_m2_a_policy_error_still_persists_the_raw_result_and_halts(tmp_path, monkeypatch):
    root, items = toy(tmp_path)
    drv = _drv()

    def bad(result):
        raise ValueError("policy bug")
    monkeypatch.setattr(drv, "policy_check", bad)
    calls = []
    rep = _session(root, tmp_path, _test_exec_factory=factory(screen={"j00": CLEAN_KILL}, calls=calls))
    sp, st = _first_state(tmp_path)
    body = json.loads((sp.parent / "jobs/j00/policy_result.json").read_text(encoding="utf-8"))
    assert calls == [("screen", "j00")] and st["stopped"] is True and rep["stop"]["kind"] == "error", rep["stop"]
    assert body["raw"] == CLEAN_KILL and body["halt"] is True and body["reason"] == "policy_error", body
    assert body["policy_error"] == "ValueError: policy bug", body


def test_m2_the_write_once_record_is_never_empty_even_if_encoding_fails(tmp_path, monkeypatch):
    drv = _drv()

    class Odd:
        def __repr__(self):
            return "<odd thing>"
    p1 = tmp_path / "a" / "policy_result.json"
    drv._write_once(p1, {("k",): Odd()})                         # json cannot encode a tuple key
    assert p1.stat().st_size > 0 and "<odd thing>" in p1.read_text(encoding="utf-8")

    def boom(*a, **k):
        raise TypeError("no json today")
    monkeypatch.setattr(drv.json, "dumps", boom)
    p2 = tmp_path / "b" / "policy_result.json"
    drv._write_once(p2, {"raw": Odd()})
    assert p2.stat().st_size > 0 and "<odd thing>" in p2.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        drv._write_once(p2, {"again": 1})


# --- m3: a BaseException (KeyboardInterrupt / SystemExit) still writes the session report, then re-raises --------
@pytest.mark.parametrize("exc", [KeyboardInterrupt, SystemExit])
def test_m3_an_interrupt_writes_an_interrupted_report_then_re_raises(tmp_path, exc):
    root, items = toy(tmp_path)
    calls = []
    with pytest.raises(exc):
        _session(root, tmp_path, _test_exec_factory=factory(screen={"j01": exc()}, calls=calls))
    croot = tmp_path / "work/s1_x__a"
    rep = json.loads((croot / "report_session-000.json").read_text(encoding="utf-8"))
    assert calls == [("screen", "j00"), ("screen", "j01")]
    assert rep["stop"]["kind"] == "interrupted" and exc.__name__ in rep["stop"]["detail"], rep["stop"]
    assert rep["screening"]["pending"][:1] == ["j01"] and rep["finished_at"], rep["screening"]
    assert cr_coord.unresolved_stops(croot / "session-000"), "the interrupted batch stays unresolved"
    with pytest.raises(cr_coord.CoordError, match=r"already exists"):
        _session(root, tmp_path, _test_exec_factory=factory())


# --- m5: the budget is the deepest COPIED FILE (copy-path entry + job / session nesting), limit 250 ---------------
def _deepest_expected(root, work, job_len):
    """Independent recomputation: the longest copied rel of the screening config and of each completion shard, under
    copies/<job> and quarantine/<job>.<n> (the deeper of the two), below <work>/s1_x__a/session-000."""
    j = "x" * job_len
    s0 = Path(work).resolve() / "s1_x__a" / "session-000"
    worst = 0
    for conf in cr_preflight.discover(root, modules=["s1_x"]):
        cfg = cr_preflight.config_from_toml(conf["dir"] / "cr.toml")
        longest = max(len(r) for r in cr_coord.copied_map(root, cr_preflight.copy_paths_for(root, cfg)))
        base = s0 if conf["kind"] == "screening" else s0 / "completion" / j / conf["dir"].name
        worst = max(worst, len(str(base / "quarantine" / f"{j}.99")) + 1 + longest)
    return worst


@pytest.mark.parametrize("completion", [True, False])      # False: screening only - its quarantine depth decides
def test_m5_the_report_records_the_deepest_copied_file_and_the_longest_work_root(tmp_path, completion):
    root, _ = toy(tmp_path, completion=completion)
    rep = _session(root, tmp_path, _test_exec_factory=factory())
    want = _deepest_expected(root, tmp_path / "work", 3)
    pb = rep["path_budget"]
    assert pb["limit"] == 250 and pb["deepest_copied_file_chars"] == want, (pb, want)
    assert "copied tree only" in pb["measures"] and "LongPathsEnabled" in pb["measures"], pb
    assert "deepest_path_chars" not in pb, "no claim beyond the copied tree"
    assert pb["max_work_root_chars"] == 250 - (want - len(str((tmp_path / "work").resolve()))), pb


def test_m5_a_copied_file_past_the_limit_is_refused_before_anything(tmp_path):
    """The child cwd would fit the old 240-character rule; the deepest COPIED FILE does not fit 250."""
    root, _ = toy(tmp_path)
    (root / "research/s1/docs" / ("d" * 100 + ".md")).write_text("long\n", encoding="utf-8")
    calls = []
    with pytest.raises(cr_coord.CoordError,
                       match=r"the work root is too long: .* \(> 250\); use a --work-root of at most \d+ characters"):
        _session(root, tmp_path, _test_exec_factory=factory(calls=calls))
    assert calls == [] and not (tmp_path / "work").exists()


# ===================================================================================== 15c-E fix round 2 (re-review)
# --- r1-m1: job-dir files go deeper than the copied tree; the host must have LongPathsEnabled = 1 (read-only) ----
@pytest.mark.parametrize("value", [0, None, 2, "1", True, "raises"])
def test_r1m1_a_host_without_long_paths_is_refused_before_anything(tmp_path, value):
    root, _ = toy(tmp_path)

    def reader():
        if value == "raises":
            raise PermissionError("registry access denied")
        return value
    calls = []
    with pytest.raises(cr_coord.CoordError, match=r"LongPathsEnabled .* not 1: refused"):
        _session(root, tmp_path, _test_long_paths_reader=reader, _test_exec_factory=factory(calls=calls))
    assert calls == [] and not (tmp_path / "work").exists()


def test_r1m1_the_report_records_the_host_long_paths_value(tmp_path):
    root, _ = toy(tmp_path)
    rep = _session(root, tmp_path, _test_exec_factory=factory())
    assert rep["host"] == {"long_paths_enabled": 1,
                           "registry": r"HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled"}, \
        rep["host"]


class _FakeWinreg:
    """Records every call; has NO write API, so any write attempt is an AttributeError."""
    HKEY_LOCAL_MACHINE, KEY_READ = "HKLM", 0x20019

    def __init__(self, value=1, missing=False):
        self.calls, self.value, self.missing = [], value, missing

    def OpenKey(self, root, sub, reserved=0, access=None):
        self.calls.append(("OpenKey", root, sub, reserved, access))
        fake = self

        class _Key:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                fake.calls.append(("close",))
                return False
        return _Key()

    def QueryValueEx(self, key, name):
        self.calls.append(("QueryValueEx", name))
        if self.missing:
            raise FileNotFoundError(name)
        return self.value, 4


def test_r1m1_the_registry_reader_opens_the_key_read_only_and_never_writes():
    real = REAL_READER["fn"]
    assert real is not None, "the driver has a real LongPathsEnabled reader"
    w = _FakeWinreg(value=1)
    assert real(_winreg=w) == 1
    assert w.calls == [("OpenKey", "HKLM", r"SYSTEM\CurrentControlSet\Control\FileSystem", 0, w.KEY_READ),
                       ("QueryValueEx", "LongPathsEnabled"), ("close",)], w.calls
    assert real(_winreg=_FakeWinreg(missing=True)) is None, "an absent value reads as None (refused upstream)"
    tree = ast.parse(Path(_drv().__file__).read_text(encoding="utf-8"))
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | \
        {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    write_api = {"SetValue", "SetValueEx", "CreateKey", "CreateKeyEx", "DeleteKey", "DeleteKeyEx", "DeleteValue",
                 "KEY_WRITE", "KEY_ALL_ACCESS", "KEY_SET_VALUE", "KEY_CREATE_SUB_KEY", "SaveKey", "LoadKey"}
    assert not names & write_api, names & write_api


# --- r1-n1: a failing interrupted-report write never masks the interrupt ----------------------------------------
def test_r1n1_a_failing_report_write_keeps_the_original_interrupt(tmp_path, monkeypatch):
    root, _ = toy(tmp_path)
    drv = _drv()

    def broken_finish(*a, **k):
        raise FileExistsError("report_session-000.json")
    monkeypatch.setattr(drv, "_finish", broken_finish)
    with pytest.raises(KeyboardInterrupt) as ei:
        _session(root, tmp_path, _test_exec_factory=factory(screen={"j01": KeyboardInterrupt()}))
    notes = getattr(ei.value, "__notes__", [])
    assert any("interrupted-report write failed: FileExistsError" in n for n in notes), notes
