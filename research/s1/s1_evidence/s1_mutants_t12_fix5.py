"""Task 12 fix round 5 (re-review 3: R-1, R-2, R-3; A10.2). Applied to MUTANTS after fix round 4:
(1) RETARGET the earlier mutants whose source text the round-5 code replaced (same intent on the new code);
(2) ADD targeted mutants for the round-5 behaviour, each with its intended test(s)."""
from s1_mutants_t12_list import CK, CM, M, MUTANTS

F4 = "test_s1_t12_fix4.py::"
F5 = "test_s1_t12_fix5.py::"
BY = {m["name"]: m for m in MUTANTS}


def retarget(name, edits, *, tests=None, function=None):
    m = BY[name]
    f = m["file"]
    m["edits"] = [(e[0], e[1], e[2]) if len(e) == 3 else (f, e[0], e[1]) for e in edits]
    m["retargeted"] = "fix round 5: source replaced by the re-review-3 fix; same intent on the new code"
    if tests:
        m["tests"] = tests
    if function:
        m["function"] = function


# ---------------------------------------------------------------- (1) retargets
retarget("N-2 opening_orphans: a capture without its claim ignored",
         [('''            if not (d / f"{slot}.attempt.json").exists() and not _finalizer_missed(q, slot):     # fix5 (R-1)''',
           '''            if False:''')])
retarget("N-3 registration_problems: no clock anchor",
         [('''    if before_opening(out, now, mailbox):
        return []
    w, ack = registration_witnesses(out, mailbox)''', '''    w, ack = registration_witnesses(out, mailbox)''')])
retarget("N-3 preregistration_problems: no clock anchor",
         [('''    if before_opening(out, now, mailbox):
        return w + ''', '''    if False:
        return w + ''')])
retarget("N-3 registration: a prereg is registered before the opening",
         [('''"registered": not before_opening(out, mailbox=mailbox),''', '''"registered": True,''')])
BY["N-3 opening_anchor: the anchor is the opening close itself"]["function"] = "_first_slot_of"

# ---------------------------------------------------------------- (2) round-5 mutants
MISSED_GUARD = F5 + "test_r1_guard_a_missed_record_no_finalizer_writes_is_still_an_orphan"
M("R-1 a MISSED record is never consistent without its claim", CM, "_finalizer_missed",
  [('''    if not q.name.endswith(".resolution.json"):
        return False''', '''    return False''')],
  [F5 + "test_r1_probe_an_opening_whose_first_slot_never_ran_still_seals"],
  "a finalizer's MISSED record of a never-claimed opening slot is no orphan: the opening still seals")
M("R-1 any claimless record is consistent", CM, "_finalizer_missed",
  [('''    if not q.name.endswith(".resolution.json"):
        return False''', '''    return True''')],
  [F5 + "test_r1_guard_a_failure_resolution_whose_claim_was_deleted_is_still_the_persistent_abort"],
  "a FAILURE resolution whose claim was deleted is still the persistent abort")
M("R-1 a MISSED decided before E is consistent", CM, "_finalizer_missed",
  [('''                and aware(rec["eligible_until"]) < aware(rec["decided_utc"]))''', '''                )''')],
  [MISSED_GUARD + "[decided-before-E]"], "a MISSED decided before E is no finalizer's record: the abort")
M("R-1 a MISSED for another slot is consistent", CM, "_finalizer_missed",
  [('''                and aware(rec["slot"]).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ") == slot''',
    '''                and aware(rec["slot"]) is not None''')],
  [MISSED_GUARD + "[other-slot]"], "a MISSED naming another slot is no finalizer's record: the abort")
M("R-1 a MISSED with capture evidence is consistent", CM, "_finalizer_missed",
  [('''rec.get("outcome") == "MISSED" and "evidence" not in rec''', '''rec.get("outcome") == "MISSED"''')],
  [MISSED_GUARD + "[with-evidence]"], "a MISSED carrying capture evidence is no finalizer's record: the abort")
M("R-2 the anchor ignores the registered evidence (plan only)", CM, "opening_anchor",
  [('''    days = _registered_opening_days(out, rows, mailbox)''', '''    days = set()''')],
  [F5 + "test_r2_probe_moving_the_plans_opening_close_after_registration_aborts_and_restoring_does_not_resume",
   F5 + "test_r2_moving_the_plans_opening_close_after_the_opening_seal_before_any_run_ack_aborts"],
  "a plan edit after registration is the persistent abort, not a pre-registration refusal")
M("R-2 the anchor is the LATEST source, not the earliest", CM, "opening_anchor",
  [('''    return min(anchors) if anchors else None''', '''    return max(anchors) if anchors else None''')],
  [F5 + "test_r2_moving_the_plans_opening_close_after_the_opening_seal_before_any_run_ack_aborts"],
  "a plan edit can never move the anchor later than the registered evidence")
M("R-2 the RUN-ACK does not anchor the opening", CM, "_registered_opening_days",
  [('''    ack = run_ack_witness(out, mailbox)
    try:''', '''    ack = None
    try:''')],
  [F5 + "test_r2_the_run_ack_alone_anchors_the_opening"], "the RUN-ACK alone still anchors the opening: the abort")
M("R-3 an after-seal opening slot leaves no evidence", CK, "run_opening_checkpoint",
  [('''        _after_opening_seal(out, day, cal, close, scheduled, cap_dir, now)                       # fix5 (R-3)''',
    '''        raise SystemExit(f"opening seal exists ({day['date']}): refusing")''')],
  [F5 + "test_r3_an_opening_slot_after_the_seal_leaves_a_claim_and_a_report_binding_the_seal",
   F5 + "test_r3_deleting_the_seal_and_its_sealing_slot_records_after_a_later_slot_bound_it_aborts"],
  "an after-seal opening slot leaves a claim and a report binding the seal")
M("R-3 the after-seal claim does not record the seal", CK, "_after_opening_seal",
  [('''        _claim_slot(out, cap_dir, scheduled, close, t, {"after_seal": {"seal": seal_rel, "sha256": sha}})''',
    '''        _claim_slot(out, cap_dir, scheduled, close, t)''')],
  [F5 + "test_r3_the_after_seal_claim_alone_still_binds_the_seal"], "the after-seal claim alone binds the seal")
M("R-3 the after-seal slot publishes no resolution", CK, "_after_opening_seal",
  [('''    _publish(cap_dir, day, cal, rep, now)
    _write_report(cap_dir, rep)
    raise SystemExit(f"opening seal exists''', '''    _write_report(cap_dir, rep)
    raise SystemExit(f"opening seal exists''')],
  [F5 + "test_r3_an_opening_slot_after_the_seal_leaves_a_claim_and_a_report_binding_the_seal"],
  "the after-seal slot is resolved (no report without its resolution, no orphan)")
M("R-3 after-seal records are no record of the seal", CM, "_report_seals",
  [('''            if seal.get("written") is True or after.get("sha256"):''',
    '''            if seal.get("written") is True:''')],
  [F5 + "test_r3_deleting_the_seal_and_its_sealing_slot_records_after_a_later_slot_bound_it_aborts",
   F5 + "test_r3_the_after_seal_claim_alone_still_binds_the_seal",
   F5 + "test_r3_the_selection_never_writes_an_opening_seal_differing_from_a_recorded_opening_seal_hash"],
  "a seal recorded only by an after-seal record still binds: deletion or a different seal is the abort")
M("R-3 slot claims are not read for after-seal records", CM, "_report_seals",
  [('''    for p in sorted(out.glob("captures/*/*.report.json")) + sorted(out.glob("captures/*/*.attempt.json")):''',
    '''    for p in sorted(out.glob("captures/*/*.report.json")):''')],
  [F5 + "test_r3_the_after_seal_claim_alone_still_binds_the_seal"], "the after-seal claim alone binds the seal")
M("R-3 the selection does not compare the recorded opening-seal hashes", CK, "_before_opening_seal",
  [('''    if recorded and seal_sha not in recorded:''', '''    if False:''')],
  [F5 + "test_r3_the_selection_never_writes_an_opening_seal_differing_from_a_recorded_opening_seal_hash"],
  "a seal differing from a recorded opening-seal hash is the persistent abort, never written")

# ---------------------------------------------------------------- (3) after fix-round-5 run 1: tightened
# (run 1, s1_mutants_t12_fix5_run1.txt: KILLED=294, KILLED-BY-EXCEPTION=2, SURVIVED=4 of 300; 3 are the known
# equivalents; each other non-kill got a strengthened assertion or a RETROSPECTIVE isolating test)
BY = {m["name"]: m for m in MUTANTS}
BY["R-1 any claimless record is consistent"]["tests"] += [
    F5 + "test_r1_retro_a_failure_record_left_without_its_claim_and_capture_is_an_orphan"]
BY["R-1 any claimless record is consistent"]["tightened"] = (
    "fix round 5: masked by the last_process.json rule; a retrospective test isolates the MISSED-only exemption")
for name in ("R-1 a MISSED record is never consistent without its claim", "R-3 the after-seal slot publishes no resolution"):
    BY[name]["tightened"] = "fix round 5: the intended test strengthened after GREEN (an assertion, not an exception)"
