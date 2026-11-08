"""S1 stage engine (Addendum 3 rev 5 F4; Erratum 1 E2, E5.5). One stage = STAGE-INTENT (the input envelope, F4.1) ->
work in staging (<root>/s1_staging/<trial_id>/<stage>/, outside s1_out, F4.2) -> prepared.json + STAGE-PREPARED (the
one canonical output commitment, F4.3) -> exclusive publication into s1_out + STAGE-CREATED (same detail, F4.4). The
stage lock is taken before the journal read and held across read-work-append (F5.1). Recovery (F4.7) and the
stage-state table (evaluate) run under the same lock. Staging keeps intent.json and prepared.json for the trial's
life; both must hash to their rows (OQ-35). JSON members named in TRIAL_ID_MEMBERS record the trial_id (OQ-36).
A post-START seal is the stage `seal/<close date>` (E2.1 r3: kind single, member seals/<close>.json, policy null).
evaluate() runs inside the trial gate and never creates s1_out (F6.6); staging and locks live outside it."""
import contextlib
import json
import re
from pathlib import Path

import s1_common as c
import s1_journal as j
import s1_locks as L

TABLE = {"audit": {"kind": "tree", "pred": None, "ack": "S1-AUDIT-ACK", "state": "ACTIVE"},
         "opening": {"kind": "single", "pred": "audit", "ack": None, "state": "ACTIVE"},
         "start_attest": {"kind": "single", "pred": "opening", "ack": "S1-OPENING-ACK", "state": "ACTIVE"},  # OQ-15
         "prereg": {"kind": "single", "pred": "start_attest", "ack": "S1-RUN-ACK", "state": "ACTIVE"},
         "stop_attest": {"kind": "single", "pred": "TRIAL-STOP", "ack": None, "state": "STOPPED"},
         "final_plan": {"kind": "single", "pred": "stop_attest", "ack": None, "state": "STOPPED"},
         "final": {"kind": "tree", "pred": "final_plan", "ack": "S1-ACQUIRE-ACK", "state": "STOPPED"},
         "score": {"kind": "tree", "pred": "final", "ack": "S1-SCORE-ACK", "state": "STOPPED"}}
FIXED_TREE = {"audit": ("audit/attempt.json", "audit/calendar_source.json", "audit/calendar.json",
                        "audit/corporate_actions.json", "audit/ca_problems.json", "audit/manifest.json"),
              "final": ("final/attempt.json", "final/bars.json", "final/bar_problems.json",
                        "final/corporate_actions.json", "final/ca_problems.json", "final/manifest.json"),
              "score": ("score/attempt.json", "score/s1.json")}
SINGLE = {"opening": lambda out: f"seals/{c.load_json(Path(out) / 'plan.json')['opening_close']}.json",
          "start_attest": lambda out: "attest_start.json",                     # OQ-15: KEEP SINGLE
          "prereg": lambda out: "prereg.json", "stop_attest": lambda out: "attest_stop.json",
          "final_plan": lambda out: "final_plan.json"}
MANIFEST_STAGES = ("audit", "final")
TRIAL_ID_MEMBERS = {"audit": ("audit/attempt.json",), "start_attest": ("attest_start.json",),
                    "prereg": ("prereg.json",), "stop_attest": ("attest_stop.json",),
                    "final_plan": ("final_plan.json",), "final": ("final/attempt.json",),
                    "score": ("score/attempt.json", "score/s1.json")}
# A3 Task 14: every stage of TABLE is enforced by the gate. The transitional stage-set and seal-file switches of
# Tasks 8-13 are deleted; their final state (the stage set equal to TABLE, the seal-file switch on) is recorded in
# a3/t14_enforced_check.txt. evaluate() judges every TABLE stage, every seal stage with a journal row and every
# post-START seals/<date>.json on disk (E2.4 r3).
# A3 Task 10 fix round 1 (review I1): the owner's publication hooks of a stage - (publish_ctx factory, before_publish)
# built by `<module>.<function>(gv, inputs, clock)` from the INTENT envelope's inputs. The stage's command passes the
# same pair to run(), and F4.7 recovery calls it too, so a recovered stage publishes exactly what a completed run
# does, including the legacy registry/witness records. A3 Task 14 keeps them: OQ-19 keeps the legacy detectors as
# additional detectors and OQ-24 makes the two opening records damage-matrix elements, so the records and the
# hooks that write them stay (no task removes them). Imported lazily (owners import this module).
PUBLISH_HOOKS = {"opening": ("s1_checkpoint", "opening_publish_hooks"),
                 "start_attest": ("s1_run", "start_attest_publish_hooks"),
                 "prereg": ("s1_run", "prereg_publish_hooks")}
SEAL_PREFIX = "seal/"                                                         # E2.1 r3: stage seal/<close date>
SEAL_SPEC = {"kind": "single", "pred": None, "ack": None, "state": "ACTIVE"}
_SEAL_NAME = re.compile(r"seal/\d{4}-\d{2}-\d{2}", re.ASCII)


class Pending(SystemExit):
    """A live owner holds the stage lock (LockHeld): "pending", a refusal with no row and no work (F4 table). A
    slot-path gate may defer it instead (evaluate(defer_pending=True), ruling N2 / Erratum 1 E1.2)."""


class StageAbort(Exception):
    """A provider anomaly (provider-structural) or a score computation error (score-aborted): the staged evidence and
    an ABORTED record are kept, no PREPARED is appended, the trial becomes INVALID with this reason (F4.6, F4.9)."""

    def __init__(self, reason: str, record: dict):
        super().__init__(reason)
        self.reason, self.record = reason, record


class _Staging:
    def __init__(self, root, trial_id, stage):
        self.dir = staging_dir(root, trial_id, stage)
        self.files = {}

    def put(self, rel: str, data: bytes) -> Path:
        p = self.dir / rel
        c.publish_exclusive(p, data)
        self.files[rel] = bytes(data)
        return p


class StageWork:
    """What a stage's work function receives: staging writers (bytes kept in memory: F0.4), the INTENT row, the
    committed request policy (or None), the op/actor, mailbox and clock."""

    def __init__(self, gv, stage, staging, intent, policy, op, actor, mailbox, clock):
        self.gv, self.stage, self.staging, self.intent, self.policy = gv, stage, staging, intent, policy
        self.op, self.actor, self.mailbox, self.clock = op, actor, mailbox, clock

    @property
    def intent_at(self) -> str:
        return self.intent.at                                                  # F4.5

    @property
    def trial_id(self) -> str:
        return self.gv.trial.trial_id

    @property
    def files(self) -> dict:
        return self.staging.files

    def put(self, rel: str, data: bytes) -> Path:
        return self.staging.put(rel, data)

    def put_json(self, rel: str, obj) -> Path:
        """The exact bytes s1_collect._write_once publishes (json indent=1, sorted keys, platform newlines)."""
        return self.staging.put(rel, c.text_bytes(json.dumps(obj, indent=1, sort_keys=True)))


def staging_dir(root, trial_id: str, stage: str) -> Path:
    """E5.5 r4: <root>/s1_staging/<trial_id>/<stage>/, outside s1_out (a seal stage nests: .../seal/<date>/)."""
    return Path(root) / "s1_staging" / trial_id / stage


def envelope(trial_id, stage, inputs: dict, acks: dict, policy) -> dict:
    return {"trial_id": trial_id, "stage": stage, "inputs": dict(sorted(inputs.items())),
            "acks": dict(sorted(acks.items())), "request_policy": policy}


def commitment(trial_id, stage, op, kind, members: dict, provenance: list) -> dict:
    """F4.3 (revision 2: the r1 `seals_checked` field is removed with E2.7 r3)."""
    return {"trial_id": trial_id, "stage": stage, "op": op, "kind": kind, "members": dict(sorted(members.items())),
            "provenance": list(provenance)}


def spec(stage: str) -> dict:
    """The F4 stage table entry; every `seal/<YYYY-MM-DD>` stage (a real date) shares SEAL_SPEC (E2.1 r3). Any other
    unknown name is a KeyError (fail closed)."""
    if isinstance(stage, str) and _SEAL_NAME.fullmatch(stage) and j.stage_name_ok(stage):
        return SEAL_SPEC
    return TABLE[stage]


def _is_seal(stage: str) -> bool:
    return spec(stage) is SEAL_SPEC


def single_member(out, stage: str) -> str:
    if _is_seal(stage):
        return f"seals/{stage[len(SEAL_PREFIX):]}.json"                       # E2.1 r3: seals/<close>.json
    return SINGLE[stage](out)


def _opening_close(out):
    try:
        return c.load_json(Path(out) / "plan.json").get("opening_close")
    except (OSError, ValueError, AttributeError):
        return None


def seal_stages(rows) -> list:
    """Every seal stage name with any row in `rows` (evaluate iterates them next to TABLE)."""
    return sorted({r_.subject[len("stage/"):] for r_ in rows
                   if r_.kind in j.STAGE_KINDS and r_.subject.startswith("stage/" + SEAL_PREFIX)})


def stage_rows(rows, stage: str) -> dict:
    mine = j.subject_rows(rows, j.stage_subject(stage))
    return {"intent": j.first(mine, "STAGE-INTENT"), "prepared": j.first(mine, "STAGE-PREPARED"),
            "created": j.first(mine, "STAGE-CREATED")}


def committed_commitment(root, trial_id: str, stage: str, rows) -> dict:
    """The staging prepared.json of `stage`, verified against its PREPARED row's detail in the caller's (verified)
    `rows`; ValueError when there is no PREPARED row or the bytes differ (never trusted on their own, F4.3)."""
    m = stage_rows(rows, stage)
    p = staging_dir(root, trial_id, stage) / "prepared.json"
    try:
        blob = p.read_bytes()
    except OSError:
        blob = None
    if m["prepared"] is None or blob is None or c.sha256_bytes(blob) != m["prepared"].detail:
        raise ValueError(f"stage {stage}: prepared.json missing or not its PREPARED detail")
    return json.loads(blob)


def permitted(trial, rows, stage: str):
    """F1 + the finalization graph: the stage's trial state, its predecessor's CREATED row (or the TRIAL-STOP), and
    its required ACK. A reason string refuses the INTENT with no row (F0.5 step 5). A seal stage additionally needs
    its close determined; that check is the caller's extra_gate (s1_slot.seal_gate, E2.2 r3)."""
    sp = spec(stage)
    st_ = j.trial_state(rows)
    if st_ != sp["state"]:
        return f"F1: stage {stage} is not allowed while {st_}"
    pred = sp["pred"]
    if pred == "TRIAL-STOP":
        if j.first(rows, "TRIAL-STOP") is None:
            return f"stage {stage}: no TRIAL-STOP"
    elif pred is not None and stage_rows(rows, pred)["created"] is None:
        return f"stage {stage}: predecessor {pred} is not CREATED (F1)"
    ack = sp["ack"]
    if ack not in (None, "S1-AUDIT-ACK") and ack not in trial.acks:
        return f"stage {stage}: no {ack} (F1 graph)"
    return None


def manifest_projection(stage: str, manifest: dict) -> dict:
    """C-a: the collector manifest's basename-keyed `files` prefixed with '<stage>/', union its s1_out-relative
    `pages`; must equal PREPARED.members minus '<stage>/manifest.json'."""
    files = {f"{stage}/{n}": h for n, h in (manifest.get("files") or {}).items()}
    pages = dict(manifest.get("pages") or {})
    return dict(sorted({**files, **pages}.items()))


def _member_problems(gv, stage, members: dict, provenance: list) -> list:
    if spec(stage)["kind"] == "single":
        want = single_member(gv.out, stage)
        return [] if list(members) == [want] else [f"single stage {stage} must have exactly one member {want}"]
    fixed = set(FIXED_TREE[stage])
    pages = [p.get("page_relpath") if isinstance(p, dict) else None for p in provenance]
    probs = [f"{stage}: fixed member {n} missing" for n in sorted(fixed - set(members))]
    if len(set(pages)) != len(pages):
        probs.append(f"{stage}: a page has two provenance entries")
    extra = set(members) - fixed
    if extra != set(pages):
        probs.append(f"{stage}: pages {sorted(map(str, extra ^ set(pages)))[:4]} lack a provenance entry or a member")
    return probs


def _lock(gv, stage):
    """F5.1/F5.5: acquired; LockHeld -> pending (the only liveness evidence); LockError (any other I/O or permission
    error, ERROR_ACCESS_DENIED included) -> refused with no row, never live or dead, never INVALID."""
    try:
        lk = L.OwnershipLock(gv.root, gv.trial.trial_id, L.stage_lock_name(stage))
        lk.acquire()
    except L.LockHeld:
        raise Pending(f"stage {stage}: pending - a live owner holds the stage lock: no work (F4 table)") from None
    except L.LockError as e:
        raise SystemExit(f"stage {stage}: lock error ({e}): refused with no row and no liveness verdict "
                         f"(F5.5)") from None
    _HELD.add(lk.path)
    return lk


_HELD = set()            # lock paths this process holds through _lock (fix round 1, M7: recover's precondition)


def _release(lk) -> None:
    _HELD.discard(lk.path)
    lk.release()


def _holds(gv, stage) -> bool:
    try:
        return L.lock_path(gv.root, gv.trial.trial_id, L.stage_lock_name(stage)) in _HELD
    except L.LockError:
        return False


def publish_hooks(gv, stage, inputs, clock=None) -> tuple:
    """(publish_ctx factory | None, before_publish | None) of `stage`'s owner (PUBLISH_HOOKS), or (None, None)."""
    import importlib
    spec_ = PUBLISH_HOOKS.get(stage)
    if spec_ is None:
        return None, None
    return getattr(importlib.import_module(spec_[0]), spec_[1])(gv, inputs, clock)


def _require_out(gv, stage) -> None:
    """F6.6 (fix round 1, M3): publication never creates s1_out; if it is gone, its absence is the total-loss
    evidence: refuse with no row (the next gate decides LOST)."""
    if not Path(gv.out).is_dir():
        raise SystemExit(f"stage {stage}: s1_out is gone: no member published, refused with no row (F6.6)")


def _no_selection(rows, subject, inputs):
    """The step-4a selection check of a non-seal stage: F0.5 has no selection rule for it (E2.2 r3 applies to seal
    stages only), so it never decides; supplied explicitly because decide() refuses a missing check (fail closed)."""
    return None


def _append(gv, req, mailbox, clock, stage_gate, stage_check):
    """Every stage row (INTENT, PREPARED, CREATED) goes through product_context: CLOSED is read from the CLOSE rows of
    the same sqlite file inside the BEGIN IMMEDIATE transaction (F0.5 step 2) and INVALID from the journal rows
    (step 3), so a seal stage's PREPARED/CREATED is serializable with TRIAL-INVALID, TRIAL-STOP and CLOSE
    (E2.3 r3). The gate callables are always real (decide refuses a missing one at step 5)."""
    import s1_trial
    return j.append(gv.trial.trial_id, gv.trial.genesis, req,
                    s1_trial.product_context(gv.trial, stage_gate=stage_gate, stage_check=stage_check),
                    mailbox=mailbox, clock=clock)


def _gates(gv, stage, extra_gate, stage_check):
    """(stage_gate, stage_check) for the stage's transactions. stage_gate = permitted AND extra_gate. A seal stage's
    extra_gate (the determined close, E2.2) and stage_check (the selected QUALIFIED, E2.2 4a) belong to the seal side
    and are never defaulted: a missing gate refuses and a missing check stays missing, so decide() refuses the INTENT
    with no row (fail closed)."""
    seal = _is_seal(stage)
    if extra_gate is None and seal:
        def stage_gate(rows_, g):
            return permitted(gv.trial, rows_, g) or "no seal gate supplied (fail closed)"
    else:
        def stage_gate(rows_, g):
            return permitted(gv.trial, rows_, g) or (extra_gate(rows_) if extra_gate is not None else None)
    if stage_check is None and not seal:
        stage_check = _no_selection
    return stage_gate, stage_check


def _invalid(gv, reason, record, mailbox, clock):
    import s1_trial
    s1_trial.invalidate(gv.trial, reason, record, root=gv.root, mailbox=mailbox, clock=clock)
    raise SystemExit(f"stage {record.get('stage')}: INVALID ({reason})") from None   # (A3 Task 9: no chained text)


def _need(res, stage, kind):
    if res.outcome == "APPEND":
        return res.row
    if res.outcome == "INVALIDATE":
        raise SystemExit(f"stage {stage}: {kind} -> INVALID ({res.reason})")
    raise SystemExit(f"stage {stage}: {kind} {res.outcome} with no row: {res.reason}")


def run(gv, stage, *, inputs: dict, acks: dict, work, policy_fn=None, mailbox=None, clock=None,
        before_publish=None, extra_gate=None, stage_check=None, publish_ctx=None) -> dict:
    """F4.1-F4.4 for one stage; re-entry resolves the existing rows per the stage table instead (never a second
    INTENT). A journal outage before the INTENT is a refusal with no request and no artifact (F4 failure 1).
    `extra_gate(rows) -> reason | None` is AND-ed with `permitted` at F0.5 step 5 (revision 2: introduced here,
    used by the seal stages and by Task 10); `stage_check(rows, subject, inputs) -> Decision | None` is evaluated
    at step 4a for the INTENT (E2.2 r3: a seal INTENT naming another QUALIFIED than the first one is INVALIDATE
    contradictory-stage). Both run inside the F0.1 transaction. A seal stage requires both (fail closed).
    A3 Task 10: publish_ctx() (a context-manager factory, e.g. s1_common.stage_publication) wraps before_publish
    and the publication of the members; it is entered only once s1_out is known to exist (F6.6: never recreated)."""
    clock = clock or c.now_utc
    stage_gate, check = _gates(gv, stage, extra_gate, stage_check)
    lk = _lock(gv, stage)
    try:
        rows = j.read_trial(gv.trial.trial_id, gv.trial.genesis, mailbox)
        m = stage_rows(rows, stage)
        if m["intent"] is not None:
            return _resolve(gv, stage, m, mailbox, clock)
        op, actor, held = j.new_nonce(), j.new_nonce(), {}

        def detail_fn(at):                                                    # OQ-7: the in-transaction clock
            held["policy"] = policy_fn(at) if policy_fn is not None else None
            held["envelope"] = envelope(gv.trial.trial_id, stage, inputs, acks, held["policy"])
            return j.detail_of(held["envelope"])
        try:
            intent = _need(_append(gv, j.Request("STAGE-INTENT", j.stage_subject(stage), op, actor,
                                                 detail_fn=detail_fn, inputs=dict(inputs)), mailbox, clock,
                                   stage_gate, check), stage, "STAGE-INTENT")
        except j.Outage as e:
            raise SystemExit(f"stage {stage}: journal outage before the INTENT ({e}): no request, no artifact") \
                from None
        staging = _Staging(gv.root, gv.trial.trial_id, stage)
        c.publish_exclusive(staging.dir / "intent.json", c.canonical(held["envelope"]))       # OQ-35
        sw = StageWork(gv, stage, staging, intent, held["policy"], op, actor, mailbox, clock)
        try:
            provenance = work(sw) or []
        except StageAbort as e:
            rec = dict(e.record, stage=stage, reason=e.reason)
            try:
                staging.put("ABORTED.json", c.canonical(rec))
            except OSError as w:              # A3 Task 13 (Task 12 N-1): a local write error on the ABORTED record
                rec = dict(rec, aborted_record=f"unwritten ({type(w).__name__})")   # never loses the anomaly's
            _invalid(gv, e.reason, rec, mailbox, clock)              # reason: INVALID(reason) is still recorded
        except OSError as e:                  # A3 Task 12 fix round 1 (I-1/I-2, ruling T12 concern 4 corrected): a
            raise SystemExit(f"stage {stage}: local I/O error after the INTENT ({type(e).__name__}): refused with "
                             f"no row; the F4 stage table decides on re-entry") from None   # local fault is no
            #                                   provider anomaly: no ABORTED record, no TRIAL-INVALID here
        probs = _member_problems(gv, stage, {r: 1 for r in staging.files}, provenance)
        if probs:
            raise SystemExit(f"stage {stage}: {probs[0]} (exactly one member / named members, F4.3): no PREPARED")
        members = {rel: c.sha256_bytes(data) for rel, data in staging.files.items()}
        com = commitment(gv.trial.trial_id, stage, op, spec(stage)["kind"], members, provenance)
        blob = c.canonical(com)
        c.publish_exclusive(staging.dir / "prepared.json", blob)
        detail = c.sha256_bytes(blob)                                         # F0.4: the in-memory bytes
        try:
            _need(_append(gv, j.Request("STAGE-PREPARED", j.stage_subject(stage), op, actor, detail=detail),
                          mailbox, clock, stage_gate, check), stage, "STAGE-PREPARED")
            _require_out(gv, stage)                                           # (before publish_ctx: F6.6)
            with (publish_ctx() if publish_ctx is not None else contextlib.nullcontext()):   # A3 Task 10
                if before_publish is not None:
                    before_publish(com)
                _require_out(gv, stage)                                       # (M3: and after before_publish)
                for rel in sorted(members):
                    _publish_one(gv.out, rel, staging.files[rel], members[rel])
            _need(_append(gv, j.Request("STAGE-CREATED", j.stage_subject(stage), op, actor, detail=detail),
                          mailbox, clock, stage_gate, check), stage, "STAGE-CREATED")
        except j.Outage as e:
            raise SystemExit(f"stage {stage}: journal outage after the work ({e}): evidence kept, no next stage; "
                             f"recovery follows the stage table") from None
        return com
    finally:
        _release(lk)


def _publish_one(out: Path, rel: str, data: bytes, sha: str) -> None:
    dst = Path(out) / rel
    try:
        c.publish_exclusive(dst, data)
    except FileExistsError:
        if c.sha256_file(dst) != sha:
            raise SystemExit(f"{rel} exists with other bytes: never overwritten") from None


def _resolve(gv, stage, m, mailbox, clock) -> dict:
    """Re-entry under the stage lock (no live owner): CREATED -> refused (F1 'each stage once'); INTENT without
    PREPARED -> INVALID stage-incomplete (no refetch); PREPARED without CREATED -> recovery (F4.7)."""
    if m["created"] is not None:
        raise SystemExit(f"stage {stage} is already CREATED: re-entry refused (F1)")
    if m["prepared"] is None:
        _invalid(gv, "stage-incomplete", {"stage": stage, "intent_seq": m["intent"].seq}, mailbox, clock)
    return recover(gv, stage, m, mailbox=mailbox, clock=clock)


def _load_committed(gv, stage, row, name):
    p = staging_dir(gv.root, gv.trial.trial_id, stage) / name
    try:
        blob = p.read_bytes()
        if row is None or c.sha256_bytes(blob) != row.detail:
            return None
        return json.loads(blob)
    except (OSError, ValueError):
        return None


def recover(gv, stage, m, *, mailbox=None, clock=None) -> dict:
    """F4.7, called with the stage lock held: prepared.json must hash to the PREPARED detail; every member, in staging
    or already in s1_out, must have its committed sha256; only the missing members are published (from staging, the
    bytes just verified); CREATED is appended with the stage's op and this actor. Any absent or mismatched byte is
    INVALID (stage-replaced). Never re-requests, recomputes or changes prepared bytes; any unexpected error refuses
    with no row (F0.7). Fix round 1 (M7): refuses with no row unless this process holds the stage lock (taken by
    run() or evaluate() through _lock); it never takes the lock itself. A3 Task 10 fix round 1 (review I1): the
    missing members are published through the owner's publication hooks (publish_hooks: e.g. stage.lock and the
    legacy registry/witness records), exactly as run() publishes them."""
    if not _holds(gv, stage):
        raise SystemExit(f"stage {stage}: recovery needs the stage lock and it is not held by this process: refused "
                         f"with no row (F4.7, F5.1)")
    clock = clock or c.now_utc
    try:
        com = _load_committed(gv, stage, m["prepared"], "prepared.json")
        if com is None:
            _invalid(gv, "stage-replaced", {"stage": stage, "problem": "prepared.json missing or not the PREPARED "
                                                                        "detail"}, mailbox, clock)
        staging = staging_dir(gv.root, gv.trial.trial_id, stage)
        todo = {}
        for rel, sha in sorted(com["members"].items()):
            dst = gv.out / rel
            if dst.is_file():
                if c.sha256_file(dst) != sha:
                    _invalid(gv, "stage-replaced", {"stage": stage, "member": rel, "problem": "published bytes differ"},
                             mailbox, clock)
                continue
            try:
                data = (staging / rel).read_bytes()
            except OSError:
                data = None
            if data is None or c.sha256_bytes(data) != sha:
                _invalid(gv, "stage-replaced", {"stage": stage, "member": rel, "problem": "staged bytes absent or "
                                                                                          "different"},
                         mailbox, clock)
            todo[rel] = data
        env = _load_committed(gv, stage, m["intent"], "intent.json")
        ctx_fn, before = publish_hooks(gv, stage, (env or {}).get("inputs"), clock)
        if (ctx_fn is not None or before is not None) and env is None:   # (the hooks read the committed envelope)
            _invalid(gv, "stage-replaced", {"stage": stage, "problem": "intent.json missing or not the INTENT "
                                                                       "detail"}, mailbox, clock)
        _require_out(gv, stage)                                                # M3: never recreate s1_out
        with (ctx_fn() if ctx_fn is not None else contextlib.nullcontext()):  # A3 Task 10 fix round 1 (I1): the
            if before is not None:                                            # owner's publication path, as in run()
                before(com)
            _require_out(gv, stage)
            for rel, data in todo.items():
                c.publish_exclusive(gv.out / rel, data)
        stage_gate, check = _gates(gv, stage, None, _no_selection)       # (step 5 is INTENT-only; CREATED: 4a/4c)
        _need(_append(gv, j.Request("STAGE-CREATED", j.stage_subject(stage), m["intent"].op, j.new_nonce(),
                                    detail=m["prepared"].detail), mailbox, clock, stage_gate, check),
              stage, "STAGE-CREATED")
        return com
    except SystemExit:
        raise
    except Exception as e:                                  # noqa: BLE001 - F0.7: fail closed, no row
        raise SystemExit(f"stage {stage}: recovery refused with no row ({type(e).__name__}) (F0.7)") from None


def _artifacts_present(out: Path, stage: str) -> list:
    if spec(stage)["kind"] == "single":
        try:
            rel = single_member(out, stage)
        except (OSError, ValueError, KeyError, TypeError):
            return []
        return [rel] if (out / rel).exists() else []
    d = out / stage
    return sorted(p.relative_to(out).as_posix() for p in d.rglob("*") if p.is_file()) if d.is_dir() else []


def created_problems(gv, stage, m) -> list:
    """F4 table, CREATED: the envelope's file inputs still hash as committed (intent.json must hash to the INTENT
    detail, OQ-35); every committed member present with its sha256 and parseable when JSON; no extra file in a tree
    stage's directory (an orphan page); for audit/final the manifest projection equals the members minus the manifest
    (C-a) and every page has exactly one provenance entry; JSON members record the trial_id (OQ-36)."""
    out, probs = gv.out, []
    env = _load_committed(gv, stage, m["intent"], "intent.json")
    com = _load_committed(gv, stage, m["prepared"], "prepared.json")
    if env is None or com is None:
        return [f"{stage}: intent.json or prepared.json missing or not its row's detail"]
    for name, sha in env["inputs"].items():
        if name.endswith(".json") and (not (out / name).is_file() or c.sha256_file(out / name) != sha):
            probs.append(f"{stage}: bound input {name} missing or changed since the INTENT")
    for rel, sha in com["members"].items():
        p = out / rel
        if not p.is_file() or c.sha256_file(p) != sha:
            probs.append(f"{stage}: member {rel} missing or changed")
        elif rel.endswith(".json"):
            try:
                json.loads(p.read_bytes())
            except ValueError:
                probs.append(f"{stage}: member {rel} unparseable")
    if spec(stage)["kind"] == "tree":
        extra = set(_artifacts_present(out, stage)) - set(com["members"])
        probs += [f"{stage}: {rel} is not a committed member (orphan)" for rel in sorted(extra)]
    probs += _member_problems(gv, stage, com["members"], com["provenance"])
    if stage in MANIFEST_STAGES and not probs:
        try:
            man = json.loads((out / f"{stage}/manifest.json").read_bytes())
            want = {k_: v for k_, v in com["members"].items() if k_ != f"{stage}/manifest.json"}
            if manifest_projection(stage, man) != dict(sorted(want.items())):
                probs.append(f"{stage}: manifest files+pages differ from the PREPARED members (C-a)")
        except (OSError, ValueError, AttributeError):
            probs.append(f"{stage}: manifest unreadable for the C-a projection")
    for rel in TRIAL_ID_MEMBERS.get(stage, ()):
        try:
            if json.loads((out / rel).read_bytes()).get("trial_id") != gv.trial.trial_id:
                probs.append(f"{stage}: {rel} does not record this trial_id (F6.2)")
        except (OSError, ValueError, AttributeError):
            probs.append(f"{stage}: {rel} unreadable for the trial_id check")
    return list(dict.fromkeys(probs))


def _seals_on_disk(out: Path) -> list:
    """Every post-START seal stage name with a seals/<date>.json file on disk (the opening close is the `opening`
    stage); a file name that is no seal stage name belongs to no seal stage."""
    oc = _opening_close(out)
    names = (f"{SEAL_PREFIX}{p.stem}" for p in sorted((Path(out) / "seals").glob("*.json")) if p.stem != oc)
    return [n for n in names if _SEAL_NAME.fullmatch(n) and j.stage_name_ok(n)]


def _check_created(gv, stage, m) -> None:
    import s1_trial
    probs = created_problems(gv, stage, m)
    if probs:
        s1_trial.invalidate(gv.trial, "stage-replaced", {"stage": stage, "problems": probs}, root=gv.root,
                            mailbox=gv.mailbox)
        raise SystemExit(f"stage {stage}: {probs[:3]}: INVALID (stage-replaced)")


def _decide_locked(gv, stage, m) -> None:
    """The stage-table decision on rows re-read under the stage lock (F5.1)."""
    import s1_trial
    if m["created"] is not None:
        _check_created(gv, stage, m)
        return
    if _is_seal(stage) and m["intent"] is not None and m["prepared"] is None \
            and (gv.out / single_member(gv.out, stage)).exists():
        s1_trial.invalidate(gv.trial, "registration-artifact", {"stage": stage, "problem": "seal file with no "
                            "PREPARED"}, root=gv.root, mailbox=gv.mailbox)
        raise SystemExit(f"stage {stage}: seal file with no PREPARED: INVALID (registration-artifact)")
    if m["intent"] is None:
        present = _artifacts_present(gv.out, stage)
        if present:
            s1_trial.invalidate(gv.trial, "registration-artifact", {"stage": stage, "present": present},
                                root=gv.root, mailbox=gv.mailbox)
            raise SystemExit(f"stage {stage}: artifacts {present[:3]} with no INTENT: INVALID "
                             f"(registration-artifact)")
        return
    _resolve(gv, stage, m, gv.mailbox, None)


def evaluate(gv, *, defer_pending: bool = False) -> None:
    """The F4 stage-state table over every stage of TABLE (A3 Task 14), run by every gate (and the F7.3 live-file
    check): no INTENT + an artifact -> INVALID (registration-artifact; before the AUDIT-ACK the gate already refused);
    INTENT or PREPARED without CREATED -> pending while a live owner holds the lock, else stage-incomplete / recovery;
    CREATED -> created_problems -> INVALID (stage-replaced).
    Seal stages (E2 r3) are evaluated too: every `seal/<date>` with a journal row, plus every post-START
    `seals/<date>.json` present on disk (a seal file with no INTENT/PREPARED is registration-artifact in
    every state, E2.4 r3; a CREATED seal missing, changed or unparseable is stage-replaced and never recreated,
    E2.6 r3). Never creates s1_out (F6.6).
    Fix round 1 (I1, F5.1): the gate's snapshot `gv.rows` only selects what to look at. A CREATED row is final, so it
    is checked directly; every decision that depends on the ABSENCE of a row (no INTENT, no PREPARED, no CREATED) is
    taken under the stage lock on rows re-read there: a live owner -> pending, never INVALID.
    A3 Task 6 (ruling N2, Erratum 1 E1.2): `defer_pending` (the slot paths: a worker's capture and, Task 7, the
    finalizer's deadline rows) records a stage whose lock is HELD in gv.deferred and goes on, instead of refusing
    "pending": a stalled stage owner never blocks a slot capture, a TIMEOUT at D or a MISSED at E. Deferring decides
    nothing about that stage (the next gate after its lock is free does); a LockError still refuses (F5.5), and
    every CREATED check and every decision on an acquirable lock is unchanged."""
    on_disk = _seals_on_disk(gv.out)
    for stage in list(TABLE) + sorted(set(seal_stages(gv.rows)) | set(on_disk)):
        m = stage_rows(gv.rows, stage)
        if m["created"] is not None:
            _check_created(gv, stage, m)
            continue
        if m["intent"] is None and not _artifacts_present(gv.out, stage):
            continue                                                           # no row, no artifact: nothing to do
        try:
            lk = _lock(gv, stage)
        except Pending:
            if not defer_pending:
                raise
            gv.deferred.append(stage)                                          # N2: undecided, not blocking
            continue
        try:
            rows = j.read_trial(gv.trial.trial_id, gv.trial.genesis, gv.mailbox)       # re-validated under the lock
            _decide_locked(gv, stage, stage_rows(rows, stage))
        finally:
            _release(lk)
