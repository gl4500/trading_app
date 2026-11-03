# S1 design v5 — Addendum 3 (external trial journal, identity, trial states and stage commitments) — revision 5

Status: DRAFT for a scoped correction check of A3-R3C-1 and the two (a) plan-consistency notes only (operator
authorized 2026-11-02). Prospective: no S1 registration has occurred.

Changes from rev 4 (61542504…), answering Codex final 42d4ae8e. Every other rev-4 text is unchanged.
- **A3-R3C-1 (F4.6, F4.8):** the request policy and member list are replaced by one authoritative source table
  (F4.9), taken from the frozen collector at c9b4322 (s1_collect.py sha256 e00df0f9…, s1_common.py c6c5c508…,
  s1_run.py score writer). It adds the pinned paper-api calendar URL as a per-family exact URL (no host list is
  opened), the two final corporate-action families (window -> final/pages/, full history -> final/pages_full/) that
  feed reconciliation, and every named final and score member.
- **(a) note 1 (F0.5 step 4):** the step-4 conditions are made disjoint with an explicit sub-order, so no outcome
  depends on table order (for example SLOT-MISSED against a QUALIFIED slot).
- **(a) note 2 (F10):** the post-STOP LOST-RACE example is restricted to a new slot with no prior row.

Changes from rev 3 (ccdc48fa…), answering Codex final 4e6e0a1d. Every other rev-3 text Codex accepted is unchanged.
- **FINAL-1 (F1, F2.4, F4, F7.4, F10):** finalization follows the existing dependency graph:
  STOP -> stop_attest -> final_plan -> ACQUIRE-ACK (after the acquisition lag) -> final -> SCORE-ACK -> score.
  The STOP prefix is restricted to sampled history.
- **FINAL-2 (F0.2, F0.5, F4):** `owner` is split into `op` (the durable operation identity, fixed at INTENT) and
  `actor` (the appending process). A recovery takeover is defined only for CREATED and for finalizer terminal rows.
- **FINAL-3 (F4.1, F9):** the INTENT commits a deterministic request POLICY (F4.6), not a request list. PREPARED
  commits the actual request/response provenance.
- **Plan-level conditions (F0.7, F3, F4.7, F5.5):**
  - LOST-RACE never moves committed files;
  - one canonical PREPARED format, stored for recovery;
  - named manifest members;
  - an explicit precedence order for overlapping append rules;
  - lock I/O errors fail closed.

Builds on:
- Addendum 1 rev 3 (6cb89e36840975b8d949ec85debf9d2cedbe45bbeb9dcb374d91343dddc5e590);
- Addendum 2 rev 1 (c7f0c3ffcd886b0f308c5f09bc0bfaca9977f8edae596bf51b30e28cb9ae3266).

Both stay byte-identical, and where this addendum differs from them, this addendum governs. Its sha256 joins the
registered bundle (A3.1).

History:
- Rev 0 78815b7b…, rev 1 0fdf7d9f… and rev 2 db453cac… are kept unchanged.
- Codex reviews: 4c4065c3, 9486480b and 7da278b2 (records under s1_addendum3_r2_codex_review_20261031).

Operator decisions:
- 2026-10-29: the S1 runner gets append-only mailbox access.
- 2026-10-31: the forum is reopened, and the uncommitted-detection residual (F8.1) is accepted.

Changes from rev 2, answering the Codex round-1 challenges:
- F1: explicit trial states ACTIVE / STOPPED / INVALID / CLOSED, with a transition table. STOPPED permits the
  bounded finalization chain (CH1).
- F0.5 and F3: a losing terminal append for an existing attempt is a no-row lost race, not invalidity. A finalizer
  carries its own owner (CH2).
- F4: stages split into INTENT (input envelope) -> PREPARED (exact output) -> CREATED. Real timestamps are kept, and
  the single-file vs tree artifacts are declared (CH3).
- F8.1: the overclaim "no result differs" is removed and the residual is rescoped (CH4).
- F5: lock semantics, per Codex answer (iii).

## Trust assumption (ruling 6, extended)
The coordination mailbox (C:/Users/gl450/.coordination/trading_app/mailbox.sqlite3) is the external authorization and
history root. This is a prospective, operator-approved assumption for an honest, reviewed, bundle-pinned runner.

It is NOT:
- proof of enforced append-only access;
- authentication;
- resistance to a compromised runner;
- protection against arbitrary edits to the mailbox file.

S1 writes rows to the same SQLite file that stores reviewer ACKs. No mailbox permission change is made by this
addendum. The threat addressed is loss, deletion or replacement of files under s1_out or of the bundle copy.

## F0. S1 journal
1. **Writer.** One bundle module, s1_journal.py. Its only mailbox write is a single-row INSERT inside `BEGIN IMMEDIATE`:
   sender `s1`, recipient `codex`, key `experiments-s1-journal`. Inside that transaction it re-reads the trial's rows
   and applies F0.5 to the state it reads there, never to an earlier read. It makes no UPDATE, DELETE or ack and uses
   no other role. All other reads are mode=ro. mailbox.py is unchanged.
2. **Canonical bytes (frozen).** The message body is exactly one line of UTF-8 with no trailing newline:
   `S1-JOURNAL trial_id=<uuid4> seq=<n> prev_sha256=<64hex> kind=<K> subject=<s> detail_sha256=<64hex|absent> op=<32hex> actor=<32hex> at=<YYYY-MM-DDTHH:MM:SS.ffffff+00:00>`
   - Fields appear in this order, single-spaced.
   - line_sha256 = sha256 of those bytes.
   - prev_sha256 is the previous row's line_sha256. For seq 1 it is the sha256 of the AUDIT-ACK token line
     (UTF-8, no newline).
   - `at` is the writer's UTC clock read immediately before the INSERT. One exception: for SLOT-QUALIFIED, `at` = R
     (F3).
   - `op` is the durable operation identity: a random nonce fixed by the row that opens the operation (SLOT-INTENT,
     STAGE-INTENT, or a finalizer's own SLOT-MISSED or TRIAL-STOP). Every later row of that operation repeats it.
   - `actor` is the nonce of the process appending this row. actor ≠ the opening row's actor marks a recovery, so
     the recovery's provenance is in the journal itself.
   - A recovery actor may append a row for someone else's op only in the cases F0.5 allows: STAGE-CREATED after
     PREPARED, and the finalizer's SLOT-TIMEOUT. In both cases it must hold the op's ownership lock (F5) and
     re-validate under it. It never appends PREPARED, QUALIFIED or FAILED for another actor's op, so it never redoes
     work or changes prepared bytes.
   - No artifact ever contains the `at` of a row that commits that artifact's hash, so there is no circularity.
3. **Kinds:**
   - Slot rows: SLOT-INTENT, SLOT-QUALIFIED, SLOT-FAILED, SLOT-TIMEOUT, SLOT-MISSED.
   - Stage rows: STAGE-INTENT, STAGE-PREPARED, STAGE-CREATED.
   - Trial rows: TRIAL-STOP, TRIAL-INVALID.
4. **Detail composition (frozen).**
   - Every detail is the sha256 of canonical bytes the writer holds in memory. It is never a hash re-read from a
     replaceable disk file.
   - The canonical form is c.canonical: sorted keys, compact separators, UTF-8.
   - Exact per-kind contents are in F3 (slots) and F4 (stages).
5. **Append rules**, applied to the state re-read inside the transaction. Each attempt has exactly one of three
   outcomes:
   - **APPEND** — the row is written.
   - **LOST-RACE** — no row is written. The caller stops, with no work and no seal. It moves to `late/` only its OWN
     uncommitted files: those carrying its actor nonce and not listed in any committed manifest. It never touches a
     file a committed row requires, and it then re-checks the winner's committed evidence (F3). `late/` is preserved
     and never selectable. This is not invalidity.
   - **INVALIDATE** — instead of the requested row, a TRIAL-INVALID row with the stated reason is appended in the same
     transaction.

   **Precedence (explicit; table row order never decides).** Evaluate these steps in order. The first step that
   decides an outcome wins.
   1. **Chain integrity:** a gap, fork, duplicate seq or bad format means refuse with no row, and escalate.
   2. **CLOSED:** refuse with no row, for every kind including TRIAL-INVALID.
   3. **INVALID:** TRIAL-INVALID gives APPEND (an extra observation; the first row is the reason). Every other kind
      gives LOST-RACE with no work.
   4. **Subject identity and contradiction checks:** step 4 of the table.
   5. **Trial-state permission (F1):** step 5.
   6. **Timing (E, D, R):** step 6.
   7. Otherwise APPEND.

   **Step-4 sub-order (rev 5).** Within step 4, the checks for one requested row are made in the sub-order 4a, 4b,
   4c, 4d below, and the first that applies decides. The conditions at one sub-step are disjoint, so no outcome
   depends on the order of table rows:
   - **4a identity:** the row's op or actor contradicts the subject's INTENT (or there is no INTENT where one is
     required) -> INVALIDATE. This is checked before terminal state, so a foreign completion stays invalid on a
     terminal subject.
   - **4b repeat:** a second opening row for a subject that already has one -> INVALIDATE.
   - **4c already decided:** the subject already has the terminal or identical row -> LOST-RACE (stale), or
     INVALIDATE where the details differ.
   - **4d in-flight conflict:** the subject has an INTENT and no terminal row, and the row may not decide it -> refuse
     with no row.

   | step | requested row | condition | outcome |
   |---|---|---|---|
   | 4a | SLOT-QUALIFIED / SLOT-FAILED s | no INTENT for s; or op ≠ the INTENT's op; or actor ≠ the INTENT's actor | INVALIDATE (contradictory-completion), whether or not s is terminal |
   | 4a | SLOT-TIMEOUT s | no INTENT for s, or op ≠ the INTENT's op | INVALIDATE (contradictory-finalizer), whether or not s is terminal |
   | 4a | STAGE-PREPARED g | no INTENT; op ≠ the INTENT's op; or actor ≠ the INTENT's actor | INVALIDATE (contradictory-stage) |
   | 4a | STAGE-CREATED g | no PREPARED; or op ≠ the INTENT's op | INVALIDATE (contradictory-stage) |
   | 4b | SLOT-INTENT s | s already has any row | INVALIDATE (repeat-attempt), also when STOPPED |
   | 4b | STAGE-INTENT g | g already has an INTENT | INVALIDATE (repeat-stage) |
   | 4c | SLOT-QUALIFIED / SLOT-FAILED s | s already terminal (identity passed 4a) | LOST-RACE (a stale completion) |
   | 4c | SLOT-TIMEOUT s | s already terminal (identity passed 4a) | LOST-RACE (a stale finalizer) |
   | 4c | SLOT-MISSED s | s already terminal (QUALIFIED, FAILED, TIMEOUT or MISSED) | LOST-RACE (a stale finalizer) |
   | 4c | STAGE-PREPARED g | PREPARED exists: same detail -> LOST-RACE (idempotent); different detail -> INVALIDATE (contradictory-stage) | as stated |
   | 4c | STAGE-CREATED g | detail ≠ the PREPARED detail -> INVALIDATE (contradictory-stage); otherwise CREATED exists: same detail -> LOST-RACE (idempotent recovery), different detail -> INVALIDATE | as stated |
   | 4d | SLOT-MISSED s | s has an INTENT and no terminal row | refuse with no row; the finalizer re-evaluates for a TIMEOUT |
   | 4c | TRIAL-STOP | already STOPPED | identical detail: LOST-RACE; different detail: INVALIDATE (stop-conflict) |
   | 5 | SLOT-INTENT s | STOPPED | LOST-RACE (no capture after the stop, not invalid: a scheduler may still fire) |
   | 5 | STAGE-INTENT g | F1 forbids g in this state, or g's predecessor stage or ACK is missing | refuse with no row and no work (not invalid) |
   | 5 | TRIAL-STOP | the stop rule isn't met by committed history | refuse with no row |
   | 6 | SLOT-INTENT s | now >= E(s) | refuse with no row; the finalizer appends MISSED |
   | 6 | SLOT-QUALIFIED s | R >= D | refuse with no row (a late R); the finalizer later appends TIMEOUT |
   | 6 | SLOT-TIMEOUT s | now < D(s) | refuse with no row (a premature finalizer) |
   | 6 | SLOT-MISSED s | now < E(s) | refuse with no row (a premature finalizer) |

   **Who may append each row:**
   - SLOT-INTENT and STAGE-INTENT open an op, with actor = that op's actor.
   - QUALIFIED, FAILED and PREPARED require the opening actor. The work is never taken over.
   - SLOT-TIMEOUT carries the slot INTENT's op with the finalizer's own actor (the recovery provenance).
   - SLOT-MISSED and TRIAL-STOP open their own op.
   - STAGE-CREATED may be appended by the opening actor, or by a recovery actor holding the op lock (F5) after it has
     verified that the published bytes equal the PREPARED commitment (F4.7).

7. **Exceptions in a finalizer or recovery path** never append a row by default. Unexpected errors fail closed:
   refuse with no row.

6. **Authority.**
   - The journal decides trial, slot and stage state. Local files are evidence, judged by F3 and F4.
   - Before any callback, capture, provider request or pricing, every gate first reads: the open trial (F6), its
     state (F1) and the bundle (F6.4).
   - INVALID is irreversible. Restoring files and deleting aborted.json never resumes.

## F1. Trial states and transitions (CH1)
The state is derived from the open trial's rows:
- **ACTIVE:** no TRIAL-STOP and no TRIAL-INVALID.
- **STOPPED:** a TRIAL-STOP row exists and no TRIAL-INVALID.
- **INVALID:** any TRIAL-INVALID row, whether or not a stop exists.
- **CLOSED:** an authorization status (F7.5), layered on top of the other three.

| action | ACTIVE | STOPPED | INVALID | CLOSED |
|---|---|---|---|---|
| SLOT-INTENT (new capture) | allowed (stage gates and ACKs apply) | LOST-RACE, no capture | no work | refused |
| completing an in-flight slot that started before the stop | allowed | allowed only if its INTENT seq < the STOP seq; it can never become a seal or a stop input | no work | refused |
| new seal | allowed (F3) | forbidden | forbidden | refused |
| finalization chain (below), each stage once, in dependency order | forbidden (no STOP) | allowed; each binds the STOP row | forbidden; no numeric work | refused |
| re-entry of any command | follows its gate | follows its gate | refused, no work | refused |
| TRIAL-INVALID | allowed | allowed | allowed (extra observation) | refused |

**Finalization dependency graph (FINAL-1).** This keeps the existing bindings: Addendum 1 acquisition bindings,
s1_collect.write_final_plan and do_final.
1. TRIAL-STOP, plus stop.json (F2).
2. stop_attest (s1_run.attest_stop), binding the STOP row and stop.json.
3. final_plan (s1_collect.write_final_plan). It requires the stop attestation first, as the code does now.
4. **ACQUIRE-ACK.** It is created strictly after the stop attestation and binds collector, final_plan, prereg, the
   stop attestation, the bundle, plus trial_id, prev, journal seq/head and stop_line_sha256. It is placed no earlier
   than the existing acquisition lag (the 3rd session after the stop, `_earliest_acquire`).
5. final (s1_collect.do_final), the historical valuation acquisition under the ACQUIRE-ACK.
6. **SCORE-ACK.** It binds runner, the final manifest, the stop attestation and the bundle, plus trial_id, prev,
   journal seq/head and stop_line_sha256.
7. score.

No provider call happens before steps 2 and 4. Each stage's STAGE-INTENT is refused (with no row) until its
predecessor's CREATED row and any required ACK exist. Any other order needs a separate operator-approved amendment
with revised exact bindings.

**STOP prefix (FINAL-1).** The frozen sampled history is the sampled ledger: slot terminal rows, seals, captures and
the stop-trigger history committed at or before the STOP seq. Slot terminals committed after the STOP are preserved
but never enter the sampled history used by stop_attest, final_plan, final or score. The post-stop finalization
artifacts themselves (the attestation, plans, ACKs, the historical-price acquisition and the score) are created
after the STOP and are the bounded finalization the STOPPED state allows. Authorized post-stop historical prices are
usable for valuation.

## F2. Stop record (CH1)
1. When a checkpoint's committed history meets the stop rule (100 fully sold MR lots, or 6 months), it builds the stop
   record in memory. The record is a pure function of committed history:
   - the rule;
   - the triggering slot;
   - that slot's terminal row seq and line_sha256;
   - `determined_utc`, equal to that terminal row's `at`;
   - the lot counts from committed slot evidence.
2. It appends TRIAL-STOP with detail = sha256 of the record, then publishes `stop.json`.
3. **Publication gap.** TRIAL-STOP is committed but stop.json is absent or not yet durable. This is a recoverable
   pending state, not a deletion. Recovery recomputes the record from committed history: matching bytes are
   published, and anything else is INVALIDATE (stop-conflict).
4. Once a finalization stage's INTENT exists, stop.json is required evidence. Missing, changed or unparseable means
   INVALID, and restoring it does not resume.
5. The STOP's timestamp and outcome are fixed by the journal and can't be replaced.

## F3. Slots: evidence table and the deadline (CH2; S1-T12-1; B1.3 unchanged)
Events for each slot:
- **P:** the report, resolution and capture are durably published.
- **R:** a same-process clock reading after P.
- **J:** the commit of SLOT-QUALIFIED.
- **T:** the commit of SLOT-TIMEOUT.

The rows for a slot:
- SLOT-QUALIFIED requires R < D (F0.5). Its `at` = R. Its detail = sha256(canonical tree manifest {relpath: sha256} of
  the slot's report, resolution and capture files, from the bytes the worker wrote).
- The first terminal row wins. A loser ends in LOST-RACE: its files go to `late/`, it causes no INVALID, and it is
  never selectable.
- A crash after P without J ends in TIMEOUT at D. The finalizer appends it with the slot's op and its own actor.
- A restarted process never appends QUALIFIED or FAILED for an earlier op (F0.5 step 4 makes that INVALIDATE), never
  reuses an earlier R, and never opens a second INTENT for the slot. The slot ends at D as TIMEOUT.

| slot state from the journal | required local evidence | tolerated | violation (INVALIDATE, reason registration artifact) |
|---|---|---|---|
| no row | none | none | any claim, capture, report or resolution for s |
| INTENT, no terminal (in flight) | none | partial files carrying the INTENT's op and actor | a file carrying another op |
| QUALIFIED | the files of the tree manifest, matching detail | `late/` | a required file missing, changed or unparseable |
| FAILED | claim and failure report matching detail | partial capture, `late/` | as above |
| TIMEOUT | none | whatever the worker left, moved to `late/` | a seal citing s |
| MISSED | none | none | any file for s outside `late/` |

The opening seal is a stage (F4). Its INTENT may be appended only after the chosen slot's QUALIFIED row exists, the
chosen slot is the first QUALIFIED one in schedule order, and every earlier scheduled slot is terminal.

## F4. Stages: INTENT -> PREPARED -> CREATED (CH3)
1. **STAGE-INTENT g:** appended before any external request or computation for g.
   - detail = sha256(c.canonical(input envelope)). The envelope is:
     {"trial_id", "stage", "inputs": {name: sha256} for every bound input artifact (named per stage, F4.8),
     "acks": {kind: line_sha256}, "request_policy": the F4.6 policy object, or null for a stage with no provider}.
   - It commits what g is allowed to do, not its output.
2. **Work:** provider requests or computation, within the request policy. Child files are written to the staging
   area `<root>/s1_staging/<trial_id>/<stage>/`, outside s1_out.
3. **STAGE-PREPARED g:** detail = sha256(c.canonical(output commitment)). The output commitment has one canonical
   format for all stages:
   `{"trial_id", "stage", "op", "kind": "single"|"tree", "members": {relpath: sha256}, "provenance": [...]}`.
   - A single-file stage has exactly one member.
   - A tree stage lists every member named in F4.8.
   - provenance is the actual request/response record for provider-backed stages (F4.6), and [] otherwise.
   - The commitment bytes are also written as `<staging>/prepared.json` before the PREPARED append, so recovery has
     them. They are never trusted on their own: they must hash to the PREPARED detail.
   - PREPARED is appended after the work and before publication into s1_out.
4. **Publication** of the staged members into s1_out (exclusive), then **STAGE-CREATED g**, whose detail equals the
   PREPARED detail.
5. **Timestamps keep their real values.** The artifact records intent_at (the INTENT's `at`), its own observation
   times (for example calendar_source.retrieved_utc, read after the request as now), and prepared_at, which is
   recorded only in the PREPARED row, never inside the artifact.
6. **Request policy (FINAL-3).** For provider-backed stages, the INTENT commits a deterministic policy, not a request
   list. It doesn't prefetch, and it never treats an unlisted request as authorized.

   **Policy object (rev 5):**
   ```
   {"redirects": false,
    "max_pages": MAX_PAGES (200),
    "cutoff": the New York date of the INTENT row's `at` (used as every CA `end`; never re-read from the clock),
    "families": [{"name", "url" (exact, scheme+host+path, no query), "scope", "batches": [[symbol, ...], ...] | null,
                  "base_params" (exact, per batch where batched), "paged": bool, "page_template"}]}
   ```
   There is no free host list. A request is authorized only if its URL equals the exact `url` of a family in the
   policy; the authorized hosts are exactly the hosts of those URLs. So paper-api.alpaca.markets is authorized only
   for the pinned calendar URL, and any other path on it is refused. The families, base parameters, batches and
   page names are those of the F4.9 source table, and nothing else.

   **Request order** is the collector's order: audit = calendar, then CA batches in ascending batch index; final =
   bars, then the window CA batches, then the full-history CA batches. An empty symbol list has zero batches and sends
   no request.

   **Pagination.** Page n+1's only extra parameter is `page_token` = the `next_page_token` of page n of the same
   family and scope, taken from the immediately preceding response that passed validation. A family ends when a
   page has no token.

   **Refusals.** Each of these is a Structural refusal: a repeated token, more than max_pages pages, a redirect, a new
   host, a URL or base parameter outside the policy, or a request with no family. They are enforced in the request
   path (`_get` and `_paged`) before the request is sent. No hidden or extra request exists: every request sent is
   recorded in provenance.

   **Provenance**, recorded in PREPARED, for each request in the order sent:
   `{"family", "scope", "n", "url", "params" (credential-free), "page_token_from": the previous page's relpath|null,
   "retrieved_utc", "status", "page_relpath", "page_sha256"}`.

   **A provider anomaly** (Structural, or a validation failure) ends the attempt. Its staged pages and an ABORTED
   record are kept as evidence, and no PREPARED row is appended. Each stage has exactly one INTENT, so the trial
   becomes INVALID (reason provider-structural).
   - This matches the frozen collector's existing one-attempt rule: `_reserve` says "one attempt only", and an
     ABORTED manifest is preserved.
   - This is a disclosed availability cost, especially for `final`, which comes after the stop.
   - A retry design (for example a FAILED-stage row plus a fresh, separately authorized ACK) would need a separate,
     operator-approved amendment. It is not part of this revision.
7. **Recovery (FINAL-2).** When PREPARED exists, CREATED doesn't, and no lock holder is live, a recovery actor:
   - takes the op lock (F5);
   - re-reads the journal under the lock;
   - loads `<staging>/prepared.json` and checks that it hashes to the PREPARED detail;
   - checks every member, in staging or already in s1_out, against its committed sha256;
   - publishes only the missing members, from staging, with matching bytes;
   - appends CREATED with the stage's op and its own actor.

   Any absent or mismatched byte is INVALIDATE (stage-replaced). Recovery never re-requests, recomputes or changes
   the prepared bytes. A foreign op, a missing PREPARED, or a detail mismatch is INVALIDATE (contradictory-stage).
8. **Named members and inputs.** All are in dependency order, and every member is listed by relpath in the PREPARED
   commitment, with no wildcard left to inference.

| stage | kind | members (relpaths under s1_out) | bound inputs in the INTENT envelope |
|---|---|---|---|
| audit | tree | exactly the audit members of F4.9 | plan.json, the AUDIT-ACK line, bundle |
| opening (seal) | single | seals/<close>.json | plan, audit manifest, the selected slot's QUALIFIED line and tree manifest, opening_receipt.json |
| start_attest | single | attest_start.json | plan, audit manifest, opening seal, opening receipt, OPENING-ACK line |
| prereg | single | prereg.json | attest_start.json, the RUN-ACK line, receipt |
| stop_attest | single | attest_stop.json | the TRIAL-STOP line, stop.json |
| final_plan | single | final_plan.json | stop.json, attest_stop.json, prereg.json, plan |
| final | tree | exactly the final members of F4.9 | final_plan.json, the ACQUIRE-ACK line, prereg.json, attest_stop.json |
| score | tree | exactly the score members of F4.9 | final manifest, attest_stop.json, the SCORE-ACK line, the sampled-history manifest up to the STOP seq |

Semantic receipts and input snapshots are covered either as named members or as exact hashes in the envelope. They
are never covered by an unspecified "every child".

9. **Source table (rev 5, A3-R3C-1).** This table is authoritative for every provider-backed stage and the score.
   It is taken from the frozen code at c9b4322 (s1_collect.py e00df0f9…: `_get`, `_paged`, `_corporate_actions`,
   `do_audit`, `do_final`, `_run_attempt`; s1_common.py c6c5c508…: `CAL_URL`; s1_run.py: `score`). Notation:
   `CA_FIXED` = {"region": "us", "data_quality": "all", "sort": "asc", "limit": 1000}; batch i = symbols[50i : 50i+50]
   of the named list in its stored order; `{i:03d}` and `{n:03d}` are the zero-padded batch and page indexes;
   `cutoff` is the policy's cutoff (F4.6).

   **Requests (families):**

   | stage | family / scope | exact url | exact base params (page n>0 adds only page_token) | paged | raw page member (under s1_out) |
   |---|---|---|---|---|---|
   | audit | calendar | https://paper-api.alpaca.markets/v2/calendar (c.CAL_URL) | {"start": plan.calendar_range[0], "end": plan.calendar_range[1], "date_type": "TRADING"} | no: exactly one request, no page_token | audit/pages/calendar.json |
   | audit | corporate_actions / audit | https://data.alpaca.markets/v1/corporate-actions | per batch i of plan.ca_symbols: CA_FIXED + {"symbols": ",".join(batch i), "start": plan.ca_range[0], "end": cutoff} | yes | audit/pages/ca_{i:03d}_page{n:03d}.json |
   | final | bars | https://data.alpaca.markets/v2/stocks/bars | {"symbols": ",".join(final_plan.bar_symbols), "timeframe": "1Day", "start": UTC-Z of New York 00:00 on the New York date of prereg.start, "end": UTC-Z (microseconds) of New York 00:00 on stop_date+1 minus 1µs, "adjustment": "raw", "feed": "sip", "limit": 10000} | yes | final/pages/bars_page{n:03d}.json |
   | final | corporate_actions / window | https://data.alpaca.markets/v1/corporate-actions | per batch i of final_plan.ca_symbols_window: CA_FIXED + {"symbols": ",".join(batch i), "start": New York date of prereg.start, "end": cutoff} | yes | final/pages/ca_{i:03d}_page{n:03d}.json |
   | final | corporate_actions / full_history | https://data.alpaca.markets/v1/corporate-actions | per batch i of final_plan.ca_symbols_full_history: CA_FIXED + {"symbols": ",".join(batch i), "start": final_plan.full_history_start, "end": cutoff} | yes | final/pages_full/ca_{i:03d}_page{n:03d}.json |
   | score | none (request_policy null) | — | — | — | — |

   Both final CA families are required: their results are reconciled into one global set (`reconcile_actions`,
   A7.2), and neither may be dropped or merged into the other's scope.

   **Members.** The raw page members of a stage are exactly the `page_relpath` values of its provenance, one per
   request sent, and every page member has exactly one provenance entry. The other members are fixed names:

   | stage | fixed members (under s1_out) | derived from |
   |---|---|---|
   | audit | audit/attempt.json, audit/calendar_source.json, audit/calendar.json, audit/corporate_actions.json, audit/ca_problems.json, audit/manifest.json | the reservation; the calendar page and its request; the calendar page; the classified CA pages; the same; all of the above |
   | final | final/attempt.json, final/bars.json, final/bar_problems.json, final/corporate_actions.json, final/ca_problems.json, final/manifest.json | the reservation; the bars pages; the same; reconciliation of the window and full-history CA pages; window and full-history CA problems plus the reconciliation conflicts; all of the above |
   | score | score/attempt.json, score/s1.json | the reservation; the score computation over the bound inputs |

   **Consistency.** The stage manifest's `files` and `pages` maps must equal the PREPARED members (excluding
   manifest.json itself from `files`), byte hash for byte hash. A member that is absent, changed or unparseable, a
   page with no provenance entry, or a provenance entry with no page is INVALIDATE (stage-replaced). It is checked
   before any valuation or scoring that reads the stage.

   **Score abort.** A score computation error ends the attempt the same way as a provider anomaly (F4.6): the ABORTED
   score/s1.json stays in staging as evidence, no PREPARED row is appended, and the trial becomes INVALID (reason
   score-aborted). This matches the frozen one-attempt score rule (its ABORTED report has verdict ABORTED-INVALID).

   **Collector change disclosed.** The frozen collector reads `cutoff` from the clock after the reservation. Under
   this addendum it is the policy cutoff fixed at INTENT. The two differ only if New York midnight passes between the
   INTENT and the reservation; the INTENT value governs and is recorded in the manifest's publication_cutoff.

   **Found while building the table (outside the authorized scope; flagged for a ruling, not decided here).** The
   prereg BLOCKED path (s1_run.py, before the RUN-ACK) writes s1_out/blocked.json and tells the operator to
   re-register. It has no stage row, so under the F4 stage-state table (no INTENT) it would read as a violation after
   the AUDIT-ACK. Proposed handling, for Codex to accept or defer: the BLOCKED outcome appends TRIAL-INVALID (reason
   pre-start-blocked), and blocked.json is evidence on an INVALID trial. This changes no outcome, since BLOCKED already
   ends the trial.

Stage states and evidence:

| journal state of stage g | handling |
|---|---|
| no INTENT | any artifact for g is a violation after the AUDIT-ACK, or a refusal before it |
| INTENT, no PREPARED, op lock held (F5) | pending: gates refuse with no work; staging children are tolerated |
| INTENT, no PREPARED, op lock acquirable | INVALIDATE (stage-incomplete). There is no refetch or recomputation: this is the conservative availability cost (Codex answer (ii)) |
| PREPARED, no CREATED, op lock held | pending |
| PREPARED, no CREATED, op lock acquirable | recovery per F4.7. Absent or different bytes: INVALIDATE (stage-replaced) |
| CREATED | every committed child is required and must match. Missing, changed or unparseable means INVALIDATE |

Two failure cases:
- **Pre-intent outage.** The INTENT append fails, so nothing happens: no request, no artifact, a refusal.
- **Completion-append failure.** PREPARED or CREATED fails after work: the evidence is kept and no next stage runs.
  Recovery resolves it under the table, with no duplicate work and no claim that the artifact is absent.

## F5. Ownership locks (Codex answer (iii))
1. Each slot, stage and stop operation takes an ownership lock BEFORE reading the journal state it acts on. It holds
   the lock across the transition: read, then work, then append. It re-validates trial, slot or stage, and its op,
   under the lock. There is no check-then-act liveness query.
2. The lock file lives at `<root>/s1_locks/<trial_id>/<slot|stage>.lock`, outside s1_out.
   - On Windows it is opened with a share mode that excludes FILE_SHARE_DELETE and FILE_SHARE_WRITE, and is
     byte-range locked (msvcrt.locking). So while it is held it can't be deleted, renamed or replaced.
   - The OS releases it when the process ends.
   - "Live owner" means the lock can't be acquired. A leftover lock file that can be acquired means there is no live
     owner. There is no PID inference.
3. If the lock file is deleted while not held, the next owner recreates it, and the journal decides the state.
   Deleting the lock is never evidence by itself.
4. Implementation tests use isolated processes, real crashes (killed child processes) and concurrent recovery, not a
   mocked live flag.
5. Lock acquisition has exactly three classified results:
   - acquired;
   - held by another process: a sharing or lock violation, the specific Windows errors;
   - error: any other I/O or permission error.
   An error fails closed: refuse with no row, and never treat it as "live" or "dead". Liveness is decided only by the
   first two results.

## F6. External trial identity (S1-T12-4; rulings 2, 4)
1. **Common ACK fields.** Every Codex S1 ACK is one standalone token line with exactly the listed fields, in order:
   - sender `codex`, recipient `claude`, key `experiments-prereg`;
   - `trial_id=<uuid4>` and `bundle_sha256=`;
   - `prev=<mailbox id of the causal-predecessor ACK>` (not on the AUDIT-ACK);
   - `created` strictly after the predecessor's, and after any journal row it references.
2. **trial_id is fixed at write_plan.** write_plan generates a uuid4 and records it in plan.json. The AUDIT-ACK
   carries the same trial_id and binds plan_sha256. Before issuing, Codex checks the id against every earlier
   AUDIT-ACK. A trial_id on more than one AUDIT-ACK refuses every trial with that id. plan.json never changes after
   the AUDIT-ACK. Every generated artifact records trial_id and is validated against it.
3. **Open trial:** the unique trial_id whose AUDIT-ACK has no valid CLOSE-ACK. It is found from the mailbox only.
   - Exactly one open trial is the positive case, and the stage gates then apply.
   - Zero open trials: trial-bound commands refuse.
   - Two or more: refuse and escalate.
   - Mailbox unreadable: outage refusal.
4. **Expected bundle:** the open trial's AUDIT-ACK bundle, compared first (A3.2).
   - A mismatch after any journal row means INVALIDATE (bundle) and a local abort, whatever state the bootstrap files
     are in.
   - A mismatch before any row is a refusal.
5. **Other trials.** An ACK or row of another trial never counts for the open trial, even with the same bundle.
6. **Total loss** of s1_out under an open trial: INVALIDATE (LOST). Restoring the files stays invalid. The operator
   closes the trial (CLOSE reason LOST). It is never a fresh trial or a reseal.

## F7. Codex ACKs and the issuance checklist
1. **Chain:** AUDIT <- OPENING <- RUN <- PREREG <- ACQUIRE <- SCORE, with CLOSE able to follow any of them.
   - At most one ACK of each kind per trial.
   - A second ACK of the same kind, byte-identical duplicates included, refuses all trial-bound commands and
     escalates.
   - An ACK with a broken prev, trial or bundle chain is refused.
   - Every ACK after the AUDIT-ACK carries `journal_seq` and `journal_head_sha256`. The S1 code checks that the
     journal extends that head without a fork.
2. **S1-OPENING-ACK** `trial_id bundle_sha256 prev plan_sha256 audit_manifest_sha256 opening_slot opening_seal_sha256
   opening_receipt_sha256 journal_seq journal_head_sha256 evidence_manifest_sha256`.
   Issuance checklist, run against one frozen snapshot:
   - a. Copy, into the review folder, all evidence that F3 and F4 require for every row up to journal_seq, plus the
     plan and the audit tree. Hash each file into an evidence manifest, whose sha256 goes in the ACK.
   - b. Every scheduled opening-day slot has a terminal row, in order. An in-flight slot blocks issuance. Earlier
     FAILED, TIMEOUT or MISSED slots are legitimate.
   - c. opening_slot is the first QUALIFIED slot. The opening stage's PREPARED and CREATED rows commit the seal, and
     the local seal and receipt match.
   - d. The trial is ACTIVE, and F3 and F4 hold for every row.
   - e. After issuing, Codex re-hashes the snapshot. This proves snapshot integrity only. A change is reported, and
     the trial is closed (INVALID).
3. **Live-file check (decisive).** At every stage callback after the OPENING-ACK, the S1 code checks the live files
   against F3 and F4 and the evidence manifest entries, and checks the journal head. A difference means INVALIDATE
   and an abort. Both checks are kept.
4. **Deadlines.**
   - OPENING-ACK by the START-attestation lead. Otherwise there is no START, and the trial closes (reason
     OPENING-UNACKED). There is no automatic ACK and no later-slot substitution.
   - RUN-ACK (existing binds plus trial_id, prev and journal seq/head) is required for prereg.
   - **S1-PREREG-ACK** `trial_id bundle_sha256 prev prereg_sha256 journal_seq journal_head_sha256` is required before
     any post-START capture.
   - ACQUIRE-ACK and SCORE-ACK each gain trial_id, prev, journal seq/head and `stop_line_sha256`.
5. **S1-CLOSE-ACK** `trial_id bundle_sha256 prev reason=<SCORED|ABORTED|LOST|OPENING-UNACKED|INVALID|WITHDRAWN> evidence_sha256=<h>`.
   - evidence_sha256 is the hash of the score record, the first TRIAL-INVALID line, or the operator withdrawal
     message.
   - CLOSE is refused, so the trial stays open and commands refuse, if: its prev is not the latest ACK; it comes
     before the AUDIT-ACK; its role or key is wrong; its bundle differs; or it is a duplicate.
   - Closure never erases invalidity and never makes ACKs or the journal reusable.

## F8. Residuals
1. **Uncommitted detection (accepted by the operator 2026-10-31; rescoped per CH4).**
   - Scope: an integrity violation observed while the journal can't be written, or by a process that ends before its
     TRIAL-INVALID commits, has no external record.
   - The observing command starts no NEW capture, provider request or pricing after detection. It doesn't undo work
     the same command already did before that integrity check.
   - It tries to write local aborted.json and evidence. An abrupt crash may leave neither.
   - If committed history is later restored byte-for-byte and any local witnesses are deleted, the trial can resume.
   - Tamper evidence can then be lost. The resumed run can differ from an uninterrupted run: refusals, missed slots,
     timeouts, availability. No guarantee is offered for an observation that never committed.
   - The residual NEVER covers loss or bypass of any committed row (INTENT, PREPARED, CREATED, terminal, STOP or
     INVALID). A TRIAL-INVALID committed before a crash keeps the same restoration invalid.
2. **Trust in the mailbox:** see the trust assumption.
3. **Journal availability:** an outage blocks intents and can lose the opening or the trial. It fails closed: never a
   retry under the same intent, an implicit ACK or a different slot.
4. **Stage-incomplete:** a crash between INTENT and PREPARED terminates the trial (conservative).
5. **Provider anomaly:** a structural provider failure in audit or final makes the trial INVALID, with no retry
   (F4.6). For `final` this means a whole trial can be lost after its stop. A retry design is out of scope.
6. **Codex's issuance checks are procedural.**
7. **R-3** (live scheduler timing) stays OPEN.

## F9. Commands allowed before the AUDIT-ACK
- Only write_plan runs without an open trial. It writes plan.json, with the trial_id, locally. It makes no provider
  request, no live callback, no journal write and no priced work.
- do_audit runs after the AUDIT-ACK as stage `audit` (F4). Its INTENT envelope commits the F4.6 audit request policy (the calendar and corporate_actions families).
- After the AUDIT-ACK, write_plan refuses for the open trial.

## F10. Acceptance examples (before code; behavioural REDs; spies for zero callbacks, captures, provider requests and valuation)
**Codex probes:**
- The original test_codex_publication.py and its XML are frozen as historical evidence. Its positive diagnostic
  assertions (a seal at D and D+1µs) are historical observations, not requirements.
- New test file, with an old -> new map and synthetic journal fixtures:
  - D-1µs qualifies when no TIMEOUT has committed first;
  - D and D+1µs do not seal;
  - a before-D positive control;
  - the P/R/J/T races.
- Intended old behavioural failures are recorded separately from fixture or setup incompatibilities.
- V1 and the "A fully deleted, then B" example: INVALID, or B never ACK-eligible.
- test_codex_combined_damage.py, adapted with the map: INVALID (bundle) after any journal row.
- Prereg restoration: invalid once its CREATED row exists. Before CREATED, it follows the F4 table.

**CH1 (stop):**
- A normal lot-count stop and a normal six-month stop each reach a numeric score with no INVALID row. They go through
  stop_attest -> final_plan -> ACQUIRE-ACK (no earlier than the 3rd session after the stop) -> final -> SCORE-ACK ->
  score, with valid prev chains (FINAL-1).
- No provider call happens before stop_attest and the ACQUIRE-ACK. final_plan before stop_attest refuses with no row.
- A post-STOP sampled slot is excluded from the sampled history, while authorized post-stop historical prices are
  used for valuation.
- After the STOP, a SLOT-INTENT for a NEW slot with no prior row gives LOST-RACE with no capture, and a new seal
  is forbidden. (A SLOT-INTENT for a slot that already has a row is INVALID (repeat-attempt) at step 4b.)
- An in-flight slot started before the stop completes but never enters final or score.
- The stop.json publication gap recovers. Deleting stop.json after a finalization INTENT gives INVALID, and
  restoration doesn't resume.
- INVALID never reaches a numeric score. A STOP with a different detail gives INVALID (stop-conflict).

**CH2 (slot races):**
- T commits, then the worker attempts J: TIMEOUT stays, no seal, LOST-RACE, no INVALID.
- J commits, then a stale finalizer runs: QUALIFIED stays, LOST-RACE.
- Two finalizers race: exactly one terminal row.
- A new SLOT-INTENT after a terminal row: INVALID (repeat-attempt).
- QUALIFIED with a foreign op or actor, or with no INTENT: INVALID, even when the slot is already terminal.
- A restarted process after a worker crash doesn't append QUALIFIED. The slot ends as TIMEOUT at D.
- A stale finalizer's LOST-RACE moves none of the winner's committed files. The post-race recheck passes.
- Precedence cases: SLOT-MISSED against a QUALIFIED slot gives LOST-RACE (4c), not a refusal. SLOT-TIMEOUT with a
  foreign op on a terminal slot gives INVALID (4a). STOPPED + a SLOT-INTENT for a terminal slot gives INVALID
  (repeat-attempt). A finalizer before E
  or D refuses with no row. Any append to a CLOSED trial refuses. A late R refuses with no row, then TIMEOUT.

**FINAL-2 (recovery owner):**
- Process A appends INTENT and PREPARED, publishes matching bytes and dies before CREATED. Process B takes the lock and
  appends CREATED (op = A's op, actor = B) with no recomputation or refetch, and no INVALID.
- B with a foreign op, missing PREPARED, or changed bytes: INVALID.
- B never appends PREPARED for A's op.

**FINAL-3 (request policy):**
- The provider returns an unpredictable next_page_token and a varying valid page count. Pagination completes without
  knowing the tokens at INTENT time, and provenance records every request.
- A wrong endpoint, changed base scope, new host, redirect, repeated token or more than max_pages pages: Structural,
  with no further request. The trial becomes INVALID (provider-structural).
- No request is sent that isn't in the provenance (spy on the HTTP client).
- Lock acquisition I/O error (not a sharing violation): refuse with no row, and no liveness verdict.

**A3-R3C-1 (source table, rev 5):**
- A normal audit authorizes the paper-api calendar request and the data-host CA batches; a normal final authorizes the
  raw/SIP bars and the window and full-history CA batches; every member of F4.9 is committed at PREPARED.
- A request to another path on paper-api.alpaca.markets, any other host, a redirect, a base parameter or batch outside
  F4.9, or a second calendar request: Structural with no further request, then INVALID (provider-structural).
- Changing or deleting any raw CA page (audit, final/pages or final/pages_full) or any derived member (calendar.json,
  bars.json, bar_problems.json, corporate_actions.json, ca_problems.json, manifest.json, score/s1.json): INVALID
  before any valuation or scoring, with zero valuation calls.
- An extra page file with no provenance entry, or a provenance entry with no page: INVALID.
- Empty ca_symbols_window or ca_symbols_full_history: zero requests for that family; final still completes.
- A score computation error: INVALID (score-aborted), no numeric score.

**CH3 (stages):**
- The provider returns arbitrary valid pages unknown at INTENT time, and the audit completes (no prefetch).
- A crash after INTENT, before PREPARED: INVALID (stage-incomplete), with no refetch.
- A crash after PREPARED, before CREATED: only matching bytes recover, and changed bytes give INVALID.
- retrieved_utc is the actual observation instant.

**CH4 (residual):**
- Observe a violation, fail the journal insert, restore committed bytes and delete the local witnesses, restart: may
  resume. This is labelled lost detection, not equivalence.
- INVALID committed before the crash: the same restoration stays invalid.

**R2-1 (from the prior forum):**
- Commit a stage, delete its artifact, detect it (INVALID commits), restore everything and delete the local witnesses,
  restart: still invalid with zero callbacks.
- A repeat-stage attempt gives INVALID.
- A restored total loss stays invalid.

**R2-2 (from the prior forum):**
- Pause after INTENT with a live owner: a concurrent gate gives pending with no work.
- Pause after PREPARED, fail CREATED, restart: recovery appends CREATED with no recreation.
- A MISSED slot with a stray file: INVALID.

**Locks (F5):**
- A killed owner frees the lock and recovery follows the tables.
- A held lock can't be deleted or replaced.
- A leftover acquirable lock file is not liveness.

**Identity (F6, F7):**
- Exactly one valid open trial authorizes a stage (positive control).
- Each of these refuses with zero callbacks: zero or two open trials; a duplicate trial_id; a wrong-role or
  wrong-bundle CLOSE; a CLOSE before AUDIT; two OPENING-ACKs; a byte-identical duplicate ACK; a broken prev; a closed
  trial's same-bundle ACK; a journal fork, gap or duplicate seq; a plan.json trial_id differing from the AUDIT-ACK.

**Other:**
- Issuance: an early FAILED then a QUALIFIED slot is eligible; a PENDING slot blocks; a change after the ACK is
  caught by F7.3; a missed OPENING-ACK deadline gives no START.
- Pre-audit: write_plan in a fresh directory makes no callbacks. Before the AUDIT-ACK, the opening and START are
  blocked.
- Matrix: every non-empty subset of {plan, audit tree, opening records x2, attestation, prereg, seal, receipt, stop},
  crossed with {bundle same, changed} and {deleted, changed, unparseable}, at each commitment point.

A requirement -> expected-outcome map is delivered with the implementation plan, before code, for Codex review.

## F11. Process
1. A scoped correction check of A3-R3C-1 and the two (a) notes only (operator authorized 2026-11-02, after
   FORUM-S1-ADDENDUM3-R3-CORRECTION ended at NO_CONSENSUS), plus a ruling on whether the flagged blocked.json item
   is in scope.
2. Operator approval.
3. A byte-frozen copy in research/s1/docs.
4. The plan, with the F10 map.
5. Build on a new head (TDD, subagents).
6. A fresh Stage-1 package and Codex code review.
No registration, audit, START, scheduler or live step until a later CONSENSUS.
