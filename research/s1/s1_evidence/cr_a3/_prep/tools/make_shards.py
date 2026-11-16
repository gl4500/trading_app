"""T15c-prep: build function-partitioned shards with bounded exact-node selectors (predeclared omissions).

usage: make_shards.py <module> <reach.json> <explore junit.xml> <cap_s> <grouping.json> [<row ranges.json>]

grouping.json: {"<shard>": {"scopes": [top-level scope names], "prefer": ["<test file stem>", ...]}}; every
top-level scope of the row ranges (or of the reach record) must be in exactly one shard.

Per shard: candidate tests = every test reaching any of its scopes (reach record). If their summed explore time is
<= cap they are all selected. Otherwise a deterministic bounded selection:
  1. for every scope, its cheapest reaching test (so each in-scope function stays covered) - forced;
  2. then one node per test FUNCTION (diversity), preferred files first, cheapest param first;
  3. then the remaining params round-robin across test functions (preferred files first), cheapest first,
while the sum stays <= cap. Everything not selected is a predeclared omission (listed with its time).
Writes per shard: <evid>/<shard>/nodes.txt (pytest @argfile, one node id per line), <evid>/<shard>/ranges.json
(cr_coord.scope_ranges of the shard's scopes, expansion record copied from the row ranges), <evid>/<shard>/
selection.json; and selectors.json entries {"args": ["@<rel>/nodes.txt"], "ranges": "<rel>/ranges.json"}."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from split import node_time, times  # noqa: E402
from t15c_common import WT, cr_coord, dump, load, sha  # noqa: E402


MODLEVEL = "<module-level>"          # statements outside every top-level def/class (run at import, by every test)


def modlevel_intervals(module):
    import ast
    src = WT / "research/s1" / f"{module}.py"
    text = src.read_bytes()
    tree = ast.parse(text)
    n_lines = len(text.splitlines())
    taken = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            taken.update(range(start, node.end_lineno + 1))
    out, cur = [], None
    for ln in range(1, n_lines + 1):
        if ln not in taken:
            cur = [ln, ln] if cur is None else [cur[0], ln]
        elif cur is not None:
            out.append(cur)
            cur = None
    if cur is not None:
        out.append(cur)
    return out


def fn_of(n):
    return n.split("[")[0]


def stem(n):
    return n.split("::")[0].rsplit("/", 1)[-1][:-3]


def select(cands, t, cap, scopes_tests, prefer):
    cost = {n: node_time(t, n) for n in cands}
    total = sum(cost.values())
    if total <= cap:
        return sorted(cands), [], "all reaching tests (under cap)"
    pr = {s: i for i, s in enumerate(prefer)}
    key = lambda n: (pr.get(stem(n), len(pr)), cost[n], n)  # noqa: E731
    chosen, used = [], 0.0

    def take(n):
        nonlocal used
        if n not in chosen:
            chosen.append(n)
            used += cost[n]
    for s, tests in sorted(scopes_tests.items()):
        if tests and not (set(tests) & set(chosen)):
            take(min(tests, key=lambda n: (cost[n], n)))
    groups = {}
    for n in sorted(cands, key=key):
        groups.setdefault(fn_of(n), []).append(n)
    order = sorted(groups, key=lambda g: key(groups[g][0]))
    for g in order:
        n = groups[g][0]
        if n not in chosen and used + cost[n] <= cap:
            take(n)
    more = True
    while more:
        more = False
        for g in order:
            rest = [n for n in groups[g] if n not in chosen]
            if rest and used + cost[rest[0]] <= cap:
                take(rest[0])
                more = True
    omitted = sorted(set(cands) - set(chosen))
    return sorted(chosen), omitted, "bounded selection (forced cover, diversity, round-robin) under cap"


def main(module, reach, junit, cap, grouping, row_ranges=None):
    r, t, g = load(reach), times(junit), load(grouping)
    cap = float(cap)
    top = {}
    for f, v in r["functions"].items():
        top.setdefault(f.split(".")[0], set()).update(v["reached_by"])
    if row_ranges:
        rr = load(row_ranges)
        all_scopes = set(rr["scopes"])
    else:                                # whole module: every top-level def/class + the module-level statements
        import ast
        tree = ast.parse((WT / "research/s1" / f"{module}.py").read_bytes())
        rr = None
        all_scopes = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                                                   ast.ClassDef))} | {MODLEVEL}
    assigned = [s for sh in g.values() for s in sh["scopes"]]
    if sorted(assigned) != sorted(all_scopes):
        raise SystemExit(f"grouping does not partition the scopes: missing {sorted(all_scopes - set(assigned))} "
                         f"extra/dup {sorted(set(a for a in assigned if assigned.count(a) > 1 or a not in all_scopes))}")
    sel_path = HERE / "selectors.json"
    sel = load(sel_path)
    sel.setdefault(module, {})
    src = WT / "research/s1" / f"{module}.py"
    for name, sh in g.items():
        rel = f"research/s1/s1_evidence/cr_a3/{module}/{name}"
        evid = WT / rel
        evid.mkdir(parents=True, exist_ok=True)
        scopes_tests = {s: sorted(top.get(s, ())) for s in sh["scopes"] if s != MODLEVEL}
        cands = set().union(*map(set, scopes_tests.values()))
        pool_note = "tests reaching the shard's scopes"
        if MODLEVEL in sh["scopes"] or any(not ts for ts in scopes_tests.values()):
            cands |= set(r["per_test"])  # import-time code / scopes no observed test reaches: the whole plan selector
            pool_note = ("whole plan selector (shard owns module-level statements and/or scopes with no observed "
                         "reaching test - e.g. reached only in child processes, which the recorder cannot see)")
        chosen, omitted, how = select(cands, t, cap, scopes_tests, sh.get("prefer", []))
        (evid / "nodes.txt").write_text("".join(n + "\n" for n in chosen), encoding="utf-8")
        doc = cr_coord.scope_ranges(src, [s for s in sh["scopes"] if s != MODLEVEL], out=None,
                                    module_rel=f"research/s1/{module}.py")
        if MODLEVEL in sh["scopes"]:
            for a, b in modlevel_intervals(module):
                doc["scopes"][f"{MODLEVEL}@{a}-{b}"] = {"qualname": MODLEVEL, "kind": "module-level", "start": a,
                                                        "end": b}
            doc["module_level_note"] = ("synthetic line intervals outside every top-level def/class (imports, "
                                        "constants, decorators excluded), so module-level mutants are owned by "
                                        "exactly one shard")
        if rr:
            doc["row_ranges"] = {"file": str(Path(row_ranges).name), "sha256": sha(row_ranges)}
            for k in ("named", "ruled_delegations", "expanded", "public_names_added_by_walk", "expansion_rule"):
                doc[k] = rr.get(k)
            doc["delegation_edges"] = [e for e in rr["delegation_edges"] if e["callee"] in sh["scopes"]
                                       or e["caller"] in sh["scopes"]]
        dump(evid / "ranges.json", doc)
        uncovered = [s for s, ts in scopes_tests.items() if not (set(ts) & set(chosen))]
        dump(evid / "selection.json", {
            "module": module, "shard": name, "scopes": sh["scopes"], "prefer": sh.get("prefer", []), "cap_s": cap,
            "method": how, "candidate_pool": pool_note, "explore_junit_sha256": sha(junit), "reach_sha256": sha(reach),
            "candidates": len(cands), "selected": len(chosen),
            "selected_time_s": round(sum(node_time(t, n) for n in chosen), 2),
            "candidate_time_s": round(sum(node_time(t, n) for n in cands), 2),
            "scopes_without_reaching_test": [s for s, ts in scopes_tests.items() if not ts],
            "scopes_uncovered_by_selection": uncovered,
            "omitted": [{"node": n, "explore_s": round(node_time(t, n), 2)} for n in omitted]})
        sel[module][name] = {"args": [f"@{rel}/nodes.txt"], "ranges": f"{rel}/ranges.json"}
        print(f"{module}/{name}: {len(chosen)}/{len(cands)} nodes "
              f"{sum(node_time(t, n) for n in chosen):.1f}s/{sum(node_time(t, n) for n in cands):.1f}s "
              f"omitted {len(omitted)} uncovered {uncovered} no-test {[s for s, ts in scopes_tests.items() if not ts]}")
    sel_path.write_text(json.dumps(sel, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(*sys.argv[1:])
