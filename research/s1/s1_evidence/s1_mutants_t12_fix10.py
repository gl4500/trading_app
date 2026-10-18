"""Task 12 fix round 10 (re-review 8 m-1; A10.2): targeted mutants for the EARLIEST_CLOSE_NY check added to
s1_seal.calendar_problems, each with its intended test(s). No earlier mutant's source text changed."""
from s1_mutants_t12_list import M, SE

F10 = "test_s1_t12_fix10.py::"
EARLY = [F10 + f"test_m1_a_session_closing_before_the_earliest_early_close_refuses_the_audit[{d}]"
         for d in ("2026-10-23", "2026-11-27", "2027-05-14")]
M("m-1 a session closing before the earliest early close is accepted", SE, "calendar_problems",
  [('''        if in_range and _ny(x["date"], x["close"]) < _ny(x["date"], c.EARLIEST_CLOSE_NY.strftime("%H:%M")):''',
    '''        if False:''')],
  EARLY, "a provider session closing before 13:00 New York refuses the audit (fail closed)")
M("m-1 a close exactly at the earliest early close refuses", SE, "calendar_problems",
  [('''        if in_range and _ny(x["date"], x["close"]) < _ny(x["date"], c.EARLIEST_CLOSE_NY.strftime("%H:%M")):''',
    '''        if in_range and _ny(x["date"], x["close"]) <= _ny(x["date"], c.EARLIEST_CLOSE_NY.strftime("%H:%M")):''')],
  [F10 + "test_m1_guard_a_session_closing_exactly_at_the_earliest_early_close_is_accepted"],
  "a 13:00 early close (the boundary) is a valid session")
M("m-1 only sessions outside calendar_range are checked", SE, "calendar_problems",
  [('''        in_range = rng is None or len(rng) != 2 or str(rng[0]) <= x["date"] <= str(rng[1])''',
    '''        in_range = rng is None or len(rng) != 2 or not str(rng[0]) <= x["date"] <= str(rng[1])''')],
  EARLY, "every session inside the plan's calendar_range is checked")

# (subset run: "m-1 a close exactly at the earliest early close refuses" was KILLED-BY-EXCEPTION - the refusal escaped
# the guard as SystemExit -> the guard strengthened after the run (pytest.fail on the refusal); re-run: KILLED)


