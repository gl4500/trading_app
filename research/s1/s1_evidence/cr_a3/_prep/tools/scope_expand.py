"""T15c-prep: row-289/290 scopes with delegation expansion (controller ruling 2026-11-15, Codex 15c prerequisite).

AST call-graph walk WITHIN the module: starting from the named scopes, a module-level function g directly called
(``g(...)``, a bare Name) from an in-scope body is ADDED iff every module-level scope that references g (call or any
other Name load, incl. module-level statements) is already in scope; transitive, to a fixed point. A g that is also
referenced from out-of-scope code is NOT added and is listed as a controller decision. Nothing outside the module is
followed. Ranges come from cr_coord.scope_ranges (the reviewed 15a resolver) on the expanded qualified-name list.

usage: scope_expand.py <module> <out ranges.json> <name> [<name> ...]"""
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t15c_common import WT, cr_coord, dump  # noqa: E402

ALGO = ("expand: module-level function g directly called (ast.Call with func=ast.Name(g)) from an in-scope body "
        "(nested defs/methods included) is added iff ALL module-level scopes referencing g (call or Name load; "
        "module-level statements count as '<module>') are in scope; iterate to a fixed point; never cross modules; "
        "g referenced from any out-of-scope scope -> controller decision, not added")


def top_scopes(tree):
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out[node.name] = node
    return out


def refs(node, names):
    """(calls {g: [lines]}, loads {g: [lines]}) of module-level names inside ``node``."""
    calls, loads = {}, {}
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in names:
            calls.setdefault(n.func.id, []).append(n.lineno)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id in names:
            loads.setdefault(n.id, []).append(n.lineno)
    return calls, loads


def main(module, out, names):
    src = WT / "research/s1" / f"{module}.py"
    tree = ast.parse(src.read_bytes(), filename=str(src))
    tops = top_scopes(tree)
    funcs = {k for k, v in tops.items() if isinstance(v, (ast.FunctionDef, ast.AsyncFunctionDef))}
    per = {k: refs(v, set(tops)) for k, v in tops.items()}
    modlevel = ast.Module(body=[s for s in tree.body if s not in tops.values()], type_ignores=[])
    per["<module>"] = refs(modlevel, set(tops))
    referrers = {g: sorted({s for s, (c, l) in per.items() if g in l and s != g} |
                           ({g} if g in per[g][1] else set())) for g in tops}
    ruled = [n[1:] for n in names if n.startswith("+")]       # controller-ruled known delegations (binding seeds)
    d4 = [n[1:] for n in names if n.startswith("^")]          # 15c-H ruling 4 (D4): value-referenced callback seeds
    names = [n for n in names if not n.startswith(("+", "^"))]
    ruled_basis = {g: "controller ruling 2026-11-15 (known delegation, binding)" for g in ruled}
    ruled_basis.update({g: "controller 15c-H ruling 4 (D4, Codex t15c_prep_review: callback passed by value, "
                           "only in-scope referrer)" for g in d4})
    ruled = ruled + d4
    for n in names + ruled:
        if n not in tops:
            raise SystemExit(f"named scope {n} is not a module-level def/class of {module}")
    scope, order, edges = list(names) + ruled, list(ruled), []
    changed = True
    while changed:
        changed = False
        for f in list(scope):
            for g, lines in sorted(per[f][0].items()):
                if g not in funcs or g in scope:
                    continue
                outside = [s for s in referrers[g] if s not in scope and s != g]
                if not outside:
                    scope.append(g)
                    order.append(g)
                    changed = True
    for g in order:                       # every in-scope caller -> g edge, with the call lines
        for f in scope:
            if f != g and g in per[f][0]:
                edges.append({"caller": f, "callee": g, "lines": sorted(per[f][0][g])})
    decisions = []
    for f in scope:
        for g, lines in sorted(per[f][0].items()):
            if g in funcs and g not in scope:
                decisions.append({"helper": g, "called_from_in_scope": f, "lines": sorted(lines),
                                  "out_of_scope_referrers": [s for s in referrers[g] if s not in scope],
                                  "disposition": "NOT added (also referenced out of scope) - controller decision"})
    for f in scope:                     # referenced as a VALUE (callback etc.), not a direct call: never auto-added
        for g, lines in sorted(per[f][1].items()):
            direct = per[f][0].get(g, [])
            extra = sorted(set(lines) - set(direct)) if len(lines) > len(direct) else []
            if g in funcs and g not in scope and extra:
                decisions.append({"helper": g, "called_from_in_scope": f, "lines": extra, "kind": "value_reference",
                                  "out_of_scope_referrers": [s for s in referrers[g] if s not in scope],
                                  "disposition": "NOT added (passed/referenced as a value, not a direct call) - "
                                                 "controller decision"})
    rel = f"research/s1/{module}.py"
    doc = cr_coord.scope_ranges(src, scope, out=None, module_rel=rel)
    ruled_notes = [{"callee": g, "basis": ruled_basis[g],
                    "also_referenced_out_of_scope_by": [s for s in referrers[g] if s not in scope]} for g in ruled]
    public_added = [g for g in order if not g.startswith("_")]
    doc.update(named=list(names), ruled_delegations=ruled_notes, public_names_added_by_walk=public_added,
               expanded=order, delegation_edges=edges, decisions=decisions, expansion_rule=ALGO,
               base_commit="02db5b9fa94ab21c4433b2655cab12782ba5bc13")
    dump(out, doc)
    print(f"{module}: named {len(names)} + expanded {order}; {len(decisions)} decision rows; sha {doc['sha256'][:12]}")


if __name__ == "__main__":
    main(sys.argv[1], Path(sys.argv[2]), sys.argv[3:])
