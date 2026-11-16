# Task 15d-1: eight named-mutant runs (adopted 15d oracles)

**Run identity.** HEAD 02ac56c6d429e40c0616e74465da5ed7724f6e1e plus the uncommitted approved Option A patch. The run was 2026-11-16 12:07:50-12:10:52 local, one sequential session, under `S1_T15_EVIDENCE_TAG=t15d1`.

**Authorization.**
- The GO is Codex's AUTHORIZATION_8_NAMED_RUNS.txt (f48d84e3), extended by INPUT_REVIEW.txt (6c3138b1) and REFREEZE_LF.txt.
- Forum status: CONDITIONAL_CONSENSUS on the inputs. The outcomes below are the proposer's raw run; they await Codex's independent reconciliation. No finding is closed, and no xfail or FINDINGS mark was changed.

## Frozen inputs (verified before the run and again after)

| input | sha256 |
|---|---|
| research/s1/s1_tests/test_s1_a3_mutants.py (runner + classifier, Option A, LF) | 276f9de7c258574eb482aef0be4d650e85b14d1ffa30ec1b34568a3bfb38a9a5 |
| research/s1/s1_evidence/a3/t15_agreed_assertions.json (mapping, CRLF as in repo) | 973fa0bb0975845642b1307d97b2a9dc4515e1a06d51aae83ec7d15efa61777d |
| research/s1/s1_tests/test_s1_a3_t15d_killers.py (killers, = draft) | 9c98162c5e71e83b81e89db42424960ac80f719ce84207b1fb8e85c6b1b10a62 |
| option_a.patch (applied with `git -c core.autocrlf=false apply`) | 2c4810823253769e8072ab05f54e45e821976a688396e25ace87d7b65bd83999 |
| previous mapping (HEAD blob, retained) | e78795f054ce196816dac72025ef0b600af5be4cd1886700c548205046602ee0 |

The Option A patch leaves classify, PLUGIN, RECORDER, run_child, MUTANTS, EXTRA, EQUIVALENT, FINDINGS, classifier_validated and FindingLabelChanged byte-identical, by AST-segment hashes; see the Option A note.

## Pre- and post-run checks
- Before the run, a3/t15d1/ and a3/t15d1_selftests/ were absent.
- Pin test `test_t15d1_selection_and_evidence_tag_from_data`: rc=0, 1 passed (_session/pin_output.txt).
- Classifier self-tests, from the `classifier_validated` fixture, written to a3/t15d1_selftests/: rc=0, 39/39 cases. The junit sha is d7e4d1a6480278a4bca48a78d6de8eabb90d7e1d7236a7db7e56931ae802f65e.
- The old a3/t15/ and a3/t15_selftests/ hold 315 files. Their hash list was identical before and after the run (list sha 4826b81132f25b721c16a68dded397698026dcc61fd77d18accfda7504bc67c0; _session/old_t15_hashes_{before,after}.txt).
- Outer pytest: rc=1, "7 failed, 1 xfailed in 181.41s".
  - The 7 failures are FindingLabelChanged with label 'killed'. That is the expected drift-guard transition; it is NOT kill evidence and the marks are kept.
  - The xfail is F11, whose label still equals its finding ('failed-elsewhere').
  - The outer rc is not used as evidence.

## Per-mutant results (inner records: a3/t15d1/<mutant>/record.json, mutant-crash.json, {control,mutant}-junit.xml)
Every one of the 8 had these properties:
- the whole control selection valid, with control rc=0;
- the mutation installed, with anchor_count=1;
- a mutant node set identical to the control's;
- mutant rc=1 and no timeout.

| ID | mutant | control | mutant rc | crash.json call frame (structural) | body-text cross-check | label | terminal = agreed? |
|---|---|---|---|---|---|---|---|
| F1 | cutoff-reservation-clock | valid, 1/1 pass | 1 | test_s1_a3_t15d_killers.py:49 builtins.AssertionError | killers.py:49 AssertionError (agrees) | killed | YES (:49) |
| F2 | deadline-missed-lt-to-le | valid, 69/69 pass (whole precedence table) | 1 | test_s1_a3_precedence.py:180 builtins.AssertionError, node [6-m-at-e] | precedence.py:180 AssertionError (agrees) | killed | YES (:180, [6-m-at-e]); the other 68 rows passed |
| F4 | omitted-envelope-input | valid, 1/1 | 1 | killers.py:60 builtins.AssertionError | killers.py:60 AssertionError (agrees) | killed | YES (:60) |
| F7 | owner-recovery-own-op | valid, 1/1 | 1 | killers.py:85 builtins.AssertionError | killers.py:85 AssertionError (agrees) | killed | YES (:85) |
| F9 | r6-books-fifo-prefix-off-by-one | valid, 1/1 | 1 | killers.py:101 builtins.AssertionError | killers.py:101 AssertionError (agrees) | killed | YES (:101) |
| F10 | r6-books-sold-events-entry-guard-dropped | valid, 2/2 ([missing], [ended]) | 1 | killers.py:118 builtins.AssertionError, node [missing] | killers.py:118 AssertionError (agrees) | killed | YES (:118, [missing]); the incidental [ended] case also failed |
| F11 | stop-pending-removed | valid, 1/1 | 1 | s1_seal.py:663 builtins.TypeError | s1_seal.py:663 TypeError (agrees) | failed-elsewhere | **NO**; agreed :130. Stays OPEN |
| F12 | stop-prefix-le-to-lt | valid, 1/1 | 1 | killers.py:149 builtins.AssertionError | killers.py:149 AssertionError (agrees) | killed | YES (:149) |

The structural paths are absolute paths under the run's scratch t15tree copy; they end with the agreed relative path. The raw values are in _session/extract.json and each mutant's crash.json.

**F11 diagnosis.** This is an observation only; the agreed line was NOT moved.
- The mutation `if stt == "unresolved":` lets a pending close fall through to `deps += dd` at s1_seal.py:663.
- For a pending close, `dd` is None, so it raises TypeError *before* `s1_slot._resolution_evidence(...)` at :668 is called.
- So the observer whose assertion is at killers.py:130 is never reached.
- Proposal_v1 predicted that the fall-through reaches `_resolution_evidence` with q=None. This run falsifies that prediction.
- The terminal is the same s1_seal.py:663 TypeError that 15b recorded. T15-F11 remains failed-elsewhere and OPEN, and its strict xfail mark is unchanged.

## Not done (by scope)
- No xfail or FINDINGS mark was removed or edited.
- No rerun, no extra mutant IDs, no Cosmic Ray, pre-flight or calibration.
- No commit, stage or stash.
- The 7 'killed' records need independent review before any mark changes.
- _session/control_* is the Step 2 unmutated check of the killers plus [6-m-at-e], taken at 52f2490 before the run. It is kept for provenance; the harness's own per-mutant controls are the ones that count.
