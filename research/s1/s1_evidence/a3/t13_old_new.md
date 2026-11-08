# A3 Task 13 - old -> new (full suite vs base 20772fb: 1774 passed, 1 skipped)

Discovery: one full-suite pass after Step 4 (six parallel shards with separate basetemps, scratchpad only - not
evidence) gave 38 failures in 12 pre-existing files. Each is classified below. The clean evidence run is
`t13_full.txt`. No requirement-map row's expected outcome changed.

Classes: **intended** (the Task 13 spec change named in the brief's Step 6), **held** (the test needs a ruling; skip
with a reason), **un-held**, **new**.

## Intended: OQ-28 AMEND - `_score`'s ABORTED-INVALID is TRIAL-INVALID (registration-artifact), report in staging

Old: `r.score` returned (and wrote to s1_out/score/s1.json) the ABORTED-INVALID report. New: the score stage
refuses "stage score: INVALID (registration-artifact)" after the verdict repeats on a second computation; the
report stays in the score staging, with no PREPARED and no s1_out/score. Migration: the call becomes
`conftest.s1_score_invalid(root, ack)`. It asserts the refusal, exactly one TRIAL-INVALID with that reason, no
PREPARED and no s1_out/score, and returns the staged report. Every assertion on the report's verdict and reasons is
unchanged.

- test_s1_run.py: test_score_aborted_checkpoint_is_invalid_and_unpriced; test_score_runner_changed_since_prereg_is_invalid;
  test_score_ack_before_the_recorded_abort_is_refused (its last line); test_cr_runner_hash_differing_upward_is_invalid;
  test_cr_opening_ledger_error_is_named.
- test_s1_run.py::test_cr_ledger_errors_name_which_ledger: intended, plus an input change for the N1 confirmation. The
  flaky `_carry_in` raised only on its 2nd call overall, so the second computation was clean and the score refused
  "did not repeat on a second computation" (the confirm-on-re-read working as designed). Its fault is now on every
  even call (the final-ledger call of each computation); the oracle is unchanged.
- test_s1_checkpoint_7b.py: test_final_snapshot_records_a_backdated_row_and_score_is_aborted_invalid;
  test_score_with_a_tampered_final_snapshot_projection_is_aborted_invalid;
  test_score_is_aborted_invalid_when_the_report_is_gone_but_an_ok_attempt_exists[missing, unreadable];
  test_score_is_aborted_invalid_when_another_attempt_is_ok_too.
- test_s1_t12_fix2_b2.py::test_b2_the_score_rechecks_every_seals_binding_and_invalid_makes_zero_valuation_calls
  [observed-B, missing, malformed]. The `_score` helper call was inlined (the same clock and re-ACK), then the
  helper. The valuation spy is still asserted empty.
- test_s1_t12_a9.py::test_a9_every_non_numeric_disposition_makes_no_valuation_call[ABORTED-INVALID]. The spies are
  unchanged.
- test_s1_task11.py::test_m7_every_report_kind_carries_restarts_and_the_quantity_bridge[aborted]: the staged report
  carries restarts and the quantity bridge.
- test_s1_bridge_8b.py::test_bridge_row_edited_before_the_final_snapshot_is_aborted_invalid.
- test_s1_t12_a3_a8.py::test_a3_score_checks_bundle_consistency_across_every_artifact[final_snapshot]: a new
  `final_snapshot` branch of its except clause (the refusal text, then the staged report).

## Intended: F4.9 score abort - a computation error is INVALID (score-aborted), record in staging

Old: "score ABORTED ...; attempt preserved, see s1_out/score/s1.json", with the retry refused "an attempt already
exists". New: `s1_score_invalid(..., reason="score-aborted")`, and the retry is the gate's INVALID refusal
("trial INVALID (reason/score-aborted)").

- test_s1_run.py::test_score_failure_inside_the_attempt_is_preserved_as_aborted.
- test_s1_run.py::test_report_is_serialised_before_the_output_file_is_opened. Also an input fix: the stage calls
  `_score(out, mailbox)` as the c9b4322 command did, so the monkeypatched lambda takes `mailbox=None`. The test now also
  asserts the staged reason names TypeError (the unserialisable object).

## Intended: the one-attempt score is the stage's one INTENT ("score/ already exists" -> "already CREATED")

- test_s1_run.py::test_second_score_refused_and_nothing_overwritten: the match is now
  `stage score is already CREATED: re-entry refused \(F1\)`, and all_hashes(s1_out) is still unchanged.
- test_s1_connected.py::test_connected_lifecycle_matches_independent_oracle[chop-FAIL-None, trend-SHADOW PASS-None,
  chop-FAIL-buy, chop-FAIL-receipt], step 12: the same match; tree_hashes is still unchanged.

## Intended: the reservation is staged (F4.2)

- test_s1_run.py::test_score_reserves_before_any_priced_computation: the spy checks the staged
  `s1_staging/<trial>/score/score/attempt.json` instead of s1_out/score/attempt.json. The property (reserved before
  the first priced call) is unchanged.

## Intended: OQ-16 - the SCORE-ACK-bound final snapshot is bound evidence

- test_s1_checkpoint_7b.py::test_score_ack_binds_the_final_snapshot_report_and_an_edit_after_the_ack_is_refused. Old:
  the Refusal "['final_snapshot_sha256'] differ". New: "the SCORE-ACK-bound final snapshot is missing or changed:
  INVALID (registration-artifact)", with the TRIAL-INVALID asserted (s1_first_invalid) and no s1_out/score. This is the
  brief's Step 6 OQ-16 bullet.

## Intended: OQ-16 - `--final-snapshot` runs only in STOPPED, and never finalizes or appends a slot row

- test_s1_checkpoint_7b.py::test_final_snapshot_refuses_without_prereg_and_while_running. Both refusals are now
  "final snapshot refused: the trial is not STOPPED (OQ-16)": the ACTIVE no-prereg case (old "prereg"), because the
  state check is the command's first step after the gate, and the ACTIVE prereg'd case (old "RUNNING").
- test_s1_checkpoint_7b.py::test_final_snapshot_after_a_recorded_abort_is_taken. Old: a capture on an ACTIVE trial
  with a hand-written local aborted.json. New: refused "not STOPPED (OQ-16)", with no final_snapshot/. The test name is
  kept and the docstring records the change.
- test_s1_a3_finalizer.py::test_final_snapshot_trial_state_refuses_a_damaged_tree_without_a_traceback (Task 7 N-1).
  `_trial_state` no longer calls finalize_pending, so it never meets the damaged tree. The property ("a SystemExit
  naming registration-artifact, never an escaping exception") is kept at the command: `run_final_snapshot` meets the
  damaged tree in its gate (the F3 evidence table). The test also asserts no final_snapshot/.

## Intended: ENFORCED

- test_s1_a3_stage.py::test_seal_files_on_disk_are_evaluated_once_the_seal_family_is_enforced: the expected ENFORCED
  set gains "score" (brief Files: `ENFORCED |= {"score"}`).

## Held (7): the NO-VALID-SEAL score path (report concern 1, awaiting a ruling)

Each test is `skip(reason=conftest.S1_NVS_HELD)`. All 7 fail with "stage score: STAGE-INTENT REFUSE with no row:
stage score: predecessor final is not CREATED (F1)". A NO-VALID-SEAL trial has no stop_attest (attest_stop refuses a
status other than STOPPED or TIMEOUT), so it has no final_plan or final either, and TABLE["score"]["pred"] == "final".
OQ-28 lists NO-VALID-SEAL among the scores to commit normally. That is a spec/plan conflict, so it is not decided
here.

- test_s1_run.py: test_score_no_valid_seal_is_never_fail; test_early_score_ack_while_running_is_refused_with_no_output;
  test_combined_abort_and_no_valid_seal_is_aborted_invalid; test_score_ack_before_the_no_valid_seal_window_end_is_refused.
- test_s1_checkpoint_7b.py::test_no_valid_seal_trial_can_take_its_final_snapshot (its snapshot half still works; the
  score half does not).
- test_s1_t12_a9.py::test_a9_every_non_numeric_disposition_makes_no_valuation_call[NO-VALID-SEAL] (pytest.skip in
  the body: the parametrization is shared).
- test_s1_task11.py::test_m7_every_report_kind_carries_restarts_and_the_quantity_bridge[no-valid-seal] (the same).

## Un-held (1)

- test_s1_a3_stop.py::test_in_flight_slot_started_before_the_stop_completes_but_never_enters_final_or_score (row 189;
  held since Task 11 for sampled_history). It has no pytest.raises. Two assertions were added: the history has
  exactly the keys rows and seals (an assertion, not a KeyError, on the RED), and the STOP's own line is in it (a
  non-vacuous oracle).

## New (31)

- test_s1_a3_score.py: 23 brief tests (rows 60, 63, 109, 118, 181, 182, 185, 191, 215, 218, 281, 282, 306, 307, 314,
  315) and 7 carry-forward tests.
- test_s1_a3_final.py::test_aborted_record_write_error_still_records_the_provider_structural_reason (Task 12 N-1).

## Brief Step 6 items that needed no change

- "A2.3/B3 -> F1/F0.6" (refused, no score, when the journal is INVALID): test_s1_t12_fix2_b3 `..._at_the_score_...`,
  test_s1_t12_reporting and test_s1_task11 m-7 already met this since A3 Task 5 (the gate refuses an INVALID trial).
  They pass unchanged; only m-7[aborted] changed, for OQ-28 above.

## Fix round 1 (task-13-review-verdict.md; full suite t13_fix1_full.txt: 1805 passed, 7 skipped)

The count change from the Task 13 suite (1799 passed, 7 skipped):
- +4 new tests:
  - test_second_computation_error_after_an_integrity_verdict_keeps_the_first_reasons;
  - test_pre_intent_sampled_history_error_is_a_refusal_not_a_traceback[ValueError, PermissionError, KeyError].
- M-5: 2 held tests un-held and split; their 2 new NVS halves are held. The skips stay at 7: the 5 still-held tests
  plus the 2 halves.

Classified changes:
- **Un-held, M-5 split**:
  - test_s1_run.py::test_early_score_ack_while_running_is_refused_with_no_output runs its early-ACK half. It gains a
    "no score stage rows" assertion (rows read through t.trials(t.scan())).
  - test_s1_checkpoint_7b.py::test_no_valid_seal_trial_can_take_its_final_snapshot runs its snapshot half.
- **Held, new NVS halves (S1_NVS_HELD)**:
  - test_s1_run.py::test_post_end_score_ack_scores_a_no_valid_seal_trial;
  - test_s1_checkpoint_7b.py::test_no_valid_seal_trial_scores_no_valid_seal.
- **Renamed, M-6**: test_s1_checkpoint_7b.py::test_final_snapshot_after_a_recorded_abort_is_taken is now
  test_final_snapshot_on_an_active_trial_with_a_local_abort_is_refused_oq16. Its body is unchanged.
- **Strengthened, I-1** (the observation must list _score's exact reasons):
  - conftest.s1_score_invalid now asserts the invalid/<seq>.json record for every caller (listed in the OQ-28 and F4.9
    sections above): its detail equals the TRIAL-INVALID row's, and its stage and reason. For registration-artifact
    it also asserts where == "score" and score_reasons == the staged report's reasons.
  - The row 306 test asserts the whole record.
- **Strengthened, M-3**: pinned regexes in test_s1_a3_score.py for the INVALID trial (row 115), row 281
  [receipt, snapshot-report], row 306, row 314 (plus the TRIAL-INVALID subject list) and the STOPPED test.
- **Strengthened, M-4**: the row 109 envelope asserts its input values.
- **Product, M-1**: the unconfirmed-verdict refusal text changes. It now names `first_computation_s1.json`, which is
  staged. test_unconfirmed_integrity_verdict_refuses_with_no_invalid pins the new text and the staged reasons.
- **Product, M-7**: no pre-existing test changed outcome.
