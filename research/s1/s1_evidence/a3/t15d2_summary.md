# Task 15d-2: ONE F11 installed-mutant attempt (isolated pending-branch seam)

**Authorization.** Codex t15d2_inputs_review_20261116/AUTHORIZATION_ONE_F11.txt. Base HEAD 81e1ffd47a132dd3d1b16716bd791f72400cb0fa plus the uncommitted, approved 15d-2 inputs.

**Run.** 2026-11-16 12:58:58-13:01:46 local, one session with `S1_T15_EVIDENCE_TAG=t15d2`, one ID, one attempt, no reruns.

**Status.** These are the proposer's raw results. The kill is INSUFFICIENT_EVIDENCE until Codex independently reconciles them. The scope is the isolated pending-branch seam ONLY: the pending tuple's unused dependency slot None -> [], with the real `_close_state` otherwise delegated. It is NOT real-tuple reachability or integration closure. The original real-tuple F11 record (s1_seal.py:663 TypeError, failed-elsewhere, a3/t15/ and a3/t15d1/) is kept as separate, unresolved scope. The F11 strict xfail/FINDINGS mark is NOT removed.

## Frozen inputs (raw bytes; identical before and after the run)

| input | sha256 | EOL |
|---|---|---|
| research/s1/s1_tests/test_s1_a3_mutants.py | fca36c554d867238d16a481ca764fa2e8c9ce00840f81d73a375efd7a3da5974 | LF |
| research/s1/s1_evidence/a3/t15_agreed_assertions.json | 3b519fdfacfb2eb07f78f231c992353b85c20b1b5176dbdd717914aad0111d11 | CRLF |
| research/s1/s1_tests/test_s1_a3_t15d_killers.py | 1a86e6376e42867dd10673593b283b98971fd24fb511daa5a1099abd24e4d7e3 | LF |
| research/s1/s1_tests/test_s1_a3_t15d_f11_branch.py | ab33dad3b50d6fbdeaaf0317f791c7d5ef10006ced49156a026169e2e23be4aa | LF |

The freeze records, with times, are in _session/freeze_{before,after}{,_time}.txt and _session/freeze_expected.txt.

## Pre-run checks
- Before the run, a3/t15d2/ and a3/t15d2_selftests/ were absent.
- Prerequisite pins: rc 0, 3 passed. They were `test_t15d1_selection_and_evidence_tag_from_data`, `test_t15d2_record_carries_the_actual_collect_rcs`, and the unmutated F11 branch test (_session/pre_pins.*).
- Standalone classifier self-tests: rc 0, 39 passed (_session/pre_selftests.*).
- In-session `classifier_validated` self-tests, written to a3/t15d2_selftests/: rc 0, 39/39. The junit sha is 3e1bea210841cf364248814dd6925026095ab7d42092782a69ea9f2ed0ca558a.
- History: the 403 files of a3/t15, t15_selftests, t15d1 and t15d1_selftests have identical hash lists before and after the run (list sha 2c8e3a169b9e1347f021426b00a06c86aa1e44275917b537c422d42c43a1e5d7).

## Result (inner record: a3/t15d2/stop-pending-removed/record.json, mutant-crash.json, {control,mutant}-junit.xml)

| field | value |
|---|---|
| selection | test_s1_a3_t15d_f11_branch.py::test_t15d_f11_pending_branch_precedes_dependency_consumption |
| control | valid; control rc 0; 1/1 pass; **control_collect_rc 0** |
| installation | anchor_found, anchor_count 1, installed true (target s1_seal._stop_record) |
| mutant | rc 1, no timeout; node set equal to the control's (1); **mutant_collect_rc 0** |
| crash.json call frame (structural) | test_s1_a3_t15d_f11_branch.py:31 builtins.AssertionError (terminal = innermost) |
| body-text cross-check | research/s1/s1_tests/test_s1_a3_t15d_f11_branch.py:31 AssertionError (agrees) |
| classifier label | **killed** |
| terminal = agreed f11_branch.py:31 | **YES** |

**Outer pytest:** rc 1, "1 failed in 166.99s". The failure is the expected `FindingLabelChanged: stop-pending-removed: label 'killed', but its finding records 'failed-elsewhere'`, because the strict mark was kept. It is NOT used as kill evidence. The structural path is an absolute path under the run's scratch t15tree copy and ends with the agreed relative path (_session/extract.json).

## Not done (by scope)
No mark removal, no rerun, no other case executed, no oracle movement, no commit, stage or stash. Next: Codex's independent reconciliation and a scoped F11 disposition, then the final init-only re-init.
