"""Task 12 (A10.2) targeted mutants, part 3: s1_collect, s1_receipt, s1_run, s1_books (see s1_mutants_t12_list.py).
Includes the Codex-named helpers _out, _seals, _sha_or_absent, _ack, _write_once and report serialisation."""
from s1_mutants_t12_list import A1, A1B, A2, A38, A4, A56, A7, A9, BK, CO, M, RC, REP, RN

MF = "test_s1_t12_mutant_followups.py"

# ====================================================================== s1_collect (A3, A5.4, A6, A7, A8)
M("_ack bypasses the shared reader (no future check)", CO, "_ack",
  [('''    return c.ack(ack_id, token, mailbox)''',
    '''    m = c.mailbox_message(ack_id, mailbox)
    if token not in m["lines"]:
        raise SystemExit(f"ack lacks the standalone line: {token}")
    return {"ack_id": ack_id, "created_utc": m["created_utc"]}''')],
  ["test_s1_collect.py::test_ack_future_missing_or_embedded_token_is_refused"], "a future ACK is refused")
M("_approved_bundle returns nothing (no bundle check at the audit)", CO, "_approved_bundle",
  [('''        return c.token_fields(c.ack_line(c.mailbox_message(ack_id, mailbox), prefix)).get("bundle_sha256")''',
    '''        return c.bundle_sha256()''')],
  [MF + "::test_mf_do_audit_refuses_an_ack_for_another_bundle_before_any_request"],
  "an AUDIT-ACK approving another bundle refuses before any request")
M("do_audit: an ACK before the plan accepted", CO, "do_audit",
  [('''    if not c.aware(ack["created_utc"]) > c.aware(plan["created_utc"]):''', '''    if False:''')],
  [A38 + "::test_a8_do_audit_checks_the_ack_is_after_the_plan"], "an AUDIT-ACK before its plan refuses")
M("do_audit.body: no calendar pin written", CO, "do_audit.body",
  [('''        _write_once(d / "calendar_source.json", {"source": CAL_URL, "params": params,              # A6 pin''',
    '''        (lambda *a: None)(d / "calendar_source.json", {"source": CAL_URL, "params": params,              # A6 pin''')],
  [A56 + "::test_a6_the_audit_pins_the_calendar_source_parameters_retrieval_time_and_raw_page"],
  "the audit pins calendar_source.json")
M("do_audit: manifest does not bind the plan", CO, "do_audit",
  [('''                                                      "plan_sha256": c.sha256_file(out / "plan.json"),   # A8.1''',
    '''                                                      "plan_sha256": None,   # A8.1''')],
  [A38 + "::test_a8_audit_manifest_binds_the_plan_and_the_audit_ack_binds_the_bundle",
   MF + "::test_mf_do_audit_manifest_binds_plan_and_bundle"],
  "the audit manifest binds plan_sha256")
M("_validate_calendar counts sessions from the plan (A5.4 regression)", CO, "_validate_calendar",
  [('''    start, acked = c.aware(plan["planned_start"]), c.aware(ack["created_utc"])''',
    '''    start, acked = c.aware(plan["planned_start"]), c.aware(plan["created_utc"])''')],
  [A56 + "::test_a5_five_sessions_are_counted_from_the_audit_acks_recorded_time"],
  ">= 5 sessions count from the AUDIT-ACK's time")
M("_validate_calendar: 4 sessions accepted", CO, "_validate_calendar",
  [('''    if sum(1 for _, o in sessions if acked < o < start) < MIN_SESSIONS_BEFORE_START:''',
    '''    if sum(1 for _, o in sessions if acked < o < start) < MIN_SESSIONS_BEFORE_START - 1:''')],
  ["test_s1_t12_mutant_survivors.py::test_ms_four_sessions_after_the_audit_ack_abort", A56 + "::test_a5_five_sessions_are_counted_from_the_audit_acks_recorded_time"], "3 sessions after the ACK abort")
M("write_plan: generic +200 days range", CO, "write_plan",
  [('''    dl = (deadline.astimezone(c.NY).date() + timedelta(days=CAL_TAIL_DAYS)).isoformat()''',
    '''    dl = (planned_start + timedelta(days=200)).date().isoformat()''')],
  [A56 + "::test_a5_plan_records_the_deadline_instant_and_a_derived_calendar_range"],
  "calendar range end = deadline date + CAL_TAIL_DAYS")
M("write_plan records the deadline date", CO, "write_plan",
  [('''        "deadline": deadline.isoformat(),''', '''        "deadline": deadline.date().isoformat(),''')],
  [A56 + "::test_a5_plan_records_the_deadline_instant_and_a_derived_calendar_range"], "plan deadline is an instant")
M("reconcile_actions: conflicts silently kept (no problem)", CO, "reconcile_actions",
  [('''            problems.append({"problem": "conflicting records for one provider action identity", "id": rid,''',
    '''            (lambda x: None)({"problem": "conflicting records for one provider action identity", "id": rid,''')],
  [A7 + "::test_a7_2_identical_records_are_kept_once_and_a_conflict_blocks_the_union_of_symbols",
   A7 + "::test_a7_2_codex_probe_i_window_and_full_history_records_are_reconciled_at_the_acquisition"],
  "one identity with differing records is a conflict problem")
M("reconcile_actions: type-scoped identity", CO, "reconcile_actions",
  [('''            rid = rec.get("id")
            if not (isinstance(rid, str) and rid):''', '''            rid = (rec.get("type"), rec.get("id")) if rec.get("id") else None
            if not rid:''')],
  [A7 + "::test_a7_2_the_identity_is_the_provider_id_alone_not_type_scoped"], "a changed type under one id conflicts")
M("reconcile_actions: conflict blocks only the first record's symbols", CO, "reconcile_actions",
  [('''                          | set(first.get("affected_symbols") or []) | set(rec.get("affected_symbols") or []))''',
    '''                          & set(first.get("affected_symbols") or []))''')],
  [A7 + "::test_a7_2_identical_records_are_kept_once_and_a_conflict_blocks_the_union_of_symbols"],
  "a conflict blocks the union of affected symbols")
M("_identity_view ignores dates", CO, "_identity_view",
  [('''    return {k_: v for k_, v in rec.items() if k_ in RECONCILE_KEYS or k_.endswith("_date") or k_.endswith("_symbol")''',
    '''    return {k_: v for k_, v in rec.items() if k_ in RECONCILE_KEYS or k_.endswith("_symbol")''')],
  [A7 + "::test_a7_2_identical_records_are_kept_once_and_a_conflict_blocks_the_union_of_symbols"],
  "a moved date is a conflict")
M("do_final.body: window and full history not reconciled", CO, "do_final.body",
  [('''        actions, conflicts = reconcile_actions(ca_win, ca_full)          # Task 12 (A7.2): one global set''',
    '''        actions, conflicts = ca_win + ca_full, []          # Task 12 (A7.2): one global set''')],
  [A7 + "::test_a7_2_codex_probe_i_window_and_full_history_records_are_reconciled_at_the_acquisition"],
  "the acquisition reconciles window + full history")
M("do_final: registration not verified", CO, "do_final",
  [('''    g.verified_registration(out, "final acquisition", mailbox)        # Task 12: A3.2 bundle first, then A8.2''',
    '''    pass''')],
  [A38 + "::test_a3_final_acquisition_verifies_the_bundle_before_any_request"], "do_final checks the bundle first")
M("do_final: manifest binds no bundle", CO, "do_final",
  [('''        "bundle_sha256": c.bundle_sha256(),                                                    # Task 12 (A3.4)''',
    '''        "bundle_sha256": None,                                                    # Task 12 (A3.4)''')],
  [MF + "::test_mf_the_final_manifest_binds_the_bundle_and_the_persisted_stop"], "the final manifest binds the bundle")
M("_stop_state ignores the persisted stop's integrity", CO, "_stop_state",
  [('''    probs = s1_seal.stop_problems(out, c.aware(pr["start"]), pr["calendar"], recheck=False)
    if probs:
        raise SystemExit(f"final plan refused: the persisted stop does not verify ({probs})")''', '''    probs = []''')],
  [MF + "::test_mf_the_final_plan_refuses_a_changed_frozen_slice"], "a changed frozen slice refuses the final plan")
M("final_plan_record binds no persisted stop", CO, "final_plan_record",
  [('''            "stop_seal_sha256": c.sha256_file(stop_p), "stop_sha256": c.sha256_file(out / "stop.json"),''',
    '''            "stop_seal_sha256": c.sha256_file(stop_p), "stop_sha256": None,''')],
  [MF + "::test_mf_the_final_plan_binds_the_persisted_stop"], "the final plan binds stop.json")
M("write_final_plan without the stop attestation check", CO, "write_final_plan",
  [('''    _stop_attestation(_out(root), rec)
    return _write_once(_out(root) / "final_plan.json", rec)''', '''    return _write_once(_out(root) / "final_plan.json", rec)''')],
  ["test_s1_task11.py::test_i4_final_plan_refused_without_the_stop_attestation"], "no final plan before attest_stop")
M("_stop_attestation (collect) ignores stop.json", CO, "_stop_attestation",
  [('''                and a.get("stop_sha256") == plan.get("stop_sha256"))                  # Task 12 (A2.1/A7.1)''',
    '''                and True)                  # Task 12 (A2.1/A7.1)''')],
  [MF + "::test_mf_the_final_plan_binds_the_persisted_stop"], "the attestation must bind the persisted stop")
M("_require_no_redirects accepts any client", CO, "_require_no_redirects",
  [('''    if getattr(client, "follow_redirects", None) is not False:''', '''    if False:''')],
  ["test_s1_task11.py::test_m4_collectors_refuse_a_client_that_may_follow_redirects"], "a redirect-following client refuses")
M("collect _load reads nothing", CO, "_load",
  [('''def _load(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8"))''', '''def _load(p: Path):
    return {}''')],
  ["test_s1_task11.py::test_i4_final_plan_is_derived_from_the_stop_seal"], "the final plan reads the stop seal")
M("collect audit_token not the shared one", CO, "audit_token",
  [('''    return c.audit_token(_out(root))''', '''    return c.audit_token(_out(root)).replace(" bundle_sha256=", " bundle=")''')],
  [A38 + "::test_a8_audit_manifest_binds_the_plan_and_the_audit_ack_binds_the_bundle"], "the audit token binds the bundle")
M("collect acquire_token drops the bundle", CO, "acquire_token",
  [('''    return c.acquire_token(_out(root))''', '''    return c.acquire_token(_out(root)).split(" bundle_sha256=")[0]''')],
  [A38 + "::test_a3_run_acquire_score_tokens_prereg_and_every_seal_bind_the_bundle"], "ACQUIRE-ACK binds the bundle")

# ====================================================================== s1_receipt (A1)
M("contract ignores the env override", RC, "contract",
  [('''    if env_required is not None:
        ct["config"]["env_required"] = env_required''', '''    if False:
        ct["config"]["env_required"] = env_required''')],
  [A1 + "::test_a1_a_missing_required_env_fails_explicitly_and_an_optional_one_is_recorded_absent"],
  "a reviewed alternate contract records an absent .env")
M("key_id independent of the key", RC, "key_id",
  [('''    return hashlib.sha256(b"s1-receipt-hmac-key-id\\0" + key).hexdigest()''',
    '''    return hashlib.sha256(b"s1-receipt-hmac-key-id\\0").hexdigest()''')],
  [A1 + "::test_a1_the_hmac_key_is_created_once_outside_s1_out_and_its_identity_is_bound"],
  "a new key changes the fingerprint (key id bound)")
M("load_or_create_key recreates the key every call", RC, "load_or_create_key",
  [('''    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)''', '''    if True:
        p.unlink(missing_ok=True)
        p.parent.mkdir(parents=True, exist_ok=True)''')],
  [A1 + "::test_a1_the_hmac_key_is_created_once_outside_s1_out_and_its_identity_is_bound"], "the key is created once")
M("_hmac unkeyed (plain sha256 of the secret)", RC, "_hmac",
  [('''    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()''',
    '''    return hashlib.sha256(value.encode("utf-8")).hexdigest()''')],
  [MF + "::test_mf_the_secret_fingerprint_is_keyed"], "the secret fingerprint depends on the key")
M("_imported_modules: missing members silently skipped", RC, "_imported_modules",
  [('''    if missing:
        raise ReceiptError(f"closure member(s) {sorted(set(missing))} imported by {rel} missing", terminal=True)''',
    '''    if False:
        raise ReceiptError(f"closure member(s) {sorted(set(missing))} imported by {rel} missing", terminal=True)''')],
  [A1 + "::test_a1_a_new_closure_member_changes_the_fingerprint_and_a_missing_member_fails"],
  "a missing in-repo member is a receipt failure")
M("_in_repo never true", RC, "_in_repo",
  [('''    return bool(parts) and ((backend / f"{parts[0]}.py").exists() or (backend / parts[0]).is_dir())''',
    '''    return False''')],
  ["test_s1_receipt.py::test_dirty_lists_any_extension_and_renames"], "a renamed (missing) member fails the receipt")
M("_namespace_dir always true", RC, "_namespace_dir",
  [('''    return d is not None and d.is_dir() and not (d / "__init__.py").exists()''', '''    return True''')],
  [A1 + "::test_a1_a_new_closure_member_changes_the_fingerprint_and_a_missing_member_fails"],
  "a missing submodule of a namespace package fails")
M("closure root check skipped", RC, "closure",
  [('''    missing = [r for r in roots if not (backend / r).exists()]''', '''    missing = []''')],
  ["test_s1_receipt.py::test_missing_root_raises"], "a missing root raises")
M("_mr_config_keys drops secret keys again", RC, "_mr_config_keys",
  [('''    return sorted(k for k in keys if include_secrets or not SECRET.search(k))''',
    '''    return sorted(k for k in keys if not SECRET.search(k))''')],
  [A1 + "::test_a1_secret_named_fields_are_bound_by_name_presence_and_keyed_hmac_never_raw"],
  "secret-named MR keys are bound (by HMAC)")
M("_git_status: untracked files not listed", RC, "_git_status",
  [('''    out = subprocess.run([*GIT, "-C", str(repo), "status", "--porcelain=v1", "-z", "--no-renames", "-uall"],''',
    '''    out = subprocess.run([*GIT, "-C", str(repo), "status", "--porcelain=v1", "-z", "--no-renames", "-uno"],''')],
  [A1 + "::test_a1_sqlite_sidecars_logs_and_caches_appearing_or_disappearing_are_provenance_only"],
  "transient files appear in the provenance")
M("_dirty_backend includes untracked non-.py", RC, "_dirty_backend",
  [('''    return sorted(p for code, p in _git_status(repo) if p.startswith("backend/") and (code != "??" or p.endswith(".py")))''',
    '''    return sorted(p for code, p in _git_status(repo) if p.startswith("backend/"))''')],
  ["test_s1_task11.py::test_i2_untracked_non_py_runtime_files_do_not_change_the_receipt"],
  "sidecars are not in the dirty list")
M("_transient lists nothing", RC, "_transient",
  [('''    return sorted(p for code, p in _git_status(repo) if p.startswith("backend/") and code == "??"
                  and not p.endswith(".py"))''', '''    return []''')],
  [A1 + "::test_a1_sqlite_sidecars_logs_and_caches_appearing_or_disappearing_are_provenance_only"],
  "transient files are recorded as provenance")
M("_runtime: missing required runtime tolerated", RC, "_runtime",
  [('''        if rt["required"]:
            raise ReceiptError(f"required runtime {rt['python']} missing", terminal=True)''', '''        if False:
            raise ReceiptError(f"required runtime {rt['python']} missing", terminal=True)''')],
  [A1 + "::test_a1_a_missing_required_runtime_fails_explicitly"], "a missing required runtime fails")
M("_runtime ignores site-packages", RC, "_runtime",
  [('''        res = subprocess.run([str(py), "-I", "-c", _RUNTIME_CODE, str(sp) if sp and sp.is_dir() else ""],''',
    '''        res = subprocess.run([str(py), "-I", "-c", _RUNTIME_CODE, ""],''')],
  [A1 + "::test_a1_the_runtime_binds_python_and_the_backends_site_packages"], "site-packages versions are bound")
M("semantic_receipt: missing required .env -> empty values", RC, "semantic_receipt",
  [('''        if cfg["env_required"]:
            raise ReceiptError(f"required config source {cfg['env_file']} (.env) missing", terminal=True)''',
    '''        if False:
            raise ReceiptError(f"required config source {cfg['env_file']} (.env) missing", terminal=True)''')],
  [A1 + "::test_a1_a_missing_required_env_fails_explicitly_and_an_optional_one_is_recorded_absent"],
  "a missing required .env fails explicitly")
M("semantic_receipt: HEAD in the fingerprint", RC, "semantic_receipt",
  [('''                   "runtime": _runtime(repo, runtime_python, ct), "key_id": kid}''',
    '''                   "runtime": _runtime(repo, runtime_python, ct), "key_id": kid, "head": head}''')],
  [A1 + "::test_a1_an_unrelated_commit_or_checkout_does_not_change_the_fingerprint"],
  "an unrelated commit changes provenance only")
M("semantic_receipt: resources not bound", RC, "semantic_receipt",
  [('''        if p.is_file():
            resources[res["path"]] = c.sha256_file(p)''', '''        if p.is_file():
            resources[res["path"]] = "present"''')],
  [A1 + "::test_a1_a_relevant_non_python_resource_is_bound_by_presence_and_hash_independent_of_git"],
  "a registered resource is bound by sha256")
M("semantic_receipt: transport keys compared", RC, "semantic_receipt",
  [('''              if k not in transport_keys and not secret.search(k)}''', '''              if not secret.search(k)}''')],
  [A1 + "::test_a1_receipt_separates_the_compared_fingerprint_from_informational_provenance"],
  "HOST is provenance only")
M("sanitize_cmdline masks nothing", RC, "sanitize_cmdline",
  [('''        if eq and SECRET.search(name.strip('"').lstrip("-/")):''', '''        if False:''')],
  [A1B + "::test_a1b_command_line_is_sanitized_secret_values_masked"], "secret option values are masked")
M("process_identity reports no binding", RC, "process_identity",
  [('''    if exe or cmd:''', '''    if False:''')],
  [A1B + "::test_a1b_process_identity_reports_the_binding"], "the process observation carries the binding")
M("ReceiptError defaults to transient", RC, "ReceiptError.__init__",
  [('''    def __init__(self, msg: str, terminal: bool = True):''', '''    def __init__(self, msg: str, terminal: bool = False):''')],
  [MF + "::test_mf_a_receipt_error_is_terminal_unless_declared_transient"], "missing inputs are terminal by default")

# ====================================================================== s1_run (A1, A2, A3, A4, A7, A8, A9 and the named helpers)
M("_out points elsewhere", RN, "_out",
  [('''def _out(root) -> Path:
    return Path(root) / "s1_out"''', '''def _out(root) -> Path:
    return Path(root) / "s1_out_x"''')],
  ["test_s1_run.py::test_attest_start_requires_exact_statement_once_and_before_start"],
  "the runner reads and writes s1_out/")
M("_seals returns none", RN, "_seals",
  [('''def _seals(out: Path) -> list:
    return [(p, _load(p)) for p in sorted((out / "seals").glob("*.json"))]''', '''def _seals(out: Path) -> list:
    return []''')],
  ["test_s1_t12_mutant_survivors.py::test_ms_runner_seals_lists_every_seal_file", "test_s1_checkpoint_7b.py::test_full_synthetic_lifecycle_uses_the_real_opening_seal_and_final_snapshot"],
  "the score reads every seal")
M("_sha_or_absent always absent", RN, "_sha_or_absent",
  [('''def _sha_or_absent(p: Path) -> str:
    return c.sha256_file(p) if p.exists() else ABSENT''', '''def _sha_or_absent(p: Path) -> str:
    return ABSENT''')],
  [MF + "::test_mf_runner_sha_or_absent_hashes_an_existing_file"], "an existing file's sha256, absent otherwise")
M("_ack: an unreadable mailbox crashes", RN, "_ack",
  [('''    except sqlite3.Error as e:
        raise SystemExit(f"mailbox unreadable ({type(e).__name__}): refusing") from None''', '''    except ZeroDivisionError as e:
        raise SystemExit(f"mailbox unreadable ({type(e).__name__}): refusing") from None''')],
  [MF + "::test_mf_runner_ack_unreadable_mailbox_is_a_refusal"], "an unreadable mailbox is a refusal")
M("_write_once overwrites", RN, "_write_once",
  [('''    try:
        k._write_once(path, obj)
    except FileExistsError:
        raise SystemExit(f"{what} already recorded: refusing") from None''', '''    path.write_text(json.dumps(obj), encoding="utf-8")''')],
  ["test_s1_t12_mutant_survivors.py::test_ms_runner_write_once_refuses_and_keeps_the_first", "test_s1_run.py::test_attest_start_requires_exact_statement_once_and_before_start"],
  "a second START attestation is refused, the first kept")
M("_clean keeps private keys (report serialisation)", RN, "_clean",
  [('''        return {str(key): _clean(v) for key, v in obj.items() if not (isinstance(key, str) and key.startswith("_"))}''',
    '''        return {str(key): _clean(v) for key, v in obj.items()}''')],
  [MF + "::test_mf_the_score_report_has_no_private_keys_and_no_secret"], "no '_'-prefixed key is serialised")
M("_serialise unsorted / unclean", RN, "_serialise",
  [('''    return json.dumps(_clean(rep), indent=1, sort_keys=True)''', '''    return json.dumps(rep, indent=1, sort_keys=True, default=str)''')],
  [MF + "::test_mf_the_score_report_has_no_private_keys_and_no_secret"], "serialisation goes through _clean")
M("_books_record keeps no economic lots", RN, "_books_record",
  [('''             "rem_qty": str(l["rem_qty"])} for l in b.economic_lots(rows, end) if l["rem_qty"] > 0]''',
    '''             "rem_qty": str(l["rem_qty"])} for l in [] if l["rem_qty"] > 0]''')],
  [A38 + "::test_a8_run_ack_binds_opening_seal_frozen_opening_books_audit_attestation_and_bundle"],
  "the frozen opening books list the open lots")
M("_opening_books accepts a changed existing file", RN, "_opening_books",
  [('''        if _load(p) != json.loads(json.dumps(rec, sort_keys=True)):''', '''        if False:''')],
  [MF + "::test_mf_an_edited_opening_books_file_refuses_the_start_attestation"],
  "an existing opening_books.json must equal the recomputation")
M("attest_start: not after the opening seal's capture", RN, "attest_start",
  [('''    if c.now_utc() <= c.aware(cap.get("capture_end") or cap.get("actual")):''', '''    if False:''')],
  [A38 + "::test_a8_attest_start_refuses_before_the_opening_seal_capture"], "the attestation follows the opening seal")
M("attest_start: bundle not verified first", RN, "attest_start",
  [('''    c.verify_bundle_first(out, "START attestation", mailbox=mailbox, need="audit")''', '''    pass''')],
  [A38 + "::test_a3_r1_attest_start_and_prereg_refuse_a_bundle_differing_from_the_opening_seal"],
  "R-1: a changed bundle at the attestation is the persistent abort")
M("do_prereg: resumes after an abort", RN, "do_prereg",
  [('''        raise SystemExit("prereg refused: the registration is ABORTED-INVALID (aborted.json)")''', '''        pass''')],
  [A38 + "::test_a3_r1_attest_start_and_prereg_refuse_a_bundle_differing_from_the_opening_seal"],
  "restoring files never resumes the registration")
M("do_prereg: no pre-START bound", RN, "_blocked_reasons",
  [('''            + carry_in_reasons(held, actions, since, problems=problems, until=_pre_start_day(start)))''',
    '''            + carry_in_reasons(held, actions, since, problems=problems))''')],
  [A4 + "::test_a4_1_prereg_bounds_the_opening_audit_to_actions_effective_before_start"],
  "a pre-announced post-START action does not BLOCK")
M("_pre_start_day is START's day", RN, "_pre_start_day",
  [('''    return (start.astimezone(c.NY).date() - timedelta(days=1)).isoformat()''',
    '''    return (start.astimezone(c.NY).date() + timedelta(days=1)).isoformat()''')],
  ["test_s1_t12_mutant_survivors.py::test_ms_an_action_effective_on_the_start_day_does_not_block_the_registration", A4 + "::test_a4_1_prereg_bounds_the_opening_audit_to_actions_effective_before_start"], "the bound is before START")
M("effective_date falls back to process_date (A7.3 regression)", RN, "effective_date",
  [('''    if field is None or not _valid_date(a.get(field)):
        return None''', '''    if field is None or not _valid_date(a.get(field)):
        return a.get("process_date") if _valid_date(a.get("process_date")) else None''')],
  [A4 + "::test_a7_no_processing_or_publication_date_is_an_effective_date"], "process_date is never an effective date")
M("effective_date ignores ambiguity", RN, "effective_date",
  [('''    return a[field] if len(vals) == 1 else None''', '''    return a[field]''')],
  [A4 + "::test_a7_no_processing_or_publication_date_is_an_effective_date"], "an ambiguous record has unknown timing")
M("effective_date ignores reconciliation conflicts", RN, "effective_date",
  [('''    if a.get("effective_conflict") or a.get("classification") in ("incomplete", "unclassifiable"):''',
    '''    if a.get("classification") in ("incomplete", "unclassifiable"):''')],
  [A4 + "::test_a7_no_processing_or_publication_date_is_an_effective_date"], "a conflicting record has unknown timing")
M("_date keeps the Task 7 fallback", RN, "_date",
  [('''    return effective_date(a)''', '''    return effective_date(a) or (a.get("process_date") if _valid_date(a.get("process_date")) else None)''')],
  [A4 + "::test_a7_an_undated_action_with_only_a_process_date_blocks_every_lot_of_its_symbol"],
  "process-date-only records block every lot (undated)")
M("contaminated_symbols: undated actions ignored", RN, "contaminated_symbols",
  [('''            hit = [s for s in syms if s in cohort_syms or s in set(held_syms)]''', '''            hit = []''')],
  [A4 + "::test_a4_a_unit_action_with_missing_or_ambiguous_date_follows_the_conservative_rule"],
  "unknown timing is never outside the date comparison")
M("contaminated_symbols: only SELLs strictly after the effective date", RN, "contaminated_symbols",
  [('''                if t["symbol"] == s and t["action"] == "SELL" and (since is None or c.aware(t["ts"]) >= since) \\''',
    '''                if t["symbol"] == s and t["action"] == "SELL" and (since is None or c.aware(t["ts"]) > since + __import__("datetime").timedelta(days=1)) \\''')],
  [A4 + "::test_a4_2b_a_post_event_sell_makes_the_whole_trial_inconclusive"],
  "a SELL on the effective date is post-event")
M("contaminated_symbols: no lot needs to be open across", RN, "contaminated_symbols",
  [('''            hit = [s for s in syms if s in open_syms]''', '''            hit = list(syms)''')],
  [A4 + "::test_a4_a_resolved_pre_entry_event_does_not_contaminate"], "a fully resolved event does not contaminate")
M("contaminated_symbols: post-stop actions included", RN, "contaminated_symbols",
  [('''        elif d <= stop_day:''', '''        elif True:''')],
  ["test_s1_run.py::test_fifo_untrusted_ignores_actions_outside_the_trial_window_and_acquirer_side"],
  "an action effective after the stop session is outside the trial")
M("_score: 2b downgraded to exclusion", RN, "_score",
  [('''    twob = {s: info for s, info in contam.items() if info["sells"]}''', '''    twob = {}''')],
  [A4 + "::test_a4_2b_a_post_event_sell_makes_the_whole_trial_inconclusive"], "any post-event SELL -> INCONCLUSIVE")
M("_score: 2c lots not excluded", RN, "_score",
  [('''    untrusted = {s: [f"contaminated symbol {s}: unit/identity action(s) {info['actions']} with a lot open across "
                     f"(A4.2c, action metadata only)"] for s, info in contam.items()}''', '''    untrusted = {}''')],
  [A4 + "::test_a4_2c_cohort_only_contamination_without_a_sell_excludes_every_cohort_lot_of_the_symbol"],
  "cohort-only contamination excludes every lot of the symbol")
M("_score: audit and final actions not reconciled", RN, "_score",
  [('''    actions, conflicts = k.reconcile_actions(audit["corporate_actions.json"], final["corporate_actions.json"])''',
    '''    actions, conflicts = audit["corporate_actions.json"] + final["corporate_actions.json"], []''')],
  [A7 + "::test_a7_2_audit_and_final_records_are_reconciled_at_the_score"], "audit vs final conflicts are found")
M("_score: RUN-ACK not re-verified", RN, "_score",
  [('''    invalid += [f"registration not verified: {x}" for x in g.run_ack_problems(out, pr, mailbox)]   # A8.2''', '''    pass''')],
  [MF + "::test_mf_the_score_reverifies_the_run_token_bindings"], "an artifact changed after prereg is ABORTED-INVALID")
M("_score: persisted-stop integrity not checked", RN, "_score",
  [('''            invalid += z.stop_problems(out, start, cal)    # A2.3: integrity through the persisted stop''', '''            pass''')],
  [A2 + "::test_a2_integrity_of_the_frozen_slices_is_enforced_at_score"], "frozen-slice tampering is ABORTED-INVALID")
M("_score: stop.json changed after the attestation accepted", RN, "_score",
  [('''                invalid.append("persisted stop (stop.json) changed after the stop attestation")''', '''                pass''')],
  ["test_s1_t12_mutant_survivors.py::test_ms_stop_json_changed_after_the_attestation_is_named", A2 + "::test_a2_attest_stop_binds_the_persisted_stop"], "stop.json edited after attest_stop is ABORTED-INVALID")
M("_score: final manifest bundle not checked", RN, "_score",
  [('''                invalid.append("final acquisition manifest bundle differs from prereg")''', '''                pass''')],
  [A38 + "::test_a3_score_checks_bundle_consistency_across_every_artifact[final_manifest]"],
  "the final manifest's bundle is checked")
M("_seal_chain_problems: seal bundle not checked", RN, "_seal_chain_problems",
  [('''        if s.get("bundle_sha256") != bundle:''', '''        if False:''')],
  [A38 + "::test_a3_score_checks_bundle_consistency_across_every_artifact[seal]"], "every seal's bundle is checked")
M("_final_snapshot_problems: bundle not checked", RN, "_final_snapshot_problems",
  [('''    if bundle is not None and rep.get("bundle_sha256") != bundle:                    # Task 12 (A3.4)''',
    '''    if False:                    # Task 12 (A3.4)''')],
  [A38 + "::test_a3_score_checks_bundle_consistency_across_every_artifact[final_snapshot]"],
  "the final snapshot's bundle is checked")
M("_start_attestation_problems: books not bound", RN, "_start_attestation_problems",
  [('''            "opening_books_sha256": c.sha_or_absent(out / "opening_books.json"),
            "bundle_sha256": c.bundle_sha256()}''', '''            "bundle_sha256": c.bundle_sha256()}''')],
  [MF + "::test_mf_an_edited_opening_books_file_is_aborted_invalid_at_score"], "the attestation binds the books")
M("_stop_attestation (score): stop.json not bound", RN, "_stop_attestation",
  [('''        probs.append("persisted stop (stop.json) hash differs")''', '''        pass''')],
  [MF + "::test_mf_an_attestation_binding_another_stop_json_is_unverified"], "the attestation binds stop.json")
M("_trial_end: integrity failure still demands the final manifest", RN, "_trial_end",
  [('''        if st_.get("persisted") and z.stop_problems(out, start, cal, recheck=False):''', '''        if False:''')],
  ["test_s1_run.py::test_cr_malformed_seal_without_final_manifest_is_still_scored_invalid"],
  "a broken frozen slice is scored ABORTED-INVALID without a final manifest")
M("_pre_reserve_gate: pinned core not loaded first", RN, "_pre_reserve_gate",
  [('''    c.sim(), c.fetch()                    # Task 7 m-2: a pinned-core hash failure refuses before the reservation''',
    '''    pass''')],
  ["test_s1_run.py::test_pinned_core_hash_mismatch_is_refused_before_reservation"], "refused before the reservation")
M("score: bundle not verified first", RN, "score",
  [('''    c.verify_bundle_first(out, "score", mailbox=mailbox, need="prereg")    # Task 12: A3.2 bundle first (RUN-ACK's)''',
    '''    pass''')],
  [A38 + "::test_a3_score_bundle_mismatch_aborts_reserves_nothing_and_restoration_scores_aborted_invalid"],
  "a score under another bundle reserves nothing")
M("attest_stop: registration not verified", RN, "attest_stop",
  [('''    g.verified_registration(out, "stop attestation", mailbox)          # Task 12: A3.2 bundle first, then A8.2''',
    '''    pass''')],
  [A38 + "::test_a3_post_stop_commands_verify_the_bundle_first"], "attest_stop checks the bundle first")
M("attest_stop: binds no stop.json", RN, "attest_stop",
  [('''           "stop_sha256": c.sha256_file(out / "stop.json"),                       # Task 12 (A2.1/A7.1)''',
    '''           "stop_sha256": None,                       # Task 12 (A2.1/A7.1)''')],
  [A2 + "::test_a2_attest_stop_binds_the_persisted_stop"], "attest_stop binds stop.json")
M("_capture_notes lists no refusals", RN, "_capture_notes",
  [('''        if rep.get("refused"):''', '''        if False:''')],
  [REP + "::test_r6_refused_captures_provenance_changes_and_observation_gaps_are_listed_in_the_score"],
  "refused captures are listed")
M("_capture_notes drops binding gaps", RN, "_capture_notes",
  [('''                    for g in rep.get("observation_gaps", [])]''', '''                    for g in []]''')],
  [REP + "::test_r6_refused_captures_provenance_changes_and_observation_gaps_are_listed_in_the_score"],
  "binding observation gaps are reported")
M("_report_restarts_and_bridge omits the capture notes", RN, "_report_restarts_and_bridge",
  [('''    rep.update(_capture_notes(out, seals))                       # Task 12 (R-6, A1.2): report-only''', '''    pass''')],
  [REP + "::test_r6_refused_captures_provenance_changes_and_observation_gaps_are_listed_in_the_score"],
  "the report carries the capture notes")
M("_capture_seal_problems ignores a missing seal", RN, "_capture_seal_problems",
  [('''        if not sp.is_file() or c.sha256_file(sp) != seal.get("sha256"):''', '''        if False:''')],
  ["test_s1_task11.py::test_m2_capture_report_naming_a_seal_that_is_not_on_disk_is_aborted_invalid"],
  "a capture report naming a missing seal is ABORTED-INVALID")
M("carry_in_reasons: until not applied", RN, "carry_in_reasons",
  [('''            elif (since is None or d >= since) and (until is None or d <= until) and not (''',
    '''            elif (since is None or d >= since) and not (''')],
  [A4 + "::test_a4_1_prereg_bounds_the_opening_audit_to_actions_effective_before_start"],
  "the pre-START bound applies")
M("exclusions: undated actions ignored", RN, "exclusions",
  [('''            if d is None:
                why.append(f"undated {a.get('type')} {a.get('id')}")''', '''            if d is None:
                pass''')],
  [A4 + "::test_a7_an_undated_action_with_only_a_process_date_blocks_every_lot_of_its_symbol"],
  "an undated action blocks every lot")
M("_receipt_sha over the whole receipt", RN, "_receipt_sha",
  [('''    return c.receipt_sha256(receipt)''', '''    return c.sha256_bytes(c.canonical(receipt))''')],
  [A1 + "::test_a1_a_head_or_dirty_change_alone_seals_and_is_recorded_as_provenance",
   "test_s1_run.py::test_attest_start_requires_exact_statement_once_and_before_start"],
  "the attestation binds the fingerprint hash")
M("_calendar keeps extra fields", RN, "_calendar",
  [('''    return z.calendar_rows(raw)''', '''    return [dict(x) for x in raw]''')],
  [MF + "::test_mf_calendar_rows_keep_only_date_open_close"], "only session rows")
M("run_token (runner) not the shared token", RN, "run_token",
  [('''    return c.run_token(_out(root))''', '''    return c.run_token(_out(root)).replace(" opening_books_sha256=", " books=")''')],
  [A38 + "::test_a8_run_ack_binds_opening_seal_frozen_opening_books_audit_attestation_and_bundle"],
  "the RUN token binds the books")
M("score_token (runner) drops the bundle", RN, "score_token",
  [('''    return c.score_token(_out(root))''', '''    return c.score_token(_out(root)).split(" bundle_sha256=")[0]''')],
  [A38 + "::test_a3_run_acquire_score_tokens_prereg_and_every_seal_bind_the_bundle"], "SCORE-ACK binds the bundle")

# ====================================================================== s1_books (Task 11)
M("held_symbols ignores operational holdings", BK, "held_symbols",
  [('''    return held | {s for s, q in operational_replay(rows_before_start)["qty"].items() if q > 0}''', '''    return held''')],
  ["test_s1_task11.py::test_i4_final_plan_is_derived_from_the_stop_seal"],
  "EXPECTED EQUIVALENT: the economic FIFO keeps every residual the operational book writes off (see triage)")
M("sold_events replays the whole prefix per SELL symbol-agnostically", BK, "sold_events",
  [('''        prefix = by_symbol.setdefault(r["symbol"], [])''', '''        prefix = by_symbol.setdefault("all", [])''')],
  ["test_s1_task11.py::test_i3_sold_events_on_2000_rows_completes_in_under_5_seconds"],
  "per-symbol prefix replay (equivalent output, I-3 performance bound)")

# ---------------------------------------------------------------------- coverage completions
M("_write_report writes nothing", "s1_checkpoint.py", "_write_report",
  [('''    _report_path(cap_dir).write_text(json.dumps(rep, indent=1), encoding="utf-8")''', '''    pass''')],
  [A56 + "::test_a5_the_clock_is_checked_before_any_capture_and_the_refused_attempt_is_preserved"],
  "every attempt's report is preserved")
M("_attempt (runner) resolves raw pages against the attempt dir", RN, "_attempt",
  [('''    return g.attempt(d, names, Path(d).parent)''', '''    return g.attempt(d, names, Path(d))''')],
  ["test_s1_checkpoint_7b.py::test_full_synthetic_lifecycle_uses_the_real_opening_seal_and_final_snapshot"],
  "the audit's raw pages (relative to s1_out) verify")
