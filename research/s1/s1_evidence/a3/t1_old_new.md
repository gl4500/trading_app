# Task 1 old -> new (intended semantic change)

test_s1_t12_a3_a8.py::test_a3_bundle_is_the_explicit_file_list_plus_the_three_document_hashes

- line 28-29, BUNDLE tuple:
  - old: `(..., "s1_gates.py", "s1_receipt.py", "s1_run.py", "s1_seal.py", "s1_snapshot.py")`
  - new: `(..., "s1_gates.py", "s1_journal.py", "s1_receipt.py", "s1_run.py", "s1_seal.py", "s1_snapshot.py")`
  - why: A3.1 (map row 2): every new s1_*.py is a listed bundle member; s1_journal.py is new in Task 1.
- line 90-92, docstring: "the sha256 of the v5 design, the spec and this addendum (the addendum's own hash included)"
  -> "the pinned document hashes (the v5 design, the spec, this addendum with its own hash, and every later pinned
  addendum and erratum)". why: DOC_PINS gains Addendum 3 (d9dd3759...) and Erratum 1 (b0346466...), map row 1.
- assertion values: unchanged (the test compares against c.DOC_PINS and BUNDLE, both updated).
- test name: unchanged (the plan and the Task 15 mutant map refer to it by this name).
