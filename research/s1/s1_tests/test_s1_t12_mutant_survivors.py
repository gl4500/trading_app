"""Task 12 (A10.2) tests for the 20 targeted mutants that SURVIVED the first run (s1_evidence/s1_mutants_t12_run1.txt).
ALL RETROSPECTIVE: each isolates a check that an earlier, overlapping check had masked (defense in depth); each
docstring names its mutant. Synthetic only."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

import s1_checkpoint as ck
import s1_collect as k
import s1_common as c
import s1_gates as g
import s1_run as r
import s1_seal as z
import s1_snapshot
from conftest import (S1_PROCESS, S1_RECEIPT, Ledger, _Clock, _write_seal, s1_mailbox, s1_plan_audit, s1_reack,
                      s1_score_refused, s1_state)

UTC = timezone.utc
START = "2026-10-26T13:30:00+00:00"
START_DT = datetime(2026, 10, 26, 13, 30, tzinfo=UTC)
OPEN_CLOSE = datetime(2026, 10, 23, 20, 0, tzinfo=UTC)


def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _registered(tmp_path):
    st_ = s1_state(tmp_path, START)
    with _Clock(START_DT - timedelta(days=1)):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    return st_


def _msg(mid, sender, body, created):
    con = sqlite3.connect(c.MAILBOX)
    con.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,NULL)",
                (mid, sender, "claude", "experiments-prereg", body, created.timestamp()))
    con.commit()
    con.close()


def _set_created(mid, t):
    con = sqlite3.connect(c.MAILBOX)
    con.execute("UPDATE messages SET created=? WHERE id=?", (t.timestamp(), mid))
    con.commit()
    con.close()


def _opening(tmp_path, ledger, minutes=45):
    sch = OPEN_CLOSE + timedelta(minutes=minutes)
    act = sch + timedelta(seconds=30)
    with _Clock(act):
        return ck.run_opening_checkpoint(tmp_path, ledger.path, sch, lambda: S1_RECEIPT, lambda: {},
                                         tmp_path / "crash.log", now=lambda: act)


# ---------------------------------------------------------------------- s1_common
def test_ms_a_message_from_another_sender_carrying_the_exact_token_is_not_an_ack(tmp_path):
    """Mutant "mailbox_message accepts any sender"."""
    s1_mailbox(tmp_path, "x", "unused", datetime(2026, 10, 1, tzinfo=UTC))
    _msg("from-claude", "claude", "S1-X token", datetime(2026, 10, 1, tzinfo=UTC))
    with pytest.raises(SystemExit, match="not a codex->claude"):
        c.mailbox_message("from-claude")


def test_ms_receipt_sha256_refuses_a_receipt_without_fingerprint():
    """Mutant "receipt_sha256 accepts a fingerprint-less receipt"."""
    with pytest.raises(ValueError, match="fingerprint"):
        c.receipt_sha256({"provenance": {}})


def test_ms_registration_refuses_a_prereg_whose_bundle_differs_from_its_run_ack(tmp_path):
    """Mutant "registration: prereg bundle not cross-checked with its RUN-ACK"."""
    _registered(tmp_path)
    p = tmp_path / "s1_out" / "prereg.json"
    p.write_text(json.dumps(dict(read(p), bundle_sha256="0" * 64)), encoding="utf-8")
    with pytest.raises(SystemExit, match="prereg bundle differs from its RUN-ACK"):
        c.registration(tmp_path / "s1_out")


def test_ms_verify_bundle_first_needs_a_prereg_when_asked(tmp_path):
    """Mutant "verify_bundle_first: no prereg requirement"."""
    s1_plan_audit(tmp_path, START)
    with pytest.raises(SystemExit, match="no verified prereg"):
        c.verify_bundle_first(tmp_path / "s1_out", "x", need="prereg")


# ---------------------------------------------------------------------- s1_gates
def test_ms_an_audit_ack_message_without_the_exact_audit_token_refuses(tmp_path, ledger):
    """Mutant "verify_audit_ack skips the token check": the ACK names the right bundle but another START.
    (A3 Task 5 fixture note: journal=False - the TEST rewrites the AUDIT-ACK body, which is every journal row's
    genesis, F0.2; with the audit stage's synthetic rows the chain itself would refuse first.)"""
    s1_plan_audit(tmp_path, START, journal=False)
    tok = c.audit_token(tmp_path / "s1_out").replace(f"start={START}", "start=2027-01-04T14:30:00+00:00")
    con = sqlite3.connect(c.MAILBOX)
    con.execute("UPDATE messages SET body=? WHERE id='audit-ack'", (tok,))
    con.commit()
    con.close()
    with pytest.raises(SystemExit, match="audit token"):
        _opening(tmp_path, ledger)


@pytest.mark.parametrize("when", ["before_plan", "after_reservation"])
def test_ms_audit_ack_causal_timing_is_checked_on_its_own(tmp_path, ledger, when):
    """Mutants "verify_audit_ack: ACK before the plan accepted" / "... after the reservation accepted": mailbox time
    and manifest record agree, only the causal order is wrong."""
    s1_plan_audit(tmp_path, START)
    out = tmp_path / "s1_out"
    t = (c.aware(read(out / "plan.json")["created_utc"]) - timedelta(minutes=1) if when == "before_plan"
         else c.aware(read(out / "audit" / "attempt.json")["reserved_utc"]) + timedelta(minutes=1))
    _set_created("audit-ack", t)
    mp = out / "audit" / "manifest.json"
    m = read(mp)
    m["ack"]["created_utc"] = t.isoformat()
    mp.write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(SystemExit, match="before the plan|not after the plan|before the audit reservation"):
        _opening(tmp_path, ledger)


def test_ms_an_out_of_order_pinned_listing_refuses_the_opening(tmp_path, ledger):
    """Mutant "verified_audit: calendar completeness skipped": consistently pinned, schedulable, but out of order."""
    import test_s1_seal as ts
    cal = [d for d in ts.cal() if d["date"] <= "2027-06-30"]
    i = next(n for n, d in enumerate(cal) if d["date"] == "2026-12-01")
    cal[i], cal[i + 1] = cal[i + 1], cal[i]
    s1_plan_audit(tmp_path, START, calendar=cal)
    with pytest.raises(SystemExit, match="out of order"):
        _opening(tmp_path, ledger)


def test_ms_a_run_ack_message_not_carrying_the_exact_run_token_refuses(tmp_path):
    """Mutant "run_ack_problems skips the token": prereg points at a codex message whose RUN line has the right
    bundle (registration passes) but another runner hash."""
    _registered(tmp_path)
    out = tmp_path / "s1_out"
    pr = read(out / "prereg.json")
    tok = c.run_token(out)
    bad = " ".join(("runner_sha256=" + "0" * 64) if x.startswith("runner_sha256=") else x for x in tok.split(" "))
    _msg("other-ack", "codex", bad, c.aware(pr["ack"]["created_utc"]))
    (out / "prereg.json").write_text(json.dumps(dict(pr, ack=dict(pr["ack"], ack_id="other-ack"))), encoding="utf-8")
    probs = g.run_ack_problems(out, read(out / "prereg.json"))
    assert probs == ["RUN-ACK runner_sha256 does not match"], probs        # A3: field by field (F6.1, OQ-5)


def test_ms_a_run_ack_after_planned_start_is_reported_on_its_own(tmp_path):
    """Mutant "run_ack_problems: ACK after START accepted": ACK and prereg both (forged) after START."""
    _registered(tmp_path)
    out = tmp_path / "s1_out"
    pr = read(out / "prereg.json")
    t = START_DT + timedelta(minutes=5)
    _set_created("run-ack", t)
    pr["ack"]["created_utc"] = t.isoformat()
    pr["recorded_utc"] = (t + timedelta(minutes=1)).isoformat()
    probs = g.run_ack_problems(out, pr)
    assert probs == ["the RUN-ACK is not before planned START"], probs


# ---------------------------------------------------------------------- s1_checkpoint
def test_ms_a_first_ever_unobserved_process_is_a_gap(tmp_path, ledger):
    """Mutant "_observe_process: no gap for an unobserved first process" (the opening is the first observation)."""
    s1_plan_audit(tmp_path, START)
    rep = _opening(tmp_path, ledger)
    assert any("process not observed" in g_ for g_ in rep["restart_gaps"]), rep["restart_gaps"]


def test_ms_the_opening_compares_the_bundle_before_reading_the_audit(tmp_path, ledger, monkeypatch):
    """Mutant "run_opening_checkpoint: bundle not verified first": no audit verification runs before the bundle
    comparison (A3.2: verified FIRST)."""
    s1_plan_audit(tmp_path, START)
    monkeypatch.setattr(c, "bundle_sha256", lambda *a, **kw: "f" * 64)
    monkeypatch.setattr(g, "verified_audit", lambda *a, **kw: pytest.fail("audit read before the bundle check"))
    with pytest.raises(SystemExit, match="S1 bundle"):
        _opening(tmp_path, ledger)


# ---------------------------------------------------------------------- s1_seal / s1_snapshot
def test_ms_stop_problems_reports_an_extra_seal_among_the_frozen_slices(tmp_path):
    """Mutant "stop_problems: extra slices ignored"."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    # A3 Task 7 (E2.6 r3): no seal stage can start after the STOP, so the extra seal is a file outside any stage
    # (stop_problems is the unit under test; the file's own INVALID is the gate's, E2.4)
    (out / "seals" / "2026-10-22.json").write_bytes((out / "seals" / "2026-10-23.json").read_bytes())
    probs = z.stop_problems(out, START_DT, st_["calendar"], recheck=False)
    assert any("seals/2026-10-22.json is not among" in p for p in probs), probs


def test_ms_take_snapshot_measures_with_the_injected_clock(tmp_path, ledger):
    """Mutant "take_snapshot ignores the injected clock"."""
    t = datetime(2030, 1, 1, tzinfo=UTC)
    meta = s1_snapshot.take_snapshot(ledger.path, tmp_path / "cap", now=lambda: t)
    assert c.aware(meta["capture_start"]) == c.aware(meta["capture_end"]) == t


# ---------------------------------------------------------------------- s1_collect
def test_ms_four_sessions_after_the_audit_ack_abort(tmp_path, monkeypatch):
    """Mutant "_validate_calendar: 4 sessions accepted": exactly 4 session opens between the ACK and START."""
    from test_s1_t12_a5_a6 import _audit_client, _plan_and_ack, cal_rows
    _plan_and_ack(tmp_path, monkeypatch, datetime(2026, 10, 21, 12, tzinfo=UTC),
                  datetime(2026, 10, 26, 18, tzinfo=UTC))             # opens 10-27 .. 10-30 = 4
    with pytest.raises(SystemExit, match="ABORTED"):
        k.do_audit(tmp_path, "a1", _audit_client(cal_rows("2026-10-21", "2027-05-31")), ("K", "S"))
    assert "fewer than 5 sessions" in read(tmp_path / "s1_out" / "audit" / "manifest.json")["error"]


# ---------------------------------------------------------------------- s1_run
def test_ms_runner_seals_lists_every_seal_file(tmp_path):
    """Mutant "_seals returns none" (Codex-named helper)."""
    s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    assert [p.name for p, _ in r._seals(out)] == sorted(p.name for p in (out / "seals").glob("*.json"))


def test_ms_runner_write_once_refuses_and_keeps_the_first(tmp_path):
    """Mutant "_write_once overwrites" (Codex-named helper)."""
    p = tmp_path / "x.json"
    r._write_once(p, {"a": 1}, "thing")
    with pytest.raises(SystemExit, match="thing already recorded"):
        r._write_once(p, {"a": 2}, "thing")
    assert read(p) == {"a": 1}


def test_ms_an_action_effective_on_the_start_day_does_not_block_the_registration(tmp_path):
    """Mutant "_pre_start_day is START's day": the pre-START bound is the day BEFORE START's NY date."""
    st_ = s1_state(tmp_path, START, audit_actions=[{"type": "forward_splits", "id": "s", "symbol": "CI",
                                                    "ex_date": "2026-10-26", "old_rate": 1, "new_rate": 2}])
    with _Clock(START_DT - timedelta(days=1)):
        assert (r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)["trial_id"]
                == json.loads((tmp_path / "s1_out" / "plan.json").read_text(encoding="utf-8"))["trial_id"])
    assert r._pre_start_day(START_DT) == "2026-10-25"


def test_ms_stop_json_changed_after_the_attestation_is_named(tmp_path, monkeypatch):
    """Mutant "_score: stop.json changed after the attestation accepted": the specific reason is recorded."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    p = tmp_path / "s1_out" / "stop.json"
    p.write_text(json.dumps(dict(read(p), decided_by="edited")), encoding="utf-8")
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    s1_reack(tmp_path, "score-ack-2", "S1-SCORE-ACK", st_["now"] - timedelta(minutes=30))
    rep = s1_score_refused(tmp_path, "score-ack-2")   # A3 F0.6/F1: refused; the unit-level record
    assert "persisted stop (stop.json) changed after the stop attestation" in rep["reasons"], rep["reasons"]
