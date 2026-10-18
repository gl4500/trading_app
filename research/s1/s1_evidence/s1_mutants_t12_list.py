"""Task 12 (A10.2) targeted semantic mutant list for s1_evidence/s1_mutants_t12.py. One entry per mutant:
name, file, function (the changed function it is bound to), edits [(file, exact old text, new text)], tests (the
intended killing test node ids, relative to s1_tests/), intent (the intended assertion)."""

CM, GT, CK, CO, RC, RN, SE, SN, BK = ("s1_common.py", "s1_gates.py", "s1_checkpoint.py", "s1_collect.py",
                                      "s1_receipt.py", "s1_run.py", "s1_seal.py", "s1_snapshot.py", "s1_books.py")
A38, A2, A1, A1B, A4, A56, A7, A9, REP = ("test_s1_t12_a3_a8.py", "test_s1_t12_a2.py", "test_s1_t12_a1.py",
                                         "test_s1_t12_a1b.py", "test_s1_t12_a4.py", "test_s1_t12_a5_a6.py",
                                         "test_s1_t12_a7.py", "test_s1_t12_a9.py", "test_s1_t12_reporting.py")
MUTANTS = []


def M(name, file, function, edits, tests, intent):
    MUTANTS.append({"name": name, "file": file, "function": function,
                    "edits": [(e[0], e[1], e[2]) if len(e) == 3 else (file, e[0], e[1]) for e in edits],
                    "tests": tests, "intent": intent})


# ====================================================================== s1_common (A3 bundle, A8 tokens/mailbox)
M("bundle_manifest ignores unexpected s1_*.py", CM, "bundle_manifest",
  [('''            "unexpected": {p.name: sha256_file(p) for p in sorted(HERE.glob("s1_*.py")) if p.name not in listed},''',
    '''            "unexpected": {},''')],
  [A38 + "::test_a3_any_changed_missing_or_extra_bundle_file_or_document_changes_the_bundle"],
  "an extra s1_extra.py changes the bundle hash and is a bundle problem")
M("bundle_manifest omits the documents", CM, "bundle_manifest",
  [('''            "docs": {d: _sha_or_missing(HERE / d) for d in DOC_PINS}}''', '''            "docs": {}}''')],
  [A38 + "::test_a3_bundle_is_the_explicit_file_list_plus_the_three_document_hashes",
   A38 + "::test_a3_any_changed_missing_or_extra_bundle_file_or_document_changes_the_bundle"],
  "the manifest carries the three document hashes; a changed document changes the bundle")
M("_sha_or_missing hashes nothing (constant)", CM, "_sha_or_missing",
  [('''    return sha256_file(p) if p.is_file() else MISSING''', '''    return MISSING if not p.is_file() else "x"''')],
  [A38 + "::test_a3_bundle_is_the_explicit_file_list_plus_the_three_document_hashes"],
  "manifest code entries equal each file's sha256")
M("bundle_problems drops the missing-member check", CM, "bundle_problems",
  [('''    out = [f"bundle member {n} missing" for n, v in manifest["code"].items() if v == MISSING]''',
    '''    out = []''')],
  [A38 + "::test_a3_any_changed_missing_or_extra_bundle_file_or_document_changes_the_bundle"],
  "a missing s1_seal.py is a named bundle problem")
M("bundle_sha256 over the code list only", CM, "bundle_sha256",
  [('''    return sha256_bytes(canonical(bundle_manifest()))''', '''    return sha256_bytes(canonical(bundle_manifest()["code"]))''')],
  [A38 + "::test_a3_bundle_is_the_explicit_file_list_plus_the_three_document_hashes"],
  "bundle_sha256 == sha256(canonical(manifest))")
M("load_pinned cache keyed by name only", CM, "load_pinned",
  [('''    key = (name, str(path.resolve()), sha)''', '''    key = name''')],
  [A38 + "::test_a3_pinned_core_cache_is_keyed_by_resolved_path_and_approved_hash"],
  "the same name from another approved file is that file's module")
M("write_abort overwrites (last abort wins)", CM, "write_abort",
  [('''        with (out / "aborted.json").open("x", encoding="utf-8") as f:''',
    '''        with (out / "aborted.json").open("w", encoding="utf-8") as f:''')],
  ["test_s1_checkpoint.py::test_cr_first_abort_wins_and_a_second_returns_it",
   "test_s1_checkpoint.py::test_abort_survives_receipt_revert"],
  "a second abort returns and keeps the first record")
M("bundle_gate: a registered mismatch is a refusal only (no persistent abort)", CM, "bundle_gate",
  [('''    if registered:
        t = (now or now_utc)()''', '''    if False:
        t = (now or now_utc)()''')],
  [A38 + "::test_a3_checkpoint_bundle_mismatch_is_a_persistent_abort_before_any_helper_or_capture",
   A38 + "::test_a3_score_bundle_mismatch_aborts_reserves_nothing_and_restoration_scores_aborted_invalid"],
  "aborted.json reason bundle is written and persists after restoration")
M("bundle_gate accepts any bundle", CM, "bundle_gate",
  [('''    if observed == expected:
        return observed''', '''    if True:
        return observed''')],
  [A38 + "::test_a3_checkpoint_bundle_mismatch_is_a_persistent_abort_before_any_helper_or_capture",
   A38 + "::test_a3_opening_checkpoint_bundle_mismatch_refuses_with_zero_callbacks_and_no_abort"],
  "a changed bundle refuses before any capture")
M("mailbox_message accepts any sender", CM, "mailbox_message",
  [('''    if row is None or row[:3] != ("codex", "claude", "experiments-prereg"):''', '''    if row is None:''')],
  ["test_s1_t12_mutant_survivors.py::test_ms_a_message_from_another_sender_carrying_the_exact_token_is_not_an_ack", "test_s1_collect.py::test_audit_refuses_without_exact_ack_and_makes_no_request",
   "test_s1_t12_a3_a8.py::test_a8_hand_made_prereg_reaches_no_live_callback",
   "test_s1_run.py::test_mismatched_or_duplicate_acks_make_no_request_no_output"],
  "only codex->claude experiments-prereg messages are ACKs")
M("ack accepts an embedded (non-standalone) token", CM, "ack",
  [('''    if token not in m["lines"]:''', '''    if not any(token in ln for ln in m["lines"]):''')],
  ["test_s1_collect.py::test_ack_future_missing_or_embedded_token_is_refused"],
  "an embedded token line is refused")
M("ack accepts a future ACK", CM, "ack",
  [('''    if aware(m["created_utc"]) > now_utc():''', '''    if False:''')],
  ["test_s1_collect.py::test_ack_future_missing_or_embedded_token_is_refused"],
  "an ACK in the future is refused")
M("token_fields keeps only the first field", CM, "token_fields",
  [('''    return dict(x.split("=", 1) for x in line.split(" ") if "=" in x)''',
    '''    return dict([x.split("=", 1) for x in line.split(" ") if "=" in x][:1])''')],
  [A38 + "::test_a3_checkpoint_bundle_mismatch_is_a_persistent_abort_before_any_helper_or_capture",
   A38 + "::test_a8_valid_registration_reaches_the_capture"],
  "the bundle field is parsed from the RUN-ACK line")
M("ack_line takes the first of several lines", CM, "ack_line",
  [('''    if len(got) != 1:''', '''    if not got:''')],
  ["test_s1_t12_mutant_followups.py::test_mf_an_ack_message_with_two_run_lines_refuses"],
  "an ACK with two prefix lines is ambiguous and refuses")
M("load_json reads nothing (empty dict)", CM, "load_json",
  [('''def load_json(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8"))''', '''def load_json(p: Path):
    return {}''')],
  [A38 + "::test_a8_valid_registration_reaches_the_capture"], "load_json returns the file's JSON")
M("sha_or_absent always absent", CM, "sha_or_absent",
  [('''    return sha256_file(p) if Path(p).exists() else ABSENT''', '''    return ABSENT''')],
  [A38 + "::test_a8_run_ack_binds_opening_seal_frozen_opening_books_audit_attestation_and_bundle"],
  "tokens bind the attestation/opening seal/books hashes")
M("receipt_sha256 hashes the whole receipt (provenance compared)", CM, "receipt_sha256",
  [('''    return sha256_bytes(canonical(receipt["fingerprint"]))''', '''    return sha256_bytes(canonical(receipt))''')],
  [A1 + "::test_a1_a_head_or_dirty_change_alone_seals_and_is_recorded_as_provenance"],
  "a HEAD-only change keeps the seal's receipt hash = the fingerprint's")
M("receipt_sha256 accepts a fingerprint-less receipt", CM, "receipt_sha256",
  [('''    if not isinstance(receipt, dict) or not isinstance(receipt.get("fingerprint"), dict):
        raise ValueError("receipt has no fingerprint (missing required evidence)")''', '''    if not isinstance(receipt, dict):
        raise ValueError("receipt has no fingerprint (missing required evidence)")''')],
  ["test_s1_t12_mutant_survivors.py::test_ms_receipt_sha256_refuses_a_receipt_without_fingerprint", A9 + "::test_a9_missing_required_evidence_never_becomes_a_plausible_match"],
  "missing fingerprint never matches / never seals")
M("opening_seal_path names a fixed file", CM, "opening_seal_path",
  [('''    return Path(out) / "seals" / f"{plan.get('opening_close')}.json"''', '''    return Path(out) / "seals" / "opening.json"''')],
  [A38 + "::test_a8_run_ack_binds_opening_seal_frozen_opening_books_audit_attestation_and_bundle"],
  "RUN token binds the opening seal's sha")
M("audit_token without the bundle", CM, "audit_token",
  [('''                            bundle=bundle_sha256(), start=plan["planned_start"])''', '''                            bundle="none", start=plan["planned_start"])''')],
  [A38 + "::test_a8_audit_manifest_binds_the_plan_and_the_audit_ack_binds_the_bundle"],
  "the AUDIT-ACK token carries the bundle")
M("run_token binds no opening books", CM, "run_token",
  [('''                          books=sha_or_absent(out / "opening_books.json"), bundle=bundle_sha256(),''',
    '''                          books=ABSENT, bundle=bundle_sha256(),''')],
  [A38 + "::test_a8_run_ack_binds_opening_seal_frozen_opening_books_audit_attestation_and_bundle"],
  "the RUN token binds opening_books_sha256")
M("acquire_token binds no stop attestation", CM, "acquire_token",
  [('''                              attest=sha_or_absent(out / "attest_stop.json"), bundle=bundle_sha256())''',
    '''                              attest=ABSENT, bundle=bundle_sha256())''')],
  ["test_s1_task11.py::test_i4_acquire_ack_binds_the_stop_attestation_and_do_final_records_the_plan"],
  "ACQUIRE-ACK binds attest_stop_sha256")
M("score_token binds no persisted stop", CM, "score_token",
  [('''                            stop=sha_or_absent(out / "stop.json"), bundle=bundle_sha256())''',
    '''                            stop=ABSENT, bundle=bundle_sha256())''')],
  ["test_s1_t12_mutant_followups.py::test_mf_the_score_ack_binds_the_persisted_stop"],
  "a stop.json edited after the SCORE-ACK makes that ACK stale (refused, nothing written)")
M("registration: prereg bundle not cross-checked with its RUN-ACK", CM, "registration",
  [('''        if not b or pr.get("bundle_sha256") != b:''', '''        if not b:''')],
  ["test_s1_t12_mutant_survivors.py::test_ms_registration_refuses_a_prereg_whose_bundle_differs_from_its_run_ack", A38 + "::test_a3_score_checks_bundle_consistency_across_every_artifact[prereg]"],
  "a prereg recording another bundle than its RUN-ACK refuses")
M("registration: audit stage never registered", CM, "registration",
  [('''        return {"stage": "audit", "bundle": b, "registered": opening_seal_path(out, plan).exists(),''',
    '''        return {"stage": "audit", "bundle": b, "registered": False,''')],
  [A38 + "::test_a3_r1_attest_start_and_prereg_refuse_a_bundle_differing_from_the_opening_seal"],
  "from the opening seal on a mismatch is the persistent bundle abort")
M("verify_bundle_first: no prereg requirement", CM, "verify_bundle_first",
  [('''    if need == "prereg" and reg["stage"] != "prereg":''', '''    if False:''')],
  ["test_s1_t12_mutant_survivors.py::test_ms_verify_bundle_first_needs_a_prereg_when_asked", "test_s1_checkpoint_7b.py::test_final_snapshot_refuses_without_prereg_and_while_running",
   A38 + "::test_a8_hand_made_prereg_reaches_no_live_callback"],
  "post-prereg commands refuse without a verified prereg")

# ====================================================================== s1_gates (A8 verification, A7.4 pages)
M("attempt does not re-verify raw pages", GT, "attempt",
  [('''        if not p.is_file() or c.sha256_file(p) != h:
            raise Invalid(f"{d.name}: raw page {rel} missing or differs from its manifest hash")''',
    '''        pass''')],
  [A38 + "::test_a8_opening_mode_verifies_the_audit_ack_plan_calendar_and_source_bindings_before_capture[raw_page_tampered]",
   A7 + "::test_a7_4_a_tampered_final_raw_page_is_an_integrity_failure_at_score"],
  "a tampered raw page refuses (opening) / is ABORTED-INVALID (score)")
M("attempt accepts a non-COMPLETE manifest", GT, "attempt",
  [('''    if not isinstance(m, dict) or m.get("outcome") != "COMPLETE":''', '''    if not isinstance(m, dict):''')],
  ["test_s1_checkpoint_7b.py::test_opening_mode_refuses_an_incomplete_audit",
   "test_s1_run.py::test_cr_incomplete_audit_is_a_recorded_reason_not_a_score_error"],
  "an ABORTED audit is refused")
M("verify_audit_ack skips the token check", GT, "verify_audit_ack",
  [('''    if c.audit_token(out) not in msg["lines"]:''', '''    if False:''')],
  ["test_s1_t12_mutant_survivors.py::test_ms_an_audit_ack_message_without_the_exact_audit_token_refuses", A38 + "::test_a8_opening_mode_verifies_the_audit_ack_plan_calendar_and_source_bindings_before_capture[plan_edited_after_audit]"],
  "a plan edited after its audit refuses the opening")
M("verify_audit_ack: ACK before the plan accepted", GT, "verify_audit_ack",
  [('''    if not t > c.aware(plan["created_utc"]):''', '''    if False:''')],
  ["test_s1_t12_mutant_survivors.py::test_ms_audit_ack_causal_timing_is_checked_on_its_own", A38 + "::test_a8_opening_mode_verifies_the_audit_ack_plan_calendar_and_source_bindings_before_capture[ack_before_plan]"],
  "an AUDIT-ACK before the plan refuses")
M("verify_audit_ack: ACK after the reservation accepted", GT, "verify_audit_ack",
  [('''    if not t < reserved:''', '''    if False:''')],
  ["test_s1_t12_mutant_survivors.py::test_ms_audit_ack_causal_timing_is_checked_on_its_own", A38 + "::test_a8_opening_mode_verifies_the_audit_ack_plan_calendar_and_source_bindings_before_capture[ack_after_reservation]"],
  "an AUDIT-ACK after the audit reservation refuses")
M("verified_audit: plan binding not checked", GT, "verified_audit",
  [('''    if m.get("plan_sha256") != c.sha256_file(out / "plan.json"):''', '''    if False:''')],
  [A38 + "::test_a8_opening_mode_verifies_the_audit_ack_plan_calendar_and_source_bindings_before_capture[manifest_plan_sha]"],
  "an audit manifest bound to another plan refuses")
M("verified_audit: calendar completeness skipped", GT, "verified_audit",
  [('''    probs = z.calendar_pin_problems(out, m, files, plan) + z.calendar_problems(files["calendar.json"], plan)''',
    '''    probs = z.calendar_pin_problems(out, m, files, plan)''')],
  ["test_s1_t12_mutant_survivors.py::test_ms_an_out_of_order_pinned_listing_refuses_the_opening", "test_s1_checkpoint_7b.py::test_cr_opening_refuses_when_the_audit_calendar_ends_at_the_opening_day"],
  "a pinned listing that does not cover the deadline+lag refuses the opening")
M("run_ack_problems skips the token", GT, "run_ack_problems",
  [('''        if c.run_token(out) not in msg["lines"]:''', '''        if False:''')],
  ["test_s1_t12_mutant_survivors.py::test_ms_a_run_ack_message_not_carrying_the_exact_run_token_refuses", A38 + "::test_a8_checkpoint_verifies_the_run_ack_identity_bindings_and_timing_before_capture[plan_edited]"],
  "an artifact edited after prereg refuses the checkpoint with zero callbacks")
M("run_ack_problems: ACK after START accepted", GT, "run_ack_problems",
  [('''        if not t < c.aware(pr["start"]):''', '''        if False:''')],
  ["test_s1_t12_mutant_survivors.py::test_ms_a_run_ack_after_planned_start_is_reported_on_its_own", A38 + "::test_a8_checkpoint_verifies_the_run_ack_identity_bindings_and_timing_before_capture[ack_after_start]"],
  "a RUN-ACK after planned START refuses")
M("run_ack_problems: prereg calendar not bound", GT, "run_ack_problems",
  [('''            probs.append("prereg calendar is not the audit's pinned calendar")''', '''            pass''')],
  [A56 + "::test_a6_a_dropped_session_relative_to_the_pinned_listing_refuses",
   "test_s1_bridge_8b.py::test_opening_close_error_is_a_recorded_refusal_not_a_crash"],
  "a prereg calendar differing from the pinned listing refuses the checkpoint")
M("verified_registration ignores problems", GT, "verified_registration",
  [('''    if probs:
        raise SystemExit(f"{where} refused: registration not verified: {probs}")''', '''    if False:
        raise SystemExit(f"{where} refused: registration not verified: {probs}")''')],
  [A38 + "::test_a8_checkpoint_verifies_the_run_ack_identity_bindings_and_timing_before_capture[plan_edited]"],
  "an unverifiable registration refuses with zero callbacks")
