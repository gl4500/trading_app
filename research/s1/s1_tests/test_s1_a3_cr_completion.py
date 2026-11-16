"""A3 Task 15c-H (controller rulings 1-2 adopting Codex t15c_prep_review_20261116) + fix round 1 (task review
CHANGES_REQUIRED, controller rulings 1-7): completion shards with a merged label, the frozen-pool binding, the monotonic
HARD session fence (nested clock), the config-bound calibration cap, and per-attempt env/helper binding.

SYNTHETIC only: stub exec seams in tmp_path projects; no Cosmic Ray process, no S1 module is mutated. Every stub seam
returns the record SHAPE real_exec returns (label/reason/guard_status/raw/raw_timeout/exec_status/cleanup_verified/
session_sha256): the reconciled label is independent of the containment verdict, which travels in exec_status /
cleanup_verified (fix round 1, C1/C2).

Merge contract (fix-1 ruling 1): an attempt COUNTS only if it is guard-clean - not stopped, exec_status "ok", cleanup
verified, and a clean guard status matching its label (killed/killed or survived/survived). killed needs >= 1
guard-clean kill (it stops the remaining shards); survived needs EVERY required shard guard-clean and survived; any
other attempt makes the candidate "unresolved" (15d triage) unless a guard-clean kill exists; shards still pending give
"deferred"."""
import inspect
import json
import math
import os
import shutil

import pytest

import cr_coord
import cr_guard
import cr_reconcile
from test_s1_a3_cr_guard import PY, _three, sha

B = cr_guard.BUDGETS
_GUARD = {"killed": "killed", "survived": "survived", "timeout": "timeout", "error": "error:collection"}


def _res(label="survived", guard=None, **kw):
    """A record shaped exactly like real_exec's return value."""
    r = {"label": label, "reason": f"guard sidecar {guard or _GUARD.get(label, label)}",
         "guard_status": guard if guard is not None else _GUARD.get(label, label), "raw": None, "raw_timeout": False,
         "exec_status": "ok", "cleanup_verified": True, "session_sha256": "0" * 64}
    r.update(kw)
    return r


CLEAN_SURV, CLEAN_KILL = _res("survived"), _res("killed")
UNCERTAIN_SURV = _res("survived", exec_status="cleanup_uncertain", cleanup_verified=False)
UNCERTAIN_KILL = _res("killed", exec_status="cleanup_uncertain", cleanup_verified=False)
CRERR_SURV = _res("survived", exec_status="error:cr_exit_1")
GUARD_TIMEOUT = _res("timeout")
GUARD_ERROR = _res("error")


def _seam(results: dict, calls: list):
    """results: {job: real_exec-shaped record} (default: a guard-clean survivor)."""
    def seam(item, copy_root, job_dir):
        calls.append(item["job_id"])
        return dict(results.get(item["job_id"], CLEAN_SURV))
    return seam


def _screened(tmp_path, result=CLEAN_SURV):
    src, items = _three(tmp_path)
    by_id = {i["job_id"]: i for i in items}
    work = tmp_path / "w"
    cr_coord.run_batch(["j1"], by_id, batch_id="b000", src_root=src, copy_paths=["pkg"], work_root=work,
                       exec_seam=_seam({"j1": result}, []))
    return src, by_id, work


def _shards(src, per_shard: dict, extra_pool=()):
    """per_shard: {shard: record (or list of records, one per successive attempt) for j1}. Each shard's node set is
    its @argfile under src; the frozen pool (pool.json) is their union (+ extra_pool). Returns
    (specs, exec_factory, calls by shard, pool path)."""
    nodes = {n: [f"t.py::test_{n}_{i}" for i in range(2)] for n in per_shard}
    for n, ns in nodes.items():
        (src / f"{n}.txt").write_text("".join(x + "\n" for x in ns), encoding="utf-8")
        (src / f"{n}.json").write_text(json.dumps({"nodes": sorted(ns)}), encoding="utf-8")
    pool = sorted([x for ns in nodes.values() for x in ns] + list(extra_pool))
    pool_path = src.parent / "pool.json"
    pool_path.write_text(json.dumps({"nodes": pool, "nodes_sha256": cr_coord.pool_sha256(pool)}), encoding="utf-8")
    calls = {n: [] for n in per_shard}
    specs = [{"name": n, "cfg": cr_coord.CRConfig(python=PY, module_rel="pkg/m.py",
                                                  guard_args=["--control", f"{n}.json", f"@{n}.txt"],
                                                  target_module="pkg.m"),
              "copy_paths": ["pkg", f"{n}.json", f"{n}.txt"]}
             for n in per_shard]

    def factory(cfg):
        n = cfg.guard_args[1][:-5]                          # shard name from its --control file
        seq = per_shard[n] if isinstance(per_shard[n], list) else [per_shard[n]]
        rec = seq[min(len(calls[n]), len(seq) - 1)]
        return _seam({"j1": rec}, calls[n])
    return specs, factory, calls, pool_path


def _complete(src, by_id, work, specs, factory, pool_path, **kw):
    return cr_coord.run_completion("j1", by_id, specs, pool_path=pool_path, src_root=src, work_root=work,
                                   exec_factory=factory, **kw)


# --------------------------------------------------------------------------------------------- completion + merge
def test_kill_in_shard_2_of_3_settles_killed_and_stops_the_rest(tmp_path):
    src, by_id, work = _screened(tmp_path)
    specs, factory, calls, pool = _shards(src, {"c1": CLEAN_SURV, "c2": CLEAN_KILL, "c3": CLEAN_SURV})
    res = _complete(src, by_id, work, specs, factory, pool)
    assert res.get("label") == "killed", res
    assert (res.get("basis") or {}).get("killed_by") == "c2"
    assert calls == {"c1": ["j1"], "c2": ["j1"], "c3": []}, "a guard-clean kill stops the remaining shards early"
    assert [a["shard"] for a in res.get("attempts", [])] == ["c1", "c2"]
    assert res.get("not_run") == ["c3"] and res.get("screening_label") == "survived"
    assert res.get("pool_sha256") == json.loads(pool.read_text(encoding="utf-8"))["nodes_sha256"]
    rec = work / "completion" / "j1" / "completion_record.json"
    assert rec.is_file() and json.loads(rec.read_text(encoding="utf-8")) == res
    for a in res["attempts"]:
        assert a["state_sha256"] == sha(work / "completion" / "j1" / a["shard"] / f"batch_{a['shard']}_state.json")


def test_all_completion_shards_guard_clean_survived_gives_survived(tmp_path):
    src, by_id, work = _screened(tmp_path)
    specs, factory, calls, pool = _shards(src, {"c1": CLEAN_SURV, "c2": CLEAN_SURV, "c3": CLEAN_SURV})
    res = _complete(src, by_id, work, specs, factory, pool)
    assert res.get("label") == "survived", res
    assert (res.get("basis") or {}).get("all_required_survived") == ["c1", "c2", "c3"] and res.get("not_run") == []


def test_guard_error_in_one_shard_is_unresolved_with_its_exact_status(tmp_path):
    src, by_id, work = _screened(tmp_path)
    specs, factory, calls, pool = _shards(src, {"c1": CLEAN_SURV, "c2": GUARD_ERROR, "c3": CLEAN_SURV})
    res = _complete(src, by_id, work, specs, factory, pool)
    assert res.get("label") == "unresolved" and res.get("resolution") == "unresolved", res
    nk = (res.get("basis") or {}).get("nonkill") or [{}]
    assert [(n.get("shard"), n.get("label"), n.get("guard_status")) for n in nk] == \
        [("c2", "error", "error:collection")]
    assert calls == {"c1": ["j1"], "c2": ["j1"], "c3": ["j1"]}, "a guard error is not a stop: the rest still run"


def test_completion_timeout_is_unresolved_stops_with_the_rest_pending_and_blocks(tmp_path):
    src, by_id, work = _screened(tmp_path)
    specs, factory, calls, pool = _shards(src, {"c1": GUARD_TIMEOUT, "c2": CLEAN_KILL, "c3": CLEAN_SURV})
    res = _complete(src, by_id, work, specs, factory, pool)
    assert res.get("label") == "unresolved", res
    assert res.get("pending_shards") == ["c2", "c3"] and calls["c2"] == [] and calls["c3"] == []
    st = json.loads((work / "completion" / "j1" / "c1" / "batch_c1_state.json").read_text(encoding="utf-8"))
    assert st["stopped"] is True and st["stop_reason"] == "timeout: j1"
    with pytest.raises(cr_coord.CoordError, match=r"batch c1 STOPPED \(timeout: j1\) and is unresolved"):
        _complete(src, by_id, work, specs, factory, pool)
    with pytest.raises(cr_coord.CoordError, match=r"batch c1 STOPPED"):
        cr_coord.run_batch(["j3"], by_id, batch_id="b001", src_root=src, copy_paths=["pkg"], work_root=work,
                           exec_seam=_seam({}, []))


def test_resumed_completion_after_a_resolved_stop_keeps_the_earlier_nonkill(tmp_path):
    src, by_id, work = _screened(tmp_path)
    specs, factory, calls, pool = _shards(src, {"c1": GUARD_TIMEOUT, "c2": CLEAN_KILL, "c3": CLEAN_SURV})
    _complete(src, by_id, work, specs, factory, pool)
    assert (work / "completion" / "j1" / "c1" / "batch_c1_state.json").is_file(), "the c1 attempt left a state"
    cr_coord.resolve_stop(work / "completion" / "j1" / "c1", "c1", by="controller", note="c1 timeout reviewed")
    res = _complete(src, by_id, work, specs, factory, pool)
    assert res.get("label") == "killed" and calls["c1"] == ["j1"], "c1 is never re-run by a resumption"
    nk = (res.get("basis") or {}).get("nonkill") or [{}]
    assert [(n.get("shard"), n.get("label"), n.get("stop_reason")) for n in nk] == [("c1", "timeout", "timeout: j1")]
    assert len(sorted((work / "completion" / "j1").glob("completion_record*.json"))) == 2


# --- C1 / C2 (task review): containment / CR-exec failures with an otherwise clean reconciled label ----------------
def test_C1_last_shard_cleanup_uncertain_survivor_is_unresolved_never_survived(tmp_path):
    src, by_id, work = _screened(tmp_path)
    specs, factory, calls, pool = _shards(src, {"c1": CLEAN_SURV, "c2": UNCERTAIN_SURV})
    res = _complete(src, by_id, work, specs, factory, pool)
    assert res.get("label") == "unresolved", res
    nk = (res.get("basis") or {}).get("nonkill") or [{}]
    assert [(n.get("shard"), n.get("exec_status"), n.get("stop_reason")) for n in nk] == \
        [("c2", "cleanup_uncertain", "cleanup_uncertain: j1")]


def test_C1_middle_shard_cleanup_uncertain_stays_unresolved_after_its_resolution(tmp_path):
    src, by_id, work = _screened(tmp_path)
    specs, factory, calls, pool = _shards(src, {"c1": UNCERTAIN_SURV, "c2": CLEAN_SURV, "c3": CLEAN_SURV})
    r1 = _complete(src, by_id, work, specs, factory, pool)
    assert r1.get("label") == "unresolved" and r1.get("pending_shards") == ["c2", "c3"], r1
    cr_coord.resolve_stop(work / "completion" / "j1" / "c1", "c1", by="controller", note="tree verified gone")
    r2 = _complete(src, by_id, work, specs, factory, pool)
    assert r2.get("label") == "unresolved", r2
    assert calls == {"c1": ["j1"], "c2": ["j1"], "c3": ["j1"]}


def test_C1_cr_exit_error_on_the_only_shard_is_unresolved(tmp_path):
    src, by_id, work = _screened(tmp_path)
    specs, factory, calls, pool = _shards(src, {"c1": CRERR_SURV})
    res = _complete(src, by_id, work, specs, factory, pool)
    assert res.get("label") == "unresolved", res
    assert (res.get("attempts") or [{}])[0].get("stop_reason") == "error:cr_exit_1: j1"


def test_C2_kill_whose_cleanup_was_not_verified_is_unresolved_not_killed(tmp_path):
    src, by_id, work = _screened(tmp_path)
    specs, factory, calls, pool = _shards(src, {"c1": UNCERTAIN_KILL, "c2": CLEAN_SURV})
    res = _complete(src, by_id, work, specs, factory, pool)
    assert res.get("label") == "unresolved", res
    assert (res.get("basis") or {}).get("killed_by") is None and res.get("pending_shards") == ["c2"]


@pytest.mark.parametrize("case", ["stopped_survivor", "kill_guard_mismatch", "survivor_guard_mismatch",
                                  "kill_cleanup_unverified", "exec_error_unstopped", "cleanup_unverified_unstopped",
                                  "clean_kill_after_nonkill", "pending_only",
                                  "empty_required", "unknown_shard", "bad_screen"])
def test_merge_counts_only_guard_clean_attempts(case):
    def a(s, label, guard=None, **kw):
        out = {"shard": s, "label": label, "guard_status": guard if guard is not None else _GUARD.get(label, label),
               "stopped": False, "stop_reason": None, "exec_status": "ok", "cleanup_verified": True}
        out.update(kw)
        return out
    m = cr_reconcile.merge_attempts
    if case == "stopped_survivor":
        r = m("survived", [a("c1", "survived", stopped=True, stop_reason="source_not_restored: j1")], ["c1"])
        assert r.get("label") == "unresolved", r
    elif case == "kill_guard_mismatch":          # pins the guard_status conjunct of a kill
        r = m("survived", [a("c1", "killed", guard="error:junit_error"), a("c2", "survived")], ["c1", "c2"])
        assert r.get("label") == "unresolved", r
    elif case == "survivor_guard_mismatch":      # pins the guard_status conjunct of a survivor
        r = m("survived", [a("c1", "survived", guard="skip")], ["c1"])
        assert r.get("label") == "unresolved", r
    elif case == "kill_cleanup_unverified":
        r = m("survived", [a("c1", "killed", cleanup_verified=False, exec_status="cleanup_uncertain")], ["c1"])
        assert r.get("label") == "unresolved", r
    elif case == "exec_error_unstopped":         # pins the exec_status conjunct on its own
        r = m("survived", [a("c1", "survived", exec_status="error:cr_exit_1")], ["c1"])
        assert r.get("label") == "unresolved", r
    elif case == "cleanup_unverified_unstopped":  # pins the cleanup_verified conjunct on its own
        r = m("survived", [a("c1", "killed", cleanup_verified=False)], ["c1"])
        assert r.get("label") == "unresolved", r
    elif case == "clean_kill_after_nonkill":
        r = m("survived", [a("c1", "timeout", stopped=True, stop_reason="timeout: j1"), a("c2", "killed")],
              ["c1", "c2", "c3"])
        assert r.get("label") == "killed" and [n["shard"] for n in r["basis"]["nonkill"]] == ["c1"], r
    elif case == "pending_only":
        r = m("survived", [a("c1", "survived"), a("c2", "survived")], ["c1", "c2", "c3"])
        assert r.get("label") == "deferred" and (r.get("basis") or {}).get("missing") == ["c3"], r
    elif case == "empty_required":
        with pytest.raises(ValueError, match=r"no required completion shards"):
            m("survived", [a("c1", "survived")], [])
    elif case == "unknown_shard":
        with pytest.raises(ValueError, match=r"attempt for unknown shard 'cX'"):
            m("survived", [a("cX", "survived")], ["c1"])
    else:
        with pytest.raises(ValueError, match=r"screening label 'killed' is not a survivor"):
            m("killed", [a("c1", "survived")], ["c1"])


def test_completion_refuses_a_candidate_that_did_not_survive_screening(tmp_path):
    src, by_id, work = _screened(tmp_path, result=CLEAN_KILL)
    specs, factory, calls, pool = _shards(src, {"c1": CLEAN_SURV})
    with pytest.raises(cr_coord.CoordError, match=r"j1 is not a screening survivor: labels \['killed'\]"):
        _complete(src, by_id, work, specs, factory, pool)
    assert not (work / "completion").exists() and calls == {"c1": []}


# --- I1: the declared shard set must cover the frozen pool exactly ------------------------------------------------
@pytest.mark.parametrize("case", ["subset", "zero", "extra_pool_node", "tampered_pool", "no_argfile"])
def test_I1_completion_refuses_shards_that_do_not_cover_the_frozen_pool(tmp_path, case):
    src, by_id, work = _screened(tmp_path)
    specs, factory, calls, pool = _shards(src, {"c1": CLEAN_SURV, "c2": CLEAN_SURV},
                                          extra_pool=["t.py::orphan"] if case == "extra_pool_node" else ())
    pattern = r"completion shards do not cover the frozen pool"
    if case == "subset":
        specs = specs[:1]
    elif case == "zero":
        specs = []
    elif case == "tampered_pool":
        d = json.loads(pool.read_text(encoding="utf-8"))
        pool.write_text(json.dumps(dict(d, nodes=d["nodes"][:-1])), encoding="utf-8")
        pattern = r"pool\.json does not match its nodes_sha256"
    elif case == "no_argfile":
        specs[0]["cfg"].guard_args = ["--control", "c1.json", "c1.py"]
        pattern = r"completion shard c1 has no single @nodes argfile"
    with pytest.raises(cr_coord.CoordError, match=pattern):
        _complete(src, by_id, work, specs, factory, pool)
    assert calls == {"c1": [], "c2": []} and not (work / "completion").exists()


# --- I2: a fence-refused shard is pending and resumes in a later session after resolve_stop ------------------------
def test_I2_fence_refused_shard_resumes_in_a_later_session(tmp_path):
    src, by_id, work = _screened(tmp_path)
    started = json.loads((work / "session.json").read_text(encoding="utf-8"))["started"]
    specs, factory, calls, pool = _shards(src, {"c1": CLEAN_SURV, "c2": CLEAN_SURV})
    late = lambda: started + B["session_length_s"] - 1.0  # noqa: E731
    r1 = _complete(src, by_id, work, specs, factory, pool, clock=late)
    assert r1.get("label") == "deferred" and r1.get("pending_shards") == ["c1", "c2"] and calls["c1"] == []
    st1 = json.loads((work / "completion" / "j1" / "c1" / "batch_c1_state.json").read_text(encoding="utf-8"))
    assert st1["pending"] == ["j1"] and st1["stop_reason"] == "session_budget: j1"
    cr_coord.resolve_stop(work / "completion" / "j1" / "c1", "c1", by="controller", note="session ended")
    s2 = tmp_path / "session2"
    r2 = _complete(src, by_id, work, specs, factory, pool, session_root=s2, clock=lambda: 5.0)
    assert r2.get("label") == "survived", r2
    assert calls == {"c1": ["j1"], "c2": ["j1"]}
    assert [a.get("attempt_batch") for a in r2.get("attempts", [])] == ["c1-a1", "c2"]
    assert json.loads((work / "completion" / "j1" / "c1" / "batch_c1_state.json").read_text(encoding="utf-8")) == st1
    assert (s2 / "session.json").is_file() and not list((work / "completion").rglob("session.json"))


def test_completion_attempts_run_on_the_parent_session_clock(tmp_path):
    src, by_id, work = _screened(tmp_path)
    started = json.loads((work / "session.json").read_text(encoding="utf-8"))["started"]
    specs, factory, calls, pool = _shards(src, {"c1": CLEAN_SURV, "c2": CLEAN_SURV})
    late = lambda: started + B["session_length_s"] - 1.0  # noqa: E731
    res = _complete(src, by_id, work, specs, factory, pool, clock=late)
    assert calls == {"c1": [], "c2": []}, "the nested completion run must not get a fresh session clock"
    assert not list((work / "completion").rglob("session.json")), "no nested session clock"
    assert res.get("label") == "deferred" and res.get("pending_shards") == ["c1", "c2"]


# --- Codex early number check (e): every completion attempt binds its env / helpers / executable ------------------
def test_completion_attempt_binds_executable_env_helpers_nodes_and_control(tmp_path, monkeypatch):
    src, by_id, work = _screened(tmp_path)
    (src / "conftest.py").write_text("# helper\n", encoding="utf-8")
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    specs, factory, calls, pool = _shards(src, {"c1": CLEAN_SURV})
    specs[0]["copy_paths"].append("conftest.py")
    res = _complete(src, by_id, work, specs, factory, pool)
    b = (res.get("attempts") or [{}])[0].get("binding") or {}
    assert b.get("python") == str(PY) and b.get("harness_sha256") == cr_coord.harness_hashes()
    assert b.get("helpers_sha256") == {"conftest.py": sha(src / "conftest.py")}
    assert b.get("node_set_sha256") == cr_coord.pool_sha256((src / "c1.txt").read_text(encoding="utf-8").splitlines())
    assert b.get("control_sha256") == sha(src / "c1.json")
    assert b.get("source_sha256") == sha(src / "pkg" / "m.py")
    assert (b.get("env") or {}).get("PYTHONHASHSEED") == "0" and b.get("pythonpath_rel") == ["."]
    assert b.get("test_command_sha256") and "containment" not in b, "the binding is identity only (fix round 3)"
    assert res["attempts"][0].get("containment") == {"exec_status": "ok", "cleanup_verified": True}


# ----------------------------------------------------------------------------------------------- frozen pool union
def test_completion_pool_union_must_equal_the_frozen_pool_exactly():
    pool = ["t.py::a", "t.py::b", "t.py::c", "u.py::d"]
    cr_coord.check_pool_union(pool, [["t.py::a", "t.py::b"], ["t.py::c", "u.py::d"]])
    with pytest.raises(cr_coord.PartitionError, match=r"missing: \['u\.py::d'\]"):
        cr_coord.check_pool_union(pool, [["t.py::a", "t.py::b"], ["t.py::c"]])
    with pytest.raises(cr_coord.PartitionError, match=r"unknown: \['v\.py::e'\]"):
        cr_coord.check_pool_union(pool, [["t.py::a", "t.py::b"], ["t.py::c", "u.py::d", "v.py::e"]])
    with pytest.raises(cr_coord.PartitionError, match=r"duplicated: \['t\.py::b'\]"):
        cr_coord.check_pool_union(pool, [["t.py::a", "t.py::b"], ["t.py::b", "t.py::c", "u.py::d"]])


# ------------------------------------------------------------------------------------------- HARD session fence
def test_fence_is_outer_plus_cleanup_plus_measured_io_and_the_clock_is_monotonic():
    assert cr_coord.IO_MARGIN_S > 0
    assert cr_coord.fence_s() == B["cr_timeout_s"] + B["cleanup_reserve_s"] + B["cleanup_reserve_s"] + \
        cr_coord.IO_MARGIN_S
    assert cr_coord.fence_s(item_outer_s=645.0, io_margin_s=2.0) == 645.0 + B["cleanup_reserve_s"] + 2.0
    import time as _t
    assert inspect.signature(cr_coord.run_batch).parameters["clock"].default is _t.monotonic


def test_candidate_is_refused_at_the_fence_boundary_and_pending_is_preserved(tmp_path):
    src, items = _three(tmp_path)
    by_id = {i["job_id"]: i for i in items}
    work, now = tmp_path / "w", [1000.0]
    clock = lambda: now[0]  # noqa: E731
    calls = []
    cr_coord.run_batch(["j1"], by_id, batch_id="b000", src_root=src, copy_paths=["pkg"], work_root=work,
                       exec_seam=_seam({}, calls), clock=clock)
    fence = cr_coord.fence_s()
    now[0] = 1000.0 + B["session_length_s"] - fence + 0.001          # remaining is just under the fence
    st = cr_coord.run_batch(["j2", "j3"], by_id, batch_id="b001", src_root=src, copy_paths=["pkg"], work_root=work,
                            exec_seam=_seam({}, calls), clock=clock)
    assert calls == ["j1"], "no candidate starts with less than the fence remaining"
    assert st.get("stopped") is True and str(st.get("stop_reason")).startswith("session_budget: j2")
    assert st.get("pending") == ["j2", "j3"] and st.get("done") == []
    assert st.get("fence_s") == fence
    cr_coord.resolve_stop(work, "b001", by="controller", note="session ended")
    now[0] = 1000.0 + B["session_length_s"] - fence                  # exactly the fence remaining: may start
    st2 = cr_coord.run_batch(["j2"], by_id, batch_id="b002", src_root=src, copy_paths=["pkg"], work_root=work,
                             exec_seam=_seam({}, calls), clock=clock)
    assert st2.get("done") == ["j2"] and calls == ["j1", "j2"]


def test_a_clock_before_the_session_start_is_refused(tmp_path):
    src, items = _three(tmp_path)
    by_id = {i["job_id"]: i for i in items}
    work, now, calls = tmp_path / "w", [1000.0], []
    cr_coord.run_batch(["j1"], by_id, batch_id="b000", src_root=src, copy_paths=["pkg"], work_root=work,
                       exec_seam=_seam({}, calls), clock=lambda: now[0])
    now[0] = 10.0                                                    # e.g. a reboot reset the monotonic clock
    st = cr_coord.run_batch(["j2"], by_id, batch_id="b001", src_root=src, copy_paths=["pkg"], work_root=work,
                            exec_seam=_seam({}, calls), clock=lambda: now[0])
    assert calls == ["j1"] and str(st.get("stop_reason")).startswith("session_clock_invalid: j2")


# --- I4 (task review D13/D14): the retry runs on the PARENT session clock with the 600 + 45 s item path ------------
def _cfg(tag="x"):
    return cr_coord.CRConfig(python=PY, module_rel="pkg/m.py", guard_args=["--control", f"{tag}.json", f"{tag}.py"],
                             target_module="pkg.m")


def test_I4_retry_uses_the_parent_session_clock_and_the_retry_fence(tmp_path):
    src, by_id, work = _screened(tmp_path, result=GUARD_TIMEOUT)
    started = json.loads((work / "session.json").read_text(encoding="utf-8"))["started"]
    calls = []
    st = cr_coord.run_retry("j1", by_id, _cfg(), src_root=src, copy_paths=["pkg"], work_root=work,
                            exec_factory=lambda c: _seam({}, calls),
                            clock=lambda: started + B["session_length_s"] - 500.0)
    assert calls == [], "500 s left is under the retry fence (600 + 45 + 45 + margin)"
    assert str(st.get("stop_reason")).startswith("session_budget: j1")
    assert st.get("fence_s") == 600.0 + B["cleanup_reserve_s"] + B["cleanup_reserve_s"] + cr_coord.IO_MARGIN_S
    assert not (work / "retries" / "j1" / "session.json").exists(), "no fresh nested session clock for a retry"


def test_N1_run_retry_refuses_a_completion_shard_directory(tmp_path):
    src, by_id, work = _screened(tmp_path)
    specs, factory, calls, pool = _shards(src, {"c1": GUARD_TIMEOUT})
    _complete(src, by_id, work, specs, factory, pool)
    sroot = work / "completion" / "j1" / "c1"
    with pytest.raises(cr_coord.CoordError, match=r"run_retry refuses a completion-shard directory"):
        cr_coord.run_retry("j1", by_id, _cfg(), src_root=src, copy_paths=["pkg"], work_root=sroot,
                           exec_factory=lambda c: _seam({}, []))
    assert not (sroot / "retries").exists()


# -------------------------------------------------------------------------------- I3: config-bound calibration cap
def _many(tmp_path, n):
    src = tmp_path / "src"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "m.py").write_text("".join(f"X{i} = {i}\n" for i in range(n)), encoding="utf-8")
    items = [{"job_id": f"j{i:02d}", "module_path": "pkg/m.py", "operator": "core/NumberReplacer",
              "operator_args": {}, "occurrence": 0, "start": [i + 1, 5], "end": [i + 1, 6]} for i in range(n)]
    return src, {i["job_id"]: i for i in items}


def _identity(tmp_path, tag):
    cfg = _cfg(tag)
    toml = tmp_path / f"{tag}_cr.toml"
    cr_coord.write_cr_toml(toml, cfg)
    return cr_coord.config_identity(cfg, toml, config_id=f"pkg.m/{tag}"), cfg, toml


def _inv_for(tmp_path, cfg, by_id):
    """fix round 4 (R3-N3): the inventory a direct run_batch(config=...) identity is verified against."""
    inv = tmp_path / "identity_inventory.json"
    inv.write_text(json.dumps({"module_rel": "pkg/m.py", "test_command": cr_coord.test_command(cfg),
                               "items": cr_coord.order_items(list(by_id.values()))}), encoding="utf-8")
    return inv


def test_I3_cap_is_bound_to_one_config_and_reverified_on_use(tmp_path):
    src, by_id = _many(tmp_path, 60)
    ids = sorted(by_id)
    ida, cfg_a, toml_a = _identity(tmp_path, "a")
    idb, _, _ = _identity(tmp_path, "b")
    assert ida.get("config_id") == "pkg.m/a" and ida.get("cr_toml_sha256") == sha(toml_a)
    assert ida.get("test_command_sha256") and ida.get("harness_sha256") == cr_coord.harness_hashes()
    now = [0.0]

    def seam(item, copy_root, job_dir):
        now[0] += 100.0 if item["job_id"] != "j05" else 150.0     # measured per-item cost (fake monotonic clock)
        return dict(CLEAN_SURV)
    work, inv = tmp_path / "w", _inv_for(tmp_path, cfg_a, by_id)
    st = cr_coord.run_batch(ids[:24], by_id, batch_id="cal", src_root=src, copy_paths=["pkg"], work_root=work,
                            exec_seam=seam, clock=lambda: now[0], config=ida, inventory_path=inv)
    assert st.get("item_s", {}).get("j05") == 150.0 and st.get("config") == ida
    state = work / "batch_cal_state.json"
    short = tmp_path / "short_state.json"
    short.write_text(json.dumps(dict(st, item_s=dict(list(st["item_s"].items())[:23]))), encoding="utf-8")
    with pytest.raises(cr_coord.CoordError, match=r"calibration needs at least 24 measured items, got 23"):
        cr_coord.derive_cap(short, out=tmp_path / "cap_short.json", identity=ida)
    with pytest.raises(cr_coord.CoordError, match=r"calibration state is from a different config"):
        cr_coord.derive_cap(state, out=tmp_path / "cap_b.json", identity=idb)
    cap_path = work / "derived_cap.json"
    rec = cr_coord.derive_cap(state, out=cap_path, identity=ida)
    fence = cr_coord.fence_s()
    assert rec.get("derived_cap") == math.floor((B["session_length_s"] - fence) / 150.0) == 69
    assert rec.get("config") == ida and rec.get("calibration_state", {}).get("sha256") == sha(state)
    with pytest.raises(cr_coord.CoordError, match=r"derived_cap\.json already exists"):
        cr_coord.derive_cap(state, out=cap_path, identity=ida)
    with pytest.raises(cr_coord.CoordError, match=r"cap record must be a recorded file path"):
        cr_coord.plan_batches(ids, size=60, cap_record={"derived_cap": 60}, identity=ida)
    with pytest.raises(cr_coord.CoordError, match=r"cap record is bound to config pkg\.m/a, not pkg\.m/b"):
        cr_coord.plan_batches(ids, size=30, cap_record=cap_path, identity=idb)
    with pytest.raises(cr_coord.PartitionError, match=r"batch size 30 exceeds the 24 cap"):
        cr_coord.plan_batches(ids, size=30)
    assert [len(b) for b in cr_coord.plan_batches(ids, size=30, cap_record=cap_path, identity=ida)] == [30, 30]
    with pytest.raises(cr_coord.PartitionError, match=r"batch size 99 exceeds the 69 cap"):
        cr_coord.plan_batches(ids, size=99, cap_record=cap_path, identity=ida)
    with pytest.raises(cr_coord.PartitionError, match=r"over the 24 cap"):
        cr_coord.run_batch(ids[24:54], by_id, batch_id="b1", src_root=src, copy_paths=["pkg"], work_root=work,
                           exec_seam=seam, clock=lambda: now[0], config=ida, inventory_path=inv)
    st2 = cr_coord.run_batch(ids[24:54], by_id, batch_id="b1", src_root=src, copy_paths=["pkg"], work_root=work,
                             exec_seam=seam, clock=lambda: now[0], config=ida, cap_record=cap_path,
                             inventory_path=inv)
    assert len(st2.get("done", [])) == 30
    toml_a.write_text(toml_a.read_text(encoding="utf-8").replace("timeout = 300.0", "timeout = 301.0"),
                      encoding="utf-8")
    with pytest.raises(cr_coord.CoordError, match=r"cr\.toml does not match the config"):
        cr_coord.config_identity(cfg_a, toml_a, config_id="pkg.m/a")
    state.write_text(state.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(cr_coord.CoordError, match=r"calibration state .* changed since the cap was derived"):
        cr_coord.read_cap_record(cap_path, identity=ida)
    cap_path.write_text(cap_path.read_text(encoding="utf-8").replace('"derived_cap": 69', '"derived_cap": 99'),
                        encoding="utf-8")
    with pytest.raises(cr_coord.CoordError, match=r"derived_cap\.json does not match its sha256"):
        cr_coord.read_cap_record(cap_path, identity=ida)
    assert os.path.isfile(cap_path)


# =============================================================================================== 15c-H fix round 2
# R1-I1 (re-review 1): an unclean kill whose stop was RESOLVED must not short-circuit the remaining shards; a later
# guard-clean kill settles killed (reviewer probe test_N_unclean_kill_resolved_then_later_clean_kill).
def test_R1_I1_resolved_unclean_kill_does_not_short_circuit_a_later_clean_kill(tmp_path):
    src, by_id, work = _screened(tmp_path)
    specs, factory, calls, pool = _shards(src, {"c1": UNCERTAIN_KILL, "c2": CLEAN_KILL, "c3": CLEAN_SURV})
    r1 = _complete(src, by_id, work, specs, factory, pool)
    assert r1.get("label") == "unresolved" and r1.get("pending_shards") == ["c2", "c3"], r1
    cr_coord.resolve_stop(work / "completion" / "j1" / "c1", "c1", by="controller", note="tree verified gone")
    r2 = _complete(src, by_id, work, specs, factory, pool)
    assert r2.get("label") == "killed" and (r2.get("basis") or {}).get("killed_by") == "c2", r2
    assert calls == {"c1": ["j1"], "c2": ["j1"], "c3": []} and r2.get("not_run") == ["c3"]
    nk = (r2.get("basis") or {}).get("nonkill") or [{}]
    assert [(n.get("shard"), n.get("label"), n.get("exec_status")) for n in nk] == \
        [("c1", "killed", "cleanup_uncertain")]


def _cap_setup(tmp_path):
    src, by_id = _many(tmp_path, 60)
    ids = sorted(by_id)
    ida, cfg_a, _ = _identity(tmp_path, "a")
    now = [0.0]

    def seam(item, copy_root, job_dir):
        now[0] += 100.0
        return dict(CLEAN_SURV)
    work = tmp_path / "w"
    cr_coord.run_batch(ids[:24], by_id, batch_id="cal", src_root=src, copy_paths=["pkg"], work_root=work,
                       exec_seam=seam, clock=lambda: now[0], config=ida,
                       inventory_path=_inv_for(tmp_path, cfg_a, by_id))
    cap_path = work / "derived_cap.json"
    cr_coord.derive_cap(work / "batch_cal_state.json", out=cap_path, identity=ida)
    return src, by_id, ids, ida, cap_path, seam, now, work


# R1-I2 (re-review 1): a cap record FILE without the caller's current config identity is refused everywhere.
def test_R1_I2_cap_record_without_a_config_identity_is_refused(tmp_path):
    src, by_id, ids, ida, cap_path, seam, now, work = _cap_setup(tmp_path)
    with pytest.raises(cr_coord.CoordError, match=r"only usable with the current config identity"):
        cr_coord.plan_batches(ids, size=30, cap_record=cap_path)
    with pytest.raises(cr_coord.CoordError, match=r"only usable with the current config identity"):
        cr_coord.run_batch(ids[24:54], by_id, batch_id="b1", src_root=src, copy_paths=["pkg"], work_root=work,
                           exec_seam=seam, clock=lambda: now[0], cap_record=cap_path)
    assert not (work / "batch_b1_state.json").exists()


# R1-N1: a direct read_cap_record(path) WITHOUT an identity still re-checks the harness on disk.
def test_R1_N1_read_cap_record_without_identity_still_rechecks_the_harness(tmp_path, monkeypatch):
    *_, cap_path, _seam_, _now, _work = _cap_setup(tmp_path)
    assert cr_coord.read_cap_record(cap_path).get("derived_cap") == 103
    real = cr_coord.harness_hashes()
    monkeypatch.setattr(cr_coord, "harness_hashes", lambda: dict(real, **{"cr_coord.py": "0" * 64}))
    with pytest.raises(cr_coord.CoordError, match=r"config files of pkg\.m/a changed since the cap was derived"):
        cr_coord.read_cap_record(cap_path)


# R1-N1: a completion shard config with TWO @argfiles is refused (the pool check must see the one node list it runs).
def test_R1_N1_completion_shard_with_two_argfiles_is_refused(tmp_path):
    src, by_id, work = _screened(tmp_path)
    specs, factory, calls, pool = _shards(src, {"c1": CLEAN_SURV, "c2": CLEAN_SURV})
    specs[0]["cfg"].guard_args = ["--control", "c1.json", "@c1.txt", "@c2.txt"]
    with pytest.raises(cr_coord.CoordError, match=r"completion shard c1 has no single @nodes argfile"):
        _complete(src, by_id, work, specs, factory, pool)
    assert calls == {"c1": [], "c2": []}


# R1-N4: the shard's --control node set (what the guard enforces) must equal its @argfile node set.
@pytest.mark.parametrize("case", ["control_differs", "control_missing"])
def test_R1_N4_completion_shard_control_must_equal_its_argfile(tmp_path, case):
    src, by_id, work = _screened(tmp_path)
    specs, factory, calls, pool = _shards(src, {"c1": CLEAN_SURV, "c2": CLEAN_SURV})
    if case == "control_differs":
        (src / "c1.json").write_text(json.dumps({"nodes": ["t.py::test_c1_0"]}), encoding="utf-8")
    else:
        (src / "c1.json").unlink()
    with pytest.raises(cr_coord.CoordError, match=r"completion shard c1: control node set != its @argfile"):
        _complete(src, by_id, work, specs, factory, pool)
    assert calls == {"c1": [], "c2": []} and not (work / "completion").exists()


# R1-N2: a SCREENING retry whose work_root merely sits under a directory named "completion" is allowed; the
# completion areas (completion/, completion/<job>, completion/<job>/<shard>) are still refused.
def test_R1_N2_screening_retry_under_a_dir_named_completion_is_allowed(tmp_path):
    src, items = _three(tmp_path)
    by_id = {i["job_id"]: i for i in items}
    work = tmp_path / "completion" / "screen_w"
    cr_coord.run_batch(["j1"], by_id, batch_id="b000", src_root=src, copy_paths=["pkg"], work_root=work,
                       exec_seam=_seam({"j1": GUARD_TIMEOUT}, []))
    calls = []
    try:
        st = cr_coord.run_retry("j1", by_id, _cfg(), src_root=src, copy_paths=["pkg"], work_root=work,
                                exec_factory=lambda c: _seam({"j1": CLEAN_KILL}, calls))
    except cr_coord.CoordError as exc:
        st = {"refused": str(exc)}
    assert st.get("done") == ["j1"] and calls == ["j1"], st


def test_R1_N2_completion_areas_are_still_refused_for_retry(tmp_path):
    src, by_id, work = _screened(tmp_path)
    specs, factory, calls, pool = _shards(src, {"c1": GUARD_TIMEOUT})
    _complete(src, by_id, work, specs, factory, pool)
    for root in (work / "completion", work / "completion" / "j1", work / "completion" / "j1" / "c1"):
        with pytest.raises(cr_coord.CoordError, match=r"run_retry refuses a completion-shard directory"):
            cr_coord.run_retry("j1", by_id, _cfg(), src_root=src, copy_paths=["pkg"], work_root=root,
                               exec_factory=lambda c: _seam({}, []))


# R1-N3: run_manifest refuses a config identity whose test-command is not the one the inventory was made for.
def test_R1_N3_run_manifest_refuses_an_identity_for_another_test_command(tmp_path):
    src, items = _three(tmp_path)
    ida, cfg_a, _ = _identity(tmp_path, "a")
    idb, _, _ = _identity(tmp_path, "b")
    work = tmp_path / "w"
    work.mkdir()
    inv = work / "inventory.json"
    inv.write_text(json.dumps({"module_rel": "pkg/m.py", "source_sha256": sha(src / "pkg" / "m.py"),
                               "test_command": cr_coord.test_command(cfg_a), "items": cr_coord.order_items(items)}),
                   encoding="utf-8")
    (m0,) = cr_coord.write_manifests(work, [["j1"]], sha(inv))
    calls = []
    with pytest.raises(cr_coord.CoordError, match=r"identity pkg\.m/b: not this inventory's test_command"):
        cr_coord.run_manifest(m0, inv, src_root=src, copy_paths=["pkg"], work_root=work / "s0",
                              exec_seam=_seam({}, calls), config=idb)
    assert calls == []
    st = cr_coord.run_manifest(m0, inv, src_root=src, copy_paths=["pkg"], work_root=work / "s1",
                               exec_seam=_seam({}, calls), config=ida)
    assert st.get("done") == ["j1"] and st.get("config") == ida


# =============================================================================================== 15c-H fix round 3
# Codex exact-head review of 192e47c: X23 (a cached completion attempt was merged under a binding recomputed from the
# CURRENT inputs) and X24 (the binding env was read from os.environ, not the env _env gives the child). Rulings: bind
# at execution time from the child's inputs, persist it with the attempt, compare it field by field on reuse/resume
# (drift fails closed, nothing is relabelled), check an explicit source_sha256, and close the screening-reuse path.
def _x23(tmp_path, monkeypatch):
    """One screened survivor + one clean completion attempt c1, with a helper on the copied path."""
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    src, by_id, work = _screened(tmp_path)
    (src / "conftest.py").write_text("# helper v1\n", encoding="utf-8")
    specs, factory, calls, pool = _shards(src, {"c1": CLEAN_SURV})
    specs[0]["copy_paths"].append("conftest.py")
    r1 = _complete(src, by_id, work, specs, factory, pool)
    assert r1.get("label") == "survived" and calls["c1"] == ["j1"], r1
    state = work / "completion" / "j1" / "c1" / "batch_c1_state.json"
    return src, by_id, work, specs, factory, calls, pool, state


def _drift(case, src, specs, monkeypatch):
    if case == "command":                                     # Codex: command-only drift
        specs[0]["cfg"].guard_args = specs[0]["cfg"].guard_args + ["-k", "no_such_test"]
    elif case == "source":                                    # Codex: source-only drift
        (src / "pkg" / "m.py").write_text("X = 1\nY = 2\nZ = 3\nDRIFT = 1\n", encoding="utf-8")
    elif case == "helper":                                    # Codex: helper-only drift
        (src / "conftest.py").write_text("# helper v2\n", encoding="utf-8")
    else:                                                     # env drift
        monkeypatch.setenv("PYTHONHASHSEED", "1")


_DRIFT_FIELD = {"command": r"test_command_sha256", "source": r"source_sha256", "helper": r"helpers_sha256",
                "env": r"env\.PYTHONHASHSEED"}


@pytest.mark.parametrize("case", ["command", "source", "helper", "env"])
def test_X23_cached_attempt_with_drifted_inputs_is_refused_not_relabelled(tmp_path, monkeypatch, case):
    src, by_id, work, specs, factory, calls, pool, state = _x23(tmp_path, monkeypatch)
    before = state.read_bytes()
    _drift(case, src, specs, monkeypatch)
    with pytest.raises(cr_coord.CoordError, match=_DRIFT_FIELD[case]):
        _complete(src, by_id, work, specs, factory, pool)
    assert calls["c1"] == ["j1"], "no attempt was re-run"
    assert state.read_bytes() == before, "the persisted attempt (and its binding) is unchanged"
    assert not list((work / "completion" / "j1").glob("completion_record_*.json")), "no relabelled record written"


def test_X23_unchanged_context_reuses_the_cached_attempt_with_its_original_binding(tmp_path, monkeypatch):
    src, by_id, work, specs, factory, calls, pool, state = _x23(tmp_path, monkeypatch)
    r2 = _complete(src, by_id, work, specs, factory, pool)
    persisted = json.loads(state.read_text(encoding="utf-8")).get("bindings", {}).get("j1")
    assert r2.get("label") == "survived" and calls["c1"] == ["j1"]
    assert r2["attempts"][0].get("binding") == persisted


def test_X23_binding_is_persisted_with_the_attempt_at_execution_time(tmp_path, monkeypatch):
    src, by_id, work, specs, factory, calls, pool, state = _x23(tmp_path, monkeypatch)
    st = json.loads(state.read_text(encoding="utf-8"))
    b = (st.get("bindings") or {}).get("j1") or {}
    assert b.get("source_sha256") == sha(src / "pkg" / "m.py") and b.get("helpers_sha256") == \
        {"conftest.py": sha(src / "conftest.py")}
    assert st.get("planned_binding") == b, "what ran equals what was planned from the source tree"
    rec = json.loads((work / "completion" / "j1" / "completion_record.json").read_text(encoding="utf-8"))
    assert rec["attempts"][0]["binding"] == b


def test_X23_explicit_source_sha256_is_checked_against_the_persisted_binding(tmp_path, monkeypatch):
    src, by_id, work, specs, factory, calls, pool, state = _x23(tmp_path, monkeypatch)
    with pytest.raises(cr_coord.CoordError, match=r"source_sha256"):
        _complete(src, by_id, work, specs, factory, pool, source_sha256={"pkg/m.py": "0" * 64})
    assert calls["c1"] == ["j1"]


def test_X23_refused_shard_resume_with_drifted_inputs_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    src, by_id, work = _screened(tmp_path)
    started = json.loads((work / "session.json").read_text(encoding="utf-8"))["started"]
    specs, factory, calls, pool = _shards(src, {"c1": CLEAN_SURV})
    _complete(src, by_id, work, specs, factory, pool, clock=lambda: started + B["session_length_s"] - 1.0)
    cr_coord.resolve_stop(work / "completion" / "j1" / "c1", "c1", by="controller", note="session ended")
    specs[0]["cfg"].guard_args = specs[0]["cfg"].guard_args + ["-k", "no_such_test"]
    with pytest.raises(cr_coord.CoordError, match=r"test_command_sha256"):
        _complete(src, by_id, work, specs, factory, pool, session_root=tmp_path / "s2", clock=lambda: 5.0)
    assert calls["c1"] == []


@pytest.mark.parametrize("case", ["source", "harness"])
def test_X23_screening_label_is_not_reused_across_source_or_harness_drift(tmp_path, monkeypatch, case):
    src, by_id, work = _screened(tmp_path)
    specs, factory, calls, pool = _shards(src, {"c1": CLEAN_SURV})
    if case == "source":
        (src / "pkg" / "m.py").write_text("X = 1\nY = 2\nZ = 3\nDRIFT = 1\n", encoding="utf-8")
        pattern = r"screening of j1 .*source_sha256"
    else:
        real = cr_coord.harness_hashes()
        monkeypatch.setattr(cr_coord, "harness_hashes", lambda: dict(real, **{"cr_coord.py": "0" * 64}))
        pattern = r"screening of j1 .*harness"
    with pytest.raises(cr_coord.CoordError, match=pattern):
        _complete(src, by_id, work, specs, factory, pool)
    assert calls["c1"] == [] and not (work / "completion").exists()


def test_X24_binding_env_is_the_child_env_not_the_parent_env(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    monkeypatch.setenv("PYTHONHASHSEED", "7")
    src, by_id, work = _screened(tmp_path)
    specs, factory, calls, pool = _shards(src, {"c1": CLEAN_SURV})
    res = _complete(src, by_id, work, specs, factory, pool)
    env = ((res.get("attempts") or [{}])[0].get("binding") or {}).get("env") or {}
    assert env.get("PYTHONDONTWRITEBYTECODE") == "1", "the child gets 1 from _env whatever the parent has"
    assert env.get("PYTHONHASHSEED") == "7" and env.get("PYTHONPATH") == [".", ".cr_harness"], env


def test_X23_inputs_changing_between_planning_and_execution_are_not_merged(tmp_path, monkeypatch):
    """A helper rewritten after the completion was planned but before the attempt's copy was made: the executed
    (copy) binding differs from the planned one, so the result is not merged."""
    src, by_id, work = _screened(tmp_path)
    (src / "conftest.py").write_text("# helper v1\n", encoding="utf-8")
    specs, factory, calls, pool = _shards(src, {"c1": CLEAN_SURV})
    specs[0]["copy_paths"].append("conftest.py")

    def racing_factory(cfg):
        (src / "conftest.py").write_text("# helper changed mid-run\n", encoding="utf-8")
        return factory(cfg)
    with pytest.raises(cr_coord.CoordError, match=r"executed binding differs from the planned one in \['helpers"):
        _complete(src, by_id, work, specs, racing_factory, pool)
    assert not list((work / "completion" / "j1").glob("completion_record*.json"))


def test_X23_merge_reads_the_persisted_binding_and_never_recomputes_it(tmp_path, monkeypatch):
    """Ruling 1: the merge / completion record take the binding persisted with the attempt. On a cached reuse the
    only binding computation is the one planned comparison per shard (white-box spy on _attempt_binding)."""
    src, by_id, work, specs, factory, calls, pool, state = _x23(tmp_path, monkeypatch)
    seen = []
    real = cr_coord._attempt_binding

    def spy(cfg, root, nodes, copy_paths):
        seen.append(str(root))
        return real(cfg, root, nodes, copy_paths)
    monkeypatch.setattr(cr_coord, "_attempt_binding", spy)
    r2 = _complete(src, by_id, work, specs, factory, pool)
    assert r2.get("label") == "survived" and seen == [str(src)], seen
    assert r2["attempts"][0]["binding"] == json.loads(state.read_text(encoding="utf-8"))["bindings"]["j1"]


# =============================================================================================== 15c-H fix round 4
# Re-review 3: R3-I1 (the child inherited every PYTHON*/PYTEST*/HYPOTHESIS*/COV* variable of the parent while only 7
# were bound), R3-N1 (six fix-3 guards survived deletion alone), R3-N2 (the drift errors named a remedy that does not
# exist), R3-N3 (direct run_batch(config=...) trusted the identity it was given), R3-N4 (_in_completion_area's
# completion_of branch was unpinned).
_PREFIXES = ("PYTHON", "PYTEST", "HYPOTHESIS", "COV")


def _capturing(factory, seen: list):
    """Wrap a stub exec factory: each seam call also records the env real_exec would give the CR child (the same
    production call real_exec makes: _env(copy_root, cfg, job_dir, job_id))."""
    def fac(cfg):
        inner = factory(cfg)

        def seam(item, copy_root, job_dir):
            seen.append((copy_root, job_dir, cr_coord._env(copy_root, cfg, job_dir, item["job_id"])))
            return inner(item, copy_root, job_dir)
        return seam
    return fac


@pytest.mark.parametrize("name,value", [("PYTHONOPTIMIZE", "1"), ("PYTEST_PLUGINS", "x"), ("PYTHONWARNINGS", "error"),
                                        ("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")])
def test_R3_I1_outcome_changing_parent_env_does_not_reach_the_child(tmp_path, monkeypatch, name, value):
    """Ruling 1 (scrub branch): the variable set in the parent is not in the child's env, so it is not in the binding
    either, and setting/unsetting it between two run_completion calls cannot change what a reused attempt ran on."""
    monkeypatch.setenv(name, value)
    src, by_id, work = _screened(tmp_path)
    specs, factory, calls, pool = _shards(src, {"c1": CLEAN_SURV})
    seen = []
    res = _complete(src, by_id, work, specs, _capturing(factory, seen), pool)
    ((_, _, child),) = seen
    assert name.upper() not in {k.upper() for k in child}, f"{name} reached the CR child"
    assert name.upper() not in {k.upper() for k in res["attempts"][0]["binding"]["env"]}
    monkeypatch.delenv(name)
    r2 = _complete(src, by_id, work, specs, factory, pool)
    assert r2.get("label") == "survived" and calls["c1"] == ["j1"], r2


def test_R3_I1_child_env_equals_the_binding_for_every_prefixed_variable(tmp_path, monkeypatch):
    for k, v in {"PYTHONHASHSEED": "5", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONOPTIMIZE": "1",
                 "PYTHONSAFEPATH": "1", "PYTEST_ADDOPTS": "-x", "HYPOTHESIS_STORAGE_DIRECTORY": "h",
                 "COVERAGE_PROCESS_START": "c", "S1_HYPOTHESIS_ROOT": "parent_hyp",
                 cr_guard.NODES_ENV: "parent_nodes"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    src, by_id, work = _screened(tmp_path)
    specs, factory, calls, pool = _shards(src, {"c1": CLEAN_SURV})
    seen = []
    res = _complete(src, by_id, work, specs, _capturing(factory, seen), pool)
    ((copy_root, job_dir, child),) = seen
    bound = res["attempts"][0]["binding"]["env"]
    child_pref = {k: v for k, v in child.items() if k.upper().startswith(_PREFIXES) and k.upper() != "PYTHONPATH"}
    bound_pref = {k: v for k, v in bound.items() if k not in ("PYTHONPATH", "TZ")}
    assert child_pref == bound_pref, (child_pref, bound_pref)
    assert child_pref == {"PYTHONHASHSEED": "5", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
                          "PYTHONDONTWRITEBYTECODE": "1"}, "only the pass list and _env's own values reach the child"
    assert [cr_coord._rel_entry(x, copy_root) for x in child["PYTHONPATH"].split(os.pathsep) if x] == \
        bound["PYTHONPATH"] == [".", ".cr_harness"]
    assert "TZ" in bound, "TZ stays bound"
    assert child["S1_HYPOTHESIS_ROOT"] == str(job_dir / "hypothesis"), "the parent's value never reaches the child"
    assert cr_guard.NODES_ENV not in child


def test_R3_I1_scrub_and_pass_list_match_names_case_insensitively(tmp_path, monkeypatch):
    """Windows env names are case-insensitive (os.environ upper-cases them there, so a mixed-case parent name cannot
    be set through it): a plain mapping stands in for os.environ to exercise the comparison itself."""
    fake = {"pythonOptimize": "1", "Pytest_Plugins": "x", "hypothesis_x": "1", "cov_core_source": "s",
            "PythonHashSeed": "3", "PATH": os.environ.get("PATH", "")}
    monkeypatch.setattr(cr_coord.os, "environ", fake)
    env = cr_coord._env(tmp_path, _cfg())
    assert {k.upper() for k in env if k.upper().startswith(_PREFIXES)} == \
        {"PYTHONHASHSEED", "PYTHONDONTWRITEBYTECODE", "PYTHONPATH"}, env
    assert env.get("PythonHashSeed") == "3" and "PATH" in env


# --- R3-N1: each fix-3 guard that survived deletion is pinned alone -----------------------------------------------
def test_R3_N1_X2_screening_check_alone_refuses_a_pin_other_than_the_screened_source(tmp_path):
    """No cached attempt: without the screening `want` conjunct the attempt would run and stop on source_drift."""
    src, by_id, work = _screened(tmp_path)
    specs, factory, calls, pool = _shards(src, {"c1": CLEAN_SURV})
    with pytest.raises(cr_coord.CoordError, match=r"screening of j1 .*expected source_sha256 is 0{64}"):
        _complete(src, by_id, work, specs, factory, pool, source_sha256={"pkg/m.py": "0" * 64})
    assert calls["c1"] == [] and not (work / "completion").exists()


def test_R3_N1_X7_cached_check_alone_refuses_a_persisted_source_other_than_the_pin(tmp_path, monkeypatch):
    """The screening check refuses first through run_completion, so the cached-attempt check is pinned directly."""
    src, by_id, work, specs, factory, calls, pool, state = _x23(tmp_path, monkeypatch)
    nodes = cr_coord.shard_nodes(specs[0]["cfg"], src, "c1")
    planned = cr_coord._attempt_binding(specs[0]["cfg"], src, nodes, specs[0]["copy_paths"])
    cr_coord._check_cached_attempts("j1", "c1", state.parent, planned, None)
    cr_coord._check_cached_attempts("j1", "c1", state.parent, planned, sha(src / "pkg" / "m.py"))
    with pytest.raises(cr_coord.CoordError, match=r"binding drift in \['source_sha256\(expected\)'\]"):
        cr_coord._check_cached_attempts("j1", "c1", state.parent, planned, "0" * 64)


def test_R3_N1_X6_legacy_attempt_state_without_a_binding_is_refused(tmp_path, monkeypatch):
    src, by_id, work, specs, factory, calls, pool, state = _x23(tmp_path, monkeypatch)
    st = json.loads(state.read_text(encoding="utf-8"))
    st.pop("bindings")                                        # a state written before fix round 3
    state.write_text(json.dumps(st), encoding="utf-8")
    with pytest.raises(cr_coord.CoordError, match=r"has no persisted executed binding.*screen j1 again in a fresh "
                                                  r"work_root"):
        _complete(src, by_id, work, specs, factory, pool)
    assert calls["c1"] == ["j1"]


def test_R3_N1_X9_binding_is_on_disk_before_the_exec_seam_runs(tmp_path):
    src, by_id, work = _screened(tmp_path)
    specs, factory, calls, pool = _shards(src, {"c1": CLEAN_SURV})
    seen = {}

    def fac(cfg):
        inner = factory(cfg)

        def seam(item, copy_root, job_dir):
            st = json.loads((job_dir.parent.parent / "batch_c1_state.json").read_text(encoding="utf-8"))
            seen["binding"] = (st.get("bindings") or {}).get("j1")
            return inner(item, copy_root, job_dir)
        return seam
    res = _complete(src, by_id, work, specs, fac, pool)
    assert seen.get("binding") and seen["binding"] == res["attempts"][0]["binding"], seen


def test_R3_N1_X12_a_helper_outside_the_copy_is_not_bound(tmp_path):
    src, by_id, work = _screened(tmp_path)
    (src / "conftest.py").write_text("# on the source tree, never copied\n", encoding="utf-8")
    specs, factory, calls, pool = _shards(src, {"c1": CLEAN_SURV})
    res = _complete(src, by_id, work, specs, factory, pool)
    assert res.get("label") == "survived" and res["attempts"][0]["binding"]["helpers_sha256"] == {}, res


def test_R3_N1_X15_binding_is_taken_from_the_copy_not_the_source_tree(tmp_path, monkeypatch):
    """A copy that differs from the source tree (simulated by wrapping make_copy) is what the child runs on, so the
    executed binding must come from the copy and then differ from the planned one."""
    src, by_id, work = _screened(tmp_path)
    (src / "conftest.py").write_text("# helper v1\n", encoding="utf-8")
    specs, factory, calls, pool = _shards(src, {"c1": CLEAN_SURV})
    specs[0]["copy_paths"].append("conftest.py")
    real = cr_coord.make_copy

    def diverging_copy(src_root, copy_paths, dest):
        out = real(src_root, copy_paths, dest)
        (dest / "conftest.py").write_text("# the copy differs\n", encoding="utf-8")
        return out
    monkeypatch.setattr(cr_coord, "make_copy", diverging_copy)
    with pytest.raises(cr_coord.CoordError, match=r"executed binding differs from the planned one in "
                                                  r"\['helpers_sha256'\]"):
        _complete(src, by_id, work, specs, factory, pool)


# --- R3-N2: the drift errors name a remedy that exists, and the remedy works ---------------------------------------
def test_R3_N2_cached_drift_error_names_an_existing_remedy_and_it_works(tmp_path, monkeypatch):
    src, by_id, work, specs, factory, calls, pool, state = _x23(tmp_path, monkeypatch)
    _drift("helper", src, specs, monkeypatch)
    with pytest.raises(cr_coord.CoordError, match=r"restore the bound inputs, or screen j1 again in a fresh "
                                                  r"work_root and complete it there"):
        _complete(src, by_id, work, specs, factory, pool)
    w2 = tmp_path / "w2"                                       # the named remedy, through the existing API only
    cr_coord.run_batch(["j1"], by_id, batch_id="b000", src_root=src, copy_paths=["pkg"], work_root=w2,
                       exec_seam=_seam({}, []))
    r = _complete(src, by_id, w2, specs, factory, pool)
    assert r.get("label") == "survived" and calls["c1"] == ["j1", "j1"], r


def test_R3_N2_mid_run_drift_error_names_an_existing_remedy(tmp_path):
    src, by_id, work = _screened(tmp_path)
    (src / "conftest.py").write_text("# helper v1\n", encoding="utf-8")
    specs, factory, calls, pool = _shards(src, {"c1": CLEAN_SURV})
    specs[0]["copy_paths"].append("conftest.py")

    def racing_factory(cfg):
        (src / "conftest.py").write_text("# helper changed mid-run\n", encoding="utf-8")
        return factory(cfg)
    with pytest.raises(cr_coord.CoordError, match=r"not merged.*screen j1 again in a fresh work_root"):
        _complete(src, by_id, work, specs, racing_factory, pool)


# --- R3-N3: direct run_batch(config=...) verifies the identity against the inventory -------------------------------
def test_R3_N3_direct_run_batch_verifies_a_config_identity_against_the_inventory(tmp_path):
    src, items = _three(tmp_path)
    by_id = {i["job_id"]: i for i in items}
    ida, cfg_a, _ = _identity(tmp_path, "a")
    idb, _, _ = _identity(tmp_path, "b")
    inv = tmp_path / "inventory.json"
    inv.write_text(json.dumps({"module_rel": "pkg/m.py", "source_sha256": sha(src / "pkg" / "m.py"),
                               "test_command": cr_coord.test_command(cfg_a), "items": cr_coord.order_items(items)}),
                   encoding="utf-8")
    work, calls = tmp_path / "w", []
    with pytest.raises(cr_coord.CoordError, match=r"identity pkg\.m/a is only accepted with the inventory"):
        cr_coord.run_batch(["j1"], by_id, batch_id="b0", src_root=src, copy_paths=["pkg"], work_root=work,
                           exec_seam=_seam({}, calls), config=ida)
    with pytest.raises(cr_coord.CoordError, match=r"identity pkg\.m/b: not this inventory's test_command"):
        cr_coord.run_batch(["j1"], by_id, batch_id="b0", src_root=src, copy_paths=["pkg"], work_root=work,
                           exec_seam=_seam({}, calls), config=idb, inventory_path=inv)
    assert calls == [] and not list(work.glob("batch_*_state.json"))
    st = cr_coord.run_batch(["j1"], by_id, batch_id="b0", src_root=src, copy_paths=["pkg"], work_root=work,
                            exec_seam=_seam({}, calls), config=ida, inventory_path=inv)
    assert st.get("done") == ["j1"] and st.get("config") == ida


# --- R3-N4: the completion_of branch of _in_completion_area ---------------------------------------------------------
def test_R3_N4_a_moved_completion_shard_dir_is_refused_by_its_completion_of_record(tmp_path):
    src, by_id, work = _screened(tmp_path)
    specs, factory, calls, pool = _shards(src, {"c1": GUARD_TIMEOUT})
    _complete(src, by_id, work, specs, factory, pool)
    moved = tmp_path / "moved" / "c1"
    moved.parent.mkdir()
    shutil.move(str(work / "completion" / "j1" / "c1"), str(moved))
    assert "completion" not in (moved.name, moved.parent.name, moved.parent.parent.name)
    rcalls = []
    with pytest.raises(cr_coord.CoordError, match=r"run_retry refuses a completion-shard directory"):
        cr_coord.run_retry("j1", by_id, _cfg(), src_root=src, copy_paths=["pkg"], work_root=moved,
                           exec_factory=lambda c: _seam({}, rcalls))
    assert rcalls == [] and not (moved / "retries").exists()
