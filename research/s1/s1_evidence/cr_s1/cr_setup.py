"""S1 Task 9 focused Cosmic Ray: build one self-contained session per module in a fresh temp work dir (copies of the
S1 sources + pinned e1 core + s1_tests; the real files are never mutated), init it, record the job count, the
focused test set and its hashes. Usage: python cr_setup.py WORK_DIR TIMEOUT_S
Round 2 (controller ruling): the focused test set per module = that module's own test files ONLY (the connected
test is dropped from the per-mutant set); every survivor is re-checked against the FULL suite (cr_recheck_s1.py)."""
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

S1 = Path(__file__).resolve().parents[2]
EV = Path(__file__).resolve().parent
PY = "C:/Users/gl450/.coordination/trading_app/testenv/Scripts/python.exe"
CR = "C:/Users/gl450/.coordination/trading_app/testenv/Scripts/cosmic-ray.exe"
TESTS = {
    "s1_books.py": ["test_s1_books.py"],
    "s1_seal.py": ["test_s1_seal.py", "test_s1_bridge_8b.py"],
    "s1_checkpoint.py": ["test_s1_checkpoint.py", "test_s1_checkpoint_7b.py", "test_s1_bridge_8b.py"],
    "s1_run.py": ["test_s1_run.py", "test_s1_bridge_8b.py"],
}
SOURCES = sorted(p.name for p in S1.glob("s1_*.py")) + ["e1_sim.py", "e1_fetch.py"]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main(work: Path, timeout: float) -> None:
    work.mkdir(parents=True, exist_ok=True)
    summary = {"sources": {f: sha(S1 / f) for f in SOURCES},
               "tests": {p.name: sha(p) for p in sorted((S1 / "s1_tests").glob("*.py"))}, "modules": {}}
    for mod, tests in TESTS.items():
        d = work / mod[:-3]
        if d.exists():
            shutil.rmtree(d)
        d.mkdir()
        for f in SOURCES:
            shutil.copy(S1 / f, d / f)
        shutil.copytree(S1 / "s1_tests", d / "s1_tests", ignore=shutil.ignore_patterns("__pycache__"))
        cmd = f"{PY} -m pytest " + " ".join(f"s1_tests/{t}" for t in tests) + " -x -q -p no:cacheprovider"
        (d / "cr.toml").write_text(
            f'[cosmic-ray]\nmodule-path = "{mod}"\ntimeout = {timeout}\nexcluded-modules = []\n'
            f'test-command = "{cmd}"\n\n[cosmic-ray.distributor]\nname = "local"\n', encoding="utf-8")
        subprocess.run([CR, "init", "cr.toml", "cr.sqlite"], cwd=d, check=True)
        n = sqlite3.connect(d / "cr.sqlite").execute("SELECT count(*) FROM work_items").fetchone()[0]
        summary["modules"][mod] = {"jobs": n, "test_set": tests, "test_command": cmd}
        print(mod, n, flush=True)
    (EV / "cr_setup.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]), float(sys.argv[2]))
