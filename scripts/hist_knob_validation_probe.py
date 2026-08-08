"""
Validation probe for the two remaining live HistoricalTrendsAgent knobs (ledger Iteration 16,
H19/H20). READ-ONLY against `backend/trading.db`. No price replay needed — both effects are
entry/sizing-side and reconstructable from the recorded BUY reasoning (`composite=`, `seasonal
bias=`) plus the realized pnl of each FIFO-paired round trip.

Both knobs were shipped OFF (PR #93) then set LIVE in .env (HIST_CONFIDENCE_CAP=0.45,
HIST_SEASONAL_WEIGHT=0.0) without validation. This probe supplies the missing evidence.

H19 — HIST_CONFIDENCE_CAP=0.45 (sizing cap).
  Size scales with confidence = |composite|; the cap shrinks any position with |composite| > cap
  by the factor cap/|composite|. Entries and exits are unchanged, so realized pnl scales linearly:
  cf_pnl = pnl * cap/|c| for |c| > cap, else pnl. (Assumes linear sizing with no binding
  MAX_POSITION_SIZE clamp — the standard approximation; flagged as such.)
  Pre-registered: keeping the cap ON is justified only if net realized delta >= +$1,000 AND the
  top-1 symbol contributes < 50% of the net. Otherwise recommend reverting to 0.0.

H20 — HIST_SEASONAL_WEIGHT=0.0 (drop the inverted seasonal pillar).
  Dropping the pillar renormalises the composite: c_new = (c_old - w_seasonal * seasonal_bias) /
  (1 - w_seasonal), w_seasonal = 0.20. This changes which trades clear the +/-0.25 BUY threshold.
  BLIND SPOT: realized data only contains trades that WERE taken; entries that would NEWLY qualify
  without seasonal are unobservable. So this is reported as DIRECTIONAL evidence, not pass/fail:
    (a) correlation — bucket trades by the seasonal contribution (w*bias) vs outcome; if a more
        bullish seasonal push goes with worse average PnL, the pillar is inverted (supports zeroing);
    (b) removal-only counterfactual — of trades that fall below +0.25 without seasonal, what is the
        net pnl dropped, and how does resizing the survivors net out (new entries excluded).

Usage:
    PYTHONPATH=../site-packages ../runtime/python/python.exe scripts/hist_knob_validation_probe.py
"""
from __future__ import annotations

import re
import sqlite3
from collections import defaultdict, deque
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "backend" / "trading.db"

AGENT = "HistoricalTrendsAgent"
CONFIDENCE_CAP = 0.45          # live HIST_CONFIDENCE_CAP
SEASONAL_WEIGHT = 0.20         # default weight the pillar carried before HIST_SEASONAL_WEIGHT=0.0
BUY_THRESHOLD = 0.25           # composite must clear +0.25 to open a long


def load_trades(db_path: Path, agent: str) -> list[tuple]:
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


def _num(pattern: str, text: str) -> Optional[float]:
    m = re.search(pattern, text)
    return float(m.group(1)) if m else None


def pair_round_trips(trades: list[tuple]) -> list[dict]:
    """FIFO-pair SELLs to BUYs; carry the entry reasoning + realized pnl."""
    open_lots: dict[str, deque] = defaultdict(deque)
    out: list[dict] = []
    for symbol, action, ts, price, shares, reason, pnl in trades:
        if action == "BUY":
            open_lots[symbol].append(reason)
        elif action == "SELL":
            entry_reason = open_lots[symbol].popleft() if open_lots[symbol] else ""
            out.append({
                "symbol": symbol,
                "pnl": pnl,
                "composite": _num(r"composite=([+-]?\d+\.\d+)", entry_reason),
                "seasonal": _num(r"seasonal bias=([+-]?\d+\.\d+)", entry_reason),
            })
    return out


def h19_sizing_cap(rts: list[dict]) -> None:
    print("\n" + "=" * 74)
    print(f"H19 — HIST_CONFIDENCE_CAP = {CONFIDENCE_CAP} (sizing cap)")
    print("=" * 74)
    net = 0.0
    n_capped = 0
    per_sym: dict[str, float] = defaultdict(float)
    # display bands aligned to the iter-15 audit convention (inclusive-low) so they reconcile
    buckets = {"< +0.45 (untouched)": [0, 0.0], "[+0.45, +0.60)": [0, 0.0], ">= +0.60": [0, 0.0]}
    for rt in rts:
        c = rt["composite"]
        if c is None:
            continue
        ac = abs(c)
        # cap semantics: min(|c|, cap) -> only |c| STRICTLY above the cap is actually shrunk
        if ac > CONFIDENCE_CAP:
            cf = rt["pnl"] * (CONFIDENCE_CAP / ac)
            delta = cf - rt["pnl"]
            net += delta
            per_sym[rt["symbol"]] += delta
            n_capped += 1
        key = "< +0.45 (untouched)" if ac < 0.45 else ("[+0.45, +0.60)" if ac < 0.60 else ">= +0.60")
        buckets[key][0] += 1
        buckets[key][1] += rt["pnl"]
    print(f"{'composite band':<22}{'n':>6}{'actual PnL':>15}   (audit iter-15 for reference)")
    ref = {"[+0.45, +0.60)": "n=43  +844", ">= +0.60": "n=22  -691"}
    for k, (n, pnl) in buckets.items():
        print(f"{k:<22}{n:>6}{pnl:>15,.2f}   {ref.get(k, '')}")
    top_sym, top_val = (max(per_sym.items(), key=lambda kv: abs(kv[1])) if per_sym else ("-", 0.0))
    print(f"\n{n_capped} trades have |composite| > {CONFIDENCE_CAP} and are actually shrunk; "
          f"net realized Δ from capping = {net:+,.2f}")
    print(f"top-1 symbol by |Δ|: {top_sym} {top_val:+,.2f}")
    c1 = net >= 1000
    c2 = abs(top_val) < 0.5 * net if net > 0 else False
    print(f"   [{'PASS' if c1 else 'FAIL'}] materiality  net {net:+,.0f} >= +1,000")
    if net > 0:
        print(f"   [{'PASS' if c2 else 'FAIL'}] robustness    top-1 {top_val:+,.0f} < 50% of net")
    else:
        print(f"   [FAIL] robustness    net not positive")
    verdict = "KEEP ON (0.45)" if (c1 and c2) else "REVERT to 0.0"
    print(f"   VERDICT H19: {verdict}")


def h20_seasonal(rts: list[dict]) -> None:
    print("\n" + "=" * 74)
    print(f"H20 — HIST_SEASONAL_WEIGHT = 0.0 (drop pillar; was {SEASONAL_WEIGHT}) — DIRECTIONAL")
    print("=" * 74)
    usable = [rt for rt in rts if rt["composite"] is not None and rt["seasonal"] is not None]

    # (a) correlation: seasonal contribution (w*bias) vs outcome
    print("\n(a) seasonal contribution (0.20 x bias) vs outcome:")
    print(f"{'contribution band':<22}{'n':>6}{'win%':>8}{'total PnL':>14}{'avg':>10}")
    bands = [("bearish  <=-0.02", -1e9, -0.02), ("neutral -0.02..+0.02", -0.02, 0.02),
             ("bullish  >=+0.02", 0.02, 1e9)]
    for label, lo, hi in bands:
        grp = [rt for rt in usable if lo <= SEASONAL_WEIGHT * rt["seasonal"] < hi]
        if not grp:
            continue
        n = len(grp)
        pnl = sum(rt["pnl"] for rt in grp)
        wins = sum(1 for rt in grp if rt["pnl"] > 0)
        print(f"{label:<22}{n:>6}{100*wins/n:>7.1f}%{pnl:>14,.2f}{pnl/n:>10,.2f}")

    # (b) removal-only counterfactual
    dropped_n = 0
    dropped_pnl = 0.0
    for rt in usable:
        c_new = (rt["composite"] - SEASONAL_WEIGHT * rt["seasonal"]) / (1 - SEASONAL_WEIGHT)
        if c_new < BUY_THRESHOLD:      # would no longer qualify as a BUY
            dropped_n += 1
            dropped_pnl += rt["pnl"]
    print(f"\n(b) removal-only counterfactual (new entries NOT observable):")
    print(f"    without seasonal, {dropped_n} taken trades fall below +{BUY_THRESHOLD:.2f} and "
          f"would be dropped;")
    print(f"    net PnL of those dropped trades = {dropped_pnl:+,.2f} "
          f"({'dropping helps' if dropped_pnl < 0 else 'dropping removes net winners'})")
    print("    NOTE: cannot measure trades that would NEWLY qualify without seasonal -> directional only.")


def main() -> None:
    trades = load_trades(DB_PATH, AGENT)
    rts = pair_round_trips(trades)
    total = sum(rt["pnl"] for rt in rts)
    parsed = sum(1 for rt in rts if rt["composite"] is not None)
    print(f"{AGENT}: {len(rts)} round trips, realized {total:+,.2f}; "
          f"composite parsed on {parsed}/{len(rts)}")
    h19_sizing_cap(rts)
    h20_seasonal(rts)


if __name__ == "__main__":
    main()
