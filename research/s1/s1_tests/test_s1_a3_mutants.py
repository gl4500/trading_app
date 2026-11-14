"""A3 H5a targeted semantic mutants with named kill evidence (A10.2): Erratum 2 Clarification 2 row 512
(`eligibility`), Clarification 3 row 531 (`seal_once`) and Clarification 4 row 549 (`intent_lower_bound`). The docs
name the nodes `test_s1_a3_mutants.py targeted (H5 list)::eligibility[...]` etc.; pytest collects only `test_*`
functions, so the nodes are test_eligibility[...], test_seal_once[...] and test_intent_lower_bound[...] (logged as a
deviation, R-G; the parameter ids are the docs' exactly).

Each mutant is applied to a FULL SCRATCH COPY of research/s1 (conftest puts its own research/s1 first on sys.path, so a
mutant can never be run by editing the sources in place): an exact single-occurrence replacement, then the named killing
test runs in a child pytest against the copy (its own basetemp, no bytecode), then the copied file is restored
byte-for-byte (sha256 asserted). A mutant is KILLED when its named killing test fails. A baseline run per family proves
every killing test passes on the unmutated copy first. Slow (one child pytest per mutant)."""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent                      # research/s1 of the tree under test
T = "research/s1/s1_tests/"


def node(f, name, param):
    return f"{T}{f}::{name}[{param}]"


EL, SO, LB, ST = ("test_s1_a3_eligibility.py", "test_s1_a3_seal_once.py", "test_s1_a3_intent_lower_bound.py",
                  "test_s1_a3_stop.py")

C2_CHECK = '''        if not pre and z.close_of(day["date"], cal) > deadline:
            return C2_REASON.format(close=day["date"])
'''
C3_CHECK = '''        q = None if pre else _earlier_qualified(rows, s, day, cal)
        if q is not None:
            return C3_REASON.format(close=day["date"], q=q.isoformat())
'''
GATE_LINE = '''    gv = s1_trial.gate(root, "checkpoint", mailbox=mailbox, now=now, defer_pending=True)   # A3 F0.6 (N2)
'''
BEFORE_GATE = '''    _pr = c.load_json(Path(root) / "s1_out" / "prereg.json")                      # MUTANT: before the gate
    _tr = s1_trial.open_trial(mailbox or c.MAILBOX)
    _why = s1_slot.post_start_gate(_tr, start=c.aware(_pr["start"]), cal=_pr["calendar"])(
        s1_slot.j.read_trial(_tr.trial_id, _tr.genesis, mailbox or c.MAILBOX), s1_slot.j.slot_subject(scheduled))
    if _why:
        raise SystemExit(_why)
''' + GATE_LINE
C4_CHECK = '''    if k == "SLOT-INTENT" and now < slot_instant(req.subject) - C4_TOLERANCE:      # A3 H5a: Clarification 4 C4.1
        return Decision("REFUSE", C4_REASON.format(slot=slot_instant(req.subject).isoformat()))
'''
EARLY_INSERT = '''            row = _insert(con, trial_id, gen, rows, req, dec, now) if dec.outcome in ("APPEND", "INVALIDATE") else None
'''

ELIGIBILITY = {
    "predicate-removed": ("s1_slot.py", [(C2_CHECK, "")], node(EL, "test_post_deadline_close_refused",
                                                              "d130-first-slot")),
    "ge-instead-of-gt": ("s1_slot.py", [('z.close_of(day["date"], cal) > deadline', 'z.close_of(day["date"], cal) >= '
                                         'deadline')],
                         node(EL, "test_close_deadline_boundary", "close-equals-deadline-not-refused")),
    "local-date-instead-of-instant": ("s1_slot.py", [('z.close_of(day["date"], cal) > deadline',
                                                      'day["date"] > deadline.astimezone(c.NY).date().isoformat()')],
                                      node(EL, "test_post_deadline_close_refused", "d130-first-slot")),
    "unconditional-membership-incl-pre-start": ("s1_slot.py", [(
        'if not pre and z.close_of(day["date"], cal) > deadline:',
        'if day["date"] not in {d_["date"] for d_ in z.eligible_sessions(start, cal)}:')],
        node(EL, "test_scheduled_mode_pre_start_session_unchanged", "scheduled-opening-close-slot-no-new-refusal")),
    "wallclock-instead-of-close-identity": ("s1_slot.py", [('if not pre and z.close_of(day["date"], cal) > deadline:',
                                                            'if not pre and c.now_utc() > deadline:')],
                                            node(EL, "test_eligible_close_window_past_deadline_stays_under_e_w",
                                                 "slot-before-e-after-deadline-proceeds")),
    "checked-before-integrity-gate": ("s1_checkpoint.py", [(GATE_LINE, BEFORE_GATE)],
                                      node(EL, "test_precedence_preserved", "integrity-violation")),
    "applied-to-opening-gate": ("s1_slot.py", [(
        '''        if j.first(j.subject_rows(rows, "stage/audit"), "STAGE-CREATED") is None:''',
        '''        return C2_REASON.format(close="the opening close")         # MUTANT: membership applied here
        if j.first(j.subject_rows(rows, "stage/audit"), "STAGE-CREATED") is None:''')],
        node(EL, "test_opening_mode_path_unchanged", "opening-mode-captures-and-seals")),
    "route-predicate-ge-w-l": ("s1_checkpoint.py", [("    if scheduled == _w_last(cal, start):",
                                                     "    if scheduled >= _w_last(cal, start):")],
                               node(EL, "test_route_predicate_unchanged", "later-registered-slot-not-routed")),
}

SEAL_ONCE = {
    "predicate-removed": ("s1_slot.py", [(C3_CHECK, "")], node(SO, "test_earlier_qualified_not_determined_refuses_later",
                                                              "earlier-slot-pending")),
    "any-qualified-blanket": ("s1_slot.py", [("        if not close < q < s:\n", "        if not close < q:\n")],
                              node(SO, "test_earlier_slot_still_attemptable", "earlier-attempt-allowed")),
    "determined-gate-instead": ("s1_slot.py", [(
        "        q = None if pre else _earlier_qualified(rows, s, day, cal)\n",
        "        q = None if pre or first_qualified(rows, day, cal) is None else "
        "slot_of(first_qualified(rows, day, cal).subject)\n")],
        node(SO, "test_earlier_qualified_not_determined_refuses_later", "earlier-slot-pending")),
    "commit-order-instead-of-scheduled": ("s1_slot.py", [(
        "        if not close < q < s:\n            continue\n        if day_for(q, cal)[\"date\"] != day[\"date\"]:"
        "          # an unknown mapping raises SystemExit (fail closed)\n            continue\n        if best is None "
        "or q < best:\n            best = q\n    return best",
        "        if not close < q:\n            continue\n        if day_for(q, cal)[\"date\"] != day[\"date\"]:\n"
        "            continue\n        if best is None:\n            best = q              # MUTANT: the first-COMMITTED "
        "QUALIFIED of the close\n    return best if best is not None and best < s else None")],
        node(SO, "test_predicate_mapping", "registered-instant-not-commit-order")),
    "other-close-qualified-counts": ("s1_slot.py", [(
        "        if not close < q < s:\n            continue\n        if day_for(q, cal)[\"date\"] != day[\"date\"]:"
        "          # an unknown mapping raises SystemExit (fail closed)\n            continue\n",
        "        if not q < s:\n            continue\n")],
        node(SO, "test_predicate_mapping", "other-close-qualified-ignored")),
    "pre-read-instead-of-transaction-rows": ("s1_checkpoint.py", [(
        "slot_gate=s1_slot.post_start_gate(gv.trial, start=start, cal=cal),",
        "slot_gate=(lambda _g: lambda rows_, sub_: _g(gv.rows, sub_))(s1_slot.post_start_gate(gv.trial, "
        "start=start, cal=cal)),")],
        node(SO, "test_transaction_barrier_around_q_commit", "intent-after-q-commit-refused")),
    "refuses-completions-too": ("s1_journal.py", [(
        '''    if k in ("SLOT-QUALIFIED", "SLOT-FAILED") and state == "STOPPED":''',
        '''    if k in ("SLOT-QUALIFIED", "SLOT-FAILED") and ctx.slot_gate is not None and \\
            ctx.slot_gate(rows, req.subject):                                     # MUTANT
        return Decision("REFUSE", ctx.slot_gate(rows, req.subject))
    if k in ("SLOT-QUALIFIED", "SLOT-FAILED") and state == "STOPPED":''')],
        node(SO, "test_preclaimed_later_completions", "qualified-r-before-d")),
    "applied-to-pre-start-session": ("s1_slot.py", [(
        "        q = None if pre else _earlier_qualified(rows, s, day, cal)\n",
        "        q = _earlier_qualified(rows, s, day, cal)\n")],
        node(SO, "test_pre_start_paths_unchanged", "scheduled-opening-close-slot-unchanged")),
    "c2-order-swapped": ("s1_slot.py", [(C2_CHECK + C3_CHECK, C3_CHECK + C2_CHECK)],
                         node(SO, "test_precedence_preserved", "c2-post-deadline-reason-first")),
    "checked-before-integrity-gate": ("s1_checkpoint.py", [(GATE_LINE, BEFORE_GATE)],
                                      node(SO, "test_precedence_preserved", "integrity-violation")),
    "unknown-mapping-treated-as-no-q": ("s1_slot.py", [(
        "        if day_for(q, cal)[\"date\"] != day[\"date\"]:          # an unknown mapping raises SystemExit "
        "(fail closed)\n            continue\n",
        "        try:\n            if day_for(q, cal)[\"date\"] != day[\"date\"]:\n                continue\n"
        "        except SystemExit:\n            continue                                    # MUTANT\n")],
        node(SO, "test_predicate_mapping", "unknown-mapping-fails-closed")),
}

INTENT_LOWER_BOUND = {
    "lower-bound-removed": ("s1_journal.py", [(C4_CHECK, "")],
                            node(LB, "test_permission_boundary", "sample-s-minus-1us-refused-no-row")),
    "tolerance-nonzero": ("s1_journal.py", [("C4_TOLERANCE = timedelta(0)", "C4_TOLERANCE = timedelta(seconds=1)")],
                          node(LB, "test_permission_boundary", "sample-s-minus-1us-refused-no-row")),
    "gt-instead-of-ge": ("s1_journal.py", [("now < slot_instant(req.subject) - C4_TOLERANCE",
                                            "now <= slot_instant(req.subject) - C4_TOLERANCE")],
                         node(LB, "test_permission_boundary", "sample-equals-s-appends")),
    "commit-clock-instead-of-sample": ("s1_journal.py", [(EARLY_INSERT, EARLY_INSERT + '''            if decide(rows, req, ctx, clock()).outcome != dec.outcome:     # MUTANT: the commit clock decides
                raise Outage("the commit clock disagrees: no row")
''')], node(LB, "test_sample_before_e_commit_after_e", "sample-before-e-commit-after-e-appends")),
    "journal-row-on-refusal": ("s1_journal.py", [(
        'if dec.outcome in ("APPEND", "INVALIDATE") else None',
        'if dec.outcome in ("APPEND", "INVALIDATE") or "(Clarification 4)" in dec.reason else None')],
        node(LB, "test_early_refusal_diagnostics", "no-journal-row")),
    "root-recreated-by-diagnostic": ("s1_slot.py", [(
        '''        if not Path(out).is_dir():
            raise FileNotFoundError(f"{Path(out).name} is absent")
''', '''        Path(out).mkdir(parents=True, exist_ok=True)                    # MUTANT
''')], node(LB, "test_early_refusal_diagnostics", "missing-root-not-recreated")),
    "mode-restricted-to-post-start": ("s1_journal.py", [(
        'if k == "SLOT-INTENT" and now < slot_instant(req.subject) - C4_TOLERANCE:',
        'if k == "SLOT-INTENT" and getattr(ctx.slot_gate, "__qualname__", "").startswith("post_start_gate") and '
        'now < slot_instant(req.subject) - C4_TOLERANCE:')],
        node(LB, "test_scope_and_precedence", "opening-mode-early-refused")),
    "step6-before-step5": ("s1_journal.py", [(C4_CHECK, ""), (
        '''    if k == "SLOT-INTENT":
        if state == "STOPPED":''', '''    if k == "SLOT-INTENT":
        if now < slot_instant(req.subject) - C4_TOLERANCE:                        # MUTANT: before step 5
            return Decision("REFUSE", C4_REASON.format(slot=slot_instant(req.subject).isoformat()))
        if state == "STOPPED":''')], node(LB, "test_scope_and_precedence", "slot-gate-reasons-first")),
    "route-opens-intent": ("s1_checkpoint.py", [(
        '''registration, slot and local-abort refusal has already propagated (run_checkpoint, G2.1(1))."""
''', '''registration, slot and local-abort refusal has already propagated (run_checkpoint, G2.1(1))."""
    import s1_journal as j_                                                   # MUTANT: the route opens an INTENT
    from datetime import timedelta as td_
    j_.append(gv.trial.trial_id, gv.trial.genesis, j_.Request("SLOT-INTENT", j_.slot_subject(scheduled),
              j_.new_nonce(), j_.new_nonce()), lambda rows_, con_: j_.Context(
              slot_times=lambda s_: (scheduled + td_(days=1), scheduled + td_(days=1)),
              slot_gate=lambda r_, s_: None), mailbox=mailbox, clock=now)
''')], node(LB, "test_w_claim_interval_empty", "exact-w-l-route-unaffected-any-clock")),
}

FAMILIES = {"eligibility": ELIGIBILITY, "seal_once": SEAL_ONCE, "intent_lower_bound": INTENT_LOWER_BOUND}


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@pytest.fixture(scope="module")
def scratch(tmp_path_factory):
    """A full scratch copy of research/s1 (no __pycache__) under a fresh root: <scratch>/research/s1."""
    root = tmp_path_factory.mktemp("h5a_mutants")
    shutil.copytree(SRC, root / "research" / "s1", ignore=shutil.ignore_patterns("__pycache__"))
    return root


def _pytest(scratch, nodes, tag):
    env = dict(os.environ, PYTHONPATH=f"{scratch / 'research' / 's1'};{scratch / 'research' / 's1' / 's1_tests'}",
               PYTHONDONTWRITEBYTECODE="1")
    cmd = [sys.executable, "-m", "pytest", "-p", "conftest", "-p", "no:cacheprovider", *nodes, "-q", "--tb=line",
           f"--basetemp={scratch / ('bt_' + tag)}"]
    return subprocess.run(cmd, cwd=scratch, env=env, capture_output=True, text=True, timeout=3600)


def _mutate_and_run(scratch, family, mid):
    rel, edits, killer = FAMILIES[family][mid]
    p = scratch / "research" / "s1" / rel
    orig = p.read_bytes()
    text = orig.decode("utf-8")
    nl = "\r\n" if "\r\n" in text else "\n"                              # the file's own line ending
    for old, new in edits:
        old, new = old.replace("\n", nl), new.replace("\n", nl)
        assert text.count(old) == 1, f"{family}/{mid}: anchor occurs {text.count(old)} times in {rel}: {old!r}"
        text = text.replace(old, new)
    p.write_bytes(text.encode("utf-8"))
    try:
        res = _pytest(scratch, [killer], f"{family}_{mid}")
    finally:
        p.write_bytes(orig)
    assert _sha(p.read_bytes()) == _sha(orig)
    out = res.stdout + res.stderr
    lines = [x for x in out.splitlines() if x.startswith(("FAILED", "C:\\", "ERROR")) or " failed" in x
             or " passed" in x]
    print(f"\n== {family}[{mid}] [{rel}] killer {killer} -> rc={res.returncode}\n   " + "\n   ".join(lines[-6:]))
    return res, out


@pytest.mark.parametrize("family", list(FAMILIES))
def test_baseline_killers_pass(scratch, family):
    """The unmutated scratch copy: every named killing test of the family passes (so a kill is the mutant's)."""
    nodes = sorted({k for _, _, k in FAMILIES[family].values()})
    res = _pytest(scratch, nodes, f"baseline_{family}")
    print(f"\n== baseline {family}: rc={res.returncode} {res.stdout.strip().splitlines()[-1]}")
    assert res.returncode == 0, res.stdout[-3000:]


def _killed(scratch, family, mid):
    res, out = _mutate_and_run(scratch, family, mid)
    killer = FAMILIES[family][mid][2]
    assert res.returncode == 1 and f"FAILED {killer}" in out, f"{family}[{mid}] SURVIVED its killer {killer}:\n" \
                                                              f"{out[-3000:]}"


@pytest.mark.parametrize("mid", list(ELIGIBILITY))
def test_eligibility(scratch, mid):
    """Row 512 (Clarification 2 PW-A13): each mutant killed by its named test."""
    _killed(scratch, "eligibility", mid)


@pytest.mark.parametrize("mid", list(SEAL_ONCE))
def test_seal_once(scratch, mid):
    """Row 531 (Clarification 3 SO-A12): each mutant killed by its named test."""
    _killed(scratch, "seal_once", mid)


@pytest.mark.parametrize("mid", list(INTENT_LOWER_BOUND))
def test_intent_lower_bound(scratch, mid):
    """Row 549 (Clarification 4 C4-A10): each mutant killed by its named test."""
    _killed(scratch, "intent_lower_bound", mid)
