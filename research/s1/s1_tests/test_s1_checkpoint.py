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


def test_consistency_uses_the_full_capture_while_counts_use_as_of_rows(tmp_path, ledger):
    """Retrospective (Task 9 mutant "consistency on as-of rows instead of the full set", killed before only by the
    connected test): a BUY stored after the close but before the capture is in the portfolio, so consistency is
    judged on the FULL captured row set (consistent, sealed) while the counts use the as-of rows only."""
    make_prereg(tmp_path)
    ledger.trade("A", "BUY", 10, 50, "2026-10-14T15:00:00+00:00")
    ledger.trade("A", "BUY", 5, 51, "2026-10-15T20:30:00+00:00")                        # after the 16:00 EDT close
    ledger.set_portfolio("A", 15)
    rep = run(tmp_path, ledger)
    assert rep["consistent"] is True and rep["entries"] == 1, rep
    assert (tmp_path / "s1_out" / "seals" / "2026-10-15.json").exists()


from datetime import timedelta                                                    # noqa: E402


# ---------------------------------------------------------------- Task 9 round 2: Cosmic Ray survivors (retrospective)
def test_cr_close_for_scans_an_unsorted_calendar_and_refuses_a_non_slot():
    """Retrospective (Task 9 CR survivors s1_checkpoint:31-32): the calendar day without a next session (no window)
    is skipped, never fatal and never the end of the scan, whatever the calendar order."""
    sch = datetime(2026, 10, 15, 20, 45, tzinfo=UTC)
    assert k._close_for(sch, list(reversed(CAL)))["date"] == "2026-10-15"
    with pytest.raises(SystemExit, match="not a registered seal slot"):
        k._close_for(sch + timedelta(minutes=1), CAL)


def test_cr_first_abort_wins_and_a_second_returns_it(tmp_path):
    """Retrospective (Task 9 CR survivors s1_checkpoint:66-68): a second _write_abort (a concurrent run) keeps and
    returns the first record."""
    rep = {"close": "c", "scheduled": "s", "actual": "a"}
    first = k._write_abort(tmp_path, "first", rep, "p1", "r1")
    second = k._write_abort(tmp_path, ["second"], rep, "p2", "r2")
    assert second == first and json.loads((tmp_path / "aborted.json").read_text())["reason"] == "first"


def test_cr_capture_exactly_at_the_slack_is_on_time_and_seals(tmp_path, ledger):
    """Retrospective (Task 9 CR survivor s1_checkpoint:88): actual == scheduled + SCHEDULE_SLACK is not late."""
    _good(tmp_path, ledger)
    rep = run(tmp_path, ledger, minutes=45, delay=600)
    assert rep["late"] is False and rep["seal"]["written"] is True


def test_cr_failed_or_corrupt_capture_reports_no_consistency_and_no_counts(tmp_path, ledger, monkeypatch):
    """Retrospective (Task 9 CR survivors s1_checkpoint:89/131): a failed capture is reported not consistent; a
    corrupt row in scheduled mode leaves the counts None (not the opening-mode marker)."""
    import sqlite3
    import s1_snapshot
    _good(tmp_path, ledger)
    real = s1_snapshot._backup

    def locked(*a, **kw):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(s1_snapshot, "_backup", locked)
    rep = run(tmp_path, ledger, minutes=45)
    assert rep["capture_ok"] is False and rep["consistent"] is False and rep["seal"]["written"] is False
    monkeypatch.setattr(s1_snapshot, "_backup", real)
    ledger.trade("A", "HOLD", 1, 50, "2026-10-14T16:00:00+00:00")
    rep = run(tmp_path, ledger, minutes=47)
    assert rep["capture_ok"] is False and rep["entries"] is None and rep["sold"] is None


def test_cr_start_exactly_at_a_close_seals_that_close_with_a_bridge(tmp_path, ledger):
    """Retrospective (Task 9 CR survivors s1_checkpoint:202): a close at exactly START is post-START, so its seal
    carries the bridge record."""
    start = datetime(2026, 10, 15, 20, 0, tzinfo=UTC)
    (tmp_path / "s1_out").mkdir(parents=True)
    (tmp_path / "s1_out" / "prereg.json").write_text(json.dumps({"start": start.isoformat(), "calendar": CAL,
                                                                 "receipt": REC}), encoding="utf-8")
    ledger.trade("A", "BUY", 10, 50, "2026-10-14T15:00:00+00:00"); ledger.set_portfolio("A", 10)
    rep = run(tmp_path, ledger)
    assert rep["seal"]["written"] is True
    assert json.loads(SEAL(tmp_path).read_text())["bridge"]["bridge_row_ids"] == [1]


def test_cr_bad_seal_record_is_recorded_as_an_abort_not_a_crash(tmp_path, ledger):
    """Retrospective (Task 9 CR survivor s1_checkpoint:212): two seals for one close (stop_decision ValueError)
    -> ABORTED-INVALID "bad seal record", the report is written."""
    _good(tmp_path, ledger)
    assert run(tmp_path, ledger, minutes=45)["seal"]["written"]
    (tmp_path / "s1_out" / "seals" / "2026-10-15-copy.json").write_bytes(SEAL(tmp_path).read_bytes())
    rep = run(tmp_path, ledger, minutes=47)
    assert rep["stop"]["status"] == "ABORTED-INVALID" and "bad seal record" in rep["stop"]["reason"]
    assert "two seals" in json.loads(ABORT(tmp_path).read_text())["reason"]


def test_cr_main_dispatches_each_mode_with_the_live_paths(monkeypatch, capsys):
    """Retrospective (Task 9 CR survivors s1_checkpoint:435-442, main): each mode calls its runner with the
    registered live paths, and the receipt is built from the live checkout's .env and runtime python (receipt
    builder stubbed: nothing live is read)."""
    seen = []
    monkeypatch.setattr(k.r, "semantic_receipt", lambda repo, env, py: seen.append((repo, env, py)) or {"ok": 1})
    monkeypatch.setattr(k, "run_final_snapshot", lambda root, db: {"mode": "final", "root": str(root), "db": str(db)})

    def fake(mode):
        def f(root, db, sch, receipt, proc, log):
            assert receipt() == {"ok": 1} and proc is k.r.process_identity and log == k.CRASH_LOG
            return {"mode": mode, "root": str(root), "db": str(db), "sch": sch.isoformat()}
        return f
    monkeypatch.setattr(k, "run_opening_checkpoint", fake("opening"))
    monkeypatch.setattr(k, "run_checkpoint", fake("scheduled"))
    t = "2026-10-23T20:45:00+00:00"
    for argv, mode in ((["--final-snapshot"], "final"), (["--opening", "--scheduled", t], "opening"),
                       (["--scheduled", t], "scheduled")):
        k.main(argv)
        out = json.loads(capsys.readouterr().out)
        assert out["mode"] == mode and out["root"] == str(k.c.HERE) and out["db"] == str(k.LIVE_DB)
    repo = k.REPO
    assert seen == [(repo, repo / ".env", repo / "runtime" / "python" / "python.exe")] * 2
    assert capsys.readouterr().out == ""


def test_cr_script_entry_point_runs_main():
    """Retrospective (Task 9 CR survivors s1_checkpoint:445, `if __name__ == "__main__"`): running the file as a
    script reaches argparse (--help prints usage and exits 0; nothing else runs)."""
    import subprocess
    import sys
    res = subprocess.run([sys.executable, str(Path(k.__file__)), "--help"], capture_output=True, text=True,
                         timeout=120)
    assert res.returncode == 0 and "--final-snapshot" in res.stdout


def test_cr_corrupt_row_marks_the_capture_meta_failed(tmp_path, ledger):
    """Retrospective (Task 9 CR survivor s1_checkpoint:52, _fail_capture): the capture's meta.json is re-marked
    ok=False (with the BookError) so the capture can never be chosen as a seal later."""
    _good(tmp_path, ledger)
    ledger.trade("A", "HOLD", 1, 50, "2026-10-14T16:00:00+00:00")
    run(tmp_path, ledger)
    meta = json.loads(next((tmp_path / "s1_out" / "captures" / "2026-10-15").glob("*/meta.json")).read_text())
    assert meta["ok"] is False and meta["error"].startswith("BookError")


def test_fr1_main_and_trial_state_compare_modes_and_status_by_value(tmp_path, monkeypatch, capsys):
    """Retrospective (Task 9 fix round 1, review M-1: s1_checkpoint:341/436/438 Eq_Is): a mode or a RUNNING status
    that is an equal but distinct str is still recognised."""
    monkeypatch.setattr(k, "run_final_snapshot", lambda root, db: {"mode": "final-snapshot"})
    monkeypatch.setattr(k, "run_opening_checkpoint", lambda *a: {"mode": "opening"})
    monkeypatch.setattr(k, "run_checkpoint", lambda *a: {"mode": "scheduled"})
    for mode in ("final-snapshot", "opening", "scheduled"):
        monkeypatch.setattr(k, "parse_mode", lambda argv=None, m=mode: ("".join(list(m)), None))
        k.main([])
        assert json.loads(capsys.readouterr().out)["mode"] == mode
    (tmp_path / "s1_out").mkdir()
    monkeypatch.setattr(k.z, "stop_decision", lambda *a, **kw: {"status": "".join(list("RUNNING")),
                                                                "stop_close": None})
    with pytest.raises(SystemExit, match="RUNNING"):
        k._trial_state(tmp_path / "s1_out", {"start": START.isoformat(), "calendar": CAL},
                       datetime(2026, 10, 20, tzinfo=UTC))
