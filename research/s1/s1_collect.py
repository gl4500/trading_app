"""S1 collectors (§4, §11, §13): metadata plan with planned START; opening audit (calendar + corporate actions,
NO prices) under S1-AUDIT-ACK; final acquisition (bars + corporate actions) under S1-ACQUIRE-ACK. One attempt each.
Only the pure corporate-action functions of the hash-pinned E1 collector are reused (validate_ca_page, classify_ca);
the network helpers below are S1's own so nothing is written into E1's module-level folders or date span."""
import json
import sqlite3
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import s1_books
import s1_common as c
import s1_gates as g
import s1_seal
import s1_trial

CAL_URL = c.CAL_URL
BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"
CA_URL = "https://data.alpaca.markets/v1/corporate-actions"
AUDIT_ACK = c.AUDIT_ACK               # Task 12 (A3/A8): binds the bundle too; token texts single-sourced in s1_common
ABSENT = c.ABSENT
CA_FIXED = {"region": "us", "data_quality": "all", "sort": "asc", "limit": 1000}          # E1 CA_PARAMS
LIMITS = ("Vendor coverage and publication lags are not guaranteed complete; corporate actions processed after "
          "the acquisition date are not known.")
MIN_LEAD_DAYS = 7                 # plan-time sanity floor; the registered rule is A5.4 (sessions after the AUDIT-ACK)
MIN_SESSIONS_BEFORE_START = 5     # A5.4: >= 5 NYSE sessions between the S1-AUDIT-ACK's recorded time and START
LAG_SESSIONS = s1_seal.FINAL_LAG_SESSIONS   # §13: no earlier than the close of the 3rd session after the stop
CAL_TAIL_DAYS = 14                # A5.1/mapping 4.5: calendar request = plan date .. deadline date + 14 calendar days
                                  # (room for the final lag; completeness is CHECKED on the pinned listing, A6)
MAX_PAGES = 200


class Structural(Exception):
    pass


def _out(root):
    return Path(root) / "s1_out"


def collector_sha() -> str:
    return c.sha256_file(Path(__file__).resolve())


def _json_text(obj) -> str:
    return json.dumps(obj, indent=1, sort_keys=True)


def json_sha256(obj) -> str:
    """Fix round 3 (M-2): the sha256 of the exact bytes _write_once publishes for `obj` (known BEFORE the write, so
    a stage can be registered before its artifact exists)."""
    return c.sha256_bytes(c.text_bytes(_json_text(obj)))


def _write_once(path: Path, obj) -> Path:
    """Write-once JSON artifact: fix round 3 (C-1) published atomically and exclusively (FileExistsError if it
    exists; never a partial file)."""
    c.publish_text_exclusive(path, _json_text(obj))
    return path


def _ny_date(t: datetime) -> str:
    return t.astimezone(c.NY).date().isoformat()


def _ny_instant(day: str, hhmm: str) -> datetime:
    return datetime.combine(date.fromisoformat(day), time.fromisoformat(hhmm), tzinfo=c.NY).astimezone(timezone.utc)


def write_plan(root, planned_start: datetime, opening_close: str, symbols, first_trade_date: str, *,
               mailbox=None) -> Path:
    """F9: the only command that runs without an open trial; it refuses once one is open (or the mailbox is
    unreadable, OQ-20). No provider request, live callback, journal write or priced work. F6.2: the trial_id."""
    s1_trial.require_no_open_trial(mailbox)
    if planned_start.tzinfo is None:
        raise ValueError("planned START must be an aware instant")
    now = c.now_utc()
    if planned_start < now + timedelta(days=MIN_LEAD_DAYS):
        raise ValueError(f"planned START must be at least {MIN_LEAD_DAYS} calendar days after the plan")
    deadline = s1_seal.deadline(planned_start)                           # Task 12 (A5.1): an aware instant
    dl = (deadline.astimezone(c.NY).date() + timedelta(days=CAL_TAIL_DAYS)).isoformat()
    return _write_once(_out(root) / "plan.json", {
        "trial_id": str(uuid.uuid4()),                               # F6.2: fixed here, carried by the AUDIT-ACK
        "planned_start": planned_start.isoformat(), "opening_close": opening_close, "created_utc": now.isoformat(),
        "deadline": deadline.isoformat(),
        "calendar_range": [_ny_date(now), dl], "ca_symbols": sorted(set(symbols)),
        "ca_range": [first_trade_date, planned_start.date().isoformat()], "collector_sha256": collector_sha(),
        "fetch_core_sha256": c.E1_FETCH_SHA, "bundle_sha256": c.bundle_sha256()})


def audit_token(root) -> str:
    """Task 12 (A3.2/A8.2): binds collector, plan, the S1 bundle and planned START (s1_common.audit_token)."""
    return c.audit_token(_out(root))


def _ack(ack_id: str, token: str, mailbox=None) -> dict:
    """The codex->claude experiments-prereg message `ack_id` must carry `token` as a standalone line and not be in the
    future. Task 11 (controller-added), I-5: read from `mailbox` (default s1_common.MAILBOX, the coordination
    mailbox), opened read-only (mode=ro URI: never created or written), never from the output root.
    (Task 12: single-sourced as s1_common.ack.)"""
    return c.ack(ack_id, token, mailbox)


def _approved_bundle(ack_id: str, prefix: str, mailbox=None):
    """Task 12 (A3.2): the bundle an ACK message approves (its one `prefix` line's bundle_sha256 field)."""
    try:
        return c.token_fields(c.ack_line(c.mailbox_message(ack_id, mailbox), prefix)).get("bundle_sha256")
    except sqlite3.Error as e:
        raise SystemExit(f"mailbox unreadable ({type(e).__name__}): refusing") from None


def _require_no_redirects(client) -> None:
    """Task 11 (controller-added), m-4: the injected client must not follow redirects (a redirect could send the key
    headers to another host); anything but follow_redirects is False is refused before any ACK or request."""
    if getattr(client, "follow_redirects", None) is not False:
        raise SystemExit("client refused: follow_redirects must be False")


def _reserve(dirpath: Path, ack: dict) -> None:
    try:
        dirpath.mkdir(parents=True, exist_ok=False)                         # one attempt: never reused
    except FileExistsError:
        raise SystemExit(f"{dirpath.name}: an attempt already exists; one attempt only") from None
    _write_once(dirpath / "attempt.json", {"reserved_utc": c.now_utc().isoformat(), "ack": ack})


def _headers(keys):
    return {"APCA-API-KEY-ID": keys[0], "APCA-API-SECRET-KEY": keys[1]}


def _write_page(path: Path, data: bytes, created: list) -> None:
    c.publish_exclusive(path, data)                       # raw page kept, never overwritten; fix round 3: atomic
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


# A7.2: the fields whose difference, for one provider action identity, is a conflict (type, dates, symbols, ratios)
RECONCILE_KEYS = ("type", "special", "foreign")


def _identity_view(rec: dict) -> dict:
    return {k_: v for k_, v in rec.items() if k_ in RECONCILE_KEYS or k_.endswith("_date") or k_.endswith("_symbol")
            or k_ == "symbol" or "rate" in k_}


def reconcile_actions(*record_lists) -> tuple:
    """Task 12 (A7.2): reconcile corporate-action records globally (across the audit, window and full-history
    acquisitions) by the provider's stable action identity. No pinned provider contract states that ids are scoped
    by type, so the identity is the id alone (conservative: a changed type is a conflict too, never a new identity).
    Identical records (type, dates, symbols, ratios) are kept once; any difference for one identity is a conflict:
    both versions are kept, marked effective_conflict (unknown timing, A7.3), and one problem record blocks the
    UNION of their affected symbols. Records without an identity stay (E1 classify_ca already made them problems).
    Returns (records, conflict problems)."""
    seen, out, problems = {}, [], []
    for recs in record_lists:
        for rec in recs:
            rid = rec.get("id")
            if not (isinstance(rid, str) and rid):
                out.append(rec)
                continue
            if rid not in seen:
                seen[rid] = rec
                out.append(rec)
                continue
            first = seen[rid]
            if _identity_view(first) == _identity_view(rec):
                continue                                       # identical duplicate
            syms = sorted({v for r_ in (first, rec) for k_, v in r_.items()
                           if (k_ == "symbol" or k_.endswith("_symbol")) and isinstance(v, str) and v}
                          | set(first.get("affected_symbols") or []) | set(rec.get("affected_symbols") or []))
            problems.append({"problem": "conflicting records for one provider action identity", "id": rid,
                             "types": sorted({str(first.get("type")), str(rec.get("type"))}),
                             "blocks_symbols": syms})
            first["effective_conflict"] = True
            out.append(dict(rec, effective_conflict=True))
    return out, problems


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
def _validate_calendar(cal, plan, ack) -> list:
    """§4 + Task 12 (A6, A5.4): the provider listing passes s1_seal.calendar_problems (non-empty, ordered as listed,
    unique, open < close, covers the opening close through the deadline instant + the final lag); planned START ==
    the open instant of its date; >= 5 session opens strictly between the S1-AUDIT-ACK's recorded time (`ack`) and
    START. Returns [(date, open_utc)]."""
    probs = s1_seal.calendar_problems(cal, plan)
    if probs:
        raise Structural("; ".join(probs))
    sessions = [(x["date"], _ny_instant(x["date"], x["open"])) for x in cal]
    start, acked = c.aware(plan["planned_start"]), c.aware(ack["created_utc"])
    if dict(sessions).get(_ny_date(start)) != start:
        raise Structural("planned START is not the regular open of a listed session")
    if sum(1 for _, o in sessions if acked < o < start) < MIN_SESSIONS_BEFORE_START:
        raise Structural(f"fewer than {MIN_SESSIONS_BEFORE_START} sessions between the AUDIT-ACK and START")
    return sessions


def do_audit(root, ack_id: str, client, keys, *, mailbox=None) -> dict:
    """One audit attempt under the exact AUDIT-ACK. Task 12: the bundle the ACK approves is compared FIRST (A3.2; no
    registration exists yet, so a mismatch is a refusal); the ACK must follow the plan it binds and precede planned
    START (A8.2); the manifest binds plan_sha256 and the bundle (A8.1); the calendar is pinned with its source,
    request parameters and retrieval time (A6)."""
    gv = s1_trial.gate(root, "audit", mailbox=mailbox)                  # A3 F0.6: open trial, state, bundle first
    _require_no_redirects(client)
    out = _out(root)
    c.bundle_gate(out, _approved_bundle(ack_id, "S1-AUDIT-ACK", mailbox),          # fix round 1 (m-1): persisted
                  registered=c.is_registered(out, mailbox), where="audit")          # once registered (B3.1)
    c.registration_gate(out, "audit", mailbox=mailbox)                  # fix round 2 (B3.3): re-entry is gated
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    ack = s1_trial.verify_current(gv, "S1-AUDIT-ACK", ack_id)          # A3: field by field (F6.1, F6.5)
    if not c.aware(ack["created_utc"]) > c.aware(plan["created_utc"]):
        raise SystemExit("audit refused: the AUDIT-ACK is not after the plan it binds")
    if c.aware(plan["planned_start"]) <= c.now_utc():
        raise SystemExit("planned START has passed: re-register")
    d = out / "audit"
    _reserve(d, ack)
    created = []
    cutoff = _ny_date(c.now_utc())

    def body():
        params = {"start": plan["calendar_range"][0], "end": plan["calendar_range"][1], "date_type": "TRADING"}
        cal = _get(client, CAL_URL, params, _headers(keys), d / "pages" / "calendar.json", created)
        retrieved = c.now_utc()
        sessions = _validate_calendar(cal, plan, ack)
        page = d / "pages" / "calendar.json"
        _write_once(d / "calendar_source.json", {"source": CAL_URL, "params": params,              # A6 pin
                                                 "retrieved_utc": retrieved.isoformat(),
                                                 "page": page.relative_to(out).as_posix(),
                                                 "page_sha256": c.sha256_file(page)})
        actions, problems = _corporate_actions(client, keys, plan["ca_symbols"], plan["ca_range"][0], cutoff,
                                               d / "pages", created)
        _write_once(d / "calendar.json", cal)
        _write_once(d / "corporate_actions.json", actions)
        _write_once(d / "ca_problems.json", problems)
        return {"calendar_sessions": len(sessions), "ca_records": len(actions), "ca_problems": len(problems)}
    return _run_attempt(d, out, ack, created, body, {"publication_cutoff": cutoff,
                                                      "ca_window": [plan["ca_range"][0], cutoff],
                                                      "plan_sha256": c.sha256_file(out / "plan.json"),   # A8.1
                                                      "bundle_sha256": c.bundle_sha256()})            # A3.1


# ------------------------------------------------------------------ final
def _load(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _stop_state(out: Path, now: datetime) -> tuple:
    """Task 11 (controller-added), I-4: (prereg, stop decision, stop seal path, stop seal) of a trial that has
    STOPPED or TIMED OUT, from the seals (the same stop_decision the score uses). Refuses with no prereg, once
    aborted.json exists (nothing to acquire), on bad seal records, and while RUNNING / NO-VALID-SEAL."""
    if not (out / "prereg.json").exists():
        raise SystemExit("final plan refused: no prereg (the trial never started)")
    if c.load_abort(out) is not None:
        raise SystemExit("final plan refused: the trial is ABORTED-INVALID (nothing to acquire)")
    pr = _load(out / "prereg.json")
    try:                                                   # Task 12 (A2.1/A7.1): the PERSISTED stop
        import s1_checkpoint                               # fix round 3 (I-1): finalize BEFORE freezing the stop
        s1_checkpoint.finalize_pending(out, pr["calendar"], c.aware(pr["start"]), now)
        st = s1_seal.current_stop(out, c.aware(pr["start"]), pr["calendar"], now, "final plan")
    except (ValueError, KeyError, TypeError) as e:
        raise SystemExit(f"final plan refused: bad seal record ({type(e).__name__}: {e})") from None
    if st["status"] not in ("STOPPED", "TIMEOUT"):
        raise SystemExit(f"final plan refused: the trial is {st['status']} (RUNNING = no stop yet)")
    probs = s1_seal.stop_problems(out, c.aware(pr["start"]), pr["calendar"], recheck=False)
    if probs:
        raise SystemExit(f"final plan refused: the persisted stop does not verify ({probs})")
    stop_p = out / s1_seal.load_stop(out)["stop_seal"]
    return pr, st, stop_p, _load(stop_p)


def final_plan_record(root, now: datetime = None, mailbox=None) -> dict:
    """Task 11 (controller-added), I-4: the final plan DERIVED from the stop seal - no hand-typed stop or symbols.
    Cohort symbols = BUYs with START <= stored time <= stop close; carry-in symbols = held at START by the pre-START
    rows (opening rows and bridge rows, bridge-introduced tickers included); MR history starts at its first row."""
    out = _out(root)
    c.verify_bundle_first(out, "final plan", mailbox=mailbox)           # fix round 2 (B3): gate first
    if (out / "prereg.json").exists():
        g.verified_registration(out, "final plan", mailbox)            # Task 12: A3.2 bundle first, then A8.2
    pr, st, stop_p, seal = _stop_state(out, c.now_utc() if now is None else now)
    start, stop = c.aware(pr["start"]), c.aware(st["stop_close"])
    try:
        asof = [t for t in seal["trades"] if c.aware(t["ts"]) <= stop]
        cohort = sorted({t["symbol"] for t in s1_seal.cohort(asof, start, stop)})
        carry = sorted(s1_books.held_symbols(s1_seal.split_bridge(asof, start)[0], start))
    except (s1_books.BookError, KeyError, ValueError, TypeError) as e:
        raise SystemExit(f"final plan refused: stop seal ledger unreadable ({type(e).__name__}: {e})") from None
    return {"stop_close": st["stop_close"], "stop_status": st["status"], "stop_date": _ny_date(stop),
            "stop_seal_sha256": c.sha256_file(stop_p), "stop_sha256": c.sha256_file(out / "stop.json"),
            "bar_symbols": sorted(set(cohort) | set(carry)),
            "ca_symbols_window": cohort, "ca_symbols_full_history": carry,
            "full_history_start": min((_ny_date(c.aware(t["ts"])) for t in asof), default=_ny_date(start)),
            "collector_sha256": collector_sha(), "fetch_core_sha256": c.E1_FETCH_SHA}


def _stop_attestation(out: Path, plan: dict) -> dict:
    """Task 11 (controller-added), I-4: the stop attestation must exist and bind this stop and its stop seal."""
    p = out / "attest_stop.json"
    if not p.exists():
        raise SystemExit("final refused: no stop attestation recorded (s1_run.attest_stop comes first)")
    a = _load(p)
    try:
        same = (c.aware(a["stop_close"]) == c.aware(plan["stop_close"])
                and a.get("sealed_final_ledger_sha256") == plan["stop_seal_sha256"]
                and a.get("stop_sha256") == plan.get("stop_sha256"))                  # Task 12 (A2.1/A7.1)
        c.aware(a["recorded_utc"])
    except (KeyError, ValueError, TypeError):
        same = False
    if not same:
        raise SystemExit("final refused: the stop attestation does not bind this stop and stop seal")
    return a


def write_final_plan(root, *, mailbox=None) -> Path:
    """Task 11 (controller-added), I-4: write-once final plan, derived (final_plan_record), only after the stop
    attestation."""
    gv = s1_trial.gate(root, "final plan", mailbox=mailbox)             # A3 F0.6: open trial, state, bundle first
    rec = final_plan_record(root, mailbox=mailbox)
    _stop_attestation(_out(root), rec)
    return _write_once(_out(root) / "final_plan.json", rec)


def acquire_token(root, mailbox=None) -> str:
    """Binds collector, final plan, prereg, the stop attestation and (Task 12, A7.1) the bundle; A3: the trial and
    journal fields from `mailbox` (s1_trial.token)."""
    return c.acquire_token(_out(root), mailbox)


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


def do_final(root, ack_id: str, client, keys, *, mailbox=None) -> dict:
    """One final acquisition under the exact ACQUIRE-ACK. Task 11 (controller-added), I-4: before reserving it
    re-derives the final plan from the stop seal (STOPPED/TIMEOUT, no aborted.json) and requires the stored plan to
    equal it, the stop attestation to bind that stop, and the ACK to be strictly after the stop attestation."""
    gv = s1_trial.gate(root, "final acquisition", mailbox=mailbox)      # A3 F0.6: open trial, state, bundle first
    _require_no_redirects(client)
    out = _out(root)
    g.verified_registration(out, "final acquisition", mailbox)        # Task 12: A3.2 bundle first, then A8.2
    fp, prp = out / "final_plan.json", out / "prereg.json"
    plan = json.loads(fp.read_text(encoding="utf-8"))
    ack = s1_trial.verify_current(gv, "S1-ACQUIRE-ACK", ack_id)        # A3: field by field (F6.1, F6.5, F7.1)
    rec = final_plan_record(root, mailbox=mailbox)
    if plan != rec:
        raise SystemExit("final refused: final_plan.json is not the plan derived from the stop seal")
    att = _stop_attestation(out, rec)
    if c.aware(ack["created_utc"]) <= c.aware(att["recorded_utc"]):
        raise SystemExit("final refused: the ACQUIRE-ACK is not strictly after the stop attestation")
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
        actions, conflicts = reconcile_actions(ca_win, ca_full)          # Task 12 (A7.2): one global set
        for name, obj in (("bars.json", bars), ("bar_problems.json", bar_problems),
                          ("corporate_actions.json", actions), ("ca_problems.json", p1 + p2 + conflicts)):
            _write_once(d / name, obj)
        per_symbol = {s: {"present": len(bars[s]), "missing": len(sessions) - len(bars[s])} for s in bars}
        return {"bars": per_symbol, "bar_problems": len(bar_problems), "ca_records": len(actions),
                "ca_problems": len(p1) + len(p2) + len(conflicts), "ca_conflicts": len(conflicts)}
    return _run_attempt(d, out, ack, created, body, {
        "publication_cutoff": cutoff, "prereg_sha256": c.sha256_file(prp), "earliest_acquire_utc": earliest.isoformat(),
        "final_plan_sha256": c.sha256_file(fp), "attest_stop_sha256": c.sha256_file(out / "attest_stop.json"),
        "bundle_sha256": c.bundle_sha256(),                                                    # Task 12 (A3.4)
        "stop_sha256": c.sha256_file(out / "stop.json"),                                       # Task 12 (A2.1)
        "bars_window": [_utc_z(bars_start), _utc_z(bars_end, micro=True)]})
