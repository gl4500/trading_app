"""S1 Task 12 (A10.2): fresh SOURCE-BOUND targeted semantic mutants for every function changed in Task 11/12 and for
_out, _seals, _sha_or_absent, _ack, _write_once and report serialisation (private-key leakage).

Each mutant = exact edits (each `old` text must occur exactly once in the CURRENT source: the run refuses
otherwise), its function, the intended killing test(s) and the intended assertion. Every mutant runs in an
isolated copy of the bundle (BUNDLE_CODE + the three pinned documents) and s1_tests; the real sources are never
modified. Only the intended tests run (focused), with -rf so the failing test id and assertion are retained.

Classification (A10.2, Codex 89e72ebc point 8):
- KILLED: pytest exit 1 and an INTENDED test failed on an assertion/refusal that is not a bundle refusal;
- KILLED-UNINTENDED: exit 1, but only non-intended tests failed (reported, not counted as intended evidence);
- BUNDLE-REFUSAL: a failure message is an S1 bundle refusal ("S1 bundle ... differs") - NOT a kill;
- HARNESS: collection/import/usage/internal errors (exit 2-5, "ERROR collecting", ImportError/SyntaxError) - NOT a
  kill;
- SURVIVED: exit 0.
The bundle check in the copy is RE-PINNED, not disabled: the tests build every registration (AUDIT-ACK, RUN-ACK,
SCORE-ACK tokens) at test time from the files of the copy, so a mutated copy is self-consistent and a kill comes
from behaviour; any output that is a bundle refusal is classified BUNDLE-REFUSAL and excluded.
Usage: python s1_evidence/s1_mutants_t12.py [WORKERS] [NAME_FILTER]"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = Path("C:/Users/gl450/.coordination/trading_app/testenv/Scripts/python.exe")
sys.path.insert(0, str(ROOT))
import s1_common  # noqa: E402

BUNDLE = list(s1_common.BUNDLE_CODE)
DOCS = list(s1_common.DOC_PINS)
ORIG = {f: (ROOT / f).read_text(encoding="utf-8") for f in BUNDLE}
SHA = {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in BUNDLE}

from s1_mutants_t12_list import MUTANTS  # noqa: E402  (the list, kept beside this harness)
import s1_mutants_t12_part2  # noqa: E402,F401  (appends to MUTANTS)
import s1_mutants_t12_part3  # noqa: E402,F401  (appends to MUTANTS)
import s1_mutants_t12_fix2  # noqa: E402,F401  (fix round 2: retargets, tightening, B1-B3 mutants)
import s1_mutants_t12_fix3  # noqa: E402,F401  (fix round 3: retargets, C-1/C-2/I-1/I-2/M-1..3 mutants)
import s1_mutants_t12_fix4  # noqa: E402,F401  (fix round 4: retargets, N-1/N-2/N-3/m-1 mutants)
import s1_mutants_t12_fix5  # noqa: E402,F401  (fix round 5: retargets, R-1/R-2/R-3 mutants)
import s1_mutants_t12_fix6  # noqa: E402,F401  (fix round 6: retargets, F-1 mutants)
import s1_mutants_t12_fix7  # noqa: E402,F401  (fix round 7: retargets, G-1 mutants)
import s1_mutants_t12_fix8  # noqa: E402,F401  (fix round 8: retargets, retired anchor mutants, H mutants)
import s1_mutants_t12_fix9  # noqa: E402,F401  (fix round 9: H-3 retargets, rule-3 inverse, H-3 mutants)
import s1_mutants_t12_fix10  # noqa: E402,F401  (fix round 10: the EARLIEST_CLOSE_NY calendar check)
import s1_mutants_t12_accept  # noqa: E402,F401  (declared intended exceptions, fix round 1)


def mutate(m) -> dict:
    out = {}
    for f, a, b in m["edits"]:
        cur = out.get(f, ORIG[f])
        n = cur.count(a)
        if n != 1:
            raise SystemExit(f"mutant {m['name']!r}: edit text occurs {n} times in {f} (must be exactly once): "
                             f"{a[:80]!r}")
        out[f] = cur.replace(a, b)
    return out


BUNDLE_REFUSAL = re.compile(r"S1 bundle \S+ differs")


ASSERTION = re.compile(r"^(AssertionError|assert |Failed: |DID NOT RAISE|.*Regex pattern did not match)")


def kind_of(msg: str) -> str:
    """The failure's kind from its retained message: an assertion of the test (assert / pytest.fail / pytest.raises
    mismatch) or the class of an exception that escaped (e.g. KeyError, SystemExit)."""
    msg = (msg or "").strip()
    if ASSERTION.match(msg) or msg.startswith("Failed"):
        return "assertion"
    head = msg.split(":", 1)[0].strip().split(" ")[0]
    return head.split(".")[-1] if head else "unknown"


def classify(rc: int, stdout: str, intended, accept=()) -> tuple:
    """Fix round 1 (m-2): every failing test id is kept with its failure message (COLUMNS widened so -rf keeps it);
    a kill counts as KILLED only when an intended test failed on an ASSERTION (or on an exception the mutant entry
    declares as the intended outcome, `accept`); an intended test failing on any other exception is
    KILLED-BY-EXCEPTION, reported and not counted."""
    failed = re.findall(r"^FAILED (\S+(?:\[[^\]]*\])?)(?: - (.*))?$", stdout, re.M)
    errors = re.findall(r"^ERROR (\S+)", stdout, re.M)
    if rc == 0:
        return "SURVIVED", []
    if rc != 1 or errors or "ERROR collecting" in stdout:
        return "HARNESS", failed
    if any(BUNDLE_REFUSAL.search(msg or "") for _, msg in failed) or BUNDLE_REFUSAL.search(stdout):
        return "BUNDLE-REFUSAL", failed
    hit = [f for f in failed if any(f[0].endswith(t) or t in f[0] for t in intended)]
    if not hit:
        return "KILLED-UNINTENDED", failed
    good = [f for f in hit if kind_of(f[1]) == "assertion" or kind_of(f[1]) in accept]
    return ("KILLED", good) if good else ("KILLED-BY-EXCEPTION", hit)


def one(m) -> dict:
    changed = mutate(m)
    d = Path(tempfile.mkdtemp(prefix="s1m12_"))
    try:
        (d / "docs").mkdir()
        for f in BUNDLE:
            shutil.copy2(ROOT / f, d / f)
        for f in DOCS:
            shutil.copy2(ROOT / f, d / f)
        for f, text in changed.items():
            (d / f).write_text(text, encoding="utf-8", newline="")
        shutil.copytree(ROOT / "s1_tests", d / "s1_tests", ignore=shutil.ignore_patterns("__pycache__"))
        nodes = [f"s1_tests/{t}" for t in m["tests"]]
        env = dict(os.environ, COLUMNS="2000")             # fix round 1 (m-2): keep the -rf failure messages
        r = subprocess.run([str(PY), "-m", "pytest", *nodes, "-q", "-p", "no:cacheprovider", "-rf", "--tb=line"],
                           cwd=d, capture_output=True, text=True, timeout=3600, env=env)
        tag, hit = classify(r.returncode, r.stdout, m["tests"], m.get("accept", ()))
        return {"m": m, "tag": tag, "hit": hit, "rc": r.returncode,
                "after": {f: hashlib.sha256(t.encode("utf-8")).hexdigest() for f, t in changed.items()},
                "tail": r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr.strip()[-200:]}
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main():
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    filt = sys.argv[2] if len(sys.argv) > 2 else ""
    items = [m for m in MUTANTS if filt in m["name"]]
    for m in items:                                     # every edit applies exactly once, before any run
        mutate(m)
    print("Task 12 targeted semantic mutants (A10.2). Sources (sha256, the source each mutant is bound to):")
    for f in BUNDLE:
        print(f"  {f} {SHA[f]}")
    print("Tests: " + ", ".join(f"{p.name} {hashlib.sha256(p.read_bytes()).hexdigest()[:16]}"
                                for p in sorted((ROOT / "s1_tests").glob("*.py"))))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(one, items))
    counts = {}
    for x in res:
        m = x["m"]
        counts[x["tag"]] = counts.get(x["tag"], 0) + 1
        print(f"\n[{x['tag']}] {m['name']}")
        print(f"  function: {m['file']}::{m['function']}   mutated sha256: "
              + ", ".join(f"{f} {h[:16]}" for f, h in x["after"].items()))
        print(f"  intended: {', '.join(m['tests'])}")
        print(f"  intended assertion: {m['intent']}")
        for key in ("retargeted", "tightened", "equivalent"):          # fix round 2
            if m.get(key):
                print(f"  {key}: {m[key]}")
        if m.get("accept"):
            print(f"  declared intended exception(s): {', '.join(m['accept'])} - {m['accept_why']}")
        for tid, msg in x["hit"]:
            print(f"  failing: {tid} :: [{kind_of(msg)}] {(msg or '').strip()[:300]}")
        print(f"  pytest rc={x['rc']}: {x['tail']}")
    print("\nSUMMARY " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) + f" (total {len(res)})")


if __name__ == "__main__":
    main()
