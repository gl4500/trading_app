import json
import sqlite3
import threading

import pytest
import s1_snapshot as s


def test_projection_is_mr_only_with_real_fields(ledger, tmp_path):
    ledger.trade("AAA", "BUY", 10, 50.0, "2026-10-15T14:30:00+00:00", reasoning="secret-ish text")
    ledger.trade("ZZZ", "BUY", 1, 1.0, "2026-10-15T14:31:00+00:00", agent_id=1)        # other agent
    ledger.set_portfolio("AAA", 10)
    m = s.take_snapshot(ledger.path, tmp_path / "cap")
    p = json.loads((tmp_path / "cap" / "projection.json").read_text(encoding="utf-8"))
    assert m["ok"] and [t["symbol"] for t in p["trades"]] == ["AAA"] and p["portfolios"] == {"AAA": 10.0}
    assert "secret-ish text" not in (tmp_path / "cap" / "projection.json").read_text(encoding="utf-8")
    assert len(p["trades"][0]["reasoning_sha256"]) == 64 and m["max_trade_id"] == p["trades"][-1]["id"]


def test_live_file_bytes_unchanged_and_refuses_existing_output(ledger, tmp_path):
    before = ledger.path.read_bytes()
    s.take_snapshot(ledger.path, tmp_path / "cap")
    assert ledger.path.read_bytes() == before
    with pytest.raises(FileExistsError):
        s.take_snapshot(ledger.path, tmp_path / "cap")


def test_missing_required_column_is_a_snapshot_error(tmp_path):
    db = tmp_path / "bad.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE agents (id INTEGER PRIMARY KEY, name TEXT)")
    con.execute("INSERT INTO agents VALUES (1,'MeanReversionAgent')")
    con.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, agent_id INT, symbol TEXT)")
    con.execute("CREATE TABLE portfolios (agent_id INT, symbol TEXT, shares REAL)")
    con.commit(); con.close()
    m = s.take_snapshot(db, tmp_path / "cap")
    assert m["ok"] is False and "column" in m["error"]
    assert not (tmp_path / "cap" / "projection.json").exists()


def test_locked_database_records_a_failed_capture_not_a_crash(ledger, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(s, "_backup", boom)
    m = s.take_snapshot(ledger.path, tmp_path / "cap")
    assert m["ok"] is False and "locked" in m["error"]
    assert not (tmp_path / "cap" / "projection.json").exists()


def test_malformed_ledger_timestamp_fails_the_capture(ledger, tmp_path):
    ledger.trade("AAA", "BUY", 1, 1.0, "15/10/2026")
    m = s.take_snapshot(ledger.path, tmp_path / "cap")
    assert m["ok"] is False and "timestamp" in m["error"]


def test_backup_during_concurrent_wal_writer_is_a_committed_state(ledger, tmp_path):
    stop = threading.Event()
    first = threading.Event()   # controller-ruled brief fix: wait for the first commit before snapshotting

    def writer():
        con = sqlite3.connect(ledger.path)
        i = 0
        while not stop.is_set() and i < 400:
            con.execute("INSERT INTO trades (agent_id, symbol, action, shares, price, timestamp, reasoning, pnl) "
                        "VALUES (?,?,?,?,?,?,?,0)", (ledger.agent_id, f"S{i%7}", "BUY", 1, 1.0,
                                                     "2026-10-15T14:30:00+00:00", "w"))
            con.commit(); first.set(); i += 1
        con.close()
    t = threading.Thread(target=writer); t.start()
    first.wait(5)
    m = s.take_snapshot(ledger.path, tmp_path / "cap")
    stop.set(); t.join()
    p = json.loads((tmp_path / "cap" / "projection.json").read_text(encoding="utf-8"))
    ids = [r["id"] for r in p["trades"]]
    assert m["ok"] and ids == sorted(ids)
    assert ids
    assert ids == list(range(ids[0], ids[0] + len(ids)))   # no holes
