# A3 Task 15c-prep + 15c-H: Cosmic Ray configs, baselines, scopes, inventories, completion shards and session plan (NO mutant executed)

**Version.** This is v10, updated for 15c-P fix round 2. That round answers re-review 1
(`task-15c-p-review-verdict.md`: spec ✅, APPROVE, R1-M1 to R1-M3, plus R1-N1 to R1-N4):
- a stale `preflight_ref` is refused;
- N18 is pinned as a liveness behaviour;
- the changed paths are recorded;
- the Info items are disclosed in step 3a;
- the inventories were re-initialised again.

v9 covered 15c-P fix round 1, which answered the task review
(`.superpowers/sdd/s1_plan_addendum3/task-15c-p-review-verdict.md`: spec ❌, CHANGES_REQUIRED, Important 3, Minor 7),
following the controller's rulings 1–11.
- **Crash safety.** Every attempt now leaves a written record, and an orphaned attempt blocks.
- **Wider binding.** The whole copied tree is bound, in the pre-flight, in each completion attempt and in each
  screening item.
- **Retries** are gated on the base pre-flight.
- **`run_batch`** gates every execution unless the seam declares itself synthetic. A real_exec seam is tied to its
  `cfg`.
- **Driver hardening:** `--write-control` is refused, the after-run checks cover the whole copy, and the frozen value
  is cross-checked.
- **Harness changed again.** The inventories were re-initialised.

v8 covered Task 15c-P: the pre-flight driver of runbook step 3a. It followed Codex's exact-head review of 9330a64
(`C:/Users/gl450/.coordination/trading_app/t15chfix_9330a64_review_20261116/REVIEW.txt`: APPROVE /
CONDITIONAL_CONSENSUS, X23 and X24 CLOSED, packaging nit N1) and the controller's 15c-P brief.
- **It changes the harness.** It adds `cr_preflight.py`, which joins `HARNESS_FILES`. In `cr_coord.py` it adds
  `preflight_binding` and `check_preflight`, and gates `run_manifest`, calibration `run_batch(config=...)` and
  `run_completion` shards on them.
- **Re-initialised.** The inventories were re-initialised again, see Method → Inventories.
- v7 covered fix round 5: re-review 4 (R4-I1, R4-N1, R4-N2), plus the pre-flight and counting rulings, with no
  harness change.
- v6 covered fix round 4: re-review 3 of fix round 3 (R3-I1, R3-N1 to R3-N4), with the controller's rulings 1–5.
- v5 covered fix round 3: Codex's exact-head review of the committed 192e47c
  (`C:/Users/gl450/.coordination/trading_app/t15ch_192e47c_review_20261116/REVIEW.txt`, CHANGES_REQUIRED / NO-GO,
  X23 and X24) and the controller's rulings in `C:/Users/gl450/.coordination/trading_app/t15c_x23_x24_confirm_claude.md`.
- v4 covered fix round 2 (re-review 1).
- v3 covered fix round 1.
- v2 covered Task 15c-H.
- v1 is what Codex reviewed as `t15c_prep_review_20261116`.
- Changes are marked **[15c-H]**, **[fix-1]**, **[fix-2]**, **[fix-3]**, **[fix-4]**, **[fix-5]**, **[15c-P]**,
  **[15c-P fix 1]** and **[15c-P fix 2]**.

**Sources.**
- Briefs: `task-15c-prep-brief.md`, the 15c-H coordinator message (rulings 1–7 adopting Codex's
  `t15c_prep_review_20261116/REVIEW.txt`), the fix-round-1 message (rulings 1–7 on the task review
  `task-15c-h-review-verdict.md`), the fix-round-2 message (re-review 1), the fix-round-3 message (X23/X24) and the
  fix-round-4 message (re-review 3).
- The fix-round-1 addendum, rulings (a)–(e), draws on Codex's early number check:
  `C:/Users/gl450/.coordination/trading_app/t15ch_early_numbers_20261116/EARLY_NUMBER_CHECK.txt`.

**Head.** HEAD is **192e47c**, which holds 15c-prep and 15c-H with rounds 1–2. Its parent is 2a4bdd1. The 7 product
modules, `research/s1/docs`, `conftest.py`, `a3_helpers.py` and the 12 selector test files are byte-identical to BASE
02db5b9.

**Nothing was executed against a mutant, and no calibration ran.** The only Cosmic Ray command run was
`cosmic-ray init`, on scratch copies, through `cr_launch.py`. Product source is untouched. The fix-3 and fix-4
changes are uncommitted on top of 192e47c:
- `cr_coord.py`;
- `test_s1_a3_cr_completion.py`;
- the evidence under `s1_evidence/`.

**Interpreter.** The testenv is 3.12.12, with Cosmic Ray 8.3.15 and pytest 8.3.3. Everything ran serially, with no
xdist and a single lane (ruling 3).

## Harness changes (15c-H rulings 1–3 + fix rounds 1–4)

**Evidence files.**

| File | Run | Result |
|---|---|---|
| `a3/t15c_h_red.txt` | first 15c-H RED | Kept as recorded. A fix-1 annotation names both test-file sha256s. |
| `a3/t15c_h_fix1_red.txt` | fix-1 RED | **23 failed**: 15 AssertionError + 8 `DID NOT RAISE`. 72 passed. |
| `a3/t15c_h_fix1_green.txt` | fix-1 GREEN | **97 passed.** Also holds the deletion checks, plus a fix-2 **correction** (R1-I1). |
| `a3/t15c_h_fix2_red.txt` | fix-2 RED | **4 failed**: 1 AssertionError + 3 `DID NOT RAISE`. 102 passed. |
| `a3/t15c_h_fix2_green.txt` | fix-2 GREEN | **106 passed.** Also holds the fix-2 deletion checks. |
| `a3/t15c_h_fix3_red.txt` | fix-3 RED | **11 failed**: 3 AssertionError + 8 `DID NOT RAISE`. 106 passed. |
| `a3/t15c_h_fix3_green.txt` | fix-3 GREEN | **119 passed.** Also holds the deletion checks and the replay of Codex's v3 probe. |
| `a3/t15c_h_fix4_red.txt` | fix-4 RED | **9 failed**, all assertion-type: 5 AssertionError, 3 regex mismatch, 1 `DID NOT RAISE`. 125 passed. Plus a supplementary RED (1 AssertionError) for the case-insensitivity test, written after the main RED. |
| `a3/t15c_h_fix4_green.txt` | fix-4 GREEN | **135 passed.** |
| `a3/t15c_h_fix5_check.txt` | fix-5 plan check | 12/12 plans calibration-first and bound; `check_plans()` refuses a plain plan. No harness or test change, so there is no new RED/GREEN. |
| `a3/t15c_p_red.txt` | 15c-P RED | **35 failed**: 32 AssertionError + 3 `DID NOT RAISE`. 135 passed. Plus two supplementary REDs of the final test file against the 9330a64 harness: 47 failed, all assertion-type. |
| `a3/t15c_p_green.txt` | 15c-P GREEN | **182 passed** (three focused files). Also holds the deletion checks (**59/59 caught**) and the archive-check demonstration. |
| `a3/t15c_p_reinit_check.txt` | 15c-P re-init | 12/12 configs: specs and kept specs identical, plans calibration-first and bound, harness current (5 files). |
| `a3/t15c_p_fix1_red.txt` | 15c-P fix-1 RED | **28 failed**, all assertion-type. 183 passed. Plus a supplementary RED for the pins added during the deletion planning. |
| `a3/t15c_p_fix1_green.txt` | 15c-P fix-1 GREEN | **222 passed** (three focused files). Deletion checks: **101 deleted, 96 caught**; the 5 not caught are argued equivalent there (P10, N18, B03, B06, B07). |
| `a3/t15c_p_fix1_reinit_check.txt` | 15c-P fix-1 re-init | 12/12 configs re-initialised again, with the superseded files under `_superseded/inventories_pre_15cp_fix1/`. |
| `a3/t15c_p_fix2_red.txt` | 15c-P fix-2 RED | **3 failed**, all assertion-type: 1 `DID NOT RAISE` + 2 AssertionError. 223 passed. The R1-M2 liveness pin passes by design. |
| `a3/t15c_p_fix2_green.txt` | 15c-P fix-2 GREEN | **226 passed.** Deletion checks: **9 deleted, 9 caught**, N18 included. |
| `a3/t15c_p_fix2_reinit_check.txt` | 15c-P fix-2 re-init | 12/12 configs re-initialised again, with the superseded files under `_superseded/inventories_pre_15cp_fix2/`, verified against `a3/t15c_prep_hashes_pre_15cp_fix2.txt`. |
| `a3/t15c_h_green.txt` | regenerated GREEN | Same final files: **135 passed**. |

**[fix-3] Changes in this round** (X23/X24; controller rulings 1–7):
- **Bind at execution time (X23, ruling 1).**
  - `run_batch(binding_fn=...)` computes the binding of each item inside its disposable copy, immediately before the
    exec seam runs. It persists the binding in the state (`bindings[<job>]`) before execution.
  - The completion binding (`_attempt_binding(cfg, root, nodes, copy_paths)`) covers: python, test-command sha256,
    node-set sha256, control sha256, target source sha256, harness hashes, helper hashes (`conftest.py` /
    `*helpers*.py` on the pythonpath dirs), `pythonpath_rel`, and the child env (below).
  - Files outside `copy_paths` are ignored, so the binding is the same whether it is computed in the copy or in the
    source tree.
  - The merge and the completion record read **only** the persisted binding. A white-box test pins that the merge
    never recomputes it.
  - The containment verdict sits at attempt level, beside the identity-only binding.
- **Check identity on reuse or resume (X23, ruling 2).** Before anything runs, `run_completion` takes every existing
  attempt state of every shard: an executed attempt's persisted binding, or a refused attempt's persisted
  `planned_binding`. It compares each one field by field (env per variable) with the binding the current context
  would give.
  - Any drift raises `CoordError` naming the fields, for example `['test_command_sha256']` or `['env.PYTHONHASHSEED']`.
  - No exec runs, the state stays byte-identical, no record is written, and a fresh completion root is required.
  - A new attempt whose executed (copy) binding differs from its planned one, for example because inputs changed
    mid-run, is not merged.
  - An unchanged context reuses the cached attempt, keeping its original binding.
- **Explicit `source_sha256` (ruling 3).** It is checked against the screening item's recorded source and against
  each persisted completion binding.
- **Screening path (ruling 4): the same gap existed, and is fixed.**
  - The screening EXECUTION never reuses a result. A batch state is write-once: an existing `batch_<id>_state.json`
    is refused. Every item runs in a fresh copy, and pending items after a stop run only in a new batch, so they are
    executed fresh. `run_manifest` writes a new batch id per manifest.
  - But `run_completion` reused the screening **label** through `_screen_labels` without checking it.
  - Now `run_batch` records `copied_source_sha256[<job>]` for every executed item. `_check_screening_context` refuses
    the screening label if that source differs from the current source (or from the explicit `source_sha256`), or if
    the screening batch's recorded harness differs from the current one. Both cases are tested.
- **Effective child env (X24).** `_child_env_binding` records the allowlisted variables from the env `_env` builds
  for the child, including its enforced overrides, not `os.environ`.
  - Allowlist (**superseded in fix 4** by the prefix scrub + full prefixed binding; see [fix-4] below):
    PYTHONHASHSEED, PYTHONDONTWRITEBYTECODE, PYTHONUTF8, PYTHONIOENCODING, PYTEST_ADDOPTS,
    HYPOTHESIS_PROFILE, TZ.
  - PYTHONPATH is recorded relative to the copy root, with the `.cr_harness` entry predicted by a new side-effect-free
    `_copy_harness(..., create=False)`.
  - Job-specific values (job dir, job id, per-job Hypothesis root) are not identity.
  - Tested: with the parent's PYTHONDONTWRITEBYTECODE unset, the binding records the child's `"1"`.
- **The fix-2 `-k` assurance is corrected.** A narrowed command on a NEW attempt still fails closed through the guard
  (`node_set_mismatch`). A narrowed command against a CACHED attempt is now refused as `test_command_sha256` drift,
  where before it relabelled the cached result.

**[fix-3] Deletion checks.** I deleted 11 guards in scratch copies (`deletion_fix3/`).
- **Caught (10):**
  - the cached-drift raise and the pre-pass call;
  - the screening source check and the screening harness check;
  - child-env-vs-parent;
  - merge-never-recomputes;
  - binding persisted;
  - executed-vs-planned;
  - planned_binding recorded;
  - copied source recorded.
- **Not caught (1, equivalent):** the explicit `source_sha256` check against the persisted completion binding. It is
  defence in depth: the screening check refuses first whenever the expected source differs, and executed-vs-planned
  keeps every persisted completion source equal to the current one.

**[fix-4] Changes in this round** (re-review 3: R3-I1, R3-N1 to R3-N4; controller rulings 1–5):
- **R3-I1, child env == bound env.** This supersedes the fix-3 allowlist above.
  - `_env` now drops every inherited variable whose name starts with PYTHON, PYTEST, HYPOTHESIS or COV (compared
    upper-case, since Windows env names are case-insensitive). The exceptions are a deliberate pass list
    (`_ENV_PASS`: PYTHONHASHSEED, PYTHONUTF8, PYTHONIOENCODING) and the two variables `_env` sets itself
    (PYTHONDONTWRITEBYTECODE=1, PYTHONPATH).
  - PYTEST_ADDOPTS and HYPOTHESIS_PROFILE, bound in fix 3, are now **scrubbed**, not passed. So are PYTHONOPTIMIZE,
    PYTHONWARNINGS, PYTEST_PLUGINS, PYTEST_DISABLE_PLUGIN_AUTOLOAD, PYTHONSAFEPATH, PYTHONHOME, PYTHONSTARTUP,
    PYTEST_CURRENT_TEST, COVERAGE_* and the rest.
  - The binding (`_child_env_binding`) records **every** prefixed variable the child receives (from the same `_env`
    call), plus TZ, with PYTHONPATH relative to the copy. It no longer uses a fixed key list.
  - **Not bound, by choice:** CR_GUARD_JOB_DIR / JOB_ID and S1_HYPOTHESIS_ROOT (set by `_env` from the job dir) and
    CR_GUARD_NODES_OUT / ATTEMPT / TARGETS (popped by `_env`, set by `cr_guard` for its pytest child). `_env` always
    pops or overwrites them, so no parent value reaches the child (tested). Their values are absolute per-attempt
    paths whose only content is the attempt layout, which the hash-bound `cr_coord.py` and `cr_guard.py` fix.
    Path-relative, they would be constants that bind nothing new.
  - Tests: each of PYTHONOPTIMIZE=1, PYTEST_PLUGINS=x, PYTHONWARNINGS=error and PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 set
    in the parent is absent from the child env (captured with the production `_env(copy, cfg, job_dir, job)` call)
    and from the binding, and unsetting it before a second run reuses the attempt. The child's prefixed set equals
    the binding's. Case-insensitive matching is tested with a plain mapping standing in for `os.environ`.
- **R3-N1.** Each of the six fix-3 guards that survived deletion alone is now pinned alone:
  - X2 (screening `want`): a pin that differs from the screened source, with no cached attempt.
  - X7 (explicit source vs persisted binding): pinned directly on `_check_cached_attempts`, because through
    `run_completion` the screening check always refuses first. This replaces the fix-3 "equivalent" entry in §G.
  - X6 (missing persisted binding): a legacy state without `bindings` raises the intended `CoordError`.
  - X9 (`_dump` before the exec seam): the seam reads the state from disk and finds the binding.
  - X12 (`_in_copy` helper filter): a helper on the source tree but outside `copy_paths` is not bound.
  - X15 (binding from the copy): a copy that differs from the source (a wrapped `make_copy`) gives executed ≠
    planned.
- **R3-N2.** Drift errors no longer say "use a fresh completion root", which no API offers. They now name
  "restore the bound inputs" (cached drift only; the attempt is then reused) and "screen <job> again in a fresh
  work_root and complete it there". A test runs that second remedy through the existing API and gets `survived`.
- **R3-N3.** `run_batch(config=...)` now needs `inventory_path=` and verifies the identity's test-command sha256
  against that inventory (`_check_identity`, shared with `run_manifest`, which now passes its inventory through).
  Without the inventory, or with another config's identity, it refuses before any state is written.
- **R3-N4.** A completion shard directory moved out from under `completion/` is still refused by `run_retry`
  through its `completion_of` record (test).

**[fix-4] Deletion checks.** 17 guards were deleted, one at a time, in scratch copies outside the repo
(`_prep/tools/deletion_fix4.py`). The log is in `t15c_h_fix4_green.txt`.
- **Caught (16):**
  - the prefix scrub, the full prefixed binding (vs a fixed key list), case-insensitive prefix matching,
    case-insensitive pass-list matching, the pass list itself, and TZ bound;
  - the remedy text;
  - run_batch's no-inventory refusal and its identity check;
  - the six fix-3 guards X2, X6, X7, X9, X12 and X15;
  - the `completion_of` branch.
- **Not caught (1, equivalent):** `run_manifest`'s own identity check (G10). `run_batch` repeats it on the same
  inventory before any state is written. It is kept as defence in depth.
- An earlier pass was stopped after five mutants because it showed the fixed-key-list binding (G2) surviving. The
  agreement test was then strengthened (PYTHONUTF8 and PYTHONIOENCODING set, exact prefixed set asserted), and all
  17 were re-run against the final files.

**[fix-3] Replay of Codex's v3 cases.** I replayed `probe_resume_binding_v3.py`, original `source_sha256` included,
against this harness (`scratchpad/x23x24/replay_v3_fixed.py`):
- command, source and helper drift are each refused, with 1 exec in total and the state unchanged;
- the binding records PYTHONDONTWRITEBYTECODE `"1"` while the parent has it unset.

Output: `t15c_h_fix3_green.txt`.

**[fix-2] Changes in this round** (re-review 1):
- **R1-I1:** a test pins the kill short-circuit's clean conjunct. An unclean kill whose stop was resolved must not
  short-circuit, so a later guard-clean kill settles `killed`. The fix-1 "equivalent" claim was wrong, and is corrected
  in `t15c_h_fix1_green.txt` and in §G below.
- **R1-I2:** a test refuses a cap-record path that comes without a config identity, in `plan_batches` and in
  `run_batch`.
- **R1-N1:**
  - `read_cap_record(path)` re-checks the harness even without an identity (test).
  - A shard config with two `@argfile`s is refused (test).
- **R1-N2:** `run_retry` refuses only real completion areas: `<root>/completion`, `<root>/completion/<job>`,
  `<root>/completion/<job>/<shard>` of a coordinator work root, or states that record `completion_of`. It no longer
  refuses any path segment named `completion`, so a screening retry under such a directory runs.
- **R1-N3:** `run_manifest` refuses a config identity whose `test_command_sha256` is not that of the inventory's
  recorded `test_command`.
- **R1-N4:** each completion shard's `--control` node set must equal its `@argfile` node set, because that is what the
  guard enforces. A missing or different control is refused before anything runs.
  - All real completion `control.json` files equal their `nodes.txt`.
  - An extra selector after the argfile (`-k`) still passes the pool check. The guard would then report
    `node_set_mismatch`, giving `untested` and therefore `unresolved`, never a false kill or survivor.
  - **[fix-3] Correction (Codex X23):** that assurance held only for NEW attempts. A narrowed command against a
    CACHED attempt used to relabel the cached result. It is now refused as `test_command_sha256` drift.

**[fix-2] Deletion checks.** I deleted 8 guards in scratch copies (`deletion_fix2/`): G10, G14, G16b, G21, both N2
guards, N3 and N4. All **8 were caught**.

- All four runs used the focused files `test_s1_a3_cr_guard.py` + `test_s1_a3_cr_completion.py`, serially. Each
  record lists the sha256 of every test and harness file it ran.
- In the fix-1 RED, harness stubs had signatures only.
- Of the 72 that passed in the fix-1 RED, 61 are cr_guard tests. The other 11 completion tests pin behaviour that was
  already correct, and their guards are proven by deletion instead.

**[fix-1] Guard-clean merge** (`cr_reconcile.attempt_clean`, `merge_attempts`; ruling 1, review C1/C2). An attempt
COUNTS only if it is guard-clean:
- it is not stopped;
- `exec_status == "ok"`;
- `cleanup_verified is True`;
- (label, guard status) is (killed, killed) or (survived, survived).

The merged label:
- `killed` needs at least one guard-clean kill. Earlier non-kill records are kept.
- Otherwise, any attempt that is not guard-clean gives **`unresolved`**, which feeds 15d triage. This covers a
  completion timeout (N1), cleanup_uncertain, a CR exit error, source_not_restored, a guard error, skip or
  label/guard mismatch, and a kill whose cleanup was not verified. The basis keeps label, guard_status, exec_status,
  cleanup_verified, stopped and stop_reason for each.
- Shards still pending with no unclean attempt give `deferred`.
- `survived` needs EVERY required shard to be guard-clean and survived.

An empty required list, an attempt for an unknown shard, or a screening label other than `survived` raises.

**`cr_coord.run_completion`** re-runs a screening survivor against every completion shard, in order. Each shard is
its own one-item attempt through `run_batch`, under `<work_root>/completion/<job>/<shard>/`.
- **[fix-1, ruling 2, I1]** It takes `pool_path`. `load_pool` verifies the `pool.json` node list against its
  `nodes_sha256`. Each declared shard's node set is read from its config's single `@argfile` (`shard_nodes`), so the
  pool check and the run see the same list. The union must equal the frozen pool exactly (`check_pool_union`). Zero
  shards, a subset, an unknown node, a tampered pool or a config without an argfile is refused before anything runs.
- Only a guard-clean kill stops the remaining shards. Any stop leaves the rest pending and blocks every batch until
  `resolve_stop`.
- **[fix-1, ruling 3, I2]** A shard refused by the fence or clock (its state shows the job never started) is recorded
  as `refused` and pending. Once that stop is resolved, a later session re-runs it as a new attempt `<shard>-a<k>`,
  and the refused state is kept. A shard that did run is never re-run.
- Every attempt records its state sha256, its test-command sha256 and **[fix-1, addendum (e)]** a `binding`:
  executable, exact node-set sha256, control sha256, target source sha256, harness hashes, helper hashes
  (`conftest.py` / `*helpers*.py` on the pythonpath dirs of the source tree), the env-relevant variables
  (PYTHONHASHSEED, PYTHONDONTWRITEBYTECODE, PYTHONUTF8, PYTHONIOENCODING, PYTEST_ADDOPTS, HYPOTHESIS_PROFILE, TZ),
  pythonpath and containment verdict.
- The pool sha256 and all attempts go into a new `completion_record*.json`, which is never overwritten.
- `unresolved_stops` also scans `completion/*/*/`.
- **[fix-1, N1]** `run_retry` refuses a completion-shard directory. A completion timeout stays `unresolved`, because
  no retry allowance has been agreed for completion attempts.

**HARD session fence** (`fence_s`, enforced in `run_batch`). A candidate starts only if the remaining session time is
at least `outer item path + nested cleanup + I/O margin`:
- Normal item: 300 + 45 (outer) + 45 (nested cleanup) + 15 = **405 s**.
- Retry: 600 + 45 + 45 + 15 = **705 s**.

The clock and the margin:
- The clock is **monotonic**. A reading earlier than the session start refuses with `session_clock_invalid`.
- The session clock lives in `session_root`, so nested completion and retry runs share their parent session's clock
  and fence. A later session's new root is created on first use.
- **[fix-1, I4]** Tests now pin the retry's parent clock and its 705 s fence. Deleting either guard fails a test.
- **[fix-1, addendum (d)]** The 15 s I/O margin is **30× the observed maximum of 0.5 s** (median 0.16 s) over 12 S1
  items. It is a judgement multiple, **not a proven I/O bound**. The observation used `run_batch` with a stub seam
  doing `real_exec`'s non-CR I/O (`_prep/measure_io.json`).
- **[fix-1, N5] Limit, disclosed and not fixed: reboot, sleep and hibernate.** Only `t_item < started` is detected.
  - A reboot followed by more uptime than the recorded start produces a bogus small elapsed time, which the harness
    does not detect.
  - Windows sleep and hibernate behaviour of `time.monotonic` was not characterized.
  - Operational rule: start a new session root after any reboot, sleep or hibernate, and treat a session that spans
    one as invalid.

**[fix-1, ruling 4, I3] Config-bound calibration cap.**
- `config_identity(cfg, cr_toml, config_id)` binds:
  - config id;
  - module;
  - test-command sha256;
  - cr.toml path + sha256 (it must render exactly this config);
  - harness hashes.
- `run_batch(config=...)` records that identity in the state, along with each item's measured duration (`item_s`).
- `derive_cap(calibration_state, out=..., identity=...)` takes ONE state of that config with at least 24 measured
  items. It records `floor((10800 - fence) / max item)` together with the identity and the state's path + sha256,
  and writes a sha256 sidecar. It never overwrites.
- `read_cap_record` re-verifies the sidecar, the calibration state bytes, the cr.toml and harness on disk, and the
  caller's identity. `batch_cap` refuses a bare dict and any mismatch.
- `plan_batches`, `run_batch` and `run_manifest` accept more than 24 items only with a verified record file. The cap
  is an efficiency estimate; the fence remains the safety bound.

**[fix-1, ruling 5] Deletion checks.** Each guard was deleted in a SCRATCH copy outside the repo
(`scratchpad/t15c_work/deletion_fix1/`), and the focused tests were run there. Full log: `t15c_h_fix1_green.txt`.
- **Caught**, 17 guards:
  - the merge's two guard_status conjuncts, plus the whole pair check;
  - the not-stopped, exec_status and cleanup_verified conjuncts;
  - pool union;
  - refused-shard resume;
  - bare-dict cap, cap identity, calibration-state config and calibration-state sha;
  - the **retry parent clock (D13)** and the **retry 600 + 45 fence (D14)**;
  - retry refusal of a completion dir;
  - non-empty required list;
  - helper binding.
- **Not caught in fix-1:**
  - The explicit zero-shard check is equivalent: `load_pool` refuses an empty pool, so `check_pool_union(pool, [])`
    always reports missing nodes.
  - The clean conjunct of the kill short-circuit. **[fix-2] Correction:** fix-1 called it equivalent, which was
    **wrong**. An unclean kill whose stop is resolved would short-circuit a later clean kill. It is now pinned by a
    test, and deletion G10 is caught.

**Not changed:** `cr_guard.py`, `cr_launch.py`, the `BUDGETS` table, and no parallel lanes.

**Harness sha256:**

| File | sha256 | Status |
|---|---|---|
| `cr_coord.py` | 43008a7fedf68d52789daa75265089bee412bb77c50eb54fcfc8070c0b49c1b2 | changed (fix-4; fix-3 was e76896cd…) |
| `cr_reconcile.py` | 1e1c07fdd1abb0177c57b7084b0c574dc3aa7aff6583542485fcedcfa2e2ce4d | changed (fix-1; not changed in fix-2) |
| `cr_guard.py` | 54e88df7…7f76 | unchanged |
| `cr_launch.py` | b6aa8d2a…2f00 | unchanged |
| `cr_preflight.py` | 22a133c376e79dc716ddf763c4d319061290d66901237f50dfdbf580c6601c0a | **new (15c-P)**, changed in fixes 1 and 2 (was fb9e8ef6…, then d8e92102…); part of `HARNESS_FILES` |

**[15c-P fix 2] `cr_coord.py` is now 02ab0c4a5ada296e017ad1e0f1fc156dc77d23d4420fdba6e82fbef30279692a.** The fix-1
value dda8997c… below is kept as history.

**[15c-P fix 1] `cr_coord.py` is now dda8997c8cce9ad4e2837bc69b660eb96f0344f8be8ded28508173bd30598a84.** The 15c-P
value 06a91463… below is kept as history.

**[15c-P] `cr_coord.py` is now 06a91463511bdfa9b6310ca64d356d3a3a9629ea269c67d345b0bebf03778ca7.** The table row
above is the fix-4 value, kept as history.
- **What changed:**
  - `preflight_binding` and `check_preflight` are new;
  - the gates in `run_manifest`, calibration `run_batch` and `run_completion` are new;
  - `HARNESS_FILES` gains `cr_preflight.py`;
  - the helper-hash loop is factored into `_helpers`, with its behaviour unchanged.
- `cr_guard.py`, `cr_reconcile.py` and `cr_launch.py` are unchanged.

## Method (unchanged from v1 unless marked)

**Copies, controls and baselines** are as in v1:
- The copy is repo-rooted. It holds `research/s1/*.py`, `docs` and `s1_tests`, plus the config's `control.json` and
  `nodes.txt`. The child runs `-p conftest`.
- `control.json` comes from a contained `--collect-only` with the guard's recorder plugin.
- Each selector got 3 serial guard baselines, each in a fresh coordinator copy with the coordinator's env, using the
  exact `cr.toml` test-command under `run_contained` with a 300 s outer deadline.
- The budget is judged on the outer wall: median ≤180 s and max ≤240 s.

**Scopes, rows 289/290.** These come from the AST delegation walk (`_prep/tools/scope_expand.py`).
- **[15c-H, D4]** collect seeds `_validate_bars_page` as a ruled inclusion, with basis "15c-H ruling 4". Its only
  module-level referrer is `do_final`, which passes it to `_paged` by value.
- The walk then adds `_is_num`, whose referrers `_parse_bars` and `_validate_bars_page` are now both in scope. Collect
  scope is now 21 scopes; seal is unchanged at 16.
- The previous collect evidence (ranges, shards, inventories, baselines) is kept under
  `cr_a3/_superseded/s1_collect_v1/`.

**Screening shards** are the earlier fast shards, kept as the screening stage (ruling 1).
- Functions are partitioned across shards. Each shard has a bounded node selection under a cap, with predeclared
  omissions in `selection.json`.
- **[15c-H, D8]** collect/final was rebuilt with the whole-selector pool rule. The shard owns `_identity_view` and
  `_is_num`, which no plan test reaches in the parent process, so its candidate pool is the whole plan selector.
- collect/audit's node list is byte-identical to v1. It was re-baselined anyway, because its row ranges changed.

**[15c-H, ruling 1] Frozen full pool and completion shards** (`_prep/tools/make_completion.py`).
- The pool is every node of the module's PLAN selector:
  - seal 132 (`test_s1_a3_stop` + `test_s1_a3_score`);
  - collect 89 (audit + final);
  - slot 94 (slots + finalizer).
- The pool includes every node omitted from all screening shards. It also includes the nodes that reach no in-scope
  function in the parent process (import-, child- or unobserved-relevant).
- The pool is written to `cr_a3/<m>/completion/pool.json` with a sha256 over the canonical node list.
- Shards use longest-processing-time packing on exploratory per-node times, under a cap of 150 s (seal, collect) or
  135 s (slot). Nodes keep the plan run order. The union is checked with `cr_coord.check_pool_union` and equals the pool.
- The whole-module selectors (journal, locks, trial, stage) ARE their full plan pool, so they need no completion stage.

**Omitted-node counts.** I re-derived Codex's counts with `_prep/tools/pool_check.py`. "Omitted" means it reaches an
in-scope function but is in no screening shard.

| Module | Screening union | Omitted everywhere | Unreaching in pool | Pool |
|---|---|---|---|---|
| seal | 60 | **70** | 2 | 132 |
| collect, v1 shards | 66 | **16** | 7 | 89 |
| collect, v2 shards (after D4/D8) | 72 | 17 | 7 | 89 |
| slot | 81 | **13** | 1 | 94 |

All omitted and unreaching nodes are in the completion pools.

**[fix-1, addendum (c)] Current screening gaps.** A screening gap is a pool node in no screening shard, counted with
`_prep/pool_check_post.json`. Codex's early number check gives the current gaps as seal **72**, collect **17** and
slot **13**. I reproduced all three:

| Module | Pool − screening union | Gap that reaches an in-scope function | Gap that reaches none |
|---|---|---|---|
| seal | 132 − 60 = **72** | 70 | 2 |
| collect (v2) | 89 − 72 = **17** | 17 | 0 |
| slot | 94 − 81 = **13** | 13 | 0 |

How these relate to the earlier 70 / 16 / 13:
- The earlier figures count only gap nodes that **reach** an in-scope function. Codex's gaps count every pool node
  outside the screening union.
- **seal:** 72 adds the 2 nodes that reach no in-scope function in the parent process.
- **collect:** v1 had 16 reaching-omitted nodes, and 89 − 66 = 23 pool nodes outside the screen. After D4/D8,
  collect/final selects from the whole plan selector. Its screen now includes all 7 unreaching nodes, but leaves 17
  reaching nodes out.
- **slot:** its single unreaching node is in the screening union, so its gap equals its 13 reaching-omitted nodes.
- The "unreaching in pool" column overlaps the screening union in some rows, slot for example. The columns are not a
  partition, so do not add them up.

Every gap node is in the completion pool, so a screening survivor runs against it.

**Inventories.** For each config, `cosmic-ray init` produces the coordinator's immutable `inventory.json`
(pre-filter, all 213 operators, no operator filter). The R8 range filter writes `inventory_filtered.json`.
- Completion shards reuse the screening inventory item (same job, same normalized mutation spec), so they have no
  inventory of their own.
- The cross-shard partition is exact:
  - seal 334 = row scope 334;
  - collect 852 = row scope 852;
  - slot 300 + 1397 = 1697.

**[fix-1, ruling 7 / N2 + addendum (a)] Re-initialised with the final harness.** After the harness was final, all 12
screening inventories were re-created with a genuine `cosmic-ray init` (`_prep/tools/reinit.py`). It ran through
`cr_launch` on scratch copies and executed nothing. The 12 inits took **40.5 s** in total, 1.6–4.2 s each.
- **Old files kept as recorded.** The previous files (`inventory.json` + `.sha256`, `inventory_filtered.json`,
  `batch_plan.json`) were **moved unedited** to `cr_a3/_superseded/inventories_pre_fix1/<config>/`. Their recorded
  harness hashes are left as recorded: HEAD's `cr_coord` 9a7c08e4… for 10 configs, and the intermediate CRLF save
  a4b42d83… for collect audit/final. No recorded hash was hand-edited.
- **Normalized specs are identical.** For all 12 configs, the item specs (module_path, operator, operator_args,
  occurrence, start, end) are identical and in the same order: 6318 candidates before and after.
- **What differs.** All item `job_id`s are new, because `cosmic-ray init` assigns fresh uuids. Each config's
  `inventory_filtered.json` and `batch_plan.json` were therefore regenerated. Only these top-level fields changed:
  - `harness_sha256`: it now records the final `cr_coord` 998e60a4… and `cr_reconcile` 1e1c07fd…;
  - `session_sha256`: a new scratch DB;
  - `copied`: its only changed entries are `cr_coord.py`, `cr_reconcile.py` and `test_s1_a3_cr_completion.py`.

  Comparison: `_prep/reinit_compare.json`.
- **Baselines were not re-run.** `cr_guard.py`, every `cr.toml` test-command and every `control.json` are unchanged.

**[fix-2] Re-initialised again with the fix-2 final harness.** All 12 screening inventories were re-created a second
time with a genuine `cosmic-ray init` that executed nothing. It took **41.0 s** in total.
- **Old files kept.** The fix-1 inventory files were moved **unedited** to
  `cr_a3/_superseded/inventories_pre_fix2/<config>/`.
- **Specs identical.** The normalized specs are identical and in the same order for all 12 configs: 6318 candidates.
- **What changed.** `job_id`s are fresh again, so the filtered inventories and batch plans were regenerated. Otherwise
  only `harness_sha256` (now `cr_coord` 235e5285…), `session_sha256` and the `copied` entries for `cr_coord.py` and
  `test_s1_a3_cr_completion.py` changed.

  Comparison: `_prep/reinit_compare_fix2.json`.
- **Baselines were still not re-run**, for the same reason as fix-1.

**[fix-3] Re-initialised a third time with the fix-3 final harness.** All 12 screening inventories were re-created
by a genuine `cosmic-ray init` that executed nothing. It took **42.3 s** in total.
- **Old files kept.** The fix-2 files were moved **unedited** to `cr_a3/_superseded/inventories_pre_fix3/<config>/`.
- **Specs identical.** The normalized specs are identical and in the same order for all 12 configs: 6318
  candidates.
- **What changed.** `job_id`s are fresh, so the filtered inventories and batch plans were regenerated. Otherwise
  only `harness_sha256` (`cr_coord` e76896cd…), `session_sha256` and the `copied` entries for `cr_coord.py` and
  `test_s1_a3_cr_completion.py` changed.

  Comparison: `_prep/reinit_compare_fix3.json`.
- **Baselines were not re-run.** `cr_guard.py`, every `cr.toml` test-command and every `control.json` are
  unchanged.

**[fix-4] Re-initialised a fourth time with the fix-4 final harness.** All 12 screening inventories were re-created
by a genuine `cosmic-ray init` (`_prep/tools/reinit.py fix4`, then `reinit_copied_diff.py fix4`) that executed
nothing. It took **41.2 s** in total.
- **Old files kept.** The fix-3 files were moved **unedited** to `cr_a3/_superseded/inventories_pre_fix4/<config>/`.
  Each moved file's sha256 equals its entry in the fix-3 hash manifest.
- **Specs identical.** The normalized specs are identical and in the same order for all 12 configs: 15685 before the
  filter, **6318 kept**. The kept spec sequences are identical too.
- **What changed.** `job_id`s are fresh, so the filtered inventories and batch plans were regenerated. Otherwise
  only `harness_sha256` (`cr_coord` 43008a7f…), `session_sha256` and the `copied` entries for `cr_coord.py` and
  `test_s1_a3_cr_completion.py` changed. Every sidecar matches, and every filtered inventory and plan is bound to its
  new `inventory.json`.

  Comparison: `_prep/reinit_compare_fix4.json`.
- **[fix-5] Correction (R4-I1): the batch plans regressed in this step.**
  - **What went wrong.** The re-init ran `inventory.py`, which writes a *plain* plan (`batches` of 24). It skipped
    `_prep/tools/plan_sessions.py`, the 15c-H ruling-2 step that rewrites each plan calibration-first.
  - **The effect.** The fix-4 plans lacked `calibration_batch`, `pending_after_calibration`, `derived_cap`,
    `derived_cap_rule` and `scenario`, so the runbook's references in steps 3 and 5 did not resolve.
  - **Fixed in fix 5.** `plan_sessions.py` was re-run; it executes nothing. All 12 plans now have exactly the key set
    of the 192e47c plans, and a superset of the `pre_fix4` keys. Each is bound to its current `inventory.json`.
    `calibration_batch` is the first 24 kept ids, and `calibration_batch` + `pending_after_calibration` equals the
    kept ids in `cr_coord.order_items` order. `scenario` and `derived_cap_rule` equal 192e47c's, and `derived_cap`
    is null.
  - **Guarded from now on.** `finalize.py hashes` runs `check_plans()` first. It refuses to write the manifest unless
    all 12 plans are calibration-first, bound to their inventory, and cover the kept ids in order. A scratch
    demonstration with one plain plan substituted was refused. Evidence: `a3/t15c_h_fix5_check.txt`.
- **Baselines were not re-run.** `cr_guard.py`, every `cr.toml` test-command and every `control.json` are
  unchanged.
- **The env scrub can change what a baseline child received.** `baseline.py` built the guard child's env with
  `cr_coord._env`, which before fix 4 passed the whole parent env through. The baselines recorded no env, so I cannot
  prove what that parent held. They were launched by `run_baselines.sh` from the agent's bash, which sets no such
  variable. The same kind of shell today has no PYTHON*/PYTEST*/HYPOTHESIS*/COV* variable (`env` checked
  2026-11-16). If that held then, the baseline children received exactly what fix 4's `_env` gives: PYTHONPATH and
  PYTHONDONTWRITEBYTECODE=1, which `_env` set then too. **The controller rules on whether baselines need re-running.**
  - **[fix-5] Ruling.** The baselines are not re-run now. Instead, after any Codex GO, one guard baseline runs per
    active config (all 21) under the fix-4 env with the frozen `--control` file. A screening config runs it before its
    calibration; a completion config runs it before its first use. See runbook step 3a.
    A config whose pre-flight is not clean is not calibrated.

**[15c-P] Re-initialised a fifth time.** `cr_coord.py` changed, and `HARNESS_FILES` gained `cr_preflight.py`, so all
12 screening inventories were re-created by a genuine `cosmic-ray init` only. The commands were
`tools/reinit.py 15cp`, then `reinit_copied_diff.py 15cp`, then `plan_sessions.py`, with -B and
PYTHONDONTWRITEBYTECODE=1. It took **41.7 s**.
- **Old files kept.** The 9330a64 files were moved **unedited** to `cr_a3/_superseded/inventories_pre_15cp/`, and
  each is byte-equal to its committed blob.
- **Specs identical.** The normalized specs and the kept specs are identical and in the same order: 15685 before the
  filter, **6318 kept**.
- **What changed.**
  - `harness_sha256` now has 5 files.
  - `copied` changed for `cr_coord.py`, `cr_preflight.py` and the three test files.
  - `session_sha256` changed.
- **Plans.** Each plan is calibration-first, and `finalize.py hashes` re-checks that.
- **Baselines were not re-run, and are replaced.** Before use, the 21 configs get the step-3a pre-flights instead.
  The guard, the test commands and the controls are unchanged.
- **Evidence:** `a3/t15c_p_reinit_check.txt` and `_prep/reinit_compare_15cp.json`.

**[15c-P fix 1] Re-initialised a sixth time.** `cr_coord.py` and `cr_preflight.py` changed, so all 12 screening
inventories were re-created again by a genuine `cosmic-ray init` only. The commands were `tools/reinit.py 15cp_fix1`,
then `reinit_copied_diff.py 15cp_fix1`, then `plan_sessions.py`. It took **41.5 s**.
- **Old files kept.** The 15c-P files were moved **unedited** to `cr_a3/_superseded/inventories_pre_15cp_fix1/`.
  They were never committed, so each was checked against its sha256 in the 15c-P hash manifest instead.
- **Specs identical.** Both the normalized specs and the kept specs are identical: 15685 before the filter, **6318
  kept**.
- **What changed:** only `copied` (cr_coord, cr_preflight and the three test files), `harness_sha256` and
  `session_sha256`.
- **Plans:** calibration-first, and bound to the new inventories.
- **Baselines** are not re-run; they are replaced by the step-3a pre-flights.
- **Evidence:** `a3/t15c_p_fix1_reinit_check.txt` and `_prep/reinit_compare_15cp_fix1.json`.

**[15c-P fix 2] Re-initialised a seventh time.** `cr_coord.py` and `cr_preflight.py` changed again, so the inventories
were re-created again by `cosmic-ray init` only. The commands were `reinit.py 15cp_fix2`, then
`reinit_copied_diff.py 15cp_fix2`, then `plan_sessions.py`. It took **41.6 s**.
- **Manifest preserved first.** Before regenerating, the fix-1 manifest was copied unedited to
  `a3/t15c_prep_hashes_pre_15cp_fix2.txt`.
- **Old files kept.** The fix-1 files were moved unedited to `_superseded/inventories_pre_15cp_fix2/`, and each
  matches its entry in that preserved manifest.
- **Specs identical.** Both the specs and the kept specs are identical: 15685 before the filter, 6318 kept.
- **Plans:** calibration-first and bound.
- **What changed:** only `copied`, `harness_sha256` and `session_sha256`.
- **Evidence:** `a3/t15c_p_fix2_reinit_check.txt` and `_prep/reinit_compare_15cp_fix2.json`.

**Coverage evidence.** For each config, `selector_coverage_detail.json` is a parent-process `sys.monitoring` reach run
on the final selector. It does not observe child or import-time code.

## Per config

Baseline times are seconds. The targets are median ≤180 and max ≤240.

### Screening stage

| # | Module / shard | Selector | Nodes | Baseline median / max | Candidates pre → post | Calibration items | Scenario cap / sessions | Covered fns |
|---|---|---|---|---|---|---|---|---|
| 1 | s1_journal | journal + precedence | 163 | 4.6 / 4.7 | 720 → 720 | 24 | 295 / 4 | 32/35 |
| 2 | s1_locks | locks | 47 | 2.5 / 2.6 | 159 → 159 | 24 | 314 / 2 | 11/11 |
| 3 | s1_trial | trial + gate | 123 | 46.3 / 47.6 | 1782 → 1782 | 24 | 133 / 15 | 41/48 |
| 4 | s1_stage | stage | 74 | 11.6 / 11.6 | 774 → 774 | 24 | 246 / 5 | 45/47 |
| 5 | s1_slot / finalizer | `@…/finalizer/nodes.txt` | 78 | 142.2 / 145.2 | 1697 → 1397 | 24 | 59 / 25 | 74/75 |
| 5 | s1_slot / slots | `@…/slots/nodes.txt` | 79 | 143.9 / 145.6 | 1697 → 300 | 24 | 59 / 6 | 7/12 |
| 6 | s1_seal / check | `@…/check/nodes.txt` | 40 | 165.9 / 170.8 | 1634 → 77 | 24 | 51 / 3 | 2/2 |
| 6 | s1_seal / decide | `@…/decide/nodes.txt` | 35 | 164.6 / 165.0 | 1634 → 101 | 24 | 53 / 3 | 6/6 |
| 6 | s1_seal / record | `@…/record/nodes.txt` | 37 | 171.3 / 172.9 | 1634 → 114 | 24 | 51 / 3 | 6/6 |
| 6 | s1_seal / sampled | `@…/sampled/nodes.txt` | 20 | 146.6 / 150.0 | 1634 → 42 | 24 | 57 / 2 | 3/3 |
| 7 | s1_collect / audit [15c-H re-baselined] | `@…/audit/nodes.txt` | 65 | 127.8 / 129.9 | 1160 → 406 | 24 | 64 / 7 | 18/18 |
| 7 | s1_collect / final [15c-H rebuilt] | `@…/final/nodes.txt` | 72 | 133.5 / 136.5 | 1160 → 446 | 24 | 62 / 8 | 9/11 |

Notes on the screening table:
- Covered functions are those reached in the parent process. Uncovered, by config:
  - journal: Row.instant, new_nonce, slot_subject.
  - trial: opening_issuance, trial_in, product_context.build.gate_, _audit_state, _holds_this_trials_audit,
    _journal_invalid, verify_current.
  - stage: StageAbort.__init__, _nvs_of.
  - slot/finalizer: QualifiedEvidence.identity.
  - slot/slots: qualified_subjects, _unreadable, _listing_refusal, _stray_files, _judge_without_calendar.
  - collect/final: _is_num, _identity_view.

  Per ruling 7 these are triage input, not dispositions.
- The s1_slot plan selector remains superseded: median 195.2 s, max 197.1 s, in `cr_plan_selector_SUPERSEDED.toml`.
- **Scenario cap** = `floor((10800 - 405) / est_item)`, where est_item = baseline max + measured I/O 0.5 s + an
  **ASSUMED, unmeasured** 30 s of CR overhead. Scenario sessions = 1 calibration session + `ceil(rest / cap)`.
- The scenario is an estimate only. The real cap comes only from `derive_cap` on the measured calibration session.

### Completion stage (screening survivors only)

| Module / completion shard | Nodes | Baseline median / max | Est. s per attempt |
|---|---|---|---|
| s1_seal / c1 | 28 | 127.4 / 127.4 | 157.9 |
| s1_seal / c2 | 26 | 126.4 / 127.9 | 158.4 |
| s1_seal / c3 | 26 | 133.2 / 137.4 | 167.9 |
| s1_seal / c4 | 26 | 130.7 / 130.7 | 161.2 |
| s1_seal / c5 | 26 | 128.6 / 146.2 | 176.7 |
| s1_collect / c1 | 51 | 131.5 / 131.5 | 162.0 |
| s1_collect / c2 | 38 | 132.5 / 133.2 | 163.7 |
| s1_slot / c1 | 49 | 86.0 / 92.7 | 123.2 |
| s1_slot / c2 | 45 | 86.6 / 87.3 | 117.8 |

- Pool sha256s: seal 31d810ab…374f (132 nodes), collect 4ff0ea44…46e0 (89 nodes), slot 63a261af…af6e (94 nodes).
- **[fix-1, addendum (b)] Completion cost per screening survivor, as a baseline-maxima scenario** (formerly called
  "worst case"), assuming no completion shard kills:
  - seal ≈822 s (822.08);
  - collect ≈326 s (325.66);
  - slot ≈241 s (240.99).

  Each figure is the sum, over the module's completion shards, of observed baseline max + 0.5 s observed I/O + an
  **assumed, unmeasured** 30 s of CR overhead. It is **not an upper bound**: a mutant's tests can run longer than the
  unmutated baseline, or time out (300 s CR timeout, 405 s fence per attempt).
  - The JSON field is now `completion_per_survivor_baseline_maxima_scenario_s` (`_prep/budget_v2.json`).
  - The "Est. s per attempt" column above is the same scenario per shard.
- No completion shard is over budget. All 27 completion baselines were guard `survived`, with node set == control,
  cleanup verified, and the target imported from the copy.

**Candidates by operator family.** These are unchanged from v1, except collect/final, which went from 423 to 446 with
the D4 additions. Exact per-operator counts are in each `inventory_filtered.json`.

## Budget totals

All the time figures below are **baseline-maxima scenarios, not bounds**. Each uses the observed baseline max, the
observed 0.5 s I/O and an **assumed** 30 s of CR overhead. Mutants can run longer or time out.

**Candidates:** 6318 = journal 720 + locks 159 + trial 1782 + stage 774 + slot 1697 + seal 334 + collect 852. That is
v1's 6295 plus 23 from D4, in `_validate_bars_page` and `_is_num`.

**Screening sessions:**
- 12 calibration sessions, one per screening config (ruling 2), of 24 items each.
- About **83 sessions** in the scenario, using the derived scenario caps.
- The old universal cap of 24 would need 269.

**First-pass screening execution:** about **196 h** in the scenario, same model as v1.

**Excluded:** completion runs for screening survivors (the survivor count is unknown, so completion is reported per
survivor), retries, controls, repairs and triage. Codex's strongest objection stands: completion could dominate the
cost.

No configuration is over budget. The 21 active configs (12 screening + 9 completion) have 63 baseline runs, all clean
guard `survived`.

## Open items carried forward

**A. Retry allowance for completion attempts is undefined.** Codex's merge contract asks whether it is "global per
candidate or per selector", and that needs explicit agreement.
- **[fix-1]** A completion timeout is merged as **`unresolved`** (15d triage), and `run_retry` refuses a
  completion-shard directory.
- `run_retry` serves screening timeouts only, under the parent session clock with the 705 s fence.

**B. The 30 s per-item CR overhead is still assumed.** The calibration sessions measure it; `derive_cap` records the
measured cap, bound to its config.

**C. The D3 coverage limit stays disclosed.** These shared helpers are excluded and recorded in `ranges.json` →
`decisions`:
- seal: seal_pass, _live, _close, _eligible, cohort, pinned, schedule, eligible_sessions, persist_stop, window_end.
- collect: _ny_date, _out, _nvs_nothing_to_acquire, _stop_attestation, final_plan_record.

**D. Inventory provenance: resolved by re-initialisation** (fix-1, and again in fix-2; see Method → Inventories). Every
current inventory records the final harness. The superseded files keep their original hashes, unedited.

**E. Node ids with spaces.** Some ids contain spaces, for example `…[final plan]`. The `@nodes.txt` argfile passes one
id per line, and the baselines show the selected set equals the control.

**F. [fix-1, N5] Reboot, sleep and hibernate limit of the monotonic session clock.** See the fence section. It is not
fixed; the operational rule is a new session root after any reboot, sleep or hibernate.

**G. Equivalent deletion mutants: two remain (zero-shard check; fix-3 explicit source_sha256 re-check).**
- Only the explicit zero-shard check survives deletion, and it is equivalent: `load_pool` refuses an empty pool, so
  `check_pool_union(pool, [])` always reports missing nodes.
- **[fix-2] Correction:** fix-1 also listed the clean conjunct of the kill short-circuit as equivalent. That was
  **wrong**: an unclean kill whose stop was resolved would short-circuit a later clean kill and turn `killed` into
  `unresolved`.
  - The guard is now pinned by `test_R1_I1_resolved_unclean_kill_does_not_short_circuit_a_later_clean_kill`, and
    deletion G10 is caught.
  - The fix-1 record keeps its original text, with a correction appended.
- **[fix-3]** The explicit `source_sha256` check against a persisted completion binding is also equivalent, as
  defence in depth. The screening-context check refuses first whenever the expected source differs, and
  executed-vs-planned keeps every persisted completion source equal to the current one. See
  `t15c_h_fix3_green.txt`.
  - **[fix-4] Superseded.** Re-review 3 showed the pair (screening `want` conjunct, explicit check) was covered only
    jointly. Each is now pinned alone: the screening conjunct through `run_completion` with no cached attempt, the
    explicit check directly on `_check_cached_attempts` (through `run_completion` it stays unreachable, as stated).
    Both deletions are caught.
- **[fix-4]** `run_manifest`'s own identity check is now equivalent: `run_batch` repeats the same check
  (`_check_identity`) on the inventory `run_manifest` passes through, before any state is written. It is kept as
  defence in depth.

**H. [fix-3] Scope of the binding.**
- **Recorded:** the binding records the env that `_env` gives the CR child (allowlisted variables plus PYTHONPATH,
  relative to the copy).
  - **[fix-4]** It now records every PYTHON*/PYTEST*/HYPOTHESIS*/COV* variable the child receives, plus TZ, and
    `_env` scrubs every other inherited one, so for that set the child env equals the bound env.
  - **[fix-4] Still not bound:** variables outside those prefixes, such as PATH, SystemRoot and TEMP. They are
    inherited as before. Of the per-attempt variables, CR_GUARD_* and S1_HYPOTHESIS_ROOT are excluded on purpose
    (see the fix-4 changes).
  - **[fix-5] Known limit (R4-N1): LANG and LC_* reach the child unbound.** They are not scrubbed and not bound.
    Nothing in scope reads them:
    - the re-reviewer's grep of `research/s1` for `os.environ`, `getenv` and `setenv` found no read in the 12 selector
      test files or the 7 mutated modules;
    - the only env read in `conftest.py` is `S1_HYPOTHESIS_ROOT`, which `_env` and the guard overwrite;
    - on Windows, Python's locale and encoding come from the OS and from PYTHONUTF8/PYTHONIOENCODING, which are
      bound.

    Per the controller's ruling, the harness is not changed for this. A future selector or module that reads the
    locale would need LANG/LC_* added to the bound set beside TZ.
- **Not bound as identity:** the guard's own per-job additions for its pytest child, which are its job-dir paths, the
  per-attempt Hypothesis home and its own directory appended to PYTHONPATH. They are fixed by `cr_guard.py`, whose
  sha is in `harness_sha256`.
- **No security boundary:** none is claimed against deliberately hand-edited state files. The state, its sha in
  the completion record and the hashes manifest make edits detectable, not impossible.

**I. [fix-5] Counting rule across work_roots (R4-N2; the controller's ruling).**
- **Each `job_id` counts exactly once.**
- **Re-screening supersedes.** A candidate may be screened again in a fresh work_root, which is the R3-N2 remedy after
  a binding drift. The earlier work_root's result for that job is then **superseded**:
  - it is kept unedited, and nothing in it is moved or rewritten;
  - it is listed in a **superseded-results ledger**, with the old work_root, the new work_root and the reason, which
    is the drifted fields named by the refusing `CoordError`.
- **15d tallies the latest result only.** It counts each job from the latest work_root in which that job has a
  result, and from no other.
- **Final counts keep both views.** They distinguish unique candidates (one per `job_id`) from attempts (every
  execution, superseded ones included).

## Exact commands for 15c (after peer agreement on this head; none of this was run)

Order (R1): journal, locks, trial, stage, slot/finalizer, slot/slots, seal/{check, decide, record, sampled},
collect/{audit, final}. Notation:
- `<E>` = `research/s1/s1_evidence/cr_a3/<module>[/<shard>]`
- `<CE>` = `research/s1/s1_evidence/cr_a3/<module>/completion/c<i>`

A reviewed 15c driver, run by the testenv interpreter from a script file, does the following.

1. **Configs.** `cfg = cr_coord.CRConfig(...)` with:
   - `python=<testenv>`;
   - `module_rel="research/s1/<module>.py"`;
   - `guard_args=["--control", "<E>/control.json", "-p", "conftest", *selector]`;
   - `pythonpath_rel=["research/s1", "research/s1/s1_tests"]`;
   - `target_module="<module>"`.

   Then:

   ```
   identity = cr_coord.config_identity(cfg, <E>/cr.toml, config_id="<module>/<shard or _>")
   ```

   This raises unless `<E>/cr.toml` renders exactly this config. Completion configs are built the same way, from
   `<CE>/control.json` and `@<CE>/nodes.txt`.
2. **Copy paths.**
   - Screening: `research/s1/*.py` + `research/s1/docs` + `research/s1/s1_tests` + `<E>/control.json` (+
     `<E>/nodes.txt`).
   - Completion: the same, with `<CE>/control.json` + `<CE>/nodes.txt`.

   `src_root` is a clean checkout at the agreed head, and the module sha256 must equal `inventory.json.source_sha256`.

3a. **[fix-5] Pre-flight guard baseline** (the controller's ruling). This runs after any Codex GO and covers **all 21
    active configs**.
    - **Screening configs (12):** each is pre-flighted before its calibration.
    - **Completion configs (9):** each is pre-flighted before its first use by any `run_completion` (re-review 5,
      R5-I1). Their 27 baselines also ran before the fix-4 scrub. An unmutated control failing under the scrubbed env
      would be labelled `killed` by the guard, giving a guard-clean false kill to every survivor that reaches that shard.
    - A config that is not clean is neither calibrated nor used for completion.
    - **Driver.** ~~The pre-flight driver is not yet written.~~ **[15c-P]** The driver is
      `research/s1/s1_tests/cr_preflight.py`; see "Driver and CLI" below. It must be task-reviewed, and
      Codex-reviewed at exact head, before it runs (R5-N1). **None of it has been run against a real config.**
    - **What runs.** A fresh copy (step 2's copy paths) and the exact `cr.toml` test-command, which carries
      `--control <E>/control.json`, the frozen control. It runs under `cr_guard.run_contained`, with the CR timeout
      as the outer deadline and the env from the production `cr_coord._env(copy, cfg, job_dir, job_id)`, which is the
      fix-4 env.
    - **Recorded.** The run records `cr_coord._child_env_binding(copy, cfg)`, `guard.json` and the sha256 of the
      control file.
    - **Not changed.** No mutation is applied, and `control.json` is never rewritten.
    - **Do not reuse `baseline.py` as-is.** Its first step re-collects and rewrites `control.json` (`--collect-only`).
      Only its single guard-run step applies, against the frozen file, whose sha256 must equal the committed one.
    - **Clean means** guard status `survived`, the node set equal to the control, no node-set mismatch, verified
      cleanup, the source unchanged, and the outer wall time within the selector budget.
    - **A config whose pre-flight is not clean is not calibrated.**
    - **[15c-P] Driver and CLI.** Run it with the testenv interpreter, by path, from a clean checkout at the agreed
      head:

      ```
      <testenv> -B research/s1/s1_tests/cr_preflight.py all --src-root <clean checkout> --work-root <scratch dir>
                [--modules s1_journal,...]
      ```

      - **What `run_all` does.** It finds the 21 configs (`discover`: the 12 screening configs in R1 module order,
        then the 9 completion shards). For each, it rebuilds the config from its committed `cr.toml`
        (`config_from_toml`), with pythonpath `research/s1`, `research/s1/s1_tests`. It uses step 2's copy paths
        (`copy_paths_for`) and calls `run_preflight`.
      - **The frozen control value** is `collect_only.json` → `control_sha256`, beside the control. That value was
        recorded when the control was created, is committed, and equals the 9330a64 blob and manifest entry for all
        21 controls. It is independent of the regenerated hash manifest, which a tampered control would follow.
      - **The source pin** is the config's `inventory.json` `source_sha256`. A completion shard uses every screening
        inventory of its module, and they must agree.
      - **Where records go.** Each run writes a write-once `<E or CE>/preflight/preflight_<k>.json`, with `k` as the
        next free attempt.
      - **Re-runs are safe.** A config that already has a clean record for its current binding is skipped. A config
        with a not_clean record for that binding stops the run without retrying, and so does a new not_clean.
      - **Exit code.** It is 0 only if every config reached is clean.
      - **Gates.**
        - `run_manifest` now needs `cfg=` and `preflight_dir=<E>/preflight`, and refuses unless the inventory's test
          command is `cfg`'s.
        - A calibration `run_batch(config=identity)` needs the same.
        - Each `run_completion` shard spec needs `"preflight_dir": <CE>/preflight`.
        - Each gate is `cr_coord.check_preflight`: a CLEAN record bound to the current `preflight_binding`, and no
          not_clean record for it. The binding covers harness, command, control, argfiles, source, helpers, copy
          paths, pythonpath and the bound child env.
        - A change in any of these, including in a later session, invalidates the record.
        - The record's path and sha256 are persisted in the batch state (`preflight`), in each completion attempt and
          in the completion record (`preflights`).
    - **[15c-P fix 1] Changes after the task review.**
      - **Crash safety (I1).** Each attempt first writes `started_<k>.json`, write-once. Every outcome after it then
        ends in a written `preflight_<k>.json` (try/finally), as a not_clean record with its reason. That covers:
        - a malformed or unreadable guard sidecar or runner result;
        - a copy that differs from the pins or the source tree;
        - a non-reviewed harness file in the copy;
        - a runner exception (a non-Exception abort is recorded, then re-raised);
        - any other driver error.
      - **Orphans.** A marker without a record (a hard kill), or a work-root `attempt_<k>` without a record, is an
        **orphan**. It blocks `check_preflight` and `run_all` exactly like a recorded not_clean, and is never retried
        past. Clearing it is an operator action, outside the driver. **[15c-P fix 2]** The work-root check in
        `run_all` ignores the binding, so a changed binding starts afresh only under a new work root (R1-N2).
      - **Every copied file is bound (I2).** `copied_sha256` is the sha256 of `cr_coord.copied_map`, which hashes every
        file a copy of the copy paths holds. It is in:
        - the pre-flight binding;
        - every completion attempt's binding and its reuse comparison;
        - each screening item (`copy_paths` + `copied_tree_sha256`). Completion refuses a screening label whose copied
          tree differs now.

        So editing any selected test or sibling module after a clean pre-flight refuses every gate.
      - **After the run (M4/M7).** The whole copy must be unchanged, as must the source tree's copy paths and the
        source-tree control.
      - **Retries are gated (I3).** `run_retry(..., preflight_dir=<E>/preflight)` checks the BASE config's pre-flight,
        not `retry_config(cfg)`. The timeout batch must have run under that same record (same sha256).
      - **Every execution is gated (M1/M3).** `run_batch` needs `cfg` and a clean pre-flight for every execution,
        unless the exec seam declares itself `synthetic` (test stubs only).
        - A `real_exec` seam is never synthetic. It carries `test_command_sha256` and must match `cfg`, or
          `retry_config(cfg)` for a retry.
        - `run_completion` and `run_retry` hand their verified reference over as `preflight_ref`, which is
          re-verified: bytes, clean verdict, command, harness.
      - **`--write-control` is refused (M6).**
      - **The frozen value is cross-checked (M5).**
        - The driver requires the `collect_only.json` value to equal every historical baseline guard sidecar's
          `control_sha256`. It needs at least one; there are 3 per config.
        - For a screening config, it must also equal the inventory's `copied` entry for the control.
        - Independently, the task reviewer verified, for 21/21 configs, that `git show 9330a64:<E>/control.json` ==
          the 9330a64 `collect_only.json` `control_sha256` == the working tree == the manifest
          (`task-15c-p-review-verdict.md`, "Executed evidence summary").
        - The driver makes no git call. Edits made consistently to `control.json`, `collect_only.json`, the baseline
          sidecars and the inventory would pass. That `--src-root` is a clean checkout at the agreed head remains an
          operator precondition.
    - **[15c-P fix 2] Changes after re-review 1** (R1-M1 to R1-M3; the R1-N items are disclosed here, with no code
      change).
      - **R1-M1: a stale reference is refused.** `_verify_preflight_ref` now also requires the record's WHOLE binding
        to equal `preflight_binding(cfg, src_root, copy_paths)`. A direct `run_batch(cfg=, preflight_ref=<stale clean
        record>)` is refused, for example after a copied file changed.
        - So run_batch's re-check now also refuses a change made between `run_completion`'s pre-pass and the attempt.
        - The executed-vs-planned guard still covers a change made after that re-check and before the copy.
      - **R1-M2: N18 was not equivalent.** The marker term in `_next_attempt` keeps a config alive after an
        old-binding orphan, provided the work root is new and the binding is new. This is now tested. The fix-1
        GREEN record carries an appended correction.
      - **R1-M3: changed paths are recorded.** A `copy_changed` / `source_tree_changed` record lists the changed
        relative paths under `changed_paths.{copy, source_tree}`, as `added`, `removed` and `modified`. Each list is
        sorted and capped at 50, with `total` and `truncated`.
      - **R1-N1: the synthetic flag is self-declared, and cannot be verified.**
        - Any non-`real_exec` seam that sets `synthetic = True` runs ungated through `run_batch`, and through
          `run_retry` with such a factory.
        - This is a declared exemption for test stubs.
        - Production is unaffected: `run_manifest` and `run_completion` always gate, and `run_retry`'s default
          factory is `real_exec`, whose seams never count as synthetic.
        - A reviewed 15c driver must never pass a non-`real_exec` seam.
      - **R1-N2: `run_all` blocks on ANY orphan `attempt_<k>` dir in its work root, whatever the binding.**
        - A changed binding starts afresh only under a NEW work root. The gate's marker-based orphan check is
          per-binding.
        - Clearing an orphan, or choosing a new work root after a binding change, is an operator action.
      - **R1-N3: the 15c-P manifest was not preserved.** The 15c-P (1056-entry) manifest was overwritten in fix 1,
        so `_superseded/inventories_pre_15cp_fix1/` can no longer be re-checked against it. The reviewer
        spot-checked 3 configs, with specs equal and in order, 0 job_id overlap.
        - From fix 2 on, the manifest is preserved before each regeneration, starting with
          `a3/t15c_prep_hashes_pre_15cp_fix2.txt` (the fix-1 manifest, 1109 entries, unedited).
      - **R1-N4: M5 is a consistency check across committed records in the same tree, not a git check.** A
        consistent four-file edit would pass, so the clean-checkout precondition stands.
3. **Calibration session** (one session root per session):

   ```
   cr_coord.write_manifests(<root>/<C>, [batch_plan.json["calibration_batch"]], sha256(<E>/inventory.json))
   cr_coord.run_manifest(<root>/<C>/batch_000.json, <E>/inventory.json, src_root=..., copy_paths=...,
                         work_root=<root>/<C>/session-000, exec_seam=cr_coord.real_exec(cfg), config=identity,
                         cfg=cfg, preflight_dir=<E>/preflight)                       # [15c-P]
   ```

   The HARD 405 s fence and the monotonic session clock apply. After any reboot, sleep or hibernate, start a new
   session root.
4. **Completion of each screening survivor `j`** in that session:

   ```
   cr_coord.run_completion(j, items_by_id,
                           [{"name": "c<i>", "cfg": cfg_c<i>, "copy_paths": ...,
                             "preflight_dir": <CE>/preflight} for every c<i>],               # [15c-P]
                           pool_path=<src_root>/research/s1/s1_evidence/cr_a3/<module>/completion/pool.json,
                           src_root=..., work_root=<root>/<C>/session-000, exec_factory=cr_coord.real_exec)
   ```

   - It refuses unless the shards cover the pool exactly.
   - Any stop requires `cr_coord.resolve_stop(<dir of the stopped state>, <batch id>, by=..., note=...)` before
     anything else runs.
   - A completion stopped or refused by the session fence resumes in a later session: pass
     `session_root=<new session root>` with the same `work_root`.
5. **Derive the cap.**

   ```
   cr_coord.derive_cap(<session-000>/batch_000_state.json, out=<root>/<C>/derived_cap.json, identity=identity)
   ```

   Then build the remaining manifests with `cr_coord.plan_batches(pending_after_calibration, size=<derived cap>,
   cap_record=<root>/<C>/derived_cap.json, identity=identity)`. Run each with
   `run_manifest(..., cap_record=<that path>, config=identity, cfg=cfg, preflight_dir=<E>/preflight)` in its own
   session root. **[fix-4]** A direct `run_batch(config=identity)` also needs `inventory_path=<E>/inventory.json`
   (and, **[15c-P]**, `cfg=` + `preflight_dir=`); `run_manifest` passes them. The record
   is re-verified on every use, and the fence, not the cap, bounds every session.
   - **[fix-5]** `calibration_batch` and `pending_after_calibration` are the keys of `<E>/batch_plan.json`, which is
     calibration-first again (see Method → Inventories). Its `batches` key is gone, so no driver can improvise from it.
6. **Timeouts and reports.**
   - Screening timeouts: `cr_coord.run_retry(job, ..., session_root=<current session root>)`, with a 705 s fence.
   - Completion timeouts stay `unresolved` (open item A).
   - Reports: `<testenv> research/s1/s1_tests/cr_launch.py cr-report <session.sqlite>` per job, plus
     `classification.json` and `completion_record*.json` (merged label: killed / unresolved / deferred / survived),
     consolidated into `a3/t15_cr_<module>.txt`.
   - **[fix-5] Counting:** apply open item I. Each `job_id` counts once, from its latest work_root. Superseded
     results are listed in the superseded-results ledger with their drifted fields.

## Files

**Per screening config:** `cr.toml`, `control.json`, `collect_only.json`, `baseline/{run1..3, timings.json}`,
`inventory.json` (+ `.sha256`) and `inventory_filtered.json` (both re-initialised in fix-1, fix-2, fix-3 and fix-4), `batch_plan.json`
(a calibration-first proposal with no manifest) and `selector_coverage_detail.json`. Shards also have `nodes.txt`,
`ranges.json` and `selection.json`.

**Per completion shard:** `cr_a3/<m>/completion/c<i>/{nodes.txt, selection.json, control.json, collect_only.json,
cr.toml, baseline/}`.

**Per module:** `cr_a3/<m>/completion/pool.json`, `selector_coverage.json`, and the row `ranges.json` for seal and
collect.

**Audit trail:** `cr_a3/_prep/`, which is unreviewed tooling and not tests. It holds:
- `budget_v2.json`, the source of the numbers above;
- `pool_check_pre.json`, `pool_check_post.json`, `measure_io.json`, `reinit_compare.json`,
  `reinit_compare_fix2.json`, `reinit_compare_fix3.json`, `reinit_compare_fix4.json` and **[15c-P]**
  `reinit_compare_15cp.json`, **[15c-P fix 1]** `reinit_compare_15cp_fix1.json` and **[15c-P fix 2]**
  `reinit_compare_15cp_fix2.json`.

**Superseded (kept unedited):**
- `cr_a3/_superseded/s1_collect_v1/`;
- `cr_a3/_superseded/inventories_pre_fix1/`;
- `cr_a3/_superseded/inventories_pre_fix2/`;
- `cr_a3/_superseded/inventories_pre_fix3/`;
- `cr_a3/_superseded/inventories_pre_fix4/`;
- **[15c-P fix 2]** `cr_a3/_superseded/inventories_pre_15cp_fix2/` (the fix-1 inventories, byte-equal to their
  entries in `a3/t15c_prep_hashes_pre_15cp_fix2.txt`, the preserved fix-1 manifest);
- **[15c-P fix 1]** `cr_a3/_superseded/inventories_pre_15cp_fix1/` (the 15c-P inventories, never committed;
  byte-equal to their 15c-P manifest entries);
- **[15c-P]** `cr_a3/_superseded/inventories_pre_15cp/` (the 9330a64 inventories, byte-equal to their committed
  blobs);
- **[15c-P]** `a3/t15c_prep_hashes_at_9330a64.txt`: the committed 1001-entry list, kept unedited as historical
  evidence (Codex N1). Its one generated-cache entry (`_prep/tools/__pycache__/t15c_common.cpython-312.pyc`) was
  never in git; that `__pycache__` directory is removed.

**Hashes:** `a3/t15c_prep_hashes.txt`, LF line endings and `sha256sum -c` compatible. It covers every file under
`cr_a3/`, this document, the RED/GREEN records and the harness and test files.
- **[15c-P fix 2] 1163 entries.** The fix-1 list (1109 entries) is preserved unedited as
  `a3/t15c_prep_hashes_pre_15cp_fix2.txt`.
- **[15c-P fix 1] 1109 entries** (15c-P had 1056). Same rules as 15c-P.
- **[15c-P] 1056 entries.** Generated caches (`__pycache__/`, `*.pyc`) are excluded, and tooling runs with `-B`.
- **[15c-P] Archive check (Codex N1).** `finalize.py hashes` refuses unless every entry is git-tracked or in the
  current `git status --porcelain` modified/untracked set, so nothing ignored can be listed.
- **Not yet verified from a clean archive.** The list's reproducibility from a clean exact-head archive can only be
  checked after a commit. That is the driver review's step.

