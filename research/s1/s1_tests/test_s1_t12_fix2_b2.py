"""Task 12 fix round 2: Addendum 2 B2 (the opening-bound process-binding reference; process_binding.json is no
authority; GAP vs MATCH vs change vs exception). Every B2.5 acceptance example, written BEFORE the fix (RED:
s1_evidence/t12_fix2_B2_red.txt). Synthetic only: tmp_path ledgers, mailbox and HMAC key; no live process."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import conftest
import s1_checkpoint as ck
import s1_common as c
import s1_run as r
from conftest import S1_BINDING, S1_PROCESS, S1_RECEIPT, Ledger, _Clock, s1_mailbox, s1_plan_audit, s1_reack, s1_state

UTC = timezone.utc
START = "2026-10-26T13:30:00+00:00"
START_DT = datetime(2026, 10, 26, 13, 30, tzinfo=UTC)
OPEN_CLOSE = datetime(2026, 10, 23, 20, 0, tzinfo=UTC)
B_CMD = '"D:/other/python.exe" main.py --port 8000'
B_BINDING = {"exe": "D:/other/python.exe", "cmdline": B_CMD, "cmdline_sha256": c.sha256_bytes(B_CMD.encode())}
GAP = {"pid": None, "binding": {"unavailable": "nothing listening"}}


def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def proc(binding=S1_BINDING, pid=1, start="2026-10-01T09:00:00"):
    return {"pid": pid, "process_start": start, "binding": dict(binding)}


def _reg(tmp_path):
    st_ = s1_state(tmp_path, START)
    with _Clock(START_DT - timedelta(days=1)):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    st_["ledger"].trade("A", "BUY", 10, 50.0, "2026-10-26T15:00:00+00:00")
    st_["ledger"].set_portfolio("A", 10)
    return st_


def _cp(tmp_path, st_, observation, day=0, minutes=45):
    sch = datetime(2026, 10, 26, 20, 0, tzinfo=UTC) + timedelta(days=day, minutes=minutes)
    act = sch + timedelta(seconds=30)
    fn = observation if callable(observation) else (lambda: json.loads(json.dumps(observation)))
    with _Clock(act):
        return ck.run_checkpoint(tmp_path, st_["ledger"].path, sch, lambda: S1_RECEIPT, fn, tmp_path / "crash.log",
                                 now=lambda: act)


def _opening(tmp_path, observation):
    s1_plan_audit(tmp_path, START)
    lg = Ledger(tmp_path / "opening_ledger.sqlite3")
    sch = OPEN_CLOSE + timedelta(minutes=45)
    act = sch + timedelta(seconds=30)
    fn = observation if callable(observation) else (lambda: json.loads(json.dumps(observation)))
    with _Clock(act):
        return ck.run_opening_checkpoint(tmp_path, lg.path, sch, lambda: S1_RECEIPT, fn, tmp_path / "crash.log",
                                         now=lambda: act)


# ====================================================================== B2.1 the opening must observe the binding
@pytest.mark.parametrize("observation", [GAP, {"pid": 1, "process_start": "s"}, {"error": "exit 1"}],
                         ids=["gap", "no-binding", "observation-error"])
def test_b2_an_unobservable_opening_binding_writes_no_opening_seal(tmp_path, observation):
    """B2.1: the opening capture must contain a usable observed sanitized binding; otherwise the opening attempt is
    preserved as failed (a report with the failure) and no opening seal is written."""
    rep = _opening(tmp_path, observation)
    assert rep["seal"]["written"] is False
    assert not list((tmp_path / "s1_out" / "seals").glob("*.json"))
    assert rep.get("failures"), rep
    assert list((tmp_path / "s1_out" / "captures" / "2026-10-23").glob("*.report.json"))


def test_b2_a_process_observation_exception_at_the_opening_is_preserved_and_writes_no_seal(tmp_path):
    """B2.4/A9.1: an exception is class + sanitized reason, no seal."""
    def boom():
        raise RuntimeError("secret=AKIA-SECRET-VALUE-42")
    rep = _opening(tmp_path, boom)
    assert rep["seal"]["written"] is False and rep["failures"]["process"]["class"] == "RuntimeError"
    assert "AKIA" not in json.dumps(rep)


def test_b2_the_opening_binding_is_the_reference_bound_by_the_attestation_and_prereg(tmp_path):
    """B2.1: the opening seal records the observed binding as the REFERENCE; the START attestation and prereg bind
    it (the RUN-ACK binds the opening seal's hash)."""
    _reg(tmp_path)
    out = tmp_path / "s1_out"
    seal = read(out / "seals" / "2026-10-23.json")
    assert seal["process_binding"] == {"status": "REFERENCE", "binding": S1_BINDING}
    pr, att = read(out / "prereg.json"), read(out / "attest_start.json")
    assert pr["process_binding"] == S1_BINDING
    assert att["process_binding_sha256"] == c.sha256_bytes(c.canonical(S1_BINDING))


# ====================================================================== B2.1 the sidecar is no authority
@pytest.mark.parametrize("sidecar", ["replaced", "deleted"])
def test_b2_deleting_or_replacing_the_reference_sidecar_cannot_rebase(tmp_path, sidecar):
    """B2.1: s1_out/process_binding.json is not an authority: replacing it with binding B, or deleting it, and then
    observing B is still a change against the OPENING's binding A -> persistent ABORTED-INVALID, no seal."""
    st_ = _reg(tmp_path)
    out = tmp_path / "s1_out"
    side = out / "process_binding.json"
    if sidecar == "replaced":
        side.write_text(json.dumps({"binding": B_BINDING, "first_observed_slot": "x"}), encoding="utf-8")
    elif side.exists():
        side.unlink()
    rep = _cp(tmp_path, st_, proc(B_BINDING))
    assert rep["seal"]["written"] is False and rep["stop"]["status"] == "ABORTED-INVALID"
    assert "process binding" in str(read(out / "aborted.json")["reason"])


# ====================================================================== B2.3/B2.4 A, gap, B / A, gap, A
def test_b2_a_then_gap_then_b_is_a_persistent_invalidity(tmp_path):
    """B2.3/B2.4: A seals (MATCH); a gap seals carrying the GAP; B is an observed difference -> persistent
    ABORTED-INVALID; observing A again does not resume (the gap never rebased the reference)."""
    st_ = _reg(tmp_path)
    out = tmp_path / "s1_out"
    assert _cp(tmp_path, st_, proc())["seal"]["written"] is True
    rep = _cp(tmp_path, st_, GAP, day=1)
    assert rep["seal"]["written"] is True and rep["process_binding"]["status"] == "GAP"
    assert read(out / "seals" / "2026-10-27.json")["process_binding"]["status"] == "GAP"
    rep = _cp(tmp_path, st_, proc(B_BINDING), day=2)
    assert rep["seal"]["written"] is False and "process binding" in str(read(out / "aborted.json")["reason"])
    rep = _cp(tmp_path, st_, proc(), day=3)
    assert rep["seal"]["written"] is False and rep["stop"]["status"] == "ABORTED-INVALID"


def test_b2_a_then_gap_then_a_preserves_the_gap_and_invents_no_change(tmp_path):
    """B2.4: a gap is never MATCH and never by itself a change: A, gap, A all seal, no abort, and the gap is
    reported (not converted into equality)."""
    st_ = _reg(tmp_path)
    out = tmp_path / "s1_out"
    reps = [_cp(tmp_path, st_, o, day=i) for i, o in enumerate((proc(), GAP, proc()))]
    assert all(x["seal"]["written"] for x in reps) and not (out / "aborted.json").exists()
    assert [x["process_binding"]["status"] for x in reps] == ["MATCH", "GAP", "MATCH"]
    assert reps[1]["process_binding"]["binding"] is None
    assert any("nothing listening" in g for g in reps[1].get("observation_gaps", [])), reps[1]


def test_b2_an_observation_exception_mid_trial_is_preserved_and_never_seals(tmp_path):
    """B2.4/A9.1: a process-observation exception (or a failed observation, {"error": ...}) is a preserved failure:
    report, no seal, no abort - never carried as a GAP."""
    st_ = _reg(tmp_path)
    def boom():
        raise OSError("powershell failed")
    rep = _cp(tmp_path, st_, boom)
    assert rep["seal"]["written"] is False and rep["failures"]["process"]["class"] == "OSError"
    rep = _cp(tmp_path, st_, {"error": "exit 1"}, minutes=47)
    assert rep["seal"]["written"] is False and "process" in rep.get("failures", {})
    assert not (tmp_path / "s1_out" / "aborted.json").exists()


def test_b2_a_malformed_claimed_binding_is_not_equality(tmp_path):
    """B2.3: an observation claiming a binding that is malformed (hash not of its command line) or missing is not
    equality: no seal (and not a GAP)."""
    st_ = _reg(tmp_path)
    bad = dict(S1_BINDING, cmdline_sha256="0" * 64)
    rep = _cp(tmp_path, st_, proc(bad))
    assert rep["seal"]["written"] is False and rep.get("failures")
    rep = _cp(tmp_path, st_, {"pid": 1, "process_start": "s"}, minutes=47)
    assert rep["seal"]["written"] is False and rep.get("failures")


def test_b2_an_identical_binding_restart_is_provenance_not_a_semantic_change(tmp_path):
    """B2.2: a restart (new pid / start time) with an identical executable + sanitized launcher binding is reported
    (restart evidence), not a semantic change: it seals, no abort."""
    st_ = _reg(tmp_path)
    assert _cp(tmp_path, st_, proc())["seal"]["written"] is True
    rep = _cp(tmp_path, st_, proc(pid=2, start="2026-10-27T09:00:00"), day=1)
    assert rep["seal"]["written"] is True and not (tmp_path / "s1_out" / "aborted.json").exists()
    assert rep["process_binding"]["status"] == "MATCH" and rep["pid"] == 2
    assert any("pid 1 -> 2" in g for g in rep["restart_gaps"]), rep["restart_gaps"]


def test_b2_a_corrupt_bound_reference_fails_closed(tmp_path):
    """B2.5: the bound reference (prereg's process_binding) made unusable -> never a seal (fails closed)."""
    st_ = _reg(tmp_path)
    p = tmp_path / "s1_out" / "prereg.json"
    p.write_text(json.dumps(dict(read(p), process_binding={"garbage": True})), encoding="utf-8")
    with pytest.raises(SystemExit, match=r"registration artifact\(s\) missing or changed"):
        _cp(tmp_path, st_, proc())
    assert not (tmp_path / "s1_out" / "seals" / "2026-10-26.json").exists()


# ====================================================================== B2.3 the score rechecks every seal
VALUATION = ("simulate_lot", "lot_economics", "baseline_economics", "compare", "paired_bootstrap")


def _spy(monkeypatch):
    sim = c.sim()
    called = []
    for name in VALUATION:
        monkeypatch.setattr(sim, name, lambda *a, _n=name, **kw: called.append(_n) or pytest.fail(_n))
    return called


def _scored_state(tmp_path, monkeypatch, dispositions):
    """score_ready state whose post-START seals record the given process_binding dispositions (by seal order)."""
    real = conftest._write_seal
    n = {"i": 0}

    def write(out, day, close_dt, trades, receipt, **kw):
        real(out, day, close_dt, trades, receipt, **kw)
        i = n["i"]
        n["i"] += 1
        if i < len(dispositions) and dispositions[i] is not None:
            p = out / "seals" / f"{day}.json"
            seal = json.loads(p.read_text(encoding="utf-8"))
            if dispositions[i] == "missing":
                seal.pop("process_binding", None)
            else:
                seal["process_binding"] = dispositions[i]
            p.write_text(json.dumps(seal), encoding="utf-8")
    monkeypatch.setattr(conftest, "_write_seal", write)
    st_ = s1_state(tmp_path, START, score_ready=True)
    monkeypatch.setattr(conftest, "_write_seal", real)
    return st_


def _score(tmp_path, monkeypatch, st_):
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"] + timedelta(days=1))
    s1_reack(tmp_path, "score-ack-b2", "S1-SCORE-ACK", st_["now"] + timedelta(hours=20))
    return r.score(tmp_path, "score-ack-b2")


@pytest.mark.parametrize("bad", [{"status": "MATCH", "binding": B_BINDING}, "missing",
                                 {"status": "MATCH", "binding": {"exe": 1}}],
                         ids=["observed-B", "missing", "malformed"])
def test_b2_the_score_rechecks_every_seals_binding_and_invalid_makes_zero_valuation_calls(tmp_path, monkeypatch,
                                                                                          bad):
    """B2.3/B2.5: the score independently rechecks every seal from the opening through the frozen stop against the
    opening reference: A, gap, B (or a missing / malformed claimed binding) -> ABORTED-INVALID, with spies proving
    no valuation helper is called."""
    st_ = _scored_state(tmp_path, monkeypatch, [{"status": "GAP", "binding": None,          # opening = A
                                                 "reason": "nothing listening"}, bad])       # then gap, then B
    called = _spy(monkeypatch)
    rep = _score(tmp_path, monkeypatch, st_)
    assert rep["verdict"] == "ABORTED-INVALID", rep["reasons"]
    assert any("process binding" in x for x in rep["reasons"]), rep["reasons"]
    assert called == [] and "levels" not in rep


def test_b2_the_score_reports_a_gap_without_inventing_a_change(tmp_path, monkeypatch):
    """B2.4: A, gap, A at the score: the gap is reported, never an invalidity by itself."""
    st_ = _scored_state(tmp_path, monkeypatch, [{"status": "GAP", "binding": None,          # opening A, gap, A
                                                 "reason": "nothing listening"}])
    rep = _score(tmp_path, monkeypatch, st_)
    assert not any("process binding" in x for x in rep["reasons"]), rep["reasons"]
    assert any(x.get("gap") and "nothing listening" in str(x["gap"]) for x in rep["seal_binding_gaps"]), rep
