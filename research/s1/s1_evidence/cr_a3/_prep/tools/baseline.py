"""T15c-prep P2: collect-only control + 3 serial unmutated guard baselines of one selector (module or shard).

usage: baseline.py <module> [<shard>]     (selector spec from selectors.json beside this file)

1. A fresh copy; contained ``pytest --collect-only`` with the 15a guard's own recorder plugin (-p cr_guard,
   CR_GUARD_NODES_OUT) -> control.json {"nodes": sorted(selected)} in the evidence dir (refuses on any collect error).
2. Three times, serially: a fresh copy built with cr_coord.make_copy (source + the evidence control/argfile), the
   coordinator's env (cr_coord._env with a job dir) and the EXACT cr.toml test-command (cr_coord.test_command:
   --deadline 240 --target <module> --control <rel> -p conftest <selector>), run under cr_guard.run_contained with
   the CR timeout (300 s) as the outer deadline - i.e. what Cosmic Ray would run, minus the mutation.
   Expected guard status: "survived" (clean all-pass, node set == control).
3. baseline/timings.json: per run guard pytest elapsed + outer wall; median/max; budget verdict."""
import json
import os
import shlex
import shutil
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t15c_common import (PY, PYTEST_EXTRA, WORK, WT, cfg_for, cr_coord, cr_guard, dump, load, sha,  # noqa: E402
                         source_copy_paths)
from cr_guard import BUDGETS  # noqa: E402

SEL = load(Path(__file__).resolve().parent / "selectors.json")


def key_paths(module, shard):
    rel = f"research/s1/s1_evidence/cr_a3/{module}" + (f"/{shard}" if shard else "")
    return rel, WT / rel


def copy_paths_for(rel_dir, spec):
    extra = [f"{rel_dir}/control.json"] + [a[1:] for a in spec["args"] if a.startswith("@")]
    return source_copy_paths() + extra


def collect(module, shard, spec, scratch, evid, rel_dir):
    copy = scratch / "collect_copy"
    cr_coord.make_copy(WT, source_copy_paths() + [a[1:] for a in spec["args"] if a.startswith("@")], copy)
    env = cr_coord._env(copy, cfg_for(module, spec["args"], "unused"))
    rec = scratch / "collect_nodes.json"
    env.update({cr_guard.NODES_ENV: str(rec), cr_guard.ATTEMPT_ENV: "collect-only",
                "S1_HYPOTHESIS_ROOT": str(scratch / "collect_hyp")})
    cmd = [str(PY), "-m", "pytest", "-p", "cr_guard", "-p", "no:cacheprovider", *PYTEST_EXTRA, "--collect-only", "-q",
           *spec["args"]]
    run = cr_guard.run_contained(cmd, cwd=copy, env=env, stdout_path=scratch / "collect_stdout.txt",
                                 stderr_path=scratch / "collect_stderr.txt", deadline_s=600)
    r = load(rec)
    if run["rc"] != 0 or r["collect_errors"] or not r["selected"] or not run["cleanup"]["verified"]:
        raise SystemExit(f"collect-only failed: rc={run['rc']} errors={r['collect_errors'][:1]}")
    nodes = sorted(r["selected"])
    if len(set(nodes)) != len(nodes):
        raise SystemExit("duplicate node ids in collect-only")
    evid.mkdir(parents=True, exist_ok=True)
    (evid / "control.json").write_text(json.dumps({"nodes": nodes}), encoding="utf-8")
    dump(evid / "collect_only.json", {"cmd": cmd, "cwd": "<fresh copy root>", "rc": run["rc"], "count": len(nodes),
                                      "control_sha256": sha(evid / "control.json"),
                                      "cleanup_verified": run["cleanup"]["verified"]})
    shutil.rmtree(copy)
    return nodes


def main(module, shard=None):
    spec = SEL[module][shard or "_"]
    rel_dir, evid = key_paths(module, shard)
    tag = module + (f"__{shard}" if shard else "")
    scratch = WORK / "baseline" / tag
    if scratch.exists():
        raise SystemExit(f"{scratch} exists (baselines are never reused)")
    scratch.mkdir(parents=True)
    nodes = collect(module, shard, spec, scratch, evid, rel_dir)
    cfg = cfg_for(module, spec["args"], f"{rel_dir}/control.json")
    cr_coord.write_cr_toml(evid / "cr.toml", cfg)
    cmd = shlex.split(cr_coord.test_command(cfg))
    runs = []
    for k in (1, 2, 3):
        copy, job = scratch / f"copy{k}", scratch / f"run{k}" / "job"
        copied = cr_coord.make_copy(WT, copy_paths_for(rel_dir, spec), copy)
        env = cr_coord._env(copy, cfg, job, f"baseline-{tag}-{k}")
        job.mkdir(parents=True)
        t0 = time.time()
        run = cr_guard.run_contained(cmd, cwd=copy, env=env, stdout_path=scratch / f"run{k}" / "guard_stdout.txt",
                                     stderr_path=scratch / f"run{k}" / "guard_stderr.txt",
                                     deadline_s=BUDGETS["cr_timeout_s"])
        wall = round(time.time() - t0, 3)
        g = load(job / "guard.json") if (job / "guard.json").is_file() else {}
        restored = sha(copy / f"research/s1/{module}.py") == copied[f"research/s1/{module}.py"]
        row = {"run": k, "status": g.get("status"), "guard_exit": g.get("exit_code"), "outer_rc": run["rc"],
               "outer_timed_out": run["timed_out"], "outer_cleanup_verified": run["cleanup"]["verified"],
               "pytest_elapsed_s": g.get("elapsed_s"), "outer_wall_s": wall, "counts": g.get("counts"),
               "node_count": len(g.get("nodes") or []), "source_unchanged": restored,
               "guard_cleanup_verified": (g.get("cleanup") or {}).get("verified")}
        runs.append(row)
        out = evid / "baseline" / f"run{k}"
        out.mkdir(parents=True, exist_ok=True)
        if g:
            shutil.copy2(job / "guard.json", out / "guard.json")
            att = Path(g["attempt_dir"])
            for n in ("junit.xml", "nodes.json", "stdout.txt", "stderr.txt", "cleanup.json"):
                if (att / n).is_file():
                    shutil.copy2(att / n, out / n)
        dump(out / "timing.json", row)
        print(tag, row, flush=True)
        shutil.rmtree(copy)
    el = [r["pytest_elapsed_s"] for r in runs if r["pytest_elapsed_s"] is not None]
    walls = [r["outer_wall_s"] for r in runs]
    ok = all(r["status"] == "survived" for r in runs)
    doc = {"module": module, "shard": shard, "selector_args": spec["args"], "node_count": len(nodes),
           "test_command": cr_coord.test_command(cfg), "runs": runs, "all_survived": ok,
           "pytest_elapsed_median_s": statistics.median(el) if el else None, "pytest_elapsed_max_s": max(el) if el else None,
           "outer_wall_median_s": statistics.median(walls), "outer_wall_max_s": max(walls),
           "targets": {"median_le_s": BUDGETS["selector_baseline_target_s"], "max_le_s": BUDGETS["guard_inner_deadline_s"]}}
    doc["within_budget"] = bool(ok and doc["outer_wall_median_s"] <= BUDGETS["selector_baseline_target_s"]
                                and doc["outer_wall_max_s"] <= BUDGETS["guard_inner_deadline_s"])
    dump(evid / "baseline" / "timings.json", doc)
    print(tag, "median", doc["outer_wall_median_s"], "max", doc["outer_wall_max_s"], "ok", ok, "budget",
          doc["within_budget"], flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
