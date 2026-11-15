# A3 H5c-FIX: old / new (Codex X-16 / H5C-CX-1: distinct-observation confirmation in the score's pre-INTENT path)

Base ca13ab6feeb35a515dbd03376cc103f29db3ec0d (H5d). Only `research/s1/` changes. Frozen docs untouched. No map row.
Includes the amendment round A1-A3 (Codex `repair_design_comment_v1.txt`, CONDITIONAL_CONSENSUS, adopted in full by
the controller).
Line endings: s1_run.py, s1_slot.py and s1_tests/test_s1_a3_score.py are LF before and after (0 CR bytes in each,
`tr -cd '\r' | wc -c`). h5cfix_red/green/mutants.txt carry CRLF lines where they embed captured Windows pytest output
(evidence files, not source).
Authority: `C:/Users/gl450/.coordination/trading_app/h5c_2b9beef_review_20261115/review_v1.txt` X-16 and its
"Related review question"; `repair_design_comment_v1.txt` A1-A3; brief `task-H5cFIX-brief.md`.

## Product changes (old -> new)
| site (line on the H5c-FIX tree) | old (ca13ab6) | new |
|---|---|---|
| s1_slot constants (:536-541) | - | kinds `QE_MISSING`="missing-or-unreadable", `QE_DIFFERS`="differs-from-detail"; A1 categories `QE_ABSENT`="typed-absence", `QE_UNPARSEABLE`="unparseable", `QE_SHAPE`="required-shape" (`QE_CATEGORIES`); `_identity_text(v)` (a non-empty str) |
| s1_slot.QualifiedEvidence (:548) | a bare ValueError subclass: the message was its only content | keyword-only `subject`, `kind`, `category`, `member`, `commitment` (class defaults None); `super().__init__(msg)` keeps `e.args == (msg,)`, so `str(e)` is byte-identical. `identity` VALIDATES (A2): `(subject, QE_MISSING, category, member)` when subject and member are non-empty str and category is in QE_CATEGORIES; `(subject, QE_DIFFERS, commitment)` when subject and commitment are non-empty str; otherwise **None** |
| s1_slot._classify typed-absence branch (:621-624) | the FileNotFoundError of the direct read was re-raised unchanged | the same exception re-raised, carrying `e.qualified_member = _member_name(out, path)` (the expected member's path relative to s1_out, posix), set AT the direct read (A1: identity attached at the observation source). The root-gone and generic-OSError branches are unchanged: QualifiedUnreadable (C5.1) |
| s1_slot._member_fault (new, :1020) | - | the category/member of a member-local fault from WHERE it was observed: before the resolution bytes were read, only a FileNotFoundError carrying `qualified_member` -> (QE_ABSENT, that member); after, ValueError (UnicodeDecodeError, JSONDecodeError) -> (QE_UNPARSEABLE, resolution), KeyError/TypeError -> (QE_SHAPE, resolution); anything else -> {} (no identity) |
| s1_slot._resolution_evidence (:1036-1054) | one try: manifest, names, read, json, ["evidence"]; both raise sites set only the text | the same operations in the same order and the same except tuple; `parsed` (the resolution relpath) is set only after `_read_member` returned. Raise site 1 (`... missing or unreadable ({type})`) adds `subject=q.subject, kind=QE_MISSING, **_member_fault(e, parsed)`; raise site 2 (`... differs from the committed detail (F3)`) adds `subject=q.subject, kind=QE_DIFFERS, commitment=q.detail`. Texts byte-identical (pinned) |
| s1_run.score `except s1_slot.QualifiedEvidence` (:805-807) | the first exception was discarded; `_pre_intent_qualified(gv, out, pr, stop_row, mailbox)` | `except ... as e:` -> `_pre_intent_qualified(..., first=e.identity)`: only the (validated) identity tuple crosses into the confirming pass |
| s1_run._pre_intent_qualified (:844) + `_qe_label` (:838) | re-read rows, recompute over `pr["calendar"]`; ANY second QualifiedEvidence -> `evidence_violation` | a fresh pass (below). Confirms only when `first is not None and e.identity == first` -> `evidence_violation(gv, [str(e)], "score", mailbox)` (TRIAL-INVALID registration-artifact + local abort, on the confirming observation's text). Otherwise -> `SystemExit("score refused: a QUALIFIED tree problem was not confirmed on a re-read (first <label>; re-read <label>): refused with no row")`, label = `<subject> [<kind>, <category>, <member>]` / `<subject> [<kind>, <commitment>]` / `unidentified`. Clean recomputation and OSError/JournalError/... texts unchanged |

## Identity (A1, A2): the chosen invariants
- **Member-local fault (QE_MISSING):** identity = (slot subject, QE_MISSING, category, expected member).
  - QE_ABSENT: the C5.1 typed absence: the FileNotFoundError of ONE direct read of the specific expected member (any
    member of the qualified tree: report, resolution, capture/backup.sqlite3, meta.json, projection.json), named by
    `_classify` at that read. It confirms only when the confirming pass's direct read of THE SAME member raises
    FileNotFoundError again (same slot, same member).
  - QE_UNPARSEABLE / QE_SHAPE: the resolution member was read but is not decodable/JSON, or parses without the
    required shape (KeyError "evidence", TypeError a non-dict). These are always the resolution member (the only
    member parsed here).
  - A generic I/O fault (PermissionError, any non-FileNotFoundError OSError) and a FileNotFoundError with s1_out
    gone never reach QualifiedEvidence: `_classify` raises QualifiedUnreadable (a SystemExit; unchanged, C5.1), which
    propagates as a refusal. The FileNotFoundError tag exists only on the root-ok branch.
  - The exception type name in the message is no part of the identity (the category is).
- **Tree mismatch (QE_DIFFERS):** identity = (slot subject, QE_DIFFERS, committed detail of the slot's QUALIFIED row).
  The invariant is "the committed QUALIFIED tree is not reproduced by the live members on both passes". It does NOT
  require the same live bytes or the same differing member (A1 explicitly permits the whole-tree commitment as the
  identity). Consequence: member X changed on pass 1 and member Y of the same slot changed on pass 2 confirms (the
  same commitment is broken twice); a different slot, or a member-local fault on the other pass, does not.
- **Missing / invalid identity (A2):** `identity` is None for an unset or empty subject, an unknown kind, a QE_MISSING
  without a known category or a member, or a QE_DIFFERS without a commitment. A None identity in either pass refuses
  with no row ("unidentified"); None == None never confirms. No product raise site produces one.
- **Ordering:** `sampled_seals` raises on the FIRST problem in eligible close (date) order, so each pass carries one
  observation; only that raised observation is compared. If the first observation A persists but an earlier close now
  raises B, A is not confirmed -> refused with no row (conservative; accepted by Codex). No completeness is claimed.

## The confirming pass is a fresh pass (brief item 4; A3)
In order, inside the same `try` (mirrors s1_slot.confirmed_close_problems):
1. **Rows:** `j.read_trial(gv.trial.trial_id, gv.trial.genesis, gv.mailbox)`.
2. **Calendar:** `s1_slot._calendar(gv)`; None or `!= pr["calendar"]` -> refused with no row (G3.1). The recompute uses
   this fresh calendar.
3. **Bundle (OP-14):** `c.bundle_sha256() != gv.trial.bundle` -> refused with no row.
4. **Pin (G3.2), the EXECUTED path** (asserted by the real end-to-end tests by recording the caller of every `c.sim()`
   call per phase): (a) the helper's explicit `c.sim()` after pass 1 and before the recompute (caller
   `_pre_intent_qualified`), then (b) inside the recompute, `s1_seal._close(day, sim=None)` -> `c.sim()` for every
   eligible close and schedule (caller `_close`). `c.sim()` is `load_pinned`, which re-hashes e1_sim.py on EVERY call
   and raises SystemExit on a mismatch (only the loaded module object is cached, keyed by path and approved hash).
   A failure is that SystemExit: a refusal with no row (test `..._verifies_the_pin_again`, mutant M5).
5. **Trees:** `z.sampled_seals(out, rows, fresh, start, upto_seq=stop_row.seq)` -> `_resolution_evidence(..., ps=None)`
   -> `_qualified_manifest(..., ps=None)`: every member read and hashed again; there is no pass object, so no tree/hash
   memo exists to cross passes (asserted: `_qualified_manifest` is called for the slot in both passes, always with
   ps None; mutant M15 installs a cross-pass memo and is killed).
Kept from the command (its verified identity, as `day` in confirmed_close_problems): START (`pr["start"]`), the STOP
row's seq, and `pr["calendar"]` as the comparison value. Nothing else of the first pass reaches the confirming pass.

## Test changes (old -> new); node ids (all in s1_tests/test_s1_a3_score.py)
| old | new |
|---|---|
| `_qe(msg)` built an identity-less QualifiedEvidence | `_qe(msg, subject, kind, category, member, commitment)` sets a VALID identity after construction (the same object on the base); the product's `identity` validation applies to it (A2). `_label(e)` is the oracle's own rendering. The 4 existing H5c nodes keep their assertions and outcomes |
| - | **27 new nodes**: `test_h5cfix_different_slots_do_not_confirm_each_other`; `test_h5cfix_same_slot_changed_kind_does_not_confirm[missing-then-differs\|differs-then-missing]`; `test_h5cfix_same_slot_changed_evidence_does_not_confirm[category\|member\|commitment]`; `test_h5cfix_same_identity_twice_is_invalid[missing-or-unreadable\|differs-from-detail]` (controls); `test_h5cfix_a_missing_or_invalid_identity_never_confirms[untagged\|no-subject\|empty-subject\|unknown-kind\|missing-no-category\|missing-unknown-category\|missing-no-member\|differs-no-commitment]` (A2); `test_h5cfix_confirming_pass_calendar_is_fresh[unreadable\|differs]`; `test_h5cfix_confirming_pass_checks_the_bundle`; `test_h5cfix_confirming_pass_verifies_the_pin_again` (A3 pin-failure control, no row); `test_h5cfix_raise_site_texts_and_identity_are_pinned` (both texts byte-identical; identities for differs, absent backup, absent resolution, JSONDecodeError, UnicodeDecodeError, KeyError, TypeError; PermissionError stays QualifiedUnreadable); `test_h5cfix_real_raise_sites_confirm_only_the_same_observation[same-differs\|moved-differs\|same-absent-member\|different-absent-members\|absent-then-malformed\|same-malformed]` (end to end through the real sampled_seals/_resolution_evidence with real file damage between passes; A3 pin-path and no-memo assertions) |

Node count: H5d collected count 5723 + 27 = 5750 (collect-only on this tree; reconciled in h5cfix_full.txt).
