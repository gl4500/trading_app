# Task 15d: disposition ledger and open items

This ledger is current as of Task 15d-3 (2026-11-16), after Codex's reconciliation and disposition of 5376f42 (t15d2_5376f42_review_20261116/REVIEW_AND_DISPOSITION.txt). Forum status: CONDITIONAL_CONSENSUS on the scoped disposition below. The historical campaign records (a3/t15/, a3/t15d1/, a3/t15d2/ and their summaries and hash lists) are unchanged. This file records today's reviewed status and keeps it separate from each record's original status.

## Tally (reviewed)
**7 adopted-oracle kills + 1 isolated-branch seam kill**, with the real-tuple F11 gap OPEN (T15-F11-REAL below).
- These are NOT 8 kills, NOT 8 integration kills, and NOT a fully closed Task 15.
- The 7 are T15-F1, F2, F4, F7, F9, F10 and F12. They were killed at their adopted agreed lines in 15d-1 (a3/t15d1/, reconciled at 81e1ffd); the 15d-2 marks were removed.
- The 1 is T15-F11, killed at the isolated pending-branch seam oracle `test_s1_a3_t15d_f11_branch.py:31` in 15d-2 (a3/t15d2/stop-pending-removed/, reconciled at 5376f42). The 15d-3 mark was removed for that CURRENT seam selection only.

## History vs today

| finding | original status (record) | today's reviewed status |
|---|---|---|
| T15-F11 stop-pending-removed | 15b: failed-elsewhere at s1_seal.py:663 TypeError (a3/t15/stop-pending-removed/); 15d-1: failed-elsewhere at s1_seal.py:663 TypeError, adopted oracle killers.py:130 not reached (a3/t15d1/stop-pending-removed/) | seam selection killed at f11_branch.py:31 (a3/t15d2/stop-pending-removed/); real-tuple gap OPEN (T15-F11-REAL) |

## OPEN items

### T15-F11-REAL: F11 real-tuple assertion-oracle gap (OPEN)
- **Mutant:** `stop-pending-removed`, which changes `s1_seal._stop_record` from `if stt in ("pending", "unresolved"):` to `if stt == "unresolved":`.
- **Gap:** no assertion oracle on REAL inputs observes this mutant.
  - `_close_state` returns the real pending tuple `("pending", None, None)`.
  - The mutant falls through and raises `TypeError` at `deps += dd` (s1_seal.py:663) before any intended assertion is reached.
- **Status of the TypeError:** this reachability is OBSERVED, not unknown or hypothetical. It was recorded twice:
  - a3/t15/stop-pending-removed/ (15b; agreed oracle stop.py:162 not reached);
  - a3/t15d1/stop-pending-removed/ (15d-1; adopted oracle test_s1_a3_t15d_killers.py:130 not reached).

  Under the real-tuple oracles it remains **failed-elsewhere**, neither killed nor equivalent.
- **No equivalence claim:** the mutation observably changes a `None` return into an exception.
- **No real-tuple closure:** the isolated seam kill (a3/t15d2/stop-pending-removed/, `test_s1_a3_t15d_f11_branch.py:31`) substitutes the pending tuple's unused dependency slot `None -> []`. It proves only the pending-guard branch contract. It does NOT prove that production tuples reach resolution, that mutated continuation is safe, or real-tuple integration closure.
- **Not closed by the mark removal.** The FINDINGS mark was removed in 15d-3 only for the current seam selection. This item stays OPEN until a scoped real-tuple oracle is separately agreed and verified.
- **Links:**
  - :663 raw records: a3/t15/stop-pending-removed/record.json and a3/t15d1/stop-pending-removed/{record.json, mutant-crash.json, mutant-junit.xml};
  - seam :31 raw record: a3/t15d2/stop-pending-removed/{record.json, mutant-crash.json, mutant-junit.xml};
  - mapping history: t15_agreed_assertions.json `stop-pending-removed`.superseded_15b and .superseded_t15d1.
