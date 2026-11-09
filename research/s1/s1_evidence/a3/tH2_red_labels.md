# A3 H2 RED labels (tH2_red.txt)

97 instances against the H2 Step-1 interface stub (a clean export of HEAD 5c5a511 plus the additive stub edits in
scratchpad `tH2/mk_stub.py`; conftest = HEAD's): **86 failing, 11 passing**. No ImportError, AttributeError or
collection error. The failures are labelled below by *how* they fail, because ruling B3 counts a RED only when it is an
assertion or a pytest `Failed` at the agreed line:

- **77 behavioural REDs (B3-countable):** 74 are `Failed: attest_stop refused on the NVS branch: stop attestation
  refused: no stop recorded (status NO-VALID-SEAL)` at test_s1_a3_nvs.py:48 (`ok()` inside `nvs_chain`, the plan's
  design: a refusal of a step the NVS branch must permit is a behavioural failure); 3 are `AssertionError`s in the
  un-held test_s1_run.py tests.
- **4 setup REDs (NOT B3-countable, recorded honestly):** `s1_trial.Refusal: no S1-ACQUIRE-ACK ... no S1-SCORE-ACK can
  follow (F7.1)` raised by HEAD's `token()` inside the fixture (`s1_ack` of a PREREG-prev SCORE-ACK). HEAD cannot even
  build the G1.4 NVS shape; on GREEN the same lines build and the tests then reach their own oracles.
- **5 held-test REDs (NOT B3-countable):** the un-held tests whose body calls `r.score` directly fail with the stub's
  `SystemExit: stage score: STAGE-INTENT REFUSE with no row: stage score: predecessor final is not CREATED (F1)` - the
  exact NVS-1 defect the hold recorded (G1.0). Their oracle lines are assertions on the returned report; the plan's
  Step 3 says the held tests are "recorded RED (they fail on the NVS refusals)".

| row | instances | label | why |
|---|---|---|---|
| 400 | test_nvs_branch_commits_inconclusive_score | **RED** (nvs_chain) | the stub's attest_stop refuses NVS (s1_run.py:700 at HEAD) |
| 401 | 14 defects | **RED** x14 (nvs_chain) | the fixture cannot reach the NVS SCORE-ACK; on GREEN each is a refusal matched to its own reason (DEFECT_REFUSAL) |
| 402 | stopped, timeout | setup RED x2 | HEAD's token() refuses a PREREG-prev SCORE-ACK (G1.4 shape absent) |
| 402 | test_wrong_branch_score_ack_names_the_branch (added) | setup RED | same; on GREEN its oracle is `wrong branch (NVS-A3)` |
| 403 | forged-stop-json | `retro` | the F2.4 stop_check INVALID (registration-artifact) exists today |
| 403 | bad-stop-detail | setup RED | HEAD's token() (PREREG-prev SCORE-ACK) |
| 403 | damaged-qualified, damaged-ineligible-seal, damaged-opening, registered-bundle-changed | **RED** x4 (nvs_chain) | the NVS chain cannot be built; on GREEN each keeps its existing INVALID |
| 404 | nvs | **RED** (nvs_chain) | |
| 404 | normal-control | `ctrl` | the normal-branch null is flagged today |
| 405 | before-w-last, pending-w-no-lots, unresolved | `retro` x3 | no TIMEOUT/NVS STOP commits and attest_stop refuses RUNNING today |
| 406 | publication-gap, same-ack-replay, conflicting-intent, computation-error | **RED** x4 (nvs_chain) | |
| 407 | test_nvs_close_scored_evidence | **RED** (nvs_chain) | |
| 450 | committed-invalid, local-abort-after-stop-attest | **RED** x2 (nvs_chain) | |
| 451 | integration + unit | **RED** x2 (nvs_chain) | |
| 452 | 5 cases | **RED** x5 (nvs_chain) | |
| 453 | 4 cases + the G1.6 control + the OP-25 in-transaction test (both added) | **RED** x6 (nvs_chain) | the OP-25 test's discriminating RED is mutant m1 (tH2_mutants.txt) |
| 467 | nvs-healthy | **RED** (nvs_chain) | |
| 467 | discovered-in-score, numeric-healthy | `ctrl` x2 | OQ-28 and a numeric score are unchanged |
| 480 | 2 cases | **RED** x2 (nvs_chain) | discriminating C1 RED without the NVS branch: tH2_red_c1_probe.txt (private function) and mutant m2 |
| 481 | 1 | **RED** (nvs_chain) | |
| 482 | scored-after-score, invalid-after-prereg, withdrawn-after-acquire | `ctrl` x3 | chronology = rank in a normal chain (C1.4) |
| 483 | 6 (2 cases x SCORED/WITHDRAWN/INVALID) + 3 attribution boundaries (added) | **RED** x9 (nvs_chain) | discriminating RED of the invalid-candidate rule: mutant m3 |
| 484 | 2 | **RED** x2 (nvs_chain) | |
| 485 | 9 (3 map ids + 6 NOP-5 refusal cases) | **RED** x9 (nvs_chain) | procedural model, O-C2 |
| 486 | 3 | **RED** x3 (nvs_chain) | |
| 487 | 1 | **RED** (nvs_chain) | after GREEN a passing residual characterization, never a refusal test |
| 488 | 3 | **RED** x3 (nvs_chain) | procedural model, O-C2 |
| 489 | 2 | **RED** x2 (nvs_chain) | discriminating RED of the lower-bound check: mutant m4 |
| 490 | 1 | **RED** (nvs_chain) | |
| G1.9 | test_s1_checkpoint_7b.py::test_no_valid_seal_trial_scores_no_valid_seal | held RED (SystemExit) | pred final not CREATED |
| G1.9 | test_s1_run.py::test_score_no_valid_seal_is_never_fail | held RED (SystemExit) | |
| G1.9 | test_s1_run.py::test_early_score_ack_while_running_is_refused_with_no_output (match changed) | **RED** (AssertionError :636) | the early ACK is refused for the old reason on HEAD |
| G1.9 | test_s1_run.py::test_post_end_score_ack_scores_a_no_valid_seal_trial | **RED** (AssertionError :655) | HEAD's fixture posts an ACQUIRE-ACK on NVS |
| G1.9 | test_s1_run.py::test_combined_abort_and_no_valid_seal_is_recorded_invalid_and_refused | `retro` (H1) | H1's gate recording (5c5a511) already gives this oracle; held only for the NVS branch's existence |
| G1.9 | test_s1_run.py::test_score_ack_before_the_no_valid_seal_window_end_is_refused | **RED** (AssertionError :871) | old refusal reason |
| G1.9 / N-2 | test_s1_run.py::test_post_window_score_ack_scores_no_valid_seal (split) | held RED (SystemExit) | |
| G1.9 | test_s1_t12_a9.py::...[NO-VALID-SEAL] | held RED (SystemExit) | |
| G1.9 | test_s1_task11.py::...[no-valid-seal] | held RED (SystemExit) | |

Counts: 97 = 77 behavioural RED + 4 setup RED + 5 held RED (SystemExit) + 11 passing (`retro` 5: 403 forged-stop-json,
405 x3, the renamed :719 test; `ctrl` 6: 404 normal-control, 467 x2, 482 x3).
