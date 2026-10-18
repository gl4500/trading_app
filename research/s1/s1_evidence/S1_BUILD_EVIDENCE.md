# S1 build evidence (Task 10 review package)

Branch `research/s1-shadow-trial`, worktree `C:\Users\gl450\trading_app-s1`, code at `4698b21` (Task 9); Task 10
commit `47f590b` changed line endings only (no content change, section 9) and added the Task 10 evidence files. Plan `docs/s1_plan.md` (sha e4d86127), spec `docs/s1_spec.md`, design
`docs/s1_design_v5.md`. Ledger = `C:\Users\gl450\.coordination\trading_app\.sdd_s1\progress.md` (cited as
`progress:L<line>`). Reports and reviews = `.sdd_s1/reports/task-*-{report,review,rereview*}.md`.

Rule for this file: it states only what an evidence file, report or review shows. Where evidence is missing it says so.
All evidence paths are relative to `research/s1/`.

## 1. Final suite (Task 10 Step 1)

`s1_evidence/full_green.txt`: `python -m pytest s1_tests -q -p no:cacheprovider` run from research/s1 with the
coordination testenv, on the HEAD 4698b21 sources plus the Task 10 `.gitattributes` change (no source or test change in
Task 10). Result: **411 passed in 715.32 s, exit 0**. The previous recorded full run is
`t9_green.txt`: 411 passed in 507 s.

## 2. RED/GREEN evidence per task

"Missing-interface RED" = the only failure is a missing module/attribute (collection error or AttributeError). It is
not behavioural evidence. "Behavioural RED" = tests ran against existing code and failed on an assertion or a wrong
outcome. Counts are the pytest summary line in each file.

| Task | RED file | RED count | RED label (as recorded) | GREEN file | GREEN count |
|---|---|---|---|---|---|
| 0 | t0_red.txt | 1 error | missing-interface (no `s1_common`) | t0_green.txt | 6 passed |
| 1 | t1_red.txt | 1 error | missing-interface (no `s1_snapshot`) | t1_green.txt | 6 passed (after the ruled test fix, progress:L30) |
| 2 | t2_red.txt | 1 error | missing-interface (no `s1_books`) | t2_green.txt | 10 passed |
| 2 fix1 | t2_fix1_red.txt | 11 failed, 12 passed | behavioural | t2_fix1_green.txt | 23 passed |
| 3 | t3_red.txt | 1 error | missing-interface (no `s1_seal`) | t3_green.txt | 52 passed (full) |
| 3 fix1 | t3_fix1_red.txt | 5 failed, 20 passed | behavioural | t3_fix1_green.txt | 60 passed (full) |
| 4 | t4_red.txt | 1 error | missing-interface (no `s1_receipt`) | t4_green.txt | 4 passed |
| 4 fix1 | t4_fix1_red.txt | 9 failed, 4 passed | behavioural | t4_fix1_green.txt | 13 passed |
| 4 fix2 | t4_fix2_red.txt | 2 failed, 13 passed | behavioural | t4_fix2_green.txt | 15 passed |
| 5 | t5_red.txt | 1 error | missing-interface (no `s1_checkpoint`) | t5_green.txt | 81 passed (full) |
| 5 fix1 | t5_fix1_red.txt | 11 failed, 7 passed | behavioural | t5_fix1_green.txt | 93 passed (full) |
| 5 fix2 | t5_fix2_red.txt | 2 failed, 19 passed | behavioural | t5_fix2_green.txt | 96 passed (full) |
| 6 | t6_red.txt | 1 error | missing-interface (no `s1_collect`) | t6_green.txt | 111 passed (full) |
| 6 fix1 | t6_fix1_red.txt | 21 failed, 16 passed | behavioural | t6_fix1_green.txt | 133 passed (full) |
| 7 | t7_red.txt | 1 error | missing-interface (no `s1_run`) | t7_green.txt | 204 passed (full) |
| 7 rulings | t7_rulings_red.txt | 5 failed | 3 missing-interface (`fifo_untrusted`), 2 behavioural | t7_rulings_green.txt | 209 passed (full) |
| 7 fix1 | t7_fix1_red.txt | 8 failed, 89 passed | behavioural | t7_fix1_green.txt | 230 passed (full) |
| 7 fix2 | t7_fix2_red.txt | 6 failed, 5 passed | behavioural | t7_fix2_green.txt | 237 passed (full) |
| 7b | t7b_red.txt | 22 failed | missing-interface (AttributeError `run_opening_checkpoint`/`run_final_snapshot`/`parse_mode`) | t7b_green.txt | 259 passed (full) |
| 7b rulings | t7b_rulings_red.txt | 8 failed, 20 passed | behavioural (recorded by the first implementer before a session restart, progress:L109) | t7b_rulings_green.txt | 265 passed (full) |
| 7b fix1 | t7b_fix1_red.txt | 6 failed, 28 passed | behavioural | t7b_fix1_green.txt | 34/34 file, 271 full |
| 7b fix2 | none (test-only fix) | - | mutant proof instead: t7b_fix2_mutant.txt (1 failed, 34 passed with the handler removed) | t7b_fix2_green.txt | 35/35 file, 272 full |
| 8 | none ("no RED expected, Tasks 0-7b exist", task-8-report) | - | oracle-teeth mutants instead: t8_oracle_mutant.txt (A, B), t8_oracle_mutant_pass.txt (C) | t8_green.txt | 2 passed (connected file); 274 full per report, no file |
| 8b | t8b_red.txt | 11 failed | 7 missing-interface (AttributeError `bridge_record`), 4 behavioural (2 connected `KeyError: 'bridge'`, Example 19 `KeyError`, edit test `['sealed row 2 changed']`) | t8b_green.txt | 283 passed (full) |
| 9 hardening | t9_hardening_red.txt | 1 failed, 2 passed | behavioural (item c) | t9_hardening_green.txt | 3 passed |
| 9 | none (mutation task) | - | see section 5 | t9_green.txt | 411 passed (full) |

Label corrections and gaps:
- Task 8b: the report says "8 missing-interface, 3 behavioural"; the RED file shows 7 and 4 (task-8b-review M2,
  corrected in the ledger, progress:L125-127). The table uses the file.
- Task 7b first round: every RED is missing-interface. The behavioural evidence for that round is 2 hand mutants run
  after GREEN (task-7b-report); their output is NOT saved as an evidence file.
- Task 7 first round: 10 hand mutants (8 killed, 2 survived -> 2 retrospective tests) are described in task-7-report;
  their output is NOT saved as an evidence file.
- Task 5 first round: two tests (corrupt row; pid change gap) were written before the code but after t5_red.txt was
  captured (task-5-report), so t5_red.txt does not show them.
- Task 7b rulings: RED was recorded by the first implementer; a second implementer finished GREEN without re-recording
  RED (progress:L109-110, task-7b-report "Rulings round").
- `t8_oracle_mutant.txt` mutants A/B ran against the round-1 connected test file (d17d02ef...); only mutant C is pinned
  to the final file (task-8-review M3).

## 3. Per requirement (spec section 2 R-IDs)

Test files are in `s1_tests/`. RED/GREEN files are those of section 2 for the listed tasks.

| R-ID | Tasks (plan headings) | Test files | RED / GREEN evidence |
|---|---|---|---|
| R-EST | none assigned in the plan | no dedicated test; enforced by implementer rules (no live DB/network) and the checkpoint import/spy tests (test_s1_checkpoint) | none specific (evidence gap) |
| R-TIME | 0 (`aware`), 3 | test_s1_common, test_s1_seal (Ex 8, UTC spellings) | t0_red/green, t3_red/green, t3_fix1_red/green |
| R-PLAN | 3, 6 | test_s1_seal (Ex 15, deadline property), test_s1_collect, test_s1_run (Ex 16) | t3_*, t6_red/green, t6_fix1_red/green, t7_* |
| R-SNAP | 1 | test_s1_snapshot; Ex 1/2 in test_s1_seal | t1_red/green, t3_* |
| R-SEAL | 3, 5, 7b, 8b | test_s1_seal, test_s1_checkpoint, test_s1_checkpoint_7b, test_s1_bridge_8b | t3_*, t5_*, t7b_*, t8b_* |
| R-QTY | 2 | test_s1_books | t2_red/green, t2_fix1_red/green |
| R-SOLD | 2 | test_s1_books (Ex 3-6) | t2_* |
| R-STOP | 3, 5 | test_s1_seal (Ex 13-15), test_s1_checkpoint | t3_*, t5_* |
| R-COUNT | 5 | test_s1_checkpoint (Ex 17, AST + runtime spies) | t5_*, t5_fix1_* |
| R-UNITS | 6, 7, 8b | test_s1_collect, test_s1_run (Ex 12, 20-23), test_s1_bridge_8b (Ex 19 end-to-end) | t6_*, t7_*, t8b_* |
| R-EPOCH | 4, 5, 7, 7b | test_s1_receipt (Ex 11), test_s1_checkpoint (Ex 10), test_s1_run (Ex 9), test_s1_checkpoint_7b | t4_*, t5_*, t7_*, t7b_* |
| R-ACQ | 6, 7b | test_s1_collect, test_s1_checkpoint_7b (final snapshot) | t6_*, t7b_* |
| R-VERDICT | 7, 8 | test_s1_run, test_s1_connected (independent Fraction oracle, FAIL and SHADOW PASS paths) | t7_*, t8_green, t8_oracle_mutant*.txt |
| R-GATES | 6, 7 | test_s1_collect, test_s1_run (Ex 16, 18) | t6_*, t7_* |
| all | 8 (connected), 9 (mutants) | test_s1_connected; s1_evidence/s1_mutants.py | t8_*, s1_mutants*.txt, cr_s1/ |

## 4. Per design example (design section 16; plan mapping table)

Every mapped test exists in the final test files (checked by `grep "def <name>"`). For every example the only recorded
RED is its task's missing-interface RED: green files are `-q` output and no fix-round RED file names an example test.
Behavioural evidence for examples comes from the targeted mutants (section 5) where the example test is the killer.

| Ex | Test | Task | RED (label) | GREEN | Targeted-mutant evidence |
|---|---|---|---|---|---|
| 1 | test_s1_seal::test_capture_between_trade_and_portfolio_commit_is_inconsistent_and_retried | 3 | t3_red (missing-interface) | t3_green, t3_fix1_green | kills mutant 10 (choose_seal ignores consistent) |
| 2 | test_s1_seal::test_trade_stored_after_close_excluded_from_as_of_rows | 3 | t3_red (m-i) | t3_green | none named; score-level retrospective tests test_fr1_score_as_of_rows_* (Task 9) |
| 3 | test_s1_books::test_dusty_closure_then_reentry_books_and_bridge | 2 | t2_red (m-i) | t2_green, t2_fix1_green | kills mutant 5 (write-off at the end) |
| 4 | test_s1_books::test_two_same_symbol_lots_fifo_count | 2 | t2_red (m-i) | t2_green | none named |
| 5 | test_s1_books::test_tiny_buy_without_sell_never_sold | 2 | t2_red (m-i) | t2_green | mutant 3 survived it; killed by retrospective test_dust_lot_without_an_allocation_from_the_sell_is_never_sold |
| 6 | test_s1_books::test_threshold_exactly_0_001_vs_below | 2 | t2_red (m-i) | t2_green | kills mutant 1 (sold `<=`) |
| 7 | test_s1_seal::test_backdated_row_invalidates | 3 | t3_red (m-i) | t3_green | mutant 15 first killed by a Task 9 8b test (none named for Ex 7) |
| 8 | test_s1_seal::test_executed_before_start_stored_after_is_cohort | 3 | t3_red (m-i) | t3_green | none named |
| 9 | test_s1_run::test_missing_attestation_is_unverified_and_not_a_nomination | 7 | t7_red (m-i) | t7_green | kills mutant 35 (UNVERIFIED pass nominated) |
| 10 | test_s1_checkpoint::test_restart_recorded_and_source_change_invalidates | 5 | t5_red (m-i) | t5_green | none named |
| 11 | test_s1_receipt::test_pid_change_without_process_start_line_is_gap | 4 | t4_red (m-i) | t4_green | mutant 23 killed by a checkpoint test, not Ex 11 |
| 12 | test_s1_run::test_carry_in_split_blocked_or_inconclusive | 7 | t7_red (m-i) | t7_green | none named |
| 13 | test_s1_seal::test_overshoot_stops_with_all_entries | 3 (amended by ruling, progress:L44) | t3_red (m-i) | t3_green, t3_fix1_green | none named |
| 14 | test_s1_seal::test_unsealed_qualifying_close_is_not_the_stop | 3 (amended by ruling, progress:L44) | t3_red (m-i) | t3_fix1_green | mutant 13 killed by it without the connected test (s1_mutants_intent.txt) |
| 15 | test_s1_seal::test_deadline_holiday_month_end_and_no_valid_seal | 3 | t3_red (m-i) | t3_green | none named (deadline mutants killed by test_deadline_calendar_months_with_month_end) |
| 16 | test_s1_run::test_prereg_after_planned_start_refused | 7 | t7_red (m-i) | t7_green | does NOT kill "prereg after START allowed" (its `match="START"` also matches the receipt refusal, task-7-report); killed by retrospective test_prereg_after_start_refused_even_with_valid_ack_and_receipt (mutant 37) |
| 17 | test_s1_checkpoint::test_checkpoint_cannot_reach_economics_or_prices | 5 | t5_red (m-i) | t5_green, t5_fix1_green | mutant 24 killed by test_counts_only_report_and_seal |
| 18 | test_s1_run::test_mismatched_or_duplicate_acks_make_no_request_no_output | 7 | t7_red (m-i) | t7_green | mutant 38 killed by test_second_score_refused_and_nothing_overwritten without the connected test (intent file) |
| 19 | test_s1_seal::test_bridge_rows_update_opening_books_not_cohort | 3 | t3_red (m-i) | t3_green | end-to-end in Task 8b: test_s1_bridge_8b::test_example19_first_post_start_seal_records_the_bridge (behavioural RED in t8b_red, kills mutant 17) |
| 20 | test_s1_run::test_bridge_ticker_unaudited_split_inconclusive | 7 | t7_red (m-i) | t7_green | none named |
| 21 | test_s1_run::test_exclusion_window_resolved_vs_inside | 7 | t7_red (m-i) | t7_green | mutant 29 survived; killed by retrospective test_exclusion_window_runs_to_the_stop_not_to_the_lots_actual_exit |
| 22 | test_s1_run::test_undated_action_excludes_all_lots_of_symbol | 7 | t7_red (m-i) | t7_green | kills mutant 30 |
| 23 | test_s1_run::test_endpoint_day_entry_missing_stop_close_excluded | 7 | t7_red (m-i) | t7_green | mutant 32 killed by it without the connected test (intent file) |

Mutant numbers refer to the order in `s1_mutants_rerun.txt`.

## 5. Mutation evidence (Task 9)

### 5.1 Targeted semantic mutants (`s1_evidence/s1_mutants.py`)
- Harness: fresh temp copy per mutant, each edit asserted to match exactly once and parse-checked; full `s1_tests`
  with `-x`; hashes printed at the head of each output.
- `s1_mutants.txt` (first run, pre-survivor-test hashes): 36/42 killed. 6 survivors, each given a labelled
  retrospective test (task-9-report section 2).
- `s1_mutants_rerun.txt` (final sources and tests): 42/42 killed. This file was refreshed in round 2; the earlier
  6/6-only re-run output described in the round-1 report no longer exists as a file.
- `s1_mutants_intent.txt`: 5 mutants first killed by the connected test or another file, re-run on a restricted test
  set: 4/4 + 1/1 killed by their intended example tests.
- Reviewer-confirmed fair mutant forms (progress:L129, "two mutant forms accepted fair"): exclusion window capped at
  the `sold_events` date; "score skips `_bridge_problems`" keeps the call and drops its result.
- Task 8 oracle teeth: t8_oracle_mutant.txt (A trail 0.11, B baseline mark at open) and t8_oracle_mutant_pass.txt
  (C hard stop 0.07) each FAIL the connected test. Task 7b: t7b_fix2_mutant.txt (handler removed, 1 failed).

### 5.2 Focused Cosmic Ray (`s1_evidence/cr_s1/`, summary `cr_summary.txt`)
- cosmic-ray 8.3.15; all operators; per-mutant test set = the module's own test files; per-mutant timeout 300 s;
  10 disjoint shards, at most 4 concurrent; sources bound in `cr_setup.json` (s1_books 63af4276, s1_seal 626ebf19,
  s1_checkpoint 403d9395, s1_run 031ec4d3, e1_sim 68f21ab1).
- **Declared scope reduction** (`cr_scope.txt`, ruling progress:L129): s1_run 2344 jobs initialised, 140 excluded
  (`_median` 92, `_restarts` 14, `_clean` 6, `_serialise` 3, `_out` 11, `_seals` 11, `_sha_or_absent` 1, `_ack` 1,
  `_write_once` 1), 2204 kept. Executed: books 194, seal 454, checkpoint 855, run 2204 = 3707 jobs.
- Focused run: 3132 KILLED (incl. 1283 stored as INCOMPETENT because the failing pytest output was not UTF-8; the
  stored traceback shows exit status 1), 575 not killed (573 survived + 2 tool failures, s1_run:529/:725).
- **Timeout kills**: 15 jobs were "KILLED" only by the 300 s timeout (14 s1_run, 1 s1_seal); they are NOT counted as
  focused kills (3132 - 15 = 3117). Re-run at 800 s (loaded focused runtime measured 369-376 s):
  1 killed by an existing test (s1_run:527), 9 by Task 9 tests, 1 genuine infinite loop (s1_seal:60 `hours=1 -> 0`,
  KILLED-by-timeout), 4 to the full suite: 3 killed by fix-round-1 tests, 1 EQUIVALENT (s1_run:213 Eq_GtE occ9).
  Future runs need >= 800 s per mutant under this load.
- Recheck of survivors against the full suite (`cr_recheck_s1.py`, `cr_recheck_full.tsv`) with two recorded
  reductions: skip the byte-identical focused files that already passed on the mutant; for function-body lines run
  only the tests that execute that line (`cr_linemap.json` via `cr_linemap_plugin.py`). Reviewer accepted, with the
  stated residual risk that an EQUIVALENT label could be wrong where a skipped test would have killed it
  (task-9-review).
- Triage of the 590 jobs not killed by the focused run (575 + 15 timeouts), `cr_triage.tsv`, rebuilt byte-identically
  from `sessions/` by `cr_triage_s1.py`:

| module | KILLED-by-full-suite | KILLED-by-new-test | KILLED-by-focused-rerun | KILLED-by-timeout | EQUIVALENT | NOT-MEANINGFUL | OPEN |
|---|---|---|---|---|---|---|---|
| s1_books | 3 | 22 | 0 | 0 | 7 | 1 | 0 |
| s1_seal | 4 | 43 | 0 | 1 | 9 | 0 | 0 |
| s1_checkpoint | 4 | 110 | 0 | 0 | 9 | 16 | 0 |
| s1_run | 52 | 269 | 1 | 0 | 34 | 5 | 0 |

- Changes vs round 2 in `cr_triage_fr1_changes.tsv` (27 rows, all intended per task-9-review re-review).
- Session DBs and `cr_linemap.json` are git-ignored; sha256 in `cr_s1/cr_untracked_manifest.txt` (78 files); durable
  copy at `.coordination/trading_app/s1_cr_archive` (progress:L134). All 78 match the working copies (section 9).
- Known inaccuracy (deferred, task-9-review m-1, progress:L133): the NOT-MEANINGFUL reason for s1_run:730 Eq_Is says
  "unreachable", but the line is reachable when aborted.json exists (verdict unaffected); plus a nit on the :213 occ9
  reason text.

## 6. Retrospective tests (written after the code they test)

Counted by docstring label in the final test files (`grep -c "Retrospective|retrospective"`): test_s1_books 17,
test_s1_seal 27, test_s1_receipt 11, test_s1_checkpoint 26, test_s1_collect 14, test_s1_run 78, test_s1_checkpoint_7b
15, test_s1_bridge_8b 3; test_s1_common, test_s1_snapshot, test_s1_connected 0. Groups:
- Task 2 fix round 1 (I-1 anomaly, I-2 invalid rows, I-3 split/boundary, M-1, M-2).
- Task 3: 1 in the first round (EST + early-close schedule), 8 in fix round 1.
- Task 4 fix rounds 1 (9 tests) and 2 (2 tests).
- Task 5 fix round 2 (3 tests); fix round 1's 12 tests were written before the fix with a behavioural RED.
- Task 6 fix round 1 (21 incl. parametrised).
- Task 7: 3 in the first round (2 kill hand-mutant survivors, 1 SystemExit-in-attempt), 5 controller-rulings tests,
  fix round 1, fix round 2.
- Task 7b: the task's own tests are labelled "Task 7b (controller-added)" (missing-interface RED); fix round 2's
  concurrent-receipt test is labelled retrospective.
- Task 8b: labelled "Task 8b (controller-added)".
- Task 9: hardening (a) and (b); 6 targeted-mutant survivor tests + 1 intent-check test; 77 `test_cr_*` tests (105
  cases); 13 `test_fr1_*` tests.
Plan tests changed by ruling (not retrospective, but amended): see section 7.

## 7. Deviations from s1_plan.md and controller rulings that changed a plan test

Process:
- Plan Global Constraints say "not a git repository ... Record evidence, not a commit". Superseded: S1 lives in the
  trading_app repo at research/s1 on branch research/s1-shadow-trial, one commit per task (progress:L27-28, L31); the
  controller commits and pushes, implementers never run git (progress:L32).
- Task 10: Steps 1-2 only; Step 3 (hashes to Codex) after the final whole-branch review (task-10-brief).

Plan tests changed by a controller ruling:
- Task 1 `test_backup_during_concurrent_wal_writer_is_a_committed_state`: brief defect; writer sets an Event after its
  first commit, test waits, asserts non-empty ids (progress:L30).
- Task 2 `test_operational_oversell_beyond_tolerance_raises` -> `..._is_an_anomaly` (same input, asserts an anomaly)
  (progress:L39).
- Task 3 `test_overshoot_stops_with_all_entries`, `test_unsealed_qualifying_close_is_not_the_stop`: explicit `today=`
  (progress:L44).
- Task 4: fixture premise change (fixture MR agent now uses `config.MR_SELL_ZSCORE` so the brief test still exercises
  an MR-used key; assertions unchanged), accepted by task-4-rereview1.
- Task 5: brief test's allowed report-key set extended for M3 (progress:L63; task-5-report fix round 1).
- Task 6: tests monkeypatch `s1_common.now_utc` (progress:L18); input adjustments under I-5 (START moved to
  2026-11-02 14:30Z, synthetic weekday calendar, plan written under an earlier clock, `final_setup` inputs), accepted
  as not weakening by task-6-rereview1.
- Task 7: `test_score_failure_inside_the_attempt_is_preserved_as_aborted` input changed (fix round 1); fix-round-1
  early-ACK test second step uses the post-window ACK (fix round 2, ruling R-1, progress:L98); rename to
  `test_score_reserves_before_any_priced_computation` (m-3).
- Task 7b: implementer edited its own (non-brief) test between RED and GREEN to be stricter (task-7b-report).

Rulings that changed behaviour vs the plan code (each tested):
- Task 0: no `s1_tests/__init__.py`; conftest puts root and s1_tests on sys.path (progress:L11).
- Task 2: I-1 oversell = anomaly not exception, OP_OVERSELL_TOL = 1e-6; I-2 row validation -> BookError; M-1/M-2
  (progress:L36-38).
- Task 3: accepted deviations UTC close instants and cohort copies with UTC ts (progress:L43); I-1 `today` required,
  the implementer's `max(today, latest seal)` removed (progress:L44); I-2 per-seal backdating (L45); M-1/M-2/M-3/M-5
  (L46).
- Task 4: design section 12 wins over brief code: closure, MR config keys (incl. class-style config.py), dirty list,
  process_identity error, crash.log rewrite (progress:L50-55).
- Task 5: C1 persistent aborted.json, C2 pid-less observations (crosses into Task 4 code), C3/M1 seal gate + receipt,
  M3 report keys, D1 reading of design section 10 (baseline_lots allowed), D2 s1_checkpoint.py as the scheduled
  command, m1 reruns.jsonl, m2 late flag, N1 last_known pid (progress:L60-68).
- Task 6: `_reserve` -> SystemExit (brief code deviation, progress:L72/L81); I-1..I-8 (progress:L73-80).
- Task 7: 15 implementer decisions accepted (progress:L89; task-7-report); C-2 FIFO-untrust rule (L87); runner change
  = ABORTED-INVALID (L88); I-1, I-2, I-3, M-1..M-6 (L92-96); R-1 and m-1..m-4 (L98).
- Task 7b (controller-added, L90): rulings L104-107, L111-114.
- Task 8: PASS path added (L118-119).
- Task 8b (controller-added, L119, L123-127).
- Task 9: hardening (c) `opening_close_of` ValueError is a recorded refusal, not an abort (L128-129); CR rulings
  (L129); scope reduction (cr_scope.txt); CR artefacts git-ignored with manifest (L134).

## 8. Controller-added tasks
- **7b** (progress:L90, L103-116): `s1_checkpoint --opening` (opening seal from plan + audit calendar, no prereg) and
  `--final-snapshot` (one successful acquisition-time capture, never seals; score requires it and SCORE_ACK binds its
  hash). Commit 0996697.
- **8b** (progress:L119, L123-127): design section 11 bootstrap: post-START seals carry a `bridge` record and hash;
  checkpoint, final snapshot and score check it. Commit 5340b5b.

## 9. Hash integrity and line endings (Task 10)

What was found (round 1, against 4698b21): every evidence hash had been recorded over the working-copy bytes, and
many working copies were CRLF or mixed, while git (core.autocrlf=true, no attribute) had stored LF-normalised blobs.
`git ls-files --eol` showed 82 tracked research/s1 files with i/lf and w/crlf or w/mixed, including s1_run.py,
s1_checkpoint.py, s1_receipt.py, conftest.py, test_s1_run.py, test_s1_checkpoint.py and most evidence files. Round 1
counts: MATCH_HEAD 59, EOL_ONLY_HEAD 53. A fresh checkout would therefore not have reproduced the recorded hashes,
including the source hashes that `cr_setup.json` binds and `cr_recheck_s1.py` asserts. This contradicts the brief's
note that the hashes were recorded on LF copies.

What was done, and why:
- `research/s1/.gitattributes` got `* -text`, with the existing e1 lines kept. `git check-attr text` gives `unset`,
  so git stops converting line endings anywhere in research/s1.
- Controller commit `47f590b` then renormalised the tree. It committed the exact tested working bytes, changed 82
  files in line endings only, and made no content change: `git diff 4698b21 47f590b --ignore-cr-at-eol` shows only
  the new Task 10 files. Index and worktree now agree (`git ls-files --eol`: 61 crlf/crlf, 41 lf/lf, 23
  mixed/mixed, no i/w disagreement).
- Why the blobs had to change: the bytes that were tested, mutation-tested and hashed are the CRLF/mixed bytes. Only
  committing those bytes lets a reviewer verify the recorded hashes from git with `git show <commit>:<path>`.

Reconciliation against HEAD 47f590b (round 2), in `s1_evidence/hash_reconciliation.txt`. It covers all 313 hash
lines in `s1_evidence/*hashes*.txt` and `cr_s1/cr_untracked_manifest.txt`.

| Status | Count | Meaning |
|---|---|---|
| MATCH_HEAD | 112 | Was 59. All 53 round-1 EOL_ONLY_HEAD rows are now exact matches. |
| MATCH_COMMIT | 13 | Exact match at the commit where that version was committed. A later task changed the file. |
| EOL_ONLY_COMMIT | 10 | Older versions of s1_checkpoint.py, s1_receipt.py, s1_run.py, test_s1_books.py and test_s1_connected.py. |
| NOT_IN_GIT_HISTORY | 22 | Intermediate pre-fix-round versions from t2–t7. They were never committed, so git cannot verify them. This is not a line-ending issue. |
| UNTRACKED MATCH | 156 | The git-ignored CR sessions and cr_linemap.json. All match their working copies. |

About the 10 EOL_ONLY_COMMIT rows: each matches the line-ending-normalised blob at its own task commit, and all of
those commits predate 47f590b. Those historic blobs cannot change. Each of the 5 files was changed again by a later
task, and its final recorded hash is a MATCH_HEAD row.

No recorded hash fails to match a committed version (raw or normalised) or the working copy, apart from the 22
intermediates.

`cr_setup.json` against the HEAD 47f590b blobs:
- The source hashes all equal the committed blobs: s1_books 63af4276, s1_seal 626ebf19, s1_checkpoint 403d9395,
  s1_run 031ec4d3, plus s1_common, s1_collect, s1_receipt, s1_snapshot and e1_sim/e1_fetch. Each of these files is
  unchanged in content since the CR setup. At 4698b21, s1_checkpoint and s1_run had hashed differently (7bc33554,
  9ebe13ad: LF blobs).
- The test files test_s1_books, test_s1_seal, test_s1_checkpoint, test_s1_checkpoint_7b and test_s1_run differ.
  This is expected: Task 9 added retrospective tests to them after the CR setup. The recheck outputs record the
  test hashes they used. conftest and the other test files match.

e1 pins, from `git show HEAD:` at 47f590b: e1_sim.py = 68f21ab19d74be27fc855f826a78b667990c2a37b5d75dd12e1a7be1f5a740fb
and e1_fetch.py = 401f17deb3551b0a585be64eb49294f50bc0396272ecd48c9f9049acc86984d6. Both are unchanged from
4698b21.

## 10. Deferred minors still open (from the ledger; status not re-verified in Task 10)
- T0 (progress:L26): fixture agents.strategy nullable vs NOT NULL; portfolios lacks last_price/entry_confidence;
  loader test covers only hash mismatch; load_pinned TOCTOU; `aware()` replaces any 'Z' and accepts date-only;
  Ledger._x leaks a connection on SQL error; `__pycache__` left behind.
- T1 (L34): WAL sidecars created by `project()` in the capture dir; live-bytes test checks only the main file; narrow
  except; partial backup.sqlite3 after failure; stale report header.
- T2 (L42): missing trade-dict key raises KeyError; weak `match="1"`; sold_events O(n^2); anomaly qty sign.
- T3 (L49): close_of no duplicate check; repeated per-seal messages; naive `today` bare TypeError; M-4 duplicate
  messages. (M-6 mutants done in Task 9.)
- T4 (L58): MR key list includes env noise (PATH, USERPROFILE, LOCALAPPDATA, HOST, PORT); broad `.config` match;
  process-environment overrides unobservable (documented limitation).
- T5 (L71): process_starts.observed double count; old-format last_process.json skips one pid comparison; BookError
  capture skips that run's fence check; corrupt aborted.json loses that slot's capture.
- T6 (L84): ABORTED manifest hashes pages only; `_abort` write failure re-exposes `__context__`; prereg hashed twice;
  plan.json ca_range end stale; naive bar `t` accepted as UTC; calendar check misses duplicates/open>=close; do_final
  does not check ACK after stop or START <= stop; bars request not batched.
- T7 (L101): TIMEOUT end instant = max sealed close; unreadable aborted.json leaves the gate open (still
  ABORTED-INVALID), no recorded-not-raised test; a final acquisition that crashes before reserving leaves no manifest.
- T7b (L116): ok-attempt helper duplicated in s1_checkpoint and s1_run; evidence line endings (addressed by section 9
  and hash_reconciliation.txt, not by editing evidence).
- T8 (L122): M2 oracle hard-codes the spin-off symbol/date; M3 mutants A/B pinned to the round-1 test file.
- T8b (L127): M5 duplicate reason. (M1, M3, M4 done in Task 9.)
- T9 (L133): s1_run:730 NOT-MEANINGFUL reason wrong; nit on :213 occ9 reason text.

## 11. Items to flag to Codex at code review
- progress:L102: C-2 FIFO-untrust rule (design clarification, ruling progress:L87); a single STOP_STATEMENT covers
  both stop attestations (progress:L96 M-5); design section 10 "imports neither the simulator nor the economics" read
  as no economics calls, `baseline_lots` allowed (progress:L64 D1); s1_checkpoint.py as the scheduled command although
  design section 6 says `s1_run.py checkpoint` (progress:L65 D2).
- C-2 (progress:L87; task-7-report concern C-2): for every unit/identity action inside the trial window on a symbol
  with any lot open across it, every cohort lot of that symbol is excluded in both arms.
- httpx carry-forward (progress:L85; task-6-rereview1): any real httpx client must keep `follow_redirects=False`;
  httpx strips only `Authorization` on cross-origin redirects, so APCA key headers would be forwarded.
- Task 9 recheck reductions (line-map test selection and skipping byte-identical focused files) and the s1_run CR
  scope reduction (cr_scope.txt).
- Line endings (section 9): resolved by commit 47f590b; the committed blobs are now the exact tested bytes, so the
  hashes sent for review can be taken from `git show 47f590b:<path>` (or later).

## 12. Evidence-file duplicates and contradictions (reported, not fixed)
- `t9_hashes.txt` repeats all 78 entries of `cr_s1/cr_untracked_manifest.txt` (identical hashes; consistent).
- `t7b_hashes.txt`, `t8_hashes.txt`, `t8_oracle_mutant.txt`, `s1_mutants_rerun.txt`, `s1_mutants_intent.txt`,
  `t9_hashes.txt` were refreshed (overwritten) in later rounds, so earlier-round values described in the reports are
  not preserved as files. Appended files (t2-t7 hashes) keep every round.
- `t7_hashes.txt` has mixed line endings (section header lines added by a different writer).
- The task-9 round-1 report names `cr_job_counts.txt` and `cr_s1/<module>/` session dirs; these are now
  `cr_job_counts_round1.txt` and `cr_s1/sessions/` (renamed in round 2, per the round-2 report).
- The Task 10 brief's statement that hashes were recorded on LF copies is contradicted by the files (section 9).

## 13. Task 11 (controller-added fix round, commit d498d3c) - deviations from s1_plan.md
- Interfaces/tokens changed by Task 11 (final-review C-1, I-1..I-6, m-1..m-7): RUN-ACK gained `toolchain_sha256=`
  (superseded by Task 12, section 14); ACQUIRE-ACK gained `attest_stop_sha256=`; `write_final_plan(root)` derives the
  final plan from the stop seal (the plan's hand-typed arguments are gone); `s1_common.MAILBOX`; post-stop captures
  never seal or abort (C-1); untracked non-.py files left the dirty list (I-2); per-symbol sold-event replay (I-3);
  carry-in uses unit/identity actions only (I-6). `docs/s1_plan.md` is a historical build plan and was not edited (R-5).
- Cosmic Ray evidence (section 5, `cr_s1/`) is bound to the 21a12b6 sources (R-4): its line numbers and triage refer
  to those files. Every function changed in Task 11 or Task 12 is covered instead by fresh targeted semantic mutants
  bound to the current sources (`s1_mutants_t12.txt`, section 14); the old CR results are not rebound to new source.

## 14. Task 12 (controller-added) - Addendum 1 rev 3
- Governing amendment: `docs/s1_design_v5_addendum1.md`, a byte copy of the approved addendum (sha256
  6cb89e36840975b8d949ec85debf9d2cedbe45bbeb9dcb374d91343dddc5e590, Codex APPROVE-ADDENDUM 92312e4f; its DRAFT header is
  unchanged by rule, the approval is recorded in the ledger). It governs where it differs from v5 / the spec, both
  unchanged.
- Per-clause implementation, tests, RED kinds and GREEN: `.sdd_s1/reports/task-12-report.md`; review closure:
  `s1_evidence/REVIEW_CLOSURE.md`; RED files `t12_<Ax>_red.txt`; full suite `t12_green.txt`; mutants
  `s1_mutants_t12.txt`; hashes `t12_hashes.txt`.

### 14.1 Deviations from s1_plan.md (Task 12)
- New module `s1_gates.py` (audit / RUN-ACK verification shared by checkpoint, runner and collector) and the explicit
  bundle list `s1_common.BUNDLE_CODE` + `DOC_PINS` (replaces Task 11's `toolchain_sha256`).
- Token texts (single-sourced in `s1_common`): AUDIT-ACK `... plan_sha256= bundle_sha256= start=`; RUN-ACK
  `runner_sha256= plan_sha256= audit_manifest_sha256= attest_start_sha256= opening_seal_sha256= opening_books_sha256=
  bundle_sha256= start=`; ACQUIRE-ACK `... attest_stop_sha256= bundle_sha256=`; SCORE-ACK `... final_snapshot_sha256=
  stop_sha256= bundle_sha256=`.
- New artifacts: `s1_out/opening_books.json` (frozen opening books, written by the START attestation),
  `s1_out/stop.json` (persisted stop), `s1_out/process_binding.json` (first observed process binding),
  `audit/calendar_source.json` (calendar pin), `captures/<day>/<slot>.attempt.json` (slot claim).
- Receipt shape `{"fingerprint", "provenance"}`; seals record `bundle_sha256`, the fingerprint hash and the provenance;
  captures record measured `capture_start`/`capture_end`; plan `deadline` is an aware instant; the calendar request
  range ends at deadline date + 14 days (`CAL_TAIL_DAYS`).

### 14.2 Disclosed limitations (A1, A6, A7)
- A6 calendar: sessions, closes and window ends come from the pinned provider listing (Alpaca `/v2/calendar`: date,
  open, close), pinned and hashed at the audit with its source, request parameters and retrieval time; completeness is
  checked against that pinned listing only (ordered as listed, unique, open < close, covering the opening close
  through deadline + 3 sessions). This is a disclosed limitation: there is no independent proof of the NYSE calendar
  beyond the pinned provider listing; special closures and early closes are the provider's open/close times. The
  synthetic dropped-session tests check the refusal path only.
- A1 effective configuration: a parsed .env subset plus the registered launcher files and the observed (sanitized)
  process binding do not prove the backend process's effective configuration; the AST closure is a file list, not proof
  of runtime loading; the operator's binding/continuity attestations stay explicit. A process binding is compared only
  when observed (an unobserved binding is an observation gap, A9.3).
- A7.2 identity: no pinned provider contract states that corporate-action ids are scoped by type, so the identity is
  the id alone (a type change under one id is a conflict - conservative).
- A7.3 effective dates: only the type's registered field (ex_date / effective_date) dates an action; process_date is
  never used; redemptions, name changes and worthless removals therefore have unknown timing (conservative handling).
  The pinned E1 `classify_ca` writes a derived `effective_date` into each record; for ex-date types a provider record
  carrying both an ex_date and a different effective_date can no longer be told apart after classification (the raw
  pages, preserved and hashed, still show it).

### 14.3 Operator notes (final-review R-2, R-3; A1 consequences)
- R-2: the bundle is the explicit list of research/s1 `s1_*.py` + the E1 pins + the three documents. Any driver or
  helper must exist (and be reviewed) BEFORE the opening seal: from the opening seal to the score, any change, removal
  or addition of a bundle file (including a new `s1_*.py`) is a PERSISTENT `aborted.json` reason "bundle" (A3.3);
  restoring the files does not resume the trial. Mutation or evidence tooling must never edit research/s1 sources in
  place during a trial (run it on a copy, as `s1_mutants_t12.py` does).
- R-3: the scheduler must queue or allow parallel instances (never "do not start a new instance"): every registered
  slot is invoked; a duplicate execution of a slot is refused and recorded (A5.2); the seal is the first eligible
  consistent capture in slot order, so a later slot's capture waits (is deferred) while an earlier slot's window is
  open and is sealed by a later invocation once it has closed. Before the scheduler entry is approved, measure a
  synthetic ledger shaped like the live MR ledger (row and symbol counts): per symbol the sold-count is still
  quadratic (final-review R-3), and a capture that ENDS after E = min(s + 10 min, W) never seals.
- A1 consequences for live-app work between the opening seal and the stop (=> ABORTED-INVALID): any change to an MR
  closure file (membership or bytes); a registered launcher file (presence or bytes); an MR-relevant .env value
  (secret-named values by keyed HMAC; the key file s1_receipt_hmac.key in the coordination folder must not be lost or
  replaced); the backend runtime's Python or package versions, including `site-packages`; the observed backend
  process binding (executable / sanitized command line). NOT invalidating: unrelated commits, pulls, checkouts,
  other branches or worktrees; tools in an isolated research venv; SQLite sidecars, logs, caches; HOST/PORT changes
  (recorded as provenance).
- The HMAC key file is created on first use by the operational receipt (never by tests, which use a tmp key).

### 14.4 Task 12 fix round 1 (reports/task-12-review.md)
- m-3 RED honesty: five tests had their scenario corrected after their RED was recorded (the post-event SELL had been
  placed after the stop close, i.e. outside the trial): test_s1_t12_a4.py
  ::test_a4_2b_a_post_event_sell_makes_the_whole_trial_inconclusive,
  ::test_a4_2b_a_sell_allocated_by_unrepaired_fifo_to_a_newer_lot_is_still_inconclusive,
  ::test_a4_a_unit_action_with_missing_or_ambiguous_date_follows_the_conservative_rule[action0] and [action1], and
  test_s1_t12_a9.py::test_a9_every_non_numeric_disposition_makes_no_valuation_call[INCONCLUSIVE-contamination].
  t12_A4_red.txt / t12_A9_red.txt show the FIRST scenario and were not re-recorded (the claim that the base code
  also priced the corrected scenarios is not evidenced by a file). Relabel: the A4 REDs that fail only on the missing
  `contamination` report key (resolved pre-entry event, closed-and-reopened symbol, event after the carry-in was
  sold, special dividend) are MISSING-INTERFACE REDs, not behavioural. The behavioural evidence for A4.2 is the killed
  2b/2c mutants (s1_mutants_t12.txt).
- m-5: test_s1_run.py::test_early_score_ack_while_running_is_refused_with_no_output now matches
  "RUNNING|not strictly after" (the NO-VALID-SEAL stop is persisted before its early step), so that test no longer
  exercises the RUNNING refusal itself; RUNNING stays pinned by test_s1_run.py::test_fr1_running_status_compared_by_value_at_the_score_gate,
  test_s1_task11.py (final plan refused while RUNNING) and test_s1_checkpoint.py::test_fr1_main_and_trial_state_compare_modes_and_status_by_value.
- m-6 (A5.3): the predicate s <= start <= end <= E with E = W = s admits a ZERO-duration capture at exactly
  08:00:00.000000; with a real clock no capture has zero duration, so the 08:00 slot is "effectively non-sealable" as
  the addendum states - a property of the clock, not of the predicate.
- m-7: test_s1_t12_mutant_survivors.py has 18 test functions (19 collected test cases: one is parametrized twice).
- Fixed: I-1 (an unreadable/unparseable closure member is a terminal ReceiptError), I-4b (a corrupt seal record is a
  preserved terminal integrity failure at checkpoint and score), m-1 (the bundle is compared, and a mismatch persisted,
  on every refusal path), m-2 (mutant evidence keeps each failure's message and kind), m-4 (a missing or changed
  stop.json after persistence is an integrity failure; stop.json's bundle is checked).
- Awaiting Codex rulings (code unchanged): I-2 process-binding reference, I-3 slot resolution rule, I-4a handling
  of registration artifacts changed after registration (REVIEW_CLOSURE.md, OPEN rows).

## 15. Task 12 fix round 2 - Addendum 2 rev 1 (s1_design_v5_addendum2.md c7f0c3ff, Codex rulings 9a72159a)
docs/s1_design_v5_addendum2.md is a byte-identical copy (sha256
c7f0c3ffcd886b0f308c5f09bc0bfaca9977f8edae596bf51b30e28cb9ae3266), pinned in s1_common.DOC_PINS beside Addendum 1,
so it is part of the registered bundle (A3.1).

### 15.1 What was implemented
- B1 (I-3): s1_seal.RESOLUTION_TIMEOUT = 30 min (single-sourced), resolution_deadline D = E + 30 min,
  pending_closes, stop_decision(pending=). s1_checkpoint: every claimed slot ends in ONE exclusive immutable
  resolution record captures/<day>/<slot>.resolution.json (SUCCESS/FAILURE published by its worker strictly before
  D; MISSED for a never-claimed slot after E; RESOLUTION-TIMEOUT at/after D, by a finalizer or by the late worker
  itself), published atomically (s1_common.publish_exclusive: temp file + hard link, never partial, never
  replaced). finalize_close selects the seal from those records in slot order; the seal bytes are a function of
  the SUCCESS record, so concurrent finalizers and replays write one identical seal. A late worker preserves its
  evidence in <slot>.late.json and never seals. Other unsealed closes left pending are resolved by later
  checkpoints and by the final snapshot (_finalize_others).
- B2 (I-2): the opening capture's observed binding is the reference (seal process_binding REFERENCE; START
  attestation process_binding_sha256; prereg process_binding; RUN-ACK through the opening seal hash).
  process_binding.json is gone. Dispositions: MATCH / GAP (explicit {"unavailable": reason}) / CHANGED (terminal,
  persistent) / EXCEPTION (A9.1, including a failed observation {"error": ...}) / MALFORMED (no seal). The score
  rechecks every seal through the frozen stop (s1_run._seal_binding_problems; gaps reported in seal_binding_gaps).
- B3 (I-4a): s1_out/registry/{opening,attest_start,prereg,stop}.json record the expected sha256 of every bound
  artifact. Registration is witnessed by any seal, any capture report recording a written seal, or a
  post-opening registry record - never by "prereg parses" or "the opening file exists".
  s1_common.registration_gate (file-only, after the bundle comparison, also when the mailbox is unreadable) records
  the first-wins abort, reason "registration artifact", with sanitized problems. Refusals are preserved in
  s1_out/refusals.jsonl. A corrupt aborted.json fails closed (s1_common.load_abort, used wherever aborted.json is
  read).
- Controller ruling (I-1 completion, A1.1): semantic_receipt(reference=) compares the bound closure's membership +
  raw sha256 BEFORE any parse (closure_raw_problems); the checkpoint hands the registered receipt to the receipt
  function (s1_checkpoint._call_receipt; main()'s receipt accepts `reference`).

### 15.2 Interpretations to confirm at code review
- The score and the final snapshot do NOT refuse on a registration-artifact violation: they persist the abort and
  go on recording (A2.3: the score is the preserved ABORTED-INVALID record). Every other command refuses.
- A registration-artifact abort records the observation time (observed_utc) and actual = None: no capture ended
  the trial, so the SCORE-ACK timing gate has no end instant for it (as for other unplaceable aborts).
- Registry ordering: the opening record is written just BEFORE the opening seal (with the seal's known sha256); a
  registry opening record without its seal is an opening in progress, not a registration (a retry of the same
  candidate re-uses it). The attestation / prereg / stop records are written just AFTER their artifact; in that
  crash window the artifact is protected only by the later bindings (RUN-ACK, prereg). Deleting EVERY witness (all
  seals, all capture reports, the registry) is indistinguishable from never registering.
- Several older refusals are now normally preceded by the B3 gate and are kept as defence in depth (attest_start's
  receipt-vs-opening-seal comparison, prereg's audit / opening-seal checks, run_ack_problems' file bindings,
  _stop_state's stop_problems); mutants on them are triaged accordingly (s1_mutants_t12_triage.txt).

### 15.3 B1 operational limitation (disclosed, B1.1)
A capture whose report is not durably published strictly before D = E + 30 min cannot seal, even if the capture
itself was eligible (for example a slow receipt or process observation). A close whose earliest claimed slot is
still PENDING holds every later slot's candidate until that slot resolves or D passes. After W (the 08:00 slot's D
lies after W) the close is resolved only by a later invocation (the next hourly slot, the next close's checkpoint
or the final snapshot), so the stop decision stays RUNNING until then. A checkpoint decides the stop at its CAPTURE
instant; for the 08:00 slot of the last eligible close that instant is W itself (still RUNNING), and the frozen stop
is decided by the next command.

### 15.4 Tests: new, corrected after RED, migrated (old -> new)
- New, written BEFORE the fix (RED s1_evidence/t12_fix2_{I1,B1,B2,B3}_red.txt; labels in t12_fix2_red_labels.txt:
  22 missing-interface, 43 behavioural): test_s1_t12_fix2_i1.py, _b1.py, _b2.py, _b3.py.
- Corrected after RED, before GREEN: fix2_b1 test_b1_a_pending_resolution_cannot_cause_an_early_terminal_stop_
  followed_by_rescue (the frozen stop is decided by a later stop decision, 15.3); fix2_b3 test_b3_a_registration_
  artifact_violation_at_the_score_is_persisted_and_prices_nothing (the score records rather than refuses, 15.2).
  Strengthened after GREEN: fix2_b3 _aborted() asserts the file exists (an assertion, not a read error); the
  registry test asserts the three records exist.
- Retrospective (after the code): test_s1_t12_fix2_mutants.py (8 tightening tests for the fix-round-1
  exception-only kills; an arbitrary / forged resolution; an earlier close resolved later; run_ack_problems'
  binding check; binding_problem's field set).
- Migrated to the Addendum 2 interface (old evidence files unchanged):
  - conftest: S1_PROCESS / S1_BINDING (the observation carries the binding); _write_seal (process +
    process_binding MATCH); new s1_unattest (the pre-attestation state: the attestation, optionally the opening
    books, and registry/attest_start.json removed).
  - test_s1_checkpoint.py: run() proc binding; allowed report keys + process_binding, resolution.
  - test_s1_checkpoint_7b.py: PROC binding; in test_attest_start_binds_the_opening_receipt_and_refuses_a_different_one
    the receipt-deletion step is removed (now the B3 abort: fix2_b3 [opening_receipt.json-deleted]).
  - test_s1_connected.py: proc binding.
  - test_s1_receipt.py test_process_identity_errors_never_empty: {} and pid-only now carry {"unavailable": ...}.
  - test_s1_run.py: test_attest_start_requires_exact_statement_once_and_before_start,
    test_prereg_refusals_write_nothing[attest], test_cr_attest_start_statement_receipt_and_clock,
    test_cr_prereg_refusal_paths, test_cr_prereg_refuses_when_the_opening_seal_is_missing - s1_unattest instead of
    deleting the attestation; an edited or deleted REGISTERED artifact now expects the B3 abort.
  - test_s1_t12_a1b.py: both binding tests REPLACED by the B2 semantics (no process_binding.json; explicit gap).
  - test_s1_t12_a3_a8.py: s1_unattest; refusals.jsonl in the hand-made-prereg listing; the plan / attest / books /
    prereg-binding breakages persist the B3 abort.
  - test_s1_t12_a5_a6.py test_a6_a_dropped_session... and test_s1_bridge_8b.py test_opening_close_error...: an
    edited prereg is first the B3 abort.
  - test_s1_t12_a9.py gap test: an explicit gap ({"error"} is now an A9.1 failure, covered by fix2_b2).
  - test_s1_t12_fix1.py I-4b and m-4 deletion tests: the B3 gate observes the bound seal / registered stop.json
    first (refusal + abort problems; no capture report).
  - test_s1_t12_mutant_followups.py: s1_unattest; "frozen slice".
  - test_s1_t12_reporting.py: the binding gap comes from an explicit unavailable observation at a later checkpoint.

## 16. Task 12 fix round 3 - re-review 1 of fix round 2 (reports/task-12-rereview1.md, CHANGES_REQUIRED)
Addendum 1 rev 3 (6cb89e36) and Addendum 2 rev 1 (c7f0c3ff) are unchanged byte for byte. Where this section and 15.2
differ, this section is the current statement (15.2's "deleting every witness is indistinguishable from never
registering" was wrong for much smaller deletions - re-review C-2 - and is superseded by 16.1/16.3).

### 16.1 What was changed
- C-1 atomic publication: every immutable artifact is created only through s1_common.publish_exclusive (temporary
  file + fsync + exclusive hard link; publish_text_exclusive keeps the former text-mode bytes): seals, stop.json,
  aborted.json, resolution / late / overrun records, both stage records, slot claims, capture reports, the opening
  receipt, final-snapshot reports, the score report, collector write-once files and raw pages, the HMAC key.
  Mutable caches (last_process.json, a re-marked meta.json) use replace_atomic. A static test pins it. Readers
  therefore never see a partial file, so no reader can turn an in-progress write into an abort.
- C-2 redundant witnesses (s1_common.registration_witnesses / _registered / _reached): every stage is recorded twice
  (registry/<stage>.json and witnesses/<stage>.json). Witnesses: the plan's opening seal, an opening capture report
  recording a written seal, an opening SUCCESS resolution, both records of every stage, attest_start.json /
  prereg.json / stop.json, the later-stage files (opening books, stop attestation, final plan, final manifest, final
  snapshot report), any post-START slot claim or seal, and the external RUN-ACK (a codex mailbox S1-RUN-ACK line
  binding this plan or audit manifest, read-only). Registered = the RUN-ACK, or >= 2 witnesses one of which is
  beyond an opening in progress. REQUIRED is decided per reached stage, not by that stage's own registry record;
  expected hashes come from either record and from the attestation's / prereg's own bindings.
- I-1: pending_closes counts a close with a SUCCESS (or unreadable) resolution but no seal as PENDING; the stop
  attestation and the final plan run the serialized finalization (s1_checkpoint.finalize_pending) before they decide
  the stop; the score (which does not finalize) refuses while RUNNING.
- I-2: a lone stray file before registration (a seal, a later-stage record or artifact) is a preserved refusal
  ("inconsistent pre-registration state"), never ABORTED-INVALID.
- M-1: the resolution timestamp is read after the evidence is built; the link instant is read again and an overrun
  at/after D is recorded (<slot>.overrun.json, report) without replacing the winner.
- M-2: the attestation and prereg are registered BEFORE their artifacts (their bytes are known first), inside
  s1_out/stage.lock; while the lock exists the gate refuses (never aborts), so a concurrent command cannot mistake
  the instant between records and artifact for a deletion. A missing stage record is detected (abort).
- M-3: with a persistent abort, the score's pre-reservation gate no longer demands a final snapshot: the one score
  records ABORTED-INVALID (zero valuation calls). M-5 docstring corrected. M-7 partially (16.3).

### 16.2 Interpretations to confirm at code review
- M-3 end instant: observed_utc is NOT used as the trial end of a registration-artifact abort. The score itself is
  frequently the observer, and its SCORE-ACK necessarily precedes it, so that rule would refuse the one score
  forever (it made 35 existing score tests refuse when tried). The verdict is ABORTED-INVALID at any ACK time.
- The stop's records are optional to the gate (stop.json is published first by whichever concurrent decider wins;
  its records follow) but must agree with it; the attestation's and prereg's records are required.
- The AUDIT-ACK is not a registration witness (it precedes the opening by design); the RUN-ACK is.
- Test-fixture migrations (same intent, the new redundancy): conftest.s1_unattest also removes
  witnesses/attest_start.json and the "run-ack" mailbox message (a RUN-ACK binds an attestation: it cannot exist in
  the pre-attestation state); fix2_mutants test_mt_a_registered_prereg_calendar_* rewrites both prereg records;
  test_mt_a_deleted_stop_and_its_registry_record_* deletes both stop records and now expects the gate's abort
  (SystemExit) - the asserted properties (no recompute, no later seal, persistent abort) are unchanged.

### 16.3 Residuals (stated, not claimed closed)
- Every local witness deleted (all records, seals, reports, resolutions, claims, attestation, books; only plan,
  audit and at most one more file left) while the mailbox is unreadable, or before any RUN-ACK exists (the interval
  between the opening and the RUN-ACK), is indistinguishable file-only from a hand-made file before the opening: a
  preserved refusal, no abort; restoring everything before the next readable-mailbox command resumes the trial.
  fix3::test_c2_residual_* documents it. Raised for a Codex ruling.
- Deleting prereg.json and BOTH its records before the first post-START slot claim leaves no prereg witness: a
  refusal ("no verified prereg"), not an abort, until a later witness exists.
- Crash windows: a crash between a stage's records and its artifact (inside stage.lock) leaves the lock: every
  command refuses until the operator inspects and removes it, after which the missing artifact is the persistent
  abort. A crash between stop.json and its records leaves stop.json without records (accepted: records optional).
- M-7: an unreadable resolution of another close is PENDING (never counted missed, no stop freezes across it), but
  _finalize_others still skips it rather than aborting; the trial then stays RUNNING until a checkpoint of that close
  aborts on it.

### 16.4 Evidence
- RED (all behavioural, run against the fix-round-2 code): t12_fix3_all_red.txt (27 failed, 3 already-satisfied
  combinations passed) split into t12_fix3_{C1,C2,I1,I2,M1,M2,M3}_red.txt. M-4: t12_fix3_M4_red.txt (5 behavioural
  REDs by guard reversion; "no capture beyond E/W" already satisfied; concurrent finalizers -> t12_fix3_C1_red).
- C-1: t12_fix3_C1_repeat200.txt (200/200 passed), t12_fix3_C1_stress.txt (4 parallel processes x 50, 0 failures).
- GREEN: t12_fix3_green.txt. Mutants: s1_mutants_t12_fix3_final.txt (runs 1-2: s1_mutants_t12_fix3_run1.txt, _run2.txt), triage s1_mutants_t12_triage.txt.
- Retrospective tests (written after the code, labelled RETROSPECTIVE): fix3::test_*_retro_* (12).

## 17. Task 12 fix round 4 - re-review 2 of fix round 3 (reports/task-12-rereview2.md, CHANGES_REQUIRED)
Addendum 1 rev 3 (6cb89e36) and Addendum 2 rev 1 (c7f0c3ff) are unchanged byte for byte. Where this section and 16
differ, this section is the current statement (it supersedes the 16.3 residual "every local witness gone ... is a
preserved refusal ... restoring everything resumes the trial", which missed the re-opening consequence, N-2).

### 17.1 What was changed
- N-1 (stage.lock race, s1_common.registration_gate/_refuse_if_locked): a violation is confirmed before the abort:
  lock check, scan, lock check, second scan, lock check; only problems present on both scans with no lock at any
  check are recorded. A lock that appeared is a "stage publication" refusal; a violation that vanished is a "state
  changed during the gate's scan" refusal - never an abort. Deterministic barrier tests (no sleeps) for both orders
  and both stages, plus the release-during-rescan order (retrospective).
- N-2 (re-opening, s1_common.opening_orphans; s1_checkpoint._before_opening_build): opening-close evidence that is
  only ever written after a record that is now missing presumes the registration happened -> the persistent
  "registration artifact" abort, whether or not any other witness remains, and never a new opening seal: a slot
  capture directory or slot record without its claim; a capture report without its resolution; last_process.json
  without any slot claim; opening_receipt.json without an opening SUCCESS resolution. The opening seal's creation
  re-checks this (after the gate, inside the serialized selection, before the receipt is stored) and refuses.
- N-3 (B3.2 narrowed, controller ruling on the A1/B3.1 reading - TO BE DISCLOSED TO CODEX): a registration needs a
  witness tied to the opening close (OPENING_TIED: a valid opening seal = a JSON seal record whose close is on the
  opening date with its capture record; any opening-close capture evidence "opening capture" - claims, capture
  directories, slot records; an opening SUCCESS resolution; a capture report recording the opening seal; the
  external RUN-ACK). Later-stage files count only once one exists. Clock anchor (s1_common.opening_anchor,
  s1_seal.first_slot_after): before the first slot of the opening close nothing is registered - registration_problems
  is empty, is_registered and registration()'s prereg stage report "not registered" (so a bundle difference is a
  refusal, not the bundle abort), and every registration file present is a preserved refusal with zero callbacks.
- m-1 (s1_common.stage_publication(out, stage)): an Exception/SystemExit after the stage's records exist but before
  its artifact keeps stage.lock (rewritten to name the interrupted stage and error): the next command refuses.
  Operator recovery: remove the lock TOGETHER with the stage's two records (the pre-stage state), never the lock alone.

### 17.2 Interpretations to confirm at code review
- N-2 literal text vs B1.4: the brief says any persisted opening-close evidence without a matching opening seal is the
  abort and that seal creation refuses if any earlier opening-slot resolution exists. Read literally this aborts a
  legitimate retry (a FAILURE at slot 45 followed by a SUCCESS at slot 47) and a SUCCESS awaiting its seal - the
  C-1 class of spurious abort. Implemented reading: evidence that is ONLY possible after a record that is now missing
  (17.1). A legitimate FAILURE, a crash before a resolution and a SUCCESS awaiting its seal stay consistent
  (fix4::test_n2_guard_* passes before and after). Seal creation refuses on that same evidence.
- The clock anchor uses the audit's pinned calendar; if that is unreadable, the earliest possible close (13:00 New
  York on the opening date) + the first offset, which is never later than the true first slot.
- A fabricated opening-tied file after the first opening slot (e.g. a claim file or capture directory plus a
  hand-made prereg) is now the persistent abort: accepted by the controller ruling ("if such evidence exists,
  registration is presumed to have happened"). For Codex to rule on.
- The scratchpad probe test_probe3.py hooks registration_problems(o, mailbox=None); the gate now passes now=, so that
  probe raises TypeError as written. Its scenario is fix4::test_n1_*[attest_start-gate-first].

### 17.3 Residuals (stated, not claimed closed) - for Codex to rule on
- Deleting EVERY file the opening produced under s1_out before any RUN-ACK exists - the opening seal, both opening
  records, every capture directory and slot record of the opening close, last_process.json, opening_receipt.json (and
  any later-stage files) - keeping plan + audit, is indistinguishable file-only from a fresh trial whose opening never
  ran: the opening can then be run again and writes a NEW, different opening seal. Deleting every file under s1_out
  (plan and audit included) is a fresh trial outright. No local check can see either; only the external mailbox
  record would, and it exists only from the RUN-ACK on.
- Narrower variant with the same consequence: the opening seal, both records, the sealing slot's resolution AND
  report AND opening_receipt.json deleted while its claim and capture directory stay is indistinguishable from a
  worker crash before its resolution (B1.4): after D the slot is RESOLUTION-TIMEOUT and a later opening slot can
  seal (a different seal). Opening-slot claims then still tie any attestation files left to the opening
  (fix4::test_n3_retro_opening_slot_claims_*), so this variant is only open while no attestation exists.
- 16.3's residuals 2 and 3 (prereg + both records deleted before the first post-START claim; crash inside
  stage.lock) stand as accepted by the re-review (m-2, m-4); m-1 now also keeps the lock after an ordinary error.
- The mailbox-unreadable variant after the RUN-ACK (re-review m-3) stands; it is outage-equivalent only because the
  re-opening it would allow is now blocked whenever any opening evidence remains (N-2).

### 17.4 Evidence
- Tests: s1_tests/test_s1_t12_fix4.py (23: 18 written first, 5 RETROSPECTIVE `*_retro_*`; the clock-anchor test and
  the forged-prereg bundle test were strengthened after GREEN for the A10.2 meaningful-kill rule and still fail on
  the round-3 code).
- RED (all behavioural, 0 missing-interface; run against the round-3 sources rebuilt in a scratch copy whose hashes
  equal the round-3 t12_hashes.txt): t12_fix4_N1_red.txt (4 failed, 1 guard), t12_fix4_N2_red.txt (4 failed, 1
  guard), t12_fix4_N3_red.txt (5 failed, 1 probe pair already a refusal), t12_fix4_minor_red.txt (2 failed).
- GREEN: t12_fix4_green.txt (813 passed). Mutants (final KILLED=283, KBE=0, SURVIVED=3 equivalents): s1_mutants_t12_fix4.py (3 retargets, 18 new; 286 in all), run 1
  s1_mutants_t12_fix4_run1.txt, final s1_mutants_t12_fix4_final.txt, triage s1_mutants_t12_triage.txt.

## 18. Task 12 fix round 5 - re-review 3 of fix round 4 (reports/task-12-rereview3.md, CHANGES_REQUIRED)
Addendum 1 rev 3 (6cb89e36) and Addendum 2 rev 1 (c7f0c3ff) are unchanged byte for byte. Targeted scope (brief
task-12-fix5.md): R-1, R-2, R-3 only. Where this section and 17 differ, this section is the current statement (it
supersedes 17.3's second residual).

### 18.1 What was changed
- R-1 (s1_common._finalizer_missed, opening_orphans): a MISSED resolution that a finalizer can have written for a
  never-claimed slot (B1.2) is consistent without a claim. The record must be outcome MISSED, for its own slot (the
  file name), decided strictly after that slot's E, and carry no capture evidence. Every other claimless record is
  still opening orphan evidence (a FAILURE/SUCCESS/TIMEOUT, a report, late or overrun record, a capture directory).
  An opening whose first slot never ran now seals at a later slot (reviewer probe test_probe8 is a permanent test).
- R-2 (s1_common.opening_anchor, _registered_opening_days, _first_slot_of, _calendar_rows): the clock anchor is the
  EARLIEST first slot over the plan's opening close and every opening close named by registered evidence: the seal
  path in either opening record, every valid seal (a seal record of its own close), every close with a slot claim,
  and the external RUN-ACK's planned START (its opening close = the session before START in the pinned calendar;
  without a readable calendar, a week before START). A plan.json edit can only move the anchor earlier. Once any
  registered evidence exists, a plan edit is evaluated as a registration: "plan.json changed since opening", the
  persistent abort; restoring the file does not resume (reviewer probe test_probe6 is a permanent test). With no
  registered evidence the plan-derived anchor stands, so the B3.2 refusal behaviour is unchanged (fix4 N-3 tests
  unchanged and green). before_opening/registration()/registration_problems/preregistration_problems pass the mailbox
  through so the RUN-ACK source is read from the same mailbox.
- R-3 (s1_checkpoint._after_opening_seal, _before_opening_seal, _claim_slot `extra`; s1_common._report_seals):
  - An opening slot invoked after the opening seal exists still refuses ("opening seal exists"): zero live
    callbacks, no capture directory. Before refusing it leaves durable evidence binding the seal: its exclusive
    claim and a refused report, both recording {"after_seal": {"seal", "sha256"}}, with a resolution (FAILURE, or
    RESOLUTION-TIMEOUT at/after D) published between them. A rerun of the same slot refuses with the same message.
  - _report_seals reads these after-seal records from reports AND claims. They are therefore registration witnesses
    ("opening capture report", opening-tied). A missing seal, or one whose hash differs from a recorded hash, is a
    registration problem: the persistent abort at the gate.
  - The serialized selection (_before_opening_seal, called in before_seal before the opening is registered) never
    writes an opening seal whose sha256 differs from any recorded opening-seal hash. It writes the persistent
    "registration artifact" abort instead.
  - The after-seal claim recording the hash was added after the first R-3 GREEN. Its own test was written first,
    with a behavioural RED (t12_fix5_R3b_red.txt), after the residual probe showed that the report alone still left
    V2 open (18.3).

### 18.2 Interpretations to confirm at code review
- R-1's field check (own slot, decided after E, no evidence) is the reviewer's optional validation. A hand-made
  MISSED record with exactly those fields, for a never-claimed slot, is indistinguishable from a finalizer's. It is
  consistent and can only make that slot unselectable (MISSED), never create a seal.
- R-2: the "earliest across registered sources" reading (re-review m-3) includes slot claims and valid seals of any
  close. A fabricated earlier claim or seal can only move the anchor earlier, which is the strict direction: files
  present then are evaluated as a registration attempt, and a lone stray is still a refusal (fix4 N-3 tests green).
  Not changed (out of scope): _opening_day_of still names the opening close from plan.json first for opening_orphans
  and the "opening seal" witness. In a registered state a plan edit is already the abort, but the abort's problem
  list can then carry extra lines naming the edited date (seen in probe6: "seals/2027-12-31.json missing").
- R-3: after-seal invocations are now recorded as refused captures, so they appear in the score report's
  refused_captures (report-only, A1.2/R-6).

### 18.3 Residuals (stated, not claimed closed) - for Codex to rule on
The §17.3 crash-like residual probe, rewritten so R-1 no longer blocks it, was re-run on the round-5 code
(t12_fix5_R3_residual_probe.txt). In each variant the opening sealed at 20:45 and the probe slot is 00:00 UTC:
- V1, §17.3 as written, with no opening slot run after the seal: the seal, both opening records, every resolution
  and report of the opening close and opening_receipt.json are deleted (the sealing slot's claim, its capture
  directory and last_process.json stay). Result: a SECOND, DIFFERENT opening seal is written; no abort.
- V2, slot 20:47 ran after the seal; the V1 set is deleted, which also removes its resolution and report while its
  claim stays: persistent abort, no seal (the claim records the hash).
- V3, as V2 but the after-seal resolution and report are kept: persistent abort, no seal.

The exact deletion set that still yields a fresh-looking (re-openable) opening, file-only, with no START
attestation file present (never made, or deleted together with both its records and opening_books.json; a deleted
attestation is indistinguishable from none) and before any RUN-ACK (wording corrected in fix round 6, re-review 4).
All of these must be deleted:
- the opening seal;
- both opening records (registry/ and witnesses/ opening.json);
- the sealing slot's resolution and report;
- opening_receipt.json;
- for EVERY opening slot that ran after the seal: its claim, its resolution and its report. With its claim gone,
  such a slot is "never claimed" and its window has passed, so the next finalizer records it MISSED, which is
  consistent under R-1.

The sealing slot's claim and capture directory and last_process.json may stay. That state is indistinguishable from
a sealing worker that crashed before its resolution (B1.4).

The scheduler normally runs every opening slot after the seal (20:47 to 08:00 the next morning), so this set
normally includes every later opening slot's claim (four more within the hour, then hourly to 08:00 New York). If those slots did not run (scheduler outage) or are deleted, V1
applies. A later opening slot then writes a different seal, and the attestation, RUN-ACK, prereg and a priced verdict
can follow. This is NOT bounded by the charter's "refusal-only" condition, so it needs Codex's explicit ruling before
any registration.

Unchanged from §17.3:
- deleting every opening-produced file under s1_out before the RUN-ACK (fresh-trial equivalent);
- deleting every file under s1_out (a fresh trial outright);
- 16.3's residuals 2 and 3;
- the mailbox-unreadable variant after the RUN-ACK.

Re-review m-3, partly open: an edit of audit/calendar.json that moves the opening close later can delay the anchor
within the opening day only. Every anchor source uses the same calendar. Once the delayed anchor passes, the
calendar edit is itself a registration problem (bound by the audit manifest). If it is restored before then,
nothing has progressed in between, because no registered command runs before the anchor. That makes it
outage-equivalent. Not hardened in this round (out of scope).

### 18.4 Evidence
- Tests: s1_tests/test_s1_t12_fix5.py (14). 13 were written before their code: the R-1/R-2/R-3 probes and
  variants, 2 R-1 guards (5 cases) and the R-3 claim-binding test, written before the claim code. 1 is
  RETROSPECTIVE (`*_retro_*`). 2 were strengthened after GREEN for the A10.2 meaningful-kill rule (18.5).
- RED (all behavioural, 0 missing-interface), run against the round-4 sources (the working tree before any fix-5
  edit; the hashes are in each file):
  - t12_fix5_R1_red.txt: probe8 fails with the persistent abort; the 5 guard cases pass;
  - t12_fix5_R2_red.txt: 3 failed, each with no abort (a refusal);
  - t12_fix5_R3_red.txt: 3 failed;
  - t12_fix5_R3b_red.txt: 1 failed (a second seal written).
- GREEN: t12_fix5_green.txt (827 passed). Residual probe: t12_fix5_R3_residual_probe.txt (its source is included).
- Reviewer probes on the round-5 code: test_probe6 and test_probe8 behave as fixed; test_probe7 (= V1) still writes
  a second seal - the 18.3 residual.

### 18.5 Mutants
- s1_mutants_t12_fix5.py: 4 retargets, 1 function rename and 14 new; 300 mutants in all.
- Run 1 (s1_mutants_t12_fix5_run1.txt): KILLED=294, KBE=2, SURVIVED=4. The non-kills were tightened (triage).
- Final (s1_mutants_t12_fix5_final.txt): KILLED=297, KILLED-BY-EXCEPTION=0, SURVIVED=3 (the known equivalents).

## 19. Task 12 fix round 6 - re-review 4 of fix round 5 (reports/task-12-rereview4.md, CHANGES_REQUIRED: F-1 only)
Addendum 1 rev 3 (6cb89e36) and Addendum 2 rev 1 (c7f0c3ff) are unchanged byte for byte. This section supersedes the
R-2 anchor statement of 18.1 ("the EARLIEST first slot over the plan's opening close and every close named by
registered evidence") and 18.2's R-2 reading.

### 19.1 What was changed
- F-1 (s1_common.opening_anchor, _audit_bound, _fallback_opening_days, _session_before):
  - **Bound plan hash.** _audit_bound reads the plan hash bound by the audit: the external S1-AUDIT-ACK line's
    plan_sha256 (its ack_id comes from the audit manifest). When that ACK cannot be read, it uses the audit
    manifest's own plan_sha256.
  - **Plan unchanged.** While plan.json's sha256 equals the bound hash, its opening close is AUTHORITATIVE for the
    clock anchor. Claims, seals or records naming any other close are never an anchor source. Before the opening,
    probe9's fabricated earlier-close claims or seals, together with an opening-close claim and prereg or
    attest_start, are a preserved refusal with zero callbacks, as they were in round 4.
  - **Plan edited.** Once plan.json differs from the bound hash, the plan is no source. The anchor is the earliest
    first slot over the sources that can name THE opening close:
    - the session before the AUDIT-ACK's planned START;
    - the seal path in either opening record;
    - the session before the RUN-ACK's planned START;
    - opening claims that record an after-seal opening seal.

    A date earlier than the AUDIT-ACK's opening close is stray evidence and never a source. Probe6 keeps the
    persistent abort, and restoring the plan does not resume.
  - **No source at all.** With the AUDIT-ACK and RUN-ACK both unreadable and no opening record, the plan-derived
    anchor stands (19.3).
  - **Evidence naming an earlier close.** It is no registration witness: "opening capture", "opening seal" and
    "post-START capture" name only the opening close and closes on/after START. Before registration such files are
    the B3.2 refusal (preregistration_problems lists stray seals).
- The 18.3 V1 wording was corrected as the reviewer asked: "with no START attestation file present (never made, or
  deleted together with both its records and opening_books.json)".

### 19.2 Interpretations to confirm at code review
- The fallback's "earliest" rule only matters between sources that can name the opening close, and every one of them
  is filtered to dates on or after the AUDIT-ACK's opening close. The reviewer's suggested "valid seal OF the
  plan-named opening close" is not used as a fallback source: the plan is untrusted there, and the AUDIT-ACK START
  names the same close.
- Unchanged (minor, re-review 4): _opening_day_of still names the close from plan.json first for opening_orphans and
  the witnesses. After a plan edit in a registered state the abort carries extra lines naming the edited date.

### 19.3 Residuals (stated, not claimed closed) - for Codex to rule on
- §18.3 unchanged, including V1 with the corrected wording. It still needs Codex's explicit ruling before any
  registration.
- New, outage-class: if plan.json is edited AND both ACK messages are unreadable AND no opening record exists, the
  edited plan's opening close is the anchor. A later date delays registration evaluation, which is a refusal, the
  same as the accepted mailbox-unreadable residual. An earlier date makes the anchor earlier, the strict direction.

### 19.4 Evidence
- Tests: s1_tests/test_s1_t12_fix6.py (8):
  - 4 written first: probe9 x3, and the edited plan with earlier-close evidence;
  - 4 RETROSPECTIVE `*_retro_*`, isolating each fallback source;
  - 1 strengthened after GREEN: a forged earlier-close opening record was added to the edited-plan test (A10.2).
- All fix4 and fix5 tests are unchanged and green.
- RED: t12_fix6_F1_red.txt, 4 behavioural failures (3 persistent aborts, 1 missing refusal), 0 missing-interface,
  run against the round-5 sources.
- GREEN: t12_fix6_green.txt (835 passed).
- Reviewer probes 6, 8 and 9 behave as fixed on the round-6 code.

### 19.5 Mutants
- s1_mutants_t12_fix6.py: 3 retargets of the round-5 R-2 mutants and 5 new F-1 mutants; 305 in all.
- First subset run (R-2/F-1, 8 mutants): 5 survived. Each source was masked by the AUDIT-ACK's opening close, or by
  "no source -> no anchor" being already strict. Fixed by:
  - falling back to the plan anchor when no source exists;
  - 4 retrospective tests and 1 strengthened test.

  After that all 8 are killed.
- Final (s1_mutants_t12_fix6_final.txt): KILLED=302, KILLED-BY-EXCEPTION=0, SURVIVED=3 (the known equivalents).

## 20. Task 12 fix round 7 - re-review 5 of fix round 6 (reports/task-12-rereview5.md, CHANGES_REQUIRED: G-1 only)
Addendum 1 rev 3 (6cb89e36) and Addendum 2 rev 1 (c7f0c3ff) are unchanged byte for byte. This section supersedes the
anchor rule of 19.1 ("while plan.json carries the bound hash its opening close is authoritative").

### 20.1 What was changed
- G-1 (1) (s1_common._audit_bound): the binding now has a status.
  - "ok": the S1-AUDIT-ACK named by the manifest was read; its plan_sha256 is the bound hash.
  - "outage": the mailbox ITSELF is unreadable (sqlite3.Error). Only then may the manifest's own plan_sha256 stand
    in, and only while the manifest's sha256 equals the hash every opening record bound.
  - "broken": anything else - a missing ack, an unknown or bogus ack id (SystemExit), a malformed or missing ACK
    line or field, or an outage with a manifest differing from the opening records. The manifest then vouches for
    nothing.

  Once registered, a changed manifest is itself the persistent "registration artifact" abort:
  audit/manifest.json is in both opening records (s1_checkpoint._register_opening), and registration_problems
  reports "audit/manifest.json changed since opening" (asserted by the probe10 test).
- G-1 (2) (opening_anchor): the anchor is the EARLIEST first slot over:
  - the plan's opening close, only while the audit vouches for the plan (status ok, or outage with matching records);
  - every source that can name THE opening close (_fallback_opening_days): the AUDIT-ACK's START, the opening
    records' seal path, after-seal claims, the RUN-ACK's START.

  Every source is kept to dates on or after the AUDIT-ACK's opening close whenever that is known (F-1). Registered
  evidence can therefore only move the anchor earlier, never be ignored. A readable RUN-ACK is a witness on its own
  (_registered), and its START anchors the clock. run_ack_witness also matches the plan and audit-manifest hashes
  that attest_start.json and prereg.json bound, so editing plan.json + the manifest cannot hide the RUN-ACK.
- With no source at all, the plan-derived anchor stands (outage class, §19.3).

### 20.2 Interpretations to confirm at code review
- "A readable RUN-ACK alone ⇒ registered" is read as a witness PLUS an anchor source: the RUN-ACK is registered from
  its own opening close's first slot. A RUN-ACK without START (the fix4 N-3 forged one) is no anchor source, and
  before the opening it stays the N-3 refusal (fix4 test unchanged).
- RETIRED: the round-6 RETROSPECTIVE test test_f1_retro_an_unchanged_plan_is_authoritative_even_when_the_audit_ack_is
  _unreadable. It is not a brief test. Its premise was:
  - a deleted AUDIT-ACK message lets the local manifest vouch for the plan;
  - an opening record naming an earlier close is ignored.

  G-1 reverses both: a missing ack id is a broken binding, and registered evidence is never ignored. Its mutant
  ("the vouched plan is no source") is now killed by a G-1 retrospective test.

### 20.3 Residuals (stated, not claimed closed) - for Codex to rule on
- New, outage class:
  - The case: the mailbox is unreadable, so the AUDIT-ACK's opening close is unknown and nothing filters the sources.
    Before the opening someone hand-makes BOTH opening records naming an EARLIER close, plus an opening-close claim
    and a later-stage file.
  - The effect: the anchor moves earlier and the gate records the persistent abort instead of a refusal.
  - The scope: it needs a mailbox outage AND fabricated stage records. No priced work is possible, but a spurious
    abort is.
- Unchanged:
  - §19.3, the edited plan + both ACKs unreadable + no opening record case;
  - §18.3 V1, which needs Codex's explicit ruling before any registration;
  - the fresh-trial deletions, the mailbox-outage variants, §16.3 residuals 2/3 and the calendar in-day delay
    (re-review 5: accepted as outage class).

### 20.4 Evidence
- Tests: s1_tests/test_s1_t12_fix7.py (7):
  - 4 written first: probe10 x2 (bogus id, ack removed), RUN-ACK alone with records deleted, and the outage with a
    manifest differing from the records;
  - 3 RETROSPECTIVE `*_retro_*`. One was edited after its first run (it now fabricates a claim of the edited plan's
    close) so it isolates its mutant.
- All fix4, fix5 and fix6 tests are green, except the one retired test (20.2).
- RED: t12_fix7_G1_red.txt, 4 behavioural failures (no abort recorded), 0 missing-interface, run against the round-6
  sources.
- GREEN: t12_fix7_green.txt (841 passed).
- Reviewer probes on the round-7 code:
  - probe10, both variants: abort; after restoring, still ABORTED-INVALID;
  - probe9: refusal;
  - probe6: abort, and after restoring, still aborted;
  - probe8: seals.

### 20.5 Mutants
- s1_mutants_t12_fix7.py: 2 retargets (one renamed "F-1/G-1 the vouched plan is no source") and 3 new G-1 mutants;
  308 in all.
- First subset run: 3 survived. The plan source can only lower the anchor, so each mutant shows only when an edited
  plan names an earlier close than every other source. They were tightened with 3 retrospective tests.
- Final (s1_mutants_t12_fix7_final.txt): KILLED=305, KILLED-BY-EXCEPTION=0, SURVIVED=3 (the known equivalents).

## 21. Task 12 fix round 8 - structural registration rule (brief task-12-fix8.md, operator-approved 2026-10-18; re-review 6 H-1, H-2)
Addendum 1 rev 3 (6cb89e36) and Addendum 2 rev 1 (c7f0c3ff) are unchanged byte for byte. This is an implementation
restructure under B3.1/B3.3/B3.4. It supersedes the anchor rules of §§17.1 (N-3), 18.1 (R-2), 19.1 (F-1) and
20.1 (G-1).

### 21.1 The rule (s1_common.registration_state - the one decision; everything else consumes it)
- **ACK lookup.** bundle_acks finds every codex->claude experiments-prereg S1-* ACK line whose `bundle_sha256=`
  equals the registered bundle. Callers pass the bundle: the bootstrap (registration()) passes the approved bundle,
  which keeps the A3.3 bundle check first-wins; the gate uses the bundle on disk, already checked equal. ACKs are
  never looked up through hashes read from editable local files.
- **Opening close and anchor.** The opening close is the session before the planned START of the S1-AUDIT-ACK(s)
  carrying the bundle, in the pinned calendar (the earliest, if several carry it). The anchor is that close's first
  slot (aware instants). plan.json, the audit manifest and the stage records never set, move or veto it.
- **registered** holds when either:
  - (a) a RUN-, ACQUIRE- or SCORE-ACK carries the bundle, together with an AUDIT-ACK carrying it. This is never
    cancelled by the anchor. An ACK with the same bundle is the same registered bundle (rule 5, fail closed).
  - (b) the clock is at/after the anchor, and the local witnesses - named by that opening close, under the unchanged
    N-3 rule _registered - register. Later-stage files count only beside an opening-tied witness. Local files
    present before the anchor are discounted: they are the B3.2 refusal (preregistration_problems).
- **Mailbox readable, no AUDIT-ACK for the bundle.** The trial is not past audit. Any local opening evidence (seals,
  opening records, capture entries, opening_receipt.json, last_process.json) is the registration-artifact abort,
  failing closed; otherwise the result is a preserved refusal.
- **Mailbox unreadable (sqlite3.Error).** Every command refuses at registration() (the outage refusal; zero
  callbacks). B3.4 is kept, so an outage cannot downgrade an observed violation: the local witnesses, named by
  plan.json else the opening records, still decide WITHOUT any anchor (fix2::test_b3_a_mailbox_outage_cannot_
  downgrade_an_established_violation unchanged and green). This reading of brief rule 3 is flagged for Codex.
- **Once registered,** every bound artifact is checked as before (both records, attestation and prereg bindings,
  audit manifest derived files, report seals, post-stop). New checks:
  - the opening records must name the AUDIT-ACK's opening seal;
  - _ack_bound_problems: the AUDIT-ACK's plan_sha256 and the RUN-ACK's plan, audit manifest, attestation, opening
    seal and books hashes, all external sources no local edit reaches. A file matching none of the ACKs that name it
    is a problem.

  Deleting, corrupting or replacing the manifest or plan is just another such violation.

### 21.2 Removed branches and removed / migrated tests
- **Code removed** from s1_common (not layered):
  - _audit_bound (the ok/outage/broken plan vouching);
  - _fallback_opening_days;
  - the plan-authoritative, min-over-sources opening_anchor (now a one-line read of registration_state);
  - before_opening;
  - the plan/manifest/attestation-hash RUN-ACK lookup in run_ack_witness (now the first RUN-ACK found by bundle);
  - the plan-named opening day in registration_witnesses, registration_problems and preregistration_problems (now
    passed in from registration_state).
- Kept: _opening_day_of / _opening_seal_rel, used only for the outage naming and opening_orphans' default for the
  checkpoint (whose plan was verified against the audit).
- **Tests:**
  - REMOVED fix4::test_n3_clock_anchor_nothing_is_registered_before_the_first_opening_slot. Its premise, a clock
    anchor cancelling a codex RUN-ACK carrying the bundle, is what rule 2 forbids. Replaced by
    fix8::test_h_a_run_ack_carrying_the_bundle_is_a_registration_even_before_the_opening (now the abort).
  - REMOVED fix7::test_g1_retro_an_outage_manifest_differing_from_the_records_never_pulls_the_anchor_earlier. Its
    premise was that in an outage the opening records name the anchor. Now an outage keeps the local witnesses with
    no anchor (21.1, 21.3).
  - MIGRATED fix4::test_n3_retro_a_lone_handmade_seal_of_the_opening_close_is_a_refusal: the interface call becomes
    `registration_witnesses(out, oc, False)`; the assertion is unchanged.
  - Still green, with docstrings that describe the superseded mechanism (they still assert correct outcomes; the
    mutants bound to that mechanism are retired):
    - fix5::test_r2_* and the fix6/fix7 retrospective anchor-source tests.

### 21.3 Residuals (stated, not claimed closed) - for Codex to rule on
- **V1 (§18.3, corrected wording):** probe7 still writes a second, different opening seal. It permits a priced path,
  so it needs Codex's explicit ruling before any registration.
- **Fresh-trial deletions:** deleting every file the opening produced before the RUN-ACK, or everything under
  s1_out, is equivalent to a fresh trial.
- **Outage class:**
  - the mailbox-outage variants;
  - in an outage, hand-made opening-tied files with no anchor: they fail closed as a spurious abort, never a priced
    path (supersedes §19.3/§20.3);
  - §16.3 residuals 2 and 3.
- **Rule 5 trade-off:** an earlier trial's ACK carrying the same bundle is treated as this registration. Before a
  fresh opening, its RUN-ACK makes the next command an abort (fail closed), and its AUDIT-ACK's START can name an
  earlier opening close. A new trial therefore needs a new bundle (e.g. a re-pinned document).
- **audit/calendar.json** (CORRECTED in fix round 9, re-review 7 H-3): the earlier wording here ("before
  registration") was wrong. The opening seal IS the registration (A3.3/B3.1), so the case was an edit AFTER
  registration, in the interval between the opening and the RUN-ACK, which B3.3 requires to be the persistent abort.
  An inserted fake session moved the calendar-derived opening close and turned it into refusal, then resume. Closed
  in fix round 9 (§22): the anchor no longer reads calendar.json.

### 21.4 Evidence
- Tests: s1_tests/test_s1_t12_fix8.py (197).
  - Written first: probe11 x3, probe12, and the exhaustive subset test (63 non-empty subsets of {plan, manifest,
    registry and witnesses opening records, attest_start, prereg} x {edit, delete, corrupt} = 189, enumerated,
    asserting the abort plus no resumption after restore).
  - RETROSPECTIVE: 3 rule-edge tests (an external ACK before the opening -> abort; opening evidence without any
    AUDIT-ACK -> abort; no AUDIT-ACK and no evidence -> refusal) and 1 isolating test (only the external ACKs bind
    a coordinated plan edit).
- RED:
  - t12_fix8_H1H2_red.txt: 6 behavioural failures against the round-7 sources (probe11 x3, probe12, the all-six
    subset in delete and corrupt modes); the other 187 subset cases already aborted on round 7.
  - t12_fix8_rule_retro_round7.txt: the 3 rule-edge tests on a scratch copy holding the round-7 s1_common (2 failed,
    1 passed; this documents round-7 behaviour, not test-first evidence).
- GREEN: t12_fix8_green.txt (1036 passed).
- Probes on the round-8 code:
  - probe11 (3) and probe12: abort; after restoring, still ABORTED-INVALID;
  - probe10 (2) and probe6: abort and no resumption;
  - probe9: refusal;
  - probe8: seals;
  - probe7 / V1: the declared residual.

### 21.5 Mutants
- s1_mutants_t12_fix8.py:
  - 6 retargets;
  - 11 RETIRED (their functions were deleted: the R-2/F-1/G-1 anchor-source mutants);
  - 6 new H mutants;
  - 303 in all.
- The first subset run left 2 survivors (other checks also catch them in a registered state) and 1 HARNESS (its
  intended test was removed). They were tightened with 1 existing and 1 retrospective isolating test and a retarget.
- Final (s1_mutants_t12_fix8_final.txt): KILLED=298, KILLED-BY-EXCEPTION=0, SURVIVED=5 (the 3 known equivalents + 2 structural equivalents under the fix-8 rule: the C-2 RUN-ACK witness and reach mutants, subsumed by rule 1a and the external-ACK binding check - triage).

## 22. Task 12 fix round 9 - re-review 7 of fix round 8 (reports/task-12-rereview7.md: H-3) and the controller corrections
Addendum 1 rev 3 (6cb89e36) and Addendum 2 rev 1 (c7f0c3ff) are unchanged byte for byte. The scope is narrow: H-3 by
the controller's decision, the rule-3 correction, and the subset-test assertion. §21.3's calendar bullet is corrected
in place: H-3 is an edit AFTER registration, not "before registration".

### 22.1 What was changed
- **The chain behind the decision.** The AUDIT-ACK carries collector_sha256, plan_sha256, bundle_sha256 and start.
  No hash in it chains to the calendar: the calendar is fetched only after the ACK. Its plan_sha256 does fix
  plan.json, and plan.json carries opening_close.
- **H-3** (s1_common.registration_state, _earliest_first_slot, EARLIEST_CLOSE_NY; controller decision):
  - The opening close DATE is plan.json's opening_close, used only while plan.json's sha256 equals the plan_sha256 of
    an S1-AUDIT-ACK found by bundle_sha256.
  - The anchor is that date's EARLIEST possible first slot: the first seal offset (OFFSETS_MIN[0] = 45 min,
    s1_seal.first_slot_after) after **EARLIEST_CLOSE_NY = 13:00 America/New_York**.

    The constant is the earliest close the slot rules allow on a session. Sources:
    - the NYSE scheduled early-close time (1:00 p.m. ET), an exchange rule I did not re-verify against a provider
      listing in this round;
    - the earliest close s1_common already assumed in its calendar-unreadable fallback since fix round 4 (§17.2).

    If no session closes earlier, no real opening slot precedes the anchor. A session closing earlier than 13:00 would
    break that, and the anchor would then need re-pinning.
  - calendar.json is no longer read for the anchor (_calendar_rows, _session_before and _first_slot_of were
    deleted). A calendar edit cannot move it. Once registered, the calendar's integrity stays checked through the
    audit manifest and the opening records ("audit/calendar.json missing or changed (bound by the audit manifest)").
  - A plan differing from every such AUDIT-ACK: with local opening evidence, the persistent abort; without it, a
    refusal. A trial registered by an external ACK still gets every bound-artifact check (the problems are combined).
- **Item 2, rule 3 corrected** (controller; it conflicted with B3.2 and the I-2 fix): with the mailbox readable but
  NO AUDIT-ACK for the bundle, the trial cannot be registered. That is always a preserved refusal with zero
  callbacks, never an abort, whatever local files exist. The fix-8 "unaudited evidence = abort" branch is removed.
- **Item 3:** the subset test now asserts the second command explicitly. After restoring, the next checkpoint reports
  stop ABORTED-INVALID with reason "registration artifact", and aborted.json is byte-identical.

### 22.2 Removed / migrated tests (old -> new)
- **Removed: fix8::test_h_opening_evidence_without_any_audit_ack_for_the_bundle_is_the_abort.** Rule 3 was
  corrected. Replaced by fix9::test_rule3_no_audit_ack_for_the_bundle_is_always_a_refusal_even_with_opening_evidence.
- **Removed: fix6::test_f1_an_edited_plan_never_lets_earlier_close_evidence_anchor_the_clock.** It asserted a refusal;
  under the controller decision an edited plan plus opening evidence is the abort. Replaced by
  fix9::test_h3_a_plan_differing_from_the_audit_ack_with_opening_evidence_is_the_abort and its refusal twin.
- **Removed: fix6::test_f1_retro_without_the_audit_ack_the_run_ack_alone_anchors_an_edited_plan and
  fix6::test_f1_retro_without_the_audit_ack_the_opening_records_anchor_an_edited_plan.** Both deleted the AUDIT-ACK
  message and asserted an abort; corrected rule 3 makes that a refusal. Replaced by fix9::test_rule3_*.
- **Removed: fix7::test_g1_retro_a_broken_binding_never_lets_an_edited_plan_pull_the_anchor_earlier.** It asserted a
  refusal for an edited plan plus a fabricated opening claim; under the controller decision that is the abort.
- **Rewritten (retrospective): fix8::test_h_retro_only_the_external_acks_bind_a_coordinated_plan_edit ->
  ..._attestation_edit.** The plan binding now catches a plan edit first, so the test edits the attestation (and every
  local copy of its hash) to isolate the external-ACK check again.
- **Migrated:**
  - fix6 probe9 x3: the anchor assertion is now `c._earliest_first_slot(oc)`; the refusal behaviour is unchanged.
  - fix8::test_h_a_run_ack_carrying_the_bundle_*: its clock is now anchor - 10 min, still before the anchor.
  - fix8 subset test: the second call is asserted (item 3).

### 22.3 Residuals and costs (for Codex)
- **New cost (controller decision, for Codex to accept):** a fabricated local opening-tied file on the opening date
  between the earliest possible first slot (13:45 New York) and the real first slot (16:45 on a regular session)
  aborts instead of refusing, since the anchor is earlier than the real first slot.
- **New, rule 5 interplay:** an AUDIT-ACK of an earlier trial with the same bundle whose plan_sha256 matches the
  current plan.json binds it the same way. A new trial needs a new bundle (as §21.3).
- **Unchanged:**
  - V1 (§18.3), which needs Codex's explicit ruling before any registration;
  - the fresh-trial deletions;
  - the outage class (§21.3; in an outage the local witnesses decide without an anchor);
  - §16.3 residuals 2 and 3.

### 22.4 Evidence
- **Tests:** s1_tests/test_s1_t12_fix9.py (6), written first:
  - probe13 x2: abort; after restoring, the START attestation is refused and the abort stays;
  - the calendar-free anchor;
  - plan mismatch without evidence (refusal) and with evidence (abort);
  - rule 3 (refusal).
- **RED:** t12_fix9_red.txt, against the round-8 sources: 4 behavioural failures (probe13 x2, the anchor, rule 3);
  0 missing-interface. The 2 plan-mismatch tests already passed on round 8 (guards).
- **GREEN:** t12_fix9_green.txt (1037 passed).
- **Probes on the round-9 code:**
  - probe13 (2): abort; after restoring, the attestation is refused;
  - probes 6, 10, 11 and 12: abort, no resumption;
  - probe9: refusal;
  - probe8: seals.

### 22.5 Mutants
- s1_mutants_t12_fix9.py: 2 retargets (one renamed "H the plan is used without the AUDIT-ACK's plan_sha256") and 1
  retired ("H opening evidence before any AUDIT-ACK is no problem", whose rule was reversed). Intended test ids that
  round 9 removed were replaced by their successors. 4 new mutants; 306 in all.
- First subset run: 2 survivors. Their intended tests no longer isolated them after the anchor moved earlier; both
  were tightened (22.2).
- Final (s1_mutants_t12_fix9_final.txt): KILLED=301, KILLED-BY-EXCEPTION=0, SURVIVED=5 (the 3 known equivalents + the 2 structural equivalents declared in fix round 8: the C-2 RUN-ACK witness and reach mutants).

## 23. Task 12 fix round 10 - re-review 8 minors (reports/task-12-rereview8.md; round 9 APPROVED_WITH_MINOR)
Addendum 1 rev 3 (6cb89e36) and Addendum 2 rev 1 (c7f0c3ff) are unchanged byte for byte. The scope is m-1, m-2 and
m-3 only.

### 23.1 What was changed
- **m-1, EARLIEST_CLOSE_NY made self-enforcing** (s1_seal.calendar_problems): a provider listing with any session in
  the plan's calendar_range whose close is earlier than s1_common.EARLIEST_CLOSE_NY (13:00 America/New_York) is a
  calendar problem.
  - At the audit it is a Structural failure: the attempt is preserved as ABORTED with the reason recorded, and no
    COMPLETE manifest exists, so the opening and every ACK-dependent stage refuse.
  - The same check also runs wherever the pinned listing is re-verified (s1_gates.verified_audit), so a later
    edited calendar cannot pass it either.
  - The clock anchor's premise (no real opening slot precedes 13:45 New York) is thus checked against the
    provider, failing closed, instead of resting on the exchange rule alone (§22.1).
- **m-2:** the fix5-7 test docstrings that describe superseded mechanisms now end with a "Fix round 10 note"
  stating the current mechanism (§21-§22). The change is text only: an AST comparison with docstrings blanked shows
  the code unchanged in all three files. Notes were added to:
  - fix5::test_r2_* (3);
  - fix6::test_f1_probe_* and test_f1_retro_a_later_fallback_*;
  - fix7::test_g1_probe_*, test_g1_the_run_ack_alone_*, test_g1_a_mailbox_outage_* and test_g1_retro_a_vouched_*.
- **m-3, housekeeping:** I removed test_probe7_fix5.py (and its .pyc) from scratchpad/probe. I created that file in
  fix round 5; its source and output are preserved in s1_evidence/t12_fix5_R3_residual_probe.txt.
  - probe_codex_map.py and s1map_vd0ifvk3/ (dated 2026-10-17 08:50, a Codex plan-review reproduction) were NOT
    created by me in this session. I left them for the controller rather than delete files whose origin I cannot
    confirm.
  - The reviewer's test_probe*.py and conftest.py are untouched.

### 23.2 Residuals
Unchanged (§22.3): V1 (for Codex before any registration); the fresh-trial deletions; the outage class; the 13:45-to-
first-slot fabrication cost. m-1 removes the "a session closing before 13:00" caveat of §22.1: such a listing now
fails the audit.

### 23.3 Evidence
- Tests: s1_tests/test_s1_t12_fix10.py (4, written first):
  - 3 cases of a 12:59 close (the opening close, a mid-trial day, the last week of calendar_range);
  - 1 guard (a 13:00 close is accepted), strengthened after the mutant run (A10.2).
- RED: t12_fix10_red.txt, against the round-9 sources: 3 behavioural failures ("DID NOT RAISE") and the guard
  passing; 0 missing-interface.
- GREEN: t12_fix10_green.txt (1041 passed).
- Mutants: s1_mutants_t12_fix10.py adds 3 mutants (check removed, boundary `<=`, range inverted); 309 in all.
  - Subset run: 2 killed, 1 KILLED-BY-EXCEPTION; the guard was strengthened and the re-run gave KILLED.
  - Final (s1_mutants_t12_fix10_final.txt): KILLED=304, KILLED-BY-EXCEPTION=0, SURVIVED=5 (the 3 known equivalents + the 2 structural equivalents declared in fix round 8).
