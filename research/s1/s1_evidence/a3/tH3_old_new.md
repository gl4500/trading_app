# A3 H3 old -> new (base e9bc6c0)

Every change to an existing test, fixture or product call shape, classified. "Intended" = required by the adopted
spec (Erratum 2 r4 G2 / Clarification 1 r2 C4 / ledger T11 N1); "aid" = a test-side helper added for a migration;
"fixture" = a test-side defect of the plan's draft fixed under R-G (no row outcome changed).

## 1. Product (research/s1/s1_checkpoint.py; CRLF kept)

| old | new | class |
|---|---|---|
| `finalize_close(out, day, cal, t, ...)` (frozen wrapper: gate/finalizer/stage on `lambda: t`) | removed; its opening branch is `finalize_opening(root, now=c.now_utc, *, mailbox=None, before_seal=None)` (C4.1-C4.6, direct call only); its post-START branch has no product caller (run_finalizer / the route cover it) | intended (O8, C4, OP-1 (b)) |
| `finalize_pending(out, cal, start, t)` | removed (no product caller since Task 13) | intended (O8) |
| `_opening_day` (identity + slot check) | `_opening_close_row(out, mailbox)` (identity) + `_opening_day` (calls it, then the slot check); messages unchanged | refactor (C4.2) |
| `run_checkpoint`: every slot takes the Worker path | after gate, registration, `_close_for`, `_no_local_abort`: exact `scheduled == _w_last(cal, start)` -> `_w_last_route` (no Worker / INTENT / capture / callback) | intended (G2.1(2)-(4), O6) |
| `run_finalizer`: no local-abort check | `_no_local_abort(out, "finalizer")` after `verified_registration`, before any finalizer work | intended (G2.1(5), O7) |
| `main`: `run_finalizer(c.HERE)`, `run_checkpoint(...)` (import-time default clock) | `now=c.now_utc` passed to both (read at call time) | intended (T11 N1; G2.1(3) clock reaches the route) |
| `parse_mode` | unchanged: exactly four modes | (C4 "no CLI mode", row 495) |

## 2. Tests

| file:test | old | new | class |
|---|---|---|---|
| test_s1_a3_prestart.py::test_the_opening_close_finalizer_never_writes_into_a_live_or_no_row_slot | `ck.finalize_close(out, day, cal, d45, ...)` | `ck.finalize_opening(tmp_path, now=lambda: d45, ...)`; assertions unchanged | intended (C4.1 call shape, O8) |
| ::test_a_crashed_opening_worker_times_out_at_d_and_the_opening_is_sealed[finalizer-command] | same | same | intended (C4, row 494 migrated param) |
| ::test_a_held_stage_lock_never_delays_the_opening_finalizers_deadline_rows | same | same | intended (C4) |
| ::test_the_finalizer_command_turns_an_opening_stage_error_into_a_refusal[x2] | `ck.finalize_close(..., e45, ...)` | `ck.finalize_opening(tmp_path, now=lambda: e45, ...)` | intended (C4) |
| test_s1_a3_finalizer.py::test_a_stalled_stage_lock_never_delays_the_finalizers_deadline_rows | `ck.finalize_close(out, day, cal, d45, mailbox=...)` | `s1_finalize_close(tmp_path, day, cal, lambda: d45, mailbox=...)` | intended (O8) |
| test_s1_a3_slots.py::test_finalize_pending_never_seals_a_slot_without_a_qualified_row | `ck.finalize_pending(out, cal, start, W + 1h)` | `ck.run_finalizer(tmp_path, now=lambda: at)` under `_Clock(at)`, at = W + 1h (asserted post-START); assertions unchanged; name kept (test id stability) | intended (O8) |
| test_s1_t12_fix2_b1.py::test_b1_expiration_racing_a_late_completion_cannot_change_the_winner[x2] (:290, :296) | `ck.finalize_close(out, day, cal, D45 + 1/2 min)` | `_finalize(out, day, cal, ...)` (module helper over `s1_finalize_close`) | intended (O8) |
| test_s1_t12_fix2_b1.py::test_b1_concurrent_finalizers_and_restart_replay_give_one_deterministic_seal | `real = ck.finalize_close` | `real = _finalize` | intended (O8) |
| test_s1_t12_fix3.py (`_two_successes_no_seal` -> test_c1_a_concurrent_finalizer_and_a_reader_never_observe_a_partial_seal; `_success_without_seal` -> test_i1_probe_a_success_without_its_seal_is_pending_so_no_stop_is_frozen calls `real`) | `real = ck.finalize_close` | `real = _finalize` (imported from test_s1_t12_fix2_b1) | intended (O8) |
| test_s1_t12_fix2_mutants.py::test_mt_an_arbitrary_report_file_does_not_resolve_a_slot, ::test_mt_a_resolution_claiming_success_for_a_late_capture_never_seals | `ck.finalize_close(out, day, cal, t)` | `s1_finalize_close(tmp_path, day, cal, lambda: t)`; refusal oracles unchanged | intended (O8) |
| test_s1_checkpoint.py::test_fr1_main_and_trial_state_compare_modes_and_status_by_value | `monkeypatch.setattr(k, "finalize_pending", no-op)`; `run_checkpoint` fake `lambda *a` | patch dropped (the attribute is gone; no product caller); fake accepts `**kw` (main now passes `now=`) | intended (O8; T11 N1/G2.1) |
| test_s1_checkpoint.py::test_cr_main_dispatches_each_mode_with_the_live_paths | fake `f(root, db, sch, receipt, proc, log)` | `f(..., log, **kw)` | intended (main passes `now=`) |
| test_s1_checkpoint_7b.py (2 tests: :712, :776) | no-op patch of `ck.finalize_pending` | dropped | intended (O8) |
| test_s1_task11.py (:149) | no-op patch of `ck.finalize_pending` | dropped | intended (O8) |
| test_s1_t12_fix2_b1.py::test_b1_a_pending_resolution_cannot_cause_an_early_terminal_stop_followed_by_rescue | the W_L (08:00 = E = W) invocation at s refused "now >= E", no row | it routes: `got["route"] == "w-last"`, zero captures, W_L `["SLOT-MISSED"]` (the route's due MISSED at E); the later finalizer runs find the same unique stop (assertions unchanged) | intended (O6, G2.1(2)/(4): exact W_L at any clock) |

No test invoking the exact W_L slot BEFORE W_L with an expected SLOT-INTENT + FAILED was found by the full suite
(the O6 "early W_L" list is empty; legacy synthetic histories built with `s1_jappend` stay valid, O15).

## 3. Fixtures / helpers

| file | change | class |
|---|---|---|
| conftest.py | new `s1_finalize_close(root, day, cal, now, *, mailbox=None)`: deadline-path gate + `s1_slot.finalize_close` + (post-prereg) `decide_stop`, all with the clock CALLABLE - the clock-callable form of the retired wrapper's post-START branch, test-only | aid (O8) |
| test_s1_t12_fix2_b1.py | new module helper `_finalize(out, day, cal, at)` = `s1_finalize_close(Path(out).parent, day, cal, lambda: at)` (the test's own fixed clock) | aid (O8) |

## 4. The plan's draft tests (R-G deviations; row outcomes unchanged) - see the report's deviations 2-6.
