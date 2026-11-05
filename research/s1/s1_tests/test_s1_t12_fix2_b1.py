"""Task 12 fix round 2: Addendum 2 B1 (slot resolution deadline D = E + RESOLUTION_TIMEOUT; serialized close-level
selection). Every B1.6 acceptance example, written BEFORE the fix (RED: s1_evidence/t12_fix2_B1_red.txt).
Concurrency and time use injected aware clocks and threading.Event / Barrier synchronization; no real sleeps.
Synthetic only: tmp_path ledgers, mailbox and HMAC key."""
import ast
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import s1_checkpoint as ck
import s1_common as c
import s1_journal as j
import s1_seal as z
import s1_trial as t
from conftest import S1_PROCESS, S1_RECEIPT
from test_s1_t12_a5_a6 import MON_CLOSE, S45, S47, SEAL_P, Snap, _registered

UTC = timezone.utc
HERE = Path(__file__).resolve().parent.parent
DAY = "2026-10-26"
E45 = S45 + timedelta(minutes=10)                       # 20:55:00
D45 = E45 + timedelta(minutes=30)                       # 21:25:00
S2100 = datetime(2026, 10, 26, 21, 0, tzinfo=UTC)
S2200 = datetime(2026, 10, 26, 22, 0, tzinfo=UTC)
WAIT = 20                                               # seconds a synchronization wait may block (never a sleep)


def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


class Clock:
    """An injected aware clock shared by every actor of a test; the test thread moves it between phases."""

    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class Killed(BaseException):
    """A worker killed mid-attempt (escapes every `except Exception`)."""


class Gate:
    """A receipt function that blocks inside the attempt until released (a slow worker)."""

    def __init__(self):
        self.inside, self.go = threading.Event(), threading.Event()

    def __call__(self, *a, **kw):
        self.inside.set()
        assert self.go.wait(WAIT), "gate never released"
        return S1_RECEIPT


def run(tmp_path, st_, slot, now, receipt_fn=None, process_fn=None):
    return ck.run_checkpoint(tmp_path, st_["ledger"].path, slot, receipt_fn or (lambda: S1_RECEIPT),
                             process_fn or (lambda: dict(S1_PROCESS)), tmp_path / "crash.log", now=now)


def bg(fn):
    box = {}

    def target():
        try:
            box["rep"] = fn()
        except BaseException as e:                     # noqa: BLE001 - reported to the test thread
            box["err"] = e
    th = threading.Thread(target=target, daemon=True)
    th.start()
    return th, box


def res_path(tmp_path, slot):
    return tmp_path / "s1_out" / "captures" / DAY / f"{slot.strftime('%Y%m%dT%H%M%SZ')}.resolution.json"


def _setup(tmp_path, monkeypatch, t):
    st_ = _registered(tmp_path)
    clock = Clock(t)
    monkeypatch.setattr(c, "now_utc", clock)
    return st_, clock


def _day(st_):
    return next(d for d in st_["calendar"] if d["date"] == DAY)


def _rows(tmp_path):
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    return j.read_trial(tr.trial_id, tr.genesis, tmp_path / "mailbox.sqlite3")


def kinds(tmp_path, slot):
    """A3 Task 6: the slot's journal rows (the journal decides the slot, F3)."""
    return [x.kind for x in j.subject_rows(_rows(tmp_path), j.slot_subject(slot))]


def timeout_row(tmp_path, st_, slot, at):
    """A3 Task 6 (E1.2): the finalizer's SLOT-TIMEOUT for `slot` at `at` (the INTENT's op, its own actor) through the
    product context - the journal transaction arbitrates it against the worker's J; no lock is taken (Task 7 builds
    the finalizer command around this append)."""
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    intent = j.first(j.subject_rows(_rows(tmp_path), j.slot_subject(slot)), "SLOT-INTENT")
    return j.append(tr.trial_id, tr.genesis, j.Request("SLOT-TIMEOUT", j.slot_subject(slot), intent.op, j.new_nonce()),
                    t.product_context(tr, st_["calendar"]), mailbox=tmp_path / "mailbox.sqlite3", clock=lambda: at)


# ====================================================================== B1.1 single-sourced deadline
def test_b1_resolution_timeout_is_thirty_minutes_and_single_sourced():
    """B1.1: RESOLUTION_TIMEOUT = 30 min, named and single-sourced in s1_seal; D(s) = E(s) + 30 min."""
    assert z.RESOLUTION_TIMEOUT == timedelta(minutes=30)
    cal = [{"date": DAY, "open": "09:30", "close": "16:00"}, {"date": "2026-10-27", "open": "09:30",
                                                                  "close": "16:00"}]
    for s in z.schedule(cal[0], cal):
        assert z.resolution_deadline(s, cal[0], cal) == z.eligible_until(s, cal[0], cal) + timedelta(minutes=30)
    for name in c.BUNDLE_CODE:
        if not name.startswith("s1_") or name == "s1_seal.py":
            continue
        tree = ast.parse((HERE / name).read_text(encoding="utf-8"))
        bad = [ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.Call) and ast.unparse(n.func).endswith(
            "timedelta") and any(kw.arg == "minutes" for kw in n.keywords)]
        assert not bad, (name, bad)


# ====================================================================== B1.6 the review's overlap race
@pytest.mark.parametrize("order", ["later_slot_finalizes_first", "earlier_slot_finishes_first"])
def test_b1_the_reviews_overlap_race_selects_the_earlier_slot_in_both_completion_orders(tmp_path, monkeypatch,
                                                                                         order):
    """B1.4/B1.6 (review I-3): slot 45 captures 20:54:50-20:54:58 (within E45 = 20:55:00) and completes its receipt
    at 20:55:06; slot 47 captures at 20:55:03. Whatever the finalizer arrival order, the seal is slot 45's."""
    st_, clock = _setup(tmp_path, monkeypatch, S45 + timedelta(minutes=9, seconds=50))
    spy = Snap(monkeypatch, dur=timedelta(seconds=8))
    if order == "later_slot_finalizes_first":
        gate = Gate()
        th, box = bg(lambda: run(tmp_path, st_, S45, clock, receipt_fn=gate))
        assert gate.inside.wait(WAIT)
        clock.t = E45 + timedelta(seconds=3)
        spy.dur = timedelta(seconds=1)
        rep47 = run(tmp_path, st_, S47, clock)
        assert rep47["consistent"] is True and rep47["seal"]["written"] is False and not SEAL_P(tmp_path).exists()
        assert "pending" in str(rep47.get("deferred")) and S45.isoformat() in str(rep47.get("deferred")), rep47
        clock.t = E45 + timedelta(seconds=6)
        gate.go.set()
        th.join(WAIT)
        assert "err" not in box, box
        assert box["rep"]["seal"]["written"] is True
    else:
        rep45 = run(tmp_path, st_, S45, clock)
        assert rep45["seal"]["written"] is True
        clock.t = E45 + timedelta(seconds=3)
        spy.dur = timedelta(seconds=1)
        assert run(tmp_path, st_, S47, clock)["seal"]["written"] is False
    assert read(SEAL_P(tmp_path))["capture"]["scheduled"] == S45.isoformat()


# ====================================================================== claim without report
def test_b1_a_claim_without_a_report_stays_pending_after_E_and_times_out_at_D(tmp_path, monkeypatch):
    """B1.2/B1.3: slot 45 is claimed and its worker dies before publishing. After E45 the slot is PENDING (no
    MISSED, no later seal); before D45 still pending; at the first invocation after D45 it becomes a preserved
    RESOLUTION-TIMEOUT and the slot-47 capture becomes the seal (slot order)."""
    st_, clock = _setup(tmp_path, monkeypatch, S45 + timedelta(seconds=30))
    Snap(monkeypatch)

    def die():
        raise Killed()
    with pytest.raises(Killed):
        run(tmp_path, st_, S45, clock, process_fn=die)
    assert not res_path(tmp_path, S45).exists()
    clock.t = S47 + timedelta(seconds=30)
    rep47 = run(tmp_path, st_, S47, clock)
    assert rep47["seal"]["written"] is False
    clock.t = S2100 + timedelta(seconds=30)                     # E45 < 21:00:30 < D45 = 21:25
    rep21 = run(tmp_path, st_, S2100, clock)
    assert rep21["seal"]["written"] is False and not SEAL_P(tmp_path).exists()
    assert "pending" in str(rep21.get("deferred")), rep21
    assert not res_path(tmp_path, S45).exists()
    clock.t = S2200 + timedelta(seconds=30)                     # after D45
    # A3 Task 6 (B1.3 -> F3, E1.4; fix round 1, review C2): no RESOLUTION-TIMEOUT file is written into the slot (the
    # finalizer never touches a worker's files); an INTENT-only slot is not terminal, so the finalizer's SLOT-TIMEOUT
    # row (Task 7's, here timeout_row) commits first at D45 - then slot 47 is selectable and is the seal
    assert timeout_row(tmp_path, st_, S45, D45).outcome == "APPEND"
    rep22 = run(tmp_path, st_, S2200, clock)
    assert not res_path(tmp_path, S45).exists() and kinds(tmp_path, S45) == ["SLOT-INTENT", "SLOT-TIMEOUT"]
    assert z.resolution_deadline(S45, _day(st_), st_["calendar"]) == D45 < clock.t
    assert rep22["seal"]["written"] is True and rep22["seal"].get("from_slot") == S47.isoformat()
    assert read(SEAL_P(tmp_path))["capture"]["scheduled"] == S47.isoformat()


# ====================================================================== just before D / at D
@pytest.mark.parametrize("offset,qualifies", [(-timedelta(microseconds=1), True), (timedelta(0), False),
                                              (timedelta(minutes=1), False)])
def test_b1_a_success_published_strictly_before_D_qualifies_at_or_after_D_it_times_out(tmp_path, monkeypatch,
                                                                                        offset, qualifies):
    """B1.3: slot 47 completes first (deferred: slot 45 claimed); slot 45's capture is eligible but its worker
    publishes at D45 + offset. Strictly before D it is SUCCESS and the seal; at/after D it is a preserved
    RESOLUTION-TIMEOUT, its late evidence is kept separately, it writes no seal, and the next invocation seals slot
    47."""
    st_, clock = _setup(tmp_path, monkeypatch, S45 + timedelta(minutes=9, seconds=50))
    Snap(monkeypatch, dur=timedelta(seconds=8))
    gate = Gate()
    th, box = bg(lambda: run(tmp_path, st_, S45, clock, receipt_fn=gate))
    assert gate.inside.wait(WAIT)
    clock.t = S47 + timedelta(minutes=8)                        # 20:55:00, within E47 = 20:57
    assert run(tmp_path, st_, S47, clock)["seal"]["written"] is False
    clock.t = D45 + offset
    gate.go.set()
    th.join(WAIT)
    assert "err" not in box, box
    rep45 = box["rep"]
    if qualifies:
        assert read(res_path(tmp_path, S45))["outcome"] == "SUCCESS"
        assert rep45["seal"]["written"] is True
        assert read(SEAL_P(tmp_path))["capture"]["scheduled"] == S45.isoformat()
        return
    # A3 Task 6 (F0.5 step 6, F3; replaces B1.3's late-worker RESOLUTION-TIMEOUT and .late.json): R >= D, so the
    # SLOT-QUALIFIED is refused with no row (the finalizer later appends TIMEOUT, Task 7); the worker's own P stays
    # (its evidence is preserved in place, never selectable) and it writes no seal
    assert rep45["journal"]["kind"] == "SLOT-QUALIFIED" and rep45["journal"]["outcome"] == "REFUSE"
    assert "late R" in rep45["journal"]["reason"] and kinds(tmp_path, S45) == ["SLOT-INTENT"]
    assert rep45["seal"]["written"] is False and not SEAL_P(tmp_path).exists()
    assert read(res_path(tmp_path, S45))["evidence"]["candidate"], "the worker's evidence is preserved"
    assert not res_path(tmp_path, S45).with_name(f"{S45.strftime('%Y%m%dT%H%M%SZ')}.late.json").exists()
    clock.t = S2200 + timedelta(seconds=30)
    assert timeout_row(tmp_path, st_, S45, clock.t).outcome == "APPEND"      # fix round 1 (C2): the finalizer's row
    rep22 = run(tmp_path, st_, S2200, clock)                                # first (Task 7), then slot 47 seals
    assert rep22["seal"]["written"] is True
    assert read(SEAL_P(tmp_path))["capture"]["scheduled"] == S47.isoformat()


# ====================================================================== expiration racing late completion
@pytest.mark.parametrize("order", ["publication_first", "expiration_first", "barrier"])
def test_b1_expiration_racing_a_late_completion_cannot_change_the_winner(tmp_path, monkeypatch, order):
    """B1.3: completion and expiration are ONE exclusive, irreversible transition per slot. The worker (its clock
    just before D) and a finalizer (at D) race for slot 45: exactly one resolution exists, the seal follows it, and
    neither the loser nor any later replay changes it.
    A3 Task 6 (B1.3 -> F3, Erratum 1 E1.2/E1.3): that one transition is the slot's FIRST TERMINAL JOURNAL ROW - the
    worker's SLOT-QUALIFIED (R just before D) or the finalizer's SLOT-TIMEOUT (at D, appended with no lock) - decided
    inside the journal transaction; the loser is LOST-RACE (no row, no INVALID); the seal follows the winner."""
    st_, clock = _setup(tmp_path, monkeypatch, S45 + timedelta(minutes=9, seconds=50))
    Snap(monkeypatch, dur=timedelta(seconds=8))
    gate = Gate()
    wclock = Clock(clock.t)
    th, box = bg(lambda: run(tmp_path, st_, S45, wclock, receipt_fn=gate))
    assert gate.inside.wait(WAIT)
    clock.t = S47 + timedelta(minutes=8)
    assert run(tmp_path, st_, S47, clock)["seal"]["written"] is False
    out, day, cal = tmp_path / "s1_out", _day(st_), st_["calendar"]
    wclock.t, clock.t = D45 - timedelta(microseconds=1), D45
    fin = {}
    if order == "barrier":
        bar = threading.Barrier(2, timeout=WAIT)
        real = j.append

        def raced(trial_id, gen, req, ctx_fn, **kw):
            if req.kind in ("SLOT-QUALIFIED", "SLOT-TIMEOUT") and req.subject == j.slot_subject(S45):
                bar.wait()
            return real(trial_id, gen, req, ctx_fn, **kw)
        monkeypatch.setattr(j, "append", raced)
        gate.go.set()
        fin["res"] = timeout_row(tmp_path, st_, S45, D45)
        th.join(WAIT)
    elif order == "publication_first":
        gate.go.set()
        th.join(WAIT)
        fin["res"] = timeout_row(tmp_path, st_, S45, D45)
    else:
        fin["res"] = timeout_row(tmp_path, st_, S45, D45)
        gate.go.set()
        th.join(WAIT)
    assert "err" not in box, box
    terminal = [k_ for k_ in kinds(tmp_path, S45) if k_ != "SLOT-INTENT"]
    assert len(terminal) == 1, terminal                                    # exactly one terminal transition
    winner = S45 if terminal == ["SLOT-QUALIFIED"] else S47
    loser = box["rep"]["journal"]["outcome"] if winner == S47 else fin["res"].outcome
    assert loser == "LOST-RACE" and all(x.kind != "TRIAL-INVALID" for x in _rows(tmp_path))
    if order == "publication_first":
        assert winner == S45
    if order == "expiration_first":
        assert winner == S47 and terminal == ["SLOT-TIMEOUT"]
    rows = _rows(tmp_path)
    ck.finalize_close(out, day, cal, D45 + timedelta(minutes=1), rows=rows)
    seal_bytes = SEAL_P(tmp_path).read_bytes()
    assert json.loads(seal_bytes)["capture"]["scheduled"] == winner.isoformat()
    ck.finalize_close(out, day, cal, D45 + timedelta(hours=1), rows=_rows(tmp_path))    # replay: nothing changes
    assert SEAL_P(tmp_path).read_bytes() == seal_bytes and [x.line for x in _rows(tmp_path)] == [x.line for x in rows]


# ====================================================================== killed vs slow
@pytest.mark.parametrize("kind", ["killed", "slow"])
def test_b1_killed_and_merely_slow_workers_get_the_same_timeout_disposition(tmp_path, monkeypatch, kind):
    """B1.1/B1.3: elapsed time never claims a worker died: a killed worker and a slow one still running after D both
    resolve as RESOLUTION-TIMEOUT with the same deadline; the slow one's late evidence is preserved separately and
    the seal is slot 47's either way."""
    st_, clock = _setup(tmp_path, monkeypatch, S45 + timedelta(seconds=30))
    Snap(monkeypatch)
    th = None
    if kind == "killed":
        def die():
            raise Killed()
        with pytest.raises(Killed):
            run(tmp_path, st_, S45, clock, process_fn=die)
    else:
        gate = Gate()
        th, box = bg(lambda: run(tmp_path, st_, S45, clock, receipt_fn=gate))
        assert gate.inside.wait(WAIT)
    clock.t = S47 + timedelta(seconds=30)
    run(tmp_path, st_, S47, clock)
    clock.t = S2200 + timedelta(seconds=30)
    # fix round 1 (review C2): the finalizer's SLOT-TIMEOUT for slot 45 (Task 7's row, here timeout_row) commits at
    # D45 with no lock, while the slow worker still holds the slot (E1.2); then slot 47 is selectable
    assert timeout_row(tmp_path, st_, S45, D45).outcome == "APPEND"
    run(tmp_path, st_, S2200, clock)
    if th is not None:
        gate.go.set()
        th.join(WAIT)
        # A3 Task 6 (E1.3): after the committed TIMEOUT the slow worker's QUALIFIED is LOST-RACE at 4c, whatever its
        # R: no row, no INVALID, no seal; its own files move to late/ (no .late.json record)
        assert "err" not in box and box["rep"]["seal"]["written"] is False, box
        assert box["rep"]["journal"]["outcome"] == "LOST-RACE", box["rep"]["journal"]
        assert not res_path(tmp_path, S45).with_name(f"{S45.strftime('%Y%m%dT%H%M%SZ')}.late.json").exists()
    # A3 Task 6 (B1.3 -> F3, E1.4): both dispositions are the same - slot 45 ends SLOT-TIMEOUT (the finalizer's row);
    # no RESOLUTION-TIMEOUT file is written into the slot
    assert kinds(tmp_path, S45) == ["SLOT-INTENT", "SLOT-TIMEOUT"]
    assert z.resolution_deadline(S45, _day(st_), st_["calendar"]) == D45
    if kind == "killed":
        assert not res_path(tmp_path, S45).exists()
    assert read(SEAL_P(tmp_path))["capture"]["scheduled"] == S47.isoformat()


# ====================================================================== no capture beyond E / W
@pytest.mark.parametrize("at", [E45 + timedelta(seconds=1), D45 - timedelta(seconds=1)])
def test_b1_D_never_extends_capture_eligibility(tmp_path, monkeypatch, at):
    """B1.5: an invocation of slot 45 after E45 (even before D45) takes no capture: D is for processing captured
    evidence only."""
    st_, clock = _setup(tmp_path, monkeypatch, at)
    spy = Snap(monkeypatch)
    with pytest.raises(SystemExit, match="now >= E"):          # A3 Task 6 (F0.5 step 6): refused with no row
        run(tmp_path, st_, S45, clock)
    assert spy.calls == 0 and not res_path(tmp_path, S45).exists() and kinds(tmp_path, S45) == []


def test_b1_the_0800_slot_takes_no_capture_after_W(tmp_path, monkeypatch):
    """B1.5: E = W = 08:00 for the last slot; one microsecond after W there is no capture although D lies after W."""
    st_ = _registered(tmp_path)
    s8 = z.schedule(_day(st_), st_["calendar"])[-1]
    clock = Clock(s8 + timedelta(microseconds=1))
    monkeypatch.setattr(c, "now_utc", clock)
    spy = Snap(monkeypatch)
    assert z.resolution_deadline(s8, _day(st_), st_["calendar"]) > s8
    with pytest.raises(SystemExit, match="now >= E"):          # A3 Task 6 (F0.5 step 6): refused with no row
        run(tmp_path, st_, s8, clock)
    assert spy.calls == 0 and kinds(tmp_path, s8) == [] and not SEAL_P(tmp_path).exists()


# ====================================================================== concurrent finalizers + replay
def test_b1_concurrent_finalizers_and_restart_replay_give_one_deterministic_seal(tmp_path, monkeypatch):
    """B1.4: with slot 45 and slot 47 both resolved SUCCESS and no seal yet, four concurrent finalizers (released
    together by a barrier) write exactly one seal - slot 45's - and a restart replay (a later slot, another
    finalize) leaves it byte-identical."""
    st_, clock = _setup(tmp_path, monkeypatch, S47 + timedelta(seconds=30))
    Snap(monkeypatch)
    run(tmp_path, st_, S47, clock)
    real = ck.finalize_close

    def crash_before_finalize(*a, **kw):
        raise Killed()
    monkeypatch.setattr(ck, "finalize_close", crash_before_finalize)
    clock.t = S45 + timedelta(minutes=4)
    with pytest.raises(Killed):
        run(tmp_path, st_, S45, clock)
    monkeypatch.setattr(ck, "finalize_close", real)
    assert read(res_path(tmp_path, S45))["outcome"] == "SUCCESS" and not SEAL_P(tmp_path).exists()
    out, day, cal = tmp_path / "s1_out", _day(st_), st_["calendar"]
    bar = threading.Barrier(4, timeout=WAIT)
    results = []

    def fin():
        bar.wait()
        return real(out, day, cal, S45 + timedelta(minutes=5))
    threads = [bg(fin) for _ in range(4)]
    for th, box in threads:
        th.join(WAIT)
        assert "err" not in box, box
        results.append(box["rep"])
    assert sum(1 for x in results if x["written"]) == 1, results
    seal_bytes = SEAL_P(tmp_path).read_bytes()
    assert json.loads(seal_bytes)["capture"]["scheduled"] == S45.isoformat()
    clock.t = S2100 + timedelta(seconds=30)
    assert run(tmp_path, st_, S2100, clock)["seal"]["written"] is False
    real(out, day, cal, S2200)
    assert SEAL_P(tmp_path).read_bytes() == seal_bytes


# ====================================================================== no early terminal stop then rescue
def test_b1_a_pending_resolution_cannot_cause_an_early_terminal_stop_followed_by_rescue(tmp_path, monkeypatch):
    """B1.5: the last eligible session's 08:00 slot (E = W = s, D = s + 30 min) is claimed and captured exactly at
    08:00:00 (zero duration) and its worker is still finishing at 08:10. A stop decision then must NOT freeze
    NO-VALID-SEAL (the attempt is PENDING); once it publishes SUCCESS before D the close is sealed and the frozen
    stop is TIMEOUT at that close - decided once, never a terminal outcome followed by a rescue."""
    st_ = _registered(tmp_path)
    cal, start = st_["calendar"], st_["start"]
    last = z.eligible_sessions(start, cal)[-1]
    s8 = z.schedule(last, cal)[-1]
    clock = Clock(s8)
    monkeypatch.setattr(c, "now_utc", clock)
    spy = Snap(monkeypatch, dur=timedelta(0))
    # A3 Task 6 (F0.5 step 6 with A5.3's E = W = s): the 08:00 slot's SLOT-INTENT at s = E is refused with no row
    # (and A5.2 refuses any capture before s), so the slot can never be in flight: no pending attempt exists that a
    # later publication could "rescue" - the stop is decided once
    assert z.eligible_until(s8, last, cal) == s8
    with pytest.raises(SystemExit, match="now >= E"):
        run(tmp_path, st_, s8, clock)
    assert spy.calls == 0 and kinds(tmp_path, s8) == []
    out = tmp_path / "s1_out"
    st1 = z.current_stop(out, start, cal, s8 + timedelta(minutes=10), "test")
    st2 = z.current_stop(out, start, cal, s8 + timedelta(minutes=25), "test")
    assert (st1["status"], st1["stop_close"]) == (st2["status"], st2["stop_close"]), (st1, st2)
    assert st1["status"] != "RUNNING" and read(out / "stop.json")["status"] == st1["status"]
