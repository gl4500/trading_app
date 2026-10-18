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


# ------------------------------------------------------------------ A2: the persisted stop (s1_out/stop.json)
def _seal_index(out: Path) -> list:
    out = Path(out)
    return [(p, json.loads(p.read_text(encoding="utf-8"))) for p in sorted((out / "seals").glob("*.json"))]


def stop_record(out: Path, decision: dict, start: datetime, decided_utc: datetime, by: str) -> dict:
    """A2.1: the stop identity persisted once - status, stop close, the authoritative stop seal file and sha256, the
    cohort row ids (START <= stored entry <= stop close, from the stop seal's rows), the decision time - plus the
    frozen slices (every seal of a close <= the stop close; NO-VALID-SEAL: every seal) with their sha256, and the
    bundle that decided it."""
    out = Path(out)
    idx = _seal_index(out)
    stop_close = decision.get("stop_close")
    rec = {"status": decision["status"], "stop_close": stop_close, "missed": decision.get("missed", []),
           "decided_utc": decided_utc.isoformat(), "decided_by": by, "bundle_sha256": c.bundle_sha256(),
           "stop_seal": None, "stop_seal_sha256": None, "cohort_row_ids": []}
    if stop_close is not None:
        sc = c.aware(stop_close)
        sp = out / "seals" / f"{sc.astimezone(c.NY).date().isoformat()}.json"
        seal = json.loads(sp.read_text(encoding="utf-8"))
        rec.update(stop_seal=sp.relative_to(out).as_posix(), stop_seal_sha256=c.sha256_file(sp),
                   cohort_row_ids=sorted(t["id"] for t in cohort(
                       [t for t in seal["trades"] if c.aware(t["ts"]) <= sc], start, sc)))
        rec["seals"] = {p.relative_to(out).as_posix(): c.sha256_file(p) for p, x in idx
                        if c.aware(x["close"]) <= sc}
    else:
        rec["seals"] = {p.relative_to(out).as_posix(): c.sha256_file(p) for p, _ in idx}
    return rec


def persist_stop(out: Path, rec: dict) -> dict:
    """A2.1: write s1_out/stop.json exclusively (never recomputed, never replaced). FileExistsError if it exists.
    Addendum 2 B3.1/B3.3: the persisted stop is then recorded in the registry (registry/stop.json and, fix round 3
    C-2, witnesses/stop.json: its sha256) - a frozen trial artifact. Fix round 3 (C-1): published atomically, so a
    concurrent decider never reads a partial stop.json; stop.json is published FIRST (the first decider wins, its
    records follow), so its records are optional to the registration gate but must agree."""
    p = Path(out) / "stop.json"
    c.publish_text_exclusive(p, json.dumps(rec, indent=1, sort_keys=True))
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


def current_stop(out: Path, start: datetime, calendar, now: datetime, by: str) -> dict:
    """A2.1: the trial state: the persisted stop if it exists; otherwise the stop decision over the seals (today =
    now) - persisted once if it has ended (STOPPED / TIMEOUT / NO-VALID-SEAL; a concurrent first writer wins).
    Returns a stop_decision-shaped dict ({"status", "stop_close", "missed"}, plus "persisted")."""
    st_ = load_stop(out)
    if st_ is None and stop_was_persisted(out):            # fix round 1 (m-4): never a silent recompute
        raise ValueError("persisted stop (stop.json) missing after it was persisted")
    if st_ is None:
        dec = stop_decision([s for _, s in _seal_index(out)], start, calendar, today=now,
                            pending=pending_closes(out))                    # fix round 2 (B1.5)
        if dec["status"] not in ENDED:
            return dict(dec, persisted=False)
        try:
            st_ = persist_stop(out, stop_record(out, dec, start, now, by))
        except FileExistsError:
            st_ = load_stop(out)
    return {"status": st_["status"], "stop_close": st_["stop_close"], "missed": st_.get("missed", []),
            "persisted": True}


def stop_problems(out: Path, start: datetime, calendar, *, recheck: bool = True) -> list:
    """A2.3: integrity of the frozen experiment through the persisted stop: stop.json's stop seal and every frozen
    slice it lists still exist with their sha256, no seal of a close <= the stop close (NO-VALID-SEAL: no seal at
    all) was added, its cohort ids are the stop seal's, and (`recheck`, used by the score) the same registered
    helpers over the frozen slices at the decision time give the same stop - a consistency check that can only
    refuse, never move the stop (the stop used is always stop.json's)."""
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
    sc = c.aware(st_["stop_close"]) if st_.get("stop_close") else None
    for p, x in _seal_index(out):
        rel = p.relative_to(out).as_posix()
        if rel not in listed and (sc is None or c.aware(x["close"]) <= sc):
            probs.append(f"seal {rel} is not among the persisted stop's frozen slices")
    if sc is not None:
        sp = out / str(st_.get("stop_seal"))
        if not sp.is_file() or c.sha256_file(sp) != st_.get("stop_seal_sha256"):
            probs.append("persisted stop seal missing or changed")
    if probs or not recheck:
        return probs
    try:
        frozen = [json.loads((out / rel).read_text(encoding="utf-8")) for rel in sorted(listed)]
        again = stop_decision(frozen, start, calendar, today=c.aware(st_["decided_utc"]))
        if (again["status"], again["stop_close"]) != (st_["status"], st_["stop_close"]):
            probs.append(f"persisted stop {st_['status']} {st_['stop_close']} is not the frozen slices' stop "
                         f"{again['status']} {again['stop_close']}")
        if sc is not None:
            seal = json.loads((out / st_["stop_seal"]).read_text(encoding="utf-8"))
            ids = sorted(t["id"] for t in cohort([t for t in seal["trades"] if c.aware(t["ts"]) <= sc], start, sc))
            if ids != st_.get("cohort_row_ids"):
                probs.append("persisted stop cohort ids differ from the stop seal's cohort")
    except (OSError, ValueError, KeyError, TypeError, b.BookError) as e:
        probs.append(f"persisted stop unverifiable: {type(e).__name__}: {e}")
    return probs
