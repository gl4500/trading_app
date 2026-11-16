"""A3 H5a targeted semantic mutants with named kill evidence (A10.2): Erratum 2 Clarification 2 row 512
(`eligibility`), Clarification 3 row 531 (`seal_once`) and Clarification 4 row 549 (`intent_lower_bound`). The docs
name the nodes `test_s1_a3_mutants.py targeted (H5 list)::eligibility[...]` etc.; pytest collects only `test_*`
functions, so the nodes are test_eligibility[...], test_seal_once[...] and test_intent_lower_bound[...] (logged as a
deviation, R-G; the parameter ids are the docs' exactly).

Each mutant is applied to a FULL SCRATCH COPY of research/s1 (conftest puts its own research/s1 first on sys.path, so a
mutant can never be run by editing the sources in place): an exact single-occurrence replacement, then the named killing
test runs in a child pytest against the copy (its own basetemp, no bytecode), then the copied file is restored
byte-for-byte (sha256 asserted). A mutant is KILLED when its named killing test fails. A baseline run per family proves
every killing test passes on the unmutated copy first. Slow (one child pytest per mutant).

A3 Task 15b (Task 15 Steps 3-4; PLAN-6, A3-PR1-3, A3-PR1-4; rows 291-298, 339-345) is the second half of this file:
targeted semantic mutants that Cosmic Ray's operators do not express, classified from structured pytest JUnit XML plus
the mutation's installation record (never from the exit code alone), the executed classifier self-tests, and the
executed Hypothesis settings. Each MUTANT names (target, anchor, mutated text, killer selection); the agreed killer
nodeid and TERMINAL assertion path:line are in s1_evidence/a3/t15_agreed_assertions.json (reviewed). A mutation is
installed by re-executing the named function's mutated source in its module namespace INSIDE THE CHILD PROCESS ONLY
(never editing a file); every child runs from a scratch copy of research/s1 under tmp. The H5a families above keep
their own (file-copy, exit-code) runner and their historical labels; they are not Task 15 labels."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
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


# =====================================================================================================================
# A3 Task 15b: targeted semantic mutants with the structured classifier (Step 3), executed Hypothesis settings (Step 4)
# =====================================================================================================================
HERE = Path(__file__).resolve().parent.parent
PY = sys.executable
AGREED = HERE / "s1_evidence" / "a3" / "t15_agreed_assertions.json"   # {mutant: {"nodeid", "terminal", ...}} (reviewed)
EQUIVALENT = {                                                          # {mutant: reason} - reviewed list only
    # T15-F8, peer-reviewed: Codex APPROVED (C:/Users/gl450/.coordination/trading_app/t15b_02db5b9_review_20261116/
    # REVIEW.txt, "Equivalence dispositions requested", F8), scoped exactly as follows.
    "r6-books-economic-in-entry-guard-dropped": (
        "EQUIVALENT within the current synchronous implementation with normal fixed helper definitions: _economic_in "
        "evaluates no input before s1_seal.pinned(px), which immediately performs the same _live check; only "
        "ValueError is caught, so an invalid-pass SystemExit propagates identically; the deleted check has no state "
        "effect. Outside the claim: timing/instrumentation, monkeypatched helper definitions, races changing the pass "
        "externally, future edits. A disposition of the mutant, not a request to remove the product guard."),
}
K = "test_s1_a3_"                                                       # killer file prefix (selections below)
# (target, anchor, mutated text, killer selection "file::function"). The anchor must occur EXACTLY ONCE in the
# CURRENT source of the target function (controller anchor ruling); drift from the plan table is recorded in
# s1_evidence/a3/t15_anchor_map.md. The exact killer nodeid (with parameter ids) is in the agreed-assertions file.
MUTANTS = {
    # row 291: deadline comparisons in decide step 6
    "deadline-intent-ge-to-gt": ("s1_journal._slot", "now >= e", "now > e", K + "precedence.py::test_precedence_table"),
    "deadline-qualified-ge-to-gt": ("s1_journal._slot", "req.r_at >= d", "req.r_at > d",
                                    K + "codex_probes.py::test_publication_at_d_and_d_plus_1us_does_not_seal"),
    "deadline-timeout-lt-to-le": ("s1_journal._slot", "now < d", "now <= d",
                                  K + "finalizer.py::test_timeout_commits_at_d_while_a_live_worker_holds_the_work_lock"),
    "deadline-missed-lt-to-le": ("s1_journal._slot", "now < e", "now <= e",
                                 K + "finalizer.py::test_missed_after_e_with_its_own_op_and_no_files"),
    # row 292: omitted commitments / ACK checks
    "omitted-envelope-input": ("s1_run.attest_start", '"opening_books.json": rec["opening_books_sha256"]', "",
                               K + "prestart.py::test_start_attest_envelope_and_single_member"),
    "omitted-verify-ack-field": ("s1_trial.verify_ack", "if bad:", "if False:",
                                 K + "prestart.py::test_start_attest_verifies_the_opening_ack_against_the_journal"),
    "omitted-check-journal": ("s1_trial.verify_ack", "if probs:", "if False:",
                              K + "trial.py::test_journal_seq_and_head_must_be_extended_without_fork"),
    "omitted-evidence-manifest": ("s1_trial.opening_manifest_check",                          # re-anchored (map)
                                  "got = _manifest_sha(gv.root, gv.rows, seq)\n    if got == want:",
                                  "got = _manifest_sha(gv.root, gv.rows, seq)\n    if True:",
                                  K + "prestart.py::test_opening_ack_evidence_manifest_is_reconstructed"),
    # row 293: STOP rules
    "stop-n-ge-to-gt": ("s1_seal._stop_record", "_close(d, sim=pinned(px))) >= STOP_N:",         # re-anchored (map)
                        "_close(d, sim=pinned(px))) > STOP_N:", K + "stop.py::test_stop_dispositions"),
    "stop-pending-removed": ("s1_seal._stop_record", 'if stt in ("pending", "unresolved"):',   # re-anchored (map)
                             'if stt == "unresolved":', K + "stop.py::test_pending_slot_blocks_the_stop"),
    "stop-prefix-le-to-lt": ("s1_seal._sampled_seals", "x.seq <= upto_seq", "x.seq < upto_seq",  # re-anchored (map)
                             K + "score.py::test_sampled_history_is_canonical_and_fixed_at_the_stop"),
    # row 294: owner / takeover
    "owner-4a-actor-removed": ("s1_journal._slot", "or req.actor != intent.actor", "",
                               K + "slots.py::test_foreign_qualified_is_invalid_even_on_a_terminal_slot"),
    "owner-timeout-op-removed": ("s1_journal._slot",
                                 'k == "SLOT-TIMEOUT" and (intent is None or req.op != intent.op)',
                                 'k == "SLOT-TIMEOUT" and intent is None', K + "precedence.py::test_precedence_table"),
    "owner-recovery-own-op": ("s1_stage.recover", 'm["intent"].op, j.new_nonce()', "j.new_nonce(), j.new_nonce()",
                              K + "stage.py::test_stage_state_table"),
    # row 295: CA scope
    "scope-window-full-swapped": ("s1_collect.final_policy", 'ca("window", fplan["ca_symbols_window"]',
                                  'ca("window", fplan["ca_symbols_full_history"]',
                                  K + "final.py::test_final_policy_is_exactly_the_f49_final_rows"),
    "scope-full-history-start": ("s1_collect.final_policy", 'fplan["full_history_start"]', "start_day",
                                 K + "final.py::test_final_policy_is_exactly_the_f49_final_rows"),
    # row 296: midnight cutoff from the reservation clock
    "cutoff-reservation-clock": ("s1_collect.do_audit", 'cutoff = sw.policy["cutoff"]',
                                 "cutoff = c.now_utc().astimezone(c.NY).date().isoformat()",
                                 K + "audit.py::test_cutoff_is_the_intent_new_york_date_across_midnight"),
    # row 297: erratum mutants
    "erratum-finalizer-takes-work-lock": ("s1_slot.finalize_close", "got = _finalizer_append(",
                                          "got = _locked_append(",
                                          K + "finalizer.py::test_finalizer_decision_never_touches_the_work_lock"),
    "erratum-seal-ignores-close": ("s1_trial.closed_in", "return tr is None or tr.closed is not None", "return False",
                                   K + "finalizer.py::test_barrier_close_between_active_read_and_prepared"),
    "erratum-stop-fence-removed": ("s1_slot.stop_fence",
                                   "return f\"determined close {d['date']} has no CREATED seal stage (E2.5)\"", "pass",
                                   K + "finalizer.py::test_stop_fence_refuses_a_determined_close_without_a_created_seal"),
    "erratum-non-official-close-counts": ("s1_trial.acks_from", "if (sender, recipient, key) != ACK_KEY:", "if False:",
                                          K + "trial.py::test_non_official_lines_are_never_candidates"),
    "erratum-backup-dropped": ("s1_slot.CAPTURE_TREE", '("backup.sqlite3", "meta.json", "projection.json")',
                               '("meta.json", "projection.json")',
                               K + "slots.py::test_qualified_at_is_r_and_detail_is_the_tree_manifest"),
    "erratum-blocked-close-rederived": ("s1_trial._close", "    why = []\n",
                                        "    why = ['re-derived from a root'] if a.fields['reason'] == 'BLOCKED' "
                                        "else []\n",
                                        K + "trial.py::test_two_root_blocked_lifecycle_closure_is_monotone"),
    # R6 (a): the H5b private s1_books helpers (controller ruling R6; not in the plan table)
    "r6-books-economic-in-foreign-module": ("s1_books._economic_in", "return s1_seal.pinned(px).baseline_lots(",
                                            "return c.sim().baseline_lots(",
                                            K + "h5b_pass.py::test_h5b_fifo_replay_uses_this_pass_module"),
    "r6-books-sold-events-foreign-module": ("s1_books._sold_events", "limit = s1_seal.pinned(px).x(c.SOLD_LT)",
                                            "limit = c.sim().x(c.SOLD_LT)",
                                            K + "h5b_pass.py::test_h5b_fifo_replay_uses_this_pass_module"),
    "r6-books-economic-in-entry-guard-dropped": ("s1_books._economic_in", "    s1_seal._live(px)\n    try:",
                                                 "    try:",
                                                 K + "h5b_pass.py::test_h5b_helpers_fail_closed_without_a_live_pass"),
    "r6-books-sold-events-entry-guard-dropped": ("s1_books._sold_events", "    s1_seal._live(px)\n    rs, events",
                                                 "    rs, events",
                                                 K + "h5b_pass.py::test_h5b_helpers_fail_closed_without_a_live_pass"),
    "r6-books-fifo-prefix-off-by-one": ("s1_books._sold_events", 'lots = _economic_in(px, prefix, r["ts"], orphans)',
                                        'lots = _economic_in(px, prefix[:-1], r["ts"], orphans)',
                                        K + "h5b_pass.py::test_h5b_pass_fifo_replay_equals_public_sold_events"),
    # R6 (b): one representative per H4/H5 repair family, on an existing killer
    "r6-strict-enum-nested-oserror-swallowed": (                                    # strict enumeration (H4-CX)
        "s1_common.strict_glob",
        "                    nxt.append((d / e.name, _scan(d / e.name)))    # nested: any OSError raises (O-C5)",
        "                    try:\n                        nxt.append((d / e.name, _scan(d / e.name)))\n"
        "                    except OSError:                                # MUTANT: swallowed\n"
        "                        pass",
        K + "strict_enum.py::test_gate_stray_capture_enumeration_failure_refuses"),
    "r6-listing-refusal-not-held-until-e55": (                                      # held unreadability / E5.5
        "s1_trial.gate",
        "    except c.ListingRefusal as e:                         # (a confirmed F3 violation is a plain Refusal: it "
        "raises)\n        unreadable, listed = [], e",
        "    except KeyboardInterrupt as e:                        # MUTANT: the listing refusal is raised at once\n"
        "        unreadable, listed = [], e",
        K + "strict_enum.py::test_gate_listing_refusal_held_until_e55"),
    "r6-early-refusal-runs-finalizer": (                                            # no early-refusal finalizer
        "s1_checkpoint.run_checkpoint", "        lost = w.intent()\n",
        "        try:\n            lost = w.intent()\n        except SystemExit:                       # MUTANT\n"
        "            _finalize_others(gv, cal, start, day[\"date\"], now, mailbox)\n            raise\n",
        K + "eligibility.py::test_eligibility_refusal_triggers_no_finalizer"),
    "r6-diagnostic-torn-tail-not-completed": (                                      # diagnostic serialization / tail
        "s1_slot.record_early_refusal", "data = _tail_completion(fd, end) + line", "data = line",
        K + "early_refusal_tail.py::test_tail_completion"),
    "r6-typed-identity-kind-ignored": (                                             # typed member identity
        "s1_run._pre_intent_qualified", "if first is None or again != first:",
        "if first is None or again is None or again[0] != first[0]:",
        K + "score.py::test_h5cfix_same_slot_changed_kind_does_not_confirm"),
    "r6-confirming-calendar-hash-unchecked": (                                      # strict same-bytes calendar
        "s1_slot._confirming_calendar",
        "        if man[\"files\"][\"calendar.json\"] != c.sha256_bytes(raw):\n            return None\n", "",
        K + "m4_pass.py::test_h5cfix2_confirming_calendar_helper"),
    "r6-pass-held-across-seal-stages": (                                            # transaction / finalizer pass life
        "s1_seal._decide_locked",
        "        for d in eligible_sessions(start, cal):                    # E2.5: the pending seal stages first\n"
        "            with seal_pass() as px:                                # A3 H5b: a fresh pass per close, never held\n"
        "                sealed = _close_state(px, index, d, cal)[0] == \"sealed\"     # across a seal-stage transaction\n"
        "            if sealed and s1_stage.stage_rows(rows, s1_slot.seal_stage_name(d[\"date\"]))[\"created\"] is None:\n"
        "                s1_slot.run_seal_stage(gv, d, cal, mailbox=mailbox, clock=now)",
        "        with seal_pass() as px:                                    # MUTANT (H5b review R-1): one pass held\n"
        "            for d in eligible_sessions(start, cal):                    # across every seal-stage transaction\n"
        "                sealed = _close_state(px, index, d, cal)[0] == \"sealed\"\n"
        "                if sealed and s1_stage.stage_rows(rows, s1_slot.seal_stage_name(d[\"date\"]))[\"created\"] is None:\n"
        "                    s1_slot.run_seal_stage(gv, d, cal, mailbox=mailbox, clock=now)",
        K + "h5b_pass.py::test_h5b_stop_decision_close_passes_verify_between_seal_stages"),
}
EXTRA = {                                    # helpers some mutated sources call; exec'd into the same namespace
    "erratum-finalizer-takes-work-lock": (
        "import s1_locks as _L\n"
        "def _locked_append(gv, cal, req, mailbox, now):\n"
        "    with _L.OwnershipLock(gv.root, gv.trial.trial_id, _L.slot_lock_name(req.subject)):\n"
        "        return _finalizer_append(gv, cal, req, mailbox, now)\n"),
}
# Results are findings (controller ruling): every mutant whose label is not "killed" carries an explicit strict xfail
# naming its finding id (T15-F<n>), listed in the report and in a3/t15_mutants.txt. A later killing test makes the case
# XPASS, strict mode fails it, and the mark must be removed. raises=AssertionError: only the plan's label assertion is
# expected to fail; a classifier-gate failure (ClassifierNotValidated) or any other error is never absorbed.
# Fix round 2 (review M-3): each mark is specific to the label its reason names ("T15-F<n>: <label>: ..."): any other
# label raises FindingLabelChanged (not an AssertionError) before the plan assertion, so the case FAILS.
FINDINGS = {                                 # from the 15b run (a3/t15_mutants.txt); remove a mark when its case XPASSes
    # Task 15d-2: the T15-F1/F2/F4/F7/F9/F10/F12 marks were removed after their 15d-1 kills at the agreed lines
    # (a3/t15d1/, a3/t15d1_summary.md; Codex reconciliation of 81e1ffd). Their 15b reasons stay in git history and in
    # each a3/t15/<mutant>/record.json "finding".
    # Task 15d-3 (Codex disposition of 5376f42): the T15-F11 mark was removed ONLY because the CURRENTLY selected
    # isolated pending-branch seam oracle (test_s1_a3_t15d_f11_branch.py:31) was killed and independently reconciled
    # (a3/t15d2/stop-pending-removed/). OPEN item T15-F11-REAL (a3/t15d_open_items.md) stays: a real-tuple
    # assertion-oracle gap - the real pending tuple ('pending', None, None) makes the mutant raise the OBSERVED
    # TypeError at s1_seal.py:663 (`deps += dd`) before any intended assertion (failed-elsewhere:
    # a3/t15/stop-pending-removed/, a3/t15d1/stop-pending-removed/). No equivalence; no real-tuple closure.
}

# The plugin: anchor EXACTLY once (controller ruling; the plan's ">= 1" would accept an ambiguous anchor) and the
# mutated source compiled at the function's own first line (tracebacks through it keep the file's line numbers).
PLUGIN = r'''
import hashlib, importlib, inspect, json, os, textwrap
TARGET, OLD, NEW, EXTRA, RECORD = {target!r}, {old!r}, {new!r}, {extra!r}, {record!r}
mod_name, _, attr = TARGET.rpartition(".")
mod = importlib.import_module(mod_name)
obj = getattr(mod, attr)
rec = {{"target": TARGET, "module_file": mod.__file__, "anchor_found": False, "installed": False}}
if isinstance(obj, tuple):
    before = repr(obj)
    setattr(mod, attr, eval(NEW))
    after = repr(getattr(mod, attr))
    rec.update(anchor_found=(before == repr(eval(OLD))), installed=(before != after),
               original_sha256=hashlib.sha256(before.encode()).hexdigest(),
               mutated_sha256=hashlib.sha256(after.encode()).hexdigest())
else:
    lines, first = inspect.getsourcelines(obj)
    src = textwrap.dedent("".join(lines))
    rec["anchor_count"] = src.count(OLD)
    rec["anchor_found"] = rec["anchor_count"] == 1
    if rec["anchor_found"]:
        new_src = src.replace(OLD, NEW, 1)
        ns = vars(mod)                               # the module namespace itself: callers see the mutant
        exec(EXTRA, ns)
        exec(compile("\n" * (first - 1) + new_src, mod.__file__, "exec"), ns)
        rec.update(original_sha256=hashlib.sha256(src.encode()).hexdigest(),
                   mutated_sha256=hashlib.sha256(new_src.encode()).hexdigest(), first_line=first)
        rec["installed"] = rec["original_sha256"] != rec["mutated_sha256"] and getattr(mod, attr) is not obj
with open(RECORD, "w", encoding="utf-8") as f:
    json.dump(rec, f)
'''


# ---- revision 3 (PLAN-R2-1): exact nodeids, whole-selection control, TERMINAL assertion frame -----------------------
JUNIT_OPTS = ["-o", "junit_family=xunit2", "-o", "junit_logging=no"]      # pinned explicitly, never the ini default
TERMINAL = re.compile(r"^(?P<path>\S[^\n]*?):(?P<line>\d+): (?P<exc>[A-Za-z_][\w.]*)(?::[^\n]*)?[ \t]*$", re.M)


def xunit2_key(nodeid: str) -> tuple:
    """The documented xunit2 mapping (pytest's mangle_test_address): a nodeid `dir/test_m.py::Cls::test_f[ids]`
    becomes classname `dir.test_m.Cls` (path relative to the run's rootdir, '/' -> '.', '.py' dropped, then every
    class) and name `test_f[ids]` (parameter IDs kept verbatim). xunit2 writes no `file`/`line` attributes, so they
    are never used; the testcase is identified only by this (classname, name) pair."""
    path, _, rest = nodeid.partition("::")
    parts = rest.split("::")
    module = path[:-3] if path.endswith(".py") else path
    return (".".join([module.replace("\\", "/").replace("/", ".")] + parts[:-1]), parts[-1])


def junit_cases(junit: Path) -> dict:
    """{(classname, name): <testcase>} for every testcase; a duplicate key is a structural error."""
    got = {}
    for tc in ET.parse(junit).getroot().iter("testcase"):
        key = (tc.get("classname", ""), tc.get("name", ""))
        if key in got:
            raise ValueError(f"duplicate JUnit testcase {key}")
        got[key] = tc
    return got


def terminal_frame(text: str):
    """The innermost frame of a pytest long-repr failure: the LAST `path:line: ExcType` line (pytest prints that
    reprcrash line for the frame that raised). Caller frames print `path:line: ` with no exception type and are
    never matched. Returns (posix path, line, exception) or None."""
    ms = list(TERMINAL.finditer(text or ""))
    if not ms:
        return None
    m = ms[-1]
    return (m.group("path").replace("\\", "/"), int(m.group("line")), m.group("exc"))


AGREED_EXC = ("AssertionError", "builtins.AssertionError",      # an assertion, or (controller ruling B3) pytest's
              "Failed", "_pytest.outcomes.Failed")              # Failed: pytest.raises "DID NOT RAISE" / pytest.fail


def at_agreed(frame, agreed_terminal: str) -> bool:
    """`agreed_terminal` is `path:line` (relative, posix). The frame's path must END with that path at a path
    boundary and the line must be equal; the exception must be AssertionError or (ruling B3) pytest's Failed - the
    outcome pytest.raises raises for "DID NOT RAISE" and pytest.fail raises. Any other exception is never a kill."""
    if frame is None:
        return False
    a_path, _, a_line = agreed_terminal.rpartition(":")
    path, line, exc = frame
    path_ok = path == a_path or path.endswith("/" + a_path)
    return path_ok and line == int(a_line) and exc in AGREED_EXC


def run_child(cwd: Path, workdir: Path, selection: str, plugin_text: str, *, pythonpath: str, timeout=1800,
              conftest=True) -> dict:
    """One child pytest of exactly `selection` with JUnit XML (xunit2, pinned), preceded by a --collect-only run of
    the same selection whose exact nodeids are the intended case set. Returns raw facts only. rootdir is pinned to
    `cwd`; bytecode is never written; Hypothesis storage and basetemp are the child's own (under `workdir`)."""
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "s1_mutant_plugin.py").write_text(RECORDER + plugin_text, encoding="utf-8")   # fix round 3: provenance
    junit = workdir / "junit.xml"
    env = dict(os.environ, PYTHONPATH=f"{workdir};{pythonpath}", PYTHONDONTWRITEBYTECODE="1",
               S1_HYPOTHESIS_ROOT=str(workdir / "hyp"))
    base = [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--rootdir={cwd}"] + \
        (["-p", "conftest"] if conftest else [])
    col = subprocess.run(base + ["--collect-only", selection], cwd=cwd, env=env, capture_output=True,
                         text=True, timeout=600)
    nodeids = [ln.strip() for ln in col.stdout.splitlines() if "::" in ln and not ln.startswith(" ")]
    try:
        p = subprocess.run(base + ["-p", "s1_mutant_plugin", f"--junitxml={junit}", f"--basetemp={workdir / 'bt'}"]
                           + JUNIT_OPTS + [selection], cwd=cwd, env=env, capture_output=True, text=True,
                           timeout=timeout)
        rc, timed_out, out = p.returncode, False, p.stdout + p.stderr
    except subprocess.TimeoutExpired:
        rc, timed_out, out = None, True, ""
    (workdir / "pytest-output.txt").write_text(out, encoding="utf-8")
    return {"rc": rc, "timeout": timed_out, "junit": junit if junit.exists() else None,
            "record": workdir / "installed.json", "crash": workdir / "crash.json", "nodeids": nodeids,
            "collect_rc": col.returncode}


def control_valid(control: dict) -> bool:
    """PLAN-R2-1 (2): the WHOLE unmutated selection passed - exit 0, the collect-only set non-empty, and every
    intended nodeid present in the JUnit file with no failure, error or skipped child (not just the first case)."""
    if control["timeout"] or control["rc"] != 0 or control["junit"] is None or control["collect_rc"] != 0:
        return False
    try:
        cases = junit_cases(control["junit"])
    except (ValueError, ET.ParseError):
        return False
    want = {xunit2_key(n) for n in control["nodeids"]}
    return bool(want) and want == set(cases) and all(len(list(tc)) == 0 for tc in cases.values())


def classify(name, control: dict, mutant: dict, agreed: dict) -> str:
    """Labels: killed | survived | error | untested | timeout | crash | not-installed | failed-elsewhere |
    equivalent. `agreed` = {"nodeid": the exact killer nodeid incl. parameter IDs, "terminal": "path:line" of the
    TERMINAL assertion frame (a helper's own file:line when the oracle lives in a helper; reviewed)}.
    'killed' only when: the whole control selection passed; the mutation is verified installed; the mutant run's
    intended nodeid set equals the control's; no <error> anywhere (collection/setup/teardown); the agreed nodeid's
    testcase has a <failure> whose innermost frame is the agreed path:line with AssertionError. Other cases of the
    selection may pass or fail; only the agreed case decides. Nothing else is ever a kill.
    Fix round 3 (X-20/X-21/X-22): the mutant rc must be exactly 1 (any other rc with a JUnit file is error), and the
    frame that decides is the STRUCTURAL one the child recorded (crash.json, call phase); the text frame, parsed from
    the failure body only (no message, nothing after a '---- Captured' line), is a cross-check - a disagreement or a
    missing/unreadable sidecar is error."""
    if name in EQUIVALENT:
        return "equivalent"
    if not control_valid(control):
        return "untested"                                           # not a valid run: never killed
    want = {xunit2_key(n) for n in control["nodeids"]}
    key = xunit2_key(agreed["nodeid"])
    if key not in want:
        return "untested"                                           # the agreed case is not in the selection
    if mutant["timeout"]:
        return "timeout"
    if mutant["junit"] is None and mutant["rc"] in (1, 2, 3, 4, 5):
        return "error"                                              # pytest: interrupted/internal/usage (plugin)
    if mutant["junit"] is None or (mutant["rc"] is not None and mutant["rc"] < 0):
        return "crash"
    try:
        rec = json.loads(Path(mutant["record"]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "error"                                              # the plugin did not run (plugin/import error)
    if not (rec.get("anchor_found") and rec.get("installed")):
        return "not-installed"
    if mutant["rc"] not in (0, 1):
        return "error"                                              # X-21: rc 2/3/4/5 even with a JUnit file
    try:
        cases = junit_cases(mutant["junit"])
    except (ValueError, ET.ParseError):
        return "error"
    if any(tc.find("error") is not None for tc in cases.values()) or \
            any(int(s.get("errors", "0")) for s in ET.parse(mutant["junit"]).getroot().iter("testsuite")):
        return "error"                                              # collection / fixture / setup / teardown
    if set(cases) != want:
        return "untested"                                           # a case went missing or appeared
    tc = cases[key]
    if tc.find("skipped") is not None:
        return "untested"
    fail = tc.find("failure")
    if fail is None:
        return "survived"
    if mutant["rc"] != 1:
        return "error"                                              # X-21: a failure needs pytest's own rc 1
    sframe = structural_frame(mutant, agreed["nodeid"])
    if sframe is None:
        return "error"                                              # no call-phase provenance for this failure
    if not frames_agree(sframe, terminal_frame(failure_body(fail.text))):
        return "error"                                              # structure and text disagree
    return "killed" if at_agreed(sframe, agreed["terminal"]) else "failed-elsewhere"


# ---- fix round 3 (X-20/X-21/X-22; controller ruling: structural provenance) ---------------------------------------
# Appended to EVERY child's s1_mutant_plugin.py (before the mutation text, so a raising mutation cannot pre-empt
# it): the child's own record of each raised exception, per nodeid and phase, from pytest's ExceptionInfo - never
# from rendered text. "terminal" is the innermost NON-HIDDEN traceback entry (pytest's own reprcrash rule,
# ExceptionInfo._getreprcrash: frames with __tracebackhide__, e.g. pytest.raises' internals, are skipped), so a B3
# "DID NOT RAISE" lands on the test's `with` line exactly as pytest reports it; "innermost" is the raw
# traceback[-1], kept as evidence.
RECORDER = r'''
# ---- Task 15b fix round 3: structural crash provenance, recorded by the child itself (crash.json) ----
import json as _t15_json
import os as _t15_os
import pytest as _t15_pytest
_T15_CRASH = _t15_os.path.join(_t15_os.path.dirname(_t15_os.path.abspath(__file__)), "crash.json")
_T15_REC = {}


def _t15_loc(e):
    return None if e is None else {"path": e.frame.code.raw.co_filename, "line": e.lineno + 1}


@_t15_pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    yield
    ei = call.excinfo
    if ei is None:
        return
    tb = list(ei.traceback)
    # pytest's own visible crash (pytest 8.3.3 _pytest/_code/code.py:607-616 ExceptionInfo._getreprcrash: the last
    # entry with no __tracebackhide__, code.py:274 TracebackEntry.ishidden), so pytest.raises/pytest.fail land on
    # the visible oracle line (their helpers hide themselves: python_api.py:1009, outcomes.py:177)
    crash = ei._getreprcrash()
    term_loc = None if crash is None else {"path": crash.path, "line": crash.lineno}
    raw_type = f"{ei.type.__module__}.{ei.type.__qualname__}"
    # pytest's Failed sets __module__ = "builtins"; it is named by IDENTITY (never by a look-alike class's name)
    typ = "_pytest.outcomes.Failed" if ei.type is _t15_pytest.fail.Exception else raw_type
    _T15_REC.setdefault(item.nodeid, {})[call.when] = {
        "type": typ, "type_raw": raw_type, "terminal": term_loc,
        "innermost": _t15_loc(tb[-1] if tb else None)}
    with open(_T15_CRASH, "w", encoding="utf-8") as f:
        _t15_json.dump(_T15_REC, f, indent=1, sort_keys=True)
# ---- end of the recorder; the mutation text (if any) follows ----
'''
CAPTURED = re.compile(r"^-{3,} Captured .*$", re.M)


def failure_body(text: str) -> str:
    """The JUnit failure body only, cut before any '---- Captured ...' section (X-22). The message is never used."""
    m = CAPTURED.search(text or "")
    return (text or "") if m is None else (text or "")[:m.start()]


def structural_frame(run: dict, nodeid: str):
    """(posix path, 1-based line, qualified exception type) of the CALL-phase exception the child recorded for
    `nodeid` (crash.json), or None when the sidecar is missing, unreadable or has no call-phase record."""
    try:
        rec = json.loads(Path(run["crash"]).read_text(encoding="utf-8"))[nodeid]["call"]
        return (str(rec["terminal"]["path"]).replace("\\", "/"), int(rec["terminal"]["line"]), str(rec["type"]))
    except (KeyError, TypeError, ValueError, OSError):
        return None


def frames_agree(sframe, tframe) -> bool:
    """The structural frame and the text-parsed (cross-check) frame name the same path (at a path boundary), line and
    exception class (last dotted component)."""
    if sframe is None or tframe is None:
        return False
    sp, sl_, se = sframe
    tp, tl, te = tframe
    path_ok = sp == tp or sp.endswith("/" + tp) or tp.endswith("/" + sp)
    return path_ok and sl_ == tl and se.rpartition(".")[2] == te.rpartition(".")[2]


def found_frame(run: dict, agreed: dict):
    """Evidence only (Step 5 record): {"structural": the recorded call-phase frame, "text": the frame parsed from the
    JUnit failure body (cross-check)} for the agreed case; each None when absent."""
    try:
        tc = junit_cases(run["junit"]).get(xunit2_key(agreed["nodeid"])) if run["junit"] else None
    except (ValueError, ET.ParseError):
        tc = None
    fail = None if tc is None else tc.find("failure")
    return {"structural": structural_frame(run, agreed["nodeid"]) if run.get("crash") else None,
            "text": None if fail is None else terminal_frame(failure_body(fail.text))}


def evidence_record(workdir: Path) -> dict:
    """PLAN-R2-1 (5): keep the JUnit file, the installation record and the pytest output, with their sha256."""
    got = {}
    for n in ("junit.xml", "installed.json", "crash.json", "pytest-output.txt", "s1_mutant_plugin.py"):
        p = workdir / n
        got[n] = c_sha256(p) if p.exists() else None
    return got


def c_sha256(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# Task 15d-1 (Option A): the evidence tag and the per-mutant child selection come from data. Unset tag = "t15" and
# an agreed entry with no "selection" = MUTANTS[name][3]: both exactly the 15b paths and selections.
T15_TAG_ENV = "S1_T15_EVIDENCE_TAG"


def t15_evidence_tag(env) -> str:
    """The evidence tag from `env` (default "t15"); only `t15[a-z0-9_]*` - never a path - is accepted."""
    tag = env.get(T15_TAG_ENV, "t15")
    if not re.fullmatch(r"t15[a-z0-9_]*", tag):
        raise ValueError(f"{T15_TAG_ENV}={tag!r}: must match t15[a-z0-9_]*")
    return tag


def t15_evidence(tag: str) -> tuple:
    """(mutant evidence dir, classifier self-test evidence dir) for `tag`: a3/<tag>/ and a3/<tag>_selftests/."""
    a3 = HERE / "s1_evidence" / "a3"
    return a3 / t15_evidence_tag({T15_TAG_ENV: tag}), a3 / f"{tag}_selftests"


def t15_selection(test: str, agreed: dict) -> str:
    """The child selection: the agreed entry's "selection" (file::function under s1_tests/) when present, else the
    MUTANTS killer selection `test` - the 15b string, unchanged."""
    return f"research/s1/s1_tests/{agreed.get('selection', test)}"


T15_EVIDENCE, SELFTEST_EVIDENCE = t15_evidence(t15_evidence_tag(os.environ))


class ClassifierNotValidated(Exception):
    """The classifier self-tests did not all pass: no mutation outcome may be reported (never absorbed by a finding's
    xfail mark, which expects only the label AssertionError)."""


@pytest.fixture(scope="session")
def t15_tree(tmp_path_factory):
    """A scratch copy of research/s1 under tmp (<root>/research/s1): every Task 15b child runs from here, never from
    the worktree. The mutation itself lives only in the child's memory."""
    root = tmp_path_factory.mktemp("t15tree")
    shutil.copytree(HERE, root / "research" / "s1",
                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".hypothesis"))
    return root


def _pp(root: Path) -> str:
    s1 = root / "research" / "s1"
    return f"{s1};{s1 / 's1_tests'}"


@pytest.fixture(scope="session")
def classifier_validated(t15_tree, tmp_path_factory):
    """PLAN-R2-1 (5): the classifier self-tests are EXECUTED (a child pytest of exactly them, JUnit kept with its
    sha256 under s1_evidence/a3/t15_selftests/) before any mutation outcome is computed; any self-test failure,
    error, skip or missing case aborts every mutant result."""
    SELFTEST_EVIDENCE.mkdir(parents=True, exist_ok=True)
    bt = tmp_path_factory.mktemp("t15self")
    junit = bt / "junit.xml"                     # fresh tmp path, read back, then copied (no stale evidence is read)
    sel = ["research/s1/s1_tests/test_s1_a3_mutants.py", "-k",
           "test_classifier_self_tests or test_classifier_terminal_frame_and_parameters or "
           "test_classifier_failed_outcome or test_classifier_contract_conditions or test_classifier_provenance or "
           "test_classifier_visible_crash"]
    p = subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "conftest", f"--rootdir={t15_tree}",
                        f"--basetemp={bt / 'bt'}", f"--junitxml={junit}"] + JUNIT_OPTS + sel,
                       cwd=t15_tree, capture_output=True, text=True, timeout=1800,
                       env=dict(os.environ, PYTHONPATH=_pp(t15_tree), PYTHONDONTWRITEBYTECODE="1",
                                S1_HYPOTHESIS_ROOT=str(bt / "hyp")))
    (SELFTEST_EVIDENCE / "pytest-output.txt").write_text(p.stdout + p.stderr, encoding="utf-8")
    if junit.exists():
        (SELFTEST_EVIDENCE / "junit.xml").write_bytes(junit.read_bytes())
    cases = junit_cases(junit) if junit.exists() else {}
    expected = (len(SELF) + 2 + 6 + len(FAILED_OUTCOME) + len(CONTRACT) + len(PROVENANCE)
                + len(VISIBLE))                                  # every self-test ran (none missing or skipped)
    ok = p.returncode == 0 and len(cases) == expected and all(len(list(tc)) == 0 for tc in cases.values())
    (SELFTEST_EVIDENCE / "hashes.json").write_text(json.dumps(
        {"junit.xml": c_sha256(junit) if junit.exists() else None, "cases": len(cases), "expected": expected,
         "rc": p.returncode, "pytest-output.txt": c_sha256(SELFTEST_EVIDENCE / "pytest-output.txt")}, indent=1),
        encoding="utf-8")
    if not ok:
        raise ClassifierNotValidated(f"classifier self-tests did not all pass (rc={p.returncode}, {len(cases)}/"
                                     f"{expected} cases): no mutation outcome may be reported")
    return {"junit_sha256": c_sha256(junit), "cases": len(cases)}


@pytest.fixture(scope="session")
def t15_work(tmp_path_factory):
    """Short per-mutant work roots (Windows path length: the killers build deep s1_out trees under basetemp)."""
    return tmp_path_factory.mktemp("t15w")


class FindingLabelChanged(Exception):
    """A finding's case got a label other than the one its FINDINGS reason names (e.g. survived -> error, or killed:
    remove the mark). Never absorbed by the finding's xfail(raises=AssertionError): the case FAILS."""


def finding_label(name):
    """The label named in a FINDINGS reason ("T15-F<n>: <label>: ..."), or None for a case with no finding."""
    f = FINDINGS.get(name)
    return None if f is None else f.split(": ", 2)[1]


def _case(name):
    f = FINDINGS.get(name)
    return pytest.param(name, marks=pytest.mark.xfail(strict=True, raises=AssertionError, reason=f)) if f else name


def t15_record(name, label, target, selection, agreed, selftests, control, mutant, installed, work) -> dict:
    """The per-mutant record.json content: the 15b fields in their 15b order, then (Task 15d-2, Codex 81e1ffd review)
    the ACTUAL --collect-only return codes run_child observed for the control and the mutant run (never inferred)."""
    return {
        "label": label, "target": target, "selection": selection, "agreed": agreed, "selftests": selftests,
        "control_valid": control_valid(control), "control_rc": control["rc"], "mutant_rc": mutant["rc"],
        "mutant_timeout": mutant["timeout"], "installed": installed, "frame_found": found_frame(mutant, agreed),
        "control": evidence_record(work / "control"), "mutant": evidence_record(work / "mutant"),
        "nodeids": control["nodeids"], "mutant_nodeids": mutant["nodeids"], "finding": FINDINGS.get(name),
        "control_collect_rc": control["collect_rc"], "mutant_collect_rc": mutant["collect_rc"]}


@pytest.mark.parametrize("name", [_case(n) for n in sorted(MUTANTS)])
def test_targeted_mutant_is_killed(tmp_path, classifier_validated, t15_tree, t15_work, name):   # rows 291-297
    target, old, new, test = MUTANTS[name]
    agreed = json.loads(AGREED.read_text(encoding="utf-8"))[name]
    # {"nodeid": "research/s1/s1_tests/<file>::<test>[<param ids>]", "terminal": "<path>:<line>"} (reviewed)
    selection = t15_selection(test, agreed)                   # 15d-1: an agreed "selection" overrides
    pp = _pp(t15_tree)
    work = t15_work / f"m{sorted(MUTANTS).index(name):02d}"
    control = run_child(t15_tree, work / "control", selection, "", pythonpath=pp)
    plugin = PLUGIN.format(target=target, old=old, new=new, extra=EXTRA.get(name, ""),
                           record=str(work / "mutant" / "installed.json"))
    mutant = run_child(t15_tree, work / "mutant", selection, plugin, pythonpath=pp)
    label = classify(name, control, mutant, agreed)
    out = T15_EVIDENCE / name                                  # 15d-1: a3/<S1_T15_EVIDENCE_TAG>/<name>
    out.mkdir(parents=True, exist_ok=True)
    for side in ("control", "mutant"):
        for f in sorted((work / side).glob("*")):
            if f.is_file():
                (out / f"{side}-{f.name}").write_bytes(f.read_bytes())
    try:
        installed = json.loads((work / "mutant" / "installed.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        installed = None
    (out / "record.json").write_text(json.dumps(t15_record(
        name, label, target, selection, agreed, classifier_validated, control, mutant, installed, work),
        indent=1), encoding="utf-8")
    if name in FINDINGS and label != finding_label(name):     # fix round 2 (review M-3): the xfail is label-specific
        raise FindingLabelChanged(f"{name}: label {label!r}, but its finding records {finding_label(name)!r}: "
                                  f"update or remove the mark ({FINDINGS[name]})")
    # the plan's assertion; a PEER-REVIEWED EQUIVALENT entry (and only that) is accepted as a disposition (15d gate)
    assert label == "killed" or (label == "equivalent" and name in EQUIVALENT), (name, label)


SELF = {
    # kind: (test module source, plugin source, expected label)
    "collection-error": ("import does_not_exist_xyz\n\ndef test_k():\n    assert 1 == 1\n", "", "error"),
    "missing-fixture": ("def test_k(no_such_fixture):\n    assert 1 == 1\n", "", "error"),
    "syntax-error": ("def test_k(:\n    assert 1 == 1\n", "", "error"),
    "plugin-error": ("def test_k():\n    assert 1 == 1\n", "raise RuntimeError('plugin boom')\n", "error"),
    "semantic-regression": ("import target_mod\n\ndef test_k():\n    assert target_mod.f() == 1\n",
                            "MUTATE", "killed"),
    # timeout/crash only under the mutation, so the unmutated control still passes
    "timeout": ("import time, target_mod\n\ndef test_k():\n    if target_mod.f() == 2:\n        time.sleep(30)\n"
                "    assert target_mod.f() == 1\n", "MUTATE", "timeout"),
    "crash": ("import os, target_mod\n\ndef test_k():\n    if target_mod.f() == 2:\n        os._exit(9)\n"
              "    assert target_mod.f() == 1\n", "MUTATE", "crash"),
    "not-installed": ("import target_mod\n\ndef test_k():\n    assert target_mod.f() == 1\n", "NOANCHOR",
                      "not-installed"),
}


def _guard_run(tmp_path, monkeypatch, test_src, mutated: bool):
    """Step 3b: cr_guard.main (15a) on a copy of the synthetic project - the CR-style mutation is the project's own
    tmp target_mod.py written mutated on disk (no product file). Supplies 15a's required --control, --target and
    the job-dir env var. Returns (exit code, sidecar status)."""
    import cr_guard
    proj = tmp_path / "guard_proj"
    proj.mkdir()
    (proj / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (proj / "target_mod.py").write_text("def f():\n    return %d\n" % (2 if mutated else 1), encoding="utf-8")
    (proj / "test_synth.py").write_text(test_src, encoding="utf-8")
    control = tmp_path / "guard_control.json"
    control.write_text(json.dumps({"nodes": ["test_synth.py::test_k"]}), encoding="utf-8")
    job = tmp_path / "guard_job"
    monkeypatch.setenv(cr_guard.JOB_DIR_ENV, str(job))
    monkeypatch.chdir(proj)
    code = cr_guard.main(["--control", str(control), "--target", "target_mod", "--deadline", "120", "--",
                          "test_synth.py"])
    return code, json.loads((job / "guard.json").read_text(encoding="utf-8"))["status"]


@pytest.mark.parametrize("kind", sorted(SELF) + ["control-fails", "equivalent-listed"])
def test_classifier_self_tests(tmp_path, monkeypatch, kind):                             # rows 339-341
    """Codex's A3-PR1-4 examples: collection/fixture/syntax/plugin failures are error/untested, never killed; an
    intended semantic regression failing at the agreed terminal assertion is killed; timeout and crash are
    separate. Revision 3: every child runs through the same run_child + classify the product mutants use.
    Step 3b: the collection-error and semantic-regression projects also go through cr_guard.main (exit 0 / 1)."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")         # pins rootdir to proj
    (proj / "target_mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    src, plug, want = SELF.get(kind, ("import target_mod\n\ndef test_k():\n    assert target_mod.f() == 1\n", "",
                                      None))
    (proj / "test_synth.py").write_text(src, encoding="utf-8")
    record = tmp_path / "mutant" / "installed.json"
    mutate = PLUGIN.format(target="target_mod.f", old="return 1", new="return 2", extra="", record=str(record))
    noanchor = PLUGIN.format(target="target_mod.f", old="return 99", new="return 2", extra="", record=str(record))
    plug_text = {"MUTATE": mutate, "NOANCHOR": noanchor}.get(plug, plug or mutate)
    agreed = {"nodeid": "test_synth.py::test_k", "terminal": "test_synth.py:4"}
    control_plugin = "" if kind != "control-fails" else "import target_mod\ntarget_mod.f = lambda: 0\n"
    control = run_child(proj, tmp_path / "control", "test_synth.py", control_plugin, pythonpath=str(proj),
                        timeout=10, conftest=False)
    mutant = run_child(proj, tmp_path / "mutant", "test_synth.py", plug_text, pythonpath=str(proj), timeout=10,
                       conftest=False)
    if kind == "equivalent-listed":
        monkeypatch.setitem(EQUIVALENT, "synthetic", "listed for this self-test")
        assert classify("synthetic", control, mutant, agreed) == "equivalent"
        return
    got = classify("synthetic", control, mutant, agreed)
    if kind == "control-fails":
        assert got == "untested"
    elif kind in ("collection-error", "missing-fixture", "syntax-error", "plugin-error"):
        assert got in ("error", "untested") and got != "killed"
    else:
        assert got == want
    if kind in ("collection-error", "semantic-regression"):                 # Step 3b: the CR guard, same projects
        code, status = _guard_run(tmp_path, monkeypatch, src, kind == "semantic-regression")
        assert (code, status) == ((1, "killed") if kind == "semantic-regression" else (0, "error:collection"))


# ---- revision 3 self-tests (PLAN-R2-1 point 4): Codex's two r2 probes as fixtures, verbatim sources -------------
PROBE_PARAM = (                      # s1_a3_plan_r2_codex_review_20261104/synthetic-classifier/test_synth.py
    "import os\nimport pytest\n\ndef target(x):\n"
    "    return -1 if os.environ.get(\"S1_CLASSIFIER_MUTATED\") == \"1\" and x == 1 else x\n\n"
    "@pytest.mark.parametrize(\"x\", [0, 1])\ndef test_k(x):\n    assert target(x) == x\n")
PROBE_HELPER_TEST = "from helper_mod import helper\ndef test_k():\n    assert helper() == 1\n"   # test_helper.py
PROBE_HELPER_MOD = (                 # synthetic-helper-frame/helper_mod.py
    "import os\ndef helper():\n    if os.environ.get(\"S1_CLASSIFIER_MUTATED\") == \"1\":\n"
    "        assert False, \"unrelated helper invariant\"\n    return 1\n")
FLAG_PLUGIN = (                      # the "mutation": an env flag, with a verified installation record
    "import json, os\nos.environ['S1_CLASSIFIER_MUTATED'] = '1'\n"
    "json.dump({{'anchor_found': True, 'installed': True, 'original_sha256': '1' * 64, "
    "'mutated_sha256': '2' * 64}}, open({record!r}, 'w'))\n")          # (braces doubled for str.format)


def _probe_project(tmp_path, files: dict) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    for n, src in files.items():
        (proj / n).write_text(src, encoding="utf-8")
    return proj


@pytest.mark.parametrize("case", ["later-parameter-killed", "later-parameter-agreed-case0-survived",
                                  "later-control-failure", "helper-frame-caller-agreed",
                                  "helper-frame-helper-agreed", "caller-frame-substring-xml"])
def test_classifier_terminal_frame_and_parameters(tmp_path, case):                      # rows 342-344
    """PLAN-R2-1: exact nodeid with parameter IDs; the whole control selection; the TERMINAL frame."""
    if case == "caller-frame-substring-xml":           # Codex's synthetic-classifier/caller-frame.xml, as text
        text = ("test_synth.py:9: in test_k\n    assert helper()\nhelper.py:3: AssertionError: unrelated internal "
                "assertion")
        assert terminal_frame(text) == ("helper.py", 3, "AssertionError")
        assert not at_agreed(terminal_frame(text), "test_synth.py:9")             # caller substring is not enough
        return
    helper = case.startswith("helper-frame")
    proj = _probe_project(tmp_path, {"test_helper.py": PROBE_HELPER_TEST, "helper_mod.py": PROBE_HELPER_MOD}
                          if helper else {"test_synth.py": PROBE_PARAM})
    sel = "test_helper.py" if helper else "test_synth.py"
    plug = FLAG_PLUGIN.format(record=str(tmp_path / "mutant" / "installed.json"))
    control_plug = plug if case == "later-control-failure" else ""     # the control's case [1] fails too
    control = run_child(proj, tmp_path / "control", sel, control_plug, pythonpath=str(proj), timeout=60,
                        conftest=False)
    mutant = run_child(proj, tmp_path / "mutant", sel, plug, pythonpath=str(proj), timeout=60, conftest=False)
    agreed = {
        "later-parameter-killed": {"nodeid": "test_synth.py::test_k[1]", "terminal": "test_synth.py:9"},
        "later-parameter-agreed-case0-survived": {"nodeid": "test_synth.py::test_k[0]",
                                                  "terminal": "test_synth.py:9"},
        "later-control-failure": {"nodeid": "test_synth.py::test_k[1]", "terminal": "test_synth.py:9"},
        "helper-frame-caller-agreed": {"nodeid": "test_helper.py::test_k", "terminal": "test_helper.py:3"},
        "helper-frame-helper-agreed": {"nodeid": "test_helper.py::test_k", "terminal": "helper_mod.py:4"},
    }[case]
    want = {"later-parameter-killed": "killed",                        # case0 passes, case1 fails at agreed line
            "later-parameter-agreed-case0-survived": "survived",       # the agreed case itself passed
            "later-control-failure": "untested",                       # not a valid run: never killed
            "helper-frame-caller-agreed": "failed-elsewhere",          # innermost frame is helper_mod.py:4
            "helper-frame-helper-agreed": "killed"}[case]              # the reviewed helper oracle line
    assert control["nodeids"] == ([f"{sel}::test_k"] if helper else [f"{sel}::test_k[0]", f"{sel}::test_k[1]"])
    assert classify("probe", control, mutant, agreed) == want


# ---- Fix round 1 (controller ruling B3): pytest's Failed at the agreed line is a kill; nothing else new is -----------
RAISES_TEST = ("import pytest, target_mod\n\ndef test_k():\n    with pytest.raises(ValueError, match=\"boom\"):\n"
               "        target_mod.g()\n")                       # line 4: the `with pytest.raises` oracle
LEN_TEST = "import target_mod\n\ndef test_k():\n    assert len(target_mod.h()) == 1\n"   # line 4
FAILED_OUTCOME = {
    # case: (test source, mutation (old, new) of target_mod, agreed terminal, expected label)
    "raises-stops-raising-at-agreed-line": (RAISES_TEST, ("raise ValueError(\"boom\")", "return None"),
                                            "test_synth.py:4", "killed"),
    "raises-stops-raising-other-line": (RAISES_TEST, ("raise ValueError(\"boom\")", "return None"),
                                        "test_synth.py:5", "failed-elsewhere"),
    "typeerror-at-agreed-line": (LEN_TEST, ("return [1]", "return 5"), "test_synth.py:4", "failed-elsewhere"),
}


@pytest.mark.parametrize("case", sorted(FAILED_OUTCOME))
def test_classifier_failed_outcome(tmp_path, case):                                       # ruling B3
    """B3: a pytest.raises killer whose mutant stops raising ("Failed: DID NOT RAISE") is killed only at the agreed
    `with pytest.raises` line; the same failure at another agreed line is failed-elsewhere; a non-assertion exception
    (TypeError) at the agreed line is never killed."""
    src, (old, new), terminal, want = FAILED_OUTCOME[case]
    proj = _probe_project(tmp_path, {"test_synth.py": src, "target_mod.py": (
        "def g():\n    raise ValueError(\"boom\")\n\n\ndef h():\n    return [1]\n")})
    target = "target_mod.g" if "raises" in case else "target_mod.h"
    plug = PLUGIN.format(target=target, old=old, new=new, extra="", record=str(tmp_path / "mutant" / "installed.json"))
    control = run_child(proj, tmp_path / "control", "test_synth.py", "", pythonpath=str(proj), timeout=60,
                        conftest=False)
    mutant = run_child(proj, tmp_path / "mutant", "test_synth.py", plug, pythonpath=str(proj), timeout=60,
                       conftest=False)
    assert classify("b3", control, mutant, {"nodeid": "test_synth.py::test_k", "terminal": terminal}) == want


# ---- Fix round 2 (review I-1, M-1): every remaining "killed" condition and classify branch is pinned -------------
CONTRACT_TARGET = "def f():\n    return 1\n\n\ndef g():\n    raise ValueError(\"first\")\n"
PLAIN_TEST = "import target_mod\n\ndef test_k():\n    assert target_mod.f() == 1\n"                    # assert: line 4
TEARDOWN_TEST = ("import pytest, target_mod\n\n@pytest.fixture\ndef fx():\n    yield\n    if target_mod.f() == 2:\n"
                 "        raise RuntimeError(\"teardown boom\")\n\ndef test_k(fx):\n    assert target_mod.f() == 1\n")  # :10
SIBLING_ERROR_TEST = ("import pytest, target_mod\n\n@pytest.fixture\ndef fx():\n    if target_mod.f() == 2:\n"
                      "        raise RuntimeError(\"setup boom\")\n\ndef test_e(fx):\n    pass\n\ndef test_k():\n"
                      "    assert target_mod.f() == 1\n")       # test_k :12; test_e errors in SETUP only when mutated
CASESET_TEST = ("import pytest, target_mod\n\n@pytest.mark.parametrize(\"x\", [0, 1] if target_mod.f() == 1 else [0])\n"
                "def test_p(x):\n    assert x in (0, 1)\n\ndef test_k():\n    assert target_mod.f() == 1\n")  # test_k :8
SKIP_TEST = ("import pytest, target_mod\n\ndef test_k():\n    if target_mod.f() == 2:\n"
             "        pytest.skip(\"skipped under the mutation\")\n    assert target_mod.f() == 1\n")              # :6
CHAINED_TEST = ("import target_mod\n\ndef test_k():\n    try:\n        target_mod.g()\n    except ValueError:\n"
                "        assert target_mod.f() == 1\n")              # :7, raised while handling target_mod.py:6
MUTATE = ("return 1", "return 2")
CONTRACT = {
    # case: (test source, mutation (old, new) of target_mod.f, agreed nodeid, agreed terminal, expected label)
    # xunit2 writes a teardown error as a SECOND <testcase> of the same name: caught by junit_cases' duplicate check
    # (and by the <error> check); the sibling setup error isolates the <error> check alone
    "failure-plus-teardown-error": (TEARDOWN_TEST, MUTATE, "test_synth.py::test_k", "test_synth.py:10", "error"),
    "failure-plus-sibling-setup-error": (SIBLING_ERROR_TEST, MUTATE, "test_synth.py::test_k", "test_synth.py:12",
                                         "error"),
    "agreed-line-in-another-file": (PLAIN_TEST, MUTATE, "test_synth.py::test_k", "other_file.py:4",
                                    "failed-elsewhere"),
    "mutant-drops-a-sibling-case": (CASESET_TEST, MUTATE, "test_synth.py::test_k", "test_synth.py:8", "untested"),
    "agreed-nodeid-not-in-selection": (PLAIN_TEST, MUTATE, "test_synth.py::test_absent", "test_synth.py:4",
                                       "untested"),
    "agreed-case-skipped": (SKIP_TEST, MUTATE, "test_synth.py::test_k", "test_synth.py:6", "untested"),
    "mutation-leaves-source-unchanged": (PLAIN_TEST, ("return 1", "return 1"), "test_synth.py::test_k",
                                         "test_synth.py:4", "not-installed"),
    "chained-exception-terminal-is-last": (CHAINED_TEST, MUTATE, "test_synth.py::test_k", "test_synth.py:7", "killed"),
}


def _label(control, mutant, agreed) -> str:
    """classify, with an exception reported as a label (so a broken branch fails the self-test by assertion)."""
    try:
        return classify("contract", control, mutant, agreed)
    except Exception as e:                                    # noqa: BLE001 - reported, then asserted on
        return f"raised {type(e).__name__}"


@pytest.mark.parametrize("case", sorted(CONTRACT))
def test_classifier_contract_conditions(tmp_path, case):                                   # review I-1, M-1
    """Each case has a VALID control and isolates one condition of the plan's 'killed' contract (or one classify /
    plugin branch): a <failure> plus an <error> (the agreed case's own teardown error, written by xunit2 as a duplicate
    testcase; a sibling case's setup error) is error; a failure at the agreed line NUMBER in another file is
    failed-elsewhere; a mutant run whose case set differs from the control's is untested; an agreed nodeid outside the
    selection is untested; a skipped agreed case is untested; a mutation whose source is unchanged is not-installed
    (the plugin's sha check); the terminal frame is the LAST typed frame (a chained exception)."""
    src, (old, new), nodeid, terminal, want = CONTRACT[case]
    proj = _probe_project(tmp_path, {"test_synth.py": src, "target_mod.py": CONTRACT_TARGET})
    plug = PLUGIN.format(target="target_mod.f", old=old, new=new, extra="",
                         record=str(tmp_path / "mutant" / "installed.json"))
    control = run_child(proj, tmp_path / "control", "test_synth.py", "", pythonpath=str(proj), timeout=60,
                        conftest=False)
    mutant = run_child(proj, tmp_path / "mutant", "test_synth.py", plug, pythonpath=str(proj), timeout=60,
                       conftest=False)
    assert control_valid(control), case                      # the condition under test is the mutant's, never the control
    assert _label(control, mutant, {"nodeid": nodeid, "terminal": terminal}) == want


# ---- Fix round 3 (X-20 / X-21 / X-22; controller ruling: structural provenance) -----------------------------------
SPOOF_HELPER = ("def helper(v):\n    assert v == 1, \"\\ntest_synth.py:6: AssertionError\"\n\n\n"
                "def plain(v):\n    assert v == 1\n")          # the real terminal is helper_mod.py:2 / :6
MSG_SPOOF_TEST = ("import target_mod\nfrom helper_mod import helper\n\n\ndef test_k():\n"
                  "    helper(target_mod.f())\n")                # :6 calls the helper; its MESSAGE names test_synth.py:6
STDOUT_SPOOF_TEST = ("import target_mod\nfrom helper_mod import plain\n\n\ndef test_k():\n"
                     "    print(\"test_synth.py:7: AssertionError\")\n    plain(target_mod.f())\n")   # stdout spoof of :7
RC_EXTRA = {
    2: "\n\ndef pytest_sessionfinish(session, exitstatus):\n    session.exitstatus = 2\n",
    3: "\n\ndef pytest_sessionfinish(session, exitstatus):\n    session.exitstatus = 3\n",
    4: ("\n\nimport pytest\n\n\n@pytest.hookimpl(hookwrapper=True, tryfirst=True)\n"
        "def pytest_sessionfinish(session, exitstatus):\n    yield\n"
        "    raise pytest.UsageError(\"synthetic post-JUnit plugin failure\")\n"),
}
PROVENANCE = {
    # case: (test source, extra plugin text, agreed terminal, post-run sidecar action, expected label)
    "message-spoof": (MSG_SPOOF_TEST, "", "test_synth.py:6", None, "failed-elsewhere"),
    # X-22 scope: with junit_logging=no (pinned) pytest 8.3.3 keeps captured output OUT of the JUnit failure text, so
    # a real printed spoof is NOT a reachable path here (real run below: a regression control). The injected case is
    # a SYNTHETIC-XML PARSER test: it edits the real JUnit text to carry a "Captured stdout" section (crafted XML).
    "captured-stdout-spoof": (STDOUT_SPOOF_TEST, "", "test_synth.py:7", None, "failed-elsewhere"),
    "captured-section-in-junit-text": (STDOUT_SPOOF_TEST, "", "test_synth.py:7", "inject-captured",
                                       "failed-elsewhere"),
    "rc2-after-junit": (PLAIN_TEST, RC_EXTRA[2], "test_synth.py:4", None, "error"),
    "rc3-after-junit": (PLAIN_TEST, RC_EXTRA[3], "test_synth.py:4", None, "error"),
    "rc4-usage-error-after-junit": (PLAIN_TEST, RC_EXTRA[4], "test_synth.py:4", None, "error"),
    "structure-text-disagree": (PLAIN_TEST, "", "test_synth.py:4", "disagree", "error"),
    "sidecar-missing": (PLAIN_TEST, "", "test_synth.py:4", "missing", "error"),
}


@pytest.mark.parametrize("case", sorted(PROVENANCE))
def test_classifier_provenance(tmp_path, case):                                           # X-20, X-21, X-22
    """killed needs the STRUCTURAL frame (the child's own pytest_runtest_makereport record of the call-phase
    exception: qualified type, innermost non-hidden path:line) at the agreed line, and mutant rc == 1. A spoofing
    assertion message or captured stdout never supplies the frame; any rc other than 1 with a JUnit file is error; a
    structural/text disagreement or a missing sidecar is error. Real child runs; disagree/missing edit the real sidecar.
    captured-section-in-junit-text is a synthetic-XML parser test (crafted JUnit text), NOT a reachable child-run path
    under the pinned junit_logging=no (X-22 scope, Codex review of 02db5b9)."""
    src, extra, terminal, action, want = PROVENANCE[case]
    proj = _probe_project(tmp_path, {"test_synth.py": src, "target_mod.py": CONTRACT_TARGET,
                                     "helper_mod.py": SPOOF_HELPER})
    plug = PLUGIN.format(target="target_mod.f", old="return 1", new="return 2", extra="",
                         record=str(tmp_path / "mutant" / "installed.json")) + extra
    control = run_child(proj, tmp_path / "control", "test_synth.py", "", pythonpath=str(proj), timeout=60,
                        conftest=False)
    mutant = run_child(proj, tmp_path / "mutant", "test_synth.py", plug, pythonpath=str(proj), timeout=60,
                       conftest=False)
    sidecar = tmp_path / "mutant" / "crash.json"
    if action == "disagree":                   # structurally line 2, while the text terminal says line 4
        sidecar.write_text(json.dumps({"test_synth.py::test_k": {"call": {
            "type": "builtins.AssertionError", "terminal": {"path": str(proj / "test_synth.py"), "line": 2},
            "innermost": {"path": str(proj / "test_synth.py"), "line": 2}}}}), encoding="utf-8")
    elif action == "missing":
        sidecar.unlink(missing_ok=True)
    elif action == "inject-captured":          # the failure body + a captured section carrying the spoof line
        jx = tmp_path / "mutant" / "junit.xml"
        tree = ET.parse(jx)
        (fail,) = [f for f in tree.getroot().iter("failure")]
        fail.text = (fail.text or "") + ("\n----------------------------- Captured stdout call "
                                         "-----------------------------\ntest_synth.py:7: AssertionError\n")
        tree.write(jx, encoding="utf-8", xml_declaration=True)
    assert control_valid(control), case
    assert _label(control, mutant, {"nodeid": "test_synth.py::test_k", "terminal": terminal}) == want


# ---- Fix round 3 amendment (ruling B3 x structural frame): pytest's VISIBLE crash is recorded -------------------
VC_TARGET = ("def f():\n    return 1\n\n\ndef g():\n    raise ValueError(\"boom\")\n\n\n"
             "def h():\n    raise KeyError(\"cause\")\n")
FAIL_TEST = ("import pytest, target_mod\n\ndef test_k():\n    if target_mod.f() != 1:\n"
             "        pytest.fail(\"f changed\")\n")                                    # pytest.fail at :5
HELPER_TEST = "import target_mod\nfrom helper_mod import plain\n\ndef test_k():\n    plain(target_mod.f())\n"
CHAIN_TEST = ("import target_mod\n\n\ndef test_k():\n    try:\n        target_mod.h()\n    except KeyError as e:\n"
              "        if target_mod.f() != 1:\n            raise AssertionError(\"outer\") from e\n")   # raise at :9
VISIBLE = {
    # case: (test source, target, (old, new), agreed terminal, expected label, expected structural (file, line, type))
    "raises-did-not-raise-at-agreed-line": (RAISES_TEST, "target_mod.g", ("raise ValueError(\"boom\")", "return None"),
                                            "test_synth.py:4", "killed",
                                            ("test_synth.py", 4, "_pytest.outcomes.Failed")),
    "pytest-fail-at-agreed-line": (FAIL_TEST, "target_mod.f", MUTATE, "test_synth.py:5", "killed",
                                   ("test_synth.py", 5, "_pytest.outcomes.Failed")),
    "assertion-in-helper-agreed-at-helper": (HELPER_TEST, "target_mod.f", MUTATE, "helper_mod.py:6", "killed",
                                             ("helper_mod.py", 6, "builtins.AssertionError")),
    "chained-raise-from-records-the-outer-crash": (CHAIN_TEST, "target_mod.f", MUTATE, "test_synth.py:9", "killed",
                                                   ("test_synth.py", 9, "builtins.AssertionError")),
}


@pytest.mark.parametrize("case", sorted(VISIBLE))
def test_classifier_visible_crash(tmp_path, case):                                       # B3 x structural frame
    """The structural frame is pytest's own visible crash (ExceptionInfo._getreprcrash: the last entry without
    __tracebackhide__), with the type taken from excinfo.type: pytest.raises DID NOT RAISE and pytest.fail land on the
    test's own line (not inside pytest's hidden helpers); an assertion in a helper lands on the helper's line; for
    `raise X from Y` the record is the raised (outer) exception's crash, never its cause. Real child runs."""
    src, target, (old, new), terminal, want, (sfile, sline, stype) = VISIBLE[case]
    proj = _probe_project(tmp_path, {"test_synth.py": src, "target_mod.py": VC_TARGET, "helper_mod.py": SPOOF_HELPER})
    plug = PLUGIN.format(target=target, old=old, new=new, extra="", record=str(tmp_path / "mutant" / "installed.json"))
    control = run_child(proj, tmp_path / "control", "test_synth.py", "", pythonpath=str(proj), timeout=60,
                        conftest=False)
    mutant = run_child(proj, tmp_path / "mutant", "test_synth.py", plug, pythonpath=str(proj), timeout=60,
                       conftest=False)
    assert control_valid(control), case
    got = structural_frame({"crash": tmp_path / "mutant" / "crash.json"}, "test_synth.py::test_k")
    assert got is not None and got[0].endswith("/" + sfile) and got[1:] == (sline, stype), got
    assert _label(control, mutant, {"nodeid": "test_synth.py::test_k", "terminal": terminal}) == want


# ---- Step 4 (row 298; revision 2, A3-PR1-3): Hypothesis settings EXECUTED -------------------------------------------
def test_hypothesis_property_executes_with_the_pinned_settings():
    """Imports and EXECUTES the decorated property in this (pinned) testenv - not a source-string check. A settings
    or collection error (e.g. derandomize=True with an explicit database, Codex's probe) fails here."""
    import test_s1_a3_precedence as tp
    prop = tp.test_substep_conditions_are_disjoint_and_decide_matches_the_oracle
    s = prop._hypothesis_internal_use_settings                    # the settings object Hypothesis attached
    assert s.derandomize is True and s.database is None
    prop()                                                        # runs all examples + generated cases to completion
    examples = getattr(prop, "hypothesis_explicit_examples", None) or \
        getattr(prop.hypothesis.inner_test, "hypothesis_explicit_examples", [])
    assert len(examples) >= 2                                     # the retained @example set is attached


# ---- Task 15d-1 (Option A) pin: selection and evidence tag from data; absent = the 15b behaviour ------------------
def test_t15d1_selection_and_evidence_tag_from_data():
    test = MUTANTS["deadline-missed-lt-to-le"][3]
    assert t15_selection(test, {"nodeid": "x", "terminal": "y:1"}) == f"research/s1/s1_tests/{test}"
    assert t15_selection(test, {"selection": "test_s1_a3_precedence.py::test_precedence_table"}) == \
        "research/s1/s1_tests/test_s1_a3_precedence.py::test_precedence_table"
    a3 = HERE / "s1_evidence" / "a3"
    assert t15_evidence_tag({}) == "t15" and t15_evidence("t15") == (a3 / "t15", a3 / "t15_selftests")
    assert t15_evidence_tag({T15_TAG_ENV: "t15d1"}) == "t15d1"
    assert t15_evidence("t15d1") == (a3 / "t15d1", a3 / "t15d1_selftests")
    for bad in ("", "x15", "T15", "t15/../t15", "t15d1\\..", "../t15"):
        with pytest.raises(ValueError):
            t15_evidence_tag({T15_TAG_ENV: bad})


# ---- Task 15d-2 pin: the record carries the actual collect-only return codes (synthetic probe; no S1 mutant) --------
def test_t15d2_record_carries_the_actual_collect_rcs(tmp_path):
    proj = _probe_project(tmp_path, {"test_synth.py": "def test_k():\n    assert 1 == 1\n"})
    control = run_child(proj, tmp_path / "control", "test_synth.py", "", pythonpath=str(proj), timeout=60,
                        conftest=False)
    mutant = run_child(proj, tmp_path / "mutant", "test_absent.py", "", pythonpath=str(proj), timeout=60,
                       conftest=False)                       # a selection that cannot collect: a distinct, real rc
    assert control["collect_rc"] == 0 and mutant["collect_rc"] not in (0, None), (control, mutant)
    agreed = {"nodeid": "test_synth.py::test_k", "terminal": "test_synth.py:2"}
    rec = t15_record("synthetic", "survived", "m.f", "test_synth.py", agreed, {}, control, mutant, None, tmp_path)
    assert rec["control_collect_rc"] == control["collect_rc"] and rec["mutant_collect_rc"] == mutant["collect_rc"]
    assert list(rec) == ["label", "target", "selection", "agreed", "selftests", "control_valid", "control_rc",
                         "mutant_rc", "mutant_timeout", "installed", "frame_found", "control", "mutant", "nodeids",
                         "mutant_nodeids", "finding", "control_collect_rc", "mutant_collect_rc"]
    import inspect                                            # the targeted runner writes exactly this record
    assert "json.dumps(t15_record(" in inspect.getsource(test_targeted_mutant_is_killed)
