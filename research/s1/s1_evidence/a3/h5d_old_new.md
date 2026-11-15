# A3 H5d: old / new (H5c review follow-ups: verdict findings 1-7; items 18-22)

Base 2b9beefe514540f8a34efedc2a6447cbe5432e81 (H5c). Only `research/s1/` changes. Frozen docs untouched. Line endings: s1_common.py stays
CRLF (every line CRLF, +2 lines, edited as bytes); every other touched file is LF with 0 CR bytes.

## Product changes (old -> new)
| site | old (2b9beef) | new |
|---|---|---|
| s1_slot.names() (:77) (item 20, verdict f6) | `slot.strftime("%Y%m%dT%H%M%SZ")` on whatever instant the caller passed: an aware non-UTC slot was named by local wall time (only Worker.__init__ normalized) | an aware slot is converted with `slot.astimezone(timezone.utc)` inside names() before formatting. **Naive slots are left exactly as before** (not converted, not refused): every production and test caller passes an aware slot (Worker.slot, `slot_of`/calendar instants, h.slot), so refusing a naive one would add a failure mode with no caller to protect; a naive-slot control test pins the old behaviour. Worker.__init__ keeps its own normalization (now redundant, harmless) |
| s1_common.registration_gate docstring (:1201) (item 19, verdict f1) | said the two `refuse=False` commands "go on and record the trial as ABORTED-INVALID" | adds: once the abort is published; and that if s1_out vanished before the abort is published (OutputRootGone) they refuse too, with "local abort not published: s1_out is gone" (F6.6: no tree to record into), instead of returning the problems. Docstring only; no behaviour change |

## Test changes (old -> new); node ids
| file / node | old | new |
|---|---|---|
| a3_h5afix_child.py (item 18) | `Path(ready).touch()` / `Path(held).touch()` | `_announce(flag)`: writes `os.getpid()` to `<flag>.tmp` and `os.replace`s it onto `<flag>` (atomic: the test never sees an empty flag); docstring updated |
| test_s1_a3_early_refusal_lock.py (item 18) | children spawned with `sys.executable` (Scripts launcher), `.kill()` on failure paths, no pid check | `EXE = sys._base_executable` (fallback sys.executable); new `_assert_child_pid(flag, p)` (the announced pid == Popen.pid); called in Holder.__enter__ (after the held flag, before the test relies on the holder; on mismatch the holder is released and reaped first) and for each writer after its ready flag, before "go". Still `-I` (these children import stdlib + the product dir, passed as argv). Every existing assertion, timeout and poll unchanged; no sleeps or retries added. Nodes: test_concurrent_writers_lose_no_record, test_lock_timeout_records_nothing_and_returns_the_class, test_lock_timeout_worker_refuses_and_discloses_the_gap, test_no_new_file_in_s1_out |
| test_s1_a3_seal_once.py (item 18) | children spawned with `sys.executable -I`, ready flag = "ready" | `EXE = sys._base_executable`; the child writes `os.getpid()` atomically into the ready flag; the test asserts it == Popen.pid right after the barrier and before `h.qualify`/go. These children import conftest (pytest), so the base interpreter needs the venv's site-packages: spawned WITHOUT `-I` (it would ignore PYTHONPATH) and with `child_env()`: PYTHONPATH = product dir, test dir, this interpreter's purelib, passed explicitly (+ PYTHONDONTWRITEBYTECODE). The subprocess.run variant ("intent-before-q-commit-allowed") gets the same exe/env but cannot assert a pid (run() hides the Popen; it has no kill). Node: test_transaction_barrier_around_q_commit[intent-after-q-commit-refused] (pid assert), [intent-before-q-commit-allowed] |
| test_s1_a3_carried_minors.py (item 20) | names() only exercised through Worker | NEW test_names_converts_an_aware_slot_to_utc_directly (-04:00 direct call == the UTC instant's names, every file UTC-named), NEW test_names_keeps_a_naive_slot_as_given |
| test_s1_a3_score.py test_pre_intent_qualified_evidence_is_invalid_when_confirmed (item 21, f7) | no check that the local abort was written | also asserts s1_out/aborted.json: reason == registration-artifact, where == "score", problems == the violation text |
| test_s1_a3_locks.py (item 22, f5) | 14 `pytest.raises` without `match=` (:108 :120 :133 :135 :137 :148 :161 :171 :195 :211 :213 :236 :238 :246) | each carries `match=`: the six LockHeld sites `HELD` (= `held by another process\|byte range locked by another process`, the two s1_locks.py messages); the two remove/rename PermissionErrors `WinError 32`, the replace one `WinError 5` (the Windows text actually raised); the two row-137 LockErrors per damage case (`lock I/O error \(Windows error 5\)` for a directory at the lock path, `lock directory unavailable \(FileExistsError\)` for a file at s1_locks); the two OQ-23 LockErrors `BAD_MSG` (= `lock trial_id is not a uuid4\|is outside the OQ-23 grammar`); the slot subject one `not a slot subject`. Messages were taken from a probe of the real exceptions |

## Findings dispositions (items 21)
| finding | disposition |
|---|---|
| f3 (m1b mislabeled; direct evidence_violation mutant not run) | h5d_mutants.txt m3 runs it: `_pre_intent_qualified` replaced by a direct `evidence_violation` (no re-read, no recomputation): KILLED by test_pre_intent_qualified_evidence_unconfirmed_refuses_with_no_row. The h5c_mutants.txt m1b label is historical evidence and is not edited; the correction is recorded here and in the report |
| f4 (OP-15 control checks gate + _no_local_abort, not a whole command) | reviewer: acceptable as is, covered by rows 425 / 492(b). No change |
| f7 (confirmed-INVALID test lacks the local abort) | test tightened (above); m4 (evidence_violation's write_abort block removed) KILLED by it |
| f2 / f1 / f5 / f6 | items 18 / 19 / 22 / 20 |
| f8 (process breach, disclosed in H5c) | not a product item; the H5d implementer has its own disclosure in the report |
