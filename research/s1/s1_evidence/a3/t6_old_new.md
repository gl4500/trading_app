# Task 6 old -> new

Base 9920867. Every edit to an existing test or fixture is listed with its class and the spec clause. Classes:
**intended** (the old expectation is replaced by the binding A3 rule; the oracle that remains is stated),
**fixture** (test set-up only, no oracle changed), **held** (the test needs a later task's interface; skipped with
the reason in its marker, not faked). No assertion was weakened without being listed here.

## Product readers (plan Step 4: `_report_seals` / `_capture_seal_problems`, OQ-11 ruling, E5.2, E2.6 r3)

| function | old line(s): what it read | new: what it reads |
|---|---|---|
| `s1_common._report_seals(out)` | every `captures/*/*.report.json` with `seal.written` true, and every report / `*.attempt.json` with `after_seal.sha256` (fix round 5, R-3); the seal path from the report's `close` | `_report_seals(out, rows=None, cal=None, *, mailbox=None)`: `s1_slot.required_seals(out, rows)` - exactly the CREATED `seal/<close>` stages with their committed member hash (prepared.json verified against the PREPARED detail). Tuple = (member relpath, seal path, sha256). `rows=None`: the open trial's rows read mode=ro (`_open_trial_rows`, [] when none). No report, claim or after.json is opened. `cal` unused (plan signature) |
| `s1_common.registration_problems` (`for rp, sp, h in _report_seals(out)`) | reports recording a seal: "seals/X missing or changed (recorded by capture report ...)" | the CREATED seal stages: "<member> missing or changed (a CREATED seal stage's committed member, E2.6)" (mailbox threaded) |
| `s1_common.registration_witnesses` ("opening capture report") | a report recording a written / after-seal opening seal | removed: a report is final before J and records no seal (OQ-11); the opening seal, resolution and capture witnesses remain (see the held fix3 C-2 test) |
| `s1_run._capture_seal_problems(out)` | every report with `seal.written` true must name an existing seal with that sha256 | `_capture_seal_problems(out, rows=None, cal=None)`: every member of `_report_seals(out, rows, cal)` (the CREATED seal stages) must exist with its committed sha256; never opens a report or after.json |
| `s1_checkpoint._before_opening_seal` | `c._report_seals(out)` (report / after-seal hashes) | `c._report_seals(out, rows)` - the journal's required seals (no opening entry until Task 10) |

## Other product interface changes

- `s1_journal.REASONS` gains `established-violation` (OQ-31). Old -> new for the Task 1 tests: none (no test pins
  REASONS).
- `BUNDLE_CODE` gains `s1_slot.py` (A3.1).
- `s1_checkpoint`: `_publish`, `_late_path`, `_overrun_path`, `_record_overrun` (B1.3 worker-side records),
  `_claim_slot` (claim -> `Worker.intent`), `_after_opening_seal` (R-3 -> opening gate), `_trial_stop`/`_stop_hash`
  and `_write_report`/`_report_path` (report -> `Worker.complete`) are removed; `finalize_close` gains
  `qualified=None, rows=None`; `_finalize_others` gains `rows=None`.
- `s1_stage.evaluate(gv, *, defer_pending=False)`, `s1_stage.Pending(SystemExit)`; `s1_trial.gate(...,
  defer_pending=False)`, `Gate.deferred` (ruling N2).

## Test and fixture edits

| file :: test | old | new | class / clause |
|---|---|---|---|
| test_s1_t12_a3_a8.py `BUNDLE` | tuple without s1_slot.py | `"s1_slot.py"` added | intended (A3.1: s1_slot.py joins BUNDLE_CODE) |
| conftest.py `s1_jappend` | slot E = D = at + 3650 d | keyword `due=False`; `due=True` makes E = D = at | fixture (a synthetic SLOT-TIMEOUT needs now >= D; brief Deviation 1) |
| conftest.py `s1_prereg_ack` (new) | - | posts the trial's PREREG-ACK 1 min after prereg.json's recorded time | fixture (F7.4: a post-START capture needs the PREREG-ACK) |
| test_s1_bridge_8b, t12_a1, t12_a1b, t12_a2, t12_a3_a8, t12_a5_a6, t12_a9, t12_fix1, t12_fix2_b2, t12_fix2_b3 (x2), t12_fix2_mutants, t12_fix3 (x4), t12_fix5 (x2), t12_mutant_followups (x2), task11 (x3): every `with _Clock(...): r.do_prereg(tmp_path, "run-ack", ...)` helper | no PREREG-ACK | `s1_prereg_ack(tmp_path)` after it | fixture (F7.4) |
| test_s1_a3_gate.py :: test_identity_refusals_have_zero_callbacks | `"SLOT-INTENT" not in raw_kinds` | `raw_kinds == before` (the kinds read after the damage, before the command) | fixture (the fixture's opening slot now has SLOT-INTENT/QUALIFIED rows); stronger (no new row of any kind) |
| test_s1_t12_a3_a8 :: test_a8_checkpoint_verifies_...[ack_deleted, ack_after_start] | RUN-ACK deleted / re-dated | the same, and the PREREG-ACK (which chains to that RUN-ACK) removed | fixture (the PREREG-ACK added by the migration cannot outlive its predecessor; the RUN-ACK refusal is unchanged) |
| test_s1_checkpoint :: run() | fixed clock | `intent_delay`: the clock until the claim exists | fixture (F0.5 step 6) |
| test_s1_checkpoint :: test_counts_only_report_and_seal | key set | + `journal` | intended (the returned dict carries the J outcome, OQ-11) |
| test_s1_checkpoint :: test_abort_survives_receipt_revert, test_abort_after_fence_violation_survives_clean_and_failed_runs, test_backdated_row_later_deleted_stays_aborted; test_s1_t12_a9 :: ..._survives_restoration; test_s1_t12_fix1 :: test_fix1_i1_merge_conflict...; test_s1_t12_fix2_b2 :: test_b2_a_then_gap_then_b... | a run after the abort captures and reports ABORTED-INVALID | the run after the abort is refused `trial INVALID (reason/established-violation)`; the first abort record is unchanged, no seal | intended (OQ-31: the violation commits TRIAL-INVALID first; F0.6/F1: INVALID -> no work) |
| test_s1_checkpoint :: test_receipt_mismatch_capture_does_not_seal_and_seal_carries_receipt | mismatch first, unlink aborted.json, positive half | positive half first (seal carries the receipt), then the mismatching slot: seal bytes unchanged, `seal.written` False, abort written | intended (F1: INVALID is irreversible, deleting aborted.json never resumes) |
| test_s1_checkpoint :: test_rerun_of_captured_slot_is_recorded_and_refused; test_s1_checkpoint_7b :: test_opening_inconsistent_capture...; test_s1_t12_fix2_mutants :: test_mt_a_duplicate_slot_execution... | "slot already captured" + reruns.jsonl | "a restart never re-intents" + the slot's journal rows (or all rows) unchanged | intended (F3: the journal pre-check under the slot lock; reruns.jsonl is no longer written) |
| test_s1_checkpoint :: test_late_capture_flagged, test_cr_capture_exactly_at_the_slack...; test_s1_checkpoint_7b :: test_opening_late_capture_does_not_seal | invocation at s + 11 min / at E | the INTENT before E (`intent_delay`), the capture at the same late instant | intended (F0.5 step 6); the late / on-time oracle unchanged |
| test_s1_checkpoint_7b :: test_opening_mode_refuses_a_second_run... | "opening seal exists" | "the opening is already decided" + no row | intended (F1 opening gate, E5.6) |
| test_s1_checkpoint_7b :: test_receipt_stored_concurrently..., test_cr_concurrent_receipt_conflict... | "(concurrent)" refusal in the report | report: `seal.written` False, consistent True; "(concurrent)" and `receipt_match` False in `<slot>.after.json` | intended (OQ-11/E5.2: the report is final before J) |
| test_s1_connected :: lifecycle (UNSEALED_DAY) | 3 h late invocation: refused report | `SystemExit("now >= E")`, no captures dir, no seal | intended (F0.5 step 6) |
| test_s1_connected :: lifecycle (post-stop, buy/receipt) | post_stop capture, receipt reported only | LOST-RACE, no capture, no abort, no seal | intended (F1, OQ-25; brief Step 6 "A2.2 -> F1") |
| test_s1_task11 :: test_c1_post_stop_checkpoint..[buy, receipt], test_c1_post_stop_fence_difference_is_reported_only | post_stop capture | LOST-RACE, no capture, no abort, no seal; the score unchanged | intended (F1, OQ-25) |
| test_s1_task11 :: test_c1_checkpoint_after_an_abort... | post_stop capture, ABORTED-INVALID | refused "aborted.json exists ... no new capture": no capture, no seal | intended (F8.1; Deviation 8) |
| test_s1_t12_fix2_b3 :: test_b3_a_corrupt_aborted_json_fails_closed | report written, ABORTED-INVALID | refused before the INTENT (a corrupt aborted.json is an abort), no capture, no seal | intended (F8.1, B3.4 fail-closed kept) |
| test_s1_task11 :: test_m2_capture_report_naming_a_seal...[missing, different] | a forged / edited report recording a seal -> "seal missing" | a CREATED seal stage `seal/2026-10-26` (synthetic rows + staging, `_created_seal_stage`) whose member is then deleted / changed: the gate commits INVALID (stage-replaced), the score's record lists "seal missing" | intended (OQ-11, E2.6 r3: required seals are the CREATED seal stages; the forged-report variant is the F3 evidence table, Task 7) |
| test_s1_t12_a2 :: test_a2_post_stop_checkpoints_follow_the_persisted_stop | `post_stop` flag | `journal.outcome == "APPEND"`, `seal.written` False, the persisted stop followed | intended (no post_stop flag: the post-STOP state is the journal's, F1; no TRIAL-STOP row exists here until Task 11) |
| test_s1_t12_a5_a6 :: test_a5_the_clock_is_checked...[at1, at2], test_a5_codex_probe_b..., test_a5_a_delayed_invocation... | refused report at t > E | refused "now >= E" with no row, no claim, zero snapshot calls, no seal | intended (F0.5 step 6, OQ-33) |
| test_s1_t12_a5_a6 :: test_a5_the_clock_is_checked...[at0] | refused report; rerun "slot already" | claim + refused report + SLOT-FAILED (APPEND); rerun "a restart never re-intents" | intended (OQ-33 early invocation; F3 restart) |
| test_s1_t12_fix1 :: test_fix1_i4b_a_corrupt_trial_seal... | the registration gate (the seal bound by its report) aborts | the next capture's seal read: TRIAL-INVALID (established-violation, seal-record) first, abort "bad seal record", observation subtype seal-record, no seal | intended (OQ-11: no report binds a seal; OQ-31) |
| test_s1_t12_fix1 :: test_fix1_m4_a_changed_persisted_stop... | `z.stop_problems` (reports' stop_sha256) | `c.registration_problems` (the stop's registry records) | intended (OQ-11: a report no longer records stop_sha256; Task 11: TRIAL-STOP detail) |
| test_s1_t12_fix2_b1 :: helpers | - | `kinds`, `timeout_row` (the finalizer's SLOT-TIMEOUT via j.append + product context) | fixture |
| test_s1_t12_fix2_b1 :: test_b1_a_claim_without_a_report... | RESOLUTION-TIMEOUT file at D45 | no file; slot = [SLOT-INTENT]; after D45 slot 47 seals | intended (B1.3 -> F3, E1.4: the finalizer never touches a worker's files; its TIMEOUT row is Task 7) |
| test_s1_t12_fix2_b1 :: test_b1_a_success_published...[0, +1 min] | RESOLUTION-TIMEOUT + .late.json | SLOT-QUALIFIED REFUSE (late R), slot = [SLOT-INTENT], the worker's evidence in place, no .late.json, later slot 47 seals | intended (F0.5 step 6, F3) |
| test_s1_t12_fix2_b1 :: test_b1_expiration_racing...[3] | one resolution file (worker vs finalize_close) | one terminal ROW (worker's QUALIFIED vs the finalizer's SLOT-TIMEOUT through the journal; barrier variant on j.append), the loser LOST-RACE, no INVALID, the seal follows, replay changes nothing | intended (E1.2/E1.3) |
| test_s1_t12_fix2_b1 :: test_b1_killed_and_merely_slow...[2] | RESOLUTION-TIMEOUT file, .late.json | both: slot = [SLOT-INTENT], D45 unchanged; slow: REFUSE (late R), no .late.json; seal 47 | intended (F3, E1.2, E1.4) |
| test_s1_t12_fix2_b1 :: test_b1_D_never_extends...[2], test_b1_the_0800_slot... | refused FAILURE resolution | "now >= E", no row, no resolution | intended (F0.5 step 6) |
| test_s1_t12_fix2_b1 :: test_b1_a_pending_resolution_cannot_cause_an_early_terminal_stop... | an 08:00 slot in flight at W | the 08:00 slot is refused at s = E (it can never be in flight); the stop decided at 08:10 equals the one at 08:25 (decided once, never rescued) | intended (F0.5 step 6 with A5.3 E = W = s; see report finding) |
| test_s1_t12_fix2_mutants :: test_mt_a_forged_success_without_complete_evidence... | abort "bad resolution record" and no seal | **split (fix round 1, review I2)**: this test keeps only the never-seals half - the forged SUCCESS of a no-row slot is never selected; slot 47 (QUALIFIED) is the seal | intended for the never-seals half (F3: only QUALIFIED is selectable) |
| test_s1_t12_fix2_mutants :: test_mt_a_forged_success_of_a_no_row_slot_is_invalid (new, skipped) | (the abort half) | the forged no-row resolution is INVALID registration-artifact with zero callbacks | **held** (Task 7: the F3 evidence table, s1_slot.slot_problems) - not intended |
| test_s1_t12_fix2_mutants :: test_mt_a_later_close_resolves_an_earlier_close... | RESOLUTION-TIMEOUT file | no file; the earlier close seals from slot 47 | intended (E1.4) |
| test_s1_t12_fix2_mutants :: test_mt_an_unbound_corrupt_seal... | report written + abort | TRIAL-INVALID (established-violation, seal-record) + observation + abort; no P | intended (OQ-31: external first; no terminal slot event required) |
| test_s1_t12_fix2_mutants :: test_mt_a_deleted_stop_and_its_registry_record... | reports' stop hash witnesses the stop | **held** (Task 11: TRIAL-STOP is the stop's authority; the report no longer records the stop hash) | held |
| test_s1_t12_fix3 :: `_success_without_seal` (I-1 x4) | the 08:00 slot in the crash window | the 07:00 slot (the last capturable one); every stop decision still after W | intended (F0.5 step 6: the 08:00 slot can never be opened) |
| test_s1_t12_fix3 :: test_m1_a_publication_whose_link_lands_at_or_after_D... | SUCCESS seals, .overrun.json | R >= D: REFUSE, no seal, no .overrun.json | intended (B1.3 M-1 -> F3: R is read after P; probes 172-174) |
| test_s1_t12_fix3 :: test_c2_retro_the_opening_report_and_resolution_witness... | the opening report witnesses the registration | **held** (Task 10: the opening seal as the `opening` stage) | held |
| test_s1_t12_fix5 :: test_r1_probe_an_opening_whose_first_slot_never_ran... | MISSED file for 20:45 | no file, no claim for 20:45; the next slot seals from 20:55 | intended (E1.4; the SLOT-MISSED row is Task 7) |
| test_s1_t12_fix5 :: test_r3_an_opening_slot_after_the_seal... | claim + resolution + after-seal report | "the opening is already decided": zero callbacks, no claim, no capture, no resolution, no report, no row; seal and receipt unchanged | intended (plan Step 6 "R-3 -> opening gate", F1, E5.6) |
| test_s1_t12_fix5 :: test_r3_deleting_the_seal..., test_r3_the_after_seal_claim_alone..., test_r3_the_selection_never_writes... | after-seal records bind the seal | **held** (Task 7: the F3 evidence table detects the deleted QUALIFIED tree / the forged no-row slot files before any callback) | held |
| test_s1_t12_mutant_followups :: test_mf_a_tampered_deferred_capture_never_seals | `refused` "differs from its recorded projection" | refused "QUALIFIED tree differs from the committed detail ... registration-artifact", no seal, abort registration artifact | intended (F3 QUALIFIED: a changed tree member is INVALIDATE; the _seal_bytes re-check is now second-line - Task 15 note) |
| test_s1_t12_reporting :: test_r6_refused_captures... | post-stop late refusal + binding gap listed | **held** (Task 11: the refused capture and the gap must be committed before the STOP) | held |
| test_s1_bridge_8b :: test_bridge_row_edited_then_scored_is_aborted_invalid | final snapshot + score run | the final snapshot refused (trial INVALID, established-violation); the score's unit-level record (`s1_score_refused`) still names the bridge abort | intended (OQ-31, F1) |
| test_s1_a3_codex_probes.py | 4 tests | + header imports (ck, j, z, sl, S1_PROCESS, s1_ack) and the 4 publication probes | new (plan Step 2) |

Held tests: 7 after fix round 1 (all `pytest.mark.skip` with the reason; t6_fix1_full.txt lists them).

## Fix round 1 (review C1, C2, I1, I2, M1-M5)

Product:
- `finalize_pending(out, cal, start, t, *, mailbox=None)` (C1): the journal-mode selection over the open trial's rows
  (`c._open_trial_rows`, fail closed): only SLOT-QUALIFIED slots are selectable; no TIMEOUT / MISSED file is written.
  `s1_run.attest_stop` passes its mailbox. The legacy file-writing branch of `finalize_close` has no product caller.
- `_journal_slot` (C2): an INTENT-only slot DEFERS until a terminal row exists, whatever t (E1.3/E1.7, E2.2, B1.4).
- `_finalize_others` (I1): re-raises `_QualifiedEvidence` (never swallowed).
- M1: `_after_terminal` and the opening path take `t` before reading the rows.
- M2: `finalize_close(qualified=)` removed (no caller).
- M4: `s1_common._open_trial_rows` fails closed (SystemExit); `registration_problems` re-raises it unless file problems
  already decide (B3.4: an outage never downgrades an established violation).

Tests:

| file :: test | old | new | class / clause |
|---|---|---|---|
| test_s1_a3_slots :: test_finalize_pending_never_seals_a_slot_without_a_qualified_row (new) | - | R = D -> REFUSE; finalize_pending: no seal, no file written under captures/ | new (C1; RED in t6_fix1_red.txt) |
| test_s1_a3_slots :: test_an_in_flight_earlier_slot_defers_the_seal_even_past_its_d (new) | - | the reviewer's 45/47 repro: slot 47 defers, slot 45 QUALIFIED, the seal is slot 45's | new (C2; RED) |
| test_s1_a3_slots :: test_a_damaged_qualified_tree_on_another_pending_close_is_invalid (new) | - | damaged slot-47 report, slot 45's finalizer TIMEOUT committed (so the walk reaches 47), next close: INVALID registration-artifact, abort, no seal | new (I1; RED for the first draft and for the revised test with the I1 fix reverted, t6_fix1_red.txt) |
| test_s1_a3_slots :: test_lost_race... `recheck == []` | unlabelled | labelled a Task 7 stub (slot_problems) | label (M3; carried to Task 7) |
| test_s1_t12_fix2_b1 :: test_b1_a_claim_without_a_report... | after D45 slot 47 seals with slot 45 INTENT-only | `timeout_row(S45, D45)` first; slot 45 = [SLOT-INTENT, SLOT-TIMEOUT]; then slot 47 seals | intended (C2: E1.3/E2.2 - the finalizer's TIMEOUT row, Task 7, comes first) |
| test_s1_t12_fix2_b1 :: test_b1_a_success_published...[0, +1 min] | S2200 seals slot 47 | `timeout_row(S45, S2200+30 s)` first | intended (C2) |
| test_s1_t12_fix2_b1 :: test_b1_killed_and_merely_slow...[2] | slot 45 INTENT-only; slow worker REFUSE (late R) | `timeout_row(S45, D45)` first (no lock, E1.2); slot 45 = [INTENT, TIMEOUT]; the slow worker's later J is LOST-RACE at 4c (E1.3) | intended (C2, E1.3) |
| test_s1_t12_fix2_mutants :: test_mt_a_later_close_resolves... | the next close seals slot 47 with 45 INTENT-only | `timeout_row(S45, D45)` first | intended (C2) |
| test_s1_checkpoint :: test_fr1_main_and_trial_state_compare_modes_and_status_by_value | `_trial_state` without a trial | `s1_common._open_trial_rows` returns [] (the unit's subject is the RUNNING comparison) | fixture (C1: finalize_pending reads the journal, fail closed) |
Regressions: none.
