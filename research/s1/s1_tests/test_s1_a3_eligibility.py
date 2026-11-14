"""Erratum 2 Clarification 2 (M3-PW; sha256 ba16fdc8...): a NEW ordinary post-START slot attempt for a session with
open_instant >= START and close_instant > the registered A5.1 deadline is refused at the F0.5 step-5 post-START slot
gate (the pinned reason, no row, no claim/capture/callback/QUALIFIED/seal). Map rows 500-508, 510, 511 and 513 (row 509
is in test_s1_a3_stop.py, row 512 in test_s1_a3_mutants.py). t11 fixture: START 2026-10-26T13:30Z, deadline
2027-04-26T13:30Z, L = d129 2027-04-23, W_L = 2027-04-26T12:00Z, d130 = 2027-04-26 (close 20:00Z), d131 = 2027-04-27.
Behavioural RED against the H5a stub (s1_evidence/a3/h5a_red.txt). Evidence labels per row are in the docstrings."""
import json
import sqlite3
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
from conftest import (S1_RECEIPT, _Clock, _weekdays, s1_ack, s1_first_invalid, s1_jappend, s1_jstage, s1_replaced,
                      s1_synthetic_stop)

START = h.START
CLARIFICATIONS = {"docs/s1_design_v5_addendum3_erratum2_clarification2.md":
                  "ba16fdc876030d824818bed4e56abd1c9e4ff1c825c738d34dbf18fc50c07e6c",
                  "docs/s1_design_v5_addendum3_erratum2_clarification3.md":
                  "fabac171ec8e6dc2769f9d3040b7acc4abdef607e5cda66de915f466b3ea7a6e",
                  "docs/s1_design_v5_addendum3_erratum2_clarification4.md":
                  "c974ed5f988e2922ec9a1ed19099b6b7260b53b27976f29191722bd6fc9c44d8"}


def test_bundle_pins_clarifications_2_3_4():
    """A3.1: each adopted, byte-frozen clarification joins the registered bundle's document pins (after Clarification
    1); the pinned hash is the frozen file's."""
    keys = list(c.DOC_PINS)
    for rel, sha in CLARIFICATIONS.items():
        assert c.DOC_PINS.get(rel) == sha, rel
        assert c.sha256_file(Path(c.__file__).resolve().parent / rel) == sha, rel
    assert keys.index("docs/s1_design_v5_addendum3_erratum2_clarification1.md") < \
        keys.index("docs/s1_design_v5_addendum3_erratum2_clarification2.md") < \
        keys.index("docs/s1_design_v5_addendum3_erratum2_clarification3.md") < \
        keys.index("docs/s1_design_v5_addendum3_erratum2_clarification4.md")


# ---------------------------------------------------------------- row 500 (PW-A1): changed, RED/GREEN
@pytest.mark.parametrize("case", ["d130-first-slot", "d131-post-deadline"])
def test_post_deadline_close_refused(tmp_path, monkeypatch, case):
    """An ACTIVE, otherwise authorized, guarded-domain session with close > deadline: SLOT-INTENT refused with the
    pinned reason (O-P3); no row, no claim, no capture, no receipt/process/provider callback, no QUALIFIED, no seal."""
    st_ = h.registered(tmp_path)
    date = {"d130-first-slot": h.D130, "d131-post-deadline": h.D131}[case]
    assert z.close_of(date, st_["calendar"]) > z.deadline(c.aware(START))
    sch = h.slot(st_, date)
    w = h.Watch(monkeypatch)
    h.refuse_no_row(tmp_path, st_, sch, sch + timedelta(seconds=30), h.c2_text(date), w)


# ---------------------------------------------------------------- row 501 (PW-A2)
@pytest.mark.parametrize("case", ["close-equals-deadline-not-refused", "close-plus-1us-refused"])
def test_close_deadline_boundary(case):
    """Aware close instants: equality is not refused; +1 us is refused. Evidence scope (O-P2): PREDICATE/GATE-LEVEL,
    NOT A REGISTERED END-TO-END TRIAL - a registered START must be the regular open of its session
    (s1_collect._validate_calendar), so its deadline (START + 6 months at START's New York wall time) never equals a
    session close; START is set here to a close wall time (2026-10-26 16:00 EDT) only at the slot gate. Production
    START validation is unchanged. Equality: control; +1 us: changed RED/GREEN."""
    cal = _weekdays("2026-09-16", "2027-06-04")
    close130 = z.close_of(h.D130, cal)
    start = c.aware("2026-10-26T20:00:00+00:00") - (h.US if case == "close-plus-1us-refused" else timedelta(0))
    assert z.deadline(start) == close130 - (h.US if case == "close-plus-1us-refused" else timedelta(0))
    assert z.open_instant(next(d for d in cal if d["date"] == h.D130)) >= start           # the guarded domain
    g = sl.post_start_gate(h.fake_trial(), start=start, cal=cal)
    why = g([], j.slot_subject(close130 + timedelta(minutes=45)))
    if case == "close-equals-deadline-not-refused":
        assert why is None, why
    else:
        assert why == h.c2_text(h.D130)


# ---------------------------------------------------------------- row 502 (PW-A3): control
START_SUNDAY_DEADLINE = "2026-11-02T14:30:00+00:00"       # deadline 2027-05-02T13:30Z: a Sunday (O-P4)


@pytest.mark.parametrize("case", ["slot-before-e-after-deadline-proceeds", "slot-at-or-after-e-refused"])
def test_eligible_close_window_past_deadline_stays_under_e_w(tmp_path, case):
    """A close at or before the deadline whose window runs past the deadline instant: an invocation after the deadline
    but before E proceeds; at now >= E the A5.2 refusal is unchanged. END-TO-END with a valid registration (O-P4):
    START 2026-11-02 09:30 EST (a regular open), deadline Sunday 2027-05-02 09:30 EDT; the last eligible close is
    Friday 2027-04-30 (20:00Z), whose window runs to Monday 08:00 EDT. Control."""
    st_ = h.registered(tmp_path, START_SUNDAY_DEADLINE)
    start, cal = c.aware(START_SUNDAY_DEADLINE), st_["calendar"]
    dl = z.deadline(start)
    fri = h.day(st_, "2027-04-30")
    assert dl == c.aware("2027-05-02T13:30:00+00:00") and z.eligible_sessions(start, cal)[-1] == fri
    sch = c.aware("2027-05-02T14:00:00+00:00")                       # Sunday 10:00 EDT: a slot of Friday's close
    assert sch in z.schedule(fri, cal) and sch > dl and z.close_of(fri["date"], cal) <= dl
    e = z.eligible_until(sch, fri, cal)
    if case == "slot-before-e-after-deadline-proceeds":
        got, res = h.attempt(h.run, tmp_path, st_, sch, sch + timedelta(seconds=30))
        assert got == "ok", res
        assert h.kinds(tmp_path, sch)[:1] == ["SLOT-INTENT"]
    else:
        before = h.shas(tmp_path)
        with pytest.raises(SystemExit, match=r"now >= E: the finalizer appends MISSED") as ex:
            h.run(tmp_path, st_, sch, e)
        assert not h.PINNED.search(str(ex.value))
        assert h.shas(tmp_path) == before


# ---------------------------------------------------------------- row 503 (PW-A4)
@pytest.mark.parametrize("case", ["exact-w-l-routes", "later-registered-slot-not-routed"])
def test_route_predicate_unchanged(tmp_path, monkeypatch, case):
    """Exact W_L takes the provider-free route at any clock (control); a registered slot after W_L is never routed:
    it is refused by the new predicate, with no route call (changed RED/GREEN)."""
    st_ = h.registered(tmp_path)
    w = h.Watch(monkeypatch)
    if case == "exact-w-l-routes":
        for at in (h.W_L - timedelta(hours=1), h.W_L + timedelta(hours=1)):
            got = h.run(tmp_path, st_, h.W_L, at, receipt=w.receipt(), process=w.process())
            assert got["route"] == "w-last"
        assert w.calls.count("_w_last_route") == 2 and "SLOT-INTENT" not in h.kinds(tmp_path, h.W_L)
        w.sp.assert_zero()
        return
    sch = h.slot(st_, h.D130)
    assert sch > h.W_L
    h.refuse_no_row(tmp_path, st_, sch, sch + timedelta(seconds=30), h.c2_text(h.D130), w)
    assert "_w_last_route" not in w.calls


# ---------------------------------------------------------------- row 504 (PW-A5): control, staged legacy history
@pytest.mark.parametrize("case", ["legacy-claim-r-after-w-l-before-d-qualifies", "legacy-claim-timeout-at-d",
                                  "legacy-w-l-claim-completes"])
def test_legacy_eligible_claim_keeps_rules(tmp_path, case):
    """An explicitly PRE-EXISTING (legacy) eligible claim - the W_L slot of the last eligible close d129, claimed at
    W_L - 10 s, written as STAGED synthetic history (s1_jstage; no current entry can open it: Clarification 4) -
    keeps its completion rules: a QUALIFIED with R after W_L and R < D appends through the product context (the
    post-START gate in force); otherwise TIMEOUT at D (never before); the exact W_L route completes it. No eligibility
    refusal of a completion."""
    st_ = h.registered(tmp_path)
    cal, sub = st_["calendar"], j.slot_subject(h.W_L)
    intent = s1_jstage(tmp_path, "SLOT-INTENT", sub, at=h.W_L - timedelta(seconds=10))
    if case == "legacy-claim-r-after-w-l-before-d-qualifies":
        tr = t.open_trial(h.mb(tmp_path))
        ctx = t.product_context(tr, cal, slot_gate=h.gate_of(st_, trial=tr))
        r_ = h.W_L + timedelta(minutes=1)
        assert h.W_L < r_ < h.D_L
        res = j.append(tr.trial_id, tr.genesis, j.Request("SLOT-QUALIFIED", sub, intent.op, intent.actor,
                                                          detail="a" * 64, r_at=r_),
                       ctx, mailbox=h.mb(tmp_path), clock=lambda: r_ + timedelta(seconds=1))
        assert (res.outcome, res.reason) == ("APPEND", "")
        assert h.kinds(tmp_path, h.W_L) == ["SLOT-INTENT", "SLOT-QUALIFIED"]
        return
    if case == "legacy-claim-timeout-at-d":
        for at in (h.D_L - h.US, h.D_L):
            with _Clock(at):
                ck.run_finalizer(tmp_path, now=lambda: at, mailbox=h.mb(tmp_path))
            want = ["SLOT-INTENT"] if at < h.D_L else ["SLOT-INTENT", "SLOT-TIMEOUT"]
            assert h.kinds(tmp_path, h.W_L) == want
    else:
        got = h.run(tmp_path, st_, h.W_L, h.D_L)
        assert got["route"] == "w-last"
        assert h.kinds(tmp_path, h.W_L) == ["SLOT-INTENT", "SLOT-TIMEOUT"]
        assert [x.kind for x in h.rows(tmp_path)].count("TRIAL-STOP") == 1
    assert h.invalids(tmp_path) == []


# ---------------------------------------------------------------- row 505 (PW-A6): control, synthetic/legacy history
@pytest.mark.parametrize("case", ["pending-ineligible-intent", "created-ineligible-seal", "no-new-invalid"])
def test_legacy_ineligible_history_kept(tmp_path, case):
    """Old ineligible rows: a pending d130 INTENT (staged legacy history) times out under its existing rules (TIMEOUT
    at D, from the --finalize catch-up); the CREATED ineligible d130 seal (row 305's history) stays required evidence;
    no deletion and no synthetic INVALID from legacy rows."""
    if case == "pending-ineligible-intent":
        st_ = h.registered(tmp_path)
        sch = h.slot(st_, h.D130)
        s1_jstage(tmp_path, "SLOT-INTENT", j.slot_subject(sch), at=sch + timedelta(seconds=1))
        d = z.resolution_deadline(sch, h.day(st_, h.D130), st_["calendar"])
        with _Clock(d):
            ck.run_finalizer(tmp_path, now=lambda: d, mailbox=h.mb(tmp_path))
        assert h.kinds(tmp_path, sch) == ["SLOT-INTENT", "SLOT-TIMEOUT"]
        assert h.invalids(tmp_path) == []
        return
    ah.stop_history(tmp_path, START, "deadline-instant-eligibility")      # row 305: a CREATED d130 seal stage
    out = tmp_path / "s1_out"
    sub130 = "slot/20270426T204500Z"
    assert [x.kind for x in j.subject_rows(h.rows(tmp_path), sub130)] == ["SLOT-INTENT", "SLOT-QUALIFIED"]
    if case == "no-new-invalid":
        s1_jstage(tmp_path, "SLOT-INTENT", "slot/20270426T204700Z", at=c.aware("2027-04-26T20:47:01+00:00"))
    before = h.shas(tmp_path)
    t.gate(tmp_path, "legacy ineligible history")
    assert h.shas(tmp_path) == before and h.invalids(tmp_path) == []
    assert "seals/2027-04-26.json" in sl.required_seals(out, h.rows(tmp_path))
    assert (out / "seals" / "2027-04-26.json").is_file()


# ---------------------------------------------------------------- row 506 (PW-A7): control
@pytest.mark.parametrize("case", ["opening-mode-captures-and-seals", "opening-mode-keeps-opening-gate-guard"])
def test_opening_mode_path_unchanged(tmp_path, monkeypatch, case):
    """run_opening_checkpoint path only: it captures and seals the opening close as before; its own opening_gate guard
    still refuses a later opening slot once the opening is decided (E5.6); the new predicate (the post-START gate) is
    never consulted in opening mode."""
    from test_s1_a3_prestart import opened, opening_slot
    built = []
    real = sl.post_start_gate
    monkeypatch.setattr(sl, "post_start_gate", lambda *a, **kw: built.append(a) or real(*a, **kw))
    start, cal, oc, lg, rep = opened(tmp_path)
    s45 = opening_slot(cal, oc, 45)
    assert rep["seal"]["written"] is True, rep
    kinds45 = [x.kind for x in j.subject_rows(h.rows(tmp_path), j.slot_subject(s45))]
    assert kinds45 == ["SLOT-INTENT", "SLOT-QUALIFIED"]
    assert (tmp_path / "s1_out" / "seals" / f"{oc}.json").is_file()
    if case == "opening-mode-keeps-opening-gate-guard":
        s47 = opening_slot(cal, oc, 47)
        at = s47 + timedelta(seconds=30)
        before = h.shas(tmp_path)
        with _Clock(at), pytest.raises(SystemExit, match=r"the opening is already decided: no further opening "
                                                         r"capture \(E5\.6\)") as ex:
            ck.run_opening_checkpoint(tmp_path, lg.path, s47, lambda reference=None: S1_RECEIPT,
                                      lambda: dict(h.S1_PROCESS), tmp_path / "c.log", now=lambda: at)
        assert not h.PINNED.search(str(ex.value)) and h.shas(tmp_path) == before
    assert built == []


# ---------------------------------------------------------------- row 507 (PW-A8): control
PRECEDENCE = {"local-abort": r"surviving local abort recorded: INVALID \(established-violation\)",
              "closed": r"zero open trials",
              "invalid": r"trial INVALID \(reason/stage-replaced\)",
              # a post-prereg foreign root (its plan names another trial): the legacy registration detector refuses it
              # first (persistent local ABORTED-INVALID in THAT root, no journal row) - the existing outcome
              "foreign-root": r"registration artifact\(s\) missing or changed: \['plan\.json changed since opening'"
                              r".*persistent ABORTED-INVALID",
              "integrity-violation": r"slot evidence violation .*INVALID \(registration-artifact\)",
              "stopped-lost-race": None,
              "repeat-attempt-invalid": r"SLOT-INTENT -> INVALID \(repeat-attempt\)",
              "mandatory-invalid-not-suppressed": r"INVALID \(bundle\)"}
NEW_INVALID = {"local-abort": ["reason/established-violation"], "integrity-violation": ["reason/registration-artifact"],
               "repeat-attempt-invalid": ["reason/repeat-attempt"], "mandatory-invalid-not-suppressed": ["reason/bundle"]}


def precondition(tmp_path, monkeypatch, st_, case, sch, at):
    """Set up one higher-precedence outcome for an invocation of slot `sch` at `at`; returns the root to invoke."""
    from test_s1_a3_abort_recovery import _foreign_root
    out = tmp_path / "s1_out"
    if case == "local-abort":
        c.write_abort(out, {"reason": "fixture: an observed violation", "observed_utc": at.isoformat()})
    elif case == "closed":
        s1_ack(tmp_path, "close", "S1-CLOSE-ACK", at - timedelta(hours=1), reason="WITHDRAWN",
               evidence_sha256="0" * 64)
    elif case == "invalid":
        s1_jappend(tmp_path, "TRIAL-INVALID", "reason/stage-replaced", at=at - timedelta(hours=1), detail="a" * 64)
    elif case == "foreign-root":
        return _foreign_root(tmp_path)
    elif case == "integrity-violation":
        stray = sl.names(out, h.slot(st_, h.D0, 53), h.D0)["claim"]
        stray.parent.mkdir(parents=True, exist_ok=True)
        stray.write_text(json.dumps({"op": "0" * 32, "actor": "0" * 32}), encoding="utf-8")
    elif case == "stopped-lost-race":
        s1_synthetic_stop(tmp_path, at - timedelta(hours=1))
    elif case == "repeat-attempt-invalid":
        s1_jstage(tmp_path, "SLOT-INTENT", j.slot_subject(sch), at=sch + timedelta(seconds=1))
        monkeypatch.setattr(sl.Worker, "_rows", lambda self: [])         # the restart pre-check raced (F3)
    elif case == "mandatory-invalid-not-suppressed":
        monkeypatch.setattr(c, "bundle_sha256", lambda: "f" * 64)
    return tmp_path


def assert_precedence(tmp_path, monkeypatch, st_, case, sch, at, run_root=None):
    """Each case keeps its existing outcome, including its required INVALID row; the pinned Clarification reasons
    never appear in place of the higher-precedence reason; no claim/capture/callback."""
    root = precondition(tmp_path, monkeypatch, st_, case, sch, at)
    before = set(h.shas(tmp_path)) if case != "closed" else None
    sp = h.Spies(monkeypatch)
    if PRECEDENCE[case] is None:                                      # STOPPED -> LOST-RACE (a record, not a refusal)
        got = h.run(root, st_, sch, at, receipt=sp.receipt(), process=sp.process())
        assert got["outcome"] == "LOST-RACE" and "STOPPED" in got["reason"]
        assert not h.PINNED.search(got["reason"])
    else:
        with pytest.raises(SystemExit, match=PRECEDENCE[case]) as ex:
            h.run(root, st_, sch, at, receipt=sp.receipt(), process=sp.process())
        assert not h.PINNED.search(str(ex.value)), str(ex.value)
    sp.assert_zero()
    if case == "closed":
        return
    new = [x for x in h.rows(tmp_path) if x.sha not in before]
    assert [x.subject for x in new] == NEW_INVALID.get(case, [])
    assert all(x.kind == "TRIAL-INVALID" for x in new)


@pytest.mark.parametrize("case", list(PRECEDENCE))
def test_precedence_preserved(tmp_path, monkeypatch, case):
    """For a post-deadline (d130) invocation: each higher-precedence outcome (gate local-abort, CLOSED, INVALID,
    foreign root, integrity; 4b repeat-attempt INVALID; step-5 STOPPED -> LOST-RACE; an independently established
    mandatory INVALID) keeps its existing outcome and row; eligibility never pre-empts or suppresses it."""
    st_ = h.registered(tmp_path)
    sch = h.slot(st_, h.D130)
    assert_precedence(tmp_path, monkeypatch, st_, case, sch, sch + timedelta(seconds=30))


# ---------------------------------------------------------------- row 508 (PW-A9): control, synthetic history
@pytest.mark.parametrize("case", ["row305-history", "damaged-ineligible-seal-invalid"])
def test_row305_kept_as_synthetic_history(tmp_path, case):
    """Row 305 (t11 'deadline-instant-eligibility') is SYNTHETIC history (its d130 QUALIFIED and seal stage are
    fixture rows): its CREATED d130 seal is required evidence and never sampled; deleting or corrupting it gives
    INVALID (stage-replaced), unchanged; the oracle is not weakened."""
    hist = ah.stop_history(tmp_path, START, "deadline-instant-eligibility")
    out = tmp_path / "s1_out"
    p = out / "seals" / "2027-04-26.json"
    if case == "row305-history":
        rows_ = h.rows(tmp_path)
        assert "seals/2027-04-26.json" in sl.required_seals(out, rows_)
        rec = z.stop_record(out, rows_, c.aware(START), hist["calendar"], t.open_trial(h.mb(tmp_path)).bundle)
        assert {k_: rec[k_] for k_ in hist["want"]} == hist["want"]
        assert "seals/2027-04-26.json" not in rec["seals"] and rec["stop_close"] != "2027-04-26T20:00:00+00:00"
        return
    p.unlink()
    with pytest.raises(SystemExit, match=s1_replaced("seals/2027-04-26.json")):
        t.gate(tmp_path, "integrity")
    assert s1_first_invalid(tmp_path) == "reason/stage-replaced"


# ---------------------------------------------------------------- row 510 (PW-A11): changed, RED/GREEN
@pytest.mark.parametrize("case", ["worker-post-start-gate-post-deadline-close"])
def test_direct_worker_entry_cannot_bypass(tmp_path, monkeypatch, case):
    """A Worker built directly with the post-START gate (no run_checkpoint) for a guarded-domain session with close >
    deadline: refused, no row."""
    st_ = h.registered(tmp_path)
    sch = h.slot(st_, h.D130)
    at = sch + timedelta(seconds=30)
    before = h.shas(tmp_path)
    with _Clock(at):
        gv = t.gate(tmp_path, "direct worker", defer_pending=True)
        with pytest.raises(SystemExit, match=h.refused(sch, h.c2_text(h.D130))):
            with sl.Worker(gv, sch, h.day(st_, h.D130), st_["calendar"],
                           slot_gate=sl.post_start_gate(gv.trial, start=c.aware(START), cal=st_["calendar"]),
                           mailbox=h.mb(tmp_path), now=lambda: at) as wk:
                wk.intent()
    assert h.shas(tmp_path) == before and h.no_files(tmp_path, st_, sch)


# ---------------------------------------------------------------- row 511 (PW-A12): changed, RED/GREEN
@pytest.mark.parametrize("case", ["no-missed-timeout-rows", "no-stop-decision"])
def test_eligibility_refusal_triggers_no_finalizer(tmp_path, monkeypatch, case):
    """After the eligibility refusal: zero finalizer/MISSED/TIMEOUT appends and no decide_stop call (today the d130
    path runs the post-capture finalizer)."""
    st_ = h.registered(tmp_path)
    sch = h.slot(st_, h.D130)
    w = h.Watch(monkeypatch)
    h.attempt(h.run, tmp_path, st_, sch, sch + timedelta(seconds=30))
    if case == "no-missed-timeout-rows":
        assert [k for k, _ in w.appends if k in ("SLOT-MISSED", "SLOT-TIMEOUT")] == [], w.appends
    else:
        assert [x for x in w.calls if x in ("decide_stop", "finalize_close", "_after_terminal", "_finalize_others",
                                             "_finalize_last_if_due")] == [], w.calls
        assert j.first(h.rows(tmp_path), "TRIAL-STOP") is None


# ---------------------------------------------------------------- row 513 (PW-A14)
@pytest.mark.parametrize("case", ["scheduled-opening-close-slot-no-new-refusal",
                                  "scheduled-opening-close-slot-keeps-ordinary-guards",
                                  "paired-post-deadline-control-refused"])
def test_scheduled_mode_pre_start_session_unchanged(tmp_path, case):
    """A scheduled-mode (run_checkpoint) slot of the opening close, after the PREREG-ACK and before its E: no new
    refusal; it keeps its ordinary guards (no PREREG-ACK refuses; now >= E refuses) and the bridge conditional gives
    None (close < START). Paired, same harness: a row-500 post-deadline session is refused with the pinned reason.
    Evidence scope: DECISION-LEVEL (the product's post-START slot gate and registered slot timing through
    s1_journal.decide, synthetic rows) - a SETUP INCOMPATIBILITY, labelled: F7.2(b) and the START attestation make
    every opening-close slot terminal before the OPENING-ACK, so no registered trial reaches an unclaimed opening-close
    slot after its PREREG-ACK. Pre-START params: control; paired: changed RED/GREEN."""
    st_ = h.registered(tmp_path)
    cal, oc = st_["calendar"], st_["opening_close"]
    start = c.aware(START)
    s47 = z.close_of(oc, cal) + timedelta(minutes=47)
    oday = h.day(st_, oc)
    assert z.open_instant(oday) < start and z.close_of(oc, cal) < start            # bridge conditional: None
    e47 = z.eligible_until(s47, oday, cal)

    def decide(sub, now, prereg=True):
        req = j.Request("SLOT-INTENT", sub, j.new_nonce(), j.new_nonce())
        return j.decide([], req, h.product_ctx(cal, h.gate_of(st_, prereg=prereg)), now)
    if case == "scheduled-opening-close-slot-no-new-refusal":
        assert decide(j.slot_subject(s47), s47 + timedelta(seconds=30)) == j.Decision("APPEND")
    elif case == "scheduled-opening-close-slot-keeps-ordinary-guards":
        no_ack = decide(j.slot_subject(s47), s47 + timedelta(seconds=30), prereg=False)
        assert (no_ack.outcome, no_ack.reason) == ("REFUSE", "no S1-PREREG-ACK: no post-START capture (F7.4)")
        late = decide(j.slot_subject(s47), e47)
        assert (late.outcome, late.reason) == ("REFUSE", "now >= E: the finalizer appends MISSED")
    else:
        s130 = h.slot(st_, h.D130)
        got = decide(j.slot_subject(s130), s130 + timedelta(seconds=30))
        assert (got.outcome, got.reason) == ("REFUSE", h.c2_text(h.D130))
