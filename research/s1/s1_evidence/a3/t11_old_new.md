# A3 Task 11 (Steps 1-3: stub + conftest) - old -> new classification

## r1 (after Codex f33d0501): the clean full suite
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

## r0 runs (unchanged)

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

## Changed outcomes (2): class **fixture** (oracle unchanged)

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

## Fixture changes that changed no pre-existing outcome

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


## Steps 4-6 (BLK-3 cleared: Codex 28e08272 ACCEPT-DISPOSITIONS on 9153062b) - old -> new

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

### A3 files (pre-existing tests)
| test | class | change |
|---|---|---|
| test_s1_a3_finalizer::test_no_seal_after_stop_even_for_a_pre_stop_qualified, ::test_seal_stage_and_stop_orders[publish-first,stop-first], ::test_deleted_created_seal_is_invalid_and_never_recreated[after-stop] | fixture | `_stop_row` uses `conftest.s1_synthetic_stop`: stop.json + a matching TRIAL-STOP detail. A bare synthetic STOP (detail "5"*64, no stop.json) is now a publication gap that the gate recomputes, giving INVALID (stop-conflict) by F2.3. These tests are about the STOPPED state, not the decision. |
| test_s1_a3_finalizer::test_stop_fence_refuses_a_determined_close_without_a_created_seal | fixture | Its hand-built context supplies `stop_ready` (otherwise it fails closed, M-6). The fence oracle is unchanged. |
| test_s1_a3_finalizer::test_barrier_close_between_active_read_and_prepared | product-fix | `current_stop` reads the plan's trial (open or CLOSED) instead of `open_trial`, so a CLOSE in mid-checkpoint no longer turns a display read into "zero open trials". |
| test_s1_a3_gate::test_final_snapshot_after_its_own_detection_captures_nothing | intended (F2.4) | The gate's stop_check detects the changed stop.json after the stop_attest INTENT: TRIAL-INVALID (registration-artifact), the same reason and zero captures, raised as the gate's SystemExit rather than the old re-read Refusal. |
| test_s1_a3_precedence::test_precedence_table[5-stop-fence-ok, 7-stop] | fixture | The base context supplies `stop_ready`. New rows: `5-stop-not-ready`, `5-stop-ready-at-txn-now` and `5-stop-no-readiness-supplied` (fail closed). |
| test_s1_a3_slots::test_post_stop_new_slot_intent_is_lost_race_with_no_capture | fixture | `s1_synthetic_stop`. |
| test_s1_a3_stage::test_seal_files_on_disk_are_evaluated_once_the_seal_family_is_enforced | intended | ENFORCED adds stop_attest and final_plan (F4.8). |

### Non-A3 files
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

### Fixture helpers (conftest)
- `s1_synthetic_stop(root, at, record=None)` (new): a consistent synthetic STOP for STOPPED-state tests.
- `s1_finish` / `_s1_finish` (new): `s1_state`'s post-stop chain, extracted unchanged.
- `s1_finalize`: a real decide_stop at `at - 1 min` when committed history gives a stop, else `s1_synthetic_stop`.
- `s1_jappend`'s synthetic context supplies `stop_ready`.
- The D1 synthetic fallback is deleted; `s1_state` asserts that decide_stop committed the STOP.

### Result
- GREEN (t11_green.txt, all A3 files): 675 passed, 1 skipped (row 189, held with Task 13).
- Full suite (t11_full.txt, one clean run, no edits during it): **1719 passed, 1 skipped in 49:51**.
  - The skip is row 189 (Task 13).
  - The two previously Task-11-held tests (fix2_mutants mt_a, reporting R-6) now run and pass.

## Fix round 1 (review task-11-review-verdict.md; progress.md Rulings C1/S4-1, M1, I1/I2)

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
