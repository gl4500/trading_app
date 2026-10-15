"""S1-SEALS / S1-STOP / S1-PLAN timing (§4, §6, §9). Deterministic capture schedule per pinned close, seal = first
consistent capture taken within SCHEDULE_SLACK of a registered slot, row fences, backdating, bridge split, calendar-
month deadline, stop decision over SEALED closes only."""
import calendar as pycal
from datetime import date, datetime, time, timedelta, timezone

import s1_books as b
import s1_common as c

OFFSETS_MIN = (45, 47, 49, 51, 53, 55)
SCHEDULE_SLACK = timedelta(minutes=10)
STOP_N = 100


def _ny(d: str, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime.combine(date.fromisoformat(d), time(h, m), tzinfo=c.NY).astimezone(timezone.utc)


def _close(day) -> datetime:
    """Close instant of a calendar row as aware UTC (the pinned core returns it in New York local time)."""
    return c.sim().close_instant(day).astimezone(timezone.utc)


def open_instant(day) -> datetime:
    return _ny(day["date"], day["open"])


def close_of(day_iso: str, calendar) -> datetime:
    return _close(next(d for d in calendar if d["date"] == day_iso))


def _sorted_calendar(calendar) -> list:
    """Calendar sorted by date; a duplicate date is a bad record."""
    cal = sorted(calendar, key=lambda d: d["date"])
    for a, b in zip(cal, cal[1:]):
        if a["date"] == b["date"]:
            raise ValueError(f"duplicate calendar date {a['date']}")
    return cal


def _next_session(day, calendar):
    later = [d for d in _sorted_calendar(calendar) if d["date"] > day["date"]]
    if not later:
        raise ValueError(f"calendar ends at {day['date']}: cannot schedule its seal window")
    return later[0]


def window_end(day, calendar) -> datetime:
    return _ny(_next_session(day, calendar)["date"], "08:00")


def schedule(day, calendar) -> list:
    close = _close(day)
    slots = [close + timedelta(minutes=m) for m in OFFSETS_MIN]
    t = (slots[-1] + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    end = window_end(day, calendar)
    while t <= end:
        slots.append(t)
        t += timedelta(hours=1)
    return slots


def choose_seal(day, calendar, captures):
    slots = set(schedule(day, calendar))
    for cap in sorted(captures, key=lambda k: (c.aware(k["scheduled"]), c.aware(k["actual"]))):
        sch, act = c.aware(cap["scheduled"]), c.aware(cap["actual"])
        if sch in slots and sch <= act <= sch + SCHEDULE_SLACK and cap["ok"] and cap["consistent"]:
            return cap
    return None


def _row_hash(t) -> str:
    return c.sha256_bytes(c.canonical({k: t[k] for k in ("id", "symbol", "action", "shares", "price", "timestamp",
                                                           "reasoning_sha256")}))


def fence(projection) -> dict:
    return {t["id"]: _row_hash(t) for t in projection["trades"]}


def check_fences(prior_seals, projection) -> list:
    now = {t["id"]: t for t in projection["trades"]}
    seen = {str(i) for s in prior_seals for i in s["fence"]}
    max_seen = max((s["max_id"] for s in prior_seals), default=0)
    out = []
    for s in prior_seals:
        for i, h in s["fence"].items():
            i = int(i)
            msg = (f"sealed row {i} deleted" if i not in now
                   else f"sealed row {i} changed" if _row_hash(now[i]) != h else None)
            if msg and msg not in out:
                out.append(msg)
    for s in prior_seals:       # per slice (§6): a row stored by this close must be in THIS seal's fence
        fenced = {str(i) for i in s["fence"]}
        for i, t in now.items():
            if str(i) not in fenced and c.aware(t["ts"]) <= c.aware(s["close"]):
                out.append(f"row {i} backdated to <= sealed close {s['close']}")
    for i in now:
        if str(i) not in seen and i < max_seen:
            out.append(f"new id {i} below previous max {max_seen}")
    return out


def split_bridge(trades, start: datetime):
    rs = sorted(trades, key=lambda t: (c.aware(t["ts"]), t["id"]))
    return [t for t in rs if c.aware(t["ts"]) < start], [t for t in rs if c.aware(t["ts"]) >= start]


def _bridge_row(t) -> dict:
    """The per-row fields the seal fence hashes, with the stored time normalised to canonical aware UTC so two
    spellings of one instant (Z / +00:00 / naive) give the same bridge hash."""
    r = {k: t[k] for k in ("id", "symbol", "action", "shares", "price", "reasoning_sha256")}
    r["timestamp"] = c.aware(t["ts"]).isoformat()
    return r


def bridge_record(trades, start: datetime, opening_close) -> dict:
    """§11 Bootstrap (Task 8b): classify rows by stored time into PRE-START bridge (< START) and cohort-era
    (>= START) and hash the bridge rows (canonical JSON, rows sorted by (aware ts, id)). `post_opening_row_ids` are
    the bridge rows stored after the opening seal's close (the part the pre-start audit never saw)."""
    oc = c.aware(opening_close) if isinstance(opening_close, str) else opening_close
    bridge, era = split_bridge(trades, start)
    return {"bridge_row_ids": sorted(t["id"] for t in bridge),
            "cohort_era_row_ids": sorted(t["id"] for t in era),
            "post_opening_row_ids": sorted(t["id"] for t in bridge if oc is not None and c.aware(t["ts"]) > oc),
            "opening_close": None if oc is None else oc.isoformat(),
            "bridge_sha256": c.sha256_bytes(c.canonical([_bridge_row(t) for t in bridge]))}


def opening_close_of(start: datetime, calendar) -> datetime:
    """Close of the session immediately before planned START (the opening seal's close, §4/§6)."""
    sd = start.astimezone(c.NY).date().isoformat()
    prior = [d for d in _sorted_calendar(calendar) if d["date"] < sd]
    if not prior:
        raise ValueError(f"no calendar session before START {start.isoformat()}")
    return _close(prior[-1])


def post_start_seals(seals, start: datetime) -> list:
    """Seals of closes >= START, in close order."""
    return sorted((s for s in seals if c.aware(s["close"]) >= start), key=lambda s: c.aware(s["close"]))


def check_bridge(seals, trades, start: datetime) -> list:
    """§6/§11 (Task 8b): every post-START seal must carry a bridge record equal to the FIRST post-START seal's, and
    the bridge recomputed from `trades` must hash the same. A pre-START row that appeared, vanished or changed after
    the bootstrap is a fence violation. No post-START seal yet -> nothing to compare."""
    post = post_start_seals(seals, start)
    if not post:
        return []
    out = [f"post-START seal {s['close']}: no bridge record" for s in post
           if not isinstance(s.get("bridge"), dict) or "bridge_sha256" not in s["bridge"]]
    if out:
        return out
    want = post[0]["bridge"]["bridge_sha256"]
    out += [f"post-START seal {s['close']}: bridge hash differs from the first post-START seal {post[0]['close']}"
            for s in post[1:] if s["bridge"]["bridge_sha256"] != want]
    got = bridge_record(trades, start, None)["bridge_sha256"]
    if got != want:
        out.append(f"bridge (pre-START rows) changed since the first post-START seal {post[0]['close']}: "
                   f"{got[:12]} != {want[:12]}")
    return out


def cohort(trades, start: datetime, close: datetime) -> list:
    """BUY rows with START <= stored time <= close. Rows come back with `ts` normalised to canonical aware UTC so
    two spellings of one instant (Z / +00:00 / naive) give identical cohorts."""
    return [{**t, "ts": c.aware(t["ts"]).isoformat()} for t in trades
            if t["action"] == "BUY" and start <= c.aware(t["ts"]) <= close]


def count_sold(trades, start: datetime, close: datetime) -> int:
    asof = [t for t in trades if c.aware(t["ts"]) <= close]
    ids = {t["id"] for t in cohort(asof, start, close)}
    return sum(1 for lid in b.sold_events(asof) if lid in ids)


def deadline(start: datetime) -> date:
    d = start.astimezone(c.NY).date()
    m = d.month + 6
    y, m = d.year + (m - 1) // 12, (m - 1) % 12 + 1
    return date(y, m, min(d.day, pycal.monthrange(y, m)[1]))


def stop_decision(seals, start: datetime, calendar, *, today: datetime) -> dict:
    """seals: [{"close": iso, "trades": projection trades of that seal, ...}] — the seal is authoritative.
    `today` is required (no real-clock default); a seal dated after it, or two seals for one close, is a bad record."""
    calendar = _sorted_calendar(calendar)
    dl = deadline(start).isoformat()
    by_close = {}
    for s in seals:
        k = c.aware(s["close"])
        if k > today:
            raise ValueError(f"seal for {k.isoformat()} is after today: bad record")
        if k in by_close:
            raise ValueError(f"two seals for close {k.isoformat()}")
        by_close[k] = s
    eligible = [d for d in calendar if open_instant(d) >= start and d["date"] <= dl]
    missed = []
    for d in eligible:
        close = _close(d)
        if close > today:
            break
        s = by_close.get(close)
        if s is None:
            if window_end(d, calendar) < today:
                missed.append(d["date"])
            continue
        if count_sold(s["trades"], start, close) >= STOP_N:
            return {"status": "STOPPED", "stop_close": close.isoformat(), "missed": missed}
    last = eligible[-1] if eligible else None
    if last is None or window_end(last, calendar) >= today:
        return {"status": "RUNNING", "stop_close": None, "missed": missed}
    sealed = [_close(d) for d in eligible if _close(d) in by_close]
    if not sealed:
        return {"status": "NO-VALID-SEAL", "stop_close": None, "missed": missed}
    return {"status": "TIMEOUT", "stop_close": max(sealed).isoformat(), "missed": missed}
