"""Task 12 fix round 6 (re-review 4: F-1; A10.2). Applied to MUTANTS after fix round 5:
(1) RETARGET the round-5 R-2 mutants whose source text the round-6 anchor replaced (same intent on the new code);
(2) ADD targeted mutants for the round-6 behaviour, each with its intended test(s)."""
from s1_mutants_t12_list import CM, M, MUTANTS

F5 = "test_s1_t12_fix5.py::"
F6 = "test_s1_t12_fix6.py::"
BY = {m["name"]: m for m in MUTANTS}


def retarget(name, edits, *, tests=None, function=None):
    m = BY[name]
    f = m["file"]
    m["edits"] = [(e[0], e[1], e[2]) if len(e) == 3 else (f, e[0], e[1]) for e in edits]
    m["retargeted"] = "fix round 6: source replaced by the re-review-4 fix; same intent on the new code"
    if tests:
        m["tests"] = tests
    if function:
        m["function"] = function


# ---------------------------------------------------------------- (1) retargets (R-2 on the F-1 anchor)
retarget("R-2 the anchor ignores the registered evidence (plan only)",
         [('''    if bound is None or plan_ok:''', '''    if True:''')])
retarget("R-2 the anchor is the LATEST source, not the earliest",
         [('''    return min(anchors) if anchors else plan_anchor''', '''    return max(anchors) if anchors else plan_anchor''')],
         tests=[F6 + "test_f1_retro_without_the_audit_ack_the_run_ack_alone_anchors_an_edited_plan"],
         function="opening_anchor")
retarget("R-2 the RUN-ACK does not anchor the opening",
         [('''    ack = run_ack_witness(out, mailbox)
    days.add(''', '''    ack = None
    days.add(''')],
         tests=[F6 + "test_f1_retro_without_the_audit_ack_the_run_ack_alone_anchors_an_edited_plan"],
         function="_fallback_opening_days")

# ---------------------------------------------------------------- (2) round-6 mutants
PROBE9 = [F6 + "test_f1_probe_fabricated_earlier_close_evidence_before_the_opening_is_a_refusal"
          f"[{i}]" for i in ("earlier-claim+opening-claim+prereg", "two-claims",
                             "earlier-seal+opening-claim+attest_start")]
M("F-1 the plan is never authoritative (always the fallback)", CM, "opening_anchor",
  [('''    if bound is None or plan_ok:''', '''    if bound is None:''')],
  PROBE9, "while plan.json carries the bound hash its opening close is the anchor: earlier-close files are a refusal")
M("F-1 earlier-close evidence is a fallback source", CM, "_fallback_opening_days",
  [('''    return {d for d in days if ack_day is None or str(d) >= ack_day}''', '''    return days''')],
  [F6 + "test_f1_an_edited_plan_never_lets_earlier_close_evidence_anchor_the_clock"],
  "a close earlier than the AUDIT-ACK's opening close never anchors the clock")
M("F-1 the AUDIT-ACK's opening close is no fallback source", CM, "_fallback_opening_days",
  [('''    out, days = Path(out), {ack_day} - {None}''', '''    out, days = Path(out), set()''')],
  [F6 + "test_f1_an_edited_plan_never_lets_earlier_close_evidence_anchor_the_clock"],
  "with an edited plan the AUDIT-ACK's opening close anchors the clock")
M("F-1 the opening records are no fallback source", CM, "_fallback_opening_days",
  [('''        days |= {rel[len("seals/"):-len(".json")] for rel in (rec or {}).get("artifacts", {})
                 if rel.startswith("seals/") and rel.endswith(".json")}''', '''        pass''')],
  [F6 + "test_f1_retro_without_the_audit_ack_the_opening_records_anchor_an_edited_plan"],
  "without the AUDIT-ACK the opening records' seal path anchors an edited plan")
M("F-1 the bound plan hash is not compared", CM, "opening_anchor",
  [('''    plan_ok = bound is not None and (out / "plan.json").is_file() and sha256_file(out / "plan.json") == bound''',
    '''    plan_ok = True''')],
  [F5 + "test_r2_probe_moving_the_plans_opening_close_after_registration_aborts_and_restoring_does_not_resume",
   F6 + "test_f1_an_edited_plan_never_lets_earlier_close_evidence_anchor_the_clock"],
  "an edited plan is never an anchor source")

# ---------------------------------------------------------------- (3) after the first fix-6 subset run: tightened
# (subset run: 5 survivors - each source is masked by the AUDIT-ACK's opening close or by the "no source -> None"
# strictness; the code now falls back to the plan anchor when no source exists, and retrospective / strengthened
# tests isolate each source)
BY = {m["name"]: m for m in MUTANTS}
BY["F-1 the plan is never authoritative (always the fallback)"]["tests"] += [
    F6 + "test_f1_retro_an_unchanged_plan_is_authoritative_even_when_the_audit_ack_is_unreadable"]
for name in ("F-1 the plan is never authoritative (always the fallback)", "R-2 the anchor is the LATEST source, not "
             "the earliest", "R-2 the RUN-ACK does not anchor the opening", "F-1 the opening records are no fallback "
             "source", "F-1 earlier-close evidence is a fallback source"):
    BY[name]["tightened"] = ("fix round 6: masked in the first subset run; isolated by a retrospective or "
                             "strengthened test (and the plan-anchor fallback when no source exists)")
BY["R-2 the anchor is the LATEST source, not the earliest"]["tests"] += [
    F6 + "test_f1_retro_a_later_fallback_source_never_delays_the_anchor"]
