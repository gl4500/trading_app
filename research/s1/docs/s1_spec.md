# S1 spec — MeanReversion P13 shadow trial

Agreed behavioural baseline: `s1_design_v5.md` (sha256 33c32840…, Codex APPROVE-DESIGN 502ca2a4). This spec
turns it into requirements, components, tests and operator steps. Where wording differs, the design governs.

## 1. What it is, in one paragraph
E1 found that, on MeanReversion's past trades, exiting with P13 (an 8% stop below the buy price plus a 12%
trailing stop below the highest daily close since buying) would have roughly doubled average return per trade.
S1 checks that on **new** trades. It never changes the live app: it reads a consistent copy of the trade
database after each market close, counts how many new MeanReversion trades have been fully sold, and stops once
100 have (or after 6 months). Only then does it download prices once and compare, trade by trade, what the app
actually did with what P13 would have done. P13 "passes" only if it earns more per trade, in both percentage and
dollars, at both 5 and 10 basis points of trading cost. A pass only nominates a separately reviewed live change.

## 2. Requirements (stable IDs; each maps to design sections and examples)
| ID | Requirement | Design § | Examples |
|---|---|---|---|
| R-EST | Offline paired daily-bar comparison vs the app as operated; no live change, app import, broker API or restart | 1–2 | — |
| R-TIME | Membership, counts and stop use stored ledger time (aware UTC); stated limitation | 3 | 8 |
| R-PLAN | Planned START (future NYSE open, ≥5 sessions after plan review), calendar range and deadline fixed before any request; misses re-register | 4 | 15, 16 |
| R-SNAP | SQLite online backup → MR projection (agents, trades, portfolios, reasoning hashes, schema, ids, capture times), hashed and kept | 5 | 1, 2 |
| R-SEAL | Scheduled seals (C+45 min, 5×2 min retries, hourly to 08:00 ET); first consistent capture seals C; unsealed closes can't be the stop; row fences; backdated rows invalidate | 6 | 7, 14 |
| R-QTY | Operational replay with per-SELL <0.001 write-off audit vs portfolios (internal consistency); economic FIFO = E1 core unchanged; bridge reported | 7 | 1, 3 |
| R-SOLD | Fully sold = first SELL allocation leaving the lot <0.001 (strict, absorbing); no SELL → never sold | 8 | 3–6 |
| R-STOP | First sealed close with ≥100 fully sold cohort lots; timeout = last sealed close ≤ START+6 calendar months; else NO-VALID-SEAL; cohort = every entry to the stop | 9 | 13–15 |
| R-COUNT | Checkpoint reports counts/integrity only; cannot import simulator/economics; no prices or PnL | 10 | 17 |
| R-UNITS | Opening audit (own ACK, no prices); pre-START bridge rows; per-lot paired exclusion windows; conservative unknown records; required bars incl. stop close | 11 | 12, 19–23 |
| R-EPOCH | Semantic receipt per seal (change → INVALID); restarts observed from crash.log PROCESS START lines (minimum, gaps reported); attestations in causal order | 12 | 9–11 |
| R-ACQ | One final acquisition ≥3 sessions after stop, every MR-held symbol, E1 collector discipline | 13 | 18 |
| R-VERDICT | SHADOW PASS iff strict mean return AND mean $ at 5 and 10 bp; dispositions in fixed order; UNVERIFIED-PROVENANCE pass is not a nomination | 14 | 9 |
| R-GATES | Staged ACKs; separate namespaces; every attempt preserved; no auto-retry | 15 | 16, 18 |

## 3. Components (all under `C:\Users\gl450\.coordination\trading_app\`, nothing in the app repo)
- `s1_snapshot.py` — online backup + MR projection + hashing (R-SNAP). Only module that opens `trading.db`.
- `s1_books.py` — operational replay with write-off audit; fully-sold event detection over the E1 economic FIFO
  (R-QTY, R-SOLD). Imports `e1_sim.baseline_lots` only (hash-pinned 68f21ab1).
- `s1_seal.py` — seal schedule, consistency, row fences, backdating checks, bridge classification (R-SEAL, R-UNITS).
- `s1_receipt.py` — semantic receipt (AST import walk, config hashes, versions) and crash.log restart record
  (R-EPOCH).
- `s1_checkpoint.py` — the scheduled read-only command; counts only (R-COUNT, R-STOP). Must not import `e1_sim`'s
  simulator/economics.
- `s1_collect.py` — opening-audit and final collectors (metadata/prices), E1 collector discipline (R-UNITS, R-ACQ).
- `s1_run.py` — lifecycle gates, ACK verification, exclusion windows, one exclusive score, report (R-GATES,
  R-VERDICT). Uses the pure E1 core for P13, costs and exact arithmetic.
- `s1_tests/` — tests; `s1_evidence/` — RED/GREEN, mutation and review records; per-stage output namespaces.

## 4. Testing (PEER_REVIEW.md standard)
- Every requirement and all 23 design examples become Given/When/Then tests written first; intended RED recorded
  before code (missing-interface failures labelled as such).
- Synthetic connected lifecycle with the REAL schemas (agents, trades with reasoning, portfolios), including a
  synthetic WAL writer committing trade and portfolio separately, late-cycle bridge rows, restarts in crash.log.
- Hypothesis properties: timestamps/time zones, seal schedule and deadline arithmetic, FIFO/write-off books,
  thresholds at exactly 0.001, exclusion windows.
- Source-bound targeted semantic mutants for each R-ID plus a focused Cosmic Ray run with survivor triage.
- Never the live database or app in tests; independent Codex replication of the final score.

## 5. What you (the operator) will be asked to do, and when
1. Review this spec (now).
2. Later: approve the Windows Task Scheduler entry that runs the read-only checkpoint after each close.
3. Before START: confirm in writing that the backend is running from the recorded code (START attestation).
4. During the trial: nothing required. Restarts are fine; changing MeanReversion's code or settings would end the
   trial. Please don't delete or truncate `backend/logs/crash.log` (it is the restart record).
5. At the stop: confirm no MeanReversion code/config/package changed and no MeanReversion trade was placed or
   edited by hand (stop attestations). Then the one score runs and Codex replicates it.

## 6. Out of scope
Changing live exits; intraday simulation; other agents; any adaptive change to P13, costs, thresholds or the
horizon after the trial starts.
