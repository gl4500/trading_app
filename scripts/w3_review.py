"""
W3 ensemble daily check-in — paste-ready review script.

Reads:
  - backend/logs/live.log               -> [W3_BLEND] activity
  - backend/data/models/signal_xgb.json.meta.json    -> XGB mean_wfe / mean_ic
  - backend/data/models/signal_w3_pergroup.pt        -> W3 metrics (if present)
  - backend/trading.db                  -> XGBReasoningAgent trades since W3 went live

Produces a single-page summary suitable for end-of-day review.
Read-only — never touches model files or trades.

Usage:
    runtime/python/python.exe scripts/w3_review.py
    (or double-click scripts/w3_review.bat)

Optional args:
    --since YYYY-MM-DD   only count entries from this date onward
    --baseline-pnl FLOAT pre-W3 XGBReasoningAgent realized P&L baseline for delta
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from statistics import mean, stdev

# The summary uses box-drawing glyphs; a Windows cp1252 console (and the .bat
# double-click path) can't encode them and crashes on the first print(). Force
# UTF-8 on stdout/stderr so output is identical whether run in a console or piped.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

ROOT       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND    = os.path.join(ROOT, "backend")
LIVE_LOG   = os.path.join(BACKEND, "logs", "live.log")
XGB_META   = os.path.join(BACKEND, "data", "models", "signal_xgb.json.meta.json")
W3_PT      = os.path.join(BACKEND, "data", "models", "signal_w3_pergroup.pt")
TRADES_DB  = os.path.join(BACKEND, "trading.db")

# W3 first landed (commit 395c0c2)
W3_LANDED_TS = "2026-05-23"

LINE_RE = re.compile(
    r'^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[INFO\] agents\.xgb_reasoning_agent: '
    r'\[W3_BLEND\] (?P<symbol>\S+) '
    r'xgb=(?P<xgb>[+-][\d.]+) w3=(?P<w3>[+-][\d.]+) blend=(?P<blend>[+-][\d.]+) '
    r'w=(?P<w>[\d.]+) dir=(?P<dir>\w+) flip=(?P<flip>True|False) '
    r'xgb_wfe=(?P<xwfe>\S+) w3_wfe=(?P<wwfe>\S+)'
)


# ── Parsers ──────────────────────────────────────────────────────────────

def parse_log(since: str | None) -> list[dict]:
    if not os.path.exists(LIVE_LOG):
        return []
    rows = []
    cutoff = f"{since} 00:00:00" if since else "0000-00-00 00:00:00"
    with open(LIVE_LOG, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            m = LINE_RE.match(line)
            if not m:
                continue
            if m["ts"] < cutoff:
                continue
            rows.append({
                "ts":     m["ts"],
                "date":   m["ts"][:10],
                "symbol": m["symbol"],
                "xgb":    float(m["xgb"]),
                "w3":     float(m["w3"]),
                "blend":  float(m["blend"]),
                "w":      float(m["w"]),
                "dir":    m["dir"],
                "flip":   m["flip"] == "True",
                "xgb_wfe": None if m["xwfe"] == "None" else float(m["xwfe"]),
                "w3_wfe":  None if m["wwfe"] == "None" else float(m["wwfe"]),
            })
    return rows


def read_xgb_meta() -> dict | None:
    if not os.path.exists(XGB_META):
        return None
    try:
        with open(XGB_META, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def read_w3_meta() -> dict | None:
    """W3 metrics are embedded in the .pt blob. Use torch to read."""
    if not os.path.exists(W3_PT):
        return None
    try:
        sys.path.insert(0, os.path.join(ROOT, "site-packages"))
        import torch  # noqa
        blob = torch.load(W3_PT, map_location="cpu", weights_only=False)  # nosec B614 - local file written by SignalW3.save()
        return {
            "mean_wfe":  blob.get("mean_wfe"),
            "mean_ic":   blob.get("mean_ic"),
            "ir":        blob.get("ir"),
            "train_ts":  blob.get("train_ts"),
            "fold_metrics": blob.get("fold_metrics", []),
        }
    except Exception as exc:
        return {"_error": str(exc)}


def read_xgb_agent_trades(since: str) -> list[dict]:
    """Pull XGBReasoningAgent trades since the W3 went live."""
    if not os.path.exists(TRADES_DB):
        return []
    try:
        conn = sqlite3.connect(f"file:{TRADES_DB}?mode=ro", uri=True, timeout=2.0)
        cur = conn.cursor()
        cur.execute("""
            SELECT t.timestamp, t.symbol, t.action, t.shares, t.price, t.pnl, a.name AS agent_name
            FROM trades t
            JOIN agents a ON a.id = t.agent_id
            WHERE a.name = 'XGBReasoningAgent'
              AND DATE(t.timestamp) >= DATE(?)
            ORDER BY t.timestamp ASC
        """, (since,))
        rows = [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]
        conn.close()
        return rows
    except sqlite3.Error as exc:
        return [{"_error": str(exc)}]


# ── Summarizers ──────────────────────────────────────────────────────────

def summarize_log(rows: list[dict]) -> None:
    if not rows:
        print("  no [W3_BLEND] entries in live.log yet (cycle hasn't fired with W3 enabled)")
        return

    print(f"  total blend fires        : {len(rows):>6}")
    flips = [r for r in rows if r["flip"]]
    print(f"  action flips vs xgb-only : {len(flips):>6}  ({len(flips)/len(rows)*100:.1f}%)")

    # Direction distribution
    dirs = Counter(r["dir"] for r in rows)
    print(f"  direction split (final)  : "
          + "  ".join(f"{d}={dirs.get(d, 0)}" for d in ("bull", "neutral", "bear")))

    # Pred magnitudes
    xgb_mags = [r["xgb"]   for r in rows]
    w3_mags  = [r["w3"]    for r in rows]
    bl_mags  = [r["blend"] for r in rows]
    def fmt(xs):
        if len(xs) < 2:
            return f"mean={mean(xs):+.4f}  (n=1, no std)"
        return f"mean={mean(xs):+.4f}  std={stdev(xs):.4f}  range=[{min(xs):+.4f},{max(xs):+.4f}]"
    print(f"  xgb pred                 : {fmt(xgb_mags)}")
    print(f"  w3  pred                 : {fmt(w3_mags)}")
    print(f"  blend                    : {fmt(bl_mags)}")

    # Daily activity
    by_day = defaultdict(list)
    for r in rows:
        by_day[r["date"]].append(r)
    print(f"  daily activity           :")
    for day in sorted(by_day.keys())[-7:]:
        d = by_day[day]
        f = sum(1 for r in d if r["flip"])
        print(f"    {day}  fires={len(d):>4}  flips={f:>3}  symbols={len({r['symbol'] for r in d}):>3}")

    # Per-symbol top-5 by flip count
    by_sym_flips = Counter(r["symbol"] for r in rows if r["flip"])
    if by_sym_flips:
        print(f"  symbols most affected    :")
        for sym, n in by_sym_flips.most_common(5):
            print(f"    {sym:6s}  {n:>3} flips")


def summarize_wfe_drift(rows: list[dict], xgb_meta: dict | None, w3_meta: dict | None) -> None:
    print()
    print("── WFE drift ─────────────────────────────────")
    # Current values from meta files (post-retrain)
    if xgb_meta:
        print(f"  current XGB meta_wfe     : {xgb_meta.get('mean_wfe'):+.4f}  "
              f"({xgb_meta.get('wfe_status', 'n/a')})")
        print(f"  current XGB mean_ic      : {xgb_meta.get('mean_ic'):+.4f}")
    else:
        print("  XGB meta file not found")
    if w3_meta and not w3_meta.get("_error"):
        wfe = w3_meta.get("mean_wfe")
        ic  = w3_meta.get("mean_ic")
        print(f"  current W3  mean_wfe     : "
              + (f"{wfe:+.4f}" if wfe is not None else "None (not yet retrained on live data)"))
        print(f"  current W3  mean_ic      : "
              + (f"{ic:+.4f}"  if ic  is not None else "None"))
    elif w3_meta and w3_meta.get("_error"):
        print(f"  W3 meta read error: {w3_meta['_error']}")
    else:
        print("  W3 .pt file not found")

    # Drift across the live log
    wfe_pairs = [(r["ts"], r["xgb_wfe"], r["w3_wfe"]) for r in rows
                 if r["xgb_wfe"] is not None or r["w3_wfe"] is not None]
    if wfe_pairs:
        first_ts, fx, fw = wfe_pairs[0]
        last_ts,  lx, lw = wfe_pairs[-1]
        print(f"  WFE seen in log          : first {first_ts} -> last {last_ts}")
        if fx is not None and lx is not None:
            print(f"    xgb_wfe drift          : {fx:+.4f} -> {lx:+.4f}  ({(lx-fx):+.4f})")
        if fw is not None and lw is not None:
            print(f"    w3_wfe drift           : {fw:+.4f} -> {lw:+.4f}  ({(lw-fw):+.4f})")


def summarize_trades(trades: list[dict], baseline_pnl: float | None) -> None:
    print()
    print("── XGBReasoningAgent trades (since 2026-05-23) ─")
    if not trades:
        print("  no trades from XGBReasoningAgent since W3 landed")
        return
    if trades[0].get("_error"):
        print(f"  trades.db read error: {trades[0]['_error']}")
        return

    buys  = [t for t in trades if t["action"] == "BUY"]
    sells = [t for t in trades if t["action"] == "SELL"]
    print(f"  trades                   : {len(trades):>4}  ({len(buys)} BUYs, {len(sells)} SELLs)")
    by_sym = Counter(t["symbol"] for t in trades)
    print(f"  unique symbols           : {len(by_sym):>4}")
    if buys:
        gross_buy  = sum(t["shares"] * t["price"] for t in buys)
        print(f"  gross BUY notional       : ${gross_buy:>10,.0f}")
    if sells:
        gross_sell = sum(t["shares"] * t["price"] for t in sells)
        print(f"  gross SELL notional      : ${gross_sell:>10,.0f}")
    realized = sum(t.get("pnl") or 0 for t in trades)
    print(f"  realized P&L (since W3)  : ${realized:>+10,.2f}")
    if baseline_pnl is not None:
        delta = realized - baseline_pnl
        print(f"  vs baseline ${baseline_pnl:+,.2f}     : ${delta:>+10,.2f}  ({delta/abs(baseline_pnl)*100:+.1f}% vs baseline)")


# ── Entry ────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", default=W3_LANDED_TS,
                    help=f"only count entries from this YYYY-MM-DD onward (default: {W3_LANDED_TS})")
    ap.add_argument("--baseline-pnl", type=float, default=None,
                    help="pre-W3 XGBReasoningAgent realized P&L baseline for delta computation")
    args = ap.parse_args()

    print(f"W3 ensemble review  ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    print(f"  filter             : --since {args.since}")
    print(f"  live.log           : {LIVE_LOG}")
    print(f"  exists             : {os.path.exists(LIVE_LOG)}")
    print()
    print("── blend activity ────────────────────────────")

    rows = parse_log(args.since)
    summarize_log(rows)

    xgb_meta = read_xgb_meta()
    w3_meta  = read_w3_meta()
    summarize_wfe_drift(rows, xgb_meta, w3_meta)

    trades = read_xgb_agent_trades(args.since)
    summarize_trades(trades, args.baseline_pnl)

    print()
    print("──── done ────")
    return 0


if __name__ == "__main__":
    sys.exit(main())
