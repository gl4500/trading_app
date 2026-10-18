# S1 review-closure table (Task 12, Addendum 1 A10.3)

One row per blocking/important review comment. Columns: ID | source | agreed requirement / example | implementing
source file:function | test ids (s1_tests/) | evidence file (s1_evidence/) | hashes (filled by the controller at
packaging) | disposition | reviewer response. Dispositions: RESOLVED / DOCUMENTED-LIMITATION / OPEN. A passing test
count does not close a row; reviewer responses are left empty for the reviewer. Unresolved rows stay visible.
Abbreviations: A38 = test_s1_t12_a3_a8.py, A56 = test_s1_t12_a5_a6.py, A2 = test_s1_t12_a2.py, A1 = test_s1_t12_a1.py,
A1b = test_s1_t12_a1b.py, A4 = test_s1_t12_a4.py, A7 = test_s1_t12_a7.py, A9 = test_s1_t12_a9.py, MF =
test_s1_t12_mutant_followups.py, REP = test_s1_t12_reporting.py; M12 = s1_mutants_t12.txt.

## 1. Codex plan review 0a58b934 (points 1-8 as the 71 atomic claims of reports/codex-plan-review-mapping.md)

| ID | Requirement / example | Source | Tests | Evidence | Hashes | Disposition | Reviewer |
|---|---|---|---|---|---|---|---|
| 1.1 | opening-capture mode without prereg | s1_checkpoint:run_opening_checkpoint | test_s1_checkpoint_7b opening tests; A38 opening tests | t7b_*, t12_A8_red/t12_green | | RESOLVED | |
| 1.2 | frozen opening books (hashed) | s1_run:_books_record/_opening_books/attest_start | A38::test_a8_run_ack_binds_opening_seal_frozen_opening_books...; MF::test_mf_an_edited_opening_books_* | t12_A8_red, M12 | | RESOLVED | |
| 1.3 | opening mode AUDIT-ACK/plan/calendar/source bound | s1_gates:verified_audit/verify_audit_ack; s1_seal:calendar_pin_problems | A38::test_a8_opening_mode_verifies_... (8 cases) | t12_A8_red | | RESOLVED | |
| 1.4 | causal order audit -> opening seal -> attestation -> RUN-ACK/prereg | s1_run:attest_start (after opening capture), do_prereg | A38::test_a8_attest_start_refuses_before_the_opening_seal_capture; ::test_a8_genuine_bootstrap... | t12_A8_red | | RESOLVED (Codex 89e72ebc approved order) | |
| 1.5 | normal checkpoints prereg/RUN-ACK bound | s1_gates:verified_registration; s1_checkpoint:run_checkpoint | A38::test_a8_checkpoint_verifies_the_run_ack_... (7 cases) | t12_A8_red | | RESOLVED | |
| 1.6 | end-to-end causal bootstrap test | conftest:s1_register; test_s1_connected | A38::test_a8_genuine_bootstrap...; test_s1_connected (4) | t12_green | | RESOLVED | |
| 2.1 | no capture before verified prereg/ACK (probe e) | s1_checkpoint:run_checkpoint -> s1_gates:verified_registration | A38::test_a8_hand_made_prereg_reaches_no_live_callback | t12_A8_red | | RESOLVED | |
| 2.2 | RUN token binds the whole S1 code | s1_common:RUN_ACK (bundle_sha256) | A38::test_a3_run_acquire_score_tokens_... | t12_A3_red | | RESOLVED | |
| 2.3 | SCORE token binds the bundle; refuse before reserving | s1_common:SCORE_ACK; s1_run:score (bundle first) | A38::test_a3_score_bundle_mismatch_...; test_s1_task11::test_i1_score_by_a_different_toolchain... | t12_A3_red | | RESOLVED | |
| 2.4 | complete closure manifest verified before operational reads and scoring | s1_common:bundle_manifest/bundle_gate/verify_bundle_first (code + E1 pins + 3 docs) | A38 A3 tests | t12_A3_red | | RESOLVED | |
| 2.5 | cache keyed by resolved path + approved hash | s1_common:load_pinned | A38::test_a3_pinned_core_cache_... | t12_A3_red (behavioural) | | RESOLVED | |
| 2.6 | RUN-ACK before planned START | s1_gates:run_ack_problems; s1_run:do_prereg | A38::...[ack_after_start]; test_s1_run prereg tests | t12_A8_red | | RESOLVED | |
| 2.7 | ACK causal timing vs bound stage | s1_gates:verify_audit_ack/run_ack_problems; s1_collect:do_audit/do_final; s1_run:_pre_reserve_gate | A38 timing cases; A38::test_a8_do_audit_checks_the_ack_is_after_the_plan | t12_A8_red (behavioural) | | RESOLVED | |
| 2.8 | final acquisition >= 3rd session close after the stop | s1_collect:_earliest_acquire/do_final | test_s1_collect::test_final_lag_* | t11/t12_green | | RESOLVED | |
| 2.9 | early / mixed-stage ACKs | s1_common token prefixes; s1_run:_pre_reserve_gate | test_s1_run early ACK tests | t12_green | | RESOLVED | |
| 2.10 | unapproved slot -> no capture | s1_checkpoint:_close_for/_opening_day | test_s1_checkpoint::test_cr_close_for_...; 7b non-opening slot | t12_green | | RESOLVED | |
| 2.11 | clock checked before capture (probe f) | s1_checkpoint:_clock_refusal | A56::test_a5_the_clock_is_checked_before_any_capture... | t12_A5_red | | RESOLVED | |
| 2.12 | attestation bindings recomputed, not trusted | s1_run:_start_attestation_problems/_stop_attestation | test_s1_run binding tests; MF attestation tests | t12_green | | RESOLVED | |
| 3.1 | no seal before receipt rejection | s1_checkpoint:run_checkpoint (abort before candidate) | test_s1_checkpoint::test_receipt_mismatch_... | t12_green | | RESOLVED | |
| 3.2 | invalidity persisted | s1_common:write_abort | test_s1_checkpoint::test_cr_first_abort_wins... | | | RESOLVED - aborted.json first-wins (test_s1_checkpoint::test_cr_first_abort_wins...) + fix round 2 (Addendum 2 c7f0c3ff) B3: registration-artifact abort persistent, corrupt aborted.json fails closed (c.load_abort) | |
| 3.3 | no resume after restoration | aborted.json first-wins; s1_run:do_prereg/attest_start refuse after abort | test_s1_checkpoint::test_abort_survives_receipt_revert; A38 R-1 tests | t12_A3_red | | RESOLVED | |
| 3.4 | invalid captures rejected before seals | s1_checkpoint:_candidate gate | A9 tests; test_s1_checkpoint | t12_A9_red | | RESOLVED | |
| 3.5 | dispositions before priced work | s1_run:_score order (1-5 before 6) | A9::test_a9_every_non_numeric_disposition_makes_no_valuation_call | t12_A9_red | | RESOLVED | |
| 3.6 | non-numeric dispositions make no valuation call | s1_run:_score | A9 (7 dispositions, spies) | t12_A9_red | | RESOLVED | |
| 3.7 | capture/receipt/process exceptions preserved (probe g) | s1_checkpoint:_safe/_failure/_capture/_observe_process/_receipt | A9::test_a9_receipt_or_process_exception_...; ::test_a9_a_capture_exception_...; ::test_a9_an_opening_receipt_exception... | t12_A9_red | | RESOLVED - I-1/I-4b (fix round 1) + fix round 2 (Addendum 2 c7f0c3ff): I-1 raw closure sha256 before any parse (test_s1_t12_fix2_i1.py), B3 corrupt/changed registered artifacts persistent (test_s1_t12_fix2_b3.py) | |
| 4.1 | deadline an aware instant; close instants compared (probe a) | s1_seal:deadline/eligible_sessions/stop_decision; s1_run:_trial_end; s1_collect:write_plan | A56::test_a5_codex_probe_a_...; ::test_a5_deadline_...; replaced test_s1_seal deadline tests | t12_A5_red (behavioural) | | RESOLVED | |
| 4.2 | registered slack E = min(s+10m, W); 08:00 non-sealable (probe b) | s1_seal:SCHEDULE_SLACK/eligible_until/capture_eligible/choose_seal | A56::test_a5_the_0800_slot...; ::test_a5_codex_probe_b... | t12_A5_red | | RESOLVED - fix round 2 (Addendum 2 c7f0c3ff) B1: claimed slots PENDING until D = E + 30 min, one exclusive resolution per slot, serialized slot-order selection (finalize_close); tests test_s1_t12_fix2_b1.py; evidence t12_fix2_B1_red, t12_fix2_green | |
| 4.3 | capture start/end validated before and after | s1_checkpoint:_clock_refusal/_new_report; s1_snapshot:take_snapshot(now=) | A56::test_a5_a_capture_finishing_after_E_... | t12_A5_red | | RESOLVED | |
| 4.4 | calendar covers the opening close | s1_seal:calendar_problems | A56::test_a6_completeness_...[opening close] | t12_A6_red | | RESOLVED | |
| 4.5 | range derived from deadline + lag, not +200 d | s1_collect:write_plan (CAL_TAIL_DAYS) + A6 completeness | A56::test_a5_plan_records_the_deadline_instant_... | t12_A5_red | | RESOLVED | |
| 4.6 | >= 5 sessions after the review (AUDIT-ACK) | s1_collect:_validate_calendar(ack) | A56::test_a5_five_sessions_* | t12_A5_red (behavioural) | | RESOLVED | |
| 4.7 | complete pinned calendar | s1_seal:calendar_problems/calendar_pin_problems; s1_gates:verified_audit | A56 A6 tests | t12_A6_red | | RESOLVED + DOCUMENTED-LIMITATION (no independent NYSE proof, S1_BUILD_EVIDENCE 14.2) | |
| 5.1 | calendar validated | s1_collect:_validate_calendar | test_s1_collect::test_audit_aborts_on_bad_calendar | | | RESOLVED | |
| 5.2 | bars page validated | s1_collect:_validate_bars_page | test_s1_collect::test_final_aborts_on_structurally_bad_bars_page | | | RESOLVED | |
| 5.3 | calendar completeness/order/identity | as 4.7 | A56 A6 tests | t12_A6_red | | RESOLVED + DOCUMENTED-LIMITATION | |
| 5.4 | bool OHLC rejected | s1_collect:_is_num | test_s1_collect::test_parse_bars_flags_* | | | RESOLVED | |
| 5.5 | corruption vs gap contract | s1_collect:_validate_bars_page/_parse_bars | test_s1_collect | | | RESOLVED | |
| 5.6 | raw page bytes hashed | s1_collect:_page_hashes | test_s1_collect::test_audit_manifest_hashes_pages_* | | | RESOLVED | |
| 5.7 | raw pages re-verified later | s1_gates:attempt | A38 [raw_page_tampered]; A7::test_a7_4_... | t12_A8_red, M12 | | RESOLVED | |
| 5.8 | global CA reconciliation (probe i) | s1_collect:reconcile_actions/do_final; s1_run:_score | A7 (retrospective) | M12 | | RESOLVED (tests retrospective, disclosed) | |
| 5.9 | daily-bar time filters | s1_collect:do_final | test_s1_collect::test_final_request_params_* | | | RESOLVED | |
| 5.10 | process date not an effective date | s1_run:effective_date (EX_DATE_TYPES/EFFECTIVE_DATE_TYPES) | A4::test_a7_* | t12_A4_red | | RESOLVED + DOCUMENTED-LIMITATION (E1 classify_ca derived field) | |
| 5.11 | invalid data never COMPLETE | s1_collect:_run_attempt | test_s1_collect | | | RESOLVED | |
| 6.1 | explicit pre-START bound for the audit | s1_run:_blocked_reasons/_pre_start_day | A4::test_a4_1_prereg_bounds_... | t12_A4_red | | RESOLVED | |
| 6.2 | held across the event / FIFO attribution | s1_run:carry_in_reasons(open_across), contaminated_symbols | A4 tests; test_s1_run carry-in tests | t12_A4_red | | RESOLVED | |
| 6.3 | unit/identity vs economic actions | s1_run:unit_identity | test_s1_task11::test_i6_*; A4 special dividend | | | RESOLVED | |
| 6.4 | per-lot exclusions separate | s1_run:exclusions | test_s1_run | | | RESOLVED | |
| 6.5 | not every economic event INCONCLUSIVE | s1_run:unit_identity | A4::test_a4_a_special_dividend_... | | | RESOLVED | |
| 6.6 | unknown/conflicting records do not disappear | s1_collect:reconcile_actions; s1_run:effective_date | A7; A4 | M12 | | RESOLVED | |
| 6.7 | closed-and-reopened, event after sale, resolved pre-entry, missing identity/date | s1_run:contaminated_symbols | A4 (6 acceptance tests) | t12_A4_red | | RESOLVED | |
| 7.1 | effective config: launcher/process binding, limitation labelled | s1_receipt:EVIDENCE_CONTRACT/process_identity/sanitize_cmdline; s1_checkpoint:_bind_process | A1; A1b | t12_A1_red, t12_A1b_red | | RESOLVED - fix round 2 (Addendum 2 c7f0c3ff) B2: the opening-bound reference (process_binding.json removed), MATCH/GAP/EXCEPTION/MALFORMED dispositions, score recheck; tests test_s1_t12_fix2_b2.py; evidence t12_fix2_B2_red, t12_fix2_green | |
| 7.2 | secret keys bound (HMAC), not omitted | s1_receipt:semantic_receipt/_hmac/load_or_create_key/key_id | A1::test_a1_secret_named_fields_...; ::test_a1_the_hmac_key_...; MF::test_mf_the_secret_fingerprint_is_keyed | t12_A1_red | | RESOLVED | |
| 7.3 | missing roots fail | s1_receipt:closure | test_s1_receipt::test_missing_root_raises | | | RESOLVED | |
| 7.4 | relative / from-package imports | s1_receipt:_imported_modules | test_s1_receipt | | | RESOLVED | |
| 7.5 | missing required evidence fails (probe j) | s1_receipt:semantic_receipt/_runtime | A1::test_a1_a_missing_required_env_...; ::test_a1_a_missing_required_runtime_... | t12_A1_red | | RESOLVED | |
| 7.6 | no raw secrets | s1_receipt | A1; A1b; A9 sanitized reasons | | | RESOLVED | |
| 7.7 | attestation / runtime-loading limitation kept | s1_run START/STOP statements; s1_receipt docstring | | S1_BUILD_EVIDENCE 14.2 | | DOCUMENTED-LIMITATION | |
| 8.1-8.4 | failed bootstrap / changed helper / terminal after good receipt / no seal on mismatch | as rows 1.x/2.x/3.x | as cited | | | RESOLVED | |
| 8.5 | 08:00 slot finishing late | as 4.2 | A56::test_a5_codex_probe_b_... | t12_A5_red | | RESOLVED | |
| 8.6 | aware deadline at 09:30 | as 4.1 | A56::test_a5_codex_probe_a_... | t12_A5_red | | RESOLVED | |
| 8.7 | corrupt pagination/calendar | s1_collect | test_s1_collect | | | RESOLVED | |
| 8.8 | raw-page tampering test | as 5.7 | A38 [raw_page_tampered]; A7::test_a7_4_... | | | RESOLVED | |
| 8.9 | early final acquisition | as 2.8 | test_s1_collect::test_final_lag_refused_* | | | RESOLVED | |
| 8.10 | no-valuation spies | as 3.6 | A9; A4 no_valuation | t12_A9_red | | RESOLVED | |
| 8.11 | connected chain + independent oracle | test_s1_connected | 4 variants | t12_green | | RESOLVED | |
| 8.12 | counts boundary by calls | test_s1_checkpoint spies | | | | RESOLVED | |
| 8.13 | mutation evidence source/test bound, harness failures excluded | s1_evidence/s1_mutants_t12.py (+ _list/_part2/_part3) | all intended tests | M12 | | RESOLVED (see section 5 below for survivors/triage) | |
| 8.14 | slack not blessed by a test | old slack tests REPLACED (task-12-report replaced-test list) | test_s1_seal / test_s1_checkpoint replacements | | | RESOLVED | |

## 2. Codex protocol rulings 97e1d853 (Q0-Q6 + acknowledgement items)

| ID | Requirement | Source | Tests | Disposition | Reviewer |
|---|---|---|---|---|---|
| Q0 | MR-semantic receipt scope, HEAD/dirty provenance, runtime binding, HOST/PORT transport-only | s1_receipt (A1) | A1, A1b | RESOLVED + DOCUMENTED-LIMITATION | |
| Q1 | stop frozen, terminal invalidity, integrity through the stop | s1_seal:stop_record/persist_stop/current_stop/stop_problems; s1_checkpoint post_stop | A2; test_s1_task11 C-1 | RESOLVED | |
| Q2 | registered bundle checked first; mismatch persistent | s1_common:bundle_gate/verify_bundle_first; every command | A38 A3 tests; task11 I-1 replacements | RESOLVED - m-1 (fix round 1) + fix round 2 (Addendum 2 c7f0c3ff) B3: registration identified independently (registry + witnesses), registration-artifact gate after the bundle comparison; tests test_s1_t12_fix2_b3.py | |
| Q3 | sidecars excluded; relevant non-.py resources bound | s1_receipt:_transient/EVIDENCE_CONTRACT resources | A1 sidecar / resource tests | RESOLVED | |
| Q4 | derived final plan, stop-attestation bound ACQUIRE-ACK, lag | s1_collect:final_plan_record/_stop_state/do_final | task11 I-4; MF final plan tests | RESOLVED | |
| Q5 | carry-in unit trust vs per-lot economics | s1_run:unit_identity/carry_in_reasons | task11 I-6; A4 | RESOLVED | |
| Q6 | contaminated symbol cannot cure an untrusted stop | s1_run:contaminated_symbols + _score 2b | A4 2b tests | RESOLVED | |
| ack | STOP_STATEMENT; counts boundary; s1_checkpoint entry point; follow_redirects | unchanged | existing | RESOLVED (ack) | |
| ack | mutation scope; `_out`, `_seals`, `_sha_or_absent`, `_ack`, `_write_once`, serialisation mutants | s1_mutants_t12 entries for each | MF::test_mf_runner_*, ::test_mf_the_score_report_has_no_private_keys_and_no_secret | RESOLVED | |

## 3. Codex 89e72ebc (Q7, mapping disclosure, point amendments, process)

| ID | Requirement | Source | Tests | Disposition | Reviewer |
|---|---|---|---|---|---|
| Q7 | E = min(s+10m, W), pre/post checks, slot order, no duplicate, 08:00 non-sealable, examples | s1_seal; s1_checkpoint:_claim_slot/_clock_refusal/_finalize | A56 (A5.2-A5.5) | RESOLVED - fix round 2 (Addendum 2 c7f0c3ff) B1 (I-3): see 4.2; the 08:00 / E / W rules unchanged (B1.5); scheduler review still separate | |
| map | mapping counts are claims; missed review kept | this table | | RESOLVED (record kept) | |
| p1 | bootstrap order | as 1.4 | | RESOLVED | |
| p2 | full causal ACK identity/bindings/timing, zero live callbacks; bundle mismatch persistent | s1_gates; s1_common | A38 | RESOLVED - m-1 (fix round 1) + fix round 2 (Addendum 2 c7f0c3ff) B3 (I-4a): preserved refusals (refusals.jsonl), persistent registration-artifact abort; tests test_s1_t12_fix2_b3.py | |
| p3 | transient vs terminal; class + sanitized reason | s1_checkpoint A9 | A9 | RESOLVED - I-1/I-4b (fix round 1) + fix round 2 (Addendum 2 c7f0c3ff) B3 (I-4a) and the I-1 raw-sha256 completion | |
| p4 | aware deadline; 5 sessions from ACK; pinned calendar | s1_seal; s1_collect | A56 | RESOLVED + DOCUMENTED-LIMITATION | |
| p5 | global reconciliation; no process_date effective date | s1_collect:reconcile_actions; s1_run:effective_date | A7; A4 | RESOLVED + DOCUMENTED-LIMITATION | |
| p6 | carry-in bound, bridge rows | s1_run | A4 | RESOLVED | |
| p7 | effective config evidence, HMAC, required inputs | s1_receipt | A1, A1b | RESOLVED - fix round 2 (Addendum 2 c7f0c3ff) B2 (I-2): opening-bound process binding; see 7.1 | |
| p8 | replaced tests listed; kills keep test id/assertion; harness failures separated | task-12-report; s1_mutants_t12.py classification | M12 | RESOLVED | |
| proc | closure table; mailbox read at handoffs | this file | | RESOLVED for the table; mailbox reading is a controller process item | |

## 4. Codex f7384943 / 38408d89 (folded into Addendum rev 3)

| ID | Requirement | Source | Tests | Disposition | Reviewer |
|---|---|---|---|---|---|
| f7384943-A4.2 | any post-event SELL -> INCONCLUSIVE; carry-in precedence | s1_run:_score 4/4b | A4 2a/2b tests | RESOLVED | |
| f7384943-A5.2 | post-capture revalidation before any seal | s1_checkpoint:_new_report/_candidate | A56 | RESOLVED - post-capture revalidation (Task 12) + fix round 2 (Addendum 2 c7f0c3ff) B1 slot-order resolution (I-3) | |
| f7384943-A1 | .env not intrinsically mandatory; REQUIRED inputs fail | s1_receipt:contract/semantic_receipt | A1 env tests | RESOLVED | |
| f7384943-A3 | minimal bootstrap reads before the bundle comparison | s1_common:registration/verify_bundle_first | A38::test_a3_checkpoint_bundle_mismatch_...(helpers spied) | RESOLVED | |
| 38408d89 | the two A4 items (rev 3) | as above | A4 | RESOLVED | |

## 5. Final review (reports/final-review.md) C-1, I-1..I-6, R-1..R-6

| ID | Requirement | Source | Tests | Disposition | Reviewer |
|---|---|---|---|---|---|
| C-1 | post-stop captures never seal/abort | s1_checkpoint:run_checkpoint (persisted stop) | test_s1_task11 C-1; A2 | RESOLVED | |
| I-1 | whole protocol code bound | bundle (A3) | A38; task11 I-1 replacements | RESOLVED | |
| I-2 | transient files not semantic | s1_receipt:_transient (provenance) | task11 I-2; A1 | RESOLVED | |
| I-3 | sold count performance | s1_books:sold_events | task11 I-3 | RESOLVED (R-3 residual, below) | |
| I-4 | stop -> attestation -> acquisition order | s1_collect | task11 I-4; MF | RESOLVED | |
| I-5 | mailbox location | s1_common:MAILBOX/mailbox_message | task11 I-5 | RESOLVED | |
| I-6 | carry-in unit/identity scope | s1_run:unit_identity | task11 I-6 | RESOLVED | |
| R-1 | opening-seal toolchain checked before prereg | s1_run:attest_start/do_prereg (verify_bundle_first, registered from the opening seal) | A38::test_a3_r1_* | RESOLVED | |
| R-2 | new s1_*.py after the opening seal = persistent abort; no in-place tooling | operator note | S1_BUILD_EVIDENCE 14.3 | DOCUMENTED-LIMITATION (operator) | |
| R-3 | quadratic per symbol; scheduler queueing; live-shaped timing before approval | operator note | S1_BUILD_EVIDENCE 14.3 | OPEN until the scheduler review (measurement not run in Task 12) | |
| R-4 | CR evidence bound to 21a12b6 | S1_BUILD_EVIDENCE 13 | M12 fresh mutants | RESOLVED (disclosed) | |
| R-5 | Task 11 deviations listed | S1_BUILD_EVIDENCE 13/14.1 | | RESOLVED | |
| R-6 | refused captures listed in the score | s1_run:_capture_notes | REP::test_r6_* | RESOLVED | |

## 6. Task-12 review (reports/task-12-review.md) and fix round 1

| ID | Requirement | Source | Tests | Evidence | Hashes | Disposition | Reviewer |
|---|---|---|---|---|---|---|---|
| I-1 | an unparseable closure member is terminal; restoring does not resume | s1_receipt:_parse | test_s1_t12_fix1::test_fix1_i1_* | t12_fix1_i1_red | | RESOLVED (fix round 1) + fix round 2 (Addendum 2 c7f0c3ff) completion: membership + raw sha256 of the bound closure compared BEFORE any parse (s1_receipt.closure_raw_problems, semantic_receipt(reference=)); tests test_s1_t12_fix2_i1.py; RED t12_fix2_I1_red | |
| I-2 | process-binding reference bound and compared at score | s1_checkpoint:_bind_process (unchanged) | test_s1_t12_a1b | | | RESOLVED - fix round 2 (Addendum 2 c7f0c3ff) B2 (Codex R-c): s1_checkpoint:_binding, s1_run:_opening_binding/_seal_binding_problems, s1_gates:run_ack_problems; tests test_s1_t12_fix2_b2.py; RED t12_fix2_B2_red | |
| I-3 | an in-flight earlier slot never loses the seal to arrival order | s1_checkpoint:_finalize (unchanged) | A56 deferral tests | | | RESOLVED - fix round 2 (Addendum 2 c7f0c3ff) B1 (Codex R-b): s1_checkpoint:finalize_close/_publish/_resolve, s1_seal:RESOLUTION_TIMEOUT/resolution_deadline/pending_closes; tests test_s1_t12_fix2_b1.py; RED t12_fix2_B1_red -> REOPENED by re-review 1 (reports/task-12-rereview1.md C-1, I-1) -> RE-CLOSED fix round 3: fix3::test_c1_a_concurrent_finalizer_and_a_reader_never_observe_a_partial_seal, fix3::test_i1_*; fix2_b1 concurrent finalizers x200 + 4x50 stress (0 failures); RED t12_fix3_C1_red, t12_fix3_I1_red; mutants s1_mutants_t12_fix3_final.txt | |
| I-4a | registration artifacts changed after registration: preserved/terminal; refused invocations leave an attempt record | s1_gates:verified_registration (unchanged) | | | | RESOLVED - fix round 2 (Addendum 2 c7f0c3ff) B3 (Codex R-e): s1_common:registry/is_registered/registration_problems/registration_gate/load_abort/record_refusal; tests test_s1_t12_fix2_b3.py; RED t12_fix2_B3_red -> REOPENED by re-review 1 (reports/task-12-rereview1.md C-2) -> RE-CLOSED fix round 3: fix3::test_c2_* (9 deletion combinations + probes + retrospective isolations); RED t12_fix3_C2_red; mutants s1_mutants_t12_fix3_final.txt | |
| I-4b | corrupt sealed evidence preserved + terminal, never a crash | s1_checkpoint:_read_seals/_trial_stop/run_checkpoint; s1_run:_score | test_s1_t12_fix1::test_fix1_i4b_* | t12_fix1_i4b_red | | RESOLVED (fix round 1) | |
| m-1 | bundle compared (and persisted) on every refusal path | s1_common:verify_bundle_first/_audit_registration; s1_collect:do_audit | test_s1_t12_fix1::test_fix1_m1_* | t12_fix1_m1_red | | RESOLVED (fix round 1) | |
| m-2 | mutant evidence keeps failing test id + message; exception kills reported apart | s1_evidence/s1_mutants_t12.py:classify/kind_of | | s1_mutants_t12.txt | | RESOLVED (fix round 1) | |
| m-3 | post-RED scenario changes disclosed; MI relabel | S1_BUILD_EVIDENCE 14.4 | | | | RESOLVED (disclosed) | |
| m-4 | missing/changed stop.json after persistence is an integrity failure; stop bundle checked | s1_seal:stop_was_persisted/current_stop/stop_problems; s1_checkpoint:_stop_hash | test_s1_t12_fix1::test_fix1_m4_* | t12_fix1_m4_red | | RESOLVED (fix round 1) | |
| m-5 | broadened match disclosed | S1_BUILD_EVIDENCE 14.4 | | | | RESOLVED (disclosed) | |
| m-6 | 08:00 zero-duration predicate documented | S1_BUILD_EVIDENCE 14.4 | | | | RESOLVED (documented) | |
| m-7 | survivor test count | S1_BUILD_EVIDENCE 14.4; task-12-report | | | | RESOLVED | |

## 7. Addendum 2 (s1_design_v5_addendum2.md c7f0c3ff, Codex rulings 9a72159a) - fix round 2

| ID | Requirement | Source | Tests | Evidence | Hashes | Disposition | Reviewer |
|---|---|---|---|---|---|---|---|
| B1.1 | RESOLUTION_TIMEOUT = 30 min single-sourced; D = E + 30 min | s1_seal:RESOLUTION_TIMEOUT/resolution_deadline | fix2_b1::test_b1_resolution_timeout_* | t12_fix2_B1_red | t12_hashes | RESOLVED | |
| B1.2 | never-claimed -> MISSED after E; claimed PENDING until a complete report or D; arbitrary/partial file never resolves | s1_checkpoint:finalize_close/_complete_success/_read_resolution; c.publish_exclusive | fix2_b1::claim_without_report; fix2_mutants::arbitrary_report / forged_success | t12_fix2_B1_red | t12_hashes | RESOLVED | |
| B1.3 | success strictly before D; one exclusive irreversible transition; late worker cannot replace/seal; late evidence separate; violations never erased | s1_checkpoint:_publish/_resolve (.resolution.json, .late.json) | fix2_b1::success_before_D / expiration_racing / killed_and_slow | t12_fix2_B1_red | t12_hashes | RESOLVED | |
| B1.4 | serialized close-level selection in slot order; respects stop/abort | s1_checkpoint:finalize_close/_finalize_others | fix2_b1::overlap_race / concurrent_finalizers; fix2_mutants::later_close_resolves | t12_fix2_B1_red | t12_hashes | RESOLVED -> REOPENED by re-review 1 (reports/task-12-rereview1.md C-1 partial seal, I-1 unapplied SUCCESS) -> RE-CLOSED fix round 3: fix3::test_c1_* (deterministic pause), fix3::test_i1_*; t12_fix3_C1_repeat200 / t12_fix3_C1_stress; RED t12_fix3_C1_red, t12_fix3_I1_red; mutants s1_mutants_t12_fix3_final.txt | |
| B1.5 | D never extends eligibility (E, W = 08:00); no frozen outcome while PENDING; no rescue | s1_seal:pending_closes/stop_decision(pending=); s1_checkpoint:_clock_refusal unchanged | fix2_b1::D_never_extends / 0800_after_W / pending_no_rescue | t12_fix2_B1_red | t12_hashes | RESOLVED (operational limitation disclosed, S1_BUILD_EVIDENCE 15) -> REOPENED by re-review 1 (reports/task-12-rereview1.md I-1) -> RE-CLOSED fix round 3: fix3::test_i1_probe_*, test_i1_the_stop_attestation_*, test_i1_the_final_plan_*, test_i1_the_score_refuses_*; RED t12_fix3_I1_red; mutants s1_mutants_t12_fix3_final.txt | |
| B2.1 | opening must observe a usable binding (else no seal); reference bound by attestation/RUN-ACK/prereg; process_binding.json no authority | s1_checkpoint:run_opening_checkpoint/_binding; s1_run:_opening_binding/attest_start/do_prereg; s1_gates:run_ack_problems | fix2_b2::unobservable_opening / reference_bound / sidecar | t12_fix2_B2_red | t12_hashes | RESOLVED | |
| B2.2 | semantic fields compared, not pid/start; no secrets | s1_checkpoint:_binding; s1_receipt:binding_problem/sanitize_cmdline | fix2_b2::identical_binding_restart; a1b sanitize | t12_fix2_B2_red | t12_hashes | RESOLVED | |
| B2.3 | later difference terminal + persistent; score rechecks every seal; missing/malformed != equality | s1_checkpoint:_binding; s1_run:_seal_binding_problems | fix2_b2::A_gap_B / malformed / score_rechecks | t12_fix2_B2_red | t12_hashes | RESOLVED | |
| B2.4 | explicit GAP never MATCH/change/rebase, reported; exception = A9.1 | s1_receipt:PROCESS_OBSERVATION/process_identity; s1_checkpoint:_binding | fix2_b2::A_gap_A / exception / score_reports_gap | t12_fix2_B2_red | t12_hashes | RESOLVED | |
| B3.1 | registration from the opening seal, identified independently of the checked artifact | s1_common:register_stage/is_registered (registry/, seal + capture-report witnesses) | fix2_b3::registry / deleting_prereg_and_opening | t12_fix2_B3_red | t12_hashes | RESOLVED -> REOPENED by re-review 1 (reports/task-12-rereview1.md C-2 erasable witness, I-2 stray seal) -> RE-CLOSED fix round 3: fix3::test_c2_*, test_i2_*; RED t12_fix3_C2_red, t12_fix3_I2_red; mutants s1_mutants_t12_fix3_final.txt | |
| B3.2 | before the opening: invalid authorization = preserved refusal, zero callbacks | s1_common:verify_bundle_first/record_refusal | fix2_b3::handmade_prereg; a3_a8 hand-made prereg | t12_fix2_B3_red | t12_hashes | RESOLVED -> REOPENED by re-review 1 (reports/task-12-rereview1.md I-2) -> RE-CLOSED fix round 3: fix3::test_i2_a_stray_seal_* (2 dates), test_i2_a_lone_later_stage_registry_record_*; RED t12_fix3_I2_red; mutants s1_mutants_t12_fix3_final.txt | |
| B3.3 | after registration: missing/changed/unparseable REQUIRED artifact -> first-wins "registration artifact" abort; restoration does not resume; future-stage artifacts not required; re-entry and post-stop covered | s1_common:registration_problems/registration_gate; s1_collect:do_audit; every command | fix2_b3::changed_or_deleted (16 cases) / not_yet_due / audit/opening re-entry / post-stop / score | t12_fix2_B3_red | t12_hashes | RESOLVED (score + final snapshot record rather than refuse, A2.3) -> REOPENED by re-review 1 (reports/task-12-rereview1.md C-2) -> RE-CLOSED fix round 3: fix3::test_c2_deleting_* (9 combinations), probes, test_c2_retro_*; M-2 fix3::test_m2_*; RED t12_fix3_C2_red, t12_fix3_M2_red; mutants s1_mutants_t12_fix3_final.txt | |
| B3.4 | bundle first; mailbox outage = refusal not tampering; outage cannot downgrade a violation; earlier reasons first-wins; corrupt aborted.json fails closed | s1_common:verify_bundle_first/load_abort | fix2_b3::mailbox_outage x2 / bundle_first / corrupt_aborted x2 | t12_fix2_B3_red | t12_hashes | RESOLVED | |
| B4 | AUDIT-ACK bundle; provider action id identity (R-a, R-d) | unchanged (Task 12) | A38; A7 | t12_green | t12_hashes | ACKNOWLEDGED (no change) | |
| ctrl-1 | I-1 completion: raw closure sha256 before parse | s1_receipt:closure_raw_problems | fix2_i1 | t12_fix2_I1_red | t12_hashes | RESOLVED | |
| ctrl-2 | the 8 exception-only mutant kills tightened or justified | s1_tests/test_s1_t12_fix2_mutants.py; s1_evidence/s1_mutants_t12_fix2.py | fix2_mutants (8 tightening tests) | s1_mutants_t12.txt; s1_mutants_t12_triage.txt | t12_hashes | see triage (fix round 2) | |

## 8. Re-review 1 of fix round 2 (reports/task-12-rereview1.md) - fix round 3

Every row below was written with its test first (behavioural RED, s1_evidence/t12_fix3_<id>_red.txt; full run
t12_fix3_all_red.txt). "fix3::" = s1_tests/test_s1_t12_fix3.py. The independence of review is a convention here, not
an enforced isolation (same model family).

| ID | Requirement | Source | Tests | Evidence | Hashes | Disposition | Reviewer |
|---|---|---|---|---|---|---|---|
| C-1 | immutable artifacts (seals, stop.json, aborted.json, resolutions, registry/witness records, claims, reports, receipts, final-snapshot reports, score, collector pages, HMAC key) published atomically + exclusively; readers never see a partial file | s1_common:publish_exclusive/publish_text_exclusive/replace_atomic/write_abort; s1_checkpoint:finalize_close/_claim_slot/_write_report/_store_opening_receipt/run_final_snapshot; s1_seal:persist_stop; s1_collect:_write_once/_write_page; s1_run:_write_text_once; s1_receipt:load_or_create_key | fix3::test_c1_* (3 deterministic pause races + static guard + 2 retrospective) | t12_fix3_C1_red; t12_fix3_C1_repeat200 (200/200); t12_fix3_C1_stress (4x50, 0 failures) | t12_hashes | RESOLVED | |
| C-2 | registration and every stage witnessed redundantly; artifact + its registry record deleted -> persistent abort; restoration never resumes | s1_common:registration_witnesses/_registered/_reached/registration_problems/run_ack_witness/stage_records (registry/ + witnesses/) | fix3::test_c2_* (9 combinations, 2 probes, RUN-ACK, stop, record-alone, 7 retrospective) | t12_fix3_C2_red | t12_hashes | RESOLVED except the DISCLOSED RESIDUAL (S1_BUILD_EVIDENCE 16.3): every local witness deleted while the mailbox is unreadable (or before any RUN-ACK exists) is a refusal; documented by fix3::test_c2_residual_* - NOT closed | |
| I-1 | a SUCCESS without its seal is pending; stop attestation / final plan finalize first; the score refuses | s1_seal:pending_closes/_applied_or_unsuccessful; s1_checkpoint:finalize_pending; s1_run:attest_stop; s1_collect:_stop_state | fix3::test_i1_* (4) | t12_fix3_I1_red | t12_hashes | RESOLVED | |
| I-2 | a stray / lone file before registration is a preserved refusal, never ABORTED-INVALID | s1_common:_registered/preregistration_problems/registration_gate | fix3::test_i2_* (3) | t12_fix3_I2_red | t12_hashes | RESOLVED | |
| I-3 | re-open contradicted rows; re-argue the 2 B3-shadow survivors | this table (6, 7); s1_evidence/s1_mutants_t12_fix3.py | mutant run (fix round 3) | s1_mutants_t12_fix3_final.txt; s1_mutants_t12_triage.txt | t12_hashes | RESOLVED: rows re-opened and re-closed above; survivors re-derived (still equivalent under the new witness rule, triage) | |
| M-1 | publication time read late; link overrun at/after D recorded, never replaces the winner | s1_checkpoint:_publish/_record_overrun | fix3::test_m1_* | t12_fix3_M1_red | t12_hashes | RESOLVED | |
| M-2 | attestation / prereg registered BEFORE their artifacts (under s1_out/stage.lock); a missing record is detected | s1_run:attest_start/do_prereg; s1_common:stage_publication/registration_gate; s1_collect:json_sha256 | fix3::test_m2_*, test_c2_a_registered_stage_whose_registry_record_alone_*, test_c2_retro_a_stage_publication_* | t12_fix3_M2_red | t12_hashes | RESOLVED (crash inside the lock: refusal until inspected, then abort - disclosed 16.3) | |
| M-3 | a registration abort still yields a recorded ABORTED-INVALID score without a final snapshot; zero valuation calls | s1_run:_pre_reserve_gate | fix3::test_m3_* | t12_fix3_M3_red | t12_hashes | RESOLVED; observed_utc NOT used as the end instant (justified 16.2: the score itself is often the observer) | |
| M-4 | behavioural REDs for the MI-only B1.6/B2.5/B3.1 examples | s1_evidence/t12_fix3_m4_reds.py (guard reversion) | the fix-round-2 example tests | t12_fix3_M4_red (5 behavioural; 2 examples already satisfied, stated) | t12_hashes | RESOLVED | |
| M-5 | inaccurate docstring | test_s1_t12_fix2_b3.py::test_b3_a_corrupt_aborted_json_fails_closed | | | t12_hashes | RESOLVED | |
| M-6 | migration adjudication | (reviewer: no weakened requirement) | | | | ACKNOWLEDGED | |
| M-7 | corrupt resolution of another close silently skipped | s1_seal:pending_closes (an unreadable resolution is PENDING, so no stop freezes across it) | | | | PARTIAL: no longer counted as missed; _finalize_others still skips it (left for the score/next checkpoint) - not in the fix-round-3 brief, stated | |

## 9. Re-review 2 of fix round 3 (reports/task-12-rereview2.md) - fix round 4

Every row below was written with its test first (behavioural RED against the round-3 sources,
s1_evidence/t12_fix4_<id>_red.txt). "fix4::" = s1_tests/test_s1_t12_fix4.py. Details: S1_BUILD_EVIDENCE §17. The
independence of review is a convention here, not an enforced isolation (same model family). This section updates §8
C-2 (its residual is restated in §17.3, including the re-opening consequence) and §8 I-2 (narrowed by N-3).

| ID | Requirement | Source | Tests | Evidence | Hashes | Disposition | Reviewer |
|---|---|---|---|---|---|---|---|
| N-1 | a gate racing a legitimate attestation / prereg publication never aborts: the lock is re-checked and the violation re-confirmed; a lock that appeared or a violation that vanished is a refusal | s1_common:registration_gate/_refuse_if_locked | fix4::test_n1_* (4 deterministic interleavings: both orders x both stages; guard; 1 retrospective release-during-rescan) | [t12_fix4_N1_red](t12_fix4_N1_red.txt); [t12_fix4_green](t12_fix4_green.txt) | t12_hashes | RESOLVED | |
| N-2 | after the opening, deleting the local witnesses before the RUN-ACK never lets a later opening slot write a second, different opening seal: opening evidence left without its records is the persistent abort; seal creation refuses on it | s1_common:opening_orphans/registration_problems; s1_checkpoint:_before_opening_build/run_opening_checkpoint | fix4::test_n2_* (probe + 2 variants, seal-creation refusal, legitimate-retry guard, 1 retrospective) | [t12_fix4_N2_red](t12_fix4_N2_red.txt) | t12_hashes | RESOLVED for every deletion that leaves any opening evidence; RESIDUAL (§17.3, for Codex): deleting every opening-produced file before the RUN-ACK (and the narrower crash-equivalent variant) is indistinguishable from a fresh / crashed opening - NOT closed. Reading of the literal brief text (would abort a legitimate retry) stated in §17.2 | |
| N-3 | B3.2: hand-made later-stage files before any opening are a refusal; a registration witness must be tied to the opening close; before the opening close's first slot nothing is registered (clock anchor), zero callbacks | s1_common:_registered/OPENING_TIED/_valid_opening_seal/registration_witnesses/opening_anchor/before_opening/is_registered/registration/preregistration_problems; s1_seal:first_slot_after | fix4::test_n3_* (4 probe pairs, 2 clock-anchor tests, 3 retrospective); fix3 deletion combinations still abort (fix3::test_c2_*, unchanged, green) | [t12_fix4_N3_red](t12_fix4_N3_red.txt) | t12_hashes | RESOLVED under the controller ruling on A1/B3.1 - TO BE DISCLOSED TO CODEX (a fabricated opening-tied file after the first slot is now presumed registration -> abort, §17.2) | |
| m-1 | stage.lock is not released as clean when an error follows the stage records: refusal, never a false abort | s1_common:stage_publication; s1_run:attest_start/do_prereg | fix4::test_minor_* (injected OSError, both stages) | [t12_fix4_minor_red](t12_fix4_minor_red.txt) | t12_hashes | RESOLVED (recovery: remove the lock with both stage records, §17.1) | |
| m-2..m-5 | reviewer-accepted residuals / choices | (S1_BUILD_EVIDENCE §16.3, §17.3) | | | | ACKNOWLEDGED (m-3 raised to Codex in §17.3) | |
| mutants | rerun all T12 mutants on the round-4 code | s1_evidence/s1_mutants_t12_fix4.py | | [run1](s1_mutants_t12_fix4_run1.txt); [final](s1_mutants_t12_fix4_final.txt); triage s1_mutants_t12_triage.txt | t12_hashes | 286 mutants: KILLED=283, KBE=0, SURVIVED=3 (the known equivalents); run 1 non-kills tightened (triage) | |

## 10. Re-review 3 of fix round 4 (reports/task-12-rereview3.md) - fix round 5

Every row below was written with its test first (behavioural RED against the round-4 sources,
s1_evidence/t12_fix5_<id>_red.txt). "fix5::" = s1_tests/test_s1_t12_fix5.py. Details: S1_BUILD_EVIDENCE §18. The
independence of review is a convention here, not an enforced isolation (same model family). This section updates §9
N-2 (its residual is restated in §18.3) and §9 N-3 (the anchor source, R-2).

| ID | Requirement | Source | Tests | Evidence | Hashes | Disposition | Reviewer |
|---|---|---|---|---|---|---|---|
| R-1 | a finalizer's MISSED record of a never-claimed opening slot (B1.2) is no orphan: an opening whose first slot never ran still seals; every other claimless record still aborts | s1_common:_finalizer_missed/opening_orphans | fix5::test_r1_probe_* (probe8); fix5::test_r1_guard_* (FAILURE without claim; 4 forged MISSED forms); 1 retrospective; fix4 deletion-orphan tests unchanged, green | [t12_fix5_R1_red](t12_fix5_R1_red.txt); [t12_fix5_green](t12_fix5_green.txt) | t12_hashes | RESOLVED | |
| R-2 | the clock anchor comes from registered evidence (opening records, valid seals, slot claims, the RUN-ACK) as the earliest source, never from plan.json alone: a plan edit after registration is the persistent abort; restoring does not resume; with no registered evidence the plan anchor and B3.2 refusals are unchanged | s1_common:opening_anchor/_registered_opening_days/_first_slot_of/_calendar_rows/before_opening (+ mailbox pass-through in registration, registration_problems, preregistration_problems) | fix5::test_r2_* (probe6 incl. restore; before any RUN-ACK incl. restore; RUN-ACK-only anchor); fix4::test_n3_* unchanged, green | [t12_fix5_R2_red](t12_fix5_R2_red.txt) | t12_hashes | RESOLVED; the calendar.json within-day shift (re-review m-3) is stated as a bounded residual in §18.3 | |
| R-3 | an opening slot after the seal leaves a claim + resolution + refused report, claim and report recording the seal's sha256; a missing seal or one differing from a recorded hash is the persistent abort at the gate; the selection never writes a seal differing from a recorded hash | s1_checkpoint:_after_opening_seal/_before_opening_seal/_claim_slot/run_opening_checkpoint; s1_common:_report_seals | fix5::test_r3_* (after-seal records; crash-like deletion after an after-seal slot; claim alone binds; selection guard) | [t12_fix5_R3_red](t12_fix5_R3_red.txt); [t12_fix5_R3b_red](t12_fix5_R3b_red.txt); [residual probe](t12_fix5_R3_residual_probe.txt) | t12_hashes | HARDENED. RESIDUAL (§18.3, FOR CODEX TO RULE ON before any registration): with no after-seal opening slot evidence left (none ran, or every after-seal claim/resolution/report deleted) plus the seal, both opening records, the sealing slot's resolution and report and opening_receipt.json deleted, before any attestation and RUN-ACK, a second, different opening seal can still be written (probe V1) - NOT closed | |
| mutants | rerun all T12 mutants on the round-5 code | s1_evidence/s1_mutants_t12_fix5.py | | [run1](s1_mutants_t12_fix5_run1.txt); [final](s1_mutants_t12_fix5_final.txt); triage s1_mutants_t12_triage.txt | t12_hashes | 300 mutants: KILLED=297, KILLED-BY-EXCEPTION=0, SURVIVED=3 (the known equivalents); run 1 non-kills tightened (triage) | |

## 11. Re-review 4 of fix round 5 (reports/task-12-rereview4.md) - fix round 6

Written with its tests first (behavioural RED against the round-5 sources, s1_evidence/t12_fix6_F1_red.txt).
"fix6::" = s1_tests/test_s1_t12_fix6.py. Details: S1_BUILD_EVIDENCE §19. The independence of review is a convention
here, not an enforced isolation (same model family). This section updates §10 R-2 (the anchor rule).

| ID | Requirement | Source | Tests | Evidence | Hashes | Disposition | Reviewer |
|---|---|---|---|---|---|---|---|
| F-1 | while plan.json carries the audit-bound plan hash (AUDIT-ACK, else the audit manifest) its opening close is authoritative for the clock anchor; evidence naming an earlier close is never an anchor source or witness - before registration a preserved refusal with zero callbacks; only an edited plan falls back to sources naming the opening close (AUDIT-ACK START, opening records, RUN-ACK, after-seal claims), never earlier than the AUDIT-ACK's opening close; probe6 stays the persistent abort | s1_common:opening_anchor/_audit_bound/_fallback_opening_days/_session_before | fix6::test_f1_probe_* (probe9 x3); fix6::test_f1_an_edited_plan_*; 4 retrospective `*_retro_*`; fix4/fix5 unchanged, green | [t12_fix6_F1_red](t12_fix6_F1_red.txt); [t12_fix6_green](t12_fix6_green.txt) | t12_hashes | RESOLVED; new outage-class residual (edited plan + both ACKs unreadable + no opening record -> plan anchor) stated in §19.3 | |
| V1 wording | §18.3 residual V1: "with no START attestation file present (never made, or deleted together with both its records and opening_books.json)" | S1_BUILD_EVIDENCE §18.3 | | | t12_hashes | DONE; V1 still FOR CODEX TO RULE ON before any registration | |
| mutants | rerun all T12 mutants on the round-6 code | s1_evidence/s1_mutants_t12_fix6.py | | [final](s1_mutants_t12_fix6_final.txt); triage s1_mutants_t12_triage.txt | t12_hashes | 305 mutants: KILLED=302, KILLED-BY-EXCEPTION=0, SURVIVED=3 (the known equivalents) | |

## 12. Re-review 5 of fix round 6 (reports/task-12-rereview5.md) - fix round 7

Written with its tests first (behavioural RED against the round-6 sources, s1_evidence/t12_fix7_G1_red.txt).
"fix7::" = s1_tests/test_s1_t12_fix7.py. Details: S1_BUILD_EVIDENCE §20. The independence of review is a convention
here, not an enforced isolation (same model family). This section updates §11 F-1 (the anchor rule).

| ID | Requirement | Source | Tests | Evidence | Hashes | Disposition | Reviewer |
|---|---|---|---|---|---|---|---|
| G-1 | (1) the audit manifest's own plan_sha256 stands in for the AUDIT-ACK only when the mailbox itself is unreadable, and only while it equals the hash the opening records bound; a missing/unknown/mismatched ack id is a broken binding; (2) a readable RUN-ACK alone witnesses and anchors; opening records, after-seal claims and the RUN-ACK can only move the anchor earlier, never be ignored; (3) once registered a changed audit manifest is the persistent abort | s1_common:_audit_bound/opening_anchor/run_ack_witness | fix7::test_g1_probe_* (probe10 x2, abort + restore still aborted); fix7::test_g1_the_run_ack_alone_*; fix7::test_g1_a_mailbox_outage_*; 3 retrospective `*_retro_*`; fix4/fix5/fix6 green (one round-6 retrospective test retired, §20.2) | [t12_fix7_G1_red](t12_fix7_G1_red.txt); [t12_fix7_green](t12_fix7_green.txt) | t12_hashes | RESOLVED; new outage-class residual (mailbox unreadable + fabricated earlier-close opening records before the opening -> a spurious abort) stated in §20.3 | |
| mutants | rerun all T12 mutants on the round-7 code | s1_evidence/s1_mutants_t12_fix7.py | | [final](s1_mutants_t12_fix7_final.txt); triage s1_mutants_t12_triage.txt | t12_hashes | 308 mutants: KILLED=305, KILLED-BY-EXCEPTION=0, SURVIVED=3 (the known equivalents) | |

## 13. Re-review 6 of fix round 7 (reports/task-12-rereview6.md) - fix round 8 (structural, operator-approved)

Brief briefs/task-12-fix8.md. "fix8::" = s1_tests/test_s1_t12_fix8.py. Details: S1_BUILD_EVIDENCE §21. The
independence of review is a convention here, not an enforced isolation (same model family). This section supersedes
the anchor dispositions of §9 N-3 (clock anchor source), §10 R-2, §11 F-1 and §12 G-1. The witnesses and their
outcomes stand; the mechanism is replaced.

| ID | Requirement | Source | Tests | Evidence | Hashes | Disposition | Reviewer |
|---|---|---|---|---|---|---|---|
| H-1 | an edited plan with the audit manifest deleted / corrupt / not a dict never switches the gate off: registration is witnessed independently of both files | s1_common:registration_state/bundle_acks/registration_problems | fix8::test_h1_probe_* (probe11 x3, abort + restore still aborted) | [t12_fix8_H1H2_red](t12_fix8_H1H2_red.txt); [t12_fix8_green](t12_fix8_green.txt) | t12_hashes | RESOLVED | |
| H-2 | a coordinated multi-file edit cannot hide a healthy-mailbox registration: ACKs are found by bundle_sha256 only; the external ACKs' bound hashes are checked | s1_common:bundle_acks/_ack_bound_problems/registration_problems | fix8::test_h2_probe_* (probe12); fix8::test_h_retro_only_the_external_acks_bind_a_coordinated_plan_edit | [t12_fix8_H1H2_red](t12_fix8_H1H2_red.txt) | t12_hashes | RESOLVED; rule-5 trade-off (an earlier trial's ACK with the same bundle = this registration, fail closed) stated in §21.3 | |
| rule | registered = an external ACK carrying the bundle OR the N-3 local witnesses at/after the AUDIT-ACK-derived anchor; editable files never set or veto the anchor; no AUDIT-ACK + local opening evidence = abort; outage = refusal (B3.4 violations still abort); every subset of the six editable files tampered = persistent abort, no resumption | s1_common:registration_state (+ removed branches §21.2) | fix8::test_h_every_subset_* (63 x 3 = 189, exhaustive); fix8::test_h_* rule edges (3 retrospective); probe6/8/9/10, B3.2 refusals, MISSED-first-slot, FAILURE-retry, outage tests green | [t12_fix8_H1H2_red](t12_fix8_H1H2_red.txt); [round-7 behaviour of the rule edges](t12_fix8_rule_retro_round7.txt) | t12_hashes | IMPLEMENTED. Removed/migrated tests listed in §21.2. The outage reading of rule 3 (B3.4 kept) is FOR CODEX TO CONFIRM | |
| mutants | rerun all T12 mutants on the round-8 code | s1_evidence/s1_mutants_t12_fix8.py | | [final](s1_mutants_t12_fix8_final.txt); triage s1_mutants_t12_triage.txt | t12_hashes | 303 mutants (11 retired with the deleted code): KILLED=298, KILLED-BY-EXCEPTION=0, SURVIVED=5 (the 3 known equivalents + 2 structural equivalents under the fix-8 rule: the C-2 RUN-ACK witness and reach mutants, subsumed by rule 1a and the external-ACK binding check - triage) | |

## 14. Re-review 7 of fix round 8 (reports/task-12-rereview7.md: H-3) - fix round 9 (controller decision + corrections)

Written with its tests first (behavioural RED against the round-8 sources, s1_evidence/t12_fix9_red.txt). "fix9::" =
s1_tests/test_s1_t12_fix9.py. Details: S1_BUILD_EVIDENCE §22. The independence of review is a convention here, not an
enforced isolation (same model family). This section updates §13 (the anchor source and rule 3).

| ID | Requirement | Source | Tests | Evidence | Hashes | Disposition | Reviewer |
|---|---|---|---|---|---|---|---|
| H-3 | the opening close date is plan.json's, used only while its sha256 equals the plan_sha256 of an AUDIT-ACK found by bundle_sha256; the anchor = that date's earliest possible first slot (13:00 New York + 45 min), never from calendar.json; an unbound plan with opening evidence = abort, without = refusal; a calendar edit after the opening seal = persistent abort, restore does not resume | s1_common:registration_state/_earliest_first_slot/EARLIEST_CLOSE_NY/registration_problems | fix9::test_h3_* (probe13 x2; anchor; plan mismatch x2) | [t12_fix9_red](t12_fix9_red.txt); [t12_fix9_green](t12_fix9_green.txt) | t12_hashes | RESOLVED under the controller decision; cost (a fabricated opening-day file between 13:45 and the real first slot aborts) FOR CODEX TO ACCEPT (§22.3) | |
| rule 3 | no AUDIT-ACK for the bundle (mailbox readable) = cannot be registered = always a preserved refusal, zero callbacks, never an abort | s1_common:registration_problems | fix9::test_rule3_* (replaces fix8 abort test; removed tests listed §22.2) | [t12_fix9_red](t12_fix9_red.txt) | t12_hashes | RESOLVED (controller correction of the fix-8 brief rule 3) | |
| subset 2nd call | the subset test asserts the post-restore command (ABORTED-INVALID, reason registration artifact) | s1_tests/test_s1_t12_fix8.py | fix8::test_h_every_subset_* (189) | [t12_fix9_green](t12_fix9_green.txt) | t12_hashes | DONE | |
| mutants | rerun all T12 mutants on the round-9 code | s1_evidence/s1_mutants_t12_fix9.py | | [final](s1_mutants_t12_fix9_final.txt); triage s1_mutants_t12_triage.txt | t12_hashes | 306 mutants: KILLED=301, KILLED-BY-EXCEPTION=0, SURVIVED=5 (the 3 known equivalents + the 2 structural equivalents declared in fix round 8: the C-2 RUN-ACK witness and reach mutants) | |

## 15. Re-review 8 of fix round 9 (reports/task-12-rereview8.md, APPROVED_WITH_MINOR) - fix round 10 (minors)

"fix10::" = s1_tests/test_s1_t12_fix10.py. Details: S1_BUILD_EVIDENCE §23. The independence of review is a convention
here, not an enforced isolation (same model family).

| ID | Requirement | Source | Tests | Evidence | Hashes | Disposition | Reviewer |
|---|---|---|---|---|---|---|---|
| m-1 | EARLIEST_CLOSE_NY self-enforcing: a provider session in calendar_range closing before 13:00 New York refuses the audit (preserved ABORTED attempt, no COMPLETE manifest, nothing ACK-dependent follows) | s1_seal:calendar_problems | fix10::test_m1_* (3 early-close cases + 1 boundary guard) | [t12_fix10_red](t12_fix10_red.txt); [t12_fix10_green](t12_fix10_green.txt) | t12_hashes | RESOLVED | |
| m-2 | fix5-7 docstrings describing superseded mechanisms updated (text only; AST-verified code unchanged) | s1_tests/test_s1_t12_fix5/6/7.py | (9 docstrings) | §23.1 | t12_hashes | DONE | |
| m-3 | implementer's stray files removed from the scratchpad probe folder | (outside the repo) | | §23.1 | | DONE for test_probe7_fix5.py; probe_codex_map.py and s1map_vd0ifvk3/ not created in this session - left for the controller | |
| mutants | T12 mutants incl. the new check | s1_evidence/s1_mutants_t12_fix10.py | | [final](s1_mutants_t12_fix10_final.txt) | t12_hashes | 309 mutants: KILLED=304, KILLED-BY-EXCEPTION=0, SURVIVED=5 (the 3 known equivalents + the 2 structural equivalents declared in fix round 8) | |
