# A3 Task 12 (final acquisition stage) - old -> new classification

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

## intended (F4.9 / OQ-22 / F1 "each stage once"): oracle changed to the new rule
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

## input (fixture / ACK placement; oracle unchanged)
| test | change |
|---|---|
| test_s1_collect `final_setup` (used by the collect final tests, test_s1_t12_a7 probe i and test_s1_t12_mutant_followups::test_mf_the_final_manifest_binds_the_bundle_and_the_persisted_stop) | the ACQUIRE-ACK goes to max(attestation + 1 h, the lag), not attestation + 1 h. For this trial: 2026-10-30T20:00Z (OQ-22, brief Step 6, first bullet). Failing before it: a7 probe i, mf, request_params, requests_every_symbol (all "the ACQUIRE-ACK precedes the acquisition lag") |
| test_s1_task11 `_acquire_ready` (i4 acquire + i4 rechecks x3) | `shutil.rmtree(final)` of the fixture's attempt is now stage-replaced (it is a CREATED stage). The state is built with `final=False`, the final plan is written at attestation + 1 h (as s1_state does), and `st_["now"]` = max(lag, plan) + 2 h, so the tests' ACK at now - 1 h respects OQ-22. The SCORE-ACK deletion is dropped: final=False posts none. Failing before it: i4 acquire and i4 rechecks[aborted]. The other two rechecks cases kept their refusal, and their oracle is unchanged |

## not changed (they were expected to need migration but still pass)
- test_s1_connected (final acquisition): the ACK at `acq_at - 1 h` is already after the lag (the 3rd session's close
  is before 07:00 New York of sessions[N_DAYS+3]). The token was already `s1_ack` (A3 Task 5), so the brief's
  second Step-6 bullet needs no change.
- test_s1_run `drop_final_and_attestation` / `rmtree(final)` users and test_s1_t12_a3_a8 bundle-before-request:
  each is refused (gate bundle, ACK F6.1 or stage-replaced) on the same oracle regexes as before. Removing the
  CREATED final makes the trial stage-replaced at the next gate, and these tests match that refusal or one the
  gate checks first (bundle).

## fixture (conftest) - no pre-existing outcome changed by it alone
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

## Fix round 1 (review I-1, I-2, M-1, M-3, M-4)
- t12_fix1_full.txt: **1774 passed, 1 skipped** = 1769 + 5 new tests:
  - test_s1_a3_final: the local-OSError test x2 and the M-1 provenance-before-write test;
  - test_s1_a3_audit: the local-OSError test x2.
- No pre-existing test changed outcome.
- Oracles tightened, still passing, so no outcome change:
  - M-3: test_s1_collect `test_final_lag_refused_before_reserving` is pinned to "ack is in the future", and
    ACK_REFUSAL["before-attest"] to the F6.1 text;
  - M-4: the provider-anomaly test now also asserts the ABORTED.json content, no prepared.json, no s1_out/final, and
    no dummy key in any file.
