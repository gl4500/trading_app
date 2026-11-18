"""A3 Task 15c-P2: the import-invalid-candidate diagnosis (Codex PROVENANCE_P_RULING P1-P5 with Claude amendments A1-A4)
and the external sampling plan v2, in research/s1/cr_tools/cr_calibrate.py.

SYNTHETIC TOYS ONLY under pytest tmp_path: a fake Cosmic Ray seam (declared synthetic) returns real_exec-shaped records
and writes guard-shaped sidecars; the diagnosis children are REAL contained children (cr_guard.run_contained) running
cr_import_probe.py on fresh copies of the TOY tree - or a fake runner where no real child is needed. No S1 module is
imported, mutated or executed; no real calibration, no derive-cap on real data.
"""
import json
import uuid
from pathlib import Path

import pytest

import cr_coord
import cr_guard
from test_cr_calibrate import (CLEAN_KILL, CLEAN_SURV, EVID_REL, _drv, _run, factory, sha, toy)

MOD_REL = "research/s1/s1_x.py"
GENUINE = ("SLOT_KINDS = ('a', 'b')\nSTAGE_KINDS = ('c',)\nTRIAL_KINDS = ('d',)\n"
           "KINDS = SLOT_KINDS + STAGE_KINDS + TRIAL_KINDS                # F0.3\n")
RUNTIME_TAIL = "\n\ndef f():\n    return 1 + 2\n"            # line 8: f's body, the runtime stratum
E_LINE = "E   TypeError: unsupported operand type(s) for &: 'tuple' and 'tuple'"
CANON = "label:error/error:collection"


def _fn(name):
    """A driver attribute, asserted to exist (RED is an assertion, never an AttributeError)."""
    assert hasattr(_drv(), name), f"cr_calibrate.{name} exists"
    return getattr(_drv(), name)


def item(job, op="core/NumberReplacer", occ=0, start=(1, 0), end=(1, 1)):
    return {"job_id": job, "module_path": MOD_REL, "operator": op, "operator_args": {}, "occurrence": occ,
            "start": list(start), "end": list(end)}


def genuine_items(n=24, *, special=None, runtime=0):
    """j00..: fillers outside every def body (import stratum; never applied - the fake CR never mutates) at line 0
    before j05 and line 1000 after it, so the deterministic order (location first) stays j00, j01, ...; ``special``
    {job: item}; the last ``runtime`` items sit in f's body (RUNTIME_TAIL line 8: runtime stratum)."""
    out = []
    for i in range(n):
        j = f"j{i:02d}"
        if special and j in special:
            out.append(special[j])
        elif i >= n - runtime:
            out.append(item(j, start=(8, 4), end=(8, 16), occ=i))
        else:
            line = 0 if i <= 5 else 1000
            out.append(item(j, start=(line, i), end=(line, i + 1), occ=i))
    return out


GENUINE_ITEM = item("j05", "core/ReplaceBinaryOperator_Add_BitAnd", 0, (4, 19), (4, 20))


def ptoy(tmp_path, src=GENUINE + RUNTIME_TAIL, special=None, runtime=0, **kw):
    sp = {"j05": GENUINE_ITEM} if special is None else special
    return toy(tmp_path, items=genuine_items(special=sp, runtime=runtime), module_src=src, completion=False, **kw)


# ------------------------------------------------------------------------------------- the fake CR (guard-shaped)
def collection_error(job_dir: Path, job: str, *, errors=None, nodes_edit=None, guard_edit=None, raw_edit=None,
                     write_nodes=True, attempt=None):
    """Write <job_dir>/guard.json + attempt-<a>/nodes.json + classification.json exactly as cr_guard.main /
    cr_reconcile write them for a collection error, and return the real_exec-shaped record."""
    a = attempt or uuid.uuid4().hex
    att = job_dir / f"attempt-{a}"
    att.mkdir(parents=True)
    errs = errors if errors is not None else [
        {"nodeid": "research/s1/s1_tests/test_x.py",
         "longrepr": f"research\\s1\\s1_tests\\test_x.py:1: in <module>\n    import s1_x\n"
                     f"research\\s1\\s1_x.py:4: in <module>\n    KINDS = SLOT_KINDS & STAGE_KINDS + TRIAL_KINDS\n{E_LINE}"}]
    nodes = {"attempt": a, "call_exc": {}, "collect_errors": errs, "exitstatus": 2, "imports": {"s1_x": None},
             "internal_error": False, "phases": {}, "selected": [], "xfail": []}
    if nodes_edit:
        nodes_edit(nodes)
    if write_nodes:
        (att / "nodes.json").write_text(json.dumps(nodes, indent=1, sort_keys=True), encoding="utf-8")
    side = {"schema": "a3-t15a-guard/1", "job_id": job, "attempt": a, "attempt_dir": str(att), "status":
            "error:collection", "exit_code": 0, "rc": 2, "collect_errors": errs, "nodes": [],
            "cleanup": {"verified": True}, "guard_sha256": sha(cr_guard.__file__),
            "nodes_record_sha256": sha(att / "nodes.json") if write_nodes else None}
    if guard_edit:
        guard_edit(side)
    (job_dir / "guard.json").write_text(json.dumps(side, indent=1, sort_keys=True), encoding="utf-8")
    raw = {"cr_timeout": False, "guard_attempt": a, "test_outcome": "survived", "worker_outcome": "normal"}
    if raw_edit:
        raw_edit(raw)
    (job_dir / "classification.json").write_text(json.dumps({
        "schema": "a3-t15a-classification/1", "items": [{
            "job_id": job, "label": "error", "raw": raw, "sidecar_sha256": sha(job_dir / "guard.json"),
            "sidecar_status": "error:collection"}]}), encoding="utf-8")
    return {"label": "error", "reason": "raw survived with guard status error:collection (own=True)",
            "guard_status": "error:collection", "raw": raw, "raw_timeout": False, "exec_status": "ok",
            "cleanup_verified": True, "session_sha256": "0" * 64}


def cr_factory(errs: dict, calls: list, *, clock_step=None, on_call=None):
    """A synthetic CR exec factory: jobs in ``errs`` (job -> kwargs for collection_error, or a callable) produce a
    collection error; every other job is a clean kill."""
    def make(cfg):
        args = [str(a) for a in cfg.guard_args]
        ctl = args[args.index("--control") + 1]
        kind = ctl.split("/")[-2] if "/completion/" in ctl else "screen"

        def seam(it, copy_root, job_dir):
            calls.append((kind, it["job_id"]))
            if on_call:
                on_call(kind, it["job_id"])
            if clock_step:
                clock_step()
            spec = errs.get(it["job_id"]) if kind == "screen" else errs.get((kind, it["job_id"]))
            if spec is None:
                return dict(CLEAN_KILL) if kind == "screen" else dict(CLEAN_SURV)
            if callable(spec):
                return spec(job_dir, it["job_id"])
            return collection_error(job_dir, it["job_id"], **spec)
        seam.synthetic = True
        return seam
    return make


def runner_spy(log: list, *, fake=None):
    """Wrap the real cr_guard.run_contained (real contained children on toy copies) and log each call."""
    def run(cmd, **kw):
        mode = cmd[cmd.index("--mode") + 1]
        log.append({"mode": mode, "deadline_s": kw.get("deadline_s"), "cleanup_s": kw.get("cleanup_s"),
                    "cmd": list(cmd), "cwd": str(kw.get("cwd"))})
        if fake is not None:
            r = fake(mode, cmd, kw)
            if r is not None:
                return r
        return cr_guard.run_contained(cmd, **kw)
    return run


def psession(tmp_path, errs, *, calls=None, log=None, fake=None, **kw):
    calls = [] if calls is None else calls
    log = [] if log is None else log
    kw.setdefault("_test_diag_runner", runner_spy(log, fake=fake))
    return _run(tmp_path / "repo", tmp_path / "work", "s1_x/a", _test_exec_factory=cr_factory(errs, calls), **kw)


def state(tmp_path):
    return json.loads((tmp_path / "work/s1_x__a/session-000/batch_000_state.json").read_text(encoding="utf-8"))


def job_dir(tmp_path, job="j05"):
    return tmp_path / "work/s1_x__a/session-000/jobs" / job


def policy_rec(tmp_path, job="j05"):
    return json.loads((job_dir(tmp_path, job) / "policy_result.json").read_text(encoding="utf-8"))


def assert_halted_at(tmp_path, rep, calls, job="j05", n=6):
    st = state(tmp_path)
    assert [j for k, j in calls if k == "screen"] == [f"j{i:02d}" for i in range(n)], "zero next call"
    assert st["stopped"] is True and st["stop_reason"].endswith(f": {job}"), st["stop_reason"]
    assert rep["stop"] is not None and job in rep["stop"]["detail"], rep["stop"]
    assert st["labels"][job] == "error" or st["labels"][job] is None
    return st


# ====================================================================== the genuine positive case (toy + replay)
def test_P5_the_c03580c0_shape_replay_continues_as_an_import_invalid_candidate(tmp_path):
    ptoy(tmp_path)
    calls, log = [], []
    rep = psession(tmp_path, {"j05": {}}, calls=calls, log=log)
    st = state(tmp_path)
    assert rep["stop"] is None, rep["stop"]
    assert [j for _, j in calls] == [f"j{i:02d}" for i in range(24)], "the session goes on"
    assert [c["mode"] for c in log] == ["control", "mutated"], "exactly one diagnosis pair"
    assert all(c["deadline_s"] == 60 and c["cleanup_s"] == 45 for c in log), log
    r = st["results"]["j05"]
    assert st["labels"]["j05"] == "error" and r["label"] == "error" and r["guard_status"] == "error:collection"
    assert r["raw"]["test_outcome"] == "survived", "the raw CR outcome is unchanged (never 'incompetent')"
    assert r["exec_status"] == "ok" and r["driver_disposition"] == "import-invalid-candidate"
    assert r["policy"]["halt"] is False and r["policy"]["canonical_reason"] == CANON
    d = json.loads((job_dir(tmp_path) / "dg" / "disposition.json").read_text(encoding="utf-8"))
    assert d["driver_disposition"] == "import-invalid-candidate" and d["policy_version"] == _fn("POLICY_VERSION")
    assert "re-applied under probe context" in d["note"] and d["nonkill"] is True
    for k in ("control", "mutated"):
        p = Path(d["records"][k]["path"])
        assert p.is_file() and sha(p) == d["records"][k]["sha256"]
    assert d["context"] == {"kind": "module", "qualname": "<module>", "firstlineno": 1}
    assert d["gate"]["innermost"]["co_qualname"] == "<module>" and d["gate"]["overlap"] is True
    with pytest.raises(FileExistsError):
        _drv()._write_once(job_dir(tmp_path) / "dg" / "disposition.json", {"again": 1})
    acc = rep["accounting"]
    assert acc["import_invalid_candidates"] == ["j05"] and acc["nonkill"] is True
    assert acc["items"]["j05"]["stratum"] == "import" and acc["items"]["j05"]["probe"] is True
    assert acc["items"]["j05"]["diagnostic_s"] >= 0 and acc["items"]["j00"]["probe"] is False
    assert set(acc["by_stratum"]) == {"import", "runtime"}
    assert "killed" not in [st["labels"]["j05"]] and rep["screening"]["labels"]["j05"] == "error"


@pytest.mark.parametrize("src,it,ctx", [
    ("A = (1,)\nB = (2,)\n\n\nclass K:\n    X = A + B\n",
     item("j05", "core/ReplaceBinaryOperator_Add_BitAnd", 0, (6, 10), (6, 11)),
     {"kind": "class", "qualname": "K", "firstlineno": 5}),
    ("A = (1,)\nB = (2,)\n\n\ndef g(a=A + B):\n    return a\n",
     item("j05", "core/ReplaceBinaryOperator_Add_BitAnd", 0, (5, 10), (5, 11)),
     {"kind": "module", "qualname": "<module>", "firstlineno": 1}),
    ("A = (1,)\nB = (2,)\n\n\nclass K:\n    def m(self, a=A + B):\n        return a\n",
     item("j05", "core/ReplaceBinaryOperator_Add_BitAnd", 0, (6, 20), (6, 21)),
     {"kind": "class", "qualname": "K", "firstlineno": 5}),
])
def test_P3_class_body_and_def_defaults_in_the_enclosing_scope_are_genuine(tmp_path, src, it, ctx):
    toy(tmp_path, items=genuine_items(special={"j05": it}), module_src=src, completion=False)
    rep = psession(tmp_path, {"j05": {"errors": [{"nodeid": "research/s1/s1_tests/test_x.py",
                                                   "longrepr": f"x\n{E_LINE}"}]}})
    assert rep["stop"] is None, rep["stop"]
    d = json.loads((job_dir(tmp_path) / "dg" / "disposition.json").read_text(encoding="utf-8"))
    assert d["context"] == ctx, d["context"]


# ====================================================================== qualification: anything else halts as today
def _halts_as_today(tmp_path, rep, calls, log):
    assert_halted_at(tmp_path, rep, calls)
    rec = policy_rec(tmp_path)
    assert rec["halt"] is True and rec["reason"] == CANON, rec
    assert rec["diagnosis"]["qualifying"] is False and rec["diagnosis"]["why"], rec["diagnosis"]
    assert log == [] and not (job_dir(tmp_path) / "dg").exists(), "no diagnosis child for a non-qualifying item"
    assert state(tmp_path)["stop_reason"] == f"policy_halt:{CANON}: j05"
    return rec["diagnosis"]["why"]


@pytest.mark.parametrize("case,spec,why", [
    ("collection_plus_a_call", {"nodes_edit": lambda n: n.update(phases={"t::a": {"call": "passed"}})}, "phases"),
    ("selected_nodes", {"nodes_edit": lambda n: n.update(selected=["t::a"])}, "selected"),
    ("call_exc", {"nodes_edit": lambda n: n.update(call_exc={"t::a": "X"})}, "call_exc"),
    ("target_imported", {"nodes_edit": lambda n: n.update(imports={"s1_x": "C:/x/s1_x.py"})}, "imports"),
    ("internal_error", {"nodes_edit": lambda n: n.update(internal_error=True)}, "internal_error"),
    ("extra_nodes_key", {"nodes_edit": lambda n: n.update(extra=1)}, "keys"),
    ("missing_nodes_key", {"nodes_edit": lambda n: n.pop("phases")}, "keys"),
    ("phases_wrong_type", {"nodes_edit": lambda n: n.update(phases=[])}, "phases"),
    ("no_nodes_record", {"write_nodes": False}, "nodes"),
    ("wrong_job", {"guard_edit": lambda s: s.update(job_id="j99")}, "job_id"),
    ("wrong_attempt", {"guard_edit": lambda s: s.update(attempt="0" * 32)}, "attempt"),
    ("raw_attempt_mismatch", {"raw_edit": lambda r: r.update(guard_attempt="f" * 32)}, "guard_attempt"),
    ("nodes_sha_mismatch", {"guard_edit": lambda s: s.update(nodes_record_sha256="0" * 64)}, "nodes_record_sha256"),
    ("guard_cleanup_unverified", {"guard_edit": lambda s: s.update(cleanup={"verified": False})}, "cleanup"),
    ("guard_status_other", {"guard_edit": lambda s: s.update(status="error:setup")}, "status"),
    ("foreign_guard_bytes", {"guard_edit": lambda s: s.update(guard_sha256="0" * 64)}, "guard_sha256"),
    ("mixed_collection_errors", {"errors": [
        {"nodeid": "a.py", "longrepr": f"x\n{E_LINE}"},
        {"nodeid": "b.py", "longrepr": "x\nE   ImportError: cannot import name 'q'"}]}, "mixed"),
    ("collect_errors_differ_from_sidecar", {"guard_edit": lambda s: s.update(collect_errors=[])}, "collect_errors"),
    ("no_e_line", {"errors": [{"nodeid": "a.py", "longrepr": "no exception line here"}]}, "E-line"),
])
def test_P5_a_non_qualifying_collection_error_halts_exactly_as_today_with_zero_next_call(tmp_path, case, spec, why):
    ptoy(tmp_path)
    calls, log = [], []
    rep = psession(tmp_path, {"j05": spec}, calls=calls, log=log)
    got = _halts_as_today(tmp_path, rep, calls, log)
    assert why in got, (case, got)


def test_P5_a_malformed_sidecar_halts_as_today(tmp_path):
    ptoy(tmp_path)

    def broken(jd, job):
        r = collection_error(jd, job)
        (jd / "guard.json").write_text("{not json", encoding="utf-8")
        return r
    calls, log = [], []
    rep = psession(tmp_path, {"j05": broken}, calls=calls, log=log)
    assert "guard.json" in _halts_as_today(tmp_path, rep, calls, log)


def test_P5_runtime_stratum_ids_never_get_a_diagnosis(tmp_path):
    ptoy(tmp_path, special={}, runtime=19)                        # j05 .. j23 sit in f's body
    calls, log = [], []
    rep = psession(tmp_path, {"j05": {}}, calls=calls, log=log)
    assert "not an eligible" in _halts_as_today(tmp_path, rep, calls, log)


def test_P5_completion_stage_errors_never_get_a_diagnosis(tmp_path):
    toy(tmp_path, items=genuine_items(special={"j05": GENUINE_ITEM}), module_src=GENUINE + RUNTIME_TAIL)
    calls, log = [], []

    def make(cfg):
        base = cr_factory({("c1", "j03"): {}}, calls)(cfg)

        def seam(it, copy_root, jd):
            if "/completion/" not in " ".join(map(str, cfg.guard_args)) and it["job_id"] == "j03":
                calls.append(("screen", "j03"))
                return dict(CLEAN_SURV)
            return base(it, copy_root, jd)
        seam.synthetic = True
        return seam
    rep = _run(tmp_path / "repo", tmp_path / "work", "s1_x/a", _test_exec_factory=make,
               _test_diag_runner=runner_spy(log))
    assert rep["stop"]["kind"] == "policy_halt" and rep["stop"]["job"] == "j03", rep["stop"]
    assert log == [] and not list((tmp_path / "work").rglob("dg")), "no diagnosis in completion"


# ====================================================================== diagnosis failures HALT before the next item
def _diag_halt(tmp_path, rep, calls, why_part):
    st = assert_halted_at(tmp_path, rep, calls)
    rec = policy_rec(tmp_path)
    assert rec["halt"] is True and rec["reason"].startswith("diagnosis:") and why_part in rec["reason"], rec["reason"]
    assert st["stop_reason"].startswith("policy_halt:diagnosis:"), st["stop_reason"]
    assert st["labels"]["j05"] == "error" and st["results"]["j05"]["guard_status"] == "error:collection"
    assert "driver_disposition" not in st["results"]["j05"]
    halt = json.loads((job_dir(tmp_path) / "dg" / "diagnosis_halt.json").read_text(encoding="utf-8"))
    assert why_part in halt["why"], halt
    assert not (job_dir(tmp_path) / "dg" / "disposition.json").exists()
    assert rep["stop"]["kind"] == "policy_halt"
    return halt


def test_P1_a_failing_unmutated_control_halts_and_the_mutated_child_never_starts(tmp_path):
    src = "import s1_missing_dependency_toy\n" + GENUINE
    special = {"j05": item("j05", "core/ReplaceBinaryOperator_Add_BitAnd", 0, (5, 19), (5, 20))}
    toy(tmp_path, items=genuine_items(special=special), module_src=src, completion=False)
    calls, log = [], []
    rep = psession(tmp_path, {"j05": {}}, calls=calls, log=log)
    _diag_halt(tmp_path, rep, calls, "control")
    assert [c["mode"] for c in log] == ["control"], "child 2 never starts"
    assert not (job_dir(tmp_path) / "dg" / "m").exists()


@pytest.mark.parametrize("mode", ["control", "mutated"])
@pytest.mark.parametrize("bad", ["timed_out", "cleanup", "rc"])
def test_P2_a_probe_timeout_or_cleanup_failure_halts(tmp_path, mode, bad):
    ptoy(tmp_path)
    calls, log = [], []

    def fake(m, cmd, kw):
        if m != mode:
            return None
        r = cr_guard.run_contained(cmd, **kw)
        if bad == "timed_out":
            r.update(timed_out=True, rc=None)
        elif bad == "cleanup":
            r["cleanup"] = dict(r["cleanup"], verified=False)
        else:
            r["rc"] = 1
        return r
    rep = psession(tmp_path, {"j05": {}}, calls=calls, log=log, fake=fake)
    _diag_halt(tmp_path, rep, calls, mode)
    assert [c["mode"] for c in log] == (["control"] if mode == "control" else ["control", "mutated"])


@pytest.mark.parametrize("mode", ["control", "mutated"])
@pytest.mark.parametrize("content", ["{not json", json.dumps({"schema": "other"}), None])
def test_P5_a_malformed_or_missing_probe_record_halts(tmp_path, mode, content):
    ptoy(tmp_path)
    calls, log = [], []

    def fake(m, cmd, kw):
        if m != mode:
            return None
        out = Path(cmd[cmd.index("--out") + 1])
        if content is not None:
            out.write_text(content, encoding="utf-8")
        return {"rc": 0, "timed_out": False, "cleanup": {"verified": True}, "elapsed_s": 0.1}
    rep = psession(tmp_path, {"j05": {}}, calls=calls, log=log, fake=fake)
    _diag_halt(tmp_path, rep, calls, mode)


def test_P3_a_target_frame_then_a_real_dependency_error_halts(tmp_path):
    src = "import s1_dep\n\nY = s1_dep.g(5)\n"
    special = {"j05": item("j05", "core/NumberReplacer", 0, (3, 13), (3, 14))}
    toy(tmp_path, items=genuine_items(special=special), module_src=src, completion=False,
        extra={"research/s1/s1_dep.py": "def g(x):\n    return [0, 1, 2, 3, 4, 5][x]\n"})
    calls, log = [], []
    rep = psession(tmp_path, {"j05": {"errors": [{"nodeid": "t.py", "longrepr": "x\nE   IndexError: x"}]}},
                   calls=calls, log=log)
    halt = _diag_halt(tmp_path, rep, calls, "innermost")
    assert halt["frames_tail"][-1]["rel"] == "research/s1/s1_dep.py", halt


def test_P3_a_mutation_whose_failure_does_not_overlap_its_span_halts(tmp_path):
    src = "N = 2\nL = [0, 1, 2]\nY = L[N]\n"
    special = {"j05": item("j05", "core/NumberReplacer", 0, (1, 4), (1, 5))}
    toy(tmp_path, items=genuine_items(special=special), module_src=src, completion=False)
    calls, log = [], []
    rep = psession(tmp_path, {"j05": {"errors": [{"nodeid": "t.py", "longrepr": "x\nE   IndexError: list index"}]}},
                   calls=calls, log=log)
    _diag_halt(tmp_path, rep, calls, "overlap")


def test_P3_a_mutant_that_imports_clean_halts_whatever_the_forged_e_text_says(tmp_path):
    """Forged E / trace text: the sidecar text claims the genuine TypeError at the target, but the re-applied mutant
    imports clean - the rendered text is never evidence."""
    src = "X = 1 + 2\n"
    special = {"j05": item("j05", "core/ReplaceBinaryOperator_Add_BitAnd", 0, (1, 6), (1, 7))}
    toy(tmp_path, items=genuine_items(special=special), module_src=src, completion=False)
    calls, log = [], []
    rep = psession(tmp_path, {"j05": {}}, calls=calls, log=log)
    _diag_halt(tmp_path, rep, calls, "imported")


def test_P3_an_unrelated_exception_class_in_the_original_collection_halts(tmp_path):
    ptoy(tmp_path)
    calls, log = [], []
    rep = psession(tmp_path, {"j05": {"errors": [{"nodeid": "t.py", "longrepr": "x\nE   ValueError: forged"}]}},
                   calls=calls, log=log)
    _diag_halt(tmp_path, rep, calls, "inconsistent")


def test_A2_a_barrier_refusal_halts(tmp_path, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "f.txt"
    src = f"if 1 == 2:\n    open(r'{outside}', 'w')\n"
    special = {"j05": item("j05", "core/ReplaceComparisonOperator_Eq_NotEq", 0, (1, 5), (1, 7))}
    toy(tmp_path, items=genuine_items(special=special), module_src=src, completion=False)
    calls, log = [], []
    rep = psession(tmp_path, {"j05": {"errors": [{"nodeid": "t.py", "longrepr": "x\nE   BarrierRefusal: x"}]}},
                   calls=calls, log=log)
    halt = _diag_halt(tmp_path, rep, calls, "barrier")
    assert not outside.exists()
    # fix round 1 (A2): the refusal halts on its own trusted reason, before any frame is read as an origin
    assert halt["why"] == "mutated:barrier_refusal" and halt["facts"]["refusals"][0]["event"] == "open", halt


def test_P3_a_diagnosis_copy_whose_source_differs_from_the_pin_halts(tmp_path):
    root, _ = ptoy(tmp_path)

    def drift(kind, job):
        if job == "j05":
            p = root / MOD_REL
            p.write_text(p.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
    calls, log = [], []
    rep = _run(root, tmp_path / "work", "s1_x/a", _test_exec_factory=cr_factory({"j05": {}}, calls, on_call=drift),
               _test_diag_runner=runner_spy(log))
    st = state(tmp_path)
    # fix round 2 (M5): only the diagnosis path can fire on this drift - pin its exact reason
    assert st["stop_reason"] == "policy_halt:diagnosis:source:src_root_not_pinned: j05", st["stop_reason"]
    assert log == [], "no child on a copy that is not the pinned source"
    assert [j for _, j in calls] == [f"j{i:02d}" for i in range(6)]
    assert rep["stop"] is not None


def test_P3_a_spec_whose_span_is_not_where_cr_mutates_halts(tmp_path):
    """The item says the SECOND + but occurrence 0 mutates the first: the change is not inside the allowed span."""
    special = {"j05": item("j05", "core/ReplaceBinaryOperator_Add_BitAnd", 0, (4, 33), (4, 34))}
    toy(tmp_path, items=genuine_items(special=special), module_src=GENUINE, completion=False)
    calls, log = [], []
    rep = psession(tmp_path, {"j05": {}}, calls=calls, log=log)
    _diag_halt(tmp_path, rep, calls, "localized")


# ====================================================================== the gate and its helpers, unit-level
def _frame(rel=MOD_REL, name="<module>", qual="<module>", first=1, flags=0, pos=(4, 4, 8, 46), agree=True,
           sha_="P", probe=False):
    return {"rel": rel, "co_name": name, "co_qualname": qual, "co_firstlineno": first, "co_flags": flags,
            "position": list(pos) if pos is not None else None, "positions_agree": agree, "file_sha256": sha_,
            "is_probe": probe, "realpath": "x", "filename": "x", "tb_lasti": 10, "tb_lineno": 4}


def _rec(frames, qual="TypeError", module="builtins", refusals=()):
    return {"schema": "a3-t15cp2-probe/1", "mode": "mutated", "stage": "done", "imported": False,
            "barrier": {"installed": True, "refusals": list(refusals)},
            "exception": {"qualname": qual, "module": module, "frames": frames}}


POST = GENUINE.replace("SLOT_KINDS + STAGE", "SLOT_KINDS & STAGE")


def _gate(rec, *, pre=GENUINE, post=POST, start=(4, 19), end=(4, 20), names=("TypeError",)):
    return _fn("gate")(rec, module_rel=MOD_REL, pre_text=pre, post_text=post, post_sha="P", start=list(start),
                       end=list(end), collect_names=list(names))


def test_gate_the_genuine_record_passes():
    ok, info = _gate(_rec([_frame(rel=None, name="import_module"), _frame()]))
    assert ok is True and info["overlap"] is True, info


@pytest.mark.parametrize("frames,why", [
    ([_frame(), _frame(rel=None, name="helper", qual="helper", flags=3)], "innermost"),
    ([_frame(), _frame(rel="research/s1/s1_dep.py", name="g", qual="g", flags=3), _frame()], "dependency"),
    ([_frame(rel=None, probe=True, name="hook", qual="make_barrier.<locals>.hook", flags=3)], "innermost"),
    ([_frame(name="f", qual="f", flags=3)], "context"),
    ([_frame(name="K", qual="K", flags=3)], "context"),
    ([_frame(pos=None)], "position"),
    ([_frame(pos=(4, None, 8, 46))], "position"),
    ([_frame(pos=(99, 99, 0, 1))], "position"),
    ([_frame(pos=(4, 4, 8, 400))], "position"),
    ([_frame(agree=False)], "position"),
    ([_frame(pos=(1, 1, 0, 5))], "overlap"),
    ([_frame(sha_="other")], "sha"),
    ([], "frames"),
])
def test_gate_rejected_shapes(frames, why):
    ok, info = _gate(_rec(frames))
    assert ok is False and why in info["why"], info


def test_gate_class_body_versus_a_runtime_method_frame_with_the_same_lineno():
    pre = "A = (1,)\nB = (2,)\n\n\nclass K:\n    X = A + B; m = lambda self: A + B\n"
    post = pre.replace("X = A + B", "X = A & B")
    body = _frame(name="K", qual="K", first=5, pos=(6, 6, 8, 13))
    ok, info = _gate(_rec([_frame(), body]), pre=pre, post=post, start=(6, 10), end=(6, 11))
    assert ok is True, info
    runtime = _frame(name="<lambda>", qual="K.<lambda>", first=6, flags=3, pos=(6, 6, 8, 13))
    ok, info = _gate(_rec([_frame(), body, runtime]), pre=pre, post=post, start=(6, 10), end=(6, 11))
    assert ok is False and ("innermost" in info["why"] or "context" in info["why"]), info     # fix round 2 (M4)
    named_like = _frame(name="K", qual="K", first=6, flags=3, pos=(6, 6, 8, 13))
    ok, info = _gate(_rec([_frame(), named_like]), pre=pre, post=post, start=(6, 10), end=(6, 11))
    assert ok is False and "context" in info["why"], info


def test_gate_a_syntax_error_halts():
    ok, info = _gate(_rec([_frame(rel=None, name="<frozen>")], qual="SyntaxError"))
    assert ok is False and "syntax" in info["why"], info


def test_gate_a_barrier_refusal_halts_even_when_caught():
    ok, info = _gate(_rec([_frame()], refusals=[{"event": "open", "detail": "x"}]))
    assert ok is False and "barrier" in info["why"], info


def test_gate_the_collection_exception_class_must_match():
    ok, info = _gate(_rec([_frame()]), names=("ValueError",))
    assert ok is False and "inconsistent" in info["why"], info
    ok, info = _gate(_rec([_frame()], qual="E", module="pkg.mod"), names=("pkg.mod.E",))
    assert ok is True, info


@pytest.mark.parametrize("src,start,ctx", [
    (GENUINE, (4, 19), {"kind": "module", "qualname": "<module>", "firstlineno": 1}),
    ("class A:\n    class B:\n        X = 1 + 2\n", (3, 14), {"kind": "class", "qualname": "A.B", "firstlineno": 2}),
    ("def d(c):\n    return c\n\n\n@d\nclass K:\n    X = 1 + 2\n", (7, 10),
     {"kind": "class", "qualname": "K", "firstlineno": 5}),
    ("class K(object if 1 + 2 else int):\n    pass\n", (1, 20),
     {"kind": "module", "qualname": "<module>", "firstlineno": 1}),
    ("def f(a=1 + 2):\n    return a\n", (1, 10), {"kind": "module", "qualname": "<module>", "firstlineno": 1}),
    ("def f():\n    return 1 + 2\n", (2, 13), {"kind": "runtime"}),
    ("def f():\n    def g(a=1 + 2):\n        return a\n", (2, 14), {"kind": "runtime"}),
    ("F = lambda: 1 + 2\n", (1, 14), {"kind": "runtime"}),
    ("X = tuple(a + 1 for a in (1,))\n", (1, 12), {"kind": "generator"}),
    ("X = tuple(a for a in (1, 1 + 2))\n", (1, 27), {"kind": "module", "qualname": "<module>", "firstlineno": 1}),
])
def test_mutation_context_follows_the_actual_ast(src, start, ctx):
    got = _fn("mutation_context")(src, list(start))
    assert {k: got.get(k) for k in ctx} == ctx, got


@pytest.mark.parametrize("post,ok_,why", [
    (POST, True, None),
    (GENUINE, False, "unchanged"),
    (POST.replace("('a', 'b')", "('a',  'b')"), False, "localized"),
    (POST + "# extra\n", False, "localized"),
    (GENUINE.replace("+ STAGE", "&\n STAGE"), False, "newline"),
    (GENUINE.replace("SLOT_KINDS + STAGE_KINDS + TRIAL", "SLOT_KINDS & STAGE_KINDS & TRIAL"), False, "localized"),
])
def test_localize_one_change_inside_the_span_only(post, ok_, why):
    ok, info = _fn("localize")(GENUINE, post, [4, 19], [4, 20])
    assert ok is ok_, info
    if why:
        assert why in info["why"], info
    else:
        assert info["post_span"] == [[4, 19], [4, 20]], info


# ====================================================================== P2: admission, budgets, no fresh clock
class Clock:
    """A settable session clock: the session start is 0; ``now`` is what every later reading returns."""

    def __init__(self):
        self.calls, self.now = 0, 0.0

    def __call__(self):
        self.calls += 1
        return 0.0 if self.calls == 1 else self.now


@pytest.mark.parametrize("remaining,admitted", [(644.0, False), (645.0, True), (646.0, True)])
def test_P2_the_admission_fence_is_exact_and_refuses_before_the_cr_item_starts(tmp_path, remaining, admitted):
    ptoy(tmp_path)                                               # j00 is an eligible (import-stratum) filler
    clock = Clock()
    clock.now = 10800.0 - remaining
    calls, log = [], []
    rep = psession(tmp_path, {}, calls=calls, log=log, clock=clock)
    st = state(tmp_path)
    if admitted:
        assert calls[:1] == [("screen", "j00")] and st["labels"].get("j00") == "killed", st["stop_reason"]
    else:
        assert calls == [] and st["stop_reason"].startswith("policy_halt:admission_fence"), st["stop_reason"]
        assert rep["stop"]["kind"] == "fence" and st["quarantined"] == ["j00"], rep["stop"]
        assert st["pending"] == [f"j{i:02d}" for i in range(1, 24)] and st["labels"]["j00"] is None
        rec = policy_rec(tmp_path, "j00")
        assert rec["reason"].startswith("admission_fence") and rec["remaining_s"] == remaining
        assert rec["reservation_s"] == 645.0


def test_P2_a_non_eligible_item_keeps_the_405_fence(tmp_path):
    ptoy(tmp_path, special={}, runtime=24)                       # every item in the runtime stratum
    clock = Clock()
    clock.now = 10800.0 - 405.0
    calls = []
    psession(tmp_path, {}, calls=calls, clock=clock)
    assert calls[:1] == [("screen", "j00")], "405 s is enough for a runtime-stratum item"


def test_P2_the_reservation_is_the_fence_plus_two_bounded_children():
    drv = _drv()
    assert _fn("PROBE_DEADLINE_S") == 60 and _fn("DIAG_IO_MARGIN_S") == 15
    assert _fn("admission_reservation_s")() == cr_coord.fence_s() + 2 * (60 + cr_guard.BUDGETS["cleanup_reserve_s"] + 15)
    assert _fn("admission_reservation_s")() == 645.0 and _fn("diagnosis_reserve_s")() == 240.0


@pytest.mark.parametrize("left_after_cr,ran", [(239.0, False), (240.0, True)])
def test_P2_the_remaining_budget_after_cr_must_still_hold_both_children(tmp_path, left_after_cr, ran):
    ptoy(tmp_path)
    clock = Clock()
    clock.now = 1000.0
    calls, log = [], []

    def step():
        if calls and calls[-1][1] == "j05":
            clock.now = 10800.0 - left_after_cr
    rep = _run(tmp_path / "repo", tmp_path / "work", "s1_x/a",
               _test_exec_factory=cr_factory({"j05": {}}, calls, clock_step=step),
               _test_diag_runner=runner_spy(log), clock=clock)
    if ran:
        assert [c["mode"] for c in log] == ["control", "mutated"], rep["stop"]
    else:
        assert log == [] and policy_rec(tmp_path)["reason"].startswith("diagnosis:budget"), policy_rec(tmp_path)
        assert rep["stop"]["kind"] == "fence"


def test_P2_child_two_needs_its_own_bounded_reserve(tmp_path):
    ptoy(tmp_path)
    clock = Clock()
    clock.now = 1000.0
    calls, log = [], []

    def fake(m, cmd, kw):
        if m == "control":
            r = cr_guard.run_contained(cmd, **kw)
            clock.now = 10800.0 - 119.0                       # less than one child + cleanup + IO left
            return r
        return None
    rep = psession(tmp_path, {"j05": {}}, calls=calls, log=log, fake=fake, clock=clock)
    assert [c["mode"] for c in log] == ["control"], log
    assert policy_rec(tmp_path)["reason"].startswith("diagnosis:budget") and rep["stop"]["kind"] == "fence"


# ====================================================================== interruption at each stage
@pytest.mark.parametrize("stage", ["cr", "control", "mutated"])
def test_P5_an_interrupt_at_each_stage_keeps_write_once_records_and_re_raises(tmp_path, stage):
    ptoy(tmp_path)
    calls, log = [], []

    def fake(m, cmd, kw):
        if m == stage:
            raise KeyboardInterrupt(f"stop in {m}")
        return None

    def cr(jd, job):
        if stage == "cr":
            raise KeyboardInterrupt("stop in cr")
        return collection_error(jd, job)
    with pytest.raises(KeyboardInterrupt):
        psession(tmp_path, {"j05": cr}, calls=calls, log=log, fake=fake)
    croot = tmp_path / "work/s1_x__a"
    rep = json.loads((croot / "report_session-000.json").read_text(encoding="utf-8"))
    assert rep["stop"]["kind"] == "interrupted", rep["stop"]
    rec = policy_rec(tmp_path)
    assert rec["halt"] is True, rec
    if stage == "mutated":
        assert (job_dir(tmp_path) / "dg" / "control.json").is_file(), "the control record survives"
    assert [j for _, j in calls][-1] == "j05"


# ====================================================================== the external plan
def _plan(tmp_path):
    return tmp_path / "plan.json"


def _tamper(tmp_path, fn):
    p = _plan(tmp_path)
    plan = json.loads(p.read_text(encoding="utf-8"))
    fn(plan)
    p.write_text(json.dumps(plan), encoding="utf-8")


@pytest.mark.parametrize("case,fn,msg", [
    ("driver_sha", lambda p: p["driver"].update(sha256="0" * 64), "driver"),
    ("probe_sha", lambda p: p["probe"].update(sha256="0" * 64), "probe"),
    ("policy_version", lambda p: p["driver"].update(policy_version="x"), "policy"),
    ("schema", lambda p: p.update(schema="x"), "schema"),
    ("manifest", lambda p: p["source"]["manifest"].update(sha256="0" * 64), "manifest"),
    ("preflight_record", lambda p: p["source"]["preflight_records"]["records"].update(
        {next(iter(p["source"]["preflight_records"]["records"])): "0" * 64}), "pre-flight"),
    ("preflight_list", lambda p: p["source"]["preflight_records"].update(list_sha256="0" * 64), "pre-flight"),
    ("inventory", lambda p: p["configs"][0].update(inventory_sha256="0" * 64), "inventory"),
    ("filtered", lambda p: p["configs"][0].update(filtered_sha256="0" * 64), "filtered"),
    ("kept_order", lambda p: p["configs"][0].update(kept_order_sha256="0" * 64), "kept"),
    ("batch", lambda p: p["configs"][0].update(calibration_batch=p["configs"][0]["calibration_batch"][::-1]), "batch"),
    ("eligible", lambda p: p["configs"][0].update(eligible=p["configs"][0]["eligible"][:-1]), "eligible"),
    ("strata", lambda p: p["configs"][0]["strata"]["import"].update(count=999), "strata"),
    ("classifier", lambda p: p["classifier"].update(source_sha256="0" * 64), "classifier"),
    ("bounds", lambda p: p["bounds"].update(admission_reservation_s=405), "bounds"),
    ("universe", lambda p: p["scope"].update(universe_kept_total=1), "universe"),
    ("eligible_total", lambda p: p.update(eligible_total=99), "eligible"),
    ("predecessor", lambda p: p["predecessor"]["files"].update(
        {next(iter(p["predecessor"]["files"])): "0" * 64}), "predecessor"),
    ("planned_root", lambda p: p.update(planned_root="C:/elsewhere"), "planned"),
    ("missing_config", lambda p: p.update(configs=[]), "config"),
])
def test_plan_any_binding_mismatch_is_refused_before_anything(tmp_path, case, fn, msg):
    ptoy(tmp_path)
    _tamper(tmp_path, fn)
    calls, log = [], []
    with pytest.raises(cr_coord.CoordError, match=r"sampling plan") as ei:
        psession(tmp_path, {"j05": {}}, calls=calls, log=log)
    assert msg in str(ei.value), (case, str(ei.value))
    assert calls == [] and not (tmp_path / "work").exists()


def test_plan_the_work_root_may_never_be_the_predecessor_root(tmp_path):
    ptoy(tmp_path)
    pred = json.loads(_plan(tmp_path).read_text(encoding="utf-8"))["predecessor"]["root"]
    _tamper(tmp_path, lambda p: p.update(planned_root=str(Path(pred).parent)))
    with pytest.raises(cr_coord.CoordError, match=r"sampling plan.*predecessor"):
        _run(tmp_path / "repo", Path(pred).parent, "s1_x/a", _test_exec_factory=cr_factory({}, []))


def test_plan_the_calibration_batch_is_the_plans_and_is_recorded(tmp_path):
    ptoy(tmp_path)
    calls = []
    rep = psession(tmp_path, {}, calls=calls)
    plan = json.loads(_plan(tmp_path).read_text(encoding="utf-8"))
    assert rep["calibration_batch"] == plan["configs"][0]["calibration_batch"]
    assert rep["plan"]["sha256"] == sha(_plan(tmp_path)) and rep["plan"]["eligible"] == plan["configs"][0]["eligible"]
    assert rep["schema"] == _fn("SCHEMA") and rep["policy_version"] == _fn("POLICY_VERSION")
    assert rep["probe_sha256"] == sha(_fn("PROBE_PATH"))


def test_plan_selection_rule_is_the_two_strata_midpoint_rule():
    drv = _drv()
    assert _fn("allocate")(62, 720) == (2, 22) and _fn("allocate")(0, 30) == (0, 24) and _fn("allocate")(30, 30) == (24, 0)
    assert _fn("allocate")(1, 720) == (1, 23) and _fn("allocate")(700, 720) == (23, 1)
    assert _fn("midpoints")(list(range(10)), 3) == [1, 5, 8]               # floor((2j+1) N / (2n))
    assert _fn("midpoints")(list(range(5)), 0) == []


# ====================================================================== derive-cap never from import errors alone
def test_derive_cap_refuses_a_calibration_without_one_clean_measurement():
    drv = _drv()
    assert _fn("cap_measurement_check")({"labels": {"a": "error", "b": "error"}}) is not None
    # fix round 2 (M6): an import-invalid candidate is excluded, and any OTHER non-clean label is no measurement
    ok = {"labels": {"a": "error", "b": "killed"}, "batch": ["a", "b"],
          "results": {"a": {"driver_disposition": "import-invalid-candidate"}, "b": {}}}
    assert _fn("cap_measurement_check")(ok) is None
    assert _fn("cap_measurement_check")({"labels": {"a": "error", "b": "killed"}}) is not None


# ====================================================================== the real plan file (read-only)
REAL_SRC = Path("C:/cr15c/src")
DRAFT = Path("C:/Users/gl450/.coordination/trading_app/t15c_import_halt_review_20261117/sampling_v2_draft.json")


@pytest.mark.skipif(not (REAL_SRC.is_dir() and DRAFT.is_file()), reason="the retained archive is not on this host")
def test_the_real_plan_file_equals_the_draft_and_binds_this_driver_and_probe():
    drv = _drv()
    plan = json.loads(_fn("PLAN_PATH").read_text(encoding="utf-8"))
    draft = {c["config"]: c["calibration_batch"] for c in json.loads(DRAFT.read_text(encoding="utf-8"))["configs"]}
    got = {c["config"]: c["calibration_batch"] for c in plan["configs"]}
    assert got == draft and len(got) == 12
    assert sum(len(c["eligible"]) for c in plan["configs"]) == plan["eligible_total"] == 23
    assert plan["scope"]["universe_kept_total"] == 6318 and plan["scope"]["all_in_scope"] is True
    assert plan["driver"]["sha256"] == sha(drv.__file__) and plan["probe"]["sha256"] == sha(_fn("PROBE_PATH"))
    assert plan["source"]["manifest"]["sha256"].startswith("819ca0fe") and plan["source"]["manifest"]["entries"] == 1268
    assert plan["source"]["preflight_records"]["list_sha256"].startswith("bf4b0889")
    assert len(plan["source"]["preflight_records"]["records"]) == 42
    assert plan["planned_root"] == "C:/cr15c/w2" and plan["predecessor"]["root"] == "C:/cr15c/w/s1_journal"
    assert "c03580c01cb54316892042b67eb9f7a8" not in {j for v in got.values() for j in v}


@pytest.mark.skipif(not (REAL_SRC.is_dir() and DRAFT.is_file()), reason="the retained archive is not on this host")
def test_the_driver_validates_the_real_plan_for_every_config_read_only():
    """Read-only: validate_plan recomputes all 12 configs from C:/cr15c/src (bytes / JSON / AST only) and re-hashes
    the predecessor files under C:/cr15c/w; nothing is imported from, executed in or written under either."""
    drv = _drv()
    drv.load_harness(REAL_SRC, fresh=False, _test_harness_anywhere=True, _test_allow_git_src_root=True)
    plan = json.loads(_fn("PLAN_PATH").read_text(encoding="utf-8"))
    for c in plan["configs"]:
        _, entry, summary = drv.validate_plan(_fn("PLAN_PATH"), REAL_SRC, c["config"])
        assert entry["calibration_batch"] == c["calibration_batch"] and summary["eligible"] == c["eligible"]
    for bad in ("C:/cr15c/w", "C:/cr15c/w/s1_journal", "C:/cr15c"):
        with pytest.raises(cr_coord.CoordError, match=r"predecessor"):
            drv._check_roots(plan, summary, Path(bad))
    drv._check_roots(plan, summary, Path("C:/cr15c/w2"))
    got = drv.protected_paths(REAL_SRC)          # fix round 1: AST-only check of the S1 constants, never imported
    assert got["verified_from_source"] == {"MAILBOX": True, "HMAC_KEY": True, "LIVE_DB": True}, got


# ===================================================================================== fix round 1 (Codex amendments)
SENTINEL_SRC = ("from pathlib import Path\nA = 1 + 1\nB = 2 + 2\n"
                "if A != 2:\n    (Path(__file__).parent / 'SENTINEL').write_text('imported', encoding='utf-8')\n")


def stoy(tmp_path, *, op="core/ReplaceBinaryOperator_Add_Sub", line=3, src=SENTINEL_SRC, **kw):
    special = {"j05": item("j05", op, 0, (line, 6), (line, 7))}
    return toy(tmp_path, items=genuine_items(special=special), module_src=src, completion=False, **kw)


def sentinel(tmp_path):
    return job_dir(tmp_path) / "dg" / "m" / "research/s1/SENTINEL"


SENT_ERR = {"errors": [{"nodeid": "t.py", "longrepr": "x\nE   TypeError: x"}]}


def test_fix1_A3_an_out_of_span_mutation_halts_before_import_and_the_sentinel_stays_absent(tmp_path):
    stoy(tmp_path)                                         # occurrence 0 mutates line 2; the item's span is line 3
    calls, log = [], []
    rep = psession(tmp_path, {"j05": SENT_ERR}, calls=calls, log=log)
    assert not sentinel(tmp_path).exists(), "the target was never imported"
    halt = _diag_halt(tmp_path, rep, calls, "mutated:refused:not_localized")
    assert [c["mode"] for c in log] == ["control", "mutated"]
    assert halt["why"].startswith("mutated:refused")


def test_fix1_A3_a_mutation_api_exception_halts_without_import(tmp_path):
    stoy(tmp_path, op="core/NoSuchOperator", line=2)
    calls, log = [], []
    rep = psession(tmp_path, {"j05": SENT_ERR}, calls=calls, log=log)
    _diag_halt(tmp_path, rep, calls, "mutated:refused:mutation_api_exception")
    assert not sentinel(tmp_path).exists()


def test_fix1_A3_a_pre_source_mismatch_inside_the_child_halts_without_import(tmp_path):
    stoy(tmp_path, line=2)
    calls, log = [], []

    def fake(m, cmd, kw):
        if m == "mutated":
            p = Path(kw["cwd"]) / MOD_REL
            p.write_text(p.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
        return None
    rep = psession(tmp_path, {"j05": SENT_ERR}, calls=calls, log=log, fake=fake)
    _diag_halt(tmp_path, rep, calls, "mutated:refused:pre_source_mismatch")
    assert not sentinel(tmp_path).exists()


def test_fix1_A3_a_mutation_exceeding_the_child_time_budget_halts_without_import(tmp_path):
    stoy(tmp_path, line=2)                                 # a valid mutation whose import WOULD write the sentinel
    calls, log = [], []

    def fake(m, cmd, kw):
        if m == "mutated":
            return cr_guard.run_contained(cmd, **dict(kw, deadline_s=0.05))
        return None
    rep = psession(tmp_path, {"j05": SENT_ERR}, calls=calls, log=log, fake=fake)
    _diag_halt(tmp_path, rep, calls, "mutated:timed_out")
    assert not sentinel(tmp_path).exists()


@pytest.mark.parametrize("how", ["truncated", "tmp_only"])
def test_fix1_A3_an_interrupted_record_write_halts(tmp_path, how):
    ptoy(tmp_path)
    calls, log = [], []

    def fake(m, cmd, kw):
        if m != "mutated":
            return None
        r = cr_guard.run_contained(cmd, **kw)
        out = Path(cmd[cmd.index("--out") + 1])
        text = out.read_text(encoding="utf-8")
        if how == "truncated":
            out.write_text(text[: len(text) // 2], encoding="utf-8")
        else:
            out.with_name(out.name + ".tmp").write_text(text[:10], encoding="utf-8")
            out.unlink()
        return r
    rep = psession(tmp_path, {"j05": {}}, calls=calls, log=log, fake=fake)
    _diag_halt(tmp_path, rep, calls, "mutated:record_unreadable")


@pytest.mark.parametrize("tamper,why", [("post_file", "mutated:source_identity"),
                                         ("preimport_missing", "mutated:preimport"),
                                         ("preimport_edited", "mutated:preimport")])
def test_fix1_A3_the_parent_re_verifies_the_persisted_bytes_hash_and_diff(tmp_path, tamper, why):
    ptoy(tmp_path)
    calls, log = [], []

    def fake(m, cmd, kw):
        if m != "mutated":
            return None
        r = cr_guard.run_contained(cmd, **kw)
        out = Path(cmd[cmd.index("--out") + 1])
        pre = out.with_name(out.stem + ".preimport.json")
        if tamper == "post_file":
            p = Path(kw["cwd"]) / MOD_REL
            p.write_text(p.read_text(encoding="utf-8") + "# later\n", encoding="utf-8")
        elif tamper == "preimport_missing":
            pre.unlink()
        else:
            d = json.loads(pre.read_text(encoding="utf-8"))
            d["validation"]["post_span"] = [[4, 0], [4, 1]]
            pre.write_text(json.dumps(d), encoding="utf-8")
        return r
    rep = psession(tmp_path, {"j05": {}}, calls=calls, log=log, fake=fake)
    _diag_halt(tmp_path, rep, calls, why)


def test_fix1_A2_a_protected_read_by_the_mutant_halts_and_never_reaches_a_record(tmp_path):
    prot = tmp_path / "synthetic_protected" / "mailbox.sqlite3"
    prot.parent.mkdir()
    prot.write_text("SYNTHETIC-MAILBOX-9931", encoding="utf-8")
    src = f"if 1 == 2:\n    X = open(r'{prot}').read()\n"
    special = {"j05": item("j05", "core/ReplaceComparisonOperator_Eq_NotEq", 0, (1, 5), (1, 7))}
    toy(tmp_path, items=genuine_items(special=special), module_src=src, completion=False)
    calls, log = [], []
    rep = psession(tmp_path, {"j05": SENT_ERR}, calls=calls, log=log, _test_protected=[prot])
    _diag_halt(tmp_path, rep, calls, "barrier")
    assert all(f"--protected" in c["cmd"] and str(prot) in c["cmd"] for c in log), "both children, same barrier"
    texts = [p.read_text(encoding="utf-8", errors="replace") for p in (tmp_path / "work").rglob("*.json")]
    assert texts and not any("SYNTHETIC-MAILBOX-9931" in t for t in texts)


def test_fix1_A2_the_default_protected_paths_are_the_s1_constants_and_go_to_both_children(tmp_path):
    drv = _drv()
    want = {"C:/Users/gl450/.coordination/trading_app/mailbox.sqlite3",
            "C:/Users/gl450/.coordination/trading_app/s1_receipt_hmac.key",
            "C:/Users/gl450/trading_app/backend/trading.db"}
    assert {p for p, _, _ in _fn("PROTECTED_PATHS")} == want
    ptoy(tmp_path)
    log = []
    rep = psession(tmp_path, {"j05": {}}, log=log)
    assert rep["stop"] is None, rep["stop"]
    for c in log:
        got = {c["cmd"][i + 1] for i, a in enumerate(c["cmd"]) if a == "--protected"}
        assert got == want, got
    d = json.loads((job_dir(tmp_path) / "dg" / "disposition.json").read_text(encoding="utf-8"))
    assert "cooperative" in d["barrier"]["claim"] and "not an OS sandbox" in d["barrier"]["claim"]
    assert "NOT identical pytest initialization" in d["scope"]
    assert Path(d["records"]["mutated_preimport"]["path"]).is_file()
    assert drv.protected_paths(tmp_path / "repo")["verified_from_source"] == {}, "toy: no S1 constant files"


@pytest.mark.parametrize("rel,name,value,ok", [
    ("research/s1/s1_common.py", "MAILBOX", "C:/Users/gl450/.coordination/trading_app/mailbox.sqlite3", True),
    ("research/s1/s1_common.py", "MAILBOX", "C:/elsewhere/mailbox.sqlite3", False),
    ("research/s1/s1_receipt.py", "HMAC_KEY", "C:/Users/gl450/.coordination/trading_app/other.key", False),
    ("research/s1/s1_checkpoint.py", "LIVE_DB", "C:/Users/gl450/trading_app/backend/trading.db", True),
])
def test_fix1_A2_the_protected_constants_are_checked_against_the_source_by_ast(tmp_path, rel, name, value, ok):
    drv = _drv()
    f = tmp_path / rel
    f.parent.mkdir(parents=True)
    f.write_text(f"from pathlib import Path\n{name} = Path({value!r})\n", encoding="utf-8")
    if ok:
        assert drv.protected_paths(tmp_path)["verified_from_source"] == {name: True}
    else:
        with pytest.raises(Exception, match=r"protected path"):
            drv.protected_paths(tmp_path)


# ===================================================================================== fix round 2 (task review)
def test_fix2_M6_derive_cap_excludes_import_invalid_candidates_and_records_them_with_their_cost(tmp_path):
    ptoy(tmp_path)
    _set_cap_min(tmp_path, 23)          # fix round 3 (R1): the default floor 24 refuses; a lowered plan floor allows
    rep = psession(tmp_path, {"j05": {}})
    assert rep["stop"] is None and rep["accounting"]["import_invalid_candidates"] == ["j05"], rep["stop"]
    sroot = tmp_path / "work/s1_x__a/session-000"
    st = json.loads((sroot / "batch_000_state.json").read_text(encoding="utf-8"))
    rec = _dcap(sroot, "s1_x/a")
    assert rec["measured_items"] == 23, "the import-invalid candidate is not a calibration measurement"
    meas_p = Path(rec["calibration_state"]["path"])
    assert meas_p.name == "cap_measurements.json" and meas_p.parent == sroot.parent
    meas = json.loads(meas_p.read_text(encoding="utf-8"))
    assert "j05" not in meas["batch"] and "j05" not in meas["item_s"] and len(meas["batch"]) == 23
    ex = meas["excluded_import_invalid"]["j05"]
    assert ex["item_s"] == st["item_s"]["j05"] and ex["diagnostic_s"] > 0 and ex["disposition_sha256"]
    assert meas["derived_from"] == {"path": str(sroot / "batch_000_state.json"),
                                    "sha256": sha(sroot / "batch_000_state.json")}
    assert rec["max_item_s"] == max(v for j, v in st["item_s"].items() if j != "j05")
    with pytest.raises(FileExistsError):
        _drv()._write_once(meas_p, {"again": 1})


def test_fix2_M6_a_calibration_of_import_invalid_items_only_yields_no_cap():
    assert _fn("cap_measurement_check")({"labels": {"a": "error", "b": "error"},
                                         "results": {"a": {"driver_disposition": "import-invalid-candidate"},
                                                     "b": {"driver_disposition": "import-invalid-candidate"}}})


def _dcap(session_root, config):
    return _drv().derive_cap(session_root, config, _test_harness_anywhere=True, _test_allow_git_src_root=True)


def test_fix2_M7_a_broken_diagnosis_writes_the_same_structured_halt_record(tmp_path, monkeypatch):
    ptoy(tmp_path)

    def boom(self, item, jd, facts):
        (Path(jd) / "dg").mkdir()
        raise ValueError("synthetic diagnosis bug")
    monkeypatch.setattr(_drv().Diagnoser, "diagnose", boom)
    calls = []
    rep = psession(tmp_path, {"j05": {}}, calls=calls)
    assert_halted_at(tmp_path, rep, calls)
    halt = json.loads((job_dir(tmp_path) / "dg" / "diagnosis_halt.json").read_text(encoding="utf-8"))
    assert halt["why"] == "error:ValueError" and "synthetic diagnosis bug" in halt["facts"]["error"], halt
    assert policy_rec(tmp_path)["reason"] == "diagnosis:error:ValueError"


def test_fix2_M8_an_interrupt_after_the_disposition_marks_it_superseded(tmp_path, monkeypatch):
    ptoy(tmp_path)
    real = _drv().Diagnoser.diagnose

    def then_interrupt(self, item, jd, facts):
        real(self, item, jd, facts)
        raise KeyboardInterrupt("after the disposition")
    monkeypatch.setattr(_drv().Diagnoser, "diagnose", then_interrupt)
    with pytest.raises(KeyboardInterrupt):
        psession(tmp_path, {"j05": {}})
    rec = policy_rec(tmp_path)
    disp = job_dir(tmp_path) / "dg" / "disposition.json"
    assert disp.is_file() and rec["reason"] == "diagnosis_interrupted" and rec["halt"] is True
    sup = rec["superseded_disposition"]
    assert {k: sup[k] for k in ("path", "sha256")} == {"path": str(disp), "sha256": sha(disp)}, rec
    assert "SUPERSEDED" in sup["note"]


def test_fix2_I2_a_mutant_creating_a_file_through_winapi_halts_on_the_barrier(tmp_path, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "made.txt"
    src = f"import _winapi\nif 1 == 2:\n    _winapi.CreateFile({str(outside)!r}, 0x40000000, 0, 0, 2, 0, 0)\n"
    special = {"j05": item("j05", "core/ReplaceComparisonOperator_Eq_NotEq", 0, (2, 5), (2, 7))}
    toy(tmp_path, items=genuine_items(special=special), module_src=src, completion=False)
    calls, log = [], []
    rep = psession(tmp_path, {"j05": SENT_ERR}, calls=calls, log=log)
    halt = _diag_halt(tmp_path, rep, calls, "mutated:barrier_refusal")
    assert halt["facts"]["refusals"][0]["event"] == "_winapi.CreateFile" and not outside.exists()


def test_fix2_M3_the_parent_line_model_is_pythons():
    pre = "# c\x0cd\x1ce f\nX = 1 + 2\n"
    post = pre.replace("1 + 2", "1 & 2")
    ok, info = _fn("localize")(pre, post, [2, 6], [2, 7])
    assert ok is True and info["post_span"] == [[2, 6], [2, 7]], info
    frame = _frame(pos=(2, 2, 4, 9), sha_="P")
    ok, info = _fn("gate")(_rec([frame]), module_rel=MOD_REL, pre_text=pre, post_text=post, post_sha="P",
                           start=[2, 6], end=[2, 7], collect_names=["TypeError"])
    assert ok is True and info["frame_span"] == [[2, 4], [2, 9]], info


# ===================================================================================== fix round 3 (re-review)
def _set_cap_min(tmp_path, n):
    p = tmp_path / "plan.json"
    plan = json.loads(p.read_text(encoding="utf-8"))
    plan["bounds"]["cap_min_measurements"] = n
    p.write_text(json.dumps(plan), encoding="utf-8")


def test_fix3_R1_derive_cap_refuses_below_the_plan_floor_of_clean_measurements(tmp_path):
    ptoy(tmp_path)
    plan = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    assert plan["bounds"]["cap_min_measurements"] == 24 == _fn("expected_bounds")()["cap_min_measurements"]
    rep = psession(tmp_path, {"j05": {}})
    assert rep["stop"] is None and rep["accounting"]["import_invalid_candidates"] == ["j05"]
    sroot = tmp_path / "work/s1_x__a/session-000"
    with pytest.raises(cr_coord.CoordError, match=r"23 clean .* fewer than the plan's cap_min_measurements 24"):
        _dcap(sroot, "s1_x/a")
    assert not (sroot.parent / "derived_cap.json").exists() and not (sroot.parent / "cap_measurements.json").exists()


@pytest.mark.parametrize("n,ok", [(0, False), (25, False), ("24", False), (True, False), (1, True), (24, True)])
def test_fix3_R1_the_floor_is_a_validated_plan_bound(tmp_path, n, ok):
    ptoy(tmp_path)
    _set_cap_min(tmp_path, n)
    if ok:
        assert psession(tmp_path, {})["stop"] is None
    else:
        with pytest.raises(cr_coord.CoordError, match=r"sampling plan .*cap_min_measurements"):
            psession(tmp_path, {})


def _lowered_floor_session(tmp_path):
    ptoy(tmp_path)
    _set_cap_min(tmp_path, 23)                           # a later peer ruling could lower it in the plan alone
    rep = psession(tmp_path, {"j05": {}})
    assert rep["stop"] is None
    return tmp_path / "work/s1_x__a/session-000"


def test_fix3_R1_a_lowered_plan_floor_is_honoured(tmp_path):
    sroot = _lowered_floor_session(tmp_path)
    rec = _dcap(sroot, "s1_x/a")
    assert rec["measured_items"] == 23 and Path(rec["calibration_state"]["path"]).name == "cap_measurements.json"


@pytest.mark.parametrize("how", ["missing", "edited"])
def test_fix3_N4_derive_cap_never_excludes_on_an_unverified_disposition(tmp_path, how):
    sroot = _lowered_floor_session(tmp_path)
    dp = sroot / "jobs/j05/dg/disposition.json"
    if how == "missing":
        dp.unlink()
    else:
        dp.write_text(dp.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(cr_coord.CoordError, match=r"disposition .* j05"):
        _dcap(sroot, "s1_x/a")
    assert not (sroot.parent / "cap_measurements.json").exists()


def test_fix3_N5_the_measurement_set_is_checked_against_the_state_it_records(tmp_path):
    sroot = _lowered_floor_session(tmp_path)
    _dcap(sroot, "s1_x/a")
    mp = sroot.parent / "cap_measurements.json"
    assert _fn("check_cap_measurements")(mp)["derived_from"]["sha256"] == sha(sroot / "batch_000_state.json")
    st = sroot / "batch_000_state.json"
    st.write_text(st.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(cr_coord.CoordError, match=r"cap_measurements\.json .* state"):
        _fn("check_cap_measurements")(mp)


def test_fix4_m4_the_driver_scope_discloses_the_bootstrap_preloads():
    s = _fn("PROBE_SCOPE")
    assert "sqlite3, ctypes and ctypes.wintypes" in s and "differs from collection" in s, s
