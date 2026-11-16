"""15c-H ruling 1: frozen full intended node pool + bounded COMPLETION shards whose union is exactly that pool.

usage: make_completion.py <module> <cap_s> <reach plan json> <explore junit.xml>

pool = every node of the module's PLAN selector (the plan reach run's per_test keys: everything the plan files
collect and run, including the nodes omitted from every screening shard and the nodes reaching no in-scope function in
the parent process). Shards: k = ceil(total explore time / cap), longest-processing-time assignment (largest node to
the least-loaded shard, ties by node id); k grows until every shard is <= cap. Within a shard nodes keep the plan run
order (explore JUnit order). cr_coord.check_pool_union verifies the union == pool exactly. Writes
cr_a3/<module>/completion/{pool.json, c<i>/nodes.txt, c<i>/selection.json} and selectors.json entries."""
import hashlib
import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from split import node_time, times  # noqa: E402
from t15c_common import EVID, MODULES, T, cr_coord, dump, load, sha  # noqa: E402


def run_order(junit):
    out = []
    for tc in ET.parse(junit).getroot().iter("testcase"):
        out.append((tc.get("classname"), tc.get("name")))
    return {k: i for i, k in enumerate(out)}


def key(n):
    path, _, rest = n.partition("::")
    return (path[:-3].replace("/", "."), rest)


def main(module, cap, reach, junit):
    cap = float(cap)
    rec, t, order = load(reach), times(junit), run_order(junit)
    pool = sorted(rec["per_test"])
    cost = {n: node_time(t, n) for n in pool}
    total = sum(cost.values())
    k = max(1, math.ceil(total / cap))
    while True:
        bins = [[0.0, i, []] for i in range(k)]
        for n in sorted(pool, key=lambda n: (-cost[n], n)):
            b = min(bins, key=lambda b: (b[0], b[1]))
            b[0] += cost[n]
            b[2].append(n)
        if max(b[0] for b in bins) <= cap:
            break
        k += 1
    shards = [sorted(b[2], key=lambda n: order[key(n)]) for b in bins]
    cr_coord.check_pool_union(pool, shards)
    root = EVID / module / "completion"
    root.mkdir(parents=True, exist_ok=True)
    canon = json.dumps(pool, separators=(",", ":")).encode("utf-8")
    dump(root / "pool.json", {"module": module, "plan_selector": [T + f for f in MODULES[module]], "nodes": pool,
                              "count": len(pool), "nodes_sha256": hashlib.sha256(canon).hexdigest(),
                              "reach_plan_sha256": sha(reach), "explore_junit_sha256": sha(junit),
                              "explore_total_s": round(total, 2), "cap_s": cap, "shards": k,
                              "rule": "pool = all plan-selector nodes; LPT bins <= cap; union == pool exactly "
                                      "(cr_coord.check_pool_union)"})
    sel = load(HERE / "selectors.json")
    for i, nodes in enumerate(shards, 1):
        d = root / f"c{i}"
        d.mkdir(exist_ok=True)
        (d / "nodes.txt").write_text("".join(n + "\n" for n in nodes), encoding="utf-8")
        dump(d / "selection.json", {"module": module, "completion_shard": f"c{i}", "nodes": len(nodes),
                                    "explore_time_s": round(sum(cost[n] for n in nodes), 2), "cap_s": cap,
                                    "pool_sha256": hashlib.sha256(canon).hexdigest()})
        rel = f"research/s1/s1_evidence/cr_a3/{module}/completion/c{i}"
        sel[module][f"completion/c{i}"] = {"args": [f"@{rel}/nodes.txt"], "completion": True}
        print(f"{module}/completion/c{i}: {len(nodes)} nodes {sum(cost[n] for n in nodes):.1f}s")
    (HERE / "selectors.json").write_text(json.dumps(sel, indent=1), encoding="utf-8")
    print(f"{module}: pool {len(pool)} nodes {total:.1f}s -> {k} completion shards")


if __name__ == "__main__":
    main(*sys.argv[1:])
