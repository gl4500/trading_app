# Task 11 Step 2a: stop-record dispositions for Codex (OQ-8 AMEND, BLK-3), revision 1

## Revision 1: answer to Codex f33d0501 (FORUM-S1-A3-BLK3, AMEND / NO_CONSENSUS on r0 bddd2573)

Revision 0 (sha256 bddd25739a609435ef4b911f6c7f13ac957614cc355e80a1be5ba7609ac8f5ec) is superseded. Codex's records
are in `.coordination/trading_app/s1_a3_blk3_codex_review_20261105/`. The controller accepted BLK3-C1 and BLK3-C2 in
full (progress.md Ruling). Here is each ruling and what r1 does with it.

| Codex item | ruling | r1 disposition |
|---|---|---|
| BLK3-C1: a last-W terminal does not prove all windows expired | material, CONTRADICTED | **Accepted.** The early-W counterexample is valid: SLOT-INTENT has no lower time bound in F0.5 step 6, OQ-33 consumes an early invocation as FAILED, and FAILED has no time bound. The pure candidate (`stop_record`) is now separated from the permission to commit (`stop_ready`, §1.3). Permission is the transaction clock, never a terminal row or its `at`. New case (i) has a negative and a positive control. |
| BLK3-C2: the completing row's `at` is not the determination time | material for provenance, CONTRADICTED | **Accepted.** `determined_utc` is defined as provenance: the trigger row's `at`, verbatim (§3). A QUALIFIED row's `at` is R and can predate its commit. The STOP's commit time is the TRIAL-STOP row's journal metadata. QUALIFIED.at is unchanged, and stop_close is never used as the trigger slot. New case (iv). |
| 6.1 close states and rules | AMEND | **Accepted.** SEALED is renamed "determined sampled candidate"; E2 CREATED authority is required separately. Window-readiness is explicit (§1.1, §1.3). |
| 6.2 rows 300, 301 | ACCEPT | Unchanged. |
| 6.2 rows 302, 303, 305 | ACCEPT WITH READINESS GUARD | Unchanged as candidates; commit is gated by §1.3. |
| 6.2 row 304 | ACCEPT; ADD COMPLETION CASE | Unchanged. New cases (ii) (row 304 after its TIMEOUT) and (iii) (UNRESOLVED resolved by MISSED). |
| 6.3 trigger | AMEND; SELECT (b) | (b) is adopted, with Codex's wording: the greatest journal seq among the necessary terminal dependencies, with later irrelevant terminal rows ignored. |
| 6.4 shape | ACCEPT WITH CLARIFICATIONS | The clarifications are added to §4. |
| A1 | AMEND / ACCEPT ELIGIBLE-WINDOW COMPLETION | Rewritten (§5 A1): an operational timeout on the fixed eligible set, with no extra wait for the deadline instant. |
| A2, A3, A5, A7, A8 | ACCEPT | Unchanged. A2 gets case (iii); A8's references are updated. |
| A4 | ACCEPT WITH INTEGRITY CONDITION | §5 A4, plus new case (v): a missing or corrupt ineligible seal is INVALID, both with row 305 and in a NO-VALID-SEAL history. |
| A6 | AMEND; NO BLANKET ALL-SLOTS REQUIREMENT | Rewritten (§5 A6): a sparse no-attempt close is missed only once all its windows have expired, shown by the transaction clock. |

Expected values still come only from independently chosen committed fixture records:
- the hand-written values in this document;
- the named journal rows' seq and line sha256;
- the CREATED seal files' sha256.

They never come from `stop_record`. Rows 300-305 are unchanged numerically: Codex recomputed them independently.
What remains PENDING Codex acceptance is the r1 text: §1.3, §3, cases (i)-(v), A1, A4 and A6.

Base: research/s1-shadow-trial at 5e97f78, with the uncommitted Task 11 Steps 1-3. Calendar arithmetic was
cross-checked against the unchanged `s1_seal.deadline`, `eligible_sessions`, `schedule`, `eligible_until` and
`resolution_deadline`. Every hand-written `at` below is asserted equal to the committed row's `at` when the fixture
history is built (`a3_helpers.stop_history`).

## 0. Sources and the frozen inputs

Spec authority:
- design v5 (`docs/s1_design_v5.md`): §4 deadline, §6 schedule / unsealed close, §8 fully sold, §9 stop and
  timeout, §16 examples 13-15;
- Addendum 1 rev 3: A2.1 the persisted stop, A5.1 the deadline instant, A5.2 slot eligibility E, A5.3 the 08:00
  slot, A6 calendar;
- Addendum 2 rev 1: B1.1 D(s), B1.2 PENDING, B1.4 close-level selection, B1.5 no frozen outcome while PENDING;
- Addendum 3 rev 5: F0.5 append precedence, F1 STOP prefix, F2.1-F2.5 stop record, F3 slot rows;
- Erratum 1 r4: E2.2 "determined", E2.4 seal authority, E2.5 STOP fence, E2.6 required members;
- plan OQ-8 (AMEND), OQ-9 (APPROVE) and OQ-33 (early invocation consumed as FAILED).

**Frozen calendar.** The examples use the calendar the test fixture pins at the audit stage:
- `conftest.s1_plan_audit` builds `audit/calendar.json`, and prereg's `calendar` is a copy of it;
- it lists every Monday-Friday from START - 40 days to deadline date + 40 days, 09:30-16:00 New York, with no
  holidays and no early closes;
- for START 2026-10-26 it spans 2026-09-16 .. 2027-06-04 (188 rows).

No real Alpaca calendar is pinned in the repo. A real pinned calendar (A6) changes the dates and counts below, never
the rules. Codex independently verified the synthetic arithmetic (188 rows / 130 eligible / 4,108 slots / the
90-minute gap).

**START** = 2026-10-26T13:30:00+00:00 = Monday 2026-10-26 09:30 EDT.

**Deadline instant** (A5.1) = START + 6 calendar months at START's New York wall time:
- = Monday 2027-04-26 09:30 EDT = **2027-04-26T13:30:00+00:00**;
- EDT at both ends; no month-end clamp.

**Opening close** = Friday 2026-10-23 16:00 EDT (2026-10-23T20:00:00+00:00). It is never eligible: its open is
before START, and it is sealed by the `opening` stage.

**Eligible sessions** (A5.1) are those with open >= START and close instant <= the deadline instant:
- d0 = 2026-10-26 .. d129 = 2027-04-23 (Friday): **130 sessions**;
- d130 = 2027-04-26 opens at 13:30Z, exactly the deadline, and closes at 20:00Z, after it: **ineligible**.

**Slot schedule of a close C** (§6, A5.2, A5.3, B1.1):
- C+45, +47, +49, +51, +53, +55 min, then every hour on the hour through W;
- W = 08:00 New York on the next session day; the last slot is W itself (the "W slot");
- E(s) = min(s + 10 min, W), so E(W) = W;
- D(s) = E(s) + 30 min;
- every window of C has closed by W(C): max over s of E(s) = W(C).

| close | slots | first slot | W slot (= E(W)) | D(W) |
|---|---|---|---|---|
| d0 2026-10-26 (Mon) | 22 | slot/20261026T204500Z | slot/20261027T120000Z | 2026-10-27T12:30Z |
| d1 2026-10-27 | 22 | slot/20261027T204500Z | slot/20261028T120000Z | 2026-10-28T12:30Z |
| d2 2026-10-28 | 22 | slot/20261028T204500Z | slot/20261029T120000Z | 2026-10-29T12:30Z |
| d129 2027-04-23 (Fri, last eligible) | 70 | slot/20270423T204500Z | slot/20270426T120000Z | 2027-04-26T12:30Z |

The d1 second slot is `slot/20261027T204700Z`, with E = 20:57Z and D = 21:27Z.

Fixture slot rows (`conftest._write_seal`) for a sealed close C at slot s (default s = C + 45 min):
- SLOT-INTENT at s + 1 s;
- SLOT-QUALIFIED with `at` = R = s + 31 s (F0.2), unless the case says otherwise;
- then the real seal stage `seal/<C>`.

The timeout close-out (`s1_close_out` = `finalize_close` at W) writes one SLOT-MISSED per slot of d129 in schedule
order, each with `at` = W, the W slot last.

Fixture lots:
- ids are assigned in stored-time order, so the carry-in BUY is id 1;
- cohort BUYs are at 15:00Z and SELLs at 18:00Z on the stated days;
- each lot is 10 shares of `S{i % 5}`.

## 1. Rules (r1)

### 1.1 Close states (from committed rows; the CANDIDATE only)

- **Determined sampled candidate** (E2.2; r0 called it "SEALED"): the close's first QUALIFIED slot is committed and
  every earlier scheduled slot has a terminal row.
  - Its seal's trades are that QUALIFIED slot's committed evidence (`sampled_seals`).
  - Authority is separate: the E2 CREATED `seal/<C>` stage, with the file equal to its PREPARED member. E2.5 makes
    it exist before any TRIAL-STOP.
- **PENDING** (B1.2/B1.5): a slot has an INTENT and no terminal row, before any determined QUALIFIED of the close.
- **UNRESOLVED** (A2, accepted): a QUALIFIED exists, but an earlier slot has no terminal row (no row yet). The close
  is not determined.
- **No attempt / no candidate**: no QUALIFIED and no PENDING slot.
  - Such a close is only **counted UNSEALED (missed) once every one of its windows has expired** (A6 r1). That needs
    the transaction clock: `now >= W(C)`. It is checked in §1.3, not inferred from rows.
  - Absence of QUALIFIED/INTENT does not prove UNSEALED while eligible windows remain (Codex 6.1).

### 1.2 The candidate (`stop_record(out, rows, start, cal, bundle)`, a pure function of rows)

- **Lots (STOPPED).** Walk the eligible closes in order:
  - a PENDING or UNRESOLVED close before the first qualifying determined close means **no candidate**;
  - otherwise the candidate is the first determined close C with count_sold(C's sampled seal, START, C) >= 100 (§8,
    §9). The no-attempt closes before C are its `missed`.
- **Timeout (TIMEOUT / NO-VALID-SEAL).** There must be no lots candidate, and no PENDING or UNRESOLVED eligible
  close.
  - The W slot of the last eligible close (d129) must have a terminal row. That row is the trigger anchor F2.1
    requires: a triggering slot with a terminal row. It is NOT a time witness (C1).
  - TIMEOUT: the last determined eligible close. NO-VALID-SEAL: none (§9; never the opening or a pre-START close,
    A5).
- **Fields** (§4):
  - `missed` = the no-attempt eligible closes up to the stop close (STOPPED), or all of them (timeout);
  - `seals` = sampled seals of eligible closes up to the stop close (`{}` for NO-VALID-SEAL);
  - `cohort_row_ids` / `lots` from the stop seal's rows <= the stop close.

### 1.3 Permission to commit (`stop_ready(out, rows, start, cal, bundle, now)`; BLK3-C1)

TRIAL-STOP may commit only when all of the following hold:
1. the candidate exists (no PENDING / UNRESOLVED blocker in its scope);
2. `now` is the clock read inside the TRIAL-STOP journal transaction (F0.1, OQ-7);
3. that clock is `>=` the W of every close the candidate counts in `missed`;
4. for TIMEOUT / NO-VALID-SEAL, that clock is `>=` W of the last eligible close (`W_last` = 2027-04-26T12:00Z), so
   every eligible window E has expired.

Otherwise the result is a refusal with no row: decide again later. The test stub's `stop_ready` always permits, and
Step 4 implements it.
- It is evaluated inside the append transaction, for example in the TRIAL-STOP context's `stop_detail`/fence
  callables. This mirrors the E2.5 fence.
- No terminal row and no terminal `at` stands in for this clock.
- The record stays a pure function. `now` affects only whether the candidate may commit, never its content.

For a STOPPED candidate, (3) is in practice met long before the stop close's own QUALIFIED. It is stated anyway
because a no-attempt close is only missed once its windows have expired. The test (row
`lots-later-not-chosen`, W(d0) = 2026-10-27T12:00Z) pins the boundary.

## 2. Worked examples

Common to all examples:
- START 2026-10-26T13:30Z;
- deadline 2027-04-26T13:30Z;
- eligible d0 2026-10-26 .. d129 2027-04-23;
- `trial_id` / `bundle_sha256` are the open trial's;
- seal sha256 = the CREATED file's;
- seq / line sha256 = the named row's;
- `determined_utc` = the named row's `at`, verbatim (provenance, §3).

Rows 300-305 are unchanged from r0, numerically accepted by Codex.

### Row 300: lots-earliest

History: 100 lots bought d0 (ids 2-101), sold d1 (ids 102-201); seals d0, d1.

Candidate: STOPPED, stop_close "2026-10-27T20:00:00+00:00", stop_seal "seals/2026-10-27.json", cohort [2..101], lots
{100, 100}, missed [], seals {d0, d1}. Trigger: `slot/20261027T204500Z` SLOT-QUALIFIED, determined_utc
"2026-10-27T20:45:31.000000+00:00".

Permission: no missed close, so the candidate is permitted at any later clock.

### Row 301: lots-later-not-chosen

History: 200 lots bought d0 (ids 2-201); lots 0-99 sold d1, lots 100-199 sold d2; seals d1 and d2; d0 has no row.

Candidate: STOPPED at d1, cohort [2..201], lots {100, 200}, missed ["2026-10-26"], seals {d1} only. Trigger:
`slot/20261027T204500Z` QUALIFIED, "2026-10-27T20:45:31.000000+00:00". The later-created d2 seal remains required
integrity evidence (A4).

Permission: now >= W(d0) = 2026-10-27T12:00:00Z (boundary test: 11:59:59 refused, 12:00:00 permitted).

### Row 302: TIMEOUT, the last determined eligible close

History:
- 100 lots bought d0; 99 sold d1 (ids 102-200);
- seals d0, d1, d2;
- the close-out of d129 at W (70 MISSED, `at` W).

Candidate: TIMEOUT, stop_close "2026-10-28T20:00:00+00:00", stop_seal "seals/2026-10-28.json", cohort [2..101], lots
{99, 100}, missed = 2026-10-29 .. 2027-04-23 (127 dates), seals {d0, d1, d2}. Trigger: `slot/20270426T120000Z`
SLOT-MISSED, "2027-04-26T12:00:00.000000+00:00".

Permission: now >= W_last = 2027-04-26T12:00:00Z (boundary test: 11:59:59 refused, 12:00:00 permitted).

### Row 303: NO-VALID-SEAL

History: 100 lots as in row 300; no post-START seal; the close-out of d129 at W.

Candidate: NO-VALID-SEAL, stop_close / stop_seal / stop_seal_sha256 null, cohort [], lots null, missed all 130
dates, seals {}. Trigger: `slot/20270426T120000Z` SLOT-MISSED, "2027-04-26T12:00:00.000000+00:00".

Permission: now >= W_last.

### Row 304: pending-close exclusion (B1.5)

History: 100 lots as in row 300; SLOT-INTENT on `slot/20261026T204500Z` at 2026-10-26T20:45:01Z with no terminal
row; seal d1.

Candidate: **None**. This holds even though D (21:25Z) has passed: only a committed terminal event resolves the slot.
There is no row.

### Row 305: deadline-instant eligibility (A5.1)

History:
- 100 lots bought d0 and sold 2027-04-26 at 18:00Z;
- seal d0;
- the close-out of d129 at W;
- then seal d130 (2027-04-26), which sells 100.

Candidate: TIMEOUT at d0 (not STOPPED at d130), stop_close "2026-10-26T20:00:00+00:00", stop_seal
"seals/2026-10-26.json", cohort [2..101], lots {0, 100}, missed = 2026-10-27 .. 2027-04-23 (129 dates), seals {d0}
only. Trigger: `slot/20270426T120000Z` SLOT-MISSED, "2027-04-26T12:00:00.000000+00:00". The CREATED
`seals/2027-04-26.json` is not a sampled input, but it remains required evidence (case (v)).

Permission: now >= W_last.

### (i) Early W FAILED (BLK3-C1 regression; test case `early-w-failed`)

History:
- 100 lots as in row 300; no post-START seal;
- SLOT-INTENT on d129's W slot `slot/20270426T120000Z` at 2027-04-23T20:46:00Z (journal: only now < E is required);
- SLOT-FAILED at 2027-04-23T20:46:30Z (OQ-33), its claim and failure report matching the detail (F3);
- no other d129 slot has a row. 69 of d129's windows are still eligible at 20:46Z.

Candidate (pure): NO-VALID-SEAL, missed all 130, seals {}, trigger `slot/20270426T120000Z` **SLOT-FAILED**,
determined_utc "2027-04-23T20:46:30.000000+00:00".

Permission:
- at now = 2027-04-23T20:47:00Z: **refused**, so there is **no STOP** (`decide_stop` appends no TRIAL-STOP);
- positive control at now = W_last = 2027-04-26T12:00:00Z: **permitted**. Every d129 window has then expired, so the
  sparse no-attempt d129 counts missed (A6 r1), and the same candidate may commit.
- The trigger is still the early FAILED row. Its `at` is provenance only (§3).

### (ii) Row 304 after its TIMEOUT (`pending-after-timeout`)

History: row 304's, then the finalizer's SLOT-TIMEOUT for `slot/20261026T204500Z` (the INTENT's op), committed at
2026-10-27T21:00:00Z after the d1 seal rows.

Candidate: STOPPED at d1, cohort [2..101], lots {100, 100}, missed ["2026-10-26"], seals {d1}.

Trigger (b): the **unblocking d0 TIMEOUT**, `slot/20261026T204500Z` SLOT-TIMEOUT, determined_utc
"2026-10-27T21:00:00.000000+00:00". It is not the stop close's QUALIFIED, and the trigger slot is not the stop close
(§4).

Permission: now >= W(d0).

### (iii) UNRESOLVED, then resolved by MISSED (A2; `unresolved-blocks`, `unresolved-resolved-by-missed`)

History:
- 100 lots as in row 300; seal d0;
- d1: SLOT-INTENT and QUALIFIED on the second slot `slot/20261027T204700Z` (R = 20:47:31Z, 100 sold), with no seal
  stage. The first slot `slot/20261027T204500Z` has no row;
- seal d2 (also 100 sold).

Candidate before the MISSED: **None**, because d1 is UNRESOLVED. The rev-0 draft would have counted d1 missed and
stopped at d2.

Then the finalizer's SLOT-MISSED on `slot/20261027T204500Z` commits at 2026-10-28T21:00:00Z, and the d1 seal stage
CREATED follows.

Candidate after: STOPPED at **d1** (the earlier close itself, not d2), stop_seal "seals/2026-10-27.json", cohort
[2..101], lots {100, 100}, missed [], seals {d0, d1}. Trigger (b): the d1 MISSED `slot/20261027T204500Z`,
"2026-10-28T21:00:00.000000+00:00".
- It has the greatest seq among d1's dependencies (MISSED, QUALIFIED) and d0's (QUALIFIED).
- The d2 rows committed between them are later irrelevant terminal rows, and are ignored.

### (iv) Completing-row clock (BLK3-C2; `delayed-qualified-clock`)

History:
- 100 lots as in row 300; seal d0;
- d1: SLOT-INTENT on `slot/20261027T204700Z`;
- then the unblocking SLOT-MISSED on `slot/20261027T204500Z`, committed with `at` 2026-10-27T20:56:00.100000Z;
- then that slot's SLOT-QUALIFIED at seq = MISSED seq + 1, with R = `at` = 2026-10-27T20:56:00.000000Z, committed
  (`created`) at 20:56:00.2;
- then the d1 seal stage.

Candidate: STOPPED at d1, cohort [2..101], lots {100, 100}, missed [], seals {d0, d1}. Trigger (b): the QUALIFIED,
`slot/20261027T204700Z`, determined_utc **"2026-10-27T20:56:00.000000+00:00" verbatim**.
- That instant predates the MISSED (20:56:00.1) it depends on.
- It is not when the stop became determinable, and not the STOP's commit time.

### (v) Damaged ineligible seal (A4 integrity condition; `test_damaged_ineligible_seal_is_invalid`)

- **Row 305's history.** Delete or corrupt the CREATED `seals/2027-04-26.json`. The gate gives **INVALID
  (stage-replaced)** through the F4 table / E2.6, even though that seal is never a sampled stop input.
- **NO-VALID-SEAL with an ineligible seal (`no-valid-seal-ineligible-seal`).** The history is row 305's lots with no
  eligible seal, the d129 close-out, then seal d130.
  - Candidate: NO-VALID-SEAL exactly as in row 303 (missed 130, seals {}; the d130 seal is not listed).
  - Deleting or corrupting `seals/2027-04-26.json` is likewise INVALID (stage-replaced).

## 3. The triggering row (Codex 6.3: (b) selected) and provenance (BLK3-C2)

- **Trigger** = the committed terminal row with the greatest journal seq among the necessary terminal dependencies of
  the sampled-state decision. Later irrelevant terminal rows are ignored. The dependencies are:
  - for every eligible close up to the stop close (STOPPED), or every eligible close (timeout):
    - a determined close contributes the terminal rows of its slots up to and including its first QUALIFIED;
    - a no-attempt close contributes the terminal rows of its slots that have an INTENT (FAILED / TIMEOUT);
  - for timeout, also the terminal row of the last eligible close's W slot (the anchor of §1.2).
- **`triggering_slot` / `terminal_seq` / `terminal_line_sha256`** are that row's subject, seq and line sha256. This
  is causal identity.
  - The triggering slot can belong to an earlier close than the stop close (cases ii and iii).
  - Consumers must not confuse it with `stop_close`.
- **`determined_utc`** = that row's `at`, verbatim. It is **terminal-at provenance (F2.1) only**:
  - for a QUALIFIED row it is R (F0.2), which can predate that row's commit and even the rows it completes (case iv);
  - it does not prove when the stop became determinable, when the windows expired, or when the seal was authorized.
- **The STOP's actual commit time** is the TRIAL-STOP row's own journal metadata (its `at` = the transaction clock,
  and its `created`). **Readiness** is §1.3. QUALIFIED.at is not changed.

## 4. Stop-record shape (accepted with clarifications)

The record has no wall-clock decision fields: `decided_utc` and `decided_by` are removed. The TRIAL-STOP detail =
sha256(canonical(record)) (F0.4). stop.json bytes = `json.dumps(record, indent=1, sort_keys=True)`.
- The detail hashes the canonical record.
- The stop.json **file** hash (the pretty bytes) is a different value. It is what stop_attest binds
  (`inputs["stop.json"]`). The two are never interchanged.

| field | type | STOPPED | TIMEOUT | NO-VALID-SEAL |
|---|---|---|---|---|
| trial_id | str (uuid4) | open trial | same | same |
| rule | "lots" \| "timeout" | "lots" | "timeout" | "timeout" |
| status | "STOPPED" \| "TIMEOUT" \| "NO-VALID-SEAL" | ✓ | ✓ | ✓ |
| triggering_slot | str `slot/YYYYMMDDTHHMMSSZ` | §3 (may be an earlier close's slot) | §3 | §3 |
| terminal_seq | int | trigger row seq | same | same |
| terminal_line_sha256 | str (64 hex) | trigger row line sha | same | same |
| determined_utc | str, the trigger row's `at` verbatim (provenance only, §3) | ✓ | ✓ | ✓ |
| stop_close | str ISO-8601 aware UTC \| null | close | last determined close | null |
| stop_seal | str `seals/YYYY-MM-DD.json` \| null | ✓ | ✓ | null |
| stop_seal_sha256 | str (64 hex) \| null | sampled seal bytes; must equal the CREATED/PREPARED member (A7), else INVALID before the stop | ✓ | null |
| cohort_row_ids | list[int], ascending | ✓ | ✓ | [] |
| lots | {"sold": int, "cohort": int} \| null | ✓ | ✓ | null |
| missed | list[str YYYY-MM-DD], ascending | no-attempt eligible closes < stop close | all no-attempt eligible | all no-attempt eligible |
| seals | dict[str relpath -> str sha256] | sampled seals of eligible closes <= stop close | same | {} |
| bundle_sha256 | str (64 hex) | the trial's AUDIT-ACK bundle | same | same |

Every hash is validated against committed stage/slot evidence. No test uses a fixture-computed `stop_record` as its
own oracle.

## 5. Ambiguities and rulings

- **A1 (r1, Codex AMEND/ACCEPT).** The timeout is an **operational eligible-window timeout on the fixed eligible
  set**, not a claim that six months of wall time have passed.
  - With a 09:30 START it can commit at W_last (2027-04-26T12:00Z), 90 minutes before the deadline instant
    (13:30Z). That is accepted: every eligible window has expired and no candidate can still qualify.
  - There is no extra wait for the deadline instant.
  - Readiness is the transaction clock >= W_last (§1.3), never an arbitrary terminal W row.
- **A2 (accepted).** UNRESOLVED blocks. See case (iii).
- **A3 (accepted).**
  - A pending slot after the selected first QUALIFIED does not undo a determined close.
  - Pending closes after the selected lots stop do not change it.
  - The E2.5 fence and the post-STOP exclusions still apply.
- **A4 (accepted with integrity condition).**
  - `seals` lists the sampled eligible seals through stop_close (`{}` for NO-VALID-SEAL).
  - Every CREATED stage remains required integrity evidence through E2/F4: opening, ineligible and later seals alike.
  - Adapting the legacy `stop_problems` must not remove those checks.
  - See case (v).
- **A5 (accepted).** The last determined eligible post-START close with close <= deadline; never the opening or a
  pre-START close.
- **A6 (r1, Codex AMEND).** There is no blanket all-slots-terminal requirement and no manufactured MISSED rows.
  - A sparse no-attempt close is counted missed only after all its claim/capture windows have expired (the
    transaction clock >= its W), with no outstanding INTENT and no UNRESOLVED candidate.
  - The full all-terminal requirement still applies to selecting a seal prefix (E2.2) and to the opening issuance
    checklist.
- **A7 (accepted).** Recomputed seal bytes and the CREATED/PREPARED member hash must agree. A mismatch is invalidity
  before stop or valuation. Tests hash the frozen CREATED file.
- **A8 (accepted, informational).** References are by function name at 5e97f78: `s1_run.attest_stop` and
  `s1_collect.write_final_plan`. The brief's line numbers are stale.

## 6. What Codex is asked to accept (r1)

1. §1.3: `stop_ready`, the permission to commit, kept separate from the pure candidate, with the transaction-clock
   rule.
2. §3: the trigger and provenance wording.
3. Cases (i)-(v) and their expected values.
4. The A1 / A4 / A6 texts.

Rows 300-305 are unchanged from what Codex accepted.

Disclosure (AGENT_FORUM §2/§10): written by the Task 11 implementer. Codex's f33d0501 review is peer evidence; the
r1 cases are verified only by the fixture's own `at` assertions and the stub RED, not by a second agent. Mailbox
isolation and stage order are convention, not enforcement.
