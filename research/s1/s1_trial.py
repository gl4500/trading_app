"""S1 external trial identity (Addendum 3 rev 5 F6, F7, F9; Erratum 1 E3.4, E4). The open trial, its ACK chain and
its CLOSE are found from the coordination mailbox only (opened mode=ro, F6.3); the trial gate (Task 5) is built on
these readers. Codex issues ACKs; S1 code only reads them. Token texts: ACK_FIELDS (exact fields in order, F6.1,
OQ-5). No function here takes an output root for the trial lookup: closure is monotone from mailbox history alone
(E3.4 r3), and S1 never recomputes a historical CLOSE's evidence."""
import json
import math
import re
import sqlite3
import sys
from dataclasses import dataclass, field
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
LOCAL_ABORT = "local-abort"     # A3 H1 (Erratum 2 r4 G6.2; ruling OP-5): the recovery record's subtype (not SUBTYPES)


class Refusal(SystemExit):
    """A trial-bound command refuses (identity, chain, CLOSE, outage): zero callbacks, no row."""


class MailboxOutage(Refusal):
    """The mailbox could not be read for the trial lookup (F6.3 outage refusal)."""


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
        """A3 H2 (Clarification 1 C1.1): the latest chain ACK by creation chronology (the default prev of a CLOSE
        token); in a valid normal chain it is the CHAIN-rank last (C1.4). A tie keeps the rank order's last - a
        tied CLOSE is refused by _close anyway (C1.2)."""
        present = [self.audit] + [self.acks[k_] for k_ in CHAIN[1:] if k_ in self.acks]
        return max(reversed(present), key=lambda a: a.created)


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


def pred_kind(kind: str, chosen: dict, created=None) -> str:
    """F7.1 PRED with A3 H2 (Erratum 2 r4 G1.4, O2): an S1-SCORE-ACK has two syntactically valid shapes - prev = the
    latest chain ACK created before it among {S1-ACQUIRE-ACK, S1-PREREG-ACK}: the ACQUIRE-ACK when one exists created
    before it (`created`; None = the ACK to be issued now, after every existing one), else the PREREG-ACK (NO-VALID-SEAL
    only). Parsing grants no authority: the score/journal gate decides the branch on its rows (s1_stage.permitted).
    Every other kind: PRED."""
    if kind != "S1-SCORE-ACK":
        return PRED[kind]
    acq = chosen.get("S1-ACQUIRE-ACK")
    return "S1-ACQUIRE-ACK" if acq is not None and (created is None or acq.created < created) else "S1-PREREG-ACK"


def _chain_problems(kind: str, a: Ack, audit: Ack, chosen: dict) -> list:
    pk = pred_kind(kind, chosen, a.created)
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


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _close_chronology(a: Ack, audit: Ack, chosen: dict, invalid: set, malformed: list, dups=()) -> tuple:
    """A3 H2, Erratum 2 Clarification 1 r2 C1 (Codex 6bfdc5cc OP-10; O-C1; ruling NOP-1, Codex 59953cfd: C1.2 kept
    exactly, no reason-specific exemption): (the predecessor the CLOSE `a` must name, or None, why-not). Candidates =
    the AUDIT-ACK plus every chosen chain ACK of the trial (official, same trial_id; F7.1/F6.1 and the G1.4
    mailbox-level shapes, the AUDIT-ACK's bundle: `invalid` names the kinds with a _chain_problems entry) created
    strictly before `a`. "Latest" = the greatest persisted `created`, never CHAIN rank (the retired rank reading took
    the rank-last ACK). Refuse and escalate (no predecessor chosen, nothing withdrawn, invented or deleted) when:
    `a`'s or a candidate's `created` is not a finite number; a chain ACK created before `a` is not chain-valid; an
    official MALFORMED line naming this trial (E4.3) was created before `a` (its kind and chain validity cannot be
    established, so neither can the predecessor chronology); or two candidates tie for the greatest `created` (exact
    equality of the persisted values, O-C1: no read-order or UUID tie-break).
    H2 fix round 1 (review I-1): `dups` = every official same-trial chain ACK that is NOT the chosen (earliest) one
    of its kind. F7.1 allows at most one ACK of each kind, so such a duplicate is not chain-valid: created before
    `a`, it refuses and escalates `a` like any invalid candidate (C1.2). A duplicate created after the closure stays
    an escalation of the closed trial only (monotonicity, C1.3)."""
    esc = "refuse and escalate (C1.2)"
    if not _finite(a.created) or not _finite(audit.created):
        return None, f"chronology cannot be established (created not a finite number): {esc}"
    before = [x for x in chosen.values() if not _finite(x.created) or x.created < a.created]
    if any(not _finite(x.created) for x in before):
        return None, f"a chain ACK's chronology cannot be established (created not a finite number): {esc}"
    bad = sorted({x.mailbox_id for x in before if x.kind in invalid}
                 | {x.mailbox_id for x in dups if not _finite(x.created) or x.created < a.created})
    if bad:
        return None, f"chain ACK(s) {bad} created before it are not chain-valid: {esc}"
    mal = sorted(m.mailbox_id for m in malformed if not _finite(m.created) or m.created < a.created)
    if mal:
        return None, f"malformed official ACK line(s) {mal} naming this trial precede it (E4.3): {esc}"
    cands = [audit] + before                              # (the AUDIT-ACK always: a CLOSE before it is refused as such)
    top = max(x.created for x in cands)
    tied = [x for x in cands if x.created == top]
    if len(tied) > 1:
        return None, f"ambiguous latest predecessor: {sorted(x.mailbox_id for x in tied)} tie on created: {esc}"
    return tied[0], None


def _close(closes: list, audit: Ack, chosen: dict, invalid: set = frozenset(), malformed: list = (),
           dups: list = ()) -> tuple:
    """F7.5 with E4 and E3.4 (controller ruling, Task 4 fix round 1): (the closure or None, problems).
    - Every CLOSE here is an official candidate (E4.1). They are taken in mailbox order (created, then read order).
    - Each is judged against the ACKs created BEFORE it: after the AUDIT-ACK, prev = the latest chain ACK created
      before it, the AUDIT-ACK's bundle. The first that validates is the trial's closure, permanently.
    - A3 H2 (Clarification 1 r2 C1, recorded explicitly, C1.8 - not a silent refactor): "latest" is decided by
      CREATION CHRONOLOGY among the individually chain-valid candidates (_close_chronology), not by CHAIN rank; a tie,
      an unestablishable chronology or a non-chain-valid / malformed candidate before it refuses and escalates.
      In a valid normal chain chronology equals rank (C1.4), so those verdicts are unchanged.
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
        latest, unclear = _close_chronology(a, audit, chosen, invalid, malformed, dups)
        why = []
        if not (_finite(a.created) and a.created > audit.created):
            why.append("before the AUDIT-ACK")
        if unclear is not None:
            why.append(unclear)
        elif a.fields["prev"] != latest.mailbox_id:
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
        invalid = set()                                   # A3 H2 (C1.2): kinds that are not individually chain-valid
        for kind in CHAIN[1:]:
            if kind in chosen:
                cp = _chain_problems(kind, chosen[kind], audit, chosen)
                probs += cp
                if cp:
                    invalid.add(kind)
        malformed = [a for a in acks if a.kind is None and a.fields.get("trial_id") == tid]
        dups = [a for kind, ys in by_kind.items() for a in ys if a is not chosen[kind]]   # (fix round 1, I-1)
        closed, cprobs = _close([a for a in acks if a.official and a.kind == "S1-CLOSE-ACK"
                                 and a.fields.get("trial_id") == tid], audit, chosen, invalid, malformed, dups)
        probs += [f"malformed official ACK line in {a.mailbox_id} names this trial (E4.3): refuse and escalate"
                  for a in malformed]
        out[tid] = Trial(tid, audit.fields["bundle_sha256"], audit, chosen, closed, probs + cprobs,
                         j.genesis(audit.line))
    return out


def open_trial(mailbox=None) -> Trial:
    """F6.3: exactly one open trial (an AUDIT-ACK with no valid CLOSE-ACK), from the mailbox only. No directory is
    consulted (E3.4 r3): the answer is the same from every root and from the rootless lookup."""
    try:
        acks = scan(mailbox)
    except sqlite3.Error as e:
        raise MailboxOutage(f"mailbox unreadable ({type(e).__name__}): outage refusal (F6.3)") from None
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
        pk = pred_kind(kind, tr.acks)                        # A3 H2 (G1.4): the SCORE-ACK's branch-aware prev
        pred = tr.audit if pk == "S1-AUDIT-ACK" else tr.acks.get(pk)
        if pred is None:
            raise Refusal(f"no {pk} for trial {tr.trial_id}: no {kind} can follow (F7.1)")
        vals["prev"] = pred.mailbox_id
    if rows:
        vals.update(journal_seq=str(rows[-1].seq), journal_head_sha256=rows[-1].sha)
    stop = j.first(rows, "TRIAL-STOP")
    if stop is not None:
        vals["stop_line_sha256"] = stop.sha
    vals.update(artifact_fields(kind, out))
    if kind == "S1-OPENING-ACK":
        vals.update(_opening_derived(root, out, rows, given, mailbox))
    vals.update({n: str(v) for n, v in given.items()})
    missing = [n for n in ACK_FIELDS[kind] if n not in vals]
    if missing:
        raise ValueError(f"{kind}: no value for {missing}")
    return " ".join([kind] + [f"{n}={vals[n]}" for n in ACK_FIELDS[kind]])


def _opening_derived(root, out, rows, given, mailbox) -> dict:
    """A3 Task 10 (token, S1-OPENING-ACK): the issuer-side fields the journal determines, unless `given`: opening_slot
    = the first QUALIFIED opening-close slot (F3, OQ-37 / row 270), and evidence_manifest_sha256 = the sha256 of the
    E5.5 reconstruction at the journal head. A field that cannot be derived (no opening yet, a file missing) is left
    out (token then raises ValueError naming it)."""
    import s1_gates
    import s1_slot
    got = {}
    if "opening_slot" not in given:
        try:
            cal = s1_gates.verified_audit(out, mailbox)["calendar"]
            plan = c.load_json(out / "plan.json")
            q = s1_slot.first_qualified(rows, next(d for d in cal if d["date"] == plan["opening_close"]), cal)
            if q is not None:
                got["opening_slot"] = q.subject
        except (s1_gates.Invalid, OSError, ValueError, KeyError, TypeError, StopIteration, SystemExit):
            pass                                         # not derivable: the field stays missing (token: ValueError)
    if "evidence_manifest_sha256" not in given and rows:
        try:
            got["evidence_manifest_sha256"] = c.sha256_bytes(c.canonical(evidence_manifest(root, rows,
                                                                                           rows[-1].seq)))
        except (OSError, ValueError, KeyError, TypeError, SystemExit):
            pass
    return got


def verify_opening_ack(gv, cal) -> Ack:
    """F7.2 (b-d) / F7.4 on the S1 side, for the START attestation: the trial's OPENING-ACK binds the current plan,
    audit manifest, opening seal and opening receipt (file hashes, OQ-30), the trial and the bundle (verify_ack: also
    its journal binding, F7.1). Within the journal prefix it names (rows[:journal_seq]): its opening_slot is the first
    QUALIFIED opening-close slot with every earlier slot terminal (F3, OQ-37 / row 270); EVERY scheduled opening-close
    slot has a terminal row (F7.2(b) literal, OQ-37 ruling: later rows never repair the ACK's prefix); the opening stage
    is CREATED and the trial ACTIVE. The evidence manifest is reconstructed (E5.5: a mismatch is INVALIDATE
    registration-artifact, never a mere refusal). The ACK is created strictly before now, the start_attest INTENT's
    instant (E5.3, OQ-18). Anything else: no START (Refusal, no row)."""
    import s1_seal as z
    import s1_slot
    import s1_stage
    out = gv.out
    plan = c.load_json(out / "plan.json")
    if "S1-OPENING-ACK" not in gv.trial.acks:
        raise Refusal("START attestation refused: no S1-OPENING-ACK (F7.4: no START without it)")
    a = verify_ack(gv.trial, gv.rows, "S1-OPENING-ACK", None,
                   dict(artifact_fields("S1-OPENING-ACK", out), trial_id=plan.get("trial_id"),
                        bundle_sha256=c.bundle_sha256()))
    rows_at = gv.rows[:int(a.fields["journal_seq"])]
    day = next((d for d in cal if d["date"] == plan.get("opening_close")), None)
    if day is None:
        raise Refusal("START attestation refused: the plan's opening close is not in the audit calendar")
    q = s1_slot.first_qualified(rows_at, day, cal)
    if q is None or q.subject != a.fields["opening_slot"]:
        raise Refusal(f"START attestation refused: the OPENING-ACK opening_slot {a.fields['opening_slot']} is not the "
                      f"first QUALIFIED opening slot (with every earlier slot terminal) at its journal_seq "
                      f"({q.subject if q is not None else 'none'}; F3, F7.2 c)")
    open_slots = [j.slot_subject(s) for s in z.schedule(day, cal)]
    unterminated = [s for s in open_slots if j.first(j.subject_rows(rows_at, s), *j.TERMINAL) is None]
    if unterminated:                                                               # F7.2(b) literal (OQ-37)
        raise Refusal(f"START attestation refused: F7.2 (b): {len(unterminated)} scheduled opening-close slot(s) have "
                      f"no terminal row in the OPENING-ACK's journal prefix (first {unterminated[0]})")
    if s1_stage.stage_rows(rows_at, "opening")["created"] is None or j.trial_state(rows_at) != "ACTIVE":
        raise Refusal("START attestation refused: the opening stage is not CREATED (or the trial not ACTIVE) at the "
                      "OPENING-ACK's journal_seq (F7.2 c, d)")
    opening_manifest_check(gv, a)                                                  # E5.5 / F7.3: INVALIDATE
    if not datetime.fromtimestamp(a.created, tz=timezone.utc) < c.now_utc():       # E5.3: before the INTENT
        raise Refusal("START attestation refused: the OPENING-ACK is not created before the START attestation (E5.3)")
    return a


def _manifest_sha(root, rows, seq) -> str:
    """The reconstructed manifest's sha256, or "unreconstructible (...)" ONLY for definite absence or corruption (a
    member gone, unparseable or malformed; an unregistered slot). Fix round 1 (review M2, F0.7, F5.5): any other
    OSError (a sharing violation, ERROR_ACCESS_DENIED, an I/O error) is no evidence of damage: a refusal with no row."""
    try:
        return c.sha256_bytes(c.canonical(evidence_manifest(root, rows, seq)))
    except (FileNotFoundError, ValueError, KeyError, TypeError, SystemExit) as e:   # gone / corrupt: unreconstructible
        return f"unreconstructible ({type(e).__name__})"
    except OSError as e:
        raise Refusal(f"E5.5 evidence manifest check: a member could not be read ({type(e).__name__}): refused with "
                      f"no row (F0.7, F5.5)") from None


def opening_manifest_check(gv, a=None) -> None:
    """E5.5 (Erratum 1 r1/r2/r4) as part of the F7.3 live-file check: once the trial has an OPENING-ACK, the evidence
    manifest reconstructed for its journal_seq (live bytes) must hash to its evidence_manifest_sha256. A wrong hash or
    a wrong membership, with otherwise valid files, is INVALIDATE (registration-artifact) - never a mere refusal. Run
    by every gate after s1_stage.evaluate and s1_slot.evidence_check (so a damaged member is reported as
    stage-replaced or by the F3 table first), and by verify_opening_ack. A mismatch is confirmed on rows re-read after
    it was first observed (Task 7 I1: every registration-artifact INVALID confirms on re-read)."""
    a = a if a is not None else gv.trial.acks.get("S1-OPENING-ACK")
    if a is None:
        return
    want, seq = a.fields["evidence_manifest_sha256"], int(a.fields["journal_seq"])
    got = _manifest_sha(gv.root, gv.rows, seq)
    if got == want:
        return
    try:
        again = j.read_trial(gv.trial.trial_id, gv.trial.genesis, gv.mailbox)
    except j.JournalError as e:
        raise Refusal(f"E5.5 evidence manifest check: journal unreadable ({type(e).__name__}): refused with no row "
                      f"(F0.7)") from None
    got = _manifest_sha(gv.root, again, seq)
    if got == want:
        return
    invalidate(gv.trial, "registration-artifact",
               {"where": "evidence manifest (E5.5)", "expected": want, "reconstructed": got, "journal_seq": seq},
               root=gv.root, mailbox=gv.mailbox)
    raise Refusal("OPENING-ACK evidence manifest differs from the reconstruction (E5.5): INVALID "
                  "(registration-artifact)")


def evidence_manifest(root, rows, journal_seq) -> dict:
    """E5.5 (Erratum 1 r1, r2, r4) exact byte format and membership, used identically by Codex when issuing:
    c.canonical({"trial_id", "journal_seq", "journal_head_sha256", "files": {relpath: sha256}}), where `files`
    covers, for the rows with seq <= journal_seq: plan.json and opening_receipt.json; every file of every QUALIFIED or
    FAILED tree; every CREATED stage member (the audit members included); the staging intent.json and prepared.json of
    every stage with an INTENT or PREPARED row (OQ-35), keyed `staging/<stage>/<name>` - a label of the real file
    <root>/s1_staging/<trial_id>/<stage>/<name>, outside s1_out (a seal stage nests: staging/seal/<date>/<name>).
    Relpaths are relative to s1_out; every sha256 is of the LIVE bytes now (r2); c.canonical sorts the keys. The
    CREATED membership comes from the stage's committed prepared.json (verified against its PREPARED row). Never
    reads Codex's folder. Raises (OSError, ValueError, KeyError, SystemExit) when a member is gone."""
    import s1_seal as z
    import s1_slot
    import s1_stage
    root = Path(root)
    out = root / "s1_out"
    pre = rows[:journal_seq]
    tid = c.load_json(out / "plan.json")["trial_id"]
    files = {"plan.json": c.sha256_file(out / "plan.json"),
             "opening_receipt.json": c.sha256_file(out / "opening_receipt.json")}
    cal = None
    for r_ in pre:
        if r_.kind in ("SLOT-QUALIFIED", "SLOT-FAILED"):
            if cal is None:
                cal = z.calendar_rows(c.load_json(out / "audit" / "calendar.json"))
            s = s1_slot.slot_of(r_.subject)
            tree = s1_slot.qualified_tree if r_.kind == "SLOT-QUALIFIED" else s1_slot.failed_tree
            files.update(tree(out, s, s1_slot.day_for(s, cal)["date"]))
        elif r_.kind in ("STAGE-INTENT", "STAGE-PREPARED"):
            stage = r_.subject[len("stage/"):]
            name = "intent.json" if r_.kind == "STAGE-INTENT" else "prepared.json"
            files[f"staging/{stage}/{name}"] = c.sha256_file(s1_stage.staging_dir(root, tid, stage) / name)
        elif r_.kind == "STAGE-CREATED":
            stage = r_.subject[len("stage/"):]
            for rel in s1_stage.committed_commitment(root, tid, stage, pre)["members"]:
                files[rel] = c.sha256_file(out / rel)                              # r2: the live bytes
    return {"trial_id": tid, "journal_seq": journal_seq, "journal_head_sha256": pre[-1].sha if pre else None,
            "files": dict(sorted(files.items()))}


def opening_issuance(root, mailbox=None) -> dict:
    """F7.2 b-d support for Codex's issuance checklist (procedural on Codex's side; one frozen snapshot): the gate
    (d: ACTIVE, F3/F4 hold, the journal chain), EVERY scheduled opening-close slot terminal (b, literal: OQ-37 ruling;
    E5.6: so not before the E of the last scheduled opening-close slot), the opening slot = the earliest QUALIFIED
    with every earlier slot terminal (F3), the opening stage CREATED (c), and the reconstructed evidence manifest at
    the journal head (E5.5). Refusal (SystemExit) when the gate refuses."""
    import s1_gates
    import s1_seal as z
    import s1_slot
    import s1_stage
    gv = gate(root, "opening issuance check", mailbox=mailbox)
    try:
        cal = s1_gates.verified_audit(gv.out, mailbox)["calendar"]
    except s1_gates.Invalid as e:
        raise Refusal(f"opening issuance check refused: audit not verified ({e})") from None
    plan = c.load_json(gv.out / "plan.json")
    day = next((d for d in cal if d["date"] == plan.get("opening_close")), None)
    if day is None:
        raise Refusal("opening issuance check refused: the plan's opening close is not in the audit calendar")
    q = s1_slot.first_qualified(gv.rows, day, cal)
    reasons = []
    if q is None:
        reasons.append("an opening slot before the first QUALIFIED one is in flight, or none qualified (F3, b)")
    open_ = [j.slot_subject(s) for s in z.schedule(day, cal)
             if j.first(j.subject_rows(gv.rows, j.slot_subject(s)), *j.TERMINAL) is None]
    if open_:                                                                      # F7.2(b) literal (OQ-37)
        reasons.append(f"{len(open_)} scheduled opening-close slot(s) have no terminal row yet (b; first {open_[0]})")
    if s1_stage.stage_rows(gv.rows, "opening")["created"] is None:
        reasons.append("the opening stage is not CREATED (c)")
    f = artifact_fields("S1-OPENING-ACK", gv.out)
    man = None if reasons else evidence_manifest(gv.root, gv.rows, gv.rows[-1].seq)
    return {"eligible": not reasons, "reasons": reasons, "opening_slot": q.subject if q is not None else None,
            "evidence_manifest_sha256": c.sha256_bytes(c.canonical(man)) if man is not None else None,
            "journal_seq": gv.rows[-1].seq if gv.rows else 0,
            "journal_head_sha256": gv.rows[-1].sha if gv.rows else None,
            "opening_seal_sha256": f["opening_seal_sha256"], "opening_receipt_sha256": f["opening_receipt_sha256"]}


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


@dataclass
class Gate:
    """What gate() read, for the command that called it (F0.6)."""
    root: Path
    out: Path
    trial: Trial
    rows: list
    state: str
    mailbox: object = None
    deferred: list = field(default_factory=list)      # A3 Task 6 (N2): pending stages a slot-path gate deferred


def _record(out: Path, where: str, msg, now=None) -> None:
    """Review I-1 (F6.6): the gate NEVER creates or writes into a missing s1_out. A refusal is preserved in
    s1_out/refusals.jsonl only when that tree exists; otherwise it goes to stderr (the total-loss evidence is the
    tree's absence, which a recreated s1_out would destroy)."""
    if Path(out).is_dir():
        c.record_refusal(Path(out), where, msg, now)
    else:
        print(f"S1 {where} refused (s1_out absent; not recorded there): {msg}", file=sys.stderr)


def _refuse(out: Path, where: str, msg: str, now=None):
    _record(out, where, msg, now)
    raise Refusal(f"{where} refused: {msg}")


def invalidate(trial: Trial, reason: str, record: dict, *, root, mailbox=None, clock=None,
               recovery: bool = False) -> j.Result:
    """Commit TRIAL-INVALID(reason) for a gate-found violation (detail = the observation record; a fresh op and
    actor, OQ-2); best-effort evidence copy s1_out/invalid/<seq>.json with the same canonical bytes (never for LOST:
    s1_out is not recreated). If the journal cannot be written, the observation is the F8.1 residual: a local
    aborted.json is attempted and the command refuses (no further work); nothing claims the violation was recorded
    externally.
    A3 H1 (Erratum 2 r4): `recovery` (G6.5, O17) marks the gate's surviving-local-abort recovery request - decide()
    then refuses when ANY TRIAL-INVALID is on the transaction's re-read rows, and the REFUSE Result comes back with no
    row and no evidence copy. The journal-failure refusal says truthfully whether the local abort was published
    (G6.3). Neither the local abort nor the evidence copy ever creates s1_out (G6.1/G6.3, O16): write_abort never
    does, and invalid/ is created non-recursively under an existing root and published with mkdir=False, so a root
    that vanished leaves the copy unpublished while the committed row stands."""
    req = j.Request("TRIAL-INVALID", j.invalid_subject(reason), j.new_nonce(), j.new_nonce(),
                    detail=j.detail_of(record))
    out = Path(root) / "s1_out"
    try:
        res = j.append(trial.trial_id, trial.genesis, req,
                       lambda rows, con: j.Context(closed=closed_in(con, trial), recovery=recovery),
                       mailbox=mailbox, clock=clock)
    except j.JournalError as e:
        if reason == "LOST":
            local = "no local abort (LOST: s1_out is not recreated)"
        elif not out.is_dir():                           # (caller guard kept; the helper never recreates it either)
            local = "local abort not published (s1_out is gone)"
        else:
            wit = {"reason": f"uncommitted {reason}", "record": record, "journal_error": str(e), "actual": None,
                   "close": None, "scheduled": None, "projection_sha256": None, "receipt_sha256": None}
            try:
                stored = c.write_abort(out, wit)
                local = ("local abort published" if stored is wit
                         else "local abort not published (an earlier aborted.json is kept: first wins)")
            except OSError as w:
                local = f"local abort not published ({type(w).__name__})"
        raise Refusal(f"violation ({reason}) observed but the journal could not be written ({type(e).__name__}): "
                      f"refused; {local}; F8.1 residual (lost detection if it never commits)") from None
    if res.row is not None and reason != "LOST" and out.is_dir():
        try:
            (out / "invalid").mkdir(exist_ok=True)          # non-recursive: never recreates a vanished s1_out
            c.publish_exclusive(out / "invalid" / f"{res.row.seq}.json", c.canonical(record), mkdir=False)
        except OSError:                                  # (FileExistsError included) best effort evidence copy
            pass
    return res


def invalidate_current(out: Path, reason: str, record: dict, mailbox=None, *, clock=None) -> None:
    """For legacy detectors (OQ-19): commit TRIAL-INVALID for the open trial; any failure is the F8.1 residual
    (the caller still writes its local aborted.json). `clock`: the detector's observation clock (the row's `at`)."""
    try:
        tr = open_trial(mailbox)
        invalidate(tr, reason, record, root=Path(out).parent, mailbox=mailbox, clock=clock)
    except (Refusal, j.JournalError):
        pass


def trial_in(con, trial: Trial):
    """A3 H2 (ruling OP-25, Codex 6bfdc5cc; ruling NOP-3): the trial as the official ACKs parsed from `con` - the BEGIN
    IMMEDIATE connection - give it inside the deciding transaction (as closed_in reads CLOSE), or a refusal reason:
    an unattributable malformed official line, the trial absent from that view or bound to another AUDIT-ACK, or any
    ACK-chain problem of the trial in that view refuses (fail closed, the same refusals as open_trial). A gate
    snapshot is never authoritative for absence (C1.9)."""
    acks = acks_from(con.execute(_SCAN).fetchall())
    if any(a.kind is None and a.fields.get("trial_id") is None for a in acks):
        return ("the transaction's ACK view has an unattributable malformed official ACK line (E4.3): refuse and "
                "escalate")
    tr = trials(acks).get(trial.trial_id)
    if tr is None or tr.audit.mailbox_id != trial.audit.mailbox_id:
        return f"trial {trial.trial_id} is not the same trial in the transaction's ACK view: fail closed (OP-25)"
    if tr.problems:
        return f"trial {trial.trial_id}: the transaction's ACK view {tr.problems[:3]}: refuse and escalate (OP-25)"
    return tr


def product_context(trial: Trial, cal=None, *, slot_gate=None, stage_gate=None, stop_detail=None,
                    stage_check=None, stop_fence=None, stop_ready=None, acks_in_txn=False):
    """The Context every product append uses: CLOSED read inside the transaction from the CLOSE rows of the same
    sqlite file (`con`, the BEGIN IMMEDIATE connection; E2.3 r3: atomic with CLOSE); slot timing from the pinned
    calendar (Task 6 supplies slot_times through s1_slot); stage/slot gates, the seal selection check, the stop rule
    and the STOP fence from their owners. A missing slot_gate, stage_check, stage_gate, stop_detail, stop_fence or slot
    timing fails closed in decide() itself (Task 2 carry-forward; review M-6: also for a raw j.Context).
    A3 H2 (ruling OP-25): `acks_in_txn` - the stage gate is called as stage_gate(rows, stage, trial) with the trial
    re-parsed from the official ACKs of `con` inside this transaction (trial_in, parsed only when the gate runs, i.e.
    for a STAGE-INTENT); a refusal reason of trial_in refuses the INTENT with no row."""

    def build(rows, con):
        st_ = None
        if cal is not None:
            import s1_slot                                   # (Task 6 module; absent before Task 6, cal is None)
            st_ = s1_slot.slot_times(cal)
        gate_ = stage_gate
        if acks_in_txn and stage_gate is not None:
            def gate_(rows_, g):
                tr_ = trial_in(con, trial)
                return tr_ if isinstance(tr_, str) else stage_gate(rows_, g, tr_)
        return j.Context(closed=closed_in(con, trial), slot_times=st_, stop_detail=stop_detail,
                         stage_gate=gate_, slot_gate=slot_gate, stage_check=stage_check,
                         stop_fence=stop_fence, stop_ready=stop_ready)    # A3 Task 11: (rows, txn now)
    return build


def gate(root, where: str, *, mailbox=None, now=None, defer_pending=False) -> Gate:
    """F0.6: the first step of every trial-bound command, before any callback, capture, provider request or pricing:
    the open trial (F6.3) and its ACK chain (F7.1) from the mailbox; the journal (chain, F0.5 step 1); the trial
    state (F1: INVALID refuses with no work, F0.6 - checked before the bundle so re-entry adds no repeat row); total
    loss (F6.6: INVALID (LOST)); the bundle against the AUDIT-ACK's (F6.4: refusal before any row, INVALID (bundle) +
    local abort after); the plan's trial_id (F6.2; after any row, plan.json as the audit bound input,
    _plan_after_rows, A3 Task 14b); then (A3 H1, Erratum 2 r4 G6.4) the recovery of a surviving local abort
    (_recover_local_abort: recorded once as INVALID (established-violation, local-abort), then a refusal with no
    work). The gate never creates or writes into a missing s1_out (review I-1). `now`: the command's clock callable (refusal records, the INVALID row's `at`). `defer_pending` (A3 Task 6,
    ruling N2, Erratum 1 E1.2): only the slot paths pass True - a stage whose lock is held by a live (possibly stalled)
    owner is recorded in gv.deferred instead of refusing "pending", so deadline arbitration is never blocked by a
    work lock. Hooks, in order, after the plan check (a foreign root is never judged): the F4 stage table
    (s1_stage.evaluate), the F3 evidence table (s1_slot.evidence_check), then (A3 Task 10) the E5.5 evidence-manifest
    check of the OPENING-ACK (opening_manifest_check)."""
    root = Path(root)
    out = root / "s1_out"
    try:
        tr = open_trial(mailbox)                                        # mailbox only: closure is monotone (E3.4 r3)
        rows = j.read_trial(tr.trial_id, tr.genesis, mailbox)
    except (Refusal, j.JournalError) as e:
        if isinstance(e, (MailboxOutage, j.Outage)):
            _legacy_detectors(out, where, now, mailbox)                 # B3.4: an outage never downgrades a violation
        _refuse(out, where, str(e), now)
    probs = check_journal(tr, rows)
    if probs:
        _refuse(out, where, f"ACK journal binding {probs[:3]} (F7.1): escalate", now)
    st_ = state(tr, rows)
    if st_ == "INVALID":                                  # review M-3: before the bundle - no repeat INVALID rows
        bad = j.first(rows, "TRIAL-INVALID")
        if out.is_dir():                                  # (never recreates a lost s1_out)
            try:
                c.write_abort(out, {"reason": f"journal INVALID ({bad.subject})", "first_invalid_line_sha256": bad.sha,
                                    "actual": None, "close": None, "scheduled": None, "projection_sha256": None,
                                    "receipt_sha256": None})
            except OSError:
                pass
        raise Refusal(f"{where} refused: trial INVALID ({bad.subject}): no work (F0.6, F1)")
    if rows and not out.is_dir():                         # review I-1: total loss before the bundle (F6.6)
        invalidate(tr, "LOST", {"where": where, "missing": "s1_out"}, root=root, mailbox=mailbox, clock=now)
        raise Refusal(f"{where} refused: s1_out is gone under an open trial with journal rows: INVALID (LOST)")
    observed = c.bundle_sha256()
    if observed != tr.bundle:
        if not rows:
            _refuse(out, where, f"S1 bundle {observed[:12]} differs from the AUDIT-ACK's {tr.bundle[:12]} "
                                f"(no journal row yet)", now)
        rec = {"where": where, "expected_bundle_sha256": tr.bundle, "observed_bundle_sha256": observed,
               "problems": c.bundle_problems(c.bundle_manifest())}
        invalidate(tr, "bundle", rec, root=root, mailbox=mailbox, clock=now)
        try:                                              # (s1_out exists: loss checked; H1 O16: if it vanished
            c.write_abort(out, dict(rec, reason="bundle", actual=None, close=None, scheduled=None,   # since, the
                                    projection_sha256=None, receipt_sha256=None))                     # helper never
        except c.OutputRootGone:                          # recreates it and the committed INVALID decides, OP-8)
            pass
        raise Refusal(f"{where} refused: S1 bundle differs from the trial's AUDIT-ACK bundle after journal rows: "
                      f"INVALID (bundle)")
    if rows:
        _plan_after_rows(tr, rows, root, out, where, now, mailbox)    # A3 Task 14b (O-3): never resumable
    else:
        try:
            plan_tid = c.load_json(out / "plan.json").get("trial_id")
        except (OSError, ValueError, AttributeError):
            plan_tid = None
        if plan_tid != tr.trial_id:                               # before any row: a refusal (F6.2, F6.4)
            _refuse(out, where, f"plan.json trial_id {plan_tid!r} differs from the AUDIT-ACK's {tr.trial_id} (F6.2)",
                    now)
    _recover_local_abort(tr, rows, root, out, where, now, mailbox)    # A3 H1 (Erratum 2 r4 G6.4)
    gv = Gate(root, out, tr, rows, st_, mailbox)
    import s1_seal                                        # A3 Task 11 (F2.3/F2.4): stop.json against the TRIAL-STOP
    s1_seal.stop_check(gv)                                # (the publication gap recovers here), before the F4 table
    import s1_stage                                       # A3 Task 8: the F4 stage-state table (never creates s1_out)
    s1_stage.evaluate(gv, defer_pending=defer_pending)    # A3 Task 6 (N2): the slot paths defer a held stage lock
    import s1_slot                                        # A3 Task 7: the F3 evidence table, after the plan check
    s1_slot.evidence_check(gv)                            # (Deviation 1, Task 8 D4: a foreign root is never judged)
    s1_seal.stop_gap_recover(gv)                          # A3 Task 11 fix round 1 (M4): the F2.3 gap, after F4/F3
    opening_manifest_check(gv)                            # A3 Task 10: E5.5 / F7.3, after the stage and F3 tables
    return gv


def _recover_local_abort(tr: Trial, rows, root: Path, out: Path, where: str, now, mailbox) -> None:
    """A3 H1 (Erratum 2 r4 G6.4, O12 items 2-5, O17, O18): a surviving local abort (s1_out/aborted.json) on an open,
    not-INVALID trial is recorded here, in the common gate, before any stop-gap or stage recovery and any requested
    work - after the identity, ACK chain, journal chain, CLOSED, INVALID, LOST, bundle and root/plan checks, which
    keep their precedence (a foreign root, no trial, a forked chain, CLOSED or a lost s1_out never reach here).
    Only once the trial has journal rows (ruling OP-15: before any row the command-local refusals stay).
    1. A typed read (c.read_abort): absent -> healthy, return; a read/OS/permission error refuses with no row (never
       a local-abort observation, I-4/O18).
    2. Confirm on a re-read: the same typed outcome and the same bytes (sha256); a change or deletion between the
       reads is unconfirmed: refusal, no row, no work (I-1).
    3. The canonical, sanitized observation (G6.2): subtype local-abort, the witness bytes' sha256, trial_id, root,
       recovery_observed_utc, and original_reason / original_observed_utc copied only when present as strings
       (ruling OP-7: observed_utc, else actual) - or the malformation for readable malformed bytes. Nothing else
       from the witness is copied; its stated reason is provenance, never the row's reason.
    4. TRIAL-INVALID (established-violation) through the request-scoped conditional append (recovery=True: ANY
       TRIAL-INVALID on the transaction's re-read rows refuses with no row, G6.5); `now` (the command's clock
       callable) is passed by identity, so the row's `at` is the transaction clock (I-5). Either way the command
       refuses with no work. The witness is never deleted or rewritten (G6.5); restoring files never resumes."""
    if not rows:                                          # ruling OP-15: record only after journal rows
        return
    reads = []
    for _ in range(2):
        try:
            a = c.read_abort(out)
        except OSError as e:
            _refuse(out, where, f"aborted.json unreadable ({type(e).__name__}): not a verified local-abort "
                                f"observation; refused with no row (G6.2, F0.7)", now)
        if a.kind == "absent" and not reads:
            return                                        # healthy: nothing to record
        reads.append(a)
    first, second = reads
    if (first.kind, first.sha256) != (second.kind, second.sha256):
        _refuse(out, where, "aborted.json unconfirmed (changed or deleted between reads): no row, no work (G6.4)",
                now)
    rec = {"subtype": LOCAL_ABORT, "abort_sha256": first.sha256, "trial_id": tr.trial_id, "root": str(root),
           "recovery_observed_utc": (now or c.now_utc)().isoformat()}
    if first.kind == "valid":
        w = first.record
        if isinstance(w.get("reason"), str):
            rec["original_reason"] = w["reason"]
        obs = w.get("observed_utc") if isinstance(w.get("observed_utc"), str) else w.get("actual")
        if isinstance(obs, str):
            rec["original_observed_utc"] = obs
    else:
        rec["malformation"] = first.malformation
    res = invalidate(tr, "established-violation", rec, root=root, mailbox=mailbox, clock=now, recovery=True)
    if res.outcome == "APPEND":
        raise Refusal(f"{where} refused: surviving local abort recorded: INVALID (established-violation), subtype "
                      f"{LOCAL_ABORT}, bound to aborted.json {first.sha256[:12]}: no work (G6.4)")
    raise Refusal(f"{where} refused: {res.reason}: no work (G6.5)")


def _plan_read(p: Path):
    """plan.json's bytes, or None when it is absent (FileNotFoundError); any other OSError propagates (a refusal)."""
    try:
        return Path(p).read_bytes()
    except FileNotFoundError:
        return None


def _plan_problem(blob, trial_id: str, committed) -> tuple:
    """(problem, tid) for one read of plan.json against the trial: problem None = the AUDIT-ACK's plan (its sha256)
    naming this trial; "foreign" = it parses and names ANOTHER trial_id (tid); else "absent" | "unparseable" |
    "without a trial_id" | "changed" (it names this trial but is not the AUDIT-ACK's bytes)."""
    if blob is None:
        return "absent", None
    try:
        obj = json.loads(blob.decode("utf-8"))
    except ValueError:                                    # (UnicodeDecodeError included)
        return "unparseable", None
    tid = obj.get("trial_id") if isinstance(obj, dict) else None
    if not isinstance(tid, str) or not tid:
        return "without a trial_id", None
    if tid != trial_id:
        return "foreign", tid
    return (None if c.sha256_bytes(blob) == committed else "changed"), tid


def _audit_state(rows) -> str:
    """The audit stage's journal state, for the plan INVALID's text (fix round 1, M-1)."""
    import s1_stage
    m = s1_stage.stage_rows(rows, "audit")
    return next((k.upper() for k in ("created", "prepared", "intent") if m[k] is not None), "no row")


def _holds_this_trials_audit(tr: Trial, rows, root: Path, out: Path) -> bool:
    """Fix round 1 (review I-1; ruling "T14b I-1", amending brief item 2): does `root` hold a journal-bound audit
    artifact of THIS trial? True when s1_staging/<trial>/audit/intent.json hashes to the audit STAGE-INTENT row's
    detail (F4.1, OQ-35), or when an audit CREATED member is present in s1_out with its committed sha256 (the
    committed member list is the staging prepared.json verified against the PREPARED row - the only journal-bound
    source of the member hashes, F4.3). Another trial's genuine root has neither (the staging dir is keyed by this
    trial's uuid4, OQ-27). An absent file is "no"; any other OSError propagates (the caller refuses with no row)."""
    import s1_stage
    m = s1_stage.stage_rows(rows, "audit")
    staging = s1_stage.staging_dir(root, tr.trial_id, "audit")
    if m["intent"] is not None:
        blob = _plan_read(staging / "intent.json")
        if blob is not None and c.sha256_bytes(blob) == m["intent"].detail:
            return True
    if m["created"] is not None and m["prepared"] is not None:
        blob = _plan_read(staging / "prepared.json")
        if blob is not None and c.sha256_bytes(blob) == m["prepared"].detail:
            try:
                members = json.loads(blob.decode("utf-8")).get("members")
            except (ValueError, AttributeError):
                members = None
            for rel, sha in (members.items() if isinstance(members, dict) else ()):
                got = _plan_read(out / rel)
                if got is not None and c.sha256_bytes(got) == sha:
                    return True
    return False


def _journal_invalid(tr: Trial, mailbox) -> bool:
    """Whether the trial's journal now holds a TRIAL-INVALID row (re-read). A read failure is not a "yes"."""
    try:
        return j.first(j.read_trial(tr.trial_id, tr.genesis, mailbox), "TRIAL-INVALID") is not None
    except (Refusal, j.JournalError):
        return False


def _plan_after_rows(tr: Trial, rows, root: Path, out: Path, where: str, now, mailbox) -> None:
    """A3 Task 14b (review O-3; ruling "T14 I-1"; fix round 1 rulings "T14b I-1", "T14b I-2"): the plan check once
    the trial has any journal row. The trial is already bound without plan.json - the mailbox's unique open trial
    (F6.3), its AUDIT-ACK trial_id and plan_sha256 (which the audit STAGE-INTENT envelope commits as its bound input,
    F4.1/F4.8) and its journal - so plan.json is judged as the audit stage's bound input, never as the trial's
    identity:
    - it parses and names ANOTHER non-empty trial_id: THIS trial's root with its plan changed (problem "names another
      trial_id") when the root holds a journal-bound audit artifact of this trial (_holds_this_trials_audit);
      otherwise a foreign root - the F6.2 refusal with no row, never judged (F10 Identity: a foreign root never
      invalidates this trial, so no legacy detector runs on it). An OSError reading the decider refuses with no row.
      Residual (F8.1 class): a swapped plan with every artifact of this trial deleted from the root reads as foreign;
    - absent, unparseable, without a trial_id, not the AUDIT-ACK's bytes, or swapped as above: F6.2 says it never
      changes after the AUDIT-ACK and the F4 table makes a missing/changed bound input INVALIDATE. Confirmed on a
      re-read first (Task 7 I1, Task 11 I1): only an absence, or the same bytes, on both reads counts; a re-read that
      differs, or any other OSError, refuses with no row. If s1_out itself is gone by then, it is the total loss
      (F6.6 precedence: INVALID (LOST); review M-3). Then the OQ-19 legacy detector runs without its A2 B3.2
      stray-file refusal (Task 7 concern-2 ruling); a refusal it raises is kept only if the journal now holds a
      TRIAL-INVALID (its persistent verdict decides first, OQ-19 order); any other refusal of it (a legacy
      s1_out/stage.lock, a scan that changed) cannot explain a confirmed plan change - nothing writes plan.json after
      the AUDIT-ACK - so the gate goes on (review I-2). Then TRIAL-INVALID (stage-replaced) for the audit bound input
      plan.json, and the local abort while s1_out exists (F6.6: never recreated). Restoring plan.json never resumes
      the trial (the journal row decides, F1)."""
    p = out / "plan.json"
    committed = tr.audit.fields.get("plan_sha256")
    try:
        first = _plan_read(p)
        problem, tid = _plan_problem(first, tr.trial_id, committed)
        if problem is None:
            return
        second = _plan_read(p) if problem != "foreign" else None
    except OSError as e:
        _refuse(out, where, f"plan.json unreadable ({type(e).__name__}) after journal rows: not a confirmed "
                            f"violation, refused with no row", now)
    if problem == "foreign":
        try:
            here = _holds_this_trials_audit(tr, rows, root, out)
        except OSError as e:
            _refuse(out, where, f"plan.json names trial_id {tid!r}; this trial's audit commitment unreadable "
                                f"({type(e).__name__}): not a confirmed violation, refused with no row", now)
        if not here:
            _refuse(out, where, f"plan.json trial_id {tid!r} differs from the AUDIT-ACK's {tr.trial_id} (F6.2)", now)
        problem = "names another trial_id"
        try:
            second = _plan_read(p)                        # confirm on re-read before any INVALID
        except OSError as e:
            _refuse(out, where, f"plan.json unreadable ({type(e).__name__}) after journal rows: not a confirmed "
                                f"violation, refused with no row", now)
    if second != first:
        _refuse(out, where, f"plan.json {problem} on the first read and different on the re-read: the violation is "
                            f"not confirmed, refused with no row", now)
    if not out.is_dir():                                  # review M-3: F6.6 precedence over the bound-input verdict
        invalidate(tr, "LOST", {"where": where, "missing": "s1_out"}, root=root, mailbox=mailbox, clock=now)
        raise Refusal(f"{where} refused: s1_out is gone under an open trial with journal rows: INVALID (LOST)")
    try:
        _legacy_detectors(out, where, now, mailbox, stray=False)  # OQ-19: its persistent INVALID still wins first
    except Refusal:
        if _journal_invalid(tr, mailbox):
            raise
    state = _audit_state(rows)
    rec = {"where": where, "stage": "audit", "audit_state": state, "bound_input": "plan.json", "problem": problem,
           "expected_plan_sha256": committed, "observed_plan_sha256": None if first is None else c.sha256_bytes(first)}
    invalidate(tr, "stage-replaced", rec, root=root, mailbox=mailbox, clock=now)
    if out.is_dir():                                      # F6.6: the local abort never recreates s1_out
        try:
            c.write_abort(out, dict(rec, reason="stage-replaced", actual=None, close=None, scheduled=None,
                                    projection_sha256=None, receipt_sha256=None))
        except OSError:
            pass
    raise Refusal(f"{where} refused: stage audit: bound input plan.json missing or changed since the AUDIT-ACK "
                  f"({problem}, after journal rows; the audit stage is at {state}; F4.1, F4.8, F6.2): INVALID "
                  f"(stage-replaced)")


def _legacy_detectors(out: Path, where: str, now, mailbox, *, stray: bool = True) -> None:
    """OQ-19: the legacy registration-artifact detector (s1_common.registration_gate: additional detector only, never
    an identity or authorization root), run where the gate refuses for a reason that could otherwise mask an
    established violation: a mailbox outage (B3.4; the TRIAL-INVALID then cannot commit, F8.1 residual, and the local
    aborted.json is written) and a damaged plan.json after journal rows (Task 14b). A confirmed violation raises its
    own refusal (TRIAL-INVALID first, then aborted.json); otherwise the gate's refusal or verdict follows. Only for a
    tree that exists (a total loss is F6.6, and the detector never recreates s1_out). `stray=False` (A3 Task 14b,
    the plan path after rows): the A2 B3.2 "inconsistent pre-registration state" refusal does not end the gate - the
    gate goes on to its own INVALID (Task 7 concern-2 ruling). Every other refusal of the detector is still raised
    from here; the plan path (_plan_after_rows, fix round 1 I-2) then keeps it only when the journal holds a
    TRIAL-INVALID (the detector's persistent verdict) and otherwise goes on to its own stage-replaced INVALID."""
    if Path(out).is_dir():
        try:
            c.registration_gate(Path(out), where, now, mailbox=mailbox, stray_refuses=stray)
        except SystemExit as e:                           # the gate's contract: every refusal is a Refusal, preserved
            c.record_refusal(Path(out), where, e, now)    # in refusals.jsonl (B3.2)
            if isinstance(e, Refusal):
                raise
            raise Refusal(str(e)) from None


def verify_current(gv: Gate, kind: str, ack_id) -> dict:
    """Field-by-field ACK verification for a command (replaces token-line equality): the trial's one `kind` ACK is
    `ack_id`, its artifact fields equal the current artifacts (artifact_fields), its trial_id is the plan's and its
    bundle the bundle on disk; its journal binding holds (verify_ack). Returns the ack record {ack_id, created_utc}."""
    try:
        tid = c.load_json(gv.out / "plan.json").get("trial_id")
    except (OSError, ValueError, AttributeError):
        tid = None
    expected = dict(artifact_fields(kind, gv.out), trial_id=tid, bundle_sha256=c.bundle_sha256())
    return ack_record(verify_ack(gv.trial, gv.rows, kind, ack_id, expected))


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
