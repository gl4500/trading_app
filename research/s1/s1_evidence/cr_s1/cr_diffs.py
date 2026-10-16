"""Triage helper: for every job in a recheck TSV, re-apply the mutation (`cosmic-ray apply`) to a fresh temp copy of
the submitted sources and print the changed line(s) before/after (no tests run). Temp dirs are removed.
Usage: python cr_diffs.py RECHECK.tsv OUT.tsv [MODULE]"""
import difflib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

S1 = Path(__file__).resolve().parents[2]
CR = "C:/Users/gl450/.coordination/trading_app/testenv/Scripts/cosmic-ray.exe"
rows = [ln.split("\t") for ln in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() if ln and ln[0] != "#"]
want = sys.argv[3] if len(sys.argv) > 3 else None
out = []
for jid, mod, row, op, occ, res in rows:
    if want and mod != want:
        continue
    d = Path(tempfile.mkdtemp(prefix="s1df_"))
    try:
        shutil.copy(S1 / mod, d / mod)
        subprocess.run([CR, "apply", mod, op, occ], cwd=d, capture_output=True, text=True)
        a = (S1 / mod).read_text(encoding="utf-8").splitlines()
        b = (d / mod).read_text(encoding="utf-8").splitlines()
        ch = [ln[1:].strip() for ln in difflib.unified_diff(a, b, n=0, lineterm="") if ln[:1] == "+" and ln[:3] != "+++"]
        out.append("\t".join([jid, mod, row, op.replace("core/", ""), occ, res[:60], " | ".join(ch)[:220]]))
    finally:
        shutil.rmtree(d, ignore_errors=True)
Path(sys.argv[2]).write_text("\n".join(out) + "\n", encoding="utf-8")
print(len(out))
