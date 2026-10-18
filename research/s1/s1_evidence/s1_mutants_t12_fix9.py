"""Task 12 fix round 9 (re-review 7: H-3, controller decision; rule-3 correction; A10.2). Applied to MUTANTS after fix
round 8:
(1) RETARGET the mutants whose source text round 9 replaced (same intent on the new code);
(2) RETIRE "H opening evidence before any AUDIT-ACK is no problem" (its rule was reversed by the controller: no
    AUDIT-ACK is now always a refusal) - replaced by its inverse below;
(3) replace intended test ids that round 9 removed (S1_BUILD_EVIDENCE §22.2) by their replacements;
(4) ADD targeted mutants for the round-9 behaviour."""
from s1_mutants_t12_list import CM, M, MUTANTS

F6 = "test_s1_t12_fix6.py::"
F7 = "test_s1_t12_fix7.py::"
F8 = "test_s1_t12_fix8.py::"
F9 = "test_s1_t12_fix9.py::"
BY = {m["name"]: m for m in MUTANTS}


def retarget(name, edits, *, tests=None, function=None):
    m = BY[name]
    f = m["file"]
    m["edits"] = [(e[0], e[1], e[2]) if len(e) == 3 else (f, e[0], e[1]) for e in edits]
    m["retargeted"] = "fix round 9: source replaced by the H-3 fix; same intent on the new code"
    if tests is not None:
        m["tests"] = tests
    if function:
        m["function"] = function


ANCHOR = F9 + "test_h3_the_anchor_is_the_earliest_possible_first_slot_of_the_audit_bound_opening_date"
PLAN_EVIDENCE = F9 + "test_h3_a_plan_differing_from_the_audit_ack_with_opening_evidence_is_the_abort"
RULE3 = F9 + "test_rule3_no_audit_ack_for_the_bundle_is_always_a_refusal_even_with_opening_evidence"

# ---------------------------------------------------------------- (1) retargets
retarget("N-3 opening_anchor: the anchor is the opening close itself",
         [('''    return s1_seal.first_slot_after(close)''', '''    return close''')],
         tests=[ANCHOR], function="_earliest_first_slot")
retarget("H the opening close is named by plan.json",
         [('''    plan_bound = plan_sha is not None and any(f.get("plan_sha256") == plan_sha for f in audits)''',
           '''    plan_bound = plan_sha is not None''')],
         tests=[PLAN_EVIDENCE], function="registration_state")
BY["H the opening close is named by plan.json"]["name"] = "H the plan is used without the AUDIT-ACK's plan_sha256"

# ---------------------------------------------------------------- (2) retired
MUTANTS[:] = [m for m in MUTANTS if m["name"] != "H opening evidence before any AUDIT-ACK is no problem"]

# ---------------------------------------------------------------- (3) removed intended tests -> their replacements
REPLACED = {
    F6 + "test_f1_an_edited_plan_never_lets_earlier_close_evidence_anchor_the_clock": PLAN_EVIDENCE,
    F8 + "test_h_retro_only_the_external_acks_bind_a_coordinated_plan_edit":
        F8 + "test_h_retro_only_the_external_acks_bind_a_coordinated_attestation_edit",
    F8 + "test_h_opening_evidence_without_any_audit_ack_for_the_bundle_is_the_abort": RULE3,
}
for m in MUTANTS:
    m["tests"] = list(dict.fromkeys(REPLACED.get(t, t) for t in m["tests"]))

# ---------------------------------------------------------------- (4) round-9 mutants
M("H-3 the anchor uses the regular close, not the earliest early close", CM, "_earliest_first_slot",
  [('''EARLIEST_CLOSE_NY = time(13, 0)''', '''EARLIEST_CLOSE_NY = time(16, 0)''')],
  [ANCHOR], "the anchor is the earliest possible first slot of the opening date (13:00 New York + the first offset)")
M("H-3 a plan differing from every AUDIT-ACK is no problem", CM, "registration_problems",
  [('''    if not st["outage"] and not st["plan_bound"]:            # fix round 9 (H-3): the plan names no AUDIT-ACK'd date''',
    '''    if False:''')],
  [PLAN_EVIDENCE], "a plan differing from the AUDIT-ACK with local opening evidence is the abort")
M("H-3 an unbound plan skips the registered checks", CM, "registration_problems",
  [('''        if not st["registered"]:
            return unbound''', '''        return unbound''')],
  [F7 + "test_g1_probe_editing_plan_and_manifest_together_aborts_and_restoring_does_not_resume[bogus]"],
  "a registered trial with an unbound plan still reports every bound artifact (the manifest change)")
M("rule 3: no AUDIT-ACK with opening evidence aborts", CM, "registration_problems",
  [('''    if not st["outage"] and not st["audited"]:              # fix round 9 (rule 3 corrected): cannot be registered
        return []''', '''    if not st["outage"] and not st["audited"]:              # fix round 9 (rule 3 corrected): cannot be registered
        return _local_opening_evidence(out)''')],
  [RULE3], "no AUDIT-ACK for the bundle is always a refusal, never an abort")

# ---------------------------------------------------------------- (5) after the first fix-9 subset run: tightened
# 2 SURVIVED: "H the anchor cancels an external ACK" (its fix-8 test's clock, slot0 - 10 min, now lies after the
# earlier calendar-free anchor -> the test's clock is now anchor - 10 min) and "H the plan is used without the
# AUDIT-ACK's plan_sha256" (an edit moving the date EARLIER also trips the orphan rule; the date moved LATER is the
# isolating state -> the fix5 R-2 test added as intended test)
BY = {m["name"]: m for m in MUTANTS}
BY["H the plan is used without the AUDIT-ACK's plan_sha256"]["tests"] += [
    "test_s1_t12_fix5.py::test_r2_moving_the_plans_opening_close_after_the_opening_seal_before_any_run_ack_aborts"]
for name in ("H the anchor cancels an external ACK", "H the plan is used without the AUDIT-ACK's plan_sha256"):
    BY[name]["tightened"] = "fix round 9: the intended test isolates the mutant again (A10.2)"
