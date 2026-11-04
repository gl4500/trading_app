# S1 design v5 — Addendum 3 rev 5, Erratum 1 — revision 4

Revision 4 (Claude, before Codex review of r3) adds six clarifications the plan drafter raised against r3
(777de174…, kept unchanged). They change no outcome:
- E2.2: the position of the wrong-selection check in the precedence;
- E2.3: the single-file assumption;
- E2.5: the opening close excluded; the retry bound; the fence and the stop record;
- E5.5: the nested staging key for seal stages.

Revision 3 answers Codex final 3ddf7d83 (FORUM-S1-A3-PLAN-R1). The operator authorized one more scoped round on
2026-11-03. Rev 2 (b03b760d…) is kept unchanged.
- A3-PR1-1: E2 is rewritten. Every post-START seal is an F4 stage, `seal/<close>`. Its decision is committed
  atomically in the journal transaction, which also reads Codex's CLOSE rows from the same sqlite file. TRIAL-STOP
  requires every determined seal of its prefix to be CREATED inside its own transaction. There is no post-write
  check and no lock-only claim.
- A3-PR1-2: E3.4 is rewritten. S1 never recomputes a historical BLOCKED CLOSE from any directory. Codex verifies
  the evidence against that trial's own root at issuance, and closure is monotone in the mailbox history.
- E1.3 oracle (Codex note): after a committed TIMEOUT, the worker's completion is LOST-RACE at 4c, whatever R is.

Revision 2 (Claude, before any Codex review) clarifies three plan-alignment points; rev 1 (bee16ded…) is kept
unchanged:
- E2.4: seals_checked lists every published seal file under seals/;
- E3.4: a BLOCKED CLOSE whose recomputation is impossible fails closed;
- E5.5: staging keys label files outside s1_out, and the manifest hashes the live bytes.


Revision 1 (Claude, before any Codex review) closes eight gaps the plan drafter found in rev 0 (4dc7a3c5…), which
is kept unchanged:
- E2.4–E2.6: when a seal is required, pre-STOP publication, a held stop lock;
- E3.1, E3.2, E3.4: the clauses named, trial_id in blocked.json, a canonical evidence hash;
- E4.3: trial_id attribution grammar;
- E5.5: the evidence-manifest byte format;
- E5.6: the opening-window consequence of literal F7.2(b).

Status: DRAFT for a scoped Codex check, then operator adoption. Prospective: no S1 registration has occurred.
Amends `research/s1/docs/s1_design_v5_addendum3.md` (rev 5, sha256
d9dd37595f0e0e73098ade1b8548e8cda2dc47fe49243f4d44735508029b9fb2), which stays byte-identical. Where this erratum
differs from it, this erratum governs. Its sha256 joins the registered bundle (A3.1) next to the addendum's.

Source: FORUM-S1-A3-PLAN (Codex final f045bd31 on plan 2de6a9b; Claude final a1d66626…).
- PLAN-1 showed a frozen-spec tension: F5.1 vs the retained B1.3 deadline.
- OQ-0 (blocked.json) needed a separate requirement ruling.
- OQ-6 (CLOSE candidates) needed a grammar clarification.
- Several OQ rulings need to be recorded as clarifications.

Operator decisions:
- 2026-11-03: erratum plus revised plan, then one scoped Codex check.
- 2026-11-03, BLOCKED handling: the operator asked to proceed on Codex's path. Codex ruled that BLOCKED must stay
  distinct from INVALID (OQ-0 ruling, f045bd31). E3 is Claude's proposal on that basis, for Codex to accept or amend.

Nothing else in rev 5 changes. In particular:
- start_attest stays a single-member stage (OQ-15 ruling);
- F7.2(b) keeps its literal all-opening-slots checklist (OQ-37 ruling);
- the F3 QUALIFIED tree includes the capture's raw bytes (OQ-32 ruling).

## E1. Deadline arbitration is separate from work ownership (PLAN-1; amends F5.1, F3, OQ-13)
1. **Slot work lock.** A slot worker takes the slot work lock `slot-<s>` before its pre-check (OQ-34) and holds it
   across its whole operation: SLOT-INTENT, work, then QUALIFIED or FAILED. Stage and stop operations keep F5.1
   unchanged.
2. **Terminal decisions are arbitrated by the journal, not the work lock.** Every slot terminal row is decided
   inside the F0.1 `BEGIN IMMEDIATE` transaction, on the state re-read there, by the F0.5 precedence. The first
   terminal row wins.
   - The finalizer's SLOT-TIMEOUT (now >= D) and SLOT-MISSED (now >= E) appends do NOT take, wait for or test the
     slot work lock.
   - A live, stalled worker therefore never prevents TIMEOUT at D.
   - This restores B1.3: a slot without a QUALIFIED row committed with R < D is TIMEOUT once now >= D.
3. **The worker after a TIMEOUT.** Once TIMEOUT is committed, a later QUALIFIED or FAILED request from the same
   authorized worker (identity passes 4a) is LOST-RACE at 4c, before step 6, whatever its R. REFUSE for a late R
   (step 6) applies only while no terminal row exists yet. In both cases there is no INVALID. The worker moves only
   its own uncommitted files to `late/` (F0.5 LOST-RACE), and makes no seal.
4. **The finalizer never touches a live worker's files.** Leftover cleanup after TIMEOUT (OQ-13) runs only when the
   slot work lock is acquirable. While the lock is held, cleanup is deferred. Deferred cleanup has no effect on any
   decision: leftovers on a TIMEOUT slot are tolerated and never selectable (F3 table).
5. **Finalizer serialization.** Two finalizers racing need no lock: the journal transaction gives exactly one
   terminal row, and the loser gets LOST-RACE at 4c.
6. **Unchanged:**
   - F5.2-F5.5 lock mechanics, for the work lock and for stage and stop locks;
   - stage recovery (F4.7), which still requires the stage lock to be acquirable;
   - "no check-then-act liveness query" still holds, because no decision reads liveness.
7. **Acceptance (added to F10):**
   - A real child process holds `slot-<s>` and stays alive and blocked past D. A competing finalizer at D appends
     TIMEOUT. The child's later QUALIFIED request is LOST-RACE (4c), whatever its R, with no seal and no INVALID.
     The child's files are not moved while it lives.
   - The same with R < D and J after D: if TIMEOUT committed first, TIMEOUT stands (first terminal wins).
   - Two finalizers at D: exactly one TIMEOUT row.

## E2. Post-START seals are journal-committed stages (PLAN-2, A3-PR1-1; amends F1, F4.8, OQ-14; replaces rev 2's E2)
1. **A seal is a stage.** Each post-START close's seal is an F4 stage with subject `stage/seal/<close date>`.
   - kind single; member `seals/<close>.json`;
   - envelope inputs: the selected QUALIFIED line and its tree detail;
   - request_policy null.
   It uses F4.1–F4.7 unchanged: INTENT, then staging, then PREPARED (canonical commitment of the exact seal bytes),
   then publication, then CREATED, with recovery from staging under the stage lock. The opening seal stays the
   `opening` stage.
2. **When a seal stage may start (F0.5 step 5 for STAGE-INTENT `seal/<c>`).** Only while the trial is ACTIVE, and only
   when close c is **determined**: its first QUALIFIED slot is committed and every earlier slot of c is terminal.
   Otherwise the request is refused with no row. The selected QUALIFIED is that first one; another choice is
   INVALIDATE (contradictory-stage). That check sits at F0.5 step 4a: the INTENT's envelope names the QUALIFIED
   line, and the transaction compares it with the first QUALIFIED of c in the rows it re-read.
3. **The decision is atomic with every terminal transition.** The F0.1 transaction (BEGIN IMMEDIATE on the mailbox
   sqlite file) re-reads, in the same transaction:
   - the journal rows;
   - the trial's ACK rows, including any CLOSE, which Codex writes into the same file.
   So the state checks in F0.5 steps 2, 3 and 5 are serializable with TRIAL-INVALID, TRIAL-STOP and CLOSE.
   - Assumption, made explicit (trusted-writer model, ruling 6): Codex issues every ACK, CLOSE included, as a row of
     that same mailbox sqlite file, through its single-row INSERT.
   - A CLOSE recorded anywhere else is not an ACK (E4) and is not serialized. No
   lock and no post-write re-read is involved. A seal stage's INTENT, PREPARED and CREATED each follow F0.5 step 3
   (INVALID: LOST-RACE, no work) and step 2 (CLOSED: refuse). A PREPARED or CREATED that is not ACTIVE is decided
   by the transaction.
4. **What "no seal after STOP" means.** "Publication" is the committed decision (PREPARED), not the file write.
   - A seal is authoritative only through its own CREATED row: seal/<c> is CREATED, and the file equals the
     PREPARED member.
   - No seal INTENT or PREPARED can commit outside ACTIVE (2, 3).
   - A file written into s1_out after a concurrent INVALID or CLOSE, for a PREPARED decided while ACTIVE, is a
     materialization of that earlier decision. In INVALID or CLOSED it carries no authority and is never read.
   - A seal file with no PREPARED row is a violation (registration-artifact), in every state.
5. **The STOP prefix is frozen atomically (F0.5 step 5 for TRIAL-STOP, added).** Inside its own transaction,
   TRIAL-STOP is refused with no row unless every close determined by the rows in that same transaction (seq <
   the new STOP seq) has a CREATED seal stage.
   - A QUALIFIED arriving between the stop operation's work and its append is inside that check.
   - So STOP never commits with a determined but unpublished seal in its prefix, even when the chosen stop record
     is unchanged.
   - The stop operation runs every pending seal stage first, then appends TRIAL-STOP. A refusal means: run the
     missing seal stages and retry (no INVALID).
   - It never waits on a worker's work lock (E1).
   - The fence covers post-START closes only. The opening close is sealed by the `opening` stage, which is CREATED
     before START by construction.
   - The fence covers every determined close in the prefix, including closes after the stop close chosen by the
     stop record. It only guarantees that their seals exist. Which closes the score uses is still decided by the
     stop record and the STOP prefix rule, and the BLK-3 stop dispositions are unchanged by it.
   - The stop operation retries a refused TRIAL-STOP at most 3 times per invocation. It then returns with no row
     (not INVALID), and the next invocation tries again. Liveness of that next invocation is a scheduler matter
     (R-3, OPEN).
6. **After the STOP.** Seal INTENT is refused (F1: not ACTIVE). Every seal CREATED before the STOP is a required
   member. Missing, changed or unparseable means INVALIDATE (stage-replaced), and it is never recreated. A seal
   stage with INTENT or PREPARED but no CREATED at STOP cannot exist (5).
7. **Removed.** `seals_checked`, the "published-committed" set and the stop-lock publication protocol of rev 2 are
   replaced by 1–6. The stop lock remains only the F5 lock of the stop operation.
8. **Acceptance:**
   - barrier: ACTIVE read, then a concurrent TRIAL-INVALID commits, then the seal stage's PREPARED is LOST-RACE.
     No seal is decided, and any file present carries no authority;
   - the same barrier with a Codex CLOSE committed in the same sqlite file: PREPARED is refused;
   - the stop operation finishes its seal pass, then a later-close QUALIFIED commits (determining that close)
     before TRIAL-STOP with an unchanged stop record: TRIAL-STOP is refused; after the seal stage, STOP commits;
   - publish-first and STOP-first orders;
   - a deleted CREATED seal after STOP: INVALID, never recreated;
   - a seal file with no PREPARED: INVALID;
   - a post-STOP seal INTENT: refused.

## E3. BLOCKED is a pre-INTENT refusal record, closed by Codex (OQ-0; amends F4.1, the F4 stage table, F4.9, F7.5)
1. **When.** The prereg command evaluates the existing BLOCKED reasons (`_blocked_reasons`: coverage, and pre-START
   unit or identity actions on symbols held at START).
   - It does so after its gates and before the prereg STAGE-INTENT.
   - It uses only committed inputs: the CREATED audit tree, the CREATED opening seal and receipt, and plan.json.
   - It is a pure function of those inputs, so every re-run gives the same result.
2. **Record.** If reasons exist, it publishes `s1_out/blocked.json` exclusively and refuses with no journal row and no
   prereg INTENT.
   - Content: the existing fields `status`, `reasons` and `recorded_utc` (the observation time), plus `trial_id`
     (E5.4).
   - This is a declared exception to F4.1's "INTENT before any computation for g": the BLOCKED evaluation is a
     pre-INTENT gate over committed inputs only.
   - blocked.json is a declared pre-INTENT refusal record. It is not a stage member, and the F4 stage-state rule
     "no INTENT: any artifact for g is a violation" does not apply to it.
   - Its absence or deletion changes nothing, because the deterministic re-check re-blocks.
3. **State.** The journal state stays ACTIVE. BLOCKED is never INVALID: no TRIAL-INVALID row is appended for it.
   - Every later prereg attempt refuses the same way, so START, captures and scoring are unreachable.
   - The operator re-registers with a new plan, which means a new trial_id after CLOSE.
4. **Closure.** F7.5 gains the reason `BLOCKED`: `S1-CLOSE-ACK … reason=BLOCKED evidence_sha256=<h>`.
   - h = sha256(c.canonical({"trial_id", "reasons"})), the deterministic recomputation. It is not the file bytes,
     which include `recorded_utc`.
   - So deleting and re-creating blocked.json never changes h and never re-opens a closed trial.
   - Codex issues the CLOSE only after checking, against that trial's own root, that blocked.json's `reasons`
     equal the recomputation from that trial's committed inputs.
   - S1 never recomputes a historical CLOSE's evidence from any directory (A3-PR1-2). A BLOCKED CLOSE is validated
     like every CLOSE, by F7.5 grammar, prev, bundle and role/key (E4), under the ruling-6 trust in Codex's
     issuance.
   - Closure is monotone: once a valid CLOSE is in the mailbox, that trial is closed for every caller, every root
     and the rootless lookup. No local file state can re-open it.
   - A BLOCKED close keeps the trial classified BLOCKED, distinct from INVALID.
5. **Unchanged.** The score's existing BLOCKED re-check (`_score` step 2) is unchanged. It can only fire if a
   prereg existed, which BLOCKED prevents.
6. **Acceptance:**
   - BLOCKED inputs: blocked.json written, no journal row, the state is ACTIVE, zero captures, provider requests and
     valuation calls;
   - deleting blocked.json and re-running gives the same refusal and an identical recomputation;
   - two-root lifecycle: root A is BLOCKED, then a valid BLOCKED CLOSE, then root B runs write_plan and gets its
     AUDIT-ACK. B is the unique open trial and A stays closed, both rootless and from either root;
   - Codex's issuance check: wrong reasons for A means no CLOSE is issued (procedural, Codex-side);
   - a non-BLOCKED prereg is unaffected.

## E4. ACK candidates come only from the official channel (OQ-6, PLAN-5; amends F6.1, F7.5, F10)
1. **Candidate.** A line in a message with sender `codex`, recipient `claude` and key `experiments-prereg` that
   starts at the beginning of a line with `S1-` and whose first token ends in `-ACK`. This applies to every ACK
   kind, CLOSE included.
2. **Not a candidate.** Lines in any other message (another sender, recipient or key), and lines not at the start
   of a line, are ignored. They never close, authorize or refuse anything. Quoted drafts in peer messages are
   therefore harmless, and no "never paste a token" rule exists.
3. **Malformed candidate.** A candidate that does not parse against its kind's field list:
   - if its trial_id can be parsed, it refuses that trial's commands and escalates. A trial_id can be parsed exactly
     when the line's second whitespace-separated token is `trial_id=<canonical lowercase uuid4>`;
   - otherwise it refuses all trial-bound commands and escalates.
   This is the same disclosed cross-trial availability cost as OQ-4, limited to Codex's own channel.
4. **F7.5 refusal list clarified.** "Its role or key is wrong" now means a CLOSE-looking line outside the official
   channel. It is not a candidate: it is ignored, does not close, and does not refuse. The other F7.5 conditions
   (prev, before AUDIT, bundle, duplicate) still refuse.
   The F10 example "a wrong-role … CLOSE refuses with zero callbacks" becomes: "a wrong-role CLOSE is ignored: the
   trial stays open and its commands follow their gates". It is tested next to an arbitrary-draft message and a
   historical other-trial message.
5. **CLOSE schema (OQ-5 ruling).** CLOSE carries exactly the F7.5 fields. It carries no `journal_seq` or
   `journal_head_sha256`, as a specific exception to the F7.1 "every ACK after the AUDIT-ACK" rule.

## E5. Recorded clarifications from the OQ rulings (no outcome changes)
1. **OQ-1, OQ-31 (diagnostic reason).** The INVALID reason `established-violation` may be used only for violations
   that earlier addenda already define as terminal: semantic receipt, process binding, fence or bridge, corrupt seal
   record.
   - The committed observation record names the exact subtype and legacy reason.
   - It is persisted externally first when writable, then as local evidence.
   - The predicates are unchanged.
2. **OQ-11 (report content).** The capture report is final before J. Seal and stop presentation may be written to
   `captures/<day>/<slot>.after.json`. That file is display-only and optional: it is never authority for seal
   membership or integrity, and deleting or changing it alters no decision.
3. **OQ-18 (lead).** No numeric OPENING-ACK lead is registered. The OPENING-ACK must causally precede the START
   attestation, which must be strictly before planned START.
4. **OQ-36 (trial_id representation).** Raw provider pages and list-shaped derived files keep their source shape and
   gain no trial_id field. They are bound to the trial through typed trial/op commitments (PREPARED members,
   provenance). Every generated identity-bearing metadata record contains the uuid4 trial_id.
5. **OQ-17 (evidence manifest).** The S1 live-file check reconstructs the canonical evidence-manifest prefix for
   journal_seq and compares its sha256 with the OPENING-ACK `evidence_manifest_sha256`. It does not read Codex's
   review folder. Byte format, used identically by Codex when issuing:
   ```
   c.canonical({"trial_id", "journal_seq", "journal_head_sha256",
                "files": {relpath: sha256}})
   ```
   - `files` covers these, for rows with seq <= journal_seq:
     - plan.json and `opening_receipt.json`;
     - every CREATED audit member;
     - every file of every QUALIFIED or FAILED tree;
     - every CREATED stage member;
     - the staging `intent.json` and `prepared.json` of every stage with an INTENT or PREPARED row (OQ-35).
   - Relpaths are relative to s1_out. Staging files use the key `staging/<stage>/<name>`, where <stage> is the
     stage name. For a seal stage that name is `seal/<date>`, so the key is nested:
     `staging/seal/<date>/intent.json`. That key is a label for
     the real file `<root>/s1_staging/<trial_id>/<stage>/<name>`, outside s1_out. Both sides hash that real file.
   - Each sha256 is of the live bytes at check or issuance time. A damaged member is caught first by the F3 and F4
     checks (stage-replaced or registration-artifact). The manifest's own INVALIDATE therefore covers a wrong hash
     or a wrong membership while the files are otherwise valid.
   - Map keys are sorted, as c.canonical does.
   - A wrong hash or a wrong membership, with otherwise valid files, is INVALIDATE (registration-artifact).
6. **Opening window (consequence of literal F7.2(b), OQ-37 ruling).**
   - Once the opening STAGE-INTENT exists, a SLOT-INTENT for a later opening-close slot is refused with no row by
     the opening gate. That slot ends MISSED at its E.
   - So the OPENING-ACK can be issued only after the E of the last scheduled opening-close slot.
   - The START attestation, RUN-ACK and prereg then have to fit between that point and planned START.
   - This is a disclosed operational constraint, not a change of rule. Widening the window would need its own
     amendment.
7. **OQ-32 (capture bytes).** The QUALIFIED tree's capture files include `backup.sqlite3` by its own sha256. No
   transitive-only binding is used.

## E6. Process
1. A scoped Codex check of this erratum together with the revised plan. Scope: E1-E5 and the plan's resolution of
   PLAN-1..6 and the OQ rulings.
2. Operator adoption.
3. A byte-frozen copy in research/s1/docs.
4. Code starts task by task.
No registration, audit, START, scheduler or live step until a later CONSENSUS. c9b4322 stays rejected. R-3 stays
OPEN / INSUFFICIENT_EVIDENCE.
