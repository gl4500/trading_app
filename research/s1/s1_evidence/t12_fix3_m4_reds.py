"""Task 12 fix round 3 (re-review M-4): BEHAVIOURAL REDs for the Addendum 2 acceptance examples whose fix-round-2 RED
was missing-interface only. Each example's test is run (with the mutant harness's isolated bundle copy, s1_mutants_t12.one)
against the current code with exactly the guard that implements the example REVERTED to the pre-Addendum-2 behaviour;
a behavioural RED = the example's test fails on an assertion. Evidence tool, not product code.
Usage (from research/s1): python s1_evidence/t12_fix3_m4_reds.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import s1_mutants_t12 as H  # noqa: E402

B1, B2, B3 = "test_s1_t12_fix2_b1.py::", "test_s1_t12_fix2_b2.py::", "test_s1_t12_fix2_b3.py::"
REVERSIONS = [
    {"name": "B1.6 just-before/at-D: no resolution deadline (a report at/after D still publishes SUCCESS)",
     "file": "s1_checkpoint.py", "function": "_publish",
     "edits": [("s1_checkpoint.py", "    if t < dl and not rp.exists():", "    if not rp.exists():")],
     "tests": [B1 + "test_b1_a_success_published_strictly_before_D_qualifies_at_or_after_D_it_times_out"],
     "intent": "publication at D is a timeout"},
    {"name": "B1.6 expiration-vs-late: the resolution is not exclusive (the last writer wins)",
     "file": "s1_checkpoint.py", "function": "_resolve",
     "edits": [("s1_checkpoint.py",
                '''        c.publish_exclusive(p, json.dumps(rec, indent=1, sort_keys=True).encode("utf-8"))''',
                '''        c.replace_atomic(p, json.dumps(rec, indent=1, sort_keys=True))'''),
               ("s1_checkpoint.py", "    if t < dl and not rp.exists():", "    if t < dl:")],
     "tests": [B1 + "test_b1_expiration_racing_a_late_completion_cannot_change_the_winner"],
     "intent": "one exclusive irreversible transition per slot"},
    {"name": "B1.6 killed-vs-slow: a claimed slot without a report is MISSED after E (the pre-Addendum-2 rule)",
     "file": "s1_checkpoint.py", "function": "finalize_close",
     "edits": [("s1_checkpoint.py", "            if _claim_path(cap_dir).exists():", "            if False:")],
     "tests": [B1 + "test_b1_killed_and_merely_slow_workers_get_the_same_timeout_disposition"],
     "intent": "killed and slow workers both get RESOLUTION-TIMEOUT at D"},
    {"name": "B2.5 identical restart: PID / start time compared as binding (a restart is a change)",
     "file": "s1_checkpoint.py", "function": "_binding",
     "edits": [("s1_checkpoint.py", "    if b == ref:", '    if b == ref and proc.get("process_start") is None:')],
     "tests": [B2 + "test_b2_an_identical_binding_restart_is_provenance_not_a_semantic_change"],
     "intent": "an identical-binding restart is provenance only"},
    {"name": "B3.1 registry: no registration record is written",
     "file": "s1_common.py", "function": "register_stage",
     "edits": [("s1_common.py", '''    for p in stage_records(out, stage):
        try:
            publish_exclusive(p, data)''', '''    for p in stage_records(out, stage)[:0]:
        try:
            publish_exclusive(p, data)''')],
     "tests": ["test_s1_t12_fix2_mutants.py::test_mt_the_opening_is_registered_with_its_seal_hash"],
     "intent": "the registry records every registered stage"},
]


def main():
    print(__doc__.splitlines()[0])
    counts = {}
    for m in REVERSIONS:
        x = H.one(m)
        counts[x["tag"]] = counts.get(x["tag"], 0) + 1
        print(f"\n[{'BEHAVIOURAL RED' if x['tag'] == 'KILLED' else x['tag']}] {m['name']}")
        print(f"  reverted guard: {m['file']}::{m['function']}   test: {', '.join(m['tests'])}")
        for tid, msg in x["hit"]:
            print(f"  failing: {tid} :: [{H.kind_of(msg)}] {(msg or '').strip()[:300]}")
        print(f"  pytest rc={x['rc']}: {x['tail']}")
    print("\nSUMMARY " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))


if __name__ == "__main__":
    main()
