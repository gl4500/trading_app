"""S1-COUNTS (§10): the scheduled read-only checkpoint. Counts and integrity only — never prices, PnL, exit levels,
candidate paths or comparisons. Imports only snapshot/books/seal/receipt/common.

Modes (exactly one per call, Task 7b):
- `--scheduled <iso>`: a post-prereg seal slot (run_checkpoint).
- `--opening --scheduled <iso>`: the opening seal (§4/§6/§12) — the seal of the NYSE close immediately before planned
  START, taken from plan.json + the COMPLETE audit calendar, BEFORE the START attestation / RUN-ACK / prereg.
- `--final-snapshot`: the acquisition-time snapshot after the stop, fence-checked against EVERY sealed slice (§6)."""
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
NA = "n/a before START"                  # opening-mode counts: there is no cohort or stop before START


def _close_for(scheduled: datetime, calendar):
    for d in calendar:
        try:
            if scheduled in z.schedule(d, calendar):
                return d
        except ValueError:                       # last calendar day: no next session, no window
            continue
    raise SystemExit(f"{scheduled.isoformat()} is not a registered seal slot")


def _load(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _seal_files(out: Path) -> list:
    return sorted((out / "seals").glob("*.json"))


def _seals(out: Path) -> list:
    return [_load(p) for p in _seal_files(out)]


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


# ------------------------------------------------------------------ shared slot-capture steps (both seal modes)
def _capture_dir(out: Path, day: str, scheduled: datetime) -> Path:
    return out / "captures" / day / scheduled.strftime("%Y%m%dT%H%M%SZ")


def _refuse_rerun(out: Path, cap_dir: Path, scheduled: datetime, close: datetime, now) -> None:
    """Never overwrite a capture; record the refused rerun."""
    if cap_dir.exists():
        with (out / "reruns.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"scheduled": scheduled.isoformat(), "actual": now().isoformat(),
                                "close": close.isoformat()}) + "\n")
        raise SystemExit(f"slot already captured: {cap_dir}")


def _new_report(close: datetime, scheduled: datetime, actual: datetime, meta: dict) -> dict:
    return {"close": close.isoformat(), "scheduled": scheduled.isoformat(), "actual": actual.isoformat(),
            "late": actual > scheduled + z.SCHEDULE_SLACK,
            "capture_ok": meta["ok"], "consistent": False, "fence_violations": [], "receipt_match": None,
            "pid": None, "process_start": None, "restart_gaps": [], "process_starts": {"observed": 0, "latest": None},
            "entries": None, "sold": None, "writeoffs": [], "snapshot": None,
            "seal": {"written": False, "sha256": None}, "stop": None,
            "exclusions": "not evaluated", "market_coverage": "not evaluated"}


def _observe_process(out: Path, rep: dict, process_fn, crash_log) -> tuple:
    """Process identity + the app's restart record against the previous observation (§12); updates `rep` and
    s1_out/last_process.json. Returns (proc, restart record)."""
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
    return proc, rec


def _read_capture(cap_dir: Path, meta: dict, rep: dict, counts) -> dict:
    """The capture's projection when it is readable by the books, else None (a corrupt row re-marks the capture
    failed). `counts(trades) -> (entries, sold)`, or None (opening mode: counts stay NA)."""
    if not meta["ok"]:
        return None
    proj = json.loads((cap_dir / "projection.json").read_text(encoding="utf-8"))
    try:
        rep["consistent"] = b.consistency(proj["trades"], proj["portfolios"])["consistent"]
        if counts is not None:
            rep["entries"], rep["sold"] = counts(proj["trades"])
        rep["writeoffs"] = b.operational_replay(proj["trades"])["writeoffs"]
    except b.BookError as e:
        na = None if counts is not None else NA
        rep.update(capture_ok=False, consistent=False, entries=na, sold=na, writeoffs=[])
        _fail_capture(cap_dir, f"BookError: {e}")
        return None
    rep["snapshot"] = meta["projection_sha256"]
    return proj


def _try_seal(out: Path, day, cal, close: datetime, rep: dict, meta: dict, cap_dir: Path, proj: dict, rec: dict,
              proc: dict, receipt_sha: str, before_seal=None, bridge=None) -> bool:
    """Write the close's seal (exclusive) if this capture is the schedule's seal; updates rep["seal"].
    `before_seal()`, if given, runs once the capture is chosen and before the seal is built or written.
    `bridge` (Task 8b): the post-START seal's bridge record (s1_seal.bridge_record); None for the opening seal."""
    cap = {"scheduled": rep["scheduled"], "actual": rep["actual"], "ok": True,
           "consistent": True, "projection_sha256": meta["projection_sha256"], "dir": str(cap_dir)}
    seal_path = out / "seals" / f"{day['date']}.json"
    if seal_path.exists() or not z.choose_seal(day, cal, [cap]):
        return False
    if before_seal is not None:
        before_seal()
    seal_path.parent.mkdir(parents=True, exist_ok=True)
    seal = {"close": close.isoformat(), "fence": z.fence(proj), "max_id": meta["max_trade_id"],
            "trades": proj["trades"], "capture": cap, "restart_record": rec, "process": proc,
            "receipt_sha256": receipt_sha, "receipt_match": True}
    if bridge is not None:
        seal["bridge"] = bridge
    with seal_path.open("x", encoding="utf-8") as f:
        json.dump(seal, f)
    rep["seal"] = {"written": True, "sha256": c.sha256_file(seal_path)}
    return True


def _write_report(cap_dir: Path, rep: dict) -> None:
    (cap_dir.parent / f"{cap_dir.name}.report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")


# ------------------------------------------------------------------ scheduled (post-prereg) mode
def run_checkpoint(root, live_db, scheduled, receipt_fn, process_fn, crash_log, now=c.now_utc) -> dict:
    out = Path(root) / "s1_out"
    pr = json.loads((out / "prereg.json").read_text(encoding="utf-8"))
    start, cal = c.aware(pr["start"]), pr["calendar"]
    day = _close_for(scheduled, cal)
    close = z.close_of(day["date"], cal)
    cap_dir = _capture_dir(out, day["date"], scheduled)
    _refuse_rerun(out, cap_dir, scheduled, close, now)
    aborted_path = out / "aborted.json"
    already = json.loads(aborted_path.read_text(encoding="utf-8")) if aborted_path.exists() else None
    meta = s.take_snapshot(live_db, cap_dir)
    actual = now()
    rep = _new_report(close, scheduled, actual, meta)
    proc, rec = _observe_process(out, rep, process_fn, crash_log)
    receipt = receipt_fn()
    rep["receipt_match"] = receipt == pr["receipt"]
    receipt_sha = c.sha256_bytes(c.canonical(receipt))
    seals = _seals(out)
    proj = _read_capture(cap_dir, meta, rep, lambda trades: (len(z.cohort(trades, start, close)),
                                                             z.count_sold(trades, start, close)))
    if proj is not None:
        rep["fence_violations"] = z.check_fences(seals, proj)
        rep["fence_violations"] += z.check_bridge(seals, proj["trades"], start)   # Task 8b (§6/§11)
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
        bridge = (z.bridge_record(proj["trades"], start, z.opening_close_of(start, cal)) if close >= start
                  else None)
        if _try_seal(out, day, cal, close, rep, meta, cap_dir, proj, rec, proc, receipt_sha, bridge=bridge):
            seals = _seals(out)
    if already is None:
        try:
            rep["stop"] = z.stop_decision(seals, start, cal, today=actual)
        except ValueError as e:                            # a bad seal record is protocol corruption
            already = _write_abort(out, f"bad seal record: {e}", rep, rep["snapshot"], receipt_sha)
    if already is not None:
        rep["stop"] = _abort_stop(already)
    _write_report(cap_dir, rep)
    return rep


# ------------------------------------------------------------------ opening mode (Task 7b)
def _audit_calendar(out: Path) -> list:
    """The audit's validated calendar: the audit manifest must be COMPLETE and every file it lists (calendar.json
    included) must match its hash. (s1_run._attempt does the same for the runner; this module may not import it.)"""
    d = out / "audit"
    mp = d / "manifest.json"
    if not mp.exists():
        raise SystemExit("opening refused: audit not COMPLETE (no audit manifest)")
    m = _load(mp)
    if m.get("outcome") != "COMPLETE":
        raise SystemExit(f"opening refused: audit not COMPLETE (outcome {m.get('outcome')!r})")
    files = m.get("files") or {}
    for n in sorted(set(files) | {"calendar.json"}):
        p = d / n
        if n not in files or not p.is_file() or c.sha256_file(p) != files[n]:
            raise SystemExit(f"opening refused: audit {n} missing or differs from its manifest hash")
    return [{"date": x["date"], "open": x["open"], "close": x["close"]} for x in _load(d / "calendar.json")]


def _opening_day(out: Path, scheduled: datetime) -> tuple:
    """(opening calendar row, calendar): plan.json + the COMPLETE audit calendar, never prereg.json. Refuses unless
    the plan's opening_close is the session immediately before planned START and `scheduled` is one of its slots."""
    pp = out / "plan.json"
    if not pp.exists():
        raise SystemExit("opening refused: no plan.json")
    plan = _load(pp)
    cal = _audit_calendar(out)
    start_day = c.aware(plan["planned_start"]).astimezone(c.NY).date().isoformat()
    prior = sorted((d for d in cal if d["date"] < start_day), key=lambda d: d["date"])
    if not prior or prior[-1]["date"] != plan.get("opening_close"):
        raise SystemExit(f"opening refused: plan opening_close {plan.get('opening_close')!r} is not the session "
                         f"immediately before planned START ({plan['planned_start']}) in the audit calendar")
    day = prior[-1]
    try:
        slots = z.schedule(day, cal)
    except ValueError as e:
        raise SystemExit(f"opening refused: {e}") from None
    if scheduled not in slots:
        raise SystemExit(f"opening refused: {scheduled.isoformat()} is not a registered seal slot of the opening "
                         f"close {day['date']}")
    return day, cal


def _stored_receipt(p: Path):
    """The stored opening receipt, or a marker that never equals a receipt when the file is unreadable (a crash
    mid-write): an unreadable receipt is treated as a differing one, never silently replaced."""
    try:
        return _load(p)
    except (ValueError, OSError):
        return ("unreadable", str(p))


def _store_opening_receipt(p: Path, receipt: dict) -> None:
    """Controller ruling 3: written BEFORE the opening seal (a receipt without a seal is harmless: attest_start needs
    both). Exclusive create; a stored receipt equal to this run's is kept as it is."""
    try:
        with p.open("x", encoding="utf-8") as f:
            json.dump(receipt, f, indent=1, sort_keys=True)
    except FileExistsError:
        if _stored_receipt(p) != receipt:                   # a concurrent run stored one after the early check
            raise _ReceiptConflict(f"opening refused: stored {p.name} differs from this run's receipt") from None


class _ReceiptConflict(SystemExit):
    """A stored opening receipt differs from this run's (fix round 1, M-2: the capture report is written first)."""


def run_opening_checkpoint(root, live_db, scheduled, receipt_fn, process_fn, crash_log, now=c.now_utc) -> dict:
    """Seal ONLY the opening close (§4/§6/§12), before the START attestation / RUN-ACK / prereg. Same capture,
    consistency, fence, no-overwrite and rerun rules as run_checkpoint; the receipt captured here is the reference
    every later seal must match (written to s1_out/opening_receipt.json for attest_start). Counts-only report.
    Controller ruling 3: opening_receipt.json is written BEFORE the seal. A receipt left by an earlier run that crashed
    before sealing is kept if it equals this run's receipt; if it differs, this run refuses (no seal, the stored
    receipt is left untouched for the operator)."""
    out = Path(root) / "s1_out"
    day, cal = _opening_day(out, scheduled)
    if (out / "seals" / f"{day['date']}.json").exists():
        raise SystemExit(f"opening seal exists ({day['date']}): refusing")
    close = z.close_of(day["date"], cal)
    cap_dir = _capture_dir(out, day["date"], scheduled)
    _refuse_rerun(out, cap_dir, scheduled, close, now)
    meta = s.take_snapshot(live_db, cap_dir)
    actual = now()
    rep = _new_report(close, scheduled, actual, meta)
    rep.update(entries=NA, sold=NA, stop=NA)
    proc, rec = _observe_process(out, rep, process_fn, crash_log)
    receipt = receipt_fn()
    rep["receipt_match"] = True                            # the opening receipt IS the reference
    receipt_sha = c.sha256_bytes(c.canonical(receipt))
    rp = out / "opening_receipt.json"
    proj = _read_capture(cap_dir, meta, rep, None)        # fix round 1 (M-1): read before any refusal
    if proj is not None:
        rep["fence_violations"] = z.check_fences(_seals(out), proj)
    if rp.exists() and _stored_receipt(rp) != receipt:    # leftover from a run that crashed before its seal
        rep["receipt_match"] = False
        rep["refused"] = f"receipt conflict: stored {rp.name} differs from this run's receipt"
        _write_report(cap_dir, rep)                       # never sealed on this path
        raise SystemExit(f"opening refused: stored {rp.name} differs from this run's receipt (no opening seal "
                         f"exists; remove it only after checking which receipt is right)")
    if proj is not None and rep["consistent"] and not rep["fence_violations"]:
        try:
            _try_seal(out, day, cal, close, rep, meta, cap_dir, proj, rec, proc, receipt_sha,
                      before_seal=lambda: _store_opening_receipt(rp, receipt))
        except _ReceiptConflict as e:                     # fix round 1 (M-2): a concurrent run stored another
            rep["receipt_match"] = False
            rep["refused"] = f"receipt conflict (concurrent): {e}"
            _write_report(cap_dir, rep)
            raise
    _write_report(cap_dir, rep)
    return rep


# ------------------------------------------------------------------ final-snapshot mode (Task 7b)
def _trial_state(out: Path, pr: dict, t: datetime) -> tuple:
    """(status, stop_close) of a trial that has ended; refuses while it is RUNNING."""
    if (out / "aborted.json").exists():
        return "ABORTED-INVALID", None
    try:
        st_ = z.stop_decision(_seals(out), c.aware(pr["start"]), pr["calendar"], today=t)
    except (ValueError, KeyError, TypeError) as e:
        raise SystemExit(f"final snapshot refused: bad seal record ({type(e).__name__}: {e})") from None
    if st_["status"] == "RUNNING":
        raise SystemExit("final snapshot refused: the trial is still RUNNING (no stop yet)")
    return st_["status"], st_["stop_close"]


def _next_attempt(d: Path) -> str:
    """The next attempt directory name under final_snapshot/ (attempt-01, attempt-02, ...)."""
    used = [int(p.name[len("attempt-"):]) for p in d.glob("attempt-*") if p.name[len("attempt-"):].isdigit()]
    return f"attempt-{max(used, default=0) + 1:02d}"


def ok_attempts(d: Path) -> list:
    """Names of the final_snapshot/attempt-NN directories whose meta.json records a successful capture (ok=True).
    Fix round 1 (I-1): success is decided by these, never by the presence of final_snapshot/report.json."""
    found = []
    for p in sorted(d.glob("attempt-*")):
        try:
            if json.loads((p / "meta.json").read_text(encoding="utf-8")).get("ok") is True:
                found.append(p.name)
        except (OSError, ValueError, AttributeError):
            pass
    return found


def run_final_snapshot(root, live_db, now=c.now_utc) -> dict:
    """The acquisition-time capture after the stop, fence-checked against EVERY seal (§6). Never seals; no prices or
    PnL. Controller ruling 2: each run is one attempt preserved under s1_out/final_snapshot/attempt-NN/ (meta.json +
    its own report.json). The first SUCCESSFUL capture (ok=True) also writes s1_out/final_snapshot/report.json and is
    final: any later run refuses, so a fence violation it records can never be retried away. A failed attempt (e.g. a
    locked DB) leaves no report.json, so a later run may try again. Fix round 1 (I-1): the refusal is decided by the
    attempts (any attempt-NN/meta.json with ok=True), so a lost or deleted report.json never re-opens the capture."""
    out = Path(root) / "s1_out"
    if not (out / "prereg.json").exists():
        raise SystemExit("final snapshot refused: no prereg (the trial never started)")
    t = now()
    status, stop_close = _trial_state(out, _load(out / "prereg.json"), t)
    d = out / "final_snapshot"
    if (d / "report.json").exists() or ok_attempts(d):    # fix round 1 (I-1): any ok attempt is final
        raise SystemExit(f"final snapshot already taken (a successful capture exists: "
                         f"{', '.join(ok_attempts(d)) or 'report.json'}): refusing")
    d.mkdir(parents=True, exist_ok=True)
    attempt = _next_attempt(d)
    files = _seal_files(out)
    seals = [_load(p) for p in files]
    try:
        meta = s.take_snapshot(live_db, d / attempt)
    except FileExistsError:
        raise SystemExit(f"final snapshot refused: {attempt} already exists (concurrent run?)") from None
    rep = {"attempt": attempt, "taken_utc": t.isoformat(), "trial_status": status, "stop_close": stop_close,
           "capture_ok": meta["ok"], "capture_error": meta.get("error"),
           "projection_sha256": meta.get("projection_sha256"), "max_trade_id": meta.get("max_trade_id"),
           "n_trades": meta.get("n_trades"),
           "seals_checked": [{"file": p.name, "close": x.get("close"), "sha256": c.sha256_file(p)}
                             for p, x in zip(files, seals)],
           "fence_checked": False, "fence_violations": []}
    if meta["ok"]:
        proj = _load(d / attempt / "projection.json")
        try:
            rep["fence_violations"] = z.check_fences(seals, proj)
            rep["fence_violations"] += z.check_bridge(seals, proj["trades"], c.aware(_load(out / "prereg.json")
                                                                                     ["start"]))   # Task 8b
        except (ValueError, KeyError, TypeError) as e:     # a malformed seal cannot vouch for anything
            rep["fence_violations"] = [f"bad seal record: {type(e).__name__}: {e}"]
        rep["fence_checked"] = True
    with (d / attempt / "report.json").open("x", encoding="utf-8") as f:
        json.dump(rep, f, indent=1)
    if meta["ok"]:
        try:
            with (d / "report.json").open("x", encoding="utf-8") as f:
                json.dump(rep, f, indent=1)
        except FileExistsError:
            raise SystemExit("final snapshot already taken (a concurrent run succeeded first): refusing") from None
    return rep


# ------------------------------------------------------------------ CLI
def parse_mode(argv=None) -> tuple:
    """Exactly one mode per call: ('scheduled', t) | ('opening', t) | ('final-snapshot', None)."""
    ap = argparse.ArgumentParser(description="S1 read-only checkpoint (counts and integrity only)")
    ap.add_argument("--scheduled", help="registered seal slot (aware ISO instant)")
    ap.add_argument("--opening", action="store_true", help="seal the opening close (with --scheduled)")
    ap.add_argument("--final-snapshot", action="store_true", help="acquisition-time snapshot after the stop")
    a = ap.parse_args(argv)
    if a.final_snapshot:
        if a.opening or a.scheduled is not None:
            ap.error("--final-snapshot takes neither --opening nor --scheduled (exactly one mode per call)")
        return "final-snapshot", None
    if a.scheduled is None:
        ap.error("--scheduled is required (alone, or with --opening)")
    return ("opening" if a.opening else "scheduled"), c.aware(a.scheduled)


def main(argv=None):
    mode, scheduled = parse_mode(argv)
    receipt = lambda: r.semantic_receipt(REPO, REPO / ".env", REPO / "runtime" / "python" / "python.exe")  # noqa: E731
    if mode == "final-snapshot":
        rep = run_final_snapshot(c.HERE, LIVE_DB)
    elif mode == "opening":
        rep = run_opening_checkpoint(c.HERE, LIVE_DB, scheduled, receipt, r.process_identity, CRASH_LOG)
    else:
        rep = run_checkpoint(c.HERE, LIVE_DB, scheduled, receipt, r.process_identity, CRASH_LOG)
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
