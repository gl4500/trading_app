"""15c-H: verify Codex's omitted-node counts on the CURRENT screening shards and report the frozen full pool.

pool        = every node of the module's PLAN selector (the reach plan run's per_test keys == its collect set)
screen      = union of the current screening shards' control.json node sets
reaching    = plan nodes reaching >= 1 in-scope function (reach plan record, restricted to the shards' scopes)
omitted     = reaching - screen   (Codex's "omitted from every shard")
unreaching  = pool - reaching     (in the pool too: parent-unobserved / import / child-relevant)
usage: pool_check.py <out.json> [<module> ...]"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from t15c_common import EVID, WORK, dump, load  # noqa: E402

PLAN = {"s1_seal": "seal_plan.json", "s1_collect": "collect_plan_v2.json", "s1_slot": "slot_plan.json"}


def check(module):
    rec = load(WORK / "reach" / PLAN[module])
    pool = sorted(rec["per_test"])
    shards = [d for d in sorted((EVID / module).iterdir()) if d.is_dir() and (d / "control.json").is_file()
              and (d / "selection.json").is_file()]
    screen = sorted(set().union(*(set(load(d / "control.json")["nodes"]) for d in shards)))
    scopes = set()
    for d in shards:
        scopes |= {s.split("@")[0] for s in load(d / "ranges.json")["scopes"]}
    reaching = sorted(n for n, hits in rec["per_test"].items()
                      if any(h.split(".")[0] in scopes for h in hits))
    omitted = sorted(set(reaching) - set(screen))
    return {"module": module, "shards": [d.name for d in shards], "pool": len(pool), "screen_union": len(screen),
            "reaching": len(reaching), "omitted_everywhere": len(omitted),
            "pool_minus_screen": len(set(pool) - set(screen)),
            "pool_minus_screen_breakdown": {"reaching": len(omitted), "unreaching": len(set(pool) - set(screen) - set(reaching))},
            "unreaching_in_pool": len(set(pool) - set(reaching)), "screen_outside_pool": sorted(set(screen) - set(pool)),
            "omitted_nodes": omitted, "unreaching_nodes": sorted(set(pool) - set(reaching))}


out = {m: check(m) for m in (sys.argv[2:] or list(PLAN))}
dump(sys.argv[1], out)
for m, r in out.items():
    print(m, {k: v for k, v in r.items() if not k.endswith("_nodes")})
