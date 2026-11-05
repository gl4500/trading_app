# Historical Codex probes (frozen evidence, never collected)

Frozen by S1 Addendum 3 Task 5 (plan "Codex probe old -> new map"). These files are evidence only: never edited, and
never collected by pytest (the s1_tests conftest `pytest_ignore_collect` hook; proven by
`test_s1_a3_codex_probes.py::test_historical_probe_copies_are_never_collected`). `SHA256SUMS` lists every file here
except itself, and `test_historical_probe_copies_are_frozen` checks it.

Provenance - the folder mixes two runs of the same probes:
- `test_codex_publication.py`, `test_codex_registration.py`, `test_codex_combined_damage.py` and the seven `*.json`
  result files: copied byte-identically from the session scratchpad `codex_repro/` folder named in the Task 5 brief.
  The three probe files equal the sha256 values in the brief. The JSON files there are an **Oct 29, 2026 re-run** of
  the probes.
- `publication-probes.xml`, `registration-probes.xml`, `bundle-bootstrap-probes.xml`: the **Oct 18, 2026 originals**
  from `C:\Users\gl450\.coordination\trading_app\s1_t12_codex_review_c9b4322_20261018\` (Codex's review at c9b4322).

Of the seven JSON files, three (`bundle-bootstrap-missing.json`, `bundle-bootstrap-unparseable.json`,
`prereg-restoration.json`) are byte-identical to the Oct 18 originals in that review folder. Four
(`publication-offset--1.json`, `publication-offset-0.json`, `publication-offset-1.json`,
`v1-selective-deletion.json`) differ from the Oct 18 originals only in recorded hash values (tmp-path dependent); the
observed behaviour they record is the same. So the XML files and those four JSON files come from different runs.
