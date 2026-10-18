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
from conftest import S1_PROCESS, S1_RECEIPT, _Clock, _write_seal, s1_mailbox, s1_state, s1_sync_portfolio

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
    with _Clock(START_DT - timedelta(days=1)):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
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
    assert c.aware(s["decided_utc"]) == STOP_CLOSE + timedelta(minutes=45, seconds=30)
    assert s["bundle_sha256"] == c.bundle_sha256()
    assert set(s["seals"]) == {"seals/2026-10-23.json", "seals/2026-10-26.json", "seals/2026-10-27.json"}
    before = (out / "stop.json").read_bytes()
    with pytest.raises(FileExistsError):
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
    s1_mailbox(tmp_path, "score-ack-2", r.score_token(tmp_path), st_["now"] - timedelta(minutes=30))
    rep = r.score(tmp_path, "score-ack-2")
    assert rep["verdict"] == "ABORTED-INVALID" and any("stop" in x for x in rep["reasons"]), rep["reasons"]


def test_a2_no_valid_seal_is_terminal_persisted_and_never_rescued_by_a_late_seal(tmp_path, monkeypatch):
    """A2.1: NO-VALID-SEAL is persisted the same way; a seal file appearing afterwards (a 'rescue' seal for an
    eligible close) never produces a trial result: the score is not a PASS/FAIL and stop.json is unchanged."""
    st_ = s1_state(tmp_path, START, score_ready=True, lots=[], seal_days=[])
    out = tmp_path / "s1_out"
    s = read(out / "stop.json")
    assert s["status"] == "NO-VALID-SEAL" and s["stop_close"] is None and s["stop_seal"] is None
    before = (out / "stop.json").read_bytes()
    _write_seal(out, "2026-10-26", datetime(2026, 10, 26, 20, 0, tzinfo=UTC), st_["rows"], S1_RECEIPT,
                start=START_DT, opening_close=datetime(2026, 10, 23, 20, 0, tzinfo=UTC))
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    s1_mailbox(tmp_path, "score-ack-2", r.score_token(tmp_path), st_["now"] - timedelta(minutes=30))
    rep = r.score(tmp_path, "score-ack-2")
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
    assert rep["post_stop"] is True and rep["seal"]["written"] is False
    assert rep["stop"]["status"] == "STOPPED" and c.aware(rep["stop"]["stop_close"]) == STOP_CLOSE
    assert not (out / "seals" / "2026-10-28.json").exists()


def test_a2_a_persisted_invalidity_is_never_converted_into_a_valid_stop(tmp_path, monkeypatch):
    """A2.2: aborted.json after stop.json (e.g. a post-stop bundle mismatch) keeps the trial terminal-invalid: no
    stop attestation, no final plan, score ABORTED-INVALID."""
    st_, lg, rows = _live_stop(tmp_path)
    out = tmp_path / "s1_out"
    c.write_abort(out, {"reason": "bundle", "actual": (STOP_CLOSE + timedelta(hours=2)).isoformat()})
    with _Clock(STOP_CLOSE + timedelta(days=1)):
        with pytest.raises(SystemExit, match="ABORTED"):
            r.attest_stop(tmp_path, r.STOP_STATEMENT)
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
    else:
        _write_seal(out, "2026-10-22", datetime(2026, 10, 22, 20, 0, tzinfo=UTC), [], S1_RECEIPT)
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    s1_mailbox(tmp_path, "score-ack-2", r.score_token(tmp_path), st_["now"] - timedelta(minutes=30))
    rep = r.score(tmp_path, "score-ack-2")
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
    s1_mailbox(tmp_path, "score-ack-2", r.score_token(tmp_path), st_["now"] - timedelta(minutes=30))
    rep = r.score(tmp_path, "score-ack-2")
    assert rep["verdict"] == "SHADOW PASS" and rep["reasons"] == [], rep["reasons"]
