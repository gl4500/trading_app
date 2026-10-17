"""Task 8: connected synthetic lifecycle with real schemas (all R-IDs).

One scenario through every stage, using the REAL module interfaces on synthetic files under tmp_path only:
plan -> audit (httpx MockTransport: calendar + no corporate actions) -> OPENING SEAL (s1_checkpoint.
run_opening_checkpoint) -> 20:00 pre-START bridge rows (a BUY of a new ticker + a SELL of an audited carry-in lot)
-> START attestation -> RUN-ACK + prereg -> per session the synthetic "app" writes trade rows and its portfolio
upserts in SEPARATE commits; s1_checkpoint.run_checkpoint at C+45 (inconsistent when a late-cycle trade lands
before its upsert, retried at C+47), one close whose only capture fires 3 h late (unsealed: a missed seal), a
restart line appended to crash.log mid-trial -> >= 100 lots fully sold with overshoot, a dust write-off, an
unsold open lot and an endpoint-day entry -> stop -> stop attestation -> final plan (includes the bridge ticker)
-> final acquisition (MockTransport bars with irregular cent prices over two pages; one spin-off inside one lot's
window) -> final snapshot (s1_checkpoint.run_final_snapshot) -> SCORE-ACK -> one score -> a second score refuses
and changes no file.

The verdict and every retained lot's economics are checked against an INDEPENDENT oracle written below with
fractions.Fraction from the raw synthetic rows and bars only (no e1_sim, s1_books economics or s1_run pricing
helper is imported for it). Rules, from s1_design_v5.md §1/§7-§9/§11/§13-§14 and EXPERIMENTS_PREREG E1-TIMING /
E1-FILLS / E1-COSTS / E1-BASELINE: hard stop 8 % below the recorded entry price; trailing stop 12 % below the
highest completed post-entry close (initial high-water mark = entry price); active from the first session whose NY
date is strictly after the entry's NY date; per session, stop = max(hard, trail); open <= stop -> exit at the open,
else low <= stop -> exit at the stop level; the close updates the high-water mark for the NEXT session; not exited
-> marked at the stop close. Baseline = FIFO over the recorded fills with residuals marked at the stop close.
Costs: bp one-way on the entry notional, on every exit fill and on the terminal mark; return on the entry notional.
SHADOW PASS iff equal-lot mean return AND mean dollar PnL are strictly higher for P13 at 5 bp and 10 bp.
Exactness note: every price is a whole number of cents and every level is entry or close x 92/100 or 88/100, so a
non-equal comparison differs by >= 1/10000 dollar - far outside the core's 1e-12 relative touch recognition; plain
exact comparisons are therefore the registered rule here."""
import json
import random
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from fractions import Fraction
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

import s1_checkpoint as ck
import s1_collect as k
import s1_common
import s1_run as r
from conftest import Ledger, s1_mailbox

UTC = timezone.utc
NYZ = ZoneInfo("America/New_York")
KEYS = ("KEYID-task8-dummy", "SECRET-task8-dummy")
START = datetime(2026, 11, 2, 14, 30, tzinfo=UTC)          # Mon 09:30 EST (the day after the DST change)
START_DAY = "2026-11-02"
OPENING_CLOSE = "2026-10-30"                                # Fri, 16:00 EDT
FIRST_TRADE_DATE = "2026-10-01"
HOLIDAYS = {"2026-11-26", "2026-12-25", "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31"}
EARLY_CLOSE = {"2026-11-27": "13:00", "2026-12-24": "13:00"}
POOL = {"AAA": 10.0, "BBB": 3.5, "CCC": 25.0, "DDD": 0.75, "EEE": 12.0, "FFF": 40.0, "GGG": 6.25, "HHH": 2.0}
N_DAYS = 22                       # trading sessions 0..21 after START; day 21 is the expected stop
LATE_DAYS = (2, 9, 16)            # a late-cycle BUY at C+40 lands before its portfolio upsert
UNSEALED_DAY = 20                 # first close with >= 100 fully sold, but its only capture fires 3 h late
RESTART_DAY = 10
SPIN_DAY = 6
RECEIPT = {"head": "h8", "dirty": [], "files": {"agents/mean_reversion_agent.py": "f8"}, "config": {"K": "v"},
           "versions": {"python": "3.12"}}


# ------------------------------------------------------------------ synthetic world (raw data only)
def calendar_rows() -> list:
    d, out = date(2026, 9, 21), []
    while d <= date(2027, 6, 10):
        s = d.isoformat()
        if d.weekday() < 5 and s not in HOLIDAYS:
            out.append({"date": s, "open": "09:30", "close": EARLY_CLOSE.get(s, "16:00")})
        d += timedelta(days=1)
    return out


def ny(day: str, hhmm: str) -> datetime:
    return datetime.combine(date.fromisoformat(day), time.fromisoformat(hhmm), tzinfo=NYZ).astimezone(UTC)


REGIMES = {  # (gap-down prob, gap-down range, open drift/noise, close drift/noise, deep-low prob, deep-low range)
    "chop": (0.07, (0.07, 0.14), (0, 0.01), (0, 0.015), 0.08, (0.05, 0.12)),
    # Round 2 (controller ruling): a trending path. By the registered rule, a P13 lot rides the trend (the 12 % trail
    # sits far below a rising close) to the stop close, while the recorded baseline sold 1-4 sessions after entry at
    # an intraday price - so P13 should keep gains the baseline gives back; rare gap-downs still give hard stops.
    "trend": (0.02, (0.09, 0.14), (0.004, 0.006), (0.002, 0.008), 0.03, (0.05, 0.10)),
}


def gen_bars(rng, dates, regime="chop") -> dict:
    """Whole-cent OHLC (irregular cents), with occasional gap-downs and deep intraday lows so both P13 exits and
    opening fills occur."""
    gp, gr, (od, on), (cd, cn), lp, lr = REGIMES[regime]
    prev, out = rng.randint(2000, 30000), {}
    for d in dates:
        gap = -rng.uniform(*gr) if rng.random() < gp else rng.gauss(od, on)
        o = max(100, round(prev * (1 + gap)))
        cl = max(100, round(o * (1 + rng.gauss(cd, cn))))
        hi = max(o, cl) + rng.randint(1, max(2, max(o, cl) // 100))
        drop = rng.uniform(*lr) if rng.random() < lp else rng.uniform(0, 0.01)
        lo = max(1, min(o, cl) - rng.randint(0, max(1, int(min(o, cl) * drop))))
        out[d] = {"o": o / 100, "h": hi / 100, "l": lo / 100, "c": cl / 100}
        prev = cl
    return out


def _px_in(rng, bar) -> float:
    return rng.randint(round(bar["l"] * 100), round(bar["h"] * 100)) / 100


def build_world(regime="chop"):
    rng = random.Random(20261102)
    cal = calendar_rows()
    sessions = [x["date"] for x in cal if x["date"] >= START_DAY]
    tdays = sessions[:N_DAYS]
    syms = list(POOL) + ["DST", "SPN", "OPN", "END", "CI", "NEWT"]
    bars = {s: gen_bars(rng, tdays, regime) for s in syms}

    counts = {d: 5 for d in range(1, 20)}
    counts[4] += 1
    counts[12] += 1
    counts[20], counts[21] = 4, 3                  # 97 sold by day 19, 101 by day 20 (unsealed), 104 by day 21
    lots = [dict(sym="DST", qty=10.0, buy=3, sell=5, sell_qty=9.9995),          # dust: operational write-off
            dict(sym="DST", qty=10.0, buy=6, sell=8),
            dict(sym="SPN", qty=8.0, buy=3, sell=10),                           # spin-off inside its window
            dict(sym="SPN", qty=8.0, buy=8, sell=15)]                           # entered after the spin-off
    for L in lots:
        counts[L["sell"]] -= 1
    general = []
    for d in sorted(counts):
        for _ in range(counts[d]):
            sym = rng.choice(list(POOL))
            general.append(dict(sym=sym, qty=POOL[sym], buy=d - rng.randint(1, min(4, d)), sell=d))
    for L in LATE_DAYS:
        g = next(g for g in general if g["sell"] > L and not g.get("late"))
        g.update(buy=L, late=True)
    lots += general
    lots += [dict(sym="OPN", qty=5.0, buy=12, sell=None),                       # unsold at the stop
             dict(sym="END", qty=4.0, buy=21, sell=None)]                       # endpoint-day entry

    events = []
    nbuy, nsell = defaultdict(int), defaultdict(int)
    for L in sorted(lots, key=lambda L: (L["buy"], L.get("late", False))):
        d = tdays[L["buy"]]
        if L.get("late"):
            t, kind = ny(d, "16:40"), "late"
        else:
            t, kind = ny(d, "09:30") + timedelta(minutes=60 + 4 * nbuy[d]), "intraday"
            nbuy[d] += 1
        events.append(dict(sym=L["sym"], action="BUY", qty=L["qty"], px=_px_in(rng, bars[L["sym"]][d]), t=t,
                           kind=kind, day=L["buy"]))
    for L in sorted((L for L in lots if L["sell"] is not None), key=lambda L: L["sell"]):
        d = tdays[L["sell"]]
        t = ny(d, "09:30") + timedelta(minutes=150 + 3 * nsell[d], seconds=30)
        nsell[d] += 1
        events.append(dict(sym=L["sym"], action="SELL", qty=L.get("sell_qty", L["qty"]),
                           px=_px_in(rng, bars[L["sym"]][d]), t=t, kind="intraday", day=L["sell"]))
    events += [dict(sym="CI", action="BUY", qty=10.0, px=50.0, t=datetime(2026, 10, 1, 15, tzinfo=UTC),
                    kind="carry"),
               dict(sym="NEWT", action="BUY", qty=15.0, px=33.17, t=ny(OPENING_CLOSE, "20:00"), kind="bridge"),
               dict(sym="CI", action="SELL", qty=4.0, px=51.23, t=ny(OPENING_CLOSE, "20:05"), kind="bridge"),
               dict(sym="OPN", action="SELL", qty=5.0, px=47.11, t=ny(sessions[N_DAYS + 1], "11:00"),
                    kind="post")]
    events.sort(key=lambda e: e["t"])
    for i, e in enumerate(events):                 # odd ledger spellings of the stored time (one instant each)
        if i % 4 == 3:
            e["t"] = e["t"].replace(microsecond=250000)
        e["ts"] = [e["t"].isoformat(), e["t"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                   e["t"].replace(tzinfo=None).isoformat(sep=" "), e["t"].isoformat()][i % 4]
    return cal, sessions, tdays, bars, events


class App:
    """The synthetic app: a trade row commit, then (separately) its portfolio upsert; closes a position below
    0.001 share at a SELL (backend/trading/portfolio.py rule)."""

    def __init__(self, ledger):
        self.ledger, self.pos = ledger, {}

    def trade(self, e, upsert=True):
        e["id"] = self.ledger.trade(e["sym"], e["action"], e["qty"], e["px"], e["ts"])
        q = self.pos.get(e["sym"], 0.0) + (e["qty"] if e["action"] == "BUY" else -e["qty"])
        if e["action"] == "SELL" and q < 0.001:
            self.pos.pop(e["sym"], None)
        else:
            self.pos[e["sym"]] = q
        if upsert:
            self.upsert(e["sym"])

    def upsert(self, sym):
        if sym in self.pos:
            self.ledger.set_portfolio(sym, self.pos[sym])
        else:
            self.ledger.drop_portfolio(sym)


# ------------------------------------------------------------------ independent oracle (Fraction, raw data only)
def X(v) -> Fraction:
    return Fraction(str(v))


def oracle_fifo(events, upto: datetime) -> dict:
    """Economic FIFO over the recorded rows stored <= upto: per BUY lot its fills, remaining quantity and the
    instant it became fully sold (first SELL allocation leaving < 0.001)."""
    lots, open_ = {}, defaultdict(list)
    for e in sorted((e for e in events if e["t"] <= upto), key=lambda e: (e["t"], e["id"])):
        if e["action"] == "BUY":
            lot = {"id": e["id"], "sym": e["sym"], "t": e["t"], "px": X(e["px"]), "qty": X(e["qty"]),
                   "rem": X(e["qty"]), "fills": [], "sold_at": None}
            lots[e["id"]] = lot
            open_[e["sym"]].append(lot)
            continue
        left = X(e["qty"])
        while left > 0 and open_[e["sym"]]:
            lot = open_[e["sym"]][0]
            take = min(left, lot["rem"])
            lot["fills"].append((take, X(e["px"])))
            lot["rem"] -= take
            left -= take
            if lot["rem"] < Fraction(1, 1000) and lot["sold_at"] is None:
                lot["sold_at"] = e["t"]
            if lot["rem"] == 0:
                open_[e["sym"]].pop(0)
        assert left == 0, f"synthetic data oversold row {e['id']}"
    return lots


def oracle_counts(events, close: datetime) -> tuple:
    lots = oracle_fifo(events, close)
    cohort = [l for l in lots.values() if START <= l["t"] <= close]
    return len(cohort), sum(1 for l in cohort if l["sold_at"] is not None and l["sold_at"] <= close)


def oracle_pnl(basis, exits, terminal, bp) -> tuple:
    """exits [(q, p)] actual/simulated fills, terminal [(q, p)] marks; costs bp one-way on every notional."""
    rate = Fraction(bp, 10_000)
    proceeds = sum((q * p for q, p in exits + terminal), Fraction(0))
    costs = rate * (basis + proceeds)
    pnl = proceeds - basis - costs
    return pnl, pnl / basis


def oracle_p13(lot, bars, tdays, stop_date) -> dict:
    entry_date = lot["t"].astimezone(NYZ).date().isoformat()
    hard, hw = lot["px"] * Fraction(92, 100), lot["px"]
    eligible = 0
    for d in (d for d in tdays if entry_date < d <= stop_date):
        b = {f: X(v) for f, v in bars[d].items()}
        eligible += 1
        trail = hw * Fraction(88, 100)
        stop, reason = (hard, "hard") if hard >= trail else (trail, "trail")
        if b["o"] <= stop:
            return {"exit": b["o"], "reason": reason, "date": d, "terminal": False, "eligible": eligible,
                    "fill": "open"}
        if b["l"] <= stop:
            return {"exit": stop, "reason": reason, "date": d, "terminal": False, "eligible": eligible,
                    "fill": "level"}
        hw = max(hw, b["c"])
    return {"exit": X(bars[stop_date]["c"]), "reason": "endpoint", "date": stop_date, "terminal": True,
            "eligible": eligible, "fill": "close"}


def oracle_score(events, bars, tdays, stop_close: datetime, spin_date: str) -> dict:
    stop_date = stop_close.astimezone(NYZ).date().isoformat()
    lots = oracle_fifo(events, stop_close)
    cohort = [l for l in lots.values() if START <= l["t"] <= stop_close]
    excluded = set()
    for l in cohort:
        ed = l["t"].astimezone(NYZ).date().isoformat()
        req = [d for d in tdays if ed < d <= stop_date] + ([stop_date] if ed == stop_date else [])
        if (l["sym"] == "SPN" and ed < spin_date <= stop_date) or any(d not in bars[l["sym"]] for d in req):
            excluded.add(l["id"])
    kept = [l for l in cohort if l["id"] not in excluded]
    per, sums = {}, {bp: defaultdict(Fraction) for bp in (0, 1, 5, 10)}
    for l in kept:
        basis, close = l["qty"] * l["px"], X(bars[l["sym"]][stop_date]["c"])
        cand = oracle_p13(l, bars[l["sym"]], tdays, stop_date)
        per[l["id"]] = {"cand": cand, "base": {}, "p13": {}}
        for bp in (0, 1, 5, 10):
            b_ = oracle_pnl(basis, l["fills"], [(l["rem"], close)] if l["rem"] > 0 else [], bp)
            fill = [(l["qty"], cand["exit"])]
            c_ = oracle_pnl(basis, [] if cand["terminal"] else fill, fill if cand["terminal"] else [], bp)
            per[l["id"]]["base"][bp], per[l["id"]]["p13"][bp] = b_, c_
            for key, v in (("b_pnl", b_[0]), ("b_ret", b_[1]), ("c_pnl", c_[0]), ("c_ret", c_[1])):
                sums[bp][key] += v
    n = len(kept)
    means = {bp: {key: v / n for key, v in s.items()} for bp, s in sums.items()}
    passes = all(means[bp]["c_ret"] > means[bp]["b_ret"] and means[bp]["c_pnl"] > means[bp]["b_pnl"]
                 for bp in (5, 10))
    disp = ("INCONCLUSIVE" if 10 * len(excluded) > len(cohort) else
            "INSUFFICIENT" if len(cohort) - len(excluded) < 30 else ("SHADOW PASS" if passes else "FAIL"))
    return {"n": len(cohort), "k": len(excluded), "excluded": excluded, "per": per, "means": means,
            "verdict": disp, "cohort_ids": {l["id"] for l in cohort}}


def tree_hashes(d: Path) -> dict:
    return {p.relative_to(d).as_posix(): s1_common.sha256_file(p) for p in sorted(d.rglob("*")) if p.is_file()}


# ------------------------------------------------------------------ the connected scenario
@pytest.mark.parametrize("regime,expected,post_stop", [("chop", "FAIL", None), ("trend", "SHADOW PASS", None),
                                                       ("chop", "FAIL", "buy"), ("chop", "FAIL", "receipt")])
def test_connected_lifecycle_matches_independent_oracle(tmp_path, monkeypatch, regime, expected, post_stop):
    """Task 8: plan -> audit -> opening seal -> bridge -> START attestation -> prereg -> scheduled checkpoints
    (inconsistent/retried, late, restart) -> stop -> stop attestation -> final plan -> final acquisition -> final
    snapshot -> one score == the independent Fraction oracle; a second score refuses and overwrites nothing.
    Task 11 (controller-added), C-1 (the final review's probe): `post_stop` = "buy" - the scheduler keeps running
    after the stop, a new MR BUY lands and the next close's scheduled checkpoint fires; "receipt" - the same with the
    semantic receipt changed after the stop (e.g. a pull into the live checkout). Either capture is recorded as
    post_stop and neither seals nor aborts; the score still equals the oracle (never ABORTED-INVALID)."""
    root, out = tmp_path, tmp_path / "s1_out"
    cal, sessions, tdays, bars, events = build_world(regime)
    clock = {"t": START - timedelta(days=14)}
    monkeypatch.setattr(s1_common, "now_utc", lambda: clock["t"])

    def at(t):
        clock["t"] = t
        return t

    proc = {"pid": 1000, "process_start": "2026-10-01T09:00:00"}
    crash = root / "crash.log"
    crash.write_text("2026-10-01 09:00:00,000 [PROCESS START] pid=1000\n" * 2, encoding="utf-8")
    ledger = Ledger(root / "trading.db")
    app = App(ledger)
    receipt = json.loads(json.dumps(RECEIPT))                 # Task 11: a per-run copy (the "receipt" probe edits it)
    receipt_fn, process_fn = (lambda: json.loads(json.dumps(receipt))), (lambda: dict(proc))

    def close_of(day: str) -> datetime:
        row = next(x for x in cal if x["date"] == day)
        return ny(day, row["close"])

    # 1. plan (fixed 14 days before START) and 2. the audit: calendar + no corporate actions, metadata only
    app.trade(next(e for e in events if e["kind"] == "carry"))
    k.write_plan(root, START, OPENING_CLOSE, ["CI"], FIRST_TRADE_DATE)
    calls = []

    def audit_handler(req):
        calls.append(str(req.url))
        if "calendar" in str(req.url):
            return httpx.Response(200, json=cal)
        return httpx.Response(200, json={"corporate_actions": {}, "next_page_token": None})
    s1_mailbox(root, "audit-ack", k.audit_token(root), at(START - timedelta(days=13, hours=1)))
    at(START - timedelta(days=13))
    m = k.do_audit(root, "audit-ack", httpx.Client(transport=httpx.MockTransport(audit_handler)), KEYS)
    assert m["outcome"] == "COMPLETE" and calls and not any("/bars" in u for u in calls)

    # 3. the OPENING SEAL (the close immediately before START), by the real opening checkpoint
    sch = close_of(OPENING_CLOSE) + timedelta(minutes=45)
    act = at(sch + timedelta(seconds=30))
    rep = ck.run_opening_checkpoint(root, ledger.path, sch, receipt_fn, process_fn, crash, now=lambda: act)
    assert rep["seal"]["written"] and rep["consistent"] and rep["entries"] == ck.NA

    # 4. pre-START bridge rows stored at 20:00 / 20:05 ET, after the opening seal
    bridge = [e for e in events if e["kind"] == "bridge"]
    for e in bridge:
        app.trade(e)

    # 5. START attestation, then RUN-ACK strictly after it, then prereg (all strictly before START)
    at(START - timedelta(days=1, hours=2, minutes=30))
    r.attest_start(root, r.START_STATEMENT, receipt_fn())
    s1_mailbox(root, "run-ack", r.run_token(root), START - timedelta(days=1, hours=1, minutes=30))
    at(START - timedelta(hours=24))
    pr = r.do_prereg(root, "run-ack", receipt_fn())
    assert pr["start"] == START.isoformat()

    # 6. sessions: trade commits then upserts; scheduled checkpoints
    def checkpoint(scheduled, actual):
        at(actual)
        return ck.run_checkpoint(root, ledger.path, scheduled, receipt_fn, process_fn, crash, now=lambda: actual)

    reports = {}
    for i, d in enumerate(tdays):
        if i == RESTART_DAY:                                   # the operator restarts the app (identical files)
            with crash.open("a", encoding="utf-8") as f:
                f.write("2026-11-16 08:00:00,000 [PROCESS START] pid=2000\n" * 2)
            proc.update(pid=2000, process_start="2026-11-16T08:00:00")
        for e in sorted((e for e in events if e.get("day") == i and e["kind"] == "intraday"), key=lambda e: e["t"]):
            app.trade(e)
        C = close_of(d)
        late = [e for e in events if e.get("day") == i and e["kind"] == "late"]
        if late:
            app.trade(late[0], upsert=False)                   # the trade commit lands; the upsert has not
            r45 = checkpoint(C + timedelta(minutes=45), C + timedelta(minutes=45, seconds=30))
            assert r45["capture_ok"] and not r45["consistent"] and not r45["seal"]["written"], (d, r45)
            app.upsert(late[0]["sym"])
            rep = checkpoint(C + timedelta(minutes=47), C + timedelta(minutes=47, seconds=30))
            assert rep["consistent"] and rep["seal"]["written"], (d, rep)
        elif i == UNSEALED_DAY:                                # scheduler fired 3 h late (PC asleep)
            rep = checkpoint(C + timedelta(minutes=45), C + timedelta(hours=3, minutes=45))
            assert rep["late"] and rep["consistent"] and not rep["seal"]["written"], (d, rep)
        else:
            rep = checkpoint(C + timedelta(minutes=45), C + timedelta(minutes=45, seconds=30))
            assert rep["consistent"] and rep["seal"]["written"], (d, rep)
        assert rep["fence_violations"] == [] and rep["receipt_match"] is True and rep["restart_gaps"] == [], rep
        assert (rep["entries"], rep["sold"]) == oracle_counts(events, C), (d, rep["entries"], rep["sold"])
        assert rep["stop"]["status"] == ("STOPPED" if i == N_DAYS - 1 else "RUNNING"), (d, rep["stop"])
        reports[i] = rep

    stop_close = close_of(tdays[-1])
    unsealed_close = close_of(tdays[UNSEALED_DAY])
    # independent stop expectation: the first qualifying close is unsealed; the next (sealed) one is the stop,
    # with overshoot and every entry through it
    assert oracle_counts(events, close_of(tdays[UNSEALED_DAY - 1]))[1] < 100 <= oracle_counts(events, unsealed_close)[1]
    assert oracle_counts(events, stop_close)[1] > 100
    assert reports[N_DAYS - 1]["stop"] == {"status": "STOPPED", "stop_close": stop_close.isoformat(),
                                           "missed": [tdays[UNSEALED_DAY]]}
    for L in LATE_DAYS:                                        # the inconsistent C+45 capture is preserved
        cap = out / "captures" / tdays[L]
        assert len(list(cap.glob("*.report.json"))) == 2
        seal = json.loads((out / "seals" / f"{tdays[L]}.json").read_text(encoding="utf-8"))
        assert seal["capture"]["scheduled"] == (close_of(tdays[L]) + timedelta(minutes=47)).isoformat()
    assert not (out / "seals" / f"{tdays[UNSEALED_DAY]}.json").exists()

    # 7. post-stop: the unsold open lot is sold by the app after the stop (must not reach either arm)
    app.trade(next(e for e in events if e["kind"] == "post"))

    # 8. stop attestation, then the final plan (carry-in incl. the bridge ticker)
    at(stop_close + timedelta(hours=15))
    att = r.attest_stop(root, r.STOP_STATEMENT)
    assert att["stop_close"] == stop_close.isoformat()
    cohort_syms = sorted({e["sym"] for e in events if e["action"] == "BUY" and START <= e["t"] <= stop_close})
    at(stop_close + timedelta(hours=16))
    fplan = json.loads(k.write_final_plan(root).read_text(encoding="utf-8"))     # Task 11 (I-4): derived
    assert "NEWT" in fplan["bar_symbols"] and fplan["ca_symbols_full_history"] == ["CI", "NEWT"]
    assert fplan["stop_close"] == att["stop_close"] and fplan["ca_symbols_window"] == cohort_syms
    assert fplan["full_history_start"] == FIRST_TRADE_DATE

    # 9. the final acquisition: two bar pages (irregular cents), one spin-off inside one SPN lot's window
    spin_date = tdays[SPIN_DAY]
    spin = {"id": "spin-1", "source_symbol": "SPN", "source_cusip": "000000001", "source_rate": 1.0,
            "new_symbol": "SPNC", "new_cusip": "000000002", "new_rate": 0.5, "process_date": spin_date,
            "ex_date": spin_date}
    fcalls = []

    def final_handler(req):
        fcalls.append(req)
        p = req.url.params
        if "/bars" in str(req.url):
            syms = p["symbols"].split(",")
            half = syms[: len(syms) // 2] if "page_token" not in p else syms[len(syms) // 2:]
            page = {s: [{"t": ny(d, "00:00").strftime("%Y-%m-%dT%H:%M:%SZ"), "v": 100, **bars[s][d]}
                        for d in tdays] for s in half}
            return httpx.Response(200, json={"bars": page, "next_page_token": None if "page_token" in p else "pg2"})
        found = {"spin_offs": [spin]} if "SPN" in p["symbols"].split(",") and p["start"] == START_DAY else {}
        return httpx.Response(200, json={"corporate_actions": found, "next_page_token": None})
    acq_at = ny(sessions[N_DAYS + 3], "07:00")                 # after the close of the 3rd session after the stop
    s1_mailbox(root, "acq-ack", k.ACQUIRE_ACK.format(collector=k.collector_sha(),
                                                     plan=s1_common.sha256_file(out / "final_plan.json"),
                                                     prereg=s1_common.sha256_file(out / "prereg.json"),
                                                     attest=s1_common.sha256_file(out / "attest_stop.json")),
               acq_at - timedelta(hours=1))
    at(acq_at)
    fm = k.do_final(root, "acq-ack", httpx.Client(transport=httpx.MockTransport(final_handler)), KEYS)
    assert fm["outcome"] == "COMPLETE"
    assert json.loads((out / "final" / "bar_problems.json").read_text(encoding="utf-8")) == []
    assert sum(1 for q in fcalls if "/bars" in str(q.url)) == 2

    # 10. the acquisition-time final snapshot, fence-checked against every seal
    snap_at = at(acq_at + timedelta(hours=1))
    snap = ck.run_final_snapshot(root, ledger.path, now=lambda: snap_at)
    assert snap["capture_ok"] and snap["fence_checked"] and snap["fence_violations"] == [], snap

    # 10b. Task 11 (C-1): the scheduler keeps running after the stop (the final review's probe, both variants)
    if post_stop is not None:
        pd = sessions[N_DAYS + 3]
        newt = ny(pd, "11:00")
        app.trade(dict(sym="ZZZ", action="BUY", qty=1.0, px=10.0, t=newt, ts=newt.isoformat()))
        if post_stop == "receipt":
            receipt["head"] = "post-stop-commit"
        pc = checkpoint(close_of(pd) + timedelta(minutes=45), close_of(pd) + timedelta(minutes=45, seconds=30))
        assert pc.get("post_stop") is True and pc["seal"]["written"] is False, pc
        assert pc["stop"]["status"] == "STOPPED" and pc["stop"]["stop_close"] == stop_close.isoformat(), pc["stop"]
        assert pc["receipt_match"] is (post_stop != "receipt")              # reported only
        assert not (out / "aborted.json").exists() and not (out / "seals" / f"{pd}.json").exists()

    # 11. SCORE-ACK and the one score
    s1_mailbox(root, "score-ack", r.score_token(root), acq_at + timedelta(days=1))
    at(acq_at + timedelta(days=1, hours=2))
    rep = r.score(root, "score-ack")

    # ---- assertions against the raw scenario and the independent oracle
    o = oracle_score(events, bars, tdays, stop_close, spin_date)
    assert o["verdict"] == expected, (regime, o["verdict"])      # the oracle's own verdict (both branches covered)
    bridge_ids = [e["id"] for e in bridge]
    spin_lots = [e["id"] for e in events if e["sym"] == "SPN" and e["action"] == "BUY"]
    assert o["excluded"] == {spin_lots[0]} and o["n"] >= 100 and o["k"] == 1
    assert rep["outcome"] == "SCORED" and rep["reasons"] == [], rep["reasons"]
    assert rep["stop"]["stop_close"] == stop_close.isoformat() and rep["missed_seals"] == [tdays[UNSEALED_DAY]]
    # cohort excludes the bridge rows; the bridge ticker is carry-in inventory
    assert not set(bridge_ids) & o["cohort_ids"]
    assert not set(bridge_ids) & ({x["id"] for x in rep["lots"]} | {int(i) for i in rep["excluded"]})
    assert rep["carry_in"]["bridge_rows"] == bridge_ids and "NEWT" in rep["carry_in"]["held_at_start"]
    # Task 8b (controller-added): the first post-START seal classifies the 20:00 bridge rows as bridge and records
    # the bridge hash; the score's provenance carries that same hash (recomputed from the frozen final ledger)
    first_post = min((json.loads(p.read_text(encoding="utf-8")) for p in (out / "seals").glob("*.json")),
                     key=lambda x: (s1_common.aware(x["close"]) < START, s1_common.aware(x["close"])))
    assert s1_common.aware(first_post["close"]) >= START
    assert set(bridge_ids) <= set(first_post["bridge"]["bridge_row_ids"])
    assert not set(bridge_ids) & set(first_post["bridge"]["cohort_era_row_ids"])
    assert rep["bridge_provenance"]["bridge_sha256"] == first_post["bridge"]["bridge_sha256"]
    # the spin-off lot is excluded in BOTH arms (absent from the paired lots); the later SPN lot is retained
    assert set(rep["excluded"]) == {str(spin_lots[0])}
    assert rep["excluded"][str(spin_lots[0])] == [f"spin_offs spin-1 on {spin_date}"]
    assert spin_lots[0] not in {x["id"] for x in rep["lots"]} and spin_lots[1] in {x["id"] for x in rep["lots"]}
    # the restart is listed (observed in crash.log), no observation gap
    assert rep["restarts"] == {"observed_in_crash_log_minimum": [{"ts": "2026-11-16 08:00:00,000", "pid": 2000}],
                               "observation_gaps": []}
    # quantity bridge: the dust write-off vs the economic residual (reported, never forced to zero)
    assert abs(rep["quantity_bridge"]["DST"]["writeoff"] - 0.0005) < 1e-12
    assert abs(rep["quantity_bridge"]["DST"]["economic_residual"] - 0.0005) < 1e-12
    end_lot = next(e["id"] for e in events if e["sym"] == "END")
    assert rep["zero_eligible"] == [end_lot]
    # counts, verdict and provenance
    assert (rep["n"], rep["k"], rep["retained"]) == (o["n"], o["k"], o["n"] - o["k"])
    assert rep["verdict"] == o["verdict"] and rep["provenance"] == "VERIFIED"
    assert rep["nomination"] is (o["verdict"] == "SHADOW PASS")
    # every retained lot, both arms, every cost level: equal to the oracle (exact value, correctly rounded)
    got = {x["id"]: x for x in rep["lots"]}
    assert set(got) == set(o["per"])
    for lid, want in o["per"].items():
        g = got[lid]
        cand = g["cand"]["5"]["P13"]
        assert (cand["reason"], cand["exit_date"], cand["eligible_sessions"]) == \
            (want["cand"]["reason"], want["cand"]["date"], want["cand"]["eligible"]), (lid, cand, want["cand"])
        for bp in (0, 1, 5, 10):
            assert (g["base"][str(bp)]["pnl"], g["base"][str(bp)]["ret"]) == tuple(map(float, want["base"][bp])), \
                (lid, bp, "baseline")
            assert (g["cand"][str(bp)]["P13"]["pnl"], g["cand"][str(bp)]["P13"]["ret"]) == \
                tuple(map(float, want["p13"][bp])), (lid, bp, "P13")
    for bp in (0, 1, 5, 10):
        lv, mn = rep["levels"][str(bp)], o["means"][bp]
        assert (lv["cand_mean_ret"], lv["base_mean_ret"], lv["cand_mean_pnl"], lv["base_mean_pnl"]) == \
            (float(mn["c_ret"]), float(mn["b_ret"]), float(mn["c_pnl"]), float(mn["b_pnl"])), bp
    reasons = {w["cand"]["reason"] for w in o["per"].values()}
    assert {"hard", "trail", "endpoint"} <= reasons, reasons           # the scenario exercises every exit kind
    fills = {w["cand"]["fill"] for w in o["per"].values()}
    assert fills == {"open", "level", "close"}, fills                  # ... and every fill rule

    # 12. a second score refuses and no file under s1_out changes
    before = tree_hashes(out)
    at(acq_at + timedelta(days=1, hours=3))
    with pytest.raises(SystemExit, match="an attempt already exists; one attempt only"):   # Task 8 review M1
        r.score(root, "score-ack")
    assert tree_hashes(out) == before
