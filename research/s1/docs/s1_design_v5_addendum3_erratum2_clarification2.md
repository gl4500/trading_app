# S1 design v5 — Addendum 3 rev 5, Erratum 2, Clarification 2 (M3-PW) — draft revision 2

**Status: PROPOSAL.** This is a prospective clarification, to be adopted before the AUDIT-ACK. It is never retrofitted to
a registered trial. Nothing here is in force until it goes through the project's adoption process: Codex's bounded
check, then operator adoption, then a byte-frozen copy in research/s1/docs.

Revision 2 answers the Codex review 62464458 of r1 (sha256
a24b88c3ee9bfd8f8f9b9ff5f5807f0b056161ab5bed914143a38ec6d1f671f7). r1 is kept unchanged.

The Codex records were verified by sha256 and read as peer data. They are in
`.coordination/trading_app/s1_clarification2_r1_codex_review_20261109/`:
- REVIEW.txt 2ea9051f69c50880a7ae5b4140f8e590dba44846e06f5ecdc73c5d3464f90f58;
- assessment.json 5835287521711a38938630de34a0d1de99ff78c26dd518603e3c214436c7ccdb.

Claude accepts every point.

## Revision table (r1 -> r2)

| item | Codex disposition | what changed in r2 | sections |
|---|---|---|---|
| D1 / O-P1 domain | AMEND (P-CH1): ACCEPT the narrower applicability | D1 is replaced by Codex's controlling text, verbatim. The new refusal predicate is `(open_instant >= START) AND (close_instant > registered deadline)`, on aware instants. A close equal to the deadline is not refused. A session opening before START gets no new refusal and no new authorization. D1.1, D1.3 and D1.6 are aligned, and D2.6 is added. r1's claim that "the bridge branch becomes unreachable" is dropped: the bridge-producing true branch stays reachable for eligible post-START closes. Nothing claims that scheduled mode invokes `opening_gate`. | D1, D2.6, O-P1 |
| Rows 506 / 513 (two mode paths) | AMEND | Row 506 now covers only the `run_opening_checkpoint` path, with its own old guard. New row 513 covers an otherwise authorized scheduled-mode (`run_checkpoint`) slot of the opening close: it keeps its ordinary guards and gets no new refusal. It is paired with row 500's post-deadline refusal control. | D5 rows 506, 513 |
| Row 512 mutants | AMEND: bind kill evidence | Each mutant is bound to a named killing test. The applicability mutant (unconditional membership, which also refuses pre-START sessions) is killed by row 513. Two r1 mutants are withdrawn as behaviourally equivalent, so they have no kill evidence: `open-ge-start-dropped` and `checked-outside-transaction` (O-P6). r1's `lt-instead-of-le` is restated as `ge-instead-of-gt` for the r2 refusal form. | row 512, O-P6 |
| O-P2 / O-P4 fixtures | ACCEPT with a truthful scope label | The predicate- or gate-level fallback is kept, labelled "not a registered end-to-end trial". Production START validation is never relaxed. Both the equality and the +1 µs boundaries are kept. | rows 501, 502, O-P2, O-P4 |
| O-P3 reason | ACCEPT | The reason is pinned in behavioural assertions. It never masks a higher-precedence refusal or INVALID. | rows 500, 507, O-P3 |
| Row 504 | AMEND | The after-W_L completion is an explicitly pre-existing (legacy) eligible claim, an old W_L claim included. No impossible current-entry fixture is used. | row 504 |
| O-P5 | ACCEPT | Unchanged: no readiness credit from the removed d130 trigger; dispatch is R-3. | O-P5 |
| D5 evidence wording | AMEND | The blanket "each case gets behavioural RED" is replaced by Codex's wording: changed behaviours get old-fail / new-pass RED/GREEN; unchanged controls stay passing; setup incompatibilities and predicate-only fixtures are labelled separately; mutants keep named kill evidence. Each row now carries its evidence label. | D5 |
| Counts | recount | Rows and cases go from 13 to 14. Instances go from 38 to 42, counted mechanically: 34 behaviour/control instances plus 8 targeted mutants (r1: 29 + 9). | Counts |


**What it amends.**
- It changes **no byte** of the adopted Erratum 2 r4 or of Clarification 1. Both are frozen in research/s1/docs at
  commit 6172c9b:
  - `s1_design_v5_addendum3_erratum2.md`, sha256 883f09be8471b9da7ee2c01c026ea90f9cec37515d79f3863e8c72085caa6d87;
  - `s1_design_v5_addendum3_erratum2_clarification1.md`, sha256 2ccb8a287de533f08dcbf1e919afb04add8d5a60a0088dfd370649689009e10d.
- It **prospectively narrows** the ordinary post-START worker's permission to open a NEW slot attempt.
  - That permission was previously unchanged: r4 G2.1(7), "Every other slot keeps the existing worker path", with
    OQ-33 kept.
  - The narrowing is not a reinterpretation of the adopted G2 text. G2.2's "no new market window or capture past W"
    is scoped to the W_L route and catch-up (Codex ad2cbf6e §1).
  - If the operator declines this clarification, the current ordinary ineligible-close behaviour stays, and is
    disclosed with its resource bound in readiness (Codex §4).
- Its sha256 joins the registered bundle (A3.1) next to r4's and Clarification 1's.

**Sources.**
- Claude question **8e0ae0cc-5147-4698-af2f-4a8547694594** (M3-PW: captures after W_L; raised by the H3 review).
- Codex ruling **ad2cbf6e** (FORUM-S1-A3-BLK3, M3-PW). CONDITIONAL_CONSENSUS on the scoped prospective guard. This is
  peer data; Claude accepts its scope.
- Records in `.coordination/trading_app/s1_m3_pw_codex_ruling_20261109/`, hashes verified:
  - REVIEW.txt fbf5c71e4cb117d3742ed80eaf1c62b640d02036d3ff04d0e2d0671443cddd67;
  - assessment.json c97941106549dc3277ec902664552e84297a69892e35ce1e0df177410c4e2337.
  - The incoming question, source manifest and Codex's test record were read alongside them.

**Authority read (frozen).**
- r4 G2.1-G2.5 (route, never-does, catch-up, worked histories, scheduler boundary) and R3-A11 / row 420.
- Addendum 1 A5.1-A5.3 (6cb89e36…): A5.1 is the eligibility of a stop or timeout close; A5.2 is the capture
  eligibility E of a registered slot; A5.3 is the 08:00 slot.
- Addendum 2 B1.1/B1.5 (D, and that D never extends capture eligibility).
- Clarification 1 (C4: the opening-finalizer helper; no new CLI).
- t11 dispositions row 305 / case (v) (an ineligible CREATED seal is required integrity evidence).

**Code basis.** Read through `git show 9af5406:<path>`, because H4 is being edited in the tree. Product hashes at
9af5406:

| file | sha256 at 9af5406 |
|---|---|
| s1_checkpoint.py | 8ff18d9179bb340c736c152df44586ec0fb8dbb939224190cb9250c97fafd154 |
| s1_slot.py | 09dde1d6e53000b1080e7235a5dc5037caa6be2e051eb7b9aa0e25ac6ffc1448 |
| s1_journal.py | 27b7123ada7f86233a59b66d3ec8a9cf444eef3a5bc156945fa2f745a091904b |
| s1_seal.py | c46cac8f72bceda01f71c4bd06338d2f74113b693560677ad00115bbbe2d08c4 |
| s1_trial.py | c871c4dd8d30bd1965478c2a9050aa0152935c788331fdb25244f0fcd1883519 |
| s1_tests/test_s1_a3_stop.py | 25062d0e5836a5a976eb25b0c07716cbca0f1d023e612e20d4e6fcd4a6a4d118 |

The s1_checkpoint, s1_slot and s1_seal hashes, and the test hash, match Codex's source-manifest. Citations describe
the current behaviour, not compliance.

**Current behaviour being narrowed (9af5406).**
- `run_checkpoint` (s1_checkpoint.py:525ff) runs these steps, then opens a `Worker` with
  `slot_gate = s1_slot.post_start_gate(gv.trial)` (:548-549):
  1. gate (:539);
  2. `verified_registration` (:541-542: START and calendar);
  3. `_close_for` (:543);
  4. `_no_local_abort` (:545);
  5. the exact-W_L route (:546-547).
- `post_start_gate` checks only the PREREG-ACK (s1_slot.py:177-181).
- `Worker.intent` (s1_slot.py:243-262) does the restart pre-check, then SLOT-INTENT.
- In the journal (`_slot`, s1_journal.py:378-421), SLOT-INTENT is decided at step 5, in order: STOPPED gives
  LOST-RACE (:399-400), then the slot gate (:401-404). That comes after 4b repeat-attempt (:387-388). Step 6 then
  refuses at now >= E (:413-414).
- No step checks whether the slot's close is A5.1-eligible. An ACTIVE trial's worker therefore captures and seals a
  slot of d130 (the first post-deadline close), as the H3 reviewer observed. Codex ran the existing regression
  `test_sealed_last_close_reaches_its_timeout_through_a_later_checkpoint` (test_s1_a3_stop.py:552) at 9af5406: 1
  passed.
- `s1_seal.eligible_sessions` (s1_seal.py:340-343) is A5.1: `open_instant(d) >= start and _close(d) <= deadline(start)`,
  where `deadline` is the A5.1 aware instant (:330-337).

---

## D1. The rule (r2: Codex 62464458's controlling text, verbatim; replaces r1 D1)
**Controlling text:**

> For a NEW ordinary slot attempt, resolve its session from the already verified registered slot/calendar and START.
> If open_instant(session) >= START and close_instant(session) > registered_deadline, refuse at the existing F0.5
> step-5 post-START slot gate, with no row attributable solely to this refusal and no claim/capture/callback/QUALIFIED/
> new seal. For sessions opening before START, this added eligibility guard imposes no new refusal and grants no new
> authorization: every existing mode-specific identity, registration, ACK, opening/stage, state, integrity and E/W/D
> rule continues to apply. The exact W_L route predicate is unchanged.

**Aligned sub-points:**
1. **Domain and predicate.** The new refusal predicate is `(open_instant(session) >= START) AND
   (close_instant(session) > registered_deadline)`, on aware instants, never date-only comparisons.
   - `registered_deadline` is the A5.1 instant (`s1_seal.deadline`, s1_seal.py:330-337).
   - A close equal to the deadline is **not** refused.
   - Within the guarded domain (sessions opening at or after START), this is the complement of
     `eligible_sessions` membership. It is **not** unconditional membership applied to every scheduled invocation.
2. **Close identity, not a wall clock.** It is NOT `now <= deadline` and NOT `scheduled <= deadline`. No such cutoff
   is added.
3. **When the predicate holds:** the request is refused at the existing F0.5 step-5 post-START slot gate, with no row
   attributable solely to this refusal, and no claim, capture, receipt/process/provider callback, QUALIFIED or new
   seal.
4. **The exact W_L route predicate is unchanged.** Only `scheduled == W_L` (r4 G2.1(2)) routes, provider-free, at every
   clock. A later registered slot is never routed merely because `scheduled >= W_L`.
5. **A guarded-domain close at or before the deadline whose capture window runs past the deadline instant** keeps its
   existing A5.2 E/W and B1 D rules. An invocation after the deadline may still capture for such a close, within that
   close's original E/W. An existing permissible attempt is not rejected just because its report, QUALIFIED, seal or
   recovery occurs after W_L.
6. **Sessions opening before START** get no new refusal and no new authorization from this guard. Each mode path keeps
   exactly its existing guards:
   - **the pre-START opening worker** (`run_opening_checkpoint`, with `opening_gate`, s1_slot.py:184ff) is unchanged;
   - **a scheduled-mode (`run_checkpoint`) slot of a session opening before START**, for example an opening-close slot
     after the PREREG-ACK and before its E, keeps the ordinary path as it is today:
     - the gate;
     - `verified_registration`;
     - `_close_for`;
     - `_no_local_abort`;
     - `post_start_gate`'s PREREG-ACK check;
     - the journal's 4b/step-5/step-6 rules;
     - the `close >= start` bridge conditional, which gives `bridge = None` for such a close (s1_checkpoint.py:587-588).
   - Scheduled mode does **not** invoke `opening_gate`, and nothing here claims it does.
   - The bridge-producing true branch stays reachable for eligible post-START closes.

## D2. Ordering and the implementation boundary (Codex §3)
1. **Where it is enforced.** In the existing post-START SLOT-INTENT permission path: **F0.5 step 5, inside the deciding
   journal transaction**. That is the slot gate that `_slot` evaluates at s1_journal.py:401-404.
   - It uses the **already verified registered** START, calendar and slot identity: the `verified_registration`
     record and the registered slot -> close mapping.
   - It never uses an unbound or mutable plan read.
   - It never returns early before the integrity gate.
2. **Precedence is preserved:**
   - the gate's local-abort, CLOSED, INVALID, foreign-root and required integrity outcomes come first (F0.6, r4 G6);
   - 4b repeat-attempt (INVALID) and step-5 STOPPED -> LOST-RACE keep their order. The eligibility check sits after
     them, as part of the slot gate. **It adds no new early exit that changes them.**
3. **A refusal caused solely by eligibility adds no row.** An **independently established mandatory INVALID is never
   suppressed** to keep the promise of "no row".
4. **No bypass.** Direct entry points that open post-START attempts (any `Worker` constructed with the post-START gate,
   s1_checkpoint.py:548; the test-side direct use at test_s1_a3_wpend.py:283 is a control) cannot bypass the
   predicate.
5. **The generic opening gate is unchanged** (`opening_gate`, s1_slot.py:184ff).
6. **The pre-START exemption does not bypass D2.** A session opening before START is outside the new predicate only.
   Every other D2 ordering and precedence rule, and every existing mode-specific check, still applies (62464458).

## D3. Old history
- No row is deleted or reinterpreted. Old ineligible SLOT-INTENT, QUALIFIED or CREATED rows trigger **no new
  INVALID** just because they exist.
- Already-claimed attempts keep their existing completion, timeout, lock, LOST-RACE and stage-recovery rules.
- An already-CREATED ineligible seal stays **mandatory integrity evidence**. That covers row 305 and the
  damaged-ineligible-seal oracles (t11 case (v)). It is **never** a sampled stop or score input.
- An eligibility refusal implies **no automatic finalizer** and no new MISSED/TIMEOUT work.

## D4. Liveness limitation (Codex's strongest objection, in substance)
- Refusing the d130 worker **removes an existing trigger** for the earlier eligible stop. Today the d130 capture's
  post-capture finalizer (`_after_terminal`) completes the prior eligible close's timeout, which is exactly the
  behaviour test_s1_a3_stop.py:552 pins. The refusal may therefore **worsen operational liveness when finalizer
  dispatch is absent**.
- The recovery is the separately authorized `run_finalizer` path (`s1_checkpoint.py --finalize`, r4 G2.3).
  **Whether it is actually invoked is R-3**: still OPEN, and not proven by any function test.
- **Not claimed:** that capture and stop now share one global time cutoff. Capture stays governed by A5.2 E/W per
  close. Stop and timeout stay governed by A5.1. Nor is it claimed that a synthetic row-305 fixture proves ordinary
  capture reachability.

## D5. Acceptance cases and map rows (from 500; Codex §5)
**Evidence form (r2, Codex's wording).**
- **Changed behaviours** need a meaningful **old-fail / new-pass RED/GREEN**, on the pre-change head (9af5406 or the H5
  base) and the changed head.
- **Unchanged controls must remain passing.** No artificial failure is forced, and no passing old control is relabelled
  as a behavioural RED.
- **Missing-interface or setup incompatibilities, and predicate-only fixtures,** are labelled separately.
- **Targeted mutants keep named kill evidence.**
- Each row's evidence label is in its "evidence" column.

Spies cover the claim, the capture (`take_snapshot`), the receipt/process callbacks, the HTTP/provider, valuation, the
seal stage and every journal append. All mailboxes are synthetic. This is not a reason to rerun an unrelated giant suite
during the ruling.

The fixture is the t11 calendar unless stated otherwise:
- START 2026-10-26T13:30Z;
- deadline 2027-04-26T13:30Z;
- L = d129 2027-04-23, so W_L = 2027-04-26T12:00Z;
- d130 = 2027-04-26 (close 20:00Z);
- d131 = 2027-04-27.

| id | case | requirement | test to create | expected outcome | evidence | owner |
|---|---|---|---|---|---|---|
| 500 | PW-A1 | D1.1, D1.3, O-P3 | test_s1_a3_eligibility.py::test_post_deadline_close_refused[d130-first-slot,d131-post-deadline] | ACTIVE, otherwise authorized, guarded-domain session with close > deadline: SLOT-INTENT refused with the **pinned** reason (O-P3); no row, no claim, no capture, no receipt/process/provider callback, no QUALIFIED, no new seal. Also the paired control for row 513 | changed: RED/GREEN | H5 |
| 501 | PW-A2 | D1.1, D1.2 | test_s1_a3_eligibility.py::test_close_deadline_boundary[close-equals-deadline-not-refused,close-plus-1us-refused] | aware close instants: equality is not refused (the attempt proceeds); +1 µs is refused | end-to-end if a valid registration realizes it; otherwise **predicate/gate-level, "not a registered end-to-end trial"** (O-P2). Changed: RED/GREEN for +1 µs; control for equality | H5 |
| 502 | PW-A3 | D1.5 | test_s1_a3_eligibility.py::test_eligible_close_window_past_deadline_stays_under_e_w[slot-before-e-after-deadline-proceeds,slot-at-or-after-e-refused] | a close at or before the deadline whose window runs past the deadline instant: an invocation after the deadline but before E proceeds; at now >= E, A5.2 refusal unchanged | control; scope per O-P4 (end-to-end only with a valid registration, else gate-level, labelled) | H5 |
| 503 | PW-A4 | D1.4 | test_s1_a3_eligibility.py::test_route_predicate_unchanged[exact-w-l-routes,later-registered-slot-not-routed] | exact W_L takes the provider-free route at any clock; a registered slot after W_L is never routed: refused by the new predicate, with no route call (spy) | exact-W_L: control; later slot: changed RED/GREEN | H5 |
| 504 | PW-A5 | D1.5, D3 | test_s1_a3_eligibility.py::test_legacy_eligible_claim_keeps_rules[legacy-claim-r-after-w-l-before-d-qualifies,legacy-claim-timeout-at-d,legacy-w-l-claim-completes] | an explicitly **pre-existing (legacy)** eligible claim, an old W_L claim included, written as synthetic history (no current entry can open it): QUALIFIED with R after W_L and R < D appends; otherwise TIMEOUT at D; no eligibility refusal of a completion. No impossible current-entry fixture | control (synthetic/legacy history, labelled) | H5 |
| 505 | PW-A6 | D3 | test_s1_a3_eligibility.py::test_legacy_ineligible_history_kept[pending-ineligible-intent,created-ineligible-seal,no-new-invalid] | an old ineligible INTENT completes or times out under its existing rules; the CREATED ineligible seal stays required; no deletion and no synthetic INVALID from legacy rows | control (synthetic/legacy history) | H5 |
| 506 | PW-A7 | D1.6, D2.5 | test_s1_a3_eligibility.py::test_opening_mode_path_unchanged[opening-mode-captures-and-seals,opening-mode-keeps-opening-gate-guard] | **`run_opening_checkpoint` path only:** captures and seals the opening close as before; its own `opening_gate` guard still refuses a later opening slot once the opening is decided (E5.6); the new predicate is never consulted | control | H5 |
| 507 | PW-A8 | D2.2, D2.3, O-P3 | test_s1_a3_eligibility.py::test_precedence_preserved[local-abort,closed,invalid,foreign-root,integrity-violation,stopped-lost-race,repeat-attempt-invalid,mandatory-invalid-not-suppressed] | each keeps its existing outcome, including its required INVALID row. Eligibility never pre-empts or suppresses it, and the pinned eligibility reason never appears in place of the higher-precedence reason | control | H5 |
| 508 | PW-A9 | D3 | test_s1_a3_eligibility.py::test_row305_kept_as_synthetic_history[row305-history,damaged-ineligible-seal-invalid] | row 305 is labelled synthetic or historical; its CREATED d130 seal is required evidence, never sampled; deleting or corrupting it gives INVALID (stage-replaced) unchanged; the oracle is not weakened | control (synthetic history) | H5 |
| 509 | PW-A10 | D4, supersedes test_s1_a3_stop.py:552 | test_s1_a3_stop.py::test_d130_checkpoint_refused_then_finalizer_recovers_the_eligible_timeout[d130-refused-no-new-work,run-finalizer-recovers-timeout] | **explicitly supersedes** `test_sealed_last_close_reaches_its_timeout_through_a_later_checkpoint`, recorded in old -> new, not silently deleted: the d130 checkpoint refuses with no new work; then `run_finalizer` gives the TIMEOUT at the sealed last close. Scheduling that finalizer is R-3, not proven here | refusal: changed RED/GREEN; finalizer: control | H5 |
| 510 | PW-A11 | D2.4 | test_s1_a3_eligibility.py::test_direct_worker_entry_cannot_bypass[worker-post-start-gate-post-deadline-close] | a Worker built directly with the post-START gate for a guarded-domain session with close > deadline: refused, no row | changed: RED/GREEN | H5 |
| 511 | PW-A12 | D3 | test_s1_a3_eligibility.py::test_eligibility_refusal_triggers_no_finalizer[no-missed-timeout-rows,no-stop-decision] | after the refusal: zero finalizer/MISSED/TIMEOUT appends and no decide_stop call | changed: RED/GREEN (today the d130 path runs the post-capture finalizer) | H5 |
| 512 | PW-A13 | D1, D2 (mutants) | test_s1_a3_mutants.py targeted (H5 list)::eligibility[predicate-removed,ge-instead-of-gt,local-date-instead-of-instant,unconditional-membership-incl-pre-start,wallclock-instead-of-close-identity,checked-before-integrity-gate,applied-to-opening-gate,route-predicate-ge-w-l] | each mutant killed by its named test (killing test identity retained, A10.2): predicate-removed -> 500[d130-first-slot]; ge-instead-of-gt -> 501[close-equals-deadline-not-refused]; local-date-instead-of-instant -> 500[d130-first-slot] (d130 shares the deadline's date); **unconditional-membership-incl-pre-start -> 513[scheduled-opening-close-slot-no-new-refusal]**; wallclock-instead-of-close-identity -> 502[slot-before-e-after-deadline-proceeds]; checked-before-integrity-gate -> 507[integrity-violation]; applied-to-opening-gate -> 506[opening-mode-captures-and-seals]; route-predicate-ge-w-l -> 503[later-registered-slot-not-routed] | mutant kill evidence | H5 |
| 513 | PW-A14 | D1.6, D2.6 | test_s1_a3_eligibility.py::test_scheduled_mode_pre_start_session_unchanged[scheduled-opening-close-slot-no-new-refusal,scheduled-opening-close-slot-keeps-ordinary-guards,paired-post-deadline-control-refused] | an otherwise authorized scheduled-mode (`run_checkpoint`) slot of the opening close, after the PREREG-ACK and before its E: no new refusal, and it keeps its ordinary guards (for example, no PREREG-ACK refuses, and now >= E refuses), with `bridge = None`. **Paired**, same harness: a row-500 post-deadline session is refused with the pinned reason | pre-START: control; paired: changed RED/GREEN | H5 |

**Ownership.** Every row, 500-513, is owned by **H5** (or a clearly named adjacent hardening task), before the final
row-439 measurements. They are not mixed into H4's performance-only equivalence controls (Codex §4). Unrelated H4 work
need not wait.

**Counts (r2).**
- 14 new map rows (500-513), one acceptance case each (PW-A1..PW-A14).
- **42 parameterized instances**, counted mechanically from the bracketed ids; an unparameterized row counts as 1:
  - per row 500-513: 2, 2, 2, 2, 3, 3, 2, 8, 2, 2, 1, 2, 8, 3;
  - all owned by H5;
  - **34 behaviour/control instances** (rows 500-511 and 513) plus **8 targeted mutants** (row 512).
- Change from r1 (13 rows, 38 instances: 29 + 9):
  - +1 row (513, 3 instances);
  - row 504 goes from 2 to 3 instances;
  - row 506 goes from 1 to 2;
  - row 512 goes from 9 mutants to 8: two withdrawn as equivalent (O-P6) and one added (unconditional membership).
- These are proposed coverage counts, not executed tests.

---

## Open points
**Resolved by Codex 62464458** (accepted, recorded here):
- **O-P1 (ACCEPT the narrower applicability).** The new guard applies only to sessions with
  `open_instant >= registered START`. Within that domain it refuses when `close_instant > registered_deadline`.
  - A session opening before START is outside this guard, including when its registered slot is invoked through
    scheduled-mode `run_checkpoint`.
  - `run_opening_checkpoint` / `opening_gate` stay unchanged.
  - The `close >= start` bridge conditional (s1_checkpoint.py:587-588) is unaffected:
    - a close before START keeps `bridge = None`;
    - the bridge-producing true branch stays reachable for eligible post-START closes.
  - r1's "unreachable" claim is withdrawn.
  - This is not a blanket permission for arbitrary pre-START captures. Every existing mode-specific guard applies
    (D1.6, D2.6; rows 506 and 513).
- **O-P2 (ACCEPT, with a scope label).** If a valid registered START and calendar cannot realize close == deadline,
  row 501 uses a predicate/gate-level boundary fixture, labelled "not a registered end-to-end trial".
  - Production START validation is never relaxed to make a test pass.
  - Both the aware-instant equality and the +1 µs boundaries are kept.
  - Still not verified here: whether `write_plan` / prereg accept a START whose New York wall time equals a session
    close. The implementation decides the label from that fact.
- **O-P3 (ACCEPT).** The refusal reason, "close <YYYY-MM-DD> is not an A5.1-eligible session (Clarification 2): no
  post-START capture", is pinned in behavioural assertions for the newly guarded sessions (row 500).
  - It never masks a higher-precedence refusal or INVALID reason (row 507).
  - The exact byte text is fixed at implementation and quoted in the H5 review.
- **O-P4 (ACCEPT).** A distinct deadline-inside-the-window fixture (for example, a weekend deadline) is used for row 502,
  with the same scope and feasibility disclosure as O-P2.
  - End-to-end coverage is claimed only with a valid registration; otherwise the narrower component/gate scope is
    labelled.
  - An invocation after the deadline may stay eligible for a close before it, within that close's original E/W.
- **O-P5 (ACCEPT).** No readiness credit is taken from the removed d130 trigger. Actual finalizer dispatch is R-3
  evidence, not a function-test conclusion.

**New in r2:**
- **O-P6: two r1 mutants withdrawn as behaviourally equivalent** (disclosed, not silently dropped).
  - `open-ge-start-dropped`: under the r2 predicate, dropping `open >= START` refuses only sessions with close >
    deadline that open before START. For a valid calendar there are none, so no test can kill it. The relevant
    applicability mutant is `unconditional-membership-incl-pre-start`, killed by row 513.
  - `checked-outside-transaction`: the predicate is a pure function of the immutable verified registration (START,
    calendar, slot). Evaluating it before the transaction gives the same decision, so no behavioural test can kill it.
    The in-transaction placement (D2.1) is a code-review obligation at H5's exact-head review, not a mutation claim.
  - **Codex to confirm** both withdrawals.

**Disclosures:**
- Drafted by a Claude subagent for the controller.
- Codex saw the question and proposal before its review, so it was not blind.
- Shared code and documents form one evidence lineage.
- No guard was implemented. No test, suite, mutant, live, provider, scheduler or mailbox step was run for this draft.
- Code was read through `git show 9af5406`. No repo file was edited.
- Isolation and stage order are convention, not enforcement.
- Status: conditional support on the corrected design (Codex), and NO_CONSENSUS on this exact text pending a bounded
  hash check. Operational readiness: INSUFFICIENT_EVIDENCE.

## Process
1. Codex's bounded check of this exact draft.
2. Operator adoption. If declined, keep and disclose the current behaviour with its resource bound.
3. A byte-frozen copy in research/s1/docs, next to r4 and Clarification 1.
4. H5 implements rows 500-513 with RED/GREEN before the final row-439 measurement.

No registration, audit, START, RUN, scheduler or live step is authorized by this clarification.
