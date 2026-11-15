# A3 H5a-FIX: old / new (Codex exact-head review of ce4a53b, H5A-CX-1 / P2; H5a M-1)

Base 0eaadaed69dc856661dc20befc2b96e72a430c3a (H4-CX on H5a). Only `research/s1/` changes. Frozen docs untouched.
Product file: `s1_slot.py` (LF, kept LF). New test files: `s1_tests/test_s1_a3_early_refusal_lock.py`,
`s1_tests/a3_h5afix_child.py` (the child-process script the tests run; not collected - no `test_` prefix). Both LF.

| observation | old (0eaadae / ce4a53b) | new (H5a-FIX) |
|---|---|---|
| 4 processes x 100 concurrent `record_early_refusal` calls, one `s1_out/early_refusals.jsonl` | every call returns None (recorded); 330 valid unique lines of 400 in the RED run (Codex: 355, 353; controller: 346 + 3 torn, 337 + 2 torn) | 400 claimed, 400 lines, 400 valid unique, 0 unparseable, in every one of 8 GREEN runs + the file run (h5afix_green.txt) |
| cross-process serialization | none: text-mode `open(..., "a")`, CRT O_APPEND seek-then-write | `msvcrt.locking` (LK_NBLCK, polled) on a fixed 1-byte region at `EARLY_LOCK_OFFSET = 0x7FFFFFF0` of the jsonl itself, held across seek-to-end, the write of the whole encoded line, and `os.fsync`; released after |
| lock held while writing / fsyncing (a second handle tries the region) | not held | held at the (single) write and at the fsync; free after the call |
| another process holds the region | records (returns None): no lock exists | returns `"LockTimeout"` after `EARLY_LOCK_WAIT_S = 2.0` s; the file is byte-identical; the next call after release records |
| worker, region held, early sample | "early-refusal diagnostic recorded" | refuses with the pinned C4 reason, no journal row, no claim/capture/work, text "early-refusal diagnostic NOT recorded (LockTimeout): recording gap (Clarification 4 C4.3.4)" |
| s1_out missing / an ancestor missing | FileNotFoundError, nothing created | unchanged (FileNotFoundError, nothing created: no directory, no jsonl, no lock file) |
| files in s1_out after a record and a timeout | the jsonl | the jsonl only (no lock file) |
| a failed write / fsync after the lock | (a torn partial line could remain) | the file is truncated back to its end before this call, under the lock (best effort), and the class is returned |
| non-Windows | appended without serialization | `"LockUnavailable"`: fail closed, gap disclosed (the S1 trial is Windows-only, as s1_locks) |
| line bytes | `json.dumps(rec, sort_keys=True)` + text-mode `"\n"` = `"\r\n"` on Windows | the same bytes, encoded explicitly (`+ "\r\n"`, UTF-8; json.dumps is ASCII) |
| M-1: a direct caller passes the slot as aware -04:00 | `_early_note` compares against `self.slot.isoformat()` (`...-04:00`) != the journal's UTC reason: `''` - nothing recorded and no gap stated | the reason is matched against `j.C4_REASON.format(slot=j.slot_instant(self.subject).isoformat())`; the record's `scheduled` is that UTC instant; the diagnostic is recorded, or on a write failure the gap is disclosed |
| UTC slot callers (CLI, every existing test) | `scheduled` = `self.slot.isoformat()` | identical value (`slot_instant(subject)` equals a whole-second UTC slot) |

## Decisions and justifications
1. **Shape: an OS lock on the file, not a native append handle.** The brief accepts either; a single `os.write`/O_APPEND
   atomicity claim is not accepted on assumption, and the CRT's O_APPEND is seek-then-write. `msvcrt.locking` is the
   same primitive s1_locks already relies on (Windows LockFile byte-range locks are mandatory and process-owned; a
   second handle, even in the same process, cannot lock the region while it is held - which the
   held-across-write test uses as its probe). It is verified on this host by the 4 x 100 concurrency test (8 + 1
   GREEN runs) and by the deterministic held-at-write/held-at-fsync test.
2. **The lock is a region of the jsonl itself (no lock file).** Controller context: no product pattern lists files at
   the s1_out root (every `c.listing`/`c.strict_glob` pattern's first segment is a literal subdirectory: `captures/`,
   `seals/`, `<stage>/`; checked by grep at the base: s1_checkpoint 75/958/967, s1_common 205/767/780/781/834/836/948/
   1176, s1_run 676/1004/1196/1207, s1_seal 109/392/423/848, s1_stage 539/590, s1_slot 1016/1050/1132/1179), so the
   jsonl stays outside every inventory/hash/F3/F4 table, and locking the file itself adds nothing to s1_out at all
   (`test_no_new_file_in_s1_out`). The jsonl is created by `open(..., "ab")` exactly as before (no directory).
3. **Region placement.** Offset 0x7FFFFFF0 (< 2^31, safe for the CRT `_locking` offset on any build) lies far past any
   realistic end of the file, so the locked byte is never read or written: readers of the jsonl are never blocked by
   the mandatory lock, and writes (always at the end, by the lock holder) never touch it.
4. **Bound: `EARLY_LOCK_WAIT_S = 2.0` s, polled every 5 ms.** The critical section is one write of a ~250-byte line
   and one fsync (single-digit ms here: 400 serialized calls in under 1 s wall including process start), and at most a
   handful of slot workers ever contend (the registered slots of one close are minutes apart; the race is only between
   retries/overlapping invocations). 2 s is >100x the expected wait yet keeps a worker's refusal prompt; well under the
   5 s ceiling the test asserts. On the bound: nothing recorded, `"LockTimeout"` (controller ruling), the worker's
   refusal text discloses the gap. `msvcrt.LK_LOCK` was rejected: its fixed 10 x 1 s retry is not our bound.
5. **Never raises out of the worker.** `LockTimeout` and `LockUnavailable` subclass OSError, so the single existing
   `except OSError` returns the class; the unlock swallows its own OSError (closing the handle releases the region) so
   a durable, fsynced line is never reported as a gap.
6. **M-1 option chosen:** match against `j.slot_instant(self.subject)` (option 1), not normalizing `self.slot` in
   `Worker.__init__`: the narrower change; normalizing would also alter the claim's `scheduled` text and `names()` for
   non-UTC callers, outside this task's scope. (Disclosed, not fixed here: `names()` formats `slot.strftime(...Z)`
   without converting to UTC, so a non-UTC direct caller that gets PAST the early refusal would name its files from
   local wall time. The early refusal path writes no such file. Recorded as a carried observation for H5c/Codex.)
7. **Refusal semantics unchanged (outcome 5).** `_early_note` still only builds text; the SystemExit, no journal row,
   no claim and no capture are untouched (asserted again by the LockTimeout worker test and the -04:00 test).

## Tests (all in `s1_tests/test_s1_a3_early_refusal_lock.py`)
- `test_concurrent_writers_lose_no_record` - outcome 1/2 (RED: claimed=400 valid_unique=330)
- `test_lock_held_across_write_and_fsync` - outcome 2 (RED: write not under a lock, no fsync)
- `test_lock_timeout_records_nothing_and_returns_the_class` - outcome 3 (RED: None)
- `test_lock_timeout_worker_refuses_and_discloses_the_gap` - outcome 3/5 (RED: "diagnostic recorded")
- `test_missing_root_is_never_created[root-missing|ancestor-missing]` - outcome 4 controls (green on base and after)
- `test_no_new_file_in_s1_out` - outcome 4 (RED: the timeout half returned None)
- `test_non_utc_slot_diagnostic[diagnostic-recorded|gap-disclosed]` - outcome 6 (RED: no diagnostic text, no gap)
- Existing C4.3 controls unchanged and green: `test_s1_a3_intent_lower_bound.py::test_early_refusal_diagnostics[*]`
  (records-slot-sample-reason, no-journal-row, no-claim-no-capture, missing-root-not-recreated,
  diagnostic-write-failure-still-refuses-and-discloses-gap).

## Fix round 1 (2026-11-15; independent review verdict I-1 and m-1; tests only, product unchanged)
`s1_slot.py` is unchanged (sha256 16d33a03c4f877405d77ba9c452b6a16e45be4bdb2c5915492f58d6caf4bb6b0). Four test nodes
were added to `s1_tests/test_s1_a3_early_refusal_lock.py`, taking it from 9 to 13:

| observation (the product already behaves this way; now pinned) | killing mutant |
|---|---|
| `test_write_or_fsync_failure_rolls_back[partial-write-failure]`: 7 bytes written, then ENOSPC. Returns "OSError", the file is byte-identical, the region is free, and the next call gives 2 parseable lines (0 torn) | no-ftruncate |
| `test_write_or_fsync_failure_rolls_back[fsync-failure]`: the fsync raises EIO. Same assertions (the written line is truncated back) | no-ftruncate |
| `test_short_writes_complete_one_line`: at most 7 bytes per write call. The line completes under the lock, with more than one write call and one parseable line | short-write-not-completed |
| `test_region_unlocked_before_the_handle_closes`: at the product's `with` exit, with the writer's fd still open, a fresh handle locks the region at once (LK_NBLCK). Deterministic | wrong-unlock-offset |

- RED is a mutant-kill RED, stated explicitly: the product is already correct, so each new node's RED is its failing
  assertion against the mutant that removes the behaviour. Evidence is in h5afix_red.txt and h5afix_mutants.txt.
- Mutants: the whole runner was re-run, with 8/8 KILLED (the 5 of round 0 plus no-ftruncate, wrong-unlock-offset and
  short-write-not-completed).
- Full-suite count, by controller ruling: there was no re-run because product code is unchanged. The count is now
  5650 (h5afix_full.txt, round 0) + 4 = **5654**. The evidence for the 4 new nodes is the focused run of the whole new
  file, 13 passed (h5afix_green.txt, "FIX ROUND 1 GREEN"). It was not executed as part of a full-suite run.
- Review m-2 (`names()` and the late/ destinations for a non-UTC slot) is not in this task; it is H5c item 17.
