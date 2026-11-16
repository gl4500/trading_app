import json, sys
for f in sys.argv[1:]:
    d = json.load(open(f, encoding="utf-8"))
    print("==", f, d["sha256"][:16])
    print(" ruled:", d["ruled_delegations"]); print(" public added:", d["public_names_added_by_walk"])
    for n, s in d["scopes"].items(): print("  scope", n, s["kind"], s["start"], s["end"])
    for e in d["delegation_edges"]: print("  edge", e["caller"], "->", e["callee"], e["lines"])
    seen = {}
    for x in d["decisions"]:
        seen.setdefault(x["helper"], {"from": [], "out": x["out_of_scope_referrers"]})["from"].append(f'{x["called_from_in_scope"]}:{x["lines"]}')
    for h, v in seen.items(): print("  DECISION", h, "from", v["from"], "out-of-scope refs", v["out"])
