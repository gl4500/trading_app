"""T15c-prep: derive a function-partitioned selector split from a reach record + per-test times (explore JUnit).

usage: split.py <reach.json> <explore junit.xml> <cap_seconds> [<grouping json>]
Prints, per top-level in-scope scope: reaching tests and their summed time; then a greedy partition of the top-level
scopes into shards (each shard's selector = union of the tests reaching its scopes) under the cap. A grouping json
({shard: [scopes...]}) overrides the greedy assignment and is just evaluated."""
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def times(junit):
    out = {}
    for tc in ET.parse(junit).getroot().iter("testcase"):
        cls, name = tc.get("classname"), tc.get("name")
        out[(cls, name)] = float(tc.get("time", 0))
    return out


def node_time(t, nodeid):
    path, _, rest = nodeid.partition("::")
    cls = path[:-3].replace("/", ".")
    return t[(cls, rest)]


def main(reach, junit, cap, grouping=None):
    r = json.loads(Path(reach).read_text(encoding="utf-8"))
    t = times(junit)
    top = {}
    for f, v in r["functions"].items():
        top.setdefault(f.split(".")[0], set()).update(v["reached_by"])
    cost = {s: sum(node_time(t, n) for n in tests) for s, tests in top.items()}
    for s in sorted(top, key=lambda s: -cost[s]):
        byf = {}
        for n in top[s]:
            f = n.split("::")[0].rsplit("/", 1)[-1].replace("test_s1_a3_", "")
            byf.setdefault(f, [0, 0.0])
            byf[f][0] += 1
            byf[f][1] += node_time(t, n)
        det = " ".join(f"{f}:{c}/{x:.0f}s" for f, (c, x) in sorted(byf.items()))
        print(f"  {s:28s} tests {len(top[s]):4d} {cost[s]:7.1f}s  {det}")
    alltests = set().union(*top.values())
    print(f"union tests {len(alltests)} {sum(node_time(t, n) for n in alltests):.1f}s of {len(r['per_test'])}")
    if grouping:
        g = json.loads(Path(grouping).read_text(encoding="utf-8"))
    else:
        shards = []
        for s in sorted(top, key=lambda s: -cost[s]):
            best = None
            for sh in shards:
                u = sh["tests"] | top[s]
                c = sum(node_time(t, n) for n in u)
                if c <= cap and (best is None or c - sh["cost"] < best[1]):
                    best = (sh, c - sh["cost"], c, u)
            if best:
                best[0]["scopes"].append(s)
                best[0]["tests"], best[0]["cost"] = best[3], best[2]
            else:
                shards.append({"scopes": [s], "tests": set(top[s]), "cost": cost[s]})
        g = {f"s{i}": sh["scopes"] for i, sh in enumerate(shards)}
    for name, scopes in g.items():
        u = set().union(*(top[s] for s in scopes))
        print(f"{name}: {len(u)} tests {sum(node_time(t, n) for n in u):.1f}s scopes {scopes}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], float(sys.argv[3]), *(sys.argv[4:5]))
