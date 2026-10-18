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
every mode; the opening seal is registered (registry/opening.json) just before it is written."""
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
def _capture_dir(out: Path, day: str, scheduled: datetime) -> Path:
    return out / "captures" / day / scheduled.strftime("%Y%m%dT%H%M%SZ")


def _report_path(cap_dir: Path) -> Path:
    return cap_dir.parent / f"{cap_dir.name}.report.json"


def _claim_slot(out: Path, cap_dir: Path, scheduled: datetime, close: datetime, t: datetime, extra=None) -> None:
    """A5.2: one attempt per registered slot, preserved with its original scheduled time: the slot is claimed
    exclusively (captures/<day>/<slot>.attempt.json) before anything else; a duplicate execution is refused and
    recorded in reruns.jsonl (never overwrites a capture). `extra`: fields the claim also records (fix round 5,
    R-3: the opening seal an after-seal opening slot found)."""
    claim = cap_dir.parent / f"{cap_dir.name}.attempt.json"
    try:                                                   # fix round 3 (C-1): published atomically
        c.publish_text_exclusive(claim, json.dumps({"scheduled": scheduled.isoformat(), "invoked_utc": t.isoformat(),
                                                    "close": close.isoformat(), **(extra or {})}))
    except FileExistsError:
        with (out / "reruns.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"scheduled": scheduled.isoformat(), "actual": t.isoformat(),
                                "close": close.isoformat()}) + "\n")
        raise SystemExit(f"slot already captured (or attempted): {cap_dir}") from None


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


def _claim_path(cap_dir: Path) -> Path:
    return cap_dir.parent / f"{cap_dir.name}.attempt.json"


def _res_path(cap_dir: Path) -> Path:
    return cap_dir.parent / f"{cap_dir.name}.resolution.json"


def _late_path(cap_dir: Path) -> Path:
    return cap_dir.parent / f"{cap_dir.name}.late.json"


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


def _read_resolution(p: Path):
    """The slot's resolution record, None when absent; an unreadable one is corrupt evidence (ValueError)."""
    if not p.exists():
        return None
    try:
        rec = _load(p)
    except (OSError, ValueError) as e:
        raise ValueError(f"resolution record {p.name} unreadable ({type(e).__name__})") from None
    if not isinstance(rec, dict) or rec.get("outcome") not in (SUCCESS, FAILURE, MISSED, TIMEOUT):
        raise ValueError(f"resolution record {p.name} malformed")
    return rec


def _resolve(p: Path, rec: dict) -> dict:
    """B1.3: the ONE exclusive, irreversible transition of a slot: publish `rec` unless a resolution exists; returns
    the stored record (this one, or the earlier winner)."""
    rec = _jsonable(rec)
    try:
        c.publish_exclusive(p, json.dumps(rec, indent=1, sort_keys=True).encode("utf-8"))
    except FileExistsError:
        return _read_resolution(p)
    return rec


def _publish(cap_dir: Path, day, cal, rep: dict, now) -> dict:
    """B1.2/B1.3: resolve this invocation's own claimed slot. Published strictly before D = resolution_deadline:
    SUCCESS (a complete candidate) or FAILURE. At/after D, or when the slot was already resolved (an expiration won),
    the outcome is RESOLUTION-TIMEOUT: this late worker cannot replace it or seal; its evidence is preserved
    separately (<slot>.late.json). An observed violation was already persisted before this step (never erased).
    Fix round 3 (M-1): the publication time is read as late as possible (after the evidence is built, just before
    the bytes are written) and the instant the link is durable is read again afterwards; a link that landed at/after
    D (a slow fsync) is recorded as an overrun (<slot>.overrun.json and the report) - it cannot replace the winner."""
    sch = c.aware(rep["scheduled"])
    dl = z.resolution_deadline(sch, day, cal)
    ev = _evidence(rep)
    rp = _res_path(cap_dir)
    t = now()
    if t < dl and not rp.exists():
        mine = {"outcome": SUCCESS if rep.get("candidate") and _complete_success(ev) else FAILURE,
                "slot": sch.isoformat(), "deadline_utc": dl.isoformat(), "published_utc": t.isoformat(),
                "evidence": ev}
        rec = _resolve(rp, mine)
        if rec == _jsonable(mine):
            linked = now()
            rep["resolution"] = {"outcome": rec["outcome"], "published_utc": rec["published_utc"],
                                 "linked_utc": linked.isoformat()}
            if linked >= dl:
                _record_overrun(cap_dir, sch, t, linked, dl)
                rep["resolution"]["publication_overrun"] = True
            return rec
    else:
        rec = _resolve(rp, {"outcome": TIMEOUT, "slot": sch.isoformat(), "deadline_utc": dl.isoformat(),
                            "decided_utc": t.isoformat(), "decided_by": "late worker"})
    late = {"slot": sch.isoformat(), "observed_utc": t.isoformat(), "resolution": rec.get("outcome"),
            "evidence": ev}
    try:
        c.publish_exclusive(_late_path(cap_dir), json.dumps(_jsonable(late), indent=1).encode("utf-8"))
    except FileExistsError:
        pass
    rep["resolution"] = {"outcome": rec.get("outcome"), "late_evidence": _late_path(cap_dir).name}
    rep["late_evidence"] = True
    rep.pop("candidate", None)
    return rec


def _overrun_path(cap_dir: Path) -> Path:
    return cap_dir.parent / f"{cap_dir.name}.overrun.json"


def _record_overrun(cap_dir: Path, sch: datetime, t: datetime, linked: datetime, dl: datetime) -> None:
    """Fix round 3 (M-1): preserve that a resolution stamped before D became durable at/after D (reported only)."""
    rec = {"slot": sch.isoformat(), "published_utc": t.isoformat(), "linked_utc": linked.isoformat(),
           "deadline_utc": dl.isoformat(),
           "note": "the resolution was stamped before D but its durable link landed at/after D; the exclusive "
                   "resolution stands (an overrun cannot replace the winner, B1.3) and is reported"}
    try:
        c.publish_exclusive(_overrun_path(cap_dir), json.dumps(rec, indent=1).encode("utf-8"))
    except FileExistsError:
        pass


def _seal_bytes(day, close: datetime, ev: dict) -> bytes:
    """The bytes of the close's seal built from a SUCCESS resolution's evidence -
    deterministic, so every finalizer of the close builds the identical seal."""
    cand = ev["candidate"]
    cap_dir = Path(cand["dir"])
    proj_p = cap_dir / "projection.json"
    if not proj_p.is_file() or c.sha256_file(proj_p) != cand["projection_sha256"]:
        raise _NoSeal(f"candidate capture {cap_dir.name} differs from its recorded projection")
    proj = _load(proj_p)
    cap = {"scheduled": ev["scheduled"], "actual": ev["actual"], "capture_start": cand["capture_start"],
           "capture_end": cand["capture_end"], "ok": True, "consistent": True,
           "projection_sha256": cand["projection_sha256"], "dir": cand["dir"]}
    seal = {"close": close.isoformat(), "fence": z.fence(proj), "max_id": cand["max_id"], "trades": proj["trades"],
            "capture": cap, "restart_record": cand["restart_record"], "process": cand["process"],
            "process_binding": cand["process_binding"],
            "receipt_sha256": cand["receipt_sha256"], "receipt_match": True,
            "receipt_provenance": cand["receipt_provenance"], "bundle_sha256": cand["bundle_sha256"]}
    if cand.get("bridge") is not None:
        seal["bridge"] = cand["bridge"]
    return json.dumps(seal).encode("utf-8")


class _NoSeal(Exception):
    """The chosen candidate cannot be sealed (recorded as a refusal; the close may stay unsealed)."""


def finalize_close(out: Path, day, cal, t: datetime, before_seal=None, before_build=None) -> dict:
    """Addendum 2 B1.4 (amends A5.2): the serialized close-level selection. Walk the close's slots in ORIGINAL
    SLOT ORDER over their immutable resolution records: an unresolved slot that is claimed is PENDING until D (the
    selection waits; at/after D this finalizer publishes RESOLUTION-TIMEOUT), one never claimed waits until E
    (then MISSED); the first SUCCESS is the seal. Every record is exclusive and immutable and the seal bytes are a
    function of that record, so concurrent finalizers and restart replays write one identical seal. Respects a
    persisted stop and any abort (no seal). `before_build(candidate)` runs before the seal is built and
    `before_seal(candidate, seal_sha256)` just before it is written (the opening: receipt, then registry).
    Returns {"written", "sha256", "from_slot", "deferred", "refused"}."""
    out = Path(out)
    res = {"written": False, "sha256": None, "from_slot": None, "deferred": None, "refused": None}
    if c.load_abort(out) is not None or (out / "stop.json").exists():
        return res
    seal_p = out / "seals" / f"{day['date']}.json"
    if seal_p.exists():
        res["sha256"] = c.sha256_file(seal_p)
        return res
    close = z.close_of(day["date"], cal)
    for slot in z.schedule(day, cal):
        cap_dir = _capture_dir(out, day["date"], slot)
        rp = _res_path(cap_dir)
        rec = _read_resolution(rp)
        if rec is None:
            until = z.eligible_until(slot, day, cal)
            dl = z.resolution_deadline(slot, day, cal)
            if _claim_path(cap_dir).exists():
                if t < dl:
                    res["deferred"] = (f"earlier slot {slot.isoformat()} is claimed and pending (no published report "
                                       f"before its resolution deadline {dl.isoformat()}): the seal waits for slot "
                                       f"order (B1)")
                    return res
                rec = _resolve(rp, {"outcome": TIMEOUT, "slot": slot.isoformat(), "deadline_utc": dl.isoformat(),
                                    "decided_utc": t.isoformat(), "decided_by": "finalizer"})
            else:
                if t <= until:
                    res["deferred"] = (f"earlier slot {slot.isoformat()} unresolved (never claimed; its window is "
                                       f"open until {until.isoformat()}): the seal waits for slot order (A5.2)")
                    return res
                rec = _resolve(rp, {"outcome": MISSED, "slot": slot.isoformat(), "eligible_until": until.isoformat(),
                                    "decided_utc": t.isoformat()})
        if rec["outcome"] != SUCCESS:
            continue
        ev = rec.get("evidence")
        if not _complete_success(ev):
            raise ValueError(f"resolution record {rp.name} claims SUCCESS without complete evidence")
        if before_build is not None:
            before_build(ev["candidate"])
        try:
            data = _seal_bytes(day, close, ev)
        except _NoSeal as e:
            res["refused"] = f"seal refused: {e}"
            return res
        sha = c.sha256_bytes(data)
        if before_seal is not None:
            before_seal(ev["candidate"], sha)
        try:                                               # fix round 3 (C-1): atomic, never a partial seal
            c.publish_exclusive(seal_p, data)
        except FileExistsError:                            # a concurrent finalizer: the same bytes, or corruption
            if seal_p.read_bytes() != data:
                raise ValueError(f"seal {seal_p.name} differs from the serialized selection") from None
            res["sha256"] = sha
            return res
        res.update(written=True, sha256=sha, from_slot=ev["scheduled"])
        return res
    return res


def _apply_finalize(rep: dict, fin: dict) -> None:
    if fin["written"]:
        rep["seal"] = {"written": True, "sha256": fin["sha256"]}
        if fin["from_slot"] != rep["scheduled"]:
            rep["seal"]["from_slot"] = fin["from_slot"]
    for k_ in ("deferred", "refused"):
        if fin[k_]:
            rep[k_] = fin[k_]


def _finalize_others(out: Path, cal, start, current: str, t: datetime) -> None:
    """B1.4/B1.5: resolve and seal any OTHER unsealed close of the trial left pending (e.g. an earlier close whose
    last slots outlived W): D lies after W only for processing already captured evidence."""
    start_day = start.astimezone(c.NY).date().isoformat()
    rows = {d["date"]: d for d in cal}
    for day_dir in sorted((out / "captures").glob("*")):
        d = day_dir.name
        if d == current or d < start_day or d not in rows or (out / "seals" / f"{d}.json").exists():
            continue
        try:
            finalize_close(out, rows[d], cal, t)
        except ValueError:                                 # no next session / corrupt record: left for the score
            continue


def finalize_pending(out: Path, cal, start, t: datetime) -> None:
    """Fix round 3 (I-1): the serialized close-level selection (B1.4) of every unsealed post-START close, run by a
    command BEFORE it decides or freezes the stop (stop attestation, final plan, final snapshot): a SUCCESS whose
    seal a crashed worker never wrote is applied first, so no stop is frozen across it."""
    _finalize_others(Path(out), cal, start, "", t)


def _write_report(cap_dir: Path, rep: dict) -> None:
    """The capture report (one per claimed slot, exclusive; never overwritten; fix round 3 C-1: atomic)."""
    c.publish_text_exclusive(_report_path(cap_dir), json.dumps(rep, indent=1))


def _trial_stop(out: Path, start, cal, t: datetime):
    """A2: (state, error): the persisted stop (s1_out/stop.json), else the decision over the existing seals -
    persisted once if the trial has ended. Task 12 fix round 1 (I-4b, m-4): unreadable seal records or a persisted
    stop that has gone missing give (None, reason): a preserved integrity failure (the abort below), never a crash
    and never a silent recompute."""
    try:
        return _public(z.current_stop(out, start, cal, t, "checkpoint")), None
    except (ValueError, KeyError, TypeError, b.BookError) as e:
        return None, f"{type(e).__name__}: {e}"


def _stop_hash(out: Path, rep: dict) -> None:
    """m-4: once the stop is persisted every report records stop.json's sha256 (a later change or deletion of
    stop.json is then detectable: s1_seal.stop_problems / current_stop)."""
    if (out / "stop.json").exists():
        rep["stop_sha256"] = c.sha256_file(out / "stop.json")


def _public(st_: dict) -> dict:
    """The stop decision as reported (the internal `persisted` flag dropped)."""
    return {k_: v for k_, v in st_.items() if k_ != "persisted"}


# ------------------------------------------------------------------ scheduled (post-prereg) mode
def run_checkpoint(root, live_db, scheduled, receipt_fn, process_fn, crash_log, now=c.now_utc,
                   mailbox=None) -> dict:
    """One registered slot of one close. Order (Task 12): bundle FIRST, then the RUN-ACK registration (A3.2/A8.2);
    the persisted stop / invalidity (A2); the slot claim and the pre-capture clock check (A5.2); the capture
    (A9.1); receipt, process, fences; the persistent abort on an established violation (A9.2); the measured
    eligibility; the slot-order seal (A5.2); the stop decision, persisted when it ends the trial (A2.1)."""
    out = Path(root) / "s1_out"
    pr = g.verified_registration(out, "checkpoint", mailbox, now)     # Task 12: A3.2 bundle first, then A8.2
    start, cal = c.aware(pr["start"]), pr["calendar"]
    day = _close_for(scheduled, cal)
    close = z.close_of(day["date"], cal)
    cap_dir = _capture_dir(out, day["date"], scheduled)
    t0 = now()
    _claim_slot(out, cap_dir, scheduled, close, t0)                    # A5.2: duplicate execution prevented
    already = c.load_abort(out)                                       # fix round 2 (B3.4): corrupt fails closed
    state, state_err = _trial_stop(out, start, cal, t0) if already is None else (None, None)
    ended = already is not None or (state is not None and state["status"] in ENDED)
    until = z.eligible_until(scheduled, day, cal)
    refused = _clock_refusal(cap_dir, day, cal, close, scheduled, t0)
    if refused is not None:                                            # A5.2: no capture outside [s, E]
        if ended:
            refused.update(post_stop=True, stop=_abort_stop(already) if already is not None else state)
        _publish(cap_dir, day, cal, refused, now)                      # B1: a FAILURE resolves the claimed slot
        _write_report(cap_dir, refused)
        return refused
    meta, rep = _capture(close, scheduled, live_db, cap_dir, now, until)
    actual = c.aware(rep["actual"])
    proc, rec = _observe_process(out, rep, process_fn, crash_log)
    binding_changed = _binding(rep, proc, pr.get("process_binding"))  # B2: the opening-bound reference
    receipt, receipt_sha = _receipt(rep, receipt_fn, pr["receipt"])
    seals, seals_err = _read_seals(out, rep)                          # fix round 1 (I-4b): never a crash
    proj = _read_capture(cap_dir, meta, rep, lambda trades: (len(z.cohort(trades, start, close)),
                                                             z.count_sold(trades, start, close)))
    if proj is not None and seals_err is None:
        rep["fence_violations"] = z.check_fences(seals, proj)
        rep["fence_violations"] += z.check_bridge(seals, proj["trades"], start)   # Task 8b (§6/§11)
    if ended:
        # Task 11 (controller-added), C-1 / Task 12 (A2.2): after the persisted stop (or an abort) a capture is still
        # taken and recorded, but it never seals and never aborts: receipt and fence differences after the stop are
        # reported only (the final snapshot and the score check the frozen slices through the persisted stop).
        rep["post_stop"] = True
        rep["stop"] = _abort_stop(already) if already is not None else state
        _stop_hash(out, rep)
        _publish(cap_dir, day, cal, rep, now)
        _write_report(cap_dir, rep)
        return rep
    failures = rep.get("failures") or {}
    reason = None
    if state_err is not None or seals_err is not None:                # fix round 1 (I-4b/m-4): corrupt records
        reason = f"bad seal record: {state_err or seals_err}"
    elif rep["receipt_match"] is False:
        reason = "semantic receipt changed"
    elif failures.get("receipt", {}).get("terminal"):                  # A9.2: an established violation
        reason = f"semantic receipt changed: {failures['receipt']['reason']}"
    elif binding_changed:                                               # A1.1: observed binding differs
        reason = "process binding changed (launcher/process binding evidence differs from the reference)"
    elif rep["fence_violations"]:
        reason = rep["fence_violations"]
    if reason is not None:
        already = _write_abort(out, reason, rep, rep["snapshot"], receipt_sha)
    if already is None and proj is not None and rep["consistent"] and not rep["fence_violations"] \
            and rep["receipt_match"] is True and not failures and not rep["late"]:
        try:                                               # Task 12 (A3): the bundle was verified first
            bridge = (z.bridge_record(proj["trades"], start, z.opening_close_of(start, cal)) if close >= start
                      else None)
        except ValueError as e:                            # Task 9 (c): a recorded refusal, never a crash
            rep["refused"] = f"bridge record unavailable: {e}"
        else:
            rep["candidate"] = _candidate(rep, meta, cap_dir, proc, rec, receipt, receipt_sha, bridge, False)
    published = _publish(cap_dir, day, cal, rep, now)                  # B1.3: before D, or a late worker
    if already is None and not rep.get("late_evidence"):
        try:
            t_fin = now()
            _apply_finalize(rep, finalize_close(out, day, cal, t_fin))      # B1.4: serialized, slot order
            _finalize_others(out, cal, start, day["date"], t_fin)
        except ValueError as e:                                            # corrupt resolution / seal evidence
            already = _write_abort(out, f"bad resolution record: {e}", rep, rep["snapshot"], receipt_sha)
    if already is None:
        try:
            rep["stop"] = _public(z.current_stop(out, start, cal, actual, "checkpoint"))   # A2.1: persisted if ended
            _stop_hash(out, rep)
        except (ValueError, KeyError, TypeError, b.BookError) as e:              # a bad seal record is corruption
            already = _write_abort(out, f"bad seal record: {e}", rep, rep["snapshot"], receipt_sha)
    if already is not None:
        rep["stop"] = _abort_stop(already)
    rep["resolution"] = rep.get("resolution") or {"outcome": published.get("outcome")}
    _write_report(cap_dir, rep)
    return rep


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
    try:                                                   # fix round 3 (C-1): atomic
        c.publish_text_exclusive(p, json.dumps(receipt, indent=1, sort_keys=True))
    except FileExistsError:
        if _stored_receipt(p) != receipt:                   # a concurrent run stored one after the early check
            raise _ReceiptConflict(f"opening refused: stored {p.name} differs from this run's receipt") from None


class _ReceiptConflict(SystemExit):
    """A stored opening receipt differs from this run's (fix round 1, M-2: the capture report is written first)."""


class _OpeningEvidenceConflict(SystemExit):
    """Fix round 4 (N-2): opening-close evidence of an earlier opening attempt exists without its records."""


def _before_opening_build(out: Path, rp: Path, cand: dict) -> None:
    """Fix round 4 (N-2): the opening seal is never created over evidence of an earlier opening attempt (opening-
    close evidence left without its records, s1_common.opening_orphans - re-checked here, at seal creation, after the
    gate); then ruling 3: the opening receipt is stored before the seal is built."""
    orphans = c.opening_orphans(out)
    if orphans:
        raise _OpeningEvidenceConflict(f"opening refused: evidence of an earlier opening attempt {orphans[:3]}: no "
                                       f"second opening seal is ever written")
    _store_opening_receipt(rp, cand["receipt"])


class _OpeningSealConflict(SystemExit):
    """Fix round 5 (R-3): the opening seal about to be written differs from a recorded opening-seal hash."""


def _after_opening_seal(out: Path, day, cal, close: datetime, scheduled: datetime, cap_dir: Path, now) -> None:
    """Fix round 5 (R-3): an opening slot invoked after the opening seal exists leaves durable evidence binding that
    seal before it refuses (zero live callbacks, no capture): its exclusive slot claim and a refused report, BOTH
    recording the seal's sha256 ("after_seal"), with its resolution (B1.3) between them. A missing seal or one whose
    hash differs from either is then a registration problem (s1_common._report_seals) and the selection never writes
    such a seal (_before_opening_seal)."""
    seal_rel = f"seals/{day['date']}.json"
    sha = c.sha256_file(out / seal_rel)
    t = now()
    try:
        _claim_slot(out, cap_dir, scheduled, close, t, {"after_seal": {"seal": seal_rel, "sha256": sha}})
    except SystemExit:                                     # a rerun of this slot: its evidence is already there
        raise SystemExit(f"opening seal exists ({day['date']}): refusing (slot already claimed)") from None
    rep = _new_report(close, scheduled, t, {"ok": False}, z.eligible_until(scheduled, day, cal))
    rep.update(entries=NA, sold=NA, stop=NA, after_seal={"seal": seal_rel, "sha256": sha},
               refused=f"opening seal exists ({day['date']}, sha256 {sha}): no capture")
    _publish(cap_dir, day, cal, rep, now)
    _write_report(cap_dir, rep)
    raise SystemExit(f"opening seal exists ({day['date']}): refusing (recorded its sha256 in "
                     f"{_report_path(cap_dir).name})")


def _before_opening_seal(out: Path, day_iso: str, seal_sha: str, t: datetime) -> None:
    """Fix round 5 (R-3): the serialized selection never writes an opening seal whose sha256 differs from an
    opening-seal hash a capture report recorded (a written seal or an after-seal record): the persistent
    "registration artifact" abort (a second, different opening seal)."""
    recorded = sorted({h for _, sp, h in c._report_seals(out) if sp.name == f"{day_iso}.json"})
    if recorded and seal_sha not in recorded:
        probs = [f"seals/{day_iso}.json: the selected opening seal {seal_sha} differs from the recorded opening seal "
                 f"hash(es) {recorded} (a second, different opening seal)"]
        c.write_abort(out, {"reason": c.REGISTRATION_ARTIFACT, "where": "opening checkpoint", "problems": probs,
                            "observed_utc": t.isoformat(), "actual": None, "close": None, "scheduled": None,
                            "projection_sha256": None, "receipt_sha256": None})
        raise _OpeningSealConflict(f"opening refused: {probs[0]}: persistent ABORTED-INVALID (reason "
                                   f"{c.REGISTRATION_ARTIFACT})")


def run_opening_checkpoint(root, live_db, scheduled, receipt_fn, process_fn, crash_log, now=c.now_utc,
                           mailbox=None) -> dict:
    """Seal ONLY the opening close (§4/§6/§12), before the START attestation / RUN-ACK / prereg. Same capture,
    consistency, fence, no-overwrite and rerun rules as run_checkpoint; the receipt captured here is the reference
    every later seal must match (written to s1_out/opening_receipt.json for attest_start). Counts-only report.
    Controller ruling 3: opening_receipt.json is written BEFORE the seal. A receipt left by an earlier run that crashed
    before sealing is kept if it equals this run's receipt; if it differs, this run refuses (no seal, the stored
    receipt is left untouched for the operator). Task 12: bundle first (A3.2), the verified AUDIT-ACK'd audit and
    its pinned calendar (A8.2/A6), the slot claim and clock (A5.2), failures preserved (A9.1), slot-order seal."""
    out = Path(root) / "s1_out"
    c.verify_bundle_first(out, "opening checkpoint", mailbox=mailbox, now=now, need="audit")    # Task 12: A3.2
    day, cal = _opening_day(out, scheduled, mailbox)                                             # A8.2
    close = z.close_of(day["date"], cal)
    cap_dir = _capture_dir(out, day["date"], scheduled)
    if (out / "seals" / f"{day['date']}.json").exists():
        _after_opening_seal(out, day, cal, close, scheduled, cap_dir, now)                       # fix5 (R-3)
    t0 = now()
    _claim_slot(out, cap_dir, scheduled, close, t0)
    until = z.eligible_until(scheduled, day, cal)
    refused = _clock_refusal(cap_dir, day, cal, close, scheduled, t0)
    if refused is not None:
        refused.update(entries=NA, sold=NA, stop=NA)
        _publish(cap_dir, day, cal, refused, now)
        _write_report(cap_dir, refused)
        return refused
    meta, rep = _capture(close, scheduled, live_db, cap_dir, now, until)
    rep.update(entries=NA, sold=NA, stop=NA)
    proc, rec = _observe_process(out, rep, process_fn, crash_log)
    _binding(rep, proc, None)                                       # B2.1: the observed binding IS the reference
    if rep["process_binding"]["status"] != "REFERENCE" and "process_binding" not in rep.get("failures", {}):
        rep.setdefault("failures", {})["process_binding"] = {
            "class": "BindingUnavailable", "terminal": False,
            "reason": f"the opening requires an observed process binding (B2.1): {rep['process_binding'].get('reason')}"}
    receipt, receipt_sha = _receipt(rep, receipt_fn, None)          # the opening receipt IS the reference
    rp = out / "opening_receipt.json"
    proj = _read_capture(cap_dir, meta, rep, None)        # fix round 1 (M-1): read before any refusal
    seals, seals_err = _read_seals(out, rep)                     # fix round 1 (I-4b): preserved, never a crash
    if proj is not None and seals_err is None:
        rep["fence_violations"] = z.check_fences(seals, proj)
    if receipt_sha is not None and rp.exists() and _stored_receipt(rp) != receipt:   # leftover, crashed before seal
        rep["receipt_match"] = False
        rep["refused"] = f"receipt conflict: stored {rp.name} differs from this run's receipt"
        _publish(cap_dir, day, cal, rep, now)
        _write_report(cap_dir, rep)                       # never sealed on this path
        raise SystemExit(f"opening refused: stored {rp.name} differs from this run's receipt (no opening seal "
                         f"exists; remove it only after checking which receipt is right)")
    if proj is not None and rep["consistent"] and not rep["fence_violations"] and receipt_sha is not None \
            and not rep.get("failures") and not rep["late"]:
        rep["candidate"] = _candidate(rep, meta, cap_dir, proc, rec, receipt, receipt_sha, None, True)
    _publish(cap_dir, day, cal, rep, now)                 # B1.3

    def before_seal(cand, seal_sha):                      # B3.1: registered just before the seal is written
        _before_opening_seal(out, day["date"], seal_sha, now())                                 # fix5 (R-3)
        _register_opening(out, day["date"], rp, (cand.get("process_binding") or {}).get("binding"), seal_sha)
    if not rep.get("late_evidence"):
        try:
            _apply_finalize(rep, finalize_close(out, day, cal, now(), before_seal=before_seal,     # ruling 3:
                                                before_build=lambda cand: _before_opening_build(out, rp, cand)))
        except _ReceiptConflict as e:                     # fix round 1 (M-2): a concurrent run stored another
            rep["receipt_match"] = False
            rep["refused"] = f"receipt conflict (concurrent): {e}"
            _write_report(cap_dir, rep)
            raise
        except (_OpeningEvidenceConflict, _OpeningSealConflict) as e:     # N-2 / R-3: never a second opening seal
            rep["refused"] = str(e)
            _write_report(cap_dir, rep)
            raise
    _write_report(cap_dir, rep)
    return rep


# ------------------------------------------------------------------ final-snapshot mode (Task 7b)
def _trial_state(out: Path, pr: dict, t: datetime) -> tuple:
    """(status, stop_close) of a trial that has ended; refuses while it is RUNNING. Task 12 (A2.1): the persisted
    stop (s1_out/stop.json; persisted now if the trial has ended and it is absent); an abort keeps its frozen stop
    close (when one was persisted) for the slices."""
    if c.load_abort(out) is not None:                   # terminal; a persisted stop keeps its frozen slices
        st_ = z.load_stop(out)
        return "ABORTED-INVALID", (st_ or {}).get("stop_close")
    finalize_pending(out, pr["calendar"], c.aware(pr["start"]), t)        # B1.5 / fix round 3 (I-1): finalize first
    try:
        st_ = z.current_stop(out, c.aware(pr["start"]), pr["calendar"], t, "final snapshot")
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
    out = Path(root) / "s1_out"
    c.verify_bundle_first(out, "final snapshot", mailbox=mailbox, now=now,          # fix round 2 (B3): the gate
                          gate_refuses=False)                                         # first; it records (A2.3)
    if not (out / "prereg.json").exists():
        raise SystemExit("final snapshot refused: no prereg (the trial never started)")
    g.verified_registration(out, "final snapshot", mailbox, now, gate_refuses=False)   # A3.2 bundle, then A8.2
    t = now()
    status, stop_close = _trial_state(out, _load(out / "prereg.json"), t)
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
    c.publish_text_exclusive(d / attempt / "report.json", json.dumps(rep, indent=1))     # fix round 3 (C-1): atomic
    if meta["ok"]:
        try:
            c.publish_text_exclusive(d / "report.json", json.dumps(rep, indent=1))
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
    def receipt(reference=None):                           # fix round 2 (I-1): the bound receipt, raw check first
        kw = {} if reference is None else {"reference": reference}
        return r.semantic_receipt(REPO, REPO / ".env", REPO / "runtime" / "python" / "python.exe", **kw)
    if mode == "final-snapshot":
        rep = run_final_snapshot(c.HERE, LIVE_DB)
    elif mode == "opening":
        rep = run_opening_checkpoint(c.HERE, LIVE_DB, scheduled, receipt, r.process_identity, CRASH_LOG)
    else:
        rep = run_checkpoint(c.HERE, LIVE_DB, scheduled, receipt, r.process_identity, CRASH_LOG)
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
