"""15c-H: measure the per-item coordinator I/O outside Cosmic Ray (fresh S1 copy, source/harness hashing, job dir,
copy removal) with the REAL cr_coord.run_batch and a stub exec seam that does no work (no Cosmic Ray, no mutation).
Also times write_cr_toml + one-item WorkDB creation + cr_reconcile.reconcile on an empty-result session (the I/O
real_exec adds around the contained CR process). Prints max/median per item."""
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t15c_common import WORK, WT, cfg_for, cr_coord, dump, load, source_copy_paths  # noqa: E402
import cr_reconcile  # noqa: E402

inv = load(WT / "research/s1/s1_evidence/cr_a3/s1_trial/inventory.json")
items = inv["items"][:12]
by_id = {i["job_id"]: i for i in items}
root = WORK / "measure_io" / time.strftime("%Y%m%dT%H%M%S")
times = {}


def seam(item, copy_root, job_dir):
    t0 = time.monotonic()
    from cosmic_ray.work_db import WorkDB, use_db
    from cosmic_ray.work_item import MutationSpec, WorkItem
    cfg = cfg_for("s1_trial", ["research/s1/s1_tests/test_s1_a3_trial.py"], "research/s1/s1_evidence/x.json")
    cr_coord.write_cr_toml(job_dir / "cr.toml", cfg)
    with use_db(str(job_dir / "session.sqlite"), WorkDB.Mode.create) as w:
        w.add_work_item(WorkItem.single(item["job_id"], MutationSpec(
            module_path=item["module_path"], operator_name=item["operator"], occurrence=item["occurrence"],
            start_pos=tuple(item["start"]), end_pos=tuple(item["end"]), operator_args=item["operator_args"])))
    cr_reconcile.reconcile(job_dir / "session.sqlite", job_dir.parent, job_dir / "classification.json")
    times.setdefault(item["job_id"], {})["seam_io_s"] = time.monotonic() - t0
    return {"label": "survived", "guard_status": "survived", "raw_timeout": False, "exec_status": "ok",
            "cleanup_verified": True}


t_items = []
last = [time.monotonic()]
for j in [i["job_id"] for i in items]:
    t0 = time.monotonic()
    cr_coord.run_batch([j], by_id, batch_id=f"io{len(t_items):03d}", src_root=WT, copy_paths=source_copy_paths(),
                       work_root=root, exec_seam=seam, source_sha256={inv["module_rel"]: inv["source_sha256"]})
    t_items.append(time.monotonic() - t0)
out = {"items": len(t_items), "per_item_s": [round(x, 3) for x in t_items],
       "max_s": round(max(t_items), 3), "median_s": round(statistics.median(t_items), 3),
       "seam_io_s": {k: round(v["seam_io_s"], 3) for k, v in times.items()},
       "note": "real run_batch per item (copy, drift+harness hashing, job dir, state dumps, rmtree) + stub seam doing "
               "real_exec's non-CR I/O (cr.toml, one-item WorkDB, reconcile); no Cosmic Ray process, no mutation"}
dump(WORK / "measure_io.json", out)
print(json.dumps({k: v for k, v in out.items() if k != "seam_io_s"}))
