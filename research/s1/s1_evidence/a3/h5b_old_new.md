# A3 H5b: old / new (Codex Q2: one verified module per evidence pass of the stop_record -> sampled_seals -> NVS chain)

Base e3d7bc9f52e401a8b7996ac0fa33a566e5e69185 (H5c + X-16/X-17/X-18 landed). Authority: Codex ruling
`s1_h4_row439_rulings_codex_20261109/REVIEW.txt` (sha256 ef7cfe61...), paragraphs Q2, "Boundaries", "Required evidence".
Q2 is a design acceptance only; this is the implementation for review at exact head. Only `research/s1/` changes; no
map row; the cap, the evidence policy, the hash coverage, the sample and every frozen doc (s1_common.DOC_PINS) are
untouched. Line endings: s1_seal.py stays CRLF (i/crlf in git, every line CRLF after the edit); s1_run.py,
s1_books.py, test_s1_a3_score.py and the new test_s1_a3_h5b_pass.py are LF with 0 CR bytes.

## Design (the brief's suggested shape, chosen; justification)
- `s1_seal.SealPass` is a small pass-context object. It holds ONLY the pinned module this pass verified - no calendar,
  hash, tree manifest, index or file-validity result. Every evidence read in the chain stays live:
  `s1_slot._resolution_evidence` / `seal_bytes` are still called with `ps=None`, so every QUALIFIED tree member is read
  and hashed on every pass. Sharing the module never shares a validity conclusion (Q2).
- It is created only by `s1_seal.seal_pass()`, a context manager and the pass owner. The constructor refuses any
  caller that does not hold the module-private `_PASS_OWNER` token (TypeError). On block exit the pass ends:
  `_live=False` and the module reference is dropped. There is no global, no memo, no stored pass, and no "already
  verified" flag.
- `s1_seal.pinned(px)` returns the module, verified (c.sim(): load_pinned, fail closed) at its first use in the pass,
  then the same module for the rest of that pass only.
  - Lazy, not eager: the first verification happens exactly where the pre-H5b code made its first c.sim() call.
  - So exception order is byte-identical. Example: a duplicate-calendar ValueError, or nvs on rows that are not
    STOPPED (which returns False before any close instant), verifies nothing, exactly as before. Pinned by
    `test_h5b_no_module_use_no_verification`.
  - Eager verification would make a broken pin raise where the base returned False or raised a ValueError. That is a
    behaviour change Q2 did not license.
- `_live(px)` runs at the entry of every pass-scoped helper. A missing (None), foreign (`s1_slot.EvidencePass`, a
  look-alike), forged (uninitialised `SealPass`) or ended (stale) context raises
  `SystemExit("s1_seal evidence pass: no live evidence pass of this module (missing, foreign or ended): refused with no
  row ...")`. It is checked on entry, even when that helper would not touch the module (B3).
  - The pass-scoped helpers: `_eligible`, `_close_state`, `_count_sold`, `_sampled_seals`, `_stop_record`,
    `_stop_ready`, `_nvs`.
  - SystemExit is the same class as a pin failure (c.sim()), so it is never caught as a ValueError, OSError or
    BookError, and never becomes an INVALID.
- Standalone entry points stay standalone, and each establishes its own pass with one verification: `stop_record`,
  `sampled_seals`, `nvs`, `stop_ready` and `eligible_sessions`.
  - Their signatures are unchanged, except for `sampled_seals(..., *, px=None)`.
  - `px` omitted -> its own verified pass. Omitting it never skips a verification, so it is not an
    optional-module bypass.
  - `px` given -> it must be a live pass, checked eagerly. Its only user is the score's confirming pass.
- The only pass owner outside s1_seal is `s1_run._pre_intent_qualified` (the score's confirming pass, a separate pass:
  B1 "across confirming reads"). It opens its own `seal_pass()`, verifies once with `z.pinned(px)` before the recompute
  (as the base's explicit `c.sim()` did), and hands that live pass to `z.sampled_seals(..., px=px)`. Pass 1's module
  never reaches it. The call still goes through the public `z.sampled_seals` (the H5c tests hook it there).
- Every other caller (gates, stop_check / stop_gap_recover / stop_problems / current_stop, decide_stop, the stage gate's
  NVS lambda, s1_collect, s1_run.score / attest_stop / _score) calls the standalone entry points, so each call is its
  own pass. In particular:
  - the score's pre-transaction `_nvs` -> `z.nvs`, and its `z.sampled_seals`, are two passes;
  - the NVS check inside the score INTENT transaction (`s1_stage._nvs_of` -> `s1_seal.nvs`) is a third (B2);
  - stop_ready and the stop detail inside the TRIAL-STOP transaction are separate passes;
  - `_decide_locked` opens a fresh pass per close for `_close_state`, closed before that close's seal-stage
    transaction, so a pass is never held across `run_seal_stage` (B1 "later transactions").
- The verified module also reaches the economic FIFO replay: `count_sold` -> `s1_books.sold_events` had one c.sim() per
  SELL, about 200 of the 204 verifications of one stop_record on the 100-lot fixture.
  - `s1_books._sold_events(trades, pinned_module)` takes a required callable, never defaulted. The pass passes
    `lambda: pinned(px)`, so the pass is checked live at each use.
  - The public `sold_events(trades)` passes `lambda: c.sim()`: it verifies at every use, exactly as before.
  - `_economic(rs, endpoint, orphans)` and `economic_lots` are unchanged (byte for byte). The new
    `_economic_with(sim, rs, endpoint, orphans)` takes the module as a required argument; only `_sold_events` uses it.
  - Disclosure: a first draft changed `_economic`'s signature instead. test_s1_task11's Hypothesis reference
    (`_reference_sold_events` calls `b._economic(rs, ts, orphans)`) failed with a TypeError in the targeted run. The
    signature was restored and the separate helper added, so no test changed. The golden, the mutants and GREEN were
    re-run on the final code.
- H4-CX strict enumeration (c.listing / strict_glob) and the H5a SLOT-INTENT order are untouched (B5): no listing, no
  journal decision and no s1_slot / s1_journal code changes.
- I-7 (no cross-gate memo): a pass lives inside one call frame (`with`). Nothing reaches a gate object, a module
  global, a lock record, a file or another command.

## Product changes (old -> new)
| site (line on the H5b tree) | old (e3d7bc9) | new |
|---|---|---|
| s1_seal.py :25-73 (new) | - | `PASS_REFUSAL`, `_PASS_OWNER`, `class SealPass` (`__slots__` `_sim`, `_live`; the constructor refuses without the owner token), `seal_pass()` (context manager; ends the pass on exit), `_live(px)` (refuses missing / foreign / forged / ended), `pinned(px)` (verifies at first use in the pass, then the same module); `from contextlib import contextmanager` |
| s1_seal.count_sold :377 / `_count_sold` :383 (new) | count_sold -> b.sold_events (c.sim() per SELL) | count_sold unchanged (legacy stop_decision and s1_checkpoint keep it); `_count_sold(px, ...)` replays via `b._sold_events(asof, lambda: pinned(px))` |
| s1_seal.eligible_sessions :401 / `_eligible` :408 (new) | c.sim() per calendar row whose open >= START | own pass; `_eligible(px, ...)`: same comprehension, `_close(d, sim=pinned(px))` (same short-circuit order) |
| s1_seal._close_state :556 | `(index, d, cal)`; `schedule(d, cal)` (c.sim()) | `(px, index, d, cal)`; `_live(px)`; `schedule(d, cal, sim=pinned(px))` |
| s1_seal.sampled_seals :587 / `_sampled_seals` :599 (new) | own c.sim() calls per close and per seal | `sampled_seals(..., *, px=None)`: own pass when omitted, else the given live pass; body moved unchanged to `_sampled_seals(px, ...)` with `_eligible`, `_close_state(px, ...)`, `_close(d, sim=pinned(px))` |
| s1_seal.stop_record :627 / `_stop_record` :641 (new) | c.sim() per close, per schedule, per count_sold SELL | own pass; body unchanged in `_stop_record(px, ...)` apart from the module source (`_eligible`, `_close_state(px)`, `_close(.., sim=pinned(px))`, `schedule(.., sim=pinned(px))` (bound to `w_last`, one line split for length), `_count_sold(px, ...)`) |
| s1_seal.stop_ready :699 / `_stop_ready` :709 (new) | stop_record + eligible_sessions (each verifying) | one pass: `_stop_record(px)`, `_eligible(px)` |
| s1_seal.nvs :729 / `_nvs` :748 (new) | stop_record + eligible_sessions + sampled_seals (each verifying, many times) | ONE pass per call: `_stop_record(px)`, `_eligible(px)`, `_sampled_seals(px, ..., stop.seq)` - the helper chain of Q2. Same early returns (no verification when not STOPPED / not one STOP) |
| s1_seal._decide_locked :826-829 | `if _close_state(index, d, cal)[0] == "sealed" and \ stage_rows(...)...:` | `with seal_pass() as px: sealed = _close_state(px, index, d, cal)[0] == "sealed"` then `if sealed and stage_rows(...)...:` - a fresh pass per close, ended before `run_seal_stage` |
| s1_books._economic_with :77 (new) | - | `_economic` with a required `sim` (`sim.baseline_lots(...)`); `_economic` :70 and `economic_lots` unchanged |
| s1_books.sold_events :94 / `_sold_events` :104 (new) | `c.sim()` for the limit and inside `_economic` per SELL | `sold_events` -> `_sold_events(trades, lambda: c.sim())` (unchanged count, verifies at every use); `_sold_events(trades, pinned_module)` calls `pinned_module()` at the same two points (`_economic_with(pinned_module(), ...)` per SELL) |
| s1_run._pre_intent_qualified :875-877 (+ docstring) | `c.sim()` then `z.sampled_seals(out, rows, fresh, start, upto_seq=...)` (the recompute then re-verified many times inside) | `with z.seal_pass() as px: z.pinned(px); z.sampled_seals(..., px=px)` - the confirming pass owns one pass, verified once before the recompute |

## Test changes (old -> new)
| file | old | new |
|---|---|---|
| test_s1_a3_score.py::test_h5cfix_real_raise_sites_confirm_only_the_same_observation[6] (:841, docstring :783-789) | `("after1", "_pre_intent_qualified") in sims and (2, "_close") in sims` - the base's executed pin path (the owner's own c.sim(), then s1_seal._close's c.sim() inside the recompute) | `[x for x in sims if x[0] in (1, "after1", 2)] == [(1, "pinned"), ("after1", "pinned")]`: exactly one verification in pass 1 (its own pass), exactly one for the confirming pass by its owner after pass 1, none inside the confirming recompute. Stronger (an exact per-pass count); the behavioural assertions of the test are unchanged. RED at the base (h5b_red.txt: the base list has dozens of `_close` frames) |
| test_s1_a3_h5b_pass.py (new, LF) | - | 63 nodes (see the boundary-to-test map in task-H5b-report.md) |

## Fix round 1 (review task-H5b-review-verdict.md: I-1, M-1, M-2, N-1, N-2, N-3)

The first-draft design notes above about s1_books are SUPERSEDED. In particular, `_economic_with` and
`_sold_events(trades, pinned_module)` are gone.

### Product (old = round 0 -> new)
| site | round 0 | fix round 1 |
|---|---|---|
| s1_books.py | `_economic_with(sim, ...)` (a bare module) and `_sold_events(trades, pinned_module)` (a bare callable); `sold_events` delegated to `_sold_events(trades, lambda: c.sim())` | **The public part is byte-identical to the base**: `_economic`, `economic_lots` and `sold_events` are restored verbatim. Two new pass-scoped helpers (I-1): `_economic_in(px, rs, endpoint, orphans)` :110 and `_sold_events(trades, px)` :123. Each takes the s1_seal pass ITSELF, checks it on entry with `s1_seal._live(px)` (missing / foreign / forged / ended refuses), and takes the module from that pass via `s1_seal.pinned(px)` at the same two points where `sold_events` calls c.sim(). There is no module or callable parameter. s1_seal is imported inside the functions (s1_seal imports s1_books). `_sold_events` repeats the 15-line replay loop of `sold_events` rather than sharing a body that would need a module-source parameter. Equality with `sold_events` is pinned by `test_h5b_pass_fifo_replay_equals_public_sold_events`, and the golden is unchanged |
| s1_books._economic_in (N-2) | `_economic_with(pinned_module(), ...)`: the lookup ran outside the try | `s1_seal.pinned(px).baseline_lots(...)` inside `try/except ValueError -> BookError`, as in the base `_economic` |
| s1_seal._count_sold :385 | `b._sold_events(asof, lambda: pinned(px))` | `b._sold_events(asof, px)`, the pass itself |
| s1_seal.py :28 / SealPass docstring (N-3) | "held only by seal_pass: no other code can make a pass" | The owner token and `_live` are described as a guard against ACCIDENTAL reuse (a missing, foreign, ended or uninitialised context), not a security boundary: deliberate forgery, e.g. `SealPass(_PASS_OWNER)` or `object.__new__` with the slots set by hand, is always possible in Python |

### Tests (old -> new)
| test | round 0 | fix round 1 |
|---|---|---|
| `test_h5b_fifo_replay_uses_this_pass_module[stop_record, nvs, stop_ready]` (new, I-1) | - | `c.sim` returns a fresh identity-recording proxy at each verification. For two consecutive passes: exactly one verification per pass; the FIFO replay's `baseline_lots` / `x` reads are on THIS pass's proxy and no other; results equal the unproxied ones. Kills the reviewer's R-2 (mutant 5) |
| `test_h5b_pass_fifo_replay_equals_public_sold_events` (new, I-1/N-2) | - | `_sold_events(trades, px) == sold_events(trades)` on every sampled seal's trades. The same `BookError("INVALID oversell 1")`, the engine's ValueError mapped inside the try, from both |
| `test_h5b_helpers_fail_closed_without_a_live_pass` | 34 nodes | + `books._sold_events` and `books._economic_in` x 5 contexts = 44 nodes |
| `test_h5b_pin_change_before_score_transaction_refuses_with_no_row` (M-2 / M-1 authorization) | `pytest.raises(SystemExit, match=PIN)` then the row check, so the reuse mutant was killed only by a regex mismatch | Parametrized `[lots, nvs-ack-in-transaction]`. The OUTCOME is asserted first (no row, no `score/`), then the exact text `e1_sim.py: missing or hash differs from the pinned 000000000000`, then its origin: the SystemExit raised inside the `STAGE-INTENT stage/score` append. On the NVS branch the SCORE-ACK authorization (predecessor and ACK rules on the transaction's own ACKs, OP-25) is decided by that same in-transaction NVS pass |
| `test_h5b_nvs_score_ack_transaction_verifies_afresh` (new, M-1) | - | NVS-branch score: the pre-transaction nvs pass and the in-INTENT-transaction nvs pass (the authorization decision) each verify exactly once |
| `test_h5b_trial_stop_transaction_passes_verify_afresh` (new, M-1) | - | decide_stop: pre-transaction `stop_record` = 1; inside the TRIAL-STOP append, the `stop_detail` callback (`stop_record`) = 1 and the `stop_ready` callback = 1 |
| `test_h5b_pin_change_before_trial_stop_transaction_refuses_with_no_row` (new, M-1) | - | Pin flipped between the pre-transaction `stop_record` and the TRIAL-STOP append. Outcome first (no TRIAL-STOP, no stop.json), then the exact refusal, raised inside the TRIAL-STOP append |
| `test_h5b_pin_change_between_stop_decision_seal_stages_refuses` (M-2) | pin refusal and no TRIAL-STOP only; it passed under the reviewer's hoist mutant R-1 | It also asserts that exactly ONE `run_seal_stage` was entered and no row was added after the first stage's. A pass held across the stages (R-1, mutant 6) enters the second stage and fails only at run_seal_stage's own downstream pin check, so it is now killed behaviourally, not only by the counter |
| test_s1_a3_score.py::test_h5cfix_real_raise_sites_confirm_only_the_same_observation (N-1) | `[(1, "pinned"), ("after1", "pinned")]` | The verifier's caller frame is recorded again (`sys._getframe(2)`): `[(1, "pinned", "_eligible"), ("after1", "pinned", "_pre_intent_qualified")]` |

Collected: 5763 (base) + 81 (test_s1_a3_h5b_pass.py) = 5844.
