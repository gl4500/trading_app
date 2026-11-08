# A3 H1 old -> new (Erratum 2 r4 G6; base 6172c9b, baseline 5160 passed / 7 skipped)

Method: a discovery run of the whole suite with the H1 product and the new test file (8 parallel pytest processes,
scratchpad only, not evidence) found **14 failures, all in existing tests**, and nothing else (5174 passed, 7 skipped:
5160 + the 28 new instances = 5188 = 5174 + 14). Every one is listed and classified below; each was then updated in
place with an `A3 H1 (intended, ...)` comment naming the old expectation. No test was deleted, skipped or held. The
7 skips are the unchanged NVS-1 holds (conftest.S1_NVS_HELD; test_s1_run.py:719 stays held until H2).

OP-16 (DOC_PINS += Erratum 2 r4 and Clarification 1 r2) changes `c.bundle_sha256()` from
`c578d6ba451dda4264ce8bfa0964553f9af41799bbd80a38c721be789c9744b7` (HEAD) to
`ea6cf7ad2644938e4ec4d8418d9636df418d61600a4e7e20fe1739b0acff8ed3`. A grep of research/s1 `*.py` for the old hex and
its 12-character prefix finds nothing; every fixture computes the bundle live. **Zero OP-16 fixture or bundle test
changes** (the bundle tests iterate over `c.DOC_PINS` and pass with the two new entries).

## Classes

- **G6 (intended, Erratum 2 r4 G6.4/G6.6/G6.7; supersedes A2.3's recording location and the M-3 / OQ-28
  known-abort paths):** a test writes a local `aborted.json` with no TRIAL-INVALID on a trial with journal rows and
  then expects a command-local refusal (`aborted.json exists ... no new capture`, `ABORTED`, `SCORE-ACK`, OQ-16 "not
  STOPPED", a stage-replaced verdict) or an OQ-28 `s1_score_invalid` (registration-artifact). New: the command's trial
  gate commits exactly one TRIAL-INVALID `reason/established-violation` (subtype `local-abort`, bound to the witness
  bytes) and refuses with no work. New expectations use `conftest.S1_LOCAL_ABORT` (the refusal text) and
  `conftest.s1_local_abort_recorded` (exactly one such row, its evidence copy, `abort_sha256` = the current witness
  bytes, no score dir).
- **O18 (intended, G6.2):** a corrupt `aborted.json` is readable malformed bytes, confirmed on a re-read: recorded with
  `malformation: "unparseable JSON"` and no invented `original_reason`.
- **G6.3 truthfulness (intended):** the journal-failure refusal of `invalidate` now states whether the local abort was
  published.
- **Setup order (test-side, no assertion changed):** a test that left its own guard's abort in place across a later
  gate call.

## Test by test

| # | test | old | new | class |
|---|---|---|---|---|
| 1 | test_s1_checkpoint_7b.py::test_final_snapshot_on_an_active_trial_with_a_local_abort_is_refused_oq16 | `final snapshot refused: the trial is not STOPPED (OQ-16)` | `S1_LOCAL_ABORT`; one local-abort row (original_reason "semantic receipt changed"); still no final_snapshot/ | G6 |
| 2 | test_s1_t12_a2.py::test_a2_a_persisted_invalidity_is_never_converted_into_a_valid_stop | attest_stop refuses `ABORTED` | attest_stop's gate: `S1_LOCAL_ABORT`, one local-abort row (witness reason "bundle" bound as provenance only, G6.2), no attest_stop.json; `final_plan_record` (no trial gate) still refuses `ABORTED`; stop.json unchanged | G6 |
| 3 | test_s1_t12_a9.py::test_a9_every_non_numeric_disposition_makes_no_valuation_call[ABORTED-INVALID] | `s1_score_invalid` (OQ-28 registration-artifact, staged ABORTED-INVALID report) | score refused `S1_LOCAL_ABORT`, one local-abort row, zero valuation calls (the test's point kept); no report exists | G6 (G6.6) |
| 4 | test_s1_t12_fix2_b3.py::test_b3_an_earlier_bundle_abort_stays_first | first checkpoint: `s1_replaced("attest_start.json")` (F4 stage-replaced); second: `trial INVALID (reason/stage-replaced)` | first: `S1_LOCAL_ABORT` (the recovery runs before the F4 stage table, G6.4 placement) with original_reason "bundle"; second: `trial INVALID (reason/established-violation)`; aborted.json reason still "bundle" (first wins) | G6 |
| 5 | test_s1_t12_fix2_b3.py::test_b3_a_corrupt_aborted_json_fails_closed | `aborted.json exists .*no new capture` | `S1_LOCAL_ABORT`; record has `malformation: "unparseable JSON"`, no original_reason; still no capture, no seal | G6 + O18 |
| 6 | test_s1_t12_fix2_b3.py::test_b3_a_corrupt_aborted_json_fails_closed_at_prereg | prereg refuses `ABORTED` | `S1_LOCAL_ABORT`; malformation recorded; no prereg.json | G6 + O18 |
| 7 | test_s1_a3_prestart.py::test_a_second_opening_seal_is_caught_beyond_the_opening_gate | the guard `_before_opening_seal` writes its own local abort; the test removed it only before the seal replacement, after an intermediate `t.gate` | the test removes the guard's abort right after the guard call (before that gate), then asserts it is absent where it used to delete it; every assertion unchanged. Left in place, the witness is now recorded by that gate (the G6 behaviour, covered by rows 460/466) | setup order |
| 8 | test_s1_a3_residual.py::test_uncommitted_detection_may_resume_and_is_labelled_lost_detection | `... (Outage): refused; F8.1 residual (...)` | `... (Outage): refused; local abort published; F8.1 residual (...)` + aborted.json exists | G6.3 truthfulness |
| 9 | test_s1_run.py::test_score_aborted_checkpoint_is_invalid_and_unpriced | `s1_score_invalid` -> staged ABORTED-INVALID report | score refused `S1_LOCAL_ABORT`, one local-abort row; the ABORTED-INVALID verdict / no nomination / no levels asserted on the private `_score` helper at unit level (G6.7: diagnostic only) | G6 |
| 10 | test_s1_run.py::test_score_ack_before_the_recorded_abort_is_refused | step 1 `match="SCORE-ACK"`; step 2: SCORE-ACK re-issued at now-30 min, then `s1_score_invalid` ABORTED-INVALID | step 1 `S1_LOCAL_ABORT` (the gate records before any SCORE-ACK check), one row, no score; step 2: the same SCORE-ACK again -> `trial INVALID (reason/established-violation): no work`, still one row. (A re-issued ACK at now-30 min would now precede the INVALID row and be refused by the F6.1/F7.1 ACK binding, so it is not re-issued.) | G6 (plan Step 6 named this test) |
| 11 | test_s1_task11.py::test_c1_checkpoint_after_an_abort_is_post_stop_and_never_seals | `aborted\.json exists .*no new capture` | `S1_LOCAL_ABORT`, one local-abort row; still no capture, no seal | G6 |
| 12 | test_s1_task11.py::test_i4_final_plan_refused_after_an_abort | `ABORTED` | `S1_LOCAL_ABORT`, one local-abort row; no final_plan.json | G6 |
| 13 | test_s1_task11.py::test_i4_do_final_rechecks_the_stop_before_reserving[aborted-...] | why = `ABORTED-INVALID` | why = `S1_LOCAL_ABORT`; still no request, no final/ | G6 |
| 14 | test_s1_task11.py::test_m7_every_report_kind_carries_restarts_and_the_quantity_bridge[aborted] | `s1_score_invalid` staged report carries restarts + quantity_bridge | score refused `S1_LOCAL_ABORT` + one row; the report-shape assertions run on the unit-level `_score` diagnostic (G6.7) | G6 (plan Step 6 named m-7 aborted) |

Plan Step 6 named members: test_s1_run.py `test_score_ack_before_the_recorded_abort_is_refused` (#10), the
ABORTED-INVALID kind of test_s1_t12_a9.py (#3), test_s1_task11.py m-7 aborted (#14), and test_s1_checkpoint_7b oq16
(#1) - all four occurred. The other ten are the same G6 class or its text consequences.

**C-O16c (r4 requires the list): tests that relied on `write_abort` creating a missing s1_out - none.** No failure
was an `OutputRootGone` or a missing-root refusal; every existing `write_abort` caller in the suite runs on an existing
s1_out.

## Test-infrastructure addition

- conftest.py: `S1_LOCAL_ABORT` (regex of the gate's recording refusal) and `s1_local_abort_recorded(root)` (asserts
  exactly one TRIAL-INVALID `reason/established-violation`, its `invalid/<seq>.json` copy with `detail` =
  `detail_of(record)`, `subtype` = `s1_trial.LOCAL_ABORT`, `abort_sha256` = the current aborted.json bytes, and no
  `s1_out/score`). Additive; no existing fixture changed.

## New tests

- research/s1/s1_tests/test_s1_a3_abort_recovery.py: 28 instances (rows 460 x3, 461, 462 x2, 463, 464 x2, 465 x6,
  466 x7, 468 x4, 469 = 27, plus the OP-16 pin test).
