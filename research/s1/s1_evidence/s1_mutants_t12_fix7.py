"""Task 12 fix round 7 (re-review 5: G-1; A10.2). Applied to MUTANTS after fix round 6:
(1) RETARGET the round-6 mutants whose source text the round-7 anchor replaced (same intent on the new code);
(2) ADD targeted mutants for the round-7 behaviour, each with its intended test(s)."""
from s1_mutants_t12_list import CM, M, MUTANTS

F5 = "test_s1_t12_fix5.py::"
F6 = "test_s1_t12_fix6.py::"
F7 = "test_s1_t12_fix7.py::"
BY = {m["name"]: m for m in MUTANTS}


def retarget(name, edits, *, tests=None, function=None):
    m = BY[name]
    f = m["file"]
    m["edits"] = [(e[0], e[1], e[2]) if len(e) == 3 else (f, e[0], e[1]) for e in edits]
    m["retargeted"] = "fix round 7: source replaced by the re-review-5 fix; same intent on the new code"
    if tests is not None:
        m["tests"] = tests
    if function:
        m["function"] = function


# ---------------------------------------------------------------- (1) retargets
retarget("R-2 the anchor ignores the registered evidence (plan only)",
         [('''    days = _fallback_opening_days(out, rows, ack_day, mailbox)''', '''    days = set()''')],
         tests=BY["R-2 the anchor ignores the registered evidence (plan only)"]["tests"]
         + [F7 + "test_g1_probe_editing_plan_and_manifest_together_aborts_and_restoring_does_not_resume[bogus]"])
retarget("F-1 the plan is never authoritative (always the fallback)",
         [('''    if plan_ok and plan_anchor is not None:''', '''    if False:''')],
         tests=[F6 + "test_f1_probe_fabricated_earlier_close_evidence_before_the_opening_is_a_refusal"
                "[earlier-claim+opening-claim+prereg]"])
BY["F-1 the plan is never authoritative (always the fallback)"]["name"] = "F-1/G-1 the vouched plan is no source"
BY["F-1/G-1 the vouched plan is no source"] = BY.pop("F-1 the plan is never authoritative (always the fallback)")

# ---------------------------------------------------------------- (2) round-7 mutants
M("G-1 a broken AUDIT-ACK binding lets the manifest vouch for the plan", CM, "_audit_bound",
  [('''    except (SystemExit, OSError, ValueError, KeyError, TypeError, AttributeError):
        return None, None, "broken"''', '''    except (SystemExit, OSError, ValueError, KeyError, TypeError, AttributeError):
        return m.get("plan_sha256"), None, "outage"''')],
  [F7 + f"test_g1_probe_editing_plan_and_manifest_together_aborts_and_restoring_does_not_resume[{x}]"
   for x in ("bogus", "None")], "a broken AUDIT-ACK binding never lets the local manifest vouch: the abort")
M("G-1 an outage manifest is not checked against the opening records", CM, "_audit_bound",
  [('''        if bound_m and bound_m != {sha256_file(mp)}:''', '''        if False:''')],
  [F7 + "test_g1_a_mailbox_outage_never_lets_a_manifest_differing_from_the_opening_records_vouch_for_the_plan"],
  "in an outage a manifest differing from the opening records vouches for nothing: the abort")
M("G-1 the RUN-ACK is not found through the attestation / prereg bindings", CM, "run_ack_witness",
  [('''    for name in ("attest_start.json", "prereg.json"):           # fix round 7 (G-1): the hashes they bound''',
    '''    for name in ():''')],
  [F7 + "test_g1_the_run_ack_alone_anchors_when_the_audit_ack_binding_is_broken"],
  "with plan and manifest edited, the RUN-ACK bound through prereg still witnesses and anchors: the abort")

# ---------------------------------------------------------------- (3) after the first fix-7 subset run: tightened
# (3 survivors: the plan source can only lower the anchor, so each shows only when an edited plan names an EARLIER
# close than every other source; one RETROSPECTIVE isolating test each)
BY = {m["name"]: m for m in MUTANTS}
for name, t in (("F-1/G-1 the vouched plan is no source", "test_g1_retro_a_vouched_plan_keeps_the_anchor_below_a_"
                                                          "later_forged_source"),
                ("G-1 a broken AUDIT-ACK binding lets the manifest vouch for the plan",
                 "test_g1_retro_a_broken_binding_never_lets_an_edited_plan_pull_the_anchor_earlier"),
                ("G-1 an outage manifest is not checked against the opening records",
                 "test_g1_retro_an_outage_manifest_differing_from_the_records_never_pulls_the_anchor_earlier")):
    BY[name]["tests"] = BY[name]["tests"] + [F7 + t]
    BY[name]["tightened"] = "fix round 7: a retrospective test whose intended assertion fails on this mutant (A10.2)"
