"""15c-H ruling 2: rewrite each screening config's batch_plan.json as a calibration-first plan (PROPOSAL, no manifest).

Session 1 = the first min(24, n) items in cr_coord.order_items order (calibration). Every other item stays explicitly
PENDING until cr_coord.derive_cap has recorded a cap from the calibration's measured per-item costs; the scenario cap
below (from baseline max + measured I/O + an ASSUMED 30 s CR overhead) is an estimate only, never used to batch."""
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from t15c_common import EVID, MODULES, cr_coord, dump, load, sha  # noqa: E402
from cr_guard import BUDGETS  # noqa: E402

b = load(Path(HERE).parent / "budget_v2.json")
for module in MODULES:
    for shard, r in b["modules"][module]["screening"].items():
        d = EVID / module / ("" if shard == "_" else shard)
        inv = load(d / "inventory_filtered.json")
        ids = [i["job_id"] for i in cr_coord.order_items(inv["kept"])]
        cal = ids[:BUDGETS["batch_max"]]
        cr_coord.check_partition(ids, [cal, ids[len(cal):]] if len(ids) > len(cal) else [cal],
                                 cap=max(len(ids), 1))
        dump(d / "batch_plan.json", {
            "module": module, "shard": None if shard == "_" else shard, "inventory_sha256": sha(d / "inventory.json"),
            "candidates": len(ids), "ordering": "cr_coord.order_items (location, operator, occurrence, job id)",
            "calibration_batch": cal, "pending_after_calibration": ids[len(cal):],
            "derived_cap": None, "derived_cap_rule": "cr_coord.derive_cap on the calibration state (>=24 measured "
                                                     "items): floor((10800 - fence) / max measured item); recorded, "
                                                     "sha256-bound; the HARD fence stays the safety bound",
            "scenario": {"est_item_s": r["est_item_s"], "derived_cap": r["scenario_derived_cap"],
                         "sessions": r["scenario_sessions"], "sessions_at_24": r["sessions_at_24"],
                         "note": "estimate from baseline max + measured I/O + ASSUMED 30 s CR overhead"},
            "status": "PROPOSAL - no manifest written, nothing executed"})
        print(module, shard, len(cal), len(ids) - len(cal), "scenario sessions", r["scenario_sessions"])
