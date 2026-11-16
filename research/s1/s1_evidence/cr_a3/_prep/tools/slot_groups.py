"""Derive the s1_slot two-shard grouping: a top-level scope goes to the "finalizer" shard when most of its reaching-test
time comes from test_s1_a3_finalizer.py, else to "slots"; scopes with no reaching test and the module-level
statements go to "slots" (recorded). Writes groups/s1_slot.json."""
import ast
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from split import node_time, times  # noqa: E402
from t15c_common import WORK, WT, dump, load  # noqa: E402

r = load(WORK / "reach/slot_plan.json")
t = times(WORK / "explore/s1_slot/junit.xml")
tree = ast.parse((WT / "research/s1/s1_slot.py").read_bytes())
tops = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
reach = {}
for f, v in r["functions"].items():
    reach.setdefault(f.split(".")[0], set()).update(v["reached_by"])
groups = {"slots": {"scopes": ["<module-level>"], "prefer": ["test_s1_a3_slots"]},
          "finalizer": {"scopes": [], "prefer": ["test_s1_a3_finalizer"]}}
for s in tops:
    tests = reach.get(s, set())
    fin = sum(node_time(t, n) for n in tests if "test_s1_a3_finalizer" in n)
    slo = sum(node_time(t, n) for n in tests if "test_s1_a3_slots" in n)
    groups["finalizer" if fin > slo else "slots"]["scopes"].append(s)
dump(WORK / "groups/s1_slot.json", groups)
print({k: len(v["scopes"]) for k, v in groups.items()})
