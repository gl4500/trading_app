"""S1-SNAPSHOTS (§5): the ONLY reader of the live trading.db. SQLite online backup from a mode=ro source into an
isolated file, then an MeanReversion-only projection. Never copies, checkpoints or hashes the live file."""
import json
import sqlite3
from pathlib import Path

import s1_common as c

REQUIRED = {"agents": {"id", "name"},
            "trades": {"id", "agent_id", "symbol", "action", "shares", "price", "timestamp", "reasoning"},
            "portfolios": {"agent_id", "symbol", "shares"}}


class SnapshotError(Exception):
    pass


def _backup(live_db: Path, dest: Path) -> None:
    src = sqlite3.connect(f"file:{Path(live_db).as_posix()}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def project(db: Path) -> dict:
    con = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)
    try:
        schema = {t: [[r[1], r[2]] for r in con.execute(f"PRAGMA table_info({t})")] for t in REQUIRED}
        for t, need in REQUIRED.items():
            missing = need - {name for name, _ in schema[t]}
            if missing:
                raise SnapshotError(f"{t}: missing column(s) {sorted(missing)}")
        ids = [r[0] for r in con.execute("SELECT id FROM agents WHERE name=?", (c.AGENT,))]
        if len(ids) != 1:
            raise SnapshotError(f"expected exactly one {c.AGENT} agent row, found {len(ids)}")
        aid = ids[0]
        trades = []
        for i, sym, act, sh, px, ts, reason in con.execute(
                "SELECT id, symbol, action, shares, price, timestamp, reasoning FROM trades WHERE agent_id=? "
                "ORDER BY id", (aid,)):
            try:
                t = c.aware(ts).isoformat()
            except ValueError as e:
                raise SnapshotError(f"trade {i}: bad timestamp {ts!r}: {e}")
            trades.append({"id": i, "symbol": sym, "action": act, "shares": sh, "price": px, "timestamp": ts,
                           "ts": t, "reasoning_sha256": c.sha256_bytes((reason or "").encode("utf-8"))})
        port = {sym: sh for sym, sh in con.execute("SELECT symbol, shares FROM portfolios WHERE agent_id=?", (aid,))}
        return {"agent_id": aid, "trades": trades, "portfolios": port, "schema": schema}
    finally:
        con.close()


def take_snapshot(live_db: Path, out_dir: Path) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=False)            # FileExistsError: never overwrite a capture
    meta = {"capture_start": c.now_utc().isoformat(), "ok": False, "error": None}
    backup = out_dir / "backup.sqlite3"
    try:
        _backup(live_db, backup)
        meta["capture_end"] = c.now_utc().isoformat()
        proj = project(backup)
        blob = c.canonical(proj)
        (out_dir / "projection.json").write_bytes(blob)
        meta.update(ok=True, backup_sha256=c.sha256_file(backup), projection_sha256=c.sha256_bytes(blob),
                    schema=proj["schema"], max_trade_id=max((t["id"] for t in proj["trades"]), default=0),
                    n_trades=len(proj["trades"]), n_portfolio_rows=len(proj["portfolios"]))
    except (sqlite3.Error, SnapshotError, OSError) as e:
        meta.setdefault("capture_end", c.now_utc().isoformat())
        meta["error"] = f"{type(e).__name__}: {e}"
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=1, default=str), encoding="utf-8")
    return meta
