"""Addendum 3 rev 5 F0.5 (precedence steps 1-7 and the rev-5 step-4 sub-order 4a-4d), F0.7, F1 state derivation and
OQ-3/OQ-9/OQ-12/OQ-21. Behavioural RED against the permissive Task 1 decide (s1_evidence/a3/t2_red.txt). Synthetic
journal rows only (the F10 'synthetic journal fixtures'); tmp mailboxes; no network, live DB or scheduler."""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import example, given, settings, strategies as st
import s1_common as c
import s1_journal as j
from conftest import s1_mailbox_init

from pathlib import Path

HERE = Path(c.__file__).resolve().parent
UTC = timezone.utc
TRIAL = "3f2b8c1e-5d4a-4b6c-9e7f-0a1b2c3d4e5f"
GEN = "7" * 64
T0 = datetime(2026, 11, 2, 21, 0, tzinfo=UTC)
S, S2, G = "slot/20261102T214500Z", "slot/20261102T214700Z", "stage/audit"
SG = "stage/seal/2026-10-27"                                         # E2.1 r3: a post-START seal stage
E = datetime(2026, 11, 2, 21, 55, tzinfo=UTC)
D = E + timedelta(minutes=30)
US = timedelta(microseconds=1)
H1, H2 = "1" * 64, "2" * 64
AO, AA = "a" * 32, "b" * 32          # worker A: op, actor
BO, BA = "c" * 32, "d" * 32          # foreign op, foreign actor
FA = "e" * 32                        # a finalizer / recovery actor
N1, N2 = "f" * 32, "9" * 32          # fresh ops of rows that open their own op


def row(kind, subject=S, op=AO, actor=AA, detail="absent"):
    return (kind, subject, op, actor, detail)


SI, QU, FL = row("SLOT-INTENT"), row("SLOT-QUALIFIED", detail=H1), row("SLOT-FAILED", detail=H1)
TO, MI = row("SLOT-TIMEOUT", actor=FA), row("SLOT-MISSED", op=N2, actor=FA)
GI, GP, GC = row("STAGE-INTENT", G, detail=H1), row("STAGE-PREPARED", G, detail=H1), row("STAGE-CREATED", G, detail=H1)
ST = row("TRIAL-STOP", "trial", op=N2, actor=FA, detail=H1)
IV = row("TRIAL-INVALID", "reason/bundle", op=N2, actor=FA, detail=H1)


def build(specs):
    rows, prev = [], GEN
    for i, (kind, subject, op, actor, detail) in enumerate(specs, start=1):
        ln = j.format_line(trial_id=TRIAL, seq=i, prev=prev, kind=kind, subject=subject, detail=detail, op=op,
                           actor=actor, at=j.fmt_at(T0 + timedelta(seconds=i)))
        r = j.Row(**j.parse_line(ln), line=ln, mailbox_id=str(i), created=float(i))
        rows.append(r)
        prev = r.sha
    return rows


def rq(kind, subject=S, op=AO, actor=AA, detail=None, r_at=None, inputs=None):
    return j.Request(kind, subject, op, actor, detail=detail, r_at=r_at, inputs=inputs)


def ctx(**kw):
    base = dict(slot_times=lambda s: (E, D), stop_detail=lambda rows: H1, stage_gate=lambda rows, g: None,
                slot_gate=lambda rows, s: None, stop_fence=lambda rows: None,      # revision 2: E2.5 r3 fence
                stage_check=lambda rows, s, i: None)          # (Task 5 fix round 1, M-6: supplied explicitly)
    base.update(kw)
    return j.Context(**base)


def Q(op=AO, actor=AA, r_at=E - US):
    return rq("SLOT-QUALIFIED", op=op, actor=actor, detail=H1, r_at=r_at)

CASES = [
    # id, existing rows, request, now, context overrides, outcome, INVALID reason
    ("4a-q-no-intent", [], Q(), E, {}, "INVALIDATE", "contradictory-completion"),
    ("4a-q-foreign-op", [SI], Q(op=BO), E, {}, "INVALIDATE", "contradictory-completion"),
    ("4a-q-foreign-actor", [SI], Q(actor=BA), E, {}, "INVALIDATE", "contradictory-completion"),
    ("4a-q-foreign-op-on-terminal", [SI, TO], Q(op=BO), D, {}, "INVALIDATE", "contradictory-completion"),
    ("4a-f-no-intent", [], rq("SLOT-FAILED", detail=H1), E, {}, "INVALIDATE", "contradictory-completion"),
    ("4a-f-foreign-op", [SI], rq("SLOT-FAILED", op=BO, detail=H1), E, {}, "INVALIDATE", "contradictory-completion"),
    ("4a-f-foreign-actor", [SI], rq("SLOT-FAILED", actor=BA, detail=H1), E, {}, "INVALIDATE",
     "contradictory-completion"),
    ("4a-t-no-intent", [], rq("SLOT-TIMEOUT", actor=FA), D, {}, "INVALIDATE", "contradictory-finalizer"),
    ("4a-t-foreign-op", [SI], rq("SLOT-TIMEOUT", op=BO, actor=FA), D, {}, "INVALIDATE", "contradictory-finalizer"),
    ("4a-t-foreign-op-on-terminal", [SI, QU], rq("SLOT-TIMEOUT", op=BO, actor=FA), D, {}, "INVALIDATE",
     "contradictory-finalizer"),
    ("4a-p-no-intent", [], rq("STAGE-PREPARED", G, detail=H1), E, {}, "INVALIDATE", "contradictory-stage"),
    ("4a-p-foreign-op", [GI], rq("STAGE-PREPARED", G, op=BO, detail=H1), E, {}, "INVALIDATE", "contradictory-stage"),
    ("4a-p-foreign-actor", [GI], rq("STAGE-PREPARED", G, actor=FA, detail=H1), E, {}, "INVALIDATE",
     "contradictory-stage"),
    ("4a-c-no-prepared", [GI], rq("STAGE-CREATED", G, detail=H1), E, {}, "INVALIDATE", "contradictory-stage"),
    ("4a-c-foreign-op", [GI, GP], rq("STAGE-CREATED", G, op=BO, actor=FA, detail=H1), E, {}, "INVALIDATE",
     "contradictory-stage"),
    ("4b-si-after-intent", [SI], rq("SLOT-INTENT", op=N1, actor=BA), E - US, {}, "INVALIDATE", "repeat-attempt"),
    ("4b-si-after-terminal", [SI, QU], rq("SLOT-INTENT", op=N1, actor=BA), E - US, {}, "INVALIDATE",
     "repeat-attempt"),
    ("4b-si-stopped-terminal", [SI, QU, ST], rq("SLOT-INTENT", op=N1, actor=BA), E - US, {}, "INVALIDATE",
     "repeat-attempt"),
    ("4b-gi-repeat", [GI], rq("STAGE-INTENT", G, op=N1, actor=BA, detail=H2), E, {}, "INVALIDATE", "repeat-stage"),
    # row 299 (OQ-3 ruling): a reused op never hides a repeated opening subject
    ("4b-si-repeat-with-reused-op", [SI], rq("SLOT-INTENT", op=AO, actor=BA), E - US, {}, "INVALIDATE",
     "repeat-attempt"),
    ("4b-gi-repeat-with-reused-op", [GI], rq("STAGE-INTENT", G, op=AO, actor=BA, detail=H2), E, {}, "INVALIDATE",
     "repeat-stage"),
    ("4c-q-after-timeout", [SI, TO], Q(), D, {}, "LOST-RACE", None),
    # E1.3 r3: after a committed TIMEOUT, a late R (R >= D) is LOST-RACE at 4c, before step 6 (row 257)
    ("4c-q-late-r-after-timeout", [SI, TO], Q(r_at=D), D + US, {}, "LOST-RACE", None),
    ("4c-f-after-timeout", [SI, TO], rq("SLOT-FAILED", detail=H1), D + US, {}, "LOST-RACE", None),
    ("4c-f-after-qualified", [SI, QU], rq("SLOT-FAILED", detail=H2), E, {}, "LOST-RACE", None),
    ("4c-t-after-qualified", [SI, QU], rq("SLOT-TIMEOUT", actor=FA), D, {}, "LOST-RACE", None),
    ("4c-m-after-qualified", [SI, QU], rq("SLOT-MISSED", op=N1, actor=FA), E, {}, "LOST-RACE", None),
    ("4c-m-after-failed", [SI, FL], rq("SLOT-MISSED", op=N1, actor=FA), E, {}, "LOST-RACE", None),
    ("4c-m-after-timeout", [SI, TO], rq("SLOT-MISSED", op=N1, actor=FA), D, {}, "LOST-RACE", None),
    ("4c-m-after-missed", [MI], rq("SLOT-MISSED", op=N1, actor=FA), E, {}, "LOST-RACE", None),
    ("4c-m-qualified-before-e", [SI, QU], rq("SLOT-MISSED", op=N1, actor=FA), E - US, {}, "LOST-RACE", None),
    ("4c-p-same", [GI, GP], rq("STAGE-PREPARED", G, detail=H1), E, {}, "LOST-RACE", None),
    ("4c-p-different", [GI, GP], rq("STAGE-PREPARED", G, detail=H2), E, {}, "INVALIDATE", "contradictory-stage"),
    ("4c-c-differs-from-prepared", [GI, GP], rq("STAGE-CREATED", G, detail=H2), E, {}, "INVALIDATE",
     "contradictory-stage"),
    ("4c-c-created-same", [GI, GP, GC], rq("STAGE-CREATED", G, actor=FA, detail=H1), E, {}, "LOST-RACE", None),
    ("4c-stop-same", [ST], rq("TRIAL-STOP", "trial", op=N1, actor=FA, detail=H1), E, {}, "LOST-RACE", None),
    ("4c-stop-different", [ST], rq("TRIAL-STOP", "trial", op=N1, actor=FA, detail=H2), E, {}, "INVALIDATE",
     "stop-conflict"),
    ("4d-m-in-flight", [SI], rq("SLOT-MISSED", op=N1, actor=FA), E, {}, "REFUSE", None),
    ("5-si-stopped", [ST], rq("SLOT-INTENT", op=N1), E - US, {}, "LOST-RACE", None),
    ("5-si-gate-refuses", [], rq("SLOT-INTENT", op=N1), E - US, {"slot_gate": lambda rows, s: "no PREREG-ACK"},
     "REFUSE", None),
    ("5-gi-forbidden", [], rq("STAGE-INTENT", G, op=N1, detail=H1), E, {"stage_gate": lambda rows, g: "no pred"},
     "REFUSE", None),
    # E2.2/E2.5 r3 (row 334): seal-stage selection at 4a, the STOP fence at step 5
    ("4a-seal-intent-wrong-selection", [], rq("STAGE-INTENT", SG, op=N1, detail=H1, inputs={"qualified_line": H2}),
     E, {"stage_check": lambda rows, s, inputs: j.Decision("INVALIDATE", "contradictory-stage")},
     "INVALIDATE", "contradictory-stage"),
    # Task 2 Deviation D2 (E2.2 r3: the selection check sits at 4a, so it precedes the 4b repeat-stage check)
    ("4a-seal-intent-wrong-selection-on-repeat", [row("STAGE-INTENT", SG, detail=H1)],
     rq("STAGE-INTENT", SG, op=N1, actor=BA, detail=H2, inputs={"qualified_line": H2}), E,
     {"stage_check": lambda rows, s, inputs: j.Decision("INVALIDATE", "contradictory-stage")},
     "INVALIDATE", "contradictory-stage"),
    ("5-seal-intent-not-determined", [], rq("STAGE-INTENT", SG, op=N1, detail=H1), E,
     {"stage_gate": lambda rows, g: "close not determined (E2.2)"}, "REFUSE", None),
    ("5-stop-fence-unsealed-close", [], rq("TRIAL-STOP", "trial", op=N1, actor=FA, detail=H1), E,
     {"stop_fence": lambda rows: "determined close 2026-10-27 has no CREATED seal stage (E2.5)"}, "REFUSE", None),
    ("5-stop-fence-ok", [], rq("TRIAL-STOP", "trial", op=N1, actor=FA, detail=H1), E,
     {"stop_fence": lambda rows: None}, "APPEND", None),
    ("5-stop-rule-not-met", [], rq("TRIAL-STOP", "trial", op=N1, actor=FA, detail=H1), E,
     {"stop_detail": lambda rows: None}, "REFUSE", None),
    ("5-stop-differs-from-recomputed", [], rq("TRIAL-STOP", "trial", op=N1, actor=FA, detail=H2), E, {}, "REFUSE",
     None),
    ("5-q-intent-before-stop", [SI, ST], Q(), E, {}, "APPEND", None),
    ("5-q-intent-after-stop", [ST, SI], Q(), E, {}, "REFUSE", None),
    ("6-si-at-e", [], rq("SLOT-INTENT", op=N1), E, {}, "REFUSE", None),
    ("6-si-before-e", [], rq("SLOT-INTENT", op=N1), E - US, {}, "APPEND", None),
    ("6-q-r-at-d", [SI], Q(r_at=D), D, {}, "REFUSE", None),
    ("6-q-r-d-plus-1us", [SI], Q(r_at=D + US), D + US, {}, "REFUSE", None),
    ("6-q-r-d-minus-1us", [SI], Q(r_at=D - US), D, {}, "APPEND", None),
    ("6-t-before-d", [SI], rq("SLOT-TIMEOUT", actor=FA), D - US, {}, "REFUSE", None),
    ("6-m-before-e", [], rq("SLOT-MISSED", op=N1, actor=FA), E - US, {}, "REFUSE", None),
    ("6-m-at-e", [], rq("SLOT-MISSED", op=N1, actor=FA), E, {}, "APPEND", None),
    ("7-t-finalizer-actor", [SI], rq("SLOT-TIMEOUT", actor=FA), D, {}, "APPEND", None),
    ("7-gi-permitted", [], rq("STAGE-INTENT", G, op=N1, detail=H1), E, {}, "APPEND", None),
    ("7-p", [GI], rq("STAGE-PREPARED", G, detail=H1), E, {}, "APPEND", None),
    ("7-c-opening-actor", [GI, GP], rq("STAGE-CREATED", G, detail=H1), E, {}, "APPEND", None),
    ("7-c-recovery-actor", [GI, GP], rq("STAGE-CREATED", G, actor=FA, detail=H1), E, {}, "APPEND", None),
    ("7-trial-invalid-active", [], rq("TRIAL-INVALID", "reason/bundle", op=N1, actor=FA, detail=H1), E, {}, "APPEND",
     None),
    ("7-trial-invalid-stopped", [ST], rq("TRIAL-INVALID", "reason/bundle", op=N1, actor=FA, detail=H1), E, {},
     "APPEND", None),
    ("7-stop", [], rq("TRIAL-STOP", "trial", op=N1, actor=FA, detail=H1), E, {}, "APPEND", None),
]


@pytest.mark.parametrize("cid,specs,req,now,kw,outcome,reason", CASES, ids=[x[0] for x in CASES])
def test_precedence_table(cid, specs, req, now, kw, outcome, reason):
    dec = j.decide(build(specs), req, ctx(**kw), now)
    assert dec.outcome == outcome, (cid, dec)
    if outcome == "INVALIDATE":
        assert dec.reason == reason


ONE = {"SLOT-INTENT": rq("SLOT-INTENT", S2, op=N1), "SLOT-QUALIFIED": Q(), "SLOT-FAILED": rq("SLOT-FAILED", detail=H1),
       "SLOT-TIMEOUT": rq("SLOT-TIMEOUT", actor=FA), "SLOT-MISSED": rq("SLOT-MISSED", S2, op=N1, actor=FA),
       "STAGE-INTENT": rq("STAGE-INTENT", G, op=N1, detail=H1), "STAGE-PREPARED": rq("STAGE-PREPARED", G, detail=H1),
       "STAGE-CREATED": rq("STAGE-CREATED", G, detail=H1),
       "TRIAL-STOP": rq("TRIAL-STOP", "trial", op=N1, actor=FA, detail=H1),
       "TRIAL-INVALID": rq("TRIAL-INVALID", "reason/LOST", op=N1, actor=FA, detail=H1)}


@pytest.mark.parametrize("kind", j.KINDS)
def test_closed_refuses_every_kind_including_trial_invalid(kind):
    assert j.decide(build([SI, GI, GP]), ONE[kind], ctx(closed=True), D).outcome == "REFUSE"


@pytest.mark.parametrize("kind", j.KINDS)
def test_invalid_appends_trial_invalid_and_lost_races_every_other_kind(kind):
    want = "APPEND" if kind == "TRIAL-INVALID" else "LOST-RACE"
    assert j.decide(build([SI, GI, GP, IV]), ONE[kind], ctx(), D).outcome == want


def test_trial_state_derivation():
    assert j.trial_state(build([SI])) == "ACTIVE"
    assert j.trial_state(build([SI, ST])) == "STOPPED"
    assert j.trial_state(build([SI, ST, IV])) == "INVALID"
    assert j.trial_state(build([IV])) == "INVALID"


def test_reused_op_on_an_opening_row_is_refused():
    """OQ-3."""
    assert j.decide(build([SI]), rq("SLOT-MISSED", S2, op=AO, actor=FA), ctx(), E).outcome == "REFUSE"


# ---------------------------------------------------------------- through the real transaction
def ctxf(**kw):
    return lambda rows, con: ctx(**kw)


def kinds(mb):
    return [r.kind for r in j.read_trial(TRIAL, GEN, mb)]


def test_append_decides_on_the_state_read_inside_the_transaction(tmp_path):
    mb = s1_mailbox_init(tmp_path)
    j.append(TRIAL, GEN, rq("SLOT-INTENT"), ctxf(), mailbox=mb, clock=lambda: E - timedelta(minutes=5))
    stale = j.read_trial(TRIAL, GEN, mb)
    assert j.decide(stale, Q(r_at=D - US), ctx(), D).outcome == "APPEND"        # what the worker saw earlier
    j.append(TRIAL, GEN, rq("SLOT-TIMEOUT", actor=FA), ctxf(), mailbox=mb, clock=lambda: D)     # T commits first
    res = j.append(TRIAL, GEN, Q(r_at=D - US), ctxf(), mailbox=mb, clock=lambda: D + US)
    assert (res.outcome, res.row) == ("LOST-RACE", None) and kinds(mb) == ["SLOT-INTENT", "SLOT-TIMEOUT"]


def test_invalidate_appends_trial_invalid_instead_in_the_same_transaction(tmp_path):
    mb = s1_mailbox_init(tmp_path)
    j.append(TRIAL, GEN, rq("SLOT-INTENT"), ctxf(), mailbox=mb, clock=lambda: E - timedelta(minutes=5))
    res = j.append(TRIAL, GEN, Q(op=BO), ctxf(), mailbox=mb, clock=lambda: E - US)
    assert (res.outcome, res.reason) == ("INVALIDATE", "contradictory-completion")
    rows = j.read_trial(TRIAL, GEN, mb)
    assert [r.kind for r in rows] == ["SLOT-INTENT", "TRIAL-INVALID"] and res.row == rows[1]
    assert (rows[1].subject, rows[1].op, rows[1].actor) == ("reason/contradictory-completion", BO, AA)
    assert rows[1].detail == j.detail_of({"reason": "contradictory-completion", "requested": {
        "kind": "SLOT-QUALIFIED", "subject": S, "op": BO, "actor": AA, "detail": H1}})


def _put_lines(mb, specs, *, drop=None, dup=None):
    rows = build(specs)
    con = sqlite3.connect(mb)
    for r in rows:
        if r.seq != drop:
            con.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,NULL)", (r.mailbox_id, "s1", "codex",
                                                                          "experiments-s1-journal", r.line, r.created))
    if dup is not None:
        con.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,NULL)", ("dup", "s1", "codex", "experiments-s1-journal",
                                                                      dup, 99.0))
    con.commit()
    con.close()


@pytest.mark.parametrize("damage", ["gap", "fork", "dup", "format"])
def test_chain_integrity_refuses_with_no_row(tmp_path, damage):
    mb = s1_mailbox_init(tmp_path)
    specs = [SI, row("SLOT-INTENT", S2, op=N1)]
    if damage == "gap":
        _put_lines(mb, specs + [row("SLOT-INTENT", "slot/20261102T214900Z", op=N2)], drop=2)
    elif damage == "fork":
        other = build([SI, row("SLOT-INTENT", "slot/20261102T215100Z", op="8" * 32)])[1].line
        _put_lines(mb, specs, dup=other)
    elif damage == "dup":
        _put_lines(mb, specs, dup=build(specs)[1].line)                      # a byte-identical second seq 2
    else:
        _put_lines(mb, specs, dup="S1-JOURNAL garbage")
    with sqlite3.connect(mb) as con:
        before = con.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    with pytest.raises(j.ChainError):
        j.append(TRIAL, GEN, rq("SLOT-INTENT", "slot/20261102T215300Z", op="6" * 32), ctxf(), mailbox=mb,
                 clock=lambda: E - US)
    with sqlite3.connect(mb) as con:
        assert con.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == before


MALFORMED = {
    "unknown-kind": rq("SLOT-RETRY"),
    "subject-for-kind": rq("STAGE-INTENT", S, op=N1, detail=H1),
    "detail-on-intent": rq("SLOT-INTENT", detail=H1),
    "absent-on-qualified": rq("SLOT-QUALIFIED", r_at=E),
    "op-not-hex": rq("SLOT-INTENT", op="Z" * 32),
    "qualified-without-r": rq("SLOT-QUALIFIED", detail=H1),
    "naive-r": rq("SLOT-QUALIFIED", detail=H1, r_at=E.replace(tzinfo=None)),
    "r-on-failed": rq("SLOT-FAILED", detail=H1, r_at=E),
    "unknown-reason": rq("TRIAL-INVALID", "reason/whatever", op=N1, detail=H1),
}


@pytest.mark.parametrize("case", sorted(MALFORMED))
def test_malformed_requests_are_refused_with_no_row(tmp_path, case):
    mb = s1_mailbox_init(tmp_path)
    with pytest.raises(j.RequestError):
        j.append(TRIAL, GEN, MALFORMED[case], ctxf(), mailbox=mb, clock=lambda: E - US)
    assert kinds(mb) == []


def test_an_exception_inside_the_transaction_appends_no_row(tmp_path):
    """F0.7 at the primitive: any exception (here from the caller's context) rolls back."""
    mb = s1_mailbox_init(tmp_path)

    def boom(rows, con):
        raise RuntimeError("unexpected")
    with pytest.raises(RuntimeError):
        j.append(TRIAL, GEN, rq("SLOT-INTENT"), boom, mailbox=mb, clock=lambda: E - US)
    assert kinds(mb) == []


# ---------------------------------------------------------------- step-4 sub-order disjointness (Hypothesis)
HISTORIES = [[], [SI], [SI, QU], [SI, FL], [SI, TO], [MI], [SI, row("SLOT-INTENT", op=BO)]]


def oracle(specs, req, now):
    """An independent transcription of the F0.5 table for slot requests: every condition of a sub-step is evaluated;
    at most one may hold (disjointness); the first sub-step that has one decides."""
    rows = [r for r in build(specs) if r.subject == req.subject]
    intent = next((r for r in rows if r.kind == "SLOT-INTENT"), None)
    term = next((r for r in rows if r.kind in j.TERMINAL), None)
    k = req.kind
    sub = {
        "4a": [(k in ("SLOT-QUALIFIED", "SLOT-FAILED") and (intent is None or req.op != intent.op
                                                             or req.actor != intent.actor),
                "INVALIDATE"),
               (k == "SLOT-TIMEOUT" and (intent is None or req.op != intent.op), "INVALIDATE")],
        "4b": [(k == "SLOT-INTENT" and bool(rows), "INVALIDATE")],
        "4c": [(k in ("SLOT-QUALIFIED", "SLOT-FAILED", "SLOT-TIMEOUT", "SLOT-MISSED") and term is not None,
                "LOST-RACE")],
        "4d": [(k == "SLOT-MISSED" and intent is not None and term is None, "REFUSE")],
        "6": [(k == "SLOT-INTENT" and now >= E, "REFUSE"), (k == "SLOT-QUALIFIED" and req.r_at >= D, "REFUSE"),
              (k == "SLOT-TIMEOUT" and now < D, "REFUSE"), (k == "SLOT-MISSED" and now < E, "REFUSE")],
    }
    for step in ("4a", "4b", "4c", "4d", "6"):
        hits = [out for cond, out in sub[step] if cond]
        assert len(hits) <= 1, (step, hits)
        if hits:
            return hits[0]
    return "APPEND"


# Scope (f045bd31): slot-subject histories × slot kinds × 5 instants. Stage and trial lifecycles are covered by the
# explicit tables, not by this property. Revision 2 policy (A3-PR1-3; the pinned Hypothesis rejects derandomize=True
# with an explicit database): derandomize=True and database=None, so every run explores the same deterministic
# sequence; reproducibility comes from derandomization, NOT database replay. Every minimized counterexample found
# during development is kept as an explicit @example below (the retained set is listed in a3/t2_examples.md). The
# two seed examples are the E1.3 r3 boundary: a late R after a committed TIMEOUT, and a late R with no terminal.
@settings(max_examples=400, deadline=None, derandomize=True, database=None)
@example(hist=[SI, TO], kind="SLOT-QUALIFIED", who=(AO, AA), now=D + US)          # 4c LOST-RACE (E1.3 r3)
@example(hist=[SI], kind="SLOT-QUALIFIED", who=(AO, AA), now=D)                   # step 6 REFUSE (no terminal)
@given(hist=st.sampled_from(HISTORIES), kind=st.sampled_from(j.SLOT_KINDS),
       who=st.sampled_from([(AO, AA), (BO, AA), (AO, BA), (BO, BA)]),
       now=st.sampled_from([E - US, E, D - US, D, D + US]))
def test_substep_conditions_are_disjoint_and_decide_matches_the_oracle(hist, kind, who, now):
    op, actor = who
    if kind in ("SLOT-INTENT", "SLOT-MISSED"):
        op = N1                                                     # rows that open their own op (OQ-3)
    req = rq(kind, op=op, actor=FA if kind in ("SLOT-TIMEOUT", "SLOT-MISSED") else actor,
             detail=H1 if kind in ("SLOT-QUALIFIED", "SLOT-FAILED") else None,
             r_at=now if kind == "SLOT-QUALIFIED" else None)
    assert j.decide(build(hist), req, ctx(), now).outcome == oracle(hist, req, now)
