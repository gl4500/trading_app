# A3 Task 14 - old -> new (base 28fe5a0: full suite 1805 passed, 7 skipped)

Classes: **intended** (the Task 14 change the brief names: every stage enforced, Step 3), **fixture** (a test
fixture or test-literal change that changes no oracle), **new** (a new test), **oracle** (a resolution of the damage
matrix's oracle against an observation, from the spec, as the brief's Step 2 requires), **held** (fix round 1: a
case that keeps the brief's expected outcome and is xfail(strict=True) on a product defect fixed by a later task).
No requirement-map row's expected outcome changed (fix round 1 restored the brief's INVALID for the O-3 cases).
The 7 NO-VALID-SEAL holds (NVS-1, `conftest.S1_NVS_HELD`) are untouched and stay skipped; the matrix does not use
them (no matrix point is a NO-VALID-SEAL trial: the s1_state default lots stop STOPPED).

## Transitional check before the deletion (Task 8 D5 carry-forward)
`a3/t14_enforced_check.txt`: at HEAD 28fe5a0, before any Task 14 edit, `ENFORCED == frozenset(TABLE)` is True (all 8
TABLE stages) and `SEALS_ENFORCED is True`. Both names were then deleted together. After the task, a grep of
research/s1 (product and tests, evidence excluded) finds the two names only inside the absence assertions
(`not hasattr(...)`) of test_every_stage_is_enforced_by_the_gate and test_seals_enforced_is_on.

## Intended (Step 3): the transitional stage set is gone, so every test runs with every stage enforced
Old: the test narrowed `s1_stage.ENFORCED` (and/or set `SEALS_ENFORCED = True`) by monkeypatch. New: no patch; the
oracle is unchanged and the test passes on the product default (all of TABLE plus the seal files). Each of these
tests already drove one stage on a plan-only trial, where no other TABLE stage has a row or an artifact, so the
other stages' table entries decide nothing.
- test_s1_a3_stage.py: `drive()` (used by every engine test that drives a stage); test_crash_after_prepared_recovery_by_b_appends_created_without_recompute;
  test_recovery_appends_created_with_a_op_and_b_actor_under_the_lock; test_recovery_failures_are_invalid[*];
  test_recovery_publishes_only_missing_members_and_never_overwrites; test_recovery_unexpected_error_appends_nothing;
  test_stage_state_table[*]; test_pause_after_intent_with_a_live_owner_is_pending;
  test_lock_io_error_refuses_with_no_row_and_no_liveness_verdict;
  test_a_seal_file_with_no_prepared_row_is_a_registration_artifact (SEALS_ENFORCED patch; docstring);
  test_a_foreign_root_is_refused_by_the_plan_check_before_the_stage_table;
  test_no_intent_in_a_stale_snapshot_is_re_read_under_the_lock_before_invalid;
  test_no_intent_in_a_stale_snapshot_with_a_live_owner_is_pending;
  test_a_seal_completed_after_a_rowless_snapshot_is_not_an_artifact (SEALS_ENFORCED patch; docstring);
  test_recovery_never_creates_s1_out.
- a3_helpers.py `child()` (the child-process entry point of the crash / live-owner tests): no longer sets
  `sg.ENFORCED = frozenset({stage})`.
- test_s1_a3_stage.py::test_seal_files_on_disk_are_evaluated_once_the_seal_family_is_enforced: old `assert
  sg.ENFORCED == frozenset({...8 stages}) and sg.SEALS_ENFORCED is True`; new: that assertion is removed (the
  absence is asserted by the new test below); the seal-file oracle is unchanged.
- test_s1_a3_finalizer.py::test_seals_enforced_is_on (Task 8 D5 condition (b)): old `assert sg.SEALS_ENFORCED is
  True`; new `assert not hasattr(sg, "SEALS_ENFORCED") and not hasattr(sg, "ENFORCED")`.
- Comment/docstring wording only (no code): test_s1_a3_audit.py (carry-forward 4 docstring), test_s1_a3_slots.py,
  test_s1_a3_finalizer.py (module docstring, row 265 docstring), test_s1_t12_fix2_b3.py, test_s1_t12_fix3.py (one
  comment; mixed line endings preserved byte for byte), test_s1_t12_fix4.py (four comments).

## Carry-forward 2 (Task 10 I1): the legacy registry/witness records stay
Not removed. Neither the Task 14 brief nor the spec removes them: OQ-19 keeps the legacy detectors as additional
detectors (never identity or authorization roots), OQ-24 makes `registry/opening.json` and `witnesses/opening.json`
two of the nine damage-matrix elements, and the brief's oracle relies on "legacy records through OQ-19". So the
publication hooks that write them (`s1_stage.PUBLISH_HOOKS`, used by run() and by F4.7 recovery) and the legacy
`registration_gate` detector stay; only the s1_stage comment that said "until Task 14 deletes them" is corrected.
The Task 10 I1 test (test_s1_a3_prestart.py::test_a_recovered_pre_start_stage_never_invalidates_the_next_command[*])
is unchanged and green (t14_green.txt, t14_full.txt).

## Fixture addition (Step 3): `conftest.s1_state(upto=...)`
- `upto` is one of `conftest.S1_UPTO` = after-start-attest, after-prereg, after-stop, after-stop-attest,
  after-final-plan, after-final, after-score. s1_state then runs the real lifecycle (attest_start; RUN-ACK;
  do_prereg; PREREG-ACK; the seals; decide_stop; attest_stop; write_final_plan; ACQUIRE-ACK; the real `final` stage
  through the existing `_final_stage` fixture work; the final snapshot; SCORE-ACK; the real `r.score` command) and
  returns right after the named point's CREATED row (after-stop: the TRIAL-STOP row and stop.json). The ACK of the
  next stage is not posted. `info["now"]` is an instant just after the point (30 s, or 1-4 min for final/score),
  at which the gate passes. `upto` implies score_ready from after-prereg on; an unknown value is a ValueError, and a
  stop with no final plan (NO-VALID-SEAL) is a ValueError for the final points.
- `_s1_finish` gains the same `upto` keyword (it holds the post-stop chain).
- Without `upto`, s1_state and _s1_finish behave exactly as before (every existing caller; full suite).
- Deviation from the brief's wording "do_final": the after-final point runs the real `final` STAGE with the
  fixture's synthetic work (`_final_stage`, Task 12), as every other s1_state caller does; do_final itself needs a
  provider transport (tested in test_s1_a3_final.py).

## New tests
- test_s1_a3_matrix.py::test_matrix (row 255): default 55 subsets x 2 bundles x 3 damages x 10 points = 3,300
  cases; S1_MATRIX_FULL=1: 511 x 2 x 3 x 10 = 30,660 (t14_matrix_full.txt).
- test_s1_a3_matrix.py::test_matrix_scope_is_the_declared_scope (row 283, static).
- test_s1_a3_residual.py::test_uncommitted_detection_may_resume_and_is_labelled_lost_detection (rows 161/223, ctrl)
  and ::test_invalid_committed_before_the_crash_keeps_restoration_invalid (rows 162/224) (t14_residual.txt).
- test_s1_a3_stage.py::test_every_stage_is_enforced_by_the_gate (Step 3; also asserts the seal switch is gone).

## Test-literal deviations from the brief's code (R-G; no row outcome changed)
1. **match= on every pytest.raises** (inherited rule). The matrix uses `MATRIX_STOP = r"refused|INVALID"`; the
   residual tests pin the exact texts (the F8.1 residual refusal; "stage start_attest: ... INVALID (stage-replaced)";
   "trial INVALID (reason/stage-replaced): no work").
2. **The stop must be the damage's** (new assertion). In the brief's code, any SystemExit from run_checkpoint
   passed a non-ok case, including the checkpoint's own later refusals for an unrelated reason ("no verified
   prereg", "no S1-PREREG-ACK", "already has a journal row: a restart never re-intents"). The first oracle check
   showed those refusals passing 'invalid' and 'refuse-or-invalid' cases vacuously (O-1/O-2 below). Each non-ok
   case now asserts that the SystemExit was raised by `s1_trial.gate`, or by the checkpoint's registration check
   (`s1_gates.verified_registration`, the A3.2/B3.3 legacy detectors, before any callback) with a legacy-detector
   text. Spies record both.
3. **The residual tests assert the journal state**: the outage case asserts no TRIAL-INVALID row was committed; the
   committed case asserts exactly one reason/stage-replaced row before the restoration.
4. **The module-scoped snapshot fixture applies the per-test guards itself** (ruling B4/C14): a module fixture is set
   up before the first test's function-scoped autouse guards, so it sets its own tmp mailbox, its own tmp receipt
   HMAC key and the network guard through `pytest.MonkeyPatch.context()` (all restored after the build). The brief
   set only the mailbox.
5. `import re` added; unused brief imports kept with `# noqa: F401`.

## Oracle (Step 2: the singleton check at every point, then the default selection)
The singleton run (all 10 points x 9 elements x 2 x 3) first gave 20 disagreements under the brief's code, and
the default selection 16 more after the O-1/O-2 resolutions. Each is resolved below; the oracle docstring carries
the same rules. The observed refusal texts came from a scratch logging plugin (scratchpad only, not evidence).
- **O-1 (oracle; OQ-24, OQ-19, E5.5).** Element "opening record (registry)" / "(witnesses)", damage "changed" (one
  trailing space), at every point from after-opening on. Old oracle: INVALID. Observed: the gate passes (the
  checkpoint then refused for its own reason). Spec: the two records are bound by no journal row and are no member
  of the E5.5 evidence manifest (they are "not journal substitutes", OQ-24); the OQ-19 detector reads them as
  parsed records, and a trailing space leaves the parsed record identical. So that damage changes no committed
  evidence and no recorded content: it is no damage. New: such an element is not counted as damaged ('ok' unless
  another element decides). "deleted" and "unparseable" of the same records stay INVALID (observed INVALID).
  Limit (fix round 1, review M-4; disclosed to Codex at Stage-1, no change): the matrix's "changed" is therefore
  vacuous for these two elements, and its 'ok' cases exercise only the trial gate. A SEMANTIC edit of a record (an
  `artifacts` hash changed) passes the trial gate and is caught only by the command's legacy check
  (`s1_gates.verified_registration` -> TRIAL-INVALID registration-artifact); that path is covered by the legacy tests
  test_s1_t12_fix8.py::test_h_every_subset_of_the_editable_registration_files_tampered_is_the_persistent_abort
  (its "edit" mode zeroes `artifacts["plan.json"]` in the opening records) and the test_s1_t12_fix3.py c2 tests.
- **O-2 (oracle; OQ-19 keeping A2 B3.1).** The same two records fabricated before the opening (after-audit,
  "changed" = `{} ` or "unparseable" = `{not JSON`). Old oracle: 'refuse-or-invalid'. Observed: the gate passes.
  A registry/witness record before the opening seal is the legacy "opening in progress" witness, which the legacy
  detector accepts by design (a crash between the record and the seal), and no F-rule judges it (it is no stage
  artifact, F4). New: a fabricated legacy record adds nothing ('ok' unless another element decides).
  Correction (fix round 1, review M-1; disclosed to Codex at Stage-1, no change): "adds nothing" holds at the trial
  gate only. Downstream, the real opening checkpoint with such a record commits the opening STAGE-INTENT and
  STAGE-PREPARED and refuses "registry/opening.json already records different artifacts: refusing"; every later
  gate refuses the same way with no row (F4.7 recovery re-runs the same before_publish) until the file is deleted,
  after which recovery completes. Fail-closed, availability only (no integrity loss); no matrix point reaches it.
  Codex question: is a pre-existing legacy record at the opening's publication an indefinite refusal (current) or
  INVALID (registration-artifact, as a stray file after the AUDIT-ACK under the Task 7 concern-2 ruling)?
- **O-3 (held since fix round 1; was "disputed").** After the audit and before the opening, damage to plan.json. The
  oracle's spec reading is INVALID (F4 table: the CREATED audit stage's bound input plan.json missing or changed ->
  INVALID stage-replaced; also the gate's own comment "OQ-19: after any row a lost/changed plan is a detected
  registration-artifact violation, never only a refusal"). The code runs the OQ-19 legacy detector first (Task 7
  deviation D10, for a plan that does not name the trial or is not the AUDIT-ACK's), and before the opening that
  detector finds no registration. Observed:
  - plan.json alone deleted or unparseable: "checkpoint refused: plan.json trial_id None differs from the
    AUDIT-ACK's <id> (F6.2)" with NO TRIAL-INVALID row, so restoring plan.json resumes the trial;
  - plan.json damaged together with a fabricated attest_start.json / prereg.json / stop.json: the A2 B3.2 refusal
    "inconsistent pre-registration state [...]" with no row (also when plan.json is only "changed", where the F4
    table alone would INVALIDate, and although the Task 7 concern-2 ruling says A3 supersedes A2 B3.2 after the
    AUDIT-ACK);
  - plan.json unparseable together with an unparseable fabricated seal / receipt / registry / witness record: the
    legacy detector's persistent abort with TRIAL-INVALID.
  Round 0 pinned these cases to the observed outcome (`disputed()`); the review (I-2) rejected that as an oracle
  change with no spec reason. Fix round 1: the brief's INVALID is restored and the failing cases are **held**
  (strict xfail), see "Fix round 1" below. The product fix is Task 14b (progress.md ruling "T14 I-1": an ordering
  defect under the existing spec). Every case still stops all work with zero callbacks. From after-opening on, the
  same damage is INVALID only through the legacy detector (review I-1: with the legacy detector disabled, 330 plan
  deleted/unparseable cases from after-opening on end with no TRIAL-INVALID).

## Full suite (t14_full.txt) vs base
**5109 passed, 7 skipped in 4213.46s (1:10:13)** (t14_full.txt) = base 1805 passed + 3,304 new (3,300 default
matrix cases + the scope test + 2 residual tests + test_every_stage_is_enforced_by_the_gate); the 7 skips are exactly
the NVS-1 holds (S1_NVS_HELD), unchanged. No pre-existing test changed outcome: every pre-existing test touched by
Task 14 is listed above (intended or wording only), and no other test needed a change. The exhaustive matrix
(t14_matrix_full.txt): 30661 passed in 5261.35s (1:27:41).

## Fix round 1 (task-14-review-verdict.md; progress.md rulings "T14 I-1", "T14 I-2")

- **Held (I-2): O-3 cases are strict xfail with the brief's oracle.** `disputed()` is gone; the oracle is the
  brief's (plus O-1/O-2). `o3_held(point, subset, bundle, damage)` only selects the cases marked
  `pytest.mark.xfail(strict=True, reason="O-3: damaged plan.json after rows refuses instead of INVALID; fixed by Task
  14b")`; the 'refuse' expectation (which asserted the defect: no TRIAL-INVALID) is deleted. Task 14b's fix makes
  them XPASS, strict fails, and Task 14b removes the marker.
- **The held set is the MEASURED failing set, 26 default cases, not 53.** The review counted 53 default cases whose
  expected outcome round 0 had changed (2 'refuse', 51 'refuse-or-invalid'). With the brief's oracle restored and no
  marker, a scratch run of every after-audit case gave 26 failures in the default selection (330 run) and 286 in the
  exhaustive one (3,066 run); the other 27 of the 53 PASS the brief's oracle (observed INVALID: plan.json changed
  alone or with the audit tree is the F4 INVALID; a fabricated seal / receipt / registry / witness record next to the
  damaged plan makes the legacy detector's persistent INVALID fire). Marking them strict xfail would make them XPASS
  and fail, so exactly the 26 are held. `o3_held`'s rule (docstring) selects exactly the measured ids in both modes
  (scratch check: default 26 == 26, exhaustive 286 == 286, set-equal). Exhaustive: **286** held cases.
- The 26 held default cases (point|subset|bundle|damage):
  - `after-audit|plan|same|deleted`
  - `after-audit|plan|same|unparseable`
  - `after-audit|plan+audit tree|same|deleted`
  - `after-audit|plan+audit tree|same|unparseable`
  - `after-audit|plan+opening record (registry)|same|deleted`
  - `after-audit|plan+opening record (witnesses)|same|deleted`
  - `after-audit|plan+attestation|same|deleted`
  - `after-audit|plan+attestation|same|changed`
  - `after-audit|plan+attestation|same|unparseable`
  - `after-audit|plan+prereg|same|deleted`
  - `after-audit|plan+prereg|same|changed`
  - `after-audit|plan+prereg|same|unparseable`
  - `after-audit|plan+seal|same|deleted`
  - `after-audit|plan+receipt|same|deleted`
  - `after-audit|plan+stop|same|deleted`
  - `after-audit|plan+stop|same|changed`
  - `after-audit|plan+stop|same|unparseable`
  - `after-audit|plan+opening record (registry)+opening record (witnesses)+attestation+prereg+seal+receipt+stop|same|deleted`
  - `after-audit|plan+audit tree+opening record (witnesses)+attestation+prereg+seal+receipt+stop|same|deleted`
  - `after-audit|plan+audit tree+opening record (registry)+attestation+prereg+seal+receipt+stop|same|deleted`
  - `after-audit|plan+audit tree+opening record (registry)+opening record (witnesses)+prereg+seal+receipt+stop|same|deleted`
  - `after-audit|plan+audit tree+opening record (registry)+opening record (witnesses)+attestation+seal+receipt+stop|same|deleted`
  - `after-audit|plan+audit tree+opening record (registry)+opening record (witnesses)+attestation+prereg+receipt+stop|same|deleted`
  - `after-audit|plan+audit tree+opening record (registry)+opening record (witnesses)+attestation+prereg+seal+stop|same|deleted`
  - `after-audit|plan+audit tree+opening record (registry)+opening record (witnesses)+attestation+prereg+seal+receipt|same|deleted`
  - `after-audit|plan+audit tree+opening record (registry)+opening record (witnesses)+attestation+prereg+seal+receipt+stop|same|deleted`
- **Fixture (M-5)**: the module-scoped snapshot fixture also patches `socket.create_connection` (as
  conftest.s1_no_network).
- **codex_probes_old_new.md (M-6)**: the three review-driven strengthenings (T5 M-7, T7 M5, T10 crash recording)
  moved out of section 2 into a separate note counted in neither section.
- **No change (rulings), disclosed at Stage-1**: O-1 limit (M-4) and O-2 downstream availability path (M-1), above;
  concern 4 measured by the review (M-2), recorded in t14_red_mutant.txt.
