"""S1 Task 9 round 2: declared Cosmic Ray scope reduction for s1_run.py (controller ruling 1: the >6 h estimate
limits s1_run to the functions that decide outcomes). Deletes the work items of the EXCLUDED functions from an
initialised session and prints every excluded function with its job count. Usage: python cr_scope.py SESSION_DIR"""
import ast
import collections
import sqlite3
import sys
from pathlib import Path

# Report-only / plumbing helpers: they decide no verdict, gate, exclusion, economics, attestation, bridge or
# final-snapshot outcome (every other function, and the module-level constants, stay in scope).
EXCLUDED = {
    "_median": "descriptive holding-age statistic in the report (after the verdict is fixed)",
    "_restarts": "report-only restart summary (observed minimum + gaps), no outcome reads it",
    "_clean": "JSON serialisation of the finished report",
    "_serialise": "JSON serialisation of the finished report",
    "_out": "path helper (s1_out)",
    "_seals": "file listing helper",
    "_sha_or_absent": "hash-or-placeholder helper (its callers run_token/score_token stay in scope)",
    "_ack": "thin wrapper turning sqlite3.Error into a refusal (the ACK rules live in s1_collect._ack)",
    "_write_once": "thin wrapper over s1_collect._write_once",
}

d = Path(sys.argv[1])
src = (d / "s1_run.py").read_text(encoding="utf-8")
fns = [(n.lineno, n.end_lineno, n.name) for n in ast.parse(src).body if isinstance(n, (ast.FunctionDef, ast.ClassDef))]


def owner(row: int) -> str:
    return next((nm for a, b, nm in fns if a <= row <= b), "<module>")


con = sqlite3.connect(d / "cr.sqlite")
rows = con.execute("SELECT job_id, start_pos_row FROM mutation_specs").fetchall()
drop = collections.Counter()
for jid, row in rows:
    f = owner(row)
    if f in EXCLUDED:
        drop[f] += 1
        con.execute("DELETE FROM work_items WHERE job_id=?", (jid,))
        con.execute("DELETE FROM mutation_specs WHERE job_id=?", (jid,))
con.commit()
left = con.execute("SELECT count(*) FROM work_items").fetchone()[0]
print(f"s1_run.py declared scope reduction: {len(rows)} jobs initialised, {sum(drop.values())} excluded, {left} kept")
for f in EXCLUDED:
    print(f"  excluded {f}: {drop[f]} jobs - {EXCLUDED[f]}")
