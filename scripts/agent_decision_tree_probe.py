"""
Decision-tree attribution probe (ledger Iteration 15, H16/H17).

READ-ONLY against `backend/trading.db`. Answers: for a given agent, which branch of its
decision tree actually produced the realized PnL — the agent's own entry/exit rules, or the
shared BaseAgent / risk-manager exits?

Emits four tables:
  1. exit-branch attribution   (H16 — which leaf closed the trade)
  2. entry composite vs outcome (H17 — is conviction correlated with result?)
  3. per-pillar attribution     (H17 — does each weighted pillar earn its weight?)
  4. monthly realized PnL split by exit branch

Entry-side buckets are FIFO-paired per symbol and are therefore approximate where a symbol
held overlapping lots. Exit-branch and monthly figures are exact (pnl is recorded on the SELL).

Usage:
    runtime\\python\\python.exe scripts/agent_decision_tree_probe.py --agent HistoricalTrendsAgent
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from collections import defaultdict, deque
from pathlib import Path
from typing import Callable, Iterable, Optional

DB_PATH = Path(__file__).resolve().parent.parent / "backend" / "trading.db"

Trade = tuple[str, str, str, str, float]  # symbol, action, timestamp, reasoning, pnl


def load_trades(db_path: Path, agent_name: str) -> list[Trade]:
    """Read one agent's trade ledger, oldest first. Never opens the DB for write."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return list(con.execute(
            "SELECT t.symbol, t.action, t.timestamp, COALESCE(t.reasoning, ''), COALESCE(t.pnl, 0) "
            "FROM trades t JOIN agents a ON a.id = t.agent_id "
            "WHERE a.name = ? ORDER BY t.timestamp, t.id",
            (agent_name,),
        ))
    finally:
        con.close()


def exit_branch(reason: str) -> str:
    """Map a SELL's reasoning text to the decision-tree leaf that fired."""
    text = reason.lower()
    if "trail" in text:
        return "TRAIL-STOP (BaseAgent)"
    if "hard stop" in text:
        return "HARD STOP -8% (risk mgr)"
    if "bayes early exit" in text:
        return "BAYES EARLY EXIT"
    if "sell:" in text and "composite=" in text:
        return "AGENT'S OWN SELL RULE"
    return "OTHER"


def composite_of(reason: str) -> Optional[float]:
    match = re.search(r"composite=([+-]?\d+\.\d+)", reason)
    return float(match.group(1)) if match else None


def channel_bucket(reason: str) -> Optional[str]:
    match = re.search(r"position=(-?\d+)%", reason)
    if match is None:
        return None
    pos = int(match.group(1))
    if pos < 25:
        return "a) <25% near period low"
    if pos < 50:
        return "b) 25-50%"
    if pos < 75:
        return "c) 50-75%"
    return "d) >75% near period high"


def alignment_bucket(reason: str) -> Optional[str]:
    match = re.search(r"alignment=(\d+)%", reason)
    return f"{int(match.group(1)):>3}% aligned" if match else None


def entry_month(_reason: str, timestamp: str) -> str:
    return timestamp[:7]


def pair_round_trips(trades: Iterable[Trade]) -> list[tuple[str, str, float]]:
    """FIFO-pair each SELL to its opening BUY. Returns (entry_reason, entry_ts, pnl)."""
    open_lots: dict[str, deque[tuple[str, str]]] = defaultdict(deque)
    paired: list[tuple[str, str, float]] = []
    for symbol, action, timestamp, reason, pnl in trades:
        if action == "BUY":
            open_lots[symbol].append((reason, timestamp))
        elif action == "SELL":
            entry = open_lots[symbol].popleft() if open_lots[symbol] else ("", "")
            paired.append((entry[0], entry[1], pnl))
    return paired


def print_table(title: str, rows: dict[str, list]) -> None:
    """rows: label -> [n, total_pnl, wins, losses]"""
    print(f"\n--- {title} ---")
    print(f"{'bucket':<32}{'n':>5}{'W':>5}{'L':>5}{'win%':>8}{'total PnL':>14}{'avg':>11}")
    for label, (n, pnl, wins, losses) in sorted(rows.items(), key=lambda kv: -kv[1][1]):
        print(f"{label:<32}{n:>5}{wins:>5}{losses:>5}{100 * wins / n:>7.1f}%{pnl:>14,.2f}{pnl / n:>11,.2f}")


def tally(items: Iterable[tuple[Optional[str], float]]) -> dict[str, list]:
    out: dict[str, list] = defaultdict(lambda: [0, 0.0, 0, 0])
    for label, pnl in items:
        if label is None:
            continue
        row = out[label]
        row[0] += 1
        row[1] += pnl
        row[2] += pnl > 0
        row[3] += pnl < 0
    return out


def composite_bucket(reason: str) -> Optional[str]:
    value = composite_of(reason)
    if value is None:
        return None
    for lo, hi in ((0.25, 0.35), (0.35, 0.45), (0.45, 0.60)):
        if lo <= value < hi:
            return f"+{lo:.2f} to +{hi:.2f}"
    return "+0.60 and up" if value >= 0.60 else f"below +0.25 ({value:+.2f})"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", default="HistoricalTrendsAgent")
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args()

    trades = load_trades(args.db, args.agent)
    if not trades:
        raise SystemExit(f"No trades found for agent {args.agent!r} in {args.db}")

    sells = [t for t in trades if t[1] == "SELL"]
    buys = [t for t in trades if t[1] == "BUY"]
    realized = sum(t[4] for t in sells)
    wins = sum(1 for t in sells if t[4] > 0)
    losses = sum(1 for t in sells if t[4] < 0)

    print("=" * 92)
    print(f"{args.agent}: {len(trades)} trades ({len(buys)} BUY / {len(sells)} SELL)")
    print(f"span {trades[0][2][:10]} -> {trades[-1][2][:10]}   realized PnL {realized:+,.2f}   "
          f"win rate {100 * wins / max(wins + losses, 1):.1f}% ({wins}W/{losses}L)")
    print("=" * 92)

    # 1. H16 — exit-branch attribution
    print_table("EXIT BRANCH (which leaf closed the trade)",
                tally((exit_branch(t[3]), t[4]) for t in sells))

    paired = pair_round_trips(trades)

    # 2 + 3. H17 — entry conviction and per-pillar attribution
    for title, fn in (
        ("ENTRY COMPOSITE vs OUTCOME", composite_bucket),
        ("CHANNEL PILLAR: position in channel at entry", channel_bucket),
        ("MOMENTUM PILLAR: multi-period alignment at entry", alignment_bucket),
    ):
        print_table(title + "  [FIFO-paired, approximate]",
                    tally((fn(reason), pnl) for reason, _ts, pnl in paired))

    # 4. monthly split by exit branch
    monthly: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for _sym, _act, timestamp, reason, pnl in sells:
        monthly[timestamp[:7]][exit_branch(reason)] += pnl
    print("\n--- MONTHLY REALIZED PnL BY EXIT BRANCH ---")
    print(f"{'month':<10}{'trail':>14}{'hard stop':>14}{'other':>12}{'net':>14}")
    for month in sorted(monthly):
        branches = monthly[month]
        trail = branches["TRAIL-STOP (BaseAgent)"]
        stop = branches["HARD STOP -8% (risk mgr)"]
        net = sum(branches.values())
        print(f"{month:<10}{trail:>14,.0f}{stop:>14,.0f}{net - trail - stop:>12,.0f}{net:>14,.0f}")


if __name__ == "__main__":
    main()
