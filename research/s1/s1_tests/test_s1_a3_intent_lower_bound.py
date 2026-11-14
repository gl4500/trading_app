"""Erratum 2 Clarification 4 (EARLY-INTENT lower bound; sha256 c974ed5f...): at F0.5 step 6, SLOT-INTENT permission is
decided on the same in-transaction clock sample as every other step-6 decision, and APPEND requires
s <= sample < E(s); a sample before scheduled(s) is refused with no row (declared tolerance 0), for ALL callers
(opening mode and pre-START sessions included); the exact W_L route is unaffected. An early refusal's diagnostic
(slot, sample, reason) goes to the reviewed path s1_out/early_refusals.jsonl - never a journal row, never creating a
missing root - and a failed write still refuses and discloses the gap. Map rows 540-548 (row 549 is in
test_s1_a3_mutants.py). Behavioural RED against the H5a stub (s1_evidence/a3/h5a_red.txt). Evidence labels per row are in
the docstrings."""
import dataclasses
import inspect
import json
import re
from datetime import timedelta
from pathlib import Path

import pytest
import a3_h5a_helpers as h
import a3_helpers as ah
import s1_checkpoint as ck
import s1_common as c
import s1_journal as j
import s1_seal as z
import s1_slot as sl
import s1_trial as t
from conftest import (S1_RECEIPT, Ledger, _Clock, _weekdays, s1_ack, s1_jappend, s1_jstage, s1_mailbox_init,
                      s1_plan_audit, s1_synthetic_stop)

START = h.START
SEC = timedelta(seconds=1)
DIAG = "early_refusals.jsonl"


def diag_lines(root) -> list:
    p = Path(root) / "s1_out" / DIAG
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.is_file() else []


# ---------------------------------------------------------------- row 540 (C4-A1)
@pytest.mark.parametrize("case", ["sample-s-minus-1us-refused-no-row", "sample-equals-s-appends",
                                  "sample-s-plus-epsilon-appends", "zero-tolerance-declared"])
def test_permission_boundary(tmp_path, monkeypatch, case):
    """The transaction sample at s - 1 us: REFUSE, no row (changed RED/GREEN); at s and s + 1 us: APPEND (controls);
    the declared tolerance is 0 (control: the module constant, and the boundary at decision level)."""
    if case == "zero-tolerance-declared":
        assert j.C4_TOLERANCE == timedelta(0)
        cal = _weekdays("2026-09-16", "2027-06-04")
        s45 = z.close_of(h.D0, cal) + timedelta(minutes=45)
        ctx = h.product_ctx(cal, sl.post_start_gate(h.fake_trial(), start=c.aware(START), cal=cal))
        req = j.Request("SLOT-INTENT", j.slot_subject(s45), j.new_nonce(), j.new_nonce())
        assert j.decide([], req, ctx, s45 - h.US) == j.Decision("REFUSE", h.c4_text(s45))
        assert j.decide([], req, ctx, s45) == j.Decision("APPEND")
        return
    st_ = h.registered(tmp_path)
    s45 = h.slot(st_, h.D0)
    at = {"sample-s-minus-1us-refused-no-row": s45 - h.US, "sample-equals-s-appends": s45,
          "sample-s-plus-epsilon-appends": s45 + h.US}[case]
    if at < s45:
        h.refuse_no_row(tmp_path, st_, s45, at, h.c4_text(s45), h.Watch(monkeypatch))
        return
    h.run(tmp_path, st_, s45, at)
    intent = j.first(j.subject_rows(h.rows(tmp_path), j.slot_subject(s45)), "SLOT-INTENT")
    assert intent is not None and intent.at == j.fmt_at(at)


# ---------------------------------------------------------------- row 541 (C4-A2)
@pytest.mark.parametrize("case", ["non-last-close-w-slot-never-claimable-ends-missed",
                                  "exact-w-l-route-unaffected-any-clock"])
def test_w_claim_interval_empty(tmp_path, monkeypatch, case):
    """A W slot of a non-last close (d0's 2026-10-27T12:00Z: E = W = s) is never claimable - a sample before s is the
    C4 refusal, at s it is now >= E - and it ends MISSED at E (changed RED/GREEN). The exact W_L route stays
    provider-free and opens no attempt at any clock (control)."""
    st_ = h.registered(tmp_path)
    if case == "exact-w-l-route-unaffected-any-clock":
        w = h.Watch(monkeypatch)
        for at in (h.W_L - timedelta(hours=1), h.W_L, h.W_L + timedelta(hours=1)):
            assert h.run(tmp_path, st_, h.W_L, at, receipt=w.receipt(), process=w.process())["route"] == "w-last"
        assert "SLOT-INTENT" not in h.kinds(tmp_path, h.W_L)
        w.sp.assert_zero()
        return
    d0 = h.day(st_, h.D0)
    w0 = z.schedule(d0, st_["calendar"])[-1]
    assert w0 == c.aware("2026-10-27T12:00:00+00:00") and z.eligible_until(w0, d0, st_["calendar"]) == w0
    s47 = h.slot(st_, h.D0, 47)
    s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(s47), at=s47 + SEC)    # d0 has rows (a crashed worker)
    h.refuse_no_row(tmp_path, st_, w0, w0 - h.US, h.c4_text(w0))
    before = h.shas(tmp_path)
    with pytest.raises(SystemExit, match=r"now >= E: the finalizer appends MISSED"):
        h.run(tmp_path, st_, w0, w0)
    assert h.shas(tmp_path) == before
    with _Clock(w0 + SEC):
        ck.run_finalizer(tmp_path, now=lambda: w0 + SEC, mailbox=h.mb(tmp_path))
    assert h.kinds(tmp_path, w0) == ["SLOT-MISSED"]


# ---------------------------------------------------------------- row 542 (C4-A3): old -> new policy evidence
@pytest.mark.parametrize("case", ["old-head-early-intent-pause-resume-qualifies",
                                  "new-head-early-refused-no-retry-slot-missed"])
def test_early_paused_worker_loses_capture(tmp_path, case):
    """Old head: an early INTENT (STAGED LEGACY history, pre-C4: the OQ-33 path committed it), a pause, and a resume
    inside the window: QUALIFIED through the real arbitration, and it is the close's selection. New head: the same
    early invocation is refused with no row, no retry follows, the slot ends MISSED at its E, and the selection
    changes (slot 47 instead of 45)."""
    st_ = h.registered(tmp_path)
    cal, d0 = st_["calendar"], h.day(st_, h.D0)
    s45, s47 = h.slot(st_, h.D0), h.slot(st_, h.D0, 47)
    if case == "old-head-early-intent-pause-resume-qualifies":
        intent = s1_jstage(tmp_path, "SLOT-INTENT", j.slot_subject(s45), at=s45 - 5 * SEC)
        tr = t.open_trial(h.mb(tmp_path))
        h._qualify_synthetic(tmp_path, st_, tr, t.product_context(tr, cal, slot_gate=h.gate_of(st_, trial=tr)),
                             s45, intent, s45 + timedelta(seconds=30))
        q = sl.first_qualified(h.rows(tmp_path), d0, cal)
        assert q is not None and q.subject == j.slot_subject(s45)
        return
    h.refuse_no_row(tmp_path, st_, s45, s45 - 5 * SEC, h.c4_text(s45))
    h.qualify(tmp_path, st_, s47)
    e45 = z.eligible_until(s45, d0, cal)
    with _Clock(e45 + SEC):
        ck.run_finalizer(tmp_path, now=lambda: e45 + SEC, mailbox=h.mb(tmp_path))
    assert h.kinds(tmp_path, s45) == ["SLOT-MISSED"]
    seal = json.loads((tmp_path / "s1_out" / "seals" / f"{h.D0}.json").read_text(encoding="utf-8"))
    assert seal["capture"]["scheduled"] == s47.isoformat()


# ---------------------------------------------------------------- row 543 (C4-A4): old -> new policy evidence
@pytest.mark.parametrize("case", ["old-head-early-failed-retry-refused", "new-head-early-refused-retry-at-s-qualifies"])
def test_failed_early_then_retry_gains_capture(tmp_path, case):
    """Old head: an early invocation became INTENT + FAILED (STAGED LEGACY history, a3_helpers._early_failed) and a
    retry is refused by the restart pre-check. New head: the early invocation leaves no row, and a retry at or after s
    QUALIFIES (the selection can change)."""
    st_ = h.registered(tmp_path)
    s45 = h.slot(st_, h.D0)
    if case == "old-head-early-failed-retry-refused":
        ah._early_failed(tmp_path, j.slot_subject(s45), h.D0, (s45 - 5 * SEC).isoformat(),
                         (s45 - 4 * SEC).isoformat())
        before = h.shas(tmp_path)
        with pytest.raises(SystemExit, match=r"a restart never re-intents"):
            h.run(tmp_path, st_, s45, s45 + timedelta(seconds=30))
        assert h.shas(tmp_path) == before and h.kinds(tmp_path, s45) == ["SLOT-INTENT", "SLOT-FAILED"]
        return
    h.refuse_no_row(tmp_path, st_, s45, s45 - 5 * SEC, h.c4_text(s45))
    h.qualify(tmp_path, st_, s45)


# ---------------------------------------------------------------- row 544 (C4-A5): changed, RED/GREEN
@pytest.mark.parametrize("case", ["records-slot-sample-reason", "no-journal-row", "no-claim-no-capture",
                                  "missing-root-not-recreated",
                                  "diagnostic-write-failure-still-refuses-and-discloses-gap"])
def test_early_refusal_diagnostics(tmp_path, monkeypatch, case):
    """The reviewed diagnostic path (s1_out/early_refusals.jsonl, appended without creating any directory) records the
    slot, the observed in-transaction sample and the reason; no journal row; no claim or capture; a missing root is
    never created; on a write failure the command still refuses, does no work and states the gap."""
    st_ = h.registered(tmp_path)
    s45 = h.slot(st_, h.D0)
    at = s45 - SEC
    out = tmp_path / "s1_out"
    before = h.shas(tmp_path)
    w = h.Watch(monkeypatch)
    if case == "missing-root-not-recreated":
        real = j.append

        def lose_root(*a, **kw):
            res = real(*a, **kw)
            if res.outcome == "REFUSE" and "(Clarification 4)" in res.reason:
                out.rename(tmp_path / "s1_out.gone")            # the root vanishes after the refusal decision
            return res
        monkeypatch.setattr(j, "append", lose_root)
    if case == "diagnostic-write-failure-still-refuses-and-discloses-gap":
        def denied(*a, **kw):
            raise PermissionError(13, "diagnostic write denied (simulated)")
        monkeypatch.setattr(sl, "open", denied, raising=False)
    with pytest.raises(SystemExit, match=h.refused(s45, h.c4_text(s45))) as ex:
        h.run(tmp_path, st_, s45, at, receipt=w.receipt(), process=w.process())
    msg = str(ex.value)
    if case == "records-slot-sample-reason":
        assert diag_lines(tmp_path) == [{"subject": j.slot_subject(s45), "scheduled": s45.isoformat(),
                                         "sample": at.isoformat(), "reason": h.c4_text(s45)}]
        assert f"early-refusal diagnostic recorded in s1_out/{DIAG}" in msg
    elif case == "no-journal-row":
        assert h.shas(tmp_path) == before and w.written() == []
    elif case == "no-claim-no-capture":
        w.assert_no_work()
        assert h.no_files(tmp_path, st_, s45)
    elif case == "missing-root-not-recreated":
        assert not out.exists() and (tmp_path / "s1_out.gone").is_dir()
        assert not (tmp_path / "s1_out.gone" / DIAG).exists()
        assert re.search(r"early-refusal diagnostic NOT recorded \(.+\): recording gap", msg), msg
    else:
        assert re.search(r"early-refusal diagnostic NOT recorded \(PermissionError\): recording gap", msg), msg
        assert diag_lines(tmp_path) == [] and h.shas(tmp_path) == before
        w.assert_no_work()


# ---------------------------------------------------------------- row 545 (C4-A6)
SCOPE = ["opening-mode-early-refused", "opening-mode-equality-appends", "scheduled-pre-start-session-early-refused",
         "scheduled-pre-start-session-equality-appends", "closed-first", "invalid-first", "identity-first",
         "integrity-first", "repeat-attempt-first", "stopped-lost-race-first", "slot-gate-reasons-first"]


@pytest.mark.parametrize("case", SCOPE)
def test_scope_and_precedence(tmp_path, case):
    """Opening and pre-START callers are governed by C4 (early refused - changed RED/GREEN; equality appends -
    control); every earlier step wins over the C4 timing reason (controls): CLOSED (step 2), INVALID (step 3), identity
    and integrity (the trial gate, F0.6), 4b repeat-attempt, STOPPED -> LOST-RACE and the step-5 slot-gate reasons
    (PREREG, Clarification 2, Clarification 3). Opening mode and identity/integrity: end-to-end. The scheduled
    pre-START session and the journal steps 2-5: DECISION-LEVEL (s1_journal.decide with the product slot gate and slot
    timing; for the pre-START session the row-513 setup incompatibility applies)."""
    if case.startswith("opening-mode"):
        start, cal, oc, _ = s1_plan_audit(tmp_path, START)
        lg = Ledger(tmp_path / "opening_ledger.sqlite3")
        s45 = z.close_of(oc, cal) + timedelta(minutes=45)
        at = s45 - h.US if case == "opening-mode-early-refused" else s45

        def opening():
            with _Clock(at):
                return ck.run_opening_checkpoint(tmp_path, lg.path, s45, lambda reference=None: S1_RECEIPT,
                                                 lambda: dict(h.S1_PROCESS), tmp_path / "c.log", now=lambda: at)
        if case == "opening-mode-early-refused":
            before = h.shas(tmp_path)
            with pytest.raises(SystemExit, match=h.refused(s45, h.c4_text(s45))):
                opening()
            assert h.shas(tmp_path) == before
        else:
            opening()
            intent = j.first(j.subject_rows(h.rows(tmp_path), j.slot_subject(s45)), "SLOT-INTENT")
            assert intent is not None and intent.at == j.fmt_at(s45)
        return
    if case in ("identity-first", "integrity-first"):
        st_ = h.registered(tmp_path)
        if case == "identity-first":
            sch = h.slot(st_, h.D0, 46)                                   # not a registered seal slot
            with pytest.raises(SystemExit, match=r"is not a registered seal slot") as ex:
                h.run(tmp_path, st_, sch, sch - SEC)
            assert not h.PINNED.search(str(ex.value))
            return
        s45 = h.slot(st_, h.D0)
        stray = sl.names(tmp_path / "s1_out", h.slot(st_, h.D0, 53), h.D0)["claim"]
        stray.parent.mkdir(parents=True, exist_ok=True)
        stray.write_text(json.dumps({"op": "0" * 32, "actor": "0" * 32}), encoding="utf-8")
        with pytest.raises(SystemExit, match=r"slot evidence violation .*INVALID \(registration-artifact\)") as ex:
            h.run(tmp_path, st_, s45, s45 - SEC)
        assert not h.PINNED.search(str(ex.value)) and h.invalids(tmp_path) == ["reason/registration-artifact"]
        return
    cal = _weekdays("2026-09-16", "2027-06-04")
    start = c.aware(START)
    oc = "2026-10-23"
    s45, s47, s49 = (z.close_of(h.D0, cal) + timedelta(minutes=m) for m in (45, 47, 49))
    gate = sl.post_start_gate(h.fake_trial(), start=start, cal=cal)
    ctx = h.product_ctx(cal, gate)

    def decide(sub, now, rows_=(), ctx_=ctx):
        return j.decide(list(rows_), j.Request("SLOT-INTENT", sub, j.new_nonce(), j.new_nonce()), ctx_, now)
    if case.startswith("scheduled-pre-start-session"):
        o47 = z.close_of(oc, cal) + timedelta(minutes=47)
        assert z.open_instant(next(d for d in cal if d["date"] == oc)) < start
        if case.endswith("early-refused"):
            assert decide(j.slot_subject(o47), o47 - h.US) == j.Decision("REFUSE", h.c4_text(o47))
        else:
            assert decide(j.slot_subject(o47), o47) == j.Decision("APPEND")
        return
    early = s45 - h.US
    sub = j.slot_subject(s45)
    if case == "closed-first":
        got = decide(sub, early, ctx_=dataclasses.replace(ctx, closed=True))
        assert got == j.Decision("REFUSE", "trial CLOSED: no row of any kind")
    elif case == "invalid-first":
        got = decide(sub, early, h.synthetic_rows([("TRIAL-INVALID", "reason/bundle", s45 - timedelta(hours=1))]))
        assert got == j.Decision("LOST-RACE", "trial INVALID: no work")
    elif case == "repeat-attempt-first":
        got = decide(sub, early, h.synthetic_rows([("SLOT-INTENT", sub, s45 - timedelta(hours=1))]))
        assert got == j.Decision("INVALIDATE", "repeat-attempt")
    elif case == "stopped-lost-race-first":
        got = decide(sub, early, h.synthetic_rows([("TRIAL-STOP", "trial", s45 - timedelta(hours=1))]))
        assert got == j.Decision("LOST-RACE", "STOPPED: no capture after the stop (not invalid)")
    else:                                                                   # slot-gate-reasons-first
        no_ack = h.product_ctx(cal, sl.post_start_gate(h.fake_trial(prereg=False), start=start, cal=cal))
        assert decide(sub, early, ctx_=no_ack) == j.Decision("REFUSE", "no S1-PREREG-ACK: no post-START capture "
                                                                         "(F7.4)")
        s130 = z.close_of(h.D130, cal) + timedelta(minutes=45)
        assert decide(j.slot_subject(s130), s130 - h.US) == j.Decision("REFUSE", h.c2_text(h.D130))
        q47 = h.synthetic_rows([("SLOT-INTENT", j.slot_subject(s47), s47 + SEC),
                                ("SLOT-QUALIFIED", j.slot_subject(s47), s47 + 30 * SEC)])
        assert decide(j.slot_subject(s49), s49 - h.US, q47) == j.Decision("REFUSE", h.c3_text(h.D0, s47))


# ---------------------------------------------------------------- row 546 (C4-A7): characterization
@pytest.mark.parametrize("case", ["sample-before-e-commit-after-e-appends"])
def test_sample_before_e_commit_after_e(tmp_path, monkeypatch, case):
    """A permission sample before E with the actual commit after E (a barrier between the sample and the commit
    advances the clock past E) APPENDs: the decision is the sample's; no commit-time guarantee is advertised."""
    (tmp_path / "synthetic").mkdir()
    mb = s1_mailbox_init(tmp_path / "synthetic")
    s = c.aware("2026-11-02T21:45:00+00:00")
    e, d = s + timedelta(minutes=10), s + timedelta(minutes=40)
    clk = {"t": e - h.US, "commit": None}

    def clock():
        return clk["t"]
    real_insert = j._insert

    def barrier(con, *a, **kw):
        clk["t"] = e + SEC                                     # time passes between the sample and the commit
        clk["commit"] = clock()
        return real_insert(con, *a, **kw)
    monkeypatch.setattr(j, "_insert", barrier)
    ctx = j.Context(slot_times=lambda sub: (e, d), slot_gate=lambda rows, sub: None)
    res = j.append(h.TRIAL, h.GEN, j.Request("SLOT-INTENT", j.slot_subject(s), j.new_nonce(), j.new_nonce()),
                   lambda rows, con: ctx, mailbox=mb, clock=clock)
    assert (res.outcome, res.row.at) == ("APPEND", j.fmt_at(e - h.US))
    assert clk["commit"] > e


# ---------------------------------------------------------------- row 547 (C4-A8): witness / characterization
def minute4_calendar():
    """The t11 weekday calendar with d0 (2026-10-26) closing at 16:04 New York (a close at minute 4), synthetic."""
    cal = _weekdays("2026-09-16", "2027-06-04")
    return [dict(x, close="16:04") if x["date"] == h.D0 else x for x in cal]


@pytest.mark.parametrize("case", ["probe1-early-claims-refused", "probe2-still-q5", "seven-slot-witness-close-minute-4",
                                  "eighth-slot-excluded-half-open", "delayed-j-after-committed-timeout-lost-race"])
def test_conditional_bound_witnesses(tmp_path, monkeypatch, case):
    """With S1 and C4 in force and B STAGED in the fixture (every terminal committed within delta; a staged B is not
    evidence of B): probe 1's early claims are refused (changed RED/GREEN); probe 2 still gives Q = 5; a minute-4 close
    reaches 7 and an 8th cannot fall inside a 71-min half-open interval (the unchanged z.schedule over all 60 close
    minutes: minimum 8-slot span 71 min at minute 4, 75 on the hour); a J after a committed TIMEOUT is LOST-RACE.
    probe 1/2: end-to-end on the t11 trial. The minute-4 witness and the LOST-RACE: DECISION-LEVEL through the real
    s1_journal.append on a synthetic mailbox, with the product slot gate and slot timing on a synthetic calendar."""
    if case in ("probe1-early-claims-refused", "probe2-still-q5"):
        st_ = h.registered(tmp_path)
        if case == "probe2-still-q5":
            assert h.probe2_q(tmp_path, st_) == 5
            return
        cal, d0 = st_["calendar"], h.day(st_, h.D0)
        cl = z.close_of(h.D0, cal)
        at = cl + timedelta(minutes=40)
        before = h.shas(tmp_path)
        for m in (45, 47, 49, 51, 53, 55, 60, 120):
            sch = cl + timedelta(minutes=m)
            with _Clock(at):
                gv = t.gate(tmp_path, f"probe1 early claim {m}", defer_pending=True)
                with pytest.raises(SystemExit, match=h.refused(sch, h.c4_text(sch))):
                    with sl.Worker(gv, sch, d0, cal, slot_gate=h.gate_of(st_, trial=gv.trial),
                                   mailbox=h.mb(tmp_path), now=lambda: at) as wk:
                        wk.intent()
        assert h.shas(tmp_path) == before and h.qualified_count(tmp_path, d0, cal) == 0
        return
    if case == "eighth-slot-excluded-half-open":
        spans = {}
        for minute in range(60):
            cal_m = [dict(x, close=f"16:{minute:02d}") if x["date"] == h.D0 else x
                     for x in _weekdays("2026-09-16", "2027-06-04")]
            sch = z.schedule(next(x for x in cal_m if x["date"] == h.D0), cal_m)
            spans[minute] = min(sch[i + 7] - sch[i] for i in range(len(sch) - 7))
        assert min(spans.values()) == timedelta(minutes=71) and spans[4] == timedelta(minutes=71)
        assert spans[0] == timedelta(minutes=75)
        cal4 = minute4_calendar()
        s4 = z.schedule(next(x for x in cal4 if x["date"] == h.D0), cal4)
        cl4 = z.close_of(h.D0, cal4)
        assert [int((x - cl4).total_seconds() // 60) for x in s4[:8]] == [45, 47, 49, 51, 53, 55, 56, 116]
        lo = s4[0]
        assert sum(1 for x in s4 if lo <= x < lo + timedelta(minutes=71)) == 7       # half-open: the 8th excluded
        assert sum(1 for x in s4 if lo <= x <= lo + timedelta(minutes=71)) == 8      # closed: strict endpoints matter
    cal4 = minute4_calendar()
    d0 = next(x for x in cal4 if x["date"] == h.D0)
    sched = z.schedule(d0, cal4)
    (tmp_path / "synthetic").mkdir()
    mb = s1_mailbox_init(tmp_path / "synthetic")
    ctx = h.product_ctx(cal4, sl.post_start_gate(h.fake_trial(), start=c.aware(START), cal=cal4))

    def append(kind, s, at, op, actor, **kw):
        return j.append(h.TRIAL, h.GEN, j.Request(kind, j.slot_subject(s), op, actor, **kw), lambda rows, con: ctx,
                        mailbox=mb, clock=lambda: at)
    if case == "delayed-j-after-committed-timeout-lost-race":
        s = sched[0]
        op, actor = j.new_nonce(), j.new_nonce()
        assert append("SLOT-INTENT", s, s, op, actor).outcome == "APPEND"
        dd = z.resolution_deadline(s, d0, cal4)
        assert append("SLOT-TIMEOUT", s, dd, op, j.new_nonce()).outcome == "APPEND"        # staged B: TIMEOUT at D
        late = append("SLOT-QUALIFIED", s, dd + SEC, op, actor, detail="c" * 64, r_at=dd - SEC)
        assert (late.outcome, late.row) == ("LOST-RACE", None)
        return
    claims = []
    for s in sched[:7]:                                       # each claims at its own s (C4: s <= sample < E)
        op, actor = j.new_nonce(), j.new_nonce()
        assert append("SLOT-INTENT", s, s, op, actor).outcome == "APPEND"
        claims.append((s, op, actor))
    t_j = sched[6] + timedelta(minutes=1)                       # every J within its window, committed by D + delta
    for s, op, actor in claims:
        assert t_j < z.resolution_deadline(s, d0, cal4)
        assert append("SLOT-QUALIFIED", s, t_j, op, actor, detail="d" * 64, r_at=t_j).outcome == "APPEND"
    rows_ = j.read_trial(h.TRIAL, h.GEN, mb)
    assert sum(1 for x in rows_ if x.kind == "SLOT-QUALIFIED") == 7
    eighth = sched[7]
    got = append("SLOT-INTENT", eighth, eighth, j.new_nonce(), j.new_nonce())
    assert (got.outcome, got.reason) == ("REFUSE", h.c3_text(h.D0, sched[0]))


# ---------------------------------------------------------------- row 548 (C4-A9): control (review-backed)
@pytest.mark.parametrize("case", ["row524-labelled-historical-or-staged", "no-disable-c4-bypass"])
def test_row524_interaction(tmp_path, case):
    """Clarification 3 row 524's Q = 8 runs only as a historical / staged S1-only fixture (its INTENTs are s1_jstage
    rows; the production entry refuses its first early claim); no runtime switch disables C4 (j.Context and j.append
    carry no such parameter, s1_journal reads no environment, and the most permissive context still refuses)."""
    if case == "row524-labelled-historical-or-staged":
        import test_s1_a3_seal_once as so
        doc = so.test_counterexamples_integrated.__doc__
        assert "HISTORICAL (pre-C4) STAGED S1-ONLY" in doc
        src = inspect.getsource(h.probe1_staged_q)
        assert "s1_jstage(" in src and "Worker(" not in src
        st_ = h.registered(tmp_path)
        cal, d0 = st_["calendar"], h.day(st_, h.D0)
        cl = z.close_of(h.D0, cal)
        sch, at = cl + timedelta(minutes=45), cl + timedelta(minutes=40)
        with _Clock(at):
            gv = t.gate(tmp_path, "probe1 production entry", defer_pending=True)
            with pytest.raises(SystemExit, match=h.refused(sch, h.c4_text(sch))):
                with sl.Worker(gv, sch, d0, cal, slot_gate=h.gate_of(st_, trial=gv.trial), mailbox=h.mb(tmp_path),
                               now=lambda: at) as wk:
                    wk.intent()
        return
    assert {f.name for f in dataclasses.fields(j.Context)} == {
        "closed", "slot_times", "stop_detail", "stage_gate", "slot_gate", "stage_check", "stop_fence", "stop_ready",
        "recovery"}
    assert list(inspect.signature(j.append).parameters) == ["trial_id", "gen", "req", "ctx_fn", "mailbox", "clock",
                                                             "timeout"]
    assert list(inspect.signature(j.decide).parameters) == ["rows", "req", "ctx", "now"]
    src = Path(j.__file__).read_text(encoding="utf-8")
    assert "environ" not in src and "getenv" not in src
    assert j.C4_TOLERANCE == timedelta(0)
    s = c.aware("2026-11-02T21:45:00+00:00")
    permissive = j.Context(slot_times=lambda sub: (s + timedelta(days=3650),) * 2, slot_gate=lambda rows, sub: None)
    got = j.decide([], j.Request("SLOT-INTENT", j.slot_subject(s), j.new_nonce(), j.new_nonce()), permissive,
                   s - h.US)
    assert got == j.Decision("REFUSE", h.c4_text(s))
