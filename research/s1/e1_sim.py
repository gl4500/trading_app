"""E1 simulation core: one candidate exit policy applied to one fixed recorded entry lot on daily bars
(EXPERIMENTS_PREREG.md, E1-TIMING / E1-FILLS / E1-UNITS / E1-COSTS / E1-POLICIES).

Per eligible session (NY date strictly after the entry's NY date):
  active stop = max(hard level, trailing level)   (trailing level = highest completed post-entry close x (1 - trail))
  1. open <= stop -> exit at open;  open >= target -> exit at open
  2. low <= stop -> exit at stop;   high >= target -> exit at target;  both -> stop first;  equality is a hit
  3. time stop at the close of the Nth eligible session
  4. the close updates the trailing reference for the NEXT session
Reason "hard" when hard >= trail level (ties -> hard), else "trail". Numeric convention (EXACT): every input
number is read as the exact rational of its shortest round-trip decimal (x(110.0) = 110, x(0.1) = 1/10); levels,
split adjustments, trailing references, fills, costs, PnL and returns are exact rationals; floats appear only in
reported fields (correctly rounded from the exact value) and the descriptive bootstrap. Paired comparisons are
decided on exact values. A relative LEVEL_EPS of 1e-12 only RECOGNISES a touch; every fill is the exact open
(opening trigger) or the exact level clamped into [low, high]. A verified split on its effective session
(entry before it) multiplies shares and divides every price reference before that session's checks. A lot not
exited by its endpoint session is marked at that session's close (reason "endpoint"). A missing required bar
raises MissingBar - never treated as "no trigger".
"""
from datetime import datetime
from fractions import Fraction
from itertools import product
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
LEVEL_EPS = Fraction(1, 10**12)   # relative touch recognition only (equality hits); never moves a fill


def x(v) -> Fraction:
    """Exact rational of a reported number: its shortest round-trip decimal (floats), exact for int/Fraction."""
    if isinstance(v, Fraction):
        return v
    if isinstance(v, bool):
        raise TypeError("bool is not a number here")
    if isinstance(v, int):
        return Fraction(v)
    return Fraction(repr(float(v)))


def _at_or_below(price, level):
    return price <= level * (1 + LEVEL_EPS)


def _at_or_above(price, level):
    return price >= level * (1 - LEVEL_EPS)


class MissingBar(Exception):
    """A required session bar is absent: the agent's result is INCONCLUSIVE, never 'no trigger'."""


def ny_date(ts: datetime) -> str:
    return ts.astimezone(NY).date().isoformat()


def policy_family() -> list:
    fam = [{"id": "P00", "no_change": True}]
    for i, (hard, trail, target, time) in enumerate(product((0.05, 0.08), (0.08, 0.12), (None, 0.10), (None, 20)),
                                                    start=1):
        fam.append({"id": f"P{i:02d}", "hard": hard, "trail": trail, "target": target, "time": time})
    return fam


def simulate_lot(entry_ts, entry_px, qty, bars, splits, policy, endpoint_date):
    """bars: the required window - ordered sessions after the entry's NY date through endpoint_date, or just the
    endpoint session for an endpoint-day entry (None = missing bar).
    Returns exit_date, exit_px, reason, shares (split-adjusted), gross_proceeds, eligible_sessions."""
    entry_date = ny_date(entry_ts)
    split_on = {s["date"]: x(s["ratio"]) for s in splits if s["date"] > entry_date}
    shares, ref, hw = x(qty), x(entry_px), x(entry_px)
    hard, trail, target, time = policy.get("hard"), policy.get("trail"), policy.get("target"), policy.get("time")
    hard, trail, target = (None if v is None else x(v) for v in (hard, trail, target))
    eligible, last = 0, None
    for b in bars:
        if b is None:
            raise MissingBar(f"missing bar after {last['date'] if last else entry_date}")
        d = b["date"]
        if d > endpoint_date:
            break
        if d in split_on:
            ratio = split_on[d]
            shares, ref, hw = shares * ratio, ref / ratio, hw / ratio
        last = b
        if d <= entry_date:
            continue
        o, h, lo, c = x(b["o"]), x(b["h"]), x(b["l"]), x(b["c"])
        eligible += 1
        hard_lvl = ref * (1 - hard) if hard is not None else None
        trail_lvl = hw * (1 - trail) if trail is not None else None
        levels = [x for x in (hard_lvl, trail_lvl) if x is not None]
        stop = max(levels) if levels else None
        stop_reason = "hard" if (hard_lvl is not None and (trail_lvl is None or hard_lvl >= trail_lvl)) else "trail"
        tgt = ref * (1 + target) if target is not None else None
        exit_px = reason = None
        # Numeric convention: LEVEL_EPS only RECOGNISES a touch; every fill is an observed price or a level
        # clamped into the session's [low, high] - an opening trigger fills exactly at the open.
        if stop is not None and _at_or_below(o, stop):
            exit_px, reason = o, stop_reason
        elif tgt is not None and _at_or_above(o, tgt):
            exit_px, reason = o, "target"
        elif stop is not None and _at_or_below(lo, stop):
            exit_px, reason = max(stop, lo), stop_reason
        elif tgt is not None and _at_or_above(h, tgt):
            exit_px, reason = min(tgt, h), "target"
        elif time is not None and eligible == time:
            exit_px, reason = c, "time"
        if reason is not None:
            return _result(d, exit_px, reason, shares, eligible)
        hw = max(hw, c)
        if d == endpoint_date:
            break
    if last is None or last["date"] != endpoint_date:
        raise MissingBar(f"endpoint bar {endpoint_date} missing")
    return _result(last["date"], x(last["c"]), "endpoint", shares, eligible)


def _result(d, exit_px, reason, shares, eligible) -> dict:
    """Exact values under *_x; float fields are the correctly rounded exact values (reporting only)."""
    return {"exit_date": d, "exit_px": float(exit_px), "reason": reason, "shares": float(shares),
            "gross_proceeds": float(shares * exit_px), "eligible_sessions": eligible,
            "exit_px_x": exit_px, "shares_x": shares}


def lot_economics(entry_notional, exits, bp):
    """exits: [(qty, price, kind)] with kind 'exit' (an actual or simulated fill) or 'terminal' (endpoint mark).
    PnL = proceeds - entry basis - entry cost - exit costs - terminal cost; return on the initial notional."""
    rate = Fraction(bp, 10_000)
    ex = [(x(q), x(p), k) for q, p, k in exits]
    basis = x(entry_notional)
    proceeds = sum((q * p for q, p, _ in ex), Fraction(0))
    exit_cost = sum((q * p * rate for q, p, k in ex if k == "exit"), Fraction(0))
    terminal_cost = sum((q * p * rate for q, p, k in ex if k == "terminal"), Fraction(0))
    entry_cost = basis * rate
    gross = proceeds - basis
    pnl = gross - entry_cost - exit_cost - terminal_cost
    out = {k: float(v) for k, v in (("gross_pnl", gross), ("entry_cost", entry_cost), ("exit_cost", exit_cost),
                                    ("terminal_cost", terminal_cost), ("pnl", pnl), ("ret", pnl / basis))}
    out.update(_pnl=pnl, _ret=pnl / basis)          # exact values: every decision uses these, never the floats
    return out


# ---------------------------------------------------------------- calendar and cohorts (E1-COHORT)
def close_instant(day: dict) -> datetime:
    """Aware close instant of a calendar session (NY local close time, early closes honoured)."""
    h, m = (int(x) for x in day["close"].split(":"))
    y, mo, d = (int(x) for x in day["date"].split("-"))
    return datetime(y, mo, d, h, m, tzinfo=NY)


def cohorts(entries, calendar, final_date):
    """B from all valid entry metadata (sorted aware timestamp, id; index n//2); D = close of the last completed
    session strictly before B; T = close of final_date. Discovery <= D; purged D < e < B; test B <= e <= T;
    after T outside. Metadata only."""
    es = sorted(entries, key=lambda r: (r["ts"], r["id"]))
    b = es[len(es) // 2]["ts"]
    closes = [close_instant(c) for c in calendar]
    prior = [c for c in closes if c < b]
    if not prior:
        raise ValueError("no completed session before B")
    d_inst = max(prior)
    final = [c for c in calendar if c["date"] == final_date]
    if len(final) != 1:
        raise ValueError(f"final session {final_date} not in calendar")
    t_inst = close_instant(final[0])
    out = {"B": b, "D": d_inst, "T": t_inst, "discovery": [], "purged": [], "test": [], "outside": []}
    for r in es:
        if r["ts"] <= d_inst:
            out["discovery"].append(r["id"])
        elif r["ts"] < b:
            out["purged"].append(r["id"])
        elif r["ts"] <= t_inst:
            out["test"].append(r["id"])
        else:
            out["outside"].append(r["id"])
    return out


# ---------------------------------------------------------------- recorded-exit baseline (E1-BASELINE)
QTY_TOL, FLOAT_SNAP_SHARES = 1e-6, 1e-12            # identical to the approved P1 rules


def baseline_lots(rows, endpoint, splits, orphans=None):
    """FIFO over ONE symbol-agnostic row list (agent's rows), reading only rows with ts <= endpoint, in
    (timestamp, id) order. Each lot records its actual SELL allocations as fills [(qty, px)] in the then-current
    (split-adjusted) units and its remaining quantity at the endpoint. Splits: applied to open lots when the
    first row dated on/after the effective date is processed, and finally for effective dates <= the endpoint's
    NY date. Oversell up to QTY_TOL is accepted (excess attributed to the last lot consumed); a remainder of at
    most FLOAT_SNAP_SHARES closes the lot (dust written off). A SELL within QTY_TOL with NO open lot is P1's
    unattributed proceeds: attributed to no lot, appended to `orphans` when given (reconciliation adds them)."""
    from collections import defaultdict
    rows = sorted((r for r in rows if r["ts"] <= endpoint), key=lambda r: (r["ts"], r["id"]))
    lots, open_lots, applied = [], defaultdict(list), set()

    def apply_splits(upto: str):
        for ev in splits:
            key = (ev["symbol"], ev["date"])
            if key in applied or ev["date"] > upto:
                continue
            applied.add(key)
            for lot in open_lots.get(ev["symbol"], []):
                lot["rem_qty"] *= x(ev["ratio"])

    for r in rows:
        apply_splits(ny_date(r["ts"]))
        qf, pf, sym = float(r["shares"]), float(r["price"]), r["symbol"]
        if not (qf > 0 and pf > 0) or qf != qf or pf != pf or qf == float("inf") or pf == float("inf"):
            raise ValueError(f"INVALID row {r['id']}")
        qty, px = x(qf), x(pf)                              # exact replay (E1 numeric convention)
        if r["action"] == "BUY":
            lot = {"id": r["id"], "symbol": sym, "entry_ts": r["ts"], "entry_px": px, "qty": qty,
                   "entry_notional": qty * px, "rem_qty": qty, "fills": []}
            lots.append(lot)
            open_lots[sym].append(lot)
        elif r["action"] == "SELL":
            held = sum((l["rem_qty"] for l in open_lots[sym]), Fraction(0))
            if qty > held + x(QTY_TOL):
                raise ValueError(f"INVALID oversell {r['id']}")
            left, last = qty, None
            while left > 0 and open_lots[sym]:
                lot = open_lots[sym][0]
                last = lot
                if left >= lot["rem_qty"] or lot["rem_qty"] - left <= x(FLOAT_SNAP_SHARES):
                    sold = min(left, lot["rem_qty"])
                    lot["fills"].append((sold, px))
                    left -= sold
                    lot["rem_qty"] = Fraction(0)
                    open_lots[sym].pop(0)
                else:
                    lot["fills"].append((left, px))
                    lot["rem_qty"] -= left
                    left = Fraction(0)
            if left > 0:
                if last is None:
                    if orphans is not None:
                        orphans.append({"id": r["id"], "symbol": sym, "qty": float(left), "px": float(px)})
                else:
                    last["fills"].append((left, px))      # accepted round-off overshoot
        else:
            raise ValueError(f"INVALID action {r['action']} {r['id']}")
    apply_splits(ny_date(endpoint))
    return lots


def baseline_economics(lot, endpoint_close, bp):
    exits = [(q, p, "exit") for q, p in lot["fills"]]
    if lot["rem_qty"] > 0:
        exits.append((lot["rem_qty"], endpoint_close, "terminal"))
    return lot_economics(entry_notional=lot["entry_notional"], exits=exits, bp=bp)


# ---------------------------------------------------------------- selection, verdict, bootstrap (E1-SELECT/-VERDICT/-BOOT)
MIN_LOTS, COST_PRIMARY, COST_GATE = 30, 5, (5, 10)
BOOT_DRAWS, BOOT_SEED, BOOT_MIN_FINITE, BOOT_MIN_SYMBOLS = 5000, 20261010, 1000, 5


def _mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def compare(lots, pid, bp) -> dict:
    """Paired candidate-vs-baseline summary on the SAME lots at one cost level (unrounded)."""
    # decided on the ORIGINAL exact per-lot values (_ret/_pnl from lot_economics; a missing exact value raises):
    # order-independent, and exactly equal economics are always equal
    c_ret, b_ret = exact_sum(lots, pid, bp, "_ret"), exact_sum(lots, None, bp, "_ret")
    c_pnl, b_pnl = exact_sum(lots, pid, bp, "_pnl"), exact_sum(lots, None, bp, "_pnl")
    n = len(lots)
    out = {"n": n, "cand_mean_ret": float(c_ret / n), "base_mean_ret": float(b_ret / n),
           "cand_mean_pnl": float(c_pnl / n), "base_mean_pnl": float(b_pnl / n),
           "cand_total_pnl": float(c_pnl), "base_total_pnl": float(b_pnl), "diff_total_pnl": float(c_pnl - b_pnl)}
    out["improves"] = bool(c_ret > b_ret and c_pnl > b_pnl)    # equal n: mean pnl > implies total >= (frozen rule)
    return out


def exact_sum(lots, pid, bp, key) -> Fraction:
    """Exact sum of one per-lot value over the lots: candidate `pid`, or the baseline when pid is None."""
    return sum(((l["base"][bp] if pid is None else l["cand"][bp][pid])[key] for l in lots), Fraction(0))


def select_policy(lots) -> dict:
    """Discovery at 5 bp only; strict improvement in both means with total nondecreasing; highest equal-lot mean
    wins; exact ties -> lowest ID; no valid candidate -> NO-CHANGE (P00)."""
    if len(lots) < MIN_LOTS:
        return {"status": "INSUFFICIENT", "policy": None, "n": len(lots), "table": []}
    table = []
    for p in policy_family()[1:]:
        c = compare(lots, p["id"], COST_PRIMARY)
        c["policy"] = p["id"]
        table.append(c)
    valid = [c for c in table if c["improves"]]
    score = {c["policy"]: exact_sum(lots, c["policy"], COST_PRIMARY, "_ret") for c in valid}   # exact; same n
    best = max(score.values(), default=None)
    pid = min((p for p, v in score.items() if v == best), default=None)
    if not valid:
        return {"status": "NO-CHANGE", "policy": "P00", "n": len(lots), "table": table}
    return {"status": "SELECTED", "policy": pid, "n": len(lots), "table": table}


def verdict(lots, pid) -> dict:
    if pid == "P00":
        return {"verdict": "NO-CHANGE", "policy": pid, "n": len(lots)}
    if len(lots) < MIN_LOTS:
        return {"verdict": "INSUFFICIENT", "policy": pid, "n": len(lots)}
    levels = {bp: compare(lots, pid, bp) for bp in (1, 5, 10)}
    passed = all(levels[bp]["improves"] for bp in COST_GATE)
    return {"verdict": "SCREEN PASS" if passed else "FAIL", "policy": pid, "n": len(lots), "levels": levels}


def paired_bootstrap(lots, pid, bp) -> dict:
    """Descriptive: candidate-minus-baseline equal-lot mean, same symbol draws for both arms."""
    import numpy as np
    syms = sorted({l["symbol"] for l in lots})
    out = {"bp": bp, "n_draws": BOOT_DRAWS, "n_finite": 0, "n_undefined": 0, "interval": None, "n_symbols": len(syms)}
    if len(syms) < BOOT_MIN_SYMBOLS:
        out.update(n_draws=0, note="fewer than 5 symbols: no interval")
        return out
    by = {s: [l for l in lots if l["symbol"] == s] for s in syms}
    rng = np.random.default_rng(BOOT_SEED)
    diffs = []
    for _ in range(BOOT_DRAWS):
        draw = [l for k in rng.integers(0, len(syms), size=len(syms)) for l in by[syms[int(k)]]]
        if not draw:
            out["n_undefined"] += 1
            continue
        diffs.append(_mean([l["cand"][bp][pid]["ret"] for l in draw]) - _mean([l["base"][bp]["ret"] for l in draw]))
    out["n_finite"] = len(diffs)
    if len(diffs) >= BOOT_MIN_FINITE:
        lo, hi = np.quantile(np.array(diffs), [0.05, 0.95], method="linear")
        out["interval"] = [float(lo), float(hi)]
    return out


def diagnostic_halves(lots):
    """Entry-time median split of the test cohort; entries at the median go to the later half. Diagnostic only."""
    ts = sorted(l["entry_ts"] for l in lots)
    med = ts[len(ts) // 2]
    return [l for l in lots if l["entry_ts"] < med], [l for l in lots if l["entry_ts"] >= med]
