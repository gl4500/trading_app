# A3 H2 old -> new (Erratum 2 r4 G1; Clarification 1 r2 C1-C3; base 5c5a511, baseline 5188 passed / 7 skipped)

Method: a discovery run of the whole suite with the H2 product, the conftest change and the new/un-held tests (8
parallel pytest processes, scratchpad only, not evidence) gave 5278 passed, **5 failed, 0 skipped** (5283 instances =
5188 + 7 un-held + 88 new). The 5 failures are all in existing tests; each is listed and classified below and was
updated in place with an `A3 H2 (intended, ...)` or `A3 H2 (fixture incompatibility, ...)` comment naming the old
expectation. One further new test was then added (row 453, OP-25 in-transaction ACK view), so the evidence suite has
5188 + 7 + 89 = 5284 instances. No test was deleted, skipped, held or xfailed.

## Classes

- **Fixture incompatibility (conftest, not an assertion):** `_s1_finish` - the NVS branch now gets `attest_stop` (the
  `stop["status"]` condition includes NO-VALID-SEAL) and NO S1-ACQUIRE-ACK (G1.2/G1.6: there is no final plan, ACQUIRE
  or final on the NVS graph; old: an ACQUIRE-ACK at t + 2 h). Every NVS fixture user (`s1_state(lots=[],
  seal_days=[])`) re-ran in the discovery suite: the only changed outcomes are the rows below.
  `conftest.S1_NVS_HELD` is removed (unused) with its 4 imports.
- **Intended (G1.4 two-shape PRED, F7.1):** an S1-SCORE-ACK's mailbox-level predecessor is the latest chain ACK
  created before it among {ACQUIRE, PREREG}. A SCORE-ACK created BEFORE the ACQUIRE-ACK therefore has the PREREG-ACK as
  its predecessor and its prev (the ACQUIRE-ACK) is refused as such - instead of "created not after its predecessor".
  On the NVS fixture (no ACQUIRE-ACK) an early SCORE-ACK is refused by its F6.1 journal binding instead. Same refusal,
  zero output, different text.
- **Intended (G1.4, token default prev):** `s1_trial.token("S1-SCORE-ACK")` defaults prev to the ACQUIRE-ACK when one
  exists, else the PREREG-ACK.
- **Fixture incompatibility (C1.2, ruling NOP-1):** a CLOSE created after a non-chain-valid chain ACK of its trial no
  longer closes it (the retired rank reading did).
- **Intended (G1.3/G1.7, OP-4):** NVS reports carry `classification: "INCONCLUSIVE"`; attest_stop.json on NVS has the
  two nulls. Only the un-held tests and the new files assert it (no existing test asserted either).
- **Intended (G1.6):** "NO-VALID-SEAL: nothing to acquire" at write_final_plan / do_final. No existing test asserted the
  old `_stop_state` text "final plan refused: the trial is NO-VALID-SEAL" for an NVS trial (none failed).
- **Intended (C3.1):** the final-snapshot report gains `written_utc`. No existing test asserts the report's exact key
  set (none failed).
- **Expected none (C1.4):** every existing CLOSE test (test_s1_a3_trial.py and the others) kept its verdict: in a
  valid normal chain chronology equals rank. Observed: none failed, except the C1.2 fixture case below (an INVALID
  chain, not a normal one).
- **Intended (C2):** no existing test expected a runtime refusal for a wrong CLOSE evidence hash (none failed); the
  residual is characterized by row 487.

## Test by test (existing tests whose expectation changed)

| # | test | old | new | class |
|---|---|---|---|---|
| 1 | test_s1_run.py::test_score_ack_created_while_running_is_refused_after_the_stop | `S1-SCORE-ACK early: created not after its predecessor` | `S1-SCORE-ACK early: prev 'acq-ack' is not the S1-PREREG-ACK` (still refused, nothing written; the unit `_pre_reserve_gate` half unchanged) | G1.4 PRED |
| 2 | test_s1_run.py::test_score_ack_strictly_after_the_stop_with_a_final_manifest_scores | `S1-SCORE-ACK at-stop: created not after its predecessor` | `S1-SCORE-ACK at-stop: prev 'acq-ack' is not the S1-PREREG-ACK`; the post-stop ACK still scores SHADOW PASS | G1.4 PRED |
| 3 | test_s1_run.py::test_cr_no_valid_seal_end_when_the_deadline_is_not_a_session | `S1-SCORE-ACK before-end: created not after its predecessor` (via the fixture's ACQUIRE-ACK) | `S1-SCORE-ACK before-end: created not after the journal row it references` (NVS fixture: no ACQUIRE-ACK; the ACK precedes the stop_attest CREATED row); the unit half unchanged | G1.4 PRED + conftest |
| 4 | test_s1_a3_gate.py::test_identity_refusals_have_zero_callbacks[closed-trial-same-bundle-ack] | the other (closed) trial: AUDIT -30 d, RUN-ACK -29 d (no OPENING-ACK: not chain-valid), CLOSE -28 d prev = the RUN-ACK - closed by the rank reading | CLOSE -29 d prev = the other AUDIT-ACK (a valid closure), RUN-ACK -28 d (after the closure: an escalation of the closed trial only). Expected refusal unchanged (`'not-this-trials-run-ack' is not the trial's S1-RUN-ACK`) | C1.2 fixture |
| 5 | test_s1_a3_gate.py::test_explicit_mailbox_is_used_for_token_and_ack | `r.score_token` refuses `no S1-ACQUIRE-ACK` | `no S1-PREREG-ACK` (the explicit mailbox is still used; the refusal names the default prev of the NVS shape) | G1.4 token |

## The un-held NVS-1 tests (old: `skip(reason=S1_NVS_HELD)`) and T13 N-2

| # | test | new expectation |
|---|---|---|
| H1 | test_s1_checkpoint_7b.py::test_no_valid_seal_trial_scores_no_valid_seal | the snapshot is taken (trial_status NO-VALID-SEAL), then NVS-A1: verdict NO-VALID-SEAL, classification INCONCLUSIVE, nomination false |
| H2 | test_s1_run.py::test_score_no_valid_seal_is_never_fail | + classification INCONCLUSIVE, no levels, no n |
| H3 | test_s1_run.py::test_post_end_score_ack_scores_a_no_valid_seal_trial | the fixture is the NVS branch (attest_stop.json, no ACQUIRE-ACK); the re-issued SCORE-ACK's prev = the PREREG-ACK; NVS-A1 |
| H4 | test_s1_run.py::test_combined_abort_and_no_valid_seal_is_aborted_invalid -> renamed ..._is_recorded_invalid_and_refused | NVS-A9(b) per G6: `S1_LOCAL_ABORT` refusal, exactly one established-violation/local-abort row (`s1_local_abort_recorded`, original_reason "x"), zero `_score` calls, no score rows (old: a committed ABORTED-INVALID score) |
| H5 | test_s1_run.py::test_score_ack_before_the_no_valid_seal_window_end_is_refused | T13 N-2 split: the early refusal (match now `created not after the journal row it references`, G1.4 PRED), the unit `_pre_reserve_gate` R-1 check and "no score/" - runs |
| H5b | test_s1_run.py::test_post_window_score_ack_scores_no_valid_seal (new, split out) | only the final NVS-A1 line (verdict NO-VALID-SEAL, classification INCONCLUSIVE) |
| H6 | test_s1_t12_a9.py::test_a9_every_non_numeric_disposition_makes_no_valuation_call[NO-VALID-SEAL] | NVS-A1 with every valuation helper spied: zero calls; + classification INCONCLUSIVE, nomination false |
| H7 | test_s1_task11.py::test_m7_every_report_kind_carries_restarts_and_the_quantity_bridge[no-valid-seal] | NVS-A1 + the restarts and quantity_bridge keys; + classification INCONCLUSIVE, no levels |
| N-2 | test_s1_run.py::test_early_score_ack_while_running_is_refused_with_no_output | docstring corrected (it no longer describes the split-out score half); match `created not after the journal row it references` (G1.4 PRED + conftest; old `created not after its predecessor`) |

Count: 7 skips -> 0; +1 split-out test.

## Fix round 1 (review I-1, I-2, M-2..M-7)

Full suite after the fix round: **5292 passed, 0 skipped** (tH2_fix1_full.txt) = 5284 + 8 new instances. No existing
test outside the H2 files changed outcome; the changes are all inside test_s1_a3_nvs.py / test_s1_a3_close.py:

| # | test | old | new | class |
|---|---|---|---|---|
| F1 | test_s1_a3_close.py::test_ambiguous_or_invalid_predecessor_refuses | 2 cases x 3 reasons | + `duplicate-before-close` x 3 reasons (a non-earliest same-kind chain ACK before the CLOSE refuses it, C1.2) | I-1 (intended; RED x3) |
| F2 | test_s1_a3_nvs.py::test_forged_or_damaged_nvs_never_inconclusive[bad-stop-detail] | refused by the missing-snapshot precondition (`refused\|stop-conflict`) | a terminal NVS-candidate history with a forged STOP detail: attest_stop `no stop recorded (status NO-VALID-SEAL)`, score `wrong branch (NVS-A3)`, no row | I-2 (test strengthened; kills s1_no_detail) |
| F3 | ...[bad-stop-detail-publication-gap] (new) | - | INVALID (stop-conflict) at the gate | I-2 (+1) |
| F4 | test_s1_a3_close.py::test_close_candidate_strictly_before_boundary[score-ack, acq-at-close] (new) | - | strict "created before X" | M-2 (+2) |
| F5 | test_s1_a3_close.py::test_nvs_fork_withdrawn_names_latest_acquire | - | + `Trial.latest` / token default prev = `acq-late` | M-3 |
| F6 | rows 480, 402, 452[missing-before-issuance] | `escalate\|refuse`; `no final acquisition manifest\|wrong branch \(NVS-A3\)`; `no final snapshot\|absent` | `refuse and escalate`; `score refused: no final acquisition manifest yet \(COMPLETE or ABORTED\)`; `score refused: no final snapshot \(run s1_checkpoint\.py --final-snapshot` | M-4 (pins) |
| F7 | test_nvs_predicate_error_in_the_intent_transaction_refuses (new) | - | an in-transaction predicate OSError is a refusal with a reason, no row | M-5 (+1; RED) |
| F8 | test_nvs_predicate_file_not_found_is_no_missing_prereg (new) | - | a predicate FileNotFoundError refuses "cannot be evaluated" | M-6 (+1; RED) |
| F9 | test_score_ack_written_utc_lower_bound[created-gt-written] | any non-lower-bound refusal accepted | the score commits (NO-VALID-SEAL, INCONCLUSIVE, CREATED) | M-7 |
