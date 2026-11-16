"""A3 Task 15c-P: the pre-flight driver (t15c_prep.md runbook step 3a) and the gates that consume its records.

SYNTHETIC only: every guard run here goes through an injected ``runner`` seam that writes a guard.json shaped like
cr_guard's sidecar; no real guard, Cosmic Ray process or S1 config is run, and no S1 module is mutated.

Contract under test:
* run_preflight runs ONE unmutated guard baseline for one config: a fresh copy of ``copy_paths``, the exact cr.toml
  test command (``--control`` the frozen control file), the production ``cr_coord._env(copy, cfg, job_dir, job_id)``
  env, the CR timeout as the outer deadline. Before running it refuses a control whose sha256 is not the frozen
  value, a module source other than the inventory pin, and a cr.toml that does not render the config. It never
  writes control.json.
* It writes a WRITE-ONCE record <record_dir>/preflight_<k>.json (k = next free attempt) holding the binding (incl.
  the prefixed child env only), the guard sidecar hash + summary, control / source / harness hashes, the wall time
  and the verdict: ``clean`` iff guard survived, node set == control, no node-set mismatch, cleanup verified, source
  unchanged and wall time within the selector budget; otherwise ``not_clean`` with reasons.
* cr_coord.check_preflight is the gate: a clean record bound to the CURRENT binding is required, and any not_clean
  record for that binding blocks the config. run_manifest, a calibration run_batch(config=...) and run_completion
  (per shard) refuse without it.
"""
import inspect
import json
import shlex
import shutil

import pytest

import cr_coord
from test_s1_a3_cr_completion import CLEAN_SURV, GUARD_TIMEOUT, _cfg, _complete, _screened, _seam, _shards
from test_s1_a3_cr_guard import PY, _three, sha

B = cr_coord.BUDGETS
NODES = ["t.py::test_a", "t.py::test_b"]


def _driver():
    try:
        import cr_preflight
    except ImportError:
        cr_preflight = None
    assert cr_preflight is not None, "the pre-flight driver module cr_preflight exists"
    return cr_preflight


def _gate():
    assert hasattr(cr_coord, "check_preflight") and hasattr(cr_coord, "preflight_binding"), "cr_coord has the gate"
    return cr_coord


# ------------------------------------------------------------------------------------------------ synthetic seams
def guard_runner(status="survived", *, nodes=None, rc=0, exit_code=0, timed_out=False, cleanup=True,
                 guard_cleanup=True, node_set=None, counts=None, wall_s=5.0, write_guard=True, edit=None,
                 raise_exc=None, calls=None, now=None, control_sha=None, outer_rc=None):
    """A runner seam shaped like cr_guard.run_contained running the guard: it writes <job_dir>/guard.json (fields as
    cr_guard.main writes them) and returns the outer run record. ``edit(copy_root)`` mutates the copy mid-run."""
    def run(cmd, *, cwd, env, job_dir, deadline_s):
        if calls is not None:
            calls.append({"cmd": list(cmd), "cwd": str(cwd), "env": dict(env), "job_dir": str(job_dir),
                          "deadline_s": deadline_s})
        if now is not None:
            now[0] += wall_s
        if raise_exc is not None:
            raise raise_exc
        if edit is not None:
            edit(cwd)
        ctl_rel = cmd[cmd.index("--control") + 1]
        ctl = json.loads((cwd / ctl_rel).read_text(encoding="utf-8"))["nodes"]
        sel = list(ctl if nodes is None else nodes)
        c = counts or {"tests": len(sel), "failures": 0, "errors": 0, "skipped": 0, "passed": len(sel)}
        if write_guard:
            (job_dir / "guard.json").write_text(json.dumps({
                "schema": "a3-t15a-guard/1", "status": status, "exit_code": exit_code, "rc": rc, "counts": c,
                "nodes": sel, "node_set": node_set, "control_sha256": control_sha or sha(cwd / ctl_rel),
                "elapsed_s": wall_s, "cleanup": {"verified": guard_cleanup}, "argv": cmd[3:]}), encoding="utf-8")
        return {"rc": exit_code if outer_rc is None else outer_rc, "timed_out": timed_out,
                "cleanup": {"verified": cleanup}, "elapsed_s": wall_s}
    return run


def _proj(tmp_path, extra_copy=()):
    """A synthetic config: pkg/m.py, ev/c/{control.json, collect_only.json, nodes.txt, cr.toml, inventory.json}."""
    src, _ = _three(tmp_path)
    ev = src / "ev" / "c"
    ev.mkdir(parents=True)
    (ev / "control.json").write_text(json.dumps({"nodes": sorted(NODES)}), encoding="utf-8")
    (ev / "nodes.txt").write_text("".join(n + "\n" for n in NODES), encoding="utf-8")
    (ev / "collect_only.json").write_text(json.dumps({"control_sha256": sha(ev / "control.json")}), encoding="utf-8")
    cfg = cr_coord.CRConfig(python=PY, module_rel="pkg/m.py", target_module="pkg.m",
                            guard_args=["--control", "ev/c/control.json", "-p", "conftest", "@ev/c/nodes.txt"])
    cr_coord.write_cr_toml(ev / "cr.toml", cfg)
    (ev / "inventory.json").write_text(json.dumps({"module_rel": "pkg/m.py",
                                                   "source_sha256": sha(src / "pkg" / "m.py")}), encoding="utf-8")
    copy_paths = ["pkg", "ev/c/control.json", "ev/c/nodes.txt", *extra_copy]
    return src, ev, cfg, copy_paths


def _pf(src, ev, cfg, copy_paths, runner, tmp_path, **kw):
    drv = _driver()
    kw.setdefault("clock", lambda: 0.0)
    return drv.run_preflight(cfg, src_root=src, copy_paths=copy_paths, record_dir=ev / "preflight",
                             cr_toml=ev / "cr.toml",
                             expected_control_sha256=json.loads((ev / "collect_only.json").read_text(
                                 encoding="utf-8"))["control_sha256"],
                             source_sha256=json.loads((ev / "inventory.json").read_text(
                                 encoding="utf-8"))["source_sha256"],
                             work_root=tmp_path / "pfwork", runner=runner, **kw)


def clean_preflight(src, spec, record_root):
    """Test helper (also used by test_s1_a3_cr_completion._complete): a CLEAN pre-flight for a completion shard spec
    under the current context, through the real driver with a synthetic clean guard runner."""
    drv = _driver()
    cfg = spec["cfg"]
    args = [str(a) for a in cfg.guard_args]
    ctl = src / args[args.index("--control") + 1]
    k = len(list(record_root.glob(f"{spec['name']}_*")))
    ev = record_root / f"{spec['name']}_{k}"
    ev.mkdir(parents=True)
    cr_coord.write_cr_toml(ev / "cr.toml", cfg)
    rec = drv.run_preflight(cfg, src_root=src, copy_paths=spec["copy_paths"], record_dir=ev / "preflight",
                            cr_toml=ev / "cr.toml", expected_control_sha256=sha(ctl),
                            source_sha256=sha(src / cfg.module_rel), work_root=ev / "work",
                            runner=guard_runner(), clock=lambda: 0.0)
    assert rec["verdict"] == "clean", rec
    spec["preflight_dir"] = ev / "preflight"
    return rec


# ----------------------------------------------------------------------------------------------- driver: running
def test_P_clean_preflight_runs_the_exact_command_in_a_fresh_copy_and_writes_a_write_once_record(tmp_path):
    src, ev, cfg, cp = _proj(tmp_path)
    calls, now = [], [100.0]
    rec = _pf(src, ev, cfg, cp, guard_runner(calls=calls, now=now, wall_s=12.5), tmp_path, clock=lambda: now[0])
    assert rec.get("verdict") == "clean" and rec.get("reasons") == [], rec
    ((call),) = calls
    assert call["cmd"] == shlex.split(cr_coord.test_command(cfg)), "the exact cr.toml test command"
    assert "--control" in call["cmd"] and call["cmd"][call["cmd"].index("--control") + 1] == "ev/c/control.json"
    assert call["deadline_s"] == cfg.timeout_s, "the CR timeout is the outer deadline"
    copy = call["cwd"]
    assert copy != str(src) and not copy.startswith(str(src)), "a fresh copy outside the source tree"
    assert call["env"] == cr_coord._env(cr_coord.Path(copy), cfg, cr_coord.Path(call["job_dir"]),
                                        call["env"][cr_coord.cr_guard.JOB_ID_ENV]), "the production _env"
    path = ev / "preflight" / "preflight_000.json"
    assert path.is_file() and json.loads(path.read_text(encoding="utf-8")) == rec
    assert rec["binding"] == cr_coord.preflight_binding(cfg, src, cp), "bound to the current context"
    assert rec["binding"]["control_sha256"] == sha(ev / "control.json")
    assert rec["binding"]["source_sha256"] == sha(src / "pkg" / "m.py")
    assert rec["binding"]["harness_sha256"] == cr_coord.harness_hashes()
    assert rec["guard"]["sha256"] and rec["guard"]["status"] == "survived" and rec["wall_s"] == 12.5
    before = path.read_bytes()
    rec2 = _pf(src, ev, cfg, cp, guard_runner(), tmp_path)
    assert (ev / "preflight" / "preflight_001.json").is_file() and rec2["attempt"] == 1
    assert path.read_bytes() == before, "an earlier record is never rewritten"


def test_P_control_json_is_never_written_and_its_bytes_are_unchanged(tmp_path):
    src, ev, cfg, cp = _proj(tmp_path)
    before = (ev / "control.json").read_bytes()
    rec = _pf(src, ev, cfg, cp, guard_runner(), tmp_path)
    assert rec["verdict"] == "clean" and (ev / "control.json").read_bytes() == before
    rewrite = guard_runner(edit=lambda c: (c / "ev/c/control.json").write_text('{"nodes": []}', encoding="utf-8"))
    rec2 = _pf(src, ev, cfg, cp, rewrite, tmp_path)
    assert rec2["verdict"] == "not_clean" and "control_changed" in rec2["reasons"], rec2
    assert (ev / "control.json").read_bytes() == before


def test_P_tampered_control_is_refused_before_anything_runs(tmp_path):
    src, ev, cfg, cp = _proj(tmp_path)
    (ev / "control.json").write_text(json.dumps({"nodes": NODES[:1]}), encoding="utf-8")
    calls = []
    with pytest.raises(cr_coord.CoordError, match=r"control .* sha256 .* is not the frozen value"):
        _pf(src, ev, cfg, cp, guard_runner(calls=calls), tmp_path)
    assert calls == [] and not (ev / "preflight").exists()


def test_P_source_other_than_the_inventory_pin_is_refused(tmp_path):
    src, ev, cfg, cp = _proj(tmp_path)
    (src / "pkg" / "m.py").write_text("X = 9\n", encoding="utf-8")
    calls = []
    with pytest.raises(cr_coord.CoordError, match=r"source .* sha256 .* is not the inventory source_sha256"):
        _pf(src, ev, cfg, cp, guard_runner(calls=calls), tmp_path)
    assert calls == [] and not (ev / "preflight").exists()


def test_P_a_cr_toml_that_does_not_render_the_config_is_refused(tmp_path):
    src, ev, cfg, cp = _proj(tmp_path)
    cfg.guard_args = cfg.guard_args + ["-k", "only_some"]
    calls = []
    with pytest.raises(cr_coord.CoordError, match=r"cr\.toml does not match the config"):
        _pf(src, ev, cfg, cp, guard_runner(calls=calls), tmp_path)
    assert calls == [] and not (ev / "preflight").exists()


_NOT_CLEAN = {
    "killed": (dict(status="killed", exit_code=1), "guard_status:killed"),
    "error": (dict(status="error:collection"), "guard_status:error:collection"),
    "nodes_differ": (dict(nodes=NODES[:1]), "node_set_differs_from_control"),
    "node_set_mismatch": (dict(node_set={"missing": NODES[1:], "extra": []}), "node_set_mismatch"),
    "outer_cleanup": (dict(cleanup=False), "cleanup_unverified"),
    "guard_cleanup": (dict(guard_cleanup=False), "cleanup_unverified"),
    "source_changed": (dict(edit=lambda c: (c / "pkg/m.py").write_text("X = 2\n", encoding="utf-8")),
                       "source_changed"),
    "over_budget": (dict(wall_s=B["selector_baseline_target_s"] + 1.0), "over_budget"),
    "outer_timeout": (dict(timed_out=True), "outer_timeout"),
    "no_guard": (dict(write_guard=False), "no_guard_sidecar"),
    "rc": (dict(exit_code=3), "nonzero_exit"),
    "skipped": (dict(counts={"tests": 2, "failures": 0, "errors": 0, "skipped": 1, "passed": 1}), "counts"),
    "runner_exception": (dict(raise_exc=OSError("boom")), "runner_exception:OSError"),
    "guard_control_sha": (dict(control_sha="0" * 64), "guard_control_sha_differs"),
    "outer_rc_only": (dict(outer_rc=1), "nonzero_exit"),
    "guard_exit_only": (dict(exit_code=3, outer_rc=0), "nonzero_exit"),
}


@pytest.mark.parametrize("case", sorted(_NOT_CLEAN))
def test_P_every_not_clean_branch_is_recorded_with_its_reason(tmp_path, case):
    src, ev, cfg, cp = _proj(tmp_path)
    kw, reason = _NOT_CLEAN[case]
    now = [0.0]
    rec = _pf(src, ev, cfg, cp, guard_runner(now=now, **kw), tmp_path, clock=lambda: now[0])
    assert rec.get("verdict") == "not_clean" and reason in rec.get("reasons", []), rec
    on_disk = json.loads((ev / "preflight" / "preflight_000.json").read_text(encoding="utf-8"))
    assert on_disk == rec, "a failed pre-flight is kept as a failure"


def test_P_wall_time_exactly_at_the_budget_is_clean(tmp_path):
    src, ev, cfg, cp = _proj(tmp_path)
    now = [0.0]
    rec = _pf(src, ev, cfg, cp, guard_runner(now=now, wall_s=float(B["selector_baseline_target_s"])), tmp_path,
              clock=lambda: now[0])
    assert rec["verdict"] == "clean", rec


def test_P_record_holds_only_the_bound_prefixed_env_never_other_variables(tmp_path, monkeypatch):
    monkeypatch.setenv("S1_PF_SECRET_TOKEN", "pf-secret-value-8812")
    monkeypatch.setenv("PYTHONOPTIMIZE", "1")
    monkeypatch.setenv("PYTHONHASHSEED", "11")
    src, ev, cfg, cp = _proj(tmp_path)
    rec = _pf(src, ev, cfg, cp, guard_runner(), tmp_path)
    text = (ev / "preflight" / "preflight_000.json").read_text(encoding="utf-8")
    for needle in ("S1_PF_SECRET_TOKEN", "pf-secret-value-8812", "PYTHONOPTIMIZE"):
        assert needle not in text, f"{needle} leaked into the pre-flight record"
    env = rec["binding"]["env"]
    assert set(env) == {k for k in env if k.upper().startswith(("PYTHON", "PYTEST", "HYPOTHESIS", "COV"))} | (
        {"TZ"} if "TZ" in env else set()), env
    assert env.get("PYTHONHASHSEED") == "11" and env.get("PYTHONDONTWRITEBYTECODE") == "1"
    assert "environ" not in text and "PATH\"" not in text.replace("PYTHONPATH\"", "")


def test_P_a_copy_that_differs_from_the_pins_is_refused(tmp_path, monkeypatch):
    src, ev, cfg, cp = _proj(tmp_path)
    real = cr_coord.make_copy

    def diverging(src_root, copy_paths, dest):
        out = real(src_root, copy_paths, dest)
        (dest / "pkg" / "m.py").write_text("X = 5\n", encoding="utf-8")
        return dict(out, **{"pkg/m.py": sha(dest / "pkg" / "m.py")})
    monkeypatch.setattr(cr_coord, "make_copy", diverging)
    calls = []
    rec = _try_pf(src, ev, cfg, cp, guard_runner(calls=calls), tmp_path)      # fix 1: recorded, not raised
    assert rec.get("verdict") == "not_clean" and "copy_differs_from_pins" in rec.get("reasons", []), rec
    assert calls == [] and (ev / "preflight" / "preflight_000.json").is_file()


def test_P_a_harness_file_in_the_copy_that_is_not_the_reviewed_one_is_refused(tmp_path):
    src, ev, cfg, cp = _proj(tmp_path)
    (src / "pkg" / "cr_guard.py").write_text("# not the reviewed guard\n", encoding="utf-8")
    calls = []
    rec = _try_pf(src, ev, cfg, cp, guard_runner(calls=calls), tmp_path)      # fix 1: recorded, not raised
    assert rec.get("verdict") == "not_clean" and "copy_harness_drift:cr_guard.py" in rec.get("reasons", []), rec
    assert calls == [] and (ev / "preflight" / "preflight_000.json").is_file()


def test_P_the_next_attempt_counts_existing_records_even_under_a_new_work_root(tmp_path):
    src, ev, cfg, cp = _proj(tmp_path)
    _pf(src, ev, cfg, cp, guard_runner(), tmp_path)
    rec = _pf(src, ev, cfg, cp, guard_runner(), tmp_path / "other")
    assert rec["attempt"] == 1 and (ev / "preflight" / "preflight_001.json").is_file()


def test_P_records_are_opened_write_once(tmp_path, monkeypatch):
    drv = _driver()
    src, ev, cfg, cp = _proj(tmp_path)
    _pf(src, ev, cfg, cp, guard_runner(), tmp_path)
    before = (ev / "preflight" / "preflight_000.json").read_bytes()
    monkeypatch.setattr(drv, "_next_attempt", lambda record_dir, work_root: 0)
    with pytest.raises(FileExistsError, match=r"(started|preflight)_000\.json"):
        _pf(src, ev, cfg, cp, guard_runner(status="killed", exit_code=1), tmp_path / "w2")
    assert (ev / "preflight" / "preflight_000.json").read_bytes() == before


# ------------------------------------------------------------------------------------------------- gate: binding
def test_P_gate_accepts_only_a_clean_record_bound_to_the_current_context(tmp_path, monkeypatch):
    src, ev, cfg, cp = _proj(tmp_path)
    gate = _gate()
    with pytest.raises(cr_coord.CoordError, match=r"no pre-flight record"):
        gate.check_preflight(ev / "preflight", cfg, src_root=src, copy_paths=cp)
    _pf(src, ev, cfg, cp, guard_runner(), tmp_path)
    ok = gate.check_preflight(ev / "preflight", cfg, src_root=src, copy_paths=cp)
    assert ok["sha256"] == sha(ev / "preflight" / "preflight_000.json")
    real = cr_coord.harness_hashes()
    monkeypatch.setattr(cr_coord, "harness_hashes", lambda: dict(real, **{"cr_coord.py": "0" * 64}))
    with pytest.raises(cr_coord.CoordError, match=r"no clean pre-flight bound to the current context.*harness"):
        gate.check_preflight(ev / "preflight", cfg, src_root=src, copy_paths=cp)


@pytest.mark.parametrize("drift", ["env", "control", "command", "copy_paths", "source_pin", "argfile", "source",
                                   "helper"])
def test_P_gate_refuses_a_record_from_another_binding(tmp_path, monkeypatch, drift):
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    src, ev, cfg, cp = _proj(tmp_path, extra_copy=["conftest.py"])
    (src / "conftest.py").write_text("# helper v1\n", encoding="utf-8")
    cr_coord.write_cr_toml(ev / "cr.toml", cfg)
    _pf(src, ev, cfg, cp, guard_runner(), tmp_path)
    gate, pin = _gate(), None
    if drift == "env":
        monkeypatch.setenv("PYTHONHASHSEED", "1")
    elif drift == "control":
        (ev / "control.json").write_text(json.dumps({"nodes": NODES[:1]}), encoding="utf-8")
    elif drift == "command":
        cfg.guard_args = cfg.guard_args + ["-x"]
    elif drift == "copy_paths":
        cp = cp + ["ev/c/collect_only.json"]
    elif drift == "argfile":
        (ev / "nodes.txt").write_text(NODES[0] + "\n", encoding="utf-8")
    elif drift == "source":
        (src / "pkg" / "m.py").write_text("X = 7\n", encoding="utf-8")
    elif drift == "helper":
        (src / "conftest.py").write_text("# helper v2\n", encoding="utf-8")
    else:
        pin = "0" * 64
    with pytest.raises(cr_coord.CoordError, match=r"pre-flight"):
        gate.check_preflight(ev / "preflight", cfg, src_root=src, copy_paths=cp, source_sha256=pin)


def test_P_a_not_clean_record_for_the_current_binding_blocks_the_config_even_beside_a_clean_one(tmp_path):
    src, ev, cfg, cp = _proj(tmp_path)
    _pf(src, ev, cfg, cp, guard_runner(), tmp_path)
    _pf(src, ev, cfg, cp, guard_runner(status="killed", exit_code=1), tmp_path)
    with pytest.raises(cr_coord.CoordError, match=r"preflight_001\.json for the current context is not_clean.*not "
                                                  r"used"):
        _gate().check_preflight(ev / "preflight", cfg, src_root=src, copy_paths=cp)


# ---------------------------------------------------------------------------------- gate: calibration / screening
def _inv(tmp_path, src, cfg, items):
    inv = tmp_path / "inventory.json"
    inv.write_text(json.dumps({"module_rel": "pkg/m.py", "source_sha256": sha(src / "pkg" / "m.py"),
                               "test_command": cr_coord.test_command(cfg), "items": cr_coord.order_items(items)}),
                   encoding="utf-8")
    return inv


def test_P_run_manifest_refuses_without_a_clean_preflight_and_runs_with_one(tmp_path):
    src, ev, cfg, cp = _proj(tmp_path)
    _, items = _three(tmp_path / "items")
    inv = _inv(tmp_path, src, cfg, items)
    work = tmp_path / "w"
    work.mkdir()
    (m0,) = cr_coord.write_manifests(work, [["j1"]], sha(inv))
    calls = []
    with pytest.raises(cr_coord.CoordError, match=r"run_manifest needs the config's clean pre-flight"):
        cr_coord.run_manifest(m0, inv, src_root=src, copy_paths=cp, work_root=work / "s0",
                              exec_seam=_seam({}, calls))
    with pytest.raises(cr_coord.CoordError, match=r"no pre-flight record"):
        cr_coord.run_manifest(m0, inv, src_root=src, copy_paths=cp, work_root=work / "s0",
                              exec_seam=_seam({}, calls), cfg=cfg, preflight_dir=ev / "preflight")
    assert calls == [] and not list((work / "s0").glob("batch_*_state.json"))
    _pf(src, ev, cfg, cp, guard_runner(), tmp_path)
    other = cr_coord.CRConfig(python=PY, module_rel="pkg/m.py", target_module="pkg.m",
                              guard_args=list(cfg.guard_args) + ["-x"])
    with pytest.raises(cr_coord.CoordError, match=r"cfg's test command is not this inventory's test_command"):
        cr_coord.run_manifest(m0, inv, src_root=src, copy_paths=cp, work_root=work / "s0",
                              exec_seam=_seam({}, calls), cfg=other, preflight_dir=ev / "preflight")
    st = cr_coord.run_manifest(m0, inv, src_root=src, copy_paths=cp, work_root=work / "s1",
                               exec_seam=_seam({}, calls), cfg=cfg, preflight_dir=ev / "preflight")
    assert st.get("done") == ["j1"] and calls == ["j1"]
    assert st.get("preflight", {}).get("sha256") == sha(ev / "preflight" / "preflight_000.json")


def test_P_calibration_run_batch_with_a_config_identity_needs_a_bound_clean_preflight(tmp_path, monkeypatch):
    src, ev, cfg, cp = _proj(tmp_path)
    _, items = _three(tmp_path / "items")
    by_id = {i["job_id"]: i for i in items}
    inv = _inv(tmp_path, src, cfg, items)
    ident = cr_coord.config_identity(cfg, ev / "cr.toml", config_id="pkg.m/c")
    work, calls = tmp_path / "w", []
    kw = dict(src_root=src, copy_paths=cp, work_root=work, exec_seam=_seam({}, calls), config=ident,
              inventory_path=inv)
    with pytest.raises(cr_coord.CoordError, match=r"needs the config's clean pre-flight"):
        cr_coord.run_batch(["j1"], by_id, batch_id="cal", **kw)
    _pf(src, ev, cfg, cp, guard_runner(), tmp_path)
    other = cr_coord.CRConfig(python=PY, module_rel="pkg/m.py", target_module="pkg.m",
                              guard_args=list(cfg.guard_args) + ["-x"])
    with pytest.raises(cr_coord.CoordError, match=r"identity pkg\.m/c: not the test command of the given cfg"):
        cr_coord.run_batch(["j1"], by_id, batch_id="cal", cfg=other, preflight_dir=ev / "preflight", **kw)
    real = cr_coord.harness_hashes()
    monkeypatch.setattr(cr_coord, "harness_hashes", lambda: dict(real, **{"cr_guard.py": "0" * 64}))
    with pytest.raises(cr_coord.CoordError, match=r"no clean pre-flight bound to the current context"):
        cr_coord.run_batch(["j1"], by_id, batch_id="cal", cfg=cfg, preflight_dir=ev / "preflight", **kw)
    monkeypatch.setattr(cr_coord, "harness_hashes", lambda: real)
    assert calls == [] and not list(work.glob("batch_*_state.json"))
    st = cr_coord.run_batch(["j1"], by_id, batch_id="cal", cfg=cfg, preflight_dir=ev / "preflight", **kw)
    assert st.get("done") == ["j1"] and st.get("preflight", {}).get("record", "").endswith("preflight_000.json")


# ------------------------------------------------------------------------------------------- gate: completion
def test_P_run_completion_refuses_a_shard_without_a_preflight(tmp_path):
    src, by_id, work = _screened(tmp_path)
    specs, factory, calls, pool = _shards(src, {"c1": CLEAN_SURV, "c2": CLEAN_SURV})
    for s in specs:
        s.pop("preflight_dir", None)
    with pytest.raises(cr_coord.CoordError, match=r"completion shard c1 has no pre-flight"):
        cr_coord.run_completion("j1", by_id, specs, pool_path=pool, src_root=src, work_root=work,
                                exec_factory=factory)
    assert calls == {"c1": [], "c2": []} and not (work / "completion").exists()


def test_P_run_completion_refuses_a_shard_whose_preflight_is_from_another_harness(tmp_path, monkeypatch):
    src, by_id, work = _screened(tmp_path)
    specs, factory, calls, pool = _shards(src, {"c1": CLEAN_SURV, "c2": CLEAN_SURV})
    for s in specs:
        clean_preflight(src, s, tmp_path / "pf")
    real = cr_coord.harness_hashes()
    monkeypatch.setattr(cr_coord, "harness_hashes", lambda: dict(real, **{"cr_preflight.py": "0" * 64}))
    monkeypatch.setattr(cr_coord, "_check_screening_context", lambda *a, **k: None)   # isolate the pre-flight gate
    with pytest.raises(cr_coord.CoordError, match=r"no clean pre-flight bound to the current context"):
        cr_coord.run_completion("j1", by_id, specs, pool_path=pool, src_root=src, work_root=work,
                                exec_factory=factory)
    assert calls == {"c1": [], "c2": []}


def test_P_run_completion_with_clean_preflights_runs_and_records_them(tmp_path):
    src, by_id, work = _screened(tmp_path)
    specs, factory, calls, pool = _shards(src, {"c1": CLEAN_SURV, "c2": CLEAN_SURV})
    for s in specs:
        clean_preflight(src, s, tmp_path / "pf")
    res = cr_coord.run_completion("j1", by_id, specs, pool_path=pool, src_root=src, work_root=work,
                                  exec_factory=factory)
    assert res.get("label") == "survived" and calls == {"c1": ["j1"], "c2": ["j1"]}, res
    assert [a.get("preflight", {}).get("sha256") for a in res["attempts"]] == \
        [sha(s["preflight_dir"] / "preflight_000.json") for s in specs]
    assert {k: v["sha256"] for k, v in res.get("preflights", {}).items()} == \
        {s["name"]: sha(s["preflight_dir"] / "preflight_000.json") for s in specs}


# --------------------------------------------------------------------------------------------- CLI over configs
def _tree(tmp_path, n_screen=2):
    """A synthetic S1-shaped tree: research/s1/s1_x.py, docs, s1_tests, and cr_a3/s1_x/{a,b}/ screening configs
    plus cr_a3/s1_x/completion/c1/, each with cr.toml, control.json, collect_only.json (+ inventory / nodes)."""
    root = tmp_path / "repo"
    s1 = root / "research" / "s1"
    (s1 / "docs").mkdir(parents=True)
    (s1 / "docs" / "d.md").write_text("doc\n", encoding="utf-8")
    (s1 / "s1_tests").mkdir()
    (s1 / "s1_tests" / "test_x.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    (s1 / "s1_x.py").write_text("X = 1\n", encoding="utf-8")
    ev = s1 / "s1_evidence" / "cr_a3" / "s1_x"
    rels = []
    for shard in ["a", "b"][:n_screen] + ["completion/c1"]:
        d = ev / shard
        d.mkdir(parents=True)
        rel = f"research/s1/s1_evidence/cr_a3/s1_x/{shard}"
        (d / "control.json").write_text(json.dumps({"nodes": ["research/s1/s1_tests/test_x.py::test_a"]}),
                                        encoding="utf-8")
        (d / "collect_only.json").write_text(json.dumps({"control_sha256": sha(d / "control.json")}),
                                             encoding="utf-8")
        sel = [f"@{rel}/nodes.txt"] if shard.startswith("completion") else ["research/s1/s1_tests/test_x.py"]
        if shard.startswith("completion"):
            (d / "nodes.txt").write_text("research/s1/s1_tests/test_x.py::test_a\n", encoding="utf-8")
        cfg = cr_coord.CRConfig(python=PY, module_rel="research/s1/s1_x.py", target_module="s1_x",
                                pythonpath_rel=["research/s1", "research/s1/s1_tests"],
                                guard_args=["--control", f"{rel}/control.json", "-p", "conftest", *sel])
        cr_coord.write_cr_toml(d / "cr.toml", cfg)
        (d / "baseline" / "run1").mkdir(parents=True)               # the historical baseline's guard sidecar
        (d / "baseline" / "run1" / "guard.json").write_text(json.dumps({"control_sha256": sha(d / "control.json")}),
                                                           encoding="utf-8")
        if not shard.startswith("completion"):
            (d / "inventory.json").write_text(json.dumps({
                "module_rel": "research/s1/s1_x.py", "source_sha256": sha(s1 / "s1_x.py"),
                "copied": {f"{rel}/control.json": sha(d / "control.json")}}), encoding="utf-8")
        rels.append(rel)
    return root, rels


def test_P_cli_runs_configs_in_order_stops_on_the_first_not_clean_and_is_safe_to_rerun(tmp_path):
    drv = _driver()
    root, rels = _tree(tmp_path)
    assert [c["rel"] for c in drv.discover(root, modules=["s1_x"])] == rels, "screening first, then completion"
    seen = []

    def runner(cmd, **kw):
        ctl = cmd[cmd.index("--control") + 1]
        seen.append(ctl)
        status = "killed" if "/b/" in ctl else "survived"
        return guard_runner(status=status, exit_code=1 if status == "killed" else 0)(cmd, **kw)
    out = drv.run_all(root, work_root=tmp_path / "pfw", modules=["s1_x"], runner=runner, clock=lambda: 0.0)
    assert [r["verdict"] for r in out] == ["clean", "not_clean"], out
    assert len(seen) == 2, "stops on the first not_clean: the completion config is not run"
    files = {p: p.read_bytes() for p in (root / "research/s1/s1_evidence/cr_a3").rglob("preflight_*.json")}
    assert len(files) == 2
    out2 = drv.run_all(root, work_root=tmp_path / "pfw", modules=["s1_x"], runner=runner, clock=lambda: 0.0)
    assert [r["verdict"] for r in out2] == ["already_clean", "blocked_not_clean"], out2
    assert len(seen) == 2, "a re-run neither repeats a clean config nor retries a failed one"
    assert {p: p.read_bytes() for p in files} == files, "records are write-once"


def test_P_cli_reads_the_frozen_control_value_from_collect_only_json(tmp_path):
    drv = _driver()
    root, rels = _tree(tmp_path, n_screen=1)
    d = root / rels[0]
    (d / "collect_only.json").write_text(json.dumps({"control_sha256": "0" * 64}), encoding="utf-8")
    with pytest.raises(cr_coord.CoordError, match=r"frozen control value 0{64}"):
        drv.run_all(root, work_root=tmp_path / "pfw", modules=["s1_x"], runner=guard_runner(), clock=lambda: 0.0)
    assert not list(d.rglob("preflight_*.json"))


def test_P_cli_refuses_completion_inventories_that_disagree_on_the_source(tmp_path):
    drv = _driver()
    root, rels = _tree(tmp_path)
    b = root / rels[1] / "inventory.json"
    b.write_text(json.dumps(dict(json.loads(b.read_text(encoding="utf-8")), source_sha256="0" * 64)),
                 encoding="utf-8")
    conf = drv.discover(root, modules=["s1_x"])[2]
    with pytest.raises(cr_coord.CoordError, match=r"no single inventory source_sha256"):
        drv.source_pin(root, conf, drv.config_from_toml(conf["dir"] / "cr.toml"))


def test_P_cli_main_exit_code_is_0_only_when_every_config_is_clean(tmp_path, monkeypatch, capsys):
    drv = _driver()
    root, rels = _tree(tmp_path, n_screen=1)
    monkeypatch.setattr(drv, "default_runner", guard_runner())
    assert drv.main(["all", "--src-root", str(root), "--work-root", str(tmp_path / "w"), "--modules", "s1_x"]) == 0
    assert [json.loads(ln)["verdict"] for ln in capsys.readouterr().out.splitlines()] == ["clean", "clean"]
    root2, _ = _tree(tmp_path / "two", n_screen=1)
    monkeypatch.setattr(drv, "default_runner", guard_runner(status="killed", exit_code=1))
    assert drv.main(["all", "--src-root", str(root2), "--work-root", str(tmp_path / "w2"), "--modules", "s1_x"]) == 1
    assert [json.loads(ln)["verdict"] for ln in capsys.readouterr().out.splitlines()] == ["not_clean"]


def _try_pf(*a, **kw):
    """run_preflight, with any exception turned into {"raised": ...} so a missing record fails as an assertion."""
    try:
        return _pf(*a, **kw)
    except BaseException as exc:              # noqa: BLE001 - the RED must be assertion-type
        return {"raised": repr(exc)}


def test_P_driver_module_is_part_of_the_hash_bound_harness():
    _driver()
    assert "cr_preflight.py" in cr_coord.HARNESS_FILES and "cr_preflight.py" in cr_coord.harness_hashes()


# =============================================================================================== 15c-P fix round 1
# Task review (task-15c-p-review-verdict.md): I1 crash safety, I2 every copied file bound, I3 retries gated, M1 seam
# tied to cfg, M2 real runner on a toy, M3 run_batch gated unless the seam declares itself synthetic, M4 source-tree
# control after the run, M5 independent control records, M6 no --write-control, M7 whole copy unchanged, N4.
def _writes_guard(text):
    def run(cmd, *, cwd, env, job_dir, deadline_s):
        (job_dir / "guard.json").write_text(text, encoding="utf-8")
        return {"rc": 0, "timed_out": True, "cleanup": {"verified": True}}
    return run


@pytest.mark.parametrize("text,reason", [('{"status": "surv', "guard_sidecar_unreadable"),
                                         ("[]", "guard_sidecar_unreadable"),
                                         ('{"status": 1, "nodes": "ab", "counts": [], "cleanup": "yes", '
                                          '"exit_code": "0"}', "guard_field_malformed")])
def test_F1_a_malformed_guard_sidecar_gives_a_written_not_clean_record(tmp_path, text, reason):
    src, ev, cfg, cp = _proj(tmp_path)
    rec = _try_pf(src, ev, cfg, cp, _writes_guard(text), tmp_path)
    assert rec.get("verdict") == "not_clean" and any(r.startswith(reason) for r in rec.get("reasons", [])), rec
    assert json.loads((ev / "preflight" / "preflight_000.json").read_text(encoding="utf-8")) == rec


def test_F1_a_malformed_runner_result_gives_a_written_not_clean_record(tmp_path):
    src, ev, cfg, cp = _proj(tmp_path)
    inner = guard_runner()
    rec = _try_pf(src, ev, cfg, cp, lambda cmd, **kw: (inner(cmd, **kw), [])[1], tmp_path)
    assert rec.get("verdict") == "not_clean" and "runner_result_malformed" in rec.get("reasons", []), rec


def test_F1_a_crash_that_leaves_no_record_is_an_orphan_that_blocks_the_gate_and_the_cli(tmp_path, monkeypatch):
    drv = _driver()
    root, rels = _tree(tmp_path, n_screen=1)
    conf = drv.discover(root, modules=["s1_x"])[0]
    cfg = drv.config_from_toml(conf["dir"] / "cr.toml")
    cp = drv.copy_paths_for(root, cfg)

    real_write = drv._write_record

    def disk_full(path, rec):                  # the final record cannot be written (the marker can)
        if path.name.startswith("preflight_"):
            raise OSError("disk full")
        return real_write(path, rec)
    monkeypatch.setattr(drv, "_write_record", disk_full, raising=False)
    with pytest.raises(OSError, match=r"disk full"):
        drv.run_all(root, work_root=tmp_path / "w", modules=["s1_x"], runner=guard_runner(), clock=lambda: 0.0)
    monkeypatch.undo()
    assert not list((conf["dir"] / "preflight").glob("preflight_*.json"))
    with pytest.raises(cr_coord.CoordError, match=r"no record \(orphan\).*not used"):
        cr_coord.check_preflight(conf["dir"] / "preflight", cfg, src_root=root, copy_paths=cp)
    out = drv.run_all(root, work_root=tmp_path / "w", modules=["s1_x"], runner=guard_runner(), clock=lambda: 0.0)
    assert [r["verdict"] for r in out] == ["blocked_orphan"], out
    assert not list((conf["dir"] / "preflight").glob("preflight_*.json")), "an orphan is never retried past"


def test_F1_an_attempt_dir_without_a_record_blocks_the_cli(tmp_path):
    drv = _driver()
    root, rels = _tree(tmp_path, n_screen=1)
    (tmp_path / "w" / rels[0].replace("/", "__") / "attempt_000").mkdir(parents=True)   # a hard-killed attempt
    out = drv.run_all(root, work_root=tmp_path / "w", modules=["s1_x"], runner=guard_runner(), clock=lambda: 0.0)
    assert [r["verdict"] for r in out] == ["blocked_orphan"], out
    assert not list(root.rglob("preflight_*.json")), "the orphaned config is not retried"


class _Abort(BaseException):
    """A non-Exception abort (like a hard stop), which pytest itself does not treat as a session interrupt."""


def test_F1_a_runner_exception_still_writes_the_record(tmp_path):
    src, ev, cfg, cp = _proj(tmp_path)
    rec = _try_pf(src, ev, cfg, cp, guard_runner(raise_exc=_Abort("hard stop")), tmp_path)
    assert (ev / "preflight" / "preflight_000.json").is_file(), rec
    on_disk = json.loads((ev / "preflight" / "preflight_000.json").read_text(encoding="utf-8"))
    assert on_disk.get("verdict") == "not_clean" and "runner_exception:_Abort" in on_disk["reasons"]
    assert "_Abort" in rec.get("raised", ""), "a non-Exception abort is re-raised after the record is written"


# --- I2: every copied file is bound ----------------------------------------------------------------------------
@pytest.mark.parametrize("change", ["edit", "add"])
def test_F2_gate_refuses_after_any_copied_file_changes(tmp_path, change):
    src, ev, cfg, cp = _proj(tmp_path)
    (src / "pkg" / "test_extra.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    _pf(src, ev, cfg, cp, guard_runner(), tmp_path)
    if change == "edit":
        (src / "pkg" / "test_extra.py").write_text("import pytest\npytestmark = pytest.mark.skip\n", encoding="utf-8")
    else:
        (src / "pkg" / "sibling.py").write_text("Y = 1\n", encoding="utf-8")
    with pytest.raises(cr_coord.CoordError, match=r"no clean pre-flight bound to the current context.*copied_sha256"):
        _gate().check_preflight(ev / "preflight", cfg, src_root=src, copy_paths=cp)


def test_F2_the_preflight_binding_holds_the_copied_tree_hash(tmp_path):
    src, ev, cfg, cp = _proj(tmp_path)
    b = _gate().preflight_binding(cfg, src, cp)
    assert b.get("copied_sha256") and hasattr(cr_coord, "copied_map"), b
    assert b["copied_sha256"] == cr_coord.map_sha256(cr_coord.copied_map(src, cp))


def test_F2_cached_completion_attempt_is_not_reused_after_a_copied_file_changes(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    src, by_id, work = _screened(tmp_path)
    (src / "extra_test.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    specs, factory, calls, pool = _shards(src, {"c1": CLEAN_SURV})
    specs[0]["copy_paths"].append("extra_test.py")
    r1 = _complete(src, by_id, work, specs, factory, pool)
    assert r1.get("label") == "survived"
    assert "copied_sha256" in r1["attempts"][0]["binding"], "the execution-time binding holds the copied tree"
    (src / "extra_test.py").write_text("import pytest\npytestmark = pytest.mark.skip\n", encoding="utf-8")
    with pytest.raises(cr_coord.CoordError, match=r"executed binding drift in \['copied_sha256'\]"):
        _complete(src, by_id, work, specs, factory, pool)
    assert calls["c1"] == ["j1"]


def test_F2_a_screening_label_is_not_reused_after_its_copied_tree_changed(tmp_path):
    src, by_id, work = _screened(tmp_path)
    st = json.loads((work / "batch_b000_state.json").read_text(encoding="utf-8"))
    assert st.get("copy_paths") == ["pkg"] and st.get("copied_tree_sha256", {}).get("j1"), st
    (src / "pkg" / "sibling.py").write_text("Y = 1\n", encoding="utf-8")             # module m.py unchanged
    specs, factory, calls, pool = _shards(src, {"c1": CLEAN_SURV})
    with pytest.raises(cr_coord.CoordError, match=r"screening of j1 .*copied tree .*not reused"):
        _complete(src, by_id, work, specs, factory, pool)
    assert calls["c1"] == []


# --- I3: a retry is gated on the BASE config's clean pre-flight, the one the timeout batch ran under -------------
def _gated_timeout(tmp_path):
    """A screening timeout of j1 run under a clean pre-flight of the base cfg (synthetic seam, gated anyway)."""
    src, items = _three(tmp_path)
    by_id = {i["job_id"]: i for i in items}
    cfg = _cfg("r")
    from test_s1_a3_cr_completion import _pf_dir
    cp = ["pkg", "r.json"]
    pfd = _pf_dir(tmp_path, src, cfg, cp)
    work = tmp_path / "w"
    st = cr_coord.run_batch(["j1"], by_id, batch_id="b000", src_root=src, copy_paths=cp, work_root=work,
                            exec_seam=_seam({"j1": GUARD_TIMEOUT}, []), cfg=cfg, preflight_dir=pfd)
    assert st["labels"] == {"j1": "timeout"}
    return src, by_id, cfg, cp, pfd, work


def _real_like(calls):
    """An exec factory whose seams do NOT declare themselves synthetic (stands for real_exec in gating tests)."""
    def factory(c):
        def seam(item, copy_root, job_dir):
            calls.append(item["job_id"])
            return dict(CLEAN_SURV)
        return seam
    return factory


def test_F3_run_retry_takes_the_base_preflight(tmp_path):
    assert "preflight_dir" in inspect.signature(cr_coord.run_retry).parameters, "run_retry(preflight_dir=...)"
    src, by_id, cfg, cp, pfd, work = _gated_timeout(tmp_path)
    calls = []
    with pytest.raises(cr_coord.CoordError, match=r"retry of j1 needs the base config's clean pre-flight"):
        cr_coord.run_retry("j1", by_id, cfg, src_root=src, copy_paths=cp, work_root=work,
                           exec_factory=_real_like(calls))
    assert calls == []
    st = cr_coord.run_retry("j1", by_id, cfg, src_root=src, copy_paths=cp, work_root=work,
                            exec_factory=_real_like(calls), preflight_dir=pfd)
    assert st.get("labels") == {"j1": "survived"} and calls == ["j1"]
    assert st.get("preflight", {}).get("sha256") == sha(pfd / "preflight_000.json")


def test_F3_run_retry_refuses_when_the_timeout_batch_ran_under_another_preflight(tmp_path):
    assert "preflight_dir" in inspect.signature(cr_coord.run_retry).parameters, "run_retry(preflight_dir=...)"
    src, items = _three(tmp_path)
    by_id = {i["job_id"]: i for i in items}
    cfg = _cfg("r")
    from test_s1_a3_cr_completion import _pf_dir
    cp = ["pkg", "r.json"]
    pfd = _pf_dir(tmp_path, src, cfg, cp)
    work = tmp_path / "w"
    cr_coord.run_batch(["j1"], by_id, batch_id="b000", src_root=src, copy_paths=cp, work_root=work,
                       exec_seam=_seam({"j1": GUARD_TIMEOUT}, []))                  # ungated synthetic screening
    calls = []
    with pytest.raises(cr_coord.CoordError, match=r"timeout batch b000 ran under pre-flight None"):
        cr_coord.run_retry("j1", by_id, cfg, src_root=src, copy_paths=cp, work_root=work,
                           exec_factory=_real_like(calls), preflight_dir=pfd)
    assert calls == []


# --- M1 / M3: the seam is tied to cfg, and only a declared synthetic seam runs without a pre-flight ---------------
def test_F4_real_exec_seam_is_tagged_and_run_batch_refuses_a_seam_for_another_command(tmp_path):
    src, ev, cfg, cp = _proj(tmp_path)
    other = cr_coord.CRConfig(python=PY, module_rel="pkg/m.py", target_module="pkg.m",
                              guard_args=list(cfg.guard_args) + ["-x"])
    seam = cr_coord.real_exec(other)
    assert getattr(seam, "test_command_sha256", None) == cr_coord.hashlib.sha256(
        cr_coord.test_command(other).encode("utf-8")).hexdigest() and getattr(seam, "cr_real_exec", False)
    _pf(src, ev, cfg, cp, guard_runner(), tmp_path)
    _, items = _three(tmp_path / "items")
    with pytest.raises(cr_coord.CoordError, match=r"exec seam was built for another test command"):
        cr_coord.run_batch(["j1"], {i["job_id"]: i for i in items}, batch_id="b0", src_root=src, copy_paths=cp,
                           work_root=tmp_path / "w", exec_seam=seam, cfg=cfg, preflight_dir=ev / "preflight")
    assert not (tmp_path / "w" / "batch_b0_state.json").exists()


def test_F6_run_batch_refuses_an_undeclared_seam_without_a_preflight(tmp_path):
    src, items = _three(tmp_path)
    calls = []
    with pytest.raises(cr_coord.CoordError, match=r"needs the config's clean pre-flight"):
        cr_coord.run_batch(["j1"], {i["job_id"]: i for i in items}, batch_id="b0", src_root=src, copy_paths=["pkg"],
                           work_root=tmp_path / "w", exec_seam=_real_like(calls)(None))
    assert calls == [] and not (tmp_path / "w" / "batch_b0_state.json").exists()


def test_F6_a_real_exec_seam_can_never_be_declared_synthetic(tmp_path):
    src, items = _three(tmp_path)
    seam = cr_coord.real_exec(_cfg("z"))
    assert getattr(seam, "cr_real_exec", False), "real_exec seams are marked"
    seam.synthetic = True
    with pytest.raises(cr_coord.CoordError, match=r"needs the config's clean pre-flight"):
        cr_coord.run_batch(["j1"], {i["job_id"]: i for i in items}, batch_id="b0", src_root=src, copy_paths=["pkg"],
                           work_root=tmp_path / "w", exec_seam=seam)


def test_F6_a_declared_synthetic_seam_runs_without_a_preflight_and_says_so(tmp_path):
    src, items = _three(tmp_path)
    st = cr_coord.run_batch(["j1"], {i["job_id"]: i for i in items}, batch_id="b0", src_root=src,
                            copy_paths=["pkg"], work_root=tmp_path / "w", exec_seam=_seam({}, []))
    assert st.get("done") == ["j1"] and st.get("preflight") is None and st.get("synthetic_seam") is True, st


# --- M2: the production runner on a two-test toy (real guard + pytest; no S1 module, no Cosmic Ray) ---------------
def _toy(tmp_path, nodes):
    src = tmp_path / "toy"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (src / "pkg" / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (src / "pkg" / "test_m.py").write_text("from pkg.m import f\n\n\ndef test_a():\n    assert f() == 1\n\n\n"
                                           "def test_b():\n    assert f() + 1 == 2\n", encoding="utf-8")
    (src / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (src / "harness").mkdir()
    shutil.copy2(cr_coord.HARNESS_DIR / "cr_guard.py", src / "harness" / "cr_guard.py")
    ev = src / "ev"
    ev.mkdir()
    (ev / "control.json").write_text(json.dumps({"nodes": sorted(nodes)}), encoding="utf-8")
    cfg = cr_coord.CRConfig(python=PY, module_rel="pkg/m.py", target_module="pkg.m", pythonpath_rel=[".", "harness"],
                            timeout_s=120.0, guard_deadline_s=60.0,
                            guard_args=["--control", "ev/control.json", "pkg/test_m.py"])
    cr_coord.write_cr_toml(ev / "cr.toml", cfg)
    return src, ev, cfg, ["pkg", "pytest.ini", "harness", "ev/control.json"]


@pytest.mark.parametrize("nodes,verdict", [(["pkg/test_m.py::test_a", "pkg/test_m.py::test_b"], "clean"),
                                           (["pkg/test_m.py::test_a"], "not_clean")])
def test_F5_default_runner_with_the_real_guard_on_a_toy(tmp_path, nodes, verdict):
    drv = _driver()
    src, ev, cfg, cp = _toy(tmp_path, nodes)
    rec = drv.run_preflight(cfg, src_root=src, copy_paths=cp, record_dir=ev / "preflight", cr_toml=ev / "cr.toml",
                            expected_control_sha256=sha(ev / "control.json"), source_sha256=sha(src / "pkg" / "m.py"),
                            work_root=tmp_path / "work", config_id="toy")
    assert rec["verdict"] == verdict, rec
    if verdict == "clean":
        assert rec["guard"]["status"] == "survived" and rec["outer"]["cleanup_verified"] is True
        cr_coord.check_preflight(ev / "preflight", cfg, src_root=src, copy_paths=cp)
    else:
        assert "guard_status:node_set_mismatch" in rec["reasons"] and "node_set_mismatch" in rec["reasons"], rec


# --- M4 / M7 / N4: the after-run checks -------------------------------------------------------------------------
@pytest.mark.parametrize("edit,reason", [
    (lambda c, src: (src / "ev/c/control.json").write_text('{"nodes": []}', encoding="utf-8"), "control_changed"),
    (lambda c, src: (c / "ev/c/nodes.txt").write_text("x\n", encoding="utf-8"), "copy_changed"),
    (lambda c, src: (c / "pkg" / "new_file.py").write_text("Z = 1\n", encoding="utf-8"), "copy_changed"),
    (lambda c, src: (src / "pkg" / "sibling.py").write_text("Y = 2\n", encoding="utf-8"), "source_tree_changed"),
])
def test_F7_the_after_run_checks_cover_the_source_control_and_every_copied_file(tmp_path, edit, reason):
    src, ev, cfg, cp = _proj(tmp_path)
    rec = _try_pf(src, ev, cfg, cp, guard_runner(edit=lambda c: edit(c, src)), tmp_path)
    assert rec.get("verdict") == "not_clean" and reason in rec.get("reasons", []), rec


@pytest.mark.parametrize("kw,reason", [(dict(rc=3), "guard_rc_nonzero"),
                                       (dict(counts={"tests": 2, "failures": 0, "errors": 0, "skipped": 0,
                                                     "passed": 1}), "counts")])
def test_F8_guard_rc_and_passed_count_are_cross_checked(tmp_path, kw, reason):
    src, ev, cfg, cp = _proj(tmp_path)
    rec = _try_pf(src, ev, cfg, cp, guard_runner(**kw), tmp_path)
    assert rec.get("verdict") == "not_clean" and reason in rec.get("reasons", []), rec


# --- M5 / M6 -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("where", ["baseline", "inventory"])
def test_F9_cli_cross_checks_the_frozen_value_against_independent_records(tmp_path, where):
    drv = _driver()
    root, rels = _tree(tmp_path, n_screen=1)
    d = root / rels[0]
    if where == "baseline":
        (d / "baseline" / "run1" / "guard.json").write_text(json.dumps({"control_sha256": "1" * 64}),
                                                            encoding="utf-8")
    else:
        inv = json.loads((d / "inventory.json").read_text(encoding="utf-8"))
        inv["copied"] = {f"{rels[0]}/control.json": "1" * 64}
        (d / "inventory.json").write_text(json.dumps(inv), encoding="utf-8")
    with pytest.raises(cr_coord.CoordError, match=r"frozen control value .* disagrees with"):
        drv.run_all(root, work_root=tmp_path / "w", modules=["s1_x"], runner=guard_runner(), clock=lambda: 0.0)
    assert not list(d.rglob("preflight_*.json"))


def test_F10_a_config_that_asks_the_guard_to_write_its_control_is_refused(tmp_path):
    src, ev, cfg, cp = _proj(tmp_path)
    cfg.guard_args = list(cfg.guard_args) + ["--write-control", "ev/c/control.json"]
    cr_coord.write_cr_toml(ev / "cr.toml", cfg)
    calls = []
    with pytest.raises(cr_coord.CoordError, match=r"--write-control"):
        _pf(src, ev, cfg, cp, guard_runner(calls=calls), tmp_path)
    assert calls == [] and not (ev / "preflight").exists()


# --- fix round 1: further pins (added while planning the deletion checks) ------------------------------------
def test_F11_a_driver_error_after_the_copy_is_a_written_not_clean_record(tmp_path):
    src, ev, cfg, cp = _proj(tmp_path)
    rec = _try_pf(src, ev, cfg, cp, guard_runner(edit=lambda c: shutil.rmtree(c / "pkg")), tmp_path)
    assert rec.get("verdict") == "not_clean" and any(r.startswith("driver_exception:") for r in rec["reasons"]), rec
    assert (ev / "preflight" / "preflight_000.json").is_file()


def test_F11_a_copy_that_differs_from_the_source_tree_elsewhere_is_refused_and_recorded(tmp_path, monkeypatch):
    src, ev, cfg, cp = _proj(tmp_path)
    real = cr_coord.make_copy

    def diverging(src_root, copy_paths, dest):
        out = real(src_root, copy_paths, dest)
        (dest / "ev" / "c" / "nodes.txt").write_text("x\n", encoding="utf-8")
        return out
    monkeypatch.setattr(cr_coord, "make_copy", diverging)
    calls = []
    rec = _try_pf(src, ev, cfg, cp, guard_runner(calls=calls), tmp_path)
    assert rec.get("verdict") == "not_clean" and "copy_differs_from_source" in rec["reasons"] and calls == [], rec


def test_F11_generated_caches_are_not_part_of_the_copied_tree(tmp_path):
    assert hasattr(cr_coord, "copied_map"), "cr_coord.copied_map exists"
    src, ev, cfg, cp = _proj(tmp_path)
    (src / "pkg" / "__pycache__").mkdir()
    (src / "pkg" / "__pycache__" / "m.cpython-312.pyc").write_bytes(b"cache")
    (src / "pkg" / "stale.pyc").write_bytes(b"cache")
    assert not any("__pycache__" in k or k.endswith(".pyc") for k in cr_coord.copied_map(src, cp))
    rec = _pf(src, ev, cfg, cp, guard_runner(), tmp_path)
    assert rec["verdict"] == "clean", rec


def test_F11_an_unreadable_record_blocks_the_gate(tmp_path):
    src, ev, cfg, cp = _proj(tmp_path)
    _pf(src, ev, cfg, cp, guard_runner(), tmp_path)
    (ev / "preflight" / "preflight_009.json").write_text("{trunc", encoding="utf-8")
    with pytest.raises(cr_coord.CoordError, match=r"preflight_009\.json for the current context is not_clean"):
        _gate().check_preflight(ev / "preflight", cfg, src_root=src, copy_paths=cp)


def test_F11_the_cli_needs_at_least_one_baseline_guard_sidecar(tmp_path):
    drv = _driver()
    root, rels = _tree(tmp_path, n_screen=1)
    shutil.rmtree(root / rels[0] / "baseline")
    with pytest.raises(cr_coord.CoordError, match=r"no baseline guard sidecar"):
        drv.run_all(root, work_root=tmp_path / "w", modules=["s1_x"], runner=guard_runner(), clock=lambda: 0.0)


@pytest.mark.parametrize("retry", [False, True])
def test_F11_the_seam_tag_must_match_the_base_or_retry_command(tmp_path, monkeypatch, retry):
    assert "retry" in inspect.signature(cr_coord.run_batch).parameters, "run_batch(retry=...)"
    src, ev, cfg, cp = _proj(tmp_path)
    _pf(src, ev, cfg, cp, guard_runner(), tmp_path)

    def no_cosmic_ray(*a, **k):
        raise OSError("no Cosmic Ray in this test")
    monkeypatch.setattr(cr_coord, "_launch", no_cosmic_ray)
    seam = cr_coord.real_exec(cfg if retry else cr_coord.retry_config(cfg))   # the WRONG one for each mode
    _, items = _three(tmp_path / "items")
    with pytest.raises(cr_coord.CoordError, match=r"exec seam was built for another test command"):
        cr_coord.run_batch(["j1"], {i["job_id"]: i for i in items}, batch_id="b0", src_root=src, copy_paths=cp,
                           work_root=tmp_path / "w", exec_seam=seam, cfg=cfg, preflight_dir=ev / "preflight",
                           retry=retry)


@pytest.mark.parametrize("case", ["sha", "other_config", "not_clean"])
def test_F11_a_handed_over_preflight_reference_is_re_verified(tmp_path, case):
    assert "preflight_ref" in inspect.signature(cr_coord.run_batch).parameters, "run_batch(preflight_ref=...)"
    src, ev, cfg, cp = _proj(tmp_path)
    rec = _pf(src, ev, cfg, cp, guard_runner(status="killed", exit_code=1) if case == "not_clean" else guard_runner(),
              tmp_path)
    path = ev / "preflight" / f"preflight_{rec['attempt']:03d}.json"
    ref = {"record": str(path), "sha256": "0" * 64 if case == "sha" else sha(path)}
    use = cfg if case != "other_config" else cr_coord.CRConfig(python=PY, module_rel="pkg/m.py", target_module="pkg.m",
                                                               guard_args=list(cfg.guard_args) + ["-x"])
    _, items = _three(tmp_path / "items")
    calls = []
    with pytest.raises(cr_coord.CoordError, match=r"pre-flight (reference .* does not match its record|"
                                                  r"preflight_000\.json is not a clean pre-flight of this config)"):
        cr_coord.run_batch(["j1"], {i["job_id"]: i for i in items}, batch_id="b0", src_root=src, copy_paths=cp,
                           work_root=tmp_path / "w", exec_seam=_real_like(calls)(None), cfg=use, preflight_ref=ref)
    assert calls == []


def test_F11_an_abort_that_escapes_the_attempt_body_is_recorded_as_interrupted(tmp_path, monkeypatch):
    drv = _driver()
    src, ev, cfg, cp = _proj(tmp_path)

    def abort(side):
        raise _Abort("stopped while reading the sidecar")
    monkeypatch.setattr(drv, "_read_guard", abort, raising=False)
    rec = _try_pf(src, ev, cfg, cp, guard_runner(), tmp_path)
    assert "_Abort" in rec.get("raised", ""), rec
    on_disk = json.loads((ev / "preflight" / "preflight_000.json").read_text(encoding="utf-8"))
    assert on_disk["verdict"] == "not_clean" and "interrupted" in on_disk["reasons"], on_disk


# =============================================================================================== 15c-P fix round 2
# Re-review 1: R1-M1 a stale handed-over pre-flight reference, R1-M2 the liveness of _next_attempt's marker term,
# R1-M3 the changed paths behind copy_changed / source_tree_changed.
def test_F12_a_stale_preflight_ref_is_refused_by_run_batch(tmp_path):
    """The reviewer's probe: a clean record, then a file added under the copied pkg/, then a direct
    run_batch(cfg=, preflight_ref=<that record>) with a non-synthetic seam."""
    src, ev, cfg, cp = _proj(tmp_path)
    rec = _pf(src, ev, cfg, cp, guard_runner(), tmp_path)
    path = ev / "preflight" / f"preflight_{rec['attempt']:03d}.json"
    (src / "pkg" / "added_later.py").write_text("Z = 1\n", encoding="utf-8")
    _, items = _three(tmp_path / "items")
    calls = []
    with pytest.raises(cr_coord.CoordError, match=r"preflight_000\.json is not bound to the current context .*"
                                                  r"copied_sha256"):
        cr_coord.run_batch(["j1"], {i["job_id"]: i for i in items}, batch_id="b0", src_root=src, copy_paths=cp,
                           work_root=tmp_path / "w", exec_seam=_real_like(calls)(None), cfg=cfg,
                           preflight_ref={"record": str(path), "sha256": sha(path)})
    assert calls == [] and not (tmp_path / "w" / "batch_b0_state.json").exists()


def test_F12_an_old_binding_orphan_does_not_block_a_new_binding_under_a_new_work_root(tmp_path, monkeypatch):
    drv = _driver()
    src, ev, cfg, cp = _proj(tmp_path)
    real_write = drv._write_record

    def disk_full(path, rec):                       # the attempt-0 record cannot be written: an orphan marker
        if path.name.startswith("preflight_"):
            raise OSError("disk full")
        return real_write(path, rec)
    monkeypatch.setattr(drv, "_write_record", disk_full)
    with pytest.raises(OSError, match=r"disk full"):
        _pf(src, ev, cfg, cp, guard_runner(), tmp_path / "w1")
    monkeypatch.undo()
    assert (ev / "preflight" / "started_000.json").is_file() and not (ev / "preflight" / "preflight_000.json").exists()
    (src / "pkg" / "new_input.py").write_text("N = 1\n", encoding="utf-8")         # the binding changes
    rec = _try_pf(src, ev, cfg, cp, guard_runner(), tmp_path / "w2")              # ... and a new work root
    assert rec.get("verdict") == "clean" and rec.get("attempt") == 1, rec
    cr_coord.check_preflight(ev / "preflight", cfg, src_root=src, copy_paths=cp)


def _changes(c, src):
    (c / "ev/c/nodes.txt").write_text("x\n", encoding="utf-8")                   # modified
    (c / "pkg" / "new_in_copy.py").write_text("A = 1\n", encoding="utf-8")       # added
    (c / "pkg" / "extra.py").unlink()                                               # removed
    (src / "pkg" / "new_in_src.py").write_text("B = 1\n", encoding="utf-8")      # source tree: added


def test_F12_the_changed_paths_are_recorded(tmp_path):
    src, ev, cfg, cp = _proj(tmp_path)
    (src / "pkg" / "extra.py").write_text("E = 1\n", encoding="utf-8")
    rec = _try_pf(src, ev, cfg, cp, guard_runner(edit=lambda c: _changes(c, src)), tmp_path)
    assert {"copy_changed", "source_tree_changed"} <= set(rec.get("reasons", [])), rec
    assert rec.get("changed_paths", {}).get("copy") == {
        "added": ["pkg/new_in_copy.py"], "removed": ["pkg/extra.py"], "modified": ["ev/c/nodes.txt"], "total": 3,
        "truncated": False}, rec.get("changed_paths")
    assert rec["changed_paths"].get("source_tree") == {"added": ["pkg/new_in_src.py"], "removed": [], "modified": [],
                                                       "total": 1, "truncated": False}


def test_F12_the_changed_path_lists_are_capped_with_a_total(tmp_path):
    src, ev, cfg, cp = _proj(tmp_path)

    def many(c):
        for i in range(70):
            (c / "pkg" / f"gen_{i:03d}.py").write_text("G = 1\n", encoding="utf-8")
    rec = _try_pf(src, ev, cfg, cp, guard_runner(edit=many), tmp_path)
    ch = rec.get("changed_paths", {}).get("copy") or {}
    assert ch.get("total") == 70 and ch.get("truncated") is True and len(ch.get("added", [])) == 50, ch
    assert ch["added"] == [f"pkg/gen_{i:03d}.py" for i in range(50)]
