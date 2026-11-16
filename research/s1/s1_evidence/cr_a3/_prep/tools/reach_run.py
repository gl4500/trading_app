"""T15c-prep: coverage-free reach run of one selector (t15c_reach plugin) on a fresh unmutated copy, then
selector_coverage.json: every in-scope function -> the selected tests that reach it; uncovered functions listed.

usage: reach_run.py <module> <selector-key> <out-json> [<ranges.json>]
  selector-key: "_" (plan files) or a shard name in selectors.json, or "plan" (plan files, ignoring selectors.json)
  ranges.json : restrict the in-scope functions to those inside its scopes (rows 289/290); default whole module."""
import ast
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from t15c_common import (MODULES, PY, PYTEST_EXTRA, T, WORK, WT, cr_coord, cr_guard, dump, load,  # noqa: E402
                         source_copy_paths)


def in_scope_functions(module, ranges):
    src = WT / "research/s1" / f"{module}.py"
    scopes = cr_coord._scopes(ast.parse(src.read_bytes()))
    funcs = [(q, s, e) for q, k, s, e in scopes if k == "function"]
    if ranges is None:
        return [q for q, _, _ in funcs]
    rs = load(ranges)["scopes"]
    keep = []
    for q, s, e in funcs:
        if any(r["start"] <= s and e <= r["end"] for r in rs.values()):
            keep.append(q)
    return keep


def main(module, key, out, ranges=None):
    if key == "plan":
        args = [T + f for f in MODULES[module]]
    else:
        args = load(HERE / "selectors.json")[module][key]["args"]
    tag = f"{module}__{key}__{Path(out).stem}"
    scratch = WORK / "reach" / tag
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir(parents=True)
    copy = scratch / "copy"
    cr_coord.make_copy(WT, source_copy_paths() + [a[1:] for a in args if a.startswith("@")], copy)
    env = dict(os.environ)
    env.update(PYTHONDONTWRITEBYTECODE="1", S1_HYPOTHESIS_ROOT=str(scratch / "hyp"), T15C_REACH_MODULE=module,
               T15C_REACH_OUT=str(scratch / "reach.json"),
               PYTHONPATH=os.pathsep.join([str(copy / "research/s1"), str(copy / "research/s1/s1_tests"), str(HERE)]))
    for k in ("CR_GUARD_JOB_DIR", "CR_GUARD_JOB_ID", "CR_GUARD_NODES_OUT", "CR_GUARD_ATTEMPT", "CR_GUARD_TARGETS"):
        env.pop(k, None)
    cmd = [str(PY), "-m", "pytest", *PYTEST_EXTRA, "-p", "t15c_reach", "-p", "no:cacheprovider", "-q",
           f"--junitxml={scratch / 'junit.xml'}", f"--basetemp={scratch / 'bt'}", *args]
    run = cr_guard.run_contained(cmd, cwd=copy, env=env, stdout_path=scratch / "stdout.txt",
                                 stderr_path=scratch / "stderr.txt", deadline_s=3600)
    rec = load(scratch / "reach.json")
    mod_file = Path(rec["module_file"]).resolve()
    if copy.resolve() not in mod_file.parents:
        raise SystemExit(f"reach: module imported from outside the copy: {mod_file}")
    funcs = in_scope_functions(module, Path(ranges) if ranges else None)
    by_fn = {f: sorted(t for t, hits in rec["per_test"].items() if f in hits) for f in funcs}
    doc = {"module": module, "selector_key": key, "selector_args": args, "cmd": cmd, "rc": run["rc"],
           "cleanup_verified": run["cleanup"]["verified"], "elapsed_s": run["elapsed_s"],
           "ranges": str(ranges) if ranges else None, "tests": len(rec["per_test"]),
           "functions": {f: {"tests": len(v), "reached_by": v} for f, v in by_fn.items()},
           "uncovered": [f for f, v in by_fn.items() if not v],
           "per_test": rec["per_test"], "method": "sys.monitoring PY_START (tools/t15c_reach.py)",
           "limitations": rec["limitations"]}
    dump(out, doc)
    print(f"{tag}: rc {run['rc']} {run['elapsed_s']}s tests {doc['tests']} functions {len(funcs)} "
          f"uncovered {doc['uncovered']}")


if __name__ == "__main__":
    main(*sys.argv[1:])
