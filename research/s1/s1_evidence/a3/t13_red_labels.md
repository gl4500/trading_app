# A3 Task 13 - RED labels (t13_red.txt, t13_red_cf.txt)

## t13_red.txt - Step 3, against the Step 1 stub (base 20772fb + `s1_seal.sampled_history` returning `{}`)

Selection: `test_s1_a3_score.py` (the brief's tests, before the carry-forward tests were appended) and the un-held row
189 test `test_s1_a3_stop.py::test_in_flight_slot_started_before_the_stop_completes_but_never_enters_final_or_score`.
Result: **12 failed, 12 passed**. Every failure ends in an AssertionError or a pytest Failed (no import, name,
fixture, KeyError or OSError failure).

| test | RED outcome | label | why |
|---|---|---|---|
| test_lot_count_stop_reaches_a_numeric_score_with_no_invalid_row | AssertionError (:54, no `stage/score` CREATED) | B | the legacy score is no stage |
| test_six_month_stop_reaches_a_numeric_score_with_no_invalid_row | passed | ctrl | the legacy one-attempt score already reaches a verdict with no TRIAL-INVALID on a timeout stop |
| test_score_positive_path_isolated | AssertionError (:36, no score staging prepared.json) | B | no PREPARED commitment (C-a) |
| test_score_computation_error_is_invalid_score_aborted_with_no_numeric_score | AssertionError (:82, regex) | B | legacy: "score ABORTED ... see s1_out/score/s1.json", no TRIAL-INVALID |
| test_invalid_never_reaches_a_numeric_score | passed | ctrl | since A3 Task 5 the gate refuses an INVALID trial with no work (the brief's B-old no longer exists) |
| test_score_envelope_inputs_and_members | AssertionError (:36, no intent.json) | B | no INTENT envelope |
| test_score_ack_fields_are_verified[ok, wrong-final, wrong-prev, wrong-stop-line, head-forked] | passed (5) | ctrl | the legacy score already verifies the SCORE-ACK field by field (A3 Task 5); the cases pin those refusals with match= |
| test_score_member_changed_is_invalid | Failed (:138, DID NOT RAISE) | B | `score` not in ENFORCED: the gate never checks s1_out/score |
| test_damaged_receipt_or_final_snapshot_is_invalid_before_scoring[receipt] | passed | ctrl | the gate's opening tables already INVALIDate a changed opening_receipt.json |
| test_damaged_receipt_or_final_snapshot_is_invalid_before_scoring[snapshot-report] | AssertionError (:149, regex) | B | legacy: the SCORE-ACK field mismatch is a refusal, not INVALID (OQ-16) |
| test_damaged_capture_backup_is_invalid_before_scoring | passed | ctrl | the gate's F3 evidence table already INVALIDates a damaged QUALIFIED capture tree (A3 Task 7) |
| test_score_integrity_violation_persists_trial_invalid | Failed (:171, DID NOT RAISE) | B | legacy: ABORTED-INVALID written to s1_out/score, no TRIAL-INVALID (OQ-28) |
| test_non_integrity_dispositions_stay_valid[INSUFFICIENT, INCONCLUSIVE] | passed (2) | ctrl | as the brief labels row 307 |
| test_final_snapshot_missing_or_changed_is_invalid_not_a_fallback[missing, changed] | AssertionError (:198, regex) x2 | B | legacy: "no final snapshot" / ACK-field refusal, never INVALID (OQ-16) |
| test_final_snapshot_only_in_stopped | AssertionError (:209, regex) | B | legacy run_final_snapshot runs in ACTIVE and refuses later ("RUNNING"), after finalize_pending |
| test_sampled_history_is_canonical_and_fixed_at_the_stop | AssertionError (:231, `{}`) | B | the stub returns {} (OQ-29) |
| test_authorized_post_stop_prices_are_used_for_valuation | passed | ctrl | the legacy score already values with post-stop bars |
| test_s1_a3_stop.py::test_in_flight_slot_..._never_enters_final_or_score (row 189, un-held) | AssertionError (:281, `{}`) | B | the stub returns {} |

The brief expected rows 281 and 282 to fail on the legacy path. Of these, [receipt] and 282 pass: earlier tasks' gate
tables (A3 Tasks 7 and 10) already make both INVALID before the score runs. They are kept as ctrl oracles (they still
pin "INVALID before scoring, zero valuation spies").

## t13_red_cf.txt - carry-forward tests, against an export of HEAD 20772fb

The carry-forward tests were written after Step 4. Their RED was recorded against an untouched export of HEAD
(`git archive HEAD research/s1` into the scratchpad, with only the two test files copied in), so the old code is
exactly the committed one. Result: **7 failed, 1 passed**. Every failure is an AssertionError (regex) or a Failed.

| test | RED outcome | label | why |
|---|---|---|---|
| test_local_oserror_in_the_score_refuses_with_no_row_never_score_aborted | AssertionError (regex) | B | legacy: a PermissionError in the computation became "score ABORTED" |
| test_journal_outage_in_the_score_refuses_with_no_row_never_score_aborted | AssertionError (regex) | B | the same, for j.Outage |
| test_unconfirmed_integrity_verdict_refuses_with_no_invalid | Failed (DID NOT RAISE) | B | legacy: no second computation; the first verdict is written |
| test_aborted_record_write_error_still_records_the_anomaly_reason | AssertionError (regex) | B | legacy score: no stage |
| test_bound_snapshot_is_confirmed_on_a_second_read_before_any_invalid[differs-once, unreadable] | AssertionError (regex) x2 | B | legacy: the first read's mismatch is refused as an ACK field mismatch, with no second read |
| test_score_ack_binding_no_snapshot_with_a_report_on_disk_is_a_refusal | passed | ctrl | legacy and new both refuse (the new code keeps that refusal for an unbound report) |
| test_s1_a3_final.py::test_aborted_record_write_error_still_records_the_provider_structural_reason | AssertionError (regex) | B | Task 12 N-1: on HEAD the PermissionError on ABORTED.json escapes s1_stage.run bare; no TRIAL-INVALID |
