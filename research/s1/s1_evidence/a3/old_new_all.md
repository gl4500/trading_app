# A3 old -> new, all tasks (Tasks 1-14)

The union of `t1_old_new.md` .. `t14_old_new.md` (plan Task 14 Step 6). Each task's record is reproduced verbatim
below its heading, so every entry keeps the test id, old expectation, new expectation, spec clause and class exactly
as the reviewed task record states them; nothing is re-worded or re-classified here. The sha256 under each heading
is the source file's, at the time this union was generated.

Class legend (the three classes of the brief, and the task records' own labels that map to them):
- **intended**: intended, intended semantic change, B-old reversal, un-held (the hold's ruling arrived), new.
- **fixture**: fixture, fixture / test literal, setup, migration (FX-*), test-literal deviation, ctrl precondition.
- **regression-fixed**: a regression found by a task's own full run and fixed in that task (each named as such in
  its record, e.g. Task 7 fix round 1 "regression found by the first fix-round full run").
Labels outside these (held, disputed, oracle) are kept as the task record states them.


## Task 1 old -> new (intended semantic change)

Source: `a3/t1_old_new.md`, sha256 `daf1699c5be98c386788832dcbe0ac2db91a28efee7e705bef0295efc2fe9f1b`


test_s1_t12_a3_a8.py::test_a3_bundle_is_the_explicit_file_list_plus_the_three_document_hashes

- line 28-29, BUNDLE tuple:
  - old: `(..., "s1_gates.py", "s1_receipt.py", "s1_run.py", "s1_seal.py", "s1_snapshot.py")`
  - new: `(..., "s1_gates.py", "s1_journal.py", "s1_receipt.py", "s1_run.py", "s1_seal.py", "s1_snapshot.py")`
  - why: A3.1 (map row 2): every new s1_*.py is a listed bundle member; s1_journal.py is new in Task 1.
- line 90-92, docstring: "the sha256 of the v5 design, the spec and this addendum (the addendum's own hash included)"
  -> "the pinned document hashes (the v5 design, the spec, this addendum with its own hash, and every later pinned
  addendum and erratum)". why: DOC_PINS gains Addendum 3 (d9dd3759...) and Erratum 1 (b0346466...), map row 1.
- assertion values: unchanged (the test compares against c.DOC_PINS and BUNDLE, both updated).
- test name: unchanged (the plan and the Task 15 mutant map refer to it by this name).

## Task 2 old -> new

Source: `a3/t2_old_new.md`, sha256 `510ec568380fecd0366578c1009325ab865d25855f14f5379afb1431c90f77a9`


None. No existing test was edited, and no existing test failed in the full suite (t2_full.txt: 1201 passed =
1096 Task 1 baseline + 105 new in test_s1_a3_precedence.py). So there is no intended semantic change, fixture
incompatibility or regression to classify. The Task 1 journal tests (test_s1_a3_journal.py) pass unchanged on the real
precedence: their OPEN context supplies slot_times, stage_gate and slot_gate.

## Task 3 old -> new

Source: `a3/t3_old_new.md`, sha256 `2e3e1e24c07588b9fdc2ec9b10a7e8f38570115f081c23dc45270e9d2f0e6f14`


### research/s1/s1_tests/test_s1_t12_a3_a8.py (BUNDLE tuple)

Old:
```python
BUNDLE = ("e1_fetch.py", "e1_sim.py", "s1_books.py", "s1_checkpoint.py", "s1_collect.py", "s1_common.py",
          "s1_gates.py", "s1_journal.py", "s1_receipt.py", "s1_run.py", "s1_seal.py", "s1_snapshot.py")
```

New:
```python
BUNDLE = ("e1_fetch.py", "e1_sim.py", "s1_books.py", "s1_checkpoint.py", "s1_collect.py", "s1_common.py",
          "s1_gates.py", "s1_journal.py", "s1_locks.py", "s1_receipt.py", "s1_run.py", "s1_seal.py",
          "s1_snapshot.py")
```

Why: intended semantic change. A3.1's explicit file list gains the new product module s1_locks.py (sorted after
s1_journal.py), mirroring the same edit to s1_common.BUNDLE_CODE. The test's assertions are unchanged
(`tuple(sorted(c.BUNDLE_CODE)) == BUNDLE` and the s1_*.py glob equality); only the expected list grows. RED on the
stub (t3_red.txt: the glob saw s1_locks.py, the tuple did not), GREEN after the edit (t3_green.txt).

### research/s1/s1_tests/test_s1_a3_journal.py

Added one assertion (no existing assertion changed) to test_bundle_pins_addendum3_and_lists_every_new_module:
`assert "s1_locks.py" in c.BUNDLE_CODE` (brief Step 4).

### Other existing tests

See t3_full.txt and the report: no other existing test was edited.

## Task 4 old -> new

Source: `a3/t4_old_new.md`, sha256 `fd2f697bd275810975fb6e3a82377353fb6ff9001b22b239456dc4fecabca330`


All of the edits below are in existing test files. Each is classified. At Task 4's end, every edited test except
the two BUNDLE-tuple tests (green) is in the Task 5 migration red list (t4_red_list.txt): its fixture now stops
before the edited assertion, at the RUN-ACK token refusal. The edited assertions are therefore first executed in
Task 5.

### research/s1/s1_tests/test_s1_t12_a3_a8.py (BUNDLE tuple)
Old: `... "s1_seal.py", "s1_snapshot.py")`
New: `... "s1_seal.py", "s1_snapshot.py", "s1_trial.py")`
Why: intended semantic change (A3.1 explicit file list gains the new module s1_trial.py, mirroring
s1_common.BUNDLE_CODE). RED on the stub (t4_red.txt), GREEN after (t4_full.txt).

### research/s1/s1_tests/test_s1_a3_journal.py
Added `assert "s1_trial.py" in c.BUNDLE_CODE` to test_bundle_pins_addendum3_and_lists_every_new_module. No existing
assertion changed.

### research/s1/s1_tests/test_s1_run.py
- L218 old: `... a["trial_id"] == "S1" and a["planned_start"] == START`
  new: `... a["trial_id"] == read(out / "plan.json")["trial_id"]` plus `assert a["planned_start"] == START`.
- L1012 old: `r.attest_start(...)["trial_id"] == "S1"`
  new: `== read(out / "plan.json")["trial_id"]`.
- L1505 old: `trial_id="".join(list(r.TRIAL_ID))`
  new: `trial_id="".join(list(plan["trial_id"]))`.
  r.TRIAL_ID is removed; the by-value comparison is kept.
Why: intended semantic change (F6.2, OQ-27). The trial id is the plan's uuid4, not the constant "S1".

### research/s1/s1_tests/test_s1_t12_a4.py
- L204 old: `assert pr["trial_id"] == "S1"`
  new: `== <plan.json>["trial_id"]`.
Why: intended semantic change (F6.2).

### research/s1/s1_tests/test_s1_t12_mutant_survivors.py
- L228 old: `r.do_prereg(...)["trial_id"] == "S1"`
  new: `== <plan.json>["trial_id"]`.
Why: intended semantic change (F6.2).

### research/s1/s1_tests/test_s1_task11.py
- L455 old: `... and "{attest}" in k.ACQUIRE_ACK`
  new: `... and "attest_stop_sha256" in s1_trial.ACK_FIELDS["S1-ACQUIRE-ACK"]`.
Why: intended semantic change (OQ-5). The ACQUIRE text is ACK_FIELDS, and k.ACQUIRE_ACK is removed.

### research/s1/s1_tests/test_s1_t12_fix8.py (fixture `template`, module scope)
- Old: `c.MAILBOX = root / "mailbox.sqlite3"` (file not yet created).
  New: `c.MAILBOX = s1_mailbox_init(root)` (and the import).
Why: fixture incompatibility. write_plan now reads the mailbox first (F9 / OQ-20, require_no_open_trial). This
module-scoped template runs outside the per-test autouse fixture that creates the tmp mailbox, so it refused
"mailbox unreadable" for all 189 parametrized cases.
- After the fix, those 189 cases fall into the Task 5 migration set (the RUN-ACK token refusal), the same single
  cause as every other red case.
- The mailbox is still a tmp file under tmp_path_factory, never the real one.

### Not edited (in the Task 5 migration set)
test_s1_connected.py:453 `k.ACQUIRE_ACK.format(...)` (the plan says this is classified in Task 5). It is in the red
list because its fixture fails earlier, at the RUN-ACK token. When Task 5 reaches that line, it would fail with
AttributeError, because k.ACQUIRE_ACK is removed as the plan requires.

## Task 5 old -> new

Source: `a3/t5_old_new.md`, sha256 `730e348c2cf3fc8a670b3cf155f70e7f919b1face7d7ae6a3db5fdd104e9ed08`


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

### conftest.py (FX)
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

### test_s1_connected.py
- test_connected_lifecycle_matches_independent_oracle[4 cases] (FX + I-F7.1): its hand-built flow gains the audit
  stage's synthetic rows after `do_audit`, the OPENING-ACK after the opening seal, `s1_ack` RUN-ACK and PREREG-ACK,
  a synthetic TRIAL-STOP before `attest_stop`, `s1_ack` ACQUIRE-ACK (old: `k.ACQUIRE_ACK.format(...)`, removed in
  Task 4 - the L453 carry-forward) and `s1_ack` SCORE-ACK. Assertions unchanged.

### Re-posted ACKs: `s1_mailbox(root, id, <kind>_token(root), at)` -> `s1_reack(root, id, "<KIND>", at)` (I-F7.1)
Old: a second ACK of a kind was posted next to the fixture's; new: at most one per trial (a second one refuses every
command, "2 S1-SCORE-ACK ... escalate"), so the test's ACK replaces the fixture's. Times unchanged unless listed below.
test_s1_bridge_8b.py:156,206 · test_s1_checkpoint_7b.py:246,427 · test_s1_run.py:360,568,583,601,725,736,747,748,
760,779,1093,1109,1280,1382,1561 · test_s1_t12_a2.py:102,118,168,186 · test_s1_t12_a3_a8.py:248,266 ·
test_s1_t12_a7.py:101 · test_s1_t12_a9.py:193 · test_s1_t12_fix2_b2.py:223 · test_s1_t12_fix2_b3.py:285 ·
test_s1_t12_fix3.py:425,537 · test_s1_t12_mutant_followups.py:364 · test_s1_t12_mutant_survivors.py:239 ·
test_s1_t12_reporting.py:34 · test_s1_task11.py:133,480 (line numbers of the base file f5f7f83).

### test_s1_run.py
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

### test_s1_bridge_8b.py
- test_bridge_row_edited_then_scored_is_aborted_invalid: `s1_finalize` before the re-issued SCORE-ACK (FX: the
  checkpoint-abort flow ends outside `s1_state`).
- I-F0.6 via `s1_score_refused`: test_score_with_a_seal_missing_its_bridge_record_is_aborted_invalid,
  ..._bridge_hash_differing_from_the_final_ledger_..., ..._bridge_record_not_matching_its_rows_...

### test_s1_checkpoint_7b.py
- test_score_ack_binds_the_final_snapshot_report_and_an_edit_after_the_ack_is_refused: match "ack lacks the
  standalone line" -> `t.Refusal` "S1-SCORE-ACK score-ack: ['final_snapshot_sha256'] differ" (I-F7.1 field by field).

### test_s1_collect.py (TIGHT)
- test_final_requests_every_symbol_bars_and_full_history (second do_final): "an attempt already exists; one attempt
  only". test_final_lag_refused_before_reserving: "acquisition lag not met".

### test_s1_t12_a2.py (I-F0.6 via `s1_score_refused`)
test_a2_attest_stop_binds_the_persisted_stop, test_a2_integrity_of_the_frozen_slices_is_enforced_at_score[3],
test_a2_no_valid_seal_is_terminal_persisted_and_never_rescued_by_a_late_seal.

### test_s1_t12_a3_a8.py
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

### test_s1_t12_a5_a6.py
- test_a6_a_dropped_session_relative_to_the_pinned_listing_refuses (I-F0.6): the score after the checkpoint's
  registration-artifact abort: old ABORTED-INVALID naming the calendar; new `t.Refusal` "trial INVALID
  (reason/registration-artifact)", no score.

### test_s1_t12_fix2_b3.py
- test_b3_the_opening_changed_after_the_opening_but_before_the_run_ack_is_a_persistent_abort: restored re-entry
  match "ABORTED" -> `t.Refusal` "trial INVALID (reason/registration-artifact)" (I-F0.6).
- test_b3_a_registered_artifact_changed_or_deleted_then_restored_stays_invalid[16]: restored re-entry old = a
  checkpoint report (seal not written, ABORTED-INVALID); new = `t.Refusal` "trial INVALID
  (reason/registration-artifact)" (I-F0.6).
- test_b3_a_registration_artifact_violation_at_the_score_is_persisted_and_prices_nothing (I-F0.6, the brief's named
  example): old = "ABORTED-INVALID report, zero prices"; new = "TRIAL-INVALID committed, score refused, zero prices"
  (asserts the TRIAL-INVALID reason/registration-artifact row, aborted.json, no score/, no valuation call).

### test_s1_t12_fix2_mutants.py
- test_mt_attest_stop_reverifies_the_run_ack (FX): the test moves the RUN-ACK's `created` after START; its
  successor PREREG-ACK (new in the fixture) is moved too, so the ACK chain stays intact (F6.1) and the legacy
  "registration not verified" timing check is what refuses (unchanged match).

### test_s1_t12_fix3.py
- test_c2_deleting_an_artifact_with_its_registry_record_is_a_persistent_abort[9] and
  test_c2_probe_deleting_prereg_and_its_registry_record_then_restoring_never_resumes: restored re-entry -> `t.Refusal`
  "trial INVALID (reason/registration-artifact)" (I-F0.6).
- test_i1_the_score_refuses_while_a_success_lacks_its_seal: `s1_finalize` before the SCORE-ACK (FX); "RUNNING"
  refusal unchanged.
- test_m3_a_registration_abort_before_the_final_snapshot_still_yields_a_recorded_score (I-F0.6): old = the score
  records ABORTED-INVALID; new = `t.Refusal` "trial INVALID (reason/registration-artifact)", zero valuation calls, no
  score/.
- TIGHT: test_c2_retro_the_run_ack_witnesses_the_attestation: "registration artifact".

### test_s1_t12_fix8.py
- test_h_every_subset_of_the_editable_registration_files_tampered_is_the_persistent_abort[189] (I-F0.6): restored
  re-entry old = a checkpoint report with stop ABORTED-INVALID (registration artifact); new = `t.Refusal` "trial
  INVALID (reason/registration-artifact)"; aborted.json unchanged (first wins).
- test_h_a_run_ack_carrying_the_bundle_is_a_registration_even_before_the_opening (I-E4.3): the forged official line
  "S1-RUN-ACK plan_sha256=..." has no trial_id: an unattributable malformed official candidate, so the gate refuses
  every trial-bound command ("unattributable malformed official ACK line"), zero callbacks; old = a persistent
  registration-artifact abort.

### test_s1_t12_mutant_followups.py
- test_mf_the_score_ack_binds_the_persisted_stop (I-F0.6 + I-F7.1): stop.json edited is a registration artifact:
  `s1_score_refused`; the binding is asserted on the posted SCORE-ACK's `stop_sha256` field vs `artifact_fields`
  (old: "ack lacks the standalone line").
- I-F0.6 via `s1_score_refused`: test_mf_the_score_reverifies_the_run_token_bindings,
  test_mf_an_edited_opening_books_file_is_aborted_invalid_at_score.

### test_s1_t12_mutant_survivors.py
- test_ms_an_audit_ack_message_without_the_exact_audit_token_refuses (FX): `s1_plan_audit(journal=False)` - the test
  rewrites the AUDIT-ACK body, which is every journal row's genesis (F0.2); assertion unchanged ("audit token").
- test_ms_a_run_ack_message_not_carrying_the_exact_run_token_refuses (I-F7.1): expected problems
  ["the RUN-ACK does not carry the RUN token of the current artifacts"] -> ["RUN-ACK runner_sha256 does not match"].
- test_ms_stop_json_changed_after_the_attestation_is_named (I-F0.6 via `s1_score_refused`).

### test_s1_task11.py
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

### Bare `pytest.raises(SystemExit)` re-check (Task 4 review carry-forward)
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
## Fix round 1 (review task-5-review-verdict.md; controller rulings in progress.md)

New tests (test_s1_a3_gate.py; RED in t5_fix1_red.txt): test_total_loss_then_outage_then_mailbox_back_never_resumes
(the reviewer's I-1 scenario), test_total_loss_with_a_bundle_mismatch_is_lost_and_never_recreates_s1_out,
test_no_gate_refusal_writes_into_a_missing_s1_out[4], test_an_invalid_trial_adds_no_repeat_invalid_rows_on_re_entry
(M-3), test_the_gate_is_the_first_call_of_every_command[10] (M-5), test_a_raw_context_without_slot_gate_or_stage
_check_fails_closed (M-6), test_final_snapshot_after_its_own_detection_captures_nothing (I-2).

### FX (fixture incompatibility, assertions unchanged)
- M-6 (`decide` now fails closed on a missing slot_gate / stage_check at step 5): the test contexts that relied on
  the old fail-open default now supply `stage_check=lambda rows, s, i: None` explicitly: conftest `s1_jappend`,
  test_s1_a3_journal.py `OPEN`, test_s1_a3_precedence.py `ctx`, test_s1_a3_trial.py `stage_row`. No assertion and no
  map-row outcome changed (steps 2-4 never read these callables; every Task 2 precedence case still passes).

### I-F8.1 (review I-2: run_final_snapshot re-gated after its legacy detector)
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

### I-3 (review): test_s1_collect.py
- test_final_lag_refused_when_calendar_lacks_three_later_sessions: old = a second ACQUIRE-ACK "f9" (passed for the
  WRONG reason: "2 S1-ACQUIRE-ACK ... escalate"). New = `s1_reack` (one ACK per kind) and the command's real reason
  asserted: "registration artifact(s) missing or changed: ['prereg.json changed" (the test edits prereg.json, a
  registered artifact since B3); the calendar/lag rule itself asserted at unit level:
  `k._earliest_acquire(<4-day calendar>, stop_day)` -> "cannot place the 3rd session after the stop".
- test_final_ack_binds_prereg (I-8): bare -> "registration artifact(s) missing or changed" (the real reason; the
  edited prereg is a registered artifact, pre-dating Task 5), plus a unit-level assertion that the ACQUIRE-ACK's
  `prereg_sha256` no longer equals `artifact_fields`.

### TIGHT (every remaining bare `pytest.raises(SystemExit)` in the migrated files gets `match=`)
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

### Minor
- M-1: test_s1_a3_codex_probes.py imports `s1_jappend` at the top (`# noqa: F401`, Task 7 appends; P41).
- M-7: codex_probes_historical/README.md added; SHA256SUMS regenerated (14 entries, README included).

## Task 6 old -> new

Source: `a3/t6_old_new.md`, sha256 `afb898c80298cba38304a1346406896958ada51d7a8000eb540393539ae396a6`


Base 9920867. Every edit to an existing test or fixture is listed with its class and the spec clause. Classes:
**intended** (the old expectation is replaced by the binding A3 rule; the oracle that remains is stated),
**fixture** (test set-up only, no oracle changed), **held** (the test needs a later task's interface; skipped with
the reason in its marker, not faked). No assertion was weakened without being listed here.

### Product readers (plan Step 4: `_report_seals` / `_capture_seal_problems`, OQ-11 ruling, E5.2, E2.6 r3)

| function | old line(s): what it read | new: what it reads |
|---|---|---|
| `s1_common._report_seals(out)` | every `captures/*/*.report.json` with `seal.written` true, and every report / `*.attempt.json` with `after_seal.sha256` (fix round 5, R-3); the seal path from the report's `close` | `_report_seals(out, rows=None, cal=None, *, mailbox=None)`: `s1_slot.required_seals(out, rows)` - exactly the CREATED `seal/<close>` stages with their committed member hash (prepared.json verified against the PREPARED detail). Tuple = (member relpath, seal path, sha256). `rows=None`: the open trial's rows read mode=ro (`_open_trial_rows`, [] when none). No report, claim or after.json is opened. `cal` unused (plan signature) |
| `s1_common.registration_problems` (`for rp, sp, h in _report_seals(out)`) | reports recording a seal: "seals/X missing or changed (recorded by capture report ...)" | the CREATED seal stages: "<member> missing or changed (a CREATED seal stage's committed member, E2.6)" (mailbox threaded) |
| `s1_common.registration_witnesses` ("opening capture report") | a report recording a written / after-seal opening seal | removed: a report is final before J and records no seal (OQ-11); the opening seal, resolution and capture witnesses remain (see the held fix3 C-2 test) |
| `s1_run._capture_seal_problems(out)` | every report with `seal.written` true must name an existing seal with that sha256 | `_capture_seal_problems(out, rows=None, cal=None)`: every member of `_report_seals(out, rows, cal)` (the CREATED seal stages) must exist with its committed sha256; never opens a report or after.json |
| `s1_checkpoint._before_opening_seal` | `c._report_seals(out)` (report / after-seal hashes) | `c._report_seals(out, rows)` - the journal's required seals (no opening entry until Task 10) |

### Other product interface changes

- `s1_journal.REASONS` gains `established-violation` (OQ-31). Old -> new for the Task 1 tests: none (no test pins
  REASONS).
- `BUNDLE_CODE` gains `s1_slot.py` (A3.1).
- `s1_checkpoint`: `_publish`, `_late_path`, `_overrun_path`, `_record_overrun` (B1.3 worker-side records),
  `_claim_slot` (claim -> `Worker.intent`), `_after_opening_seal` (R-3 -> opening gate), `_trial_stop`/`_stop_hash`
  and `_write_report`/`_report_path` (report -> `Worker.complete`) are removed; `finalize_close` gains
  `qualified=None, rows=None`; `_finalize_others` gains `rows=None`.
- `s1_stage.evaluate(gv, *, defer_pending=False)`, `s1_stage.Pending(SystemExit)`; `s1_trial.gate(...,
  defer_pending=False)`, `Gate.deferred` (ruling N2).

### Test and fixture edits

| file :: test | old | new | class / clause |
|---|---|---|---|
| test_s1_t12_a3_a8.py `BUNDLE` | tuple without s1_slot.py | `"s1_slot.py"` added | intended (A3.1: s1_slot.py joins BUNDLE_CODE) |
| conftest.py `s1_jappend` | slot E = D = at + 3650 d | keyword `due=False`; `due=True` makes E = D = at | fixture (a synthetic SLOT-TIMEOUT needs now >= D; brief Deviation 1) |
| conftest.py `s1_prereg_ack` (new) | - | posts the trial's PREREG-ACK 1 min after prereg.json's recorded time | fixture (F7.4: a post-START capture needs the PREREG-ACK) |
| test_s1_bridge_8b, t12_a1, t12_a1b, t12_a2, t12_a3_a8, t12_a5_a6, t12_a9, t12_fix1, t12_fix2_b2, t12_fix2_b3 (x2), t12_fix2_mutants, t12_fix3 (x4), t12_fix5 (x2), t12_mutant_followups (x2), task11 (x3): every `with _Clock(...): r.do_prereg(tmp_path, "run-ack", ...)` helper | no PREREG-ACK | `s1_prereg_ack(tmp_path)` after it | fixture (F7.4) |
| test_s1_a3_gate.py :: test_identity_refusals_have_zero_callbacks | `"SLOT-INTENT" not in raw_kinds` | `raw_kinds == before` (the kinds read after the damage, before the command) | fixture (the fixture's opening slot now has SLOT-INTENT/QUALIFIED rows); stronger (no new row of any kind) |
| test_s1_t12_a3_a8 :: test_a8_checkpoint_verifies_...[ack_deleted, ack_after_start] | RUN-ACK deleted / re-dated | the same, and the PREREG-ACK (which chains to that RUN-ACK) removed | fixture (the PREREG-ACK added by the migration cannot outlive its predecessor; the RUN-ACK refusal is unchanged) |
| test_s1_checkpoint :: run() | fixed clock | `intent_delay`: the clock until the claim exists | fixture (F0.5 step 6) |
| test_s1_checkpoint :: test_counts_only_report_and_seal | key set | + `journal` | intended (the returned dict carries the J outcome, OQ-11) |
| test_s1_checkpoint :: test_abort_survives_receipt_revert, test_abort_after_fence_violation_survives_clean_and_failed_runs, test_backdated_row_later_deleted_stays_aborted; test_s1_t12_a9 :: ..._survives_restoration; test_s1_t12_fix1 :: test_fix1_i1_merge_conflict...; test_s1_t12_fix2_b2 :: test_b2_a_then_gap_then_b... | a run after the abort captures and reports ABORTED-INVALID | the run after the abort is refused `trial INVALID (reason/established-violation)`; the first abort record is unchanged, no seal | intended (OQ-31: the violation commits TRIAL-INVALID first; F0.6/F1: INVALID -> no work) |
| test_s1_checkpoint :: test_receipt_mismatch_capture_does_not_seal_and_seal_carries_receipt | mismatch first, unlink aborted.json, positive half | positive half first (seal carries the receipt), then the mismatching slot: seal bytes unchanged, `seal.written` False, abort written | intended (F1: INVALID is irreversible, deleting aborted.json never resumes) |
| test_s1_checkpoint :: test_rerun_of_captured_slot_is_recorded_and_refused; test_s1_checkpoint_7b :: test_opening_inconsistent_capture...; test_s1_t12_fix2_mutants :: test_mt_a_duplicate_slot_execution... | "slot already captured" + reruns.jsonl | "a restart never re-intents" + the slot's journal rows (or all rows) unchanged | intended (F3: the journal pre-check under the slot lock; reruns.jsonl is no longer written) |
| test_s1_checkpoint :: test_late_capture_flagged, test_cr_capture_exactly_at_the_slack...; test_s1_checkpoint_7b :: test_opening_late_capture_does_not_seal | invocation at s + 11 min / at E | the INTENT before E (`intent_delay`), the capture at the same late instant | intended (F0.5 step 6); the late / on-time oracle unchanged |
| test_s1_checkpoint_7b :: test_opening_mode_refuses_a_second_run... | "opening seal exists" | "the opening is already decided" + no row | intended (F1 opening gate, E5.6) |
| test_s1_checkpoint_7b :: test_receipt_stored_concurrently..., test_cr_concurrent_receipt_conflict... | "(concurrent)" refusal in the report | report: `seal.written` False, consistent True; "(concurrent)" and `receipt_match` False in `<slot>.after.json` | intended (OQ-11/E5.2: the report is final before J) |
| test_s1_connected :: lifecycle (UNSEALED_DAY) | 3 h late invocation: refused report | `SystemExit("now >= E")`, no captures dir, no seal | intended (F0.5 step 6) |
| test_s1_connected :: lifecycle (post-stop, buy/receipt) | post_stop capture, receipt reported only | LOST-RACE, no capture, no abort, no seal | intended (F1, OQ-25; brief Step 6 "A2.2 -> F1") |
| test_s1_task11 :: test_c1_post_stop_checkpoint..[buy, receipt], test_c1_post_stop_fence_difference_is_reported_only | post_stop capture | LOST-RACE, no capture, no abort, no seal; the score unchanged | intended (F1, OQ-25) |
| test_s1_task11 :: test_c1_checkpoint_after_an_abort... | post_stop capture, ABORTED-INVALID | refused "aborted.json exists ... no new capture": no capture, no seal | intended (F8.1; Deviation 8) |
| test_s1_t12_fix2_b3 :: test_b3_a_corrupt_aborted_json_fails_closed | report written, ABORTED-INVALID | refused before the INTENT (a corrupt aborted.json is an abort), no capture, no seal | intended (F8.1, B3.4 fail-closed kept) |
| test_s1_task11 :: test_m2_capture_report_naming_a_seal...[missing, different] | a forged / edited report recording a seal -> "seal missing" | a CREATED seal stage `seal/2026-10-26` (synthetic rows + staging, `_created_seal_stage`) whose member is then deleted / changed: the gate commits INVALID (stage-replaced), the score's record lists "seal missing" | intended (OQ-11, E2.6 r3: required seals are the CREATED seal stages; the forged-report variant is the F3 evidence table, Task 7) |
| test_s1_t12_a2 :: test_a2_post_stop_checkpoints_follow_the_persisted_stop | `post_stop` flag | `journal.outcome == "APPEND"`, `seal.written` False, the persisted stop followed | intended (no post_stop flag: the post-STOP state is the journal's, F1; no TRIAL-STOP row exists here until Task 11) |
| test_s1_t12_a5_a6 :: test_a5_the_clock_is_checked...[at1, at2], test_a5_codex_probe_b..., test_a5_a_delayed_invocation... | refused report at t > E | refused "now >= E" with no row, no claim, zero snapshot calls, no seal | intended (F0.5 step 6, OQ-33) |
| test_s1_t12_a5_a6 :: test_a5_the_clock_is_checked...[at0] | refused report; rerun "slot already" | claim + refused report + SLOT-FAILED (APPEND); rerun "a restart never re-intents" | intended (OQ-33 early invocation; F3 restart) |
| test_s1_t12_fix1 :: test_fix1_i4b_a_corrupt_trial_seal... | the registration gate (the seal bound by its report) aborts | the next capture's seal read: TRIAL-INVALID (established-violation, seal-record) first, abort "bad seal record", observation subtype seal-record, no seal | intended (OQ-11: no report binds a seal; OQ-31) |
| test_s1_t12_fix1 :: test_fix1_m4_a_changed_persisted_stop... | `z.stop_problems` (reports' stop_sha256) | `c.registration_problems` (the stop's registry records) | intended (OQ-11: a report no longer records stop_sha256; Task 11: TRIAL-STOP detail) |
| test_s1_t12_fix2_b1 :: helpers | - | `kinds`, `timeout_row` (the finalizer's SLOT-TIMEOUT via j.append + product context) | fixture |
| test_s1_t12_fix2_b1 :: test_b1_a_claim_without_a_report... | RESOLUTION-TIMEOUT file at D45 | no file; slot = [SLOT-INTENT]; after D45 slot 47 seals | intended (B1.3 -> F3, E1.4: the finalizer never touches a worker's files; its TIMEOUT row is Task 7) |
| test_s1_t12_fix2_b1 :: test_b1_a_success_published...[0, +1 min] | RESOLUTION-TIMEOUT + .late.json | SLOT-QUALIFIED REFUSE (late R), slot = [SLOT-INTENT], the worker's evidence in place, no .late.json, later slot 47 seals | intended (F0.5 step 6, F3) |
| test_s1_t12_fix2_b1 :: test_b1_expiration_racing...[3] | one resolution file (worker vs finalize_close) | one terminal ROW (worker's QUALIFIED vs the finalizer's SLOT-TIMEOUT through the journal; barrier variant on j.append), the loser LOST-RACE, no INVALID, the seal follows, replay changes nothing | intended (E1.2/E1.3) |
| test_s1_t12_fix2_b1 :: test_b1_killed_and_merely_slow...[2] | RESOLUTION-TIMEOUT file, .late.json | both: slot = [SLOT-INTENT], D45 unchanged; slow: REFUSE (late R), no .late.json; seal 47 | intended (F3, E1.2, E1.4) |
| test_s1_t12_fix2_b1 :: test_b1_D_never_extends...[2], test_b1_the_0800_slot... | refused FAILURE resolution | "now >= E", no row, no resolution | intended (F0.5 step 6) |
| test_s1_t12_fix2_b1 :: test_b1_a_pending_resolution_cannot_cause_an_early_terminal_stop... | an 08:00 slot in flight at W | the 08:00 slot is refused at s = E (it can never be in flight); the stop decided at 08:10 equals the one at 08:25 (decided once, never rescued) | intended (F0.5 step 6 with A5.3 E = W = s; see report finding) |
| test_s1_t12_fix2_mutants :: test_mt_a_forged_success_without_complete_evidence... | abort "bad resolution record" and no seal | **split (fix round 1, review I2)**: this test keeps only the never-seals half - the forged SUCCESS of a no-row slot is never selected; slot 47 (QUALIFIED) is the seal | intended for the never-seals half (F3: only QUALIFIED is selectable) |
| test_s1_t12_fix2_mutants :: test_mt_a_forged_success_of_a_no_row_slot_is_invalid (new, skipped) | (the abort half) | the forged no-row resolution is INVALID registration-artifact with zero callbacks | **held** (Task 7: the F3 evidence table, s1_slot.slot_problems) - not intended |
| test_s1_t12_fix2_mutants :: test_mt_a_later_close_resolves_an_earlier_close... | RESOLUTION-TIMEOUT file | no file; the earlier close seals from slot 47 | intended (E1.4) |
| test_s1_t12_fix2_mutants :: test_mt_an_unbound_corrupt_seal... | report written + abort | TRIAL-INVALID (established-violation, seal-record) + observation + abort; no P | intended (OQ-31: external first; no terminal slot event required) |
| test_s1_t12_fix2_mutants :: test_mt_a_deleted_stop_and_its_registry_record... | reports' stop hash witnesses the stop | **held** (Task 11: TRIAL-STOP is the stop's authority; the report no longer records the stop hash) | held |
| test_s1_t12_fix3 :: `_success_without_seal` (I-1 x4) | the 08:00 slot in the crash window | the 07:00 slot (the last capturable one); every stop decision still after W | intended (F0.5 step 6: the 08:00 slot can never be opened) |
| test_s1_t12_fix3 :: test_m1_a_publication_whose_link_lands_at_or_after_D... | SUCCESS seals, .overrun.json | R >= D: REFUSE, no seal, no .overrun.json | intended (B1.3 M-1 -> F3: R is read after P; probes 172-174) |
| test_s1_t12_fix3 :: test_c2_retro_the_opening_report_and_resolution_witness... | the opening report witnesses the registration | **held** (Task 10: the opening seal as the `opening` stage) | held |
| test_s1_t12_fix5 :: test_r1_probe_an_opening_whose_first_slot_never_ran... | MISSED file for 20:45 | no file, no claim for 20:45; the next slot seals from 20:55 | intended (E1.4; the SLOT-MISSED row is Task 7) |
| test_s1_t12_fix5 :: test_r3_an_opening_slot_after_the_seal... | claim + resolution + after-seal report | "the opening is already decided": zero callbacks, no claim, no capture, no resolution, no report, no row; seal and receipt unchanged | intended (plan Step 6 "R-3 -> opening gate", F1, E5.6) |
| test_s1_t12_fix5 :: test_r3_deleting_the_seal..., test_r3_the_after_seal_claim_alone..., test_r3_the_selection_never_writes... | after-seal records bind the seal | **held** (Task 7: the F3 evidence table detects the deleted QUALIFIED tree / the forged no-row slot files before any callback) | held |
| test_s1_t12_mutant_followups :: test_mf_a_tampered_deferred_capture_never_seals | `refused` "differs from its recorded projection" | refused "QUALIFIED tree differs from the committed detail ... registration-artifact", no seal, abort registration artifact | intended (F3 QUALIFIED: a changed tree member is INVALIDATE; the _seal_bytes re-check is now second-line - Task 15 note) |
| test_s1_t12_reporting :: test_r6_refused_captures... | post-stop late refusal + binding gap listed | **held** (Task 11: the refused capture and the gap must be committed before the STOP) | held |
| test_s1_bridge_8b :: test_bridge_row_edited_then_scored_is_aborted_invalid | final snapshot + score run | the final snapshot refused (trial INVALID, established-violation); the score's unit-level record (`s1_score_refused`) still names the bridge abort | intended (OQ-31, F1) |
| test_s1_a3_codex_probes.py | 4 tests | + header imports (ck, j, z, sl, S1_PROCESS, s1_ack) and the 4 publication probes | new (plan Step 2) |

Held tests: 7 after fix round 1 (all `pytest.mark.skip` with the reason; t6_fix1_full.txt lists them).

### Fix round 1 (review C1, C2, I1, I2, M1-M5)

Product:
- `finalize_pending(out, cal, start, t, *, mailbox=None)` (C1): the journal-mode selection over the open trial's rows
  (`c._open_trial_rows`, fail closed): only SLOT-QUALIFIED slots are selectable; no TIMEOUT / MISSED file is written.
  `s1_run.attest_stop` passes its mailbox. The legacy file-writing branch of `finalize_close` has no product caller.
- `_journal_slot` (C2): an INTENT-only slot DEFERS until a terminal row exists, whatever t (E1.3/E1.7, E2.2, B1.4).
- `_finalize_others` (I1): re-raises `_QualifiedEvidence` (never swallowed).
- M1: `_after_terminal` and the opening path take `t` before reading the rows.
- M2: `finalize_close(qualified=)` removed (no caller).
- M4: `s1_common._open_trial_rows` fails closed (SystemExit); `registration_problems` re-raises it unless file problems
  already decide (B3.4: an outage never downgrades an established violation).

Tests:

| file :: test | old | new | class / clause |
|---|---|---|---|
| test_s1_a3_slots :: test_finalize_pending_never_seals_a_slot_without_a_qualified_row (new) | - | R = D -> REFUSE; finalize_pending: no seal, no file written under captures/ | new (C1; RED in t6_fix1_red.txt) |
| test_s1_a3_slots :: test_an_in_flight_earlier_slot_defers_the_seal_even_past_its_d (new) | - | the reviewer's 45/47 repro: slot 47 defers, slot 45 QUALIFIED, the seal is slot 45's | new (C2; RED) |
| test_s1_a3_slots :: test_a_damaged_qualified_tree_on_another_pending_close_is_invalid (new) | - | damaged slot-47 report, slot 45's finalizer TIMEOUT committed (so the walk reaches 47), next close: INVALID registration-artifact, abort, no seal | new (I1; RED for the first draft and for the revised test with the I1 fix reverted, t6_fix1_red.txt) |
| test_s1_a3_slots :: test_lost_race... `recheck == []` | unlabelled | labelled a Task 7 stub (slot_problems) | label (M3; carried to Task 7) |
| test_s1_t12_fix2_b1 :: test_b1_a_claim_without_a_report... | after D45 slot 47 seals with slot 45 INTENT-only | `timeout_row(S45, D45)` first; slot 45 = [SLOT-INTENT, SLOT-TIMEOUT]; then slot 47 seals | intended (C2: E1.3/E2.2 - the finalizer's TIMEOUT row, Task 7, comes first) |
| test_s1_t12_fix2_b1 :: test_b1_a_success_published...[0, +1 min] | S2200 seals slot 47 | `timeout_row(S45, S2200+30 s)` first | intended (C2) |
| test_s1_t12_fix2_b1 :: test_b1_killed_and_merely_slow...[2] | slot 45 INTENT-only; slow worker REFUSE (late R) | `timeout_row(S45, D45)` first (no lock, E1.2); slot 45 = [INTENT, TIMEOUT]; the slow worker's later J is LOST-RACE at 4c (E1.3) | intended (C2, E1.3) |
| test_s1_t12_fix2_mutants :: test_mt_a_later_close_resolves... | the next close seals slot 47 with 45 INTENT-only | `timeout_row(S45, D45)` first | intended (C2) |
| test_s1_checkpoint :: test_fr1_main_and_trial_state_compare_modes_and_status_by_value | `_trial_state` without a trial | `s1_common._open_trial_rows` returns [] (the unit's subject is the RUNNING comparison) | fixture (C1: finalize_pending reads the journal, fail closed) |
Regressions: none.

## A3 Task 7 - old -> new (every migrated legacy test, classified)

Source: `a3/t7_old_new.md`, sha256 `136918f1d164a40b7488d1b61597d409cf9833e36b40cf351314f6b4ed7703ae`


Classes: intended (a spec clause changes the expected outcome; the row's oracle is replaced by the spec's, never weakened), fixture (test setup or reach only; the oracle is unchanged), strengthened, none (the test is unchanged; a product fix made it pass again). No requirement-map row outcome changed.

| file::test | old oracle | new oracle | class | spec |
|---|---|---|---|---|
| test_s1_a3_stage::test_seal_files_on_disk_are_not_evaluated_while_the_seal_family_is_not_enforced -> ..._are_evaluated_once_the_seal_family_is_enforced | SEALS_ENFORCED is False; a rowless seal file passes the gate | SEALS_ENFORCED is True; a rowless seal file is INVALID (registration-artifact) | intended (the D5 switch flipped with the seal stage) | E2.4 r3; Task 8 D5 (a) |
| test_s1_a3_slots::test_finalize_pending_never_seals_a_slot_without_a_qualified_row | captures/ file set unchanged | no seal; slot 45 gets the finalizer's SLOT-TIMEOUT; no file added under captures/ (subset), the removed files are the losing op's, now in late/ | intended (the finalizer appends TIMEOUT at D and does the deferred cleanup) | E1.2, E1.4, OQ-13 |
| test_s1_a3_slots::test_an_in_flight_earlier_slot_defers_the_seal_even_past_its_d | r47 seal not written ("in flight"); slot 45 QUALIFIED; seal is slot 45's | r47's finalizer appends slot 45's TIMEOUT (t >= D45); seal is slot 47's; slot 45 rows INTENT, TIMEOUT; no INVALID | intended (the Task 6 C2 premise "no finalizer TIMEOUT yet" is gone: the worker path runs the journal finalizer) | E1.2, E1.3, E1.7 (TIMEOUT committed first stands) |
| test_s1_a3_slots::test_lost_race_moves_only_own_uncommitted_files_to_late | recheck == [] (vacuous: Task 6 stub) | recheck == [] by the real F3 table, plus a control: a seal citing the TIMEOUT slot makes slot_problems non-empty | strengthened (review M3) | F0.5 LOST-RACE re-check |
| test_s1_t12_fix5::test_r3_deleting_the_seal_and_its_sealing_slot_records_after_a_later_slot_bound_it_aborts | HELD (Task 6); first reopen "opening seal exists" | un-held; first reopen "the opening is already decided" (E5.6 opening gate); the deletion -> match "QUALIFIED tree differs .*INVALID (registration-artifact)", abort, zero callbacks, last row reason/registration-artifact | intended (un-held for its stated reason) | F3, E5.6, OQ-11/E5.2 |
| test_s1_t12_fix5::test_r3_the_after_seal_claim_alone_still_binds_the_seal | HELD; the after-seal claim records the seal's sha256 | un-held; the later slot leaves no claim (asserted absent); the deletion is INVALID (registration-artifact) as above | intended (no after-seal record exists, OQ-11; the binding is the journal's QUALIFIED tree) | F3, OQ-11, E5.6 |
| test_s1_t12_fix5::test_r3_the_selection_never_writes_an_opening_seal_differing_from_a_recorded_opening_seal_hash | HELD; bare SystemExit | un-held; match "exists with no journal row .*INVALID (registration-artifact)" (the F3 re-check of the opening close before the selection); no opening seal; abort; last row reason/registration-artifact | intended | F3 ("no row: any claim, report or resolution") |
| test_s1_t12_fix2_mutants::test_mt_a_forged_success_of_a_no_row_slot_is_invalid | HELD | un-held, passes as written (match "registration-artifact", zero snapshots, abort) | intended (held for Task 7) | F3 |
| test_s1_checkpoint::test_counts_only_report_and_seal | key allow-list | + "deferred" (the finalizer's display status for the later slots of the close) | intended (display text only; counts-only property unchanged) | F3 finalizer walks every slot |
| test_s1_checkpoint::test_cr_bad_seal_record_is_recorded_as_an_abort_not_a_crash | the next checkpoint records ABORTED-INVALID "bad seal record" / "two seals" | the next checkpoint's gate: "2026-10-15-copy.json is not the seal ... INVALID (registration-artifact)", abort reason registration artifact | intended (a seal file outside a seal stage is a registration artifact, earlier and stronger than the stop check) | E2.4 r3, OQ-14 |
| test_s1_checkpoint::test_fr1_main_and_trial_state_compare_modes_and_status_by_value | _open_trial_rows patched | + finalize_pending patched to a no-op (it is now the journal finalizer behind its own gate; the unit test has no trial; its subject, the RUNNING comparison, is unchanged) | fixture | - |
| test_s1_run::test_score_seal_or_receipt_violation_is_invalid[row,receipt,capture], test_malformed_seal_is_recorded_as_aborted_invalid_not_refused_forever, test_cr_malformed_seal_without_final_manifest_is_still_scored_invalid, test_fr1_unreadable_seal_rows_are_a_bad_seal_record_reason | s1_score_refused(... "registration-artifact"): the score refused as trial INVALID, unit-level record ABORTED-INVALID | s1_score_refused(..., reason="stage-replaced"): a changed CREATED seal is INVALID (stage-replaced) at the score's gate; the unit-level record assertions unchanged | intended | E2.6 r3 |
| test_s1_run::test_cr_attest_stop_statement_and_bad_seal | attest_stop "bad seal record" (a duplicate seal file) | "seals/zz.json is not the seal ... INVALID (registration-artifact)" | intended | E2.4 r3, OQ-14 |
| test_s1_run::test_cr_duplicate_seal_is_a_bad_seal_record_reason | unchanged text; passes through the widened helper (registration-artifact, committed by the F3 table) | same | fixture (helper) | OQ-14 |
| conftest::s1_score_refused | pytest.raises(Refusal, match "trial INVALID (reason/<r>)") | pytest.raises(SystemExit, match "trial INVALID (reason/<r>)" OR ": INVALID (<r>)") - also the refusal of the gate that commits the INVALID itself (stage table / F3 table raise SystemExit) | fixture (helper; reason-specific match kept) | F0.6 |
| conftest::_write_seal | hand-written seal file + projection | real QUALIFIED slot (INTENT, claim, resolution, report, capture tree incl. backup.sqlite3, QUALIFIED with the real detail) + the REAL seal/<close> stage; with_stage=False stops after QUALIFIED; same seal bytes (seal_bytes) | fixture (brief Step 4) | F3, E5.6, E2 r3 |
| test_s1_checkpoint_7b::test_cr_final_snapshot_refuses_on_a_bad_seal_record[{},[],dup] | command: Refusal "trial INVALID (reason/registration-artifact)" (legacy detector); unit level: "bad seal record" / frozen-slice violation | command: Refusal "seals/zz.json is not the seal ... INVALID (registration-artifact)" (F3/OQ-14 at the gate); unit level unchanged, with finalize_pending patched to a no-op (it is now behind its own gate, which refuses the INVALID trial) | intended (oracle) + fixture (unit reach) | OQ-14, E2.4 |
| test_s1_checkpoint_7b::test_cr_final_snapshot_records_a_malformed_seal_fence_as_a_violation[3] | command: Refusal registration-artifact | command: SystemExit "member seals/... missing or changed ... INVALID (stage-replaced)"; unit level unchanged (finalize_pending no-op) | intended + fixture | E2.6 r3 |
| test_s1_collect::test_final_lag_refused_when_calendar_lacks_three_later_sessions; test_s1_bridge_8b::test_opening_close_error_is_a_recorded_refusal_not_a_crash | (failed in run 1: the F3 table read the EDITED prereg calendar and called the slots unregistered) | unchanged - product fix: the F3 table takes the audit's hash-verified calendar first (Deviation 8) | none (product) | A8.2 |
| test_s1_bridge_8b::test_score_with_a_seal_missing_its_bridge_record..., ...bridge_hash_differing..., ...bridge_record_not_matching_its_rows... | s1_score_refused(registration-artifact) | s1_score_refused(reason="stage-replaced"); the unit-level "bridge" reasons unchanged | intended | E2.6 r3 |
| test_s1_t12_a3_a8::test_a3_score_checks_bundle_consistency_across_every_artifact[seal] | Refusal "trial INVALID (reason/registration-artifact)" | SystemExit "seals/2026-10-26.json missing or changed ... INVALID (stage-replaced)"; unit-level "bundle" reason unchanged | intended | E2.6 r3 |
| test_s1_t12_fix1::test_fix1_i4b_a_corrupt_trial_seal_is_a_preserved_terminal_integrity_failure | the next checkpoint's capture observes it: TRIAL-INVALID established-violation/seal-record, report + abort | the next checkpoint's gate: TRIAL-INVALID (stage-replaced) before any capture (no capture dir of the next close, no seal); its evidence copy names stage seal/2026-10-26 | intended ("never a crash with no record" kept; earlier and external) | E2.6 r3 |
| test_s1_t12_fix2_b2::_scored_state (4 tests) | the seal bytes edited after the fixture wrote them | the binding disposition injected as the capture's own (`_write_seal(process_binding=)`; "missing" = null); the sealed bytes stay the stage's | fixture | E2 r3 |
| conftest::_write_seal(process_binding=) | - | new keyword (default MATCH of S1_BINDING) | fixture | - |
| test_s1_t12_a2::test_a2_no_valid_seal_is_terminal_persisted_and_never_rescued_by_a_late_seal | the late rescue seal written by the fixture | no seal stage can start after the STOP: the rescue seal is a file outside any stage (the opening seal's bytes) -> registration artifact at the score's gate; the unit-level record assertions unchanged | intended | E2.4/E2.6 r3 |
| test_s1_t12_a2::test_a2_integrity_of_the_frozen_slices_is_enforced_at_score[3] | s1_score_refused(registration-artifact); extra seal via the fixture | edited/deleted: reason stage-replaced; extra: a stage-less file (registration-artifact); unit-level record unchanged | intended | E2.4/E2.6 r3 |
| test_s1_t12_a2::test_a2_post_stop_checkpoints_follow_the_persisted_stop | (failed in run 1: the seal stage sealed 10-28 after the persisted stop) | unchanged - product: run_seal_stage refuses while stop.json exists (Deviation 9, transitional until Task 11) | none (product) | A2.1/A2.2 |
| test_s1_t12_fix2_b1::test_b1_the_reviews_overlap_race..., test_b1_a_claim_without_a_report_stays_pending... | (failed in run 1: the deferred text lacked "pending" / the slot) | unchanged - product: the finalizer's deferred text names the slot and says pending (as the legacy text did) | none (product) | - |
| test_s1_t12_fix2_b1::test_b1_expiration_racing_a_late_completion_cannot_change_the_winner[3] | ck.finalize_close(..., rows=rows) twice; journal rows unchanged by the replay | the finalizer command ck.finalize_close(out, day, cal, t) (no rows=; the legacy branch is removed); the first call also appends the later past-E slots' MISSED rows, so the replay snapshot is taken after it; the replay at D45 + 2 min changes nothing; the winner's terminal row stands | intended (the finalizer appends MISSED, F3) | F3, E1.5 |
| test_s1_t12_fix2_b1::test_b1_concurrent_finalizers_and_restart_replay_give_one_deterministic_seal; test_s1_t12_fix3::_two_successes_no_seal, _success_without_seal | crash injected by patching ck.finalize_close | patched s1_slot.finalize_close (the worker path's journal finalizer); the concurrent / replay finalizers are still ck.finalize_close | fixture | - |
| test_s1_t12_fix2_b3::test_b3_post_stop_integrity_of_frozen_artifacts_is_persistent | "registration artifact(s) missing or changed", abort reason registration artifact | "member seals/... missing or changed ... INVALID (stage-replaced)"; persistence: the next command refuses "trial INVALID (reason/stage-replaced)" and the abort records it | intended | E2.6 r3 |
| test_s1_t12_fix2_mutants::test_mt_an_arbitrary_report_file_does_not_resolve_a_slot | the dropped report resolves nothing: slot 45 MISSED (file), seal from 47 | the dropped report is itself the F3 "no row" violation at the finalizer's gate: INVALID registration-artifact, no MISSED file, no seal, abort | intended (stronger) | F3 |
| test_s1_t12_fix2_mutants::test_mt_a_forged_success_without_complete_evidence_never_seals | never selected; the later slot 47 seals | never selected: INVALID registration-artifact at the next gate, no seal (the detection half is the un-held sibling) | intended | F3 |
| test_s1_t12_fix2_mutants::test_mt_an_unbound_corrupt_seal_is_a_preserved_abort_not_a_crash | the capture's own seal read: established-violation / seal-record | gate: INVALID (stage-replaced) before any capture; no other exception escapes; the evidence copy names the stage | intended | E2.6 r3 |
| test_s1_t12_fix2_mutants::test_mt_a_resolution_claiming_success_for_a_late_capture_never_seals | ValueError "without complete evidence" | SystemExit "resolution exists with no journal row ... INVALID (registration-artifact)" | intended | F3 |
| test_s1_t12_fix3::test_c1_a_concurrent_finalizer_and_a_reader_never_observe_a_partial_seal | both finalizers report the seal's sha256 | A writes and reports it; B (inside A's publication window) is refused "pending" by the stage lock (sha256 None); still no partial seal observed and exactly one written | intended | E2.1 r3, F5.1 |
| test_s1_t12_fix3::test_c2_deleting_..._persistent_abort[3], test_c2_probe_seals_registry_and_reports_deleted..., test_c2_the_external_run_ack_witnesses..., test_c2_residual_... (second half), test_c2_retro_the_run_ack_alone... | match "registration artifact(s) missing or changed" | match REG_OR_F3 (that, or the F3 table's "QUALIFIED tree differs ... INVALID (registration-artifact)"): the deleted reports/resolutions are the opening slot's QUALIFIED tree; the abort reason (registration artifact) and the "restoring never resumes" checks are unchanged | intended (same disposition, detected first by the journal-bound table) | F3 |
| test_s1_t12_fix3::test_c1_retro_an_unreadable_seal_stops_the_checkpoint_before_any_seal | the checkpoint aborts on the corrupt record (seal-record) | gate: INVALID (stage-replaced) before any capture; no next-close capture or seal | intended | E2.6 r3 |
| test_s1_t12_fix3::test_i2_a_stray_seal_before_the_opening_is_a_preserved_refusal_never_an_abort[2026-01-01.json] | pre-opening refusal, no abort, the opening then runs | a stage-less seal of a non-opening close is INVALID (registration-artifact) "in every state": zero callbacks, no claim ([2026-10-23.json], the opening close, unchanged) | intended | E2.4 r3 |
| test_s1_t12_fix4::test_n3_probe_two_handmade_later_stage_files_before_any_opening_are_a_refusal[pair0] | refusal, no abort | (prereg.json, seals/2026-01-01.json): INVALID (registration-artifact) at the gate, zero callbacks; the other pairs unchanged | intended | E2.4 r3 |
| test_s1_t12_fix6::test_f1_probe_fabricated_earlier_close_evidence_before_the_opening_is_a_refusal[3] | refusal, no abort, a preserved refusal record | hand-made slot claims (no row) / a stage-less seal: INVALID (registration-artifact) at the gate, zero callbacks; the calendar-free anchor assertion unchanged | intended (Addendum 3 F3/E2.4 governs over A2 B3.2 for these files) | F3, E2.4 r3 |
| test_s1_t12_fix5::test_r2_probe..., test_s1_t12_fix7::test_g1_probe...[2], test_s1_t12_fix8::test_h1_probe...[3], test_h2_probe... | (failed in run 1: the edited plan's opening_close made the genuine opening seal look like a stage-less seal - INVALID with a misleading record) | unchanged - product: after any row, a plan.json that is not the AUDIT-ACK's plan_sha256 runs the legacy detector first (Deviation 10) | none (product) | A8.1, OQ-19 |
| test_s1_t12_mutant_followups::test_mf_a_tampered_deferred_capture_never_seals | unchanged | unchanged (the product message keeps "QUALIFIED tree differs from the committed detail") | none | F3 |
| test_s1_t12_mutant_followups::test_mf_the_final_plan_refuses_a_changed_frozen_slice | match "frozen slice" | match "seals/2026-10-26.json missing or changed ... INVALID (stage-replaced)" at the final plan's gate | intended | E2.6 r3 |
| test_s1_t12_mutant_survivors::test_ms_stop_problems_reports_an_extra_seal_among_the_frozen_slices | the extra seal written by the fixture (after the STOP) | a stage-less file (the opening seal's bytes); stop_problems, the unit under test, unchanged | fixture | E2.6 r3 |
| test_s1_task11::test_c1_final_snapshot_and_score_check_fences_only_against_seals_up_to_the_stop | a later-close seal written by the fixture after the STOP; the command's report checked | the later-close seal is a legacy file (the stop seal record, close 10-29 + the ghost row): the command is INVALID (registration-artifact); the fence logic is checked at unit level (_final_snapshot_capture, finalize_pending no-op) and through the score's unit-level record - both oracles unchanged | intended + fixture | E2.4/E2.6 r3 |
| test_s1_task11::test_i1_score_requires_every_seal_and_itself_to_match_the_prereg_toolchain | s1_score_refused(registration-artifact) | reason="stage-replaced"; the "bundle" reason unchanged | intended | E2.6 r3 |
| test_s1_task11::test_m2_capture_report_naming_a_seal_that_is_not_on_disk_is_aborted_invalid[2] | made required by synthetic stage rows (_created_seal_stage) | already required (the fixture's real CREATED stage; asserted with required_seals); _created_seal_stage removed (its staging dir now exists) | fixture | E2.6 r3 |
| test_s1_run::test_cr_plan_key_error_is_a_recorded_reason | s1_score_refused: "trial INVALID (reason/registration-artifact)" | unchanged text; the widened helper also accepts the legacy detector's committing refusal ("registration artifact(s) missing or changed"), which the gate now runs first for a plan.json that is not the AUDIT-ACK's (Deviation 10); the unit-level "KeyError: 'planned_start'" reason unchanged | fixture (helper) | A8.1, OQ-19 |
| conftest::s1_score_refused (second widening) | - | for reason="registration-artifact" also "registration artifact(s) missing or changed" (the legacy detector commits the same TRIAL-INVALID, OQ-19) | fixture (helper) | OQ-19 |
| test_s1_t12_a3_a8::test_a8_opening_mode_verifies_the_audit_ack_plan_calendar_and_source_bindings_before_capture[plan_edited_after_audit] | "audit is not bound to the current plan" | unchanged - product: the gate's plan step runs only the legacy detector (no own refusal), so before any registration the command's A8.1 refusal is the one seen (Deviation 10 refined) | none (product) | A8.1 |

## Task 8 old -> new

Source: `a3/t8_old_new.md`, sha256 `5ceb857e6623adaddbe0a13c91e98af60661c26db4ec89df093171a86296ce8a`


Base 165e0b0. With `s1_stage.ENFORCED = frozenset()` and `s1_stage.SEALS_ENFORCED = False` (transitional), the
gate's new `s1_stage.evaluate(gv)` hook evaluates no TABLE stage and no rowless seal file, so no existing test
changes outcome (t8_full.txt). The only edit to an existing test file:

| file | old | new | class |
|---|---|---|---|
| research/s1/s1_tests/test_s1_t12_a3_a8.py `BUNDLE` | `(..., "s1_snapshot.py", "s1_trial.py")` | `(..., "s1_snapshot.py", "s1_stage.py", "s1_trial.py")` | intended (A3.1: s1_stage.py joins BUNDLE_CODE; the test pins the explicit list and that every s1_*.py is listed) |

New files: research/s1/s1_stage.py, research/s1/s1_tests/a3_helpers.py (test-only helpers and child-process entry
points; not a test module, never imported by product code), research/s1/s1_tests/test_s1_a3_stage.py.

Regressions: none.

## A3 Task 9 - old -> new (every migrated legacy test, classified)

Source: `a3/t9_old_new.md`, sha256 `e68a8849cffc57e20689fb8ddad4e1c04e24f6262a83e3fdeafd6b17e92c7ecb`


Classes: intended (a spec clause changes the expected outcome; the row's oracle is replaced by the spec's, never weakened), fixture (test setup or reach only; the oracle is unchanged), strengthened, none (the test is unchanged; a product fix made it pass again). No requirement-map row outcome changed.

| file::test | old oracle | new oracle | class | spec |
|---|---|---|---|---|
| test_s1_collect::test_audit_once_metadata_only | second do_audit: SystemExit "an attempt already exists; one attempt only" | second do_audit: SystemExit "stage audit is already CREATED: re-entry refused (F1)", and no further request (call count unchanged) | intended (+ strengthened: zero requests asserted) | F1 "each stage once", F4 stage table |
| test_s1_collect::test_audit_aborts_on_bad_calendar[6] | SystemExit "audit: ABORTED (Structural)"; s1_out/audit/manifest.json outcome ABORTED, error_type Structural, pages non-empty; retry "an attempt already exists" | SystemExit "stage audit: INVALID (provider-structural)"; staging ABORTED.json outcome ABORTED, error_type Structural, provenance non-empty, every provenance page kept in staging; no prepared.json; nothing under s1_out/audit; retry: "trial INVALID (reason/provider-structural)" | intended | F4.6 provider anomaly, F8.5 no retry |
| test_s1_collect::test_audit_midrun_http_failure_writes_aborted_manifest | ABORTED manifest in s1_out with "HTTP 429", 2 page hashes; no key text in non-page s1_out files | staging ABORTED.json with "HTTP 429", 2 provenance entries whose page_sha256 equal the staged pages; no key text in non-page files of s1_out AND s1_staging | intended (+ strengthened: hashes checked against the staged bytes; staging scanned too) | F4.6 |
| test_s1_collect::test_foreign_exception_records_type_name_only | SystemExit "audit: ABORTED (RuntimeError)", no key text, no chained cause/context; manifest error_type/error = RuntimeError | SystemExit "stage audit: INVALID (provider-structural)", no key text, no chained cause/context (kept: Deviation 6); ABORTED.json error_type/error = RuntimeError | intended (message only; the no-leak oracle kept) | F4.6 |
| test_s1_collect::test_e1_structural_from_ca_validation_is_recorded | manifest outcome ABORTED, "corporate-actions root malformed" | staging ABORTED.json outcome ABORTED, the same error text | intended | F4.6 |
| test_s1_collect::test_paged_refuses_repeated_token | k._paged(cl, url, base, headers, prefix, validate, created) raises Structural "repeated" | the F4.6 signature k._paged(cl, auth, family, scope, url, base, headers, sw, validate) with a one-family policy; same Structural "repeated" | fixture (signature) | F4.6 |
| test_s1_collect::test_transport_error_message_has_no_key_text | k._get(...) Structural with no key text | the F4.6 signature k._get(cl, auth, family, scope, url, params, headers, sw); same oracle | fixture (signature) | F4.6 |
| test_s1_collect::test_get_http_error_and_non_json | Structural "HTTP 500" / "not JSON" | same, through the F4.6 signature | fixture (signature) | F4.6 |
| conftest::s1_plan_audit (journal=True) | hand-written s1_out/audit files + synthetic STAGE-INTENT/PREPARED/CREATED rows (details not the envelope/commitment) | the REAL stage s1_stage.run(gv, "audit", ...) with the real audit_policy, a fixture work staging the same objects (byte-identical except attempt.json + trial_id/intent_at and the manifest's attempt.json hash: t9_conftest_bytes.txt PASS); rows at the old times (INTENT reserved-1 s, PREPARED +2 min, CREATED +3 min) | fixture (brief Step 4) | F4.1-F4.4, F9, OQ-36 |
| conftest::s1_plan_audit (journal=False) | hand-written files, no row | unchanged | none | F6.4 |
| test_s1_a3_stage::test_seal_files_on_disk_are_evaluated_once_the_seal_family_is_enforced | static: ENFORCED == frozenset() | static: ENFORCED == frozenset({"audit"}); the seal-file oracle unchanged | intended (Task 9 adds audit to ENFORCED) | F4 table, Task 8 D5 |
| test_s1_a3_slots::test_an_opening_slot_needs_the_created_audit_stage | journal=False audit -> opening refused "the audit stage is not CREATED", zero callbacks, no slot row | command: "stage audit: artifacts ... with no INTENT: INVALID (registration-artifact)", zero callbacks, no slot row, the only row TRIAL-INVALID; unit level: s1_slot.opening_gate(...) on those rows returns "the audit stage is not CREATED: no opening capture" | intended (+ the gate's reason kept at unit level) | F4 table 'no INTENT', F9 |
| test_s1_connected::test_connected_lifecycle_matches_independent_oracle[4] | after do_audit the test appended synthetic audit STAGE rows | do_audit is the real stage; the test asserts its three rows (INTENT, PREPARED, CREATED on stage/audit) instead of appending them; every lifecycle oracle unchanged | fixture | F9 |
| test_s1_run::test_cr_prereg_refusal_paths | edited audit manifest (outcome ABORTED) -> do_prereg "prereg refused: registration artifact" | do_prereg: "stage audit: ... audit/manifest.json ... INVALID (stage-replaced)"; no prereg.json; unit level: s1_common.registration_gate(out, "prereg") still raises "registration artifact(s) missing or changed" | intended (+ detector kept at unit level) | F4 table CREATED, F4.9 consistency |
| test_s1_run::test_cr_incomplete_audit_is_a_recorded_reason_not_a_score_error | s1_score_refused(reason registration-artifact); unit record has the "audit attempt outcome is 'ABORTED'" reason | s1_score_refused(reason="stage-replaced"); unit-level record assertions unchanged | intended | F4 table CREATED |
| test_s1_t12_a3_a8::test_a8_opening_mode_verifies_..._before_capture[no_ack_recorded, plan_edited_after_audit, manifest_plan_sha, raw_page_tampered, calendar_source_tampered] | opening refused with the A8.2/A6 reason (WHY478) | opening: "stage audit: ... INVALID (stage-replaced)" (a changed member, or the bound input plan.json), zero callbacks, no captures; unit level on the same files: s1_gates.verified_audit raises the WHY478 reason (no_ack_recorded: s1_common.registration raises it) | intended (+ every A8.2/A6 reason kept at unit level) | F4 table CREATED, F4.9 consistency |
| test_s1_t12_a5_a6::test_a5_five_sessions_are_counted_from_the_audit_acks_recorded_time; ::test_a6_completeness_is_checked_against_the_pinned_listing[5] | SystemExit "ABORTED"; s1_out/audit/manifest.json outcome ABORTED with the reason text | SystemExit "stage audit: INVALID (provider-structural)"; conftest.s1_audit_aborted: staging ABORTED.json (outcome ABORTED, the same reason text), no prepared.json, nothing under s1_out/audit, TRIAL-INVALID provider-structural | intended (+ strengthened: INVALID row and no publication asserted) | F4.6 |
| test_s1_t12_fix10::test_m1_a_session_closing_before_the_earliest_early_close_refuses_the_audit[3] | bare SystemExit; manifest ABORTED, Structural, "earliest" + day in error | SystemExit with match S1_AUDIT_ABORTED; the staged ABORTED record, same assertions | intended (+ match= added) | F4.6 |
| test_s1_t12_mutant_survivors::test_ms_four_sessions_after_the_audit_ack_abort | "ABORTED"; manifest error "fewer than 5 sessions" | S1_AUDIT_ABORTED; staged ABORTED error "fewer than 5 sessions" | intended | F4.6 |
| test_s1_t12_mutant_survivors::test_ms_an_audit_ack_message_without_the_exact_audit_token_refuses | journal=False; opening refused "audit token" | opening: "stage audit: artifacts ... with no INTENT: INVALID (registration-artifact)"; unit level: s1_gates.verified_audit raises "audit token" (the mutant's killer) | intended (+ killer kept at unit level) | F4 table 'no INTENT' |
| test_s1_t12_mutant_survivors::test_ms_audit_ack_causal_timing_is_checked_on_its_own[2] | opening refused "before the plan / not after the plan / before the audit reservation" | opening: "stage audit: ... audit/manifest.json ... INVALID (stage-replaced)"; unit level: s1_gates.verified_audit raises the same causal-order reason | intended (+ killer kept at unit level) | F4 table CREATED |
| test_s1_t12_mutant_followups::test_mf_a_calendar_json_differing_from_its_pinned_raw_page_refuses; ::test_mf_a_calendar_pinned_with_other_request_parameters_refuses | opening refused "pinned raw page" / "request parameters" | opening: "stage audit: ... INVALID (stage-replaced)"; unit level: s1_gates.verified_audit raises "pinned raw page" / "request parameters" | intended (+ killer kept at unit level) | F4 table CREATED, F4.9 |
| test_s1_t12_fix2_b3::test_b3_a_registered_artifact_changed_or_deleted_then_restored_stays_invalid[audit/manifest.json, audit/calendar.json x changed, deleted] | "registration artifact(s) missing or changed"; abort reason registration artifact; restored -> "trial INVALID (reason/registration-artifact)" | "stage audit: ... member <rel> missing or changed ... INVALID (stage-replaced)"; restored -> "trial INVALID (reason/stage-replaced)"; the local abort records reason/stage-replaced (restoration never resumes) | intended | F4 table CREATED, F4.9 |
| test_s1_t12_fix9::test_h3_probe_a_session_inserted_into_the_calendar_after_the_opening_seal_aborts[2] | bare SystemExit; abort reason registration artifact; restored -> attest_start bare SystemExit, abort stays | match "stage audit: ... audit/calendar.json ... INVALID (stage-replaced)"; restored -> attest_start "trial INVALID (reason/stage-replaced)"; abort records reason/stage-replaced; no attest_start.json | intended (+ match= on both raises) | F4 table CREATED |
| conftest::s1_audit_aborted, S1_AUDIT_ABORTED | - | new helper: the staged ABORTED record + no PREPARED + nothing published + TRIAL-INVALID provider-structural | fixture (new helper) | F4.6 |

## A3 Task 10 - old -> new classification

Source: `a3/t10_old_new.md`, sha256 `ba35b2ad1ba9511311fbefde5bb4ef1ddff2d6932c3c20b6bfa85f6f1fc837d0`


Erratum 1 adoption state: ADOPTED (de008b1; the adopted copy research/s1/docs/s1_design_v5_addendum3_erratum1.md,
revision 4, sha256 b03464669673927fdb057acad9b0dc3258b1f08692d55ec3b0cffd4550f6ca2f - s1_common.DOC_PINS). E3 (BLOCKED
as a pre-INTENT refusal record, closed by Codex with reason BLOCKED, h = sha256(canonical{trial_id, reasons}); S1 never
recomputes a historical CLOSE's evidence; closure monotone) is implemented as adopted; it is no longer "pending".

Classes: **fixture** (a fixture/time change only, the oracle unchanged), **intended** (a requirement of Addendum 3 /
Erratum 1 changes the outcome; the old reason is kept as a unit-level oracle where it was a killer), **un-held**.
No assertion was weakened: every migrated command-level regex names the stage and the damaged member
(`conftest.s1_replaced(rel)`), and where the old oracle was the B3.3 detector's finding, the same finding is asserted
on the same tampered files at unit level (`s1_common.registration_problems`, `s1_slot.evidence_problems`,
`s1_run._score` through `s1_score_refused(..., reason="stage-replaced")`).

### Fixture changes (F7.2(b) literal, OQ-37 ruling, E5.6)
- `conftest.s1_state`, `conftest.s1_register`: after the opening checkpoint the new `s1_close_out` runs the journal
  finalizer to the E of the opening close's last (W) slot, then the OPENING-ACK is issued with NO `opening_slot` /
  `evidence_manifest_sha256` override (`s1_trial.token` derives both). The START attestation, RUN-ACK and prereg follow
  at E_W + 2 / 3 / 4 min (the old instants START - 2 d / - 1 d 1 h / - 1 d now precede the OPENING-ACK); the
  PREREG-ACK at + 5 min (s1_register). `info["now"]` = max(START - 12 h, prereg + 1 min); new keys `attest_at`,
  `opening_acked_at`. New `s1_state(attest=False)`: the pre-attestation state (replaces `s1_unattest`, whose file
  deletion is now stage-replaced because the attestation is journal-committed).
- New helpers: `s1_close_out`, `s1_prereg_at` (RUN-ACK + 1 min: the fixture's causal prereg instant), `s1_replaced`,
  `s1_first_invalid`.
- The prereg instant START - 1 day (START - 2 h in test_s1_run / checkpoint_7b, st_["start"] - 1 d in a4) before a
  `do_prereg` call -> `s1_prereg_at(tmp_path)`: 37 lines in a1, a1b, a2, a3_a8 (3), a4, a5_a6, a9, checkpoint_7b (2),
  fix1, fix2_b2, fix2_b3 (3), fix2_mutants, fix3 (5), fix4, fix5 (2), fix6, fix7, fix8, mutant_followups (2),
  mutant_survivors (2), task11 (5); 10 `at(...)` lines in test_s1_run. (t10_mig_prereg.txt lists each
  line.) This repaired the 189 fix8 setup errors and 56 "RUN-ACK in the future" failures of discovery run 1.
- test_s1_a3_gate: `_damage` posts after the trial's latest ACK (was 2026-10-25T23:00, before the new ACKs);
  closure_never_erases_invalidity and product_context_reads_closed post their CLOSE after `st_["now"]`;
  product_context_fails_closed uses stage `prereg` (start_attest is now a CREATED stage: a second INTENT is
  repeat-stage at 4b before the step-5 fail-closed check it tests).
- test_s1_connected: the OPENING-ACK after `s1_close_out`, without the `"e" * 64` override (the gate's E5.5 hook
  would otherwise INVALIDATE); attestation / RUN-ACK / prereg / PREREG-ACK at E_W + 2..5 min.
- test_s1_checkpoint_7b: `_opening_acked` (close-out + OPENING-ACK) before the two attestations.
- test_s1_task11 i1 / i5: the prereg instant read before the malformed line / the mailbox move.
- test_s1_t12_fix4 `_stage_run` / `_interleave` / minor: s1_state(attest=False) for the attestation; the hook
  patches `s1_common.publish_exclusive` (the stage engine's member publication) instead of publish_text_exclusive.
- test_s1_t12_mutant_followups `test_mf_an_edited_opening_books_file_refuses_the_start_attestation`: the
  pre-attestation state, with the existing books file = the recomputation (exact published bytes) with one field
  changed (same oracle: "opening_books.json differs").
- test_s1_run attest_start_requires_exact_statement_once_and_before_start / cr_attest_start_statement_receipt_and_clock /
  prereg_refusals_write_nothing[attest]: from s1_state(attest=False) instead of s1_unattest (same refusals).
- test_s1_t12_a3_a8 a8_attest_start_refuses_before_the_opening_seal_capture, test_s1_t12_fix4
  n3_retro_the_attestation_between...: s1_state(attest=False).

### Intended changes
- **F4 table CREATED (opening / start_attest / prereg ENFORCED) pre-empts the B3.3 detector** (plan Task 10 Step 6:
  "N-2/R-3 (fix rounds 4/5) -> F3 + F4: opening orphan and after-seal tests now see INVALID (stage-replaced ...)").
  A changed, deleted or unparseable opening seal, opening_receipt.json (opening input), attest_start.json,
  opening_books.json (start_attest input) or prereg.json is `stage <g>: [... member|bound input <rel> missing or
  changed ...]: INVALID (stage-replaced)` at the gate (TRIAL-INVALID first, no work; the local aborted.json at the next
  gate, "journal INVALID (reason/stage-replaced)"), instead of the legacy "registration artifact(s) missing or
  changed" abort. Restoring never resumes ("trial INVALID (reason/stage-replaced)"). Unit-level oracle kept.
  Tests: fix2_b3 (the_opening_changed..., registered_artifact_changed_or_deleted[attest_start, opening_books, prereg,
  seal, opening_receipt x changed/deleted], deleting_prereg_and_the_opening_together[2], opening_re_entry (named in
  Step 6), an_earlier_bundle_abort_stays_first (first-wins "bundle" kept), registration_artifact_violation_at_the_score);
  fix3 (c2_deleting_an_artifact_with_its_registry_record[8 combos; plan+registry unchanged], c2_probe_deleting_prereg...,
  c2_probe_seals_registry_and_reports..., c2_the_external_run_ack_witnesses..., c2_residual (its outage half unchanged),
  m3_a_registration_abort_before_the_final_snapshot, c2_retro_the_run_ack_witnesses_the_attestation,
  c2_retro_prereg_binds_the_attestation_even_when..., c2_retro_the_run_ack_alone..., c2_retro_a_post_start_capture...);
  fix4 n2_reopening_after_the_local_witnesses_are_deleted[3] (named in Step 6); fix5 r3_deleting_the_seal...,
  r3_the_after_seal_claim_alone... (named in Step 6; the F3 "QUALIFIED tree differs" finding kept via
  s1_slot.evidence_problems); test_s1_run cr_each_prereg_binding_alone[6], cr_prereg_start_or_calendar_alone[4],
  cr_prereg_refuses_when_the_opening_seal_is_missing, attest_start_requires_exact... (seal half),
  cr_attest_start_statement... (seal half); a3_a8 a3_score_checks_bundle_consistency[prereg] (now also the unit-level
  ABORTED-INVALID "bundle" record, like [seal]), a8_checkpoint_verifies...[attest_edited, books_edited, prereg_binding];
  a5_a6 a6_a_dropped_session...; fix2_b2 b2_a_corrupt_bound_reference...; bridge_8b
  opening_close_error_is_a_recorded_refusal...; collect final_lag_refused..., final_ack_binds_prereg; mutant_followups
  mf_the_score_reverifies_the_run_token_bindings, mf_an_edited_opening_books_file_is_aborted_invalid_at_score;
  a3_gate registration_violation_commits_trial_invalid_first (its legacy-only damage is now prereg's registry record,
  which no stage commits: the OQ-19 oracle unchanged).
- **F4 table "no INTENT: any artifact for g is a violation after the AUDIT-ACK"** (opening / start_attest / prereg
  ENFORCED; the Task 7 concern-2 ruling: A3 supersedes A2 B3.2 after the AUDIT-ACK; the Task 7 review predicted the
  opening case): a hand-made prereg.json, attest_start.json or opening-close seal under an open trial is TRIAL-INVALID
  (registration-artifact) with zero callbacks, no claim and no registration manufactured, instead of the B3.2 preserved
  refusal. Tests: fix2_b3 an_invalid_handmade_prereg_before_the_opening...; fix3 i2_a_stray_seal...[2026-10-23.json];
  fix4 n3_probe_two_handmade_later_stage_files[pair0 (prereg named first: TABLE stages before seal stages), pair1,
  pair3; pair2 final_plan/attest_stop unchanged], n3_retro_a_lone_handmade_seal_of_the_opening_close.
- **F6.1 / F7.1 ACK chain pre-empts prereg's own causal check**: a RUN-ACK created before (or at) the attestation now
  also precedes the OPENING-ACK, or is not after the start_attest CREATED row it references - the gate refuses it.
  Tests: test_s1_run run_ack_not_strictly_after_start_attestation[offset -1 h: "its predecessor", offset 0: "the
  journal row it references"]; a3_a8 a8_checkpoint_verifies...[ack_before_attestation]. prereg's
  "RUN-ACK is not strictly after the START attestation" check is implied (recorded_utc <= INTENT <= CREATED < ACK):
  Task 15 should treat that line as equivalent/unkillable.
- **fix3 c2_retro_a_stage_publication_in_progress**: prereg.json is a CREATED stage member, judged by the stage table
  whatever stage.lock says (a stage in publication holds its F5 lock and has no CREATED row); the legacy stage.lock rule
  is exercised on what only the B3.3 detector judges: prereg's registry record. Same oracles (refusal "stage
  publication", no abort; then the persistent abort).
- **E5.4**: blocked.json gains `trial_id` (no existing test asserted the exact key set; test_s1_run's BLOCKED tests
  still pass). The BLOCKED refusal text keeps "S1 BLOCKED (pre-START units): <reasons>; re-register" and adds the E3
  note.
- **OQ-15**: opening_books.json keeps the c9b4322 bytes (s1_collect._write_once format); the RUN-ACK's
  `opening_books_sha256` and attest_start.json's are the file sha256 (as artifact_fields already computed); no test
  asserted `k.json_sha256(books)`.
- attest_start.json / prereg.json record `intent_at` (F4.5); `attest_start` / `do_prereg` return the published file
  (with intent_at). No existing test compared the old return value byte for byte with the file.
- test_s1_a3_stage seal_files_on_disk...: ENFORCED is {"audit", "opening", "start_attest", "prereg"}.

### Un-held
- test_s1_t12_fix3 c2_retro_the_opening_report_and_resolution_witness_the_registration (held since Task 6 "for Task
  10"): passes for its stated reason - the deleted opening seal is a CREATED `opening` member: `stage opening: ...
  member seals/2026-10-23.json missing or changed ... INVALID (stage-replaced)`, TRIAL-INVALID reason/stage-replaced,
  then "trial INVALID (reason/stage-replaced)".

### Fix round 1 (review I1, M1-M6, M8)
- **Fixture / test literal**: every test spy of `s1_common.publish_exclusive` (a3_codex_probes `delayed`, a3_slots
  `late`/`pub`/`pub47`/`pub45`, fix3 `slow`/`concurrent`/M-2 `rec`, fix4 `pub`/`disk_full`) forwards keyword
  arguments - publish_exclusive gained `mkdir=` (M5). Oracles unchanged.
- **M8 (wording corrected)**: the unit-level B3.3 oracles now name the expected member - fix3 c2_deleting...
  (STAGE_MEMBER[combo]), c2_probe_seals_registry..., c2_the_external_run_ack..., c2_retro_the_run_ack_alone...
  (the opening seal), c2_residual (the opening seal, added); fix2_b3 deleting_prereg_and_the_opening_together (both
  files), an_earlier_bundle_abort_stays_first (attest_start.json, added). The statement above "the same finding is
  asserted" holds for every migrated intended change after this round.
- New tests (no migration): test_s1_a3_prestart fix-round section (I1 x3, M1, M2 x3, M3 x2, M4, M5 x3).

## A3 Task 11 (Steps 1-3: stub + conftest) - old -> new classification

Source: `a3/t11_old_new.md`, sha256 `01bb67b3279e6fd3b4cdf5aca079c1d3dc818d67feedb6d06856744bb1612456`


### r1 (after Codex f33d0501): the clean full suite
- **t11_stub_full.txt, r1: 32 failed, 1676 passed, 3 skipped in 45:50.** It was run once, with no file edited during
  the run.
  - It is run after the stop=False migration below, so it closes the r0 re-run gap.
- The 32 failures are exactly the r1 RED of test_s1_a3_stop.py (t11_red.txt / t11_red_labels.md).
- No pre-existing test fails.
- 1676 = 1661 (the 5e97f78 baseline) + the 15 ctrl passes of test_s1_a3_stop.py.
- The 3 skips are:
  - the two pre-existing Task-11-held tests (fix2_mutants:316 and reporting:19);
  - the row 189 test held with Task 13.
- The r1 conftest change (`_write_seal` keyword hooks `minutes`, `r_at`, `q_at`, `before_qualified`, `stage_at`,
  with defaults equal to the old behaviour) changed no pre-existing outcome.
- Suite time is +11:04 over the baseline. Most of it comes from test_s1_a3_stop.py (48 tests, 3:17 alone), whose 24
  `stop_history` builds include 10 d129 close-outs (70 MISSED rows each), plus the timeout close-outs in s1_state.
- The r0 full run is kept as t11_stub_full_r0.txt.

### r0 runs (unchanged)

- Baseline (5e97f78, t10_fix1_full.txt): 1661 passed, 2 skipped, 34:46.
- Stub full suite (r0, now t11_stub_full_r0.txt), run once with no file edited during it: **24 failed, 1666
  passed, 3 skipped** in 37:28.
  - 22 failed, 7 passed and 1 skipped are the new test_s1_a3_stop.py. They are its RED (t11_red.txt,
    t11_red_labels.md).
  - The remaining 1659 passed and 2 skipped are pre-existing tests. The two pre-existing skips are unchanged: the
    Task-11-held fix2_mutants:316 deleted-stop mutant and reporting:19 R-6. Both stay held for Step 4.
  - 2 pre-existing tests changed outcome. Both are classified below.
- After migrating those 2 tests:
  - test_s1_run.py + test_s1_t12_fix3.py in full: 216 passed (t11_stub_migrated.txt). That run used an
    intermediate copy of fix3 whose line endings the editor had normalised. The bytes were then restored from HEAD
    with only the edits below applied;
  - the 2 tests on the final bytes: 2 passed (t11_stub_migrated_final.txt);
  - the full suite was NOT re-run after the migration. That is a test-input-only change to 2 tests. Expected full
    result: 22 failed (the RED), 1668 passed, 3 skipped.

### Changed outcomes (2): class **fixture** (oracle unchanged)

Cause, for both:
- conftest `s1_state(score_ready=True)` now reaches its stop through `s1_seal.decide_stop`;
- the Step-1 stub of `decide_stop` calls the legacy `current_stop`, as the brief prescribes, and that persists
  stop.json during the fixture;
- before, stop.json was first persisted by `attest_stop`. With `stop_attest=False` it was not persisted at all in
  the fixture.

Both tests use `stop_attest=False` to obtain "an ended trial with no persisted stop yet", and assert that as a
precondition.

| test | old | new (stub) | migration |
|---|---|---|---|
| test_s1_run.py::test_fr1_running_status_compared_by_value_at_the_score_gate | pass | precondition `assert not stop.json.exists()` fails | `s1_state(..., stop=False)`; `now = st_["now"] + 1 d`. st_["now"] with stop=False is the fixture's decision instant `t`, which is what `stop_attested_at` was. `s1_finalize` still supplies the TRIAL-STOP / ACQUIRE-ACK chain, as before. The oracle ("still RUNNING", no score) is unchanged. |
| test_s1_t12_fix3.py::test_c1_a_concurrent_stop_decision_never_observes_a_partial_stop_json | pass | precondition `assert not stop.json.exists()` fails | `s1_state(..., stop=False)`; `t = st_["now"]` (same instant as before). `st_["stop"]["status"]` (None with stop=False) is replaced by the literal "STOPPED", which is the value it had: default lots, a lots stop at day 1. The oracle (no partial stop.json observed; one status; registration consistent) is unchanged. |

Both files keep their original byte encoding: test_s1_run.py is LF, and test_s1_t12_fix3.py keeps its mixed CRLF/LF
with only the touched lines changed.

These two tests use the legacy `current_stop` directly or through the score. Task 11 Step 6 ("A2.1 -> F2", which
names test_s1_t12_fix3.py) revisits them when stop.json is persisted only after a TRIAL-STOP row.

### Fixture changes that changed no pre-existing outcome

- **Timeout path.** `s1_close_out` (finalize_close) on the last eligible close at its window end W, before the
  decision: about 22-70 SLOT-MISSED rows per timeout fixture.
- **decide_stop.** The (stub) `decide_stop` runs at the old decision instant t.
- **Transitional synthetic TRIAL-STOP.** It is appended only when no TRIAL-STOP row exists. On the stub that is
  always the case, at the same instant and with the same detail as Task 5. Step 4 deletes it.
- **stop.json for NO-VALID-SEAL / stop_attest=False fixtures.** stop.json is now persisted at t with
  decided_by="decide_stop". It used to be persisted by the first later command.
- **New s1_state keywords.** `stop`, `score_ack`, `seal_stage`, and `info["opening_close"]`.
- **Suite time.** +2:42 (37:28 vs 34:46). That comes from the 30 new tests (~1:37 alone) plus the timeout
  close-outs.


### Steps 4-6 (BLK-3 cleared: Codex 28e08272 ACCEPT-DISPOSITIONS on 9153062b) - old -> new

Classes:
- **intended**: an A3 / r1 requirement changes the outcome. Where the old oracle was a mutant killer, the old reason
  is kept as a unit-level oracle (Task 10's pattern).
- **fixture**: an input or timing change only; the oracle is unchanged.
- **product-fix**: a Step 4 product correction; the test is unchanged.
- **un-held**: a previously skipped test, now running.

Discovery runs before the clean one:
- A3 files after Step 4: 11 failed / 661 passed;
- non-A3 files: 49 failed / 994 passed.

Every one of these is classified below, then re-run: the 61 legacy node ids all pass, and GREEN (all A3 files) is
675 passed / 1 skipped.

#### A3 files (pre-existing tests)
| test | class | change |
|---|---|---|
| test_s1_a3_finalizer::test_no_seal_after_stop_even_for_a_pre_stop_qualified, ::test_seal_stage_and_stop_orders[publish-first,stop-first], ::test_deleted_created_seal_is_invalid_and_never_recreated[after-stop] | fixture | `_stop_row` uses `conftest.s1_synthetic_stop`: stop.json + a matching TRIAL-STOP detail. A bare synthetic STOP (detail "5"*64, no stop.json) is now a publication gap that the gate recomputes, giving INVALID (stop-conflict) by F2.3. These tests are about the STOPPED state, not the decision. |
| test_s1_a3_finalizer::test_stop_fence_refuses_a_determined_close_without_a_created_seal | fixture | Its hand-built context supplies `stop_ready` (otherwise it fails closed, M-6). The fence oracle is unchanged. |
| test_s1_a3_finalizer::test_barrier_close_between_active_read_and_prepared | product-fix | `current_stop` reads the plan's trial (open or CLOSED) instead of `open_trial`, so a CLOSE in mid-checkpoint no longer turns a display read into "zero open trials". |
| test_s1_a3_gate::test_final_snapshot_after_its_own_detection_captures_nothing | intended (F2.4) | The gate's stop_check detects the changed stop.json after the stop_attest INTENT: TRIAL-INVALID (registration-artifact), the same reason and zero captures, raised as the gate's SystemExit rather than the old re-read Refusal. |
| test_s1_a3_precedence::test_precedence_table[5-stop-fence-ok, 7-stop] | fixture | The base context supplies `stop_ready`. New rows: `5-stop-not-ready`, `5-stop-ready-at-txn-now` and `5-stop-no-readiness-supplied` (fail closed). |
| test_s1_a3_slots::test_post_stop_new_slot_intent_is_lost_race_with_no_capture | fixture | `s1_synthetic_stop`. |
| test_s1_a3_stage::test_seal_files_on_disk_are_evaluated_once_the_seal_family_is_enforced | intended | ENFORCED adds stop_attest and final_plan (F4.8). |

#### Non-A3 files
| test | class | change |
|---|---|---|
| test_s1_collect: test_final_requests_every_symbol_bars_and_full_history, test_final_refused_ack_makes_no_request, test_final_lag_refused_before_reserving, test_final_lag_refused_when_calendar_lacks_three_later_sessions, test_final_request_params_windows_and_manifest, test_final_ack_binds_prereg, test_final_aborts_on_structurally_bad_bars_page[x5]; test_s1_t12_a7::test_a7_2_codex_probe_i...; test_s1_t12_mutant_followups::test_mf_the_final_manifest_binds_the_bundle_and_the_persisted_stop | fixture | `final_setup` writes the final plan 30 min after the attestation. The final plan is a journal stage now, so the ACQUIRE-ACK (which binds the journal head) must follow its CREATED row; otherwise F6.1 refuses. |
| test_s1_run::test_attest_stop_binds_start_attestation_stop_and_sealed_ledger | intended (F4) | Deleting the CREATED attest_stop.json is INVALID (stage-replaced), never a re-attestation. The new test `test_attest_stop_refused_once_a_final_acquisition_exists` keeps the old "final exists" refusal; it also asserts stop_line_sha256. |
| test_s1_run::test_score_without_stop_attestation_is_unverified_not_nominated; ::test_cr_unverified_numeric_pass_note_only_on_a_pass[False-*] | intended (F1 graph 2-3, F4) | An unattested acquisition can no longer exist. The attestation removed after CREATED is INVALID (stage-replaced) at the score's gate. `s1_score_refused` keeps the unit-level provenance and note rules (the killers). |
| test_s1_run::test_score_stop_attestation_with_wrong_binding_is_unverified; test_s1_t12_mutant_followups::test_mf_an_attestation_binding_another_stop_json_is_unverified | intended (F4) | The edited attest_stop.json is stage-replaced at the gate; the unit-level record keeps the binding problem. |
| test_s1_run::test_score_ack_with_stale_hash_is_refused_with_no_output[attest_stop.json] | intended (F4) | The stage table refuses (stage-replaced) before the ACK field check. The `final/manifest.json` case is unchanged (final is Task 12). |
| test_s1_run::test_score_ack_after_the_stop_but_before_any_final_manifest_is_refused | fixture | Only `final/` is removed (attest_stop / final_plan are stage members now). Same oracle. |
| test_s1_run::test_cr_final_acquisition_binding_checks[plan-1, plan+1, noplan] | intended (F4) | The edited or deleted final_plan.json is stage-replaced at the gate; the unit record keeps "final plan stop" / "final acquisition unusable". |
| test_s1_run::test_fr1_attest_stop_accepts_an_equal_but_distinct_statement | fixture | Built with `stop_attest=False, final=False` (no deletion of the CREATED member). Same oracle. |
| test_s1_run::test_fr1_running_status_compared_by_value_at_the_score_gate; test_s1_checkpoint::test_fr1_main_and_trial_state_compare_modes_and_status_by_value | intended (F1/F2) | The RUNNING check reads the journal's stop (`current_stop`). The equal-but-distinct "RUNNING" is injected there instead of into stop_decision. Same killer. |
| test_s1_run::test_cr_duplicate_seal_is_a_bad_seal_record_reason; test_s1_checkpoint_7b::test_cr_final_snapshot_refuses_on_a_bad_seal_record[dup] | product-fix | They failed in discovery only because of an over-broad first version of the A4 skip. Final rule: skip only seals named for an INELIGIBLE calendar date; a junk name like zz.json is still a frozen-slice problem. The tests are unchanged. |
| test_s1_t12_a2::test_a2_the_stop_is_persisted_once_at_the_seal_with_its_identity | intended (OQ-8 r1, A4) | `decided_utc` and `decided_by` are gone. The test now asserts determined_utc (trigger provenance), rule, triggering_slot, terminal_seq, the detail equal to the STOP's, and eligible-only seals. Also `match=` on FileExistsError. |
| test_s1_t12_a2::test_a2_post_stop_checkpoints_follow_the_persisted_stop | intended (F1) | The stop close's checkpoint commits the TRIAL-STOP, so the later slot is LOST-RACE with no capture. stop.json is unchanged and nothing is sealed. |
| test_s1_t12_fix1::test_fix1_m4_a_deleted_persisted_stop_is_an_integrity_failure_not_a_recompute; test_s1_t12_fix3::test_c2_deleting_the_persisted_stop_and_its_registry_record_is_a_gate_abort; ::test_c2_retro_the_stop_records_witness_a_stop_no_report_recorded | intended (F2.3) | The journal's TRIAL-STOP detail is the stop's authority. A deletion before any finalization INTENT is the publication gap: the gate republishes the SAME bytes from the rows before the STOP (no abort, no different stop). After an INTENT the same deletion is INVALID (test_s1_a3_stop; fix2_mutants mt_a[after-stop-attest]). |
| test_s1_t12_fix2_b1::test_b1_a_pending_resolution_cannot_cause_an_early_terminal_stop_followed_by_rescue | intended (F2.2, r1 §1.3) | `current_stop` never decides. The finalizer command (MISSED at E, then decide_stop on the transaction clock >= W) decides once, and a second run 15 min later finds the same stop. The B1.5 property is unchanged. |
| test_s1_t12_fix3::test_c1_a_concurrent_stop_decision_never_observes_a_partial_stop_json | intended (F2.2/F2.3) | Command A is decide_stop (TRIAL-STOP, then the exclusive publication). Command B reads in the publication gap and gets the STOP's own record recomputed (`current_stop`, persisted=False), never a partial file. Same assertions. |
| test_s1_t12_fix3::test_i1_the_stop_attestation_finalizes_before_it_freezes_the_stop; ::test_i1_the_final_plan_finalizes_before_it_freezes_the_stop | intended (F1, F2.2, r1 A2) | Finalization commands never decide or finalize a stop. In the crash window the close is UNRESOLVED, so they refuse ("no stop recorded (status RUNNING)" / "the trial is RUNNING"). After the finalizer command the stop is the TIMEOUT at the sealed close, the same end property (never NO-VALID-SEAL with the seal lost). |
| test_s1_t12_fix3::test_i1_the_score_refuses_while_a_success_lacks_its_seal | intended (F1) | No TRIAL-STOP in the crash window, so no SCORE-ACK chain exists and the score refuses ("S1-SCORE-ACK"). No STOP row, no stop.json, no score. |
| test_s1_t12_fix3::test_c1_retro_a_bad_seal_record_stops_the_checkpoint_before_any_seal | intended | The checkpoint no longer decides a stop over seal files. The future seal is caught by the row fence ("backdated to <= sealed close 2026-10-28"): the same abort before the own close is sealed; only the recorded reason changes. |
| test_s1_t12_fix4::test_n3_probe_two_handmade_later_stage_files_before_any_opening_are_a_refusal[pair2] | intended (F4 table) | attest_stop.json / final_plan.json are ENFORCED stage artifacts, so they are INVALID (registration-artifact) at the gate, as Task 10 did for start_attest / opening. |
| test_s1_t12_mutant_followups::test_mf_a_stop_json_naming_a_non_qualifying_close_is_aborted_invalid | intended (OQ-8) | The recheck is "stop.json == stop_record over the rows before the TRIAL-STOP": a new message, still caught. |
| test_s1_t12_mutant_followups::test_mf_the_final_plan_binds_the_persisted_stop | intended (F4) | The command is stage-replaced; the binding check (`k._stop_attestation`) is asserted at unit level. |
| test_s1_t12_mutant_survivors::test_ms_stop_problems_reports_an_extra_seal_among_the_frozen_slices | intended (r1 A4) | A seal named for an ineligible calendar date is not a frozen-slice candidate (its integrity is E2.4/E2.6 at the gate). The extra seal is now `zz.json`, which still kills "extra slices ignored". |
| test_s1_task11::test_i4_final_plan_refused_after_an_abort; ::test_i4_final_plan_refused_without_the_stop_attestation | fixture | Built with `final=False` (and `stop_attest=False`) instead of deleting the CREATED final_plan.json. Same oracles. |
| test_s1_task11::test_i4_do_final_rechecks_the_stop_before_reserving[hand-typed plan] | intended (F4) | A hand-typed final_plan.json is stage-replaced at do_final's gate. do_final's own re-derivation is now defence in depth (for Task 15: equivalent/unkillable from the command). |
| test_s1_task11::test_i4_do_final_rechecks_the_stop_before_reserving[ack before attestation] | intended (F1 graph 4 / F6.1) | An ACQUIRE-ACK before the attestation is necessarily before final_plan's CREATED row, so F6.1 refuses it first. |
| test_s1_task11::test_m1_final_plan_edited_after_the_acquisition_is_aborted_invalid | intended (F4) | stage-replaced at the gate; the unit record keeps "final plan". |
| test_s1_connected (end-to-end) | intended (F2.2) | The stop close's own checkpoint commits the real TRIAL-STOP; the Task 5 synthetic append is replaced by an assertion that it exists. |
| test_s1_t12_reporting::test_r6_... | un-held | Both captures (a clock-refused early invocation and a binding gap) are committed BEFORE the real STOP. That checkpoint's decide_stop commits it; then `conftest.s1_finish` runs the post-stop chain. |
| test_s1_t12_fix2_mutants::test_mt_a_deleted_stop_...[publication-gap, after-stop-attest] | un-held | Publication gap: recovered with the same bytes, LOST-RACE, no seal, no abort. After the stop_attest INTENT: `match="stop\.json missing: INVALID \(registration-artifact\)"`, no recompute, no seal. |

#### Fixture helpers (conftest)
- `s1_synthetic_stop(root, at, record=None)` (new): a consistent synthetic STOP for STOPPED-state tests.
- `s1_finish` / `_s1_finish` (new): `s1_state`'s post-stop chain, extracted unchanged.
- `s1_finalize`: a real decide_stop at `at - 1 min` when committed history gives a stop, else `s1_synthetic_stop`.
- `s1_jappend`'s synthetic context supplies `stop_ready`.
- The D1 synthetic fallback is deleted; `s1_state` asserts that decide_stop committed the STOP.

#### Result
- GREEN (t11_green.txt, all A3 files): 675 passed, 1 skipped (row 189, held with Task 13).
- Full suite (t11_full.txt, one clean run, no edits during it): **1719 passed, 1 skipped in 49:51**.
  - The skip is row 189 (Task 13).
  - The two previously Task-11-held tests (fix2_mutants mt_a, reporting R-6) now run and pass.

### Fix round 1 (review task-11-review-verdict.md; progress.md Rulings C1/S4-1, M1, I1/I2)

Reclassified (review I2 ruling: they reach the stop end to end through the PRODUCT finalizer command again, with
their original property asserted):

| test | class | change |
|---|---|---|
| test_s1_t12_fix3::test_i1_the_stop_attestation_finalizes_before_it_freezes_the_stop | intended (F1/F2.2), property restored | The attestation still refuses in the crash window, because it binds and never decides. The operator's product finalizer command (`s1_checkpoint.py --finalize` -> `run_finalizer`) then finalizes the close and decides the stop. The attested stop is TIMEOUT at the sealed close: the pre-A3 property "never NO-VALID-SEAL with the seal lost", end to end through a product command. It was ck.finalize_close before. |
| test_s1_t12_fix3::test_i1_the_final_plan_finalizes_before_it_freezes_the_stop | intended, property restored | Same, for the final plan. |
| test_s1_t12_fix2_b1::test_b1_a_pending_resolution_cannot_cause_an_early_terminal_stop_followed_by_rescue | intended, property restored | Two `run_finalizer` runs, 15 min apart, decide the same stop once. It was ck.finalize_close before. |

New tests (test_s1_a3_stop.py), with RED in t11_fix1_red.txt and GREEN in t11_fix1_green.txt:
- **C1:**
  - `test_sealed_last_close_reaches_its_timeout_through_the_finalizer_command`;
  - `test_sealed_last_close_reaches_its_timeout_through_a_later_checkpoint`;
  - `test_the_finalize_mode_dispatches_to_the_finalizer_command`.
- **M1:** `test_the_finalizer_command_decides_on_the_append_clock_not_its_start_instant[pre<W<=txn, txn<W<=pre]`.
- **I1:** `test_a_stop_json_read_error_is_confirmed_and_never_invalidates[transient, persistent]`.
- **M2:** `test_the_score_threads_its_mailbox_into_the_stop_read`.
- **M3:** `test_a_publication_failure_after_the_stop_row_is_reported_truthfully`.
- **M4:**
  - `test_a_gap_whose_recompute_raises_is_never_left_silent`;
  - `test_a_damaged_slot_tree_in_the_gap_is_judged_by_the_evidence_table` (ctrl in the RED: F3 already decides it).
- **M5:** `test_a_busy_stop_lock_defers_but_another_lock_error_is_a_refusal`.
- **M7:** `test_persist_stop_never_recreates_a_lost_s1_out`.

Gate order after fix round 1:
1. journal INVALID;
2. LOST;
3. bundle;
4. plan;
5. `stop_check` (stop.json present: compare, confirmed by a re-read; after a finalization INTENT: missing / changed
   is INVALID);
6. the F4 stage table;
7. the F3 evidence table;
8. `stop_gap_recover` (the F2.3 publication gap);
9. the opening manifest check.

No other pre-existing outcome changed: see t11_fix1_full.txt.

## A3 Task 12 (final acquisition stage) - old -> new classification

Source: `a3/t12_old_new.md`, sha256 `3a5cb982fedfd47bd51d886139b96c2bfe82a4ed342f5c000f2511d0823fc004`


Baseline: 87209f7 (Task 11 fix round 1, `t11_fix1_full.txt`): 1732 passed, 1 skipped.

What changed in product code:
- `s1_collect.final_policy` (F4.6/F4.9 final rows);
- `do_final` runs as stage `final`: it adds the OQ-22 ACK lag check and an INTENT-fixed cutoff (C-b), and work,
  ABORTED and members go through the stage engine (C-a);
- `s1_stage.ENFORCED` gains `final`;
- the legacy request helpers `_legacy_get`, `_legacy_paged`, `_legacy_corporate_actions`, `_write_page`,
  `_page_hashes`, `_abort` and `_run_attempt` are removed;
- `_reserve` is kept: `s1_run.score` still calls it until Task 13. See the report, deviation 1.

Discovery: one run of every non-A3 file on the implementation, before the migrations (scratch, not evidence):
**18 failed, 1026 passed**. Plus one A3 run: 1 failed, 724 passed, 1 skipped. Each of those 19 outcomes is
classified below. After the migrations, the 7 touched files gave 398 passed, and the A3 files are `t12_green.txt`.

### intended (F4.9 / OQ-22 / F1 "each stage once"): oracle changed to the new rule
| test | old | new |
|---|---|---|
| test_s1_a3_stage::test_seal_files_on_disk_are_evaluated_once_the_seal_family_is_enforced | static `ENFORCED == {...}` without final | the set includes `final` (Task 12 adds its stage) |
| test_s1_collect::test_final_requests_every_symbol_bars_and_full_history | 2nd do_final: "an attempt already exists; one attempt only" | "stage final is already CREATED: re-entry refused (F1)"; still no request |
| test_s1_collect::test_final_aborts_on_structurally_bad_bars_page[x5] | "final: ABORTED (Structural)" + s1_out/final/manifest.json outcome ABORTED | "stage final: INVALID (provider-structural)"; ABORTED.json in staging (outcome ABORTED, error_type Structural, non-empty provenance), nothing under s1_out/final, first TRIAL-INVALID = reason/provider-structural (brief Step 6, third bullet) |
| test_s1_collect::test_final_lag_refused_before_reserving | at 19:59 "acquisition lag not met" | the ACK is now at the lag (input below), so at 19:59 it is still in the future: `ack is in the future\|acquisition lag not met`; at exactly 20:00 the stage completes with earliest_acquire_utc 20:00 (unchanged). An ACK before the lag is refused by OQ-22 (test_s1_a3_final [before-lag]); the execution-time check is the same boundary, since a valid ACK is never in the future |
| test_s1_run::test_score_ack_with_stale_hash_is_refused_with_no_output[final/manifest.json] | the SCORE-ACK field check: "['final_manifest_sha256'] differ" | the edited manifest is a CREATED final member: `s1_replaced("final/manifest.json")` (stage-replaced at the score's gate), the same as the attest_stop.json case since Task 11; the field is still asserted to be an ACK field |
| test_s1_run::test_cr_final_acquisition_binding_checks[prereg0, preregf, outcome] | r.score's report names the reason | those three edit final/manifest.json, a CREATED member, so the score's gate refuses (stage-replaced); the reason is asserted on the unit-level record via `s1_score_refused(..., "stage-replaced")`, as the plan/noplan cases have done since Task 11 (oracle reason strings unchanged) |
| test_s1_t12_a3_a8::test_a3_score_checks_bundle_consistency_across_every_artifact[final_manifest] | r.score returns ABORTED-INVALID (bundle) | refused `s1_replaced("final/manifest.json")`; the unit-level `_score` record is still ABORTED-INVALID with a bundle reason (same as the seal and prereg cases) |
| test_s1_t12_a7::test_a7_4_a_tampered_final_raw_page_is_an_integrity_failure_at_score | r.score ABORTED-INVALID "raw page" | the changed manifest and the orphan page are stage-replaced at the score's gate (F4.9: consistency before valuation); `s1_score_refused(..., "stage-replaced")` keeps the score's raw-page reason as the unit-level killer |

### input (fixture / ACK placement; oracle unchanged)
| test | change |
|---|---|
| test_s1_collect `final_setup` (used by the collect final tests, test_s1_t12_a7 probe i and test_s1_t12_mutant_followups::test_mf_the_final_manifest_binds_the_bundle_and_the_persisted_stop) | the ACQUIRE-ACK goes to max(attestation + 1 h, the lag), not attestation + 1 h. For this trial: 2026-10-30T20:00Z (OQ-22, brief Step 6, first bullet). Failing before it: a7 probe i, mf, request_params, requests_every_symbol (all "the ACQUIRE-ACK precedes the acquisition lag") |
| test_s1_task11 `_acquire_ready` (i4 acquire + i4 rechecks x3) | `shutil.rmtree(final)` of the fixture's attempt is now stage-replaced (it is a CREATED stage). The state is built with `final=False`, the final plan is written at attestation + 1 h (as s1_state does), and `st_["now"]` = max(lag, plan) + 2 h, so the tests' ACK at now - 1 h respects OQ-22. The SCORE-ACK deletion is dropped: final=False posts none. Failing before it: i4 acquire and i4 rechecks[aborted]. The other two rechecks cases kept their refusal, and their oracle is unchanged |

### not changed (they were expected to need migration but still pass)
- test_s1_connected (final acquisition): the ACK at `acq_at - 1 h` is already after the lag (the 3rd session's close
  is before 07:00 New York of sessions[N_DAYS+3]). The token was already `s1_ack` (A3 Task 5), so the brief's
  second Step-6 bullet needs no change.
- test_s1_run `drop_final_and_attestation` / `rmtree(final)` users and test_s1_t12_a3_a8 bundle-before-request:
  each is refused (gate bundle, ACK F6.1 or stage-replaced) on the same oracle regexes as before. Removing the
  CREATED final makes the trial stage-replaced at the next gate, and these tests match that refusal or one the
  gate checks first (bundle).

### fixture (conftest) - no pre-existing outcome changed by it alone
- `_s1_finish`:
  - the final attempt is the REAL stage `final` (`_final_stage`: s1_stage.run with the real final_policy; inputs
    final_plan.json, prereg.json and attest_stop.json; the ACQUIRE-ACK line sha; INTENT/PREPARED/CREATED at
    reserved - 1 s / + 2 min / + 3 min; provenance []);
  - the bytes are the same as before, except attempt.json's trial_id/intent_at (and so the manifest's attempt hash);
  - the ACQUIRE-ACK is at max(t + 2 h, lag), and every later instant shifts by the same amount;
  - the unattested branch (stop_attest=False) keeps the hand-written files: its final_plan has no CREATED row, so
    no final stage can run (an INVALID state already, Task 11 concern 1).
- Every test using s1_state(score_ready=True) with the default final=True now has a CREATED final stage. The
  t12_full.txt counts are the evidence that this changed no other outcome.

### Fix round 1 (review I-1, I-2, M-1, M-3, M-4)
- t12_fix1_full.txt: **1774 passed, 1 skipped** = 1769 + 5 new tests:
  - test_s1_a3_final: the local-OSError test x2 and the M-1 provenance-before-write test;
  - test_s1_a3_audit: the local-OSError test x2.
- No pre-existing test changed outcome.
- Oracles tightened, still passing, so no outcome change:
  - M-3: test_s1_collect `test_final_lag_refused_before_reserving` is pinned to "ack is in the future", and
    ACK_REFUSAL["before-attest"] to the F6.1 text;
  - M-4: the provider-anomaly test now also asserts the ABORTED.json content, no prepared.json, no s1_out/final, and
    no dummy key in any file.

## A3 Task 13 - old -> new (full suite vs base 20772fb: 1774 passed, 1 skipped)

Source: `a3/t13_old_new.md`, sha256 `6319e34454149260321c34cbc1d6d53579f8c4bbceadb9432e3e01b4d7095c4f`


Discovery: one full-suite pass after Step 4 (six parallel shards with separate basetemps, scratchpad only - not
evidence) gave 38 failures in 12 pre-existing files. Each is classified below. The clean evidence run is
`t13_full.txt`. No requirement-map row's expected outcome changed.

Classes: **intended** (the Task 13 spec change named in the brief's Step 6), **held** (the test needs a ruling; skip
with a reason), **un-held**, **new**.

### Intended: OQ-28 AMEND - `_score`'s ABORTED-INVALID is TRIAL-INVALID (registration-artifact), report in staging

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

### Intended: F4.9 score abort - a computation error is INVALID (score-aborted), record in staging

Old: "score ABORTED ...; attempt preserved, see s1_out/score/s1.json", with the retry refused "an attempt already
exists". New: `s1_score_invalid(..., reason="score-aborted")`, and the retry is the gate's INVALID refusal
("trial INVALID (reason/score-aborted)").

- test_s1_run.py::test_score_failure_inside_the_attempt_is_preserved_as_aborted.
- test_s1_run.py::test_report_is_serialised_before_the_output_file_is_opened. Also an input fix: the stage calls
  `_score(out, mailbox)` as the c9b4322 command did, so the monkeypatched lambda takes `mailbox=None`. The test now also
  asserts the staged reason names TypeError (the unserialisable object).

### Intended: the one-attempt score is the stage's one INTENT ("score/ already exists" -> "already CREATED")

- test_s1_run.py::test_second_score_refused_and_nothing_overwritten: the match is now
  `stage score is already CREATED: re-entry refused \(F1\)`, and all_hashes(s1_out) is still unchanged.
- test_s1_connected.py::test_connected_lifecycle_matches_independent_oracle[chop-FAIL-None, trend-SHADOW PASS-None,
  chop-FAIL-buy, chop-FAIL-receipt], step 12: the same match; tree_hashes is still unchanged.

### Intended: the reservation is staged (F4.2)

- test_s1_run.py::test_score_reserves_before_any_priced_computation: the spy checks the staged
  `s1_staging/<trial>/score/score/attempt.json` instead of s1_out/score/attempt.json. The property (reserved before
  the first priced call) is unchanged.

### Intended: OQ-16 - the SCORE-ACK-bound final snapshot is bound evidence

- test_s1_checkpoint_7b.py::test_score_ack_binds_the_final_snapshot_report_and_an_edit_after_the_ack_is_refused. Old:
  the Refusal "['final_snapshot_sha256'] differ". New: "the SCORE-ACK-bound final snapshot is missing or changed:
  INVALID (registration-artifact)", with the TRIAL-INVALID asserted (s1_first_invalid) and no s1_out/score. This is the
  brief's Step 6 OQ-16 bullet.

### Intended: OQ-16 - `--final-snapshot` runs only in STOPPED, and never finalizes or appends a slot row

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

### Intended: ENFORCED

- test_s1_a3_stage.py::test_seal_files_on_disk_are_evaluated_once_the_seal_family_is_enforced: the expected ENFORCED
  set gains "score" (brief Files: `ENFORCED |= {"score"}`).

### Held (7): the NO-VALID-SEAL score path (report concern 1, awaiting a ruling)

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

### Un-held (1)

- test_s1_a3_stop.py::test_in_flight_slot_started_before_the_stop_completes_but_never_enters_final_or_score (row 189;
  held since Task 11 for sampled_history). It has no pytest.raises. Two assertions were added: the history has
  exactly the keys rows and seals (an assertion, not a KeyError, on the RED), and the STOP's own line is in it (a
  non-vacuous oracle).

### New (31)

- test_s1_a3_score.py: 23 brief tests (rows 60, 63, 109, 118, 181, 182, 185, 191, 215, 218, 281, 282, 306, 307, 314,
  315) and 7 carry-forward tests.
- test_s1_a3_final.py::test_aborted_record_write_error_still_records_the_provider_structural_reason (Task 12 N-1).

### Brief Step 6 items that needed no change

- "A2.3/B3 -> F1/F0.6" (refused, no score, when the journal is INVALID): test_s1_t12_fix2_b3 `..._at_the_score_...`,
  test_s1_t12_reporting and test_s1_task11 m-7 already met this since A3 Task 5 (the gate refuses an INVALID trial).
  They pass unchanged; only m-7[aborted] changed, for OQ-28 above.

### Fix round 1 (task-13-review-verdict.md; full suite t13_fix1_full.txt: 1805 passed, 7 skipped)

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

## A3 Task 14 - old -> new (base 28fe5a0: full suite 1805 passed, 7 skipped)

Source: `a3/t14_old_new.md`, sha256 `27f0119beb3534bac6f3f1f4632a94ab5b1b6db17f05cfb829eeb764c562f9a6`


Classes: **intended** (the Task 14 change the brief names: every stage enforced, Step 3), **fixture** (a test
fixture or test-literal change that changes no oracle), **new** (a new test), **oracle** (a resolution of the damage
matrix's oracle against an observation, from the spec, as the brief's Step 2 requires), **held** (fix round 1: a
case that keeps the brief's expected outcome and is xfail(strict=True) on a product defect fixed by a later task).
No requirement-map row's expected outcome changed (fix round 1 restored the brief's INVALID for the O-3 cases).
The 7 NO-VALID-SEAL holds (NVS-1, `conftest.S1_NVS_HELD`) are untouched and stay skipped; the matrix does not use
them (no matrix point is a NO-VALID-SEAL trial: the s1_state default lots stop STOPPED).

### Transitional check before the deletion (Task 8 D5 carry-forward)
`a3/t14_enforced_check.txt`: at HEAD 28fe5a0, before any Task 14 edit, `ENFORCED == frozenset(TABLE)` is True (all 8
TABLE stages) and `SEALS_ENFORCED is True`. Both names were then deleted together. After the task, a grep of
research/s1 (product and tests, evidence excluded) finds the two names only inside the absence assertions
(`not hasattr(...)`) of test_every_stage_is_enforced_by_the_gate and test_seals_enforced_is_on.

### Intended (Step 3): the transitional stage set is gone, so every test runs with every stage enforced
Old: the test narrowed `s1_stage.ENFORCED` (and/or set `SEALS_ENFORCED = True`) by monkeypatch. New: no patch; the
oracle is unchanged and the test passes on the product default (all of TABLE plus the seal files). Each of these
tests already drove one stage on a plan-only trial, where no other TABLE stage has a row or an artifact, so the
other stages' table entries decide nothing.
- test_s1_a3_stage.py: `drive()` (used by every engine test that drives a stage); test_crash_after_prepared_recovery_by_b_appends_created_without_recompute;
  test_recovery_appends_created_with_a_op_and_b_actor_under_the_lock; test_recovery_failures_are_invalid[*];
  test_recovery_publishes_only_missing_members_and_never_overwrites; test_recovery_unexpected_error_appends_nothing;
  test_stage_state_table[*]; test_pause_after_intent_with_a_live_owner_is_pending;
  test_lock_io_error_refuses_with_no_row_and_no_liveness_verdict;
  test_a_seal_file_with_no_prepared_row_is_a_registration_artifact (SEALS_ENFORCED patch; docstring);
  test_a_foreign_root_is_refused_by_the_plan_check_before_the_stage_table;
  test_no_intent_in_a_stale_snapshot_is_re_read_under_the_lock_before_invalid;
  test_no_intent_in_a_stale_snapshot_with_a_live_owner_is_pending;
  test_a_seal_completed_after_a_rowless_snapshot_is_not_an_artifact (SEALS_ENFORCED patch; docstring);
  test_recovery_never_creates_s1_out.
- a3_helpers.py `child()` (the child-process entry point of the crash / live-owner tests): no longer sets
  `sg.ENFORCED = frozenset({stage})`.
- test_s1_a3_stage.py::test_seal_files_on_disk_are_evaluated_once_the_seal_family_is_enforced: old `assert
  sg.ENFORCED == frozenset({...8 stages}) and sg.SEALS_ENFORCED is True`; new: that assertion is removed (the
  absence is asserted by the new test below); the seal-file oracle is unchanged.
- test_s1_a3_finalizer.py::test_seals_enforced_is_on (Task 8 D5 condition (b)): old `assert sg.SEALS_ENFORCED is
  True`; new `assert not hasattr(sg, "SEALS_ENFORCED") and not hasattr(sg, "ENFORCED")`.
- Comment/docstring wording only (no code): test_s1_a3_audit.py (carry-forward 4 docstring), test_s1_a3_slots.py,
  test_s1_a3_finalizer.py (module docstring, row 265 docstring), test_s1_t12_fix2_b3.py, test_s1_t12_fix3.py (one
  comment; mixed line endings preserved byte for byte), test_s1_t12_fix4.py (four comments).

### Carry-forward 2 (Task 10 I1): the legacy registry/witness records stay
Not removed. Neither the Task 14 brief nor the spec removes them: OQ-19 keeps the legacy detectors as additional
detectors (never identity or authorization roots), OQ-24 makes `registry/opening.json` and `witnesses/opening.json`
two of the nine damage-matrix elements, and the brief's oracle relies on "legacy records through OQ-19". So the
publication hooks that write them (`s1_stage.PUBLISH_HOOKS`, used by run() and by F4.7 recovery) and the legacy
`registration_gate` detector stay; only the s1_stage comment that said "until Task 14 deletes them" is corrected.
The Task 10 I1 test (test_s1_a3_prestart.py::test_a_recovered_pre_start_stage_never_invalidates_the_next_command[*])
is unchanged and green (t14_green.txt, t14_full.txt).

### Fixture addition (Step 3): `conftest.s1_state(upto=...)`
- `upto` is one of `conftest.S1_UPTO` = after-start-attest, after-prereg, after-stop, after-stop-attest,
  after-final-plan, after-final, after-score. s1_state then runs the real lifecycle (attest_start; RUN-ACK;
  do_prereg; PREREG-ACK; the seals; decide_stop; attest_stop; write_final_plan; ACQUIRE-ACK; the real `final` stage
  through the existing `_final_stage` fixture work; the final snapshot; SCORE-ACK; the real `r.score` command) and
  returns right after the named point's CREATED row (after-stop: the TRIAL-STOP row and stop.json). The ACK of the
  next stage is not posted. `info["now"]` is an instant just after the point (30 s, or 1-4 min for final/score),
  at which the gate passes. `upto` implies score_ready from after-prereg on; an unknown value is a ValueError, and a
  stop with no final plan (NO-VALID-SEAL) is a ValueError for the final points.
- `_s1_finish` gains the same `upto` keyword (it holds the post-stop chain).
- Without `upto`, s1_state and _s1_finish behave exactly as before (every existing caller; full suite).
- Deviation from the brief's wording "do_final": the after-final point runs the real `final` STAGE with the
  fixture's synthetic work (`_final_stage`, Task 12), as every other s1_state caller does; do_final itself needs a
  provider transport (tested in test_s1_a3_final.py).

### New tests
- test_s1_a3_matrix.py::test_matrix (row 255): default 55 subsets x 2 bundles x 3 damages x 10 points = 3,300
  cases; S1_MATRIX_FULL=1: 511 x 2 x 3 x 10 = 30,660 (t14_matrix_full.txt).
- test_s1_a3_matrix.py::test_matrix_scope_is_the_declared_scope (row 283, static).
- test_s1_a3_residual.py::test_uncommitted_detection_may_resume_and_is_labelled_lost_detection (rows 161/223, ctrl)
  and ::test_invalid_committed_before_the_crash_keeps_restoration_invalid (rows 162/224) (t14_residual.txt).
- test_s1_a3_stage.py::test_every_stage_is_enforced_by_the_gate (Step 3; also asserts the seal switch is gone).

### Test-literal deviations from the brief's code (R-G; no row outcome changed)
1. **match= on every pytest.raises** (inherited rule). The matrix uses `MATRIX_STOP = r"refused|INVALID"`; the
   residual tests pin the exact texts (the F8.1 residual refusal; "stage start_attest: ... INVALID (stage-replaced)";
   "trial INVALID (reason/stage-replaced): no work").
2. **The stop must be the damage's** (new assertion). In the brief's code, any SystemExit from run_checkpoint
   passed a non-ok case, including the checkpoint's own later refusals for an unrelated reason ("no verified
   prereg", "no S1-PREREG-ACK", "already has a journal row: a restart never re-intents"). The first oracle check
   showed those refusals passing 'invalid' and 'refuse-or-invalid' cases vacuously (O-1/O-2 below). Each non-ok
   case now asserts that the SystemExit was raised by `s1_trial.gate`, or by the checkpoint's registration check
   (`s1_gates.verified_registration`, the A3.2/B3.3 legacy detectors, before any callback) with a legacy-detector
   text. Spies record both.
3. **The residual tests assert the journal state**: the outage case asserts no TRIAL-INVALID row was committed; the
   committed case asserts exactly one reason/stage-replaced row before the restoration.
4. **The module-scoped snapshot fixture applies the per-test guards itself** (ruling B4/C14): a module fixture is set
   up before the first test's function-scoped autouse guards, so it sets its own tmp mailbox, its own tmp receipt
   HMAC key and the network guard through `pytest.MonkeyPatch.context()` (all restored after the build). The brief
   set only the mailbox.
5. `import re` added; unused brief imports kept with `# noqa: F401`.

### Oracle (Step 2: the singleton check at every point, then the default selection)
The singleton run (all 10 points x 9 elements x 2 x 3) first gave 20 disagreements under the brief's code, and
the default selection 16 more after the O-1/O-2 resolutions. Each is resolved below; the oracle docstring carries
the same rules. The observed refusal texts came from a scratch logging plugin (scratchpad only, not evidence).
- **O-1 (oracle; OQ-24, OQ-19, E5.5).** Element "opening record (registry)" / "(witnesses)", damage "changed" (one
  trailing space), at every point from after-opening on. Old oracle: INVALID. Observed: the gate passes (the
  checkpoint then refused for its own reason). Spec: the two records are bound by no journal row and are no member
  of the E5.5 evidence manifest (they are "not journal substitutes", OQ-24); the OQ-19 detector reads them as
  parsed records, and a trailing space leaves the parsed record identical. So that damage changes no committed
  evidence and no recorded content: it is no damage. New: such an element is not counted as damaged ('ok' unless
  another element decides). "deleted" and "unparseable" of the same records stay INVALID (observed INVALID).
  Limit (fix round 1, review M-4; disclosed to Codex at Stage-1, no change): the matrix's "changed" is therefore
  vacuous for these two elements, and its 'ok' cases exercise only the trial gate. A SEMANTIC edit of a record (an
  `artifacts` hash changed) passes the trial gate and is caught only by the command's legacy check
  (`s1_gates.verified_registration` -> TRIAL-INVALID registration-artifact); that path is covered by the legacy tests
  test_s1_t12_fix8.py::test_h_every_subset_of_the_editable_registration_files_tampered_is_the_persistent_abort
  (its "edit" mode zeroes `artifacts["plan.json"]` in the opening records) and the test_s1_t12_fix3.py c2 tests.
- **O-2 (oracle; OQ-19 keeping A2 B3.1).** The same two records fabricated before the opening (after-audit,
  "changed" = `{} ` or "unparseable" = `{not JSON`). Old oracle: 'refuse-or-invalid'. Observed: the gate passes.
  A registry/witness record before the opening seal is the legacy "opening in progress" witness, which the legacy
  detector accepts by design (a crash between the record and the seal), and no F-rule judges it (it is no stage
  artifact, F4). New: a fabricated legacy record adds nothing ('ok' unless another element decides).
  Correction (fix round 1, review M-1; disclosed to Codex at Stage-1, no change): "adds nothing" holds at the trial
  gate only. Downstream, the real opening checkpoint with such a record commits the opening STAGE-INTENT and
  STAGE-PREPARED and refuses "registry/opening.json already records different artifacts: refusing"; every later
  gate refuses the same way with no row (F4.7 recovery re-runs the same before_publish) until the file is deleted,
  after which recovery completes. Fail-closed, availability only (no integrity loss); no matrix point reaches it.
  Codex question: is a pre-existing legacy record at the opening's publication an indefinite refusal (current) or
  INVALID (registration-artifact, as a stray file after the AUDIT-ACK under the Task 7 concern-2 ruling)?
- **O-3 (held since fix round 1; was "disputed").** After the audit and before the opening, damage to plan.json. The
  oracle's spec reading is INVALID (F4 table: the CREATED audit stage's bound input plan.json missing or changed ->
  INVALID stage-replaced; also the gate's own comment "OQ-19: after any row a lost/changed plan is a detected
  registration-artifact violation, never only a refusal"). The code runs the OQ-19 legacy detector first (Task 7
  deviation D10, for a plan that does not name the trial or is not the AUDIT-ACK's), and before the opening that
  detector finds no registration. Observed:
  - plan.json alone deleted or unparseable: "checkpoint refused: plan.json trial_id None differs from the
    AUDIT-ACK's <id> (F6.2)" with NO TRIAL-INVALID row, so restoring plan.json resumes the trial;
  - plan.json damaged together with a fabricated attest_start.json / prereg.json / stop.json: the A2 B3.2 refusal
    "inconsistent pre-registration state [...]" with no row (also when plan.json is only "changed", where the F4
    table alone would INVALIDate, and although the Task 7 concern-2 ruling says A3 supersedes A2 B3.2 after the
    AUDIT-ACK);
  - plan.json unparseable together with an unparseable fabricated seal / receipt / registry / witness record: the
    legacy detector's persistent abort with TRIAL-INVALID.
  Round 0 pinned these cases to the observed outcome (`disputed()`); the review (I-2) rejected that as an oracle
  change with no spec reason. Fix round 1: the brief's INVALID is restored and the failing cases are **held**
  (strict xfail), see "Fix round 1" below. The product fix is Task 14b (progress.md ruling "T14 I-1": an ordering
  defect under the existing spec). Every case still stops all work with zero callbacks. From after-opening on, the
  same damage is INVALID only through the legacy detector (review I-1: with the legacy detector disabled, 330 plan
  deleted/unparseable cases from after-opening on end with no TRIAL-INVALID).

### Full suite (t14_full.txt) vs base
**5109 passed, 7 skipped in 4213.46s (1:10:13)** (t14_full.txt) = base 1805 passed + 3,304 new (3,300 default
matrix cases + the scope test + 2 residual tests + test_every_stage_is_enforced_by_the_gate); the 7 skips are exactly
the NVS-1 holds (S1_NVS_HELD), unchanged. No pre-existing test changed outcome: every pre-existing test touched by
Task 14 is listed above (intended or wording only), and no other test needed a change. The exhaustive matrix
(t14_matrix_full.txt): 30661 passed in 5261.35s (1:27:41).

### Fix round 1 (task-14-review-verdict.md; progress.md rulings "T14 I-1", "T14 I-2")

- **Held (I-2): O-3 cases are strict xfail with the brief's oracle.** `disputed()` is gone; the oracle is the
  brief's (plus O-1/O-2). `o3_held(point, subset, bundle, damage)` only selects the cases marked
  `pytest.mark.xfail(strict=True, reason="O-3: damaged plan.json after rows refuses instead of INVALID; fixed by Task
  14b")`; the 'refuse' expectation (which asserted the defect: no TRIAL-INVALID) is deleted. Task 14b's fix makes
  them XPASS, strict fails, and Task 14b removes the marker.
- **The held set is the MEASURED failing set, 26 default cases, not 53.** The review counted 53 default cases whose
  expected outcome round 0 had changed (2 'refuse', 51 'refuse-or-invalid'). With the brief's oracle restored and no
  marker, a scratch run of every after-audit case gave 26 failures in the default selection (330 run) and 286 in the
  exhaustive one (3,066 run); the other 27 of the 53 PASS the brief's oracle (observed INVALID: plan.json changed
  alone or with the audit tree is the F4 INVALID; a fabricated seal / receipt / registry / witness record next to the
  damaged plan makes the legacy detector's persistent INVALID fire). Marking them strict xfail would make them XPASS
  and fail, so exactly the 26 are held. `o3_held`'s rule (docstring) selects exactly the measured ids in both modes
  (scratch check: default 26 == 26, exhaustive 286 == 286, set-equal). Exhaustive: **286** held cases.
- The 26 held default cases (point|subset|bundle|damage):
  - `after-audit|plan|same|deleted`
  - `after-audit|plan|same|unparseable`
  - `after-audit|plan+audit tree|same|deleted`
  - `after-audit|plan+audit tree|same|unparseable`
  - `after-audit|plan+opening record (registry)|same|deleted`
  - `after-audit|plan+opening record (witnesses)|same|deleted`
  - `after-audit|plan+attestation|same|deleted`
  - `after-audit|plan+attestation|same|changed`
  - `after-audit|plan+attestation|same|unparseable`
  - `after-audit|plan+prereg|same|deleted`
  - `after-audit|plan+prereg|same|changed`
  - `after-audit|plan+prereg|same|unparseable`
  - `after-audit|plan+seal|same|deleted`
  - `after-audit|plan+receipt|same|deleted`
  - `after-audit|plan+stop|same|deleted`
  - `after-audit|plan+stop|same|changed`
  - `after-audit|plan+stop|same|unparseable`
  - `after-audit|plan+opening record (registry)+opening record (witnesses)+attestation+prereg+seal+receipt+stop|same|deleted`
  - `after-audit|plan+audit tree+opening record (witnesses)+attestation+prereg+seal+receipt+stop|same|deleted`
  - `after-audit|plan+audit tree+opening record (registry)+attestation+prereg+seal+receipt+stop|same|deleted`
  - `after-audit|plan+audit tree+opening record (registry)+opening record (witnesses)+prereg+seal+receipt+stop|same|deleted`
  - `after-audit|plan+audit tree+opening record (registry)+opening record (witnesses)+attestation+seal+receipt+stop|same|deleted`
  - `after-audit|plan+audit tree+opening record (registry)+opening record (witnesses)+attestation+prereg+receipt+stop|same|deleted`
  - `after-audit|plan+audit tree+opening record (registry)+opening record (witnesses)+attestation+prereg+seal+stop|same|deleted`
  - `after-audit|plan+audit tree+opening record (registry)+opening record (witnesses)+attestation+prereg+seal+receipt|same|deleted`
  - `after-audit|plan+audit tree+opening record (registry)+opening record (witnesses)+attestation+prereg+seal+receipt+stop|same|deleted`
- **Fixture (M-5)**: the module-scoped snapshot fixture also patches `socket.create_connection` (as
  conftest.s1_no_network).
- **codex_probes_old_new.md (M-6)**: the three review-driven strengthenings (T5 M-7, T7 M5, T10 crash recording)
  moved out of section 2 into a separate note counted in neither section.
- **No change (rulings), disclosed at Stage-1**: O-1 limit (M-4) and O-2 downstream availability path (M-1), above;
  concern 4 measured by the review (M-2), recorded in t14_red_mutant.txt.
