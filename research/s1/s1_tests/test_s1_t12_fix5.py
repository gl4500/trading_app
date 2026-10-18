"""Task 12 fix round 5 (re-review 3 of fix round 4: R-1, R-2, R-3). Written BEFORE the fix; behavioural RED per item
in s1_evidence/t12_fix5_<id>_red.txt. The reviewer probes (scratchpad/probe/test_probe6.py, test_probe8.py) are
permanent tests here; the crash-like residual probe (test_probe7.py) is re-run as evidence
(s1_evidence/t12_fix5_R3_residual_probe.txt). Time is an injected aware clock. Synthetic only: tmp_path ledgers,
mailbox and HMAC key; no live DB, network, real mailbox or scheduler.
Tests marked "guard" pass before and after the fix: they pin behaviour the fix must keep."""
import json
from datetime import timedelta

import pytest

import s1_checkpoint as ck
import s1_common as c
import s1_run as r
import s1_seal as z
from conftest import S1_RECEIPT, S1_PROCESS, Ledger, _Clock, s1_opening_checkpoint, s1_plan_audit, s1_state
from test_s1_t12_fix2_b3 import MON, Spies, _aborted, _cp
from test_s1_t12_fix4 import START, START_DT, _delete, _opening, _reopen

FMT = "%Y%m%dT%H%M%SZ"


def _slots(cal, oc):
    return z.schedule(next(d for d in cal if d["date"] == oc), cal)


def _read(p):
    return json.loads(p.read_text(encoding="utf-8"))


# ====================================================================== R-1 a MISSED slot is not an orphan
def test_r1_probe_an_opening_whose_first_slot_never_ran_still_seals(tmp_path):
    """R-1 reviewer probe test_legit_missed_first_slot (B1.2/B1.4): the opening's first slot (20:45) never runs; slot
    20:55 captures and defers (slot 20:47's window is still open), and its finalizer publishes the MISSED record of
    the never-claimed 20:45 slot - a resolution that legitimately has no claim. The next opening slot must seal
    normally (from the 20:55 SUCCESS, first in slot order): no persistent abort, no refusal."""
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    out = tmp_path / "s1_out"
    lg = Ledger(tmp_path / "l.sqlite3")
    slots = _slots(cal, oc)
    rep = s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT, minutes=55)
    assert not rep["seal"]["written"] and rep.get("deferred"), rep
    first = out / "captures" / oc / slots[0].strftime(FMT)
    assert _read(first.parent / f"{first.name}.resolution.json")["outcome"] == "MISSED"
    assert not (first.parent / f"{first.name}.attempt.json").exists()
    try:                                                 # (strengthened after GREEN, A10.2: a refusal or abort is
        rep = _reopen(tmp_path, lg, oc, cal, 7)          # an assertion failure, not an escaping SystemExit)
    except SystemExit as e:
        pytest.fail(f"the next opening slot refused: {e}")
    assert c.load_abort(out) is None, c.load_abort(out)
    assert rep["seal"]["written"] and rep["seal"].get("from_slot") == slots[5].isoformat(), rep
    assert (out / "seals" / f"{oc}.json").exists()


def _failed_first_slot(tmp_path):
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    lg = Ledger(tmp_path / "l.sqlite3")

    def no_process():
        raise RuntimeError("process observation unavailable")
    sch = _slots(cal, oc)[0]
    act = sch + timedelta(seconds=30)
    with _Clock(act):
        ck.run_opening_checkpoint(tmp_path, lg.path, sch, lambda: S1_RECEIPT, no_process, tmp_path / "crash.log",
                                  now=lambda: act)
    return tmp_path / "s1_out", cal, oc, lg, sch.strftime(FMT)


def test_r1_guard_a_failure_resolution_whose_claim_was_deleted_is_still_the_persistent_abort(tmp_path):
    """R-1 guard (fix4 deletion-orphan class): a legitimate FAILURE at the first opening slot, then its claim deleted:
    a FAILURE (unlike a finalizer's MISSED) is only ever published after its claim, so the next opening slot records
    the persistent "registration artifact" abort and no opening seal is written."""
    out, cal, oc, lg, name = _failed_first_slot(tmp_path)
    (out / "captures" / oc / f"{name}.attempt.json").unlink()
    with pytest.raises(SystemExit):
        _reopen(tmp_path, lg, oc, cal, 1)
    assert _aborted(tmp_path)["reason"] == "registration artifact"
    assert not (out / "seals" / f"{oc}.json").exists()


@pytest.mark.parametrize("forgery", ["decided-before-E", "other-slot", "with-evidence", "unreadable"])
def test_r1_guard_a_missed_record_no_finalizer_writes_is_still_an_orphan(tmp_path, forgery):
    """R-1 guard (the optional field check): only a MISSED record a finalizer can have written - for its own slot,
    decided after that slot's eligibility end E, without capture evidence - is consistent without a claim. Any
    other claimless resolution of an opening slot is the persistent abort, never a seal."""
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    out = tmp_path / "s1_out"
    lg = Ledger(tmp_path / "l.sqlite3")
    day = next(d for d in cal if d["date"] == oc)
    slots = _slots(cal, oc)
    until = z.eligible_until(slots[0], day, cal)
    rec = {"outcome": "MISSED", "slot": slots[0].isoformat(), "eligible_until": until.isoformat(),
           "decided_utc": (until + timedelta(minutes=1)).isoformat()}
    if forgery == "decided-before-E":
        rec["decided_utc"] = (until - timedelta(minutes=1)).isoformat()
    elif forgery == "other-slot":
        rec["slot"] = slots[1].isoformat()
    elif forgery == "with-evidence":
        rec["evidence"] = {"capture_ok": True}
    p = out / "captures" / oc / f"{slots[0].strftime(FMT)}.resolution.json"
    p.parent.mkdir(parents=True)
    p.write_text("{not json" if forgery == "unreadable" else json.dumps(rec), encoding="utf-8")
    with pytest.raises(SystemExit):
        _reopen(tmp_path, lg, oc, cal, 6)
    assert _aborted(tmp_path)["reason"] == "registration artifact"
    assert not (out / "seals" / f"{oc}.json").exists()


# ====================================================================== R-2 the clock anchor from registered evidence
def _move_plan(out, opening_close="2027-12-31"):
    p = out / "plan.json"
    good = p.read_bytes()
    plan = json.loads(good)
    plan["opening_close"] = opening_close
    p.write_text(json.dumps(plan), encoding="utf-8")
    return good


def test_r2_probe_moving_the_plans_opening_close_after_registration_aborts_and_restoring_does_not_resume(tmp_path):
    """R-2 reviewer probe test_plan_moves_anchor (B3.3/B3.5 "registered plan changed ... then restored -> still
    invalid"): after prereg (records and RUN-ACK present) plan.json's opening_close is moved to 2027-12-31. The clock
    anchor comes from registered evidence, not from the plan it guards, so the next checkpoint records the persistent
    "registration artifact" abort (not a pre-registration refusal); after plan.json is restored the trial is still
    ABORTED-INVALID - it never runs again.
    Fix round 10 note (the mechanism described above is superseded; text only): the clock anchor now comes only from the
    AUDIT-ACK found by bundle_sha256 (plan.json's opening_close is used only while it equals that ACK's plan_sha256; the
    earliest possible first slot), and the RUN-ACK found by bundle_sha256 registers on its own and binds the plan hash
    (§21-§22)."""
    st_ = s1_state(tmp_path, START)
    with _Clock(START_DT - timedelta(days=1)):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    out = tmp_path / "s1_out"
    good = _move_plan(out)
    with pytest.raises(SystemExit):
        _cp(tmp_path, st_["ledger"].path)
    ab = _aborted(tmp_path)
    assert ab["reason"] == "registration artifact" and any("plan.json" in x for x in ab["problems"]), ab
    (out / "plan.json").write_bytes(good)
    try:
        rep = _cp(tmp_path, st_["ledger"].path, minutes=47)
    except SystemExit:
        rep = None
    assert c.load_abort(out)["reason"] == "registration artifact"
    assert rep is None or rep["stop"]["status"] == "ABORTED-INVALID", rep["stop"]


def test_r2_moving_the_plans_opening_close_after_the_opening_seal_before_any_run_ack_aborts(tmp_path):
    """R-2: the same edit between the opening seal and any RUN-ACK (the opening's two records, its seal and its slot
    claim are registered evidence): the gate records the persistent abort; restoring plan.json keeps it.
    Fix round 10 note (the mechanism described above is superseded; text only): the edited plan no longer equals the
    AUDIT-ACK's plan_sha256, so it names no opening date; with the opening evidence present that is the abort (§22)."""
    out, cal, oc, lg, first = _opening(tmp_path)
    good = _move_plan(out)
    t = _slots(cal, oc)[0] + timedelta(hours=2)
    with pytest.raises(SystemExit):
        c.registration_gate(out, "checkpoint", now=lambda: t)
    assert _aborted(tmp_path)["reason"] == "registration artifact"
    (out / "plan.json").write_bytes(good)
    c.registration_gate(out, "checkpoint", now=lambda: t + timedelta(minutes=5))
    assert c.load_abort(out)["reason"] == "registration artifact"


def test_r2_the_run_ack_alone_anchors_the_opening(tmp_path):
    """R-2 (never let the plan override the RUN-ACK): after prereg, the opening seal, both records of every stage and
    every capture are deleted and plan.json's opening_close is moved later. The external RUN-ACK (binding the audit
    manifest; it names planned START, whose preceding session is the opening close) still anchors the clock: the
    deletion is the persistent abort, not a pre-registration refusal.
    Fix round 10 note (the mechanism described above is superseded; text only): the RUN-ACK is found by bundle_sha256
    and registers on its own (rule 1a); it no longer anchors the clock - the anchor comes only from the AUDIT-ACK
    (§21-§22)."""
    s1_state(tmp_path, START)
    with _Clock(START_DT - timedelta(days=1)):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    out = tmp_path / "s1_out"
    assert _delete(out, ["seals", "registry", "witnesses", "captures"])
    _move_plan(out)
    assert c.run_ack_witness(out) is not None
    with pytest.raises(SystemExit):
        c.registration_gate(out, "checkpoint", now=lambda: MON + timedelta(minutes=45))
    assert _aborted(tmp_path)["reason"] == "registration artifact"


# ====================================================================== R-3 a second opening seal
def test_r3_an_opening_slot_after_the_seal_leaves_a_claim_and_a_report_binding_the_seal(tmp_path, monkeypatch):
    """R-3 hardening: an opening slot that runs after the opening seal exists still refuses ("opening seal exists"),
    with zero live callbacks and no capture, but first leaves durable evidence binding the seal: its exclusive slot
    claim, its resolution and a refused report recording the seal's sha256. The seal and the stored receipt are
    unchanged, and the state stays consistent (no orphan, no registration problem)."""
    out, cal, oc, lg, first = _opening(tmp_path)
    receipt = (out / "opening_receipt.json").read_bytes()
    spies = Spies(monkeypatch)
    with pytest.raises(SystemExit, match="opening seal exists"):
        _reopen(tmp_path, lg, oc, cal, 1, spies)
    assert spies.zero(), spies.n
    d, name = out / "captures" / oc, _slots(cal, oc)[1].strftime(FMT)
    assert (d / f"{name}.attempt.json").exists() and not (d / name).exists()
    assert (d / f"{name}.resolution.json").exists(), "the after-seal slot was left unresolved"   # (after GREEN)
    assert _read(d / f"{name}.resolution.json")["outcome"] in ("FAILURE", "RESOLUTION-TIMEOUT")
    rep = _read(d / f"{name}.report.json")
    assert rep["refused"] and rep["after_seal"] == {"seal": f"seals/{oc}.json", "sha256": first}, rep
    assert c.sha256_file(out / "seals" / f"{oc}.json") == first
    assert (out / "opening_receipt.json").read_bytes() == receipt
    t = _slots(cal, oc)[1] + timedelta(minutes=5)
    assert c.opening_orphans(out) == [] and c.registration_problems(out, now=lambda: t) == []


def test_r3_deleting_the_seal_and_its_sealing_slot_records_after_a_later_slot_bound_it_aborts(tmp_path,
                                                                                              monkeypatch):
    """R-3: the §17.3 crash-like deletion (the opening seal, both records, the sealing slot's resolution and report,
    the stored receipt; its claim and capture kept) AFTER a later opening slot recorded the seal's hash: the after-
    seal report witnesses the seal, so the next opening slot records the persistent abort with zero live callbacks
    and no second, different opening seal is ever written."""
    out, cal, oc, lg, first = _opening(tmp_path)
    with pytest.raises(SystemExit, match="opening seal exists"):
        _reopen(tmp_path, lg, oc, cal, 1)
    sealing = _slots(cal, oc)[0].strftime(FMT)
    assert _delete(out, [f"seals/{oc}.json", "registry", "witnesses", f"captures/{oc}/{sealing}.resolution.json",
                         f"captures/{oc}/{sealing}.report.json", "opening_receipt.json"])
    spies = Spies(monkeypatch)
    with pytest.raises(SystemExit):
        _reopen(tmp_path, lg, oc, cal, 8, spies)
    assert not (out / "seals" / f"{oc}.json").exists(), "a second, different opening seal was written"
    assert _aborted(tmp_path)["reason"] == "registration artifact"
    assert spies.zero(), spies.n


def test_r3_the_after_seal_claim_alone_still_binds_the_seal(tmp_path, monkeypatch):
    """R-3 (written after the first R-3 GREEN, before its code; the residual probe's V2): the same deletion, but
    also the after-seal slot's resolution and report - only its exclusive claim stays. The claim itself records the
    seal's sha256, so it still witnesses the seal: the persistent abort, never a second opening seal."""
    out, cal, oc, lg, first = _opening(tmp_path)
    with pytest.raises(SystemExit, match="opening seal exists"):
        _reopen(tmp_path, lg, oc, cal, 1)
    later = _slots(cal, oc)[1].strftime(FMT)
    assert _delete(out, [f"seals/{oc}.json", "registry", "witnesses", f"captures/{oc}/*.resolution.json",
                         f"captures/{oc}/*.report.json", "opening_receipt.json"])
    spies = Spies(monkeypatch)
    with pytest.raises(SystemExit):
        _reopen(tmp_path, lg, oc, cal, 8, spies)
    assert not (out / "seals" / f"{oc}.json").exists(), "a second, different opening seal was written"
    assert _aborted(tmp_path)["reason"] == "registration artifact"
    assert spies.zero(), spies.n
    assert c.load_json(out / "captures" / oc / f"{later}.attempt.json").get("after_seal", {}).get("sha256") == first


def test_r3_the_selection_never_writes_an_opening_seal_differing_from_a_recorded_opening_seal_hash(tmp_path):
    """R-3 (selection): a report recording an opening-seal hash appears after the gate ran (written during this run's
    capture, with its claim and resolution, so it is no orphan). The serialized selection compares the seal it is
    about to write with every recorded opening-seal hash: a different seal is the persistent abort, never written."""
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    out = tmp_path / "s1_out"
    lg = Ledger(tmp_path / "l.sqlite3")
    slots = _slots(cal, oc)
    close = z.close_of(oc, cal)
    d, name = out / "captures" / oc, slots[1].strftime(FMT)

    def receipt():                                       # runs after the gate, before the selection
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.attempt.json").write_text(json.dumps({"scheduled": slots[1].isoformat()}), encoding="utf-8")
        (d / f"{name}.resolution.json").write_text(json.dumps({"outcome": "FAILURE", "slot": slots[1].isoformat()}),
                                                   encoding="utf-8")
        (d / f"{name}.report.json").write_text(json.dumps({
            "close": close.isoformat(), "scheduled": slots[1].isoformat(), "refused": "opening seal exists",
            "seal": {"written": False, "sha256": None},
            "after_seal": {"seal": f"seals/{oc}.json", "sha256": "ab" * 32}}), encoding="utf-8")
        return S1_RECEIPT
    act = slots[0] + timedelta(seconds=30)
    with _Clock(act), pytest.raises(SystemExit):
        ck.run_opening_checkpoint(tmp_path, lg.path, slots[0], receipt, lambda: dict(S1_PROCESS),
                                  tmp_path / "crash.log", now=lambda: act)
    assert not (out / "seals" / f"{oc}.json").exists(), "an opening seal differing from the recorded hash was written"
    assert _aborted(tmp_path)["reason"] == "registration artifact"


def test_r1_retro_a_failure_record_left_without_its_claim_and_capture_is_an_orphan(tmp_path):
    """RETROSPECTIVE (written after GREEN, A10.2: isolates the MISSED-only exemption from the last_process.json
    rule that masked it). Two legitimate FAILUREs (first two opening slots); then the first slot's claim AND capture
    directory are deleted, so only its FAILURE resolution and report remain without a claim (another claim still
    exists). Only a finalizer's MISSED record is consistent without a claim: the next slot records the abort."""
    out, cal, oc, lg, name = _failed_first_slot(tmp_path)

    def no_process():
        raise RuntimeError("process observation unavailable")
    sch = _slots(cal, oc)[1]
    with _Clock(sch + timedelta(seconds=30)):
        ck.run_opening_checkpoint(tmp_path, lg.path, sch, lambda: S1_RECEIPT, no_process, tmp_path / "crash.log",
                                  now=lambda: sch + timedelta(seconds=30))
    assert _delete(out, [f"captures/{oc}/{name}.attempt.json", f"captures/{oc}/{name}"])
    with pytest.raises(SystemExit):
        _reopen(tmp_path, lg, oc, cal, 2)
    assert _aborted(tmp_path)["reason"] == "registration artifact"
    assert not (out / "seals" / f"{oc}.json").exists()
