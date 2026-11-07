# A3 Task 11 RED labels, r1 (Steps 1-3 only; Steps 4-7 HELD on BLK-3)

`t11_red.txt` is r1, after Codex f33d0501 (AMEND). The r0 RED (22 failed, 7 passed, 1 skipped) is kept as
`t11_red_r0.txt`.

r1 runs `test_s1_a3_stop.py` against the Task 11 Step 1 stub plus the Step 2 conftest/a3_helpers additions:
**32 failed, 15 passed, 1 skipped**.

What the stub is:
- `s1_seal.sampled_seals` -> {};
- `stop_record(out, rows, start, cal, bundle)` -> None;
- `stop_ready(out, rows, start, cal, bundle, now)` -> None, which means permitted (r1, BLK3-C1);
- `decide_stop` calls the legacy `current_stop`, which persists stop.json with no journal row, and returns None;
- `stop_check` is a no-op;
- the c9b4322 `stop_record` is renamed `_legacy_stop_record`.

How the 32 failures end:
- 25 end in AssertionError: plain `assert`, or `assert ..., msg`;
- 7 end in pytest Failed: 6 "DID NOT RAISE <class 'SystemExit'>" and 1 `pytest.fail("not a refusal: ...")`, whose
  chained cause is the legacy do_final's FileNotFoundError;
- there is no ImportError, NameError, AttributeError, KeyError, IndexError, TypeError or fixture error;
- in particular, none of the fixture's own checks fired. Those are `stop_history`'s "hand-written `at` == committed
  row's `at`" and "calendar == §0" asserts.

## B: behavioural RED on the stub (32)
| row(s) | test | why it fails on the stub |
|---|---|---|
| 64 | test_stop_record_is_a_pure_function_of_committed_history | stop_record is None |
| 65 | test_trial_stop_is_appended_before_stop_json_is_published | stop.json is published with no TRIAL-STOP row |
| 66, 190 | test_publication_gap_recovers_matching_bytes | no TRIAL-STOP row, so no gap state |
| 67 | test_publication_gap_with_different_history_is_stop_conflict | no stop_check: DID NOT RAISE |
| 68, 190 | test_stop_json_damaged_after_a_finalization_intent_is_invalid[deleted,changed,unparseable] | no stop_check: DID NOT RAISE |
| 192 | test_a_stop_with_a_different_detail_is_invalid_stop_conflict | DID NOT RAISE |
| 131 | test_stop_lock_is_taken_before_the_journal_read | no stop lock, no TRIAL-STOP append |
| 106 | test_stop_attest_envelope_and_member | stop_attest is not a stage |
| 107 | test_final_plan_envelope_and_member | final_plan is not a stage |
| 56 | test_finalization_stages_are_refused_while_active[stop_attest] | the legacy attest_stop attests while the journal is ACTIVE |
| 56 | test_finalization_stages_are_refused_while_active[final] | the legacy do_final hits FileNotFoundError, not a refusal |
| 62, 185 | test_post_stop_sampled_slot_is_excluded_from_the_sampled_history | no TRIAL-STOP row |
| 55, 187 | test_no_new_seal_after_the_stop | refused by the Task 7 D9 stop.json guard, not by F1 "outside ACTIVE" |
| 323 | test_stop_operation_runs_pending_seal_stages_before_trial_stop | decide_stop returns None |
| 262, 334 | test_later_close_qualified_before_stop_with_unchanged_record_is_fenced | no TRIAL-STOP request |
| 300 | test_stop_dispositions[lots-earliest] | stop_record is None |
| 301 | test_stop_dispositions[lots-later-not-chosen] | stop_record is None |
| 302 | test_stop_dispositions[timeout-last-sealed] | stop_record is None |
| 303 | test_stop_dispositions[no-valid-seal] | stop_record is None |
| 305 | test_stop_dispositions[deadline-instant-eligibility] | stop_record is None |
| r1 (i), BLK3-C1 | test_stop_dispositions[early-w-failed] | stop_record is None (the expected NO-VALID-SEAL candidate) |
| r1 (ii) | test_stop_dispositions[pending-after-timeout] | stop_record is None (expected STOPPED at d1, trigger d0 TIMEOUT) |
| r1 (iii), A2 | test_stop_dispositions[unresolved-resolved-by-missed] | stop_record is None (expected STOPPED at d1, trigger d1 MISSED) |
| r1 (iv), BLK3-C2 | test_stop_dispositions[delayed-qualified-clock] | stop_record is None |
| r1 (v), A4 | test_stop_dispositions[no-valid-seal-ineligible-seal] | stop_record is None (expected NO-VALID-SEAL; the d130 seal is not listed) |
| r1 (i), BLK3-C1 | test_stop_readiness_is_the_transaction_clock[early-w-failed@2027-04-23T20:47:00] | the stub permits before W_last |
| r1 §1.3 | test_stop_readiness_is_the_transaction_clock[timeout-last-sealed@2027-04-26T11:59:59] | the stub permits 1 s before W_last |
| r1 §1.3, A6 | test_stop_readiness_is_the_transaction_clock[lots-later-not-chosen@2026-10-27T11:59:59] | the stub permits before W(d0) of the missed d0 |
| r1 (i), BLK3-C1 | test_early_w_failed_commits_no_stop | the stub's stop_ready permits at 20:47Z. The test's "no TRIAL-STOP" half holds on the stub (the legacy decide is RUNNING) |
| r1 (iv), BLK3-C2 | test_completing_row_at_is_provenance_not_commit_time | stop_record is None |

## ctrl: expected passes on the stub (15)
| row(s) | test | why it passes on the stub |
|---|---|---|
| 304 | test_stop_dispositions[pending-excluded] | **ctrl**: the stub's stop_record is always None, and None is expected. The GREEN must keep None while d0 is PENDING. |
| r1 (iii), A2 | test_stop_dispositions[unresolved-blocks] | **ctrl**: same. The GREEN must return None while d1 is UNRESOLVED. The rev-0 draft would have returned STOPPED at d2. |
| (B1.5) | test_pending_slot_blocks_the_stop | **ctrl**: stop_record None. |
| (rule not met) | test_stop_rule_not_met_refuses_with_no_row | **ctrl**: the stub never appends a row. |
| 69 | test_stop_outcome_is_fixed_by_the_journal | **ctrl**: F2.5 is enforced by the Task 2 journal (`_stop` 4c). On the stub the STOP is the transitional synthetic one. |
| 184 | test_final_plan_before_stop_attest_refuses_with_no_row | **ctrl (precondition)**: the legacy "no stop attestation recorded". The regex also accepts the GREEN's stage refusal. |
| 56 | test_finalization_stages_are_refused_while_active[final_plan] | **ctrl (precondition)**: the legacy "no stop attestation recorded"; the F1 wording is also accepted. |
| 56 | test_finalization_stages_are_refused_while_active[score] | **ctrl (precondition)**: "no S1-SCORE-ACK" (an ACTIVE fixture has none); the F1 wording is also accepted. |
| r1 (i) | test_stop_readiness_is_the_transaction_clock[early-w-failed@2027-04-26T12:00:00] | **ctrl**: the positive control. The stub always permits. It guards against an over-blocking GREEN: at W_last, the sparse d129 counts missed. |
| r1 §1.3 | test_stop_readiness_is_the_transaction_clock[timeout-last-sealed@2027-04-26T12:00:00] | **ctrl**: the `>=` boundary. The stub always permits. |
| r1 §1.3 | test_stop_readiness_is_the_transaction_clock[lots-later-not-chosen@2026-10-27T12:00:00] | **ctrl**: the `>=` boundary. The stub always permits. |
| r1 (v), A4 | test_damaged_ineligible_seal_is_invalid[deadline-instant-eligibility-deleted, -corrupt] | **ctrl**: the existing Task 7/10 E2.6 / F4-table check already makes a missing or corrupt CREATED seal INVALID (stage-replaced). The GREEN, when it adapts stop_problems, must not remove it (A4). |
| r1 (v), A4 | test_damaged_ineligible_seal_is_invalid[no-valid-seal-ineligible-seal-deleted, -corrupt] | **ctrl**: same, in a NO-VALID-SEAL history. |

## Held (1)
- **row 189** `test_in_flight_slot_started_before_the_stop_completes_but_never_enters_final_or_score`: SKIPPED. It
  needs `s1_seal.sampled_history` (Task 13; ruling B11/B12/B16).

## Test-text deviations from the plan's Step 2 code (ruling R-G; no map-row outcome changed)
- **Deviations 1-6** are unchanged from r0:
  - D1: the transitional synthetic TRIAL-STOP fallback in the conftest;
  - D2: the row 189 hold;
  - D3: asserts before dereferences;
  - D4: the `_envelope` assert;
  - D5: `match=` on every `pytest.raises`;
  - D6: `_refused`.
- **r1 additions** (Codex f33d0501):
  - `s1_seal.stop_ready` is a stub, and is named in the interface;
  - `conftest._write_seal` gains keyword-default hooks `minutes`, `r_at`, `q_at`, `before_qualified` and
    `stage_at`; the existing callers are unchanged;
  - `a3_helpers.stop_history` gains the r1 cases;
  - new tests: `test_stop_readiness_is_the_transaction_clock` (6), `test_early_w_failed_commits_no_stop`,
    `test_completing_row_at_is_provenance_not_commit_time` and `test_damaged_ineligible_seal_is_invalid` (4);
  - every `want` value is hand-written or read from a named committed row / CREATED file, never from `stop_record`.
