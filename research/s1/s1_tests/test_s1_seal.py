from datetime import date, datetime, timedelta, timezone

import pytest
import s1_seal as z
from test_s1_books import tr

UTC = timezone.utc


def cal():
    out, d = [], date(2026, 10, 1)
    while d <= date(2027, 6, 30):
        if d.weekday() < 5 and d.isoformat() not in ("2026-11-26", "2026-12-25", "2027-01-01", "2027-05-31"):
            out.append({"date": d.isoformat(), "open": "09:30",
                        "close": "13:00" if d.isoformat() == "2026-11-27" else "16:00"})
        d += timedelta(days=1)
    return out


CAL = cal()
DAY = next(d for d in CAL if d["date"] == "2026-10-15")


def test_schedule_is_fixed_offsets_then_hourly_to_0800_next_session():
    s = z.schedule(DAY, CAL)
    close = datetime(2026, 10, 15, 20, 0, tzinfo=UTC)                      # 16:00 EDT
    assert s[:6] == [close + timedelta(minutes=m) for m in (45, 47, 49, 51, 53, 55)]
    assert s[6] == datetime(2026, 10, 15, 21, 0, tzinfo=UTC) and s[-1] == datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
    assert all(b > a for a, b in zip(s, s[1:]))


def cap(minute_offset, ok=True, consistent=True, late=0):
    close = datetime(2026, 10, 15, 20, 0, tzinfo=UTC)
    sch = close + timedelta(minutes=minute_offset)
    return {"scheduled": sch.isoformat(), "actual": (sch + timedelta(minutes=late)).isoformat(), "ok": ok,
            "consistent": consistent, "projection_sha256": "h", "dir": "d"}


def test_capture_between_trade_and_portfolio_commit_is_inconsistent_and_retried():    # example 1
    s = z.choose_seal(DAY, CAL, [cap(45, consistent=False), cap(47, consistent=True)])
    assert s["scheduled"] == cap(47)["scheduled"]


def test_late_capture_outside_the_registered_slot_cannot_seal():                     # Review Focus 3
    assert z.choose_seal(DAY, CAL, [cap(45, late=180)]) is None


def test_no_consistent_capture_means_unsealed():
    assert z.choose_seal(DAY, CAL, [cap(45, consistent=False), cap(47, ok=False)]) is None


def test_trade_stored_after_close_excluded_from_as_of_rows():                          # example 2
    t = [tr(1, "A", "BUY", 10, 50, 5), {**tr(2, "A", "SELL", 10, 55, 5), "ts": "2026-10-15T20:30:00+00:00"}]
    start = datetime(2026, 10, 14, 13, 30, tzinfo=UTC)
    assert z.count_sold(t, start, datetime(2026, 10, 15, 20, 0, tzinfo=UTC)) == 0


def test_backdated_row_invalidates():                                                   # example 7
    p1 = {"trades": [tr(1, "A", "BUY", 10, 50, 5)]}
    seals = [{"close": "2026-10-15T20:00:00+00:00", "fence": z.fence(p1), "max_id": 1}]
    p2 = {"trades": p1["trades"] + [{**tr(2, "A", "SELL", 1, 55, 5), "ts": "2026-10-15T19:00:00+00:00"}]}
    assert any("backdated" in v for v in z.check_fences(seals, p2))
    p3 = {"trades": [{**p1["trades"][0], "shares": 9}]}
    assert any("changed" in v for v in z.check_fences(seals, p3))
    assert any("deleted" in v for v in z.check_fences(seals, {"trades": []}))


def test_executed_before_start_stored_after_is_cohort():                                # example 8
    start = datetime(2026, 10, 14, 13, 30, tzinfo=UTC)
    t = [{**tr(1, "A", "BUY", 1, 50), "ts": "2026-10-14T13:30:00.200000+00:00"}]
    assert [r["id"] for r in z.cohort(t, start, datetime(2026, 10, 15, 20, 0, tzinfo=UTC))] == [1]


def test_two_utc_spellings_give_the_same_cohort():                                      # Review Focus 1
    start = datetime(2026, 10, 14, 13, 30, tzinfo=UTC)
    a = [{**tr(1, "A", "BUY", 1, 50), "ts": "2026-10-14T13:30:00Z"}]
    b = [{**tr(1, "A", "BUY", 1, 50), "ts": "2026-10-14T13:30:00+00:00"}]
    c_ = datetime(2026, 10, 15, 20, 0, tzinfo=UTC)
    assert z.cohort(a, start, c_) == z.cohort(b, start, c_)


def test_bridge_rows_update_opening_books_not_cohort():                                 # example 19
    start = datetime(2026, 10, 16, 13, 30, tzinfo=UTC)
    t = [tr(1, "A", "BUY", 10, 50, 5), {**tr(2, "NEW", "BUY", 5, 20), "ts": "2026-10-16T00:00:00+00:00"},
         {**tr(3, "A", "SELL", 4, 51), "ts": "2026-10-16T00:00:00+00:00"}]
    bridge, era = z.split_bridge(t, start)
    assert [r["id"] for r in bridge] == [1, 2, 3] and era == []


def _seal(day_iso, trades):
    return {"close": z.close_of(day_iso, CAL).isoformat(), "fence": {}, "max_id": 0, "trades": trades}


TODAY = datetime(2026, 10, 20, 12, tzinfo=UTC)


def test_overshoot_stops_with_all_entries():                                            # example 13
    """Amended by controller ruling (Task 3 fix round 1): the plan test relied on the real clock."""
    start = datetime(2026, 10, 14, 13, 30, tzinfo=UTC)
    t = []
    for i in range(103):
        t += [{**tr(2 * i + 1, f"S{i}", "BUY", 1, 10), "ts": "2026-10-14T15:00:00+00:00"},
              {**tr(2 * i + 2, f"S{i}", "SELL", 1, 11), "ts": "2026-10-15T15:00:00+00:00"}]
    t.append({**tr(999, "OPEN", "BUY", 1, 10), "ts": "2026-10-15T15:30:00+00:00"})
    d = z.stop_decision([_seal("2026-10-14", t[:0]), _seal("2026-10-15", t)], start, CAL, today=TODAY)
    assert d["status"] == "STOPPED" and d["stop_close"] == z.close_of("2026-10-15", CAL).isoformat()
    assert len(z.cohort(t, start, z.close_of("2026-10-15", CAL))) == 104


def test_unsealed_qualifying_close_is_not_the_stop():                                   # example 14
    """Amended by controller ruling (Task 3 fix round 1): the plan test relied on the real clock."""
    start = datetime(2026, 10, 14, 13, 30, tzinfo=UTC)
    t = []
    for i in range(100):
        t += [{**tr(2 * i + 1, f"S{i}", "BUY", 1, 10), "ts": "2026-10-14T15:00:00+00:00"},
              {**tr(2 * i + 2, f"S{i}", "SELL", 1, 11), "ts": "2026-10-15T15:00:00+00:00"}]
    d = z.stop_decision([_seal("2026-10-16", t)], start, CAL, today=TODAY)  # 10-15 unsealed
    assert d["stop_close"] == z.close_of("2026-10-16", CAL).isoformat()
    assert "2026-10-15" in d["missed"]


@pytest.mark.parametrize("start,want", [(datetime(2026, 8, 31, 13, 30, tzinfo=UTC), date(2027, 2, 28)),
                                        (datetime(2026, 10, 14, 13, 30, tzinfo=UTC), date(2027, 4, 14))])
def test_deadline_calendar_months_with_month_end(start, want):
    assert z.deadline(start) == want


def test_deadline_holiday_month_end_and_no_valid_seal():                                # example 15
    start = datetime(2026, 11, 2, 14, 30, tzinfo=UTC)
    cal_short = [d for d in CAL if d["date"] <= "2027-05-31"]
    d = z.stop_decision([], start, cal_short, today=datetime(2027, 6, 1, 12, tzinfo=UTC))
    assert d["status"] == "NO-VALID-SEAL"
    few = [_seal("2026-11-02", [])]
    d = z.stop_decision(few, start, cal_short, today=datetime(2027, 6, 1, 12, tzinfo=UTC))
    assert d["status"] == "TIMEOUT" and d["stop_close"] == z.close_of("2026-11-02", CAL).isoformat()


def test_no_trades_for_weeks_keeps_running():                                           # Review Focus 5
    start = datetime(2026, 10, 14, 13, 30, tzinfo=UTC)
    d = z.stop_decision([_seal("2026-10-15", []), _seal("2026-10-16", [])], start, CAL,
                        today=datetime(2026, 10, 17, 12, tzinfo=UTC))
    assert d["status"] == "RUNNING"


from hypothesis import given, settings, strategies as st


@settings(max_examples=300, deadline=None)
@given(st.dates(min_value=date(2026, 1, 1), max_value=date(2030, 12, 31)))
def test_prop_deadline_is_six_calendar_months_clamped(d):
    got = z.deadline(datetime(d.year, d.month, d.day, 14, tzinfo=UTC))
    m = d.month + 6
    y, m = d.year + (m - 1) // 12, (m - 1) % 12 + 1
    import calendar as pycal
    assert got == date(y, m, min(d.day, pycal.monthrange(y, m)[1]))


def test_schedule_across_est_and_early_close_retrospective():
    """Retrospective (added after the code): EST (-5) and the 13:00 early close shift the fixed offsets and the
    08:00 New York end of the window by the right UTC amount."""
    day = next(d for d in CAL if d["date"] == "2026-11-27")                 # early close, EST
    s = z.schedule(day, CAL)
    close = datetime(2026, 11, 27, 18, 0, tzinfo=UTC)                       # 13:00 EST
    assert s[0] == close + timedelta(minutes=45) and s[6] == datetime(2026, 11, 27, 19, 0, tzinfo=UTC)
    assert s[-1] == datetime(2026, 11, 30, 13, 0, tzinfo=UTC)               # 08:00 EST Monday
    assert z.close_of("2026-11-27", CAL) == close and z.close_of("2026-11-27", CAL).utcoffset() == timedelta(0)


R = "Retrospective (Task 3 review fix round 1)"


def test_seal_after_today_raises_and_open_window_is_not_missed():
    """Retrospective (Task 3 review fix round 1): a seal ahead of the clock is a bad record; an unfinished
    window is never counted as missed."""
    start = datetime(2026, 10, 14, 13, 30, tzinfo=UTC)
    with pytest.raises(ValueError, match="after today"):
        z.stop_decision([_seal("2026-10-16", [])], start, CAL, today=datetime(2026, 10, 15, 12, tzinfo=UTC))
    d = z.stop_decision([], start, CAL, today=datetime(2026, 10, 15, 21, tzinfo=UTC))     # 10-15 window open
    assert d["missed"] == ["2026-10-14"] and d["status"] == "RUNNING"
    with pytest.raises(TypeError):
        z.stop_decision([], start, CAL)


def test_backdating_is_checked_per_seal():
    """Retrospective (Task 3 review fix round 1): row stored before C1 but absent from C1's seal is a violation
    even though C2's seal contains it."""
    r1 = tr(1, "A", "BUY", 10, 50, 5)
    r2 = {**tr(2, "A", "BUY", 1, 50, 5), "ts": "2026-10-05T19:00:00+00:00"}
    s1 = {"close": "2026-10-05T20:00:00+00:00", "fence": z.fence({"trades": [r1]}), "max_id": 1}
    s2 = {"close": "2026-10-06T20:00:00+00:00", "fence": z.fence({"trades": [r1, r2]}), "max_id": 2}
    v = z.check_fences([s1, s2], {"trades": [r1, r2]})
    assert any("backdated" in x for x in v)


def test_choose_seal_prefers_slot_order_within_slack():
    """Retrospective (Task 3 review fix round 1): slot 45 taken at minute 54 beats slot 47 taken at 47."""
    s = z.choose_seal(DAY, CAL, [cap(47), cap(45, late=9)])
    assert s["scheduled"] == cap(45)["scheduled"]


def test_reversed_calendar_gives_same_window_and_duplicates_raise():
    """Retrospective (Task 3 review fix round 1)."""
    assert z.window_end(DAY, list(reversed(CAL))) == z.window_end(DAY, CAL)
    assert z.schedule(DAY, list(reversed(CAL))) == z.schedule(DAY, CAL)
    with pytest.raises(ValueError, match="duplicate"):
        z.window_end(DAY, CAL + [CAL[0]])


def test_duplicate_seals_for_one_close_raise():
    """Retrospective (Task 3 review fix round 1)."""
    start = datetime(2026, 10, 14, 13, 30, tzinfo=UTC)
    with pytest.raises(ValueError, match="two seals"):
        z.stop_decision([_seal("2026-10-15", []), _seal("2026-10-15", [])], start, CAL, today=TODAY)


def test_dst_fall_back_window():
    """Retrospective (Task 3 review fix round 1): 2026-10-30 close, window crosses 2026-11-01 fall-back."""
    day = next(d for d in CAL if d["date"] == "2026-10-30")
    s = z.schedule(day, CAL)
    assert len(s) == len(set(s)) and all(b > a for a, b in zip(s, s[1:]))
    assert all(b - a == timedelta(hours=1) for a, b in zip(s[6:], s[7:]))
    assert s[-1] == datetime(2026, 11, 2, 13, 0, tzinfo=UTC)


def test_string_fence_keys_after_json_roundtrip():
    """Retrospective (Task 3 review fix round 1)."""
    import json
    p1 = {"trades": [tr(1, "A", "BUY", 10, 50, 5), tr(2, "A", "BUY", 1, 50, 5)]}
    seal = json.loads(json.dumps({"close": "2026-10-15T20:00:00+00:00", "fence": z.fence(p1), "max_id": 2}))
    assert any("deleted" in v for v in z.check_fences([seal], {"trades": [p1["trades"][0]]}))
    assert any("changed" in v for v in z.check_fences([seal], {"trades": [{**p1["trades"][0], "shares": 9}, p1["trades"][1]]}))
    new_low = {**tr(0, "B", "BUY", 1, 50, 5), "ts": "2026-10-16T10:00:00+00:00"}
    v = z.check_fences([seal], {"trades": p1["trades"] + [new_low]})
    assert any("below previous max" in x for x in v)
    assert z.check_fences([seal], p1) == []


def test_calendar_without_next_session_raises():
    """Retrospective (Task 3 review fix round 1)."""
    with pytest.raises(ValueError, match="calendar ends"):
        z.window_end(CAL[-1], CAL)


# ---------------------------------------------------------------- Task 9 mutant survivors (retrospective tests)
def test_capture_at_a_non_registered_instant_cannot_seal():
    """Retrospective (Task 9 mutant survivor "choose_seal skips slot membership"): a consistent, on-time capture
    whose scheduled instant (close + 46 min) is not a registered slot never seals."""
    assert z.choose_seal(DAY, CAL, [cap(46)]) is None
    assert z.choose_seal(DAY, CAL, [cap(46), cap(47)])["scheduled"] == cap(47)["scheduled"]


def test_check_bridge_compares_every_post_start_seal_with_the_first():
    """Retrospective (Task 9 mutant survivor "bridge hash not compared across seals"): a later post-START seal whose
    bridge hash differs from the first one is a violation even when the recomputed bridge equals the first."""
    start = datetime(2026, 10, 14, 13, 30, tzinfo=UTC)
    trades = [tr(1, "A", "BUY", 10, 50, 3), tr(2, "A", "BUY", 5, 51, 5)]
    h = z.bridge_record(trades, start, None)["bridge_sha256"]
    seals = [{"close": "2026-10-14T20:00:00+00:00", "bridge": {"bridge_sha256": h}},
             {"close": "2026-10-15T20:00:00+00:00", "bridge": {"bridge_sha256": "0" * 64}}]
    assert z.check_bridge(seals[:1], trades, start) == []
    v = z.check_bridge(seals, trades, start)
    assert len(v) == 1 and "2026-10-15T20:00:00+00:00" in v[0] and "differs from the first post-START seal" in v[0]


# ---------------------------------------------------------------- Task 9 round 2: Cosmic Ray survivors (retrospective)
START_T9 = datetime(2026, 10, 14, 13, 30, tzinfo=UTC)
C15 = datetime(2026, 10, 15, 20, 0, tzinfo=UTC)


def _sold_lots(n, buy_ts="2026-10-14T15:00:00+00:00", sell_ts="2026-10-15T15:00:00+00:00"):
    t = []
    for i in range(n):
        t += [{**tr(2 * i + 1, f"S{i}", "BUY", 1, 10), "ts": buy_ts},
              {**tr(2 * i + 2, f"S{i}", "SELL", 1, 11), "ts": sell_ts}]
    return t


def test_cr_slack_boundary_and_capture_before_its_slot():
    """Retrospective (Task 9 CR survivors s1_seal:11/68): a capture exactly SCHEDULE_SLACK (10 min) after its slot
    seals; one taken before its slot never does."""
    assert z.choose_seal(DAY, CAL, [cap(45, late=10)])["scheduled"] == cap(45)["scheduled"]
    assert z.choose_seal(DAY, CAL, [cap(45, late=-1)]) is None


def test_cr_stop_threshold_is_exactly_100_sold():
    """Retrospective (Task 9 CR survivor s1_seal:12 STOP_N): 99 sold lots keep running, 100 stop."""
    for n, want in ((99, "RUNNING"), (100, "STOPPED")):
        d = z.stop_decision([_seal("2026-10-15", _sold_lots(n))], START_T9, CAL,
                            today=datetime(2026, 10, 16, 0, tzinfo=UTC))
        assert d["status"] == want, (n, d)


def test_cr_close_of_and_duplicate_check_do_not_depend_on_order_or_string_identity():
    """Retrospective (Task 9 CR survivors s1_seal:30/37): close_of finds the exact date in an unsorted calendar; a
    duplicate date is detected by value even when the two strings are distinct objects."""
    assert z.close_of("2026-10-15", list(reversed(CAL))) == C15
    a = {"date": "".join(["2026-10-", "15"]), "open": "09:30", "close": "16:00"}
    b = {"date": "".join(["2026-10", "-15"]), "open": "09:30", "close": "16:00"}
    assert a["date"] is not b["date"]
    with pytest.raises(ValueError, match="duplicate"):
        z.window_end(DAY, [a, b] + [d for d in CAL if d["date"] != "2026-10-15"])


def test_cr_hourly_slots_start_after_the_last_offset_for_any_close_minute():
    """Retrospective (Task 9 CR survivors s1_seal:56): the first hourly slot is the first full hour after the LAST
    fixed offset (close + 55 min), also for a close that is not on the hour."""
    day = {"date": "2026-10-15", "open": "09:30", "close": "16:06"}
    cal = [day if d["date"] == "2026-10-15" else d for d in CAL]
    s = z.schedule(day, cal)
    assert all(b > a for a, b in zip(s, s[1:]))
    assert s[6] == datetime(2026, 10, 15, 22, 0, tzinfo=UTC)                 # last offset 21:01Z + 1 h -> 22:00Z


def test_cr_changed_row_detected_whichever_way_its_hash_moves():
    """Retrospective (Task 9 CR survivor s1_seal:91): a changed row is flagged whether its new hash sorts above or
    below the sealed one."""
    row = tr(1, "A", "BUY", 10, 50, 5)
    seal = {"close": "2026-10-15T20:00:00+00:00", "fence": z.fence({"trades": [row]}), "max_id": 1}
    h = seal["fence"][1]
    lower = next({**row, "shares": 10 + k} for k in range(1, 200) if z._row_hash({**row, "shares": 10 + k}) < h)
    higher = next({**row, "shares": 10 + k} for k in range(1, 200) if z._row_hash({**row, "shares": 10 + k}) > h)
    for changed in (lower, higher):
        assert z.check_fences([seal], {"trades": [changed]}) == ["sealed row 1 changed"]


def test_cr_row_stored_exactly_at_a_sealed_close_but_unfenced_is_backdated():
    """Retrospective (Task 9 CR survivor s1_seal:97): stored time == the sealed close is "by this close"."""
    r1 = tr(1, "A", "BUY", 10, 50, 5)
    seal = {"close": "2026-10-15T20:00:00+00:00", "fence": z.fence({"trades": [r1]}), "max_id": 1}
    r2 = {**tr(2, "A", "BUY", 1, 50, 5), "ts": "2026-10-15T20:00:00+00:00"}
    assert any("row 2 backdated" in v for v in z.check_fences([seal], {"trades": [r1, r2]}))


def test_cr_post_opening_rows_are_strictly_after_the_opening_close():
    """Retrospective (Task 9 CR survivors s1_seal:126): post_opening_row_ids = bridge rows stored strictly after the
    opening close (before, at, after)."""
    oc = datetime(2026, 10, 13, 20, 0, tzinfo=UTC)
    rows = [{**tr(1, "A", "BUY", 1, 50), "ts": "2026-10-13T19:00:00+00:00"},
            {**tr(2, "A", "BUY", 1, 50), "ts": "2026-10-13T20:00:00+00:00"},
            {**tr(3, "A", "BUY", 1, 50), "ts": "2026-10-13T21:00:00+00:00"}]
    assert z.bridge_record(rows, START_T9, oc)["post_opening_row_ids"] == [3]


def test_cr_seal_of_a_close_exactly_at_start_is_post_start():
    """Retrospective (Task 9 CR survivor s1_seal:142)."""
    s = {"close": START_T9.isoformat()}
    assert z.post_start_seals([s], START_T9) == [s]


def test_cr_check_bridge_messages_and_hash_direction():
    """Retrospective (Task 9 CR survivors s1_seal:153/157/158/160-162): a post-START bridge without a hash is "no
    bridge record"; differing hashes are flagged in either sort direction and named against the FIRST seal; the
    recomputed-bridge message carries both 12-char prefixes."""
    trades = [tr(1, "A", "BUY", 10, 50, 3), tr(2, "A", "BUY", 5, 51, 5)]
    h = z.bridge_record(trades, START_T9, None)["bridge_sha256"]
    first = {"close": "2026-10-14T20:00:00+00:00", "bridge": {"bridge_sha256": h}}
    assert z.check_bridge([first, {"close": "2026-10-15T20:00:00+00:00", "bridge": {}}], trades, START_T9) == \
        ["post-START seal 2026-10-15T20:00:00+00:00: no bridge record"]
    for other in ("0" * 64, "f" * 64):
        seals = [first, {"close": "2026-10-15T20:00:00+00:00", "bridge": {"bridge_sha256": h}},
                 {"close": "2026-10-16T20:00:00+00:00", "bridge": {"bridge_sha256": other}}]
        assert z.check_bridge(seals, trades, START_T9) == [
            "post-START seal 2026-10-16T20:00:00+00:00: bridge hash differs from the first post-START seal "
            "2026-10-14T20:00:00+00:00"]
    for want in ("0" * 64, "f" * 64):
        seals = [{"close": "2026-10-14T20:00:00+00:00", "bridge": {"bridge_sha256": want}},
                 {"close": "2026-10-15T20:00:00+00:00", "bridge": {"bridge_sha256": want}}]
        assert z.check_bridge(seals, trades, START_T9) == [
            f"bridge (pre-START rows) changed since the first post-START seal 2026-10-14T20:00:00+00:00: "
            f"{h[:12]} != {want[:12]}"]


def test_cr_cohort_and_sold_counts_include_rows_exactly_at_start_and_close():
    """Retrospective (Task 9 CR survivors s1_seal:170/174): a BUY stored exactly at START and one exactly at the
    close are cohort entries; a SELL stored exactly at the close counts as sold by that close."""
    t = [{**tr(1, "A", "BUY", 1, 50), "ts": START_T9.isoformat()},
         {**tr(2, "B", "BUY", 1, 50), "ts": C15.isoformat()},
         {**tr(3, "A", "SELL", 1, 51), "ts": C15.isoformat()}]
    assert [x["id"] for x in z.cohort(t, START_T9, C15)] == [1, 2]
    assert z.count_sold(t, START_T9, C15) == 1


def test_cr_stop_decision_today_boundaries():
    """Retrospective (Task 9 CR survivors s1_seal:194/203/207/212/213): a seal whose close == today is allowed and
    evaluated; a window ending exactly at today is not yet missed; the trial is RUNNING until the LAST eligible
    session's window has passed (inclusive), not the second-to-last."""
    t = _sold_lots(100)
    d = z.stop_decision([_seal("2026-10-15", t)], START_T9, CAL, today=C15)
    assert d["status"] == "STOPPED" and d["stop_close"] == C15.isoformat()
    we14 = z.window_end(next(x for x in CAL if x["date"] == "2026-10-14"), CAL)
    assert z.stop_decision([], START_T9, CAL, today=we14)["missed"] == []
    dl = z.deadline(START_T9).isoformat()
    elig = [x for x in CAL if z.open_instant(x) >= START_T9 and x["date"] <= dl]
    last_end, prev_end = z.window_end(elig[-1], CAL), z.window_end(elig[-2], CAL)
    assert z.stop_decision([], START_T9, CAL, today=prev_end + timedelta(minutes=1))["status"] == "RUNNING"
    assert z.stop_decision([], START_T9, CAL, today=last_end)["status"] == "RUNNING"
    assert z.stop_decision([], START_T9, CAL, today=last_end + timedelta(minutes=1))["status"] == "NO-VALID-SEAL"


def test_cr_deadline_session_itself_is_eligible():
    """Retrospective (Task 9 CR survivor s1_seal:199): the deadline day's close can be the stop."""
    dl = z.deadline(START_T9).isoformat()
    assert any(x["date"] == dl for x in CAL)
    t = _sold_lots(100, buy_ts="2027-04-13T15:00:00+00:00", sell_ts="2027-04-14T15:00:00+00:00")
    d = z.stop_decision([_seal(dl, t)], START_T9, CAL, today=datetime(2027, 4, 20, tzinfo=UTC))
    assert d["status"] == "STOPPED" and d["stop_close"] == z.close_of(dl, CAL).isoformat()
