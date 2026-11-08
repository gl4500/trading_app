"""A3 Task 13 fix round 1: apply one mutant to a SCRATCH copy of research/s1 (never the worktree)."""
import sys
from pathlib import Path

base = Path(sys.argv[1]) / "research" / "s1"
which = sys.argv[2]


def sub(rel, old, new):
    p = base / rel
    b = p.read_bytes()
    crlf = b"\r\n" in b
    t = b.decode("utf-8").replace("\r\n", "\n")
    assert t.count(old) == 1, (rel, t.count(old))
    t = t.replace(old, new)
    if crlf:
        t = t.replace("\n", "\r\n")
    p.write_bytes(t.encode("utf-8"))


if which == "m5":      # (reviewer's I-1 mutant) the observation drops _score's reasons
    sub("s1_run.py", '"score_reasons": _clean(rep.get("reasons"))', '"score_reasons": None')
elif which == "m6":    # M-4: the envelope's sampled history runs to the journal head, not the STOP
    sub("s1_run.py", "z.sampled_history(gv.rows, stop_row, seals)", "z.sampled_history(gv.rows, gv.rows[-1], seals)")
elif which == "m7":    # M-4: the final-manifest input hashes another file
    sub("s1_run.py", 'inputs = {"final/manifest.json": c.sha_or_absent(out / "final" / "manifest.json"),',
        'inputs = {"final/manifest.json": c.sha_or_absent(out / "attest_stop.json"),')
elif which == "m8":    # M-3: the OQ-16 INVALID fires with another reason (a loose "INVALID" regex accepts it)
    sub("s1_run.py", '    s1_trial.invalidate(gv.trial, "registration-artifact",\n                        {"where": "score", "final_snapshot"',
        '    s1_trial.invalidate(gv.trial, "stage-replaced",\n                        {"where": "score", "final_snapshot"')
    sub("s1_run.py", 'missing or changed: "\n                     "INVALID (registration-artifact)")',
        'missing or changed: "\n                     "INVALID (stage-replaced)")')
print("mutated", which)
