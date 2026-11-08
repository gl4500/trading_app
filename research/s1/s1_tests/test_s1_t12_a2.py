"""Task 12 (controller-added): Addendum 1 rev 3 section A2 (stop freezing, post-stop operation, integrity through the
persisted stop). Written BEFORE the implementation (RED: s1_evidence/t12_A2_red.txt). All synthetic: tmp_path
ledgers and mailbox, fixed clocks; no live DB, network, real mailbox or scheduler."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import s1_checkpoint as ck
import s1_collect as k
import s1_common as c
import s1_run as r
import s1_seal as z
from conftest import s1_prereg_at  # A3 Task 10 (fixture instant)
from conftest import s1_prereg_ack  # A3 Task 6
from conftest import (S1_PROCESS, S1_RECEIPT, _Clock, _write_seal, s1_mailbox, s1_reack, s1_score_refused, s1_state,
                      s1_sync_portfolio)
from conftest import S1_LOCAL_ABORT, s1_local_abort_recorded  # A3 H1 (Erratum 2 r4 G6)

UTC = timezone.utc
START = "2026-10-26T13:30:00+00:00"                     # Mon 09:30 EDT; opening close Fri 2026-10-23
START_DT = datetime(2026, 10, 26, 13, 30, tzinfo=UTC)
STOP_CLOSE = datetime(2026, 10, 27, 20, 0, tzinfo=UTC)  # s1_state default: 100 lots bought 10-26, sold 10-27


def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _cp(root, ledger, day_close, minutes=45, receipt=S1_RECEIPT):
    sch = day_close + timedelta(minutes=minutes)
    act = sch + timedelta(seconds=30)
    with _Clock(act):
        return ck.run_checkpoint(root, ledger.path, sch, lambda: receipt, lambda: dict(S1_PROCESS),
                                 Path(root) / "crash.log", now=lambda: act)


def _live_stop(tmp_path):
    """A registered trial whose stop is determined by the REAL scheduled checkpoint: 100 lots bought on the START
    session and sold on the next; checkpoints seal 10-26 and 10-27 (the stop)."""
    st_ = s1_state(tmp_path, START)
    with _Clock(s1_prereg_at(tmp_path)):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    s1_prereg_ack(tmp_path)                    # A3 Task 6 (F7.4): the PREREG-ACK before captures
    lg = st_["ledger"]
    rows = list(st_["rows"])
    for i in range(100):
        rid = lg.trade(f"S{i % 5}", "BUY", 10, 100.0, "2026-10-26T15:00:00+00:00")
        rows.append({"id": rid, "symbol": f"S{i % 5}", "action": "BUY", "shares": 10.0, "price": 100.0,
                     "timestamp": "2026-10-26T15:00:00+00:00", "ts": "2026-10-26T15:00:00+00:00"})
    s1_sync_portfolio(lg, rows)
    assert _cp(tmp_path, lg, datetime(2026, 10, 26, 20, 0, tzinfo=UTC))["seal"]["written"]
    for i in range(100):
        rid = lg.trade(f"S{i % 5}", "SELL", 10, 90.0, "2026-10-27T18:00:00+00:00")
        rows.append({"id": rid, "symbol": f"S{i % 5}", "action": "SELL", "shares": 10.0, "price": 90.0,
                     "timestamp": "2026-10-27T18:00:00+00:00", "ts": "2026-10-27T18:00:00+00:00"})
    s1_sync_portfolio(lg, rows)
    rep = _cp(tmp_path, lg, STOP_CLOSE)
    assert rep["seal"]["written"] and rep["stop"]["status"] == "STOPPED", rep
    return st_, lg, rows


# ====================================================================== A2.1 the persisted stop
def test_a2_the_stop_is_persisted_once_at_the_seal_with_its_identity(tmp_path):
    """A2.1: when the stop is determined at a seal, its identity - stop close, authoritative stop seal file and
    sha256, cohort row ids, decision time - is persisted once in s1_out/stop.json (exclusive)."""
    st_, lg, rows = _live_stop(tmp_path)
    out = tmp_path / "s1_out"
    s = read(out / "stop.json")
    assert s["status"] == "STOPPED" and c.aware(s["stop_close"]) == STOP_CLOSE
    assert s["stop_seal"] == "seals/2026-10-27.json"
    assert s["stop_seal_sha256"] == c.sha256_file(out / "seals" / "2026-10-27.json")
    cohort = sorted(t["id"] for t in rows if t["action"] == "BUY" and START_DT <= c.aware(t["ts"]) <= STOP_CLOSE)
    assert s["cohort_row_ids"] == cohort and len(cohort) == 100
    # A3 Task 11 (intended, F2.1 / OQ-8 r1): no wall-clock decision fields; the record is the journal's TRIAL-STOP
    # detail; determined_utc = the trigger row's `at` (provenance: the stop close's first QUALIFIED, R = the
    # checkpoint's clock); the frozen seals are the ELIGIBLE sampled ones (r1 A4: the opening seal is not listed)
    import s1_journal as j
    import s1_trial as t
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    jr = j.read_trial(tr.trial_id, tr.genesis, tmp_path / "mailbox.sqlite3")
    stop, trig = j.first(jr, "TRIAL-STOP"), j.first(j.subject_rows(jr, "slot/20261027T204500Z"), "SLOT-QUALIFIED")
    assert "decided_utc" not in s and "decided_by" not in s and j.detail_of(s) == stop.detail
    assert (s["rule"], s["triggering_slot"], s["terminal_seq"], s["determined_utc"]) == (
        "lots", trig.subject, trig.seq, trig.at)
    assert c.aware(s["determined_utc"]) == STOP_CLOSE + timedelta(minutes=45, seconds=30)
    assert s["bundle_sha256"] == c.bundle_sha256()
    assert set(s["seals"]) == {"seals/2026-10-26.json", "seals/2026-10-27.json"}
    before = (out / "stop.json").read_bytes()
    with pytest.raises(FileExistsError, match="stop.json"):
        z.persist_stop(out, dict(s, status="TIMEOUT"))
    assert (out / "stop.json").read_bytes() == before


def test_a2_the_persisted_stop_is_never_recomputed_from_later_rows_or_changed_helpers(tmp_path, monkeypatch):
    """A2.1: after stop.json exists, the stop attestation, the final plan and the score use it: a changed helper
    (here count_sold returning 0 - same bundle files, a runtime stub) or later rows cannot move the stop."""
    st_, lg, rows = _live_stop(tmp_path)
    out = tmp_path / "s1_out"
    monkeypatch.setattr(z, "count_sold", lambda *a, **kw: 0)
    t = STOP_CLOSE + timedelta(days=1)
    with _Clock(t):
        att = r.attest_stop(tmp_path, r.STOP_STATEMENT)
        assert c.aware(att["stop_close"]) == STOP_CLOSE and att["stop_sha256"] == c.sha256_file(out / "stop.json")
        assert c.aware(k.final_plan_record(tmp_path)["stop_close"]) == STOP_CLOSE


def test_a2_attest_stop_binds_the_persisted_stop(tmp_path, monkeypatch):
    """A2.1/A7.1: the stop attestation binds stop.json's sha256; an edited stop.json makes it unverified at score
    and the score ABORTED-INVALID (integrity of the frozen experiment)."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    assert read(out / "attest_stop.json")["stop_sha256"] == c.sha256_file(out / "stop.json")
    p = out / "stop.json"
    p.write_text(json.dumps(dict(read(p), decided_by="edited")), encoding="utf-8")
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    s1_reack(tmp_path, "score-ack-2", "S1-SCORE-ACK", st_["now"] - timedelta(minutes=30))
    rep = s1_score_refused(tmp_path, "score-ack-2")   # A3 F0.6/F1: refused; the unit-level record
    assert rep["verdict"] == "ABORTED-INVALID" and any("stop" in x for x in rep["reasons"]), rep["reasons"]


def test_a2_no_valid_seal_is_terminal_persisted_and_never_rescued_by_a_late_seal(tmp_path, monkeypatch):
    """A2.1: NO-VALID-SEAL is persisted the same way; a seal file appearing afterwards (a 'rescue' seal for an
    eligible close) never produces a trial result: the score is not a PASS/FAIL and stop.json is unchanged."""
    st_ = s1_state(tmp_path, START, score_ready=True, lots=[], seal_days=[])
    out = tmp_path / "s1_out"
    s = read(out / "stop.json")
    assert s["status"] == "NO-VALID-SEAL" and s["stop_close"] is None and s["stop_seal"] is None
    before = (out / "stop.json").read_bytes()
    # A3 Task 7 (E2.4/E2.6 r3): no seal stage can start after the STOP, so the late 'rescue' seal can only be a file
    # written outside any stage (here the opening seal's bytes under an eligible close's name): a registration
    # artifact at the score's gate (TRIAL-INVALID), and never a trial result
    (out / "seals" / "2026-10-26.json").write_bytes((out / "seals" / "2026-10-23.json").read_bytes())
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    s1_reack(tmp_path, "score-ack-2", "S1-SCORE-ACK", st_["now"] - timedelta(minutes=30))
    rep = s1_score_refused(tmp_path, "score-ack-2")   # A3 F0.6/F1: refused; the unit-level record
    assert rep["verdict"] in ("NO-VALID-SEAL", "ABORTED-INVALID") and "levels" not in rep, rep
    assert any("seal" in x for x in rep["reasons"]) or rep["verdict"] == "NO-VALID-SEAL"
    assert (out / "stop.json").read_bytes() == before


# ====================================================================== A2.2 post-stop operation
def test_a2_post_stop_checkpoints_follow_the_persisted_stop(tmp_path, monkeypatch):
    """A2.2: after the persisted stop a scheduled checkpoint records a post_stop capture only (no seal), even when
    a (stubbed) stop helper would now call the trial RUNNING."""
    st_, lg, rows = _live_stop(tmp_path)
    out = tmp_path / "s1_out"
    monkeypatch.setattr(z, "stop_decision", lambda *a, **kw: {"status": "RUNNING", "stop_close": None,
                                                                 "missed": []})
    rep = _cp(tmp_path, lg, datetime(2026, 10, 28, 20, 0, tzinfo=UTC))
    # A3 Task 6: the legacy `post_stop` report flag is gone (the post-STOP state is the journal's, F1).
    # A3 Task 11 (intended, F1 table): the stop close's checkpoint committed the TRIAL-STOP, so this later slot's
    # INTENT is LOST-RACE with no capture; the persisted stop is unchanged and nothing seals after it
    assert rep["outcome"] == "LOST-RACE", rep
    assert read(out / "stop.json")["status"] == "STOPPED" and c.aware(read(out / "stop.json")["stop_close"]) == \
        STOP_CLOSE
    assert not (out / "seals" / "2026-10-28.json").exists()


def test_a2_a_persisted_invalidity_is_never_converted_into_a_valid_stop(tmp_path, monkeypatch):
    """A2.2: aborted.json after stop.json (e.g. a post-stop bundle mismatch) keeps the trial terminal-invalid: no
    stop attestation, no final plan, score ABORTED-INVALID.
    A3 H1 (intended, Erratum 2 r4 G6.4/G6.7): the stop attestation's trial gate records the surviving abort first
    (one TRIAL-INVALID established-violation / local-abort; the witness's "bundle" reason is provenance only, G6.2)
    and refuses with no work; the final plan (no trial gate) still refuses ABORTED."""
    st_, lg, rows = _live_stop(tmp_path)
    out = tmp_path / "s1_out"
    c.write_abort(out, {"reason": "bundle", "actual": (STOP_CLOSE + timedelta(hours=2)).isoformat()})
    with _Clock(STOP_CLOSE + timedelta(days=1)):
        with pytest.raises(SystemExit, match=S1_LOCAL_ABORT):
            r.attest_stop(tmp_path, r.STOP_STATEMENT)
        assert s1_local_abort_recorded(tmp_path)["original_reason"] == "bundle"
        assert not (out / "attest_stop.json").exists()
        with pytest.raises(SystemExit, match="ABORTED"):
            k.final_plan_record(tmp_path)
    assert read(out / "stop.json")["status"] == "STOPPED"


# ====================================================================== A2.3 integrity through the persisted stop
@pytest.mark.parametrize("tamper", ["stop_seal_edited", "slice_seal_deleted", "extra_slice_seal"])
def test_a2_integrity_of_the_frozen_slices_is_enforced_at_score(tmp_path, monkeypatch, tamper):
    """A2.3: a changed or missing opening/bridge/trial seal (through the persisted stop) or an extra seal among the
    frozen slices is a preserved integrity failure: ABORTED-INVALID at score."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    if tamper == "stop_seal_edited":
        p = out / "seals" / "2026-10-27.json"
        p.write_text(json.dumps(dict(read(p), note="x")), encoding="utf-8")
    elif tamper == "slice_seal_deleted":
        (out / "seals" / "2026-10-26.json").unlink()
    else:                                             # A3 Task 7 (E2.6): no seal stage after the STOP - an extra
        (out / "seals" / "2026-10-22.json").write_bytes(    # seal can only be a file outside any stage
            (out / "seals" / "2026-10-23.json").read_bytes())
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    s1_reack(tmp_path, "score-ack-2", "S1-SCORE-ACK", st_["now"] - timedelta(minutes=30))
    # A3 Task 7 (E2.4/E2.6 r3): a changed or deleted CREATED seal is stage-replaced; an extra one with no stage rows
    # is a registration artifact - both TRIAL-INVALID at the score's gate (the unit-level record is unchanged)
    rep = s1_score_refused(tmp_path, "score-ack-2",
                           reason="registration-artifact" if tamper == "extra_slice_seal" else "stage-replaced")
    assert rep["verdict"] == "ABORTED-INVALID" and any("stop" in x or "seal" in x for x in rep["reasons"]), \
        rep["reasons"]


def test_a2_rows_stored_after_the_stop_close_are_irrelevant_to_the_frozen_experiment(tmp_path, monkeypatch):
    """A2.2/A2.3: ordinary post-stop live operation (a new BUY stored after the stop close, a restart) changes no
    outcome: the final snapshot and the score check fences through the persisted stop only."""
    st_ = s1_state(tmp_path, START, score_ready=True, final_snapshot=False)
    lg = st_["ledger"]
    rid = lg.trade("POST", "BUY", 1, 10.0, "2026-10-29T15:00:00+00:00")
    s1_sync_portfolio(lg, st_["rows"] + [{"id": rid, "symbol": "POST", "action": "BUY", "shares": 1.0,
                                          "price": 10.0, "ts": "2026-10-29T15:00:00+00:00"}])
    with _Clock(st_["snapshot_at"]):
        snap = ck.run_final_snapshot(tmp_path, lg.path, now=lambda: st_["snapshot_at"])
    assert snap["fence_violations"] == [] and c.aware(snap["stop_close"]) == STOP_CLOSE
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    s1_reack(tmp_path, "score-ack-2", "S1-SCORE-ACK", st_["now"] - timedelta(minutes=30))
    rep = r.score(tmp_path, "score-ack-2")
    assert rep["verdict"] == "SHADOW PASS" and rep["reasons"] == [], rep["reasons"]
