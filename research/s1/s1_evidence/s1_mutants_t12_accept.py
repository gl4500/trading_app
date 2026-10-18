"""Task 12 fix round 1 (m-2): per-mutant declared INTENDED exceptions. A kill through an exception counts as KILLED
only when the exception is the intended test's own observation of the intended outcome (listed here with the
reason); every other exception kill is reported as KILLED-BY-EXCEPTION and not counted."""
from s1_mutants_t12_list import MUTANTS

ABORT = "the intended test reads the persisted aborted.json it asserts exists; its absence raises FileNotFoundError"
ESCAPE = "the intended outcome is that this exception is preserved, not raised; the escaping exception is the detection"
KEY = "the intended test reads the report/seal key it asserts; its absence raises KeyError"
WRONG_EXC = "the intended test expects a specific exception; the mutant raises another one instead"
REFUSE = "the intended outcome is that the command proceeds; the mutant's refusal (SystemExit) is the detection"
ACCEPT = {
    "bundle_gate: a registered mismatch is a refusal only (no persistent abort)": (("FileNotFoundError",), ABORT),
    "bundle_gate accepts any bundle": (("FileNotFoundError",), ABORT),
    "receipt_sha256 accepts a fingerprint-less receipt": (("KeyError",), WRONG_EXC),
    "registration: audit stage never registered": (("FileNotFoundError",), ABORT),
    "_safe re-raises": (("RuntimeError", "ValueError"), ESCAPE),
    "_capture: a snapshot exception is not preserved": (("ValueError",), ESCAPE),
    "_observe_process: process exceptions crash": (("RuntimeError",), ESCAPE),
    "_candidate omits the bridge record": (("KeyError",), KEY),
    "_seal_from: seal records no bundle": (("SystemExit",),
                                           "the START attestation refuses because the opening seal records no bundle - "
                                           "the very property the test asserts"),
    "_seal_from: seal records no capture start/end": (("KeyError",), KEY),
    "_trial_stop never persists (stop decision only)": (("KeyError",), KEY),
    "run_checkpoint: stop not persisted at the stop seal": (("FileNotFoundError",),
                                                            "the intended test reads stop.json, which must exist"),
    "_trial_state: an aborted trial is not reported ABORTED": (("SystemExit",), REFUSE),
    "load_stop never finds the stop": (("KeyError", "SystemExit"), KEY),
    "current_stop recomputes even when persisted": (("KeyError",), KEY),
    "_read_seals: a corrupt seal crashes": (("JSONDecodeError",), ESCAPE),
    "verify_bundle_first: prereg refusal before the comparison (m-1 regression)": (("FileNotFoundError",), ABORT),
    "do_audit.body: no calendar pin written": (("FileNotFoundError",),
                                               "the intended test reads calendar_source.json, which must exist"),
    "do_final: registration not verified": (("FileNotFoundError",), ABORT),
    "contract ignores the env override": (("ReceiptError",), REFUSE),
    "closure root check skipped": (("FileNotFoundError",), WRONG_EXC),
    "process_identity reports no binding": (("KeyError",), KEY),
    "_ack: an unreadable mailbox crashes": (("OperationalError",), ESCAPE),
    "attest_start: bundle not verified first": (("FileNotFoundError",), ABORT),
    "do_prereg: no pre-START bound": (("SystemExit",), REFUSE),
    "_pre_start_day is START's day": (("SystemExit",), REFUSE),
    "carry_in_reasons: until not applied": (("SystemExit",), REFUSE),
    "_trial_end: integrity failure still demands the final manifest": (("FileNotFoundError",),
                                                                       "the intended test reads score/s1.json, which "
                                                                       "must be written"),
    "score: bundle not verified first": (("FileNotFoundError",), ABORT),
    "_report_restarts_and_bridge omits the capture notes": (("KeyError",), KEY),
}
_names = {m["name"] for m in MUTANTS}
_missing = sorted(set(ACCEPT) - _names)
assert not _missing, _missing
for m in MUTANTS:
    if m["name"] in ACCEPT:
        m["accept"], m["accept_why"] = ACCEPT[m["name"]]
