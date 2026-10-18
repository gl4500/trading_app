# S1 design v5 — Addendum 1 (protocol amendments before registration) — revision 3

Status: DRAFT for Codex approval. Revision 3 supersedes revisions 1 (13ac4371…, 3bf0ce3a) and 2 (252fc434), and folds in Codex f7384943 (A4.2 any post-event SELL, carry-in precedence, A5.2 post-capture revalidation, A1 .env wording, A3 bootstrap reads) and
folds in Codex mailbox 89e72ebc (Q7 + plan-review points 1–8). Amends s1_design_v5.md (sha256 33c32840…) and
s1_spec.md (4b882f52…), which stay unchanged as historical records; where they differ, this addendum governs.
Sources: Codex rulings 97e1d853 (Q0–Q6; controlling text s1-q0-q6-codex-rulings.txt), 89e72ebc, the final
branch review (reports/final-review.md) and the Codex plan review 0a58b934 (2026-10-14). The missed 0a58b934
review stays in the record. This addendum must be approved, implemented and tested BEFORE any registration
(opening seal, START attestation, RUN-ACK); it cannot rescue an already-started trial (none has started).

## A1. Semantic receipt scope (replaces the receipt definition in §12; Q0, Q3, point 7)
1. **Validity fingerprint (compared for equality at every pre-stop seal):**
   - the complete reviewed MR dependency closure: membership AND sha256 of every file; roots as in §12 plus every
     in-repo transitive import (relative and `from pkg import sub` included) and shared execution/risk/lifecycle/
     persistence/data-context code; nothing trimmed for convenience. A missing root, a missing member or a new
     member is a receipt FAILURE, never a silently different list;
   - MR-relevant static policy/config resources of any file type, bound by presence/absence and sha256
     independently of git tracking or extension (registered resource list);
   - MR-relevant effective configuration evidence under a registered evidence contract: the bound config sources
     (`.env` and code defaults) plus sanitized launcher/process binding evidence; a parsed `.env` subset alone is
     not claimed to prove the effective process configuration (disclosed limitation). Secret-named fields are bound
     by field name, presence and a keyed HMAC-SHA256 fingerprint, never raw values; the HMAC key is stored outside
     s1_out and the repo, and its identity (key-id hash) is bound so that key loss or rotation shows as a change,
     not as unchanged values. No operator key rotation is required by this addendum. The evidence contract binds the
     actual effective-config sources including code defaults and overrides; `.env` is not intrinsically mandatory —
     a reviewed alternate source arrangement is permissible — but an input the registered contract marks REQUIRED
     (`.env`, runtime, resource) that is missing fails explicitly, and there is never a silent fallback to an empty
     value set. Disclosed `.env` incompleteness alone does not establish effective-config equality;
   - the backend's registered runtime: Python version and installed package versions of the backend runtime.
2. **Informational provenance (recorded at every seal, NOT compared):** live checkout HEAD, the git dirty list,
   transient files (SQLite `-journal`/`-wal`/`-shm`, logs, runtime caches), and HOST/PORT where they affect
   transport/observation only (a setting that changes execution, market data, risk or MR behaviour stays in the
   fingerprint). Changes and observation gaps are reported.
3. Consequences: an unrelated commit/pull/checkout, other branches/worktrees, or tools in an isolated research venv
   do not invalidate. A change to any fingerprint item between the opening seal and the stop => ABORTED-INVALID.
   The AST closure is a file-list control, not proof of runtime loading; dynamic-import limits and the operator's
   binding/continuity attestations stay explicit as in §12.

## A2. Stop freezing and post-stop operation (amends §6, §9; Q1)
1. When the stop (STOPPED/TIMEOUT) is determined at a seal, the stop identity — stop close, authoritative stop seal
   file and sha256, cohort row ids, decision time — is persisted once (`s1_out/stop.json`, exclusive) and never
   recomputed from later rows or changed helpers. NO-VALID-SEAL is terminal and persisted the same way; no late
   rescue seal.
2. After the persisted stop (or a persisted invalidity), scheduled checkpoints record `post_stop` captures only:
   no trial seal, and no outcome change from ordinary post-stop live operation (rows stored after the stop close,
   restarts, live-app edits). A persisted invalidity stays terminal and is never converted into a valid stop.
3. Integrity of the frozen experiment is enforced after the stop: a change, deletion or backdated insert affecting
   rows with stored time <= stop close; a changed or missing opening/bridge/trial seal or attestation; or a
   registered-bundle mismatch (A3) => preserved integrity failure and ABORTED-INVALID at score. Final snapshot and
   score check fences against the opening, bridge and trial seals through the persisted stop only.

## A3. Registered S1 bundle (new; Q2)
1. The bundle = every `research/s1/s1_*.py` plus pinned `e1_sim.py`/`e1_fetch.py` as an explicit expected file list
   with sha256, plus the sha256 of v5 design, spec and this addendum. Tests are evidence, not runtime dependencies,
   and are not part of the bundle. RUN-ACK, prereg, every opening and trial seal, ACQUIRE-ACK and SCORE-ACK bind the
   bundle hash; caches are keyed by resolved path + approved hash.
2. Every S1 command verifies the bundle FIRST — before reading protocol state, deciding a stop, any live capture or
   request, or any reservation. Only the minimal reviewed bootstrap reads needed to obtain the externally approved
   expected manifest/ACK precede the comparison; arbitrary prereg state never chooses the expected hash, and no stop
   or economic helper runs before the comparison. Persistent mismatch evidence and the frozen stop survive
   restoration of files.
3. A mismatch against a valid registered bundle observed from the opening seal to the score is a PERSISTENT protocol
   failure for that registration (`aborted.json`, reason "bundle"); restoring files does not resume it; no re-clock,
   no valid score; a correction needs a disclosed, separately reviewed new registration. (This is distinct from
   invalid or fabricated authorization, A8, which refuses with zero live callbacks.)
4. Score checks persistent mismatch evidence and bundle consistency across prereg, every seal, the final snapshot,
   the final manifest and itself; current-hash equality at score alone is not sufficient.

## A4. Unit/identity trust vs economic per-lot exclusions (amends §11; Q5, Q6, point 6)
1. **Carry-in inventory trust (BLOCKED before START / INCONCLUSIVE after):** triggered only by unit/identity actions
   (all split kinds, parent unit/identity changes, stock dividends, relevant acquiree-side events) on a symbol held
   across the action's effective date, with an explicit pre-START effective-date bound for the opening audit and
   held-interval checks; and by combined, incomplete, conflicting or unknown records for that symbol. A special cash
   dividend alone, or a plain spin-off/rights distribution leaving parent units and identity unchanged, is not a
   carry-in trigger; it stays a per-lot paired exclusion (§11). The opening audit is not proof about unseen
   pre-START bridge rows: bridge-introduced units/identity are checked by the same rule.
2. **Contaminated symbol (pre-registered conservative rule; replaces Task-7 ruling C-2):** a unit/identity action on
   symbol S with any lot of S (cohort or carry-in) open across its effective date contaminates S. An action whose
   effective date is missing, ambiguous or conflicting follows the conservative unknown-action rules and is never
   treated as outside the date comparison. Then, in this order:
   a. **Precedence:** all protocol, carry-in (A4.1 and v5 §11 carry-in precedence), stop and cohort trust checks run
      first. A contaminated carry-in position is governed by A4.1 (whole-trial INCONCLUSIVE after START) even when no
      SELL of S follows the action; it is never downgraded to symbol exclusion.
   b. **Any post-event SELL => INCONCLUSIVE:** if S is contaminated and ANY SELL of S has stored time on or after the
      action's effective date and at or before the stop close, the whole trial is INCONCLUSIVE ("unit event may
      affect stop/cohort attribution"), whatever the unrepaired FIFO allocation of that SELL shows. The allocation
      under the unrepaired ledger is not evidence that the SELL is harmless. No SHADOW PASS/FAIL from the remaining
      symbols. (No independently sound unit/identity basis for an exception is registered; none is applied.)
   c. **Otherwise** (cohort-only contamination, no SELL of S from the effective date through the stop): every cohort
      lot of S is excluded in both arms, from action/identity metadata only (never returns), with the original N and
      the fixed > 10 % cap unchanged; no replacement lots, endpoint extension or post-score whitelisting. The basis is
      recorded in the score report.
   A fully resolved event with no lot of S open across it does not contaminate S. No implicit unit repair.
3. Acceptance tests: a post-event SELL that the unrepaired FIFO allocates only to a newer lot (or that leaves no old
   residual after a write-off) but whose allocation changes under the true post-action units (2b INCONCLUSIVE); a
   post-event BUY whose SELL is consumed by a contaminated earlier lot (2b); a unit event changing the apparent 100th
   sale (2b); a no-SELL carry-in split (2a, INCONCLUSIVE under A4.1); a cohort-only contaminated symbol with no SELL
   (2c exclusion); a special dividend on a carry-in symbol (scored, lot-level exclusion only); closed-and-reopened
   symbol; event after the carry-in was fully sold; harmless resolved pre-entry event; missing or ambiguous action
   identity/date (conservative block).

## A5. Timing (amends §4, §6, §9; Q7, point 4)
1. The deadline is an aware INSTANT: START + 6 calendar months at START's New York wall time (month-end clamp). The
   timeout close is the last sealed close whose close INSTANT is <= the deadline instant (e.g. START 2026-10-15
   09:30 => the Apr-15-2027 16:00 close is ineligible). All comparisons use close instants.
2. **Slot eligibility (Q7, registered):** for registered slot s and that close's window end W (08:00
   America/New_York on the next NYSE session day), E = min(s + SCHEDULE_SLACK, W), SCHEDULE_SLACK = 10 minutes,
   named and single-sourced, registered prospectively. A capture is eligible only if
   s <= capture_start <= capture_end <= E (aware instants). The actual clock is checked to be within [s, E] BEFORE
   any capture (necessary, not sufficient); the measured capture start and end are re-validated against the same
   predicate AFTER the capture and BEFORE any seal is written; a capture finishing after E never seals. Completion
   exactly at E is allowed. No shifted slots, extra retries, new late attempts, or W recomputed from invocation
   time; a delayed queued invocation cannot claim a later slot. Every attempt and its original scheduled time is
   preserved; duplicate execution of a slot is prevented; the seal is the first eligible consistent capture in slot
   order, never chosen by arrival order. Late/refused reports use the same predicate.
3. **The 08:00 slot** has no positive-duration eligible window (E = W = s): it is a documented, effectively
   non-sealable terminal boundary; it is not slid to 08:10 nor replaced by 07:50.
4. The ">= 5 NYSE sessions after review" rule counts from the S1-AUDIT-ACK's recorded time.
5. Required examples: exact-boundary (end == E) eligible; just-late (end = E + 1 s) ineligible; capture starting
   before s ineligible; overnight, weekend and holiday windows; overlapping retry tolerances resolved by slot order.

## A6. Calendar (amends §4; point 4)
The trading calendar used for sessions, closes and window ends is the provider's session calendar (Alpaca
`/v2/calendar`: date, open, close), pinned and hashed at the audit with its source, request parameters and
retrieval time, covering the session before START (opening close) through deadline + final lag. Completeness is
checked against that pinned source (ordered, unique, open < close, contiguous by the provider's own listing); any
listed gap or inconsistency refuses. The design does not claim an independent proof of the NYSE calendar beyond the
pinned provider listing (disclosed limitation); special closures and early closes come from the provider's open/
close times, never a weekday-minus-holidays rule. Synthetic dropped-session tests check the refusal path only.

## A7. Final acquisition (amends §13; Q4, point 5)
1. The final plan is derived from the persisted stop (A2) and its bound seal (stop, cohort, carry-in and
   bridge-introduced symbols); it requires STOPPED/TIMEOUT, no persisted invalidity, and the artifact-bound stop
   attestation. ACQUIRE-ACK binds the stop-attestation sha256 and the bundle hash; the three-session lag and causal
   ACK order are re-validated before reservation and before any request.
2. Corporate actions are reconciled globally across the audit, window and full-history acquisitions by the
   provider's stable action identity (type-scoped where the provider scopes ids by type); any difference in type,
   date, symbol or ratio for one identity is a conflict, and conflicts block the union of affected symbols.
3. No field (e.g. a processing/publication date) is treated as the economic effective date without a cited,
   pinned provider field contract, prepared with the collector review; unknown effective timing stays unresolved
   and is handled conservatively; no ad hoc window margin is claimed to prove completeness. Extra scopes or
   requests need prospective, bound plan approval.
4. Every raw page and derived file is hashed in its manifest and re-verified at each later stage (opening mode,
   score); a mismatch is an integrity failure.

## A8. Authorization and bootstrap (point 1, point 2)
1. Order: reviewed plan -> AUDIT-ACK -> metadata/calendar audit -> plan/audit-bound opening capture and seal ->
   opening-unit/receipt review -> START attestation -> exact-bundle RUN-ACK/prereg, all before planned START. The
   audit is metadata only. RUN-ACK binds the opening seal, the frozen opening books, the audit and the attestation.
   No silent reuse of an audit after its window, START or plan changes (the audit manifest binds plan_sha256).
2. Every stage verifies its ACK's identity, artifact bindings and causal timing (ACK after the bound artifact,
   before the stage; RUN-ACK before planned START; final acquisition no earlier than the third session close after
   the stop) BEFORE any live capture, request, or reservation. The opening mode verifies the AUDIT-ACK,
   plan/calendar/source bindings and slot/clock with no prereg prerequisite; normal checkpoints require a verified
   prereg and RUN-ACK. Invalid or fabricated authorization refuses with zero live callbacks.

## A9. Failure outcomes (point 3)
1. Every capture, receipt or process-observation exception is preserved in a report with the exception class and a
   sanitized reason (never secret-bearing text), and never seals.
2. A transient unavailable observation with no established integrity or semantic violation is a failed attempt
   under the frozen retry schedule. Missing required evidence never becomes a plausible match. An observed semantic
   mismatch, corrupt sealed evidence or other registered invalidity is terminal; restoration cannot erase it.
3. At final validation, unresolved required evidence gets its registered failure/provenance disposition before any
   priced work; a process-observation gap is not equated with an MR semantic change. Every non-numeric disposition
   is proven by spies to make no valuation call.

## A10. Tests, mutation evidence and review closure (point 8, A7 of rev 1, process)
1. Tests contradicting the aware-deadline and 08:00 rules are replaced; the old evidence is preserved and each old ->
   new expectation is listed with its rationale. Acceptance rules are tested before their fixes; revised
   implementation output is never the oracle.
2. Mutation evidence: a kill is meaningful only with the failing test's identity and intended assertion retained;
   collection/import/environment/harness failures are separated; a bundle/hash refusal is not a detection of an
   economic or gate mutant. The Cosmic Ray scope reduction is a scoped measurement, not adequacy; `_out`, `_seals`,
   `_sha_or_absent`, `_ack`, `_write_once` and report serialisation get source-bound semantic mutants. Code changed
   after the Cosmic Ray run gets fresh targeted evidence; old Cosmic Ray results are not rebound to new source.
3. A review-closure table is maintained: each blocking comment -> agreed requirement/example -> implementing source/
   test/evidence hashes -> disposition and reviewer response; unresolved rows stay visible; a passing test count
   does not close a row. The mailbox is read at every review handoff and gate move.
