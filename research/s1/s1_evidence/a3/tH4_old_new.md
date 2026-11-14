# A3 H4: old -> new classification (Erratum 2 r4 G3 / M4; Clarification 1 r2 C5; row 439 tooling)

Base: HEAD 9af5406 (H3). Product files changed: `s1_slot.py`, `s1_seal.py`, `s1_run.py`. Nothing else in product
code changes. Every change is classified below as one of:
- **interface**: a new keyword or name, with the default behaviour unchanged;
- **performance**: same result, less work;
- **O9**: the prospective semantic strengthening of G3.1;
- **G3.4**: a listing error refuses;
- **C5**: the disclosed exception to G3.3/M4-A9 baseline equivalence. It is not part of row 438's equivalence control
  and has its own RED, in `h4_c5_red.txt`.

## Product

| # | where (H4 tree) | old | new | class |
|---|---|---|---|---|
| 1 | s1_seal `_close`, `close_of`, `schedule` | the pin verified inside every call (`c.sim()`) | keyword `sim=None`: None still verifies (unchanged); a caller's pass passes the module it verified | interface |
| 2 | s1_slot `EvidencePass`, `new_pass`, `_pass_of`, `_index`, `_mine`, `_close_on`, `_sched_on` | none | one evidence pass: rows + index, the calendar read, the bundle check, the module verified once, the per-row schedules and closes, and the trees hashed once. Never stored beyond the pass (I-7) | interface / performance |
| 3 | `day_for`, `first_qualified`, `_schedule`, `slot_problems`, `close_problems`, `evidence_problems`, `seal_bytes`, `_resolution_evidence` | n/a | keyword `ps=None`. Without it, every call computes exactly as before, apart from rows 10-14 (C5), which apply with or without a pass | interface |
| 4 | `evidence_problems(ps)` | about 9,800 pin verifications per gate; an O(J) row scan per slot; each QUALIFIED tree hashed twice (slot_problems, then the OQ-14 recomputation) | one `c.sim()` per pass; the subject index; each tree hashed once per pass and shared by slot_problems, _resolution_evidence and seal_bytes (the projection hash comes from the pass manifest when the candidate's dir is the hashed member) | performance (texts and order unchanged; row 438) |
| 5 | `evidence_check` | one calendar read reused by both passes; the second pass re-read only the rows | each pass is `new_pass(gv)`: a fresh calendar, rows, index, bundle check, pin and tree hashes. A calendar that is unreadable in the confirming pass refuses (it used to be reused) | **O9** (row 435[between-passes]) |
| 6 | `new_pass` bundle check | the bundle was verified once, by the gate, before the hooks | a mismatch inside a pass refuses with no row; the next gate commits INVALID (bundle) | O9 / ruling OP-14 |
| 7 | `confirmed_close_problems` | the second scan re-read the rows only | a new pass: fresh rows and index, the pin verified again, the trees re-hashed, a bundle check, and the registered calendar re-read (`_calendar`; unreadable or different from the command's calendar refuses with no row) | **O9** (G3.1 names confirmed_close_problems) |
| 8 | `_file_subjects`, `_stray_files`, the `evidence_check` has-files probe, the seals listing, the `_present` existence probe | a raw OSError escaped the gate | a Refusal "listing error never means empty or absent" | **G3.4** (row 433[scandir] was RED on the stub) |
| 9 | `_qualified_manifest` | `qualified_tree` -> `tree_manifest` -> `c.sha256_file` | the same members, order and hashes, each read through `_member_sha` (one direct `c.sha256_file`, classified) | performance + C5 |
| 10 | QUALIFIED member reads (`_read_member` / `_member_sha` / `_classify`) in `slot_problems` (QUALIFIED), `_resolution_evidence`, `seal_bytes`, and the OQ-14 seal read | an OSError became the F3 problem / QualifiedEvidence / "not the seal", and so INVALID (registration-artifact) once confirmed | a direct FileNotFoundError stays the typed absence (unchanged text; confirmed only by a second direct FNF). Any other OSError is **QualifiedUnreadable** (SystemExit): a refusal, no row, no INVALID. FNF with s1_out gone is unreadable (F6.6 LOST belongs to the next gate) | **C5** |
| 11 | `evidence_check`, `confirmed_close_problems` | (as row 10) | unreadable observations are recorded per pass. Confirmed problems still commit INVALID (an unrelated violation keeps its precedence); otherwise any unreadable member refuses. The gate refuses with an `s1_trial.Refusal` | **C5** |
| 12 | `s1_seal.stop_problems` | `except (..., SystemExit)` turned the evidence error into a problem ("persisted stop unverifiable") | `QualifiedUnreadable` is re-raised (a refusal) | **C5** (C5.2, all consumers; H4 D-9) |
| 13 | `s1_run._score_attempt` | `except (Exception, SystemExit)` turned it into score-aborted (ABORTED-INVALID) | `QualifiedUnreadable` is re-raised, like an OSError (a local fault: a refusal, no PREPARED) | **C5** (H4 D-9) |
| 14 | `sampled_seals`, `stop_record`, `decide_stop`, `run_seal_stage`, `_opening_stage`, `finalize_opening`, `run_opening_checkpoint` | QualifiedEvidence -> refusal or INVALID | unchanged code. They inherit `QualifiedUnreadable` (a SystemExit) as a refusal; decide_stop was already a refusal (NOP-4) | C5 (inherited) |

Out of scope, and unchanged:
- `Worker.complete`'s own tree hash (`qualified_tree`, C5.2);
- `s1_trial.evidence_manifest` (`qualified_tree`: a generic OSError already refuses there, `_manifest_sha`);
- `nvs`, `stop_record` and `sampled_seals` keep one pin verification per schedule call (see the report's D-2 analysis).

## Tests (existing)

| test | old | new | class |
|---|---|---|---|
| test_s1_a3_finalizer.py::test_a_worker_starting_during_the_seal_stage_recheck_is_not_a_violation[legitimate-start, stray-claim-control], ::test_a_worker_starting_during_the_opening_recheck_is_not_a_violation[legitimate-start, stray-claim-control] | the spy `window(out_, rows_, day_, cal_)` | the spy forwards `**kw` (the new `ps=` keyword). Oracle unchanged | interface (spy signature) |

| test_s1_a3_m4_workload_verdict.py::test_b_conditional_labels (fix round 1) | `b_conditional(runs, 15.0)` -> B-CONDITIONAL READY | the READY case states `workloads_resolved=True, injected_resolved=True` (M-5: both default to unresolved). Oracle unchanged for that case | interface (fail-closed defaults) |

(Review N-3: the original note here promised a complete old -> new list "appended below". No such list exists. The
full-suite summary below and the two rows above are the whole old -> new record.)

## Tests (new)

- `test_s1_a3_m4_pass.py`:
  - rows 430-438: 16 instances;
  - rows 496-497: 16 instances;
  - 2 supplementary tests (H4 D-9).
- `test_s1_a3_m4_workload_verdict.py`: 8 tests, the RM-1 arithmetic for row 439's verdict rule (tooling).

## Full-suite result (tH4_full.txt)

**5385 passed, 0 skipped**, in 1:24:42. H3's baseline was 5343 passed in 1:35:30, so the suite ran 10:48 faster.
- **+42 new instances:**
  - test_s1_a3_m4_pass.py: 32 map instances plus 2 supplementary;
  - test_s1_a3_m4_workload_verdict.py: 8.
- **No existing test changed outcome.** The only edit to an existing test is the finalizer spy signature (4
  instances, interface only, oracle unchanged).
- **No existing test changed outcome under C5.** Nothing in the existing suite expected INVALID from a generic OSError
  on a QUALIFIED member: every existing test passes unmodified, apart from the spy above. The tests themselves were
  not individually audited for this.
- **The matrix.** Its default run is inside the suite (green). The `S1_MATRIX_FULL=1 -k after-audit` subset gives 3066
  passed (tH4_matrix_after_audit.txt), identical to Task 14b's count. No C5 case appears there.

## Fix round 1 (review I-1, M-1, M-2, M-5, M-6; nits N-1, N-3, N-4)

Product:

| # | where | old (H4 r0) | new (fix round 1) | class |
|---|---|---|---|---|
| 15 | `s1_slot.evidence_check` | raised the C5 refusal (`_refuse_unreadable`) inside the hook, before `stop_gap_recover` and E5.5 `opening_manifest_check` ran | returns the gate's unreadable observations as a list (`[]` when none). Confirmed problems still commit INVALID first | **C5.1 precedence** (I-1) |
| 16 | `s1_trial.gate` | `evidence_check(gv)`, `stop_gap_recover(gv)`, `opening_manifest_check(gv)` | holds the returned list and any `QualifiedUnreadable` from `stop_gap_recover` as local values; runs `opening_manifest_check`; then `s1_slot.refuse_unreadable(list)` (the old text), then the held exception. Nothing is stored on the Gate | **C5.1 precedence** (I-1) |
| 17 | `s1_slot.slot_problems` | `_present` (existence probe) ran for every slot; for a QUALIFIED slot its OSError was a Refusal that masked a confirmed violation elsewhere | the probe runs only for the branches that use it (no row, in flight, MISSED) | **C5.1 precedence** (M-1) |
| 18 | `s1_checkpoint._opening_stage` | one `_resolution_evidence` QualifiedEvidence -> the callers' TRIAL-INVALID | confirmed on a second read: seen again -> QualifiedEvidence (unchanged INVALID path); healthy on the re-read -> `{"refused": ...}`, no row | **I-1 confirm-on-re-read** (M-6) |
| 19 | `s1_slot._sched_on` | memo keyed by `id(day)` | keyed by `c.canonical(day)` (the row's content) | nit N-1 (no behaviour change) |
| 20 | `s1_slot._unreadable` | the QualifiedUnreadable text named the absolute path | the path relative to s1_out (absolute when not under it) | nit N-4 (text only) |
| 21 | `m4_workload/verdict_rule.b_conditional` (tooling) | no workload or injected-case input: READY possible with open bounds | keyword `workloads_resolved` and `injected_resolved`, both default False. The label is never READY while either is unresolved | M-5 |

N-2 (one line, as asked): `confirmed_close_problems`' first pass uses the caller's rows and calendar and has no bundle
check of its own. Only the confirming pass is new (fresh rows, calendar re-read, bundle check, pin re-verified), as the
brief requires.

Tests (new, fix round 1):
- `test_s1_a3_m4_pass.py`:
  - row 496 gains `[unrelated-mandatory-invalid-precedence-e55]`;
  - `test_fix1_gate_unreadable_refusal_after_e55`;
  - `test_fix1_stop_gap_unreadable_never_masks_e55[e55-mismatch, e55-healthy]`;
  - `test_fix1_qualified_probe_error_never_masks[confirmed-violation, no-other-damage]`;
  - `test_fix1_confirming_pass_unreadable_refuses[permission, readable]` (kills mutant R3);
  - `test_fix1_opening_stage_confirms_on_reread[missing-once, changed-once, missing-twice]`.

  That is 11 instances.
- `test_s1_a3_m4_workload_verdict.py`: `test_b_conditional_requires_resolved_workloads_and_injected_cases` (1).

Existing tests: only `test_b_conditional_labels` changed (row above). No other existing test was edited.

Full suite, fix round 1 (`tH4_fix1_full.txt`, one clean run, no edit under research/s1 during it): **5397 passed,
0 skipped** in 1:22:02. That is 5385 + 12 new instances (11 in m4_pass, 1 in the verdict tests). No existing test
changed outcome; the one existing edit is `test_b_conditional_labels` (above).

## Fix round 2 (re-review F-1; controller ruling: a refusal path does no work - no row, no file publication)

| # | where | old (fix round 1) | new (fix round 2) | class |
|---|---|---|---|---|
| 22 | `s1_seal.stop_gap_recover`, `s1_trial.gate` | with a C5 refusal pending, the F2.3 recovery could still publish a missing stop.json (`persist_stop`) before the gate refused | keyword `publish=True`. The gate passes `publish=not unreadable`: with a refusal pending, the recompute and the stop-conflict INVALID still run (precedence kept), but stop.json is not written. Default callers are unchanged | **refusal = no work** (F-1) |

Tests:
- New: `test_s1_a3_m4_pass.py::test_fix2_stop_gap_publication_never_on_a_refusal_path[pending-refusal-no-publish,
  pending-refusal-conflict-invalid-wins, no-refusal-publishes]` (3).
- Changed: the fix-round-1 stub in `test_fix1_stop_gap_unreadable_never_masks_e55` takes `**kw` (the gate passes
  `publish=`). Interface only; oracle unchanged.

Full suite, fix round 2 (`tH4_fix2_full.txt`, one clean run, no edit under research/s1 during it): **5400 passed,
0 skipped** in 1:20:37. That is 5397 + 3.
