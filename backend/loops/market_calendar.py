"""NYSE market calendar helpers — open/close detection, holidays, ET clock.

Extracted from main.py for issue #67. Used by trading_loop, auto_scan_loop,
news_sentinel_loop, and the /api/sentinel endpoint.

Test-compatibility note: `_get_market_status`, `_market_is_open`, and
`_minutes_until_open` look up `_et_now` via the `main` module so that
existing `patch("main._et_now", ...)` tests continue to work.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _et_now() -> datetime:
    """Return the current time as a timezone-aware datetime in US Eastern Time
    (EST/EDT). DST is computed from first principles — no pytz or tzdata required.

    US DST rule:
      EDT (UTC-4): 2nd Sunday of March at 02:00 local → 1st Sunday of November at 02:00 local
      EST (UTC-5): all other times
    """
    utc_now = datetime.now(timezone.utc)

    def _nth_weekday(year: int, month: int, weekday: int, n: int) -> datetime:
        """Return the nth occurrence (1-based) of weekday (Mon=0…Sun=6) in the given month."""
        first = datetime(year, month, 1, tzinfo=timezone.utc)
        delta = (weekday - first.weekday()) % 7
        return first + timedelta(days=delta + (n - 1) * 7)

    y = utc_now.year
    # 2nd Sunday of March 02:00 EST = 07:00 UTC
    dst_start = _nth_weekday(y, 3, 6, 2).replace(hour=7)
    # 1st Sunday of November 02:00 EDT = 06:00 UTC
    dst_end   = _nth_weekday(y, 11, 6, 1).replace(hour=6)

    offset = timedelta(hours=-4) if dst_start <= utc_now < dst_end else timedelta(hours=-5)
    return utc_now.astimezone(timezone(offset))


def _nyse_holidays(year: int) -> set:
    """Return the set of (month, day) NYSE holidays for the given year.

    All floating holidays are computed exactly — no hardcoded dates.

    Holiday schedule:
      New Year's Day     — Jan 1 (observed Mon if Sun, Fri if Sat)
      MLK Day            — 3rd Monday of January
      Presidents Day     — 3rd Monday of February
      Good Friday        — Easter Sunday minus 2 days
      Memorial Day       — last Monday of May
      Juneteenth         — Jun 19 (observed Mon if Sun, Fri if Sat)
      Independence Day   — Jul 4  (observed Mon if Sun, Fri if Sat)
      Labor Day          — 1st Monday of September
      Thanksgiving       — 4th Thursday of November
      Christmas          — Dec 25 (observed Mon if Sun, Fri if Sat)
    """

    def _nth_weekday(month: int, weekday: int, n: int) -> tuple:
        first = datetime(year, month, 1)
        delta = (weekday - first.weekday()) % 7
        d = first + timedelta(days=delta + (n - 1) * 7)
        return (d.month, d.day)

    def _last_weekday(month: int, weekday: int) -> tuple:
        """Last occurrence of weekday in month."""
        # Start from end of month and walk back
        import calendar
        last_day = calendar.monthrange(year, month)[1]
        d = datetime(year, month, last_day)
        delta = (d.weekday() - weekday) % 7
        d -= timedelta(days=delta)
        return (d.month, d.day)

    def _observed(month: int, day: int) -> tuple:
        """NYSE observance rule: if holiday falls on Sat → Fri; Sun → Mon."""
        d = datetime(year, month, day)
        if d.weekday() == 5:   # Saturday → Friday
            d -= timedelta(days=1)
        elif d.weekday() == 6:  # Sunday → Monday
            d += timedelta(days=1)
        return (d.month, d.day)

    def _easter(y: int) -> datetime:
        """Anonymous Gregorian algorithm for Easter Sunday."""
        a = y % 19
        b, c = divmod(y, 100)
        d, e = divmod(b, 4)
        f = (b + 8) // 25
        g = (b - f + 1) // 3
        h = (19 * a + b - d - g + 15) % 30
        i, k = divmod(c, 4)
        l = (32 + 2 * e + 2 * i - h - k) % 7
        m = (a + 11 * h + 22 * l) // 451
        month = (h + l - 7 * m + 114) // 31
        day   = (h + l - 7 * m + 114) % 31 + 1
        return datetime(y, month, day)

    easter = _easter(year)
    good_friday = easter - timedelta(days=2)

    return {
        _observed(1, 1),                        # New Year's Day
        _nth_weekday(1, 0, 3),                  # MLK Day (3rd Mon Jan)
        _nth_weekday(2, 0, 3),                  # Presidents Day (3rd Mon Feb)
        (good_friday.month, good_friday.day),   # Good Friday
        _last_weekday(5, 0),                    # Memorial Day (last Mon May)
        _observed(6, 19),                       # Juneteenth
        _observed(7, 4),                        # Independence Day
        _nth_weekday(9, 0, 1),                  # Labor Day (1st Mon Sep)
        _nth_weekday(11, 3, 4),                 # Thanksgiving (4th Thu Nov)
        _observed(12, 25),                      # Christmas
    }


def _get_market_status() -> str:
    """Return 'open' during regular NYSE hours (09:30–15:59 ET on trading days),
    'closed' at all other times.
    """
    import main  # late import so patch("main._et_now", ...) takes effect
    now = main._et_now()
    if now.weekday() >= 5:
        return "closed"
    if (now.month, now.day) in main._nyse_holidays(now.year):
        return "closed"
    h, m = now.hour, now.minute
    if (h == 9 and m >= 30) or (10 <= h <= 15):
        return "open"
    return "closed"


def _market_is_open() -> bool:
    """Return True only during regular NYSE trading hours."""
    import main
    return main._get_market_status() == "open"


def _detect_close_transition(prev_status: str, current_status: str) -> bool:
    """Return True when the market has just transitioned from open to closed."""
    return "open" in prev_status and current_status == "closed"


def _minutes_until_open() -> float:
    """Minutes until the next regular market open (09:30 ET on the next trading day).
    Returns 0 if the market is currently open.
    """
    import main
    if main._market_is_open():
        return 0
    now = main._et_now()
    for days_ahead in range(8):
        candidate = now + timedelta(days=days_ahead)
        if candidate.weekday() >= 5:
            continue
        if (candidate.month, candidate.day) in main._nyse_holidays(candidate.year):
            continue
        opens = candidate.replace(hour=9, minute=30, second=0, microsecond=0)
        if opens > now:
            return (opens - now).total_seconds() / 60
    return 0
