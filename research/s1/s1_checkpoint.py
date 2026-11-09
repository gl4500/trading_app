"""S1-COUNTS (§10): the scheduled read-only checkpoint. Counts and integrity only — never prices, PnL, exit levels,
candidate paths or comparisons. Imports only snapshot/books/seal/receipt/common.

Modes (exactly one per call, Task 7b):
- `--scheduled <iso>`: a post-prereg seal slot (run_checkpoint).
- `--opening --scheduled <iso>`: the opening seal (§4/§6/§12) — the seal of the NYSE close immediately before planned
  START, taken from plan.json + the COMPLETE audit calendar, BEFORE the START attestation / RUN-ACK / prereg.
- `--final-snapshot`: the acquisition-time snapshot after the stop, fence-checked against EVERY sealed slice (§6).

Task 12 (controller-added), Addendum 1: every mode verifies the registered S1 bundle FIRST (A3.2; a mismatch once
registered is the persistent "bundle" abort, A3.3) and then its stage's authorization (A8.2): the opening mode the
AUDIT-ACK, plan/calendar/source bindings (no prereg prerequisite); the scheduled and final-snapshot modes a verified
prereg + RUN-ACK. Invalid or fabricated authorization refuses with zero live callbacks.

Task 12 fix round 2 (Addendum 2): B1 - every claimed slot attempt is resolved by ONE exclusive, immutable resolution
record (captures/<day>/<slot>.resolution.json: SUCCESS / FAILURE published strictly before D = E + 30 min,
MISSED after E for a never-claimed slot, RESOLUTION-TIMEOUT at/after D); the seal of a close is a deterministic
function of those records in slot order (finalize_close), so concurrent finalizers write one seal. B2 - the opening
capture's observed binding is the registered process-binding reference (bound by the START attestation, RUN-ACK and
prereg); process_binding.json is gone. B3 - the registration-artifact gate (s1_common.verify_bundle_first) runs in
every mode; the opening seal is registered (registry/opening.json) just before it is written.
(A3 Task 7: the B1 resolution-record mechanism above is superseded - no finalizer publishes MISSED or
RESOLUTION-TIMEOUT records any more; a slot's state is its journal rows (F3: the finalizer's SLOT-TIMEOUT /
SLOT-MISSED), and a post-START seal is the seal/<close> stage, s1_slot.finalize_close / run_seal_stage.)

A3 Task 6 (Addendum 3 F3, F0.5, F1, F5.1/E1, F7.4; s1_slot.Worker): both seal modes run one slot worker - the slot
work lock, SLOT-INTENT, the claim (op, actor, capture_dir), P (resolution, then report: final before J), R, then J
(SLOT-QUALIFIED, R < D) or SLOT-FAILED. A late invocation (now >= E) and a late R (R >= D) are refused with no row
(the B1.3 worker-side RESOLUTION-TIMEOUT / .late.json / .overrun.json records are gone; the finalizer's TIMEOUT is
Task 7); after the STOP a new slot is LOST-RACE with no capture; an established violation commits TRIAL-INVALID
(established-violation) before the local abort; the seal is selected over QUALIFIED slots only; seal and stop
presentation is display-only (<slot>.after.json, OQ-11)."""
import argparse
import inspect
import json
import re
from datetime import datetime
from pathlib import Path

import s1_books as b
import s1_common as c
import s1_gates as g
import s1_receipt as r
import s1_seal as z
import s1_snapshot as s
import s1_trial

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


def _read_seals(out: Path, rep: dict) -> tuple:
    """Task 12 fix round 1 (I-4b, A9.1/A9.2): (seals, None), or (None, reason) for an unreadable seal record - the
    failure is preserved in the report (terminal: corrupt sealed evidence)."""
    try:
        return _seals(out), None
    except (OSError, ValueError) as e:
        why = f"seal record unreadable ({type(e).__name__})"
        rep.setdefault("failures", {})["seals"] = {"class": type(e).__name__, "reason": why, "terminal": True}
        return None, why


def _fail_capture(cap_dir: Path, error: str) -> None:
    """Re-mark a written capture as failed (corrupt rows) and keep the reason in its meta.json."""
    mp = cap_dir / "meta.json"
    meta = json.loads(mp.read_text(encoding="utf-8"))
    meta.update(ok=False, error=error)
    c.replace_atomic(mp, json.dumps(meta, indent=1))                 # fix round 3 (C-1): never a partial file


def _abort_stop(ab: dict) -> dict:
    return {"status": "ABORTED-INVALID", "stop_close": None, "reason": ab.get("reason"),
            "aborted_scheduled": ab.get("scheduled")}


def _write_abort(out: Path, reason, rep: dict, snapshot, receipt_sha) -> dict:
    """First abort wins (exclusive create, s1_common.write_abort): ABORTED-INVALID is permanent from that instant."""
    return c.write_abort(out, {"reason": reason, "close": rep["close"], "scheduled": rep["scheduled"],
                               "actual": rep["actual"], "projection_sha256": snapshot, "receipt_sha256": receipt_sha})


def _fingerprint(receipt):
    """A1: the compared part of a receipt (None when it has none: missing required evidence never matches)."""
    return receipt.get("fingerprint") if isinstance(receipt, dict) else None


# ------------------------------------------------------------------ A9: failure outcomes
OWN_ERRORS = (r.ReceiptError, s.SnapshotError, b.BookError)


def _failure(where: str, e: BaseException) -> dict:
    """A9.1: exception class + a sanitized reason: the text of S1's own errors (built without secret values), never
    the text of a foreign exception (which may carry a URL, a header or a value)."""
    reason = str(e) if isinstance(e, OWN_ERRORS) else f"{where} raised {type(e).__name__}"
    return {"class": type(e).__name__, "reason": reason,
            "terminal": bool(getattr(e, "terminal", False))}


def _safe(rep: dict, where: str, fn, *a, **kw):
    """Run one live observation; an exception is preserved in rep["failures"][where] (A9.1) and None returned."""
    try:
        return fn(*a, **kw)
    except Exception as e:                                         # noqa: BLE001 - preserved, never re-raised text
        rep.setdefault("failures", {})[where] = _failure(where, e)
        return None


# ------------------------------------------------------------------ shared slot-capture steps (both seal modes)
def _new_report(close: datetime, scheduled: datetime, actual: datetime, meta: dict, until: datetime) -> dict:
    """A counts-only capture report. Task 12 (A5.2): the measured capture start/end and the slot's eligibility end
    E; "late" = the capture does not satisfy s <= start <= end <= E (the same predicate the seal uses)."""
    cs, ce = meta.get("capture_start"), meta.get("capture_end")
    eligible = bool(cs and ce) and scheduled <= c.aware(cs) <= c.aware(ce) <= until
    return {"close": close.isoformat(), "scheduled": scheduled.isoformat(), "actual": actual.isoformat(),
            "capture_start": cs, "capture_end": ce, "eligible_until": until.isoformat(), "late": not eligible,
            "capture_ok": bool(meta.get("ok")), "consistent": False, "fence_violations": [], "receipt_match": None,
            "pid": None, "process_start": None, "restart_gaps": [], "process_starts": {"observed": 0, "latest": None},
            "entries": None, "sold": None, "writeoffs": [], "snapshot": None,
            "seal": {"written": False, "sha256": None}, "stop": None,
            "exclusions": "not evaluated", "market_coverage": "not evaluated"}


def _clock_refusal(cap_dir: Path, day, cal, close: datetime, scheduled: datetime, t: datetime):
    """A5.2: the actual clock must be within [s, E] BEFORE any capture (necessary, not sufficient). Outside it the
    attempt is preserved as a refused report (no capture) with the same predicate's verdict; None when in time."""
    until = z.eligible_until(scheduled, day, cal)
    if scheduled <= t <= until:
        return None
    rep = _new_report(close, scheduled, t, {"ok": False}, until)
    rep["refused"] = (f"clock {t.isoformat()} outside the slot window [{scheduled.isoformat()}, "
                      f"{until.isoformat()}]: no capture (A5.2)")
    return rep


def _capture(rep_close, scheduled, live_db, cap_dir: Path, now, until):
    """The snapshot (A9.1: any exception preserved, never a crash without a report) and the report around it."""
    holder = {}
    meta = _safe(holder, "capture", s.take_snapshot, live_db, cap_dir, now=now)
    actual = now()
    if meta is None:
        meta = {"ok": False, "error": holder["failures"]["capture"]["class"]}
    rep = _new_report(rep_close, scheduled, actual, meta, until)
    if holder.get("failures"):
        rep["failures"] = holder["failures"]
    return meta, rep


def _observe_process(out: Path, rep: dict, process_fn, crash_log) -> tuple:
    """Process identity + the app's restart record against the previous observation (§12); updates `rep` and
    s1_out/last_process.json. Returns (proc, restart record). Task 12 (A9.1): an exception from the observation
    is preserved (rep["failures"]["process"]) and reported as an observation gap."""
    proc = _safe(rep, "process", process_fn)
    if not isinstance(proc, dict):
        proc = {"error": (rep.get("failures") or {}).get("process", {}).get("class", "no observation")}
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
    c.replace_atomic(prev_obs, json.dumps({**proc, "record": rec, "last_known": last_known}))   # fix round 3 (C-1)
    return proc, rec


_ERR_TEXT = re.compile(r"^(exit -?\d+|[A-Za-z_][A-Za-z0-9_]{0,63})$")


def _binding(rep: dict, proc, ref) -> bool:
    """Addendum 2 B2 (amends A1.1/A9): the process-binding disposition of this observation against the registered
    reference `ref` (the opening's binding; None = this IS the opening). Sets rep["process_binding"]
    {"status", "binding"[, "reason"]} and returns True only for an OBSERVED DIFFERENCE (terminal, persistent):
    - an observation exception or a failed observation ({"error": ...}) -> EXCEPTION: A9.1 failure, no seal;
    - {"unavailable": reason} -> GAP: reported, never MATCH, never by itself a change, never a rebase;
    - a well-formed observed binding -> REFERENCE (opening) / MATCH / a change (semantic fields only: executable and
      sanitized launcher command line + its hash; pid / start time are provenance);
    - anything else (missing, malformed) -> MALFORMED: required evidence missing, no seal (never equality)."""
    failures = rep.get("failures") or {}
    if "process" in failures:
        rep["process_binding"] = {"status": "EXCEPTION", "binding": None, "reason": failures["process"]["reason"]}
        return False
    if not isinstance(proc, dict):
        proc = {}
    if proc.get("error") is not None:
        err = str(proc["error"])
        failures = rep.setdefault("failures", {})
        failures["process"] = {"class": "ProcessObservationError", "terminal": False,
                               "reason": f"process observation failed ({err if _ERR_TEXT.match(err) else 'error'})"}
        rep["process_binding"] = {"status": "EXCEPTION", "binding": None, "reason": failures["process"]["reason"]}
        return False
    b = proc.get("binding")
    if isinstance(b, dict) and set(b) == {r.GAP_FIELD} and isinstance(b[r.GAP_FIELD], str):
        rep["process_binding"] = {"status": "GAP", "binding": None, "reason": b[r.GAP_FIELD]}
        rep.setdefault("observation_gaps", []).append(f"process binding not observed ({b[r.GAP_FIELD]})")
        return False
    why = r.binding_problem(b)
    if why:
        rep.setdefault("failures", {})["process_binding"] = {"class": "MalformedBinding", "terminal": False,
                                       "reason": f"process binding missing or malformed: {why}"}
        rep["process_binding"] = {"status": "MALFORMED", "binding": None, "reason": why}
        return False
    if ref is None:
        rep["process_binding"] = {"status": "REFERENCE", "binding": dict(b)}
        return False
    if b == ref:
        rep["process_binding"] = {"status": "MATCH", "binding": dict(b)}
        return False
    rep["process_binding"] = {"status": "CHANGED", "binding": dict(b)}
    rep["process_binding_changed"] = True
    return True


def _read_capture(cap_dir: Path, meta: dict, rep: dict, counts) -> dict:
    """The capture's projection when it is readable by the books, else None (a corrupt row re-marks the capture
    failed). `counts(trades) -> (entries, sold)`, or None (opening mode: counts stay NA)."""
    if not meta.get("ok"):
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


def _receipt(rep: dict, receipt_fn, reference) -> tuple:
    """(receipt, receipt_sha) with A1/A9: the fingerprint is compared with `reference` (None = this IS the reference,
    the opening); an exception is preserved, never a match; a receipt without a fingerprint never matches."""
    receipt = _safe(rep, "receipt", _call_receipt, receipt_fn, reference)
    fp = _fingerprint(receipt)
    if fp is None and receipt is not None and "receipt" not in (rep.get("failures") or {}):
        rep.setdefault("failures", {})["receipt"] = {"class": "MissingEvidence", "terminal": False,
                                                     "reason": "receipt has no fingerprint (missing required evidence)"}
    if fp is None:
        rep["receipt_match"] = None
        return receipt, None
    rep["receipt_match"] = True if reference is None else fp == _fingerprint(reference)
    return receipt, c.receipt_sha256(receipt)


def _call_receipt(receipt_fn, reference):
    """Fix round 2 (I-1 completion): a receipt function that accepts `reference` is handed the bound receipt, so the
    closure's membership + raw sha256 are compared before any parse (s1_receipt.semantic_receipt)."""
    try:
        params = inspect.signature(receipt_fn).parameters
    except (TypeError, ValueError):
        params = {}
    if reference is not None and ("reference" in params or any(p.kind == p.VAR_KEYWORD for p in params.values())):
        return receipt_fn(reference=reference)
    return receipt_fn()


def _candidate(rep: dict, meta: dict, cap_dir: Path, proc: dict, rec: dict, receipt, receipt_sha, bridge,
               opening: bool) -> dict:
    """What a seal built from this capture needs (A5.2: a capture may become the seal at a later invocation, once
    every earlier slot of its close is resolved). The rows stay in the capture's projection.json."""
    cand = {"projection_sha256": meta["projection_sha256"], "dir": str(cap_dir), "max_id": meta["max_trade_id"],
            "capture_start": meta["capture_start"], "capture_end": meta["capture_end"], "process": proc,
            "restart_record": rec, "receipt_sha256": receipt_sha,
            "receipt_provenance": receipt.get("provenance") if isinstance(receipt, dict) else None,
            "bridge": bridge, "bundle_sha256": c.bundle_sha256(),
            "process_binding": rep.get("process_binding")}             # fix round 2 (B2)
    if opening:
        cand["receipt"] = receipt                          # the opening receipt is stored with the seal
    return cand


# ------------------------------------------------------------------ B1: slot resolution records + serialized seal
SUCCESS, FAILURE, MISSED, TIMEOUT = "SUCCESS", "FAILURE", "MISSED", "RESOLUTION-TIMEOUT"
EVIDENCE_KEYS = ("close", "scheduled", "actual", "capture_start", "capture_end", "eligible_until", "late",
                 "capture_ok", "consistent", "receipt_match", "process_binding", "snapshot", "fence_violations",
                 "failures", "refused", "candidate")
CANDIDATE_KEYS = ("projection_sha256", "dir", "max_id", "capture_start", "capture_end", "process", "restart_record",
                  "receipt_sha256", "receipt_provenance", "bridge", "bundle_sha256", "process_binding")


def _jsonable(obj):
    return json.loads(c.canonical(obj))


def _evidence(rep: dict) -> dict:
    """B1.2: the report a resolution publishes: capture, consistency, receipt/process dispositions and hashes."""
    return _jsonable({k_: rep.get(k_) for k_ in EVIDENCE_KEYS})


def _complete_success(ev) -> bool:
    """B1.2: a SUCCESS resolves the slot only with complete evidence of an eligible, consistent, matching capture."""
    if not isinstance(ev, dict) or any(k_ not in ev for k_ in EVIDENCE_KEYS):
        return False
    cand = ev.get("candidate")
    return (isinstance(cand, dict) and all(k_ in cand for k_ in CANDIDATE_KEYS)
            and ev["capture_ok"] is True and ev["consistent"] is True and ev["receipt_match"] is True
            and ev["late"] is False and not ev["failures"] and not ev["fence_violations"]
            and (ev["process_binding"] or {}).get("status") in ("REFERENCE", "MATCH", "GAP")
            and ev["snapshot"] == cand["projection_sha256"])


def finalize_close(out: Path, day, cal, t: datetime, before_seal=None, before_build=None, *, mailbox=None,
                   now=None) -> dict:
    """A3 Task 7: the finalizer command for one post-START close - the trial gate as a deadline path (ruling N2:
    defer_pending=True, so a stalled stage lock never delays a TIMEOUT at D or a MISSED at E; the gate also runs the
    F3 evidence table), then s1_slot.finalize_close (the journal finalizer: TIMEOUT / MISSED rows, the deferred
    leftover cleanup, the seal/<close> stage). It never writes a resolution file. `t`: the finalizer's clock.
    `before_seal` is the seal stage's before_publish hook; `before_build` is accepted for the legacy signature and
    ignored. A3 Task 10 (Task 7 concern 7): for the OPENING close the same journal finalizer runs, then the `opening`
    stage (_opening_stage) - so a crashed opening worker's SLOT-TIMEOUT at D determines the opening close and the
    opening seal follows, even when no later opening slot is captured.
    Returns {"written", "sha256", "from_slot", "deferred", "refused", "cleanup"}."""
    import s1_slot
    gv = s1_trial.gate(Path(out).parent, "finalize", mailbox=mailbox, now=lambda: t, defer_pending=True)
    fin = s1_slot.finalize_close(gv, day, cal, lambda: t, mailbox=mailbox, before_seal=before_seal,
                                 before_build=before_build)
    if day["date"] == s1_slot._opening_date(Path(out)):            # A3 Task 10 (Task 7 concern 7): the opening close
        try:
            _apply_opening(fin, _opening_stage(gv, Path(out), day, cal, lambda: t, mailbox))
        except s1_slot.QualifiedEvidence as e:                     # F3: a committed tree damaged (a race past the
            s1_slot.evidence_violation(gv, [str(e)], "opening seal stage", mailbox, clock=lambda: t)   # re-check)
        except SystemExit:
            raise
        except Exception as e:                  # noqa: BLE001 - F0.7 (fix round 1, M3): unexpected errors fail closed
            raise SystemExit(f"finalizer (opening stage) refused with no row ({type(e).__name__}: {e}) "
                             f"(F0.7)") from None
    elif (Path(out) / "prereg.json").is_file():       # A3 Task 11 (F2.2): a post-START close - the stop decision
        pr = _load(Path(out) / "prereg.json")         # after the finalizer (the W slot's MISSED can complete it);
        z.decide_stop(gv, pr["calendar"], c.aware(pr["start"]), now or c.now_utc,   # fix round 1 (review M1): a
                      mailbox=mailbox)                # clock CALLABLE sampled inside the TRIAL-STOP transaction
    return fin


def _apply_opening(fin: dict, got: dict) -> None:
    """A3 Task 10: fold an _opening_stage result into a finalize_close result (the opening close's seal is the
    `opening` stage, not run_seal_stage's seal/<close>)."""
    if "seal" in got:
        fin.update(written=True, sha256=got["seal"]["sha256"], from_slot=got["seal"]["from_slot"], deferred=None)
    elif "opening" in got:
        fin["deferred"] = None
    else:
        fin["deferred"] = got.get("deferred") or fin.get("deferred")
        fin["refused"] = got.get("refused") or fin.get("refused")


def _apply_finalize(rep: dict, fin: dict) -> None:
    if fin["written"]:
        rep["seal"] = {"written": True, "sha256": fin["sha256"]}
        if fin["from_slot"] != rep["scheduled"]:
            rep["seal"]["from_slot"] = fin["from_slot"]
    for k_ in ("deferred", "refused"):
        if fin[k_]:
            rep[k_] = fin[k_]


def _finalize_others(gv, cal, start, current: str, now, mailbox=None) -> None:
    """B1.4/B1.5 on the journal (A3 Task 7): the journal finalizer (s1_slot.finalize_close) for every OTHER post-START
    close of the trial that has slot rows and no CREATED seal stage - e.g. an earlier close whose worker crashed
    before J: its TIMEOUT at D, then its seal from the first QUALIFIED slot (sealing liveness, Task 6 review C2). D
    lies after W only for processing already captured evidence. A refusal or INVALID propagates (fail closed)."""
    import s1_journal as j
    import s1_slot
    import s1_stage
    start_day = start.astimezone(c.NY).date().isoformat()
    by_day = {d["date"]: d for d in cal}
    rows = j.read_trial(gv.trial.trial_id, gv.trial.genesis, gv.mailbox if mailbox is None else mailbox)
    days = set()
    for sub in sorted({r_.subject for r_ in rows if r_.kind in j.SLOT_KINDS}):
        try:
            days.add(s1_slot.day_for(s1_slot.slot_of(sub), cal)["date"])
        except SystemExit:                                 # (no committed row names an unregistered slot)
            continue
    for d in sorted(days):
        if d == current or d < start_day or d not in by_day:
            continue
        if s1_stage.stage_rows(rows, s1_slot.seal_stage_name(d))["created"] is not None:
            continue                                       # sealed: nothing left to decide for the seal
        s1_slot.finalize_close(gv, by_day[d], cal, now, mailbox=mailbox)


def _finalize_last_if_due(gv, cal, start, now, mailbox=None) -> None:
    """A3 Task 11 fix round 1 (review C1 ruling): once the clock is >= W of the LAST eligible close, the journal
    finalizer runs on that close even when it is sealed (its later slots MISSED at E), so its W slot - the timeout's
    trigger anchor (r1 P2) - gets its terminal row; the stop decision follows. Only the last eligible close is needed
    for that (other closes counted missed need no rows, r1 A6). The sealed close's first QUALIFIED and its CREATED
    seal stage are untouched (later terminals never change a determined close, E2.2). No-op before W or once every
    slot of the close is terminal."""
    import s1_journal as j
    import s1_slot
    eligible = z.eligible_sessions(start, cal)
    if not eligible:
        return
    last = eligible[-1]
    if now() < z.window_end(last, cal):
        return
    done = {r_.subject for r_ in j.read_trial(gv.trial.trial_id, gv.trial.genesis,
                                              gv.mailbox if mailbox is None else mailbox) if r_.kind in j.TERMINAL}
    if all(j.slot_subject(s) in done for s in z.schedule(last, cal)):
        return
    s1_slot.finalize_close(gv, last, cal, now, mailbox=mailbox)


def run_finalizer(root, now=c.now_utc, mailbox=None) -> dict:
    """A3 Task 11 fix round 1 (review C1 / M1 rulings): the finalizer COMMAND (`s1_checkpoint.py --finalize`). The
    trial gate as a deadline path (ruling N2: defer_pending=True), the A8.2 registration, then the journal finalizer
    of every unsealed post-START close with slot rows (_finalize_others), the last eligible close once the clock is
    >= its W even when sealed (_finalize_last_if_due), and the stop decision (decide_stop, F2.2). `now` is a clock
    CALLABLE (c.now_utc): j.append samples it inside each transaction - the TRIAL-STOP's readiness is never a fixed
    command-start instant (Codex 28e08272 checkpoint). Read-only towards the app: it captures nothing."""
    gv = s1_trial.gate(root, "finalizer", mailbox=mailbox, now=now, defer_pending=True)
    out = Path(root) / "s1_out"
    pr = g.verified_registration(out, "finalizer", mailbox, now)
    start, cal = c.aware(pr["start"]), pr["calendar"]
    _finalize_others(gv, cal, start, "", now, mailbox)
    _finalize_last_if_due(gv, cal, start, now, mailbox)
    z.decide_stop(gv, cal, start, now, mailbox=mailbox)
    return {"mode": "finalize",
            "stop": _public(z.current_stop(out, start, cal, now(), "finalizer", mailbox=mailbox))}


def finalize_pending(out: Path, cal, start, t: datetime, *, mailbox=None) -> None:
    """Fix round 3 (I-1) on the journal (A3 Task 7): run by a command BEFORE it decides or freezes the stop (stop
    attestation, final plan, final snapshot) - the journal finalizer of every unsealed post-START close with slot rows
    (TIMEOUT at D, MISSED at E, then its seal stage, which is refused with no row once the trial is not ACTIVE, E2.6).
    Its own gate is a deadline path (defer_pending=True, ruling N2) and runs the F3 evidence table, so a damaged
    QUALIFIED tree is TRIAL-INVALID (registration-artifact), never a mere refusal (Task 6 review N-2). It never writes
    a resolution file into any slot (E1.4)."""
    gv = s1_trial.gate(Path(out).parent, "finalize pending", mailbox=mailbox, now=lambda: t, defer_pending=True)
    _finalize_others(gv, cal, start, "", lambda: t, mailbox)


def _trial_stop_error(out: Path, start, cal, t: datetime, mailbox=None):
    """A2.1 / I-4b (kept from the pre-A3 checkpoint): the persisted stop, read BEFORE the capture only for its
    integrity: a stop.json gone missing or unreadable is the established violation `seal-record` (OQ-31); None when
    it reads. A3 Task 11: current_stop reads the journal's TRIAL-STOP (F1/F2) and never decides."""
    try:
        z.current_stop(out, start, cal, t, "checkpoint", mailbox=mailbox)
        return None
    except (ValueError, KeyError, TypeError, b.BookError) as e:
        return f"{type(e).__name__}: {e}"


def _qualified_violation(gv, w, out: Path, e: Exception, now) -> None:
    """F3 (QUALIFIED: a required file missing, changed or unparseable): TRIAL-INVALID (registration-artifact) first,
    then the local abort; refused (no seal)."""
    t = now()
    rec = {"where": "seal selection", "problems": [str(e)], "observed_utc": t.isoformat()}
    try:
        s1_trial.invalidate(gv.trial, "registration-artifact", rec, root=gv.root, mailbox=gv.mailbox, clock=now)
    finally:
        c.write_abort(out, dict(rec, reason=c.REGISTRATION_ARTIFACT, actual=None, close=None, scheduled=None,
                                projection_sha256=None, receipt_sha256=None))
    raise SystemExit(f"seal selection refused: {e}: INVALID (registration-artifact)")


def _public(st_: dict) -> dict:
    """The stop decision as reported (the internal `persisted` flag dropped)."""
    return {k_: v for k_, v in st_.items() if k_ != "persisted"}


# ------------------------------------------------------------------ scheduled (post-prereg) mode
def run_checkpoint(root, live_db, scheduled, receipt_fn, process_fn, crash_log, now=c.now_utc,
                   mailbox=None) -> dict:
    """One registered post-START slot (Addendum 3 F3; Task 6): the trial gate (F0.6; a slot path: a held stage lock
    is deferred, ruling N2 / E1.2), the RUN-ACK registration (A8.2), the slot work lock, SLOT-INTENT (STOPPED ->
    LOST-RACE with no capture; now >= E -> refusal with no row; no PREREG-ACK -> refusal, F7.4), the claim, the A5.2
    clock check (t < s: FAILED with the refused report, OQ-33), the capture and the observations (unchanged), an
    established violation external first (OQ-31), the resolution and report (P), R and J (QUALIFIED, R < D) or
    FAILED; then the legacy seal selection over QUALIFIED slots and the legacy stop (display-only <slot>.after.json,
    OQ-11/E5.2). The stored report is final before J; the returned dict adds the post-J outcome."""
    import s1_slot
    gv = s1_trial.gate(root, "checkpoint", mailbox=mailbox, now=now, defer_pending=True)   # A3 F0.6 (N2)
    out = Path(root) / "s1_out"
    pr = g.verified_registration(out, "checkpoint", mailbox, now)     # Task 12: A3.2 bundle first, then A8.2
    start, cal = c.aware(pr["start"]), pr["calendar"]
    day = _close_for(scheduled, cal)
    close = z.close_of(day["date"], cal)
    _no_local_abort(out, "checkpoint")
    with s1_slot.Worker(gv, scheduled, day, cal, slot_gate=s1_slot.post_start_gate(gv.trial), mailbox=mailbox,
                        now=now) as w:
        lost = w.intent()
        if lost is not None:                                        # F1: STOPPED -> LOST-RACE, no capture
            return lost
        cap_dir, t0 = w.cap_dir, now()
        refused = _clock_refusal(cap_dir, day, cal, close, scheduled, t0)
        if refused is not None:                                    # A5.2 (t < s; t >= E cannot reach here)
            return dict(refused, journal=w.complete(refused, success=False))
        state_err = _trial_stop_error(out, start, cal, t0, mailbox)   # A2.1 / I-4b: corrupt stop or seal records
        meta, rep = _capture(close, scheduled, live_db, cap_dir, now, z.eligible_until(scheduled, day, cal))
        actual = c.aware(rep["actual"])
        proc, rec = _observe_process(out, rep, process_fn, crash_log)
        binding_changed = _binding(rep, proc, pr.get("process_binding"))  # B2: the opening-bound reference
        receipt, receipt_sha = _receipt(rep, receipt_fn, pr["receipt"])
        seals, seals_err = _read_seals(out, rep)                          # fix round 1 (I-4b): never a crash
        proj = _read_capture(cap_dir, meta, rep, lambda trades: (len(z.cohort(trades, start, close)),
                                                                 z.count_sold(trades, start, close)))
        fences, bridges = [], []
        if proj is not None and seals_err is None:
            fences = z.check_fences(seals, proj)
            bridges = z.check_bridge(seals, proj["trades"], start)             # Task 8b (§6/§11)
            rep["fence_violations"] = fences + bridges                         # unchanged legacy field
        failures = rep.get("failures") or {}
        reason = subtype = None
        if state_err is not None or seals_err is not None:              # fix round 1 (I-4b/m-4): corrupt records
            reason, subtype = f"bad seal record: {state_err or seals_err}", "seal-record"
        elif rep["receipt_match"] is False:
            reason, subtype = "semantic receipt changed", "receipt"
        elif failures.get("receipt", {}).get("terminal"):                  # A9.2: an established violation
            reason, subtype = f"semantic receipt changed: {failures['receipt']['reason']}", "receipt"
        elif binding_changed:                                               # A1.1: observed binding differs
            reason = "process binding changed (launcher/process binding evidence differs from the reference)"
            subtype = "binding"
        elif rep["fence_violations"]:
            reason, subtype = rep["fence_violations"], ("fence" if fences else "bridge")
        if reason is None and proj is not None and rep["consistent"] and rep["receipt_match"] is True \
                and not failures and not rep["late"]:
            try:                                               # Task 12 (A3): the bundle was verified first
                bridge = (z.bridge_record(proj["trades"], start, z.opening_close_of(start, cal)) if close >= start
                          else None)
            except ValueError as e:                            # Task 9 (c): a recorded refusal, never a crash
                rep["refused"] = f"bridge record unavailable: {e}"
            else:
                rep["candidate"] = _candidate(rep, meta, cap_dir, proc, rec, receipt, receipt_sha, bridge, False)
        if reason is not None:                                  # OQ-31: external first, then local; no slot row
            w.violation(subtype, reason, rep, receipt_sha)
            return dict(rep, stop=_abort_stop(c.load_abort(out) or {"reason": reason}),        # (display, A9.2)
                        journal={"kind": "TRIAL-INVALID", "reason": s1_slot.REASON_VIOLATION, "subtype": subtype})
        result = w.complete(rep, success=bool(rep.get("candidate")))
    if result["outcome"] != "APPEND":                           # REFUSE (late R) or LOST-RACE: no seal, no stop
        return dict(rep, journal=result)
    after = {"journal": result}
    after.update(_after_terminal(gv, w, out, day, cal, start, actual, rep, receipt_sha, now, mailbox))
    w.after(after)
    return dict(rep, **after)


def _no_local_abort(out: Path, where: str) -> None:
    """F8.1: while a local aborted.json exists (an observed violation, e.g. one whose TRIAL-INVALID could not
    commit) no new capture is started (a committed TRIAL-INVALID is already refused by the gate)."""
    if c.load_abort(out) is not None:
        raise SystemExit(f"{where} refused: s1_out/aborted.json exists (an observed violation, F8.1): no new capture")


def _seal_view(rep: dict, fin: dict) -> dict:
    """The legacy rep["seal"] / deferred / refused presentation of a finalize_close result (display only)."""
    view = {"seal": dict(rep.get("seal") or {"written": False, "sha256": None}), "scheduled": rep["scheduled"]}
    _apply_finalize(view, fin)
    view.pop("scheduled")
    return view


def _after_terminal(gv, w, out, day, cal, start, actual, rep, receipt_sha, now, mailbox) -> dict:
    """Task 6, after a committed QUALIFIED or FAILED: A3 Task 7 - the journal finalizer (s1_slot.finalize_close:
    TIMEOUT / MISSED rows, the seal/<close> stage from the first QUALIFIED slot, E2) for this close and every other
    pending close (the worker's gate is a slot path, defer_pending=True: ruling N2); a damaged QUALIFIED tree is
    TRIAL-INVALID (registration-artifact) there and refuses. Then the legacy persisted stop (A2.1; a corrupt seal record
    is the established violation `seal-record`, OQ-31: external first); Task 11 replaces it with TRIAL-STOP. Display
    only: what this returns goes to the returned dict and <slot>.after.json (E5.2)."""
    import s1_slot
    got = dict(_seal_view(rep, s1_slot.finalize_close(gv, day, cal, now, mailbox=mailbox)))    # A3 Task 7
    _finalize_others(gv, cal, start, day["date"], now, mailbox)
    _finalize_last_if_due(gv, cal, start, now, mailbox)      # A3 Task 11 fix round 1 (review C1): the W anchor
    z.decide_stop(gv, cal, start, now, mailbox=mailbox)     # A3 Task 11 (F2.2): TRIAL-STOP then stop.json, if met
    try:
        got["stop"] = _public(z.current_stop(out, start, cal, actual, "checkpoint", mailbox=mailbox))   # (F1)
        if (out / "stop.json").exists():
            got["stop_sha256"] = c.sha256_file(out / "stop.json")
    except (ValueError, KeyError, TypeError, b.BookError) as e:              # a bad seal record is corruption
        why = f"bad seal record: {e}"
        w.violation("seal-record", why, rep, receipt_sha)
        got["stop"] = _abort_stop(c.load_abort(out) or {"reason": why})
    return got


ENDED = z.ENDED


# ------------------------------------------------------------------ opening mode (Task 7b)
def _audit_calendar(out: Path, mailbox=None) -> tuple:
    """(plan, calendar) of the verified audit (s1_gates.verified_audit: COMPLETE, derived files and raw pages, plan
    and bundle binding, AUDIT-ACK identity/token/timing, pinned provider calendar). Task 12 (A8.2)."""
    if not (out / "audit" / "manifest.json").exists():
        raise SystemExit("opening refused: audit not COMPLETE (no audit manifest)")
    try:
        aud = g.verified_audit(out, mailbox)
    except g.Invalid as e:
        raise SystemExit(f"opening refused: audit not verified ({e})") from None
    return aud["plan"], aud["calendar"]


def _opening_day(out: Path, scheduled: datetime, mailbox=None) -> tuple:
    """(opening calendar row, calendar): plan.json + the verified audit calendar, never prereg.json. Refuses unless
    the plan's opening_close is the session immediately before planned START and `scheduled` is one of its slots."""
    if not (out / "plan.json").exists():
        raise SystemExit("opening refused: no plan.json")
    plan, cal = _audit_calendar(out, mailbox)
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


def _register_opening(out: Path, plan_day: str, receipt_p: Path, binding, seal_sha: str) -> None:
    """Addendum 2 B3.1: the opening registration (registry/opening.json), written just before the opening seal with
    the seal's sha256 (its bytes are known): plan, audit manifest, opening receipt and opening seal, plus the bound
    process-binding reference and the bundle."""
    c.register_stage(out, "opening", {"plan.json": c.sha256_file(out / "plan.json"),
                                      "audit/manifest.json": c.sha256_file(out / "audit" / "manifest.json"),
                                      receipt_p.relative_to(out).as_posix(): c.sha256_file(receipt_p),
                                      f"seals/{plan_day}.json": seal_sha},
                     process_binding=binding, bundle_sha256=c.bundle_sha256())


def _store_opening_receipt(p: Path, receipt: dict) -> None:
    """Controller ruling 3: written BEFORE the opening seal (a receipt without a seal is harmless: attest_start needs
    both). Exclusive create; a stored receipt equal to this run's is kept as it is."""
    try:                                                   # fix round 3 (C-1): atomic; A3 Task 10 fix round 1 (M5, F6.6)
        c.publish_in_out(p, c.text_bytes(json.dumps(receipt, indent=1, sort_keys=True)), "opening")
    except FileExistsError:
        if _stored_receipt(p) != receipt:                   # a concurrent run stored one after the early check
            raise _ReceiptConflict(f"opening refused: stored {p.name} differs from this run's receipt") from None


class _ReceiptConflict(SystemExit):
    """A stored opening receipt differs from this run's (fix round 1, M-2: the capture report is written first)."""


class _OpeningSealConflict(SystemExit):
    """Fix round 5 (R-3): the opening seal about to be written differs from a recorded opening-seal hash."""


def _before_opening_seal(out: Path, day_iso: str, seal_sha: str, t: datetime, rows=None) -> None:
    """Fix round 5 (R-3): the serialized selection never writes an opening seal whose sha256 differs from a recorded
    opening-seal hash: the persistent "registration artifact" abort (a second, different opening seal). A3 Task 6
    (OQ-11, E2.6 r3): the recorded hashes are the REQUIRED seals of the journal (s1_common._report_seals), never a
    capture report or after.json. A3 Task 10 (Task 6 review M6): the opening seal is the `opening` stage, whose CREATED
    member is one of those required seals (s1_slot.required_seals), so a second, different opening seal is refused
    here and not only by the opening gate."""
    recorded = sorted({h for _, sp, h in c._report_seals(out, rows) if sp.name == f"{day_iso}.json"})
    if recorded and seal_sha not in recorded:
        probs = [f"seals/{day_iso}.json: the selected opening seal {seal_sha} differs from the recorded opening seal "
                 f"hash(es) {recorded} (a second, different opening seal)"]
        c.write_abort(out, {"reason": c.REGISTRATION_ARTIFACT, "where": "opening checkpoint", "problems": probs,
                            "observed_utc": t.isoformat(), "actual": None, "close": None, "scheduled": None,
                            "projection_sha256": None, "receipt_sha256": None})
        raise _OpeningSealConflict(f"opening refused: {probs[0]}: persistent ABORTED-INVALID (reason "
                                   f"{c.REGISTRATION_ARTIFACT})")


def _opening_stage(gv, out: Path, day, cal, now, mailbox) -> dict:
    """A3 Task 10 (F3, F4.8 'opening (seal)', E5.6): the opening seal as the F4 stage `opening` - kind single, member
    seals/<opening close>.json = s1_slot.seal_bytes of the first QUALIFIED opening slot's committed evidence; envelope
    inputs plan.json, audit/manifest.json, opening_receipt.json and that slot's QUALIFIED line + tree manifest;
    request_policy null; recovery F4.7 (s1_stage). F3: the INTENT is requested only once the close is determined - its
    first QUALIFIED slot committed and every earlier scheduled slot terminal (s1_slot.first_qualified) - and the
    stage's extra_gate re-checks exactly that selection inside the INTENT transaction (else refused, no row).
    Before the INTENT (pre-INTENT checks over committed inputs; no row on refusal): the opening close's F3 evidence,
    confirmed on re-read (Task 7 I1: a confirmed problem is TRIAL-INVALID registration-artifact); the QUALIFIED tree
    (s1_slot._resolution_evidence: QualifiedEvidence for the caller); opening_receipt.json published from that
    evidence BEFORE the seal is built (controller ruling 3 / OQ-15: an identical existing one is kept, a different one
    is _ReceiptConflict); the seal bytes buildable. before_publish: the R-3 second-seal guard (_before_opening_seal) and the legacy opening records
    (OQ-19). Never calls the trial gate (ruling N1). Returns {"opening": "already decided"} | {"deferred": why} |
    {"refused": why} | {"seal": {"written", "sha256", "from_slot"}}."""
    import s1_journal as j
    import s1_slot
    import s1_stage
    out = Path(out)
    rows = j.read_trial(gv.trial.trial_id, gv.trial.genesis, mailbox)
    if s1_stage.stage_rows(rows, "opening")["intent"] is not None:
        return {"opening": "already decided"}
    if c.load_abort(out) is not None:                       # F8.1: an observed violation - no further opening work
        return {"refused": "s1_out/aborted.json exists (an observed violation, F8.1): no opening seal"}
    q = s1_slot.first_qualified(rows, day, cal)
    if q is None:
        return {"deferred": "the opening close is not determined: an earlier opening slot is in flight or not yet "
                            "terminal, or no slot qualified yet (F3)"}
    probs = s1_slot.confirmed_close_problems(gv, out, rows, day, cal, mailbox)    # Task 7 I1: confirmed on re-read
    if probs:
        s1_slot.evidence_violation(gv, probs, "opening seal stage", mailbox, clock=now)
    ev = s1_slot._resolution_evidence(out, q, day["date"])
    close = z.close_of(day["date"], cal)
    rel = f"seals/{day['date']}.json"
    rp = out / "opening_receipt.json"
    _store_opening_receipt(rp, ev["candidate"]["receipt"])  # controller ruling 3: the receipt BEFORE the seal is built
    try:
        s1_slot.seal_bytes(day, close, ev)                 # pre-INTENT: the capture must equal its recorded projection
    except ValueError as e:
        return {"refused": f"seal refused: {e}"}
    inputs = {"plan.json": c.sha256_file(out / "plan.json"),
              "audit/manifest.json": c.sha256_file(out / "audit" / "manifest.json"),
              "opening_receipt.json": c.sha256_file(rp), "qualified_line": q.sha, "tree_manifest": q.detail}

    def selected(rows_):                                   # F3, inside the INTENT transaction (step 5)
        fq = s1_slot.first_qualified(rows_, day, cal)
        return None if fq is not None and fq.sha == q.sha else \
            "the opening close's first QUALIFIED slot with every earlier slot terminal is not this one (F3)"

    def work(sw):
        sw.put(rel, s1_slot.seal_bytes(day, close, ev))
        return []

    _, before = opening_publish_hooks(gv, inputs, now)    # (fix round 1, I1: the same path F4.7 recovery uses)
    try:
        com = s1_stage.run(gv, "opening", inputs=inputs, acks={}, work=work, mailbox=mailbox, clock=now,
                           extra_gate=selected, before_publish=before)
    except (_OpeningSealConflict, _ReceiptConflict):
        raise
    except SystemExit as e:                                # refusal / pending / lock error / INVALID: no seal here
        return {"refused": str(e)}
    return {"seal": {"written": True, "sha256": com["members"][rel], "from_slot": ev["scheduled"]}}


def opening_publish_hooks(gv, inputs, clock=None) -> tuple:
    """The `opening` stage's publication hooks (s1_stage.PUBLISH_HOOKS; the stage run and F4.7 recovery alike - A3
    Task 10 fix round 1, review I1): no publish_ctx; before_publish = the R-3 second-opening-seal guard
    (_before_opening_seal, Task 6 M6) over the trial's rows read through the GATE's mailbox (review M4), then the
    legacy opening records (B3.1, OQ-19) with the process-binding reference read from the staged seal member itself
    (the bytes the PREPARED commitment binds)."""
    import s1_journal as j
    import s1_stage
    out = Path(gv.out)
    clock = clock or c.now_utc
    day_iso = c.load_json(out / "plan.json")["opening_close"]
    rel = f"seals/{day_iso}.json"

    def before(com):
        rows = j.read_trial(gv.trial.trial_id, gv.trial.genesis, gv.mailbox)
        _before_opening_seal(out, day_iso, com["members"][rel], clock(), rows)                # fix5 (R-3), M6
        seal = json.loads((s1_stage.staging_dir(gv.root, gv.trial.trial_id, "opening") / rel).read_bytes())
        _register_opening(out, day_iso, out / "opening_receipt.json",
                          (seal.get("process_binding") or {}).get("binding"), com["members"][rel])
    return None, before


def _opening_view(rep: dict, fin: dict, got: dict) -> dict:
    """The legacy rep["seal"] / deferred / refused presentation of the opening close (display only, E5.2)."""
    view = {"seal": dict(rep.get("seal") or {"written": False, "sha256": None})}
    if "seal" in got:
        view["seal"] = {"written": True, "sha256": got["seal"]["sha256"]}
        if got["seal"]["from_slot"] != rep["scheduled"]:
            view["seal"]["from_slot"] = got["seal"]["from_slot"]
    for k_ in ("deferred", "refused"):
        why = got.get(k_) or (fin.get(k_) if "seal" not in got and "opening" not in got else None)
        if why and why != "the opening close is sealed by the opening stage (Task 10)":
            view[k_] = why
    if fin.get("cleanup"):
        view["cleanup"] = fin["cleanup"]
    return view


def run_opening_checkpoint(root, live_db, scheduled, receipt_fn, process_fn, crash_log, now=c.now_utc,
                           mailbox=None) -> dict:
    """Seal ONLY the opening close (§4/§6/§12), before the START attestation / RUN-ACK / prereg. Same capture,
    consistency, fence, no-overwrite and rerun rules as run_checkpoint; the receipt captured here is the reference
    every later seal must match (written to s1_out/opening_receipt.json for attest_start). Counts-only report.
    Controller ruling 3: opening_receipt.json is written BEFORE the seal. A receipt left by an earlier run that crashed
    before sealing is kept if it equals this run's receipt; if it differs, this run refuses (no seal, the stored
    receipt is left untouched for the operator). Task 12: bundle first (A3.2), the verified AUDIT-ACK'd audit and
    its pinned calendar (A8.2/A6), the clock (A5.2), failures preserved (A9.1), slot-order seal.
    A3 Task 6: the same slot worker as run_checkpoint (slot lock, SLOT-INTENT, P, R, J) with the opening gate (F1:
    the audit stage CREATED; E5.6: once the opening is decided a later opening-close slot is refused with no row,
    which replaces fix round 5's after-seal record); the seal is selected over QUALIFIED slots only.
    A3 Task 10: after J, the journal finalizer on the opening close (s1_slot.finalize_close: TIMEOUT at D, MISSED at
    E, never a file in a live or no-row slot, E1.4; the worker's gate is a slot path, defer_pending=True, N2) and then
    the `opening` stage (_opening_stage). The legacy _opening_selection, its resolution-file reads and the N-2 orphan
    re-check before the build are gone (F3 supersedes them)."""
    import s1_journal as j
    import s1_slot
    gv = s1_trial.gate(root, "opening checkpoint", mailbox=mailbox, now=now, defer_pending=True)   # A3 F0.6 (N2)
    out = Path(root) / "s1_out"
    c.verify_bundle_first(out, "opening checkpoint", mailbox=mailbox, now=now, need="audit")    # Task 12: A3.2
    day, cal = _opening_day(out, scheduled, mailbox)                                             # A8.2
    close = z.close_of(day["date"], cal)
    _no_local_abort(out, "opening checkpoint")
    rp = out / "opening_receipt.json"
    with s1_slot.Worker(gv, scheduled, day, cal, slot_gate=s1_slot.opening_gate(gv.trial, out), mailbox=mailbox,
                        now=now) as w:
        lost = w.intent()
        if lost is not None:
            return lost
        cap_dir, t0 = w.cap_dir, now()
        refused = _clock_refusal(cap_dir, day, cal, close, scheduled, t0)
        if refused is not None:
            refused.update(entries=NA, sold=NA, stop=NA)
            return dict(refused, journal=w.complete(refused, success=False))
        meta, rep = _capture(close, scheduled, live_db, cap_dir, now, z.eligible_until(scheduled, day, cal))
        rep.update(entries=NA, sold=NA, stop=NA)
        proc, rec = _observe_process(out, rep, process_fn, crash_log)
        _binding(rep, proc, None)                                   # B2.1: the observed binding IS the reference
        if rep["process_binding"]["status"] != "REFERENCE" and "process_binding" not in rep.get("failures", {}):
            rep.setdefault("failures", {})["process_binding"] = {
                "class": "BindingUnavailable", "terminal": False,
                "reason": f"the opening requires an observed process binding (B2.1): "
                          f"{rep['process_binding'].get('reason')}"}
        receipt, receipt_sha = _receipt(rep, receipt_fn, None)      # the opening receipt IS the reference
        proj = _read_capture(cap_dir, meta, rep, None)    # fix round 1 (M-1): read before any refusal
        seals, seals_err = _read_seals(out, rep)                 # fix round 1 (I-4b): preserved, never a crash
        if proj is not None and seals_err is None:
            rep["fence_violations"] = z.check_fences(seals, proj)
        if receipt_sha is not None and rp.exists() and _stored_receipt(rp) != receipt:   # leftover, crashed before seal
            rep["receipt_match"] = False
            rep["refused"] = f"receipt conflict: stored {rp.name} differs from this run's receipt"
            w.complete(rep, success=False)                # never sealed on this path (FAILED)
            raise SystemExit(f"opening refused: stored {rp.name} differs from this run's receipt (no opening seal "
                             f"exists; remove it only after checking which receipt is right)")
        if proj is not None and rep["consistent"] and not rep["fence_violations"] and receipt_sha is not None \
                and not rep.get("failures") and not rep["late"]:
            rep["candidate"] = _candidate(rep, meta, cap_dir, proc, rec, receipt, receipt_sha, None, True)
        result = w.complete(rep, success=bool(rep.get("candidate")))
    if result["outcome"] != "APPEND":
        return dict(rep, journal=result)
    after = {"journal": result}
    try:                                                  # A3 Task 10 (Task 7 concern 7): the journal finalizer on the
        fin = s1_slot.finalize_close(gv, day, cal, now, mailbox=mailbox)       # opening close (TIMEOUT / MISSED rows;
        after.update(_opening_view(rep, fin, _opening_stage(gv, out, day, cal, now, mailbox)))   # a slot path, N2),
    except _ReceiptConflict as e:                         # then the `opening` stage (F3, F4.8)
        w.after(dict(after, receipt_match=False, refused=f"receipt conflict (concurrent): {e}"))
        raise
    except _OpeningSealConflict as e:                     # R-3 / M6: never a second opening seal
        w.after(dict(after, refused=str(e)))
        raise
    except s1_slot.QualifiedEvidence as e:                # F3: a committed tree damaged
        _qualified_violation(gv, w, out, e, now)
    except j.JournalError as e:
        raise SystemExit(f"opening seal stage refused: journal unreadable ({type(e).__name__}): no seal") from None
    w.after(after)
    return dict(rep, **after)


# ------------------------------------------------------------------ final-snapshot mode (Task 7b)
def _trial_state(out: Path, pr: dict, t: datetime, *, mailbox=None) -> tuple:
    """(status, stop_close) of a trial that has ended, for the report (the command refuses outside STOPPED first:
    OQ-16); refuses while it is RUNNING. Task 12 (A2.1): the persisted stop; an abort keeps its frozen stop close
    (when one was persisted) for the slices. A3 Task 13 (OQ-16): it reads the journal's stop only - it never
    finalizes a close and never appends a slot row (the final snapshot is never sampled history)."""
    if c.load_abort(out) is not None:                   # terminal; a persisted stop keeps its frozen slices
        st_ = z.load_stop(out)
        return "ABORTED-INVALID", (st_ or {}).get("stop_close")
    try:                                                # A3 Task 7 (review N-1, F0.7): inside the try, mailbox threaded
        st_ = z.current_stop(out, c.aware(pr["start"]), pr["calendar"], t, "final snapshot", mailbox=mailbox)
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


def run_final_snapshot(root, live_db, now=c.now_utc, mailbox=None) -> dict:
    """The acquisition-time capture after the stop, fence-checked against EVERY seal of a close <= the stop (§6;
    Task 11 C-1: a seal after the stop is not a trial slice). Never seals; no prices or PnL. Controller ruling 2: each run is one attempt preserved under s1_out/final_snapshot/attempt-NN/ (meta.json +
    its own report.json). The first SUCCESSFUL capture (ok=True) also writes s1_out/final_snapshot/report.json and is
    final: any later run refuses, so a fence violation it records can never be retried away. A failed attempt (e.g. a
    locked DB) leaves no report.json, so a later run may try again. Fix round 1 (I-1): the refusal is decided by the
    attempts (any attempt-NN/meta.json with ok=True), so a lost or deleted report.json never re-opens the capture.
    Task 12: bundle first and the verified registration (A3.2/A8.2); the stop is the persisted one (A2.1)."""
    gv = s1_trial.gate(root, "final snapshot", mailbox=mailbox, now=now)          # A3 F0.6: the gate first
    if gv.state != "STOPPED":                                                     # A3 Task 13 (OQ-16)
        raise SystemExit("final snapshot refused: the trial is not STOPPED (OQ-16)")
    out = Path(root) / "s1_out"
    c.verify_bundle_first(out, "final snapshot", mailbox=mailbox, now=now,          # fix round 2 (B3): the gate
                          gate_refuses=False)                                         # first; it records (A2.3)
    if not (out / "prereg.json").exists():
        raise SystemExit("final snapshot refused: no prereg (the trial never started)")
    g.verified_registration(out, "final snapshot", mailbox, now, gate_refuses=False)   # A3.2 bundle, then A8.2
    gv = s1_trial.gate(root, "final snapshot", mailbox=mailbox, now=now)   # A3 (F1, F8.1, OQ-19; review I-2): a
    return _final_snapshot_capture(out, live_db, now, mailbox=mailbox)   # violation the legacy detector just
    #                                                                     committed: no capture


def _final_snapshot_capture(out: Path, live_db, now, *, mailbox=None) -> dict:
    """The final snapshot's capture and fence check, after every gate of run_final_snapshot (split out in Task 5 fix
    round 1 so the fence logic is reachable at unit level; run_final_snapshot is its only product caller)."""
    t = now()
    status, stop_close = _trial_state(out, _load(out / "prereg.json"), t, mailbox=mailbox)
    d = out / "final_snapshot"
    if (d / "report.json").exists() or ok_attempts(d):    # fix round 1 (I-1): any ok attempt is final
        raise SystemExit(f"final snapshot already taken (a successful capture exists: "
                         f"{', '.join(ok_attempts(d)) or 'report.json'}): refusing")
    files = _seal_files(out)
    try:
        seals = [_load(p) for p in files]
        if stop_close is not None:      # Task 11 (controller-added), C-1: the trial's slices = closes <= the stop
            kept = [(p, x) for p, x in zip(files, seals) if c.aware(x["close"]) <= c.aware(stop_close)]
            files, seals = [p for p, _ in kept], [x for _, x in kept]
        probs = (z.stop_problems(out, c.aware(_load(out / "prereg.json")["start"]), _load(out / "prereg.json")
                                 ["calendar"], recheck=False) if z.load_stop(out) is not None else [])
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise SystemExit(f"final snapshot refused: bad seal record ({type(e).__name__}: {e})") from None
    d.mkdir(parents=True, exist_ok=True)
    attempt = _next_attempt(d)
    try:
        meta = s.take_snapshot(live_db, d / attempt, now=now)
    except FileExistsError:
        raise SystemExit(f"final snapshot refused: {attempt} already exists (concurrent run?)") from None
    rep = {"attempt": attempt, "taken_utc": t.isoformat(), "trial_status": status, "stop_close": stop_close,
           "capture_ok": meta["ok"], "capture_error": meta.get("error"),
           "projection_sha256": meta.get("projection_sha256"), "max_trade_id": meta.get("max_trade_id"),
           "n_trades": meta.get("n_trades"),
           "seals_checked": [{"file": p.name, "close": x.get("close"), "sha256": c.sha256_file(p)}
                             for p, x in zip(files, seals)],
           "fence_checked": False, "fence_violations": [], "bundle_sha256": c.bundle_sha256(),
           "stop_sha256": c.sha_or_absent(out / "stop.json")}
    if meta["ok"]:
        proj = _load(d / attempt / "projection.json")
        try:
            rep["fence_violations"] = z.check_fences(seals, proj)
            rep["fence_violations"] += z.check_bridge(seals, proj["trades"], c.aware(_load(out / "prereg.json")
                                                                                     ["start"]))   # Task 8b
        except (ValueError, KeyError, TypeError) as e:     # a malformed seal cannot vouch for anything
            rep["fence_violations"] = [f"bad seal record: {type(e).__name__}: {e}"]
        rep["fence_checked"] = True
        rep["fence_violations"] += [f"persisted stop: {x}" for x in probs]     # Task 12 (A2.3), recorded
    # A3 H2 (Erratum 2 Clarification 1 r2 C3.1; ruling NOP-2): written_utc is sampled ONCE, after every other field
    # is final and immediately before the first of the two publications, so the attempt report and the published
    # final_snapshot/report.json carry the same value. It is a LOWER BOUND only: a report cannot contain its own
    # publication time, and SCORE-ACK.created > written_utc does not prove the report existed before the ACK (C3.1).
    rep["written_utc"] = now().isoformat()
    c.publish_text_exclusive(d / attempt / "report.json", json.dumps(rep, indent=1))     # fix round 3 (C-1): atomic
    if meta["ok"]:
        try:
            c.publish_text_exclusive(d / "report.json", json.dumps(rep, indent=1))
        except FileExistsError:
            raise SystemExit("final snapshot already taken (a concurrent run succeeded first): refusing") from None
    return rep


# ------------------------------------------------------------------ CLI
def parse_mode(argv=None) -> tuple:
    """Exactly one mode per call: ('scheduled', t) | ('opening', t) | ('final-snapshot', None) | ('finalize', None)."""
    ap = argparse.ArgumentParser(description="S1 read-only checkpoint (counts and integrity only)")
    ap.add_argument("--scheduled", help="registered seal slot (aware ISO instant)")
    ap.add_argument("--opening", action="store_true", help="seal the opening close (with --scheduled)")
    ap.add_argument("--final-snapshot", action="store_true", help="acquisition-time snapshot after the stop")
    ap.add_argument("--finalize", action="store_true", help="journal finalizer + stop decision (A3 Task 11)")
    a = ap.parse_args(argv)
    if a.finalize:
        if a.opening or a.scheduled is not None or a.final_snapshot:
            ap.error("--finalize takes no other mode (exactly one mode per call)")
        return "finalize", None
    if a.final_snapshot:
        if a.opening or a.scheduled is not None:
            ap.error("--final-snapshot takes neither --opening nor --scheduled (exactly one mode per call)")
        return "final-snapshot", None
    if a.scheduled is None:
        ap.error("--scheduled is required (alone, or with --opening)")
    return ("opening" if a.opening else "scheduled"), c.aware(a.scheduled)


def main(argv=None):
    mode, scheduled = parse_mode(argv)
    def receipt(reference=None):                           # fix round 2 (I-1): the bound receipt, raw check first
        kw = {} if reference is None else {"reference": reference}
        return r.semantic_receipt(REPO, REPO / ".env", REPO / "runtime" / "python" / "python.exe", **kw)
    if mode == "finalize":                                 # A3 Task 11 fix round 1 (review C1): the finalizer command
        rep = run_finalizer(c.HERE)
    elif mode == "final-snapshot":
        rep = run_final_snapshot(c.HERE, LIVE_DB)
    elif mode == "opening":
        rep = run_opening_checkpoint(c.HERE, LIVE_DB, scheduled, receipt, r.process_identity, CRASH_LOG)
    else:
        rep = run_checkpoint(c.HERE, LIVE_DB, scheduled, receipt, r.process_identity, CRASH_LOG)
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
