"""CLI for the re-selection backtest harness (ledger Iteration 17).

Runs one or more config variants of a rule agent over historical bars and writes
a comparison report. Does not modify production state.

Example:
    PYTHONPATH='site-packages;backend' runtime/python/python.exe scripts/reselection_backtest.py \\
      --universe live --start 2026-03-30 --end 2026-07-31 \\
      --variant "baseline=HIST_SEASONAL_WEIGHT=0.20" \\
      --variant "no_seasonal=HIST_SEASONAL_WEIGHT=0.0"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

from agents.historical_trends_agent import HistoricalTrendsAgent
from backtest.bars_provider import BarsProvider
from backtest.reselection import run_backtest, BacktestResult

_ROOT = Path(__file__).resolve().parent.parent
_AGENTS = {"HistoricalTrendsAgent": HistoricalTrendsAgent}


def _parse_variant(spec: str):
    name, _, rest = spec.partition("=")
    overrides: Dict[str, float] = {}
    for pair in rest.split(","):
        k, _, v = pair.partition("=")
        overrides[k.strip()] = float(v)
    return name.strip(), overrides


def _live_universe(db: Path, agent_name: str) -> List[str]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return [r[0] for r in con.execute(
            "SELECT DISTINCT t.symbol FROM trades t JOIN agents a ON a.id=t.agent_id "
            "WHERE a.name=?", (agent_name,))]
    finally:
        con.close()


def _max_drawdown(curve) -> float:
    peak = float("-inf"); mdd = 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    return mdd


def _iso(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--agent", default="HistoricalTrendsAgent", choices=list(_AGENTS))
    p.add_argument("--history", default=str(_ROOT / "backend" / "data" / "history"))
    p.add_argument("--logs", default=str(_ROOT / "scripts" / "logs"))
    p.add_argument("--db", default=str(_ROOT / "backend" / "trading.db"))
    p.add_argument("--universe", required=True, help='"live" or a comma-separated symbol list')
    p.add_argument("--start", required=True, type=_iso)
    p.add_argument("--end", required=True, type=_iso)
    p.add_argument("--variant", action="append", required=True, help='"name=KEY=VAL,KEY=VAL"')
    p.add_argument("--trailing-bars", type=int, default=504)
    args = p.parse_args(argv)

    universe = (_live_universe(Path(args.db), args.agent)
                if args.universe == "live" else
                [s.strip() for s in args.universe.split(",") if s.strip()])
    bars = BarsProvider(Path(args.history), trailing_bars=args.trailing_bars)
    factory = _AGENTS[args.agent]

    results: Dict[str, BacktestResult] = {}
    for spec in args.variant:
        name, overrides = _parse_variant(spec)
        results[name] = asyncio.run(run_backtest(
            factory, universe=universe, start=args.start, end=args.end,
            bars=bars, config_overrides=overrides))

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    logs = Path(args.logs); logs.mkdir(parents=True, exist_ok=True)
    md = logs / f"reselection_{ts}.md"
    jl = logs / f"reselection_{ts}.jsonl"

    lines = [f"# Re-selection backtest {ts}",
             f"agent={args.agent} universe={len(universe)} syms  {args.start}->{args.end}", "",
             "| variant | realized PnL | final equity | trades | max DD |",
             "|---|---|---|---|---|"]
    for name, r in results.items():
        lines.append(f"| {name} | {r.realized_pnl:,.0f} | {r.final_equity:,.0f} | "
                     f"{len(r.trades)} | {_max_drawdown(r.equity_curve):.1%} |")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with jl.open("w", encoding="utf-8") as f:
        for name, r in results.items():
            for t in r.trades:
                f.write(json.dumps({"variant": name, **t}) + "\n")

    print(f"wrote {md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
