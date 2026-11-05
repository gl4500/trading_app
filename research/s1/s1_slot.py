"""S1 slot rows and slot evidence (Addendum 3 rev 5 F3; Erratum 1 E1, E2.6, E5.1, E5.2, E5.6; OQ-10, OQ-11, OQ-13,
OQ-14, OQ-31, OQ-32, OQ-33).
Each slot: P (resolution, then report, durably published), R (a same-process clock reading after P), J (the
SLOT-QUALIFIED commit, R < D) or a SLOT-FAILED; T (a finalizer's SLOT-TIMEOUT, Task 7). The slot work lock is held
across read-work-append (F5.1 as amended by E1.1); terminal decisions are arbitrated by the journal transaction,
never by a lock (E1.2). Every JSON record a worker writes carries its op and actor; its capture directory carries
them through its claim (OQ-10). A loser (LOST-RACE) moves only its own uncommitted files to late/ and re-checks."""
import json
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
    previous close); SystemExit when no row does."""
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
    """E2.6 (Erratum 1 r3): the required post-START seals are exactly the CREATED `seal/<close>` stages, each with
    its committed member hash {member: sha256}. Nothing else makes a seal required (the r1/r2 `seals_checked` and
    published-committed set are removed, E2.7 r3). after.json is never read (E5.2). A CREATED stage whose committed
    commitment cannot be read contributes nothing here: that is s1_stage.evaluate's stage-replaced violation."""
    import s1_stage
    tids = {x.trial_id for x in rows}
    if len(tids) != 1:
        return {}
    tid = tids.pop()
    got = {}
    for stage in s1_stage.seal_stages(rows):
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
    decided (no opening STAGE-INTENT; before Task 10 also: no opening seal file). E5.6: once decided, a later
    opening-close slot is refused with no row (it ends MISSED at its E)."""
    def g(rows, subject):
        if j.first(j.subject_rows(rows, "stage/audit"), "STAGE-CREATED") is None:
            return "the audit stage is not CREATED: no opening capture"
        if j.first(j.subject_rows(rows, "stage/opening"), "STAGE-INTENT") is not None or \
                any((Path(out) / "seals").glob("*.json")):
            return "the opening is already decided: no further opening capture (E5.6)"
        return None
    return g


def slot_problems(out, rows, subject, cal) -> list:
    """Task 6: [] (Task 7 implements the F3 evidence table; this name is its per-slot entry point, the LOST-RACE
    re-check of the winner's committed evidence)."""
    return []


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
