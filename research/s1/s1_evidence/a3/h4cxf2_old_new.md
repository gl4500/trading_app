# A3 H4-CX fix2 (Codex X-13): overflow-safe arithmetic in s1_evidence/a3/m4_workload/verdict_rule.py

Base a42ea8b826b0b19da84738397b7ab15ebd92094d. Changed: verdict_rule.py, test_s1_a3_m4_workload_verdict.py (LF kept,
0 CR), new evidence h4cxf2_*. Frozen docs, historical evidence, CAP untouched. No workload re-run.

| input (each value individually valid) | old | new |
|---|---|---|
| verdict `[L=10**308, T=10**308]` | OverflowError (L + T exact int, math.isfinite) | NOT READY "run ovf: C = L + T overflows the float range (L = ..., T = ...)"; run left out of max_C |
| verdict L=1e308, T=1e308 (sum inf) | NOT READY "C = L + T not finite" | NOT READY, same shape of reason, now naming L and T |
| b_conditional `T=B=10**308` | OverflowError | B-CONDITIONAL NOT READY "max(T) + B overflows the float range (...)", max_T_plus_B None |
| b_conditional max(T)=B=1e308 (float sum inf) | label with `max_T + b` = inf, `:.3f` of inf, "inf > 60" reason | NOT READY "max(T) + B not finite", max_T_plus_B None |
| cap = 10**400 / 10**5000, small values | NOT READY "cap invalid" (fix round 1) - but 10**5000 raised ValueError in repr | NOT READY "cap invalid", never raises |
| cap = 10**308 (float-representable), small values | READY | READY (exact comparison; `:g` safe) |
| any invalid value that is a >4300-digit int | ValueError from `repr()` inside the reason | reason uses `_r` (`<int of N bits>`), never raises |
| ordinary values (L=20, T=45; T=50, B=10) | unchanged | unchanged ("65.000 s > 60 s"; READY, max_T_plus_B 60.0) |

## Decisions
- `_add(a, b)` returns the EXACT sum (int stays int) when `math.isfinite` holds, else `(None, "overflows the float range" |
  "not finite")`. Every `:.3f` / `:g` / comparison in the module runs only on a value that passed `_add` or `_real`.
- max_C: an overflowing C is excluded, so max_C is the max over the runs whose C is defined, or None if none is.
  max_T: unchanged (exact valid values, so `max_T` may be a huge int such as 10**308 - exact, not None).
  max_T_plus_B: None when the sum is unusable (overflow, inf), the exact sum otherwise.
- Never READY on an overflow: the reason is appended, so verdict/label is NOT READY / B-CONDITIONAL NOT READY.
- A transient probe `f"{s:.3f}"` inside `_add` was dropped: `math.isfinite` already raises for every int that the
  format would reject, so the probe was an equivalent mutant (SURVIVED the first mutant run).

## Historical (32 recorded run JSONs, scratchpad h4cxf2/recompute.py; no workload re-run)
old (a42ea8b) and new are identical: verdict(workloads_resolved=False) NOT READY max_T 373.70092279976234 max_C
373.7011571652256, 23 reasons; verdict(...) NOT READY, 22 reasons; b_conditional(runs, None) NOT READY, 3 reasons.

## Importers (grep -rl verdict_rule --include=*.py)
`m4_workload/driver.py` (offline measurement driver; imports verdict_rule), `s1_tests/test_s1_a3_m4_workload_verdict.py`,
`s1_tests/test_s1_a3_strict_enum.py` (loads it by path for the M-1 huge-int test). No backend/product importer.
Hence the focused run (verdict test + strict_enum test, 127 passed) instead of the whole suite. driver.py's calls
(`b_conditional`, summarize) are signature-compatible: no signature changed.

## Evidence
h4cxf2_red.txt (9 failed, all AssertionError, 35 passed, against the base product + new tests), h4cxf2_green.txt
(127 passed), h4cxf2_mutants.txt (4 mutants, all KILLED), h4cxf2_hashes.txt.

## Fix round 1 (review verdict task-H4CXfix2-review-verdict.md: SPEC PASS, 3 minors)

| finding | old (fix2 round 0) | new | test / mutant |
|---|---|---|---|
| M-1 `_r` | fallback called `x.bit_length()`: T/B/cap = `[10**5000]` (any non-int whose repr raises) -> AttributeError | `except Exception` -> `<unprintable TypeName>`; the text is capped at 200 chars + "..." (a 10**6-char str / bytes value no longer floods a reason) | `test_unprintable_or_container_values_never_raise_in_reasons[7]`; mutants `repr-guard-removed`, `fr1-r-catches-only-valueerror`, `fr1-text-uncapped` |
| M-2 run id | `f"run {id}"` -> ValueError for a >4300-digit int id (and any raising `__str__`) | ids go through `_s`: a `str` verbatim (capped), anything else through `_r`; str ids print exactly as before | `test_run_id_of_any_type_never_raises[5]`, `test_run_id_text_unchanged_for_strings`; mutant `fr1-run-id-raw-str` |
| M-3 fixed-width ints | `np.int64(2**62)` twice: sum wraps negative, READY with max_C = -2**63 | CHOICE: strict rejection (fail closed). `_real` accepts only the exact builtin types `int` and `float` (`type(x) in (int, float)`); numpy scalars and every int/float subclass (which can override `+`) are an invalid value -> NOT READY naming the run / B / cap. Conversion via int()/float() was not chosen: it would silently accept values the caller never validated and it cannot recognise a wrapped sum after the fact | `test_numpy_fixed_width_ints_fail_closed_never_ready` (numpy 2.2.6 IS importable in the testenv), `test_int_subclass_with_wrapping_add_...` (a wrapping int subclass), `test_builtin_int_and_float_still_accepted`; mutants `fr1-real-accepts-numpy-ints`, `fr1-real-accepts-int-subclasses` |

Consequence of M-3: bool stays rejected (type is bool, not int); Fraction/Decimal, previously `numbers.Real`, are now invalid too
(they were never produced by the JSON-fed driver; no recorded value changes). The `numbers` import is gone.

Evidence: RED 11 failed / 49 passed (all AssertionError, base = fix2 round 0 + new tests); GREEN 143 passed (verdict file 60 +
strict_enum 83; the importers are the verdict test, strict_enum and driver.py - no product importer); 9/9 mutants KILLED;
historical recompute over the 32 recorded runs unchanged (NOT READY, max_T 373.70092279976234, max_C 373.7011571652256).
