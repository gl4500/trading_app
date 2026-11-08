# A3 H1 RED labels (tH1_red.txt)

Part A: 28 instances against the H1 Step-1 stub: **17 RED** (every one an `AssertionError` or a pytest `Failed`; no
ImportError, AttributeError or fixture error), **11 passing**, each labelled below. Part B: the OP-16 pin test against
a clean HEAD export: **1 RED** (AssertionError).

| row | instance | label | why |
|---|---|---|---|
| OP-16 | test_bundle_pins_the_adopted_erratum2_and_clarification1 | `op16-stub` on Part A; **RED** on Part B | ruling OP-16 puts the DOC_PINS entry into Step 1, so the stub passes; its behavioural RED is Part B (HEAD has no pin: `None == 883f09be…`) |
| 460 | nvs, stopped, timeout | **RED** x3 | stub records nothing; the score refuses for another reason: `match=EV` fails |
| 461 | test_already_invalid_reentry_no_recovery_row | `retro` | the gate's INVALID branch (s1_trial.py:721-731) already refuses with no extra row |
| 462 | same-witness | **RED** | the stub never requests a TRIAL-INVALID, so the child never reaches the barrier (`AssertionError: PASSED`) |
| 462 | different-reason-invalid | **RED (barrier only)** | same mechanism as above; not discriminating by itself - its discriminating RED is mutants m1/m2 (tH1_mutants.txt) |
| 463 | test_crash_after_invalid_before_abort_publication | `retro` | the journal INVALID refuses at the gate today |
| 464 | local-witness-kept | **RED** | the refusal text does not state "local abort published" (G6.3 truthfulness) |
| 464 | local-publish-fails | **RED** | the failed publication is swallowed; text lacks "local abort not published" |
| 465 | foreign-root, no-trial, forked-chain, closed, bundle-mismatch, missing-s1-out | `retro` x6 | no recovery exists in the stub; kept as mutant killers m3 (bundle-mismatch) and m4 (missing-s1-out) |
| 466 | permission-error-persistent, read-error-persistent | **RED** x2 | the score ran on, no "aborted.json unreadable (...)" refusal |
| 466 | malformed-confirmed, valid-residual-once | **RED** x2 | no established-violation recording |
| 466 | changed-between-reads, deleted-between-reads | **RED** x2 | no "unconfirmed" refusal |
| 466 | healthy-absence | `ctrl` | absence: the gate proceeds (unchanged) |
| 468 | root-missing-at-entry, root-vanishes-before-publish | **RED** x2 | `Failed: DID NOT RAISE OutputRootGone` (the stub's mkdirs recreate s1_out) |
| 468 | root-vanishes-before-evidence-copy | **RED** | the evidence copy's recursive mkdir recreates s1_out |
| 468 | existing-root-first-wins | `ctrl` | first-wins publication is unchanged |
| 469 | test_default_extra_invalid_observation_still_appends | **RED** | the APPEND half is the control; `recovery=True` still APPENDs on the stub |

Counts: RED 17 (Part A) + 1 (Part B); retro 8 (461, 463, 465 x6); ctrl 2 (466 healthy-absence, 468 first-wins);
op16-stub 1.
