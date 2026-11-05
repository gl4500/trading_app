"""Addendum 3 rev 5 F3 (slot rows: P, R, J; QUALIFIED/FAILED details; restart), F0.5 LOST-RACE, F1 post-stop,
F5.1 slot lock order, F7.4 PREREG-ACK. Behavioural RED against the Task 6 stub (s1_evidence/a3/t6_red.txt).
Synthetic ledgers and journals; tmp mailbox; spies; real child processes only where a crash or a live owner is
needed. Task 6 additions (after the plan's list): Erratum 1 E1.2 / ruling N2 (a held stage lock never blocks the
slot path or the deadline rows), the slot lock's F5.5 results (held -> pending, ERROR_ACCESS_DENIED -> refusal),
the opening gate (F1, E5.6) and the fail-closed slot gate."""
import json
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
import s1_checkpoint as ck
import s1_common as c
import s1_journal as j
import s1_locks as L
import s1_run as r
import s1_seal as z
import s1_slot as sl
import s1_trial as t
from conftest import (S1_PROCESS, S1_RECEIPT, Ledger, Spies, _Clock, s1_ack, s1_jappend, s1_opening_checkpoint,
                      s1_plan_audit, s1_state)

START = "2026-10-26T13:30:00+00:00"
HERE = Path(__file__).resolve().parent.parent
HELPERS = Path(__file__).resolve().parent / "a3_helpers.py"


def registered(tmp_path):
    st_ = s1_state(tmp_path, START)
    with _Clock(st_["prereg_at"]):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    s1_ack(tmp_path, "prereg-ack", "S1-PREREG-ACK", st_["prereg_at"] + timedelta(minutes=1))
    return st_


def first_slot(st_, minutes=45):
    day = next(d for d in st_["calendar"] if d["date"] == "2026-10-26")
    return day, z.close_of(day["date"], st_["calendar"]) + timedelta(minutes=minutes)


def run(tmp_path, st_, sch, at, sp=None, receipt=S1_RECEIPT):
    if sp is None:
        rec, proc = (lambda reference=None: json.loads(json.dumps(receipt))), (lambda: dict(S1_PROCESS))
    else:
        rec, proc = sp.receipt(receipt), sp.process()
    with _Clock(at):
        return ck.run_checkpoint(tmp_path, st_["ledger"].path, sch, rec, proc, tmp_path / "crash.log", now=lambda: at)


def rows(tmp_path):
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    return j.read_trial(tr.trial_id, tr.genesis, tmp_path / "mailbox.sqlite3")


def slot_rows(tmp_path, sch):
    return [(x.kind, x.op, x.actor, x.at, x.detail) for x in j.subject_rows(rows(tmp_path), j.slot_subject(sch))]


def test_qualified_at_is_r_and_detail_is_the_tree_manifest(tmp_path, monkeypatch):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    at = sch + timedelta(seconds=30)
    run(tmp_path, st_, sch, at)
    got = slot_rows(tmp_path, sch)
    assert [k_ for k_, *_ in got] == ["SLOT-INTENT", "SLOT-QUALIFIED"]
    (k1, op1, act1, _, _), (k2, op2, act2, at2, det2) = got
    assert (op2, act2) == (op1, act1) and at2 == j.fmt_at(at)                      # R = the clock after P
    tree = sl.qualified_tree(tmp_path / "s1_out", sch, day["date"])
    assert set(tree) == {f"captures/2026-10-26/{sch:%Y%m%dT%H%M%SZ}.report.json",
                         f"captures/2026-10-26/{sch:%Y%m%dT%H%M%SZ}.resolution.json",
                         f"captures/2026-10-26/{sch:%Y%m%dT%H%M%SZ}/backup.sqlite3",        # E5.6: raw bytes
                         f"captures/2026-10-26/{sch:%Y%m%dT%H%M%SZ}/meta.json",
                         f"captures/2026-10-26/{sch:%Y%m%dT%H%M%SZ}/projection.json"}
    assert det2 == j.detail_of(tree)
    for rel in tree:                                               # OQ-10: JSON records carry op/actor
        if rel.endswith((".report.json", ".resolution.json")):
            rec = json.loads((tmp_path / "s1_out" / rel).read_text(encoding="utf-8"))
            assert (rec["op"], rec["actor"]) == (op1, act1)


def test_claim_names_its_capture_dir_and_the_report_is_bound(tmp_path):              # row 311 (OQ-10), row 70
    """Revision 2: the r1 `seals_checked` report field is gone (E2.7 r3); the report is still frozen before J and
    bound by the QUALIFIED tree."""
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    out = tmp_path / "s1_out"
    run(tmp_path, st_, sch, sch + timedelta(seconds=30))
    n = sl.names(out, sch, day["date"])
    rep = json.loads(n["report"].read_text(encoding="utf-8"))
    assert "seals_checked" not in rep
    claim = json.loads(n["claim"].read_text(encoding="utf-8"))
    assert claim.get("capture_dir") == n["capture"].relative_to(out).as_posix()      # OQ-10 ruling
    det = slot_rows(tmp_path, sch)[1][4]
    n["report"].write_text(json.dumps(dict(rep, note="x"), indent=1), encoding="utf-8")   # the TEST edits its tmp
    assert j.detail_of(sl.qualified_tree(out, sch, day["date"])) != det              # bound by the tree


@pytest.mark.parametrize("damage", ["deleted", "tampered"])
def test_after_json_is_display_only(tmp_path, damage):                                 # row 264 (E5.2)
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    out = tmp_path / "s1_out"
    run(tmp_path, st_, sch, sch + timedelta(seconds=30))
    probe = lambda: (sl.required_seals(out, rows(tmp_path)),                                # noqa: E731
                     r._capture_seal_problems(out, rows(tmp_path), st_["calendar"]),
                     c._report_seals(out, rows(tmp_path), st_["calendar"]))
    before = probe()
    after = sl.names(out, sch, day["date"])["capture"].parent / f"{sch:%Y%m%dT%H%M%SZ}.after.json"
    assert after.is_file()                                         # (Task 6: the display-only record is written)
    if damage == "deleted":
        after.unlink()
    else:
        after.write_text(json.dumps({"seal": {"written": True, "sha256": "0" * 64}}), encoding="utf-8")
    assert probe() == before
    t.gate(tmp_path, "after.json is display-only")                  # no refusal, no INVALID


@pytest.mark.parametrize("subtype", ["receipt", "binding", "fence"])
def test_established_violation_is_external_first_with_subtype(tmp_path, monkeypatch, subtype):   # row 308
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    out = tmp_path / "s1_out"
    order = []
    real_inv, real_abort = t.invalidate, ck._write_abort
    monkeypatch.setattr(t, "invalidate", lambda *a, **k: (order.append(("invalid", (out / "aborted.json").exists())),
                                                           real_inv(*a, **k))[1])
    monkeypatch.setattr(ck, "_write_abort", lambda *a, **k: (order.append(("abort", None)), real_abort(*a, **k))[1])
    if subtype == "receipt":                                        # the observation, not the predicate, is forced
        real_receipt = ck._receipt

        def changed(rep, *a, **k):
            got = real_receipt(rep, *a, **k)
            rep["receipt_match"] = False
            return got
        monkeypatch.setattr(ck, "_receipt", changed)
    elif subtype == "binding":
        monkeypatch.setattr(ck, "_binding", lambda *a, **k: True)
    else:
        monkeypatch.setattr(z, "check_fences", lambda seals, proj: ["fence: synthetic violation"])
    run(tmp_path, st_, sch, sch + timedelta(seconds=30))
    assert order and order[0] == ("invalid", False) and ("abort", None) in order[1:]          # external first
    inv = j.first(rows(tmp_path), "TRIAL-INVALID")
    assert inv is not None and inv.subject == "reason/established-violation"
    obs = json.loads((out / "invalid" / f"{inv.seq}.json").read_text(encoding="utf-8"))
    assert obs["subtype"] == subtype and obs["legacy_reason"]
    assert j.first(j.subject_rows(rows(tmp_path), j.slot_subject(sch)), "SLOT-QUALIFIED", "SLOT-FAILED") is None


@pytest.mark.parametrize("offset", ["s-1us", "s", "E-1us", "E", "E+1us"])
def test_clock_boundaries_before_capture(tmp_path, monkeypatch, offset):               # row 310 (OQ-33)
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    e = z.eligible_until(sch, day, st_["calendar"])
    us = timedelta(microseconds=1)
    at = {"s-1us": sch - us, "s": sch, "E-1us": e - us, "E": e, "E+1us": e + us}[offset]
    captured = []
    real = ck._capture
    monkeypatch.setattr(ck, "_capture", lambda *a, **k: (captured.append(1), real(*a, **k))[1])
    n = sl.names(tmp_path / "s1_out", sch, day["date"])
    if offset in ("E", "E+1us"):
        with pytest.raises(SystemExit, match="now >= E"):
            run(tmp_path, st_, sch, at)
        assert slot_rows(tmp_path, sch) == [] and not n["claim"].exists() and captured == []
    elif offset == "s-1us":
        run(tmp_path, st_, sch, at)
        assert [k_ for k_, *_ in slot_rows(tmp_path, sch)] == ["SLOT-INTENT", "SLOT-FAILED"]
        assert n["claim"].exists() and captured == []
    else:
        run(tmp_path, st_, sch, at)
        assert captured == [1] and [k_ for k_, *_ in slot_rows(tmp_path, sch)][:1] == ["SLOT-INTENT"]


def test_failed_detail_binds_the_claim_and_the_failure_report(tmp_path):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    run(tmp_path, st_, sch, sch - timedelta(seconds=5))           # an early invocation: clock before s -> FAILURE
    got = slot_rows(tmp_path, sch)
    assert [k_ for k_, *_ in got] == ["SLOT-INTENT", "SLOT-FAILED"]
    assert got[1][4] == j.detail_of(sl.failed_tree(tmp_path / "s1_out", sch, day["date"]))


def test_slot_intent_at_or_after_e_refuses_with_no_row_and_no_capture(tmp_path, monkeypatch):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    sp = Spies(monkeypatch)
    with pytest.raises(SystemExit, match="now >= E"):
        run(tmp_path, st_, sch, z.eligible_until(sch, day, st_["calendar"]), sp)
    sp.assert_zero()
    assert slot_rows(tmp_path, sch) == [] and not sl.names(tmp_path / "s1_out", sch, day["date"])["claim"].exists()


def test_lost_race_moves_only_own_uncommitted_files_to_late(tmp_path, monkeypatch):
    """A synthetic TIMEOUT row is committed between this worker's P and J (with F5 a live lock-holding worker
    excludes the finalizer; the row is forced to prove that the journal decides even then)."""
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    out = tmp_path / "s1_out"
    real = sl.Worker._append

    def racing(self, req):
        if req.kind == "SLOT-QUALIFIED":
            intent = j.first(j.subject_rows(rows(tmp_path), self.subject), "SLOT-INTENT")
            s1_jappend(tmp_path, "SLOT-TIMEOUT", self.subject, op=intent.op, at=req.r_at, due=True)
        return real(self, req)
    monkeypatch.setattr(sl.Worker, "_append", racing)
    res = run(tmp_path, st_, sch, sch + timedelta(seconds=30))
    assert (res.get("journal") or {}).get("outcome") == "LOST-RACE"
    n = sl.names(out, sch, day["date"])
    late = out / "late" / day["date"] / f"{sch:%Y%m%dT%H%M%SZ}"
    assert not n["claim"].exists() and not n["capture"].exists() and (late / n["claim"].name).exists()
    assert not (out / "seals" / f"{day['date']}.json").exists()
    assert [k_ for k_, *_ in slot_rows(tmp_path, sch)] == ["SLOT-INTENT", "SLOT-TIMEOUT"]
    assert all(x.kind != "TRIAL-INVALID" for x in rows(tmp_path))
    assert res["journal"]["recheck"] == []      # the winner's (TIMEOUT) evidence re-checked by the real F3 table
    seal = out / "seals" / f"{day['date']}.json"            # (Task 7, review M3) control: the same re-check is not
    seal.parent.mkdir(parents=True, exist_ok=True)          # vacuous - a seal citing the TIMEOUT slot is a violation
    seal.write_text(json.dumps({"capture": {"scheduled": sch.isoformat()}}), encoding="utf-8")
    assert sl.slot_problems(out, rows(tmp_path), j.slot_subject(sch), st_["calendar"]) != []


CRASH_AFTER_P = r'''
import json, os, sys
from datetime import datetime
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[1] + "/s1_tests")
import s1_common as c, s1_checkpoint as ck, s1_journal as j
c.MAILBOX = sys.argv[2] + "/mailbox.sqlite3"
at = c.aware(sys.argv[4]); c.now_utc = lambda: at
real = j.append
def crash(trial_id, gen, req, ctx_fn, **kw):
    if req.kind == "SLOT-QUALIFIED":
        os._exit(9)                                          # a real crash after P, before J
    return real(trial_id, gen, req, ctx_fn, **kw)
j.append = crash
from conftest import S1_RECEIPT, S1_PROCESS
ck.run_checkpoint(sys.argv[2], sys.argv[3], c.aware(sys.argv[5]), lambda reference=None: S1_RECEIPT,
                  lambda: dict(S1_PROCESS), sys.argv[2] + "/crash.log", now=lambda: at)
'''


def test_restart_after_a_worker_crash_never_appends_qualified(tmp_path):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    at = sch + timedelta(seconds=30)
    p = subprocess.run([sys.executable, "-I", "-c", CRASH_AFTER_P, str(HERE), str(tmp_path), str(st_["ledger"].path),
                        at.isoformat(), sch.isoformat()], capture_output=True, text=True, timeout=120)
    assert p.returncode == 9, p.stderr
    assert [k_ for k_, *_ in slot_rows(tmp_path, sch)] == ["SLOT-INTENT"]
    with pytest.raises(SystemExit, match="never re-intents"):
        run(tmp_path, st_, sch, at + timedelta(seconds=30))
    assert [k_ for k_, *_ in slot_rows(tmp_path, sch)] == ["SLOT-INTENT"]


def _stop(tmp_path, at):
    s1_jappend(tmp_path, "TRIAL-STOP", "trial", at=at, detail=j.detail_of({"synthetic": "stop"}))


def test_post_stop_new_slot_intent_is_lost_race_with_no_capture(tmp_path, monkeypatch):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    _stop(tmp_path, sch - timedelta(minutes=1))
    sp = Spies(monkeypatch)
    res = run(tmp_path, st_, sch, sch + timedelta(seconds=30), sp)
    assert res.get("outcome") == "LOST-RACE"
    sp.assert_zero()
    assert slot_rows(tmp_path, sch) == [] and not (tmp_path / "s1_out" / "captures" / day["date"]).exists()


def test_post_stop_repeat_slot_intent_is_invalid_repeat_attempt(tmp_path):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    run(tmp_path, st_, sch, sch + timedelta(seconds=30))
    _stop(tmp_path, sch + timedelta(minutes=5))
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    res = j.append(tr.trial_id, tr.genesis, j.Request("SLOT-INTENT", j.slot_subject(sch), j.new_nonce(),
                                                       j.new_nonce()),
                   t.product_context(tr, st_["calendar"]), mailbox=tmp_path / "mailbox.sqlite3",
                   clock=lambda: sch + timedelta(minutes=6))
    assert (res.outcome, res.reason) == ("INVALIDATE", "repeat-attempt")


def test_new_slot_intent_after_a_terminal_row_is_invalid_repeat_attempt(tmp_path):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    run(tmp_path, st_, sch, sch + timedelta(seconds=30))
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    res = j.append(tr.trial_id, tr.genesis, j.Request("SLOT-INTENT", j.slot_subject(sch), j.new_nonce(),
                                                       j.new_nonce()),
                   t.product_context(tr, st_["calendar"]), mailbox=tmp_path / "mailbox.sqlite3",
                   clock=lambda: sch + timedelta(minutes=1))
    assert (res.outcome, res.reason) == ("INVALIDATE", "repeat-attempt")


@pytest.mark.parametrize("who", ["no-intent", "foreign-op", "foreign-actor"])
def test_foreign_qualified_is_invalid_even_on_a_terminal_slot(tmp_path, who):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    run(tmp_path, st_, sch, sch + timedelta(seconds=30))            # QUALIFIED: terminal
    sub = j.slot_subject(sch if who != "no-intent" else sch + timedelta(minutes=2))
    intent = j.first(j.subject_rows(rows(tmp_path), j.slot_subject(sch)), "SLOT-INTENT")
    assert j.first(j.subject_rows(rows(tmp_path), j.slot_subject(sch)), "SLOT-QUALIFIED") is not None
    op = intent.op if who == "foreign-actor" else j.new_nonce()
    actor = intent.actor if who == "foreign-op" else j.new_nonce()
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    res = j.append(tr.trial_id, tr.genesis, j.Request("SLOT-QUALIFIED", sub, op, actor, detail="1" * 64,
                                                       r_at=sch + timedelta(minutes=1)),
                   t.product_context(tr, st_["calendar"]), mailbox=tmp_path / "mailbox.sqlite3",
                   clock=lambda: sch + timedelta(minutes=1))
    assert (res.outcome, res.reason) == ("INVALIDATE", "contradictory-completion")


def test_post_start_capture_requires_the_prereg_ack(tmp_path, monkeypatch):
    st_ = s1_state(tmp_path, START)
    with _Clock(st_["prereg_at"]):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    day, sch = first_slot(st_)
    sp = Spies(monkeypatch)
    with pytest.raises(SystemExit, match="PREREG-ACK"):
        run(tmp_path, st_, sch, sch + timedelta(seconds=30), sp)
    sp.assert_zero()
    assert slot_rows(tmp_path, sch) == []
    s1_ack(tmp_path, "prereg-ack", "S1-PREREG-ACK", st_["prereg_at"] + timedelta(minutes=1))
    run(tmp_path, st_, sch + timedelta(minutes=2), sch + timedelta(minutes=2, seconds=30))
    assert [k_ for k_, *_ in slot_rows(tmp_path, sch + timedelta(minutes=2))][0] == "SLOT-INTENT"


def test_slot_lock_is_taken_before_the_journal_read(tmp_path, monkeypatch):
    """Row 130: lock < (pre-check) read < INTENT append < QUALIFIED append < release. Task 6 adds the read spy."""
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    order = []
    real_acq, real_rel, real_app, real_read = L.OwnershipLock.acquire, L.OwnershipLock.release, j.append, j.read_trial
    monkeypatch.setattr(L.OwnershipLock, "acquire", lambda self: order.append(("lock", self.path.name))
                        or real_acq(self))
    monkeypatch.setattr(L.OwnershipLock, "release", lambda self: order.append(("release", self.path.name))
                        or real_rel(self))
    monkeypatch.setattr(j, "append", lambda *a, **kw: order.append(("append", a[2].kind)) or real_app(*a, **kw))
    monkeypatch.setattr(j, "read_trial", lambda *a, **kw: order.append(("read", None)) or real_read(*a, **kw))
    run(tmp_path, st_, sch, sch + timedelta(seconds=30))
    name = L.slot_lock_name(j.slot_subject(sch)) + ".lock"
    assert ("lock", name) in order
    i = order.index(("lock", name))
    assert ("read", None) in order[i + 1:order.index(("append", "SLOT-INTENT"))]           # the pre-check read
    assert order.index(("append", "SLOT-INTENT")) > i and order.index(("append", "SLOT-QUALIFIED")) > i
    assert order.index(("release", name)) > order.index(("append", "SLOT-QUALIFIED"))


# ---------------------------------------------------------------- Task 6 additions (F5.5, E1.2 / N2, F1 opening)
def test_a_held_slot_lock_is_pending_with_no_row_and_no_work(tmp_path, monkeypatch):
    """F5.5: LockHeld (here: this test holds the slot lock through another handle, a sharing violation) is the only
    liveness evidence: the worker refuses "pending" with no row, no claim and zero callbacks."""
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    held = L.OwnershipLock(tmp_path, tr.trial_id, L.slot_lock_name(j.slot_subject(sch))).acquire()
    try:
        sp = Spies(monkeypatch)
        with pytest.raises(SystemExit, match="pending - another process owns this slot"):
            run(tmp_path, st_, sch, sch + timedelta(seconds=30), sp)
        sp.assert_zero()
    finally:
        held.release()
    assert slot_rows(tmp_path, sch) == [] and not sl.names(tmp_path / "s1_out", sch, day["date"])["claim"].exists()


def test_slot_lock_access_denied_is_a_refusal_with_no_row(tmp_path, monkeypatch):
    """F5.5 + Task 3 carry-forward: a slot lock path that is a directory gives ERROR_ACCESS_DENIED (Windows error 5)
    from CreateFileW - LockError: refused with no row, never 'pending', never INVALID, no claim, zero callbacks."""
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    lp = L.lock_path(tmp_path, tr.trial_id, L.slot_lock_name(j.slot_subject(sch)))
    lp.mkdir(parents=True)                                     # an I/O error, not a sharing violation
    sp = Spies(monkeypatch)
    with pytest.raises(SystemExit, match=r"lock error .*Windows error 5\b.*refused with no row"):
        run(tmp_path, st_, sch, sch + timedelta(seconds=30), sp)
    sp.assert_zero()
    assert slot_rows(tmp_path, sch) == [] and not sl.names(tmp_path / "s1_out", sch, day["date"])["claim"].exists()
    assert all(x.kind != "TRIAL-INVALID" for x in rows(tmp_path))


def test_a_missing_slot_gate_fails_closed(tmp_path, monkeypatch):
    """Task 2/5 carry-forward: a Worker given no slot gate cannot open a slot (decide step 5 refuses, no row)."""
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    with _Clock(sch + timedelta(seconds=30)):
        gv = t.gate(tmp_path, "missing slot gate")
        w = sl.Worker(gv, sch, day, st_["calendar"], slot_gate=None, now=lambda: sch + timedelta(seconds=30))
        with w, pytest.raises(SystemExit, match="no slot gate supplied"):
            w.intent()
    assert slot_rows(tmp_path, sch) == []


def _hold_seal_stage(tmp_path, stage, at):
    """A REAL child process appends seal stage `stage`'s STAGE-INTENT and then holds its stage lock (alive, blocked
    on stdin) - a stalled stage owner (F5.4: a real process, no mocked live flag)."""
    p = subprocess.Popen([sys.executable, "-I", str(HELPERS), str(tmp_path), stage, "hold-after-intent", at.isoformat()],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "held", p.stderr.read()
    return p


def test_a_held_stage_lock_never_blocks_the_slot_path_or_the_deadline_rows(tmp_path, monkeypatch):
    """Ruling N2 (Erratum 1 E1.2): while a stalled stage owner holds an unrelated stage lock (a plain gate reads
    "pending"), the slot worker still captures and commits (its gate defers that pending stage); a worker whose R
    reaches D gets REFUSE with no row (never "pending"); at D the finalizer's SLOT-TIMEOUT and at E a SLOT-MISSED
    commit (the journal arbitrates; no lock is read). The stalled stage itself is left undecided (its lock is still
    held afterwards)."""
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    cal = st_["calendar"]
    stage = "seal/2026-10-27"                                      # an unrelated (later-close) seal stage
    p = _hold_seal_stage(tmp_path, stage, sch - timedelta(minutes=5))
    try:
        tr = t.open_trial(tmp_path / "mailbox.sqlite3")
        with _Clock(sch), pytest.raises(SystemExit, match="pending"):
            t.gate(tmp_path, "a plain gate")                       # the hazard: every plain gate is pending
        with _Clock(sch):
            try:
                gv = t.gate(tmp_path, "slot path", defer_pending=True)
            except SystemExit as e:
                pytest.fail(f"the slot-path gate was refused: {e}")
        assert gv.deferred == [stage]
        try:
            run(tmp_path, st_, sch, sch + timedelta(seconds=30))   # (1) the slot worker is not refused "pending"
        except SystemExit as e:
            pytest.fail(f"the slot path was refused: {e}")
        assert [k_ for k_, *_ in slot_rows(tmp_path, sch)] == ["SLOT-INTENT", "SLOT-QUALIFIED"]
        # (2) a late R: the clock reaches D just before the report (the last file of P) is published
        sch2 = sch + timedelta(minutes=2)
        d2, e2 = z.resolution_deadline(sch2, day, cal), z.eligible_until(sch2, day, cal)
        clock = [sch2 + timedelta(seconds=30)]
        real = c.publish_exclusive

        def late(path, data):
            if Path(path).name == f"{sch2:%Y%m%dT%H%M%SZ}.report.json":
                clock[0] = d2
            return real(path, data)
        monkeypatch.setattr(c, "publish_exclusive", late)
        with _Clock(clock[0]):
            res = ck.run_checkpoint(tmp_path, st_["ledger"].path, sch2, lambda reference=None: S1_RECEIPT,
                                    lambda: dict(S1_PROCESS), tmp_path / "crash.log", now=lambda: clock[0])
        monkeypatch.setattr(c, "publish_exclusive", real)
        assert res["journal"]["outcome"] == "REFUSE" and "late R" in res["journal"]["reason"]
        assert [k_ for k_, *_ in slot_rows(tmp_path, sch2)] == ["SLOT-INTENT"]
        # (3) the finalizer's deadline rows (Task 7 builds the finalizer; here its two appends, through the product
        # context, while the stage lock is still held): TIMEOUT at D, MISSED at E of a never-opened slot
        intent2 = j.first(j.subject_rows(rows(tmp_path), j.slot_subject(sch2)), "SLOT-INTENT")
        timeout = j.append(tr.trial_id, tr.genesis, j.Request("SLOT-TIMEOUT", j.slot_subject(sch2), intent2.op,
                                                              j.new_nonce()),
                           t.product_context(tr, cal), mailbox=tmp_path / "mailbox.sqlite3", clock=lambda: d2)
        assert timeout.outcome == "APPEND", timeout
        sch3 = sch + timedelta(minutes=4)
        e3 = z.eligible_until(sch3, day, cal)
        missed = j.append(tr.trial_id, tr.genesis, j.Request("SLOT-MISSED", j.slot_subject(sch3), j.new_nonce(),
                                                             j.new_nonce()),
                          t.product_context(tr, cal), mailbox=tmp_path / "mailbox.sqlite3", clock=lambda: e3)
        assert missed.outcome == "APPEND", missed
        assert e2 < d2 and [k_ for k_, *_ in slot_rows(tmp_path, sch2)] == ["SLOT-INTENT", "SLOT-TIMEOUT"]
        assert [k_ for k_, *_ in slot_rows(tmp_path, sch3)] == ["SLOT-MISSED"]
        assert not L.lock_acquirable(tmp_path, tr.trial_id, L.stage_lock_name(stage))     # still held: undecided
        assert all(x.kind != "TRIAL-INVALID" for x in rows(tmp_path))
    finally:
        p.stdin.close()
        p.wait(timeout=60)


def test_a_stage_lock_error_is_never_deferred(tmp_path, monkeypatch):
    """N2 is narrow: only a HELD stage lock is deferred by the slot path; a stage lock I/O error (F5.5) still
    refuses the slot path with no row."""
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    stage = "seal/2026-10-27"
    s1_jappend(tmp_path, "STAGE-INTENT", j.stage_subject(stage), at=sch - timedelta(minutes=5),
               detail=j.detail_of({"synthetic": "seal intent"}))
    lp = L.lock_path(tmp_path, tr.trial_id, L.stage_lock_name(stage))
    lp.mkdir(parents=True)
    with pytest.raises(SystemExit, match=r"lock error .*Windows error 5\b"):
        run(tmp_path, st_, sch, sch + timedelta(seconds=30))
    assert slot_rows(tmp_path, sch) == []


def _opening(tmp_path):
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    return start, cal, oc, Ledger(tmp_path / "opening_ledger.sqlite3")


def test_an_opening_slot_after_the_opening_is_decided_is_refused_with_no_row(tmp_path):
    """F1 ('stage gates and ACKs apply') + E5.6, replacing fix round 5 R-3: once the opening seal exists, a later
    opening-close slot is refused by the opening gate with no row, no claim and no report."""
    start, cal, oc, lg = _opening(tmp_path)
    assert s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT)["seal"]["written"]
    sch2 = z.close_of(oc, cal) + timedelta(minutes=47)
    with pytest.raises(SystemExit, match="the opening is already decided"):
        s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT, minutes=47)
    assert slot_rows(tmp_path, sch2) == []
    assert not sl.names(tmp_path / "s1_out", sch2, oc)["claim"].exists()


def test_an_opening_slot_needs_the_created_audit_stage(tmp_path, monkeypatch):
    """F1: the opening capture needs the audit stage CREATED in the journal (no audit rows: refused, no row)."""
    start, cal, oc, _ = s1_plan_audit(tmp_path, START, journal=False)
    sp = Spies(monkeypatch)
    with pytest.raises(SystemExit, match="the audit stage is not CREATED"):
        s1_opening_checkpoint(tmp_path, Ledger(tmp_path / "opening_ledger.sqlite3"), oc, cal, S1_RECEIPT)
    sp.assert_zero()
    sch = z.close_of(oc, cal) + timedelta(minutes=45)
    assert slot_rows(tmp_path, sch) == [] and not sl.names(tmp_path / "s1_out", sch, oc)["claim"].exists()


# ---------------------------------------------------------------- Task 6 fix round 1 (review C1, C2, I1)
def _late_r_45(tmp_path, st_, monkeypatch, s45, d45):
    """Slot 45's worker publishes P, then its clock reaches D before R: SLOT-QUALIFIED is refused (late R)."""
    real_pub = c.publish_exclusive
    clock = [s45 + timedelta(seconds=30)]

    def pub(path, data):
        if Path(path).name == f"{s45:%Y%m%dT%H%M%SZ}.report.json":
            clock[0] = d45
        return real_pub(path, data)
    monkeypatch.setattr(c, "publish_exclusive", pub)
    with _Clock(clock[0]):
        rep = ck.run_checkpoint(tmp_path, st_["ledger"].path, s45, lambda reference=None: S1_RECEIPT,
                                lambda: dict(S1_PROCESS), tmp_path / "crash.log", now=lambda: clock[0])
    monkeypatch.setattr(c, "publish_exclusive", real_pub)
    return rep


def test_finalize_pending_never_seals_a_slot_without_a_qualified_row(tmp_path, monkeypatch):
    """Review C1 (F3, A2 B1.3, E1.2, E1.4): a worker whose R reaches D keeps its SUCCESS P but has no SLOT-QUALIFIED
    row; finalize_pending (stop attestation / final plan / final snapshot) selects from the journal: no seal from that
    slot, and no TIMEOUT or MISSED file is written into any slot of the close."""
    st_ = registered(tmp_path)
    day, s45 = first_slot(st_)
    cal = st_["calendar"]
    rep = _late_r_45(tmp_path, st_, monkeypatch, s45, z.resolution_deadline(s45, day, cal))
    assert rep["journal"]["outcome"] == "REFUSE" and [k_ for k_, *_ in slot_rows(tmp_path, s45)] == ["SLOT-INTENT"]
    out = tmp_path / "s1_out"
    files = lambda: sorted(p.relative_to(out).as_posix() for p in (out / "captures").rglob("*"))   # noqa: E731
    before = files()
    pr = json.loads((out / "prereg.json").read_text(encoding="utf-8"))
    ck.finalize_pending(out, cal, c.aware(pr["start"]), z.window_end(day, cal) + timedelta(hours=1))
    assert not (out / "seals" / f"{day['date']}.json").exists()
    # A3 Task 7 (E1.2, E1.4, OQ-13): the journal finalizer appends slot 45's TIMEOUT (past D, no QUALIFIED) and,
    # the worker being gone, moves its leftovers to late/; nothing is ever written INTO a slot
    assert [k_ for k_, *_ in slot_rows(tmp_path, s45)] == ["SLOT-INTENT", "SLOT-TIMEOUT"]
    assert set(files()) <= set(before)                         # no file written into a live or no-row slot
    late = out / "late" / day["date"] / f"{s45:%Y%m%dT%H%M%SZ}"
    gone = {Path(x).name for x in set(before) - set(files()) if x.count("/") == 2}
    assert gone and gone <= {p.name for p in late.iterdir()}   # the losing op's own files, in late/ (never selectable)


def test_an_in_flight_earlier_slot_defers_the_seal_even_past_its_d(tmp_path, monkeypatch):
    """Review C2 (E1.3, E1.7, E2.2, A2 B1.4): slot 45's worker publishes P with R < D45, then stalls before J; slot 47
    qualifies after D45. Slot 45 has no terminal row, so the selection defers (an INTENT-only slot is not terminal);
    slot 45's QUALIFIED then commits (no TIMEOUT exists) and the seal is slot 45's - the first QUALIFIED in slot
    order."""
    st_ = registered(tmp_path)
    day, s45 = first_slot(st_)
    cal = st_["calendar"]
    s47 = s45 + timedelta(minutes=2)
    d45 = z.resolution_deadline(s45, day, cal)
    real_append, real_pub = sl.Worker._append, c.publish_exclusive
    clock47 = [s47 + timedelta(seconds=30)]
    nested = {}

    def pub47(path, data):
        if Path(path).name == f"{s47:%Y%m%dT%H%M%SZ}.report.json":
            clock47[0] = d45 + timedelta(seconds=30)
        return real_pub(path, data)

    def stalled(self, req):
        if req.kind == "SLOT-QUALIFIED" and req.subject == j.slot_subject(s45) and "done" not in nested:
            nested["done"] = True
            assert req.r_at < d45
            monkeypatch.setattr(c, "publish_exclusive", pub47)
            with _Clock(clock47[0]):
                nested["r47"] = ck.run_checkpoint(tmp_path, st_["ledger"].path, s47, lambda reference=None: S1_RECEIPT,
                                                  lambda: dict(S1_PROCESS), tmp_path / "crash.log",
                                                  now=lambda: clock47[0])
            monkeypatch.setattr(c, "publish_exclusive", real_pub)
        return real_append(self, req)
    monkeypatch.setattr(sl.Worker, "_append", stalled)
    clock45 = [s45 + timedelta(seconds=30)]

    def pub45(path, data):
        if Path(path).name == f"{s45:%Y%m%dT%H%M%SZ}.report.json":
            clock45[0] = d45 - timedelta(microseconds=1)
        return real_pub(path, data)
    monkeypatch.setattr(c, "publish_exclusive", pub45)
    with _Clock(clock45[0]):
        ck.run_checkpoint(tmp_path, st_["ledger"].path, s45, lambda reference=None: S1_RECEIPT,
                          lambda: dict(S1_PROCESS), tmp_path / "crash.log", now=lambda: clock45[0])
    # A3 Task 7 (E1.2, E1.3, E1.7): slot 47's worker runs the journal finalizer after its J, at t >= D45: slot 45 is
    # INTENT-only, so its SLOT-TIMEOUT commits first (the selection never skips it: C2) and the close is determined
    # from slot 47; slot 45's later J (R < D45) is LOST-RACE at 4c - TIMEOUT stands, no INVALID
    assert nested["r47"]["seal"]["written"] is True
    assert [k_ for k_, *_ in slot_rows(tmp_path, s45)] == ["SLOT-INTENT", "SLOT-TIMEOUT"]
    seal = json.loads((tmp_path / "s1_out" / "seals" / f"{day['date']}.json").read_text(encoding="utf-8"))
    assert seal["capture"]["scheduled"] == s47.isoformat()
    assert all(x.kind != "TRIAL-INVALID" for x in rows(tmp_path))


def test_a_damaged_qualified_tree_on_another_pending_close_is_invalid(tmp_path):
    """Review I1 (F3 table, QUALIFIED): _finalize_others does not swallow a damaged QUALIFIED tree of another close:
    TRIAL-INVALID (registration-artifact), the abort, no seal of that close."""
    st_ = registered(tmp_path)
    cal = st_["calendar"]
    day, s45 = first_slot(st_)
    s47 = s45 + timedelta(minutes=2)
    s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(s45), at=s45 + timedelta(seconds=10))   # crashed before P
    run(tmp_path, st_, s47, s47 + timedelta(seconds=30))
    out = tmp_path / "s1_out"
    assert not (out / "seals" / f"{day['date']}.json").exists()                              # deferred behind 45
    rp = sl.names(out, s47, day["date"])["report"]
    rp.write_text(rp.read_text(encoding="utf-8") + " ", encoding="utf-8")                  # the TEST damages its tmp
    intent45 = j.first(j.subject_rows(rows(tmp_path), j.slot_subject(s45)), "SLOT-INTENT")   # the finalizer's TIMEOUT
    s1_jappend(tmp_path, "SLOT-TIMEOUT", j.slot_subject(s45), op=intent45.op, due=True,     # at D45 (Task 7's row):
               at=z.resolution_deadline(s45, day, cal))                                    # slot 47 is now selectable
    nday = next(d for d in cal if d["date"] == "2026-10-27")
    n45 = z.close_of(nday["date"], cal) + timedelta(minutes=45)
    with pytest.raises(SystemExit, match=r"QUALIFIED tree differs .*registration-artifact"):
        run(tmp_path, st_, n45, n45 + timedelta(seconds=30))
    inv = j.first(rows(tmp_path), "TRIAL-INVALID")
    assert inv is not None and inv.subject == "reason/registration-artifact"
    assert c.load_abort(out)["reason"] == c.REGISTRATION_ARTIFACT
    assert not (out / "seals" / f"{day['date']}.json").exists()
