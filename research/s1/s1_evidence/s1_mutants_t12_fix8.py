"""Task 12 fix round 8 (re-review 6: H-1, H-2; the operator-approved structural registration rule; A10.2). Applied to
MUTANTS after fix round 7:
(1) RETARGET the earlier mutants whose source text the restructure replaced but whose intent still applies;
(2) RETIRE the mutants bound to the deleted anchor code (_audit_bound, _fallback_opening_days, the plan-vouching
    branch, the attestation/prereg-hash RUN-ACK lookup): their functions no longer exist (listed in RETIRED);
(3) ADD targeted mutants for the round-8 rule, each with its intended test(s)."""
from s1_mutants_t12_list import CM, M, MUTANTS

F2 = "test_s1_t12_fix2_b3.py::"
F4 = "test_s1_t12_fix4.py::"
F6 = "test_s1_t12_fix6.py::"
F8 = "test_s1_t12_fix8.py::"
BY = {m["name"]: m for m in MUTANTS}


def retarget(name, edits, *, tests=None, function=None):
    m = BY[name]
    f = m["file"]
    m["edits"] = [(e[0], e[1], e[2]) if len(e) == 3 else (f, e[0], e[1]) for e in edits]
    m["retargeted"] = "fix round 8: source replaced by the structural rule; same intent on the new code"
    if tests is not None:
        m["tests"] = tests
    if function:
        m["function"] = function


PROBE9_TWO = F6 + "test_f1_probe_fabricated_earlier_close_evidence_before_the_opening_is_a_refusal[two-claims]"
PROBE9_PRE = F6 + ("test_f1_probe_fabricated_earlier_close_evidence_before_the_opening_is_a_refusal"
                   "[earlier-claim+opening-claim+prereg]")

# ---------------------------------------------------------------- (1) retargets
retarget("registration: audit stage never registered",
         [('''"registered": is_registered(out, mailbox, bundle=b), "ack_id": ack_id}''',
           '''"registered": False, "ack_id": ack_id}''')])
retarget("I-2 preregistration_problems ignores stray seal files",
         [('''    return [x for x in w if x not in IN_PROGRESS] + seals''',
           '''    return [x for x in w if x not in IN_PROGRESS]''')])
retarget("N-2 registration_problems: orphans ignored before registration",
         [('''    if not st["registered"]:
        return orphans''', '''    if not st["registered"]:
        return []''')])
retarget("N-3 registration_problems: no clock anchor",
         [('''        local = anchor is not None and (now or now_utc)() >= anchor''', '''        local = True''')],
         tests=[PROBE9_PRE], function="registration_state")
retarget("N-3 preregistration_problems: no clock anchor",
         [('''    if not st["local"]:
        return w + seals''', '''    if False:
        return w + seals''')], tests=[PROBE9_TWO])
retarget("N-3 registration: a prereg is registered before the opening",
         [('''"registered": is_registered(out, mailbox, bundle=b),   # fix round 8''',
           '''"registered": True,   # fix round 8''')])

# ---------------------------------------------------------------- (2) retired (their code was deleted)
RETIRED = ("R-2 the anchor ignores the registered evidence (plan only)",
           "R-2 the anchor is the LATEST source, not the earliest", "R-2 the RUN-ACK does not anchor the opening",
           "F-1/G-1 the vouched plan is no source", "F-1 earlier-close evidence is a fallback source",
           "F-1 the AUDIT-ACK's opening close is no fallback source", "F-1 the opening records are no fallback source",
           "F-1 the bound plan hash is not compared",
           "G-1 a broken AUDIT-ACK binding lets the manifest vouch for the plan",
           "G-1 an outage manifest is not checked against the opening records",
           "G-1 the RUN-ACK is not found through the attestation / prereg bindings")
MUTANTS[:] = [m for m in MUTANTS if m["name"] not in RETIRED]

# ---------------------------------------------------------------- (3) round-8 mutants
H1 = [F8 + f"test_h1_probe_an_edited_plan_with_an_unreadable_manifest_aborts_and_restoring_does_not_resume[{x}]"
      for x in ("delete", "corrupt", "list")]
H2 = [F8 + "test_h2_probe_a_six_file_coordinated_edit_aborts_through_the_ack_found_by_its_bundle"]
M("H ACKs are found whatever bundle they carry", CM, "bundle_acks",
  [('''                if f.get("bundle_sha256") == b:''', '''                if True:''')],
  [F4 + "test_n3_clock_anchor_a_forged_prereg_and_run_ack_before_the_opening_cannot_record_a_bundle_abort"],
  "an ACK carrying another bundle is no registration: the bundle difference stays a refusal")
M("H the anchor cancels an external ACK", CM, "registration_state",
  [('''            "registered": bool(later) or (local and _registered(w))}''',
    '''            "registered": local and (bool(later) or _registered(w))}''')],
  [F8 + "test_h_a_run_ack_carrying_the_bundle_is_a_registration_even_before_the_opening"],
  "a RUN-ACK carrying the bundle is a registration even before the anchor")
M("H the opening close is named by plan.json", CM, "registration_state",
  [('''    oday = days[0] if days else None''', '''    oday = _opening_day_of(out)''')],
  H1[:1] + H2, "an edited plan never names the opening close: the abort")
M("H the external ACKs' bound hashes are not checked", CM, "registration_problems",
  [('''    probs += _ack_bound_problems(out, st, seal_rel)''', '''    pass''')],
  H2, "a coordinated six-file edit is caught by the hashes the external ACKs bound")
M("H opening evidence before any AUDIT-ACK is no problem", CM, "registration_problems",
  [('''    if not st["outage"] and not st["audited"]:              # fix round 8 (rule 3): not past audit''',
    '''    if not st["outage"] and not st["audited"] and False:''')],
  [F8 + "test_h_opening_evidence_without_any_audit_ack_for_the_bundle_is_the_abort"],
  "opening evidence with no AUDIT-ACK for the bundle is the abort (fail closed)")
M("H an outage drops the local witnesses", CM, "registration_state",
  [('''        oday, local = _opening_day_of(out), True''', '''        oday, local = None, False''')],
  [F2 + "test_b3_a_mailbox_outage_cannot_downgrade_an_established_violation"],
  "a violation observed during a mailbox outage is still the persistent abort (B3.4)")

# ---------------------------------------------------------------- (4) after the first fix-8 subset run: tightened
# (HARNESS: "N-3 opening_anchor" named the removed fix4 test -> retargeted to the probe-9 anchor assertion; 2
# SURVIVED: in a registered state other checks also catch them -> an isolating test each)
BY = {m["name"]: m for m in MUTANTS}
BY["N-3 opening_anchor: the anchor is the opening close itself"]["tests"] = [PROBE9_TWO]
BY["N-3 opening_anchor: the anchor is the opening close itself"]["retargeted"] = (
    "fix round 8: its intended test was removed (§21.2); the probe-9 test asserts the anchor")
BY["H the opening close is named by plan.json"]["tests"] += [
    F6 + "test_f1_an_edited_plan_never_lets_earlier_close_evidence_anchor_the_clock"]
BY["H the external ACKs' bound hashes are not checked"]["tests"] += [
    F8 + "test_h_retro_only_the_external_acks_bind_a_coordinated_plan_edit"]
for name in ("H the opening close is named by plan.json", "H the external ACKs' bound hashes are not checked"):
    BY[name]["tightened"] = "fix round 8: an isolating (existing or retrospective) test added after the subset run"
