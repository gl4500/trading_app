# A3 Task 10 - old -> new classification

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

## Fixture changes (F7.2(b) literal, OQ-37 ruling, E5.6)
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

## Intended changes
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

## Un-held
- test_s1_t12_fix3 c2_retro_the_opening_report_and_resolution_witness_the_registration (held since Task 6 "for Task
  10"): passes for its stated reason - the deleted opening seal is a CREATED `opening` member: `stage opening: ...
  member seals/2026-10-23.json missing or changed ... INVALID (stage-replaced)`, TRIAL-INVALID reason/stage-replaced,
  then "trial INVALID (reason/stage-replaced)".

## Fix round 1 (review I1, M1-M6, M8)
- **Fixture / test literal**: every test spy of `s1_common.publish_exclusive` (a3_codex_probes `delayed`, a3_slots
  `late`/`pub`/`pub47`/`pub45`, fix3 `slow`/`concurrent`/M-2 `rec`, fix4 `pub`/`disk_full`) forwards keyword
  arguments - publish_exclusive gained `mkdir=` (M5). Oracles unchanged.
- **M8 (wording corrected)**: the unit-level B3.3 oracles now name the expected member - fix3 c2_deleting...
  (STAGE_MEMBER[combo]), c2_probe_seals_registry..., c2_the_external_run_ack..., c2_retro_the_run_ack_alone...
  (the opening seal), c2_residual (the opening seal, added); fix2_b3 deleting_prereg_and_the_opening_together (both
  files), an_earlier_bundle_abort_stays_first (attest_start.json, added). The statement above "the same finding is
  asserted" holds for every migrated intended change after this round.
- New tests (no migration): test_s1_a3_prestart fix-round section (I1 x3, M1, M2 x3, M3 x2, M4, M5 x3).
