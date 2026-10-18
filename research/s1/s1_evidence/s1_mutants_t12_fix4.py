"""Task 12 fix round 4 (re-review 2: N-1, N-2, N-3, m-1; A10.2). Applied to MUTANTS after fix round 3:
(1) RETARGET the earlier mutants whose source text the round-4 code replaced (same intent on the new code);
(2) ADD targeted mutants for the round-4 behaviour, each with its intended test(s)."""
from s1_mutants_t12_list import CK, CM, M, MUTANTS

F3 = "test_s1_t12_fix3.py::"
F4 = "test_s1_t12_fix4.py::"
BY = {m["name"]: m for m in MUTANTS}


def retarget(name, edits, *, tests=None, function=None):
    m = BY[name]
    f = m["file"]
    m["edits"] = [(e[0], e[1], e[2]) if len(e) == 3 else (f, e[0], e[1]) for e in edits]
    m["retargeted"] = "fix round 4: source replaced by the re-review-2 fix; same intent on the new code"
    if tests:
        m["tests"] = tests
    if function:
        m["function"] = function


# ---------------------------------------------------------------- (1) retargets
REG = '''    return "RUN-ACK" in w or (len(w) >= 2 and any(x not in IN_PROGRESS for x in w)
                              and any(x in OPENING_TIED for x in w))'''
retarget("C-2/I-2 _registered: a lone witness registers",
         [(REG, REG.replace("len(w) >= 2", "len(w) >= 1"))])
retarget("C-2 _registered: the RUN-ACK is no witness",
         [(REG, REG.replace('"RUN-ACK" in w or ', ""))])
retarget("C-2/M-2 registration_gate ignores the stage lock",
         [('''    if (Path(out) / STAGE_LOCK).exists():''', '''    if False:''')], function="_refuse_if_locked")

# ---------------------------------------------------------------- (2) round-4 mutants
N1_GATE_FIRST = [F4 + f"test_n1_a_gate_racing_a_legitimate_stage_publication_refuses_and_never_aborts[{s}-gate-first]"
                 for s in ("attest_start", "prereg")]
N1_PUB_FIRST = [F4 + "test_n1_a_gate_racing_a_legitimate_stage_publication_refuses_and_never_aborts"
                f"[{s}-publication-first]" for s in ("attest_start", "prereg")]
M("N-1 registration_gate: the lock is not re-checked after the scan", CM, "registration_gate",
  [('''    _refuse_if_locked(out, where)                            # N-1: a publication began during the scan''',
    '''    pass''')],
  N1_GATE_FIRST, "a gate scanning inside a stage publication refuses, never aborts")
M("N-1 registration_gate: the violation is not confirmed by a second scan", CM, "registration_gate",
  [('''    probs = [x for x in again if x in probs]''', '''    pass''')],
  N1_PUB_FIRST, "a violation that vanished before the re-scan is a refusal, never an abort")
M("N-1 registration_gate: no second scan at all", CM, "registration_gate",
  [('''    again = registration_problems(out, mailbox, now=now)''', '''    again = probs''')],
  N1_PUB_FIRST, "a violation that vanished before the re-scan is a refusal, never an abort")
M("N-2 opening_orphans finds nothing", CM, "opening_orphans",
  [('''    d, probs = out / "captures" / oday, []''', '''    return []
    d, probs = out / "captures" / oday, []''')],
  [F4 + f"test_n2_reopening_after_the_local_witnesses_are_deleted_never_writes_a_second_opening_seal[{x}]"
   for x in ("probe", "captures-whole", "resolution+report")],
  "evidence of an earlier opening is the persistent abort, never a second opening seal")
M("N-2 opening_orphans: a capture without its claim ignored", CM, "opening_orphans",
  [('''            if not (d / f"{slot}.attempt.json").exists():''', '''            if False:''')],
  [F4 + "test_n2_opening_seal_creation_refuses_on_earlier_opening_evidence_without_its_record"],
  "the opening seal is never created over an earlier slot's capture")
M("N-2 opening_orphans: a report without its resolution ignored", CM, "opening_orphans",
  [('''            if q.name.endswith(".report.json") and not (d / f"{slot}.resolution.json").exists():''',
    '''            if False:''')],
  [F4 + "test_n2_retro_a_capture_report_without_its_resolution_is_an_earlier_opening_attempt"],
  "a report without its resolution is an earlier opening attempt")
M("N-2 opening_orphans: last_process.json without a claim ignored", CM, "opening_orphans",
  [('''    if (out / "last_process.json").exists() and not any(out.glob("captures/*/*.attempt.json")):''',
    '''    if False:''')],
  [F4 + "test_n2_reopening_after_the_local_witnesses_are_deleted_never_writes_a_second_opening_seal"
        "[captures-whole]"], "last_process.json without any claim is an earlier opening attempt")
M("N-2 opening_orphans: the stored receipt without a SUCCESS ignored", CM, "opening_orphans",
  [('''    if (out / "opening_receipt.json").exists() and not _day_success(out, oday):''', '''    if False:''')],
  [F4 + "test_n2_reopening_after_the_local_witnesses_are_deleted_never_writes_a_second_opening_seal"
        "[resolution+report]"], "the stored opening receipt without its SUCCESS is an earlier opening attempt")
M("N-2 registration_problems: orphans ignored before registration", CM, "registration_problems",
  [('''    if not _registered(w):
        return orphans''', '''    if not _registered(w):
        return []''')],
  [F4 + "test_n2_reopening_after_the_local_witnesses_are_deleted_never_writes_a_second_opening_seal[probe]"],
  "evidence of an earlier opening is the persistent abort, never a second opening seal")
M("N-2 opening seal creation does not re-check the opening evidence", CK, "_before_opening_build",
  [('''    orphans = c.opening_orphans(out)
    if orphans:''', '''    orphans = c.opening_orphans(out)
    if False:''')],
  [F4 + "test_n2_opening_seal_creation_refuses_on_earlier_opening_evidence_without_its_record"],
  "the opening seal is never created over an earlier slot's capture")
M("N-3 _registered: no opening-tied witness required", CM, "_registered",
  [(REG, '''    return "RUN-ACK" in w or (len(w) >= 2 and any(x not in IN_PROGRESS for x in w))''')],
  [F4 + f"test_n3_probe_two_handmade_later_stage_files_before_any_opening_are_a_refusal[pair{i}]"
   for i in (1, 2)], "two hand-made later-stage files are a refusal")
M("N-3 any file at the opening seal's path is a valid opening seal", CM, "_valid_opening_seal",
  [('''        rec = load_json(Path(out) / rel)
        return (isinstance(rec, dict)''', '''        rec = load_json(Path(out) / rel)
        return True or (isinstance(rec, dict)''')],
  [F4 + "test_n3_probe_two_handmade_later_stage_files_before_any_opening_are_a_refusal[pair3]"],
  "a file at the opening seal's path that is no seal of the opening close is no witness")
M("N-3 opening capture evidence is no witness", CM, "registration_witnesses",
  [('''        got.append("opening capture")                       # fix round 4 (N-3): claims, captures, records''',
    '''        pass''')],
  [F4 + "test_n3_retro_opening_slot_claims_tie_the_attestation_to_the_opening"],
  "opening-slot claims tie the attestation's files to the opening")
M("N-3 registration_problems: no clock anchor", CM, "registration_problems",
  [('''    if before_opening(out, now):
        return []
    w, ack = registration_witnesses(out, mailbox)''', '''    w, ack = registration_witnesses(out, mailbox)''')],
  [F4 + "test_n3_clock_anchor_nothing_is_registered_before_the_first_opening_slot"],
  "before the first opening slot nothing is registered: a refusal")
M("N-3 preregistration_problems: no clock anchor", CM, "preregistration_problems",
  [('''    if before_opening(out, now):
        return w + ''', '''    if False:
        return w + ''')],
  [F4 + "test_n3_clock_anchor_nothing_is_registered_before_the_first_opening_slot"],
  "before the first opening slot every registration file is a refusal with zero callbacks")
M("N-3 registration: a prereg is registered before the opening", CM, "registration",
  [('''"registered": not before_opening(out), "ack_id": ack_id}''', '''"registered": True, "ack_id": ack_id}''')],
  [F4 + "test_n3_clock_anchor_a_forged_prereg_and_run_ack_before_the_opening_cannot_record_a_bundle_abort"],
  "before the first opening slot a bundle difference is a refusal, never the bundle abort")
M("N-3 opening_anchor: the anchor is the opening close itself", CM, "opening_anchor",
  [('''    return s1_seal.first_slot_after(close.astimezone(timezone.utc))''',
    '''    return close.astimezone(timezone.utc)''')],
  [F4 + "test_n3_clock_anchor_nothing_is_registered_before_the_first_opening_slot"],
  "the anchor is the opening close's first slot")
M("m-1 stage_publication releases the lock after an error", CM, "stage_publication",
  [('''        return (any(p.exists() for p in stage_records(self.out, self.stage))''',
    '''        return False and (any(p.exists() for p in stage_records(self.out, self.stage))''')],
  [F4 + f"test_minor_an_artifact_write_error_after_the_stage_records_keeps_the_lock_and_refuses[{s}]"
   for s in ("attest_start", "prereg")], "an error after the stage records keeps the lock: a refusal")

# ---------------------------------------------------------------- (3) after fix-round-4 run 1: tightened
# (run 1, s1_mutants_t12_fix4_run1.txt: KILLED=278, BUNDLE-REFUSAL=1, SURVIVED=7 of 286; 3 are the known equivalents;
# each other non-kill got a RETROSPECTIVE isolating test or a strengthened assertion)
BY = {m["name"]: m for m in MUTANTS}
for name, tests in (
        ("C-2/I-2 _registered: a lone witness registers",
         ["test_n3_retro_a_lone_handmade_seal_of_the_opening_close_is_a_refusal"]),
        ("N-1 registration_gate: the lock is not re-checked after the scan",
         ["test_n1_retro_a_publication_released_during_the_gate_rescan_is_a_refusal"]),
        ("attest_start: not after the opening seal's capture",
         ["test_n3_retro_the_attestation_between_the_first_slot_and_the_capture_end_refuses"])):
    BY[name]["tests"] = BY[name]["tests"] + [F4 + t for t in tests]
    BY[name]["tightened"] = "fix round 4: a retrospective test whose intended assertion fails on this mutant (A10.2)"
for name in ("N-3 preregistration_problems: no clock anchor",
             "N-3 registration: a prereg is registered before the opening"):
    BY[name]["tightened"] = ("fix round 4: the intended test strengthened after GREEN (the prereg names the RUN-ACK; "
                             "the assertion message carries no bundle text)")
