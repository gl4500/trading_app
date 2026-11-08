# Codex probes: old -> new (plan "Codex probe old -> new map", F10 "Codex probes"; map row 176)

Rewritten by A3 Task 14 (it was first written by Task 5 for the Task 5 row only). It has two separate sections, as
map row 176 requires: **(1) intended old behavioural failures** and **(2) fixture/setup incompatibilities**. An entry
in one section never counts toward the other.

The historical probes are frozen, byte-identical, under `codex_probes_historical/` (sha256 in its `SHA256SUMS`;
never collected: the conftest `pytest_ignore_collect` hook, proven by
`test_s1_a3_codex_probes.py::test_historical_probe_copies_are_never_collected`; frozen hashes checked by
`::test_historical_probe_copies_are_frozen`, row 171). Their result JSON files are the historical observations. All
new tests are in `research/s1/s1_tests/test_s1_a3_codex_probes.py`.

## Section 1 - intended old behavioural failures

One row per new probe test: the historical file and test, the historical JSON observation it reverses, the new
expected outcome, the spec clause, and the task that changed it. Rows marked "(new)" have no historical probe; they
are listed because they live in the probe file, with "none" as the old observation.

| new test | historical file :: test | historical observation (frozen JSON / XML) | new expected | spec clause | task |
|---|---|---|---|---|---|
| test_combined_damage_is_invalid_bundle_after_any_journal_row[missing] | test_codex_combined_damage.py :: test_bundle_change_plus_damaged_bootstrap_is_refusal_without_persistent_abort[missing] | bundle-bootstrap-missing.json: refusal "inconsistent pre-registration state ... (B3.2: nothing is registered, nothing is aborted)", `abort: null`, `restoration_resumes: true` | INVALID (bundle) + local aborted.json (reason bundle); restored files + aborted.json deleted -> still refused "trial INVALID (reason/bundle)"; spies zero | F6.4 (a bundle mismatch after any journal row is INVALIDATE + local abort), F0.6 | T5 |
| test_combined_damage_is_invalid_bundle_after_any_journal_row[unparseable] | ...[unparseable] | bundle-bootstrap-unparseable.json: the same refusal, `abort: null`, `restoration_resumes: true` | the same as [missing] | F6.4, F0.6 | T5 |
| test_publication_d_minus_1us_qualifies_when_no_timeout_committed_first | test_codex_publication.py :: test_observe_actual_publication_deadline_behavior[-1] | publication-offset--1.json: `resolution.outcome: SUCCESS`, `seal.written: true` (linked_utc = D - 1 µs) | SLOT-INTENT, SLOT-QUALIFIED (R = D - 1 µs < D); seal written. The old observation is kept (ctrl, row 172): the reversal is in the next two rows | F3 (R < D qualifies), Erratum 1 E1 | T6 |
| test_publication_at_d_and_d_plus_1us_does_not_seal[0] | test_codex_publication.py :: test_observe_actual_publication_deadline_behavior[0]; :: test_required_durable_publication_at_or_after_deadline_must_not_seal[0] (failed at c9b4322: it sealed) | publication-offset-0.json: `outcome: SUCCESS`, `publication_overrun: true`, `seal.written: true` | the late R is REFUSE with no row and no seal (`rep["journal"]["outcome"] == "REFUSE"`, slot rows == [SLOT-INTENT]); the finalizer later commits the TIMEOUT at D | F3 (R >= D never qualifies), Erratum 1 E1.2/E1.3 | T6 |
| test_publication_at_d_and_d_plus_1us_does_not_seal[1] | ...[1] (both historical tests) | publication-offset-1.json: `outcome: SUCCESS`, `publication_overrun: true`, `seal.written: true` | the same as [0] | F3, Erratum 1 E1.2/E1.3 | T6 |
| test_publication_well_before_d_seals | (new) positive control | none | SLOT-INTENT, SLOT-QUALIFIED; seal written | F3 | T6 |
| test_race_t_commits_then_j_is_lost_race | (new) P/R/J/T race | none | J is LOST-RACE after a committed TIMEOUT; slot rows [SLOT-INTENT, SLOT-TIMEOUT]; no seal; no TRIAL-INVALID | F3, Erratum 1 E1, F10 CH2 | T7 |
| test_race_j_commits_then_stale_t_is_lost_race | (new) P/R/J/T race | none | a stale TIMEOUT after J is LOST-RACE; slot rows [SLOT-INTENT, SLOT-QUALIFIED] | F3, Erratum 1 E1 | T7 |
| test_race_two_finalizers_one_terminal | (new) P/R/J/T race | none | two overlapping finalizers (file barrier) commit exactly one SLOT-TIMEOUT; no TRIAL-INVALID | F3, F5.1, Erratum 1 E1 | T7 |
| test_race_p_without_j_restart_ends_in_timeout | (new) P/R/J/T race | none | a crash after P without J: the restart refuses "never re-intents"; the finalizer commits the TIMEOUT | F3, Erratum 1 E1.3 | T7 |
| test_v1_selective_deletion_is_invalid | test_codex_registration.py :: test_v1_selective_deletion_allows_different_opening_and_start_attestation | v1-selective-deletion.json: the deletion set (opening seal, both opening records, receipt, the first slot's resolution/report) left `registered: false`, `abort: null`, `attestation_and_prereg_accept_replacement: true` (a replacement seal accepted) | the re-run opening checkpoint refuses "stage opening: ... INVALID (stage-replaced)" (the CREATED opening member is missing); attest_start then refuses "trial INVALID (reason/stage-replaced)"; zero callbacks; no second opening | F4 table (CREATED member missing -> stage-replaced), F0.6 | T10 |
| test_a_fully_deleted_then_b_is_invalid_or_never_ack_eligible | (new; F10 "A fully deleted, then B") | none | after s1_out is deleted, a second plan B refuses ("open" trial); the opening checkpoint commits INVALID (LOST) with zero callbacks; the opening issuance refuses "trial INVALID (reason/LOST)" | F6.6 (total loss -> INVALID LOST), F6.3, F9 | T10 |
| test_prereg_restoration_is_invalid_once_created | test_codex_registration.py :: test_missing_prereg_and_both_records_is_only_refusal_then_restoration_resumes | prereg-restoration.json: `observed_refusal: "... no verified prereg (RUN-ACK registration)"`, `abort: null`, `restoration_resumes: true` | deleting prereg.json and its two records is "stage prereg: ... INVALID (stage-replaced)"; after restoring them (aborted.json deleted) the gate still refuses "trial INVALID (reason/stage-replaced)"; zero callbacks | F4 table (CREATED), F6.4 persistence, F0.6 | T10 |
| test_prereg_before_created_follows_the_stage_table[intent-only-free] | (the same historical probe, before CREATED) | prereg-restoration.json (as above) | a crash after the prereg INTENT with the lock free: INVALID (stage-incomplete) | F4 table (INTENT without PREPARED, lock free) | T10 |
| test_prereg_before_created_follows_the_stage_table[prepared-free] | (the same) | prereg-restoration.json (as above) | a crash after PREPARED with the lock free: the gate passes and its F4.7 recovery appends the prereg STAGE-CREATED (the recovery publishes through the same publication hook as run(), Task 10 I1) | F4.7, F4 table | T10 |

Not in this file but in the plan's map: the two f045bd31 revision-0 demonstrations (deadline lock, post-stop seal)
are reversed by `test_s1_a3_finalizer.py::test_timeout_commits_at_d_while_a_live_worker_holds_the_work_lock` and
`::test_no_seal_after_stop_even_for_a_pre_stop_qualified` (Task 7); their JSON files are not among the frozen copies.

## Section 2 - fixture/setup incompatibilities

Every incompatibility met when a new probe test was first run, or when a later task's fixture change touched the
probe file, with its fix: things that failed, or could not run, only because of setup. None of them changed an
oracle. (Fix round 1, review M-6: three review-driven test strengthenings that were listed here are not setup
incompatibilities; they moved to the separate note below.) Sources: the task reports and t5/t6/t7/t10 old->new
records; where a task recorded none, the entry says so.

| task | test(s) | incompatibility | fix |
|---|---|---|---|
| T5 | test_combined_damage_is_invalid_bundle_after_any_journal_row[*] | none recorded: the new test builds its state with the migrated `s1_state` (journal rows from the audit stage on; OPENING- and RUN-ACK through `s1_trial.token`) and calls `do_prereg` itself, as the historical probe did | - |
| T5 (fix round 1, M-1) | the probe file header | `s1_jappend` was needed by the appends planned for Task 7 (P41) | imported at the top with `# noqa: F401` |
| T6 | the 4 publication probes | the probe file lacked the imports the slot worker probes need | header imports added (ck, j, z, sl, S1_PROCESS, s1_ack) (t6_old_new.md) |
| T10 (fix round 1, M5) | test_publication_* (the `delayed` spy of `s1_common.publish_exclusive`) | `publish_exclusive` gained a `mkdir=` keyword; the spy did not forward keyword arguments | the spy forwards `**kw` (t10_old_new.md, "Fixture / test literal"); oracles unchanged |
| T14 | the whole file | none: Task 14 changed no probe test (the transitional stage-set switch it deletes was never patched in this file) | - |

## Note - review-driven test strengthenings (counted in neither section)

These changed a probe test after a review asked for a stronger test. They are not old behavioural failures (nothing
historical is reversed by them) and not setup incompatibilities (nothing failed because of setup), so they are
counted in neither section above. No oracle changed.

| task | test(s) | weakness found by the review | strengthening |
|---|---|---|---|
| T5 (fix round 1, M-7) | test_historical_probe_copies_are_frozen | the frozen folder had no provenance note | `codex_probes_historical/README.md` added; `SHA256SUMS` regenerated (14 entries, README included) |
| T7 (fix round 1, M5) | test_race_two_finalizers_one_terminal | the two child finalizers could run one after the other, so the "race" was not shown to overlap | a file barrier: both children pass their gate before either finalizer appends; the test asserts both reached it |
| T10 | test_prereg_before_created_follows_the_stage_table[*] | the crash was simulated by an exception; a test that never reached the crash point would pass vacuously | the test records the crash and asserts `crashed == [stop_after]` |

Section 1 also lists 7 rows that reverse no historical observation (the D-1 µs and well-before-D controls, the four
races and "A fully deleted, then B"); each is labelled "(new)" or "ctrl" there and counts only as a probe-file test.
