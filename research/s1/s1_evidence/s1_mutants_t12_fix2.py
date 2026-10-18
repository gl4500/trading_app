"""Task 12 fix round 2 (Addendum 2 B1-B3, I-1 completion; A10.2). Applied to MUTANTS after the list/part2/part3:
(1) RETARGET the fix-round-1 mutants whose source text the round-2 code replaced (same intent, the new code);
(2) TIGHTEN the 8 mutants fix round 1 reported KILLED-BY-EXCEPTION: each gets a test whose intended assertion fails
    on it (s1_tests/test_s1_t12_fix2_mutants.py, retrospective);
(3) ADD targeted mutants for the round-2 behaviour, each with its intended test(s)."""
from s1_mutants_t12_list import A1B, A56, CK, CM, CO, GT, M, MUTANTS, RC, RN, SE

FX2 = "test_s1_t12_fix2_mutants.py::"
B1, B2, B3, I1 = ("test_s1_t12_fix2_b1.py::", "test_s1_t12_fix2_b2.py::", "test_s1_t12_fix2_b3.py::",
                  "test_s1_t12_fix2_i1.py::")
BY = {m["name"]: m for m in MUTANTS}


def retarget(name, edits, *, file=None, function=None, tests=None, new_name=None):
    m = BY[name]
    f = file or m["file"]
    m["edits"] = [(e[0], e[1], e[2]) if len(e) == 3 else (f, e[0], e[1]) for e in edits]
    m["retargeted"] = "fix round 2: source replaced by the Addendum 2 implementation; same intent on the new code"
    if function:
        m["function"] = function
    if tests:
        m["tests"] = tests
    if new_name:
        m["name"] = new_name


# ---------------------------------------------------------------- (1) retargets
retarget("registration: audit stage never registered",
         [('''        return {"stage": "audit", "bundle": b, "registered": is_registered(out), "ack_id": ack_id}''',
           '''        return {"stage": "audit", "bundle": b, "registered": False, "ack_id": ack_id}''')])
retarget("verified_registration ignores problems",
         [('''    if probs:
        c.record_refusal(out, where, f"registration not verified: {probs}", now)       # fix round 2 (B3.2)''',
           '''    if False:
        c.record_refusal(out, where, f"registration not verified: {probs}", now)       # fix round 2 (B3.2)''')],
         tests=["test_s1_t12_a3_a8.py::test_a8_checkpoint_verifies_the_run_ack_identity_bindings_and_timing_before_capture"
                "[ack_after_start]"])          # (an edited plan is now first the B3 gate's abort: an ACK breakage)
retarget("_bind_process: a changed binding is accepted",
         [('''    rep["process_binding"] = {"status": "CHANGED", "binding": dict(b)}
    rep["process_binding_changed"] = True
    return True''', '''    rep["process_binding"] = {"status": "MATCH", "binding": dict(b)}
    return False''')],
         function="_binding", new_name="_binding: a changed binding is accepted",
         tests=[A1B + "::test_a1b_the_first_observed_binding_is_the_reference_and_a_change_is_aborted_invalid",
                B2 + "test_b2_a_then_gap_then_b_is_a_persistent_invalidity"])
retarget("_bind_process: unobserved binding not reported",
         [('''        rep.setdefault("observation_gaps", []).append(f"process binding not observed ({b[r.GAP_FIELD]})")''',
           '''        pass''')],
         function="_binding", new_name="_binding: a gap is not reported",
         tests=[A1B + "::test_a1b_an_unobserved_binding_is_a_reported_gap_never_a_change",
                B2 + "test_b2_a_then_gap_then_a_preserves_the_gap_and_invents_no_change"])
retarget("_candidate omits the bridge record",
         [('''            "bridge": bridge, "bundle_sha256": c.bundle_sha256(),''',
           '''            "bridge": None, "bundle_sha256": c.bundle_sha256(),''')])
retarget("_slot_reports reads no reports",
         [('''        rec = _read_resolution(rp)
        if rec is None:''', '''        rec = None
        if rec is None:''')],
         function="finalize_close", new_name="finalize_close reads no resolution records")
retarget("_finalize: earlier unresolved slots ignored",
         [('''                if t <= until:
                    res["deferred"] = (f"earlier slot {slot.isoformat()} unresolved (never claimed;''',
           '''                if False:
                    res["deferred"] = (f"earlier slot {slot.isoformat()} unresolved (never claimed;''')],
         function="finalize_close", new_name="finalize_close: an unclaimed earlier slot with an open window ignored")
retarget("_finalize: only this invocation's capture can seal",
         [('''        if rec["outcome"] != SUCCESS:
            continue''', '''        if rec["outcome"] != SUCCESS:
            return res''')],
         function="finalize_close", new_name="finalize_close stops at the first unsuccessful slot")
retarget("_seal_from: seal records no capture start/end",
         [('''    cap = {"scheduled": ev["scheduled"], "actual": ev["actual"], "capture_start": cand["capture_start"],
           "capture_end": cand["capture_end"], "ok": True, "consistent": True,''',
           '''    cap = {"scheduled": ev["scheduled"], "actual": ev["actual"], "ok": True, "consistent": True,''')],
         function="_seal_bytes")
retarget("verify_bundle_first: prereg refusal before the comparison (m-1 regression)",
         [('''            err = e
            try:
                reg = _audit_registration(out, mailbox)
            except SystemExit:
                reg = {"stage": None}''', '''            raise''')])
retarget("process_identity reports no binding", [('''    if exe and cmd:''', '''    if False:''')])
retarget("score: bundle not verified first",
         [('''    c.verify_bundle_first(out, "score", mailbox=mailbox, gate_refuses=False)   # fix round 2 (B3): gate first;''',
           '''    pass'''),
          ('''    c.verify_bundle_first(out, "score", mailbox=mailbox, need="prereg",           # Task 12: A3.2 bundle first
                          gate_refuses=False)''', '''    pass''')])
retarget("_write_report writes nothing",
         [('''    with _report_path(cap_dir).open("x", encoding="utf-8") as f:
        f.write(json.dumps(rep, indent=1))''', '''    pass''')])

# ---------------------------------------------------------------- (2) the 8 exception-only kills, tightened
for name, test in (("token_fields keeps only the first field", "test_mt_token_fields_parses_every_field"),
                   ("load_json reads nothing (empty dict)", "test_mt_load_json_returns_the_files_json"),
                   ("_require_no_redirects accepts any client",
                    "test_mt_a_client_that_may_follow_redirects_is_refused_by_name"),
                   ("collect _load reads nothing", "test_mt_the_collectors_loader_returns_the_files_json"),
                   ("_namespace_dir always true", "test_mt_namespace_dir_is_a_package_directory_without_init"),
                   ("_out points elsewhere", "test_mt_the_runner_works_under_root_s1_out"),
                   ("attest_stop: binds no stop.json", "test_mt_the_stop_attestation_binds_stop_json"),
                   ("_receipt_sha over the whole receipt", "test_mt_the_runners_receipt_hash_is_the_fingerprints")):
    BY[name]["tests"] = BY[name]["tests"] + [FX2 + test]
    BY[name]["tightened"] = "fix round 2: a test whose intended assertion fails on this mutant (A10.2)"

# ---------------------------------------------------------------- (3) new mutants: I-1 completion
M("semantic_receipt: no raw pre-parse comparison", RC, "semantic_receipt",
  [('''    if reference is not None:
        raw = closure_raw_problems(backend, reference)''', '''    if False:
        raw = closure_raw_problems(backend, reference)''')],
  [I1 + "test_i1_a_changed_closure_member_is_terminal_before_any_parse",
   I1 + "test_i1_the_checkpoint_passes_the_bound_reference_and_a_valid_edit_aborts"],
  "a changed member is terminal before any parse")
M("closure_raw_problems: sha256 not compared", RC, "closure_raw_problems",
  [('''        elif c.sha256_file(p) != h:''', '''        elif False:''')],
  [I1 + "test_i1_a_changed_closure_member_is_terminal_before_any_parse"], "an edited member is a raw change")
M("_call_receipt never passes the bound reference", CK, "_call_receipt",
  [('''    if reference is not None and ("reference" in params''', '''    if False and ("reference" in params''')],
  [I1 + "test_i1_the_checkpoint_passes_the_bound_reference_and_a_valid_edit_aborts"],
  "the checkpoint hands the registered receipt to the receipt function")

# ---------------------------------------------------------------- B1
M("RESOLUTION_TIMEOUT is not 30 minutes", SE, "RESOLUTION_TIMEOUT",
  [('''RESOLUTION_TIMEOUT = timedelta(minutes=30)''', '''RESOLUTION_TIMEOUT = timedelta(minutes=31)''')],
  [B1 + "test_b1_resolution_timeout_is_thirty_minutes_and_single_sourced"], "D = E + 30 min, single-sourced")
M("resolution_deadline is E (no timeout)", SE, "resolution_deadline",
  [('''    return eligible_until(slot, day, calendar) + RESOLUTION_TIMEOUT''', '''    return eligible_until(slot, day, calendar)''')],
  [B1 + "test_b1_a_claim_without_a_report_stays_pending_after_E_and_times_out_at_D"],
  "a claimed slot stays pending after E until D")
M("finalize_close: a claimed unresolved slot is not pending (old A5.2)", CK, "finalize_close",
  [('''            if _claim_path(cap_dir).exists():
                if t < dl:''', '''            if False:
                if t < dl:''')],
  [B1 + "test_b1_the_reviews_overlap_race_selects_the_earlier_slot_in_both_completion_orders"],
  "the earlier in-flight slot wins in both completion orders")
M("finalize_close: the timeout only after D (not at D)", CK, "finalize_close",
  [('''                if t < dl:
                    res["deferred"] = (f"earlier slot {slot.isoformat()} is claimed and pending''',
    '''                if t <= dl:
                    res["deferred"] = (f"earlier slot {slot.isoformat()} is claimed and pending''')],
  [B1 + "test_b1_expiration_racing_a_late_completion_cannot_change_the_winner"],
  "at D a pending attempt is a RESOLUTION-TIMEOUT")
M("_publish: a publication at D still succeeds", CK, "_publish",
  [('''    if t < dl and not rp.exists():''', '''    if t <= dl and not rp.exists():''')],
  [B1 + "test_b1_a_success_published_strictly_before_D_qualifies_at_or_after_D_it_times_out"],
  "publication must be strictly before D")
M("pending_closes ignores claims", SE, "pending_closes",
  [('''                got.add(day_dir.name)''', '''                pass''')],
  [B1 + "test_b1_a_pending_resolution_cannot_cause_an_early_terminal_stop_followed_by_rescue"],
  "no terminal stop while a claimed attempt is pending")
M("stop_decision ignores pending closes", SE, "stop_decision",
  [('''        if s is None and d["date"] in pending:''', '''        if False:''')],
  [B1 + "test_b1_a_pending_resolution_cannot_cause_an_early_terminal_stop_followed_by_rescue"],
  "the stop decision is RUNNING across a pending close")
M("_finalize_others resolves no other close", CK, "_finalize_others",
  [('''            finalize_close(out, rows[d], cal, t)
        except ValueError:''', '''            pass
        except ValueError:''')],
  [FX2 + "test_mt_a_later_close_resolves_an_earlier_close_left_pending"],
  "an earlier close left pending is resolved by a later checkpoint")
M("a late worker still runs the selection", CK, "run_checkpoint",
  [('''    if already is None and not rep.get("late_evidence"):''', '''    if already is None:''')],
  [B1 + "test_b1_a_success_published_strictly_before_D_qualifies_at_or_after_D_it_times_out"],
  "a late worker writes no seal")
M("_complete_success accepts any candidate", CK, "_complete_success",
  [('''    return (isinstance(cand, dict) and all(k_ in cand for k_ in CANDIDATE_KEYS)''',
    '''    return (isinstance(cand, dict) or all(k_ in cand for k_ in CANDIDATE_KEYS)''')],
  [FX2 + "test_mt_a_forged_success_without_complete_evidence_never_seals"],
  "a SUCCESS without complete evidence never seals")

# ---------------------------------------------------------------- B2
M("_binding: a gap counts as MATCH", CK, "_binding",
  [('''        rep["process_binding"] = {"status": "GAP", "binding": None, "reason": b[r.GAP_FIELD]}''',
    '''        rep["process_binding"] = {"status": "MATCH", "binding": None, "reason": b[r.GAP_FIELD]}''')],
  [B2 + "test_b2_a_then_gap_then_a_preserves_the_gap_and_invents_no_change"], "a gap is never MATCH")
M("_binding: a failed observation is not a failure", CK, "_binding",
  [('''    if proc.get("error") is not None:''', '''    if False:''')],
  [B2 + "test_b2_an_observation_exception_mid_trial_is_preserved_and_never_seals"],
  "a failed observation is an A9.1 process failure")
M("_binding: a malformed binding is not a failure", CK, "_binding",
  [('''    if why:
        rep.setdefault("failures", {})["process_binding"] = {''', '''    if False:
        rep.setdefault("failures", {})["process_binding"] = {''')],
  [B2 + "test_b2_a_malformed_claimed_binding_is_not_equality"], "a malformed binding is not equality")
M("_binding: pid compared too", CK, "_binding",
  [('''    if b == ref:''', '''    if b == ref and proc.get("pid") == 1:''')],
  [B2 + "test_b2_an_identical_binding_restart_is_provenance_not_a_semantic_change"],
  "an identical-binding restart is provenance only")
M("opening accepts an unobserved binding", CK, "run_opening_checkpoint",
  [('''    if rep["process_binding"]["status"] != "REFERENCE" and "process_binding" not in rep.get("failures", {}):''',
    '''    if False:''')],
  [B2 + "test_b2_an_unobservable_opening_binding_writes_no_opening_seal"], "no opening seal without a binding")
M("prereg binds no process binding", RN, "do_prereg",
  [('''          "process_binding": _opening_binding(seal, "prereg"),                     # fix round 2 (B2.1)''',
    '''          "process_binding": None,''')],
  [B2 + "test_b2_the_opening_binding_is_the_reference_bound_by_the_attestation_and_prereg"],
  "prereg binds the opening reference")
M("attest_start binds no process binding", RN, "attest_start",
  [('''           "process_binding_sha256": _binding_sha(binding),                         # fix round 2 (B2.1)''',
    '''           "process_binding_sha256": None,''')],
  [B2 + "test_b2_the_opening_binding_is_the_reference_bound_by_the_attestation_and_prereg"],
  "the START attestation binds the reference")
M("score: a different MATCH binding accepted", RN, "_seal_binding_problems",
  [('''            if isinstance(pb, dict) and pb.get("status") == "MATCH" and pb.get("binding") == ref:''',
    '''            if isinstance(pb, dict) and pb.get("status") == "MATCH":''')],
  [B2 + "test_b2_the_score_rechecks_every_seals_binding_and_invalid_makes_zero_valuation_calls"],
  "A, gap, B is INVALID at score")
M("score: a missing seal binding accepted", RN, "_seal_binding_problems",
  [('''            bad.append(f"seal {Path(p).stem}: process binding missing, malformed or different from the opening "
                       f"reference")''', '''            pass''')],
  [B2 + "test_b2_the_score_rechecks_every_seals_binding_and_invalid_makes_zero_valuation_calls"],
  "a missing or malformed seal binding is INVALID")
M("score: gaps not reported", RN, "_seal_binding_problems",
  [('''                rep["seal_binding_gaps"].append({"seal": Path(p).stem, "gap": pb["reason"]})''', '''                pass''')],
  [B2 + "test_b2_the_score_reports_a_gap_without_inventing_a_change"], "the score reports seal gaps")
M("run_ack_problems: prereg binding not checked", GT, "run_ack_problems",
  [('''        if rc.binding_problem(ref) or pb != {"status": "REFERENCE", "binding": ref}:''', '''        if False:''')],
  [FX2 + "test_mt_run_ack_problems_names_a_prereg_binding_that_is_not_the_opening_reference"],
  "prereg's binding must be the opening reference")
M("binding_problem accepts any field set", RC, "binding_problem",
  [('''    if set(b) != set(BINDING_FIELDS):''', '''    if not set(BINDING_FIELDS) <= set(b):''')],
  [FX2 + "test_mt_binding_problem_requires_exactly_the_binding_fields"], "exactly the binding fields")
M("process_identity: nothing listening is not explicit", RC, "process_identity",
  [('''        got["binding"] = {GAP_FIELD: "nothing listening"}''', '''        pass''')],
  ["test_s1_receipt.py::test_process_identity_errors_never_empty"], "an unavailable binding is explicit")

# ---------------------------------------------------------------- B3
M("is_registered: the capture-report witness ignored", CM, "is_registered",
  [('''    if any((out / "seals").glob("*.json")) or _report_seals(out):''', '''    if any((out / "seals").glob("*.json")):''')],
  [B3 + "test_b3_deleting_prereg_and_the_opening_together_cannot_erase_the_registration"],
  "deleting artifacts cannot move back to pre-registration")
M("registration_problems: changed artifacts not compared", CM, "registration_problems",
  [('''            elif sha256_file(p) != h:
                probs.append(f"{rel} changed since {stage}")''', '''            elif False:
                probs.append(f"{rel} changed since {stage}")''')],
  [B3 + "test_b3_a_registered_artifact_changed_or_deleted_then_restored_stays_invalid"],
  "a changed registered artifact is the persistent abort")
M("registration_problems: missing artifacts not reported", CM, "registration_problems",
  [('''                probs.append(f"{rel} missing (bound at {stage})")''', '''                pass''')],
  [B3 + "test_b3_a_registered_artifact_changed_or_deleted_then_restored_stays_invalid"],
  "a deleted registered artifact is the persistent abort")
M("registration_problems: audit-manifest files not checked", CM, "registration_problems",
  [('''                if not (out / "audit" / n).is_file() or sha256_file(out / "audit" / n) != h:''', '''                if False:''')],
  [B3 + "test_b3_a_registered_artifact_changed_or_deleted_then_restored_stays_invalid"],
  "a changed audit file is the persistent abort")
M("registration_problems: report-bound seals not checked", CM, "registration_problems",
  [('''        if not sp.is_file() or sha256_file(sp) != h:''', '''        if False:''')],
  ["test_s1_t12_fix1.py::test_fix1_i4b_a_corrupt_trial_seal_is_a_preserved_terminal_integrity_failure"],
  "a corrupt bound seal is the persistent abort")
M("registration_problems: post-stop frozen artifacts not checked", CM, "registration_problems",
  [('''    if (out / "stop.json").exists() or "stop" in recs:''', '''    if False:''')],
  [B3 + "test_b3_post_stop_integrity_of_frozen_artifacts_is_persistent"], "post-stop integrity is persistent")
M("registration_gate records no abort", CM, "registration_gate",
  [('''    write_abort(out, {"reason": REGISTRATION_ARTIFACT, "where": where, "problems": probs, "observed_utc": t.isoformat(),''',
    '''    (lambda *a: None)(out, {"reason": REGISTRATION_ARTIFACT, "where": where, "problems": probs, "observed_utc": t.isoformat(),''')],
  [B3 + "test_b3_a_registered_artifact_changed_or_deleted_then_restored_stays_invalid"],
  "the violation is persisted (first-wins aborted.json)")
M("verify_bundle_first: an authorization failure skips the gate", CM, "verify_bundle_first",
  [('''        registration_gate(out, where, now, refuse=gate_refuses)             # B3.3 (file-only)
        if err is not None:
            raise err''', '''        if err is not None:
            raise err
        registration_gate(out, where, now, refuse=gate_refuses)             # B3.3 (file-only)''')],
  [B3 + "test_b3_a_mailbox_outage_cannot_downgrade_an_established_violation"],
  "a mailbox outage cannot downgrade an established violation")
M("record_refusal records nothing", CM, "record_refusal",
  [('''            f.write(json.dumps({"where": where, "refused": str(e), "utc": (now or now_utc)().isoformat()}) + "\\n")''',
    '''            pass''')],
  [B3 + "test_b3_an_invalid_handmade_prereg_before_the_opening_is_a_preserved_refusal_with_no_callback"],
  "a refusal is preserved")
M("load_abort: a corrupt aborted.json means no abort", CM, "load_abort",
  [('''    return {"reason": CORRUPT_ABORT, "corrupt": True, "actual": None, "close": None, "scheduled": None}''',
    '''    return None''')],
  [B3 + "test_b3_a_corrupt_aborted_json_fails_closed"], "a corrupt aborted.json fails closed")
M("do_audit: re-entry not gated", CO, "do_audit",
  [('''    c.registration_gate(out, "audit")                                    # fix round 2 (B3.3): re-entry is gated''',
    '''    pass''')],
  [B3 + "test_b3_audit_re_entry_cannot_bypass_persistence"], "audit re-entry cannot bypass persistence")
M("the opening registration is not recorded", CK, "run_opening_checkpoint",
  [('''        _register_opening(out, day["date"], rp, (cand.get("process_binding") or {}).get("binding"), seal_sha)''',
    '''        pass''')],
  [B3 + "test_b3_registration_is_recorded_independently_of_the_artifacts_it_binds"],
  "the opening is registered with its bound hashes")
M("prereg is not registered", RN, "do_prereg",
  [('''    c.register_stage(out, "prereg", {"prereg.json": c.sha256_file(out / "prereg.json")})        # B3.1''',
    '''    pass''')],
  [B3 + "test_b3_registration_is_recorded_independently_of_the_artifacts_it_binds"],
  "prereg is registered with its hash")
M("the persisted stop is not registered", SE, "persist_stop",
  [('''    c.register_stage(out, "stop", {"stop.json": c.sha256_file(p)})''', '''    pass''')],
  ["test_s1_t12_fix1.py::test_fix1_m4_a_deleted_persisted_stop_is_an_integrity_failure_not_a_recompute"],
  "stop.json is a registered frozen artifact")


# ---------------------------------------------------------------- (4) after the first fix-round-2 run: tightened
BY = {m["name"]: m for m in MUTANTS}
for name, tests in (
        ("run_ack_problems: prereg calendar not bound",
         ["test_mt_a_registered_prereg_calendar_not_the_pinned_listing_is_refused_by_the_run_ack_check"]),
        ("_claim_slot allows a duplicate execution", ["test_mt_a_duplicate_slot_execution_is_refused_before_any_capture"]),
        ("run_checkpoint: a late capture may seal", ["test_mt_a_late_or_failed_capture_is_never_a_candidate[late]"]),
        ("run_checkpoint: a failed observation may seal",
         ["test_mt_a_late_or_failed_capture_is_never_a_candidate[failed-observation]"]),
        ("run_opening_checkpoint: a late capture may seal", ["test_mt_a_late_opening_capture_is_never_a_candidate"]),
        ("persist_stop overwrites", ["test_mt_a_second_persist_never_overwrites_stop_json"]),
        ("_read_seals: a corrupt seal crashes", ["test_mt_an_unbound_corrupt_seal_is_a_preserved_abort_not_a_crash"]),
        ("run_checkpoint: a corrupt seal is not an abort",
         ["test_mt_a_deleted_stop_and_its_registry_record_is_never_recomputed_or_sealed_past"]),
        ("stop_was_persisted always false",
         ["test_mt_a_deleted_stop_and_its_registry_record_is_never_recomputed_or_sealed_past"]),
        ("attest_stop: registration not verified", ["test_mt_attest_stop_reverifies_the_run_ack"]),
        ("_complete_success accepts any candidate",
         ["test_mt_a_resolution_claiming_success_for_a_late_capture_never_seals"]),
        ("attest_start binds no process binding", ["test_mt_the_attestation_records_the_opening_binding_hash"]),
        ("the opening registration is not recorded", ["test_mt_the_opening_is_registered_with_its_seal_hash"])):
    BY[name]["tests"] = BY[name]["tests"] + [FX2 + t for t in tests]
    BY[name]["tightened"] = "fix round 2: a test whose intended assertion fails on this mutant (A10.2)"
# Equivalent under Addendum 2 B3 (documented in s1_mutants_t12_triage.txt; kept in the run, expected SURVIVED):
EQUIVALENT_B3 = {
    "_stop_state ignores the persisted stop's integrity":
        "the registration gate evaluates the SAME s1_seal.stop_problems(recheck=False) earlier in the same command "
        "(write_final_plan -> final_plan_record -> verify_bundle_first) whenever stop.json exists, so _stop_state's "
        "copy can never be the first to observe a problem",
    "_trial_end: integrity failure still demands the final manifest":
        "the score's record-only registration gate runs the same stop_problems(recheck=False) before _pre_reserve_gate "
        "and persists aborted.json on any problem, so _trial_end always takes its aborted branch first and the "
        "mutated branch is unreachable"}
for name, why in EQUIVALENT_B3.items():
    BY[name]["equivalent"] = why
