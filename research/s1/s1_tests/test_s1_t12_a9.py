"""Task 12 (controller-added): Addendum 1 rev 3 section A9 (failure outcomes): exceptions preserved with class +
sanitized reason and never sealing (A9.1); transient vs terminal (A9.2); final validation dispositions before
priced work, proven by no-valuation spies across EVERY non-numeric disposition (A9.3). Written BEFORE the
implementation (RED: s1_evidence/t12_A9_red.txt). All synthetic."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import s1_checkpoint as ck
import s1_common as c
import s1_receipt as rc
import s1_run as r
import s1_snapshot
from conftest import s1_prereg_at  # A3 Task 10 (fixture instant)
from conftest import s1_prereg_ack  # A3 Task 6
from conftest import S1_PROCESS, S1_RECEIPT, _Clock, s1_plan_audit, s1_reack, s1_receipt_with, s1_state

UTC = timezone.utc
START = "2026-10-26T13:30:00+00:00"
START_DT = datetime(2026, 10, 26, 13, 30, tzinfo=UTC)
OPEN_CLOSE = datetime(2026, 10, 23, 20, 0, tzinfo=UTC)
SECRET = "AKIA-SECRET-VALUE-42"


def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _reg(tmp_path):
    st_ = s1_state(tmp_path, START)
    with _Clock(s1_prereg_at(tmp_path)):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    s1_prereg_ack(tmp_path)                    # A3 Task 6 (F7.4): the PREREG-ACK before captures
    st_["ledger"].trade("A", "BUY", 10, 50.0, "2026-10-26T15:00:00+00:00")
    st_["ledger"].set_portfolio("A", 10)
    return st_


def _cp(tmp_path, st_, receipt_fn=None, process_fn=None, minutes=45):
    sch = datetime(2026, 10, 26, 20, 0, tzinfo=UTC) + timedelta(minutes=minutes)
    act = sch + timedelta(seconds=30)
    with _Clock(act):
        return ck.run_checkpoint(tmp_path, st_["ledger"].path, sch, receipt_fn or (lambda: S1_RECEIPT),
                                 process_fn or (lambda: dict(S1_PROCESS)), tmp_path / "crash.log", now=lambda: act)


def boom(exc):
    def f():
        raise exc
    return f


SEAL = lambda root: root / "s1_out" / "seals" / "2026-10-26.json"           # noqa: E731


# ====================================================================== A9.1 preserved, sanitized, never sealed
@pytest.mark.parametrize("where", ["receipt", "process"])
def test_a9_receipt_or_process_exception_is_preserved_sanitized_and_never_seals(tmp_path, where):
    """A9.1 / Codex probe g: an exception from the receipt or the process observation is preserved in the capture
    report (exception class + sanitized reason, never secret-bearing text) and the attempt never seals."""
    st_ = _reg(tmp_path)
    exc = RuntimeError(f"git failed; token={SECRET}")
    rep = _cp(tmp_path, st_, **{f"{where}_fn": boom(exc)})
    assert rep["seal"]["written"] is False and not SEAL(tmp_path).exists()
    err = rep["failures"][where]
    assert err["class"] == "RuntimeError" and SECRET not in json.dumps(rep)
    reports = list((tmp_path / "s1_out" / "captures" / "2026-10-26").glob("*.report.json"))
    assert len(reports) == 1 and SECRET not in reports[0].read_text(encoding="utf-8")
    assert read(reports[0])["failures"][where]["class"] == "RuntimeError"


def test_a9_a_capture_exception_is_preserved_and_never_seals(tmp_path, monkeypatch):
    """A9.1: an unexpected exception inside the capture is preserved (class + sanitized reason), never a crash
    without a report, never a seal."""
    st_ = _reg(tmp_path)

    def bad(*a, **kw):
        raise ValueError(f"weird {SECRET}")
    monkeypatch.setattr(s1_snapshot, "take_snapshot", bad)
    rep = _cp(tmp_path, st_)
    assert rep["seal"]["written"] is False and rep["failures"]["capture"]["class"] == "ValueError"
    assert SECRET not in json.dumps(rep) and not SEAL(tmp_path).exists()


def test_a9_an_opening_receipt_exception_is_preserved_and_never_seals(tmp_path, ledger):
    """A9.1 in the opening mode."""
    s1_plan_audit(tmp_path, START)
    sch = OPEN_CLOSE + timedelta(minutes=45)
    act = sch + timedelta(seconds=30)
    with _Clock(act):
        rep = ck.run_opening_checkpoint(tmp_path, ledger.path, sch, boom(OSError(f"denied {SECRET}")),
                                        lambda: dict(S1_PROCESS), tmp_path / "crash.log", now=lambda: act)
    assert rep["seal"]["written"] is False and rep["failures"]["receipt"]["class"] == "OSError"
    assert SECRET not in json.dumps(rep) and not (tmp_path / "s1_out" / "opening_receipt.json").exists()


# ====================================================================== A9.2 transient vs terminal
def test_a9_a_transient_unavailable_receipt_is_a_failed_attempt_and_a_later_slot_seals(tmp_path):
    """A9.2: an unavailable observation with no established violation is a failed attempt under the frozen retry
    schedule: no abort; the next registered slot can seal."""
    st_ = _reg(tmp_path)
    rep = _cp(tmp_path, st_, receipt_fn=boom(rc.ReceiptError("git unavailable (TimeoutExpired)", terminal=False)))
    assert rep["seal"]["written"] is False and not (tmp_path / "s1_out" / "aborted.json").exists()
    rep = _cp(tmp_path, st_, minutes=47)
    assert rep["seal"]["written"] is True


def test_a9_an_established_receipt_violation_is_terminal_and_survives_restoration(tmp_path):
    """A9.2: an observed semantic violation (here: a registered closure member is gone) is terminal: aborted.json;
    a later good receipt never resumes the trial."""
    st_ = _reg(tmp_path)
    rep = _cp(tmp_path, st_, receipt_fn=boom(rc.ReceiptError("closure member trading/risk.py missing",
                                                             terminal=True)))
    assert rep["stop"]["status"] == "ABORTED-INVALID"
    assert "semantic receipt" in read(tmp_path / "s1_out" / "aborted.json")["reason"]
    with pytest.raises(SystemExit, match=r"trial INVALID \(reason/established-violation\)"):   # A3 Task 6 (F1)
        _cp(tmp_path, st_, minutes=47)                                   # a later good receipt: no work, no seal
    assert not (tmp_path / "s1_out" / "seals" / "2026-10-26.json").exists()


def test_a9_missing_required_evidence_never_becomes_a_plausible_match(tmp_path):
    """A9.2: a receipt that lacks its fingerprint is not a match (and not a mismatch either: nothing is compared);
    no seal."""
    st_ = _reg(tmp_path)
    rep = _cp(tmp_path, st_, receipt_fn=lambda: {"provenance": {"head": "h"}})
    assert rep["receipt_match"] is not True and rep["seal"]["written"] is False


def test_a9_a_process_observation_gap_is_not_an_mr_semantic_change(tmp_path, monkeypatch):
    """A9.3: a process-observation gap (nothing listening, a pid change without a PROCESS START line) is reported,
    never equated with an MR semantic change: the trial still seals and is scored."""
    st_ = _reg(tmp_path)
    # (fix round 2 migration, Addendum 2 B2.4: the gap is an explicitly unavailable binding; {"error": ...} is now
    # a failed observation, A9.1 - covered by test_s1_t12_fix2_b2.py)
    rep = _cp(tmp_path, st_, process_fn=lambda: {"pid": None, "binding": {"unavailable": "nothing listening"}})
    assert rep["restart_gaps"] and rep["seal"]["written"] is True
    assert not (tmp_path / "s1_out" / "aborted.json").exists()


# ====================================================================== A9.3 no valuation on non-numeric dispositions
VALUATION = ("simulate_lot", "lot_economics", "baseline_economics", "compare", "paired_bootstrap")


def _spy(monkeypatch):
    sim = c.sim()
    called = []
    for name in VALUATION:
        monkeypatch.setattr(sim, name, lambda *a, _n=name, **kw: called.append(_n) or pytest.fail(_n))
    return called


def _lots(n=100, sell_day=1):
    return [{"symbol": f"S{i % 5}", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (sell_day, 80.0)}
            for i in range(n)]


DISPOSITIONS = {
    "ABORTED-INVALID": dict(lots=_lots(), _abort=True),
    "BLOCKED": dict(lots=_lots(), audit_actions=[{"type": "forward_splits", "id": "s", "symbol": "CI",
                                                  "ex_date": "2026-10-05", "old_rate": 1, "new_rate": 2}],
                    _prereg_blocked=True),
    "NO-VALID-SEAL": dict(lots=[], seal_days=[]),
    "INCONCLUSIVE-carry-in": dict(lots=_lots(), final_actions=[{"type": "forward_splits", "id": "s",
                                                                "symbol": "CI", "ex_date": "2026-10-27",
                                                                "old_rate": 1, "new_rate": 2}]),
    "INCONCLUSIVE-contamination": dict(lots=_lots() + [{"symbol": "A", "qty": 1, "px": 5.0, "buy_day": 0,
                                                        "sell": (1, 5.0)}],
                                       final_actions=[{"type": "forward_splits", "id": "s", "symbol": "A",
                                                       "ex_date": "2026-10-27", "old_rate": 1, "new_rate": 2}]),
    "INCONCLUSIVE-cap": dict(lots=_lots(), bar_fn=lambda s, d: None if s == "S0" else
                             {"date": d, "o": 100, "h": 101, "l": 99, "c": 100}),
    "INSUFFICIENT": dict(lots=_lots(20)),                   # 20 sold lots: a TIMEOUT with N = 20 < 30 retained
}


@pytest.mark.parametrize("kind", sorted(DISPOSITIONS))
def test_a9_every_non_numeric_disposition_makes_no_valuation_call(tmp_path, monkeypatch, kind):
    """A9.3: ABORTED-INVALID, BLOCKED, NO-VALID-SEAL, INCONCLUSIVE (carry-in, contamination 2b, > 10 % cap) and
    INSUFFICIENT are each reached with spies on every valuation helper - none may be called (proof by spies, not by
    omitted output fields)."""
    kw = dict(DISPOSITIONS[kind])
    abort, blocked = kw.pop("_abort", False), kw.pop("_prereg_blocked", False)
    if blocked:                                       # as test_s1_run: bypass prereg's BLOCKED gate, score re-checks
        with monkeypatch.context() as m:
            m.setattr(r, "carry_in_reasons", lambda *a, **k_: [])
            st_ = s1_state(tmp_path, START, score_ready=True, **kw)
    else:
        st_ = s1_state(tmp_path, START, score_ready=True, **kw)
    if abort:
        c.write_abort(tmp_path / "s1_out", {"reason": "semantic receipt changed",
                                             "actual": (START_DT + timedelta(hours=30)).isoformat()})
    called = _spy(monkeypatch)
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"] + timedelta(days=1))
    from conftest import s1_mailbox
    s1_reack(tmp_path, "score-ack-n", "S1-SCORE-ACK", st_["now"] + timedelta(hours=20))
    rep = r.score(tmp_path, "score-ack-n")
    want = {"INCONCLUSIVE-carry-in": "INCONCLUSIVE", "INCONCLUSIVE-contamination": "INCONCLUSIVE",
            "INCONCLUSIVE-cap": "INCONCLUSIVE"}.get(kind, kind)
    assert rep["verdict"] == want, (kind, rep["verdict"], rep["reasons"])
    assert called == [] and "levels" not in rep
