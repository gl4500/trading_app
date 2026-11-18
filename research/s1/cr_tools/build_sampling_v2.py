"""A3 Task 15c-P2: the deterministic builder of the EXTERNAL calibration sampling plan v2 (plans/sampling_v2.json).

Read-only on the source: it reads inventories, filtered inventories, pre-flight records and the module sources of a
--src-root (the retained 30e72bb archive C:/cr15c/src, or a toy) as bytes / JSON / AST - it never imports or executes
any of them, and never imports the harness. It reads the predecessor halt root (C:/cr15c/w/s1_journal) only to hash
the listed files. The selection rule and classifier are cr_calibrate's pure functions (runtime_ranges, stratum,
allocate, midpoints, select_calibration), so the driver's validate_plan recomputes exactly this.

Codex RULING (calibration sample) + PROVENANCE_P_RULING (plan-v2 binding fields): per screening config, two syntactic
strata over the WHOLE kept pool (import / definition time vs runtime body), 24 allocated proportionally (nearest
integer, at least 1 per non-empty stratum), midpoint quantiles floor((2j+1)N/(2n)) within each stratum, the result in
original kept order; no randomness, no outcome filtering. An efficiency calibration plan only: all kept candidates
stay in scope (calibration is not a filter), the sample maximum is not a worst-case bound. The plan binds the driver
and probe raw-byte sha256 (hash code first, then the plan; the driver never embeds the plan hash).

usage (real plan; asserts the 12 lists == Codex's draft, 23 eligible, 6318 kept):
    build_sampling_v2.py --src-root C:/cr15c/src --draft <sampling_v2_draft.json>
        --preflight-list <worktree>/research/s1/s1_evidence/a3/t15c_preflight_records_sha256.txt
        --predecessor-root C:/cr15c/w/s1_journal --planned-root C:/cr15c/w2 --out plans/sampling_v2.json
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import cr_calibrate as drv

MODULES = ("s1_journal", "s1_locks", "s1_trial", "s1_stage", "s1_slot", "s1_seal", "s1_collect")
FIRST_HALTED_JOB = "c03580c01cb54316892042b67eb9f7a8"
PREDECESSOR_FILES = ("report_session-000.json", "batch_000.json", "session-000/session.json",
                     "session-000/batch_000_state.json")
FIRST_JOB_FILES = ("guard.json", "policy_result.json", "classification.json", "session.sqlite", "cr_exec_run.json",
                   "cr.toml", "cr_exec_stdout.txt", "cr_exec_stderr.txt")


def sha(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def screening_configs(src_root: Path) -> list:
    """The screening configs in discover order (restated: cr_preflight.discover, screening only)."""
    ev = Path(src_root) / drv.EVID_REL
    out = []
    for m in MODULES:
        d = ev / m
        if (d / "cr.toml").is_file():
            out.append(m)
        else:
            out += sorted(f"{m}/{p.parent.name}" for p in d.glob("*/cr.toml") if p.parent.name != "completion")
    return out


def preflight_records(src_root: Path, list_file: Path | None = None) -> dict:
    """{rel: sha256} of the pre-flight record set: the committed list (order kept; every entry verified against the
    src_root, the rendered list must be the file's exact bytes) or, without one, every cr_a3 pre-flight record."""
    if list_file is None:
        ev = Path(src_root) / drv.EVID_REL
        return {p.relative_to(src_root).as_posix(): sha(p) for p in sorted(ev.glob("**/preflight/*.json"))}
    recs = {}
    for ln in Path(list_file).read_text(encoding="utf-8").splitlines():
        h, _, rel = ln.partition(" *")
        recs[rel] = h
    bad = [r for r, h in recs.items() if sha(Path(src_root) / r) != h]
    assert not bad, f"pre-flight records differ from the src_root: {bad[:3]}"
    assert drv.render_record_list(recs) == Path(list_file).read_bytes(), "the list renders back to its own bytes"
    return recs


def build_plan(src_root, *, configs, source_commit: str, preflight_commit: str, predecessor: dict,
               planned_root: str, preflight_list=None) -> dict:
    src_root = Path(src_root)
    entries = [drv.config_strata(src_root, c) for c in configs]
    for e in entries:
        assert e["kept_sorted_like_order_items"], f"{e['config']}: kept order is not the deterministic order"
        e.pop("kept_sorted_like_order_items")
    recs = preflight_records(src_root, preflight_list)
    for e in entries:
        assert all(recs.get(r) == h for r, h in e["preflight"].items()), f"{e['config']}: pre-flight not in the set"
    man = src_root / drv.MANIFEST_REL
    proot = Path(predecessor["root"])
    eligible_total = sum(len(e["eligible"]) for e in entries)
    return {
        "schema": drv.PLAN_SCHEMA, "plan_version": 2, "algorithm_revision": drv.ALGORITHM_REVISION,
        "status": "PLAN FOR REVIEW - no calibration, resume, retry or new-root execution GO is implied",
        "purpose": "efficiency calibration only: a prospective two-strata sample after the observed prefix bias; not "
                   "a representativeness or worst-case claim; the sample maximum is not a worst-case bound; the hard "
                   "405 s fence and the 3 h session clock stay the safety bound",
        "scope": {"universe_kept_total": sum(e["kept_count"] for e in entries), "all_in_scope": True,
                  "configs": len(entries),
                  "statement": "calibration is not a filter: every kept candidate stays in the full campaign scope; "
                               "sample membership is no exclusion; the 30e72bb inventories, batch plans and manifest "
                               "stay unchanged"},
        "source": {"commit": source_commit,
                   "manifest": {"rel": drv.MANIFEST_REL, "sha256": sha(man),
                                "entries": len([ln for ln in man.read_text(encoding="utf-8").splitlines()
                                                if ln.strip()])},
                   "preflight_records": {"commit": preflight_commit, "count": len(recs),
                                         "list_sha256": hashlib.sha256(drv.render_record_list(recs)).hexdigest(),
                                         "records": recs}},
        "classifier": {"version": drv.CLASSIFIER_VERSION, "source_sha256": drv.classifier_source_sha256(),
                       "definition": "a mutation START (line, col) is RUNTIME iff it lies inside a def body (its "
                                     "first body statement's start to the def's end, inclusive) or a lambda body; "
                                     "everything else - module scope, class bodies, def headers, defaults, "
                                     "decorators, annotations - is IMPORT / DEFINITION time. Syntactic location "
                                     "triage only: not a claim that any such mutation fails import"},
        "selection": {"size": drv.SAMPLE_SIZE,
                      "allocation": "n_import = (24*N_import + N//2) // N, at least 1 per non-empty stratum (at "
                                    "most 23 either way), bounded by stratum capacity; runtime = the rest within "
                                    "capacity; a pool of at most 24 is taken whole",
                      "formula": "floor((2j+1)N/(2n)) for j = 0..n-1 within each stratum (original kept order)",
                      "ties": "integer floor; strata keep the original kept order; the batch is restored to the "
                              "original kept order", "randomness": "none", "outcome_filtering": "none"},
        "configs": entries,
        "eligible_total": eligible_total,
        "diagnostic_children_ceiling": drv.MAX_DIAG_CHILDREN * eligible_total,
        "eligibility": "only these exact import-stratum SCREENING ids may get the import-invalid diagnosis; "
                       "runtime-stratum ids and every completion-stage error halt as before",
        "driver": {"rel": "research/s1/cr_tools/cr_calibrate.py", "sha256": sha(drv.__file__),
                   "policy_version": drv.POLICY_VERSION, "schema": drv.SCHEMA},
        "probe": {"rel": "research/s1/cr_tools/cr_import_probe.py", "sha256": sha(drv.PROBE_PATH),
                  "schema": drv.PROBE_SCHEMA},
        "builder": {"rel": "research/s1/cr_tools/build_sampling_v2.py", "sha256": sha(__file__)},
        "bounds": drv.expected_bounds(),
        "predecessor": {"root": str(predecessor["root"]), "first_job": predecessor["first_job"],
                        "files": {rel: sha(proot / rel) for rel in predecessor["files"]},
                        "disposition": "preserved untouched and unresolved: never resumed, retried, resolved or "
                                       "reused; no new attempt re-credits it; the first halted job is not in any "
                                       "list of this plan"},
        "planned_root": str(planned_root),
    }


def write_plan(path, plan: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes((json.dumps(plan, indent=1) + "\n").encode("utf-8"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="build_sampling_v2.py")
    for a in ("--src-root", "--draft", "--preflight-list", "--predecessor-root", "--planned-root", "--out"):
        ap.add_argument(a, required=True)
    a = ap.parse_args(argv)
    src = Path(a.src_root)
    draft = json.loads(Path(a.draft).read_text(encoding="utf-8"))
    configs = screening_configs(src)
    assert configs == [c["config"] for c in draft["configs"]], (configs, [c["config"] for c in draft["configs"]])
    proot = Path(a.predecessor_root)
    jobs = sorted(p.name for p in (proot / "session-000" / "jobs").iterdir())
    assert jobs == [FIRST_HALTED_JOB], jobs
    jd = f"session-000/jobs/{FIRST_HALTED_JOB}"
    att = sorted(p.name for p in (proot / jd).glob("attempt-*"))
    assert len(att) == 1, att
    files = list(PREDECESSOR_FILES) + [f"{jd}/{f}" for f in FIRST_JOB_FILES] + [f"{jd}/{att[0]}/nodes.json"]
    plan = build_plan(src, configs=configs, source_commit="30e72bbbd7ead5e6eb9cf48803245786f6c22608",
                      preflight_commit="3f198a3997d09b8d9e8f3c3c5ac6bd2b9ea9a6db",
                      predecessor={"root": str(proot).replace("\\", "/"), "first_job": FIRST_HALTED_JOB,
                                   "files": files},
                      planned_root=a.planned_root, preflight_list=Path(a.preflight_list))
    got = {c["config"]: c["calibration_batch"] for c in plan["configs"]}
    want = {c["config"]: c["calibration_batch"] for c in draft["configs"]}
    assert got == want, "the 12 lists equal Codex's sampling_v2_draft.json exactly"
    for c, d in zip(plan["configs"], draft["configs"]):
        assert (c["strata"]["import"]["count"], c["strata"]["runtime"]["count"]) == (
            d["import_definition_time_pool"], d["runtime_body_pool"]), c["config"]
        assert (c["strata"]["import"]["allocation"], c["strata"]["runtime"]["allocation"]) == (
            d["sample_import"], d["sample_runtime"]), c["config"]
        assert c["inventory_sha256"] == d["inventory_sha256"] and c["filtered_sha256"] == d["filtered_sha256"]
    assert plan["eligible_total"] == 23, plan["eligible_total"]
    assert plan["scope"]["universe_kept_total"] == 6318, plan["scope"]["universe_kept_total"]
    assert plan["source"]["manifest"]["entries"] == 1268 and plan["source"]["manifest"]["sha256"].startswith(
        "819ca0fe")
    assert plan["source"]["preflight_records"]["list_sha256"] == sha(a.preflight_list)
    assert plan["source"]["preflight_records"]["list_sha256"].startswith("bf4b0889")
    assert plan["source"]["preflight_records"]["count"] == 42
    assert FIRST_HALTED_JOB not in {j for v in got.values() for j in v}
    write_plan(a.out, plan)
    print(json.dumps({"out": str(a.out), "sha256": sha(a.out), "configs": len(got), "eligible_total": 23,
                      "universe": 6318, "driver_sha256": plan["driver"]["sha256"],
                      "probe_sha256": plan["probe"]["sha256"]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
