"""15c-H: totals after the rebuild - screening configs, completion shards, calibration + scenario sessions.

Writes WORK/budget_v2.json and per-module selector_coverage.json (screening shards). Reads evidence only."""
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from t15c_common import EVID, MODULES, WORK, cr_coord, dump, load, sha  # noqa: E402
from cr_guard import BUDGETS  # noqa: E402

SEL = load(HERE / "selectors.json")
IO_S = load(WORK / "measure_io.json")["max_s"]            # measured per-item coordinator I/O (max)
CR_OVERHEAD_S = 30.0                                       # ASSUMED, unmeasured (no exec run)
FENCE = cr_coord.fence_s()
L = BUDGETS["session_length_s"]


def mkey(i):
    return (i["operator"], i["occurrence"], tuple(i["start"]), tuple(i["end"]))


def main():
    out = {"io_max_s_measured": IO_S, "cr_overhead_s_assumed": CR_OVERHEAD_S, "fence_s": FENCE,
           "session_length_s": L, "calibration_items": BUDGETS["batch_max"], "modules": {}}
    for module in MODULES:
        md = {"screening": {}, "completion": {}}
        keys, cov = [], {"module": module, "shards": {}}
        for shard, spec in SEL[module].items():
            sub = "" if shard == "_" else shard
            d = EVID / module / sub
            tm = load(d / "baseline/timings.json")
            row = {"selector": tm["selector_args"], "nodes": tm["node_count"], "all_survived": tm["all_survived"],
                   "median_s": tm["outer_wall_median_s"], "max_s": tm["outer_wall_max_s"],
                   "pytest_median_s": tm["pytest_elapsed_median_s"], "pytest_max_s": tm["pytest_elapsed_max_s"],
                   "within_budget": tm["within_budget"],
                   "est_item_s": round(tm["outer_wall_max_s"] + IO_S + CR_OVERHEAD_S, 1)}
            if spec.get("completion"):
                md["completion"][shard] = row
                continue
            inv = load(d / "inventory_filtered.json")
            n = inv["post_filter_count"]
            cap = max(1, int((L - FENCE) // row["est_item_s"]))
            row.update(pre=inv["pre_filter_count"], post=n, post_by_family=inv["post_by_family"],
                       calibration_items=min(n, BUDGETS["batch_max"]),
                       scenario_derived_cap=cap,
                       scenario_sessions=1 + (math.ceil((n - BUDGETS["batch_max"]) / cap)
                                              if n > BUDGETS["batch_max"] else 0),
                       sessions_at_24=math.ceil(n / BUDGETS["batch_max"]),
                       est_exec_s=round(n * row["est_item_s"], 1))
            md["screening"][shard] = row
            keys += [mkey(i) for i in inv["kept"]]
            if (d / "selector_coverage_detail.json").is_file():
                c = load(d / "selector_coverage_detail.json")
                cov["shards"][shard] = {"uncovered": c["uncovered"],
                                        "functions": {f: v["tests"] for f, v in c["functions"].items()},
                                        "detail_sha256": sha(d / "selector_coverage_detail.json")}
        md["candidates"] = len(keys)
        md["duplicates_across_shards"] = len(keys) - len(set(keys))
        if (EVID / module / "ranges.json").is_file():
            first = next(s for s in SEL[module] if not SEL[module][s].get("completion"))
            items = load(EVID / module / first / "inventory.json")["items"]
            kept, _ = cr_coord.filter_by_scope(items, load(EVID / module / "ranges.json"))
            md["row_scope_candidates"] = len(kept)
            md["partition_equal_row_scope"] = {mkey(i) for i in kept} == set(keys) and \
                md["duplicates_across_shards"] == 0
        if md["completion"]:
            md["completion_per_survivor_baseline_maxima_scenario_s"] = round(sum(r["est_item_s"] for r in md["completion"].values()), 1)
            pool = load(EVID / module / "completion" / "pool.json")
            shards = [(EVID / module / "completion" / s.split("/")[1] / "nodes.txt").read_text(
                encoding="utf-8").splitlines() for s in md["completion"]]
            cr_coord.check_pool_union(pool["nodes"], shards)       # raises on any gap
            md["completion_pool"] = {"count": pool["count"], "nodes_sha256": pool["nodes_sha256"],
                                     "union_equals_pool": True}
        md["calibration_sessions"] = len(md["screening"])
        md["scenario_sessions"] = sum(r["scenario_sessions"] for r in md["screening"].values())
        md["sessions_at_24"] = sum(r["sessions_at_24"] for r in md["screening"].values())
        md["est_exec_s"] = round(sum(r["est_exec_s"] for r in md["screening"].values()), 1)
        out["modules"][module] = md
        dump(EVID / module / "selector_coverage.json", cov)
    ms = out["modules"].values()
    out["total_candidates"] = sum(m["candidates"] for m in ms)
    out["calibration_sessions"] = sum(m["calibration_sessions"] for m in ms)
    out["scenario_sessions"] = sum(m["scenario_sessions"] for m in ms)
    out["sessions_at_24"] = sum(m["sessions_at_24"] for m in ms)
    out["est_screening_exec_h"] = round(sum(m["est_exec_s"] for m in ms) / 3600, 2)
    out["over_budget"] = [f"{m}/{s}" for m, md in out["modules"].items()
                          for part in ("screening", "completion") for s, r in md[part].items() if not r["within_budget"]]
    dump(WORK / "budget_v2.json", out)
    print(json.dumps({k: v for k, v in out.items() if k != "modules"}, indent=1))
    for m, md in out["modules"].items():
        print(m, {k: v for k, v in md.items() if k not in ("screening", "completion")})
        for part in ("screening", "completion"):
            for s, r in md[part].items():
                print("   ", part, s, {k: r.get(k) for k in ("nodes", "median_s", "max_s", "within_budget", "post",
                                                            "scenario_derived_cap", "scenario_sessions", "est_item_s")})


if __name__ == "__main__":
    main()
