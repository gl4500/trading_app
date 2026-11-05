"""Task 12 (controller-added): Addendum 1 rev 3 sections A5 (timing: aware deadline instant, Q7 slot eligibility
E = min(s + SCHEDULE_SLACK, W), the non-sealable 08:00 slot, the >= 5 sessions from the AUDIT-ACK) and A6 (the
pinned provider calendar). Written BEFORE the implementation (RED: s1_evidence/t12_A5_red.txt, t12_A6_red.txt).
All synthetic: tmp_path ledgers and mailbox, fixed clocks; no live DB, network, real mailbox or scheduler."""
import ast
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from hypothesis import given, settings, strategies as st

import s1_checkpoint as ck
import s1_collect as k
import s1_common as c
import s1_run as r
import s1_seal as z
import s1_snapshot
import s1_trial as t
from conftest import S1_PROCESS, S1_RECEIPT, _Clock, _weekdays, s1_mailbox, s1_state


def tr(i, sym, act, sh, ts):
    return {"id": i, "symbol": sym, "action": act, "shares": sh, "price": 10.0, "timestamp": ts, "ts": ts,
            "reasoning_sha256": "0" * 64}

UTC = timezone.utc
NY = c.NY
HERE = Path(__file__).resolve().parent.parent
START = "2026-10-26T13:30:00+00:00"                     # Mon 09:30 EDT
START_DT = datetime(2026, 10, 26, 13, 30, tzinfo=UTC)


def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def ny(d: str, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime.combine(date.fromisoformat(d), datetime.min.time().replace(hour=h, minute=m),
                            tzinfo=NY).astimezone(UTC)


def cal_rows(first, last, holidays=(), early=None):
    out, d = [], date.fromisoformat(first)
    while d <= date.fromisoformat(last):
        if d.weekday() < 5 and d.isoformat() not in holidays:
            out.append({"date": d.isoformat(), "open": "09:30", "close": (early or {}).get(d.isoformat(), "16:00")})
        d += timedelta(days=1)
    return out


# ====================================================================== A5.1 the deadline is an aware instant
def test_a5_deadline_is_an_aware_instant_at_starts_new_york_wall_time():
    """A5.1: START + 6 calendar months at START's New York wall time (month-end clamp), an aware instant; DST
    changes keep the wall time (09:30 EDT -> 09:30 EST)."""
    dl = z.deadline(datetime(2026, 10, 15, 13, 30, tzinfo=UTC))            # 09:30 EDT
    assert isinstance(dl, datetime) and dl.tzinfo is not None
    assert dl == ny("2027-04-15", "09:30") == datetime(2027, 4, 15, 13, 30, tzinfo=UTC)
    dl = z.deadline(datetime(2026, 8, 31, 13, 30, tzinfo=UTC))             # 09:30 EDT -> Feb 28, 09:30 EST
    assert dl == ny("2027-02-28", "09:30") == datetime(2027, 2, 28, 14, 30, tzinfo=UTC)
    assert z.deadline(datetime(2026, 11, 2, 14, 30, tzinfo=UTC)) == ny("2027-05-02", "09:30")


@settings(max_examples=200, deadline=None)
@given(st.dates(min_value=date(2026, 1, 1), max_value=date(2030, 12, 31)), st.integers(0, 23), st.integers(0, 59))
def test_a5_prop_deadline_keeps_the_new_york_wall_time_and_clamps(d, h, m):
    """A5.1 property: the deadline's New York wall time equals START's (except where that wall time does not exist
    on the target day, a DST gap); its date is START's date + 6 months with the month-end clamp."""
    import calendar as pycal
    start = datetime(d.year, d.month, d.day, h, m, tzinfo=NY).astimezone(UTC)
    s_ny = start.astimezone(NY)
    dl = z.deadline(start).astimezone(NY)
    mo = s_ny.month + 6
    y, mo = s_ny.year + (mo - 1) // 12, (mo - 1) % 12 + 1
    assert dl.date() == date(y, mo, min(s_ny.day, pycal.monthrange(y, mo)[1]))
    naive = datetime.combine(dl.date(), s_ny.time())
    if naive.replace(tzinfo=NY).astimezone(UTC).astimezone(NY).replace(tzinfo=None) == naive:   # not a DST gap
        assert (dl.hour, dl.minute) == (s_ny.hour, s_ny.minute)


def _seal(close_dt, trades):
    return {"close": close_dt.isoformat(), "trades": trades}


CAL_APR = cal_rows("2026-10-01", "2027-05-31", holidays=("2026-11-26", "2026-12-25", "2027-01-01", "2027-05-31"))


def test_a5_codex_probe_a_the_deadline_days_close_after_a_0930_deadline_is_ineligible():
    """A5.1 / Codex 0a58b934 probe a: START 2026-10-15 09:30 NY -> deadline 2027-04-15 09:30; with seals for the
    Apr-14 and Apr-15 closes and today Apr-16, the TIMEOUT close is Apr-14 16:00 (the last sealed close whose close
    INSTANT is <= the deadline), never Apr-15 16:00."""
    start = datetime(2026, 10, 15, 13, 30, tzinfo=UTC)
    seals = [_seal(ny("2027-04-14", "16:00"), []), _seal(ny("2027-04-15", "16:00"), [])]
    st_ = z.stop_decision(seals, start, CAL_APR, today=ny("2027-04-16", "12:00"))
    assert st_["status"] == "TIMEOUT" and st_["stop_close"] == ny("2027-04-14", "16:00").isoformat(), st_


def test_a5_an_ineligible_post_deadline_close_can_never_be_the_stop():
    """A5.1: a close after the deadline instant does not qualify as STOPPED even with >= 100 fully sold."""
    start = datetime(2026, 10, 15, 13, 30, tzinfo=UTC)
    rows = [tr(i, "A", "BUY", 1, "2027-04-14T15:00:00+00:00") for i in range(1, 101)]
    rows += [tr(100 + i, "A", "SELL", 1, "2027-04-15T15:00:00+00:00") for i in range(1, 101)]
    seals = [_seal(ny("2027-04-14", "16:00"), rows[:100]), _seal(ny("2027-04-15", "16:00"), rows)]
    st_ = z.stop_decision(seals, start, CAL_APR, today=ny("2027-04-16", "12:00"))
    assert st_["status"] == "TIMEOUT" and st_["stop_close"] == ny("2027-04-14", "16:00").isoformat(), st_


def test_a5_the_timeout_waits_for_the_last_eligible_closes_window():
    """A5.1 with v5 §9: while the last eligible close's (Apr-14) seal schedule runs (until 08:00 Apr-15) the trial
    is RUNNING; the Apr-15 window is irrelevant (that close is ineligible)."""
    start = datetime(2026, 10, 15, 13, 30, tzinfo=UTC)
    seals = [_seal(ny("2027-04-13", "16:00"), [])]
    assert z.stop_decision(seals, start, CAL_APR, today=ny("2027-04-15", "07:59"))["status"] == "RUNNING"
    st_ = z.stop_decision(seals, start, CAL_APR, today=ny("2027-04-15", "08:01"))
    assert st_["status"] == "TIMEOUT" and st_["stop_close"] == ny("2027-04-13", "16:00").isoformat()
    assert st_["missed"] == ["2027-04-14"] or "2027-04-14" in st_["missed"]


def test_a5_plan_records_the_deadline_instant_and_a_derived_calendar_range(tmp_path, monkeypatch):
    """A5.1 / mapping 4.5: plan.json records the deadline as an aware instant and the calendar request range runs
    from the plan date through the deadline date + the registered tail (covering the final lag), not a generic
    +200 days."""
    monkeypatch.setattr(c, "now_utc", lambda: datetime(2026, 10, 21, 12, tzinfo=UTC))
    start = datetime(2026, 11, 2, 14, 30, tzinfo=UTC)
    p = read(k.write_plan(tmp_path, start, "2026-10-30", ["A"], "2026-03-17"))
    assert c.aware(p["deadline"]) == ny("2027-05-02", "09:30")
    assert p["calendar_range"] == ["2026-10-21", (date(2027, 5, 2) + timedelta(days=k.CAL_TAIL_DAYS)).isoformat()]
    assert k.CAL_TAIL_DAYS >= 7


def test_a5_no_valid_seal_trial_end_is_the_last_eligible_closes_window_end(tmp_path):
    """A5.1: the NO-VALID-SEAL end instant (score timing) is the window end of the last close whose close instant
    is <= the deadline instant."""
    st_ = s1_state(tmp_path, START, score_ready=True, lots=[], seal_days=[], final_snapshot=False)
    out = tmp_path / "s1_out"
    with _Clock(st_["now"]):
        end, need_final = r._trial_end(out, read(out / "prereg.json"))
    dl = z.deadline(START_DT)
    last = [d for d in st_["calendar"] if z.open_instant(d) >= START_DT and z.close_of(d["date"], st_["calendar"]) <= dl][-1]
    assert end == z.window_end(last, st_["calendar"]) and need_final is False


# ====================================================================== A5.2 slot eligibility (Q7)
CAL = cal_rows("2026-10-01", "2027-06-30", holidays=("2026-11-26", "2026-12-25", "2027-01-01"),
               early={"2026-11-27": "13:00"})
DAY = next(d for d in CAL if d["date"] == "2026-10-15")                  # Thu, close 20:00Z
FRI = next(d for d in CAL if d["date"] == "2026-10-16")
WED_PRE_HOLIDAY = next(d for d in CAL if d["date"] == "2026-11-25")      # next session Fri 11-27 (Thanksgiving)


def test_a5_schedule_slack_is_ten_minutes_and_single_sourced():
    """A5.2: SCHEDULE_SLACK = 10 minutes, named and single-sourced in s1_seal; no other bundle module defines a
    10-minute tolerance of its own."""
    assert z.SCHEDULE_SLACK == timedelta(minutes=10)
    for name in c.BUNDLE_CODE:
        if not name.startswith("s1_") or name == "s1_seal.py":
            continue
        tree = ast.parse((HERE / name).read_text(encoding="utf-8"))
        bad = [ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.Call) and ast.unparse(n.func).endswith(
            "timedelta") and any(kw.arg == "minutes" for kw in n.keywords)]
        assert not bad, (name, bad)


def test_a5_eligible_until_is_min_of_slot_plus_slack_and_the_window_end():
    """A5.2: E = min(s + SCHEDULE_SLACK, W), W = 08:00 America/New_York on the next session day (never recomputed
    from invocation time)."""
    slots = z.schedule(DAY, CAL)
    s45 = slots[0]
    assert z.eligible_until(s45, DAY, CAL) == s45 + timedelta(minutes=10)
    w = z.window_end(DAY, CAL)
    assert w == ny("2026-10-16", "08:00") and slots[-1] == w
    assert z.eligible_until(slots[-2], DAY, CAL) == slots[-2] + timedelta(minutes=10)     # 07:00 -> 07:10
    assert z.eligible_until(slots[-1], DAY, CAL) == w                                     # 08:00 -> 08:00


@pytest.mark.parametrize("start_off,end_off,ok", [
    (0, 0, True),                    # instantaneous capture at s
    (30, 60, True),                  # inside
    (30, 600, True),                 # completion exactly at E (exact boundary) is allowed
    (30, 601, False),                # just late: end = E + 1 s
    (-1, 30, False),                 # a capture starting before s
    (601, 602, False),               # starts after E
    (60, 30, False),                 # end before start: not a capture interval
])
def test_a5_capture_eligibility_predicate_examples(start_off, end_off, ok):
    """A5.2/A5.5: s <= capture_start <= capture_end <= E, all aware instants."""
    s = z.schedule(DAY, CAL)[0]
    got = z.capture_eligible(s, DAY, CAL, s + timedelta(seconds=start_off), s + timedelta(seconds=end_off))
    assert got is ok


def test_a5_the_0800_slot_has_no_positive_duration_window_and_is_not_slid():
    """A5.3: the 08:00 slot is kept in the schedule (not slid to 08:10, not replaced by 07:50); E = W = s, so any
    capture of positive duration (or starting after 08:00) is ineligible."""
    slots = z.schedule(DAY, CAL)
    s8 = slots[-1]
    assert s8.astimezone(NY).strftime("%H:%M") == "08:00" and slots[-2].astimezone(NY).strftime("%H:%M") == "07:00"
    assert z.eligible_until(s8, DAY, CAL) == s8
    assert z.capture_eligible(s8, DAY, CAL, s8, s8 + timedelta(seconds=1)) is False
    assert z.capture_eligible(s8, DAY, CAL, s8 + timedelta(seconds=1), s8 + timedelta(seconds=2)) is False
    assert z.capture_eligible(slots[-2], DAY, CAL, slots[-2], slots[-2] + timedelta(minutes=10)) is True


def test_a5_overnight_weekend_and_holiday_windows():
    """A5.5: Friday's window runs to Monday 08:00 ET with hourly slots over the weekend; the session before a holiday
    runs to 08:00 of the next SESSION day (Thanksgiving skipped); each hourly slot is eligible for 10 minutes."""
    fri = z.schedule(FRI, CAL)
    assert z.window_end(FRI, CAL) == ny("2026-10-19", "08:00") and fri[-1] == ny("2026-10-19", "08:00")
    sat_noon = datetime(2026, 10, 17, 16, 0, tzinfo=UTC)
    assert sat_noon in fri and z.eligible_until(sat_noon, FRI, CAL) == sat_noon + timedelta(minutes=10)
    assert z.window_end(WED_PRE_HOLIDAY, CAL) == ny("2026-11-27", "08:00")


def _cap(slot, start, end, consistent=True):
    return {"scheduled": slot.isoformat(), "actual": end.isoformat(), "capture_start": start.isoformat(),
            "capture_end": end.isoformat(), "ok": True, "consistent": consistent, "projection_sha256": "h",
            "dir": "d"}


def test_a5_overlapping_retry_tolerances_are_resolved_by_slot_order_not_arrival():
    """A5.2/A5.5: slot 45's window [20:45, 20:55] overlaps slot 47's; a slot-45 capture that arrived later (20:50)
    than an eligible slot-47 one (20:47) is still THE seal (first eligible consistent capture in slot order)."""
    s = z.schedule(DAY, CAL)
    a = _cap(s[0], s[0] + timedelta(minutes=5), s[0] + timedelta(minutes=6))       # arrived second
    b = _cap(s[1], s[1] + timedelta(seconds=10), s[1] + timedelta(seconds=40))      # arrived first
    assert z.choose_seal(DAY, CAL, [b, a])["scheduled"] == s[0].isoformat()
    late = _cap(s[0], s[0] + timedelta(minutes=5), s[0] + timedelta(minutes=11))   # finished after E45
    assert z.choose_seal(DAY, CAL, [late, b])["scheduled"] == s[1].isoformat()
    assert z.choose_seal(DAY, CAL, [_cap(s[0], s[0], s[0] + timedelta(seconds=5), consistent=False), b])[
        "scheduled"] == s[1].isoformat()


# ---------------------------------------------------------------------- A5.2 in the scheduled checkpoint
class Snap:
    """take_snapshot spy whose measured capture end is `dur` after its start (the real snapshot runs inside)."""

    def __init__(self, monkeypatch, dur=timedelta(seconds=1)):
        self.calls, self.dur = 0, dur
        real = s1_snapshot.take_snapshot

        def snap(live_db, out_dir, now=c.now_utc):
            self.calls += 1
            meta = real(live_db, out_dir, now=now)
            t0 = c.aware(meta["capture_start"])
            meta["capture_end"] = (t0 + self.dur).isoformat()
            (Path(out_dir) / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
            return meta
        monkeypatch.setattr(s1_snapshot, "take_snapshot", snap)


def _registered(tmp_path):
    st_ = s1_state(tmp_path, START)
    with _Clock(START_DT - timedelta(days=1)):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    st_["ledger"].trade("A", "BUY", 10, 50.0, "2026-10-26T15:00:00+00:00")
    st_["ledger"].set_portfolio("A", 10)
    return st_


def _run(tmp_path, st_, slot, at):
    with _Clock(at):
        return ck.run_checkpoint(tmp_path, st_["ledger"].path, slot, lambda: S1_RECEIPT, lambda: dict(S1_PROCESS),
                                 tmp_path / "crash.log", now=lambda: at)


MON_CLOSE = datetime(2026, 10, 26, 20, 0, tzinfo=UTC)
S45, S47, S55 = (MON_CLOSE + timedelta(minutes=m) for m in (45, 47, 55))
SEAL_P = lambda root: root / "s1_out" / "seals" / "2026-10-26.json"     # noqa: E731


@pytest.mark.parametrize("at", [S45 - timedelta(seconds=1), S45 + timedelta(minutes=10, seconds=1),
                                S45 + timedelta(hours=3)])
def test_a5_the_clock_is_checked_before_any_capture_and_the_refused_attempt_is_preserved(tmp_path, monkeypatch, at):
    """A5.2: the actual clock must be within [s, E] BEFORE any capture; an early or late invocation takes no
    capture (zero snapshot calls) but its attempt and original scheduled time are preserved (a refused report with
    the same predicate's verdict); the slot is then consumed (a rerun of it is a duplicate)."""
    st_ = _registered(tmp_path)
    spy = Snap(monkeypatch)
    rep = _run(tmp_path, st_, S45, at)
    assert spy.calls == 0 and rep["seal"]["written"] is False and rep["capture_ok"] is False
    assert rep["late"] is True and "clock" in str(rep.get("refused")) and rep["scheduled"] == S45.isoformat()
    reports = list((tmp_path / "s1_out" / "captures" / "2026-10-26").glob("*.report.json"))
    assert len(reports) == 1 and read(reports[0])["scheduled"] == S45.isoformat()
    with pytest.raises(SystemExit, match="slot already"):
        _run(tmp_path, st_, S45, S45 + timedelta(seconds=30))
    assert spy.calls == 0


def test_a5_a_capture_finishing_after_E_never_seals_one_ending_exactly_at_E_does(tmp_path, monkeypatch):
    """A5.2/A5.5: the measured capture start/end are re-validated AFTER the capture and BEFORE any seal: started at
    s + 9 min and lasting 61 s ends at E + 1 s -> preserved, not sealed, late; a capture ending exactly at E
    (next slot) seals."""
    st_ = _registered(tmp_path)
    Snap(monkeypatch, dur=timedelta(seconds=61))
    rep = _run(tmp_path, st_, S45, S45 + timedelta(minutes=9))
    assert rep["capture_ok"] is True and rep["consistent"] is True and rep["seal"]["written"] is False, rep
    assert rep["late"] is True and not SEAL_P(tmp_path).exists()
    Snap(monkeypatch, dur=timedelta(seconds=60))
    rep = _run(tmp_path, st_, S47, S47 + timedelta(minutes=9))
    assert rep["seal"]["written"] is True and rep["late"] is False
    assert read(SEAL_P(tmp_path))["capture"]["scheduled"] == S47.isoformat()


def test_a5_codex_probe_b_the_0800_slot_finishing_at_0805_never_seals(tmp_path, monkeypatch):
    """A5.3 / Codex probe b: the final 08:00 slot run at 08:00:30 (or finishing at 08:05) never seals."""
    st_ = _registered(tmp_path)
    s8 = z.schedule(next(d for d in st_["calendar"] if d["date"] == "2026-10-26"), st_["calendar"])[-1]
    spy = Snap(monkeypatch, dur=timedelta(minutes=5))
    rep = _run(tmp_path, st_, s8, s8 + timedelta(seconds=30))
    assert rep["seal"]["written"] is False and rep["late"] is True and spy.calls == 0
    assert not SEAL_P(tmp_path).exists()


def test_a5_a_later_slot_capture_waits_for_an_unresolved_earlier_slot_then_the_earlier_one_seals(tmp_path,
                                                                                                monkeypatch):
    """A5.2: arrival order never selects the seal. Slot 47 captures (consistent) at 20:47:30 while slot 45 has no
    completed attempt and its window (to 20:55) is open: no seal yet. Slot 45 then runs (queued) at 20:50 and its
    consistent capture is THE seal (first eligible in slot order)."""
    st_ = _registered(tmp_path)
    Snap(monkeypatch)
    rep47 = _run(tmp_path, st_, S47, S47 + timedelta(seconds=30))
    assert rep47["consistent"] is True and rep47["seal"]["written"] is False and not SEAL_P(tmp_path).exists()
    assert "slot" in str(rep47.get("deferred")), rep47
    rep45 = _run(tmp_path, st_, S45, S45 + timedelta(minutes=5))
    assert rep45["seal"]["written"] is True
    assert read(SEAL_P(tmp_path))["capture"]["scheduled"] == S45.isoformat()


def test_a5_a_deferred_capture_seals_once_the_earlier_slots_window_has_passed(tmp_path, monkeypatch):
    """A5.2: slot 45 never runs; the deferred slot-47 capture becomes the seal at the first invocation after E45
    (here slot 55 at 20:55:30), never the later slot-55 capture itself."""
    st_ = _registered(tmp_path)
    Snap(monkeypatch)
    _run(tmp_path, st_, S47, S47 + timedelta(seconds=30))
    rep55 = _run(tmp_path, st_, S55, S55 + timedelta(seconds=30))
    assert rep55["seal"]["written"] is True, rep55
    assert read(SEAL_P(tmp_path))["capture"]["scheduled"] == S47.isoformat()
    assert rep55["seal"].get("from_slot") == S47.isoformat()


def test_a5_a_delayed_invocation_cannot_claim_a_later_slot(tmp_path, monkeypatch):
    """A5.2: a slot-45 invocation queued until 20:56 is refused for slot 45 (late); it never becomes a slot-47
    capture (the slot is its --scheduled argument, never recomputed from the invocation time)."""
    st_ = _registered(tmp_path)
    spy = Snap(monkeypatch)
    rep = _run(tmp_path, st_, S45, S45 + timedelta(minutes=11))
    assert rep["scheduled"] == S45.isoformat() and spy.calls == 0 and not SEAL_P(tmp_path).exists()
    names = [p.name for p in (tmp_path / "s1_out" / "captures" / "2026-10-26").iterdir()]
    assert not any("204700" in n for n in names), names


# ====================================================================== A5.4 >= 5 sessions after the AUDIT-ACK
def _audit_client(cal):
    def handler(req):
        if "calendar" in str(req.url):
            return httpx.Response(200, json=cal)
        return httpx.Response(200, json={"corporate_actions": {}, "next_page_token": None})
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def _plan_and_ack(tmp_path, monkeypatch, plan_at, ack_at, start=datetime(2026, 11, 2, 14, 30, tzinfo=UTC)):
    monkeypatch.setattr(c, "now_utc", lambda: plan_at)
    k.write_plan(tmp_path, start, "2026-10-30", ["A"], "2026-03-17")
    s1_mailbox(tmp_path, "a1", k.audit_token(tmp_path), ack_at)
    monkeypatch.setattr(c, "now_utc", lambda: ack_at + timedelta(minutes=5))


def test_a5_five_sessions_are_counted_from_the_audit_acks_recorded_time(tmp_path, monkeypatch):
    """A5.4: the >= 5 NYSE sessions before START count from the S1-AUDIT-ACK's recorded time, not from the plan's
    creation: a plan 12 days ahead whose ACK arrives 3 sessions before START aborts the audit."""
    cal = cal_rows("2026-10-21", "2027-05-31")
    _plan_and_ack(tmp_path, monkeypatch, datetime(2026, 10, 21, 12, tzinfo=UTC), datetime(2026, 10, 28, 12, tzinfo=UTC))
    with pytest.raises(SystemExit, match="ABORTED"):
        k.do_audit(tmp_path, "a1", _audit_client(cal), ("K", "S"))
    m = read(tmp_path / "s1_out" / "audit" / "manifest.json")
    assert m["outcome"] == "ABORTED" and "AUDIT-ACK" in m["error"], m


def test_a5_five_sessions_after_the_ack_exactly_pass(tmp_path, monkeypatch):
    """A5.4 boundary: exactly 5 session opens strictly between the ACK and START are enough."""
    cal = cal_rows("2026-10-21", "2027-05-31")
    # sessions with open in (ack, START): 10-26 .. 10-30 (5); the ACK is after the 10-23 open
    _plan_and_ack(tmp_path, monkeypatch, datetime(2026, 10, 21, 12, tzinfo=UTC), datetime(2026, 10, 23, 18, tzinfo=UTC))
    assert k.do_audit(tmp_path, "a1", _audit_client(cal), ("K", "S"))["outcome"] == "COMPLETE"


# ====================================================================== A6 the pinned provider calendar
def test_a6_the_audit_pins_the_calendar_source_parameters_retrieval_time_and_raw_page(tmp_path, monkeypatch):
    """A6: pinned and hashed at the audit with its source, request parameters and retrieval time; the raw page is
    bound in the manifest and calendar.json is exactly that listing."""
    cal = cal_rows("2026-10-21", "2027-05-31")
    _plan_and_ack(tmp_path, monkeypatch, datetime(2026, 10, 21, 12, tzinfo=UTC), datetime(2026, 10, 21, 13, tzinfo=UTC))
    m = k.do_audit(tmp_path, "a1", _audit_client(cal), ("K", "S"))
    out = tmp_path / "s1_out"
    src = read(out / "audit" / "calendar_source.json")
    plan = read(out / "plan.json")
    assert src["source"] == c.CAL_URL == k.CAL_URL
    assert src["params"] == {"start": plan["calendar_range"][0], "end": plan["calendar_range"][1],
                             "date_type": "TRADING"}
    assert c.aware(src["retrieved_utc"]) == datetime(2026, 10, 21, 13, 5, tzinfo=UTC)
    assert m["pages"][src["page"]] == src["page_sha256"] == c.sha256_file(out / src["page"])
    assert read(out / "audit" / "calendar.json") == cal and "calendar_source.json" in m["files"]


@pytest.mark.parametrize("mutate,why", [
    (lambda cal: cal[:5] + [cal[6], cal[5]] + cal[7:], "order"),                          # listing out of order
    (lambda cal: cal[:5] + [cal[5]] + cal[5:], "duplicate"),
    (lambda cal: cal[:5] + [dict(cal[5], open="16:00", close="09:30")] + cal[6:], "open is not before close"),
    (lambda cal: [d for d in cal if d["date"] > "2026-10-30"], "opening close"),           # misses the opening close
    (lambda cal: [d for d in cal if d["date"] <= "2027-05-04"], "deadline"),               # < 3 sessions after
])
def test_a6_completeness_is_checked_against_the_pinned_listing(tmp_path, monkeypatch, mutate, why):
    """A6: ordered (as listed), unique, open < close, covering the session before START (the opening close) through
    the deadline + the final lag; any listed gap or inconsistency aborts the audit attempt."""
    cal = mutate(cal_rows("2026-10-21", "2027-05-31"))
    _plan_and_ack(tmp_path, monkeypatch, datetime(2026, 10, 21, 12, tzinfo=UTC), datetime(2026, 10, 21, 13, tzinfo=UTC))
    with pytest.raises(SystemExit, match="ABORTED"):
        k.do_audit(tmp_path, "a1", _audit_client(cal), ("K", "S"))
    m = read(tmp_path / "s1_out" / "audit" / "manifest.json")
    assert m["outcome"] == "ABORTED" and why in m["error"], m["error"]


def test_a6_special_and_early_closes_come_from_the_providers_listing():
    """A6: closes come from the provider's open/close times, never a weekday-minus-holidays rule: an early 13:00
    close is that session's close instant and its seal schedule starts at 13:45."""
    fri = next(d for d in CAL if d["date"] == "2026-11-27")
    assert z.close_of("2026-11-27", CAL) == ny("2026-11-27", "13:00")
    assert z.schedule(fri, CAL)[0] == ny("2026-11-27", "13:45")


def test_a6_a_dropped_session_relative_to_the_pinned_listing_refuses(tmp_path, monkeypatch):
    """A6 (refusal path only): a calendar in use that drops a session of the pinned listing is refused - at the
    checkpoint (before any capture) and at the score (ABORTED-INVALID); the design claims no independent NYSE
    calendar proof beyond the pinned listing. A3 Task 5 (intended, F0.6/F1 + OQ-19): the checkpoint's detection
    commits TRIAL-INVALID, so the score then refuses with no work (no ABORTED-INVALID record)."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    pp = out / "prereg.json"
    pr = read(pp)
    pr["calendar"] = [d for d in pr["calendar"] if d["date"] != "2026-10-28"]
    pp.write_text(json.dumps(pr), encoding="utf-8")
    # (fix round 2, B3.3: an edited registered prereg is first the persistent "registration artifact" abort; the
    # score still names the calendar)
    with pytest.raises(SystemExit, match="registration artifact"):
        _run(tmp_path, st_, datetime(2026, 10, 29, 20, 45, tzinfo=UTC), datetime(2026, 10, 29, 20, 45, 30, tzinfo=UTC))
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    with pytest.raises(t.Refusal, match=r"trial INVALID \(reason/registration-artifact\)"):   # A3 F0.6/F1: no score
        r.score(tmp_path, "score-ack")
    assert not (out / "score").exists()


def test_a6_the_disclosed_calendar_limitation_is_in_the_build_evidence():
    """A6: the disclosed limitation (no independent NYSE calendar proof beyond the pinned provider listing) is
    stated in S1_BUILD_EVIDENCE.md."""
    text = (HERE / "s1_evidence" / "S1_BUILD_EVIDENCE.md").read_text(encoding="utf-8")
    assert "pinned provider" in text and "limitation" in text.lower() and "/v2/calendar" in text
