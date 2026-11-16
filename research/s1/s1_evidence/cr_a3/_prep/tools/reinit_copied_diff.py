"""Which copied-file hashes differ between each superseded and re-initialised inventory (adds to reinit_compare.json)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t15c_common import EVID, WORK, dump, load  # noqa: E402

ROUND = sys.argv[1] if len(sys.argv) > 1 else "fix1"
NAME = "reinit_compare.json" if ROUND == "fix1" else f"reinit_compare_{ROUND}.json"
rep = load(WORK / NAME)
SUP = EVID / "_superseded" / f"inventories_pre_{ROUND}"
allk = set()
for tag, row in rep["configs"].items():
    module, _, shard = tag.partition("__")
    old = load(SUP / tag / "inventory.json")["copied"]
    new = load(EVID / module / shard / "inventory.json" if shard else EVID / module / "inventory.json")["copied"]
    keys = sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))
    row["copied_files_differing"] = keys
    allk |= set(keys)
rep["copied_files_differing_any"] = sorted(allk)
dump(WORK / NAME, rep)
print(sorted(allk))
