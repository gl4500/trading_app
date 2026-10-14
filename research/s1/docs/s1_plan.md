# S1 MeanReversion P13 Shadow Trial — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Build the offline S1 toolchain (snapshot, books, seals, receipt, checkpoint, collectors, runner) that
runs the agreed MeanReversion P13 daily-bar shadow trial without touching the live app.

**Architecture:** Seven focused modules plus a shared-constants module in `C:\Users\gl450\.coordination\trading_app\`.
Only `s1_snapshot` opens `trading.db` (SQLite online backup, read-only source). The economic maths (P13, FIFO,
costs, exact arithmetic, paired comparison) comes from the hash-pinned PURE E1 core `e1_sim.py`; corporate-action
validation/classification comes from the hash-pinned E1 collector `e1_fetch.py` (its pure functions only). Each lifecycle stage has its own output namespace
and approval token.

**Tech Stack:** Python 3.12 (isolated testenv), sqlite3, ast, httpx 0.28.1 (collectors only), pytest 8.3.3,
hypothesis 6.112.1, cosmic-ray 8.3.15. No new product dependencies.

**Spec:** `s1_spec.md` (sha256 4b882f52…, Codex APPROVE-SPEC 7a6b16fd). Governing design: `s1_design_v5.md`
(sha256 33c32840…, Codex APPROVE-DESIGN 502ca2a4) — **the design's full clauses govern**; section numbers
(§) below refer to it. Read both before starting.

## Global Constraints
- Working dir `C:\Users\gl450\.coordination\trading_app`; python `testenv/Scripts/python.exe` for tests and tools.
- NEVER open the live `C:\Users\gl450\trading_app\backend\trading.db`, the live app, port 8000 or any network
  endpoint while building or testing. Tests use synthetic files under pytest `tmp_path` only.
- NEVER register a scheduler task, take a live snapshot, request data or score: those run only after the staged
  approvals in §15 (S1-AUDIT-ACK, S1-RUN-ACK, S1-ACQUIRE-ACK, S1-SCORE-ACK), outside this build plan.
- Do NOT edit `e1_sim.py` (sha256 68f21ab19d74be27fc855f826a78b667990c2a37b5d75dd12e1a7be1f5a740fb) or
  `e1_fetch.py` (sha256 401f17deb3551b0a585be64eb49294f50bc0396272ecd48c9f9049acc86984d6); load them only via
  `s1_common.load_pinned`.
- P13 = `e1_sim.policy_family()` entry `"P13"`: hard 0.08, trail 0.12, target None, time None (asserted).
- Costs: 5 bp and 10 bp gate; 0 and 1 bp reported. Exact arithmetic via the E1 core.
- Fully sold: strict `< 0.001` share after an actual SELL allocation to the lot (§8). Operational write-off:
  aggregate `< 0.001` after a SELL (§7). Consistency tolerance 1e-9 shares.
- Seal schedule per close C: C+45 min, then +47, +49, +51, +53, +55 min, then on each full hour until 08:00
  America/New_York of the next NYSE session day (§6).
- Timeout: START + 6 calendar months (missing day-of-month → month's last day); last sealed close ≤ deadline (§9).
- Cap: INCONCLUSIVE iff 10·K > N; INSUFFICIENT iff N − K < 30 (§14).
- Ledger time = stored `trades.timestamp`; naive values are read as UTC (E1 convention); all instants aware UTC.
- Testing standard: PEER_REVIEW.md — intended RED recorded before code (missing-interface failures labelled),
  GREEN, Hypothesis, connected workflow with real schemas, targeted mutants + focused Cosmic Ray, independent
  oracle for economics.
- This folder is not a git repository: each task ends with "Record evidence" (hashes + test output into
  `s1_evidence/`), not a commit.

## Review Focus
1. **Odd ledger timestamp spellings** (`Z` vs `+00:00`, microseconds, a naive legacy value): the same instant must
   give the same cohort and stop; a malformed value must abort the checkpoint, not be skipped. → Task 1, Task 3.
2. **Symbol spelling mismatch between `trades` and `portfolios`** (e.g. `brk.b` vs `BRK.B`, trailing space): a
   reasonable operator expects it flagged as an inconsistency, never silently merged. → Task 2.
3. **Scheduler fires late or the PC was asleep** (capture taken hours after its slot): it must not seal outside
   the registered schedule and must be reported as a missed slot. → Task 3.
4. **Live database busy/locked during backup** (`sqlite3.OperationalError: database is locked`): the capture
   is recorded as failed and the next scheduled slot is used; no crash, no partial projection. → Task 1.
5. **No new MR trades for weeks** (empty cohort, zero sales): checkpoints keep working and the trial ends by
   timeout as NO-VALID-SEAL or INSUFFICIENT, never as FAIL. → Task 3, Task 7.

---

## File Structure
| File | Responsibility |
|---|---|
| `s1_common.py` | constants, hashing, canonical JSON, aware timestamp parsing, pinned-module loader |
| `s1_snapshot.py` | SQLite online backup of a live file + MR projection + hashes (§5) — only `trading.db` reader |
| `s1_books.py` | operational replay with write-off audit, consistency, economic FIFO wrapper, sold events, bridge (§7–8) |
| `s1_seal.py` | calendar helpers, seal schedule, seal choice, row fences, backdating checks, deadline, stop (§4, §6, §9) |
| `s1_receipt.py` | semantic receipt (git, AST closure, config, versions), process identity, crash.log restarts (§12) |
| `s1_checkpoint.py` | the scheduled read-only counts-only command (§10) |
| `s1_collect.py` | metadata plan, opening audit, final acquisition (§4, §11, §13) using pinned e1_fetch helpers |
| `s1_run.py` | lifecycle gates/ACKs, attestations, exclusions, economics, verdict, report (§12–15) |
| `s1_tests/` | `conftest.py` (synthetic real-schema DB builder) + one test module per component + connected workflow + oracle |
| `s1_evidence/` | RED/GREEN outputs, hashes, mutant and Cosmic Ray records |

## Example → test mapping (design §16)
| Ex | Test (module::name) |
|---|---|
| 1 | test_s1_seal::test_capture_between_trade_and_portfolio_commit_is_inconsistent_and_retried |
| 2 | test_s1_seal::test_trade_stored_after_close_excluded_from_as_of_rows |
| 3 | test_s1_books::test_dusty_closure_then_reentry_books_and_bridge |
| 4 | test_s1_books::test_two_same_symbol_lots_fifo_count |
| 5 | test_s1_books::test_tiny_buy_without_sell_never_sold |
| 6 | test_s1_books::test_threshold_exactly_0_001_vs_below |
| 7 | test_s1_seal::test_backdated_row_invalidates |
| 8 | test_s1_seal::test_executed_before_start_stored_after_is_cohort |
| 9 | test_s1_run::test_missing_attestation_is_unverified_and_not_a_nomination |
| 10 | test_s1_checkpoint::test_restart_recorded_and_source_change_invalidates |
| 11 | test_s1_receipt::test_pid_change_without_process_start_line_is_gap |
| 12 | test_s1_run::test_carry_in_split_blocked_or_inconclusive |
| 13 | test_s1_seal::test_overshoot_stops_with_all_entries |
| 14 | test_s1_seal::test_unsealed_qualifying_close_is_not_the_stop |
| 15 | test_s1_seal::test_deadline_holiday_month_end_and_no_valid_seal |
| 16 | test_s1_run::test_prereg_after_planned_start_refused |
| 17 | test_s1_checkpoint::test_checkpoint_cannot_reach_economics_or_prices |
| 18 | test_s1_run::test_mismatched_or_duplicate_acks_make_no_request_no_output |
| 19 | test_s1_seal::test_bridge_rows_update_opening_books_not_cohort |
| 20 | test_s1_run::test_bridge_ticker_unaudited_split_inconclusive |
| 21 | test_s1_run::test_exclusion_window_resolved_vs_inside |
| 22 | test_s1_run::test_undated_action_excludes_all_lots_of_symbol |
| 23 | test_s1_run::test_endpoint_day_entry_missing_stop_close_excluded |

---

### Task 0: Shared constants, pinned loader, synthetic real-schema fixture

**Files:**
- Create: `s1_common.py`, `s1_tests/__init__.py` (empty), `s1_tests/conftest.py`, `s1_tests/test_s1_common.py`
- Create dirs: `s1_evidence/`

**Interfaces:**
- Produces: `s1_common.AGENT`, `POLICY_ID`, `SOLD_LT`, `CONSIST_TOL`, `NY`, `sha256_bytes(b)->str`,
  `sha256_file(p)->str`, `canonical(obj)->bytes`, `aware(ts:str)->datetime`, `load_pinned(name, path, sha)->module`,
  `sim()->module`, `fetch()->module`, `p13()->dict`, `now_utc()->datetime`.
- Produces (tests): fixture `ledger(tmp_path)` → `Ledger` with `.path`, `.agent_id`, `.trade(symbol, action,
  shares, price, ts, reasoning="r")->int`, `.set_portfolio(symbol, shares)`, `.drop_portfolio(symbol)`.
  Task 7 adds `s1_state(root, planned_start, score_ready=False)` to this conftest (synthetic `s1_out/`: plan,
  audit manifest, START attestation, mailbox; with `score_ready` also seals, stop attestation and a final
  manifest) — test-only, never in a product module.

- [ ] **Step 1: Write the failing test** — `s1_tests/test_s1_common.py`

```python
import pytest
from datetime import datetime, timezone
import s1_common as c


def test_aware_parses_both_utc_spellings_to_the_same_instant():
    a = c.aware("2026-10-15T14:30:00.123456+00:00")
    b = c.aware("2026-10-15T14:30:00.123456Z")
    assert a == b and a.tzinfo is not None


def test_aware_reads_naive_as_utc_and_rejects_garbage():
    assert c.aware("2026-10-15 14:30:00") == datetime(2026, 10, 15, 14, 30, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        c.aware("15/10/2026 2:30pm")


def test_pinned_core_and_p13():
    p = c.p13()
    assert (p["id"], p["hard"], p["trail"], p["target"], p["time"]) == ("P13", 0.08, 0.12, None, None)


def test_pinned_loader_refuses_a_changed_file(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("X = 1\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="hash"):
        c.load_pinned("m_pinned", f, "0" * 64)


def test_canonical_is_order_independent():
    assert c.canonical({"b": 1, "a": [2, 1]}) == c.canonical({"a": [2, 1], "b": 1})


def test_fixture_has_the_real_schema(ledger):
    import sqlite3
    con = sqlite3.connect(ledger.path)
    cols = {t: [r[1] for r in con.execute(f"PRAGMA table_info({t})")] for t in ("agents", "trades", "portfolios")}
    assert cols["trades"] == ["id", "agent_id", "symbol", "action", "shares", "price", "timestamp", "reasoning", "pnl"]
    assert cols["portfolios"] == ["id", "agent_id", "symbol", "shares", "avg_cost", "current_value", "unrealized_pnl"]
```

- [ ] **Step 2: Write the fixture** — `s1_tests/conftest.py` (schema copied from trading_app `backend/database_schema.py`
  on origin/main f03b7dc, plus the `pnl` column that `save_trade` writes)

```python
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SCHEMA = [
    """CREATE TABLE agents (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, strategy TEXT,
       created_at TEXT NOT NULL)""",
    """CREATE TABLE portfolios (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id INTEGER NOT NULL, symbol TEXT NOT NULL,
       shares REAL NOT NULL DEFAULT 0, avg_cost REAL NOT NULL DEFAULT 0, current_value REAL NOT NULL DEFAULT 0,
       unrealized_pnl REAL NOT NULL DEFAULT 0, UNIQUE(agent_id, symbol))""",
    """CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id INTEGER NOT NULL, symbol TEXT NOT NULL,
       action TEXT NOT NULL, shares REAL NOT NULL, price REAL NOT NULL, timestamp TEXT NOT NULL, reasoning TEXT,
       pnl REAL DEFAULT 0)""",
]


class Ledger:
    def __init__(self, path: Path):
        self.path = path
        con = sqlite3.connect(path)
        con.execute("PRAGMA journal_mode=WAL")
        for s in SCHEMA:
            con.execute(s)
        con.execute("INSERT INTO agents (name, strategy, created_at) VALUES ('XGBReasoningAgent','x','t')")
        self.agent_id = con.execute("INSERT INTO agents (name, strategy, created_at) VALUES "
                                    "('MeanReversionAgent','mr','t')").lastrowid
        con.commit()
        con.close()

    def _x(self, sql, args):
        con = sqlite3.connect(self.path)
        cur = con.execute(sql, args)
        con.commit()
        con.close()
        return cur.lastrowid

    def trade(self, symbol, action, shares, price, ts, reasoning="r", agent_id=None):
        return self._x("INSERT INTO trades (agent_id, symbol, action, shares, price, timestamp, reasoning, pnl) "
                       "VALUES (?,?,?,?,?,?,?,0)", (agent_id or self.agent_id, symbol, action, shares, price, ts,
                                                    reasoning))

    def set_portfolio(self, symbol, shares):
        self._x("INSERT INTO portfolios (agent_id, symbol, shares) VALUES (?,?,?) "
                "ON CONFLICT(agent_id, symbol) DO UPDATE SET shares=excluded.shares", (self.agent_id, symbol, shares))

    def drop_portfolio(self, symbol):
        self._x("DELETE FROM portfolios WHERE agent_id=? AND symbol=?", (self.agent_id, symbol))


@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path / "trading.db")
```

- [ ] **Step 3: Run to verify RED** — `testenv/Scripts/python.exe -m pytest s1_tests/test_s1_common.py -q -p no:cacheprovider 2>&1 | tee s1_evidence/t0_red.txt`
  Expected: collection error `ModuleNotFoundError: s1_common` (label: missing-interface RED).

- [ ] **Step 4: Implement** — `s1_common.py`

```python
"""S1 shared constants and helpers (design s1_design_v5.md 33c32840; spec s1_spec.md 4b882f52)."""
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
NY = ZoneInfo("America/New_York")
AGENT = "MeanReversionAgent"
POLICY_ID = "P13"
SOLD_LT = 0.001                 # app close rule: backend/trading/portfolio.py `pos.shares < 0.001`
CONSIST_TOL = 1e-9
E1_SIM_SHA = "68f21ab19d74be27fc855f826a78b667990c2a37b5d75dd12e1a7be1f5a740fb"
E1_FETCH_SHA = "401f17deb3551b0a585be64eb49294f50bc0396272ecd48c9f9049acc86984d6"
_CACHE = {}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p) -> str:
    return sha256_bytes(Path(p).read_bytes())


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def aware(ts: str) -> datetime:
    """Stored ledger time -> aware UTC. `Z` accepted; naive read as UTC (E1 convention); anything else raises."""
    if not isinstance(ts, str) or not ts:
        raise ValueError(f"not a timestamp: {ts!r}")
    t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def load_pinned(name: str, path, sha: str):
    path = Path(path)
    if not path.exists() or sha256_file(path) != sha:
        raise SystemExit(f"{path.name}: missing or hash differs from the pinned {sha[:12]}")
    if name not in _CACHE:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _CACHE[name] = mod
    return _CACHE[name]


def sim():
    return load_pinned("e1_sim_pinned", HERE / "e1_sim.py", E1_SIM_SHA)


def fetch():
    return load_pinned("e1_fetch_pinned", HERE / "e1_fetch.py", E1_FETCH_SHA)


def p13() -> dict:
    p = next(p for p in sim().policy_family() if p["id"] == POLICY_ID)
    if (p["hard"], p["trail"], p.get("target"), p.get("time")) != (0.08, 0.12, None, None):
        raise SystemExit(f"P13 in the pinned core is not the registered rule: {p}")
    return p
```

- [ ] **Step 5: Run to verify GREEN** — same command → `s1_evidence/t0_green.txt`; Expected: 6 passed.
- [ ] **Step 6: Record evidence** — `sha256sum s1_common.py s1_tests/conftest.py s1_tests/test_s1_common.py > s1_evidence/t0_hashes.txt`

---

### Task 1: Snapshot — online backup + MR projection (R-SNAP, Review Focus 1, 4)

**Files:** Create `s1_snapshot.py`, `s1_tests/test_s1_snapshot.py`

**Interfaces:**
- Consumes: `s1_common.*`
- Produces: `take_snapshot(live_db: Path, out_dir: Path) -> dict` (meta: capture_start, capture_end, ok, error,
  backup_sha256, projection_sha256, schema, max_trade_id, n_trades, n_portfolio_rows; writes
  `out_dir/backup.sqlite3`, `out_dir/projection.json`, `out_dir/meta.json`); `project(db: Path) -> dict`
  (`{"agent_id", "trades": [{id, symbol, action, shares, price, timestamp, ts, reasoning_sha256}], "portfolios":
  {symbol: shares}, "schema": {...}}` — `ts` is the aware ISO form of `timestamp`); `class SnapshotError`.

- [ ] **Step 1: Write the failing tests**

```python
import json
import sqlite3
import threading

import pytest
import s1_snapshot as s


def test_projection_is_mr_only_with_real_fields(ledger, tmp_path):
    ledger.trade("AAA", "BUY", 10, 50.0, "2026-10-15T14:30:00+00:00", reasoning="secret-ish text")
    ledger.trade("ZZZ", "BUY", 1, 1.0, "2026-10-15T14:31:00+00:00", agent_id=1)        # other agent
    ledger.set_portfolio("AAA", 10)
    m = s.take_snapshot(ledger.path, tmp_path / "cap")
    p = json.loads((tmp_path / "cap" / "projection.json").read_text(encoding="utf-8"))
    assert m["ok"] and [t["symbol"] for t in p["trades"]] == ["AAA"] and p["portfolios"] == {"AAA": 10.0}
    assert "secret-ish text" not in (tmp_path / "cap" / "projection.json").read_text(encoding="utf-8")
    assert len(p["trades"][0]["reasoning_sha256"]) == 64 and m["max_trade_id"] == p["trades"][-1]["id"]


def test_live_file_bytes_unchanged_and_refuses_existing_output(ledger, tmp_path):
    before = ledger.path.read_bytes()
    s.take_snapshot(ledger.path, tmp_path / "cap")
    assert ledger.path.read_bytes() == before
    with pytest.raises(FileExistsError):
        s.take_snapshot(ledger.path, tmp_path / "cap")


def test_missing_required_column_is_a_snapshot_error(tmp_path):
    db = tmp_path / "bad.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE agents (id INTEGER PRIMARY KEY, name TEXT)")
    con.execute("INSERT INTO agents VALUES (1,'MeanReversionAgent')")
    con.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, agent_id INT, symbol TEXT)")
    con.execute("CREATE TABLE portfolios (agent_id INT, symbol TEXT, shares REAL)")
    con.commit(); con.close()
    m = s.take_snapshot(db, tmp_path / "cap")
    assert m["ok"] is False and "column" in m["error"]
    assert not (tmp_path / "cap" / "projection.json").exists()


def test_locked_database_records_a_failed_capture_not_a_crash(ledger, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(s, "_backup", boom)
    m = s.take_snapshot(ledger.path, tmp_path / "cap")
    assert m["ok"] is False and "locked" in m["error"]
    assert not (tmp_path / "cap" / "projection.json").exists()


def test_malformed_ledger_timestamp_fails_the_capture(ledger, tmp_path):
    ledger.trade("AAA", "BUY", 1, 1.0, "15/10/2026")
    m = s.take_snapshot(ledger.path, tmp_path / "cap")
    assert m["ok"] is False and "timestamp" in m["error"]


def test_backup_during_concurrent_wal_writer_is_a_committed_state(ledger, tmp_path):
    stop = threading.Event()

    def writer():
        con = sqlite3.connect(ledger.path)
        i = 0
        while not stop.is_set() and i < 400:
            con.execute("INSERT INTO trades (agent_id, symbol, action, shares, price, timestamp, reasoning, pnl) "
                        "VALUES (?,?,?,?,?,?,?,0)", (ledger.agent_id, f"S{i%7}", "BUY", 1, 1.0,
                                                     "2026-10-15T14:30:00+00:00", "w"))
            con.commit(); i += 1
        con.close()
    t = threading.Thread(target=writer); t.start()
    m = s.take_snapshot(ledger.path, tmp_path / "cap")
    stop.set(); t.join()
    p = json.loads((tmp_path / "cap" / "projection.json").read_text(encoding="utf-8"))
    ids = [r["id"] for r in p["trades"]]
    assert m["ok"] and ids == sorted(ids) and ids == list(range(ids[0], ids[0] + len(ids)))   # no holes
```

- [ ] **Step 2: RED** — `testenv/Scripts/python.exe -m pytest s1_tests/test_s1_snapshot.py -q -p no:cacheprovider 2>&1 | tee s1_evidence/t1_red.txt` (expected: missing `s1_snapshot`, label missing-interface).

- [ ] **Step 3: Implement** — `s1_snapshot.py`

```python
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
```

- [ ] **Step 4: GREEN** — same command → `s1_evidence/t1_green.txt`; Expected: 6 passed.
- [ ] **Step 5: Record evidence** — `sha256sum s1_snapshot.py s1_tests/test_s1_snapshot.py > s1_evidence/t1_hashes.txt`

---

### Task 2: Books — operational replay, consistency, economic FIFO, sold events, bridge (R-QTY, R-SOLD, Review Focus 2)

**Files:** Create `s1_books.py`, `s1_tests/test_s1_books.py`

**Interfaces:**
- Consumes: projection trades (Task 1 format), `s1_common.sim()`.
- Produces: `rows(trades) -> list[dict]` (E1 row dicts: id, symbol, action, shares, price, ts:datetime, sorted by
  (ts, id)); `operational_replay(trades) -> {"qty": {sym: float}, "writeoffs": [{"id","symbol","qty"}]}`;
  `consistency(trades, portfolios) -> {"consistent": bool, "diffs": [{"symbol","replay","portfolio"}]}`;
  `economic_lots(trades, endpoint: datetime) -> list` (E1 `baseline_lots` output; orphans raise);
  `sold_events(trades) -> {lot_id: {"sold_at": iso, "sell_id": int}}`;
  `bridge(trades, endpoint) -> {sym: {"writeoff": float, "economic_residual": float}}`; `class BookError`.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
import s1_books as b

T = "2026-10-1{}T14:3{}:00+00:00"


def tr(i, sym, act, sh, px, d=5, m=0):
    return {"id": i, "symbol": sym, "action": act, "shares": sh, "price": px, "timestamp": T.format(d, m),
            "ts": T.format(d, m), "reasoning_sha256": "0" * 64}


def test_dusty_closure_then_reentry_books_and_bridge():                       # design example 3
    t = [tr(1, "A", "BUY", 10, 50, 5), tr(2, "A", "SELL", 9.9995, 55, 6), tr(3, "A", "BUY", 10, 52, 7)]
    op = b.operational_replay(t)
    assert op["qty"] == {"A": 10.0} and op["writeoffs"] == [{"id": 2, "symbol": "A", "qty": pytest.approx(0.0005)}]
    assert b.consistency(t, {"A": 10.0})["consistent"]
    lots = {l["id"]: l for l in b.economic_lots(t, b.rows(t)[-1]["ts"])}
    assert float(lots[1]["rem_qty"]) == pytest.approx(0.0005) and float(lots[3]["rem_qty"]) == 10.0
    assert b.sold_events(t)[1]["sell_id"] == 2 and 3 not in b.sold_events(t)
    assert b.bridge(t, b.rows(t)[-1]["ts"])["A"] == {"writeoff": pytest.approx(0.0005),
                                                       "economic_residual": pytest.approx(10.0005)}


def test_two_same_symbol_lots_fifo_count():                                    # example 4
    t = [tr(1, "A", "BUY", 10, 50, 5), tr(2, "A", "BUY", 10, 51, 5, 1), tr(3, "A", "SELL", 10, 55, 6)]
    assert set(b.sold_events(t)) == {1}


def test_tiny_buy_without_sell_never_sold():                                   # example 5
    assert b.sold_events([tr(1, "A", "BUY", 0.0005, 50, 5)]) == {}


@pytest.mark.parametrize("left,sold", [(0.001, False), (0.000999, True)])
def test_threshold_exactly_0_001_vs_below(left, sold):                         # example 6
    t = [tr(1, "A", "BUY", 10, 50, 5), tr(2, "A", "SELL", 10 - left, 55, 6)]
    assert (1 in b.sold_events(t)) is sold


def test_sold_event_is_absorbing_and_attribution_unchanged():
    t = [tr(1, "A", "BUY", 10, 50, 5), tr(2, "A", "SELL", 9.9995, 55, 6), tr(3, "A", "BUY", 10, 52, 7),
         tr(4, "A", "SELL", 5, 56, 8)]
    ev = b.sold_events(t)
    assert ev[1]["sell_id"] == 2                       # still the first event after later rows
    lots = {l["id"]: l for l in b.economic_lots(t, b.rows(t)[-1]["ts"])}
    assert float(lots[1]["rem_qty"]) == 0.0            # residual consumed FIFO by SELL 4 (economic rule)


def test_symbol_spelling_mismatch_is_flagged_not_merged():                     # Review Focus 2
    t = [tr(1, "BRK.B", "BUY", 3, 400, 5)]
    r = b.consistency(t, {"brk.b": 3.0})
    assert r["consistent"] is False and {d["symbol"] for d in r["diffs"]} == {"BRK.B", "brk.b"}


def test_operational_oversell_beyond_tolerance_raises():
    with pytest.raises(b.BookError):
        b.operational_replay([tr(1, "A", "BUY", 1, 50, 5), tr(2, "A", "SELL", 1.01, 55, 6)])


def test_orphan_sell_raises_in_economic_books():
    with pytest.raises(b.BookError):
        b.economic_lots([tr(1, "A", "SELL", 0.0000005, 55, 6)], b.rows([tr(1, "A", "SELL", 0.0000005, 55, 6)])[0]["ts"])
```

- [ ] **Step 2: Hypothesis property** — append:

```python
from hypothesis import given, settings, strategies as st


@settings(max_examples=200, deadline=None)
@given(st.lists(st.tuples(st.sampled_from(["A", "B"]), st.integers(1, 5000)), min_size=1, max_size=12),
       st.data())
def test_prop_operational_replay_matches_a_hand_model(buys, data):
    """Independent hand model of the app rule: per symbol, subtract, then zero if < 0.001."""
    t, i, held = [], 0, {}
    for sym, q in buys:
        i += 1; t.append(tr(i, sym, "BUY", q / 100, 10, 5)); held[sym] = held.get(sym, 0) + q / 100
        if data.draw(st.booleans()):
            s_q = data.draw(st.integers(1, int(held[sym] * 100))) / 100
            i += 1; t.append(tr(i, sym, "SELL", s_q, 11, 6))
            held[sym] -= s_q
            if held[sym] < 0.001:
                held[sym] = 0.0
    got = b.operational_replay(t)["qty"]
    assert set(got) <= set(held) and all(got.get(k, 0.0) == pytest.approx(v, abs=1e-9) for k, v in held.items())
```

- [ ] **Step 3: RED** — `testenv/Scripts/python.exe -m pytest s1_tests/test_s1_books.py -q -p no:cacheprovider 2>&1 | tee s1_evidence/t2_red.txt`.

- [ ] **Step 4: Implement** — `s1_books.py`

```python
"""S1-QUANTITY / S1-SOLD (§7–8). Operational quantity book (app write-off rule at each SELL) for internal
consistency; economic FIFO = pinned E1 core baseline_lots, unchanged; sold events per the registered FIFO-lot
convention (first SELL allocation leaving the lot < 0.001, absorbing)."""
import s1_common as c


class BookError(Exception):
    pass


def rows(trades) -> list:
    out = [{"id": t["id"], "symbol": t["symbol"], "action": t["action"], "shares": t["shares"],
            "price": t["price"], "ts": c.aware(t["ts"])} for t in trades]
    return sorted(out, key=lambda r: (r["ts"], r["id"]))


def operational_replay(trades) -> dict:
    qty, writeoffs = {}, []
    for r in rows(trades):
        s = r["symbol"]
        if r["action"] == "BUY":
            qty[s] = qty.get(s, 0.0) + float(r["shares"])
        elif r["action"] == "SELL":
            q = qty.get(s, 0.0) - float(r["shares"])
            if q < -1e-6:
                raise BookError(f"operational oversell at trade {r['id']} ({s}): {q}")
            if q < c.SOLD_LT:
                if q != 0.0:
                    writeoffs.append({"id": r["id"], "symbol": s, "qty": q})
                q = 0.0
            qty[s] = q
        else:
            raise BookError(f"unknown action {r['action']!r} at trade {r['id']}")
    return {"qty": {s: q for s, q in qty.items() if q != 0.0}, "writeoffs": writeoffs}


def consistency(trades, portfolios) -> dict:
    rep = operational_replay(trades)["qty"]
    diffs = [{"symbol": s, "replay": rep.get(s, 0.0), "portfolio": float(portfolios.get(s, 0.0))}
             for s in sorted(set(rep) | set(portfolios))
             if abs(rep.get(s, 0.0) - float(portfolios.get(s, 0.0))) > c.CONSIST_TOL]
    return {"consistent": not diffs, "diffs": diffs}


def economic_lots(trades, endpoint) -> list:
    orphans = []
    try:
        lots = c.sim().baseline_lots(rows(trades), endpoint=endpoint, splits=[], orphans=orphans)
    except ValueError as e:
        raise BookError(str(e))
    if orphans:
        raise BookError(f"orphan SELL(s) with no open lot: {[o['id'] for o in orphans]}")
    return lots


def sold_events(trades) -> dict:
    """Prefix replay of the economic FIFO: at each SELL, a lot that received an allocation from THIS SELL and is
    left with < SOLD_LT is fully sold (first time only)."""
    rs, sim, events, prev_fills = rows(trades), c.sim(), {}, {}
    limit = sim.x(c.SOLD_LT)
    for i, r in enumerate(rs):
        if r["action"] != "SELL":
            continue
        lots = sim.baseline_lots(rs[: i + 1], endpoint=r["ts"], splits=[])
        for l in lots:
            n = len(l["fills"])
            if n > prev_fills.get(l["id"], 0) and l["rem_qty"] < limit and l["id"] not in events:
                events[l["id"]] = {"sold_at": r["ts"].isoformat(), "sell_id": r["id"]}
            prev_fills[l["id"]] = n
    return events


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
```

- [ ] **Step 5: GREEN** → `s1_evidence/t2_green.txt`; Expected: all pass.
- [ ] **Step 6: Record evidence** — hashes to `s1_evidence/t2_hashes.txt`.

---

### Task 3: Seals, fences, bridge rows, deadline and stop (R-PLAN, R-SEAL, R-STOP, R-TIME, Review Focus 1, 3, 5)

**Files:** Create `s1_seal.py`, `s1_tests/test_s1_seal.py`

**Interfaces:**
- Consumes: Task 1 projection; Task 2 `consistency`, `sold_events`; `s1_common.sim().close_instant`.
- Produces: `open_instant(day)->datetime`; `schedule(day, calendar)->list[datetime]`;
  `window_end(day, calendar)->datetime`; `choose_seal(day, calendar, captures)->dict|None` (captures:
  `[{"scheduled": iso, "actual": iso, "ok": bool, "consistent": bool, "projection_sha256", "dir"}]`);
  `fence(projection)->{id: row_hash}`; `check_fences(prior_seals, projection)->list[str]` (violations; prior
  seal = `{"close": iso, "fence": {...}, "max_id": int}`); `split_bridge(trades, start)->(bridge, cohort_era)`;
  `deadline(start: datetime)->date`; `cohort(trades, start, close)->list`; `count_sold(trades, start, close)->int`;
  `stop_decision(seals, start, calendar)->dict` (`{"status": "RUNNING"|"STOPPED"|"TIMEOUT"|"NO-VALID-SEAL",
  "stop_close": iso|None, "missed": [...]}`); `SCHEDULE_SLACK = timedelta(minutes=10)`.

- [ ] **Step 1: Write the failing tests** — `s1_tests/test_s1_seal.py` (calendar fixture: weekdays Oct–Dec 2026
  with 2026-11-26 holiday and 2026-11-27 early close 13:00)

```python
from datetime import date, datetime, timedelta, timezone

import pytest
import s1_seal as z
from test_s1_books import tr

UTC = timezone.utc


def cal():
    out, d = [], date(2026, 10, 1)
    while d <= date(2027, 6, 30):
        if d.weekday() < 5 and d.isoformat() not in ("2026-11-26", "2026-12-25", "2027-01-01", "2027-05-31"):
            out.append({"date": d.isoformat(), "open": "09:30",
                        "close": "13:00" if d.isoformat() == "2026-11-27" else "16:00"})
        d += timedelta(days=1)
    return out


CAL = cal()
DAY = next(d for d in CAL if d["date"] == "2026-10-15")


def test_schedule_is_fixed_offsets_then_hourly_to_0800_next_session():
    s = z.schedule(DAY, CAL)
    close = datetime(2026, 10, 15, 20, 0, tzinfo=UTC)                      # 16:00 EDT
    assert s[:6] == [close + timedelta(minutes=m) for m in (45, 47, 49, 51, 53, 55)]
    assert s[6] == datetime(2026, 10, 15, 21, 0, tzinfo=UTC) and s[-1] == datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
    assert all(b > a for a, b in zip(s, s[1:]))


def cap(minute_offset, ok=True, consistent=True, late=0):
    close = datetime(2026, 10, 15, 20, 0, tzinfo=UTC)
    sch = close + timedelta(minutes=minute_offset)
    return {"scheduled": sch.isoformat(), "actual": (sch + timedelta(minutes=late)).isoformat(), "ok": ok,
            "consistent": consistent, "projection_sha256": "h", "dir": "d"}


def test_capture_between_trade_and_portfolio_commit_is_inconsistent_and_retried():    # example 1
    s = z.choose_seal(DAY, CAL, [cap(45, consistent=False), cap(47, consistent=True)])
    assert s["scheduled"] == cap(47)["scheduled"]


def test_late_capture_outside_the_registered_slot_cannot_seal():                     # Review Focus 3
    assert z.choose_seal(DAY, CAL, [cap(45, late=180)]) is None


def test_no_consistent_capture_means_unsealed():
    assert z.choose_seal(DAY, CAL, [cap(45, consistent=False), cap(47, ok=False)]) is None


def test_trade_stored_after_close_excluded_from_as_of_rows():                          # example 2
    t = [tr(1, "A", "BUY", 10, 50, 5), {**tr(2, "A", "SELL", 10, 55, 5), "ts": "2026-10-15T20:30:00+00:00"}]
    start = datetime(2026, 10, 14, 13, 30, tzinfo=UTC)
    assert z.count_sold(t, start, datetime(2026, 10, 15, 20, 0, tzinfo=UTC)) == 0


def test_backdated_row_invalidates():                                                   # example 7
    p1 = {"trades": [tr(1, "A", "BUY", 10, 50, 5)]}
    seals = [{"close": "2026-10-15T20:00:00+00:00", "fence": z.fence(p1), "max_id": 1}]
    p2 = {"trades": p1["trades"] + [{**tr(2, "A", "SELL", 1, 55, 5), "ts": "2026-10-15T19:00:00+00:00"}]}
    assert any("backdated" in v for v in z.check_fences(seals, p2))
    p3 = {"trades": [{**p1["trades"][0], "shares": 9}]}
    assert any("changed" in v for v in z.check_fences(seals, p3))
    assert any("deleted" in v for v in z.check_fences(seals, {"trades": []}))


def test_executed_before_start_stored_after_is_cohort():                                # example 8
    start = datetime(2026, 10, 14, 13, 30, tzinfo=UTC)
    t = [{**tr(1, "A", "BUY", 1, 50), "ts": "2026-10-14T13:30:00.200000+00:00"}]
    assert [r["id"] for r in z.cohort(t, start, datetime(2026, 10, 15, 20, 0, tzinfo=UTC))] == [1]


def test_two_utc_spellings_give_the_same_cohort():                                      # Review Focus 1
    start = datetime(2026, 10, 14, 13, 30, tzinfo=UTC)
    a = [{**tr(1, "A", "BUY", 1, 50), "ts": "2026-10-14T13:30:00Z"}]
    b = [{**tr(1, "A", "BUY", 1, 50), "ts": "2026-10-14T13:30:00+00:00"}]
    c_ = datetime(2026, 10, 15, 20, 0, tzinfo=UTC)
    assert z.cohort(a, start, c_) == z.cohort(b, start, c_)


def test_bridge_rows_update_opening_books_not_cohort():                                 # example 19
    start = datetime(2026, 10, 16, 13, 30, tzinfo=UTC)
    t = [tr(1, "A", "BUY", 10, 50, 5), {**tr(2, "NEW", "BUY", 5, 20), "ts": "2026-10-16T00:00:00+00:00"},
         {**tr(3, "A", "SELL", 4, 51), "ts": "2026-10-16T00:00:00+00:00"}]
    bridge, era = z.split_bridge(t, start)
    assert [r["id"] for r in bridge] == [1, 2, 3] and era == []


def _seal(day_iso, trades):
    return {"close": z.close_of(day_iso, CAL).isoformat(), "fence": {}, "max_id": 0, "trades": trades}


def test_overshoot_stops_with_all_entries():                                            # example 13
    start = datetime(2026, 10, 14, 13, 30, tzinfo=UTC)
    t = []
    for i in range(103):
        t += [{**tr(2 * i + 1, f"S{i}", "BUY", 1, 10), "ts": "2026-10-14T15:00:00+00:00"},
              {**tr(2 * i + 2, f"S{i}", "SELL", 1, 11), "ts": "2026-10-15T15:00:00+00:00"}]
    t.append({**tr(999, "OPEN", "BUY", 1, 10), "ts": "2026-10-15T15:30:00+00:00"})
    d = z.stop_decision([_seal("2026-10-14", t[:0]), _seal("2026-10-15", t)], start, CAL)
    assert d["status"] == "STOPPED" and d["stop_close"] == z.close_of("2026-10-15", CAL).isoformat()
    assert len(z.cohort(t, start, z.close_of("2026-10-15", CAL))) == 104


def test_unsealed_qualifying_close_is_not_the_stop():                                   # example 14
    start = datetime(2026, 10, 14, 13, 30, tzinfo=UTC)
    t = []
    for i in range(100):
        t += [{**tr(2 * i + 1, f"S{i}", "BUY", 1, 10), "ts": "2026-10-14T15:00:00+00:00"},
              {**tr(2 * i + 2, f"S{i}", "SELL", 1, 11), "ts": "2026-10-15T15:00:00+00:00"}]
    d = z.stop_decision([_seal("2026-10-16", t)], start, CAL)              # 10-15 unsealed
    assert d["stop_close"] == z.close_of("2026-10-16", CAL).isoformat()
    assert "2026-10-15" in d["missed"]


@pytest.mark.parametrize("start,want", [(datetime(2026, 8, 31, 13, 30, tzinfo=UTC), date(2027, 2, 28)),
                                        (datetime(2026, 10, 14, 13, 30, tzinfo=UTC), date(2027, 4, 14))])
def test_deadline_calendar_months_with_month_end(start, want):
    assert z.deadline(start) == want


def test_deadline_holiday_month_end_and_no_valid_seal():                                # example 15
    start = datetime(2026, 11, 2, 14, 30, tzinfo=UTC)
    cal_short = [d for d in CAL if d["date"] <= "2027-05-31"]
    d = z.stop_decision([], start, cal_short, today=datetime(2027, 6, 1, 12, tzinfo=UTC))
    assert d["status"] == "NO-VALID-SEAL"
    few = [_seal("2026-11-02", [])]
    d = z.stop_decision(few, start, cal_short, today=datetime(2027, 6, 1, 12, tzinfo=UTC))
    assert d["status"] == "TIMEOUT" and d["stop_close"] == z.close_of("2026-11-02", CAL).isoformat()


def test_no_trades_for_weeks_keeps_running():                                           # Review Focus 5
    start = datetime(2026, 10, 14, 13, 30, tzinfo=UTC)
    d = z.stop_decision([_seal("2026-10-15", []), _seal("2026-10-16", [])], start, CAL,
                        today=datetime(2026, 10, 17, 12, tzinfo=UTC))
    assert d["status"] == "RUNNING"
```

- [ ] **Step 2: Hypothesis property** — append:

```python
from hypothesis import given, settings, strategies as st


@settings(max_examples=300, deadline=None)
@given(st.dates(min_value=date(2026, 1, 1), max_value=date(2030, 12, 31)))
def test_prop_deadline_is_six_calendar_months_clamped(d):
    got = z.deadline(datetime(d.year, d.month, d.day, 14, tzinfo=UTC))
    m = d.month + 6
    y, m = d.year + (m - 1) // 12, (m - 1) % 12 + 1
    import calendar as pycal
    assert got == date(y, m, min(d.day, pycal.monthrange(y, m)[1]))
```

- [ ] **Step 3: RED** — `testenv/Scripts/python.exe -m pytest s1_tests/test_s1_seal.py -q -p no:cacheprovider 2>&1 | tee s1_evidence/t3_red.txt`.

- [ ] **Step 4: Implement** — `s1_seal.py`

```python
"""S1-SEALS / S1-STOP / S1-PLAN timing (§4, §6, §9). Deterministic capture schedule per pinned close, seal = first
consistent capture taken within SCHEDULE_SLACK of a registered slot, row fences, backdating, bridge split, calendar-
month deadline, stop decision over SEALED closes only."""
import calendar as pycal
from datetime import date, datetime, time, timedelta, timezone

import s1_books as b
import s1_common as c

OFFSETS_MIN = (45, 47, 49, 51, 53, 55)
SCHEDULE_SLACK = timedelta(minutes=10)
STOP_N = 100


def _ny(d: str, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime.combine(date.fromisoformat(d), time(h, m), tzinfo=c.NY).astimezone(timezone.utc)


def open_instant(day) -> datetime:
    return _ny(day["date"], day["open"])


def close_of(day_iso: str, calendar) -> datetime:
    return c.sim().close_instant(next(d for d in calendar if d["date"] == day_iso))


def _next_session(day, calendar):
    later = [d for d in calendar if d["date"] > day["date"]]
    if not later:
        raise ValueError(f"calendar ends at {day['date']}: cannot schedule its seal window")
    return later[0]


def window_end(day, calendar) -> datetime:
    return _ny(_next_session(day, calendar)["date"], "08:00")


def schedule(day, calendar) -> list:
    close = c.sim().close_instant(day)
    slots = [close + timedelta(minutes=m) for m in OFFSETS_MIN]
    t = (slots[-1] + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    end = window_end(day, calendar)
    while t <= end:
        slots.append(t)
        t += timedelta(hours=1)
    return slots


def choose_seal(day, calendar, captures):
    slots = set(schedule(day, calendar))
    for cap in sorted(captures, key=lambda k: c.aware(k["actual"])):
        sch, act = c.aware(cap["scheduled"]), c.aware(cap["actual"])
        if sch in slots and sch <= act <= sch + SCHEDULE_SLACK and cap["ok"] and cap["consistent"]:
            return cap
    return None


def _row_hash(t) -> str:
    return c.sha256_bytes(c.canonical({k: t[k] for k in ("id", "symbol", "action", "shares", "price", "timestamp",
                                                           "reasoning_sha256")}))


def fence(projection) -> dict:
    return {t["id"]: _row_hash(t) for t in projection["trades"]}


def check_fences(prior_seals, projection) -> list:
    now = {t["id"]: t for t in projection["trades"]}
    seen = set().union(*[set(s["fence"]) for s in prior_seals]) if prior_seals else set()
    max_seen = max((s["max_id"] for s in prior_seals), default=0)
    out = []
    for s in prior_seals:
        for i, h in s["fence"].items():
            i = int(i)
            if i not in now:
                out.append(f"sealed row {i} deleted")
            elif _row_hash(now[i]) != h:
                out.append(f"sealed row {i} changed")
    for i, t in now.items():
        if i in seen or str(i) in {str(x) for x in seen}:
            continue
        if i < max_seen:
            out.append(f"new id {i} below previous max {max_seen}")
        for s in prior_seals:
            if c.aware(t["ts"]) <= c.aware(s["close"]):
                out.append(f"row {i} backdated to <= sealed close {s['close']}")
                break
    return out


def split_bridge(trades, start: datetime):
    rs = sorted(trades, key=lambda t: (c.aware(t["ts"]), t["id"]))
    return [t for t in rs if c.aware(t["ts"]) < start], [t for t in rs if c.aware(t["ts"]) >= start]


def cohort(trades, start: datetime, close: datetime) -> list:
    return [t for t in trades if t["action"] == "BUY" and start <= c.aware(t["ts"]) <= close]


def count_sold(trades, start: datetime, close: datetime) -> int:
    asof = [t for t in trades if c.aware(t["ts"]) <= close]
    ids = {t["id"] for t in cohort(asof, start, close)}
    return sum(1 for lid in b.sold_events(asof) if lid in ids)


def deadline(start: datetime) -> date:
    d = start.astimezone(c.NY).date()
    m = d.month + 6
    y, m = d.year + (m - 1) // 12, (m - 1) % 12 + 1
    return date(y, m, min(d.day, pycal.monthrange(y, m)[1]))


def stop_decision(seals, start: datetime, calendar, today: datetime = None) -> dict:
    """seals: [{"close": iso, "trades": projection trades of that seal, ...}] — the seal is authoritative."""
    today = today or c.now_utc()
    dl = deadline(start).isoformat()
    by_close = {s["close"]: s for s in seals}
    eligible = [d for d in calendar if open_instant(d) >= start and d["date"] <= dl]
    missed = []
    for d in eligible:
        close = c.sim().close_instant(d)
        if close > today:
            break
        s = by_close.get(close.isoformat())
        if s is None:
            if window_end(d, calendar) < today:
                missed.append(d["date"])
            continue
        if count_sold(s["trades"], start, close) >= STOP_N:
            return {"status": "STOPPED", "stop_close": close.isoformat(), "missed": missed}
    last = eligible[-1] if eligible else None
    if last is None or window_end(last, calendar) >= today:
        return {"status": "RUNNING", "stop_close": None, "missed": missed}
    sealed = [c.sim().close_instant(d) for d in eligible if c.sim().close_instant(d).isoformat() in by_close]
    if not sealed:
        return {"status": "NO-VALID-SEAL", "stop_close": None, "missed": missed}
    return {"status": "TIMEOUT", "stop_close": max(sealed).isoformat(), "missed": missed}
```

- [ ] **Step 5: GREEN** → `s1_evidence/t3_green.txt`; Expected: all pass.
- [ ] **Step 6: Record evidence** — hashes to `s1_evidence/t3_hashes.txt`.

---

### Task 4: Receipt — semantic receipt, process identity, crash.log restarts (R-EPOCH)

**Files:** Create `s1_receipt.py`, `s1_tests/test_s1_receipt.py`

**Interfaces:**
- Produces: `closure(backend: Path, roots: list[str]) -> list[str]` (sorted relative paths of in-repo modules
  reachable by AST imports); `semantic_receipt(repo: Path, env_file: Path, runtime_python: Path) -> dict`
  (`{"head", "dirty", "files": {path: sha}, "config": {key: sha_of_value}, "versions": {...}}`);
  `restart_record(crash_log: Path) -> {"starts": [{"ts", "pid"}], "size", "sha256"}`;
  `restart_gaps(prev_obs, obs) -> list[str]` (obs = `{"pid", "process_start", "record": restart_record}`);
  `MR_ROOTS` (list of backend-relative files from §12).

- [ ] **Step 1: Write the failing tests**

```python
import subprocess
from pathlib import Path

import s1_receipt as r


def repo(tmp_path):
    be = tmp_path / "backend"
    (be / "agents").mkdir(parents=True)
    (be / "agents" / "mean_reversion_agent.py").write_text("from agents.base_agent import B\nimport config\n")
    (be / "agents" / "base_agent.py").write_text("from trading.portfolio import P\nimport numpy\n")
    (be / "trading").mkdir()
    (be / "trading" / "portfolio.py").write_text("X = 1\n")
    (be / "config.py").write_text("import os\nMR_SELL_ZSCORE = float(os.getenv('MR_SELL_ZSCORE', '1.5'))\n"
                                  "API = os.getenv('FRED_API_KEY')\n")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"],
                   check=True)
    return tmp_path


def test_closure_follows_in_repo_imports_only(tmp_path):
    root = repo(tmp_path)
    got = r.closure(root / "backend", ["agents/mean_reversion_agent.py"])
    assert got == ["agents/base_agent.py", "agents/mean_reversion_agent.py", "config.py", "trading/portfolio.py"]


def test_receipt_changes_with_code_or_mr_config_but_not_secrets(tmp_path):
    root = repo(tmp_path)
    env = tmp_path / ".env"
    env.write_text("MR_SELL_ZSCORE=1.5\nFRED_API_KEY=abc12345\n")
    a = r.semantic_receipt(root, env, None, roots=["agents/mean_reversion_agent.py"])
    env.write_text("MR_SELL_ZSCORE=1.5\nFRED_API_KEY=zzz99999\n")
    assert r.semantic_receipt(root, env, None, roots=["agents/mean_reversion_agent.py"]) == a
    env.write_text("MR_SELL_ZSCORE=2.0\nFRED_API_KEY=zzz99999\n")
    assert r.semantic_receipt(root, env, None, roots=["agents/mean_reversion_agent.py"]) != a
    assert "abc12345" not in str(a) and "FRED_API_KEY" not in a["config"]


def test_restart_record_parses_process_start_lines(tmp_path):
    log = tmp_path / "crash.log"
    log.write_text("2026-10-12 23:17:37 [PROCESS START] pid=38508\nnoise\n2026-10-20 08:00:01 [PROCESS START] pid=11\n")
    rec = r.restart_record(log)
    assert [s["pid"] for s in rec["starts"]] == [38508, 11] and rec["size"] == log.stat().st_size


def test_pid_change_without_process_start_line_is_gap(tmp_path):                         # example 11
    log = tmp_path / "crash.log"
    log.write_text("2026-10-12 23:17:37 [PROCESS START] pid=1\n")
    o1 = {"pid": 1, "process_start": "2026-10-12T23:17:25", "record": r.restart_record(log)}
    o2 = {"pid": 2, "process_start": "2026-10-21T09:00:00", "record": r.restart_record(log)}
    assert any("without a PROCESS START" in g for g in r.restart_gaps(o1, o2))
    log.write_text("")                                                                    # truncated
    o3 = {"pid": 2, "process_start": "2026-10-21T09:00:00", "record": r.restart_record(log)}
    assert any("truncated" in g for g in r.restart_gaps(o2, o3))
```

- [ ] **Step 2: RED** → `s1_evidence/t4_red.txt`.

- [ ] **Step 3: Implement** — `s1_receipt.py`

```python
"""S1-EPOCH (§12): semantic receipt (compared at every seal), process identity and the app's own crash.log
[PROCESS START] restart record (observed minimum; gaps reported). Read-only: git, files, the OS process table."""
import ast
import json
import re
import subprocess
from pathlib import Path

import s1_common as c

MR_ROOTS = ["agents/mean_reversion_agent.py", "agents/base_agent.py", "trading/portfolio.py",
            "trading/risk_manager.py", "loops/trading_loop.py", "lifespan.py", "database.py", "config.py",
            "logging_setup.py"]
SECRET = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD)", re.I)
START_LINE = re.compile(r"^(\S+ \S+) \[PROCESS START\] pid=(\d+)")


def _module_file(backend: Path, name: str):
    p = backend.joinpath(*name.split("."))
    for cand in (p.with_suffix(".py"), p / "__init__.py"):
        if cand.exists():
            return cand
    if name.startswith("backend."):
        return _module_file(backend, name[len("backend."):])
    return None


def closure(backend: Path, roots) -> list:
    seen, todo = set(), [backend / r for r in roots if (backend / r).exists()]
    while todo:
        f = todo.pop()
        rel = f.relative_to(backend).as_posix()
        if rel in seen:
            continue
        seen.add(rel)
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            for n in names:
                m = _module_file(backend, n)
                if m is not None:
                    todo.append(m)
    return sorted(seen)


def _config_keys(config_py: Path) -> list:
    keys = set()
    for node in ast.walk(ast.parse(config_py.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", "")) in ("getenv", "get") \
                and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            keys.add(node.args[0].value)
    return sorted(k for k in keys if not SECRET.search(k))


def _env(env_file: Path) -> dict:
    out = {}
    if env_file and Path(env_file).exists():
        for line in Path(env_file).read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def semantic_receipt(repo: Path, env_file: Path, runtime_python, roots=None) -> dict:
    backend = Path(repo) / "backend"
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()
    dirty = sorted(l[3:] for l in subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                                                  capture_output=True, text=True, check=True).stdout.splitlines()
                   if l[3:].startswith("backend/") and l[3:].endswith(".py"))
    files = {p: c.sha256_file(backend / p) for p in closure(backend, roots or MR_ROOTS)}
    env = _env(env_file)
    config = {k: c.sha256_bytes(env[k].encode()) for k in _config_keys(backend / "config.py") if k in env}
    versions = {}
    if runtime_python:
        versions = json.loads(subprocess.run(
            [str(runtime_python), "-I", "-c", "import sys,json,importlib.metadata as m;"
             "print(json.dumps({'python':sys.version.split()[0],"
             "'packages':{d.metadata['Name'].lower():d.version for d in m.distributions()}}))"],
            capture_output=True, text=True, check=True).stdout)
    return {"head": head, "dirty": dirty, "files": files, "config": config, "versions": versions}


def restart_record(crash_log: Path) -> dict:
    p = Path(crash_log)
    if not p.exists():
        return {"starts": [], "size": None, "sha256": None}
    data = p.read_bytes()
    starts = []
    for line in data.decode("utf-8", errors="replace").splitlines():
        m = START_LINE.match(line)
        if m:
            starts.append({"ts": m.group(1), "pid": int(m.group(2))})
    uniq = [s for i, s in enumerate(starts) if s not in starts[:i]]        # the app writes the line twice
    return {"starts": uniq, "size": len(data), "sha256": c.sha256_bytes(data)}


def restart_gaps(prev, obs) -> list:
    gaps = []
    pr, nr = prev["record"], obs["record"]
    if pr["size"] is not None and (nr["size"] is None or nr["size"] < pr["size"]):
        gaps.append("crash.log truncated, rotated or deleted")
    new_pids = {s["pid"] for s in nr["starts"]} - {s["pid"] for s in pr["starts"]}
    if obs["pid"] != prev["pid"] and obs["pid"] not in new_pids:
        gaps.append(f"pid {prev['pid']} -> {obs['pid']} without a PROCESS START line")
    return gaps


def process_identity(port: int = 8000) -> dict:
    ps = ("$c = Get-NetTCPConnection -LocalPort %d -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1;"
          " if ($c) { $p = Get-Process -Id $c.OwningProcess; "
          "'{\"pid\":' + $p.Id + ',\"process_start\":\"' + $p.StartTime.ToString('s') + '\"}' } else { '{}' }") % port
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout.strip()
    return json.loads(out or "{}")
```

- [ ] **Step 4: GREEN** → `s1_evidence/t4_green.txt`.
- [ ] **Step 5: Record evidence** — hashes to `s1_evidence/t4_hashes.txt`.

---

### Task 5: Checkpoint — the counts-only scheduled command (R-COUNT, R-SEAL, R-EPOCH)

**Files:** Create `s1_checkpoint.py`, `s1_tests/test_s1_checkpoint.py`

**Interfaces:**
- Consumes: Tasks 1–4. Reads `s1_out/prereg.json` (START, calendar, receipt — written by Task 7) and prior
  seals from `s1_out/seals/*.json`.
- Produces: `run_checkpoint(root: Path, live_db: Path, scheduled: datetime, receipt_fn, process_fn,
  crash_log: Path) -> dict` writing `s1_out/captures/<close>/<scheduled>/{meta,projection}.json` and, when it
  seals, `s1_out/seals/<close>.json`. Report keys are ONLY: `close, scheduled, actual, capture_ok, consistent,
  fence_violations, receipt_match, pid, process_start, restart_gaps, entries, sold, stop`, plus
  `"exclusions": "not evaluated", "market_coverage": "not evaluated"`. CLI: `python s1_checkpoint.py
  --scheduled <iso>` (close derived from the pinned calendar).

- [ ] **Step 1: Write the failing tests** (uses a synthetic prereg written by a helper `make_prereg(root,
  start, calendar, receipt)` defined in the test module)

```python
import ast
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import s1_checkpoint as k
from test_s1_seal import CAL

UTC = timezone.utc
START = datetime(2026, 10, 14, 13, 30, tzinfo=UTC)
REC = {"head": "h", "dirty": [], "files": {"a.py": "1"}, "config": {}, "versions": {}}


def make_prereg(root, receipt=REC):
    (root / "s1_out").mkdir(parents=True, exist_ok=True)
    (root / "s1_out" / "prereg.json").write_text(json.dumps({"start": START.isoformat(), "calendar": CAL,
                                                             "receipt": receipt}), encoding="utf-8")


def run(root, ledger, minutes=45, receipt=REC, pid=1, log=None):
    sch = datetime(2026, 10, 15, 20, 0, tzinfo=UTC).timestamp() + minutes * 60
    return k.run_checkpoint(root, ledger.path, datetime.fromtimestamp(sch, UTC), lambda: receipt,
                            lambda: {"pid": pid, "process_start": "2026-10-12T23:17:25"}, log or root / "crash.log",
                            now=lambda: datetime.fromtimestamp(sch + 30, UTC))


def test_counts_only_report_and_seal(tmp_path, ledger):
    make_prereg(tmp_path)
    ledger.trade("A", "BUY", 10, 50, "2026-10-14T15:00:00+00:00"); ledger.set_portfolio("A", 10)
    rep = run(tmp_path, ledger)
    assert rep["consistent"] and rep["entries"] == 1 and rep["sold"] == 0 and rep["receipt_match"]
    assert set(rep) <= {"close", "scheduled", "actual", "capture_ok", "consistent", "fence_violations",
                        "receipt_match", "pid", "process_start", "restart_gaps", "entries", "sold", "stop",
                        "exclusions", "market_coverage"}
    assert (tmp_path / "s1_out" / "seals" / "2026-10-15.json").exists()
    assert "price" not in json.dumps(rep) and "pnl" not in json.dumps(rep).lower()


def test_restart_recorded_and_source_change_invalidates(tmp_path, ledger):               # example 10
    make_prereg(tmp_path)
    (tmp_path / "crash.log").write_text("2026-10-15 08:00:00 [PROCESS START] pid=2\n")
    rep = run(tmp_path, ledger, pid=2)
    assert rep["receipt_match"] and rep["restart_gaps"] == []
    bad = dict(REC, files={"a.py": "2"})
    rep = run(tmp_path, ledger, minutes=47, receipt=bad, pid=2)
    assert rep["receipt_match"] is False and rep["stop"]["status"] == "ABORTED-INVALID"


def test_checkpoint_cannot_reach_economics_or_prices(tmp_path, ledger, monkeypatch):      # example 17
    src = Path(k.__file__).read_text(encoding="utf-8")
    imported = {n.names[0].name for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Import)} | \
               {n.module for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)}
    assert not imported & {"s1_run", "s1_collect", "httpx", "e1_fetch"}
    import s1_common
    sim = s1_common.sim()
    for name in ("simulate_lot", "lot_economics", "baseline_economics", "compare", "paired_bootstrap", "verdict"):
        monkeypatch.setattr(sim, name, lambda *a, **kw: pytest.fail("economics reached from checkpoint"))
    make_prereg(tmp_path)
    ledger.trade("A", "BUY", 10, 50, "2026-10-14T15:00:00+00:00"); ledger.set_portfolio("A", 10)
    run(tmp_path, ledger)


def test_inconsistent_capture_does_not_seal_and_is_preserved(tmp_path, ledger):
    make_prereg(tmp_path)
    ledger.trade("A", "BUY", 10, 50, "2026-10-14T15:00:00+00:00")                       # portfolio not yet upserted
    rep = run(tmp_path, ledger)
    assert rep["consistent"] is False and not (tmp_path / "s1_out" / "seals" / "2026-10-15.json").exists()
    assert list((tmp_path / "s1_out" / "captures" / "2026-10-15").iterdir())
```

- [ ] **Step 2: RED** → `s1_evidence/t5_red.txt`.

- [ ] **Step 3: Implement** — `s1_checkpoint.py`

```python
"""S1-COUNTS (§10): the scheduled read-only checkpoint. Counts and integrity only — never prices, PnL, exit levels,
candidate paths or comparisons. Imports only snapshot/books/seal/receipt/common."""
import argparse
import json
from datetime import datetime
from pathlib import Path

import s1_books as b
import s1_common as c
import s1_receipt as r
import s1_seal as z
import s1_snapshot as s

LIVE_DB = Path("C:/Users/gl450/trading_app/backend/trading.db")
REPO = Path("C:/Users/gl450/trading_app")
CRASH_LOG = REPO / "backend" / "logs" / "crash.log"


def _close_for(scheduled: datetime, calendar):
    for d in calendar:
        if scheduled in z.schedule(d, calendar):
            return d
    raise SystemExit(f"{scheduled.isoformat()} is not a registered seal slot")


def _seals(out: Path) -> list:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((out / "seals").glob("*.json"))]


def run_checkpoint(root, live_db, scheduled, receipt_fn, process_fn, crash_log, now=c.now_utc) -> dict:
    out = Path(root) / "s1_out"
    pr = json.loads((out / "prereg.json").read_text(encoding="utf-8"))
    start, cal = c.aware(pr["start"]), pr["calendar"]
    day = _close_for(scheduled, cal)
    close = c.sim().close_instant(day)
    cap_dir = out / "captures" / day["date"] / scheduled.strftime("%Y%m%dT%H%M%SZ")
    meta = s.take_snapshot(live_db, cap_dir)
    actual = now()
    rep = {"close": close.isoformat(), "scheduled": scheduled.isoformat(), "actual": actual.isoformat(),
           "capture_ok": meta["ok"], "consistent": False, "fence_violations": [], "receipt_match": None,
           "pid": None, "process_start": None, "restart_gaps": [], "entries": None, "sold": None,
           "stop": None, "exclusions": "not evaluated", "market_coverage": "not evaluated"}
    proc = process_fn()
    rec = r.restart_record(crash_log)
    rep.update(pid=proc.get("pid"), process_start=proc.get("process_start"))
    prev_obs = out / "last_process.json"
    if prev_obs.exists():
        rep["restart_gaps"] = r.restart_gaps(json.loads(prev_obs.read_text(encoding="utf-8")), {**proc, "record": rec})
    prev_obs.write_text(json.dumps({**proc, "record": rec}), encoding="utf-8")
    rep["receipt_match"] = receipt_fn() == pr["receipt"]
    seals = _seals(out)
    if meta["ok"]:
        proj = json.loads((cap_dir / "projection.json").read_text(encoding="utf-8"))
        rep["consistent"] = b.consistency(proj["trades"], proj["portfolios"])["consistent"]
        rep["fence_violations"] = z.check_fences(seals, proj)
        rep["entries"] = len(z.cohort(proj["trades"], start, close))
        rep["sold"] = z.count_sold(proj["trades"], start, close)
        cap = {"scheduled": scheduled.isoformat(), "actual": actual.isoformat(), "ok": True,
               "consistent": rep["consistent"], "projection_sha256": meta["projection_sha256"], "dir": str(cap_dir)}
        seal_path = out / "seals" / f"{day['date']}.json"
        if not seal_path.exists() and z.choose_seal(day, cal, [cap]) and not rep["fence_violations"]:
            seal_path.parent.mkdir(parents=True, exist_ok=True)
            seal = {"close": close.isoformat(), "fence": z.fence(proj),
                    "max_id": meta["max_trade_id"], "trades": proj["trades"], "capture": cap,
                    "restart_record": rec, "process": proc}
            with seal_path.open("x", encoding="utf-8") as f:
                json.dump(seal, f)
            seals = _seals(out)
    if not rep["receipt_match"] or rep["fence_violations"]:
        rep["stop"] = {"status": "ABORTED-INVALID", "stop_close": None,
                       "reason": "semantic receipt changed" if not rep["receipt_match"] else rep["fence_violations"]}
    else:
        rep["stop"] = z.stop_decision(seals, start, cal, today=actual)
    (cap_dir.parent / f"{cap_dir.name}.report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scheduled", required=True)
    a = ap.parse_args()
    root = c.HERE
    pr = json.loads((root / "s1_out" / "prereg.json").read_text(encoding="utf-8"))
    rep = run_checkpoint(root, LIVE_DB, c.aware(a.scheduled),
                         lambda: r.semantic_receipt(REPO, REPO / ".env", REPO / "runtime" / "python" / "python.exe"),
                         r.process_identity, CRASH_LOG)
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: GREEN** → `s1_evidence/t5_green.txt`.
- [ ] **Step 5: Record evidence** — hashes to `s1_evidence/t5_hashes.txt`.

---

### Task 6: Collectors — metadata plan, opening audit, final acquisition (R-PLAN, R-UNITS, R-ACQ)

**Files:** Create `s1_collect.py`, `s1_tests/test_s1_collect.py`

**Interfaces:**
- Consumes: ONLY the pure, reviewed corporate-action functions of the pinned `e1_fetch` (sha 401f17de):
  `validate_ca_page(data, where)` and `classify_ca([(batch_symbols, page)]) -> (records, problems)`. Its `get`,
  `paged` and `parse_bars` are NOT reused: they write into e1_fetch's module-level `PAGES` folder and
  `parse_bars` hard-codes E1's date span (`BAR_PARAMS`). S1 implements its own `_get`, `_paged`, `_parse_bars`
  with the same discipline.
- Produces: `write_plan(root, planned_start: datetime, opening_close: str, symbols: list, first_trade_date: str)
  -> Path` (`s1_out/plan.json`, refuses if exists); `AUDIT_ACK = "S1-AUDIT-ACK collector_sha256={collector}
  plan_sha256={plan} start={start}"`; `ACQUIRE_ACK = "S1-ACQUIRE-ACK collector_sha256={collector}
  final_plan_sha256={plan}"`; `do_audit(root, ack_id, client, keys) -> dict` (one attempt; writes
  `s1_out/audit/{calendar.json, corporate_actions.json, ca_problems.json, manifest.json, pages/}`);
  `write_final_plan(root, stop_close, symbols, carry_in_symbols, first_trade_date) -> Path`;
  `do_final(root, ack_id, client, keys) -> dict` (one attempt; `s1_out/final/...` incl. `bars.json`).
  `client` is an `httpx.Client`; tests pass `httpx.Client(transport=httpx.MockTransport(handler))`.

- [ ] **Step 1: Write the failing tests** — plan is immutable; audit refuses without the exact standalone ACK
  line (synthetic `mailbox.sqlite3` with the E1 `messages` schema), refuses a second attempt, makes no request
  when refused (MockTransport handler counts calls), requests NO bars in the audit, requests every carry-in and
  bridge symbol in the final plan, and records pages/manifests with hashes.

```python
import json
import sqlite3
from datetime import datetime, timezone

import httpx
import pytest
import s1_collect as k

UTC = timezone.utc
START = datetime(2026, 10, 26, 13, 30, tzinfo=UTC)


def mailbox(root, mid, body):
    con = sqlite3.connect(root / "mailbox.sqlite3")
    con.execute("CREATE TABLE IF NOT EXISTS messages (id TEXT, sender TEXT, recipient TEXT, request_key TEXT, "
                "body TEXT, created REAL, acknowledged REAL)")
    con.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,NULL)", (mid, "codex", "claude", "experiments-prereg",
                                                                  body, datetime(2026, 10, 20, tzinfo=UTC).timestamp()))
    con.commit(); con.close()


def client(calls):
    def handler(req):
        calls.append(str(req.url))
        if "calendar" in str(req.url):
            return httpx.Response(200, json=[{"date": "2026-10-26", "open": "09:30", "close": "16:00"}])
        return httpx.Response(200, json={"corporate_actions": {}, "next_page_token": None})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_plan_is_written_once(tmp_path):
    k.write_plan(tmp_path, START, "2026-10-23", ["A", "B"], "2026-03-17")
    with pytest.raises(FileExistsError):
        k.write_plan(tmp_path, START, "2026-10-23", ["A"], "2026-03-17")


def test_audit_refuses_without_exact_ack_and_makes_no_request(tmp_path):
    k.write_plan(tmp_path, START, "2026-10-23", ["A"], "2026-03-17")
    mailbox(tmp_path, "m1", "approve, roughly")
    calls = []
    with pytest.raises(SystemExit):
        k.do_audit(tmp_path, "m1", client(calls), ("id", "secret"))
    assert calls == [] and not (tmp_path / "s1_out" / "audit").exists()


def test_audit_once_metadata_only(tmp_path):
    p = k.write_plan(tmp_path, START, "2026-10-23", ["A"], "2026-03-17")
    mailbox(tmp_path, "m2", k.audit_token(tmp_path))
    calls = []
    m = k.do_audit(tmp_path, "m2", client(calls), ("id", "secret"))
    assert m["outcome"] == "COMPLETE" and not any("/bars" in u for u in calls)
    with pytest.raises(SystemExit):
        k.do_audit(tmp_path, "m2", client(calls), ("id", "secret"))
    assert "secret" not in json.dumps(m)


def test_final_plan_covers_carry_in_and_bridge_symbols(tmp_path):
    p = k.write_final_plan(tmp_path, "2027-01-20T21:00:00+00:00", ["A"], ["B", "NEW"], "2026-03-17")
    plan = json.loads(p.read_text(encoding="utf-8"))
    assert plan["bar_symbols"] == ["A", "B", "NEW"] and plan["ca_symbols_full_history"] == ["B", "NEW"]
```

- [ ] **Step 2: RED** → `s1_evidence/t6_red.txt`.

- [ ] **Step 3: Implement** — `s1_collect.py` (follows E1 collector discipline: exclusive writes, raw pages
  kept, manifest of hashes, one attempt file, keys read from `C:\Users\gl450\trading_app\.env` by the caller and
  never written; `paged`/`get`/`classify_ca` from the pinned e1_fetch)

```python
"""S1 collectors (§4, §11, §13): metadata plan with planned START; opening audit (calendar + corporate actions,
NO prices) under S1-AUDIT-ACK; final acquisition (bars + corporate actions) under S1-ACQUIRE-ACK. One attempt each.
Network helpers come from the hash-pinned E1 collector."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import s1_common as c

CAL_URL = "https://paper-api.alpaca.markets/v2/calendar"
BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"
CA_URL = "https://data.alpaca.markets/v1/corporate-actions"
AUDIT_ACK = "S1-AUDIT-ACK collector_sha256={collector} plan_sha256={plan} start={start}"
ACQUIRE_ACK = "S1-ACQUIRE-ACK collector_sha256={collector} final_plan_sha256={plan}"


def _out(root):
    return Path(root) / "s1_out"


def collector_sha() -> str:
    return c.sha256_file(Path(__file__).resolve())


def _write_once(path: Path, obj) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as f:
        f.write(json.dumps(obj, indent=1, sort_keys=True))
    return path


def write_plan(root, planned_start: datetime, opening_close: str, symbols, first_trade_date: str) -> Path:
    dl = (planned_start + timedelta(days=200)).date().isoformat()          # covers deadline + 3 sessions
    return _write_once(_out(root) / "plan.json", {
        "planned_start": planned_start.isoformat(), "opening_close": opening_close,
        "calendar_range": [planned_start.date().isoformat(), dl], "ca_symbols": sorted(set(symbols)),
        "ca_range": [first_trade_date, planned_start.date().isoformat()], "collector_sha256": collector_sha(),
        "fetch_core_sha256": c.E1_FETCH_SHA})


def audit_token(root) -> str:
    plan = _out(root) / "plan.json"
    p = json.loads(plan.read_text(encoding="utf-8"))
    return AUDIT_ACK.format(collector=collector_sha(), plan=c.sha256_file(plan), start=p["planned_start"])


def _ack(root, ack_id: str, token: str) -> dict:
    con = sqlite3.connect(f"file:{(Path(root) / 'mailbox.sqlite3').as_posix()}?mode=ro", uri=True)
    try:
        row = con.execute("SELECT sender, recipient, request_key, body, created FROM messages WHERE id=?",
                          (ack_id,)).fetchone()
    finally:
        con.close()
    if row is None or row[:3] != ("codex", "claude", "experiments-prereg"):
        raise SystemExit(f"{ack_id!r} is not a codex->claude experiments-prereg message")
    if token not in [ln.rstrip("\r") for ln in (row[3] or "").split("\n")]:
        raise SystemExit(f"ack lacks the standalone line: {token}")
    t = datetime.fromtimestamp(row[4], tz=timezone.utc)
    if t > c.now_utc():
        raise SystemExit("ack is in the future")
    return {"ack_id": ack_id, "created_utc": t.isoformat()}


def _reserve(dirpath: Path, ack: dict) -> None:
    dirpath.mkdir(parents=True, exist_ok=False)                             # one attempt: never reused
    _write_once(dirpath / "attempt.json", {"reserved_utc": c.now_utc().isoformat(), "ack": ack})


def _headers(keys):
    return {"APCA-API-KEY-ID": keys[0], "APCA-API-SECRET-KEY": keys[1]}


MAX_PAGES = 200


class Structural(Exception):
    pass


def _write_page(path: Path, data: bytes, created: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as f:                                            # raw page kept, never overwritten
        f.write(data)
    created.append(path)


def _get(client, url, params, headers, page_path: Path, created):
    try:
        resp = client.get(url, params=params, headers=headers)
    except Exception as e:                                                # transport failure: no secrets in text
        raise Structural(f"{page_path.name}: transport error {type(e).__name__}")
    _write_page(page_path, resp.content, created)
    if resp.status_code != 200:
        raise Structural(f"{page_path.name}: HTTP {resp.status_code}")
    try:
        return json.loads(resp.content)
    except ValueError:
        raise Structural(f"{page_path.name}: body is not JSON")


def _paged(client, url, base, headers, prefix: Path, validate, created) -> list:
    pages, token, seen = [], None, set()
    for n in range(MAX_PAGES):
        params = dict(base, **({"page_token": token} if token else {}))
        data = _get(client, url, params, headers, prefix.with_name(f"{prefix.name}_page{n:03d}.json"), created)
        if validate:
            validate(data, f"{prefix.name}_page{n:03d}")
        pages.append(data)
        token = data.get("next_page_token")
        if not token:
            return pages
        if token in seen:
            raise Structural(f"{prefix.name}: repeated next_page_token")
        seen.add(token)
    raise Structural(f"{prefix.name}: more than {MAX_PAGES} pages")


def _parse_bars(symbols, pages, sessions):
    """{symbol: {session_date: {date,o,h,l,c}}} + problems; finite positive OHLC with l <= min(o,c) <= max(o,c) <= h,
    one bar per (symbol, session), only requested symbols and sessions; anything else is a problem record."""
    want, sess = set(symbols), set(sessions)
    out, problems = {s: {} for s in symbols}, []
    for page in pages:
        for sym, rows in (page.get("bars") or {}).items():
            if sym not in want:
                problems.append({"symbol": sym, "session": None, "problem": "unrequested symbol"})
                continue
            for bar in rows:
                d = c.aware(bar["t"]).astimezone(c.NY).date().isoformat()
                o, h, l, cl = (bar.get(k_) for k_ in ("o", "h", "l", "c"))
                ok = all(isinstance(v, (int, float)) and v == v and 0 < v < float("inf") for v in (o, h, l, cl))
                if d not in sess or not ok or not (l <= min(o, cl) <= max(o, cl) <= h) or d in out[sym]:
                    problems.append({"symbol": sym, "session": d, "problem": "invalid, duplicate or off-calendar bar"})
                    continue
                out[sym][d] = {"date": d, "o": o, "h": h, "l": l, "c": cl}
    for sym in symbols:
        for d in sessions:
            if d not in out[sym]:
                problems.append({"symbol": sym, "session": d, "problem": "missing session"})
    return out, problems


def _corporate_actions(client, keys, symbols, start, end, pages_dir, created):
    f = c.fetch()
    batched = []
    for i in range(0, len(symbols), 50):
        batch = symbols[i:i + 50]
        base = {"symbols": ",".join(batch), "start": start, "end": end, "limit": 1000}
        for page in _paged(client, CA_URL, base, _headers(keys), pages_dir / f"ca_{i // 50:03d}",
                           f.validate_ca_page, created):
            batched.append((batch, page))
    return f.classify_ca(batched)


def do_audit(root, ack_id: str, client, keys) -> dict:
    out = _out(root)
    plan_path = out / "plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    ack = _ack(root, ack_id, audit_token(root))
    if c.aware(plan["planned_start"]) <= c.now_utc():
        raise SystemExit("planned START has passed: re-register")
    d = out / "audit"
    _reserve(d, ack)
    created = []
    cal = _get(client, CAL_URL, {"start": plan["calendar_range"][0], "end": plan["calendar_range"][1],
                                 "date_type": "TRADING"}, _headers(keys), d / "pages" / "calendar.json", created)
    actions, problems = _corporate_actions(client, keys, plan["ca_symbols"], plan["ca_range"][0],
                                           plan["ca_range"][1], d / "pages", created)
    _write_once(d / "calendar.json", cal)
    _write_once(d / "corporate_actions.json", actions)
    _write_once(d / "ca_problems.json", problems)
    files = {p.name: c.sha256_file(p) for p in sorted(d.glob("*.json")) if p.name != "manifest.json"}
    return json.loads(_write_once(d / "manifest.json", {"outcome": "COMPLETE", "ack": ack, "files": files,
                                                        "pages": sorted(str(p) for p in created)}).read_text())


def write_final_plan(root, stop_close: str, symbols, carry_in_symbols, first_trade_date: str) -> Path:
    stop_day = c.aware(stop_close).astimezone(c.NY).date().isoformat()
    return _write_once(_out(root) / "final_plan.json", {
        "stop_close": stop_close, "bar_symbols": sorted(set(symbols) | set(carry_in_symbols)),
        "ca_symbols_window": sorted(set(symbols)), "ca_symbols_full_history": sorted(set(carry_in_symbols)),
        "full_history_start": first_trade_date, "stop_date": stop_day, "collector_sha256": collector_sha(),
        "fetch_core_sha256": c.E1_FETCH_SHA})


def do_final(root, ack_id: str, client, keys) -> dict:
    out = _out(root)
    fp = out / "final_plan.json"
    plan = json.loads(fp.read_text(encoding="utf-8"))
    ack = _ack(root, ack_id, ACQUIRE_ACK.format(collector=collector_sha(), plan=c.sha256_file(fp)))
    pr = json.loads((out / "prereg.json").read_text(encoding="utf-8"))
    d = out / "final"
    _reserve(d, ack)
    created = []
    start_day = c.aware(pr["start"]).astimezone(c.NY).date().isoformat()
    sessions = [x["date"] for x in pr["calendar"] if start_day <= x["date"] <= plan["stop_date"]]
    bar_pages = _paged(client, BARS_URL, {"symbols": ",".join(plan["bar_symbols"]), "timeframe": "1Day",
                                          "start": pr["start"], "end": plan["stop_close"], "adjustment": "raw",
                                          "feed": "sip", "limit": 10000}, _headers(keys),
                       d / "pages" / "bars", None, created)
    bars, bar_problems = _parse_bars(plan["bar_symbols"], bar_pages, sessions)
    ca_win, p1 = _corporate_actions(client, keys, plan["ca_symbols_window"], start_day, plan["stop_date"],
                                    d / "pages", created)
    ca_full, p2 = _corporate_actions(client, keys, plan["ca_symbols_full_history"], plan["full_history_start"],
                                     plan["stop_date"], d / "pages_full", created)
    for name, obj in (("bars.json", bars), ("bar_problems.json", bar_problems),
                      ("corporate_actions.json", ca_win + ca_full), ("ca_problems.json", p1 + p2)):
        _write_once(d / name, obj)
    files = {p.name: c.sha256_file(p) for p in sorted(d.glob("*.json")) if p.name != "manifest.json"}
    return json.loads(_write_once(d / "manifest.json", {"outcome": "COMPLETE", "ack": ack, "files": files,
                                                        "pages": sorted(str(p) for p in created)}).read_text())
```

  Add to the Step 1 tests: `_parse_bars` flags a bar with `l > min(o, c)`, a duplicate session, an off-calendar
  date and a missing session; `_paged` refuses a repeated `next_page_token`; a transport error message contains
  no key text. Do not edit e1_fetch.

- [ ] **Step 4: GREEN** → `s1_evidence/t6_green.txt`.
- [ ] **Step 5: Record evidence** — hashes to `s1_evidence/t6_hashes.txt`.

---

### Task 7: Runner — gates, attestations, exclusions, economics, verdict (R-GATES, R-UNITS, R-VERDICT, R-EPOCH)

**Files:** Create `s1_run.py`, `s1_tests/test_s1_run.py`

**Interfaces:**
- Consumes: Tasks 1–6; `s1_common.sim()` (`baseline_lots`, `baseline_economics`, `simulate_lot`,
  `lot_economics`, `compare`, `paired_bootstrap`, `x`, `ny_date`, `close_instant`).
- Produces:
  - `RUN_ACK = "S1-RUN-ACK runner_sha256={runner} plan_sha256={plan} audit_manifest_sha256={audit} start={start}"`,
    `SCORE_ACK = "S1-SCORE-ACK runner_sha256={runner} final_manifest_sha256={final} stop_attest_sha256={attest}"`.
  - `attest_start(root, statement) / attest_stop(root, statement)` — write `s1_out/attest_start.json` /
    `attest_stop.json` (exact statements in `START_STATEMENT`, `STOP_STATEMENT`; bound hashes per §12).
  - `do_prereg(root, ack_id, receipt) -> dict` — refuses after planned START (example 16), without audit
    COMPLETE, without START attestation, or if the audit shows a BLOCKED carry-in (example 12, known case).
  - `blocks(action, symbol) -> bool`; `exclusions(lots, actions, problems, stop_date, sessions, bars,
    bar_problems) -> {lot_id: [reasons]}`; `disposition(n, k) -> str` (`OK`/`INCONCLUSIVE`/`INSUFFICIENT`).
  - `score(root, ack_id) -> dict` — one exclusive score into `s1_out/score/` (reservation file `x`-mode).

- [ ] **Step 1: Write the failing tests** (design examples 9, 12, 16, 18, 20–23 plus the cap boundary and the
  independent economic oracle)

```python
from datetime import datetime, timezone
from fractions import Fraction

import pytest
import s1_run as r
from conftest import s1_state

UTC = timezone.utc
SESS = ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"]


def bar(d, o=100, h=101, l=99, c=100):
    return {"date": d, "o": o, "h": h, "l": l, "c": c}


def lot(i, sym, day, qty=10, px=100.0):
    return {"id": i, "symbol": sym, "entry_ts": datetime.fromisoformat(f"{day}T15:00:00+00:00"), "qty": qty,
            "entry_px": px, "entry_notional": qty * px}


def test_exclusion_window_resolved_vs_inside():                                          # example 21
    acts = [{"type": "forward_splits", "id": "s", "symbol": "A", "ex_date": "2026-10-27", "old_rate": 1,
             "new_rate": 2}]
    bars = {"A": {d: bar(d) for d in SESS}}
    ex = r.exclusions([lot(1, "A", "2026-10-26"), lot(2, "A", "2026-10-28")], acts, [], "2026-10-30", SESS, bars, [])
    assert 1 in ex and 2 not in ex


def test_undated_action_excludes_all_lots_of_symbol():                                   # example 22
    acts = [{"type": "spin_offs", "id": "u", "source_symbol": "A"}]
    bars = {"A": {d: bar(d) for d in SESS}}
    ex = r.exclusions([lot(1, "A", "2026-10-26"), lot(2, "A", "2026-10-29")], acts, [], "2026-10-30", SESS, bars, [])
    assert set(ex) == {1, 2}


def test_endpoint_day_entry_missing_stop_close_excluded():                               # example 23
    bars = {"A": {d: bar(d) for d in SESS[:-1]}}
    assert 1 in r.exclusions([lot(1, "A", "2026-10-30")], [], [], "2026-10-30", SESS, bars, [])


@pytest.mark.parametrize("n,k,want", [(40, 4, "OK"), (40, 5, "INCONCLUSIVE"), (30, 1, "INSUFFICIENT"),
                                      (0, 0, "INSUFFICIENT"), (300, 30, "OK")])
def test_cap_boundary(n, k, want):
    assert r.disposition(n, k) == want


def test_independent_oracle_for_p13_economics():
    """Hand computation (no e1_sim) of one lot: entry 100 x 10 on 10-26; 10-27 close 110 (hw 110); 10-28 low 96
    <= trail 110*0.88 = 96.8 -> exit at 96.8. 5 bp costs on entry and exit."""
    bars = [bar("2026-10-27", 100, 111, 99, 110), bar("2026-10-28", 100, 100, 96, 97)]
    out = r.candidate_economics(lot(1, "A", "2026-10-26"), bars, "2026-10-28", bp=5)
    proceeds = Fraction(968, 10) * 10
    pnl = proceeds - 1000 - Fraction(1000 * 5, 10000) - proceeds * Fraction(5, 10000)
    assert out["_pnl"] == pnl and out["reason"] == "trail"


def test_missing_attestation_is_unverified_and_not_a_nomination():                       # example 9
    v = r.final_verdict(numeric="SHADOW PASS", attest_stop=None)
    assert v == {"verdict": "SHADOW PASS", "provenance": "UNVERIFIED-PROVENANCE", "nomination": False}
    assert r.final_verdict(numeric="SHADOW PASS", attest_stop={"ok": True})["nomination"] is True


def test_prereg_after_planned_start_refused(tmp_path, monkeypatch):                      # example 16
    s1_state(tmp_path, planned_start="2026-10-26T13:30:00+00:00")
    monkeypatch.setattr(r.c, "now_utc", lambda: datetime(2026, 10, 26, 13, 31, tzinfo=UTC))
    with pytest.raises(SystemExit, match="START"):
        r.do_prereg(tmp_path, "m", receipt={})
    assert not (tmp_path / "s1_out" / "prereg.json").exists()


def test_mismatched_or_duplicate_acks_make_no_request_no_output(tmp_path):              # example 18
    s1_state(tmp_path, planned_start="2026-10-26T13:30:00+00:00", score_ready=True)
    with pytest.raises(SystemExit):
        r.score(tmp_path, "wrong-id")
    assert not (tmp_path / "s1_out" / "score").exists()


def test_carry_in_split_blocked_or_inconclusive():                                       # example 12
    acts = [{"type": "forward_splits", "id": "s", "symbol": "B", "ex_date": "2026-09-01", "old_rate": 1,
             "new_rate": 2}]
    assert r.carry_in_status({"B": 5.0}, acts, held_since={"B": "2026-08-01"}, phase="audit") == "BLOCKED"
    assert r.carry_in_status({"B": 5.0}, acts, held_since={"B": "2026-08-01"}, phase="final") == "INCONCLUSIVE"
    assert r.carry_in_status({"B": 5.0}, [], held_since={"B": "2026-08-01"}, phase="final") == "OK"


def test_bridge_ticker_unaudited_split_inconclusive():                                   # example 20
    acts = [{"type": "reverse_splits", "id": "s", "symbol": "NEW", "ex_date": "2026-10-23", "old_rate": 10,
             "new_rate": 1}]
    assert r.carry_in_status({"NEW": 5.0}, acts, held_since={"NEW": "2026-10-22"}, phase="final") == "INCONCLUSIVE"
```

- [ ] **Step 2: RED** → `s1_evidence/t7_red.txt`.

- [ ] **Step 3: Implement** — `s1_run.py`. Required content (write it in full; the snippets below are the exact
  rules, complete):

```python
"""S1 runner (§11–15): lifecycle gates and ACKs, attestations, carry-in unit trust, per-lot paired exclusions,
economics from the pinned E1 core, verdict and report. Never touches the live app or trading.db."""
import json
from datetime import datetime
from pathlib import Path

import s1_books as b
import s1_collect as k
import s1_common as c
import s1_seal as z

RUN_ACK = "S1-RUN-ACK runner_sha256={runner} plan_sha256={plan} audit_manifest_sha256={audit} start={start}"
SCORE_ACK = "S1-SCORE-ACK runner_sha256={runner} final_manifest_sha256={final} stop_attest_sha256={attest}"
START_STATEMENT = "I confirm the trading_app backend runs from the recorded checkout, started after the S1 receipt."
STOP_STATEMENT = ("I confirm that between START and the stop no MeanReversion code, config or package changed "
                  "(including changed and reverted) and no MeanReversion trade was placed or edited by hand.")
BPS = (0, 1, 5, 10)
BLOCKING_TYPES = {"forward_splits", "reverse_splits", "unit_splits", "spin_offs", "rights_distributions",
                  "cash_mergers", "stock_mergers", "stock_and_cash_mergers", "stock_dividends", "redemptions",
                  "worthless_removals", "name_changes"}
SYMBOL_FIELDS = ("symbol", "old_symbol", "new_symbol", "alternate_symbol", "acquiree_symbol", "source_symbol")
DATE_FIELDS = ("ex_date", "effective_date", "process_date")


def runner_sha() -> str:
    return c.sha256_file(Path(__file__).resolve())


def _date(a):
    return next((a[f] for f in DATE_FIELDS if isinstance(a.get(f), str) and a[f]), None)


def blocks(a, sym) -> bool:
    """§11: any split kind (symbol/old/new/alternate), spin-off/rights SOURCE, ACQUIREE of any merger, stock dividend,
    redemption, worthless removal, identity change (old_symbol), special cash dividend. Acquirer side does not block.
    Unknown types naming the symbol block."""
    t = a.get("type")
    if t == "cash_dividends":
        return a.get("symbol") == sym and a.get("special") is not False
    if t in ("spin_offs", "rights_distributions"):
        return a.get("source_symbol") == sym
    if t in ("cash_mergers", "stock_mergers", "stock_and_cash_mergers"):
        return a.get("acquiree_symbol") == sym
    if t == "name_changes":
        return a.get("old_symbol") == sym
    if t in BLOCKING_TYPES:
        return sym in {a.get(f) for f in ("symbol", "old_symbol", "new_symbol", "alternate_symbol")}
    return sym in {a.get(f) for f in SYMBOL_FIELDS}


def required_sessions(entry_date, stop_date, sessions) -> list:
    req = [s for s in sessions if entry_date < s <= stop_date]
    return req if stop_date in req else req + [stop_date]


def exclusions(lots, actions, problems, stop_date, sessions, bars, bar_problems) -> dict:
    sim = c.sim()
    blocked = {s for p in problems for s in p.get("blocks_symbols", [])}
    flagged = {(p["symbol"], p["session"]) for p in bar_problems}
    out = {}
    for l in lots:
        s, ed, why = l["symbol"], sim.ny_date(l["entry_ts"]), []
        if s in blocked:
            why.append("corporate-action problem record")
        for a in actions:
            if not blocks(a, s):
                continue
            d = _date(a)
            if d is None:
                why.append(f"undated {a.get('type')} {a.get('id')}")
            elif ed < d <= stop_date:
                why.append(f"{a.get('type')} {a.get('id')} on {d}")
        for d in required_sessions(ed, stop_date, sessions):
            if bars.get(s, {}).get(d) is None or (s, d) in flagged:
                why.append(f"missing or flagged bar {d}")
        if why:
            out[l["id"]] = why
    return out


def disposition(n: int, k_: int) -> str:
    """§14 order: N = 0 -> INSUFFICIENT; 10*K > N -> INCONCLUSIVE (exactly 10 % allowed); N - K < 30 ->
    INSUFFICIENT; else OK."""
    if n == 0:
        return "INSUFFICIENT"
    if 10 * k_ > n:
        return "INCONCLUSIVE"
    if n - k_ < 30:
        return "INSUFFICIENT"
    return "OK"


def carry_in_status(held_at_start: dict, actions, held_since: dict, phase: str) -> str:
    for sym, q in held_at_start.items():
        if q <= 0:
            continue
        for a in actions:
            d = _date(a)
            if blocks(a, sym) and (d is None or d >= held_since[sym]):
                return "BLOCKED" if phase == "audit" else "INCONCLUSIVE"
    return "OK"


def candidate_economics(lot, path, stop_date, bp) -> dict:
    sim = c.sim()
    r = sim.simulate_lot(entry_ts=lot["entry_ts"], entry_px=lot["entry_px"], qty=lot["qty"], bars=path, splits=[],
                         policy=c.p13(), endpoint_date=stop_date)
    kind = "terminal" if r["reason"] == "endpoint" else "exit"
    return dict(sim.lot_economics(entry_notional=lot["entry_notional"], exits=[(r["shares_x"], r["exit_px_x"], kind)],
                                  bp=bp), reason=r["reason"], exit_date=r["exit_date"],
                eligible_sessions=r["eligible_sessions"])


def final_verdict(numeric: str, attest_stop) -> dict:
    prov = "VERIFIED" if attest_stop and attest_stop.get("ok") else "UNVERIFIED-PROVENANCE"
    return {"verdict": numeric, "provenance": prov, "nomination": numeric == "SHADOW PASS" and prov == "VERIFIED"}
```

  Then, in the same module, implement in full (and add the test-only `s1_state` helper to
  `s1_tests/conftest.py`, building the synthetic `s1_out/` the two gate tests need):
  - `_ack(root, ack_id, token)` = `k._ack` (reuse).
  - `attest_start(root, statement)`: refuse unless `statement == START_STATEMENT`; write once
    `{"statement", "trial_id": "S1", "planned_start", "receipt_sha256", "plan_sha256", "audit_manifest_sha256",
    "opening_seal_sha256", "recorded_utc"}`.
  - `do_prereg(root, ack_id, receipt)`: refuse if `now >= planned_start` ("planned START has passed:
    re-register"), if `s1_out/audit/manifest.json` is not COMPLETE, if `attest_start.json` is absent, if
    `carry_in_status(..., phase="audit") == "BLOCKED"`; verify `RUN_ACK` exactly; write once
    `s1_out/prereg.json` = `{"start": planned_start, "calendar": audit calendar, "receipt": receipt,
    "runner_sha256", "plan_sha256", "audit_manifest_sha256", "attest_start_sha256", "ack", "recorded_utc"}`.
  - `attest_stop(root, statement)`: refuse unless `statement == STOP_STATEMENT` and a stop is recorded
    (`stop_decision` status STOPPED/TIMEOUT from the seals); write once binding `attest_start_sha256`, actual
    `start`, `stop_close`, and `sealed_final_ledger_sha256` (= sha of the stop seal file).
  - `score(root, ack_id)`: verify `SCORE_ACK` (runner, final manifest, stop attestation hash); reserve
    `s1_out/score/attempt.json` with `open("x")` BEFORE computing anything; load the stop seal trades, economic
    lots over all rows with ts <= stop close (`b.economic_lots`), cohort = `z.cohort`; `carry_in_status(...,
    phase="final")` on the bridge book; `exclusions`; `disposition`; for each retained lot build
    `{"id","symbol","base": {bp: sim.baseline_economics(lot, close_at_stop, bp)}, "cand": {bp: {"P13":
    candidate_economics(...)}}}` with the path from `required_sessions`; `sim.compare(lots, "P13", bp)` for every
    bp in BPS; numeric verdict = `"SHADOW PASS"` iff `compare(...,5)["improves"] and compare(...,10)["improves"]`
    else `"FAIL"`, overridden in order by ABORTED-INVALID (any seal violation or receipt mismatch recorded),
    BLOCKED, NO-VALID-SEAL, carry-in INCONCLUSIVE, cap INCONCLUSIVE, INSUFFICIENT; `final_verdict(...)`; report
    N/K/retained, excluded IDs/reasons/notional share, zero-eligible lots, missed seals, observed restarts and
    gaps, the `b.bridge` quantities, totals, `sim.paired_bootstrap` at 5 and 10 bp; write `s1_out/score/s1.json`
    with `open("x")`. Strip `_`-prefixed keys before serialising.

- [ ] **Step 4: GREEN** → `s1_evidence/t7_green.txt`.
- [ ] **Step 5: Record evidence** — hashes to `s1_evidence/t7_hashes.txt`.

---

### Task 8: Connected synthetic lifecycle with real schemas (all R-IDs)

**Files:** Create `s1_tests/test_s1_connected.py`

**Interfaces:** consumes every module; uses `conftest.Ledger`, a synthetic mailbox, MockTransport collectors and a
synthetic `crash.log`.

- [ ] **Step 1: Write the test** — one scenario through every stage: plan → audit (MockTransport: calendar +
  no actions) → START attestation → prereg (RUN-ACK) → for each session: the synthetic "app" writes BUY/SELL rows
  then portfolio upserts in separate commits; a checkpoint at C+45 (inconsistent when it lands between them) and
  C+47 (consistent) → a 20:00 bridge BUY of a new ticker before START → a restart line in crash.log mid-trial →
  ≥ 100 lots fully sold with overshoot and an unsold open lot → stop → stop attestation → final plan includes the
  bridge ticker → final acquisition (MockTransport bars with irregular cent prices; one spin-off inside one lot's
  window) → SCORE-ACK → one score. Assert: cohort excludes bridge rows; stop close is the first sealed qualifying
  close; the spin-off lot is excluded in both arms; the restart is listed; the verdict equals an INDEPENDENT
  recomputation done in the test with `fractions.Fraction` (hard 8 %, trail 12 % of prior completed closes,
  activation the session after entry, opening fills at the open, intraday at the level, 5/10 bp costs) for every
  retained lot; a second `score` call refuses; no file under `s1_out` was overwritten (hash all files before and
  after the second call).
- [ ] **Step 2: Run** — GREEN expected once Tasks 0–7 are done; record `s1_evidence/t8_green.txt`. If it fails,
  fix the module at fault test-first (never the oracle).
- [ ] **Step 3: Record evidence** — hashes to `s1_evidence/t8_hashes.txt`.

---

### Task 9: Mutation evidence (targeted semantic mutants + focused Cosmic Ray)

**Files:** Create `s1_evidence/s1_mutants.py` (harness copied in structure from `e1_evidence/e1_r2_mutants.py`:
isolated copies, parallel, full `s1_tests` suite with `-x`), `s1_evidence/cr_s1/` session.

- [ ] **Step 1: Targeted mutants — each must be KILLED for its intended reason:** strict `<` 0.001 → `<=` (sold and
  write-off); sold event without requiring a SELL allocation; sold event not absorbing; operational write-off at
  the end instead of at each SELL; consistency on as-of rows instead of the full set; seal from a non-registered
  slot (slack 10 min → 600 min); seal from an inconsistent capture; unsealed close allowed to stop; backdated row
  ignored; deleted sealed row ignored; bridge rows in the cohort; deadline 180 days; no month-end clamp; NO-VALID-
  SEAL reported as FAIL; receipt includes secret keys; PID-change gap ignored; checkpoint emitting a price field;
  exclusion window shortened to the actual exit; undated action ignored; acquirer side blocking; stop close not
  required for endpoint-day entries; cap `>=`; INSUFFICIENT at 30; UNVERIFIED-PROVENANCE pass nominated; prereg
  after START allowed; duplicate score allowed; reservation after computing.
- [ ] **Step 2: Run** — `testenv/Scripts/python.exe s1_evidence/s1_mutants.py | tee s1_evidence/s1_mutants.txt`;
  every survivor gets a retrospective test (labelled) and a re-run.
- [ ] **Step 3: Focused Cosmic Ray** on `s1_books.py`, `s1_seal.py`, `s1_checkpoint.py`, `s1_run.py` (green
  baseline first; shards via `e1_evidence/cr_shard.py`; triage every survivor as KILLED-by-new-test / EQUIVALENT
  / NOT-MEANINGFUL / OPEN with reasons, re-applied via a recheck tool bound to the exact sources and test set).
- [ ] **Step 4: Record evidence** — counts, triage TSV, hashes.

---

### Task 10: Review package

- [ ] **Step 1:** Full suite `testenv/Scripts/python.exe -m pytest s1_tests -q -p no:cacheprovider` → `s1_evidence/full_green.txt`.
- [ ] **Step 2:** Write `s1_evidence/S1_BUILD_EVIDENCE.md`: per R-ID and per example the RED and GREEN files,
  retrospective tests labelled, mutant and Cosmic Ray results, every deviation from this plan.
- [ ] **Step 3:** Send Codex the exact hashes of every `s1_*.py`, test file and evidence file for code review. The
  next steps (scheduler entry, metadata plan, S1-AUDIT-ACK, START attestation, S1-RUN-ACK) follow §15 and are NOT
  part of this build.
