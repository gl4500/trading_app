"""Task 12 fix round 9 (re-review 7: H-3; controller decision on H-3 and correction of the fix-8 brief rule 3).
Written BEFORE the fix; behavioural RED in s1_evidence/t12_fix9_<id>_red.txt. The reviewer probe
scratchpad/probe/test_probe13.py is a permanent test here. Time is an injected aware clock. Synthetic only: tmp_path
ledgers and mailbox (read-only); no live DB, network, real mailbox or scheduler."""
import json
import sqlite3
from datetime import datetime, time, timedelta, timezone

import pytest

import s1_checkpoint as ck
import s1_common as c
import s1_run as r
import s1_seal as z
from conftest import S1_PROCESS, S1_RECEIPT, Ledger, _Clock, s1_opening_checkpoint, s1_plan_audit, s1_state
from test_s1_t12_fix2_b3 import MON, Spies, _aborted, _refusals
from test_s1_t12_fix4 import START, START_DT, _fabricate


def _drop_audit_ack(tmp_path):
    con = sqlite3.connect(tmp_path / "mailbox.sqlite3")
    con.execute("DELETE FROM messages WHERE id=?", ("audit-ack",))
    con.commit()
    con.close()


# ====================================================================== H-3 (probe13)
@pytest.mark.parametrize("fake", ["2026-10-24", "2026-10-25"])
def test_h3_probe_a_session_inserted_into_the_calendar_after_the_opening_seal_aborts(tmp_path, fake):
    """H-3 reviewer probe test_calendar_insert_after_opening (B3.3): after the opening seal (before any RUN-ACK) a
    fake session is inserted into audit/calendar.json between the real opening close and START. The opening close
    comes from plan.json verified against the AUDIT-ACK's plan_sha256 and the anchor never reads calendar.json, so the
    next opening slot records the persistent "registration artifact" abort (the calendar is bound by the audit
    manifest); restoring calendar.json does not resume: the START attestation is refused and the abort stays."""
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    lg = Ledger(tmp_path / "l.sqlite3")
    assert s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT)["seal"]["written"]
    out = tmp_path / "s1_out"
    cp = out / "audit" / "calendar.json"
    good = cp.read_bytes()
    rows = json.loads(good)
    rows.append({"date": fake, "open": "09:30", "close": "16:00"})
    rows.sort(key=lambda x: x["date"])
    cp.write_text(json.dumps(rows), encoding="utf-8")
    sch = z.schedule(next(d for d in cal if d["date"] == oc), cal)[8]
    act = sch + timedelta(seconds=30)
    with _Clock(act), pytest.raises(SystemExit):
        ck.run_opening_checkpoint(tmp_path, lg.path, sch, lambda: S1_RECEIPT, lambda: dict(S1_PROCESS),
                                  tmp_path / "crash.log", now=lambda: act)
    assert _aborted(tmp_path)["reason"] == "registration artifact"
    cp.write_bytes(good)
    with _Clock(act + timedelta(minutes=30)), pytest.raises(SystemExit):
        r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    assert c.load_abort(out)["reason"] == "registration artifact"
    assert not (out / "attest_start.json").exists()


def test_h3_the_anchor_is_the_earliest_possible_first_slot_of_the_audit_bound_opening_date(tmp_path):
    """Controller decision on H-3: the anchor is the first slot of the opening date (plan.json's opening_close,
    verified against the AUDIT-ACK's plan_sha256) computed as if the close were the earliest early close (13:00 New
    York) - never read from calendar.json: an edited calendar does not move it."""
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    out = tmp_path / "s1_out"
    want = z.first_slot_after(datetime.combine(datetime.fromisoformat(oc).date(), time(13, 0), tzinfo=c.NY)
                              .astimezone(timezone.utc))
    assert c.opening_anchor(out) == want
    (out / "audit" / "calendar.json").write_text(json.dumps([{"date": "2026-10-25", "open": "09:30",
                                                              "close": "16:00"}]), encoding="utf-8")
    assert c.opening_anchor(out) == want


def test_h3_a_plan_differing_from_the_audit_ack_with_no_opening_evidence_is_a_refusal(tmp_path, monkeypatch):
    """Controller decision on H-3: plan.json no longer equals the AUDIT-ACK's plan_sha256 and no local opening
    evidence exists (a hand-made prereg only): a preserved refusal with zero live callbacks, never an abort."""
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    out = tmp_path / "s1_out"
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    plan["opening_close"] = "2026-10-22"
    (out / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    _fabricate(tmp_path, ["prereg.json"], cal)
    with pytest.raises(SystemExit):
        c.registration_gate(out, "checkpoint", now=lambda: MON + timedelta(minutes=45))
    assert c.load_abort(out) is None, c.load_abort(out)


def test_h3_a_plan_differing_from_the_audit_ack_with_opening_evidence_is_the_abort(tmp_path):
    """Controller decision on H-3: after the opening seal, plan.json changed (its opening_close moved to the day
    before; it no longer equals the AUDIT-ACK's plan_sha256): local opening evidence exists - the persistent abort."""
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    lg = Ledger(tmp_path / "l.sqlite3")
    assert s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT)["seal"]["written"]
    out = tmp_path / "s1_out"
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    plan["opening_close"] = "2026-10-22"
    (out / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(SystemExit):
        c.registration_gate(out, "checkpoint", now=lambda: START_DT - timedelta(days=2))
    assert _aborted(tmp_path)["reason"] == "registration artifact"


# ====================================================================== item 2 (rule 3 corrected)
def test_rule3_no_audit_ack_for_the_bundle_is_always_a_refusal_even_with_opening_evidence(tmp_path, monkeypatch):
    """Controller correction of the fix-8 brief rule 3 (B3.2, the I-2 fix; replaces
    fix8::test_h_opening_evidence_without_any_audit_ack_for_the_bundle_is_the_abort): the mailbox readable but NO
    AUDIT-ACK carries the bundle - the trial cannot be registered - so, whatever local files exist (here the whole
    registered opening: seal, records, captures, receipt), the next command is a preserved refusal with zero live
    callbacks and NO abort."""
    s1_state(tmp_path, START)
    _drop_audit_ack(tmp_path)
    con = sqlite3.connect(tmp_path / "mailbox.sqlite3")
    con.execute("DELETE FROM messages WHERE id=?", ("run-ack",))
    con.commit()
    con.close()
    out = tmp_path / "s1_out"
    spies = Spies(monkeypatch)
    with pytest.raises(SystemExit):
        c.verify_bundle_first(out, "checkpoint", now=lambda: MON + timedelta(minutes=45), need="audit")
    assert c.load_abort(out) is None, c.load_abort(out)
    assert spies.zero() and _refusals(tmp_path)
