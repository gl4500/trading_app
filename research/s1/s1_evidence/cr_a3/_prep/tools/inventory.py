"""T15c-prep P1: ``cosmic-ray init`` (15a launcher, scratch copy) for one module/shard config, the R8 range filter,
operator counts and the proposed batch plan. NO exec, NO baseline on a mutated tree, no mutant is run.

usage: inventory.py <module> [<shard>]"""
import collections
import os
import math
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from t15c_common import WORK, WT, cfg_for, cr_coord, dump, load, sha  # noqa: E402
from baseline import SEL, copy_paths_for, key_paths  # noqa: E402
from cr_guard import BUDGETS  # noqa: E402


def by_op(items):
    return dict(sorted(collections.Counter(i["operator"] for i in items).items()))


def family(op):
    name = op.split("/", 1)[-1]
    for pre in ("ReplaceComparisonOperator", "ReplaceBinaryOperator", "ReplaceUnaryOperator", "ReplaceAndWithOr",
                "ReplaceOrWithAnd", "NumberReplacer", "AddNot", "ZeroIterationForLoop", "ExceptionReplacer",
                "RemoveDecorator", "ReplaceBreakWithContinue", "ReplaceContinueWithBreak", "ReplaceTrueWithFalse",
                "ReplaceFalseWithTrue", "VariableReplacer", "VariableInserter", "NoOp"):
        if name.startswith(pre):
            return pre
    return name


def main(module, shard=None):
    spec = SEL[module][shard or "_"]
    rel_dir, evid = key_paths(module, shard)
    tag = module + (f"__{shard}" if shard else "")
    cfg = cfg_for(module, spec["args"], f"{rel_dir}/control.json")
    work = WORK / os.environ.get("T15C_INV_DIR", "inv") / tag
    items = cr_coord.inventory(WT, copy_paths_for(rel_dir, spec), cfg, work)
    for n in ("inventory.json", "inventory.json.sha256"):
        if (evid / n).exists():
            raise SystemExit(f"{evid / n} exists: an inventory is immutable")
        shutil.copy2(work / n, evid / n)
    inv_sha = sha(evid / "inventory.json")
    if spec.get("ranges"):
        rpath = WT / spec["ranges"]
        ranges = load(rpath)
        if ranges["sha256"] != load(evid / "inventory.json")["source_sha256"]:
            raise SystemExit("ranges.json source sha256 != inventory source sha256")
        kept, excluded = cr_coord.filter_by_scope(items, ranges)
        for e in excluded:
            r0, r1 = cr_coord._span(e)
            e["reason"] = f"mutation lines {r0}-{r1} overlap no in-scope range of {spec['ranges']}"
        rinfo = {"ranges": spec["ranges"], "ranges_file_sha256": sha(rpath), "ranges_source_sha256": ranges["sha256"],
                 "rule": ranges["rule"]}
    else:
        kept, excluded, rinfo = items, [], {"ranges": None, "rule": "whole module: no range filter (R1)"}
    ids = [i["job_id"] for i in cr_coord.order_items(kept)]
    batches = cr_coord.plan_batches(ids)
    doc = {"module": module, "shard": shard, "inventory_sha256": inv_sha, **rinfo,
           "pre_filter_count": len(items), "post_filter_count": len(kept), "excluded_count": len(excluded),
           "pre_by_operator": by_op(items), "post_by_operator": by_op(kept),
           "post_by_family": dict(sorted(collections.Counter(family(i["operator"]) for i in kept).items())),
           "kept": kept, "excluded": excluded}
    dump(evid / "inventory_filtered.json", doc)
    plan = {"module": module, "shard": shard, "inventory_sha256": inv_sha, "candidates": len(ids),
            "batch_max": BUDGETS["batch_max"], "sessions": math.ceil(len(ids) / BUDGETS["batch_max"]),
            "ordering": "cr_coord.order_items (location, operator, occurrence, job id); no priority overrides",
            "batches": batches, "status": "PROPOSAL - no manifest written, nothing executed"}
    dump(evid / "batch_plan.json", plan)
    print(f"{tag}: pre {len(items)} post {len(kept)} excluded {len(excluded)} sessions {plan['sessions']}")


if __name__ == "__main__":
    main(*sys.argv[1:])
