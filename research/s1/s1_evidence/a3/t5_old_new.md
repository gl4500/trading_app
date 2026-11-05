# Task 5 old -> new

Classes (plan TDD discipline step 4 and the Task 5 brief Step 7):
- **FX** fixture incompatibility: the conftest or a test-local flow/helper is migrated; assertions unchanged.
- **I-F6.4** intended (F6.4): bundle mismatch after any journal row is INVALID (bundle) + local abort.
- **I-F0.6** intended (F0.6/F1 + OQ-19): a committed TRIAL-INVALID refuses every command with no work (re-entry,
  restored files, the score after its own detector committed the violation).
- **I-F7.1** intended (F7.1/F6.1/OQ-5): one ACK of each kind per trial; ACKs are built by `s1_trial.token` and
  verified field by field; an ACK created before its predecessor ACK or its journal row refuses the chain.
- **I-E4.3** intended (E4.3): a malformed official ACK candidate refuses its trial (attributable) or all trials.
- **TIGHT** carry-forward (Task 4 review / B3): a bare `pytest.raises(SystemExit)` given its exact reason.
- **Regression**: none. Every failure seen in the full runs was classified into one of the classes above; the only
  product changes made in response to full-suite failures are the deviations D6/D7/D8 (report), each a fix in
  Task 5's own new code.

The Task 4 red list (640 cases, one cause) is closed by the conftest migration (FX-1..FX-4). No assertion was
edited for a fixture incompatibility.

## conftest.py (FX)
- FX-1 `s1_plan_audit(..., journal=True)`: appends the audit stage's synthetic STAGE-INTENT / PREPARED / CREATED rows
  (brief; Task 9 replaces them). `journal=False` = no journal row.
- FX-2 `s1_state` / `s1_register`: OPENING-ACK after the opening checkpoint; RUN-ACK via `s1_ack` (was
  `s1_mailbox(..., r.run_token(root), ...)`); PREREG-ACK after `do_prereg`.
- FX-3 `s1_state(score_ready)`: synthetic TRIAL-STOP whenever the trial has ended (STOPPED, TIMEOUT **or
  NO-VALID-SEAL**; deviation D4), ACQUIRE-ACK after the final-plan block (also for NO-VALID-SEAL), SCORE-ACK via
  `s1_ack`.
- FX-4 new helpers: `s1_no_network` (autouse), `pytest_ignore_collect` (historical probes), `Spies`, `s1_jappend`,
  `s1_ack` (brief); `s1_reack` (re-issue an ACK of a kind: removes the open trial's existing ACK(s) of that kind from
  the tmp mailbox, then posts the token), `s1_finalize` (PREREG-ACK / TRIAL-STOP / ACQUIRE-ACK for flows that end the
  trial outside `s1_state`), `s1_score_refused` (asserts the score's INVALID refusal and returns the unit-level
  `_score` record so the score's own integrity-reason assertions keep running).

## test_s1_connected.py
- test_connected_lifecycle_matches_independent_oracle[4 cases] (FX + I-F7.1): its hand-built flow gains the audit
  stage's synthetic rows after `do_audit`, the OPENING-ACK after the opening seal, `s1_ack` RUN-ACK and PREREG-ACK,
  a synthetic TRIAL-STOP before `attest_stop`, `s1_ack` ACQUIRE-ACK (old: `k.ACQUIRE_ACK.format(...)`, removed in
  Task 4 - the L453 carry-forward) and `s1_ack` SCORE-ACK. Assertions unchanged.

## Re-posted ACKs: `s1_mailbox(root, id, <kind>_token(root), at)` -> `s1_reack(root, id, "<KIND>", at)` (I-F7.1)
Old: a second ACK of a kind was posted next to the fixture's; new: at most one per trial (a second one refuses every
command, "2 S1-SCORE-ACK ... escalate"), so the test's ACK replaces the fixture's. Times unchanged unless listed below.
test_s1_bridge_8b.py:156,206 · test_s1_checkpoint_7b.py:246,427 · test_s1_run.py:360,568,583,601,725,736,747,748,
760,779,1093,1109,1280,1382,1561 · test_s1_t12_a2.py:102,118,168,186 · test_s1_t12_a3_a8.py:248,266 ·
test_s1_t12_a7.py:101 · test_s1_t12_a9.py:193 · test_s1_t12_fix2_b2.py:223 · test_s1_t12_fix2_b3.py:285 ·
test_s1_t12_fix3.py:425,537 · test_s1_t12_mutant_followups.py:364 · test_s1_t12_mutant_survivors.py:239 ·
test_s1_t12_reporting.py:34 · test_s1_task11.py:133,480 (line numbers of the base file f5f7f83).

## test_s1_run.py
- test_prereg_refusals_write_nothing[ack]: match "ack" -> "'bad' is not the trial's S1-RUN-ACK" (I-F7.1: the RUN-ACK
  is the trial's one ACK, F6.5).
- test_early_score_ack_while_running_is_refused_with_no_output: old refusal "RUNNING|not strictly after"; new
  `t.Refusal` "S1-SCORE-ACK early: created not after its predecessor" (I-F7.1, F6.1: created before the
  ACQUIRE-ACK); then the SCORE-ACK is re-issued (`s1_reack`, after the ACQUIRE-ACK) and scores NO-VALID-SEAL as before.
- test_run_ack_not_strictly_after_start_attestation_is_refused: unchanged refusal; the proper RUN-ACK is re-issued
  with `s1_reack` before the positive prereg (one RUN-ACK per trial).
- test_score_ack_created_while_running_is_refused_after_the_stop, ..._strictly_after_the_stop_with_a_final_manifest
  _scores, ..._before_the_no_valid_seal_window_end_is_refused, test_cr_no_valid_seal_end_when_the_deadline_is_not_a
  _session: old refusal from the legacy end check (SystemExit "SCORE-ACK"); new `t.Refusal` "created not after its
  predecessor" (I-F7.1: under the A3 chain a SCORE-ACK before the ACQUIRE-ACK cannot exist), PLUS the legacy end
  check asserted at unit level (`r._pre_reserve_gate(out, {created_utc})` -> "is not strictly after the trial's
  end"), so its CR/mutant kills are kept. Positive steps re-issue the SCORE-ACK after the ACQUIRE-ACK.
- test_score_ack_after_the_stop_but_before_any_final_manifest_is_refused: the SCORE-ACK time STOP_CLOSE+1h ->
  `st_["now"]` - 1 day (after the ACQUIRE-ACK, F6.1); the refusal ("final") is unchanged.
- test_cr_attest_start_statement_receipt_and_clock: last step match "ABORTED-INVALID" -> `t.Refusal`
  "trial INVALID (reason/registration-artifact)" (I-F0.6).
- test_cr_attest_stop_statement_and_bad_seal: the statement checks move after `s1_state` (I-F0.6: the gate is the
  first statement, so with no trial they refuse "zero open trials" first); same "statement" match.
- test_fr1_running_status_compared_by_value_at_the_score_gate: `s1_finalize` (FX) and the clock moved after the
  fixture's TRIAL-STOP row (`stop_attested_at` + 1 day; with final=False the fixture's `now` is START-12h); the
  refusal "still RUNNING" is unchanged.
- TIGHT: test_mismatched_or_duplicate_acks_make_no_request_no_output (`t.Refusal` "'wrong-id' is not the trial's
  S1-SCORE-ACK"); test_second_score_refused_and_nothing_overwritten and
  test_score_failure_inside_the_attempt_is_preserved_as_aborted ("an attempt already exists; one attempt only");
  test_score_ack_with_stale_hash_is_refused_with_no_output (`t.Refusal` "S1-SCORE-ACK score-ack: ['<field>'] differ",
  field per edit; old: token-line inequality, I-F7.1).
- I-F0.6 via `s1_score_refused` (old: the score command recorded ABORTED-INVALID with the asserted reason; new: the
  score's legacy detector commits TRIAL-INVALID, the score refuses with no reservation and no record, and the same
  reason assertions run on the unit-level `_score` record): test_score_seal_or_receipt_violation_is_invalid[row,
  receipt, capture], test_malformed_seal_is_recorded_as_aborted_invalid_not_refused_forever,
  test_cr_malformed_seal_without_final_manifest_is_still_scored_invalid (+ unit `_pre_reserve_gate`: no final
  manifest demanded), test_cr_each_prereg_binding_alone_is_checked[6], test_cr_prereg_start_or_calendar_alone_is
  _checked[4], test_cr_incomplete_audit_is_a_recorded_reason_not_a_score_error, test_cr_plan_key_error_is_a_recorded
  _reason, test_cr_duplicate_seal_is_a_bad_seal_record_reason, test_fr1_unreadable_seal_rows_are_a_bad_seal_record
  _reason.

## test_s1_bridge_8b.py
- test_bridge_row_edited_then_scored_is_aborted_invalid: `s1_finalize` before the re-issued SCORE-ACK (FX: the
  checkpoint-abort flow ends outside `s1_state`).
- I-F0.6 via `s1_score_refused`: test_score_with_a_seal_missing_its_bridge_record_is_aborted_invalid,
  ..._bridge_hash_differing_from_the_final_ledger_..., ..._bridge_record_not_matching_its_rows_...

## test_s1_checkpoint_7b.py
- test_score_ack_binds_the_final_snapshot_report_and_an_edit_after_the_ack_is_refused: match "ack lacks the
  standalone line" -> `t.Refusal` "S1-SCORE-ACK score-ack: ['final_snapshot_sha256'] differ" (I-F7.1 field by field).

## test_s1_collect.py (TIGHT)
- test_final_requests_every_symbol_bars_and_full_history (second do_final): "an attempt already exists; one attempt
  only". test_final_lag_refused_before_reserving: "acquisition lag not met".

## test_s1_t12_a2.py (I-F0.6 via `s1_score_refused`)
test_a2_attest_stop_binds_the_persisted_stop, test_a2_integrity_of_the_frozen_slices_is_enforced_at_score[3],
test_a2_no_valid_seal_is_terminal_persisted_and_never_rescued_by_a_late_seal.

## test_s1_t12_a3_a8.py
- test_a3_checkpoint_bundle_mismatch_is_a_persistent_abort_before_any_helper_or_capture (I-F6.4/I-F0.6): the first
  checkpoint now refuses INVALID (bundle) from the gate (abort fields unchanged); the restored re-entry old = a
  post_stop capture reporting ABORTED-INVALID, new = `t.Refusal` "trial INVALID (reason/bundle)" with zero callbacks
  and the same aborted.json.
- test_a3_opening_checkpoint_bundle_mismatch_refuses_with_zero_callbacks_and_no_abort (I-F6.4, the brief's named
  class): old = refusal, no aborted.json; new = INVALID (bundle) + aborted.json reason bundle, zero callbacks, no
  capture (the fixture carries the audit stage's rows; the no-row refusal is test_s1_a3_gate row 144).
- test_a3_score_bundle_mismatch_aborts_reserves_nothing_and_restoration_scores_aborted_invalid (I-F6.4/I-F0.6):
  restoration old = an ABORTED-INVALID score naming the bundle; new = `t.Refusal` "trial INVALID (reason/bundle)",
  no score.
- test_a3_score_checks_bundle_consistency_across_every_artifact[seal] (I-F0.6): an edited seal is a registration
  artifact: refusal, then the unit-level `_score` record names the bundle (other params unchanged).
- test_a3_final_acquisition_verifies_the_bundle_before_any_request (I-F7.1/I-F6.4): the fixture's one ACQUIRE-ACK
  "acq-ack" is used (old: a second ACQUIRE-ACK "acq"); match "bundle" -> `t.Refusal` "INVALID (bundle)".

## test_s1_t12_a5_a6.py
- test_a6_a_dropped_session_relative_to_the_pinned_listing_refuses (I-F0.6): the score after the checkpoint's
  registration-artifact abort: old ABORTED-INVALID naming the calendar; new `t.Refusal` "trial INVALID
  (reason/registration-artifact)", no score.

## test_s1_t12_fix2_b3.py
- test_b3_the_opening_changed_after_the_opening_but_before_the_run_ack_is_a_persistent_abort: restored re-entry
  match "ABORTED" -> `t.Refusal` "trial INVALID (reason/registration-artifact)" (I-F0.6).
- test_b3_a_registered_artifact_changed_or_deleted_then_restored_stays_invalid[16]: restored re-entry old = a
  checkpoint report (seal not written, ABORTED-INVALID); new = `t.Refusal` "trial INVALID
  (reason/registration-artifact)" (I-F0.6).
- test_b3_a_registration_artifact_violation_at_the_score_is_persisted_and_prices_nothing (I-F0.6, the brief's named
  example): old = "ABORTED-INVALID report, zero prices"; new = "TRIAL-INVALID committed, score refused, zero prices"
  (asserts the TRIAL-INVALID reason/registration-artifact row, aborted.json, no score/, no valuation call).

## test_s1_t12_fix2_mutants.py
- test_mt_attest_stop_reverifies_the_run_ack (FX): the test moves the RUN-ACK's `created` after START; its
  successor PREREG-ACK (new in the fixture) is moved too, so the ACK chain stays intact (F6.1) and the legacy
  "registration not verified" timing check is what refuses (unchanged match).

## test_s1_t12_fix3.py
- test_c2_deleting_an_artifact_with_its_registry_record_is_a_persistent_abort[9] and
  test_c2_probe_deleting_prereg_and_its_registry_record_then_restoring_never_resumes: restored re-entry -> `t.Refusal`
  "trial INVALID (reason/registration-artifact)" (I-F0.6).
- test_i1_the_score_refuses_while_a_success_lacks_its_seal: `s1_finalize` before the SCORE-ACK (FX); "RUNNING"
  refusal unchanged.
- test_m3_a_registration_abort_before_the_final_snapshot_still_yields_a_recorded_score (I-F0.6): old = the score
  records ABORTED-INVALID; new = `t.Refusal` "trial INVALID (reason/registration-artifact)", zero valuation calls, no
  score/.
- TIGHT: test_c2_retro_the_run_ack_witnesses_the_attestation: "registration artifact".

## test_s1_t12_fix8.py
- test_h_every_subset_of_the_editable_registration_files_tampered_is_the_persistent_abort[189] (I-F0.6): restored
  re-entry old = a checkpoint report with stop ABORTED-INVALID (registration artifact); new = `t.Refusal` "trial
  INVALID (reason/registration-artifact)"; aborted.json unchanged (first wins).
- test_h_a_run_ack_carrying_the_bundle_is_a_registration_even_before_the_opening (I-E4.3): the forged official line
  "S1-RUN-ACK plan_sha256=..." has no trial_id: an unattributable malformed official candidate, so the gate refuses
  every trial-bound command ("unattributable malformed official ACK line"), zero callbacks; old = a persistent
  registration-artifact abort.

## test_s1_t12_mutant_followups.py
- test_mf_the_score_ack_binds_the_persisted_stop (I-F0.6 + I-F7.1): stop.json edited is a registration artifact:
  `s1_score_refused`; the binding is asserted on the posted SCORE-ACK's `stop_sha256` field vs `artifact_fields`
  (old: "ack lacks the standalone line").
- I-F0.6 via `s1_score_refused`: test_mf_the_score_reverifies_the_run_token_bindings,
  test_mf_an_edited_opening_books_file_is_aborted_invalid_at_score.

## test_s1_t12_mutant_survivors.py
- test_ms_an_audit_ack_message_without_the_exact_audit_token_refuses (FX): `s1_plan_audit(journal=False)` - the test
  rewrites the AUDIT-ACK body, which is every journal row's genesis (F0.2); assertion unchanged ("audit token").
- test_ms_a_run_ack_message_not_carrying_the_exact_run_token_refuses (I-F7.1): expected problems
  ["the RUN-ACK does not carry the RUN token of the current artifacts"] -> ["RUN-ACK runner_sha256 does not match"].
- test_ms_stop_json_changed_after_the_attestation_is_named (I-F0.6 via `s1_score_refused`).

## test_s1_task11.py
- test_i1_prereg_and_run_ack_bind_the_toolchain (I-E4.3): the bundle-less "old-ack" line in the official channel
  is a malformed candidate naming this trial: `t.Refusal` "malformed official ACK line in old-ack names this trial";
  the test then withdraws its tmp message and the proper prereg runs (old: a bare SystemExit, then prereg).
- `_acquire_ready` (FX): also removes the fixture's SCORE-ACK (before the acquisition there is none), so the
  ACQUIRE-ACK can be re-issued without breaking the chain.
- test_i4_acquire_ack_binds_the_stop_attestation_and_do_final_records_the_plan (I-F7.1): `s1_reack`, asserting the
  re-issued line equals the token (old: a second ACQUIRE-ACK).
- test_i4_do_final_rechecks_the_stop_before_reserving[3] (TIGHT + FX): each breakage gets its reason
  ("ABORTED-INVALID", "not the plan derived from the stop seal", "not strictly after the stop attestation"); the
  "ack before attestation" ACK moves from attestation-1 min to attestation-500 ms, still after the TRIAL-STOP row it
  references (F6.1), so the attestation order is what refuses.
- test_m4_collectors_refuse_a_client_that_may_follow_redirects[2] (I-F0.6): run under an open trial (gate first);
  same "follow_redirects" match; "nothing under s1_out changes" replaces "no s1_out".
- I-F0.6 via `s1_score_refused`: test_i1_score_requires_every_seal_and_itself_to_match_the_prereg_toolchain,
  test_m2_capture_report_naming_a_seal_that_is_not_on_disk_is_aborted_invalid[2].

## Bare `pytest.raises(SystemExit)` re-check (Task 4 review carry-forward)
| site (base f5f7f83) | old | new |
|---|---|---|
| test_s1_run L73 | bare | `t.Refusal` "'wrong-id' is not the trial's S1-SCORE-ACK" |
| test_s1_run L369 | bare | "an attempt already exists; one attempt only" |
| test_s1_run L481 | bare | "an attempt already exists; one attempt only" |
| test_s1_run L688 | bare | `t.Refusal` "S1-SCORE-ACK score-ack: ['<field>'] differ" |
| test_s1_collect L282 | bare | "an attempt already exists; one attempt only" |
| test_s1_collect L453 | bare | "acquisition lag not met" |
| test_s1_task11 L485 | bare | per-breakage reason (above) |
| test_s1_t12_fix3 L556 | bare | "registration artifact" |
Each was confirmed to fail for its intended reason (the tightened match passes; t5_full.txt).

---
# Fix round 1 (review task-5-review-verdict.md; controller rulings in progress.md)

New tests (test_s1_a3_gate.py; RED in t5_fix1_red.txt): test_total_loss_then_outage_then_mailbox_back_never_resumes
(the reviewer's I-1 scenario), test_total_loss_with_a_bundle_mismatch_is_lost_and_never_recreates_s1_out,
test_no_gate_refusal_writes_into_a_missing_s1_out[4], test_an_invalid_trial_adds_no_repeat_invalid_rows_on_re_entry
(M-3), test_the_gate_is_the_first_call_of_every_command[10] (M-5), test_a_raw_context_without_slot_gate_or_stage
_check_fails_closed (M-6), test_final_snapshot_after_its_own_detection_captures_nothing (I-2).

## FX (fixture incompatibility, assertions unchanged)
- M-6 (`decide` now fails closed on a missing slot_gate / stage_check at step 5): the test contexts that relied on
  the old fail-open default now supply `stage_check=lambda rows, s, i: None` explicitly: conftest `s1_jappend`,
  test_s1_a3_journal.py `OPEN`, test_s1_a3_precedence.py `ctx`, test_s1_a3_trial.py `stage_row`. No assertion and no
  map-row outcome changed (steps 2-4 never read these callables; every Task 2 precedence case still passes).

## I-F8.1 (review I-2: run_final_snapshot re-gated after its legacy detector)
The fence logic moved, unchanged, into `s1_checkpoint._final_snapshot_capture` (run_final_snapshot = the gates + the
re-gate + that call). The 6 CR-survivor fence tests in test_s1_checkpoint_7b.py:
- test_cr_final_snapshot_refuses_on_a_bad_seal_record[{}], [[]], [dup]
- test_cr_final_snapshot_records_a_malformed_seal_fence_as_a_violation[KeyError], [ValueError], [TypeError]
Old: `run_final_snapshot` captured and either refused "bad seal record" ({}/[]) or recorded the violation
(dup / malformed fence). New: (1) the command now refuses `t.Refusal` "trial INVALID (reason/registration-artifact)"
with no final_snapshot/ (the tampered seal is a registration artifact its own detector commits); (2) the same fence
assertions, unchanged ("bad seal record"; "zz.json … frozen slices"; `fence_checked` and "bad seal record: <kind>"),
run on `_final_snapshot_capture` (unit level, after every gate). Map rows: none of these are map rows; no map-row
outcome changes.

## I-3 (review): test_s1_collect.py
- test_final_lag_refused_when_calendar_lacks_three_later_sessions: old = a second ACQUIRE-ACK "f9" (passed for the
  WRONG reason: "2 S1-ACQUIRE-ACK ... escalate"). New = `s1_reack` (one ACK per kind) and the command's real reason
  asserted: "registration artifact(s) missing or changed: ['prereg.json changed" (the test edits prereg.json, a
  registered artifact since B3); the calendar/lag rule itself asserted at unit level:
  `k._earliest_acquire(<4-day calendar>, stop_day)` -> "cannot place the 3rd session after the stop".
- test_final_ack_binds_prereg (I-8): bare -> "registration artifact(s) missing or changed" (the real reason; the
  edited prereg is a registered artifact, pre-dating Task 5), plus a unit-level assertion that the ACQUIRE-ACK's
  `prereg_sha256` no longer equals `artifact_fields`.

## TIGHT (every remaining bare `pytest.raises(SystemExit)` in the migrated files gets `match=`)
Each reason was taken from an instrumented run (a scratchpad pytest plugin logging the message every bare site
caught), then checked against the test's intent. 55 sites in 9 files:
- test_s1_checkpoint_7b.py:305 `^2$` (argparse usage exit).
- test_s1_collect.py (14): 86 "zero open trials" (the test's inexact "approve, roughly" message is no ACK
  candidate, so no trial exists: the A3 reason for "refuses without the exact ACK"); 97/364 "an attempt already
  exists"; 128 "planned START has passed"; 137 "ack is in the future"; 142 "is not a codex->claude
  experiments-prereg message"; 145 "ack lacks the standalone line" (c.ack unit); 293 "'f3' is not the trial's
  S1-ACQUIRE-ACK"; 360/385/420 "audit: ABORTED (Structural)"; 404 "audit: ABORTED (RuntimeError)"; 510 see I-3;
  525 "final: ABORTED (Structural)".
- test_s1_run.py (4): 226/307 "the statement must be exactly START_/STOP_STATEMENT"; 228 "START attestation already
  recorded"; 256 "prereg already recorded".
- test_s1_t12_a3_a8.py (3): 231 "trial INVALID (reason/bundle)"; 420 and 478 per breakage (`WHY420`, `WHY478`).
- test_s1_t12_fix2_b2.py:181, fix2_b3 (135,171,190,205,216,230,255,265), fix3 (249,269,287,304,323,337,349,570,586,
  604,640,652,676), fix8 (53,93,149,235): "registration artifact(s) missing or changed".
- fix2_b3:118, fix3:319, fix3:466, fix8:208: "inconsistent pre-registration state". fix2_b3:242 "mailbox
  unreadable". fix3:538 "registration not verified". test_s1_task11.py:566 "is not a codex->claude
  experiments-prereg message".
Sites found passing for a reason other than their test's stated intent (all pre-date Task 5 except I-3, which
Task 5 caused): see the report's fix-round-1 "wrong reason" list.

## Minor
- M-1: test_s1_a3_codex_probes.py imports `s1_jappend` at the top (`# noqa: F401`, Task 7 appends; P41).
- M-7: codex_probes_historical/README.md added; SHA256SUMS regenerated (14 entries, README included).
