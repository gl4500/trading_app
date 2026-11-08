# A3 Task 12 RED labels

`t12_red.txt` runs `s1_tests/test_s1_a3_final.py` against the Task 12 Step 1 stub: **33 failed, 4 passed**.

The stub:
- `s1_collect.final_policy(fplan, prereg, cutoff)` returns `{"families": []}`;
- `do_final` is unchanged: the c9b4322 body (legacy request path straight into s1_out, `_reserve` /
  `_run_attempt` / `_abort`) behind the gate;
- `s1_stage.ENFORCED` is unchanged (no `final`), and conftest is unchanged.

How the 33 failures end (the last frame of each failure section):
- 29 end in AssertionError: a plain `assert`, an `assert ..., msg`, or pytest.raises' "Regex pattern did not match";
- 4 end in pytest Failed "DID NOT RAISE <class 'SystemExit'>";
- none ends in an ImportError, NameError, AttributeError, KeyError, IndexError, OSError, TypeError or a fixture
  error. Chained SystemExit/Refusal frames appear only as the input of a "Regex pattern did not match".

## B: behavioural RED on the stub (33)
| test | why it fails on the stub |
|---|---|
| test_final_policy_is_exactly_the_f49_final_rows | `final_policy` is the empty stub |
| test_normal_final_commits_every_member | no stage: no PREPARED commitment in staging |
| test_final_members_are_the_fixed_names_plus_one_page_per_request | the same |
| test_final_manifest_projection_equals_the_members | the same |
| test_final_envelope_inputs_and_members | no stage: no intent.json |
| test_acquire_ack_binds_prev_stop_line_and_is_not_before_the_lag[ok] | no stage/final rows (legacy path) |
| test_acquire_ack_binds_prev_stop_line_and_is_not_before_the_lag[before-lag] | DID NOT RAISE: no OQ-22 refusal |
| test_empty_ca_family_sends_no_request_and_final_completes[window, full_history, both] | no PREPARED commitment (see deviation 1) |
| test_both_ca_families_are_requested_and_reconciled | the same (deviation 1) |
| test_final_request_order_is_the_collector_order | the same (deviation 1) |
| test_cutoff_is_the_intent_new_york_date_across_midnight | the cutoff is the reservation date (B-old: `'2026-10-30' != '2026-10-30'` fails the chained `!=`) |
| test_damaged_final_member_is_invalid_before_valuation_with_zero_valuation_calls (16) | the damaged member reaches the score: no stage-replaced refusal (the stub's score refuses "no final snapshot" instead) |
| test_final_extra_page_or_orphan_provenance_is_invalid[extra-page, missing-page, extra-full-page] | DID NOT RAISE: `final` is not in ENFORCED |
| test_final_provider_anomaly_after_the_stop_is_invalid_with_no_retry | the legacy "final: ABORTED (Structural)" refusal, not INVALID (provider-structural) |

## ctrl: passes on the stub (4)
| test | why it passes on the stub |
|---|---|
| test_acquire_ack_binds_prev_stop_line_and_is_not_before_the_lag[before-attest] | the ACK precedes the final_plan row it binds: the gate's F6.1 journal binding refuses it (also the legacy "not strictly after the stop attestation") |
| test_acquire_ack_binds_prev_stop_line_and_is_not_before_the_lag[wrong-stop-line] | the gate's F7.1 binding: "stop_line_sha256 is not the TRIAL-STOP line" |
| test_acquire_ack_binds_prev_stop_line_and_is_not_before_the_lag[wrong-prev] | the trial scan: "prev 'audit-ack' is not the S1-PREREG-ACK" |
| test_no_provider_request_before_stop_attest_and_acquire_ack | no final plan (Task 11 S4-8 refusal) |

## Deviations from the brief's test text (ruling R-G; no map-row outcome changed)
1. **The brief labels the empty-CA, both-families and request-order tests `retro` (passing on c9b4322).** As written
   they read the PREPARED commitment (`commitment()`), which the legacy path never writes, so they fail on the stub
   (behavioural). Labelled B here. Their c9b4322 property (the request sequence) is unchanged.
2. **`commitment()` and the envelope test assert that the staged file exists** before reading it, so the stub fails
   on an assertion, not on an OSError.
3. **The `[ok]` case asserts that the stage/final rows are not empty** before indexing `[-1]` (no IndexError).
4. **`jrows()` reads the open trial through `t.trials(t.scan(...))`**, as conftest.s1_first_invalid does. With
   `open_trial`, the `[wrong-prev]` oracle itself raised the trial-scan Refusal: the malformed chain makes
   open_trial refuse, so the rows could never be read (it would fail on the GREEN too).
5. **`ready()` places the ACK at max(lag, final plan instant) + 1 min.** For a TIMEOUT stop (`lots=[]`,
   `seal_days=[0]`) the stop close is the last sealed close (day 0), so the lag (2026-10-29) is months before the
   attestation (2027-04-27). An ACK at the lag then precedes the final_plan row it binds, and the gate refuses it
   (F6.1). The brief's literal helper did that in the `[window]` and `[both]` cases.
6. **`match=` on every pytest.raises** (inherited rule): the ACK cases use `ACK_REFUSAL[case]` (the intended
   refusal texts above; before-lag is the OQ-22 text), and the no-attest test uses "no final plan (final_plan comes
   first, F1)".
