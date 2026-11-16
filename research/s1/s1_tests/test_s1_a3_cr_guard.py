"""A3 Task 15a (Task 15 Step 3b + controller rulings R2/R3/R4/R5/R8): the safe Cosmic Ray harness, tested on SYNTHETIC
throwaway projects in tmp_path only. No real S1 module is mutated here.

Covers: cr_guard exit/sidecar contract (killed only on a clean assertion failure; error/empty/skip/node-set/crash/timeout
all exit 0 with the precise status recorded), Windows Job Object containment of a grandchild that outlives the inner
deadline (proved dead by handles the test opened itself), the reconciler's overrides of raw Cosmic Ray labels, the
AST range filter (no pragmas), the one-mutant-per-copy coordinator (exact partition, quarantine + stop, pending kept),
and one end-to-end run of the REAL installed Cosmic Ray 8.3.15 through cr_launch.py with cr_guard as test-command."""
import ctypes
import hashlib
import json
import os
import random
import sqlite3
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

import pytest

import cr_coord
import cr_guard
import cr_reconcile

PY = Path(sys.executable)
HARNESS = Path(cr_guard.__file__).resolve().parent


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def project(root: Path, files: dict) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    return root


def control(path: Path, nodes) -> Path:
    path.write_text(json.dumps({"nodes": sorted(nodes)}), encoding="utf-8")
    return path


def guard(monkeypatch, proj: Path, job: Path, argv) -> tuple[int, dict]:
    monkeypatch.chdir(proj)
    monkeypatch.setenv("CR_GUARD_JOB_DIR", str(job))
    monkeypatch.setenv("CR_GUARD_JOB_ID", job.name)
    rc = cr_guard.main([str(a) for a in argv])
    side = job / "guard.json"
    assert side.exists(), f"guard wrote no sidecar (rc={rc})"
    return rc, json.loads(side.read_text(encoding="utf-8"))


GOOD_AND_BAD = {"test_a.py": "def test_ok():\n    assert 1 == 1\n\n\ndef test_bad():\n    assert 1 == 2\n"}


# ------------------------------------------------------------------------------------------------------ guard: exits
def test_assertion_failure_exits_1_and_records_killed(tmp_path, monkeypatch):
    proj = project(tmp_path / "p", GOOD_AND_BAD)
    ctl = control(tmp_path / "ctl.json", ["test_a.py::test_ok", "test_a.py::test_bad"])
    rc, g = guard(monkeypatch, proj, tmp_path / "job1", ["--control", ctl, "test_a.py"])
    assert (rc, g.get("status"), g.get("exit_code")) == (1, "killed", 1)
    assert g.get("counts", {}).get("failures") == 1 and g["counts"].get("errors") == 0, g.get("counts")
    assert sorted(g.get("nodes", [])) == ["test_a.py::test_bad", "test_a.py::test_ok"]
    att = Path(g.get("attempt_dir", tmp_path / "job1" / "no-attempt-dir"))
    assert att.parent == tmp_path / "job1" and att.name.startswith("attempt-"), att
    assert g.get("junit_sha256") == sha(att / "junit.xml")
    assert g.get("deadline_s") == cr_guard.BUDGETS["guard_inner_deadline_s"] == 240
    assert g.get("cleanup", {}).get("verified") is True
    assert json.loads((att / "cleanup.json").read_text(encoding="utf-8")).get("verified") is True
    assert g.get("job_id") == "job1"
    assert g.get("failed_types") == {"test_a.py::test_bad": "AssertionError"}


# Fix round 1, I3: each error rule is pinned WITH a declared control (so a missing rule would otherwise give killed)
def test_collection_error_anywhere_exits_0_even_with_a_failure(tmp_path, monkeypatch):
    proj = project(tmp_path / "p", dict(GOOD_AND_BAD, **{"test_b.py": "import no_such_module_t15a\n\n"
                                                         "def test_x():\n    assert True\n"}))
    ctl = control(tmp_path / "ctl.json", ["test_a.py::test_ok", "test_a.py::test_bad", "test_b.py::test_x"])
    rc, g = guard(monkeypatch, proj, tmp_path / "job", ["--control", ctl, "test_a.py", "test_b.py"])
    assert (rc, g.get("status")) == (0, "error:collection")
    assert g.get("collect_errors"), "the collection error is recorded"


def test_setup_fixture_error_exits_0(tmp_path, monkeypatch):
    src = ("import pytest\n\n@pytest.fixture\ndef broken():\n    raise RuntimeError('fixture boom')\n\n"
           "def test_uses(broken):\n    assert True\n\n\ndef test_bad():\n    assert 1 == 2\n")
    proj = project(tmp_path / "p", {"test_s.py": src})
    ctl = control(tmp_path / "ctl.json", ["test_s.py::test_uses", "test_s.py::test_bad"])
    rc, g = guard(monkeypatch, proj, tmp_path / "job", ["--control", ctl, "test_s.py"])
    assert (rc, g.get("status")) == (0, "error:setup")
    assert g.get("counts", {}).get("errors", 0) >= 1


def test_teardown_error_exits_0(tmp_path, monkeypatch):
    src = ("import pytest\n\n@pytest.fixture\ndef td():\n    yield 1\n    raise RuntimeError('teardown boom')\n\n"
           "def test_bad(td):\n    assert td == 2\n")
    proj = project(tmp_path / "p", {"test_t.py": src})
    ctl = control(tmp_path / "ctl.json", ["test_t.py::test_bad"])
    rc, g = guard(monkeypatch, proj, tmp_path / "job", ["--control", ctl, "test_t.py"])
    assert (rc, g.get("status")) == (0, "error:teardown")


def test_clean_failure_without_a_declared_control_is_not_killed(tmp_path, monkeypatch):
    proj = project(tmp_path / "p", GOOD_AND_BAD)
    rc, g = guard(monkeypatch, proj, tmp_path / "job", ["test_a.py"])
    assert (rc, g.get("status")) == (0, "error:no_control")


def test_empty_selection_exits_0(tmp_path, monkeypatch):
    proj = project(tmp_path / "p", {"test_e.py": "X = 1\n"})
    rc, g = guard(monkeypatch, proj, tmp_path / "job", ["test_e.py"])
    assert (rc, g.get("status")) == (0, "empty")


def test_skip_present_exits_0_and_is_recorded(tmp_path, monkeypatch):
    src = "import pytest\n\n@pytest.mark.skip(reason='t15a')\ndef test_sk():\n    pass\n\n\ndef test_bad():\n    assert 0\n"
    proj = project(tmp_path / "p", {"test_k.py": src})
    rc, g = guard(monkeypatch, proj, tmp_path / "job", ["test_k.py"])
    assert (rc, g.get("status")) == (0, "skip")
    assert g.get("counts", {}).get("skipped") == 1 and g.get("skipped") == ["test_k.py::test_sk"]


def test_node_set_differing_from_declared_control_exits_0(tmp_path, monkeypatch):
    proj = project(tmp_path / "p", GOOD_AND_BAD)
    ctl = control(tmp_path / "ctl.json", ["test_a.py::test_bad", "test_a.py::test_gone"])
    rc, g = guard(monkeypatch, proj, tmp_path / "job", ["--control", ctl, "test_a.py"])
    assert (rc, g.get("status")) == (0, "node_set_mismatch")
    assert g.get("node_set", {}).get("missing") == ["test_a.py::test_gone"]
    assert g.get("node_set", {}).get("extra") == ["test_a.py::test_ok"]


def test_crash_without_junit_exits_0(tmp_path, monkeypatch):
    proj = project(tmp_path / "p", {"test_c.py": "import os\n\ndef test_die():\n    os._exit(9)\n"})
    rc, g = guard(monkeypatch, proj, tmp_path / "job", ["test_c.py"])
    assert (rc, g.get("status"), g.get("rc")) == (0, "crash", 9)


def test_write_control_records_the_clean_node_set(tmp_path, monkeypatch):
    proj = project(tmp_path / "p", {"test_w.py": "def test_one():\n    assert True\n\n\ndef test_two():\n    pass\n"})
    out = tmp_path / "control.json"
    rc, g = guard(monkeypatch, proj, tmp_path / "job", ["--write-control", out, "test_w.py"])
    assert (rc, g.get("status")) == (0, "control:ok")
    assert json.loads(out.read_text(encoding="utf-8")) == {"nodes": ["test_w.py::test_one", "test_w.py::test_two"]}


def test_job_dir_env_unset_refuses_with_exit_0(tmp_path, monkeypatch, capsys):
    proj = project(tmp_path / "p", GOOD_AND_BAD)
    monkeypatch.chdir(proj)
    monkeypatch.delenv("CR_GUARD_JOB_DIR", raising=False)
    rc = cr_guard.main(["test_a.py"])
    out = capsys.readouterr().out
    assert rc == 0 and "error:no_job_dir" in out, out
    assert sorted(p.name for p in proj.iterdir()) == ["pytest.ini", "test_a.py"], "no child pytest ran"


# ------------------------------------------------------------------------------------- guard: process-tree containment
_K32 = ctypes.WinDLL("kernel32", use_last_error=True)
_K32.OpenProcess.restype = wintypes.HANDLE
_K32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_K32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
_K32.WaitForSingleObject.restype = wintypes.DWORD
_K32.CloseHandle.argtypes = (wintypes.HANDLE,)


def _hold(pid: int):
    """The TEST's own SYNCHRONIZE handle on a process (independent of cr_guard): it pins the process object, so a later
    'signalled' answer cannot be confused by PID reuse."""
    return _K32.OpenProcess(0x00100000 | 0x1000, False, pid)


SLEEPER = "import os, sys, time\nopen(sys.argv[1], 'w').write(str(os.getpid()))\ntime.sleep(120)\n"
SPAWNER = ("import subprocess, sys, time\nfrom pathlib import Path\n\n"
           "def test_spawns_a_grandchild_then_hangs():\n"
           "    here = Path(__file__).resolve().parent\n"
           "    p = subprocess.Popen([sys.executable, str(here / 'sleeper.py'), str(here / 'gc_real.pid')])\n"
           "    (here / 'gc_launcher.pid').write_text(str(p.pid))\n"
           "    time.sleep(120)\n")


def test_grandchild_past_the_deadline_is_contained_and_verified_dead(tmp_path, monkeypatch):
    proj = project(tmp_path / "p", {"test_g.py": SPAWNER, "sleeper.py": SLEEPER})
    handles, stop = {}, threading.Event()

    def watch():                                    # open our own handles as soon as the pids are published
        while not stop.is_set():
            for name in ("gc_launcher.pid", "gc_real.pid"):
                f = proj / name
                if name not in handles and f.exists() and f.read_text().strip():
                    pid = int(f.read_text())
                    handles[name] = (pid, _hold(pid))
            time.sleep(0.05)
    t = threading.Thread(target=watch, daemon=True)
    t.start()
    t0 = time.monotonic()
    try:
        rc, g = guard(monkeypatch, proj, tmp_path / "job", ["--deadline", "12", "test_g.py"])
    finally:
        stop.set()
        t.join(5)
    elapsed = time.monotonic() - t0
    assert (rc, g.get("status")) == (0, "timeout")
    assert elapsed < 12 + cr_guard.BUDGETS["cleanup_reserve_s"], elapsed
    assert set(handles) == {"gc_launcher.pid", "gc_real.pid"}, f"grandchild pids not published in time: {handles}"
    try:
        for name, (pid, h) in handles.items():
            assert h, f"{name}: could not open pid {pid}"
            assert _K32.WaitForSingleObject(h, 0) == 0, f"{name} pid {pid} still alive after the guard returned"
    finally:
        for _, h in handles.values():
            if h:
                _K32.CloseHandle(h)
    seen = {p["pid"] for p in g.get("holder_pids", [])}
    assert handles["gc_real.pid"][0] in seen, "the real grandchild interpreter was a recorded job member"
    clean = json.loads((Path(g.get("attempt_dir", tmp_path / "job")) / "cleanup.json").read_text(encoding="utf-8"))
    assert clean.get("terminated") is True and clean.get("verified") is True and clean.get("active_after") == 0


# ----------------------------------------------------------------------------------------------------- reconciler
def _session(db: Path, results: dict):
    """A Cosmic Ray session built through the installed WorkDB API (the real storage format)."""
    from cosmic_ray.work_db import WorkDB, use_db
    from cosmic_ray.work_item import MutationSpec, TestOutcome, WorkerOutcome, WorkItem, WorkResult
    with use_db(str(db), WorkDB.Mode.create) as w:
        for i, job in enumerate(results):
            w.add_work_item(WorkItem.single(job, MutationSpec("m.py", "core/NumberReplacer", 0, (i + 1, 0), (i + 1, 1))))
        for job, r in results.items():
            if r is None:
                continue
            wo, to, out = r
            w.set_result(job, WorkResult(worker_outcome=WorkerOutcome(wo), test_outcome=to and TestOutcome(to),
                                         output=out))


def _out(job, status="x", code=1):
    """The stdout line cr_guard prints, which Cosmic Ray stores as the result output (binds result to attempt)."""
    return f"cr_guard: attempt=att-{job} exit={code} status={status} sidecar=jobs/{job}/guard.json"   # R1-N3 order


def _side(jobs: Path, job: str, status: str, job_id=None, attempt=None):
    (jobs / job).mkdir(parents=True)
    (jobs / job / "guard.json").write_text(json.dumps({"status": status, "job_id": job_id or job,
                                                      "attempt": attempt or f"att-{job}"}), encoding="utf-8")


def test_reconciler_overrides_raw_cosmic_ray_labels(tmp_path):
    db, jobs = tmp_path / "s.sqlite", tmp_path / "jobs"
    _session(db, {"k_to": ("normal", "killed", _out("k_to")), "k_err": ("normal", "killed", _out("k_err")),
                  "k_ok": ("normal", "killed", _out("k_ok")), "cr_to": ("normal", "killed", "timeout"),
                  "k_none": ("normal", "killed", _out("k_none")), "k_wrongid": ("normal", "killed", _out("k_wrongid")),
                  "k_wrongatt": ("normal", "killed", _out("k_wrongatt")), "k_noatt": ("normal", "killed", "rc=1"),
                  "s_ok": ("normal", "survived", _out("s_ok", "survived", 0)),
                  "s_empty": ("normal", "survived", _out("s_empty", "empty", 0)),
                  "skip": ("skipped", None, None), "pend": None})
    _side(jobs, "k_to", "timeout")
    _side(jobs, "k_err", "error:collection")
    _side(jobs, "k_ok", "killed")
    _side(jobs, "cr_to", "killed")                  # even a 'killed' sidecar cannot rescue a raw CR timeout
    _side(jobs, "k_wrongid", "killed", job_id="someone_else")
    _side(jobs, "k_wrongatt", "killed", attempt="att-of-a-retry")   # M3: same job id, another attempt
    _side(jobs, "k_noatt", "killed")                # M3: CR output carries no guard attempt line
    _side(jobs, "s_ok", "survived")
    _side(jobs, "s_empty", "empty")
    out = tmp_path / "classification.json"
    res = cr_reconcile.reconcile(db, jobs, out)
    assert out.exists()
    on_disk = json.loads(out.read_text(encoding="utf-8"))
    assert on_disk == res
    lab = {i["job_id"]: i.get("label") for i in res.get("items", [])}
    assert lab == {"k_to": "timeout", "k_err": "error", "k_ok": "killed", "cr_to": "timeout", "k_none": "error",
                   "k_wrongid": "error", "k_wrongatt": "error", "k_noatt": "error", "s_ok": "survived", "s_empty": "untested", "skip": "skipped-by-scope",
                   "pend": "deferred"}, lab
    raw = {i["job_id"]: i.get("raw", {}) for i in res["items"]}
    assert raw["cr_to"].get("test_outcome") == "killed" and raw["cr_to"].get("cr_timeout") is True
    assert raw["k_to"].get("test_outcome") == "killed" and raw["k_to"].get("cr_timeout") is False
    assert "equivalent" not in lab.values()
    assert res.get("session_sha256") == sha(db)


def test_reconciler_vocabulary_is_the_plan_label_set():
    assert cr_reconcile.LABELS == ("killed", "survived", "error", "untested", "timeout", "crash", "not-installed",
                                   "failed-elsewhere", "equivalent", "skipped-by-scope", "deferred")


# ----------------------------------------------------------------------------------------------- range filter (R8)
SAMPLE = '''import functools


def alpha(x):
    def inner(y):
        return y + 1
    return inner(x) * 2


def beta():
    return 3


class Box:
    def get(self):
        return 1

    class Nested:
        def deep(self):
            return 2


@functools.lru_cache
def gamma():
    return 4
'''


def _item(job, row, col=4, end=None):
    return {"job_id": job, "module_path": "sample.py", "operator": "core/NumberReplacer", "operator_args": {},
            "occurrence": 0, "start": [row, col], "end": end or [row, col + 1]}


def test_range_filter_keeps_only_named_scopes_including_nested_and_methods(tmp_path):
    src = tmp_path / "sample.py"
    src.write_text(SAMPLE, encoding="utf-8")
    before = sha(src)
    rng = cr_coord.scope_ranges(src, ["alpha", "Box", "gamma"], out=tmp_path / "ranges.json")
    assert sha(src) == before, "no pragma or any other byte added to the source"
    assert (tmp_path / "ranges.json").exists(), "ranges.json recorded"
    on_disk = json.loads((tmp_path / "ranges.json").read_text(encoding="utf-8"))
    assert on_disk == rng and rng.get("sha256") == before
    sc = rng.get("scopes", {})
    assert (sc.get("alpha", {}).get("start"), sc.get("alpha", {}).get("end")) == (4, 7)
    assert (sc.get("Box", {}).get("start"), sc.get("Box", {}).get("end")) == (14, 20)
    assert (sc.get("gamma", {}).get("start"), sc.get("gamma", {}).get("end")) == (23, 25), "decorator included"
    items = [_item("in_inner", 6), _item("in_alpha", 7), _item("beta", 11), _item("get", 16), _item("deep", 20),
             _item("decor", 23, 1, [23, 18]), _item("import", 1, 0, [1, 16])]
    kept, excluded = cr_coord.filter_by_scope(items, rng)
    assert sorted(i["job_id"] for i in kept) == ["decor", "deep", "get", "in_alpha", "in_inner"]
    assert sorted(i["job_id"] for i in excluded) == ["beta", "import"]
    assert all(i.get("disposition") == "skipped-by-scope" for i in excluded)


def test_range_filter_marks_excluded_items_in_the_workdb(tmp_path):
    from cosmic_ray.work_db import WorkDB, use_db
    db = tmp_path / "s.sqlite"
    _session(db, {"a": None, "b": None, "c": None})
    cr_coord.mark_skipped_by_scope(db, ["b"])
    with use_db(str(db), WorkDB.Mode.open) as w:
        res = {j: r.worker_outcome.value for j, r in w.results}
        pend = sorted(i.job_id for i in w.pending_work_items)
    assert res == {"b": "skipped"} and pend == ["a", "c"]


def test_range_name_resolving_zero_times_raises(tmp_path):
    src = tmp_path / "sample.py"
    src.write_text(SAMPLE, encoding="utf-8")
    with pytest.raises(cr_coord.ScopeError, match=r"'missing_fn' resolves 0 times"):
        cr_coord.scope_ranges(src, ["alpha", "missing_fn"])


def test_range_name_resolving_more_than_once_raises(tmp_path):
    src = tmp_path / "dup.py"
    src.write_text("def a():\n    def h():\n        pass\n\n\ndef b():\n    def h():\n        pass\n", encoding="utf-8")
    with pytest.raises(cr_coord.ScopeError, match=r"'h' resolves 2 times: a\.h, b\.h"):
        cr_coord.scope_ranges(src, ["h"])
    assert cr_coord.scope_ranges(src, ["b.h"])["scopes"]["b.h"]["start"] == 7, "a dotted qualname is exact"


# ----------------------------------------------------------------------------------------------------- coordinator
def test_budgets_are_the_controller_values_in_one_place():
    assert cr_guard.BUDGETS == {"guard_inner_deadline_s": 240, "cleanup_reserve_s": 45, "cr_timeout_s": 300,
                                "selector_baseline_target_s": 180, "batch_max": 24, "session_length_s": 3 * 3600,
                                "retry_cr_timeout_s": 600}
    assert cr_coord.BUDGETS is cr_guard.BUDGETS and cr_reconcile.BUDGETS is cr_guard.BUDGETS
    assert cr_guard.BUDGETS["guard_inner_deadline_s"] + cr_guard.BUDGETS["cleanup_reserve_s"] < \
        cr_guard.BUDGETS["cr_timeout_s"]


def _three(tmp_path):
    src = tmp_path / "src"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "m.py").write_text("X = 1\nY = 2\nZ = 3\n", encoding="utf-8")
    items = [dict(_item(j, r, 4), module_path="pkg/m.py") for j, r in (("j3", 3), ("j1", 1), ("j2", 2))]
    return src, items


def test_ordering_is_deterministic_and_batches_partition_exactly(tmp_path):
    _, items = _three(tmp_path)
    shuffled = items[:]
    random.Random(7).shuffle(shuffled)
    assert [i["job_id"] for i in cr_coord.order_items(items)] == ["j1", "j2", "j3"]
    assert cr_coord.order_items(shuffled) == cr_coord.order_items(items)
    batches = cr_coord.plan_batches(["j1", "j2", "j3"], size=2)
    assert batches == [["j1", "j2"], ["j3"]]
    cr_coord.check_partition(["j1", "j2", "j3"], batches)
    with pytest.raises(cr_coord.PartitionError, match=r"lost: \['j3'\]"):
        cr_coord.check_partition(["j1", "j2", "j3"], [["j1", "j2"]])
    with pytest.raises(cr_coord.PartitionError, match=r"duplicated: \['j2'\]"):
        cr_coord.check_partition(["j1", "j2", "j3"], [["j1", "j2"], ["j2", "j3"]])
    with pytest.raises(cr_coord.PartitionError, match=r"batch size 25 exceeds the 24 cap"):
        cr_coord.plan_batches([f"x{i}" for i in range(30)], size=25)


@pytest.mark.parametrize("bad", ["cleanup_uncertain", "timeout"])
def test_coordinator_quarantines_and_stops_with_pending_preserved(tmp_path, bad):
    src, items = _three(tmp_path)
    by_id = {i["job_id"]: i for i in items}
    calls = []

    def seam(item, copy_root, job_dir):              # stub CR exec: no real Cosmic Ray in the logic test
        calls.append((item["job_id"], copy_root))
        assert (copy_root / "pkg" / "m.py").read_bytes() == (src / "pkg" / "m.py").read_bytes()
        status = "killed" if item["job_id"] == "j1" else bad
        return {"guard_status": status, "raw_timeout": False, "exec_status": "ok",
                "cleanup_verified": status != "cleanup_uncertain", "label": status}
    work = tmp_path / "work"
    st = cr_coord.run_batch(["j1", "j2", "j3"], by_id, batch_id="b000", src_root=src, copy_paths=["pkg"],
                            work_root=work,
                            exec_seam=seam)
    assert [c[0] for c in calls] == ["j1", "j2"], "j3 never started"
    assert calls[0][1] != calls[1][1], "a fresh disposable copy per WorkItem"
    assert (st.get("done"), st.get("quarantined"), st.get("pending")) == (["j1"], ["j2"], ["j3"])
    assert st.get("stopped") is True and st.get("stop_reason", "").startswith(bad)
    assert sorted(st["done"] + st["quarantined"] + st["pending"]) == ["j1", "j2", "j3"]
    assert (work / "quarantine" / "j2").is_dir() and not calls[1][1].exists()
    assert not (work / "copies" / "j3").exists()
    assert (work / "batch_b000_state.json").is_file(), "per-batch state file"
    assert json.loads((work / "batch_b000_state.json").read_text(encoding="utf-8")) == st


# ------------------------------------------------------------------------------------- end-to-end, real Cosmic Ray
E2E_MOD = 'def is_missing(x):\n    return x is None\n\n\ndef label(flag):\n    return "on" if flag else "off"\n'
E2E_TEST = ("from mod_e2e import is_missing\n\n\ndef test_is_missing():\n    assert is_missing(None) is True\n"
            "    assert is_missing(0) is False\n")


def test_end_to_end_real_cosmic_ray_with_guard_and_reconciler(tmp_path):
    t0 = time.monotonic()
    src = project(tmp_path / "src", {"mod_e2e.py": E2E_MOD, "test_e2e.py": E2E_TEST})
    before = sha(src / "mod_e2e.py")                  # (bytes as written on this OS: CRLF on Windows)
    ctl = control(tmp_path / "control.json", ["test_e2e.py::test_is_missing"])
    cfg = cr_coord.CRConfig(python=PY, module_rel="mod_e2e.py", guard_args=["--control", ctl, "test_e2e.py"],
                            pythonpath_rel=["."], target_module="mod_e2e")
    work = tmp_path / "work"
    items = cr_coord.inventory(src, ["mod_e2e.py", "test_e2e.py", "pytest.ini"], cfg, work)
    assert sorted(i.get("operator") for i in items) == ["core/AddNot", "core/ReplaceComparisonOperator_Is_IsNot"]
    inv = work / "inventory.json"
    assert json.loads(inv.read_text(encoding="utf-8")).get("items") == items
    with pytest.raises(cr_coord.CoordError, match=r"inventory\.json already exists"):
        cr_coord.inventory(src, ["mod_e2e.py"], cfg, work)
    ordered = [i["job_id"] for i in cr_coord.order_items(items)]
    st = cr_coord.run_batch(ordered, {i["job_id"]: i for i in items}, batch_id="e2e", src_root=src,
                            copy_paths=["mod_e2e.py", "test_e2e.py", "pytest.ini"], work_root=work / "b0",
                            exec_seam=cr_coord.real_exec(cfg))
    op = {i["job_id"]: i["operator"] for i in items}
    labels = {op[j]: lab for j, lab in st.get("labels", {}).items()}
    assert labels == {"core/ReplaceComparisonOperator_Is_IsNot": "killed", "core/AddNot": "survived"}, st
    assert (st.get("stopped"), st.get("pending"), sorted(st.get("done", []))) == (False, [], sorted(ordered))
    for j in ordered:
        cls = json.loads((work / "b0" / "jobs" / j / "classification.json").read_text(encoding="utf-8"))
        (row,) = cls["items"]
        assert row["job_id"] == j and row["raw"]["test_outcome"] in ("killed", "survived")
        assert row["label"] == st["labels"][j]
        gj = json.loads((work / "b0" / "jobs" / j / "guard.json").read_text())
        assert gj["job_id"] == j
        imp = gj.get("imports", {}).get("mod_e2e", {})               # I4: the child imported the disposable copy
        assert imp.get("under_root") is True and Path(imp["file"]).resolve().parent == (work / "b0" / "copies" / j).resolve(), imp
        assert str(cr_coord.HARNESS_DIR) not in gj.get("pythonpath", [str(cr_coord.HARNESS_DIR)]), "worktree s1_tests"
    assert sha(src / "mod_e2e.py") == before, "the source tree is never mutated (only the disposable copies)"
    assert time.monotonic() - t0 < 120


# =============================================================================================== Fix round 1 (review)
# I1 (probe P4): stale artifacts in a job dir are never read; a child that dies with rc 1 writing nothing is no kill.
def test_stale_artifacts_in_the_job_dir_never_give_killed(tmp_path, monkeypatch):
    ctl = control(tmp_path / "ctl.json", ["test_a.py::test_ok", "test_a.py::test_bad"])
    rc1, g1 = guard(monkeypatch, project(tmp_path / "p1", GOOD_AND_BAD), tmp_path / "jobA",
                    ["--control", ctl, "test_a.py"])
    assert g1.get("status") == "killed"
    stale = tmp_path / "jobB"
    stale.mkdir()
    for f in (tmp_path / "jobA").rglob("*"):                     # every artifact of the killed run, minus guard.json
        if f.is_file() and f.name in ("junit.xml", "nodes.json", "cleanup.json"):
            (stale / f.name).write_bytes(f.read_bytes())
    dead = project(tmp_path / "p2", {"test_a.py": "import os\n\ndef test_ok():\n    os._exit(1)\n\n\n"
                                                  "def test_bad():\n    pass\n"})
    rc2, g2 = guard(monkeypatch, dead, stale, ["--control", ctl, "test_a.py"])
    assert (rc2, g2.get("status"), g2.get("rc")) == (0, "crash", 1)


# M2 (probe P2): a strict XPASS fails the call phase without any exception; it is not an assertion failure.
def test_strict_xpass_is_not_killed(tmp_path, monkeypatch):
    src = "import pytest\n\n@pytest.mark.xfail(strict=True, reason='r')\ndef test_x():\n    assert True\n"
    proj = project(tmp_path / "p", {"test_x.py": src})
    rc, g = guard(monkeypatch, proj, tmp_path / "job",
                  ["--control", control(tmp_path / "c.json", ["test_x.py::test_x"]), "test_x.py"])
    assert (rc, g.get("status")) == (0, "error:xpass_strict")


# I4: the target module must be imported from under the copy root (the guard's cwd), never from elsewhere.
def test_target_module_imported_from_outside_the_copy_is_refused(tmp_path, monkeypatch):
    outside = tmp_path / "worktree"
    outside.mkdir()
    (outside / "tmod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    test_src = "import tmod\n\n\ndef test_f():\n    assert tmod.f() == 2\n"
    ctl = control(tmp_path / "c.json", ["test_t.py::test_f"])
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(outside), os.environ.get("PYTHONPATH", "")]))
    broken = project(tmp_path / "copy_missing_target", {"test_t.py": test_src})          # tmod.py NOT in the copy
    rc, g = guard(monkeypatch, broken, tmp_path / "job1", ["--control", ctl, "--target", "tmod", "test_t.py"])
    assert (rc, g.get("status")) == (0, "error:import_not_from_copy")
    assert g.get("imports", {}).get("tmod", {}).get("under_root") is False
    good = project(tmp_path / "copy_ok", {"test_t.py": test_src, "tmod.py": "def f():\n    return 1\n"})
    rc, g = guard(monkeypatch, good, tmp_path / "job2", ["--control", ctl, "--target", "tmod", "test_t.py"])
    assert (rc, g.get("status")) == (1, "killed")
    assert g.get("imports", {}).get("tmod", {}).get("under_root") is True


# I5 (probe P5): a descendant outliving a NORMAL pytest exit is terminated and verified dead.
STRAY = ("import subprocess, sys, time\nfrom pathlib import Path\n\n"
         "def test_spawn_and_pass():\n    here = Path(__file__).resolve().parent\n"
         "    subprocess.Popen([sys.executable, str(here / 'sleeper.py'), str(here / 'gc_real.pid')])\n"
         "    for _ in range(100):\n"
         "        if (here / 'gc_real.pid').exists() and (here / 'gc_real.pid').read_text():\n"
         "            break\n        time.sleep(0.1)\n    time.sleep(1)\n")


def test_stray_descendant_after_a_normal_exit_is_terminated_and_verified(tmp_path, monkeypatch):
    proj = project(tmp_path / "p", {"test_s.py": STRAY, "sleeper.py": SLEEPER})
    held, stop = {}, threading.Event()

    def watch():
        while not stop.is_set():
            f = proj / "gc_real.pid"
            if not held and f.exists() and f.read_text().strip():
                held["gc"] = (int(f.read_text()), _hold(int(f.read_text())))
            time.sleep(0.05)
    t = threading.Thread(target=watch, daemon=True)
    t.start()
    try:
        rc, g = guard(monkeypatch, proj, tmp_path / "job",
                      ["--control", control(tmp_path / "c.json", ["test_s.py::test_spawn_and_pass"]), "test_s.py"])
    finally:
        stop.set()
        t.join(5)
    assert (rc, g.get("status")) == (0, "survived")
    c = g.get("cleanup", {})
    assert c.get("stray_after_exit", 0) >= 1 and c.get("terminated") is True and c.get("verified") is True, c
    pid, h = held["gc"]
    try:
        assert h and _K32.WaitForSingleObject(h, 0) == 0, f"stray grandchild {pid} alive"
    finally:
        _K32.CloseHandle(h)


# M7: a job PID list that does not fit is never silently empty; it is reported, conservatively.
def test_pid_list_overflow_is_cleanup_uncertain(tmp_path, monkeypatch):
    monkeypatch.setattr(cr_guard, "_PID_LIST_CAP", 1, raising=False)
    proj = project(tmp_path / "p", {"test_o.py": "def test_ok():\n    assert True\n"})
    rc, g = guard(monkeypatch, proj, tmp_path / "job",
                  ["--control", control(tmp_path / "c.json", ["test_o.py::test_ok"]), "test_o.py"])
    assert (rc, g.get("status")) == (0, "cleanup_uncertain")
    assert g.get("cleanup", {}).get("pid_list_overflow") is True


# M7: a PID read from the job list but reused by a foreign process before OpenProcess is never held as a member.
def test_open_member_refuses_a_process_outside_the_job():
    job = cr_guard._new_job()
    try:
        assert getattr(cr_guard, "_open_member", lambda pid, job: -1)(os.getpid(), job) == 0
    finally:
        cr_guard._k32.CloseHandle(job)


# Nit: a guard option given twice is a usage error, not "last one wins".
def test_duplicate_guard_option_is_a_usage_error(tmp_path, monkeypatch):
    proj = project(tmp_path / "p", GOOD_AND_BAD)
    rc, g = guard(monkeypatch, proj, tmp_path / "job", ["--deadline", "30", "--deadline", "60", "test_a.py"])
    assert rc == 0 and str(g.get("status")).startswith("error:usage:duplicate --deadline"), g.get("status")


# M1 / M4 / M5: the pure classifier, pinned around one valid kill.
def _killed_inputs():
    run = {"timed_out": False, "rc": 1, "cleanup": {"verified": True}}
    junit = {"tests": 2, "failures": 1, "errors": 0, "skipped": 0, "case_failures": 1, "case_errors": 0,
             "case_skipped": 0, "cases": 2, "ids": [["test_a", "test_ok"], ["test_a", "test_bad"]]}
    rec = {"selected": ["test_a.py::test_ok", "test_a.py::test_bad"], "xfail": [], "collect_errors": [],
           "internal_error": False, "exitstatus": 1, "imports": {},
           "phases": {"test_a.py::test_ok": {"setup": "passed", "call": "passed", "teardown": "passed"},
                      "test_a.py::test_bad": {"setup": "passed", "call": "failed", "teardown": "passed"}},
           "call_exc": {"test_a.py::test_bad": "AssertionError"}}
    return run, junit, rec, ["test_a.py::test_ok", "test_a.py::test_bad"]


def test_classifier_pins_precedence_and_consistency_rules():
    run, junit, rec, ctl = _killed_inputs()
    assert cr_guard.classify(run=run, junit=junit, rec=rec, control=ctl)[0] == "killed"
    st = cr_guard.classify(run={"timed_out": True, "rc": None, "cleanup": {"verified": False}}, junit=None, rec=None,
                           control=ctl)[0]
    assert st == "cleanup_uncertain", "M1: unverified cleanup outranks timeout"
    assert cr_guard.classify(run={"timed_out": True, "rc": None, "cleanup": {"verified": True}}, junit=None,
                             rec=None, control=ctl)[0] == "timeout"
    _, _, r2, _ = _killed_inputs()
    r2["exitstatus"] = 0
    assert cr_guard.classify(run=run, junit=junit, rec=r2, control=ctl)[0] == "error:plugin_record", "M4: rc pinned"
    _, j2, _, _ = _killed_inputs()
    j2["ids"] = [["test_a", "test_bad"], ["test_a", "test_bad"]]
    assert cr_guard.classify(run=run, junit=j2, rec=rec, control=ctl)[0] == "error:junit_node_mismatch", "M5"
    _, j3, _, _ = _killed_inputs()
    j3["ids"] = [["test_a", "test_ok"], ["test_a", "test_other"]]
    assert cr_guard.classify(run=run, junit=j3, rec=rec, control=ctl)[0] == "error:junit_node_mismatch", "M5"


# I2 (probe P7): a STOPPED batch blocks the work_root until a recorded resolution; its state is never overwritten.
def _stub(bad_ids, how="timeout", calls=None):
    def seam(item, copy_root, job_dir):
        if calls is not None:
            calls.append(item["job_id"])
        bad = item["job_id"] in bad_ids
        return {"guard_status": how if bad else "killed", "raw_timeout": False, "exec_status": "ok",
                "cleanup_verified": True, "label": how if bad else "killed"}
    return seam


def test_stopped_batch_blocks_the_work_root_until_resolved(tmp_path):
    src, items = _three(tmp_path)
    by_id = {i["job_id"]: i for i in items}
    work = tmp_path / "w"
    st0 = cr_coord.run_batch(["j1", "j2"], by_id, batch_id="b000", src_root=src, copy_paths=["pkg"],
                             work_root=work, exec_seam=_stub({"j2"}))
    assert st0.get("stopped") is True
    state0 = work / "batch_b000_state.json"
    assert state0.is_file(), "per-batch state file"
    before = sha(state0)
    calls = []
    with pytest.raises(cr_coord.CoordError, match=r"batch b000 STOPPED .*unresolved"):
        cr_coord.run_batch(["j3"], by_id, batch_id="b001", src_root=src, copy_paths=["pkg"], work_root=work,
                           exec_seam=_stub(set(), calls=calls))
    assert calls == [] and sha(state0) == before
    assert json.loads(state0.read_text(encoding="utf-8"))["labels"] == {"j1": "killed", "j2": "timeout"}
    cr_coord.resolve_stop(work, "b000", by="controller", note="j2 timeout queued for the 600 s retry")
    assert json.loads((work / "batch_b000_resolution.json").read_text(encoding="utf-8"))["by"] == "controller"
    st1 = cr_coord.run_batch(["j3"], by_id, batch_id="b001", src_root=src, copy_paths=["pkg"], work_root=work,
                             exec_seam=_stub(set(), calls=calls))
    assert st1.get("done") == ["j3"] and sha(state0) == before
    with pytest.raises(cr_coord.CoordError, match=r"batch_b000_state\.json already exists"):
        cr_coord.run_batch(["j3"], by_id, batch_id="b000", src_root=src, copy_paths=["pkg"], work_root=work,
                           exec_seam=_stub(set()))


# I5: run_retry is one separate recorded session with the retry budgets; initial labels are kept, never rewritten.
def test_run_retry_is_one_separate_session_keeping_the_initial_label(tmp_path):
    src, items = _three(tmp_path)
    by_id = {i["job_id"]: i for i in items}
    work = tmp_path / "w"
    cr_coord.run_batch(["j1", "j2"], by_id, batch_id="b000", src_root=src, copy_paths=["pkg"], work_root=work,
                       exec_seam=_stub({"j2"}))
    state0 = work / "batch_b000_state.json"
    assert state0.is_file(), "per-batch state file"
    before = sha(state0)
    seen = []

    def factory(cfg):
        seen.append(cfg)
        return _stub(set())
    cfg = cr_coord.CRConfig(python=PY, module_rel="pkg/m.py", guard_args=["t.py"], target_module="pkg.m")
    st = cr_coord.run_retry("j2", by_id, cfg, src_root=src, copy_paths=["pkg"], work_root=work, exec_factory=factory)
    assert [(c.timeout_s, c.guard_deadline_s) for c in seen] == [(600, 540)]
    assert st.get("labels") == {"j2": "killed"} and st.get("done") == ["j2"]
    assert st.get("initial_labels") == [{"batch": "b000", "label": "timeout"}]
    assert st.get("eligibility") == {"timeout_batch": "b000", "basis": "own_timeout_stop"}, st.get("eligibility")
    assert (work / "retries" / "j2" / "batch_retry_state.json").is_file() and sha(state0) == before
    with pytest.raises(cr_coord.CoordError, match=r"j2 was already retried"):
        cr_coord.run_retry("j2", by_id, cfg, src_root=src, copy_paths=["pkg"], work_root=work, exec_factory=factory)


# I5: the session budget spans every batch in a work_root (persisted start), not each run_batch call.
def test_session_budget_spans_batches(tmp_path):
    src, items = _three(tmp_path)
    by_id = {i["job_id"]: i for i in items}
    work, now = tmp_path / "w", [1000.0]

    def clock():
        return now[0]
    cr_coord.run_batch(["j1"], by_id, batch_id="b000", src_root=src, copy_paths=["pkg"], work_root=work,
                       exec_seam=_stub(set()), clock=clock)
    assert (work / "session.json").is_file(), "session start persisted"
    assert json.loads((work / "session.json").read_text(encoding="utf-8")).get("started") == 1000.0
    now[0] = 1000.0 + cr_guard.BUDGETS["session_length_s"] - 100
    calls = []
    st = cr_coord.run_batch(["j2", "j3"], by_id, batch_id="b001", src_root=src, copy_paths=["pkg"], work_root=work,
                            exec_seam=_stub(set(), calls=calls), clock=clock)
    assert calls == [] and st.get("stopped") is True and str(st.get("stop_reason")).startswith("session_budget")
    assert st.get("pending") == ["j2", "j3"] and st.get("done") == []


# I5: manifests tie a batch to the exact inventory bytes; run_manifest refuses a changed inventory.
def test_write_manifests_and_run_manifest_bind_the_inventory(tmp_path):
    src, items = _three(tmp_path)
    work = tmp_path / "w"
    work.mkdir()
    inv = work / "inventory.json"
    inv.write_text(json.dumps({"module_rel": "pkg/m.py", "source_sha256": sha(src / "pkg" / "m.py"),
                               "items": cr_coord.order_items(items)}), encoding="utf-8")
    paths = cr_coord.write_manifests(work, [["j1", "j2"], ["j3"]], sha(inv))
    assert [p.name for p in paths] == ["batch_000.json", "batch_001.json"]
    assert json.loads(paths[0].read_text(encoding="utf-8"))["items"] == ["j1", "j2"]
    with pytest.raises(cr_coord.CoordError, match=r"batch_000\.json already exists"):
        cr_coord.write_manifests(work, [["j1"]], sha(inv))
    assert hasattr(cr_coord, "run_manifest"), "run_manifest exists"
    st = cr_coord.run_manifest(paths[0], inv, src_root=src, copy_paths=["pkg"], work_root=work,
                               exec_seam=_stub(set()))
    assert st.get("done") == ["j1", "j2"] and st.get("manifest_sha256") == sha(paths[0])
    assert st.get("inventory_sha256") == sha(inv)
    inv.write_text(inv.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(cr_coord.CoordError, match=r"inventory sha256 .* does not match the manifest"):
        cr_coord.run_manifest(paths[1], inv, src_root=src, copy_paths=["pkg"], work_root=work,
                              exec_seam=_stub(set()))


# I5: the harness_drift / source_drift / exec_exception stops quarantine the copy and keep the rest pending.
@pytest.mark.parametrize("kind", ["harness_drift", "source_drift", "exec_exception"])
def test_drift_and_exception_stops(tmp_path, kind):
    src, items = _three(tmp_path)
    by_id = {i["job_id"]: i for i in items}
    expected = {"pkg/m.py": sha(src / "pkg" / "m.py")}
    if kind == "harness_drift":
        (src / "pkg" / "cr_guard.py").write_text("# not the reviewed guard\n", encoding="utf-8")
    if kind == "source_drift":
        expected = {"pkg/m.py": "0" * 64}

    def seam(item, copy_root, job_dir):
        if kind == "exec_exception":
            raise OSError("launcher vanished")
        return {"guard_status": "killed", "raw_timeout": False, "exec_status": "ok", "cleanup_verified": True,
                "label": "killed"}
    work = tmp_path / "w"
    st = cr_coord.run_batch(["j1", "j2"], by_id, batch_id="b000", src_root=src, copy_paths=["pkg"], work_root=work,
                            exec_seam=seam, source_sha256=expected)
    assert st.get("stopped") is True and str(st.get("stop_reason")).startswith(kind), st.get("stop_reason")
    assert (st.get("quarantined"), st.get("pending"), st.get("done")) == (["j1"], ["j2"], [])
    assert (work / "quarantine" / "j1").is_dir()


# M6: an unknown item or an already-existing copy dir writes a stop record before raising.
def test_unknown_item_and_existing_copy_write_a_stop_record(tmp_path):
    src, items = _three(tmp_path)
    by_id = {i["job_id"]: i for i in items}
    work = tmp_path / "w"
    with pytest.raises((cr_coord.CoordError, KeyError), match=r"zz") as ei:
        cr_coord.run_batch(["zz"], by_id, batch_id="b000", src_root=src, copy_paths=["pkg"], work_root=work,
                           exec_seam=_stub(set()))
    assert isinstance(ei.value, cr_coord.CoordError) and "unknown item zz" in str(ei.value), repr(ei.value)
    assert (work / "batch_b000_state.json").is_file(), "stop record written"
    s = json.loads((work / "batch_b000_state.json").read_text(encoding="utf-8"))
    assert s.get("stopped") is True and s.get("stop_reason") == "unknown_item: zz" and s.get("pending") == ["zz"]
    work2 = tmp_path / "w2"
    (work2 / "copies" / "j1").mkdir(parents=True)
    with pytest.raises(cr_coord.CoordError, match=r"already exists"):
        cr_coord.run_batch(["j1"], by_id, batch_id="b000", src_root=src, copy_paths=["pkg"], work_root=work2,
                           exec_seam=_stub(set()))
    assert (work2 / "batch_b000_state.json").is_file(), "stop record written"
    s2 = json.loads((work2 / "batch_b000_state.json").read_text(encoding="utf-8"))
    assert s2.get("stopped") is True and s2.get("stop_reason") == "copy_exists: j1" and s2.get("pending") == ["j1"]


# I4: the coordinator refuses a config without a target module (it cannot prove import identity otherwise).
def test_config_without_a_target_module_is_refused():
    cfg = cr_coord.CRConfig(python=PY, module_rel="m.py", guard_args=["t.py"])
    with pytest.raises(cr_coord.CoordError, match=r"target_module is required"):
        cr_coord.test_command(cfg)


# I5: cr-report through cr_launch.py, a real call on a tiny synthetic session.
def test_cr_report_through_the_launcher(tmp_path):
    import subprocess
    db = tmp_path / "s.sqlite"
    _session(db, {"a": ("normal", "killed", _out("a")), "b": ("normal", "survived", _out("b", "survived", 0)),
                  "c": None})
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([str(PY), str(HARNESS / "cr_launch.py"), "cr-report", str(db)], capture_output=True,
                       text=True, timeout=120, env=env, cwd=tmp_path)
    assert p.returncode == 0, p.stderr
    assert "total jobs: 3" in p.stdout and "complete: 2" in p.stdout, p.stdout
    bad = subprocess.run([str(PY), str(HARNESS / "cr_launch.py"), "cr-html", str(db)], capture_output=True,
                         text=True, timeout=120, env=env, cwd=tmp_path)
    assert bad.returncode == 2 and "must be one of" in bad.stderr


# =============================================================================================== Fix round 2 (re-review)
def _labelled(labels: dict):
    """Stub seam returning a given reconciled label per job (guard status consistent with it)."""
    status = {"killed": "killed", "survived": "survived", "timeout": "timeout", "error": "error:collection",
              "cleanup_uncertain": "cleanup_uncertain"}

    def seam(item, copy_root, job_dir):
        lab = labels.get(item["job_id"], "killed")
        return {"guard_status": status[lab], "raw_timeout": False, "exec_status": "ok",
                "cleanup_verified": lab != "cleanup_uncertain", "label": lab}
    return seam


def _retry(work, src, by_id, job):
    cfg = cr_coord.CRConfig(python=PY, module_rel="pkg/m.py", guard_args=["t.py"], target_module="pkg.m")
    return cr_coord.run_retry(job, by_id, cfg, src_root=src, copy_paths=["pkg"], work_root=work,
                              exec_factory=lambda c: _stub(set()))


# R1-I1: only a job whose initial reconciled label is timeout may be retried, and only when its batch's stop is that
# job's own timeout stop or has a recorded resolution; any other unresolved stop/interruption in the work_root refuses.
@pytest.mark.parametrize("case", ["killed", "survived", "cleanup_uncertain", "error", "other_unresolved_stop",
                                  "unknown_job"])
def test_retry_is_refused_unless_the_job_is_an_eligible_timeout(tmp_path, case):
    src, items = _three(tmp_path)
    by_id = {i["job_id"]: i for i in items}
    work = tmp_path / "w"
    if case in ("killed", "survived", "cleanup_uncertain", "error"):
        cr_coord.run_batch(["j1"], by_id, batch_id="b000", src_root=src, copy_paths=["pkg"], work_root=work,
                           exec_seam=_labelled({"j1": case}))
        job, pattern = "j1", rf"j1 is not retry-eligible: initial labels \['{case}'\]"
    elif case == "other_unresolved_stop":
        cr_coord.run_batch(["j1"], by_id, batch_id="b000", src_root=src, copy_paths=["pkg"], work_root=work,
                           exec_seam=_labelled({"j1": "timeout"}))
        cr_coord.resolve_stop(work, "b000", by="controller", note="j1 queued for retry")
        cr_coord.run_batch(["j2"], by_id, batch_id="b001", src_root=src, copy_paths=["pkg"], work_root=work,
                           exec_seam=_labelled({"j2": "cleanup_uncertain"}))
        job, pattern = "j1", r"j1 is not retry-eligible: batch b001 STOPPED \(cleanup_uncertain: j2\) is unresolved"
    else:
        job, pattern = "zz", r"unknown job zz"
    with pytest.raises(cr_coord.CoordError, match=pattern):
        _retry(work, src, by_id, job)
    assert not (work / "retries" / job).exists(), "nothing was run or recorded for a refused retry"


# R1-I1 positive (basis "resolved"): a timeout whose batch stop was resolved is retried; the history is kept.
def test_retry_of_a_resolved_timeout_runs_and_keeps_the_initial_label(tmp_path):
    src, items = _three(tmp_path)
    by_id = {i["job_id"]: i for i in items}
    work = tmp_path / "w"
    cr_coord.run_batch(["j1", "j2"], by_id, batch_id="b000", src_root=src, copy_paths=["pkg"], work_root=work,
                       exec_seam=_labelled({"j2": "timeout"}))
    res = cr_coord.resolve_stop(work, "b000", by="controller", note="timeout -> one 600 s retry")
    st = _retry(work, src, by_id, "j2")
    assert st.get("done") == ["j2"] and st.get("labels") == {"j2": "killed"}
    assert st.get("initial_labels") == [{"batch": "b000", "label": "timeout"}]
    assert st.get("eligibility") == {"timeout_batch": "b000", "basis": "resolved", "resolution_sha256": sha(res)}


# R1-M1 (probe P10): a batch interrupted mid-item (not stopped, pending left, copy left) blocks the next batch until a
# resolution is recorded.
class _CoordinatorDied(BaseException):
    """Stands in for the coordinator process dying mid-exec (not an Exception, so run_batch cannot record it)."""


def test_interrupted_batch_blocks_the_next_until_resolved(tmp_path):
    src, items = _three(tmp_path)
    by_id = {i["job_id"]: i for i in items}
    work = tmp_path / "w"

    def dying(item, copy_root, job_dir):
        raise _CoordinatorDied("coordinator killed mid-exec")
    with pytest.raises(_CoordinatorDied, match=r"coordinator killed mid-exec"):
        cr_coord.run_batch(["j1", "j2"], by_id, batch_id="b000", src_root=src, copy_paths=["pkg"], work_root=work,
                           exec_seam=dying)
    s0 = json.loads((work / "batch_b000_state.json").read_text(encoding="utf-8"))
    assert (s0["stopped"], s0["pending"], (work / "copies" / "j1").exists()) == (False, ["j1", "j2"], True)
    calls = []
    with pytest.raises(cr_coord.CoordError, match=r"batch b000 INTERRUPTED .*unresolved"):
        cr_coord.run_batch(["j3"], by_id, batch_id="b001", src_root=src, copy_paths=["pkg"], work_root=work,
                           exec_seam=_stub(set(), calls=calls))
    assert calls == []
    cr_coord.resolve_stop(work, "b000", by="controller", note="coordinator died; copy j1 inspected")
    st = cr_coord.run_batch(["j3"], by_id, batch_id="b001", src_root=src, copy_paths=["pkg"], work_root=work,
                            exec_seam=_stub(set(), calls=calls))
    assert st.get("done") == ["j3"] and calls == ["j3"]


# R1-N1: junit_id is pytest's own mangling (params may contain '::'; illegal XML chars are bin_xml_escape'd).
def test_junit_id_models_param_colons_and_xml_escapes():
    assert cr_guard.junit_id("pkg/t.py::C::test_x[a::b]") == ["pkg.t.C", "test_x[a::b]"]
    assert cr_guard.junit_id("t.py::test_x[a\x07b]") == ["t", "test_x[a#x07b]"]
    assert cr_guard.junit_id("t.py::test_y") == ["t", "test_y"]


def test_junit_ids_unmodelled_is_refused_explicitly(monkeypatch):
    run, junit, rec, ctl = _killed_inputs()
    monkeypatch.setattr(cr_guard, "_junit_model", lambda: None, raising=False)
    assert cr_guard.classify(run=run, junit=junit, rec=rec, control=ctl)[0] == "error:junit_node_unmodelled"


PARAM_IDS = ("import pytest\n\n\n@pytest.mark.parametrize('v', ['a::b', '<&>\"q\"', 'x[y]'], ids=lambda v: v)\n"
             "def test_p(v):\n    assert v != 'x[y]'\n")


def test_real_run_with_awkward_param_ids_is_not_a_false_mismatch(tmp_path, monkeypatch):
    proj = project(tmp_path / "p", {"test_p.py": PARAM_IDS})
    nodes = ["test_p.py::test_p[a::b]", 'test_p.py::test_p[<&>"q"]', "test_p.py::test_p[x[y]]"]
    rc, g = guard(monkeypatch, proj, tmp_path / "job", ["--control", control(tmp_path / "c.json", nodes),
                                                        "test_p.py"])
    assert (rc, g.get("status")) == (1, "killed"), g.get("status")


# R1-N2: a module_rel naming a harness file (or anything under .cr_harness) is refused.
@pytest.mark.parametrize("rel", ["research/s1/s1_tests/cr_guard.py", "cr_reconcile.py", "cr_coord.py",
                                 "tools/cr_launch.py", "research/s1/s1_tests/conftest.py",
                                 "copy/.cr_harness/anything.py"])
def test_module_rel_naming_a_harness_file_is_refused(rel):
    cfg = cr_coord.CRConfig(python=PY, module_rel=rel, guard_args=["t.py"], target_module="m")
    with pytest.raises(cr_coord.CoordError, match=r"names a harness file"):
        cr_coord.test_command(cfg)


# R1-N3: the attempt id comes first on the guard line, so a status with spaces cannot break the binding.
def test_attempt_binding_survives_spaces_in_the_status(tmp_path, monkeypatch, capsys):
    line = "cr_guard: attempt=ab12 exit=0 status=error:usage:duplicate --deadline sidecar=C:/a b/guard.json"
    assert cr_reconcile.guard_attempt(line) == "ab12"
    assert cr_reconcile.guard_attempt("noise\n" + line + "\n") == "ab12"
    assert cr_reconcile.guard_attempt(line + "\n" + line) is None, "two guard runs in one output: unbound"
    proj = project(tmp_path / "p", GOOD_AND_BAD)
    capsys.readouterr()
    rc, g = guard(monkeypatch, proj, tmp_path / "job", ["--deadline", "30", "--deadline", "60", "test_a.py"])
    out = capsys.readouterr().out
    assert " " in g["status"] and cr_reconcile.guard_attempt(out) == g["attempt"], (g["status"], out)


# =============================================================================================== Fix round 3 (re-review 2)
# R2-M1 (probe P13): a retry's own unresolved stop (here cleanup_uncertain) blocks the next ORIGINAL batch until it is
# resolved in its retry root.
def test_unresolved_retry_stop_blocks_the_next_original_batch(tmp_path):
    src, items = _three(tmp_path)
    by_id = {i["job_id"]: i for i in items}
    work = tmp_path / "w"
    cr_coord.run_batch(["j1", "j2"], by_id, batch_id="b000", src_root=src, copy_paths=["pkg"], work_root=work,
                       exec_seam=_labelled({"j2": "timeout"}))
    cr_coord.resolve_stop(work, "b000", by="controller", note="j2 timeout -> one retry")
    cfg = cr_coord.CRConfig(python=PY, module_rel="pkg/m.py", guard_args=["t.py"], target_module="pkg.m")
    st = cr_coord.run_retry("j2", by_id, cfg, src_root=src, copy_paths=["pkg"], work_root=work,
                            exec_factory=lambda c: _labelled({"j2": "cleanup_uncertain"}))
    assert (st.get("stopped"), st.get("stop_reason")) == (True, "cleanup_uncertain: j2")
    calls = []
    with pytest.raises(cr_coord.CoordError, match=r"retry of j2 \(batch retry\) STOPPED \(cleanup_uncertain: j2\) "
                                                  r"and is unresolved"):
        cr_coord.run_batch(["j3"], by_id, batch_id="b001", src_root=src, copy_paths=["pkg"], work_root=work,
                           exec_seam=_stub(set(), calls=calls))
    assert calls == []
    cr_coord.resolve_stop(work / "retries" / "j2", "retry", by="controller", note="retry cleanup reviewed")
    nxt = cr_coord.run_batch(["j3"], by_id, batch_id="b001", src_root=src, copy_paths=["pkg"], work_root=work,
                             exec_seam=_stub(set(), calls=calls))
    assert nxt.get("done") == ["j3"] and calls == ["j3"]


# R2-M2 (probe P16): a timeout-labelled job whose batch stopped on cleanup_uncertain (raw CR timeout, outer cleanup
# unverified) is refused for retry until its stop is resolved; after resolve_stop the retry runs (basis "resolved").
def test_timeout_label_with_a_cleanup_uncertain_stop_needs_a_resolution_before_retry(tmp_path):
    src, items = _three(tmp_path)
    by_id = {i["job_id"]: i for i in items}
    work = tmp_path / "w"

    def seam(item, copy_root, job_dir):
        if item["job_id"] == "j2":
            return {"guard_status": None, "raw_timeout": True, "exec_status": "timeout", "cleanup_verified": False,
                    "label": "timeout"}
        return {"guard_status": "killed", "raw_timeout": False, "exec_status": "ok", "cleanup_verified": True,
                "label": "killed"}
    st0 = cr_coord.run_batch(["j1", "j2"], by_id, batch_id="b000", src_root=src, copy_paths=["pkg"],
                             work_root=work, exec_seam=seam)
    assert (st0["stop_reason"], st0["labels"]["j2"]) == ("cleanup_uncertain: j2", "timeout")
    with pytest.raises(cr_coord.CoordError, match=r"j2 is not retry-eligible: batch b000 STOPPED "
                                                  r"\(cleanup_uncertain: j2\) is neither j2's own timeout stop nor "
                                                  r"resolved"):
        _retry(work, src, by_id, "j2")
    assert not (work / "retries" / "j2").exists()
    res = cr_coord.resolve_stop(work, "b000", by="controller", note="j2 cleanup reviewed: tree gone")
    st = _retry(work, src, by_id, "j2")
    assert st.get("done") == ["j2"]
    assert st.get("eligibility") == {"timeout_batch": "b000", "basis": "resolved", "resolution_sha256": sha(res)}
