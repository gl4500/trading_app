"""Task 12 (A10.2) targeted mutants, part 2: s1_checkpoint, s1_seal, s1_snapshot (see s1_mutants_t12_list.py)."""
from s1_mutants_t12_list import A1, A1B, A2, A38, A56, A9, CK, M, SE, SN

# ====================================================================== s1_checkpoint (A5 slot/clock, A2, A9, A1b)
M("_abort_stop reports the trial RUNNING", CK, "_abort_stop",
  [('''    return {"status": "ABORTED-INVALID", "stop_close": None, "reason": ab.get("reason"),''',
    '''    return {"status": "RUNNING", "stop_close": None, "reason": ab.get("reason"),''')],
  ["test_s1_checkpoint.py::test_abort_survives_receipt_revert"], "after an abort every report says ABORTED-INVALID")
M("_write_abort records no reason", CK, "_write_abort",
  [('''    return c.write_abort(out, {"reason": reason, "close": rep["close"], "scheduled": rep["scheduled"],''',
    '''    return c.write_abort(out, {"reason": None, "close": rep["close"], "scheduled": rep["scheduled"],''')],
  [A1 + "::test_a1_a_fingerprint_change_between_the_opening_seal_and_the_stop_is_aborted_invalid"],
  "aborted.json reason = semantic receipt changed")
M("_fingerprint compares whole receipts", CK, "_fingerprint",
  [('''    return receipt.get("fingerprint") if isinstance(receipt, dict) else None''',
    '''    return receipt if isinstance(receipt, dict) and "fingerprint" in receipt else None''')],
  [A1 + "::test_a1_a_head_or_dirty_change_alone_seals_and_is_recorded_as_provenance"],
  "a HEAD-only change matches (provenance is not compared)")
M("_failure leaks the foreign exception text", CK, "_failure",
  [('''    reason = str(e) if isinstance(e, OWN_ERRORS) else f"{where} raised {type(e).__name__}"''',
    '''    reason = str(e)''')],
  [A9 + "::test_a9_receipt_or_process_exception_is_preserved_sanitized_and_never_seals"],
  "the secret-bearing exception text never appears in the report")
M("_failure marks every failure transient", CK, "_failure",
  [('''            "terminal": bool(getattr(e, "terminal", False))}''', '''            "terminal": False}''')],
  [A9 + "::test_a9_an_established_receipt_violation_is_terminal_and_survives_restoration"],
  "a terminal ReceiptError aborts")
M("_safe re-raises", CK, "_safe",
  [('''        rep.setdefault("failures", {})[where] = _failure(where, e)
        return None''', '''        raise''')],
  [A9 + "::test_a9_receipt_or_process_exception_is_preserved_sanitized_and_never_seals",
   A9 + "::test_a9_a_capture_exception_is_preserved_and_never_seals"],
  "an observation exception is preserved, never a crash without a report")
M("_report_path renames the report", CK, "_report_path",
  [('''    return cap_dir.parent / f"{cap_dir.name}.report.json"''', '''    return cap_dir.parent / f"{cap_dir.name}.rep.json"''')],
  [A56 + "::test_a5_the_clock_is_checked_before_any_capture_and_the_refused_attempt_is_preserved",
   "test_s1_checkpoint_7b.py::test_opening_mode_seals_the_opening_close_from_plan_and_audit_without_prereg"],
  "the capture report is <slot>.report.json")
M("_claim_slot allows a duplicate execution", CK, "_claim_slot",
  [('''        with claim.open("x", encoding="utf-8") as f:''', '''        with claim.open("w", encoding="utf-8") as f:''')],
  [A56 + "::test_a5_the_clock_is_checked_before_any_capture_and_the_refused_attempt_is_preserved",
   "test_s1_checkpoint.py::test_rerun_of_captured_slot_is_recorded_and_refused"],
  "a rerun of a slot is refused and recorded")
M("_new_report: eligibility ignores the capture end", CK, "_new_report",
  [('''    eligible = bool(cs and ce) and scheduled <= c.aware(cs) <= c.aware(ce) <= until''',
    '''    eligible = bool(cs and ce) and scheduled <= c.aware(cs) <= until''')],
  [A56 + "::test_a5_a_capture_finishing_after_E_never_seals_one_ending_exactly_at_E_does"],
  "a capture ending after E is late and never seals")
M("_clock_refusal: no pre-capture clock check", CK, "_clock_refusal",
  [('''    if scheduled <= t <= until:
        return None''', '''    if True:
        return None''')],
  [A56 + "::test_a5_the_clock_is_checked_before_any_capture_and_the_refused_attempt_is_preserved"],
  "an early/late invocation takes no capture")
M("_clock_refusal: E is the window end, not s + slack", CK, "_clock_refusal",
  [('''    until = z.eligible_until(scheduled, day, cal)
    if scheduled <= t <= until:''', '''    until = z.window_end(day, cal)
    if scheduled <= t <= until:''')],
  [A56 + "::test_a5_a_delayed_invocation_cannot_claim_a_later_slot"],
  "a slot-45 invocation at 20:56 is refused")
M("_capture: a snapshot exception is not preserved", CK, "_capture",
  [('''    meta = _safe(holder, "capture", s.take_snapshot, live_db, cap_dir, now=now)''',
    '''    meta = s.take_snapshot(live_db, cap_dir, now=now)''')],
  [A9 + "::test_a9_a_capture_exception_is_preserved_and_never_seals"], "a capture exception is preserved")
M("_observe_process: process exceptions crash", CK, "_observe_process",
  [('''    proc = _safe(rep, "process", process_fn)''', '''    proc = process_fn()''')],
  [A9 + "::test_a9_receipt_or_process_exception_is_preserved_sanitized_and_never_seals"],
  "a process-observation exception is preserved")
M("_observe_process: no gap for an unobserved first process", CK, "_observe_process",
  [('''        rep["restart_gaps"] = [f"process not observed ({proc.get('error') or 'nothing listening'})"]''',
    '''        rep["restart_gaps"] = []''')],
  ["test_s1_t12_mutant_survivors.py::test_ms_a_first_ever_unobserved_process_is_a_gap", "test_s1_checkpoint.py::test_first_run_pidless_reports_not_observed_gap"],
  "an unobserved process is a reported gap")
M("_bind_process: a changed binding is accepted", CK, "_bind_process",
  [('''    if _load(refp).get("binding") != got:''', '''    if False:''')],
  [A1B + "::test_a1b_the_first_observed_binding_is_the_reference_and_a_change_is_aborted_invalid"],
  "a different observed binding is ABORTED-INVALID")
M("_bind_process: unobserved binding not reported", CK, "_bind_process",
  [('''        rep.setdefault("observation_gaps", []).append("process binding not observed")''', '''        pass''')],
  [A1B + "::test_a1b_an_unobserved_binding_is_a_reported_gap_never_a_change"], "an unobserved binding is a gap")
M("_read_capture: consistency ignored", CK, "_read_capture",
  [('''        rep["consistent"] = b.consistency(proj["trades"], proj["portfolios"])["consistent"]''',
    '''        rep["consistent"] = True''')],
  ["test_s1_checkpoint.py::test_inconsistent_capture_does_not_seal_and_is_preserved"],
  "an inconsistent capture never seals")
M("_receipt: a fingerprint-less receipt matches", CK, "_receipt",
  [('''    if fp is None:
        rep["receipt_match"] = None
        return receipt, None''', '''    if fp is None:
        rep["receipt_match"] = True
        return receipt, "0" * 64''')],
  [A9 + "::test_a9_missing_required_evidence_never_becomes_a_plausible_match"], "missing evidence never matches")
M("_candidate omits the bridge record", CK, "_candidate",
  [('''            "bridge": bridge, "bundle_sha256": c.bundle_sha256()}''', '''            "bridge": None, "bundle_sha256": c.bundle_sha256()}''')],
  ["test_s1_bridge_8b.py::test_example19_first_post_start_seal_records_the_bridge"],
  "the first post-START seal carries its bridge record")
M("_candidate: opening receipt not carried", CK, "_candidate",
  [('''        cand["receipt"] = receipt                          # the opening receipt is stored with the seal''',
    '''        cand["receipt"] = {}''')],
  ["test_s1_checkpoint_7b.py::test_opening_mode_seals_the_opening_close_from_plan_and_audit_without_prereg"],
  "opening_receipt.json is the opening receipt")
M("_slot_reports reads no reports", CK, "_slot_reports",
  [('''            got[x["scheduled"]] = x''', '''            pass''')],
  [A56 + "::test_a5_a_deferred_capture_seals_once_the_earlier_slots_window_has_passed"],
  "the deferred slot-47 capture is the seal at slot 55")
M("_finalize: earlier unresolved slots ignored", CK, "_finalize",
  [('''            if t <= until:
                rep["deferred"] = (''', '''            if False:
                rep["deferred"] = (''')],
  [A56 + "::test_a5_a_later_slot_capture_waits_for_an_unresolved_earlier_slot_then_the_earlier_one_seals"],
  "a later slot never seals while an earlier slot's window is open")
M("_finalize: only this invocation's capture can seal", CK, "_finalize",
  [('''        if not x.get("candidate"):
            continue''', '''        if not x.get("candidate") or x is not rep:
            continue''')],
  [A56 + "::test_a5_a_deferred_capture_seals_once_the_earlier_slots_window_has_passed"],
  "the first eligible capture in slot order is the seal, not this invocation's")
M("_seal_from: projection not re-verified", CK, "_seal_from",
  [('''    if not proj_p.is_file() or c.sha256_file(proj_p) != cand["projection_sha256"]:''', '''    if not proj_p.is_file():''')],
  ["test_s1_t12_mutant_followups.py::test_mf_a_tampered_deferred_capture_never_seals"],
  "a deferred capture changed before its seal is written never seals")
M("_seal_from: seal records no bundle", CK, "_seal_from",
  [('''            "receipt_provenance": cand["receipt_provenance"], "bundle_sha256": cand["bundle_sha256"]}''',
    '''            "receipt_provenance": cand["receipt_provenance"], "bundle_sha256": None}''')],
  ["test_s1_task11.py::test_i1_every_seal_records_the_checkpoint_toolchain"], "every seal records the bundle")
M("_seal_from: seal records no capture start/end", CK, "_seal_from",
  [('''    cap = {"scheduled": rep["scheduled"], "actual": rep["actual"], "capture_start": cand["capture_start"],
           "capture_end": cand["capture_end"], "ok": True, "consistent": True,''',
    '''    cap = {"scheduled": rep["scheduled"], "actual": rep["actual"], "ok": True, "consistent": True,''')],
  ["test_s1_t12_mutant_followups.py::test_mf_every_seal_records_its_measured_capture_interval"],
  "every seal records its measured capture start/end")
M("_trial_stop never persists (stop decision only)", CK, "_trial_stop",
  [('''        return _public(z.current_stop(out, start, cal, t, "checkpoint"))''',
    '''        return z.stop_decision(_seals(out), start, cal, today=t)''')],
  [A2 + "::test_a2_post_stop_checkpoints_follow_the_persisted_stop"], "post-stop follows the persisted stop")
M("_public keeps the internal flag", CK, "_public",
  [('''    return {k_: v for k_, v in st_.items() if k_ != "persisted"}''', '''    return dict(st_)''')],
  ["test_s1_connected.py::test_connected_lifecycle_matches_independent_oracle[chop-FAIL-None]"],
  "the reported stop equals the stop decision")
M("run_checkpoint: a late capture may seal", CK, "run_checkpoint",
  [('''            and rep["receipt_match"] is True and not failures and not rep["late"]:''',
    '''            and rep["receipt_match"] is True and not failures:''')],
  [A56 + "::test_a5_a_capture_finishing_after_E_never_seals_one_ending_exactly_at_E_does"],
  "a capture ending after E never seals")
M("run_checkpoint: a failed observation may seal", CK, "run_checkpoint",
  [('''            and rep["receipt_match"] is True and not failures and not rep["late"]:''',
    '''            and rep["receipt_match"] is True and not rep["late"]:''')],
  [A9 + "::test_a9_receipt_or_process_exception_is_preserved_sanitized_and_never_seals"],
  "a process exception never seals")
M("run_checkpoint: terminal receipt error not an abort", CK, "run_checkpoint",
  [('''    elif failures.get("receipt", {}).get("terminal"):                  # A9.2: an established violation''',
    '''    elif False:''')],
  [A9 + "::test_a9_an_established_receipt_violation_is_terminal_and_survives_restoration"],
  "an established receipt violation is terminal")
M("run_checkpoint: stop not persisted at the stop seal", CK, "run_checkpoint",
  [('''            rep["stop"] = _public(z.current_stop(out, start, cal, actual, "checkpoint"))   # A2.1: persisted if ended''',
    '''            rep["stop"] = z.stop_decision(_seals(out), start, cal, today=actual)'''),
   ('''    state, state_err = _trial_stop(out, start, cal, t0) if already is None else (None, None)''',
    '''    state, state_err = (z.stop_decision(_seals(out), start, cal, today=t0), None) if already is None else (None, None)''')],
  [A2 + "::test_a2_the_stop_is_persisted_once_at_the_seal_with_its_identity"], "stop.json written at the stop seal")
M("run_checkpoint: registration not verified", CK, "run_checkpoint",
  [('''    pr = g.verified_registration(out, "checkpoint", mailbox, now)     # Task 12: A3.2 bundle first, then A8.2''',
    '''    pr = c.load_json(out / "prereg.json")''')],
  [A38 + "::test_a8_hand_made_prereg_reaches_no_live_callback"], "a hand-made prereg reaches no live callback")
M("run_opening_checkpoint: bundle not verified first", CK, "run_opening_checkpoint",
  [('''    c.verify_bundle_first(out, "opening checkpoint", mailbox=mailbox, now=now, need="audit")    # Task 12: A3.2''',
    '''    pass''')],
  ["test_s1_t12_mutant_survivors.py::test_ms_the_opening_compares_the_bundle_before_reading_the_audit", A38 + "::test_a3_opening_checkpoint_bundle_mismatch_refuses_with_zero_callbacks_and_no_abort"],
  "the opening refuses a changed bundle")
M("run_opening_checkpoint: a late capture may seal", CK, "run_opening_checkpoint",
  [('''            and not rep.get("failures") and not rep["late"]:''', '''            and not rep.get("failures"):''')],
  ["test_s1_t12_mutant_followups.py::test_mf_an_opening_capture_ending_after_E_never_seals"],
  "an opening capture ending after E never seals")
M("_audit_calendar: audit not verified", CK, "_audit_calendar",
  [('''        aud = g.verified_audit(out, mailbox)
    except g.Invalid as e:
        raise SystemExit(f"opening refused: audit not verified ({e})") from None''',
    '''        aud = g.verified_audit(out, mailbox)
    except g.Invalid:
        aud = {"plan": c.load_json(out / "plan.json"),
               "calendar": z.calendar_rows(c.load_json(out / "audit" / "calendar.json"))}''')],
  [A38 + "::test_a8_opening_mode_verifies_the_audit_ack_plan_calendar_and_source_bindings_before_capture"],
  "an unverified audit refuses the opening")
M("_opening_day: any slot accepted", CK, "_opening_day",
  [('''    if scheduled not in slots:''', '''    if False:''')],
  ["test_s1_checkpoint_7b.py::test_opening_mode_refuses_a_non_opening_slot"], "a non-opening slot refuses")
M("_trial_state: an aborted trial is not reported ABORTED", CK, "_trial_state",
  [('''        return "ABORTED-INVALID", (st_ or {}).get("stop_close")''', '''        pass''')],
  ["test_s1_checkpoint_7b.py::test_final_snapshot_after_a_recorded_abort_is_taken"],
  "an aborted trial's final snapshot reports ABORTED-INVALID")
M("run_final_snapshot: frozen-slice problems not recorded", CK, "run_final_snapshot",
  [('''        rep["fence_violations"] += [f"persisted stop: {x}" for x in probs]     # Task 12 (A2.3), recorded''',
    '''        pass''')],
  ["test_s1_checkpoint_7b.py::test_cr_final_snapshot_refuses_on_a_bad_seal_record"],
  "an extra seal among the frozen slices is a recorded violation")
M("run_final_snapshot: no bundle recorded", CK, "run_final_snapshot",
  [('''           "fence_checked": False, "fence_violations": [], "bundle_sha256": c.bundle_sha256(),''',
    '''           "fence_checked": False, "fence_violations": [], "bundle_sha256": None,''')],
  [A38 + "::test_a3_run_acquire_score_tokens_prereg_and_every_seal_bind_the_bundle"],
  "the final snapshot records the bundle")

# ====================================================================== s1_seal (A5, A6, A2)
M("deadline at the end of the NY day (A5.1 regression)", SE, "deadline",
  [('''    return datetime.combine(d, s.time().replace(tzinfo=None), tzinfo=c.NY).astimezone(timezone.utc)''',
    '''    return datetime.combine(d, time(23, 59), tzinfo=c.NY).astimezone(timezone.utc)''')],
  [A56 + "::test_a5_codex_probe_a_the_deadline_days_close_after_a_0930_deadline_is_ineligible",
   A56 + "::test_a5_deadline_is_an_aware_instant_at_starts_new_york_wall_time"],
  "Apr-15 16:00 is ineligible for an Apr-15 09:30 deadline")
M("deadline without the month-end clamp", SE, "deadline",
  [('''    d = date(y, m, min(s.day, pycal.monthrange(y, m)[1]))''', '''    d = date(y, m, 1) + timedelta(days=s.day - 1)''')],
  [A56 + "::test_a5_deadline_is_an_aware_instant_at_starts_new_york_wall_time"], "Aug-31 + 6 months = Feb-28")
M("eligible_sessions by date (A5.1 regression)", SE, "eligible_sessions",
  [('''    return [d for d in _sorted_calendar(calendar) if open_instant(d) >= start and _close(d) <= dl]''',
    '''    return [d for d in _sorted_calendar(calendar) if open_instant(d) >= start
            and d["date"] <= dl.astimezone(c.NY).date().isoformat()]''')],
  [A56 + "::test_a5_codex_probe_a_the_deadline_days_close_after_a_0930_deadline_is_ineligible",
   A56 + "::test_a5_an_ineligible_post_deadline_close_can_never_be_the_stop"],
  "the deadline day's close is ineligible")
M("eligible_until without the window clamp", SE, "eligible_until",
  [('''    return min(slot + SCHEDULE_SLACK, window_end(day, calendar))''', '''    return slot + SCHEDULE_SLACK''')],
  [A56 + "::test_a5_eligible_until_is_min_of_slot_plus_slack_and_the_window_end",
   A56 + "::test_a5_the_0800_slot_has_no_positive_duration_window_and_is_not_slid"],
  "the 08:00 slot's E is W itself")
M("capture_eligible allows a start before s", SE, "capture_eligible",
  [('''    return slot <= capture_start <= capture_end <= eligible_until(slot, day, calendar)''',
    '''    return capture_start <= capture_end <= eligible_until(slot, day, calendar)''')],
  [A56 + "::test_a5_capture_eligibility_predicate_examples"], "a capture starting before s is ineligible")
M("capture_eligible: completion exactly at E refused", SE, "capture_eligible",
  [('''    return slot <= capture_start <= capture_end <= eligible_until(slot, day, calendar)''',
    '''    return slot <= capture_start <= capture_end < eligible_until(slot, day, calendar)''')],
  [A56 + "::test_a5_capture_eligibility_predicate_examples"], "completion exactly at E is allowed")
M("choose_seal by arrival order", SE, "choose_seal",
  [('''    for cap in sorted(captures, key=lambda k: c.aware(k["scheduled"])):''',
    '''    for cap in sorted(captures, key=lambda k: c.aware(k["capture_end"])):''')],
  [A56 + "::test_a5_overlapping_retry_tolerances_are_resolved_by_slot_order_not_arrival"],
  "the slot-45 capture is the seal even though it arrived later")
M("calendar_rows keeps extra provider fields", SE, "calendar_rows",
  [('''    return [{"date": x["date"], "open": x["open"], "close": x["close"]} for x in raw]''',
    '''    return [dict(x) for x in raw]''')],
  ["test_s1_t12_mutant_followups.py::test_mf_calendar_rows_keep_only_date_open_close"],
  "prereg's calendar holds only the session rows of the pinned listing")
M("calendar_problems: order not checked", SE, "calendar_problems",
  [('''        if prev is not None and x["date"] <= prev:''', '''        if prev is not None and x["date"] == prev:''')],
  [A56 + "::test_a6_completeness_is_checked_against_the_pinned_listing"], "an out-of-order listing aborts")
M("calendar_problems: lag coverage off by one", SE, "calendar_problems",
  [('''    elif sum(1 for x in listing if _ny(x["date"], x["close"]) > dl) < FINAL_LAG_SESSIONS:''',
    '''    elif sum(1 for x in listing if _ny(x["date"], x["close"]) > dl) < FINAL_LAG_SESSIONS - 1:''')],
  [A56 + "::test_a6_completeness_is_checked_against_the_pinned_listing"], "fewer than 3 sessions after the deadline aborts")
M("calendar_problems: opening close not required", SE, "calendar_problems",
  [('''    if not oc or listing[0]["date"] > oc or oc not in {x["date"] for x in listing}:''', '''    if not oc:''')],
  [A56 + "::test_a6_completeness_is_checked_against_the_pinned_listing"],
  "a listing missing the opening close aborts")
M("calendar_pin_problems: raw page binding skipped", SE, "calendar_pin_problems",
  [('''        if raw != files.get("calendar.json"):''', '''        if False:''')],
  ["test_s1_t12_mutant_followups.py::test_mf_a_calendar_json_differing_from_its_pinned_raw_page_refuses"],
  "a calendar.json differing from its pinned raw page refuses (manifest hash rewritten)")
M("calendar_pin_problems: params not compared", SE, "calendar_pin_problems",
  [('''    if src.get("params") != want:''', '''    if False:''')],
  ["test_s1_t12_mutant_followups.py::test_mf_a_calendar_pinned_with_other_request_parameters_refuses"],
  "a pin whose request parameters are not the plan's refuses")
M("stop_decision admits a post-deadline close", SE, "stop_decision",
  [('''    eligible = eligible_sessions(start, calendar)                    # A5.1: close instants <= the deadline''',
    '''    eligible = [d for d in calendar if open_instant(d) >= start]''')],
  [A56 + "::test_a5_an_ineligible_post_deadline_close_can_never_be_the_stop"], "a post-deadline close is never the stop")
M("stop_record: cohort ids include the post-stop rows", SE, "stop_record",
  [('''                       [t for t in seal["trades"] if c.aware(t["ts"]) <= sc], start, sc)))''',
    '''                       seal["trades"], start, sc + timedelta(days=30))))''')],
  ["test_s1_t12_mutant_followups.py::test_mf_cohort_ids_are_the_stop_seals_cohort_through_the_stop_close"],
  "cohort ids = BUYs with START <= stored time <= the stop close")
M("stop_record: frozen slices = every seal", SE, "stop_record",
  [('''        rec["seals"] = {p.relative_to(out).as_posix(): c.sha256_file(p) for p, x in idx
                        if c.aware(x["close"]) <= sc}''', '''        rec["seals"] = {p.relative_to(out).as_posix(): c.sha256_file(p) for p, x in idx}''')],
  ["test_s1_t12_mutant_followups.py::test_mf_frozen_slices_stop_at_the_stop_close"],
  "the frozen slices are the seals through the stop close")
M("persist_stop overwrites", SE, "persist_stop",
  [('''    with p.open("x", encoding="utf-8") as f:
        json.dump(rec, f, indent=1, sort_keys=True)''', '''    with p.open("w", encoding="utf-8") as f:
        json.dump(rec, f, indent=1, sort_keys=True)''')],
  [A2 + "::test_a2_the_stop_is_persisted_once_at_the_seal_with_its_identity"], "stop.json is written once")
M("load_stop never finds the stop", SE, "load_stop",
  [('''    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None''', '''    return None''')],
  [A2 + "::test_a2_post_stop_checkpoints_follow_the_persisted_stop",
   A2 + "::test_a2_the_persisted_stop_is_never_recomputed_from_later_rows_or_changed_helpers"],
  "the persisted stop governs later commands")
M("current_stop recomputes even when persisted", SE, "current_stop",
  [('''    st_ = load_stop(out)
    if st_ is None and stop_was_persisted(out):            # fix round 1 (m-4): never a silent recompute
        raise ValueError("persisted stop (stop.json) missing after it was persisted")
    if st_ is None:''', '''    st_ = None
    if st_ is None:''')],
  [A2 + "::test_a2_post_stop_checkpoints_follow_the_persisted_stop"], "never recomputed after persisting")
M("stop_problems: extra slices ignored", SE, "stop_problems",
  [('''        if rel not in listed and (sc is None or c.aware(x["close"]) <= sc):''', '''        if False:''')],
  ["test_s1_t12_mutant_survivors.py::test_ms_stop_problems_reports_an_extra_seal_among_the_frozen_slices", A2 + "::test_a2_integrity_of_the_frozen_slices_is_enforced_at_score",
   A2 + "::test_a2_no_valid_seal_is_terminal_persisted_and_never_rescued_by_a_late_seal"],
  "an extra seal among the frozen slices is an integrity failure")
M("stop_problems: changed slice ignored", SE, "stop_problems",
  [('''        elif c.sha256_file(p) != h:
            probs.append(f"frozen slice {rel} changed since the persisted stop")''', '''        elif False:
            probs.append(f"frozen slice {rel} changed since the persisted stop")''')],
  ["test_s1_run.py::test_fr1_unreadable_seal_rows_are_a_bad_seal_record_reason"],
  "a changed frozen slice is reported")
M("stop_problems: no consistency re-check", SE, "stop_problems",
  [('''        if (again["status"], again["stop_close"]) != (st_["status"], st_["stop_close"]):''', '''        if False:''')],
  ["test_s1_t12_mutant_followups.py::test_mf_a_stop_json_naming_a_non_qualifying_close_is_aborted_invalid"],
  "a stop.json whose stop is not the frozen slices' stop is ABORTED-INVALID")
M("_seal_index reads no seals", SE, "_seal_index",
  [('''    return [(p, json.loads(p.read_text(encoding="utf-8"))) for p in sorted((out / "seals").glob("*.json"))]''',
    '''    return []''')],
  [A2 + "::test_a2_the_stop_is_persisted_once_at_the_seal_with_its_identity"], "the stop is decided over the seals")

# ====================================================================== s1_snapshot
M("take_snapshot ignores the injected clock", SN, "take_snapshot",
  [('''    now = now or c.now_utc''', '''    now = c.now_utc''')],
  ["test_s1_t12_mutant_survivors.py::test_ms_take_snapshot_measures_with_the_injected_clock", A56 + "::test_a5_a_capture_finishing_after_E_never_seals_one_ending_exactly_at_E_does"],
  "measured capture instants come from the injected clock")


# ====================================================================== Task 12 fix round 1 (I-1, I-4b, m-1, m-4)
FX = "test_s1_t12_fix1.py::"
M("_parse: an unparseable member is a foreign exception again", "s1_receipt.py", "_parse",
  [('''    except (SyntaxError, UnicodeDecodeError, ValueError) as e:
        raise ReceiptError(''', '''    except ZeroDivisionError as e:
        raise ReceiptError(''')],
  [FX + "test_fix1_i1_an_unparseable_closure_member_is_a_terminal_receipt_failure",
   FX + "test_fix1_i1_merge_conflict_mid_trial_is_aborted_invalid_and_restoring_does_not_resume"],
  "a merge-conflicted MR file is a terminal receipt failure (ABORTED-INVALID)")
M("_parse: an unparseable member is transient", "s1_receipt.py", "_parse",
  [('''        raise ReceiptError(f"closure member {rel} unparseable ({type(e).__name__}): a registered member changed",
                           terminal=True) from None''', '''        raise ReceiptError(f"closure member {rel} unparseable ({type(e).__name__}): a registered member changed",
                           terminal=False) from None''')],
  [FX + "test_fix1_i1_an_unparseable_closure_member_is_a_terminal_receipt_failure",
   FX + "test_fix1_i1_merge_conflict_mid_trial_is_aborted_invalid_and_restoring_does_not_resume"],
  "the failure is terminal, so restoring does not resume")
M("_read_seals: a corrupt seal crashes", CK, "_read_seals",
  [('''    try:
        return _seals(out), None
    except (OSError, ValueError) as e:''', '''    try:
        return _seals(out), None
    except ZeroDivisionError as e:''')],
  [FX + "test_fix1_i4b_a_corrupt_trial_seal_is_a_preserved_terminal_integrity_failure"],
  "a corrupt trial seal is a preserved terminal integrity failure")
M("run_checkpoint: a corrupt seal is not an abort", CK, "run_checkpoint",
  [('''    if state_err is not None or seals_err is not None:                # fix round 1 (I-4b/m-4): corrupt records''',
    '''    if False:                # fix round 1 (I-4b/m-4): corrupt records''')],
  [FX + "test_fix1_i4b_a_corrupt_trial_seal_is_a_preserved_terminal_integrity_failure",
   FX + "test_fix1_m4_a_deleted_persisted_stop_is_an_integrity_failure_not_a_recompute"],
  "corrupt records / a vanished stop.json abort the trial")
M("_stop_hash records nothing", CK, "_stop_hash",
  [('''        rep["stop_sha256"] = c.sha256_file(out / "stop.json")''', '''        pass''')],
  [FX + "test_fix1_m4_a_changed_persisted_stop_before_the_attestation_is_detected",
   FX + "test_fix1_m4_a_deleted_persisted_stop_is_an_integrity_failure_not_a_recompute"],
  "every report after the stop records stop.json's hash")
M("stop_was_persisted always false", SE, "stop_was_persisted",
  [('''        if v not in (None, c.ABSENT):
            return True
    return False''', '''        if False:
            return True
    return False''')],
  [FX + "test_fix1_m4_a_deleted_persisted_stop_is_an_integrity_failure_not_a_recompute"],
  "a deleted persisted stop is never recomputed")
M("stop_problems: recorded stop hashes not compared", SE, "stop_problems",
  [('''        if v not in (None, c.ABSENT, sj):''', '''        if False:''')],
  [FX + "test_fix1_m4_a_changed_persisted_stop_before_the_attestation_is_detected"],
  "a changed stop.json is detected before any attestation")
M("stop_problems: stop bundle not checked", SE, "stop_problems",
  [('''    if st_.get("bundle_sha256") != c.bundle_sha256():''', '''    if False:''')],
  [FX + "test_fix1_m4_the_persisted_stops_bundle_is_checked"], "stop.json's bundle is the registered one")
M("verify_bundle_first: prereg refusal before the comparison (m-1 regression)", "s1_common.py", "verify_bundle_first",
  [('''        err = e
        try:
            reg = _audit_registration(out, mailbox)
        except SystemExit:
            reg = {"stage": None}''', '''        raise''')],
  [FX + "test_fix1_m1_a_bundle_mismatch_is_persisted_even_on_a_prereg_refusal_path"],
  "a mismatch observed on a prereg refusal path is persisted")
