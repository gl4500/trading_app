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
import s1_seal as z
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
    rep22 = run(tmp_path, st_, S2200, clock)
    res = read(res_path(tmp_path, S45))
    assert res["outcome"] == "RESOLUTION-TIMEOUT" and c.aware(res["deadline_utc"]) == D45, res
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
    assert read(res_path(tmp_path, S45))["outcome"] == "RESOLUTION-TIMEOUT"
    assert rep45["seal"]["written"] is False and not SEAL_P(tmp_path).exists()
    late = res_path(tmp_path, S45).with_name(f"{S45.strftime('%Y%m%dT%H%M%SZ')}.late.json")
    assert late.exists() and read(late)["evidence"]["candidate"], "late evidence preserved separately"
    clock.t = S2200 + timedelta(seconds=30)
    rep22 = run(tmp_path, st_, S2200, clock)
    assert rep22["seal"]["written"] is True
    assert read(SEAL_P(tmp_path))["capture"]["scheduled"] == S47.isoformat()


# ====================================================================== expiration racing late completion
@pytest.mark.parametrize("order", ["publication_first", "expiration_first", "barrier"])
def test_b1_expiration_racing_a_late_completion_cannot_change_the_winner(tmp_path, monkeypatch, order):
    """B1.3: completion and expiration are ONE exclusive, irreversible transition per slot. The worker (its clock
    just before D) and a finalizer (at D) race for slot 45: exactly one resolution exists, the seal follows it, and
    neither the loser nor any later replay changes it."""
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
    if order == "barrier":
        bar = threading.Barrier(2, timeout=WAIT)
        real = c.publish_exclusive

        def raced(path, data):
            if Path(path).name.endswith(".resolution.json") and S45.strftime("%Y%m%dT%H%M%SZ") in Path(path).name:
                bar.wait()
            return real(path, data)
        monkeypatch.setattr(c, "publish_exclusive", raced)
        gate.go.set()
        ck.finalize_close(out, day, cal, D45)
        th.join(WAIT)
    elif order == "publication_first":
        gate.go.set()
        th.join(WAIT)
        ck.finalize_close(out, day, cal, D45)
    else:
        ck.finalize_close(out, day, cal, D45)
        gate.go.set()
        th.join(WAIT)
    assert "err" not in box, box
    res = read(res_path(tmp_path, S45))
    winner = S45 if res["outcome"] == "SUCCESS" else S47
    if order == "publication_first":
        assert winner == S45
    if order == "expiration_first":
        assert winner == S47 and res["outcome"] == "RESOLUTION-TIMEOUT"
    ck.finalize_close(out, day, cal, D45 + timedelta(minutes=1))
    seal_bytes = SEAL_P(tmp_path).read_bytes()
    assert json.loads(seal_bytes)["capture"]["scheduled"] == winner.isoformat()
    ck.finalize_close(out, day, cal, D45 + timedelta(hours=1))          # replay: nothing changes
    assert SEAL_P(tmp_path).read_bytes() == seal_bytes and read(res_path(tmp_path, S45)) == res


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
    run(tmp_path, st_, S2200, clock)
    if th is not None:
        gate.go.set()
        th.join(WAIT)
        assert "err" not in box and box["rep"]["seal"]["written"] is False, box
        assert box["rep"]["resolution"]["outcome"] == "RESOLUTION-TIMEOUT"
        assert res_path(tmp_path, S45).with_name(f"{S45.strftime('%Y%m%dT%H%M%SZ')}.late.json").exists()
    res = read(res_path(tmp_path, S45))
    assert res["outcome"] == "RESOLUTION-TIMEOUT" and c.aware(res["deadline_utc"]) == D45
    assert read(SEAL_P(tmp_path))["capture"]["scheduled"] == S47.isoformat()


# ====================================================================== no capture beyond E / W
@pytest.mark.parametrize("at", [E45 + timedelta(seconds=1), D45 - timedelta(seconds=1)])
def test_b1_D_never_extends_capture_eligibility(tmp_path, monkeypatch, at):
    """B1.5: an invocation of slot 45 after E45 (even before D45) takes no capture: D is for processing captured
    evidence only."""
    st_, clock = _setup(tmp_path, monkeypatch, at)
    spy = Snap(monkeypatch)
    rep = run(tmp_path, st_, S45, clock)
    assert spy.calls == 0 and rep["capture_ok"] is False and "clock" in str(rep.get("refused"))
    assert read(res_path(tmp_path, S45))["outcome"] == "FAILURE"


def test_b1_the_0800_slot_takes_no_capture_after_W(tmp_path, monkeypatch):
    """B1.5: E = W = 08:00 for the last slot; one microsecond after W there is no capture although D lies after W."""
    st_ = _registered(tmp_path)
    s8 = z.schedule(_day(st_), st_["calendar"])[-1]
    clock = Clock(s8 + timedelta(microseconds=1))
    monkeypatch.setattr(c, "now_utc", clock)
    spy = Snap(monkeypatch)
    assert z.resolution_deadline(s8, _day(st_), st_["calendar"]) > s8
    rep = run(tmp_path, st_, s8, clock)
    assert spy.calls == 0 and rep["seal"]["written"] is False


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
    Snap(monkeypatch, dur=timedelta(0))
    gate = Gate()
    th, box = bg(lambda: run(tmp_path, st_, s8, clock, receipt_fn=gate))
    assert gate.inside.wait(WAIT)
    clock.t = s8 + timedelta(minutes=10)
    out = tmp_path / "s1_out"
    st = z.current_stop(out, start, cal, clock.t, "test")
    assert st["status"] == "RUNNING" and not (out / "stop.json").exists(), st
    clock.t = s8 + timedelta(minutes=20)
    gate.go.set()
    th.join(WAIT)
    assert "err" not in box, box
    assert box["rep"]["seal"]["written"] is True
    # (corrected after RED, before GREEN: the checkpoint decides the stop at its CAPTURE instant, W itself, where the
    # trial is still RUNNING; the frozen stop is decided by the next command after W - here a stop decision at 08:25)
    assert not (out / "stop.json").exists()
    z.current_stop(out, start, cal, s8 + timedelta(minutes=25), "test")
    stop = read(out / "stop.json")
    assert stop["status"] == "TIMEOUT" and c.aware(stop["stop_close"]) == z.close_of(last["date"], cal), stop
