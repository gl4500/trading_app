"""S1-SEALS / S1-STOP / S1-PLAN timing (§4, §6, §9). Deterministic capture schedule per pinned close, seal = first
consistent capture taken within SCHEDULE_SLACK of a registered slot, row fences, backdating, bridge split, calendar-
month deadline, stop decision over SEALED closes only.

Task 12 (controller-added), Addendum 1: the deadline is an aware INSTANT and every comparison uses close instants
(A5.1); slot eligibility E = min(s + SCHEDULE_SLACK, W) for the measured capture start/end (A5.2; the 08:00 slot has
E = W = s, A5.3); the pinned provider calendar's completeness (A6); the persisted stop, s1_out/stop.json (A2)."""
import calendar as pycal
import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import s1_books as b
import s1_common as c

OFFSETS_MIN = (45, 47, 49, 51, 53, 55)
SCHEDULE_SLACK = timedelta(minutes=10)    # A5.2 (Codex Q7): registered prospectively, named and single-sourced here
RESOLUTION_TIMEOUT = timedelta(minutes=30)  # Addendum 2 B1.1 (Codex R-b): D(s) = E(s) + 30 min, single-sourced here
STOP_N = 100
FINAL_LAG_SESSIONS = 3                    # v5 §13: no earlier than the close of the 3rd session after the stop
ENDED = ("STOPPED", "TIMEOUT", "NO-VALID-SEAL")


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


def first_slot_after(close: datetime) -> datetime:
    """Task 12 fix round 4 (N-3 clock anchor): the first registered seal slot of a close (close + the first offset;
    single-sourced here, as schedule's first slot)."""
    return close + timedelta(minutes=OFFSETS_MIN[0])


def eligible_until(slot: datetime, day, calendar) -> datetime:
    """A5.2: E = min(s + SCHEDULE_SLACK, W), W = 08:00 America/New_York on the next session day of `day` (from the
    registered calendar; never recomputed from invocation time). For the 08:00 slot E = W = s (A5.3)."""
    return min(slot + SCHEDULE_SLACK, window_end(day, calendar))


def resolution_deadline(slot: datetime, day, calendar) -> datetime:
    """Addendum 2 B1.1: D(s) = E(s) + RESOLUTION_TIMEOUT - the deadline by which a CLAIMED attempt must have
    published its success/failure report (strictly before D); it never extends capture eligibility (B1.5)."""
    return eligible_until(slot, day, calendar) + RESOLUTION_TIMEOUT


def _applied_or_unsuccessful(res: Path) -> bool:
    """A resolution record that cannot (any longer) make its close's seal: anything but a readable SUCCESS. Fix round
    3 (I-1): a SUCCESS whose seal is not written yet is NOT applied (the crash window between its publication and the
    close-level finalization); an unreadable record is not known to be unsuccessful (pending, never missed)."""
    try:
        return json.loads(res.read_text(encoding="utf-8")).get("outcome") != "SUCCESS"
    except (OSError, ValueError, AttributeError):
        return False


def pending_closes(out: Path) -> set:
    """Addendum 2 B1.4/B1.5: the closes (NY session dates) without a seal that have a claimed slot attempt with no
    resolution record yet (PENDING): no stop may be frozen across them. Fix round 3 (I-1): a close with a SUCCESS
    resolution (or an unreadable one) but no seal is pending too - the success is not applied until the serialized
    close-level selection writes the seal, so no command that did not finalize can freeze a stop across it."""
    out, got = Path(out), set()
    for day_dir in sorted((out / "captures").glob("*")):
        if not day_dir.is_dir() or (out / "seals" / f"{day_dir.name}.json").exists():
            continue
        for claim in day_dir.glob("*.attempt.json"):
            name = claim.name[:-len(".attempt.json")]
            res = day_dir / f"{name}.resolution.json"
            if not res.exists() or not _applied_or_unsuccessful(res):
                got.add(day_dir.name)
                break
    return got


def capture_eligible(slot: datetime, day, calendar, capture_start: datetime, capture_end: datetime) -> bool:
    """A5.2: s <= capture_start <= capture_end <= E (aware instants); completion exactly at E is allowed."""
    return slot <= capture_start <= capture_end <= eligible_until(slot, day, calendar)


def choose_seal(day, calendar, captures):
    """A5.2: the seal = the FIRST eligible consistent capture IN SLOT ORDER (never arrival order): a capture of a
    registered slot whose measured start/end satisfy capture_eligible."""
    slots = set(schedule(day, calendar))
    for cap in sorted(captures, key=lambda k: c.aware(k["scheduled"])):
        sch = c.aware(cap["scheduled"])
        if sch in slots and cap["ok"] and cap["consistent"] and capture_eligible(
                sch, day, calendar, c.aware(cap["capture_start"]), c.aware(cap["capture_end"])):
            return cap
    return None


# ------------------------------------------------------------------ A6: the pinned provider calendar
def calendar_rows(raw) -> list:
    """The session rows (date, open, close) of a provider calendar listing."""
    return [{"date": x["date"], "open": x["open"], "close": x["close"]} for x in raw]


def calendar_problems(listing, plan: dict) -> list:
    """A6: completeness of the pinned provider listing, checked against that listing only: a non-empty list of
    {date, open, close} rows (ISO date, HH:MM), strictly ascending AS LISTED (no re-sort: out of order or duplicate
    refuses), open < close, covering the opening close (the session before START) through the deadline + the final
    lag (>= FINAL_LAG_SESSIONS sessions whose close is after the deadline instant). No weekday-minus-holidays rule:
    special closures and early closes are whatever the provider lists. Fix round 10 (m-1): a session in the plan's
    calendar_range closing before s1_common.EARLIEST_CLOSE_NY (13:00 New York, the close the calendar-free clock
    anchor assumes as the earliest) refuses - the anchor's premise is checked against the provider, fail closed."""
    if not isinstance(listing, list) or not listing:
        return ["calendar is not a non-empty list (wrong shape)"]
    out, prev = [], None
    for x in listing:
        if not isinstance(x, dict) or any(not isinstance(x.get(k_), str) for k_ in ("date", "open", "close")):
            return ["calendar entry lacks date/open/close (wrong shape)"]
        try:
            o, cl = _ny(x["date"], x["open"]), _ny(x["date"], x["close"])
        except ValueError:
            return ["calendar entry has an unparseable date/time (wrong shape)"]
        if o >= cl:
            out.append(f"calendar entry {x['date']}: open is not before close")
        if prev is not None and x["date"] <= prev:
            out.append(f"calendar has a duplicate date {x['date']}" if x["date"] == prev
                       else f"calendar listing out of order at {x['date']} (after {prev})")
        prev = x["date"]
    if out:
        return out
    rng = plan.get("calendar_range") if isinstance(plan.get("calendar_range"), list) else None
    for x in listing:                                      # fix round 10 (m-1): EARLIEST_CLOSE_NY self-enforcing
        in_range = rng is None or len(rng) != 2 or str(rng[0]) <= x["date"] <= str(rng[1])
        if in_range and _ny(x["date"], x["close"]) < _ny(x["date"], c.EARLIEST_CLOSE_NY.strftime("%H:%M")):
            out.append(f"calendar entry {x['date']}: close {x['close']} is before the earliest early close "
                       f"{c.EARLIEST_CLOSE_NY.strftime('%H:%M')} America/New_York the clock anchor assumes")
    if out:
        return out
    oc = plan.get("opening_close")
    if not oc or listing[0]["date"] > oc or oc not in {x["date"] for x in listing}:
        out.append(f"calendar does not cover the opening close (plan opening_close {oc!r}, the session before "
                   f"START)")
    dl = c.aware(plan["deadline"]) if isinstance(plan.get("deadline"), str) and "T" in plan["deadline"] else None
    if dl is None:
        out.append("plan deadline is not an aware instant")
    elif sum(1 for x in listing if _ny(x["date"], x["close"]) > dl) < FINAL_LAG_SESSIONS:
        out.append(f"calendar does not cover the deadline plus {FINAL_LAG_SESSIONS} sessions")
    return out


def calendar_pin_problems(out, manifest: dict, files: dict, plan: dict) -> list:
    """Task 12 (A6/A8.2 source binding): the audit's calendar must be the pinned provider listing - source and
    request parameters as the plan registered, retrieved within the audit attempt, its raw page hashed under the
    manifest's `pages`, and calendar.json exactly the parsed raw page."""
    from pathlib import Path
    import json
    src = files.get("calendar_source.json")
    if not isinstance(src, dict):
        return ["no calendar_source.json pin"]
    probs = []
    want = {"start": plan["calendar_range"][0], "end": plan["calendar_range"][1], "date_type": "TRADING"}
    if src.get("source") != c.CAL_URL:
        probs.append(f"calendar source {src.get('source')!r} is not the provider calendar {c.CAL_URL}")
    if src.get("params") != want:
        probs.append(f"calendar request parameters {src.get('params')!r} are not the plan's {want!r}")
    page = src.get("page")
    if not page or (manifest.get("pages") or {}).get(page) != src.get("page_sha256"):
        probs.append("calendar raw page is not bound in the manifest pages")
    else:
        try:
            raw = json.loads((Path(out) / page).read_bytes())
        except (OSError, ValueError):
            raw = None
        if raw != files.get("calendar.json"):
            probs.append("calendar.json is not the pinned raw page")
    try:
        t = c.aware(src.get("retrieved_utc"))
        reserved = c.aware(json.loads((Path(out) / "audit" / "attempt.json").read_text(encoding="utf-8"))
                           ["reserved_utc"])
        if t < reserved:
            probs.append("calendar retrieved before the audit attempt")
    except (OSError, ValueError, KeyError, TypeError):
        probs.append("calendar retrieval time unreadable")
    return probs


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


def deadline(start: datetime) -> datetime:
    """A5.1: START + 6 calendar months at START's New York wall time (missing day-of-month -> that month's last day),
    an aware instant (UTC). Task 3 returned a date; the A5.1 instant replaces it."""
    s = start.astimezone(c.NY)
    m = s.month + 6
    y, m = s.year + (m - 1) // 12, (m - 1) % 12 + 1
    d = date(y, m, min(s.day, pycal.monthrange(y, m)[1]))
    return datetime.combine(d, s.time().replace(tzinfo=None), tzinfo=c.NY).astimezone(timezone.utc)


def eligible_sessions(start: datetime, calendar) -> list:
    """A5.1: the sessions that can be the stop or the timeout: open >= START and close INSTANT <= the deadline."""
    dl = deadline(start)
    return [d for d in _sorted_calendar(calendar) if open_instant(d) >= start and _close(d) <= dl]


def stop_decision(seals, start: datetime, calendar, *, today: datetime, pending=()) -> dict:
    """seals: [{"close": iso, "trades": projection trades of that seal, ...}] — the seal is authoritative.
    `today` is required (no real-clock default); a seal dated after it, or two seals for one close, is a bad record.
    Addendum 2 B1.5: `pending` = closes with a PENDING claimed attempt (pending_closes): reaching one, the decision
    is RUNNING (not frozen) - a later resolution may still seal it."""
    calendar = _sorted_calendar(calendar)
    by_close = {}
    for s in seals:
        k = c.aware(s["close"])
        if k > today:
            raise ValueError(f"seal for {k.isoformat()} is after today: bad record")
        if k in by_close:
            raise ValueError(f"two seals for close {k.isoformat()}")
        by_close[k] = s
    eligible = eligible_sessions(start, calendar)                    # A5.1: close instants <= the deadline
    missed = []
    for d in eligible:
        close = _close(d)
        if close > today:
            break
        s = by_close.get(close)
        if s is None and d["date"] in pending:                  # B1.5: never frozen across a PENDING close
            return {"status": "RUNNING", "stop_close": None, "missed": missed}
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


# ------------------------------------------------------------------ A2 / A3 F2: the persisted stop (s1_out/stop.json)
# A3 Task 11 (Steps 4-6; dispositions r1 9153062b, ACCEPTED by Codex 28e08272): the stop is the journal's TRIAL-STOP
# row; stop.json publishes its record (F2.2). The record is a pure function of committed rows (stop_record); the
# permission to commit it is the TRIAL-STOP transaction's own clock (stop_ready, BLK3-C1). Nothing here decides a stop
# from seal files or a wall clock outside that transaction.
def _seal_index(out: Path) -> list:
    out = Path(out)
    return [(p, json.loads(p.read_text(encoding="utf-8"))) for p in sorted((out / "seals").glob("*.json"))]


def persist_stop(out: Path, rec: dict) -> dict:
    """F2.2/F2.3: publish s1_out/stop.json = json.dumps(record, indent=1, sort_keys=True), exclusively, after the
    TRIAL-STOP row; an existing file with exactly these bytes is accepted (a concurrent publisher of the same record,
    or the completion of an interrupted one); any other existing file is FileExistsError. Then (OQ-19, legacy detector
    only) the two registry records. Called only by decide_stop and stop_check."""
    p = Path(out) / "stop.json"
    text = json.dumps(rec, indent=1, sort_keys=True)
    if not Path(out).is_dir():                           # fix round 1 (review M7, F6.6): never recreate a lost s1_out
        raise SystemExit("stop.json: s1_out is gone: not published, refused (F6.6)")
    try:
        c.publish_text_exclusive(p, text)
    except FileExistsError:
        if p.read_bytes() != c.text_bytes(text):
            raise
    c.register_stage(out, "stop", {"stop.json": c.sha256_file(p)})
    return rec


def load_stop(out: Path):
    """The persisted stop (A2.1), or None."""
    p = Path(out) / "stop.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def stop_was_persisted(out: Path) -> bool:
    """m-4: some artifact recorded stop.json's hash (a capture report after the stop, the stop attestation, the final
    plan / manifest / snapshot report): stop.json existed."""
    out = Path(out)
    named = [p for p in (out / "captures").glob("*/*.report.json")]
    named += [out / "attest_stop.json", out / "final_plan.json", out / "final" / "manifest.json",
              out / "final_snapshot" / "report.json"]
    if any(p.exists() for p in c.stage_records(out, "stop")):     # fix round 2/3 (B3.1, C-2): both stop records
        return True
    for p in named:
        try:
            v = json.loads(p.read_text(encoding="utf-8")).get("stop_sha256") if p.is_file() else None
        except (OSError, ValueError, AttributeError):
            continue
        if v not in (None, c.ABSENT):
            return True
    return False


def _journal(mailbox=None, out=None) -> tuple:
    """(trial, its verified rows) - read only. With `out`, the trial plan.json names (open or CLOSED: the stop is a
    fact of that trial's journal even after a CLOSE); else, or when that trial is not in the mailbox, the open trial."""
    import s1_journal as j
    import s1_trial
    tr = None
    if out is not None:
        try:
            tid = c.load_json(Path(out) / "plan.json").get("trial_id")
        except (OSError, ValueError, AttributeError):
            tid = None
        tr = s1_trial.trials(s1_trial.scan(mailbox)).get(tid) if tid else None
    tr = tr or s1_trial.open_trial(mailbox)
    return tr, j.read_trial(tr.trial_id, tr.genesis, mailbox)


def current_stop(out: Path, start: datetime, calendar, now: datetime, by: str, *, mailbox=None) -> dict:
    """A3 F1/F2 (Task 11): the trial's stop as the journal records it - with a TRIAL-STOP row, stop.json's
    {"status", "stop_close", "missed"} and persisted=True (a missing stop.json is a ValueError: the publication gap
    is the gate's to recover, F2.3); otherwise RUNNING with persisted=False. It never decides and never persists
    (only decide_stop does, F2.2). `start`, `calendar`, `now` and `by` are kept for the callers' signature."""
    import s1_journal as j
    tr, rows = _journal(mailbox, out)
    stop = j.first(rows, "TRIAL-STOP")
    if stop is None:
        return {"status": "RUNNING", "stop_close": None, "missed": [], "persisted": False}
    st_ = load_stop(out)
    if st_ is None:                                      # F2.3 publication gap (a concurrent decide_stop between its
        rec = stop_record(out, [x for x in rows if x.seq < stop.seq], start, calendar, tr.bundle)   # STOP and its
        if rec is None or j.detail_of(rec) != stop.detail:                                          # stop.json):
            raise ValueError("TRIAL-STOP is committed, stop.json is missing and committed history gives another "
                             "record (F2.3: stop-conflict, the gate's to decide)")
        return {"status": rec["status"], "stop_close": rec["stop_close"], "missed": rec["missed"],
                "persisted": False}                      # the STOP's own record - read, never published here
    return {"status": st_["status"], "stop_close": st_["stop_close"], "missed": st_.get("missed", []),
            "persisted": True}


# ------------------------------------------------------------------ the stop record (F2.1, OQ-8 r1)
def _by_subject(rows) -> dict:
    got = {}
    for r_ in rows:
        got.setdefault(r_.subject, []).append(r_)
    return got


def _first(rows_of, *kinds):
    return next((r_ for r_ in rows_of if r_.kind in kinds), None)


def _close_state(index, d, cal) -> tuple:
    """r1 §1.1 from committed rows only: ("sealed", deps, first QUALIFIED) - the determined sampled candidate (E2.2;
    deps = the terminal rows of its slots up to and including the first QUALIFIED); ("pending", ...) - a slot with an
    INTENT and no terminal before any determined QUALIFIED (B1.2/B1.5); ("unresolved", ...) - a QUALIFIED exists but
    an earlier slot has no terminal row (A2); ("none", deps, None) - no QUALIFIED and no PENDING slot (deps = the
    terminal rows of its slots that have an INTENT). Whether a "none" close counts missed needs the clock (stop_ready,
    A6 r1), never these rows."""
    import s1_journal as j
    slots = schedule(d, cal)
    deps, seen_gap = [], False
    for s in slots:
        mine = index.get(j.slot_subject(s), [])
        term = _first(mine, *j.TERMINAL)
        if term is None:
            if _first(mine, "SLOT-INTENT") is not None:
                return "pending", None, None
            seen_gap = True
            continue
        if term.kind == "SLOT-QUALIFIED":
            if seen_gap:
                return "unresolved", None, None
            return "sealed", deps + [term], term
        if not seen_gap:
            deps.append(term)
    # no QUALIFIED at all: every INTENT-bearing slot is terminal (a pending one returned above)
    inten = [_first(index.get(j.slot_subject(s), []), *j.TERMINAL) for s in slots
             if _first(index.get(j.slot_subject(s), []), "SLOT-INTENT") is not None]
    return "none", [x for x in inten if x is not None], None


def sampled_seals(out, rows, cal, start, upto_seq=None) -> dict:
    """F1 STOP prefix / OQ-14: {day: (first QUALIFIED row, recomputed seal bytes)} for every eligible post-START close
    determined (E2.2) by the rows committed at or before `upto_seq` (all rows when None)."""
    import s1_journal as j
    import s1_slot
    if upto_seq is None:                                 # F1 STOP prefix: terminals after a STOP never enter it
        stop = j.first(rows, "TRIAL-STOP")
        upto_seq = None if stop is None else stop.seq
    rows = [x for x in rows if upto_seq is None or x.seq <= upto_seq]
    index = _by_subject(rows)
    got = {}
    for d in eligible_sessions(start, cal):
        stt, _deps, q = _close_state(index, d, cal)
        if stt == "sealed":
            ev = s1_slot._resolution_evidence(out, q, d["date"])
            got[d["date"]] = (q, s1_slot.seal_bytes(d, _close(d), ev))
    return got


def sampled_history(rows, stop_row, seals: dict) -> dict:
    """OQ-29: the score's sampled-history input - every journal row at or before the STOP seq (line sha256 in seq
    order) and the seals derived from QUALIFIED slots committed at or before it ({relpath: sha256}, keys sorted).
    `seals` is sampled_seals(..., upto_seq=stop_row.seq): {day: (first QUALIFIED row, recomputed seal bytes)}. Later
    completions change neither part (F1 STOP prefix)."""
    return {"rows": [x.sha for x in sorted(rows, key=lambda x: x.seq) if x.seq <= stop_row.seq],
            "seals": {f"seals/{d}.json": c.sha256_bytes(b_) for d, (_, b_) in sorted(seals.items())}}


def stop_record(out, rows, start, cal, bundle):
    """F2.1 / OQ-8 r1 (t11_dispositions.md 9153062b, ACCEPTED): the stop CANDIDATE, a pure function of the committed
    rows (and the files they commit), or None.
    Lots: walk the eligible closes in order; a PENDING or UNRESOLVED close before the first qualifying determined
    close -> None; else the first determined close C whose sampled seal sells >= STOP_N cohort lots by C; the "none"
    closes before C are `missed`. Timeout (no lots candidate): no PENDING/UNRESOLVED eligible close and the W slot of
    the last eligible close terminal (the F2.1 trigger anchor, P2 - never a time witness); TIMEOUT = the last
    determined eligible close, NO-VALID-SEAL = none. Trigger (b): the greatest-seq terminal row among the necessary
    dependencies; determined_utc = that row's `at` verbatim (provenance only, BLK3-C2)."""
    import s1_journal as j
    import s1_slot
    rows = list(rows)
    tids = {x.trial_id for x in rows}
    if len(tids) != 1:
        return None
    index = _by_subject(rows)
    eligible = eligible_sessions(start, cal)
    if not eligible:
        return None
    missed, deps, sealed, stop_day = [], [], [], None
    for d in eligible:
        stt, dd, q = _close_state(index, d, cal)
        if stt in ("pending", "unresolved"):
            return None
        deps += dd
        if stt == "none":
            missed.append(d["date"])
            continue
        ev = s1_slot._resolution_evidence(out, q, d["date"])
        data = s1_slot.seal_bytes(d, _close(d), ev)
        sealed.append((d, data))
        if count_sold(json.loads(data)["trades"], start, _close(d)) >= STOP_N:
            stop_day = d
            break
    if stop_day is not None:
        status, rule = "STOPPED", "lots"
    else:
        w_term = _first(index.get(j.slot_subject(schedule(eligible[-1], cal)[-1]), []), *j.TERMINAL)
        if w_term is None:
            return None
        deps.append(w_term)
        status, rule = ("TIMEOUT", "timeout") if sealed else ("NO-VALID-SEAL", "timeout")
        stop_day = sealed[-1][0] if sealed else None
    trig = max(deps, key=lambda r_: r_.seq)
    rec = {"trial_id": tids.pop(), "rule": rule, "status": status, "triggering_slot": trig.subject,
           "terminal_seq": trig.seq, "terminal_line_sha256": trig.sha, "determined_utc": trig.at,
           "missed": missed, "bundle_sha256": bundle, "stop_close": None, "stop_seal": None,
           "stop_seal_sha256": None, "cohort_row_ids": [], "lots": None, "seals": {}}
    if stop_day is None:
        return rec
    sc = _close(stop_day)
    data = dict((d["date"], x) for d, x in sealed)[stop_day["date"]]
    trades = [x for x in json.loads(data)["trades"] if c.aware(x["ts"]) <= sc]
    ids = sorted(x["id"] for x in cohort(trades, start, sc))
    rec.update(stop_close=sc.isoformat(), stop_seal=f"seals/{stop_day['date']}.json",
               stop_seal_sha256=c.sha256_bytes(data), cohort_row_ids=ids,
               lots={"sold": count_sold(trades, start, sc), "cohort": len(ids)},
               seals={f"seals/{d['date']}.json": c.sha256_bytes(x) for d, x in sealed if _close(d) <= sc})
    return rec


def stop_ready(out, rows, start, cal, bundle, now):
    """r1 §1.3 (BLK3-C1, P1; ACCEPTED): permission to COMMIT the candidate, given `now` = the clock sampled INSIDE the
    TRIAL-STOP journal transaction (j.append passes it to Context.stop_ready): None = permitted, else the reason.
    Requires a candidate; now >= W of every close it counts missed; for TIMEOUT / NO-VALID-SEAL now >= W of the last
    eligible close (every eligible window E has expired). No terminal row or `at` stands in for this clock."""
    rec = stop_record(out, rows, start, cal, bundle)
    if rec is None:
        return "no stop candidate in committed history"
    by_date = {d["date"]: d for d in eligible_sessions(start, cal)}
    need = [window_end(by_date[x], cal) for x in rec["missed"]]
    if rec["rule"] == "timeout":
        need.append(window_end(list(by_date.values())[-1], cal))
    w = max(need, default=None)
    if w is not None and now < w:
        return (f"not ready: transaction clock {now.isoformat()} < {w.isoformat()} (an eligible window counted by "
                f"the stop is still open, BLK3-C1)")
    return None


NVS_NULLS = ("stop_close", "stop_seal", "stop_seal_sha256", "lots")              # t11 §4 NVS shape (Erratum 2 G1.1)


def nvs(out, rows, start, cal, bundle) -> bool:
    """A3 H2, Erratum 2 r4 G1.1 (NVS-REQ1): the NO-VALID-SEAL terminal-score branch predicate, decided on the DECIDING
    rows only (a stage transaction's re-read rows, or a command's gate rows). True only when all of:
    1. STOPPED: exactly one TRIAL-STOP and no TRIAL-INVALID (CLOSED is the caller's: the gate / step 2 refuse first);
    2. the record recomputed from the rows with seq < the STOP seq (stop_record, F2.3) exists and its detail equals
       the TRIAL-STOP detail;
    3. that record is status NO-VALID-SEAL, rule timeout, with exactly the t11 §4 NVS shape: stop_close, stop_seal,
       stop_seal_sha256 and lots null, cohort_row_ids [], seals {}, and missed = every eligible close (each is a
       no-attempt close: no QUALIFIED, ruling OP-3);
    4. sampled_seals(..., upto_seq = the STOP seq) is empty.
    It never follows a CLI flag, file presence, a display status or a caller's verdict. An exception (an evidence
    read, a malformed record) PROPAGATES: the caller refuses - it never selects the normal branch silently (I-2).
    Recomputed per call; nothing is cached (I-7)."""
    import s1_journal as j
    rows = list(rows)
    if j.trial_state(rows) != "STOPPED":
        return False
    stops = [x for x in rows if x.kind == "TRIAL-STOP"]
    if len(stops) != 1:
        return False
    stop = stops[0]
    rec = stop_record(out, [x for x in rows if x.seq < stop.seq], start, cal, bundle)
    if rec is None or j.detail_of(rec) != stop.detail:
        return False
    if (rec["status"], rec["rule"]) != ("NO-VALID-SEAL", "timeout") or any(rec[k_] is not None for k_ in NVS_NULLS) \
            or rec["cohort_row_ids"] != [] or rec["seals"] != {} \
            or rec["missed"] != [d["date"] for d in eligible_sessions(start, cal)]:
        return False
    return not sampled_seals(out, rows, cal, start, upto_seq=stop.seq)


STOP_FENCE_RETRIES = 3                                            # E2.5 r3: bounded seal-then-STOP retry


def _stop_context(gv, cal, start):
    import s1_journal as j
    import s1_slot
    import s1_trial
    out, bundle = gv.out, gv.trial.bundle

    def detail(rows_):
        x = stop_record(out, rows_, start, cal, bundle)
        return None if x is None else j.detail_of(x)
    return s1_trial.product_context(gv.trial, cal, stop_detail=detail, stop_fence=s1_slot.stop_fence(cal, start),
                                    stop_ready=lambda rows_, now_: stop_ready(out, rows_, start, cal, bundle, now_))


def decide_stop(gv, cal, start, now, *, mailbox=None):
    """F2.2 + E2.5 r3 + r1 §1.3: under the stop lock (F5.1, taken before the journal read), when committed history
    gives a stop candidate: run every pending seal stage (a determined eligible close without a CREATED seal stage),
    then append TRIAL-STOP (detail = sha256 of the record, recomputed inside the transaction; OQ-9) with the F0.5
    step-5 checks inside that same transaction - the record, the E2.5 fence, and the readiness on the transaction's own
    clock (`now` is the append's clock: no preflight time decides). On APPEND (or LOST-RACE to the same record) publish
    stop.json. Returns the record, or None (no candidate / not ready / still unsealed after the bounded retries: no
    row, decide later). INVALIDATE (a different STOP exists) raises SystemExit. A failed publication AFTER the row
    committed says so (review M3: the F2.3 gap, recovered by the next gate)."""
    import s1_locks as L
    import s1_slot
    mailbox = gv.mailbox if mailbox is None else mailbox
    lock = L.OwnershipLock(gv.root, gv.trial.trial_id, L.STOP_LOCK)
    try:                                                 # fix round 1 (review M5): only THIS lock's LockHeld means
        lock.acquire()                                   # "another stop operation is deciding: decide later"
    except L.LockHeld:
        return None
    except L.LockError as e:
        raise SystemExit(f"stop decision refused with no row: stop lock error ({e}) (F5.5)") from None
    try:
        return _decide_locked(gv, cal, start, now, mailbox)
    except (s1_slot.QualifiedEvidence, ValueError, OSError, KeyError, TypeError, b.BookError, L.LockHeld,
            L.LockError) as e:                           # (any other lock inside the operation is a refusal)
        raise SystemExit(f"stop decision refused with no row ({type(e).__name__}: {e}) (F0.7)") from None
    finally:
        lock.release()


def _decide_locked(gv, cal, start, now, mailbox):
    """decide_stop's body, under the stop lock: read, the pending seal stages (E2.5), re-read, the TRIAL-STOP append
    (record, fence and readiness inside its transaction), then the publication."""
    import s1_journal as j
    import s1_slot
    import s1_stage
    for _attempt in range(STOP_FENCE_RETRIES):
        rows = j.read_trial(gv.trial.trial_id, gv.trial.genesis, mailbox)
        if j.first(rows, "TRIAL-STOP") is not None:
            return None
        if stop_record(gv.out, rows, start, cal, gv.trial.bundle) is None:
            return None
        index = _by_subject(rows)
        for d in eligible_sessions(start, cal):                    # E2.5: the pending seal stages first
            if _close_state(index, d, cal)[0] == "sealed" and \
                    s1_stage.stage_rows(rows, s1_slot.seal_stage_name(d["date"]))["created"] is None:
                s1_slot.run_seal_stage(gv, d, cal, mailbox=mailbox, clock=now)
        rows = j.read_trial(gv.trial.trial_id, gv.trial.genesis, mailbox)
        rec = stop_record(gv.out, rows, start, cal, gv.trial.bundle)
        if rec is None:
            return None
        res = j.append(gv.trial.trial_id, gv.trial.genesis,
                       j.Request("TRIAL-STOP", "trial", j.new_nonce(), j.new_nonce(), detail=j.detail_of(rec)),
                       _stop_context(gv, cal, start), mailbox=mailbox, clock=now)
        if res.outcome == "INVALIDATE":
            raise SystemExit(f"TRIAL-STOP -> INVALID ({res.reason})")
        if res.outcome == "APPEND" or (res.outcome == "LOST-RACE" and "already STOPPED" in res.reason):
            try:
                persist_stop(gv.out, rec)
            except (OSError, SystemExit) as e:           # fix round 1 (review M3): the row EXISTS - say so
                seq = res.row.seq if res.row is not None else "existing"
                raise SystemExit(f"TRIAL-STOP committed (seq {seq}); stop.json publication pending "
                                 f"({type(e).__name__}: {e}): the next gate recovers or judges it (F2.3/F2.4)") \
                    from None
            return rec
        if "not sealed" not in res.reason:                          # rule not met / differs / not ready
            return None
    return None


FINALIZATION = ("stop_attest", "final_plan", "final", "score")


def _read_stop_json(p: Path) -> tuple:
    """("ok", record) | ("missing", None) | ("corrupt", None) | ("error", OSError)."""
    try:
        if not p.exists():
            return "missing", None
        return "ok", json.loads(p.read_text(encoding="utf-8"))
    except OSError as e:
        return "error", e
    except ValueError:
        return "corrupt", None


def stop_check(gv) -> None:
    """Gate hook (F2.3/F2.4), before the stage table: with a TRIAL-STOP, stop.json must parse to the record its
    detail commits. Changed or unparseable before any finalization INTENT: INVALID (stop-conflict); absent, changed or
    unparseable after one: INVALID (registration-artifact) - restoring never resumes. Absent before any finalization
    INTENT is the publication gap, recovered by stop_gap_recover AFTER the F4/F3 tables (fix round 1, review M4).
    Fix round 1 (review I1, Task 7 confirm-on-re-read): any non-matching read is confirmed by a second read before a
    decision; a read error (OSError) on the second read refuses with no row and never invalidates."""
    import s1_journal as j
    import s1_stage
    import s1_trial
    stop = j.first(gv.rows, "TRIAL-STOP")
    if stop is None:
        return
    p = gv.out / "stop.json"
    state, obj = _read_stop_json(p)
    if state == "ok" and j.detail_of(obj) == stop.detail:
        return
    state, obj = _read_stop_json(p)                      # confirm on a re-read before any decision
    if state == "ok" and j.detail_of(obj) == stop.detail:
        return
    if state == "error":
        raise SystemExit(f"stop.json unreadable ({type(obj).__name__}: {obj}): refused with no row (a read error never "
                         f"invalidates, F2.3/F2.4)")
    fin = any(s1_stage.stage_rows(gv.rows, s)["intent"] is not None for s in FINALIZATION)
    if state == "missing" and not fin:
        return                                           # the publication gap: stop_gap_recover, after F4/F3
    reason = "registration-artifact" if fin else "stop-conflict"
    what = "missing" if state == "missing" else "changed or unparseable"
    s1_trial.invalidate(gv.trial, reason, {"stop.json": what, "stop_line_sha256": stop.sha}, root=gv.root,
                        mailbox=gv.mailbox)
    raise SystemExit(f"stop.json {what}: INVALID ({reason}) (F2.3/F2.4)")


def stop_gap_recover(gv) -> None:
    """Gate hook (F2.3), AFTER the F4 stage table and the F3 evidence table (fix round 1, review M4: a damaged stage
    member or slot tree is judged by its own table first): a TRIAL-STOP whose stop.json is absent before any
    finalization INTENT is the publication gap - the record recomputed from the rows before the STOP is published
    when it matches the STOP's detail (same bytes), else INVALID (stop-conflict). A recompute that raises (an
    evidence error the tables did not judge) or a publication error refuses with no row - never a silent gap."""
    import s1_journal as j
    import s1_stage
    import s1_trial
    stop = j.first(gv.rows, "TRIAL-STOP")
    if stop is None or (gv.out / "stop.json").exists():
        return
    if any(s1_stage.stage_rows(gv.rows, s)["intent"] is not None for s in FINALIZATION):
        return                                           # (stop_check already decided that case)
    pre = [x for x in gv.rows if x.seq < stop.seq]
    if s1_stage.stage_rows(pre, "prereg")["created"] is None:
        rec = None                                       # no registered start: no committed history gives a stop
    else:
        try:
            pr = c.load_json(gv.out / "prereg.json")
            rec = stop_record(gv.out, pre, c.aware(pr["start"]), pr["calendar"], gv.trial.bundle)
        except (OSError, ValueError, KeyError, TypeError, b.BookError) as e:
            raise SystemExit(f"publication gap: the stop record cannot be recomputed ({type(e).__name__}: {e}): "
                             f"refused with no row (F2.3)") from None
    if rec is None or j.detail_of(rec) != stop.detail:
        s1_trial.invalidate(gv.trial, "stop-conflict", {"recomputed": None if rec is None else j.detail_of(rec),
                                                        "stop_line_sha256": stop.sha},
                            root=gv.root, mailbox=gv.mailbox)
        raise SystemExit("publication gap: the recomputed stop record differs: INVALID (stop-conflict) (F2.3)")
    try:
        persist_stop(gv.out, rec)
    except (OSError, SystemExit) as e:
        raise SystemExit(f"publication gap: stop.json not published ({type(e).__name__}: {e}): refused with no row "
                         f"(F2.3)") from None


def stop_problems(out: Path, start: datetime, calendar, *, recheck: bool = True, mailbox=None) -> list:
    """A2.3 (kept) + A3 F2: integrity of the frozen experiment through the persisted stop: stop.json's stop seal and
    every frozen slice it lists still exist with their sha256; no seal of an ELIGIBLE close <= the stop close (NO-
    VALID-SEAL: no eligible seal) is missing from its slices (r1 A4: ineligible and later seals are not sampled stop
    inputs - their integrity is the E2.6 / F4-table CREATED check, which stays); the recorded hashes agree. `recheck`
    (OQ-8): stop.json equals stop_record over the rows before the TRIAL-STOP and its detail is the STOP's. It can only
    refuse, never move the stop."""
    import s1_journal as j
    out = Path(out)
    st_ = load_stop(out)
    if st_ is None:
        return ["no persisted stop (s1_out/stop.json)"]
    probs = []
    sj = c.sha256_file(out / "stop.json")                  # fix round 1 (m-4): recorded hashes and the bundle
    for p in sorted((out / "captures").glob("*/*.report.json")):
        try:
            v = json.loads(p.read_text(encoding="utf-8")).get("stop_sha256")
        except (OSError, ValueError, AttributeError):
            continue
        if v not in (None, c.ABSENT, sj):
            probs.append(f"persisted stop (stop.json) changed since capture report {p.parent.name}/{p.name}")
            break
    if st_.get("bundle_sha256") != c.bundle_sha256():
        probs.append("persisted stop (stop.json) was not decided by the registered bundle")
    listed = st_.get("seals") or {}
    for rel, h in sorted(listed.items()):
        p = out / rel
        if not p.is_file():
            probs.append(f"frozen slice {rel} missing (persisted stop)")
        elif c.sha256_file(p) != h:
            probs.append(f"frozen slice {rel} changed since the persisted stop")
    if start is None or calendar is None:
        try:
            pr = c.load_json(out / "prereg.json")
            start, calendar = c.aware(pr["start"]), pr["calendar"]
        except (OSError, ValueError, KeyError, TypeError):
            start = calendar = None
    eligible = ({d["date"] for d in eligible_sessions(start, calendar)} if start is not None else None)
    ineligible = ({d["date"] for d in calendar} - eligible) if eligible is not None else set()
    sc = c.aware(st_["stop_close"]) if st_.get("stop_close") else None
    for p, x in _seal_index(out):
        rel = p.relative_to(out).as_posix()
        if rel in listed or p.stem in ineligible:        # r1 A4: an ineligible close's seal (opening, post-deadline)
            continue                                     # is required evidence via E2.6/F4, never a frozen slice
        if sc is None or c.aware(x["close"]) <= sc:
            probs.append(f"seal {rel} is not among the persisted stop's frozen slices")
    if sc is not None:
        sp = out / str(st_.get("stop_seal"))
        if not sp.is_file() or c.sha256_file(sp) != st_.get("stop_seal_sha256"):
            probs.append("persisted stop seal missing or changed")
    if probs or not recheck:
        return probs
    try:
        tr, rows = _journal(mailbox, out)
        stop = j.first(rows, "TRIAL-STOP")
        if stop is None:
            return ["stop.json exists with no TRIAL-STOP row (F2.2)"]
        again = stop_record(out, [x for x in rows if x.seq < stop.seq], start, calendar, tr.bundle)
        if again != st_ or j.detail_of(st_) != stop.detail:
            probs.append("persisted stop is not the record committed history gives before its TRIAL-STOP (OQ-8)")
    except (OSError, ValueError, KeyError, TypeError, b.BookError, SystemExit) as e:
        probs.append(f"persisted stop unverifiable: {type(e).__name__}: {e}")
    return probs
