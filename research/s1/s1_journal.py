"""S1 external trial journal (Addendum 3 rev 5, sha256 d9dd3759..., F0).

The ONE writer of the coordination mailbox. Its only write is a single-row INSERT inside BEGIN IMMEDIATE (sender s1,
recipient codex, key experiments-s1-journal); inside that transaction it re-reads the trial's rows and applies the
F0.5 precedence (decide) to the state it reads there, never to an earlier read. Every other read is mode=ro (never
created). No UPDATE, DELETE or ack; mailbox.py is never imported. A row is judged by its body only: the mailbox's
`acknowledged` column (Codex's inbox ack) is ignored."""
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import s1_common as c

SENDER, RECIPIENT, KEY = "s1", "codex", "experiments-s1-journal"
SLOT_KINDS = ("SLOT-INTENT", "SLOT-QUALIFIED", "SLOT-FAILED", "SLOT-TIMEOUT", "SLOT-MISSED")
STAGE_KINDS = ("STAGE-INTENT", "STAGE-PREPARED", "STAGE-CREATED")
TRIAL_KINDS = ("TRIAL-STOP", "TRIAL-INVALID")
KINDS = SLOT_KINDS + STAGE_KINDS + TRIAL_KINDS                                        # F0.3
TERMINAL = ("SLOT-QUALIFIED", "SLOT-FAILED", "SLOT-TIMEOUT", "SLOT-MISSED")
OPENING = ("SLOT-INTENT", "STAGE-INTENT", "SLOT-MISSED", "TRIAL-STOP")                # rows that open their own op
STAGES = ("audit", "opening", "start_attest", "prereg", "stop_attest", "final_plan", "final", "score")   # F4.8
REASONS = ("contradictory-completion", "contradictory-finalizer", "contradictory-stage", "repeat-attempt",
           "repeat-stage", "stop-conflict", "stage-incomplete", "stage-replaced", "provider-structural",
           "score-aborted", "bundle", "LOST", "registration-artifact",
           "established-violation")                                       # OQ-1; OQ-31 (A3 Task 6)
ABSENT, TRIAL_SUBJECT = "absent", "trial"
DETAIL_ABSENT = ("SLOT-INTENT", "SLOT-TIMEOUT", "SLOT-MISSED")                                         # OQ-2
_HEX64, _HEX32 = re.compile(r"[0-9a-f]{64}"), re.compile(r"[0-9a-f]{32}")
# re.ASCII: `\d` would otherwise match any Unicode digit; the frozen F0.2 bytes are ASCII digits only.
_UUID4 = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
_LINE = re.compile(
    rf"S1-JOURNAL trial_id=(?P<trial_id>{_UUID4}) seq=(?P<seq>[1-9][0-9]*) prev_sha256=(?P<prev>[0-9a-f]{{64}}) "
    r"kind=(?P<kind>[A-Z-]+) subject=(?P<subject>[^ =\r\n]+) detail_sha256=(?P<detail>[0-9a-f]{64}|absent) "
    r"op=(?P<op>[0-9a-f]{32}) actor=(?P<actor>[0-9a-f]{32}) "
    r"at=(?P<at>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00)", re.ASCII)
_SLOT = re.compile(r"slot/\d{8}T\d{6}Z", re.ASCII)
SEAL_PREFIX = "seal/"                                     # Erratum 1 E2.1: post-START seal stage seal/<close date>
_SEAL = re.compile(r"seal/(\d{4}-\d{2}-\d{2})", re.ASCII)


class JournalError(Exception):
    """Base of every journal failure; the caller refuses with no row."""


class ChainError(JournalError):
    """F0.5 step 1: a gap, fork, duplicate seq or bad format (or a foreign row under the key, OQ-4): refuse with no
    row and escalate."""


class RequestError(JournalError):
    """A malformed requested row (kind, subject, detail, op, actor, R): refused before any transaction, no row."""


class Outage(JournalError):
    """The mailbox could not be read or written (missing, locked, no table): fail closed, no row (F8.3)."""


@dataclass(frozen=True)
class Row:
    trial_id: str
    seq: int
    prev: str
    kind: str
    subject: str
    detail: str
    op: str
    actor: str
    at: str
    line: str
    mailbox_id: str
    created: float

    @property
    def sha(self) -> str:
        return line_sha256(self.line)

    @property
    def instant(self) -> datetime:
        return c.aware(self.at)


@dataclass
class Request:
    """A requested row. `detail_fn(at)` (STAGE-INTENT, OQ-7) computes the detail from the in-transaction clock; `r_at`
    is R for SLOT-QUALIFIED (its `at`, F3); `inputs` is the STAGE-INTENT envelope's inputs (whose hash is in the
    detail), visible to Context.stage_check (E2.2 r3)."""
    kind: str
    subject: str
    op: str
    actor: str
    detail: Optional[str] = None
    detail_fn: Optional[Callable[[datetime], str]] = None
    r_at: Optional[datetime] = None
    inputs: Optional[dict] = None


@dataclass
class Context:
    """What the caller supplies, evaluated inside the transaction: CLOSED (F7.5, read from the CLOSE rows of the same
    sqlite file, E2.3 r3); slot_times(subject) -> (E, D); stop_detail(rows) -> the stop record sha256 committed
    history gives, or None (rule not met); stage_gate(rows, stage) / slot_gate(rows, subject) -> a refusal reason or
    None (F1 permission, predecessor, ACKs, the seal stage's determined close); stage_check(rows, subject, inputs)
    -> Decision | None at step 4a for a STAGE-INTENT (E2.2 r3: a seal stage selecting another QUALIFIED than the
    first one is INVALIDATE contradictory-stage); stop_fence(rows) -> a refusal reason or None at step 5 for
    TRIAL-STOP (E2.5 r3: every close determined by these rows must have a CREATED seal stage); stop_ready(rows, now)
    -> a refusal reason or None at step 5 for TRIAL-STOP, after the fence (A3 Task 11, BLK3-C1 / Codex 28e08272
    checkpoint: `now` is the clock append() sampled inside THIS transaction - the same instant that becomes the row's
    `at` - never a preflight time). A missing slot_gate, stage_gate or stage_check (and slot_times, stop_detail,
    stop_fence, stop_ready) fails closed at step 5/6 (Task 5 fix round 1, review M-6); steps 2-4 never depend on
    them."""
    closed: bool = False
    slot_times: Optional[Callable[[str], tuple]] = None
    stop_detail: Optional[Callable[[list], Optional[str]]] = None
    stage_gate: Optional[Callable[[list, str], Optional[str]]] = None
    slot_gate: Optional[Callable[[list, str], Optional[str]]] = None
    stage_check: Optional[Callable[[list, str, dict], Optional["Decision"]]] = None
    stop_fence: Optional[Callable[[list], Optional[str]]] = None
    stop_ready: Optional[Callable[[list, datetime], Optional[str]]] = None


@dataclass(frozen=True)
class Decision:
    outcome: str                      # "APPEND" | "LOST-RACE" | "INVALIDATE" | "REFUSE" (OQ-21)
    reason: str = ""


@dataclass
class Result:
    outcome: str
    reason: str
    row: Optional[Row]                # the row written (the requested one, or the TRIAL-INVALID), else None
    rows: list                        # the trial's rows as read inside the transaction (before this row)


def new_nonce() -> str:
    return uuid.uuid4().hex


def fmt_at(t: datetime) -> str:
    if not isinstance(t, datetime) or t.tzinfo is None:
        raise RequestError("an aware instant is required for `at`")
    return t.astimezone(timezone.utc).isoformat(timespec="microseconds")


def slot_subject(slot: datetime) -> str:
    return "slot/" + slot.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def stage_name_ok(stage: str) -> bool:
    """F4.8 + Erratum 1 E2.1: one of the eight named stages, or a post-START seal stage `seal/<YYYY-MM-DD>` whose date
    is a real calendar date."""
    if stage in STAGES:
        return True
    m = _SEAL.fullmatch(stage) if isinstance(stage, str) else None
    if m is None:
        return False
    try:
        date.fromisoformat(m.group(1))
    except ValueError:
        return False
    return True


def stage_subject(stage: str) -> str:
    if not stage_name_ok(stage):
        raise RequestError(f"unknown stage {stage!r}")
    return "stage/" + stage


def invalid_subject(reason: str) -> str:
    if reason not in REASONS:
        raise RequestError(f"unknown INVALID reason {reason!r}")
    return "reason/" + reason


def subject_ok(kind: str, subject: str) -> bool:
    if kind in SLOT_KINDS:
        return bool(_SLOT.fullmatch(subject or ""))
    if kind in STAGE_KINDS:
        return isinstance(subject, str) and subject.startswith("stage/") and stage_name_ok(subject[len("stage/"):])
    if kind == "TRIAL-STOP":
        return subject == TRIAL_SUBJECT
    if kind == "TRIAL-INVALID":
        return isinstance(subject, str) and subject.startswith("reason/") and subject[len("reason/"):] in REASONS
    return False


def detail_ok(kind: str, detail: str) -> bool:
    return detail == ABSENT if kind in DETAIL_ABSENT else bool(_HEX64.fullmatch(detail or ""))


def format_line(*, trial_id, seq, prev, kind, subject, detail, op, actor, at) -> str:
    """F0.2: the frozen one-line body (fields in order, single-spaced, no trailing newline)."""
    return (f"S1-JOURNAL trial_id={trial_id} seq={seq} prev_sha256={prev} kind={kind} subject={subject} "
            f"detail_sha256={detail} op={op} actor={actor} at={at}")


def parse_line(line: str) -> dict:
    """The fields of a journal line, or ChainError for any deviation from the frozen grammar (F0.2, F0.3, OQ-1/2)."""
    m = _LINE.fullmatch(line) if isinstance(line, str) else None
    if m is None:
        raise ChainError("journal line does not match the frozen F0.2 grammar")
    f = m.groupdict()
    if f["kind"] not in KINDS:
        raise ChainError(f"unknown journal kind {f['kind']!r} (F0.3)")
    if not subject_ok(f["kind"], f["subject"]):
        raise ChainError(f"subject {f['subject']!r} is not valid for {f['kind']} (OQ-1)")
    if not detail_ok(f["kind"], f["detail"]):
        raise ChainError(f"detail presence is not valid for {f['kind']} (OQ-2)")
    try:
        datetime.fromisoformat(f["at"])
    except ValueError:
        raise ChainError("journal `at` is not a real instant") from None
    f["seq"] = int(f["seq"])
    return f


def line_sha256(line: str) -> str:
    return c.sha256_bytes(line.encode("utf-8"))


def genesis(audit_ack_line: str) -> str:
    """F0.2: seq 1's prev_sha256 = sha256 of the AUDIT-ACK token line (UTF-8, no newline)."""
    return line_sha256(audit_ack_line)


def detail_of(obj) -> str:
    """F0.4: sha256 of the canonical bytes held in memory (c.canonical: sorted keys, compact, UTF-8)."""
    return c.sha256_bytes(c.canonical(obj))


def validate_request(req: Request) -> None:
    """C-c: a malformed request is refused before any transaction (no row)."""
    if req.kind not in KINDS:
        raise RequestError(f"unknown kind {req.kind!r}")
    if not subject_ok(req.kind, req.subject):
        raise RequestError(f"subject {req.subject!r} is not valid for {req.kind}")
    if not (_HEX32.fullmatch(req.op or "") and _HEX32.fullmatch(req.actor or "")):
        raise RequestError("op and actor must be 32 lowercase hex")
    if req.detail is not None and req.detail_fn is not None:
        raise RequestError("detail and detail_fn are exclusive")
    if req.kind in DETAIL_ABSENT:
        if req.detail not in (None, ABSENT) or req.detail_fn is not None:
            raise RequestError(f"{req.kind} carries no detail (OQ-2)")
    elif req.detail_fn is None and not _HEX64.fullmatch(req.detail or ""):
        raise RequestError(f"{req.kind} requires a 64-hex detail")
    if req.kind == "SLOT-QUALIFIED":
        if not isinstance(req.r_at, datetime) or req.r_at.tzinfo is None:
            raise RequestError("SLOT-QUALIFIED requires an aware R (its `at`, F3)")
    elif req.r_at is not None:
        raise RequestError("only SLOT-QUALIFIED carries R")


def _path(mailbox) -> Path:
    return Path(c.MAILBOX if mailbox is None else mailbox)


def _uri(mailbox, mode: str) -> str:
    """A sqlite file: URI for the mailbox; the path is percent-quoted so a `?`, `#` or `%` in it cannot change the
    file or the mode (escaped locally: no URL library is imported, M-6)."""
    path = _path(mailbox).as_posix().replace("%", "%25").replace("?", "%3f").replace("#", "%23")
    return f"file:{path}?mode={mode}"


def _ro(mailbox):
    """F0.1: every read other than the in-transaction re-read is mode=ro (the file is never created)."""
    return sqlite3.connect(_uri(mailbox, "ro"), uri=True)


def _connect_rw(mailbox, timeout):
    """mode=rw: an existing mailbox only (never created); autocommit so BEGIN IMMEDIATE is explicit."""
    return sqlite3.connect(_uri(mailbox, "rw"), uri=True, isolation_level=None, timeout=timeout)


def _rows_from(con) -> list:
    out = []
    for mid, sender, recipient, body, created in con.execute(
            "SELECT id, sender, recipient, body, created FROM messages WHERE request_key=?", (KEY,)):
        if (sender, recipient) != (SENDER, RECIPIENT):
            raise ChainError(f"journal-key row {mid!r} from {sender!r} to {recipient!r}: only s1->codex writes it")
        out.append(Row(**parse_line(body), line=body, mailbox_id=mid, created=created))
    return out


def read_all(mailbox=None) -> list:
    """Every journal row of every trial (mode=ro). Outage when unreadable; ChainError for a bad row (OQ-4)."""
    try:
        con = _ro(mailbox)
        try:
            return _rows_from(con)
        finally:
            con.close()
    except sqlite3.Error as e:
        raise Outage(f"mailbox unreadable ({type(e).__name__})") from None


def verify_chain(rows, trial_id: str, gen: str) -> list:
    """F0.5 step 1 for one trial (other trials' rows are ignored, F6.5): seq 1..n contiguous and unique, each prev the
    previous row's line_sha256 and seq 1's the genesis. Returns the trial's rows in seq order."""
    mine = sorted((r for r in rows if r.trial_id == trial_id), key=lambda r: r.seq)
    seqs = [r.seq for r in mine]
    if len(set(seqs)) != len(seqs):
        raise ChainError("duplicate seq (a fork): refuse with no row and escalate")
    if seqs != list(range(1, len(mine) + 1)):
        raise ChainError(f"seq gap in {seqs[:8]}: refuse with no row and escalate")
    prev = gen
    for r in mine:
        if r.prev != prev:
            raise ChainError(f"seq {r.seq}: prev_sha256 does not chain (fork): refuse with no row and escalate")
        prev = r.sha
    return mine


def read_trial(trial_id: str, gen: str, mailbox=None) -> list:
    return verify_chain(read_all(mailbox), trial_id, gen)


def trial_state(rows) -> str:
    """F1: INVALID = any TRIAL-INVALID (with or without a stop); STOPPED = a TRIAL-STOP and no TRIAL-INVALID; else
    ACTIVE. CLOSED is an authorization status layered on top by s1_trial (F7.5)."""
    ks = {r.kind for r in rows}
    if "TRIAL-INVALID" in ks:
        return "INVALID"
    return "STOPPED" if "TRIAL-STOP" in ks else "ACTIVE"


def subject_rows(rows, subject) -> list:
    return [r for r in rows if r.subject == subject]


def first(rows, *kinds):
    return next((r for r in rows if r.kind in kinds), None)


def decide(rows, req, ctx, now) -> Decision:
    """F0.5 precedence on the state read inside the transaction (step 1, chain integrity, is verify_chain, run before
    this). Steps in order; the first that decides wins; the step-4 sub-steps 4a, 4b, 4c, 4d are disjoint. The OQ-3
    reused-op check (a malformed opening request: REFUSE) runs after 4b, so a repeated subject is still
    repeat-attempt / repeat-stage (f045bd31 OQ-3 ruling)."""
    if ctx.closed:                                                                     # step 2
        return Decision("REFUSE", "trial CLOSED: no row of any kind")
    state = trial_state(rows)
    if state == "INVALID":                                                             # step 3
        if req.kind == "TRIAL-INVALID":
            return Decision("APPEND", "an extra INVALID observation")
        return Decision("LOST-RACE", "trial INVALID: no work")
    if req.kind == "TRIAL-INVALID":                                                    # (no step-4..6 rule applies)
        return Decision("APPEND")
    mine = subject_rows(rows, req.subject)
    reused = req.kind in OPENING and any(r.op == req.op for r in rows)                 # OQ-3, applied after 4b
    if req.kind in SLOT_KINDS:
        return _slot(rows, mine, req, ctx, now, state, reused)
    if req.kind in STAGE_KINDS:
        return _stage(rows, mine, req, ctx, reused)
    return _stop(rows, req, ctx, now, reused)


_REUSED = Decision("REFUSE", "an opening row must open a new op; this op is already used (OQ-3: malformed)")


def _slot(rows, mine, req, ctx, now, state, reused=False) -> Decision:
    intent, terminal, k = first(mine, "SLOT-INTENT"), first(mine, *TERMINAL), req.kind
    # 4a identity (before terminal state, so a foreign completion stays invalid on a terminal subject)
    if k in ("SLOT-QUALIFIED", "SLOT-FAILED") and (intent is None or req.op != intent.op
                                                   or req.actor != intent.actor):
        return Decision("INVALIDATE", "contradictory-completion")
    if k == "SLOT-TIMEOUT" and (intent is None or req.op != intent.op):
        return Decision("INVALIDATE", "contradictory-finalizer")
    # 4b repeat
    if k == "SLOT-INTENT" and mine:
        return Decision("INVALIDATE", "repeat-attempt")
    if reused:                                                                         # OQ-3 (after 4b)
        return _REUSED
    # 4c already decided (E1.3 r3: after a committed TIMEOUT a completion is LOST-RACE here, whatever its R)
    if k != "SLOT-INTENT" and terminal is not None:
        return Decision("LOST-RACE", f"stale: {req.subject} is already {terminal.kind}")
    # 4d in-flight conflict
    if k == "SLOT-MISSED" and intent is not None:
        return Decision("REFUSE", "in flight: the finalizer re-evaluates for a TIMEOUT at D")
    # 5 trial-state permission (F1)
    if k == "SLOT-INTENT":
        if state == "STOPPED":
            return Decision("LOST-RACE", "STOPPED: no capture after the stop (not invalid)")
        why = (ctx.slot_gate(rows, req.subject) if ctx.slot_gate is not None     # review M-6: fail closed
               else "no slot gate supplied (fail closed)")
        if why:
            return Decision("REFUSE", why)
    if k in ("SLOT-QUALIFIED", "SLOT-FAILED") and state == "STOPPED":
        stop = first(rows, "TRIAL-STOP")
        if not intent.seq < stop.seq:
            return Decision("REFUSE", "completion after the STOP needs its INTENT before the STOP (F1)")
    # 6 timing (E, D, R)
    if ctx.slot_times is None:
        return Decision("REFUSE", "no slot timing supplied (fail closed)")
    e, d = ctx.slot_times(req.subject)
    if k == "SLOT-INTENT" and now >= e:
        return Decision("REFUSE", "now >= E: the finalizer appends MISSED")
    if k == "SLOT-QUALIFIED" and req.r_at >= d:
        return Decision("REFUSE", "late R (R >= D): the finalizer later appends TIMEOUT")
    if k == "SLOT-TIMEOUT" and now < d:
        return Decision("REFUSE", "premature finalizer (now < D)")
    if k == "SLOT-MISSED" and now < e:
        return Decision("REFUSE", "premature finalizer (now < E)")
    return Decision("APPEND")                                                          # 7 (SLOT-FAILED: OQ-12)


def _stage(rows, mine, req, ctx, reused=False) -> Decision:
    intent, prepared, created = (first(mine, x) for x in STAGE_KINDS)
    k = req.kind
    if k == "STAGE-PREPARED" and (intent is None or req.op != intent.op or req.actor != intent.actor):   # 4a
        return Decision("INVALIDATE", "contradictory-stage")
    if k == "STAGE-CREATED" and (intent is None or prepared is None or req.op != intent.op):              # 4a
        return Decision("INVALIDATE", "contradictory-stage")
    if k == "STAGE-INTENT" and ctx.stage_check is not None:                  # 4a (E2.2 r3: the selected QUALIFIED)
        d = ctx.stage_check(rows, req.subject, req.inputs or {})
        if d is not None:
            return d
    if k == "STAGE-INTENT" and intent is not None:                                                         # 4b
        return Decision("INVALIDATE", "repeat-stage")
    if reused:                                                                                             # OQ-3
        return _REUSED
    if k == "STAGE-PREPARED" and prepared is not None:                                                     # 4c
        if req.detail == prepared.detail:
            return Decision("LOST-RACE", "PREPARED already committed (idempotent)")
        return Decision("INVALIDATE", "contradictory-stage")
    if k == "STAGE-CREATED":                                                                               # 4c
        if req.detail != prepared.detail:
            return Decision("INVALIDATE", "contradictory-stage")
        if created is not None:
            if req.detail == created.detail:
                return Decision("LOST-RACE", "CREATED already committed (idempotent recovery)")
            return Decision("INVALIDATE", "contradictory-stage")
    if k == "STAGE-INTENT":                                                                                # 5
        why = (ctx.stage_gate(rows, req.subject[len("stage/"):]) if ctx.stage_gate is not None
               else "no stage gate supplied (fail closed)")
        if why:
            return Decision("REFUSE", why)
        if ctx.stage_check is None:                       # review M-6: the seal-selection check (4a) never skipped
            return Decision("REFUSE", "no stage check supplied (fail closed)")
    return Decision("APPEND")


def _stop(rows, req, ctx, now, reused=False) -> Decision:
    stop = first(rows, "TRIAL-STOP")
    if stop is not None:                                                                                   # 4c
        if req.detail == stop.detail:
            return Decision("LOST-RACE", "already STOPPED with this record")
        return Decision("INVALIDATE", "stop-conflict")
    if reused:                                                                                             # OQ-3
        return _REUSED
    want = ctx.stop_detail(rows) if ctx.stop_detail is not None else None                                 # 5
    if want is None:
        return Decision("REFUSE", "the stop rule is not met by committed history")
    if want != req.detail:
        return Decision("REFUSE", "the stop record differs from the one committed history gives (OQ-9: escalate)")
    fence = ctx.stop_fence(rows) if ctx.stop_fence is not None else "no stop fence supplied (fail closed)"
    if fence:                                                                 # E2.5 r3: the frozen prefix
        return Decision("REFUSE", f"STOP prefix not sealed: {fence} (run the missing seal stages and retry)")
    why = (ctx.stop_ready(rows, now) if ctx.stop_ready is not None                # BLK3-C1: the transaction clock
           else "no stop readiness supplied (fail closed)")
    if why:
        return Decision("REFUSE", f"STOP not ready: {why}")
    return Decision("APPEND")


def _requested_detail(req: Request, now: datetime) -> str:
    d = req.detail_fn(now) if req.detail_fn is not None else (req.detail or ABSENT)
    if not detail_ok(req.kind, d):
        raise RequestError(f"{req.kind}: computed detail {d!r} is not valid")
    return d


def _insert(con, trial_id: str, gen: str, rows: list, req: Request, dec: Decision, now: datetime) -> Row:
    seq, prev = len(rows) + 1, (rows[-1].sha if rows else gen)
    requested = _requested_detail(req, now)
    if dec.outcome == "INVALIDATE":                                   # OQ-2: the reason record, the request's op
        kind, subject, at = "TRIAL-INVALID", invalid_subject(dec.reason), now
        detail = detail_of({"reason": dec.reason, "requested": {"kind": req.kind, "subject": req.subject,
                                                                "op": req.op, "actor": req.actor,
                                                                "detail": requested}})
    else:
        kind, subject, detail = req.kind, req.subject, requested
        at = req.r_at if req.kind == "SLOT-QUALIFIED" else now        # F0.2: QUALIFIED at = R
    line = format_line(trial_id=trial_id, seq=seq, prev=prev, kind=kind, subject=subject, detail=detail, op=req.op,
                       actor=req.actor, at=fmt_at(at))
    fields = parse_line(line)                                          # never write a line the grammar rejects
    mid, created = str(uuid.uuid4()), now.timestamp()                  # OQ-26
    con.execute("INSERT INTO messages (id, sender, recipient, request_key, body, created, acknowledged) "
                "VALUES (?, ?, ?, ?, ?, ?, NULL)", (mid, SENDER, RECIPIENT, KEY, line, created))
    return Row(**fields, line=line, mailbox_id=mid, created=created)


def append(trial_id: str, gen: str, req: Request, ctx_fn, *, mailbox=None, clock=None, timeout: float = 10.0) -> Result:
    """F0.1/F0.5: validate, BEGIN IMMEDIATE, re-read and chain-verify the trial's rows, build the Context from that
    state (`ctx_fn(rows, con)`), read the clock once (the row's `at`, OQ-7/26), decide, and INSERT at most one row
    (the requested row on APPEND, the TRIAL-INVALID on INVALIDATE). Any exception rolls back: no row (F0.7)."""
    validate_request(req)
    clock = clock or c.now_utc
    try:
        con = _connect_rw(mailbox, timeout)
    except sqlite3.Error as e:
        raise Outage(f"mailbox not writable ({type(e).__name__}): no row") from None
    try:
        try:
            con.execute("BEGIN IMMEDIATE")
        except sqlite3.Error as e:
            raise Outage(f"journal transaction not started ({type(e).__name__}): no row") from None
        try:
            rows = verify_chain(_rows_from(con), trial_id, gen)
            ctx = ctx_fn(rows, con)
            now = clock()
            dec = decide(rows, req, ctx, now)
            row = _insert(con, trial_id, gen, rows, req, dec, now) if dec.outcome in ("APPEND", "INVALIDATE") else None
            con.execute("COMMIT")
        except BaseException:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
    except sqlite3.Error as e:
        raise Outage(f"journal write failed ({type(e).__name__}): no row") from None
    finally:
        con.close()
    return Result(dec.outcome, dec.reason, row, rows)
