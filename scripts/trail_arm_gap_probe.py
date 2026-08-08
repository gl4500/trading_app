"""
Trail-arm-gap provisional-stop probe (ledger Iteration 16 candidate, H18).

READ-ONLY against `backend/trading.db` + the offline `backend/data/history/*.parquet`
price-snapshot cache. No network, no writes, no live change.

Context (from Iteration 15, H16): HistoricalTrendsAgent makes 100% of its P&L in the exit
layer. The entire loss column is the HARD STOP -8% branch (108 exits, -$56,474), and every
one of those is an "unprotected gap" trade: a position whose peak unrealized PnL never
reached TRAIL_ARM_USD ($100), so the trailing stop never armed and nothing sat between entry
and -8%. The trail branch, by contrast, is +$70,425 at 90.6% win.

H18 (this probe): a *provisional* stop, tighter than -8% and active ONLY while
peak_uPnL < TRAIL_ARM_USD, cuts those losses shorter. The risk is that it also stops out
positions that dipped and would have recovered to arm the trail and win. This probe measures
the trade-off honestly by replaying every round trip against the actual observed price path.

Method
------
- FIFO-pair each SELL to its opening BUY (per symbol) -> round trips with entry/exit price,
  shares, timestamps, realized pnl, and the exit branch that actually fired.
- For each round trip, pull the symbol's snapshot price series (the same cadence the live
  agent observed) strictly between entry and exit, and replay uPnL = (price-entry)*shares.
- Candidate rule, for a threshold p%: walk the path; track running peak uPnL. The moment
  peak uPnL >= TRAIL_ARM_USD, the provisional stop DISENGAGES for the rest of that trade
  (the position armed; real trail/hard-stop logic owns it -> keep the actual realized pnl).
  While still un-armed, if uPnL <= -p% * entry_notional, exit provisionally at that observed
  price; counterfactual pnl = that uPnL.
- Trades with no usable path in the window are left at their actual pnl (unmodeled), and
  counted separately so coverage is transparent.

Resolution note: we only ever act on prices the agent actually observed (~8 snapshots/trading
day in the live window), so a provisional fill is always a real, achievable price -- never an
interpolated intrabar level. Same faithfulness the live -8% stop had.

Pre-registered non-loosenable falsifier (H18 SUPPORTED only if the single best threshold
clears ALL THREE):
  1. net realized improvement >= +$8,000 over the sample
  2. loss_saved > winner_damage
  3. top-1 symbol contributes < 50% of the net gain
No threshold clearing all three => REJECTED; thresholds are NOT to be loosened afterward.

Usage:
    PYTHONPATH=../site-packages ../runtime/python/python.exe scripts/trail_arm_gap_probe.py
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict, deque
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "backend" / "trading.db"
HISTORY_DIR = ROOT / "backend" / "data" / "history"

TRAIL_ARM_USD = 100.0          # matches BaseAgent TRAIL_ARM_USD; trail arms after +$100 peak uPnL
HARD_STOP_PCT = 0.08           # existing risk-manager hard stop, for reference
THRESHOLDS = (0.02, 0.03, 0.04, 0.05, 0.06)   # provisional price-stop candidates to sweep
TIME_STOPS = (2, 3, 5, 7, 10, 15)             # provisional time-stop candidates (days), un-armed

AGENT = "HistoricalTrendsAgent"


# --------------------------------------------------------------------------- data


def load_trades(db_path: Path, agent: str) -> list[tuple]:
    """(symbol, action, ts, price, shares, reasoning, pnl), oldest first. Read-only."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return list(con.execute(
            "SELECT t.symbol, t.action, t.timestamp, t.price, t.shares, "
            "       COALESCE(t.reasoning,''), COALESCE(t.pnl,0) "
            "FROM trades t JOIN agents a ON a.id = t.agent_id "
            "WHERE a.name = ? ORDER BY t.timestamp, t.id",
            (agent,),
        ))
    finally:
        con.close()


def exit_branch(reason: str) -> str:
    text = reason.lower()
    if "trail" in text:
        return "TRAIL"
    if "hard stop" in text:
        return "HARD_STOP"
    if "bayes early exit" in text:
        return "BAYES"
    if "sell:" in text and "composite=" in text:
        return "OWN_SELL"
    return "OTHER"


_price_cache: dict[str, Optional[pd.DataFrame]] = {}


def price_series(symbol: str) -> Optional[pd.DataFrame]:
    """DataFrame indexed by tz-naive UTC datetime with a single 'price' column, sorted."""
    if symbol not in _price_cache:
        path = HISTORY_DIR / f"{symbol}.parquet"
        if not path.exists():
            _price_cache[symbol] = None
        else:
            df = pd.read_parquet(path, columns=["snapshot_ts", "price"]).dropna(subset=["price"])
            df = df.assign(dt=pd.to_datetime(df["snapshot_ts"], unit="s")).sort_values("dt")
            _price_cache[symbol] = df.set_index("dt")[["price"]]
    return _price_cache[symbol]


def path_between(symbol: str, start: str, end: str) -> list[float]:
    """Observed prices strictly after entry and up to exit (inclusive of exit instant)."""
    df = price_series(symbol)
    if df is None:
        return []
    lo = pd.to_datetime(start).tz_localize(None)
    hi = pd.to_datetime(end).tz_localize(None)
    window = df.loc[(df.index > lo) & (df.index <= hi), "price"]
    return [float(p) for p in window.to_list()]


def timed_path_between(symbol: str, start: str, end: str) -> list[tuple[float, float]]:
    """(elapsed_days_since_entry, price) for observed snapshots in the hold window."""
    df = price_series(symbol)
    if df is None:
        return []
    lo = pd.to_datetime(start).tz_localize(None)
    hi = pd.to_datetime(end).tz_localize(None)
    window = df.loc[(df.index > lo) & (df.index <= hi), "price"]
    return [((idx - lo).total_seconds() / 86400.0, float(p)) for idx, p in window.items()]


# --------------------------------------------------------------------------- pairing


class RoundTrip:
    __slots__ = ("symbol", "entry_ts", "entry_px", "shares",
                 "exit_ts", "exit_px", "pnl", "branch")

    def __init__(self, symbol, entry_ts, entry_px, shares,
                 exit_ts, exit_px, pnl, branch):
        self.symbol = symbol
        self.entry_ts = entry_ts
        self.entry_px = entry_px
        self.shares = shares
        self.exit_ts = exit_ts
        self.exit_px = exit_px
        self.pnl = pnl
        self.branch = branch


def pair_round_trips(trades: list[tuple]) -> list[RoundTrip]:
    open_lots: dict[str, deque] = defaultdict(deque)
    out: list[RoundTrip] = []
    for symbol, action, ts, price, shares, reason, pnl in trades:
        if action == "BUY":
            open_lots[symbol].append((ts, price, shares))
        elif action == "SELL":
            if open_lots[symbol]:
                e_ts, e_px, e_sh = open_lots[symbol].popleft()
            else:
                e_ts, e_px, e_sh = ("", price, shares)
            out.append(RoundTrip(symbol, e_ts, e_px, e_sh, ts, price, pnl,
                                 exit_branch(reason)))
    return out


# --------------------------------------------------------------------------- simulate


def counterfactual_pnl(rt: RoundTrip, threshold: float) -> tuple[float, bool, bool]:
    """
    Return (cf_pnl, modeled, triggered).

    modeled   = we had a usable price path and evaluated the rule.
    triggered = the provisional stop fired (position exited early while un-armed).
    If not modeled, cf_pnl == actual pnl (rule abstains).
    """
    notional = abs(rt.entry_px * rt.shares)
    if notional == 0:
        return rt.pnl, False, False
    path = path_between(rt.symbol, rt.entry_ts, rt.exit_ts)
    if len(path) < 2:
        return rt.pnl, False, False

    stop_upnl = -threshold * notional
    peak = 0.0
    for px in path:
        upnl = (px - rt.entry_px) * rt.shares
        peak = max(peak, upnl)
        if peak >= TRAIL_ARM_USD:
            return rt.pnl, True, False          # armed -> real logic owns it
        if upnl <= stop_upnl:
            return upnl, True, True              # provisional stop fires at observed price
    return rt.pnl, True, False                   # never armed, never breached -> unchanged


def counterfactual_timestop(rt: RoundTrip, max_days: float) -> tuple[float, bool, bool]:
    """
    Time-stop variant: while un-armed (peak uPnL < TRAIL_ARM_USD), if the position has been
    held >= max_days, exit at the current observed price. Disengages once armed.
    Returns (cf_pnl, modeled, triggered).
    """
    if abs(rt.entry_px * rt.shares) == 0:
        return rt.pnl, False, False
    path = timed_path_between(rt.symbol, rt.entry_ts, rt.exit_ts)
    if len(path) < 2:
        return rt.pnl, False, False

    peak = 0.0
    for elapsed, px in path:
        upnl = (px - rt.entry_px) * rt.shares
        peak = max(peak, upnl)
        if peak >= TRAIL_ARM_USD:
            return rt.pnl, True, False           # armed in time -> real logic owns it
        if elapsed >= max_days:
            return upnl, True, True               # stale + un-armed -> cut at observed price
    return rt.pnl, True, False


def _sweep(rts, param_label, params, fn, fmt):
    print(f"\n{param_label:>5}{'net Δ':>13}{'loss_saved':>13}{'winner_dmg':>13}"
          f"{'n_fired':>9}{'modeled':>9}{'top1 sym':>16}")
    results = []
    for p in params:
        net = loss_saved = winner_dmg = 0.0
        n_fired = n_modeled = 0
        per_sym: dict[str, float] = defaultdict(float)
        for rt in rts:
            cf, modeled, triggered = fn(rt, p)
            n_modeled += modeled
            delta = cf - rt.pnl
            net += delta
            per_sym[rt.symbol] += delta
            if triggered:
                n_fired += 1
                if delta > 0:
                    loss_saved += delta
                elif delta < 0:
                    winner_dmg += -delta
        top_sym, top_val = (max(per_sym.items(), key=lambda kv: abs(kv[1]))
                            if per_sym else ("-", 0))
        results.append((p, net, loss_saved, winner_dmg, n_fired, n_modeled, top_sym, top_val))
        print(f"{fmt(p):>5}{net:>13,.0f}{loss_saved:>13,.0f}{winner_dmg:>13,.0f}"
              f"{n_fired:>9}{n_modeled:>9}{top_sym:>10}{top_val:>+7,.0f}")
    return results


def _verdict(label, results):
    print(f"\n--- {label}: falsifier (>= +$8,000 net; loss_saved > winner_dmg; "
          "top-1 sym < 50% of net) ---")
    best = max(results, key=lambda r: r[1])
    p, net, loss_saved, winner_dmg, n_fired, n_modeled, top_sym, top_val = best
    c1 = net >= 8000
    c2 = loss_saved > winner_dmg
    c3 = (abs(top_val) < 0.5 * net) if net > 0 else False
    print(f"best = {p}   net Δ = {net:+,.0f}")
    print(f"   [{'PASS' if c1 else 'FAIL'}] materiality  net {net:+,.0f} >= +8,000")
    print(f"   [{'PASS' if c2 else 'FAIL'}] trade-off     loss_saved {loss_saved:,.0f} "
          f"> winner_dmg {winner_dmg:,.0f}")
    if net > 0:
        print(f"   [{'PASS' if c3 else 'FAIL'}] robustness    top-1 {top_sym} {top_val:+,.0f} "
              f"< 50% of net ({0.5 * net:,.0f})")
    else:
        print(f"   [FAIL] robustness    net not positive")
    verdict = "SUPPORTED" if (c1 and c2 and c3) else "REJECTED"
    print(f"   VERDICT: {label} {verdict}")
    return verdict


def run() -> None:
    trades = load_trades(DB_PATH, AGENT)
    rts = pair_round_trips(trades)
    actual_total = sum(rt.pnl for rt in rts)

    # ---- harness validation: reproduce the published attribution totals ----
    by_branch: dict[str, float] = defaultdict(float)
    for rt in rts:
        by_branch[rt.branch] += rt.pnl
    print("=" * 74)
    print(f"{AGENT}: {len(rts)} round trips   actual realized {actual_total:+,.2f}")
    print("exit-branch totals (must match ledger iter-15 H16):")
    for b in ("TRAIL", "HARD_STOP", "BAYES", "OWN_SELL", "OTHER"):
        if b in by_branch:
            n = sum(1 for rt in rts if rt.branch == b)
            print(f"   {b:<10} n={n:<4} {by_branch[b]:>13,.2f}")
    print("=" * 74)

    # ---- variant A: provisional PRICE stop while un-armed ----
    price_results = _sweep(rts, "thr", THRESHOLDS, counterfactual_pnl, lambda p: f"{p:.0%}")
    v_price = _verdict("H18a price-stop", price_results)

    # ---- variant B: provisional TIME stop while un-armed ----
    time_results = _sweep(rts, "days", TIME_STOPS, counterfactual_timestop, lambda p: f"{p:g}d")
    v_time = _verdict("H18b time-stop", time_results)

    print("\n" + "=" * 74)
    print(f"BUILD #1 (trail-arm gap): price-stop {v_price}, time-stop {v_time}")
    print("=" * 74)


if __name__ == "__main__":
    run()
