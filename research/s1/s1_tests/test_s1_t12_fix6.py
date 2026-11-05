"""Task 12 fix round 6 (re-review 4 of fix round 5: F-1 only). Written BEFORE the fix; behavioural RED in
s1_evidence/t12_fix6_F1_red.txt. The reviewer probe scratchpad/probe/test_probe9.py is a permanent test here. Time is
an injected aware clock. Synthetic only: tmp_path ledgers and mailbox; no live DB, network, real mailbox or
scheduler."""
import json
from datetime import datetime, timezone

import pytest

import s1_checkpoint as ck
import s1_common as c
import s1_seal as z
from conftest import s1_prereg_at  # A3 Task 10 (fixture instant)
from conftest import S1_RECEIPT, Ledger, _Clock, s1_plan_audit
from test_s1_t12_fix2_b3 import Spies, _refusals
from test_s1_t12_fix4 import START

UTC = timezone.utc
BEFORE = datetime(2026, 10, 20, 15, 0, tzinfo=UTC)        # before the real opening close (2026-10-23)
PROBE9 = [
    ["captures/2026-10-01/20261001T204500Z.attempt.json", "captures/2026-10-23/20261023T204500Z.attempt.json",
     "prereg.json"],
    ["captures/2026-10-01/20261001T204500Z.attempt.json", "captures/2026-10-23/20261023T204500Z.attempt.json"],
    ["seals/2026-10-01.json", "captures/2026-10-23/20261023T204500Z.attempt.json", "attest_start.json"],
]


def _fabricate(out, files, cal):
    for rel in files:
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if rel.startswith("seals/"):
            body = {"close": "2026-10-01T20:00:00+00:00", "capture": {}, "trades": []}
        elif rel.endswith("attempt.json"):
            d = rel.split("/")[1]
            body = {"scheduled": f"{d}T20:45:00+00:00", "invoked_utc": f"{d}T20:45:00+00:00",
                    "close": f"{d}T20:00:00+00:00"}
        else:
            body = {"start": START, "calendar": cal, "receipt": S1_RECEIPT, "bundle_sha256": c.bundle_sha256(),
                    "ack": {"ack_id": "forged", "created_utc": START}}
        p.write_text(json.dumps(body), encoding="utf-8")


def _forged_opening_record(out, day):
    """A hand-made opening record (both copies) naming the seal of `day`."""
    for d in ("registry", "witnesses"):
        (out / d).mkdir(parents=True, exist_ok=True)
        (out / d / "opening.json").write_text(json.dumps({"stage": "opening", "artifacts": {
            f"seals/{day}.json": "ab" * 32}}), encoding="utf-8")


def _opening_attempt(tmp_path, cal, oc, spies):
    slot0 = z.schedule(next(d for d in cal if d["date"] == oc), cal)[0]
    with _Clock(BEFORE):
        ck.run_opening_checkpoint(tmp_path, Ledger(tmp_path / "l.sqlite3").path, slot0, spies.receipt,
                                  spies.process, tmp_path / "crash.log", now=lambda: BEFORE)


@pytest.mark.parametrize("files", PROBE9, ids=["earlier-claim+opening-claim+prereg", "two-claims",
                                               "earlier-seal+opening-claim+attest_start"])
def test_f1_probe_fabricated_earlier_close_evidence_before_the_opening_is_a_refusal(tmp_path, monkeypatch, files):
    """F-1 reviewer probe test_earlier_anchor_fabrication (B3.2): with only plan + audit (plan.json unchanged, so its
    opening close is authoritative for the clock anchor), hand-made claims/seals for a close EARLIER than the opening
    close, an opening-close claim and a later-stage file, all before the real opening: the command refuses
    (preserved), with zero live callbacks, and records NO abort - the legitimate opening can still run.
    Fix round 10 note (the mechanism described above is superseded; text only): plan.json's opening close is used
    because its sha256 equals the AUDIT-ACK's plan_sha256 (found by bundle_sha256); the anchor is that date's earliest
    possible first slot, calendar-free (§22)."""
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    out = tmp_path / "s1_out"
    _fabricate(out, files, cal)
    spies = Spies(monkeypatch)
    # A3 Task 7 (F3 table "no row: any claim ..."; E2.4 r3 "a seal file with no PREPARED ... in every state"): once
    # the trial exists (AUDIT-ACK, audit stage rows), hand-made slot claims / a stage-less seal are a registration
    # artifact at the gate - TRIAL-INVALID (and the abort) with zero live callbacks; Addendum 3 governs over the
    # B3.2 pre-opening "refusal, no abort" outcome for these files (the calendar-free clock anchor is unchanged)
    with pytest.raises(SystemExit, match=r"(exists with no journal row|with no INTENT).*INVALID \(registration-artifact\)"):
        _opening_attempt(tmp_path, cal, oc, spies)
    assert spies.zero(), spies.n
    assert c.opening_anchor(out) == c._earliest_first_slot(oc)      # (fix round 9: the calendar-free anchor)


# Fix round 9: test_f1_an_edited_plan_never_lets_earlier_close_evidence_anchor_the_clock REMOVED - controller
# decision on H-3: plan.json differing from the AUDIT-ACK's plan_sha256 with local opening evidence present is the
# persistent abort (it asserted a refusal). Replaced by fix9::test_h3_a_plan_differing_from_the_audit_ack_with_
# opening_evidence_is_the_abort (and its no-evidence refusal twin).

# ====================================================================== retrospective isolating tests (A10.2)
def _drop_audit_ack(tmp_path):
    import sqlite3
    con = sqlite3.connect(tmp_path / "mailbox.sqlite3")
    con.execute("DELETE FROM messages WHERE id=?", ("audit-ack",))
    con.commit()
    con.close()


# Fix round 9: test_f1_retro_without_the_audit_ack_the_run_ack_alone_anchors_an_edited_plan and
# test_f1_retro_without_the_audit_ack_the_opening_records_anchor_an_edited_plan REMOVED - both delete the AUDIT-ACK
# message and asserted an abort; the corrected rule 3 makes a missing AUDIT-ACK always a refusal (fix9::
# test_rule3_*).

# Fix round 7 (G-1): test_f1_retro_an_unchanged_plan_is_authoritative_even_when_the_audit_ack_is_unreadable (a
# round-6 RETROSPECTIVE test, not a brief test) was RETIRED: its premise - a deleted AUDIT-ACK message lets the local
# manifest vouch for the plan, and an opening record naming an earlier close is then ignored - is what the G-1 ruling
# reverses (a missing ack id is a broken binding; registered evidence may only move the anchor earlier, never be
# ignored). Disclosed in S1_BUILD_EVIDENCE §20.2 and the fix round 7 report.

def test_f1_retro_a_later_fallback_source_never_delays_the_anchor(tmp_path):
    """RETROSPECTIVE (written after GREEN, A10.2: every real fallback source names the same opening close). After
    prereg, plan.json is moved later and a hand-made after-seal claim names a LATER close (2026-10-27): the anchor is
    the EARLIEST fallback source (the real opening close), so the plan edit is the persistent abort on 2026-10-26.
    Fix round 10 note (the mechanism described above is superseded; text only): there are no fallback anchor sources any
    more (after-seal claims never move the anchor); the abort follows from the edited plan no longer equalling the
    AUDIT-ACK's plan_sha256 and from the external RUN-ACK registration (§21-§22)."""
    from datetime import timedelta
    import s1_run as r
    from conftest import s1_state
    from test_s1_t12_fix2_b3 import MON, _aborted
    from test_s1_t12_fix4 import START_DT
    from test_s1_t12_fix5 import _move_plan
    s1_state(tmp_path, START)
    with _Clock(s1_prereg_at(tmp_path)):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    out = tmp_path / "s1_out"
    _move_plan(out)
    q = out / "captures" / "2026-10-27" / "20261027T204500Z.attempt.json"
    q.parent.mkdir(parents=True)
    q.write_text(json.dumps({"scheduled": "2026-10-27T20:45:00+00:00", "close": "2026-10-27T20:00:00+00:00",
                             "after_seal": {"seal": "seals/2026-10-27.json", "sha256": "ab" * 32}}), encoding="utf-8")
    with pytest.raises(SystemExit):
        c.registration_gate(out, "checkpoint", now=lambda: MON + timedelta(minutes=45))
    assert _aborted(tmp_path)["reason"] == "registration artifact"
