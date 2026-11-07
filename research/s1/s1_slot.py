"""S1 slot rows and slot evidence (Addendum 3 rev 5 F3; Erratum 1 E1, E2.6, E5.1, E5.2, E5.6; OQ-10, OQ-11, OQ-13,
OQ-14, OQ-31, OQ-32, OQ-33).
Each slot: P (resolution, then report, durably published), R (a same-process clock reading after P), J (the
SLOT-QUALIFIED commit, R < D) or a SLOT-FAILED; T (a finalizer's SLOT-TIMEOUT, Task 7). The slot work lock is held
across read-work-append (F5.1 as amended by E1.1); terminal decisions are arbitrated by the journal transaction,
never by a lock (E1.2). Every JSON record a worker writes carries its op and actor; its capture directory carries
them through its claim (OQ-10). A loser (LOST-RACE) moves only its own uncommitted files to late/ and re-checks."""
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import s1_common as c
import s1_journal as j
import s1_locks as L
import s1_seal as z

REASON_VIOLATION = "established-violation"                                 # OQ-31
SUBTYPES = ("receipt", "binding", "fence", "bridge", "seal-record")         # OQ-31 ruling (E5.1)
CAPTURE_TREE = ("backup.sqlite3", "meta.json", "projection.json")          # OQ-32 ruling (E5.6): raw bytes in the tree


def slot_of(subject: str) -> datetime:
    return datetime.strptime(subject[len("slot/"):], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def day_for(slot, cal) -> dict:
    """The calendar row whose seal schedule contains `slot` (its CLOSE day: an overnight slot belongs to the
    previous close); SystemExit when no row does. A3 Task 7 (performance only; the evidence table calls this for
    every slot at every gate): a close's slots lie after its close and no later than 08:00 New York on its next
    session, before that session's close - so the owner can only be the LATEST session whose close precedes the slot;
    only that row's schedule is computed (any malformed row: the full scan below, as before)."""
    try:
        ny = slot.astimezone(c.NY).date().isoformat()
        latest = None
        for d in sorted((d for d in cal if d["date"] <= ny), key=lambda d: d["date"], reverse=True)[:2]:
            if z.close_of(d["date"], cal) < slot:                 # (a session's close is on its own date)
                latest = d
                break
    except (KeyError, TypeError, ValueError, AttributeError):
        latest = False
    if latest is None:
        raise SystemExit(f"{slot.isoformat()} is not a registered seal slot")
    if latest is not False:
        try:
            if slot in z.schedule(latest, cal):
                return latest
        except ValueError:
            pass
        raise SystemExit(f"{slot.isoformat()} is not a registered seal slot")
    for d in cal:
        try:
            if slot in z.schedule(d, cal):
                return d
        except ValueError:
            continue
    raise SystemExit(f"{slot.isoformat()} is not a registered seal slot")


def slot_times(cal):
    """subject -> (E, D) from the pinned calendar (F0.5 step 6)."""
    def f(subject):
        s = slot_of(subject)
        d = day_for(s, cal)
        return z.eligible_until(s, d, cal), z.resolution_deadline(s, d, cal)
    return f


def names(out, slot, day_iso) -> dict:
    n = slot.strftime("%Y%m%dT%H%M%SZ")
    d = Path(out) / "captures" / day_iso
    return {"claim": d / f"{n}.attempt.json", "report": d / f"{n}.report.json",
            "resolution": d / f"{n}.resolution.json", "capture": d / n, "after": d / f"{n}.after.json"}


def _rel(out, p) -> str:
    return Path(p).relative_to(out).as_posix()


def qualified_subjects(rows) -> frozenset:
    """The slot subjects with a SLOT-QUALIFIED row (the only slots a seal may be selected from, F3)."""
    return frozenset(r_.subject for r_ in rows if r_.kind == "SLOT-QUALIFIED")


def required_seals(out, rows) -> dict:
    """E2.6 (Erratum 1 r3): the required seals are exactly the CREATED `seal/<close>` stages (post-START) and the
    CREATED `opening` stage (below), each with its committed member hash {member: sha256}. Nothing else makes a seal
    required (the r1/r2 `seals_checked` and
    published-committed set are removed, E2.7 r3). after.json is never read (E5.2). A CREATED stage whose committed
    commitment cannot be read contributes nothing here: that is s1_stage.evaluate's stage-replaced violation.
    A3 Task 10 (Task 6 review M6): the CREATED `opening` stage's member seals/<opening close>.json is required too,
    so the R-3 second-opening-seal guard (s1_checkpoint._before_opening_seal, through s1_common._report_seals) and
    the registration detector see the committed opening seal - not only the opening gate."""
    import s1_stage
    tids = {x.trial_id for x in rows}
    if len(tids) != 1:
        return {}
    tid = tids.pop()
    got = {}
    for stage in ["opening"] + s1_stage.seal_stages(rows):
        if s1_stage.stage_rows(rows, stage)["created"] is None:
            continue
        try:
            got.update(s1_stage.committed_commitment(Path(out).parent, tid, stage, rows)["members"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return got


def tree_manifest(out, paths) -> dict:
    """{relpath under s1_out: sha256} of `paths` (bytes as written; F3). A missing path raises (OSError)."""
    out = Path(out)
    return {_rel(out, p): c.sha256_file(p) for p in sorted(Path(x) for x in paths)}


def qualified_tree(out, slot, day_iso) -> dict:
    """F3 + OQ-32 (E5.6): the QUALIFIED detail's tree - report, resolution and the capture's raw files."""
    n = names(out, slot, day_iso)
    return tree_manifest(out, [n["report"], n["resolution"]] + [n["capture"] / f for f in CAPTURE_TREE])


def failed_tree(out, slot, day_iso) -> dict:
    """F3: the FAILED detail's tree - the claim and the failure report."""
    n = names(out, slot, day_iso)
    return tree_manifest(out, [n["claim"], n["report"]])


def _carries(p: Path, actor: str) -> bool:
    try:
        rec = json.loads(Path(p).read_text(encoding="utf-8"))
        return isinstance(rec, dict) and rec.get("actor") == actor
    except (OSError, ValueError):
        return False


def committed_paths(out, rows, cal) -> set:
    """Every relpath a committed slot row binds (QUALIFIED/FAILED trees; conservatively the claim, report and
    resolution of either), so a LOST-RACE never moves a committed file. captures/<day> is the slot's CLOSE date,
    from the calendar."""
    got = set()
    for r_ in rows:
        if r_.kind not in ("SLOT-QUALIFIED", "SLOT-FAILED"):
            continue
        s = slot_of(r_.subject)
        try:
            day_iso = day_for(s, cal)["date"]
        except SystemExit:
            continue                                    # (no committed row names an unregistered slot)
        n = names(out, s, day_iso)
        got |= {_rel(out, n[k_]) for k_ in ("report", "resolution", "claim")}
        got |= {_rel(out, n["capture"] / f) for f in CAPTURE_TREE}
    return got


def move_own_late(out, slot, day_iso, actor, committed: set) -> list:
    """F0.5 LOST-RACE: move to late/<day>/<slot>/ only this actor's own files (claim/report/resolution carrying its
    actor; the capture directory through its own claim) that no committed manifest lists. Never touches a committed
    file or a file of another actor."""
    out, n = Path(out), names(out, slot, day_iso)
    own_claim = n["claim"].is_file() and _carries(n["claim"], actor)
    dest = out / "late" / day_iso / slot.strftime("%Y%m%dT%H%M%SZ")
    moved = []
    for key in ("resolution", "report", "capture", "claim"):            # the claim last: it vouches for the capture
        p = n[key]
        rel = _rel(out, p)
        if not p.exists() or rel in committed or any(x.startswith(rel + "/") for x in committed):
            continue
        mine = own_claim if key == "capture" else _carries(p, actor)
        if mine:
            dest.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(dest / p.name))
            moved.append(rel)
    return moved


def post_start_gate(trial):
    """F7.4: no post-START capture without the trial's S1-PREREG-ACK (a refusal with no row at F0.5 step 5)."""
    def g(rows, subject):
        return None if "S1-PREREG-ACK" in trial.acks else "no S1-PREREG-ACK: no post-START capture (F7.4)"
    return g


def opening_gate(trial, out):
    """F1 'stage gates and ACKs apply' for an opening-close slot: the audit stage CREATED, and the opening not yet
    decided. A3 Task 10: only the opening STAGE-INTENT decides "already decided" (the legacy seal-file clause is gone:
    a seal file with no opening INTENT is the F4 stage table's violation). E5.6: once decided, a later opening-close
    slot is refused with no row (it ends MISSED at its E). `out` is kept for the callers' signature."""
    def g(rows, subject):
        if j.first(j.subject_rows(rows, "stage/audit"), "STAGE-CREATED") is None:
            return "the audit stage is not CREATED: no opening capture"
        if j.first(j.subject_rows(rows, "stage/opening"), "STAGE-INTENT") is not None:
            return "the opening is already decided: no further opening capture (E5.6)"
        return None
    return g


class Worker:
    """One process's attempt at one slot (F3). Context manager: the slot work lock `slot-<s>` (F5.1/E1.1), taken
    before the pre-check read and held across INTENT, work and J. LockHeld -> refused "pending" (the only liveness
    evidence); LockError (ERROR_ACCESS_DENIED included) -> refused with no row and no liveness verdict (F5.5)."""

    def __init__(self, gv, slot, day, cal, *, slot_gate, mailbox=None, now=c.now_utc):
        import s1_trial
        self.gv, self.slot, self.day, self.cal, self.now, self.mailbox = gv, slot, day, cal, now, mailbox
        self.subject = j.slot_subject(slot)
        self.op, self.actor = j.new_nonce(), j.new_nonce()
        self.n = names(gv.out, slot, day["date"])
        self.cap_dir = self.n["capture"]
        self.ctx = s1_trial.product_context(gv.trial, cal, slot_gate=slot_gate)
        self.lock = L.OwnershipLock(gv.root, gv.trial.trial_id, L.slot_lock_name(self.subject))

    def __enter__(self):
        try:
            self.lock.acquire()
        except L.LockHeld:
            raise SystemExit(f"{self.subject}: pending - another process owns this slot (F5): no row, no work") \
                from None
        except L.LockError as e:
            raise SystemExit(f"{self.subject}: lock error ({e}): refused with no row and no liveness verdict "
                             f"(F5.5)") from None
        return self

    def __exit__(self, *exc):
        self.lock.release()
        return False

    def _append(self, req):
        try:
            return j.append(self.gv.trial.trial_id, self.gv.trial.genesis, req, self.ctx, mailbox=self.mailbox,
                            clock=self.now)
        except j.JournalError as e:                   # F0.7 / F8.3: an outage or a chain fault: no row, a refusal
            raise SystemExit(f"{self.subject}: {req.kind} not written ({type(e).__name__}: {e}): refused with no "
                             f"row") from None

    def _rows(self):
        try:
            return j.read_trial(self.gv.trial.trial_id, self.gv.trial.genesis, self.mailbox)
        except j.JournalError as e:
            raise SystemExit(f"{self.subject}: journal unreadable ({type(e).__name__}: {e}): refused with no "
                             f"row") from None

    def intent(self):
        """The restart pre-check under the lock (F3: a restarted process never opens a second INTENT), then
        SLOT-INTENT and the claim. Returns None to proceed, or a LOST-RACE record (STOPPED: no capture).
        Refusals and INVALID raise SystemExit."""
        if j.subject_rows(self._rows(), self.subject):
            raise SystemExit(f"{self.subject}: already has a journal row: a restart never re-intents (F3); the "
                             f"finalizer decides it")
        res = self._append(j.Request("SLOT-INTENT", self.subject, self.op, self.actor))
        if res.outcome == "LOST-RACE":
            return {"scheduled": self.slot.isoformat(), "outcome": "LOST-RACE", "reason": res.reason}
        if res.outcome == "INVALIDATE":
            raise SystemExit(f"{self.subject}: SLOT-INTENT -> INVALID ({res.reason})")
        if res.outcome != "APPEND":
            raise SystemExit(f"{self.subject}: SLOT-INTENT refused with no row: {res.reason}")
        self.intent_row = res.row
        c.publish_text_exclusive(self.n["claim"], json.dumps({
            "scheduled": self.slot.isoformat(), "invoked_utc": res.row.at,
            "close": z.close_of(self.day["date"], self.cal).isoformat(), "op": self.op, "actor": self.actor,
            "intent_seq": res.row.seq, "capture_dir": _rel(self.gv.out, self.cap_dir)}))     # OQ-10 ruling
        return None

    def complete(self, rep: dict, success: bool) -> dict:
        """P: the resolution, then the report (each carries op/actor; the report is final before J, E5.2); R; then J
        (QUALIFIED with at = R) or FAILED. Returns {kind, outcome, reason, R[, late, recheck]}; LOST-RACE moves
        this actor's own uncommitted files to late/ and re-checks; INVALIDATE raises."""
        import s1_checkpoint as ck
        ev = ck._evidence(rep)
        ok = bool(success and rep.get("candidate") and ck._complete_success(ev))
        sch = self.slot
        res_rec = {"outcome": ck.SUCCESS if ok else ck.FAILURE, "slot": sch.isoformat(),
                   "deadline_utc": z.resolution_deadline(sch, self.day, self.cal).isoformat(),
                   "published_utc": self.now().isoformat(), "evidence": ev, "op": self.op, "actor": self.actor}
        try:
            c.publish_exclusive(self.n["resolution"], json.dumps(ck._jsonable(res_rec), indent=1,
                                                                  sort_keys=True).encode("utf-8"))
            rep["resolution"] = {"outcome": res_rec["outcome"], "published_utc": res_rec["published_utc"]}
            c.publish_text_exclusive(self.n["report"], json.dumps(dict(rep, op=self.op, actor=self.actor),
                                                                  indent=1))
        except FileExistsError as e:                  # another writer's file: P cannot be this worker's - no J
            name = Path(getattr(e, "filename2", None) or e.filename or "a slot record").name
            raise SystemExit(f"{self.subject}: P not published ({name} "
                             f"exists and is not this worker's): no completion row; the finalizer decides (F3)") \
                from None
        r_ = self.now()                                                        # R (F3)
        if ok:
            req = j.Request("SLOT-QUALIFIED", self.subject, self.op, self.actor,
                            detail=j.detail_of(qualified_tree(self.gv.out, sch, self.day["date"])), r_at=r_)
        else:
            req = j.Request("SLOT-FAILED", self.subject, self.op, self.actor,
                            detail=j.detail_of(failed_tree(self.gv.out, sch, self.day["date"])))
        res = self._append(req)
        got = {"kind": req.kind, "outcome": res.outcome, "reason": res.reason, "R": r_.isoformat()}
        if res.outcome == "LOST-RACE":
            rows = self._rows()
            got["late"] = move_own_late(self.gv.out, sch, self.day["date"], self.actor,
                                        committed_paths(self.gv.out, rows, self.cal))
            got["recheck"] = slot_problems(self.gv.out, rows, self.subject, self.cal)
        if res.outcome == "INVALIDATE":
            raise SystemExit(f"{self.subject}: {req.kind} -> INVALID ({res.reason})")
        return got

    def after(self, record: dict) -> None:
        """E5.2: the display-only <slot>.after.json (seal and stop presentation), carrying op/actor (OQ-10). No check
        or decision ever reads it."""
        c.publish_text_exclusive(self.n["after"], json.dumps(dict(record, op=self.op, actor=self.actor), indent=1,
                                                             default=str))

    def violation(self, subtype, reason, rep, receipt_sha) -> None:
        """An established violation (A9.2) observed by this capture (OQ-31 ruling, E5.1): EXTERNAL FIRST -
        TRIAL-INVALID(established-violation) with `subtype` and the exact legacy reason - then the local first-wins
        aborted.json. If the journal cannot be written, invalidate() writes the local abort and refuses (the F8.1
        residual; nothing claims an external record). No terminal slot event is required first."""
        import s1_checkpoint as ck
        import s1_trial
        if subtype not in SUBTYPES:
            raise SystemExit(f"{self.subject}: unknown violation subtype {subtype!r}")
        legacy = reason if isinstance(reason, str) else list(reason)
        rec = {"subtype": subtype, "legacy_reason": legacy, "slot": self.slot.isoformat(),
               "snapshot": rep.get("snapshot"), "receipt_sha256": receipt_sha}
        try:
            s1_trial.invalidate(self.gv.trial, REASON_VIOLATION, rec, root=self.gv.root, mailbox=self.mailbox,
                                clock=self.now)
        finally:
            ck._write_abort(self.gv.out, reason, rep, rep.get("snapshot"), receipt_sha)    # first-wins, local


# ---------------------------------------------------------------- A3 Task 7: finalizer, F3 evidence table, seal stages
_SLOT_STEM = re.compile(r"\d{8}T\d{6}Z", re.ASCII)


class QualifiedEvidence(ValueError):
    """F3 table, QUALIFIED: a required file of the slot's committed tree is missing, changed or unparseable: INVALIDATE
    (registration-artifact); the seal is never built from it."""


def _empty() -> dict:
    return {"written": False, "sha256": None, "from_slot": None, "deferred": None, "refused": None, "cleanup": None}


def _schedule(day, cal) -> list:
    try:
        return z.schedule(day, cal)
    except ValueError:                                 # the last calendar day: no next session, no window
        return []


def first_qualified(rows, day, cal):
    """F3/OQ-14: walking the close's slots in schedule order, the first QUALIFIED one, provided every earlier slot is
    terminal (QUALIFIED, FAILED, TIMEOUT, MISSED); None otherwise. late/ files are never consulted."""
    for slot in _schedule(day, cal):
        term = j.first(j.subject_rows(rows, j.slot_subject(slot)), *j.TERMINAL)
        if term is None:
            return None
        if term.kind == "SLOT-QUALIFIED":
            return term
    return None


def determined(rows, day, cal):
    """E2.2 r3: close `day` is determined when its first QUALIFIED slot is committed and every earlier slot of the
    close is terminal; returns that QUALIFIED row (== first_qualified)."""
    return first_qualified(rows, day, cal)


def seal_bytes(day, close, ev) -> bytes:
    """The deterministic seal of a close from the SUCCESS evidence (moved unchanged from s1_checkpoint._seal_bytes;
    a capture that differs from its recorded projection is a ValueError)."""
    cand = ev["candidate"]
    cap_dir = Path(cand["dir"])
    proj_p = cap_dir / "projection.json"
    if not proj_p.is_file() or c.sha256_file(proj_p) != cand["projection_sha256"]:
        raise ValueError(f"candidate capture {cap_dir.name} differs from its recorded projection")
    proj = json.loads(proj_p.read_text(encoding="utf-8"))
    cap = {"scheduled": ev["scheduled"], "actual": ev["actual"], "capture_start": cand["capture_start"],
           "capture_end": cand["capture_end"], "ok": True, "consistent": True,
           "projection_sha256": cand["projection_sha256"], "dir": cand["dir"]}
    seal = {"close": close.isoformat(), "fence": z.fence(proj), "max_id": cand["max_id"], "trades": proj["trades"],
            "capture": cap, "restart_record": cand["restart_record"], "process": cand["process"],
            "process_binding": cand["process_binding"], "receipt_sha256": cand["receipt_sha256"],
            "receipt_match": True, "receipt_provenance": cand["receipt_provenance"],
            "bundle_sha256": cand["bundle_sha256"]}
    if cand.get("bridge") is not None:
        seal["bridge"] = cand["bridge"]
    return json.dumps(seal).encode("utf-8")


def _read_op(p: Path):
    try:
        rec = json.loads(Path(p).read_text(encoding="utf-8"))
        return rec.get("op") if isinstance(rec, dict) else None
    except (OSError, ValueError):
        return None


def move_leftovers(out, slot, day_iso, op, *, root=None, trial_id=None, rows=None, mailbox=None):
    """OQ-13 as amended by E1.4: after a committed TIMEOUT, move the losing op's uncommitted files to late/<day>/<slot>/
    ONLY when the slot work lock is acquirable (the worker is gone). While it is held the cleanup is deferred (returns
    None). Cleanup never decides anything; leftovers on a TIMEOUT slot are tolerated and never selectable either way
    (F3 table). Only a slot whose terminal row is a SLOT-TIMEOUT of `op` is cleaned (`rows`: the trial's verified rows,
    else the open trial's): a QUALIFIED or FAILED winner's files are never moved. A lock I/O error (F5.5) raises
    L.LockError (the caller reports the cleanup refused)."""
    out, sub = Path(out), j.slot_subject(slot)
    if rows is None:
        rows = c._open_trial_rows(mailbox)
    term = j.first(j.subject_rows(rows, sub), *j.TERMINAL)
    if term is None or term.kind != "SLOT-TIMEOUT" or term.op != op:
        return []
    if root is not None and not L.lock_acquirable(root, trial_id, L.slot_lock_name(sub)):
        return None                                                               # deferred: a live worker
    n = names(out, slot, day_iso)
    claim_op = _read_op(n["claim"])
    dest = out / "late" / day_iso / slot.strftime("%Y%m%dT%H%M%SZ")
    moved = []
    for key in ("resolution", "report", "capture", "claim"):                     # the claim last: it vouches
        p = n[key]
        if not p.exists():
            continue
        if (claim_op if key == "capture" else _read_op(p)) == op:
            dest.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(dest / p.name))
            moved.append(_rel(out, p))
    return moved


def _cleanup(gv, slot, day, timeout_row, mailbox):
    """E1.4: the leftovers of the TIMEOUT's (losing) op, moved only when the work lock is acquirable. Never decides
    anything; a lock I/O error (ERROR_ACCESS_DENIED included) or a move failure refuses the cleanup only."""
    try:
        moved = move_leftovers(gv.out, slot, day["date"], timeout_row.op, root=gv.root, trial_id=gv.trial.trial_id,
                               mailbox=mailbox)
    except L.LockError as e:
        return (f"{timeout_row.subject}: cleanup refused - lock error ({e}): no liveness verdict, nothing moved "
                f"(F5.5)")
    except OSError as e:
        return f"{timeout_row.subject}: cleanup refused ({type(e).__name__}): leftovers stay (tolerated, F3)"
    if moved is None:
        return f"{timeout_row.subject}: cleanup deferred - the slot work lock is held (E1.4)"
    return {"moved": moved} if moved else None


def _finalizer_append(gv, cal, req, mailbox, now):
    import s1_trial
    return j.append(gv.trial.trial_id, gv.trial.genesis, req, s1_trial.product_context(gv.trial, cal),
                    mailbox=mailbox, clock=now)


def finalize_close(gv, day, cal, now, *, mailbox=None, before_seal=None, before_build=None) -> dict:
    """F3 finalizer + the E2 seal stage, in schedule order over the JOURNAL. `gv`: the caller's gate, a deadline path
    (gate(..., defer_pending=True), ruling N2: a stalled stage lock never delays TIMEOUT or MISSED).
    E1 (PLAN-1): terminal decisions are arbitrated by the journal transaction alone. Per slot: no row and now >= E ->
    SLOT-MISSED (own op); INTENT, no terminal and now >= D -> SLOT-TIMEOUT (the INTENT's op, own actor). Neither takes,
    waits for or tests the slot work lock, so a live stalled worker never prevents TIMEOUT at D. After every decision,
    leftover cleanup of each TIMEOUT slot runs only if its work lock is acquirable (E1.4), else it is deferred.
    E2 r3 (A3-PR1-1): once the close is determined, its seal is the F4 stage `seal/<close>` (run_seal_stage); every
    decision of that stage is taken inside the F0.1 transaction (INVALID, STOP and CLOSE read from the same sqlite
    file). Any unexpected error refuses with no row (F0.7). `before_build` is unused. The opening close runs the same
    finalizer (A3 Task 10: s1_checkpoint.run_opening_checkpoint and the finalizer command), but its seal is the
    `opening` stage (s1_checkpoint._opening_stage), never run_seal_stage."""
    res = _empty()
    mailbox = gv.mailbox if mailbox is None else mailbox
    try:
        times = slot_times(cal)
        actor = j.new_nonce()
        timeouts = []
        for slot in _schedule(day, cal):
            sub = j.slot_subject(slot)
            e, d = times(sub)
            t_ = now()                                                   # t first, then the rows (Task 6 M1)
            mine = j.subject_rows(j.read_trial(gv.trial.trial_id, gv.trial.genesis, mailbox), sub)
            term = j.first(mine, *j.TERMINAL)
            if term is not None:                     # every slot is finalized, also after the first QUALIFIED one
                if term.kind == "SLOT-TIMEOUT":
                    timeouts.append((slot, term))
                continue
            intent = j.first(mine, "SLOT-INTENT")
            if (intent is None and t_ < e) or (intent is not None and t_ < d):
                res["deferred"] = (f"earlier slot {slot.isoformat()} has no row and its window is open until E "
                                   f"{e.isoformat()}: the seal waits for slot order (A5.2)" if intent is None else
                                   f"earlier slot {slot.isoformat()} is in flight (SLOT-INTENT, no terminal row; "
                                   f"pending until its TIMEOUT at D {d.isoformat()}): the seal waits for slot order "
                                   f"(F3, E1.3, E2.2)")
                break                                # later slots wait; the seal step below still runs
            req = (j.Request("SLOT-MISSED", sub, j.new_nonce(), actor) if intent is None
                   else j.Request("SLOT-TIMEOUT", sub, intent.op, actor))
            got = _finalizer_append(gv, cal, req, mailbox, now)                  # E1.2: no work lock here
            if got.outcome == "INVALIDATE":
                raise SystemExit(f"{sub}: {req.kind} -> INVALID ({got.reason})")
            if got.outcome == "REFUSE":
                res["deferred"] = f"{sub}: {req.kind} refused with no row ({got.reason})"
                break
            if got.outcome == "APPEND" and req.kind == "SLOT-TIMEOUT":
                timeouts.append((slot, got.row))
        cleanup = [x for x in (_cleanup(gv, s, day, row, mailbox) for s, row in timeouts) if x is not None]
        res["cleanup"] = (cleanup[0] if len(cleanup) == 1 else cleanup) or None      # after every decision (E1.4)
        return run_seal_stage(gv, day, cal, res, mailbox=mailbox, clock=now, before_publish=before_seal)
    except SystemExit:
        raise
    except Exception as e:                       # noqa: BLE001 - F0.7: unexpected errors fail closed, no row
        raise SystemExit(f"finalizer refused with no row ({type(e).__name__}: {e}) (F0.7)") from None


def seal_stage_name(day_iso: str) -> str:
    return f"seal/{day_iso}"                                                   # subject stage/seal/<close date>


def seal_gate(day, cal):
    """F0.5 step 5 for STAGE-INTENT seal/<c> (E2.2 r3), evaluated inside the transaction: ACTIVE is `permitted`'s
    check; here the close must be determined."""
    def g(rows):
        return None if determined(rows, day, cal) is not None else \
            f"close {day['date']} is not determined: no seal stage yet (E2.2)"
    return g


def seal_check(day, cal):
    """F0.5 step 4a for STAGE-INTENT seal/<c> (E2.2 r3): the INTENT's inputs must name the close's first QUALIFIED
    line and its tree detail; another choice is INVALIDATE (contradictory-stage)."""
    def chk(rows, subject, inputs):
        q = determined(rows, day, cal)
        if q is not None and (inputs.get("qualified_line") != q.sha or inputs.get("tree_manifest") != q.detail):
            return j.Decision("INVALIDATE", "contradictory-stage")
        return None
    return chk


def run_seal_stage(gv, day, cal, res=None, *, mailbox=None, clock=None, before_publish=None) -> dict:
    """E2.1 r3: the post-START seal of close `day` as the F4 stage seal/<close>: kind single, member
    seals/<close>.json, envelope inputs = the selected QUALIFIED line and its tree detail, request_policy null,
    INTENT -> staging -> PREPARED (the exact seal bytes) -> publication -> CREATED, with F4.7 recovery. The opening
    close is the `opening` stage (Task 10), never this one. Not determined: nothing; not ACTIVE: refused with no row
    (res["refused"]); INVALID between the reads: PREPARED is LOST-RACE (no decision); CLOSED: refused. The close's
    slot evidence is re-checked first (F3 table): a violation is TRIAL-INVALID (registration-artifact)."""
    import s1_stage
    res = res if res is not None else _empty()
    mailbox = gv.mailbox if mailbox is None else mailbox
    out = Path(gv.out)
    if day["date"] == _opening_date(out):
        res["deferred"] = res["deferred"] or "the opening close is sealed by the opening stage (Task 10)"
        return res
    rows = j.read_trial(gv.trial.trial_id, gv.trial.genesis, mailbox)
    q = determined(rows, day, cal)
    if q is None:
        return res
    stage = seal_stage_name(day["date"])
    member = s1_stage.single_member(out, stage)
    if s1_stage.stage_rows(rows, stage)["created"] is not None:
        res["sha256"] = required_seals(out, rows).get(member)
        return res
    probs = confirmed_close_problems(gv, out, rows, day, cal, mailbox)    # fix round 1 (review I1): confirmed
    if probs:
        evidence_violation(gv, probs, f"seal stage {stage}", mailbox)
    ev = _resolution_evidence(out, q, day["date"])
    close = z.close_of(day["date"], cal)

    def work(sw):                                             # after the INTENT (the barrier tests hook in here)
        sw.put(member, seal_bytes(day, close, ev))
        return []
    try:
        com = s1_stage.run(gv, stage, inputs={"qualified_line": q.sha, "tree_manifest": q.detail}, acks={},
                           work=work, mailbox=mailbox, clock=clock, before_publish=before_publish,
                           extra_gate=seal_gate(day, cal), stage_check=seal_check(day, cal))
    except SystemExit as e:                                   # refusal / LOST-RACE / pending / lock error: no seal
        res["refused"] = str(e)
        return res
    res.update(written=True, sha256=com["members"][member], from_slot=ev["scheduled"])
    return res


def stop_fence(cal, start):
    """E2.5 r3, F0.5 step 5 for TRIAL-STOP, evaluated INSIDE the TRIAL-STOP transaction on the rows read there:
    every post-START close determined by these rows must have a CREATED seal stage. A QUALIFIED that commits between
    the stop operation's seal pass and its append is inside this check, even when the stop record is unchanged."""
    def fence(rows):
        import s1_stage
        opening = z.opening_close_of(start, cal).astimezone(c.NY).date().isoformat()
        for d in z.eligible_sessions(start, cal):
            if d["date"] == opening:
                continue                                              # the opening seal is the `opening` stage
            if determined(rows, d, cal) is not None and \
                    s1_stage.stage_rows(rows, seal_stage_name(d["date"]))["created"] is None:
                return f"determined close {d['date']} has no CREATED seal stage (E2.5)"
        return None
    return fence


def _opening_date(out):
    try:
        return c.load_json(Path(out) / "plan.json").get("opening_close")
    except (OSError, ValueError, AttributeError):
        return None


def _resolution_evidence(out, q, day_iso) -> dict:
    s = slot_of(q.subject)
    try:
        tree = qualified_tree(out, s, day_iso)
        ev = json.loads(names(out, s, day_iso)["resolution"].read_text(encoding="utf-8"))["evidence"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise QualifiedEvidence(f"{q.subject}: a file of its QUALIFIED tree is missing or unreadable "
                                f"({type(e).__name__})") from None
    if j.detail_of(tree) != q.detail:
        raise QualifiedEvidence(f"{q.subject}: QUALIFIED tree differs from the committed detail (F3)")
    return ev


def slot_problems(out, rows, subject, cal) -> list:
    """The F3 evidence table for one slot subject (states from the journal; files as evidence):
    no row - any claim, capture, report or resolution; in flight (INTENT, no terminal) - a file carrying another op
    (or a capture directory its claim does not name, OQ-10); QUALIFIED - a file of the tree manifest missing, changed
    or unparseable; FAILED - its claim/report missing or changed; TIMEOUT - a seal citing the slot; MISSED - any file
    outside late/. late/ is never read. Also the LOST-RACE re-check of the winner's committed evidence."""
    out = Path(out)
    try:
        s = slot_of(subject)
        day_iso = day_for(s, cal)["date"]
    except (SystemExit, ValueError):
        return [f"{subject}: not a registered slot"]
    n = names(out, s, day_iso)
    mine = j.subject_rows(rows, subject)
    intent, term = j.first(mine, "SLOT-INTENT"), j.first(mine, *j.TERMINAL)
    present = [k_ for k_ in ("claim", "report", "resolution", "capture") if n[k_].exists()]
    if not mine:
        return [f"{subject}: {k_} exists with no journal row (F3)" for k_ in present]
    if term is None:                                                              # in flight
        bad, claim = [], None
        for k_ in present:
            if k_ == "capture":
                continue
            try:
                rec = json.loads(n[k_].read_text(encoding="utf-8"))
                ok = isinstance(rec, dict) and (rec.get("op"), rec.get("actor")) == (intent.op, intent.actor)
            except (OSError, ValueError):
                rec, ok = None, False
            if k_ == "claim" and ok:
                claim = rec
            if not ok:
                bad.append(f"{subject}: in-flight {k_} carries another op (F3)")
        if "capture" in present and (claim is None or claim.get("capture_dir") != _rel(out, n["capture"])):
            bad.append(f"{subject}: in-flight capture directory is not the one its claim names (OQ-10)")
        return bad
    if term.kind == "SLOT-QUALIFIED":
        try:
            ok = j.detail_of(qualified_tree(out, s, day_iso)) == term.detail
            json.loads(n["resolution"].read_text(encoding="utf-8"))
            json.loads(n["report"].read_text(encoding="utf-8"))
        except (OSError, ValueError):
            ok = False
        return [] if ok else [f"{subject}: QUALIFIED tree differs from the committed detail (a required file missing, "
                              f"changed or unparseable, F3)"]
    if term.kind == "SLOT-FAILED":
        try:
            ok = j.detail_of(failed_tree(out, s, day_iso)) == term.detail
        except OSError:
            ok = False
        return [] if ok else [f"{subject}: FAILED claim/report missing or changed (F3)"]
    if term.kind == "SLOT-TIMEOUT":
        seal = out / "seals" / f"{day_iso}.json"
        try:
            cites = seal.is_file() and json.loads(seal.read_text(encoding="utf-8"))["capture"]["scheduled"] == \
                s.isoformat()
        except (OSError, ValueError, KeyError, TypeError):
            cites = False
        return [f"{subject}: a seal cites a TIMEOUT slot (F3)"] if cites else []
    return [f"{subject}: MISSED slot has {k_} outside late/ (F3)" for k_ in present]                # MISSED


def close_problems(out, rows, day, cal) -> list:
    """slot_problems for every scheduled slot of close `day` (every QUALIFIED slot included, not only those reached
    in slot order; Task 6 review N-2)."""
    probs = []
    for slot in _schedule(day, cal):
        probs += slot_problems(out, rows, j.slot_subject(slot), cal)
    return probs


def confirmed_close_problems(gv, out, rows, day, cal, mailbox=None) -> list:
    """close_problems confirmed on rows re-read AFTER the problems were first observed (fix round 1, review I1: the
    same confirm-on-re-read as the gate hook). A legitimate slot file is always written after its row, so a later
    slot whose worker starts between the first read and the file scan is never a violation; a problem seen on both
    scans, the second on rows read after the first, is. A journal error is the caller's refusal (F0.7)."""
    first = close_problems(out, rows, day, cal)
    if not first:
        return []
    again = j.read_trial(gv.trial.trial_id, gv.trial.genesis, gv.mailbox if mailbox is None else mailbox)
    return [p for p in close_problems(out, again, day, cal) if p in first]


def _file_subjects(out) -> set:
    got = set()
    for p in sorted((Path(out) / "captures").glob("*/*")):
        stem = p.name.split(".", 1)[0]
        if _SLOT_STEM.fullmatch(stem):
            got.add("slot/" + stem)
    return got


def evidence_problems(out, rows, cal) -> list:
    """Every slot subject with rows, plus every captures/<day>/<slot>* file whose slot has no row (F3 table); and every
    post-START seal file that is not the recomputation from its first QUALIFIED slot (OQ-14). Seal stage state (a seal
    file with no PREPARED, a CREATED seal missing or changed) is s1_stage.evaluate's (E2.4/E2.6 r3); this function adds
    only the recomputation check of the bytes against the selected QUALIFIED evidence."""
    out = Path(out)
    subjects = {r_.subject for r_ in rows if r_.kind in j.SLOT_KINDS} | _file_subjects(out)
    probs = []
    for sub in sorted(subjects):
        probs += slot_problems(out, rows, sub, cal)
    oday = _opening_date(out)
    for seal in sorted((out / "seals").glob("*.json")):
        day_iso = seal.stem
        if day_iso == oday:
            continue                                                              # the opening stage (Task 10)
        day = next((d for d in cal if d["date"] == day_iso), None)
        q = first_qualified(rows, day, cal) if day is not None else None
        try:
            want = seal_bytes(day, z.close_of(day_iso, cal), _resolution_evidence(out, q, day_iso)) if q else None
            ok = want is not None and seal.read_bytes() == want
        except (OSError, ValueError, KeyError, TypeError):
            ok = False
        if not ok:
            probs.append(f"seals/{seal.name} is not the seal of its first QUALIFIED slot (OQ-14)")
    return probs


def _calendar(gv):
    """The registered calendar: the audit's pinned calendar.json when it hashes to the audit manifest's record (the
    calendar prereg is bound to, A8.2 - so an edited prereg.json never re-labels a slot); else prereg.json's; else the
    verified audit's. None when there is none yet."""
    out = Path(gv.out)
    try:
        man = c.load_json(out / "audit" / "manifest.json")
        if man["files"]["calendar.json"] == c.sha256_file(out / "audit" / "calendar.json"):
            return z.calendar_rows(c.load_json(out / "audit" / "calendar.json"))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    try:
        cal = c.load_json(out / "prereg.json")["calendar"]
        if isinstance(cal, list):
            return cal
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        import s1_gates
        return s1_gates.verified_audit(gv.out, gv.mailbox)["calendar"]
    except Exception:                                   # noqa: BLE001 - no verified calendar yet: no slot can exist
        return None


def evidence_violation(gv, probs, where, mailbox=None, clock=None):
    """F3 violation: TRIAL-INVALID (registration-artifact) first, then the local abort; refused with no work."""
    import s1_trial
    rec = {"where": where, "problems": list(probs[:20])}
    s1_trial.invalidate(gv.trial, "registration-artifact", rec, root=gv.root,
                        mailbox=gv.mailbox if mailbox is None else mailbox, clock=clock)
    if Path(gv.out).is_dir():                                       # (never recreates a lost s1_out)
        try:
            c.write_abort(gv.out, dict(rec, reason=c.REGISTRATION_ARTIFACT, actual=None, close=None, scheduled=None,
                                       projection_sha256=None, receipt_sha256=None))
        except OSError:
            pass
    raise s1_trial.Refusal(f"{where}: slot evidence violation {list(probs[:3])}: INVALID (registration-artifact)")


def _read_rows(gv) -> list:
    """The hook's own journal read (fix round 1, review M2, F0.7): a JournalError is a refusal with no row."""
    import s1_trial
    try:
        return j.read_trial(gv.trial.trial_id, gv.trial.genesis, gv.mailbox)
    except j.JournalError as e:
        raise s1_trial.Refusal(f"F3 evidence table: journal unreadable ({type(e).__name__}: {e}): refused with no "
                               f"row (F0.7)") from None


def _stray_files(out: Path) -> list:
    """The slot files a gate can see with no calendar to place them: every captures/<day>/* entry, and the opening
    close's seal file (written only from a QUALIFIED opening slot, so with no slot row it is a stray; since A3 Task 10
    the `opening` stage covers it and s1_stage.evaluate, which runs first, decides it - kept here harmlessly). Every
    other seals/<date>.json is a seal stage's, judged by s1_stage.evaluate (E2.4/E2.6 r3)."""
    out = Path(out)
    found = list((out / "captures").glob("*/*"))
    oday = _opening_date(out)
    if oday and (out / "seals" / f"{oday}.json").exists():
        found.append(out / "seals" / f"{oday}.json")
    return sorted(_rel(out, p) for p in found)


def _judge_without_calendar(gv, out) -> bool:
    """A3 Task 9 (Task 7 carry-forward N1; F3 'no row: any claim, capture, report or resolution', F4 'no INTENT: any
    artifact is a violation after the AUDIT-ACK', E2.4): no registered calendar is readable and the gate's rows have no
    slot row, yet slot/seal files exist. Every gate runs under an open trial, i.e. after the AUDIT-ACK, so such a file
    is a violation, never a silent pass. Confirmed on re-read (as evidence_check): rows read AFTER the files were
    first seen; the files still present on a second scan are the violation (TRIAL-INVALID registration-artifact, then
    the local abort, refused with no work). Returns True when the re-read now shows slot rows (the caller's fail-closed
    M3 refusal applies), False when nothing is left to judge."""
    first = _stray_files(out)
    if not first:
        return False
    if any(r_.kind in j.SLOT_KINDS for r_ in _read_rows(gv)):
        return True
    confirmed = [p for p in _stray_files(out) if p in first]
    if not confirmed:
        return False
    evidence_violation(gv, [f"{p} exists with no slot row and no registered calendar (F3, F4)" for p in confirmed],
                       "gate", gv.mailbox)
    return False                                                    # (unreachable: evidence_violation raises)


def evidence_check(gv) -> None:
    """Gate hook (F3 table), after the F6.2 plan check: a violation commits TRIAL-INVALID (registration-artifact) and
    refuses with no work. The rows are read here (not the gate's snapshot), and a problem is confirmed on rows re-read
    after it was first observed: a legitimate file is always written after its row, so a file seen before that re-read
    with no row in it is a violation, never a race with a starting worker (F5.1 lesson, Task 8 I1)."""
    out = Path(gv.out)
    has_files = any((out / "captures").glob("*/*")) or any((out / "seals").glob("*.json"))
    if not has_files and not any(r_.kind in j.SLOT_KINDS for r_ in gv.rows):
        return
    cal = _calendar(gv)
    if cal is None:
        if not any(r_.kind in j.SLOT_KINDS for r_ in gv.rows) and not _judge_without_calendar(gv, out):
            return                                                    # A3 Task 9 (N1): nothing left to judge
        import s1_trial                                               # fix round 1 (review M3): fail closed - an
        s1_trial._legacy_detectors(out, "F3 evidence table", None, gv.mailbox)       # unreadable registered calendar
        raise s1_trial.Refusal("slot rows exist but no registered calendar is readable (the F3 evidence table "  # is
                               "cannot run): refused with no row (fail closed)")      # first the legacy detector's
    first = evidence_problems(out, _read_rows(gv), cal)
    if not first:
        return
    confirmed = [p for p in evidence_problems(out, _read_rows(gv), cal) if p in first]
    if confirmed:
        evidence_violation(gv, confirmed, "gate", gv.mailbox)
