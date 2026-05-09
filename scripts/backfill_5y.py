"""
5-year historical backfill — populate per-symbol parquets with daily bars
including volume so the new HISTORICAL channels (option C) and the
hist_volume_pattern channel (#85) have real 5-year context for training.

Walks the symbol list (default = config.WATCHLIST + active watchlist pool;
override via --symbols), fetches daily Alpaca bars for the last `--days`
calendar days (default 1825 = ~5 years), and writes them to
backend/data/history/{SYMBOL}.parquet via the existing
backfill_signal_history pipeline.

Idempotent — backfill_signal_history checks for existing rows and only
adds NEW dates, so re-running the script doesn't duplicate data. Safe
to ctrl-C and resume.

What gets populated for historical rows:
  ✓ snapshot_ts, price, volume (from Alpaca bars)
  ✓ return_1d, return_5d, return_10d (computed from price series)
  ✓ rv_20d, rv_60d (computed from price series)
  ✗ analyst/earnings/alpaca/yahoo/congress/iv_rv/composite scores — set 0.0
    or NaN (live-source data; not recoverable historically without paid feeds)
  ✗ agent_consensus, agent_agreement, top_agent_correct — NaN (agents
    weren't running at those past timestamps)

Usage:
  cd backend
  ../runtime/python/python.exe ../scripts/backfill_5y.py
  ../runtime/python/python.exe ../scripts/backfill_5y.py --days 1825 --symbols AAPL,MSFT,SPY
  ../runtime/python/python.exe ../scripts/backfill_5y.py --watchlist
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from typing import List

_HERE    = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.join(os.path.dirname(_HERE), "backend")
_SITE    = os.path.join(os.path.dirname(_HERE), "site-packages")
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from config import config
from data.history_backfill import backfill_signal_history


def _resolve_symbols(args) -> List[str]:
    """--symbols=A,B,C overrides everything. Otherwise default to the
    union of:
      1. existing per-symbol parquet files in backend/data/history/
         (the system's "tracked universe" — symbols we've already been
         persisting signal history for; this is the 100+ symbol set)
      2. config.WATCHLIST (static default, often empty on fluid setups)
      3. watchlist_manager.get_active_watchlist() (dynamic active pool)
    Excludes any `__`-prefixed special filenames (e.g. __MACRO__).
    """
    if args.symbols:
        return [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    syms: List[str] = []

    # 1. Symbols with existing parquet files — the on-disk universe
    hist_dir = os.path.join(os.path.dirname(_HERE), "backend", "data", "history")
    if os.path.isdir(hist_dir):
        for fname in sorted(os.listdir(hist_dir)):
            if fname.endswith(".parquet") and not fname.startswith("__"):
                sym = fname[:-len(".parquet")].upper()
                if sym not in syms:
                    syms.append(sym)

    # 2. config.WATCHLIST static list (often empty on fluid setups)
    for s in config.WATCHLIST:
        if s not in syms:
            syms.append(s)

    # 3. Dynamic watchlist pool
    try:
        from data.watchlist_manager import watchlist_manager
        active = watchlist_manager.get_active_watchlist()
        for s in active:
            if s not in syms:
                syms.append(s)
    except Exception as exc:
        print(f"[warn] could not load active watchlist pool: {exc}", file=sys.stderr)

    return syms


async def _run(symbols: List[str], days: int) -> int:
    print(f"[backfill_5y] target: {len(symbols)} symbols × {days}d window")
    print(f"[backfill_5y] symbols: {', '.join(symbols[:20])}"
          + (f" ... (+{len(symbols) - 20} more)" if len(symbols) > 20 else ""))

    t0 = time.time()
    results = await backfill_signal_history(symbols, days=days)
    elapsed = time.time() - t0

    total_added = sum(results.values())
    populated = sum(1 for v in results.values() if v > 0)

    print()
    print("=" * 72)
    print(f"[backfill_5y] complete in {elapsed:.1f}s")
    print(f"[backfill_5y] symbols with new rows: {populated} / {len(symbols)}")
    print(f"[backfill_5y] total rows added: {total_added:,}")
    print("=" * 72)

    # Per-symbol summary (winners + losers)
    sorted_results = sorted(results.items(), key=lambda kv: -kv[1])
    print("\nTop 10 symbols by rows added:")
    for sym, n in sorted_results[:10]:
        print(f"  {sym:<8}  {n:>6} rows")
    zero_count = sum(1 for v in results.values() if v == 0)
    if zero_count:
        zero_syms = [s for s, v in results.items() if v == 0]
        print(f"\n{zero_count} symbols added 0 rows (already up-to-date or fetch failed):")
        print(f"  {', '.join(zero_syms[:30])}"
              + (" ..." if len(zero_syms) > 30 else ""))

    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="5-year historical backfill of per-symbol signal-history parquets.")
    p.add_argument("--days", type=int, default=1825,
                   help="Calendar days of history to fetch (default 1825 = ~5 years)")
    p.add_argument("--symbols", type=str, default="",
                   help="Comma-separated symbol list (overrides --watchlist)")
    p.add_argument("--watchlist", action="store_true",
                   help="Use config.WATCHLIST + active watchlist pool (default)")
    args = p.parse_args()

    symbols = _resolve_symbols(args)
    if not symbols:
        print("[error] no symbols resolved — check config.WATCHLIST or pass --symbols", file=sys.stderr)
        return 1

    return asyncio.run(_run(symbols, args.days))


if __name__ == "__main__":
    sys.exit(main())
