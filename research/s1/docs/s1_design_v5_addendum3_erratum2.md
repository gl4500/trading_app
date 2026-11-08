# S1 design v5 — Addendum 3 rev 5, Erratum 2 — draft revision 4

Status: **PROPOSAL** (Claude controller draft for a bounded Codex check, then operator adoption). Not adopted. Nothing
here is in force until a byte-frozen copy lands in research/s1/docs.

Revision 4 answers the Codex review 784e1e6e of r3. r3 (783b1931068cdef13fb60dd2a3af3f037c1081185edb0d992162b07af280fe93),
r2 (240d0166…) and r1 (d9b1c70d…) are kept unchanged.

The Codex records were verified by sha256 and read as peer data. They are in
`.coordination/trading_app/s1_erratum2_r3_codex_review_20261108/`:
- REVIEW.txt (d29ac22099c0c451e035090ec76aa4127a2c551d35c38123c0843e9484efee3a);
- assessment.json (9f531b6ae53093aebe6e72fccbe1be02ad47d5f167153b8302e3a46d0cb47168);
- checks.json (9fbf2f9273090cdbb6c5b769560bc0cea823be0416bc62e092d1ad02786047d0).

Codex's verdict on r3 was AMEND, limited to O16, O17 and O18, with NO_CONSENSUS on r3. These are accepted and are not
reopened: G6/O12 and O19, plus every earlier item. Codex independently verified the 47 rows, the 46 cases and all 10
blob hashes at 28fe5a0. Code citations stay at HEAD 28fe5a0 (header table).

## Revision table (r3 -> r4)

| item | Codex disposition | what changed in r4 | sections |
|---|---|---|---|
| O16 no recreation of s1_out | AMEND: enforce it inside `write_abort`, keep the caller guards | The no-recreation invariant now lives in the helper chain. `write_abort` and its nested publisher (`publish_text_exclusive` -> `publish_exclusive`, whose default is `mkdir=True`) must never create s1_out or any missing ancestor. That covers a root that disappears after any caller check. The G6 evidence copy `invalid/<seq>.json` must not recreate a lost root through a recursive parent mkdir. Creating the `invalid/` child under an existing root is still allowed. Exclusive first-wins publication is kept. The r3 claim "every product caller guards this" is withdrawn as unverified. New case AB-A9, row 468. | G6.1, G6.3, G6.8 AB-A9, G4 468, open points |
| O17 any prior INVALID | AMEND: the condition tests ANY prior TRIAL-INVALID | The request-scoped condition refuses recovery when **any** TRIAL-INVALID row is on the transaction's re-read rows, whatever its reason, subtype, witness or detail. It is evaluated after chain integrity and CLOSED, and before the default step-3 APPEND. This is a documented, narrow F0.5 exception. No other request changes. The implementation note is aligned. AB-A3 gains a different-reason race; new control AB-A10 (an unrelated genuine extra INVALID still appends), row 469. | G6.5, G6.8 AB-A3/AB-A10, G4 462/469, open points |
| O18 I/O error versus malformed bytes | ACCEPT the distinction; AMEND the text (Codex narrowed its own r2 wording) | A persistent read, OS or permission error **refuses**, with no requested work and no local-abort INVALID, under the existing I/O/outage classification. Identical, readable but malformed bytes, confirmed on re-read, are a truthful established-violation / local-abort. The loader's typed outcomes are split. Codex's position change is recorded. AB-A7 and row 466 are re-parameterized. | G6.2, G6.4, G6.8 AB-A7, G4 466, open points |

**Counts change** (exactly):
- +2 map rows (468, 469) and +2 acceptance cases (AB-A9, AB-A10).
- Row 462 goes from 1 to 2 parameterized instances, and row 466 from 4 to 7.
- Totals: **49 unique map rows** (48 acceptance + measurement row 439), **48 acceptance cases**, and **121
  parameterized test instances** (r3: 47 / 46 / 112).

---

Revision 3 answered the Codex review b0b1acd9 of r2. r2 (sha256
240d01660c153b5782ab1453144b8dc2ee77c2aa00db89680fca00485d8d0a47) and r1 (d9b1c70d…) are kept unchanged.

The Codex records were verified by sha256 and read as peer data. They are in
`.coordination/trading_app/s1_erratum2_r2_codex_review_20261108/`:
- REVIEW.txt (4d98ba8c973b2d0d5a735ddbef319c856e25a1671c6376ac0e19f9b8d41f0e4e);
- assessment.json (37358d8251924f591b9e85e01c20bc1a6acaaf0a341e78adac02416074120655);
- source-manifest.json (82be61cc0eeffd6c788419c52daf0d66a6ccb220d87ef1eb7a81d6c4027b5949).

Codex's verdict on r2 was AMEND, on O12 only, with NO_CONSENSUS on r2. Everything else is accepted and closed and is
not reopened: O1-O11, E2-C1-C5, O13, O14, O15 and the O8 inventory condition. r3 changes only what the table below
lists.

## Revision table (r2 -> r3)

| item | Codex disposition | what changed in r3 | sections |
|---|---|---|---|
| O12 known-abort recording point | AMEND: the recording point moves out of score, on ALL branches | New normative section **G6**. In outline: (1) new detections stay external-first, as an ordered sequence that is not atomic; detector-specific reasons are kept. (2) A residual witness is recorded as `reason/established-violation` with subtype `local-abort`; no new journal reason is added; the row is bound to the witness bytes and never backdated. (3) If the journal fails, the local witness is attempted or kept, and the refusal says so truthfully. (4) Recovery runs in the common gate, after the identity, chain, INVALID, bundle and root/plan checks and before stage recovery or any work. (5) Recovery is idempotent through a request-scoped conditional append, with F0.5 unchanged for other requests. (6) Every score branch refuses a known invalidity before any score work; OQ-28 is kept for a failure discovered inside a score. (7) This supersedes A2.3's recording location and the M-3 exceptions. The r2 open point O12 is closed. | G1.1, G1.8 NVS-A9, G1.9, **G6** (new), G4 rows 450 and 460-467, open points |
| G4 count correction | Codex correction (minor evidence) | r2 has **39 unique map rows**, not 46: 12 NVS + 17 R3 + 9 M4 cases, plus measurement row 439, which makes **38 acceptance cases**. The parameterized instances are now counted separately (G4 footer). With G6 added, r3 has **47 unique rows and 46 cases**, plus **112 parameterized test instances**, counted mechanically. | G4 |

Code is re-cited at **HEAD 28fe5a0** (Task 13 committed). The product files at HEAD are byte-identical to the hashes r2
cited, so every r2 citation stands. The only worktree change against HEAD is test-only (`s1_tests/conftest.py`
modified, plus two untracked test/evidence files). See the header.

The re-citation also updates the G1.9 held-test names and lines to HEAD. Task 13 fix round 1 (M-5) split two of the
tests r2 listed. The expectations are unchanged, except that the abort-plus-NVS row now follows G6.

---

Revision 2 answered the Codex review be1215c9 of r1. r1 (sha256
d9b1c70d4d8a5b1908ce170bc58e0d1d16a40f4aa826157515caf81569f25bc6) is kept unchanged. The full Codex records were
verified by sha256 and read, and they are treated as peer data. They are in
`.coordination/trading_app/s1_erratum2_r1_codex_review_20261108/`:
- REVIEW.txt (13aa08c4b9ed067ba7f1d98d85ec009dd0252fb1208c16f3bec29237ffde4580);
- O1-O11-rulings.json (796517e39af14c73d40b9d8cdcdf75d23aac5f565749d536a0acd641bd189754);
- assessment.json (101807d91b1553ff101737ac27b4bb740dc9ee4da43833b4063b8a1723661f1f);
- scope-counterexample.json (d68a5ad3…) and capacity-counterexample.json (4333e0c5…). Both are requirement and
  arithmetic counterexamples, not product runs.

Codex's verdict on r1 was AMEND, NO_CONSENSUS on r1, with conditional support for the repaired design.

## Revision table (r1 -> r2)

| item | Codex disposition | what changed in r2 | sections |
|---|---|---|---|
| O1 final snapshot under NVS | AMEND (Codex revised its own 102df404 position) | The local, provider-free final snapshot is **required** for a valid NVS score. SCORE-ACK `final_snapshot_sha256` is the verified report hash and never `absent`. `final_manifest_sha256=absent` stays NVS-only. The snapshot is a separate authorized command before SCORE-ACK; score never snapshots. The four score inputs stay; the snapshot is bound through the SCORE-ACK line, explicitly. The existing snapshot, projection, fence and bridge checks are kept. No seal is promoted. | G1.2, G1.4, G1.5, G1.8 A1/A5/A11, G1.9, G4 400/404/452 |
| O2 PRED | ACCEPT | prev is exactly PREREG-ACK and no ACQUIRE-ACK may exist. The mailbox parser accepts two shapes but grants no authority. The score/journal gate decides before STAGE-INTENT. Both wrong-branch directions are tested. | G1.4, A2/A3, G4 401/402 |
| O3 mistaken ACQUIRE-ACK | AMEND | Refuse and escalate. The ACK is never deleted, ignored or skipped in latest-chain validation. No BLOCKED and no blocked.json after START. WITHDRAWN only after a genuine operator withdrawal, a future decision with nothing automatic. INVALID only if an invalidity is actually established. | G1.4, G1.6a, A12, G4 453 |
| O4 classification | ACCEPT | verdict NO-VALID-SEAL, classification INCONCLUSIVE, nomination false (now normative). | G1.7 |
| O5 attest_stop keys | AMEND | The current key set is pinned on both branches. stop_close and sealed_final_ledger_sha256 are null **only** under NVS; normal values stay required and non-null. No new key. | G1.3, A5 |
| O6 route scope | ACCEPT | Every exact W_L invocation is routed at any clock, after identity, registration and local-abort checks. This is an explicit narrow OQ-33 exception. New early-route and ordinary-OQ-33 control cases. | G2.1, G2.2, R3-A12/A13, G4 421/422 |
| O7 local abort | ACCEPT | `_no_local_abort` applies to both the W_L route and `run_finalizer`, before any finalizer or stop work. | G2.1, G2.3(8), R3-A16, G4 425 |
| O8 frozen wrappers | ACCEPT | `s1_checkpoint.finalize_close` and `finalize_pending` are retired from prospective product code. Tests move to the clock-callable path. `s1_slot.finalize_close` stays. No compatibility shim. | G2.1, R3-A17, G4 426 |
| O9 confirming pass | ACCEPT | Normative, and labelled a prospective **semantic strengthening**. The G3 heading is revised. The M4-A7 counts apply to completed healthy passes only. | G3 heading, G3.1, M4-A7 |
| O10 capacity | AMEND | A 60 s cap on the **complete healthy scheduled-checkpoint critical path** under pre-bound stress fixtures, not per gate. A miss means NOT READY. | G3.7, G4 439 |
| O11 next_due_utc | AMEND (defer) | Dropped from this erratum and from the implementation scope. | Open points (removed) |
| E2-C1 invalidity in refusals | correction | R3-A2 separates "no requested operation" from "no row". A post-row bundle change means TRIAL-INVALID(bundle) and then refusal. Established registration-artifact violations keep their persistent INVALID. | G2.6 R3-A2, NVS-A2 note, G4 411 |
| E2-C2 pending scope and idempotence | correction | A pending claim blocks only TIMEOUT/NVS and candidates whose required prefix contains it. A pre-STOP INTENT may get its one TIMEOUT or completion after STOP. Idempotence means no duplicate terminal row, no second STOP and no change to stop.json. R3-A11 exempts the route. New controls. | G1.1, G2.3, G2.4, R3-A4/A5/A7/A8/A11/A14/A15, G4 413/414/416/417/420/423/424 |
| E2-C3 known vs discovered invalidity | correction | A known TRIAL-INVALID or local abort refuses at the front door, with no score callback. A failure discovered after a legitimate score INTENT follows OQ-28/F4. The two are separate cases, and a direct `_score` unit test is labelled unit-only. | G1.1, G1.8 A4/A9/A10, G1.9, G4 403/450/451 |
| E2-C4 O1 applied consistently | correction | Every valid-NVS `final_snapshot_sha256=absent` alternative is removed. The snapshot is set up before SCORE-ACK in A1. Missing-before-issuance and changed-after-binding are separate cases. | G1.4, A1, A5, A11, G1.9 |
| E2-C5 normative O3/O5/O9/O10 | correction | All four are now in normative text and map rows. Row 439 now holds the whole-invocation cap and a pre-bound measurement record; it is a measurement gate, not a unit-test PASS. | G1.3, G1.6a, G3, G4 |

## Header (unchanged from r1 except for the sources)
Amends:
- `research/s1/docs/s1_design_v5_addendum3.md` (rev 5, sha256
  d9dd37595f0e0e73098ade1b8548e8cda2dc47fe49243f4d44735508029b9fb2);
- `research/s1/docs/s1_design_v5_addendum3_erratum1.md` (r4, sha256
  b03464669673927fdb057acad9b0dc3258b1f08692d55ec3b0cffd4550f6ca2f).

Both stay byte-identical. Where they differ, this erratum governs. Its sha256 joins the registered bundle (A3.1).

**Prospective only.** It must land, be implemented and be Codex-reviewed on the exact head SHA before any AUDIT-ACK.
It is never retrofitted to a registered trial. No S1 registration has occurred. Earlier approved designs stay
historical records.

Sources (peer dispositions ADOPTED in full by the controller):
- Claude aeabae63-b5ce-49fa-b128-96f170d89512;
- Claude 2f0a98cf-28ac-4876-b0ef-69bdf1fe7feb;
- Codex 78fdedb4-20ad-4062-8c29-15b81cb924ee;
- Codex 102df404-8554-4099-b23c-f3c2a9151783 (its snapshot-absence recommendation is superseded by Codex's O1 ruling);
- Codex be1215c9 (review of r1, records above);
- Codex b0b1acd9 (review of r2; O12 recording-point rule, records above).

Transcription: `.sdd_s1/erratum2_inputs.md` (799a2536…).

Other inputs, read-only: design v5 §9/§14 (33c32840…), A1 A2.x/A5.x (6cb89e36…), A2 B1.x (c7f0c3ff…), t11 r1
(9153062b…), M4 profile (25d64507…).

Code citations are `file:line` at **HEAD 28fe5a0** ("S1 A3 Task 13: score stage, score-aborted INVALID, connected
runs"), `research/s1/`. The file sha256 values below are `git show 28fe5a0:<file> | sha256sum`:

| file | sha256 at 28fe5a0 |
|---|---|
| s1_journal.py | f83913f22ace59cdf8a7ab022566ff6df4d2fbbd4e564c6afb27fbc3465a1afb |
| s1_checkpoint.py | c982a4890bdce2981f65aa806fc02eea6cdef1f9a0c5d058764f6ac583827d92 |
| s1_run.py | 35aa486147ff107d28fef6b87ac56a84a0fe516d86c9e13753be07bed7acf183 |
| s1_collect.py | ded5d7d5beb555d889f4002fb0827ae3982b3642161776bdd885a6083bae11fd |
| s1_slot.py | 09dde1d6e53000b1080e7235a5dc5037caa6be2e051eb7b9aa0e25ac6ffc1448 |
| s1_stage.py | 87b2dd116b6a59ca1afae196eb543c5f97d9ee097219c3f49bad73b503b3a1c7 |
| s1_seal.py | 9c7fd0597cc0327e51d9aa7327d1d1436b4b4ce1468d8f57d304a61614837278 |
| s1_trial.py | 58edd7c84fe8ea9573b8bfeca8ae6dbb2a01670660ecacf6b7395067268fd63d |
| s1_common.py | ef44f70d45aa1d2435c375de480ddd184c0d4e7c09da016def9aeb34c8e247d4 |
| docs/s1_plan_addendum3.md | bfa389ea1f9690af35278f301d0fc6a2cf9a294d898bd00cdd08b5d8d10d580f |

These equal the hashes in r2 and in Codex's r2 source-manifest. r1's s1_run.py citations after line 720 are stale by
about 12 lines; r2 and r3 are correct. The citations describe the behaviour being amended. They are not evidence that
any requirement here is met.

---

## G1. NO-VALID-SEAL terminal-score branch (NVS-1; amends F1, F2, F4 table, F4.8, F7.1, F7.4, the ACK PRED chain, F10)

### G1.0 The conflict being repaired (verified against code; unchanged from r1)
- v5 §9 and R-STOP keep INCONCLUSIVE (NO-VALID-SEAL). A2.1 makes it terminal and persisted. OQ-28 row 307 keeps
  INSUFFICIENT/INCONCLUSIVE as committed scores.
- A3 forces final -> SCORE-ACK -> score. The code does too: s1_stage.py:25, and s1_trial.py:33-34
  (`PRED["S1-SCORE-ACK"]="S1-ACQUIRE-ACK"`).
- Other blockers in the code:
  - s1_run.py:700: attest_stop refuses NVS;
  - s1_run.py:708: it builds `out / None`;
  - s1_collect.py:470-471: `_stop_state` refuses NVS;
  - s1_run.py:1267-1268: the NVS return in `_score` cannot be reached.
- Every binding below must move together.

### G1.1 Branch predicate, authority and precedence (NVS-REQ1; E2-C3)
NVS(rows) holds only when all of these hold on the deciding transaction's rows:
1. STOPPED: exactly one TRIAL-STOP and no TRIAL-INVALID, and not CLOSED;
2. the stop record recomputed from the rows with seq < the STOP seq (`stop_record`, as in F2.3) exists and its detail
   equals the TRIAL-STOP detail;
3. that record has status NO-VALID-SEAL, rule timeout, and exactly the t11 §4 NVS shape: stop_close, stop_seal,
   stop_seal_sha256 and lots null; cohort_row_ids []; seals {}; missed = every no-attempt eligible close;
4. `sampled_seals(…, upto_seq = STOP seq)` is empty.

The command checks before any INTENT that stop.json parses and equals that record. After a finalization INTENT, this
is F2.4.

The branch follows only the journal-authoritative recomputed record bound by the TRIAL-STOP detail. It never follows a
CLI flag, file presence or absence, a display status, or a caller's verdict.

**Precedence, unchanged and evaluated before the branch:**
- ACTIVE: the score is refused.
- INVALID: the gate refuses with no work (s1_trial.py:719-728).
- CLOSED: refused.
- A bundle mismatch after rows: TRIAL-INVALID(bundle), then refusal (s1_trial.py:732-744).
- A damaged frozen prefix, CREATED stage or stop file: F3, F4, E2.6, F2.3/F2.4.
- Persistent mismatch evidence: A3.3, B3.3.
- A failing (2), or a stop.json that differs from the record: stop-conflict handling (F2.3/F2.4). This is never NVS
  and never the normal branch.

**Known invalidity is not a score input (E2-C3).** A pre-existing TRIAL-INVALID, or a known local `s1_out/aborted.json`,
never authorizes a score callback, not even to produce an ABORTED report.
- The front-door gate and the local-abort refusal come first. So do the external-invalidity and outage rules
  (F0.6, F8.1, B3.4).
- The result is no score STAGE-INTENT, no score work and no INCONCLUSIVE.
- **Where a surviving local abort is recorded (r3, O12):** in the common trial-bound gate, on every branch and before
  any requested work, per **G6**. The score never records it.
- A failure genuinely **discovered** after a legitimate score INTENT is different. It follows the existing OQ-28/F4.9
  rules: confirmation on a second computation, the report kept in staging, no PREPARED, and TRIAL-INVALID
  (registration-artifact). It never becomes a PREPARED success.

**No NVS branch may launder an integrity failure into INCONCLUSIVE.** There is no late rescue seal, no changed cohort
and no changed stop (A2.1).

### G1.2 Amended F1 finalization graph, NO-VALID-SEAL only (O1)
```
TRIAL-STOP + stop.json (F2, unchanged)
  -> stop_attest     (STAGE-INTENT, STAGE-PREPARED, STAGE-CREATED; bindings G1.3)
  -> final snapshot  (the existing local, provider-free `s1_checkpoint.py --final-snapshot`, run_final_snapshot,
                      s1_checkpoint.py:921ff; required; a separate authorized command; G1.4a)
  -> S1-SCORE-ACK    (strictly after stop_attest's STAGE-CREATED row; binds the snapshot report hash; G1.4)
  -> score           (STAGE-INTENT, STAGE-PREPARED, STAGE-CREATED; pred = stop_attest CREATED; inputs G1.5)
```
- **Order.** The snapshot comes after the STOP and before SCORE-ACK issuance. Its order relative to stop_attest is
  unchanged from today, where neither requires the other.
- **`s1_stage.permitted`.** Under NVS(rows), and for the score stage only, the predecessor is stop_attest CREATED. The
  ACK is still S1-SCORE-ACK and the state still STOPPED. Every other stage row is unchanged.
- **Not on this branch:** final_plan, ACQUIRE-ACK and final. There is no 3-session lag and no provider-backed step.
- **Still required:** STOP readiness (t11 §1.3) and causality. The trigger `at` is not enough.
- **Never created:** a dummy final manifest, a fake ACQUIRE-ACK, an empty provider-backed final stage, a substituted
  opening seal, or a fabricated stop seal.
- **Seal scope.** The opening seal and any ineligible or later seal are never promoted to sampled economic history or
  an economic endpoint. NVS has none. They stay required integrity evidence (CREATED-file checks, E2.6). The
  snapshot's opening and bridge post-stop fences stay.
- Every status other than NO-VALID-SEAL keeps its graph, lag, thresholds and inputs.

### G1.3 stop_attest bindings under NVS (NVS-REQ2; O5)
- **Statement.** The existing STOP_STATEMENT (s1_run.py:19-20), and only when it is truthfully attestable. Nothing is
  automatic.
- **Stage, unchanged.** Kind single; member attest_stop.json; inputs `{"stop.json", "trial_stop_line"}`
  (s1_run.py:720); request_policy null.
- **Key set, pinned and identical on both branches.** The current record keys are (s1_run.py:709-715, plus
  `intent_at`, s1_run.py:718): `statement, trial_id, attest_start_sha256, start, stop_close, stop_status,
  sealed_final_ledger_sha256, stop_sha256, stop_line_sha256, recorded_utc, intent_at`.
  - No new key is added: no stop_seal and no bundle field.
  - Bundle identity is bound through the gate and the downstream ACK.
- **Nulls, only under NVS(rows):** `stop_close = null` and `sealed_final_ledger_sha256 = null`, with
  `stop_status = "NO-VALID-SEAL"`.
  - On the normal branch both stay required and non-null.
  - Every other key stays populated and validated, NVS or not.
  - stop_seal stays null in stop.json (t11 §4).
- It never builds a path from null (s1_run.py:708 today) and never hashes the opening or any other ledger as "final".
- The operator-binding limitations stay (§12, A1.3).
- The score's provenance check (`_stop_attestation`, s1_run.py:1057ff; today s1_run.py:1069 flags a null stop_close)
  accepts these two nulls **only** under NVS(rows).

### G1.4 SCORE-ACK, F7 and the ACK PRED chain (NVS-REQ3; O1, O2, O3)
- **Kind and fields.** The kind and its exact field list stay (s1_trial.py:28-30): `trial_id bundle_sha256 prev
  runner_sha256 final_manifest_sha256 stop_attest_sha256 final_snapshot_sha256 stop_sha256 journal_seq
  journal_head_sha256 stop_line_sha256`.
- **Bound as normal:** runner, bundle, trial, stop_sha256, stop line, stop attest sha, and journal seq/head.
- **`final_manifest_sha256=absent` is authorized ONLY under a verified NVS(rows).** It never authorizes scoring a
  normal STOPPED/TIMEOUT trial without `final`.
- **`final_snapshot_sha256` is the sha256 of the verified `final_snapshot/report.json` on every valid score, NVS
  included. It is never `absent`** (O1, E2-C4).
  - The parser still accepts `absent` syntactically, because the field is not in STRICT_HEX (s1_trial.py:45-46).
  - The score-level rule therefore refuses `absent` on the NVS branch.
  - The existing OQ-16 binding is unchanged (`_bound_snapshot_check`, s1_run.py:831-854).
- **prev (O2).** On the NVS branch, prev is **exactly** the S1-PREREG-ACK, and no S1-ACQUIRE-ACK may exist for the
  trial. F7.1's chain becomes AUDIT <- OPENING <- RUN <- PREREG <- {ACQUIRE <- SCORE | SCORE (NVS only)}; CLOSE may
  follow any of them.
  - **Mailbox level** (`trials()`, which reads the mailbox only, E3.4 r3). The parser recognizes two syntactically
    valid shapes: prev = the latest chain ACK created before the SCORE-ACK (the ACQUIRE-ACK if one exists, else the
    PREREG-ACK). This grants no stage or work authority, because the TRIAL-STOP line carries only a hash.
  - **Score/journal gate.** Before the score STAGE-INTENT, on the deciding rows, the gate establishes NVS(rows) and
    the matching predecessor:
    - under NVS: PREREG-ACK and no ACQUIRE-ACK;
    - otherwise: ACQUIRE-ACK and final CREATED.
    - Any other combination refuses with no score row.
- **Mistaken ACQUIRE-ACK on an NVS trial (O3).** Refuse and escalate.
  - The ACK is never deleted, ignored or skipped in latest-chain validation. A later CLOSE's prev must name it if it
    is the latest.
  - BLOCKED is not used and S1 writes no blocked.json: BLOCKED is the adopted pre-INTENT, pre-START refusal closure
    (E3), not a post-START repair.
  - If the operator decides to abandon such a trial, the closure is the existing WITHDRAWN. It needs a genuine,
    explicit operator withdrawal message as evidence, with prev = the latest valid ACK. That is a future operator
    decision, and nothing is withdrawn by this erratum.
  - INVALID is the closure only if an existing registered invalidity is actually established. It is never fabricated
    to clear the chain.
- **Causality** adds to F6.1/check_journal:
  - `journal_seq` >= the seq of the stop_attest STAGE-CREATED row;
  - `created` strictly after that row's `created`;
  - `created` strictly after the final snapshot report was written;
  - the existing NVS end-instant rule stays (created > W_last, s1_run.py:887-895).
- There is no fabricated artifact hash and no automatic ACK.
- Unexpected final artifacts still face the existing F4 checks. Nothing may be deleted or bypassed to force the
  branch.

### G1.4a The NVS final snapshot (O1, E2-C4)
- **The existing command, unchanged.** `run_final_snapshot` (s1_checkpoint.py:921ff): state STOPPED, bundle first,
  verified registration. It is a read-only local capture with a fence check and no provider call. One successful
  attempt is final.
- **Seal scope, unchanged.** It checks every seal file as it does today for a status other than STOPPED/TIMEOUT
  (s1_checkpoint.py `_final_snapshot_capture`; s1_run.py:923 filter only STOPPED/TIMEOUT). The opening and bridge
  fences are therefore kept.
- **Required.** `_pre_reserve_gate`'s requirement is unchanged for NVS: a non-abort score needs the snapshot
  (s1_run.py:901-903). `_final_snapshot_problems` (s1_run.py:919ff) applies in full.
- **Score itself makes zero snapshot callbacks.**

### G1.5 F4 table rows under NVS (NVS-REQ4; O1)
These replace the F4.8 stop_attest and score rows only under NVS(rows):

| stage | kind | members (under s1_out) | bound inputs in the INTENT envelope | acks | request_policy | PREPARED provenance |
|---|---|---|---|---|---|---|
| stop_attest (NVS) | single | attest_stop.json | `stop.json`, `trial_stop_line` (unchanged) | {} | null | [] |
| score (NVS) | tree | exactly score/attempt.json, score/s1.json (F4.9) | exactly four: `stop.json`, `trial_stop_line`, `attest_stop.json`, `sampled_history` (OQ-29, `sampled_history(rows, STOP row, {})`) | {"S1-SCORE-ACK": the validated line sha256} | null | [] |

- **Snapshot binding, explicit.** The snapshot is bound transitively. The SCORE-ACK line, whose sha256 is in `acks`,
  carries `final_snapshot_sha256` = the report hash. That hash is verified against the live report before the
  INTENT (`_bound_snapshot_check`). The envelope gains no fifth input.
- There is no `final/manifest.json` key: it is neither "absent" nor present.
- **Kept:** the existing score-tree semantics (single attempt, crash, publication gap, recovery F4.7, idempotence,
  score abort F4.9, OQ-28). Audit, prereg, opening, ineligible and later CREATED integrity evidence stays required.
- `_score`'s step-1 checks run unchanged, including `_final_snapshot_problems`. The one exception is the G1.3 null
  rule, and it applies only under NVS.

### G1.6 final_plan, ACQUIRE-ACK and final under NVS
- These refuse with **no stage row, no work and no provider request** ("NO-VALID-SEAL: nothing to acquire"):
  - `write_final_plan`;
  - `do_final`;
  - an S1-ACQUIRE-ACK presented to `do_final`.
- Each refusal comes after the gate and the integrity checks, and before any INTENT or HTTP-client use. It is decided
  on NVS(rows) and proven by spies. The existing refusal points are s1_collect.py:470-471 and :602-603.
- ACQUIRE-ACK issuance is Codex-side and procedural. Codex does not issue one for a verified NVS trial.

### G1.6a A mistaken ACQUIRE-ACK on an NVS trial (O3)
- `write_final_plan`, `do_final` and `score` refuse and escalate, with no row and no work. G1.4 gives the chain and
  closure rules.
- S1 takes no automatic closure action.

### G1.7 Outcome and closure (NVS-REQ5; O4)
- score/s1.json carries `verdict = "NO-VALID-SEAL"`, `classification = "INCONCLUSIVE"` and `nomination = false`.
- There is no PASS/FAIL and no invented zero or numeric return.
- Zero observed sampled records may be reported as zero. They are never reported as proof of zero live trades.
- There is no pricing, no return calculation and no provider call.
- **Closure.** The existing `S1-CLOSE-ACK … reason=SCORED evidence_sha256=<sha256 of score/s1.json>` (F7.5). SCORED
  means a record was committed, not that a strategy passed. No new CLOSE reason is added.
- There is no implicit new trial and no automatic CLOSE.

### G1.8 Acceptance cases (Codex examples 1-8 plus the r2 corrections)
**Spies.** HTTP client / `_get` / `_paged`; every valuation helper (test_s1_t12_a9 `_spy`); `write_final_plan`,
`do_final`, `final_plan_record`; `s1_snapshot.take_snapshot`; receipt and process callbacks.

**Assertion convention (E2-C1).**
- "No requested operation" means zero score, finalizer, capture, provider and requested SLOT/STOP/stage rows.
- An existing mandatory TRIAL-INVALID row is required where stated. It is never asserted away.

**NVS-A1 (ex. 1; O1).** A valid NVS history (t11 row 303; STOP at a clock >= W_last).
- Steps: stop_attest CREATED; the final snapshot taken (its report hash recorded); then SCORE-ACK with prev =
  PREREG-ACK, final_manifest_sha256 = absent and final_snapshot_sha256 = that report hash; then the score.
- Expected:
  - the score has INTENT/PREPARED/CREATED;
  - exactly the four G1.5 inputs; policy null; provenance [];
  - exactly the two members;
  - s1.json: verdict NO-VALID-SEAL, classification INCONCLUSIVE, nomination false;
  - the score makes zero provider, valuation, final_plan, final, do_final and take_snapshot calls.

**NVS-A2 (ex. 2; O2).** Each of these is refused before any score STAGE-INTENT, with no score/ and no score staging:
- no SCORE-ACK;
- created <= the stop_attest CREATED row;
- journal_seq < that row's seq;
- created <= W_last;
- created <= the snapshot report write;
- a wrong trial_id;
- an ACK `bundle_sha256` that differs from the AUDIT-ACK's (a mailbox chain refusal, F7.1). This is distinct from a
  changed *registered* bundle on disk, which is NVS-A4;
- a wrong stop_line_sha256, stop_attest_sha256 or stop_sha256;
- prev = RUN-ACK or AUDIT-ACK;
- prev naming a nonexistent ACQUIRE-ACK;
- an ACQUIRE-ACK present with SCORE-ACK prev = ACQUIRE-ACK (wrong-branch direction 1).

The legacy ACQUIRE-dependent chain is never reused.

**NVS-A3 (ex. 3; O2).** Normal STOPPED and TIMEOUT trials with no final stage (wrong-branch direction 2):
- an SCORE-ACK with final_manifest_sha256=absent and/or prev=PREREG-ACK is refused with no row;
- an NVS-envelope score INTENT is refused with no row.

**NVS-A4 (ex. 4; E2-C1, E2-C3).** These never become a committed INCONCLUSIVE. Each keeps its existing outcome:
- a forged NVS stop.json on a TIMEOUT trial: stop-conflict, or INVALID per F2.4 after a finalization INTENT;
- a TRIAL-STOP detail that is not the recomputed NVS record: stop-conflict;
- a damaged frozen prefix (QUALIFIED tree, CREATED ineligible seal, opening seal): INVALID (registration-artifact /
  stage-replaced);
- a changed registered bundle after rows: TRIAL-INVALID(bundle) row required, then refusal.

The known-abort case moves to NVS-A9.

**NVS-A5 (ex. 5; O1, O5).** Exact schemas.
- stop.json carries the t11 §4 NVS nulls.
- attest_stop.json has exactly the pinned G1.3 key list, on both branches.
  - Under NVS, only stop_close and sealed_final_ledger_sha256 are null.
  - A normal-branch control has them non-null; a normal-branch null is refused or flagged.
- The SCORE-ACK token parses with final_manifest_sha256=absent and final_snapshot_sha256 = a 64-hex hash.
  - An NVS SCORE-ACK with final_snapshot_sha256=absent is refused.
- No `Path(None)`.
- The opening is never read as the final ledger.
- The s1_out inventory after the score has no final_plan.json, no final/ and no dummy file.

**NVS-A6 (ex. 6; E2-C2).** These are not a terminal NVS. In each, no TRIAL-STOP of status TIMEOUT or NVS commits, and
stop_attest and score are refused with no row:
- a candidate before W_last (t11 case (i));
- a pending W_L INTENT before D(W_L), in a history with no lots candidate (G2.4);
- an UNRESOLVED last close.

**NVS-A7 (ex. 7).** The existing rules hold, with no extra run (`_score` count 1, or 2 only for the OQ-28 confirm):
- publication gap: same-byte recovery (F4.7);
- same-ACK replay: LOST-RACE / idempotent;
- conflicting second score INTENT: INVALID (repeat-stage);
- computation error: INVALID (score-aborted), with the report in staging.

**NVS-A8 (ex. 8).** CLOSE SCORED on sha256(score/s1.json) closes the trial. A wrong evidence hash leaves it open. S1
writes no CLOSE, and no new trial appears.

**NVS-A9 (E2-C3, known invalidity at the front door).** Score work is zero in each case, with no score INTENT and no
INCONCLUSIVE:
- (a) committed TRIAL-INVALID, then score: the gate refuses with no work, and no extra INVALID row is written
  (s1_trial.py:719-728);
- (b) a local aborted.json written after stop_attest CREATED (the held abort-plus-NVS history), with no TRIAL-INVALID,
  then score (r3, G6):
  - the common gate records exactly one TRIAL-INVALID `reason/established-violation`, subtype `local-abort`, bound to
    the witness bytes (G6.2, G6.4);
  - the score is refused before any SCORE-ACK use, score INTENT, callback, snapshot, provider or numeric work;
  - no SCORE-ACK is needed to record the invalidity.
  - The map row is 450, and the general cross-branch cases are G6.8 / rows 460-467.

**NVS-A10 (E2-C3, discovered during an authorized score).**
- After a legitimate NVS score INTENT, an integrity failure is injected so that `_score` returns ABORTED-INVALID on
  both computations.
- Expected: the report stays in staging, there is no PREPARED, and TRIAL-INVALID (registration-artifact) is
  committed (OQ-28).
- A separate direct `_score` unit test may return ABORTED-INVALID. It is labelled unit-level only, and is not proof
  that a known-invalid trial may enter the score stage.

**NVS-A11 (O1, E2-C4, snapshot cases).**
- (a) No snapshot before issuance: an NVS SCORE-ACK with final_snapshot_sha256=absent is refused with no row, and so
  is `_pre_reserve_gate` "no final snapshot" (s1_run.py:901-903).
- (b) The report is deleted or changed after SCORE-ACK binding, confirmed on a second read: INVALID
  (registration-artifact) via `_bound_snapshot_check` (s1_run.py:831-854).
- (c) A differing read that does not confirm: refusal with no row.
- (d) A snapshot fence or projection violation: ABORTED-INVALID via `_final_snapshot_problems`. A failure discovered
  during the score goes to OQ-28 (NVS-A10 path).

**NVS-A12 (O3, mistaken ACQUIRE-ACK).** An NVS trial with an S1-ACQUIRE-ACK present:
- write_final_plan, do_final and score refuse and escalate, with no row;
- S1 writes no blocked.json;
- a CLOSE whose prev skips the ACQUIRE-ACK is refused;
- a fixture-only WITHDRAWN CLOSE with prev = the ACQUIRE-ACK and an operator-message evidence hash closes the trial
  (procedural control; no product withdrawal).

### G1.9 The 7 held tests (conftest.S1_NVS_HELD), re-expected before un-holding
Re-cited at HEAD 28fe5a0. Task 13 fix round 1 (M-5) split two r2-listed tests, and their non-NVS halves now run. The
held set is still 7. Test file sha256 at HEAD: test_s1_run.py 296cdd9d…, test_s1_checkpoint_7b.py 61f0c3e1….

| held test (HEAD 28fe5a0) | new expectation |
|---|---|
| test_s1_checkpoint_7b.py:328 `test_no_valid_seal_trial_scores_no_valid_seal` (the NVS half of :321, which now runs the snapshot half) | the snapshot is taken (trial_status NO-VALID-SEAL); then NVS-A1 scores it (O1: required) |
| test_s1_run.py:458-459 `test_score_no_valid_seal_is_never_fail` | NVS-A1 (classification INCONCLUSIVE, nomination false) |
| test_s1_run.py:636-637 `test_post_end_score_ack_scores_a_no_valid_seal_trial` (the NVS half of :616, whose early-ACK half now runs) | NVS-A2 (early) then NVS-A1; the fixture builds the NVS branch (snapshot, no ACQUIRE-ACK) |
| test_s1_run.py:719-720 `test_combined_abort_and_no_valid_seal_is_aborted_invalid` | **NVS-A9(b) per G6:** the gate records one TRIAL-INVALID established-violation / local-abort; the score is refused with no score callback and no INCONCLUSIVE; renamed accordingly. A unit-only `_score` variant may assert the ABORTED-INVALID diagnostic (NVS-A10 label) |
| test_s1_run.py:829-830 `test_score_ack_before_the_no_valid_seal_window_end_is_refused` | NVS-A2 (<= W_last, <= stop_attest CREATED) |
| test_s1_t12_a9.py:185 `…[NO-VALID-SEAL]` | NVS-A1 spies |
| test_s1_task11.py:777 `test_m7_…[no-valid-seal]` | NVS-A1 + the restarts and quantity_bridge keys |

The non-NVS `aborted` kind of test_s1_task11.py m-7 (:771ff), and the other legacy score-abort tests listed in the plan
(Task 13 step 6, docs/s1_plan_addendum3.md:11074-11077), follow G6: the gate records TRIAL-INVALID, then refuses with
no score. This matches the plan's stated intent ("refused, no score"). G6.1 to G6.6 now also specify the recording
point.

---

## G2. R-3 liveness: the W_L route plus finalizer catch-up (R3-WPEND-1; amends F3, F0.5 step-6 dispatch, OQ-33 narrowly, E1, E2.5; B1.3/B1.5 unchanged)

Definitions (unchanged):
- L = `eligible_sessions(start, cal)[-1]`;
- W_L = `schedule(L, cal)[-1]` = `window_end(L, cal)`;
- E(W_L) = W_L, and D(W_L) = W_L + 30 min.
- t11 fixture: W_L = slot/20270426T120000Z and D(W_L) = 2027-04-26T12:30:00Z.

### G2.1 The W_L invocation route (O6, O7, O8)
Today, a `--scheduled W_L` invocation at a clock >= W_L is refused (s1_journal.py:400-401 via Worker.intent,
s1_slot.py:256). With L sealed, no invocation terminalizes W_L.

Amended, in run_checkpoint (s1_checkpoint.py:497ff):
1. **Identity first, unchanged and in order:**
   - the gate (s1_checkpoint.py:507). Its existing persistent-invalidity actions, such as TRIAL-INVALID(bundle) after
     rows, are kept (E2-C1);
   - `verified_registration` (:509);
   - the registered-slot identity (`_close_for`, :511);
   - the F8.1 local-abort refusal `_no_local_abort` (:513, :572-576).
   Each refusal propagates.
2. **Route predicate (positive).** `scheduled == W_L`, an exact aware-instant equality computed from the verified
   calendar and START. It holds **at any clock**: early, on time or late (O6).
3. **Route body:** `_finalize_others`, `_finalize_last_if_due` and `decide_stop`, with the command's own clock callable
   `now`, unwrapped. `j.append` samples it inside each transaction (s1_journal.py:515-516).
4. **OQ-33 exception (O6, explicit and narrow).**
   - An exact W_L invocation never opens SLOT-INTENT. An early W_L invocation therefore no longer produces the OQ-33
     FAILED record.
   - Every ordinary and every non-W_L worker keeps OQ-33 unchanged.
   - Existing histories with an early W_L INTENT stay valid. They are resolved by the D catch-up (G2.3).
5. **The same `_no_local_abort` refusal is added to `run_finalizer`** (s1_checkpoint.py:438-453, which has none today),
   before any finalizer or stop work (O7). An abort refusal is never permission to work. Required
   persistent-invalidity and outage classification are kept.
6. **Frozen wrappers retired (O8).**
   - `s1_checkpoint.finalize_close` (:337-366) and `finalize_pending` (:456-464) are removed from prospective product
     code once the caller inventory is confirmed.
   - Today: no product caller (main calls run_finalizer only, :1023); 9 test modules reference them (static grep).
   - Those tests move to the clock-callable path.
   - `s1_slot.finalize_close` stays. No shim may turn invocation-start time into a fixed lambda.
   - Historical frozen source and evidence stay intact.
7. Every other slot keeps the existing worker path.

### G2.2 What the route never does
- No capture, no Worker, no work lock, no SLOT-INTENT, no receipt or process callback, and no provider call.
- No frozen time.
- No START re-clock, no eligible-window extension, no shifted or extra slot, no change to E/D/W/W_L or the eligible
  set, and no new market window or capture past W.
- It never catches SystemExit, auth, ACK, bundle or INVALID refusals as permission. Only the G2.1(2) predicate enters
  the route.
- **What it may append (E2-C2):** only the finalizer rows that are due on their own transaction clock (MISSED at or
  after E, TIMEOUT at or after D) and a TRIAL-STOP that is ready under t11 §1.3. That includes an already valid earlier
  lots stop. It never appends a premature MISSED, a premature TIMEOUT or a timeout/NVS STOP.

### G2.3 Provider-free finalizer catch-up (R3-WPEND-1; E2-C2)
The catch-up is `s1_checkpoint.py --finalize` (run_finalizer), invoked at or after every outstanding D, D(W_L)
included. When invoked:
1. **Before D of a pending slot:**
   - no TIMEOUT for that slot (s1_journal.py:404-405);
   - the pending claim blocks TIMEOUT and NO-VALID-SEAL, and any candidate whose required prefix contains it;
   - it does **not** block an earlier lots stop whose prefix is complete (t11 A3; scope-counterexample.json). That
     stop may commit;
   - other due rows are appended.
2. **At or after D:**
   - SLOT-TIMEOUT (the INTENT's op, the finalizer's actor);
   - then, if no STOP exists and the stop rule is met, TRIAL-STOP in the same invocation (E2.5 retries), with `at` the
     in-transaction clock;
   - if a STOP already exists, the pre-STOP INTENT still receives its one TIMEOUT after the STOP (F1: completing an
     in-flight slot whose INTENT seq < STOP seq). That TIMEOUT never enters the sampled history.
3. **Missed W dispatch:** with no W_L invocation, one later catch-up gives MISSED (no INTENT) or TIMEOUT (INTENT,
   clock >= D), then any ready STOP.
4. **Early claim and restart:**
   - a restarted worker never re-intents (s1_slot.py:247-249);
   - the route never reaches that path;
   - a prior W_L INTENT never makes the route append SLOT-INTENT (which would be repeat-attempt).
5. **Late invocation:** any clock after D behaves as (2). There is no upper bound and no invocation-start decision
   clock.
6. **Idempotence (E2-C2):** a repeat appends no duplicate terminal row for a slot and no second STOP (4c), and leaves
   stop.json byte-identical. The journal may still grow by newly due authorized rows, such as (2)'s post-STOP TIMEOUT
   or a legitimate pre-STOP completion. "No extra row" is asserted only in fixture states with no such due row.
7. **Held worker:**
   - a live worker holding `slot-<W_L>` past D cannot block TIMEOUT or STOP (E1.2);
   - cleanup is deferred while the lock is held (E1.4);
   - the worker's later completion is LOST-RACE (E1.3).
8. Identity, registration and local-abort checks come first (G2.1(1), (5)). Nothing is captured, and there are zero
   provider calls and zero live callbacks.

### G2.4 Worked histories (t11 fixture)
- **(a) R3-WPEND-1, NVS lots.**
  - An early W_L INTENT at 11:59:50Z; the worker is killed.
  - 12:00:00Z: the route MISSES the 69 unclaimed d129 slots. There is no W_L TIMEOUT and no STOP.
  - 12:29:59.999999Z: still none.
  - 12:30:00Z: TIMEOUT on W_L, then TRIAL-STOP NO-VALID-SEAL. With row-302 seals instead, the STOP is TIMEOUT.
- **(b) Earlier lots stop with W_L pending** (scope-counterexample.json).
  - The row-300 lots (100/100 sold at d1, stop close 2026-10-27T20:00Z) are present, with an early W_L INTENT.
  - The STOPPED record at d1 commits whenever it is ready, the W_L pending claim notwithstanding.
  - At or after 12:30:00Z the catch-up appends the one W_L TIMEOUT after the STOP. The STOP stays unique and
    stop.json is unchanged.

### G2.5 Boundary (unchanged)
Registering the invocations (W_L tasks, catch-up at or after every outstanding D, dispatch latency, missed and late
runs) is the **scheduler matter, R-3, still OPEN / INSUFFICIENT_EVIDENCE**. G2 fixes only the behaviour when invoked.
`--finalize` is a capability, not proof of invocation. No registration is requested. Actual catch-up registration needs
an independent, evidence-based schedule (O11 ruling).

### G2.6 Acceptance cases
- **R3-A1 dispatch pin.**
  - The route receives the exact clock callable of the command, by identity (no wrapper, no fixed lambda).
  - Zero live callbacks (capture/take_snapshot, receipt_fn, process_fn, HTTP).
- **R3-A2 identity first (E2-C1).** In every case: zero finalizer, capture, provider and requested SLOT/STOP work.
  - No open trial, or a forged or unverified authorization: a refusal with no row.
  - A changed registered bundle after journal rows: **TRIAL-INVALID(bundle) row required**, then refusal.
  - Committed INVALID: refused, no extra row. CLOSED: refused.
  - An established registration-artifact violation found by `verified_registration` or the legacy detector: its
    existing persistent TRIAL-INVALID row is required.
  - An unregistered scheduled instant: refusal with no row.
- **R3-A3 no laundering.**
  - A non-W_L slot at now >= E: refusal with no row and zero finalizer calls.
  - A SystemExit or Refusal injected into any G2.1(1) step for W_L: it propagates, with zero finalizer calls.
- **R3-A4 before D (E2-C2), history G2.4(a).**
  - Route at 12:00:00Z, and catch-up at 12:29:59.999999Z.
  - No W_L TIMEOUT. No TRIAL-STOP of status TIMEOUT or NVS (this history has no lots candidate).
  - The other d129 slots are MISSED.
- **R3-A5 at or after D.**
  - Catch-up at exactly 12:30:00Z: SLOT-TIMEOUT (INTENT op, finalizer actor), then TRIAL-STOP with `at` >= W_last.
  - Run in both the NVS and TIMEOUT variants.
- **R3-A6 held worker.**
  - A real child process holds `slot-<W_L>` past D: TIMEOUT and STOP still commit, and cleanup is deferred.
  - The child's later FAILED is LOST-RACE, with no INVALID and no file of the child moved while it lives.
- **R3-A7 idempotence (E2-C2).**
  - Two routes, two catch-ups, and the two interleaved, in a fixture with no other due row: no row after the first
    STOP, and stop.json byte-identical.
  - Plus a variant with history G2.4(b): exactly one post-STOP W_L TIMEOUT, a unique STOP, and stop.json unchanged.
- **R3-A8 missed dispatch.**
  - No W_L invocation; catch-up at W_L + 3 h.
  - No INTENT: MISSED, then STOP. Early INTENT: TIMEOUT, then STOP.
- **R3-A9 early claim and restart.** With a W_L INTENT present:
  - the route appends no SLOT-INTENT and there is no repeat-attempt INVALID;
  - a restarted W_L worker is refused.
- **R3-A10 late invocation.**
  - The route at W_L + 40 min commits TIMEOUT and STOP in one invocation.
  - An advancing clock callable shows each `at` is that transaction's sample.
- **R3-A11 no window extension (E2-C2).**
  - Ordinary (non-W_L) L-slot worker invocations at now >= E are refused with no row and no capture or INTENT.
  - The exact-W_L route is exempt from that refusal: it may append due MISSED, TIMEOUT and STOP, never a capture.
  - There is no eligible window past W_L, and d130 is never eligible.
- **R3-A12 early W_L route (O6).**
  - No prior INTENT; route at W_L - 10 s.
  - Zero slot attempt: no SLOT-INTENT, no claim, no capture.
  - No MISSED or TIMEOUT for W_L, and no timeout/NVS STOP.
- **R3-A13 ordinary OQ-33 control (O6).** A non-W_L slot invoked before s gives SLOT-INTENT, then FAILED with the
  refused report (unchanged).
- **R3-A14 earlier lots stop with W_L pending (E2-C2), history G2.4(b).**
  - The STOPPED record at d1 commits while W_L is pending.
  - At or after D: exactly one post-STOP W_L TIMEOUT, a unique STOP, and stop.json unchanged.
- **R3-A15 late completion control (E2-C2).**
  - A pre-STOP INTENT's worker publishes and commits before D, after the STOP: its QUALIFIED or FAILED appends (F1).
    It is never a seal or a stop input.
  - A new post-STOP SLOT-INTENT is LOST-RACE.
- **R3-A16 local abort (O7).** A local aborted.json is present: both the W_L route and `run_finalizer` refuse before
  any finalizer or stop work.
- **R3-A17 wrappers retired (O8).**
  - No product or test caller of `s1_checkpoint.finalize_close` or `finalize_pending` remains.
  - An advancing transaction clock is observed through the callable path.
  - `s1_slot.finalize_close` is present.
  - An import or fixture failure is not counted as a behavioural RED.

---

## G3. M4 gate-cost optimizations, with pass scope, and a prospective semantic strengthening of the confirming pass (Codex M4(1)-(3); O9)

### G3.1 Evidence pass (definition; O9)
- An **evidence pass** is one evaluation of the F3 table, the F4 table and the OQ-14 seal recomputation on one
  verified read of the rows.
- **Each confirming re-read is a NEW pass.** That covers s1_slot.py:829, `confirmed_close_problems`, F5
  lock-protected re-reads and fresh transaction reads.
- A new pass has fresh rows, a fresh index, a fresh calendar read, fresh bundle and pin verification, and fresh file
  and tree hashes.
- **This is a prospective semantic strengthening, not only a performance refactor.**
  - Current `evidence_check` reuses one calendar read across both passes (s1_slot.py:818, 826, 829).
  - The gate verifies the bundle once.
- A pass's results never reach a confirming pass, a later gate, another callback or authorization boundary, or
  another command. Verification before each such boundary stays as required.

### G3.2 M4(1): one verified load_pinned / c.sim per pass
- Each pass calls the verified `c.sim()` once (`load_pinned`, s1_common.py:127-139, fail closed). It passes the
  verified module, the calendar read and verified in this pass, and the slot -> (close, E, D) map downward.
- A3.1/A3.2 do not require per-`close_of` re-verification.
- **Every direct `load_pinned` call still verifies.** The verified module is shared only within the current pass.
- No global or earlier calendar cache.
- An unknown slot remains a refusal or violation under the existing classification.

### G3.3 M4(2): per-pass subject index (unchanged from r1)
- A local `subject -> rows` index is built from the pass's verified ordered rows.
- Kept: duplicate and conflict detection, row order, and the exact problem classifications and texts.
- It is recomputed after every fresh, confirming or lock-protected read.
- It never reuses `gv.rows` or its index under the F5 lock or after a head change.

### G3.4 M4(3): each QUALIFIED tree hashed once per pass (unchanged from r1)
- One hash per QUALIFIED tree per pass. It is shared only within that pass, by slot_problems (s1_slot.py:645) and
  `_resolution_evidence`/`seal_bytes` (:595-606).
- Every QUALIFIED tree is hashed, every member and its live bytes checked, and the extra-file inventory checked.
- Trees are re-hashed in the confirming pass and in every later gate.
- A listing, read or permission error, including any scandir replacement of s1_slot.py:623, refuses or triggers
  integrity handling. It never means empty, absent or OK.
- No cross-gate validity memo.

### G3.5 Not allowed (unchanged from r1)
- No cross-gate memo.
- No (size, mtime) shortcut.
- No verified-through-seq record and no incremental full-chain bypass.
- No light worker-path check.
- No discarding of unsampled QUALIFIED evidence to fit capacity.

### G3.6 Acceptance: semantic mutants and fixture cases
Cases marked (C) are listed by Codex. Cases marked (+) are added by this draft.
- **M4-A1 (C) same-size, same-mtime change between gates.** The next gate is INVALID (registration-artifact). Kills
  the (size, mtime) memo and the cross-gate memo.
- **M4-A2 (C) file missing or added.** The existing F3 classification applies. Kills "skip inventory".
- **M4-A3 (C) re-read new journal.**
  - A row appended between the passes legitimizes the file: no violation.
  - The same holds for a lock re-read after a head change.
  - Kills index and rows reuse.
- **M4-A4 (C) listing, read or permission error.** Refusal or integrity handling, never OK.
- **M4-A5 (C) changed pin, between gates or between passes.** Fail closed in the next pass.
- **M4-A6 (C) changed calendar, between gates or between passes.** The fresh calendar is used, and an unknown slot is a
  refusal or violation.
- **M4-A7 (+; O9) pass counters, on completed healthy passes only.**
  - At least one verified pin load per pass, and exactly one inside `evidence_problems`.
  - Each QUALIFIED tree is hashed once per pass, and every tree is hashed.
  - The confirming pass and the next gate repeat the counts.
  - A fail-closed early exit after an established invalidity need not hash the rest.
- **M4-A8 (+) damage to a non-selected later QUALIFIED tree.** INVALID.
- **M4-A9 (+) problem lists.** They equal hand-written lists in text and order. Pre-change equality is only a control
  (A10.1).

### G3.7 M4-WORKLOAD-1 and the readiness cap (O10; OPEN operationally)
**Facts kept from r1:**
- 10.17 + 0.89 × 7.6 ≈ 16.93 s, under a one-QUALIFIED-per-close model. The 0.89 s/MB already includes the 130 closes.
- Cost scales with N_QUALIFIED and with cumulative backup bytes (s1_slot.py:177-181: post_start_gate checks only the
  PREREG-ACK).
- Stress model: (3,979 + 131) × 7.6 MB ≈ 31,236 MB, about 106 s of hashing alone. This is a model, not a timing.

**Readiness cap (normative, prospective operating convention).**
1. **What is capped.** The maximum observed wall time of the complete healthy scheduled-checkpoint critical path must
   be <= 60 s on every declared run. The path covers:
   - process startup;
   - healthy dispatch lateness;
   - every gate and confirming pass reached;
   - lock waits;
   - receipt and capture;
   - durable preparation and R;
   - the required terminal publication.
   This cap is not per gate: 3 gates × 60 s = 180 s > the 120 s minimum slot spacing (capacity-counterexample.json,
   arithmetic only).
2. **Per-gate timings** are reported as well.
3. **Successful controls must complete.** A fast refusal or a skip is not a pass.
4. **Pre-bound measurement record**, declared before measuring: low-Q and high-Q counts, backup bytes,
   trade/projection sizes, a growth margin, CPU/I/O contention, cold and warm runs, and sample counts. Unresolved
   workload bounds mean **NOT READY**.
5. **Injected cases are separate.** Outage, missed-run and very-late recovery cases are correctness and availability
   tests, not omitted members of the healthy sample. Their lateness is reported.
6. **E/D/R and journal timing still apply on their own.** No 60 s result waives them.
7. **The figure is the maximum observed across the declared runs.** It is not a probability guarantee or a p99 from a
   small sample.
8. **The cap is half the minimum spacing.** It is a conservative convention, not an established safety theorem.
9. **A miss means NOT READY.** There is no post-hoc relaxation and no evidence-cache shortcut.

The 45:50 regression-suite time is not a scheduler measurement. R-3 and M4 stay OPEN operationally.

---

## G6. Known-abort recording point and residual-witness recovery (r3, O12; all branches; amends F0.6, F8.1 and the A1 A2.3 recording location; Codex b0b1acd9 REVIEW.txt "O12" items 1-7)

### G6.0 Scope and authority
- This section applies to **every** trial-bound command and **every** branch: NVS, normal STOPPED/TIMEOUT, ACTIVE and
  pre-STOP. It is not limited to score.
- Why: refusing a local-abort trial without ever recording its surviving witness would leave an avoidable F8.1
  residual, and no INVALID evidence line for closure.
- A1's older wording ("ABORTED-INVALID at score", A2.3) cannot override F0.6/F1.
- The adopted plan already states the intended change: docs/s1_plan_addendum3.md Task 5 step 7 (:4654-4658) and
  Task 13 step 6 (:11075-11077), "TRIAL-INVALID committed, score refused".
- This section supplies the recording point that the plan left unspecified for a surviving local witness with no
  committed INVALID.

### G6.1 New detections stay external-first (O12 item 1)
1. The immutable, sanitized observation bytes are built in memory, or staged locally.
2. TRIAL-INVALID is appended through the sole journal writer (`s1_trial.invalidate` -> `j.append`,
   s1_trial.py:635-662).
3. Then the first-wins local abort and evidence are published (`c.write_abort`, s1_common.py:176-187;
   `invalid/<seq>.json`, s1_trial.py:657-661).
- **This is an ordered operation, NOT an atomic transaction spanning SQLite and the files.** A crash between steps is
  possible, and G6.4 and G6.8 handle it.
- Staging authorizes no callback and no economic work.
- **No recreation of s1_out (r4, O16).** Step 3's publication never creates s1_out or any missing ancestor (G6.3).
  This includes the evidence copy `invalid/<seq>.json` (today `c.publish_exclusive(out / "invalid" / …)` at
  s1_trial.py:659, with the default `mkdir=True` whose `parent.mkdir(parents=True)` at s1_common.py:208-209 would
  recreate a vanished s1_out).
- The existing detector-specific reasons stay unchanged (REASONS, s1_journal.py:26-29): bundle,
  registration-artifact, established-violation with its subtypes (s1_slot.py:19, OQ-31/E5.1), stage-replaced,
  stop-conflict, LOST, and so on. They are never replaced by a generic reason.

### G6.2 The recovery reason and observation record (O12 item 2)
**Reason.**
- No new journal reason or subject is added. `reason/local-abort` is not in the frozen REASONS list
  (s1_journal.py:26-29), and `invalid_subject` refuses unknown reasons (s1_journal.py:174-177).
- An established residual abort that has no more specific verified reason is recorded as
  **`reason/established-violation` with `subtype = "local-abort"`** in the canonical observation.
- A "more specific verified reason" is one that the gate's own detectors re-establish in this command: for example,
  the bundle check, or the legacy registration-artifact detector. A reason that is merely stated inside the witness is
  bound as provenance. It is never promoted to the row's reason.

**Observation record**, canonical, with the detail = sha256(c.canonical(record)). The field names are proposed, and
the content is as ruled:
- `subtype: "local-abort"`;
- `abort_sha256`: sha256 of the observed aborted.json bytes;
- `original_reason` and `original_observed_utc`: copied from the witness when they are present and readable,
  otherwise omitted (never guessed);
- `recovery_observed_utc`;
- `trial_id` and `root` identity.

**Timing.** The INVALID row's `at` is the transaction time (F0.2). It is never backdated to the witness time.

**Malformed versus unreadable (r4, O18; replaces r3's "corrupt or unreadable" paragraph).**
- **Readable but malformed bytes.** The bytes are identical by sha256 on both confirmation reads and do not parse as an
  abort record. They are recorded as established-violation / local-abort. The record states the observed byte hash
  and the malformation, for example "unparseable JSON" or "not an object". It never states an invented original
  reason.
- **A read, OS or permission error is not recorded.** It is not proof of malformed content, and not a verified
  local-abort observation.
  - It refuses with no requested work and no local-abort INVALID row, under the existing I/O and outage
    classification (F0.7, F5.5, B3.4).
  - A confirming re-read cannot turn two PermissionErrors into proof of corrupt bytes.
  - The refusal stays fail-closed even when confirmation cannot complete.
  - A later readable witness is then judged normally. No file repair, no deletion and no resume authorization is
    granted.
- **Already-established bundle or registration invalidity** keeps its own outcome.
- Evidence is sanitized: no secret-bearing text (A9.1). No economic result is ever inferred.
- **Codex position change (recorded, 784e1e6e).** Codex's r2 wording "corrupt or unreadable … record exactly the
  failure observed" was too broad: it could be read as authorizing INVALID for a permission outage. Codex narrowed it
  for a stated evidential reason. Being unable to inspect bytes cannot establish that they are malformed, and the
  existing F0.7/F5.5/B3.4 rules already separate an I/O refusal from an established violation. Codex accepted the
  peer objection (r3 O18). The known-invalid no-work rule is unchanged.

### G6.3 Journal unavailable or unwritable (O12 item 3)
- **Try** to publish or keep the local first-wins abort and evidence, then refuse with no new work. Today `invalidate`
  attempts this (s1_trial.py:647-656).
- The only witness is never left in unpublished staging just because the INSERT failed.
- If even the local publication fails, the refusal says so truthfully.
- F8.1 still covers a crash before commit and the loss of uncommitted witnesses.
- No external INVALID, and no closable INVALID evidence, is claimed until a row actually commits.
- **A missing s1_out is never recreated, and the invariant lives in the helper (r4, O16).**
  - `write_abort` and its nested publisher must never create s1_out or any missing ancestor. That holds whether
    s1_out is absent on entry or disappears after any caller's check. The nested publisher is `publish_text_exclusive`
    -> `publish_exclusive`, which defaults to `mkdir=True`.
  - Today both layers create it:
    - `write_abort` calls `out.mkdir(parents=True, exist_ok=True)` (s1_common.py:182);
    - `publish_text_exclusive` (s1_common.py:229-232) calls `publish_exclusive` with the default `mkdir=True`, which
      runs `path.parent.mkdir(parents=True, exist_ok=True)` (s1_common.py:202, 208-209).
  - An `is_dir()` guard alone is insufficient, because the root can vanish between the check and the publication.
  - When s1_out is missing, the publication refuses truthfully and s1_out stays absent.
  - Atomic, exclusive, first-wins publication is kept: temporary file, then hard link, then FileExistsError for a
    later writer (s1_common.py:210-216).
  - One implementation option is the existing `publish_exclusive(…, mkdir=False)` path, as `publish_in_out` uses
    (s1_common.py:190-199). The exact code is left for review.
  - **Evidence copies:** `invalid/<seq>.json` (s1_trial.py:659) must not recreate a lost root through a recursive
    parent mkdir. Creating the `invalid/` child directory under an existing root is distinct from recreating the root,
    and stays allowed.
  - **Caller guards are kept**, as defence in depth: for example s1_trial.py:648, :657, :720, :729.
  - r3's statement that "every product caller guards this" is withdrawn as unverified. Other callers exist:
    s1_checkpoint.py:102, :486, :697; s1_common.py:265, :1076; s1_slot.py:326 (via `ck._write_abort`), :758;
    s1_trial.py:650, :723, :740. The helper-level invariant makes that claim unnecessary.

### G6.4 Recovery in the common trial-bound gate (O12 item 4)
**Where.** In `s1_trial.gate` (s1_trial.py:694ff), at this point:
- **after**, keeping their existing precedence:
  - the verified open trial and ACK chain (:708-717);
  - the journal chain (F0.5 step 1);
  - CLOSED (the open-trial lookup) and INVALID (:719-728);
  - total loss / LOST (:729-731);
  - the bundle (:732-744: TRIAL-INVALID(bundle) after rows);
  - the matching root and plan checks (:745-757, including `_legacy_detectors`);
- **before** stop-gap and stage recovery and any requested work: `s1_seal.stop_check` (:760), `s1_stage.evaluate`
  (:762), the F3 table (:764), `stop_gap_recover` (:765), and every command body.

**Steps.**
1. Read `s1_out/aborted.json` with a **typed** loader (r4, O18). It has four outcomes, which are not collapsed into
   one CORRUPT marker:
   - **absent**: healthy; nothing to record;
   - **readable valid** (a parsed abort record): a residual witness to record;
   - **readable malformed** (the bytes are read but do not parse as an abort record): a malformation to record, with
     its byte hash;
   - **I/O error** (OSError, PermissionError, read error): refuse with no work and no row (G6.2).
   - Today `load_abort` collapses OSError and parse failure into one CORRUPT marker (s1_common.py:161-173,
     CORRUPT_ABORT at :158). See O18.
2. Confirm on a **re-read**: the same bytes by sha256 and the same typed outcome on both reads, with the journal re-read
   still showing no TRIAL-INVALID. A witness that changes or disappears between the reads is unconfirmed: refusal with
   no row and no work, and no invented diagnosis.
3. Record a confirmed readable-valid or readable-malformed witness through the conditional append (G6.5).
4. Refuse, with no new work. The trial is now INVALID, and F0.6 holds.

Every other `load_abort` consumer keeps its fail-closed meaning, as an abort and never "no abort" (B3.4). The typed
split governs only what G6 may record.

**Never a guessed INVALID append** for:
- a foreign root;
- no verified trial;
- a broken or forked journal chain;
- a CLOSED trial;
- a missing s1_out (that is LOST, F6.6, and nothing is recreated).

**Other precedence.**
- The bundle, registration-specific and outage outcomes keep their precedence. Local detection never masks them. For
  example, a bundle mismatch after rows commits TRIAL-INVALID(bundle), not local-abort.
- An outage follows G6.3, with `_legacy_detectors` on outage as today (:711-713).
- No bypass of source or bundle verification is authorized.
- The command-local refusals stay as the outage-path fallback (F8.1) and are normally unreachable after a successful
  recording: `_no_local_abort` (s1_checkpoint.py:572-576, also on the W_L route and in run_finalizer per O7),
  `attest_stop` (s1_run.py:690-691) and `_stop_state` (s1_collect.py:462-463).

### G6.5 Recovery is provider-free and idempotent: a conditional append (O12 item 5)
- The recovery TRIAL-INVALID is appended with a **request-scoped condition**, evaluated inside the `BEGIN IMMEDIATE`
  transaction on the re-read rows (F0.1), in this order:
  1. chain integrity (F0.5 step 1);
  2. CLOSED (step 2);
  3. **the recovery-only condition: if ANY TRIAL-INVALID row exists on those rows, the result is REFUSE, with no row.**
     This holds whatever the reason, subtype, witness or detail of that row (r4, O17).
  4. Only otherwise does the default step-3 / step-7 APPEND apply.
- "Any" means any. A concurrently committed bundle, registration-artifact or other-witness INVALID also makes the
  recovery refuse, and so does a same-witness one.
- The condition never needs to inspect or reverse an existing INVALID's detail hash: the presence of such a row is
  enough.
- The first genuine reason stays authoritative. A stale recovery request can never append after a known INVALID
  (O12 item 5, G6.4, AB-A2).
- **This is a documented, narrow F0.5 exception, for this one recovery request.** Every other TRIAL-INVALID
  observation keeps the existing step-3 behaviour ("an extra INVALID observation", APPEND). There is no global
  deduplication change.
- The implementation note is aligned with this rule. The weaker "suppress only a row with the same subtype and witness
  hash" proposal (controller mailbox note) is rejected.
- **A pre-read alone is insufficient.** F0.5 step 3 currently APPENDs every TRIAL-INVALID as "an extra INVALID
  observation" (s1_journal.py:345-349), and Context has no such condition today (s1_journal.py:102-122).
- The condition applies to this recovery request only. F0.5 is unchanged for every other request, and distinct genuine
  INVALID observations stay permitted (O17).
- The original abort's first-wins bytes are preserved. A witness is never deleted or overwritten to resume a trial.
- No provider call, capture, callback or economic work happens.

### G6.6 Score on every branch (O12 item 6)
- Every score branch refuses a known invalidity before any score INTENT, callback, snapshot, provider or numeric work.
  Known invalidity means a committed TRIAL-INVALID, or a surviving abort that the gate records per G6.4.
- No SCORE-ACK is required merely to record the surviving invalidity.
- A failure first discovered after an otherwise legitimate score INTENT still follows OQ-28: confirmation on a second
  computation, the report kept in staging, TRIAL-INVALID, and no PREPARED (s1_run.py:786-800).
- The direct private `_score` helper stays a unit-only case (NVS-A10).
- CLOSED, and actual transaction race outcomes, keep precedence.

### G6.7 What this supersedes (O12 item 7)
- **A1 A2.3:** only the recording location ("ABORTED-INVALID at score"), and only as far as needed.
- **The known-local-abort exceptions in the current code, tests and comments:**
  - `_pre_reserve_gate` (s1_run.py:899-900, M-3) lets an abort skip the snapshot requirement in order to score;
  - `_score` lists the abort as the first ABORTED-INVALID reason (s1_run.py:1158-1160);
  - `_trial_end`'s abort branch (s1_run.py:861ff).
  All of these become diagnostic only, and are unreachable for a known abort.
- **ABORTED-INVALID** stays the diagnostic classification. It is not a newly committed successful score and not a new
  closure reason.
- **CLOSE INVALID** still binds the first genuine TRIAL-INVALID line (F7.5), issued separately through the existing
  procedure.

### G6.8 Acceptance (Codex's O12 additions; stable ids)
These use behavioural RED/GREEN and real synthetic gate and journal integration. The implementation uses generated
state and ordering boundaries plus targeted crash, race and skip-witness mutations. This document runs no test.
- **AB-A1 surviving abort, no INVALID** (NVS, normal STOPPED, normal TIMEOUT):
  - exactly one genuine TRIAL-INVALID commit (established-violation / local-abort, unless a more specific reason is
    re-detected);
  - no score INTENT, callback, provider, snapshot or valuation;
  - the INVALID closure evidence is that committed line.
- **AB-A2 already-INVALID re-entry:** refused; no duplicate recovery row; the first reason is preserved.
- **AB-A3 concurrent arbitration (r4, O17):** real processes and real `BEGIN IMMEDIATE` arbitration, not a mocked
  pre-read.
  - (a) Two recoverers of the same witness: at most one recovery INVALID, and the loser does no work.
  - (b) A recoverer racing a concurrently committed **different-reason** INVALID, for example bundle or
    registration-artifact: the recovery appends **zero** rows and does no work. The first genuine reason stays.
  - Kills the mutants "pre-read-only idempotence" and "same-subtype/same-witness-only condition".
- **AB-A4 crash after the INVALID commit, before the abort is published:** the next gate refuses from the journal, with
  no work. Restoring the files never resumes the trial.
- **AB-A5 journal outage during a new detection:**
  - the local witness is attempted and kept;
  - no external commit is claimed;
  - after the journal recovers, the surviving witness commits once;
  - variant: the local publication also fails, and the refusal says so truthfully;
  - an abrupt crash before either witness is durable stays explicitly F8.1 (documented, not a success case).
- **AB-A6 identity and precedence:** each of these follows the existing identity, precedence and LOST rules. None gets a
  fabricated local-abort INVALID, and no directory is recreated:
  - a foreign root or no trial;
  - a forked chain;
  - CLOSED;
  - a bundle mismatch (gives TRIAL-INVALID(bundle));
  - a missing s1_out (LOST).
- **AB-A7 witness integrity (r4, O18).** Each case is distinct. In every refusal: zero callbacks and no recreated
  directory.
  - A persistent PermissionError, or a persistent read/OS error, on both reads: refusal, with no local-abort INVALID
    and no requested work.
  - The same readable malformed bytes on both reads: exactly one genuine INVALID (established-violation / local-abort,
    with the byte hash and the malformation stated).
  - Bytes that change between the reads, or a witness deleted between them: refusal (unconfirmed), with no row and no
    work.
  - A valid residual witness: recorded exactly once.
  - Healthy absence: nothing recorded, and the command proceeds through its normal gates.
  - No guessed reason in any case.
- **AB-A8 controls:**
  - a genuinely new integrity failure inside an authorized score keeps OQ-28 (shares the oracle with NVS-A10 /
    row 451);
  - ordinary healthy numeric controls are unchanged;
  - NVS controls are unchanged.
- **AB-A9 no recreation of s1_out (r4, O16).** These exercise the actual helper chain (`write_abort` ->
  `publish_text_exclusive` -> `publish_exclusive`, and the `invalid/<seq>.json` evidence copy). A fake mkdir spy alone
  is not enough.
  - (a) The output root is missing at entry: a truthful refusal, and s1_out stays absent.
  - (b) The root disappears between the caller or helper check and the publication (an injected barrier): a truthful
    refusal, and s1_out stays absent.
  - (c) The root disappears before the evidence copy `invalid/<seq>.json`: the copy is not published, s1_out stays
    absent, and the committed row stands.
  - (d) A valid existing root: exactly one complete first-wins witness is published, and later writers preserve it
    (FileExistsError, and the stored record is returned). Creating the `invalid/` child under an existing root is
    allowed.
- **AB-A10 default extra-observation control (r4, O17).** On an already-INVALID trial, an unrelated, authorized,
  genuine extra TRIAL-INVALID observation (not the G6 recovery request) still APPENDs under the unchanged F0.5 step 3.
  The recovery-only condition does not leak into other requests.

---

## G4. Requirement-map rows (one row per acceptance case)

| id | requirement | test to create | expected outcome |
|---|---|---|---|
| 400 | NVS-REQ1-5, O1, O4 (ex. 1) | test_s1_a3_nvs.py::test_nvs_branch_commits_inconclusive_score | snapshot taken before SCORE-ACK; score CREATED, 4 inputs, policy null, provenance []; verdict NO-VALID-SEAL, classification INCONCLUSIVE, nomination false; score makes zero provider/valuation/final/snapshot calls |
| 401 | NVS-REQ3, O2 (ex. 2) | test_s1_a3_nvs.py::test_nvs_score_ack_defects_refuse[no-ack,before-stop-attest,seq-before-stop-attest,before-w-last,before-snapshot,wrong-trial,ack-bundle-chain,wrong-stop-line,wrong-attest-sha,wrong-stop-sha,prev-run,prev-audit,prev-missing-acquire,nvs-with-acquire-prev] | refused before any score INTENT; no score/ or staging; no requested work |
| 402 | NVS-REQ3, O2 (ex. 3) | test_s1_a3_nvs.py::test_normal_stop_cannot_take_nvs_path[stopped,timeout] | absent-final / PREREG-prev SCORE-ACK refused; NVS-envelope INTENT refused, no row |
| 403 | NVS-REQ1, E2-C1 (ex. 4) | test_s1_a3_nvs.py::test_forged_or_damaged_nvs_never_inconclusive[forged-stop-json,bad-stop-detail,damaged-qualified,damaged-ineligible-seal,damaged-opening,registered-bundle-changed] | existing INVALID/refusal (bundle: TRIAL-INVALID(bundle) row required); never INCONCLUSIVE |
| 404 | NVS-REQ2/3, O1, O5 (ex. 5) | test_s1_a3_nvs.py::test_nvs_exact_schemas[nvs,normal-control] | pinned attest key list; NVS-only nulls; SCORE-ACK snapshot hash 64-hex (absent refused); no Path(None); no dummy files |
| 405 | NVS-REQ1, E2-C2 (ex. 6) | test_s1_a3_nvs.py::test_not_terminal_nvs_cannot_attest_or_score[before-w-last,pending-w-no-lots,unresolved] | no TIMEOUT/NVS TRIAL-STOP; stop_attest and score refused, no row |
| 406 | NVS-REQ4, F4.7/F4.9/OQ-28 (ex. 7) | test_s1_a3_nvs.py::test_nvs_score_failure_and_recovery_rules[publication-gap,same-ack-replay,conflicting-intent,computation-error] | same-byte recovery / idempotent / INVALID repeat-stage / INVALID score-aborted; no extra run |
| 407 | NVS-REQ5, F7.5 (ex. 8) | test_s1_a3_nvs.py::test_nvs_close_scored_evidence | CLOSE SCORED on sha256(score/s1.json) closes; no S1 CLOSE, no new trial |
| 450 | E2-C3, G6.6 known invalidity (NVS) | test_s1_a3_nvs.py::test_known_invalidity_never_enters_score[committed-invalid,local-abort-after-stop-attest] | zero score work, no score INTENT, no INCONCLUSIVE; committed INVALID: no extra row; local abort: gate commits exactly one established-violation/local-abort INVALID (G6.4), then refuses |
| 451 | E2-C3 discovered failure | test_s1_a3_nvs.py::test_failure_discovered_during_authorized_score; unit: test_s1_a3_nvs.py::test_score_helper_unit_aborted_invalid | report in staging, no PREPARED, TRIAL-INVALID (registration-artifact); unit test labelled unit-only |
| 452 | O1, E2-C4 snapshot | test_s1_a3_nvs.py::test_nvs_snapshot_cases[missing-before-issuance,deleted-after-binding,changed-after-binding,unconfirmed-read,fence-violation] | refusal no row / INVALID registration-artifact / INVALID / refusal no row / ABORTED-INVALID per existing rules |
| 453 | O3 | test_s1_a3_nvs.py::test_mistaken_acquire_ack_on_nvs[refuse-escalate,no-blocked-json,close-skipping-acquire,withdrawn-fixture] | refuse + escalate, no row; no blocked.json; skipping CLOSE refused; fixture WITHDRAWN with operator evidence closes |
| 410 | G2.1 dispatch | test_s1_a3_wpend.py::test_w_last_route_pins_clock_and_no_live_callback | exact callable; zero live callbacks |
| 411 | G2.1(1), E2-C1 | test_s1_a3_wpend.py::test_w_last_route_identity_first[no-trial,forged-auth,registered-bundle-changed,invalid,closed,registration-artifact,unregistered-slot] | zero requested work in all; INVALID(bundle) / persistent registration-artifact row where required; else no row |
| 412 | G2.2 | test_s1_a3_wpend.py::test_refusals_never_become_finalization[non-w-after-e,injected-systemexit] | refusal propagates; zero finalizer calls |
| 413 | G2.3(1), E2-C2 | test_s1_a3_wpend.py::test_before_d_no_timeout[route-at-w,catchup-at-d-minus-1us] | no W_L TIMEOUT; no TIMEOUT/NVS STOP; other L slots MISSED |
| 414 | G2.3(2) | test_s1_a3_wpend.py::test_at_d_timeout_then_stop[nvs,timeout] | SLOT-TIMEOUT (INTENT op, finalizer actor) then TRIAL-STOP, at >= W_last |
| 415 | G2.3(7) | test_s1_a3_wpend.py::test_held_worker_cannot_block_timeout | TIMEOUT + STOP; cleanup deferred; child LOST-RACE, no INVALID |
| 416 | G2.3(6), E2-C2 | test_s1_a3_wpend.py::test_repeat_invocations_idempotent[no-due-rows,post-stop-timeout] | no duplicate terminal, no second STOP, stop.json identical; no extra row only in the no-due fixture |
| 417 | G2.3(3) | test_s1_a3_wpend.py::test_missed_w_dispatch_catchup[no-intent,early-intent] | MISSED or TIMEOUT, then STOP |
| 418 | G2.3(4) | test_s1_a3_wpend.py::test_early_claim_restart_refusal | no SLOT-INTENT from the route; restart refused |
| 419 | G2.3(5) | test_s1_a3_wpend.py::test_late_scheduler_invocation | one late invocation: TIMEOUT + STOP; per-transaction `at` |
| 420 | G2.2, E2-C2 | test_s1_a3_wpend.py::test_no_window_extension | ordinary L-slot workers at now >= E refused, no capture/INTENT; W_L route exempt (due rows only); d130 ineligible |
| 421 | O6 | test_s1_a3_wpend.py::test_early_w_last_route_no_attempt | no INTENT/claim/capture; no W_L MISSED/TIMEOUT; no timeout/NVS STOP |
| 422 | O6 | test_s1_a3_wpend.py::test_ordinary_early_slot_oq33_unchanged | INTENT then FAILED (refused report) |
| 423 | E2-C2 | test_s1_a3_wpend.py::test_earlier_lots_stop_with_pending_w_last | STOPPED at d1 commits; one post-STOP W_L TIMEOUT at D; unique STOP; stop.json unchanged |
| 424 | E2-C2 | test_s1_a3_wpend.py::test_pre_stop_intent_late_completion | completion after STOP appends; never seal/stop input; new post-STOP INTENT LOST-RACE |
| 425 | O7 | test_s1_a3_wpend.py::test_local_abort_refuses_route_and_finalizer[route,finalizer] | refusal before any finalizer/stop work |
| 426 | O8 | test_s1_a3_wpend.py::test_frozen_wrappers_retired | no callers; advancing clock observed; s1_slot.finalize_close present |
| 430 | G3.4/G3.5 (C) | test_s1_a3_m4_pass.py::test_same_size_same_mtime_change_detected_next_gate | INVALID (registration-artifact) |
| 431 | G3.4 (C) | test_s1_a3_m4_pass.py::test_tree_file_missing_or_added[missing,added] | existing F3 classification |
| 432 | G3.1/G3.3 (C) | test_s1_a3_m4_pass.py::test_confirming_pass_rereads_journal[new-row,lock-reread-head-change] | fresh rows/index; no violation |
| 433 | G3.4 (C) | test_s1_a3_m4_pass.py::test_listing_error_refuses[scandir,read,permission] | refusal / integrity handling, never OK |
| 434 | G3.2 (C) | test_s1_a3_m4_pass.py::test_changed_pin_fails_closed[between-gates,between-passes] | fail closed |
| 435 | G3.2, O9 (C) | test_s1_a3_m4_pass.py::test_changed_calendar_fresh_pass[between-gates,between-passes,unknown-slot] | fresh calendar; existing classification |
| 436 | G3.1-G3.4, O9 (+) | test_s1_a3_m4_pass.py::test_pass_counters | counts on completed healthy passes; confirming and next gate repeat |
| 437 | G3.4 (+) | test_s1_a3_m4_pass.py::test_non_selected_qualified_damage_invalid | INVALID |
| 438 | G3.3 (+) | test_s1_a3_m4_pass.py::test_problem_lists_exact | equal to hand-written lists |
| 439 | G3.7, O10 | measurement gate (not a unit-test PASS): pre-bound record + runs under s1_evidence/a3/m4_workload/ | READY only if every declared healthy run's complete critical path <= 60 s, with per-gate timings reported, all controls completed and the workload bounds resolved; otherwise NOT READY |

| 460 | G6.4/G6.6, O12 (AB-A1) | test_s1_a3_abort_recovery.py::test_surviving_abort_recorded_once_then_refused[nvs,stopped,timeout] | exactly one TRIAL-INVALID established-violation/local-abort bound to the witness sha256; zero score INTENT/callback/provider/snapshot/valuation; CLOSE INVALID evidence = that line |
| 461 | G6.5 (AB-A2) | test_s1_a3_abort_recovery.py::test_already_invalid_reentry_no_recovery_row | refused; no recovery row; first INVALID reason preserved |
| 462 | G6.5, O17 (AB-A3) | test_s1_a3_abort_recovery.py::test_concurrent_recovery_arbitration[same-witness,different-reason-invalid] | real processes / real transaction arbitration: at most one recovery INVALID (same witness); zero recovery rows against a concurrently committed different-reason INVALID; loser does no work; pre-read-only and same-witness-only mutants killed |
| 463 | G6.1/G6.4 (AB-A4) | test_s1_a3_abort_recovery.py::test_crash_after_invalid_before_abort_publication | next gate refuses from the journal, no work; restoration never resumes |
| 464 | G6.3 (AB-A5) | test_s1_a3_abort_recovery.py::test_journal_outage_keeps_witness_then_commits_once[local-witness-kept,local-publish-fails] | witness attempted and kept; no claimed external commit; after recovery exactly one commit; publish failure reported truthfully |
| 465 | G6.4 (AB-A6) | test_s1_a3_abort_recovery.py::test_no_guessed_invalid_on_identity_failures[foreign-root,no-trial,forked-chain,closed,bundle-mismatch,missing-s1-out] | existing identity/precedence/LOST outcome (bundle: TRIAL-INVALID(bundle)); no local-abort INVALID; no recreated directory |
| 466 | G6.2/G6.4, O18 (AB-A7) | test_s1_a3_abort_recovery.py::test_witness_integrity[permission-error-persistent,read-error-persistent,malformed-confirmed,changed-between-reads,deleted-between-reads,valid-residual-once,healthy-absence] | persistent permission/read error: refusal, no local-abort INVALID, no work; same readable malformed bytes: exactly one established-violation/local-abort with byte hash and malformation; changed/deleted: refusal unconfirmed, no row, no work; valid residual: recorded once; absence: nothing recorded; all refusals zero callbacks, no recreated directory |
| 467 | G6.6 (AB-A8) | test_s1_a3_abort_recovery.py::test_abort_recovery_controls[discovered-in-score,numeric-healthy,nvs-healthy] | OQ-28 for a failure found inside the score (same oracle as 451); healthy numeric and NVS unchanged |
| 468 | G6.1/G6.3, O16 (AB-A9) | test_s1_a3_abort_recovery.py::test_no_s1_out_recreation[root-missing-at-entry,root-vanishes-before-publish,root-vanishes-before-evidence-copy,existing-root-first-wins] | actual helper chain: truthful refusal and s1_out absent (a,b); evidence copy not published, s1_out absent, committed row stands (c); one complete first-wins witness, later writers preserve it, invalid/ child allowed (d) |
| 469 | G6.5, O17 (AB-A10) | test_s1_a3_abort_recovery.py::test_default_extra_invalid_observation_still_appends | an unrelated authorized genuine extra TRIAL-INVALID on an INVALID trial APPENDs (unchanged F0.5 step 3); the recovery condition does not leak |

The test names are proposed. Each RED is recorded old-fail / new-pass, with fixture incompatibilities separated
(A10.1, F10). The ids from r1 are kept. New in r2: rows 421-426 and 450-453. New in r3: rows 460-467. New in r4: rows
468-469. Re-parameterized in r4: rows 462 and 466.

**Counts (r4):**
- **49 unique map rows:**
  - 22 NVS/abort rows (400-407, 450-453, 460-469);
  - 17 R3 rows (410-426);
  - 10 M4 rows (430-439, row 439 being the measurement gate).
- **48 acceptance cases**, one per non-measurement row:
  - NVS-A1..A12 (12);
  - AB-A1..A10 (10);
  - R3-A1..A17 (17);
  - M4-A1..A9 (9).
- **121 parameterized test instances** across the 48 test rows (NVS/abort 76, R3 29, M4 16). An unparameterized row
  counts as 1; row 451 counts as 2 (one integration and one unit test); row 439 is excluded. Counted mechanically from
  the bracketed ids in this table.
  - NVS/abort per row: 400:1, 401:14, 402:2, 403:6, 404:2, 405:3, 406:4, 407:1, 450:2, 451:2, 452:5, 453:4, 460:3,
    461:1, 462:2, 463:1, 464:2, 465:6, 466:7, 467:3, 468:4, 469:1.
  - R3 rows 410-426: 1, 7, 2, 2, 2, 1, 2, 2, 1, 1, 1, 1, 1, 1, 1, 2, 1.
  - M4 rows 430-438: 1, 2, 2, 3, 2, 3, 1, 1, 1.
- **Delta from r3** (47 rows, 46 cases, 112 instances):
  - +2 rows and +2 cases (468/AB-A9, 469/AB-A10);
  - +9 instances: row 462 goes from 1 to 2, row 466 from 4 to 7, row 468 adds 4 and row 469 adds 1.
- r2's actual counts were 39 rows and 38 cases (r3 correction).

---

## Open points, flags and disagreements (r4)
Codex has accepted and closed G6/O12, O19, O13, O14, O15, the O8 inventory condition and every earlier item. r4
incorporates the O16, O17 and O18 corrections as ruled. None is judged wrong or internally contradictory.

**Resolved in r4 (from r3's flags):**
- **O16:** the no-recreation invariant lives in the helper chain (G6.1, G6.3, AB-A9 / row 468).
- **O17:** an ANY-INVALID recovery condition, documented as a narrow F0.5 exception (G6.5, AB-A3 / row 462, AB-A10 /
  row 469).
- **O18:** an I/O error refuses, and readable malformed bytes are recorded (G6.2, G6.4, AB-A7 / row 466).

**Code conflicts the implementation must change** (all at HEAD 28fe5a0). These are recorded, not decided silently,
and the exact code is left for review:
- **C-O16a. The helpers create s1_out today:**
  - `write_abort` does `out.mkdir(parents=True, exist_ok=True)` (s1_common.py:182);
  - `publish_text_exclusive` (s1_common.py:229-232) passes the default `mkdir=True` to `publish_exclusive`, which runs
    `parent.mkdir(parents=True, …)` (s1_common.py:202, 208-209).
- **C-O16b. The evidence copy can recreate s1_out:**
  - `invalidate`'s copy `c.publish_exclusive(out / "invalid" / …)` (s1_trial.py:659) uses that default;
  - its `out.is_dir()` guard (s1_trial.py:657) is check-then-act.
  - Requirement: create `invalid/` only under an existing root, never the root itself.
- **C-O16c. A behaviour change for other callers.** Every product caller of `write_abort` inherits the
  no-recreation behaviour: s1_checkpoint.py:102, :486, :697; s1_common.py:265, :1076; s1_slot.py:326, :758;
  s1_trial.py:650, :723, :740. A caller that relied on implicit creation, if any, now refuses truthfully instead. The
  implementation must run the existing suite against this change and list any such test.
- **C-O17. There is no recovery condition today.** F0.5 step 3 APPENDs every extra TRIAL-INVALID (s1_journal.py:345-349),
  and `Context` (s1_journal.py:102-122) has no recovery-only field. The narrow exception needs a new request-scoped
  Context/Request field, evaluated after steps 1 and 2.
- **C-O18. `load_abort` cannot tell the cases apart.** It collapses OSError and parse failure into one CORRUPT marker
  (s1_common.py:161-173; CORRUPT_ABORT at :158).
  - The typed split (absent / readable valid / readable malformed / I/O error) is required for G6.
  - Every existing consumer must keep its fail-closed meaning (B3.4): an abort, never "no abort".

**Remaining choices** (no ruling requested unless Codex objects):
- the field names of the G6.2 observation record (proposed);
- whether the typed loader is a new function or a mode of `load_abort` (implementation choice under C-O18).

**Disclosures:**
- Written by a Claude subagent for the controller.
- Codex's r3 review saw r3 and the controller positions, so it was not blind.
- Isolation and stage order are convention, not enforcement.
- No test, mutant, benchmark, live, registration or scheduler step was run.
- The code citations are static reads at HEAD 28fe5a0. The s1_common.py lines were read from
  `git show 28fe5a0:research/s1/s1_common.py` (ef44f70d…).
- Status: NO_CONSENSUS on r4 pending Codex's bounded check of the exact hash. NVS-1 is CONDITIONAL_SUPPORT. R-3 and M4
  are OPEN / INSUFFICIENT_EVIDENCE operationally.

## G5. Process
1. A bounded Codex check of r4 (exact hash): O16, O17, O18 and the counts.
2. Operator adoption.
3. A byte-frozen copy in research/s1/docs.
4. Implementation in the pre-AUDIT-ACK hardening task, RED/GREEN, with the held tests re-expected per G1.9 before they
   are un-held.
5. The exact amendment, source and test hashes go into the pre-AUDIT review package.

No registration, audit, START, scheduler or live step happens until a later CONSENSUS. R-3 stays OPEN.
