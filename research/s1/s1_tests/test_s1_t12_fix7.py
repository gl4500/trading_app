"""Task 12 fix round 7 (re-review 5 of fix round 6: G-1 only). Written BEFORE the fix; behavioural RED in
s1_evidence/t12_fix7_G1_red.txt. The reviewer probe scratchpad/probe/test_probe10.py is a permanent test here. Time
is an injected aware clock. Synthetic only: tmp_path ledgers and mailbox (read-only); no live DB, network, real
mailbox or scheduler."""
import json
from datetime import timedelta

import pytest

import s1_common as c
import s1_run as r
from conftest import S1_RECEIPT, _Clock, s1_state
from test_s1_t12_fix2_b3 import MON, _aborted, _cp
from test_s1_t12_fix4 import START, START_DT, _delete


def _registered(tmp_path):
    st_ = s1_state(tmp_path, START)
    with _Clock(START_DT - timedelta(days=1)):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    return st_, tmp_path / "s1_out"


def _edit_plan_and_manifest(out, ack):
    """plan.json's opening_close moved to 2027-12-31 and the audit manifest re-pointed at the edited plan; `ack`:
    "bogus" (an ack id no message has), None (the ack removed) or "keep"."""
    p, mp = out / "plan.json", out / "audit" / "manifest.json"
    good = p.read_bytes(), mp.read_bytes()
    plan = json.loads(good[0])
    plan["opening_close"] = "2027-12-31"
    p.write_text(json.dumps(plan), encoding="utf-8")
    m = json.loads(good[1])
    m["plan_sha256"] = c.sha256_file(p)
    if ack == "bogus":
        m["ack"]["ack_id"] = "bogus"
    elif ack is None:
        m.pop("ack")
    mp.write_text(json.dumps(m), encoding="utf-8")
    return good


@pytest.mark.parametrize("ack", ["bogus", None])
def test_g1_probe_editing_plan_and_manifest_together_aborts_and_restoring_does_not_resume(tmp_path, ack):
    """G-1 reviewer probe test_plan_and_manifest_edit (B3.3/B3.5), healthy mailbox: after prereg, plan.json's
    opening_close is moved and the audit manifest re-pointed at the edited plan with its AUDIT-ACK id made bogus or
    removed. A broken AUDIT-ACK binding never lets the local manifest vouch for the plan: the registered evidence
    (opening records, RUN-ACK) anchors the opening, so the next checkpoint records the persistent "registration
    artifact" abort (the audit manifest is itself bound by the opening records); restoring both files keeps the trial
    ABORTED-INVALID.
    Fix round 10 note (the mechanism described above is superseded; text only): the ACKs are found by bundle_sha256,
    never through the manifest's ack id; the edited plan is unbound and the trial is registered by the RUN-ACK, so every
    bound artifact (the manifest included) is checked (§21-§22)."""
    st_, out = _registered(tmp_path)
    good = _edit_plan_and_manifest(out, ack)
    with pytest.raises(SystemExit):
        _cp(tmp_path, st_["ledger"].path)
    ab = _aborted(tmp_path)
    assert ab["reason"] == "registration artifact", ab
    assert any("audit/manifest.json" in x for x in ab["problems"]), ab["problems"]
    (out / "plan.json").write_bytes(good[0])
    (out / "audit" / "manifest.json").write_bytes(good[1])
    try:
        rep = _cp(tmp_path, st_["ledger"].path, minutes=47)
    except SystemExit:
        rep = None
    assert c.load_abort(out)["reason"] == "registration artifact"
    assert rep is None or rep["stop"]["status"] == "ABORTED-INVALID", rep["stop"]


def test_g1_the_run_ack_alone_anchors_when_the_audit_ack_binding_is_broken(tmp_path):
    """G-1 (2): as the probe (ack id bogus), and the opening seal, every stage record and every capture deleted: the
    readable RUN-ACK alone names the opening close - the persistent abort, never a refusal.
    Fix round 10 note (the mechanism described above is superseded; text only): the RUN-ACK is found by bundle_sha256
    and registers on its own (rule 1a); it does not anchor the clock (§21)."""
    st_, out = _registered(tmp_path)
    _edit_plan_and_manifest(out, "bogus")
    assert _delete(out, ["seals", "registry", "witnesses", "captures"])
    with pytest.raises(SystemExit):
        c.registration_gate(out, "checkpoint", now=lambda: MON + timedelta(minutes=45))
    assert _aborted(tmp_path)["reason"] == "registration artifact"


def test_g1_a_mailbox_outage_never_lets_a_manifest_differing_from_the_opening_records_vouch_for_the_plan(
        tmp_path, monkeypatch):
    """G-1 (1)(a): the mailbox itself is unreadable (the only case the audit manifest's own plan_sha256 may stand in
    for the AUDIT-ACK), but the manifest no longer equals the hash the opening records bound: it vouches for nothing;
    the opening records anchor the opening - the persistent abort.
    Fix round 10 note (the mechanism described above is superseded; text only): in a mailbox outage no anchor is used at
    all - the local witnesses decide (the B3.4 reading, §21.1); the manifest/records comparison is no longer the
    mechanism."""
    st_, out = _registered(tmp_path)
    _edit_plan_and_manifest(out, "keep")
    monkeypatch.setattr(c, "MAILBOX", tmp_path / "no-such-dir" / "mailbox.sqlite3")
    with pytest.raises(SystemExit):
        c.registration_gate(out, "checkpoint", now=lambda: MON + timedelta(minutes=45))
    assert _aborted(tmp_path)["reason"] == "registration artifact"


# ====================================================================== retrospective isolating tests (A10.2)
# Written after GREEN: the plan source can only move the anchor EARLIER, so whether the audit vouches for the plan
# only shows when an edited plan names an EARLIER close than every other source. Each test is such a state BEFORE
# the opening (B3.2): the real code keeps the anchor at the opening close (a preserved refusal); a plan the audit
# does not vouch for, wrongly used, would make the fabricated files a persistent abort.
from datetime import datetime, timezone  # noqa: E402

import s1_seal as z  # noqa: E402
from conftest import Ledger, s1_mailbox, s1_plan_audit  # noqa: E402
from test_s1_t12_fix6 import PROBE9, _fabricate, _forged_opening_record  # noqa: E402

BEFORE = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)


def _edit_earlier(out, ack):
    p, mp = out / "plan.json", out / "audit" / "manifest.json"
    plan = json.loads(p.read_text(encoding="utf-8"))
    plan["opening_close"] = "2026-10-01"
    p.write_text(json.dumps(plan), encoding="utf-8")
    m = json.loads(mp.read_text(encoding="utf-8"))
    m["plan_sha256"] = c.sha256_file(p)
    if ack == "bogus":
        m["ack"]["ack_id"] = "bogus"
    mp.write_text(json.dumps(m), encoding="utf-8")


# Fix round 9: test_g1_retro_a_broken_binding_never_lets_an_edited_plan_pull_the_anchor_earlier REMOVED - it
# asserted a refusal for an edited plan plus a fabricated opening claim; the controller decision on H-3 makes a plan
# differing from the AUDIT-ACK's plan_sha256 with local opening evidence the persistent abort.


# Fix round 8: test_g1_retro_an_outage_manifest_differing_from_the_records_never_pulls_the_anchor_earlier REMOVED -
# its premise (in a mailbox outage the opening records name the anchor) is superseded: in an outage the fix-8 rule
# keeps the local witnesses without any anchor (B3.4), so hand-made records + claims there fail closed (§21.3).


def test_g1_retro_a_vouched_plan_keeps_the_anchor_below_a_later_forged_source(tmp_path, monkeypatch):
    """RETROSPECTIVE. After prereg, the mailbox unreadable and both stage-record directories deleted (the unchanged
    plan is vouched for by the manifest), plus a forged after-seal claim naming a LATER close: the vouched plan's
    opening close stays the anchor, so the deletion is the persistent abort on 2026-10-26 (not a refusal until the
    forged close).
    Fix round 10 note (the mechanism described above is superseded; text only): in a mailbox outage no anchor is used at
    all; the abort follows from the local witnesses (§21.1)."""
    st_, out = _registered(tmp_path)
    assert _delete(out, ["registry", "witnesses"])
    q = out / "captures" / "2026-10-27" / "20261027T204500Z.attempt.json"
    q.parent.mkdir(parents=True)
    q.write_text(json.dumps({"scheduled": "2026-10-27T20:45:00+00:00", "close": "2026-10-27T20:00:00+00:00",
                             "after_seal": {"seal": "seals/2026-10-27.json", "sha256": "ab" * 32}}), encoding="utf-8")
    monkeypatch.setattr(c, "MAILBOX", tmp_path / "no-such-dir" / "mailbox.sqlite3")
    with pytest.raises(SystemExit):
        c.registration_gate(out, "checkpoint", now=lambda: MON + timedelta(minutes=45))
    assert _aborted(tmp_path)["reason"] == "registration artifact"
