import json
import sqlite3
import sys
from pathlib import Path

import pytest

# Project root (for s1_common, e1_* modules) and this directory (so test modules can
# `from test_s1_books import tr` and `from conftest import ...`). Inserted at the front.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE))

SCHEMA = [
    """CREATE TABLE agents (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, strategy TEXT,
       created_at TEXT NOT NULL)""",
    """CREATE TABLE portfolios (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id INTEGER NOT NULL, symbol TEXT NOT NULL,
       shares REAL NOT NULL DEFAULT 0, avg_cost REAL NOT NULL DEFAULT 0, current_value REAL NOT NULL DEFAULT 0,
       unrealized_pnl REAL NOT NULL DEFAULT 0, UNIQUE(agent_id, symbol))""",
    """CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id INTEGER NOT NULL, symbol TEXT NOT NULL,
       action TEXT NOT NULL, shares REAL NOT NULL, price REAL NOT NULL, timestamp TEXT NOT NULL, reasoning TEXT,
       pnl REAL DEFAULT 0)""",
]


class Ledger:
    def __init__(self, path: Path):
        self.path = path
        con = sqlite3.connect(path)
        con.execute("PRAGMA journal_mode=WAL")
        for s in SCHEMA:
            con.execute(s)
        con.execute("INSERT INTO agents (name, strategy, created_at) VALUES ('XGBReasoningAgent','x','t')")
        self.agent_id = con.execute("INSERT INTO agents (name, strategy, created_at) VALUES "
                                    "('MeanReversionAgent','mr','t')").lastrowid
        con.commit()
        con.close()

    def _x(self, sql, args):
        con = sqlite3.connect(self.path)
        cur = con.execute(sql, args)
        con.commit()
        con.close()
        return cur.lastrowid

    def trade(self, symbol, action, shares, price, ts, reasoning="r", agent_id=None):
        return self._x("INSERT INTO trades (agent_id, symbol, action, shares, price, timestamp, reasoning, pnl) "
                       "VALUES (?,?,?,?,?,?,?,0)", (agent_id or self.agent_id, symbol, action, shares, price, ts,
                                                    reasoning))

    def set_portfolio(self, symbol, shares):
        self._x("INSERT INTO portfolios (agent_id, symbol, shares) VALUES (?,?,?) "
                "ON CONFLICT(agent_id, symbol) DO UPDATE SET shares=excluded.shares", (self.agent_id, symbol, shares))

    def drop_portfolio(self, symbol):
        self._x("DELETE FROM portfolios WHERE agent_id=? AND symbol=?", (self.agent_id, symbol))


@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path / "trading.db")


@pytest.fixture(autouse=True)
def s1_tmp_mailbox(tmp_path):
    """Task 11 (controller-added), I-5: product code reads ACKs from s1_common.MAILBOX (the coordination mailbox).
    Every test gets it redirected to <tmp_path>/mailbox.sqlite3 (where s1_mailbox writes for root = tmp_path), so
    no test can open the real one. Set and restored by hand (not via `monkeypatch`), so a test's
    monkeypatch.undo() never re-exposes the real path."""
    import s1_common
    had, old = hasattr(s1_common, "MAILBOX"), getattr(s1_common, "MAILBOX", None)
    s1_common.MAILBOX = tmp_path / "mailbox.sqlite3"
    yield s1_common.MAILBOX
    if had:
        s1_common.MAILBOX = old
    else:
        del s1_common.MAILBOX


@pytest.fixture(autouse=True)
def s1_tmp_hmac_key(tmp_path):
    """Task 12 (A1): the receipt's HMAC key file is redirected to <tmp_path>/s1_receipt_hmac.key for every test, so no
    test can create or read the real key (C:/Users/gl450/.coordination/trading_app/s1_receipt_hmac.key). Set and
    restored by hand, like the mailbox redirect."""
    import s1_receipt
    had, old = hasattr(s1_receipt, "HMAC_KEY"), getattr(s1_receipt, "HMAC_KEY", None)
    s1_receipt.HMAC_KEY = tmp_path / "s1_receipt_hmac.key"
    yield s1_receipt.HMAC_KEY
    if had:
        s1_receipt.HMAC_KEY = old
    else:
        del s1_receipt.HMAC_KEY


# ---------------------------------------------------------------- Task 7: synthetic s1_out/ lifecycle (test-only)
# Task 12 (A1) interface: a receipt is {"fingerprint": compared, "provenance": recorded only}.
S1_RECEIPT = {"fingerprint": {"closure": {"agents/mean_reversion_agent.py": "1"}, "resources": {}, "config": {},
                              "runtime": {}},
              "provenance": {"head": "h", "dirty": []}}


def s1_receipt_with(receipt, *, head=None, files=None):
    """Task 12 (A1) test helper: a copy of `receipt` with the PROVENANCE head changed (`head`, not compared) and/or
    the fingerprint closure changed (`files`, compared)."""
    out = json.loads(json.dumps(receipt))
    if head is not None:
        out["provenance"]["head"] = head
    if files is not None:
        out["fingerprint"]["closure"] = files
    return out


class _Clock:
    """Pin s1_common.now_utc to one instant for the duration of a block (restores the previous function)."""

    def __init__(self, t):
        self.t = t

    def __enter__(self):
        import s1_common
        self._old = s1_common.now_utc
        s1_common.now_utc = lambda: self.t

    def __exit__(self, *exc):
        import s1_common
        s1_common.now_utc = self._old


def _weekdays(first, last):
    from datetime import date, timedelta
    d, out = date.fromisoformat(first), []
    while d <= date.fromisoformat(last):
        if d.weekday() < 5:
            out.append({"date": d.isoformat(), "open": "09:30", "close": "16:00"})
        d += timedelta(days=1)
    return out


def s1_mailbox(root, mid, body, created):
    con = sqlite3.connect(Path(root) / "mailbox.sqlite3")
    con.execute("CREATE TABLE IF NOT EXISTS messages (id TEXT, sender TEXT, recipient TEXT, request_key TEXT, "
                "body TEXT, created REAL, acknowledged REAL)")
    con.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,NULL)",
                (mid, "codex", "claude", "experiments-prereg", body, created.timestamp()))
    con.commit()
    con.close()


def s1_bar(d, o=100, h=101, l=99, c=100):
    return {"date": d, "o": o, "h": h, "l": l, "c": c}


def _dump(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, sort_keys=True), encoding="utf-8")


def _write_seal(out: Path, day: str, close_dt, trades, receipt, *, start=None, opening_close=None):
    """A seal exactly as s1_checkpoint writes it, plus its preserved capture projection. Task 8b (controller-added):
    a post-START seal (`start` given, close >= start) carries the bridge record s1_seal.bridge_record. Task 12
    interface: the capture records its measured start/end (A5), the seal the registered bundle (A3) and the receipt
    FINGERPRINT hash (A1)."""
    from datetime import timedelta
    import s1_common as c
    import s1_seal as z
    proj = {"agent_id": 2, "trades": trades, "portfolios": {}, "schema": {}}
    sch = close_dt + timedelta(minutes=45)
    cap_dir = out / "captures" / day / sch.strftime("%Y%m%dT%H%M%SZ")
    cap_dir.mkdir(parents=True)
    blob = c.canonical(proj)
    (cap_dir / "projection.json").write_bytes(blob)
    t = (sch + timedelta(seconds=30)).isoformat()
    cap = {"scheduled": sch.isoformat(), "actual": t, "capture_start": t, "capture_end": t, "ok": True,
           "consistent": True, "projection_sha256": c.sha256_bytes(blob), "dir": str(cap_dir)}
    seal = {"close": close_dt.isoformat(), "fence": z.fence(proj),
            "max_id": max((t["id"] for t in trades), default=0), "trades": trades, "capture": cap,
            "restart_record": {"starts": [], "size": 0, "sha256": None, "prefix_sha256": None},
            "process": json.loads(json.dumps(S1_PROCESS)),
            "process_binding": {"status": "MATCH", "binding": dict(S1_BINDING)},     # fix round 2 (B2)
            "receipt_sha256": c.receipt_sha256(receipt), "receipt_match": True,
            "receipt_provenance": receipt.get("provenance"),
            "bundle_sha256": c.bundle_sha256()}                             # Task 12 (A3): as the checkpoint
    if start is not None and close_dt >= start:
        seal["bridge"] = z.bridge_record(trades, start, opening_close)
    (out / "seals").mkdir(parents=True, exist_ok=True)
    (out / "seals" / f"{day}.json").write_text(json.dumps(seal), encoding="utf-8")


def _dl_day(dl):
    """The calendar day of a deadline (an aware instant since Task 12 A5.1; a date before)."""
    return dl.astimezone(__import__("s1_common").NY).date() if hasattr(dl, "astimezone") else dl


def _dl_ok(z, d, cal, dl):
    """Calendar row `d` is <= the deadline: by close INSTANT (Task 12 A5.1), or by date for a date deadline."""
    return z.close_of(d["date"], cal) <= dl if hasattr(dl, "astimezone") else d["date"] <= dl.isoformat()


def _default_lots():
    return [{"symbol": f"S{i % 5}", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (1, 80.0)} for i in range(100)]


# Task 12 fix round 2 (Addendum 2 B2): the observation carries the sanitized launcher binding (the opening's is the
# registered reference); an explicit gap is {"binding": {"unavailable": reason}}.
S1_CMDLINE = '"C:/app/runtime/python/python.exe" main.py --port 8000'
S1_BINDING = {"exe": "C:/app/runtime/python/python.exe", "cmdline": S1_CMDLINE,
              "cmdline_sha256": __import__("hashlib").sha256(S1_CMDLINE.encode("utf-8")).hexdigest()}
S1_PROCESS = {"pid": 1, "process_start": "2026-10-01T09:00:00", "binding": dict(S1_BINDING)}


def s1_plan_audit(root, planned_start, *, carry_in_syms=(), first_day=None, audit_actions=(), audit_problems=(),
                  calendar=None, ack_id="audit-ack", opening_close=None):
    """Task 7b (controller-added) helper, extracted from s1_state: the plan (s1_collect.write_plan, under a fixed
    clock 14 days before START) and a COMPLETE audit attempt (calendar + corporate actions, manifest hashes).
    Returns (start, raw calendar, opening close date, plan creation instant).
    Task 12 interface (A3/A6/A8): an S1-AUDIT-ACK message `ack_id` (12 h after the plan, before the audit
    reservation) carrying the real audit token; the manifest records that ACK, plan_sha256 and bundle_sha256; the
    calendar is pinned with its raw page (hashed under `pages`) and calendar_source.json (source, params, retrieval
    time). `calendar` overrides the synthetic weekday calendar; `opening_close` the plan's opening close (to test a
    wrong one: since A8.1 a plan edited after its audit is refused for that reason first)."""
    from datetime import timedelta
    import s1_collect as k
    import s1_common as c
    import s1_seal as z

    out = Path(root) / "s1_out"
    start = c.aware(planned_start)
    start_day = start.astimezone(c.NY).date().isoformat()
    dl = z.deadline(start)
    raw_cal = (list(calendar) if calendar is not None else
               _weekdays((start - timedelta(days=40)).date().isoformat(),
                         (_dl_day(dl) + timedelta(days=40)).isoformat()))
    opening_close = opening_close or max(d["date"] for d in raw_cal if d["date"] < start_day)
    created = start - timedelta(days=14)
    with _Clock(created):
        k.write_plan(root, start, opening_close, sorted(set(carry_in_syms)), first_day or start_day)
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    ack_t = created + timedelta(hours=12)
    s1_mailbox(root, ack_id, c.audit_token(out), ack_t)
    ack = {"ack_id": ack_id, "created_utc": ack_t.isoformat()}
    audit = out / "audit"
    reserved = created + timedelta(days=1)
    _dump(audit / "attempt.json", {"reserved_utc": reserved.isoformat(), "ack": ack})
    page = audit / "pages" / "calendar.json"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_bytes(json.dumps(raw_cal).encode("utf-8"))
    _dump(audit / "calendar.json", raw_cal)
    _dump(audit / "calendar_source.json", {
        "source": k.CAL_URL, "params": {"start": plan["calendar_range"][0], "end": plan["calendar_range"][1],
                                        "date_type": "TRADING"},
        "retrieved_utc": (reserved + timedelta(minutes=1)).isoformat(), "page": "audit/pages/calendar.json",
        "page_sha256": c.sha256_file(page)})
    _dump(audit / "corporate_actions.json", list(audit_actions))
    _dump(audit / "ca_problems.json", list(audit_problems))
    _dump(audit / "manifest.json", {"outcome": "COMPLETE", "ack": ack, "pages": {"audit/pages/calendar.json":
                                                                                  c.sha256_file(page)},
                                    "coverage": {}, "plan_sha256": c.sha256_file(out / "plan.json"),
                                    "bundle_sha256": c.bundle_sha256(),
                                    "files": {n: c.sha256_file(audit / n) for n in
                                              ("attempt.json", "calendar.json", "calendar_source.json",
                                               "corporate_actions.json", "ca_problems.json")}})
    return start, raw_cal, opening_close, created


def s1_sync_portfolio(ledger, trades):
    """Task 7b (controller-added) helper: make the synthetic portfolios table equal the operational replay of
    `trades` (so a capture of the synthetic ledger is consistent)."""
    import s1_books as b
    qty = b.operational_replay(trades)["qty"]
    for sym in sorted({t["symbol"] for t in trades}):
        if sym in qty:
            ledger.set_portfolio(sym, qty[sym])
        else:
            ledger.drop_portfolio(sym)


def s1_opening_checkpoint(root, ledger, opening_close, cal, receipt, *, minutes=45):
    """Task 7b (controller-added) helper: run the REAL opening checkpoint for the slot opening close + `minutes`,
    30 s after the slot, on a fixed clock."""
    from datetime import timedelta
    import s1_checkpoint as ck
    import s1_seal as z
    sch = z.close_of(opening_close, cal) + timedelta(minutes=minutes)
    act = sch + timedelta(seconds=30)
    with _Clock(act):
        return ck.run_opening_checkpoint(root, ledger.path, sch, lambda: receipt, lambda: dict(S1_PROCESS),
                                         Path(root) / "crash.log", now=lambda: act)


def s1_state(root, planned_start, score_ready=False, *, carry_in=(("CI", 10, 50.0, "2026-10-01T15:00:00+00:00"),),
             bridge=(), audit_actions=(), audit_problems=(), lots=None, bar_fn=None, final_actions=(),
             final_problems=(), bar_problems=(), seal_days=None, stop_attest=True, receipt=None,
             final_snapshot=True, final=True):
    """Build a synthetic s1_out/ under `root` through the REAL product gates (Task 7 test helper, not product code).

    Always: plan (s1_collect.write_plan), a COMPLETE audit attempt (calendar + corporate actions, manifest hashes),
    the opening seal (carry-in rows; bridge rows are stored after it), the START attestation (s1_run.attest_start)
    and a RUN-ACK mailbox message "run-ack" (a test may call do_prereg itself).
    With score_ready: prereg (s1_run.do_prereg), cohort rows (`lots`: symbol, qty, px, buy_day, sell=(day, px)|None,
    day = index of the post-START session), seals for `seal_days` (default: every session through the last trade),
    the stop attestation (if `stop_attest` and a stop exists), the final plan + a COMPLETE final attempt (bars from
    `bar_fn(symbol, date)`, None = missing) when a stop exists, the acquisition-time final snapshot (if
    `final_snapshot`) and a SCORE-ACK message "score-ack". Task 12: `final=False` stops after the stop attestation
    (no final plan, final attempt, snapshot or SCORE-ACK), for tests that run the real final acquisition.
    carry_in: (symbol, qty, px, ts) BUYs before the opening close; bridge: (symbol, action, qty, px, ts) rows after
    the opening seal and before START. Returns start, calendar, sessions, rows, stop, the synthetic `ledger` and
    `now` (after everything).
    Task 7b (controller-added): the rows live in a synthetic SQLite ledger (root/s1_ledger.sqlite3, inserted in
    stored-time order so ids increase with time); the opening seal is produced by
    s1_checkpoint.run_opening_checkpoint (no hand-written opening seal) and the final snapshot by
    s1_checkpoint.run_final_snapshot. Post-START seals are still written in the checkpoint's seal format."""
    from datetime import timedelta
    import s1_checkpoint as ck
    import s1_collect as k
    import s1_common as c
    import s1_run as r
    import s1_seal as z

    receipt = S1_RECEIPT if receipt is None else receipt
    root = Path(root)
    out = root / "s1_out"
    start = c.aware(planned_start)
    start_day = start.astimezone(c.NY).date().isoformat()
    dl = z.deadline(start)
    first_day = min((c.aware(x[3]).astimezone(c.NY).date().isoformat() for x in carry_in), default=start_day)
    start, raw_cal, opening_close, created = s1_plan_audit(
        root, planned_start, carry_in_syms=[x[0] for x in carry_in], first_day=first_day,
        audit_actions=audit_actions, audit_problems=audit_problems)
    cal = [dict(d) for d in raw_cal]
    sessions = [d["date"] for d in cal if d["date"] >= start_day]

    # all rows in stored-time order; ids increase with time (as the app's autoincrement gives them)
    lots = (_default_lots() if lots is None else lots) if score_ready else []
    pending = [(ts, sym, "BUY", q, px) for sym, q, px, ts in carry_in]
    pending += [(ts, sym, act, q, px) for sym, act, q, px, ts in bridge]
    for L in lots:
        pending.append((f"{sessions[L['buy_day']]}T15:00:00+00:00", L["symbol"], "BUY", L["qty"], L["px"]))
        if L.get("sell"):
            pending.append((f"{sessions[L['sell'][0]]}T18:00:00+00:00", L["symbol"], "SELL", L["qty"],
                            L["sell"][1]))
    pending.sort(key=lambda p: c.aware(p[0]))
    reason_sha = c.sha256_bytes(b"r")                                  # Ledger.trade's default reasoning
    rows = [{"id": i, "symbol": sym, "action": act, "shares": float(q), "price": float(px), "timestamp": ts,
             "ts": c.aware(ts).isoformat(), "reasoning_sha256": reason_sha}
            for i, (ts, sym, act, q, px) in enumerate(pending, start=1)]
    held_syms = sorted({x[0] for x in carry_in} | {x[0] for x in bridge})

    ledger = Ledger(root / "s1_ledger.sqlite3")
    stored = []

    def store_until(limit):
        for t in rows[len(stored):]:
            if limit is not None and c.aware(t["ts"]) > limit:
                break
            assert ledger.trade(t["symbol"], t["action"], t["shares"], t["price"], t["timestamp"]) == t["id"]
            stored.append(t)
        s1_sync_portfolio(ledger, stored)

    oc = z.close_of(opening_close, cal)
    store_until(oc + timedelta(minutes=45))
    rep = s1_opening_checkpoint(root, ledger, opening_close, cal, receipt)
    assert rep["seal"]["written"], rep
    store_until(None)                                                  # bridge + cohort rows, stored after it
    # Task 12 (A8 causal order): the START attestation follows the opening seal, the RUN-ACK the attestation and
    # prereg the RUN-ACK (unchanged instants for a Monday START; later ones when the opening close is the eve)
    attest_t = max(start - timedelta(days=2), oc + timedelta(hours=2))
    ack_t = max(start - timedelta(days=1, hours=1), oc + timedelta(hours=3))
    prereg_t = max(start - timedelta(days=1), oc + timedelta(hours=4))
    with _Clock(attest_t):
        r.attest_start(root, r.START_STATEMENT, receipt)
    s1_mailbox(root, "run-ack", r.run_token(root), ack_t)
    info = {"start": start, "calendar": cal, "sessions": sessions, "rows": rows, "stop": None, "ledger": ledger,
            "now": start - timedelta(hours=12), "prereg_at": prereg_t}     # Task 12: a causal prereg instant
    if not score_ready:
        return info

    with _Clock(prereg_t):
        r.do_prereg(root, "run-ack", receipt)
    if seal_days is None:
        used = [L["buy_day"] for L in lots] + [L["sell"][0] for L in lots if L.get("sell")]
        seal_days = range(0, max(used, default=-1) + 1)
    last_close = start
    for i in seal_days:
        cl = z.close_of(sessions[i], cal)
        _write_seal(out, sessions[i], cl, [t for t in rows if c.aware(t["ts"]) <= cl + timedelta(minutes=45)],
                    receipt, start=start, opening_close=oc)
        last_close = max(last_close, cl)
    seals = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((out / "seals").glob("*.json"))]
    t = last_close + timedelta(days=1)
    stop = z.stop_decision(seals, start, cal, today=t)
    if stop["status"] != "STOPPED":                      # let the timeout window close
        last_eligible = [d for d in cal if z.open_instant(d) >= start and _dl_ok(z, d, cal, dl)][-1]
        t = z.window_end(last_eligible, cal) + timedelta(days=1)
        stop = z.stop_decision(seals, start, cal, today=t)
    info["stop"] = stop
    if stop_attest and stop["status"] in ("STOPPED", "TIMEOUT"):
        with _Clock(t):
            r.attest_stop(root, r.STOP_STATEMENT)
    info["stop_attested_at"] = t
    if not final:
        return info
    if stop["status"] in ("STOPPED", "TIMEOUT"):
        stop_day = c.aware(stop["stop_close"]).astimezone(c.NY).date().isoformat()
        cohort_syms = sorted({L["symbol"] for L in lots})
        with _Clock(t + timedelta(hours=1)):         # Task 11 (I-4): derived from the stop seal, after attest_stop
            if stop_attest:
                k.write_final_plan(root)
            else:                                     # (test-only: an unattested acquisition, for the score's paths)
                k._write_once(out / "final_plan.json", k.final_plan_record(root))
        fin = out / "final"
        bar_fn = bar_fn or (lambda sym, d: s1_bar(d))
        win = [d for d in sessions if d <= stop_day]
        bars = {}
        for s in sorted(set(cohort_syms) | set(held_syms)):
            bars[s] = {}
            for d in win:
                b_ = bar_fn(s, d)
                if b_ is not None:
                    bars[s][d] = b_
        _dump(fin / "attempt.json", {"reserved_utc": (t + timedelta(days=2)).isoformat(), "ack": {}})
        _dump(fin / "bars.json", bars)
        _dump(fin / "bar_problems.json", list(bar_problems))
        _dump(fin / "corporate_actions.json", list(final_actions))
        _dump(fin / "ca_problems.json", list(final_problems))
        _dump(fin / "manifest.json", {"outcome": "COMPLETE", "ack": {}, "pages": {}, "coverage": {},
                                      "bundle_sha256": c.bundle_sha256(),                     # Task 12 (A3)
                                      "stop_sha256": c.sha_or_absent(out / "stop.json"),      # Task 12 (A2)
                                      "prereg_sha256": c.sha256_file(out / "prereg.json"),
                                      "final_plan_sha256": c.sha256_file(out / "final_plan.json"),   # Task 11
                                      "attest_stop_sha256": (c.sha256_file(out / "attest_stop.json")
                                                             if (out / "attest_stop.json").exists() else "absent"),
                                      "files": {n: c.sha256_file(fin / n) for n in
                                                ("attempt.json", "bars.json", "bar_problems.json",
                                                 "corporate_actions.json", "ca_problems.json")}})
    info["snapshot_at"] = t + timedelta(days=2, minutes=5)          # the acquisition-time snapshot (§6)
    if final_snapshot:
        with _Clock(info["snapshot_at"]):
            ck.run_final_snapshot(root, ledger.path, now=lambda: info["snapshot_at"])
    s1_mailbox(root, "score-ack", r.score_token(root), t + timedelta(days=3))
    info["now"] = t + timedelta(days=4)
    return info


def s1_unattest(root, *, books=True):
    """Fix round 2 (Addendum 2 B3) test helper: the state BEFORE the START attestation, for tests that used to delete
    attest_start.json to re-attest: the attestation (and, with `books`, the opening books it wrote) AND its registry
    record are removed - exactly the files the attestation stage creates (deleting only the attestation now is the
    persistent "registration artifact" abort, B3.3).
    Fix round 3 (C-2): the attestation stage is now witnessed redundantly, so the pre-attestation state also lacks
    the attestation's second registration record (witnesses/attest_start.json) and the RUN-ACK message "run-ack"
    (a RUN-ACK binds an attestation: it cannot exist before one)."""
    out = Path(root) / "s1_out"
    for rel in ["attest_start.json", "registry/attest_start.json", "witnesses/attest_start.json"] + (
            ["opening_books.json"] if books else []):
        (out / rel).unlink()
    con = sqlite3.connect(Path(root) / "mailbox.sqlite3")
    con.execute("DELETE FROM messages WHERE id=?", ("run-ack",))
    con.commit()
    con.close()


def s1_register(root, planned_start, *, calendar=None, receipt=None, carry_in_syms=(), first_day=None,
                ledger=None):
    """Task 12 (A8) test helper: a GENUINE registration through the real gates, for tests that used to hand-write
    prereg.json (a hand-made prereg now refuses with zero live callbacks): plan + AUDIT-ACK'd audit
    (s1_plan_audit), the real opening checkpoint on an empty opening ledger (root/opening_ledger.sqlite3), the START
    attestation 2 h after the opening seal, a RUN-ACK message "run-ack" 1 h later and do_prereg 1 h after that (all
    before planned START). `ledger`: capture this ledger at the opening instead (its rows stored by then are the
    opening seal's). Returns {start, calendar, opening_close, prereg}."""
    from datetime import timedelta
    import s1_run as r
    import s1_seal as z
    receipt = S1_RECEIPT if receipt is None else receipt
    root = Path(root)
    start, raw_cal, opening_close, _ = s1_plan_audit(root, planned_start, calendar=calendar,
                                                     carry_in_syms=carry_in_syms, first_day=first_day)
    lg = ledger if ledger is not None else Ledger(root / "opening_ledger.sqlite3")   # caller keeps it consistent
    rep = s1_opening_checkpoint(root, lg, opening_close, raw_cal, receipt)
    assert rep["seal"]["written"], rep
    oc = z.close_of(opening_close, raw_cal)
    with _Clock(oc + timedelta(hours=2)):
        r.attest_start(root, r.START_STATEMENT, receipt)
    s1_mailbox(root, "run-ack", r.run_token(root), oc + timedelta(hours=3))
    with _Clock(oc + timedelta(hours=4)):
        pr = r.do_prereg(root, "run-ack", receipt)
    assert oc + timedelta(hours=4) < start
    return {"start": start, "calendar": raw_cal, "opening_close": opening_close, "prereg": pr}
