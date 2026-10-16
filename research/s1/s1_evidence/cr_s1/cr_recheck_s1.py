"""S1 Task 9 round 2 (cr_recheck.py pattern): re-check every Cosmic Ray survivor of the focused per-module runs against
the FULL s1_tests suite. Each mutant is re-applied (`cosmic-ray apply`, same module/operator/occurrence) to a fresh
isolated copy of the SUBMITTED sources (asserted = the hashes recorded in cr_setup.json at session init); the FULL
test directory is copied in (per-file hashes in the output header, asserted unchanged at the end); pytest runs -x.
Which full-suite files run (sound reductions, all recorded per row in the output):
- the module's focused files that are byte-identical to the ones the CR session ran are skipped: they already PASSED
  on this exact mutant;
- for a mutated line inside a function body, only the tests (node ids) that EXECUTE that line on the unmutated code
  run (cr_linemap.json, made by cr_linemap_plugin.py over the same sources + tests): a test that never reaches the
  line behaves identically under the mutant. If no other test executes it, the result is "SURVIVED (not executed by
  any other test)" without a run. Import-time lines (module level, def/decorator/default lines) run every file.
KILLED here = "KILLED-by-full-suite". With env CR_TESTS="node ..." exactly those tests run instead (re-run of the
survivors against NEW retrospective tests: KILLED-by-new-test); with env CR_ONLY=<previous recheck TSV> only the
rows that SURVIVED there are re-checked. Fix round 1: CR_TIMEOUTS=1 selects the jobs cosmic-ray scored KILLED by
its timeout (output 'timeout'); CR_FOCUSED=1 re-runs the module's focused set; CR_TIMEOUT sets the per-mutant timeout.
Usage: python cr_recheck_s1.py WORK_DIR OUT.tsv WORKERS [FILTER]
  WORK_DIR: the directory holding the executed shard sessions (<module>_sN/cr.sqlite).
  FILTER: substring of "module:row:operator" (optional)."""
import ast
import glob
import os
import hashlib
import json
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

S1 = Path(__file__).resolve().parents[2]
EV = Path(__file__).resolve().parent
PY = "C:/Users/gl450/.coordination/trading_app/testenv/Scripts/python.exe"
CR = "C:/Users/gl450/.coordination/trading_app/testenv/Scripts/cosmic-ray.exe"
SETUP = json.loads((EV / "cr_setup.json").read_text(encoding="utf-8"))
SUBMITTED = SETUP["sources"]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


for f, h in SUBMITTED.items():
    assert sha(S1 / f) == h, f"{f} is not the submitted source"
TESTS = sorted((S1 / "s1_tests").glob("*.py"))
TEST_HASHES = {t.name: sha(t) for t in TESTS}
LINEMAP_P = EV / "cr_linemap.json"
LINEMAP = json.loads(LINEMAP_P.read_text(encoding="utf-8"))
CR_TESTS = shlex.split(os.environ.get("CR_TESTS", ""))      # fix round 1: shell-style quoting
CR_TIMEOUTS = os.environ.get("CR_TIMEOUTS") == "1"     # fix round 1 (review I-1): pick the jobs cosmic-ray scored
CR_FOCUSED = os.environ.get("CR_FOCUSED") == "1"       # KILLED only by its timeout, and re-run the module's focused
RUN_TIMEOUT = float(os.environ.get("CR_TIMEOUT", "1500"))  # set with a measured, recorded per-mutant timeout


def _body_lines(mod: str) -> set:
    """Lines inside some function body (executed only when that function runs)."""
    tree = ast.parse((S1 / mod).read_text(encoding="utf-8"))
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out |= set(range(n.body[0].lineno, n.end_lineno + 1))
    return out


BODY = {m: _body_lines(m) for m in ("s1_books.py", "s1_seal.py", "s1_checkpoint.py", "s1_run.py")}


def selection(mod: str, row: int):
    """(pytest args, note) or (None, note) when no other test file executes the line."""
    if CR_TESTS:
        return CR_TESTS, "CR_TESTS"
    if CR_FOCUSED:
        return [f"s1_tests/{t}" for t in SETUP["modules"][mod]["test_set"]], f"focused set, timeout {RUN_TIMEOUT:.0f} s"
    skip = {t for t in SETUP["modules"][mod]["test_set"] if TEST_HASHES.get(t) == SETUP["tests"].get(t)}
    if row in BODY[mod]:
        nodes = [n for n in LINEMAP.get(mod, {}).get(str(row), []) if n.split("::")[0].split("/")[-1] not in skip]
        if not nodes:
            return None, "not executed by any other test"
        return nodes, f"{len(nodes)} other tests executing the line"
    return ["s1_tests", *[f"--ignore=s1_tests/{t}" for t in sorted(skip)]], "import-time line: full suite minus focused"


def survivors(work: Path, filt: str) -> list:
    jobs = []
    for d in sorted(glob.glob(str(work / "s1_*_s[0-9]"))):
        con = sqlite3.connect(Path(d) / "cr.sqlite")
        jobs += con.execute("""SELECT s.job_id, s.module_path, s.operator_name, s.occurrence, s.start_pos_row
                               FROM work_results r JOIN mutation_specs s ON s.job_id = r.job_id
                               WHERE """ + ("r.output = 'timeout'" if CR_TIMEOUTS else "r.test_outcome = 'SURVIVED'")
                            ).fetchall()
        con.close()
    only = os.environ.get("CR_ONLY")             # a previous recheck TSV: re-check only its SURVIVED rows
    if only:
        keep = {ln.split("	")[0] for ln in Path(only).read_text(encoding="utf-8").splitlines()
                if ln and ln[0] != "#" and ln.split("	")[5].startswith("SURVIVED")}
        jobs = [j for j in jobs if j[0] in keep]
    return [j for j in jobs if filt in f"{j[1]}:{j[4]}:{j[2]}"]


def one(job):
    jid, mod, op, occ, row = job
    d = Path(tempfile.mkdtemp(prefix="s1rc_"))
    try:
        for f in SUBMITTED:
            shutil.copy(S1 / f, d / f)
        (d / "s1_tests").mkdir()
        for t in TESTS:
            shutil.copy(t, d / "s1_tests" / t.name)
        a = subprocess.run([CR, "apply", mod, op, str(occ)], cwd=d, capture_output=True, text=True)
        if a.returncode != 0:
            return (jid, mod, row, op, occ, "APPLY-FAILED")
        if all(sha(d / f) == h for f, h in SUBMITTED.items()):
            return (jid, mod, row, op, occ, "NO-CHANGE")
        args, note = selection(mod, row)
        if args is None:
            return (jid, mod, row, op, occ, f"SURVIVED ({note})")
        r = subprocess.run([PY, "-m", "pytest", *args, "-x", "-q", "-p", "no:cacheprovider"], cwd=d,
                           capture_output=True, text=True, timeout=RUN_TIMEOUT)
        first = next((l.split(" ")[1] for l in r.stdout.splitlines() if l.startswith("FAILED")), "")
        res = (("KILLED " + first) if r.returncode == 1 else "SURVIVED" if r.returncode == 0
               else f"ERROR rc={r.returncode}") + f" [{note}]"
        return (jid, mod, row, op, occ, res)
    except subprocess.TimeoutExpired:
        return (jid, mod, row, op, occ, f"KILLED timeout ({RUN_TIMEOUT:.0f} s)")
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    work, out_path, workers = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
    jobs = survivors(work, sys.argv[4] if len(sys.argv) > 4 else "")
    head = ["# sources " + " ".join(f"{f}={h}" for f, h in SUBMITTED.items()),
            "# tests " + " ".join(f"{n}={h}" for n, h in TEST_HASHES.items())
            + f" linemap={sha(LINEMAP_P)} CR_TESTS={' '.join(CR_TESTS) or '-'}",
            "# job_id\tmodule\trow\toperator\toccurrence\tresult"]
    # Results are appended as they finish; a re-run resumes, but only under the SAME source + test hashes.
    if out_path.exists():
        old = out_path.read_text(encoding="utf-8").splitlines()
        assert old[:2] == head[:2], "existing output was produced under other sources/tests: use a new file"
        done = {ln.split("\t")[0] for ln in old if ln and not ln.startswith("#")}
    else:
        out_path.write_text("\n".join(head) + "\n", encoding="utf-8")
        done = set()
    lock = threading.Lock()

    def run_and_record(job):
        r = one(job)
        with lock, out_path.open("a", encoding="utf-8") as f:
            f.write("\t".join(map(str, r)) + "\n")
        return r

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(run_and_record, [j for j in jobs if j[0] not in done]))
    assert {t.name: sha(t) for t in TESTS} == TEST_HASHES, "tests changed during the recheck"
    res = [ln.split("\t") for ln in out_path.read_text(encoding="utf-8").splitlines() if ln and ln[0] != "#"]
    print(f"{sum(r[5].startswith('KILLED') for r in res)} killed / {sum(r[5].startswith('SURVIVED') for r in res)} survived "
          f"/ {len(res)} rechecked")
