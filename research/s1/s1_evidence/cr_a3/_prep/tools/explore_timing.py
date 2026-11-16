"""EXPLORATORY (not a baseline): one plain contained pytest run per plan selector on an unmutated fresh copy, with
JUnit per-test times, to decide which selectors need splitting before the 3x guard baselines. Serial."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t15c_common import (MODULES, PY, PYTEST_EXTRA, PYTHONPATH_REL, T, WORK, WT, cr_coord, cr_guard, dump,
                         source_copy_paths)

only = sys.argv[1:] or list(MODULES)
root = WORK / "explore"
copy = root / "copy"
if not copy.exists():
    cr_coord.make_copy(WT, source_copy_paths(), copy)
env = dict(os.environ)
env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=os.pathsep.join(str(copy / r) for r in PYTHONPATH_REL))
for k in ("CR_GUARD_JOB_DIR", "CR_GUARD_JOB_ID", "CR_GUARD_NODES_OUT", "CR_GUARD_ATTEMPT", "CR_GUARD_TARGETS"):
    env.pop(k, None)
for mod in only:
    out = root / mod
    out.mkdir(parents=True, exist_ok=True)
    env["S1_HYPOTHESIS_ROOT"] = str(out / "hyp")
    cmd = [str(PY), "-m", "pytest", *PYTEST_EXTRA, "-p", "no:cacheprovider", "-q", "-rA",
           f"--junitxml={out / 'junit.xml'}", f"--basetemp={out / 'bt'}", *[T + f for f in MODULES[mod]]]
    t0 = time.time()
    run = cr_guard.run_contained(cmd, cwd=copy, env=env, stdout_path=out / "stdout.txt",
                                 stderr_path=out / "stderr.txt", deadline_s=3600)
    run["wall_s"] = round(time.time() - t0, 3)
    run["cmd"] = cmd
    dump(out / "run.json", run)
    print(mod, run["rc"], run["wall_s"], run["cleanup"]["verified"], flush=True)
