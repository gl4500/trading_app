r"""
Diagnostic: replay all trades for a single agent through a fresh Portfolio
and compare the replayed cash + cost-basis state against the live snapshot
stored in trading.db.

Originally written for GitHub issue #64 (HistoricalTrendsAgent $18,720.78
cash drift, 2026-05-16) but parameterised by agent_id so it can be re-used
to audit any agent's books.

Run from repo root:
    runtime\python\python.exe scripts\debug_historical_drift.py [agent_id]

Default agent_id = 82 (HistoricalTrendsAgent at the time of issue #64).
"""
import io
import os
import sqlite3
import sys

# Force UTF-8 on the console so box-drawing chars don't crash cp1252 (Windows)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
elif isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Path bootstrap so the script can import the production Portfolio
# without depending on PYTHONPATH being set externally.
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "site-packages"))
sys.path.insert(0, os.path.join(REPO, "backend"))

from trading.portfolio import Portfolio  # noqa: E402


DB_PATH = os.path.join(REPO, "backend", "trading.db")
STARTING_CAPITAL = 100_000.0


def main(agent_id: int = 82) -> int:
    if not os.path.exists(DB_PATH):
        print(f"trading.db not found at {DB_PATH}")
        return 1

    # READ-ONLY connection (URI mode + mode=ro)
    uri = f"file:{DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Agent name (for the report header)
    cur.execute("SELECT name FROM agents WHERE id = ?", (agent_id,))
    row = cur.fetchone()
    if not row:
        print(f"agent_id={agent_id} not found")
        return 1
    agent_name = row["name"]

    # All trades in chronological order
    cur.execute(
        "SELECT id, symbol, action, shares, price, timestamp, pnl "
        "FROM trades WHERE agent_id = ? ORDER BY timestamp ASC, id ASC",
        (agent_id,),
    )
    trades = cur.fetchall()

    # Live DB snapshot
    cur.execute(
        "SELECT cash, total_value FROM performance "
        "WHERE agent_id = ? ORDER BY id DESC LIMIT 1",
        (agent_id,),
    )
    perf = cur.fetchone()
    db_cash = perf["cash"] if perf else None
    db_total = perf["total_value"] if perf else None

    cur.execute(
        "SELECT symbol, shares, avg_cost, last_price "
        "FROM portfolios WHERE agent_id = ? AND shares > 0",
        (agent_id,),
    )
    db_positions = {r["symbol"]: dict(r) for r in cur.fetchall()}

    # ── Replay ───────────────────────────────────────────────────────────────
    portfolio = Portfolio(starting_capital=STARTING_CAPITAL)
    steps = []  # per-trade snapshot
    sell_fail_counts = {"no_position": 0, "shares_capped": 0, "sold_more_than_held": 0}
    buy_fail_counts = {"insufficient_cash": 0}

    # Track DB-stated vs replay flows to spot divergence early
    db_buy_dollars = 0.0
    db_sell_dollars = 0.0
    db_realized = 0.0

    for t in trades:
        tid = t["id"]
        sym = t["symbol"]
        action = t["action"]
        shares = float(t["shares"])
        price = float(t["price"])
        db_pnl = float(t["pnl"] or 0.0)
        ts = t["timestamp"]

        before_cash = portfolio.cash
        before_pos_shares = (
            portfolio.positions[sym].shares if sym in portfolio.positions else 0.0
        )

        outcome = "ok"
        if action == "BUY":
            db_buy_dollars += shares * price
            ok = portfolio.execute_buy(sym, shares, price, reasoning=f"replay#{tid}")
            if not ok:
                buy_fail_counts["insufficient_cash"] += 1
                outcome = "BUY_FAIL_NO_CASH"
        elif action == "SELL":
            db_sell_dollars += shares * price
            db_realized += db_pnl
            if sym not in portfolio.positions:
                sell_fail_counts["no_position"] += 1
                outcome = "SELL_FAIL_NO_POSITION"
            else:
                held = portfolio.positions[sym].shares
                if shares > held + 1e-6:
                    sell_fail_counts["sold_more_than_held"] += 1
                    outcome = f"SELL_OVERSIZED({shares:.4f}_vs_held_{held:.4f})"
                ok = portfolio.execute_sell(sym, shares, price, reasoning=f"replay#{tid}")
                if not ok:
                    outcome = (outcome + "|EXEC_FALSE") if outcome != "ok" else "SELL_EXEC_FALSE"
        elif action == "SPLIT":
            # Synthetic; shouldn't appear for agent 82, but handle gracefully
            outcome = "SPLIT_skipped"
        else:
            outcome = f"UNKNOWN_ACTION_{action}"

        after_cash = portfolio.cash
        after_pos_shares = (
            portfolio.positions[sym].shares if sym in portfolio.positions else 0.0
        )

        steps.append({
            "idx": len(steps) + 1,
            "trade_id": tid,
            "ts": ts,
            "action": action,
            "symbol": sym,
            "shares": shares,
            "price": price,
            "db_pnl": db_pnl,
            "before_cash": before_cash,
            "after_cash": after_cash,
            "delta_cash": after_cash - before_cash,
            "before_held": before_pos_shares,
            "after_held": after_pos_shares,
            "outcome": outcome,
        })

    # ── Replay vs implied vs live ────────────────────────────────────────────
    # Implied cash from pure trade math (issue #64 reconciliation):
    implied_cash = STARTING_CAPITAL + db_sell_dollars - db_buy_dollars

    # Replay cost basis still held
    replay_cost_basis = sum(p.shares * p.avg_cost for p in portfolio.positions.values())
    # Replay realized
    replay_realized = sum(t.pnl for t in portfolio.trade_history if t.action == "SELL")

    # DB cost basis still held
    db_cost_basis = sum(
        float(p["shares"]) * float(p["avg_cost"]) for p in db_positions.values()
    )

    print("=" * 78)
    print(f"REPLAY DIAGNOSTIC: agent_id={agent_id} ({agent_name})")
    print(f"DB: {DB_PATH}")
    print(f"Trades replayed: {len(trades)}")
    print("=" * 78)

    print("\n── Cash reconciliation ──────────────────────────────────────────────")
    print(f"  starting_capital                      : ${STARTING_CAPITAL:>14,.2f}")
    print(f"  DB sum of BUY  cash out  (shares*px)  : ${db_buy_dollars:>14,.2f}")
    print(f"  DB sum of SELL cash in   (shares*px)  : ${db_sell_dollars:>14,.2f}")
    print(f"  DB sum of SELL.pnl col   (realized)   : ${db_realized:>14,.2f}")
    print(f"  IMPLIED cash (start + sells - buys)   : ${implied_cash:>14,.2f}")
    print(f"  REPLAY portfolio.cash (final)         : ${portfolio.cash:>14,.2f}")
    if db_cash is not None:
        print(f"  LIVE   performance.cash (DB snapshot) : ${db_cash:>14,.2f}")
        print(f"  DRIFT  (replay - live)                : ${portfolio.cash - db_cash:>14,.2f}")
        print(f"  DRIFT  (implied - live)               : ${implied_cash - db_cash:>14,.2f}")
        print(f"  DRIFT  (replay - implied)             : ${portfolio.cash - implied_cash:>14,.2f}")

    print("\n── Cost basis & realized ────────────────────────────────────────────")
    print(f"  REPLAY cost basis held                : ${replay_cost_basis:>14,.2f}")
    print(f"  DB     cost basis held (sum sh*avg)   : ${db_cost_basis:>14,.2f}")
    print(f"  REPLAY realized (sum sell.pnl)        : ${replay_realized:>14,.2f}")
    print(f"  DB     realized (sum sell.pnl col)    : ${db_realized:>14,.2f}")

    print("\n── Identity check  cash + cost_basis_held - realized ≈ start ───────")
    identity_db = (db_cash or 0.0) + db_cost_basis - db_realized
    identity_replay = portfolio.cash + replay_cost_basis - replay_realized
    print(f"  DB    : ${identity_db:>14,.2f}  (gap from $100k: ${STARTING_CAPITAL - identity_db:>+14,.2f})")
    print(f"  REPLAY: ${identity_replay:>14,.2f}  (gap from $100k: ${STARTING_CAPITAL - identity_replay:>+14,.2f})")

    print("\n── Failure counts during replay ─────────────────────────────────────")
    for k, v in {**buy_fail_counts, **sell_fail_counts}.items():
        print(f"  {k:30s}: {v}")

    # ── Show steps where replay deviated from a naive equality with DB ────
    print("\n── Anomalous steps (oversized / no-position / fail) ──────────────────")
    n_anom = 0
    for s in steps:
        if s["outcome"] != "ok":
            n_anom += 1
            if n_anom <= 30:  # cap output
                print(
                    f"  step#{s['idx']:>3} trade#{s['trade_id']:>5} "
                    f"{s['ts']} {s['action']:>4} {s['symbol']:>5} "
                    f"shares={s['shares']:>10.4f} held={s['before_held']:>10.4f} "
                    f"outcome={s['outcome']}"
                )
    if n_anom > 30:
        print(f"  ... ({n_anom - 30} more anomalies suppressed)")
    print(f"  TOTAL anomalous steps: {n_anom}")

    # ── Per-symbol open-position comparison ──────────────────────────────────
    print("\n── Open-position comparison REPLAY vs DB ────────────────────────────")
    all_syms = sorted(set(portfolio.positions) | set(db_positions))
    print(f"  {'symbol':<8} {'replay_sh':>12} {'db_sh':>12}  {'replay_avg':>12} {'db_avg':>12} {'note':<30}")
    for sym in all_syms:
        rs = portfolio.positions[sym].shares if sym in portfolio.positions else 0.0
        ravg = portfolio.positions[sym].avg_cost if sym in portfolio.positions else 0.0
        ds = float(db_positions[sym]["shares"]) if sym in db_positions else 0.0
        davg = float(db_positions[sym]["avg_cost"]) if sym in db_positions else 0.0
        note = ""
        if sym in portfolio.positions and sym not in db_positions:
            note = "REPLAY-ONLY (likely cleanup_stale removed)"
        elif sym in db_positions and sym not in portfolio.positions:
            note = "DB-ONLY (replay sold to 0)"
        elif abs(rs - ds) > 0.001:
            note = f"SHARES_DIFF ({rs - ds:+.4f})"
        print(f"  {sym:<8} {rs:>12.4f} {ds:>12.4f}  {ravg:>12.4f} {davg:>12.4f} {note:<30}")

    # ── Save full step CSV for deep dive ─────────────────────────────────────
    csv_path = os.path.join(HERE, f"debug_historical_drift_agent{agent_id}_steps.csv")
    import csv
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(steps[0].keys()))
        w.writeheader()
        w.writerows(steps)
    print(f"\nFull step trace written to: {csv_path}")

    conn.close()
    return 0


if __name__ == "__main__":
    aid = int(sys.argv[1]) if len(sys.argv) > 1 else 82
    raise SystemExit(main(aid))
