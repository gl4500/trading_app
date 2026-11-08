"""Addendum 3 rev 5 F3 (finalizer rows, the evidence table, the opening/post-START seal from the first QUALIFIED
slot in schedule order), F0.5 4c/4d/6, F0.7, OQ-13/OQ-14. Behavioural RED against the Task 7 stub
(s1_evidence/a3/t7_red.txt). Synthetic journals and ledgers; spies; child processes for the two-finalizer race.
Task 7 additions after the plan's list: the hook position (Task 8 D4), SEALS_ENFORCED (Task 8 D5), N2 (a stalled
stage lock never delays the finalizer's deadline rows), N-1/N-2 (a damaged QUALIFIED tree is INVALID at gate level,
also for the stop attestation, the final plan and the final snapshot), ERROR_ACCESS_DENIED on the finalizer's locks,
and the gate-level check of a QUALIFIED slot behind an in-flight earlier slot."""
import json
import shutil
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
import s1_checkpoint as ck
import s1_collect as k
import s1_common as c
import s1_journal as j
import s1_locks as L
import s1_run as r
import s1_seal as z
import s1_slot as sl
import s1_stage as sg
import s1_trial as t
from conftest import S1_PROCESS, S1_RECEIPT, Spies, _Clock, s1_ack, s1_jappend  # noqa: F401
from test_s1_a3_slots import START, _hold_seal_stage, first_slot, registered, rows, run, slot_rows

HERE = Path(__file__).resolve().parent.parent
REAL_RUN_SEAL_STAGE = sl.run_seal_stage                  # tests that stub it call the real one through this name
_ = shutil                                               # (the brief's import list)


def fin(tmp_path, st_, day, at):
    gv = t.gate(tmp_path, "finalizer test", defer_pending=True)        # the finalizer is a deadline path (N2)
    with _Clock(at):
        return sl.finalize_close(gv, day, st_["calendar"], lambda: at, mailbox=tmp_path / "mailbox.sqlite3")


def E_D(st_, day, sch):
    return z.eligible_until(sch, day, st_["calendar"]), z.resolution_deadline(sch, day, st_["calendar"])


def test_missed_after_e_with_its_own_op_and_no_files(tmp_path):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    e, d = E_D(st_, day, sch)
    fin(tmp_path, st_, day, e)
    got = slot_rows(tmp_path, sch)
    assert [k_ for k_, *_ in got] == ["SLOT-MISSED"]
    n = sl.names(tmp_path / "s1_out", sch, day["date"])
    assert not any(n[k_].exists() for k_ in ("claim", "report", "resolution", "capture"))


def test_premature_finalizer_before_e_or_d_refuses_with_no_row(tmp_path):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    e, d = E_D(st_, day, sch)
    fin(tmp_path, st_, day, e - timedelta(microseconds=1))
    assert slot_rows(tmp_path, sch) == []
    s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(sch), at=sch + timedelta(seconds=1))
    fin(tmp_path, st_, day, d - timedelta(microseconds=1))
    assert [k_ for k_, *_ in slot_rows(tmp_path, sch)] == ["SLOT-INTENT"]


def test_missed_against_an_in_flight_slot_refuses_then_timeout_at_d(tmp_path):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    e, d = E_D(st_, day, sch)
    s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(sch), at=sch + timedelta(seconds=1))
    fin(tmp_path, st_, day, e)                                      # 4d: no MISSED for an in-flight slot
    assert [k_ for k_, *_ in slot_rows(tmp_path, sch)] == ["SLOT-INTENT"]
    fin(tmp_path, st_, day, d)
    assert [k_ for k_, *_ in slot_rows(tmp_path, sch)] == ["SLOT-INTENT", "SLOT-TIMEOUT"]


def test_timeout_carries_the_intent_op_and_the_finalizer_actor(tmp_path):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    e, d = E_D(st_, day, sch)
    s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(sch), at=sch + timedelta(seconds=1), op="1" * 32,
               actor="2" * 32)
    fin(tmp_path, st_, day, d)
    got = slot_rows(tmp_path, sch)
    assert len(got) == 2
    (k1, op1, a1, *_), (k2, op2, a2, *_) = got
    assert op2 == op1 == "1" * 32 and a2 != a1


# ---------------------------------------------------------------- E1 (rows 256-259, 320-322): PLAN-1
LIVE_WORKER = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import s1_common as c, s1_journal as j, s1_locks as L, s1_slot as sl, s1_trial as t
root, subject, cal_p, at0, day_iso = sys.argv[2], sys.argv[3], sys.argv[4], c.aware(sys.argv[5]), sys.argv[6]
mb = root + "/mailbox.sqlite3"
cal = json.loads(open(cal_p, encoding="utf-8").read())
tr = t.open_trial(mb)
lk = L.OwnershipLock(root, tr.trial_id, L.slot_lock_name(subject)).acquire()      # the slot WORK lock, held to exit
op, actor = j.new_nonce(), j.new_nonce()
ctx = t.product_context(tr, cal, slot_gate=lambda rows, s: None)
res = j.append(tr.trial_id, tr.genesis, j.Request("SLOT-INTENT", subject, op, actor), ctx, mailbox=mb,
               clock=lambda: at0)
n = sl.names(Path(root) / "s1_out", sl.slot_of(subject), day_iso)
n["claim"].parent.mkdir(parents=True, exist_ok=True)
n["claim"].write_text(json.dumps({"op": op, "actor": actor,
                                  "capture_dir": n["capture"].relative_to(Path(root) / "s1_out").as_posix()}))
(n["capture"]).mkdir(parents=True, exist_ok=True)
(n["capture"] / "meta.json").write_text("{}")                                    # an uncommitted partial capture
print(json.dumps({"op": op, "actor": actor, "outcome": res.outcome}), flush=True)
cmd = sys.stdin.readline().split()                    # "complete <R> <now>": a stalled worker wakes up after D
if cmd:
    r_at, now_ = c.aware(cmd[1]), c.aware(cmd[2])
    res = j.append(tr.trial_id, tr.genesis, j.Request("SLOT-QUALIFIED", subject, op, actor, detail="1" * 64,
                                                      r_at=r_at), ctx, mailbox=mb, clock=lambda: now_)
    print(json.dumps({"outcome": res.outcome, "reason": res.reason}), flush=True)
sys.stdin.readline()                                  # stays alive (lock held) until the test closes stdin
'''


def live_worker(tmp_path, st_, day, sch):
    cal_p = tmp_path / "cal.json"
    cal_p.write_text(json.dumps(st_["calendar"]), encoding="utf-8")
    p = subprocess.Popen([sys.executable, "-I", "-c", LIVE_WORKER, str(HERE), str(tmp_path), j.slot_subject(sch),
                          str(cal_p), (sch + timedelta(seconds=1)).isoformat(), day["date"]],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    hello = json.loads(p.stdout.readline())
    assert hello["outcome"] == "APPEND"
    return p, hello


def _fin_or_fail(tmp_path, st_, day, at):
    try:
        return fin(tmp_path, st_, day, at)
    except SystemExit as e:                                         # B3: an escaping refusal fails by assertion
        pytest.fail(f"the finalizer was refused: {e}")


def test_timeout_commits_at_d_while_a_live_worker_holds_the_work_lock(tmp_path):       # rows 256, 320
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    e, d = E_D(st_, day, sch)
    p, hello = live_worker(tmp_path, st_, day, sch)
    try:
        _fin_or_fail(tmp_path, st_, day, d)
        got = slot_rows(tmp_path, sch)
        assert [k_ for k_, *_ in got] == ["SLOT-INTENT", "SLOT-TIMEOUT"]
        assert got[1][1] == hello["op"] and got[1][2] != hello["actor"]
        assert p.poll() is None                                        # the worker is still alive and holds the lock
        assert all(x.kind != "TRIAL-INVALID" for x in rows(tmp_path))
    finally:
        p.stdin.close()
        p.wait(timeout=30)


@pytest.mark.parametrize("case", ["late-r", "early-r"])
def test_live_worker_after_timeout_is_lost_race_whatever_r_and_its_files_stay(tmp_path, case):  # rows 257, 321
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    e, d = E_D(st_, day, sch)
    out = tmp_path / "s1_out"
    n = sl.names(out, sch, day["date"])
    p, hello = live_worker(tmp_path, st_, day, sch)
    try:
        res = _fin_or_fail(tmp_path, st_, day, d)                       # TIMEOUT first; cleanup deferred
        assert "deferred" in str(res.get("cleanup"))
        r_at = d if case == "late-r" else d - timedelta(microseconds=1)
        p.stdin.write(f"complete {r_at.isoformat()} {(d + timedelta(seconds=1)).isoformat()}\n")
        p.stdin.flush()
        said = json.loads(p.stdout.readline())
        assert said["outcome"] == "LOST-RACE"                          # E1.3 r3: 4c precedes step 6, whatever R
        assert [k_ for k_, *_ in slot_rows(tmp_path, sch)] == ["SLOT-INTENT", "SLOT-TIMEOUT"]   # TIMEOUT stands
        assert n["claim"].exists() and (n["capture"] / "meta.json").exists()      # not moved while it lives
        assert not (out / "seals" / f"{day['date']}.json").exists()
        assert all(x.kind != "TRIAL-INVALID" for x in rows(tmp_path))
    finally:
        p.stdin.close()
        p.wait(timeout=30)
    res = _fin_or_fail(tmp_path, st_, day, d + timedelta(seconds=2))   # worker gone: the deferred cleanup runs
    assert not n["claim"].exists() and (out / "late" / day["date"] / f"{sch:%Y%m%dT%H%M%SZ}").is_dir()


def test_finalizer_decision_never_touches_the_work_lock(tmp_path, monkeypatch):       # row 258 (E1.2)
    st_ = registered(tmp_path)
    day, s_t = first_slot(st_, 45)
    _, s_m = first_slot(st_, 47)
    e_t, d_t = E_D(st_, day, s_t)
    s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(s_t), at=s_t + timedelta(seconds=1))
    events = []
    real_acq, real_app = sl.L.OwnershipLock.acquire, j.append

    def acq(self):
        events.append(("lock", self.path.stem))
        return real_acq(self)

    def app(trial_id, gen, req, ctx_fn, **kw):
        res = real_app(trial_id, gen, req, ctx_fn, **kw)
        events.append(("append", req.kind, res.outcome))
        return res
    monkeypatch.setattr(sl.L.OwnershipLock, "acquire", acq)
    monkeypatch.setattr(j, "append", app)
    try:
        fin(tmp_path, st_, day, d_t)                                # s_t -> TIMEOUT, s_m (no INTENT) -> MISSED
    except SystemExit as e:
        pytest.fail(f"the finalizer was refused: {e}")
    decided = [i for i, ev in enumerate(events) if ev[0] == "append" and ev[1] in ("SLOT-TIMEOUT", "SLOT-MISSED")]
    assert decided
    assert not any(ev[0] == "lock" and ev[1].startswith("slot-") for ev in events[:decided[-1] + 1])


def test_timeout_cleanup_waits_for_the_work_lock(tmp_path):                         # row 259 (E1.4, OQ-13)
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    e, d = E_D(st_, day, sch)
    n = sl.names(tmp_path / "s1_out", sch, day["date"])
    p, _ = live_worker(tmp_path, st_, day, sch)
    try:
        res = _fin_or_fail(tmp_path, st_, day, d)
        kinds_held = [k_ for k_, *_ in slot_rows(tmp_path, sch)]
        assert "deferred" in str(res.get("cleanup")) and n["claim"].exists()
    finally:
        p.stdin.close()
        p.wait(timeout=30)
    res = _fin_or_fail(tmp_path, st_, day, d + timedelta(seconds=1))
    assert [k_ for k_, *_ in slot_rows(tmp_path, sch)] == kinds_held               # cleanup decides nothing
    assert not n["claim"].exists() and sl.slot_problems(tmp_path / "s1_out", rows(tmp_path), j.slot_subject(sch),
                                                         st_["calendar"]) == []


# ---------------------------------------------------------------- E2 r3 (rows 55, 260-266, 323-325, 331, 334-336)
def _stop_row(tmp_path, at):
    """A3 Task 11 (fixture, F2.3): a consistent synthetic stop (stop.json + matching detail), so the gate's stop_check
    finds no publication gap to recompute; the tests here are about the STOPPED state, not the stop decision."""
    from conftest import s1_synthetic_stop
    return s1_synthetic_stop(tmp_path, at)


def seal_kinds(tmp_path, day_iso):
    return [x.kind for x in j.subject_rows(rows(tmp_path), f"stage/seal/{day_iso}")]


def test_seal_is_an_f4_stage(tmp_path):                                                # row 266 (E2.1 r3)
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    run(tmp_path, st_, sch, sch + timedelta(seconds=30))            # QUALIFIED -> close determined -> seal stage
    assert seal_kinds(tmp_path, day["date"]) == ["STAGE-INTENT", "STAGE-PREPARED", "STAGE-CREATED"]
    q = j.first(j.subject_rows(rows(tmp_path), j.slot_subject(sch)), "SLOT-QUALIFIED")
    tid = t.open_trial(tmp_path / "mailbox.sqlite3").trial_id
    st_dir = sg.staging_dir(tmp_path, tid, f"seal/{day['date']}")
    env = json.loads((st_dir / "intent.json").read_bytes())
    com = json.loads((st_dir / "prepared.json").read_bytes())
    assert env["inputs"] == {"qualified_line": q.sha, "tree_manifest": q.detail} and env["request_policy"] is None
    assert com["kind"] == "single" and list(com["members"]) == [f"seals/{day['date']}.json"]
    assert "seals_checked" not in com                                # removed (E2.7 r3)


def test_no_seal_after_stop_even_for_a_pre_stop_qualified(tmp_path):                  # rows 55, 260, 323, 336
    """A QUALIFIED committed before the STOP whose close becomes determined only after the STOP: the seal INTENT
    is refused (not ACTIVE), so no seal is decided and no file is written."""
    st_ = registered(tmp_path)
    day, s1_ = first_slot(st_, 45)
    _, s2 = first_slot(st_, 47)
    s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(s1_), at=s1_ + timedelta(seconds=1))   # earlier in flight
    run(tmp_path, st_, s2, s2 + timedelta(seconds=30))             # s2 QUALIFIED; close not determined yet
    seal = tmp_path / "s1_out" / "seals" / f"{day['date']}.json"
    assert not seal.exists() and seal_kinds(tmp_path, day["date"]) == []
    _stop_row(tmp_path, s2 + timedelta(minutes=1))                 # STOP (synthetic) before s1 is terminal
    e1, d1 = E_D(st_, day, s1_)
    res = fin(tmp_path, st_, day, d1)                               # s1 TIMEOUT: the close is now determined
    assert [k_ for k_, *_ in slot_rows(tmp_path, s1_)] == ["SLOT-INTENT", "SLOT-TIMEOUT"]
    assert seal_kinds(tmp_path, day["date"]) == [] and not seal.exists()          # INTENT refused (E2.6 r3)
    assert "not allowed while STOPPED" in str(res["refused"])


def _barrier(monkeypatch, commit):
    """Run `commit()` after the seal stage's INTENT committed (its ACTIVE read) and before its PREPARED: the
    stage's work calls seal_bytes, which is wrapped here."""
    real = sl.seal_bytes
    done = []

    def wrapped(*a, **k):
        if not done:
            done.append(1)
            commit()
        return real(*a, **k)
    monkeypatch.setattr(sl, "seal_bytes", wrapped)


def test_barrier_invalid_between_active_read_and_prepared(tmp_path, monkeypatch):      # row 260b (E2.8 r3)
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    _barrier(monkeypatch, lambda: s1_jappend(tmp_path, "TRIAL-INVALID", "reason/registration-artifact",
                                             detail="6" * 64, at=sch + timedelta(seconds=40)))
    run(tmp_path, st_, sch, sch + timedelta(seconds=30))
    assert seal_kinds(tmp_path, day["date"]) == ["STAGE-INTENT"]                   # PREPARED was LOST-RACE
    assert not (tmp_path / "s1_out" / "seals" / f"{day['date']}.json").exists()


def test_barrier_close_between_active_read_and_prepared(tmp_path, monkeypatch):        # row 261 (E2.8 r3)
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    _barrier(monkeypatch, lambda: s1_ack(tmp_path, "close", "S1-CLOSE-ACK", sch + timedelta(seconds=40),
                                         reason="WITHDRAWN", evidence_sha256="e" * 64))
    run(tmp_path, st_, sch, sch + timedelta(seconds=30))
    tr = t.trials(t.scan(tmp_path / "mailbox.sqlite3"))
    (only,) = tr.values()
    kinds_ = [x.kind for x in j.subject_rows(j.read_trial(only.trial_id, only.genesis, tmp_path / "mailbox.sqlite3"),
                                             f"stage/seal/{day['date']}")]
    assert kinds_ == ["STAGE-INTENT"] and only.closed is not None                 # PREPARED refused (CLOSED)
    assert not (tmp_path / "s1_out" / "seals" / f"{day['date']}.json").exists()


def test_stop_fence_refuses_a_determined_close_without_a_created_seal(tmp_path, monkeypatch):   # row 262 (E2.5)
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    monkeypatch.setattr(sl, "run_seal_stage", lambda gv, d, cal, res=None, **k: res or {})   # no seal stage yet
    run(tmp_path, st_, sch, sch + timedelta(seconds=30))            # close determined, no seal stage
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    req = j.Request("TRIAL-STOP", "trial", j.new_nonce(), j.new_nonce(), detail="5" * 64)
    ctx = t.product_context(tr, st_["calendar"], stop_detail=lambda rows_: "5" * 64,
                            stop_fence=sl.stop_fence(st_["calendar"], c.aware(START)),
                            stop_ready=lambda rows_, now_: None)       # A3 Task 11: readiness is not under test here
    at = sch + timedelta(minutes=2)
    res = j.append(tr.trial_id, tr.genesis, req, ctx, mailbox=tmp_path / "mailbox.sqlite3", clock=lambda: at)
    assert res.outcome == "REFUSE" and "not sealed" in res.reason
    gv = t.gate(tmp_path, "seal stage")
    REAL_RUN_SEAL_STAGE(gv, day, st_["calendar"], mailbox=tmp_path / "mailbox.sqlite3", clock=lambda: at)
    res = j.append(tr.trial_id, tr.genesis, req, ctx, mailbox=tmp_path / "mailbox.sqlite3", clock=lambda: at)
    assert res.outcome == "APPEND"


@pytest.mark.parametrize("order", ["publish-first", "stop-first"])
def test_seal_stage_and_stop_orders(tmp_path, order):                                  # rows 324, 335 (E2.8 r3)
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    seal = tmp_path / "s1_out" / "seals" / f"{day['date']}.json"
    if order == "publish-first":                                    # seal CREATED, then the (fenced) STOP commits
        run(tmp_path, st_, sch, sch + timedelta(seconds=30))
        assert seal_kinds(tmp_path, day["date"])[-1:] == ["STAGE-CREATED"] and seal.exists()
        _stop_row(tmp_path, sch + timedelta(minutes=2))
        t.gate(tmp_path, "after the STOP")                          # the CREATED seal verifies: no INVALID
    else:                                                           # STOP first: a later determination is refused
        _, s2 = first_slot(st_, 47)
        s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(sch), at=sch + timedelta(seconds=1))   # earlier in flight
        run(tmp_path, st_, s2, s2 + timedelta(seconds=30))         # s2 QUALIFIED; not determined
        _stop_row(tmp_path, s2 + timedelta(minutes=1))              # nothing determined: the fence would pass
        d1 = E_D(st_, day, sch)[1]
        res = fin(tmp_path, st_, day, d1)                           # sch TIMEOUT -> determined after the STOP
        assert seal_kinds(tmp_path, day["date"]) == [] and not seal.exists()       # post-STOP seal INTENT refused
        assert "not allowed while STOPPED" in str(res["refused"])


@pytest.mark.parametrize("when", ["after-stop", "while-active"])
def test_deleted_created_seal_is_invalid_and_never_recreated(tmp_path, monkeypatch, when):   # rows 263, 325, 264b
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    run(tmp_path, st_, sch, sch + timedelta(seconds=30))            # seal/<close> CREATED
    seal = tmp_path / "s1_out" / "seals" / f"{day['date']}.json"
    assert f"seals/{day['date']}.json" in sl.required_seals(tmp_path / "s1_out", rows(tmp_path))
    if when == "after-stop":
        _stop_row(tmp_path, sch + timedelta(minutes=1))
    seal.unlink()                                                   # the TEST deletes its tmp seal
    sp = Spies(monkeypatch)
    with pytest.raises(SystemExit, match=r"INVALID \(stage-replaced\)"):
        t.gate(tmp_path, "CREATED seal missing")
    sp.assert_zero()
    assert not seal.exists()                                        # never recreated


def test_seal_file_without_prepared_is_invalid(tmp_path, monkeypatch):                 # row 265 (E2.4 r3)
    """Runs on the module default s1_stage.SEALS_ENFORCED (Task 8 D5 condition (b)): no monkeypatch of it."""
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    monkeypatch.setattr(sl, "run_seal_stage", lambda gv, d, cal, res=None, **k: res or {})   # no stage rows
    run(tmp_path, st_, sch, sch + timedelta(seconds=30))
    seal = tmp_path / "s1_out" / "seals" / f"{day['date']}.json"
    seal.parent.mkdir(parents=True, exist_ok=True)
    seal.write_bytes(b'{"forged": true}')                           # the TEST writes a seal outside any stage
    with pytest.raises(SystemExit, match=r"INVALID \(registration-artifact\)"):
        t.gate(tmp_path, "seal without PREPARED")


def test_seals_enforced_is_on():                                                       # Task 8 D5 condition (b)
    assert sg.SEALS_ENFORCED is True


def test_late_r_refuses_with_no_row_then_timeout(tmp_path, monkeypatch):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    e, d = E_D(st_, day, sch)
    real = sl.Worker.complete

    def late(self, rep, success):
        self.now = lambda: d                                         # R = D (late)
        return real(self, rep, success)
    monkeypatch.setattr(sl.Worker, "complete", late)
    res = run(tmp_path, st_, sch, sch + timedelta(seconds=30))
    assert res["journal"]["outcome"] == "REFUSE" and [k_ for k_, *_ in slot_rows(tmp_path, sch)] == ["SLOT-INTENT"]
    monkeypatch.setattr(sl.Worker, "complete", real)        # (never monkeypatch.undo(): it would drop the guards)
    fin(tmp_path, st_, day, d)
    assert [k_ for k_, *_ in slot_rows(tmp_path, sch)] == ["SLOT-INTENT", "SLOT-TIMEOUT"]
    late_dir = tmp_path / "s1_out" / "late" / day["date"] / f"{sch:%Y%m%dT%H%M%SZ}"
    assert late_dir.is_dir()                                         # OQ-13: leftovers moved by the finalizer


def test_stale_finalizer_moves_none_of_the_winners_files_and_the_recheck_passes(tmp_path):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    e, d = E_D(st_, day, sch)
    run(tmp_path, st_, sch, sch + timedelta(seconds=30))
    before = sorted(p.relative_to(tmp_path) for p in (tmp_path / "s1_out" / "captures").rglob("*") if p.is_file())
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    intent = j.first(j.subject_rows(rows(tmp_path), j.slot_subject(sch)), "SLOT-INTENT")
    res = j.append(tr.trial_id, tr.genesis, j.Request("SLOT-TIMEOUT", j.slot_subject(sch), intent.op, j.new_nonce()),
                   t.product_context(tr, st_["calendar"]), mailbox=tmp_path / "mailbox.sqlite3", clock=lambda: d)
    assert res.outcome == "LOST-RACE"
    assert sl.move_leftovers(tmp_path / "s1_out", sch, day["date"], intent.op) == []
    after = sorted(p.relative_to(tmp_path) for p in (tmp_path / "s1_out" / "captures").rglob("*") if p.is_file())
    assert before == after and sl.slot_problems(tmp_path / "s1_out", rows(tmp_path), j.slot_subject(sch),
                                                st_["calendar"]) == []


def _put(p: Path, text="{}"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _evidence_case(tmp_path, st_, case):
    """Set up one F3 evidence-table case; returns the expected verdict ('ok' or 'invalid')."""
    day, sch = first_slot(st_)
    out = tmp_path / "s1_out"
    n = sl.names(out, sch, day["date"])
    e, d = E_D(st_, day, sch)
    sub = j.slot_subject(sch)
    if case == "no-row-clean":
        return "ok"
    if case == "no-row-stray-claim":
        _put(n["claim"], json.dumps({"op": "9" * 32, "actor": "9" * 32}))
        return "invalid"
    if case == "no-row-stray-capture":
        _put(n["capture"] / "meta.json")
        return "invalid"
    if case.startswith("in-flight"):
        row = s1_jappend(tmp_path, "SLOT-INTENT", sub, at=sch + timedelta(seconds=1))
        who = (row.op, row.actor) if case != "in-flight-foreign-op" else ("8" * 32, "8" * 32)
        cap_rel = n["capture"].relative_to(out).as_posix()
        named = cap_rel if case != "in-flight-capture-dir-not-named-by-claim" else cap_rel + "-other"
        _put(n["claim"], json.dumps({"op": who[0], "actor": who[1], "capture_dir": named}))
        _put(n["capture"] / "meta.json")                                # a partial capture
        return "ok" if case == "in-flight-own-partial" else "invalid"   # row 311 (OQ-10 ruling)
    if case.startswith("qualified") or case.startswith("failed"):
        if case.startswith("failed"):
            run(tmp_path, st_, sch, sch - timedelta(seconds=5))       # early: FAILED
        else:
            run(tmp_path, st_, sch, sch + timedelta(seconds=30))
        if case in ("qualified-ok", "failed-ok"):
            return "ok"
        if case == "qualified-missing":
            (n["capture"] / "projection.json").unlink()
        elif case == "qualified-changed":
            n["report"].write_text(n["report"].read_text(encoding="utf-8") + " ", encoding="utf-8")
        elif case == "qualified-unparseable":
            n["resolution"].write_text("{not JSON", encoding="utf-8")
        elif case == "qualified-late-extra":
            _put(out / "late" / day["date"] / "extra.json")
            return "ok"
        elif case == "qualified-backup-changed":                       # row 267 (E5.6)
            with open(n["capture"] / "backup.sqlite3", "ab") as f:
                f.write(b"\0")
        elif case == "qualified-backup-deleted":
            (n["capture"] / "backup.sqlite3").unlink()
        elif case == "failed-report-changed":
            n["report"].write_text("{}", encoding="utf-8")
        elif case == "failed-partial-capture":
            _put(n["capture"] / "partial.bin", "x")
            return "ok"
        return "invalid"
    if case.startswith("timeout"):
        row = s1_jappend(tmp_path, "SLOT-INTENT", sub, at=sch + timedelta(seconds=1))
        _put(n["claim"], json.dumps({"op": row.op, "actor": row.actor}))      # a dead worker's own partial file
        fin(tmp_path, st_, day, d)
        if case == "timeout-leftovers":
            return "ok"
        _put(out / "seals" / f"{day['date']}.json", json.dumps({"capture": {"scheduled": sch.isoformat()}}))
        return "invalid"
    if case.startswith("missed"):
        fin(tmp_path, st_, day, e)
        if case == "missed-stray":
            _put(n["report"])
            return "invalid"
        return "ok"
    raise AssertionError(case)


CASES = ["no-row-clean", "no-row-stray-claim", "no-row-stray-capture", "in-flight-own-partial", "in-flight-foreign-op",
         "in-flight-capture-dir-not-named-by-claim",
         "qualified-ok", "qualified-missing", "qualified-changed", "qualified-unparseable", "qualified-late-extra",
         "qualified-backup-changed", "qualified-backup-deleted",
         "failed-ok", "failed-report-changed", "failed-partial-capture", "timeout-leftovers", "timeout-seal-cites",
         "missed-clean", "missed-stray"]


@pytest.mark.parametrize("case", CASES)
def test_slot_evidence_table(tmp_path, monkeypatch, case):
    st_ = registered(tmp_path)
    want = _evidence_case(tmp_path, st_, case)
    sp = Spies(monkeypatch)
    if want == "ok":
        try:
            t.gate(tmp_path, "evidence table")
        except SystemExit as e:
            pytest.fail(f"a tolerated F3 state was refused: {e}")
        return
    with pytest.raises(SystemExit, match="INVALID"):
        t.gate(tmp_path, "evidence table")
    sp.assert_zero()
    assert rows(tmp_path)[-1].subject == "reason/registration-artifact"


def test_seal_from_the_first_qualified_slot_in_schedule_order_after_earlier_slots_terminal(tmp_path):
    """Also carry-forward 6 (Task 6 C2, sealing liveness): a crashed worker's INTENT-only slot gets the finalizer's
    SLOT-TIMEOUT at D, so the close becomes determined and seals from the later QUALIFIED slot."""
    st_ = registered(tmp_path)
    day, s1_ = first_slot(st_, 45)
    _, s2 = first_slot(st_, 47)
    s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(s1_), at=s1_ + timedelta(seconds=1))   # earlier slot in flight
    run(tmp_path, st_, s2, s2 + timedelta(seconds=30))                                          # later slot QUALIFIED
    assert not (tmp_path / "s1_out" / "seals" / f"{day['date']}.json").exists()
    e1, d1 = E_D(st_, day, s1_)
    fin(tmp_path, st_, day, d1)                                     # earlier slot TIMEOUT -> later slot seals
    assert [k_ for k_, *_ in slot_rows(tmp_path, s1_)] == ["SLOT-INTENT", "SLOT-TIMEOUT"]
    seal = tmp_path / "s1_out" / "seals" / f"{day['date']}.json"
    assert seal.exists() and json.loads(seal.read_text(encoding="utf-8"))["capture"]["scheduled"] == s2.isoformat()
    assert seal_kinds(tmp_path, day["date"]) == ["STAGE-INTENT", "STAGE-PREPARED", "STAGE-CREATED"]


def test_late_files_are_never_selectable_for_a_seal(tmp_path, monkeypatch):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    out = tmp_path / "s1_out"
    late = out / "late" / day["date"] / f"{sch:%Y%m%dT%H%M%SZ}"
    _put(late / f"{sch:%Y%m%dT%H%M%SZ}.resolution.json", json.dumps({"outcome": "SUCCESS"}))
    e, d = E_D(st_, day, sch)
    fin(tmp_path, st_, day, e)
    assert not (out / "seals" / f"{day['date']}.json").exists() and \
        [k_ for k_, *_ in slot_rows(tmp_path, sch)] == ["SLOT-MISSED"]


def test_finalizer_unexpected_error_appends_nothing(tmp_path, monkeypatch):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    e, d = E_D(st_, day, sch)
    monkeypatch.setattr(sl, "slot_times", lambda cal: (_ for _ in ()).throw(RuntimeError("unexpected")))
    with pytest.raises(SystemExit, match="refused with no row"):
        fin(tmp_path, st_, day, e)
    assert slot_rows(tmp_path, sch) == []


# ---------------------------------------------------------------- Task 7 additions (carry-forwards)
def test_evidence_check_runs_after_the_plan_check(tmp_path):                   # carry-forward 1 (Task 8 D4)
    """A root whose plan.json names another trial is refused by the F6.2 plan check, and its slot files are never
    judged as the open trial's (no TRIAL-INVALID). Moving evidence_check before the plan check fails this test."""
    import a3_helpers as h
    from conftest import _weekdays
    h.plan_only(tmp_path, c.aware(START))                          # an open trial with no journal row yet (F6.4)
    cal = _weekdays("2026-10-01", "2026-11-30")
    day = next(d for d in cal if d["date"] == "2026-10-26")
    sch = z.close_of(day["date"], cal) + timedelta(minutes=45)
    other = tmp_path / "other_root"
    src = tmp_path / "s1_out"
    plan = json.loads((src / "plan.json").read_text(encoding="utf-8"))
    (other / "s1_out").mkdir(parents=True)
    (other / "s1_out" / "plan.json").write_text(json.dumps(dict(plan, trial_id="9a1b2c3d-4e5f-4a6b-8c7d-"
                                                                             "0e1f2a3b4c5d")), encoding="utf-8")
    (other / "s1_out" / "prereg.json").write_text(json.dumps({"calendar": cal}), encoding="utf-8")   # names the slot
    _put(sl.names(other / "s1_out", sch, day["date"])["claim"], json.dumps({"op": "9" * 32, "actor": "9" * 32}))
    assert sl.evidence_problems(other / "s1_out", rows(tmp_path), cal)                    # a violation, if judged
    with pytest.raises(SystemExit, match=r"plan\.json trial_id .* differs from the AUDIT-ACK"):
        t.gate(other, "foreign root")
    assert all(x.kind != "TRIAL-INVALID" for x in rows(tmp_path))


def test_a_stalled_stage_lock_never_delays_the_finalizers_deadline_rows(tmp_path):     # carry-forward 3 (N2)
    """Ruling N2 (E1.2) for the finalizer command (s1_checkpoint.finalize_close, the journal finalizer behind a
    slot-path gate): while a REAL child process holds an unrelated seal stage's lock after its INTENT (a plain gate is
    "pending"), TIMEOUT at D and MISSED at E commit; the stalled stage stays undecided (its lock still held)."""
    st_ = registered(tmp_path)
    day, s45 = first_slot(st_)
    cal = st_["calendar"]
    s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(s45), at=s45 + timedelta(seconds=1))    # a crashed worker
    stage = "seal/2026-10-27"
    p = _hold_seal_stage(tmp_path, stage, s45 - timedelta(minutes=5))
    try:
        d45 = z.resolution_deadline(s45, day, cal)
        with _Clock(d45), pytest.raises(SystemExit, match="pending"):
            t.gate(tmp_path, "a plain gate")                         # the hazard N2 removes from the deadline path
        with _Clock(d45):
            try:
                res = ck.finalize_close(tmp_path / "s1_out", day, cal, d45, mailbox=tmp_path / "mailbox.sqlite3")
            except SystemExit as e:
                pytest.fail(f"the finalizer was refused: {e}")
        assert [k_ for k_, *_ in slot_rows(tmp_path, s45)] == ["SLOT-INTENT", "SLOT-TIMEOUT"]
        s47 = s45 + timedelta(minutes=2)
        assert [k_ for k_, *_ in slot_rows(tmp_path, s47)] == ["SLOT-MISSED"]                 # E47 < D45
        assert res["refused"] is None
        tr = t.open_trial(tmp_path / "mailbox.sqlite3")
        assert not L.lock_acquirable(tmp_path, tr.trial_id, L.stage_lock_name(stage))        # still held: undecided
        assert all(x.kind != "TRIAL-INVALID" for x in rows(tmp_path))
    finally:
        p.stdin.close()
        p.wait(timeout=60)


def test_a_damaged_qualified_tree_behind_an_in_flight_slot_is_invalid_at_the_gate(tmp_path, monkeypatch):  # N-2
    """The F3 table checks every QUALIFIED slot of a close, not only those reached in slot order: slot 47 is
    QUALIFIED behind slot 45 (INTENT-only, so the close is not determined); its damaged report is INVALID
    (registration-artifact) at the next gate, with zero callbacks and the local abort."""
    st_ = registered(tmp_path)
    day, s45 = first_slot(st_)
    s47 = s45 + timedelta(minutes=2)
    s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(s45), at=s45 + timedelta(seconds=1))
    run(tmp_path, st_, s47, s47 + timedelta(seconds=30))
    rp = sl.names(tmp_path / "s1_out", s47, day["date"])["report"]
    rp.write_text(rp.read_text(encoding="utf-8") + " ", encoding="utf-8")
    sp = Spies(monkeypatch)
    with pytest.raises(SystemExit, match=r"INVALID \(registration-artifact\)"):
        t.gate(tmp_path, "damaged later slot")
    sp.assert_zero()
    assert rows(tmp_path)[-1].subject == "reason/registration-artifact"
    assert c.load_abort(tmp_path / "s1_out")["reason"] == c.REGISTRATION_ARTIFACT


def _stopped_with_a_damaged_tree(tmp_path):
    """A QUALIFIED (sealed) slot, then a synthetic TRIAL-STOP, then the TEST damages the slot's tmp report."""
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    run(tmp_path, st_, sch, sch + timedelta(seconds=30))
    _stop_row(tmp_path, sch + timedelta(minutes=5))
    rp = sl.names(tmp_path / "s1_out", sch, day["date"])["report"]
    rp.write_text(rp.read_text(encoding="utf-8") + " ", encoding="utf-8")
    return st_, day, sch


@pytest.mark.parametrize("command", ["stop attestation", "final plan", "final snapshot"])
def test_post_stop_commands_invalidate_a_damaged_qualified_tree(tmp_path, monkeypatch, command):   # N-2
    """N-2: the stop attestation, the final plan and the final snapshot meet a damaged QUALIFIED tree: TRIAL-INVALID
    (registration-artifact), not a mere 'bad seal record' refusal."""
    st_, day, sch = _stopped_with_a_damaged_tree(tmp_path)
    at = sch + timedelta(days=3)
    with _Clock(at), pytest.raises(SystemExit, match=r"INVALID \(registration-artifact\)"):
        if command == "stop attestation":
            r.attest_stop(tmp_path, r.STOP_STATEMENT)
        elif command == "final plan":
            k.write_final_plan(tmp_path)
        else:
            ck.run_final_snapshot(tmp_path, st_["ledger"].path, now=lambda: at)
    assert rows(tmp_path)[-1].subject == "reason/registration-artifact"


def test_final_snapshot_trial_state_refuses_a_damaged_tree_without_a_traceback(tmp_path):   # carry-forward 8 (N-1)
    """N-1 (F0.7): the final snapshot's _trial_state meets a damaged QUALIFIED tree of a pending close (slot 45 TIMEOUT
    by the finalizer, slot 47 QUALIFIED with a damaged report): a SystemExit refusal through the threaded mailbox,
    never an escaping ValueError (the reviewer's repro).
    A3 Task 13 (intended, OQ-16): the final snapshot never finalizes a close (it is never sampled history), so its
    _trial_state no longer meets the tree; the property is kept at the command, which meets it in its gate (the F3
    evidence table): a SystemExit naming registration-artifact, never an escaping exception."""
    st_ = registered(tmp_path)
    cal = st_["calendar"]
    day, s45 = first_slot(st_)
    s47 = s45 + timedelta(minutes=2)
    s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(s45), at=s45 + timedelta(seconds=10))
    run(tmp_path, st_, s47, s47 + timedelta(seconds=30))
    out = tmp_path / "s1_out"
    assert not (out / "seals" / f"{day['date']}.json").exists()
    d45 = z.resolution_deadline(s45, day, cal)
    intent = j.first(j.subject_rows(rows(tmp_path), j.slot_subject(s45)), "SLOT-INTENT")
    s1_jappend(tmp_path, "SLOT-TIMEOUT", j.slot_subject(s45), op=intent.op, at=d45, due=True)
    rp = sl.names(out, s47, day["date"])["report"]
    rp.write_text(rp.read_text(encoding="utf-8") + " ", encoding="utf-8")
    pr = json.loads((out / "prereg.json").read_text(encoding="utf-8"))
    assert pr["start"]
    try:
        with _Clock(d45 + timedelta(hours=1)):
            ck.run_final_snapshot(tmp_path, tmp_path / "no_ledger.sqlite3", now=lambda: d45 + timedelta(hours=1),
                                  mailbox=tmp_path / "mailbox.sqlite3")
    except SystemExit as e:
        assert "registration-artifact" in str(e), e
    except BaseException as e:                                       # noqa: BLE001 - the N-1 defect, by assertion
        pytest.fail(f"run_final_snapshot escaped with {type(e).__name__}: {e}")
    else:
        pytest.fail("run_final_snapshot did not refuse a damaged QUALIFIED tree")
    assert not (out / "final_snapshot").exists()


def test_access_denied_on_the_slot_lock_refuses_the_cleanup_with_no_invalid(tmp_path):   # carry-forward 11
    """ERROR_ACCESS_DENIED (a directory where the slot lock file belongs) at the E1.4 cleanup probe: the TIMEOUT row
    (a journal decision, no lock) stands; the cleanup is refused (F5.5: no liveness verdict), nothing is moved, and
    there is no TRIAL-INVALID."""
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    e, d = E_D(st_, day, sch)
    row = s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(sch), at=sch + timedelta(seconds=1))
    n = sl.names(tmp_path / "s1_out", sch, day["date"])
    _put(n["claim"], json.dumps({"op": row.op, "actor": row.actor}))
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    L.lock_path(tmp_path, tr.trial_id, L.slot_lock_name(j.slot_subject(sch))).mkdir(parents=True)
    res = _fin_or_fail(tmp_path, st_, day, d)
    assert [k_ for k_, *_ in slot_rows(tmp_path, sch)] == ["SLOT-INTENT", "SLOT-TIMEOUT"]
    assert "lock error" in str(res.get("cleanup")) and n["claim"].exists()
    assert all(x.kind != "TRIAL-INVALID" for x in rows(tmp_path))


def test_access_denied_on_the_seal_stage_lock_is_a_refusal(tmp_path, monkeypatch):      # carry-forward 11
    """ERROR_ACCESS_DENIED on the seal stage lock: the seal stage is refused with no row (no INVALID); once the lock
    is usable again the stage runs."""
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    monkeypatch.setattr(sl, "run_seal_stage", lambda gv, d, cal, res=None, **k: res or {})
    run(tmp_path, st_, sch, sch + timedelta(seconds=30))
    monkeypatch.setattr(sl, "run_seal_stage", REAL_RUN_SEAL_STAGE)
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    lp = L.lock_path(tmp_path, tr.trial_id, L.stage_lock_name(f"seal/{day['date']}"))
    lp.mkdir(parents=True)
    res = _fin_or_fail(tmp_path, st_, day, sch + timedelta(minutes=1))
    assert "lock error" in str(res["refused"]) and seal_kinds(tmp_path, day["date"]) == []
    assert all(x.kind != "TRIAL-INVALID" for x in rows(tmp_path))
    lp.rmdir()
    _fin_or_fail(tmp_path, st_, day, sch + timedelta(minutes=2))
    assert seal_kinds(tmp_path, day["date"]) == ["STAGE-INTENT", "STAGE-PREPARED", "STAGE-CREATED"]


# ---------------------------------------------------------------- Task 7 fix round 1 (review I1, M2, M3)
def _start_in_the_window(monkeypatch, tmp_path, slot, day_iso, *, stray):
    """Review I1 repro: the first close_problems re-check (its rows read BEFORE it) is preceded by a later slot's
    start - a legitimate worker's SLOT-INTENT then its claim (row first, file after), or (`stray`) a claim with no
    row at all (the control: a real violation)."""
    real_cp = sl.close_problems
    out = tmp_path / "s1_out"
    fired = []

    def window(out_, rows_, day_, cal_):
        if not fired:
            fired.append(1)
            n = sl.names(out, slot, day_iso)
            if stray:
                who = {"op": "9" * 32, "actor": "9" * 32}
            else:
                row = s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(slot), at=slot + timedelta(seconds=1))
                who = {"op": row.op, "actor": row.actor}
            _put(n["claim"], json.dumps(dict(who, capture_dir=n["capture"].relative_to(out).as_posix())))
        return real_cp(out_, rows_, day_, cal_)
    monkeypatch.setattr(sl, "close_problems", window)
    return fired


@pytest.mark.parametrize("stray", [False, True], ids=["legitimate-start", "stray-claim-control"])
def test_a_worker_starting_during_the_seal_stage_recheck_is_not_a_violation(tmp_path, monkeypatch, stray):
    """Review I1 (F5.1 lesson, E1.5): run_seal_stage's F3 re-check confirms a problem on rows re-read after it was
    first observed - a later slot whose INTENT then claim land inside the window is never a violation (the seal stage
    runs); the control, a claim with no row, is still TRIAL-INVALID (registration-artifact)."""
    st_ = registered(tmp_path)
    day, s45 = first_slot(st_, 45)
    _, s47 = first_slot(st_, 47)
    monkeypatch.setattr(sl, "run_seal_stage", lambda gv, d, cal, res=None, **k: res or {})   # no seal stage yet
    run(tmp_path, st_, s45, s45 + timedelta(seconds=30))            # s45 QUALIFIED: close determined, no seal
    monkeypatch.setattr(sl, "run_seal_stage", REAL_RUN_SEAL_STAGE)
    gv = t.gate(tmp_path, "I1 seal stage", defer_pending=True)
    fired = _start_in_the_window(monkeypatch, tmp_path, s47, day["date"], stray=stray)
    at = s47 + timedelta(seconds=2)
    if stray:
        with pytest.raises(SystemExit, match=r"claim exists with no journal row .*INVALID \(registration-artifact\)"):
            REAL_RUN_SEAL_STAGE(gv, day, st_["calendar"], mailbox=tmp_path / "mailbox.sqlite3", clock=lambda: at)
        assert fired and rows(tmp_path)[-1].subject == "reason/registration-artifact"
        assert seal_kinds(tmp_path, day["date"]) == []
        return
    try:
        REAL_RUN_SEAL_STAGE(gv, day, st_["calendar"], mailbox=tmp_path / "mailbox.sqlite3", clock=lambda: at)
    except SystemExit as e:
        pytest.fail(f"a legitimate worker start inside the re-check window was refused: {e}")
    assert fired and all(x.kind != "TRIAL-INVALID" for x in rows(tmp_path))
    assert seal_kinds(tmp_path, day["date"]) == ["STAGE-INTENT", "STAGE-PREPARED", "STAGE-CREATED"]


@pytest.mark.parametrize("stray", [False, True], ids=["legitimate-start", "stray-claim-control"])
def test_a_worker_starting_during_the_opening_recheck_is_not_a_violation(tmp_path, monkeypatch, stray):
    """Review I1, opening twin (s1_checkpoint.run_opening_checkpoint's F3 re-check of the opening close before the
    selection): a later opening slot's INTENT then claim inside the window never invalidates (the opening seal is
    written); the control, a claim with no row, is TRIAL-INVALID (registration-artifact) and no opening seal."""
    from conftest import Ledger, s1_opening_checkpoint, s1_plan_audit
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    day = next(d for d in cal if d["date"] == oc)
    s47 = z.close_of(oc, cal) + timedelta(minutes=47)
    fired = _start_in_the_window(monkeypatch, tmp_path, s47, oc, stray=stray)
    seal = tmp_path / "s1_out" / "seals" / f"{oc}.json"
    if stray:
        with pytest.raises(SystemExit, match=r"claim exists with no journal row .*INVALID \(registration-artifact\)"):
            s1_opening_checkpoint(tmp_path, Ledger(tmp_path / "l.sqlite3"), oc, cal, S1_RECEIPT)
        assert fired and rows(tmp_path)[-1].subject == "reason/registration-artifact" and not seal.exists()
        return
    try:
        rep = s1_opening_checkpoint(tmp_path, Ledger(tmp_path / "l.sqlite3"), oc, cal, S1_RECEIPT)
    except SystemExit as e:
        pytest.fail(f"a legitimate opening-slot start inside the re-check window was refused: {e}")
    assert fired and rep["seal"]["written"] and seal.exists() and day["date"] == oc
    assert all(x.kind != "TRIAL-INVALID" for x in rows(tmp_path))


def test_a_journal_read_error_in_the_gate_hook_is_a_refusal(tmp_path, monkeypatch):
    """Review M2 (F0.7): the F3 hook's own journal reads failing (an outage after the gate's read) refuse with no
    row - a SystemExit refusal, never an escaping JournalError."""
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    run(tmp_path, st_, sch, sch + timedelta(seconds=30))             # slot rows exist: the hook reads the journal

    import inspect
    real = j.read_trial

    def outage_in_the_hook(*a, **k):                                 # the gate's own read succeeds; the hook's fails
        if any(f.function == "evidence_check" or f.function == "_read_rows" for f in inspect.stack()[1:4]):
            raise j.Outage("mailbox unreadable (OperationalError)")
        return real(*a, **k)
    monkeypatch.setattr(j, "read_trial", outage_in_the_hook)
    try:
        with pytest.raises(SystemExit, match=r"journal unreadable .*refused with no row"):
            t.gate(tmp_path, "M2 outage")
    except j.JournalError as e:                                      # the defect, by assertion (B3)
        pytest.fail(f"the hook let a JournalError escape: {e!r}")


def test_slot_rows_without_a_calendar_fail_closed(tmp_path, monkeypatch):
    """Review M3 (fail closed): slot rows exist but no registered calendar can be read - the F3 table cannot run, so
    the gate refuses with no row (no TRIAL-INVALID); with no slot row and no file there is nothing to judge."""
    from conftest import s1_plan_audit
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)             # an open trial with audit rows, no slot row yet
    real_cal = sl._calendar
    monkeypatch.setattr(sl, "_calendar", lambda gv: None)
    t.gate(tmp_path, "M3 control: no slot row yet")                  # nothing to judge: passes
    monkeypatch.setattr(sl, "_calendar", real_cal)
    sch = z.close_of(oc, cal) + timedelta(minutes=45)
    s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(sch), at=sch + timedelta(seconds=1))
    monkeypatch.setattr(sl, "_calendar", lambda gv: None)
    with pytest.raises(SystemExit, match=r"no registered calendar .*fail closed"):
        t.gate(tmp_path, "M3 no calendar")
    assert all(x.kind != "TRIAL-INVALID" for x in rows(tmp_path))
