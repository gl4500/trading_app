"""Task 12 fix round 3 (re-review 1: C-1, C-2, I-1, I-2, M-1, M-2, M-3; A10.2). Applied to MUTANTS after fix round 2:
(1) RETARGET the earlier mutants whose source text the round-3 code replaced (same intent on the new code);
(2) ADD targeted mutants for the round-3 behaviour, each with its intended test(s);
(3) re-argue the two fix-round-2 "equivalent under B3" survivors under the round-3 witness logic."""
from s1_mutants_t12_list import CK, CM, CO, M, MUTANTS, RC, RN, SE

F3 = "test_s1_t12_fix3.py::"
FX2 = "test_s1_t12_fix2_mutants.py::"
BY = {m["name"]: m for m in MUTANTS}


def retarget(name, edits, *, tests=None, function=None):
    m = BY[name]
    f = m["file"]
    m["edits"] = [(e[0], e[1], e[2]) if len(e) == 3 else (f, e[0], e[1]) for e in edits]
    m["retargeted"] = "fix round 3: source replaced by the re-review-1 fix; same intent on the new code"
    if tests:
        m["tests"] = tests
    if function:
        m["function"] = function


# ---------------------------------------------------------------- (1) retargets
retarget("write_abort overwrites (last abort wins)",
         [('''        publish_text_exclusive(out / "aborted.json", json.dumps(rec, indent=1, default=str))''',
           '''        replace_atomic(out / "aborted.json", json.dumps(rec, indent=1, default=str))''')])
retarget("registration: audit stage never registered",
         [('''        return {"stage": "audit", "bundle": b, "registered": is_registered(out, mailbox), "ack_id": ack_id}''',
           '''        return {"stage": "audit", "bundle": b, "registered": False, "ack_id": ack_id}''')])
retarget("_claim_slot allows a duplicate execution",
         [('''        c.publish_text_exclusive(claim, json.dumps({"scheduled": scheduled.isoformat(), "invoked_utc": t.isoformat(),''',
           '''        c.replace_atomic(claim, json.dumps({"scheduled": scheduled.isoformat(), "invoked_utc": t.isoformat(),''')])
retarget("persist_stop overwrites",
         [('''    c.publish_text_exclusive(p, json.dumps(rec, indent=1, sort_keys=True))''',
           '''    c.replace_atomic(p, json.dumps(rec, indent=1, sort_keys=True))''')])
retarget("load_or_create_key recreates the key every call",
         [('''    if not p.exists():
        try:                                               # fix round 3 (C-1): atomic, never a partial key''',
           '''    if True:
        p.unlink(missing_ok=True)
        try:                                               # fix round 3 (C-1): atomic, never a partial key''')])
retarget("_write_report writes nothing",
         [('''    c.publish_text_exclusive(_report_path(cap_dir), json.dumps(rep, indent=1))''', '''    pass''')])
retarget("is_registered: the capture-report witness ignored",
         [('''    if oday and any(sp.stem == oday for _, sp, _ in _report_seals(out)):''', '''    if False:''')],
         tests=[F3 + "test_c2_retro_the_opening_report_and_resolution_witness_the_registration"],
         function="registration_witnesses")
retarget("registration_problems: changed artifacts not compared",
         [('''                if p.is_file() and sha256_file(p) != h:''', '''                if False:''')])
retarget("registration_problems: missing artifacts not reported",
         [('''        probs += [f"{rel} missing (required at {stage})" for rel in need[stage] if not (out / rel).is_file()]''',
           '''        pass''')])
retarget("registration_problems: post-stop frozen artifacts not checked",
         [('''    if reached["stop"]:
        import s1_seal''', '''    if False:
        import s1_seal''')])
retarget("verify_bundle_first: an authorization failure skips the gate",
         [('''        registration_gate(out, where, now, refuse=gate_refuses, mailbox=mailbox)       # B3.3
        if err is not None:
            raise err''', '''        if err is not None:
            raise err
        registration_gate(out, where, now, refuse=gate_refuses, mailbox=mailbox)       # B3.3''')])
retarget("do_audit: re-entry not gated",
         [('''    c.registration_gate(out, "audit", mailbox=mailbox)                  # fix round 2 (B3.3): re-entry is gated''',
           '''    pass''')])
retarget("prereg is not registered",
         [('''        c.register_stage(out, "prereg", {"prereg.json": k.json_sha256(pr)})                          # B3.1''',
           '''        pass''')])

# ---------------------------------------------------------------- (2) fix-round-3 mutants
NONATOMIC = "a concurrent reader/writer observes the partial file (deterministic pause inside the write)"
M("C-1 publish_exclusive writes the target directly (no temporary file + link)", CM, "publish_exclusive",
  [('''        with tmp.open("xb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.link(tmp, path)''', '''        with path.open("xb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())''')],
  [F3 + "test_c1_a_concurrent_finalizer_and_a_reader_never_observe_a_partial_seal",
   F3 + "test_c1_a_concurrent_stop_decision_never_observes_a_partial_stop_json",
   F3 + "test_c1_a_concurrent_abort_writer_never_loses_the_real_reason"], NONATOMIC)
M("C-1 finalize_close writes the seal non-atomically", CK, "finalize_close",
  [('''            c.publish_exclusive(seal_p, data)''', '''            with seal_p.open("xb") as f:
                f.write(data)''')],
  [F3 + "test_c1_a_concurrent_finalizer_and_a_reader_never_observe_a_partial_seal",
   F3 + "test_c1_every_immutable_artifact_is_published_atomically"], NONATOMIC)
M("C-1 persist_stop writes stop.json non-atomically", SE, "persist_stop",
  [('''    c.publish_text_exclusive(p, json.dumps(rec, indent=1, sort_keys=True))''',
    '''    with p.open("x", encoding="utf-8") as f:
        json.dump(rec, f, indent=1, sort_keys=True)''')],
  [F3 + "test_c1_a_concurrent_stop_decision_never_observes_a_partial_stop_json"], NONATOMIC)
M("C-1 write_abort writes aborted.json non-atomically", CM, "write_abort",
  [('''        publish_text_exclusive(out / "aborted.json", json.dumps(rec, indent=1, default=str))''',
    '''        with (out / "aborted.json").open("x", encoding="utf-8") as f:
            json.dump(rec, f, indent=1, default=str)''')],
  [F3 + "test_c1_a_concurrent_abort_writer_never_loses_the_real_reason"], NONATOMIC)
M("C-2 register_stage writes only the registry copy", CM, "register_stage",
  [('''    for p in stage_records(out, stage):
        try:
            publish_exclusive(p, data)''', '''    for p in stage_records(out, stage)[:1]:
        try:
            publish_exclusive(p, data)''')],
  [F3 + "test_c2_deleting_an_artifact_with_its_registry_record_is_a_persistent_abort[prereg+registry]"],
  "deleting an artifact with its registry record leaves the second record")
M("C-2/I-2 _registered: a lone witness registers", CM, "_registered",
  [('''    return "RUN-ACK" in w or (len(w) >= 2 and any(x not in IN_PROGRESS for x in w))''',
    '''    return "RUN-ACK" in w or (len(w) >= 1 and any(x not in IN_PROGRESS for x in w))''')],
  [F3 + "test_i2_a_stray_seal_before_the_opening_is_a_preserved_refusal_never_an_abort[2026-10-23.json]",
   F3 + "test_i2_a_lone_later_stage_registry_record_before_the_opening_is_a_refusal"],
  "a lone stray file is a refusal, never a registration")
M("C-2 _registered: the RUN-ACK is no witness", CM, "_registered",
  [('''    return "RUN-ACK" in w or (len(w) >= 2 and any(x not in IN_PROGRESS for x in w))''',
    '''    return (len(w) >= 2 and any(x not in IN_PROGRESS for x in w))''')],
  [F3 + "test_c2_the_external_run_ack_witnesses_the_registration_when_every_other_local_witness_is_gone"],
  "the external RUN-ACK witnesses the registration")
M("C-2 _reached: the RUN-ACK does not reach the attestation", CM, "_reached",
  [('''                                               ack.get("attest_start_sha256") not in (None, ABSENT))''',
    '''                                               False)''')],
  [F3 + "test_c2_retro_the_run_ack_witnesses_the_attestation"], "the RUN-ACK witnesses the attestation stage")
M("C-2 _reached: prereg reached only by its own files", CM, "_reached",
  [('''    prereg = stop or has("prereg") or any(x in w for x in ("post-START capture",) + LATER_FILES[1:])''',
    '''    prereg = has("prereg")''')],
  [F3 + "test_c2_deleting_the_persisted_stop_and_its_registry_record_is_a_gate_abort",
   F3 + "test_c2_deleting_an_artifact_with_its_registry_record_is_a_persistent_abort[seals+registry+witnesses+reports+resolutions]"],
  "later stages reach prereg")
M("C-2 registration_problems: stage records not required", CM, "registration_problems",
  [('''                    probs.append(f"{rel} missing (stage {stage} is registered)")''', '''                    pass''')],
  [F3 + "test_c2_a_registered_stage_whose_registry_record_alone_is_deleted_is_detected"],
  "a missing stage record is detected")
M("C-2 registration_problems: the attestation's / prereg's own bindings ignored", CM, "registration_problems",
  [('''        probs += _bound_problems(out, "prereg.json", PREREG_BINDS, seal_rel)''', '''        pass''')],
  [F3 + "test_c2_retro_prereg_binds_the_attestation_even_when_its_records_are_rewritten"],
  "prereg's binding is a second expected source")
M("I-2 preregistration_problems ignores stray seal files", CM, "preregistration_problems",
  [('''    return stray + [f"seals/{p.name}" for p in sorted((out / "seals").glob("*.json"))]''', '''    return stray''')],
  [F3 + "test_i2_a_stray_seal_before_the_opening_is_a_preserved_refusal_never_an_abort[2026-01-01.json]"],
  "a stray seal before the opening is a preserved refusal")
M("C-2/M-2 registration_gate ignores the stage lock", CM, "registration_gate",
  [('''    if (out / STAGE_LOCK).exists():''', '''    if False:''')],
  [F3 + "test_c2_retro_a_stage_publication_in_progress_is_a_refusal_not_an_abort"],
  "an in-flight stage publication is a refusal")
M("M-2 stage_publication takes no lock", CM, "stage_publication",
  [('''            publish_text_exclusive(self.p, json.dumps({"pid": os.getpid(), "utc": now_utc().isoformat()}))''',
    '''            pass''')],
  [F3 + "test_m2_retro_a_concurrent_command_during_the_prereg_publication_refuses"],
  "a concurrent command during a stage publication refuses, never aborts")
M("M-2 the START attestation is registered after its artifact", RN, "attest_start",
  [('''        c.register_stage(out, "attest_start", {"attest_start.json": k.json_sha256(rec),                   # B3.1
                                               "opening_books.json": c.sha256_file(books_p)})
        _write_once(out / "attest_start.json", rec, "START attestation")''',
    '''        _write_once(out / "attest_start.json", rec, "START attestation")
        c.register_stage(out, "attest_start", {"attest_start.json": k.json_sha256(rec),                   # B3.1
                                               "opening_books.json": c.sha256_file(books_p)})''')],
  [F3 + "test_m2_the_attestation_and_prereg_are_registered_before_their_artifacts_are_published"],
  "records before the artifact")
M("M-2 prereg is registered after its artifact", RN, "do_prereg",
  [('''        c.register_stage(out, "prereg", {"prereg.json": k.json_sha256(pr)})                          # B3.1
        _write_once(out / "prereg.json", pr, "prereg")''',
    '''        _write_once(out / "prereg.json", pr, "prereg")
        c.register_stage(out, "prereg", {"prereg.json": k.json_sha256(pr)})                          # B3.1''')],
  [F3 + "test_m2_the_attestation_and_prereg_are_registered_before_their_artifacts_are_published"],
  "records before the artifact")
M("I-1 pending_closes: a SUCCESS without its seal counts as applied", SE, "_applied_or_unsuccessful",
  [('''        return json.loads(res.read_text(encoding="utf-8")).get("outcome") != "SUCCESS"''',
    '''        return True''')],
  [F3 + "test_i1_probe_a_success_without_its_seal_is_pending_so_no_stop_is_frozen",
   F3 + "test_i1_the_score_refuses_while_a_success_lacks_its_seal"], "no stop is frozen across an unapplied SUCCESS")
M("I-1 the stop attestation does not finalize first", RN, "attest_stop",
  [('''        s1_checkpoint.finalize_pending(out, pr["calendar"], c.aware(pr["start"]), c.now_utc())''', '''        pass''')],
  [F3 + "test_i1_the_stop_attestation_finalizes_before_it_freezes_the_stop"], "finalize before the stop")
M("I-1 the final plan does not finalize first", CO, "_stop_state",
  [('''        s1_checkpoint.finalize_pending(out, pr["calendar"], c.aware(pr["start"]), now)''', '''        pass''')],
  [F3 + "test_i1_the_final_plan_finalizes_before_it_freezes_the_stop"], "finalize before the stop")
M("M-1 _publish: a link overrun is not recorded", CK, "_publish",
  [('''            if linked >= dl:''', '''            if False:''')],
  [F3 + "test_m1_a_publication_whose_link_lands_at_or_after_D_records_the_overrun"], "the overrun is recorded")
M("M-3 _pre_reserve_gate: an abort still demands the final snapshot", RN, "_pre_reserve_gate",
  [('''    if c.load_abort(out) is not None:     # fix round 3 (M-3): a persistent abort is terminal - the one score records
        return''', '''    if False:
        return''')],
  [F3 + "test_m3_a_registration_abort_before_the_final_snapshot_still_yields_a_recorded_score"],
  "an aborted trial is recorded by the one score")

# ---------------------------------------------------------------- (3) the two fix-round-2 B3 survivors, re-argued
EQUIVALENT_FIX3 = (
    "fix round 3 re-derivation: both callers run only with prereg.json present (they refuse first otherwise) and the "
    "mutated check only matters for a stop.json that already existed; prereg.json + stop.json are two witnesses, so "
    "the trial is registered (_registered), the stop stage is reached (stop.json) and the registration gate - which "
    "runs earlier in the same command - evaluates the same s1_seal.stop_problems(recheck=False) and persists the "
    "abort on any problem. The C-2 states in which is_registered was False with stop.json present (re-review I-3) no "
    "longer exist: stop.json and both stop records are witnesses, and a lone stop.json with nothing else cannot "
    "reach these commands (no prereg -> refusal).")
for name in ("_stop_state ignores the persisted stop's integrity",
             "_trial_end: integrity failure still demands the final manifest"):
    BY[name]["equivalent"] = EQUIVALENT_FIX3

# ---------------------------------------------------------------- (4) after fix-round-3 run 1: tightened
# (run 1: KILLED=260, KILLED-BY-EXCEPTION=1, SURVIVED=7 of 268; run 2: 263/1/4; each non-equivalent non-kill got a
# RETROSPECTIVE isolating test)
BY = {m["name"]: m for m in MUTANTS}
for name, tests in (
        ("run_checkpoint: a corrupt seal is not an abort",
         ["test_c1_retro_an_unreadable_seal_stops_the_checkpoint_before_any_seal",
          "test_c1_retro_a_bad_seal_record_stops_the_checkpoint_before_any_seal"]),
        ("the persisted stop is not registered", ["test_c2_retro_the_stop_records_witness_a_stop_no_report_recorded"]),
        ("C-2 _registered: the RUN-ACK is no witness", ["test_c2_retro_the_run_ack_alone_witnesses_the_registration"]),
        ("C-2 _reached: prereg reached only by its own files", ["test_c2_retro_a_post_start_capture_witnesses_prereg"]),
        ("C-2 register_stage writes only the registry copy", ["test_c2_retro_every_stage_is_recorded_twice",
                                                              "test_c2_retro_the_opening_is_recorded_twice"])):
    BY[name]["tests"] = BY[name]["tests"] + [F3 + t for t in tests]
    BY[name]["tightened"] = "fix round 3: a retrospective test whose intended assertion fails on this mutant (A10.2)"
