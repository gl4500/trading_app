# Correction note to tH3_red_labels.md (dated 2026-11-15, A3 H5c item 9; H3 review M-4)

`tH3_red_labels.md` is historical evidence and is not edited (its sha256 stays the one in `tH3_hashes.txt`). This note
corrects one sentence of it.

**As written (tH3_red_labels.md:44-45):** "Every `retro` row has at least one killed semantic mutant (13 mutants r1-r6,
o1-o5, o6a, o6b: all killed by an assertion or a pytest `Failed`)."

**The sentence is false as written.** The table's own `retro` rows 414 x2, 415, 417 x2, 423 and 424 carry "-" in the
mutant column: no semantic mutant was run against them.

**Corrected text:** "Every `retro` row of NEW H3 behaviour (411 x7, 412 x2, 425[route], 495, 492 x3, 493 x9 and
494 x5: 28 instances) has at least one killed semantic mutant (13 mutants r1-r6, o1-o5, o6a, o6b: all killed by an
assertion or a pytest `Failed`). The other 7 `retro` instances - 414 x2, 415, 417 x2, 423 and 424 - pin catch-up /
F1-completion behaviour that existed before H3 (Task 11); they are retro with no mutant of their own."

(28 + 7 = the table's 35 `retro` instances.)

The `retro` labels themselves are unchanged and remain legitimate. Nothing in the H3 RED/GREEN counts changes
(RED 15, `retro` 35, `ctrl` 1).
