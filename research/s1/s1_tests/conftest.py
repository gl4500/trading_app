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


# ---------------------------------------------------------------- Task 7: synthetic s1_out/ lifecycle (test-only)
S1_RECEIPT = {"head": "h", "dirty": [], "files": {"agents/mean_reversion_agent.py": "1"}, "config": {},
              "versions": {}}


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
    a post-START seal (`start` given, close >= start) carries the bridge record s1_seal.bridge_record."""
    from datetime import timedelta
    import s1_common as c
    import s1_seal as z
    proj = {"agent_id": 2, "trades": trades, "portfolios": {}, "schema": {}}
    sch = close_dt + timedelta(minutes=45)
    cap_dir = out / "captures" / day / sch.strftime("%Y%m%dT%H%M%SZ")
    cap_dir.mkdir(parents=True)
    blob = c.canonical(proj)
    (cap_dir / "projection.json").write_bytes(blob)
    cap = {"scheduled": sch.isoformat(), "actual": (sch + timedelta(seconds=30)).isoformat(), "ok": True,
           "consistent": True, "projection_sha256": c.sha256_bytes(blob), "dir": str(cap_dir)}
    seal = {"close": close_dt.isoformat(), "fence": z.fence(proj),
            "max_id": max((t["id"] for t in trades), default=0), "trades": trades, "capture": cap,
            "restart_record": {"starts": [], "size": 0, "sha256": None, "prefix_sha256": None},
            "process": {"pid": 1, "process_start": "2026-10-01T09:00:00"},
            "receipt_sha256": c.sha256_bytes(c.canonical(receipt)), "receipt_match": True}
    if start is not None and close_dt >= start:
        seal["bridge"] = z.bridge_record(trades, start, opening_close)
    (out / "seals").mkdir(parents=True, exist_ok=True)
    (out / "seals" / f"{day}.json").write_text(json.dumps(seal), encoding="utf-8")


def _default_lots():
    return [{"symbol": f"S{i % 5}", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (1, 80.0)} for i in range(100)]


S1_PROCESS = {"pid": 1, "process_start": "2026-10-01T09:00:00"}


def s1_plan_audit(root, planned_start, *, carry_in_syms=(), first_day=None, audit_actions=(), audit_problems=()):
    """Task 7b (controller-added) helper, extracted from s1_state: the plan (s1_collect.write_plan, under a fixed
    clock 14 days before START) and a COMPLETE audit attempt (calendar + corporate actions, manifest hashes).
    Returns (start, raw calendar, opening close date, plan creation instant)."""
    from datetime import timedelta
    import s1_collect as k
    import s1_common as c
    import s1_seal as z

    out = Path(root) / "s1_out"
    start = c.aware(planned_start)
    start_day = start.astimezone(c.NY).date().isoformat()
    dl = z.deadline(start)
    raw_cal = _weekdays((start - timedelta(days=40)).date().isoformat(), (dl + timedelta(days=40)).isoformat())
    opening_close = max(d["date"] for d in raw_cal if d["date"] < start_day)
    created = start - timedelta(days=14)
    with _Clock(created):
        k.write_plan(root, start, opening_close, sorted(set(carry_in_syms)), first_day or start_day)
    audit = out / "audit"
    _dump(audit / "attempt.json", {"reserved_utc": (created + timedelta(days=1)).isoformat(), "ack": {}})
    _dump(audit / "calendar.json", raw_cal)
    _dump(audit / "corporate_actions.json", list(audit_actions))
    _dump(audit / "ca_problems.json", list(audit_problems))
    _dump(audit / "manifest.json", {"outcome": "COMPLETE", "ack": {}, "pages": {}, "coverage": {},
                                    "files": {n: c.sha256_file(audit / n) for n in
                                              ("attempt.json", "calendar.json", "corporate_actions.json",
                                               "ca_problems.json")}})
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
             final_snapshot=True):
    """Build a synthetic s1_out/ under `root` through the REAL product gates (Task 7 test helper, not product code).

    Always: plan (s1_collect.write_plan), a COMPLETE audit attempt (calendar + corporate actions, manifest hashes),
    the opening seal (carry-in rows; bridge rows are stored after it), the START attestation (s1_run.attest_start)
    and a RUN-ACK mailbox message "run-ack" (a test may call do_prereg itself).
    With score_ready: prereg (s1_run.do_prereg), cohort rows (`lots`: symbol, qty, px, buy_day, sell=(day, px)|None,
    day = index of the post-START session), seals for `seal_days` (default: every session through the last trade),
    the stop attestation (if `stop_attest` and a stop exists), the final plan + a COMPLETE final attempt (bars from
    `bar_fn(symbol, date)`, None = missing) when a stop exists, the acquisition-time final snapshot (if
    `final_snapshot`) and a SCORE-ACK message "score-ack".
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
    with _Clock(start - timedelta(days=2)):
        r.attest_start(root, r.START_STATEMENT, receipt)
    s1_mailbox(root, "run-ack", r.run_token(root), start - timedelta(days=1, hours=1))
    info = {"start": start, "calendar": cal, "sessions": sessions, "rows": rows, "stop": None, "ledger": ledger,
            "now": start - timedelta(hours=12)}
    if not score_ready:
        return info

    with _Clock(start - timedelta(days=1)):
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
        last_eligible = [d for d in cal if z.open_instant(d) >= start and d["date"] <= dl.isoformat()][-1]
        t = z.window_end(last_eligible, cal) + timedelta(days=1)
        stop = z.stop_decision(seals, start, cal, today=t)
    info["stop"] = stop
    if stop_attest and stop["status"] in ("STOPPED", "TIMEOUT"):
        with _Clock(t):
            r.attest_stop(root, r.STOP_STATEMENT)
    if stop["status"] in ("STOPPED", "TIMEOUT"):
        stop_day = c.aware(stop["stop_close"]).astimezone(c.NY).date().isoformat()
        cohort_syms = sorted({L["symbol"] for L in lots})
        with _Clock(t + timedelta(hours=1)):
            k.write_final_plan(root, stop["stop_close"], cohort_syms, held_syms, first_day)
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
                                      "prereg_sha256": c.sha256_file(out / "prereg.json"),
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
