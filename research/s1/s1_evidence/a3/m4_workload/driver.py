"""A3 H4 row 439 (Erratum 2 r4 G3.7, O10; M4-WORKLOAD-1; Codex 799fc940 RM-1): the scheduled-checkpoint workload
driver. TEST TOOLING - never product, never imported by product code.

Subcommands (run with the testenv interpreter: python driver.py <cmd> ...):
  build   <kind low-Q|high-Q> --root R --backup-mb M   build one PRISTINE synthetic fixture root through the real
          conftest helpers and product stages (conftest.s1_state, conftest._write_seal, s1_slot.run_seal_stage,
          s1_slot.finalize_close); writes R/fixture.json (the workload actually built).
  child   --root R                                       ONE timed invocation: s1_checkpoint.run_checkpoint on the run
          root R for its pre-declared slot (never s1_checkpoint.main, which binds the live root, LIVE_DB and the live
          mailbox - ruling OP-13); writes R/child.json (control outcome, per-gate spans).
  measure --pristine P --runs-dir D --cell ...           prepare a fresh run root from P (cold: robocopy /J unbuffered
          real copies; warm: copies, big backups hard-linked for high-Q, then a full warm-up read), optional
          contention, the due instant, the launch, the wait; writes D/<id>.json per run.
  burn / ioload                                          the declared contention processes.
  summarize --runs-dir D --out F                         per-cell table and the RM-1 verdict (verdict_rule.py).

Isolation (asserted in every process that touches a root): s1_common.MAILBOX -> <root>/mailbox.sqlite3 (never the
coordination mailbox), s1_receipt.HMAC_KEY -> <root>/s1_receipt_hmac.key, s1_checkpoint.LIVE_DB / REPO / CRASH_LOG ->
non-existent paths under the root, socket.create_connection and httpx.HTTPTransport.handle_request raise. Every root
must lie under --scratch (the session scratchpad); a path naming trading.db, the coordination directory or the app
repository refuses. mailbox.py is never imported."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

START = "2026-10-26T13:30:00+00:00"
LOTS = [{"symbol": f"S{i % 5}", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (1, 80.0) if i < 99 else None}
        for i in range(100)]                     # the row-302 shape (99 lots sold): no lots stop - a running trial
FORBIDDEN = ("trading.db", "/.coordination/", "/.coordination")       # substrings of a normalized path
APP_REPO = "c:/users/gl450/trading_app/"                                 # the live app repository (and its root)


def _norm(p) -> str:
    return os.path.normcase(os.path.abspath(str(p))).replace("\\", "/").lower()


def guard_root(root: Path, scratch: Path) -> None:
    r, s = _norm(root), _norm(scratch)
    if not r.startswith(s.rstrip("/") + "/"):
        raise SystemExit(f"driver refused: root {root} is not under the scratch directory {scratch}")
    if any(bad in r for bad in FORBIDDEN) or r.startswith(APP_REPO) or (r + "/").startswith(APP_REPO):
        raise SystemExit(f"driver refused: root {root} names a forbidden location (live root, trading.db or the "
                         f"coordination directory)")


def setup(s1: Path, root: Path, scratch: Path) -> dict:
    """Import the product from `s1` and isolate it to `root` (see the module docstring). Returns the modules."""
    guard_root(root, scratch)
    sys.path[:0] = [str(s1), str(s1 / "s1_tests")]
    import socket

    import httpx
    import s1_checkpoint as ck
    import s1_common as c
    import s1_receipt

    def refuse(*a, **kw):
        raise AssertionError("driver network guard: a real network call was attempted")
    socket.create_connection = refuse
    httpx.HTTPTransport.handle_request = refuse
    coord = c.MAILBOX
    c.MAILBOX = root / "mailbox.sqlite3"
    assert _norm(c.MAILBOX) != _norm(coord) and ".coordination" not in _norm(c.MAILBOX), c.MAILBOX
    s1_receipt.HMAC_KEY = root / "s1_receipt_hmac.key"
    ck.LIVE_DB, ck.REPO, ck.CRASH_LOG = root / "NOT_LIVE.db", root / "NOT_REPO", root / "crash.log"
    assert "mailbox" not in sys.modules, "mailbox.py must never be imported"
    return {"c": c, "ck": ck}


# ------------------------------------------------------------------------------------------------- build
def _pad_ledger(path: Path, target: int) -> None:
    import sqlite3
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE IF NOT EXISTS m4_filler (id INTEGER PRIMARY KEY, b BLOB)")
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")              # the ledger is WAL: size the MAIN file
    while path.stat().st_size < target:
        con.execute("INSERT INTO m4_filler (b) VALUES (?)",
                    (os.urandom(max(4096, min(1 << 20, target - path.stat().st_size - 8192))),))
        con.commit()
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()


def build(args) -> None:
    root, scratch, s1 = Path(args.root), Path(args.scratch), Path(args.s1)
    if root.exists():
        raise SystemExit(f"build refused: {root} exists (a pristine fixture is built once)")
    root.mkdir(parents=True)
    m = setup(s1, root, scratch)
    c = m["c"]
    import s1_journal as j
    import s1_seal as z
    import s1_slot as sl
    import s1_trial as t
    from conftest import S1_RECEIPT, _write_seal, s1_mailbox_init, s1_state
    t0 = time.perf_counter()

    def log(msg):
        print(f"[{time.perf_counter() - t0:8.1f}s] {msg}", flush=True)
    s1_mailbox_init(root)
    info = s1_state(root, START, score_ready=True, stop=False, lots=LOTS, seal_days=[])
    log("trial ACTIVE (plan, audit, opening, START attestation, prereg, PREREG-ACK)")
    out, mb, cal, start = root / "s1_out", root / "mailbox.sqlite3", info["calendar"], info["start"]
    led = root / "s1_ledger.sqlite3"
    _pad_ledger(led, int(args.backup_mb * 1024 * 1024))
    log(f"ledger padded to {led.stat().st_size} bytes")
    oc = z.close_of(info["opening_close"], cal)
    elig = z.eligible_sessions(start, cal)
    rows_all = info["rows"]
    tr = t.open_trial(mb)

    def gv():
        return t.Gate(root, out, tr, j.read_trial(tr.trial_id, tr.genesis, mb), "ACTIVE", mb)
    built = elig[:-1] if args.max_closes is None else elig[:args.max_closes]     # (--max-closes: smoke only)
    for i, day in enumerate(built):                          # the last eligible close is the measured invocation's
        cl = z.close_of(day["date"], cal)
        slots = z.schedule(day, cal)
        q_slots = slots[:1] if args.kind == "low-Q" else slots[:-1]           # high-Q: every slot but W QUALIFIED
        for k, s in enumerate(q_slots):
            trades = [x for x in rows_all if c.aware(x["ts"]) <= s]
            _write_seal(out, day["date"], cl, trades, S1_RECEIPT, start=start, opening_close=oc, with_stage=False,
                        minutes=int((s - cl).total_seconds() // 60))
            if k == 0:                                       # the close's seal stage (E2), at the first slot + 32 s
                res = sl.run_seal_stage(gv(), day, cal, mailbox=mb, clock=lambda s=s: s + timedelta(seconds=32))
                assert res["written"], res
        w = z.window_end(day, cal)
        sl.finalize_close(gv(), day, cal, lambda w=w: w + timedelta(seconds=1), mailbox=mb)   # MISSED at E
        if i % 10 == 0 or i == len(built) - 1:
            log(f"close {i + 1}/{len(built)} {day['date']}: {len(q_slots)} QUALIFIED")
    rows = j.read_trial(tr.trial_id, tr.genesis, mb)
    backups = sorted(out.glob("captures/*/*/backup.sqlite3"))
    projs = [p.stat().st_size for p in out.glob("captures/*/*/projection.json")]
    last = elig[-1]
    run_slot = z.schedule(last, cal)[0]
    fx = {"kind": args.kind, "start": START, "backup_mb_declared": args.backup_mb,
          "ledger_bytes": led.stat().st_size, "eligible_closes": len(elig), "sealed_closes": len(built), "max_closes_smoke": args.max_closes,
          "n_qualified_rows": sum(1 for r_ in rows if r_.kind == "SLOT-QUALIFIED"),
          "n_qualified_trees": len(backups), "backup_bytes_total": sum(p.stat().st_size for p in backups),
          "projection_bytes": {"n": len(projs), "min": min(projs), "max": max(projs), "total": sum(projs)},
          "journal_rows_J": len(rows), "mailbox_bytes": mb.stat().st_size,
          "run_close": last["date"], "run_slot": run_slot.isoformat(),
          "bundle_sha256": c.bundle_sha256(), "pristine_root": str(root), "build_seconds": time.perf_counter() - t0,
          "built_utc": datetime.now(timezone.utc).isoformat()}
    (root / "fixture.json").write_text(json.dumps(fx, indent=1), encoding="utf-8")
    log(f"built: {json.dumps(fx)}")


# ------------------------------------------------------------------------------------------------- child
SPAN_TARGETS = (("s1_trial", "gate"), ("s1_slot", "evidence_check"), ("s1_slot", "evidence_problems"),
                ("s1_slot", "confirmed_close_problems"), ("s1_slot", "finalize_close"), ("s1_slot", "run_seal_stage"),
                ("s1_seal", "decide_stop"), ("s1_seal", "stop_record"), ("s1_seal", "current_stop"),
                ("s1_gates", "verified_registration"), ("s1_checkpoint", "_capture"),
                ("s1_checkpoint", "_finalize_others"), ("s1_checkpoint", "_after_terminal"),
                ("s1_journal", "read_trial"), ("s1_journal", "append"), ("s1_common", "sha256_file"),
                ("s1_common", "bundle_sha256"), ("s1_common", "load_pinned"))


def _instrument(spans: dict) -> None:
    """Diagnostics only (RM-1: no per-gate cap; nested spans are never summed into T): wall time and call count per
    function, recorded by wrapping the module attribute (calls through the module and bare-name calls inside it)."""
    import importlib
    for mod, name in SPAN_TARGETS:
        m = importlib.import_module(mod)
        real = getattr(m, name)
        key = f"{mod}.{name}"
        spans[key] = {"n": 0, "s": 0.0, "max": 0.0}

        def wrap(*a, _real=real, _k=key, **kw):
            t_ = time.perf_counter()
            try:
                return _real(*a, **kw)
            finally:
                d = time.perf_counter() - t_
                sp = spans[_k]
                sp["n"] += 1
                sp["s"] += d
                sp["max"] = max(sp["max"], d)
        setattr(m, name, wrap)


def child(args) -> None:
    m0, w0 = time.perf_counter(), time.time()                # the child's first instants (startup is inside T anyway)
    root, scratch, s1 = Path(args.root), Path(args.scratch), Path(args.s1)
    m = setup(s1, root, scratch)
    c, ck = m["c"], m["ck"]
    fx = json.loads((root / "fixture.json").read_text(encoding="utf-8"))
    slot = c.aware(fx["run_slot"])
    base = slot + timedelta(seconds=30)

    def now():                                            # a MOVING clock: the slot + 30 s + the elapsed monotonic
        return base + timedelta(seconds=time.perf_counter() - m0)
    c.now_utc = now
    from conftest import S1_PROCESS, S1_RECEIPT
    spans = {}
    _instrument(spans)
    rec = {"child_mono_start": m0, "child_wall_start": w0, "imports_done_mono": time.perf_counter()}
    try:
        res = ck.run_checkpoint(root, root / "s1_ledger.sqlite3", slot,
                                lambda reference=None: json.loads(json.dumps(S1_RECEIPT)),
                                lambda: dict(S1_PROCESS), root / "crash.log", now=now, mailbox=root / "mailbox.sqlite3")
        jr = res.get("journal") or {}
        rec.update(control_ok=bool(jr.get("kind") == "SLOT-QUALIFIED" and jr.get("outcome") == "APPEND"
                                   and (res.get("seal") or {}).get("written")),
                   journal=jr, seal=res.get("seal"), stop=res.get("stop"), refused=None)
    except SystemExit as e:
        rec.update(control_ok=False, refused=str(e)[:500])
    rec.update(return_mono=time.perf_counter(), return_wall=time.time(), spans=spans)
    (root / "child.json").write_text(json.dumps(rec, indent=1, default=str), encoding="utf-8")


# ------------------------------------------------------------------------------------------------- contention
def burn(args) -> None:
    buf = os.urandom(16 << 20)
    while True:
        hashlib.sha256(buf).digest()


def ioload(args) -> None:
    d = Path(args.dir)
    d.mkdir(parents=True, exist_ok=True)
    chunk = os.urandom(64 << 20)
    i = 0
    while True:
        p = d / f"io_{i % 16}.bin"
        with open(p, "wb") as f:
            f.write(chunk)
            f.flush()
            os.fsync(f.fileno())
        i += 1


# ------------------------------------------------------------------------------------------------- measure
def _robocopy_unbuffered(src: Path, dst: Path) -> None:
    r = subprocess.run(["robocopy", str(src), str(dst), "/E", "/J", "/R:0", "/W:0", "/NFL", "/NDL", "/NJH", "/NJS",
                        "/NP"], capture_output=True, text=True)
    if r.returncode >= 8:
        raise SystemExit(f"robocopy failed ({r.returncode}): {r.stdout[-500:]} {r.stderr[-500:]}")


def _copy_warm(src: Path, dst: Path, link_backups: bool) -> None:
    def cp(s, d):
        if link_backups and Path(s).name == "backup.sqlite3":
            os.link(s, d)
        else:
            shutil.copy2(s, d)
    shutil.copytree(src, dst, copy_function=cp)


def _warm_read(root: Path) -> int:
    n = 0
    for p in root.rglob("*"):
        if p.is_file():
            with open(p, "rb") as f:
                while True:
                    b = f.read(8 << 20)
                    if not b:
                        break
                    n += len(b)
    return n


def measure(args) -> None:
    pristine, runs_dir, scratch = Path(args.pristine), Path(args.runs_dir), Path(args.scratch)
    guard_root(pristine, scratch)
    runs_dir.mkdir(parents=True, exist_ok=True)
    fx = json.loads((pristine / "fixture.json").read_text(encoding="utf-8"))
    py = sys.executable
    me = str(Path(__file__).resolve())
    for k in range(args.n):
        rid = f"{fx['kind']}_{args.contention}_{args.cache}_{k + 1:02d}"
        if (runs_dir / f"{rid}.json").exists():
            print(f"{rid}: exists, skipped", flush=True)
            continue
        run_root = scratch / "m4_runs" / rid
        guard_root(run_root, scratch)
        if run_root.exists():
            shutil.rmtree(run_root)
        run_root.parent.mkdir(parents=True, exist_ok=True)
        tc = time.perf_counter()
        if args.cache == "cold":
            _robocopy_unbuffered(pristine, run_root)                     # real copies, unbuffered (no cache fill)
            warm_bytes = 0
        else:
            _copy_warm(pristine, run_root, link_backups=(fx["kind"] == "high-Q"))
            warm_bytes = _warm_read(run_root)
        prep_s = time.perf_counter() - tc
        for leftover in ("child.json",):
            (run_root / leftover).unlink(missing_ok=True)
        procs = []
        if args.contention == "contended":
            procs = [subprocess.Popen([py, me, "burn"]) for _ in range(os.cpu_count() or 4)]
            procs.append(subprocess.Popen([py, me, "ioload", "--dir", str(scratch / "m4_ioload")]))
            time.sleep(2.0)                                              # ramp (before the due instant is chosen)
        due_wall = time.time() + 1.0                                     # the nominal due instant, declared first
        while time.time() < due_wall:
            time.sleep(0.001)
        launch_wall, launch_mono = time.time(), time.perf_counter()          # the launch boundary
        p = subprocess.Popen([py, me, "child", "--root", str(run_root), "--scratch", str(scratch), "--s1", args.s1])
        p.wait()
        end_mono, end_wall = time.perf_counter(), time.time()               # the required-completion boundary
        for q in procs:
            q.kill()
        for q in procs:
            q.wait()
        ch = json.loads((run_root / "child.json").read_text(encoding="utf-8")) if (run_root / "child.json").exists() \
            else {"control_ok": False, "refused": f"child exited {p.returncode} without child.json"}
        T = end_mono - launch_mono
        L = launch_wall - due_wall
        rec = {"id": rid, "workload": fx["kind"], "contention": args.contention, "cache": args.cache,
               "due_wall": due_wall, "launch_wall": launch_wall, "launch_mono": launch_mono,
               "end_mono": end_mono, "end_wall": end_wall, "child_exit": p.returncode,
               "L_driver": L, "T": T, "C_driver": L + T,
               "wall_minus_mono_over_T": (end_wall - launch_wall) - T,
               "child_startup_s": ch.get("child_mono_start", launch_mono) - launch_mono,
               "child_return_to_exit_s": end_mono - ch.get("return_mono", end_mono),
               "clocks": {"T_clock": "time.perf_counter (QueryPerformanceCounter: monotonic, system-wide)",
                          "perf_counter": vars(time.get_clock_info("perf_counter")),
                          "wall": vars(time.get_clock_info("time")),
                          "wall_vs_mono_note": "L from wall instants (due, launch); T from perf_counter; their "
                                               "relation per run = wall_minus_mono_over_T (wall span - T)"},
               "control_ok": bool(ch.get("control_ok")), "child": ch, "prep_seconds": prep_s,
               "warm_read_bytes": warm_bytes, "fixture": fx, "contention_procs": len(procs)}
        (runs_dir / f"{rid}.json").write_text(json.dumps(rec, indent=1, default=str), encoding="utf-8")
        print(f"{rid}: T={T:.2f}s L_driver={L * 1000:.1f}ms control_ok={rec['control_ok']} prep={prep_s:.0f}s",
              flush=True)
        shutil.rmtree(run_root, ignore_errors=True)
        if (scratch / "m4_ioload").exists():
            shutil.rmtree(scratch / "m4_ioload", ignore_errors=True)


# ------------------------------------------------------------------------------------------------- summarize
def summarize(args) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import verdict_rule as vr
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(args.runs_dir).glob("*.json"))]
    cells = {}
    for r in runs:
        cells.setdefault((r["workload"], r["contention"], r["cache"]), []).append(r)
    rows = []
    for key, rs in sorted(cells.items()):
        ts = [r["T"] for r in rs]
        sp = {}
        for r in rs:
            for k_, v in (r["child"].get("spans") or {}).items():
                sp.setdefault(k_, []).append(v)
        rows.append({"cell": "/".join(key), "n": len(rs), "controls_ok": sum(r["control_ok"] for r in rs),
                     "min_T": min(ts), "max_T": max(ts), "max_L_driver": max(r["L_driver"] for r in rs),
                     "max_C_driver": max(r["C_driver"] for r in rs),
                     "spans_max_total_s": {k_: max(x["s"] for x in v) for k_, v in sp.items()},
                     "spans_max_calls": {k_: max(x["n"] for x in v) for k_, v in sp.items()}})
    scheduler = vr.b_conditional([{"id": r["id"], "T": r["T"], "control_ok": r["control_ok"]} for r in runs],
                                 None)
    driver_c = vr.verdict([{"id": r["id"], "L": r["L_driver"], "T": r["T"], "control_ok": r["control_ok"]}
                           for r in runs])
    Path(args.out).write_text(json.dumps({"cells": rows, "rm1_scheduler_verdict": scheduler,
                                          "driver_dispatch_C_only": driver_c, "n_runs": len(runs)}, indent=1),
                              encoding="utf-8")
    print(json.dumps({"rm1_scheduler_verdict": scheduler, "driver_dispatch_C_only": driver_c}, indent=1))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("kind", choices=["low-Q", "high-Q"])
    b.add_argument("--root", required=True)
    b.add_argument("--backup-mb", type=float, required=True)
    b.add_argument("--max-closes", type=int, default=None)
    ch = sub.add_parser("child")
    ch.add_argument("--root", required=True)
    me = sub.add_parser("measure")
    me.add_argument("--pristine", required=True)
    me.add_argument("--runs-dir", required=True)
    me.add_argument("--contention", choices=["idle", "contended"], required=True)
    me.add_argument("--cache", choices=["cold", "warm"], required=True)
    me.add_argument("--n", type=int, required=True)
    sub.add_parser("burn")
    io = sub.add_parser("ioload")
    io.add_argument("--dir", required=True)
    su = sub.add_parser("summarize")
    su.add_argument("--runs-dir", required=True)
    su.add_argument("--out", required=True)
    for p in (b, ch, me):
        p.add_argument("--scratch", required=True)
        p.add_argument("--s1", required=True)
    args = ap.parse_args(argv)
    {"build": build, "child": child, "measure": measure, "burn": burn, "ioload": ioload,
     "summarize": summarize}[args.cmd](args)


if __name__ == "__main__":
    main()
