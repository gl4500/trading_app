# A3 Task 15c-prep + 15c-H: Cosmic Ray configs, baselines, scopes, inventories, completion shards and session plan (NO mutant executed)

**Version.** This is v4, updated for 15c-H fix round 2, which addresses re-review 1 in `task-15c-h-review-verdict.md`.
- v3 was regenerated for fix round 1.
- v2 was regenerated for Task 15c-H.
- v1 is what Codex reviewed as `t15c_prep_review_20261116`.
- Changes are marked **[15c-H]**, **[fix-1]** and **[fix-2]**.

**Sources.**
- Briefs: `task-15c-prep-brief.md`, the 15c-H coordinator message (rulings 1–7 adopting Codex's
  `t15c_prep_review_20261116/REVIEW.txt`), and the fix-round-1 message, which carries rulings 1–7 on the task review
  `task-15c-h-review-verdict.md`.
- The fix-round-1 addendum, rulings (a)–(e), draws on Codex's early number check:
  `C:/Users/gl450/.coordination/trading_app/t15ch_early_numbers_20261116/EARLY_NUMBER_CHECK.txt`.

**Head.** HEAD is 2a4bdd1. The 7 product modules, `research/s1/docs`, `conftest.py`, `a3_helpers.py` and the 12
selector test files are byte-identical to BASE 02db5b9.

**Nothing was executed against a mutant.** The only Cosmic Ray command run was `cosmic-ray init`, on scratch copies,
through `cr_launch.py`. Product source is untouched. The harness changes are uncommitted, and `git status` shows only
these:
- `cr_coord.py`, `cr_reconcile.py`;
- the new `test_s1_a3_cr_completion.py`;
- the evidence under `s1_evidence/`.

**Interpreter.** The testenv is 3.12.12, with Cosmic Ray 8.3.15 and pytest 8.3.3. Everything ran serially, with no
xdist and a single lane (ruling 3).

## Harness changes (15c-H rulings 1–3 + fix round 1)

**Evidence files.**

| File | Run | Result |
|---|---|---|
| `a3/t15c_h_red.txt` | first 15c-H RED | Kept as recorded. A fix-1 annotation names both test-file sha256s. |
| `a3/t15c_h_fix1_red.txt` | fix-1 RED | **23 failed**: 15 AssertionError + 8 `DID NOT RAISE`. 72 passed. |
| `a3/t15c_h_fix1_green.txt` | fix-1 GREEN | **97 passed.** Also holds the deletion checks, plus a fix-2 **correction** (R1-I1). |
| `a3/t15c_h_fix2_red.txt` | fix-2 RED | **4 failed**: 1 AssertionError + 3 `DID NOT RAISE`. 102 passed. |
| `a3/t15c_h_fix2_green.txt` | fix-2 GREEN | **106 passed.** Also holds the fix-2 deletion checks. |
| `a3/t15c_h_green.txt` | regenerated GREEN | Same final files: **106 passed**. |

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
| `cr_coord.py` | 235e5285fc9cbd82dc7cdbf1b6ecb18acf4cb8a1656a7eeba4cd7b37a5ea4019 | changed (fix-2) |
| `cr_reconcile.py` | 1e1c07fdd1abb0177c57b7084b0c574dc3aa7aff6583542485fcedcfa2e2ce4d | changed (fix-1; not changed in fix-2) |
| `cr_guard.py` | 54e88df7…7f76 | unchanged |
| `cr_launch.py` | b6aa8d2a…2f00 | unchanged |

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

**G. Equivalent deletion mutants: one remains.**
- Only the explicit zero-shard check survives deletion, and it is equivalent: `load_pool` refuses an empty pool, so
  `check_pool_union(pool, [])` always reports missing nodes.
- **[fix-2] Correction:** fix-1 also listed the clean conjunct of the kill short-circuit as equivalent. That was
  **wrong**: an unclean kill whose stop was resolved would short-circuit a later clean kill and turn `killed` into
  `unresolved`.
  - The guard is now pinned by `test_R1_I1_resolved_unclean_kill_does_not_short_circuit_a_later_clean_kill`, and
    deletion G10 is caught.
  - The fix-1 record keeps its original text, with a correction appended.

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
3. **Calibration session** (one session root per session):

   ```
   cr_coord.write_manifests(<root>/<C>, [batch_plan.json["calibration_batch"]], sha256(<E>/inventory.json))
   cr_coord.run_manifest(<root>/<C>/batch_000.json, <E>/inventory.json, src_root=..., copy_paths=...,
                         work_root=<root>/<C>/session-000, exec_seam=cr_coord.real_exec(cfg), config=identity)
   ```

   The HARD 405 s fence and the monotonic session clock apply. After any reboot, sleep or hibernate, start a new
   session root.
4. **Completion of each screening survivor `j`** in that session:

   ```
   cr_coord.run_completion(j, items_by_id,
                           [{"name": "c<i>", "cfg": cfg_c<i>, "copy_paths": ...} for every c<i>],
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
   `run_manifest(..., cap_record=<that path>, config=identity)` in its own session root. The record is re-verified on
   every use, and the fence, not the cap, bounds every session.
6. **Timeouts and reports.**
   - Screening timeouts: `cr_coord.run_retry(job, ..., session_root=<current session root>)`, with a 705 s fence.
   - Completion timeouts stay `unresolved` (open item A).
   - Reports: `<testenv> research/s1/s1_tests/cr_launch.py cr-report <session.sqlite>` per job, plus
     `classification.json` and `completion_record*.json` (merged label: killed / unresolved / deferred / survived),
     consolidated into `a3/t15_cr_<module>.txt`.

## Files

**Per screening config:** `cr.toml`, `control.json`, `collect_only.json`, `baseline/{run1..3, timings.json}`,
`inventory.json` (+ `.sha256`) and `inventory_filtered.json` (both re-initialised in fix-1 and fix-2), `batch_plan.json`
(a calibration-first proposal with no manifest) and `selector_coverage_detail.json`. Shards also have `nodes.txt`,
`ranges.json` and `selection.json`.

**Per completion shard:** `cr_a3/<m>/completion/c<i>/{nodes.txt, selection.json, control.json, collect_only.json,
cr.toml, baseline/}`.

**Per module:** `cr_a3/<m>/completion/pool.json`, `selector_coverage.json`, and the row `ranges.json` for seal and
collect.

**Audit trail:** `cr_a3/_prep/`, which is unreviewed tooling and not tests. It holds:
- `budget_v2.json`, the source of the numbers above;
- `pool_check_pre.json`, `pool_check_post.json`, `measure_io.json`, `reinit_compare.json` and
  `reinit_compare_fix2.json`.

**Superseded (kept unedited):**
- `cr_a3/_superseded/s1_collect_v1/`;
- `cr_a3/_superseded/inventories_pre_fix1/`;
- `cr_a3/_superseded/inventories_pre_fix2/`.

**Hashes:** `a3/t15c_prep_hashes.txt`, LF line endings and `sha256sum -c` compatible. It covers every file under
`cr_a3/`, this document, the RED/GREEN records and the harness and test files.

