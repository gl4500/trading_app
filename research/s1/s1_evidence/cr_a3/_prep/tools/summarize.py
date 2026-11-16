"""T15c-prep: cross-shard partition check, per-module selector_coverage.json, totals (budget.json). Prints a summary.

Run after baselines, inventories and shard reach runs. Reads only evidence + scratch reach records."""
import json
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from t15c_common import EVID, MODULES, WORK, WT, cr_coord, dump, load, sha, source_copy_paths  # noqa: E402
from cr_guard import BUDGETS  # noqa: E402

SEL = load(HERE / "selectors.json")
CR_ITEM_RESERVE_S = 30.0      # assumed per-item CR launch + exec + reconcile overhead (NOT measured: no exec run)


def mkey(i):
    return (i["operator"], i["occurrence"], tuple(i["start"]), tuple(i["end"]))


def copy_time():
    dest = WORK / "copytime"
    if dest.exists():
        import shutil
        shutil.rmtree(dest)
    t0 = time.time()
    cr_coord.make_copy(WT, source_copy_paths(), dest)
    return round(time.time() - t0, 2)


def main():
    ct = copy_time()
    rows, out = [], {"copy_creation_s": ct, "cr_item_reserve_s_assumed": CR_ITEM_RESERVE_S, "modules": {}}
    for module in MODULES:
        shards = SEL[module]
        mdoc = {"shards": {}}
        cov = {"module": module, "shards": {}}
        keys_all = []
        for shard in shards:
            sub = None if shard == "_" else shard
            d = EVID / module / (sub or "")
            tm, inv, plan = load(d / "baseline/timings.json"), load(d / "inventory_filtered.json"), load(d / "batch_plan.json")
            rr = WORK / "reach" / f"{module}__{shard}__shardcov"
            rec = load(rr / "reach.json") if (rr / "reach.json").is_file() else None
            per_item = tm["outer_wall_max_s"] + ct + CR_ITEM_RESERVE_S
            n = inv["post_filter_count"]
            sessions = math.ceil(n / BUDGETS["batch_max"])
            row = {"selector": tm["selector_args"], "nodes": tm["node_count"], "all_survived": tm["all_survived"],
                   "median_s": tm["outer_wall_median_s"], "max_s": tm["outer_wall_max_s"],
                   "pytest_median_s": tm["pytest_elapsed_median_s"], "pytest_max_s": tm["pytest_elapsed_max_s"],
                   "within_budget": tm["within_budget"], "pre": inv["pre_filter_count"], "post": n,
                   "post_by_family": inv["post_by_family"], "sessions": sessions,
                   "est_item_s": round(per_item, 1), "est_session_s": round(min(n, 24) * per_item, 1),
                   "est_total_exec_s": round(n * per_item, 1),
                   "worst_session_s": BUDGETS["batch_max"] * (BUDGETS["cr_timeout_s"] + BUDGETS["cleanup_reserve_s"])}
            keys_all += [mkey(i) for i in inv["kept"]]
            mdoc["shards"][shard] = row
            covdoc = load(d / "selector_coverage_detail.json") if (d / "selector_coverage_detail.json").is_file() else None
            if covdoc:
                cov["shards"][shard] = {"uncovered": covdoc["uncovered"],
                                        "functions": {f: v["tests"] for f, v in covdoc["functions"].items()},
                                        "detail": str((d / "selector_coverage_detail.json").relative_to(WT)),
                                        "detail_sha256": sha(d / "selector_coverage_detail.json")}
        dup = len(keys_all) - len(set(keys_all))
        mdoc["candidates"] = len(keys_all)
        mdoc["duplicate_mutations_across_shards"] = dup
        if (EVID / module / "ranges.json").is_file():          # cross-shard partition == row-level filter
            any_shard = next(iter(s for s in shards if s != "_"))
            items = load(EVID / module / any_shard / "inventory.json")["items"]
            kept, _ = cr_coord.filter_by_scope(items, load(EVID / module / "ranges.json"))
            row_keys = {mkey(i) for i in kept}
            mdoc["row_scope_candidates"] = len(row_keys)
            mdoc["partition_equal_row_scope"] = row_keys == set(keys_all) and dup == 0
        mdoc["sessions"] = sum(r["sessions"] for r in mdoc["shards"].values())
        out["modules"][module] = mdoc
        dump(EVID / module / "selector_coverage.json", cov)
    out["total_candidates"] = sum(m["candidates"] for m in out["modules"].values())
    out["total_sessions"] = sum(m["sessions"] for m in out["modules"].values())
    out["over_budget"] = [f"{m}/{s}" for m, md in out["modules"].items() for s, r in md["shards"].items()
                          if not r["within_budget"]]
    dump(WORK / "budget.json", out)
    print(json.dumps({k: v for k, v in out.items() if k != "modules"}, indent=1))
    for m, md in out["modules"].items():
        print(m, {k: v for k, v in md.items() if k != "shards"})
        for s, r in md["shards"].items():
            print("   ", s, {k: r[k] for k in ("nodes", "median_s", "max_s", "within_budget", "pre", "post", "sessions",
                                               "est_item_s")})


if __name__ == "__main__":
    main()
