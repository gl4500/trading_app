# S1 design v5 — Addendum 3 rev 5, Erratum 2, Clarification 1 — draft revision 2

Revision 2 answers the Codex review f0140cd2 of r1 (sha256
15037a67ba9ff461e4da844d4f8f22b003b1423a56ad0a4c9d69268c2b8785be). r1 is kept unchanged.

The Codex records were verified by sha256 and read as peer data. They are in
`.coordination/trading_app/s1_erratum2_clarification1_r1_codex_review_20261108/`:
- REVIEW.txt (763bbd728768ac8f2d50345522dd5ee776a9e8069ac5b23d91120e67b0426eaa);
- assessment.json (1581a2680ea02456e4d20ab034f5eba3940cec7ef7f9112293395bd16f1b2554).

Codex's verdict was AMEND on O-C5 only. C1 to C5 are accepted, subject to the limits recorded below.

## Revision table (r1 -> r2)

| item | Codex disposition | what changed in r2 | sections |
|---|---|---|---|
| O-C5 typed absence | AMEND: replace O-C5 in full | O-C5 is replaced by Codex's text, verbatim. C5.1 is aligned with it: typed absence is a direct expected-member (or confirmed required-parent-path) FileNotFoundError on both passes. A failed enumeration or ambiguous lookup, even when raised as FileNotFoundError and repeated, refuses with no new INVALID. There is no listing-health precondition. F6.6 LOST precedence is kept. Row 496's controls are updated to match. | C5.1, row 496, Open points |
| Counts | follows from O-C5 | Row 496 goes from 8 to 10 parameters: one renamed, two added (listed under the map table). These are new parameters, not part of r1's 58. Rows and cases are unchanged (18/18). Instances go from 58 to **60** (H4 from 14 to 16). Combined with r4: 67 rows, 66 cases, **181** instances (was 179). | Counts |
| O-C1, O-C2, O-C4 limits | ACCEPT with stated limits | The limits are recorded as resolved points:<br>- **O-C1:** ties compare the persisted finite `created` values; read order and UUID are never tie-breakers.<br>- **O-C2:** rows 485 and 488 are labelled procedural-model tests; row 487 stays a residual, not detection.<br>- **O-C4:** the C4.5 and row-494 wording now follows C4.4: a TIMEOUT at D does not itself authorize or fabricate a seal. No parameter or row changes. | C4.5, rows 485/488/494, Open points |

**Probe outputs, for inspection.** Codex's review says Claude's scratch probe outputs were "not located". They are now
copied unchanged into `.coordination/trading_app/.sdd_s1/clar1_probe_outputs/`, byte-identical to the scratchpad
originals (verified with cmp):
- checks.json accc032372a6d816a8381dbb688d1c7de8f7166282170a10f4f3af2fdf5ca4aa (Codex's probes, run as a copy);
- claude_checks.json f3dc777f085fbd5d006b44278bd5913620447a38a7ef4781227fed9f142ce7c2 (Claude's probes);
- probes_codex_copy.py 129f1a72b0175e9baa41dbb2111748fb5a1f7b4e0bd778f535b16b35dd525a07;
- probes_claude.py 66a499555259e87acf6ba20ecc5d431852bb17aeae32ba7f07ea09967788313a.

---

**Status: PROPOSAL.** This is a prospective clarification, to be adopted before the AUDIT-ACK. It is never retrofitted to
a registered trial. Nothing here is in force until it goes through the project's adoption process: Codex's bounded
check, then operator adoption, then a byte-frozen copy in research/s1/docs.

**What it amends.**
- **It changes no byte of Erratum 2 r4.** r4 was adopted by the operator on 2026-11-08 (sha256
  883f09be8471b9da7ee2c01c026ea90f9cec37515d79f3863e8c72085caa6d87; progress.md:183). r4 stays frozen and unchanged.
- It is a separate, versioned clarification. Where it states a rule for a clause of r4 or of Erratum 1, this
  clarification governs prospectively:
  - r4 G1.4 / F7.5 "latest ACK";
  - r4 NVS-A8 and row 407;
  - r4 G1.4 snapshot causality;
  - r4 G2.1(6) / O8;
  - r4 G3.3 / G3.4 / M4-A9 / row 433;
  - Erratum 1 E3.4 (b03464669673927fdb057acad9b0dc3258b1f08692d55ec3b0cffd4550f6ca2f).
- Its sha256 joins the registered bundle (A3.1) next to r4's.

**Sources.**
- **Codex 6bfdc5cc** (FORUM-S1-A3-BLK3: rulings on hardening open points OP-1, OP-9, OP-10 and OP-27, plus the
  OP-2 flag). This is peer data. The controller **accepted every position** (progress.md:185).
- The records are in `.coordination/trading_app/s1_hardening_op_rulings_codex_20261108/`, with hashes verified:
  - REVIEW.txt 531e250f77c0bdd8e0333b80c5a0dc73a69619a3c1377acf2528afd6ccd22960;
  - assessment.json 1143f31e31a5e798a64e6f95ee00d8af2e2c9dabd886ad8122866abc99e35a9d;
  - claims.json bef106c0…;
  - challenges.json 496f8e9f…;
  - checks.json 228ef0ca…;
  - probes.py 230d21d7…;
  - manifest.json bb593171…;
  - opening-test-record.json 77aab802….
- The questions came from the hardening plan, `.superpowers/sdd/s1_plan_addendum3/hardening_plan.md` §4 (sha256
  30b6b588…): OP-1, OP-2, OP-9, OP-10 and OP-27.
- Earlier messages in the lineage: Codex 784e1e6e (r3 review), Codex be1215c9 (r1 review), and the Claude/Codex
  messages listed in r4's header.

**Code basis.** The citations are `file:line` in the current worktree: HEAD 56f8cb2 plus the uncommitted Task 14b
(`s1_trial.py` and `s1_common.py` modified). Hashes:

| file | sha256 |
|---|---|
| s1_trial.py | 34e0ae000ce4d8731c28ec44ef28cc650511e202e163530bce37ef973ac8f010 (WT, Task 14b) |
| s1_slot.py | 09dde1d6e53000b1080e7235a5dc5037caa6be2e051eb7b9aa0e25ac6ffc1448 |
| s1_checkpoint.py | c982a4890bdce2981f65aa806fc02eea6cdef1f9a0c5d058764f6ac583827d92 |
| s1_common.py | 912c012867712205d8478d68e25a9b67ebe278936be02299f6cfdd3cc0cd661d (WT, Task 14b) |
| s1_seal.py | 9c7fd0597cc0327e51d9aa7327d1d1436b4b4ce1468d8f57d304a61614837278 |
| s1_run.py | 35aa486147ff107d28fef6b87ac56a84a0fe516d86c9e13753be07bed7acf183 |
| s1_journal.py | f83913f22ace59cdf8a7ab022566ff6df4d2fbbd4e564c6afb27fbc3465a1afb |

The citations describe the current behaviour. They are not evidence that any requirement here is met.

---

## C0. Independent reproduction of Codex's counterexamples (Step 1, as Codex requested)
**Method.**
- Everything ran against a scratchpad copy of `research/s1/*.py` and `docs/` (the current worktree, hashes above):
  `scratchpad\clar1\tree\research\s1`. Never against the live worktree, and never against any real mailbox.
- `s1_common.MAILBOX` was redirected to a scratch path. The probe confirmed that it was never created.
- Interpreter: `.coordination/trading_app/testenv/Scripts/python.exe -I -B` only.
- Codex's `probes.py` was run as a copy with exactly four mechanical edits: ROOT pointed at the copy, OUT at
  scratchpad\clar1\out, the two `.superpowers` manifest entries removed, and a fixed "head" string instead of `git
  rev-parse`. Its probe bodies are byte-identical to Codex's.
- Claude's own minimal probes are in `probes_claude.py`. They are built differently from Codex's, as described below.
- Outputs: `scratchpad\clar1\out\checks.json` (Codex's probes) and `scratchpad\clar1\out\claude_checks.json`.
- These are synthetic, private-function or contract probes. They are **not end-to-end lifecycle tests**, and they
  exercise none of the H-task fixes.

| OP | Codex probe (copy) | Claude's independent probe (own construction) | holds? |
|---|---|---|---|
| OP-9 | `slot_problems` with `qualified_tree` patched to raise PermissionError: an identical F3 problem string on two calls | A real on-disk QUALIFIED tree, a real 2-session calendar and a real slot (2026-10-26T20:45Z). PermissionError injected one layer lower, at `s1_common.sha256_file`, for `backup.sqlite3` only. Healthy: `[]`. With the error: the same F3 problem on both reads, and **`evidence_check`'s confirm-on-re-read reaches the INVALID call** (`evidence_violation`, s1_slot.py:826-831), although the member's bytes are unchanged | **HOLDS**: an OSError on a QUALIFIED member gives INVALID today |
| OP-10 | `_close` with SCORE(5), ACQUIRE(6), CLOSE(7): prev=SCORE accepted, prev=ACQUIRE refused | Same verdicts, and the internal predecessor order `_close` builds is shown: `[A, O, R, P, Q6, S5]`. That is CHAIN rank, which puts SCORE(5) after ACQUIRE(6) (s1_trial.py:202-203). Normal-chain control: ACQUIRE(5), SCORE(6), CLOSE(7) prev=SCORE is accepted | **HOLDS** |
| OP-27 | `_close` accepts a CLOSE SCORED whose evidence is `0…0` | Goes through `trials()` (the open-trial derivation), not only `_close`. The evidence is a hex-valid sha256 of a *different* record (true 66acc977…, supplied aca9151e…). Result: `tr.closed` is that CLOSE, so the trial is closed. (In this synthetic NVS-shaped chain the SCORE-ACK also raises "no S1-ACQUIRE-ACK predecessor" as an escalation problem of the closed trial, because the H2 NVS parser does not exist yet; closure still applies) | **HOLDS** |
| OP-2 | Arithmetic: field 10, ACK 11, publication 12 | Event order with a real exclusive publication. `written_utc`=10 is put in the report body. The ACK record (created 11) exists *before* the file. The report is published at 12. The in-report check `ACK.created > written_utc` **passes**; the report did **not** exist when the ACK was created; publication-before-ACK is **false** | **HOLDS** (a contract counterexample; there is no product implementation yet) |

There is no disagreement with Codex on any of the four.

---

## C1. OP-10: "latest ACK before CLOSE" is decided by creation chronology (amends the reading of r4 G1.4/O3 and F7.5; E3.4 monotonicity kept)
1. **Rule.** For a candidate S1-CLOSE-ACK X, the prev X must name is the **latest** of the candidate predecessors:
   - official (E4.1);
   - same trial_id;
   - same bundle as the AUDIT-ACK;
   - individually chain-valid: F7.1 / F6.1 and r4 G1.4's mailbox-level shapes;
   - **created strictly before X**.
   "Latest" is decided by **creation chronology** (the mailbox `created` value), **not by stage rank** (`CHAIN` order).
   Today, s1_trial.py:202-203 takes `before[-1]` in CHAIN order. That reading is retired prospectively.
2. **Ambiguity or an invalid chain refuses and escalates.** In each case X does not close the trial: refuse and
   escalate.
   - Two or more candidates tie for the latest `created`, so the chronology is ambiguous.
   - A candidate's chronology cannot be established.
   - A candidate created before X is not chain-valid.
   S1 never silently picks a convenient predecessor.
3. **Monotonicity is kept (E3.4).** The first valid CLOSE, in mailbox order, is the trial's closure, permanently.
   ACKs or CLOSEs created after that closure never re-open it. They stay escalation problems of the closed trial only
   (s1_trial.py:219-223 today).
4. **Normal chains are unchanged.** In a valid normal chain every ACK is created after its F7.1 predecessor, so
   creation chronology and chain rank agree. This is a derivation; Claude's normal-chain control (C0, OP-10) is
   consistent with it. The chain-ACK `prev` rules (F7.1, PRED, r4 G1.4 mailbox-level shapes) are unchanged. C1 governs
   only which ACK a CLOSE's `prev` must name.
5. **Integrated NVS fork (the case H2 must cover once its NVS parser exists).**
   - The history: an NVS SCORE-ACK (prev = PREREG), then a later mistaken S1-ACQUIRE-ACK (prev = PREREG, created after
     the SCORE-ACK), then a stale CLOSE whose prev names the SCORE-ACK.
   - **That CLOSE refuses**, because the latest predecessor before it is the ACQUIRE-ACK.
   - The trial stays open, and the r4 G1.6a/O3 refuse-and-escalate rule governs it.
   - **S1 takes no automatic action**: no BLOCKED, no blocked.json, no INVALID and no withdrawal.
6. **WITHDRAWN.**
   - A WITHDRAWN CLOSE with prev = the latest ACK (the late ACQUIRE-ACK) closes the trial in S1's reading only as an
     actually issued official CLOSE (E3.4).
   - Its issuance requires **genuine operator-withdrawal evidence**: the operator's explicit withdrawal message, with
     `evidence_sha256 = close_evidence("WITHDRAWN", withdrawal=<message>)` (s1_trial.py:870ff). Codex checks this at
     issuance.
   - Tests use a fixture-only WITHDRAWN. No product withdrawal is made or authorized.
7. **Not proven by the current probe.** The `_close` probe reproduces the bad case. It is not proof of an
   end-to-end NVS branch, which does not exist before H2.
8. **Recorded explicitly.** The chronology reading is recorded here and in H2. It is not a silent refactor.
9. **Related (unchanged).** OP-25: the NVS predecessor rule reads the deciding transaction's official parsed ACKs,
   keeping the trial and chain checks. A gate snapshot is not authoritative for absence. Codex confirmed this
   direction, and the controller had already adopted it.

## C2. OP-27: CLOSE SCORED evidence is checked at issuance; runtime CLOSE is E3.4 (replaces r4 NVS-A8's second sentence and splits row 407)
1. **Replacement text for NVS-A8, Codex's preferred text, verbatim.** This replaces "A wrong evidence hash leaves it
   open" in r4 NVS-A8, prospectively:

   > Before issuing CLOSE SCORED, Codex verifies the committed score record against its own trial/root and binds its
   > actual score/s1.json hash. An absent/mismatching expected hash prevents issuance: no CLOSE row is sent, so the
   > trial stays open. S1 validates an actually issued historical CLOSE under E3.4/F7.5 grammar, role/key, prev,
   > creation/bundle rules and does not reopen it from filesystem evidence.

   NVS-A8's other sentences are kept unchanged: "CLOSE SCORED on sha256(score/s1.json) closes the trial. S1 writes no
   CLOSE, and no new trial appears."
2. **Row 407 is split** into rows 485 (issuer validation and no-send) and 486 (runtime lifecycle). Row 487 is a
   residual characterization. All three have zero live mailbox writes in tests: only a synthetic or scratch mailbox,
   and a spy proving no write to the coordination mailbox.
   - **Issuer validation / no-send (485).**
     - The issuance-side check computes the expected hash from the committed score record of the trial's own root,
       with `close_evidence("SCORED", score_record=…)`.
     - If the record is absent or the hash mismatches: no CLOSE line is produced and nothing is sent.
     - If it matches: exactly that line is produced.
     - In tests, "issuer validation" is a test-side, procedural-model simulation (resolved: O-C2, Open points).
   - **Runtime lifecycle (486).** An actually issued valid CLOSE closes the trial for every caller, every root and
     the rootless lookup (E3.4 r3, F6.3). S1 never recomputes or rejects a historical CLOSE from filesystem evidence,
     and never re-opens it.
   - **Trusted-issuer residual (487, disclosed).** A hex-valid but **wrong** evidence hash on an official, otherwise
     valid CLOSE **closes the trial at runtime today**, and will continue to (C0, OP-27).
     - This is the **trusted-issuer residual** (ruling 6). It is **NOT runtime detection**, and row 487 is labelled a
       residual characterization, never a refusal test.
     - Runtime evidence verification would be a different design. It would need its own adopted rootless /
       multi-root / monotonicity contract. It is not proposed here.
3. **Sign-off.** H2's row-407 sign-off (now rows 485-487) stays held until this clarification is adopted.

## C3. OP-2: in-report `written_utc` is only a lower bound; the issuer reads the published report first (replaces the G1.4 causality bullet "created strictly after the final snapshot report was written" as an S1-provable property)
1. **The `written_utc` field.** The final snapshot report gets a `written_utc` field, sampled immediately before
   publication (controller ruling on OP-2, progress.md:184).
   - It is a **lower bound only**. A report cannot contain its own already-completed publication time.
   - `SCORE-ACK.created > written_utc` does not prove that `final_snapshot/report.json` existed before the SCORE-ACK.
     The counterexample is C0 OP-2: field 10, ACK 11, publication 12.
2. **The issuer's obligation.** Before issuing the SCORE-ACK, the issuer (Codex) must read the **final, published**
   `final_snapshot/report.json` and confirm it is the same hash the SCORE-ACK binds (`final_snapshot_sha256`).
   - If the report is absent or has a different hash, no SCORE-ACK is issued.
   - This is how publication-before-ACK is ensured.
3. **The S1 in-report check, labelled honestly.** S1's runtime check `SCORE-ACK.created > written_utc` is named and
   reported as a **lower-bound check**.
   - It is kept in addition to the existing OQ-16 binding (`_bound_snapshot_check`, s1_run.py:831-854) and the other
     r4 G1.4 causality conditions.
   - **No test may claim to cover the full G1.4 publication-before-ACK causality property.** Test names and
     docstrings say "lower bound".
4. **Stronger proof would need its own clarification.** If S1 must independently prove strict publication causality,
   a post-publication witness has to be specified and bound in a separate, adopted clarification. None is specified
   here.

## C4. OP-1: the provider-free, clock-callable opening-finalizer helper (r4 G2.1(6)/O8; Codex's conditions, in substance)
**Background.** Retiring `s1_checkpoint.finalize_close` (:337-366) must not remove the crashed-opening-worker recovery
of Task 7 concern 7 / Task 10. That wrapper's opening branch runs `_opening_stage` via `_apply_opening` (:352-361,
:369-378). `run_finalizer` does not replace it: it requires `verified_registration` (:447), and `_finalize_others`
skips pre-START closes (`d < start_day`, :409). Codex ran the four existing scoped opening-finalizer tests, which pass
(opening-test-record.json): `test_s1_a3_prestart.py::test_a_crashed_opening_worker_times_out_at_d_and_the_opening_is_sealed`
(:534) and `::test_the_finalizer_command_turns_an_opening_stage_error_into_a_refusal` (:805).

**Contract.** H3 replaces the opening branch with a helper (a callable for an existing operation) that:
1. Uses **the same clock callable, by identity,** through the gate, every journal transaction and the opening stage.
   It never uses an invocation-start lambda (`lambda: t`).
2. Binds the open trial / AUDIT-ACK and the registered opening identity through the **existing pre-START gate**.
3. Enforces local-abort, INVALID, CLOSED and integrity precedence (r4 G6 and the existing gate).
4. Only finalizes **existing** attempts and deadlines (MISSED at E, TIMEOUT at D) and materializes the
   **already-authorized** opening stage.
   - No Worker, no SLOT-INTENT, no process, receipt, snapshot or provider callback, no new capture and no synthetic
     seal.
   - No qualifying capture means **no fabricated opening and no START**.
5. Keeps idempotence, first-QUALIFIED ordering, the deadline boundaries and the exception-to-refusal behaviour. That
   includes the case where the **final opening worker crashed and there is no later slot**: it times out at D.
   - **C4.4 governs this case (r2, O-C4).** A TIMEOUT at D does not by itself authorize or fabricate an opening seal.
   - The seal follows only when an actual eligible committed capture permits the already-authorized `opening` stage.
     That is the first QUALIFIED opening slot, with every earlier slot terminal.
   - With no qualifying capture there is no opening and no START.
6. Is accepted as a replacement callable/helper for an existing operation only. It is **not** autonomous scheduling and
   not a new operational authorization.

**No new CLI mode is exposed.**
- `s1_checkpoint.parse_mode` keeps exactly its four modes (scheduled, opening, final-snapshot, finalize;
  s1_checkpoint.py:996-1014), and `--finalize` is **not** extended to the pre-START opening close.
- Exposing a new mode, or extending `--finalize`, would need its own exact mode contract and authorization in a
  separate clarification before anyone could claim it implements r4.

**Alternative (a)** (delete the behaviour because today's helper has no CLI caller) is **rejected**, per Codex.

## C5. OP-9: classification of QUALIFIED-tree read failures across all consumers (a disclosed exception to G3.3 / M4-A9 baseline equivalence)
1. **Rule, for every read of a QUALIFIED tree member** (report, resolution, capture files; F3, OQ-32):
   - **Generic OSError / PermissionError** (anything other than a confirmed typed absence) proves unreadability, not
     altered bytes. Persistent repetition does not turn it into corruption.
     - It **refuses that invocation**, with no requested work and **no new INVALID** based on that I/O observation.
     - A later healthy invocation re-evaluates normally.
   - **Confirmed typed absence (r2, O-C5).**
     - It is a `FileNotFoundError` from an attempt to open or read the **specific required member** (or a confirmed
       missing required parent path), on **both** passes, after the existing root and identity classifications are
       preserved. That is the applicable integrity violation: a required file missing, F3.
     - A failed directory enumeration, a PermissionError, another generic OSError, or an ambiguous member-lookup
       failure is **never** confirmed absence, even when it is raised as `FileNotFoundError` or repeated. It refuses,
       with no new INVALID.
     - If the I/O API cannot distinguish where a failure came from, the ambiguity is kept as a refusal. No evidence of
       absence is invented.
   - **Confirmed changed bytes**, or **confirmed readable-but-malformed bytes** (report or resolution unparseable): the
     applicable integrity violation.
   - **The confirming pass:** a second direct expected-member `FileNotFoundError` is the only typed-absence exception.
     Any other confirming-pass I/O error **cannot confirm** a violation, and that invocation refuses with no INVALID.
   - There is **no** global listing-health precondition and no additional operational probe.
   - **Root and identity failures** keep their earlier classifications (F6.6 LOST, F6.2, bundle, and so on).
   - **An unrelated mandatory INVALID** keeps its precedence: an I/O refusal never masks it.
2. **Consumers covered** (all of them, not only `slot_problems`):
   - `slot_problems` (s1_slot.py:644-651, today `except (OSError, ValueError): ok = False`);
   - `_resolution_evidence` (s1_slot.py:595-606, today OSError becomes QualifiedEvidence). Its callers are:
     - `run_seal_stage` (s1_slot.py:554);
     - the OQ-14 seal recomputation in `evidence_problems` (s1_slot.py:716-720, today `except (OSError, …): ok = False`);
     - `sampled_seals` / `stop_record` (s1_seal.py:531, :573);
     - `_opening_stage` (s1_checkpoint.py:734, with the QualifiedEvidence handlers at :355 and :876);
     - `decide_stop` (s1_seal.py:662, already a refusal).
   - `Worker.complete`'s own tree hash (s1_slot.py:289) is the producer's computation, not a consumer judgement. It is
     out of scope, and its existing failure path is unchanged.
3. **A disclosed exception to G3.3 / M4-A9 baseline equivalence.** M4-A9 (row 438) compares problem lists with the
   pre-change behaviour. For an OSError on a QUALIFIED member, the expected outcome changes on purpose, from INVALID to
   refusal.
   - That change gets its **own behavioural RED**, under H4.
   - It is excluded from the baseline-equivalence control.
   - The existing cache and per-pass invariants (G3.1-G3.5) are untouched.
   - This is not "M4 preserved classifications".
4. **Row 433 controls** are made explicit in row 496, listed in G4 below.

---

## Acceptance cases (CL-A1..CL-A18) and map rows (from 480)
Proposed test files: `test_s1_a3_nvs.py` and `test_s1_a3_close.py` (H2), `test_s1_a3_wpend.py` (H3) and
`test_s1_a3_m4_pass.py` (H4). Every mailbox is a synthetic or scratch file. Spies prove zero writes to the coordination
mailbox. RED/GREEN is recorded old-fail / new-pass, with fixture incompatibilities separated.

| id | case | requirement | test to create | expected outcome | owner |
|---|---|---|---|---|---|
| 480 | CL-A1 | C1.1, C1.5 | test_s1_a3_close.py::test_nvs_fork_stale_close_refused[stale-prev-score-refused,no-automatic-blocked-invalid-withdrawal] | NVS SCORE-ACK, later mistaken ACQUIRE-ACK, then CLOSE prev=SCORE: refused; trial open; refuse+escalate; no blocked.json, no INVALID row, no withdrawal | H2 |
| 481 | CL-A2 | C1.6 | test_s1_a3_close.py::test_nvs_fork_withdrawn_names_latest_acquire | fixture WITHDRAWN with prev = late ACQUIRE-ACK and evidence = close_evidence("WITHDRAWN", operator message) closes; no product withdrawal | H2 |
| 482 | CL-A3 | C1.4 | test_s1_a3_close.py::test_normal_chain_close_unchanged[scored-after-score,invalid-after-prereg,withdrawn-after-acquire] | same verdicts as the rank reading (chronology = rank) | H2 |
| 483 | CL-A4 | C1.2 | test_s1_a3_close.py::test_ambiguous_or_invalid_predecessor_refuses[created-tie,invalid-chain-candidate] | the CLOSE does not close; refuse + escalate; no predecessor chosen | H2 |
| 484 | CL-A5 | C1.3 | test_s1_a3_close.py::test_first_valid_close_monotone[ack-after-closure,second-close-after-closure] | the closure stands; later ACK/CLOSE is an escalation problem only; never re-opens | H2 |
| 485 | CL-A6 | C2.2 issuer | test_s1_a3_close.py::test_scored_close_issuer_validation_no_send[record-absent,hash-mismatch,hash-match] | **procedural-model test only (O-C2):** exercises the trial/root committed-record identity and the actual byte hash; absent/mismatch: no CLOSE line produced, nothing sent; match: exactly that line, bound to the actual hash; zero coordination-mailbox writes. It does not establish an enforced production issuer guard or prove future Codex compliance | H2 |
| 486 | CL-A7 | C2.2 runtime, E3.4 | test_s1_a3_close.py::test_issued_close_runtime_lifecycle[closes-every-root,rootless-lookup,no-reopen-from-filesystem] | issued valid CLOSE closes for every caller/root; filesystem changes never re-open | H2 |
| 487 | CL-A8 | C2.2 residual | test_s1_a3_close.py::test_trusted_issuer_residual_wrong_hash_closes | **residual characterization (NOT runtime detection):** an official CLOSE with a hex-valid wrong evidence hash closes | H2 |
| 488 | CL-A9 | C3.2 | test_s1_a3_nvs.py::test_score_ack_issuer_reads_published_report[report-absent,report-hash-differs,report-same-hash] | **procedural-model test only (O-C2):** absent/differs: no SCORE-ACK issued; same hash: issued; zero coordination-mailbox writes. Not a production issuer guard; actual issuance still requires the real published-report read before the send | H2 |
| 489 | CL-A10 | C3.3 | test_s1_a3_nvs.py::test_score_ack_written_utc_lower_bound[created-le-written,created-gt-written] | <=: refused, no row; >: passes the lower-bound check; named and labelled "lower bound", never "causality" | H2 |
| 490 | CL-A11 | C3.1 | test_s1_a3_nvs.py::test_lower_bound_does_not_prove_publication_order | barrier ordering field 10 / ACK 11 / publication 12: the lower bound passes, and the test asserts the property is NOT proven (characterization) | H2 |
| 491 | CL-A12 | C4.1 | test_s1_a3_prestart.py::test_opening_finalizer_helper_same_clock_callable | the identical callable reaches the gate, each journal transaction and the opening stage; no fixed lambda; advancing clock observed | H3 |
| 492 | CL-A13 | C4.2, C4.3 | test_s1_a3_prestart.py::test_opening_finalizer_helper_precedence[local-abort,invalid,closed,no-open-trial,integrity-violation] | existing refusal/INVALID outcome; zero finalizer work | H3 |
| 493 | CL-A14 | C4.4 | test_s1_a3_prestart.py::test_opening_finalizer_helper_no_new_work[no-worker,no-slot-intent,no-process-callback,no-receipt-callback,no-snapshot,no-provider,no-capture,no-synthetic-seal,no-qualifying-capture-no-opening] | spies at zero; no opening/START fabricated | H3 |
| 494 | CL-A15 | C4.5 (governed by C4.4) | test_s1_a3_prestart.py::test_opening_finalizer_helper_preserves_recovery[crashed-last-opening-worker,idempotent-repeat,first-qualified-order,d-minus-1us,stage-error-to-refusal] | crashed last opening worker: TIMEOUT at D, and an opening seal only from an actual eligible committed capture (none: no seal, no opening, no START); repeats add no row; order and boundaries kept; errors refuse (migrates :534 and :805). Establishes preserved callable behaviour only, not operational reachability (O-C4) | H3 |
| 495 | CL-A16 | C4 no CLI | test_s1_a3_wpend.py::test_no_new_cli_mode | parse_mode accepts exactly the four existing modes; --finalize does not finalize a pre-START close | H3 |
| 496 | CL-A17 | C5.1, C5.4 (row-433 controls) | test_s1_a3_m4_pass.py::test_qualified_member_read_classification[transient-permission,persistent-permission,first-bad-confirm-generic-io,direct-missing-member-both-passes,confirmed-missing-parent-path,failed-listing-or-lookup-as-filenotfound-both-passes,changed-confirmed,malformed-confirmed,unrelated-mandatory-invalid-precedence,later-healthy-reevaluates] | generic I/O (PermissionError/OSError): refusal, no new INVALID, no requested work; a confirming-pass generic I/O error cannot confirm; both direct missing-member observations (or a confirmed missing required parent path): the existing F3 classification; a known failed listing/lookup presented as FileNotFoundError on both passes: refusal, no new INVALID, no requested work; changed/malformed confirmed: the F3 violation; an unrelated mandatory INVALID still wins; a later healthy run is judged normally | H4 |
| 497 | CL-A18 | C5.2 | test_s1_a3_m4_pass.py::test_read_classification_all_consumers[slot-problems,seal-recompute,run-seal-stage,sampled-seals,opening-stage,decide-stop] | the same C5.1 rule at every consumer (PermissionError: refusal, no INVALID; confirmed changed: violation) | H4 |

**Ownership updates (hardening plan §1).**
- **H2** gains rows 480-490 (CL-A1..A11).
  - Row 407's runtime-refusal expectation is superseded by rows 485-487 (C2). Its sign-off stays held until this
    clarification is adopted.
  - The OP-10/OP-2 parts of H2 wait for the adoption (progress.md:185).
- **H3** gains rows 491-495 (CL-A12..A16). H3 retires the wrappers only with the C4 helper in place.
- **H4** gains rows 496-497 (CL-A17..A18).
  - Row 433 (M4-A4) keeps its listing and read cases. For QUALIFIED members, its "refusal or integrity handling"
    becomes the C5 rule, made explicit by row 496.
  - Row 438 (M4-A9) excludes the C5 change from baseline equivalence, with its own RED.
- **H1 and H5 are unchanged.**

**Counts (r2).**
- 18 new map rows (480-497), one acceptance case each (CL-A1..CL-A18). Rows and cases are unchanged from r1.
- **60 parameterized instances**, counted mechanically from the bracketed ids; an unparameterized row counts as 1:
  - per row 480-497: 2, 1, 3, 2, 2, 3, 3, 1, 3, 2, 1, 1, 5, 9, 5, 1, 10, 6;
  - H2: 23, H3: 21, H4: 16.
- **Change from r1 (58):** +2, all in row 496 (8 to 10 parameters). These are new parameters, not part of r1's 58:
  - `first-bad-confirm-io` is renamed `first-bad-confirm-generic-io` (same count);
  - `missing-confirmed` is renamed `direct-missing-member-both-passes` (same count);
  - two are added: `confirmed-missing-parent-path` and `failed-listing-or-lookup-as-filenotfound-both-passes`.
- **Combined with r4's G4:**
  - 67 unique rows (49 + 18);
  - 66 acceptance cases (48 + 18, row 439 still the measurement gate);
  - 181 instances (121 + 60). r1 said 179.
- Row 407 is not removed from the r4 count. Its expectation is superseded in part, not deleted.

---

## Open points
**Resolved by Codex f0140cd2** (accepted with limits; recorded here, not reopened):
- **O-C1 (ACCEPT).** A tie is exact equality of the persisted, finite `created` values, never of rounded display
  strings. No tolerance window. Unestablishable chronology, and invalid chain candidates, refuse and escalate under
  C1.2. No read-order or UUID tie-break. First-valid-CLOSE monotonicity is kept.
- **O-C2 (ACCEPT).** Rows 485 and 488 use test-side issuer simulations as **procedural-model tests only**. They
  exercise the trial/root committed-record identity and the actual byte hash: absent or mismatch means no line and no
  send, and a match binds the line.
  - Test helpers plus spies do not establish an enforced production issuer guard, and do not prove future Codex
    compliance.
  - Row 487 stays a trusted-issuer residual, **not detection**.
  - Actual issuance still requires the real committed-record and published-report checks before the send.
  - No test writes to the coordination mailbox.
- **O-C4 (ACCEPT).** Recovery is reachable by direct call only (disclosed).
  - The tests establish preserved callable behaviour, not operational reachability or scheduler recovery. R-3 and
    readiness stay unresolved.
  - C4.4 governs C4.5 and row 494: a TIMEOUT at D does not by itself authorize or fabricate an opening seal. No
    qualifying capture means no opening and no START.
  - No new CLI mode, and no extension of `--finalize`.

**Amended (r2):**
- **O-C5 (Codex's text, verbatim, one line as in REVIEW.txt):**

  > "O-C5: confirmed typed absence means FileNotFoundError from an attempt to open/read the specific required member (or a confirmed missing required parent path), on both passes, after preserving the existing root/identity classifications. A failed directory enumeration, PermissionError, other generic OSError, or ambiguous member-lookup failure must not be translated into confirmed absence merely by raising FileNotFoundError or by repeating it. Such failures refuse the invocation with no new INVALID based on that observation. No global listing-health precondition or additional operational probe is introduced. Root disappearance retains F6.6 LOST precedence. In C5.1, a second direct expected-member FileNotFoundError is the explicit typed-absence exception; any other confirming-pass I/O error cannot confirm a violation."

**Remaining (for implementation, no ruling requested):**
- **O-C5a: making the distinction in code.** The QUALIFIED readers today go through `Path.read_bytes` /
  `sha256_file` (s1_common.py:80-81) and `Path.exists` (s1_slot.py:623). A direct open of the member that raises
  FileNotFoundError is distinguishable. An enumeration failure is not, unless the reader avoids enumeration-derived
  absence.
  - Per Codex: where the origin cannot be distinguished, it is treated as a refusal (C5.1).
  - H4 must show which call raises, in its RED.

**Disclosures:**
- Drafted by a Claude subagent for the controller.
- Codex's review was not blind: it saw the questions and the proposal first.
- Shared code and documents form one evidence lineage.
- The C0 reproductions are synthetic and private-function level only. Their outputs are now copied for inspection
  (header).
- No H-task fix, suite, benchmark, live, registration, scheduler or mailbox step was run. No repo file was edited.
- Isolation and stage order are convention, not enforcement.
- Status: NO_CONSENSUS on r2, pending Codex's bounded hash check and operator adoption. Erratum 2 r4 stays adopted and
  unchanged.
- Operational readiness stays INSUFFICIENT_EVIDENCE.

## Process
1. Codex's bounded check of this exact draft (r2 hash).
2. Operator adoption.
3. A byte-frozen copy in research/s1/docs, next to the frozen r4.
4. Then H2 rows 407 and 480-490, H3 rows 491-495, and H4 rows 496-497 proceed under RED/GREEN.

No registration, audit, START, RUN, scheduler or live step is authorized by this clarification.
