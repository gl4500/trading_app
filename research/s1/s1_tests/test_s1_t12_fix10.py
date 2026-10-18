"""Task 12 fix round 10 (re-review 8 m-1): EARLIEST_CLOSE_NY made self-enforcing. Written BEFORE the fix;
behavioural RED in s1_evidence/t12_fix10_red.txt. Synthetic only: httpx MockTransport for the provider, tmp_path
mailbox; no network, live DB or scheduler."""
import pytest

import s1_collect as k
from test_s1_collect import KEYS, audit_with_calendar, fixed_clock, full_calendar, manifest_of  # noqa: F401


def _with_close(day, close):
    return [dict(x, close=close) if x["date"] == day else x for x in full_calendar()]


@pytest.mark.parametrize("day", ["2026-10-23", "2026-11-27", "2027-05-14"])
def test_m1_a_session_closing_before_the_earliest_early_close_refuses_the_audit(tmp_path, day):
    """Re-review 8 m-1: the clock anchor assumes no session closes before EARLIEST_CLOSE_NY (13:00 America/New_York).
    A fetched provider listing with any session in the plan's calendar_range closing earlier (here 12:59, on the
    opening close, a mid-trial day and the last week of calendar_range) makes the audit fail closed: the attempt is preserved as
    ABORTED (Structural, the reason recorded), no COMPLETE manifest exists, so nothing ACK-dependent can follow."""
    cl = audit_with_calendar(tmp_path, _with_close(day, "12:59"))
    with pytest.raises(SystemExit):
        k.do_audit(tmp_path, "a1", cl, KEYS)
    m = manifest_of(tmp_path, "audit")
    assert m["outcome"] == "ABORTED" and m["error_type"] == "Structural", m
    assert "earliest" in m["error"] and day in m["error"], m["error"]


def test_m1_guard_a_session_closing_exactly_at_the_earliest_early_close_is_accepted(tmp_path):
    """m-1 guard (passes before and after): a 13:00 early close (the boundary) is a valid session."""
    cl = audit_with_calendar(tmp_path, _with_close("2026-11-27", "13:00"))
    try:                                                 # (strengthened after the mutant run, A10.2: a refusal is an
        m = k.do_audit(tmp_path, "a1", cl, KEYS)         # assertion failure, not an escaping SystemExit)
    except SystemExit as e:
        pytest.fail(f"a 13:00 early close was refused: {e}")
    assert m["outcome"] == "COMPLETE", m
