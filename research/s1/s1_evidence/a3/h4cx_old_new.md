# A3 H4-CX: old / new (Codex exact-head review of 5370bce, findings H4-CX-2 / P1 and H4-CX-1 / P2)

Base ce4a53b22fc5aa349bb5bd3a97c15b66f13132e9 (H5a on H4). Only `research/s1/` changes. Frozen docs untouched.

## Part A - H4-CX-2: strict directory enumeration

| observation | old (ce4a53b) | new (H4-CX) |
|---|---|---|
| `os.scandir` fails on `s1_out/captures` (PermissionError / OSError / FileNotFoundError), a stray claim present, gate | the gate PASSES (pathlib's glob yields nothing; H4's `except OSError` never runs; the stray is never seen) | refusal "captures/ could not be listed", no new INVALID, no aborted.json; held until after E5.5 (stop_gap_recover publish=False) |
| the same on the stray's `captures/<day>` | gate passes | refusal, no INVALID |
| Codex's probe shape: `_file_subjects` / `evidence_check(rows=[])` | `set()` / `[]` (the early no-files/no-rows branch accepted) | ListingRefused raised (never `[]`) |
| `os.scandir` fails on `seals/`, a stray seal present | gate passes (the F4 table's and the F3 table's seal lists both empty) | refusal (the F4 table's `_seals_on_disk` first), no INVALID |
| every other product glob site (h4cx_sites.md #1-#27) | an empty / partial inventory ("none", "no attempt", "no seal", "no stop problem", "not persisted", an unchanged bundle hash) | `c.ListingRefusal` (refused with no row) |
| listing refusal inside the score computation | (unreachable before: glob returned []) | re-raised by `_score_attempt` (no score-aborted INVALID) |
| listing refusal while deriving the OPENING-ACK `opening_slot` | (unreachable before) | re-raised (never "not derivable") |
| a genuinely absent optional directory (captures/, seals/, final_snapshot/, a day, a tree stage) | [] | [] (not in its parent's listing) |
| healthy trees, every product pattern | Path.glob | identical lists (test_matches_path_glob_on_a_healthy_tree, 14 patterns, recursive included) |

### Decisions and disclosures
1. **Missing root vs. Codex's FileNotFoundError case.** The brief makes a FileNotFoundError on `root` itself the
   typed absence (`[]`). Codex's third probe case raises FileNotFoundError on an EXISTING `captures/`. Every product
   site therefore enumerates from `s1_out` (or the parent of `final_snapshot/` / of the code directory) with the
   subdirectory as the first pattern segment: an existing `captures/` or `seals/` is a nested directory listed a
   moment earlier, so its FileNotFoundError raises (O-C5), and only a directory absent from its parent's listing is
   `[]`. No additional probe is introduced. Residual: a FileNotFoundError from scandir of `s1_out` itself is `[]`
   (s1_out absent), as today; the gate decides that root's loss first (F6.6 LOST / the plan check).
2. **No s1_out root file is ever returned.** Every pattern's first segment is a literal subdirectory name, so
   `early_refusals.jsonl` (H5a), `refusals.jsonl`, `aborted.json` etc. are never in an inventory (they are listed by
   the scandir of s1_out, never matched).
3. **Gate ordering (H4's, extended).** A listing refusal of the F3 evidence table is held exactly like a C5
   QualifiedUnreadable: stop_gap_recover runs with publish=False, E5.5 runs, then the listing refusal is raised (a
   confirmed F3 violation still raises its INVALID first; C5.1 "an I/O refusal never masks an unrelated mandatory
   INVALID"). A listing refusal from the F2.3 recompute is held like its QualifiedUnreadable. Listing refusals
   before the F3 table (stop_check, the F4 table) raise where they occur: no refusal is pending there.
4. **Capture-time refusals.** `_read_seals` runs inside the Worker after the SLOT-INTENT. A seals/ listing failure
   there now refuses (no FAILED/QUALIFIED row from the observation, no seal); the slot stays in flight and the D
   finalizer decides it - the same consequence as any other local refusal mid-capture. Previously the empty listing
   made the capture skip its fence check silently.
5. **Links.** Intermediate segments follow a directory link (as `_WildcardSelector`'s `entry.is_dir()`); `**`
   never descends into a linked directory (as `Path.walk(follow_symlinks=False)` under `rglob`). Unchanged from today.
6. **Short-circuits.** `_post_start_capture` now lists both captures and seals before deciding (fail closed on
   either); `evidence_check`'s `has_files` keeps `or` (seals/ is listed strictly by `evidence_problems` whenever
   captures has files).

### test_listing_error_refuses[scandir] (row 433): RE-POINTED at os.scandir
Kept as-is it would no longer test anything: the product no longer calls `Path.glob`, so a `Path.glob` patch is
inert, the gate passes, and the test fails. It now patches `os.scandir` for `s1_out/captures` (the layer pathlib
swallowed) - the real boundary Codex required. Its outcome is unchanged (a SystemExit, never OK). RED: on the base
the re-pointed case FAILS (the base swallows the failure); `[read]` and `[permission]` are untouched and pass.

### test_qualified_member_read_classification[failed-listing-or-lookup-as-filenotfound-both-passes] (row 496): RE-POINTED
Found by the first GREEN run (the controller's note named only row 433): it too patched `Path.glob` (captures ->
FileNotFoundError), so it became inert and failed. Re-pointed the same way, at `os.scandir` for `s1_out/captures`
raising FileNotFoundError - now a nested listed-then-failed directory, so it refuses (O-C5). Outcome unchanged
(refusal, no new INVALID). Its RED on the base is the addendum of h4cx_red.txt. No other test patches Path.glob /
rglob (grep).

## Part B - H4-CX-1: numeric validation (s1_evidence/a3/m4_workload/verdict_rule.py)

| input | old | new |
|---|---|---|
| verdict, T = NaN | READY, max_C NaN, max_T NaN, no reasons | NOT READY "run bad: invocation duration T invalid (nan)"; max over valid values only |
| verdict, L = NaN | READY, max_C NaN | NOT READY "dispatch delay L invalid (nan)" |
| verdict, T = +inf | NOT READY via "C = inf > 60" (max_T inf) | NOT READY "T invalid (inf)", max_T finite |
| verdict, T = True / L = False | READY (bool counted as 1 / 0) | NOT READY (bool rejected) |
| verdict, T = "5" | TypeError (unhandled) | NOT READY "T invalid ('5')" |
| b_conditional, T = NaN / inf / True / "5" / -1 | READY / inf / READY / TypeError / READY | B-CONDITIONAL NOT READY naming the run and T |
| b_conditional, B = NaN / True / "1" | READY / READY / TypeError | NOT READY "B invalid" |
| b_conditional, B = -1 / +inf | NOT READY | NOT READY |
| cap = NaN / inf / 0 / -60 / True, both routes | READY or nonsense comparisons | NOT READY "cap invalid" |
| T = 60.0 exactly | READY | READY |
| T = nextafter(60, inf) | NOT READY | NOT READY |

Existing reason texts for missing / negative T, unknown / negative L and negative B are unchanged (the 10 earlier
tests pass unchanged). L stays ignored in B-CONDITIONAL mode (nothing there is presented as a measured-L verdict).

### Historical summary: recomputed from the 32 recorded run JSON files (no workload re-run)
Runner: scratchpad `h4cx/recompute.py` (reads `m4_workload/runs/*.json`, L = L_driver as Codex's check_evidence.py),
old rule = `git show ce4a53b:.../verdict_rule.py`, new rule = the working tree:

| call | old | new |
|---|---|---|
| verdict(runs, workloads_resolved=False) | NOT READY, max_T 373.70092279976234, max_C 373.7011571652256, 23 reasons | identical |
| verdict(runs) | NOT READY, max_T 373.70092279976234, 22 reasons | identical |
| b_conditional(runs, None) | NOT READY, max_T 373.70092279976234, 3 reasons | identical |

All 32 recorded T / L_driver values are finite and >= 0, so no reason changes; the row-439 historical conclusion
(NOT READY, max T 373.70092279976234 s) stands. verdict.md and summary.json are not edited.

## Evidence
- h4cx_red.txt: base product (git archive ce4a53b) + the new tests: 81 failed (all AssertionError), 23 passed (the
  controls and the pre-existing verdict tests).
- h4cx_green.txt, h4cx_mutants.txt, h4cx_full.txt, h4cx_hashes.txt; h4cx_sites.md (the per-site audit).

## Fix round 1 (2026-11-15; task review verdict task-H4CX-review-verdict.md: SPEC ❌, I-1)

| finding | old (fix round 0) | new (fix round 1) | test / mutant |
|---|---|---|---|
| I-1 `s1_gates.run_ack_problems` | `except SystemExit` turned a ListingRefusal from `c.bundle_sha256()` (site #1) into "RUN-ACK unverifiable"; `s1_run._score` then appended "registration not verified: ..." and the score published **ABORTED-INVALID** | `except c.ListingRefusal: raise` ahead of `except SystemExit` - the score attempt refuses (no PREPARED, no s1.json, no row) | `test_run_ack_problems_never_turns_a_listing_refusal_into_a_problem`, `test_score_listing_refusal_in_registration_check_is_no_invalid[*]`; mutant `run-ack-problems-swallows-listing-refusal` |
| I-1 audit | catcher table compiled by reading; it missed the `_score` caller | every SystemExit-catching handler (35) enumerated by AST with a transitive call graph (h4cx_sites.md "Fix round 1"): this was the only unguarded converting one | - |
| M-1 verdict_rule | `10**400` (T, L, B or cap) -> OverflowError from math.isfinite in both routes | `_real` returns False on OverflowError: NOT READY with a reason naming the field | `test_verdict_huge_int_is_not_ready_never_raises[8]`; mutant `real-overflow-raises` |
| M-3 `s1_seal.pending_closes` | listed `captures/*`, then re-listed each day FROM s1_out: a day listed then gone vanished from the second listing -> "no pending claim" | one strict `captures/*/*.attempt.json` walk: a day listed then gone is a nested FileNotFoundError -> refusal | `test_pending_closes_day_vanishing_between_listings_refuses`; mutant `pending-closes-reanchored-per-day` |
| M-4 capture-time seals refusal | correct by reading, untested | real `run_checkpoint` with seals/ failing only inside `_read_seals`: refusal; rows = [SLOT-INTENT] only; no TRIAL-INVALID, no aborted.json, no seal; the slot lock is free | `test_checkpoint_capture_with_unlistable_seals_refuses[control, seals-at-capture]` (RED on the BASE ce4a53b: the capture QUALIFIED with an empty seal list) |
| N-1 docstring | "`**` never descends into a linked directory" | `**` never enters a directory SYMLINK but enters a JUNCTION (`is_dir(follow_symlinks=False)` is True for it), exactly as Path.walk / rglob | (behaviour unchanged; the reviewer's junction probe matched pathlib) |

### Disclosures (no code change)
- **M-2: F4-table listing refusals are not held.** `s1_stage.evaluate` (`_seals_on_disk`, `_artifacts_present`) runs
  in the gate BEFORE the F3 table and raises its listing refusal at once. If seals/ (or a tree stage directory) is
  unlistable, E5.5's mandatory INVALID - and any F3 violation - is not evaluated by this gate; a later healthy gate
  commits it. The same fault on captures/ (F3 table) IS held until after E5.5. This is the brief's letter (no
  refusal is pending at F4) and within Codex's bounded CH-H4-4, but it is a residual asymmetry, recorded for Codex.
- **N-3: a pass-abort skips confirming an already-found violation.** A seals/ listing failure inside
  `evidence_problems` (s1_slot.py:1050) aborts the whole pass, so a slot violation already found earlier in that pass
  is neither confirmed nor committed by this gate: it refuses, and the next healthy gate commits the violation.
  Conservative (never an INVALID from an unconfirmed observation), accepted behaviour.
- N-2 (intent-to-add index entries of the 8 new files) were made by the controller's `git add -N`, not by the
  implementer; no content is staged.

### Full suite
The fix-round-0 full run (5627 passed, 0 failed, 0 skipped, 2:15:58, run end 2026-11-15T01:02:55Z) is replaced in
h4cx_full.txt by ONE clean fix-round-1 run; expected 5627 + 14 fix-round-1 tests (test_s1_a3_strict_enum.py 69 -> 83) = 5641.
