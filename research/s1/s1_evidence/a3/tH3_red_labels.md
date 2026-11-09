# A3 H3 RED labels (tH3_red.txt)

51 instances (test_s1_a3_wpend.py: 31 = rows 410-426 (29) + T11 N1 + row 495; test_s1_a3_prestart.py: 20 = rows
491-494, selected by `-k "wpend or opening_finalizer_helper"`) against the H3 Step-1 interface stub: a clean export of HEAD e9bc6c0 (`git archive HEAD research/s1`) plus the additive
stub edits of scratchpad `tH3/mk_stub.py` (`_w_last` real, `_w_last_route` defined and unused, `_opening_close_row`
real, `finalize_opening` delegating to the frozen wrapper `finalize_close(out, day, cal, now(), ...)` at an
invocation-start instant; wrappers present; `run_finalizer` without the abort refusal; `main` unchanged; conftest =
HEAD's). The test files are the final H3 test files.

**Result: 15 failed, 36 passed.** No ImportError, AttributeError, collection error or fixture error. Every failure is
an `AssertionError` or a pytest `Failed` (including `ok()`'s `pytest.fail` on a refusal the route must not give, and
pytest.raises' `DID NOT RAISE` / `Regex pattern did not match`) at the test's own oracle line (ruling B3).

| row | instance | label | why (stub) | discriminating mutant (tH3_mutants.txt) |
|---|---|---|---|---|
| 410 | pins_clock_and_no_live_callback | **RED** | `ok()` Failed: the W_L invocation takes the worker path - "a restart never re-intents" | r6 (frozen route clock) |
| 411 | no-trial, forged-auth, registered-bundle-changed, invalid, closed, registration-artifact, unregistered-slot | `retro` x7 | the identity refusals exist today; the route does not exist | r1 (route before the registration) |
| 412 | non-w-after-e, injected-systemexit | `retro` x2 | no route exists to launder a refusal | r2 (widened predicate), r3 (route catches _close_for) |
| 413 | route-at-w | **RED** | `ok()` Failed (worker path) | - |
| 413 | catchup-at-d-minus-1us | **RED** | its first step is the route at W: `ok()` Failed (plan said `retro`; the catch-up half alone is retro) | - |
| 414 | nvs, timeout | `retro` x2 | the catch-up (run_finalizer) exists since Task 11 fix round 1 | - |
| 415 | held_worker_cannot_block_timeout | `retro` | catch-up | - |
| 416 | no-due-rows, post-stop-timeout | **RED** x2 | `ok()` Failed on the route (plan listed only post-stop-timeout; both interleave routes) | - |
| 417 | no-intent, early-intent | `retro` x2 | catch-up | - |
| 418 | early_claim_restart_refusal | **RED** | `ok()` Failed on the route half | - |
| 419 | late_scheduler_invocation | **RED** | `ok()` Failed: "now >= E" | r6 |
| 420 | no_window_extension | **RED** | ordinary half passes; the W_L-exempt half: `ok()` Failed "now >= E" | r2 |
| 421 | early_w_last_route_no_attempt | **RED** | AssertionError: `['SLOT-INTENT', 'SLOT-FAILED'] == []` (OQ-33 on the stub) | - |
| 422 | ordinary_early_slot_oq33_unchanged | `ctrl` | OQ-33 unchanged | - |
| 423 | earlier_lots_stop_with_pending_w_last | `retro` | catch-up | - |
| 424 | pre_stop_intent_late_completion | `retro` | F1 completion exists | - |
| 425 | route | `retro` | the worker path's `_no_local_abort` refuses both sub-cases | r4 (route before `_no_local_abort`) |
| 425 | finalizer | **RED** | `DID NOT RAISE`: run_finalizer has no abort refusal (after-gate sub-case) | r5 |
| 426 | frozen_wrappers_retired | **RED** | AssertionError: the wrappers exist | - |
| T11 N1 | finalize_cli_dispatch_pins_the_clock_callable | **RED** | AssertionError: `None is <sentinel>` (main passes no `now`) | - |
| 495 | no_new_cli_mode | `retro` | four modes today | o6a (`--finalize-opening`), o6b (`--finalize` reaches the opening close) |
| 491 | same_clock_callable | **RED** | AssertionError (`assert False`): the stub hands `lambda: t` to the gate/stage, not the callable | - |
| 492 | local-abort | **RED** | after-gate sub-case: no abort refusal in the stub; the delegate reaches the (mocked) finalizer and fails F0.7 - `Regex pattern did not match` (plan said `retro`; H3 added the after-gate sub-case, deviation 4) | o1 |
| 492 | no-open-trial | **RED** | precedence: the stub refuses at the audit verification ("audit not verified"), not at the pre-START gate ("zero open trials", C4.2) - regex mismatch | - |
| 492 | invalid, closed, integrity-violation | `retro` x3 | the wrapper's own gate refuses first | o5 (gate refusal skipped) |
| 493 | 9 instances | `retro` x9 | today's wrapper already builds no Worker / INTENT / capture and seals only from QUALIFIED | o2 (Worker), o3 (synthetic seal) |
| 494 | 5 instances | `retro` x5 | today's opening path (Codex opening-test-record.json) | o4 (exception swallowed) |

Totals: RED 15 (B3-countable, all behavioural); `retro` 35; `ctrl` 1. Every `retro` row has at least one killed
semantic mutant (13 mutants r1-r6, o1-o5, o6a, o6b: all killed by an assertion or a pytest `Failed`).
