# Task 2 retained Hypothesis examples (A3-PR1-3, R2-08, map rows 48 and 298)

Property: `research/s1/s1_tests/test_s1_a3_precedence.py::test_substep_conditions_are_disjoint_and_decide_matches_the_oracle`

Settings: `@settings(max_examples=400, deadline=None, derandomize=True, database=None)`. No example database is used or
kept. The generated sequence is deterministic (derandomize), so replaying means running the test. The explicit
`@example`s below always run first, before any generated case.

Scope: slot-subject histories x the five slot kinds x five instants (E-1us, E, D-1us, D, D+1us) x four (op, actor)
pairs. Stage and trial lifecycles are covered by the explicit `test_precedence_table` cases, not by this property.

## Retained examples

| # | example | outcome pinned (oracle and decide) | rule it pins | why it is kept |
|---|---|---|---|---|
| 1 | `hist=[SI, TO], kind="SLOT-QUALIFIED", who=(AO, AA), now=D + US` (so R = D + 1us) | LOST-RACE | F0.5 4c before step 6; Erratum 1 E1.3 r3: after a committed TIMEOUT, the authorized worker's completion is LOST-RACE at 4c whatever its R (map rows 257, 338) | Seed. It is the E1.3 boundary: a late R that would be REFUSE at step 6 if 4c did not decide first. A decide that ran the timing step before the terminal check gives REFUSE here. |
| 2 | `hist=[SI], kind="SLOT-QUALIFIED", who=(AO, AA), now=D` (so R = D) | REFUSE | F0.5 step 6: R >= D is REFUSE while no terminal row exists (E1.3: "REFUSE for a late R applies only while no terminal row exists yet"; map row 44) | Seed. It is the other side of the same boundary: with no terminal row, the late R is refused at step 6, not LOST-RACE. Together with #1 it pins that 4c, not the R test, separates the two. |

## Minimized counterexamples found during development

None. Against the implementation the property passed on its first run (t2_green.txt). Against the permissive stub
the two explicit examples failed first (t2_red_property.txt: APPEND != LOST-RACE for #1, APPEND != REFUSE for #2), so
Hypothesis reported those explicit examples and generated no new minimized case. If a later change makes the
property fail, the minimized failing input must be added here and as an `@example`, with the rule it reproduced.
