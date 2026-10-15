import ast
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import s1_checkpoint as k
from test_s1_seal import CAL

UTC = timezone.utc
START = datetime(2026, 10, 14, 13, 30, tzinfo=UTC)
REC = {"head": "h", "dirty": [], "files": {"a.py": "1"}, "config": {}, "versions": {}}


def make_prereg(root, receipt=REC):
    (root / "s1_out").mkdir(parents=True, exist_ok=True)
    (root / "s1_out" / "prereg.json").write_text(json.dumps({"start": START.isoformat(), "calendar": CAL,
                                                             "receipt": receipt}), encoding="utf-8")


def run(root, ledger, minutes=45, receipt=REC, pid=1, log=None, proc=None, delay=30):
    sch = datetime(2026, 10, 15, 20, 0, tzinfo=UTC).timestamp() + minutes * 60
    p = {"pid": pid, "process_start": "2026-10-12T23:17:25"} if proc is None else proc
    return k.run_checkpoint(root, ledger.path, datetime.fromtimestamp(sch, UTC), lambda: receipt,
                            lambda: p, log or root / "crash.log",
                            now=lambda: datetime.fromtimestamp(sch + delay, UTC))


def test_counts_only_report_and_seal(tmp_path, ledger):
    make_prereg(tmp_path)
    ledger.trade("A", "BUY", 10, 50, "2026-10-14T15:00:00+00:00"); ledger.set_portfolio("A", 10)
    rep = run(tmp_path, ledger)
    assert rep["consistent"] and rep["entries"] == 1 and rep["sold"] == 0 and rep["receipt_match"]
    assert set(rep) <= {"close", "scheduled", "actual", "capture_ok", "consistent", "fence_violations",
                        "receipt_match", "pid", "process_start", "restart_gaps", "entries", "sold", "stop",
                        "exclusions", "market_coverage",
                        # controller-ruled additions (Task 5 fix round 1, M3 / m2):
                        "writeoffs", "process_starts", "snapshot", "seal", "late"}
    assert (tmp_path / "s1_out" / "seals" / "2026-10-15.json").exists()
    assert "price" not in json.dumps(rep) and "pnl" not in json.dumps(rep).lower()


def test_restart_recorded_and_source_change_invalidates(tmp_path, ledger):               # example 10
    make_prereg(tmp_path)
    (tmp_path / "crash.log").write_text("2026-10-15 08:00:00 [PROCESS START] pid=2\n")
    rep = run(tmp_path, ledger, pid=2)
    assert rep["receipt_match"] and rep["restart_gaps"] == []
    bad = dict(REC, files={"a.py": "2"})
    rep = run(tmp_path, ledger, minutes=47, receipt=bad, pid=2)
    assert rep["receipt_match"] is False and rep["stop"]["status"] == "ABORTED-INVALID"


def test_checkpoint_cannot_reach_economics_or_prices(tmp_path, ledger, monkeypatch):      # example 17
    src = Path(k.__file__).read_text(encoding="utf-8")
    imported = {n.names[0].name for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Import)} | \
               {n.module for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)}
    assert not imported & {"s1_run", "s1_collect", "httpx", "e1_fetch"}
    import s1_common
    sim = s1_common.sim()
    for name in ("simulate_lot", "lot_economics", "baseline_economics", "compare", "paired_bootstrap", "verdict"):
        monkeypatch.setattr(sim, name, lambda *a, **kw: pytest.fail("economics reached from checkpoint"))
    make_prereg(tmp_path)
    ledger.trade("A", "BUY", 10, 50, "2026-10-14T15:00:00+00:00"); ledger.set_portfolio("A", 10)
    run(tmp_path, ledger)


def test_inconsistent_capture_does_not_seal_and_is_preserved(tmp_path, ledger):
    make_prereg(tmp_path)
    ledger.trade("A", "BUY", 10, 50, "2026-10-14T15:00:00+00:00")                       # portfolio not yet upserted
    rep = run(tmp_path, ledger)
    assert rep["consistent"] is False and not (tmp_path / "s1_out" / "seals" / "2026-10-15.json").exists()
    assert list((tmp_path / "s1_out" / "captures" / "2026-10-15").iterdir())


def test_corrupt_row_is_a_failed_capture_not_a_crash(tmp_path, ledger):
    """Added with the interface update: BookError from the books is recorded, not raised."""
    make_prereg(tmp_path)
    ledger.trade("A", "BUY", 10, 50, "2026-10-14T15:00:00+00:00"); ledger.set_portfolio("A", 10)
    ledger.trade("A", "HOLD", 1, 50, "2026-10-14T16:00:00+00:00")                       # unknown action
    rep = run(tmp_path, ledger)
    assert rep["capture_ok"] is False and rep["consistent"] is False and "error" not in rep
    metas = list((tmp_path / "s1_out" / "captures" / "2026-10-15").glob("*/meta.json"))
    assert metas and "BookError" in json.loads(metas[0].read_text())["error"]
    assert not (tmp_path / "s1_out" / "seals" / "2026-10-15.json").exists()


def test_pid_change_without_start_line_reported_and_prefix_checked(tmp_path, ledger):
    """Added with the interface update: previous record size feeds restart_record; pid change is a gap."""
    make_prereg(tmp_path)
    run(tmp_path, ledger, pid=1)
    rep = run(tmp_path, ledger, minutes=47, pid=9)
    assert any("pid 1 -> 9" in g for g in rep["restart_gaps"])


# ---- Task 5 fix round 1 (controller rulings C1, C2, C3/M1, M3, D1/I3, m1, m2) ----
SEAL = lambda root: root / "s1_out" / "seals" / "2026-10-15.json"
ABORT = lambda root: root / "s1_out" / "aborted.json"


def _good(tmp_path, ledger):
    make_prereg(tmp_path)
    ledger.trade("A", "BUY", 10, 50, "2026-10-14T15:00:00+00:00"); ledger.set_portfolio("A", 10)


def test_abort_survives_receipt_revert(tmp_path, ledger):
    """Retrospective (Task 5 review fix round 1), C1: change-then-revert of the receipt stays ABORTED."""
    _good(tmp_path, ledger)
    rep = run(tmp_path, ledger, minutes=47, receipt=dict(REC, head="x"))
    assert rep["stop"]["status"] == "ABORTED-INVALID" and ABORT(tmp_path).exists()
    first = json.loads(ABORT(tmp_path).read_text())
    assert {"reason", "close", "scheduled", "actual", "projection_sha256", "receipt_sha256"} <= set(first)
    rep = run(tmp_path, ledger, minutes=49)                                   # receipt back to the registered one
    assert rep["receipt_match"] and rep["stop"]["status"] == "ABORTED-INVALID"
    assert json.loads(ABORT(tmp_path).read_text()) == first                  # exclusive: first abort is kept
    assert not SEAL(tmp_path).exists()                                        # nothing seals after an abort


def test_abort_after_fence_violation_survives_clean_and_failed_runs(tmp_path, ledger):
    """Retrospective (Task 5 review fix round 1), C1: fence violation, then clean run, then a failed capture."""
    _good(tmp_path, ledger)
    run(tmp_path, ledger, minutes=45)
    assert SEAL(tmp_path).exists()
    ledger._x("DELETE FROM trades WHERE id=1", ())                            # a sealed row disappears
    ledger._x("DELETE FROM portfolios", ())
    rep = run(tmp_path, ledger, minutes=47)
    assert rep["fence_violations"] and rep["stop"]["status"] == "ABORTED-INVALID"
    rep = run(tmp_path, ledger, minutes=49)
    assert rep["stop"]["status"] == "ABORTED-INVALID"
    bad = tmp_path / "nodb.sqlite3"
    rep = k.run_checkpoint(tmp_path, bad, datetime(2026, 10, 15, 20, 51, tzinfo=UTC), lambda: REC,
                           lambda: {"pid": 1}, tmp_path / "crash.log",
                           now=lambda: datetime(2026, 10, 15, 20, 51, 30, tzinfo=UTC))
    assert rep["capture_ok"] is False and rep["stop"]["status"] == "ABORTED-INVALID"


def test_backdated_row_later_deleted_stays_aborted(tmp_path, ledger):
    """Retrospective (Task 5 review fix round 1), C1."""
    _good(tmp_path, ledger)
    run(tmp_path, ledger, minutes=45)
    rid = ledger.trade("B", "BUY", 1, 10, "2026-10-15T19:00:00+00:00")      # stored after the seal, dated <= close
    ledger.set_portfolio("B", 1)
    rep = run(tmp_path, ledger, minutes=47)
    assert any("backdated" in v for v in rep["fence_violations"]) and rep["stop"]["status"] == "ABORTED-INVALID"
    ledger._x("DELETE FROM trades WHERE id=?", (rid,)); ledger.drop_portfolio("B")
    rep = run(tmp_path, ledger, minutes=49)
    assert rep["fence_violations"] == [] and rep["stop"]["status"] == "ABORTED-INVALID"


@pytest.mark.parametrize("bad", [{}, {"error": "OSError"}])
def test_pidless_process_never_crashes_first_or_later(tmp_path, ledger, bad):
    """Retrospective (Task 5 review fix round 1), C2."""
    _good(tmp_path, ledger)
    rep = run(tmp_path, ledger, minutes=45, proc=bad)
    assert any("process not observed" in g for g in rep["restart_gaps"]) or rep["restart_gaps"] == []
    rep = run(tmp_path, ledger, minutes=47, proc=bad)
    assert any("process not observed" in g for g in rep["restart_gaps"])
    rep = run(tmp_path, ledger, minutes=49, proc={"pid": 5, "process_start": "s"})     # recovers afterwards
    assert rep["pid"] == 5


def test_pidless_after_good_observation_is_a_gap_with_reason(tmp_path, ledger):
    """Retrospective (Task 5 review fix round 1), C2."""
    _good(tmp_path, ledger)
    run(tmp_path, ledger, minutes=45, pid=1)
    rep = run(tmp_path, ledger, minutes=47, proc={"error": "x"})
    assert any("process not observed (x)" in g for g in rep["restart_gaps"])
    rep = run(tmp_path, ledger, minutes=49, proc={})
    assert any("process not observed (nothing listening)" in g for g in rep["restart_gaps"])


def test_real_restart_on_second_run_observed_and_unlogged_pid_change_is_gap(tmp_path, ledger):
    """Retrospective (Task 5 review fix round 1), C2 / Example 10 (non-vacuous: needs a PREVIOUS observation)."""
    _good(tmp_path, ledger)
    log = tmp_path / "crash.log"
    log.write_text("2026-10-15 08:00:00 [PROCESS START] pid=1\n")
    run(tmp_path, ledger, minutes=45, pid=1)
    log.write_text(log.read_text() + "2026-10-15 20:46:00 [PROCESS START] pid=2\n")
    rep = run(tmp_path, ledger, minutes=47, pid=2)
    assert rep["restart_gaps"] == [] and rep["process_starts"]["observed"] == 1
    assert rep["process_starts"]["latest"]["pid"] == 2
    rep = run(tmp_path, ledger, minutes=49, pid=3)                                   # no PROCESS START line for 3
    assert any("pid 2 -> 3" in g for g in rep["restart_gaps"]) and rep["process_starts"]["observed"] == 0


def test_receipt_mismatch_capture_does_not_seal_and_seal_carries_receipt(tmp_path, ledger):
    """Retrospective (Task 5 review fix round 1), C3/M1/M3."""
    _good(tmp_path, ledger)
    rep = run(tmp_path, ledger, minutes=45, receipt=dict(REC, head="x"))
    assert not SEAL(tmp_path).exists() and rep["seal"] == {"written": False, "sha256": None}
    ABORT(tmp_path).unlink()                                                  # fresh trial for the positive half
    rep = run(tmp_path, ledger, minutes=47)
    seal = json.loads(SEAL(tmp_path).read_text())
    import s1_common
    assert seal["receipt_match"] is True and seal["receipt_sha256"] == s1_common.sha256_bytes(s1_common.canonical(REC))
    assert rep["seal"]["written"] is True and rep["seal"]["sha256"] == s1_common.sha256_file(SEAL(tmp_path))
    assert rep["snapshot"] and len(rep["snapshot"]) == 64


def test_writeoff_audit_in_report_has_quantities_only(tmp_path, ledger):
    """Retrospective (Task 5 review fix round 1), M3."""
    _good(tmp_path, ledger)
    ledger.trade("A", "SELL", 9.9995, 51, "2026-10-14T16:00:00+00:00"); ledger.set_portfolio("A", 0)
    rep = run(tmp_path, ledger)
    assert [set(w) for w in rep["writeoffs"]] == [{"id", "symbol", "qty"}]
    assert rep["writeoffs"][0]["symbol"] == "A"


def test_economics_and_price_fetch_unreachable_with_sells(tmp_path, ledger, monkeypatch):
    """Retrospective (Task 5 review fix round 1), D1/I3: a ledger WITH BUY+SELL so the FIFO runs. The E1 FIFO
    allocator baseline_lots IS allowed (design section 8 needs the economic-FIFO sold count); simulation,
    economics, comparison, verdict, policy selection and the price fetcher are spied and must never be called."""
    import s1_common
    sim = s1_common.sim()
    for name in ("simulate_lot", "lot_economics", "baseline_economics", "compare", "paired_bootstrap", "verdict",
                 "select_policy"):
        if hasattr(sim, name):
            monkeypatch.setattr(sim, name, lambda *a, **kw: pytest.fail("economics reached from checkpoint"))
    monkeypatch.setattr(s1_common, "fetch", lambda *a, **kw: pytest.fail("price fetch reached from checkpoint"))
    make_prereg(tmp_path)
    ledger.trade("A", "BUY", 10, 50, "2026-10-14T15:00:00+00:00")
    ledger.trade("A", "SELL", 10, 55, "2026-10-14T16:00:00+00:00"); ledger.set_portfolio("A", 0)
    rep = run(tmp_path, ledger)
    assert rep["entries"] == 1 and rep["sold"] == 1


def test_rerun_of_captured_slot_is_recorded_and_refused(tmp_path, ledger):
    """Retrospective (Task 5 review fix round 1), m1."""
    _good(tmp_path, ledger)
    run(tmp_path, ledger, minutes=45)
    before = SEAL(tmp_path).read_bytes()
    with pytest.raises(SystemExit, match="slot already captured"):
        run(tmp_path, ledger, minutes=45)
    lines = (tmp_path / "s1_out" / "reruns.jsonl").read_text().splitlines()
    assert len(lines) == 1 and "scheduled" in json.loads(lines[0])
    assert SEAL(tmp_path).read_bytes() == before


def test_late_capture_flagged(tmp_path, ledger):
    """Retrospective (Task 5 review fix round 1), m2."""
    _good(tmp_path, ledger)
    assert run(tmp_path, ledger, minutes=45, delay=30)["late"] is False
    rep = run(tmp_path, ledger, minutes=47, delay=11 * 60)
    assert rep["late"] is True


def test_pid_change_across_a_pidless_run_without_start_line_is_gap(tmp_path, ledger):
    """Retrospective (Task 5 review fix round 2), N1: pid 2 -> {} -> pid 77, no new PROCESS START line."""
    _good(tmp_path, ledger)
    run(tmp_path, ledger, minutes=45, pid=2)
    run(tmp_path, ledger, minutes=47, proc={})
    rep = run(tmp_path, ledger, minutes=49, pid=77)
    assert any("pid 2 -> 77" in g for g in rep["restart_gaps"])


def test_pid_change_across_a_pidless_run_with_start_line_is_observed(tmp_path, ledger):
    """Retrospective (Task 5 review fix round 2), N1: same, but a PROCESS START pid=77 line explains it."""
    _good(tmp_path, ledger)
    log = tmp_path / "crash.log"
    log.write_text("2026-10-15 08:00:00 [PROCESS START] pid=2\n")
    run(tmp_path, ledger, minutes=45, pid=2)
    run(tmp_path, ledger, minutes=47, proc={})
    log.write_text(log.read_text() + "2026-10-15 20:48:00 [PROCESS START] pid=77\n")
    rep = run(tmp_path, ledger, minutes=49, pid=77)
    assert not any("pid 2 -> 77" in g for g in rep["restart_gaps"])
    assert rep["process_starts"]["observed"] == 1 and rep["process_starts"]["latest"]["pid"] == 77


def test_first_run_pidless_reports_not_observed_gap(tmp_path, ledger):
    """Retrospective (Task 5 review fix round 2), N1: a first-ever pid-less observation is itself a gap."""
    _good(tmp_path, ledger)
    rep = run(tmp_path, ledger, minutes=45, proc={})
    assert any("process not observed (nothing listening)" in g for g in rep["restart_gaps"])
