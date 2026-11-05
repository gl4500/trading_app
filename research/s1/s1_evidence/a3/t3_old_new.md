# Task 3 old -> new

## research/s1/s1_tests/test_s1_t12_a3_a8.py (BUNDLE tuple)

Old:
```python
BUNDLE = ("e1_fetch.py", "e1_sim.py", "s1_books.py", "s1_checkpoint.py", "s1_collect.py", "s1_common.py",
          "s1_gates.py", "s1_journal.py", "s1_receipt.py", "s1_run.py", "s1_seal.py", "s1_snapshot.py")
```

New:
```python
BUNDLE = ("e1_fetch.py", "e1_sim.py", "s1_books.py", "s1_checkpoint.py", "s1_collect.py", "s1_common.py",
          "s1_gates.py", "s1_journal.py", "s1_locks.py", "s1_receipt.py", "s1_run.py", "s1_seal.py",
          "s1_snapshot.py")
```

Why: intended semantic change. A3.1's explicit file list gains the new product module s1_locks.py (sorted after
s1_journal.py), mirroring the same edit to s1_common.BUNDLE_CODE. The test's assertions are unchanged
(`tuple(sorted(c.BUNDLE_CODE)) == BUNDLE` and the s1_*.py glob equality); only the expected list grows. RED on the
stub (t3_red.txt: the glob saw s1_locks.py, the tuple did not), GREEN after the edit (t3_green.txt).

## research/s1/s1_tests/test_s1_a3_journal.py

Added one assertion (no existing assertion changed) to test_bundle_pins_addendum3_and_lists_every_new_module:
`assert "s1_locks.py" in c.BUNDLE_CODE` (brief Step 4).

## Other existing tests

See t3_full.txt and the report: no other existing test was edited.
