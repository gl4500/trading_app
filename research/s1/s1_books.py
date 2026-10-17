"""S1-QUANTITY / S1-SOLD (§7–8). Operational quantity book (app write-off rule at each SELL) for internal
consistency; economic FIFO = pinned E1 core baseline_lots, unchanged; sold events per the registered FIFO-lot
convention (first SELL allocation leaving the lot < 0.001, absorbing). Quantities are exact Fractions."""
import math
from fractions import Fraction

import s1_common as c

OP_OVERSELL_TOL = 1e-6          # equals e1_sim QTY_TOL (the economic book's oversell tolerance)


class BookError(Exception):
    pass


def _positive(v, field: str, tid) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise BookError(f"trade {tid}: {field} is not a number: {v!r}")
    if not (math.isfinite(f) and f > 0):
        raise BookError(f"trade {tid}: {field} must be finite and > 0, got {v!r}")
    return f


def rows(trades) -> list:
    out = []
    for t in trades:
        tid = t["id"]
        if t["action"] not in ("BUY", "SELL"):
            raise BookError(f"trade {tid}: unknown action {t['action']!r}")
        out.append({"id": tid, "symbol": t["symbol"], "action": t["action"],
                    "shares": _positive(t["shares"], "shares", tid),
                    "price": _positive(t["price"], "price", tid), "ts": c.aware(t["ts"])})
    return sorted(out, key=lambda r: (r["ts"], r["id"]))


def operational_replay(trades) -> dict:
    """Per symbol: BUY adds; SELL subtracts. A remainder in (0, SOLD_LT) is written off (positive entries only).
    A SELL beyond the position by more than OP_OVERSELL_TOL is an anomaly; the position is set to 0."""
    sim = c.sim()
    tol, lt = sim.x(OP_OVERSELL_TOL), sim.x(c.SOLD_LT)
    qty, writeoffs, anomalies = {}, [], []
    for r in rows(trades):
        s = r["symbol"]
        if r["action"] == "BUY":
            qty[s] = qty.get(s, Fraction(0)) + sim.x(r["shares"])
            continue
        q = qty.get(s, Fraction(0)) - sim.x(r["shares"])
        if q < -tol:
            anomalies.append({"id": r["id"], "symbol": s, "qty": float(q)})
            q = Fraction(0)
        elif q < lt:
            if q > 0:
                writeoffs.append({"id": r["id"], "symbol": s, "qty": float(q)})
            q = Fraction(0)
        qty[s] = q
    return {"qty": {s: float(q) for s, q in qty.items() if q != 0}, "writeoffs": writeoffs, "anomalies": anomalies}


def consistency(trades, portfolios) -> dict:
    op = operational_replay(trades)
    rep = op["qty"]
    diffs = [{"symbol": s, "replay": rep.get(s, 0.0), "portfolio": float(portfolios.get(s, 0.0))}
             for s in sorted(set(rep) | set(portfolios))
             if abs(rep.get(s, 0.0) - float(portfolios.get(s, 0.0))) > c.CONSIST_TOL]
    return {"consistent": not diffs and not op["anomalies"], "diffs": diffs, "anomalies": op["anomalies"]}


def _economic(rs, endpoint, orphans) -> list:
    try:
        return c.sim().baseline_lots(rs, endpoint=endpoint, splits=[], orphans=orphans)
    except ValueError as e:
        raise BookError(str(e))


def economic_lots(trades, endpoint) -> list:
    orphans = []
    lots = _economic(rows(trades), endpoint, orphans)
    if orphans:
        raise BookError(f"orphan SELL(s) with no open lot: {[o['id'] for o in orphans]}")
    return lots


def sold_events(trades) -> dict:
    """Prefix replay of the economic FIFO: at each SELL, a lot that received an allocation from THIS SELL and is
    left with < SOLD_LT is fully sold (first time only). Engine errors and orphan SELLs raise BookError.
    Task 11 (controller-added), I-3: FIFO is per symbol (splits=[]), so each SELL replays only the prefix rows of ITS
    OWN symbol - the same lots, fills and errors as the whole prefix (Hypothesis-checked against the old whole-prefix
    replay in s1_tests/test_s1_task11.py), about #symbols times less work."""
    rs, events, prev_fills, by_symbol = rows(trades), {}, {}, {}
    limit = c.sim().x(c.SOLD_LT)
    for r in rs:
        prefix = by_symbol.setdefault(r["symbol"], [])
        prefix.append(r)
        if r["action"] != "SELL":
            continue
        orphans = []
        lots = _economic(prefix, r["ts"], orphans)
        if orphans:
            raise BookError(f"orphan SELL(s) with no open lot: {[o['id'] for o in orphans]}")
        for l in lots:
            n = len(l["fills"])
            if n > prev_fills.get(l["id"], 0) and l["rem_qty"] < limit and l["id"] not in events:
                events[l["id"]] = {"sold_at": r["ts"].isoformat(), "sell_id": r["id"]}
            prev_fills[l["id"]] = n
    return events


def held_symbols(rows_before_start, start) -> set:
    """Task 11 (controller-added), I-4: symbols held at START by the pre-START rows - an open economic-FIFO lot (dust
    residuals included) or an operational holding (the key set of s1_run._carry_in's opening inventory)."""
    held = {l["symbol"] for l in economic_lots(rows_before_start, start) if l["rem_qty"] > 0}
    return held | {s for s, q in operational_replay(rows_before_start)["qty"].items() if q > 0}


def bridge(trades, endpoint) -> dict:
    op = operational_replay(trades)
    lots = economic_lots(trades, endpoint)
    out = {}
    for w in op["writeoffs"]:
        out.setdefault(w["symbol"], {"writeoff": 0.0, "economic_residual": 0.0})["writeoff"] += w["qty"]
    for l in lots:
        if l["rem_qty"] > 0:
            out.setdefault(l["symbol"], {"writeoff": 0.0, "economic_residual": 0.0})["economic_residual"] += \
                float(l["rem_qty"])
    return out
