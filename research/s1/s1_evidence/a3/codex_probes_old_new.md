# Codex probes: old -> new (plan "Codex probe old -> new map", F10 "Codex probes")

The historical probes are frozen, byte-identical, under `codex_probes_historical/` (sha256 in its `SHA256SUMS`;
never collected: the conftest `pytest_ignore_collect` hook, proven by
`test_s1_a3_codex_probes.py::test_historical_probe_copies_are_never_collected`). Their result JSON files are the
historical observations ("intended old behavioural failures"). They are recorded here separately from any fixture or
setup incompatibility.

## Task 5 row

| historical probe | old observation (frozen JSON) | new test | new expected | result |
|---|---|---|---|---|
| test_codex_combined_damage.py::test_bundle_change_plus_damage[missing] | bundle-bootstrap-missing.json: refusal "inconsistent pre-registration state … (B3.2: nothing is registered, nothing is aborted)", `abort: null`, then `restoration_resumes: true` | test_s1_a3_codex_probes.py::test_combined_damage_is_invalid_bundle_after_any_journal_row[missing] | INVALID (bundle) + local aborted.json (reason bundle); restored files + aborted.json deleted -> still refused "trial INVALID (reason/bundle)"; spies zero | RED on the stub (DID NOT RAISE), GREEN after (t5_red.txt, t5_green.txt) |
| …[unparseable] | bundle-bootstrap-unparseable.json: same | …[unparseable] | same | same |

Intended old behavioural failure: the historical JSON records `restoration_resumes: true` (restoring the files resumed
the trial). The new expectation is the opposite (F6.4 persistence after any journal row, F0.6 irreversibility).

Fixture / setup incompatibilities seen when the new file runs: none. The new test builds its state with the migrated
`s1_state` (journal rows from the audit stage on; OPENING- and RUN-ACK through `s1_trial.token`) and calls
`do_prereg` itself, as the historical probe did.

## Rows owned by later tasks (not run here)
publication-offset-{-1,0,1}.json (T6), v1-selective-deletion.json and prereg-restoration.json (T10): frozen now,
their new tests arrive with those tasks.

## Provenance note
The seven result JSON files are copied from the scratchpad `codex_repro/` folder named in the brief (Oct 29 re-run of
the three probes). Four of them (publication-offset-*.json, v1-selective-deletion.json) differ from the Oct 18
originals in `.coordination/trading_app/s1_t12_codex_review_c9b4322_20261018/` only in recorded hash values (tmp-path
dependent); the two bundle-bootstrap JSONs and prereg-restoration.json are byte-identical to the originals. The three
XML files are the Oct 18 originals from the coordination folder.
