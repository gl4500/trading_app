"""S1 collectors (§4, §11, §13): metadata plan with planned START; opening audit (calendar + corporate actions,
NO prices) under S1-AUDIT-ACK; final acquisition (bars + corporate actions) under S1-ACQUIRE-ACK. One attempt each.
Only the pure corporate-action functions of the hash-pinned E1 collector are reused (validate_ca_page, classify_ca);
the network helpers below are S1's own so nothing is written into E1's module-level folders or date span."""
import json
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import s1_common as c
import s1_seal

CAL_URL = "https://paper-api.alpaca.markets/v2/calendar"
BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"
CA_URL = "https://data.alpaca.markets/v1/corporate-actions"
AUDIT_ACK = "S1-AUDIT-ACK collector_sha256={collector} plan_sha256={plan} start={start}"
ACQUIRE_ACK = "S1-ACQUIRE-ACK collector_sha256={collector} final_plan_sha256={plan} prereg_sha256={prereg}"
CA_FIXED = {"region": "us", "data_quality": "all", "sort": "asc", "limit": 1000}          # E1 CA_PARAMS
LIMITS = ("Vendor coverage and publication lags are not guaranteed complete; corporate actions processed after "
          "the acquisition date are not known.")
MIN_LEAD_DAYS = 7                 # proxy for >= 5 NYSE sessions between plan review and START (§4)
MIN_SESSIONS_BEFORE_START = 5
LAG_SESSIONS = 3                  # §13: no earlier than the close of the 3rd session after the stop
MAX_PAGES = 200


class Structural(Exception):
    pass


def _out(root):
    return Path(root) / "s1_out"


def collector_sha() -> str:
    return c.sha256_file(Path(__file__).resolve())


def _write_once(path: Path, obj) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as f:
        f.write(json.dumps(obj, indent=1, sort_keys=True))
    return path


def _ny_date(t: datetime) -> str:
    return t.astimezone(c.NY).date().isoformat()


def _ny_instant(day: str, hhmm: str) -> datetime:
    return datetime.combine(date.fromisoformat(day), time.fromisoformat(hhmm), tzinfo=c.NY).astimezone(timezone.utc)


def write_plan(root, planned_start: datetime, opening_close: str, symbols, first_trade_date: str) -> Path:
    if planned_start.tzinfo is None:
        raise ValueError("planned START must be an aware instant")
    now = c.now_utc()
    if planned_start < now + timedelta(days=MIN_LEAD_DAYS):
        raise ValueError(f"planned START must be at least {MIN_LEAD_DAYS} calendar days after the plan")
    dl = (planned_start + timedelta(days=200)).date().isoformat()          # covers deadline + 3 sessions
    return _write_once(_out(root) / "plan.json", {
        "planned_start": planned_start.isoformat(), "opening_close": opening_close, "created_utc": now.isoformat(),
        "deadline": s1_seal.deadline(planned_start).isoformat(),
        "calendar_range": [_ny_date(now), dl], "ca_symbols": sorted(set(symbols)),
        "ca_range": [first_trade_date, planned_start.date().isoformat()], "collector_sha256": collector_sha(),
        "fetch_core_sha256": c.E1_FETCH_SHA})


def audit_token(root) -> str:
    plan = _out(root) / "plan.json"
    p = json.loads(plan.read_text(encoding="utf-8"))
    return AUDIT_ACK.format(collector=collector_sha(), plan=c.sha256_file(plan), start=p["planned_start"])


def _ack(root, ack_id: str, token: str) -> dict:
    con = sqlite3.connect(f"file:{(Path(root) / 'mailbox.sqlite3').as_posix()}?mode=ro", uri=True)
    try:
        row = con.execute("SELECT sender, recipient, request_key, body, created FROM messages WHERE id=?",
                          (ack_id,)).fetchone()
    finally:
        con.close()
    if row is None or row[:3] != ("codex", "claude", "experiments-prereg"):
        raise SystemExit(f"{ack_id!r} is not a codex->claude experiments-prereg message")
    if token not in [ln.rstrip("\r") for ln in (row[3] or "").split("\n")]:
        raise SystemExit(f"ack lacks the standalone line: {token}")
    t = datetime.fromtimestamp(row[4], tz=timezone.utc)
    if t > c.now_utc():
        raise SystemExit("ack is in the future")
    return {"ack_id": ack_id, "created_utc": t.isoformat()}


def _reserve(dirpath: Path, ack: dict) -> None:
    try:
        dirpath.mkdir(parents=True, exist_ok=False)                         # one attempt: never reused
    except FileExistsError:
        raise SystemExit(f"{dirpath.name}: an attempt already exists; one attempt only") from None
    _write_once(dirpath / "attempt.json", {"reserved_utc": c.now_utc().isoformat(), "ack": ack})


def _headers(keys):
    return {"APCA-API-KEY-ID": keys[0], "APCA-API-SECRET-KEY": keys[1]}


def _write_page(path: Path, data: bytes, created: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as f:                                            # raw page kept, never overwritten
        f.write(data)
    created.append(path)


def _get(client, url, params, headers, page_path: Path, created):
    try:
        resp = client.get(url, params=params, headers=headers)
    except Exception as e:                                                # transport failure: no secrets in text
        raise Structural(f"{page_path.name}: transport error {type(e).__name__}") from None
    _write_page(page_path, resp.content, created)
    if resp.status_code != 200:
        raise Structural(f"{page_path.name}: HTTP {resp.status_code}")
    try:
        return json.loads(resp.content)
    except ValueError:
        raise Structural(f"{page_path.name}: body is not JSON") from None


def _paged(client, url, base, headers, prefix: Path, validate, created) -> list:
    pages, token, seen = [], None, set()
    for n in range(MAX_PAGES):
        params = dict(base, **({"page_token": token} if token else {}))
        data = _get(client, url, params, headers, prefix.with_name(f"{prefix.name}_page{n:03d}.json"), created)
        if validate:
            validate(data, f"{prefix.name}_page{n:03d}")
        pages.append(data)
        token = data.get("next_page_token")
        if not token:
            return pages
        if token in seen:
            raise Structural(f"{prefix.name}: repeated next_page_token")
        seen.add(token)
    raise Structural(f"{prefix.name}: more than {MAX_PAGES} pages")


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _validate_bars_page(data, where) -> None:
    """Structural defects abort (E1 validate_bars_page discipline); bad bar VALUES become problem records."""
    if not isinstance(data, dict) or not isinstance(data.get("bars"), dict):
        raise Structural(f"{where}: 'bars' missing or not an object")
    if "next_page_token" not in data:
        raise Structural(f"{where}: next_page_token key missing (explicit null required on the last page)")
    tok = data["next_page_token"]
    if tok is not None and not (isinstance(tok, str) and tok):
        raise Structural(f"{where}: malformed next_page_token")
    for sym, rows in data["bars"].items():
        if not isinstance(rows, list):
            raise Structural(f"{where}: bars[{sym!r}] not a list")
        for b in rows:
            if not isinstance(b, dict) or any(k_ not in b for k_ in ("t", "o", "h", "l", "c")):
                raise Structural(f"{where}: malformed bar for {sym!r}")
            if not all(_is_num(b[k_]) for k_ in ("o", "h", "l", "c")):
                raise Structural(f"{where}: non-numeric OHLC for {sym!r}")
            try:
                c.aware(b["t"])
            except (ValueError, TypeError):
                raise Structural(f"{where}: bad bar time for {sym!r}") from None


def _parse_bars(symbols, pages, sessions):
    """{symbol: {session_date: {date,o,h,l,c}}} + problems; finite positive OHLC with l <= min(o,c) <= max(o,c) <= h,
    stamped at New York midnight, one bar per (symbol, session), only requested symbols and sessions; anything
    else is a problem record."""
    want, sess = set(symbols), set(sessions)
    out, problems = {s: {} for s in symbols}, []
    for page in pages:
        for sym, rows in (page.get("bars") or {}).items():
            if sym not in want:
                problems.append({"symbol": sym, "session": None, "problem": "unrequested symbol"})
                continue
            for bar in rows:
                local = c.aware(bar["t"]).astimezone(c.NY)
                d = local.date().isoformat()
                if (local.hour, local.minute, local.second, local.microsecond) != (0, 0, 0, 0):
                    problems.append({"symbol": sym, "session": d, "problem": "bar start not New York midnight"})
                    continue
                o, h, l, cl = (bar.get(k_) for k_ in ("o", "h", "l", "c"))
                ok = all(_is_num(v) and v == v and 0 < v < float("inf") for v in (o, h, l, cl))
                if d not in sess or not ok or not (l <= min(o, cl) <= max(o, cl) <= h) or d in out[sym]:
                    problems.append({"symbol": sym, "session": d, "problem": "invalid, duplicate or off-calendar bar"})
                    continue
                out[sym][d] = {"date": d, "o": o, "h": h, "l": l, "c": cl}
    for sym in symbols:
        for d in sessions:
            if d not in out[sym]:
                problems.append({"symbol": sym, "session": d, "problem": "missing session"})
    return out, problems


def _corporate_actions(client, keys, symbols, start, end, pages_dir, created):
    f = c.fetch()
    batched = []
    for i in range(0, len(symbols), 50):
        batch = symbols[i:i + 50]
        base = dict(CA_FIXED, symbols=",".join(batch), start=start, end=end)
        for page in _paged(client, CA_URL, base, _headers(keys), pages_dir / f"ca_{i // 50:03d}",
                           f.validate_ca_page, created):
            batched.append((batch, page))
    return f.classify_ca(batched)


# ------------------------------------------------------------------ attempts: manifest / ABORTED
def _page_hashes(out: Path, created) -> dict:
    return {p.relative_to(out).as_posix(): c.sha256_file(p) for p in sorted(created) if p.exists()}


def _abort(d: Path, out: Path, ack: dict, created, e: Exception):
    """ABORTED manifest (exclusive). Only an S1/E1 Structural's text is recorded (key-free by construction);
    anything else records the exception TYPE NAME only. All pages stay, hashed."""
    structural = isinstance(e, (Structural, c.fetch().Structural))
    _write_once(d / "manifest.json", {
        "outcome": "ABORTED", "error_type": type(e).__name__, "error": str(e) if structural else type(e).__name__,
        "ack": ack, "pages": _page_hashes(out, created)})
    raise SystemExit(f"{d.name}: ABORTED ({type(e).__name__}); attempt preserved, see manifest.json") from None


def _run_attempt(d: Path, out: Path, ack: dict, created: list, body, head: dict) -> dict:
    try:
        coverage = body()
    except Exception as e:
        _abort(d, out, ack, created, e)
    files = {p.name: c.sha256_file(p) for p in sorted(d.glob("*.json")) if p.name != "manifest.json"}
    manifest = dict(head, outcome="COMPLETE", ack=ack, files=files, pages=_page_hashes(out, created),
                    coverage=coverage, limits=LIMITS)
    _write_once(d / "manifest.json", manifest)
    return json.loads((d / "manifest.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ audit
def _validate_calendar(cal, plan) -> list:
    """§4: non-empty list of {date, open, close}; planned START == open instant of its date; >= 5 sessions strictly
    between the plan's creation and START; covers deadline + 3 sessions. Returns [(date, open_utc)]."""
    if not isinstance(cal, list) or not cal:
        raise Structural("calendar is not a non-empty list")
    sessions = []
    for x in cal:
        if not isinstance(x, dict) or any(not isinstance(x.get(k_), str) for k_ in ("date", "open", "close")):
            raise Structural("calendar entry lacks date/open/close")
        try:
            sessions.append((x["date"], _ny_instant(x["date"], x["open"])))
            _ny_instant(x["date"], x["close"])
        except ValueError:
            raise Structural("calendar entry has an unparseable date/time") from None
    start, created = c.aware(plan["planned_start"]), c.aware(plan["created_utc"])
    if dict(sessions).get(_ny_date(start)) != start:
        raise Structural("planned START is not the regular open of a listed session")
    if sum(1 for _, o in sessions if created < o < start) < MIN_SESSIONS_BEFORE_START:
        raise Structural(f"fewer than {MIN_SESSIONS_BEFORE_START} sessions between the plan and START")
    if sum(1 for d_, _ in sessions if d_ > plan["deadline"]) < 3:
        raise Structural("calendar does not cover the deadline plus 3 sessions")
    return sessions


def do_audit(root, ack_id: str, client, keys) -> dict:
    out = _out(root)
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    ack = _ack(root, ack_id, audit_token(root))
    if c.aware(plan["planned_start"]) <= c.now_utc():
        raise SystemExit("planned START has passed: re-register")
    d = out / "audit"
    _reserve(d, ack)
    created = []
    cutoff = _ny_date(c.now_utc())

    def body():
        cal = _get(client, CAL_URL, {"start": plan["calendar_range"][0], "end": plan["calendar_range"][1],
                                     "date_type": "TRADING"}, _headers(keys), d / "pages" / "calendar.json", created)
        sessions = _validate_calendar(cal, plan)
        actions, problems = _corporate_actions(client, keys, plan["ca_symbols"], plan["ca_range"][0], cutoff,
                                               d / "pages", created)
        _write_once(d / "calendar.json", cal)
        _write_once(d / "corporate_actions.json", actions)
        _write_once(d / "ca_problems.json", problems)
        return {"calendar_sessions": len(sessions), "ca_records": len(actions), "ca_problems": len(problems)}
    return _run_attempt(d, out, ack, created, body, {"publication_cutoff": cutoff,
                                                      "ca_window": [plan["ca_range"][0], cutoff]})


# ------------------------------------------------------------------ final
def write_final_plan(root, stop_close: str, symbols, carry_in_symbols, first_trade_date: str) -> Path:
    stop_day = _ny_date(c.aware(stop_close))
    return _write_once(_out(root) / "final_plan.json", {
        "stop_close": stop_close, "bar_symbols": sorted(set(symbols) | set(carry_in_symbols)),
        "ca_symbols_window": sorted(set(symbols)), "ca_symbols_full_history": sorted(set(carry_in_symbols)),
        "full_history_start": first_trade_date, "stop_date": stop_day, "collector_sha256": collector_sha(),
        "fetch_core_sha256": c.E1_FETCH_SHA})


def _earliest_acquire(calendar, stop_day: str) -> datetime:
    """Close of the 3rd session after the stop session, from the pinned (prereg) calendar."""
    try:
        days = sorted(calendar, key=lambda x: x["date"])
        idx = [x["date"] for x in days].index(stop_day)
        return _ny_instant(days[idx + LAG_SESSIONS]["date"], days[idx + LAG_SESSIONS]["close"])
    except (ValueError, IndexError, KeyError, TypeError):
        raise SystemExit("prereg calendar cannot place the 3rd session after the stop: refusing") from None


def _utc_z(t: datetime, micro: bool = False) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ" if micro else "%Y-%m-%dT%H:%M:%SZ")


def do_final(root, ack_id: str, client, keys) -> dict:
    out = _out(root)
    fp, prp = out / "final_plan.json", out / "prereg.json"
    plan = json.loads(fp.read_text(encoding="utf-8"))
    ack = _ack(root, ack_id, ACQUIRE_ACK.format(collector=collector_sha(), plan=c.sha256_file(fp),
                                                prereg=c.sha256_file(prp)))
    pr = json.loads(prp.read_text(encoding="utf-8"))
    earliest = _earliest_acquire(pr["calendar"], plan["stop_date"])
    if c.now_utc() < earliest:
        raise SystemExit(f"acquisition lag not met: not before {earliest.isoformat()}")
    d = out / "final"
    _reserve(d, ack)
    created = []
    cutoff = _ny_date(c.now_utc())
    start_day = _ny_date(c.aware(pr["start"]))
    sessions = [x["date"] for x in pr["calendar"] if start_day <= x["date"] <= plan["stop_date"]]
    bars_start = _ny_instant(start_day, "00:00")
    bars_end = _ny_instant((date.fromisoformat(plan["stop_date"]) + timedelta(days=1)).isoformat(),
                           "00:00") - timedelta(microseconds=1)

    def body():
        bar_pages = _paged(client, BARS_URL, {"symbols": ",".join(plan["bar_symbols"]), "timeframe": "1Day",
                                              "start": _utc_z(bars_start), "end": _utc_z(bars_end, micro=True),
                                              "adjustment": "raw", "feed": "sip", "limit": 10000},
                           _headers(keys), d / "pages" / "bars", _validate_bars_page, created)
        bars, bar_problems = _parse_bars(plan["bar_symbols"], bar_pages, sessions)
        ca_win, p1 = _corporate_actions(client, keys, plan["ca_symbols_window"], start_day, cutoff,
                                        d / "pages", created)
        ca_full, p2 = _corporate_actions(client, keys, plan["ca_symbols_full_history"], plan["full_history_start"],
                                         cutoff, d / "pages_full", created)
        for name, obj in (("bars.json", bars), ("bar_problems.json", bar_problems),
                          ("corporate_actions.json", ca_win + ca_full), ("ca_problems.json", p1 + p2)):
            _write_once(d / name, obj)
        per_symbol = {s: {"present": len(bars[s]), "missing": len(sessions) - len(bars[s])} for s in bars}
        return {"bars": per_symbol, "bar_problems": len(bar_problems), "ca_records": len(ca_win) + len(ca_full),
                "ca_problems": len(p1) + len(p2)}
    return _run_attempt(d, out, ack, created, body, {
        "publication_cutoff": cutoff, "prereg_sha256": c.sha256_file(prp), "earliest_acquire_utc": earliest.isoformat(),
        "bars_window": [_utc_z(bars_start), _utc_z(bars_end, micro=True)]})
