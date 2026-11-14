# Row 439 (G3.7, O10, M4-WORKLOAD-1; RM-1): verdict

## **NOT READY**

The verdict is NOT READY for each of the following reasons, independently:
1. **R-3 is unresolved.** No scheduler-dispatch evidence exists, and no dispatch-lateness bound B was predeclared
   (record.md section 7). With B unknown, RM-1 B-CONDITIONAL is NOT READY.
2. **max(T) = 373.70 s**, over all 32 declared healthy runs (high-Q / contended / cold). That is above the 60 s cap
   even with L = 0. **6 of the 8 cells** have a max(T) over 60 s (cells are workload × contention × cache). Only the two low-Q / idle
   cells stay under it, at 37.39 s and 36.64 s.
3. **Declared unresolved workload bounds** (record.md section 2): high-Q at margin ×1, live projection sizes, holidays
   and early closes.
4. **Injected cases** were not run (record.md section 8).

| | |
|---|---|
| Pre-bound record | record.md, sha256 `aac473252547579d20762de6b62a87a66a35e70443e3214e45d1603f1a8eeffd`, written 2026-11-09T12:44Z |
| Declared runs | 13:52Z to 15:23Z |
| Code | 9af5406 plus the H4 working tree; bundle sha256 `64b37236f4a92a89362d0fd9e5c7244d503780c147925ce38c64c3098d6d1cc2` |
| Runs | 32 of 32 declared runs completed, all with the success control completed (APPEND SLOT-QUALIFIED, and the close's seal written). No run was dropped or repeated |
| Script | `driver.py summarize` produced `summary.json` |
| Logs | `build_low-Q.txt`, `build_high-Q.txt`, `measure_all.txt` (renamed from `.log` in H4 fix round 1, bytes unchanged, so that `.gitignore`'s `*.log` does not drop hashed evidence; the hashes in `a3/tH4_hashes.txt` follow the new names) |

### Correction (H4 fix round 1, review M-4): how record.md is bound

record.md section 0 says its sha256 is "in every run file's header". **That is wrong:** none of the 32 run JSON files
contains it (record.md is frozen, so the correction is made here). The actual binding evidence is weaker, and is only
this:
- the sha256 `aac47325…` stated by the implementer, and matching both the scratchpad draft (mtime 2026-11-09T12:43:00Z)
  and the repo copy (mtime 12:44:07Z);
- both mtimes precede the first declared run file (13:52:46Z);
- `a3/tH4_hashes.txt`, which lists the same hash, was written after the runs (16:50Z).

No commit and no run file binds record.md before the runs. The binding is therefore consistent, but not
cryptographic: it rests on the implementer's statement and on file mtimes.

### H5 voids this measurement by construction

H5 changes the measured code in two ways:
- it adds Erratum 2 Clarification 2 to `DOC_PINS`, so the bundle sha256 changes (the fixtures' `64b37236…` is no longer
  the code's bundle);
- it adds the Clarification 2 close-identity eligibility guard for new post-START SLOT-INTENTs (F0.5 step 5), which
  is on the scheduled-checkpoint path.

Codex 55c51f51's Q2 (one verified module passed down `stop_record` / `sampled_seals` / NVS) also lands in H5. This
record therefore cannot stand as row-439 evidence for the final code. **Row 439 must be re-run on the final head**, in
a separately predeclared, controller-committed campaign. The expected verdict is still NOT READY.

## Per cell

T is the launch to the child's exit, by perf_counter. L_driver is the driver's own dispatch, not the scheduler's.

| workload | contention | cache | n | controls | min T (s) | **max T (s)** | max L_driver (ms) | max C_driver (s), information only |
|---|---|---|---|---|---|---|---|---|
| low-Q | idle | warm | 5 | 5 | 35.48 | **37.39** | 1.6 | 37.39 |
| low-Q | idle | cold | 5 | 5 | 36.08 | **36.64** | 1.3 | 36.64 |
| low-Q | contended | warm | 5 | 5 | 100.26 | **103.85** | 1.2 | 103.85 |
| low-Q | contended | cold | 5 | 5 | 101.80 | **105.59** | 1.4 | 105.59 |
| high-Q | idle | warm | 3 | 3 | 112.35 | **121.28** | 1.1 | 121.28 |
| high-Q | idle | cold | 3 | 3 | 133.94 | **136.90** | 2.0 | 136.90 |
| high-Q | contended | warm | 3 | 3 | 317.22 | **342.27** | 1.0 | 342.27 |
| high-Q | contended | cold | 3 | 3 | 360.01 | **373.70** | 1.0 | 373.70 |

**Workloads as built** (`fixture_*.json`):

| | low-Q | high-Q |
|---|---|---|
| QUALIFIED trees | 130 (129 + the opening) | 3,910 |
| backup bytes | 2.056 GB (15.94 MB each; the opening's is small) | 31.16 GB (7.97 MB each) |
| journal rows J | 4,637 | 8,417 |
| projections | at most 45 KB | at most 45 KB |
| eligible closes | 130 | 130 |
| measured slot | 2027-04-23T20:45Z | 2027-04-23T20:45Z |

**Clocks.** The clock relation, (end_wall − launch_wall) − T, lies within [−0.10 ms, +0.03 ms] across the runs. No
discontinuity was seen. L_driver lay between 0.1 and 2.0 ms and was never negative.

## Diagnostics: per-gate spans

These are seconds of wall time inside each function. They are diagnostics only: nested spans overlap and are not
summed (RM-1).

| run | gate (evidence pass) | decide_stop → stop_record | `_finalize_others` | sha256_file calls / s | load_pinned calls / s |
|---|---|---|---|---|---|
| low-Q idle warm 01 (T 36.0) | 7.20 | 21.05 / 20.99 | 5.08 | 25,560 / 13.8 | 23,441 / 10.5 |
| low-Q contended cold 05 (T 105.6) | 23.28 | 61.56 / 61.34 | 13.31 | 25,560 / 42.4 | 23,441 / 27.3 |
| high-Q idle warm 01 (T 121.3) | 93.24 | 18.50 / 18.38 | 5.14 | 44,460 / 89.2 | 23,441 / 10.5 |
| high-Q contended cold 03 (T 373.7) | 292.01 | 54.93 / 54.57 | 13.96 | 44,460 / 283.5 | 23,441 / 27.9 |

**Reading the diagnostics.** These are observations, not a readiness argument.
- **The M4 gate path is no longer the low-Q bottleneck.** It costs about 7 s idle. The gate makes ONE evidence pass:
  130 trees hashed once, and the pin verified once in the pass.
- **The low-Q critical path is dominated by the post-terminal stop decision.** `decide_stop` → `stop_record` takes
  about 21 s idle and about 61 s contended:
  - it re-hashes the 129 selected trees: a new evidence read, allowed by G3;
  - it makes about 23,400 `load_pinned` verifications (about 10.5 s idle), because `s1_seal.stop_record`,
    `_close_state` and the `count_sold` economics call `c.sim()` per call;
  - `_finalize_others` adds 5-14 s (`day_for` per slot subject, with no pass).

  Pass-scoping those callers was outside H4's brief (s1_seal changed only by the `sim=` keywords). See the report's
  D-2 section.
- **The high-Q critical path is dominated by hashing.** The single gate pass hashes about 31 GB at about 0.33 GB/s
  (this CPU, an i7-10750H, has no SHA-NI). That alone is 89 s idle and 284 s contended. Even with every other cost
  removed, one pass of high-Q hashing is above 60 s on this machine.

## Conditions and limitations

- **Ambient load on "idle".** "Idle" means no load from the driver. Other user processes were running and were not
  controlled:
  - the polymarket_app backend (`main.py --mode replace`, under two interpreters);
  - the session_bridge and task_coordinator processes;
  - a weekday_candle_replication controller.
- **Cold reads.** Cold runs read a `robocopy /J` copy. The coldcheck shows the first read slower than the second
  (about 1.07 against 1.96 GB/s). Hashing dominates in either case.
- **The H5 caveat.** Measured before H5, on the controller's direction. An H5 change on this path voids the
  measurement. Re-run with:

  ```
  driver.py build ...
  measure_all.sh   (the scratchpad copy of the driver loop)
  driver.py summarize
  ```
- **Fixtures deleted.** The pristine fixtures (low-Q 2.1 GB, high-Q 31 GB) and the run roots were deleted from the
  scratchpad after this record.
