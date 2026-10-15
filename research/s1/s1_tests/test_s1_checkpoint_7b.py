"""Task 7b (controller-added): checkpoint `--opening` and `--final-snapshot` modes (design §4/§6/§12/§13).
All synthetic: tmp_path ledgers and mailbox, fixed clocks; no live DB, network or .env."""
import json
from datetime import datetime, timedelta, timezone

import pytest
import s1_checkpoint as ck
import s1_common as c
import s1_run as r
import sqlite3

import s1_seal
import s1_snapshot
from conftest import S1_RECEIPT, _Clock, s1_mailbox, s1_plan_audit, s1_state, s1_sync_portfolio

UTC = timezone.utc
START = "2026-10-26T13:30:00+00:00"
START_DT = datetime(2026, 10, 26, 13, 30, tzinfo=UTC)
OPEN_DAY = "2026-10-23"                                          # the Friday session before the Monday START
OPEN_CLOSE = datetime(2026, 10, 23, 20, 0, tzinfo=UTC)
PROC = {"pid": 1, "process_start": "2026-10-01T09:00:00"}


def read(p):
    return json.loads(p.read_text(encoding="utf-8"))


def opening_ready(tmp_path, ledger):
    """Plan + COMPLETE audit (no prereg) and a consistent synthetic ledger with one carry-in BUY."""
    s1_plan_audit(tmp_path, START, carry_in_syms=["A"], first_day="2026-10-20")
    ledger.trade("A", "BUY", 10, 50, "2026-10-20T15:00:00+00:00")
    ledger.set_portfolio("A", 10)


def opening(tmp_path, ledger, minutes=45, receipt=S1_RECEIPT, scheduled=None, delay=30):
    sch = scheduled or OPEN_CLOSE + timedelta(minutes=minutes)
    act = sch + timedelta(seconds=delay)
    with _Clock(act):
        return ck.run_opening_checkpoint(tmp_path, ledger.path, sch, lambda: receipt, lambda: dict(PROC),
                                         tmp_path / "crash.log", now=lambda: act)


def no_capture(tmp_path):
    return not (tmp_path / "s1_out" / "captures").exists()


# ---------------------------------------------------------------- opening mode
def test_opening_mode_seals_the_opening_close_from_plan_and_audit_without_prereg(tmp_path, ledger):
    """Task 7b (controller-added), C-1: the opening seal exists before any prereg/START attestation."""
    opening_ready(tmp_path, ledger)
    out = tmp_path / "s1_out"
    assert not (out / "prereg.json").exists()
    rep = opening(tmp_path, ledger)
    seal_p = out / "seals" / f"{OPEN_DAY}.json"
    assert rep["seal"] == {"written": True, "sha256": c.sha256_file(seal_p)}
    seal = read(seal_p)
    assert c.aware(seal["close"]) == OPEN_CLOSE and set(seal["fence"]) == {"1"} and seal["max_id"] == 1
    assert seal["receipt_match"] is True and seal["receipt_sha256"] == c.sha256_bytes(c.canonical(S1_RECEIPT))
    assert {"fence", "max_id", "trades", "capture", "restart_record", "process"} <= set(seal)
    proj = out / "captures" / OPEN_DAY / "20261023T204500Z" / "projection.json"
    assert c.sha256_file(proj) == seal["capture"]["projection_sha256"]
    assert read(out / "opening_receipt.json") == S1_RECEIPT
    assert rep["consistent"] is True and rep["capture_ok"] is True and rep["fence_violations"] == []
    assert rep["entries"] == rep["sold"] == "n/a before START" and rep["stop"] == "n/a before START"
    assert (out / "captures" / OPEN_DAY / "20261023T204500Z.report.json").exists()
    text = json.dumps(rep).lower()
    assert "price" not in text and "pnl" not in text
    assert not (out / "prereg.json").exists() and not (out / "aborted.json").exists()


@pytest.mark.parametrize("scheduled", [
    datetime(2026, 10, 22, 20, 45, tzinfo=UTC),                   # a slot of an earlier close
    datetime(2026, 10, 26, 20, 45, tzinfo=UTC),                   # a slot of the START session's close
    OPEN_CLOSE + timedelta(minutes=46),                           # not a registered slot at all
])
def test_opening_mode_refuses_a_non_opening_slot(tmp_path, ledger, scheduled):
    """Task 7b (controller-added)."""
    opening_ready(tmp_path, ledger)
    with pytest.raises(SystemExit, match="opening"):
        opening(tmp_path, ledger, scheduled=scheduled)
    assert no_capture(tmp_path) and not (tmp_path / "s1_out" / "seals").exists()


@pytest.mark.parametrize("breakage", ["outcome", "calendar_hash", "no_manifest"])
def test_opening_mode_refuses_an_incomplete_audit(tmp_path, ledger, breakage):
    """Task 7b (controller-added)."""
    opening_ready(tmp_path, ledger)
    audit = tmp_path / "s1_out" / "audit"
    if breakage == "outcome":
        (audit / "manifest.json").write_text(json.dumps(dict(read(audit / "manifest.json"), outcome="ABORTED")),
                                             encoding="utf-8")
    elif breakage == "calendar_hash":
        cal = read(audit / "calendar.json")
        (audit / "calendar.json").write_text(json.dumps(cal[1:]), encoding="utf-8")
    else:
        (audit / "manifest.json").unlink()
    with pytest.raises(SystemExit, match="audit"):
        opening(tmp_path, ledger)
    assert no_capture(tmp_path)


def test_opening_mode_refuses_a_wrong_opening_close(tmp_path, ledger):
    """Task 7b (controller-added): the plan's opening_close must be the session immediately before START."""
    opening_ready(tmp_path, ledger)
    p = tmp_path / "s1_out" / "plan.json"
    p.write_text(json.dumps(dict(read(p), opening_close="2026-10-22")), encoding="utf-8")
    with pytest.raises(SystemExit, match="opening_close"):
        opening(tmp_path, ledger)
    with pytest.raises(SystemExit, match="opening_close"):           # nor its slot, now that the plan names it
        opening(tmp_path, ledger, scheduled=datetime(2026, 10, 22, 20, 45, tzinfo=UTC))
    assert no_capture(tmp_path)


def test_opening_mode_refuses_a_second_run_once_the_opening_seal_exists(tmp_path, ledger):
    """Task 7b (controller-added)."""
    opening_ready(tmp_path, ledger)
    opening(tmp_path, ledger, minutes=45)
    seal_p = tmp_path / "s1_out" / "seals" / f"{OPEN_DAY}.json"
    before = seal_p.read_bytes(), (tmp_path / "s1_out" / "opening_receipt.json").read_bytes()
    with pytest.raises(SystemExit, match="opening seal exists"):
        opening(tmp_path, ledger, minutes=47)
    assert not (tmp_path / "s1_out" / "captures" / OPEN_DAY / "20261023T204700Z").exists()
    assert (seal_p.read_bytes(), (tmp_path / "s1_out" / "opening_receipt.json").read_bytes()) == before


def test_opening_inconsistent_capture_does_not_seal_rerun_refused_retry_slot_seals(tmp_path, ledger):
    """Task 7b (controller-added): run_checkpoint's capture/consistency/no-overwrite/rerun rules apply."""
    opening_ready(tmp_path, ledger)
    ledger.drop_portfolio("A")                                     # replay 10 vs portfolio 0: inconsistent
    out = tmp_path / "s1_out"
    rep = opening(tmp_path, ledger, minutes=45)
    assert rep["consistent"] is False and rep["seal"]["written"] is False
    assert not (out / "seals").exists() and not (out / "opening_receipt.json").exists()
    with pytest.raises(SystemExit, match="slot already captured"):
        opening(tmp_path, ledger, minutes=45)
    assert len((out / "reruns.jsonl").read_text().splitlines()) == 1
    ledger.set_portfolio("A", 10)
    rep = opening(tmp_path, ledger, minutes=47)
    assert rep["seal"]["written"] is True and (out / "seals" / f"{OPEN_DAY}.json").exists()


def test_opening_late_capture_does_not_seal(tmp_path, ledger):
    """Task 7b (controller-added): the seal is the first consistent capture within SCHEDULE_SLACK of its slot."""
    opening_ready(tmp_path, ledger)
    rep = opening(tmp_path, ledger, minutes=45, delay=11 * 60)
    assert rep["late"] is True and rep["seal"]["written"] is False


def test_attest_start_binds_the_opening_receipt_and_refuses_a_different_one(tmp_path, ledger):
    """Task 7b (controller-added): attest_start binds the opening seal and s1_out/opening_receipt.json."""
    opening_ready(tmp_path, ledger)
    out = tmp_path / "s1_out"
    rp = out / "opening_receipt.json"
    with _Clock(START_DT - timedelta(days=2)):
        with pytest.raises(SystemExit, match="opening seal"):              # no opening checkpoint yet
            r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    opening(tmp_path, ledger)
    saved = rp.read_bytes()
    rp.unlink()
    with _Clock(START_DT - timedelta(days=2)):
        with pytest.raises(SystemExit, match="no opening receipt"):         # seal present, receipt file gone
            r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    rp.write_bytes(saved)
    with _Clock(START_DT - timedelta(days=2)):
        with pytest.raises(SystemExit, match="opening receipt"):
            r.attest_start(tmp_path, r.START_STATEMENT, dict(S1_RECEIPT, head="other"))
        assert not (out / "attest_start.json").exists()
        a = r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    assert a["receipt_sha256"] == c.sha256_bytes(c.canonical(read(rp)))
    assert a["opening_seal_sha256"] == c.sha256_file(out / "seals" / f"{OPEN_DAY}.json")


def test_attest_start_refuses_when_the_opening_receipt_differs_from_the_seal(tmp_path, ledger):
    """Task 7b (controller-added): an edited opening_receipt.json no longer matches the sealed receipt hash."""
    opening_ready(tmp_path, ledger)
    opening(tmp_path, ledger)
    other = dict(S1_RECEIPT, head="other")
    (tmp_path / "s1_out" / "opening_receipt.json").write_text(json.dumps(other), encoding="utf-8")
    with _Clock(START_DT - timedelta(days=2)):
        with pytest.raises(SystemExit, match="opening"):
            r.attest_start(tmp_path, r.START_STATEMENT, other)
    assert not (tmp_path / "s1_out" / "attest_start.json").exists()


# ---------------------------------------------------------------- final-snapshot mode
def test_final_snapshot_refuses_without_prereg_and_while_running(tmp_path):
    """Task 7b (controller-added)."""
    st_ = s1_state(tmp_path, START)
    out = tmp_path / "s1_out"
    with pytest.raises(SystemExit, match="prereg"):
        ck.run_final_snapshot(tmp_path, st_["ledger"].path, now=lambda: START_DT - timedelta(hours=3))
    with _Clock(START_DT - timedelta(hours=2)):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    with pytest.raises(SystemExit, match="RUNNING"):
        ck.run_final_snapshot(tmp_path, st_["ledger"].path, now=lambda: START_DT + timedelta(days=1))
    assert not (out / "final_snapshot").exists()


def test_final_snapshot_after_a_recorded_abort_is_taken(tmp_path):
    """Task 7b (controller-added): an aborted trial has stopped too (aborted.json)."""
    st_ = s1_state(tmp_path, START)
    with _Clock(START_DT - timedelta(hours=2)):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    (tmp_path / "s1_out" / "aborted.json").write_text(json.dumps(
        {"reason": "semantic receipt changed", "actual": (START_DT + timedelta(hours=8)).isoformat()}),
        encoding="utf-8")
    rep = ck.run_final_snapshot(tmp_path, st_["ledger"].path, now=lambda: START_DT + timedelta(days=1))
    assert rep["trial_status"] == "ABORTED-INVALID" and rep["capture_ok"] is True


def test_final_snapshot_writes_once_after_the_stop_and_never_seals(tmp_path):
    """Task 7b (controller-added), C-3: one acquisition-time capture, fence-checked against EVERY seal."""
    st_ = s1_state(tmp_path, START, score_ready=True, final_snapshot=False)
    out = tmp_path / "s1_out"
    seals_before = {p.name: p.read_bytes() for p in (out / "seals").glob("*.json")}
    rep = ck.run_final_snapshot(tmp_path, st_["ledger"].path, now=lambda: st_["snapshot_at"])
    disk = read(out / "final_snapshot" / "report.json")
    assert disk == rep and rep["capture_ok"] is True and rep["fence_violations"] == []
    assert rep["trial_status"] == st_["stop"]["status"]
    assert rep["projection_sha256"] == c.sha256_file(out / "final_snapshot" / rep["attempt"] / "projection.json")
    assert sorted(x["file"] for x in rep["seals_checked"]) == sorted(seals_before)
    assert all(x["sha256"] == c.sha256_file(out / "seals" / x["file"]) for x in rep["seals_checked"])
    assert {p.name: p.read_bytes() for p in (out / "seals").glob("*.json")} == seals_before
    text = json.dumps(rep).lower()
    assert "price" not in text and "pnl" not in text
    before = (out / "final_snapshot" / "report.json").read_bytes()
    with pytest.raises(SystemExit, match="final snapshot"):
        ck.run_final_snapshot(tmp_path, st_["ledger"].path, now=lambda: st_["snapshot_at"] + timedelta(hours=1))
    assert (out / "final_snapshot" / "report.json").read_bytes() == before


def test_final_snapshot_records_a_backdated_row_and_score_is_aborted_invalid(tmp_path, monkeypatch):
    """Task 7b (controller-added), C-3: a row stored after the stop with a stored time <= a sealed close."""
    st_ = s1_state(tmp_path, START, score_ready=True, final_snapshot=False)
    lg = st_["ledger"]
    rid = lg.trade("S0", "BUY", 1, 100, "2026-10-26T19:00:00+00:00")       # <= the 2026-10-26 sealed close
    s1_sync_portfolio(lg, st_["rows"] + [
        {"id": rid, "symbol": "S0", "action": "BUY", "shares": 1.0, "price": 100.0,
         "ts": "2026-10-26T19:00:00+00:00"}])
    rep = ck.run_final_snapshot(tmp_path, lg.path, now=lambda: st_["snapshot_at"])
    assert any(f"row {rid} backdated" in v for v in rep["fence_violations"])
    assert not (tmp_path / "s1_out" / "aborted.json").exists()                  # recorded, scored later
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    # Input adjusted for the controller rulings (SCORE_ACK binds final_snapshot_sha256): the snapshot was taken after
    # s1_state's "score-ack" ("absent"), so the operator issues a fresh ACK binding the recorded report.
    s1_mailbox(tmp_path, "score-ack-2", r.score_token(tmp_path), st_["now"] - timedelta(hours=1))
    out = r.score(tmp_path, "score-ack-2")
    assert out["verdict"] == "ABORTED-INVALID" and out["nomination"] is False and "levels" not in out
    assert any("final snapshot" in x and "backdated" in x for x in out["reasons"])


def test_score_refuses_with_no_output_when_the_final_snapshot_is_missing(tmp_path, monkeypatch):
    """Task 7b (controller-added): the refusal happens before the reservation."""
    st_ = s1_state(tmp_path, START, score_ready=True, final_snapshot=False)
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    with pytest.raises(SystemExit, match="final snapshot"):
        r.score(tmp_path, "score-ack")
    assert not (tmp_path / "s1_out" / "score").exists()


def test_score_with_a_tampered_final_snapshot_projection_is_aborted_invalid(tmp_path, monkeypatch):
    """Task 7b (controller-added): the preserved projection must still hash to the recorded value."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    p = tmp_path / "s1_out" / "final_snapshot" / "attempt-01" / "projection.json"
    p.write_bytes(p.read_bytes() + b" ")
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    out = r.score(tmp_path, "score-ack")
    assert out["verdict"] == "ABORTED-INVALID" and any("final snapshot" in x for x in out["reasons"])


def test_full_synthetic_lifecycle_uses_the_real_opening_seal_and_final_snapshot(tmp_path, monkeypatch):
    """Task 7b (controller-added): s1_state now runs the opening checkpoint and the final snapshot for real."""
    st_ = s1_state(tmp_path, START, score_ready=True,
                   bar_fn=lambda s, d: {"date": d, "o": 100, "h": 100, "l": 85, "c": 90} if d == "2026-10-27"
                   else {"date": d, "o": 100, "h": 101, "l": 99, "c": 100})
    out = tmp_path / "s1_out"
    cap = out / "captures" / OPEN_DAY / "20261023T204500Z"
    assert (cap / "backup.sqlite3").exists() and read(cap / "meta.json")["ok"] is True
    assert read(out / "opening_receipt.json") == S1_RECEIPT
    assert read(out / "final_snapshot" / "report.json")["fence_violations"] == []
    assert read(out / "attest_start.json")["opening_seal_sha256"] == c.sha256_file(out / "seals" / f"{OPEN_DAY}.json")
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    rep = r.score(tmp_path, "score-ack")
    assert (rep["verdict"], rep["provenance"], rep["nomination"]) == ("SHADOW PASS", "VERIFIED", True)


def test_no_valid_seal_trial_can_take_its_final_snapshot(tmp_path, monkeypatch):
    """Task 7b (controller-added): NO-VALID-SEAL is a terminal trial state too (decision recorded in the report)."""
    st_ = s1_state(tmp_path, START, score_ready=True, lots=[], seal_days=[])
    assert read(tmp_path / "s1_out" / "final_snapshot" / "report.json")["trial_status"] == "NO-VALID-SEAL"
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    assert r.score(tmp_path, "score-ack")["verdict"] == "NO-VALID-SEAL"


# ---------------------------------------------------------------- CLI
def test_cli_takes_exactly_one_mode():
    """Task 7b (controller-added): `--scheduled`, `--opening --scheduled`, `--final-snapshot`; one per call."""
    t = "2026-10-23T20:45:00+00:00"
    assert ck.parse_mode(["--scheduled", t]) == ("scheduled", c.aware(t))
    assert ck.parse_mode(["--opening", "--scheduled", t]) == ("opening", c.aware(t))
    assert ck.parse_mode(["--final-snapshot"]) == ("final-snapshot", None)
    for bad in ([], ["--opening"], ["--final-snapshot", "--scheduled", t], ["--final-snapshot", "--opening"]):
        with pytest.raises(SystemExit):
            ck.parse_mode(bad)


# ---------------------------------------------------------------- Task 7b controller rulings (concerns 1-3)
def test_score_ack_binds_the_final_snapshot_report_and_an_edit_after_the_ack_is_refused(tmp_path, monkeypatch):
    """Task 7b (controller rulings), concern 1: SCORE_ACK binds final_snapshot_sha256."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    p = tmp_path / "s1_out" / "final_snapshot" / "report.json"
    assert f"final_snapshot_sha256={c.sha256_file(p)}" in r.score_token(tmp_path)
    p.write_text(json.dumps(dict(read(p), edited=True)), encoding="utf-8")
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    with pytest.raises(SystemExit, match="ack lacks the standalone line"):   # fix round 1 (M-3): the ACK binding
        r.score(tmp_path, "score-ack")
    assert not (tmp_path / "s1_out" / "score").exists()


def test_score_ack_final_snapshot_is_absent_when_none_exists(tmp_path):
    """Task 7b (controller rulings), concern 1: "absent" placeholder before the snapshot."""
    s1_state(tmp_path, START, score_ready=True, final_snapshot=False)
    assert "final_snapshot_sha256=absent" in r.score_token(tmp_path)


def _locked(monkeypatch):
    def locked(*a, **kw):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(s1_snapshot, "_backup", locked)


def test_failed_final_capture_is_preserved_and_a_later_run_succeeds(tmp_path, monkeypatch):
    """Task 7b (controller rulings), concern 2: a locked-DB failure, then a successful run -> report from the
    second attempt; the failed attempt stays preserved; a run after the success refuses."""
    st_ = s1_state(tmp_path, START, score_ready=True, final_snapshot=False)
    d = tmp_path / "s1_out" / "final_snapshot"
    _locked(monkeypatch)
    first = ck.run_final_snapshot(tmp_path, st_["ledger"].path, now=lambda: st_["snapshot_at"])
    assert first["capture_ok"] is False and first["attempt"] == "attempt-01"
    assert "locked" in read(d / "attempt-01" / "meta.json")["error"] and not (d / "report.json").exists()
    monkeypatch.undo()
    second = ck.run_final_snapshot(tmp_path, st_["ledger"].path,
                                   now=lambda: st_["snapshot_at"] + timedelta(hours=1))
    assert second["capture_ok"] is True and second["attempt"] == "attempt-02"
    assert read(d / "report.json") == second and (d / "attempt-01" / "meta.json").exists()
    before = (d / "report.json").read_bytes()
    with pytest.raises(SystemExit, match="final snapshot"):
        ck.run_final_snapshot(tmp_path, st_["ledger"].path, now=lambda: st_["snapshot_at"] + timedelta(hours=2))
    assert not (d / "attempt-03").exists() and (d / "report.json").read_bytes() == before


def test_backdated_row_after_a_failed_attempt_is_still_recorded_and_never_retried_away(tmp_path, monkeypatch):
    """Task 7b (controller rulings), concern 2: the successful capture records the violation; it is final."""
    st_ = s1_state(tmp_path, START, score_ready=True, final_snapshot=False)
    lg = st_["ledger"]
    _locked(monkeypatch)
    ck.run_final_snapshot(tmp_path, lg.path, now=lambda: st_["snapshot_at"])
    monkeypatch.undo()
    rid = lg.trade("S0", "BUY", 1, 100, "2026-10-26T19:00:00+00:00")
    rep = ck.run_final_snapshot(tmp_path, lg.path, now=lambda: st_["snapshot_at"] + timedelta(hours=1))
    assert rep["attempt"] == "attempt-02" and any(f"row {rid} backdated" in v for v in rep["fence_violations"])
    lg._x("DELETE FROM trades WHERE id=?", (rid,))                          # the row disappears again
    with pytest.raises(SystemExit, match="final snapshot"):
        ck.run_final_snapshot(tmp_path, lg.path, now=lambda: st_["snapshot_at"] + timedelta(hours=2))
    assert read(tmp_path / "s1_out" / "final_snapshot" / "report.json")["fence_violations"] == \
        rep["fence_violations"]


def _crash_in_seal_write(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("simulated crash while building the seal")
    monkeypatch.setattr(s1_seal, "fence", boom)


def test_opening_receipt_is_written_before_the_seal_and_attest_start_needs_both(tmp_path, ledger, monkeypatch):
    """Task 7b (controller rulings), concern 3: a crash after the receipt write leaves a receipt without a seal;
    attest_start refuses ("opening seal"); the next opening run seals and keeps the matching receipt."""
    opening_ready(tmp_path, ledger)
    out = tmp_path / "s1_out"
    _crash_in_seal_write(monkeypatch)
    with pytest.raises(RuntimeError):
        opening(tmp_path, ledger, minutes=45)
    monkeypatch.undo()
    assert read(out / "opening_receipt.json") == S1_RECEIPT and not (out / "seals" / f"{OPEN_DAY}.json").exists()
    kept = (out / "opening_receipt.json").read_bytes()
    with _Clock(START_DT - timedelta(days=2)):
        with pytest.raises(SystemExit, match="opening seal"):
            r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    assert not (out / "attest_start.json").exists()
    rep = opening(tmp_path, ledger, minutes=47)
    assert rep["seal"]["written"] is True and (out / "opening_receipt.json").read_bytes() == kept
    with _Clock(START_DT - timedelta(days=2)):
        assert r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)["receipt_sha256"] == \
            c.sha256_bytes(c.canonical(S1_RECEIPT))


def test_opening_run_refuses_when_a_stored_receipt_differs_from_its_receipt(tmp_path, ledger, monkeypatch):
    """Task 7b (controller rulings), concern 3: a leftover receipt is kept only if it matches; otherwise refuse."""
    opening_ready(tmp_path, ledger)
    out = tmp_path / "s1_out"
    other = dict(S1_RECEIPT, head="other")
    _crash_in_seal_write(monkeypatch)
    with pytest.raises(RuntimeError):
        opening(tmp_path, ledger, minutes=45, receipt=other)
    monkeypatch.undo()
    with pytest.raises(SystemExit, match="opening_receipt"):
        opening(tmp_path, ledger, minutes=47, receipt=S1_RECEIPT)
    assert not (out / "seals").exists() or not (out / "seals" / f"{OPEN_DAY}.json").exists()
    assert read(out / "opening_receipt.json") == other


# ---------------------------------------------------------------- Task 7b fix round 1 (review I-1, M-1, M-2)
def _backdated_final_attempt(tmp_path):
    """A final snapshot whose (successful) attempt-01 records a backdated row; returns (state, row id, report)."""
    st_ = s1_state(tmp_path, START, score_ready=True, final_snapshot=False)
    lg = st_["ledger"]
    rid = lg.trade("S0", "BUY", 1, 100, "2026-10-26T19:00:00+00:00")       # <= the 2026-10-26 sealed close
    s1_sync_portfolio(lg, st_["rows"] + [
        {"id": rid, "symbol": "S0", "action": "BUY", "shares": 1.0, "price": 100.0,
         "ts": "2026-10-26T19:00:00+00:00"}])
    rep = ck.run_final_snapshot(tmp_path, lg.path, now=lambda: st_["snapshot_at"])
    assert rep["attempt"] == "attempt-01" and any(f"row {rid} backdated" in v for v in rep["fence_violations"])
    return st_, rid, rep


def _fresh_score_ack(tmp_path, st_, ack_id):
    s1_mailbox(tmp_path, ack_id, r.score_token(tmp_path), st_["now"] - timedelta(hours=1))


def test_deleted_report_after_a_successful_attempt_refuses_a_new_attempt(tmp_path):
    """Task 7b fix round 1 (controller-added), review I-1: success is decided by the attempts, not by report.json.
    The reviewer's probe: backdated row in attempt-01, report.json deleted (the crash window), row removed, rerun."""
    st_, rid, _ = _backdated_final_attempt(tmp_path)
    d = tmp_path / "s1_out" / "final_snapshot"
    (d / "report.json").unlink()
    st_["ledger"]._x("DELETE FROM trades WHERE id=?", (rid,))
    with pytest.raises(SystemExit, match="final snapshot"):
        ck.run_final_snapshot(tmp_path, st_["ledger"].path, now=lambda: st_["snapshot_at"] + timedelta(hours=1))
    assert not (d / "attempt-02").exists() and not (d / "report.json").exists()


@pytest.mark.parametrize("breakage", ["missing", "unreadable"])
def test_score_is_aborted_invalid_when_the_report_is_gone_but_an_ok_attempt_exists(tmp_path, monkeypatch, breakage):
    """Task 7b fix round 1 (controller-added), review I-1: a missing/unreadable final_snapshot/report.json while a
    successful attempt exists is ABORTED-INVALID inside the attempt (not a pre-reserve refusal, not a pass)."""
    st_, _, _ = _backdated_final_attempt(tmp_path)
    p = tmp_path / "s1_out" / "final_snapshot" / "report.json"
    if breakage == "missing":
        p.unlink()
    else:
        p.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    _fresh_score_ack(tmp_path, st_, "score-ack-2")
    out = r.score(tmp_path, "score-ack-2")
    assert out["verdict"] == "ABORTED-INVALID" and out["nomination"] is False and "levels" not in out
    assert any("final snapshot" in x and "report" in x for x in out["reasons"])


def test_score_is_aborted_invalid_when_another_attempt_is_ok_too(tmp_path, monkeypatch):
    """Task 7b fix round 1 (controller-added), review I-1: a hand-made second ok attempt (not the one report.json
    names) makes the score ABORTED-INVALID."""
    import shutil
    st_ = s1_state(tmp_path, START, score_ready=True)
    d = tmp_path / "s1_out" / "final_snapshot"
    assert read(d / "report.json")["attempt"] == "attempt-01"
    shutil.copytree(d / "attempt-01", d / "attempt-02")
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    out = r.score(tmp_path, "score-ack")                           # report.json unchanged: the ACK still binds it
    assert out["verdict"] == "ABORTED-INVALID" and out["nomination"] is False
    assert any("final snapshot" in x and "attempt-02" in x for x in out["reasons"])


def test_opening_receipt_conflict_report_records_the_real_consistency_and_never_seals(tmp_path, ledger,
                                                                                       monkeypatch):
    """Task 7b fix round 1 (controller-added), review M-1: the capture taken before the "stored receipt differs"
    refusal is read, so its report shows the capture's real consistency and the reason "receipt conflict"."""
    opening_ready(tmp_path, ledger)
    out = tmp_path / "s1_out"
    _crash_in_seal_write(monkeypatch)
    with pytest.raises(RuntimeError):
        opening(tmp_path, ledger, minutes=45, receipt=dict(S1_RECEIPT, head="other"))
    monkeypatch.undo()
    with pytest.raises(SystemExit, match="opening_receipt"):
        opening(tmp_path, ledger, minutes=47, receipt=S1_RECEIPT)
    rep = read(out / "captures" / OPEN_DAY / "20261023T204700Z.report.json")
    assert rep["capture_ok"] is True and rep["consistent"] is True and rep["snapshot"] is not None
    assert "receipt conflict" in rep["refused"] and rep["seal"]["written"] is False
    assert not (out / "seals" / f"{OPEN_DAY}.json").exists()


def test_concurrent_opening_receipt_refusal_still_writes_the_capture_report(tmp_path, ledger, monkeypatch):
    """Task 7b fix round 1 (controller-added), review M-2: a differing receipt stored after the capture is read makes
    this run refuse, but the capture's .report.json is written (with the reason) first. Fix round 2 note: since the
    M-1 reorder the receipt lands before the early check, so this case covers the early-check (M-1) refusal path;
    the concurrent path is covered by test_receipt_stored_concurrently_after_the_early_check_is_reported."""
    opening_ready(tmp_path, ledger)
    out = tmp_path / "s1_out"
    real = ck._read_capture

    def racing(*a, **kw):
        proj = real(*a, **kw)
        (out / "opening_receipt.json").write_text(json.dumps(dict(S1_RECEIPT, head="other")), encoding="utf-8")
        return proj
    monkeypatch.setattr(ck, "_read_capture", racing)
    with pytest.raises(SystemExit, match="differs"):
        opening(tmp_path, ledger, minutes=45)
    rp = out / "captures" / OPEN_DAY / "20261023T204500Z.report.json"
    assert rp.exists()
    rep = read(rp)
    assert "receipt conflict" in rep["refused"] and rep["seal"]["written"] is False and rep["consistent"] is True
    assert not (out / "seals" / f"{OPEN_DAY}.json").exists()


def test_receipt_stored_concurrently_after_the_early_check_is_reported(tmp_path, ledger, monkeypatch):
    """Task 7b fix round 2 (controller-added, retrospective: written after the handler existed; proven by the
    t7b_fix2_mutant.txt run with the handler removed), review2 m-1 / M-2: a differing receipt stored by a concurrent
    run AFTER the early check, at the moment this run stores its own, raises ck._ReceiptConflict; the capture's
    .report.json is still written with the "(concurrent)" reason and no seal is written."""
    opening_ready(tmp_path, ledger)
    out = tmp_path / "s1_out"
    real = ck._store_opening_receipt

    def racing(p, receipt):
        assert not p.exists()                                      # the early check has already passed
        p.write_text(json.dumps(dict(S1_RECEIPT, head="other")), encoding="utf-8")
        return real(p, receipt)
    monkeypatch.setattr(ck, "_store_opening_receipt", racing)
    with pytest.raises(ck._ReceiptConflict, match="differs"):
        opening(tmp_path, ledger, minutes=45)
    rp = out / "captures" / OPEN_DAY / "20261023T204500Z.report.json"
    assert rp.exists()
    rep = read(rp)
    assert "(concurrent)" in rep["refused"] and rep["seal"]["written"] is False and rep["consistent"] is True
    assert not (out / "seals" / f"{OPEN_DAY}.json").exists()
