# S1 Addendum 3 (external trial journal) Implementation Plan — revision 1

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Revision 1 answers Codex final f045bd31 (FORUM-S1-A3-PLAN, CHANGES_REQUIRED on revision 0, sha256 81116f87…).
The review records are in `C:\Users\gl450\.coordination\trading_app\s1_a3_plan_codex_review_20261103\`.

It also implements Erratum 1 draft revision 1 (E1–E5). That draft is
`C:\Users\gl450\.coordination\trading_app\.sdd_s1\s1_design_v5_addendum3_erratum1_draft_r1.md`, sha256 bee16ded…
of the draft; it supersedes rev 0 (4dc7a3c5…). It is not yet adopted.

**Controller note (erratum draft revision 2).** The erratum under review is now draft revision 2,
`s1_design_v5_addendum3_erratum1_draft_r2.md`, sha256
`b03b760dcded5b5d6ede5981e2c6b643d7647edb5bcedfbd2c9ba723cae1ef28`. It differs from revision 1 only by three
clarifications that this plan already implements, which the drafter raised as alignment points:
- E2.4: `seals_checked` lists every seal file under `s1_out/seals/`;
- E3.4: a BLOCKED CLOSE that cannot be recomputed fails closed;
- E5.5: staging keys label the real files under `<root>/s1_staging/…`, and the manifest hashes live bytes.

References below to "draft revision 1" read as revision 2 for these three items.

**Every Codex ruling below is a requirement. There is no "implement the proposed reading until Codex disagrees"
default anywhere in this plan.** Items that still need a decision are listed under "Blockers", together with the
tasks they stop.

## Revision 1 changes
Each line gives the change and the finding, ruling or erratum item it answers. "Row n" means a row of the
requirement map. Row numbers 1–255 are kept; rows 256–333 are new. R1-33..R1-36 align the plan with Erratum 1
draft revision 1 (bee16ded…).

| # | change | answers |
|---|---|---|
| R1-01 | The finalizer's TIMEOUT/MISSED never takes, waits for or tests the slot work lock; the decision is the journal transaction alone. Leftover cleanup runs only when the work lock is acquirable. Task 7 code and tests rewritten. Rows 12, 45, 50, 130 and 205 rewritten; rows 256–259 added. | PLAN-1, E1, OQ-12, OQ-13, OQ-23 |
| R1-02 | No seal is published in STOPPED/INVALID/CLOSED, whatever the QUALIFIED seq (E2.1). Seal publication holds the stop lock across read-state, publish and re-read (E2.3); a held stop lock means no change and pending (E2.6). A published-committed seal missing after STOP is INVALID, never recreated (E2.2/E2.4). The stop operation publishes every determined unpublished seal under the stop lock, re-reads, then appends TRIAL-STOP (E2.5). Tasks 7 and 11 rewritten. Rows 55 and 187 rewritten; rows 260–263 added; rows 320–325 follow E2.7's wording. | PLAN-2, E2 r1 (E2.1–E2.7), OQ-14 |
| R1-03 | Required seal membership is derived from committed history only: each pre-J report's `seals_checked` (bound by the QUALIFIED tree), each committed PREPARED commitment's `seals_checked` (R1-34), the first-QUALIFIED rows, and the F2 stop record. It is never derived from `after.json`. `_report_seals`/`_capture_seal_problems` are rewritten to that. Rows 264–266 added. | PLAN-4, E2.4, E5.2, OQ-11, OQ-14 |
| R1-04 | `backup.sqlite3` is in the QUALIFIED tree by its own sha256 (`CAPTURE_TREE`). Backup change and deletion are evidence-table cases. Rows 70 and 77 rewritten; row 267 added. | PLAN-4, E5.6, OQ-32 |
| R1-05 | start_attest stays single (`attest_start.json`). `opening_books.json` is a deterministic derived input, published before the INTENT by the existing `_opening_books`, hash-bound in the envelope and in the record, and RUN-ACK-bound. Task 8 TABLE and Task 10 code rewritten. Rows 85 and 104 rewritten; row 268 added. | PLAN-3, OQ-15 |
| R1-06 | F7.2(b) is literal: every scheduled slot of the opening close must have a terminal row within the OPENING-ACK's journal prefix. Earliest-success selection (F3) is tested separately. The conftest issues the OPENING-ACK only after the opening close's W slot is finalized. Rows 81 and 152 rewritten; rows 269–270 added. | PLAN-3, OQ-37 |
| R1-07 | BLOCKED follows E3 r1: a pre-INTENT refusal record (a declared F4.1 exception), ACTIVE, no TRIAL-INVALID, CLOSE reason `BLOCKED`. blocked.json carries `status`, `reasons`, `recorded_utc` and `trial_id`. The CLOSE evidence is h = sha256(c.canonical({trial_id, reasons})) of the deterministic recomputation (`s1_run.blocked_close_evidence`), never the file bytes, so deleting or re-creating blocked.json never re-opens a closed trial. Marked "pending Codex acceptance of E3"; Task 10's BLOCKED step is not committed before adoption. Row 121 rewritten; rows 271–274 and 332 added; row 273 moved to Tasks 4 and 10. | PLAN-3, OQ-0, E3 r1 |
| R1-08 | ACK candidates come only from codex->claude `experiments-prereg` at line start. Other lines are ignored. A malformed candidate refuses its own trial when the trial_id parses (E4.3 r1 grammar: the second whitespace-separated token is exactly `trial_id=<canonical lowercase uuid4>`), otherwise all trials. A wrong-role/key CLOSE is ignored. Task 4 and Task 5 code and tests rewritten. Rows 158 and 238 rewritten; rows 275–278 added. | PLAN-5, E4, OQ-5, OQ-6 |
| R1-09 | The OPENING-ACK `evidence_manifest_sha256` is compared with the reconstructed canonical prefix manifest in E5.5's exact format and membership (Erratum 1 r1; it includes the staging `intent.json`/`prepared.json` as `staging/<stage>/<name>`). A wrong hash or wrong membership is INVALIDATE (registration-artifact) per F7.3, checked in `verify_opening_ack` and by every gate after the OPENING-ACK. BLK-2 is resolved. Rows 151 and 154 rewritten; rows 279–280 added (INVALIDATE). | PLAN-4, OQ-17, E5.5 r1 |
| R1-10 | The no-circularity oracle is now data independence: member bytes are identical across runs whose PREPARED/CREATED clocks differ, and same-tick clocks are allowed. It replaces the substring test. Rows 15 and 89 rewritten. | coverage 15/89 |
| R1-11 | Damaged-member coverage is extended to raw backup bytes, the opening receipt and the final-snapshot report, alongside metadata. Rows 117 and 215 rewritten; rows 281–282 added. | coverage 70/77, 117/215 |
| R1-12 | Matrix: 10 points, which are 9 commitment points (audit … score) plus the OPENING-ACK point. "Audit tree" means every file under `s1_out/audit/`. INTENT/PREPARED boundaries are covered by the per-stage state-table tests, and the matrix scope claim says so. Task 14 rewritten. Row 255 rewritten; row 283 added. | PLAN-6, coverage 255, OQ-24 |
| R1-13 | New Task 15: Cosmic Ray on the changed critical modules, plus targeted semantic mutants. Survivors, timeouts and untested are reported separately, with no score target. Rows 284–297 added. | PLAN-6 |
| R1-14 | Hypothesis is pinned: `derandomize=True`, `@seed(20261103)`, a `DirectoryBasedExampleDatabase` under `s1_evidence/a3/hypothesis_db/`, and every minimized failure kept as an `@example`. The scope is declared as slot-table cases only. Row 48 rewritten; row 298 added. | PLAN-6, coverage (Hypothesis) |
| R1-15 | The OQ-3 op-reuse check runs after step 4b, so a repeated opening row stays `repeat-attempt`/`repeat-stage`. Task 2 rewritten; row 299 added. | OQ-3 |
| R1-16 | The stop record's dispositions are shown as examples before the shape is pinned (lots-earliest, lots-not-later, TIMEOUT, NO-VALID-SEAL, pending exclusion, deadline-instant eligibility). Task 11 Steps 4+ wait on BLK-3. Rows 300–305 added. | OQ-8 |
| R1-17 | A `_score` ABORTED-INVALID from an established integrity violation persists TRIAL-INVALID (`registration-artifact`, with the exact reasons in the observation). The report stays in staging, with no PREPARED. INSUFFICIENT/INCONCLUSIVE are unaffected. Task 13 rewritten; rows 306–307 added. | OQ-28 |
| R1-18 | `established-violation` is external first: TRIAL-INVALID, then the local abort. The observation records the subtype and the legacy reason, and the predicates are unchanged. Task 6 rewritten; row 308 added. | OQ-1, OQ-31, E5.1 |
| R1-19 | Lock and subject names are validated against a strict grammar (no traversal or cross-trial aliasing). Row 309 added. | OQ-23 |
| R1-20 | Boundary tests at s−1µs, s, E−1µs, E, E+1µs separate no-work from an authorized claim/failure. Row 310 added. | OQ-33 |
| R1-21 | The claim names its capture directory (`capture_dir`), and the F3 in-flight check binds the directory to that claim. Row 311 added. | OQ-10 |
| R1-22 | Cross-trial substitution of a raw page or list-shaped member is caught through the typed commitment. Row 312 added. | OQ-36, E5.4 |
| R1-23 | Gate-generated TRIAL-INVALID rows use a fresh op and actor, never an input operation's op. Row 313 added. | OQ-2 |
| R1-24 | The final snapshot is bound by the SCORE-ACK; a missing or changed report makes the score INVALID, never an economic fallback. Row 314 added. | OQ-16 |
| R1-25 | The sampled-history manifest is canonical and deterministic, and later completions cannot change it. Row 315 added. | OQ-29 |
| R1-26 | OPENING-ACK is causally before the attestation, and the attestation is before START. No numeric lead. Row 316 added. | OQ-18, E5.3 |
| R1-27 | `prepared.json`/`intent.json` lifecycle declared and tested (deletion or change after CREATED). Row 317 added. | OQ-35 |
| R1-28 | `opening_receipt_sha256` is the raw file hash and is tested as distinct from the fingerprint. Row 318 added. | OQ-30 |
| R1-29 | Valid pagination and empty families stay non-anomalous (positive controls next to the Structural cases). Row 319 added. | Codex reply P-4 |
| R1-30 | E1–E4 acceptance tests are added verbatim as map rows 320–330. | E1.7, E2.5, E3.6, E4.4 |
| R1-31 | Erratum 1 is pinned in DOC_PINS and the bundle (Task 1) as `docs/s1_design_v5_addendum3_erratum1.md`. Its hash is ERRATUM1_SHA256, filled from the adopted byte-frozen copy of draft revision 1 (bee16ded…, which supersedes rev 0, 4dc7a3c5…). Task 1 cannot be committed before adoption. Row 1 rewritten. | erratum header, E6 |
| R1-32 | The OQ section now carries each ruling as a requirement; the revision-0 proposals are removed. Blockers are listed. | PLAN-3 (no default), all rulings |
| R1-33 | Aligned with Erratum 1 r1 E5.5: BLK-2 is resolved; `evidence_manifest` implements the exact E5.5 format and membership (including the staging `intent.json`/`prepared.json` as `staging/<stage>/<name>`); a mismatch is INVALIDATE (registration-artifact) via `opening_manifest_check`, called by `verify_opening_ack` and by every gate after the OPENING-ACK. Rows 279–280 changed to INVALIDATE and a staging-membership case. | E5.5 r1, F7.3 |
| R1-34 | Aligned with E2.4 r1: every PREPARED commitment carries `seals_checked` (Task 8 `commitment`); `required_seals` = the published-committed set (QUALIFIED trees' and committed PREPAREDs' `seals_checked`, plus the stop record); `committed_commitment` moves to Task 8. Row 331 added; rows 265–266 reworded. | E2.4 r1 |
| R1-35 | Aligned with E5.6 r1: the opening-window consequence (later opening-close SLOT-INTENT refused with no row once the opening INTENT exists, MISSED at its E, no OPENING-ACK before the last opening-close slot's E) has its own test. Row 333 added. | E5.6 r1, OQ-37 |
| R1-36 | Aligned with E4.3 r1: the attribution grammar is the erratum's, with boundary tests (whitespace, uppercase, position, version). Row 278 extended. | E4.3 r1 |

**Goal:** Implement Addendum 3 rev 5 in the offline S1 toolchain. The external mailbox journal becomes the authority
for trial, slot and stage state. Stages run as INTENT -> PREPARED -> CREATED, under ownership locks, with a
deterministic request policy in the collector. The finalization chain and the score become journal-bound. Nothing
is registered, audited, started or scheduled.

**Architecture:** Five new bundle modules carry the new rules:
- `s1_journal.py`: F0 line grammar, chain, precedence and the one INSERT.
- `s1_locks.py`: F5 Windows ownership locks.
- `s1_trial.py`: F6/F7 identity, ACK reading and the first gate of every command.
- `s1_slot.py`: F3 slot rows and the evidence table.
- `s1_stage.py`: F4 stage engine, staging, recovery and the stage-state table.

The existing modules change only where Addendum 3 governs:
- `s1_collect`: request policy, audit and final as stages.
- `s1_checkpoint`: slot worker and finalizer on the journal; opening stage.
- `s1_run`: start_attest, prereg, stop_attest and score stages.
- `s1_seal`: the F2 stop record.
- `s1_gates`: field-by-field ACK verification.
- `s1_common`: bundle pins and ACK token texts.

Legacy file-level gates stay in place as extra detectors that can only refuse or invalidate; they never override the
journal (OQ-19).

**Tech Stack:**
- Python 3.12.12 (isolated testenv), sqlite3, ctypes + msvcrt (Windows locks).
- httpx 0.28.1 (`MockTransport` only in tests).
- pytest 8.3.3, hypothesis 6.112.1.
- No new dependencies.

**Spec:** `research/s1/docs/s1_design_v5_addendum3.md`, Addendum 3 rev 5, sha256
`d9dd37595f0e0e73098ade1b8548e8cda2dc47fe49243f4d44735508029b9fb2`. Codex APPROVE-ADDENDUM is mailbox `c85a0009`,
recorded in `C:\Users\gl450\.coordination\trading_app\s1_addendum3_r5_check_codex_20261102\REVIEW.txt`. The
interpretations recorded there are conditions of this plan; see "Codex conditions".

**Erratum 1 governs over Addendum 3 where they differ.** Its draft is revision 1, sha256
`bee16deda794a652098f9ae79ac1d5357ca6cb63b20735ed32d786a74980c63e` (rev 0, 4dc7a3c5…, is superseded). The adopted
byte-frozen copy of revision 1 (or of whatever revision Codex and the operator adopt) will be
`research/s1/docs/s1_design_v5_addendum3_erratum1.md`, with hash ERRATUM1_SHA256 filled from that copy. Erratum
items E1–E5 are requirements of this plan, each marked "pending Codex acceptance of E1–E5". Under the erratum's E6,
no task starts before the erratum is adopted.

The spec builds on these documents, which stay byte-identical. Where they differ, Addendum 3 governs:
- `s1_design_v5.md` (33c32840…) and `s1_spec.md` (4b882f52…);
- Addendum 1 rev 3 (6cb89e36…);
- Addendum 2 rev 1 (c7f0c3ff…).

The conventions come from the earlier plan `research/s1/docs/s1_plan.md`. Executors read the spec and this plan
together; the spec's clauses govern.

## Global Constraints
- **Where:**
  - Worktree `C:\Users\gl450\trading_app-s1`, branch `research/s1-shadow-trial`, base head `93f4c3e`.
  - Only files under `research/s1/` change.
  - Never `cd` to another checkout.
- **Python:**
  - Use only `C:/Users/gl450/.coordination/trading_app/testenv/Scripts/python.exe` (3.12.12). Never bare
    `python3` or `python`.
  - Run from the worktree root:
    `PYTHONPATH="research/s1;research/s1/s1_tests" C:/Users/gl450/.coordination/trading_app/testenv/Scripts/python.exe -m pytest -p conftest -p no:cacheprovider <paths> -q`.
- **No live access:**
  - Never run anything against the live app (port 8000).
  - Never open `C:\Users\gl450\trading_app\backend\trading.db`.
  - Never read or print `.env` values.
  - No network. Tests use injected `httpx.MockTransport` clients only, and the conftest network guard (Task 5)
    makes any real transport call fail.
- **Mailbox:**
  - Product code defaults to `s1_common.MAILBOX` (`C:/Users/gl450/.coordination/trading_app/mailbox.sqlite3`).
  - Every test runs against `<tmp_path>/mailbox.sqlite3` (the autouse fixture `s1_tmp_mailbox`). No test or step
    opens the real mailbox.
  - `mailbox.py` (sha256 `92b59ba92be9daddf593962460b904c95052d7d79f1f0914bd77239b00a3191b`) is never modified,
    imported or executed by product code or tests.
- **Journal write (F0.1, verbatim):** "Its only mailbox write is a single-row INSERT inside `BEGIN IMMEDIATE`:
  sender `s1`, recipient `codex`, key `experiments-s1-journal`." No UPDATE, DELETE or ack. All other reads are
  `mode=ro`.
- **Journal line (F0.2, verbatim):**
  `S1-JOURNAL trial_id=<uuid4> seq=<n> prev_sha256=<64hex> kind=<K> subject=<s> detail_sha256=<64hex|absent> op=<32hex> actor=<32hex> at=<YYYY-MM-DDTHH:MM:SS.ffffff+00:00>`
  It is one UTF-8 line with no trailing newline.
- **Frozen pins:**
  - `e1_sim.py` 68f21ab1… and `e1_fetch.py` 401f17de…;
  - documents 33c32840… / 4b882f52… / 6cb89e36… / c7f0c3ff…, plus Addendum 3 d9dd3759…, plus Erratum 1
    (ERRATUM1_SHA256, the adopted copy);
  - registered constants: `MAX_PAGES = 200`, `CA_FIXED = {"region": "us", "data_quality": "all", "sort": "asc",
    "limit": 1000}`, 50-symbol batches, `SCHEDULE_SLACK = 10 min`, `RESOLUTION_TIMEOUT = 30 min`.
- **Prospective only:** no registration, audit, START, scheduler or live step until a later CONSENSUS. R-3 (live
  scheduler timing) stays OPEN.
- **blocked.json** follows Erratum E3 (pending Codex acceptance of E3):
  - a pre-INTENT refusal record; the state stays ACTIVE; no TRIAL-INVALID; CLOSE reason `BLOCKED` with
    h = sha256(c.canonical({trial_id, reasons})); blocked.json carries `trial_id`.
  - Task 10's BLOCKED step is not committed before the erratum is adopted. No TRIAL-INVALID mapping exists.
- **Locks (Erratum E1):**
  - The slot work lock is held by the worker across its whole operation.
  - Slot terminal decisions (QUALIFIED, FAILED, TIMEOUT, MISSED) are arbitrated only by the journal transaction. The
    finalizer never takes, waits for or tests the work lock for a decision.
  - Stage and stop operations keep F5.1.
- **Seals (Erratum E2 r1):**
  - No seal is published unless the trial is ACTIVE, under the stop lock; a held stop lock is pending (E2.6).
  - The stop operation publishes every determined unpublished seal before TRIAL-STOP (E2.5).
  - Every QUALIFIED tree and every PREPARED commitment carries `seals_checked`; those seals are published-committed
    and are never recreated (E2.4). After STOP, seals are only verified.
- **Evidence manifest (Erratum E5.5 r1):** exact format and membership; a mismatch is INVALIDATE
  (registration-artifact), checked at the start attestation and by every gate after the OPENING-ACK.
- **ACK candidates (Erratum E4):** only codex->claude `experiments-prereg` lines at line start.
- **Mutation testing (Task 15):** Cosmic Ray 8.3.15 on the changed critical modules, plus targeted semantic mutants.
  Survivors, timeouts and untested mutants are reported separately. There is no blanket score target.
- **Property tests:** every Hypothesis test uses `derandomize=True`, `@seed(20261103)` and
  `database=DirectoryBasedExampleDatabase("research/s1/s1_evidence/a3/hypothesis_db")`. Every minimized failure ever
  found is kept as an `@example`. Each property's docstring states its actual scope.
- **TDD:**
  - Every task records a **behavioural RED**, obtained against an interface stub that has the final signatures and
    permissive (pre-Addendum-3) behaviour, before the fix.
  - An ImportError, AttributeError or collection error is a **missing-interface** failure. It is labelled as such and
    never counts as a RED.
  - Retrospective tests (the rule already held) are labelled `retro`.
- **Evidence:**
  - Everything goes under `research/s1/s1_evidence/a3/`: `tN_red.txt`, `tN_green.txt`, `tN_full.txt`,
    `tN_old_new.md` and `tN_hashes.txt`.
  - The Codex probe history goes under `research/s1/s1_evidence/a3/codex_probes_historical/`.
- **Commits:**
  - The controller commits and pushes after each task review. The implementer never commits.
  - The controller asserts the HEAD SHA before and after each commit.
  - Every message ends with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- **ACK issuance** is Codex's. S1 code only reads ACKs (mode=ro). The token builders exist for tests and for Codex's
  own cross-check.

## Review Focus
1. **A mailbox write lock held by another process.** Example: Codex running `mailbox.py send` during S1's
   `BEGIN IMMEDIATE`. `sqlite3.OperationalError: database is locked` after the busy timeout must be an outage: no row,
   no work, and no retry under the same intent (F8.3). Test: Task 1 `test_concurrent_append_is_serialized_and_a_busy_mailbox_is_an_outage`.
2. **Codex acking a journal row.** `mailbox.py --role codex ack <id>` runs an UPDATE on `acknowledged` for rows
   addressed to `codex`, which includes S1 journal rows. The journal must ignore the `acknowledged` column. Test:
   Task 1 `test_acknowledged_column_never_changes_the_journal`.
3. **A New York midnight or DST transition between INTENT and the request.** INTENT at 23:59:59.999999 NY, with the
   reservation and requests after midnight, or the fall-back hour. The cutoff is the INTENT's NY date. Tests: Task 9
   and Task 12 `test_cutoff_is_the_intent_new_york_date_across_midnight` (DST variant parametrized).
4. **A crash after partial publication.** Some members are already in s1_out when CREATED fails. Recovery publishes
   only the missing members and never overwrites. Test: Task 8
   `test_recovery_publishes_only_missing_members_and_never_overwrites`.
5. **A third process holding the lock file.** An antivirus or indexer may hold the file with a sharing violation. That
   reads as "held" (pending, no verdict), never as "free". An I/O error reads as neither. Test: Task 3
   `test_sharing_violation_from_any_holder_is_held`.

---

## Codex conditions (recorded interpretations of APPROVE-ADDENDUM c85a0009, treated as requirements)
- **C-a Manifest projection.**
  - The collector manifest's `files` map is keyed by basename: `p.name` for `d/*.json` minus `manifest.json`, as
    `s1_collect._run_attempt` writes it. Its `pages` map is keyed by path relative to s1_out (`_page_hashes`).
  - Equivalence: prefix every `files` key with `audit/` or `final/`, then take the union with `pages`. The result
    must equal `PREPARED.members` minus the manifest's own relpath. The function is `s1_stage.manifest_projection`
    (Task 8). It is used for audit (Task 9) and final (Task 12).
  - The old manifest shape is preserved byte-for-byte apart from the disclosed `publication_cutoff` source and the
    staging location.
  - Score has no collector manifest. Its two files, `score/attempt.json` and `score/s1.json`, are bound directly by
    the score PREPARED commitment (Task 13). No synthetic score manifest is created.
- **C-b Cross-midnight cutoff.** INTENT before New York midnight, reservation and requests after. The INTENT's NY date
  governs and appears as `publication_cutoff` and as every CA `end`. Tests are in Task 9 (audit) and Task 12 (final).
- **C-c Code verification.**
  - Malformed journal kinds and fields are rejected, both as rows read (chain integrity, refuse and escalate) and as
    requests (no row).
  - Every gate is applied under the required rules: the decision inside the `BEGIN IMMEDIATE` transaction on the state
    re-read there (Tasks 1 and 2), and the ownership lock taken before the journal read (Tasks 6, 7, 8, 11).
- **C-d blocked.json.**
  - Revision 0 was DEFERRED. f045bd31 ruled OQ-0 HOLD: BLOCKED is distinct from INVALID, and no interim policy was
    approved.
  - Erratum E3 now gives the requirement (pending Codex acceptance of E3).
  - The TRIAL-INVALID `pre-start-blocked` mapping is not implemented.
- **C-e Score-aborted and INTENT cutoff are prospective rules.** Each has a positive path and a failure path with
  isolated evidence (separate tests and separate evidence files):
  - Task 9 and Task 12: `t9_cutoff_*.txt`, `t12_cutoff_*.txt`.
  - Task 13: `t13_score_positive.txt`, `t13_score_aborted.txt`.

## Blockers (items that still need a decision; the named tasks cannot start, or cannot be committed, until it is made)
- **BLK-1: Erratum 1 adoption.**
  - What is needed: a scoped Codex check of E1–E5 with this plan, operator adoption, and a byte-frozen copy at
    `research/s1/docs/s1_design_v5_addendum3_erratum1.md` whose sha256 is ERRATUM1_SHA256.
  - Effect: under E6, no task starts before adoption. Task 1 pins the hash, so Task 1, and with it every later
    task, cannot be committed before adoption.
  - Task 10's BLOCKED step (E3) and every E1/E2/E4 test depend on it.
- **BLK-2: RESOLVED by Erratum 1 r1 E5.5.** The evidence-manifest byte format and membership are now fixed by
  E5.5 and implemented exactly in Task 10 (`s1_trial.evidence_manifest`). A wrong hash or wrong membership is
  INVALIDATE (registration-artifact), per F7.3 (rows 279–280). Nothing waits on BLK-2 any more. The number is kept
  so that references stay stable.
- **BLK-3: the stop record's dispositions (OQ-8 AMEND).**
  - Codex requires each stop disposition to be shown against the frozen calendar, deadline and pending rules before
    the shape is pinned.
  - Task 11 Step 2a produces `a3/t11_dispositions.md`: worked examples for lots-earliest, lots-later-not-chosen,
    TIMEOUT, NO-VALID-SEAL, pending exclusion and deadline-instant eligibility, plus their tests.
  - Blocks: Task 11 Steps 4–7 (TRIAL-STOP and the stop.json shape) until Codex accepts the dispositions.
  - Tasks 12–14 depend on Task 11.

No other open question remains. Every other OQ below carries its f045bd31 ruling as a requirement.

## Codex rulings (f045bd31) on OQ-0 … OQ-38 — requirements of this plan
Each item gives the ruling, then what the plan does. The revision-0 proposals are removed. Where a ruling amended
or rejected a proposal, the affected task code and map rows are rewritten (see "Revision 1 changes").

- **OQ-0 (blocked.json): HOLD, now Erratum E3.**
  - No interim was approved. E3 now gives the requirement:
    - BLOCKED is evaluated after the gates and before the prereg STAGE-INTENT, from committed inputs only;
    - blocked.json is a declared pre-INTENT refusal record, not a stage member;
    - the state stays ACTIVE and no TRIAL-INVALID is appended;
    - blocked.json carries `status`, `reasons`, `recorded_utc` and `trial_id` (E3.2 r1);
    - CLOSE gains reason `BLOCKED`, with `evidence_sha256` = h = sha256(c.canonical({"trial_id", "reasons"})) of
      the deterministic recomputation, not the file bytes (E3.4 r1).
  - Pending Codex acceptance of E3. Task 10's BLOCKED step and the CLOSE `BLOCKED` reason (Task 4) are not
    committed before adoption (BLK-1). Rows 121, 271–274 and 332; Tasks 4 and 10.
- **OQ-1 (subjects, INVALID reasons): AMEND.**
  - The typed subject prefixes are kept: `slot/<UTC %Y%m%dT%H%M%SZ>`, `stage/<name>`, `trial`, `reason/<code>`.
  - The reason taxonomy is frozen as {contradictory-completion, contradictory-finalizer, contradictory-stage,
    repeat-attempt, repeat-stage, stop-conflict, stage-incomplete, stage-replaced, provider-structural,
    score-aborted, bundle, LOST, registration-artifact, established-violation}.
  - `established-violation` is used only for the already-terminal A9.2 violations (receipt, binding, fence or
    bridge, corrupt seal record). Its observation names the exact subtype and the legacy reason, and the predicates
    are unchanged (E5.1).
  - Any change of an outcome or of a reason's meaning needs an erratum. Tasks 1 and 6.
- **OQ-2 (detail presence, INVALID record): APPROVE WITH CONDITIONS.**
  - The detail-presence table: `absent` for SLOT-INTENT/TIMEOUT/MISSED, required otherwise.
  - The INVALIDATE record is `{"reason", "requested": {...}}`, and the gate-observation record is canonical.
  - A gate-generated TRIAL-INVALID uses a fresh op and actor (`j.new_nonce()` for both), never the op of an input
    operation.
  - A precedence INVALIDATE repeats the requested row's op, which is the operation being invalidated, not a
    successful one.
  - The first external INVALID reason is preserved. Row 313; Tasks 1, 2 and 5.
- **OQ-3 (reused op): APPROVE.**
  - A reused opening-row nonce is a malformed request: REFUSE, no row.
  - The check runs after step 4b, so a repeated subject is still `repeat-attempt`/`repeat-stage`. Row 299; Task 2.
- **OQ-4 (foreign rows under the journal key): APPROVE WITH CONDITIONS.** These fail closed and escalate for every
  trial. The cross-trial availability cost of an un-attributable malformed journal-key row is disclosed. The rule is
  limited to the writer-only journal key and never applies to ordinary messages. Task 1.
- **OQ-5 (ACK field order): APPROVE WITH CLARIFICATION.**
  - The seven ACK_FIELDS lists are accepted, as preserved in `reviewed-ack-fields.json`.
  - CLOSE carries exactly the F7.5 fields, with no `journal_seq` or `journal_head_sha256`. This is a recorded
    exception to the F7.1 "every ACK after the AUDIT-ACK" rule (E4.5).
  - Accepting the field names issues no ACK. Task 4.
- **OQ-6 (ACK candidates): AMEND, now Erratum E4.**
  - Candidates are only lines at line start in codex->claude `experiments-prereg` messages whose first token is
    `S1-…-ACK`, for every kind including CLOSE. Everything else is ignored: it never closes, authorizes or refuses.
  - A malformed candidate refuses its own trial when its trial_id parses, otherwise all trial-bound commands. Both
    escalate.
  - A wrong-role or wrong-key CLOSE is ignored. There is no "never paste a token" rule.
  - Pending Codex acceptance of E4. Rows 158, 238 and 275–278; Task 4.
- **OQ-7 (INTENT detail and cutoff): APPROVE.**
  - One clock instant is read inside the transaction. It is passed to `detail_fn` and is also `row.at` and the
    policy cutoff's source.
  - There is no self-hash reference, and a later insert timestamp never selects a different cutoff. Tasks 1, 8, 9
    and 12.
- **OQ-8 (stop record): AMEND.**
  - A canonical deterministic record with the pure legacy fields, and no wall-clock decision fields (`decided_utc`
    and `decided_by` are gone).
  - The last-W-slot-as-trigger rule is NOT pinned yet. Task 11 Step 2a first demonstrates each disposition (rows
    300–305) against the frozen calendar, deadline and pending rules: the earliest qualifying lot-count close,
    pending-close exclusion, true six-month eligibility by close instant, and explicit TIMEOUT and NO-VALID-SEAL
    examples.
  - The shape is pinned only after Codex accepts them (BLK-3). Task 11.
- **OQ-9 (differing STOP before any STOP): APPROVE.** REFUSE and escalate, with no new stop chosen. A STOP that
  differs from an existing STOP is INVALID (`stop-conflict`). Task 2.
- **OQ-10 (op and actor on files): APPROVE WITH CONDITIONS.**
  - Claim, report and resolution carry op and actor.
  - The claim names its capture directory (`capture_dir`, a relpath). The F3 in-flight check accepts a capture
    directory only when its own claim names exactly that directory and carries the INTENT's op and actor.
  - Trial binding and raw-byte integrity remain mandatory. Row 311; Tasks 6 and 7.
- **OQ-11 (report before J; after.json): AMEND.**
  - The pre-J report is frozen and is a member of the QUALIFIED tree.
  - `after.json` is display-only and optional. It is never read by any check or decision (E5.2).
  - Required seal membership comes from committed history (E2.4 r1): each pre-J report's `seals_checked` (bound by
    the QUALIFIED tree), each committed PREPARED commitment's `seals_checked`, the first-QUALIFIED rows and the F2
    stop record.
  - `_report_seals` and `_capture_seal_problems` are rewritten accordingly. The old->new mapping is listed in
    `a3/t6_old_new.md`. Rows 264–266; Tasks 6 and 7.
- **OQ-12 (FAILED timing): APPROVE WITH CONDITIONS.**
  - FAILED has no time restriction and stands until another terminal wins.
  - It never becomes a success and never erases a deadline or integrity violation.
  - The deadline finalizer is never prevented by a live worker (E1). Task 2 and Task 7.
- **OQ-13 (TIMEOUT leftovers): AMEND, now E1.4.**
  - Leftovers are non-selectable.
  - The finalizer moves only uncommitted files of the losing op, and only when the slot work lock is acquirable
    (the worker is gone). While the lock is held, cleanup is deferred.
  - Cleanup never decides anything. Rows 257 and 259; Task 7.
- **OQ-14 (post-START seals): AMEND, now E2.** Pinned publication contract:
  1. **Authority.** The authority is the close's first QUALIFIED slot (every earlier slot terminal) and its committed
     tree. The seal file is the published copy of `s1_slot.seal_bytes` of that evidence.
  2. **Readers.** Fences, stop record, final plan and score recompute from the evidence; a present copy must equal the
     recomputation.
  3. **Publication.** Only while ACTIVE, under the stop lock (read state, publish, re-read state); a held stop lock
     is no change and pending (E2.6). The stop operation publishes every determined unpublished seal, re-reads, then
     appends TRIAL-STOP, under the same lock (E2.5). A seal is never published in STOPPED, INVALID or CLOSED.
  4. **Required (published-committed, E2.4 r1).** A seal is determined once its close's first QUALIFIED slot is
     committed with every earlier slot terminal. It becomes published-committed once a later committed QUALIFIED
     tree or PREPARED commitment lists it in `seals_checked`, or the F2 stop record lists it. A published-committed
     seal that is missing or different is INVALID (registration-artifact) and is never recreated.
  5. **Not yet required.** Before STOP, a determined, not-yet-published-committed, missing seal may be published
     once, with exactly its recomputed bytes.

  Rows 55, 187, 260–266, 323–325 and 331; Tasks 6, 7, 8 and 11.
- **OQ-15 (opening receipt and books): AMEND; KEEP SINGLE.**
  - start_attest stays the single member `attest_start.json`.
  - `opening_books.json` is a deterministic derived input:
    - it is published before the start_attest INTENT by the existing `_opening_books` (write once, or verify that an
      existing file equals the recomputation from the committed opening seal);
    - its sha256 is in the envelope inputs and in `attest_start.json`'s `opening_books_sha256`;
    - the RUN-ACK binds it.
  - `opening_receipt.json` is derived only from the committed selected slot's evidence. No mutable reference is
    rebased. Rows 85, 104 and 268; Tasks 8 and 10.
- **OQ-16 (final snapshot): APPROVE WITH CONDITIONS.**
  - It stays separately bound evidence through the SCORE-ACK's `final_snapshot_sha256`.
  - The authorized command is `s1_checkpoint --final-snapshot`, behind the trial gate, in STOPPED only. Its report
    bytes are bound by the SCORE-ACK.
  - It never becomes sampled history and never a slot capture after the STOP.
  - A missing or changed bound report makes the score INVALID (OQ-28 path), never an economic fallback.
    Row 314; Tasks 12 and 13.
- **OQ-17 (evidence manifest): AMEND, now E5.5.**
  - The S1 check reconstructs the canonical prefix manifest and compares its sha256 with the OPENING-ACK's
    `evidence_manifest_sha256`, besides the journal and file checks. It never reads Codex's folder.
  - The byte format and membership are E5.5 (Erratum 1 r1), which resolves the former BLK-2.
  - Wrong-hash and wrong-membership negatives use an otherwise valid journal and valid files and are INVALIDATE
    (registration-artifact) (rows 279 and 280). Task 10.
- **OQ-18 (OPENING-ACK lead): APPROVE WITH CLARIFICATION, now E5.3.**
  - There is no numeric lead.
  - The OPENING-ACK must be created before the START attestation's INTENT (causal check on `created`), and the
    attestation must be strictly before planned START. Row 316; Task 10.
- **OQ-19 (legacy machinery): APPROVE WITH CONDITIONS.**
  - The legacy witnesses are additional detectors only, never identity or authorization roots.
  - F6.4 persistence applies after any journal row.
  - Which artifacts are required still depends on the actual reached stage, and local parsing can never downgrade a
    journal INVALID. Task 5.
- **OQ-20 (unreadable mailbox at write_plan): APPROVE.** A fail-closed refusal, with no mailbox creation. It is never
  read as "no open trial". Task 4.
- **OQ-21 (REFUSE): APPROVE.** REFUSE is a distinct return, separate from LOST-RACE cleanup and INVALIDATE. Task 2.
- **OQ-22 (ACQUIRE-ACK lag): APPROVE.** Both the ACK's `created` and the actual execution time satisfy the lag, the
  attestation causal order is kept, and the New York session instants are exact. Task 12.
- **OQ-23 (lock names): APPROVE WITH CONDITIONS.**
  - Lock names are validated against `^(slot-\d{8}T\d{6}Z|stage-(audit|opening|start_attest|prereg|stop_attest|final_plan|final|score)|stop)$`.
  - The trial_id is validated against uuid4.
  - Any other name is a LockError: no path traversal or cross-trial aliasing. The deadline conflict is solved by
    E1, not by naming. Row 309; Task 3.
- **OQ-24 (matrix opening records): APPROVE WITH CONDITIONS.** These are `registry/opening.json` and
  `witnesses/opening.json`, and they are not journal substitutes. The matrix also covers the new commitment stages
  and raw members (Task 14). Row 255.
- **OQ-25 (no capture after STOP): APPROVE.**
  - A late completion of a slot that started before the stop is kept as evidence but excluded from sampled history.
  - The bounded historical-price finalization stays allowed. Task 6 and Task 11.
- **OQ-26 (`created`): APPROVE.**
  - `created` is the in-transaction write clock. `at` may be an earlier R only for QUALIFIED.
  - ACK causal checks use `created`, and journal seq is the ordering authority. Task 1.
- **OQ-27 (uuid4 trial_id): APPROVE.** Identity-bearing records carry the uuid4 and are validated against the trial
  and the envelope. Task 4.
- **OQ-28 (score ABORTED-INVALID): AMEND.**
  - An ABORTED-INVALID returned by `_score` because of an established integrity violation persists TRIAL-INVALID
    (`registration-artifact`; the observation lists `_score`'s exact reasons). The report stays in staging, with no
    PREPARED or CREATED.
  - INSUFFICIENT, INCONCLUSIVE, NO-VALID-SEAL and BLOCKED verdicts without an integrity violation are committed as
    normal non-numeric scores. Rows 306 and 307; Task 13.
- **OQ-29 (sampled-history manifest): APPROVE WITH CONDITIONS.**
  - The input is
    `{"rows": [line_sha256 of every row with seq <= STOP seq, in seq order], "seals": {relpath: sha256}}` (keys
    sorted). The seals are the recomputed first-QUALIFIED seals committed at or before the STOP seq.
  - Later completions cannot change it, and the post-stop final acquisition is an additional input. Row 315;
    Task 13.
- **OQ-30 (opening_receipt_sha256): APPROVE.** It is the raw file sha256, distinct from the fingerprint hash, and
  both are tested. Row 318; Task 10.
- **OQ-31 (established violations): AMEND, now E5.1.**
  - The order is external first: TRIAL-INVALID (`established-violation`) when the journal is writable, then the
    local `aborted.json`.
  - The observation records `subtype` (one of receipt, binding, fence, bridge, seal-record) and `legacy_reason`
    (the exact c9b4322 text).
  - The predicates are unchanged, and no terminal slot event is required first. Row 308; Task 6.
- **OQ-32 (capture bytes): REJECT AS PROPOSED, now E5.6.** `backup.sqlite3` is in the QUALIFIED tree by its own
  sha256: `CAPTURE_TREE = ("backup.sqlite3", "meta.json", "projection.json")`. Backup deletion and change are tested
  (row 267). Task 6.
- **OQ-33 (clock outside [s, E]): APPROVE WITH CONDITIONS.**
  - now >= E: no row, no claim, no capture.
  - An early invocation (now < s): an authorized claim plus FAILED, with zero capture.
  - Tested at s−1µs, s, E−1µs, E and E+1µs (row 310). Task 6.
- **OQ-34 (restart pre-check): APPROVE.** The worker pre-checks under its work lock and refuses. The journal still
  rejects a genuinely submitted repeat, and the deadline finalizer is not bypassed. Task 6.
- **OQ-35 (staging evidence): APPROVE WITH CONDITIONS.**
  - `intent.json` and `prepared.json` are declared required evidence. Their lifecycle: written exclusively before
    their row, kept for the trial's life, checked against the row detail at every gate.
  - Their loss or change after CREATED is INVALID (stage-replaced).
  - No other staging file is authority. Row 317; Task 8.
- **OQ-36 (trial_id representation): AMEND, an explicit exception, now E5.4.**
  - Raw provider pages and list-shaped derived files keep their source shape. They are bound to the trial through
    the typed commitment (`trial_id`, `op`, members, provenance).
  - Cross-trial substitution is tested (row 312). Every identity-bearing metadata record carries the uuid4.
    Tasks 8–13.
- **OQ-37 (opening issuance): REJECT, so F7.2(b) stays literal.**
  - Every scheduled slot of the opening close must have a terminal row within the OPENING-ACK's journal prefix.
  - Later opening-close slots are refused, with no row, by the opening gate once the opening INTENT exists. Each
    ends MISSED at its E (now Erratum 1 r1 E5.6, a disclosed operational constraint).
  - So the OPENING-ACK can be issued only after the E of the last scheduled opening-close slot; the conftest issues
    it after `close_out`. Rows 81, 152, 269, 270 and 333; Task 10.
- **OQ-38 (stop.json damage): APPROVE.**
  - After a finalization INTENT: `registration-artifact`.
  - Before it: the deterministic publication-gap recovery, or `stop-conflict`.
  - The external STOP is immutable, and an INVALID trial never resumes. Task 11.

## TDD discipline (applies to every task)
1. **Interface stub first.** Each task's Step 1 creates or changes the interface with its final names and types, and a
   permissive body. A permissive body is the pre-Addendum-3 behaviour, or for a new module the absence of the rule
   (accept everything, always APPEND, never lock, no check). The stub is committed to the working tree only, never to
   git.
2. **Behavioural RED.**
   - Step 3 runs the new tests against the stub and saves the output to `a3/tN_red.txt`.
   - A test counts as RED only if it fails on an assertion about behaviour.
   - Any ImportError, AttributeError, fixture error or collection error is labelled `missing-interface` in
     `a3/tN_red_labels.txt` and is fixed in the stub until the failure is behavioural.
   - Tests that pass on the stub are labelled: `ctrl` (positive control), `retro` (the rule already held) or
     `static`.
3. **GREEN.** Implement, then run the task's tests and save `a3/tN_green.txt`.
4. **Full suite and old->new.**
   - Run the whole suite. For every existing test that now fails, classify it in `a3/tN_old_new.md` as one of:
     - **intended semantic change**: old expectation -> new expectation, with the spec clause, and the test edited
       accordingly;
     - **fixture incompatibility**: the conftest or helper is fixed, never the assertion;
     - **regression**: the product code is fixed.
   - Re-run until green and save `a3/tN_full.txt`. Then save `a3/tN_hashes.txt`: sha256 of every changed file and
     every evidence file.
   - Existing test files are edited only for intended semantic changes. Every edit gets one old->new line.
5. **Codex probes** (spec F10):
   - The historical copies are frozen. Task 5 copies the three probe files and the result JSON byte-identically into
     `a3/codex_probes_historical/`, and the XML from the coordination folder. They are never collected by pytest.
   - New tests go to `s1_tests/test_s1_a3_codex_probes.py`, with the old->new map below.
   - The "intended old behavioural failures" are the historical observations (the JSON files). They are recorded in
     `a3/codex_probes_old_new.md` separately from any fixture or setup incompatibility seen when the new file is run.
6. **Spies on every refusal and invalid path.**
   - The conftest `Spies` helper (Task 5) counts four things:
     - live callbacks: the receipt and process functions handed to a command;
     - captures: `s1_snapshot.take_snapshot`;
     - provider requests: every request a `MockTransport` handler sees;
     - valuation calls: `c.sim().simulate_lot`, `c.sim().baseline_economics`, `c.sim().lot_economics` and
       `s1_run.candidate_economics`.
   - Every refusal or invalid test ends with `spies.assert_zero()`, or with the exact allowed counts.
   - Tests never use a real network. A conftest autouse guard patches `httpx.HTTPTransport.handle_request` and
     `socket.create_connection` to raise.

## Codex probe old -> new map (F10 "Codex probes")
| historical probe (frozen copy) | old observation (historical JSON) | new test (`test_s1_a3_codex_probes.py`) | new expected | task |
|---|---|---|---|---|
| test_codex_publication.py::test_observe_actual_publication_deadline_behavior[-1] | publication-offset--1.json: seal written | test_publication_d_minus_1us_qualifies_when_no_timeout_committed_first | QUALIFIED (R = D-1µs), seal written | T6 |
| …[0], …[1] | publication-offset-0/1.json: seal written, `publication_overrun` | test_publication_at_d_and_d_plus_1us_does_not_seal[0,1] | REFUSE late R, no row, no seal; then TIMEOUT at D by the finalizer | T6 |
| test_codex_publication.py::test_required_durable_publication_at_or_after_deadline_must_not_seal[0,1] | failed (sealed) | same as the row above | passes | T6 |
| (new) | none | test_publication_well_before_d_seals (positive control) | QUALIFIED, seal | T6 |
| (new) P/R/J/T races | none | test_race_t_commits_then_j_is_lost_race, test_race_j_commits_then_stale_t_is_lost_race, test_race_two_finalizers_one_terminal, test_race_p_without_j_restart_ends_in_timeout | as named, no INVALID | T7 |
| f045bd31 deadline-lock-demonstration.json (revision 0 control flow) | at D with a live slot lock: deferred, 0 TIMEOUT appends | test_s1_a3_finalizer.py::test_timeout_commits_at_d_while_a_live_worker_holds_the_work_lock (+ row 257) | TIMEOUT at D with the worker alive (E1) | T7 |
| f045bd31 post-stop-seal-demonstration.json (revision 0 control flow) | STOPPED, QUALIFIED seq1 < STOP seq2, seal written=True | test_s1_a3_finalizer.py::test_no_seal_after_stop_even_for_a_pre_stop_qualified | no seal ever; "outside ACTIVE" refusal (E2.1) | T7 |
| test_codex_registration.py::test_v1_selective_deletion_allows_different_opening_and_start_attestation | v1-selective-deletion.json: replacement seal accepted, attestation and prereg accept it | test_v1_selective_deletion_is_invalid | INVALID (opening CREATED member missing -> stage-replaced); zero callbacks; no second opening | T10 |
| (F10 "A fully deleted, then B") | none | test_a_fully_deleted_then_b_is_invalid_or_never_ack_eligible | INVALID (LOST), or B has no ACK-eligible state; zero callbacks | T10 |
| test_codex_registration.py::test_missing_prereg_and_both_records_is_only_refusal_then_restoration_resumes | prereg-restoration.json: refusal, then resumes | test_prereg_restoration_is_invalid_once_created; test_prereg_before_created_follows_the_stage_table | INVALID (stage-replaced) once CREATED; before CREATED: pending, recovery or stage-incomplete per the table | T10 |
| test_codex_combined_damage.py::…[missing], […unparseable] | bundle-bootstrap-*.json: refusal, then restoration resumes | test_combined_damage_is_invalid_bundle_after_any_journal_row[missing,unparseable] | INVALID (bundle) plus local aborted.json; restoration stays invalid; zero callbacks | T5 |

---

## File Structure
| File | Responsibility | Task |
|---|---|---|
| `research/s1/s1_journal.py` (new, bundle) | F0: line grammar, parse/format, chain verification, mode=ro readers, `decide` (F0.5 precedence), `append` (the one INSERT under BEGIN IMMEDIATE), detail builders | 1, 2 |
| `research/s1/s1_locks.py` (new, bundle) | F5: `OwnershipLock` (CreateFileW share-read-only + msvcrt.locking), the three classified results | 3 |
| `research/s1/s1_trial.py` (new, bundle) | F6/F7: ACK grammar, mailbox scan, open trial, CLOSE validity, ACK chain and journal binding, trial state, token builders, `gate()` (the first step of every command), `invalidate()` | 4, 5 |
| `research/s1/s1_slot.py` (new, bundle) | F3: slot subjects, tree manifests, slot timing, worker rows, finalizer rows, the evidence table, `late/` moves, post-START seal recomputation | 6, 7 |
| `research/s1/s1_stage.py` (new, bundle) | F4: stage table, envelope and commitment, staging, `run`, `recover`, the stage-state table `evaluate`, member checks, manifest projection (C-a) | 8 |
| `research/s1/s1_common.py` | DOC_PINS + BUNDLE_CODE; ACK token texts (new fields); `registration_gate` violation -> TRIAL-INVALID | 1, 4, 5 |
| `research/s1/s1_collect.py` | write_plan trial_id + F9; request policy and `_Authorizer` in `_get`/`_paged`; audit and final as stages | 4, 9, 12 |
| `research/s1/s1_checkpoint.py` | worker on SLOT rows; finalizer on the journal; opening stage; final-snapshot gate | 5, 6, 7, 10 |
| `research/s1/s1_run.py` | gate wiring; start_attest/prereg/stop_attest/score stages; trial_id | 5, 10, 11, 13 |
| `research/s1/s1_seal.py` | F2 stop record from committed history; journal-based stop | 11 |
| `research/s1/s1_gates.py` | field-by-field ACK verification (replaces token-line equality) | 5 |
| `research/s1/s1_tests/conftest.py` | MAILBOX_SCHEMA, `s1_mailbox_init`, network guard, `Spies`, trial and journal fixtures, migrated helpers | 1, 5, 6, 7, 9–13 |
| `research/s1/s1_tests/test_s1_a3_*.py` (new) | journal, precedence, locks, trial, gate, slots, finalizer, stage, audit, prestart, stop, final, score, matrix, residual, codex_probes, mutants | each |
| `research/s1/docs/s1_design_v5_addendum3_erratum1.md` (pending, BLK-1) | the adopted byte-frozen Erratum 1; pinned in DOC_PINS as ERRATUM1_SHA256 | 1 (precondition) |
| `research/s1/s1_evidence/a3/` (new) | RED/GREEN/full outputs, old->new lists, hashes, historical probes, t11_dispositions.md (BLK-3), hypothesis_db/, t15 mutation reports | each |
| `research/s1/s1_evidence/cr_a3/<module>/cr.toml` (new) | Cosmic Ray 8.3.15 configs for the changed critical modules | 15 |

---
## Requirement -> expected-outcome map (spec F10: "delivered with the implementation plan, before code, for Codex review")
RED type:
- **B**: behavioural RED against the task's permissive interface stub.
- **B-old**: behavioural RED that is also a documented old behaviour. The c9b4322-era code shows the outcome the
  test forbids, either in a historical Codex observation (`codex_probes_historical/*.json`) or in the c9b4322 code
  path the task's stub keeps. The test is RED against the task's stub for that reason. It is never counted twice.
- **ctrl**: positive control (passes before and after; not a RED).
- **retro**: the rule already held; the test is retrospective.
- **static**: source or evidence check.
- **proc**: procedural, no S1 test possible (stated why).

All test paths are under `research/s1/s1_tests/`. `[x]` names a parametrize id.

| # | spec ref | requirement | test name | expected outcome | task | RED |
|---|---|---|---|---|---|---|
| 1 | A3.1, Erratum header | Addendum 3 sha256 d9dd3759… and Erratum 1 ERRATUM1_SHA256 join DOC_PINS; both byte copies hash to their pins | test_s1_a3_journal.py::test_bundle_pins_addendum3_and_lists_every_new_module | DOC_PINS["docs/s1_design_v5_addendum3.md"] == d9dd…; DOC_PINS["docs/s1_design_v5_addendum3_erratum1.md"] == sha256 of the adopted copy; bundle_problems == [] | T1 | B |
| 2 | A3.1 | every new s1_*.py is a listed bundle member | same test, extended in T3/T4/T6/T8; old->new test_s1_t12_a3_a8.py::test_a3_bundle_is_the_explicit_file_list_plus_the_three_document_hashes | BUNDLE_CODE lists s1_journal/s1_locks/s1_trial/s1_slot/s1_stage; `unexpected` == {} | T1,3,4,6,8 | B |
| 3 | F0.1 | the only write is one INSERT inside BEGIN IMMEDIATE, s1->codex, key experiments-s1-journal | test_s1_a3_journal.py::test_append_is_one_insert_inside_begin_immediate | SQL trace: BEGIN IMMEDIATE, SELECT, one INSERT, COMMIT; stored sender/recipient/key exact; acknowledged NULL | T1 | B |
| 4 | F0.1 | rows re-read inside the transaction; a concurrent appender is serialized, never forks | test_s1_a3_journal.py::test_concurrent_append_is_serialized_and_a_busy_mailbox_is_an_outage | the inner appender gets Outage during the outer transaction; final seq 1,2 chain verifies | T1 | B |
| 5 | F0.1 | no UPDATE/DELETE/ack/other role; mailbox.py never imported | test_s1_a3_journal.py::test_journal_module_never_updates_deletes_or_imports_mailbox | AST: one INSERT literal, no UPDATE/DELETE/REPLACE/CREATE/DROP literal; no `mailbox` import | T1 | static |
| 6 | F0.1 | every other read is mode=ro; a missing mailbox is never created | test_s1_a3_journal.py::test_readers_are_mode_ro_and_never_create_the_mailbox | read_all(missing) raises Outage; the file still does not exist | T1 | B |
| 7 | F0.1, C-c | the decision is applied to the state read inside the transaction | test_s1_a3_precedence.py::test_append_decides_on_the_state_read_inside_the_transaction | stale QUALIFIED after a committed TIMEOUT -> LOST-RACE, no row | T2 | B |
| 8 | F0.2 | exact line bytes, field order, single spaces, no newline | test_s1_a3_journal.py::test_line_format_round_trip_exact_bytes | format == template; parse(format(x)) == x | T1 | B |
| 9 | F0.2, F0.3, C-c | every grammar deviation is rejected | test_s1_a3_journal.py::test_line_rejects_every_grammar_deviation[*] (19 ids) | ChainError | T1 | B |
| 10 | F0.2 | line_sha256; seq-1 prev = sha256(AUDIT-ACK line) | test_s1_a3_journal.py::test_genesis_is_the_sha256_of_the_audit_ack_line | rows[0].prev == sha256(audit line UTF-8) | T1 | B |
| 11 | F0.2 | `at` = the in-transaction clock reading; QUALIFIED `at` = R | test_s1_a3_journal.py::test_at_is_the_in_transaction_clock_and_qualified_uses_r | INTENT at == clock(); QUALIFIED at == R; created == clock() (OQ-26) | T1 | B |
| 12 | F0.2 | op is fixed by the opening row and repeated; actor is the appender | test_s1_a3_precedence.py::test_precedence_table[7-t-finalizer-actor]; test_s1_a3_finalizer.py::test_timeout_carries_the_intent_op_and_the_finalizer_actor | TIMEOUT.op == INTENT.op, TIMEOUT.actor == finalizer nonce != INTENT.actor; the finalizer never takes the work lock (E1) | T2,T7 | B |
| 13 | F0.2 | a recovery actor appends only STAGE-CREATED after PREPARED and SLOT-TIMEOUT | test_s1_a3_precedence.py::test_precedence_table[4a-q-foreign-actor,4a-f-foreign-actor,4a-p-foreign-actor,7-c-recovery-actor,7-t-finalizer-actor] | foreign-actor QUALIFIED/FAILED/PREPARED -> INVALIDATE; CREATED/TIMEOUT -> APPEND | T2 | B |
| 14 | F0.2 | a recovery actor holds the op lock and re-validates under it | test_s1_a3_stage.py::test_recovery_appends_created_with_a_op_and_b_actor_under_the_lock | B acquires `stage-<g>` before its journal read (order spy); CREATED.op == A.op, actor == B | T8 | B |
| 15 | F0.2 | no artifact contains the `at` of the row that commits its hash (no data dependency, not substring inequality) | test_s1_a3_stage.py::test_member_bytes_do_not_depend_on_the_prepared_or_created_clock[distinct-ticks,same-tick] | two runs whose PREPARED/CREATED clocks differ give byte-identical members; a same-tick run (every row at one instant) is accepted; the commitment has no `at` field | T8 | B |
| 16 | F0.3 | only the ten kinds | test_s1_a3_precedence.py::test_malformed_requests_are_refused_with_no_row[unknown-kind] | RequestError, no row | T2 | B |
| 17 | F0.4 | detail = sha256 of in-memory canonical bytes | test_s1_a3_journal.py::test_detail_is_hashed_from_memory_not_reread_from_disk | detail_of(obj) == sha256(canonical(obj)); detail_fn result committed | T1 | B |
| 18 | F0.4 | never re-read from a replaceable disk file | test_s1_a3_stage.py::test_prepared_detail_comes_from_memory_even_if_prepared_json_is_altered | PREPARED detail = in-memory commitment; altered prepared.json -> recovery INVALID (stage-replaced) | T8 | B |
| 19 | F0.5 | LOST-RACE: no row; only own uncommitted files move to late/; winner re-checked | test_s1_a3_slots.py::test_lost_race_moves_only_own_uncommitted_files_to_late | own claim/report/capture in late/<day>/<slot>/; nothing committed moved; recheck passes | T6 | B |
| 20 | F0.5 | late/ is preserved and never selectable | test_s1_a3_finalizer.py::test_late_files_are_never_selectable_for_a_seal | seal comes only from the QUALIFIED tree, never from late/ | T7 | B |
| 21 | F0.5 | INVALIDATE appends TRIAL-INVALID with the reason instead, in the same transaction | test_s1_a3_precedence.py::test_invalidate_appends_trial_invalid_instead_in_the_same_transaction | exactly one new row, kind TRIAL-INVALID, subject reason/<code>, detail per OQ-2 | T2 | B |
| 22 | F0.5 step 1 | gap, fork, duplicate seq, bad format: refuse with no row, escalate | test_s1_a3_precedence.py::test_chain_integrity_refuses_with_no_row[gap,fork,dup,format] | ChainError; row count unchanged | T2 | B |
| 23 | F0.5 step 2 | CLOSED refuses every kind, TRIAL-INVALID included | test_s1_a3_precedence.py::test_closed_refuses_every_kind_including_trial_invalid[10 kinds] | REFUSE | T2 | B |
| 24 | F0.5 step 3 | INVALID: TRIAL-INVALID APPEND, every other kind LOST-RACE | test_s1_a3_precedence.py::test_invalid_appends_trial_invalid_and_lost_races_every_other_kind[10 kinds] | as stated | T2 | B |
| 25 | F0.5 4a | QUALIFIED/FAILED: no INTENT, op or actor differs -> INVALIDATE contradictory-completion, also on a terminal slot | test_s1_a3_precedence.py::test_precedence_table[4a-q-no-intent,4a-q-foreign-op,4a-q-foreign-actor,4a-q-foreign-op-on-terminal,4a-f-no-intent,4a-f-foreign-op,4a-f-foreign-actor] | INVALIDATE contradictory-completion | T2 | B |
| 26 | F0.5 4a | TIMEOUT: no INTENT or op differs -> contradictory-finalizer, also terminal | test_s1_a3_precedence.py::test_precedence_table[4a-t-no-intent,4a-t-foreign-op,4a-t-foreign-op-on-terminal] | INVALIDATE contradictory-finalizer | T2 | B |
| 27 | F0.5 4a | PREPARED: no INTENT, op or actor differs -> contradictory-stage | test_s1_a3_precedence.py::test_precedence_table[4a-p-no-intent,4a-p-foreign-op,4a-p-foreign-actor] | INVALIDATE contradictory-stage | T2 | B |
| 28 | F0.5 4a | CREATED: no PREPARED or op differs -> contradictory-stage | test_s1_a3_precedence.py::test_precedence_table[4a-c-no-prepared,4a-c-foreign-op] | INVALIDATE contradictory-stage | T2 | B |
| 29 | F0.5 4b | SLOT-INTENT for a slot with any row -> repeat-attempt, also when STOPPED | test_s1_a3_precedence.py::test_precedence_table[4b-si-after-intent,4b-si-after-terminal,4b-si-stopped-terminal] | INVALIDATE repeat-attempt | T2 | B |
| 30 | F0.5 4b | STAGE-INTENT with an INTENT -> repeat-stage | test_s1_a3_precedence.py::test_precedence_table[4b-gi-repeat] | INVALIDATE repeat-stage | T2 | B |
| 31 | F0.5 4c | QUALIFIED/FAILED on a terminal slot (identity passed) -> LOST-RACE | test_s1_a3_precedence.py::test_precedence_table[4c-q-after-timeout,4c-f-after-qualified] | LOST-RACE | T2 | B |
| 32 | F0.5 4c | TIMEOUT on a terminal slot -> LOST-RACE | test_s1_a3_precedence.py::test_precedence_table[4c-t-after-qualified] | LOST-RACE | T2 | B |
| 33 | F0.5 4c | MISSED on QUALIFIED/FAILED/TIMEOUT/MISSED -> LOST-RACE, before the timing step | test_s1_a3_precedence.py::test_precedence_table[4c-m-after-qualified,4c-m-after-failed,4c-m-after-timeout,4c-m-after-missed,4c-m-qualified-before-e] | LOST-RACE (even when now < E) | T2 | B |
| 34 | F0.5 4c | PREPARED exists: same detail LOST-RACE, different INVALIDATE | test_s1_a3_precedence.py::test_precedence_table[4c-p-same,4c-p-different] | LOST-RACE / INVALIDATE contradictory-stage | T2 | B |
| 35 | F0.5 4c | CREATED: detail != PREPARED -> INVALIDATE; CREATED exists same -> LOST-RACE | test_s1_a3_precedence.py::test_precedence_table[4c-c-differs-from-prepared,4c-c-created-same] | as stated | T2 | B |
| 36 | F0.5 4c | TRIAL-STOP when STOPPED: identical LOST-RACE, different stop-conflict | test_s1_a3_precedence.py::test_precedence_table[4c-stop-same,4c-stop-different] | LOST-RACE / INVALIDATE stop-conflict | T2 | B |
| 37 | F0.5 4d | MISSED with INTENT and no terminal -> refuse with no row | test_s1_a3_precedence.py::test_precedence_table[4d-m-in-flight] | REFUSE | T2 | B |
| 38 | F0.5 5 | SLOT-INTENT when STOPPED -> LOST-RACE | test_s1_a3_precedence.py::test_precedence_table[5-si-stopped] | LOST-RACE | T2 | B |
| 39 | F0.5 5 | SLOT-INTENT refused by stage gates/ACKs (F1 "stage gates and ACKs apply") | test_s1_a3_precedence.py::test_precedence_table[5-si-gate-refuses] | REFUSE | T2 | B |
| 40 | F0.5 5 | STAGE-INTENT forbidden by F1 or missing predecessor/ACK -> refuse | test_s1_a3_precedence.py::test_precedence_table[5-gi-forbidden] | REFUSE | T2 | B |
| 41 | F0.5 5 | TRIAL-STOP with the stop rule not met -> refuse | test_s1_a3_precedence.py::test_precedence_table[5-stop-rule-not-met,5-stop-differs-from-recomputed] | REFUSE (OQ-9) | T2 | B |
| 42 | F1 row 2 | completing an in-flight slot after the STOP only if its INTENT seq < STOP seq | test_s1_a3_precedence.py::test_precedence_table[5-q-intent-before-stop,5-q-intent-after-stop] | APPEND / REFUSE | T2 | B |
| 43 | F0.5 6 | SLOT-INTENT with now >= E -> refuse | test_s1_a3_precedence.py::test_precedence_table[6-si-at-e,6-si-before-e] | REFUSE / APPEND | T2 | B |
| 44 | F0.5 6 | QUALIFIED with R >= D -> refuse | test_s1_a3_precedence.py::test_precedence_table[6-q-r-at-d,6-q-r-d-plus-1us,6-q-r-d-minus-1us] | REFUSE, REFUSE, APPEND | T2 | B |
| 45 | F0.5 6, E1.2 | TIMEOUT with now < D -> refuse; at D it appends whether or not a worker is alive | test_s1_a3_precedence.py::test_precedence_table[6-t-before-d,7-t-finalizer-actor]; row 256 | REFUSE / APPEND at D | T2,T7 | B |
| 46 | F0.5 6 | MISSED with now < E -> refuse | test_s1_a3_precedence.py::test_precedence_table[6-m-before-e,6-m-at-e] | REFUSE / APPEND | T2 | B |
| 47 | F0.5 7 | otherwise APPEND | test_s1_a3_precedence.py::test_precedence_table[7-*] (gi-permitted, p, c-opening-actor, c-recovery-actor, trial-invalid-active, trial-invalid-stopped, stop) | APPEND | T2 | B |
| 48 | F0.5 sub-order | sub-step conditions are disjoint; no outcome depends on table order | test_s1_a3_precedence.py::test_substep_conditions_are_disjoint_and_decide_matches_the_oracle (Hypothesis, pinned: derandomize, seed 20261103, example database kept; scope: slot-subject histories × slot kinds × 5 instants only, not the stage or trial lifecycle) | at most one condition per sub-step; decide == independent oracle; minimized failures kept as @example | T2 | B |
| 49 | F0.5 who | QUALIFIED/FAILED/PREPARED need the opening actor; work never taken over | rows 13, 25, 27 | as stated | T2 | B |
| 50 | F0.7 | exceptions in a finalizer/recovery path append no row; unexpected errors fail closed | test_s1_a3_finalizer.py::test_finalizer_unexpected_error_appends_nothing; test_s1_a3_stage.py::test_recovery_unexpected_error_appends_nothing | SystemExit refusal, row count unchanged (the finalizer path takes no work lock, E1) | T7,T8 | B |
| 51 | F0.6 | the journal decides; local files are evidence | test_s1_a3_gate.py::test_journal_state_governs_over_local_files | INVALID row and no aborted.json -> refuse, no work | T5 | B |
| 52 | F0.6 | before any callback, capture, request or pricing: open trial, state, bundle are read | test_s1_a3_gate.py::test_every_command_reads_trial_state_and_bundle_before_any_callback[10 commands] | refusal with spies zero; gate call order recorded first | T5 | B |
| 53 | F0.6 | INVALID is irreversible; restoring files or deleting aborted.json never resumes | test_s1_a3_gate.py::test_invalid_is_irreversible | still refused, zero callbacks | T5 | B |
| 54 | F1 | ACTIVE/STOPPED/INVALID derivation; CLOSED layered on top | test_s1_a3_precedence.py::test_trial_state_derivation; test_s1_a3_trial.py::test_closed_is_layered_on_the_journal_state | as stated | T2,T4 | B |
| 55 | F1 table, E2.1 | no new seal in STOPPED/INVALID/CLOSED, whatever the QUALIFIED's seq | test_s1_a3_finalizer.py::test_no_seal_after_stop_even_for_a_pre_stop_qualified; test_s1_a3_stop.py::test_no_new_seal_after_the_stop (QUALIFIED after the STOP) | pre-STOP QUALIFIED with an unpublished seal, then STOP: no seal file ever; post-STOP QUALIFIED: no seal; neither is a stop input | T7,T11 | B |
| 56 | F1 table | finalization stages forbidden while ACTIVE | test_s1_a3_stop.py::test_finalization_stages_are_refused_while_active[stop_attest,final_plan,final,score] | REFUSE, no row, zero callbacks | T11 | B |
| 57 | F1 table | re-entry follows its gate; INVALID refused with no work | rows 53, 226 | as stated | T5,T8 | B |
| 58 | F1 graph | each finalization stage once, in dependency order, binding the STOP row | test_s1_a3_stage.py::test_stage_intent_refused_until_predecessor_created_and_ack[8 stages] | REFUSE until predecessor CREATED and ACK | T8 | B |
| 59 | F1 graph | ACQUIRE-ACK strictly after stop_attest, binds the listed fields, no earlier than the lag | test_s1_a3_final.py::test_acquire_ack_binds_prev_stop_line_and_is_not_before_the_lag[ok,before-attest,before-lag,wrong-stop-line,wrong-prev] | ok -> runs; others REFUSE, zero requests | T12 | B |
| 60 | F1 graph | SCORE-ACK binds runner, final manifest, stop attestation, bundle, trial_id, prev, journal seq/head, stop_line | test_s1_a3_score.py::test_score_ack_fields_are_verified[ok,wrong-final,wrong-prev,wrong-stop-line,head-forked] | ok -> score; others REFUSE | T13 | B |
| 61 | F1 graph | no provider call before stop_attest and the ACQUIRE-ACK | test_s1_a3_final.py::test_no_provider_request_before_stop_attest_and_acquire_ack | zero requests until both exist | T12 | B |
| 62 | F1 prefix | sampled history = rows at or before the STOP seq; later terminals excluded | test_s1_a3_stop.py::test_post_stop_sampled_slot_is_excluded_from_the_sampled_history | stop_attest/final_plan/score use only seq <= STOP | T11 | B |
| 63 | F1 prefix | authorized post-stop historical prices are usable for valuation | test_s1_a3_score.py::test_authorized_post_stop_prices_are_used_for_valuation | numeric score uses final/bars.json | T13 | ctrl |
| 64 | F2.1 | stop record = pure function of committed history | test_s1_a3_stop.py::test_stop_record_is_a_pure_function_of_committed_history | same rows -> same bytes; fields per OQ-8 | T11 | B |
| 65 | F2.2 | TRIAL-STOP detail = sha256(record), then stop.json | test_s1_a3_stop.py::test_trial_stop_is_appended_before_stop_json_is_published | STOP row exists while stop.json absent (barrier); then sha256(stop.json) == STOP detail | T11 | B |
| 66 | F2.3 | publication gap is recoverable; matching bytes published | test_s1_a3_stop.py::test_publication_gap_recovers_matching_bytes | stop.json published by the next command; no INVALID | T11 | B |
| 67 | F2.3 | recomputation mismatch -> stop-conflict | test_s1_a3_stop.py::test_publication_gap_with_different_history_is_stop_conflict | INVALID stop-conflict | T11 | B |
| 68 | F2.4 | after a finalization INTENT, stop.json missing/changed/unparseable -> INVALID; restoring doesn't resume | test_s1_a3_stop.py::test_stop_json_damaged_after_a_finalization_intent_is_invalid[deleted,changed,unparseable] | INVALID; restored -> still refused | T11 | B |
| 69 | F2.5 | the STOP timestamp and outcome are fixed | test_s1_a3_stop.py::test_stop_outcome_is_fixed_by_the_journal | second STOP different -> stop-conflict; same -> LOST-RACE | T11 | B |
| 70 | F3, E5.6 | QUALIFIED requires R < D; at = R; detail = tree manifest of report, resolution, capture files including the raw backup | test_s1_a3_slots.py::test_qualified_at_is_r_and_detail_is_the_tree_manifest | the tree keys are exactly report, resolution, capture/backup.sqlite3, capture/meta.json, capture/projection.json; detail == sha256(canonical({rel: sha})) | T6 | B |
| 71 | F3 | FAILED detail binds claim + failure report | test_s1_a3_slots.py::test_failed_detail_binds_the_claim_and_the_failure_report | as stated | T6 | B |
| 72 | F3 | first terminal wins; loser LOST-RACE, files to late/, no INVALID | test_s1_a3_codex_probes.py::test_race_t_commits_then_j_is_lost_race | TIMEOUT stays; worker LOST-RACE; no seal; no INVALID | T7 | B |
| 73 | F3 | crash after P without J -> TIMEOUT at D (slot op, finalizer actor) | test_s1_a3_codex_probes.py::test_race_p_without_j_restart_ends_in_timeout | TIMEOUT at D | T7 | B |
| 74 | F3 | a restarted process never appends QUALIFIED/FAILED for an earlier op, never reuses R, never opens a second INTENT | test_s1_a3_slots.py::test_restart_after_a_worker_crash_never_appends_qualified | restart refuses (slot has a row: no second INTENT, no completion) | T6 | B |
| 75 | F3 table | no row: any claim/capture/report/resolution -> INVALIDATE | test_s1_a3_finalizer.py::test_slot_evidence_table[no-row-stray-claim,no-row-stray-capture,no-row-clean] | INVALID registration-artifact / clean passes | T7 | B |
| 76 | F3 table | in flight: partial files with the INTENT's op/actor tolerated; another op -> violation | test_s1_a3_finalizer.py::test_slot_evidence_table[in-flight-own-partial,in-flight-foreign-op] | pass / INVALID | T7 | B |
| 77 | F3 table | QUALIFIED: tree files must match; late/ tolerated | test_s1_a3_finalizer.py::test_slot_evidence_table[qualified-ok,qualified-missing,qualified-changed,qualified-unparseable,qualified-late-extra,qualified-backup-changed,qualified-backup-deleted] | pass / INVALID ×3 / pass / INVALID ×2 | T7 | B |
| 78 | F3 table | FAILED: claim + failure report match; partial capture, late/ tolerated | test_s1_a3_finalizer.py::test_slot_evidence_table[failed-ok,failed-report-changed,failed-partial-capture] | pass / INVALID / pass | T7 | B |
| 79 | F3 table | TIMEOUT: leftovers tolerated (late/); a seal citing s -> violation | test_s1_a3_finalizer.py::test_slot_evidence_table[timeout-leftovers,timeout-seal-cites] | pass / INVALID | T7 | B |
| 80 | F3 table | MISSED: any file for s outside late/ -> violation | test_s1_a3_finalizer.py::test_slot_evidence_table[missed-clean,missed-stray] | pass / INVALID | T7 | B |
| 81 | F3 (opening seal selection only; issuance is row 152) | opening STAGE-INTENT only after the chosen slot's QUALIFIED, first in schedule order, earlier slots terminal | test_s1_a3_prestart.py::test_opening_intent_only_after_the_first_qualified_slot_and_earlier_slots_terminal[pending-earlier,failed-earlier,first-qualified] | no opening INTENT while an earlier slot is in flight; INTENT after; later slots' state is irrelevant here | T10 | B |
| 82 | F4.1 | STAGE-INTENT before any external request or computation | test_s1_a3_stage.py::test_intent_precedes_any_work_and_the_envelope_is_exact | work spy sees the INTENT row already committed | T8 | B |
| 83 | F4.1 | envelope = {trial_id, stage, inputs, acks, request_policy or null} | same test | detail == sha256(canonical(envelope)) | T8 | B |
| 84 | F4.2 | children written to `<root>/s1_staging/<trial_id>/<stage>/`, outside s1_out | test_s1_a3_stage.py::test_work_writes_only_to_staging_outside_s1_out | nothing in s1_out before publication | T8 | B |
| 85 | F4.3 | commitment format; single = one member; tree = every named member; provenance [] without provider | test_s1_a3_stage.py::test_prepared_commitment_format[single,tree,single-with-two-members-refused]; test_s1_a3_stage.py::test_stage_kinds_are_the_frozen_f48_kinds | exact keys; a 2-member single -> refusal ("exactly one member"), no PREPARED; TABLE kinds == F4.8 (start_attest single, audit/final/score tree) | T8 | B |
| 86 | F4.3 | prepared.json written before PREPARED; never trusted alone | test_s1_a3_stage.py::test_prepared_json_is_written_before_prepared_and_never_trusted_alone | file exists at the PREPARED append; recovery rejects a mismatching prepared.json | T8 | B |
| 87 | F4.3 | PREPARED after the work, before publication | test_s1_a3_stage.py::test_publication_is_exclusive_then_created_repeats_the_prepared_detail | order spy: work < PREPARED < publish < CREATED | T8 | B |
| 88 | F4.4 | publication exclusive, then CREATED detail = PREPARED detail | same test | an existing member is never overwritten | T8 | B |
| 89 | F4.5 | intent_at recorded in the artifact; observation times real; prepared_at only in the row | test_s1_a3_stage.py::test_member_bytes_do_not_depend_on_the_prepared_or_created_clock[distinct-ticks,same-tick]; test_s1_a3_stage.py::test_intent_at_field_equals_the_intent_row | `intent_at` == INTENT row `at` (schema placement); no member field derives from PREPARED/CREATED | T8 | B |
| 90 | F4.5, CH3 | retrieved_utc is the actual observation instant | test_s1_a3_audit.py::test_retrieved_utc_is_the_actual_observation_instant | equals the clock read after the calendar response | T9 | B |
| 91 | F4.6 | audit policy object exactly the F4.9 audit rows | test_s1_a3_audit.py::test_audit_policy_is_exactly_the_f49_audit_rows | equality with a hand-written expected policy | T9 | B |
| 92 | F4.6 | final policy object exactly the F4.9 final rows | test_s1_a3_final.py::test_final_policy_is_exactly_the_f49_final_rows | as above | T12 | B |
| 93 | F4.6 | authorized only by exact family URL; hosts = those URLs' hosts; paper-api only for the calendar | test_s1_a3_audit.py::test_structural_refusals_send_no_further_request_then_invalid[other-paper-path,other-host] | Structural before send; INVALID provider-structural | T9 | B |
| 94 | F4.6 | request order = collector order | test_s1_a3_audit.py::test_request_order_is_the_collector_order; test_s1_a3_final.py::test_final_request_order_is_the_collector_order | calendar, CA batch 0..n; bars, window, full_history | T9,T12 | retro |
| 95 | F4.6 | empty symbol list -> zero batches, no request | test_s1_a3_audit.py::test_empty_ca_symbols_send_no_ca_request_and_the_audit_completes | only the calendar request | T9 | retro |
| 96 | F4.6 | page n+1 adds only page_token from the immediately preceding validated page; a family ends at a page with no token | test_s1_a3_audit.py::test_unpredictable_tokens_and_page_counts_complete_with_full_provenance | provenance page_token_from chain | T9 | B |
| 97 | F4.6 | refusals (repeated token, > max_pages, redirect, new host, URL/base outside policy, no family) enforced in `_get`/`_paged` before sending | test_s1_a3_audit.py::test_structural_refusals_send_no_further_request_then_invalid[repeated-token,over-max-pages,redirect,other-host,wrong-endpoint,changed-base,outside-batch,other-paper-path]; test_s1_a3_audit.py::test_authorizer_refuses_a_second_calendar_request_and_an_unlisted_family (second calendar, no family) | Structural; HTTP spy shows no request after the refusal; INVALID provider-structural | T9 | B |
| 98 | F4.6 | provenance: every request in order with family/scope/n/url/params/page_token_from/retrieved_utc/status/page_relpath/page_sha256; credential-free | test_s1_a3_audit.py::test_every_sent_request_is_in_provenance | HTTP spy list == provenance list; no key text | T9 | B |
| 99 | F4.6 | provider anomaly: staged pages + ABORTED kept, no PREPARED, INVALID provider-structural | test_s1_a3_audit.py::test_provider_anomaly_keeps_aborted_staging_no_prepared_and_invalidates | as stated | T9 | B |
| 100 | F4.7 | recovery: lock, re-read, prepared.json hash, check members, publish missing, CREATED (own actor) | test_s1_a3_stage.py::test_crash_after_prepared_recovery_by_b_appends_created_without_recompute | process B appends CREATED; work spy zero | T8 | B |
| 101 | F4.7 | absent/mismatched byte -> stage-replaced; foreign op / missing PREPARED / detail mismatch -> contradictory-stage | test_s1_a3_stage.py::test_recovery_failures_are_invalid[member-absent,member-changed,prepared-json-mismatch,foreign-op,missing-prepared] | INVALID with the named reason | T8 | B |
| 102 | F4.8 audit | tree = F4.9 audit members; inputs plan.json, AUDIT-ACK line, bundle | test_s1_a3_audit.py::test_audit_envelope_inputs_and_members | as stated | T9 | B |
| 103 | F4.8 opening | single seals/<close>.json; inputs plan, audit manifest, QUALIFIED line + tree manifest, opening_receipt.json | test_s1_a3_prestart.py::test_opening_stage_envelope_and_single_member | as stated | T10 | B |
| 104 | F4.8 start_attest, OQ-15 | single member attest_start.json; inputs plan, audit manifest, opening seal, opening receipt, OPENING-ACK line, plus the derived hash-bound opening_books.json | test_s1_a3_prestart.py::test_start_attest_envelope_and_single_member | kind single, members == {attest_start.json}; inputs include opening_books.json == sha of the recomputation; attest record's opening_books_sha256 equal | T10 | B |
| 105 | F4.8 prereg | prereg.json; inputs attest_start.json, RUN-ACK line, receipt | test_s1_a3_prestart.py::test_prereg_envelope_and_member | as stated | T10 | B |
| 106 | F4.8 stop_attest | attest_stop.json; inputs TRIAL-STOP line, stop.json | test_s1_a3_stop.py::test_stop_attest_envelope_and_member | as stated | T11 | B |
| 107 | F4.8 final_plan | final_plan.json; inputs stop.json, attest_stop.json, prereg.json, plan | test_s1_a3_stop.py::test_final_plan_envelope_and_member | as stated | T11 | B |
| 108 | F4.8 final | tree = F4.9 final members; inputs final_plan.json, ACQUIRE-ACK line, prereg.json, attest_stop.json | test_s1_a3_final.py::test_final_envelope_inputs_and_members | as stated | T12 | B |
| 109 | F4.8 score | tree = score/attempt.json, score/s1.json; inputs final manifest, attest_stop.json, SCORE-ACK line, sampled-history manifest | test_s1_a3_score.py::test_score_envelope_inputs_and_members | as stated (OQ-29) | T13 | B |
| 110 | F4.9 audit calendar | exact URL c.CAL_URL, base {start, end, date_type}, one request, page audit/pages/calendar.json | test_s1_a3_audit.py::test_audit_policy_is_exactly_the_f49_audit_rows | as stated | T9 | B |
| 111 | F4.9 audit CA | data host CA URL, CA_FIXED + symbols/start/end=cutoff per 50-batch, paged, audit/pages/ca_{i:03d}_page{n:03d}.json | same test + test_s1_a3_audit.py::test_normal_audit_authorizes_calendar_and_ca_batches_and_commits_every_member | as stated | T9 | B |
| 112 | F4.9 final bars | bars URL, raw/SIP/1Day/limit 10000, start/end per table, final/pages/bars_page{n:03d}.json | test_s1_a3_final.py::test_final_policy_is_exactly_the_f49_final_rows | as stated | T12 | B |
| 113 | F4.9 final CA window / full | window: start = NY date of prereg.start; full: start = full_history_start; end = cutoff; pages under final/pages/ and final/pages_full/ | same + test_s1_a3_final.py::test_normal_final_commits_every_member | as stated | T12 | B |
| 114 | F4.9 | both final CA families required and reconciled, neither dropped or merged | test_s1_a3_final.py::test_both_ca_families_are_requested_and_reconciled | two scopes in provenance; reconcile_actions over both | T12 | retro |
| 115 | F4.9 | raw page members = provenance page_relpaths one-to-one; fixed member names | test_s1_a3_audit.py::test_members_are_the_fixed_names_plus_one_page_per_request; test_s1_a3_final.py::test_final_members_are_the_fixed_names_plus_one_page_per_request | as stated | T9,T12 | B |
| 116 | F4.9, C-a | manifest files+pages (projected) == PREPARED members minus manifest; old shape kept | test_s1_a3_stage.py::test_manifest_projection_rule; test_s1_a3_audit.py::test_manifest_shape_is_preserved_and_its_projection_equals_the_members; test_s1_a3_final.py::test_final_manifest_projection_equals_the_members | equality; manifest key set == the c9b4322 key set | T8,T9,T12 | B |
| 117 | F4.9 | a member absent/changed/unparseable, an orphan page, a provenance entry without page -> stage-replaced, before valuation/scoring | test_s1_a3_final.py::test_damaged_final_member_is_invalid_before_valuation_with_zero_valuation_calls[*]; test_s1_a3_audit.py::test_damaged_audit_member_is_invalid_before_use[*]; rows 281–282 (receipt, final snapshot, raw backup) | INVALID stage-replaced (or registration-artifact for slot bytes); valuation spy zero | T9,T12,T13 | B |
| 118 | F4.9 | score abort: ABORTED s1.json stays in staging, no PREPARED, INVALID score-aborted | test_s1_a3_score.py::test_score_computation_error_is_invalid_score_aborted_with_no_numeric_score | as stated; evidence t13_score_aborted.txt | T13 | B |
| 119 | F4.9, C-b | cutoff = INTENT's NY date, used as every CA end, recorded as publication_cutoff | test_s1_a3_audit.py::test_cutoff_is_the_intent_new_york_date_across_midnight[midnight,dst-fall-back]; test_s1_a3_final.py::test_cutoff_is_the_intent_new_york_date_across_midnight | publication_cutoff == INTENT NY date != reservation NY date | T9,T12 | B-old |
| 120 | F4.9, C-e | cutoff positive same-day path, isolated | test_s1_a3_audit.py::test_cutoff_same_day_positive_path | equal dates; audit COMPLETE | T9 | ctrl |
| 121 | F4.9 flagged, OQ-0, E3 (pending Codex acceptance of E3) | BLOCKED is a pre-INTENT refusal record, ACTIVE, never INVALID | rows 271–274 (E3.6) | as rows 271–274; not committed before adoption | T10 | B |
| 122 | F4 table | no INTENT: an artifact for g is a violation after the AUDIT-ACK, a refusal before it | test_s1_a3_stage.py::test_stage_state_table[no-intent-artifact-after-audit-ack,no-intent-artifact-before-audit-ack] | INVALID registration-artifact / refusal | T8 | B |
| 123 | F4 table | INTENT, no PREPARED, lock held -> pending; staging children tolerated | test_s1_a3_stage.py::test_stage_state_table[intent-lock-held] | refusal, no work | T8 | B |
| 124 | F4 table | INTENT, no PREPARED, lock acquirable -> stage-incomplete | test_s1_a3_stage.py::test_stage_state_table[intent-lock-free] | INVALID stage-incomplete; no refetch | T8 | B |
| 125 | F4 table | PREPARED, no CREATED, lock held -> pending | test_s1_a3_stage.py::test_stage_state_table[prepared-lock-held] | refusal | T8 | B |
| 126 | F4 table | PREPARED, no CREATED, lock acquirable -> recovery | test_s1_a3_stage.py::test_stage_state_table[prepared-lock-free] | CREATED appended | T8 | B |
| 127 | F4 table | CREATED: every committed child required and must match | test_s1_a3_stage.py::test_created_member_missing_changed_or_unparseable_is_invalid[*] | INVALID stage-replaced | T8 | B |
| 128 | F4 failure 1 | pre-intent outage: no request, no artifact, refusal | test_s1_a3_stage.py::test_pre_intent_outage_makes_no_request_and_no_artifact | spies zero; staging absent | T8 | B |
| 129 | F4 failure 2 | completion-append failure: evidence kept, no next stage, recovery per table | test_s1_a3_stage.py::test_completion_append_failure_keeps_evidence_and_no_next_stage_runs | staging kept; next STAGE-INTENT refused | T8 | B |
| 130 | F5.1 as amended by E1.1 | the worker's slot work lock is taken before its pre-check read and held across INTENT, work and J; terminal decisions are arbitrated by the journal (the finalizer path is rows 256–259) | test_s1_a3_slots.py::test_slot_lock_is_taken_before_the_journal_read | order spy: lock < read < append < release (worker only) | T6 | B |
| 131 | F5.1 | stage/stop lock before the journal read | test_s1_a3_stage.py::test_stage_lock_is_taken_before_the_journal_read; test_s1_a3_stop.py::test_stop_lock_is_taken_before_the_journal_read | as above | T8,T11 | B |
| 132 | F5.2 | lock at `<root>/s1_locks/<trial_id>/<name>.lock`, outside s1_out | test_s1_a3_locks.py::test_lock_lives_outside_s1_out | path as stated | T3 | B |
| 133 | F5.2 | share mode excludes write/delete; held lock can't be deleted, renamed or replaced | test_s1_a3_locks.py::test_held_lock_cannot_be_deleted_renamed_or_replaced | PermissionError ×3 while a child holds it | T3 | B |
| 134 | F5.2 | the OS releases at process end; live = not acquirable; no PID inference | test_s1_a3_locks.py::test_killed_owner_frees_the_lock | after kill: acquired | T3 | B |
| 135 | F5.3 | a deleted unheld lock file is recreated; deletion is never evidence | test_s1_a3_locks.py::test_deleted_lock_file_is_recreated_and_is_not_evidence | acquired; journal decides | T3 | B |
| 136 | F5.4 | isolated processes, real crashes, concurrent recovery | test_s1_a3_locks.py::test_concurrent_recovery_exactly_one_acquires; test_s1_a3_stage.py::test_concurrent_recovery_appends_exactly_one_created | exactly one acquires; one CREATED | T3,T8 | B |
| 137 | F5.5 | exactly three results; an I/O error fails closed | test_s1_a3_locks.py::test_io_error_is_error_not_held_or_free; test_s1_a3_locks.py::test_sharing_violation_from_any_holder_is_held | LockError / LockHeld | T3 | B |
| 138 | F6.1 | each ACK: exact fields in order, sender/recipient/key | test_s1_a3_trial.py::test_ack_lines_have_exactly_the_listed_fields_in_order[7 kinds]; ::test_ack_line_deviation_refuses[extra,missing,reordered,bad-hex,bad-uuid] | parse ok / ValueError | T4 | B |
| 139 | F6.1 | created strictly after the predecessor's and after any referenced journal row | test_s1_a3_trial.py::test_ack_created_not_after_its_predecessor_or_referenced_row_refuses[equal-pred,before-row] | Refusal | T4 | B |
| 140 | F6.2 | trial_id uuid4 generated at write_plan and recorded in plan.json | test_s1_a3_trial.py::test_write_plan_records_a_uuid4_trial_id_and_makes_no_request_callback_or_journal_write | uuid4 in plan; journal empty; spies zero | T4 | B |
| 141 | F6.2 | a trial_id on more than one AUDIT-ACK refuses every trial with that id | test_s1_a3_trial.py::test_duplicate_trial_id_refuses_every_trial_with_that_id | Refusal | T4 | B |
| 142 | F6.2 | every generated artifact records trial_id and is validated against it | test_s1_a3_stage.py::test_every_stage_artifact_records_and_is_validated_against_the_trial_id | wrong trial_id inside a member -> INVALID stage-replaced | T8 | B |
| 143 | F6.3 | exactly one open trial (positive); zero refuses; two+ refuse and escalate; unreadable outage | test_s1_a3_trial.py::test_open_trial_cases[one,zero,two,outage] | Trial / Refusal ×3 | T4 | B |
| 144 | F6.4 | expected bundle = AUDIT-ACK's; mismatch before any row -> refusal | test_s1_a3_gate.py::test_bundle_mismatch_before_any_journal_row_is_a_refusal | refusal, no row, no aborted.json | T5 | B |
| 145 | F6.4 | mismatch after any row -> INVALIDATE (bundle) + local abort, whatever the bootstrap files | test_s1_a3_gate.py::test_bundle_mismatch_after_any_journal_row_is_invalid_bundle | TRIAL-INVALID reason/bundle; aborted.json reason bundle | T5 | B-old |
| 146 | F6.5 | another trial's ACK or row never counts, even same bundle | test_s1_a3_trial.py::test_other_trials_acks_and_rows_never_count_even_with_the_same_bundle | ignored / refusal | T4 | B |
| 147 | F6.6 | total loss of s1_out -> INVALIDATE (LOST); restoring stays invalid | test_s1_a3_gate.py::test_total_loss_is_invalid_lost_and_restoring_stays_invalid | INVALID LOST; restored -> refused, zero callbacks | T5 | B |
| 148 | F7.1 | chain AUDIT<-OPENING<-RUN<-PREREG<-ACQUIRE<-SCORE, CLOSE after any | test_s1_a3_trial.py::test_ack_chain_prev_is_the_predecessor_mailbox_id[*] | ok / Refusal | T4 | B |
| 149 | F7.1 | a second ACK of a kind (byte-identical included) refuses all and escalates | test_s1_a3_trial.py::test_second_ack_of_a_kind_refuses_even_byte_identical[distinct,identical] | Refusal | T4 | B |
| 150 | F7.1 | journal_seq/head: the journal extends that head without a fork | test_s1_a3_trial.py::test_journal_seq_and_head_must_be_extended_without_fork[ok,wrong-head,seq-beyond,forked] | ok / Refusal | T4 | B |
| 151 | F7.2 | OPENING-ACK verified against the journal (first QUALIFIED slot, seal/receipt hashes, head) | test_s1_a3_prestart.py::test_start_attest_verifies_the_opening_ack_against_the_journal[ok,not-first-qualified,seal-differs,receipt-differs,head-forked,a-slot-not-terminal]; rows 279–280 (evidence manifest) | ok / REFUSE, zero callbacks | T10 | B |
| 152 | F7.2 b-d (literal, OQ-37) | issuance: EVERY scheduled slot of the opening close terminal; any in-flight or not-yet-finalized slot blocks; earlier FAILED/TIMEOUT/MISSED legitimate | test_s1_a3_prestart.py::test_opening_issuance_helper[all-terminal-eligible,early-failed-then-qualified-all-terminal,later-slot-unfinalized-blocks,pending-blocks,missed-then-qualified-all-terminal] | eligible / eligible / blocked / blocked / eligible | T10 | B |
| 153 | F7.2 e | Codex re-hash after issuing | n/a | procedural on Codex's side; S1 counterpart is row 154 | — | proc |
| 154 | F7.3, E5.5 | live-file check at every stage callback after the OPENING-ACK: F3/F4 committed hashes, the journal head, and the reconstructed evidence manifest | test_s1_a3_prestart.py::test_a_change_after_the_opening_ack_is_caught_by_the_live_file_check; rows 279–280 | INVALID (stage-replaced: the opening stage's bound input changed), zero callbacks | T10 | B-old |
| 155 | F7.4 | OPENING-ACK by the START-attestation lead, else no START | test_s1_a3_prestart.py::test_missed_opening_ack_deadline_gives_no_start | start_attest refuses with no row; prereg unreachable | T10 | B |
| 156 | F7.4 | RUN-ACK with the new fields required for prereg | test_s1_a3_prestart.py::test_prereg_requires_the_run_ack_with_trial_prev_and_journal_fields[ok,old-format,wrong-prev] | ok / REFUSE | T10 | B |
| 157 | F7.4 | PREREG-ACK required before any post-START capture | test_s1_a3_slots.py::test_post_start_capture_requires_the_prereg_ack | SLOT-INTENT REFUSE, zero captures; with PREREG-ACK -> INTENT | T6 | B |
| 158 | F7.5 as clarified by E4.4 | CLOSE fields; a CLOSE candidate is refused when prev is not the latest ACK, it is before the AUDIT-ACK, its bundle differs, or it is a duplicate; a wrong-role/key CLOSE is no candidate (rows 275–277) | test_s1_a3_trial.py::test_close_refused_cases[valid,prev-not-latest,before-audit,wrong-bundle,duplicate] | valid closes; others: trial stays open, commands refuse | T4 | B |
| 159 | F7.5 | evidence_sha256 = score record / first TRIAL-INVALID line / withdrawal message | test_s1_a3_trial.py::test_close_evidence_hashes[SCORED,INVALID,WITHDRAWN] | as stated | T4 | B |
| 160 | F7.5 | closure never erases invalidity, never makes ACKs or the journal reusable | test_s1_a3_gate.py::test_closure_never_erases_invalidity_or_reuses_the_journal | closed trial's rows/ACKs never count for a new trial_id | T5 | B |
| 161 | F8.1 | violation, journal insert fails, restore + delete witnesses, restart: may resume, labelled lost detection | test_s1_a3_residual.py::test_uncommitted_detection_may_resume_and_is_labelled_lost_detection | resumes; evidence note "lost detection, not equivalence" | T14 | ctrl |
| 162 | F8.1 | never covers loss/bypass of a committed row; INVALID committed before the crash keeps restoration invalid | test_s1_a3_residual.py::test_invalid_committed_before_the_crash_keeps_restoration_invalid | refused, zero callbacks | T14 | B |
| 163 | F8.3 | journal outage fails closed, never a retry under the same intent | test_s1_a3_journal.py::test_concurrent_append_is_serialized_and_a_busy_mailbox_is_an_outage; test_s1_a3_stage.py::test_pre_intent_outage_makes_no_request_and_no_artifact | Outage, no row, no work | T1,T8 | B |
| 164 | F8.4 | crash between INTENT and PREPARED terminates the trial | row 124 | INVALID stage-incomplete | T8 | B |
| 165 | F8.5 | structural provider failure in audit/final -> INVALID, no retry | test_s1_a3_audit.py::test_provider_anomaly_keeps_aborted_staging_no_prepared_and_invalidates; test_s1_a3_final.py::test_final_provider_anomaly_after_the_stop_is_invalid_with_no_retry | INVALID; re-run refused | T9,T12 | B |
| 166 | F8.6 | Codex's issuance checks are procedural | n/a | procedural | — | proc |
| 167 | F8.7 | R-3 stays OPEN | n/a | process section; no live/scheduler step | — | proc |
| 168 | F9 | only write_plan runs without an open trial; no request, callback, journal write or priced work | test_s1_a3_trial.py::test_write_plan_records_a_uuid4_trial_id_and_makes_no_request_callback_or_journal_write | as stated | T4 | retro |
| 169 | F9 | do_audit after the AUDIT-ACK as stage `audit`; its INTENT commits the audit policy | test_s1_a3_audit.py::test_audit_runs_as_a_stage_only_after_the_audit_ack | before: refusal, zero requests; after: INTENT with policy | T9 | B |
| 170 | F9 | after the AUDIT-ACK, write_plan refuses for the open trial | test_s1_a3_trial.py::test_write_plan_refuses_with_an_open_trial_or_an_unreadable_mailbox[open,outage] | SystemExit; no plan written | T4 | B |
| 171 | F10 probes | historical probe file and XML frozen | test_s1_a3_codex_probes.py::test_historical_probe_copies_are_frozen | sha256 equal to the recorded list | T5 | static |
| 172 | F10 probes | D-1µs qualifies when no TIMEOUT committed first | test_s1_a3_codex_probes.py::test_publication_d_minus_1us_qualifies_when_no_timeout_committed_first | QUALIFIED, seal written | T6 | ctrl |
| 173 | F10 probes | D and D+1µs do not seal | test_s1_a3_codex_probes.py::test_publication_at_d_and_d_plus_1us_does_not_seal[0,1] | REFUSE, no seal; later TIMEOUT | T6 | B-old |
| 174 | F10 probes | a before-D positive control | test_s1_a3_codex_probes.py::test_publication_well_before_d_seals | QUALIFIED, seal | T6 | ctrl |
| 175 | F10 probes | P/R/J/T races | test_s1_a3_codex_probes.py::test_race_t_commits_then_j_is_lost_race, ::test_race_j_commits_then_stale_t_is_lost_race, ::test_race_two_finalizers_one_terminal, ::test_race_p_without_j_restart_ends_in_timeout | as named | T7 | B |
| 176 | F10 probes | old behavioural failures recorded separately from fixture incompatibilities | evidence a3/codex_probes_old_new.md | two separate sections | T14 | proc |
| 177 | F10 probes | V1: INVALID | test_s1_a3_codex_probes.py::test_v1_selective_deletion_is_invalid | INVALID; attestation refused; zero callbacks | T10 | B-old |
| 178 | F10 probes | "A fully deleted, then B": INVALID or B never ACK-eligible | test_s1_a3_codex_probes.py::test_a_fully_deleted_then_b_is_invalid_or_never_ack_eligible | INVALID LOST; B refused | T10 | B-old |
| 179 | F10 probes | combined damage: INVALID (bundle) after any journal row | test_s1_a3_codex_probes.py::test_combined_damage_is_invalid_bundle_after_any_journal_row[missing,unparseable] | INVALID bundle; restore -> refused | T5 | B-old |
| 180 | F10 probes | prereg restoration invalid once CREATED; before CREATED follows the F4 table | test_s1_a3_codex_probes.py::test_prereg_restoration_is_invalid_once_created; ::test_prereg_before_created_follows_the_stage_table[intent-only-free,prepared-free] | INVALID stage-replaced; stage-incomplete / recovery | T10 | B-old |
| 181 | F10 CH1 | normal lot-count stop: stop_attest -> final_plan -> ACQUIRE-ACK (>= 3rd session) -> final -> SCORE-ACK -> score, numeric, no INVALID, valid prev chain | test_s1_a3_score.py::test_lot_count_stop_reaches_a_numeric_score_with_no_invalid_row | SHADOW PASS or FAIL; journal has no TRIAL-INVALID | T13 | B |
| 182 | F10 CH1 | normal six-month stop: same | test_s1_a3_score.py::test_six_month_stop_reaches_a_numeric_score_with_no_invalid_row | numeric; no INVALID | T13 | B |
| 183 | F10 CH1 | no provider call before stop_attest and the ACQUIRE-ACK | row 61 | zero requests | T12 | B |
| 184 | F10 CH1 | final_plan before stop_attest refuses with no row | test_s1_a3_stop.py::test_final_plan_before_stop_attest_refuses_with_no_row | REFUSE, no row | T11 | B |
| 185 | F10 CH1 | post-STOP sampled slot excluded; post-stop historical prices used | rows 62, 63 | as stated | T11,T13 | B |
| 186 | F10 CH1 | post-STOP SLOT-INTENT for a new slot: LOST-RACE, no capture | test_s1_a3_slots.py::test_post_stop_new_slot_intent_is_lost_race_with_no_capture | LOST-RACE; spies zero | T6 | B |
| 187 | F10 CH1, E2 | post-STOP new seal forbidden, including a pre-STOP QUALIFIED whose seal was unpublished | rows 55, 260–263 | no seal; missing required seal INVALID | T7,T11 | B |
| 188 | F10 CH1 | post-STOP SLOT-INTENT for a slot with a row: INVALID repeat-attempt | test_s1_a3_slots.py::test_post_stop_repeat_slot_intent_is_invalid_repeat_attempt | INVALID repeat-attempt | T6 | B |
| 189 | F10 CH1 | an in-flight slot started before the stop completes but never enters final or score | test_s1_a3_stop.py::test_in_flight_slot_started_before_the_stop_completes_but_never_enters_final_or_score | QUALIFIED appended; absent from final_plan/score inputs | T11 | B |
| 190 | F10 CH1 | stop.json publication gap recovers; deleting after a finalization INTENT is INVALID; restoration doesn't resume | rows 66, 68 | as stated | T11 | B |
| 191 | F10 CH1 | INVALID never reaches a numeric score | test_s1_a3_score.py::test_invalid_never_reaches_a_numeric_score | refused; no score/s1.json; valuation spy zero | T13 | B-old |
| 192 | F10 CH1 | a STOP with a different detail: INVALID stop-conflict | test_s1_a3_stop.py::test_a_stop_with_a_different_detail_is_invalid_stop_conflict | INVALID stop-conflict | T11 | B |
| 193 | F10 CH2 | T commits, then J: TIMEOUT stays, no seal, LOST-RACE, no INVALID | row 72 | as stated | T7 | B |
| 194 | F10 CH2 | J commits, then a stale finalizer: QUALIFIED stays, LOST-RACE | test_s1_a3_codex_probes.py::test_race_j_commits_then_stale_t_is_lost_race | as stated | T7 | B |
| 195 | F10 CH2 | two finalizers race: exactly one terminal row | test_s1_a3_codex_probes.py::test_race_two_finalizers_one_terminal | one TIMEOUT (processes) | T7 | B |
| 196 | F10 CH2 | a new SLOT-INTENT after a terminal row: INVALID repeat-attempt | test_s1_a3_slots.py::test_new_slot_intent_after_a_terminal_row_is_invalid_repeat_attempt | INVALID | T6 | B |
| 197 | F10 CH2 | QUALIFIED foreign op/actor or no INTENT: INVALID, even when terminal | row 25 + test_s1_a3_slots.py::test_foreign_qualified_is_invalid_even_on_a_terminal_slot | INVALID contradictory-completion | T2,T6 | B |
| 198 | F10 CH2 | a restarted process doesn't append QUALIFIED; the slot ends TIMEOUT at D | rows 73, 74 | as stated | T6,T7 | B |
| 199 | F10 CH2 | a stale finalizer's LOST-RACE moves none of the winner's files; the recheck passes | test_s1_a3_finalizer.py::test_stale_finalizer_moves_none_of_the_winners_files_and_the_recheck_passes | as stated | T7 | B |
| 200 | F10 CH2 | MISSED against QUALIFIED -> LOST-RACE (4c), not refusal | row 33 [4c-m-after-qualified] | LOST-RACE | T2 | B |
| 201 | F10 CH2 | TIMEOUT with foreign op on a terminal slot -> INVALID (4a) | row 26 [4a-t-foreign-op-on-terminal] | INVALID | T2 | B |
| 202 | F10 CH2 | STOPPED + SLOT-INTENT for a terminal slot -> INVALID repeat-attempt | row 29 [4b-si-stopped-terminal] | INVALID | T2 | B |
| 203 | F10 CH2 | a finalizer before E or D refuses with no row | rows 45, 46 | REFUSE | T2 | B |
| 204 | F10 CH2 | any append to a CLOSED trial refuses | row 23 | REFUSE | T2 | B |
| 205 | F10 CH2, E1.3 | a late R refuses with no row, then TIMEOUT (the TIMEOUT does not wait for the worker) | test_s1_a3_finalizer.py::test_late_r_refuses_with_no_row_then_timeout | REFUSE; TIMEOUT at D; cleanup only once the work lock is acquirable | T7 | B |
| 206 | F10 FINAL-2 | A: INTENT+PREPARED, matching bytes published, dies; B takes the lock, appends CREATED (op A, actor B), no recompute/refetch, no INVALID | row 100 (child-process A killed) | as stated | T8 | B |
| 207 | F10 FINAL-2 | B with foreign op, missing PREPARED or changed bytes: INVALID | row 101 | INVALID | T8 | B |
| 208 | F10 FINAL-2 | B never appends PREPARED for A's op | test_s1_a3_stage.py::test_recovery_never_appends_prepared_for_another_actors_op | INVALIDATE contradictory-stage if attempted; recover() has no PREPARED path | T8 | B |
| 209 | F10 FINAL-3 | unpredictable next_page_token, varying valid page count: completes; provenance records every request | row 96 | as stated | T9 | B |
| 210 | F10 FINAL-3 | wrong endpoint, changed base scope, new host, redirect, repeated token, > max_pages: Structural, no further request, INVALID | row 97 | as stated | T9 | B |
| 211 | F10 FINAL-3 | no request is sent that isn't in provenance (HTTP spy) | row 98 | as stated | T9 | B |
| 212 | F10 FINAL-3 | lock acquisition I/O error: refuse with no row, no liveness verdict | test_s1_a3_stage.py::test_lock_io_error_refuses_with_no_row_and_no_liveness_verdict | REFUSE; no INVALID; no recovery | T8 | B |
| 213 | F10 A3-R3C-1 | normal audit: calendar + CA batches authorized; normal final: raw/SIP bars + window + full-history CA; every F4.9 member committed at PREPARED | test_s1_a3_audit.py::test_normal_audit_authorizes_calendar_and_ca_batches_and_commits_every_member; test_s1_a3_final.py::test_normal_final_commits_every_member | as stated | T9,T12 | B |
| 214 | F10 A3-R3C-1 | another paper-api path, any other host, redirect, base/batch outside F4.9, second calendar request: Structural, no further request, INVALID | rows 93, 97 | as stated | T9 | B |
| 215 | F10 A3-R3C-1 | changing/deleting any raw CA page (audit, final/pages, final/pages_full) or derived member (calendar.json, bars.json, bar_problems.json, corporate_actions.json, ca_problems.json, manifest.json, score/s1.json): INVALID before valuation/scoring, zero valuation calls | row 117 + test_s1_a3_score.py::test_score_member_changed_is_invalid + rows 281–282 (raw capture backup, opening receipt, final-snapshot report) | INVALID stage-replaced / registration-artifact; valuation spy zero | T9,T12,T13 | B |
| 216 | F10 A3-R3C-1 | extra page without provenance, provenance without page: INVALID | test_s1_a3_audit.py::test_extra_page_or_orphan_provenance_is_invalid[extra-page,missing-page]; test_s1_a3_final.py::test_final_extra_page_or_orphan_provenance_is_invalid[*] | INVALID stage-replaced | T9,T12 | B |
| 217 | F10 A3-R3C-1 | empty ca_symbols_window or ca_symbols_full_history: zero requests for that family; final completes | test_s1_a3_final.py::test_empty_ca_family_sends_no_request_and_final_completes[window,full_history,both] | as stated | T12 | retro |
| 218 | F10 A3-R3C-1 | a score computation error: INVALID score-aborted, no numeric score | row 118 | as stated | T13 | B |
| 219 | F10 CH3 | arbitrary valid pages unknown at INTENT: audit completes (no prefetch) | row 96 | as stated | T9 | B |
| 220 | F10 CH3 | crash after INTENT, before PREPARED: INVALID stage-incomplete, no refetch | row 124 (child process killed after INTENT) | HTTP spy: no request on re-run | T8 | B |
| 221 | F10 CH3 | crash after PREPARED, before CREATED: only matching bytes recover; changed bytes INVALID | rows 100, 101 | as stated | T8 | B |
| 222 | F10 CH3 | retrieved_utc is the actual observation instant | row 90 | as stated | T9 | B |
| 223 | F10 CH4 | observe, fail the insert, restore, delete witnesses, restart: may resume; labelled lost detection | row 161 | as stated | T14 | ctrl |
| 224 | F10 CH4 | INVALID committed before the crash: same restoration stays invalid | row 162 | as stated | T14 | B |
| 225 | F10 R2-1 | commit a stage, delete its artifact, INVALID commits, restore everything, delete local witnesses, restart: still invalid, zero callbacks | test_s1_a3_stage.py::test_commit_delete_detect_restore_is_still_invalid_with_zero_callbacks | as stated | T8 | B-old |
| 226 | F10 R2-1 | a repeat-stage attempt gives INVALID | test_s1_a3_stage.py::test_repeat_stage_intent_is_invalid | INVALID repeat-stage | T8 | B |
| 227 | F10 R2-1 | a restored total loss stays invalid | row 147 | as stated | T5 | B |
| 228 | F10 R2-2 | pause after INTENT with a live owner: a concurrent gate gives pending, no work | test_s1_a3_stage.py::test_pause_after_intent_with_a_live_owner_is_pending | refusal "pending"; spies zero; child process holds the lock | T8 | B |
| 229 | F10 R2-2 | pause after PREPARED, fail CREATED, restart: recovery appends CREATED, no recreation | test_s1_a3_stage.py::test_created_failure_then_restart_recovers_without_recreation | CREATED; work spy zero | T8 | B |
| 230 | F10 R2-2 | a MISSED slot with a stray file: INVALID | row 80 [missed-stray] | INVALID | T7 | B |
| 231 | F10 Locks | a killed owner frees the lock; recovery follows the tables | row 134 + row 100 | as stated | T3,T8 | B |
| 232 | F10 Locks | a held lock can't be deleted or replaced | row 133 | as stated | T3 | B |
| 233 | F10 Locks | a leftover acquirable lock file is not liveness | test_s1_a3_locks.py::test_leftover_acquirable_lock_file_is_no_liveness | acquired | T3 | B |
| 234 | F10 Identity | exactly one valid open trial authorizes a stage | test_s1_a3_gate.py::test_one_valid_open_trial_authorizes_a_stage | gate returns; stage runs | T5 | ctrl |
| 235 | F10 Identity | zero open trials refuses, zero callbacks | test_s1_a3_gate.py::test_identity_refusals_have_zero_callbacks[zero-open] | refusal, spies zero | T5 | B |
| 236 | F10 Identity | two open trials | …[two-open] | same | T5 | B |
| 237 | F10 Identity | a duplicate trial_id | …[duplicate-trial-id] | same | T5 | B |
| 238 | F10 Identity as clarified by E4.4 | a wrong-role CLOSE is ignored: the trial stays open and its commands follow their gates | test_s1_a3_gate.py::test_wrong_role_close_is_ignored_and_the_trial_stays_open | gate returns ACTIVE; no closure; no refusal from the line | T5 | B |
| 239 | F10 Identity | a wrong-bundle CLOSE | …[wrong-bundle-close] | same | T5 | B |
| 240 | F10 Identity | a CLOSE before AUDIT | …[close-before-audit] | same | T5 | B |
| 241 | F10 Identity | two OPENING-ACKs | …[two-opening-acks] | same | T5 | B |
| 242 | F10 Identity | a byte-identical duplicate ACK | …[identical-duplicate-ack] | same | T5 | B |
| 243 | F10 Identity | a broken prev | …[broken-prev] | same | T5 | B |
| 244 | F10 Identity | a closed trial's same-bundle ACK | …[closed-trial-same-bundle-ack] | same | T5 | B |
| 245 | F10 Identity | a journal fork | …[journal-fork] | same | T5 | B |
| 246 | F10 Identity | a journal gap | …[journal-gap] | same | T5 | B |
| 247 | F10 Identity | a duplicate seq | …[duplicate-seq] | same | T5 | B |
| 248 | F10 Identity | plan.json trial_id differing from the AUDIT-ACK | …[plan-trial-id-differs] | same | T5 | B |
| 249 | F10 Other | issuance: an early FAILED then a QUALIFIED slot is eligible | row 152 [early-failed-then-qualified] | eligible | T10 | B |
| 250 | F10 Other | issuance: a PENDING slot blocks | row 152 [pending-blocks] | blocked | T10 | B |
| 251 | F10 Other | a change after the ACK is caught by F7.3 | row 154 | INVALID | T10 | B-old |
| 252 | F10 Other | a missed OPENING-ACK deadline gives no START | row 155 | no START | T10 | B |
| 253 | F10 Other | pre-audit: write_plan in a fresh directory makes no callbacks | row 140 | spies zero | T4 | retro |
| 254 | F10 Other | before the AUDIT-ACK, the opening and START are blocked | test_s1_a3_gate.py::test_before_the_audit_ack_the_opening_and_start_are_blocked | refusal, zero callbacks | T5 | B |
| 255 | F10 Other | matrix: every non-empty subset of the 9 elements × {bundle same, changed} × {deleted, changed, unparseable} at each commitment point. The 10 points are 9 commitment points (audit, opening, start_attest, prereg, TRIAL-STOP+stop.json, stop_attest, final_plan, final, score) plus the OPENING-ACK point. "Audit tree" means every file under s1_out/audit/ | test_s1_a3_matrix.py::test_matrix (exhaustive when S1_MATRIX_FULL=1: 511×2×3×10 = 30,660 cases; default: singletons, pairs, complements, full set) | the oracle's outcome; zero callbacks on every refusal/INVALID. INTENT/PREPARED boundaries are covered by the per-stage state-table tests (rows 122–129, 180, 228–229), not by the matrix; the matrix claims no more | T14 | B |
| 256 | E1.2, E1.7a, PLAN-1 | a real child holds `slot-<s>` and stays alive and blocked past D; a competing finalizer at D appends TIMEOUT | test_s1_a3_finalizer.py::test_timeout_commits_at_d_while_a_live_worker_holds_the_work_lock | TIMEOUT row (op = the child's INTENT op, actor = finalizer); child still alive; no INVALID | T7 | B |
| 257 | E1.3, E1.4, E1.7a | the live child's later QUALIFIED request is REFUSE (R >= D) or LOST-RACE (R < D, after TIMEOUT); no seal; its files are not moved while it lives | test_s1_a3_finalizer.py::test_live_worker_after_timeout_is_refuse_or_lost_race_and_its_files_stay[late-r,early-r] | REFUSE / LOST-RACE; claim and capture still in captures/ until the child exits; then its own move to late/ (LOST-RACE) or the deferred cleanup | T7 | B |
| 258 | E1.2 | the finalizer's TIMEOUT/MISSED decisions never take, wait for or test the work lock | test_s1_a3_finalizer.py::test_finalizer_decision_never_touches_the_work_lock | lock spy: no `slot-*` acquire before or during the TIMEOUT/MISSED append | T7 | B |
| 259 | E1.4, OQ-13 | leftover cleanup after TIMEOUT runs only when the work lock is acquirable; deferred otherwise; it never affects a decision | test_s1_a3_finalizer.py::test_timeout_cleanup_waits_for_the_work_lock | while held: files stay, deferred note; after release: own-op files to late/; decisions identical | T7 | B |
| 260 | E2.1, E2.7 (1), PLAN-2 | a QUALIFIED committed before the STOP whose seal becomes determined only after the STOP (an earlier slot still in flight): once TRIAL-STOP is committed no seal is ever written, including by a finalizer that read state before the STOP | test_s1_a3_finalizer.py::test_no_seal_after_stop_even_for_a_pre_stop_qualified | no seal file; refusal "outside ACTIVE" in STOPPED | T7 | B |
| 261 | E2.3, E2.7 (2) | publish-then-STOP race: the publisher holds the stop lock; the stop side finds it held, then sees the published seal | test_s1_a3_finalizer.py::test_seal_publication_and_stop_race[publish-first] | seal published while ACTIVE; TRIAL-STOP after it; no post-STOP seal | T7 | B |
| 262 | E2.3, E2.5, E2.6, E2.7 (2) | STOP-then-publish race: the stop side holds the stop lock; the publisher finds it held, makes no change and returns pending (E2.6); after TRIAL-STOP it publishes nothing. The stop operation itself publishes every determined unpublished seal before TRIAL-STOP (E2.5) | test_s1_a3_finalizer.py::test_seal_publication_and_stop_race[stop-first]; test_s1_a3_stop.py::test_decide_stop_publishes_every_sampled_seal_before_trial_stop | pending while held; no seal written after STOP; decide_stop's seal publication precedes its TRIAL-STOP append | T7,T11 | B |
| 263 | E2.2, E2.7 (3) | a missing required (published-committed) seal after STOP is INVALID (registration-artifact), never recreated | test_s1_a3_finalizer.py::test_missing_required_seal_after_stop_is_invalid | INVALID; the file still absent; zero callbacks | T7 | B |
| 264 | E5.2, OQ-11, PLAN-4 | after.json is display only: deleting or tampering with it changes no decision | test_s1_a3_slots.py::test_after_json_is_display_only[deleted,tampered] | gate outcome, required seals and stop record identical to the untouched run | T6,T7 | B |
| 265 | E2.4 r1, OQ-14 | a published-committed seal (listed by a committed QUALIFIED tree's `seals_checked`), deleted while ACTIVE, is INVALID and never recreated; a determined seal NOT yet published-committed may be published once with exactly its recomputed bytes | test_s1_a3_finalizer.py::test_previously_required_seal_deleted_is_invalid_and_never_recreated; test_s1_a3_finalizer.py::test_seal_publication_and_stop_race[publish-first] (the not-yet-required republication) | INVALID registration-artifact, no publication / first publication allowed | T7 | B |
| 266 | E2.4 r1, OQ-11 | required seal membership comes from committed history: the pre-J report's `seals_checked` is in the QUALIFIED tree | test_s1_a3_slots.py::test_reports_record_seals_checked_in_the_tree | report `seals_checked` == {relpath: sha} of the published seals; changing it changes the tree detail | T6 | B |
| 267 | E5.6, OQ-32, PLAN-4 | raw capture backup change/deletion on a QUALIFIED slot | test_s1_a3_finalizer.py::test_slot_evidence_table[qualified-backup-changed,qualified-backup-deleted] | INVALID registration-artifact | T7 | B |
| 268 | OQ-15 | opening_books.json is a hash-bound derived input of the single start_attest stage | test_s1_a3_prestart.py::test_opening_books_is_a_hash_bound_derived_input[changed,deleted] | after start_attest CREATED: change or deletion -> INVALID stage-replaced; before INTENT: a differing pre-existing file refuses the attestation | T10 | B |
| 269 | F7.2(b) literal, OQ-37 | start_attest refuses when any scheduled opening-close slot lacks a terminal row in the OPENING-ACK prefix | test_s1_a3_prestart.py::test_start_attest_requires_every_opening_close_slot_terminal_in_the_ack_prefix | REFUSE, no row | T10 | B |
| 270 | F3, OQ-37 | the opening slot is the earliest QUALIFIED, independent of issuance | test_s1_a3_prestart.py::test_opening_slot_is_the_earliest_qualified_independent_of_issuance | OPENING-ACK opening_slot must equal the earliest QUALIFIED even when later slots also qualified | T10 | B |
| 271 | E3.6a (pending E3) | BLOCKED inputs: blocked.json written, no journal row, ACTIVE, zero captures/requests/valuation | test_s1_a3_prestart.py::test_blocked_prereg_is_a_pre_intent_refusal_record | as stated | T10 | B |
| 272 | E3.6b (pending E3) | deleting blocked.json and re-running gives the same refusal and an identical recomputation of the reasons | test_s1_a3_prestart.py::test_blocked_rerun_after_deletion_recomputes_identically | same SystemExit text; same reasons; still no row | T10 | B |
| 273 | E3.4 r1, E3.6c (pending E3) | a CLOSE with reason BLOCKED whose evidence hash is wrong is refused; a correct one closes; h = sha256(c.canonical({trial_id, reasons})), never the file bytes | test_s1_a3_trial.py::test_close_blocked_evidence_hash[ok,wrong] (unit, recomputation stubbed); test_s1_a3_prestart.py::test_close_blocked_evidence_hash_end_to_end[ok,wrong] | ok: zero open trials; wrong: Refusal (trial stays open); h != sha256 of blocked.json bytes | T4,T10 | B |
| 274 | E3.6d (pending E3) | a non-BLOCKED prereg is unaffected | test_s1_a3_prestart.py::test_non_blocked_prereg_is_unaffected | prereg CREATED; no blocked.json | T10 | ctrl |
| 275 | E4.2, E4.4, PLAN-5 | CLOSE-looking lines outside the official channel are never candidates | test_s1_a3_trial.py::test_non_official_lines_are_never_candidates[wrong-role-close,wrong-key-close] | ignored: the trial stays open, nothing refuses | T4 | B |
| 276 | E4.2, PLAN-5 | arbitrary peer drafts, indented or quoted token lines in any message are ignored | test_s1_a3_trial.py::test_non_official_lines_are_never_candidates[peer-draft,indented-line,quoted-line] | ignored | T4 | B |
| 277 | E4.2, PLAN-5 | historical messages of another (closed) trial never count or refuse | test_s1_a3_trial.py::test_non_official_lines_are_never_candidates[historical-other-trial] | ignored for the open trial | T4 | B |
| 278 | E4.3 r1 | a malformed official candidate refuses its own trial if its trial_id parses (second whitespace-separated token exactly `trial_id=<canonical lowercase uuid4>`), else all trials | test_s1_a3_trial.py::test_malformed_candidate_refuses_its_own_trial_or_all[attributable,unattributable]; test_s1_a3_trial.py::test_attribution_grammar_is_the_e43_grammar | attributable: that trial refused, another open trial unaffected; unattributable: every trial-bound command refuses | T4 | B |
| 279 | E5.5 (r1), F7.3, OQ-17, PLAN-4 | the reconstructed evidence manifest (exact E5.5 format and membership, staging intent/prepared included as `staging/<stage>/<name>`) must hash to the OPENING-ACK's evidence_manifest_sha256 | test_s1_a3_prestart.py::test_opening_ack_evidence_manifest_is_reconstructed[ok,wrong-hash] | ok passes; a wrong hash with an otherwise valid journal and files: INVALIDATE (registration-artifact), zero callbacks, no start_attest row | T10 | B |
| 280 | E5.5 (r1), F7.3, OQ-17 | a manifest with the wrong membership (the opening receipt omitted; or the rev-0 membership without staging files) | test_s1_a3_prestart.py::test_opening_ack_evidence_manifest_is_reconstructed[wrong-membership-receipt,wrong-membership-staging] | INVALIDATE (registration-artifact) | T10 | B |
| 281 | coverage 117/215, OQ-16 | damaged opening receipt or final-snapshot report: INVALID before scoring, zero valuation calls | test_s1_a3_score.py::test_damaged_receipt_or_final_snapshot_is_invalid_before_scoring[receipt,snapshot-report] | INVALID; valuation spy zero | T13 | B |
| 282 | coverage 70/77/117 | damaged raw backup of a sampled seal's capture: INVALID before scoring | test_s1_a3_score.py::test_damaged_capture_backup_is_invalid_before_scoring | INVALID registration-artifact; valuation spy zero | T13 | B |
| 283 | PLAN-6, map 255 | the matrix's declared points, elements and damage scopes are exactly the stated ones | test_s1_a3_matrix.py::test_matrix_scope_is_the_declared_scope | POINTS has 10 entries; "audit tree" damages every file under audit/ | T14 | static |
| 284 | PLAN-6 | Cosmic Ray on s1_journal.py with its A3 tests | evidence a3/t15_cr_s1_journal.txt | survivors, timeouts and untested listed separately; every survivor triaged (killed by a new test, or argued equivalent) | T15 | proc |
| 285 | PLAN-6 | Cosmic Ray on s1_locks.py | a3/t15_cr_s1_locks.txt | as row 284 | T15 | proc |
| 286 | PLAN-6 | Cosmic Ray on s1_trial.py | a3/t15_cr_s1_trial.txt | as row 284 | T15 | proc |
| 287 | PLAN-6 | Cosmic Ray on s1_slot.py | a3/t15_cr_s1_slot.txt | as row 284 | T15 | proc |
| 288 | PLAN-6 | Cosmic Ray on s1_stage.py | a3/t15_cr_s1_stage.txt | as row 284 | T15 | proc |
| 289 | PLAN-6 | Cosmic Ray on the changed s1_seal.py functions (stop_record, decide_stop, stop_check, sampled_seals, sampled_history) | a3/t15_cr_s1_seal.txt | as row 284 | T15 | proc |
| 290 | PLAN-6 | Cosmic Ray on the changed s1_collect.py functions (audit_policy, final_policy, _Authorizer, _get, _paged, do_audit, do_final) | a3/t15_cr_s1_collect.txt | as row 284 | T15 | proc |
| 291 | PLAN-6 | targeted mutant: deadline comparisons (`>=` -> `>`, `<` -> `<=`) in decide step 6, ×4 | test_s1_a3_mutants.py::test_targeted_mutant_is_killed[deadline-*] | each mutant killed by a named test | T15 | B |
| 292 | PLAN-6 | targeted mutant: omitted commitments/ACKs (envelope input dropped, verify_ack field skipped, check_journal skipped, evidence-manifest check skipped) | …[omitted-*] | killed | T15 | B |
| 293 | PLAN-6 | targeted mutant: STOP rules (STOP_N `>=` -> `>`, pending exclusion removed, prefix seq `<=` -> `<`) | …[stop-*] | killed | T15 | B |
| 294 | PLAN-6 | targeted mutant: owner/takeover (4a actor check removed, TIMEOUT op check removed, recovery uses own op) | …[owner-*] | killed | T15 | B |
| 295 | PLAN-6 | targeted mutant: wrong CA scope (window/full_history swapped; full_history start = window start) | …[scope-*] | killed | T15 | B |
| 296 | PLAN-6 | targeted mutant: midnight cutoff from the reservation clock | …[cutoff-reservation-clock] | killed | T15 | B |
| 297 | PLAN-6 | targeted mutants for the erratum: the finalizer takes the work lock; a seal is published in STOPPED; a non-official CLOSE counts; the backup is dropped from the tree; after.json is used as authority | …[erratum-*] | killed | T15 | B |
| 298 | PLAN-6 | Hypothesis settings pinned; the example database is kept under evidence | test_s1_a3_mutants.py::test_hypothesis_settings_are_pinned | every @given in test_s1_a3_* has derandomize=True and @seed(20261103) | T15 | static |
| 299 | OQ-3 | op-reuse never hides a repeated opening subject | test_s1_a3_precedence.py::test_precedence_table[4b-si-repeat-with-reused-op,4b-gi-repeat-with-reused-op] | INVALIDATE repeat-attempt / repeat-stage | T2 | B |
| 300 | OQ-8 (BLK-3) | lots: the earliest eligible close whose seal reaches 100 sold triggers | test_s1_a3_stop.py::test_stop_dispositions[lots-earliest] | STOPPED at that close; triggering slot = its first QUALIFIED | T11 | B |
| 301 | OQ-8 (BLK-3) | lots: a later close that also qualifies is not chosen | …[lots-later-not-chosen] | earlier close wins | T11 | B |
| 302 | OQ-8 (BLK-3) | TIMEOUT: no lots stop by the deadline; the last sealed eligible close | …[timeout-last-sealed] | TIMEOUT; stop_close = last sealed eligible close | T11 | B |
| 303 | OQ-8 (BLK-3) | NO-VALID-SEAL: no eligible close sealed by the deadline | …[no-valid-seal] | NO-VALID-SEAL; stop_close None | T11 | B |
| 304 | OQ-8, B1.5 (BLK-3) | a pending close (INTENT, no terminal) before the trigger blocks the decision | …[pending-excluded] | None; no row | T11 | B |
| 305 | OQ-8, A5.1 (BLK-3) | eligibility by close instant at the deadline (the 16:00 close on the deadline date is ineligible when START was 09:30) | …[deadline-instant-eligibility] | that close is not eligible | T11 | B |
| 306 | OQ-28 | a `_score` ABORTED-INVALID from integrity checks persists TRIAL-INVALID; report kept in staging; no PREPARED | test_s1_a3_score.py::test_score_integrity_violation_persists_trial_invalid | TRIAL-INVALID registration-artifact with the reasons; no score/ in s1_out | T13 | B |
| 307 | OQ-28 | INSUFFICIENT/INCONCLUSIVE without integrity violation stay valid committed scores | test_s1_a3_score.py::test_non_integrity_dispositions_stay_valid[insufficient,inconclusive] | score CREATED; no TRIAL-INVALID | T13 | ctrl |
| 308 | OQ-31, E5.1 | established-violation is external first, with subtype and legacy reason | test_s1_a3_slots.py::test_established_violation_is_external_first_with_subtype[receipt,binding,fence] | TRIAL-INVALID committed before aborted.json exists; observation subtype/legacy_reason exact | T6 | B |
| 309 | OQ-23 | lock names and trial_ids are validated (no traversal or aliasing) | test_s1_a3_locks.py::test_lock_names_and_trial_ids_are_validated[dotdot-name,slash-name,unknown-stage,bad-trial] | LockError; no file created outside s1_locks/<trial>/ | T3 | B |
| 310 | OQ-33 | clock boundaries before capture | test_s1_a3_slots.py::test_clock_boundaries_before_capture[s-1us,s,E-1us,E,E+1us] | s-1µs: claim + FAILED, zero capture; s and E-1µs: capture; E and E+1µs: no row, no claim | T6 | B |
| 311 | OQ-10 | an in-flight capture directory must be the one its claim names | test_s1_a3_finalizer.py::test_slot_evidence_table[in-flight-capture-dir-not-named-by-claim] | INVALID registration-artifact | T7 | B |
| 312 | OQ-36, E5.4 | cross-trial substitution is caught: another trial's commitment (staging prepared.json), its identity-bearing member (audit/attempt.json), or its raw page with different bytes. A byte-identical raw page is the same evidence, and the commitment's trial_id/op still binds it to this trial | test_s1_a3_audit.py::test_cross_trial_substitution_is_invalid[commitment,attempt,page] | INVALID stage-replaced | T9 | B |
| 313 | OQ-2 | gate-generated TRIAL-INVALID rows use a fresh operation identity | test_s1_a3_gate.py::test_gate_invalid_rows_use_a_fresh_operation_identity | op and actor occur in no earlier row | T5 | B |
| 314 | OQ-16 | final snapshot missing/changed: INVALID, not an economic fallback; the command runs only in STOPPED | test_s1_a3_score.py::test_final_snapshot_missing_or_changed_is_invalid_not_a_fallback[missing,changed]; test_s1_a3_score.py::test_final_snapshot_only_in_stopped | TRIAL-INVALID; no numeric score / refusal in ACTIVE, zero captures, no row | T13 | B |
| 315 | OQ-29 | the sampled-history manifest is canonical and fixed at the STOP | test_s1_a3_score.py::test_sampled_history_is_canonical_and_fixed_at_the_stop | identical before/after a post-STOP completion; keys sorted | T13 | B |
| 316 | OQ-18, E5.3 | the OPENING-ACK must be created before the start_attest INTENT; the attestation before START | test_s1_a3_prestart.py::test_opening_ack_must_precede_the_attestation_and_the_attestation_start[ack-after-attest,attest-at-start] | REFUSE, no row | T10 | B |
| 317 | OQ-35 | intent.json/prepared.json lost or changed after CREATED | test_s1_a3_stage.py::test_intent_or_prepared_json_lost_after_created_is_invalid[intent-deleted,prepared-changed] | INVALID stage-replaced | T8 | B |
| 318 | OQ-30 | opening_receipt_sha256 is the raw file hash, distinct from the fingerprint | test_s1_a3_trial.py::test_opening_receipt_sha256_is_the_raw_file_hash | artifact_fields value == sha256_file; != receipt_sha256(fingerprint) | T4 | B |
| 319 | Codex reply P-4 | valid pagination and empty families are not anomalous | test_s1_a3_audit.py::test_valid_pagination_and_empty_families_are_not_anomalous | COMPLETE; no TRIAL-INVALID | T9 | ctrl |
| 320 | E1.7 (1) | live child past D; finalizer TIMEOUT; later QUALIFIED REFUSE or LOST-RACE; no seal, no INVALID; files not moved while it lives | rows 256–257 | as stated | T7 | B |
| 321 | E1.7 (2) | R < D and J after D with TIMEOUT committed first: TIMEOUT stands | test_s1_a3_finalizer.py::test_live_worker_after_timeout_is_refuse_or_lost_race_and_its_files_stay[early-r] | LOST-RACE; TIMEOUT stands | T7 | B |
| 322 | E1.7 (3) | two finalizers at D: exactly one TIMEOUT | test_s1_a3_codex_probes.py::test_race_two_finalizers_one_terminal (no work lock involved) | one TIMEOUT | T7 | B |
| 323 | E2.7 (1) | a pre-STOP QUALIFIED with an unpublished (determined) seal, then a stop operation: the stop operation publishes it before TRIAL-STOP; once TRIAL-STOP is committed no seal is ever written, including by a finalizer that read state before the STOP | test_s1_a3_stop.py::test_decide_stop_publishes_every_sampled_seal_before_trial_stop; row 260 | as stated | T7,T11 | B |
| 324 | E2.7 (2) | the STOP race in both orders: exactly one consistent outcome | rows 261–262 | one consistent outcome, no post-STOP seal | T7 | B |
| 325 | E2.7 (3) | a missing required seal after STOP: INVALID (registration-artifact) | row 263 | as stated | T7 | B |
| 326 | E3.6 (1) | BLOCKED: record, no row, ACTIVE, zero spies | row 271 | as stated | T10 | B |
| 327 | E3.6 (2) | blocked.json deleted and re-run: same refusal, identical recomputation | row 272 | as stated | T10 | B |
| 328 | E3.6 (3) | CLOSE BLOCKED with a wrong evidence hash refused | row 273 | as stated | T4,T10 | B |
| 329 | E3.6 (4) | a non-BLOCKED prereg unaffected | row 274 | as stated | T10 | ctrl |
| 330 | E4.4 | wrong-role CLOSE ignored, tested next to an arbitrary-draft message and a historical other-trial message | rows 238, 275–277 | ignored; the trial stays open | T4,T5 | B |
| 331 | E2.4 r1 | every PREPARED commitment carries `seals_checked` = {relpath: sha256} of every seal published at that moment; a committed PREPARED's `seals_checked` makes those seals published-committed (required) | test_s1_a3_stage.py::test_prepared_commitment_format[single,tree]; test_s1_a3_stage.py::test_seal_seen_only_by_a_prepared_commitment_is_required | commitment keys include `seals_checked` with the exact map; a seal listed only by a committed PREPARED is in `s1_slot.required_seals` (so Task 7's evidence check makes its deletion INVALID registration-artifact, never recreated) | T8 | B |
| 332 | E3.4 r1 (pending E3) | with an existing valid BLOCKED CLOSE, deleting blocked.json, or deleting and re-creating it with a different `recorded_utc`, never changes h and never re-opens the trial | test_s1_a3_prestart.py::test_blocked_close_survives_delete_and_recreate[deleted,deleted-and-recreated] | h unchanged; the trial stays closed; commands refuse with "zero open trials" | T10 | B |
| 333 | E5.6 r1, F7.2(b), OQ-37 | once the opening STAGE-INTENT exists, a later opening-close SLOT-INTENT is refused with no row by the opening gate and ends MISSED at its E; the OPENING-ACK cannot be issued before the E of the last scheduled opening-close slot | test_s1_a3_prestart.py::test_opening_window_later_slots_refused_then_missed | refusal, no slot row; MISSED after its E; issuance ineligible 1µs before the last slot's E, eligible after close-out | T10 | B |

Map rows: 333. Spec rules with no S1-testable counterpart are rows 153, 166 and 167 (`proc`) and row 176
(process evidence). Rows 284–290 are mutation-evidence rows (`proc`): a Cosmic Ray run is evidence, not a pass/fail
test.

---
## Task order and dependencies
1. **Journal primitive.** Line grammar, chain, readers, the one INSERT, and the bundle pin. Nothing depends on
   earlier tasks.
2. **Append precedence**, `decide`. Needs 1.
3. **Ownership locks.** Independent; needed by 6, 7, 8 and 11.
4. **Trial identity and ACK reading**, plus write_plan trial_id and tokens. Needs 1 and 2.
5. **The trial gate in every command**, the conftest migration, spies and the network guard. Needs 1–4.
6. **Slot worker**: SLOT-INTENT, QUALIFIED/FAILED, LOST-RACE, post-stop, PREREG-ACK. Needs 1–5.
7. **Slot finalizer and the F3 evidence table**, plus post-START seals. Needs 6.
8. **Stage engine**: INTENT/PREPARED/CREATED, staging, recovery, the stage-state table. Needs 1–5.
9. **Request policy plus the audit stage**, with the F4.9 audit rows. Needs 8.
10. **Pre-START stages**: opening seal, start_attest (OPENING-ACK), prereg (RUN-ACK, PREREG-ACK). Needs 6–9.
11. **STOP and the finalization prefix**: the F2 stop record, stop_attest, final_plan. Needs 7, 8 and 10.
12. **Final acquisition stage**: ACQUIRE-ACK and the F4.9 final rows. Needs 9 and 11.
13. **Score stage and CLOSE evidence**, plus connected lot-count and six-month runs. Needs 12.
14. **Matrix, residual, probe consolidation**, and removal of the transitional `ENFORCED` set. Needs 1–13.
15. **Mutation testing**: Cosmic Ray on the changed critical modules plus targeted semantic mutants (PLAN-6).
    Needs 1–14.

Start conditions (Blockers):
- No task starts before BLK-1 (Erratum 1 adopted).
- Task 11 Steps 4–7 wait on BLK-3.

---

### Task 1: Bundle pin and the journal primitive (F0.1–F0.4, A3.1)

**Files:**
- Create: `research/s1/s1_journal.py`
- Modify: `research/s1/s1_common.py:51-56` (BUNDLE_CODE, DOC_PINS)
- Modify: `research/s1/s1_tests/conftest.py`:
  - add `MAILBOX_SCHEMA` and `s1_mailbox_init`;
  - `s1_mailbox` uses `MAILBOX_SCHEMA`;
  - `s1_tmp_mailbox` creates the schema.
- Create: `research/s1/s1_tests/test_s1_a3_journal.py`
- Modify (old->new): `research/s1/s1_tests/test_s1_t12_a3_a8.py:28-29,90-102`. The BUNDLE tuple gains
  `s1_journal.py`. The docstring changes from "three document hashes" to "the pinned document hashes".

**Interfaces:**
- Consumes: `s1_common.sha256_bytes`, `canonical`, `aware`, `now_utc`, `MAILBOX`.
- Produces (`s1_journal`):
  - constants `SENDER = "s1"`, `RECIPIENT = "codex"`, `KEY = "experiments-s1-journal"`, `KINDS`, `SLOT_KINDS`,
    `STAGE_KINDS`, `TRIAL_KINDS`, `TERMINAL`, `OPENING`, `STAGES`, `REASONS`, `ABSENT`, `TRIAL_SUBJECT`;
  - exceptions `JournalError`, `ChainError(JournalError)`, `RequestError(JournalError)`, `Outage(JournalError)`;
  - `new_nonce() -> str` (32 hex); `fmt_at(t: datetime) -> str`; `slot_subject(slot: datetime) -> str`;
    `stage_subject(stage: str) -> str`; `invalid_subject(reason: str) -> str`;
  - `format_line(*, trial_id, seq, prev, kind, subject, detail, op, actor, at) -> str`;
    `parse_line(line: str) -> dict`; `line_sha256(line: str) -> str`; `genesis(audit_ack_line: str) -> str`;
    `detail_of(obj) -> str`;
  - dataclasses `Row` (fields trial_id, seq, prev, kind, subject, detail, op, actor, at, line, mailbox_id,
    created; properties `sha` and `instant`), `Request(kind, subject, op, actor, detail=None, detail_fn=None,
    r_at=None)`, `Context(closed=False, slot_times=None, stop_detail=None, stage_gate=None, slot_gate=None)`,
    `Decision(outcome, reason="")`, `Result(outcome, reason, row, rows)`;
  - `validate_request(req) -> None`; `read_all(mailbox=None) -> list[Row]`;
    `verify_chain(rows, trial_id, gen) -> list[Row]`; `read_trial(trial_id, gen, mailbox=None) -> list[Row]`;
  - `decide(rows, req, ctx, now) -> Decision`. Permissive in Task 1: it is Task 2's stub.
  - `append(trial_id, gen, req, ctx_fn, *, mailbox=None, clock=None, timeout=10.0) -> Result`, where
    `ctx_fn(rows, con) -> Context` runs inside the transaction;
  - `_connect_rw(mailbox, timeout)` and `_ro(mailbox)`: connection seams for the SQL-trace tests.
- Produces (conftest): `MAILBOX_SCHEMA: str` (verbatim mailbox.py SCHEMA); `s1_mailbox_init(root) -> Path`.
- Precondition (BLK-1): the adopted, byte-frozen Erratum 1 is at
  `research/s1/docs/s1_design_v5_addendum3_erratum1.md`, committed by the controller as its own docs commit, the way
  Addendum 3 was in 93f4c3e. Its sha256 is ERRATUM1_SHA256.

- [ ] **Step 0: Erratum precondition.**
  - Run `sha256sum research/s1/docs/s1_design_v5_addendum3_erratum1.md > research/s1/s1_evidence/a3/t1_erratum_pin.txt`.
  - If the file is absent, or the operator's adoption record names a different hash, STOP. Task 1 cannot be
    committed before adoption.
  - In the code and test below, replace the literal `ERRATUM1_SHA256` with the 64-hex value from
    `t1_erratum_pin.txt`. That is the only permitted fill-in; nothing else in this plan is a placeholder.

- [ ] **Step 1: Interface stub.** Create `research/s1/s1_journal.py` with the final names and permissive bodies. It
  creates the file on read, has no grammar, no chain check, a deferred transaction, `seq` from a read made before
  the transaction, and always APPEND.

```python
"""S1 external trial journal - Task 1 INTERFACE STUB (permissive; replaced in Step 4)."""
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import s1_common as c

SENDER, RECIPIENT, KEY = "s1", "codex", "experiments-s1-journal"
SLOT_KINDS = ("SLOT-INTENT", "SLOT-QUALIFIED", "SLOT-FAILED", "SLOT-TIMEOUT", "SLOT-MISSED")
STAGE_KINDS = ("STAGE-INTENT", "STAGE-PREPARED", "STAGE-CREATED")
TRIAL_KINDS = ("TRIAL-STOP", "TRIAL-INVALID")
KINDS = SLOT_KINDS + STAGE_KINDS + TRIAL_KINDS
TERMINAL = ("SLOT-QUALIFIED", "SLOT-FAILED", "SLOT-TIMEOUT", "SLOT-MISSED")
OPENING = ("SLOT-INTENT", "STAGE-INTENT", "SLOT-MISSED", "TRIAL-STOP")
STAGES = ("audit", "opening", "start_attest", "prereg", "stop_attest", "final_plan", "final", "score")
REASONS = ("contradictory-completion", "contradictory-finalizer", "contradictory-stage", "repeat-attempt",
           "repeat-stage", "stop-conflict", "stage-incomplete", "stage-replaced", "provider-structural",
           "score-aborted", "bundle", "LOST", "registration-artifact")
ABSENT, TRIAL_SUBJECT = "absent", "trial"


class JournalError(Exception):
    pass


class ChainError(JournalError):
    pass


class RequestError(JournalError):
    pass


class Outage(JournalError):
    pass


@dataclass(frozen=True)
class Row:
    trial_id: str
    seq: int
    prev: str
    kind: str
    subject: str
    detail: str
    op: str
    actor: str
    at: str
    line: str
    mailbox_id: str
    created: float

    @property
    def sha(self) -> str:
        return c.sha256_bytes(self.line.encode("utf-8"))

    @property
    def instant(self) -> datetime:
        return c.aware(self.at)


@dataclass
class Request:
    kind: str
    subject: str
    op: str
    actor: str
    detail: Optional[str] = None
    detail_fn: Optional[Callable] = None
    r_at: Optional[datetime] = None


@dataclass
class Context:
    closed: bool = False
    slot_times: Optional[Callable] = None
    stop_detail: Optional[Callable] = None
    stage_gate: Optional[Callable] = None
    slot_gate: Optional[Callable] = None


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str = ""


@dataclass
class Result:
    outcome: str
    reason: str
    row: Optional[Row]
    rows: list


def new_nonce() -> str:
    return uuid.uuid4().hex


def fmt_at(t: datetime) -> str:
    return t.isoformat()


def slot_subject(slot: datetime) -> str:
    return "slot/" + slot.strftime("%Y%m%dT%H%M%SZ")


def stage_subject(stage: str) -> str:
    return "stage/" + stage


def invalid_subject(reason: str) -> str:
    return "reason/" + reason


def format_line(*, trial_id, seq, prev, kind, subject, detail, op, actor, at) -> str:
    return (f"S1-JOURNAL trial_id={trial_id} seq={seq} prev_sha256={prev} kind={kind} subject={subject} "
            f"detail_sha256={detail} op={op} actor={actor} at={at}")


def parse_line(line: str) -> dict:
    f = dict(x.split("=", 1) for x in str(line).split() if "=" in x)
    return {"trial_id": f.get("trial_id"), "seq": int(f.get("seq") or 0), "prev": f.get("prev_sha256"),
            "kind": f.get("kind"), "subject": f.get("subject"), "detail": f.get("detail_sha256"), "op": f.get("op"),
            "actor": f.get("actor"), "at": f.get("at")}


def line_sha256(line: str) -> str:
    return c.sha256_bytes(line.encode("utf-8"))


def genesis(audit_ack_line: str) -> str:
    return "0" * 64


def detail_of(obj) -> str:
    return c.sha256_bytes(json.dumps(obj).encode("utf-8"))


def validate_request(req) -> None:
    return None


def _ro(mailbox):
    return sqlite3.connect(str(Path(c.MAILBOX if mailbox is None else mailbox)))


def _connect_rw(mailbox, timeout):
    return sqlite3.connect(str(Path(c.MAILBOX if mailbox is None else mailbox)), timeout=timeout)


def _rows_from(con) -> list:
    out = []
    for mid, body, created in con.execute("SELECT id, body, created FROM messages WHERE request_key=?", (KEY,)):
        out.append(Row(**parse_line(body), line=body, mailbox_id=mid, created=created))
    return out


def read_all(mailbox=None) -> list:
    con = _ro(mailbox)
    try:
        return _rows_from(con)
    finally:
        con.close()


def verify_chain(rows, trial_id, gen) -> list:
    return [r for r in rows if r.trial_id == trial_id]


def read_trial(trial_id, gen, mailbox=None) -> list:
    return verify_chain(read_all(mailbox), trial_id, gen)


def decide(rows, req, ctx, now) -> Decision:
    return Decision("APPEND")


def append(trial_id, gen, req, ctx_fn, *, mailbox=None, clock=None, timeout=10.0) -> Result:
    rows = read_trial(trial_id, gen, mailbox)
    now = (clock or c.now_utc)()
    con = _connect_rw(mailbox, timeout)
    try:
        ctx = ctx_fn(rows, con)
        line = format_line(trial_id=trial_id, seq=len(rows) + 1, prev=gen, kind=req.kind, subject=req.subject,
                           detail=req.detail or ABSENT, op=req.op, actor=req.actor, at=fmt_at(req.r_at or now))
        with con:
            con.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,NULL)",
                        (str(uuid.uuid4()), SENDER, RECIPIENT, KEY, line, now.timestamp()))
    finally:
        con.close()
    return Result("APPEND", "", Row(**parse_line(line), line=line, mailbox_id="", created=now.timestamp()), rows)
```

- [ ] **Step 2: Write the failing tests.** Create `research/s1/s1_tests/test_s1_a3_journal.py`. Add `MAILBOX_SCHEMA`
  and `s1_mailbox_init` to conftest (verbatim schema), and make `s1_tmp_mailbox` initialise the schema. Then update
  `s1_common` BUNDLE_CODE and DOC_PINS: that is the change under test.

`conftest.py` additions (insert after `SCHEMA`; and replace the `CREATE TABLE` in `s1_mailbox` with
`con.executescript(MAILBOX_SCHEMA)`):

```python
# Verbatim copy of mailbox.py SCHEMA (mailbox.py sha256 92b59ba92be9daddf593962460b904c95052d7d79f1f0914bd77239b00a3191b,
# never imported by tests or product code; Task 1 evidence a3/t1_schema_parity.txt records the comparison).
MAILBOX_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    sender TEXT NOT NULL,
    recipient TEXT NOT NULL,
    request_key TEXT,
    body TEXT NOT NULL,
    created REAL NOT NULL,
    acknowledged REAL
);
CREATE INDEX IF NOT EXISTS ix_inbox ON messages(recipient, acknowledged, created);
"""


def s1_mailbox_init(root) -> Path:
    """A3 test helper: <root>/mailbox.sqlite3 with the real mailbox schema (empty). Never the coordination mailbox."""
    p = Path(root) / "mailbox.sqlite3"
    con = sqlite3.connect(p)
    try:
        con.executescript(MAILBOX_SCHEMA)
    finally:
        con.close()
    return p
```

In `s1_tmp_mailbox`, after `s1_common.MAILBOX = tmp_path / "mailbox.sqlite3"`, add `s1_mailbox_init(tmp_path)`.
A3 commands read the mailbox mode=ro, and an absent file is an outage (OQ-20).

`test_s1_a3_journal.py`:

```python
"""Addendum 3 rev 5 (d9dd3759...) A3.1 and F0.1-F0.4: the bundle pin, the journal line grammar, the chain, the mode=ro
readers and the one INSERT. Written BEFORE the implementation (behavioural RED against the Task 1 stub:
s1_evidence/a3/t1_red.txt). Synthetic only: every mailbox is a tmp_path file; no real mailbox, network or live DB."""
import ast
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import s1_common as c
import s1_journal as j
from conftest import s1_mailbox_init

UTC = timezone.utc
HERE = Path(__file__).resolve().parent.parent
A3_SHA = "d9dd37595f0e0e73098ade1b8548e8cda2dc47fe49243f4d44735508029b9fb2"
ERRATUM1 = "ERRATUM1_SHA256"        # Step 0: the 64-hex sha256 of the adopted byte-frozen Erratum 1 copy
T0 = datetime(2026, 11, 2, 21, 45, 30, tzinfo=UTC)
FAR = datetime(2030, 1, 1, tzinfo=UTC)
TRIAL = "3f2b8c1e-5d4a-4b6c-9e7f-0a1b2c3d4e5f"
AUDIT_LINE = (f"S1-AUDIT-ACK trial_id={TRIAL} bundle_sha256={'a' * 64} collector_sha256={'b' * 64} "
              f"plan_sha256={'c' * 64} start=2026-11-16T14:30:00+00:00")
GEN = c.sha256_bytes(AUDIT_LINE.encode("utf-8"))
OP, ACTOR = "1" * 32, "2" * 32
SLOT, SLOT2 = "slot/20261102T214500Z", "slot/20261102T214700Z"


def OPEN(rows, con):
    """A context every Task-2 rule accepts for these requests (E and D far ahead, gates open)."""
    return j.Context(slot_times=lambda s: (FAR, FAR + timedelta(minutes=30)), stage_gate=lambda rows, g: None,
                     slot_gate=lambda rows, s: None)


def base_line(**kw):
    f = dict(trial_id=TRIAL, seq=1, prev=GEN, kind="SLOT-INTENT", subject=SLOT, detail="absent", op=OP, actor=ACTOR,
             at="2026-11-02T21:45:30.000000+00:00")
    f.update(kw)
    return j.format_line(**f)


def intent(subject=SLOT, op=OP, actor=ACTOR):
    return j.Request("SLOT-INTENT", subject, op, actor)


def stored(mb):
    con = sqlite3.connect(mb)
    try:
        return con.execute("SELECT sender, recipient, request_key, body, created, acknowledged FROM messages").fetchall()
    finally:
        con.close()


def put(mb, mid, body, sender="s1", recipient="codex", key="experiments-s1-journal", created=1.0):
    con = sqlite3.connect(mb)
    con.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,NULL)", (mid, sender, recipient, key, body, created))
    con.commit()
    con.close()


# ---------------------------------------------------------------- A3.1
def test_bundle_pins_addendum3_and_lists_every_new_module():
    assert c.DOC_PINS["docs/s1_design_v5_addendum3.md"] == A3_SHA
    assert c.sha256_file(HERE / "docs" / "s1_design_v5_addendum3.md") == A3_SHA
    assert c.DOC_PINS["docs/s1_design_v5_addendum3_erratum1.md"] == ERRATUM1
    assert c.sha256_file(HERE / "docs" / "s1_design_v5_addendum3_erratum1.md") == ERRATUM1   # the adopted copy
    assert "s1_journal.py" in c.BUNDLE_CODE
    m = c.bundle_manifest()
    assert m["unexpected"] == {} and c.bundle_problems(m) == []


# ---------------------------------------------------------------- F0.2 grammar
def test_line_format_round_trip_exact_bytes():
    ln = base_line()
    assert ln == (f"S1-JOURNAL trial_id={TRIAL} seq=1 prev_sha256={GEN} kind=SLOT-INTENT subject={SLOT} "
                  f"detail_sha256=absent op={OP} actor={ACTOR} at=2026-11-02T21:45:30.000000+00:00")
    f = j.parse_line(ln)
    assert f["seq"] == 1 and j.format_line(**f) == ln and "\n" not in ln


BAD = {
    "trailing-newline": lambda ln: ln + "\n",
    "double-space": lambda ln: ln.replace(" seq=", "  seq="),
    "field-order": lambda ln: ln.replace(f"op={OP} actor={ACTOR}", f"actor={ACTOR} op={OP}"),
    "uppercase-hex": lambda ln: ln.replace(GEN, GEN.upper()),
    "uuid-not-v4": lambda ln: ln.replace(TRIAL, TRIAL[:14] + "1" + TRIAL[15:]),
    "seq-zero": lambda ln: ln.replace(" seq=1 ", " seq=0 "),
    "seq-leading-zero": lambda ln: ln.replace(" seq=1 ", " seq=01 "),
    "at-no-microseconds": lambda ln: ln.replace(".000000+00:00", "+00:00"),
    "at-not-utc": lambda ln: ln.replace("+00:00", "-05:00"),
    "at-z-suffix": lambda ln: ln.replace("+00:00", "Z"),
    "at-impossible-date": lambda ln: ln.replace("2026-11-02T", "2026-13-02T"),
    "unknown-kind": lambda ln: ln.replace("kind=SLOT-INTENT", "kind=SLOT-RETRY"),
    "slot-subject-on-stage-kind": lambda ln: ln.replace("kind=SLOT-INTENT", "kind=STAGE-INTENT").replace(
        "detail_sha256=absent", "detail_sha256=" + "9" * 64),
    "unknown-stage": lambda ln: ln.replace("kind=SLOT-INTENT", "kind=STAGE-INTENT").replace(
        f"subject={SLOT}", "subject=stage/bogus").replace("detail_sha256=absent", "detail_sha256=" + "9" * 64),
    "detail-on-slot-intent": lambda ln: ln.replace("detail_sha256=absent", "detail_sha256=" + "9" * 64),
    "absent-on-qualified": lambda ln: ln.replace("kind=SLOT-INTENT", "kind=SLOT-QUALIFIED"),
    "short-op": lambda ln: ln.replace(f"op={OP}", f"op={OP[:-1]}"),
    "unknown-reason": lambda ln: ln.replace("kind=SLOT-INTENT", "kind=TRIAL-INVALID").replace(
        f"subject={SLOT}", "subject=reason/bogus").replace("detail_sha256=absent", "detail_sha256=" + "9" * 64),
    "extra-field": lambda ln: ln + " note=x",
}


@pytest.mark.parametrize("case", sorted(BAD))
def test_line_rejects_every_grammar_deviation(case):
    with pytest.raises(j.ChainError):
        j.parse_line(BAD[case](base_line()))


def test_genesis_is_the_sha256_of_the_audit_ack_line(tmp_path):
    mb = s1_mailbox_init(tmp_path)
    assert j.genesis(AUDIT_LINE) == GEN == j.line_sha256(AUDIT_LINE)
    first = j.append(TRIAL, GEN, intent(), OPEN, mailbox=mb, clock=lambda: T0)
    assert first.row.prev == GEN and first.row.sha == c.sha256_bytes(first.row.line.encode("utf-8"))


# ---------------------------------------------------------------- chain and readers
def chained(n, trial=TRIAL, gen=GEN):
    lines, prev = [], gen
    for i in range(1, n + 1):
        ln = base_line(trial_id=trial, seq=i, prev=prev, subject=f"slot/2026110{i}T214500Z", op=f"{i:032x}")
        lines.append(ln)
        prev = j.line_sha256(ln)
    return lines


def as_rows(lines):
    return [j.Row(**j.parse_line(ln), line=ln, mailbox_id=str(i), created=float(i)) for i, ln in enumerate(lines)]


def test_verify_chain_detects_gap_fork_duplicate_and_bad_prev():
    good = chained(3)
    assert [r.seq for r in j.verify_chain(as_rows(good), TRIAL, GEN)] == [1, 2, 3]
    with pytest.raises(j.ChainError, match="gap"):
        j.verify_chain(as_rows([good[0], good[2]]), TRIAL, GEN)
    fork = base_line(seq=2, prev=j.line_sha256(good[0]), subject="slot/20261109T214500Z", op="f" * 32)
    with pytest.raises(j.ChainError, match="duplicate seq"):
        j.verify_chain(as_rows(good + [fork]), TRIAL, GEN)
    bad_prev = base_line(seq=2, prev="0" * 64, subject="slot/20261108T214500Z", op="e" * 32)
    with pytest.raises(j.ChainError, match="prev"):
        j.verify_chain(as_rows([good[0], bad_prev]), TRIAL, GEN)
    with pytest.raises(j.ChainError, match="prev"):
        j.verify_chain(as_rows(good), TRIAL, "f" * 64)                  # seq 1 must chain to the genesis


def test_other_trials_rows_are_ignored_and_have_their_own_chain(tmp_path):
    other = "9a1b2c3d-4e5f-4a6b-8c7d-0e1f2a3b4c5d"
    mb = s1_mailbox_init(tmp_path)
    for i, ln in enumerate(chained(2) + chained(1, trial=other, gen="e" * 64)):
        put(mb, f"m{i}", ln, created=float(i))
    assert [r.seq for r in j.read_trial(TRIAL, GEN, mb)] == [1, 2]
    assert [r.seq for r in j.read_trial(other, "e" * 64, mb)] == [1]


@pytest.mark.parametrize("sender,recipient,body", [("codex", "codex", None), ("s1", "claude", None),
                                                    ("s1", "codex", "not a journal line")])
def test_foreign_or_unparseable_row_under_the_journal_key_is_a_chain_failure(tmp_path, sender, recipient, body):
    """OQ-4: only s1->codex well-formed lines may sit under the journal key."""
    mb = s1_mailbox_init(tmp_path)
    put(mb, "m0", body or chained(1)[0], sender=sender, recipient=recipient)
    with pytest.raises(j.ChainError):
        j.read_all(mb)


def test_acknowledged_column_never_changes_the_journal(tmp_path):
    """Review Focus 2: mailbox.py `ack` (run by Codex on its inbox) UPDATEs `acknowledged` on rows addressed to codex."""
    mb = s1_mailbox_init(tmp_path)
    j.append(TRIAL, GEN, intent(), OPEN, mailbox=mb, clock=lambda: T0)
    before = j.read_trial(TRIAL, GEN, mb)
    con = sqlite3.connect(mb)
    con.execute("UPDATE messages SET acknowledged=?", (T0.timestamp() + 5,))     # the test simulates Codex's ack
    con.commit()
    con.close()
    assert j.read_trial(TRIAL, GEN, mb) == before


def test_readers_are_mode_ro_and_never_create_the_mailbox(tmp_path):
    missing = tmp_path / "absent.sqlite3"
    with pytest.raises(j.Outage):
        j.read_all(missing)
    assert not missing.exists()
    mb = s1_mailbox_init(tmp_path)
    con = j._ro(mb)
    try:
        with pytest.raises(sqlite3.OperationalError):
            con.execute("INSERT INTO messages VALUES ('x','s1','codex','k','b',0,NULL)")
    finally:
        con.close()


# ---------------------------------------------------------------- F0.1 the one INSERT
def test_append_is_one_insert_inside_begin_immediate(tmp_path, monkeypatch):
    mb = s1_mailbox_init(tmp_path)
    seen = []
    real = j._connect_rw

    def traced(mailbox, timeout):
        con = real(mailbox, timeout)
        con.set_trace_callback(seen.append)
        return con
    monkeypatch.setattr(j, "_connect_rw", traced)
    res = j.append(TRIAL, GEN, intent(), OPEN, mailbox=mb, clock=lambda: T0)
    assert res.outcome == "APPEND" and seen[0] == "BEGIN IMMEDIATE" and seen[-1] == "COMMIT"
    verbs = [s.split(None, 1)[0].upper() for s in seen]
    assert [v for v in verbs if v in ("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER")] == ["INSERT"]
    assert verbs.index("SELECT") < verbs.index("INSERT")                 # re-read inside the transaction
    assert stored(mb) == [("s1", "codex", "experiments-s1-journal", res.row.line, T0.timestamp(), None)]


def test_concurrent_append_is_serialized_and_a_busy_mailbox_is_an_outage(tmp_path):
    """F0.1 + Review Focus 1 + F8.3: a second writer while the first holds BEGIN IMMEDIATE is an Outage (no row), never
    a fork; the chain stays contiguous."""
    mb = s1_mailbox_init(tmp_path)
    inner = {}

    def ctx_outer(rows, con):
        try:
            j.append(TRIAL, GEN, intent(SLOT2, op="3" * 32), OPEN, mailbox=mb, clock=lambda: T0, timeout=0.2)
            inner["outcome"] = "appended"
        except j.Outage as e:
            inner["outcome"] = f"outage: {e}"
        return OPEN(rows, con)
    first = j.append(TRIAL, GEN, intent(), ctx_outer, mailbox=mb, clock=lambda: T0)
    assert inner["outcome"].startswith("outage") and first.row.seq == 1
    second = j.append(TRIAL, GEN, intent(SLOT2, op="3" * 32), OPEN, mailbox=mb, clock=lambda: T0 + timedelta(seconds=1))
    rows = j.read_trial(TRIAL, GEN, mb)
    assert [r.seq for r in rows] == [1, 2] and rows[1].prev == rows[0].sha and second.row == rows[1]


def test_at_is_the_in_transaction_clock_and_qualified_uses_r(tmp_path, monkeypatch):
    mb = s1_mailbox_init(tmp_path)
    seen = []
    real = j._connect_rw

    def traced(mailbox, timeout):
        con = real(mailbox, timeout)
        con.set_trace_callback(lambda s: seen.append(s.split(None, 1)[0].upper()))
        return con
    monkeypatch.setattr(j, "_connect_rw", traced)
    reads = []

    def clock():
        seen.append("CLOCK")
        reads.append(T0 + timedelta(seconds=len(reads)))
        return reads[-1]
    a = j.append(TRIAL, GEN, intent(), OPEN, mailbox=mb, clock=clock)
    r_ = T0 + timedelta(minutes=1, microseconds=7)
    q = j.append(TRIAL, GEN, j.Request("SLOT-QUALIFIED", SLOT, OP, ACTOR, detail="9" * 64, r_at=r_), OPEN, mailbox=mb,
                 clock=clock)
    assert len(reads) == 2
    first = seen[:seen.index("COMMIT") + 1]
    assert first.index("BEGIN") < first.index("CLOCK") < first.index("INSERT")
    assert a.row.at == reads[0].isoformat(timespec="microseconds") and a.row.created == reads[0].timestamp()
    assert q.row.at == "2026-11-02T21:46:30.000007+00:00" and q.row.created == reads[1].timestamp()   # OQ-26


def test_detail_is_hashed_from_memory_not_reread_from_disk(tmp_path):
    obj = {"b": 1, "a": "x"}
    assert j.detail_of(obj) == c.sha256_bytes(c.canonical(obj)) == c.sha256_bytes(b'{"a":"x","b":1}')
    mb = s1_mailbox_init(tmp_path)
    got = []

    def fn(at):
        got.append(at)
        return j.detail_of({"cutoff": at.astimezone(c.NY).date().isoformat()})
    res = j.append(TRIAL, GEN, j.Request("STAGE-INTENT", "stage/audit", OP, ACTOR, detail_fn=fn), OPEN, mailbox=mb,
                   clock=lambda: T0)
    assert got == [T0] and res.row.detail == j.detail_of({"cutoff": "2026-11-02"})      # OQ-7


@pytest.mark.parametrize("state", ["no-file", "no-table"])
def test_missing_mailbox_or_table_is_an_outage_with_no_row(tmp_path, state):
    mb = tmp_path / "mb.sqlite3"
    if state == "no-table":
        sqlite3.connect(mb).close()
    with pytest.raises(j.Outage):
        j.append(TRIAL, GEN, intent(), OPEN, mailbox=mb, clock=lambda: T0)
    assert (state == "no-file") == (not mb.exists())


def test_journal_module_never_updates_deletes_or_imports_mailbox():
    tree = ast.parse((HERE / "s1_journal.py").read_text(encoding="utf-8"))
    sql = [n.value.strip().split(None, 1)[0].upper() for n in ast.walk(tree)
           if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.strip()
           and n.value.strip().split(None, 1)[0].upper() in ("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP",
                                                             "ALTER")]
    assert sql == ["INSERT"]
    imports = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imports |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert "mailbox" not in imports


def test_default_mailbox_is_the_tmp_redirect(s1_tmp_mailbox):
    real = Path("C:/Users/gl450/.coordination/trading_app/mailbox.sqlite3")
    assert Path(c.MAILBOX) == s1_tmp_mailbox and Path(c.MAILBOX).resolve() != real.resolve()
    assert s1_tmp_mailbox.is_file()                                       # the redirect carries the real schema
```

Then change `s1_common.py:51-56` (the change under test):

```python
BUNDLE_CODE = ("e1_fetch.py", "e1_sim.py", "s1_books.py", "s1_checkpoint.py", "s1_collect.py", "s1_common.py",
               "s1_gates.py", "s1_journal.py", "s1_receipt.py", "s1_run.py", "s1_seal.py", "s1_snapshot.py")
DOC_PINS = {"docs/s1_design_v5.md": "33c3284072dc51392476f7cae596eab05f1fcbaccd622abbe05c6e6a198cbb9b",
            "docs/s1_spec.md": "4b882f52a448dbf2d30583828c5085a636009f6c8db7b18307bc6e9991529c98",
            "docs/s1_design_v5_addendum1.md": "6cb89e36840975b8d949ec85debf9d2cedbe45bbeb9dcb374d91343dddc5e590",
            "docs/s1_design_v5_addendum2.md": "c7f0c3ffcd886b0f308c5f09bc0bfaca9977f8edae596bf51b30e28cb9ae3266",
            "docs/s1_design_v5_addendum3.md": "d9dd37595f0e0e73098ade1b8548e8cda2dc47fe49243f4d44735508029b9fb2",
            "docs/s1_design_v5_addendum3_erratum1.md": "ERRATUM1_SHA256"}    # Step 0 fill-in (adopted copy)
```

The old->new edit to `test_s1_t12_a3_a8.py:28-29`:
`BUNDLE = (..., "s1_gates.py", "s1_journal.py", "s1_receipt.py", ...)`. The assertion values are unchanged.

- [ ] **Step 3: Run the tests and record a behavioural RED.**

Run: `PYTHONPATH="research/s1;research/s1/s1_tests" C:/Users/gl450/.coordination/trading_app/testenv/Scripts/python.exe -m pytest -p conftest -p no:cacheprovider research/s1/s1_tests/test_s1_a3_journal.py -q > research/s1/s1_evidence/a3/t1_red.txt 2>&1`

Expected: FAIL on assertions. Typical failures:
- every grammar deviation is accepted, so `ChainError` is not raised;
- `genesis != sha256`;
- the inner append succeeds (`inner["outcome"] == "appended"`);
- the missing file gets created;
- the trace shows no `BEGIN IMMEDIATE`;
- `at` lacks microseconds.

`test_bundle_pins…`, `test_journal_module_never_updates…`, `test_default_mailbox…` and the chain tests on
sequential appends may pass. Label them `static` or `ctrl` in `a3/t1_red_labels.txt`. No ImportError may remain.

- [ ] **Step 4: Implement `research/s1/s1_journal.py`.** Replace the stub entirely.

```python
"""S1 external trial journal (Addendum 3 rev 5, sha256 d9dd3759..., F0).

The ONE writer of the coordination mailbox. Its only write is a single-row INSERT inside BEGIN IMMEDIATE (sender s1,
recipient codex, key experiments-s1-journal); inside that transaction it re-reads the trial's rows and applies the
F0.5 precedence (decide) to the state it reads there, never to an earlier read. Every other read is mode=ro (never
created). No UPDATE, DELETE or ack; mailbox.py is never imported. A row is judged by its body only: the mailbox's
`acknowledged` column (Codex's inbox ack) is ignored."""
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import s1_common as c

SENDER, RECIPIENT, KEY = "s1", "codex", "experiments-s1-journal"
SLOT_KINDS = ("SLOT-INTENT", "SLOT-QUALIFIED", "SLOT-FAILED", "SLOT-TIMEOUT", "SLOT-MISSED")
STAGE_KINDS = ("STAGE-INTENT", "STAGE-PREPARED", "STAGE-CREATED")
TRIAL_KINDS = ("TRIAL-STOP", "TRIAL-INVALID")
KINDS = SLOT_KINDS + STAGE_KINDS + TRIAL_KINDS                                        # F0.3
TERMINAL = ("SLOT-QUALIFIED", "SLOT-FAILED", "SLOT-TIMEOUT", "SLOT-MISSED")
OPENING = ("SLOT-INTENT", "STAGE-INTENT", "SLOT-MISSED", "TRIAL-STOP")                # rows that open their own op
STAGES = ("audit", "opening", "start_attest", "prereg", "stop_attest", "final_plan", "final", "score")   # F4.8
REASONS = ("contradictory-completion", "contradictory-finalizer", "contradictory-stage", "repeat-attempt",
           "repeat-stage", "stop-conflict", "stage-incomplete", "stage-replaced", "provider-structural",
           "score-aborted", "bundle", "LOST", "registration-artifact")                                 # OQ-1
ABSENT, TRIAL_SUBJECT = "absent", "trial"
DETAIL_ABSENT = ("SLOT-INTENT", "SLOT-TIMEOUT", "SLOT-MISSED")                                         # OQ-2
_HEX64, _HEX32 = re.compile(r"[0-9a-f]{64}"), re.compile(r"[0-9a-f]{32}")
_UUID4 = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
_LINE = re.compile(
    rf"S1-JOURNAL trial_id=(?P<trial_id>{_UUID4}) seq=(?P<seq>[1-9][0-9]*) prev_sha256=(?P<prev>[0-9a-f]{{64}}) "
    r"kind=(?P<kind>[A-Z-]+) subject=(?P<subject>[^ =\r\n]+) detail_sha256=(?P<detail>[0-9a-f]{64}|absent) "
    r"op=(?P<op>[0-9a-f]{32}) actor=(?P<actor>[0-9a-f]{32}) "
    r"at=(?P<at>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00)")
_SLOT = re.compile(r"slot/\d{8}T\d{6}Z")


class JournalError(Exception):
    """Base of every journal failure; the caller refuses with no row."""


class ChainError(JournalError):
    """F0.5 step 1: a gap, fork, duplicate seq or bad format (or a foreign row under the key, OQ-4): refuse with no
    row and escalate."""


class RequestError(JournalError):
    """A malformed requested row (kind, subject, detail, op, actor, R): refused before any transaction, no row."""


class Outage(JournalError):
    """The mailbox could not be read or written (missing, locked, no table): fail closed, no row (F8.3)."""


@dataclass(frozen=True)
class Row:
    trial_id: str
    seq: int
    prev: str
    kind: str
    subject: str
    detail: str
    op: str
    actor: str
    at: str
    line: str
    mailbox_id: str
    created: float

    @property
    def sha(self) -> str:
        return line_sha256(self.line)

    @property
    def instant(self) -> datetime:
        return c.aware(self.at)


@dataclass
class Request:
    """A requested row. `detail_fn(at)` (STAGE-INTENT, OQ-7) computes the detail from the in-transaction clock; `r_at`
    is R for SLOT-QUALIFIED (its `at`, F3)."""
    kind: str
    subject: str
    op: str
    actor: str
    detail: Optional[str] = None
    detail_fn: Optional[Callable[[datetime], str]] = None
    r_at: Optional[datetime] = None


@dataclass
class Context:
    """What the caller supplies, evaluated inside the transaction: CLOSED (F7.5); slot_times(subject) -> (E, D);
    stop_detail(rows) -> the stop record sha256 committed history gives, or None (rule not met); stage_gate(rows,
    stage) / slot_gate(rows, subject) -> a refusal reason or None (F1 permission, predecessor, ACKs)."""
    closed: bool = False
    slot_times: Optional[Callable[[str], tuple]] = None
    stop_detail: Optional[Callable[[list], Optional[str]]] = None
    stage_gate: Optional[Callable[[list, str], Optional[str]]] = None
    slot_gate: Optional[Callable[[list, str], Optional[str]]] = None


@dataclass(frozen=True)
class Decision:
    outcome: str                      # "APPEND" | "LOST-RACE" | "INVALIDATE" | "REFUSE" (OQ-21)
    reason: str = ""


@dataclass
class Result:
    outcome: str
    reason: str
    row: Optional[Row]                # the row written (the requested one, or the TRIAL-INVALID), else None
    rows: list                        # the trial's rows as read inside the transaction (before this row)


def new_nonce() -> str:
    return uuid.uuid4().hex


def fmt_at(t: datetime) -> str:
    if not isinstance(t, datetime) or t.tzinfo is None:
        raise RequestError("an aware instant is required for `at`")
    return t.astimezone(timezone.utc).isoformat(timespec="microseconds")


def slot_subject(slot: datetime) -> str:
    return "slot/" + slot.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def stage_subject(stage: str) -> str:
    if stage not in STAGES:
        raise RequestError(f"unknown stage {stage!r}")
    return "stage/" + stage


def invalid_subject(reason: str) -> str:
    if reason not in REASONS:
        raise RequestError(f"unknown INVALID reason {reason!r}")
    return "reason/" + reason


def subject_ok(kind: str, subject: str) -> bool:
    if kind in SLOT_KINDS:
        return bool(_SLOT.fullmatch(subject or ""))
    if kind in STAGE_KINDS:
        return isinstance(subject, str) and subject.startswith("stage/") and subject[len("stage/"):] in STAGES
    if kind == "TRIAL-STOP":
        return subject == TRIAL_SUBJECT
    if kind == "TRIAL-INVALID":
        return isinstance(subject, str) and subject.startswith("reason/") and subject[len("reason/"):] in REASONS
    return False


def detail_ok(kind: str, detail: str) -> bool:
    return detail == ABSENT if kind in DETAIL_ABSENT else bool(_HEX64.fullmatch(detail or ""))


def format_line(*, trial_id, seq, prev, kind, subject, detail, op, actor, at) -> str:
    """F0.2: the frozen one-line body (fields in order, single-spaced, no trailing newline)."""
    return (f"S1-JOURNAL trial_id={trial_id} seq={seq} prev_sha256={prev} kind={kind} subject={subject} "
            f"detail_sha256={detail} op={op} actor={actor} at={at}")


def parse_line(line: str) -> dict:
    """The fields of a journal line, or ChainError for any deviation from the frozen grammar (F0.2, F0.3, OQ-1/2)."""
    m = _LINE.fullmatch(line) if isinstance(line, str) else None
    if m is None:
        raise ChainError("journal line does not match the frozen F0.2 grammar")
    f = m.groupdict()
    if f["kind"] not in KINDS:
        raise ChainError(f"unknown journal kind {f['kind']!r} (F0.3)")
    if not subject_ok(f["kind"], f["subject"]):
        raise ChainError(f"subject {f['subject']!r} is not valid for {f['kind']} (OQ-1)")
    if not detail_ok(f["kind"], f["detail"]):
        raise ChainError(f"detail presence is not valid for {f['kind']} (OQ-2)")
    try:
        datetime.fromisoformat(f["at"])
    except ValueError:
        raise ChainError("journal `at` is not a real instant") from None
    f["seq"] = int(f["seq"])
    return f


def line_sha256(line: str) -> str:
    return c.sha256_bytes(line.encode("utf-8"))


def genesis(audit_ack_line: str) -> str:
    """F0.2: seq 1's prev_sha256 = sha256 of the AUDIT-ACK token line (UTF-8, no newline)."""
    return line_sha256(audit_ack_line)


def detail_of(obj) -> str:
    """F0.4: sha256 of the canonical bytes held in memory (c.canonical: sorted keys, compact, UTF-8)."""
    return c.sha256_bytes(c.canonical(obj))


def validate_request(req: Request) -> None:
    """C-c: a malformed request is refused before any transaction (no row)."""
    if req.kind not in KINDS:
        raise RequestError(f"unknown kind {req.kind!r}")
    if not subject_ok(req.kind, req.subject):
        raise RequestError(f"subject {req.subject!r} is not valid for {req.kind}")
    if not (_HEX32.fullmatch(req.op or "") and _HEX32.fullmatch(req.actor or "")):
        raise RequestError("op and actor must be 32 lowercase hex")
    if req.detail is not None and req.detail_fn is not None:
        raise RequestError("detail and detail_fn are exclusive")
    if req.kind in DETAIL_ABSENT:
        if req.detail not in (None, ABSENT) or req.detail_fn is not None:
            raise RequestError(f"{req.kind} carries no detail (OQ-2)")
    elif req.detail_fn is None and not _HEX64.fullmatch(req.detail or ""):
        raise RequestError(f"{req.kind} requires a 64-hex detail")
    if req.kind == "SLOT-QUALIFIED":
        if not isinstance(req.r_at, datetime) or req.r_at.tzinfo is None:
            raise RequestError("SLOT-QUALIFIED requires an aware R (its `at`, F3)")
    elif req.r_at is not None:
        raise RequestError("only SLOT-QUALIFIED carries R")


def _path(mailbox) -> Path:
    return Path(c.MAILBOX if mailbox is None else mailbox)


def _ro(mailbox):
    """F0.1: every read other than the in-transaction re-read is mode=ro (the file is never created)."""
    return sqlite3.connect(f"file:{_path(mailbox).as_posix()}?mode=ro", uri=True)


def _connect_rw(mailbox, timeout):
    """mode=rw: an existing mailbox only (never created); autocommit so BEGIN IMMEDIATE is explicit."""
    return sqlite3.connect(f"file:{_path(mailbox).as_posix()}?mode=rw", uri=True, isolation_level=None,
                           timeout=timeout)


def _rows_from(con) -> list:
    out = []
    for mid, sender, recipient, body, created in con.execute(
            "SELECT id, sender, recipient, body, created FROM messages WHERE request_key=?", (KEY,)):
        if (sender, recipient) != (SENDER, RECIPIENT):
            raise ChainError(f"journal-key row {mid!r} from {sender!r} to {recipient!r}: only s1->codex writes it")
        out.append(Row(**parse_line(body), line=body, mailbox_id=mid, created=created))
    return out


def read_all(mailbox=None) -> list:
    """Every journal row of every trial (mode=ro). Outage when unreadable; ChainError for a bad row (OQ-4)."""
    try:
        con = _ro(mailbox)
        try:
            return _rows_from(con)
        finally:
            con.close()
    except sqlite3.Error as e:
        raise Outage(f"mailbox unreadable ({type(e).__name__})") from None


def verify_chain(rows, trial_id: str, gen: str) -> list:
    """F0.5 step 1 for one trial (other trials' rows are ignored, F6.5): seq 1..n contiguous and unique, each prev the
    previous row's line_sha256 and seq 1's the genesis. Returns the trial's rows in seq order."""
    mine = sorted((r for r in rows if r.trial_id == trial_id), key=lambda r: r.seq)
    seqs = [r.seq for r in mine]
    if len(set(seqs)) != len(seqs):
        raise ChainError("duplicate seq (a fork): refuse with no row and escalate")
    if seqs != list(range(1, len(mine) + 1)):
        raise ChainError(f"seq gap in {seqs[:8]}: refuse with no row and escalate")
    prev = gen
    for r in mine:
        if r.prev != prev:
            raise ChainError(f"seq {r.seq}: prev_sha256 does not chain (fork): refuse with no row and escalate")
        prev = r.sha
    return mine


def read_trial(trial_id: str, gen: str, mailbox=None) -> list:
    return verify_chain(read_all(mailbox), trial_id, gen)


def decide(rows, req, ctx, now) -> Decision:
    """Task 1: permissive (always APPEND). This is Task 2's behavioural-RED interface stub; Task 2 replaces it with the
    F0.5 precedence."""
    return Decision("APPEND")


def _requested_detail(req: Request, now: datetime) -> str:
    d = req.detail_fn(now) if req.detail_fn is not None else (req.detail or ABSENT)
    if not detail_ok(req.kind, d):
        raise RequestError(f"{req.kind}: computed detail {d!r} is not valid")
    return d


def _insert(con, trial_id: str, gen: str, rows: list, req: Request, dec: Decision, now: datetime) -> Row:
    seq, prev = len(rows) + 1, (rows[-1].sha if rows else gen)
    requested = _requested_detail(req, now)
    if dec.outcome == "INVALIDATE":                                   # OQ-2: the reason record, the request's op
        kind, subject, at = "TRIAL-INVALID", invalid_subject(dec.reason), now
        detail = detail_of({"reason": dec.reason, "requested": {"kind": req.kind, "subject": req.subject,
                                                                "op": req.op, "actor": req.actor,
                                                                "detail": requested}})
    else:
        kind, subject, detail = req.kind, req.subject, requested
        at = req.r_at if req.kind == "SLOT-QUALIFIED" else now        # F0.2: QUALIFIED at = R
    line = format_line(trial_id=trial_id, seq=seq, prev=prev, kind=kind, subject=subject, detail=detail, op=req.op,
                       actor=req.actor, at=fmt_at(at))
    fields = parse_line(line)                                          # never write a line the grammar rejects
    mid, created = str(uuid.uuid4()), now.timestamp()                  # OQ-26
    con.execute("INSERT INTO messages (id, sender, recipient, request_key, body, created, acknowledged) "
                "VALUES (?, ?, ?, ?, ?, ?, NULL)", (mid, SENDER, RECIPIENT, KEY, line, created))
    return Row(**fields, line=line, mailbox_id=mid, created=created)


def append(trial_id: str, gen: str, req: Request, ctx_fn, *, mailbox=None, clock=None, timeout: float = 10.0) -> Result:
    """F0.1/F0.5: validate, BEGIN IMMEDIATE, re-read and chain-verify the trial's rows, build the Context from that
    state (`ctx_fn(rows, con)`), read the clock once (the row's `at`, OQ-7/26), decide, and INSERT at most one row
    (the requested row on APPEND, the TRIAL-INVALID on INVALIDATE). Any exception rolls back: no row (F0.7)."""
    validate_request(req)
    clock = clock or c.now_utc
    try:
        con = _connect_rw(mailbox, timeout)
    except sqlite3.Error as e:
        raise Outage(f"mailbox not writable ({type(e).__name__}): no row") from None
    try:
        try:
            con.execute("BEGIN IMMEDIATE")
        except sqlite3.Error as e:
            raise Outage(f"journal transaction not started ({type(e).__name__}): no row") from None
        try:
            rows = verify_chain(_rows_from(con), trial_id, gen)
            ctx = ctx_fn(rows, con)
            now = clock()
            dec = decide(rows, req, ctx, now)
            row = _insert(con, trial_id, gen, rows, req, dec, now) if dec.outcome in ("APPEND", "INVALIDATE") else None
            con.execute("COMMIT")
        except BaseException:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
    except sqlite3.Error as e:
        raise Outage(f"journal write failed ({type(e).__name__}): no row") from None
    finally:
        con.close()
    return Result(dec.outcome, dec.reason, row, rows)
```

- [ ] **Step 5: Run the task tests GREEN.**

Run: `PYTHONPATH="research/s1;research/s1/s1_tests" C:/Users/gl450/.coordination/trading_app/testenv/Scripts/python.exe -m pytest -p conftest -p no:cacheprovider research/s1/s1_tests/test_s1_a3_journal.py -q > research/s1/s1_evidence/a3/t1_green.txt 2>&1`
Expected: all PASS.

- [ ] **Step 6: Schema parity evidence (read-only).**

Run: `C:/Users/gl450/.coordination/trading_app/testenv/Scripts/python.exe -I -c "import pathlib,re,sys; sys.path.insert(0,'research/s1/s1_tests'); src=pathlib.Path('C:/Users/gl450/.coordination/trading_app/mailbox.py').read_text(encoding='utf-8'); m=re.search(r'SCHEMA = \"\"\"(.*?)\"\"\"', src, re.S).group(1); t=pathlib.Path('research/s1/s1_tests/conftest.py').read_text(encoding='utf-8'); n=re.search(r'MAILBOX_SCHEMA = \"\"\"(.*?)\"\"\"', t, re.S).group(1); print('parity', m==n)" > research/s1/s1_evidence/a3/t1_schema_parity.txt`
Then append `sha256sum C:/Users/gl450/.coordination/trading_app/mailbox.py` to the same file.
Expected: `parity True` and mailbox.py sha256 `92b59ba9…`. This only reads mailbox.py as text; it never imports it.

- [ ] **Step 7: Full suite, old->new, hashes.**

Run the whole suite into `a3/t1_full.txt`. The expected intended change is
`test_s1_t12_a3_a8.py::test_a3_bundle_is_the_explicit_file_list_plus_the_three_document_hashes`: the BUNDLE tuple
gains `s1_journal.py`, and DOC_PINS gains the Addendum 3 and Erratum 1 pins. Record the old->new line in `a3/t1_old_new.md`. Tests that insert a duplicate message `id`
into a tmp mailbox now fail on the PRIMARY KEY; that is a fixture incompatibility, fixed by giving them distinct ids.
Then write `a3/t1_hashes.txt` (sha256 of every changed and evidence file).

- [ ] **Step 8: Controller review and commit (only after BLK-1: Erratum 1 adopted and its byte-frozen copy
  committed).**
  - The controller confirms that `a3/t1_erratum_pin.txt` equals the adoption record's hash, reviews, asserts
    `git rev-parse HEAD` before, then runs
    `git add research/s1/s1_journal.py research/s1/s1_common.py research/s1/s1_tests/conftest.py research/s1/s1_tests/test_s1_a3_journal.py research/s1/s1_tests/test_s1_t12_a3_a8.py research/s1/s1_evidence/a3/t1_*`.
  - Commit with the message `S1 A3 Task 1: journal primitive and Addendum 3 bundle pin`, a body that lists the map
    rows covered (1–6, 8–11, 17) and the evidence files, and the line
    `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
  - Push, then assert that HEAD advanced by exactly one commit.

---

### Task 2: Append precedence (F0.5 steps 1–7, the step-4 sub-order, F1 state, OQ-3, OQ-9, OQ-12, OQ-21)

**Files:**
- Modify: `research/s1/s1_journal.py`. Replace `decide`; add `trial_state`, `subject_rows`, `first` and `_slot`,
  `_stage`, `_stop`.
- Create: `research/s1/s1_tests/test_s1_a3_precedence.py`

**Interfaces:**
- Consumes: Task 1 `Row`, `Request`, `Context`, `Decision`, `append`, `format_line`, `parse_line`.
- Produces:
  - `trial_state(rows) -> "ACTIVE" | "STOPPED" | "INVALID"`;
  - `subject_rows(rows, subject) -> list[Row]`;
  - `first(rows, *kinds) -> Row | None`;
  - `decide(rows, req, ctx, now) -> Decision`, the full precedence. `outcome` is one of APPEND, LOST-RACE,
    INVALIDATE, REFUSE; `reason` is an INVALID reason code on INVALIDATE, else text.

- [ ] **Step 1: Interface stub.** The stub is Task 1's permissive `decide`, which always returns APPEND, plus these
  helpers with permissive bodies:

```python
def trial_state(rows) -> str:
    return "ACTIVE"


def subject_rows(rows, subject) -> list:
    return [r for r in rows if r.subject == subject]


def first(rows, *kinds):
    return next((r for r in rows if r.kind in kinds), None)
```

- [ ] **Step 2: Write the failing tests.** Create `research/s1/s1_tests/test_s1_a3_precedence.py`:

```python
"""Addendum 3 rev 5 F0.5 (precedence steps 1-7 and the rev-5 step-4 sub-order 4a-4d), F0.7, F1 state derivation and
OQ-3/OQ-9/OQ-12/OQ-21. Behavioural RED against the permissive Task 1 decide (s1_evidence/a3/t2_red.txt). Synthetic
journal rows only (the F10 'synthetic journal fixtures'); tmp mailboxes; no network, live DB or scheduler."""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import given, seed, settings, strategies as st
from hypothesis.database import DirectoryBasedExampleDatabase
import s1_common as c
import s1_journal as j
from conftest import s1_mailbox_init

from pathlib import Path

HERE = Path(c.__file__).resolve().parent
UTC = timezone.utc
TRIAL = "3f2b8c1e-5d4a-4b6c-9e7f-0a1b2c3d4e5f"
GEN = "7" * 64
T0 = datetime(2026, 11, 2, 21, 0, tzinfo=UTC)
S, S2, G = "slot/20261102T214500Z", "slot/20261102T214700Z", "stage/audit"
E = datetime(2026, 11, 2, 21, 55, tzinfo=UTC)
D = E + timedelta(minutes=30)
US = timedelta(microseconds=1)
H1, H2 = "1" * 64, "2" * 64
AO, AA = "a" * 32, "b" * 32          # worker A: op, actor
BO, BA = "c" * 32, "d" * 32          # foreign op, foreign actor
FA = "e" * 32                        # a finalizer / recovery actor
N1, N2 = "f" * 32, "9" * 32          # fresh ops of rows that open their own op


def row(kind, subject=S, op=AO, actor=AA, detail="absent"):
    return (kind, subject, op, actor, detail)


SI, QU, FL = row("SLOT-INTENT"), row("SLOT-QUALIFIED", detail=H1), row("SLOT-FAILED", detail=H1)
TO, MI = row("SLOT-TIMEOUT", actor=FA), row("SLOT-MISSED", op=N2, actor=FA)
GI, GP, GC = row("STAGE-INTENT", G, detail=H1), row("STAGE-PREPARED", G, detail=H1), row("STAGE-CREATED", G, detail=H1)
ST = row("TRIAL-STOP", "trial", op=N2, actor=FA, detail=H1)
IV = row("TRIAL-INVALID", "reason/bundle", op=N2, actor=FA, detail=H1)


def build(specs):
    rows, prev = [], GEN
    for i, (kind, subject, op, actor, detail) in enumerate(specs, start=1):
        ln = j.format_line(trial_id=TRIAL, seq=i, prev=prev, kind=kind, subject=subject, detail=detail, op=op,
                           actor=actor, at=j.fmt_at(T0 + timedelta(seconds=i)))
        r = j.Row(**j.parse_line(ln), line=ln, mailbox_id=str(i), created=float(i))
        rows.append(r)
        prev = r.sha
    return rows


def rq(kind, subject=S, op=AO, actor=AA, detail=None, r_at=None):
    return j.Request(kind, subject, op, actor, detail=detail, r_at=r_at)


def ctx(**kw):
    base = dict(slot_times=lambda s: (E, D), stop_detail=lambda rows: H1, stage_gate=lambda rows, g: None,
                slot_gate=lambda rows, s: None)
    base.update(kw)
    return j.Context(**base)


def Q(op=AO, actor=AA, r_at=E - US):
    return rq("SLOT-QUALIFIED", op=op, actor=actor, detail=H1, r_at=r_at)

CASES = [
    # id, existing rows, request, now, context overrides, outcome, INVALID reason
    ("4a-q-no-intent", [], Q(), E, {}, "INVALIDATE", "contradictory-completion"),
    ("4a-q-foreign-op", [SI], Q(op=BO), E, {}, "INVALIDATE", "contradictory-completion"),
    ("4a-q-foreign-actor", [SI], Q(actor=BA), E, {}, "INVALIDATE", "contradictory-completion"),
    ("4a-q-foreign-op-on-terminal", [SI, TO], Q(op=BO), D, {}, "INVALIDATE", "contradictory-completion"),
    ("4a-f-no-intent", [], rq("SLOT-FAILED", detail=H1), E, {}, "INVALIDATE", "contradictory-completion"),
    ("4a-f-foreign-op", [SI], rq("SLOT-FAILED", op=BO, detail=H1), E, {}, "INVALIDATE", "contradictory-completion"),
    ("4a-f-foreign-actor", [SI], rq("SLOT-FAILED", actor=BA, detail=H1), E, {}, "INVALIDATE",
     "contradictory-completion"),
    ("4a-t-no-intent", [], rq("SLOT-TIMEOUT", actor=FA), D, {}, "INVALIDATE", "contradictory-finalizer"),
    ("4a-t-foreign-op", [SI], rq("SLOT-TIMEOUT", op=BO, actor=FA), D, {}, "INVALIDATE", "contradictory-finalizer"),
    ("4a-t-foreign-op-on-terminal", [SI, QU], rq("SLOT-TIMEOUT", op=BO, actor=FA), D, {}, "INVALIDATE",
     "contradictory-finalizer"),
    ("4a-p-no-intent", [], rq("STAGE-PREPARED", G, detail=H1), E, {}, "INVALIDATE", "contradictory-stage"),
    ("4a-p-foreign-op", [GI], rq("STAGE-PREPARED", G, op=BO, detail=H1), E, {}, "INVALIDATE", "contradictory-stage"),
    ("4a-p-foreign-actor", [GI], rq("STAGE-PREPARED", G, actor=FA, detail=H1), E, {}, "INVALIDATE",
     "contradictory-stage"),
    ("4a-c-no-prepared", [GI], rq("STAGE-CREATED", G, detail=H1), E, {}, "INVALIDATE", "contradictory-stage"),
    ("4a-c-foreign-op", [GI, GP], rq("STAGE-CREATED", G, op=BO, actor=FA, detail=H1), E, {}, "INVALIDATE",
     "contradictory-stage"),
    ("4b-si-after-intent", [SI], rq("SLOT-INTENT", op=N1, actor=BA), E - US, {}, "INVALIDATE", "repeat-attempt"),
    ("4b-si-after-terminal", [SI, QU], rq("SLOT-INTENT", op=N1, actor=BA), E - US, {}, "INVALIDATE",
     "repeat-attempt"),
    ("4b-si-stopped-terminal", [SI, QU, ST], rq("SLOT-INTENT", op=N1, actor=BA), E - US, {}, "INVALIDATE",
     "repeat-attempt"),
    ("4b-gi-repeat", [GI], rq("STAGE-INTENT", G, op=N1, actor=BA, detail=H2), E, {}, "INVALIDATE", "repeat-stage"),
    # row 299 (OQ-3 ruling): a reused op never hides a repeated opening subject
    ("4b-si-repeat-with-reused-op", [SI], rq("SLOT-INTENT", op=AO, actor=BA), E - US, {}, "INVALIDATE",
     "repeat-attempt"),
    ("4b-gi-repeat-with-reused-op", [GI], rq("STAGE-INTENT", G, op=AO, actor=BA, detail=H2), E, {}, "INVALIDATE",
     "repeat-stage"),
    ("4c-q-after-timeout", [SI, TO], Q(), D, {}, "LOST-RACE", None),
    ("4c-f-after-qualified", [SI, QU], rq("SLOT-FAILED", detail=H2), E, {}, "LOST-RACE", None),
    ("4c-t-after-qualified", [SI, QU], rq("SLOT-TIMEOUT", actor=FA), D, {}, "LOST-RACE", None),
    ("4c-m-after-qualified", [SI, QU], rq("SLOT-MISSED", op=N1, actor=FA), E, {}, "LOST-RACE", None),
    ("4c-m-after-failed", [SI, FL], rq("SLOT-MISSED", op=N1, actor=FA), E, {}, "LOST-RACE", None),
    ("4c-m-after-timeout", [SI, TO], rq("SLOT-MISSED", op=N1, actor=FA), D, {}, "LOST-RACE", None),
    ("4c-m-after-missed", [MI], rq("SLOT-MISSED", op=N1, actor=FA), E, {}, "LOST-RACE", None),
    ("4c-m-qualified-before-e", [SI, QU], rq("SLOT-MISSED", op=N1, actor=FA), E - US, {}, "LOST-RACE", None),
    ("4c-p-same", [GI, GP], rq("STAGE-PREPARED", G, detail=H1), E, {}, "LOST-RACE", None),
    ("4c-p-different", [GI, GP], rq("STAGE-PREPARED", G, detail=H2), E, {}, "INVALIDATE", "contradictory-stage"),
    ("4c-c-differs-from-prepared", [GI, GP], rq("STAGE-CREATED", G, detail=H2), E, {}, "INVALIDATE",
     "contradictory-stage"),
    ("4c-c-created-same", [GI, GP, GC], rq("STAGE-CREATED", G, actor=FA, detail=H1), E, {}, "LOST-RACE", None),
    ("4c-stop-same", [ST], rq("TRIAL-STOP", "trial", op=N1, actor=FA, detail=H1), E, {}, "LOST-RACE", None),
    ("4c-stop-different", [ST], rq("TRIAL-STOP", "trial", op=N1, actor=FA, detail=H2), E, {}, "INVALIDATE",
     "stop-conflict"),
    ("4d-m-in-flight", [SI], rq("SLOT-MISSED", op=N1, actor=FA), E, {}, "REFUSE", None),
    ("5-si-stopped", [ST], rq("SLOT-INTENT", op=N1), E - US, {}, "LOST-RACE", None),
    ("5-si-gate-refuses", [], rq("SLOT-INTENT", op=N1), E - US, {"slot_gate": lambda rows, s: "no PREREG-ACK"},
     "REFUSE", None),
    ("5-gi-forbidden", [], rq("STAGE-INTENT", G, op=N1, detail=H1), E, {"stage_gate": lambda rows, g: "no pred"},
     "REFUSE", None),
    ("5-stop-rule-not-met", [], rq("TRIAL-STOP", "trial", op=N1, actor=FA, detail=H1), E,
     {"stop_detail": lambda rows: None}, "REFUSE", None),
    ("5-stop-differs-from-recomputed", [], rq("TRIAL-STOP", "trial", op=N1, actor=FA, detail=H2), E, {}, "REFUSE",
     None),
    ("5-q-intent-before-stop", [SI, ST], Q(), E, {}, "APPEND", None),
    ("5-q-intent-after-stop", [ST, SI], Q(), E, {}, "REFUSE", None),
    ("6-si-at-e", [], rq("SLOT-INTENT", op=N1), E, {}, "REFUSE", None),
    ("6-si-before-e", [], rq("SLOT-INTENT", op=N1), E - US, {}, "APPEND", None),
    ("6-q-r-at-d", [SI], Q(r_at=D), D, {}, "REFUSE", None),
    ("6-q-r-d-plus-1us", [SI], Q(r_at=D + US), D + US, {}, "REFUSE", None),
    ("6-q-r-d-minus-1us", [SI], Q(r_at=D - US), D, {}, "APPEND", None),
    ("6-t-before-d", [SI], rq("SLOT-TIMEOUT", actor=FA), D - US, {}, "REFUSE", None),
    ("6-m-before-e", [], rq("SLOT-MISSED", op=N1, actor=FA), E - US, {}, "REFUSE", None),
    ("6-m-at-e", [], rq("SLOT-MISSED", op=N1, actor=FA), E, {}, "APPEND", None),
    ("7-t-finalizer-actor", [SI], rq("SLOT-TIMEOUT", actor=FA), D, {}, "APPEND", None),
    ("7-gi-permitted", [], rq("STAGE-INTENT", G, op=N1, detail=H1), E, {}, "APPEND", None),
    ("7-p", [GI], rq("STAGE-PREPARED", G, detail=H1), E, {}, "APPEND", None),
    ("7-c-opening-actor", [GI, GP], rq("STAGE-CREATED", G, detail=H1), E, {}, "APPEND", None),
    ("7-c-recovery-actor", [GI, GP], rq("STAGE-CREATED", G, actor=FA, detail=H1), E, {}, "APPEND", None),
    ("7-trial-invalid-active", [], rq("TRIAL-INVALID", "reason/bundle", op=N1, actor=FA, detail=H1), E, {}, "APPEND",
     None),
    ("7-trial-invalid-stopped", [ST], rq("TRIAL-INVALID", "reason/bundle", op=N1, actor=FA, detail=H1), E, {},
     "APPEND", None),
    ("7-stop", [], rq("TRIAL-STOP", "trial", op=N1, actor=FA, detail=H1), E, {}, "APPEND", None),
]


@pytest.mark.parametrize("cid,specs,req,now,kw,outcome,reason", CASES, ids=[x[0] for x in CASES])
def test_precedence_table(cid, specs, req, now, kw, outcome, reason):
    dec = j.decide(build(specs), req, ctx(**kw), now)
    assert dec.outcome == outcome, (cid, dec)
    if outcome == "INVALIDATE":
        assert dec.reason == reason


ONE = {"SLOT-INTENT": rq("SLOT-INTENT", S2, op=N1), "SLOT-QUALIFIED": Q(), "SLOT-FAILED": rq("SLOT-FAILED", detail=H1),
       "SLOT-TIMEOUT": rq("SLOT-TIMEOUT", actor=FA), "SLOT-MISSED": rq("SLOT-MISSED", S2, op=N1, actor=FA),
       "STAGE-INTENT": rq("STAGE-INTENT", G, op=N1, detail=H1), "STAGE-PREPARED": rq("STAGE-PREPARED", G, detail=H1),
       "STAGE-CREATED": rq("STAGE-CREATED", G, detail=H1),
       "TRIAL-STOP": rq("TRIAL-STOP", "trial", op=N1, actor=FA, detail=H1),
       "TRIAL-INVALID": rq("TRIAL-INVALID", "reason/LOST", op=N1, actor=FA, detail=H1)}


@pytest.mark.parametrize("kind", j.KINDS)
def test_closed_refuses_every_kind_including_trial_invalid(kind):
    assert j.decide(build([SI, GI, GP]), ONE[kind], ctx(closed=True), D).outcome == "REFUSE"


@pytest.mark.parametrize("kind", j.KINDS)
def test_invalid_appends_trial_invalid_and_lost_races_every_other_kind(kind):
    want = "APPEND" if kind == "TRIAL-INVALID" else "LOST-RACE"
    assert j.decide(build([SI, GI, GP, IV]), ONE[kind], ctx(), D).outcome == want


def test_trial_state_derivation():
    assert j.trial_state(build([SI])) == "ACTIVE"
    assert j.trial_state(build([SI, ST])) == "STOPPED"
    assert j.trial_state(build([SI, ST, IV])) == "INVALID"
    assert j.trial_state(build([IV])) == "INVALID"


def test_reused_op_on_an_opening_row_is_refused():
    """OQ-3."""
    assert j.decide(build([SI]), rq("SLOT-MISSED", S2, op=AO, actor=FA), ctx(), E).outcome == "REFUSE"


# ---------------------------------------------------------------- through the real transaction
def ctxf(**kw):
    return lambda rows, con: ctx(**kw)


def kinds(mb):
    return [r.kind for r in j.read_trial(TRIAL, GEN, mb)]


def test_append_decides_on_the_state_read_inside_the_transaction(tmp_path):
    mb = s1_mailbox_init(tmp_path)
    j.append(TRIAL, GEN, rq("SLOT-INTENT"), ctxf(), mailbox=mb, clock=lambda: E - timedelta(minutes=5))
    stale = j.read_trial(TRIAL, GEN, mb)
    assert j.decide(stale, Q(r_at=D - US), ctx(), D).outcome == "APPEND"        # what the worker saw earlier
    j.append(TRIAL, GEN, rq("SLOT-TIMEOUT", actor=FA), ctxf(), mailbox=mb, clock=lambda: D)     # T commits first
    res = j.append(TRIAL, GEN, Q(r_at=D - US), ctxf(), mailbox=mb, clock=lambda: D + US)
    assert (res.outcome, res.row) == ("LOST-RACE", None) and kinds(mb) == ["SLOT-INTENT", "SLOT-TIMEOUT"]


def test_invalidate_appends_trial_invalid_instead_in_the_same_transaction(tmp_path):
    mb = s1_mailbox_init(tmp_path)
    j.append(TRIAL, GEN, rq("SLOT-INTENT"), ctxf(), mailbox=mb, clock=lambda: E - timedelta(minutes=5))
    res = j.append(TRIAL, GEN, Q(op=BO), ctxf(), mailbox=mb, clock=lambda: E - US)
    assert (res.outcome, res.reason) == ("INVALIDATE", "contradictory-completion")
    rows = j.read_trial(TRIAL, GEN, mb)
    assert [r.kind for r in rows] == ["SLOT-INTENT", "TRIAL-INVALID"] and res.row == rows[1]
    assert (rows[1].subject, rows[1].op, rows[1].actor) == ("reason/contradictory-completion", BO, AA)
    assert rows[1].detail == j.detail_of({"reason": "contradictory-completion", "requested": {
        "kind": "SLOT-QUALIFIED", "subject": S, "op": BO, "actor": AA, "detail": H1}})


def _put_lines(mb, specs, *, drop=None, dup=None):
    rows = build(specs)
    con = sqlite3.connect(mb)
    for r in rows:
        if r.seq != drop:
            con.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,NULL)", (r.mailbox_id, "s1", "codex",
                                                                          "experiments-s1-journal", r.line, r.created))
    if dup is not None:
        con.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,NULL)", ("dup", "s1", "codex", "experiments-s1-journal",
                                                                      dup, 99.0))
    con.commit()
    con.close()


@pytest.mark.parametrize("damage", ["gap", "fork", "dup", "format"])
def test_chain_integrity_refuses_with_no_row(tmp_path, damage):
    mb = s1_mailbox_init(tmp_path)
    specs = [SI, row("SLOT-INTENT", S2, op=N1)]
    if damage == "gap":
        _put_lines(mb, specs + [row("SLOT-INTENT", "slot/20261102T214900Z", op=N2)], drop=2)
    elif damage == "fork":
        other = build([SI, row("SLOT-INTENT", "slot/20261102T215100Z", op="8" * 32)])[1].line
        _put_lines(mb, specs, dup=other)
    elif damage == "dup":
        _put_lines(mb, specs, dup=build(specs)[1].line)                      # a byte-identical second seq 2
    else:
        _put_lines(mb, specs, dup="S1-JOURNAL garbage")
    with sqlite3.connect(mb) as con:
        before = con.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    with pytest.raises(j.ChainError):
        j.append(TRIAL, GEN, rq("SLOT-INTENT", "slot/20261102T215300Z", op="6" * 32), ctxf(), mailbox=mb,
                 clock=lambda: E - US)
    with sqlite3.connect(mb) as con:
        assert con.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == before


MALFORMED = {
    "unknown-kind": rq("SLOT-RETRY"),
    "subject-for-kind": rq("STAGE-INTENT", S, op=N1, detail=H1),
    "detail-on-intent": rq("SLOT-INTENT", detail=H1),
    "absent-on-qualified": rq("SLOT-QUALIFIED", r_at=E),
    "op-not-hex": rq("SLOT-INTENT", op="Z" * 32),
    "qualified-without-r": rq("SLOT-QUALIFIED", detail=H1),
    "naive-r": rq("SLOT-QUALIFIED", detail=H1, r_at=E.replace(tzinfo=None)),
    "r-on-failed": rq("SLOT-FAILED", detail=H1, r_at=E),
    "unknown-reason": rq("TRIAL-INVALID", "reason/whatever", op=N1, detail=H1),
}


@pytest.mark.parametrize("case", sorted(MALFORMED))
def test_malformed_requests_are_refused_with_no_row(tmp_path, case):
    mb = s1_mailbox_init(tmp_path)
    with pytest.raises(j.RequestError):
        j.append(TRIAL, GEN, MALFORMED[case], ctxf(), mailbox=mb, clock=lambda: E - US)
    assert kinds(mb) == []


def test_an_exception_inside_the_transaction_appends_no_row(tmp_path):
    """F0.7 at the primitive: any exception (here from the caller's context) rolls back."""
    mb = s1_mailbox_init(tmp_path)

    def boom(rows, con):
        raise RuntimeError("unexpected")
    with pytest.raises(RuntimeError):
        j.append(TRIAL, GEN, rq("SLOT-INTENT"), boom, mailbox=mb, clock=lambda: E - US)
    assert kinds(mb) == []


# ---------------------------------------------------------------- step-4 sub-order disjointness (Hypothesis)
HISTORIES = [[], [SI], [SI, QU], [SI, FL], [SI, TO], [MI], [SI, row("SLOT-INTENT", op=BO)]]


def oracle(specs, req, now):
    """An independent transcription of the F0.5 table for slot requests: every condition of a sub-step is evaluated;
    at most one may hold (disjointness); the first sub-step that has one decides."""
    rows = [r for r in build(specs) if r.subject == req.subject]
    intent = next((r for r in rows if r.kind == "SLOT-INTENT"), None)
    term = next((r for r in rows if r.kind in j.TERMINAL), None)
    k = req.kind
    sub = {
        "4a": [(k in ("SLOT-QUALIFIED", "SLOT-FAILED") and (intent is None or req.op != intent.op
                                                             or req.actor != intent.actor),
                "INVALIDATE"),
               (k == "SLOT-TIMEOUT" and (intent is None or req.op != intent.op), "INVALIDATE")],
        "4b": [(k == "SLOT-INTENT" and bool(rows), "INVALIDATE")],
        "4c": [(k in ("SLOT-QUALIFIED", "SLOT-FAILED", "SLOT-TIMEOUT", "SLOT-MISSED") and term is not None,
                "LOST-RACE")],
        "4d": [(k == "SLOT-MISSED" and intent is not None and term is None, "REFUSE")],
        "6": [(k == "SLOT-INTENT" and now >= E, "REFUSE"), (k == "SLOT-QUALIFIED" and req.r_at >= D, "REFUSE"),
              (k == "SLOT-TIMEOUT" and now < D, "REFUSE"), (k == "SLOT-MISSED" and now < E, "REFUSE")],
    }
    for step in ("4a", "4b", "4c", "4d", "6"):
        hits = [out for cond, out in sub[step] if cond]
        assert len(hits) <= 1, (step, hits)
        if hits:
            return hits[0]
    return "APPEND"


# Scope (f045bd31): slot-subject histories × slot kinds × 5 instants. Stage and trial lifecycles are covered by the
# explicit tables, not by this property. Pinned per Global Constraints (derandomize, seed, kept example database);
# every minimized counterexample found during development is added as an @example and kept.
@seed(20261103)
@settings(max_examples=400, deadline=None, derandomize=True,
          database=DirectoryBasedExampleDatabase(str(HERE / "s1_evidence" / "a3" / "hypothesis_db")))
@given(hist=st.sampled_from(HISTORIES), kind=st.sampled_from(j.SLOT_KINDS),
       who=st.sampled_from([(AO, AA), (BO, AA), (AO, BA), (BO, BA)]),
       now=st.sampled_from([E - US, E, D - US, D, D + US]))
def test_substep_conditions_are_disjoint_and_decide_matches_the_oracle(hist, kind, who, now):
    op, actor = who
    if kind in ("SLOT-INTENT", "SLOT-MISSED"):
        op = N1                                                     # rows that open their own op (OQ-3)
    req = rq(kind, op=op, actor=FA if kind in ("SLOT-TIMEOUT", "SLOT-MISSED") else actor,
             detail=H1 if kind in ("SLOT-QUALIFIED", "SLOT-FAILED") else None,
             r_at=now if kind == "SLOT-QUALIFIED" else None)
    assert j.decide(build(hist), req, ctx(), now).outcome == oracle(hist, req, now)
```

- [ ] **Step 3: Run the tests and record a behavioural RED.** Run the file into `a3/t2_red.txt`.
  - Expected: every non-APPEND case of `test_precedence_table` fails with `assert 'APPEND' == …`, as do the
    CLOSED/INVALID tests, `test_append_decides…` (APPEND instead of LOST-RACE), `test_invalidate…`,
    `test_reused_op…` and the oracle property.
  - The malformed and chain tests pass: Task 1 already enforces them. Label them `retro`.
  - The `7-*` and `6-si-before-e`/`6-m-at-e`/`6-q-r-d-minus-1us`/`5-q-intent-before-stop` cases pass. Label them
    `ctrl`.

- [ ] **Step 4: Implement `decide` in `research/s1/s1_journal.py`.** Replace the Task 1 stub:

```python
def trial_state(rows) -> str:
    """F1: INVALID = any TRIAL-INVALID (with or without a stop); STOPPED = a TRIAL-STOP and no TRIAL-INVALID; else
    ACTIVE. CLOSED is an authorization status layered on top by s1_trial (F7.5)."""
    ks = {r.kind for r in rows}
    if "TRIAL-INVALID" in ks:
        return "INVALID"
    return "STOPPED" if "TRIAL-STOP" in ks else "ACTIVE"


def subject_rows(rows, subject) -> list:
    return [r for r in rows if r.subject == subject]


def first(rows, *kinds):
    return next((r for r in rows if r.kind in kinds), None)


def decide(rows, req, ctx, now) -> Decision:
    """F0.5 precedence on the state read inside the transaction (step 1, chain integrity, is verify_chain, run before
    this). Steps in order; the first that decides wins; the step-4 sub-steps 4a, 4b, 4c, 4d are disjoint. The OQ-3
    reused-op check (a malformed opening request: REFUSE) runs after 4b, so a repeated subject is still
    repeat-attempt / repeat-stage (f045bd31 OQ-3 ruling)."""
    if ctx.closed:                                                                     # step 2
        return Decision("REFUSE", "trial CLOSED: no row of any kind")
    state = trial_state(rows)
    if state == "INVALID":                                                             # step 3
        if req.kind == "TRIAL-INVALID":
            return Decision("APPEND", "an extra INVALID observation")
        return Decision("LOST-RACE", "trial INVALID: no work")
    if req.kind == "TRIAL-INVALID":                                                    # (no step-4..6 rule applies)
        return Decision("APPEND")
    mine = subject_rows(rows, req.subject)
    reused = req.kind in OPENING and any(r.op == req.op for r in rows)                 # OQ-3, applied after 4b
    if req.kind in SLOT_KINDS:
        return _slot(rows, mine, req, ctx, now, state, reused)
    if req.kind in STAGE_KINDS:
        return _stage(rows, mine, req, ctx, reused)
    return _stop(rows, req, ctx, reused)


_REUSED = Decision("REFUSE", "an opening row must open a new op; this op is already used (OQ-3: malformed)")


def _slot(rows, mine, req, ctx, now, state, reused=False) -> Decision:
    intent, terminal, k = first(mine, "SLOT-INTENT"), first(mine, *TERMINAL), req.kind
    # 4a identity (before terminal state, so a foreign completion stays invalid on a terminal subject)
    if k in ("SLOT-QUALIFIED", "SLOT-FAILED") and (intent is None or req.op != intent.op
                                                   or req.actor != intent.actor):
        return Decision("INVALIDATE", "contradictory-completion")
    if k == "SLOT-TIMEOUT" and (intent is None or req.op != intent.op):
        return Decision("INVALIDATE", "contradictory-finalizer")
    # 4b repeat
    if k == "SLOT-INTENT" and mine:
        return Decision("INVALIDATE", "repeat-attempt")
    if reused:                                                                         # OQ-3 (after 4b)
        return _REUSED
    # 4c already decided
    if k != "SLOT-INTENT" and terminal is not None:
        return Decision("LOST-RACE", f"stale: {req.subject} is already {terminal.kind}")
    # 4d in-flight conflict
    if k == "SLOT-MISSED" and intent is not None:
        return Decision("REFUSE", "in flight: the finalizer re-evaluates for a TIMEOUT at D")
    # 5 trial-state permission (F1)
    if k == "SLOT-INTENT":
        if state == "STOPPED":
            return Decision("LOST-RACE", "STOPPED: no capture after the stop (not invalid)")
        why = ctx.slot_gate(rows, req.subject) if ctx.slot_gate is not None else None
        if why:
            return Decision("REFUSE", why)
    if k in ("SLOT-QUALIFIED", "SLOT-FAILED") and state == "STOPPED":
        stop = first(rows, "TRIAL-STOP")
        if not intent.seq < stop.seq:
            return Decision("REFUSE", "completion after the STOP needs its INTENT before the STOP (F1)")
    # 6 timing (E, D, R)
    if ctx.slot_times is None:
        return Decision("REFUSE", "no slot timing supplied (fail closed)")
    e, d = ctx.slot_times(req.subject)
    if k == "SLOT-INTENT" and now >= e:
        return Decision("REFUSE", "now >= E: the finalizer appends MISSED")
    if k == "SLOT-QUALIFIED" and req.r_at >= d:
        return Decision("REFUSE", "late R (R >= D): the finalizer later appends TIMEOUT")
    if k == "SLOT-TIMEOUT" and now < d:
        return Decision("REFUSE", "premature finalizer (now < D)")
    if k == "SLOT-MISSED" and now < e:
        return Decision("REFUSE", "premature finalizer (now < E)")
    return Decision("APPEND")                                                          # 7 (SLOT-FAILED: OQ-12)


def _stage(rows, mine, req, ctx, reused=False) -> Decision:
    intent, prepared, created = (first(mine, x) for x in STAGE_KINDS)
    k = req.kind
    if k == "STAGE-PREPARED" and (intent is None or req.op != intent.op or req.actor != intent.actor):   # 4a
        return Decision("INVALIDATE", "contradictory-stage")
    if k == "STAGE-CREATED" and (prepared is None or req.op != intent.op):                                # 4a
        return Decision("INVALIDATE", "contradictory-stage")
    if k == "STAGE-INTENT" and intent is not None:                                                         # 4b
        return Decision("INVALIDATE", "repeat-stage")
    if reused:                                                                                             # OQ-3
        return _REUSED
    if k == "STAGE-PREPARED" and prepared is not None:                                                     # 4c
        if req.detail == prepared.detail:
            return Decision("LOST-RACE", "PREPARED already committed (idempotent)")
        return Decision("INVALIDATE", "contradictory-stage")
    if k == "STAGE-CREATED":                                                                               # 4c
        if req.detail != prepared.detail:
            return Decision("INVALIDATE", "contradictory-stage")
        if created is not None:
            if req.detail == created.detail:
                return Decision("LOST-RACE", "CREATED already committed (idempotent recovery)")
            return Decision("INVALIDATE", "contradictory-stage")
    if k == "STAGE-INTENT":                                                                                # 5
        why = (ctx.stage_gate(rows, req.subject[len("stage/"):]) if ctx.stage_gate is not None
               else "no stage gate supplied (fail closed)")
        if why:
            return Decision("REFUSE", why)
    return Decision("APPEND")


def _stop(rows, req, ctx, reused=False) -> Decision:
    stop = first(rows, "TRIAL-STOP")
    if stop is not None:                                                                                   # 4c
        if req.detail == stop.detail:
            return Decision("LOST-RACE", "already STOPPED with this record")
        return Decision("INVALIDATE", "stop-conflict")
    if reused:                                                                                             # OQ-3
        return _REUSED
    want = ctx.stop_detail(rows) if ctx.stop_detail is not None else None                                 # 5
    if want is None:
        return Decision("REFUSE", "the stop rule is not met by committed history")
    if want != req.detail:
        return Decision("REFUSE", "the stop record differs from the one committed history gives (OQ-9: escalate)")
    return Decision("APPEND")
```

- [ ] **Step 5: GREEN.** Run `test_s1_a3_precedence.py` and `test_s1_a3_journal.py` into `a3/t2_green.txt`. All
  pass.
- [ ] **Step 6: Full suite, old->new, hashes.** Save `a3/t2_full.txt`, `a3/t2_old_new.md` (expected: none) and
  `a3/t2_hashes.txt`.
- [ ] **Step 7: Controller review and commit.**
  - Message: `S1 A3 Task 2: F0.5 append precedence (4a-4d sub-order)`, listing map rows 7, 12, 13, 16, 21–49 and 54.
  - End with the Co-Authored-By line. Push, and assert the HEAD SHA.

---

### Task 3: Ownership locks (F5.1–F5.5, OQ-23)

**Files:**
- Create: `research/s1/s1_locks.py`
- Modify: `research/s1/s1_common.py` (BUNDLE_CODE gains `s1_locks.py`); `research/s1/s1_tests/test_s1_t12_a3_a8.py`
  (BUNDLE tuple, old->new)
- Create: `research/s1/s1_tests/test_s1_a3_locks.py`

**Interfaces:**
- Produces (`s1_locks`):
  - `LockHeld(Exception)`: "held by another process". Only a sharing violation (Windows error 32) or a lock
    violation (33).
  - `LockError(Exception)`: any other I/O or permission error. Fails closed.
  - `lock_path(root, trial_id, name) -> Path`. It validates the uuid4 trial_id and the name against `NAME_RE` (the
    OQ-23 grammar) and raises LockError otherwise.
  - `slot_lock_name(subject: str) -> str` (`"slot/20261102T214500Z"` -> `"slot-20261102T214500Z"`);
    `stage_lock_name(stage: str) -> str` (`"stage-audit"`); `STOP_LOCK = "stop"`.
  - `lock_acquirable(root, trial_id, name) -> bool`: the E1.4 cleanup probe. It acquires and releases at once,
    returns False on LockHeld and propagates LockError. Never used for a decision.
  - `class OwnershipLock(root, trial_id, name)` with `.path`, `.acquire() -> self` (raises LockHeld or LockError),
    `.release()`, `__enter__`/`__exit__` (`__enter__` acquires).
- Consumes: nothing from earlier tasks.

- [ ] **Step 1: Interface stub.** It always acquires and never excludes:

```python
"""S1 ownership locks - Task 3 INTERFACE STUB (permissive; replaced in Step 4)."""
from pathlib import Path

STOP_LOCK = "stop"


class LockHeld(Exception):
    pass


class LockError(Exception):
    pass


def lock_path(root, trial_id, name) -> Path:
    return Path(root) / "s1_out" / f"{name}.lock"


def slot_lock_name(subject: str) -> str:
    return "slot-" + subject.split("/", 1)[1]


def stage_lock_name(stage: str) -> str:
    return "stage-" + stage


def lock_acquirable(root, trial_id, name) -> bool:
    return True


class OwnershipLock:
    def __init__(self, root, trial_id, name):
        self.path = lock_path(root, trial_id, name)

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch()
        return self

    def release(self):
        return None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
        return False
```

- [ ] **Step 2: Write the failing tests.** Create `research/s1/s1_tests/test_s1_a3_locks.py`. The tests use real child
  processes: they hold the lock or open the file, and the parent kills them for a real crash. There is no mocked
  liveness flag (F5.4).

```python
"""Addendum 3 rev 5 F5 (ownership locks): isolated processes, real crashes (killed children), concurrent acquisition;
no mocked live flag (F5.4). Behavioural RED against the Task 3 stub (s1_evidence/a3/t3_red.txt). Windows only (F5.2:
share mode + msvcrt.locking); tmp_path only."""
import os
import subprocess
import sys
from pathlib import Path

import pytest
import s1_locks as L

HERE = Path(__file__).resolve().parent.parent
TRIAL = "3f2b8c1e-5d4a-4b6c-9e7f-0a1b2c3d4e5f"
HOLD = r'''
import sys
sys.path.insert(0, sys.argv[1])
import s1_locks
try:
    s1_locks.OwnershipLock(sys.argv[2], sys.argv[3], sys.argv[4]).acquire()
    print("acquired", flush=True)
except s1_locks.LockHeld:
    print("held", flush=True)
    sys.exit(0)
sys.stdin.readline()
'''
OPEN_PLAIN = r'''
import sys
f = open(sys.argv[1], "r+b")
print("opened", flush=True)
sys.stdin.readline()
'''


def child(script, *args):
    p = subprocess.Popen([sys.executable, "-I", "-c", script, *map(str, args)], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, text=True)
    return p, p.stdout.readline().strip()


def stop(p, kill=False):
    if kill:
        p.kill()
    else:
        p.stdin.close()
    p.wait(timeout=30)


def test_lock_lives_outside_s1_out(tmp_path):
    p = L.lock_path(tmp_path, TRIAL, L.stage_lock_name("audit"))
    assert p == tmp_path / "s1_locks" / TRIAL / "stage-audit.lock"
    assert (tmp_path / "s1_out") not in p.parents
    assert L.slot_lock_name("slot/20261102T214500Z") == "slot-20261102T214500Z" and L.STOP_LOCK == "stop"


def test_acquire_release_and_reacquire_in_one_process(tmp_path):
    a = L.OwnershipLock(tmp_path, TRIAL, "stage-audit").acquire()
    with pytest.raises(L.LockHeld):
        L.OwnershipLock(tmp_path, TRIAL, "stage-audit").acquire()
    a.release()
    with L.OwnershipLock(tmp_path, TRIAL, "stage-audit"):
        pass


def test_held_by_another_process_is_held_not_dead(tmp_path):
    p, said = child(HOLD, HERE, tmp_path, TRIAL, "slot-20261102T214500Z")
    try:
        assert said == "acquired"
        with pytest.raises(L.LockHeld):
            L.OwnershipLock(tmp_path, TRIAL, "slot-20261102T214500Z").acquire()
    finally:
        stop(p)


def test_held_lock_cannot_be_deleted_renamed_or_replaced(tmp_path):
    p, said = child(HOLD, HERE, tmp_path, TRIAL, "stop")
    path = L.lock_path(tmp_path, TRIAL, "stop")
    other = tmp_path / "other.txt"
    other.write_text("x")
    try:
        assert said == "acquired"
        with pytest.raises(PermissionError):
            os.remove(path)
        with pytest.raises(PermissionError):
            os.rename(path, tmp_path / "moved.lock")
        with pytest.raises(PermissionError):
            os.replace(other, path)
        assert path.exists()
    finally:
        stop(p)


def test_killed_owner_frees_the_lock(tmp_path):
    p, said = child(HOLD, HERE, tmp_path, TRIAL, "stage-final")
    assert said == "acquired"
    stop(p, kill=True)                                            # a real crash: the OS releases the handle
    with L.OwnershipLock(tmp_path, TRIAL, "stage-final"):
        pass


def test_leftover_acquirable_lock_file_is_no_liveness(tmp_path):
    path = L.lock_path(tmp_path, TRIAL, "stage-score")
    path.parent.mkdir(parents=True)
    path.write_text("pid 4242 started yesterday")                 # no PID inference
    with L.OwnershipLock(tmp_path, TRIAL, "stage-score"):
        pass


def test_deleted_lock_file_is_recreated_and_is_not_evidence(tmp_path):
    with L.OwnershipLock(tmp_path, TRIAL, "stage-prereg") as lk:
        path = lk.path
    path.unlink()
    with L.OwnershipLock(tmp_path, TRIAL, "stage-prereg"):
        assert path.exists()


def test_concurrent_recovery_exactly_one_acquires(tmp_path):
    procs = [subprocess.Popen([sys.executable, "-I", "-c", HOLD, str(HERE), str(tmp_path), TRIAL, "stage-opening"],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) for _ in range(2)]
    try:
        said = sorted(p.stdout.readline().strip() for p in procs)
        assert said == ["acquired", "held"]
    finally:
        for p in procs:
            if p.poll() is None:
                stop(p)


def test_sharing_violation_from_any_holder_is_held(tmp_path):
    """Review Focus 5: a third program (AV, indexer) holding the file is 'held' (pending), never 'free'."""
    path = L.lock_path(tmp_path, TRIAL, "slot-20261102T214700Z")
    path.parent.mkdir(parents=True)
    path.write_bytes(b"")
    p, said = child(OPEN_PLAIN, path)
    try:
        assert said == "opened"
        with pytest.raises(L.LockHeld):
            L.OwnershipLock(tmp_path, TRIAL, "slot-20261102T214700Z").acquire()
    finally:
        stop(p)


@pytest.mark.parametrize("damage", ["directory-at-lock-path", "file-at-locks-dir"])
def test_io_error_is_error_not_held_or_free(tmp_path, damage):
    if damage == "directory-at-lock-path":
        L.lock_path(tmp_path, TRIAL, "slot-20261102T214900Z").mkdir(parents=True)
    else:
        (tmp_path / "s1_locks").write_text("not a directory")
    with pytest.raises(L.LockError):
        L.OwnershipLock(tmp_path, TRIAL, "slot-20261102T214900Z").acquire()


@pytest.mark.parametrize("trial,name", [(TRIAL, "../stage-audit"), (TRIAL, "slot-a/b"), (TRIAL, "stage-other"),
                                        ("S1", "stage-audit")],
                         ids=["dotdot-name", "slash-name", "unknown-stage", "bad-trial"])
def test_lock_names_and_trial_ids_are_validated(tmp_path, trial, name):             # row 309 (OQ-23)
    with pytest.raises(L.LockError):
        L.OwnershipLock(tmp_path, trial, name).acquire()
    assert list(tmp_path.rglob("*")) == []                     # validation precedes any mkdir or open


def test_lock_acquirable_probe(tmp_path):                                              # E1.4 seam (rows 257, 259)
    name = "slot-20261102T214500Z"
    assert L.lock_acquirable(tmp_path, TRIAL, name) is True
    p, said = child(HOLD, HERE, tmp_path, TRIAL, name)
    try:
        assert said == "acquired" and L.lock_acquirable(tmp_path, TRIAL, name) is False
    finally:
        stop(p)
    assert L.lock_acquirable(tmp_path, TRIAL, name) is True
```

- [ ] **Step 3: Behavioural RED.** Run into `a3/t3_red.txt`.
  - Expected failures: `lock_path` points under s1_out; no `LockHeld`; the delete/rename/replace succeed; both
    children print `acquired`; the I/O error is not `LockError` (a directory at the path makes `touch` raise
    PermissionError, which is not LockError).
  - `test_lock_names_and_trial_ids_are_validated[*]` fails (the stub accepts every name and writes under s1_out).
    `test_lock_acquirable_probe` fails at the held step (the stub always returns True).
  - `test_killed_owner…`, `test_leftover…` and `test_deleted…` pass on the stub. Label them `ctrl`: their meaning
    comes from the other tests.

- [ ] **Step 4: Implement `research/s1/s1_locks.py`:**

```python
"""S1 ownership locks (Addendum 3 rev 5 F5). One lock file per slot, stage or stop operation at
<root>/s1_locks/<trial_id>/<name>.lock, outside s1_out (F5.2). It is opened with CreateFileW sharing READ only (never
FILE_SHARE_WRITE or FILE_SHARE_DELETE) and byte-range locked with msvcrt.locking, so while it is held it cannot be
deleted, renamed or replaced; the OS releases it when the process ends. Exactly three results (F5.5): acquired;
LockHeld (Windows sharing or lock violation - the only liveness evidence); LockError (any other I/O or permission
error: fail closed, never 'live' or 'dead'). No PID inference; a leftover acquirable file is no liveness."""
import ctypes
import errno
import os
import re
import sys
from pathlib import Path

GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
FILE_SHARE_READ = 0x00000001
OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL = 4, 0x80
ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION = 32, 33
STOP_LOCK = "stop"                                                                 # OQ-23


class LockHeld(Exception):
    """Held by another process (a Windows sharing or lock violation)."""


class LockError(Exception):
    """Any other I/O or permission error: the caller refuses with no row (F5.5)."""


if sys.platform == "win32":
    import msvcrt
    from ctypes import wintypes
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                 wintypes.DWORD, wintypes.HANDLE)
    _k32.CreateFileW.restype = wintypes.HANDLE
    _k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _INVALID = wintypes.HANDLE(-1).value


NAME_RE = re.compile(r"^(slot-\d{8}T\d{6}Z|stage-(audit|opening|start_attest|prereg|stop_attest|final_plan|final"
                     r"|score)|stop)$")                                                   # OQ-23 ruling
UUID4_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def lock_path(root, trial_id: str, name: str) -> Path:
    """Validated: a uuid4 trial_id and a name from the closed grammar; anything else is LockError (no traversal, no
    cross-trial aliasing)."""
    if not isinstance(trial_id, str) or not UUID4_RE.match(trial_id):
        raise LockError("lock trial_id is not a uuid4")
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise LockError(f"lock name {name!r} is outside the OQ-23 grammar")
    return Path(root) / "s1_locks" / trial_id / f"{name}.lock"


def slot_lock_name(subject: str) -> str:
    return "slot-" + subject.split("/", 1)[1]


def stage_lock_name(stage: str) -> str:
    return "stage-" + stage


def lock_acquirable(root, trial_id: str, name: str) -> bool:
    """E1.4: the cleanup probe. True only when this process could acquire the lock (it is then released at once);
    False when LockHeld. LockError propagates (fail closed). It never decides a terminal row."""
    try:
        OwnershipLock(root, trial_id, name).acquire().release()
        return True
    except LockHeld:
        return False


def _open_exclusive(path: Path) -> int:
    if sys.platform != "win32":
        raise LockError("ownership locks require Windows share modes (F5.2): fail closed")
    h = _k32.CreateFileW(str(path), GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ, None, OPEN_ALWAYS,
                         FILE_ATTRIBUTE_NORMAL, None)
    if h is None or h == _INVALID:
        err = ctypes.get_last_error()
        if err in (ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION):
            raise LockHeld(f"{path.name}: held by another process (Windows error {err})")
        raise LockError(f"{path.name}: lock I/O error (Windows error {err})")
    try:
        return msvcrt.open_osfhandle(h, os.O_RDWR)
    except OSError as e:
        _k32.CloseHandle(h)
        raise LockError(f"{path.name}: handle conversion failed ({type(e).__name__})") from None


class OwnershipLock:
    def __init__(self, root, trial_id: str, name: str):
        self.path = lock_path(root, trial_id, name)
        self.fd = None

    def acquire(self) -> "OwnershipLock":
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise LockError(f"lock directory unavailable ({type(e).__name__})") from None
        fd = _open_exclusive(self.path)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as e:
            os.close(fd)
            if e.errno in (errno.EACCES, errno.EDEADLOCK):
                raise LockHeld(f"{self.path.name}: byte range locked by another process") from None
            raise LockError(f"{self.path.name}: lock I/O error ({type(e).__name__})") from None
        self.fd = fd
        return self

    def release(self) -> None:
        if self.fd is None:
            return
        try:
            msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        os.close(self.fd)
        self.fd = None

    def __enter__(self) -> "OwnershipLock":
        return self.acquire()

    def __exit__(self, *exc) -> bool:
        self.release()
        return False
```

Add `"s1_locks.py"` to `BUNDLE_CODE`, in sorted position after `s1_journal.py`, and to the
`test_s1_t12_a3_a8.py` BUNDLE tuple (old->new). Extend `test_bundle_pins_addendum3_and_lists_every_new_module` with
`assert "s1_locks.py" in c.BUNDLE_CODE`.

- [ ] **Step 5: GREEN.** Run `test_s1_a3_locks.py` into `a3/t3_green.txt`, three times in a row, to rule out a
  timing-dependent pass. All pass each time.
- [ ] **Step 6: Full suite, old->new, hashes.** Save `a3/t3_full.txt`, `a3/t3_old_new.md` (the BUNDLE tuple line) and
  `a3/t3_hashes.txt`.
- [ ] **Step 7: Controller review and commit.** Message: `S1 A3 Task 3: F5 ownership locks (share mode + byte lock)`,
  listing map rows 132–137, 231–233 and 309, with the Co-Authored-By line. Push and assert the HEAD SHA.

---

### Task 4: Trial identity and ACK reading (F6.1–F6.3, F6.5, F7.1, F7.5, F9; OQ-5, OQ-6, OQ-20, OQ-27)

**Files:**
- Create: `research/s1/s1_trial.py`
- Modify: `research/s1/s1_common.py`:
  - `AUDIT_ACK` text;
  - `audit_token` (trial_id first);
  - `run_token`/`acquire_token`/`score_token` delegate to `s1_trial.token`;
  - BUNDLE_CODE gains `s1_trial.py`.
- Modify: `research/s1/s1_collect.py:69-82` (write_plan: `require_no_open_trial`, `trial_id`). Remove the alias
  `ACQUIRE_ACK = c.ACQUIRE_ACK` (line 19); `AUDIT_ACK` stays.
- Modify: `research/s1/s1_run.py`:
  - `TRIAL_ID` (line 25) is removed;
  - artifacts record `plan["trial_id"]` at lines 456, 470, 531, 590, 629 and 933;
  - the aliases `RUN_ACK`/`SCORE_ACK` (lines 17–18) are removed.
- Create: `research/s1/s1_tests/test_s1_a3_trial.py`

**Interfaces:**
- Consumes: Task 1 `s1_journal` (`_ro`, `line_sha256`, `genesis`, `read_trial`, `first`, `trial_state`) and Task 2
  `trial_state`.
- Produces (`s1_trial`):
  - `ACK_KEY = ("codex", "claude", "experiments-prereg")`.
  - `ACK_FIELDS: dict[kind, tuple]`; `CHAIN`; `PRED`; `CLOSE_REASONS`.
  - `Refusal(SystemExit)`.
  - `Ack` (frozen): mailbox_id, created, sender, recipient, key, line, kind (None = malformed), fields; properties
    `official` and `sha`.
  - `parse_ack_line(line) -> (kind, fields)`, raising ValueError.
  - `acks_from(rows) -> list[Ack]`; `scan(mailbox=None) -> list[Ack]`.
  - `Trial`: trial_id, bundle, audit, acks, closed, problems, genesis; property `latest`.
  - `trials(acks) -> dict[str, Trial]`; `open_trial(mailbox=None) -> Trial`;
    `require_no_open_trial(mailbox=None) -> None`.
  - `check_journal(trial, rows, only=None) -> list[str]`; `state(trial, rows) -> str`;
    `closed_in(con, trial) -> bool`.
  - `artifact_fields(kind, out: Path) -> dict`; `token(kind, root, *, mailbox=None, **given) -> str`.
  - `verify_ack(trial, rows, kind, ack_id, expected: dict) -> Ack`; `ack_record(ack) -> dict` (keys ack_id,
    created_utc).
  - `close_evidence(kind, *, score_record=None, rows=None, withdrawal=None) -> str`.
- Produces (`s1_collect`): `write_plan(root, planned_start, opening_close, symbols, first_trade_date, *, mailbox=None)`.
  plan.json gains `"trial_id": <uuid4>`.

- [ ] **Step 1: Interface stub.** Create `s1_trial.py` with the final names. Its behaviour is permissive: any AUDIT
  line opens a trial, there are no chain or CLOSE checks, and `require_no_open_trial` is a no-op. Change write_plan to
  add `"trial_id": "S1"`, which is not a uuid4 and so a behavioural fault.

```python
"""S1 external trial identity - Task 4 INTERFACE STUB (permissive; replaced in Step 4)."""
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import s1_common as c
import s1_journal as j

ACK_KEY = ("codex", "claude", "experiments-prereg")
ACK_FIELDS = {
    "S1-AUDIT-ACK": ("trial_id", "bundle_sha256", "collector_sha256", "plan_sha256", "start"),
    "S1-OPENING-ACK": ("trial_id", "bundle_sha256", "prev", "plan_sha256", "audit_manifest_sha256", "opening_slot",
                       "opening_seal_sha256", "opening_receipt_sha256", "journal_seq", "journal_head_sha256",
                       "evidence_manifest_sha256"),
    "S1-RUN-ACK": ("trial_id", "bundle_sha256", "prev", "runner_sha256", "plan_sha256", "audit_manifest_sha256",
                   "attest_start_sha256", "opening_seal_sha256", "opening_books_sha256", "start", "journal_seq",
                   "journal_head_sha256"),
    "S1-PREREG-ACK": ("trial_id", "bundle_sha256", "prev", "prereg_sha256", "journal_seq", "journal_head_sha256"),
    "S1-ACQUIRE-ACK": ("trial_id", "bundle_sha256", "prev", "collector_sha256", "final_plan_sha256", "prereg_sha256",
                       "attest_stop_sha256", "journal_seq", "journal_head_sha256", "stop_line_sha256"),
    "S1-SCORE-ACK": ("trial_id", "bundle_sha256", "prev", "runner_sha256", "final_manifest_sha256",
                     "stop_attest_sha256", "final_snapshot_sha256", "stop_sha256", "journal_seq",
                     "journal_head_sha256", "stop_line_sha256"),
    "S1-CLOSE-ACK": ("trial_id", "bundle_sha256", "prev", "reason", "evidence_sha256"),
}
CHAIN = ("S1-AUDIT-ACK", "S1-OPENING-ACK", "S1-RUN-ACK", "S1-PREREG-ACK", "S1-ACQUIRE-ACK", "S1-SCORE-ACK")
PRED = dict(zip(CHAIN[1:], CHAIN[:-1]))
CLOSE_REASONS = ("SCORED", "ABORTED", "LOST", "OPENING-UNACKED", "INVALID", "WITHDRAWN",
                 "BLOCKED")                                       # BLOCKED: E3.4, pending Codex acceptance of E3


class Refusal(SystemExit):
    pass


@dataclass(frozen=True)
class Ack:
    mailbox_id: str
    created: float
    sender: str
    recipient: str
    key: str
    line: str
    kind: object
    fields: dict

    @property
    def official(self) -> bool:
        return (self.sender, self.recipient, self.key) == ACK_KEY

    @property
    def sha(self) -> str:
        return j.line_sha256(self.line)


@dataclass
class Trial:
    trial_id: str
    bundle: str
    audit: Ack
    acks: dict
    closed: object
    problems: list
    genesis: str

    @property
    def latest(self) -> Ack:
        return self.audit


def parse_ack_line(line):
    kind, _, rest = line.partition(" ")
    return kind, dict(p.split("=", 1) for p in rest.split(" ") if "=" in p)


def acks_from(rows) -> list:
    out = []
    for mid, s, r, k, body, created in rows:
        for ln in (body or "").split("\n"):
            if ln.startswith("S1-") and "-ACK " in ln:
                kind, f = parse_ack_line(ln.rstrip("\r"))
                out.append(Ack(mid, created, s, r, k, ln.rstrip("\r"), kind, f))
    return out


def scan(mailbox=None) -> list:
    con = j._ro(mailbox)
    try:
        return acks_from(con.execute("SELECT id, sender, recipient, request_key, body, created FROM messages"))
    finally:
        con.close()


def attributed_trial(line):
    return None


def trials(acks, root=None) -> dict:
    out = {}
    for a in acks:
        if a.kind == "S1-AUDIT-ACK":
            out[a.fields.get("trial_id")] = Trial(a.fields.get("trial_id"), a.fields.get("bundle_sha256"), a,
                                                  {x.kind: x for x in acks if x.kind != "S1-AUDIT-ACK"}, None, [],
                                                  j.genesis(a.line))
    return out


def open_trial(mailbox=None, root=None) -> Trial:
    ts = list(trials(scan(mailbox)).values())
    if not ts:
        raise Refusal("zero open trials")
    return ts[0]


def require_no_open_trial(mailbox=None, root=None) -> None:
    return None


def check_journal(trial, rows, only=None) -> list:
    return []


def state(trial, rows) -> str:
    return j.trial_state(rows)


def closed_in(con, trial, root=None) -> bool:
    return False


def artifact_fields(kind, out) -> dict:
    return {}


def token(kind, root, *, mailbox=None, **given) -> str:
    return c.audit_token(Path(root) / "s1_out")


def verify_ack(trial, rows, kind, ack_id, expected) -> Ack:
    return trial.acks.get(kind) or trial.audit


def ack_record(ack) -> dict:
    return {"ack_id": ack.mailbox_id, "created_utc": datetime.fromtimestamp(ack.created, tz=timezone.utc).isoformat()}


def close_evidence(kind, *, score_record=None, rows=None, withdrawal=None, blocked_record=None) -> str:
    return "0" * 64
```

- [ ] **Step 2: Write the failing tests.** Create `research/s1/s1_tests/test_s1_a3_trial.py`. Its mailbox helper
  writes tmp rows only.

```python
"""Addendum 3 rev 5 F6.1-F6.3, F6.5, F7.1, F7.5, F9 (trial identity, ACK grammar and chain, CLOSE, write_plan).
Behavioural RED against the Task 4 stub (s1_evidence/a3/t4_red.txt). tmp_path mailboxes only (never the real one);
no network, live DB or scheduler; ACK lines are synthetic test data."""
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import s1_collect as k
import s1_common as c
import s1_journal as j
import s1_trial as t
from conftest import s1_mailbox_init

UTC = timezone.utc
START = datetime(2026, 11, 16, 14, 30, tzinfo=UTC)
T0 = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
BUNDLE = "b" * 64
H = "1" * 64


def post(mb, mid, line, at, sender="codex", recipient="claude", key="experiments-prereg"):
    con = sqlite3.connect(mb)
    con.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,NULL)", (mid, sender, recipient, key, line, at.timestamp()))
    con.commit()
    con.close()


def line(kind, **f):
    return " ".join([kind] + [f"{n}={f[n]}" for n in t.ACK_FIELDS[kind]])


def audit(tid, bundle=BUNDLE):
    return line("S1-AUDIT-ACK", trial_id=tid, bundle_sha256=bundle, collector_sha256=H, plan_sha256=H,
                start=START.isoformat())


def opening(tid, prev, seq=1, head=H, bundle=BUNDLE):
    return line("S1-OPENING-ACK", trial_id=tid, bundle_sha256=bundle, prev=prev, plan_sha256=H,
                audit_manifest_sha256=H, opening_slot="slot/20261113T214500Z", opening_seal_sha256=H,
                opening_receipt_sha256=H, journal_seq=seq, journal_head_sha256=head, evidence_manifest_sha256=H)


def close(tid, prev, bundle=BUNDLE, reason="WITHDRAWN"):
    return line("S1-CLOSE-ACK", trial_id=tid, bundle_sha256=bundle, prev=prev, reason=reason, evidence_sha256=H)


def tid():
    return str(uuid.uuid4())


def test_write_plan_records_a_uuid4_trial_id_and_makes_no_request_callback_or_journal_write(tmp_path):
    with _clock(T0):
        p = k.write_plan(tmp_path, START, "2026-11-13", ["A"], "2026-03-17")
    plan = json.loads(p.read_text(encoding="utf-8"))
    assert uuid.UUID(plan["trial_id"]).version == 4
    assert j.read_all(tmp_path / "mailbox.sqlite3") == []


def test_write_plan_refuses_with_an_open_trial_or_an_unreadable_mailbox(tmp_path, monkeypatch):
    mb = tmp_path / "mailbox.sqlite3"
    post(mb, "a1", audit(tid()), T0)
    with _clock(T0), pytest.raises(SystemExit, match="open"):
        k.write_plan(tmp_path, START, "2026-11-13", ["A"], "2026-03-17")
    monkeypatch.setattr(c, "MAILBOX", tmp_path / "gone.sqlite3")
    with _clock(T0), pytest.raises(SystemExit, match="unreadable"):
        k.write_plan(tmp_path, START, "2026-11-13", ["A"], "2026-03-17")
    assert not (tmp_path / "s1_out" / "plan.json").exists()


@pytest.mark.parametrize("kind", sorted(t.ACK_FIELDS))
def test_ack_lines_have_exactly_the_listed_fields_in_order(kind):
    vals = {n: (str(uuid.uuid4()) if n == "trial_id" else "1" if n == "journal_seq" else START.isoformat()
                if n == "start" else "slot/20261113T214500Z" if n == "opening_slot" else "SCORED" if n == "reason"
                else "m-1" if n == "prev" else H) for n in t.ACK_FIELDS[kind]}
    got_kind, got = t.parse_ack_line(line(kind, **vals))
    assert got_kind == kind and list(got) == list(t.ACK_FIELDS[kind])


@pytest.mark.parametrize("dev", ["extra", "missing", "reordered", "bad-hex", "bad-uuid"])
def test_ack_line_deviation_refuses(dev):
    good = audit(tid())
    bad = {"extra": good + " note=x", "missing": good.rsplit(" ", 1)[0],
           "reordered": good.replace(f"collector_sha256={H} plan_sha256={H}", f"plan_sha256={H} collector_sha256={H}"),
           "bad-hex": good.replace(f"bundle_sha256={BUNDLE}", "bundle_sha256=XYZ"),
           "bad-uuid": good.replace(good.split(" ")[1], "trial_id=S1")}[dev]
    with pytest.raises(ValueError):
        t.parse_ack_line(bad)


@pytest.mark.parametrize("case", ["one", "zero", "two", "outage"])
def test_open_trial_cases(tmp_path, monkeypatch, case):
    mb = s1_mailbox_init(tmp_path)
    a = tid()
    if case in ("one", "two"):
        post(mb, "a1", audit(a), T0)
    if case == "two":
        post(mb, "a2", audit(tid()), T0 + timedelta(minutes=1))
    if case == "outage":
        mb = tmp_path / "missing.sqlite3"
    if case == "one":
        tr = t.open_trial(mb)
        assert (tr.trial_id, tr.bundle, tr.genesis) == (a, BUNDLE, j.line_sha256(audit(a)))
        return
    with pytest.raises(t.Refusal, match={"zero": "zero open", "two": "2 open", "outage": "unreadable"}[case]):
        t.open_trial(mb)


def test_duplicate_trial_id_refuses_every_trial_with_that_id(tmp_path):
    mb = s1_mailbox_init(tmp_path)
    a = tid()
    post(mb, "a1", audit(a), T0)
    post(mb, "a2", audit(a).replace(f"plan_sha256={H}", "plan_sha256=" + "2" * 64), T0 + timedelta(minutes=1))
    with pytest.raises(t.Refusal, match="2 AUDIT-ACKs"):
        t.open_trial(mb)


@pytest.mark.parametrize("case", ["distinct", "identical"])
def test_second_ack_of_a_kind_refuses_even_byte_identical(tmp_path, case):
    mb = s1_mailbox_init(tmp_path)
    a = tid()
    post(mb, "a1", audit(a), T0)
    post(mb, "o1", opening(a, "a1"), T0 + timedelta(hours=1))
    second = opening(a, "a1") if case == "identical" else opening(a, "a1", head="3" * 64)
    post(mb, "o2", second, T0 + timedelta(hours=2))
    with pytest.raises(t.Refusal, match="2 S1-OPENING-ACK"):
        t.open_trial(mb)


@pytest.mark.parametrize("case", ["ok", "prev-not-predecessor", "wrong-bundle", "no-predecessor"])
def test_ack_chain_prev_is_the_predecessor_mailbox_id(tmp_path, case):
    mb = s1_mailbox_init(tmp_path)
    a = tid()
    post(mb, "a1", audit(a), T0)
    if case != "no-predecessor":
        post(mb, "o1", opening(a, "a1", bundle="9" * 64 if case == "wrong-bundle" else BUNDLE), T0 + timedelta(hours=1))
    run = line("S1-RUN-ACK", trial_id=a, bundle_sha256=BUNDLE, prev="a1" if case == "prev-not-predecessor" else "o1",
               runner_sha256=H, plan_sha256=H, audit_manifest_sha256=H, attest_start_sha256=H, opening_seal_sha256=H,
               opening_books_sha256=H, start=START.isoformat(), journal_seq=1, journal_head_sha256=H)
    post(mb, "r1", run, T0 + timedelta(hours=2))
    if case == "ok":
        assert t.open_trial(mb).acks["S1-RUN-ACK"].mailbox_id == "r1"
    else:
        with pytest.raises(t.Refusal):
            t.open_trial(mb)


@pytest.mark.parametrize("case", ["equal-pred", "before-row"])
def test_ack_created_not_after_its_predecessor_or_referenced_row_refuses(tmp_path, case):
    mb = s1_mailbox_init(tmp_path)
    a = tid()
    post(mb, "a1", audit(a), T0)
    tr = t.open_trial(mb)
    row = j.append(a, tr.genesis, j.Request("STAGE-INTENT", "stage/audit", "1" * 32, "2" * 32, detail=H),
                   lambda rows, con: j.Context(stage_gate=lambda r_, g: None), mailbox=mb,
                   clock=lambda: T0 + timedelta(hours=2)).row
    when = T0 if case == "equal-pred" else T0 + timedelta(hours=1)
    post(mb, "o1", opening(a, "a1", seq=1, head=row.sha), when)
    tr = t.open_trial(mb) if case == "before-row" else None
    if case == "equal-pred":
        with pytest.raises(t.Refusal, match="not after"):
            t.open_trial(mb)
    else:
        assert any("not after" in p for p in t.check_journal(tr, j.read_trial(a, tr.genesis, mb)))


@pytest.mark.parametrize("case", ["ok", "wrong-head", "seq-beyond", "forked"])
def test_journal_seq_and_head_must_be_extended_without_fork(tmp_path, case):
    mb = s1_mailbox_init(tmp_path)
    a = tid()
    post(mb, "a1", audit(a), T0)
    tr = t.open_trial(mb)
    row = j.append(a, tr.genesis, j.Request("STAGE-INTENT", "stage/audit", "1" * 32, "2" * 32, detail=H),
                   lambda rows, con: j.Context(stage_gate=lambda r_, g: None), mailbox=mb, clock=lambda: T0).row
    head = {"ok": row.sha, "wrong-head": "4" * 64, "seq-beyond": row.sha, "forked": row.sha}[case]
    post(mb, "o1", opening(a, "a1", seq=2 if case == "seq-beyond" else 1, head=head), T0 + timedelta(hours=1))
    tr = t.open_trial(mb)
    rows = j.read_trial(a, tr.genesis, mb)
    if case == "forked":
        rows = [j.Row(**dict(j.parse_line(rows[0].line), detail="5" * 64), line=rows[0].line.replace(H, "5" * 64),
                      mailbox_id="x", created=rows[0].created)]
    probs = t.check_journal(tr, rows)
    assert (probs == []) == (case == "ok"), probs


@pytest.mark.parametrize("case", ["valid", "prev-not-latest", "before-audit", "wrong-bundle", "duplicate"])
def test_close_refused_cases(tmp_path, case):
    """Row 158 (E4.4): official CLOSE candidates only; wrong-role/key lines are no candidates (rows 275-277)."""
    mb = s1_mailbox_init(tmp_path)
    a = tid()
    post(mb, "a1", audit(a), T0)
    post(mb, "o1", opening(a, "a1"), T0 + timedelta(hours=1))
    at = T0 - timedelta(hours=1) if case == "before-audit" else T0 + timedelta(hours=2)
    post(mb, "c1", close(a, "a1" if case == "prev-not-latest" else "o1",
                         bundle="9" * 64 if case == "wrong-bundle" else BUNDLE), at)
    if case == "duplicate":
        post(mb, "c2", close(a, "o1"), T0 + timedelta(hours=3))
    if case == "valid":
        with pytest.raises(t.Refusal, match="zero open"):
            t.open_trial(mb)
    else:
        with pytest.raises(t.Refusal, match="CLOSE"):
            t.open_trial(mb)


def test_closed_is_layered_on_the_journal_state(tmp_path):
    mb = s1_mailbox_init(tmp_path)
    a = tid()
    post(mb, "a1", audit(a), T0)
    tr = t.open_trial(mb)
    assert t.state(tr, []) == "ACTIVE"
    post(mb, "c1", close(a, "a1"), T0 + timedelta(hours=1))
    closed = t.trials(t.scan(mb))[a]
    assert closed.closed is not None and t.state(closed, []) == "CLOSED"


def test_other_trials_acks_and_rows_never_count_even_with_the_same_bundle(tmp_path):
    mb = s1_mailbox_init(tmp_path)
    old, new = tid(), tid()
    post(mb, "a0", audit(old), T0 - timedelta(days=9))
    post(mb, "o0", opening(old, "a0"), T0 - timedelta(days=8))
    post(mb, "c0", close(old, "o0"), T0 - timedelta(days=7))
    post(mb, "a1", audit(new), T0)
    tr = t.open_trial(mb)
    assert tr.trial_id == new and "S1-OPENING-ACK" not in tr.acks
    with pytest.raises(t.Refusal, match="not the trial's"):
        t.verify_ack(tr, [], "S1-OPENING-ACK", "o0", {})


@pytest.mark.parametrize("kind", ["SCORED", "INVALID", "WITHDRAWN"])
def test_close_evidence_hashes(kind):
    rows = [j.Row(trial_id="x", seq=1, prev="0" * 64, kind="TRIAL-INVALID", subject="reason/LOST", detail=H,
                  op="1" * 32, actor="2" * 32, at="2026-11-02T12:00:00.000000+00:00", line="LINE-1", mailbox_id="m",
                  created=1.0)]
    got = t.close_evidence(kind, score_record=b"{score}", rows=rows, withdrawal="operator withdrew")
    want = {"SCORED": c.sha256_bytes(b"{score}"), "INVALID": j.line_sha256("LINE-1"),
            "WITHDRAWN": c.sha256_bytes("operator withdrew".encode("utf-8"))}[kind]
    assert got == want


# ---------------------------------------------------------------- E4 (rows 275-278, 330)
@pytest.mark.parametrize("case", ["wrong-role-close", "wrong-key-close", "peer-draft", "indented-line", "quoted-line",
                                  "historical-other-trial"])
def test_non_official_lines_are_never_candidates(tmp_path, case):
    mb = s1_mailbox_init(tmp_path)
    a = tid()
    post(mb, "a1", audit(a), T0)
    later = T0 + timedelta(hours=1)
    if case == "wrong-role-close":
        post(mb, "x1", close(a, "a1"), later, sender="claude")
    elif case == "wrong-key-close":
        post(mb, "x1", close(a, "a1"), later, key="other-key")
    elif case == "peer-draft":                      # an arbitrary draft from a peer, malformed and well-formed lines
        post(mb, "x1", "draft:\n" + close(a, "a1") + "\nS1-OPENING-ACK trial_id=" + a + " junk", later,
             sender="claude", recipient="codex", key="experiments-s1-review")
    elif case == "indented-line":                   # the official channel, but not at line start
        post(mb, "x1", "  " + close(a, "a1"), later)
    elif case == "quoted-line":
        post(mb, "x1", "> " + close(a, "a1"), later)
    else:                                           # another, closed trial's history (official, well formed)
        old = tid()
        post(mb, "a0", audit(old), T0 - timedelta(days=9))
        post(mb, "c0", close(old, "a0"), T0 - timedelta(days=8))
    tr = t.open_trial(mb)                           # no refusal, no closure
    assert tr.trial_id == a and tr.closed is None and tr.problems == []


@pytest.mark.parametrize("case", ["attributable", "unattributable"])
def test_malformed_candidate_refuses_its_own_trial_or_all(tmp_path, case):             # row 278 (E4.3)
    mb = s1_mailbox_init(tmp_path)
    a, b = tid(), tid()
    post(mb, "a1", audit(a), T0)
    post(mb, "b1", audit(b), T0 + timedelta(minutes=1))
    post(mb, "c1", close(a, "a1"), T0 + timedelta(minutes=2))            # trial a closed; b is the open trial
    bad = f"S1-OPENING-ACK trial_id={b} broken" if case == "attributable" else "S1-OPENING-ACK broken"
    post(mb, "m1", bad, T0 + timedelta(minutes=3))
    with pytest.raises(t.Refusal, match="E4.3"):
        t.open_trial(mb)
    if case == "attributable":                      # it names b; a different trial would be unaffected
        trs = t.trials(t.scan(mb))
        assert trs[b].problems and trs[a].problems == []


def test_attribution_grammar_is_the_e43_grammar():                                    # row 278 (E4.3 r1 grammar)
    u = "3f2b8c1e-5d4a-4b6c-9e7f-0a1b2c3d4e5f"
    assert t.attributed_trial(f"S1-OPENING-ACK trial_id={u} junk") == u
    assert t.attributed_trial(f"S1-OPENING-ACK\ttrial_id={u}\tjunk") == u            # whitespace-separated
    assert t.attributed_trial(f"S1-OPENING-ACK trial_id={u.upper()} junk") is None   # not canonical lowercase
    assert t.attributed_trial(f"S1-OPENING-ACK junk trial_id={u}") is None           # not the second token
    assert t.attributed_trial(f"S1-OPENING-ACK trial_id={u}x") is None               # not exactly a uuid4
    assert t.attributed_trial("S1-OPENING-ACK trial_id=3f2b8c1e-5d4a-1b6c-9e7f-0a1b2c3d4e5f") is None   # not v4


@pytest.mark.parametrize("case", ["ok", "wrong"])
def test_close_blocked_evidence_hash(tmp_path, monkeypatch, case):                     # row 273, Task 4 unit part
    """E3.4 r1 (pending E3): h = sha256(canonical({trial_id, reasons})), never the blocked.json bytes. The
    recomputation itself is Task 10's (s1_run.blocked_close_evidence); here it is stubbed to a known record, and the
    end-to-end form is test_s1_a3_prestart.py::test_close_blocked_evidence_hash_end_to_end."""
    import s1_run
    mb = s1_mailbox_init(tmp_path)
    a = tid()
    rec = {"trial_id": a, "reasons": ["coverage"]}
    h = t.close_evidence("BLOCKED", blocked_record=rec)
    assert h == c.sha256_bytes(c.canonical(rec))
    monkeypatch.setattr(s1_run, "blocked_close_evidence", lambda out: h, raising=False)
    post(mb, "a1", audit(a), T0)
    post(mb, "c1", line("S1-CLOSE-ACK", trial_id=a, bundle_sha256=BUNDLE, prev="a1", reason="BLOCKED",
                        evidence_sha256=h if case == "ok" else "8" * 64), T0 + timedelta(hours=1))
    if case == "ok":
        with pytest.raises(t.Refusal, match="zero open"):
            t.open_trial(mb, root=tmp_path)
    else:
        with pytest.raises(t.Refusal, match="BLOCKED evidence"):
            t.open_trial(mb, root=tmp_path)


def test_opening_receipt_sha256_is_the_raw_file_hash(tmp_path, monkeypatch):           # row 318 (OQ-30)
    out = tmp_path / "s1_out"
    out.mkdir()
    rec = {"fingerprint": {"x": 1}, "receipt_sha256": "0" * 64}
    (out / "opening_receipt.json").write_bytes(c.canonical(rec))                       # canonical -> bytes
    (out / "plan.json").write_bytes(c.canonical({"trial_id": tid(), "planned_start": "2026-11-09T14:30:00+00:00",
                                                 "opening_close": "2026-11-06"}))
    monkeypatch.setattr(c, "opening_seal_path", lambda o, p: o / "absent-seal.json")
    got = t.artifact_fields("S1-OPENING-ACK", out)["opening_receipt_sha256"]
    assert got == c.sha256_file(out / "opening_receipt.json")
    assert got != c.receipt_sha256(rec["fingerprint"])


class _clock:
    def __init__(self, at):
        self.at = at

    def __enter__(self):
        self.old = c.now_utc
        c.now_utc = lambda: self.at

    def __exit__(self, *exc):
        c.now_utc = self.old
```

- [ ] **Step 3: Behavioural RED.** Run into `a3/t4_red.txt`.
  - Expected: a non-uuid trial_id; write_plan does not refuse; deviations parse; zero/two/outage do not refuse the
    way asserted; duplicates and broken chains pass; CLOSE is ignored; evidence hashes are `"0" * 64`.
  - E4 rows: `test_non_official_lines_are_never_candidates[wrong-role-close,wrong-key-close,peer-draft]` fail on
    the stub, which counts any `S1-…-ACK` line in any message. `[indented-line,quoted-line,historical-other-trial]`
    pass on the stub. Label them `ctrl`; their meaning comes from the wrong-channel cases and from rows 276–277
    against the Step 4 code.
  - `test_malformed_candidate…` and `test_close_blocked_evidence_hash[*]` fail (no refusal). Row 318 fails because
    the stub's `artifact_fields` returns {}.
  - The `ok`/`one` cases pass. Label them `ctrl`.

- [ ] **Step 4: Implement `research/s1/s1_trial.py`.** Replace the stub. Constants as in the stub; functions:

```python
"""S1 external trial identity (Addendum 3 rev 5 F6, F7). The open trial, its ACK chain and its CLOSE are found from
the coordination mailbox only (opened mode=ro, F6.3); the trial gate (Task 5) is built on these readers. Codex issues
ACKs; S1 code only reads them. Token texts: ACK_FIELDS (exact fields in order, F6.1, OQ-5)."""
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import s1_common as c
import s1_journal as j

# (ACK_KEY, ACK_FIELDS, CHAIN, PRED, CLOSE_REASONS exactly as in the Step 1 stub)
_UUID4 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
STRICT_HEX = ("bundle_sha256", "journal_head_sha256", "stop_line_sha256", "evidence_sha256",
              "evidence_manifest_sha256", "plan_sha256")          # never "absent"


class Refusal(SystemExit):
    """A trial-bound command refuses (identity, chain, CLOSE, outage): zero callbacks, no row."""


# (Ack, Trial dataclasses as in the stub, with Trial.latest:)
#     @property
#     def latest(self) -> Ack:
#         present = [self.audit] + [self.acks[k_] for k_ in CHAIN[1:] if k_ in self.acks]
#         return present[-1]


def parse_ack_line(line: str) -> tuple:
    """F6.1: one standalone token line with exactly the listed fields, in order (OQ-5). ValueError otherwise."""
    kind, sep, rest = line.partition(" ")
    if kind not in ACK_FIELDS or not sep:
        raise ValueError(f"not an S1 ACK kind: {kind!r}")
    parts = rest.split(" ")
    if any("=" not in p or p.endswith("=") or p.startswith("=") for p in parts):
        raise ValueError(f"{kind}: malformed field")
    names = [p.split("=", 1)[0] for p in parts]
    if names != list(ACK_FIELDS[kind]):
        raise ValueError(f"{kind}: fields {names} are not exactly {list(ACK_FIELDS[kind])} in order")
    f = dict(p.split("=", 1) for p in parts)
    if not _UUID4.fullmatch(f["trial_id"]):
        raise ValueError(f"{kind}: trial_id is not a uuid4")
    for n, v in f.items():
        if n.endswith("_sha256") and not (_HEX64.fullmatch(v) or (v == c.ABSENT and n not in STRICT_HEX)):
            raise ValueError(f"{kind}: {n} is not a 64-hex sha256")
    if "journal_seq" in f and not re.fullmatch(r"[1-9][0-9]*", f["journal_seq"]):
        raise ValueError(f"{kind}: journal_seq is not a positive integer")
    if "start" in f:
        try:
            c.aware(f["start"])
        except ValueError:
            raise ValueError(f"{kind}: start is not an instant") from None
    if "reason" in f and f["reason"] not in CLOSE_REASONS:
        raise ValueError(f"{kind}: reason {f['reason']!r} is not a CLOSE reason")
    if "opening_slot" in f and not re.fullmatch(r"slot/\d{8}T\d{6}Z", f["opening_slot"]):
        raise ValueError(f"{kind}: opening_slot is not a slot subject")
    return kind, f


_ATTRIB = re.compile(r"trial_id=([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})")


def attributed_trial(line: str):
    """E4.3 (Erratum 1 r1) attribution grammar: a trial_id can be parsed exactly when the line's second
    whitespace-separated token is `trial_id=<canonical lowercase uuid4>`. Otherwise None (unattributable)."""
    parts = line.split()
    m = _ATTRIB.fullmatch(parts[1]) if len(parts) > 1 else None
    return m.group(1) if m else None


def acks_from(rows) -> list:
    """E4.1/E4.2: candidates come ONLY from official messages (codex->claude experiments-prereg), every kind CLOSE
    included, and only from lines whose first character starts `S1-` and whose first token ends `-ACK` (no
    stripping: an indented or quoted line is no candidate). Lines in any other message are ignored entirely. A
    malformed candidate is kept with kind None and its attributed trial_id (E4.3)."""
    out = []
    for mid, sender, recipient, key, body, created in rows:
        if (sender, recipient, key) != ACK_KEY:
            continue                                                                   # E4.2: never a candidate
        for ln in (body or "").split("\n"):
            ln = ln.rstrip("\r")
            head = ln.split(" ", 1)[0]
            if not (head.startswith("S1-") and head.endswith("-ACK")):
                continue
            try:
                kind, f = parse_ack_line(ln)
            except ValueError as e:
                kind, f = None, {"_malformed": str(e), "trial_id": attributed_trial(ln)}
            out.append(Ack(mid, created, sender, recipient, key, ln, kind, f))
    return out


_SCAN = "SELECT id, sender, recipient, request_key, body, created FROM messages"


def scan(mailbox=None) -> list:
    con = j._ro(mailbox)                    # mode=ro; raises sqlite3.Error when unreadable
    try:
        return acks_from(con.execute(_SCAN).fetchall())
    finally:
        con.close()


def _chain_problems(kind: str, a: Ack, audit: Ack, chosen: dict) -> list:
    pk = PRED[kind]
    pred = audit if pk == "S1-AUDIT-ACK" else chosen.get(pk)
    if pred is None:
        return [f"{kind} {a.mailbox_id}: no {pk} predecessor (F7.1)"]
    probs = []
    if a.fields["prev"] != pred.mailbox_id:
        probs.append(f"{kind} {a.mailbox_id}: prev {a.fields['prev']!r} is not the {pk} {pred.mailbox_id!r} (F7.1)")
    if not a.created > pred.created:
        probs.append(f"{kind} {a.mailbox_id}: created not after its predecessor (F6.1)")
    if a.fields["bundle_sha256"] != audit.fields["bundle_sha256"]:
        probs.append(f"{kind} {a.mailbox_id}: bundle chain broken (F7.1)")
    return probs


def _blocked_evidence_problem(a: Ack, root):
    """E3.4 (Erratum 1 r1; pending Codex acceptance of E3): a BLOCKED CLOSE's evidence_sha256 must be
    h = sha256(c.canonical({"trial_id", "reasons"})), the deterministic recomputation from committed inputs - not the
    blocked.json bytes. Task 4 ships the fail-closed form (refused: the recomputation arrives in Task 10, which
    replaces this body with `_blocked_h(root) != evidence_sha256`). Without a root it is refused."""
    if root is None:
        return "BLOCKED evidence cannot be checked without the trial root"
    try:
        import s1_run                                    # late import; blocked_close_evidence is Task 10's
        want = s1_run.blocked_close_evidence(Path(root) / "s1_out")
    except (AttributeError, OSError, ValueError, KeyError, SystemExit) as e:
        return f"BLOCKED evidence not recomputable ({type(e).__name__})"
    if want != a.fields["evidence_sha256"]:
        return "BLOCKED evidence_sha256 is not sha256(canonical({trial_id, reasons})) of the recomputation (E3.4)"
    return None


def _close(closes: list, audit: Ack, chosen: dict, root=None) -> tuple:
    """F7.5 with E4: (the valid CLOSE or None, problems). Every CLOSE here is an official candidate (E4.1); any that
    is not valid refuses the trial's commands."""
    if not closes:
        return None, []
    if len(closes) > 1:
        return None, [f"{len(closes)} CLOSE-ACKs for trial {audit.fields['trial_id']} (duplicate): refuse"]
    a = closes[0]
    present = [audit] + [chosen[k_] for k_ in CHAIN[1:] if k_ in chosen]
    latest = present[-1]
    why = []
    if a.fields["reason"] == "BLOCKED":
        bp = _blocked_evidence_problem(a, root)
        if bp:
            why.append(bp)
    if a.created <= audit.created:
        why.append("before the AUDIT-ACK")
    if a.fields["prev"] != latest.mailbox_id:
        why.append(f"prev is not the latest ACK {latest.mailbox_id!r}")
    elif a.created <= latest.created:
        why.append("not after the latest ACK")
    if a.fields["bundle_sha256"] != audit.fields["bundle_sha256"]:
        why.append("bundle differs")
    if why:
        return None, [f"CLOSE-ACK {a.mailbox_id} refused ({'; '.join(why)}): the trial stays open and commands refuse"]
    return a, []


def trials(acks, root=None) -> dict:
    """Per trial: the ACK chain, CLOSE and problems. A malformed candidate (E4.3) refuses the trial whose trial_id it
    names; an unattributable one is handled by open_trial (it refuses every trial-bound command)."""
    audits = {}
    for a in acks:
        if a.official and a.kind == "S1-AUDIT-ACK":
            audits.setdefault(a.fields["trial_id"], []).append(a)
    out = {}
    for tid, xs in audits.items():
        audit = min(xs, key=lambda a: a.created)
        probs = ([f"trial_id {tid} is on {len(xs)} AUDIT-ACKs (F6.2): every trial with that id refuses"]
                 if len(xs) > 1 else [])
        by_kind = {}
        for a in acks:
            if a.official and a.kind in CHAIN[1:] and a.fields.get("trial_id") == tid:
                by_kind.setdefault(a.kind, []).append(a)
        for kind, ys in by_kind.items():
            if len(ys) > 1:
                probs.append(f"{len(ys)} {kind} for trial {tid} (F7.1; byte-identical included): escalate")
        chosen = {kind: min(ys, key=lambda a: a.created) for kind, ys in by_kind.items()}
        for kind, a in chosen.items():
            probs += _chain_problems(kind, a, audit, chosen)
        closed, cprobs = _close([a for a in acks if a.kind == "S1-CLOSE-ACK" and a.fields.get("trial_id") == tid],
                                audit, chosen, root)
        probs += [f"malformed official ACK line in {a.mailbox_id} names this trial (E4.3): refuse and escalate"
                  for a in acks if a.kind is None and a.fields.get("trial_id") == tid]
        out[tid] = Trial(tid, audit.fields["bundle_sha256"], audit, chosen, closed, probs + cprobs,
                         j.genesis(audit.line))
    return out


def open_trial(mailbox=None, root=None) -> Trial:
    """F6.3: exactly one open trial (an AUDIT-ACK with no valid CLOSE-ACK), from the mailbox; `root` is used only to
    check a BLOCKED CLOSE's evidence (E3.4)."""
    try:
        acks = scan(mailbox)
    except sqlite3.Error as e:
        raise Refusal(f"mailbox unreadable ({type(e).__name__}): outage refusal (F6.3)") from None
    bad = [a.mailbox_id for a in acks if a.kind is None and a.fields.get("trial_id") is None]
    if bad:
        raise Refusal(f"unattributable malformed official ACK line(s) in {bad[:3]}: every trial-bound command "
                      f"refuses (E4.3): escalate")
    open_ = [x for x in trials(acks, root).values() if x.closed is None]
    if not open_:
        raise Refusal("zero open trials: trial-bound commands refuse (F6.3)")
    if len(open_) > 1:
        raise Refusal(f"{len(open_)} open trials: refuse and escalate (F6.3)")
    tr = open_[0]
    if tr.problems:
        raise Refusal(f"trial {tr.trial_id}: {tr.problems[:3]}: refuse and escalate")
    return tr


def require_no_open_trial(mailbox=None, root=None) -> None:
    """F9 / OQ-20: write_plan runs only without an open trial; an unreadable mailbox refuses (fail closed)."""
    try:
        acks = [a for a in scan(mailbox) if a.kind is not None]
    except sqlite3.Error as e:
        raise Refusal(f"write_plan refused: mailbox unreadable ({type(e).__name__}) (OQ-20)") from None
    open_ = [x for x in trials(acks, root).values() if x.closed is None]
    if open_:
        raise Refusal(f"write_plan refused: trial {open_[0].trial_id} is open (F9)")


def check_journal(trial: Trial, rows: list, only: Ack = None) -> list:
    """F7.1/F6.1: each ACK's journal_seq/head names a row of this trial's (verified) journal, the journal extends it
    without a fork, the ACK was created after that row, and stop_line_sha256 is the TRIAL-STOP line."""
    probs = []
    stop = j.first(rows, "TRIAL-STOP")
    for a in ([only] if only is not None else list(trial.acks.values())):
        if "journal_seq" in a.fields:
            n = int(a.fields["journal_seq"])
            if n > len(rows):
                probs.append(f"{a.kind} {a.mailbox_id}: journal_seq {n} beyond the journal ({len(rows)} rows)")
            elif rows[n - 1].sha != a.fields["journal_head_sha256"]:
                probs.append(f"{a.kind} {a.mailbox_id}: journal head at seq {n} differs (fork)")
            elif not a.created > rows[n - 1].created:
                probs.append(f"{a.kind} {a.mailbox_id}: created not after the journal row it references (F6.1)")
        if "stop_line_sha256" in a.fields and (stop is None or stop.sha != a.fields["stop_line_sha256"]):
            probs.append(f"{a.kind} {a.mailbox_id}: stop_line_sha256 is not the TRIAL-STOP line")
    return probs


def state(trial: Trial, rows: list) -> str:
    return "CLOSED" if trial.closed is not None else j.trial_state(rows)


def closed_in(con, trial: Trial, root=None) -> bool:
    """For a journal Context built inside the BEGIN IMMEDIATE transaction (same connection, same snapshot)."""
    tr = trials(acks_from(con.execute(_SCAN).fetchall()), root).get(trial.trial_id)
    return tr is None or tr.closed is not None


def artifact_fields(kind: str, out: Path) -> dict:
    """The ACK fields bound to current artifacts (the same files the old tokens bound)."""
    out = Path(out)
    plan = c.load_json(out / "plan.json")
    sha = c.sha_or_absent
    if kind == "S1-AUDIT-ACK":
        return {"collector_sha256": c.sha256_file(c.HERE / "s1_collect.py"), "plan_sha256": sha(out / "plan.json"),
                "start": plan["planned_start"]}
    if kind == "S1-OPENING-ACK":
        return {"plan_sha256": sha(out / "plan.json"), "audit_manifest_sha256": sha(out / "audit" / "manifest.json"),
                "opening_seal_sha256": sha(c.opening_seal_path(out, plan)),
                "opening_receipt_sha256": sha(out / "opening_receipt.json")}                            # OQ-30
    if kind == "S1-RUN-ACK":
        return {"runner_sha256": c.sha256_file(c.HERE / "s1_run.py"), "plan_sha256": sha(out / "plan.json"),
                "audit_manifest_sha256": sha(out / "audit" / "manifest.json"),
                "attest_start_sha256": sha(out / "attest_start.json"),
                "opening_seal_sha256": sha(c.opening_seal_path(out, plan)),
                "opening_books_sha256": sha(out / "opening_books.json"), "start": plan["planned_start"]}
    if kind == "S1-PREREG-ACK":
        return {"prereg_sha256": sha(out / "prereg.json")}
    if kind == "S1-ACQUIRE-ACK":
        return {"collector_sha256": c.sha256_file(c.HERE / "s1_collect.py"),
                "final_plan_sha256": sha(out / "final_plan.json"), "prereg_sha256": sha(out / "prereg.json"),
                "attest_stop_sha256": sha(out / "attest_stop.json")}
    if kind == "S1-SCORE-ACK":
        return {"runner_sha256": c.sha256_file(c.HERE / "s1_run.py"),
                "final_manifest_sha256": sha(out / "final" / "manifest.json"),
                "stop_attest_sha256": sha(out / "attest_stop.json"),
                "final_snapshot_sha256": sha(out / "final_snapshot" / "report.json"),
                "stop_sha256": sha(out / "stop.json")}
    return {}


def token(kind: str, root, *, mailbox=None, **given) -> str:
    """The exact ACK line for `kind` from the current artifacts and the open trial (tests; Codex's cross-check).
    `given` supplies issuer-only fields (evidence_manifest_sha256, opening_slot, reason, evidence_sha256) or
    overrides."""
    out = Path(root) / "s1_out"
    if kind == "S1-AUDIT-ACK":
        return c.audit_token(out)
    tr = open_trial(mailbox)
    rows = j.read_trial(tr.trial_id, tr.genesis, mailbox)
    vals = {"trial_id": tr.trial_id, "bundle_sha256": tr.bundle}
    vals["prev"] = (tr.latest if kind == "S1-CLOSE-ACK"
                    else tr.audit if PRED[kind] == "S1-AUDIT-ACK" else tr.acks[PRED[kind]]).mailbox_id
    if rows:
        vals.update(journal_seq=str(rows[-1].seq), journal_head_sha256=rows[-1].sha)
    stop = j.first(rows, "TRIAL-STOP")
    if stop is not None:
        vals["stop_line_sha256"] = stop.sha
    vals.update(artifact_fields(kind, out))
    vals.update({n: str(v) for n, v in given.items()})
    return " ".join([kind] + [f"{n}={vals[n]}" for n in ACK_FIELDS[kind]])


def verify_ack(trial: Trial, rows: list, kind: str, ack_id, expected: dict) -> Ack:
    """The trial's one `kind` ACK: `ack_id` (when given) must be it (F6.5); its artifact-bound fields equal
    `expected`; its journal binding holds (F7.1); it is not in the future."""
    a = trial.audit if kind == "S1-AUDIT-ACK" else trial.acks.get(kind)
    if a is None:
        raise Refusal(f"no {kind} for trial {trial.trial_id}")
    if ack_id is not None and a.mailbox_id != ack_id:
        raise Refusal(f"{ack_id!r} is not the trial's {kind} (F6.5: another trial's or a stray ACK never counts)")
    bad = sorted(n for n, v in expected.items() if a.fields.get(n) != v)
    if bad:
        raise Refusal(f"{kind} {a.mailbox_id}: {bad} differ from the current artifacts")
    probs = check_journal(trial, rows, only=a)
    if probs:
        raise Refusal(f"{kind} {a.mailbox_id}: {probs}")
    if datetime.fromtimestamp(a.created, tz=timezone.utc) > c.now_utc():
        raise Refusal(f"{kind} {a.mailbox_id}: ack is in the future")
    return a


def ack_record(a: Ack) -> dict:
    return {"ack_id": a.mailbox_id, "created_utc": datetime.fromtimestamp(a.created, tz=timezone.utc).isoformat()}


def close_evidence(kind: str, *, score_record: bytes = None, rows=None, withdrawal: str = None,
                   blocked_record: dict = None) -> str:
    """F7.5 evidence_sha256: SCORED = the score record bytes; INVALID = the first TRIAL-INVALID line; WITHDRAWN = the
    operator withdrawal message (UTF-8); BLOCKED = sha256(c.canonical({"trial_id", "reasons"})) (E3.4 r1). (Codex
    computes it; S1 offers the same function for the cross-check.)"""
    if kind == "SCORED":
        return c.sha256_bytes(score_record)
    if kind == "INVALID":
        return j.first(rows, "TRIAL-INVALID").sha
    if kind == "WITHDRAWN":
        return c.sha256_bytes(withdrawal.encode("utf-8"))
    if kind == "BLOCKED":                                         # E3.4 r1: h over {trial_id, reasons}, not file bytes
        return c.sha256_bytes(c.canonical({"trial_id": blocked_record["trial_id"],
                                           "reasons": blocked_record["reasons"]}))
    raise ValueError(f"no evidence rule for {kind!r}")
```

`s1_common.py` changes:
- `AUDIT_ACK = "S1-AUDIT-ACK trial_id={trial} bundle_sha256={bundle} collector_sha256={collector} plan_sha256={plan} start={start}"`.
- `audit_token(out)` formats it with `trial=plan["trial_id"]`.
- Delete the `RUN_ACK`, `ACQUIRE_ACK` and `SCORE_ACK` texts.
- `run_token(out, mailbox=None)`, `acquire_token(out, mailbox=None)` and `score_token(out, mailbox=None)` return
  `s1_trial.token("S1-RUN-ACK" | "S1-ACQUIRE-ACK" | "S1-SCORE-ACK", Path(out).parent, mailbox=mailbox)`, through a
  late import with the comment `# late import: s1_trial imports this module`.

`s1_collect.write_plan` (lines 69–82):

```python
def write_plan(root, planned_start: datetime, opening_close: str, symbols, first_trade_date: str, *,
               mailbox=None) -> Path:
    """F9: the only command that runs without an open trial; it refuses once one is open (or the mailbox is
    unreadable, OQ-20). No provider request, live callback, journal write or priced work. F6.2: the trial_id."""
    import s1_trial                                    # (late import: s1_trial imports s1_common only)
    s1_trial.require_no_open_trial(mailbox)
    if planned_start.tzinfo is None:
        raise ValueError("planned START must be an aware instant")
    now = c.now_utc()
    if planned_start < now + timedelta(days=MIN_LEAD_DAYS):
        raise ValueError(f"planned START must be at least {MIN_LEAD_DAYS} calendar days after the plan")
    deadline = s1_seal.deadline(planned_start)
    dl = (deadline.astimezone(c.NY).date() + timedelta(days=CAL_TAIL_DAYS)).isoformat()
    return _write_once(_out(root) / "plan.json", {
        "trial_id": str(uuid.uuid4()),
        "planned_start": planned_start.isoformat(), "opening_close": opening_close, "created_utc": now.isoformat(),
        "deadline": deadline.isoformat(),
        "calendar_range": [_ny_date(now), dl], "ca_symbols": sorted(set(symbols)),
        "ca_range": [first_trade_date, planned_start.date().isoformat()], "collector_sha256": collector_sha(),
        "fetch_core_sha256": c.E1_FETCH_SHA, "bundle_sha256": c.bundle_sha256()})
```

Add `import uuid` to `s1_collect.py`.

In `s1_run.py`:
- remove `TRIAL_ID`;
- in `attest_start`, `_start_attestation_problems`, `do_prereg` and `attest_stop`, use `plan["trial_id"]`;
- in `score`/`_score`, use `_load(out / "plan.json").get("trial_id")`.

Add `"s1_trial.py"` to BUNDLE_CODE and to the test BUNDLE tuple.

- [ ] **Step 5: GREEN.** Run `test_s1_a3_trial.py` and `test_s1_a3_journal.py` into `a3/t4_green.txt`.
- [ ] **Step 6: Full suite, old->new.** Expected intended changes, each recorded:
  - `test_s1_run.py:218,1012,1505`, `test_s1_t12_a4.py:204` and `test_s1_t12_mutant_survivors.py:228`:
    `trial_id == "S1"` becomes `trial_id == plan["trial_id"]` (a uuid4) (F6.2, OQ-27).
  - `test_s1_task11.py:455`: `"{attest}" in k.ACQUIRE_ACK` becomes `"attest_stop_sha256" in t.ACK_FIELDS["S1-ACQUIRE-ACK"]`
    (OQ-5).
  - `test_s1_connected.py:453`: a hand-formatted ACQUIRE token becomes
    `s1_trial.token("S1-ACQUIRE-ACK", root, mailbox=…)`. This is classified in Task 5, when the token can resolve
    the trial.
  - Tests that build RUN/SCORE/ACQUIRE tokens before Task 5's fixture migration may now error with
    `Refusal("no S1-OPENING-ACK")` when the token's predecessor is absent. That is a fixture incompatibility,
    resolved in Task 5. If any are failing at Task 4's end, the controller may commit Task 4 with a recorded red
    list only when the list is exactly the Task 5 migration set. Otherwise fix them in Task 4.

  Save `a3/t4_full.txt`, `a3/t4_old_new.md` and `a3/t4_hashes.txt`.
- [ ] **Step 7: Controller review and commit.** Message: `S1 A3 Task 4: trial identity, ACK grammar and chain, CLOSE,
  write_plan trial_id`, listing map rows 54, 138–143, 146, 148–150, 158, 159, 168, 170, 253, 273, 275–278 and 318,
  with the Co-Authored-By line. Push and assert the HEAD SHA. (Row 273 implements E3.4, pending Codex acceptance
  of E3. The commit follows BLK-1 like every task.)

---

### Task 5: The trial gate in every command; conftest migration; spies and the network guard (F0.6, F6.4, F6.6, F7.5; OQ-19)

**Files:**
- Modify: `research/s1/s1_trial.py`. Add `Gate`, `gate`, `invalidate`, `_refuse`, `product_context`.
- Modify (the first statement of every command is `gv = s1_trial.gate(...)`):
  - `research/s1/s1_collect.py`: `do_audit` (line 317), `write_final_plan` (line 431), `do_final` (line 458);
  - `research/s1/s1_checkpoint.py`: `run_checkpoint` (line 596), `run_opening_checkpoint` (line 814),
    `run_final_snapshot` (line 922);
  - `research/s1/s1_run.py`: `attest_start` (line 420), `do_prereg` (line 485), `attest_stop` (line 563),
    `score` (line 614).
- Modify (field-by-field ACK verification replaces token-line equality):
  - `s1_collect.do_audit` line 328 and `do_final` line 467;
  - `s1_run.do_prereg` line 528 and `score` line 623;
  - `s1_gates.run_ack_problems` line 107.
- Modify: `research/s1/s1_common.py:1023-1060` (`registration_gate`). A confirmed violation first calls
  `s1_trial.invalidate_current(out, "registration-artifact", record, mailbox)`, then `write_abort` (OQ-19).
- Modify: `research/s1/s1_tests/conftest.py`:
  - add the `s1_no_network` autouse guard, `Spies`, `s1_jappend` and `s1_ack`;
  - `s1_plan_audit` gains synthetic audit stage rows (`journal=True` default);
  - `s1_state` and `s1_register` issue OPENING-ACK, RUN-ACK and PREREG-ACK (and, when score_ready,
    TRIAL-STOP + ACQUIRE-ACK + SCORE-ACK) through `s1_trial.token`.
- Create: `research/s1/s1_tests/test_s1_a3_gate.py`, `research/s1/s1_tests/test_s1_a3_codex_probes.py`
- Create: `research/s1/s1_evidence/a3/codex_probes_historical/`. It holds byte copies of the three probe files, the
  six result JSONs, and `publication-probes.xml`, `registration-probes.xml` and `bundle-bootstrap-probes.xml` (from
  `C:\Users\gl450\.coordination\trading_app\s1_t12_codex_review_c9b4322_20261018\`), plus `SHA256SUMS`.

**Interfaces:**
- Consumes: Tasks 1, 2 and 4.
- Produces (`s1_trial`):
  - `Gate(root, out, trial, rows, state, mailbox)`;
  - `gate(root, where, *, mailbox=None, now=None) -> Gate`, which raises `Refusal`;
  - `invalidate(trial, reason, record, *, root, mailbox=None, clock=None) -> j.Result`;
  - `invalidate_current(out, reason, record, mailbox=None) -> None`, best effort (F8.1);
  - `product_context(trial, cal=None, *, slot_gate=None, stage_gate=None, stop_detail=None) -> Callable[[rows, con], j.Context]`.
- Produces (conftest):
  - `Spies(monkeypatch)` with `.receipt(rec=S1_RECEIPT)`, `.process()`, `.client(handler=None) -> httpx.Client`,
    `.n` and `.assert_zero()`;
  - `s1_jappend(root, kind, subject, *, at, detail=None, op=None, actor=None, r_at=None) -> j.Row`;
  - `s1_ack(root, mid, kind, at, **given) -> str`, which posts `s1_trial.token(kind, root, **given)` as codex->claude
    experiments-prereg and returns the line.

- [ ] **Step 1: Interface stub.** Add a permissive `gate` to `s1_trial`. It returns a Gate without the bundle, state
  or loss checks, and `invalidate` is a no-op. Wire `gate(...)` as the first statement of each of the 10 commands.

```python
@dataclass
class Gate:
    root: Path
    out: Path
    trial: Trial
    rows: list
    state: str
    mailbox: object = None


def gate(root, where, *, mailbox=None, now=None) -> Gate:
    tr = open_trial(mailbox)
    return Gate(Path(root), Path(root) / "s1_out", tr, j.read_trial(tr.trial_id, tr.genesis, mailbox), "ACTIVE",
                mailbox)


def invalidate(trial, reason, record, *, root, mailbox=None, clock=None):
    return None


def invalidate_current(out, reason, record, mailbox=None) -> None:
    return None


def product_context(trial, cal=None, *, slot_gate=None, stage_gate=None, stop_detail=None):
    return lambda rows, con: j.Context(stage_gate=stage_gate, slot_gate=slot_gate, stop_detail=stop_detail)
```

- [ ] **Step 2: Freeze the historical probes.**
  1. Create `research/s1/s1_evidence/a3/codex_probes_historical/`.
  2. Copy byte-identically, using `cp --preserve=timestamps`, from
     `C:\Users\gl450\AppData\Local\Temp\claude\C--Users-gl450\c661c7e7-0401-4122-9c4b-9345620dbebb\scratchpad\codex_repro\`:
     - `test_codex_publication.py` (sha256 `3c81f41fc08ff171881e62c5bddc1dc27e16aaa9b23c033a95a2f172c240b2b9`);
     - `test_codex_registration.py` (`98ec8af58edd8d7535f4cc9689c3cff99e35e15f356d8500457c2d155f0b055e`);
     - `test_codex_combined_damage.py` (`418a9594f2b9c7a3716a2f8e663c20a9494f268e43bae7220fbfce0645fd53c1`);
     - the six `*.json`.
  3. Copy the three XML files from the coordination review folder.
  4. Write `SHA256SUMS` with `sha256sum *`.

  These files are evidence: never collected (they are outside `s1_tests/`), never edited.

- [ ] **Step 3: Write the failing tests.**

conftest additions:

```python
@pytest.fixture(autouse=True)
def s1_no_network(monkeypatch):
    """A3 (F10, plan Global Constraints): no test can reach a network; injected MockTransport clients only."""
    import socket
    import httpx

    def refuse(*a, **kw):
        raise AssertionError("A3 network guard: a real network call was attempted")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


class Spies:
    """A3 F10 spies: live callbacks (receipt, process), captures (s1_snapshot.take_snapshot), provider requests (every
    request an injected MockTransport client sees) and valuation calls (pinned-core economics + s1_run
    candidate_economics)."""

    def __init__(self, monkeypatch):
        import s1_common as c
        import s1_run
        import s1_snapshot
        self.n = {"receipt": 0, "process": 0, "capture": 0, "request": 0, "valuation": 0}
        self.requests = []
        monkeypatch.setattr(s1_snapshot, "take_snapshot", self._count("capture", s1_snapshot.take_snapshot))
        sim = c.sim()
        for name in ("simulate_lot", "baseline_economics", "lot_economics"):
            monkeypatch.setattr(sim, name, self._count("valuation", getattr(sim, name)))
        monkeypatch.setattr(s1_run, "candidate_economics", self._count("valuation", s1_run.candidate_economics))

    def _count(self, key, fn):
        def f(*a, **kw):
            self.n[key] += 1
            return fn(*a, **kw)
        return f

    def receipt(self, rec=None):
        rec = S1_RECEIPT if rec is None else rec
        return self._count("receipt", lambda reference=None: json.loads(json.dumps(rec)))

    def process(self):
        return self._count("process", lambda: dict(S1_PROCESS))

    def client(self, handler=None):
        import httpx

        def h(req):
            self.n["request"] += 1
            self.requests.append(req)
            if handler is None:
                return httpx.Response(500)
            return handler(req)
        return httpx.Client(transport=httpx.MockTransport(h))

    def assert_zero(self):
        assert self.n == dict.fromkeys(self.n, 0), self.n


def s1_jappend(root, kind, subject, *, at, detail=None, op=None, actor=None, r_at=None):
    """A3 synthetic journal fixture (F10 'synthetic journal fixtures'): append one row through the real
    s1_journal.append with a context that accepts it. Test-only."""
    from datetime import timedelta
    import s1_journal as j
    import s1_trial as t
    mb = Path(root) / "mailbox.sqlite3"
    tr = t.open_trial(mb)
    far = at + timedelta(days=3650)
    ctx = j.Context(slot_times=lambda s: (far, far), stop_detail=lambda rows: detail,
                    stage_gate=lambda rows, g: None, slot_gate=lambda rows, s: None)
    res = j.append(tr.trial_id, tr.genesis, j.Request(kind, subject, op or j.new_nonce(), actor or j.new_nonce(),
                                                       detail=detail, r_at=r_at),
                   lambda rows, con: ctx, mailbox=mb, clock=lambda: at)
    assert res.outcome == "APPEND", res
    return res.row


def s1_ack(root, mid, kind, at, **given):
    """Post the exact ACK line s1_trial.token builds (codex->claude experiments-prereg, created `at`)."""
    import s1_trial as t
    ln = t.token(kind, root, mailbox=Path(root) / "mailbox.sqlite3", **given)
    s1_mailbox(root, mid, ln, at)
    return ln
```

At the end of `s1_plan_audit` (`journal=True` keyword; Task 9 replaces this with the real audit stage), add:

```python
    if journal:
        import s1_journal as j
        g = j.stage_subject("audit")
        op, actor = j.new_nonce(), j.new_nonce()
        s1_jappend(root, "STAGE-INTENT", g, at=reserved - timedelta(seconds=1), op=op, actor=actor,
                   detail=j.detail_of({"synthetic": "audit-intent"}))
        d = j.detail_of({"synthetic": "audit-prepared", "manifest": c.sha256_file(audit / "manifest.json")})
        s1_jappend(root, "STAGE-PREPARED", g, at=reserved + timedelta(minutes=2), op=op, actor=actor, detail=d)
        s1_jappend(root, "STAGE-CREATED", g, at=reserved + timedelta(minutes=3), op=op, actor=actor, detail=d)
```

In `s1_state` and `s1_register`, after the opening checkpoint and before the START attestation, add:

```python
    import s1_journal as j
    slot = j.slot_subject(z.close_of(opening_close, cal) + timedelta(minutes=45))
    s1_ack(root, "opening-ack", "S1-OPENING-ACK", oc + timedelta(hours=1), opening_slot=slot,
           evidence_manifest_sha256="e" * 64)
```

The `s1_mailbox(root, "run-ack", r.run_token(root), ack_t)` line becomes
`s1_ack(root, "run-ack", "S1-RUN-ACK", ack_t)`.

After `do_prereg` (`s1_state` score_ready branch and `s1_register`), add
`s1_ack(root, "prereg-ack", "S1-PREREG-ACK", prereg_t + timedelta(minutes=1))`.

In `s1_state` score_ready, when a stop exists:
- before `attest_stop`, add
  `s1_jappend(root, "TRIAL-STOP", "trial", at=t - timedelta(seconds=1), detail=j.detail_of({"synthetic": "stop", "stop": stop}))`;
- after the final plan, add `s1_ack(root, "acq-ack", "S1-ACQUIRE-ACK", t + timedelta(hours=2))`;
- the `"score-ack"` post becomes `s1_ack(root, "score-ack", "S1-SCORE-ACK", t + timedelta(days=3))`.

`test_s1_a3_gate.py`:

```python
"""Addendum 3 rev 5 F0.6 (gates read the open trial, its state and the bundle before any callback, capture, provider
request or pricing), F6.4 (bundle), F6.6 (total loss), F7.5 (closure), F10 Identity and Other/pre-audit. Behavioural
RED against the Task 5 gate stub (s1_evidence/a3/t5_red.txt). Synthetic only; spies on every refusal path."""
import json
import shutil
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest
import s1_checkpoint as ck
import s1_collect as k
import s1_common as c
import s1_journal as j
import s1_run as r
import s1_trial as t
from conftest import (S1_RECEIPT, Spies, _Clock, s1_ack, s1_jappend, s1_mailbox, s1_plan_audit, s1_state)

START = "2026-10-26T13:30:00+00:00"
KEYS = ("KEYID-dummy-123", "SECRET-dummy-456")


def mb(root):
    return Path(root) / "mailbox.sqlite3"


def journal(root):
    tr = t.trials(t.scan(mb(root)))
    return {tid: j.read_trial(tid, x.genesis, mb(root)) for tid, x in tr.items()}


def kinds(root):
    return [(r_.kind, r_.subject) for rows in journal(root).values() for r_ in rows]


def commands(root, sp, sch):
    lg = Path(root) / "ledger.sqlite3"
    after = lambda: sch + timedelta(seconds=30)                                 # noqa: E731
    return {
        "do_audit": lambda: k.do_audit(root, "audit-ack", sp.client(), KEYS),
        "opening": lambda: ck.run_opening_checkpoint(root, lg, sch, sp.receipt(), sp.process(), Path(root) / "c.log",
                                                     now=after),
        "attest_start": lambda: r.attest_start(root, r.START_STATEMENT, S1_RECEIPT),
        "prereg": lambda: r.do_prereg(root, "run-ack", S1_RECEIPT),
        "checkpoint": lambda: ck.run_checkpoint(root, lg, sch, sp.receipt(), sp.process(), Path(root) / "c.log",
                                                now=after),
        "attest_stop": lambda: r.attest_stop(root, r.STOP_STATEMENT),
        "final_plan": lambda: k.write_final_plan(root),
        "final": lambda: k.do_final(root, "acq-ack", sp.client(), KEYS),
        "final_snapshot": lambda: ck.run_final_snapshot(root, lg, now=after),
        "score": lambda: r.score(root, "score-ack"),
    }


@pytest.mark.parametrize("name", ["do_audit", "opening", "attest_start", "prereg", "checkpoint", "attest_stop",
                                  "final_plan", "final", "final_snapshot", "score"])
def test_every_command_reads_trial_state_and_bundle_before_any_callback(tmp_path, monkeypatch, name):
    s1_plan_audit(tmp_path, START, journal=False)
    con = sqlite3.connect(mb(tmp_path))
    con.execute("DELETE FROM messages")                     # the test removes the AUDIT-ACK: zero open trials
    con.commit()
    con.close()
    sp = Spies(monkeypatch)
    sch = c.aware(START) + timedelta(hours=7, minutes=15)
    with pytest.raises(SystemExit, match="zero open trials"):
        commands(tmp_path, sp, sch)[name]()
    sp.assert_zero()


def test_one_valid_open_trial_authorizes_a_stage(tmp_path):
    s1_state(tmp_path, START)
    gv = t.gate(tmp_path, "positive control")
    assert gv.state == "ACTIVE" and gv.rows and gv.trial.trial_id == c.load_json(gv.out / "plan.json")["trial_id"]


def test_wrong_role_close_is_ignored_and_the_trial_stays_open(tmp_path):              # rows 238, 330 (E4.4)
    s1_state(tmp_path, START)
    m = mb(tmp_path)
    ln = t.token("S1-CLOSE-ACK", tmp_path, mailbox=m, reason="WITHDRAWN", evidence_sha256="e" * 64)
    con = sqlite3.connect(m)
    con.execute("INSERT INTO messages VALUES ('c-claude','claude','codex','experiments-prereg',?,?,NULL)",
                (ln, c.aware("2026-10-25T23:00:00+00:00").timestamp()))
    con.commit()
    con.close()
    gv = t.gate(tmp_path, "wrong-role close is no candidate")
    assert gv.state == "ACTIVE" and gv.trial.closed is None


def test_gate_invalid_rows_use_a_fresh_operation_identity(tmp_path):                   # row 313 (OQ-2)
    s1_state(tmp_path, START)
    shutil.rmtree(tmp_path / "s1_out")                                  # the TEST removes its tmp tree: INVALID (LOST)
    with pytest.raises(SystemExit, match="LOST"):
        t.gate(tmp_path, "tree lost")
    tr = t.trials(t.scan(mb(tmp_path)))
    (only,) = tr.values()
    rows = j.read_trial(only.trial_id, only.genesis, mb(tmp_path))
    inv = [x for x in rows if x.kind == "TRIAL-INVALID"]
    assert len(inv) == 1
    earlier = [y for y in rows if y.seq < inv[0].seq]
    assert all(inv[0].op != y.op and inv[0].actor != y.actor for y in earlier)


def _damage(root, case):
    """Mutate the tmp mailbox / journal / plan for one F10 Identity refusal case (test data only)."""
    m = mb(root)
    tr = t.open_trial(m)
    rows = j.read_trial(tr.trial_id, tr.genesis, m)
    last = max(a.created for a in [tr.audit, *tr.acks.values()])
    at = c.aware("2026-10-25T23:00:00+00:00")
    if case == "zero-open":
        s1_ack(root, "close", "S1-CLOSE-ACK", at, reason="WITHDRAWN", evidence_sha256="e" * 64)
    elif case == "two-open":
        other = tr.audit.line.replace(tr.trial_id, "9a1b2c3d-4e5f-4a6b-8c7d-0e1f2a3b4c5d")
        s1_mailbox(root, "audit-2", other, at)
    elif case == "duplicate-trial-id":
        s1_mailbox(root, "audit-dup", tr.audit.line, at)
    elif case == "wrong-bundle-close":
        s1_ack(root, "close", "S1-CLOSE-ACK", at, reason="WITHDRAWN", evidence_sha256="e" * 64,
               bundle_sha256="f" * 64)
    elif case == "close-before-audit":
        s1_ack(root, "close", "S1-CLOSE-ACK", c.aware("2026-01-01T00:00:00+00:00"), reason="WITHDRAWN",
               evidence_sha256="e" * 64)
    elif case == "two-opening-acks":
        em = tr.acks["S1-OPENING-ACK"].fields["evidence_manifest_sha256"]          # (revision 1: derived value)
        s1_mailbox(root, "opening-2", tr.acks["S1-OPENING-ACK"].line.replace("evidence_manifest_sha256=" + em,
                                                                             "evidence_manifest_sha256=" + "d" * 64),
                   at)
    elif case == "identical-duplicate-ack":
        s1_mailbox(root, "run-ack-2", tr.acks["S1-RUN-ACK"].line, at)
    elif case == "broken-prev":
        con = sqlite3.connect(m)
        bad = tr.acks["S1-RUN-ACK"].line.replace(f"prev={tr.acks['S1-OPENING-ACK'].mailbox_id}",
                                                 f"prev={tr.audit.mailbox_id}")
        con.execute("UPDATE messages SET body=? WHERE id='run-ack'", (bad,))   # the TEST edits its tmp mailbox
        con.commit()
        con.close()
    elif case == "closed-trial-same-bundle-ack":                # another (closed) trial's same-bundle RUN-ACK id
        other = "9a1b2c3d-4e5f-4a6b-8c7d-0e1f2a3b4c5d"
        s1_mailbox(root, "other-audit", tr.audit.line.replace(tr.trial_id, other), at - timedelta(days=30))
        s1_mailbox(root, "not-this-trials-run-ack", tr.acks["S1-RUN-ACK"].line.replace(tr.trial_id, other),
                   at - timedelta(days=29))
        s1_mailbox(root, "other-close", " ".join(["S1-CLOSE-ACK", f"trial_id={other}", f"bundle_sha256={tr.bundle}",
                                                  "prev=not-this-trials-run-ack", "reason=WITHDRAWN",
                                                  "evidence_sha256=" + "e" * 64]), at - timedelta(days=28))
    elif case in ("journal-fork", "journal-gap", "duplicate-seq"):
        con = sqlite3.connect(m)
        r0 = rows[-1]
        if case == "journal-gap":
            con.execute("DELETE FROM messages WHERE id=?", (rows[1].mailbox_id,))
        else:
            dup = r0.line if case == "duplicate-seq" else r0.line.replace(f"op={r0.op}", f"op={'7' * 32}")
            con.execute("INSERT INTO messages VALUES ('jdup','s1','codex','experiments-s1-journal',?,?,NULL)",
                        (dup, r0.created + 1))
        con.commit()
        con.close()
    return None


IDENTITY = ["zero-open", "two-open", "duplicate-trial-id", "wrong-bundle-close",
            "close-before-audit", "two-opening-acks", "identical-duplicate-ack", "broken-prev",
            "closed-trial-same-bundle-ack", "journal-fork", "journal-gap", "duplicate-seq", "plan-trial-id-differs"]


@pytest.mark.parametrize("case", IDENTITY)
def test_identity_refusals_have_zero_callbacks(tmp_path, monkeypatch, case):
    if case == "plan-trial-id-differs":
        s1_plan_audit(tmp_path, START, journal=False)
        p = tmp_path / "s1_out" / "plan.json"
        plan = json.loads(p.read_text(encoding="utf-8"))
        plan["trial_id"] = "9a1b2c3d-4e5f-4a6b-8c7d-0e1f2a3b4c5d"
        p.write_text(json.dumps(plan), encoding="utf-8")     # the TEST edits its tmp plan
    else:
        s1_state(tmp_path, START)
        special = _damage(tmp_path, case)
    sp = Spies(monkeypatch)
    sch = c.aware(START) + timedelta(hours=7, minutes=15)
    with pytest.raises(SystemExit):
        if case == "closed-trial-same-bundle-ack":
            with _Clock(c.aware(START) - timedelta(hours=20)):
                r.do_prereg(tmp_path, "not-this-trials-run-ack", S1_RECEIPT)
        else:
            commands(tmp_path, sp, sch)["checkpoint"]()
    sp.assert_zero()
    assert not any(kind == "SLOT-INTENT" for kind, _ in kinds(tmp_path))


def test_bundle_mismatch_before_any_journal_row_is_a_refusal(tmp_path, monkeypatch):
    s1_plan_audit(tmp_path, START, journal=False)
    monkeypatch.setattr(c, "bundle_sha256", lambda *a, **kw: "f" * 64)
    with pytest.raises(SystemExit, match="no journal row yet"):
        t.gate(tmp_path, "probe")
    assert kinds(tmp_path) == [] and c.load_abort(tmp_path / "s1_out") is None


def test_bundle_mismatch_after_any_journal_row_is_invalid_bundle(tmp_path, monkeypatch):
    s1_state(tmp_path, START)
    monkeypatch.setattr(c, "bundle_sha256", lambda *a, **kw: "f" * 64)
    with pytest.raises(SystemExit, match=r"INVALID \(bundle\)"):
        t.gate(tmp_path, "probe")
    assert kinds(tmp_path)[-1] == ("TRIAL-INVALID", "reason/bundle")
    assert c.load_abort(tmp_path / "s1_out")["reason"] == "bundle"


def test_total_loss_is_invalid_lost_and_restoring_stays_invalid(tmp_path, monkeypatch):
    s1_state(tmp_path, START)
    out = tmp_path / "s1_out"
    shutil.copytree(out, tmp_path / "backup")
    shutil.rmtree(out)                                          # the TEST deletes its tmp s1_out
    with pytest.raises(SystemExit, match=r"INVALID \(LOST\)"):
        t.gate(tmp_path, "probe")
    shutil.copytree(tmp_path / "backup", out)
    (out / "aborted.json").unlink(missing_ok=True)
    sp = Spies(monkeypatch)
    with pytest.raises(SystemExit, match="INVALID"):
        commands(tmp_path, sp, c.aware(START) + timedelta(hours=7, minutes=15))["checkpoint"]()
    sp.assert_zero()
    assert ("TRIAL-INVALID", "reason/LOST") in kinds(tmp_path)


def test_invalid_is_irreversible(tmp_path, monkeypatch):
    s1_state(tmp_path, START)
    s1_jappend(tmp_path, "TRIAL-INVALID", "reason/registration-artifact", at=c.aware(START) - timedelta(hours=10),
               detail=j.detail_of({"synthetic": "violation"}))
    for attempt in range(2):
        (tmp_path / "s1_out" / "aborted.json").unlink(missing_ok=True)
        sp = Spies(monkeypatch)
        with pytest.raises(SystemExit, match="INVALID"):
            commands(tmp_path, sp, c.aware(START) + timedelta(hours=7, minutes=15))["checkpoint"]()
        sp.assert_zero()


def test_journal_state_governs_over_local_files(tmp_path):
    s1_state(tmp_path, START)
    s1_jappend(tmp_path, "TRIAL-INVALID", "reason/LOST", at=c.aware(START) - timedelta(hours=10),
               detail=j.detail_of({"synthetic": "lost"}))
    assert c.load_abort(tmp_path / "s1_out") is None            # no local witness at all
    with pytest.raises(SystemExit, match="INVALID"):
        t.gate(tmp_path, "probe")


def test_closure_never_erases_invalidity_or_reuses_the_journal(tmp_path):
    s1_state(tmp_path, START)
    s1_jappend(tmp_path, "TRIAL-INVALID", "reason/LOST", at=c.aware(START) - timedelta(hours=10),
               detail=j.detail_of({"synthetic": "lost"}))
    first_invalid = journal(tmp_path)
    s1_ack(tmp_path, "close", "S1-CLOSE-ACK", c.aware(START) - timedelta(hours=9), reason="INVALID",
           evidence_sha256=[r_ for rows in first_invalid.values() for r_ in rows if r_.kind == "TRIAL-INVALID"][0].sha)
    second = tmp_path / "second"
    with _Clock(c.aware(START) - timedelta(days=20)):
        k.write_plan(second, c.aware(START) + timedelta(days=7), "2026-10-30", [], "2026-10-01", mailbox=mb(tmp_path))
    s1_mailbox(tmp_path, "audit-2", c.audit_token(second / "s1_out"), c.aware(START) - timedelta(hours=8))
    tr = t.open_trial(mb(tmp_path))
    assert tr.trial_id == c.load_json(second / "s1_out" / "plan.json")["trial_id"]
    assert j.read_trial(tr.trial_id, tr.genesis, mb(tmp_path)) == [] and set(tr.acks) == set()
    assert j.trial_state(list(first_invalid.values())[0]) == "INVALID"


def test_before_the_audit_ack_the_opening_and_start_are_blocked(tmp_path, monkeypatch):
    with _Clock(c.aware(START) - timedelta(days=14)):
        k.write_plan(tmp_path, c.aware(START), "2026-10-23", [], "2026-10-01")
    sp = Spies(monkeypatch)
    sch = c.aware("2026-10-23T20:45:00+00:00")
    for name in ("opening", "attest_start"):
        with pytest.raises(SystemExit, match="zero open trials"):
            commands(tmp_path, sp, sch)[name]()
    sp.assert_zero()
```

The `closed-trial-same-bundle-ack` case uses another trial that has the same bundle and is validly closed. Its CLOSE's
`prev` is its latest ACK, the RUN-ACK. The chain problems of a closed trial are never evaluated, because a closed
trial is never open. `do_prereg` offered that trial's RUN-ACK id refuses: by F6.5 it never counts for the open trial.

`test_s1_a3_codex_probes.py` (Task 5 part; later tasks append):

```python
"""Addendum 3 rev 5 F10 'Codex probes': the new tests for the frozen historical probes (copies and hashes in
s1_evidence/a3/codex_probes_historical/, never collected). Old -> new map: plan 'Codex probe old -> new map'.
Synthetic journal fixtures; tmp mailboxes; spies."""
import shutil
from datetime import timedelta
from pathlib import Path

import pytest
import s1_common as c
import s1_run as r
import s1_trial as t
from conftest import S1_RECEIPT, Spies, _Clock, s1_state

START = "2026-10-26T13:30:00+00:00"
HIST = Path(__file__).resolve().parent.parent / "s1_evidence" / "a3" / "codex_probes_historical"
FROZEN = {"test_codex_publication.py": "3c81f41fc08ff171881e62c5bddc1dc27e16aaa9b23c033a95a2f172c240b2b9",
          "test_codex_registration.py": "98ec8af58edd8d7535f4cc9689c3cff99e35e15f356d8500457c2d155f0b055e",
          "test_codex_combined_damage.py": "418a9594f2b9c7a3716a2f8e663c20a9494f268e43bae7220fbfce0645fd53c1"}


def test_historical_probe_copies_are_frozen():
    for name, sha in FROZEN.items():
        assert c.sha256_file(HIST / name) == sha
    sums = dict(reversed(line.split(" *", 1)) if " *" in line else reversed(line.split("  ", 1))
                for line in (HIST / "SHA256SUMS").read_text(encoding="utf-8").splitlines() if line.strip())
    assert all(c.sha256_file(HIST / n) == h for n, h in sums.items()) and len(sums) >= 12


@pytest.mark.parametrize("auth_damage", ["missing", "unparseable"])
def test_combined_damage_is_invalid_bundle_after_any_journal_row(tmp_path, monkeypatch, auth_damage):
    state = s1_state(tmp_path, START)
    with _Clock(state["prereg_at"]):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    out = tmp_path / "s1_out"
    copy = tmp_path / "bundle-copy"
    for rel in (*c.BUNDLE_CODE, *c.DOC_PINS):
        (copy / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(c.HERE / rel, copy / rel)
    monkeypatch.setattr(c, "HERE", copy)
    code = copy / "s1_checkpoint.py"
    saved_code = code.read_bytes()
    code.write_bytes(saved_code + b"\n# synthetic observed bundle change\n")
    damaged = [out / "prereg.json", out / "audit" / "manifest.json"]
    saved = {p: p.read_bytes() for p in damaged}
    for p in damaged:
        if auth_damage == "missing":
            p.unlink()
        else:
            p.write_text("{not JSON", encoding="utf-8")
    sp = Spies(monkeypatch)
    at = state["start"] - timedelta(hours=1)
    with _Clock(at), pytest.raises(SystemExit, match=r"INVALID \(bundle\)"):
        t.gate(tmp_path, "Codex combined-damage probe")
    assert c.load_abort(out)["reason"] == "bundle"
    for p, b in saved.items():
        p.write_bytes(b)
    code.write_bytes(saved_code)
    (out / "aborted.json").unlink()
    with _Clock(at + timedelta(minutes=1)), pytest.raises(SystemExit, match="INVALID"):
        t.gate(tmp_path, "Codex restored probe")
    sp.assert_zero()
```

- [ ] **Step 4: Behavioural RED.** Run `test_s1_a3_gate.py` and `test_s1_a3_codex_probes.py` into `a3/t5_red.txt`.
  - Expected: with the stub gate, the bundle, loss, INVALID and CLOSE/duplicate cases do not refuse with the asserted
    messages; the combined-damage probe does not raise `INVALID (bundle)`.
  - `test_every_command_reads…` passes on the stub, because `open_trial` already refuses zero trials (Task 4).
    Label it `retro (Task 4 reader)`. Its value is that the refusal comes before any spy count.
  - `test_historical_probe_copies_are_frozen` is `static`.
  - `test_wrong_role_close_is_ignored…` passes against the Task 4 reader (E4 is Task 4's). Label it
    `retro (Task 4 reader)`; its RED is row 275 in Task 4.
  - `test_gate_invalid_rows_use_a_fresh_operation_identity` fails on the stub gate (no LOST row is appended).

- [ ] **Step 5: Implement the gate in `s1_trial.py`:**

```python
def _refuse(out: Path, where: str, msg: str, now=None):
    c.record_refusal(out, where, msg, now)
    raise Refusal(f"{where} refused: {msg}")


def invalidate(trial: Trial, reason: str, record: dict, *, root, mailbox=None, clock=None) -> j.Result:
    """Commit TRIAL-INVALID(reason) for a gate-found violation (detail = the observation record, OQ-2); best-effort
    evidence copy s1_out/invalid/<seq>.json with the same canonical bytes (never for LOST: s1_out is not recreated).
    If the journal cannot be written, the observation is the F8.1 residual: a local aborted.json is attempted and the
    command refuses (no further work); nothing claims the violation was recorded externally."""
    req = j.Request("TRIAL-INVALID", j.invalid_subject(reason), j.new_nonce(), j.new_nonce(),
                    detail=j.detail_of(record))
    out = Path(root) / "s1_out"
    try:
        res = j.append(trial.trial_id, trial.genesis, req,
                       lambda rows, con: j.Context(closed=closed_in(con, trial)), mailbox=mailbox, clock=clock)
    except j.JournalError as e:
        if reason != "LOST" and out.is_dir():
            try:
                c.write_abort(out, {"reason": f"uncommitted {reason}", "record": record, "journal_error": str(e),
                                    "actual": None, "close": None, "scheduled": None, "projection_sha256": None,
                                    "receipt_sha256": None})
            except OSError:
                pass
        raise Refusal(f"violation ({reason}) observed but the journal could not be written ({type(e).__name__}): "
                      f"refused; F8.1 residual (lost detection if it never commits)") from None
    if res.row is not None and reason != "LOST" and out.is_dir():
        try:
            c.publish_exclusive(out / "invalid" / f"{res.row.seq}.json", c.canonical(record))
        except (OSError, FileExistsError):
            pass
    return res


def invalidate_current(out: Path, reason: str, record: dict, mailbox=None) -> None:
    """For legacy detectors (OQ-19): commit TRIAL-INVALID for the open trial; any failure is the F8.1 residual
    (the caller still writes its local aborted.json)."""
    try:
        tr = open_trial(mailbox)
        invalidate(tr, reason, record, root=Path(out).parent, mailbox=mailbox)
    except (Refusal, j.JournalError):
        pass


def product_context(trial: Trial, cal=None, *, slot_gate=None, stage_gate=None, stop_detail=None):
    """The Context every product append uses: CLOSED read inside the transaction; slot timing from the pinned
    calendar (Task 6 supplies slot_times through s1_slot); stage/slot gates and the stop rule from their owners."""
    def build(rows, con):
        st_ = None
        if cal is not None:
            import s1_slot                                   # (Task 6 module; absent before Task 6, cal is None)
            st_ = s1_slot.slot_times(cal)
        return j.Context(closed=closed_in(con, trial), slot_times=st_, stop_detail=stop_detail,
                         stage_gate=stage_gate, slot_gate=slot_gate)
    return build


def gate(root, where: str, *, mailbox=None, now=None) -> Gate:
    """F0.6: the first step of every trial-bound command, before any callback, capture, provider request or pricing:
    the open trial (F6.3) and its ACK chain (F7.1) from the mailbox; the journal (chain, F0.5 step 1); the bundle
    against the AUDIT-ACK's (F6.4: refusal before any row, INVALID (bundle) + local abort after); the trial state (F1:
    INVALID refuses with no work, F0.6); total loss (F6.6: INVALID (LOST)); the plan's trial_id (F6.2)."""
    root = Path(root)
    out = root / "s1_out"
    try:
        tr = open_trial(mailbox, root=root)                                            # root: E3.4 BLOCKED evidence
        rows = j.read_trial(tr.trial_id, tr.genesis, mailbox)
    except (Refusal, j.JournalError) as e:
        _refuse(out, where, str(e), now)
    probs = check_journal(tr, rows)
    if probs:
        _refuse(out, where, f"ACK journal binding {probs[:3]} (F7.1): escalate", now)
    observed = c.bundle_sha256()
    if observed != tr.bundle:
        if not rows:
            _refuse(out, where, f"S1 bundle {observed[:12]} differs from the AUDIT-ACK's {tr.bundle[:12]} "
                                f"(no journal row yet)", now)
        rec = {"where": where, "expected_bundle_sha256": tr.bundle, "observed_bundle_sha256": observed,
               "problems": c.bundle_problems(c.bundle_manifest())}
        invalidate(tr, "bundle", rec, root=root, mailbox=mailbox, clock=now)
        c.write_abort(out, dict(rec, reason="bundle", actual=None, close=None, scheduled=None,
                                projection_sha256=None, receipt_sha256=None))
        raise Refusal(f"{where} refused: S1 bundle differs from the trial's AUDIT-ACK bundle after journal rows: "
                      f"INVALID (bundle)")
    st_ = state(tr, rows)
    if st_ == "INVALID":
        bad = j.first(rows, "TRIAL-INVALID")
        try:
            c.write_abort(out, {"reason": f"journal INVALID ({bad.subject})", "first_invalid_line_sha256": bad.sha,
                                "actual": None, "close": None, "scheduled": None, "projection_sha256": None,
                                "receipt_sha256": None})
        except OSError:
            pass
        raise Refusal(f"{where} refused: trial INVALID ({bad.subject}): no work (F0.6, F1)")
    if rows and not out.is_dir():
        invalidate(tr, "LOST", {"where": where, "missing": "s1_out"}, root=root, mailbox=mailbox, clock=now)
        raise Refusal(f"{where} refused: s1_out is gone under an open trial with journal rows: INVALID (LOST)")
    try:
        plan_tid = c.load_json(out / "plan.json").get("trial_id")
    except (OSError, ValueError, AttributeError):
        plan_tid = None
    if plan_tid != tr.trial_id:
        _refuse(out, where, f"plan.json trial_id {plan_tid!r} differs from the AUDIT-ACK's {tr.trial_id} (F6.2)", now)
    return Gate(root, out, tr, rows, st_, mailbox)
```

Hooks added later go between the total-loss check and the plan check, in this order: Task 8 adds
`s1_stage.evaluate(gv)` and Task 7 adds `s1_slot.evidence_check(gv)`. The plan check stays last.

Command wiring:
- The first statement of each command is `gv = s1_trial.gate(root, "<where>", mailbox=mailbox, now=now)`. Use the
  existing `where` texts. Commands without a `now` parameter pass none.
- `s1_collect.do_audit`: replace line 328 with
  `ack = s1_trial.ack_record(s1_trial.verify_ack(gv.trial, gv.rows, "S1-AUDIT-ACK", ack_id, dict(s1_trial.artifact_fields("S1-AUDIT-ACK", out), trial_id=plan["trial_id"], bundle_sha256=c.bundle_sha256())))`.
- The same pattern applies to `do_final` (`S1-ACQUIRE-ACK`), `do_prereg` (`S1-RUN-ACK`) and `score`
  (`S1-SCORE-ACK`): `expected = artifact_fields(kind, out)` plus `trial_id` and `bundle_sha256`.
- `s1_gates.run_ack_problems` line 107: replace the token-line check with a field comparison:
  `kind, f = t.parse_ack_line(c.ack_line(msg, "S1-RUN-ACK"))` (late import of s1_trial), then
  `probs += [f"RUN-ACK {n} does not match" for n, v in t.artifact_fields("S1-RUN-ACK", out).items() if f.get(n) != v]`.

In `s1_common.registration_gate`, insert before the `write_abort` call at line 1054:

```python
    import s1_trial                                          # (late import) OQ-19: commit the violation first
    s1_trial.invalidate_current(out, "registration-artifact", {"where": where, "problems": probs,
                                                               "observed_utc": t.isoformat()}, mailbox)
```

- [ ] **Step 6: GREEN.** Run `test_s1_a3_gate.py`, `test_s1_a3_codex_probes.py`, `test_s1_a3_trial.py`,
  `test_s1_a3_journal.py` and `test_s1_a3_precedence.py` into `a3/t5_green.txt`.

- [ ] **Step 7: Full suite and the old->new list.** Expected classes, each recorded per test in `a3/t5_old_new.md`:
  - **Intended (F6.4):** bundle-mismatch tests that expected a refusal before the opening seal (A3.3/B3 "nothing
    registered yet") now get INVALID (bundle). The fixtures now carry journal rows from the audit on. Examples are in
    `test_s1_t12_a3_a8.py` and `test_s1_t12_fix2_b3.py`; list every one by name.
  - **Intended (F0.6/F1):** tests that expected a recorded ABORTED-INVALID score report after an abort now get a
    refusal with no score when the journal is INVALID. Example:
    `test_s1_t12_fix2_b3.py::test_b3_a_registration_artifact_violation_at_the_score_is_persisted_and_prices_nothing`:
    old = "ABORTED-INVALID report, zero prices", new = "TRIAL-INVALID committed, score refused, zero prices". Every
    test asserting an ABORTED-INVALID score after a legacy abort is listed.
  - **Intended (F7.1/OQ-5):** tests that post hand-formatted RUN/ACQUIRE/SCORE tokens now use `s1_ack`.
  - **Fixture incompatibility:** test-local mailbox helpers that post old AUDIT tokens. `k.audit_token` already emits
    the new format, so a failure here is a real defect. Investigate it; do not classify it away.
  - **Regression:** anything else. Fix the product code.

  Save `a3/t5_full.txt` and `a3/t5_hashes.txt`.
- [ ] **Step 8: Controller review and commit.** Message: `S1 A3 Task 5: trial gate first in every command; bundle,
  loss and identity refusals`, listing map rows 51–53, 57, 144, 145, 147, 160, 171, 179, 227, 234–248, 254, 313
  and 330, with the Co-Authored-By line. Push and assert the HEAD SHA.

---

### Task 6: Slot worker on the journal (F3 events and rows, F0.5 LOST-RACE, F1 post-stop, F7.4 PREREG-ACK; OQ-10, OQ-11, OQ-25, OQ-31–OQ-33)

**Files:**
- Create: `research/s1/s1_slot.py`
- Modify: `research/s1/s1_checkpoint.py`:
  - `run_checkpoint` (lines 596–683) and the worker part of `run_opening_checkpoint` (lines 814–882) use
    `s1_slot.Worker`;
  - `_publish` (lines 385–423) is replaced by `Worker.complete`;
  - `_after_opening_seal` (lines 777–796) is removed, because an opening slot after the opening is decided is
    refused by the slot gate with no row;
  - `finalize_close` accepts a SUCCESS only for a slot with a SLOT-QUALIFIED row (new keyword
    `qualified: frozenset`).
- Modify: `research/s1/s1_common.py:561-577`. `_report_seals` is rewritten to take required seal membership from
  committed history (`s1_slot.required_seals`), never from `after.json` (OQ-11 ruling, E5.2). BUNDLE_CODE gains
  `s1_slot.py`.
- Modify: `research/s1/s1_run.py:768-786`. `_capture_seal_problems` is rewritten the same way. The old->new mapping
  of both functions is listed in `a3/t6_old_new.md`.
- Create: `research/s1/s1_tests/test_s1_a3_slots.py`; append to `research/s1/s1_tests/test_s1_a3_codex_probes.py`.

**Interfaces:**
- Consumes: Task 1/2 (`append`, `decide`, `subject_rows`, `first`, `slot_subject`, `new_nonce`, `detail_of`); Task 3
  (`OwnershipLock`, `slot_lock_name`, `LockHeld`, `LockError`); Task 4/5 (`Gate`, `gate`, `product_context`,
  `invalidate`).
- Produces (`s1_slot`):
  - `slot_of(subject) -> datetime`;
  - `day_for(slot: datetime, cal) -> dict` (the calendar row whose schedule contains it; SystemExit otherwise);
  - `slot_times(cal) -> Callable[[str], tuple[datetime, datetime]]` (E, D);
  - `names(out, slot, day_iso) -> dict` (claim, report, resolution, capture, after paths);
  - `tree_manifest(out, paths) -> dict[str, str]`;
  - `qualified_tree(out, slot, day_iso) -> dict` (report, resolution, capture `backup.sqlite3`, `meta.json` and
    `projection.json`; OQ-32 ruling, E5.6);
  - `seals_checked(out) -> dict[str, str]` ({relpath: sha256} of every seal file the capture read, recorded in the
    pre-J report);
  - `required_seals(out, rows, cal) -> dict[str, str]` (E2.4 r1, the published-committed seals: the union of
    `seals_checked` over committed QUALIFIED reports and, once Task 8 exists, committed PREPARED commitments; Task 11
    adds the stop record's seals);
  - `failed_tree(out, slot, day_iso) -> dict` (claim, report);
  - `move_own_late(out, slot, day_iso, actor, committed: set) -> list[str]`;
  - `post_start_gate(trial) -> Callable[[rows, subject], str | None]`;
  - `opening_gate(trial, out) -> Callable[[rows, subject], str | None]`;
  - `class Worker(gv, slot, day, cal, *, slot_gate, mailbox=None, now=c.now_utc)` with `.subject`, `.op`, `.actor`,
    `.cap_dir`, context-manager lock, `.intent() -> dict | None`, `.complete(rep, success: bool) -> dict`, and
    `.violation(subtype, reason, rep, receipt_sha) -> None` (OQ-31: external first);
  - `SUBTYPES = ("receipt", "binding", "fence", "bridge", "seal-record")`;
  - `REASON_VIOLATION = "established-violation"`.
- Changes Task 1's `s1_journal.REASONS`: add `"established-violation"` (OQ-31). It is recorded in the Task 6
  old->new.

- [ ] **Step 1: Interface stub.** Create `s1_slot.py` with the names above. Its behaviour is permissive and legacy:
  - `Worker.intent()` appends nothing and only publishes the legacy claim;
  - `complete()` calls the legacy `_publish` and appends nothing;
  - `qualified_tree` returns `{}`;
  - `move_own_late` moves nothing;
  - the gates return None.

  Wire `run_checkpoint` and `run_opening_checkpoint` through `Worker`, so the tests exercise the real call path.
  Add `"established-violation"` to `REASONS`.

```python
"""S1 slot rows and slot evidence - Task 6 INTERFACE STUB (permissive; replaced in Step 4)."""
from datetime import datetime, timezone
from pathlib import Path

import s1_common as c
import s1_journal as j
import s1_seal as z

REASON_VIOLATION = "established-violation"


def slot_of(subject: str) -> datetime:
    return datetime.strptime(subject[len("slot/"):], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def day_for(slot, cal) -> dict:
    for d in cal:
        try:
            if slot in z.schedule(d, cal):
                return d
        except ValueError:
            continue
    raise SystemExit(f"{slot.isoformat()} is not a registered seal slot")


def slot_times(cal):
    def f(subject):
        s = slot_of(subject)
        d = day_for(s, cal)
        return z.eligible_until(s, d, cal), z.resolution_deadline(s, d, cal)
    return f


def names(out, slot, day_iso) -> dict:
    n = slot.strftime("%Y%m%dT%H%M%SZ")
    d = Path(out) / "captures" / day_iso
    return {"claim": d / f"{n}.attempt.json", "report": d / f"{n}.report.json",
            "resolution": d / f"{n}.resolution.json", "capture": d / n, "after": d / f"{n}.after.json"}


def tree_manifest(out, paths) -> dict:
    return {}


def qualified_tree(out, slot, day_iso) -> dict:
    return {}


def failed_tree(out, slot, day_iso) -> dict:
    return {}


def move_own_late(out, slot, day_iso, actor, committed) -> list:
    return []


def post_start_gate(trial):
    return lambda rows, subject: None


def opening_gate(trial, out):
    return lambda rows, subject: None


class Worker:
    def __init__(self, gv, slot, day, cal, *, slot_gate, mailbox=None, now=c.now_utc):
        self.gv, self.slot, self.day, self.cal, self.now = gv, slot, day, cal, now
        self.subject = j.slot_subject(slot)
        self.op, self.actor = j.new_nonce(), j.new_nonce()
        self.cap_dir = names(gv.out, slot, day["date"])["capture"]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def intent(self):
        import s1_checkpoint as ck
        ck._claim_slot(self.gv.out, self.cap_dir, self.slot, z.close_of(self.day["date"], self.cal), self.now())
        return None

    def complete(self, rep, success) -> dict:
        import s1_checkpoint as ck
        rec = ck._publish(self.cap_dir, self.day, self.cal, rep, self.now)
        ck._write_report(self.cap_dir, rep)
        return {"kind": None, "outcome": rec.get("outcome"), "reason": ""}

    def violation(self, reason, rep, receipt_sha) -> None:
        import s1_checkpoint as ck
        ck._write_abort(self.gv.out, reason, rep, rep.get("snapshot"), receipt_sha)
```

- [ ] **Step 2: Write the failing tests.** `research/s1/s1_tests/test_s1_a3_slots.py`:

```python
"""Addendum 3 rev 5 F3 (slot rows: P, R, J; QUALIFIED/FAILED details; restart), F0.5 LOST-RACE, F1 post-stop,
F5.1 slot lock order, F7.4 PREREG-ACK. Behavioural RED against the Task 6 stub (s1_evidence/a3/t6_red.txt).
Synthetic ledgers and journals; tmp mailbox; spies; real child processes only where a crash is needed."""
import json
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
import s1_checkpoint as ck
import s1_common as c
import s1_journal as j
import s1_locks as L
import s1_run as r
import s1_seal as z
import s1_slot as sl
import s1_trial as t
from conftest import S1_PROCESS, S1_RECEIPT, Spies, _Clock, s1_ack, s1_jappend, s1_state

START = "2026-10-26T13:30:00+00:00"
HERE = Path(__file__).resolve().parent.parent


def registered(tmp_path):
    st_ = s1_state(tmp_path, START)
    with _Clock(st_["prereg_at"]):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    s1_ack(tmp_path, "prereg-ack", "S1-PREREG-ACK", st_["prereg_at"] + timedelta(minutes=1))
    return st_


def first_slot(st_, minutes=45):
    day = next(d for d in st_["calendar"] if d["date"] == "2026-10-26")
    return day, z.close_of(day["date"], st_["calendar"]) + timedelta(minutes=minutes)


def run(tmp_path, st_, sch, at, sp=None, receipt=S1_RECEIPT):
    if sp is None:
        rec, proc = (lambda reference=None: json.loads(json.dumps(receipt))), (lambda: dict(S1_PROCESS))
    else:
        rec, proc = sp.receipt(receipt), sp.process()
    with _Clock(at):
        return ck.run_checkpoint(tmp_path, st_["ledger"].path, sch, rec, proc, tmp_path / "crash.log", now=lambda: at)


def rows(tmp_path):
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    return j.read_trial(tr.trial_id, tr.genesis, tmp_path / "mailbox.sqlite3")


def slot_rows(tmp_path, sch):
    return [(x.kind, x.op, x.actor, x.at, x.detail) for x in j.subject_rows(rows(tmp_path), j.slot_subject(sch))]


def test_qualified_at_is_r_and_detail_is_the_tree_manifest(tmp_path, monkeypatch):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    at = sch + timedelta(seconds=30)
    run(tmp_path, st_, sch, at)
    got = slot_rows(tmp_path, sch)
    assert [k_ for k_, *_ in got] == ["SLOT-INTENT", "SLOT-QUALIFIED"]
    (k1, op1, act1, _, _), (k2, op2, act2, at2, det2) = got
    assert (op2, act2) == (op1, act1) and at2 == j.fmt_at(at)                      # R = the clock after P
    tree = sl.qualified_tree(tmp_path / "s1_out", sch, day["date"])
    assert set(tree) == {f"captures/2026-10-26/{sch:%Y%m%dT%H%M%SZ}.report.json",
                         f"captures/2026-10-26/{sch:%Y%m%dT%H%M%SZ}.resolution.json",
                         f"captures/2026-10-26/{sch:%Y%m%dT%H%M%SZ}/backup.sqlite3",        # E5.6: raw bytes
                         f"captures/2026-10-26/{sch:%Y%m%dT%H%M%SZ}/meta.json",
                         f"captures/2026-10-26/{sch:%Y%m%dT%H%M%SZ}/projection.json"}
    assert det2 == j.detail_of(tree)
    for rel in tree:                                               # OQ-10: JSON records carry op/actor
        if rel.endswith((".report.json", ".resolution.json")):
            rec = json.loads((tmp_path / "s1_out" / rel).read_text(encoding="utf-8"))
            assert (rec["op"], rec["actor"]) == (op1, act1)


def test_reports_record_seals_checked_in_the_tree(tmp_path):                         # row 266 (E2.4)
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    out = tmp_path / "s1_out"
    want = sl.seals_checked(out)                                   # the opening seal is present after registration
    assert want
    run(tmp_path, st_, sch, sch + timedelta(seconds=30))
    n = sl.names(out, sch, day["date"])
    assert json.loads(n["report"].read_text(encoding="utf-8"))["seals_checked"] == want
    claim = json.loads(n["claim"].read_text(encoding="utf-8"))
    assert claim["capture_dir"] == n["capture"].relative_to(out).as_posix()          # OQ-10 ruling
    det = slot_rows(tmp_path, sch)[1][4]
    rep = json.loads(n["report"].read_text(encoding="utf-8"))
    rep["seals_checked"] = {}
    n["report"].write_text(json.dumps(rep, indent=1), encoding="utf-8")              # the TEST edits its tmp report
    assert j.detail_of(sl.qualified_tree(out, sch, day["date"])) != det              # bound by the tree


@pytest.mark.parametrize("damage", ["deleted", "tampered"])
def test_after_json_is_display_only(tmp_path, damage):                                 # row 264 (E5.2)
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    out = tmp_path / "s1_out"
    run(tmp_path, st_, sch, sch + timedelta(seconds=30))
    probe = lambda: (sl.required_seals(out, rows(tmp_path), st_["calendar"]),               # noqa: E731
                     r._capture_seal_problems(out, rows(tmp_path), st_["calendar"]),
                     c._report_seals(out, rows(tmp_path), st_["calendar"]))
    before = probe()
    after = sl.names(out, sch, day["date"])["capture"].parent / f"{sch:%Y%m%dT%H%M%SZ}.after.json"
    if damage == "deleted":
        after.unlink()
    else:
        after.write_text(json.dumps({"seal": {"written": True, "sha256": "0" * 64}}), encoding="utf-8")
    assert probe() == before
    t.gate(tmp_path, "after.json is display-only")                  # no refusal, no INVALID


@pytest.mark.parametrize("subtype", ["receipt", "binding", "fence"])
def test_established_violation_is_external_first_with_subtype(tmp_path, monkeypatch, subtype):   # row 308
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    out = tmp_path / "s1_out"
    order = []
    real_inv, real_abort = t.invalidate, ck._write_abort
    monkeypatch.setattr(t, "invalidate", lambda *a, **k: (order.append(("invalid", (out / "aborted.json").exists())),
                                                           real_inv(*a, **k))[1])
    monkeypatch.setattr(ck, "_write_abort", lambda *a, **k: (order.append(("abort", None)), real_abort(*a, **k))[1])
    if subtype == "receipt":                                        # the observation, not the predicate, is forced
        real_receipt = ck._receipt

        def changed(rep, *a, **k):
            got = real_receipt(rep, *a, **k)
            rep["receipt_match"] = False
            return got
        monkeypatch.setattr(ck, "_receipt", changed)
    elif subtype == "binding":
        monkeypatch.setattr(ck, "_binding", lambda *a, **k: True)
    else:
        monkeypatch.setattr(z, "check_fences", lambda seals, proj: ["fence: synthetic violation"])
    run(tmp_path, st_, sch, sch + timedelta(seconds=30))
    assert order[0] == ("invalid", False) and ("abort", None) in order[1:]          # external first
    inv = j.first(rows(tmp_path), "TRIAL-INVALID")
    assert inv.subject == "reason/established-violation"
    obs = json.loads((out / "invalid" / f"{inv.seq}.json").read_text(encoding="utf-8"))
    assert obs["subtype"] == subtype and obs["legacy_reason"]
    assert j.first(j.subject_rows(rows(tmp_path), j.slot_subject(sch)), "SLOT-QUALIFIED", "SLOT-FAILED") is None


@pytest.mark.parametrize("offset", ["s-1us", "s", "E-1us", "E", "E+1us"])
def test_clock_boundaries_before_capture(tmp_path, monkeypatch, offset):               # row 310 (OQ-33)
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    e = z.eligible_until(sch, day, st_["calendar"])
    us = timedelta(microseconds=1)
    at = {"s-1us": sch - us, "s": sch, "E-1us": e - us, "E": e, "E+1us": e + us}[offset]
    captured = []
    real = ck._capture
    monkeypatch.setattr(ck, "_capture", lambda *a, **k: (captured.append(1), real(*a, **k))[1])
    n = sl.names(tmp_path / "s1_out", sch, day["date"])
    if offset in ("E", "E+1us"):
        with pytest.raises(SystemExit, match="now >= E"):
            run(tmp_path, st_, sch, at)
        assert slot_rows(tmp_path, sch) == [] and not n["claim"].exists() and captured == []
    elif offset == "s-1us":
        run(tmp_path, st_, sch, at)
        assert [k_ for k_, *_ in slot_rows(tmp_path, sch)] == ["SLOT-INTENT", "SLOT-FAILED"]
        assert n["claim"].exists() and captured == []
    else:
        run(tmp_path, st_, sch, at)
        assert captured == [1] and slot_rows(tmp_path, sch)[0][0] == "SLOT-INTENT"


def test_failed_detail_binds_the_claim_and_the_failure_report(tmp_path):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    run(tmp_path, st_, sch, sch - timedelta(seconds=5))           # an early invocation: clock before s -> FAILURE
    got = slot_rows(tmp_path, sch)
    assert [k_ for k_, *_ in got] == ["SLOT-INTENT", "SLOT-FAILED"]
    assert got[1][4] == j.detail_of(sl.failed_tree(tmp_path / "s1_out", sch, day["date"]))


def test_slot_intent_at_or_after_e_refuses_with_no_row_and_no_capture(tmp_path, monkeypatch):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    sp = Spies(monkeypatch)
    with pytest.raises(SystemExit, match="now >= E"):
        run(tmp_path, st_, sch, z.eligible_until(sch, day, st_["calendar"]), sp)
    sp.assert_zero()
    assert slot_rows(tmp_path, sch) == [] and not sl.names(tmp_path / "s1_out", sch, day["date"])["claim"].exists()


def test_lost_race_moves_only_own_uncommitted_files_to_late(tmp_path, monkeypatch):
    """A synthetic TIMEOUT row is committed between this worker's P and J (with F5 a live lock-holding worker
    excludes the finalizer; the row is forced to prove that the journal decides even then)."""
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    out = tmp_path / "s1_out"
    real = sl.Worker._append

    def racing(self, req):
        if req.kind == "SLOT-QUALIFIED":
            intent = j.first(j.subject_rows(rows(tmp_path), self.subject), "SLOT-INTENT")
            s1_jappend(tmp_path, "SLOT-TIMEOUT", self.subject, op=intent.op, at=req.r_at)
        return real(self, req)
    monkeypatch.setattr(sl.Worker, "_append", racing)
    res = run(tmp_path, st_, sch, sch + timedelta(seconds=30))
    assert res["journal"]["outcome"] == "LOST-RACE"
    n = sl.names(out, sch, day["date"])
    late = out / "late" / day["date"] / f"{sch:%Y%m%dT%H%M%SZ}"
    assert not n["claim"].exists() and not n["capture"].exists() and (late / n["claim"].name).exists()
    assert not (out / "seals" / f"{day['date']}.json").exists()
    assert [k_ for k_, *_ in slot_rows(tmp_path, sch)] == ["SLOT-INTENT", "SLOT-TIMEOUT"]
    assert all(x.kind != "TRIAL-INVALID" for x in rows(tmp_path))
    assert res["journal"]["recheck"] == []


CRASH_AFTER_P = r'''
import json, os, sys
from datetime import datetime
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[1] + "/s1_tests")
import s1_common as c, s1_checkpoint as ck, s1_journal as j
c.MAILBOX = sys.argv[2] + "/mailbox.sqlite3"
at = c.aware(sys.argv[4]); c.now_utc = lambda: at
real = j.append
def crash(trial_id, gen, req, ctx_fn, **kw):
    if req.kind == "SLOT-QUALIFIED":
        os._exit(9)                                          # a real crash after P, before J
    return real(trial_id, gen, req, ctx_fn, **kw)
j.append = crash
from conftest import S1_RECEIPT, S1_PROCESS
ck.run_checkpoint(sys.argv[2], sys.argv[3], c.aware(sys.argv[5]), lambda reference=None: S1_RECEIPT,
                  lambda: dict(S1_PROCESS), sys.argv[2] + "/crash.log", now=lambda: at)
'''


def test_restart_after_a_worker_crash_never_appends_qualified(tmp_path):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    at = sch + timedelta(seconds=30)
    p = subprocess.run([sys.executable, "-I", "-c", CRASH_AFTER_P, str(HERE), str(tmp_path), str(st_["ledger"].path),
                        at.isoformat(), sch.isoformat()], capture_output=True, text=True, timeout=120)
    assert p.returncode == 9, p.stderr
    assert [k_ for k_, *_ in slot_rows(tmp_path, sch)] == ["SLOT-INTENT"]
    with pytest.raises(SystemExit, match="never re-intents"):
        run(tmp_path, st_, sch, at + timedelta(seconds=30))
    assert [k_ for k_, *_ in slot_rows(tmp_path, sch)] == ["SLOT-INTENT"]


def _stop(tmp_path, at):
    s1_jappend(tmp_path, "TRIAL-STOP", "trial", at=at, detail=j.detail_of({"synthetic": "stop"}))


def test_post_stop_new_slot_intent_is_lost_race_with_no_capture(tmp_path, monkeypatch):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    _stop(tmp_path, sch - timedelta(minutes=1))
    sp = Spies(monkeypatch)
    res = run(tmp_path, st_, sch, sch + timedelta(seconds=30), sp)
    assert res["outcome"] == "LOST-RACE"
    sp.assert_zero()
    assert slot_rows(tmp_path, sch) == [] and not (tmp_path / "s1_out" / "captures" / day["date"]).exists()


def test_post_stop_repeat_slot_intent_is_invalid_repeat_attempt(tmp_path):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    run(tmp_path, st_, sch, sch + timedelta(seconds=30))
    _stop(tmp_path, sch + timedelta(minutes=5))
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    res = j.append(tr.trial_id, tr.genesis, j.Request("SLOT-INTENT", j.slot_subject(sch), j.new_nonce(),
                                                       j.new_nonce()),
                   t.product_context(tr, st_["calendar"]), mailbox=tmp_path / "mailbox.sqlite3",
                   clock=lambda: sch + timedelta(minutes=6))
    assert (res.outcome, res.reason) == ("INVALIDATE", "repeat-attempt")


def test_new_slot_intent_after_a_terminal_row_is_invalid_repeat_attempt(tmp_path):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    run(tmp_path, st_, sch, sch + timedelta(seconds=30))
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    res = j.append(tr.trial_id, tr.genesis, j.Request("SLOT-INTENT", j.slot_subject(sch), j.new_nonce(),
                                                       j.new_nonce()),
                   t.product_context(tr, st_["calendar"]), mailbox=tmp_path / "mailbox.sqlite3",
                   clock=lambda: sch + timedelta(minutes=1))
    assert (res.outcome, res.reason) == ("INVALIDATE", "repeat-attempt")


@pytest.mark.parametrize("who", ["no-intent", "foreign-op", "foreign-actor"])
def test_foreign_qualified_is_invalid_even_on_a_terminal_slot(tmp_path, who):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    run(tmp_path, st_, sch, sch + timedelta(seconds=30))            # QUALIFIED: terminal
    sub = j.slot_subject(sch if who != "no-intent" else sch + timedelta(minutes=2))
    intent = j.first(j.subject_rows(rows(tmp_path), j.slot_subject(sch)), "SLOT-INTENT")
    op = intent.op if who == "foreign-actor" else j.new_nonce()
    actor = intent.actor if who == "foreign-op" else j.new_nonce()
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    res = j.append(tr.trial_id, tr.genesis, j.Request("SLOT-QUALIFIED", sub, op, actor, detail="1" * 64,
                                                       r_at=sch + timedelta(minutes=1)),
                   t.product_context(tr, st_["calendar"]), mailbox=tmp_path / "mailbox.sqlite3",
                   clock=lambda: sch + timedelta(minutes=1))
    assert (res.outcome, res.reason) == ("INVALIDATE", "contradictory-completion")


def test_post_start_capture_requires_the_prereg_ack(tmp_path, monkeypatch):
    st_ = s1_state(tmp_path, START)
    with _Clock(st_["prereg_at"]):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    day, sch = first_slot(st_)
    sp = Spies(monkeypatch)
    with pytest.raises(SystemExit, match="PREREG-ACK"):
        run(tmp_path, st_, sch, sch + timedelta(seconds=30), sp)
    sp.assert_zero()
    assert slot_rows(tmp_path, sch) == []
    s1_ack(tmp_path, "prereg-ack", "S1-PREREG-ACK", st_["prereg_at"] + timedelta(minutes=1))
    run(tmp_path, st_, sch + timedelta(minutes=2), sch + timedelta(minutes=2, seconds=30))
    assert [k_ for k_, *_ in slot_rows(tmp_path, sch + timedelta(minutes=2))][0] == "SLOT-INTENT"


def test_slot_lock_is_taken_before_the_journal_read(tmp_path, monkeypatch):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    order = []
    real_acq, real_rel, real_app = L.OwnershipLock.acquire, L.OwnershipLock.release, j.append
    monkeypatch.setattr(L.OwnershipLock, "acquire", lambda self: order.append(("lock", self.path.name))
                        or real_acq(self))
    monkeypatch.setattr(L.OwnershipLock, "release", lambda self: order.append(("release", self.path.name))
                        or real_rel(self))
    monkeypatch.setattr(j, "append", lambda *a, **kw: order.append(("append", a[2].kind)) or real_app(*a, **kw))
    run(tmp_path, st_, sch, sch + timedelta(seconds=30))
    name = L.slot_lock_name(j.slot_subject(sch)) + ".lock"
    i = order.index(("lock", name))
    assert order.index(("append", "SLOT-INTENT")) > i and order.index(("append", "SLOT-QUALIFIED")) > i
    assert order.index(("release", name)) > order.index(("append", "SLOT-QUALIFIED"))
```

Append to `test_s1_a3_codex_probes.py` (new header imports: `s1_checkpoint as ck`, `s1_seal as z`, `s1_slot as sl`,
`s1_journal as j`, `from conftest import S1_PROCESS, s1_ack`):

```python
def _publication(tmp_path, monkeypatch, offset_us):
    """Old: test_codex_publication.exercise (frozen copy). New: the clock is moved to D + offset just before the
    report - the last file of P - is published, so R = D + offset."""
    st_ = s1_state(tmp_path, START)
    with _Clock(st_["prereg_at"]):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    s1_ack(tmp_path, "prereg-ack", "S1-PREREG-ACK", st_["prereg_at"] + timedelta(minutes=1))
    day = next(d for d in st_["calendar"] if d["date"] == "2026-10-26")
    sch = z.close_of(day["date"], st_["calendar"]) + timedelta(minutes=45)
    dl = z.resolution_deadline(sch, day, st_["calendar"])
    clock = [sch + timedelta(seconds=30)]
    target = f"{sch:%Y%m%dT%H%M%SZ}.report.json"
    real = c.publish_exclusive

    def delayed(path, data):
        if offset_us is not None and Path(path).name == target:
            clock[0] = dl + timedelta(microseconds=offset_us)
        return real(path, data)
    monkeypatch.setattr(c, "publish_exclusive", delayed)
    with _Clock(clock[0]):
        rep = ck.run_checkpoint(tmp_path, st_["ledger"].path, sch, lambda reference=None: S1_RECEIPT,
                                lambda: dict(S1_PROCESS), tmp_path / "crash.log", now=lambda: clock[0])
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    got = [x.kind for x in j.subject_rows(j.read_trial(tr.trial_id, tr.genesis, tmp_path / "mailbox.sqlite3"),
                                          j.slot_subject(sch))]
    return rep, got, (tmp_path / "s1_out" / "seals" / f"{day['date']}.json").exists()


def test_publication_d_minus_1us_qualifies_when_no_timeout_committed_first(tmp_path, monkeypatch):
    rep, got, sealed = _publication(tmp_path, monkeypatch, -1)
    assert got == ["SLOT-INTENT", "SLOT-QUALIFIED"] and sealed


@pytest.mark.parametrize("offset_us", [0, 1])
def test_publication_at_d_and_d_plus_1us_does_not_seal(tmp_path, monkeypatch, offset_us):
    rep, got, sealed = _publication(tmp_path, monkeypatch, offset_us)
    assert got == ["SLOT-INTENT"] and not sealed and rep["journal"]["outcome"] == "REFUSE"


def test_publication_well_before_d_seals(tmp_path, monkeypatch):
    rep, got, sealed = _publication(tmp_path, monkeypatch, None)
    assert got == ["SLOT-INTENT", "SLOT-QUALIFIED"] and sealed
```

- [ ] **Step 3: Behavioural RED.** Run `test_s1_a3_slots.py` and the new probe tests into `a3/t6_red.txt`.
  - Expected: no SLOT rows are appended (`[] != ["SLOT-INTENT", …]`); the stub's legacy `_publish` writes a
    RESOLUTION-TIMEOUT and still seals at D and D+1µs (the old behaviour); post-stop captures happen; no
    PREREG-ACK refusal; no lock order entries.
  - `test_publication_well_before_d_seals` and the `[-1]` case assert rows too, so they fail on the stub as well.
    Their outcome part (sealed) is labelled `ctrl`.
  - Revision 1 rows:
    - 266 fails (no `seals_checked`, no `capture_dir`);
    - 264 fails (the stub has no `required_seals`, and the legacy readers have the old signature);
    - 308 fails (the stub writes the local abort first and appends no row);
    - 310 fails at s−1µs, E and E+1µs (no rows; the legacy late path writes a claim).
  - The stub must also define `seals_checked` and `required_seals` as permissive names (returning {}) so that
    collection succeeds.

- [ ] **Step 4: Implement `research/s1/s1_slot.py`.** Replace the stub. Keep `slot_of`, `day_for`, `slot_times` and
  `names` as in the stub. Add the following:

```python
"""S1 slot rows and slot evidence (Addendum 3 rev 5 F3; OQ-10, OQ-11, OQ-13, OQ-14, OQ-31, OQ-32).
Each slot: P (resolution, then report, durably published), R (a same-process clock reading after P), J (the
SLOT-QUALIFIED commit, R < D) or a SLOT-FAILED; T (a finalizer's SLOT-TIMEOUT, Task 7). The slot lock is held across
read-work-append (F5.1). Every JSON record a worker writes carries its op and actor; its capture directory carries
them through its claim (OQ-10). A loser (LOST-RACE) moves only its own uncommitted files to late/ and re-checks."""
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import s1_common as c
import s1_journal as j
import s1_locks as L
import s1_seal as z

REASON_VIOLATION = "established-violation"                                 # OQ-31
SUBTYPES = ("receipt", "binding", "fence", "bridge", "seal-record")         # OQ-31 ruling (E5.1)
CAPTURE_TREE = ("backup.sqlite3", "meta.json", "projection.json")          # OQ-32 ruling (E5.6): raw bytes in the tree


def _rel(out, p) -> str:
    return Path(p).relative_to(out).as_posix()


def seals_checked(out) -> dict:
    """{relpath: sha256} of every seal file under s1_out/seals/ at capture time (the ones _read_seals reads). It is
    written into the pre-J report, so the QUALIFIED/FAILED tree binds it (E2.4, OQ-11)."""
    out = Path(out)
    return {_rel(out, p): c.sha256_file(p) for p in sorted((out / "seals").glob("*.json"))}


def required_seals(out, rows, cal) -> dict:
    """E2.4 (Erratum 1 r1): the PUBLISHED-COMMITTED seals - a determined seal becomes required once a later committed
    tree records it. Task 6: the union of `seals_checked` over the reports of committed QUALIFIED rows whose tree
    detail still verifies (a report that does not verify is itself a Task 7 violation). Task 8 adds every committed
    PREPARED commitment's `seals_checked`; Task 11 adds the F2 stop record's seals. after.json is never read (E5.2).
    A determined seal that is not in this set and is missing may still be published once, with exactly its
    recomputed bytes, while ACTIVE (E2.4); one in this set is never recreated."""
    got = {}
    for r_ in rows:
        if r_.kind == "STAGE-PREPARED":                                            # Task 8 (E2.4: PREPARED)
            try:
                import s1_stage
                tid = {x.trial_id for x in rows}.pop()
                com = s1_stage.committed_commitment(Path(out).parent, tid, r_.subject[len("stage/"):], rows)
            except (ImportError, AttributeError, OSError, ValueError, SystemExit):
                continue                                    # a bad commitment is s1_stage.evaluate's violation
            for rel, sha in (com.get("seals_checked") or {}).items():
                got.setdefault(rel, sha)
            continue
        if r_.kind != "SLOT-QUALIFIED":
            continue
        s = slot_of(r_.subject)
        n = names(out, s, day_for(s, cal)["date"])
        try:
            rep = json.loads(n["report"].read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if j.detail_of(_tree_or_empty(out, r_, s, cal)) != r_.detail:
            continue
        for rel, sha in (rep.get("seals_checked") or {}).items():
            got.setdefault(rel, sha)
    return got


def _tree_or_empty(out, r_, s, cal) -> dict:
    try:
        f = qualified_tree if r_.kind == "SLOT-QUALIFIED" else failed_tree
        return f(out, s, day_for(s, cal)["date"])
    except OSError:
        return {}


def tree_manifest(out, paths) -> dict:
    """{relpath under s1_out: sha256} of `paths` (bytes as written; F3)."""
    out = Path(out)
    return {_rel(out, p): c.sha256_file(p) for p in sorted(Path(x) for x in paths)}


def qualified_tree(out, slot, day_iso) -> dict:
    n = names(out, slot, day_iso)
    return tree_manifest(out, [n["report"], n["resolution"]] + [n["capture"] / f for f in CAPTURE_TREE])


def failed_tree(out, slot, day_iso) -> dict:
    n = names(out, slot, day_iso)
    return tree_manifest(out, [n["claim"], n["report"]])


def _carries(p: Path, actor: str) -> bool:
    try:
        rec = json.loads(Path(p).read_text(encoding="utf-8"))
        return isinstance(rec, dict) and rec.get("actor") == actor
    except (OSError, ValueError):
        return False


def move_own_late(out, slot, day_iso, actor, committed: set) -> list:
    """F0.5 LOST-RACE: move to late/<day>/<slot>/ only this actor's own files (claim/report/resolution carrying its
    actor; the capture directory through its claim) that no committed manifest lists. Never touches committed files."""
    out, n = Path(out), names(out, slot, day_iso)
    own_claim = n["claim"].is_file() and _carries(n["claim"], actor)
    dest = out / "late" / day_iso / slot.strftime("%Y%m%dT%H%M%SZ")
    moved = []
    for key in ("resolution", "report", "claim", "capture"):
        p = n[key]
        if not p.exists() or _rel(out, p) in committed:
            continue
        mine = own_claim if key == "capture" else _carries(p, actor)
        if mine and not any(x.startswith(_rel(out, p) + "/") for x in committed):
            dest.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(dest / p.name))
            moved.append(_rel(out, p))
    return moved


def post_start_gate(trial):
    """F7.4: no post-START capture without the PREREG-ACK."""
    def g(rows, subject):
        return None if "S1-PREREG-ACK" in trial.acks else "no S1-PREREG-ACK: no post-START capture (F7.4)"
    return g


def opening_gate(trial, out):
    """F1 'stage gates and ACKs apply' for an opening-close slot: the audit stage CREATED, and the opening not yet
    decided (no opening STAGE-INTENT; before Task 10: no opening seal file)."""
    def g(rows, subject):
        if j.first(j.subject_rows(rows, "stage/audit"), "STAGE-CREATED") is None:
            return "the audit stage is not CREATED: no opening capture"
        if j.first(j.subject_rows(rows, "stage/opening"), "STAGE-INTENT") is not None or \
                any((Path(out) / "seals").glob("*.json")):
            return "the opening is already decided: no further opening capture"
        return None
    return g


def committed_paths(out, rows, cal) -> set:
    """Every relpath a committed slot row binds (QUALIFIED/FAILED trees) - so a LOST-RACE never moves a committed
    file. captures/<day> is the slot's CLOSE date (an overnight slot belongs to the previous close), from the
    calendar."""
    got = set()
    for r_ in rows:
        if r_.kind in ("SLOT-QUALIFIED", "SLOT-FAILED"):
            s = slot_of(r_.subject)
            day_iso = day_for(s, cal)["date"]
            n = names(out, s, day_iso)
            got |= {_rel(out, n[k_]) for k_ in ("report", "resolution", "claim") if n[k_].exists()}
            got |= {_rel(out, n["capture"] / f) for f in CAPTURE_TREE}
    return got


class Worker:
    """One process's attempt at one slot (F3). Context manager: the slot lock (F5.1)."""

    def __init__(self, gv, slot, day, cal, *, slot_gate, mailbox=None, now=c.now_utc):
        import s1_trial
        self.gv, self.slot, self.day, self.cal, self.now, self.mailbox = gv, slot, day, cal, now, mailbox
        self.subject = j.slot_subject(slot)
        self.op, self.actor = j.new_nonce(), j.new_nonce()
        self.n = names(gv.out, slot, day["date"])
        self.cap_dir = self.n["capture"]
        self.ctx = s1_trial.product_context(gv.trial, cal, slot_gate=slot_gate)
        self.lock = L.OwnershipLock(gv.root, gv.trial.trial_id, L.slot_lock_name(self.subject))

    def __enter__(self):
        try:
            self.lock.acquire()
        except L.LockHeld:
            raise SystemExit(f"{self.subject}: pending - another process owns this slot (F5)") from None
        except L.LockError as e:
            raise SystemExit(f"{self.subject}: lock error ({e}): refused with no row (F5.5)") from None
        return self

    def __exit__(self, *exc):
        self.lock.release()
        return False

    def _append(self, req):
        return j.append(self.gv.trial.trial_id, self.gv.trial.genesis, req, self.ctx, mailbox=self.mailbox,
                        clock=self.now)

    def _rows(self):
        return j.read_trial(self.gv.trial.trial_id, self.gv.trial.genesis, self.mailbox)

    def intent(self):
        """The restart pre-check (F3: a restarted process never opens a second INTENT), then SLOT-INTENT and the claim.
        Returns None to proceed, or a LOST-RACE record (STOPPED: no capture). Refusals and INVALID raise."""
        if j.subject_rows(self._rows(), self.subject):
            raise SystemExit(f"{self.subject}: already has a journal row: a restart never re-intents (F3); the "
                             f"finalizer decides it")
        res = self._append(j.Request("SLOT-INTENT", self.subject, self.op, self.actor))
        if res.outcome == "LOST-RACE":
            return {"scheduled": self.slot.isoformat(), "outcome": "LOST-RACE", "reason": res.reason}
        if res.outcome == "INVALIDATE":
            raise SystemExit(f"{self.subject}: SLOT-INTENT -> INVALID ({res.reason})")
        if res.outcome != "APPEND":
            raise SystemExit(f"{self.subject}: SLOT-INTENT refused with no row: {res.reason}")
        c.publish_text_exclusive(self.n["claim"], json.dumps({
            "scheduled": self.slot.isoformat(), "invoked_utc": res.row.at,
            "close": z.close_of(self.day["date"], self.cal).isoformat(), "op": self.op, "actor": self.actor,
            "intent_seq": res.row.seq,
            "capture_dir": _rel(self.gv.out, self.cap_dir)}))                         # OQ-10 ruling
        return None

    def complete(self, rep: dict, success: bool) -> dict:
        """P: the resolution, then the report (each carries op/actor; the report is frozen before J and carries
        `seals_checked`, E2.4); R; then J (QUALIFIED with at = R) or FAILED. Seal and stop outcomes go to the
        display-only <slot>.after.json (E5.2), which no check or decision reads."""
        rep.setdefault("seals_checked", {})
        import s1_checkpoint as ck
        ev = ck._evidence(rep)
        ok = bool(success and rep.get("candidate") and ck._complete_success(ev))
        res_rec = {"outcome": ck.SUCCESS if ok else ck.FAILURE, "slot": self.slot.isoformat(),
                   "evidence": ev, "op": self.op, "actor": self.actor}
        c.publish_exclusive(self.n["resolution"], json.dumps(ck._jsonable(res_rec), indent=1,
                                                              sort_keys=True).encode("utf-8"))
        c.publish_text_exclusive(self.n["report"], json.dumps(dict(rep, op=self.op, actor=self.actor), indent=1))
        r_ = self.now()                                                        # R (F3)
        if ok:
            req = j.Request("SLOT-QUALIFIED", self.subject, self.op, self.actor,
                            detail=j.detail_of(qualified_tree(self.gv.out, self.slot, self.day["date"])), r_at=r_)
        else:
            req = j.Request("SLOT-FAILED", self.subject, self.op, self.actor,
                            detail=j.detail_of(failed_tree(self.gv.out, self.slot, self.day["date"])))
        res = self._append(req)
        got = {"kind": req.kind, "outcome": res.outcome, "reason": res.reason, "R": r_.isoformat()}
        if res.outcome == "LOST-RACE":
            rows = self._rows()
            got["late"] = move_own_late(self.gv.out, self.slot, self.day["date"], self.actor,
                                        committed_paths(self.gv.out, rows, self.cal))
            got["recheck"] = slot_problems(self.gv.out, rows, self.subject, self.cal)
        if res.outcome == "INVALIDATE":
            raise SystemExit(f"{self.subject}: {req.kind} -> INVALID ({res.reason})")
        return got

    def violation(self, subtype, reason, rep, receipt_sha) -> None:
        """An established violation (A9.2) observed by this capture (OQ-31 ruling, E5.1): EXTERNAL FIRST -
        TRIAL-INVALID(established-violation) with `subtype` and the exact c9b4322 `legacy_reason`, then the local
        first-wins aborted.json. If the journal cannot be written, invalidate() writes the local abort and refuses
        (the F8.1 residual; nothing claims an external record). No terminal slot event is required first."""
        import s1_checkpoint as ck
        import s1_trial
        assert subtype in SUBTYPES, subtype
        legacy = reason if isinstance(reason, str) else list(reason)
        rec = {"subtype": subtype, "legacy_reason": legacy, "slot": self.slot.isoformat(),
               "snapshot": rep.get("snapshot"), "receipt_sha256": receipt_sha}
        try:
            s1_trial.invalidate(self.gv.trial, REASON_VIOLATION, rec, root=self.gv.root, mailbox=self.mailbox,
                                clock=self.now)
        finally:
            ck._write_abort(self.gv.out, reason, rep, rep.get("snapshot"), receipt_sha)    # first-wins, local


def slot_problems(out, rows, subject, cal) -> list:
    """Task 6: [] (Task 7 implements the F3 evidence table; this name is its per-slot entry point)."""
    return []
```

`run_checkpoint` (replace lines 596–683):

```python
def run_checkpoint(root, live_db, scheduled, receipt_fn, process_fn, crash_log, now=c.now_utc,
                   mailbox=None) -> dict:
    """One registered post-START slot (Addendum 3 F3; Task 6): the trial gate (F0.6), the RUN-ACK registration
    (A8.2), the slot lock, SLOT-INTENT (STOPPED -> LOST-RACE with no capture; now >= E -> refusal with no row), the
    claim, the A5.2 clock check, the capture and the observations (unchanged), the resolution and report (P), R and
    J/FAILED; then the seal selection over QUALIFIED slots and the stop (after.json, OQ-11)."""
    import s1_slot
    import s1_trial
    out = Path(root) / "s1_out"
    gv = s1_trial.gate(root, "checkpoint", mailbox=mailbox, now=now)
    pr = g.verified_registration(out, "checkpoint", mailbox, now)
    start, cal = c.aware(pr["start"]), pr["calendar"]
    day = _close_for(scheduled, cal)
    close = z.close_of(day["date"], cal)
    with s1_slot.Worker(gv, scheduled, day, cal, slot_gate=s1_slot.post_start_gate(gv.trial), mailbox=mailbox,
                        now=now) as w:
        lost = w.intent()
        if lost is not None:
            return lost
        cap_dir, t0 = w.cap_dir, now()
        refused = _clock_refusal(cap_dir, day, cal, close, scheduled, t0)
        if refused is not None:                                    # A5.2 (t < s; t > E cannot reach here)
            return dict(refused, journal=w.complete(refused, success=False))
        meta, rep = _capture(close, scheduled, live_db, cap_dir, now, z.eligible_until(scheduled, day, cal))
        proc, rec = _observe_process(out, rep, process_fn, crash_log)
        binding_changed = _binding(rep, proc, pr.get("process_binding"))
        receipt, receipt_sha = _receipt(rep, receipt_fn, pr["receipt"])
        rep["seals_checked"] = s1_slot.seals_checked(out)                     # E2.4: bound by the tree
        seals, seals_err = _read_seals(out, rep)
        proj = _read_capture(cap_dir, meta, rep, lambda trades: (len(z.cohort(trades, start, close)),
                                                                 z.count_sold(trades, start, close)))
        fences, bridges = [], []
        if proj is not None and seals_err is None:
            fences = z.check_fences(seals, proj)
            bridges = z.check_bridge(seals, proj["trades"], start)
            rep["fence_violations"] = fences + bridges                         # unchanged legacy field
        failures = rep.get("failures") or {}
        reason = subtype = None
        if seals_err is not None:
            reason, subtype = f"bad seal record: {seals_err}", "seal-record"
        elif rep["receipt_match"] is False:
            reason, subtype = "semantic receipt changed", "receipt"
        elif failures.get("receipt", {}).get("terminal"):
            reason, subtype = f"semantic receipt changed: {failures['receipt']['reason']}", "receipt"
        elif binding_changed:
            reason = "process binding changed (launcher/process binding evidence differs from the reference)"
            subtype = "binding"
        elif rep["fence_violations"]:
            reason, subtype = rep["fence_violations"], ("fence" if fences else "bridge")
        if reason is None and proj is not None and rep["consistent"] and rep["receipt_match"] is True \
                and not failures and not rep["late"]:
            try:
                bridge = (z.bridge_record(proj["trades"], start, z.opening_close_of(start, cal)) if close >= start
                          else None)
            except ValueError as e:
                rep["refused"] = f"bridge record unavailable: {e}"
            else:
                rep["candidate"] = _candidate(rep, meta, cap_dir, proc, rec, receipt, receipt_sha, bridge, False)
        if reason is not None:                                                  # OQ-31: external first, then
            w.violation(subtype, reason, rep, receipt_sha)                      # local; no slot row first
            return dict(rep, journal={"kind": "TRIAL-INVALID", "reason": s1_slot.REASON_VIOLATION,
                                      "subtype": subtype})
        result = w.complete(rep, success=bool(rep.get("candidate")))
    after = {"journal": result}
    if result["outcome"] == "APPEND" and result["kind"] == "SLOT-QUALIFIED":
        after.update(_after_qualified(gv, out, day, cal, start, now, mailbox))
    c.publish_text_exclusive(_after_path(cap_dir), json.dumps(after, indent=1, default=str))
    return dict(rep, **after)


def _after_path(cap_dir: Path) -> Path:
    return cap_dir.parent / f"{cap_dir.name}.after.json"


def _after_qualified(gv, out, day, cal, start, now, mailbox) -> dict:
    """Task 6: the legacy serialized selection, restricted to slots with a SLOT-QUALIFIED row (the journal decides),
    then the legacy persisted stop (A2.1). Task 7 replaces the selection with the journal finalizer; Task 11 replaces
    the stop with TRIAL-STOP."""
    import s1_journal as j
    rows = j.read_trial(gv.trial.trial_id, gv.trial.genesis, mailbox)
    q = frozenset(r_.subject for r_ in rows if r_.kind == "SLOT-QUALIFIED")
    fin = finalize_close(out, day, cal, now(), qualified=q)
    got = {"seal": {"written": fin["written"], "sha256": fin["sha256"], "from_slot": fin["from_slot"]},
           "deferred": fin["deferred"], "refused": fin["refused"]}
    try:
        got["stop"] = _public(z.current_stop(out, start, cal, now(), "checkpoint"))
    except (ValueError, KeyError, TypeError, b.BookError) as e:
        got["stop_error"] = f"{type(e).__name__}: {e}"
    return got
```

In `finalize_close`, add the keyword `qualified=None`. Where it reads `if rec["outcome"] != SUCCESS: continue`, it now
reads:

```python
        if rec["outcome"] != SUCCESS or (qualified is not None and j_subject(slot) not in qualified):
            continue
```

`j_subject` is `s1_journal.slot_subject`, imported at the top of the function.

`run_opening_checkpoint`: the same worker skeleton with `slot_gate=s1_slot.opening_gate(gv.trial, out)`:
- the receipt reference is None and the opening receipt is handled as now;
- the after-seal branch is deleted;
- after QUALIFIED, `_after_qualified` runs with the existing `before_seal`/`before_build` hooks passed through to
  `finalize_close`.

`s1_common._report_seals` (line 567) and `s1_run._capture_seal_problems` (line 772) are rewritten (OQ-11 ruling).
Their new signatures are `_report_seals(out, rows, cal) -> list[(relpath, seal path, sha256)]` and
`_capture_seal_problems(out, rows, cal) -> list[str]`; each caller passes the gate's `gv.rows` and the plan
calendar:
- the required seals are `s1_slot.required_seals(out, rows, cal)` (committed reports' `seals_checked`; Task 11 adds
  the stop record), read from the trial's journal;
- each required seal must exist with the listed sha256, otherwise a registration-artifact problem;
- neither function opens any `after.json` (E5.2). Their docstrings say so.

`a3/t6_old_new.md` lists, per old line, what it read (`report["seal"]`/after.json) and what it reads now.
`after.json` stays as a display-only convenience; deleting or editing it changes no outcome (row 264).

Add `"s1_slot.py"` to BUNDLE_CODE and to the BUNDLE test tuple. Add `"established-violation"` to
`s1_journal.REASONS`, and to the OQ-1 code list (old->new for the Task 1 test is none; no test pins REASONS).

- [ ] **Step 5: GREEN.** Run `test_s1_a3_slots.py`, `test_s1_a3_codex_probes.py` and the earlier A3 files into
  `a3/t6_green.txt`.
- [ ] **Step 6: Full suite, old->new.** Expected intended changes, each listed in `a3/t6_old_new.md` with its spec
  clause:
  - **F0.5 step 6:** late invocations (t > E) no longer write a claim and refused report; they are refused with no
    row. This affects `test_s1_t12_a5_a6.py` and `test_s1_checkpoint.py` tests asserting a refused report at
    t > E. Early invocations (t < s) still produce a claim and a FAILED row with the refused report (OQ-33).
  - **B1.3 -> F3:** late-worker RESOLUTION-TIMEOUT records and `.late.json`/`.overrun.json` are no longer written
    by the worker. The R >= D case is a REFUSE with no row. This affects `test_s1_t12_fix2_b1.py`,
    `test_s1_t12_fix3.py` (M-1 overrun) and `test_s1_t12_fix2_mutants.py`.
  - **R-3 (fix round 5) -> opening gate:** after-seal opening slots no longer leave claim/report evidence; they are
    refused with no row. This affects `test_s1_t12_fix5.py` R-3 tests.
  - **A2.2 -> F1 (OQ-25):** post-stop scheduled checkpoints no longer capture; they are LOST-RACE. This affects
    `test_s1_task11.py` post-stop capture tests and `test_s1_t12_a2.py`.
  - **Report content (OQ-11):** `rep["seal"]` and `rep["stop"]` in the stored report are now initial values.
    Assertions move to the returned dict or to `.after.json`. This affects `test_s1_checkpoint.py` and
    `test_s1_checkpoint_7b.py`.

  Fixture: none expected. Save `a3/t6_full.txt` and `a3/t6_hashes.txt`.
- [ ] **Step 7: Controller review and commit.** Message: `S1 A3 Task 6: slot worker on the journal (INTENT, P, R,
  QUALIFIED/FAILED, LOST-RACE)`, listing map rows 19, 70, 71, 74, 130, 157, 172–174, 186, 188, 196, 197, 264, 266,
  308 and 310, with the Co-Authored-By line. Push and assert the HEAD SHA.

---

### Task 7: Slot finalizer, the F3 evidence table and post-START seals (F3, F0.5 4c/4d/6, F0.7; OQ-13, OQ-14)

**Files:**
- Modify: `research/s1/s1_slot.py`. Add `finalize_close`, `first_qualified`, `seal_bytes`, `slot_problems` (real),
  `evidence_problems`, `evidence_check` and `move_leftovers`.
- Modify: `research/s1/s1_checkpoint.py`:
  - `finalize_close`, `_finalize_others` and `finalize_pending` delegate to `s1_slot.finalize_close` (the journal
    walk; no MISSED/RESOLUTION-TIMEOUT files);
  - `_seal_bytes` moves to `s1_slot.seal_bytes`, and checkpoint calls it.
- Modify: `research/s1/s1_trial.py:gate`. Add the hook `s1_slot.evidence_check(gv)` before the plan check.
- Modify: `research/s1/s1_tests/conftest.py`. `_write_seal` also writes the slot's claim, resolution and report, with
  evidence a `seal_bytes` round-trip reproduces, and appends synthetic INTENT + QUALIFIED rows with the real tree
  detail.
- Create: `research/s1/s1_tests/test_s1_a3_finalizer.py`; append the race probes to `test_s1_a3_codex_probes.py`.

**Interfaces:**
- Consumes: Task 6 `Worker`, `names`, `qualified_tree`, `failed_tree`, `committed_paths`, `slot_times`.
- Produces (`s1_slot`):
  - `finalize_close(gv, day, cal, now, *, mailbox=None, before_seal=None, before_build=None) -> dict` (same keys as
    the legacy result: written, sha256, from_slot, deferred, refused);
  - `first_qualified(rows, day, cal) -> Row | None`;
  - `seal_bytes(day, close, ev) -> bytes`;
  - `slot_problems(out, rows, subject, cal) -> list[str]`;
  - `evidence_problems(out, rows, cal) -> list[str]`;
  - `evidence_check(gv) -> None` (INVALIDATE registration-artifact plus refusal on problems; includes E2.4 required
    seals);
  - `move_leftovers(out, slot, day_iso, op, *, root=None, trial_id=None) -> list[str] | None` (None = deferred: the
    work lock is held, E1.4);
  - `publish_seal(gv, day, cal, res, *, mailbox=None, before_seal=None, stop_lock_held=False) -> dict` (E2.3: the
    only seal publisher; under the stop lock; ACTIVE only).
- E1: `finalize_close` takes no slot work lock for any decision. The revision-0 "pending: a live owner holds the
  slot lock" path is deleted (PLAN-1).

- [ ] **Step 1: Interface stub.** In `s1_slot`, `finalize_close` calls the legacy
  `s1_checkpoint.finalize_close(gv.out, day, cal, now(), qualified=…)`; `evidence_problems` and `slot_problems`
  return `[]`; `evidence_check` is a no-op; `move_leftovers` returns `[]`; `first_qualified` returns the first
  QUALIFIED row without the "earlier slots terminal" condition. `publish_seal` calls the legacy seal write with no
  stop lock and no state check. `finalize_close` takes the slot lock around its legacy call (revision 0's
  behaviour), so that rows 256–258 have a genuine RED. Wire the gate hook.

- [ ] **Step 2: Write the failing tests.** `research/s1/s1_tests/test_s1_a3_finalizer.py`:

```python
"""Addendum 3 rev 5 F3 (finalizer rows, the evidence table, the opening/post-START seal from the first QUALIFIED
slot in schedule order), F0.5 4c/4d/6, F0.7, OQ-13/OQ-14. Behavioural RED against the Task 7 stub
(s1_evidence/a3/t7_red.txt). Synthetic journals and ledgers; spies; child processes for the two-finalizer race."""
import json
import shutil
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
import s1_checkpoint as ck
import s1_common as c
import s1_journal as j
import s1_seal as z
import s1_slot as sl
import s1_trial as t
from conftest import S1_PROCESS, S1_RECEIPT, Spies, _Clock, s1_jappend
from test_s1_a3_slots import first_slot, registered, rows, run, slot_rows

HERE = Path(__file__).resolve().parent.parent


def fin(tmp_path, st_, day, at):
    gv = t.gate(tmp_path, "finalizer test")
    with _Clock(at):
        return sl.finalize_close(gv, day, st_["calendar"], lambda: at, mailbox=tmp_path / "mailbox.sqlite3")


def E_D(st_, day, sch):
    return z.eligible_until(sch, day, st_["calendar"]), z.resolution_deadline(sch, day, st_["calendar"])


def test_missed_after_e_with_its_own_op_and_no_files(tmp_path):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    e, d = E_D(st_, day, sch)
    fin(tmp_path, st_, day, e)
    got = slot_rows(tmp_path, sch)
    assert [k_ for k_, *_ in got] == ["SLOT-MISSED"]
    n = sl.names(tmp_path / "s1_out", sch, day["date"])
    assert not any(n[k_].exists() for k_ in ("claim", "report", "resolution", "capture"))


def test_premature_finalizer_before_e_or_d_refuses_with_no_row(tmp_path):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    e, d = E_D(st_, day, sch)
    fin(tmp_path, st_, day, e - timedelta(microseconds=1))
    assert slot_rows(tmp_path, sch) == []
    s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(sch), at=sch + timedelta(seconds=1))
    fin(tmp_path, st_, day, d - timedelta(microseconds=1))
    assert [k_ for k_, *_ in slot_rows(tmp_path, sch)] == ["SLOT-INTENT"]


def test_missed_against_an_in_flight_slot_refuses_then_timeout_at_d(tmp_path):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    e, d = E_D(st_, day, sch)
    s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(sch), at=sch + timedelta(seconds=1))
    fin(tmp_path, st_, day, e)                                      # 4d: no MISSED for an in-flight slot
    assert [k_ for k_, *_ in slot_rows(tmp_path, sch)] == ["SLOT-INTENT"]
    fin(tmp_path, st_, day, d)
    assert [k_ for k_, *_ in slot_rows(tmp_path, sch)] == ["SLOT-INTENT", "SLOT-TIMEOUT"]


def test_timeout_carries_the_intent_op_and_the_finalizer_actor(tmp_path):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    e, d = E_D(st_, day, sch)
    s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(sch), at=sch + timedelta(seconds=1), op="1" * 32,
               actor="2" * 32)
    fin(tmp_path, st_, day, d)
    (k1, op1, a1, *_), (k2, op2, a2, *_) = slot_rows(tmp_path, sch)
    assert op2 == op1 == "1" * 32 and a2 != a1


# ---------------------------------------------------------------- E1 (rows 256-259, 320-322): PLAN-1
LIVE_WORKER = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import s1_common as c, s1_journal as j, s1_locks as L, s1_slot as sl, s1_trial as t
root, subject, cal_p, at0, day_iso = sys.argv[2], sys.argv[3], sys.argv[4], c.aware(sys.argv[5]), sys.argv[6]
mb = root + "/mailbox.sqlite3"
cal = json.loads(open(cal_p, encoding="utf-8").read())
tr = t.open_trial(mb)
lk = L.OwnershipLock(root, tr.trial_id, L.slot_lock_name(subject)).acquire()      # the slot WORK lock, held to exit
op, actor = j.new_nonce(), j.new_nonce()
ctx = t.product_context(tr, cal, slot_gate=lambda rows, s: None)
res = j.append(tr.trial_id, tr.genesis, j.Request("SLOT-INTENT", subject, op, actor), ctx, mailbox=mb,
               clock=lambda: at0)
n = sl.names(Path(root) / "s1_out", sl.slot_of(subject), day_iso)
n["claim"].parent.mkdir(parents=True, exist_ok=True)
n["claim"].write_text(json.dumps({"op": op, "actor": actor,
                                  "capture_dir": n["capture"].relative_to(Path(root) / "s1_out").as_posix()}))
(n["capture"]).mkdir(parents=True, exist_ok=True)
(n["capture"] / "meta.json").write_text("{}")                                    # an uncommitted partial capture
print(json.dumps({"op": op, "actor": actor, "outcome": res.outcome}), flush=True)
cmd = sys.stdin.readline().split()                    # "complete <R> <now>": a stalled worker wakes up after D
if cmd:
    r_at, now_ = c.aware(cmd[1]), c.aware(cmd[2])
    res = j.append(tr.trial_id, tr.genesis, j.Request("SLOT-QUALIFIED", subject, op, actor, detail="1" * 64,
                                                      r_at=r_at), ctx, mailbox=mb, clock=lambda: now_)
    print(json.dumps({"outcome": res.outcome, "reason": res.reason}), flush=True)
sys.stdin.readline()                                  # stays alive (lock held) until the test closes stdin
'''


def live_worker(tmp_path, st_, day, sch):
    cal_p = tmp_path / "cal.json"
    cal_p.write_text(json.dumps(st_["calendar"]), encoding="utf-8")
    p = subprocess.Popen([sys.executable, "-I", "-c", LIVE_WORKER, str(HERE), str(tmp_path), j.slot_subject(sch),
                          str(cal_p), (sch + timedelta(seconds=1)).isoformat(), day["date"]],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    hello = json.loads(p.stdout.readline())
    assert hello["outcome"] == "APPEND"
    return p, hello


def test_timeout_commits_at_d_while_a_live_worker_holds_the_work_lock(tmp_path):       # rows 256, 320
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    e, d = E_D(st_, day, sch)
    p, hello = live_worker(tmp_path, st_, day, sch)
    try:
        fin(tmp_path, st_, day, d)
        got = slot_rows(tmp_path, sch)
        assert [k_ for k_, *_ in got] == ["SLOT-INTENT", "SLOT-TIMEOUT"]
        assert got[1][1] == hello["op"] and got[1][2] != hello["actor"]
        assert p.poll() is None                                        # the worker is still alive and holds the lock
        assert all(x.kind != "TRIAL-INVALID" for x in rows(tmp_path))
    finally:
        p.stdin.close()
        p.wait(timeout=30)


@pytest.mark.parametrize("case", ["late-r", "early-r"])
def test_live_worker_after_timeout_is_refuse_or_lost_race_and_its_files_stay(tmp_path, case):  # rows 257, 321
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    e, d = E_D(st_, day, sch)
    out = tmp_path / "s1_out"
    n = sl.names(out, sch, day["date"])
    p, hello = live_worker(tmp_path, st_, day, sch)
    try:
        res = fin(tmp_path, st_, day, d)                                # TIMEOUT first; cleanup deferred
        assert "deferred" in str(res.get("cleanup"))
        r_at = d if case == "late-r" else d - timedelta(microseconds=1)
        p.stdin.write(f"complete {r_at.isoformat()} {(d + timedelta(seconds=1)).isoformat()}\n")
        p.stdin.flush()
        said = json.loads(p.stdout.readline())
        assert said["outcome"] == ("REFUSE" if case == "late-r" else "LOST-RACE")
        assert [k_ for k_, *_ in slot_rows(tmp_path, sch)] == ["SLOT-INTENT", "SLOT-TIMEOUT"]   # TIMEOUT stands
        assert n["claim"].exists() and (n["capture"] / "meta.json").exists()      # not moved while it lives
        assert not (out / "seals" / f"{day['date']}.json").exists()
        assert all(x.kind != "TRIAL-INVALID" for x in rows(tmp_path))
    finally:
        p.stdin.close()
        p.wait(timeout=30)
    res = fin(tmp_path, st_, day, d + timedelta(seconds=2))           # worker gone: the deferred cleanup runs
    assert not n["claim"].exists() and (out / "late" / day["date"] / f"{sch:%Y%m%dT%H%M%SZ}").is_dir()


def test_finalizer_decision_never_touches_the_work_lock(tmp_path, monkeypatch):       # row 258 (E1.2)
    st_ = registered(tmp_path)
    day, s_t = first_slot(st_, 45)
    _, s_m = first_slot(st_, 47)
    e_t, d_t = E_D(st_, day, s_t)
    s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(s_t), at=s_t + timedelta(seconds=1))
    events = []
    real_acq, real_app = sl.L.OwnershipLock.acquire, j.append

    def acq(self):
        events.append(("lock", self.path.stem))
        return real_acq(self)

    def app(trial_id, gen, req, ctx_fn, **kw):
        res = real_app(trial_id, gen, req, ctx_fn, **kw)
        events.append(("append", req.kind, res.outcome))
        return res
    monkeypatch.setattr(sl.L.OwnershipLock, "acquire", acq)
    monkeypatch.setattr(j, "append", app)
    fin(tmp_path, st_, day, d_t)                                    # s_t -> TIMEOUT, s_m (no INTENT) -> MISSED
    decided = [i for i, ev in enumerate(events) if ev[0] == "append" and ev[1] in ("SLOT-TIMEOUT", "SLOT-MISSED")]
    assert decided
    assert not any(ev[0] == "lock" and ev[1].startswith("slot-") for ev in events[:decided[-1] + 1])


def test_timeout_cleanup_waits_for_the_work_lock(tmp_path):                         # row 259 (E1.4, OQ-13)
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    e, d = E_D(st_, day, sch)
    n = sl.names(tmp_path / "s1_out", sch, day["date"])
    p, _ = live_worker(tmp_path, st_, day, sch)
    try:
        res = fin(tmp_path, st_, day, d)
        kinds_held = [k_ for k_, *_ in slot_rows(tmp_path, sch)]
        assert "deferred" in str(res.get("cleanup")) and n["claim"].exists()
    finally:
        p.stdin.close()
        p.wait(timeout=30)
    res = fin(tmp_path, st_, day, d + timedelta(seconds=1))
    assert [k_ for k_, *_ in slot_rows(tmp_path, sch)] == kinds_held               # cleanup decides nothing
    assert not n["claim"].exists() and sl.slot_problems(tmp_path / "s1_out", rows(tmp_path), j.slot_subject(sch),
                                                         st_["calendar"]) == []


# ---------------------------------------------------------------- E2 (rows 55, 260-263, 265, 323-325): PLAN-2
def _stop_row(tmp_path, at):
    return s1_jappend(tmp_path, "TRIAL-STOP", "trial", detail="5" * 64, at=at)


def test_no_seal_after_stop_even_for_a_pre_stop_qualified(tmp_path):                  # rows 55, 260, 323
    st_ = registered(tmp_path)
    day, s1_ = first_slot(st_, 45)
    _, s2 = first_slot(st_, 47)
    s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(s1_), at=s1_ + timedelta(seconds=1))   # earlier in flight
    run(tmp_path, st_, s2, s2 + timedelta(seconds=30))             # s2 QUALIFIED; its seal waits for s1
    seal = tmp_path / "s1_out" / "seals" / f"{day['date']}.json"
    assert not seal.exists()
    _stop_row(tmp_path, s2 + timedelta(minutes=1))                 # STOP (synthetic) before s1 is terminal
    e1, d1 = E_D(st_, day, s1_)
    res = fin(tmp_path, st_, day, d1)                               # s1 TIMEOUT: s2 is now the first QUALIFIED
    assert [k_ for k_, *_ in slot_rows(tmp_path, s1_)] == ["SLOT-INTENT", "SLOT-TIMEOUT"]
    assert not seal.exists() and "STOPPED" in str(res["refused"])  # E2.1: never published outside ACTIVE


HOLD_STOP = r'''
import sys
sys.path.insert(0, sys.argv[1])
import s1_locks
try:
    s1_locks.OwnershipLock(sys.argv[2], sys.argv[3], "stop").acquire()
    print("acquired", flush=True)
except s1_locks.LockHeld:
    print("held", flush=True)
    sys.exit(0)
sys.stdin.readline()
'''


@pytest.mark.parametrize("order", ["publish-first", "stop-first"])
def test_seal_publication_and_stop_race(tmp_path, order):                              # rows 261, 262, 324
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    seal = tmp_path / "s1_out" / "seals" / f"{day['date']}.json"
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    stop_child = [sys.executable, "-I", "-c", HOLD_STOP, str(HERE), str(tmp_path), tr.trial_id]
    if order == "publish-first":
        seen = []

        def before_seal():                                          # runs while the publisher holds the stop lock
            p = subprocess.run(stop_child, input="", capture_output=True, text=True, timeout=60)
            seen.append(p.stdout.strip())
        gv = t.gate(tmp_path, "race")
        run(tmp_path, st_, sch, sch + timedelta(seconds=30))        # QUALIFIED; seal published by the worker path
        assert seal.exists()
        seal.unlink()                                               # (not yet required: no committed report lists it)
        with _Clock(sch + timedelta(minutes=1)):
            sl.finalize_close(gv, day, st_["calendar"], lambda: sch + timedelta(minutes=1),
                              mailbox=tmp_path / "mailbox.sqlite3", before_seal=before_seal)
        assert seen == ["held"] and seal.exists()                   # the STOP side had to wait
        _stop_row(tmp_path, sch + timedelta(minutes=2))
        assert rows(tmp_path)[-1].kind == "TRIAL-STOP"
    else:
        _, s2 = first_slot(st_, 47)
        s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(sch), at=sch + timedelta(seconds=1))   # earlier in flight
        run(tmp_path, st_, s2, s2 + timedelta(seconds=30))         # s2 QUALIFIED; its seal waits for sch
        d1 = E_D(st_, day, sch)[1]
        p = subprocess.Popen(stop_child, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            assert p.stdout.readline().strip() == "acquired"        # the STOP side holds the stop lock
            res = fin(tmp_path, st_, day, d1)                       # TIMEOUT for sch; publication deferred
            assert "stop lock is held" in str(res["deferred"]) and not seal.exists()
            _stop_row(tmp_path, d1 + timedelta(seconds=1))           # ... the STOP commits under its lock
        finally:
            p.stdin.close()
            p.wait(timeout=30)
        res = fin(tmp_path, st_, day, d1 + timedelta(seconds=2))   # now STOPPED: never published
        assert not seal.exists() and "outside ACTIVE" in str(res["refused"])


def test_missing_required_seal_after_stop_is_invalid(tmp_path, monkeypatch):          # rows 263, 325
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    _, later = first_slot(st_, 47)
    run(tmp_path, st_, sch, sch + timedelta(seconds=30))            # QUALIFIED + seal published
    seal = tmp_path / "s1_out" / "seals" / f"{day['date']}.json"
    assert seal.exists()
    run(tmp_path, st_, later, later + timedelta(seconds=30))        # its committed report lists the seal
    _stop_row(tmp_path, later + timedelta(minutes=1))
    seal.unlink()                                                   # the TEST deletes its tmp seal
    sp = Spies(monkeypatch)
    with pytest.raises(SystemExit, match="INVALID"):
        t.gate(tmp_path, "required seal missing")
    sp.assert_zero()
    assert rows(tmp_path)[-1].subject == "reason/registration-artifact" and not seal.exists()


def test_previously_required_seal_deleted_is_invalid_and_never_recreated(tmp_path):   # row 265 (E2.4)
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    _, later = first_slot(st_, 47)
    run(tmp_path, st_, sch, sch + timedelta(seconds=30))
    run(tmp_path, st_, later, later + timedelta(seconds=30))        # later report: seals_checked lists the seal
    seal = tmp_path / "s1_out" / "seals" / f"{day['date']}.json"
    rel = seal.relative_to(tmp_path / "s1_out").as_posix()
    assert rel in sl.required_seals(tmp_path / "s1_out", rows(tmp_path), st_["calendar"])
    seal.unlink()
    with pytest.raises(SystemExit, match="INVALID"):
        fin(tmp_path, st_, day, later + timedelta(minutes=1))       # the finalizer's gate catches it first
    assert not seal.exists()


def test_late_r_refuses_with_no_row_then_timeout(tmp_path, monkeypatch):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    e, d = E_D(st_, day, sch)
    real = sl.Worker.complete

    def late(self, rep, success):
        self.now = lambda: d                                         # R = D (late)
        return real(self, rep, success)
    monkeypatch.setattr(sl.Worker, "complete", late)
    res = run(tmp_path, st_, sch, sch + timedelta(seconds=30))
    assert res["journal"]["outcome"] == "REFUSE" and [k_ for k_, *_ in slot_rows(tmp_path, sch)] == ["SLOT-INTENT"]
    monkeypatch.setattr(sl.Worker, "complete", real)        # (never monkeypatch.undo(): it would drop the guards)
    fin(tmp_path, st_, day, d)
    assert [k_ for k_, *_ in slot_rows(tmp_path, sch)] == ["SLOT-INTENT", "SLOT-TIMEOUT"]
    late_dir = tmp_path / "s1_out" / "late" / day["date"] / f"{sch:%Y%m%dT%H%M%SZ}"
    assert late_dir.is_dir()                                         # OQ-13: leftovers moved by the finalizer


def test_stale_finalizer_moves_none_of_the_winners_files_and_the_recheck_passes(tmp_path):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    e, d = E_D(st_, day, sch)
    run(tmp_path, st_, sch, sch + timedelta(seconds=30))
    before = sorted(p.relative_to(tmp_path) for p in (tmp_path / "s1_out" / "captures").rglob("*") if p.is_file())
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    intent = j.first(j.subject_rows(rows(tmp_path), j.slot_subject(sch)), "SLOT-INTENT")
    res = j.append(tr.trial_id, tr.genesis, j.Request("SLOT-TIMEOUT", j.slot_subject(sch), intent.op, j.new_nonce()),
                   t.product_context(tr, st_["calendar"]), mailbox=tmp_path / "mailbox.sqlite3", clock=lambda: d)
    assert res.outcome == "LOST-RACE"
    assert sl.move_leftovers(tmp_path / "s1_out", sch, day["date"], intent.op) == []
    after = sorted(p.relative_to(tmp_path) for p in (tmp_path / "s1_out" / "captures").rglob("*") if p.is_file())
    assert before == after and sl.slot_problems(tmp_path / "s1_out", rows(tmp_path), j.slot_subject(sch),
                                                st_["calendar"]) == []


def _put(p: Path, text="{}"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _evidence_case(tmp_path, st_, case):
    """Set up one F3 evidence-table case; returns the expected verdict ('ok' or 'invalid')."""
    day, sch = first_slot(st_)
    out = tmp_path / "s1_out"
    n = sl.names(out, sch, day["date"])
    e, d = E_D(st_, day, sch)
    sub = j.slot_subject(sch)
    if case == "no-row-clean":
        return "ok"
    if case == "no-row-stray-claim":
        _put(n["claim"], json.dumps({"op": "9" * 32, "actor": "9" * 32}))
        return "invalid"
    if case == "no-row-stray-capture":
        _put(n["capture"] / "meta.json")
        return "invalid"
    if case.startswith("in-flight"):
        row = s1_jappend(tmp_path, "SLOT-INTENT", sub, at=sch + timedelta(seconds=1))
        who = (row.op, row.actor) if case != "in-flight-foreign-op" else ("8" * 32, "8" * 32)
        cap_rel = n["capture"].relative_to(out).as_posix()
        named = cap_rel if case != "in-flight-capture-dir-not-named-by-claim" else cap_rel + "-other"
        _put(n["claim"], json.dumps({"op": who[0], "actor": who[1], "capture_dir": named}))
        _put(n["capture"] / "meta.json")                                # a partial capture
        return "ok" if case == "in-flight-own-partial" else "invalid"   # row 311 (OQ-10 ruling)
    if case.startswith("qualified") or case.startswith("failed"):
        if case.startswith("failed"):
            run(tmp_path, st_, sch, sch - timedelta(seconds=5))       # early: FAILED
        else:
            run(tmp_path, st_, sch, sch + timedelta(seconds=30))
        if case in ("qualified-ok", "failed-ok"):
            return "ok"
        if case == "qualified-missing":
            (n["capture"] / "projection.json").unlink()
        elif case == "qualified-changed":
            n["report"].write_text(n["report"].read_text(encoding="utf-8") + " ", encoding="utf-8")
        elif case == "qualified-unparseable":
            n["resolution"].write_text("{not JSON", encoding="utf-8")
        elif case == "qualified-late-extra":
            _put(out / "late" / day["date"] / "extra.json")
            return "ok"
        elif case == "qualified-backup-changed":                       # row 267 (E5.6)
            with open(n["capture"] / "backup.sqlite3", "ab") as f:
                f.write(b"\0")
        elif case == "qualified-backup-deleted":
            (n["capture"] / "backup.sqlite3").unlink()
        elif case == "failed-report-changed":
            n["report"].write_text("{}", encoding="utf-8")
        elif case == "failed-partial-capture":
            _put(n["capture"] / "partial.bin", "x")
            return "ok"
        return "invalid"
    if case.startswith("timeout"):
        row = s1_jappend(tmp_path, "SLOT-INTENT", sub, at=sch + timedelta(seconds=1))
        _put(n["claim"], json.dumps({"op": row.op, "actor": row.actor}))      # a dead worker's own partial file
        fin(tmp_path, st_, day, d)
        if case == "timeout-leftovers":
            return "ok"
        _put(out / "seals" / f"{day['date']}.json", json.dumps({"capture": {"scheduled": sch.isoformat()}}))
        return "invalid"
    if case.startswith("missed"):
        fin(tmp_path, st_, day, e)
        if case == "missed-stray":
            _put(n["report"])
            return "invalid"
        return "ok"
    raise AssertionError(case)


CASES = ["no-row-clean", "no-row-stray-claim", "no-row-stray-capture", "in-flight-own-partial", "in-flight-foreign-op",
         "in-flight-capture-dir-not-named-by-claim",
         "qualified-ok", "qualified-missing", "qualified-changed", "qualified-unparseable", "qualified-late-extra",
         "qualified-backup-changed", "qualified-backup-deleted",
         "failed-ok", "failed-report-changed", "failed-partial-capture", "timeout-leftovers", "timeout-seal-cites",
         "missed-clean", "missed-stray"]


@pytest.mark.parametrize("case", CASES)
def test_slot_evidence_table(tmp_path, monkeypatch, case):
    st_ = registered(tmp_path)
    want = _evidence_case(tmp_path, st_, case)
    sp = Spies(monkeypatch)
    if want == "ok":
        t.gate(tmp_path, "evidence table")
        return
    with pytest.raises(SystemExit, match="INVALID"):
        t.gate(tmp_path, "evidence table")
    sp.assert_zero()
    assert rows(tmp_path)[-1].subject == "reason/registration-artifact"


def test_seal_from_the_first_qualified_slot_in_schedule_order_after_earlier_slots_terminal(tmp_path):
    st_ = registered(tmp_path)
    day, s1_ = first_slot(st_, 45)
    _, s2 = first_slot(st_, 47)
    s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(s1_), at=s1_ + timedelta(seconds=1))   # earlier slot in flight
    run(tmp_path, st_, s2, s2 + timedelta(seconds=30))                                          # later slot QUALIFIED
    assert not (tmp_path / "s1_out" / "seals" / f"{day['date']}.json").exists()
    e1, d1 = E_D(st_, day, s1_)
    fin(tmp_path, st_, day, d1)                                     # earlier slot TIMEOUT -> later slot seals
    seal = tmp_path / "s1_out" / "seals" / f"{day['date']}.json"
    assert seal.exists() and json.loads(seal.read_text(encoding="utf-8"))["capture"]["scheduled"] == s2.isoformat()


def test_late_files_are_never_selectable_for_a_seal(tmp_path, monkeypatch):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    out = tmp_path / "s1_out"
    late = out / "late" / day["date"] / f"{sch:%Y%m%dT%H%M%SZ}"
    _put(late / f"{sch:%Y%m%dT%H%M%SZ}.resolution.json", json.dumps({"outcome": "SUCCESS"}))
    e, d = E_D(st_, day, sch)
    fin(tmp_path, st_, day, e)
    assert not (out / "seals" / f"{day['date']}.json").exists() and \
        [k_ for k_, *_ in slot_rows(tmp_path, sch)] == ["SLOT-MISSED"]


def test_finalizer_unexpected_error_appends_nothing(tmp_path, monkeypatch):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    e, d = E_D(st_, day, sch)
    monkeypatch.setattr(sl, "slot_times", lambda cal: (_ for _ in ()).throw(RuntimeError("unexpected")))
    with pytest.raises(SystemExit, match="refused with no row"):
        fin(tmp_path, st_, day, e)
    assert slot_rows(tmp_path, sch) == []
```

Append to `test_s1_a3_codex_probes.py` (the P/R/J/T races, F10 CH2):

```python
from test_s1_a3_slots import first_slot, registered, rows as journal_rows, run as run_slot, slot_rows


def _fin(tmp_path, st_, day, at):
    gv = t.gate(tmp_path, "probe finalizer")
    with _Clock(at):
        return sl.finalize_close(gv, day, st_["calendar"], lambda: at, mailbox=tmp_path / "mailbox.sqlite3")


def test_race_t_commits_then_j_is_lost_race(tmp_path, monkeypatch):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    d = z.resolution_deadline(sch, day, st_["calendar"])
    real = sl.Worker._append

    def t_first(self, req):
        if req.kind == "SLOT-QUALIFIED":
            intent = j.first(j.subject_rows(journal_rows(tmp_path), self.subject), "SLOT-INTENT")
            s1_jappend(tmp_path, "SLOT-TIMEOUT", self.subject, op=intent.op, at=d)
        return real(self, req)
    monkeypatch.setattr(sl.Worker, "_append", t_first)
    res = run_slot(tmp_path, st_, sch, sch + timedelta(seconds=30))
    assert res["journal"]["outcome"] == "LOST-RACE"
    assert [k_ for k_, *_ in slot_rows(tmp_path, sch)] == ["SLOT-INTENT", "SLOT-TIMEOUT"]
    assert not (tmp_path / "s1_out" / "seals" / f"{day['date']}.json").exists()
    assert all(x.kind != "TRIAL-INVALID" for x in journal_rows(tmp_path))


def test_race_j_commits_then_stale_t_is_lost_race(tmp_path):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    run_slot(tmp_path, st_, sch, sch + timedelta(seconds=30))
    _fin(tmp_path, st_, day, z.resolution_deadline(sch, day, st_["calendar"]))
    assert [k_ for k_, *_ in slot_rows(tmp_path, sch)] == ["SLOT-INTENT", "SLOT-QUALIFIED"]


FINALIZE = r'''
import sys
sys.path.insert(0, sys.argv[1])
import s1_common as c, s1_slot as sl, s1_trial as t
c.MAILBOX = sys.argv[2] + "/mailbox.sqlite3"
at = c.aware(sys.argv[3]); c.now_utc = lambda: at
import json
cal = json.loads(open(sys.argv[4], encoding="utf-8").read())
day = next(d for d in cal if d["date"] == sys.argv[5])
gv = t.gate(sys.argv[2], "child finalizer")
print(json.dumps(sl.finalize_close(gv, day, cal, lambda: at, mailbox=c.MAILBOX), default=str), flush=True)
'''


def test_race_two_finalizers_one_terminal(tmp_path):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    d = z.resolution_deadline(sch, day, st_["calendar"])
    s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(sch), at=sch + timedelta(seconds=1))
    cal_p = tmp_path / "cal.json"
    cal_p.write_text(json.dumps(st_["calendar"]), encoding="utf-8")
    args = [sys.executable, "-I", "-c", FINALIZE, str(Path(c.HERE)), str(tmp_path), d.isoformat(), str(cal_p),
            day["date"]]
    procs = [subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    for p in procs:
        p.wait(timeout=120)
    kinds_ = [k_ for k_, *_ in slot_rows(tmp_path, sch)]
    assert kinds_.count("SLOT-TIMEOUT") == 1 and kinds_[0] == "SLOT-INTENT"


CRASH = r'''
import os, sys
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[1] + "/s1_tests")
import s1_common as c, s1_checkpoint as ck, s1_journal as j
c.MAILBOX = sys.argv[2] + "/mailbox.sqlite3"
at = c.aware(sys.argv[4]); c.now_utc = lambda: at
real = j.append
def crash(trial_id, gen, req, ctx_fn, **kw):
    if req.kind == "SLOT-QUALIFIED":
        os._exit(9)
    return real(trial_id, gen, req, ctx_fn, **kw)
j.append = crash
from conftest import S1_RECEIPT, S1_PROCESS
ck.run_checkpoint(sys.argv[2], sys.argv[3], c.aware(sys.argv[5]), lambda reference=None: S1_RECEIPT,
                  lambda: dict(S1_PROCESS), sys.argv[2] + "/crash.log", now=lambda: at)
'''


def test_race_p_without_j_restart_ends_in_timeout(tmp_path):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    at = sch + timedelta(seconds=30)
    p = subprocess.run([sys.executable, "-I", "-c", CRASH, str(Path(c.HERE)), str(tmp_path), str(st_["ledger"].path),
                        at.isoformat(), sch.isoformat()], capture_output=True, text=True, timeout=120)
    assert p.returncode == 9, p.stderr
    with pytest.raises(SystemExit, match="never re-intents"):
        run_slot(tmp_path, st_, sch, at + timedelta(seconds=30))
    _fin(tmp_path, st_, day, z.resolution_deadline(sch, day, st_["calendar"]))
    assert [k_ for k_, *_ in slot_rows(tmp_path, sch)] == ["SLOT-INTENT", "SLOT-TIMEOUT"]
```

- [ ] **Step 3: Behavioural RED.** Run the finalizer tests and the race probes into `a3/t7_red.txt`.
  - Expected: the legacy finalizer appends no MISSED/TIMEOUT rows and writes MISSED/RESOLUTION-TIMEOUT files; the
    evidence-table violations are not detected (no INVALID); the seal is selected without "earlier slots
    terminal"; there are no leftovers moves.
  - `test_race_j_commits_then_stale_t…` passes (the QUALIFIED already exists and the legacy finalizer adds no
    rows). Label it `ctrl`.
  - Revision 1 rows:
    - 256, 257, 259 and 321 fail (no TIMEOUT row; the legacy finalizer writes files);
    - 258 fails on the Step 1 stub only if the stub locks. Make the stub's `finalize_close` take the slot lock
      around its legacy call, as revision 0 did, so that row 258 has a genuine RED;
    - 260 and 262 fail (the legacy finalizer seals in STOPPED);
    - 261 fails (no stop lock: the child acquires, so `seen == ["acquired"]`);
    - 263 and 265 fail (no required-seal check);
    - 267 and 311 fail (backup not in the tree; no capture_dir check).
  - Record the RED of each in `a3/t7_red.txt` with its failing assertion.

- [ ] **Step 4: Implement.** In `s1_slot.py`, add:

```python
def first_qualified(rows, day, cal):
    """F3/OQ-14: walking the close's slots in schedule order, the first QUALIFIED one, provided every earlier slot
    is terminal (QUALIFIED, FAILED, TIMEOUT, MISSED); None otherwise. late/ files are never consulted."""
    for slot in z.schedule(day, cal):
        mine = j.subject_rows(rows, j.slot_subject(slot))
        term = j.first(mine, *j.TERMINAL)
        if term is None:
            return None
        if term.kind == "SLOT-QUALIFIED":
            return term
    return None


def seal_bytes(day, close, ev) -> bytes:
    """The deterministic seal of a close from the SUCCESS evidence (moved unchanged from s1_checkpoint._seal_bytes)."""
    cand = ev["candidate"]
    cap_dir = Path(cand["dir"])
    proj_p = cap_dir / "projection.json"
    if not proj_p.is_file() or c.sha256_file(proj_p) != cand["projection_sha256"]:
        raise ValueError(f"candidate capture {cap_dir.name} differs from its recorded projection")
    proj = json.loads(proj_p.read_text(encoding="utf-8"))
    cap = {"scheduled": ev["scheduled"], "actual": ev["actual"], "capture_start": cand["capture_start"],
           "capture_end": cand["capture_end"], "ok": True, "consistent": True,
           "projection_sha256": cand["projection_sha256"], "dir": cand["dir"]}
    seal = {"close": close.isoformat(), "fence": z.fence(proj), "max_id": cand["max_id"], "trades": proj["trades"],
            "capture": cap, "restart_record": cand["restart_record"], "process": cand["process"],
            "process_binding": cand["process_binding"], "receipt_sha256": cand["receipt_sha256"],
            "receipt_match": True, "receipt_provenance": cand["receipt_provenance"],
            "bundle_sha256": cand["bundle_sha256"]}
    if cand.get("bridge") is not None:
        seal["bridge"] = cand["bridge"]
    return json.dumps(seal).encode("utf-8")


def move_leftovers(out, slot, day_iso, op, *, root=None, trial_id=None) -> list:
    """OQ-13 as amended by E1.4: after a committed TIMEOUT, move the losing op's uncommitted files to
    late/<day>/<slot>/ ONLY when the slot work lock is acquirable (the worker is gone). While it is held the cleanup
    is deferred (returns None). Cleanup never decides anything; leftovers on a TIMEOUT slot are tolerated and never
    selectable either way (F3 table)."""
    if root is not None and not L.lock_acquirable(root, trial_id, L.slot_lock_name(j.slot_subject(slot))):
        return None                                                               # deferred: a live worker
    out, n = Path(out), names(out, slot, day_iso)
    claim_op = None
    try:
        claim_op = json.loads(n["claim"].read_text(encoding="utf-8")).get("op")
    except (OSError, ValueError, AttributeError):
        pass
    dest = out / "late" / day_iso / slot.strftime("%Y%m%dT%H%M%SZ")
    moved = []
    for key in ("resolution", "report", "claim", "capture"):
        p = n[key]
        if not p.exists():
            continue
        try:
            rec_op = claim_op if key == "capture" else json.loads(p.read_text(encoding="utf-8")).get("op")
        except (OSError, ValueError, AttributeError):
            rec_op = None
        if rec_op == op:
            try:
                dest.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), str(dest / p.name))
                moved.append(_rel(out, p))
            except OSError:
                pass
    return moved


def _finalizer_append(gv, cal, req, mailbox, now):
    import s1_trial
    return j.append(gv.trial.trial_id, gv.trial.genesis, req, s1_trial.product_context(gv.trial, cal),
                    mailbox=mailbox, clock=now)


def finalize_close(gv, day, cal, now, *, mailbox=None, before_seal=None, before_build=None) -> dict:
    """F3 finalizer + the E2 seal publication, in schedule order over the JOURNAL.
    E1 (PLAN-1): terminal decisions are arbitrated by the journal transaction alone. Per slot: no row and now >= E ->
    SLOT-MISSED (own op); INTENT, no terminal and now >= D -> SLOT-TIMEOUT (the INTENT's op, own actor). Neither
    takes, waits for or tests the slot work lock, so a live stalled worker never prevents TIMEOUT at D. After a
    committed TIMEOUT, leftover cleanup runs only if the work lock is acquirable (E1.4), else it is deferred.
    E2 (PLAN-2): the close's seal (its first QUALIFIED slot with every earlier slot terminal) is published only while
    the trial is ACTIVE, under the stop lock: read state, publish, re-read state. A held stop lock defers the
    publication (no seal); in STOPPED/INVALID/CLOSED nothing is ever published, whatever the QUALIFIED's seq.
    Any unexpected error refuses with no row (F0.7)."""
    res = {"written": False, "sha256": None, "from_slot": None, "deferred": None, "refused": None, "cleanup": None}
    out = gv.out
    try:
        times = slot_times(cal)
        actor = j.new_nonce()
        for slot in z.schedule(day, cal):
            sub = j.slot_subject(slot)
            e, d = times(sub)
            mine = j.subject_rows(j.read_trial(gv.trial.trial_id, gv.trial.genesis, mailbox), sub)
            term = j.first(mine, *j.TERMINAL)
            if term is not None:                     # every slot is finalized, also after the first QUALIFIED one:
                if term.kind == "SLOT-TIMEOUT":      # F7.2(b) literal needs every opening-close slot terminal
                    res["cleanup"] = _cleanup(gv, slot, day, term) or res["cleanup"]
                continue
            t_ = now()
            intent = j.first(mine, "SLOT-INTENT")
            if (intent is None and t_ < e) or (intent is not None and t_ < d):
                res["deferred"] = f"{sub}: waiting for {'E' if intent is None else 'D'} (slot order)"
                break                                # later slots wait; the seal step below still runs
            req = (j.Request("SLOT-MISSED", sub, j.new_nonce(), actor) if intent is None
                   else j.Request("SLOT-TIMEOUT", sub, intent.op, actor))
            got = _finalizer_append(gv, cal, req, mailbox, now)                  # E1.2: no work lock here
            if got.outcome == "INVALIDATE":
                raise SystemExit(f"{sub}: {req.kind} -> INVALID ({got.reason})")
            if got.outcome == "REFUSE":
                res["deferred"] = f"{sub}: {req.kind} refused with no row ({got.reason})"
                break
            if req.kind == "SLOT-TIMEOUT" and got.outcome == "APPEND":
                res["cleanup"] = _cleanup(gv, slot, day, got.row)
        return publish_seal(gv, day, cal, res, mailbox=mailbox, before_seal=before_seal)
    except Exception as e:                       # noqa: BLE001 - F0.7: unexpected errors fail closed, no row
        raise SystemExit(f"finalizer refused with no row ({type(e).__name__}: {e}) (F0.7)") from None


def _cleanup(gv, slot, day, timeout_row):
    """E1.4: the leftovers of the TIMEOUT's (losing) op, moved only when the work lock is acquirable."""
    moved = move_leftovers(gv.out, slot, day["date"], timeout_row.op, root=gv.root, trial_id=gv.trial.trial_id)
    if moved is None:
        return f"{timeout_row.subject}: cleanup deferred - the slot work lock is held (E1.4)"
    return {"moved": moved} if moved else None


def publish_seal(gv, day, cal, res, *, mailbox=None, before_seal=None, stop_lock_held=False) -> dict:
    """E2.3-E2.6 (Erratum 1 r1): the only seal publisher (the finalizer and the stop operation both call it). Under
    the stop lock (non-blocking: held -> no change, pending, E2.6): read the journal; publish a DETERMINED seal only
    while ACTIVE, with exactly its recomputed bytes, and never a missing published-committed one (E2.4); re-read; a
    state change between the reads is impossible under the lock and is a refusal if seen.
    `stop_lock_held=True` is passed only by decide_stop, which already holds the stop lock (Task 11)."""
    out = gv.out
    rows = j.read_trial(gv.trial.trial_id, gv.trial.genesis, mailbox)
    q = first_qualified(rows, day, cal)
    if q is None:
        return res
    if day["date"] == _opening_date(out):
        res["deferred"] = "the opening close is sealed by the opening stage (Task 10)"
        return res
    lk = None
    if not stop_lock_held:
        try:
            lk = L.OwnershipLock(gv.root, gv.trial.trial_id, L.STOP_LOCK).acquire()
        except L.LockHeld:
            res["deferred"] = "pending: the stop lock is held; no change, retried on the next run (E2.6)"
            return res
    try:
        import s1_trial
        rows = j.read_trial(gv.trial.trial_id, gv.trial.genesis, mailbox)
        try:
            st_ = s1_trial.state(s1_trial.open_trial(mailbox, root=gv.root), rows)
        except s1_trial.Refusal:
            st_ = "CLOSED-or-unavailable"                                          # fail closed: no publication
        if st_ != "ACTIVE":
            res["refused"] = f"trial {st_}: no seal is ever published outside ACTIVE (E2.1)"
            return res
        if before_seal is not None:
            before_seal()
        res = _write_post_start_seal(out, rows, q, day, cal, res)
        again = j.read_trial(gv.trial.trial_id, gv.trial.genesis, mailbox)
        if j.trial_state(again) != "ACTIVE":
            raise SystemExit("the trial left ACTIVE while the stop lock was held (E2.3): refuse")
        return res
    finally:
        if lk is not None:
            lk.release()


def _opening_date(out):
    try:
        return c.load_json(Path(out) / "plan.json").get("opening_close")
    except (OSError, ValueError, AttributeError):
        return None


def _resolution_evidence(out, q, day_iso) -> dict:
    s = slot_of(q.subject)
    if j.detail_of(qualified_tree(out, s, day_iso)) != q.detail:
        raise ValueError(f"{q.subject}: QUALIFIED tree differs from its committed detail")
    return json.loads(names(out, s, day_iso)["resolution"].read_text(encoding="utf-8"))["evidence"]


def _write_post_start_seal(out, rows, q, day, cal, res) -> dict:
    ev = _resolution_evidence(out, q, day["date"])
    data = seal_bytes(day, z.close_of(day["date"], cal), ev)
    p = Path(out) / "seals" / f"{day['date']}.json"
    if not p.exists() and _rel(out, p) in required_seals(out, rows, cal):
        raise ValueError(f"required seal {p.name} is missing: never recreated (E2.4)")
    try:
        c.publish_exclusive(p, data)
        res.update(written=True, sha256=c.sha256_bytes(data), from_slot=ev["scheduled"])
    except FileExistsError:
        if p.read_bytes() != data:
            raise ValueError(f"seal {p.name} differs from the one its first QUALIFIED slot gives (OQ-14)")
        res["sha256"] = c.sha256_bytes(data)
    return res


def slot_problems(out, rows, subject, cal) -> list:
    """The F3 evidence table for one slot subject (states from the journal; files as evidence)."""
    out, s = Path(out), slot_of(subject)
    try:
        day_iso = day_for(s, cal)["date"]
    except SystemExit:
        return [f"{subject}: not a registered slot"]
    n = names(out, s, day_iso)
    mine = j.subject_rows(rows, subject)
    intent, term = j.first(mine, "SLOT-INTENT"), j.first(mine, *j.TERMINAL)
    present = [k_ for k_ in ("claim", "report", "resolution", "capture") if n[k_].exists()]
    if not mine:
        return [f"{subject}: {k_} exists with no journal row" for k_ in present]
    if term is None:                                                              # in flight
        bad = []
        claim = None
        for k_ in present:
            if k_ == "capture":
                continue
            try:
                rec = json.loads(n[k_].read_text(encoding="utf-8"))
                ok = (rec.get("op"), rec.get("actor")) == (intent.op, intent.actor)
            except (OSError, ValueError, AttributeError):
                rec, ok = None, False
            if k_ == "claim" and ok:
                claim = rec
            if not ok:
                bad.append(f"{subject}: in-flight {k_} carries another op")
        if "capture" in present and (claim is None or claim.get("capture_dir") != _rel(out, n["capture"])):
            bad.append(f"{subject}: in-flight capture directory is not the one its claim names (OQ-10)")
        return bad
    if term.kind == "SLOT-QUALIFIED":
        try:
            ok = j.detail_of(qualified_tree(out, s, day_iso)) == term.detail
            json.loads(n["resolution"].read_text(encoding="utf-8"))
            json.loads(n["report"].read_text(encoding="utf-8"))
        except (OSError, ValueError):
            ok = False
        return [] if ok else [f"{subject}: QUALIFIED files missing, changed or unparseable"]
    if term.kind == "SLOT-FAILED":
        try:
            ok = j.detail_of(failed_tree(out, s, day_iso)) == term.detail
        except OSError:
            ok = False
        return [] if ok else [f"{subject}: FAILED claim/report missing or changed"]
    if term.kind == "SLOT-TIMEOUT":
        seal = out / "seals" / f"{day_iso}.json"
        try:
            cites = seal.is_file() and json.loads(seal.read_text(encoding="utf-8"))["capture"]["scheduled"] == \
                s.isoformat()
        except (OSError, ValueError, KeyError, TypeError):
            cites = False
        return [f"{subject}: a seal cites a TIMEOUT slot"] if cites else []
    return [f"{subject}: MISSED slot has {k_} outside late/" for k_ in present]                   # MISSED


def evidence_problems(out, rows, cal) -> list:
    """Every slot subject with rows, plus every captures/<day>/<slot>* file whose slot has no row; and every
    post-START seal that is not the recomputation from its first QUALIFIED slot (OQ-14)."""
    out = Path(out)
    subjects = {r_.subject for r_ in rows if r_.kind in j.SLOT_KINDS}
    for p in sorted((out / "captures").glob("*/*")):
        stem = p.name.split(".", 1)[0]
        if len(stem) == 16 and stem.endswith("Z"):
            subjects.add("slot/" + stem)
    probs = []
    for sub in sorted(subjects):
        probs += slot_problems(out, rows, sub, cal)
    oday = _opening_date(out)
    for seal in sorted((out / "seals").glob("*.json")):
        day_iso = seal.stem
        if day_iso == oday:
            continue                                                              # the opening stage (Task 10)
        day = next((d for d in cal if d["date"] == day_iso), None)
        q = first_qualified(rows, day, cal) if day is not None else None
        try:
            want = seal_bytes(day, z.close_of(day_iso, cal), _resolution_evidence(out, q, day_iso)) if q else None
        except (OSError, ValueError, KeyError):
            want = None
        if want is None or seal.read_bytes() != want:
            probs.append(f"seals/{seal.name} is not the seal of its first QUALIFIED slot (OQ-14)")
    for rel, sha in sorted(required_seals(out, rows, cal).items()):              # E2.2/E2.4: never recreated
        p = out / rel
        if not p.is_file() or c.sha256_file(p) != sha:
            probs.append(f"required seal {rel} is missing or differs from the committed record (E2.4)")
    return probs


def evidence_check(gv) -> None:
    """Gate hook (F3 table): a violation commits TRIAL-INVALID (registration-artifact) and refuses with no work."""
    import s1_trial
    try:
        cal = c.load_json(gv.out / "prereg.json")["calendar"]
    except (OSError, ValueError, KeyError, TypeError):
        try:
            import s1_gates
            cal = s1_gates.verified_audit(gv.out, gv.mailbox)["calendar"]
        except Exception:                               # noqa: BLE001 - no calendar yet: no slot can exist
            return
    probs = evidence_problems(gv.out, gv.rows, cal)
    if probs:
        s1_trial.invalidate(gv.trial, "registration-artifact", {"problems": probs}, root=gv.root,
                            mailbox=gv.mailbox)
        raise SystemExit(f"slot evidence violation {probs[:3]}: INVALID (registration-artifact)")
```

`s1_checkpoint`:
- `finalize_close(out, day, cal, t, before_seal=None, before_build=None, qualified=None)` becomes a thin wrapper:
  `return s1_slot.finalize_close(s1_trial.gate(out.parent, "finalize"), day, cal, lambda: t, before_seal=before_seal, before_build=before_build)`;
- `_finalize_others` and `finalize_pending` keep their loops over the wrapper;
- `_seal_bytes` and `_resolve` are deleted, and every caller uses `s1_slot.seal_bytes`;
- `_after_qualified` calls `s1_slot.finalize_close(gv, day, cal, now, mailbox=mailbox)`.

`s1_trial.gate`: insert `import s1_slot; s1_slot.evidence_check(Gate(root, out, tr, rows, st_, mailbox))` before the
plan check. The late import goes inside `gate`.

`conftest._write_seal` additionally does the following:
1. `s1_jappend(SLOT-INTENT)` for `sch` at `sch + 1 s`.
2. It writes the claim (with `capture_dir`), the resolution and the report JSON (with `seals_checked`) with that
   row's op and actor. The resolution's `evidence.candidate` holds the capture fields `seal_bytes` reads, the same
   dict the seal file is built from. The capture directory holds `backup.sqlite3` (a copy of the tmp ledger),
   `meta.json` and `projection.json`, so that `qualified_tree` covers the raw bytes (E5.6).
3. It writes the seal file as `s1_slot.seal_bytes(...)`, and not with `json.dumps(seal)` by hand.
4. `s1_jappend(SLOT-QUALIFIED, detail=j.detail_of(s1_slot.qualified_tree(out, sch, day)), r_at=sch + 31 s)`.

The written seal therefore equals the recomputation.

- [ ] **Step 5: GREEN.** Run the finalizer tests, the race probes and the earlier A3 files into `a3/t7_green.txt`.
  Run the child-process tests three times.
- [ ] **Step 6: Full suite, old->new.** Expected intended changes:
  - **B1.2/B1.4 -> F3:** MISSED/RESOLUTION-TIMEOUT resolution files are no longer written by finalizers. The
    selection reads journal rows. This affects `test_s1_t12_fix2_b1.py`, `test_s1_t12_fix5.py` (R-1
    `_finalizer_missed`), `test_s1_t12_fix3.py` (I-1 pending) and `test_s1_checkpoint.py`.
  - **`c.opening_orphans`:** a finalizer's MISSED record no longer exists. The `_finalizer_missed` exception is now
    vacuous. The existing orphan tests stay valid only where they create claims without rows; those now become
    F3 violations (INVALID) rather than legacy orphans. Classify each one.
  - **Hand-written-seal fixtures** in individual test files that bypass `conftest._write_seal` are fixture
    incompatibilities: migrate them to `_write_seal`.
  - **E1:** any existing test that expected a finalizer to defer ("pending") because a live owner held the slot lock
    now expects a TIMEOUT at D. List each one; the revision-0 test of that name is deleted (PLAN-1).
  - **E2:** any existing test that expected a seal written after a TRIAL-STOP (or the legacy A2.1 stop) for a
    pre-STOP QUALIFIED now expects no seal.

  Save `a3/t7_full.txt`, `a3/t7_old_new.md` and `a3/t7_hashes.txt`.
- [ ] **Step 7: Controller review and commit.** Message: `S1 A3 Task 7: journal finalizer, F3 evidence table,
  post-START seals from the first QUALIFIED slot; E1 deadline arbitration; E2 seal publication`, listing map rows
  12, 20, 45, 50, 55 (pre-STOP part), 72, 73, 75–80, 175, 187, 193–195, 198, 199, 205, 230, 256–263, 265, 267, 311
  and 320–325, with the Co-Authored-By line. Push and assert the HEAD SHA.

---

### Task 8: Stage engine: INTENT -> PREPARED -> CREATED, staging, recovery, the stage-state table (F4.1–F4.5, F4.7, the F4 stage table, F1 graph; C-a; OQ-35, OQ-36)

**Files:**
- Create: `research/s1/s1_stage.py`
- Modify: `research/s1/s1_trial.py:gate`. Add the hook `s1_stage.evaluate(gv)` before `s1_slot.evidence_check`.
- Modify: `research/s1/s1_common.py` BUNDLE_CODE (`s1_stage.py`); `test_s1_t12_a3_a8.py` BUNDLE tuple (old->new).
- Create: `research/s1/s1_tests/a3_helpers.py`. It holds the fake stage works and the child-process entry points. It is
  not a test module, and nothing in product code imports it.
- Create: `research/s1/s1_tests/test_s1_a3_stage.py`

**Interfaces:**
- Consumes: Task 1/2 (`append`, `stage_subject`, `first`, `subject_rows`, `trial_state`); Task 3 (`OwnershipLock`,
  `stage_lock_name`, `LockHeld`, `LockError`); Task 5 (`Gate`, `product_context`, `invalidate`).
- Produces (`s1_stage`):
  - `TABLE: dict[stage, {"kind", "pred", "ack", "state"}]`;
  - `FIXED_TREE: dict[stage, tuple[str, ...]]` (F4.9 fixed members);
  - `SINGLE: dict[stage, Callable[[Path], str]]` (the one relpath of a single stage);
  - `MANIFEST_STAGES = ("audit", "final")`;
  - `TRIAL_ID_MEMBERS: dict[stage, tuple[str, ...]]` (OQ-36);
  - `ENFORCED: frozenset[str]` (transitional; `frozenset()` in Task 8; Tasks 9–13 add their stage; Task 14 asserts
    it equals `frozenset(TABLE)`);
  - `class StageAbort(Exception)` (fields `reason`, `record`);
  - `class StageWork` (fields gv, stage, staging, intent, policy, op, actor, mailbox, clock; properties `intent_at`
    and `trial_id`; methods `put(rel, data: bytes) -> Path` and `put_json(rel, obj) -> Path`);
  - `envelope(trial_id, stage, inputs, acks, policy) -> dict`;
  - `commitment(trial_id, stage, op, kind, members, provenance, seals_checked) -> dict` (E2.4 r1: `seals_checked`
    = `s1_slot.seals_checked(out)` at PREPARED time);
  - `committed_commitment(root, trial_id, stage, rows) -> dict`: the staging `prepared.json`, verified against its
    PREPARED row's detail in the caller's (verified) `rows` (`ValueError` otherwise). Body:
    `m = stage_rows(rows, stage)`; `p = staging_dir(root, trial_id, stage) / "prepared.json"`;
    `if m["prepared"] is None or c.sha256_file(p) != m["prepared"].detail: raise ValueError(...)`;
    `return json.loads(p.read_bytes())`. It is used by `s1_slot.required_seals` (E2.4) and, from Task 10, by
    `s1_trial.evidence_manifest`;
  - `staging_dir(root, trial_id, stage) -> Path`;
  - `stage_rows(rows, stage) -> dict` (keys intent, prepared, created);
  - `permitted(trial, rows, stage) -> str | None`;
  - `manifest_projection(stage, manifest) -> dict` (C-a);
  - `run(gv, stage, *, inputs, acks, work, policy_fn=None, mailbox=None, clock=None, before_publish=None) -> dict`
    (returns the commitment);
  - `recover(gv, stage, m, *, mailbox=None, clock=None) -> dict`;
  - `created_problems(gv, stage, m) -> list[str]`;
  - `evaluate(gv) -> None`.

- [ ] **Step 1: Interface stub.** Create `s1_stage.py` with the names above and permissive bodies:
  - `run` performs `work` writing straight into s1_out: no rows, no staging, no lock;
  - `permitted` returns None; `evaluate` and `recover` are no-ops; `created_problems` returns `[]`;
  - `manifest_projection` returns `manifest["files"]` unprojected.

  Wire the gate hook.

```python
"""S1 stage engine - Task 8 INTERFACE STUB (permissive; replaced in Step 4)."""
import json
from pathlib import Path

import s1_common as c

TABLE = {"audit": {"kind": "tree", "pred": None, "ack": "S1-AUDIT-ACK", "state": "ACTIVE"},
         "opening": {"kind": "single", "pred": "audit", "ack": None, "state": "ACTIVE"},
         "start_attest": {"kind": "single", "pred": "opening", "ack": "S1-OPENING-ACK", "state": "ACTIVE"},  # OQ-15
         "prereg": {"kind": "single", "pred": "start_attest", "ack": "S1-RUN-ACK", "state": "ACTIVE"},
         "stop_attest": {"kind": "single", "pred": "TRIAL-STOP", "ack": None, "state": "STOPPED"},
         "final_plan": {"kind": "single", "pred": "stop_attest", "ack": None, "state": "STOPPED"},
         "final": {"kind": "tree", "pred": "final_plan", "ack": "S1-ACQUIRE-ACK", "state": "STOPPED"},
         "score": {"kind": "tree", "pred": "final", "ack": "S1-SCORE-ACK", "state": "STOPPED"}}
FIXED_TREE = {"audit": ("audit/attempt.json", "audit/calendar_source.json", "audit/calendar.json",
                        "audit/corporate_actions.json", "audit/ca_problems.json", "audit/manifest.json"),
              "final": ("final/attempt.json", "final/bars.json", "final/bar_problems.json",
                        "final/corporate_actions.json", "final/ca_problems.json", "final/manifest.json"),
              "score": ("score/attempt.json", "score/s1.json")}
SINGLE = {"opening": lambda out: f"seals/{c.load_json(Path(out) / 'plan.json')['opening_close']}.json",
          "start_attest": lambda out: "attest_start.json",                     # OQ-15: KEEP SINGLE
          "prereg": lambda out: "prereg.json", "stop_attest": lambda out: "attest_stop.json",
          "final_plan": lambda out: "final_plan.json"}
MANIFEST_STAGES = ("audit", "final")
TRIAL_ID_MEMBERS = {"audit": ("audit/attempt.json",), "start_attest": ("attest_start.json",),
                    "prereg": ("prereg.json",), "stop_attest": ("attest_stop.json",),
                    "final_plan": ("final_plan.json",), "final": ("final/attempt.json",),
                    "score": ("score/attempt.json", "score/s1.json")}
ENFORCED = frozenset()


class StageAbort(Exception):
    def __init__(self, reason, record):
        super().__init__(reason)
        self.reason, self.record = reason, record


class StageWork:
    def __init__(self, gv, stage, staging, intent, policy, op, actor, mailbox, clock):
        self.gv, self.stage, self.staging, self.intent, self.policy = gv, stage, staging, intent, policy
        self.op, self.actor, self.mailbox, self.clock = op, actor, mailbox, clock
        self.files = {}

    @property
    def intent_at(self):
        return c.now_utc().isoformat()

    @property
    def trial_id(self):
        return self.gv.trial.trial_id

    def put(self, rel, data):
        p = self.gv.out / rel
        c.publish_exclusive(p, data)
        self.files[rel] = data
        return p

    def put_json(self, rel, obj):
        return self.put(rel, c.text_bytes(json.dumps(obj, indent=1, sort_keys=True)))


def envelope(trial_id, stage, inputs, acks, policy):
    return {}


def commitment(trial_id, stage, op, kind, members, provenance, seals_checked):
    return {}


def staging_dir(root, trial_id, stage):
    return Path(root) / "s1_out"


def stage_rows(rows, stage):
    return {"intent": None, "prepared": None, "created": None}


def permitted(trial, rows, stage):
    return None


def manifest_projection(stage, manifest):
    return dict(manifest.get("files") or {})


def run(gv, stage, *, inputs, acks, work, policy_fn=None, mailbox=None, clock=None, before_publish=None):
    sw = StageWork(gv, stage, gv.out, None, policy_fn(c.now_utc()) if policy_fn else None, "0" * 32, "0" * 32,
                   mailbox, clock)
    work(sw)
    return {}


def recover(gv, stage, m, *, mailbox=None, clock=None):
    return {}


def created_problems(gv, stage, m):
    return []


def evaluate(gv):
    return None
```

- [ ] **Step 2: Write the test helpers and the failing tests.**

`research/s1/s1_tests/a3_helpers.py`:

```python
"""A3 test helpers (Task 8+): fake stage works with real staging, and child-process entry points for real crashes and
live owners (F5.4). Test-only; never imported by product code."""
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))      # research/s1 (child processes run this file)
import s1_common as c                                                  # noqa: E402
import s1_journal as j
import s1_stage as sg
import s1_trial as t


def relax(monkeypatch_or_none, stage, *, state="ACTIVE"):
    """Engine tests: drive `stage` with its F1 prerequisites relaxed (they are tested separately)."""
    entry = dict(sg.TABLE[stage], pred=None, ack=None, state=state)
    if monkeypatch_or_none is None:
        sg.TABLE[stage] = entry
    else:
        monkeypatch_or_none.setitem(sg.TABLE, stage, entry)


def fake_single(sw):
    """final_plan-shaped single member that records trial_id and intent_at."""
    sw.put_json("final_plan.json", {"trial_id": sw.trial_id, "intent_at": sw.intent_at, "plan": "synthetic"})
    return []


def fake_audit(sw, pages=2):
    """An audit-shaped tree: the six F4.9 fixed members (the manifest's files/pages consistent with them) + pages."""
    prov = []
    for n in range(pages):
        rel = f"audit/pages/ca_000_page{n:03d}.json"
        data = json.dumps({"corporate_actions": {}, "next_page_token": None if n == pages - 1 else f"tok{n}"}).encode()
        sw.put(rel, data)
        prov.append({"family": "corporate_actions", "scope": "audit", "n": n,
                     "url": "https://data.alpaca.markets/v1/corporate-actions", "params": {"n": n},
                     "page_token_from": None if n == 0 else f"audit/pages/ca_000_page{n - 1:03d}.json",
                     "retrieved_utc": sw.intent_at, "status": 200, "page_relpath": rel,
                     "page_sha256": c.sha256_bytes(data)})
    for name in sg.FIXED_TREE["audit"][:-1]:
        sw.put_json(name, {"trial_id": sw.trial_id, "intent_at": sw.intent_at, "name": name})
    files = {Path(n).name: c.sha256_bytes(sw.files[n]) for n in sg.FIXED_TREE["audit"][:-1]}
    sw.put_json("audit/manifest.json", {"outcome": "COMPLETE", "files": files,
                                        "pages": {p["page_relpath"]: p["page_sha256"] for p in prov}})
    return prov


def plan_only(root, start):
    """write_plan + its AUDIT-ACK (no audit files, no journal rows): the audit stage is permitted."""
    import s1_collect as k
    from conftest import _Clock, s1_mailbox
    with _Clock(start - timedelta(days=14)):
        k.write_plan(root, start, "2026-10-23", ["A"], "2026-03-17")
    s1_mailbox(root, "audit-ack", c.audit_token(Path(root) / "s1_out"), start - timedelta(days=13))
    return t.gate(root, "plan_only")


def child(root, stage, mode, at_iso):
    """Run one stage in this (child) process. mode: die-after-intent | die-after-prepared | hold-after-intent |
    hold-after-prepared | recover. Prints a status line; 'hold' modes wait on stdin while holding the stage lock."""
    c.MAILBOX = Path(root) / "mailbox.sqlite3"
    at = c.aware(at_iso)
    c.now_utc = lambda: at
    relax(None, stage)
    sg.ENFORCED = frozenset({stage})
    real = j.append

    def hooked(trial_id, gen, req, ctx_fn, **kw):
        res = real(trial_id, gen, req, ctx_fn, **kw)
        if mode.startswith("die-after-intent") and req.kind == "STAGE-INTENT":
            os._exit(9)
        if mode == "die-after-prepared" and req.kind == "STAGE-PREPARED":
            os._exit(9)
        if mode.startswith("hold-after-intent") and req.kind == "STAGE-INTENT":
            print("held", flush=True)
            sys.stdin.readline()
            os._exit(0)
        if mode == "hold-after-prepared" and req.kind == "STAGE-PREPARED":
            print("held", flush=True)
            sys.stdin.readline()
            os._exit(0)
        return res
    j.append = hooked
    gv = t.gate(root, f"child {mode}")
    work = fake_audit if stage == "audit" else fake_single
    if mode == "recover":
        print(json.dumps(sorted(sg.evaluate(gv) or [])), flush=True)
        return
    sg.run(gv, stage, inputs={"plan.json": c.sha256_file(Path(root) / "s1_out" / "plan.json")}, acks={},
           work=work, mailbox=c.MAILBOX, clock=lambda: at)


if __name__ == "__main__":
    child(*sys.argv[1:5])
```

`research/s1/s1_tests/test_s1_a3_stage.py`:

```python
"""Addendum 3 rev 5 F4.1-F4.5, F4.7, the F4 stage-state table, F1 graph and failure cases, F5 for stages, R2-1/R2-2,
FINAL-2, C-a projection. Behavioural RED against the Task 8 stub (s1_evidence/a3/t8_red.txt). Fake stage works over
real staging and the real journal; child processes for crashes and live owners; spies."""
import json
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import a3_helpers as h
import s1_common as c
import s1_journal as j
import s1_locks as L
import s1_stage as sg
import s1_trial as t
from conftest import Spies, s1_ack, s1_jappend

UTC = timezone.utc
START = datetime(2026, 10, 26, 13, 30, tzinfo=UTC)
AT = START - timedelta(days=12)
HELPERS = Path(__file__).resolve().parent / "a3_helpers.py"


def mb(root):
    return Path(root) / "mailbox.sqlite3"


def jrows(root):
    tr = t.open_trial(mb(root))
    return j.read_trial(tr.trial_id, tr.genesis, mb(root))


def stage_kinds(root, stage):
    return [r_.kind for r_ in j.subject_rows(jrows(root), j.stage_subject(stage))]


def drive(root, stage, work, monkeypatch, inputs=None, clock=None, **kw):
    monkeypatch.setattr(sg, "ENFORCED", frozenset({stage}))
    if stage != "audit":
        h.relax(monkeypatch, stage)
    gv = t.gate(root, "engine")
    return sg.run(gv, stage, inputs=inputs if inputs is not None else
                  {"plan.json": c.sha256_file(Path(root) / "s1_out" / "plan.json")}, acks={}, work=work,
                  mailbox=mb(root), clock=clock or (lambda: AT), **kw)


def child(root, stage, mode, wait=True):
    p = subprocess.Popen([sys.executable, "-I", str(HELPERS), str(root), stage, mode, AT.isoformat()],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if mode.startswith("hold"):
        assert p.stdout.readline().strip() == "held", p.stderr.read()
        return p
    p.wait(timeout=120)
    return p


@pytest.fixture
def trial(tmp_path):
    return h.plan_only(tmp_path, START)


def test_intent_precedes_any_work_and_the_envelope_is_exact(tmp_path, trial, monkeypatch):
    seen = {}

    def work(sw):
        seen["kinds"] = stage_kinds(tmp_path, "audit")
        return h.fake_audit(sw)
    drive(tmp_path, "audit", work, monkeypatch)
    assert seen["kinds"] == ["STAGE-INTENT"]
    intent = j.first(j.subject_rows(jrows(tmp_path), "stage/audit"), "STAGE-INTENT")
    env = sg.envelope(trial.trial.trial_id, "audit", {"plan.json": c.sha256_file(tmp_path / "s1_out" / "plan.json")},
                      {}, None)
    assert intent.detail == j.detail_of(env) == j.detail_of(json.loads(
        (sg.staging_dir(tmp_path, trial.trial.trial_id, "audit") / "intent.json").read_bytes()))


def test_work_writes_only_to_staging_outside_s1_out(tmp_path, trial, monkeypatch):
    seen = {}

    def work(sw):
        prov = h.fake_audit(sw)
        seen["in_out"] = sorted(p.relative_to(tmp_path / "s1_out").as_posix()
                                for p in (tmp_path / "s1_out").rglob("*") if p.is_file())
        seen["staging"] = sw.staging.dir
        return prov
    drive(tmp_path, "audit", work, monkeypatch)
    assert seen["in_out"] == ["plan.json"]
    assert seen["staging"] == tmp_path / "s1_staging" / trial.trial.trial_id / "audit"
    assert (tmp_path / "s1_out") not in seen["staging"].parents


@pytest.mark.parametrize("case", ["single", "tree", "single-with-two-members-refused"])
def test_prepared_commitment_format(tmp_path, trial, monkeypatch, case):
    if case == "tree":
        com = drive(tmp_path, "audit", h.fake_audit, monkeypatch)
        assert com["kind"] == "tree" and set(sg.FIXED_TREE["audit"]) <= set(com["members"])
        assert {p["page_relpath"] for p in com["provenance"]} == set(com["members"]) - set(sg.FIXED_TREE["audit"])
    elif case == "single":
        com = drive(tmp_path, "final_plan", h.fake_single, monkeypatch)
        assert (com["kind"], list(com["members"]), com["provenance"]) == ("single", ["final_plan.json"], [])
    else:
        def two(sw):
            h.fake_single(sw)
            sw.put_json("extra.json", {})
            return []
        with pytest.raises(SystemExit, match="exactly one member"):
            drive(tmp_path, "final_plan", two, monkeypatch)
        assert stage_kinds(tmp_path, "final_plan") == ["STAGE-INTENT"]
        return
    assert set(com) == {"trial_id", "stage", "op", "kind", "members", "provenance", "seals_checked"}
    seal_dir = tmp_path / "s1_out" / "seals"
    assert com["seals_checked"] == {f"seals/{p.name}": c.sha256_file(p)
                                    for p in sorted(seal_dir.glob("*.json"))}     # E2.4 r1 (row 331)
    prepared = j.first(j.subject_rows(jrows(tmp_path), j.stage_subject(com["stage"])), "STAGE-PREPARED")
    assert prepared.detail == j.detail_of(com)


def test_prepared_json_is_written_before_prepared_and_never_trusted_alone(tmp_path, trial, monkeypatch):
    seen = {}
    real = j.append

    def spy(trial_id, gen, req, ctx_fn, **kw):
        if req.kind == "STAGE-PREPARED":
            seen["exists"] = (sg.staging_dir(tmp_path, trial_id, "audit") / "prepared.json").is_file()
        return real(trial_id, gen, req, ctx_fn, **kw)
    monkeypatch.setattr(j, "append", spy)
    drive(tmp_path, "audit", h.fake_audit, monkeypatch)
    assert seen["exists"] is True


def test_publication_is_exclusive_then_created_repeats_the_prepared_detail(tmp_path, trial, monkeypatch):
    order = []
    real_pub, real_app = c.publish_exclusive, j.append
    monkeypatch.setattr(c, "publish_exclusive", lambda p, d: order.append(("publish", Path(p).name))
                        or real_pub(p, d))
    monkeypatch.setattr(j, "append", lambda *a, **kw: order.append(("append", a[2].kind)) or real_app(*a, **kw))
    drive(tmp_path, "final_plan", h.fake_single, monkeypatch)
    names_ = [x for x in order if x[0] == "append" or x[1] == "final_plan.json"]
    assert names_ == [("append", "STAGE-INTENT"), ("publish", "final_plan.json"), ("append", "STAGE-PREPARED"),
                      ("publish", "final_plan.json"), ("append", "STAGE-CREATED")]
    rows = j.subject_rows(jrows(tmp_path), "stage/final_plan")
    assert rows[2].detail == rows[1].detail


def test_intent_at_field_equals_the_intent_row(tmp_path, trial, monkeypatch):          # row 89 (schema placement)
    ticks = []

    def clock():                                              # every in-transaction reading is a distinct instant
        ticks.append(AT + timedelta(seconds=len(ticks)))
        return ticks[-1]
    drive(tmp_path, "final_plan", h.fake_single, monkeypatch, clock=clock)
    rows = j.subject_rows(jrows(tmp_path), "stage/final_plan")
    assert len({r_.at for r_ in rows}) == 3
    body = (tmp_path / "s1_out" / "final_plan.json").read_text(encoding="utf-8")
    assert json.loads(body)["intent_at"] == rows[0].at


def _member_bytes_with(root, monkeypatch, gaps):
    """Drive final_plan with the INTENT at AT and PREPARED/CREATED at AT + gaps (seconds); return member bytes."""
    seq = iter([AT] + [AT + timedelta(seconds=g) for g in gaps])
    last = [AT]

    def clock():
        last[0] = next(seq, last[0])
        return last[0]
    drive(root, "final_plan", h.fake_single, monkeypatch, clock=clock)
    return (root / "s1_out" / "final_plan.json").read_bytes(), j.subject_rows(jrows(root), "stage/final_plan")


@pytest.mark.parametrize("case", ["distinct-ticks", "same-tick"])
def test_member_bytes_do_not_depend_on_the_prepared_or_created_clock(tmp_path_factory, monkeypatch, case):
    """Rows 15, 89 (coverage 15/89): a DATA-INDEPENDENCE oracle, not substring inequality. Two runs with the same
    INTENT instant and different PREPARED/CREATED instants give byte-identical members; the same-tick run (all three
    rows at one instant, where a substring test would be vacuous or false) is accepted."""
    a, b = tmp_path_factory.mktemp("a"), tmp_path_factory.mktemp("b")
    ta, _ = h.plan_only(a, START), h.plan_only(b, START)
    gaps_b = [7, 13] if case == "distinct-ticks" else [0, 0]
    bytes_a, rows_a = _member_bytes_with(a, monkeypatch, [1, 2])
    bytes_b, rows_b = _member_bytes_with(b, monkeypatch, gaps_b)
    strip = lambda x: json.loads(x) | {"trial_id": None, "op": None}           # noqa: E731 (per-trial identity)
    assert strip(bytes_a) == strip(bytes_b)
    prepared = json.loads((sg.staging_dir(a, ta.trial.trial_id, "final_plan") / "prepared.json").read_bytes())
    assert "at" not in prepared and "prepared_at" not in prepared              # the commitment has no clock field
    if case == "same-tick":
        assert len({r_.at for r_ in rows_b}) == 1


def test_seal_seen_only_by_a_prepared_commitment_is_required(tmp_path, trial, monkeypatch):    # row 331 (E2.4 r1)
    import s1_slot as sl
    seal = tmp_path / "s1_out" / "seals" / "2026-10-27.json"
    seal.parent.mkdir(parents=True, exist_ok=True)
    seal.write_bytes(b'{"synthetic": "published seal"}')                      # the TEST writes its tmp seal
    drive(tmp_path, "final_plan", h.fake_single, monkeypatch)               # PREPARED records seals_checked
    req = sl.required_seals(tmp_path / "s1_out", jrows(tmp_path), [])        # no slot rows: PREPARED part only
    assert req == {"seals/2026-10-27.json": c.sha256_file(seal)}
    seal.unlink()
    assert "seals/2026-10-27.json" in sl.required_seals(tmp_path / "s1_out", jrows(tmp_path), [])   # still required


def test_stage_kinds_are_the_frozen_f48_kinds():                                       # row 85 (OQ-15)
    assert {g: v["kind"] for g, v in h.TABLE.items()} == {
        "audit": "tree", "opening": "single", "start_attest": "single", "prereg": "single", "stop_attest": "single",
        "final_plan": "single", "final": "tree", "score": "tree"}


@pytest.mark.parametrize("case", ["intent-deleted", "prepared-changed"])
def test_intent_or_prepared_json_lost_after_created_is_invalid(tmp_path, trial, monkeypatch, case):   # row 317
    drive(tmp_path, "final_plan", h.fake_single, monkeypatch)
    st_dir = sg.staging_dir(tmp_path, trial.trial.trial_id, "final_plan")
    if case == "intent-deleted":
        (st_dir / "intent.json").unlink()
    else:
        (st_dir / "prepared.json").write_bytes((st_dir / "prepared.json").read_bytes() + b" ")
    with pytest.raises(SystemExit, match="stage-replaced"):
        t.gate(tmp_path, "staging evidence")


def test_prepared_detail_comes_from_memory_even_if_prepared_json_is_altered(tmp_path, trial, monkeypatch):
    real = c.publish_exclusive

    def tamper(p, data):
        real(p, data)
        if Path(p).name == "prepared.json":
            Path(p).write_bytes(data.replace(b'"single"', b'"tree"'))      # the TEST alters its staging copy
    monkeypatch.setattr(c, "publish_exclusive", tamper)
    real_app = j.append

    def stop_before_created(*a, **kw):
        if a[2].kind == "STAGE-CREATED":
            raise KeyboardInterrupt                                       # simulate a crash before CREATED
        return real_app(*a, **kw)
    monkeypatch.setattr(j, "append", stop_before_created)
    with pytest.raises(KeyboardInterrupt):
        drive(tmp_path, "final_plan", h.fake_single, monkeypatch)
    monkeypatch.setattr(j, "append", real_app)
    monkeypatch.setattr(c, "publish_exclusive", real)
    with pytest.raises(SystemExit, match=r"INVALID \(stage-replaced\)"):
        t.gate(tmp_path, "recovery")


def test_crash_after_prepared_recovery_by_b_appends_created_without_recompute(tmp_path, trial, monkeypatch):
    p = child(tmp_path, "final_plan", "die-after-prepared")
    assert p.returncode == 9, p.stderr.read()
    assert stage_kinds(tmp_path, "final_plan") == ["STAGE-INTENT", "STAGE-PREPARED"]
    monkeypatch.setattr(sg, "ENFORCED", frozenset({"final_plan"}))
    h.relax(monkeypatch, "final_plan")
    called = []
    monkeypatch.setattr(h, "fake_single", lambda sw: called.append(1))
    t.gate(tmp_path, "B recovers")
    rows = j.subject_rows(jrows(tmp_path), "stage/final_plan")
    assert [r_.kind for r_ in rows] == ["STAGE-INTENT", "STAGE-PREPARED", "STAGE-CREATED"] and called == []
    assert rows[2].op == rows[0].op and rows[2].actor != rows[0].actor and rows[2].detail == rows[1].detail
    assert all(r_.kind != "TRIAL-INVALID" for r_ in jrows(tmp_path))


def test_recovery_appends_created_with_a_op_and_b_actor_under_the_lock(tmp_path, trial, monkeypatch):
    assert child(tmp_path, "final_plan", "die-after-prepared").returncode == 9
    monkeypatch.setattr(sg, "ENFORCED", frozenset({"final_plan"}))
    h.relax(monkeypatch, "final_plan")
    order = []
    real_acq, real_read, real_app = L.OwnershipLock.acquire, j.read_trial, j.append
    monkeypatch.setattr(L.OwnershipLock, "acquire", lambda self: order.append("lock") or real_acq(self))
    monkeypatch.setattr(j, "read_trial", lambda *a, **kw: order.append("read") or real_read(*a, **kw))
    monkeypatch.setattr(j, "append", lambda *a, **kw: order.append(a[2].kind) or real_app(*a, **kw))
    t.gate(tmp_path, "B recovers")
    before = order[:order.index("STAGE-CREATED")][::-1]
    assert "lock" in before and before.index("read") < before.index("lock")   # re-read after the lock, then CREATED
    rows = j.subject_rows(jrows(tmp_path), "stage/final_plan")
    assert rows[2].op == rows[0].op and rows[2].actor not in (rows[0].actor, rows[1].actor)


@pytest.mark.parametrize("case", ["member-absent", "member-changed", "prepared-json-mismatch", "foreign-op",
                                  "missing-prepared"])
def test_recovery_failures_are_invalid(tmp_path, trial, monkeypatch, case):
    monkeypatch.setattr(sg, "ENFORCED", frozenset({"final_plan"}))
    h.relax(monkeypatch, "final_plan")
    tid = trial.trial.trial_id
    staging = sg.staging_dir(tmp_path, tid, "final_plan")
    if case in ("foreign-op", "missing-prepared"):
        row = s1_jappend(tmp_path, "STAGE-INTENT", "stage/final_plan", at=AT, detail="1" * 64)
        if case == "foreign-op":
            s1_jappend(tmp_path, "STAGE-PREPARED", "stage/final_plan", at=AT, detail="2" * 64, op=row.op,
                       actor=row.actor)
        tr = t.open_trial(mb(tmp_path))
        res = j.append(tid, tr.genesis, j.Request("STAGE-CREATED", "stage/final_plan",
                                                  j.new_nonce() if case == "foreign-op" else row.op, j.new_nonce(),
                                                  detail="2" * 64),
                       t.product_context(tr), mailbox=mb(tmp_path), clock=lambda: AT)
        assert (res.outcome, res.reason) == ("INVALIDATE", "contradictory-stage")
        return
    assert child(tmp_path, "final_plan", "die-after-prepared").returncode == 9
    if case == "member-absent":
        (staging / "final_plan.json").unlink()
    elif case == "member-changed":
        (staging / "final_plan.json").write_bytes(b"{}")
    else:
        (staging / "prepared.json").write_bytes(b"{}")
    with pytest.raises(SystemExit, match=r"INVALID \(stage-replaced\)"):
        t.gate(tmp_path, "recovery")


def test_recovery_never_appends_prepared_for_another_actors_op(tmp_path, trial):
    row = s1_jappend(tmp_path, "STAGE-INTENT", "stage/final_plan", at=AT, detail="1" * 64)
    tr = t.open_trial(mb(tmp_path))
    res = j.append(tr.trial_id, tr.genesis, j.Request("STAGE-PREPARED", "stage/final_plan", row.op, j.new_nonce(),
                                                      detail="2" * 64),
                   t.product_context(tr), mailbox=mb(tmp_path), clock=lambda: AT)
    assert (res.outcome, res.reason) == ("INVALIDATE", "contradictory-stage")
    import inspect
    assert "STAGE-PREPARED" not in inspect.getsource(sg.recover)


def test_recovery_publishes_only_missing_members_and_never_overwrites(tmp_path, trial, monkeypatch):
    assert child(tmp_path, "audit", "die-after-prepared").returncode == 9
    staging = sg.staging_dir(tmp_path, trial.trial.trial_id, "audit")
    first = "audit/attempt.json"
    (tmp_path / "s1_out" / first).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(staging / first, tmp_path / "s1_out" / first)          # partially published before the crash
    before = (tmp_path / "s1_out" / first).stat().st_mtime_ns
    monkeypatch.setattr(sg, "ENFORCED", frozenset({"audit"}))
    t.gate(tmp_path, "recovery")
    assert (tmp_path / "s1_out" / first).stat().st_mtime_ns == before
    assert stage_kinds(tmp_path, "audit")[-1] == "STAGE-CREATED"


def test_recovery_unexpected_error_appends_nothing(tmp_path, trial, monkeypatch):
    assert child(tmp_path, "final_plan", "die-after-prepared").returncode == 9
    monkeypatch.setattr(sg, "ENFORCED", frozenset({"final_plan"}))
    h.relax(monkeypatch, "final_plan")
    monkeypatch.setattr(c, "publish_exclusive", lambda p, d: (_ for _ in ()).throw(RuntimeError("disk")))
    with pytest.raises(SystemExit, match="refused with no row"):
        t.gate(tmp_path, "recovery")
    assert stage_kinds(tmp_path, "final_plan") == ["STAGE-INTENT", "STAGE-PREPARED"]


def test_concurrent_recovery_appends_exactly_one_created(tmp_path, trial):
    assert child(tmp_path, "final_plan", "die-after-prepared").returncode == 9
    procs = [subprocess.Popen([sys.executable, "-I", str(HELPERS), str(tmp_path), "final_plan", "recover",
                               AT.isoformat()], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             for _ in range(2)]
    for p in procs:
        p.wait(timeout=120)
    assert stage_kinds(tmp_path, "final_plan").count("STAGE-CREATED") == 1


@pytest.mark.parametrize("case", ["no-intent-artifact-after-audit-ack", "no-intent-artifact-before-audit-ack",
                                  "intent-lock-held", "intent-lock-free", "prepared-lock-held", "prepared-lock-free"])
def test_stage_state_table(tmp_path, monkeypatch, case):
    if case == "no-intent-artifact-before-audit-ack":
        import s1_collect as k
        from conftest import _Clock
        with _Clock(START - timedelta(days=14)):
            k.write_plan(tmp_path, START, "2026-10-23", ["A"], "2026-03-17")
        (tmp_path / "s1_out" / "final_plan.json").write_text("{}", encoding="utf-8")
        with pytest.raises(SystemExit, match="zero open trials"):
            t.gate(tmp_path, "table")
        return
    trial = h.plan_only(tmp_path, START)
    monkeypatch.setattr(sg, "ENFORCED", frozenset({"final_plan"}))
    h.relax(monkeypatch, "final_plan")
    sp = Spies(monkeypatch)
    if case == "no-intent-artifact-after-audit-ack":
        (tmp_path / "s1_out" / "final_plan.json").write_text("{}", encoding="utf-8")
        with pytest.raises(SystemExit, match=r"INVALID \(registration-artifact\)"):
            t.gate(tmp_path, "table")
    elif case.endswith("lock-held"):
        p = child(tmp_path, "final_plan", "hold-after-intent" if case.startswith("intent") else "hold-after-prepared")
        try:
            with pytest.raises(SystemExit, match="pending"):
                t.gate(tmp_path, "table")
            assert all(r_.kind != "TRIAL-INVALID" for r_ in jrows(tmp_path))
        finally:
            p.stdin.close()
            p.wait(timeout=60)
    elif case == "intent-lock-free":
        assert child(tmp_path, "final_plan", "die-after-intent").returncode == 9
        with pytest.raises(SystemExit, match=r"INVALID \(stage-incomplete\)"):
            t.gate(tmp_path, "table")
    else:
        assert child(tmp_path, "final_plan", "die-after-prepared").returncode == 9
        t.gate(tmp_path, "table")
        assert stage_kinds(tmp_path, "final_plan")[-1] == "STAGE-CREATED"
    sp.assert_zero()


@pytest.mark.parametrize("damage", ["missing", "changed", "unparseable"])
def test_created_member_missing_changed_or_unparseable_is_invalid(tmp_path, trial, monkeypatch, damage):
    drive(tmp_path, "final_plan", h.fake_single, monkeypatch)
    p = tmp_path / "s1_out" / "final_plan.json"
    if damage == "missing":
        p.unlink()
    else:
        p.write_text("{}" if damage == "changed" else "{not JSON", encoding="utf-8")
    sp = Spies(monkeypatch)
    with pytest.raises(SystemExit, match=r"INVALID \(stage-replaced\)"):
        t.gate(tmp_path, "created check")
    sp.assert_zero()


def test_pre_intent_outage_makes_no_request_and_no_artifact(tmp_path, trial, monkeypatch):
    sp = Spies(monkeypatch)
    real = j.append

    def outage(trial_id, gen, req, ctx_fn, **kw):
        if req.kind == "STAGE-INTENT":
            raise j.Outage("mailbox busy")
        return real(trial_id, gen, req, ctx_fn, **kw)
    monkeypatch.setattr(j, "append", outage)
    with pytest.raises(SystemExit, match="outage"):
        drive(tmp_path, "audit", lambda sw: sp.client().get("https://data.alpaca.markets/x"), monkeypatch)
    sp.assert_zero()
    assert not (tmp_path / "s1_staging").exists() and stage_kinds(tmp_path, "audit") == []


def test_completion_append_failure_keeps_evidence_and_no_next_stage_runs(tmp_path, trial, monkeypatch):
    real = j.append

    def fail_created(trial_id, gen, req, ctx_fn, **kw):
        if req.kind == "STAGE-CREATED":
            raise j.Outage("mailbox busy")
        return real(trial_id, gen, req, ctx_fn, **kw)
    monkeypatch.setattr(j, "append", fail_created)
    with pytest.raises(SystemExit, match="outage"):
        drive(tmp_path, "audit", h.fake_audit, monkeypatch)
    staging = sg.staging_dir(tmp_path, trial.trial.trial_id, "audit")
    assert (staging / "prepared.json").is_file() and stage_kinds(tmp_path, "audit") == ["STAGE-INTENT",
                                                                                        "STAGE-PREPARED"]
    assert "not CREATED" in sg.permitted(trial.trial, jrows(tmp_path), "opening")


@pytest.mark.parametrize("stage", list(sg.TABLE))
def test_stage_intent_refused_until_predecessor_created_and_ack(tmp_path, trial, stage):
    rows = jrows(tmp_path)
    why = sg.permitted(trial.trial, rows, stage)
    assert (why is None) == (stage == "audit"), (stage, why)


def test_repeat_stage_intent_is_invalid(tmp_path, trial):
    s1_jappend(tmp_path, "STAGE-INTENT", "stage/audit", at=AT, detail="1" * 64)
    tr = t.open_trial(mb(tmp_path))
    res = j.append(tr.trial_id, tr.genesis, j.Request("STAGE-INTENT", "stage/audit", j.new_nonce(), j.new_nonce(),
                                                      detail="2" * 64),
                   t.product_context(tr, stage_gate=lambda r_, g: None), mailbox=mb(tmp_path), clock=lambda: AT)
    assert (res.outcome, res.reason) == ("INVALIDATE", "repeat-stage")


def test_commit_delete_detect_restore_is_still_invalid_with_zero_callbacks(tmp_path, trial, monkeypatch):
    drive(tmp_path, "final_plan", h.fake_single, monkeypatch)
    p = tmp_path / "s1_out" / "final_plan.json"
    keep = p.read_bytes()
    p.unlink()
    with pytest.raises(SystemExit, match="INVALID"):
        t.gate(tmp_path, "detect")
    p.write_bytes(keep)
    for w in ("aborted.json", "refusals.jsonl"):
        (tmp_path / "s1_out" / w).unlink(missing_ok=True)
    shutil.rmtree(tmp_path / "s1_out" / "invalid", ignore_errors=True)
    sp = Spies(monkeypatch)
    with pytest.raises(SystemExit, match="INVALID"):
        t.gate(tmp_path, "restart")
    sp.assert_zero()


def test_pause_after_intent_with_a_live_owner_is_pending(tmp_path, trial, monkeypatch):
    p = child(tmp_path, "final_plan", "hold-after-intent")
    try:
        monkeypatch.setattr(sg, "ENFORCED", frozenset({"final_plan"}))
        h.relax(monkeypatch, "final_plan")
        sp = Spies(monkeypatch)
        with pytest.raises(SystemExit, match="pending"):
            t.gate(tmp_path, "concurrent gate")
        sp.assert_zero()
    finally:
        p.stdin.close()
        p.wait(timeout=60)


def test_created_failure_then_restart_recovers_without_recreation(tmp_path, trial, monkeypatch):
    real = j.append
    monkeypatch.setattr(j, "append", lambda *a, **kw: (_ for _ in ()).throw(j.Outage("busy"))
                        if a[2].kind == "STAGE-CREATED" else real(*a, **kw))
    with pytest.raises(SystemExit):
        drive(tmp_path, "final_plan", h.fake_single, monkeypatch)
    monkeypatch.setattr(j, "append", real)
    calls = []
    monkeypatch.setattr(h, "fake_single", lambda sw: calls.append(1))
    t.gate(tmp_path, "restart")
    assert stage_kinds(tmp_path, "final_plan")[-1] == "STAGE-CREATED" and calls == []


def test_lock_io_error_refuses_with_no_row_and_no_liveness_verdict(tmp_path, trial, monkeypatch):
    assert child(tmp_path, "final_plan", "die-after-intent").returncode == 9
    monkeypatch.setattr(sg, "ENFORCED", frozenset({"final_plan"}))
    h.relax(monkeypatch, "final_plan")
    lp = L.lock_path(tmp_path, trial.trial.trial_id, "stage-final_plan")
    lp.unlink(missing_ok=True)
    lp.mkdir(parents=True)                                     # an I/O error, not a sharing violation
    with pytest.raises(SystemExit, match="lock error"):
        t.gate(tmp_path, "lock error")
    assert stage_kinds(tmp_path, "final_plan") == ["STAGE-INTENT"]
    assert all(r_.kind != "TRIAL-INVALID" for r_ in jrows(tmp_path))


def test_stage_lock_is_taken_before_the_journal_read(tmp_path, trial, monkeypatch):
    order = []
    real_acq, real_read, real_app = L.OwnershipLock.acquire, j.read_trial, j.append
    monkeypatch.setattr(L.OwnershipLock, "acquire", lambda self: order.append(("lock", self.path.name))
                        or real_acq(self))
    monkeypatch.setattr(j, "read_trial", lambda *a, **kw: order.append(("read",)) or real_read(*a, **kw))
    monkeypatch.setattr(j, "append", lambda *a, **kw: order.append(("append", a[2].kind)) or real_app(*a, **kw))
    drive(tmp_path, "final_plan", h.fake_single, monkeypatch)
    i_lock = order.index(("lock", "stage-final_plan.lock"))
    i_intent = order.index(("append", "STAGE-INTENT"))
    assert i_lock < i_intent and ("read",) in order[i_lock:i_intent]      # the stage state is read under the lock


def test_manifest_projection_rule():
    m = {"files": {"attempt.json": "a", "calendar.json": "b"}, "pages": {"audit/pages/calendar.json": "c"}}
    assert sg.manifest_projection("audit", m) == {"audit/attempt.json": "a", "audit/calendar.json": "b",
                                                  "audit/pages/calendar.json": "c"}
    m2 = {"files": {"bars.json": "d"}, "pages": {"final/pages_full/ca_000_page000.json": "e"}}
    assert sg.manifest_projection("final", m2) == {"final/bars.json": "d", "final/pages_full/ca_000_page000.json": "e"}


def test_every_stage_artifact_records_and_is_validated_against_the_trial_id(tmp_path, trial, monkeypatch):
    def wrong(sw):
        sw.put_json("final_plan.json", {"trial_id": "9a1b2c3d-4e5f-4a6b-8c7d-0e1f2a3b4c5d", "intent_at": sw.intent_at})
        return []
    drive(tmp_path, "final_plan", wrong, monkeypatch)
    with pytest.raises(SystemExit, match=r"INVALID \(stage-replaced\)"):
        t.gate(tmp_path, "trial id")
```

- [ ] **Step 3: Behavioural RED.** Run `test_s1_a3_stage.py` into `a3/t8_red.txt`.
  - Expected: the stub writes into s1_out, appends no rows, does no recovery, raises no INVALID, takes no lock, and
    leaves the projection unprojected. Nearly every test fails on an assertion.
  - `test_stage_intent_refused…` fails (the stub permits everything).
  - `test_repeat_stage_intent_is_invalid` passes (journal-level, Task 2). Label it `retro`.
  - Revision 1:
    - `test_member_bytes_do_not_depend…[*]` fails on the stub (no rows; no prepared.json);
    - `test_stage_kinds_are_the_frozen_f48_kinds` is `static` (the stub carries the final TABLE). It is kept as the
      guard that revision 0's start_attest `tree` cannot return;
    - `test_intent_or_prepared_json_lost_after_created_is_invalid[*]` fails (no INVALID);
    - `test_seal_seen_only_by_a_prepared_commitment_is_required` fails (no PREPARED row, so nothing required);
    - `test_prepared_commitment_format` fails on the `seals_checked` key (E2.4 r1).

- [ ] **Step 4: Implement `research/s1/s1_stage.py`.** Replace the stub; keep the constant tables from the stub.

```python
"""S1 stage engine (Addendum 3 rev 5 F4). One stage = STAGE-INTENT (the input envelope, F4.1) -> work in staging
(<root>/s1_staging/<trial_id>/<stage>/, outside s1_out, F4.2) -> prepared.json + STAGE-PREPARED (the one canonical
output commitment, F4.3) -> exclusive publication into s1_out + STAGE-CREATED (same detail, F4.4). The stage lock is
taken before the journal read and held across read-work-append (F5.1). Recovery (F4.7) and the stage-state table
(evaluate) run under the same lock. Staging keeps intent.json and prepared.json for the trial's life; both must hash
to their rows (OQ-35). JSON members named in TRIAL_ID_MEMBERS record the trial_id (OQ-36)."""
import json
from pathlib import Path

import s1_common as c
import s1_journal as j
import s1_locks as L

# (TABLE, FIXED_TREE, SINGLE, MANIFEST_STAGES, TRIAL_ID_MEMBERS exactly as in the stub)
ENFORCED = frozenset()      # transitional (Task 8); Tasks 9-13 add their stage; Task 14 requires all of TABLE


class StageAbort(Exception):
    """A provider anomaly (provider-structural) or a score computation error (score-aborted): the staged evidence and
    an ABORTED record are kept, no PREPARED is appended, the trial becomes INVALID with this reason (F4.6, F4.9)."""

    def __init__(self, reason: str, record: dict):
        super().__init__(reason)
        self.reason, self.record = reason, record


class _Staging:
    def __init__(self, root, trial_id, stage):
        self.dir = staging_dir(root, trial_id, stage)
        self.files = {}

    def put(self, rel: str, data: bytes) -> Path:
        p = self.dir / rel
        c.publish_exclusive(p, data)
        self.files[rel] = bytes(data)
        return p


class StageWork:
    """What a stage's work function receives: staging writers (bytes kept in memory: F0.4), the INTENT row, the
    committed request policy (or None), the op/actor, mailbox and clock."""

    def __init__(self, gv, stage, staging, intent, policy, op, actor, mailbox, clock):
        self.gv, self.stage, self.staging, self.intent, self.policy = gv, stage, staging, intent, policy
        self.op, self.actor, self.mailbox, self.clock = op, actor, mailbox, clock

    @property
    def intent_at(self) -> str:
        return self.intent.at                                                  # F4.5

    @property
    def trial_id(self) -> str:
        return self.gv.trial.trial_id

    @property
    def files(self) -> dict:
        return self.staging.files

    def put(self, rel: str, data: bytes) -> Path:
        return self.staging.put(rel, data)

    def put_json(self, rel: str, obj) -> Path:
        """The exact bytes s1_collect._write_once publishes (json indent=1, sorted keys, platform newlines)."""
        return self.staging.put(rel, c.text_bytes(json.dumps(obj, indent=1, sort_keys=True)))


def staging_dir(root, trial_id: str, stage: str) -> Path:
    return Path(root) / "s1_staging" / trial_id / stage


def envelope(trial_id, stage, inputs: dict, acks: dict, policy) -> dict:
    return {"trial_id": trial_id, "stage": stage, "inputs": dict(sorted(inputs.items())),
            "acks": dict(sorted(acks.items())), "request_policy": policy}


def commitment(trial_id, stage, op, kind, members: dict, provenance: list, seals_checked: dict) -> dict:
    """F4.3 plus E2.4 (Erratum 1 r1): every PREPARED commitment carries `seals_checked` = {relpath: sha256} of every
    seal published at that moment, so the seals it saw become published-committed (required)."""
    return {"trial_id": trial_id, "stage": stage, "op": op, "kind": kind, "members": dict(sorted(members.items())),
            "provenance": list(provenance), "seals_checked": dict(sorted(seals_checked.items()))}


def stage_rows(rows, stage: str) -> dict:
    mine = j.subject_rows(rows, j.stage_subject(stage))
    return {"intent": j.first(mine, "STAGE-INTENT"), "prepared": j.first(mine, "STAGE-PREPARED"),
            "created": j.first(mine, "STAGE-CREATED")}


def permitted(trial, rows, stage: str):
    """F1 + the finalization graph: the stage's trial state, its predecessor's CREATED row (or the TRIAL-STOP), and
    its required ACK. A reason string refuses the INTENT with no row (F0.5 step 5)."""
    spec = TABLE[stage]
    st_ = j.trial_state(rows)
    if st_ != spec["state"]:
        return f"F1: stage {stage} is not allowed while {st_}"
    pred = spec["pred"]
    if pred == "TRIAL-STOP":
        if j.first(rows, "TRIAL-STOP") is None:
            return f"stage {stage}: no TRIAL-STOP"
    elif pred is not None and stage_rows(rows, pred)["created"] is None:
        return f"stage {stage}: predecessor {pred} is not CREATED (F1)"
    ack = spec["ack"]
    if ack not in (None, "S1-AUDIT-ACK") and ack not in trial.acks:
        return f"stage {stage}: no {ack} (F1 graph)"
    return None


def manifest_projection(stage: str, manifest: dict) -> dict:
    """C-a: the collector manifest's basename-keyed `files` prefixed with '<stage>/', union its s1_out-relative
    `pages`; must equal PREPARED.members minus '<stage>/manifest.json'."""
    files = {f"{stage}/{n}": h for n, h in (manifest.get("files") or {}).items()}
    pages = dict(manifest.get("pages") or {})
    return dict(sorted({**files, **pages}.items()))


def _member_problems(gv, stage, members: dict, provenance: list) -> list:
    if TABLE[stage]["kind"] == "single":
        want = SINGLE[stage](gv.out)
        return [] if list(members) == [want] else [f"single stage {stage} must have exactly one member {want}"]
    fixed = set(FIXED_TREE[stage])
    pages = [p.get("page_relpath") for p in provenance]
    probs = [f"{stage}: fixed member {n} missing" for n in sorted(fixed - set(members))]
    if len(set(pages)) != len(pages):
        probs.append(f"{stage}: a page has two provenance entries")
    extra = set(members) - fixed
    if extra != set(pages):
        probs.append(f"{stage}: pages {sorted(extra ^ set(pages))[:4]} lack a provenance entry or a member")
    return probs


def _lock(gv, stage):
    lk = L.OwnershipLock(gv.root, gv.trial.trial_id, L.stage_lock_name(stage))
    try:
        return lk.acquire()
    except L.LockHeld:
        raise SystemExit(f"stage {stage}: pending - a live owner holds the stage lock: no work (F4 table)") from None
    except L.LockError as e:
        raise SystemExit(f"stage {stage}: lock error ({e}): refused with no row and no liveness verdict "
                         f"(F5.5)") from None


def _append(gv, req, mailbox, clock, stage_gate=None):
    import s1_trial
    return j.append(gv.trial.trial_id, gv.trial.genesis, req, s1_trial.product_context(gv.trial,
                                                                                       stage_gate=stage_gate),
                    mailbox=mailbox, clock=clock)


def _invalid(gv, reason, record, mailbox, clock):
    import s1_trial
    s1_trial.invalidate(gv.trial, reason, record, root=gv.root, mailbox=mailbox, clock=clock)
    raise SystemExit(f"stage {record.get('stage')}: INVALID ({reason})")


def _need(res, stage, kind):
    if res.outcome == "APPEND":
        return res.row
    if res.outcome == "INVALIDATE":
        raise SystemExit(f"stage {stage}: {kind} -> INVALID ({res.reason})")
    raise SystemExit(f"stage {stage}: {kind} {res.outcome} with no row: {res.reason}")


def run(gv, stage, *, inputs: dict, acks: dict, work, policy_fn=None, mailbox=None, clock=None,
        before_publish=None) -> dict:
    """F4.1-F4.4 for one stage; re-entry resolves the existing rows per the stage table instead (never a second
    INTENT). A journal outage before the INTENT is a refusal with no request and no artifact (F4 failure 1)."""
    clock = clock or c.now_utc
    lk = _lock(gv, stage)
    try:
        rows = j.read_trial(gv.trial.trial_id, gv.trial.genesis, mailbox)
        m = stage_rows(rows, stage)
        if m["intent"] is not None:
            return _resolve(gv, stage, m, mailbox, clock)
        op, actor, held = j.new_nonce(), j.new_nonce(), {}

        def detail_fn(at):                                                    # OQ-7: the in-transaction clock
            held["policy"] = policy_fn(at) if policy_fn is not None else None
            held["envelope"] = envelope(gv.trial.trial_id, stage, inputs, acks, held["policy"])
            return j.detail_of(held["envelope"])
        try:
            intent = _need(_append(gv, j.Request("STAGE-INTENT", j.stage_subject(stage), op, actor,
                                                 detail_fn=detail_fn), mailbox, clock,
                                   stage_gate=lambda rows_, g: permitted(gv.trial, rows_, g)),
                           stage, "STAGE-INTENT")
        except j.Outage as e:
            raise SystemExit(f"stage {stage}: journal outage before the INTENT ({e}): no request, no artifact") \
                from None
        staging = _Staging(gv.root, gv.trial.trial_id, stage)
        c.publish_exclusive(staging.dir / "intent.json", c.canonical(held["envelope"]))       # OQ-35
        sw = StageWork(gv, stage, staging, intent, held["policy"], op, actor, mailbox, clock)
        try:
            provenance = work(sw) or []
        except StageAbort as e:
            rec = dict(e.record, stage=stage, reason=e.reason)
            staging.put("ABORTED.json", c.canonical(rec))
            _invalid(gv, e.reason, rec, mailbox, clock)
        probs = _member_problems(gv, stage, {r: 1 for r in staging.files}, provenance)
        if probs:
            raise SystemExit(f"stage {stage}: {probs[0]} (exactly one member / named members, F4.3): no PREPARED")
        members = {rel: c.sha256_bytes(data) for rel, data in staging.files.items()}
        import s1_slot                                                         # late import (E2.4)
        com = commitment(gv.trial.trial_id, stage, op, TABLE[stage]["kind"], members, provenance,
                         s1_slot.seals_checked(gv.out))
        blob = c.canonical(com)
        c.publish_exclusive(staging.dir / "prepared.json", blob)
        detail = c.sha256_bytes(blob)                                         # F0.4: the in-memory bytes
        try:
            _need(_append(gv, j.Request("STAGE-PREPARED", j.stage_subject(stage), op, actor, detail=detail),
                          mailbox, clock), stage, "STAGE-PREPARED")
            if before_publish is not None:
                before_publish(com)
            for rel in sorted(members):
                _publish_one(gv.out, rel, staging.files[rel], members[rel])
            _need(_append(gv, j.Request("STAGE-CREATED", j.stage_subject(stage), op, actor, detail=detail),
                          mailbox, clock), stage, "STAGE-CREATED")
        except j.Outage as e:
            raise SystemExit(f"stage {stage}: journal outage after the work ({e}): evidence kept, no next stage; "
                             f"recovery follows the stage table") from None
        return com
    finally:
        lk.release()


def _publish_one(out: Path, rel: str, data: bytes, sha: str) -> None:
    dst = Path(out) / rel
    try:
        c.publish_exclusive(dst, data)
    except FileExistsError:
        if c.sha256_file(dst) != sha:
            raise SystemExit(f"{rel} exists with other bytes: never overwritten") from None


def _resolve(gv, stage, m, mailbox, clock) -> dict:
    """Re-entry under the stage lock (no live owner): CREATED -> refused (F1 'each stage once'); INTENT without
    PREPARED -> INVALID stage-incomplete (no refetch); PREPARED without CREATED -> recovery (F4.7)."""
    if m["created"] is not None:
        raise SystemExit(f"stage {stage} is already CREATED: re-entry refused (F1)")
    if m["prepared"] is None:
        _invalid(gv, "stage-incomplete", {"stage": stage, "intent_seq": m["intent"].seq}, mailbox, clock)
    return recover(gv, stage, m, mailbox=mailbox, clock=clock)


def _load_committed(gv, stage, row, name) -> dict:
    p = staging_dir(gv.root, gv.trial.trial_id, stage) / name
    try:
        blob = p.read_bytes()
        if c.sha256_bytes(blob) != row.detail:
            return None
        return json.loads(blob)
    except (OSError, ValueError):
        return None


def recover(gv, stage, m, *, mailbox=None, clock=None) -> dict:
    """F4.7, called with the stage lock held: prepared.json must hash to the PREPARED detail; every member, in staging
    or already in s1_out, must have its committed sha256; only the missing members are published (from staging, the
    bytes just verified); CREATED is appended with the stage's op and this actor. Any absent or mismatched byte is
    INVALID (stage-replaced). Never re-requests, recomputes or changes prepared bytes; any unexpected error refuses
    with no row (F0.7)."""
    clock = clock or c.now_utc
    try:
        com = _load_committed(gv, stage, m["prepared"], "prepared.json")
        if com is None:
            _invalid(gv, "stage-replaced", {"stage": stage, "problem": "prepared.json missing or not the PREPARED "
                                                                        "detail"}, mailbox, clock)
        staging = staging_dir(gv.root, gv.trial.trial_id, stage)
        todo = {}
        for rel, sha in sorted(com["members"].items()):
            dst = gv.out / rel
            if dst.is_file():
                if c.sha256_file(dst) != sha:
                    _invalid(gv, "stage-replaced", {"stage": stage, "member": rel, "problem": "published bytes differ"},
                             mailbox, clock)
                continue
            try:
                data = (staging / rel).read_bytes()
            except OSError:
                data = None
            if data is None or c.sha256_bytes(data) != sha:
                _invalid(gv, "stage-replaced", {"stage": stage, "member": rel, "problem": "staged bytes absent or "
                                                                                          "different"},
                         mailbox, clock)
            todo[rel] = data
        for rel, data in todo.items():
            c.publish_exclusive(gv.out / rel, data)
        _need(_append(gv, j.Request("STAGE-CREATED", j.stage_subject(stage), m["intent"].op, j.new_nonce(),
                                    detail=m["prepared"].detail), mailbox, clock), stage, "STAGE-CREATED")
        return com
    except SystemExit:
        raise
    except Exception as e:                                  # noqa: BLE001 - F0.7: fail closed, no row
        raise SystemExit(f"stage {stage}: recovery refused with no row ({type(e).__name__}) (F0.7)") from None


def _artifacts_present(out: Path, stage: str) -> list:
    if TABLE[stage]["kind"] == "single":
        try:
            rel = SINGLE[stage](out)
        except (OSError, ValueError, KeyError):
            return []
        return [rel] if (out / rel).exists() else []
    names = FIXED_TREE[stage]
    if stage in ("audit", "final", "score"):
        d = out / stage
        return sorted(p.relative_to(out).as_posix() for p in d.rglob("*") if p.is_file()) if d.is_dir() else []
    return [n for n in names if (out / n).exists()]


def created_problems(gv, stage, m) -> list:
    """F4 table, CREATED: the envelope's file inputs still hash as committed (intent.json must hash to the INTENT
    detail, OQ-35); every committed member present with its sha256 and parseable when JSON; no extra file in a tree
    stage's directory (an orphan page); for audit/final the manifest projection equals the members minus the manifest
    (C-a) and every page has exactly one provenance entry; JSON members record the trial_id (OQ-36)."""
    out, probs = gv.out, []
    env = _load_committed(gv, stage, m["intent"], "intent.json")
    com = _load_committed(gv, stage, m["prepared"], "prepared.json")
    if env is None or com is None:
        return [f"{stage}: intent.json or prepared.json missing or not its row's detail"]
    for name, sha in env["inputs"].items():
        if name.endswith(".json") and (not (out / name).is_file() or c.sha256_file(out / name) != sha):
            probs.append(f"{stage}: bound input {name} missing or changed since the INTENT")
    for rel, sha in com["members"].items():
        p = out / rel
        if not p.is_file() or c.sha256_file(p) != sha:
            probs.append(f"{stage}: member {rel} missing or changed")
        elif rel.endswith(".json"):
            try:
                json.loads(p.read_bytes())
            except ValueError:
                probs.append(f"{stage}: member {rel} unparseable")
    if TABLE[stage]["kind"] == "tree" and stage in ("audit", "final", "score"):
        extra = set(_artifacts_present(out, stage)) - set(com["members"])
        probs += [f"{stage}: {rel} is not a committed member (orphan)" for rel in sorted(extra)]
    probs += _member_problems(gv, stage, com["members"], com["provenance"])
    if stage in MANIFEST_STAGES and not probs:
        man = json.loads((out / f"{stage}/manifest.json").read_bytes())
        want = {k_: v for k_, v in com["members"].items() if k_ != f"{stage}/manifest.json"}
        if manifest_projection(stage, man) != dict(sorted(want.items())):
            probs.append(f"{stage}: manifest files+pages differ from the PREPARED members (C-a)")
    for rel in TRIAL_ID_MEMBERS.get(stage, ()):
        try:
            if json.loads((out / rel).read_bytes()).get("trial_id") != gv.trial.trial_id:
                probs.append(f"{stage}: {rel} does not record this trial_id (F6.2)")
        except (OSError, ValueError, AttributeError):
            probs.append(f"{stage}: {rel} unreadable for the trial_id check")
    return list(dict.fromkeys(probs))


def evaluate(gv) -> None:
    """The F4 stage-state table over the enforced stages, run by every gate (and the F7.3 live-file check): no INTENT
    + an artifact -> INVALID (registration-artifact; before the AUDIT-ACK the gate already refused); INTENT or
    PREPARED without CREATED -> pending while a live owner holds the lock, else stage-incomplete / recovery; CREATED ->
    created_problems -> INVALID (stage-replaced)."""
    import s1_trial
    for stage in TABLE:
        if stage not in ENFORCED:
            continue
        m = stage_rows(gv.rows, stage)
        if m["intent"] is None:
            present = _artifacts_present(gv.out, stage)
            if present:
                s1_trial.invalidate(gv.trial, "registration-artifact", {"stage": stage, "present": present},
                                    root=gv.root, mailbox=gv.mailbox)
                raise SystemExit(f"stage {stage}: artifacts {present[:3]} with no INTENT: INVALID "
                                 f"(registration-artifact)")
            continue
        if m["created"] is not None:
            probs = created_problems(gv, stage, m)
            if probs:
                s1_trial.invalidate(gv.trial, "stage-replaced", {"stage": stage, "problems": probs}, root=gv.root,
                                    mailbox=gv.mailbox)
                raise SystemExit(f"stage {stage}: {probs[:3]}: INVALID (stage-replaced)")
            continue
        lk = _lock(gv, stage)
        try:
            rows = j.read_trial(gv.trial.trial_id, gv.trial.genesis, gv.mailbox)       # re-validated under the lock
            m = stage_rows(rows, stage)
            if m["created"] is None:
                _resolve(gv, stage, m, gv.mailbox, None)
        finally:
            lk.release()
```

`s1_trial.gate`: insert `import s1_stage; s1_stage.evaluate(Gate(root, out, tr, rows, st_, mailbox))` immediately
before the `s1_slot.evidence_check` hook.

Add `"s1_stage.py"` to BUNDLE_CODE and to the test BUNDLE tuple.

- [ ] **Step 5: GREEN.** Run `test_s1_a3_stage.py` (three times, because of the child processes) and all earlier A3
  files into `a3/t8_green.txt`.
- [ ] **Step 6: Full suite, old->new, hashes.** With `ENFORCED = frozenset()`, expected: none apart from the BUNDLE
  tuple. Save `a3/t8_full.txt`, `a3/t8_old_new.md` and `a3/t8_hashes.txt`.
- [ ] **Step 7: Controller review and commit.** Message: `S1 A3 Task 8: stage engine (INTENT/PREPARED/CREATED,
  staging, recovery, stage table)`, listing map rows 14, 15, 18, 50, 58, 82–89, 100, 101, 116, 122–129, 131, 136,
  142, 163, 164, 206–208, 212, 220, 221, 225, 226, 228, 229, 317 and 331, with the Co-Authored-By line. Push and
  assert the HEAD SHA.

---

### Task 9: Request policy and the audit stage (F4.6, F4.9 audit rows, F9; C-a, C-b, C-e)

**Files:**
- Modify: `research/s1/s1_collect.py`:
  - add `CA_BATCH = 50`, `CA_FAMILY = "corporate_actions"`, `audit_policy`, `_Authorizer`;
  - `_get` and `_paged` take the authorizer and the `StageWork`;
  - `_corporate_actions` takes `(client, auth, keys, scope, symbols, start, end, sw, pages_prefix)`;
  - `do_audit` runs as stage `audit`;
  - `_reserve`, `_abort` and `_run_attempt` are kept for nothing else and removed in Task 12.
- Modify: `research/s1/s1_stage.py`: `ENFORCED = frozenset({"audit"})`.
- Modify: `research/s1/s1_tests/conftest.py:s1_plan_audit`. The synthetic audit rows are replaced by
  `s1_stage.run(gv, "audit", …)` with a fixture work that stages the same files as before (calendar page + derived
  files; provenance = the calendar request). The bytes are unchanged; `attempt.json` gains `trial_id` and
  `intent_at`.
- Create: `research/s1/s1_tests/test_s1_a3_audit.py`

**Interfaces:**
- Consumes: Task 8 `s1_stage.run`, `StageWork`, `StageAbort`, `manifest_projection`; Task 5 `gate`, `verify_ack`,
  `ack_record`.
- Produces (`s1_collect`):
  - `audit_policy(plan: dict, cutoff: str) -> dict` (the F4.6 policy object with the F4.9 audit families);
  - `class _Authorizer(policy)` with `.authorize(family, scope, url, params) -> (n, page_relpath)`,
    `.record(family, scope, n, url, params, retrieved_utc, status, page_relpath, page_sha256)`,
    `.page_done(data) -> str | None`, `.finished() -> bool` and `.provenance: list`;
  - `do_audit(root, ack_id, client, keys, *, mailbox=None) -> dict` (the published manifest).

- [ ] **Step 1: Interface stub.**
  - `audit_policy` returns `{"families": []}`.
  - `_Authorizer.authorize` returns `(0, "audit/pages/unchecked.json")` and refuses nothing; `record` appends
    nothing.
  - `do_audit` keeps its c9b4322 body behind `s1_trial.gate`, so it still writes straight into s1_out with
    `cutoff = _ny_date(c.now_utc())` after the reservation.

- [ ] **Step 2: Write the failing tests.** Create `research/s1/s1_tests/test_s1_a3_audit.py`:

```python
"""Addendum 3 rev 5 F4.6 (the deterministic request policy enforced in _get/_paged before sending, provenance,
provider anomaly), F4.9 audit rows (calendar + corporate_actions/audit), F9 (audit as a stage after the AUDIT-ACK),
C-a (manifest projection), C-b (cross-midnight cutoff), C-e (positive path isolated). Behavioural RED against the
Task 9 stub (s1_evidence/a3/t9_red.txt). Injected httpx.MockTransport clients only; tmp mailbox; spies."""
import itertools
import json
import random
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import s1_collect as k
import s1_common as c
import s1_journal as j
import s1_stage as sg
import s1_trial as t
from conftest import Spies, s1_mailbox

UTC = timezone.utc
NOW = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)
START = datetime(2026, 10, 26, 13, 30, tzinfo=UTC)
KEYS = ("KEYID-dummy-123", "SECRET-dummy-456")
CAL = [{"date": d.isoformat(), "open": "09:30", "close": "16:00"}
       for d in (date(2026, 10, 1) + timedelta(days=i) for i in range(300)) if d.weekday() < 5]


class Provider:
    """A synthetic Alpaca: calendar listing; corporate-action pages per batch, with optional tokens."""

    def __init__(self, pages_per_batch=None, tokens=None, status=None):
        self.pages_per_batch, self.tokens, self.status = pages_per_batch or {}, tokens, status or {}
        self.sent = []

    def __call__(self, req):
        self.sent.append(req)
        url = str(req.url).split("?")[0]
        if url in self.status:
            return httpx.Response(self.status[url], headers={"Location": "https://evil.example.com/x"})
        if url == k.CAL_URL:
            return httpx.Response(200, json=CAL)
        syms = req.url.params.get("symbols")
        n = sum(1 for r in self.sent if str(r.url).split("?")[0] == url and r.url.params.get("symbols") == syms) - 1
        last = n + 1 >= self.pages_per_batch.get(syms, 1)
        tok = None if last else (self.tokens(n) if self.tokens else f"t-{syms[:6]}-{n}")
        return httpx.Response(200, json={"corporate_actions": {}, "next_page_token": tok})


def setup(root, symbols=("A",), now=NOW, start=START, opening_close="2026-10-23"):
    with _clock(now - timedelta(hours=1)):
        k.write_plan(root, start, opening_close, list(symbols), "2026-03-17")
    s1_mailbox(root, "audit-ack", c.audit_token(Path(root) / "s1_out"), now - timedelta(minutes=30))


def audit(root, monkeypatch, provider, now=NOW):
    sp = Spies(monkeypatch)
    with _clock(now):
        m = k.do_audit(root, "audit-ack", sp.client(provider), KEYS)
    return m, sp


def commitment(root):
    tr = t.open_trial(Path(root) / "mailbox.sqlite3")
    return json.loads((sg.staging_dir(root, tr.trial_id, "audit") / "prepared.json").read_bytes())


def kinds(root):
    tr = t.open_trial(Path(root) / "mailbox.sqlite3")
    return [(r_.kind, r_.subject) for r_ in j.read_trial(tr.trial_id, tr.genesis, Path(root) / "mailbox.sqlite3")]


class _clock:
    def __init__(self, at):
        self.at = at

    def __enter__(self):
        self.old = c.now_utc
        c.now_utc = self.at if callable(self.at) else (lambda: self.at)

    def __exit__(self, *exc):
        c.now_utc = self.old


def test_audit_policy_is_exactly_the_f49_audit_rows():
    syms = [f"S{i:03d}" for i in range(120)]
    plan = {"calendar_range": ["2026-10-13", "2027-05-10"], "ca_symbols": syms, "ca_range": ["2026-03-17", "2026-10-26"]}
    fixed = {"region": "us", "data_quality": "all", "sort": "asc", "limit": 1000}
    batches = [syms[0:50], syms[50:100], syms[100:120]]
    assert k.audit_policy(plan, "2026-10-13") == {
        "redirects": False, "max_pages": 200, "cutoff": "2026-10-13",
        "families": [
            {"name": "calendar", "url": "https://paper-api.alpaca.markets/v2/calendar", "scope": "audit",
             "batches": None, "base_params": {"start": "2026-10-13", "end": "2027-05-10", "date_type": "TRADING"},
             "paged": False, "page_template": "audit/pages/calendar.json"},
            {"name": "corporate_actions", "url": "https://data.alpaca.markets/v1/corporate-actions", "scope": "audit",
             "batches": batches,
             "base_params": [dict(fixed, symbols=",".join(b), start="2026-03-17", end="2026-10-13") for b in batches],
             "paged": True, "page_template": "audit/pages/ca_{i:03d}_page{n:03d}.json"}]}


def test_normal_audit_authorizes_calendar_and_ca_batches_and_commits_every_member(tmp_path, monkeypatch):
    syms = [f"S{i:03d}" for i in range(120)]
    setup(tmp_path, syms)
    prov = Provider(pages_per_batch={",".join(syms[0:50]): 2})
    m, sp = audit(tmp_path, monkeypatch, prov)
    com = commitment(tmp_path)
    pages = sorted(p["page_relpath"] for p in com["provenance"])
    assert pages == ["audit/pages/ca_000_page000.json", "audit/pages/ca_000_page001.json",
                     "audit/pages/ca_001_page000.json", "audit/pages/ca_002_page000.json", "audit/pages/calendar.json"]
    assert set(com["members"]) == set(sg.FIXED_TREE["audit"]) | set(pages)
    assert sp.n["request"] == len(com["provenance"]) == 5
    assert kinds(tmp_path) == [("STAGE-INTENT", "stage/audit"), ("STAGE-PREPARED", "stage/audit"),
                               ("STAGE-CREATED", "stage/audit")]


def test_unpredictable_tokens_and_page_counts_complete_with_full_provenance(tmp_path, monkeypatch):
    syms = [f"S{i:03d}" for i in range(140)]
    setup(tmp_path, syms)
    rnd = random.Random(20261103)
    per = {",".join(syms[i:i + 50]): rnd.randint(1, 4) for i in range(0, 140, 50)}
    prov = Provider(pages_per_batch=per, tokens=lambda n: f"{rnd.getrandbits(64):016x}")
    audit(tmp_path, monkeypatch, prov)
    pv = commitment(tmp_path)["provenance"]
    assert len(pv) == 1 + sum(per.values()) == len(prov.sent)
    for a, b in zip(pv, pv[1:]):
        if b["n"] > 0:
            assert b["page_token_from"] == a["page_relpath"] and "page_token" in b["params"]


CASES = ["repeated-token", "over-max-pages", "redirect", "other-host", "wrong-endpoint", "changed-base",
         "outside-batch", "other-paper-path"]


@pytest.mark.parametrize("case", CASES)
def test_structural_refusals_send_no_further_request_then_invalid(tmp_path, monkeypatch, case):
    syms = [f"S{i:03d}" for i in range(60)]
    setup(tmp_path, syms)
    frozen = k.audit_policy
    prov = Provider()
    if case == "repeated-token":
        prov = Provider(pages_per_batch={",".join(syms[:50]): 5}, tokens=lambda n: "same-token")
    elif case == "over-max-pages":
        prov = Provider(pages_per_batch={",".join(syms[:50]): 10_000})
    elif case == "redirect":
        prov = Provider(status={k.CA_URL: 302})
    else:                                                                 # the code deviates from the committed policy
        if case == "other-host":
            monkeypatch.setattr(k, "CA_URL", "https://evil.example.com/v1/corporate-actions")
        elif case == "wrong-endpoint":
            monkeypatch.setattr(k, "CA_URL", "https://data.alpaca.markets/v1beta1/corporate-actions")
        elif case == "changed-base":
            monkeypatch.setattr(k, "CA_FIXED", dict(k.CA_FIXED, limit=500))
        elif case == "outside-batch":
            monkeypatch.setattr(k, "CA_BATCH", 40)
        elif case == "other-paper-path":
            monkeypatch.setattr(k, "CAL_URL", "https://paper-api.alpaca.markets/v2/orders")
        monkeypatch.setattr(k, "audit_policy", lambda plan, cutoff, f=frozen: _policy_with_original_constants(
            f, plan, cutoff))
    with pytest.raises(SystemExit, match=r"INVALID \(provider-structural\)"):
        audit(tmp_path, monkeypatch, prov)
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    staging = sg.staging_dir(tmp_path, tr.trial_id, "audit")
    aborted = json.loads((staging / "ABORTED.json").read_bytes())
    assert len(prov.sent) == len(aborted["provenance"])                    # nothing sent beyond the provenance
    if case == "over-max-pages":
        assert len(prov.sent) == 1 + 200
    if case in ("other-host", "wrong-endpoint", "changed-base", "outside-batch", "other-paper-path"):
        assert {str(r.url).split("?")[0] for r in prov.sent} <= {"https://paper-api.alpaca.markets/v2/calendar"}
    assert [kd for kd, _ in kinds(tmp_path)] == ["STAGE-INTENT", "TRIAL-INVALID"]
    assert not (tmp_path / "s1_out" / "audit").exists()


ORIGINAL = {"CAL_URL": "https://paper-api.alpaca.markets/v2/calendar",
            "CA_URL": "https://data.alpaca.markets/v1/corporate-actions",
            "CA_FIXED": {"region": "us", "data_quality": "all", "sort": "asc", "limit": 1000}, "CA_BATCH": 50}


def _policy_with_original_constants(f, plan, cutoff):
    """The policy the INTENT commits is built from the registered constants; the test then makes the request path
    deviate (the constants the code sends from were changed after import)."""
    saved = {n: getattr(k, n) for n in ORIGINAL}
    try:
        for n, v in ORIGINAL.items():
            setattr(k, n, v)
        return f(plan, cutoff)
    finally:
        for n, v in saved.items():
            setattr(k, n, v)


def test_authorizer_refuses_a_second_calendar_request_and_an_unlisted_family():
    plan = {"calendar_range": ["2026-10-13", "2027-05-10"], "ca_symbols": [], "ca_range": ["2026-03-17", "2026-10-26"]}
    pol = k.audit_policy(plan, "2026-10-13")
    auth = k._Authorizer(pol)
    base = pol["families"][0]["base_params"]
    assert auth.authorize("calendar", "audit", k.CAL_URL, base) == (0, "audit/pages/calendar.json")
    auth.record("calendar", "audit", 0, k.CAL_URL, base, NOW.isoformat(), 200, "audit/pages/calendar.json", "0" * 64)
    assert auth.page_done(CAL) is None
    with pytest.raises(k.Structural, match="no family"):
        auth.authorize("calendar", "audit", k.CAL_URL, base)                # a second calendar request
    auth2 = k._Authorizer(pol)
    with pytest.raises(k.Structural, match="not the next family"):
        auth2.authorize("bars", "final", k.BARS_URL, {})


def test_every_sent_request_is_in_provenance(tmp_path, monkeypatch):
    syms = [f"S{i:03d}" for i in range(55)]
    setup(tmp_path, syms)
    prov = Provider(pages_per_batch={",".join(syms[:50]): 3})
    audit(tmp_path, monkeypatch, prov)
    pv = commitment(tmp_path)["provenance"]
    assert [(str(r.url).split("?")[0], dict(r.url.params)) for r in prov.sent] == [
        (p["url"], {n: str(v) for n, v in p["params"].items()}) for p in pv]
    for f in tmp_path.rglob("*"):
        if f.is_file() and f.name != "mailbox.sqlite3":
            txt = f.read_bytes().decode("utf-8", "ignore")
            assert KEYS[0] not in txt and KEYS[1] not in txt


def test_retrieved_utc_is_the_actual_observation_instant(tmp_path, monkeypatch):
    setup(tmp_path)
    ticks = itertools.count()
    clock = lambda: NOW + timedelta(seconds=next(ticks))                   # noqa: E731
    sp = Spies(monkeypatch)
    prov = Provider()
    seen = []

    def handler(req):
        seen.append(clock())                                              # the provider's own clock reading
        return prov(req)
    with _clock(clock):
        k.do_audit(tmp_path, "audit-ack", sp.client(handler), KEYS)
    src = json.loads((tmp_path / "s1_out" / "audit" / "calendar_source.json").read_bytes())
    pv = commitment(tmp_path)["provenance"]
    assert c.aware(src["retrieved_utc"]) > seen[0] and src["retrieved_utc"] == pv[0]["retrieved_utc"]


@pytest.mark.parametrize("pre,date_,start,oc", [
    (datetime(2026, 10, 13, 3, 59, 59, 999999, tzinfo=UTC), "2026-10-12", START, "2026-10-23"),
    (datetime(2026, 11, 1, 3, 59, 59, 999999, tzinfo=UTC), "2026-10-31", datetime(2026, 11, 16, 14, 30, tzinfo=UTC),
     "2026-11-13")], ids=["midnight", "dst-fall-back"])
def test_cutoff_is_the_intent_new_york_date_across_midnight(tmp_path, monkeypatch, pre, date_, start, oc):
    setup(tmp_path, ("A",), now=pre - timedelta(minutes=1), start=start, opening_close=oc)
    post = pre + timedelta(microseconds=2)
    now = [pre - timedelta(seconds=10)]
    real = j.append

    def at_intent(trial_id, gen, req, ctx_fn, **kw):
        if req.kind == "STAGE-INTENT":
            kw["clock"] = lambda: pre
            res = real(trial_id, gen, req, ctx_fn, **kw)
            now[0] = post                                                 # reservation and requests after midnight
            return res
        return real(trial_id, gen, req, ctx_fn, **kw)
    monkeypatch.setattr(j, "append", at_intent)
    prov = Provider()
    sp = Spies(monkeypatch)
    with _clock(lambda: now[0]):
        m = k.do_audit(tmp_path, "audit-ack", sp.client(prov), KEYS)
    reserved = json.loads((tmp_path / "s1_out" / "audit" / "attempt.json").read_bytes())["reserved_utc"]
    assert m["publication_cutoff"] == date_ != c.aware(reserved).astimezone(c.NY).date().isoformat()
    assert all(r.url.params.get("end") == date_ for r in prov.sent if "corporate-actions" in str(r.url))


def test_cutoff_same_day_positive_path(tmp_path, monkeypatch):
    setup(tmp_path)
    m, sp = audit(tmp_path, monkeypatch, Provider())
    assert m["outcome"] == "COMPLETE" and m["publication_cutoff"] == NOW.astimezone(c.NY).date().isoformat()


LEGACY_MANIFEST_KEYS = {"publication_cutoff", "ca_window", "plan_sha256", "bundle_sha256", "outcome", "ack", "files",
                        "pages", "coverage", "limits"}


def test_manifest_shape_is_preserved_and_its_projection_equals_the_members(tmp_path, monkeypatch):
    setup(tmp_path, ("A", "B"))
    m, _ = audit(tmp_path, monkeypatch, Provider())
    assert set(m) == LEGACY_MANIFEST_KEYS
    assert set(m["files"]) == {"attempt.json", "calendar_source.json", "calendar.json", "corporate_actions.json",
                               "ca_problems.json"}
    com = commitment(tmp_path)
    want = {r: h for r, h in com["members"].items() if r != "audit/manifest.json"}
    assert sg.manifest_projection("audit", m) == want


def test_empty_ca_symbols_send_no_ca_request_and_the_audit_completes(tmp_path, monkeypatch):
    setup(tmp_path, ())
    prov = Provider()
    m, _ = audit(tmp_path, monkeypatch, prov)
    assert m["outcome"] == "COMPLETE" and [str(r.url).split("?")[0] for r in prov.sent] == [k.CAL_URL]


def test_request_order_is_the_collector_order(tmp_path, monkeypatch):
    syms = [f"S{i:03d}" for i in range(110)]
    setup(tmp_path, syms)
    prov = Provider()
    audit(tmp_path, monkeypatch, prov)
    order = [(str(r.url).split("?")[0], r.url.params.get("symbols", "")[:4]) for r in prov.sent]
    assert order == [(k.CAL_URL, ""), (k.CA_URL, "S000"), (k.CA_URL, "S050"), (k.CA_URL, "S100")]


def test_provider_anomaly_keeps_aborted_staging_no_prepared_and_invalidates(tmp_path, monkeypatch):
    syms = [f"S{i:03d}" for i in range(60)]
    setup(tmp_path, syms)
    prov = Provider()
    real = prov.__call__

    def flaky(req):
        if req.url.params.get("symbols", "").startswith("S050"):
            prov.sent.append(req)
            return httpx.Response(500, content=b"server error")
        return real(req)
    with pytest.raises(SystemExit, match=r"INVALID \(provider-structural\)"):
        audit(tmp_path, monkeypatch, flaky)
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    staging = sg.staging_dir(tmp_path, tr.trial_id, "audit")
    assert (staging / "ABORTED.json").is_file() and (staging / "audit" / "pages" / "ca_001_page000.json").is_file()
    assert not (staging / "prepared.json").exists()
    assert [kd for kd, _ in kinds(tmp_path)] == ["STAGE-INTENT", "TRIAL-INVALID"]
    with pytest.raises(SystemExit, match="INVALID"):                                    # F8.5: no retry
        audit(tmp_path, monkeypatch, Provider())


def test_audit_runs_as_a_stage_only_after_the_audit_ack(tmp_path, monkeypatch):
    with _clock(NOW - timedelta(hours=1)):
        k.write_plan(tmp_path, START, "2026-10-23", ["A"], "2026-03-17")
    prov = Provider()
    with pytest.raises(SystemExit, match="zero open trials"):
        audit(tmp_path, monkeypatch, prov)
    assert prov.sent == []
    s1_mailbox(tmp_path, "audit-ack", c.audit_token(tmp_path / "s1_out"), NOW - timedelta(minutes=30))
    audit(tmp_path, monkeypatch, prov)
    intent = j.first(j.subject_rows(j.read_trial(*_tg(tmp_path)), "stage/audit"), "STAGE-INTENT")
    env = json.loads((sg.staging_dir(tmp_path, t.open_trial(tmp_path / "mailbox.sqlite3").trial_id, "audit")
                      / "intent.json").read_bytes())
    assert intent.detail == j.detail_of(env) and env["request_policy"]["families"][0]["name"] == "calendar"


def _tg(root):
    tr = t.open_trial(Path(root) / "mailbox.sqlite3")
    return tr.trial_id, tr.genesis, Path(root) / "mailbox.sqlite3"


def test_audit_envelope_inputs_and_members(tmp_path, monkeypatch):
    setup(tmp_path)
    audit(tmp_path, monkeypatch, Provider())
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    env = json.loads((sg.staging_dir(tmp_path, tr.trial_id, "audit") / "intent.json").read_bytes())
    assert env["inputs"] == {"bundle": c.bundle_sha256(), "plan.json": c.sha256_file(tmp_path / "s1_out" / "plan.json")}
    assert env["acks"] == {"S1-AUDIT-ACK": tr.audit.sha} and env["stage"] == "audit" and env["trial_id"] == tr.trial_id


def test_members_are_the_fixed_names_plus_one_page_per_request(tmp_path, monkeypatch):
    setup(tmp_path, ("A",))
    audit(tmp_path, monkeypatch, Provider(pages_per_batch={"A": 3}))
    com = commitment(tmp_path)
    pages = [p["page_relpath"] for p in com["provenance"]]
    assert len(pages) == len(set(pages)) == 4 and set(com["members"]) == set(sg.FIXED_TREE["audit"]) | set(pages)


@pytest.mark.parametrize("victim", ["audit/calendar.json", "audit/pages/calendar.json", "audit/manifest.json",
                                    "audit/pages/ca_000_page000.json"])
@pytest.mark.parametrize("damage", ["changed", "deleted"])
def test_damaged_audit_member_is_invalid_before_use(tmp_path, monkeypatch, victim, damage):
    setup(tmp_path, ("A",))
    audit(tmp_path, monkeypatch, Provider())
    p = tmp_path / "s1_out" / victim
    if damage == "deleted":
        p.unlink()
    else:
        p.write_bytes(p.read_bytes() + b" ")
    sp = Spies(monkeypatch)
    with pytest.raises(SystemExit, match=r"INVALID \(stage-replaced\)"):
        t.gate(tmp_path, "use of the audit")
    sp.assert_zero()


@pytest.mark.parametrize("case", ["extra-page", "missing-page"])
def test_extra_page_or_orphan_provenance_is_invalid(tmp_path, monkeypatch, case):
    setup(tmp_path, ("A",))
    audit(tmp_path, monkeypatch, Provider())
    if case == "extra-page":
        (tmp_path / "s1_out" / "audit" / "pages" / "ca_000_page001.json").write_text("{}", encoding="utf-8")
    else:
        (tmp_path / "s1_out" / "audit" / "pages" / "ca_000_page000.json").unlink()
    with pytest.raises(SystemExit, match=r"INVALID \(stage-replaced\)"):
        t.gate(tmp_path, "orphan")


@pytest.mark.parametrize("case", ["commitment", "attempt", "page"])
def test_cross_trial_substitution_is_invalid(tmp_path_factory, monkeypatch, case):    # row 312 (OQ-36, E5.4)
    mine, other = tmp_path_factory.mktemp("mine"), tmp_path_factory.mktemp("other")
    setup(mine, ("A",))
    setup(other, ("A",))
    audit(mine, monkeypatch, Provider())
    audit(other, monkeypatch, Provider(pages_per_batch={"A": 2}))          # different page bytes for the page case
    tm, to = (t.open_trial(Path(r) / "mailbox.sqlite3").trial_id for r in (mine, other))
    assert tm != to
    if case == "commitment":
        src = sg.staging_dir(other, to, "audit") / "prepared.json"
        dst = sg.staging_dir(mine, tm, "audit") / "prepared.json"
    elif case == "attempt":
        src, dst = other / "s1_out" / "audit" / "attempt.json", mine / "s1_out" / "audit" / "attempt.json"
    else:
        src = other / "s1_out" / "audit" / "pages" / "ca_000_page000.json"
        dst = mine / "s1_out" / "audit" / "pages" / "ca_000_page000.json"
        assert src.read_bytes() != dst.read_bytes()
    shutil.copyfile(src, dst)                                               # the TEST substitutes tmp files
    with pytest.raises(SystemExit, match=r"INVALID \(stage-replaced\)"):
        t.gate(mine, "cross-trial substitution")


@pytest.mark.parametrize("case", ["multi-page", "empty-families"])
def test_valid_pagination_and_empty_families_are_not_anomalous(tmp_path, monkeypatch, case):   # row 319 (P-4)
    syms = ("A", "B") if case == "multi-page" else ()
    setup(tmp_path, syms)
    prov = Provider(pages_per_batch={"A,B": 3}) if case == "multi-page" else Provider()
    audit(tmp_path, monkeypatch, prov)
    assert kinds(tmp_path)[-1] == ("STAGE-CREATED", "stage/audit")
    assert all(k_ != "TRIAL-INVALID" for k_, _ in kinds(tmp_path))
    t.gate(tmp_path, "valid audit is usable")                              # no refusal, no INVALID
```

- [ ] **Step 3: Behavioural RED.** Run into `a3/t9_red.txt`.
  - Expected: no stage rows; `audit_policy` is `{"families": []}`; no Structural refusal from the policy; the
    cutoff after midnight is the reservation's date (c9b4322 behaviour: the cross-midnight cases fail as `B-old`);
    files are written straight into s1_out; no ABORTED staging.
  - `test_empty_ca…` and `test_request_order…` pass the c9b4322 path. Label them `retro`.
  - Revision 1: `test_cross_trial_substitution_is_invalid[*]` fails (no stage, no INVALID).
    `test_valid_pagination_and_empty_families…` fails on the stub's assertion of a STAGE-CREATED row. Its
    no-INVALID half is `ctrl` (Codex reply P-4).

- [ ] **Step 4: Implement.** In `s1_collect.py`, add after the constants:

```python
CA_BATCH = 50                     # F4.9: batch i = symbols[50i : 50i+50] (single-sourced)
CA_FAMILY = "corporate_actions"


def audit_policy(plan: dict, cutoff: str) -> dict:
    """F4.6/F4.9: the audit's deterministic request policy (committed by its INTENT; no request list, no host list:
    a request is authorized only by its family's exact URL)."""
    syms = list(plan["ca_symbols"])
    batches = [syms[i:i + CA_BATCH] for i in range(0, len(syms), CA_BATCH)]
    return {"redirects": False, "max_pages": MAX_PAGES, "cutoff": cutoff, "families": [
        {"name": "calendar", "url": CAL_URL, "scope": "audit", "batches": None,
         "base_params": {"start": plan["calendar_range"][0], "end": plan["calendar_range"][1],
                         "date_type": "TRADING"},
         "paged": False, "page_template": "audit/pages/calendar.json"},
        {"name": CA_FAMILY, "url": CA_URL, "scope": "audit", "batches": batches,
         "base_params": [dict(CA_FIXED, symbols=",".join(b), start=plan["ca_range"][0], end=cutoff) for b in batches],
         "paged": True, "page_template": "audit/pages/ca_{i:03d}_page{n:03d}.json"}]}


class _Authorizer:
    """F4.6 request path: each request must be the next one the committed policy allows (family and scope in
    order; the exact family URL; the exact base parameters of the current batch; page n+1 adds only the page_token of
    the immediately preceding validated page; at most max_pages pages; one request for an unpaged family) - checked
    BEFORE it is sent. Every request sent is recorded in provenance (credential-free)."""

    def __init__(self, policy: dict):
        self.policy, self.provenance = policy, []
        self.slots = []
        for fi, fam in enumerate(policy["families"]):
            self.slots += [(fi, None)] if fam["batches"] is None else [(fi, bi) for bi in range(len(fam["batches"]))]
        self.pos, self.n, self.token, self.seen, self.last_rel = 0, 0, None, set(), None

    def _current(self):
        if self.pos >= len(self.slots):
            raise Structural("a request with no family left in the policy (F4.6)")
        fi, bi = self.slots[self.pos]
        fam = self.policy["families"][fi]
        return fam, bi, (fam["base_params"][bi] if bi is not None else fam["base_params"])

    def authorize(self, family: str, scope: str, url: str, params: dict) -> tuple:
        fam, bi, base = self._current()
        if (family, scope) != (fam["name"], fam["scope"]):
            raise Structural(f"request {family}/{scope} is not the next family in the policy "
                             f"({fam['name']}/{fam['scope']})")
        if url != fam["url"]:
            raise Structural(f"{family}: URL outside the policy (only {fam['url']} is authorized)")
        if {n: v for n, v in params.items() if n != "page_token"} != base:
            raise Structural(f"{family}: base parameters or batch outside the policy")
        if self.n == 0 and "page_token" in params:
            raise Structural(f"{family}: page 0 carries a page_token")
        if self.n > 0 and (not fam["paged"] or params.get("page_token") != self.token):
            raise Structural(f"{family}: page_token is not the preceding page's next_page_token")
        if self.n >= self.policy["max_pages"]:
            raise Structural(f"{family}: more than {self.policy['max_pages']} pages")
        return self.n, fam["page_template"].format(i=bi if bi is not None else 0, n=self.n)

    def record(self, family, scope, n, url, params, retrieved_utc, status, page_relpath, page_sha256) -> None:
        self.provenance.append({"family": family, "scope": scope, "n": n, "url": url, "params": dict(params),
                                "page_token_from": self.last_rel if n > 0 else None, "retrieved_utc": retrieved_utc,
                                "status": status, "page_relpath": page_relpath, "page_sha256": page_sha256})
        self.last_rel = page_relpath

    def page_done(self, data) -> str:
        """After the page passed validation: the next page_token of this family/batch, or None (the family/batch
        ends; the next one starts at page 0). A repeated token or a page beyond max_pages is Structural."""
        fam, bi, base = self._current()
        token = data.get("next_page_token") if fam["paged"] and isinstance(data, dict) else None
        if not token:
            self.pos, self.n, self.token, self.seen, self.last_rel = self.pos + 1, 0, None, set(), None
            return None
        if token in self.seen:
            raise Structural(f"{fam['name']}: repeated next_page_token")
        self.seen.add(token)
        self.token, self.n = token, self.n + 1
        if self.n >= self.policy["max_pages"]:
            raise Structural(f"{fam['name']}: more than {self.policy['max_pages']} pages")
        return token

    def finished(self) -> bool:
        return self.pos >= len(self.slots)


def _get(client, auth, family, scope, url, params, headers, sw):
    """One authorized request (refused BEFORE sending if outside the policy); its raw page is staged and recorded."""
    n, rel = auth.authorize(family, scope, url, params)
    try:
        resp = client.get(url, params=params, headers=headers)
    except Exception as e:                                                # transport failure: no secrets in text
        auth.record(family, scope, n, url, params, c.now_utc().isoformat(), None, None, None)
        raise Structural(f"{rel}: transport error {type(e).__name__}") from None
    retrieved = c.now_utc()                                               # F4.5: the actual observation instant
    sw.put(rel, resp.content)
    auth.record(family, scope, n, url, params, retrieved.isoformat(), resp.status_code, rel,
                c.sha256_bytes(resp.content))
    if resp.status_code != 200:
        raise Structural(f"{rel}: HTTP {resp.status_code}" + (" (redirect, not followed)"
                                                               if 300 <= resp.status_code < 400 else ""))
    try:
        return json.loads(resp.content), retrieved
    except ValueError:
        raise Structural(f"{rel}: body is not JSON") from None


def _paged(client, auth, family, scope, url, base, headers, sw, validate) -> list:
    pages, token = [], None
    while True:
        data, _ = _get(client, auth, family, scope, url, dict(base, **({"page_token": token} if token else {})),
                       headers, sw)
        if validate:
            validate(data, Path(auth.provenance[-1]["page_relpath"]).stem)
        pages.append(data)
        token = auth.page_done(data)
        if token is None:
            return pages


def _corporate_actions(client, auth, keys, scope, symbols, start, end, sw):
    f = c.fetch()
    batched = []
    for i in range(0, len(symbols), CA_BATCH):
        batch = symbols[i:i + CA_BATCH]
        base = dict(CA_FIXED, symbols=",".join(batch), start=start, end=end)
        for page in _paged(client, auth, CA_FAMILY, scope, CA_URL, base, _headers(keys), sw, f.validate_ca_page):
            batched.append((batch, page))
    return f.classify_ca(batched)


def _attempt_files(sw, stage: str) -> tuple:
    """The legacy manifest maps: `files` keyed by basename (every <stage>/*.json except manifest.json), `pages` keyed by
    s1_out-relative path (C-a: the projection of these equals the PREPARED members minus the manifest)."""
    files = {Path(r).name: c.sha256_bytes(b) for r, b in sw.files.items()
             if r.count("/") == 1 and r.startswith(stage + "/") and r != f"{stage}/manifest.json"}
    pages = {r: c.sha256_bytes(b) for r, b in sw.files.items() if r.count("/") >= 2}
    return dict(sorted(files.items())), dict(sorted(pages.items()))


def _provider_abort(auth, e):
    structural = isinstance(e, (Structural, c.fetch().Structural))
    raise s1_stage.StageAbort("provider-structural", {
        "outcome": "ABORTED", "error_type": type(e).__name__, "error": str(e) if structural else type(e).__name__,
        "provenance": auth.provenance})


def do_audit(root, ack_id: str, client, keys, *, mailbox=None) -> dict:
    """F9: stage `audit` after the AUDIT-ACK. The INTENT commits the audit request policy (F4.6) with the cutoff = the
    New York date of the INTENT row's `at` (F4.9, C-b; disclosed change from c9b4322's post-reservation clock read).
    Work in staging; Structural/validation failure -> ABORTED staging + INVALID (provider-structural), no retry."""
    import s1_stage
    import s1_trial
    gv = s1_trial.gate(root, "audit", mailbox=mailbox)
    _require_no_redirects(client)
    out = _out(root)
    c.registration_gate(out, "audit", mailbox=mailbox)
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    a = s1_trial.verify_ack(gv.trial, gv.rows, "S1-AUDIT-ACK", ack_id,
                            dict(s1_trial.artifact_fields("S1-AUDIT-ACK", out), trial_id=plan["trial_id"],
                                 bundle_sha256=c.bundle_sha256()))
    ack = s1_trial.ack_record(a)
    if not c.aware(ack["created_utc"]) > c.aware(plan["created_utc"]):
        raise SystemExit("audit refused: the AUDIT-ACK is not after the plan it binds")
    if c.aware(plan["planned_start"]) <= c.now_utc():
        raise SystemExit("planned START has passed: re-register")

    def work(sw):
        auth = _Authorizer(sw.policy)
        cutoff = sw.policy["cutoff"]
        sw.put_json("audit/attempt.json", {"reserved_utc": c.now_utc().isoformat(), "ack": ack,
                                           "trial_id": sw.trial_id, "intent_at": sw.intent_at})
        try:
            params = {"start": plan["calendar_range"][0], "end": plan["calendar_range"][1], "date_type": "TRADING"}
            cal, retrieved = _get(client, auth, "calendar", "audit", CAL_URL, params, _headers(keys), sw)
            auth.page_done(cal)
            sessions = _validate_calendar(cal, plan, ack)
            page = "audit/pages/calendar.json"
            sw.put_json("audit/calendar_source.json", {"source": CAL_URL, "params": params,
                                                       "retrieved_utc": retrieved.isoformat(), "page": page,
                                                       "page_sha256": c.sha256_bytes(sw.files[page])})
            actions, problems = _corporate_actions(client, auth, keys, "audit", plan["ca_symbols"],
                                                   plan["ca_range"][0], cutoff, sw)
            if not auth.finished():
                raise Structural("audit: the policy's families were not all requested")
        except Exception as e:                                         # noqa: BLE001 - recorded type/Structural text
            _provider_abort(auth, e)
        sw.put_json("audit/calendar.json", cal)
        sw.put_json("audit/corporate_actions.json", actions)
        sw.put_json("audit/ca_problems.json", problems)
        files, pages = _attempt_files(sw, "audit")
        sw.put_json("audit/manifest.json", {
            "publication_cutoff": cutoff, "ca_window": [plan["ca_range"][0], cutoff],
            "plan_sha256": c.sha256_file(out / "plan.json"), "bundle_sha256": c.bundle_sha256(),
            "outcome": "COMPLETE", "ack": ack, "files": files, "pages": pages,
            "coverage": {"calendar_sessions": len(sessions), "ca_records": len(actions),
                         "ca_problems": len(problems)}, "limits": LIMITS})
        return auth.provenance

    s1_stage.run(gv, "audit", inputs={"plan.json": c.sha256_file(out / "plan.json"), "bundle": c.bundle_sha256()},
                 acks={"S1-AUDIT-ACK": a.sha}, policy_fn=lambda at: audit_policy(plan, _ny_date(at)), work=work,
                 mailbox=mailbox)
    return json.loads((out / "audit" / "manifest.json").read_text(encoding="utf-8"))
```

Add `import s1_stage` at the top of `s1_collect.py`; `s1_stage` imports only s1_common/s1_journal/s1_locks. Change
`s1_stage.ENFORCED` to `frozenset({"audit"})`.

The conftest `s1_plan_audit` fixture work stages the same objects through `sw.put`/`sw.put_json`:
- the raw calendar page bytes `json.dumps(raw_cal).encode("utf-8")`;
- the derived files, with `attempt.json` = `{"reserved_utc", "ack", "trial_id", "intent_at"}`.

Its provenance is one calendar entry. It passes `policy_fn=lambda at: k.audit_policy(plan, ny_date(at))` and the
fixture's clock (`reserved - 1 s`). The fixture makes no CA requests. That is a synthetic shortcut, stated in its
comment:
- the stage engine does not compare provenance with the policy;
- the real collector enforces completeness itself (`auth.finished()`), and `test_s1_a3_audit.py` tests that path.

- [ ] **Step 5: GREEN.** Run `test_s1_a3_audit.py` and all A3 files into `a3/t9_green.txt`. Save
  `a3/t9_cutoff_midnight.txt` and `a3/t9_cutoff_positive.txt`: separate runs of the two cutoff tests, isolated per
  C-e.
- [ ] **Step 6: Full suite, old->new.** Expected:
  - **Intended (F4.6/F4.9):** `test_s1_collect.py` audit tests now find raw pages under s1_out only after
    publication, and a second `do_audit` refuses with "already CREATED" instead of "an attempt already exists".
    Record the exact message per test.
  - **Intended (C-b):** any test asserting `publication_cutoff` = the reservation-time date where these differ.
  - **Fixture:** helpers that hand-write `s1_out/audit` after the AUDIT-ACK without stage rows are now INVALID
    (F4 "no INTENT"). Migrate them to `s1_plan_audit`.

  Save `a3/t9_full.txt`, `a3/t9_old_new.md` and `a3/t9_hashes.txt`.
- [ ] **Step 7: Controller review and commit.** Message: `S1 A3 Task 9: request policy in _get/_paged and the audit
  stage`, listing map rows 90, 91, 93–99, 102, 110, 111, 115–117, 119, 120, 165, 169, 209–211, 213, 214, 216, 219,
  222, 312 and 319, with the Co-Authored-By line. Push and assert the HEAD SHA.

---

### Task 10: Pre-START stages: opening seal, start_attest (OPENING-ACK), prereg (RUN-ACK) (F3 opening rule, F4.8 rows 2–4, F7.2–F7.4; E3 (pending), E5.3, E5.5; OQ-0, OQ-15, OQ-17, OQ-18, OQ-30, OQ-37)

**Files:**
- Modify: `research/s1/s1_stage.py`:
  - `run` gains the keywords `extra_gate=None` (a callable `rows -> str | None`, AND-ed with `permitted`) and
    `publish_ctx=None` (a context-manager factory wrapping `before_publish` + publication);
  - `ENFORCED = frozenset({"audit", "opening", "start_attest", "prereg"})`;
  - `committed_commitment` (added in Task 8) is also used by `evidence_manifest`.
- Modify: `research/s1/s1_checkpoint.py`:
  - add `_opening_stage(gv, out, day, cal, now, mailbox) -> dict`;
  - `run_opening_checkpoint` runs `s1_slot.finalize_close`, then `_opening_stage`, after its worker completes;
  - `_before_opening_build` (the legacy N-2 orphan re-check) is removed; F3 supersedes it.
- Modify: `research/s1/s1_slot.py:opening_gate`. Only the opening STAGE-INTENT decides "already decided"; the legacy
  seal-file clause is removed.
- Modify: `research/s1/s1_trial.py`:
  - add `verify_opening_ack(gv, cal) -> Ack`, `opening_issuance(root, mailbox=None) -> dict` and
    `evidence_manifest(root, rows, journal_seq) -> dict` and `opening_manifest_check(gv, a=None) -> None`
    (E5.5 exact format and membership; INVALIDATE on mismatch). The gate gains the hook
    `opening_manifest_check(gv)` after `s1_slot.evidence_check`;
  - `token()` derives `opening_slot` (the earliest QUALIFIED, OQ-37/row 270) and `evidence_manifest_sha256` from
    the journal.
- Modify: `research/s1/s1_run.py`:
  - `attest_start` (lines 420–466) and `do_prereg` (lines 485–542) run as stages;
  - start_attest stays SINGLE (OQ-15). `_opening_books` publishes `opening_books.json` before the start_attest
    INTENT: write once, or verify that an existing file equals the recomputation from the committed opening seal,
    otherwise refuse. Its sha256 is an envelope input and `attest_start.json`'s `opening_books_sha256`;
  - the BLOCKED path follows E3, pending Codex acceptance of E3: a pre-INTENT refusal record over committed inputs
    only, with no journal row; Step 4b.
- Modify: `research/s1/s1_tests/conftest.py`. `s1_state` and `s1_register` issue the OPENING-ACK through `s1_ack`
  without `opening_slot` or `evidence_manifest_sha256` overrides (the token derives both). They issue it only after
  `close_out(root, cal, oc)` has run the finalizer to the W slot's E, so that every opening-close slot is terminal
  (F7.2(b) literal, OQ-37 ruling). Every later fixture time is shifted after that instant.
- Create: `research/s1/s1_tests/test_s1_a3_prestart.py`; append to `test_s1_a3_codex_probes.py`.

**Interfaces:**
- Consumes: Task 6/7 `Worker`, `first_qualified`, `seal_bytes`, `_resolution_evidence`, `finalize_close`; Task 8
  `run`, `stage_rows`, `permitted`; Task 5 `verify_ack`.
- Produces:
  - `s1_trial.verify_opening_ack(gv, cal) -> Ack`. It raises Refusal unless all of these hold within
    `rows[:journal_seq]`:
    - the OPENING-ACK's `opening_slot` is the first QUALIFIED opening slot;
    - EVERY scheduled opening-close slot has a terminal row (F7.2(b) literal);
    - the opening stage is CREATED and the trial is ACTIVE;
    - the seal, receipt, plan and audit hashes match;
    - `evidence_manifest_sha256` equals the sha256 of the reconstructed manifest (E5.5; a mismatch is
      INVALIDATE registration-artifact, not a refusal);
    - the ACK's `created` is before now, the start_attest INTENT instant (E5.3).
  - `s1_trial.opening_issuance(root, mailbox=None) -> {"eligible": bool, "reasons": [...], "opening_slot",
    "journal_seq", "journal_head_sha256", "opening_seal_sha256", "opening_receipt_sha256"}`.
  - `s1_checkpoint._opening_stage(...)`.
  - `s1_trial.evidence_manifest(root, rows, journal_seq) -> dict`: exactly E5.5 (Erratum 1 r1). The shape is
    `{"trial_id", "journal_seq", "journal_head_sha256", "files": {relpath: sha256}}`, where `files` covers, for rows
    with seq <= journal_seq:
    - plan.json and opening_receipt.json;
    - every CREATED audit member;
    - every file of every QUALIFIED or FAILED tree;
    - every CREATED stage member;
    - the staging `intent.json` and `prepared.json` of every stage with an INTENT or PREPARED row, keyed
      `staging/<stage>/<name>`.

    Relpaths are relative to s1_out; keys are sorted by `c.canonical`. Its sha256 is
    `c.sha256_bytes(c.canonical(...))`.
  - `s1_run.blocked_reasons_record(out, cal) -> dict` (E3, pending Codex acceptance of E3): the pure recomputation
    `{"trial_id", "reasons"}` from committed inputs only; and `s1_run.blocked_close_evidence(out) -> str`
    = `sha256(c.canonical({"trial_id", "reasons"}))` of it (E3.4 r1), which Task 4's CLOSE check calls.

- [ ] **Step 1: Interface stub.**
  - `verify_opening_ack` returns the trial's OPENING-ACK or raises only if it is absent;
  - `opening_issuance` returns `{"eligible": True, "reasons": []}`;
  - `_opening_stage` returns `{}` and leaves the legacy seal path in place;
  - `attest_start`/`do_prereg` keep their c9b4322 bodies behind the gate;
  - `s1_stage.run` accepts and ignores the two new keywords.

- [ ] **Step 2: Write the failing tests.** `research/s1/s1_tests/test_s1_a3_prestart.py`:

```python
"""Addendum 3 rev 5 F3 (the opening seal is a stage, opened only after the first QUALIFIED opening slot with every
earlier slot terminal), F4.8 rows opening/start_attest/prereg, F7.2 (OPENING-ACK verified against the journal;
issuance helper; (b) literal), F7.3 (live-file check), F7.4 (deadlines; RUN-ACK fields), E3 (BLOCKED record; pending
Codex acceptance of E3), E5.3, E5.5 (evidence manifest; INVALIDATE on mismatch), E5.6 (opening window).
Behavioural RED against the Task 10 stub (s1_evidence/a3/t10_red.txt). Synthetic ledgers; tmp mailbox; spies."""
import json
from datetime import timedelta
from pathlib import Path

import pytest
import s1_checkpoint as ck
import s1_common as c
import s1_journal as j
import s1_run as r
import s1_seal as z
import s1_slot as sl
import s1_stage as sg
import s1_trial as t
from conftest import (Ledger, S1_PROCESS, S1_RECEIPT, Spies, _Clock, s1_ack, s1_jappend, s1_mailbox,
                      s1_opening_checkpoint, s1_plan_audit, s1_state)

START = "2026-10-26T13:30:00+00:00"


def mb(root):
    return Path(root) / "mailbox.sqlite3"


def jrows(root):
    tr = t.open_trial(mb(root))
    return j.read_trial(tr.trial_id, tr.genesis, mb(root))


def stage_kinds(root, stage):
    return [x.kind for x in j.subject_rows(jrows(root), j.stage_subject(stage))]


def opened(root, minutes=45):
    start, cal, oc, _ = s1_plan_audit(root, START)
    lg = Ledger(Path(root) / "opening_ledger.sqlite3")
    rep = s1_opening_checkpoint(root, lg, oc, cal, S1_RECEIPT, minutes=minutes)
    return start, cal, oc, lg, rep


def opening_slot(cal, oc, minutes):
    return z.close_of(oc, cal) + timedelta(minutes=minutes)


def env(root, stage):
    tr = t.open_trial(mb(root))
    return json.loads((sg.staging_dir(root, tr.trial_id, stage) / "intent.json").read_bytes())


def com(root, stage):
    tr = t.open_trial(mb(root))
    return json.loads((sg.staging_dir(root, tr.trial_id, stage) / "prepared.json").read_bytes())


@pytest.mark.parametrize("case", ["pending-earlier", "failed-earlier", "first-qualified"])
def test_opening_intent_only_after_the_first_qualified_slot_and_earlier_slots_terminal(tmp_path, case):
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    lg = Ledger(tmp_path / "opening_ledger.sqlite3")
    s45, s47 = opening_slot(cal, oc, 45), opening_slot(cal, oc, 47)
    if case == "pending-earlier":
        s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(s45), at=s45 + timedelta(seconds=1))
    elif case == "failed-earlier":
        with _Clock(s45 - timedelta(seconds=5)):
            ck.run_opening_checkpoint(tmp_path, lg.path, s45, lambda reference=None: S1_RECEIPT,
                                      lambda: dict(S1_PROCESS), tmp_path / "c.log",
                                      now=lambda: s45 - timedelta(seconds=5))
    if case == "first-qualified":
        s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT, minutes=45)
    else:
        s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT, minutes=47)
    want = [] if case == "pending-earlier" else ["STAGE-INTENT", "STAGE-PREPARED", "STAGE-CREATED"]
    assert stage_kinds(tmp_path, "opening") == want
    assert (tmp_path / "s1_out" / "seals" / f"{oc}.json").exists() == bool(want)


def test_opening_stage_envelope_and_single_member(tmp_path):
    start, cal, oc, lg, rep = opened(tmp_path)
    e, cm = env(tmp_path, "opening"), com(tmp_path, "opening")
    assert set(e["inputs"]) == {"plan.json", "audit/manifest.json", "opening_receipt.json", "qualified_line",
                                "tree_manifest"}
    q = j.first(j.subject_rows(jrows(tmp_path), j.slot_subject(opening_slot(cal, oc, 45))), "SLOT-QUALIFIED")
    assert (e["inputs"]["qualified_line"], e["inputs"]["tree_manifest"]) == (q.sha, q.detail)
    assert cm["kind"] == "single" and list(cm["members"]) == [f"seals/{oc}.json"] and e["acks"] == {}


def close_out(root, cal, oc):
    """F7.2(b) literal (OQ-37 ruling): run the finalizer to the W slot's E so that EVERY scheduled opening-close
    slot is terminal (later opening slots were refused with no row by the opening gate and end MISSED)."""
    day = next(d for d in cal if d["date"] == oc)
    last = z.schedule(day, cal)[-1]
    e_w = z.eligible_until(last, day, cal)
    gv = t.gate(root, "close out the opening close")
    with _Clock(e_w):
        sl.finalize_close(gv, day, cal, lambda: e_w, mailbox=mb(root))
    return e_w


def _open_and_ack(root, **override):
    start, cal, oc, lg, rep = opened(root)
    w = close_out(root, cal, oc)
    s1_ack(root, "opening-ack", "S1-OPENING-ACK", w + timedelta(minutes=1), **override)
    return start, cal, oc, w


def test_start_attest_envelope_and_single_member(tmp_path):                           # rows 104, 268 (OQ-15)
    start, cal, oc, w = _open_and_ack(tmp_path)
    with _Clock(w + timedelta(minutes=2)):
        r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    e, cm = env(tmp_path, "start_attest"), com(tmp_path, "start_attest")
    books = tmp_path / "s1_out" / "opening_books.json"
    assert set(e["inputs"]) == {"plan.json", "audit/manifest.json", f"seals/{oc}.json", "opening_receipt.json",
                                "opening_books.json"}
    assert e["inputs"]["opening_books.json"] == c.sha256_file(books)
    assert e["acks"] == {"S1-OPENING-ACK": t.open_trial(mb(tmp_path)).acks["S1-OPENING-ACK"].sha}
    assert cm["kind"] == "single" and list(cm["members"]) == ["attest_start.json"]
    rec = json.loads((tmp_path / "s1_out" / "attest_start.json").read_bytes())
    assert rec["opening_books_sha256"] == c.sha256_file(books)


@pytest.mark.parametrize("case", ["changed", "deleted"])
def test_opening_books_is_a_hash_bound_derived_input(tmp_path, monkeypatch, case):    # row 268 (OQ-15)
    start, cal, oc, w = _open_and_ack(tmp_path)
    books = tmp_path / "s1_out" / "opening_books.json"
    with _Clock(w + timedelta(minutes=2)):
        r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    if case == "changed":
        books.write_bytes(books.read_bytes() + b" ")
    else:
        books.unlink()
    sp = Spies(monkeypatch)
    with pytest.raises(SystemExit, match=r"INVALID \(stage-replaced\)"):
        t.gate(tmp_path, "opening books bound")
    sp.assert_zero()


def test_opening_books_preexisting_different_refuses_the_attestation(tmp_path):      # row 268 (before INTENT)
    start, cal, oc, w = _open_and_ack(tmp_path)
    (tmp_path / "s1_out" / "opening_books.json").write_text("{}", encoding="utf-8")
    with _Clock(w + timedelta(minutes=2)), pytest.raises(SystemExit, match="opening_books"):
        r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    assert stage_kinds(tmp_path, "start_attest") == []


@pytest.mark.parametrize("case", ["ok", "not-first-qualified", "seal-differs", "receipt-differs", "head-forked",
                                  "a-slot-not-terminal"])
def test_start_attest_verifies_the_opening_ack_against_the_journal(tmp_path, monkeypatch, case):
    start, cal, oc, lg, rep = opened(tmp_path)
    over = {"not-first-qualified": {"opening_slot": j.slot_subject(opening_slot(cal, oc, 47))},
            "seal-differs": {"opening_seal_sha256": "0" * 64}, "receipt-differs": {"opening_receipt_sha256": "0" * 64},
            "head-forked": {"journal_head_sha256": "f" * 64}}.get(case, {})
    w = close_out(tmp_path, cal, oc) if case != "a-slot-not-terminal" else z.close_of(oc, cal) + timedelta(hours=1)
    s1_ack(tmp_path, "opening-ack", "S1-OPENING-ACK", w + timedelta(minutes=1), **over)
    if case == "a-slot-not-terminal":                               # rows 269: ACK prefix lacks terminal rows
        w = close_out(tmp_path, cal, oc)                            # (later rows do not repair the ACK's prefix)
    with _Clock(w + timedelta(minutes=2)):
        if case == "ok":
            r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
            assert stage_kinds(tmp_path, "start_attest")[-1] == "STAGE-CREATED"
            return
        with pytest.raises(SystemExit):
            r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    assert stage_kinds(tmp_path, "start_attest") == [] and not (tmp_path / "s1_out" / "attest_start.json").exists()


def test_start_attest_requires_every_opening_close_slot_terminal_in_the_ack_prefix(tmp_path):   # row 269
    start, cal, oc, lg, rep = opened(tmp_path)
    s1_ack(tmp_path, "opening-ack", "S1-OPENING-ACK", z.close_of(oc, cal) + timedelta(hours=1))
    w = close_out(tmp_path, cal, oc)
    with _Clock(w + timedelta(minutes=2)), pytest.raises(SystemExit, match=r"F7\.2.*\(b\)"):
        r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    assert stage_kinds(tmp_path, "start_attest") == []


def test_opening_slot_is_the_earliest_qualified_independent_of_issuance(tmp_path):    # row 270 (F3, OQ-37)
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    lg = Ledger(tmp_path / "opening_ledger.sqlite3")
    s45, s47 = opening_slot(cal, oc, 45), opening_slot(cal, oc, 47)
    s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT, minutes=45)
    w = close_out(tmp_path, cal, oc)
    s1_ack(tmp_path, "opening-ack", "S1-OPENING-ACK", w + timedelta(minutes=1),
           opening_slot=j.slot_subject(s47))                        # a later slot named: refused
    with _Clock(w + timedelta(minutes=2)), pytest.raises(SystemExit, match="first QUALIFIED"):
        r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    assert t.opening_issuance(tmp_path, mb(tmp_path))["opening_slot"] == j.slot_subject(s45)


@pytest.mark.parametrize("case", ["all-terminal-eligible", "early-failed-then-qualified-all-terminal",
                                  "later-slot-unfinalized-blocks", "pending-blocks",
                                  "missed-then-qualified-all-terminal"])
def test_opening_issuance_helper(tmp_path, case):                                       # row 152 (F7.2 b literal)
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    lg = Ledger(tmp_path / "opening_ledger.sqlite3")
    s45, s47 = opening_slot(cal, oc, 45), opening_slot(cal, oc, 47)
    day = next(d for d in cal if d["date"] == oc)
    if case == "early-failed-then-qualified-all-terminal":
        with _Clock(s45 - timedelta(seconds=5)):
            ck.run_opening_checkpoint(tmp_path, lg.path, s45, lambda reference=None: S1_RECEIPT,
                                      lambda: dict(S1_PROCESS), tmp_path / "c.log",
                                      now=lambda: s45 - timedelta(seconds=5))
        s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT, minutes=47)
        close_out(tmp_path, cal, oc)
    elif case == "pending-blocks":
        s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(s45), at=s45 + timedelta(seconds=1))
        s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT, minutes=47)
    elif case == "missed-then-qualified-all-terminal":
        s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT, minutes=47)
        e45 = z.eligible_until(s45, day, cal)
        gv = t.gate(tmp_path, "finalizer")
        with _Clock(e45):
            sl.finalize_close(gv, day, cal, lambda: e45, mailbox=mb(tmp_path))
            ck._opening_stage(t.gate(tmp_path, "opening"), tmp_path / "s1_out", day, cal, lambda: e45, mb(tmp_path))
        close_out(tmp_path, cal, oc)
    else:
        s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT, minutes=45)
        if case == "all-terminal-eligible":
            close_out(tmp_path, cal, oc)                            # later-slot-unfinalized: not closed out
    got = t.opening_issuance(tmp_path, mb(tmp_path))
    want = case not in ("pending-blocks", "later-slot-unfinalized-blocks")
    assert got["eligible"] == want, got
    if got["eligible"]:
        assert got["opening_slot"] == j.slot_subject(s45 if case == "all-terminal-eligible" else s47)


@pytest.mark.parametrize("case", ["ok", "wrong-hash", "wrong-membership-receipt", "wrong-membership-staging"])
def test_opening_ack_evidence_manifest_is_reconstructed(tmp_path, monkeypatch, case):  # rows 279, 280 (E5.5 r1)
    start, cal, oc, lg, rep = opened(tmp_path)
    w = close_out(tmp_path, cal, oc)
    rows_ = jrows(tmp_path)
    man = t.evidence_manifest(tmp_path, rows_, rows_[-1].seq)
    assert {"plan.json", "opening_receipt.json", "staging/audit/intent.json", "staging/audit/prepared.json",
            "staging/opening/intent.json", "staging/opening/prepared.json"} <= set(man["files"])   # E5.5 membership
    assert man["files"]["staging/opening/prepared.json"] == c.sha256_file(
        sg.staging_dir(tmp_path, t.open_trial(mb(tmp_path)).trial_id, "opening") / "prepared.json")
    if case == "wrong-membership-receipt":
        bad = dict(man, files={k_: v for k_, v in man["files"].items() if k_ != "opening_receipt.json"})
        value = c.sha256_bytes(c.canonical(bad))
    elif case == "wrong-membership-staging":                         # rev-0 membership (no staging files)
        bad = dict(man, files={k_: v for k_, v in man["files"].items() if not k_.startswith("staging/")})
        value = c.sha256_bytes(c.canonical(bad))
    else:
        value = c.sha256_bytes(c.canonical(man)) if case == "ok" else "a" * 64
    s1_ack(tmp_path, "opening-ack", "S1-OPENING-ACK", w + timedelta(minutes=1), evidence_manifest_sha256=value)
    sp = Spies(monkeypatch)
    with _Clock(w + timedelta(minutes=2)):                           # journal and files are otherwise valid
        if case == "ok":
            r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
            return
        with pytest.raises(SystemExit, match=r"evidence manifest.*INVALID \(registration-artifact\)"):
            r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    sp.assert_zero()
    assert stage_kinds(tmp_path, "start_attest") == []
    assert jrows(tmp_path)[-1].subject == "reason/registration-artifact"            # INVALIDATE, not REFUSE


def test_opening_window_later_slots_refused_then_missed(tmp_path):                   # row 333 (E5.6 r1)
    """E5.6: once the opening STAGE-INTENT exists, a later opening-close SLOT-INTENT is refused with no row by the
    opening gate; that slot ends MISSED at its E; the OPENING-ACK cannot be issued before the E of the last
    scheduled opening-close slot."""
    start, cal, oc, lg, rep = opened(tmp_path)                    # slot :45 QUALIFIED -> opening INTENT..CREATED
    assert stage_kinds(tmp_path, "opening")[0] == "STAGE-INTENT"
    day = next(d for d in cal if d["date"] == oc)
    s47 = opening_slot(cal, oc, 47)
    at = s47 + timedelta(seconds=30)
    with _Clock(at), pytest.raises(SystemExit, match="opening is already decided"):
        ck.run_opening_checkpoint(tmp_path, lg.path, s47, lambda reference=None: S1_RECEIPT,
                                  lambda: dict(S1_PROCESS), tmp_path / "c.log", now=lambda: at)
    assert j.subject_rows(jrows(tmp_path), j.slot_subject(s47)) == []          # no row
    last = z.schedule(day, cal)[-1]
    e_last = z.eligible_until(last, day, cal)
    gv = t.gate(tmp_path, "before the last E")
    with _Clock(e_last - timedelta(microseconds=1)):
        sl.finalize_close(gv, day, cal, lambda: e_last - timedelta(microseconds=1), mailbox=mb(tmp_path))
    assert t.opening_issuance(tmp_path, mb(tmp_path))["eligible"] is False         # last slot not yet terminal
    close_out(tmp_path, cal, oc)
    assert [x.kind for x in j.subject_rows(jrows(tmp_path), j.slot_subject(s47))] == ["SLOT-MISSED"]
    assert t.opening_issuance(tmp_path, mb(tmp_path))["eligible"] is True


@pytest.mark.parametrize("case", ["ack-after-attest", "attest-at-start"])
def test_opening_ack_must_precede_the_attestation_and_the_attestation_start(tmp_path, case):   # row 316 (E5.3)
    start, cal, oc, lg, rep = opened(tmp_path)
    w = close_out(tmp_path, cal, oc)
    if case == "ack-after-attest":
        s1_ack(tmp_path, "opening-ack", "S1-OPENING-ACK", w + timedelta(minutes=5))
        at = w + timedelta(minutes=2)                               # the attestation INTENT would precede the ACK
    else:
        s1_ack(tmp_path, "opening-ack", "S1-OPENING-ACK", w + timedelta(minutes=1))
        at = c.aware(START)
    with _Clock(at), pytest.raises(SystemExit):
        r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    assert stage_kinds(tmp_path, "start_attest") == []


def test_a_change_after_the_opening_ack_is_caught_by_the_live_file_check(tmp_path, monkeypatch):
    start, cal, oc, w = _open_and_ack(tmp_path)
    rp = tmp_path / "s1_out" / "opening_receipt.json"
    rp.write_bytes(rp.read_bytes() + b" ")                       # the TEST changes its tmp opening receipt
    sp = Spies(monkeypatch)
    with _Clock(w + timedelta(minutes=2)), pytest.raises(SystemExit, match=r"INVALID \(stage-replaced\)"):
        r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    sp.assert_zero()


def test_missed_opening_ack_deadline_gives_no_start(tmp_path):
    start, cal, oc, lg, rep = opened(tmp_path)
    w = close_out(tmp_path, cal, oc)
    with _Clock(w + timedelta(minutes=2)), pytest.raises(SystemExit, match="OPENING-ACK"):
        r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    with _Clock(c.aware(START) - timedelta(hours=1)), pytest.raises(SystemExit):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    assert stage_kinds(tmp_path, "start_attest") == [] and stage_kinds(tmp_path, "prereg") == []


@pytest.mark.parametrize("case", ["ok", "old-format", "wrong-prev"])
def test_prereg_requires_the_run_ack_with_trial_prev_and_journal_fields(tmp_path, case):
    st_ = s1_state(tmp_path, START)                       # opening, OPENING-ACK, start_attest and RUN-ACK
    con_line = t.open_trial(mb(tmp_path)).acks["S1-RUN-ACK"].line
    if case != "ok":
        import sqlite3
        con = sqlite3.connect(mb(tmp_path))
        if case == "old-format":
            old = " ".join(["S1-RUN-ACK"] + [p for p in con_line.split(" ")[1:]
                                             if p.split("=")[0] not in ("trial_id", "prev", "journal_seq",
                                                                        "journal_head_sha256")])
            con.execute("UPDATE messages SET body=? WHERE id='run-ack'", (old,))    # the TEST edits its tmp mailbox
        else:
            tr = t.open_trial(mb(tmp_path))
            con.execute("UPDATE messages SET body=? WHERE id='run-ack'",
                        (con_line.replace(f"prev={tr.acks['S1-OPENING-ACK'].mailbox_id}",
                                          f"prev={tr.audit.mailbox_id}"),))
        con.commit()
        con.close()
    with _Clock(st_["prereg_at"]):
        if case == "ok":
            r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
            assert stage_kinds(tmp_path, "prereg")[-1] == "STAGE-CREATED"
            return
        with pytest.raises(SystemExit):
            r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)


def test_prereg_envelope_and_member(tmp_path):
    st_ = s1_state(tmp_path, START)
    with _Clock(st_["prereg_at"]):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    e, cm = env(tmp_path, "prereg"), com(tmp_path, "prereg")
    assert set(e["inputs"]) == {"attest_start.json", "receipt"} and e["inputs"]["receipt"] == c.receipt_sha256(
        S1_RECEIPT)
    assert e["acks"] == {"S1-RUN-ACK": t.open_trial(mb(tmp_path)).acks["S1-RUN-ACK"].sha}
    assert list(cm["members"]) == ["prereg.json"] and cm["kind"] == "single"


SPLIT = {"id": "ca-split-1", "type": "forward_splits", "symbol": "CI", "ex_date": "2026-10-05",
         "effective_date": "2026-10-05", "classification": "complete"}


def test_blocked_prereg_is_a_pre_intent_refusal_record(tmp_path, monkeypatch):     # rows 121, 271, 326 (E3)
    """E3 (pending Codex acceptance of E3): BLOCKED is a pre-INTENT refusal record - blocked.json, no journal row,
    ACTIVE, never INVALID - with zero captures, provider requests and valuation calls."""
    st_ = s1_state(tmp_path, START, audit_actions=[SPLIT])
    n_rows = len(jrows(tmp_path))
    sp = Spies(monkeypatch)
    with _Clock(st_["prereg_at"]), pytest.raises(SystemExit, match=r"S1 BLOCKED \(pre-START units\)"):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    sp.assert_zero()
    blocked = json.loads((tmp_path / "s1_out" / "blocked.json").read_text(encoding="utf-8"))
    assert blocked["status"] == "BLOCKED" and blocked["trial_id"] == t.open_trial(mb(tmp_path)).trial_id   # E5.4
    assert len(jrows(tmp_path)) == n_rows and stage_kinds(tmp_path, "prereg") == []
    assert j.trial_state(jrows(tmp_path)) == "ACTIVE"
    t.gate(tmp_path, "blocked.json is a declared pre-INTENT record, not a stage member")


def test_blocked_rerun_after_deletion_recomputes_identically(tmp_path):              # rows 272, 327 (E3.2)
    st_ = s1_state(tmp_path, START, audit_actions=[SPLIT])
    out = tmp_path / "s1_out"
    with _Clock(st_["prereg_at"]), pytest.raises(SystemExit) as first:
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    rec1 = r.blocked_reasons_record(out, c.load_json(out / "audit" / "calendar.json"))
    (out / "blocked.json").unlink()
    with _Clock(st_["prereg_at"] + timedelta(minutes=1)), pytest.raises(SystemExit) as second:
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    rec2 = r.blocked_reasons_record(out, c.load_json(out / "audit" / "calendar.json"))
    assert str(first.value) == str(second.value) and rec1 == rec2
    assert json.loads((out / "blocked.json").read_bytes())["reasons"] == rec2["reasons"]
    assert stage_kinds(tmp_path, "prereg") == [] and j.trial_state(jrows(tmp_path)) == "ACTIVE"


def _blocked_and_closed(tmp_path, st_, good=True):
    with _Clock(st_["prereg_at"]), pytest.raises(SystemExit, match="S1 BLOCKED"):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    h = r.blocked_close_evidence(tmp_path / "s1_out") if good else "8" * 64
    s1_ack(tmp_path, "close", "S1-CLOSE-ACK", st_["prereg_at"] + timedelta(minutes=5), reason="BLOCKED",
           evidence_sha256=h)
    return h


@pytest.mark.parametrize("case", ["ok", "wrong"])
def test_close_blocked_evidence_hash_end_to_end(tmp_path, case):                       # rows 273, 328 (E3.4 r1)
    st_ = s1_state(tmp_path, START, audit_actions=[SPLIT])
    h = _blocked_and_closed(tmp_path, st_, good=(case == "ok"))
    out = tmp_path / "s1_out"
    rec = r.blocked_reasons_record(out, c.load_json(out / "audit" / "calendar.json"))
    assert r.blocked_close_evidence(out) == c.sha256_bytes(c.canonical({"trial_id": rec["trial_id"],
                                                                         "reasons": rec["reasons"]}))
    assert r.blocked_close_evidence(out) != c.sha256_file(out / "blocked.json")      # not the file bytes
    if case == "ok":
        with pytest.raises(SystemExit, match="zero open"):
            t.gate(tmp_path, "closed BLOCKED")
    else:
        with pytest.raises(SystemExit, match="BLOCKED evidence"):
            t.gate(tmp_path, "wrong BLOCKED evidence")


@pytest.mark.parametrize("case", ["deleted", "deleted-and-recreated"])
def test_blocked_close_survives_delete_and_recreate(tmp_path, case):                   # row 332 (E3.4 r1)
    st_ = s1_state(tmp_path, START, audit_actions=[SPLIT])
    h = _blocked_and_closed(tmp_path, st_)
    out = tmp_path / "s1_out"
    (out / "blocked.json").unlink()
    if case == "deleted-and-recreated":                              # new recorded_utc => different file bytes
        rec = r.blocked_reasons_record(out, c.load_json(out / "audit" / "calendar.json"))
        (out / "blocked.json").write_text(json.dumps(dict(rec, status="BLOCKED",
                                                          recorded_utc="2026-12-01T00:00:00+00:00")),
                                          encoding="utf-8")
    assert r.blocked_close_evidence(out) == h                       # h unchanged
    tr = t.trials(t.scan(mb(tmp_path)), root=tmp_path)
    assert all(x.closed is not None for x in tr.values())            # the closed trial never re-opens
    with pytest.raises(SystemExit, match="zero open"):
        t.gate(tmp_path, "still closed")


def test_non_blocked_prereg_is_unaffected(tmp_path):                                  # rows 274, 329 (ctrl)
    st_ = s1_state(tmp_path, START)
    with _Clock(st_["prereg_at"]):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    assert stage_kinds(tmp_path, "prereg")[-1] == "STAGE-CREATED"
    assert not (tmp_path / "s1_out" / "blocked.json").exists()
```

Append to `test_s1_a3_codex_probes.py`:

```python
import shutil as _sh
import s1_checkpoint as ck_
from conftest import Ledger, S1_PROCESS as P_, s1_opening_checkpoint, s1_plan_audit


def _opened(tmp_path):
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    lg = Ledger(tmp_path / "ledger.sqlite3")
    s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT)
    return start, cal, oc, lg


def test_v1_selective_deletion_is_invalid(tmp_path, monkeypatch):
    start, cal, oc, lg = _opened(tmp_path)
    out = tmp_path / "s1_out"
    first = z.schedule(next(d for d in cal if d["date"] == oc), cal)[0]
    name = f"{first:%Y%m%dT%H%M%SZ}"
    for p in [out / "seals" / f"{oc}.json", *c.stage_records(out, "opening"), out / "opening_receipt.json",
              out / "captures" / oc / f"{name}.resolution.json", out / "captures" / oc / f"{name}.report.json"]:
        p.unlink()                                            # the historical V1 deletion set (frozen copy)
    later = z.close_of(oc, cal) + timedelta(hours=4)
    sp = Spies(monkeypatch)
    changed = json.loads(json.dumps(S1_RECEIPT))
    changed["fingerprint"]["config"] = {"synthetic_changed_setting": "different"}
    with _Clock(later), pytest.raises(SystemExit, match="INVALID"):
        ck_.run_opening_checkpoint(tmp_path, lg.path, later, sp.receipt(changed), sp.process(), tmp_path / "c.log",
                                   now=lambda: later)
    with _Clock(c.aware(START) - timedelta(days=1)), pytest.raises(SystemExit, match="INVALID"):
        r.attest_start(tmp_path, r.START_STATEMENT, changed)
    sp.assert_zero()


def test_a_fully_deleted_then_b_is_invalid_or_never_ack_eligible(tmp_path, monkeypatch):
    import s1_collect as k_
    start, cal, oc, lg = _opened(tmp_path)
    _sh.rmtree(tmp_path / "s1_out")
    with _Clock(c.aware(START) - timedelta(days=3)), pytest.raises(SystemExit, match="open"):
        k_.write_plan(tmp_path, c.aware(START) + timedelta(days=7), "2026-10-30", [], "2026-10-01")    # B
    sp = Spies(monkeypatch)
    later = z.close_of(oc, cal) + timedelta(hours=4)
    with _Clock(later), pytest.raises(SystemExit, match=r"INVALID \(LOST\)"):
        ck_.run_opening_checkpoint(tmp_path, lg.path, later, sp.receipt(), sp.process(), tmp_path / "c.log",
                                   now=lambda: later)
    sp.assert_zero()
    with pytest.raises(SystemExit):
        t.opening_issuance(tmp_path, tmp_path / "mailbox.sqlite3")


def test_prereg_restoration_is_invalid_once_created(tmp_path, monkeypatch):
    st_ = s1_state(tmp_path, START)
    with _Clock(st_["prereg_at"]):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    out = tmp_path / "s1_out"
    files = [out / "prereg.json", *c.stage_records(out, "prereg")]
    saved = {p: p.read_bytes() for p in files}
    for p in files:
        p.unlink()
    with _Clock(st_["prereg_at"] + timedelta(minutes=1)), pytest.raises(SystemExit, match="INVALID"):
        t.gate(tmp_path, "Codex synthetic probe")
    for p, b in saved.items():
        p.write_bytes(b)
    (out / "aborted.json").unlink(missing_ok=True)
    sp = Spies(monkeypatch)
    with _Clock(st_["prereg_at"] + timedelta(minutes=2)), pytest.raises(SystemExit, match="INVALID"):
        t.gate(tmp_path, "Codex synthetic probe")
    sp.assert_zero()


@pytest.mark.parametrize("crash", ["intent-only-free", "prepared-free"])
def test_prereg_before_created_follows_the_stage_table(tmp_path, monkeypatch, crash):
    st_ = s1_state(tmp_path, START)
    real = j.append
    stop_after = "STAGE-INTENT" if crash == "intent-only-free" else "STAGE-PREPARED"

    def crashing(trial_id, gen, req, ctx_fn, **kw):
        res = real(trial_id, gen, req, ctx_fn, **kw)
        if req.kind == stop_after and req.subject == "stage/prereg":
            raise KeyboardInterrupt                               # a crash (the lock is released on unwind)
        return res
    monkeypatch.setattr(j, "append", crashing)
    with _Clock(st_["prereg_at"]), pytest.raises(KeyboardInterrupt):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    monkeypatch.setattr(j, "append", real)
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    if crash == "intent-only-free":
        with pytest.raises(SystemExit, match=r"INVALID \(stage-incomplete\)"):
            t.gate(tmp_path, "probe")
    else:
        t.gate(tmp_path, "probe")
        rows = j.read_trial(tr.trial_id, tr.genesis, tmp_path / "mailbox.sqlite3")
        assert [x.kind for x in j.subject_rows(rows, "stage/prereg")][-1] == "STAGE-CREATED"
```

- [ ] **Step 3: Behavioural RED.** Run `test_s1_a3_prestart.py` and the new probe tests into `a3/t10_red.txt`.
  - Expected: no opening stage rows (the legacy seal path); no OPENING-ACK verification (attest_start proceeds on
    seal-differs and the other cases); the issuance helper always says eligible; the receipt change is not caught
    as stage-replaced; prereg is not a stage.
  - The c9b4322 observations for V1 and prereg restoration (historical JSON) are reproduced: label them `B-old`.
  - Revision 1:
    - row 268 fails: the stub's start_attest is not a stage, and opening_books.json is written by the legacy path
      without binding;
    - row 269 and verify `[a-slot-not-terminal]` fail: no prefix check;
    - row 270 fails: the stub accepts any opening_slot;
    - rows 279/280 fail: no manifest check, so no INVALIDATE;
    - row 316 `[ack-after-attest]` fails: no causal check;
    - row 271 fails on the `trial_id` in blocked.json (E5.4) and the zero-spy assertion;
    - row 272 fails: no `blocked_reasons_record`;
    - rows 273 (end-to-end) and 332 fail: no `blocked_close_evidence`, so every BLOCKED CLOSE is refused;
    - row 333 fails: the stub keeps the legacy opening path (no opening INTENT, so the later slot is captured);
    - row 274 passes. Label it `ctrl`;
    - the issuance cases `later-slot-unfinalized-blocks` and `pending-blocks` fail (the stub always says eligible).

- [ ] **Step 4: Implement.**

`s1_stage.run`: add the keywords and change two places:

```python
def run(gv, stage, *, inputs, acks, work, policy_fn=None, mailbox=None, clock=None, before_publish=None,
        extra_gate=None, publish_ctx=None) -> dict:
    ...
            intent = _need(_append(gv, j.Request("STAGE-INTENT", j.stage_subject(stage), op, actor,
                                                 detail_fn=detail_fn), mailbox, clock,
                                   stage_gate=lambda rows_, g: permitted(gv.trial, rows_, g)
                                   or (extra_gate(rows_) if extra_gate is not None else None)),
                           stage, "STAGE-INTENT")
    ...
            with (publish_ctx() if publish_ctx is not None else contextlib.nullcontext()):
                if before_publish is not None:
                    before_publish(com)
                for rel in sorted(members):
                    _publish_one(gv.out, rel, staging.files[rel], members[rel])
```

Add `import contextlib`. Set `ENFORCED = frozenset({"audit", "opening", "start_attest", "prereg"})`.

`s1_checkpoint._opening_stage`:

```python
def _opening_stage(gv, out: Path, day, cal, now, mailbox) -> dict:
    """F3 + F4.8 'opening (seal)': once the opening close's first QUALIFIED slot is decided (every earlier slot
    terminal: s1_slot.first_qualified), publish opening_receipt.json from that slot's committed evidence (OQ-15; an
    existing identical one is kept, a different one refuses) and run stage `opening` (single member
    seals/<close>.json = s1_slot.seal_bytes of that evidence). The legacy opening records are registered before
    publication (OQ-19)."""
    import s1_journal as j
    import s1_slot
    import s1_stage
    rows = j.read_trial(gv.trial.trial_id, gv.trial.genesis, mailbox)
    if s1_stage.stage_rows(rows, "opening")["intent"] is not None:
        return {"opening": "already decided"}
    q = s1_slot.first_qualified(rows, day, cal)
    if q is None:
        return {"deferred": "the opening close's first QUALIFIED slot is not decided (an earlier slot is in flight, "
                            "or none qualified)"}
    ev = s1_slot._resolution_evidence(out, q, day["date"])
    rp = out / "opening_receipt.json"
    _store_opening_receipt(rp, ev["candidate"]["receipt"])
    rel = f"seals/{day['date']}.json"
    close = z.close_of(day["date"], cal)
    inputs = {"plan.json": c.sha256_file(out / "plan.json"),
              "audit/manifest.json": c.sha256_file(out / "audit" / "manifest.json"),
              "opening_receipt.json": c.sha256_file(rp), "qualified_line": q.sha, "tree_manifest": q.detail}

    def work(sw):
        sw.put(rel, s1_slot.seal_bytes(day, close, ev))
        return []

    def before(com):
        _before_opening_seal(out, day["date"], com["members"][rel], now())
        _register_opening(out, day["date"], rp, (ev["candidate"].get("process_binding") or {}).get("binding"),
                          com["members"][rel])
    com = s1_stage.run(gv, "opening", inputs=inputs, acks={}, work=work, mailbox=mailbox, clock=now,
                       extra_gate=lambda rows_: None if s1_slot.first_qualified(rows_, day, cal) is not None
                       else "no first QUALIFIED opening slot with every earlier slot terminal (F3)",
                       before_publish=before)
    return {"seal": {"written": True, "sha256": com["members"][rel], "from_slot": ev["scheduled"]}}
```

`run_opening_checkpoint`: after the worker block, when the result is QUALIFIED (or always, to advance a deferred
opening):

```python
    after = {"journal": result}
    gv = s1_trial.gate(root, "opening checkpoint", mailbox=mailbox, now=now)        # re-read after the slot row
    fin = s1_slot.finalize_close(gv, day, cal, now, mailbox=mailbox)
    pending = "pending" in (fin.get("deferred") or "")
    after.update({"deferred": fin["deferred"]} if pending else _opening_stage(gv, out, day, cal, now, mailbox))
```

`s1_slot.opening_gate` keeps only the audit-CREATED and opening-INTENT clauses.

`s1_trial`:

```python
def verify_opening_ack(gv, cal):
    """F7.2 (c, d) / F7.4 on the S1 side: the trial's OPENING-ACK binds the current plan, audit manifest, opening seal
    and opening receipt (file hashes, OQ-30); within the journal prefix it names (journal_seq), its opening_slot is
    the first QUALIFIED opening slot with every earlier slot terminal (OQ-37), the opening stage is CREATED and the
    trial ACTIVE. Missing or failing: no START (Refusal)."""
    import s1_seal as z
    import s1_slot
    import s1_stage
    out = gv.out
    plan = c.load_json(out / "plan.json")
    if "S1-OPENING-ACK" not in gv.trial.acks:
        raise Refusal("START attestation refused: no S1-OPENING-ACK (F7.4: no START without it)")
    a = verify_ack(gv.trial, gv.rows, "S1-OPENING-ACK", None,
                   dict(artifact_fields("S1-OPENING-ACK", out), trial_id=plan["trial_id"],
                        bundle_sha256=c.bundle_sha256()))
    seq = int(a.fields["journal_seq"])
    rows_at = gv.rows[:seq]
    day = next(d for d in cal if d["date"] == plan["opening_close"])
    q = s1_slot.first_qualified(rows_at, day, cal)
    if q is None or q.subject != a.fields["opening_slot"]:
        raise Refusal("OPENING-ACK opening_slot is not the first QUALIFIED opening slot at its journal_seq (F7.2 c)")
    open_slots = [j.slot_subject(s) for s in z.schedule(day, cal)]
    unterminated = [s for s in open_slots if j.first(j.subject_rows(rows_at, s), *j.TERMINAL) is None]
    if unterminated:                                                              # F7.2(b) literal (OQ-37)
        raise Refusal(f"F7.2 (b): {len(unterminated)} opening-close slot(s) have no terminal row in the "
                      f"OPENING-ACK's journal prefix (first {unterminated[0]})")
    if s1_stage.stage_rows(rows_at, "opening")["created"] is None or j.trial_state(rows_at) != "ACTIVE":
        raise Refusal("the opening stage is not CREATED (or the trial not ACTIVE) at the ACK's journal_seq (F7.2)")
    opening_manifest_check(gv, a)                                                 # E5.5 / F7.3: INVALIDATE
    if not datetime.fromtimestamp(a.created, tz=timezone.utc) < c.now_utc():      # E5.3: before the INTENT
        raise Refusal("OPENING-ACK is not created before the START attestation (E5.3)")
    return a


def opening_manifest_check(gv, a=None) -> None:
    """E5.5 (Erratum 1 r1) as part of the F7.3 live-file check: with an OPENING-ACK, the reconstructed manifest's
    sha256 must equal its evidence_manifest_sha256. A wrong hash or a wrong membership, with otherwise valid files,
    is INVALIDATE (registration-artifact) - not a refusal. Called by verify_opening_ack and, from Task 10 on, by
    every gate after the stage and slot evidence checks (so a damaged member is reported as stage-replaced first)."""
    a = a if a is not None else gv.trial.acks.get("S1-OPENING-ACK")
    if a is None:
        return
    try:
        got = c.sha256_bytes(c.canonical(evidence_manifest(gv.root, gv.rows, int(a.fields["journal_seq"]))))
    except (OSError, ValueError, KeyError) as e:                                  # a member gone: not reconstructible
        got = f"unreconstructible ({type(e).__name__})"
    if got != a.fields["evidence_manifest_sha256"]:
        invalidate(gv.trial, "registration-artifact",
                   {"where": "evidence manifest", "expected": a.fields["evidence_manifest_sha256"],
                    "reconstructed": got}, root=gv.root, mailbox=gv.mailbox)
        raise Refusal("OPENING-ACK evidence manifest differs from the reconstruction (E5.5): "
                      "INVALID (registration-artifact)")


def evidence_manifest(root, rows, journal_seq) -> dict:
    """E5.5 (Erratum 1 r1) exact byte format and membership, used identically by Codex when issuing:
    c.canonical({"trial_id", "journal_seq", "journal_head_sha256", "files": {relpath: sha256}}), where `files`
    covers, for rows with seq <= journal_seq: plan.json and opening_receipt.json; every CREATED audit member; every
    file of every QUALIFIED or FAILED tree; every CREATED stage member; the staging intent.json and prepared.json of
    every stage with an INTENT or PREPARED row (OQ-35), keyed `staging/<stage>/<name>`. Relpaths are relative to
    s1_out; c.canonical sorts the keys. Never reads Codex's folder."""
    import s1_slot
    import s1_stage
    out = Path(root) / "s1_out"
    pre = rows[:journal_seq]
    plan = c.load_json(out / "plan.json")
    files = {"plan.json": c.sha256_file(out / "plan.json"),
             "opening_receipt.json": c.sha256_file(out / "opening_receipt.json")}
    cal = c.load_json(out / "audit" / "calendar.json")
    for r_ in pre:
        if r_.kind in ("SLOT-QUALIFIED", "SLOT-FAILED"):
            s = s1_slot.slot_of(r_.subject)
            f = s1_slot.qualified_tree if r_.kind == "SLOT-QUALIFIED" else s1_slot.failed_tree
            files.update(f(out, s, s1_slot.day_for(s, cal)["date"]))
        if r_.kind.startswith("STAGE-"):
            stage = r_.subject[len("stage/"):]
            name = {"STAGE-INTENT": "intent.json", "STAGE-PREPARED": "prepared.json"}.get(r_.kind)
            if name is not None:                                                  # OQ-35 staging evidence
                p = s1_stage.staging_dir(root, plan["trial_id"], stage) / name
                files[f"staging/{stage}/{name}"] = c.sha256_file(p)
            if r_.kind == "STAGE-CREATED":                                        # includes the audit members
                files.update(s1_stage.committed_commitment(root, plan["trial_id"], stage, pre)["members"])
    return {"trial_id": plan["trial_id"], "journal_seq": journal_seq,
            "journal_head_sha256": pre[-1].sha if pre else None, "files": files}


def opening_issuance(root, mailbox=None) -> dict:
    """F7.2 b-d support for Codex's issuance checklist (procedural on Codex's side): the gate (d: ACTIVE, F3/F4 hold,
    journal chain), EVERY scheduled opening-close slot terminal (b, literal: OQ-37 ruling), the opening slot = the
    earliest QUALIFIED (F3), the opening stage CREATED with the local seal and receipt matching (c), and the
    reconstructed evidence manifest (E5.5)."""
    import s1_gates
    import s1_slot
    import s1_stage
    import s1_seal as z
    gv = gate(root, "opening issuance check", mailbox=mailbox)
    cal = s1_gates.verified_audit(gv.out, mailbox)["calendar"]
    plan = c.load_json(gv.out / "plan.json")
    day = next(d for d in cal if d["date"] == plan["opening_close"])
    q = s1_slot.first_qualified(gv.rows, day, cal)
    reasons = []
    if q is None:
        reasons.append("an opening slot before the first QUALIFIED one is in flight, or none qualified (b)")
    open_ = [j.slot_subject(s) for s in z.schedule(day, cal)
             if j.first(j.subject_rows(gv.rows, j.slot_subject(s)), *j.TERMINAL) is None]
    if open_:                                                                     # F7.2(b) literal (OQ-37)
        reasons.append(f"{len(open_)} scheduled opening-close slot(s) have no terminal row yet (b)")
    if s1_stage.stage_rows(gv.rows, "opening")["created"] is None:
        reasons.append("the opening stage is not CREATED (c)")
    f = artifact_fields("S1-OPENING-ACK", gv.out)
    man = evidence_manifest(gv.root, gv.rows, len(gv.rows)) if not reasons else None
    return {"eligible": not reasons, "reasons": reasons, "opening_slot": q.subject if q else None,
            "evidence_manifest_sha256": c.sha256_bytes(c.canonical(man)) if man else None,
            "journal_seq": gv.rows[-1].seq if gv.rows else 0,
            "journal_head_sha256": gv.rows[-1].sha if gv.rows else None,
            "opening_seal_sha256": f["opening_seal_sha256"], "opening_receipt_sha256": f["opening_receipt_sha256"]}
```

In `token()`, before `vals.update(given)`, for `S1-OPENING-ACK`:
- if no `opening_slot` is given, set `vals["opening_slot"]` to the first QUALIFIED opening slot's subject. Use
  `s1_slot.first_qualified` over the current rows, with the opening close's row taken from
  `s1_gates.verified_audit(out, mailbox)["calendar"]`;
- if no `evidence_manifest_sha256` is given, set it to
  `c.sha256_bytes(c.canonical(evidence_manifest(root, rows, rows[-1].seq)))`.

The Task 5 `_damage("two-opening-acks")` case already reads the ACK's own `evidence_manifest_sha256` value from
`tr.acks["S1-OPENING-ACK"].fields`, so it is unaffected. Task 5's conftest ACK fixtures that passed `"e" * 64` drop
that override in this task. Record this in `a3/t10_old_new.md` as a fixture change.

`s1_run.attest_start` (replaces lines 420–466; the legacy checks above line 452 are unchanged):

```python
def attest_start(root, statement: str, receipt, *, mailbox=None) -> dict:
    """START attestation as stage `start_attest` (F4.8; OQ-15 ruling: SINGLE member attest_start.json, with
    opening_books.json a deterministic, hash-bound derived input published before the INTENT): the trial gate
    first; the legacy checks (statement, bundle, abort, START not passed, verified audit, opening seal, capture
    order, binding reference, receipt); then the OPENING-ACK verified against the journal (F7.2/F7.4, E5.3, E5.5)."""
    import s1_stage
    import s1_trial
    if statement != START_STATEMENT:
        raise SystemExit("START attestation refused: the statement must be exactly START_STATEMENT")
    gv = s1_trial.gate(root, "START attestation", mailbox=mailbox)
    out = _out(root)
    c.verify_bundle_first(out, "START attestation", mailbox=mailbox, need="audit")
    if c.load_abort(out) is not None:
        raise SystemExit("START attestation refused: the registration is ABORTED-INVALID (aborted.json)")
    plan = _load(out / "plan.json")
    if c.now_utc() >= c.aware(plan["planned_start"]):
        raise SystemExit("planned START has passed: re-register")
    try:
        aud = g.verified_audit(out, mailbox)
        seal_p, seal = _opening_seal(out, plan, aud["calendar"])
    except Invalid as e:
        raise SystemExit(f"START attestation refused: {e}") from None
    if seal.get("bundle_sha256") != c.bundle_sha256():
        raise SystemExit("START attestation refused: the opening seal was not written by the registered bundle")
    cap = seal.get("capture") or {}
    if c.now_utc() <= c.aware(cap.get("capture_end") or cap.get("actual")):
        raise SystemExit("START attestation refused: it must follow the opening seal's capture")
    binding = _opening_binding(seal, "START attestation")
    opening_receipt = _opening_receipt(out, seal)
    if c.receipt_sha256(receipt) != _receipt_sha(opening_receipt):
        raise SystemExit("START attestation refused: the receipt differs from the opening receipt "
                         "(s1_out/opening_receipt.json)")
    a = s1_trial.verify_opening_ack(gv, aud["calendar"])
    books_p = _opening_books(out, seal_p, seal)          # OQ-15: write once, or verify == recomputation; else refuse
    seal_rel = seal_p.relative_to(out).as_posix()
    rec = {"statement": statement, "trial_id": plan["trial_id"], "planned_start": plan["planned_start"],
           "receipt_sha256": _receipt_sha(opening_receipt), "plan_sha256": c.sha256_file(out / "plan.json"),
           "audit_manifest_sha256": c.sha256_file(out / "audit" / "manifest.json"),
           "opening_seal_sha256": c.sha256_file(seal_p), "opening_books_sha256": c.sha256_file(books_p),
           "process_binding_sha256": _binding_sha(binding), "bundle_sha256": c.bundle_sha256(),
           "recorded_utc": c.now_utc().isoformat()}

    def work(sw):
        sw.put_json("attest_start.json", dict(rec, intent_at=sw.intent_at))
        return []
    s1_stage.run(gv, "start_attest", inputs={"plan.json": rec["plan_sha256"],
                                             "audit/manifest.json": rec["audit_manifest_sha256"],
                                             seal_rel: rec["opening_seal_sha256"],
                                             "opening_receipt.json": c.sha256_file(out / "opening_receipt.json"),
                                             "opening_books.json": rec["opening_books_sha256"]},
                 acks={"S1-OPENING-ACK": a.sha}, work=work, mailbox=mailbox,
                 publish_ctx=lambda: c.stage_publication(out, "attest_start"),
                 before_publish=lambda com: c.register_stage(out, "attest_start", {
                     "attest_start.json": com["members"]["attest_start.json"]}))
    return _load(out / "attest_start.json")


def _opening_books(out, seal_p, seal) -> Path:
    """OQ-15 (KEEP SINGLE): opening_books.json is a deterministic derived input. Recompute it from the committed
    opening seal; publish it exclusively if absent; if present it must equal the recomputation byte for byte,
    otherwise refuse with no row (a later change after CREATED is caught by the envelope input check)."""
    try:
        data = c.canonical(_books_record(seal_p, seal))
    except b.BookError as e:
        raise SystemExit(f"START attestation refused: opening ledger unreadable ({e})") from None
    p = out / "opening_books.json"
    try:
        c.publish_exclusive(p, data)
    except FileExistsError:
        if p.read_bytes() != data:
            raise SystemExit("START attestation refused: opening_books.json differs from its recomputation "
                             "from the committed opening seal (OQ-15)") from None
    return p
```

`s1_run.do_prereg`: keep lines 490–527 unchanged except the BLOCKED block, which Step 4b replaces. Replace lines
528–542 with:

```python
    a = s1_trial.verify_ack(gv.trial, gv.rows, "S1-RUN-ACK", ack_id,
                            dict(s1_trial.artifact_fields("S1-RUN-ACK", out), trial_id=plan["trial_id"],
                                 bundle_sha256=c.bundle_sha256()))
    ack = s1_trial.ack_record(a)
    if c.aware(ack["created_utc"]) <= c.aware(_load(ap)["recorded_utc"]):
        raise SystemExit("prereg refused: the RUN-ACK is not strictly after the START attestation")
    pr = {"trial_id": plan["trial_id"], "start": plan["planned_start"], "calendar": cal, "receipt": receipt,
          "runner_sha256": runner_sha(), "bundle_sha256": c.bundle_sha256(),
          "plan_sha256": c.sha256_file(out / "plan.json"),
          "audit_manifest_sha256": c.sha256_file(out / "audit" / "manifest.json"),
          "attest_start_sha256": c.sha256_file(ap), "opening_seal_sha256": c.sha256_file(seal_p),
          "opening_books_sha256": c.sha_or_absent(out / "opening_books.json"),
          "process_binding": _opening_binding(seal, "prereg"), "ack": ack, "recorded_utc": c.now_utc().isoformat()}

    def work(sw):
        sw.put_json("prereg.json", dict(pr, intent_at=sw.intent_at))
        return []
    s1_stage.run(gv, "prereg", inputs={"attest_start.json": c.sha256_file(ap), "receipt": c.receipt_sha256(receipt)},
                 acks={"S1-RUN-ACK": a.sha}, work=work, mailbox=mailbox,
                 publish_ctx=lambda: c.stage_publication(out, "prereg"),
                 before_publish=lambda com: c.register_stage(out, "prereg",
                                                             {"prereg.json": com["members"]["prereg.json"]}))
    return _load(out / "prereg.json")
```

Here `gv = s1_trial.gate(root, "prereg", mailbox=mailbox)` is the first statement of `do_prereg`.

- [ ] **Step 4b: BLOCKED as a pre-INTENT refusal record (E3, pending Codex acceptance of E3).**
  - Implement in the working tree with the rest of Task 10. This step's code must NOT be committed until Erratum 1
    is adopted (BLK-1).
  - If Codex amends E3 before adoption, rework this step and rows 271–274 to the amended text first.

```python
def blocked_reasons_record(out, cal) -> dict:
    """E3.1: a pure function of committed inputs only - the CREATED audit tree (calendar, corporate actions), the
    CREATED opening seal and receipt, and plan.json. Every re-run gives the same record (E3.2, E3.6b)."""
    plan = _load(Path(out) / "plan.json")
    seal_p, seal = _opening_seal(Path(out), plan, cal)
    reasons = _blocked_reasons(Path(out), plan, cal, seal)            # the existing c9b4322 predicate, unchanged
    return {"trial_id": plan["trial_id"], "reasons": reasons}


def _blocked_refusal(out, cal) -> None:
    """E3.2: after the prereg gates and before the prereg STAGE-INTENT. With reasons, publish s1_out/blocked.json
    exclusively (the existing content plus trial_id, E5.4; recorded_utc = the observation time), or keep an existing
    one whose reasons equal the recomputation, and refuse with no journal row. Never INVALID (E3.3)."""
    rec = blocked_reasons_record(out, cal)
    if not rec["reasons"]:
        return
    p = Path(out) / "blocked.json"
    body = {"status": "BLOCKED", "trial_id": rec["trial_id"], "reasons": rec["reasons"],
            "recorded_utc": c.now_utc().isoformat()}
    try:
        c.publish_exclusive(p, json.dumps(body, indent=1).encode("utf-8"))
    except FileExistsError:
        if _load(p).get("reasons") != rec["reasons"]:
            raise SystemExit("prereg refused: blocked.json differs from the recomputed BLOCKED reasons: "
                             "escalate") from None
    raise SystemExit(f"S1 BLOCKED (pre-START units): {rec['reasons'][:3]} - prereg refused with no journal row "
                     f"(E3); Codex closes the trial with reason=BLOCKED")


def blocked_close_evidence(out) -> str:
    """E3.4 (Erratum 1 r1): the BLOCKED CLOSE evidence h = sha256(c.canonical({"trial_id", "reasons"})) of the
    deterministic recomputation from committed inputs. It never reads blocked.json, so deleting or re-creating that
    file never changes h and never re-opens a closed trial."""
    out = Path(out)
    return c.sha256_bytes(c.canonical(blocked_reasons_record(out, c.load_json(out / "audit" / "calendar.json"))))
```

  `s1_trial._blocked_evidence_problem` (Task 4) already calls `s1_run.blocked_close_evidence`; from this task on the
  recomputation exists, so a correct BLOCKED CLOSE closes and a wrong one is refused (rows 273, 328).

  In `do_prereg`, the existing BLOCKED block is replaced by `_blocked_refusal(out, cal)`. It sits at the same place,
  after the gate and the RUN-ACK verification and before `s1_stage.run(gv, "prereg", …)`. The refusal text's prefix
  `S1 BLOCKED (pre-START units)` is unchanged.

  BLOCKED is never in `TRIAL_ID_MEMBERS` or any stage table. `s1_stage.evaluate`'s "no INTENT: any artifact for g"
  rule lists prereg's artifacts as `prereg.json` and its stage records only, so `blocked.json` is outside it (E3.2).

- [ ] **Step 5: GREEN.** Run `test_s1_a3_prestart.py`, `test_s1_a3_codex_probes.py` and all A3 files into
  `a3/t10_green.txt`.
- [ ] **Step 6: Full suite, old->new.** Expected intended changes:
  - **N-2/R-3 (fix rounds 4/5) -> F3 + F4:** opening orphan and after-seal tests now see INVALID (stage-replaced or
    registration-artifact) or a refusal with no row. This affects `test_s1_t12_fix4.py`, `test_s1_t12_fix5.py` and
    `test_s1_t12_fix2_b3.py::test_b3_opening_re_entry_cannot_bypass_persistence`.
  - **B3 (A8.1) -> F7.2:** `attest_start` needs the OPENING-ACK. Tests that call it after a bare opening now issue
    `s1_ack(..., "S1-OPENING-ACK", ...)`. This is a fixture change through `s1_register`/`s1_state`.
  - **Codex probes:** the historical V1 and prereg-restoration observations are reversed (see the probe map).
  - **E3 (pending):** blocked.json gains `trial_id`. Every test that asserted `set(blocked) == {"status",
    "reasons", "recorded_utc"}` is listed as an intended change (E5.4).
  - **F7.2(b) literal:** every fixture that issued the OPENING-ACK before the opening close's W slot is moved after
    `close_out` (fixture change; list each).
  - **OQ-15:** the RUN-ACK's `opening_books_sha256` is now the file sha256 of the published `opening_books.json`.
    It was `k.json_sha256(books)` in revision 0 and in c9b4322. List any test asserting the old value.

  Record in `a3/t10_old_new.md` the Erratum 1 adoption state (and the adopted revision). Save `a3/t10_full.txt` and
  `a3/t10_hashes.txt`.
- [ ] **Step 7: Controller review and commit.** This step waits for BLK-1 (Erratum 1 adopted, which also settles E3
  and fixes E5.5). Message: `S1 A3 Task 10: opening seal, start_attest and prereg as stages; OPENING-ACK
  verification and evidence manifest; E3 BLOCKED record`, listing map rows 81, 103–105, 121, 151, 152, 154–156,
  177, 178, 180, 249–252, 268–274, 279, 280, 316, 326–329, 332 and 333, with the Co-Authored-By line. Push and
  assert the HEAD SHA.

---

### Task 11: STOP and the finalization prefix: F2 stop record, TRIAL-STOP, stop.json, stop_attest and final_plan stages (F1 graph steps 1–3, STOP prefix, F2.1–F2.5; OQ-8, OQ-9)

**Files:**
- Modify: `research/s1/s1_seal.py`:
  - add `sampled_seals`, `stop_record`, `decide_stop` and `stop_check`;
  - `current_stop(out, start, calendar, now, by, *, mailbox=None)` reads the journal: the TRIAL-STOP + stop.json, or
    RUNNING; it never persists;
  - `stop_problems` rechecks with `stop_record` (OQ-8);
  - `persist_stop` is used only by `decide_stop` and `stop_check`.
- Modify: `research/s1/s1_checkpoint.py`:
  - `_after_qualified` calls `s1_seal.decide_stop` after the seal;
  - the finalizer paths (`_finalize_others`, the opening/post-START callers) call `decide_stop` after
    `finalize_close`.
- Modify: `research/s1/s1_run.py:attest_stop` (lines 563–597) and `research/s1/s1_collect.py:write_final_plan`
  (lines 431–436) run as stages; `final_plan_record` adds `"trial_id"`.
- Modify: `research/s1/s1_trial.py:gate`. Add the hook `s1_seal.stop_check(gv)` before `s1_stage.evaluate`.
- Modify: `research/s1/s1_stage.py`: `ENFORCED |= {"stop_attest", "final_plan"}`.
- Modify: `research/s1/s1_tests/conftest.py`. `s1_state(score_ready=True)` reaches its stop through `decide_stop`
  (seals via `_write_seal`, which carries real slot rows since Task 7). For a timeout it runs `s1_slot.finalize_close`
  on the last eligible close at its window end first. The synthetic TRIAL-STOP of Task 5 is removed.
- Create: `research/s1/s1_tests/test_s1_a3_stop.py`; `research/s1/s1_evidence/a3/t11_dispositions.md` (Step 2a,
  BLK-3).
- Modify: `research/s1/s1_tests/a3_helpers.py`: add `stop_history(root, start, case) -> {"calendar", "want"}`,
  which builds each accepted disposition's history (synthetic seals with real slot rows) and its accepted expected
  fields.
- Modify: `research/s1/s1_slot.py:required_seals`. Once a TRIAL-STOP exists and stop.json parses to its committed
  record, the record's `seals` are added (E2.4: "listed in the F2 stop record").

**Interfaces:**
- Produces (`s1_seal`):
  - `sampled_seals(out, rows, cal, start, upto_seq=None) -> dict[str, tuple[Row, bytes]]` (day -> (first QUALIFIED
    row, recomputed seal bytes));
  - `stop_record(out, rows, start, cal, bundle) -> dict | None`;
  - `decide_stop(gv, cal, start, now, *, mailbox=None) -> dict | None`;
  - `stop_check(gv) -> None`.

- [ ] **Step 1: Interface stub.**
  - `stop_record` returns None; `decide_stop` calls the legacy `current_stop` (which persists stop.json without a
    row); `stop_check` is a no-op; `sampled_seals` returns `{}`.
  - `attest_stop`/`write_final_plan` keep their c9b4322 bodies behind the gate.

- [ ] **Step 2a: Stop dispositions for Codex (OQ-8 AMEND; BLK-3).**
  - Before any Task 11 code, write `research/s1/s1_evidence/a3/t11_dispositions.md`. For each disposition below it
    gives the frozen calendar dates, the deadline instant and the pending-close rule, as worked examples computed
    by hand from `docs/s1_design_v5.md` and the pinned calendar:
    1. the earliest qualifying lot-count close (row 300);
    2. a later qualifying close that is not chosen (row 301);
    3. TIMEOUT with the last sealed eligible close (row 302);
    4. NO-VALID-SEAL (row 303);
    5. pending-close exclusion (B1.5; row 304);
    6. six-month eligibility by close instant at the deadline (A5.1; row 305).
  - It also states the open choice: is the triggering slot for TIMEOUT and NO-VALID-SEAL the last eligible close's
    W slot, or another determinable row?
  - The controller sends it to Codex. Steps 4–7 of this task do not start until Codex accepts the dispositions and
    the stop-record shape (BLK-3).
  - Steps 2–3 (tests and RED) may be written first. The rows 300–305 expected outcomes are the ones Codex accepts:
    if Codex amends a disposition, the test is changed before Step 4.

- [ ] **Step 2: Write the failing tests.** `research/s1/s1_tests/test_s1_a3_stop.py`:

```python
"""Addendum 3 rev 5 F1 (graph steps 1-3; STOP prefix; post-STOP rules), F2.1-F2.5 (the stop record, TRIAL-STOP then
stop.json, the publication gap, required evidence after a finalization INTENT), F4.8 rows stop_attest/final_plan,
OQ-8/OQ-9. Behavioural RED against the Task 11 stub (s1_evidence/a3/t11_red.txt). Synthetic seals with real slot rows
(conftest._write_seal); tmp mailbox; spies."""
import json
from datetime import timedelta
from pathlib import Path

import pytest
import a3_helpers as h
import s1_collect as k
import s1_common as c
import s1_journal as j
import s1_run as r
import s1_seal as z
import s1_slot as sl
import s1_stage as sg
import s1_trial as t
from conftest import S1_RECEIPT, Spies, _Clock, _write_seal, s1_ack, s1_jappend, s1_state

START = "2026-10-26T13:30:00+00:00"


def mb(root):
    return Path(root) / "mailbox.sqlite3"


def jrows(root):
    tr = t.open_trial(mb(root))
    return j.read_trial(tr.trial_id, tr.genesis, mb(root))


def stopped(tmp_path, *, attest=False):
    """A lot-count STOP on post-START day 1 (100 default lots bought day 0, sold day 1), decided by decide_stop."""
    st_ = s1_state(tmp_path, START, score_ready=True, stop_attest=attest, final=False)
    return st_


def test_stop_record_is_a_pure_function_of_committed_history(tmp_path):
    st_ = stopped(tmp_path)
    out = tmp_path / "s1_out"
    rows = jrows(tmp_path)
    stop = j.first(rows, "TRIAL-STOP")
    pre = [x for x in rows if x.seq < stop.seq]
    a = z.stop_record(out, pre, st_["start"], st_["calendar"], t.open_trial(mb(tmp_path)).bundle)
    b = z.stop_record(out, list(pre), st_["start"], st_["calendar"], t.open_trial(mb(tmp_path)).bundle)
    assert a == b and j.detail_of(a) == stop.detail
    trig = next(x for x in pre if x.subject == a["triggering_slot"] and x.kind in j.TERMINAL)
    assert (a["rule"], a["status"], a["terminal_seq"], a["terminal_line_sha256"], a["determined_utc"]) == (
        "lots", "STOPPED", trig.seq, trig.sha, trig.at)
    assert set(a) >= {"lots", "stop_close", "stop_seal", "stop_seal_sha256", "cohort_row_ids", "seals", "missed",
                      "bundle_sha256", "trial_id"} and "decided_utc" not in a


def test_trial_stop_is_appended_before_stop_json_is_published(tmp_path, monkeypatch):
    seen = {}
    real = c.publish_text_exclusive

    def spy(path, text):
        if Path(path).name == "stop.json":
            seen["rows"] = [x.kind for x in jrows(Path(path).parent.parent)]
        return real(path, text)
    monkeypatch.setattr(c, "publish_text_exclusive", spy)
    stopped(tmp_path)
    assert "TRIAL-STOP" in seen["rows"]
    stop = j.first(jrows(tmp_path), "TRIAL-STOP")
    assert j.detail_of(json.loads((tmp_path / "s1_out" / "stop.json").read_text(encoding="utf-8"))) == stop.detail


def test_publication_gap_recovers_matching_bytes(tmp_path, monkeypatch):
    real = c.publish_text_exclusive
    calls = []

    def crash_once(path, text):
        if Path(path).name == "stop.json" and not calls:
            calls.append(1)
            raise KeyboardInterrupt                               # a crash between TRIAL-STOP and stop.json
        return real(path, text)
    monkeypatch.setattr(c, "publish_text_exclusive", crash_once)
    with pytest.raises(KeyboardInterrupt):
        stopped(tmp_path)
    monkeypatch.setattr(c, "publish_text_exclusive", real)
    assert not (tmp_path / "s1_out" / "stop.json").exists() and j.first(jrows(tmp_path), "TRIAL-STOP")
    t.gate(tmp_path, "gap recovery")
    stop = j.first(jrows(tmp_path), "TRIAL-STOP")
    assert j.detail_of(json.loads((tmp_path / "s1_out" / "stop.json").read_text(encoding="utf-8"))) == stop.detail
    assert all(x.kind != "TRIAL-INVALID" for x in jrows(tmp_path))


def test_publication_gap_with_different_history_is_stop_conflict(tmp_path):
    st_ = s1_state(tmp_path, START)                              # no stop rule met yet
    s1_jappend(tmp_path, "TRIAL-STOP", "trial", at=st_["now"], detail=j.detail_of({"forged": True}))
    with pytest.raises(SystemExit, match=r"INVALID \(stop-conflict\)"):
        t.gate(tmp_path, "gap recovery")


@pytest.mark.parametrize("damage", ["deleted", "changed", "unparseable"])
def test_stop_json_damaged_after_a_finalization_intent_is_invalid(tmp_path, monkeypatch, damage):
    stopped(tmp_path, attest=True)                               # stop_attest CREATED: a finalization INTENT exists
    p = tmp_path / "s1_out" / "stop.json"
    keep = p.read_bytes()
    if damage == "deleted":
        p.unlink()
    else:
        p.write_text("{}" if damage == "changed" else "{not JSON", encoding="utf-8")
    with pytest.raises(SystemExit, match="INVALID"):
        t.gate(tmp_path, "stop evidence")
    p.unlink(missing_ok=True)
    p.write_bytes(keep)
    (tmp_path / "s1_out" / "aborted.json").unlink(missing_ok=True)
    sp = Spies(monkeypatch)
    with pytest.raises(SystemExit, match="INVALID"):
        t.gate(tmp_path, "restored")
    sp.assert_zero()


def test_stop_outcome_is_fixed_by_the_journal(tmp_path):
    stopped(tmp_path)
    tr = t.open_trial(mb(tmp_path))
    stop = j.first(jrows(tmp_path), "TRIAL-STOP")
    same = j.append(tr.trial_id, tr.genesis, j.Request("TRIAL-STOP", "trial", j.new_nonce(), j.new_nonce(),
                                                       detail=stop.detail),
                    t.product_context(tr), mailbox=mb(tmp_path), clock=c.now_utc)
    assert same.outcome == "LOST-RACE"
    other = j.append(tr.trial_id, tr.genesis, j.Request("TRIAL-STOP", "trial", j.new_nonce(), j.new_nonce(),
                                                        detail="9" * 64),
                     t.product_context(tr), mailbox=mb(tmp_path), clock=c.now_utc)
    assert (other.outcome, other.reason) == ("INVALIDATE", "stop-conflict")


def test_a_stop_with_a_different_detail_is_invalid_stop_conflict(tmp_path, monkeypatch):
    st_ = s1_state(tmp_path, START, score_ready=True, stop_attest=False, final=False)
    first = j.first(jrows(tmp_path), "TRIAL-STOP")
    (tmp_path / "s1_out" / "stop.json").unlink()                  # a gap, then a different history is recomputed
    monkeypatch.setattr(z, "stop_record", lambda *a, **kw: {"forged": "different"})
    with pytest.raises(SystemExit, match=r"INVALID \(stop-conflict\)"):
        t.gate(tmp_path, "recompute")
    assert first is not None


def test_stop_rule_not_met_refuses_with_no_row(tmp_path):
    st_ = s1_state(tmp_path, START, score_ready=True, lots=[{"symbol": "A", "qty": 1, "px": 10.0, "buy_day": 0,
                                                             "sell": (1, 9.0)}], stop_attest=False, final=False,
                   stop=False)
    gv = t.gate(tmp_path, "decide")
    assert z.decide_stop(gv, st_["calendar"], st_["start"], lambda: st_["now"], mailbox=mb(tmp_path)) is None
    assert j.first(jrows(tmp_path), "TRIAL-STOP") is None


def test_pending_slot_blocks_the_stop(tmp_path):
    """B1.5 kept (OQ-8): an in-flight slot on an eligible close before the triggering close blocks the stop."""
    st_ = s1_state(tmp_path, START, score_ready=True, seal_days=[1], stop_attest=False, final=False, stop=False)
    day0 = st_["sessions"][0]
    s45 = z.close_of(day0, st_["calendar"]) + timedelta(minutes=45)
    s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(s45), at=s45 + timedelta(seconds=1))
    gv = t.gate(tmp_path, "decide")
    assert z.stop_record(gv.out, gv.rows, st_["start"], st_["calendar"], gv.trial.bundle) is None


def test_stop_lock_is_taken_before_the_journal_read(tmp_path, monkeypatch):
    import s1_locks as L
    order = []
    real_acq, real_read, real_app = L.OwnershipLock.acquire, j.read_trial, j.append
    monkeypatch.setattr(L.OwnershipLock, "acquire", lambda self: order.append(("lock", self.path.name))
                        or real_acq(self))
    monkeypatch.setattr(j, "read_trial", lambda *a, **kw: order.append(("read",)) or real_read(*a, **kw))
    monkeypatch.setattr(j, "append", lambda *a, **kw: order.append(("append", a[2].kind)) or real_app(*a, **kw))
    stopped(tmp_path)
    i_lock, i_stop = order.index(("lock", "stop.lock")), order.index(("append", "TRIAL-STOP"))
    assert i_lock < i_stop and ("read",) in order[i_lock:i_stop]


def _envelope(root, stage):
    tr = t.open_trial(mb(root))
    return json.loads((sg.staging_dir(root, tr.trial_id, stage) / "intent.json").read_bytes())


def test_stop_attest_envelope_and_member(tmp_path):
    stopped(tmp_path, attest=True)
    e = _envelope(tmp_path, "stop_attest")
    stop = j.first(jrows(tmp_path), "TRIAL-STOP")
    assert e["inputs"] == {"stop.json": c.sha256_file(tmp_path / "s1_out" / "stop.json"), "trial_stop_line": stop.sha}
    att = json.loads((tmp_path / "s1_out" / "attest_stop.json").read_text(encoding="utf-8"))
    assert att["stop_line_sha256"] == stop.sha and att["trial_id"] == t.open_trial(mb(tmp_path)).trial_id


def test_final_plan_envelope_and_member(tmp_path):
    stopped(tmp_path, attest=True)
    with _Clock(jrows(tmp_path)[-1].instant + timedelta(hours=1)):
        k.write_final_plan(tmp_path)
    e = _envelope(tmp_path, "final_plan")
    assert set(e["inputs"]) == {"stop.json", "attest_stop.json", "prereg.json", "plan.json"}
    assert json.loads((tmp_path / "s1_out" / "final_plan.json").read_text(encoding="utf-8"))["trial_id"]


def test_final_plan_before_stop_attest_refuses_with_no_row(tmp_path):
    stopped(tmp_path, attest=False)
    with _Clock(jrows(tmp_path)[-1].instant + timedelta(hours=1)), pytest.raises(SystemExit):
        k.write_final_plan(tmp_path)
    assert [x.kind for x in j.subject_rows(jrows(tmp_path), "stage/final_plan")] == []


@pytest.mark.parametrize("stage", ["stop_attest", "final_plan", "final", "score"])
def test_finalization_stages_are_refused_while_active(tmp_path, monkeypatch, stage):
    st_ = s1_state(tmp_path, START, score_ready=True, stop_attest=False, final=False, stop=False)
    sp = Spies(monkeypatch)
    with _Clock(st_["now"]), pytest.raises(SystemExit):
        {"stop_attest": lambda: r.attest_stop(tmp_path, r.STOP_STATEMENT),
         "final_plan": lambda: k.write_final_plan(tmp_path),
         "final": lambda: k.do_final(tmp_path, "acq-ack", sp.client(), ("k", "s")),
         "score": lambda: r.score(tmp_path, "score-ack")}[stage]()
    sp.assert_zero()
    assert j.subject_rows(jrows(tmp_path), j.stage_subject(stage)) == []


def _in_flight_across_the_stop(tmp_path, monkeypatch):
    """A day-2 slot's INTENT commits before the STOP (decided on the day-1 seal) and its QUALIFIED after it: the
    TRIAL-STOP is appended from inside the worker, just before its J (F1 row 2: INTENT seq < STOP seq)."""
    import s1_checkpoint as ck
    from conftest import S1_PROCESS
    st_ = s1_state(tmp_path, START, score_ready=True, stop_attest=False, final=False, stop=False)
    day2 = st_["sessions"][2]
    sch = z.close_of(day2, st_["calendar"]) + timedelta(minutes=45)
    at = sch + timedelta(seconds=30)
    real = sl.Worker._append

    def stop_first(self, req):
        if req.kind == "SLOT-QUALIFIED":
            z.decide_stop(t.gate(tmp_path, "stop decision"), st_["calendar"], st_["start"], lambda: at,
                          mailbox=mb(tmp_path))
        return real(self, req)
    monkeypatch.setattr(sl.Worker, "_append", stop_first)
    with _Clock(at):
        rep = ck.run_checkpoint(tmp_path, st_["ledger"].path, sch, lambda reference=None: S1_RECEIPT,
                                lambda: dict(S1_PROCESS), tmp_path / "c.log", now=lambda: at)
    monkeypatch.setattr(sl.Worker, "_append", real)
    rows = jrows(tmp_path)
    mine = j.subject_rows(rows, j.slot_subject(sch))
    return st_, day2, rows, mine, j.first(rows, "TRIAL-STOP"), rep


def test_in_flight_slot_started_before_the_stop_completes_but_never_enters_final_or_score(tmp_path, monkeypatch):
    st_, day2, rows, mine, stop, rep = _in_flight_across_the_stop(tmp_path, monkeypatch)
    intent, qual = j.first(mine, "SLOT-INTENT"), j.first(mine, "SLOT-QUALIFIED")
    assert intent.seq < stop.seq < qual.seq                       # completed after the stop (allowed)
    rec = json.loads((tmp_path / "s1_out" / "stop.json").read_text(encoding="utf-8"))
    assert f"seals/{day2}.json" not in rec["seals"]
    hist = z.sampled_history(rows, stop, z.sampled_seals(tmp_path / "s1_out", rows, st_["calendar"], st_["start"],
                                                         upto_seq=stop.seq))
    assert qual.sha not in hist["rows"] and f"seals/{day2}.json" not in hist["seals"]


def test_post_stop_sampled_slot_is_excluded_from_the_sampled_history(tmp_path, monkeypatch):
    st_, day2, rows, mine, stop, rep = _in_flight_across_the_stop(tmp_path, monkeypatch)
    assert day2 not in z.sampled_seals(tmp_path / "s1_out", rows, st_["calendar"], st_["start"], upto_seq=stop.seq)
    assert day2 not in z.sampled_seals(tmp_path / "s1_out", rows, st_["calendar"], st_["start"])   # never sealed


def test_no_new_seal_after_the_stop(tmp_path, monkeypatch):
    st_, day2, rows, mine, stop, rep = _in_flight_across_the_stop(tmp_path, monkeypatch)
    assert not (tmp_path / "s1_out" / "seals" / f"{day2}.json").exists()
    assert "outside ACTIVE" in (rep.get("refused") or "")                       # E2.1 wording (Task 7)


def test_decide_stop_publishes_every_sampled_seal_before_trial_stop(tmp_path, monkeypatch):   # row 262 (E2 gap)
    st_ = s1_state(tmp_path, START, score_ready=True, stop=False)    # seals + rows; decide_stop not yet run
    seal_dir = tmp_path / "s1_out" / "seals"
    order = []
    real_pub, real_app = c.publish_exclusive, j.append
    monkeypatch.setattr(c, "publish_exclusive", lambda p, d: (order.append(("seal", Path(p).name))
                                                              if Path(p).parent == seal_dir else None,
                                                              real_pub(p, d))[1])
    monkeypatch.setattr(j, "append", lambda *a, **k: (order.append(("row", a[2].kind)), real_app(*a, **k))[1])
    victim = sorted(seal_dir.glob("*.json"))[-1]
    victim.unlink()                                       # an unpublished (not yet required) sampled seal
    gv = t.gate(tmp_path, "decide")
    at = c.aware(START) + timedelta(days=2)               # after post-START day 1's close
    with _Clock(at):
        rec = z.decide_stop(gv, st_["calendar"], c.aware(START), lambda: at, mailbox=mb(tmp_path))
    assert rec is not None and victim.exists()
    assert order.index(("seal", victim.name)) < order.index(("row", "TRIAL-STOP"))


# ---------------------------------------------------------------- OQ-8 dispositions (rows 300-305; BLK-3)
@pytest.mark.parametrize("case", ["lots-earliest", "lots-later-not-chosen", "timeout-last-sealed", "no-valid-seal",
                                  "pending-excluded", "deadline-instant-eligibility"])
def test_stop_dispositions(tmp_path, case):
    """Expected outcomes are the Step 2a dispositions as ACCEPTED by Codex (BLK-3); s1_state builds each history
    from `a3_helpers.stop_history(case)` (synthetic seals with real slot rows)."""
    hist = h.stop_history(tmp_path, START, case)
    rec = z.stop_record(tmp_path / "s1_out", jrows(tmp_path), c.aware(START), hist["calendar"],
                        t.open_trial(mb(tmp_path)).bundle)
    want = hist["want"]                                   # from t11_dispositions.md as accepted
    if want is None:
        assert rec is None
    else:
        assert {k_: rec[k_] for k_ in want} == want
```

`s1_state` gains the keywords `stop=True` (False: seals are written but `decide_stop` is not run, and no attestation
or final step follows) and `score_ack=True` (Task 13), and returns `opening_close` in its info dict (Task 14). All are
added in this task's conftest change.


- [ ] **Step 3: Behavioural RED.** Run into `a3/t11_red.txt`.
  - Expected: no TRIAL-STOP row (the legacy stop.json without a row); `stop_record` is None; no publication-gap
    recovery; damaged stop.json after attest is not INVALID; stop_attest/final_plan are not stages.
  - Revision 1:
    - `test_decide_stop_publishes_every_sampled_seal_before_trial_stop` fails: no row, no publication;
    - `test_stop_dispositions[*]` fails (`stop_record` is None) except `pending-excluded`, which passes on the
      stub. Label that case `ctrl`.

  STOP here until BLK-3 is cleared. Steps 4–7 implement the dispositions as Codex accepted them. The `stop_record`
  code below is the revision-0 proposal and is changed to match the acceptance before use.

- [ ] **Step 4: Implement.** In `s1_seal.py`, add:

```python
def sampled_seals(out, rows, cal, start, upto_seq=None) -> dict:
    """F1 STOP prefix / OQ-14: {day: (first QUALIFIED row, recomputed seal bytes)} for every post-START close whose
    first QUALIFIED slot (every earlier slot terminal) was committed at or before `upto_seq` (all rows when None)."""
    import s1_journal as j
    import s1_slot
    rows = [x for x in rows if upto_seq is None or x.seq <= upto_seq]
    got = {}
    for d in eligible_sessions(start, cal):
        q = s1_slot.first_qualified(rows, d, cal)
        if q is not None:
            ev = s1_slot._resolution_evidence(out, q, d["date"])
            got[d["date"]] = (q, s1_slot.seal_bytes(d, _close(d), ev))
    return got


def _close_state(rows, d, cal) -> str:
    """'sealed' | 'pending' (some slot has an INTENT and no terminal) | 'open' (otherwise unsealed)."""
    import s1_journal as j
    import s1_slot
    if s1_slot.first_qualified(rows, d, cal) is not None:
        return "sealed"
    for s in schedule(d, cal):
        mine = j.subject_rows(rows, j.slot_subject(s))
        if j.first(mine, "SLOT-INTENT") is not None and j.first(mine, *j.TERMINAL) is None:
            return "pending"
    return "open"


def stop_record(out, rows, start, cal, bundle) -> dict:
    """F2.1 / OQ-8: the stop record as a pure function of committed history (rows + the files they commit), or None
    while the rule is not met. Lots rule: the first eligible close, in order, whose seal sells >= STOP_N cohort lots,
    with no earlier eligible close pending (B1.5); the triggering slot is its first QUALIFIED slot. Timeout rule (six
    months): the last eligible close's last scheduled slot (its W slot) has a terminal row and no eligible close is
    pending; TIMEOUT (the last sealed close) or NO-VALID-SEAL; the triggering slot is that W slot."""
    import s1_journal as j
    tid = {x.trial_id for x in rows}.pop() if rows else None
    eligible = eligible_sessions(start, cal)
    seals = sampled_seals(out, rows, cal, start)
    missed, trig, status, stop_day = [], None, None, None
    for d in eligible:
        stt = _close_state(rows, d, cal)
        if stt == "pending":
            return None
        if stt == "open":
            missed.append(d["date"])
            continue
        q, data = seals[d["date"]]
        if count_sold(json.loads(data)["trades"], start, _close(d)) >= STOP_N:
            trig, status, stop_day = q, "STOPPED", d
            break
    if trig is None:
        if not eligible:
            return None
        last = eligible[-1]
        w_slot = schedule(last, cal)[-1]
        w_rows = j.subject_rows(rows, j.slot_subject(w_slot))
        trig = j.first(w_rows, *j.TERMINAL)
        if trig is None:
            return None
        sealed = [d for d in eligible if d["date"] in seals]
        status, stop_day = ("TIMEOUT", sealed[-1]) if sealed else ("NO-VALID-SEAL", None)
        missed = [x for x in missed if x != last["date"] or last["date"] not in seals]
    rec = {"trial_id": tid, "rule": "lots" if status == "STOPPED" else "timeout", "status": status,
           "triggering_slot": trig.subject, "terminal_seq": trig.seq, "terminal_line_sha256": trig.sha,
           "determined_utc": trig.at, "missed": missed, "bundle_sha256": bundle,
           "stop_close": None, "stop_seal": None, "stop_seal_sha256": None, "cohort_row_ids": [], "lots": None}
    if stop_day is not None:
        sc = _close(stop_day)
        q, data = seals[stop_day["date"]]
        trades = [x for x in json.loads(data)["trades"] if c.aware(x["ts"]) <= sc]
        ids = sorted(x["id"] for x in cohort(trades, start, sc))
        rec.update(stop_close=sc.isoformat(), stop_seal=f"seals/{stop_day['date']}.json",
                   stop_seal_sha256=c.sha256_bytes(data), cohort_row_ids=ids,
                   lots={"sold": count_sold(trades, start, sc), "cohort": len(ids)})
        rec["seals"] = {f"seals/{dd}.json": c.sha256_bytes(b_) for dd, (_, b_) in seals.items()
                        if _close(next(x for x in eligible if x["date"] == dd)) <= sc}
    else:
        rec["seals"] = {f"seals/{dd}.json": c.sha256_bytes(b_) for dd, (_, b_) in seals.items()}
    return rec


def decide_stop(gv, cal, start, now, *, mailbox=None):
    """F2.2: when committed history meets the stop rule, append TRIAL-STOP (detail = sha256 of the record; the record
    recomputed inside the transaction, OQ-9) under the stop lock (F5.1), then publish stop.json. Returns the record,
    or None (rule not met: no row)."""
    import s1_journal as j
    import s1_locks as L
    import s1_slot
    import s1_trial
    with L.OwnershipLock(gv.root, gv.trial.trial_id, L.STOP_LOCK):
        rows = j.read_trial(gv.trial.trial_id, gv.trial.genesis, mailbox)
        if j.first(rows, "TRIAL-STOP") is not None:
            return None
        rec = stop_record(gv.out, rows, start, cal, gv.trial.bundle)
        if rec is None:
            return None
        # E2.5 (Erratum 1 r1): holding the stop lock, publish EVERY determined seal that is not yet published, then
        # re-read the journal, then append TRIAL-STOP - so a seal determined before the STOP never becomes
        # unpublishable (E2.1 does not apply to this pre-append step).
        for d in eligible_sessions(start, cal):
            got = s1_slot.publish_seal(gv, d, cal, {"written": False, "sha256": None, "from_slot": None,
                                                    "deferred": None, "refused": None}, mailbox=mailbox,
                                       stop_lock_held=True)        # a close with no determined seal: no-op
            if got.get("refused") or (got.get("deferred") and "opening" not in got["deferred"]):
                return None                                       # no STOP while a determined seal is unpublished
        rows = j.read_trial(gv.trial.trial_id, gv.trial.genesis, mailbox)
        if stop_record(gv.out, rows, start, cal, gv.trial.bundle) != rec:
            return None                                           # history moved: decide again later
        res = j.append(gv.trial.trial_id, gv.trial.genesis,
                       j.Request("TRIAL-STOP", j.TRIAL_SUBJECT, j.new_nonce(), j.new_nonce(), detail=j.detail_of(rec)),
                       s1_trial.product_context(gv.trial, stop_detail=lambda rows_: (
                           None if (x := stop_record(gv.out, rows_, start, cal, gv.trial.bundle)) is None
                           else j.detail_of(x))),
                       mailbox=mailbox, clock=now)
        if res.outcome == "INVALIDATE":
            raise SystemExit(f"TRIAL-STOP -> INVALID ({res.reason})")
        if res.outcome != "APPEND":
            return None
        persist_stop(gv.out, rec)
        return rec


def stop_check(gv) -> None:
    """Gate hook (F2.3/F2.4): with a TRIAL-STOP, stop.json must parse to the record its detail commits. Absent before
    any finalization INTENT: the publication gap - recompute from committed history and publish matching bytes, else
    INVALID (stop-conflict). Absent, changed or unparseable after a finalization INTENT: INVALID
    (registration-artifact); restoring never resumes."""
    import s1_journal as j
    import s1_stage
    import s1_trial
    stop = j.first(gv.rows, "TRIAL-STOP")
    if stop is None:
        return
    p = gv.out / "stop.json"
    fin = any(s1_stage.stage_rows(gv.rows, s)["intent"] is not None
              for s in ("stop_attest", "final_plan", "final", "score"))
    try:
        ok = j.detail_of(json.loads(p.read_text(encoding="utf-8"))) == stop.detail if p.exists() else None
    except (OSError, ValueError):
        ok = False
    if ok:
        return
    if fin or ok is False:
        reason = "registration-artifact" if fin else "stop-conflict"
        s1_trial.invalidate(gv.trial, reason, {"stop.json": "missing" if ok is None else "changed or unparseable"},
                            root=gv.root, mailbox=gv.mailbox)
        raise SystemExit(f"stop.json missing, changed or unparseable: INVALID ({reason}) (F2.3/F2.4)")
    pr = c.load_json(gv.out / "prereg.json")
    rec = stop_record(gv.out, [x for x in gv.rows if x.seq < stop.seq], c.aware(pr["start"]), pr["calendar"],
                      gv.trial.bundle)
    if rec is None or j.detail_of(rec) != stop.detail:
        s1_trial.invalidate(gv.trial, "stop-conflict", {"recomputed": None if rec is None else j.detail_of(rec)},
                            root=gv.root, mailbox=gv.mailbox)
        raise SystemExit("publication gap: the recomputed stop record differs: INVALID (stop-conflict) (F2.3)")
    persist_stop(gv.out, rec)
```

`persist_stop(out, rec)` publishes `json.dumps(rec, indent=1, sort_keys=True)` exclusively; an identical existing file
is accepted. The legacy `register_stage(out, "stop", ...)` call is kept (OQ-19).

`current_stop(out, start, calendar, now, by, *, mailbox=None)`: when the open trial's journal has a TRIAL-STOP,
return `{"status", "stop_close", "missed"}` from stop.json with `persisted=True`; otherwise return `RUNNING` with
`persisted=False`. It never persists.

`stop_problems(..., recheck=True)` keeps its file checks. Its recheck becomes "stop.json equals
`stop_record(out, rows before the STOP, …)`".

`s1_run.attest_stop` becomes a stage. Its legacy checks stay. The record adds `"trial_id": plan["trial_id"]` and
`"stop_line_sha256"`. Then:

```python
    stop_row = j.first(gv.rows, "TRIAL-STOP")
    rec = {..., "stop_line_sha256": stop_row.sha, "recorded_utc": c.now_utc().isoformat()}

    def work(sw):
        sw.put_json("attest_stop.json", dict(rec, intent_at=sw.intent_at))
        return []
    s1_stage.run(gv, "stop_attest", inputs={"stop.json": c.sha256_file(out / "stop.json"),
                                            "trial_stop_line": stop_row.sha}, acks={}, work=work, mailbox=mailbox)
```

`s1_collect.write_final_plan`:

```python
def write_final_plan(root, *, mailbox=None) -> Path:
    """Stage `final_plan` (F1 step 3; F4.8): after stop_attest's CREATED row (s1_stage.permitted refuses the INTENT
    with no row otherwise); derived from the persisted stop (unchanged final_plan_record) plus the trial_id."""
    import s1_stage
    import s1_trial
    gv = s1_trial.gate(root, "final plan", mailbox=mailbox)
    out = _out(root)
    rec = dict(final_plan_record(root, mailbox=mailbox), trial_id=gv.trial.trial_id)
    _stop_attestation(out, rec)

    def work(sw):
        sw.put_json("final_plan.json", dict(rec, intent_at=sw.intent_at))
        return []
    s1_stage.run(gv, "final_plan", inputs={n: c.sha256_file(out / n) for n in ("stop.json", "attest_stop.json",
                                                                              "prereg.json", "plan.json")},
                 acks={}, work=work, mailbox=mailbox)
    return out / "final_plan.json"
```

`do_final`'s comparison `plan != rec` becomes a comparison of `plan` minus `intent_at` with `rec` plus `trial_id`.

`s1_trial.gate`: insert `import s1_seal; s1_seal.stop_check(Gate(...))` before `s1_stage.evaluate`.
`s1_stage.ENFORCED` adds `stop_attest` and `final_plan`.

In `s1_checkpoint._after_qualified`, replace the legacy `current_stop` block with
`got["stop"] = s1_seal.decide_stop(gv, cal, start, now, mailbox=mailbox)`. `_finalize_others` (and the opening
caller) also calls `decide_stop` after each `finalize_close`.

- [ ] **Step 5: GREEN.** Run `test_s1_a3_stop.py` and all A3 files into `a3/t11_green.txt`.
- [ ] **Step 6: Full suite, old->new.** Expected intended changes:
  - **A2.1 -> F2:** stop.json is persisted only after a TRIAL-STOP row; its fields follow OQ-8 (`decided_utc` and
    `decided_by` are gone; `determined_utc`, `rule`, `triggering_slot`, `terminal_seq`, `terminal_line_sha256` and
    `lots` are added). This affects `test_s1_t12_a2.py`, `test_s1_seal.py` stop tests, `test_s1_task11.py` and
    `test_s1_t12_fix3.py` (I-1 pending).
  - **Legacy "persisted by the first command that sees an ended trial" (attest_stop/final plan/final snapshot
    calling current_stop) -> F2.2:** only `decide_stop` persists.
  - **B1.5 preserved:** a pending slot blocks the stop.

  Save `a3/t11_full.txt`, `a3/t11_old_new.md` and `a3/t11_hashes.txt`.
- [ ] **Step 7: Controller review and commit.** Message: `S1 A3 Task 11: F2 stop record, TRIAL-STOP, stop.json gap
  recovery, stop_attest and final_plan stages`, listing map rows 55, 56, 62, 64–69, 106, 107, 131, 184, 185, 187,
  189–192, 262 (decide_stop part) and 300–305, with the Co-Authored-By line. Push and assert the HEAD SHA. This step
  waits for BLK-3 as well as BLK-1.

---

### Task 12: Final acquisition stage (F1 graph step 4–5, F4.6/F4.9 final rows, OQ-22; C-a, C-b)

**Files:**
- Modify: `research/s1/s1_collect.py`:
  - add `final_policy(final_plan, prereg, cutoff)`;
  - `do_final` (lines 458–510) runs as stage `final`, under the ACQUIRE-ACK checks (OQ-22);
  - `_reserve`, `_abort`, `_run_attempt` and `_page_hashes` are removed (no remaining caller);
  - `_write_once` stays for `write_plan`.
- Modify: `research/s1/s1_stage.py`: `ENFORCED |= {"final"}`.
- Modify: `research/s1/s1_tests/conftest.py`. The `s1_state` final branch stages `final/*` through `s1_stage.run`
  with a fixture work: the same bytes as before, no pages, provenance `[]`, `attempt.json` with `trial_id`/
  `intent_at`. It is issued after an `s1_ack(…, "S1-ACQUIRE-ACK", …)` placed at or after `_earliest_acquire`.
- Create: `research/s1/s1_tests/test_s1_a3_final.py`

**Interfaces:**
- Produces (`s1_collect`): `final_policy(fplan: dict, prereg: dict, cutoff: str) -> dict`;
  `do_final(root, ack_id, client, keys, *, mailbox=None) -> dict`.

- [ ] **Step 1: Interface stub.** `final_policy` returns `{"families": []}`; `do_final` keeps the c9b4322 body behind
  the gate.

- [ ] **Step 2: Write the failing tests.** `research/s1/s1_tests/test_s1_a3_final.py`:

```python
"""Addendum 3 rev 5 F1 (no provider call before stop_attest and the ACQUIRE-ACK; the ACK no earlier than the lag),
F4.6/F4.9 final rows (raw/SIP bars, CA window, CA full history; empty families), consistency before valuation, C-a,
C-b, F8.5. Behavioural RED against the Task 12 stub (s1_evidence/a3/t12_red.txt). Injected MockTransport clients;
synthetic stopped trials; spies (requests and valuation)."""
import json
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import s1_collect as k
import s1_common as c
import s1_journal as j
import s1_run as r
import s1_stage as sg
import s1_trial as t
from conftest import Spies, _Clock, s1_ack, s1_state

START = "2026-10-26T13:30:00+00:00"
KEYS = ("KEYID-dummy-123", "SECRET-dummy-456")


def mb(root):
    return Path(root) / "mailbox.sqlite3"


def jrows(root):
    tr = t.open_trial(mb(root))
    return j.read_trial(tr.trial_id, tr.genesis, mb(root))


class Provider:
    def __init__(self, bars_pages=1, empty=False, fail_url=None):
        self.bars_pages, self.fail_url, self.sent = bars_pages, fail_url, []

    def __call__(self, req):
        self.sent.append(req)
        url = str(req.url).split("?")[0]
        if url == self.fail_url:
            return httpx.Response(500)
        if url == k.BARS_URL:
            n = sum(1 for x in self.sent if str(x.url).split("?")[0] == k.BARS_URL) - 1
            tok = None if n + 1 >= self.bars_pages else f"b{n}"
            return httpx.Response(200, json={"bars": {}, "next_page_token": tok})
        return httpx.Response(200, json={"corporate_actions": {}, "next_page_token": None})


def ready(tmp_path, **kw):
    """Stopped, attested, final plan written; ACQUIRE-ACK at the lag (OQ-22). Returns (state, acquire instant)."""
    st_ = s1_state(tmp_path, START, score_ready=True, final=False, **kw)
    with _Clock(st_["stop_attested_at"] + timedelta(hours=1)):
        k.write_final_plan(tmp_path)
    fp = json.loads((tmp_path / "s1_out" / "final_plan.json").read_text(encoding="utf-8"))
    pr = json.loads((tmp_path / "s1_out" / "prereg.json").read_text(encoding="utf-8"))
    at = k._earliest_acquire(pr["calendar"], fp["stop_date"])
    s1_ack(tmp_path, "acq-ack", "S1-ACQUIRE-ACK", at + timedelta(minutes=1))
    return st_, at + timedelta(minutes=2)


def final(tmp_path, monkeypatch, prov, at):
    sp = Spies(monkeypatch)
    with _Clock(at):
        m = k.do_final(tmp_path, "acq-ack", sp.client(prov), KEYS)
    return m, sp


def commitment(root):
    tr = t.open_trial(mb(root))
    return json.loads((sg.staging_dir(root, tr.trial_id, "final") / "prepared.json").read_bytes())


def test_final_policy_is_exactly_the_f49_final_rows():
    fp = {"bar_symbols": ["A", "B"], "ca_symbols_window": ["A"], "ca_symbols_full_history": ["B"],
          "full_history_start": "2026-09-01", "stop_date": "2026-10-28"}
    pr = {"start": "2026-10-26T13:30:00+00:00"}
    fixed = {"region": "us", "data_quality": "all", "sort": "asc", "limit": 1000}
    assert k.final_policy(fp, pr, "2026-11-02") == {
        "redirects": False, "max_pages": 200, "cutoff": "2026-11-02", "families": [
            {"name": "bars", "url": "https://data.alpaca.markets/v2/stocks/bars", "scope": "final", "batches": None,
             "base_params": {"symbols": "A,B", "timeframe": "1Day", "start": "2026-10-26T04:00:00Z",
                             "end": "2026-10-29T03:59:59.999999Z", "adjustment": "raw", "feed": "sip",
                             "limit": 10000},
             "paged": True, "page_template": "final/pages/bars_page{n:03d}.json"},
            {"name": "corporate_actions", "url": "https://data.alpaca.markets/v1/corporate-actions", "scope": "window",
             "batches": [["A"]], "base_params": [dict(fixed, symbols="A", start="2026-10-26", end="2026-11-02")],
             "paged": True, "page_template": "final/pages/ca_{i:03d}_page{n:03d}.json"},
            {"name": "corporate_actions", "url": "https://data.alpaca.markets/v1/corporate-actions",
             "scope": "full_history", "batches": [["B"]],
             "base_params": [dict(fixed, symbols="B", start="2026-09-01", end="2026-11-02")],
             "paged": True, "page_template": "final/pages_full/ca_{i:03d}_page{n:03d}.json"}]}


def test_normal_final_commits_every_member(tmp_path, monkeypatch):
    st_, at = ready(tmp_path)
    m, sp = final(tmp_path, monkeypatch, Provider(bars_pages=2), at)
    cm = commitment(tmp_path)
    assert set(sg.FIXED_TREE["final"]) <= set(cm["members"])
    assert {p["scope"] for p in cm["provenance"]} >= {"final", "window"} and sp.n["request"] == len(cm["provenance"])


def test_final_members_are_the_fixed_names_plus_one_page_per_request(tmp_path, monkeypatch):
    st_, at = ready(tmp_path)
    final(tmp_path, monkeypatch, Provider(bars_pages=3), at)
    cm = commitment(tmp_path)
    pages = [p["page_relpath"] for p in cm["provenance"]]
    assert len(pages) == len(set(pages)) and set(cm["members"]) == set(sg.FIXED_TREE["final"]) | set(pages)


def test_final_manifest_projection_equals_the_members(tmp_path, monkeypatch):
    st_, at = ready(tmp_path)
    m, _ = final(tmp_path, monkeypatch, Provider(), at)
    cm = commitment(tmp_path)
    assert sg.manifest_projection("final", m) == {r_: h for r_, h in cm["members"].items()
                                                  if r_ != "final/manifest.json"}


def test_final_envelope_inputs_and_members(tmp_path, monkeypatch):
    st_, at = ready(tmp_path)
    final(tmp_path, monkeypatch, Provider(), at)
    tr = t.open_trial(mb(tmp_path))
    e = json.loads((sg.staging_dir(tmp_path, tr.trial_id, "final") / "intent.json").read_bytes())
    assert set(e["inputs"]) == {"final_plan.json", "prereg.json", "attest_stop.json"}
    assert e["acks"] == {"S1-ACQUIRE-ACK": tr.acks["S1-ACQUIRE-ACK"].sha}


@pytest.mark.parametrize("case", ["ok", "before-attest", "before-lag", "wrong-stop-line", "wrong-prev"])
def test_acquire_ack_binds_prev_stop_line_and_is_not_before_the_lag(tmp_path, monkeypatch, case):
    st_ = s1_state(tmp_path, START, score_ready=True, final=False)
    with _Clock(st_["stop_attested_at"] + timedelta(hours=1)):
        k.write_final_plan(tmp_path)
    fp = json.loads((tmp_path / "s1_out" / "final_plan.json").read_text(encoding="utf-8"))
    pr = json.loads((tmp_path / "s1_out" / "prereg.json").read_text(encoding="utf-8"))
    lag = k._earliest_acquire(pr["calendar"], fp["stop_date"])
    att = c.aware(json.loads((tmp_path / "s1_out" / "attest_stop.json").read_text(encoding="utf-8"))["recorded_utc"])
    when = {"ok": lag + timedelta(minutes=1), "before-attest": att - timedelta(seconds=1),
            "before-lag": lag - timedelta(minutes=1)}.get(case, lag + timedelta(minutes=1))
    over = {"wrong-stop-line": {"stop_line_sha256": "0" * 64},
            "wrong-prev": {"prev": t.open_trial(mb(tmp_path)).audit.mailbox_id}}.get(case, {})
    s1_ack(tmp_path, "acq-ack", "S1-ACQUIRE-ACK", when, **over)
    prov = Provider()
    if case == "ok":
        final(tmp_path, monkeypatch, prov, lag + timedelta(minutes=2))
        assert [x.kind for x in j.subject_rows(jrows(tmp_path), "stage/final")][-1] == "STAGE-CREATED"
        return
    with pytest.raises(SystemExit):
        final(tmp_path, monkeypatch, prov, lag + timedelta(minutes=2))
    assert prov.sent == [] and j.subject_rows(jrows(tmp_path), "stage/final") == []


def test_no_provider_request_before_stop_attest_and_acquire_ack(tmp_path, monkeypatch):
    st_ = s1_state(tmp_path, START, score_ready=True, stop_attest=False, final=False)
    prov = Provider()
    with pytest.raises(SystemExit):
        final(tmp_path, monkeypatch, prov, st_["now"])
    assert prov.sent == []


@pytest.mark.parametrize("empty", ["window", "full_history", "both"])
def test_empty_ca_family_sends_no_request_and_final_completes(tmp_path, monkeypatch, empty):
    """A3-R3C-1 (retrospective): ca_symbols_window is the cohort (empty: no post-START BUY - a TIMEOUT stop on a
    day-0 seal); ca_symbols_full_history is the carry-in/bridge symbols (empty: no carry-in)."""
    kw = {}
    if empty in ("window", "both"):
        kw.update(lots=[], seal_days=[0])
    if empty in ("full_history", "both"):
        kw.update(carry_in=())
    st_, at = ready(tmp_path, **kw)
    prov = Provider()
    m, _ = final(tmp_path, monkeypatch, prov, at)
    scopes = [p["scope"] for p in commitment(tmp_path)["provenance"]]
    assert m["outcome"] == "COMPLETE"
    assert ("window" in scopes) == (empty not in ("window", "both"))
    assert ("full_history" in scopes) == (empty not in ("full_history", "both"))


def test_both_ca_families_are_requested_and_reconciled(tmp_path, monkeypatch):
    st_, at = ready(tmp_path)
    m, _ = final(tmp_path, monkeypatch, Provider(), at)
    scopes = {p["scope"] for p in commitment(tmp_path)["provenance"]}
    assert {"window", "full_history"} <= scopes and m["coverage"]["ca_conflicts"] == 0


def test_final_request_order_is_the_collector_order(tmp_path, monkeypatch):
    st_, at = ready(tmp_path)
    prov = Provider()
    final(tmp_path, monkeypatch, prov, at)
    fams = [p["scope"] for p in commitment(tmp_path)["provenance"]]
    assert fams == sorted(fams, key=["final", "window", "full_history"].index)


def test_cutoff_is_the_intent_new_york_date_across_midnight(tmp_path, monkeypatch):
    st_, at = ready(tmp_path)
    pre = datetime.combine(at.astimezone(c.NY).date(), time(23, 59, 59, 999999), tzinfo=c.NY).astimezone(timezone.utc)
    post = pre + timedelta(microseconds=2)
    now = [pre - timedelta(seconds=5)]
    real = j.append

    def at_intent(trial_id, gen, req, ctx_fn, **kw):
        if req.kind == "STAGE-INTENT" and req.subject == "stage/final":
            kw["clock"] = lambda: pre
            res = real(trial_id, gen, req, ctx_fn, **kw)
            now[0] = post                                         # reservation and requests after New York midnight
            return res
        return real(trial_id, gen, req, ctx_fn, **kw)
    monkeypatch.setattr(j, "append", at_intent)
    monkeypatch.setattr(c, "now_utc", lambda: now[0])
    prov, sp = Provider(), Spies(monkeypatch)
    m = k.do_final(tmp_path, "acq-ack", sp.client(prov), KEYS)
    want = pre.astimezone(c.NY).date().isoformat()
    reserved = json.loads((tmp_path / "s1_out" / "final" / "attempt.json").read_bytes())["reserved_utc"]
    assert m["publication_cutoff"] == want != c.aware(reserved).astimezone(c.NY).date().isoformat()
    assert all(r_.url.params.get("end") == want for r_ in prov.sent if "corporate-actions" in str(r_.url))


@pytest.mark.parametrize("victim", ["final/bars.json", "final/bar_problems.json", "final/corporate_actions.json",
                                    "final/ca_problems.json", "final/manifest.json", "final/pages/bars_page000.json",
                                    "final/pages/ca_000_page000.json", "final/pages_full/ca_000_page000.json"])
@pytest.mark.parametrize("damage", ["changed", "deleted"])
def test_damaged_final_member_is_invalid_before_valuation_with_zero_valuation_calls(tmp_path, monkeypatch, victim,
                                                                                    damage):
    st_, at = ready(tmp_path)
    final(tmp_path, monkeypatch, Provider(), at)
    s1_ack(tmp_path, "score-ack", "S1-SCORE-ACK", at + timedelta(days=1))
    p = tmp_path / "s1_out" / victim
    if damage == "deleted":
        p.unlink()
    else:
        p.write_bytes(p.read_bytes() + b" ")
    sp = Spies(monkeypatch)
    with _Clock(at + timedelta(days=2)), pytest.raises(SystemExit, match=r"INVALID \(stage-replaced\)"):
        r.score(tmp_path, "score-ack")
    assert sp.n["valuation"] == 0 and not (tmp_path / "s1_out" / "score").exists()


@pytest.mark.parametrize("case", ["extra-page", "missing-page", "extra-full-page"])
def test_final_extra_page_or_orphan_provenance_is_invalid(tmp_path, monkeypatch, case):
    st_, at = ready(tmp_path)
    final(tmp_path, monkeypatch, Provider(), at)
    out = tmp_path / "s1_out"
    if case == "extra-page":
        (out / "final" / "pages" / "bars_page009.json").write_text("{}", encoding="utf-8")
    elif case == "extra-full-page":
        (out / "final" / "pages_full" / "ca_009_page000.json").write_text("{}", encoding="utf-8")
    else:
        (out / "final" / "pages" / "bars_page000.json").unlink()
    with pytest.raises(SystemExit, match=r"INVALID \(stage-replaced\)"):
        t.gate(tmp_path, "orphan")


def test_final_provider_anomaly_after_the_stop_is_invalid_with_no_retry(tmp_path, monkeypatch):
    st_, at = ready(tmp_path)
    with pytest.raises(SystemExit, match=r"INVALID \(provider-structural\)"):
        final(tmp_path, monkeypatch, Provider(fail_url=k.CA_URL), at)
    prov = Provider()
    with pytest.raises(SystemExit, match="INVALID"):
        final(tmp_path, monkeypatch, prov, at + timedelta(minutes=1))
    assert prov.sent == []
```


- [ ] **Step 3: Behavioural RED.** Run into `a3/t12_red.txt`.
  - Expected: no stage rows; empty `final_policy`; the cutoff is the reservation date (`B-old`); damaged members
    reach the score (legacy ABORTED-INVALID report, not the gate's stage-replaced refusal); no OQ-22 refusal on
    `before-lag`.
  - `test_empty_ca_family…`, `test_both_ca_families…` and the request-order test pass the c9b4322 path. Label them
    `retro`.

- [ ] **Step 4: Implement.** In `s1_collect.py`:

```python
def final_policy(fplan: dict, prereg: dict, cutoff: str) -> dict:
    """F4.6/F4.9: the final acquisition's policy - raw/SIP daily bars (one paged family), then corporate actions for
    the window scope and the full-history scope (each per 50-symbol batch); every CA end = the INTENT's cutoff."""
    start_day = _ny_date(c.aware(prereg["start"]))
    bars_start = _ny_instant(start_day, "00:00")
    bars_end = _ny_instant((date.fromisoformat(fplan["stop_date"]) + timedelta(days=1)).isoformat(),
                           "00:00") - timedelta(microseconds=1)

    def ca(scope, syms, start, template):
        batches = [list(syms[i:i + CA_BATCH]) for i in range(0, len(syms), CA_BATCH)]
        return {"name": CA_FAMILY, "url": CA_URL, "scope": scope, "batches": batches,
                "base_params": [dict(CA_FIXED, symbols=",".join(b), start=start, end=cutoff) for b in batches],
                "paged": True, "page_template": template}
    return {"redirects": False, "max_pages": MAX_PAGES, "cutoff": cutoff, "families": [
        {"name": "bars", "url": BARS_URL, "scope": "final", "batches": None,
         "base_params": {"symbols": ",".join(fplan["bar_symbols"]), "timeframe": "1Day", "start": _utc_z(bars_start),
                         "end": _utc_z(bars_end, micro=True), "adjustment": "raw", "feed": "sip", "limit": 10000},
         "paged": True, "page_template": "final/pages/bars_page{n:03d}.json"},
        ca("window", fplan["ca_symbols_window"], start_day, "final/pages/ca_{i:03d}_page{n:03d}.json"),
        ca("full_history", fplan["ca_symbols_full_history"], fplan["full_history_start"],
           "final/pages_full/ca_{i:03d}_page{n:03d}.json")]}
```

`do_final` keeps its legacy prechecks:
- the plan equals the derived record, as amended in Task 11;
- the stop attestation binds;
- the ACK is strictly after the attestation;
- `now >= earliest`.

It adds OQ-22: `if c.aware(ack["created_utc"]) < earliest: raise SystemExit("final refused: the ACQUIRE-ACK precedes the acquisition lag (F1 step 4)")`.

Then:

```python
    a = s1_trial.verify_ack(gv.trial, gv.rows, "S1-ACQUIRE-ACK", ack_id,
                            dict(s1_trial.artifact_fields("S1-ACQUIRE-ACK", out), trial_id=gv.trial.trial_id,
                                 bundle_sha256=c.bundle_sha256()))
    ack = s1_trial.ack_record(a)
    ...

    def work(sw):
        auth, cutoff = _Authorizer(sw.policy), sw.policy["cutoff"]
        sw.put_json("final/attempt.json", {"reserved_utc": c.now_utc().isoformat(), "ack": ack,
                                           "trial_id": sw.trial_id, "intent_at": sw.intent_at})
        try:
            bar_pages = _paged(client, auth, "bars", "final", BARS_URL, sw.policy["families"][0]["base_params"],
                               _headers(keys), sw, _validate_bars_page)
            ca_win, p1 = _corporate_actions(client, auth, keys, "window", plan["ca_symbols_window"], start_day,
                                            cutoff, sw)
            ca_full, p2 = _corporate_actions(client, auth, keys, "full_history", plan["ca_symbols_full_history"],
                                             plan["full_history_start"], cutoff, sw)
            if not auth.finished():
                raise Structural("final: the policy's families were not all requested")
        except Exception as e:                                             # noqa: BLE001
            _provider_abort(auth, e)
        bars, bar_problems = _parse_bars(plan["bar_symbols"], bar_pages, sessions)
        actions, conflicts = reconcile_actions(ca_win, ca_full)
        for name, obj in (("bars.json", bars), ("bar_problems.json", bar_problems),
                          ("corporate_actions.json", actions), ("ca_problems.json", p1 + p2 + conflicts)):
            sw.put_json(f"final/{name}", obj)
        files, pages = _attempt_files(sw, "final")
        per_symbol = {s: {"present": len(bars[s]), "missing": len(sessions) - len(bars[s])} for s in bars}
        sw.put_json("final/manifest.json", {
            "publication_cutoff": cutoff, "prereg_sha256": c.sha256_file(prp),
            "earliest_acquire_utc": earliest.isoformat(), "final_plan_sha256": c.sha256_file(fp),
            "attest_stop_sha256": c.sha256_file(out / "attest_stop.json"), "bundle_sha256": c.bundle_sha256(),
            "stop_sha256": c.sha256_file(out / "stop.json"),
            "bars_window": [sw.policy["families"][0]["base_params"]["start"],
                            sw.policy["families"][0]["base_params"]["end"]],
            "outcome": "COMPLETE", "ack": ack, "files": files, "pages": pages,
            "coverage": {"bars": per_symbol, "bar_problems": len(bar_problems), "ca_records": len(actions),
                         "ca_problems": len(p1) + len(p2) + len(conflicts), "ca_conflicts": len(conflicts)},
            "limits": LIMITS})
        return auth.provenance
    s1_stage.run(gv, "final", inputs={"final_plan.json": c.sha256_file(fp), "prereg.json": c.sha256_file(prp),
                                      "attest_stop.json": c.sha256_file(out / "attest_stop.json")},
                 acks={"S1-ACQUIRE-ACK": a.sha}, policy_fn=lambda at: final_policy(plan, pr, _ny_date(at)),
                 work=work, mailbox=mailbox)
    return json.loads((out / "final" / "manifest.json").read_text(encoding="utf-8"))
```

Add `"final"` to `ENFORCED`.

- [ ] **Step 5: GREEN.** Run `test_s1_a3_final.py` and all A3 files into `a3/t12_green.txt`. Save
  `a3/t12_cutoff_midnight.txt` as an isolated run (C-e).
- [ ] **Step 6: Full suite, old->new.** Expected intended changes:
  - `test_s1_collect.py` final tests: "an attempt already exists" becomes "already CREATED", and the ACK placement
    must respect the lag (OQ-22).
  - `test_s1_connected.py` final acquisition: the hand-formatted token becomes `s1_ack`.
  - Legacy ABORTED manifest assertions become: ABORTED.json in staging, plus INVALID (provider-structural).

  Save `a3/t12_full.txt`, `a3/t12_old_new.md` and `a3/t12_hashes.txt`.
- [ ] **Step 7: Controller review and commit.** Message: `S1 A3 Task 12: final acquisition stage under the
  ACQUIRE-ACK and the F4.9 final families`, listing map rows 59, 61, 92, 94, 108, 112–117, 119, 165, 183, 213 and
  215–217, with the Co-Authored-By line. Push and assert the HEAD SHA.

---

### Task 13: Score stage, CLOSE evidence, connected lot-count and six-month runs (F1 graph steps 6–7, F4.8 score row, F4.9 score members and score abort; C-a score binding, C-e; OQ-16, OQ-28, OQ-29)

**Files:**
- Modify: `research/s1/s1_run.py:score` (lines 614–634). It runs as stage `score`; `_pre_reserve_gate` is kept;
  `k._reserve` is removed.
- Modify: `research/s1/s1_seal.py`: add `sampled_history(rows, stop_row, seals) -> dict` (OQ-29).
- Modify: `research/s1/s1_stage.py`: `ENFORCED |= {"score"}`.
- Modify: `research/s1/s1_checkpoint.py:run_final_snapshot` (line 922) and `_trial_state` (line 886), for the
  OQ-16 ruling:
  - its first statement is `gv = s1_trial.gate(root, "final snapshot", mailbox=mailbox, now=now)`;
  - `_trial_state` is replaced by `if gv.state != "STOPPED": raise SystemExit("final snapshot refused: the trial is
    not STOPPED (OQ-16)")`;
  - it never appends a slot row, and its report is never sampled history.

  Test: `test_s1_a3_score.py::test_final_snapshot_only_in_stopped` (part of row 314).
- Modify: `research/s1/s1_tests/conftest.py`. The `s1_state` SCORE-ACK is issued through `s1_ack` after the final
  stage.
- Create: `research/s1/s1_tests/test_s1_a3_score.py`

**Interfaces:**
- Produces: `s1_seal.sampled_history(rows, stop_row, seals: dict) -> dict` (the `rows` and `seals` keys of OQ-29);
  `s1_run.score(root, ack_id, *, mailbox=None) -> dict`.

- [ ] **Step 1: Interface stub.** `score` keeps its c9b4322 body behind the gate (`k._reserve`, then `s1.json` straight
  into s1_out; an exception records an ABORTED report there); `sampled_history` returns `{}`.

- [ ] **Step 2: Write the failing tests.** `research/s1/s1_tests/test_s1_a3_score.py`:

```python
"""Addendum 3 rev 5 F1 (finalization graph to the score; INVALID never numeric; post-stop prices usable), F4.8 score
row, F4.9 score members and abort, C-a (score bound by PREPARED, no collector manifest), C-e (positive and abort paths
isolated), F7.4/F7.5. Behavioural RED against the Task 13 stub (s1_evidence/a3/t13_red.txt). Synthetic connected
lifecycles through the real commands; spies."""
import json
from datetime import timedelta
from pathlib import Path

import pytest
import s1_common as c
import s1_journal as j
import s1_run as r
import s1_seal as z
import s1_stage as sg
import s1_trial as t
from conftest import Spies, _Clock, s1_ack, s1_jappend, s1_state

START = "2026-10-26T13:30:00+00:00"


def mb(root):
    return Path(root) / "mailbox.sqlite3"


def jrows(root):
    tr = t.open_trial(mb(root))
    return j.read_trial(tr.trial_id, tr.genesis, mb(root))


def scored(tmp_path, **kw):
    st_ = s1_state(tmp_path, START, score_ready=True, **kw)
    with _Clock(st_["now"]):
        rep = r.score(tmp_path, "score-ack")
    return st_, rep


def test_lot_count_stop_reaches_a_numeric_score_with_no_invalid_row(tmp_path):
    st_, rep = scored(tmp_path)
    rows = jrows(tmp_path)
    assert json.loads((tmp_path / "s1_out" / "stop.json").read_text(encoding="utf-8"))["rule"] == "lots"
    assert rep["verdict"] in ("SHADOW PASS", "FAIL") and all(x.kind != "TRIAL-INVALID" for x in rows)
    stages = [x.subject for x in rows if x.kind == "STAGE-CREATED"]
    assert stages == ["stage/audit", "stage/opening", "stage/start_attest", "stage/prereg", "stage/stop_attest",
                      "stage/final_plan", "stage/final", "stage/score"]
    tr = t.open_trial(mb(tmp_path))
    assert not t.check_journal(tr, rows) and set(tr.acks) == {"S1-OPENING-ACK", "S1-RUN-ACK", "S1-PREREG-ACK",
                                                              "S1-ACQUIRE-ACK", "S1-SCORE-ACK"}


def test_six_month_stop_reaches_a_numeric_score_with_no_invalid_row(tmp_path):
    lots = [{"symbol": f"S{i % 5}", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (1, 80.0)} for i in range(40)]
    st_, rep = scored(tmp_path, lots=lots)
    assert json.loads((tmp_path / "s1_out" / "stop.json").read_text(encoding="utf-8"))["rule"] == "timeout"
    assert rep["verdict"] in ("SHADOW PASS", "FAIL", "INSUFFICIENT", "INCONCLUSIVE")
    assert rep["verdict"] != "ABORTED-INVALID" and all(x.kind != "TRIAL-INVALID" for x in jrows(tmp_path))


def test_score_positive_path_isolated(tmp_path):
    """C-e positive: evidence s1_evidence/a3/t13_score_positive.txt (run alone)."""
    st_, rep = scored(tmp_path)
    tr = t.open_trial(mb(tmp_path))
    cm = json.loads((sg.staging_dir(tmp_path, tr.trial_id, "score") / "prepared.json").read_bytes())
    assert set(cm["members"]) == {"score/attempt.json", "score/s1.json"} and cm["provenance"] == []
    assert cm["members"]["score/s1.json"] == c.sha256_file(tmp_path / "s1_out" / "score" / "s1.json")
    assert not (tmp_path / "s1_out" / "score" / "manifest.json").exists()             # C-a: no collector manifest


def test_score_computation_error_is_invalid_score_aborted_with_no_numeric_score(tmp_path, monkeypatch):
    """C-e failure: evidence s1_evidence/a3/t13_score_aborted.txt (run alone)."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    monkeypatch.setattr(r, "_score", lambda out, mailbox=None: (_ for _ in ()).throw(RuntimeError("boom")))
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=r"INVALID \(score-aborted\)"):
        r.score(tmp_path, "score-ack")
    tr = t.open_trial(mb(tmp_path))
    staging = sg.staging_dir(tmp_path, tr.trial_id, "score")
    aborted = json.loads((staging / "score" / "s1.json").read_text(encoding="utf-8"))
    assert aborted["verdict"] == "ABORTED-INVALID" and not (staging / "prepared.json").exists()
    assert not (tmp_path / "s1_out" / "score").exists()
    assert jrows(tmp_path)[-1].subject == "reason/score-aborted"


def test_invalid_never_reaches_a_numeric_score(tmp_path, monkeypatch):
    st_ = s1_state(tmp_path, START, score_ready=True)
    s1_jappend(tmp_path, "TRIAL-INVALID", "reason/registration-artifact", at=st_["now"] - timedelta(hours=1),
               detail=j.detail_of({"synthetic": "violation"}))
    sp = Spies(monkeypatch)
    with _Clock(st_["now"]), pytest.raises(SystemExit, match="INVALID"):
        r.score(tmp_path, "score-ack")
    assert sp.n["valuation"] == 0 and not (tmp_path / "s1_out" / "score").exists()


def test_score_envelope_inputs_and_members(tmp_path):
    st_, rep = scored(tmp_path)
    tr = t.open_trial(mb(tmp_path))
    e = json.loads((sg.staging_dir(tmp_path, tr.trial_id, "score") / "intent.json").read_bytes())
    assert set(e["inputs"]) == {"final/manifest.json", "attest_stop.json", "sampled_history"}
    assert e["acks"] == {"S1-SCORE-ACK": tr.acks["S1-SCORE-ACK"].sha}


@pytest.mark.parametrize("case", ["ok", "wrong-final", "wrong-prev", "wrong-stop-line", "head-forked"])
def test_score_ack_fields_are_verified(tmp_path, case):
    st_ = s1_state(tmp_path, START, score_ready=True, score_ack=False)
    over = {"wrong-final": {"final_manifest_sha256": "0" * 64},
            "wrong-prev": {"prev": t.open_trial(mb(tmp_path)).audit.mailbox_id},
            "wrong-stop-line": {"stop_line_sha256": "0" * 64}, "head-forked": {"journal_head_sha256": "f" * 64}
            }.get(case, {})
    s1_ack(tmp_path, "score-ack", "S1-SCORE-ACK", st_["now"] - timedelta(hours=1), **over)
    with _Clock(st_["now"]):
        if case == "ok":
            assert r.score(tmp_path, "score-ack")["verdict"]
            return
        with pytest.raises(SystemExit):
            r.score(tmp_path, "score-ack")
    assert j.subject_rows(jrows(tmp_path), "stage/score") == []


def test_score_member_changed_is_invalid(tmp_path, monkeypatch):
    st_, rep = scored(tmp_path)
    p = tmp_path / "s1_out" / "score" / "s1.json"
    p.write_bytes(p.read_bytes() + b" ")
    sp = Spies(monkeypatch)
    with pytest.raises(SystemExit, match=r"INVALID \(stage-replaced\)"):
        t.gate(tmp_path, "after the score")
    sp.assert_zero()


@pytest.mark.parametrize("victim", ["receipt", "snapshot-report"])
def test_damaged_receipt_or_final_snapshot_is_invalid_before_scoring(tmp_path, monkeypatch, victim):   # row 281
    st_ = s1_state(tmp_path, START, score_ready=True)
    p = tmp_path / "s1_out" / ("opening_receipt.json" if victim == "receipt" else "final_snapshot/report.json")
    p.write_bytes(p.read_bytes() + b" ")                                  # the TEST damages its tmp file
    sp = Spies(monkeypatch)
    with _Clock(st_["now"]), pytest.raises(SystemExit, match="INVALID"):
        r.score(tmp_path, "score-ack")
    sp.assert_zero()
    assert not (tmp_path / "s1_out" / "score").exists()


def test_damaged_capture_backup_is_invalid_before_scoring(tmp_path, monkeypatch):     # row 282 (E5.6)
    st_ = s1_state(tmp_path, START, score_ready=True)
    backup = sorted((tmp_path / "s1_out" / "captures").glob("*/*/backup.sqlite3"))[-1]
    with open(backup, "ab") as f:
        f.write(b"\0")
    sp = Spies(monkeypatch)
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=r"INVALID \(registration-artifact\)"):
        r.score(tmp_path, "score-ack")
    sp.assert_zero()


def test_score_integrity_violation_persists_trial_invalid(tmp_path, monkeypatch):     # row 306 (OQ-28)
    st_ = s1_state(tmp_path, START, score_ready=True)
    monkeypatch.setattr(r, "_score", lambda out, mailbox=None: {"trial_id": "x", "outcome": "ABORTED",
                                                                "verdict": "ABORTED-INVALID",
                                                                "reasons": ["fence violation in seal X"]})
    with _Clock(st_["now"]), pytest.raises(SystemExit, match="INVALID"):
        r.score(tmp_path, "score-ack")
    inv = [x for x in jrows(tmp_path) if x.kind == "TRIAL-INVALID"]
    assert len(inv) == 1 and inv[0].subject == "reason/registration-artifact"
    staging = sg.staging_dir(tmp_path, t.open_trial(mb(tmp_path)).trial_id, "score")
    assert (staging / "score" / "s1.json").exists() and not (staging / "prepared.json").exists()
    assert not (tmp_path / "s1_out" / "score").exists()


@pytest.mark.parametrize("verdict", ["INSUFFICIENT", "INCONCLUSIVE"])
def test_non_integrity_dispositions_stay_valid(tmp_path, monkeypatch, verdict):        # row 307 (ctrl)
    st_ = s1_state(tmp_path, START, score_ready=True)
    real = r._score
    monkeypatch.setattr(r, "_score", lambda out, mailbox=None: dict(real(out, mailbox), verdict=verdict))
    with _Clock(st_["now"]):
        rep = r.score(tmp_path, "score-ack")
    assert rep["verdict"] == verdict and all(x.kind != "TRIAL-INVALID" for x in jrows(tmp_path))


@pytest.mark.parametrize("case", ["missing", "changed"])
def test_final_snapshot_missing_or_changed_is_invalid_not_a_fallback(tmp_path, monkeypatch, case):   # row 314
    st_ = s1_state(tmp_path, START, score_ready=True)
    p = tmp_path / "s1_out" / "final_snapshot" / "report.json"
    if case == "missing":
        p.unlink()
    else:
        p.write_bytes(p.read_bytes() + b" ")
    with _Clock(st_["now"]), pytest.raises(SystemExit, match="INVALID"):
        r.score(tmp_path, "score-ack")
    assert any(x.kind == "TRIAL-INVALID" for x in jrows(tmp_path))
    assert not (tmp_path / "s1_out" / "score" / "s1.json").exists()


def test_final_snapshot_only_in_stopped(tmp_path, monkeypatch):                       # row 314 (OQ-16)
    import s1_checkpoint as ck
    st_ = s1_state(tmp_path, START)                                     # ACTIVE: registered, no STOP
    sp = Spies(monkeypatch)
    n = len(jrows(tmp_path))
    with _Clock(st_["prereg_at"]), pytest.raises(SystemExit, match="STOPPED"):
        ck.run_final_snapshot(tmp_path, st_["ledger"].path, now=lambda: st_["prereg_at"],
                              mailbox=tmp_path / "mailbox.sqlite3")
    sp.assert_zero()
    assert len(jrows(tmp_path)) == n and not (tmp_path / "s1_out" / "final_snapshot").exists()


def test_sampled_history_is_canonical_and_fixed_at_the_stop(tmp_path, monkeypatch):   # row 315 (OQ-29)
    st_ = s1_state(tmp_path, START, score_ready=True, final=False)
    out = tmp_path / "s1_out"
    rows0 = jrows(tmp_path)
    stop = j.first(rows0, "TRIAL-STOP")
    pr = c.load_json(out / "prereg.json")
    seals = z.sampled_seals(out, rows0, pr["calendar"], c.aware(pr["start"]), upto_seq=stop.seq)
    before = z.sampled_history(rows0, stop, seals)
    s1_jappend(tmp_path, "SLOT-INTENT", "slot/20261028T214500Z", at=c.aware(START) + timedelta(days=2, hours=8))
    rows1 = jrows(tmp_path)
    after = z.sampled_history(rows1, stop, z.sampled_seals(out, rows1, pr["calendar"], c.aware(pr["start"]),
                                                            upto_seq=stop.seq))
    assert before == after and list(before["seals"]) == sorted(before["seals"])
    assert before["rows"] == [x.sha for x in rows0 if x.seq <= stop.seq]


def test_authorized_post_stop_prices_are_used_for_valuation(tmp_path):
    seen = []
    st_, rep = scored(tmp_path, bar_fn=lambda sym, d: seen.append(d) or {"date": d, "o": 100, "h": 101, "l": 99,
                                                                          "c": 100})
    stop_day = c.aware(json.loads((tmp_path / "s1_out" / "stop.json").read_text(encoding="utf-8"))["stop_close"]
                       ).astimezone(c.NY).date().isoformat()
    assert stop_day in seen and rep["verdict"] in ("SHADOW PASS", "FAIL")
```

`s1_state` needs a `score_ack=True` keyword (default True; False skips the SCORE-ACK post) for
`test_score_ack_fields_are_verified`. Add it in this task's conftest change.

- [ ] **Step 3: Behavioural RED.** Run into `a3/t13_red.txt`.
  - Expected: no score stage rows; the ABORTED report lands in s1_out with no TRIAL-INVALID (the c9b4322 one-attempt
    report); with an INVALID journal the legacy path records ABORTED-INVALID instead of refusing (`B-old`); the
    sampled-history input is absent.
  - Revision 1:
    - rows 281, 282, 306 and 314 fail (the legacy path scores, or records ABORTED-INVALID in s1_out without a
      TRIAL-INVALID);
    - row 307 passes on the legacy path. Label it `ctrl`;
    - row 315 fails (`sampled_history` returns {}).

- [ ] **Step 4: Implement.** In `s1_seal.py`:

```python
def sampled_history(rows, stop_row, seals: dict) -> dict:
    """OQ-29: the score's sampled-history input - every journal row at or before the STOP seq (line sha256 in seq
    order) and the seals derived from QUALIFIED slots committed at or before it ({relpath: sha256})."""
    return {"rows": [x.sha for x in rows if x.seq <= stop_row.seq],
            "seals": {f"seals/{d}.json": c.sha256_bytes(b_) for d, (_, b_) in sorted(seals.items())}}
```

`s1_run.score`:

```python
def score(root, ack_id: str, *, mailbox=None) -> dict:
    """Stage `score` (F1 step 7; F4.8/F4.9): members score/attempt.json and score/s1.json bound directly by PREPARED (no
    collector manifest, C-a). A computation error ends the attempt: the ABORTED s1.json stays in staging, no PREPARED,
    INVALID (score-aborted). An INVALID trial never reaches here (the gate refuses with no work)."""
    import s1_journal as j
    import s1_stage
    import s1_trial
    gv = s1_trial.gate(root, "score", mailbox=mailbox)
    out = _out(root)
    c.verify_bundle_first(out, "score", mailbox=mailbox, gate_refuses=False)
    if not (out / "prereg.json").exists():
        raise SystemExit("no prereg: the trial never started; nothing to score")
    c.verify_bundle_first(out, "score", mailbox=mailbox, need="prereg", gate_refuses=False)
    expected = dict(s1_trial.artifact_fields("S1-SCORE-ACK", out), trial_id=gv.trial.trial_id,
                    bundle_sha256=c.bundle_sha256())
    expected.pop("final_snapshot_sha256")                        # checked below as INVALID, not as a refusal
    a = s1_trial.verify_ack(gv.trial, gv.rows, "S1-SCORE-ACK", ack_id, expected)
    ack = s1_trial.ack_record(a)
    _pre_reserve_gate(out, ack)
    stop_row = j.first(gv.rows, "TRIAL-STOP")
    snap = out / "final_snapshot" / "report.json"                  # OQ-16 ruling: bound evidence, never a fallback
    if (c.sha256_file(snap) if snap.is_file() else None) != a.fields["final_snapshot_sha256"]:
        s1_trial.invalidate(gv.trial, "registration-artifact",
                            {"where": "score", "final_snapshot": "missing or differs from the SCORE-ACK"},
                            root=gv.root, mailbox=mailbox)
        raise SystemExit("score refused: the SCORE-ACK-bound final snapshot is missing or changed: "
                         "INVALID (registration-artifact)")
    pr = _load(out / "prereg.json")
    seals = z.sampled_seals(out, gv.rows, pr["calendar"], c.aware(pr["start"]), upto_seq=stop_row.seq)
    inputs = {"final/manifest.json": c.sha256_file(out / "final" / "manifest.json"),
              "attest_stop.json": c.sha256_file(out / "attest_stop.json"),
              "sampled_history": j.detail_of(z.sampled_history(gv.rows, stop_row, seals))}

    def work(sw):
        sw.put_json("score/attempt.json", {"reserved_utc": c.now_utc().isoformat(), "ack": ack,
                                           "trial_id": sw.trial_id, "intent_at": sw.intent_at})
        try:
            text = _serialise(_score(out, mailbox))
        except (Exception, SystemExit) as e:                       # the one attempt (F4.9 score abort)
            rep = {"trial_id": sw.trial_id, "outcome": "ABORTED", "verdict": "ABORTED-INVALID", "provenance": None,
                   "nomination": False, "reasons": [f"score error: {type(e).__name__}"]}
            sw.put("score/s1.json", c.text_bytes(_serialise(rep)))
            raise s1_stage.StageAbort("score-aborted", {"error_type": type(e).__name__})
        sw.put("score/s1.json", c.text_bytes(text))
        rep = json.loads(text)
        if rep.get("verdict") == "ABORTED-INVALID":               # OQ-28 AMEND: an established integrity violation
            raise s1_stage.StageAbort("registration-artifact",    # the report stays in staging; no PREPARED
                                      {"where": "score", "score_reasons": rep.get("reasons")})
        return []                                                 # INSUFFICIENT/INCONCLUSIVE/NO-VALID-SEAL/BLOCKED:
                                                                  # normal non-numeric committed scores
    s1_stage.run(gv, "score", inputs=inputs, acks={"S1-SCORE-ACK": a.sha}, work=work, mailbox=mailbox)
    return _load(out / "score" / "s1.json")
```

In `_score`, replace `"trial_id": TRIAL_ID` with `_load(out / "plan.json")["trial_id"]`. Remove `_write_text_once` if it
is now unused. Add `"score"` to `ENFORCED`.

- [ ] **Step 5: GREEN.** Run `test_s1_a3_score.py` and all A3 files into `a3/t13_green.txt`. Isolated runs:
  `a3/t13_score_positive.txt` (`::test_score_positive_path_isolated`) and `a3/t13_score_aborted.txt`
  (`::test_score_computation_error…`) (C-e).
- [ ] **Step 6: Full suite, old->new.** Expected intended changes:
  - **A2.3/B3 -> F1/F0.6:** tests expecting an ABORTED-INVALID score report after a legacy abort now get "refused,
    no score" when the journal is INVALID. This affects the `test_s1_run.py` score-abort tests,
    `test_s1_t12_fix2_b3.py::…_at_the_score_…`, `test_s1_task11.py` (m-7 report kinds `aborted`) and
    `test_s1_t12_reporting.py`. List each one.
  - **The one-attempt score:** "score/ already exists" becomes "already CREATED".
  - **OQ-28 AMEND:** tests where `_score` itself returns ABORTED-INVALID from integrity checks now get
    TRIAL-INVALID (registration-artifact), with the report kept in staging and no PREPARED and no `score/` in
    s1_out. Other non-numeric verdicts are committed normally. List each one.
  - **OQ-16:** a missing or changed final-snapshot report at the score is INVALID (registration-artifact), not a
    SCORE-ACK refusal.

  Save `a3/t13_full.txt`, `a3/t13_old_new.md` and `a3/t13_hashes.txt`.
- [ ] **Step 7: Controller review and commit.** Message: `S1 A3 Task 13: score stage, score-aborted INVALID, connected
  lot-count and six-month runs`, listing map rows 60, 63, 109, 118, 181, 182, 185, 191, 215, 218, 281, 282,
  306, 307, 314 and 315, with the Co-Authored-By line. Push and assert the HEAD SHA.

---

### Task 14: Matrix, residual (CH4), the probe record, and the end of the transitional `ENFORCED` (F10 Other matrix, F8.1, F10 probes record)

**Files:**
- Modify: `research/s1/s1_stage.py`. `ENFORCED` is removed; `evaluate` iterates over every stage in `TABLE`.
- Create: `research/s1/s1_tests/test_s1_a3_matrix.py`, `research/s1/s1_tests/test_s1_a3_residual.py`
- Create: `research/s1/s1_evidence/a3/codex_probes_old_new.md`. It has two separate sections: "intended old
  behavioural failures" (each new probe test, the historical JSON observation it reverses, and the spec clause) and
  "fixture/setup incompatibilities" (what failed only because of setup when the new file was first run, and how it
  was fixed). Neither section counts toward the other.
- Create: `research/s1/s1_evidence/a3/t14_matrix_full.txt` (the exhaustive run).

**Interfaces:**
- Consumes: all earlier tasks.
- Produces: no product interface. `s1_stage.ENFORCED` is gone; no test may reference it after this task.

- [ ] **Step 1: Interface stub.** None: this task adds tests over finished code. Its RED is behavioural against a
  deliberate mutant: run the matrix with `s1_stage.evaluate` monkeypatched to a no-op, and save the result to
  `a3/t14_red_mutant.txt`. That shows the matrix detects the missing check. Record the run as "behavioural RED
  (mutant)".

- [ ] **Step 2: Write the tests.** `research/s1/s1_tests/test_s1_a3_matrix.py`:

```python
"""Addendum 3 rev 5 F10 'Other': the damage matrix - every non-empty subset of the nine elements x {bundle same,
changed} x {deleted, changed, unparseable}, at each commitment point. Exhaustive when S1_MATRIX_FULL=1 (evidence
a3/t14_matrix_full.txt); otherwise singletons, pairs, complements and the full set. Each case runs on a copy of the
commitment point's snapshot; the expected outcome comes from `oracle`; every refusal or INVALID has zero callbacks,
captures, provider requests and valuation calls."""
import itertools
import os
import shutil
from datetime import timedelta
from pathlib import Path

import pytest
import s1_checkpoint as ck
import s1_common as c
import s1_journal as j
import s1_run as r
import s1_seal as z
import s1_trial as t
from conftest import Ledger, S1_RECEIPT, Spies, _Clock, s1_ack, s1_opening_checkpoint, s1_plan_audit, s1_state

START = "2026-10-26T13:30:00+00:00"
ELEMENTS = ("plan", "audit tree", "opening record (registry)", "opening record (witnesses)", "attestation",
            "prereg", "seal", "receipt", "stop")
# PLAN-6 / map 255: the 9 commitment points (every CREATED stage, with TRIAL-STOP + stop.json as one) plus the
# OPENING-ACK point = 10. INTENT/PREPARED boundaries are NOT matrix points: the per-stage state-table tests cover
# them (rows 122-129, 180, 228-229), and the matrix claims no more than this list.
POINTS = ("after-audit", "after-opening", "after-opening-ack", "after-start-attest", "after-prereg", "after-stop",
          "after-stop-attest", "after-final-plan", "after-final", "after-score")
EXISTS_FROM = {"plan": 0, "audit tree": 0, "opening record (registry)": 1, "opening record (witnesses)": 1,
               "seal": 1, "receipt": 1, "attestation": 3, "prereg": 4, "stop": 5}
FIRST_FINALIZATION_INTENT = POINTS.index("after-stop-attest")
JOURNAL_MEMBERS = {"seal", "attestation", "prereg"}          # F4 table: a stage artifact with no INTENT is a violation
FULL = os.environ.get("S1_MATRIX_FULL") == "1"


def paths(out, oc):
    """Element -> file(s). 'audit tree' is EVERY file under s1_out/audit/ (map 255 wording; PLAN-6), at least the
    fixed members when the tree does not exist yet."""
    audit = sorted(p for p in (out / "audit").rglob("*") if p.is_file()) or \
        [out / rel for rel in ("audit/calendar.json", "audit/manifest.json")]
    return {"plan": out / "plan.json", "audit tree": audit,
            "opening record (registry)": out / "registry" / "opening.json",
            "opening record (witnesses)": out / "witnesses" / "opening.json",
            "attestation": out / "attest_start.json", "prereg": out / "prereg.json",
            "seal": out / "seals" / f"{oc}.json", "receipt": out / "opening_receipt.json", "stop": out / "stop.json"}


def subsets():
    if FULL:
        return [s for n in range(1, len(ELEMENTS) + 1) for s in itertools.combinations(ELEMENTS, n)]
    small = [s for n in (1, 2) for s in itertools.combinations(ELEMENTS, n)]
    return small + [tuple(e for e in ELEMENTS if e != x) for x in ELEMENTS] + [ELEMENTS]


def oracle(point, subset, bundle, damage) -> str:
    """'invalid' | 'ok' | 'refuse-or-invalid'.
    - Every commitment point has journal rows, so a changed bundle is INVALID (bundle) (F6.4).
    - Damage to an element that exists at the point is INVALID (F3/F4 committed evidence; legacy records through
      OQ-19), except that deleting only stop.json before any finalization INTENT is the recoverable publication gap
      (F2.3): 'ok'.
    - Deleting elements that do not exist yet is a no-op: 'ok'.
    - A fabricated stage artifact (seal, attestation, prereg) with no INTENT is INVALID (F4 table).
    - A fabricated legacy-only file (registry/witness record, opening receipt, stop.json) before its time is outside
      every F-rule: the spec fixes no single outcome; both outcomes stop all work: 'refuse-or-invalid' (OQ-19/OQ-24)."""
    if bundle == "changed":
        return "invalid"
    idx = POINTS.index(point)
    live = [e for e in subset if EXISTS_FROM[e] <= idx]
    if live == ["stop"] and damage == "deleted" and idx < FIRST_FINALIZATION_INTENT:
        return "ok"                                                # F2.3 publication gap (only before stop_attest)
    if live:
        return "invalid"
    if damage == "deleted":
        return "ok"
    if any(e in JOURNAL_MEMBERS for e in subset):
        return "invalid"
    return "refuse-or-invalid"


def _build(root, point):
    """The real lifecycle up to `point` (synthetic ledgers; tmp mailbox)."""
    if point in ("after-audit", "after-opening", "after-opening-ack"):
        start, cal, oc, _ = s1_plan_audit(root, START)
        if point == "after-audit":
            return {"oc": oc, "now": z.close_of(oc, cal) + timedelta(hours=1)}
        s1_opening_checkpoint(root, Ledger(root / "ledger.sqlite3"), oc, cal, S1_RECEIPT)
        if point == "after-opening":
            return {"oc": oc, "now": z.close_of(oc, cal) + timedelta(hours=1)}
        from test_s1_a3_prestart import close_out
        w = close_out(root, cal, oc)
        s1_ack(root, "opening-ack", "S1-OPENING-ACK", w + timedelta(minutes=1))
        return {"oc": oc, "now": w + timedelta(minutes=2)}
    # conftest.s1_state(upto=...) (added in this task) stops the real lifecycle right after the named CREATED point
    st_ = s1_state(root, START, upto=point)
    return {"oc": st_["opening_close"], "now": st_["now"]}


@pytest.fixture(scope="module")
def snapshots(tmp_path_factory):
    got = {}
    base = tmp_path_factory.mktemp("matrix")
    for p in POINTS:
        root = base / p
        root.mkdir()
        old = c.MAILBOX
        c.MAILBOX = root / "mailbox.sqlite3"                        # module-scoped build: its own tmp mailbox
        try:
            from conftest import s1_mailbox_init
            s1_mailbox_init(root)
            got[p] = dict(_build(root, p), root=root)
        finally:
            c.MAILBOX = old
    return got


def _invalid_rows(root) -> int:
    trials = t.trials(t.scan(root / "mailbox.sqlite3"))
    return sum(1 for tid, x in trials.items() for row in j.read_trial(tid, x.genesis, root / "mailbox.sqlite3")
               if row.kind == "TRIAL-INVALID")


CASES = [(p, s, b, d) for p in POINTS for s in subsets() for b in ("same", "changed")
         for d in ("deleted", "changed", "unparseable")]


@pytest.mark.parametrize("point,subset,bundle,damage", CASES,
                         ids=[f"{p}|{'+'.join(s)}|{b}|{d}" for p, s, b, d in CASES])
def test_matrix(tmp_path, monkeypatch, snapshots, point, subset, bundle, damage):
    snap = snapshots[point]
    root = tmp_path / "root"
    shutil.copytree(snap["root"], root)
    monkeypatch.setattr(c, "MAILBOX", root / "mailbox.sqlite3")
    out = root / "s1_out"
    for e in subset:
        targets = paths(out, snap["oc"])[e]
        for p in (targets if isinstance(targets, list) else [targets]):
            if damage == "deleted":
                p.unlink(missing_ok=True)
            elif damage == "changed":
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes((p.read_bytes() if p.is_file() else b"{}") + b" ")
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"{not JSON")
    if bundle == "changed":
        monkeypatch.setattr(c, "bundle_sha256", lambda *a, **kw: "f" * 64)
    want = oracle(point, subset, bundle, damage)
    before = _invalid_rows(root)
    sp = Spies(monkeypatch)
    if want == "ok":
        with _Clock(snap["now"]):
            t.gate(root, "matrix probe")
        assert _invalid_rows(root) == before
        return
    sch = c.aware(START) + timedelta(hours=7, minutes=15)
    with _Clock(snap["now"]), pytest.raises(SystemExit):
        ck.run_checkpoint(root, root / "ledger.sqlite3", sch, sp.receipt(), sp.process(), root / "c.log",
                          now=lambda: snap["now"])
    sp.assert_zero()
    if want == "invalid":
        assert _invalid_rows(root) > before
```

Before the exhaustive run, the oracle is checked element by element: a singleton run at every point. Any case where
observation and oracle disagree is resolved from the spec (F2.3, F3, F4, F6.4) and OQ-19/OQ-24, and recorded in
`a3/t14_old_new.md`. The oracle is never edited to match an observation without a stated spec reason.


`research/s1/s1_tests/test_s1_a3_residual.py`:

```python
"""Addendum 3 rev 5 F8.1 / F10 CH4: the accepted uncommitted-detection residual (labelled lost detection, not
equivalence) and its limit (a committed INVALID keeps the same restoration invalid)."""
import shutil
from datetime import timedelta

import pytest
import s1_common as c
import s1_journal as j
import s1_trial as t
from conftest import Spies, s1_state

START = "2026-10-26T13:30:00+00:00"


def test_uncommitted_detection_may_resume_and_is_labelled_lost_detection(tmp_path, monkeypatch):
    """The violation is observed while the journal cannot be written; the INVALID never commits; committed bytes are
    restored and the local witnesses deleted; the restart may resume. This is the F8.1 residual - LOST DETECTION, NOT
    EQUIVALENCE - recorded in s1_evidence/a3/t14_residual.txt; no guarantee is claimed for it."""
    s1_state(tmp_path, START)
    out = tmp_path / "s1_out"
    p = out / "attest_start.json"
    keep = p.read_bytes()
    p.write_bytes(keep + b" ")
    real = j.append
    monkeypatch.setattr(j, "append", lambda *a, **kw: (_ for _ in ()).throw(j.Outage("journal down")))
    with pytest.raises(SystemExit):
        t.gate(tmp_path, "observer during an outage")
    monkeypatch.setattr(j, "append", real)
    p.write_bytes(keep)
    for w in ("aborted.json", "refusals.jsonl"):
        (out / w).unlink(missing_ok=True)
    shutil.rmtree(out / "invalid", ignore_errors=True)
    gv = t.gate(tmp_path, "restart")
    assert gv.state == "ACTIVE"                                    # resumed: lost detection, not equivalence


def test_invalid_committed_before_the_crash_keeps_restoration_invalid(tmp_path, monkeypatch):
    s1_state(tmp_path, START)
    out = tmp_path / "s1_out"
    p = out / "attest_start.json"
    keep = p.read_bytes()
    p.write_bytes(keep + b" ")
    with pytest.raises(SystemExit, match="INVALID"):
        t.gate(tmp_path, "observer")
    p.write_bytes(keep)
    for w in ("aborted.json", "refusals.jsonl"):
        (out / w).unlink(missing_ok=True)
    shutil.rmtree(out / "invalid", ignore_errors=True)
    sp = Spies(monkeypatch)
    with pytest.raises(SystemExit, match="INVALID"):
        t.gate(tmp_path, "restart")
    sp.assert_zero()
```

- [ ] **Step 3: Remove the transitional set.** In `s1_stage.py`, delete `ENFORCED` and its checks; `evaluate` loops
  over `TABLE`. Replace every test reference (`monkeypatch.setattr(sg, "ENFORCED", …)`) by nothing: all stages are
  enforced. Add to `test_s1_a3_stage.py`:

```python
def test_every_stage_is_enforced_by_the_gate():
    import s1_stage
    assert not hasattr(s1_stage, "ENFORCED")
```

  Add to `test_s1_a3_matrix.py` (row 283, `static`):

```python
def test_matrix_scope_is_the_declared_scope(tmp_path):
    assert len(POINTS) == 10 and POINTS[2] == "after-opening-ack"
    import s1_stage
    assert {p.split("after-", 1)[1].replace("-", "_") for p in POINTS} - {"opening_ack", "stop"} == \
        set(s1_stage.TABLE) - set()                                # every CREATED stage is a point
    out = tmp_path / "s1_out"
    for rel in ("audit/calendar.json", "audit/pages/calendar.json", "audit/manifest.json"):
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        (out / rel).write_text("{}", encoding="utf-8")
    assert {p.relative_to(out).as_posix() for p in paths(out, "2026-10-23")["audit tree"]} == {
        "audit/calendar.json", "audit/pages/calendar.json", "audit/manifest.json"}
```

  `conftest.s1_state` gains `upto` (one of the POINTS from `after-start-attest` on). It runs the real lifecycle
  (`attest_start`, `do_prereg`, `decide_stop`, `attest_stop`, `write_final_plan`, `do_final`, `score`, each with its
  ACK) and stops right after the named CREATED point. Record this in `a3/t14_old_new.md` as a fixture addition.

- [ ] **Step 4: Run.**
  - `S1_MATRIX_FULL=1` exhaustive matrix into `a3/t14_matrix_full.txt` (record the case count:
    511 × 2 × 3 × 10 = 30,660; the default run is 55 × 2 × 3 × 10 = 3,300);
  - the default suite into `a3/t14_green.txt`;
  - `test_s1_a3_residual.py` into `a3/t14_residual.txt`, with the header line `F8.1 residual: lost detection, not
    equivalence`.
- [ ] **Step 5: Write `a3/codex_probes_old_new.md`.** One row per new probe test: the historical file and test name,
  the historical JSON observation (`publication-offset-0.json`, `seal.written=true`, and so on), the new expected
  outcome, the spec clause, and the task that changed it. A second, separate section lists every fixture/setup
  incompatibility met while the probe file was first run, with its fix.
- [ ] **Step 6: Full suite, consolidated old->new, hashes.**
  - Save `a3/t14_full.txt`.
  - Write `a3/old_new_all.md`: the union of `t1_old_new.md`..`t14_old_new.md`, each entry with test id, old
    expectation, new expectation, spec clause and class (intended, fixture or regression-fixed).
  - Write `a3/hashes_final.txt`: sha256 of every file under `research/s1` (product, tests, docs, evidence) at the
    final head.
- [ ] **Step 7: Controller review and commit.** Message: `S1 A3 Task 14: damage matrix, CH4 residual, probe record,
  all stages enforced`, listing map rows 161, 162, 176, 223, 224, 255 and 283, with the Co-Authored-By line. Push
  and assert the HEAD SHA.

---

### Task 15: Mutation testing - Cosmic Ray on the changed critical modules and targeted semantic mutants (PLAN-6; F10 Other; rows 284–298)

**Files:**
- Create: `research/s1/s1_evidence/cr_a3/<module>/cr.toml` for each of `s1_journal`, `s1_locks`, `s1_trial`,
  `s1_slot`, `s1_stage`, `s1_seal`, `s1_collect`. The format follows the existing
  `research/s1/s1_evidence/cr_s1/sessions/` configs (Cosmic Ray 8.3.15):

```toml
[cosmic-ray]
module-path = "research/s1/s1_journal.py"
timeout = 300.0
excluded-modules = []
test-command = "C:/Users/gl450/.coordination/trading_app/testenv/Scripts/python.exe -m pytest -x -q -p no:cacheprovider -p conftest research/s1/s1_tests/test_s1_a3_journal.py research/s1/s1_tests/test_s1_a3_precedence.py"

[cosmic-ray.distributor]
name = "local"
```

  Each module's test-command names that module's A3 test files:
  - `s1_locks`: `test_s1_a3_locks.py`;
  - `s1_trial`: `test_s1_a3_trial.py` and `test_s1_a3_gate.py`;
  - `s1_slot`: `test_s1_a3_slots.py` and `test_s1_a3_finalizer.py`;
  - `s1_stage`: `test_s1_a3_stage.py`;
  - `s1_seal`: `test_s1_a3_stop.py` and `test_s1_a3_score.py`;
  - `s1_collect`: `test_s1_a3_audit.py` and `test_s1_a3_final.py`.

  For `s1_seal` and `s1_collect`, the run is restricted to the changed functions listed in rows 289–290: a
  `cr-filter-pragma`-style exclusion of the other line ranges is generated from `git diff 93f4c3e -- <file>` and
  recorded in the config.
- Create: `research/s1/s1_tests/test_s1_a3_mutants.py` (rows 291–298).
- Create: `research/s1/s1_evidence/a3/t15_cr_<module>.txt` (rows 284–290) and `a3/t15_mutants.txt`.

**Interfaces:** none (tests and evidence only).

- [ ] **Step 1: Cosmic Ray runs.** For each module:
  - `cosmic-ray init cr.toml session.sqlite`, then `cosmic-ray exec cr.toml session.sqlite`, then
    `cr-report session.sqlite`, all with the testenv python, PYTHONPATH as in Global Constraints, tmp only;
  - save the report to `a3/t15_cr_<module>.txt`.

  The S1 tests never touch the network, the live app or the real mailbox, so neither do the mutation runs.
- [ ] **Step 2: Triage.** In each report file, list survivors, timeouts and incompetent/untested mutants
  separately. Then for each survivor:
  - kill it: write a new test that fails on the mutant and passes on the code, recorded old-fail/new-pass. It goes
    into the module's A3 test file, with a map-row reference;
  - or argue it equivalent, citing the exact reason. Equivalence claims are listed for Codex review and never
    silently accepted.

  A timeout is not a kill. Rerun it with a longer `timeout` once, then triage it as a survivor.
- [ ] **Step 3: Targeted semantic mutants** (`test_s1_a3_mutants.py`). Each case applies one named mutation by
  monkeypatching a named function with a mutated copy, never by editing a file. It then runs the named killing test
  through `pytest.main([...])` in a child process and asserts that the test FAILS. The unmutated control asserts that
  the same test PASSES:

```python
"""PLAN-6: targeted semantic mutants that Cosmic Ray's operators do not express. Each MUTANT names (target, mutated
behaviour, killing test). The mutation is installed by a tiny plugin module written to tmp_path and loaded with
`-p`; the child pytest must fail. Never edits product files."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
PY = sys.executable
MUTANTS = {
    # rows 291: deadline comparisons in decide step 6
    "deadline-intent-ge-to-gt": ("s1_journal._slot", "now >= e", "now > e",
                                 "test_s1_a3_precedence.py::test_precedence_table"),
    "deadline-qualified-ge-to-gt": ("s1_journal._slot", "req.r_at >= d", "req.r_at > d",
                                    "test_s1_a3_slots.py::test_publication_at_d_and_d_plus_1us_does_not_seal"),
    "deadline-timeout-lt-to-le": ("s1_journal._slot", "now < d", "now <= d",
                                  "test_s1_a3_finalizer.py::test_timeout_commits_at_d_while_a_live_worker_holds_the_work_lock"),
    "deadline-missed-lt-to-le": ("s1_journal._slot", "now < e", "now <= e",
                                 "test_s1_a3_finalizer.py::test_missed_after_e_with_its_own_op_and_no_files"),
    # row 292: omitted commitments / ACK checks
    "omitted-envelope-input": ("s1_run.attest_start", '"opening_books.json": rec["opening_books_sha256"]', "",
                               "test_s1_a3_prestart.py::test_start_attest_envelope_and_single_member"),
    "omitted-verify-ack-field": ("s1_trial.verify_ack", "if bad:", "if False:",
                                 "test_s1_a3_prestart.py::test_start_attest_verifies_the_opening_ack_against_the_journal"),
    "omitted-check-journal": ("s1_trial.verify_ack", "if probs:", "if False:",
                              "test_s1_a3_trial.py::test_journal_seq_and_head_must_be_extended_without_fork"),
    "omitted-evidence-manifest": ("s1_trial.opening_manifest_check",
                                  'if got != a.fields["evidence_manifest_sha256"]:', "if False:",
                                  "test_s1_a3_prestart.py::test_opening_ack_evidence_manifest_is_reconstructed"),
    # row 293: STOP rules
    "stop-n-ge-to-gt": ("s1_seal.stop_record", ">= STOP_N", "> STOP_N",
                        "test_s1_a3_stop.py::test_stop_dispositions"),
    "stop-pending-removed": ("s1_seal.stop_record", 'if stt == "pending":\n            return None',
                             'if False:\n            return None', "test_s1_a3_stop.py::test_pending_slot_blocks_the_stop"),
    "stop-prefix-le-to-lt": ("s1_seal.sampled_seals", "x.seq <= upto_seq", "x.seq < upto_seq",
                             "test_s1_a3_score.py::test_sampled_history_is_canonical_and_fixed_at_the_stop"),
    # row 294: owner / takeover
    "owner-4a-actor-removed": ("s1_journal._slot", "or req.actor != intent.actor", "",
                               "test_s1_a3_slots.py::test_foreign_qualified_is_invalid_even_on_a_terminal_slot"),
    "owner-timeout-op-removed": ("s1_journal._slot", 'k == "SLOT-TIMEOUT" and (intent is None or req.op != intent.op)',
                                 'k == "SLOT-TIMEOUT" and intent is None',
                                 "test_s1_a3_precedence.py::test_precedence_table"),
    "owner-recovery-own-op": ("s1_stage.recover", 'm["intent"].op, j.new_nonce()', "j.new_nonce(), j.new_nonce()",
                              "test_s1_a3_stage.py::test_stage_state_table"),
    # row 295: CA scope
    "scope-window-full-swapped": ("s1_collect.final_policy", 'ca("window", fplan["ca_symbols_window"]',
                                  'ca("window", fplan["ca_symbols_full_history"]',
                                  "test_s1_a3_final.py::test_final_policy_is_exactly_the_f49_final_rows"),
    "scope-full-history-start": ("s1_collect.final_policy", 'fplan["full_history_start"]', "start_day",
                                 "test_s1_a3_final.py::test_final_policy_is_exactly_the_f49_final_rows"),
    # row 296: midnight cutoff from the reservation clock
    "cutoff-reservation-clock": ("s1_collect.do_audit", 'cutoff = sw.policy["cutoff"]',
                                 "cutoff = c.now_utc().astimezone(c.NY).date().isoformat()",
                                 "test_s1_a3_audit.py::test_cutoff_is_the_intent_new_york_date_across_midnight"),
    # row 297: erratum mutants
    "erratum-finalizer-takes-work-lock": ("s1_slot.finalize_close", "got = _finalizer_append(",
                                          "got = _locked_append(",
                                          "test_s1_a3_finalizer.py::test_finalizer_decision_never_touches_the_work_lock"),
    "erratum-seal-in-stopped": ("s1_slot.publish_seal", 'if st_ != "ACTIVE":', "if False:",
                                "test_s1_a3_finalizer.py::test_no_seal_after_stop_even_for_a_pre_stop_qualified"),
    "erratum-non-official-close-counts": ("s1_trial.acks_from", "if (sender, recipient, key) != ACK_KEY:",
                                          "if False:",
                                          "test_s1_a3_trial.py::test_non_official_lines_are_never_candidates"),
    "erratum-backup-dropped": ("s1_slot.CAPTURE_TREE", '("backup.sqlite3", "meta.json", "projection.json")',
                               '("meta.json", "projection.json")',
                               "test_s1_a3_slots.py::test_qualified_at_is_r_and_detail_is_the_tree_manifest"),
    "erratum-after-json-authority": ("s1_slot.required_seals", 'rep.get("seals_checked")',
                                     '_after_seals(n)', "test_s1_a3_slots.py::test_after_json_is_display_only"),
}
EXTRA = {                                    # helpers some mutated sources call; exec'd into the same namespace
    "erratum-finalizer-takes-work-lock": (
        "import s1_locks as _L\n"
        "def _locked_append(gv, cal, req, mailbox, now):\n"
        "    with _L.OwnershipLock(gv.root, gv.trial.trial_id, _L.slot_lock_name(req.subject)):\n"
        "        return _finalizer_append(gv, cal, req, mailbox, now)\n"),
    "erratum-after-json-authority": (
        "def _after_seals(n):\n"
        "    import json as _json\n"
        "    p = n['capture'].parent / (n['capture'].name + '.after.json')\n"
        "    try:\n"
        "        s = _json.loads(p.read_text(encoding='utf-8')).get('seal') or {}\n"
        "    except (OSError, ValueError):\n"
        "        return {}\n"
        "    return {'seals/' + n['capture'].parent.name + '.json': s.get('sha256')} if s.get('written') else {}\n"),
}
PLUGIN = r'''
import importlib, inspect, textwrap
TARGET, OLD, NEW, EXTRA = {target!r}, {old!r}, {new!r}, {extra!r}
mod_name, _, attr = TARGET.rpartition(".")
mod = importlib.import_module(mod_name)
obj = getattr(mod, attr)
if isinstance(obj, tuple):
    setattr(mod, attr, eval(NEW))
else:
    src = textwrap.dedent(inspect.getsource(obj))
    assert src.count(OLD) >= 1, ("mutation anchor not found", TARGET, OLD)
    ns = vars(mod)                                   # the module namespace itself: callers see the mutant
    exec(EXTRA, ns)
    exec(compile(src.replace(OLD, NEW, 1), mod.__file__, "exec"), ns)
'''


def _run(tmp_path, name, mutate):
    target, old, new, test = MUTANTS[name]
    plug = tmp_path / "s1_mutant_plugin.py"
    plug.write_text(PLUGIN.format(target=target, old=old, new=new, extra=EXTRA.get(name, "")) if mutate else "",
                    encoding="utf-8")
    env_pp = f"{tmp_path};{HERE};{HERE / 's1_tests'}"
    return subprocess.run([PY, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", "-p", "conftest",
                           "-p", "s1_mutant_plugin", f"research/s1/s1_tests/{test}"],
                          cwd=HERE.parent.parent, env=dict(os.environ, PYTHONPATH=env_pp),
                          capture_output=True, text=True, timeout=1800)


@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_targeted_mutant_is_killed(tmp_path, name):
    assert _run(tmp_path, name, mutate=False).returncode == 0           # control: the killing test passes
    p = _run(tmp_path, name, mutate=True)
    assert p.returncode != 0 and "mutation anchor not found" not in p.stdout + p.stderr, p.stdout[-2000:]
```

  The anchor strings are written against this plan's code. At Step 3 each one is checked against the final code. An
  anchor that no longer occurs fails loudly ("mutation anchor not found"); it never passes silently. Fix the anchor,
  not the assertion.

  The mutated function is re-executed in the module's own namespace, so it replaces the original for every caller.
  Methods and nested names are out of scope for this mechanism: their mutations are Cosmic Ray's.

- [ ] **Step 4: Hypothesis pinning (row 298).** Add to `test_s1_a3_mutants.py`:

```python
def test_hypothesis_settings_are_pinned():
    import ast
    for f in sorted((HERE / "s1_tests").glob("test_s1_a3_*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            decos = [ast.unparse(d) for d in fn.decorator_list]
            if any(d.startswith("given(") for d in decos):
                assert any(d == "seed(20261103)" for d in decos), (f.name, fn.name)
                assert any("derandomize=True" in d for d in decos), (f.name, fn.name)
                assert any("DirectoryBasedExampleDatabase" in d for d in decos), (f.name, fn.name)
```

  Copy `s1_evidence/a3/hypothesis_db/` into the evidence hashes. Every minimized failure found during Tasks 1–15 is
  kept as an `@example` next to its `@given`.
- [ ] **Step 5: RED/GREEN record.** The behavioural RED of this task is the set of mutants: each must fail its killing
  test. A mutant that survives is a finding. Add a killing test to the owning task's file, then rerun. Save
  `a3/t15_mutants.txt` (each mutant: control PASS, mutant FAIL, killing test id).
- [ ] **Step 6: Full suite and hashes.** Save `a3/t15_full.txt` and `a3/t15_hashes.txt`. Update `a3/old_new_all.md`
  with any killing test added in Step 2 or Step 5.
- [ ] **Step 7: Controller review and commit.** Message: `S1 A3 Task 15: Cosmic Ray on the changed critical modules,
  targeted semantic mutants, pinned Hypothesis`, listing map rows 284–298, with the Co-Authored-By line. Push and
  assert the HEAD SHA.

---

## Process (after each task, and at the end)
1. **Per task.**
   - The implementer, a fresh subagent per superpowers:subagent-driven-development, follows the task's steps and
     leaves the work uncommitted. It records the behavioural RED, the GREEN, the full-suite run, the old->new list
     and the hashes under `research/s1/s1_evidence/a3/`.
   - A fresh reviewer checks the task against this plan, the spec clauses in its map rows, and the TDD discipline:
     RED labels, no ImportError counted as RED, every changed existing test listed old->new.
2. **Commit.**
   - Only after the review does the controller commit.
   - Before: `git -C C:\Users\gl450\trading_app-s1 rev-parse HEAD`.
   - `git add` the task's exact files, with no `-A`; `git status` must show no unrelated paths.
   - Commit with the message given in the task. Every message ends with
     `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
   - Push. Assert that HEAD moved by exactly one commit.
   - Blocker gates (no default reading exists any more):
     - no task commits before BLK-1;
     - Task 11 Steps 4–7 do not start before BLK-3.
     - (BLK-2 is resolved by Erratum 1 r1 E5.5.)

     A Codex ruling that amends E3 or E1–E5 before adoption reworks the affected task text first, through a new
     plan revision.
3. **Whole-branch review.**
   - After Task 15, one fresh reviewer reviews the whole branch from `93f4c3e` to the final head: the spec
     coverage (every map row has its test and evidence), the consolidated `a3/old_new_all.md`, and
     `a3/hashes_final.txt`.
   - Findings are listed first and fixed in order (find-list-fix). Each fix carries its own test, and the
     controller commits it.
4. **Stage-1 package.** The controller builds a fresh Stage-1 package for Codex at the exact final head SHA. It
   contains:
   - this plan;
   - the frozen spec;
   - the map with its evidence pointers;
   - the open-question list with the f045bd31 rulings and the blocker resolutions (BLK-1..BLK-3);
   - the adopted Erratum 1 and its sha256;
   - `codex_probes_old_new.md`;
   - the full-suite output, the exhaustive matrix run and the Task 15 mutation reports;
   - the hash list.

   It is delivered through the coordination mailbox under the Agent Forum protocol
   (`C:\Users\gl450\.agent-forum\AGENT_FORUM_FRAMEWORK.md`). The disclosures:
   - mailbox isolation and stage order are convention, not enforcement;
   - the proposer is not the sole verifier of its decision-critical claims.
5. **Codex code review** is on that exact head. The result is labelled CONSENSUS, CONDITIONAL_CONSENSUS,
   NO_CONSENSUS or INSUFFICIENT_EVIDENCE. Any further change produces a new head and a new review of that head.
6. **Hard stops until a later CONSENSUS.**
   - No registration, audit, START, scheduler task or live step.
   - No write to the real coordination mailbox by S1 code.
   - No provider request.
   - **R-3** (live scheduler timing) stays OPEN.
   - **E3** (BLOCKED) is implemented but stays pending Codex acceptance of E3. It is settled only by Erratum 1's
     adoption.

## Plan self-review record (revision 1)
- **Spec coverage.**
  - Every F10 example, every normative rule of F0–F9 and every Erratum 1 r1 acceptance item (E1.7, E2.7, E3.6,
    E4.4) plus the r1 clarifications E2.4–E2.6, E3.4, E4.3, E5.5 and E5.6 has a map row: 333 rows, where 1–255 keep
    their numbers and 256–333 are new.
  - The PLAN-1..6 findings, the nine coverage corrections and all 39 OQ rulings each point to a task step and a row
    (the "Revision 1 changes" table).
  - Rows 153, 166 and 167 are procedural (Codex's re-hash, Codex's issuance checks, R-3) and have no S1 test; the
    reason is stated in each row. Row 176 is a process-evidence row.
  - Rows 284–290 are mutation-evidence rows.
  - Nothing is deliberately unimplemented. E3 is implemented, pending Codex acceptance of E3.
- **Placeholders.** One permitted fill-in: `ERRATUM1_SHA256` (Task 1 Step 0, from the adopted copy of Erratum 1
  revision 1, or of the revision actually adopted). Two pieces are explicitly not final:
  - the BLK-3 stop dispositions (Task 11 `stop_record` and `a3_helpers.stop_history` expected values, fixed by
    Codex's acceptance of `t11_dispositions.md`);
  - the Task 15 mutant anchors, which are checked against the final code with a loud failure.

  No step implements a reading "until Codex disagrees".
- **Default removed.** Revision 0's rule "implement the proposed reading until Codex disagrees" is gone. Every OQ
  carries its f045bd31 ruling. OQ-8 still needs a Codex decision and is blocker BLK-3, naming the steps that cannot
  start. OQ-17's former blocker BLK-2 is resolved by Erratum 1 r1 E5.5.
- **Erratum consistency.** The plan was re-checked against Erratum 1 draft revision 1 (sha256 bee16ded…), which
  governs over the addendum. The four plan-level choices disclosed against rev 0 are now erratum text, and the
  plan follows that text:
  - E2.6: a held stop lock means no change and pending;
  - E2.5: the stop operation publishes every determined unpublished seal before TRIAL-STOP;
  - E4.3: the attribution grammar;
  - E5.6: the opening-window consequence.

  E2.4 (`seals_checked` in every QUALIFIED tree and PREPARED commitment), E3.2/E3.4 (trial_id in blocked.json; h
  over {trial_id, reasons}) and E5.5 (format, membership, INVALIDATE) are implemented as written.
- **Type consistency.**
  - These names are used identically across tasks: `s1_journal.Row/Request/Context/Decision/Result/append/decide/read_trial`,
    `s1_trial.Trial/Ack/Gate/gate/open_trial/verify_ack/ack_record/artifact_fields/token/invalidate/product_context`,
    `s1_locks.OwnershipLock/LockHeld/LockError/slot_lock_name/stage_lock_name/STOP_LOCK`,
    `s1_slot.Worker/names/qualified_tree/failed_tree/first_qualified/seal_bytes/finalize_close/evidence_check`,
    `s1_stage.run/recover/evaluate/permitted/stage_rows/StageWork/StageAbort/manifest_projection/TABLE/FIXED_TREE`,
    `s1_seal.stop_record/decide_stop/stop_check/sampled_seals/sampled_history`.
  - `s1_stage.run` gains `extra_gate`/`publish_ctx` in Task 10; earlier callers are unaffected (keywords with
    defaults).
  - Revision 1 additions, used consistently:
    - `s1_locks.lock_acquirable`, `NAME_RE`;
    - `s1_slot.seals_checked`, `required_seals`, `publish_seal(…, stop_lock_held=)`, `SUBTYPES`, the new
      `Worker.violation(subtype, reason, rep, receipt_sha)` signature, and `move_leftovers(…, root=, trial_id=)`
      returning None when deferred;
    - `s1_trial.attributed_trial`, `evidence_manifest`, `opening_manifest_check`, `open_trial(mailbox, root=)`,
      and `close_evidence(…, blocked_record: dict)`;
    - `s1_run.blocked_reasons_record`, `blocked_close_evidence`, `_blocked_refusal` and `_opening_books`;
    - `s1_stage.committed_commitment(root, trial_id, stage, rows)` and the `seals_checked` argument of
      `s1_stage.commitment`;
    - `s1_common._report_seals(out, rows, cal)` and `s1_run._capture_seal_problems(out, rows, cal)`.
  - The start_attest kind is `single` everywhere: `TABLE`, `SINGLE` and rows 85, 104 and 268.
- **Review Focus.** Its five lines have tests in Tasks 1, 3, 8, 9 and 12.
- **Known risks for the executor.**
  1. The ctypes CreateFileW path in `s1_locks` must be proven by the Task 3 child-process tests on this Windows
     host. If `msvcrt.locking` behaves differently on a zero-length file, lock one byte at offset 0 after writing a
     single byte. A test pins the behaviour either way.
  2. The conftest migration (Tasks 5, 7, 9, 11, 12) is the largest source of old->new churn. Every changed existing
     test must appear in `a3/old_new_all.md` with its class.
  3. Task 2's Hypothesis oracle is an independent transcription of the F0.5 table. If it disagrees with `decide`,
     the spec table decides; the oracle is never edited to match. Its scope is slot subjects only (row 48).
  4. F7.2(b) literal moves every OPENING-ACK fixture after the W slot's E. If `eligible_until(W)` on the fixture
     calendar is not strictly before planned START minus the attestation margin, the fixture START moves later; it
     is recorded in `a3/t10_old_new.md`, never by weakening the check.
  5. E1 makes a live, stalled worker and a finalizer coexist past D. Rows 256–259 use real child processes. The
     child must be killed in `finally`, so that no lock outlives the test.
  6. Task 15's Cosmic Ray runs are slow (timeout 300 s per mutant). Run them per module, in the background, never
     against the live app. Timeouts are triaged as survivors.
- **Self-check of this revision (static, no scripts run).**
  - Every R1-xx entry names rows that exist.
  - Every new row names a task that now contains its test.
  - Every task's commit list includes its new rows.
  - start_attest is never `tree`.
  - No revision-0 "pending: a live owner holds the slot lock" finalizer path remains.
  - Row 121 is no longer `retro`.

