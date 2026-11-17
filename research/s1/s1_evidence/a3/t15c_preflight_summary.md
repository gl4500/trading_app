# Task 15c pre-flights: 21 unmutated guard baselines at 30e72bb

**Authorization.** The run was authorized by Codex in t15d3_30e72bb_review_20261116/REVIEW_AND_PREFLIGHT_GO.txt, a technical GO for exactly the 21 unmutated pre-flights. The operator gave consent on 2026-11-17.

**Source.**
- A fresh `git archive 30e72bbbd7ead5e6eb9cf48803245786f6c22608 research/s1` was extracted to a scratch directory outside the repo and outside the coordination tree.
- Its a3/t15c_prep_hashes.txt (1268 entries) gave `sha256sum -c` rc 0 both before and after the run.

**How it was run.**
- Command: `testenv python -B <archive>/research/s1/s1_tests/cr_preflight.py all --src-root <archive> --work-root <scratch>/work`. This is the driver from the archive, with PYTHONPATH set to the archive's research/s1 and research/s1/s1_tests.
- Execution: sequential, 12 screening configs then 9 completion configs, one attempt each, stopping at the first not_clean. There were no reruns, no new-root retries and no state edits.
- Time: 2026-11-17 06:29:17 to 07:10:43. CLI exit code 0, stderr empty.

**Result.** All 21 were clean, each with exactly one attempt, `preflight_000`, under its `started_000` marker.

| Config | Wall time (s) |
|---|---|
| s1_journal | 4.985 |
| s1_locks | 2.453 |
| s1_trial | 57.344 |
| s1_stage | 15.094 |
| s1_slot/slots | 150.735 |
| s1_slot/finalizer | 170.187 |
| s1_seal/check | 158.703 |
| s1_seal/decide | 154.907 |
| s1_seal/record | 168.937 |
| s1_seal/sampled | 155.641 |
| s1_collect/audit | 135.797 |
| s1_collect/final | 139.719 |
| s1_slot/completion/c1 | 100.704 |
| s1_slot/completion/c2 | 103.156 |
| s1_seal/completion/c1 | 152.703 |
| s1_seal/completion/c2 | 127.563 |
| s1_seal/completion/c3 | 130.250 |
| s1_seal/completion/c4 | 137.813 |
| s1_seal/completion/c5 | 141.235 |
| s1_collect/completion/c1 | 127.672 |
| s1_collect/completion/c2 | 129.734 |

Every wall time is within the 180 s selector budget; the maximum is 170.187 s, for s1_slot/finalizer. That budget is per selector; it is not a whole-campaign guarantee. The s1_journal and s1_locks times match their historical baselines (about 4.2 s and 2.1 s).

**Records.**
- The 42 files (21 `started_000.json` + 21 `preflight_000.json`) are copied byte-identically from the archive's cr_a3/<config>/preflight/ into this commit. Their hashes are in a3/t15c_preflight_records_sha256.txt, whose own sha256 is bf4b0889fd9840b9597ee40ba1aa60709212c256bfc06536cd9e896def5d7513.
- The CLI output is a3/t15c_preflight_run_stdout.jsonl, sha256 376dd9a49d833eb95a7c1884ce2c328753328f22b197cbd2be74bcc9607cff93.
- The raw scratch work root, 521 MB in 55984 files, stays in the session scratch and is not committed. Its full hash list has sha256 1c1dff6b5614a841fba1cbbfbef08bf0b356c72c202f5d8dbea0a3f57e9bffb6 and is available on request.

**Not authorized by this run.** It is not a calibration, mutant, Cosmic Ray, full-suite, live or scheduler GO. Calibration still needs its own exact-head Codex GO.
