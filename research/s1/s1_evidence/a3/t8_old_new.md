# Task 8 old -> new

Base 165e0b0. With `s1_stage.ENFORCED = frozenset()` and `s1_stage.SEALS_ENFORCED = False` (transitional), the
gate's new `s1_stage.evaluate(gv)` hook evaluates no TABLE stage and no rowless seal file, so no existing test
changes outcome (t8_full.txt). The only edit to an existing test file:

| file | old | new | class |
|---|---|---|---|
| research/s1/s1_tests/test_s1_t12_a3_a8.py `BUNDLE` | `(..., "s1_snapshot.py", "s1_trial.py")` | `(..., "s1_snapshot.py", "s1_stage.py", "s1_trial.py")` | intended (A3.1: s1_stage.py joins BUNDLE_CODE; the test pins the explicit list and that every s1_*.py is listed) |

New files: research/s1/s1_stage.py, research/s1/s1_tests/a3_helpers.py (test-only helpers and child-process entry
points; not a test module, never imported by product code), research/s1/s1_tests/test_s1_a3_stage.py.

Regressions: none.
