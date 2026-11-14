# S1 design v5 — Addendum 3 rev 5, Erratum 2, Clarification 3 (SEAL-ONCE) — draft revision 3 (S1-S6 only)

**Status: PROPOSAL.** This is a prospective clarification, to be adopted before the AUDIT-ACK. It is never retrofitted to
a registered trial. Nothing here is in force until it goes through the project's adoption process: Codex's bounded
check, then operator adoption, then a byte-frozen copy in research/s1/docs. The operator requested it on 2026-11-09.

**Relationship to r2.** Revision 3 answers the Codex review **371c137b-defb-4007-9117-0d2b244c6517** of r2 (sha256
b7f3344f52c99ef523db3ac41b2678df21cee4a2be397da3284980e0b89dae6b; submitted as aa3a2898). r1 and r2 are kept
unchanged.

**Codex records.** Verified by sha256, read in full, and treated as peer data. They are in
`.coordination/trading_app/s1_clarification3_r2_codex_review_20261109/`:
- REVIEW.txt 7aa328980ca2997af47a926daaf3bef9f2c38c45cac721b448656c9168cb4c20;
- assessment.json 623ac4b983f09c6e1ab0efb5fb10452eb095a6721c817906ba7693afe9f38b2e;
- schedule-bound-check.json 551972bd…, also read.

Codex's verdict: S1-S6 have conditional support and are **separable**; S7 is AMEND. Claude accepts all of it.

**The document is split, as Codex offered.**
- **This file is S1-S6 only.**
- The early-INTENT lower bound (r2's S7) moves to its own artifact: **Erratum 2 Clarification 4**
  (`s1_design_v5_addendum3_erratum2_clarification4_draft_r1.md`). It is reviewed, adopted and frozen independently.
- **Adopting this clarification does NOT accept S7, does NOT accept any lower time bound on SLOT-INTENT, and does NOT
  accept the conditional 7-per-close bound or the 910-tree envelope.** None of these is claimed here.

## Revision table (r2 -> r3)

| item | Codex disposition (371c137b) | what changed in r3 | sections |
|---|---|---|---|
| Split | Codex offered "split the two propositions into independently frozen/adopted artifacts" | S7 and its rows 540-544 are removed, and their substance moves to Clarification 4 r1. The revision says explicitly that adopting this clarification adopts neither S7 nor the conditional bound or envelope. | header, S4.2, counts, open points, process |
| S1-S6 | conditional_support (R2-CORE) | Text unchanged from r2, except: S4.2 now names Clarification 4 instead of claiming any bound; row 524's evidence label says Q = 8 is a reachable S1-only characterization (true here, because S7 is not adopted by this clarification). | S4.2, S6 row 524 |
| O-S7 / O-S8 / O-S9 | moved | Resolved in, and carried by, Clarification 4: O-S7 is the recording, cost, clock and scope corrections; O-S8 is the form of B (accepted); O-S9 is the δ <= 31 min geometry (accepted, conditional). | open points |
| Counts | recount | 12 rows / 12 cases / 47 instances (36 + 11 mutants), unchanged from r2's S1 part. The 5 S7 rows / 12 instances are removed. | counts |

---

## History: the r2 relationship, probe re-run and revision table (kept unchanged)

**Relationship to r1.** Revision 2 answers the Codex review **b4304771-adb9-4210-aa19-74d069125911** of r1 (sha256
9d31f04775b62199c3cda40577110a2451366decacfbe63a0774d2f0e45e2632). r1 is kept unchanged.

**Codex records.** Verified by sha256, read in full, and treated as peer data. They are in
`.coordination/trading_app/s1_clarification3_r1_codex_review_20261109/`:
- REVIEW.txt ca47942c34eb021ef8905fec2cb45cb754c80db7966a9a5dfcbc1262d314a243;
- assessment.json 7f9c8e3835c3156d5eaae55f74afb375c30f880b54bddedbccdbf489d3700ab6;
- probe_bounds.py 76b6ff956f8bf99829b57f792e5c5456d4c86be33120883ba2e58f38a9d9d981;
- counterexamples.json 7f2e285fb5d49453389de6f6e04d7c4ead0487986fe04f06e94816e4d82abf7e.

Claude accepts every point.

**Independent re-run of Codex's probe.** `probe_bounds.py` was re-run unchanged against a scratchpad copy of
`research/s1/*.py` at 8dfc1ab:
- run with `testenv python -I -B` through `runpy`;
- `s1_common.MAILBOX` redirected to a scratch path, and the probe touched no mailbox;
- exit code 0;
- the `counterexamples.json` it wrote is **byte-identical** to Codex's (7f2e285f…): Q=8 and Q=5.

This reproduces the **same probe** (real `s1_journal._slot`, modelled gate, fake in-memory rows). It is not the
integrated committed-fixture reproduction Codex requests. That is row 524.

## Revision table (r1 -> r2)

| item | Codex disposition | what changed in r2 | sections |
|---|---|---|---|
| O-S4 selection | ACCEPT, narrowly: primary rule | S1-S3 are rewritten on the **earlier-QUALIFIED predicate**: refuse a NEW attempt for slot s when the transaction's verified rows hold a committed SLOT-QUALIFIED for a slot q of the same close with scheduled(q) < scheduled(s). The DETERMINED gate is dropped. Codex's selection-neutrality proof and its limits are included. | S1, S1a, S2, S3 |
| O-S4 workload | REJECT as stated (SO-CH-EARLY, SO-CH-LATE) | The 7-per-close and 910 figures and the "only already-scheduled slots can claim" claim are **withdrawn**. S4 is replaced by Codex's accounting, Q(C) <= \|A0\| + \|B0\|: a finite accounting bound, not a capacity guarantee. The full ordinary schedule stays the conservative envelope. Both counterexamples are included, with their scope. | S4 |
| S7 (new) | — | A **separate proposal**, not part of the accepted predicate: an early-intent lower bound. With it, a bound is derived under S1 + S7 + an explicit dispatch assumption B. Without B there is no small bound. | S7 |
| O-S1 | ACCEPT exclusion | Sessions with open < START are excluded from this guard. The old row 530 becomes a passing unchanged control (now within row 526). Pre-START N and bytes are not bounded. | S1.4, S6 |
| O-S2 | ACCEPT | The order inside the slot gate is PREREG, then Clarification 2, then Clarification 3, after all earlier state, identity, integrity and repeat checks. | S2.2 |
| O-S3 | ACCEPT as a tradeoff | Lost observations are disclosed as a design tradeoff for the operator, not as harmless. | S5.1 |
| O-S5 | ACCEPT | Only the primary-predicate reason exists. | S1.3 |
| O-S6 | ACCEPT | The delayed-STOP-prefix effect is recorded as existing. Nothing claims that all output bytes are unchanged. | S5.2 |
| Acceptance matrix | rebuild | r1 rows 520-531 are **replaced in full** by a matrix covering Codex's nine required tests, with mutants bound to the new predicate. r1's row 520 and its `first-qualified-ignoring-earlier-terminal` expectation are removed. S7 rows are added separately. | S6, S7.6 |

## What it amends
- It changes **no byte** of the frozen documents in research/s1/docs:
  - Erratum 2 r4 (883f09be8471b9da7ee2c01c026ea90f9cec37515d79f3863e8c72085caa6d87);
  - Clarification 1 (2ccb8a287de533f08dcbf1e919afb04add8d5a60a0088dfd370649689009e10d);
  - Clarification 2 (ba16fdc876030d824818bed4e56abd1c9e4ff1c825c738d34dbf18fc50c07e6c), frozen at commit 8dfc1ab.
- It prospectively narrows the ordinary worker's permission to open a NEW slot attempt (S1). Any lower time bound on
  SLOT-INTENT is a separate proposal, Clarification 4, and is not part of this file.
- Its sha256 joins the registered bundle (A3.1).

**Purpose, stated plainly.** The aim is to reduce N_QUALIFIED, the number of QUALIFIED trees every gate pass must hash
(r4 G3.4), toward row-439 feasibility.
- **This is a policy change, not an optimization.** S1 removes captures that the protocol authorizes today.
- It is **not an M4 change**, and never described as one.
- S1 alone is selection-neutral, but it **proves no small worst-case bound** (S4).
- It proves nothing about timing. Row 439 stays **NOT READY**.

**Sources.**
- Codex **55c51f51** (row-439 rulings; records `s1_h4_row439_rulings_codex_20261109/`, REVIEW.txt ef7cfe61…).
- Codex **ad2cbf6e** (M3-PW).
- Codex **b4304771** (review of r1, above).
- Claude **fbc15d88-22cc-47c3-a45b-50ec96598022** (the r1 submission).
- Operator request, 2026-11-09.

**Code basis.** Read through `git show 8dfc1ab:<path>`, because H4 is uncommitted in the tree. Clarification 2 is
adopted but not yet implemented at 8dfc1ab.

| file | sha256 at 8dfc1ab |
|---|---|
| s1_checkpoint.py | 8ff18d9179bb340c736c152df44586ec0fb8dbb939224190cb9250c97fafd154 |
| s1_slot.py | 09dde1d6e53000b1080e7235a5dc5037caa6be2e051eb7b9aa0e25ac6ffc1448 |
| s1_journal.py | 27b7123ada7f86233a59b66d3ec8a9cf444eef3a5bc156945fa2f745a091904b |
| s1_seal.py | c46cac8f72bceda01f71c4bd06338d2f74113b693560677ad00115bbbe2d08c4 |
| s1_trial.py | c871c4dd8d30bd1965478c2a9050aa0152935c788331fdb25244f0fcd1883519 |
| s1_locks.py | 19679475cc42e7b2c52d3f3c534e1736af23f8d444b217ac1af767819dbfb09d |

**Current behaviour (8dfc1ab).**
- `run_checkpoint` (s1_checkpoint.py:525ff) runs the gate, the registration, `_close_for`, the local-abort check and the
  W_L route. It then opens a `Worker` with `post_start_gate` (:548-549), which checks only the PREREG-ACK
  (s1_slot.py:177-181).
- `Worker.intent` blocks only a second INTENT for the **same** slot (s1_slot.py:247-249; 4b, s1_journal.py:387-388).
- The journal step 5 order is STOPPED -> LOST-RACE (:399-400), then the slot gate (:401-404).
- Step 6 refuses SLOT-INTENT **only at now >= E** (:413-414). **There is no lower bound now >= s.**
- `_clock_refusal` runs only after a committed INTENT (s1_checkpoint.py:554-556, OQ-33). An early invocation that is
  not paused becomes FAILED. A worker that pauses after its committed INTENT and resumes inside its window can still
  capture and QUALIFY.
- The work lock is per slot (s1_locks.py:77ff) and never serializes different slots.
- A worker can pause between R and J. Step 6 checks `R < D`, not the commit clock (:415-416). A committed TIMEOUT makes a
  later J LOST-RACE (4c, E1.3).

---

## S1. The rule (primary predicate; Codex b4304771)
**Controlling text:**

> For a NEW ordinary post-START slot attempt for registered slot s of close C, after the existing higher-precedence
> checks, refuse at the existing F0.5 step-5 post-START slot gate, with no row attributable solely to this refusal and
> no claim/capture/receipt/process/provider callback/QUALIFIED/new seal, when the deciding transaction's verified
> journal rows contain a committed SLOT-QUALIFIED for a registered slot q of the SAME close C with scheduled(q) <
> scheduled(s). Compare registered scheduled instants only — not commit order, R, arrival order, string sorting, or
> which seal-stage file exists. Use only the rows re-read in that transaction and the verified calendar mapping.

1. **Mapping.** A slot subject is mapped to its close and scheduled instant through the verified registered calendar
   (`slot_of` / `day_for` / `schedule`).
   - A missing, invalid or unknown mapping, for s or for any committed QUALIFIED row being judged, keeps the existing
     fail-closed classification. It is **never** read as "no qualifying earlier slot".
2. **Damage to q's required evidence** keeps its existing integrity handling (F3, C5).
   - q is never ignored.
   - q's tree is never deleted so that captures can resume.
3. **Pinned refusal reason (primary predicate only):** "close <YYYY-MM-DD> has a committed QUALIFIED at an earlier
   registered slot <q>: no later slot attempt (Clarification 3)".
   - The exact bytes are fixed at implementation and quoted in the H5 review.
   - It never masks a higher-precedence outcome.
   - No separate "determined" reason exists.
4. **Domain (O-S1).** The guard applies only to sessions with `open_instant >= registered START`, as in
   Clarification 2.
   - Scheduled-mode slots of a session opening before START (the opening close) get no new refusal and no new
     authority from this guard.
   - `run_opening_checkpoint` / `opening_gate` keep their existing rules.
   - **Pre-START N_QUALIFIED and bytes are not bounded by this proposal.** They stay in row 439's total envelope.
5. **Not affected:**
   - the exact W_L route, which never opens an attempt (r4 G2.1);
   - every completion, timeout, MISSED or recovery row;
   - Clarification 2's post-deadline guard, which keeps precedence (S2.2).
6. **The DETERMINED gate (r1) is dropped.**
   - On a valid history it adds nothing. Every slot earlier than the selected q is already terminal, so it is not a
     NEW slot. The equal slot is already used, and 4b repeat-attempt / restart precedence decides it. Every later NEW
     slot has that earlier q.
   - No conflicting second predicate or reason is kept.

### S1a. Selection neutrality (Codex's proof) and its limits
**Proof.** While QUALIFIED(q) stands in the append-only valid history, a NEW attempt at a later scheduled slot s can
never become the first QUALIFIED in schedule order: q precedes it. That holds whether or not every slot before q has
terminalized. The close-level selection (B1.4 / E2.2 `first_qualified`) therefore never selects s, so refusing s
removes no selectable capture.

**What is NOT refused, and why.** Earlier slots stay attemptable. A slot earlier than q, still within its window, may
still QUALIFY and become the selected seal. A blanket "any QUALIFIED exists" guard would change the selection, which is
why it is rejected.

**Limits.** The proof shows only that a never-selectable later NEW capture is excluded under the fixed history and
selection rule. It does **not** show any of the following:
- equal integrity observation (S5.1);
- unchanged STOP-prefix timing (S5.2);
- liveness;
- any measured capacity;
- a small worst-case bound (S4).

## S2. Ordering and the implementation boundary
1. **Where.** F0.5 step 5, **inside the deciding SLOT-INTENT transaction**, on the rows re-read there, as part of the
   post-START slot gate that `_slot` evaluates (s1_journal.py:401-404).
   - It never uses `gv.rows`, a pre-transaction result, or a file.
2. **Order (O-S2).** The gate's local-abort, CLOSED, INVALID, foreign-root and integrity outcomes come first (F0.6,
   r4 G6). Then 4b repeat-attempt (INVALID) and step-5 STOPPED -> LOST-RACE. Then, inside the ordered slot gate:
   1. PREREG-ACK (existing);
   2. Clarification 2 post-deadline eligibility;
   3. this predicate.
   - Clarification 2's reason takes precedence.
   - No early return.
3. **A refusal caused solely by this predicate adds no row.** An independently established mandatory INVALID is
   **never** suppressed.
4. **No bypass.** Direct entry points opening ordinary attempts (any `Worker` built with the post-START gate,
   s1_checkpoint.py:548; the test-side use at test_s1_a3_wpend.py:283) cannot bypass the predicate.
5. **Unchanged:** the generic opening gate (s1_slot.py:184ff) and the exact W_L route predicate.
6. **No refusal-triggered finalizer.** A refusal implies no automatic finalizer and no new MISSED or TIMEOUT work.
   Recovery is the explicitly authorized paths: the next worker's post-terminal pass, the W_L route, or `--finalize`.

## S3. Already-open attempts and legacy history
- **Already-open attempts.** An attempt whose SLOT-INTENT committed before any earlier-slot QUALIFIED keeps every
  existing rule: P/R/J (QUALIFIED with R < D, or FAILED), TIMEOUT at D, LOST-RACE (E1.3), the work lock, late/ cleanup
  (E1.4) and stage recovery. **Only new SLOT-INTENTs are refused.**
- **Late QUALIFIED.** A late QUALIFIED for a close whose first QUALIFIED is earlier keeps existing B1.4 / E2.2
  handling. The selection is unchanged, the late tree is never selected, and the CREATED seal is unchanged.
- **Retained trees.** Old and non-selected QUALIFIED trees are never deleted or reinterpreted. Every retained tree,
  with all its members, stays required evidence under G3.4 / F3, and is hashed in every pass.
- **No new INVALID** arises from old rows.

## S4. Workload accounting (Codex b4304771; replaces r1 S4)
1. **Accounting**, for a close C with at least one QUALIFIED:
   - **q0** is the **first-committed** QUALIFIED of C, cut by journal sequence / transaction order. It is not cut by
     its R timestamp.
   - **A0** is the **distinct** slots whose SLOT-INTENT committed before q0's QUALIFIED row, **including q0's own
     slot**.
   - **B0** is the slots newly claimed after that row whose scheduled instant is earlier than scheduled(q0). Under S1,
     these are the only new claims that can still QUALIFY.
   - Every eventual QUALIFIED belongs to A0 or B0, so **Q(C) <= |A0| + |B0|**, with q0 counted once.
   - If C has no QUALIFIED, Q(C) = 0.
2. **This is a finite accounting bound, not a small capacity guarantee.**
   - B0 is not generally empty.
   - Under current rules A0 is not bounded by any ten-minute claim window, because SLOT-INTENT has no lower time bound.
   - A conditional per-close bound might become possible only if a separate lower-bound policy **and** a dispatch
     assumption B were both adopted. That is Clarification 4, a separate artifact. **No such bound is claimed or
     adopted here.**
3. **The conservative worst-case envelope stays the full ordinary schedule:** |schedule(C)| claimable slots per close.
   That is 22 for a weekday close followed by a weekday, more over weekends or holiday spans (70 Friday -> Monday in
   the t11 fixture), with the 08:00 W slot unable to QUALIFY (A5.3).
4. **Counterexamples** (Codex `probe_bounds.py`: real `s1_journal._slot` arbitration, the proposed predicate modelled
   as `slot_gate`, fake in-memory rows; every modelled capture inside its own window and every R < D):
   - **Probe 1 (early intent): Q = 8.**
     - Slots C+45, 47, 49, 51, 53, 55, 60 and 120 all commit INTENT at C+40, before any QUALIFIED.
     - Each resumes and QUALIFIES at s + 30 s.
     - Every arbitration APPENDs. The first slot already determines the close; every later one is a pre-existing claim
       (S3).
     - This falsifies r1's "7 under assumption A": prompt finalization cannot revoke committed claims.
   - **Probe 2 (earlier claims after the first QUALIFIED): Q = 5.**
     - q0 is slot C+55 (QUALIFIED at C+55m30s), the only claim before it.
     - At C+55m36s, slots C+47, 49, 51 and 53 claim. Each is earlier than q0 and before its own E. All four then
       QUALIFY.
     - "1 + claims before the first Q" gives 2, so that cut fails.
   - **Evidence scope.** These are executable protocol counterexamples. They are **not** a full valid-journal/tree
     integration test, not a worker-pause reproduction, not an implementation test and not a performance run.
     - Claude re-ran the same probe and got byte-identical output (header).
     - The integrated reproduction, with committed synthetic journal and capture fixtures and barriers, is row 524.
5. **Not bounded by S1:**
   - pre-START evidence (S1.4);
   - legacy trees;
   - in-flight and pre-claimed attempts (A0);
   - cumulative backup growth;
   - projection and trade sizes, journal length, contention, and dispatch latency.
6. **Row 439** must be re-measured in a separately predeclared, controller-committed campaign on final code. The 32
   existing runs and their NOT READY verdict are kept. Nothing here waives the cap, reduces hash coverage, or discards
   the old high-Q failure.

## S5. The cost
1. **Lost observations (O-S3): a design tradeoff for the operator, not a claim of harmlessness.**
   - Each refused later capture would have been an independent observation:
     - fence and bridge checks against all current seals (s1_checkpoint.py:566-570);
     - the semantic receipt (A1);
     - the process binding (B2);
     - capture consistency.
   - Fewer observations can miss transient changes: a backdated or edited row at or before a sealed close, or a
     receipt or binding change, made and reverted between the remaining observations.
   - Keeping all already-created evidence, and the later and final rechecks (A2.3), does **not** restore observations
     never made. F8.1 already disclaims unobserved changes.
   - No unreviewed monitoring mode or compensating capture policy is authorized.
2. **Liveness and STOP prefix (O-S6).**
   - Refused attempts do not run `_after_terminal` (s1_checkpoint.py:621-641). So these wait for the next authorized
     trigger (another worker's post-terminal pass, the W_L route or `--finalize`):
     - a crash between a determining J and the seal stage leaves `seal/<C>`;
     - a crash before `decide_stop` leaves a lots STOP;
     - `_finalize_others` / `_finalize_last_if_due` leave other closes' pending rows.
     Whether that trigger is dispatched is **R-3** (OPEN). No readiness credit is taken from the removed triggers.
   - The STOP **record** is a pure function of the rows (unchanged).
   - **A delayed STOP commit lets later-close rows enter the pre-STOP prefix.** That changes the sampled-history row
     hash (OQ-29), but not the stop close or cohort.
   - This effect exists today: it is reachable whenever later workers fail. It is recorded here. Nothing claims that
     all output bytes, or whole operational histories, are unchanged.
   - The timeout path for L is unaffected: its terminal is the W_L route, which never opens an attempt.

## S6. Acceptance matrix for S1 (rows from 520; replaces r1 rows 520-531 in full)
**Evidence form.**
- Changed behaviours need old-fail / new-pass RED/GREEN, on the H5 base and the changed head.
- Unchanged controls stay passing; no artificial RED.
- Setup incompatibilities and predicate-only fixtures are labelled separately.
- Mutants keep named kill evidence.
- Race cases use real processes and `BEGIN IMMEDIATE` arbitration with barriers.
- All mailboxes are synthetic.
- The t11 fixture is used: C = d0 2026-10-26 16:00 EDT (20:00Z).

| id | case | Codex test | test to create | expected outcome | evidence | owner |
|---|---|---|---|---|---|---|
| 520 | SO-A1 | (1) | test_s1_a3_seal_once.py::test_earlier_qualified_not_determined_refuses_later[earlier-slot-pending,earlier-slot-unclaimed-window-open] | q's QUALIFIED is committed while an earlier slot is pending or unclaimed (the close is NOT determined): a NEW attempt for a later slot is refused with the pinned reason; no row, no claim, no capture, no callback, no QUALIFIED, no seal | changed: RED/GREEN | H5 |
| 521 | SO-A2 | (2) | test_s1_a3_seal_once.py::test_earlier_slot_still_attemptable[earlier-attempt-allowed,earlier-qualified-becomes-selected-seal] | a later QUALIFIED exists; a slot earlier than it, still inside its window: its NEW attempt is allowed, can QUALIFY, and becomes the selected seal (B1.4) | control | H5 |
| 522 | SO-A3 | (3) | test_s1_a3_seal_once.py::test_transaction_barrier_around_q_commit[intent-before-q-commit-allowed,intent-after-q-commit-refused] | real processes with a barrier: a later-slot INTENT whose transaction precedes q's QUALIFIED commit is allowed (and is pre-claimed under S3); one whose transaction reads q's committed row is refused | first: control; second: changed RED/GREEN | H5 |
| 523 | SO-A4 | (4) | test_s1_a3_seal_once.py::test_preclaimed_later_completions[qualified-r-before-d,failed,timeout-at-d,lost-race-after-timeout] | pre-claimed later attempts complete after q / determination under their existing rules; no completion is refused; the selection is unchanged | control | H5 |
| 524 | SO-A5 | (5) | test_s1_a3_seal_once.py::test_counterexamples_integrated[probe1-early-intent-q8,probe2-post-first-q-earlier-claims-q5] | with committed synthetic journal and capture fixtures, worker-pause barriers and real arbitration, under S1 only: Q = 8 and Q = 5 respectively; every capture inside its own window with R < D | characterization: a reachable S1-only history under this clarification (S7 is not adopted here; see Clarification 4 for its interaction); integrated reproduction of b4304771's probes; shows S1 gives no small bound; not a capacity claim | H5 |
| 525 | SO-A6 | (6) | test_s1_a3_seal_once.py::test_direct_worker_entry_cannot_bypass[worker-post-start-gate-later-slot-after-q] | a Worker built directly with the post-START gate, for a later slot after q: refused, no row | changed: RED/GREEN | H5 |
| 526 | SO-A7 | (7) pre-START | test_s1_a3_seal_once.py::test_pre_start_paths_unchanged[scheduled-opening-close-slot-unchanged,opening-mode-unchanged,exact-w-l-route-unchanged] | a scheduled-mode slot of the opening close after an earlier opening-close QUALIFIED: no new refusal (O-S1); `run_opening_checkpoint` and the exact W_L route behave as before | control (replaces r1 row 530's refusal) | H5 |
| 527 | SO-A8 | (7) precedence | test_s1_a3_seal_once.py::test_precedence_preserved[local-abort,closed,invalid,foreign-root,integrity-violation,stopped-lost-race,repeat-attempt-invalid,mandatory-invalid-not-suppressed,prereg-missing-first,c2-post-deadline-reason-first] | each keeps its existing outcome and row; the Clarification 3 reason never replaces a higher-precedence one; a post-deadline close with an earlier QUALIFIED gets Clarification 2's reason | controls; changed RED/GREEN for the last parameter | H5 |
| 528 | SO-A9 | (8) | test_s1_a3_seal_once.py::test_retained_evidence_verified[multi-qualified-all-trees-hashed,damaged-non-selected-tree-invalid,damaged-q-tree-integrity-not-ignored,no-new-invalid-from-legacy] | every retained QUALIFIED tree is hashed each pass; damage to a non-selected tree, or to q, gets existing F3/C5 handling (q is never ignored to resume captures); legacy multi-QUALIFIED closes cause no new INVALID | control (synthetic/legacy history, labelled) | H5 |
| 529 | SO-A10 | (9) | test_s1_a3_seal_once.py::test_no_refusal_triggered_finalizer[refusal-runs-no-finalizer,next-close-worker-recovers,run-finalizer-recovers] | a refused attempt runs zero `_after_terminal` / finalizer / decide_stop; after a determining-worker crash, the next close's worker or `run_finalizer` creates `seal/<C>` and commits the same STOP record. Dispatch is R-3, not proven | refusal: changed RED/GREEN; recovery: control | H5 |
| 530 | SO-A11 | S1.1 mapping | test_s1_a3_seal_once.py::test_predicate_mapping[unknown-mapping-fails-closed,registered-instant-not-commit-order,other-close-qualified-ignored] | an unknown/invalid mapping keeps the fail-closed classification (never "no earlier q"); the comparison uses scheduled instants (a q committed later in the journal but scheduled earlier still refuses s); a QUALIFIED of another close never refuses | changed RED/GREEN for the first two; control for the third | H5 |
| 531 | SO-A12 | mutants | test_s1_a3_mutants.py targeted (H5 list)::seal_once[predicate-removed,any-qualified-blanket,determined-gate-instead,commit-order-instead-of-scheduled,other-close-qualified-counts,pre-read-instead-of-transaction-rows,refuses-completions-too,applied-to-pre-start-session,c2-order-swapped,checked-before-integrity-gate,unknown-mapping-treated-as-no-q] | each killed by a named test: predicate-removed -> 520[earlier-slot-pending]; any-qualified-blanket -> 521[earlier-attempt-allowed]; determined-gate-instead -> 520[earlier-slot-pending]; commit-order-instead-of-scheduled -> 530[registered-instant-not-commit-order]; other-close-qualified-counts -> 530[other-close-qualified-ignored]; pre-read-instead-of-transaction-rows -> 522[intent-after-q-commit-refused]; refuses-completions-too -> 523[qualified-r-before-d]; applied-to-pre-start-session -> 526[scheduled-opening-close-slot-unchanged]; c2-order-swapped -> 527[c2-post-deadline-reason-first]; checked-before-integrity-gate -> 527[integrity-violation]; unknown-mapping-treated-as-no-q -> 530[unknown-mapping-fails-closed] | mutant kill evidence | H5 |

**Ownership.** Rows 520-531 are owned by **H5**, or a clearly named adjacent semantic-hardening task. They are never in
H4. They come before any new row-439 campaign.

---

## Counts (r3; mechanical, from the bracketed ids; an unparameterized row counts as 1)
- **12 map rows (520-531) / 12 acceptance cases (SO-A1..SO-A12), 47 parameterized instances.**
  - Per row: 2, 2, 2, 4, 2, 1, 3, 10, 4, 3, 3, 11.
  - 36 behaviour/control/characterization instances plus 11 mutants (row 531).
  - All rows are owned by H5.
- **Change from r2:** r2's S7 rows 540-544 (5 rows, 12 instances) are removed from this file and carried by
  Clarification 4. S1-S6 counts are unchanged.
- These are proposed coverage counts, not executed tests.

---

## Open points (not decided here)
- **Moved to Clarification 4:**
  - O-S7: S7 recording, cost, clock and scope;
  - O-S8: the form of B, accepted;
  - O-S9: the δ <= 31 min geometry, accepted as conditional.
  - None is decided by adopting this file.
- **O-S3 tradeoff (accepted as disclosure).** The operator must explicitly accept the lost-observation tradeoff (S5.1)
  at adoption.
- **Row 524 and Clarification 4.**
  - Under this clarification alone, row 524's Q = 8 (early intent) is reachable through the current production entry
    points.
  - If Clarification 4 is adopted later, row 524 becomes a historical (pre-S7) or staged S1-only committed fixture. It
    is never presented as reachable through production entry points under S7.
  - No runtime disable-S7 bypass is introduced to make both hold. Clarification 4 records this interaction.
- **Disclosures:**
  - Drafted by a Claude subagent for the controller.
  - The Codex rulings were read after peer exposure, not blind.
  - Shared code and documents form one evidence lineage.
  - Codex's probe was re-run on a scratchpad copy at 8dfc1ab with byte-identical output. That is the same model, not
    an integrated reproduction (row 524).
  - No guard implementation, integrated test, benchmark, live, provider, scheduler or mailbox step was run. No repo
    file was edited.
  - Isolation and stage order are convention, not enforcement.
  - Status: conditional support (Codex 371c137b), NO_CONSENSUS on this exact text pending a bounded hash check.
    Row 439: NOT READY. Operational readiness: INSUFFICIENT_EVIDENCE.

## Process
1. Codex's bounded check of this exact draft (S1-S6 only).
2. Operator adoption of S1-S6, independent of Clarification 4. If declined, the current behaviour and the NOT READY
   result stand, disclosed.
3. A byte-frozen copy in research/s1/docs.
4. H5 (or a named adjacent task) implements rows 520-531 with RED/GREEN, together with Clarification 2 rows 500-513.
5. Then a new, separately predeclared, controller-committed row-439 campaign.

No registration, audit, START, RUN, scheduler or live step is authorized by this clarification.
