# A3 H4-CX: per-site audit of every product enumeration (Codex H4-CX-2)

Base: ce4a53b22fc5aa349bb5bd3a97c15b66f13132e9 (H5a on H4). Line numbers are the base's (re-grepped there; H5a added
no glob site - the 30 call expressions on 26 lines are the brief's list, with s1_checkpoint.py's two attempt-* sites
moved from 954/962 to 958/966). After H4-CX, `grep -n "\.r\?glob(" research/s1/s1_*.py` finds nothing
(test_s1_a3_strict_enum.py::test_no_product_module_calls_path_glob).

## The mechanism

- `c.strict_glob(root, pattern)` walks the `/` segments with `os.scandir` and `fnmatch.fnmatch`; a missing `root`
  is `[]`; every other enumeration error raises (a nested directory's FileNotFoundError included). `**` = the
  directory and every descendant directory, never through a link (as Path.walk under rglob); an intermediate
  segment follows a directory link (as `_WildcardSelector`'s `entry.is_dir()`).
- `c.listing(root, pattern)` = strict_glob that turns the OSError into `c.ListingRefusal` (a SystemExit, like
  `QualifiedUnreadable`: no `except OSError` / `except Exception` on any caller path can make it "none", a problem or
  an INVALID). Every site outside s1_slot uses it.
- s1_slot keeps H4's handlers (`except OSError: raise _listing_refusal(...)`), which now actually run; the refusal is
  `s1_trial.ListingRefused` (a `Refusal` and a `c.ListingRefusal`).
- **The root is always a directory that exists while the files matter.** Every s1_out site enumerates from
  `s1_out` (`captures/*/*`, `seals/*.json`, `captures/<day>/...`, `<stage>/**/*`), the attempt sites from the parent
  of `final_snapshot/`, and the bundle from the parent of the code directory. So an existing `captures/` or `seals/`
  that fails - even with FileNotFoundError, Codex's third probe case - is a NESTED failure and refuses; only a
  genuinely absent optional directory (not in its parent's listing) is `[]`. No pattern enumerates s1_out's own
  files: the first segment is always the literal `captures`, `seals` or a stage name, so `early_refusals.jsonl`
  (H5a, s1_slot.py:252), `refusals.jsonl` and every other root file are never returned (they are never a stray or a
  registration artifact).
- **The gate.** A listing refusal raised by `s1_slot.evidence_check` is HELD by `s1_trial.gate` exactly like a C5
  refusal: `stop_gap_recover(publish=False)` (no publication), then E5.5 `opening_manifest_check` (an unrelated
  mandatory INVALID keeps its precedence, C5.1), then the listing refusal is raised. A listing refusal from the F2.3
  recompute is held like its QualifiedUnreadable. Listing refusals before the F3 table (stop_check, the F4 table) are
  raised where they occur: no refusal is pending there (H4's ordering kept).
- **SystemExit catchers on the paths** were audited; two would have turned the refusal into something else and now
  re-raise it: `s1_run._score_attempt` (score-aborted INVALID) and `s1_trial._opening_derived` (field silently "not
  derivable"). The others keep a refusal: listed in the last table.

"Refusal, no row": the command raises SystemExit; no journal row, no INVALID, no aborted.json, no publication is
based on the failed listing. Earlier rows of the same invocation (e.g. a SLOT-INTENT before the capture) are not
rolled back - exactly as for any other local I/O refusal on that path (F0.7).

## Sites

| # | site (base line) | now | caller path | outcome on a raised enumeration error | test |
|---|---|---|---|---|---|
| 1 | s1_common.py:118 `bundle_manifest` `HERE.glob("s1_*.py")` | `listing(HERE.parent, "s1/s1_*.py")` | `bundle_sha256` <- `s1_trial.gate` F6.4 (first bundle read, before any row; no catcher), `bundle_gate` / `verify_bundle_first` (SystemExit -> `record_refusal`, re-raised), `s1_gates.verified_audit` (<- `s1_slot._calendar`: `except Exception` does not catch it, so it reaches the gate's held listing refusal; <- `_opening_derived`: now re-raised), `s1_gates.run_ack_problems` (**fix round 1, review I-1:** it caught the SystemExit as "RUN-ACK unverifiable"; callers `verified_registration` (a refusal) AND `s1_run._score` :1270 (`invalid += ...` -> ABORTED-INVALID); now re-raised before its `except SystemExit`), record builders after the gate (propagate) | refusal, no row; never a silent empty `unexpected` (which would hash as the approved bundle) | site test `[s1_common.bundle_manifest]`, `test_bundle_hash_refuses_when_the_code_directory_is_unlistable` |
| 2 | s1_common.py:679 `_day_success` | `listing(out, "captures/<day>/*.resolution.json")` | `opening_orphans`, `registration_witnesses` <- `registration_state` / `registration_problems` / `preregistration_problems` <- `registration_gate` (both scans; `write_abort` / `invalidate_current` only after both scans return) <- `verify_bundle_first` (record_refusal, raise) / `s1_trial._legacy_detectors` (record_refusal, raise Refusal) / `is_registered` | refusal, no row, no abort | `[s1_common._day_success]` |
| 3 | s1_common.py:692-693 `_post_start_capture` (`captures/*`, `<day>/*.attempt.json`) | `listing(out, "captures/*/*.attempt.json")` | `registration_witnesses` -> as #2 | refusal, no row, no abort | `[s1_common._post_start_capture[captures]]` |
| 4 | s1_common.py:695 `_post_start_capture` `seals/*.json` | `listing(out, "seals/*.json")`, listed BEFORE either `any()` decides (no short-circuit past an unlistable seals/) | as #3 | refusal | `[s1_common._post_start_capture[seals]]` |
| 5 | s1_common.py:745 `_local_opening_evidence` seals | `listing(out, "seals/*.json")` | `registration_problems` (fix round 9 unbound-plan branch) -> as #2 | refusal, no row, no abort | `[s1_common._local_opening_evidence[seals]]` |
| 6 | s1_common.py:747 `_local_opening_evidence` `captures/*/*` | `listing(out, "captures/*/*")` | as #5 | refusal | `[s1_common._local_opening_evidence[captures]]` |
| 7 | s1_common.py:859 `opening_orphans` `captures/*/*.attempt.json` | `listing(out, ...)` | `registration_problems`, `preregistration_problems` -> as #2 | refusal; never "last_process.json without any claim" (an orphan problem -> abort) from an unlistable captures/ | `[s1_common.opening_orphans]` |
| 8 | s1_common.py:1087 `preregistration_problems` seals | `listing(out, "seals/*.json")` | `registration_gate` (the B3.2 stray refusal branch) | refusal (a listing refusal instead of a stray refusal; never "no stray seal") | `[s1_common.preregistration_problems]` (unregistered root) |
| 9 | s1_checkpoint.py:75 `_seal_files` | `c.listing(out, "seals/*.json")` | `_seals` <- `_read_seals` (checkpoint capture :567 and opening :905, inside the Worker after the SLOT-INTENT; its `except (OSError, ValueError)` -> terminal "bad seal record" FAILED does not catch a SystemExit); `_final_snapshot_capture` :1006 (after the ok-attempt check, before any attempt directory) | refusal: no FAILED / QUALIFIED row and no seal from the observation (the Worker releases its lock; the slot stays in flight and the D finalizer decides it, as for any capture-time local refusal); final snapshot: no attempt, no row | `[s1_checkpoint._seal_files]`, `[s1_checkpoint._read_seals]` |
| 10 | s1_checkpoint.py:958 `_next_attempt` | `c.listing(d.parent, "final_snapshot/attempt-*")` | `_final_snapshot_capture` :1017 (after `d.mkdir`, before `take_snapshot`) | refusal; no attempt-NN, no row (final_snapshot/ itself may have just been created empty, as before any refused attempt) | `[s1_checkpoint._next_attempt]` |
| 11 | s1_checkpoint.py:966 `ok_attempts` | `c.listing(d.parent, "final_snapshot/attempt-*")` | `_final_snapshot_capture` :1003 (the "already taken" check) | refusal before any write; never "no successful attempt" (which would allow a retake) | `[s1_checkpoint.ok_attempts]` |
| 12 | s1_run.py:676 `_seals` | `c.listing(out, "seals/*.json")` | `_score` :1285 (`except (OSError, ValueError)` -> "bad seal record" INVALID does not catch it) <- `_score_attempt` (now re-raises `c.ListingRefusal`, never StageAbort(score-aborted)) <- `s1_stage.run` work (propagates after the STAGE-INTENT, no PREPARED; F4 table decides on re-entry - as an OSError) | refusal, no PREPARED, no score-aborted INVALID | `[s1_run._seals]`, `test_score_attempt_listing_refusal_is_no_score_abort` |
| 13 | s1_run.py:1003 `_ok_attempts` | `c.listing(d.parent, "final_snapshot/attempt-*")` | score preconditions :994 (before the stage: "nothing written"); `_final_snapshot_problems` <- `_score` -> as #12 | refusal | `[s1_run._ok_attempts]` |
| 14 | s1_run.py:1195 `_restarts` | `c.listing(out, "captures/*/*.report.json")` | `_report_restarts_and_bridge` <- `_score` -> as #12 | refusal | `[s1_run._restarts]` |
| 15 | s1_run.py:1206 `_capture_notes` | `c.listing(out, "captures/*/*.report.json")` | as #14 | refusal | `[s1_run._capture_notes]` |
| 16 | s1_seal.py:109 `pending_closes` `captures/*` | fix round 1 (review M-3): ONE `c.listing(out, "captures/*/*.attempt.json")` for #16+#17 (the fix-round-0 per-day re-listing from s1_out turned a day listed then gone into "no pending claim") | no product caller (kept strict) | refusal | `[s1_seal.pending_closes]`, `test_pending_closes_day_vanishing_between_listings_refuses` |
| 17 | s1_seal.py:112 `pending_closes` `<day>/*.attempt.json` | folded into #16 | as #16 | refusal (a vanished day is a nested FileNotFoundError) | as #16 |
| 18 | s1_seal.py:393 `_seal_index` | `c.listing(out, "seals/*.json")` | `stop_problems` :875 (outside its recheck try) -> as #19 | refusal | `[s1_seal._seal_index]` |
| 19 | s1_seal.py:849 `stop_problems` reports | `c.listing(out, "captures/*/*.report.json")` | final plan (s1_collect:472), stop attestation (s1_run:717), score end (s1_run:968) and integrity (s1_run:1297 -> #12), final snapshot (s1_checkpoint:1012, catches ValueError/KeyError/TypeError only), `registration_problems` post-stop (:1070, catches OSError/ValueError/... not SystemExit) | refusal; never "no stop problem" or "persisted stop unverifiable" | `[s1_seal.stop_problems]` |
| 20 | s1_seal.py:424 `stop_was_persisted` | `c.listing(out, "captures/*/*.report.json")` | `c._reached` <- `registration_problems` -> as #2 | refusal | `[s1_seal.stop_was_persisted]` |
| 21 | s1_slot.py:1015 `_file_subjects` | `c.strict_glob(out, "captures/*/*")` in H4's `except OSError -> _listing_refusal` (now reached) | `evidence_problems` <- `evidence_check` <- `s1_trial.gate`: held (stop_gap_recover publish=False, E5.5, then raised) | refusal, no new INVALID, no abort, no publication; a stray is never missed (Codex's probe: all three exception types) | `test_gate_stray_capture_enumeration_failure_refuses[*]`, `test_evidence_check_never_takes_the_no_evidence_branch[*]`, `test_gate_listing_refusal_held_until_e55`, `test_listing_error_refuses[scandir]` |
| 22 | s1_slot.py:1049 `evidence_problems` seals | `c.strict_glob(out, "seals/*.json")` (H4 handler) | as #21, in either pass (a confirming-pass failure cannot confirm) | refusal (held) | `test_gate_seals_inventory_failure_refuses[seals-*]` (the F4 table's #29 fires first in the gate) |
| 23 | s1_slot.py:1131 `_stray_files` | `c.strict_glob(out, "captures/*/*")` (H4 handler) | `_judge_without_calendar` (both scans) <- `evidence_check` -> as #21 | refusal (held); never "nothing left to judge" | `[s1_slot._stray_files]` |
| 24-25 | s1_slot.py:1178 `evidence_check` `has_files` (captures, seals) | `bool(c.strict_glob(...))` (H4 handler) | `s1_trial.gate` -> held as #21 | refusal; never the early no-files/no-rows return | `test_evidence_check_never_takes_the_no_evidence_branch[*]` |
| 26 | s1_stage.py:539 `_artifacts_present` `d.rglob("*")` | `c.listing(out, "<stage>/**/*")` (the explicit strict walk) | `evaluate` (gate, F4 table, before F3: nothing pending), `created_problems` / `_check_created` (before `invalidate`), `_decide_locked` (under the stage lock, before `invalidate`; the lock is released in `finally`) | refusal, no INVALID (stage-replaced / registration-artifact are never based on it) | `[s1_stage._artifacts_present]` |
| 27 | s1_stage.py:589 `_seals_on_disk` | `c.listing(out, "seals/*.json")` | `evaluate` first line (gate) | refusal; a stray seal is never missed | `[s1_stage._seals_on_disk]`, `test_gate_seals_inventory_failure_refuses[seals-*]` |

(#3/#4 and #24/#25 are the two expressions of one line each; the brief's 692-695 range is #3/#4 plus the `any()`
on 693.)

## SystemExit catchers on these paths

| catcher | reached by a listing refusal? | result |
|---|---|---|
| `s1_run._score_attempt` `except (Exception, SystemExit)` -> StageAbort(score-aborted) | yes (#12-#15, #19) | **changed**: `c.ListingRefusal` re-raised with OSError / QualifiedUnreadable (refusal, no PREPARED) |
| `s1_trial._opening_derived` `except (..., SystemExit): pass` (opening_slot) | yes (#1 via verified_audit) | **changed**: `c.ListingRefusal` re-raised (never "not derivable") |
| `s1_trial.gate` held C5 refusals | yes (#21-#25; F2.3 recompute) | **changed**: listing refusals held until after E5.5; stop_gap_recover publish=False |
| `s1_trial._opening_derived` evidence_manifest `except (..., SystemExit)`; `_manifest_sha` (SystemExit -> unreconstructible) | no: `evidence_manifest` reads named members and enumerates nothing | unchanged |
| `s1_seal.stop_problems` recheck `except (..., SystemExit)` | no: `_journal` / `stop_record` / `sampled_seals` enumerate nothing (#18/#19 are outside that try) | unchanged |
| `c.verify_bundle_first` (registration() fallback, then record_refusal + raise) | yes | refusal (preserved in refusals.jsonl) |
| `c.registration_problems` `_report_seals` SystemExit | no (required_seals reads rows) | unchanged |
| `s1_trial._legacy_detectors` (record_refusal, raise Refusal) | yes (#2-#8, #20) | refusal |
| `s1_gates.run_ack_problems` SystemExit -> problem | yes (#1) | **changed in fix round 1 (review I-1)**: the fix-round-0 table said "refusal (verified_registration)" and missed its second caller `s1_run._score`, where the problem became ABORTED-INVALID; `c.ListingRefusal` is now re-raised |
| `s1_slot.run_seal_stage` / `s1_checkpoint._opening_stage` SystemExit -> `{"refused": ...}` | yes (stage run gates/work) | a reported refusal, no seal (existing representation of every refusal there) |
| `s1_slot._calendar` `except Exception` | yes (#1) | not caught (SystemExit) -> the gate's held listing refusal |
| `s1_journal.append` `except BaseException` (ROLLBACK, re-raise) | yes (in-transaction gates) | no row |
| `s1_stage._resolve` / `s1_slot.finalize_close` / `s1_checkpoint.run_opening_finalizer` `except SystemExit: raise` | yes | refusal |

## Fix round 1 (2026-11-15): the complete catcher audit (review I-1: "prove there is no second")

**Method.** The fix-round-0 catcher table was compiled by reading caller paths, and it missed
`s1_gates.run_ack_problems` -> `s1_run._score`. This audit enumerates mechanically instead. The runner is the scratchpad
`h4cx/catchers.py` (sha256 d4b3b317a6717fe3380707ddeb62332d63925676c19275d1ecd3769d142044ab). Every handler in
`research/s1/s1_*.py` that can catch a `c.ListingRefusal` is listed by the AST: one that names SystemExit,
BaseException, ListingRefusal, ListingRefused or Refusal (a ListingRefused is a Refusal), or a bare `except:`. That is
**35 handlers**. `except Exception` cannot catch a SystemExit; those 9 handlers are listed by the runner for
completeness only. For each handler the runner computes whether its `try` body reaches `strict_glob` /
`strict_rglob` / `listing` / `_scan` through the transitive call graph:
- module-qualified calls resolve to that module's function;
- bare names resolve to the same module or a `from` import;
- `obj.f` resolves to every s1 method named `f`;
- functions passed as values count as called.

For a handler found unreachable, the runner also lists every **dynamic call site** in the body's closure: a call
through a parameter, local or callback attribute, which static resolution cannot follow. Each such site is resolved
by hand below. A cruder `--dynamic` mode makes every dynamic site call every escaped function. It reaches everything,
including through CLI entry points, so it proves nothing and is not used for the verdicts.

**Verdict:** exactly one handler turned a listing refusal into a non-refusal outcome that the fix-round-0 table did not
already guard: `s1_gates.run_ack_problems`, fixed in this round. Every other handler re-raises it, holds it, or turns
it into another refusal with no row. Or its `try` body cannot reach an enumeration.

### Handlers whose try body reaches an enumeration (statically)

| handler (fix-round-1 line) | what it does with a ListingRefusal | outcome |
|---|---|---|
| s1_checkpoint.py:376 `except SystemExit: raise` (opening finalizer) | re-raises | refusal |
| s1_checkpoint.py:816 `_opening_stage` `except SystemExit -> {"refused": ...}` | reported refusal | no seal, no row from the observation |
| s1_common.py:575 `verify_bundle_first` registration() `-> err` | held, then `raise err` at the end on every path | refusal (preserved) |
| s1_common.py:579 `_audit_registration` fallback `-> {"stage": None}` | only reached when `err` is set; `err` is always raised at the end | refusal |
| s1_common.py:591 `verify_bundle_first` outer | `record_refusal`, re-raise | refusal (preserved) |
| **s1_gates.py:147/149 `run_ack_problems`** | **fix round 1: `except c.ListingRefusal: raise` ahead of `except SystemExit`** (it was "RUN-ACK unverifiable", which became ABORTED-INVALID in `s1_run._score`) | refusal |
| s1_run.py:912/918 `_score_attempt` | fix round 0: re-raised ahead of the score-abort catch | refusal, no score-aborted |
| s1_slot.py:742 `finalize_close` `except SystemExit: raise` | re-raises | refusal |
| s1_trial.py:487/489 `_opening_derived` opening_slot | fix round 0: re-raised ahead of the "not derivable" catch | refusal |
| s1_trial.py:890 gate `evidence_check` | held until after E5.5 | refusal |
| s1_trial.py:1082 `_plan_after_rows` `except Refusal` around `_legacy_detectors` | the detector's listing refusal (a plain Refusal by then) is swallowed unless the journal holds a TRIAL-INVALID; the gate then commits its OWN stage-replaced INVALID | the INVALID is based on the plan.json damage, confirmed on a re-read before this point, never on the listing (accepted C5.1 precedence: an I/O refusal never masks an unrelated mandatory INVALID) |
| s1_trial.py:1114 `_legacy_detectors` | `record_refusal`, re-raised as a Refusal | refusal (preserved) |

### Handlers whose try body cannot reach an enumeration

| handler | effect if it did catch one | dynamic call sites in the closure, resolved |
|---|---|---|
| s1_checkpoint.py:421 `day_for` -> continue | (skip) | none |
| s1_common.py:531 / :555 RUN-/AUDIT-ACK `mailbox_message` | refusal | none |
| s1_common.py:1148 `_report_seals` | (B3.4 continue) | none |
| s1_gates.py:61 `verify_audit_ack` `mailbox_message` | Invalid | none |
| s1_run.py:540 `_start_attestation_problems` binding | problem | none |
| s1_seal.py:733 / :828 `persist_stop` | refusal | none |
| s1_seal.py:896 `stop_problems` recheck | problem | s1_slot.py:458 `read(path)` in `_classify`: its only callers (s1_slot.py:474, :479, :614, :1062) pass `Path.read_bytes`, `c.sha256_file` or `Path.is_file` of one named path |
| s1_slot.py:152 / :892 `day_for` | skip / "not a registered slot" | none |
| s1_trial.py:495 / :548 `evidence_manifest` | field absent / unreconstructible | s1_trial.py:610 `tree(...)` = `s1_slot.qualified_tree` / `failed_tree` -> `tree_manifest` over named members |
| s1_trial.py:1023 `_journal_invalid`, :834 gate `open_trial` | False / refusal | none |
| s1_trial.py:764 `invalidate_current` (Refusal -> pass) | the caller's local abort | s1_journal.py:413-498 / :541: the TRIAL-INVALID Context is `closed_in` + `recovery` only; no slot/stage/stop callback and no `detail_fn` on that path |
| s1_journal.py:546 `append` `except BaseException` (ROLLBACK, re-raise) | refusal, no row | the ctx callbacks; it re-raises anyway |
| s1_slot.py:808 `run_seal_stage`, s1_stage.py:525 `_resolve` | reported refusal / re-raise | the ctx callbacks; the outcome is a refusal anyway |
| s1_trial.py:895 gate F2.3 recompute | held (it names `c.ListingRefusal`) | the ctx callbacks; held anyway |

### Tests and mutant for I-1
- `test_run_ack_problems_never_turns_a_listing_refusal_into_a_problem`: control `[]`. With os.scandir of the code
  directory failing during that call only: a ListingRefusal.
- `test_score_listing_refusal_in_registration_check_is_no_invalid[control, code-directory-in-run-ack-problems]`: the
  real `_score_attempt` on the `three_qualified` fixture. The fault is active only inside `run_ack_problems`, so the
  score's own earlier bundle listings succeed. Asserted: a ListingRefusal, not StageAbort; no staged s1.json; no
  journal row; no aborted.json. RED on the fix-round-0 tree: a published ABORTED-INVALID with "registration not
  verified: RUN-ACK unverifiable: ... could not be listed".
- Mutant `run-ack-problems-swallows-listing-refusal`, which removes the re-raise, is killed by both tests.
