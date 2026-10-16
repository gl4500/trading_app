"""Task 8b (controller-added): bridge classification + bridge hash in every post-START seal (design §11 "Opening seal
-> START bridge" / "Bootstrap", §6 row fences, example 19). All synthetic: tmp_path ledgers and mailbox, fixed
clocks; no live DB, network or .env."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import s1_checkpoint as ck
import s1_common as c
import s1_run as r
import s1_seal as z
from conftest import S1_PROCESS, S1_RECEIPT, _Clock, s1_mailbox, s1_state, s1_sync_portfolio

UTC = timezone.utc
START = "2026-10-27T13:30:00+00:00"                     # Tue 09:30 EDT
START_DT = datetime(2026, 10, 27, 13, 30, tzinfo=UTC)
OPEN_CLOSE = datetime(2026, 10, 26, 20, 0, tzinfo=UTC)  # Mon 16:00 EDT (opening seal at 16:45)
BRIDGE = (("NEWT", "BUY", 15, 33.17, "2026-10-27T00:00:00+00:00"),   # 20:00 ET the evening before START
          ("CI", "SELL", 4, 51.23, "2026-10-27T00:00:00Z"))          # same instant, other spelling


def row(i, ts, shares=10.0, sym="A", act="BUY"):
    return {"id": i, "symbol": sym, "action": act, "shares": shares, "price": 50.0, "timestamp": ts, "ts": ts,
            "reasoning_sha256": "0" * 64}


def read(p):
    return json.loads(p.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ the pure helper
def test_bridge_record_classifies_at_the_start_boundary():
    """Task 8b (controller-added): ts == START is cohort-era; START - 1 us is bridge; sorted ids."""
    just_before = (START_DT - timedelta(microseconds=1)).isoformat()
    rows = [row(3, START), row(1, "2026-10-20T15:00:00+00:00"), row(2, just_before),
            row(4, "2026-10-28T15:00:00+00:00")]
    rec = z.bridge_record(rows, START_DT, OPEN_CLOSE)
    assert rec["bridge_row_ids"] == [1, 2]
    assert rec["cohort_era_row_ids"] == [3, 4]
    assert isinstance(rec["bridge_sha256"], str) and len(rec["bridge_sha256"]) == 64


def test_bridge_hash_is_stable_across_timestamp_spellings():
    """Task 8b (controller-added): Z / +00:00 spellings of one instant give the same bridge hash; row order in the
    input does not matter; cohort-era rows do not enter the hash."""
    a = [row(1, "2026-10-20T15:00:00+00:00"), row(2, "2026-10-27T00:00:00+00:00", sym="B")]
    b = [row(2, "2026-10-27T00:00:00Z", sym="B"), row(1, "2026-10-20T15:00:00Z")]
    ha = z.bridge_record(a, START_DT, OPEN_CLOSE)["bridge_sha256"]
    assert ha == z.bridge_record(b, START_DT, OPEN_CLOSE)["bridge_sha256"]
    assert ha == z.bridge_record(a + [row(9, "2026-10-28T15:00:00+00:00")], START_DT, OPEN_CLOSE)["bridge_sha256"]


def test_bridge_hash_changes_when_a_bridge_rows_shares_change():
    """Task 8b (controller-added): a changed bridge row (shares) changes the bridge hash."""
    a = [row(1, "2026-10-20T15:00:00+00:00"), row(2, "2026-10-27T00:00:00+00:00", shares=15.0)]
    b = [row(1, "2026-10-20T15:00:00+00:00"), row(2, "2026-10-27T00:00:00+00:00", shares=16.0)]
    assert z.bridge_record(a, START_DT, OPEN_CLOSE)["bridge_sha256"] != \
        z.bridge_record(b, START_DT, OPEN_CLOSE)["bridge_sha256"]


# ------------------------------------------------------------------ example 19 through the real checkpoint
def _checkpoint(root, ledger, close, minutes=45):
    sch = close + timedelta(minutes=minutes)
    act = sch + timedelta(seconds=30)
    with _Clock(act):
        return ck.run_checkpoint(root, ledger.path, sch, lambda: S1_RECEIPT, lambda: dict(S1_PROCESS),
                                 root / "crash.log", now=lambda: act)


def _example19(tmp_path):
    """Opening seal 16:45, then a BUY of a NEW ticker + a SELL of an audited carry-in lot stored at 20:00, START
    09:30 next day; prereg; one cohort BUY on the START session."""
    st_ = s1_state(tmp_path, START, bridge=BRIDGE)
    with _Clock(START_DT - timedelta(days=1)):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    lg = st_["ledger"]
    ts = "2026-10-27T15:00:00+00:00"
    rid = lg.trade("A", "BUY", 10, 50, ts)
    rows = st_["rows"] + [{"id": rid, "symbol": "A", "action": "BUY", "shares": 10.0, "price": 50.0,
                           "timestamp": ts, "ts": ts}]
    s1_sync_portfolio(lg, rows)
    return st_, lg, rows, rid


def test_example19_first_post_start_seal_records_the_bridge(tmp_path):
    """Task 8b (controller-added), design example 19: both 20:00 rows are PRE-START bridge rows in the first
    post-START seal's bridge record, neither is in the cohort; the opening seal carries no bridge record."""
    st_, lg, rows, rid = _example19(tmp_path)
    bridge_ids = [t["id"] for t in st_["rows"] if t["symbol"] == "NEWT" or t["action"] == "SELL"]
    assert len(bridge_ids) == 2
    rep = _checkpoint(tmp_path, lg, datetime(2026, 10, 27, 20, 0, tzinfo=UTC))
    assert rep["seal"]["written"] and rep["fence_violations"] == [], rep
    out = tmp_path / "s1_out"
    seal = read(out / "seals" / "2026-10-27.json")
    br = seal["bridge"]
    assert set(bridge_ids) <= set(br["bridge_row_ids"]) and rid not in br["bridge_row_ids"]
    assert br["cohort_era_row_ids"] == [rid]
    assert br["bridge_sha256"] == z.bridge_record(seal["trades"], START_DT, OPEN_CLOSE)["bridge_sha256"]
    assert not {t["id"] for t in z.cohort(seal["trades"], START_DT, c.aware(seal["close"]))} & set(bridge_ids)
    assert "bridge" not in read(out / "seals" / "2026-10-26.json")          # the opening seal precedes START


def test_bridge_row_edited_after_first_post_start_seal_is_a_checkpoint_violation(tmp_path):
    """Task 8b (controller-added): a bridge row changed after the first post-START seal -> the next checkpoint
    records a bridge violation, writes no seal and records ABORTED-INVALID."""
    st_, lg, rows, rid = _example19(tmp_path)
    assert _checkpoint(tmp_path, lg, datetime(2026, 10, 27, 20, 0, tzinfo=UTC))["seal"]["written"]
    newt = next(t for t in rows if t["symbol"] == "NEWT")
    con = sqlite3.connect(lg.path)
    con.execute("UPDATE trades SET shares=16 WHERE id=?", (newt["id"],))
    con.commit()
    con.close()
    s1_sync_portfolio(lg, [dict(t, shares=16.0) if t["id"] == newt["id"] else t for t in rows])
    rep = _checkpoint(tmp_path, lg, datetime(2026, 10, 28, 20, 0, tzinfo=UTC))
    assert any("bridge" in v for v in rep["fence_violations"]), rep["fence_violations"]
    assert rep["seal"]["written"] is False and rep["stop"]["status"] == "ABORTED-INVALID"
    out = tmp_path / "s1_out"
    assert not (out / "seals" / "2026-10-28.json").exists() and (out / "aborted.json").exists()


# ------------------------------------------------------------------ score
def _first_post_start_seal(out):
    return min((p for p in (out / "seals").glob("*.json") if c.aware(read(p)["close"]) >= START_DT),
               key=lambda p: c.aware(read(p)["close"]))


def test_score_carries_the_bridge_hash_and_count(tmp_path, monkeypatch):
    """Task 8b (controller-added): a clean trial scores, and the report carries the first post-START seal's
    bridge hash recomputed from the frozen final ledger, plus the bridge row count (counts and hashes only)."""
    st_ = s1_state(tmp_path, START, score_ready=True, bridge=BRIDGE)
    first = read(_first_post_start_seal(tmp_path / "s1_out"))
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    rep = r.score(tmp_path, "score-ack")
    assert rep["outcome"] == "SCORED" and rep["reasons"] == [], rep["reasons"]
    bp = rep["bridge_provenance"]
    assert bp["bridge_sha256"] == first["bridge"]["bridge_sha256"]
    assert bp["bridge_row_count"] == 3                                     # the carry-in BUY + the two 20:00 rows


def test_bridge_row_edited_before_the_final_snapshot_is_aborted_invalid(tmp_path, monkeypatch):
    """Task 8b (controller-added): a bridge row changed after the seals -> run_final_snapshot records a bridge
    fence violation and the score is ABORTED-INVALID with a reason naming the bridge."""
    st_ = s1_state(tmp_path, START, score_ready=True, bridge=BRIDGE, final_snapshot=False)
    lg = st_["ledger"]
    newt = next(t for t in st_["rows"] if t["symbol"] == "NEWT")
    con = sqlite3.connect(lg.path)
    con.execute("UPDATE trades SET shares=16 WHERE id=?", (newt["id"],))
    con.commit()
    con.close()
    s1_sync_portfolio(lg, [dict(t, shares=16.0) if t["id"] == newt["id"] else t for t in st_["rows"]])
    snap = ck.run_final_snapshot(tmp_path, lg.path, now=lambda: st_["snapshot_at"])
    assert any("bridge" in v for v in snap["fence_violations"]), snap["fence_violations"]
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    s1_mailbox(tmp_path, "score-ack-2", r.score_token(tmp_path), st_["now"] - timedelta(hours=1))
    rep = r.score(tmp_path, "score-ack-2")
    assert rep["verdict"] == "ABORTED-INVALID" and any("bridge" in x for x in rep["reasons"]), rep["reasons"]


def _edit_first_seal(tmp_path, fn):
    p = _first_post_start_seal(tmp_path / "s1_out")
    s = read(p)
    fn(s)
    p.write_text(json.dumps(s), encoding="utf-8")


def test_score_with_a_seal_missing_its_bridge_record_is_aborted_invalid(tmp_path, monkeypatch):
    """Task 8b (controller-added): a post-START seal without `bridge` -> ABORTED-INVALID naming the bridge."""
    st_ = s1_state(tmp_path, START, score_ready=True, bridge=BRIDGE)
    _edit_first_seal(tmp_path, lambda s: s.pop("bridge"))
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    rep = r.score(tmp_path, "score-ack")
    assert rep["verdict"] == "ABORTED-INVALID" and any("bridge" in x for x in rep["reasons"]), rep["reasons"]


def test_score_with_a_bridge_hash_differing_from_the_final_ledger_is_aborted_invalid(tmp_path, monkeypatch):
    """Task 8b (controller-added): the first post-START seal's bridge hash must equal the one recomputed from the
    frozen final ledger."""
    st_ = s1_state(tmp_path, START, score_ready=True, bridge=BRIDGE)
    _edit_first_seal(tmp_path, lambda s: s["bridge"].update(bridge_sha256="0" * 64))
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    rep = r.score(tmp_path, "score-ack")
    assert rep["verdict"] == "ABORTED-INVALID" and any("bridge" in x for x in rep["reasons"]), rep["reasons"]


# ------------------------------------------------------------------ Task 9 test-hardening (from the Task 8b review)
def test_bridge_row_edited_then_scored_is_aborted_invalid(tmp_path, monkeypatch):
    """Task 9 hardening (a), retrospective (written after the code exists): the bridge-row edit of
    test_bridge_row_edited_after_first_post_start_seal_is_a_checkpoint_violation, carried on through the final
    snapshot and the score -> the score is ABORTED-INVALID, its reasons naming the checkpoint abort."""
    st_, lg, rows, rid = _example19(tmp_path)
    assert _checkpoint(tmp_path, lg, datetime(2026, 10, 27, 20, 0, tzinfo=UTC))["seal"]["written"]
    newt = next(t for t in rows if t["symbol"] == "NEWT")
    con = sqlite3.connect(lg.path)
    con.execute("UPDATE trades SET shares=16 WHERE id=?", (newt["id"],))
    con.commit()
    con.close()
    s1_sync_portfolio(lg, [dict(t, shares=16.0) if t["id"] == newt["id"] else t for t in rows])
    rep = _checkpoint(tmp_path, lg, datetime(2026, 10, 28, 20, 0, tzinfo=UTC))
    assert rep["stop"]["status"] == "ABORTED-INVALID", rep["stop"]
    snap_at = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
    ck.run_final_snapshot(tmp_path, lg.path, now=lambda: snap_at)
    now = snap_at + timedelta(hours=2)
    monkeypatch.setattr(c, "now_utc", lambda: now)
    s1_mailbox(tmp_path, "score-ack-a", r.score_token(tmp_path), now - timedelta(hours=1))
    sc = r.score(tmp_path, "score-ack-a")
    assert sc["verdict"] == "ABORTED-INVALID" and sc["nomination"] is False, sc
    assert any("ABORTED-INVALID" in x and "bridge" in x for x in sc["reasons"]), sc["reasons"]


def test_pre_start_row_first_observed_after_first_post_start_seal_is_backdating_and_bridge(tmp_path):
    """Task 9 hardening (b), retrospective: a row whose stored time is before START (after the opening close) that
    first appears after the first post-START seal -> the next checkpoint records violations naming BOTH backdating
    and the bridge, writes no seal and records ABORTED-INVALID with both reasons."""
    st_, lg, rows, rid = _example19(tmp_path)
    assert _checkpoint(tmp_path, lg, datetime(2026, 10, 27, 20, 0, tzinfo=UTC))["seal"]["written"]
    ts = "2026-10-27T01:00:00Z"                                          # 21:00 ET the evening before START
    late = lg.trade("LATE", "BUY", 5, 20.0, ts)
    s1_sync_portfolio(lg, rows + [{"id": late, "symbol": "LATE", "action": "BUY", "shares": 5.0, "price": 20.0,
                                   "timestamp": ts, "ts": ts}])
    rep = _checkpoint(tmp_path, lg, datetime(2026, 10, 28, 20, 0, tzinfo=UTC))
    v = rep["fence_violations"]
    assert any("backdated" in x and str(late) in x for x in v), v
    assert any("bridge" in x for x in v), v
    assert rep["seal"]["written"] is False and rep["stop"]["status"] == "ABORTED-INVALID"
    out = tmp_path / "s1_out"
    assert not (out / "seals" / "2026-10-28.json").exists()
    reason = read(out / "aborted.json")["reason"]
    assert any("backdated" in x for x in reason) and any("bridge" in x for x in reason), reason


def test_opening_close_error_is_a_recorded_refusal_not_a_crash(tmp_path):
    """Task 9 hardening (c), product fix (test written first, behavioural RED in s1_evidence/t9_hardening_red.txt):
    when the bridge's opening close cannot be placed (prereg calendar has no session before START), run_checkpoint
    records the refusal in the capture report, writes no seal and returns; it does not crash before the report."""
    st_, lg, rows, rid = _example19(tmp_path)
    out = tmp_path / "s1_out"
    pp = out / "prereg.json"
    pr = read(pp)
    pr["calendar"] = [d for d in pr["calendar"] if d["date"] >= "2026-10-27"]
    pp.write_text(json.dumps(pr), encoding="utf-8")
    rep = _checkpoint(tmp_path, lg, datetime(2026, 10, 27, 20, 0, tzinfo=UTC))
    assert "no calendar session before START" in str(rep.get("refused")), rep
    assert rep["seal"]["written"] is False
    assert not (out / "seals" / "2026-10-27.json").exists()
    reports = list((out / "captures" / "2026-10-27").glob("*.report.json"))
    assert len(reports) == 1 and "no calendar session before START" in str(read(reports[0]).get("refused"))


def test_score_with_a_bridge_record_not_matching_its_rows_is_aborted_invalid(tmp_path, monkeypatch):
    """Retrospective (Task 9 mutant survivor "score skips _bridge_problems"): a post-START seal whose bridge record
    lists the wrong rows (hash left intact, so the hash comparisons all agree) -> ABORTED-INVALID naming it."""
    st_ = s1_state(tmp_path, START, score_ready=True, bridge=BRIDGE)
    _edit_first_seal(tmp_path, lambda s: s["bridge"].update(bridge_row_ids=s["bridge"]["bridge_row_ids"][1:]))
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    rep = r.score(tmp_path, "score-ack")
    assert rep["verdict"] == "ABORTED-INVALID", rep["reasons"]
    assert any("bridge record does not match its rows" in x for x in rep["reasons"]), rep["reasons"]
