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
        try:
            if scheduled in z.schedule(d, calendar):
                return d
        except ValueError:                       # last calendar day: no next session, no window
            continue
    raise SystemExit(f"{scheduled.isoformat()} is not a registered seal slot")


def _seals(out: Path) -> list:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((out / "seals").glob("*.json"))]


def _fail_capture(cap_dir: Path, error: str) -> None:
    """Re-mark a written capture as failed (corrupt rows) and keep the reason in its meta.json."""
    mp = cap_dir / "meta.json"
    meta = json.loads(mp.read_text(encoding="utf-8"))
    meta.update(ok=False, error=error)
    mp.write_text(json.dumps(meta, indent=1), encoding="utf-8")


def _abort_stop(ab: dict) -> dict:
    return {"status": "ABORTED-INVALID", "stop_close": None, "reason": ab["reason"], "aborted_scheduled": ab["scheduled"]}


def _write_abort(out: Path, reason, rep: dict, snapshot, receipt_sha: str) -> dict:
    """First abort wins (exclusive create): ABORTED-INVALID is permanent from that instant (§6/§12)."""
    ab = {"reason": reason, "close": rep["close"], "scheduled": rep["scheduled"], "actual": rep["actual"],
          "projection_sha256": snapshot, "receipt_sha256": receipt_sha}
    try:
        with (out / "aborted.json").open("x", encoding="utf-8") as f:
            json.dump(ab, f, indent=1)
    except FileExistsError:
        return json.loads((out / "aborted.json").read_text(encoding="utf-8"))
    return ab


def run_checkpoint(root, live_db, scheduled, receipt_fn, process_fn, crash_log, now=c.now_utc) -> dict:
    out = Path(root) / "s1_out"
    pr = json.loads((out / "prereg.json").read_text(encoding="utf-8"))
    start, cal = c.aware(pr["start"]), pr["calendar"]
    day = _close_for(scheduled, cal)
    close = z.close_of(day["date"], cal)
    cap_dir = out / "captures" / day["date"] / scheduled.strftime("%Y%m%dT%H%M%SZ")
    if cap_dir.exists():                                   # never overwrite; record the refused rerun
        with (out / "reruns.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"scheduled": scheduled.isoformat(), "actual": now().isoformat(),
                                "close": close.isoformat()}) + "\n")
        raise SystemExit(f"slot already captured: {cap_dir}")
    aborted_path = out / "aborted.json"
    already = json.loads(aborted_path.read_text(encoding="utf-8")) if aborted_path.exists() else None
    meta = s.take_snapshot(live_db, cap_dir)
    actual = now()
    rep = {"close": close.isoformat(), "scheduled": scheduled.isoformat(), "actual": actual.isoformat(),
           "late": actual > scheduled + z.SCHEDULE_SLACK,
           "capture_ok": meta["ok"], "consistent": False, "fence_violations": [], "receipt_match": None,
           "pid": None, "process_start": None, "restart_gaps": [], "process_starts": {"observed": 0, "latest": None},
           "entries": None, "sold": None, "writeoffs": [], "snapshot": None,
           "seal": {"written": False, "sha256": None}, "stop": None,
           "exclusions": "not evaluated", "market_coverage": "not evaluated"}
    proc = process_fn()
    prev_obs = out / "last_process.json"
    prev = json.loads(prev_obs.read_text(encoding="utf-8")) if prev_obs.exists() else None
    # Baseline for the restart checks: the previous observation, or, if that one had no pid, the last one that did.
    base = None if prev is None else (prev if prev.get("pid") is not None else prev.get("last_known") or prev)
    rec = r.restart_record(crash_log, prev_size=(base["record"]["size"] if base else None))
    rep.update(pid=proc.get("pid"), process_start=proc.get("process_start"))
    known = {(x["ts"], x["pid"]) for x in (base["record"]["starts"] if base else [])}
    rep["process_starts"] = {"observed": sum(1 for x in rec["starts"] if (x["ts"], x["pid"]) not in known),
                             "latest": rec["starts"][-1] if rec["starts"] else None}
    if base is not None:
        rep["restart_gaps"] = r.restart_gaps(base, {**proc, "record": rec})
    elif proc.get("pid") is None:
        rep["restart_gaps"] = [f"process not observed ({proc.get('error') or 'nothing listening'})"]
    last_known = ({"pid": proc["pid"], "process_start": proc.get("process_start"), "record": rec}
                  if proc.get("pid") is not None else (prev or {}).get("last_known"))
    prev_obs.write_text(json.dumps({**proc, "record": rec, "last_known": last_known}), encoding="utf-8")
    receipt = receipt_fn()
    rep["receipt_match"] = receipt == pr["receipt"]
    receipt_sha = c.sha256_bytes(c.canonical(receipt))
    seals = _seals(out)
    proj = None
    if meta["ok"]:
        proj = json.loads((cap_dir / "projection.json").read_text(encoding="utf-8"))
        try:
            rep["consistent"] = b.consistency(proj["trades"], proj["portfolios"])["consistent"]
            rep["entries"] = len(z.cohort(proj["trades"], start, close))
            rep["sold"] = z.count_sold(proj["trades"], start, close)
            rep["writeoffs"] = b.operational_replay(proj["trades"])["writeoffs"]
        except b.BookError as e:
            rep.update(capture_ok=False, consistent=False, entries=None, sold=None, writeoffs=[])
            _fail_capture(cap_dir, f"BookError: {e}")
            proj = None
    if proj is not None:
        rep["snapshot"] = meta["projection_sha256"]
        rep["fence_violations"] = z.check_fences(seals, proj)
    reason = None
    if already is None:
        if not rep["receipt_match"]:
            reason = "semantic receipt changed"
        elif rep["fence_violations"]:
            reason = rep["fence_violations"]
        if reason is not None:
            already = _write_abort(out, reason, rep, rep["snapshot"], receipt_sha)
    if (already is None and proj is not None and rep["consistent"] and rep["receipt_match"]
            and not rep["fence_violations"]):
        cap = {"scheduled": scheduled.isoformat(), "actual": actual.isoformat(), "ok": True,
               "consistent": True, "projection_sha256": meta["projection_sha256"], "dir": str(cap_dir)}
        seal_path = out / "seals" / f"{day['date']}.json"
        if not seal_path.exists() and z.choose_seal(day, cal, [cap]):
            seal_path.parent.mkdir(parents=True, exist_ok=True)
            seal = {"close": close.isoformat(), "fence": z.fence(proj), "max_id": meta["max_trade_id"],
                    "trades": proj["trades"], "capture": cap, "restart_record": rec, "process": proc,
                    "receipt_sha256": receipt_sha, "receipt_match": True}
            with seal_path.open("x", encoding="utf-8") as f:
                json.dump(seal, f)
            rep["seal"] = {"written": True, "sha256": c.sha256_file(seal_path)}
            seals = _seals(out)
    if already is None:
        try:
            rep["stop"] = z.stop_decision(seals, start, cal, today=actual)
        except ValueError as e:                            # a bad seal record is protocol corruption
            already = _write_abort(out, f"bad seal record: {e}", rep, rep["snapshot"], receipt_sha)
    if already is not None:
        rep["stop"] = _abort_stop(already)
    (cap_dir.parent / f"{cap_dir.name}.report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scheduled", required=True)
    a = ap.parse_args()
    rep = run_checkpoint(c.HERE, LIVE_DB, c.aware(a.scheduled),
                         lambda: r.semantic_receipt(REPO, REPO / ".env", REPO / "runtime" / "python" / "python.exe"),
                         r.process_identity, CRASH_LOG)
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
