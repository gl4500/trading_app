"""S1 external trial identity (Addendum 3 rev 5 F6, F7, F9; Erratum 1 E3.4, E4). The open trial, its ACK chain and
its CLOSE are found from the coordination mailbox only (opened mode=ro, F6.3); the trial gate (Task 5) is built on
these readers. Codex issues ACKs; S1 code only reads them. Token texts: ACK_FIELDS (exact fields in order, F6.1,
OQ-5). No function here takes an output root for the trial lookup: closure is monotone from mailbox history alone
(E3.4 r3), and S1 never recomputes a historical CLOSE's evidence."""
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import s1_common as c
import s1_journal as j

ACK_KEY = ("codex", "claude", "experiments-prereg")
ACK_FIELDS = {
    "S1-AUDIT-ACK": ("trial_id", "bundle_sha256", "collector_sha256", "plan_sha256", "start"),
    "S1-OPENING-ACK": ("trial_id", "bundle_sha256", "prev", "plan_sha256", "audit_manifest_sha256", "opening_slot",
                       "opening_seal_sha256", "opening_receipt_sha256", "journal_seq", "journal_head_sha256",
                       "evidence_manifest_sha256"),
    "S1-RUN-ACK": ("trial_id", "bundle_sha256", "prev", "runner_sha256", "plan_sha256", "audit_manifest_sha256",
                   "attest_start_sha256", "opening_seal_sha256", "opening_books_sha256", "start", "journal_seq",
                   "journal_head_sha256"),
    "S1-PREREG-ACK": ("trial_id", "bundle_sha256", "prev", "prereg_sha256", "journal_seq", "journal_head_sha256"),
    "S1-ACQUIRE-ACK": ("trial_id", "bundle_sha256", "prev", "collector_sha256", "final_plan_sha256", "prereg_sha256",
                       "attest_stop_sha256", "journal_seq", "journal_head_sha256", "stop_line_sha256"),
    "S1-SCORE-ACK": ("trial_id", "bundle_sha256", "prev", "runner_sha256", "final_manifest_sha256",
                     "stop_attest_sha256", "final_snapshot_sha256", "stop_sha256", "journal_seq",
                     "journal_head_sha256", "stop_line_sha256"),
    "S1-CLOSE-ACK": ("trial_id", "bundle_sha256", "prev", "reason", "evidence_sha256"),     # E4.5: no journal fields
}
CHAIN = ("S1-AUDIT-ACK", "S1-OPENING-ACK", "S1-RUN-ACK", "S1-PREREG-ACK", "S1-ACQUIRE-ACK", "S1-SCORE-ACK")
PRED = dict(zip(CHAIN[1:], CHAIN[:-1]))
CLOSE_REASONS = ("SCORED", "ABORTED", "LOST", "OPENING-UNACKED", "INVALID", "WITHDRAWN",
                 "BLOCKED")                                       # BLOCKED: E3.4 of the adopted Erratum 1, de008b1

# re.ASCII throughout: `\d` would otherwise match any Unicode digit.
_UUID4_TEXT = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
_UUID4 = re.compile(_UUID4_TEXT, re.ASCII)
_HEX64 = re.compile(r"[0-9a-f]{64}", re.ASCII)
_SEQ = re.compile(r"[1-9][0-9]*", re.ASCII)
_SLOT = re.compile(r"slot/\d{8}T\d{6}Z", re.ASCII)
_ATTRIB = re.compile(rf"trial_id=({_UUID4_TEXT})", re.ASCII)
STRICT_HEX = ("bundle_sha256", "journal_head_sha256", "stop_line_sha256", "evidence_sha256",
              "evidence_manifest_sha256", "plan_sha256")          # never "absent"
_SCAN = "SELECT id, sender, recipient, request_key, body, created FROM messages"


class Refusal(SystemExit):
    """A trial-bound command refuses (identity, chain, CLOSE, outage): zero callbacks, no row."""


@dataclass(frozen=True)
class Ack:
    mailbox_id: str
    created: float
    sender: str
    recipient: str
    key: str
    line: str
    kind: object                      # None = a malformed official candidate (E4.3)
    fields: dict

    @property
    def official(self) -> bool:
        return (self.sender, self.recipient, self.key) == ACK_KEY

    @property
    def sha(self) -> str:
        return j.line_sha256(self.line)


@dataclass
class Trial:
    trial_id: str
    bundle: str
    audit: Ack
    acks: dict                        # kind -> the trial's one ACK of that kind (CHAIN[1:])
    closed: object                    # the valid CLOSE-ACK, or None
    problems: list
    genesis: str

    @property
    def latest(self) -> Ack:
        present = [self.audit] + [self.acks[k_] for k_ in CHAIN[1:] if k_ in self.acks]
        return present[-1]


def parse_ack_line(line: str) -> tuple:
    """F6.1: one standalone token line with exactly the listed fields, in order (OQ-5). ValueError otherwise."""
    kind, sep, rest = line.partition(" ")
    if kind not in ACK_FIELDS or not sep:
        raise ValueError(f"not an S1 ACK kind: {kind!r}")
    parts = rest.split(" ")
    if any("=" not in p or p.startswith("=") or p.endswith("=") for p in parts):
        raise ValueError(f"{kind}: malformed field")
    names = [p.split("=", 1)[0] for p in parts]
    if names != list(ACK_FIELDS[kind]):
        raise ValueError(f"{kind}: fields {names} are not exactly {list(ACK_FIELDS[kind])} in order")
    f = dict(p.split("=", 1) for p in parts)
    if not _UUID4.fullmatch(f["trial_id"]):
        raise ValueError(f"{kind}: trial_id is not a uuid4")
    for n, v in f.items():
        if n.endswith("_sha256") and not (_HEX64.fullmatch(v) or (v == c.ABSENT and n not in STRICT_HEX)):
            raise ValueError(f"{kind}: {n} is not a 64-hex sha256")
    if "journal_seq" in f and not _SEQ.fullmatch(f["journal_seq"]):
        raise ValueError(f"{kind}: journal_seq is not a positive integer")
    if "start" in f:
        try:
            c.aware(f["start"])
        except ValueError:
            raise ValueError(f"{kind}: start is not an instant") from None
    if "reason" in f and f["reason"] not in CLOSE_REASONS:
        raise ValueError(f"{kind}: reason {f['reason']!r} is not a CLOSE reason")
    if "opening_slot" in f and not _SLOT.fullmatch(f["opening_slot"]):
        raise ValueError(f"{kind}: opening_slot is not a slot subject")
    return kind, f


def attributed_trial(line: str):
    """E4.3 (Erratum 1 r1) attribution grammar: a trial_id can be parsed exactly when the line's second
    whitespace-separated token is `trial_id=<canonical lowercase uuid4>`. Otherwise None (unattributable)."""
    parts = line.split()
    m = _ATTRIB.fullmatch(parts[1]) if len(parts) > 1 else None
    return m.group(1) if m else None


def _is_candidate(ln: str) -> bool:
    """E4.1: the line itself starts with `S1-` (no stripping: an indented or quoted line is no candidate) and its
    first whitespace-separated token ends in `-ACK`."""
    return ln.startswith("S1-") and ln.split()[0].endswith("-ACK")


def acks_from(rows) -> list:
    """E4.1/E4.2: candidates come ONLY from official messages (codex->claude experiments-prereg), every kind CLOSE
    included. Lines in any other message are ignored entirely: they never close, authorize or refuse. A malformed
    candidate is kept with kind None and its attributed trial_id (E4.3)."""
    out = []
    for mid, sender, recipient, key, body, created in rows:
        if (sender, recipient, key) != ACK_KEY:
            continue                                                                   # E4.2: never a candidate
        for ln in (body or "").split("\n"):
            ln = ln.rstrip("\r")
            if not _is_candidate(ln):
                continue
            try:
                kind, f = parse_ack_line(ln)
            except ValueError as e:
                kind, f = None, {"_malformed": str(e), "trial_id": attributed_trial(ln)}
            out.append(Ack(mid, created, sender, recipient, key, ln, kind, f))
    return out


def scan(mailbox=None) -> list:
    """Every official ACK candidate (mode=ro; raises sqlite3.Error when the mailbox is unreadable)."""
    con = j._ro(mailbox)
    try:
        return acks_from(con.execute(_SCAN).fetchall())
    finally:
        con.close()


def _chain_problems(kind: str, a: Ack, audit: Ack, chosen: dict) -> list:
    pk = PRED[kind]
    pred = audit if pk == "S1-AUDIT-ACK" else chosen.get(pk)
    if pred is None:
        return [f"{kind} {a.mailbox_id}: no {pk} predecessor (F7.1)"]
    probs = []
    if a.fields["prev"] != pred.mailbox_id:
        probs.append(f"{kind} {a.mailbox_id}: prev {a.fields['prev']!r} is not the {pk} {pred.mailbox_id!r} (F7.1)")
    if not a.created > pred.created:
        probs.append(f"{kind} {a.mailbox_id}: created not after its predecessor (F6.1)")
    if a.fields["bundle_sha256"] != audit.fields["bundle_sha256"]:
        probs.append(f"{kind} {a.mailbox_id}: bundle chain broken (F7.1)")
    return probs


def _close(closes: list, audit: Ack, chosen: dict) -> tuple:
    """F7.5 with E4 and E3.4 (controller ruling, Task 4 fix round 1): (the closure or None, problems).
    - Every CLOSE here is an official candidate (E4.1). They are taken in mailbox order (created, then read order).
    - Each is judged against the ACKs created BEFORE it: after the AUDIT-ACK, prev = the latest chain ACK created
      before it, the AUDIT-ACK's bundle. The first that validates is the trial's closure, permanently.
    - Monotone (E3.4): later messages never re-open a closed trial. Any other CLOSE (re-post, different, refused)
      and any chain ACK created after the closure are escalation problems of the closed trial only; a closed trial
      refuses no command of another trial.
    - No valid CLOSE: the trial stays open and its commands refuse, with every refusal reason (and "duplicate" when
      there are several).
    - A BLOCKED CLOSE is validated exactly like every CLOSE, from the mailbox alone (E3.4 r3, A3-PR1-2): S1 never
      recomputes a historical CLOSE's evidence from any directory; Codex verified it against that trial's own root
      at issuance (ruling-6 trust)."""
    if not closes:
        return None, []
    order = [a for _, a in sorted(enumerate(closes), key=lambda p: (p[1].created, p[0]))]
    closed, refused = None, []
    for a in order:
        before = [audit] + [chosen[k_] for k_ in CHAIN[1:] if k_ in chosen and chosen[k_].created < a.created]
        latest = before[-1]
        why = []
        if a.created <= audit.created:
            why.append("before the AUDIT-ACK")
        if a.fields["prev"] != latest.mailbox_id:
            why.append(f"prev is not the latest ACK {latest.mailbox_id!r} created before it")
        if a.fields["bundle_sha256"] != audit.fields["bundle_sha256"]:
            why.append("bundle differs")
        if not why:
            closed = a
            break
        refused.append(f"CLOSE-ACK {a.mailbox_id} refused ({'; '.join(why)})")
    tid = audit.fields["trial_id"]
    if closed is None:
        dup = [f"{len(closes)} CLOSE-ACKs for trial {tid} (duplicate): refuse"] if len(closes) > 1 else []
        return None, dup + [f"{r}: the trial stays open and commands refuse" for r in refused]
    probs = [f"CLOSE-ACK {a.mailbox_id} besides the closure {closed.mailbox_id} of trial {tid}: escalate (the trial "
             f"stays closed, E3.4)" for a in order if a is not closed]
    probs += [f"{k_} {chosen[k_].mailbox_id} created after the closure {closed.mailbox_id} of trial {tid}: escalate "
              f"(the trial stays closed, E3.4)" for k_ in CHAIN[1:] if k_ in chosen
              and chosen[k_].created >= closed.created]
    return closed, probs


def trials(acks) -> dict:
    """Per trial: the ACK chain, CLOSE and problems, from the mailbox alone (no root: E3.4 r3). A malformed candidate
    (E4.3) refuses the trial whose trial_id it names; an unattributable one is handled by open_trial (it refuses every
    trial-bound command)."""
    audits = {}
    for a in acks:
        if a.official and a.kind == "S1-AUDIT-ACK":
            audits.setdefault(a.fields["trial_id"], []).append(a)
    out = {}
    for tid, xs in audits.items():
        audit = min(xs, key=lambda a: a.created)
        probs = ([f"trial_id {tid} is on {len(xs)} AUDIT-ACKs (F6.2): every trial with that id refuses"]
                 if len(xs) > 1 else [])
        by_kind = {}
        for a in acks:
            if a.official and a.kind in CHAIN[1:] and a.fields.get("trial_id") == tid:
                by_kind.setdefault(a.kind, []).append(a)
        for kind in CHAIN[1:]:
            if len(by_kind.get(kind, ())) > 1:
                probs.append(f"{len(by_kind[kind])} {kind} for trial {tid} (F7.1; byte-identical included): escalate")
        chosen = {kind: min(ys, key=lambda a: a.created) for kind, ys in by_kind.items()}
        for kind in CHAIN[1:]:
            if kind in chosen:
                probs += _chain_problems(kind, chosen[kind], audit, chosen)
        closed, cprobs = _close([a for a in acks if a.official and a.kind == "S1-CLOSE-ACK"
                                 and a.fields.get("trial_id") == tid], audit, chosen)
        probs += [f"malformed official ACK line in {a.mailbox_id} names this trial (E4.3): refuse and escalate"
                  for a in acks if a.kind is None and a.fields.get("trial_id") == tid]
        out[tid] = Trial(tid, audit.fields["bundle_sha256"], audit, chosen, closed, probs + cprobs,
                         j.genesis(audit.line))
    return out


def open_trial(mailbox=None) -> Trial:
    """F6.3: exactly one open trial (an AUDIT-ACK with no valid CLOSE-ACK), from the mailbox only. No directory is
    consulted (E3.4 r3): the answer is the same from every root and from the rootless lookup."""
    try:
        acks = scan(mailbox)
    except sqlite3.Error as e:
        raise Refusal(f"mailbox unreadable ({type(e).__name__}): outage refusal (F6.3)") from None
    bad = [a.mailbox_id for a in acks if a.kind is None and a.fields.get("trial_id") is None]
    if bad:
        raise Refusal(f"unattributable malformed official ACK line(s) in {bad[:3]}: every trial-bound command "
                      f"refuses (E4.3): escalate")
    open_ = [x for x in trials(acks).values() if x.closed is None]
    if not open_:
        raise Refusal("zero open trials: trial-bound commands refuse (F6.3)")
    if len(open_) > 1:
        raise Refusal(f"{len(open_)} open trials: refuse and escalate (F6.3)")
    tr = open_[0]
    if tr.problems:
        raise Refusal(f"trial {tr.trial_id}: {tr.problems[:3]}: refuse and escalate")
    return tr


def require_no_open_trial(mailbox=None) -> None:
    """F9 / OQ-20: write_plan runs only without an open trial; an unreadable mailbox refuses (fail closed). A trial
    whose CLOSE was refused is still open."""
    try:
        acks = scan(mailbox)
    except sqlite3.Error as e:
        raise Refusal(f"write_plan refused: mailbox unreadable ({type(e).__name__}) (OQ-20)") from None
    open_ = [x for x in trials(acks).values() if x.closed is None]
    if open_:
        raise Refusal(f"write_plan refused: trial {open_[0].trial_id} is open (F9)")


def check_journal(trial: Trial, rows: list, only: Ack = None) -> list:
    """F7.1/F6.1: each ACK's journal_seq/head names a row of this trial's (verified) journal, the journal extends it
    without a fork, the ACK was created after that row, and stop_line_sha256 is the TRIAL-STOP line."""
    probs = []
    stop = j.first(rows, "TRIAL-STOP")
    for a in ([only] if only is not None else list(trial.acks.values())):
        if "journal_seq" in a.fields:
            n = int(a.fields["journal_seq"])
            if n > len(rows):
                probs.append(f"{a.kind} {a.mailbox_id}: journal_seq {n} beyond the journal ({len(rows)} rows)")
            elif rows[n - 1].sha != a.fields["journal_head_sha256"]:
                probs.append(f"{a.kind} {a.mailbox_id}: journal head at seq {n} differs (fork)")
            elif not a.created > rows[n - 1].created:
                probs.append(f"{a.kind} {a.mailbox_id}: created not after the journal row it references (F6.1)")
        if "stop_line_sha256" in a.fields and (stop is None or stop.sha != a.fields["stop_line_sha256"]):
            probs.append(f"{a.kind} {a.mailbox_id}: stop_line_sha256 is not the TRIAL-STOP line")
    return probs


def state(trial: Trial, rows: list) -> str:
    """F1 with F7.5: CLOSED is an authorization status layered on the journal state."""
    return "CLOSED" if trial.closed is not None else j.trial_state(rows)


def closed_in(con, trial: Trial) -> bool:
    """For a journal Context built inside the BEGIN IMMEDIATE transaction (same connection, same snapshot): the CLOSE
    rows Codex writes into the same sqlite file are read here, so CLOSED is atomic with the append (E2.3 r3). An
    unknown trial counts as closed (fail closed)."""
    tr = trials(acks_from(con.execute(_SCAN).fetchall())).get(trial.trial_id)
    return tr is None or tr.closed is not None


def artifact_fields(kind: str, out: Path) -> dict:
    """The ACK fields bound to current artifacts (the same files the old tokens bound)."""
    out = Path(out)
    plan = c.load_json(out / "plan.json")
    sha = c.sha_or_absent
    if kind == "S1-AUDIT-ACK":
        return {"collector_sha256": c.sha256_file(c.HERE / "s1_collect.py"), "plan_sha256": sha(out / "plan.json"),
                "start": plan["planned_start"]}
    if kind == "S1-OPENING-ACK":
        return {"plan_sha256": sha(out / "plan.json"), "audit_manifest_sha256": sha(out / "audit" / "manifest.json"),
                "opening_seal_sha256": sha(c.opening_seal_path(out, plan)),
                "opening_receipt_sha256": sha(out / "opening_receipt.json")}                            # OQ-30
    if kind == "S1-RUN-ACK":
        return {"runner_sha256": c.sha256_file(c.HERE / "s1_run.py"), "plan_sha256": sha(out / "plan.json"),
                "audit_manifest_sha256": sha(out / "audit" / "manifest.json"),
                "attest_start_sha256": sha(out / "attest_start.json"),
                "opening_seal_sha256": sha(c.opening_seal_path(out, plan)),
                "opening_books_sha256": sha(out / "opening_books.json"), "start": plan["planned_start"]}
    if kind == "S1-PREREG-ACK":
        return {"prereg_sha256": sha(out / "prereg.json")}
    if kind == "S1-ACQUIRE-ACK":
        return {"collector_sha256": c.sha256_file(c.HERE / "s1_collect.py"),
                "final_plan_sha256": sha(out / "final_plan.json"), "prereg_sha256": sha(out / "prereg.json"),
                "attest_stop_sha256": sha(out / "attest_stop.json")}
    if kind == "S1-SCORE-ACK":
        return {"runner_sha256": c.sha256_file(c.HERE / "s1_run.py"),
                "final_manifest_sha256": sha(out / "final" / "manifest.json"),
                "stop_attest_sha256": sha(out / "attest_stop.json"),
                "final_snapshot_sha256": sha(out / "final_snapshot" / "report.json"),
                "stop_sha256": sha(out / "stop.json")}
    return {}


def token(kind: str, root, *, mailbox=None, **given) -> str:
    """The exact ACK line for `kind` from the current artifacts and the open trial (tests; Codex's cross-check).
    `given` supplies issuer-only fields (evidence_manifest_sha256, opening_slot, reason, evidence_sha256) or
    overrides. Refusal when the trial lookup refuses or the predecessor ACK is absent; ValueError when a field has
    no value."""
    out = Path(root) / "s1_out"
    if kind == "S1-AUDIT-ACK":
        return c.audit_token(out)
    if kind not in ACK_FIELDS:
        raise ValueError(f"not an S1 ACK kind: {kind!r}")
    tr = open_trial(mailbox)
    try:
        rows = j.read_trial(tr.trial_id, tr.genesis, mailbox)
    except j.JournalError as e:
        raise Refusal(f"{kind}: the trial's journal does not verify ({e})") from None
    vals = {"trial_id": tr.trial_id, "bundle_sha256": tr.bundle}
    if kind == "S1-CLOSE-ACK":
        vals["prev"] = tr.latest.mailbox_id
    else:
        pred = tr.audit if PRED[kind] == "S1-AUDIT-ACK" else tr.acks.get(PRED[kind])
        if pred is None:
            raise Refusal(f"no {PRED[kind]} for trial {tr.trial_id}: no {kind} can follow (F7.1)")
        vals["prev"] = pred.mailbox_id
    if rows:
        vals.update(journal_seq=str(rows[-1].seq), journal_head_sha256=rows[-1].sha)
    stop = j.first(rows, "TRIAL-STOP")
    if stop is not None:
        vals["stop_line_sha256"] = stop.sha
    vals.update(artifact_fields(kind, out))
    vals.update({n: str(v) for n, v in given.items()})
    missing = [n for n in ACK_FIELDS[kind] if n not in vals]
    if missing:
        raise ValueError(f"{kind}: no value for {missing}")
    return " ".join([kind] + [f"{n}={vals[n]}" for n in ACK_FIELDS[kind]])


def verify_ack(trial: Trial, rows: list, kind: str, ack_id, expected: dict) -> Ack:
    """The trial's one `kind` ACK: `ack_id` (when given) must be it (F6.5: another trial's or a stray ACK never
    counts); its artifact-bound fields equal `expected`; its journal binding holds (F7.1); it is not in the
    future."""
    a = trial.audit if kind == "S1-AUDIT-ACK" else trial.acks.get(kind)
    if a is None:
        raise Refusal(f"no {kind} for trial {trial.trial_id}" + ("" if ack_id is None else
                      f": {ack_id!r} does not count (F6.5: another trial's or a stray ACK never counts)"))
    if ack_id is not None and a.mailbox_id != ack_id:
        raise Refusal(f"{ack_id!r} is not the trial's {kind} (F6.5: another trial's or a stray ACK never counts)")
    bad = sorted(n for n, v in expected.items() if a.fields.get(n) != v)
    if bad:
        raise Refusal(f"{kind} {a.mailbox_id}: {bad} differ from the current artifacts")
    probs = check_journal(trial, rows, only=a)
    if probs:
        raise Refusal(f"{kind} {a.mailbox_id}: {probs}")
    if datetime.fromtimestamp(a.created, tz=timezone.utc) > c.now_utc():
        raise Refusal(f"{kind} {a.mailbox_id}: ack is in the future")
    return a


def ack_record(a: Ack) -> dict:
    return {"ack_id": a.mailbox_id, "created_utc": datetime.fromtimestamp(a.created, tz=timezone.utc).isoformat()}


def close_evidence(kind: str, *, score_record: bytes = None, rows=None, withdrawal: str = None,
                   blocked_record: dict = None) -> str:
    """F7.5 evidence_sha256: SCORED = the score record bytes; INVALID = the first TRIAL-INVALID line; WITHDRAWN = the
    operator withdrawal message (UTF-8); BLOCKED = sha256(c.canonical({"trial_id", "reasons"})) (E3.4 r1), never the
    blocked.json bytes. Codex computes it at issuance; S1 offers the same function for that cross-check and never
    calls it to validate a historical CLOSE (E3.4)."""
    if kind == "SCORED":
        if not isinstance(score_record, bytes):
            raise ValueError("SCORED evidence needs the score record bytes")
        return c.sha256_bytes(score_record)
    if kind == "INVALID":
        first = j.first(rows or [], "TRIAL-INVALID")
        if first is None:
            raise ValueError("INVALID evidence needs a TRIAL-INVALID row")
        return first.sha
    if kind == "WITHDRAWN":
        if not isinstance(withdrawal, str):
            raise ValueError("WITHDRAWN evidence needs the operator withdrawal message")
        return c.sha256_bytes(withdrawal.encode("utf-8"))
    if kind == "BLOCKED":                                         # E3.4 r1: h over {trial_id, reasons}, not file bytes
        return c.sha256_bytes(c.canonical({"trial_id": blocked_record["trial_id"],
                                           "reasons": blocked_record["reasons"]}))
    raise ValueError(f"no evidence rule for {kind!r}")
