# A3 Task 15b: anchor and killer drift map (controller anchor ruling)

Base 5b4fe84ed8f0691702133a30fcfaa78fa5dd5f54. The plan's MUTANTS table (Task 15 Step 3) was written before Tasks H1-H5.
Every anchor was resolved in the CURRENT function source at the base (`inspect.getsource`, dedented, exactly as the
child plugin does) and every killer node id was re-collected (`pytest --collect-only`). Rule applied: an anchor that
occurs exactly once with an unchanged meaning is kept; a renamed/moved function or a changed anchor text for the SAME
semantic rule is re-anchored here (old -> new, reason, file:line of the rule); a rule that no longer exists would be
`not-installed` with a reason. No different rule was substituted under any mutant id.

Result: 23 plan mutants - 19 kept verbatim, 4 re-anchored, 0 not-installed. Killer drift: 1 killer moved (renamed
file), 11 plan killers are parametrized (the exact parameter id chosen is in t15_agreed_assertions.json). The 12 R6 additions
are new (no plan anchor); their anchors are listed with the rule's file:line for review.

## Plan mutants kept verbatim (anchor occurs exactly once, same meaning)

| mutant | target | rule at |
|---|---|---|
| deadline-intent-ge-to-gt | s1_journal._slot | s1_journal.py:427 |
| deadline-qualified-ge-to-gt | s1_journal._slot | s1_journal.py:429 |
| deadline-timeout-lt-to-le | s1_journal._slot | s1_journal.py:431 |
| deadline-missed-lt-to-le | s1_journal._slot | s1_journal.py:433 |
| omitted-envelope-input | s1_run.attest_start | s1_run.py:500 |
| omitted-verify-ack-field | s1_trial.verify_ack | s1_trial.py:672 |
| omitted-check-journal | s1_trial.verify_ack | s1_trial.py:675 |
| owner-4a-actor-removed | s1_journal._slot | s1_journal.py:394 |
| owner-timeout-op-removed | s1_journal._slot | s1_journal.py:396 |
| owner-recovery-own-op | s1_stage.recover | s1_stage.py:521 |
| scope-window-full-swapped | s1_collect.final_policy | s1_collect.py:613 |
| scope-full-history-start | s1_collect.final_policy | s1_collect.py:614 |
| cutoff-reservation-clock | s1_collect.do_audit | s1_collect.py:413 |
| erratum-finalizer-takes-work-lock | s1_slot.finalize_close | s1_slot.py:890 |
| erratum-seal-ignores-close | s1_trial.closed_in | s1_trial.py:397 |
| erratum-stop-fence-removed | s1_slot.stop_fence | s1_slot.py:986 |
| erratum-non-official-close-counts | s1_trial.acks_from | s1_trial.py:156 |
| erratum-backup-dropped | s1_slot.CAPTURE_TREE (tuple) | s1_slot.py:26 |
| erratum-blocked-close-rederived | s1_trial._close | s1_trial.py:270 (now inside the per-candidate loop, 8-space indent; the 4-space anchor still matches once and the replacement keeps the indent) |

## Plan mutants re-anchored (same rule, changed function or text)

| mutant | old (plan) | new (15b) | reason | rule at |
|---|---|---|---|---|
| omitted-evidence-manifest | `s1_trial.opening_manifest_check`: `if got != a.fields["evidence_manifest_sha256"]:` -> `if False:` | same function: `got = _manifest_sha(gv.root, gv.rows, seq)\n    if got == want:` -> `...\n    if True:` | Task 7 I1 / H-era rewrite: the check is now an early `return` on a match (`want` = the ACK field), then a confirming re-read before INVALIDATE. The plan anchor text no longer occurs (0). The mutant makes the FIRST comparison always return, i.e. a mismatch never reaches INVALIDATE - the same omitted E5.5 check. | s1_trial.py:566-568 |
| stop-n-ge-to-gt | `s1_seal.stop_record`: `>= STOP_N` -> `> STOP_N` | `s1_seal._stop_record`: `_close(d, sim=pinned(px))) >= STOP_N:` -> `... > STOP_N:` | H5b split stop_record into a pass-owning wrapper and the pass-scoped `_stop_record`. The plan anchor still occurs once in `stop_record` - but ONLY in its docstring (s1_seal.py:634); kept, it would have "installed" a docstring edit. Re-anchored to the code. | s1_seal.py:670 |
| stop-pending-removed | `s1_seal.stop_record`: `if stt == "pending":\n            return None` -> `if False:...` | `s1_seal._stop_record`: `if stt in ("pending", "unresolved"):` -> `if stt == "unresolved":` | H5b split (as above), and the pending and unresolved branches are now one test. The mutant removes only the pending half (unresolved still blocks), which is the plan's rule. | s1_seal.py:661 |
| stop-prefix-le-to-lt | `s1_seal.sampled_seals`: `x.seq <= upto_seq` | `s1_seal._sampled_seals`: same text | H5b split: the prefix filter moved into the pass-scoped `_sampled_seals` (0 occurrences in `sampled_seals`). | s1_seal.py:610 |

## Killer drift

| mutant | plan killer | 15b killer (selection; agreed node id in t15_agreed_assertions.json) | change |
|---|---|---|---|
| deadline-qualified-ge-to-gt | test_s1_a3_slots.py::test_publication_at_d_and_d_plus_1us_does_not_seal | test_s1_a3_codex_probes.py::test_publication_at_d_and_d_plus_1us_does_not_seal, agreed `[0]` | moved to the Codex-probes file (absent from test_s1_a3_slots.py at the base); parametrized offset_us [0, 1]; [0] (R == D) is the `>=` boundary |
| deadline-intent-ge-to-gt / owner-timeout-op-removed | test_precedence_table | same, agreed `[6-si-at-e]` / `[4a-t-foreign-op]` | parametrized (table ids) |
| omitted-verify-ack-field | ...verifies_the_opening_ack_against_the_journal | same, agreed `[seal-differs]` | parametrized |
| omitted-check-journal | test_journal_seq_and_head_must_be_extended_without_fork | same, agreed `[wrong-head]` | parametrized |
| omitted-evidence-manifest | test_opening_ack_evidence_manifest_is_reconstructed | same, agreed `[wrong-hash]` | parametrized |
| stop-n-ge-to-gt | test_stop_dispositions | same, agreed `[lots-earliest]` (exactly 100 = STOP_N sold) | parametrized |
| owner-4a-actor-removed | test_foreign_qualified_is_invalid_even_on_a_terminal_slot | same, agreed `[foreign-actor]` | parametrized |
| owner-recovery-own-op | test_stage_state_table | same, agreed `[prepared-lock-free]` (the recovery path) | parametrized |
| cutoff-reservation-clock | test_cutoff_is_the_intent_new_york_date_across_midnight | same, agreed `[midnight]` | parametrized |
| erratum-non-official-close-counts | test_non_official_lines_are_never_candidates | same, agreed `[wrong-role-close]` | parametrized |

Every other plan killer exists unchanged and is not parametrized.

## R6 additions (controller ruling R6; not in the plan table)

| mutant | family | target | anchor -> mutation | rule at | killer (existing) |
|---|---|---|---|---|---|
| r6-books-economic-in-foreign-module | H5b s1_books: another module than the pass's | s1_books._economic_in | `return s1_seal.pinned(px).baseline_lots(` -> `return c.sim().baseline_lots(` | s1_books.py:118 | test_s1_a3_h5b_pass.py::test_h5b_fifo_replay_uses_this_pass_module[stop_record] |
| r6-books-sold-events-foreign-module | H5b s1_books: another module than the pass's | s1_books._sold_events | `limit = s1_seal.pinned(px).x(c.SOLD_LT)` -> `limit = c.sim().x(c.SOLD_LT)` | s1_books.py:132 | same |
| r6-books-economic-in-entry-guard-dropped | H5b s1_books: entry guard dropped | s1_books._economic_in | `s1_seal._live(px)` line deleted | s1_books.py:116 | ...helpers_fail_closed_without_a_live_pass[missing-books._economic_in] |
| r6-books-sold-events-entry-guard-dropped | H5b s1_books: entry guard dropped | s1_books._sold_events | `s1_seal._live(px)` line deleted | s1_books.py:130 | ...helpers_fail_closed_without_a_live_pass[missing-books._sold_events] |
| r6-books-fifo-prefix-off-by-one | H5b s1_books: FIFO replay off-by-one | s1_books._sold_events | `_economic_in(px, prefix, ...)` -> `_economic_in(px, prefix[:-1], ...)` (the SELL's own row left out of its replay) | s1_books.py:139 | test_h5b_pass_fifo_replay_equals_public_sold_events |
| r6-strict-enum-nested-oserror-swallowed | H4-CX strict enumeration | s1_common.strict_glob | nested `_scan` OSError swallowed (H4-CX runner's `helper-swallows-nested-oserror`, same text) | s1_common.py:159 | test_s1_a3_strict_enum.py::test_gate_stray_capture_enumeration_failure_refuses[captures-root-permission] |
| r6-listing-refusal-not-held-until-e55 | H4 held unreadability / E5.5 | s1_trial.gate | `except c.ListingRefusal` -> `except KeyboardInterrupt` (H4-CX `gate-does-not-hold-listing-refusal`, same text) | s1_trial.py:890 | test_gate_listing_refusal_held_until_e55[captures] |
| r6-early-refusal-runs-finalizer | H5a/H5c no early-refusal finalizer | s1_checkpoint.run_checkpoint | a refused SLOT-INTENT runs `_finalize_others` before re-raising | s1_checkpoint.py:557 | test_s1_a3_eligibility.py::test_eligibility_refusal_triggers_no_finalizer[no-stop-decision] |
| r6-diagnostic-torn-tail-not-completed | H5a-FIX2 diagnostic serialization / torn tail | s1_slot.record_early_refusal | `data = _tail_completion(fd, end) + line` -> `data = line` (H5a-FIX2 `no-tail-check`) | s1_slot.py:342 | test_s1_a3_early_refusal_tail.py::test_tail_completion[no-terminator] |
| r6-typed-identity-kind-ignored | H5c-FIX typed member identity | s1_run._pre_intent_qualified | identity compared by subject only (H5c-FIX `M2`) | s1_run.py:880 | test_s1_a3_score.py::test_h5cfix_same_slot_changed_kind_does_not_confirm[missing-then-differs] |
| r6-confirming-calendar-hash-unchecked | H5c-FIX2 strict same-bytes confirming calendar | s1_slot._confirming_calendar | the manifest-hash check deleted (H5c-FIX2 mutant c) | s1_slot.py:1295 | test_s1_a3_m4_pass.py::test_h5cfix2_confirming_calendar_helper[hash-mismatch] |
| r6-pass-held-across-seal-stages | H5b transaction / finalizer pass lifetime | s1_seal._decide_locked | one seal_pass held across every seal-stage transaction (H5b `seal-stage-single-pass`, review R-1). The H5b runner targeted the loop "in decide_stop"; at the base it is in `_decide_locked` (decide_stop's locked body) - same rule, located by function | s1_seal.py:829 | test_s1_a3_h5b_pass.py::test_h5b_stop_decision_close_passes_verify_between_seal_stages |

Families with no representative here: none of the seven R6(b) families lacked an existing killer, so no R6 gap mutant
was recorded as `untested`. The method-level mutants of the H5c-FIX runner (M10/M11: `QualifiedEvidence` methods) are
out of this mechanism's scope (Step 3: methods are Cosmic Ray's); M2 represents typed identity instead.

## Fix round 1 (controller ruling B3): killer rewrites considered for F2 and F9 - none made

B3 allows restructuring a killer that fails only inside its own setup so that the agreed oracle is an assertion or
pytest.raises at a named line in the test body, provided the meaning, inputs and expected outcome are preserved exactly.
Neither case can be restructured cleanly, so both stay findings:

- **T15-F2 deadline-missed-lt-to-le**, killer `test_s1_a3_finalizer.py::test_missed_after_e_with_its_own_op_and_no_files`.
  The mutated rule (SLOT-MISSED needs now >= E) is exercised by the killer's OWN fixture: `registered()` ->
  `conftest.s1_state` -> the opening close-out commits MISSED for the later opening-close slots at exactly E, and
  `attest_start` then refuses (F7.2 (b), s1_trial.py:531) because those slots have no terminal row. Every restructure
  either moves the oracle into setup (a `pytest.fail` guard around `registered()` - the agreed line would be a setup
  line, not the rule's oracle at finalizer.py:51) or changes the inputs (a fixture whose close-out avoids MISSED at E).
  Neither preserves the test exactly. An existing setup-free killer of the same rule exists -
  `test_s1_a3_precedence.py::test_precedence_table[6-m-at-e]` (SLOT-MISSED at now == E -> APPEND, terminal
  precedence.py:180) - but re-pointing a mutant to a different killer is not what B3 authorizes; offered to the
  controller as the candidate.
- **T15-F9 r6-books-fifo-prefix-off-by-one**, killer
  `test_s1_a3_h5b_pass.py::test_h5b_pass_fifo_replay_equals_public_sold_events`. The killer's `ctx()` helper (a plain helper called in the test body,
  test_s1_a3_h5b_pass.py:64 / :542 - not a pytest fixture, hence a `<failure>`, not an `<error>`; wording corrected in
  fix round 2, review N-1) builds a
  lots-STOPPED trial (s1_state score_ready); its decide_stop counts sold lots through `s1_seal._count_sold` ->
  `s1_books._sold_events`, i.e. the mutated function itself, so the fixture's own assertion "decide_stop committed no
  TRIAL-STOP" (conftest.py:873) fires before the body oracle (h5b_pass.py:548). The body needs that STOPPED history (its
  trades come from the sampled seals); building it without the mutated replay would change the inputs. Not
  restructured; the detection is real but at a fixture line.

No killer file was changed in fix round 1.
