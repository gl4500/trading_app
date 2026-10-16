"""List Cosmic Ray results of the executed shard sessions: per-shard outcome counts, and every non-killed job with its
source line (for triage). INCOMPETENT jobs are classified from the recorded worker traceback: cosmic-ray 8.3.15 marks
a job INCOMPETENT when the FAILING test run's output is not UTF-8 (cp1252 '§' in a traceback), i.e. the test command
had already exited non-zero ("returned non-zero exit status 1" = killed by the focused set).
Usage: python cr_survivors.py WORK_DIR [OUT.tsv]"""
import collections
import glob
import sqlite3
import sys
from pathlib import Path

work = Path(sys.argv[1])
rows, counts = [], collections.Counter()
for d in sorted(glob.glob(str(work / "s1_*_s[0-9]"))):
    d = Path(d)
    src = {}
    con = sqlite3.connect(d / "cr.sqlite")
    total = con.execute("SELECT count(*) FROM work_items").fetchone()[0]
    for jid, mod, op, occ, row, col, wo, to, out in con.execute(
            """SELECT s.job_id, s.module_path, s.operator_name, s.occurrence, s.start_pos_row, s.start_pos_col,
                      r.worker_outcome, r.test_outcome, r.output
               FROM work_results r JOIN mutation_specs s ON s.job_id = r.job_id"""):
        if to == "INCOMPETENT":
            kind = ("KILLED(non-utf8 output)" if "returned non-zero exit status 1" in (out or "")
                    else "INCOMPETENT(other)")
        else:
            kind = to
        counts[(d.name, kind)] += 1
        if kind not in ("KILLED", "KILLED(non-utf8 output)"):
            if mod not in src:
                src[mod] = (d / mod).read_text(encoding="utf-8").splitlines()
            rows.append((d.name, jid, mod, row, col, op.replace("core/", ""), occ, kind,
                         src[mod][row - 1].strip()[:140]))
    counts[(d.name, "total")] = total
    con.close()
for k in sorted(counts):
    print(*k, counts[k])
if len(sys.argv) > 2:
    Path(sys.argv[2]).write_text("\n".join("\t".join(map(str, r)) for r in rows) + "\n", encoding="utf-8")
print(len(rows), "not killed")
