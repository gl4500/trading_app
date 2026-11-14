# S1 design v5 — Addendum 3 rev 5, Erratum 2, Clarification 4 (EARLY-INTENT lower bound) — draft revision 1

**Status: PROPOSAL.** This is a prospective clarification, to be adopted before the AUDIT-ACK. It is never retrofitted to
a registered trial. Nothing here is in force until it goes through the project's adoption process: Codex's bounded
check, then **separate** operator adoption, then a byte-frozen copy in research/s1/docs.

**What it is.** This is a separate, independently reviewed and adopted artifact.
- It carries r2's former S7 from Clarification 3 (b7f3344f…), with all four corrections Codex required in
  **371c137b-defb-4007-9117-0d2b244c6517**.
- It is split out of Clarification 3, as Codex offered.
- **Adopting Clarification 3 (S1-S6) does not adopt this rule.** Adopting this rule does not adopt Clarification 3.
- The conditional per-close bound in C4.6 needs **both** to be adopted, **and** assumption B (C4.5).

**What it amends.**
- It changes **no byte** of the frozen documents:
  - Erratum 2 r4 (883f09be…);
  - Clarification 1 (2ccb8a28…);
  - Clarification 2 (ba16fdc8…, commit 8dfc1ab).
- It changes no byte of the Clarification 3 drafts.
- It **prospectively replaces OQ-33's early-invocation behaviour** (INTENT, then FAILED, for an invocation before its
  slot) for new invocations only (C4.3).
- It is **not selection-neutral** (C4.2).
- Its sha256 joins the registered bundle (A3.1).

**Sources.**
- **Codex 371c137b** (review of Clarification 3 r2). Records in
  `.coordination/trading_app/s1_clarification3_r2_codex_review_20261109/`, hashes verified:
  - REVIEW.txt 7aa328980ca2997af47a926daaf3bef9f2c38c45cac721b448656c9168cb4c20;
  - assessment.json 623ac4b983f09c6e1ab0efb5fb10452eb095a6721c817906ba7693afe9f38b2e;
  - schedule-bound-check.json 551972bd4e3fb5f3f06f3157a4813386fae45985c56ee6f13ead4a1d9de79dc1. This is Codex's
    executed 60-offset schedule-geometry calculation.
- **Codex b4304771** (review of Clarification 3 r1; `probe_bounds.py` counterexamples).
- **Codex 55c51f51** (row-439 rulings).
- **Claude aa3a2898-eac4-471b-ac4a-8f3e016b2356** (the Clarification 3 r2 submission).
- Operator request, 2026-11-09.

**Code basis.** Read through `git show 8dfc1ab:<path>`.

| file | sha256 at 8dfc1ab |
|---|---|
| s1_journal.py | 27b7123ada7f86233a59b66d3ec8a9cf444eef3a5bc156945fa2f745a091904b |
| s1_slot.py | 09dde1d6e53000b1080e7235a5dc5037caa6be2e051eb7b9aa0e25ac6ffc1448 |
| s1_checkpoint.py | 8ff18d9179bb340c736c152df44586ec0fb8dbb939224190cb9250c97fafd154 |
| s1_common.py | e5b4db83856c499966d76dd71e56d9e15eacce36854bca91673db6a5937257de |
| s1_trial.py | c871c4dd8d30bd1965478c2a9050aa0152935c788331fdb25244f0fcd1883519 |

**Current behaviour (8dfc1ab).**
- **The clock sample.** `j.append` samples the clock inside the BEGIN IMMEDIATE transaction (`now = clock()`,
  s1_journal.py:528), decides on it (:529), INSERTs, then COMMITs (:531).
- **SLOT-INTENT has an upper permission bound only:** `now >= E` refuses (:413).
- **`messages.created` is sampled before INSERT** (`_insert`, :504).
- **An early invocation today** commits INTENT. `_clock_refusal` then runs after it (run_checkpoint
  s1_checkpoint.py:550-556; opening mode :874-878) and makes the slot FAILED (OQ-33), **unless** the worker pauses
  after the committed INTENT and resumes inside its window. In that case it can capture and QUALIFY: Codex probe 1.
- **A REFUSE from `Worker.intent`** raises SystemExit (s1_slot.py:255-256). Neither run_checkpoint nor `main` records
  it.
- **`c.record_refusal`** (s1_common.py:522-531) is **not called on this path**, and it does `mkdir(parents=True)`
  (:527).

---

## C4.1. The rule
At F0.5 step 6 (timing), for a SLOT-INTENT request:

> SLOT-INTENT permission is decided using the same in-transaction clock sample as every other step-6 decision, and
> APPEND requires s <= sample < E(s). A request whose sample is before scheduled(s) is refused with no row
> (declared tolerance: 0).

1. **Tolerance 0.**
   - It is an exact permission-boundary convention, matched to A5.2's capture lower bound `capture_start >= s`.
   - It is not evidence that the scheduler fires at the right instant.
   - A positive tolerance would reopen a pre-s claim window, and is not proposed.
2. **Clock semantics (Codex correction 3).**
   - The sample is taken **before** INSERT/COMMIT. A pause after the sample can delay the actual commit past E.
     **Step 6 gives no guarantee about the commit time**, and no new commit-clock rule is added.
   - "Within [s, E)" describes the **permission sample** only.
3. **Retry.** A retry at or after s is a **new invocation of the same, unconsumed registered slot**. It is not
   re-clocking or slot-sliding.
   - The registered scheduled identity is unchanged.
   - This rule authorizes **no** extra retry policy and **no** compensating capture.
4. **The W claim interval is empty.** For every W slot, E = W = s, so [s, s) is empty: no W slot can be claimed
   (consistent with A5.3). The exact W_L route never opens an attempt, and stays provider-free at **any** clock
   (r4 G2.1).
5. **The `_clock_refusal` t < s path** (OQ-33) stays as a fail-closed defence, for example against clock rollback.
   On an order-consistent clock it becomes unreachable for new attempts.

## C4.2. Cost and selection (Codex correction 1): NOT selection-neutral
Both of these outcomes are real. Which one occurs depends on dispatch and pause history.
1. **An early-paused worker loses a capture.**
   - Today, an early invocation can commit INTENT, pause before `_clock_refusal`, resume inside its own window, and
     validly QUALIFY (probe 1).
   - Under C4 the same early invocation is refused and exits. Unless a new, timely invocation follows, that capture
     is **lost**, and the slot later becomes **MISSED**.
   - That can **lower availability** and **change which capture seals**.
2. **An immediately-failed early invocation, followed by a retry, gains a capture.**
   - Today, an early invocation that reaches `_clock_refusal` at once becomes **FAILED**. The slot is consumed, and a
     retry is refused by the restart pre-check / repeat rule.
   - Under C4, the early invocation leaves no row, so a later invocation at or after s can capture. That can
     **increase availability** and also **change selection**.
3. **Both are genuine policy and observability changes.** C4 is **not** selection-neutral, unlike Clarification 3's S1.
   - Its cost is part of what the operator adopts, explicitly.
   - It gives no permission to slide a slot, or to compensate with an extra retry policy that is not separately
     authorized.

## C4.3. Recording (Codex correction 2)
1. **A new definition.** A request refused before its SLOT-INTENT is committed is an **unauthorized invocation, not a
   capture attempt**.
   - This prospectively and explicitly **replaces OQ-33's INTENT + FAILED behaviour** for early invocations.
   - Every **actual** attempt (an INTENT exists) is still preserved, as A5.2 requires.
   - **Historical rows are unchanged:** an old early INTENT is never treated as nonexistent, and old FAILED or TIMEOUT
     history is never mutated.
2. **No journal row.** The early refusal writes no journal row of any kind, and no claim, capture or callback. A
   journal attempt row is **never** used to meet the diagnostic requirement.
3. **Implementation requirement (not a claim about current code).** Preserve the early refusal's diagnostic record:
   - the original registered slot, the observed decision time (the in-transaction sample) and the reason;
   - through a **reviewed local / launcher diagnostic path outside the journal**;
   - with no claim, no capture, and **no recreation of a missing trial root or its ancestors**.
   - Current code has no such path. The existing `c.record_refusal` is not on it and can `mkdir`
     (s1_common.py:527), so it must not be assumed to qualify.
4. **When the diagnostic write fails:** the command **still refuses**, does no work, and **discloses the recording
   gap** in its refusal output. Durable logging is not promised beyond the implemented path.

## C4.4. Scope and precedence (Codex correction 4)
1. **All callers.** At generic F0.5 step 6, C4 applies to **all** SLOT-INTENT callers, **including** opening mode
   (`run_opening_checkpoint`) and scheduled-mode slots of sessions opening before START.
   - This differs from Clarification 3's S1 and Clarification 2's session-domain restriction.
   - It is recorded here so that the change is not hidden or mode-dependent.
   - It is controlled by row 545.
2. **The exact W_L route** is unaffected: provider-free at any clock, and it never opens an attempt.
3. **Precedence.** Everything that decides before step 6 keeps precedence over the new step-6 timing reason:
   - CLOSED (step 2), INVALID (step 3), identity and contradiction checks (step 4, including 4b repeat-attempt);
   - STOPPED -> LOST-RACE and the slot-gate reasons (step 5: PREREG, Clarification 2, Clarification 3 S1);
   - the gate's identity and integrity outcomes (F0.6, r4 G6).
4. **Pinned reason (proposed):** "slot <s> requested before its scheduled instant: no claim (Clarification 4)". The
   exact bytes are fixed at implementation.

## C4.5. Assumption B (Codex's form, O-S8 accepted)
**B.** Every claimed attempt relevant to the trial (**every qualifying claim**, not only healthy workers or successful
scheduler runs) has an **ACTUAL committed terminal row by D(s) + δ**: a valid completion, or a TIMEOUT. A late J after
a committed TIMEOUT stays LOST-RACE (4c / E1.3).
- "A finalizer launched by D + δ" is weaker and **insufficient**. B includes dispatch, waits, processing and the
  terminal transaction's commit.
- An unhandled crash, outage or lock delay beyond the bound violates B.
- **B is not code-enforced**, and this clarification does not establish it.
- **If B is absent or violated,** the small envelope is unavailable. The actual history is preserved, and the full
  conservative stress envelope applies (Clarification 3 S4.3). **No automatic INVALID or withdrawal follows.**

**What does not count as evidence of B.**
- `SLOT-QUALIFIED.at` is R, not the commit instant.
- `messages.created` is sampled before INSERT/COMMIT (s1_journal.py:504; the decision sample is at :528), so it is
  not an upper-bound witness of the actual terminal commit.
- B needs independent dispatch and completion evidence for the declared operating envelope. For example, a
  post-commit observation or return with a stated clock relationship, in the separately reviewed R-3 evidence.
- No live scheduler experiment and no new witness product schema are authorized here.
- A few observed runs are not a universal reliability guarantee. B stays an explicit operating assumption.

## C4.6. Conditional bound under Clarification 3 S1 + C4 + B (Codex's refined clocks)
**Model.** A common, order-consistent timing model of actual causal instants. Calendar or clock-mapping
inconsistencies, or a rollback, are never silently treated as proof of B.

**Definitions** (Clarification 3 S4):
- **t_q** is the **actual** commit instant of q0's QUALIFIED (the first committed QUALIFIED of close C). It is not its
  stored R.
- **A0** is the slots whose INTENT committed before t_q, q0 included.
- **B0** is the slots claimed afterwards. Under S1 they are earlier than scheduled(q0).

**Proof.**
- **(i) B0.**
  - Let c be the **permission-clock sample** of the claim's transaction. The transaction sees q0 committed
    (serialized BEGIN IMMEDIATE), so c >= t_q under the stated clock relation.
  - C4 and step 6 give s <= c < E(s) <= s + 10 min, so **s > t_q - 10 min**.
  - Nothing is asserted about this claim's actual commit (c_commit is not bounded by E).
- **(ii) A0 members that eventually QUALIFY**, q0 included.
  - C4's sample is >= s, and the claim's commit causally precedes t_q, so **s < t_q**.
  - B's actual terminal deadline: the QUALIFIED commit is >= t_q, and it is no later than D(s) + δ <= s + 40 min + δ,
    so **s >= t_q - 40 min - δ**.
  - Claims that never QUALIFY add nothing to Q(C).
- **(iii)** So every QUALIFIED slot of C lies in the **half-open** interval **[t_q - 40 min - δ, t_q)**.

**Geometry (O-S9 accepted, conditional).** Codex executed the unchanged `schedule` function at 8dfc1ab for all 60
close-minute offsets (schedule-bound-check.json).
- The minimum span of 8 consecutive slots is **71 min**: close minute 4, offsets 45, 47, 49, 51, 53, 55, 56, 116.
- On the hour it is 75 min.
- So a half-open interval of length <= 71 min holds at most 7 slots. **Strict endpoints matter:** a closed 71-min
  interval can hold 8.
- No rounding, and R is never substituted for the commit instant.

**Result.** **Q(C) <= 7 if δ <= 31 min**, for **fresh governed post-START histories only**: closes whose attempts were
all opened under Clarification 3 S1 and C4, with B holding.
- Not covered: legacy histories, pre-START retained evidence, and bytes per tree. Those are additional and unbounded
  here.
- No unconditional tree-count or timing claim is made. Row 439 stays **NOT READY** until B is independently evidenced
  (R-3) and a new, separately predeclared, controller-committed campaign is run on final code.

**Without B, or without Clarification 3 S1,** there is no small bound.
- A worker can pause between R and J, and step 6 checks only R < D (s1_journal.py:415).
- Without S1, later slots can claim after t_q.

**Witnesses.**
- Probe 1 (early claims at C+40) is refused under C4.
- Probe 2 (Q = 5) stays reachable and is inside the bound.

## C4.7. Interaction with Clarification 3 row 524
- If C4 is adopted, Clarification 3 row 524's Q = 8 (probe 1, early intent) is **no longer reachable through the
  production entry points**. It becomes a **historical (pre-C4)** characterization, or a **staged S1-only committed
  fixture**, labelled as such.
- Row 548 checks that it is not presented as production-reachable.
- **No runtime "disable C4" bypass** is introduced to make both statements hold.

## C4.8. Acceptance rows (from 540; they supersede Clarification 3 r2's draft S7 rows 540-544, which were never adopted)
**Evidence form.**
- Changed behaviours: old-fail / new-pass RED/GREEN, with explicit old -> new evidence where the policy outcome
  changes.
- Controls stay passing.
- Characterizations and staged fixtures are labelled.
- Mutants keep named kill evidence.
- All mailboxes are synthetic, and spies cover claim, capture, callbacks and every journal append.

| id | case | requirement | test to create | expected outcome | evidence | owner |
|---|---|---|---|---|---|---|
| 540 | C4-A1 | C4.1 | test_s1_a3_intent_lower_bound.py::test_permission_boundary[sample-s-minus-1us-refused-no-row,sample-equals-s-appends,sample-s-plus-epsilon-appends,zero-tolerance-declared] | the transaction sample at s - 1 µs: REFUSE, no row; at s and s + ε: APPEND; the declared tolerance is 0 | changed RED/GREEN (first); controls | H5 |
| 541 | C4-A2 | C4.1.4 | test_s1_a3_intent_lower_bound.py::test_w_claim_interval_empty[non-last-close-w-slot-never-claimable-ends-missed,exact-w-l-route-unaffected-any-clock] | a W slot of a non-last close is never claimable and ends MISSED at E; the exact W_L route stays provider-free and opens no attempt at any clock | changed RED/GREEN (first); control (second) | H5 |
| 542 | C4-A3 | C4.2.1 | test_s1_a3_intent_lower_bound.py::test_early_paused_worker_loses_capture[old-head-early-intent-pause-resume-qualifies,new-head-early-refused-no-retry-slot-missed] | old head: an early INTENT, pause, resume inside the window: QUALIFIED (it can be selected). New head: the same invocation is refused, no retry follows, the slot ends MISSED, and the selection can change | old -> new policy evidence (changed) | H5 |
| 543 | C4-A4 | C4.2.2 | test_s1_a3_intent_lower_bound.py::test_failed_early_then_retry_gains_capture[old-head-early-failed-retry-refused,new-head-early-refused-retry-at-s-qualifies] | old head: an early invocation becomes INTENT + FAILED, and a retry is refused (restart pre-check). New head: the early invocation leaves no row, and a retry at s QUALIFIES; the selection can change | old -> new policy evidence (changed) | H5 |
| 544 | C4-A5 | C4.3 | test_s1_a3_intent_lower_bound.py::test_early_refusal_diagnostics[records-slot-sample-reason,no-journal-row,no-claim-no-capture,missing-root-not-recreated,diagnostic-write-failure-still-refuses-and-discloses-gap] | the reviewed diagnostic path records the slot, the observed sample and the reason; no journal row, no claim or capture; a missing root is never created; on a write failure the command still refuses, does no work and states the gap | changed RED/GREEN | H5 |
| 545 | C4-A6 | C4.4 | test_s1_a3_intent_lower_bound.py::test_scope_and_precedence[opening-mode-early-refused,opening-mode-equality-appends,scheduled-pre-start-session-early-refused,scheduled-pre-start-session-equality-appends,closed-first,invalid-first,identity-first,integrity-first,repeat-attempt-first,stopped-lost-race-first,slot-gate-reasons-first] | opening and pre-START callers are governed by C4 (early refused, equality appends); every earlier step (CLOSED, INVALID, identity/integrity, 4b repeat, STOPPED, slot-gate reasons PREREG/C2/S1) wins over the C4 timing reason | changed RED/GREEN (early params); controls | H5 |
| 546 | C4-A7 | C4.1.2 | test_s1_a3_intent_lower_bound.py::test_sample_before_e_commit_after_e[sample-before-e-commit-after-e-appends] | a permission sample before E with an actual commit after E (barrier between the sample and the commit) APPENDs: no commit-time guarantee is advertised | characterization | H5 |
| 547 | C4-A8 | C4.6 | test_s1_a3_intent_lower_bound.py::test_conditional_bound_witnesses[probe1-early-claims-refused,probe2-still-q5,seven-slot-witness-close-minute-4,eighth-slot-excluded-half-open,delayed-j-after-committed-timeout-lost-race] | with S1 and C4 in force and B **staged** in the fixture (TIMEOUT committed within δ): probe 1's early claims are refused; probe 2 gives Q = 5; a minute-4 close reaches 7; an 8th cannot fall inside a 71-min half-open interval; a J after a committed TIMEOUT is LOST-RACE. A staged B is not evidence of B | witness / characterization (staged B, labelled) | H5 |
| 548 | C4-A9 | C4.7 | test_s1_a3_intent_lower_bound.py::test_row524_interaction[row524-labelled-historical-or-staged,no-disable-c4-bypass] | Clarification 3 row 524's Q = 8 runs only as a historical / staged S1-only fixture; no runtime switch disables C4 | control (review-backed) | H5 |
| 549 | C4-A10 | mutants | test_s1_a3_mutants.py targeted::intent_lower_bound[lower-bound-removed,tolerance-nonzero,gt-instead-of-ge,commit-clock-instead-of-sample,journal-row-on-refusal,root-recreated-by-diagnostic,mode-restricted-to-post-start,step6-before-step5,route-opens-intent] | lower-bound-removed -> 540[sample-s-minus-1us-refused-no-row]; tolerance-nonzero -> 540[sample-s-minus-1us-refused-no-row]; gt-instead-of-ge -> 540[sample-equals-s-appends]; commit-clock-instead-of-sample -> 546[sample-before-e-commit-after-e-appends]; journal-row-on-refusal -> 544[no-journal-row]; root-recreated-by-diagnostic -> 544[missing-root-not-recreated]; mode-restricted-to-post-start -> 545[opening-mode-early-refused]; step6-before-step5 -> 545[slot-gate-reasons-first]; route-opens-intent -> 541[exact-w-l-route-unaffected-any-clock] | mutant kill evidence | H5 |

**Counts** (mechanical, from the bracketed ids; an unparameterized row counts as 1):
- **10 map rows (540-549) / 10 acceptance cases (C4-A1..C4-A10), 43 parameterized instances.**
  - Per row: 4, 2, 2, 2, 5, 11, 1, 5, 2, 9.
  - 34 behaviour / control / characterization instances plus 9 mutants.
  - All rows are owned by H5.
- These are proposed coverage counts, not executed tests.

---

## Open points (not decided here)
- **O-C4-1: the diagnostic path's form.** The diagnostic path for early refusals is not yet specified. A launcher log,
  a separate local file under an existing root, or stderr captured by the launcher are possible. The implementation
  must name it, and it must be reviewed (C4.3.3). A no-mkdir guard is mandatory.
- **O-C4-2: the operator must explicitly adopt C4.2's selection and availability costs.** Both directions are real.
  If the operator declines, OQ-33's current behaviour stays, and Clarification 3 S4's full envelope applies.
- **O-C4-3: B stays unevidenced.** The C4.6 bound is unavailable until R-3 supplies independent post-commit
  completion and dispatch evidence for the declared envelope. Row 439 stays NOT READY.
- **O-C4-4: opening-mode impact.** In opening mode, an early opening-slot invocation that today becomes INTENT + FAILED
  (and can, if paused, yield the opening seal) is now refused with no row. The opening issuance checklist (F7.2(b):
  every opening slot terminal) is unchanged: such a slot ends MISSED at its E instead of FAILED.
  - Codex to confirm that this is acceptable within the opening window constraint of E5.6.
- **Disclosures:**
  - Drafted by a Claude subagent for the controller.
  - Codex's review was read after peer exposure, not blind.
  - Shared code and documents form one evidence lineage.
  - The C4.6 proof is a derivation. The geometry figure comes from Codex's executed calculation, not re-run here.
  - No implementation, test, benchmark, live, provider, scheduler or mailbox step was run. No repo file was edited.
  - Isolation and stage order are convention, not enforcement.
  - Status: NO_CONSENSUS on this exact text pending Codex's bounded check. Row 439: NOT READY. Operational readiness:
    INSUFFICIENT_EVIDENCE.

## Process
1. Codex's bounded check of this exact draft, independent of Clarification 3.
2. Separate operator adoption, including the C4.2 costs. If declined, OQ-33 stays and Clarification 3 S4 governs.
3. A byte-frozen copy in research/s1/docs.
4. H5 (or a named adjacent task) implements rows 540-549 with RED/GREEN.
5. Any capacity use of C4.6 waits for R-3 evidence of B and a new predeclared campaign.

No registration, audit, START, RUN, scheduler or live step is authorized by this clarification.
