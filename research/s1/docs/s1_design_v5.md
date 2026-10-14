# S1 — MeanReversion P13 offline daily-bar exit shadow trial (design v5, complete)

Status: DESIGN DRAFT v5 for Codex agreement. Supersedes v1–v4 entirely (no inherited clauses). Nothing built; no
snapshot, acquisition, scheduler task or evaluation authorised. v5 = v4 (2bdd9bd1) + Codex 7a2fb98f's three
corrections (pre-START bridge rows, attestation causal order, explicit paired exclusion windows). The operator
declined the second key rotation (2026-10-14), so no restart is pending before START. Operator decisions (2026-10-12/14), not to be revisited: stop = 100 FULLY SOLD new MR lots with a
6-calendar-month timeout; restarts are part of the as-operated baseline; manual-trade absence by operator
attestation.

## 1. S1-PURPOSE and estimand
Check prospectively, on NEW MeanReversion (MR) entries, whether E1's MR result holds for P13: hard stop 8% below
the recorded entry price; trailing stop 12% below the highest completed daily close after entry; active from the
first NYSE session strictly after the entry's NY date; no target; no time stop. Operator's "better": more net
return per trade with total not dropping.
**Estimand:** a prospectively registered, fixed-entry, paired, daily-bar comparison of P13 against the live MR app
AS OPERATED (restarts included), on MR's recorded entries and sizes. Not an intraday executable shadow
portfolio; no modelling of intraday exit timing, re-entry/cool-down, capital reuse, dividends or every fill
constraint.

## 2. S1-APPROACH
Offline. No live-app change, app import, broker/order API or restart. Live state is read only through (a) SQLite
online-backup snapshots and (b) read-only file/process observations. The only new operational object is a
Windows Task Scheduler entry that runs the read-only checkpoint command (operator approves it separately). A new
adapter `s1_run.py` (own namespace, pins and tests) wraps the hash-pinned PURE E1 core `e1_sim.py` 68f21ab1
(P13 maths, exact arithmetic, fills, costs, economic FIFO). The E1 runner is not reused.

## 3. S1-TIME
Membership, counts and the stop use the stored ledger time `trades.timestamp` (persistence time set by
save_trade; no offline execution timestamp exists) — a stated limitation. All instants are aware UTC.

## 4. S1-PLAN (planned start, calendar, deadline — fixed before any metadata request)
A reviewed metadata plan, written before the audit or calendar request, fixes:
- **Planned START** = a named future NYSE regular open (aware instant), at least 5 NYSE sessions after the plan's
  review.
- **Calendar range** = START's session through the deadline + 3 sessions; **deadline** = START + 6 calendar months
  (missing day-of-month -> that month's last day).
- **Audit ledger cut** = the opening seal (§6) of the close immediately before START.
The S1-AUDIT-ACK binds the collector/plan hashes AND the planned START. The audit, receipt review, S1-RUN-ACK and
prereg must all complete strictly before that START. If they do not, the trial is not started: disclosed and
re-registered with a new planned START, never slid silently; an audit is never reused for an unreviewed window.
A calendar or audit acquisition failure is preserved under its own attempt namespace and stops the plan.

## 5. S1-SNAPSHOTS
SQLite online backup from a `mode=ro` source connection into an isolated file, then an MR projection:
agents(id, name) for MR; trades(id, agent_id, symbol, action, shares, price, timestamp) for MR, ALL history;
portfolios(agent_id, symbol, shares) for MR; a SHA256 per trade of `reasoning` (fingerprint only); PRAGMA
table_info of each table; max ids; row counts; capture start/end. Each snapshot and projection is hashed and
preserved. No immutable=1, checkpoint, plain file copy or live-file hash.

## 6. S1-SEALS (deterministic schedule)
- **Owner:** the Task Scheduler entry runs `s1_run.py checkpoint` (read-only, counts only) for each pinned close C.
- **Schedule per close C:** first capture at C + 45 min; on an inconsistent capture (§7) up to 5 retries 2 min
  apart; if still none, one further attempt each hour on the hour until 08:00 ET of the next NYSE session day.
  Every scheduled and actual time, failure and capture is recorded and preserved.
- **Seal of C** = the first CONSISTENT capture in that schedule. Writes outside regular hours are not assumed
  impossible (late cycle finish, `force_trading`): consistency is checked regardless.
- **Unsealed close:** no consistent capture in its schedule -> C is unsealed and cannot be the stop. This is a
  registered OPERATIONAL stopping rule (the stop is "the first SEALED close with >= 100 fully sold"), reported
  with every missed seal; seal availability may correlate with activity and is disclosed as such.
- **Row fences:** a seal records every MR row id, stored timestamp and row hash. A row later observed with stored
  time <= a sealed close but absent from that seal, a new id below a previous max, or any change/deletion of a
  sealed row => ABORTED-INVALID. After the stop the frozen final ledger and the acquisition-time snapshot are
  checked against EVERY sealed slice.
- **Opening seal** = the seal of the close immediately before START (the audit ledger cut, §4).

## 7. S1-QUANTITY (operational replay vs economic FIFO)
- **Operational replay (quantity only):** per symbol, replay MR rows in (stored time, id) order applying the
  app's rule AT EACH SELL — if the symbol's aggregate remaining shares fall below 0.001 the whole position is
  written off to zero (backend/trading/portfolio.py: `pos.shares < 0.001`) — with an explicit write-off audit
  (row id, symbol, written-off quantity).
- **Consistency of a capture** = for every MR symbol, operational-replay quantity over the capture's FULL trade set
  equals portfolios(shares) (absent row = 0) within 1e-9 shares. Internal consistency only (both written by the
  same app); it is not unit validation.
- **Economic FIFO** = e1_sim baseline_lots, unchanged (E1 rules: 1e-6 oversell tolerance, 1e-12 dust snap;
  residuals stay open and are consumed by later SELLs FIFO, else marked at the stop close). The bridge between the
  two books (sum of operational write-offs vs economic residuals per symbol) is reported, never forced to zero.
- Example: BUY 10 -> SELL 9.9995 -> BUY 10: operational 0.0005 written off, holds 10 = portfolios; economic FIFO
  holds 10.0005 (lot 1 residual 0.0005 + lot 2 10); bridge 0.0005 reported; capture consistent.

## 8. S1-SOLD (registered FIFO-lot counting convention)
- A cohort lot becomes **fully sold** at the first economic-FIFO SELL allocation TO THAT LOT after which its
  remaining quantity is < 0.001 share (strict). The event is absorbing: once counted, never un-counted, and it
  does not change any economic attribution (residuals keep following §7).
- A lot with no SELL allocation is never fully sold, however small (a 0.0005-share BUY with no SELL: not
  completed). Remaining exactly 0.001 after a SELL: not fully sold; 0.000999…: fully sold.
- Two lots of one symbol: FIFO consumes the older first; each lot is counted on its own; the convention is a FIFO-
  lot count, not identity with the app's aggregate position closure.

## 9. S1-STOP and timeout
- **Stop close** = the first SEALED close C with >= 100 cohort lots (START <= stored entry <= C) fully sold by C
  (rows <= C from C's seal). Overshoot kept.
- **Timeout:** the last SEALED close <= the deadline. If none exists after START: INCONCLUSIVE (NO-VALID-SEAL);
  never a pre-START close, never an extension. If the deadline close's own seal schedule (§6) is still running,
  wait for it to end, then finalize.
- **Cohort** = every BUY with START <= stored entry <= stop close; unsold quantities marked at the stop close in
  both arms; zero-eligible lots retained; excluded lots never replaced. Exit-dependent stopping disclosed.
- No interim efficacy or futility look.

## 10. S1-COUNTS (pre-stop)
`checkpoint` reports only: snapshot/seal identity and integrity, row-fence checks, consistency and the write-off
audit (quantities only), semantic receipt match, observed process starts, calendar progress, cohort entries and
fully-sold count, stop qualification. Exclusions and market coverage: "not evaluated". It imports neither the
simulator nor the economics (enforced by tests) and emits no price, level, PnL or comparison. The operator can
still see the live app's performance: "no interim paired efficacy analysis", not full blinding.

## 11. S1-INVENTORY and units
- **Opening audit (S1-AUDIT-ACK, own namespace, no prices):** corporate actions (all split kinds, spin-offs,
  mergers, symbol/identity changes) for every symbol MR ever traded, from MR's first trade through the audit's
  publication cutoff, plus the pinned calendar. Opening lot state frozen = economic FIFO lots and operational
  replay over the opening seal's rows (hashed).
- A unit/identity action on a symbol MR held across it before START, with that symbol still held at START => S1
  BLOCKED (re-registration), never forced.
- **Opening seal -> START bridge:** the opening seal is the audit anchor, not proof of inventory at START. All
  later observed rows with stored timestamp < planned START are retained as PRE-START bridge rows, even if they
  arrive after the opening seal (e.g. a late-cycle or `force_trading` trade at 20:00 before a 09:30 START). They
  update the operational and economic opening books causally and never enter the S1 cohort. The bridge is
  captured and hashed with its row fence; all rows with START <= stored timestamp are cohort-era rows under the
  normal rules. **Bootstrap:** the first seal after START (no exactly-at-START physical capture is assumed)
  classifies rows by stored timestamp into bridge (< START) and cohort-era (>= START) and records the bridge
  hash; the design does not claim the pre-start audit verified this unseen bridge. New or changed carry-in
  identity or units not covered by the reviewed audit (including a bridge-introduced ticker) => BLOCKED before
  START if known, or INCONCLUSIVE before priced scoring if discovered after START; no unapproved extra
  acquisition, forced allocation or retrospective repair. A row genuinely backdated to <= an already sealed close
  still follows the §6 invalidation rule.
- **Late announcements:** the audit cannot know actions published after its cutoff. The FINAL acquisition
  re-requests corporate actions for every carry-in symbol (bridge-introduced symbols included) over MR's whole
  history through the stop (metadata only beyond the cohort window); a newly revealed pre-START unit action on a
  carry-in symbol still held at START => INCONCLUSIVE (inventory untrusted) — no whitelist, no cohort repair.
- **Paired exclusion window per cohort LOT:** entry NY date EXCLUSIVE through the common stop session INCLUSIVE,
  identical in BOTH arms, regardless of the actual or candidate exit. A lot is excluded when any unit/economic/
  identity action on its held symbol (all split kinds, spin-off/rights source, acquiree-side merger, stock
  dividend, redemption, worthless removal, special dividend) has its effective date inside that window. A lot
  entered after a fully resolved event is not excluded solely for that earlier event. Undated, unclassifiable or
  conflicting identity/action records block every lot of the affected symbol (fixed conservative rule; never
  silently dropped). If carry-in units make FIFO attribution of cohort-era SELLs untrustworthy, the inventory
  INCONCLUSIVE rule applies instead. Ordinary dividends: not cash flows (price-only, disclosed).
- **Required bars per lot:** every eligible post-entry session through the stop session plus the stop close, which
  is always required (endpoint-day entries included); a missing or flagged required bar excludes the lot in both
  arms.
- Validation order before any priced work: schema -> units -> quantities (operational and economic) -> prices.

## 12. S1-EPOCH (receipt, restarts, continuity)
- **Semantic receipt** (prereg; re-captured at every seal; must stay identical): live checkout HEAD and dirty
  list; SHA256 of the MR dependency closure (backend/agents/mean_reversion_agent.py, backend/agents/base_agent.py,
  backend/trading/portfolio.py, backend/trading/risk_manager.py, backend/loops/trading_loop.py,
  backend/lifespan.py, backend/database.py, backend/config.py, backend/logging_setup.py and their in-repo
  transitive imports by an AST import walk — a file list, not proof of runtime loading); hashes of the MR-relevant
  effective config values; runtime Python and package versions.
- **Process observations** (not compared): PID and start time on :8000 at each seal; and the app's own append-only
  restart record — `[PROCESS START] pid=…` lines in backend/logs/crash.log (backend/logging_setup.py) — with the
  file's size/hash at each seal. Restart counts are reported as "observed in crash.log" (minimum), never as a
  complete history; a truncated/rotated/deleted crash.log or a PID change without a new PROCESS START line is a
  reported observation gap.
- **Restarts (operator):** allowed; reported with times; part of the baseline.
- **Semantic change** detected at any seal => ABORTED-INVALID from that seal.
- **Binding and continuity attestations (operator), in causal order:**
  - START attestation (recorded before S1-RUN-ACK/prereg): the backend runs from the recorded checkout after the
    receipt. It binds the trial ID, planned START, semantic receipt and the opening-seal/audit artifacts and their
    hashes.
  - Stop attestations (recorded after the stop, before any paired result is computed): between START and the stop
    (a) no MR-relevant code, config or package was changed (including changed-and-reverted), and (b) no MR trade
    was placed or edited by hand. They bind the START-attestation artifact and hash, the actual START and stop, and
    the sealed final-ledger hash.
  - Missing required binding, continuity or manual-trade attestations prevent a verified nomination under the
    UNVERIFIED-PROVENANCE rule (§14).

## 13. S1-ACQUIRE (final)
S1-ACQUIRE-ACK, one attempt, no earlier than the close of the 3rd NYSE session after the stop (fixed operational
lag, not a completeness claim). Scope: SIP raw daily bars for every MR-held symbol START..stop (carry-in and
cohort); corporate actions per §11 (carry-in symbols over MR's whole history; cohort symbols over the window).
E1 collector discipline: raw pages, pagination, manifest, hashes, coverage report; API completeness/publication
limits disclosed; no refetch, whitelist growth or endpoint change. Failure => ABORTED, preserved.

## 14. S1-VERDICT
- Paired, same retained lots in both arms: baseline = recorded MR exits (economic FIFO, full history) vs P13.
- **SHADOW PASS** iff equal-lot mean return AND mean dollar PnL are strictly higher for P13 at 5 bp AND 10 bp
  (exact arithmetic; total reported).
- Dispositions, in order: protocol/snapshot/seal/receipt failure, semantic change or backdated row =>
  ABORTED-INVALID; BLOCKED (pre-START units); NO-VALID-SEAL; untrusted inventory => INCONCLUSIVE; > 10% distinct
  excluded lots of the original N (exactly 10% allowed) => INCONCLUSIVE; < 30 retained => INSUFFICIENT; else PASS
  or FAIL. A timeout with too few lots is not a FAIL.
- **Provenance:** without both stop attestations the result carries UNVERIFIED-PROVENANCE. A numeric pass with
  UNVERIFIED-PROVENANCE is NOT a verified SHADOW PASS nomination; it is reported only as a flagged exploratory
  result.
- Report: N/K/retained, every excluded ID/reason/notional share, zero-eligible lots, missed seals, observed
  restarts, the operational/economic quantity bridge, holding-age and symbol concentration, totals, E1's
  descriptive fixed-seed symbol-cluster bootstrap with its guards. None alters the verdict. 100 is a feasibility
  horizon, not a power calculation.
- Meaning: a verified SHADOW PASS nominates (does not approve) a separately reviewed live MR exit change; FAIL
  means no nomination from this trial.

## 15. S1-GATES
design agreement -> operator-reviewed spec -> reviewed code (counts, adapter, collectors, scheduler entry) ->
metadata plan with planned START -> S1-AUDIT-ACK -> one audit + calendar + review -> semantic receipt + START
attestation -> exact-hash S1-RUN-ACK + prereg, strictly before planned START -> sealed counts-only checkpoints ->
stop -> stop attestations bound to the sealed final ledger -> S1-ACQUIRE-ACK -> one acquisition + review ->
S1-SCORE-ACK -> one exclusive score -> independent replication. Separate namespaces; every attempt, capture and
seal preserved; aborts disclosed, never auto-retried.

## 16. S1-EXAMPLES (expected outcomes, agreed before code)
1. Capture between a trade commit and its portfolio upsert -> inconsistent; retried per §6; all preserved.
2. Capture containing a trade stored after C -> excluded from C's as-of rows; full-set consistency still checked.
3. BUY 10 -> SELL 9.9995 -> BUY 10 -> operational write-off 0.0005, consistent; economic FIFO 10.0005; bridge
   reported; lot 1 counted fully sold at that SELL.
4. Two same-symbol lots 10 and 10, SELL 10 -> lot 1 fully sold, lot 2 not.
5. BUY 0.0005, no SELL -> not fully sold.
6. Lot remaining exactly 0.001 after a SELL -> not fully sold; just below -> fully sold.
7. Row later observed with stored time before a sealed close -> ABORTED-INVALID.
8. Trade executed before START, stored after it -> cohort member (stored time), limitation reported.
9. Manual MR row without operator attestation -> UNVERIFIED-PROVENANCE; a numeric pass is not a nomination.
10. Restart with identical files (trailing peaks reset) -> observed restart reported, trial continues; changed MR
    source hash at a seal -> ABORTED-INVALID.
11. PID change with no new PROCESS START line -> observation gap reported.
12. Split on a carry-in symbol with no new cohort BUY, still held at START, known at audit -> BLOCKED; revealed only
    by the final acquisition -> INCONCLUSIVE.
13. 99 -> 103 fully sold at one sealed close -> stop there with every entry through that close.
14. The only qualifying close is unsealed -> not the stop; the next sealed close is evaluated.
15. Deadline on a holiday / missing day-of-month -> last sealed close <= deadline; no sealed post-START close ->
    NO-VALID-SEAL.
16. RUN-ACK/prereg not done before planned START -> trial not started; re-registration.
17. The counts command cannot import the simulator or economics and emits no price or PnL.
18. Mismatched hash, early ACK, duplicate acquisition or reservation -> no request, no output.
19. Opening seal 16:45; an MR BUY of a NEW ticker and a SELL of an audited carry-in lot are stored at 20:00, START
    is 09:30 next day -> both are PRE-START bridge rows: opening books updated, neither in the cohort; the new
    ticker is added to carry-in metadata coverage; the first post-START seal records the bridge hash.
20. That bridge ticker turns out (final acquisition) to have had an unaudited split before START while still held
    -> INCONCLUSIVE before priced scoring; no repair.
21. A split effective before a lot's entry date (resolved) -> that lot is not excluded; a split inside the lot's
    window -> excluded in both arms even if the baseline sold before the split date.
22. An undated corporate-action record naming a held symbol -> every lot of that symbol excluded.
23. An endpoint-day entry with a missing stop close -> excluded (stop close always required).
