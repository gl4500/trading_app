# A3 H5c: old / new (T13 N-1 and the carried minors H1 M-1/M-2/M-3/M-5, H2 N-1, H3 M-1/M-2/M-3/M-4, H5a M-2/N-1/M-3, PS-1, H5a-FIX concern 4)

Base 864ecc2aacd7a4c4fce976c78cd09a8d6055753e (H5a-FIX2). Only `research/s1/` changes. Frozen docs (s1_common.DOC_PINS)
untouched. Items 11 and 14 were moved to H5a-FIX (done there) and are not in this task.
Line endings: s1_common.py and s1_checkpoint.py stay CRLF (i/crlf in git, every line CRLF after the edit); every other
touched or new file is LF with 0 CR bytes.

## Product changes (old -> new)
| site (line on the H5c tree) | old (864ecc2) | new |
|---|---|---|
| s1_run.score pre-INTENT block (:805-809) + new `_pre_intent_qualified` (:837) | `except (OSError, ValueError, KeyError, TypeError)` swallowed `s1_slot.QualifiedEvidence` (a ValueError) as "sampled history unreadable (QualifiedEvidence)": the INVALID came one command later | `except s1_slot.QualifiedEvidence` first: the rows are re-read (`j.read_trial`) and `z.sampled_seals` recomputed once over them (I-1). Confirmed -> `s1_slot.evidence_violation(gv, ..., "score", ...)`: TRIAL-INVALID (registration-artifact), then the local abort while s1_out exists. Clean recomputation -> "score refused: a QUALIFIED tree problem was not confirmed on a re-read: refused with no row". OSError / JournalError (or another error) on the re-read -> "... could not be re-read (<type>): refused with no row (I-4)". `QualifiedUnreadable` and `ListingRefusal` (SystemExits) are not caught anywhere in the new code |
| s1_checkpoint._qualified_violation `finally:` (:513-519) | `c.write_abort` in the `finally:`: an OutputRootGone (FileNotFoundError) replaced the invalidate Refusal | the write is wrapped `try/except c.OutputRootGone: pass` (as evidence_violation): the journal-down Refusal, or after a committed INVALID the "seal selection refused ...: INVALID (registration-artifact)" SystemExit, surfaces |
| s1_slot.Worker.violation `finally:` (:523-527) | same masking through `ck._write_abort` | same wrap; after a committed INVALID `violation()` returns (its caller's display path) |
| s1_checkpoint._before_opening_seal (:744-753) | OutputRootGone escaped instead of `_OpeningSealConflict` | `_OpeningSealConflict("<the site's own text> (local abort not published: s1_out is gone)")` |
| s1_common.bundle_gate (:409-421) | OutputRootGone escaped instead of its SystemExit | its SystemExit text + " (local abort not published: s1_out is gone)" |
| s1_common.registration_gate (:1232-1246) | OutputRootGone escaped instead of its SystemExit (after invalidate_current) | its SystemExit text + the same suffix; **decision:** also for the recording commands (`refuse=False`): with s1_out gone there is no tree to record ABORTED-INVALID into, so the gate refuses (fail closed) instead of returning the problems |
| s1_common.record_refusal (:622-634) | `out.mkdir(parents=True, exist_ok=True)` behind the callers' check-then-act `is_dir()` guard: a vanished s1_out was RECREATED and refusals.jsonl written into it (destroying the F6.6 total-loss evidence) | no mkdir: appended only into an existing s1_out; a FileNotFoundError (root missing or vanished) prints "S1 <where> refusal not recorded (s1_out absent): <text>" to stderr; the refusal stands. `import sys` added. Pre-s1_out callers: verify_bundle_first / verified_registration / s1_trial._record / _legacy_detectors; the full suite (h5c_full.txt) found no caller that relies on the mkdir |
| s1_slot.Worker.__init__ (:383-384) | `self.slot = slot` as given: names(), the claim, the capture dir and late/ used the caller's wall time (`strftime(...Z)` without a conversion) | **decision (controller ruling): normalize, never refuse** - an aware slot becomes `slot.astimezone(timezone.utc)`; a naive one is left as before. names(), the claim's `scheduled`, the QUALIFIED tree and late/<day>/<slot> are UTC wall time. The CLI already normalizes (`c.aware`), so production entries are unaffected |

## Test changes (old -> new); node ids
| file | old | new |
|---|---|---|
| test_s1_a3_score.py | - | + `test_pre_intent_qualified_evidence_is_invalid_when_confirmed`, `test_pre_intent_qualified_evidence_unconfirmed_refuses_with_no_row`, `test_pre_intent_qualified_evidence_reread_failure_refuses_with_no_row[oserror-recompute\|journal-reread]` (4 nodes). The existing `test_pre_intent_sampled_history_error_is_a_refusal_not_a_traceback[ValueError]` keeps its outcome (a plain ValueError is not QualifiedEvidence) |
| test_s1_a3_carried_minors.py (new, LF) | - | `test_write_abort_callers_root_gone_keeps_the_original_outcome[8 sites]`, `test_record_refusal_never_creates_s1_out[2]`, `test_record_refusal_appends_into_an_existing_root`, `test_non_utc_slot_names_files_by_utc_wall_time`, `test_non_utc_slot_late_paths_use_utc_wall_time` (13 nodes) |
| test_s1_a3_abort_recovery.py | row 462 same-witness: `[release(a), release(b)]` (b released only after a exited) | `release_together([a, b])`: both stdins written before either output is read (H1 M-5); outcome unchanged. + `test_witness_before_any_journal_row_stays_command_local` (OP-15, H1 M-3; 1 node) |
| test_s1_a3_close.py | row 484: 2 cases | + `test_first_valid_close_monotone[duplicate-after-closure]` (H2 N-1; 1 node); the shared final oracle now prints `tr.problems` on failure |
| test_s1_a3_prestart.py | row 491: `all(x is clk ... if n == "append" and x is not None)` | `appends and all(x is clk for x in appends)` (H3 M-1, oracle only; no node change) |
| test_s1_a3_wpend.py | row 420: `kinds(...) in (["SLOT-MISSED"], [])`; `test_ordinary_early_slot_oq33_unchanged` | row 420: `== ["SLOT-MISSED"]`; + `test_registered_slot_after_w_last_never_routes[first-registered-slot-after-w-last]` (H3 M-2; 1 node); **renamed** `test_ordinary_early_slot_oq33_unchanged` -> `test_ordinary_early_slot_refused_by_c4_never_routed` (H5a N-1: the node id changes; body unchanged, docstring added) |
| test_s1_a3_eligibility.py | row 511: `h.attempt(...)` result discarded | `got == ("refused", "<subject>: SLOT-INTENT refused with no row: " + h.c2_text(D130))` (H5a M-2) |
| test_s1_a3_seal_once.py | row 529[refusal-runs-no-finalizer]: result discarded | `got == ("refused", ... + h.c3_text(D0, s[47]))` (H5a M-2) |
| test_s1_a3_locks.py | children spawned with `sys.executable` (the venv Scripts launcher: Popen.pid is the launcher, the holder a grandchild); handshake "acquired"/"held"/"opened" | spawned with `sys._base_executable` (fallback sys.executable); every handshake line carries `os.getpid()` and `handshake()` asserts it equals `Popen.pid` before any kill/wait; `child()` stops (stdin EOF) a child whose handshake fails. Held control, immediate post-wait reacquisition, timeouts and every other assertion unchanged; no sleeps or retries (PS-1) |

Node count: 5701 (base) + 4 + 13 + 1 + 1 + 1 = **5721**; one rename (count unchanged).

## Evidence corrections
- H3 M-4: `tH3_red_labels_correction_20261115.md` (new, dated) corrects the false "every retro row has a killed
  mutant" sentence; tH3_red_labels.md itself is untouched (its tH3_hashes.txt sha256 still holds).

## Process notes (disclosed)
- **s1_common.py line endings.** A `sed -i` edit attempt in git-bash rewrote s1_common.py with LF line endings (whole
  file). It was detected before the mutant run of record (the first mutant run on that LF copy is superseded and
  not evidence) and normalized back to CRLF on every line with a byte-level script (git: `i/crlf w/crlf`;
  `git diff --numstat` 27/15, no whole-file churn). h5c_green.txt (414 passed) ran on the LF-only bytes of the same
  text; h5c_mutants.txt and h5c_full.txt ran on the final CRLF bytes.
- **After GREEN, test-only:** row 484's shared final oracle became `tr.closed is not None and ...` (an AssertionError
  instead of an AttributeError when a mutant re-opens the trial), so the m6 kill is B3. Covered by h5c_mutants.txt
  (baseline 26 passed) and h5c_full.txt.
