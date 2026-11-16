"""15c-H fix round 1, ruling 7 (N2): genuine re-initialisation of all 12 screening inventories with the FINAL harness
(cosmic-ray init only, via cr_launch on scratch copies; executes nothing). The previous inventory files are MOVED,
unedited, to cr_a3/_superseded/inventories_pre_fix1/<config>/ (historical provenance kept as recorded). Then:
compare old vs new item content - normalized mutation specs (module_path, operator, operator_args, occurrence,
start, end), in order - and report every differing field (job ids are fresh uuids from cosmic-ray init)."""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from t15c_common import EVID, MODULES, PY, WORK, cr_coord, dump, load, sha  # noqa: E402

SEL = load(HERE / "selectors.json")
SPEC_KEYS = ("module_path", "operator", "operator_args", "occurrence", "start", "end")
ROUND = sys.argv[1] if len(sys.argv) > 1 else "fix1"          # the round whose final harness re-initialises
SUP = EVID / "_superseded" / f"inventories_pre_{ROUND}"
os.environ["T15C_INV_DIR"] = f"inv_{ROUND}"
report = {"harness_sha256_now": cr_coord.harness_hashes(), "configs": {}}
t_all = time.monotonic()
for module in MODULES:
    for shard, spec in SEL[module].items():
        if spec.get("completion"):
            continue
        tag = module + ("" if shard == "_" else f"__{shard}")
        d = EVID / module / ("" if shard == "_" else shard)
        old_dir = SUP / tag
        if old_dir.exists():
            raise SystemExit(f"{old_dir} exists")
        old_dir.mkdir(parents=True)
        for n in ("inventory.json", "inventory.json.sha256", "inventory_filtered.json", "batch_plan.json"):
            shutil.move(str(d / n), str(old_dir / n))
        t0 = time.monotonic()
        args = [str(PY), str(HERE / "inventory.py"), module] + ([] if shard == "_" else [shard])
        r = subprocess.run(args, capture_output=True, text=True, env=dict(os.environ))
        dt = round(time.monotonic() - t0, 2)
        if r.returncode != 0:
            raise SystemExit(f"{tag}: inventory failed\n{r.stdout}\n{r.stderr}")
        old, new = load(old_dir / "inventory.json"), load(d / "inventory.json")
        norm = lambda inv: [{k: i[k] for k in SPEC_KEYS} for i in inv["items"]]  # noqa: E731
        diff_fields = sorted(k for k in set(old) | set(new) if k not in ("items",) and old.get(k) != new.get(k))
        report["configs"][tag] = {
            "seconds": dt, "count_old": old["count"], "count_new": new["count"],
            "normalized_items_identical_in_order": norm(old) == norm(new),
            "job_ids_changed": sum(1 for a, b in zip(old["items"], new["items"]) if a["job_id"] != b["job_id"]),
            "top_level_fields_differing": diff_fields,
            "old_harness_sha256": old.get("harness_sha256"), "new_harness_sha256": new.get("harness_sha256"),
            "old_inventory_sha256": sha(old_dir / "inventory.json"), "new_inventory_sha256": sha(d / "inventory.json"),
            "post_filter_old": load(old_dir / "inventory_filtered.json")["post_filter_count"],
            "post_filter_new": load(d / "inventory_filtered.json")["post_filter_count"]}
        print(tag, report["configs"][tag]["seconds"], "s identical:",
              report["configs"][tag]["normalized_items_identical_in_order"], diff_fields, flush=True)
report["total_seconds"] = round(time.monotonic() - t_all, 2)
dump(WORK / ("reinit_compare.json" if ROUND == "fix1" else f"reinit_compare_{ROUND}.json"), report)
print("total", report["total_seconds"])
