# A3 Task 14b - old -> new (base 56f8cb2: full suite 5083 passed, 7 skipped, 26 xfailed)

Classes: **intended** (the product change the brief requires: after any journal row a damaged plan.json is
TRIAL-INVALID, never a resumable refusal), **held-released** (a Task 14 strict-xfail hold whose product fix this is;
marker removed, expected outcome unchanged), **new** (a new test). No requirement-map row's expected outcome changed:
the matrix oracle (row 255) is untouched; only the o3_held selector and its markers are deleted.

## Product outcome changes (all are plan.json-damage cases after a journal row; nothing else changes)
Source: `research/s1/s1_trial.py` (`gate` -> new `_plan_after_rows`, `_plan_read`, `_plan_problem`; `_legacy_detectors`
gains `stray=`), `research/s1/s1_common.py` (`registration_gate` gains `stray_refuses=True`, default = old behaviour).

| # | Case (after any journal row) | Old (HEAD 56f8cb2) | New | Class |
|---|---|---|---|---|
| 1 | plan.json deleted / unparseable / without trial_id, no registration yet (after-audit) | F6.2 refusal "plan.json trial_id None differs ...", no row; restoring resumes | TRIAL-INVALID (stage-replaced), record {stage audit, bound_input plan.json, problem}, local abort; restoring stays INVALID | intended |
| 2 | 1 + a fabricated attest_start / prereg / stop.json | A2 B3.2 "inconsistent pre-registration state" refusal, no row; resumes | TRIAL-INVALID (stage-replaced) | intended |
| 3 | plan.json changed (same trial_id, other bytes) + fabricated attest_start / prereg / stop.json | B3.2 refusal, no row | TRIAL-INVALID (stage-replaced) | intended |
| 4 | plan.json changed alone, or with the audit tree | legacy detector (nothing), then the F4 table: INVALID (stage-replaced) "stage audit: bound input plan.json missing or changed" | same reason, decided by the gate before stop_check / the F4 table; message "stage audit: bound input plan.json missing or changed since the AUDIT-ACK (changed, after journal rows; ...): INVALID (stage-replaced)" (worded like the F4 table's, so the existing matchers `stage audit: .*INVALID \(stage-replaced\)` and conftest.s1_replaced("plan.json") still match); now also writes the local abort | intended (reason unchanged, decider changed) |
| 5 | plan damage once a registration exists (after-opening on) | legacy detector: persistent INVALID (registration-artifact) | unchanged: the legacy detector still runs first (stray refusal off only) and decides | unchanged |
| 6 | plan.json parses and names ANOTHER trial_id (Task 14b round 0; superseded by fix round 1, see below) | the legacy detector ran on any such plan after rows. After the opening it INVALIDATED THIS trial (registration-artifact, "... plan.json differs from every AUDIT-ACK's plan_sha256") both for a plan swapped into this trial's root AND for another trial's genuine whole root gated under this trial's mailbox (review I-1, measured): right outcome for the swap, wrong reason, and a violation of F6.2/F10 Identity for the genuine foreign root | round 0: F6.2 refusal, no row, in both cases. Fix round 1 (ruling "T14b I-1"): INVALID (stage-replaced, "names another trial_id") when the root holds this trial's journal-bound audit artifact (staging intent.json = the INTENT detail, or a committed audit member); F6.2 refusal with no row otherwise (another trial's genuine root) | intended |
| 7 | another trial_id in this root + fabricated attest_start (after-audit) | B3.2 refusal | round 0: F6.2 refusal; fix round 1: TRIAL-INVALID (stage-replaced) | intended |
| 8 | OSError other than FileNotFoundError on the plan read | uncaught PermissionError traceback out of `c.sha_or_absent` (no row) | refusal "plan.json unreadable (<type>) after journal rows: not a confirmed violation, refused with no row" | intended |
| 9 | plan damaged on the first read, different on the re-read (incl. absent then intact) | F6.2 refusal, no row (no re-read existed) | refusal "... not confirmed, refused with no row" | intended (message; outcome already no-row) |
| 10 | plan.json damaged while the audit stage has only its INTENT and a live owner holds its lock | legacy detector, then the F4 table: "pending" refusal (56f8cb2: the F6.2 refusal for unparseable, review M-2) | TRIAL-INVALID (stage-replaced), message "... the audit stage is at INTENT ..."; an intact plan is still "pending" (fix round 1 test test_fx1_a_live_audit_owner_at_intent_...) | intended (F4.1: the INTENT commits plan.json's sha256; F6.2; F9) |

Before any journal row the gate's plan check is byte-for-byte the old code (`load_json(...).get("trial_id")`,
refusal on a mismatch, no legacy detector): unchanged (controls in the new test file).

## Held released (Task 14 fix round 1, ruling "T14 I-2")
`research/s1/s1_tests/test_s1_a3_matrix.py`: `O3_REASON`, `o3_held()`, `O3_B32_FILES` and the `marks=[xfail(strict=True)]`
on PARAMS are deleted; the oracle docstring's O-3 bullet now says Task 14b fixed it. Before deletion, with the fixed
product, the after-audit default subset gave **26 failed [XPASS(strict)], 304 passed** - the 26 failures are exactly
the 26 held ids (t14b_green.txt). After deletion all 26 PASS (listed in t14b_green.txt); the exhaustive after-audit
subset is **3066 passed** (t14b_matrix_after_audit.txt; was 2780 passed + 286 xfailed).

## New tests (research/s1/s1_tests/test_s1_a3_plan_damage.py, 38)
- test_control_the_undamaged_snapshot_passes_the_gate[3 points] - control.
- test_a_damaged_plan_after_journal_rows_is_invalid_and_restoring_never_resumes[after-audit|after-opening|after-start-attest x deleted|unparseable|no-trial-id] - 9.
  After-audit: reason/stage-replaced from the gate. After-opening / after-start-attest: the legacy detector's
  persistent INVALID decides (as at HEAD - these 6 pass on HEAD too; they are regression guards for the OQ-19 order).
- test_a_damaged_plan_with_a_fabricated_registration_file_is_invalid_never_the_b32_refusal[3 files x 4 damages] - 12.
- test_a_plan_naming_another_trial_is_the_f62_refusal_and_never_invalidates_this_trial[after-audit|after-opening x none|attest_start] - 4.
- test_a_transient_os_error_on_the_plan_read_refuses_with_no_row[after-audit|after-opening] - 2.
- test_a_re_read_that_differs_refuses_with_no_row[bad-then-other-bad|absent-then-intact|bad-then-intact] - 3.
- test_the_invalidation_never_recreates_a_vanished_s1_out - F6.6.
- test_control_before_any_journal_row_a_damaged_plan_is_still_a_plain_refusal[3] and
  test_control_before_any_journal_row_a_changed_plan_passes_the_gate - pre-row controls (unchanged behaviour).
Every damage test asserts zero callbacks/captures/requests/valuations (Spies) and trips on any s1_stage.evaluate /
run / recover call. Every pytest.raises carries match=.

RED (t14b_red.txt): run on a clean `git archive HEAD research/s1` copy plus only this test file: 24 failed, 14 passed.

## Pre-existing tests
No pre-existing test was edited except test_s1_a3_matrix.py (above). Full-suite comparison: see the "Full suite"
section (appended after t14b_full.txt).

## Full suite (t14b_full.txt) vs base
**5147 passed, 7 skipped, 0 xfailed in 4224.20s (1:10:24)** = base 5083 passed + 26 released holds + 38 new tests;
the 7 skips are the NVS-1 holds, unchanged. No pre-existing test changed outcome or was edited (other than the
matrix markers above). One pre-existing matcher was kept by wording the new refusal like the F4 table's
(test_s1_t12_a3_a8.py[plan_edited_after_audit]: `stage audit: .*INVALID \(stage-replaced\)`; its outcome, INVALID
stage-replaced, is the same old and new - row 4 above). A first full run also had one failure unrelated to Task 14b,
test_s1_a3_locks.py::test_killed_owner_frees_the_lock (Windows released the killed child's handle late; passes in
isolation 5/5 and in the clean run).

## Fix round 1 (task-14b-review-verdict.md; progress.md rulings "T14b I-1", "T14b I-2")
Product: research/s1/s1_trial.py only (`_plan_after_rows` now takes the gate's rows; new `_holds_this_trials_audit`,
`_journal_invalid`, `_audit_state`). s1_common.py is unchanged by this round.

| # | Case (after any journal row) | Before fix round 1 (Task 14b round 0) | After | Class |
|---|---|---|---|---|
| F1 | another trial's plan.json swapped into THIS root (after-audit, after-opening, after-start-attest) | F6.2 refusal, no row; restoring resumes | after-audit: TRIAL-INVALID (stage-replaced, "names another trial_id"); from the opening on the legacy detector's persistent INVALID (registration-artifact) decides first; restoring never resumes | intended (ruling T14b I-1) |
| F2 | another trial's genuine whole root gated under this trial's mailbox (after-audit, after-opening) | F6.2 refusal, no row (56f8cb2 after the opening: TRIAL-INVALID of this trial) | unchanged: F6.2 refusal, no row, this trial ACTIVE (regression guard) | unchanged |
| F3 | OSError reading this trial's audit intent.json / prepared.json / members while plan.json names another trial | (decider did not exist) F6.2 refusal | refusal "... this trial's audit commitment unreadable (<type>) ... refused with no row" | intended |
| F4 | s1_out/stage.lock next to a deleted / unparseable plan.json (after-audit, after-opening) | legacy refusal "a stage publication is in progress or was interrupted (s1_out/stage.lock)", no row; resumes (also at 56f8cb2) | TRIAL-INVALID (stage-replaced): a legacy refusal is kept only when the journal now holds a TRIAL-INVALID | intended (ruling T14b I-2) |
| F5 | the INVALID message | "... F4 table CREATED, F4.8, F6.2 ..." | "... the audit stage is at <CREATED/PREPARED/INTENT/no row>; F4.1, F4.8, F6.2 ...", record gains audit_state | intended (M-1) |
| F6 | s1_out vanishes between the LOST check and the plan reads | TRIAL-INVALID (stage-replaced) | TRIAL-INVALID (LOST), "s1_out is gone under an open trial with journal rows" (F6.6 precedence) | intended (M-3) |

Test changes:
- **intended (ruling T14b I-1 amends brief item 2):** test_a_plan_naming_another_trial_is_the_f62_refusal_and_never_invalidates_this_trial[4]
  is replaced by test_a_plan_naming_another_trial_id_in_this_trials_own_root_is_invalid[4] - same four cases (a plan
  edited to another trial_id in this trial's own root, with or without a fabricated attest_start.json, after-audit /
  after-opening); old expectation F6.2 refusal + resumes, new INVALID + never resumes. The genuine-foreign-root
  outcome the old test protected is now asserted by test_fx1_another_trials_genuine_root_... on real foreign roots.
- **new (13):** test_fx1_another_trials_plan_swapped_into_this_root_is_invalid_and_never_resumes[3],
  test_fx1_another_trials_genuine_root_is_refused_and_never_invalidates_the_open_trial[2],
  test_fx1_an_os_error_reading_this_trials_audit_commitment_refuses_with_no_row,
  test_fx1_a_legacy_stage_lock_next_to_a_damaged_plan_never_pre_empts_the_invalid[4],
  test_fx1_a_live_audit_owner_at_intent_pending_for_an_intact_plan_invalid_for_a_damaged_one[2],
  test_fx1_s1_out_vanishing_between_the_plan_reads_is_lost_not_stage_replaced.
- **fixture:** the module snapshot fixture also builds two more trials (foreign-after-audit, foreign-after-opening),
  each with its own mailbox; `_copy` takes a name and an optional mailbox switch. No oracle change.
- RED: t14b_fix1_red.txt (10 failed, 3 passed on the round-0 tree; the after-opening genuine-root guard fails on
  56f8cb2). GREEN: t14b_fix1_green.txt. Exhaustive after-audit subset: t14b_fix1_matrix_after_audit.txt (3066 passed).

Residual (disclosed, F8.1 class): a plan swapped in AND every journal-bound audit artifact of this trial deleted from
the root (staging intent.json/prepared.json, or all committed audit members) reads as a foreign root: the F6.2
refusal with no row. Restoring only the plan then still meets the F4 table (intent.json/prepared.json missing:
INVALID); only a byte-for-byte restoration of everything resumes.

Fix-round-1 full suite (t14b_fix1_full.txt): **5160 passed, 7 skipped, 0 xfailed in 4270.72s (1:11:10)** = 5147 +
13 new fix-round tests (the 4 replaced foreign-in-own-root tests keep their count). The 7 skips are the NVS-1 holds.
No other pre-existing test changed outcome.
