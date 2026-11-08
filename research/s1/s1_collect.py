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
import s1_stage
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
CA_BATCH = 50                     # F4.9: batch i = symbols[50i : 50i+50] (single-sourced)
CA_FAMILY = "corporate_actions"


class Structural(Exception):
    pass


# ------------------------------------------------------------------ A3 F4.6 request policy (Task 9)
def audit_policy(plan: dict, cutoff: str) -> dict:
    """F4.6/F4.9: the audit's deterministic request policy (committed by its INTENT; no request list, no host list:
    a request is authorized only by its family's exact URL)."""
    syms = list(plan["ca_symbols"])
    batches = [syms[i:i + CA_BATCH] for i in range(0, len(syms), CA_BATCH)]
    return {"redirects": False, "max_pages": MAX_PAGES, "cutoff": cutoff, "families": [
        {"name": "calendar", "url": CAL_URL, "scope": "audit", "batches": None,
         "base_params": {"start": plan["calendar_range"][0], "end": plan["calendar_range"][1],
                         "date_type": "TRADING"},
         "paged": False, "page_template": "audit/pages/calendar.json"},
        {"name": CA_FAMILY, "url": CA_URL, "scope": "audit", "batches": batches,
         "base_params": [dict(CA_FIXED, symbols=",".join(b), start=plan["ca_range"][0], end=cutoff) for b in batches],
         "paged": True, "page_template": "audit/pages/ca_{i:03d}_page{n:03d}.json"}]}


class _Authorizer:
    """F4.6 request path: each request must be the next one the committed policy allows (family and scope in
    order; the exact family URL; the exact base parameters of the current batch; page n+1 adds only the page_token of
    the immediately preceding validated page; at most max_pages pages; one request for an unpaged family) - checked
    BEFORE it is sent. Every request sent is recorded in provenance (credential-free)."""

    def __init__(self, policy: dict):
        self.policy, self.provenance = policy, []
        self.slots = []
        for fi, fam in enumerate(policy["families"]):
            self.slots += [(fi, None)] if fam["batches"] is None else [(fi, bi) for bi in range(len(fam["batches"]))]
        self.pos, self.n, self.token, self.seen, self.last_rel = 0, 0, None, set(), None

    def _current(self):
        if self.pos >= len(self.slots):
            raise Structural("a request with no family left in the policy (F4.6)")
        fi, bi = self.slots[self.pos]
        fam = self.policy["families"][fi]
        return fam, bi, (fam["base_params"][bi] if bi is not None else fam["base_params"])

    def authorize(self, family: str, scope: str, url: str, params: dict) -> tuple:
        fam, bi, base = self._current()
        if (family, scope) != (fam["name"], fam["scope"]):
            raise Structural(f"request {family}/{scope} is not the next family in the policy "
                             f"({fam['name']}/{fam['scope']})")
        if url != fam["url"]:
            raise Structural(f"{family}: URL outside the policy (only {fam['url']} is authorized)")
        if {n: v for n, v in params.items() if n != "page_token"} != base:
            raise Structural(f"{family}: base parameters or batch outside the policy")
        if self.n == 0 and "page_token" in params:
            raise Structural(f"{family}: page 0 carries a page_token")
        if self.n > 0 and (not fam["paged"] or params.get("page_token") != self.token):
            raise Structural(f"{family}: page_token is not the preceding page's next_page_token")
        if self.n >= self.policy["max_pages"]:
            raise Structural(f"{family}: more than {self.policy['max_pages']} pages")
        return self.n, fam["page_template"].format(i=bi if bi is not None else 0, n=self.n)

    def record(self, family, scope, n, url, params, retrieved_utc, status, page_relpath, page_sha256) -> None:
        self.provenance.append({"family": family, "scope": scope, "n": n, "url": url, "params": dict(params),
                                "page_token_from": self.last_rel if n > 0 else None, "retrieved_utc": retrieved_utc,
                                "status": status, "page_relpath": page_relpath, "page_sha256": page_sha256})
        self.last_rel = page_relpath

    def page_done(self, data):
        """After the page passed validation: the next page_token of this family/batch, or None (the family/batch
        ends; the next one starts at page 0). A repeated token or a page beyond max_pages is Structural."""
        fam, bi, base = self._current()
        token = data.get("next_page_token") if fam["paged"] and isinstance(data, dict) else None
        if not token:
            self.pos, self.n, self.token, self.seen, self.last_rel = self.pos + 1, 0, None, set(), None
            return None
        if token in self.seen:
            raise Structural(f"{fam['name']}: repeated next_page_token")
        self.seen.add(token)
        self.token, self.n = token, self.n + 1
        if self.n >= self.policy["max_pages"]:
            raise Structural(f"{fam['name']}: more than {self.policy['max_pages']} pages")
        return token

    def finished(self) -> bool:
        return self.pos >= len(self.slots)


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


def _headers(keys):
    return {"APCA-API-KEY-ID": keys[0], "APCA-API-SECRET-KEY": keys[1]}


def _get(client, auth, family, scope, url, params, headers, sw):
    """F4.6: one authorized request (refused BEFORE sending if outside the policy); its raw page is staged and
    recorded in provenance (credential-free: the headers are never recorded)."""
    n, rel = auth.authorize(family, scope, url, params)
    try:
        resp = client.get(url, params=params, headers=headers)
    except Exception as e:                                                # transport failure: no secrets in text
        auth.record(family, scope, n, url, params, c.now_utc().isoformat(), None, None, None)
        raise Structural(f"{rel}: transport error {type(e).__name__}") from None
    retrieved = c.now_utc()                                               # F4.5: the actual observation instant
    auth.record(family, scope, n, url, params, retrieved.isoformat(), resp.status_code, rel,   # T12 fix round 1
                c.sha256_bytes(resp.content))         # (M-1): recorded BEFORE the page write - every request sent
    sw.put(rel, resp.content)                         # is in provenance even if the staging write fails (F4.6)
    if resp.status_code != 200:
        raise Structural(f"{rel}: HTTP {resp.status_code}" + (" (redirect, not followed)"
                                                               if 300 <= resp.status_code < 400 else ""))
    try:
        return json.loads(resp.content), retrieved
    except ValueError:
        raise Structural(f"{rel}: body is not JSON") from None


def _paged(client, auth, family, scope, url, base, headers, sw, validate) -> list:
    """F4.6 pagination: page n+1 adds only the page_token of page n (validated first); the authorizer refuses a
    repeated token and a page beyond max_pages before any further request."""
    pages, token = [], None
    while True:
        data, _ = _get(client, auth, family, scope, url, dict(base, **({"page_token": token} if token else {})),
                       headers, sw)
        if validate:
            validate(data, Path(auth.provenance[-1]["page_relpath"]).stem)
        pages.append(data)
        token = auth.page_done(data)
        if token is None:
            return pages


def _corporate_actions(client, auth, keys, scope, symbols, start, end, sw):
    """F4.9: the CA batches of `symbols` (batch i = symbols[50i : 50i+50]) in ascending batch index, each paged."""
    f = c.fetch()
    batched = []
    for i in range(0, len(symbols), CA_BATCH):
        batch = symbols[i:i + CA_BATCH]
        base = dict(CA_FIXED, symbols=",".join(batch), start=start, end=end)
        for page in _paged(client, auth, CA_FAMILY, scope, CA_URL, base, _headers(keys), sw, f.validate_ca_page):
            batched.append((batch, page))
    return f.classify_ca(batched)


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


def _attempt_files(sw, stage: str) -> tuple:
    """The legacy manifest maps: `files` keyed by basename (every <stage>/*.json except manifest.json), `pages` keyed by
    s1_out-relative path (C-a: the projection of these equals the PREPARED members minus the manifest)."""
    files = {Path(r).name: c.sha256_bytes(b) for r, b in sw.files.items()
             if r.count("/") == 1 and r.startswith(stage + "/") and r != f"{stage}/manifest.json"}
    pages = {r: c.sha256_bytes(b) for r, b in sw.files.items() if r.count("/") >= 2}
    return dict(sorted(files.items())), dict(sorted(pages.items()))


def _provider_abort(auth, e):
    """F4.6 provider anomaly: the staged pages stay, the ABORTED record (written by the stage engine into staging)
    carries the provenance of every request sent; only an S1/E1 Structural's text is recorded (key-free by
    construction), anything else its type name only."""
    structural = isinstance(e, (Structural, c.fetch().Structural))
    raise s1_stage.StageAbort("provider-structural", {
        "outcome": "ABORTED", "error_type": type(e).__name__, "error": str(e) if structural else type(e).__name__,
        "provenance": auth.provenance}) from None            # (no chained foreign text: c9b4322 _abort's rule)


def do_audit(root, ack_id: str, client, keys, *, mailbox=None) -> dict:
    """F9: stage `audit` after the AUDIT-ACK. The INTENT commits the audit request policy (F4.6) with the cutoff = the
    New York date of the INTENT row's `at` (F4.9, C-b; disclosed change from c9b4322's post-reservation clock read).
    Work in staging; Structural/validation failure -> ABORTED staging + INVALID (provider-structural), no retry.
    Kept from c9b4322/Task 12: the ACK must follow the plan it binds and precede planned START (A8.2); the manifest
    binds plan_sha256 and the bundle (A8.1); the calendar is pinned with its source, request parameters and retrieval
    time (A6). The bundle is the gate's (F6.4) and the ACK's field-by-field check (verify_ack)."""
    gv = s1_trial.gate(root, "audit", mailbox=mailbox)                  # A3 F0.6: open trial, state, bundle first
    _require_no_redirects(client)
    out = _out(root)
    c.registration_gate(out, "audit", mailbox=mailbox)                  # fix round 2 (B3.3): re-entry is gated
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    a = s1_trial.verify_ack(gv.trial, gv.rows, "S1-AUDIT-ACK", ack_id,
                            dict(s1_trial.artifact_fields("S1-AUDIT-ACK", out), trial_id=plan.get("trial_id"),
                                 bundle_sha256=c.bundle_sha256()))
    ack = s1_trial.ack_record(a)
    if not c.aware(ack["created_utc"]) > c.aware(plan["created_utc"]):
        raise SystemExit("audit refused: the AUDIT-ACK is not after the plan it binds")
    if c.aware(plan["planned_start"]) <= c.now_utc():
        raise SystemExit("planned START has passed: re-register")

    def work(sw):
        auth = _Authorizer(sw.policy)
        cutoff = sw.policy["cutoff"]
        sw.put_json("audit/attempt.json", {"reserved_utc": c.now_utc().isoformat(), "ack": ack,
                                           "trial_id": sw.trial_id, "intent_at": sw.intent_at})
        try:
            params = {"start": plan["calendar_range"][0], "end": plan["calendar_range"][1], "date_type": "TRADING"}
            cal, retrieved = _get(client, auth, "calendar", "audit", CAL_URL, params, _headers(keys), sw)
            auth.page_done(cal)
            sessions = _validate_calendar(cal, plan, ack)
            page = "audit/pages/calendar.json"
            sw.put_json("audit/calendar_source.json", {"source": CAL_URL, "params": params,       # A6 pin
                                                       "retrieved_utc": retrieved.isoformat(), "page": page,
                                                       "page_sha256": c.sha256_bytes(sw.files[page])})
            actions, problems = _corporate_actions(client, auth, keys, "audit", plan["ca_symbols"],
                                                   plan["ca_range"][0], cutoff, sw)
            if not auth.finished():
                raise Structural("audit: the policy's families were not all requested")
        except OSError:                       # T12 fix round 1 (I-1/I-2): a local I/O fault (a staging write) is not a
            raise                             # provider anomaly - s1_stage.run refuses with no row (transport errors
        except Exception as e:                # are already Structural in _get)  # noqa: BLE001 - recorded type/text
            _provider_abort(auth, e)
        sw.put_json("audit/calendar.json", cal)
        sw.put_json("audit/corporate_actions.json", actions)
        sw.put_json("audit/ca_problems.json", problems)
        files, pages = _attempt_files(sw, "audit")
        sw.put_json("audit/manifest.json", {
            "publication_cutoff": cutoff, "ca_window": [plan["ca_range"][0], cutoff],
            "plan_sha256": c.sha256_file(out / "plan.json"), "bundle_sha256": c.bundle_sha256(),        # A8.1, A3.1
            "outcome": "COMPLETE", "ack": ack, "files": files, "pages": pages,
            "coverage": {"calendar_sessions": len(sessions), "ca_records": len(actions),
                         "ca_problems": len(problems)}, "limits": LIMITS})
        return auth.provenance

    s1_stage.run(gv, "audit", inputs={"plan.json": c.sha256_file(out / "plan.json"), "bundle": c.bundle_sha256()},
                 acks={"S1-AUDIT-ACK": a.sha}, policy_fn=lambda at: audit_policy(plan, _ny_date(at)), work=work,
                 mailbox=mailbox)
    return json.loads((out / "audit" / "manifest.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ final
def _load(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _stop_state(out: Path, now: datetime, mailbox=None) -> tuple:
    """Task 11 (controller-added), I-4: (prereg, stop decision, stop seal path, stop seal) of a trial that has
    STOPPED or TIMED OUT, from the seals (the same stop_decision the score uses). Refuses with no prereg, once
    aborted.json exists (nothing to acquire), on bad seal records, and while RUNNING / NO-VALID-SEAL."""
    if not (out / "prereg.json").exists():
        raise SystemExit("final plan refused: no prereg (the trial never started)")
    if c.load_abort(out) is not None:
        raise SystemExit("final plan refused: the trial is ABORTED-INVALID (nothing to acquire)")
    pr = _load(out / "prereg.json")
    try:                                                   # A3 Task 11 (F1/F2): the journal's TRIAL-STOP + stop.json
        st = s1_seal.current_stop(out, c.aware(pr["start"]), pr["calendar"], now, "final plan",
                                  mailbox=mailbox)         # (never decides a stop: only decide_stop does, F2.2)
    except (ValueError, KeyError, TypeError) as e:
        raise SystemExit(f"final plan refused: bad stop record ({type(e).__name__}: {e})") from None
    if st["status"] not in ("STOPPED", "TIMEOUT"):
        raise SystemExit(f"final plan refused: the trial is {st['status']} (RUNNING = no stop yet)")
    probs = s1_seal.stop_problems(out, c.aware(pr["start"]), pr["calendar"], recheck=False, mailbox=mailbox)
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
    pr, st, stop_p, seal = _stop_state(out, c.now_utc() if now is None else now, mailbox)
    start, stop = c.aware(pr["start"]), c.aware(st["stop_close"])
    try:
        asof = [t for t in seal["trades"] if c.aware(t["ts"]) <= stop]
        cohort = sorted({t["symbol"] for t in s1_seal.cohort(asof, start, stop)})
        carry = sorted(s1_books.held_symbols(s1_seal.split_bridge(asof, start)[0], start))
    except (s1_books.BookError, KeyError, ValueError, TypeError) as e:
        raise SystemExit(f"final plan refused: stop seal ledger unreadable ({type(e).__name__}: {e})") from None
    try:
        trial_id = c.load_json(out / "plan.json").get("trial_id")          # A3 Task 11: final_plan binds the trial
    except (OSError, ValueError, AttributeError):
        trial_id = None
    return {"trial_id": trial_id,
            "stop_close": st["stop_close"], "stop_status": st["status"], "stop_date": _ny_date(stop),
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
    attestation. A3 Task 11: the stage `final_plan` (F1 step 3; F4.8): after stop_attest's CREATED row
    (s1_stage.permitted refuses the INTENT with no row otherwise); the member is the derived record (with trial_id)
    plus the INTENT's intent_at; inputs stop.json, attest_stop.json, prereg.json and plan.json."""
    import s1_stage
    gv = s1_trial.gate(root, "final plan", mailbox=mailbox)             # A3 F0.6: open trial, state, bundle first
    out = _out(root)
    rec = final_plan_record(root, mailbox=mailbox)
    _stop_attestation(out, rec)

    def work(sw):
        sw.put_json("final_plan.json", dict(rec, intent_at=sw.intent_at))
        return []
    s1_stage.run(gv, "final_plan", inputs={n: c.sha256_file(out / n) for n in ("stop.json", "attest_stop.json",
                                                                              "prereg.json", "plan.json")},
                 acks={}, work=work, mailbox=mailbox)
    return out / "final_plan.json"


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


def final_policy(fplan: dict, prereg: dict, cutoff: str) -> dict:
    """F4.6/F4.9: the final acquisition's policy - raw/SIP daily bars (one paged family), then corporate actions for
    the window scope and the full-history scope (each per 50-symbol batch); every CA end = the INTENT's cutoff."""
    start_day = _ny_date(c.aware(prereg["start"]))
    bars_start = _ny_instant(start_day, "00:00")
    bars_end = _ny_instant((date.fromisoformat(fplan["stop_date"]) + timedelta(days=1)).isoformat(),
                           "00:00") - timedelta(microseconds=1)

    def ca(scope, syms, start, template):
        batches = [list(syms[i:i + CA_BATCH]) for i in range(0, len(syms), CA_BATCH)]
        return {"name": CA_FAMILY, "url": CA_URL, "scope": scope, "batches": batches,
                "base_params": [dict(CA_FIXED, symbols=",".join(b), start=start, end=cutoff) for b in batches],
                "paged": True, "page_template": template}
    return {"redirects": False, "max_pages": MAX_PAGES, "cutoff": cutoff, "families": [
        {"name": "bars", "url": BARS_URL, "scope": "final", "batches": None,
         "base_params": {"symbols": ",".join(fplan["bar_symbols"]), "timeframe": "1Day", "start": _utc_z(bars_start),
                         "end": _utc_z(bars_end, micro=True), "adjustment": "raw", "feed": "sip", "limit": 10000},
         "paged": True, "page_template": "final/pages/bars_page{n:03d}.json"},
        ca("window", fplan["ca_symbols_window"], start_day, "final/pages/ca_{i:03d}_page{n:03d}.json"),
        ca("full_history", fplan["ca_symbols_full_history"], fplan["full_history_start"],
           "final/pages_full/ca_{i:03d}_page{n:03d}.json")]}


def do_final(root, ack_id: str, client, keys, *, mailbox=None) -> dict:
    """F1 graph step 5: the stage `final` under the exact ACQUIRE-ACK (F4.6/F4.9 final rows). Before the INTENT it
    re-derives the final plan from the stop seal (Task 11, I-4) and requires the stored plan to equal it (less the
    stage's intent_at), the stop attestation to bind that stop, the ACK to be strictly after the stop attestation and
    no earlier than the acquisition lag (OQ-22: both the ACK's created and the execution time satisfy the lag, F1 step
    4). The INTENT commits the final request policy (final_policy) with the cutoff = the New York date of the INTENT
    row's `at` (F4.9, C-b). Work in staging; a provider anomaly -> ABORTED staging + INVALID (provider-structural), no
    retry (F4.6). Every member is committed at PREPARED and published by the stage engine (C-a)."""
    gv = s1_trial.gate(root, "final acquisition", mailbox=mailbox)      # A3 F0.6: open trial, state, bundle first
    _require_no_redirects(client)
    out = _out(root)
    g.verified_registration(out, "final acquisition", mailbox)        # Task 12: A3.2 bundle first, then A8.2
    fp, prp = out / "final_plan.json", out / "prereg.json"
    if not fp.is_file():                                   # A3 Task 11 (F1 graph 3 -> 5; row 56): a refusal, not
        raise SystemExit("final refused: no final plan (final_plan comes first, F1)")   # a FileNotFoundError
    plan = json.loads(fp.read_text(encoding="utf-8"))
    a = s1_trial.verify_ack(gv.trial, gv.rows, "S1-ACQUIRE-ACK", ack_id,      # A3: field by field (F6.1, F6.5, F7.1)
                            dict(s1_trial.artifact_fields("S1-ACQUIRE-ACK", out), trial_id=gv.trial.trial_id,
                                 bundle_sha256=c.bundle_sha256()))
    ack = s1_trial.ack_record(a)
    rec = final_plan_record(root, mailbox=mailbox)
    if {k_: v for k_, v in plan.items() if k_ != "intent_at"} != rec:     # A3 Task 11: the stage adds intent_at
        raise SystemExit("final refused: final_plan.json is not the plan derived from the stop seal")
    att = _stop_attestation(out, rec)
    if c.aware(ack["created_utc"]) <= c.aware(att["recorded_utc"]):
        raise SystemExit("final refused: the ACQUIRE-ACK is not strictly after the stop attestation")
    pr = json.loads(prp.read_text(encoding="utf-8"))
    earliest = _earliest_acquire(pr["calendar"], plan["stop_date"])
    if c.aware(ack["created_utc"]) < earliest:                                                  # OQ-22
        raise SystemExit("final refused: the ACQUIRE-ACK precedes the acquisition lag (F1 step 4)")
    if c.now_utc() < earliest:
        raise SystemExit(f"acquisition lag not met: not before {earliest.isoformat()}")
    start_day = _ny_date(c.aware(pr["start"]))
    sessions = [x["date"] for x in pr["calendar"] if start_day <= x["date"] <= plan["stop_date"]]

    def work(sw):
        auth, cutoff = _Authorizer(sw.policy), sw.policy["cutoff"]
        sw.put_json("final/attempt.json", {"reserved_utc": c.now_utc().isoformat(), "ack": ack,
                                           "trial_id": sw.trial_id, "intent_at": sw.intent_at})
        try:
            bar_pages = _paged(client, auth, "bars", "final", BARS_URL, sw.policy["families"][0]["base_params"],
                               _headers(keys), sw, _validate_bars_page)
            ca_win, p1 = _corporate_actions(client, auth, keys, "window", plan["ca_symbols_window"], start_day,
                                            cutoff, sw)
            ca_full, p2 = _corporate_actions(client, auth, keys, "full_history", plan["ca_symbols_full_history"],
                                             plan["full_history_start"], cutoff, sw)
            if not auth.finished():
                raise Structural("final: the policy's families were not all requested")
        except OSError:                       # T12 fix round 1 (I-1/I-2): a local I/O fault (a staging write) is not a
            raise                             # provider anomaly - s1_stage.run refuses with no row (transport errors
        except Exception as e:                # are already Structural in _get)  # noqa: BLE001 - recorded type/text
            _provider_abort(auth, e)
        bars, bar_problems = _parse_bars(plan["bar_symbols"], bar_pages, sessions)
        actions, conflicts = reconcile_actions(ca_win, ca_full)          # Task 12 (A7.2): one global set
        for name, obj in (("bars.json", bars), ("bar_problems.json", bar_problems),
                          ("corporate_actions.json", actions), ("ca_problems.json", p1 + p2 + conflicts)):
            sw.put_json(f"final/{name}", obj)
        files, pages = _attempt_files(sw, "final")
        per_symbol = {s: {"present": len(bars[s]), "missing": len(sessions) - len(bars[s])} for s in bars}
        bars_params = sw.policy["families"][0]["base_params"]
        sw.put_json("final/manifest.json", {
            "publication_cutoff": cutoff, "prereg_sha256": c.sha256_file(prp),
            "earliest_acquire_utc": earliest.isoformat(), "final_plan_sha256": c.sha256_file(fp),
            "attest_stop_sha256": c.sha256_file(out / "attest_stop.json"),
            "bundle_sha256": c.bundle_sha256(),                                                  # Task 12 (A3.4)
            "stop_sha256": c.sha256_file(out / "stop.json"),                                     # Task 12 (A2.1)
            "bars_window": [bars_params["start"], bars_params["end"]],
            "outcome": "COMPLETE", "ack": ack, "files": files, "pages": pages,
            "coverage": {"bars": per_symbol, "bar_problems": len(bar_problems), "ca_records": len(actions),
                         "ca_problems": len(p1) + len(p2) + len(conflicts), "ca_conflicts": len(conflicts)},
            "limits": LIMITS})
        return auth.provenance

    s1_stage.run(gv, "final", inputs={"final_plan.json": c.sha256_file(fp), "prereg.json": c.sha256_file(prp),
                                      "attest_stop.json": c.sha256_file(out / "attest_stop.json")},
                 acks={"S1-ACQUIRE-ACK": a.sha}, policy_fn=lambda at: final_policy(plan, pr, _ny_date(at)),
                 work=work, mailbox=mailbox)
    return json.loads((out / "final" / "manifest.json").read_text(encoding="utf-8"))
