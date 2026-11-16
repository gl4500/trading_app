# A3 Task 15b fix round 1: DRAFT equivalence arguments for the three survivors (F8, F10, F12)

Status: DRAFTS ONLY. None of these is in `EQUIVALENT` (test_s1_a3_mutants.py); an equivalence needs Codex's
independent peer sign-off (Task 15 Step 2; Agent Forum protocol: the proposer is never the sole verifier). The strict
xfail marks stay. Line numbers are at base 5b4fe84. Each draft states the exact claim, the evidence, and the strongest
objection I could construct.

## T15-F8 `r6-books-economic-in-entry-guard-dropped` - draft verdict: EQUIVALENT (proposed)

Mutation: in `s1_books._economic_in` (s1_books.py:110-120) the entry line `s1_seal._live(px)` (:116) is deleted.

Claim: for every input, the mutant's observable behaviour (return value, exception type and text, side effects) equals
the original's.

Evidence:
1. After `:116` the next statements are `try:` and `return s1_seal.pinned(px).baseline_lots(rs, ...)` (:117-118). No
   argument is read, and nothing is evaluated, before `s1_seal.pinned(px)`.
2. `s1_seal.pinned` (s1_seal.py:69-75) begins with `px = _live(px)` (:72) - the same call, on the same object, as the
   deleted line - before reading `px._sim` or calling `c.sim()`.
3. `_live` (s1_seal.py:60-66) raises `SystemExit(PASS_REFUSAL)` for a missing/foreign/forged/ended pass. The `try`
   catches only `ValueError` (:119), and `SystemExit` is not a `ValueError` subclass, so the refusal propagates
   unchanged, with the same text, exactly as from the deleted line.
4. `_live` has no side effect (a type and attribute check), so calling it once instead of twice changes nothing.
5. Reachability: the only callers are `s1_books._sold_events` (:139, after its own checks) and the H5b tests;
   `grep -n "_economic_in" research/s1/*.py` shows no other product caller.

Strongest objection tested: "the guard documents and enforces entry before the try; a future edit inside the try
before `pinned` would lose it". True, but it is a maintainability argument about future code, not an observable
difference in this code; the mutant is equivalent for the current bytes. If the controller wants the guard to be
load-bearing, the honest alternative is to delete one of the two checks in the product (not this task).

## T15-F10 `r6-books-sold-events-entry-guard-dropped` - draft verdict: NOT EQUIVALENT (a killer gap)

Mutation: in `s1_books._sold_events` (s1_books.py:123-147) the entry line `s1_seal._live(px)` (:130) is deleted.

Analysis: the next statement is `rs, events, prev_fills, by_symbol = rows(trades), {}, {}, {}` (:131), and only then
`limit = s1_seal.pinned(px).x(c.SOLD_LT)` (:132), whose `_live` check is the next pass check. `rows(trades)`
(s1_books.py:26-35) raises `BookError` for an unknown action or a non-positive/non-finite share count or price.

Counterexample (an observable difference): a dead or missing pass (`px=None`, or an ended `seal_pass`) together with
a malformed trade, e.g. `[{"id": 1, "symbol": "A", "action": "HOLD", "shares": 1, "price": 1, "ts": START}]`:
- original: `SystemExit` with the NO_PASS refusal text (from :130);
- mutant: `s1_books.BookError("trade 1: unknown action 'HOLD'")` (from :131).

Why no current test kills it: `test_h5b_helpers_fail_closed_without_a_live_pass[*-books._sold_events]`
(test_s1_a3_h5b_pass.py:464, 480) calls `b._sold_events([], px)` - with EMPTY trades `rows([])` raises nothing, and
`pinned(px)` then refuses with the same text. The difference needs non-empty malformed trades.

Reachability: in the product, `_sold_events` is called only from `s1_seal._count_sold` (s1_seal.py:391) with a live pass
(`_count_sold` itself calls `_live(px)` at :388 first), so the difference is reachable only by a direct call. That is
exactly the H5b B3 contract ("every direct / standalone helper fails closed: a missing, foreign, forged or ended pass
context refuses") - the helper-level contract the killer tests, not the caller's.

Draft disposition: a survivor, not an equivalent. Step 2/5 triage would add a killer: the existing parametrization
with a malformed non-empty trade list (`match=NO_PASS`), recorded old-fail/new-pass. Not written here (controller
ruling: no new killers in 15b).

## T15-F12 `stop-prefix-le-to-lt` - draft verdict: EQUIVALENT under every product caller (proposed, with a scope note)

Mutation: in `s1_seal._sampled_seals` (s1_seal.py:602-618) the prefix filter `x.seq <= upto_seq` (:610) becomes
`x.seq < upto_seq`: the row whose seq equals `upto_seq` is dropped.

Claim: in every product call, the dropped row is the TRIAL-STOP row, which no part of the computation reads, so the
result is identical.

Evidence:
1. Every product caller passes the seq of the TRIAL-STOP row, or None:
   - s1_run.py:797 `upto_seq=stop_row.seq`, with `stop_row = j.first(gv.rows, "TRIAL-STOP")` (s1_run.py:787);
   - s1_run.py:877 `upto_seq=stop_row.seq` in `_pre_intent_qualified`, called only at s1_run.py:806 with the
     `stop_row = j.first(gv.rows, "TRIAL-STOP")` of :787;
   - s1_seal.py:769 `_sampled_seals(px, out, rows, cal, start, stop.seq)` with `stop = stops[0]`, the TRIAL-STOP rows;
   - `upto_seq=None`: computed in `_sampled_seals` itself as `stop.seq` of `j.first(rows, "TRIAL-STOP")` (:607-609).
   (`grep -n "sampled_seals(" research/s1/*.py` lists exactly these.)
2. The filtered rows feed only `_by_subject(rows)` (:611) and `_close_state(px, index, d, cal)` (:614), which reads
   `index.get(j.slot_subject(s), [])` for the scheduled slots (s1_seal.py:571) - slot subjects only. The TRIAL-STOP
   row's subject is `trial`, never a slot subject, so its presence or absence changes no `_close_state` result, no
   QUALIFIED row and no seal bytes (the seal bytes come from `_resolution_evidence` / `seal_bytes` of the QUALIFIED
   row and the files).
3. Journal seqs are unique (`s1_journal` hash chain), so `seq == upto_seq` selects exactly that one TRIAL-STOP row.

Strongest objection: `sampled_seals` is a public function; a direct caller passing the seq of a SLOT row (e.g. a
QUALIFIED) would observe a difference (that QUALIFIED is dropped). No product caller does so, and the docstring
defines `upto_seq` as the STOP prefix ("F1 STOP prefix / OQ-14"), but the function does not enforce it. So the
equivalence holds for the product's call graph, not for the function's full input domain. A reviewer may instead
prefer a killer that calls `sampled_seals(..., upto_seq=<a QUALIFIED row's seq>)` and pins inclusion of that row -
which would test a use the product never makes. This is the open point for peer review.

## Peer review outcome (Codex, `C:/Users/gl450/.coordination/trading_app/t15b_02db5b9_review_20261116/REVIEW.txt`, fix round 3)

- **F8 `r6-books-economic-in-entry-guard-dropped`: APPROVED EQUIVALENT**, scoped as follows: "for the current
  synchronous implementation with normal fixed helper definitions". `_economic_in` evaluates no input before
  `pinned(px)`, which immediately performs the same `_live` check. Only ValueError is caught, so an invalid-pass
  SystemExit propagates identically, and the deleted check has no state effect. Outside the claim: timing and
  instrumentation, monkeypatched helper definitions, races that change the pass externally, and future edits. This
  disposes of the mutant; it is not a request to remove the product guard.
  - Entered in `EQUIVALENT` (test_s1_a3_mutants.py) with exactly that scoped reason. Its strict xfail mark (T15-F8)
    was removed, and its label is now `equivalent`.
- **F12 `stop-prefix-le-to-lt`: REJECTED as full-domain EQUIVALENT.**
  - **Counterexample** (Codex's own connected fixture; `reconciliation_equivalence.json` in the same directory
    records the row kind, seq and key difference): pass `upto_seq = 85`, the seq of a post-START SLOT-QUALIFIED row.
    - Original (`x.seq <= upto_seq`): returns close 2026-10-26.
    - Mutant (`<`): returns no close.

    This is an observable boundary change for inputs the inclusive-prefix contract supports.
  - The current-product-call-graph argument above (every product caller passes a TRIAL-STOP seq) still stands as an
    observation, but it does not cover the public helper's contract.
  - F12 stays a `survived` finding (T15-F12, strict xfail) for 15d. Two ways forward: a boundary killer, or a
    separately approved call-graph-constrained exclusion that states its coverage limit.
- **F10:** no equivalence was approved; it remains a killer gap, as drafted.
