# Row 439 (M4-WORKLOAD-1) - pre-bound measurement record

Status: **declared BEFORE any declared timed run** (Erratum 2 r4 G3.7 item 4; hardening plan H4 Step 8.1). Its sha256
is recorded in `a3/tH4_hashes.txt` and in every run file's header. Implementers never commit (progress.md:5); this
record could not be committed before the runs. Its hash and its write time are the binding instead. Nothing below is
changed after the first declared run; any later note goes into `verdict.md`.

Authority:
- Erratum 2 r4 G3.7 (O10), with the M4-WORKLOAD-1 limitation (Codex 78fdedb4);
- Codex 799fc940 RM-1 (C = L + T; the verdict max(C) <= 60 s; B-CONDITIONAL; controller-accepted 2026-11-08);
- controller rulings OP-13 (a driver subprocess, check free disk first, expected NOT READY until R-3 dispatch
  evidence exists) and OP-14 (a mid-gate bundle mismatch refuses).

## 1. Code measured

- The worktree `C:\Users\gl450\trading_app-s1`, base HEAD 9af5406 (H3) plus the uncommitted H4 working tree.
- The sha256 of every product file at the run is in `a3/tH4_hashes.txt`, and the bundle sha256 is in each fixture's
  `fixture.json`.
- **H5 has not landed.** The hardening plan places Step 8 after H5, on the final pre-AUDIT head. The controller
  directed this measurement now. Any later change on the scheduled-checkpoint critical path voids it. The driver is
  re-runnable as it stands.

## 2. Workloads

Both workloads use the same calendar and lifecycle:
- **Calendar.** A synthetic weekday calendar (`conftest.s1_plan_audit`), START 2026-10-26T13:30Z. The deadline is
  START + 6 months. That gives **130 eligible closes** and about 4,108 registered slots (about 3,978 of them non-W).
- **Lifecycle.** The real lifecycle through `conftest.s1_state`: plan, audit stage, opening checkpoint and stage, START
  attestation, prereg and PREREG-ACK.
- **History.** Built through the real product steps: `conftest._write_seal` (with_stage=False), then
  `s1_slot.run_seal_stage` for each close's first QUALIFIED slot, then `s1_slot.finalize_close` at that close's W + 1
  s. That gives MISSED at E for every slot without a row.
- **Trial state.** The cohort is 100 lots, 99 of them sold (the row-302 shape), so there is no lots stop. The trial is
  ACTIVE and RUNNING.
- **Measured invocation.** `s1_checkpoint.run_checkpoint` for the first slot (close + 45 min) of the **130th**
  eligible close, at a moving clock (that slot + 30 s + elapsed).

| workload | QUALIFIED trees | backup bytes per tree | growth margin | journal J |
|---|---|---|---|---|
| **low-Q** | 129 sealed closes, each with exactly one QUALIFIED (its first slot) and every later slot MISSED, plus the opening's tree | **15.2 MB**: 7.6 MB, the live trading.db size by stat only (progress.md:130), × the declared growth margin 2 | ×2 | as built (expected about 4,500 rows: 31 terminal rows per close plus seal-stage rows) |
| **high-Q** | 129 sealed closes, each with **every non-W slot QUALIFIED** (the G3.7 stress model; post_start_gate checks only the PREREG-ACK) and the W slot MISSED, plus the opening's tree. About 3,850 trees | **7.6 MB** | ×1 (see below) | as built (expected about 8,400 rows) |

- **Measured workload.** Each fixture's actual numbers are recorded in its `fixture.json`: N_QUALIFIED, the total
  backup bytes, J and the projection sizes.
- **Opening tree.** It was captured before the ledger was padded, so it is small. This is disclosed.
- **Backup content.** Each tree's backup.sqlite3 is a byte copy of the synthetic ledger (the conftest `Ledger`), padded
  with an `m4_filler` BLOB table to the declared size. The measured invocation's own capture backs up that same ledger.
- **Projection and trade sizes.** These are the synthetic cohort's: at most about 45 KB per projection.

**Declared unresolved workload bounds.** Each of these keeps the verdict NOT READY on its own:
- (a) High-Q is measured at margin ×1. A ×2 byte margin (about 60 GB) is not measured.
- (b) The live projection and trade sizes at month 6 are not modelled.
- (c) The live calendar has holidays and early closes. The synthetic calendar does not.

## 3. Contention profiles

- **idle**: no load induced by the driver. Other user processes are not controlled, for example the polymarket_app
  backend and the session bridges that were running. They are listed in `verdict.md`.
- **contended**:
  - `os.cpu_count()` (12) CPU-burner processes, each looping sha256 over a 16 MB in-memory buffer;
  - one I/O writer, writing 64 MB chunks with fsync across 16 rotating files under the scratchpad;
  - all at normal priority, started 2 s before the due instant is chosen, and killed after the child exits.

## 4. Cache states

- **cold**: a fresh `robocopy /E /J` copy of the whole pristine fixture, with no warm-up read. /J is unbuffered: the
  copy is real, and the copy's pages are not left in the file cache. The sanity check is in `coldcheck.txt`: first read
  of a /J copy about 1.07 GB/s, second about 1.96 GB/s, sha256 about 0.33 GB/s.
- **warm**: a buffered copy, followed by a full read of every file of the run root before the due instant. For high-Q
  the backups are **hard-linked** to the pristine fixture, which the product only reads.
- **In both states**, `resolution.json` records each candidate's capture dir as an absolute path, and that path names
  the pristine fixture. So the projection reads of `seal_bytes` go to the pristine fixture's small JSON files. This is
  disclosed.

## 5. Sample counts per cell (workload × contention × cache)

- low-Q: **n = 5** per cell (4 cells, 20 runs);
- high-Q: **n = 3** per cell (4 cells, 12 runs).

Every declared run counts: none is dropped or re-run. A run whose child does not complete its success control stays in
the sample as a failed control.

## 6. Instants, spans and the success control (RM-1)

**Instants** (defined before measuring, so that startup is counted once):
- **due**: a wall-clock instant the driver fixes 1 s ahead (`time.time() + 1`). The driver sleeps until it.
- **launch**: wall time (`time.time()`) and `time.perf_counter()`, sampled immediately before `subprocess.Popen` of the
  child (the testenv interpreter running `driver.py child`).
- **required completion**: the child process's exit, observed by `wait()`. It comes after `run_checkpoint` returned and
  the child wrote child.json.

**Spans:**
- **T** = perf_counter(completion) − perf_counter(launch), seconds. perf_counter is QueryPerformanceCounter: monotonic
  and system-wide. T covers interpreter startup, imports, the trial gate and every evidence pass, the A8.2
  registration, the slot work lock, SLOT-INTENT and the claim, the capture (the ledger backup and projection), receipt
  and process observation, P, R, J, the post-terminal finalizer and seal stage of the close, `_finalize_others`,
  `_finalize_last_if_due`, `decide_stop`, `current_stop`, after.json and the child's own record.
- **L_driver** = launch_wall − due_wall: the **driver's** dispatch delay. It is not the Task Scheduler's: the driver
  cannot observe scheduler dispatch (RM-1).
- **Clock relation**: each run records (end_wall − launch_wall) − T, and both clocks' resolution.

**Per-gate spans** are diagnostics only. They are wall time and call counts of the trial gate, the evidence check and
passes, `finalize_close`, `run_seal_stage`, `decide_stop`, `stop_record`, the journal reads and appends, and the hashing
calls. There is no per-gate cap, and no nested span is summed into T.

**Success control:**
- Pass: the journal outcome APPEND of SLOT-QUALIFIED, and the close's seal written.
- Anything else, a refusal included, is a failed control. A fast refusal is not a pass.

## 7. Dispatch lateness and the pass rule (RM-1, G3.7)

- **No R-3 scheduler-dispatch evidence exists**, and **no dispatch-lateness bound B is declared**. No justified value
  is available, and none is invented here.
- **Verdict for row 439:** `verdict_rule.b_conditional(runs, None)` gives **NOT READY with R-3 unresolved**. max(T) is
  reported over all declared healthy runs, and per cell.
- **For information only**, `verdict_rule.verdict` is also reported over the runs with L = L_driver. That
  "driver-dispatch C" is never a readiness verdict.
- **READY would require all of the following:**
  - every declared healthy run's C = L + T <= 60 s, with L the scheduler's dispatch delay;
  - every success control completed;
  - every workload bound resolved.

  None of these is relaxed after the runs. There is no evidence-cache shortcut.

## 8. Injected cases

- Outage, missed-run and very-late-recovery cases are not run in H4.
- Their correctness is covered by rows 410-426 and the H3 tests. Their availability lateness needs R-3 scheduler
  evidence.
- They are reported as unresolved and are not part of the healthy sample.

## 9. Safety

- The driver redirects `s1_common.MAILBOX` and `s1_receipt.HMAC_KEY` to the run root, and asserts the mailbox is not
  the coordination mailbox.
- It moves `s1_checkpoint.LIVE_DB`, `REPO` and `CRASH_LOG` to non-existent paths under the root, and patches
  `socket.create_connection` and `httpx.HTTPTransport.handle_request` to raise.
- Every root must lie under the session scratchpad. A path naming trading.db, the coordination directory or the app
  repository refuses.
- mailbox.py is never imported, and `s1_checkpoint.main` is never called.
- The big fixtures stay in the scratchpad (free disk was checked first, about 1.2 TB) and are deleted after the runs
  are recorded.
