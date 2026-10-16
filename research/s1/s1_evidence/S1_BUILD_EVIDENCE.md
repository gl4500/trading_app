# S1 build evidence (Task 10 review package)

Branch `research/s1-shadow-trial`, worktree `C:\Users\gl450\trading_app-s1`, code at HEAD `4698b21` (Task 9) plus the
Task 10 files listed in section 10. Plan `docs/s1_plan.md` (sha e4d86127), spec `docs/s1_spec.md`, design
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
- `research/s1/.gitattributes` now has `* -text` (existing e1 lines kept). `git check-attr text` gives `unset` for
  s1 files.
- Reconciliation of all 313 hash lines in `s1_evidence/*hashes*.txt` and `cr_s1/cr_untracked_manifest.txt`:
  `s1_evidence/hash_reconciliation.txt`. Results: MATCH_HEAD 59; EOL_ONLY_HEAD 53; MATCH_COMMIT (file changed by a later
  task) 13; EOL_ONLY_COMMIT 10; NOT_IN_GIT_HISTORY 22 (intermediate pre-fix-round versions of t2-t7, never committed,
  cannot be verified from git); untracked (CR sessions, cr_linemap.json) 156, all matching the working copy. No
  recorded hash matched neither a committed version (raw or line-ending-normalised) nor the working copy, other than
  the 22 intermediates.
- Finding that contradicts the known-issue note in the Task 10 brief: the hashes were NOT recorded on LF working
  copies. They were recorded on CRLF (or mixed) working copies; git (autocrlf) stored LF blobs. `git ls-files --eol`
  shows 82 tracked files under research/s1 with LF in the index and CRLF/mixed in the working tree (including
  s1_run.py, s1_checkpoint.py, s1_receipt.py, conftest.py, test_s1_run.py, test_s1_checkpoint.py, most evidence files).
  The sources bound in `cr_setup.json` and t9_hashes.txt are those CRLF bytes, so a fresh LF checkout does not
  reproduce them (cr_recheck_s1.py's source-hash assertion would fail on it).
- e1_sim.py (CRLF blob) and e1_fetch.py (LF blob) match their pins at HEAD and in the working copy.

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
- Line endings (section 9): the committed blobs are LF while the recorded hashes are over CRLF bytes; decide which
  bytes are the reviewed ones before sending hashes.

## 12. Evidence-file duplicates and contradictions (reported, not fixed)
- `t9_hashes.txt` repeats all 78 entries of `cr_s1/cr_untracked_manifest.txt` (identical hashes; consistent).
- `t7b_hashes.txt`, `t8_hashes.txt`, `t8_oracle_mutant.txt`, `s1_mutants_rerun.txt`, `s1_mutants_intent.txt`,
  `t9_hashes.txt` were refreshed (overwritten) in later rounds, so earlier-round values described in the reports are
  not preserved as files. Appended files (t2-t7 hashes) keep every round.
- `t7_hashes.txt` has mixed line endings (section header lines added by a different writer).
- The task-9 round-1 report names `cr_job_counts.txt` and `cr_s1/<module>/` session dirs; these are now
  `cr_job_counts_round1.txt` and `cr_s1/sessions/` (renamed in round 2, per the round-2 report).
- The Task 10 brief's statement that hashes were recorded on LF copies is contradicted by the files (section 9).
