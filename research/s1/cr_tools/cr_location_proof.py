"""A3 Task 15c-P2 location proof (Codex PROVENANCE_P_RULING P4: "prove 21 bindings / 12 maps unchanged again after
driver + probe + tests install"). Read-only on the worktree; the same recomputation as the 15c-E proof: for all 21
configs the copy paths, the RECOMPUTED pre-flight binding (sha256 of its canonical JSON, its copied_sha256, file count)
and whether check_preflight accepts the committed record; for the 12 screening configs the RECOMPUTED copied map and
the stored inventory.json "copied" map; every inventory / filtered inventory / batch plan sha256; and any copy path
or copied file naming cr_tools. Imports only the worktree harness (cr_coord, cr_preflight) - no S1 module.

usage: cr_location_proof.py <worktree root> <out.json> [--expect-body <sha256>]
"""
import hashlib
import json
import sys
from pathlib import Path


def sha(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def jsha(o) -> str:
    return hashlib.sha256(json.dumps(o, sort_keys=True).encode("utf-8")).hexdigest()


def main(argv) -> int:
    wt, out_p = Path(argv[0]), Path(argv[1])
    expect = argv[argv.index("--expect-body") + 1] if "--expect-body" in argv else None
    sys.path.insert(0, str(wt / "research/s1/s1_tests"))
    import cr_coord
    import cr_preflight
    out = {"cr_tools_present": sorted(p.name for p in (wt / "research/s1/cr_tools").rglob("*") if p.is_file()
                                      and "__pycache__" not in p.parts),
           "configs": {}, "screening_copied_maps": {}, "inventories": {}, "mentions_cr_tools": []}
    for conf in cr_preflight.discover(wt):
        cfg = cr_preflight.config_from_toml(conf["dir"] / "cr.toml")
        cp = sorted(cr_preflight.copy_paths_for(wt, cfg))
        b = cr_coord.preflight_binding(cfg, wt, cp)
        cm = cr_coord.copied_map(wt, cp)
        try:
            gate = cr_coord.check_preflight(conf["dir"] / "preflight", cfg, src_root=wt, copy_paths=cp)["sha256"]
        except cr_coord.CoordError as e:
            gate = f"REFUSED: {str(e)[:160]}"
        out["configs"][conf["rel"]] = {"copy_paths": cp, "binding_sha256": jsha(b),
                                       "copied_sha256": b["copied_sha256"], "copied_files": len(cm), "gate": gate}
        out["mentions_cr_tools"] += [f"{conf['rel']}: {x}" for x in list(cp) + list(cm) if "cr_tools" in x]
        if conf["kind"] == "screening":
            inv = json.loads((conf["dir"] / "inventory.json").read_text(encoding="utf-8"))
            out["screening_copied_maps"][conf["rel"]] = {
                "recomputed_copied_map_sha256": cr_coord.map_sha256(cm), "recomputed_files": len(cm),
                "inventory_copied_map_sha256": cr_coord.map_sha256(inv.get("copied") or {}),
                "inventory_copied_files": len(inv.get("copied") or {})}
    for p in sorted((wt / "research/s1/s1_evidence/cr_a3").rglob("*.json")):
        if "_superseded" in p.parts or p.name not in ("inventory.json", "inventory_filtered.json", "batch_plan.json"):
            continue
        out["inventories"][p.relative_to(wt).as_posix()] = sha(p)
    body = {k: v for k, v in out.items() if k != "cr_tools_present"}
    out["body_sha256"] = jsha(body)
    accepted = sum(1 for v in out["configs"].values() if not v["gate"].startswith("REFUSED"))
    same = [k for k, v in out["screening_copied_maps"].items()
            if v["recomputed_copied_map_sha256"] == v["inventory_copied_map_sha256"]]
    out["summary"] = {"configs": len(out["configs"]), "accepted": accepted,
                      "screening_maps": len(out["screening_copied_maps"]), "maps_equal_inventory": len(same),
                      "inventory_files": len(out["inventories"]), "mentions_cr_tools": len(out["mentions_cr_tools"]),
                      "expected_body": expect, "body_equal": expect is None or expect == out["body_sha256"]}
    out_p.write_text(json.dumps(out, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps(dict(out["summary"], body_sha256=out["body_sha256"], cr_tools=out["cr_tools_present"]),
                     indent=1))
    return 0 if (accepted == 21 and len(out["screening_copied_maps"]) == 12 and not out["mentions_cr_tools"]
                 and out["summary"]["body_equal"]) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
