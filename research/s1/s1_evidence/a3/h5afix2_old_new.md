# A3 H5a-FIX2: old / new (Codex exact-head review of a42ea8b, X-15 / H5AFIX-CX-1, P2)

Base 655fc89a989cdd3f4366d911b24e5234d1d0f96d (H4-CX fix2 on H5a-FIX a42ea8b). Only `research/s1/` changes. Frozen
docs untouched. Product: `s1_slot.py` (LF, kept LF). New test file: `s1_tests/test_s1_a3_early_refusal_tail.py`
(19 nodes after fix round 1, LF).
Review: `C:/Users/gl450/.coordination/trading_app/h5afix_a42ea8b_review_20261115/review_v1.txt`, sha256
a31d8f797a1ba31d6c89dacc349f3cdca3140a24cfcf5b3481433e80473ac0de. Its probe_torn_tail.py was not run.

| observation | old (655fc89 = a42ea8b's s1_slot) | new (H5a-FIX2) |
|---|---|---|
| Codex two-call regression: record 1; record 2 makes a 7-byte partial write AND its rollback ftruncate fails; record 3 is healthy | 1 None, 2 "OSError", 3 **None**, but record 3 is concatenated onto the torn 7 bytes and is unparseable: only record 1 is valid (RED) | 1 None, 2 "OSError", 3 None. Records 1 and 3 parse with both readers; the fragment is the only unparseable line; record 1's bytes and the fragment are untouched |
| tail = no terminator (`...{"reason": "slot 20`) | line glued to the fragment | `\r\n` + line |
| tail = lone CR | `...\r` + line: one line for an LF reader, a glued fragment | `\n` + line (the CR is completed to CRLF) |
| tail = lone LF | line (already clean) | line (unchanged) |
| file = `\r` only | glued | `\n` + line |
| file = `\n` only | line | line (unchanged) |
| empty file / absent file / healthy file | line | line, byte for byte (no completion added) |
| reading the tail fails (EIO) | (no read: None) | "OSError", nothing written, file byte-identical; the next call records |
| open mode | `"ab"`, buffering 0 | `"a+b"`, buffering 0: append + read. It is created when absent exactly as before (O_CREAT, never a directory); writes still always go to EOF (O_APPEND) |
| 4 x 100 concurrency | 400/400 | 400/400 in all 6 runs (h5afix2_green.txt) |

## Decisions and justifications
1. **Handle it, do not refuse** (controller ruling). The tail is read and completed under the same lock and on the
   same fd, after the seek to end and before the single write of `completion + line`. Holding the lock means no other
   writer can change the tail between the read and the write.
2. **The completion rule decides by the last byte only.** No terminator: `b"\r\n"`. A lone `b"\r"`: `b"\n"`. A
   `b"\n"`, or an empty file: nothing.
   - This is the minimal completion. It never adds a blank line, which matters because a strict reader that
     splits on a lone CR (`str.splitlines`, as `test_s1_a3_intent_lower_bound.diag_lines` does) would otherwise see
     an empty line and fail.
   - Given the controller's literal shape (prefix `\r\n` whenever the file does not end with `\r\n`), a lone `\n`
     tail would get `\n\r\n`, and a lone `\r` would get `\r\r\n`. Both create a blank line for splitlines readers. So
     for those two tails I chose the minimal completion, and I disclose the deviation here.
   - The lone-LF and lone-CR outcomes are pinned byte-for-byte by `test_tail_completion`. The
     `lone-cr-gets-full-crlf` mutant is killed.
3. **Never delete or rewrite.** The file after the call is always exactly the old bytes + the completion + the line,
   asserted byte for byte. The `tail-check-deletes-the-fragment` mutant is killed. The torn fragment stays as
   historical evidence. It is a disclosed gap only when it came from one of OUR failed returns. A killed process or
   other pre-existing corruption may never have disclosed its gap, and nothing here claims that it did.
4. **A tail-read failure is a gap, not a guess.** lseek or read raising, or a short read, produces an OSError, which
   comes back as its class. Nothing has been written at that point, so there is nothing to roll back.
5. **Rollback is still best effort.** A failed write or fsync of `completion + line` truncates back to `end`, so this
   call's completion is removed too. If that truncate also fails, the next call completes the tail.
6. **The completion is part of the one write** (`test_lock_held_across_write_and_fsync` still asserts exactly one
   write call for a healthy file).

## Tests
- `test_fault_then_recovery_keeps_every_claimed_record`: the Codex regression (RED: record 3 lost).
- `test_tail_completion[absent-file|empty-file|healthy-file|no-terminator|lone-cr|lone-lf|bare-cr|bare-lf]`. Five are
  controls that are green on the base (absent, empty, healthy, lone-lf, bare-lf); three are RED on the base
  (no-terminator, lone-cr, bare-cr). Each also asserts that a following call adds no completion.
- `test_tail_read_failure_returns_the_class` (RED: None).
- The existing 13 lock tests and 34 C4.3 tests are unchanged and green.

## Mutants (h5afix2_mutants.txt): 13/13 KILLED
The new ones:
- no-tail-check;
- tail-check-deletes-the-fragment;
- completion-outside-the-rollback (the completion is written separately and left out of the rollback point);
- completion-applied-unconditionally (it breaks the healthy byte-for-byte case);
- lone-cr-gets-full-crlf.

The other 8 are H5a-FIX round 1's, re-run. A 12-mutant run before the addendum (12/12) is superseded.

## Codex addendum (CONSENSUS on the repair design, not code approval), folded in
1. **Same lock, same handle.** The tail is inspected and the completion prefixed under the one lock, on the one
   read-capable fd: `open(..., "a+b", buffering=0)`. `"ab"` is write-only. Creation behaviour is unchanged: O_CREAT
   creates the file when it is absent, the directory is never created, and every write goes to EOF (O_APPEND).
2. **Failure classes.** A tail-read failure (`test_tail_read_failure_returns_the_class`), a failure in the completion
   itself, a write failure and an fsync failure (`test_write_or_fsync_failure_rolls_back`, lock file) each return
   their class.
3. **Extra tests:**
   - `test_failure_during_the_completion_rolls_back[before-any-byte|inside-the-completion]`: the failure class and a
     byte-identical file. The next call adds exactly `\r\n` + its line.
   - `test_short_writes_through_the_completion`: 1 byte per write call, starting inside the completion. The result
     is exactly the old bytes + `\r\n` + the line.
   - `test_inherited_tail_failed_rollback_then_success[torn-inside-the-completion|torn-after-the-completion]`: an
     inherited torn tail, then a failing call (1 or 5 bytes) whose rollback also fails, then a healthy None. Every
     file is a prefix of the next, so every prior byte is preserved, and the expected bytes are exact. The new record
     is its own line and parses with both readers.
4. **Exact lone-LF bytes.** For `HEALTHY + b'{"reason": "slot 20\n'` the call appends exactly the line, with no
   completion (`test_tail_completion[lone-lf]`), and for a bare `b"\n"` file likewise. A healthy CRLF-terminated file
   is unchanged apart from the appended line (`[healthy-file]`, byte for byte).
5. **Wording.** The docstrings (`s1_slot._tail_completion`, the test module) and this file say a fragment is
   "disclosed" only for our own failed-return case; no claim is made for a killed process or arbitrary corruption.
   The product edit for this is docstring only, and the logic is identical to the pre-addendum GREEN.

## Fix round 1 (2026-11-15; independent review verdict findings 1-4)
- **Finding 1 (Material), tail read under the lock.** New test
  `test_tail_read_happens_under_the_lock_on_the_products_fd`. It spies `os.read` during a real call and checks three
  things: the tail byte is read exactly once, it is read on the product's own fd (captured by spying `sl.open`), and
  at that moment a second handle fails to lock the region at `EARLY_LOCK_OFFSET` with LK_NBLCK.
  - Why this probe: Windows byte-range locks conflict across handles even within one process. That is the same
    deterministic probe the lock file's held-across-write test already uses, so no extra process or timing is needed.
  - The reviewer's mutant B is `tail-read-before-lock` (same fd, tail read moved above `_lock_diag`). It survived the
    62 earlier focused tests. It is now in the runner and KILLED by this test, with an assertion failure (`held`
    False). That kill is this test's RED (B3): the product was already correct.
- **Finding 2 (Minor), wording.** A fragment becomes its own line, usually unparseable. A fragment missing only its
  terminator, from a failed call that wrote all but the last 1-2 bytes and whose rollback also failed, becomes a
  VALID record whose call still returned its failure class. That is over-disclosure (a reported gap whose record
  nevertheless exists), never loss.
  - Now pinned by `test_terminator_only_fragment_becomes_a_valid_over_disclosed_record[all-but-lf|all-but-crlf]`:
    3 valid records and 0 unparseable lines, under both readers.
  - The wording is corrected in `s1_slot._tail_completion` and in the test module docstring. It supersedes the
    "becomes its own unparseable line" wording in decision 2 above and in the report's concern 2.
- **Finding 3 (Nit), short read.** New test `test_tail_short_read_returns_the_class`: `os.read` returns `b""`, the
  call returns "OSError", and the file is byte-identical. Mutant `short-read-branch-removed` is KILLED.
- **Finding 4 (Nit), whitespace.** `line =(json.dumps(` is reverted to `line = (json.dumps(`. The diff no longer
  touches that line.
- **Product change in this round:** docstring and whitespace only; the logic is identical. By controller ruling there
  was no full-suite re-run. The count is 5697 (h5afix2_full.txt) + 4 = 5701, and the evidence for the 4 new nodes is
  the focused run.
