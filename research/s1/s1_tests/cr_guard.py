"""A3 Task 15a (Task 15 Step 3b, controller ruling R2): the Cosmic Ray test-command guard.

Cosmic Ray 8.3.15 labels ANY nonzero test-command exit, and a TimeoutExpired, as "killed" (cosmic_ray/testing.py).
So each cr.toml runs ``<testenv python> -m cr_guard [guard options] <pytest targets...>`` instead of bare pytest. The
guard runs ONE child pytest (with --junitxml and this module loaded as a recording plugin) inside a Win32 Job Object,
and exits:

* 1  ONLY when status == "killed": at least one testcase has a <failure>, there is no <error> anywhere, no collection /
     setup / teardown / plugin / internal error, no skip or xfail in the selected set, the selected node set equals the
     declared control set (``--control``), the JUnit testcase ids equal the recorded node ids, every ``--target``
     module was imported from under the cwd (the disposable copy), every failure carries an exception (a strict
     XPASS does not), pytest exited 1, and the process tree was cleaned up and verified;
* 0  in every other case, with the precise non-kill status in the per-job sidecar ``guard.json``: "survived",
     "error:<why>" (collection, setup, teardown, junit_error, pytest_exit_N, plugin_record, junit_node_mismatch,
     import_not_from_copy, xpass_strict, no_control, usage:..., ...), "empty", "skip", "node_set_mismatch", "crash",
     "timeout", "cleanup_uncertain" (outranks timeout), "control:ok", "control:invalid:<why>".

The sidecar directory comes from the env var CR_GUARD_JOB_DIR (unset -> refuse: exit 0, status "error:no_job_dir",
printed to stdout because there is nowhere to write a sidecar). CR_GUARD_JOB_ID, if set, is copied into the sidecar so
the reconciler can match it to the WorkItem. Every run gets a fresh attempt id; all of its artifacts (junit.xml,
nodes.json, stdout/stderr, cleanup.json, basetemp, Hypothesis home) live in ``<job dir>/attempt-<id>/`` and nothing
else in the job dir is ever read (fix round 1, I1). The plugin record carries the attempt id, and the guard's stdout
line (which Cosmic Ray stores as the result output) names it, so the reconciler binds result to attempt (M3).

Guard options (they must come before the pytest arguments; ``--`` ends them explicitly; each at most once, except
``--target``):
  --control FILE        JSON {"nodes": [...]}: the declared control node set; required for a "killed" verdict.
  --write-control FILE  baseline mode: on a clean all-pass run, write the selected node set to FILE ("control:ok").
  --deadline SECONDS    inner deadline (default BUDGETS["guard_inner_deadline_s"]).
  --target MODULE       (repeatable) a module that must be imported from under the cwd, i.e. the disposable copy.

Containment (required on Windows): the child is created CREATE_SUSPENDED, assigned to a fresh Job Object with
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (no breakaway allowed), verified in the job with IsProcessInJob, and only then
resumed. The venv python.exe is a launcher whose real interpreter is its child; that child, and every descendant, is
born inside the job. At the deadline (or when pytest exits leaving descendants) the guard calls TerminateJobObject,
then verifies ActiveProcesses == 0 and that every member it ever sampled is signalled, within the cleanup reserve.
Unverifiable -> "cleanup_uncertain" (which stops the coordinator's batch). The guard never touches a process outside
its own job: a PID read from the job list is only held after IsProcessInJob confirms the opened handle is a member
(PID reuse), and a PID list longer than _PID_LIST_CAP is reported as pid_list_overflow (cleanup unverified).
If the guard itself dies, closing the job handle kills the tree (KILL_ON_JOB_CLOSE).

Part of the mutation harness: excluded from every mutation inventory and hashed separately (t15a_hashes.txt).
"""
import ctypes
import datetime as _dt
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from ctypes import wintypes
from pathlib import Path

import pytest

# ------------------------------------------------------------------------------------------- budgets (R4/R5, one place)
# Controller rulings R4/R5. These are the ONLY literals for these budgets; cr_coord and cr_reconcile import this dict.
BUDGETS = {
    "guard_inner_deadline_s": 240,      # guard kills its pytest tree at this point
    "cleanup_reserve_s": 45,            # time allowed after the deadline to terminate + verify the tree
    "cr_timeout_s": 300,                # Cosmic Ray's own per-item timeout (cr.toml `timeout`)
    "selector_baseline_target_s": 180,  # an unmutated selector should finish within this
    "batch_max": 24,                    # at most this many candidates per batch
    "session_length_s": 3 * 3600,       # wall allocation per session
    "retry_cr_timeout_s": 600,          # the single retry, in a separately recorded one-item session
}

JOB_DIR_ENV, JOB_ID_ENV, NODES_ENV = "CR_GUARD_JOB_DIR", "CR_GUARD_JOB_ID", "CR_GUARD_NODES_OUT"
ATTEMPT_ENV, TARGETS_ENV = "CR_GUARD_ATTEMPT", "CR_GUARD_TARGETS"
SCHEMA = "a3-t15a-guard/1"
_SAMPLE_S = 0.2


# ---------------------------------------------------------------------------------------------- Win32 job objects
_k32 = ctypes.WinDLL("kernel32", use_last_error=True) if os.name == "nt" else None

CREATE_SUSPENDED = 0x00000004
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectBasicAccountingInformation, JobObjectBasicProcessIdList, JobObjectExtendedLimitInformation = 1, 3, 9
TH32CS_SNAPPROCESS, TH32CS_SNAPTHREAD = 0x2, 0x4
THREAD_SUSPEND_RESUME = 0x0002
SYNCHRONIZE, PROCESS_QUERY_LIMITED_INFORMATION = 0x00100000, 0x1000
WAIT_OBJECT_0 = 0
ERROR_MORE_DATA = 234
_PID_LIST_CAP = 1024                     # job PID-list capacity; a longer list is reported, never truncated silently
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value


class _IoCounters(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                  "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _BasicLimit(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]


class _ExtendedLimit(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimit), ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


class _Accounting(ctypes.Structure):
    _fields_ = [("TotalUserTime", ctypes.c_int64), ("TotalKernelTime", ctypes.c_int64),
                ("ThisPeriodTotalUserTime", ctypes.c_int64), ("ThisPeriodTotalKernelTime", ctypes.c_int64),
                ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD),
                ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD)]


class _ThreadEntry(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ThreadID", wintypes.DWORD),
                ("th32OwnerProcessID", wintypes.DWORD), ("tpBasePri", wintypes.LONG), ("tpDeltaPri", wintypes.LONG),
                ("dwFlags", wintypes.DWORD)]


class _ProcessEntry(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]


if _k32 is not None:
    _H, _D, _B = wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL
    for _name, _res, _args in (
            ("CreateJobObjectW", _H, (ctypes.c_void_p, wintypes.LPCWSTR)),
            ("SetInformationJobObject", _B, (_H, ctypes.c_int, ctypes.c_void_p, _D)),
            ("QueryInformationJobObject", _B, (_H, ctypes.c_int, ctypes.c_void_p, _D, ctypes.POINTER(_D))),
            ("AssignProcessToJobObject", _B, (_H, _H)),
            ("IsProcessInJob", _B, (_H, _H, ctypes.POINTER(_B))),
            ("TerminateJobObject", _B, (_H, ctypes.c_uint)),
            ("TerminateProcess", _B, (_H, ctypes.c_uint)),
            ("CloseHandle", _B, (_H,)),
            ("CreateToolhelp32Snapshot", _H, (_D, _D)),
            ("Thread32First", _B, (_H, ctypes.POINTER(_ThreadEntry))),
            ("Thread32Next", _B, (_H, ctypes.POINTER(_ThreadEntry))),
            ("Process32FirstW", _B, (_H, ctypes.POINTER(_ProcessEntry))),
            ("Process32NextW", _B, (_H, ctypes.POINTER(_ProcessEntry))),
            ("OpenThread", _H, (_D, _B, _D)),
            ("ResumeThread", _D, (_H,)),
            ("OpenProcess", _H, (_D, _B, _D)),
            ("WaitForSingleObject", _D, (_H, _D))):
        _fn = getattr(_k32, _name)
        _fn.restype, _fn.argtypes = _res, _args


class ContainmentError(RuntimeError):
    """The child could not be placed in (or verified in) a fresh Job Object; nothing is run uncontained."""


def _check(ok, what):
    if not ok:
        raise ContainmentError(f"{what} failed (winerror {ctypes.get_last_error()})")
    return ok


def _new_job():
    job = _check(_k32.CreateJobObjectW(None, None), "CreateJobObjectW")
    info = _ExtendedLimit()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE      # no BREAKAWAY_OK: none can leave
    _check(_k32.SetInformationJobObject(job, JobObjectExtendedLimitInformation, ctypes.byref(info),
                                        ctypes.sizeof(info)), "SetInformationJobObject")
    return job


def _job_pids(job) -> tuple[list[int], bool]:
    """(member pids, complete). ``complete`` is False when the list did not fit in _PID_LIST_CAP entries or could
    not be read at all; the caller then reports the cleanup as unverifiable instead of trusting a short list."""
    class _List(ctypes.Structure):
        _fields_ = [("NumberOfAssignedProcesses", wintypes.DWORD), ("NumberOfProcessIdsInList", wintypes.DWORD),
                    ("ProcessIdList", ctypes.c_size_t * max(1, int(_PID_LIST_CAP)))]
    lst = _List()
    ok = _k32.QueryInformationJobObject(job, JobObjectBasicProcessIdList, ctypes.byref(lst), ctypes.sizeof(lst),
                                        None)
    if not ok and ctypes.get_last_error() != ERROR_MORE_DATA:
        return [], False
    n = min(int(lst.NumberOfProcessIdsInList), max(1, int(_PID_LIST_CAP)))
    pids = [int(lst.ProcessIdList[i]) for i in range(n)]
    return pids, bool(ok) and int(lst.NumberOfAssignedProcesses) <= n


def _open_member(pid: int, job) -> int:
    """A SYNCHRONIZE handle on ``pid`` ONLY if that process is in ``job`` (else 0). A PID read from the job list can
    be reused by a foreign process before OpenProcess; the IsProcessInJob check on the opened handle rules that out,
    so a foreign process is never held, recorded as a member, or counted as a survivor."""
    h = _k32.OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return 0
    inside = wintypes.BOOL(False)
    if _k32.IsProcessInJob(h, job, ctypes.byref(inside)) and inside.value:
        return int(h)
    _k32.CloseHandle(h)
    return 0


def _job_active(job) -> int | None:
    acc = _Accounting()
    if not _k32.QueryInformationJobObject(job, JobObjectBasicAccountingInformation, ctypes.byref(acc),
                                          ctypes.sizeof(acc), None):
        return None
    return int(acc.ActiveProcesses)


def _resume_all_threads(pid: int) -> int:
    snap = _k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if not snap or snap == INVALID_HANDLE_VALUE:
        raise ContainmentError(f"CreateToolhelp32Snapshot(threads) failed (winerror {ctypes.get_last_error()})")
    resumed = 0
    try:
        te = _ThreadEntry()
        te.dwSize = ctypes.sizeof(te)
        ok = _k32.Thread32First(snap, ctypes.byref(te))
        while ok:
            if te.th32OwnerProcessID == pid:
                th = _k32.OpenThread(THREAD_SUSPEND_RESUME, False, te.th32ThreadID)
                if th:
                    if _k32.ResumeThread(th) != 0xFFFFFFFF:
                        resumed += 1
                    _k32.CloseHandle(th)
            ok = _k32.Thread32Next(snap, ctypes.byref(te))
    finally:
        _k32.CloseHandle(snap)
    return resumed


def _parents(pids) -> dict:
    """{pid: (ppid, exe)} for the given pids from one process snapshot (recording only)."""
    want, out = set(pids), {}
    snap = _k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID_HANDLE_VALUE:
        return out
    try:
        pe = _ProcessEntry()
        pe.dwSize = ctypes.sizeof(pe)
        ok = _k32.Process32FirstW(snap, ctypes.byref(pe))
        while ok:
            if pe.th32ProcessID in want:
                out[int(pe.th32ProcessID)] = (int(pe.th32ParentProcessID), pe.szExeFile)
            ok = _k32.Process32NextW(snap, ctypes.byref(pe))
    finally:
        _k32.CloseHandle(snap)
    return out


def run_contained(cmd, *, cwd, env, stdout_path: Path, stderr_path: Path, deadline_s: float,
                  cleanup_s: float = BUDGETS["cleanup_reserve_s"]) -> dict:
    """Run ``cmd`` inside a fresh kill-on-close Job Object; kill the WHOLE tree at ``deadline_s``.

    Returns {"rc", "timed_out", "elapsed_s", "holder_pids", "cleanup"}. ``cleanup`` = {"method", "terminated",
    "active_after", "survivors", "verified", "stray_after_exit"}. Raises ContainmentError (after killing the one
    process it just created) when the child cannot be placed in the job; nothing then runs uncontained."""
    if _k32 is None:
        raise ContainmentError("Win32 Job Object containment is required and is only available on Windows")
    t0 = time.monotonic()
    job = _new_job()
    held: dict[int, int] = {}                                      # pid -> our SYNCHRONIZE handle (pins the object)
    try:
        with open(stdout_path, "wb") as out, open(stderr_path, "wb") as err:
            proc = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                    creationflags=CREATE_SUSPENDED)
        if not hasattr(proc, "_handle"):                           # CPython-private; refuse rather than guess
            proc.kill()                                            # public API on the one suspended process we made
            proc.wait()
            raise ContainmentError(f"subprocess.Popen has no _handle on this Python ({sys.version.split()[0]})")
        hproc = int(proc._handle)                                  # noqa: SLF001 - the Popen-owned process handle
        try:
            _check(_k32.AssignProcessToJobObject(job, hproc), "AssignProcessToJobObject")
            inside = wintypes.BOOL(False)
            _check(_k32.IsProcessInJob(hproc, job, ctypes.byref(inside)), "IsProcessInJob")
            if not inside.value:
                raise ContainmentError("child is not in the job after AssignProcessToJobObject")
            if _resume_all_threads(proc.pid) < 1:
                raise ContainmentError("no thread of the suspended child could be resumed")
        except ContainmentError:
            _k32.TerminateProcess(hproc, 1)                         # the one process we just created, still suspended
            proc.wait()
            raise

        info: dict = {}                                            # pid -> (ppid, exe), taken while alive
        overflow = [False]

        def sample():
            new = []
            pids, complete = _job_pids(job)
            overflow[0] = overflow[0] or not complete
            for pid in pids:
                if pid not in held:
                    h = _open_member(pid, job)
                    held[pid] = int(h or 0)
                    new.append(pid)
            if new:
                info.update(_parents(new))
        timed_out, rc = False, None
        while True:
            sample()
            left = deadline_s - (time.monotonic() - t0)
            if left <= 0:
                timed_out = True
                break
            try:
                rc = proc.wait(timeout=min(_SAMPLE_S, left))
                break
            except subprocess.TimeoutExpired:
                continue
        sample()
        stray = _job_active(job)
        cleanup = {"method": "win32-job-object(kill_on_job_close, terminate_job_object)", "terminated": False,
                   "stray_after_exit": 0 if timed_out else (stray or 0)}
        if timed_out or stray:                                     # deadline, or descendants outliving pytest
            sample()
            cleanup["terminated"] = bool(_k32.TerminateJobObject(job, 1))
        verify_until = time.monotonic() + cleanup_s
        active = _job_active(job)
        while active and time.monotonic() < verify_until:
            time.sleep(0.05)
            active = _job_active(job)
        # ActiveProcesses can reach 0 a moment before each process object is signalled: wait on every held handle
        # too (bounded by the same cleanup reserve). A handle pins its process object, so PID reuse cannot fool this.
        survivors = []
        for pid, h in held.items():
            if h:
                ms = int(max(0.0, verify_until - time.monotonic()) * 1000)
                if _k32.WaitForSingleObject(h, ms) != WAIT_OBJECT_0:
                    survivors.append(pid)
        unheld = [pid for pid, h in held.items() if not h]
        try:
            proc_rc = proc.wait(timeout=max(0.1, verify_until - time.monotonic()))
        except subprocess.TimeoutExpired:
            proc_rc = None
        rc = None if timed_out else (rc if rc is not None else proc_rc)
        cleanup.update(active_after=active, survivors=survivors, unheld_members=unheld, pid_list_overflow=overflow[0],
                       verified=(active == 0 and not survivors and proc_rc is not None and not overflow[0]))

        holders = [{"pid": pid, "ppid": info.get(pid, (None, None))[0], "exe": info.get(pid, (None, None))[1],
                    "held": bool(held[pid]), "role": "launcher" if pid == proc.pid else "descendant"}
                   for pid in sorted(held)]
        return {"rc": rc, "timed_out": timed_out, "elapsed_s": round(time.monotonic() - t0, 3),
                "launcher_pid": proc.pid, "holder_pids": holders, "cleanup": cleanup}
    finally:
        for h in held.values():
            if h:
                _k32.CloseHandle(h)
        _k32.CloseHandle(job)                                      # KILL_ON_JOB_CLOSE: nothing in it outlives this


# ------------------------------------------------------------------------------------------- pytest recording plugin
# Loaded into the CHILD pytest with ``-p cr_guard``; inert unless CR_GUARD_NODES_OUT is set there. The record carries
# this attempt's id (CR_GUARD_ATTEMPT), so a node record from any other run can never be mistaken for this one.
_REC: dict | None = None


def pytest_configure(config):
    global _REC
    if os.environ.get(NODES_ENV):
        _REC = {"attempt": os.environ.get(ATTEMPT_ENV), "selected": None, "phases": {}, "xfail": [],
                "collect_errors": [], "internal_error": False, "exitstatus": None, "call_exc": {}, "imports": {}}


@pytest.hookimpl(trylast=True)                   # after any -k/-m deselection
def pytest_collection_modifyitems(session, config, items):
    if _REC is not None:
        _REC["selected"] = [it.nodeid for it in items]


def pytest_collectreport(report):
    if _REC is not None and report.failed:
        _REC["collect_errors"].append({"nodeid": report.nodeid, "longrepr": str(report.longrepr)[:4000]})


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    if _REC is not None and call.when == "call":
        rep = outcome.get_result()
        if rep.failed:                           # None = failed without an exception (e.g. a strict XPASS)
            _REC["call_exc"][item.nodeid] = call.excinfo.typename if call.excinfo is not None else None


def pytest_runtest_logreport(report):
    if _REC is not None:
        _REC["phases"].setdefault(report.nodeid, {})[report.when] = report.outcome
        if hasattr(report, "wasxfail"):
            _REC["xfail"].append(report.nodeid)


def pytest_internalerror(excrepr, excinfo):
    if _REC is not None:
        _REC["internal_error"] = True


def pytest_sessionfinish(session, exitstatus):
    if _REC is not None:
        _REC["exitstatus"] = int(exitstatus)
        for name in [t for t in os.environ.get(TARGETS_ENV, "").split(",") if t]:
            mod = sys.modules.get(name)
            _REC["imports"][name] = getattr(mod, "__file__", None) if mod is not None else None
        Path(os.environ[NODES_ENV]).write_text(json.dumps(_REC, indent=1, sort_keys=True), encoding="utf-8")


# --------------------------------------------------------------------------------------------------- classification
def _sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _junit(path: Path) -> dict | None:
    """Counts, per-testcase (classname, name) ids and outcomes from the JUnit XML; None when missing/unparsable."""
    if not path.is_file():
        return None
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return None
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    c = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for s in suites:
        for k in c:
            c[k] += int(s.get(k, 0))
    cases = list(root.iter("testcase"))
    c["case_failures"] = sum(1 for tc in cases if tc.find("failure") is not None)
    c["case_errors"] = sum(1 for tc in cases if tc.find("error") is not None)
    c["case_skipped"] = sum(1 for tc in cases if tc.find("skipped") is not None)
    c["cases"] = len(cases)
    c["ids"] = [[tc.get("classname", ""), tc.get("name", "")] for tc in cases]
    return c


def _junit_model():
    """(mangle_test_address, bin_xml_escape) from the INSTALLED pytest's junitxml - the exact functions that wrote the
    XML (record_testreport: classname = '.'.join(names[:-1]), name = bin_xml_escape(names[-1]); the guard never sets
    --junitprefix). None if they are not importable: the guard then refuses (error:junit_node_unmodelled) rather
    than compare against a guess."""
    try:
        from _pytest.junitxml import bin_xml_escape, mangle_test_address
    except ImportError:
        return None
    return mangle_test_address, bin_xml_escape


def junit_id(nodeid: str) -> list | None:
    """[classname, name] exactly as pytest's junitxml writes it for ``nodeid`` (params split off before '::', so a
    param id containing '::' stays in the name; illegal XML characters escaped as '#xNN'). None when unmodelled."""
    model = _junit_model()
    if model is None:
        return None
    mangle, escape = model
    names = mangle(nodeid)
    return [".".join(names[:-1]), escape(names[-1])]


def _under(path: str | None, root: str | None) -> bool:
    if not path or not root:
        return False
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def classify(*, run: dict, junit: dict | None, rec: dict | None, control: list | None,
             targets: list | None = None, root: str | None = None) -> tuple[str, dict]:
    """The R2 contract as a pure function. Returns (status, detail). Only "killed" leads to exit 1. Order matters:
    an unverifiable cleanup outranks everything (M1), then timeout, crash and every error class, then the node-set,
    import-identity and failure checks."""
    if not run["cleanup"]["verified"]:
        return "cleanup_uncertain", {}
    if run["timed_out"]:
        return "timeout", {}
    rc = run["rc"]
    if rc is None or rc < 0 or rc > 5:
        return "crash", {}
    if rec is not None and rec.get("collect_errors"):
        return "error:collection", {}
    if rc in (2, 3, 4):
        return f"error:pytest_exit_{rc}", {}
    if junit is None:
        return "crash", {}
    if rec is None or rec.get("selected") is None or rec.get("exitstatus") != rc:
        return "error:plugin_record", {}
    if rec["internal_error"]:
        return "error:internal", {}
    phases = rec["phases"]
    if any(ph.get("setup") == "failed" for ph in phases.values()):
        return "error:setup", {}
    if any(ph.get("teardown") == "failed" for ph in phases.values()):
        return "error:teardown", {}
    if junit["errors"] or junit["case_errors"]:
        return "error:junit_error", {}
    selected = rec["selected"]
    if len(set(selected)) != len(selected):
        return "error:duplicate_node_ids", {}
    if not selected or junit["cases"] == 0 or rc == 5:
        return "empty", {}
    skipped = sorted({n for n, ph in phases.items() if "skipped" in ph.values()} | set(rec["xfail"]))
    if skipped or junit["skipped"] or junit["case_skipped"]:
        return "skip", {"skipped": skipped}
    if set(phases) != set(selected):
        return "error:selected_not_run", {"not_run": sorted(set(selected) - set(phases))}
    if _junit_model() is None:
        return "error:junit_node_unmodelled", {}
    ids = junit.get("ids")
    if ids is None or sorted(map(tuple, ids)) != sorted(tuple(junit_id(n)) for n in selected):
        return "error:junit_node_mismatch", {}
    if control is not None and set(control) != set(selected):
        return "node_set_mismatch", {"node_set": {"missing": sorted(set(control) - set(selected)),
                                                  "extra": sorted(set(selected) - set(control))}}
    if targets:
        imports = rec.get("imports") or {}
        if not all(_under(imports.get(t), root) for t in targets):
            return "error:import_not_from_copy", {}
    failed = sorted(n for n, ph in phases.items() if ph.get("call") == "failed")
    call_exc = rec.get("call_exc") or {}
    if failed or junit["failures"] or junit["case_failures"]:
        if not (failed and junit["case_failures"] == len(failed) and rc == 1):
            return "error:inconsistent_failure_record", {"failed": failed}
        if any(call_exc.get(n) is None for n in failed):
            return "error:xpass_strict", {"failed": failed}
        if control is None:
            return "error:no_control", {"failed": failed}
        return "killed", {"failed": failed}
    if rc != 0:
        return "error:rc_without_failure", {}
    return "survived", {}


_OPTS = {"--control": "control", "--write-control": "write_control", "--deadline": "deadline", "--target": "target"}


def _parse(argv):
    opts, rest = {"control": None, "write_control": None, "deadline": None, "target": []}, list(argv)
    while rest and rest[0] in _OPTS:
        if len(rest) < 2:
            raise ValueError(f"{rest[0]} needs a value")
        key = _OPTS[rest[0]]
        if key == "target":
            opts["target"].append(rest[1])
        elif opts[key] is not None:
            raise ValueError(f"duplicate {rest[0]}")
        else:
            opts[key] = rest[1]
        rest = rest[2:]
    if rest and rest[0] == "--":
        rest = rest[1:]
    if opts["control"] and opts["write_control"]:
        raise ValueError("--control and --write-control are exclusive")
    return opts, rest


def main(argv) -> int:
    argv = [str(a) for a in argv]
    job = os.environ.get(JOB_DIR_ENV, "").strip()
    if not job:
        print(json.dumps({"schema": SCHEMA, "status": "error:no_job_dir", "exit_code": 0,
                          "why": f"{JOB_DIR_ENV} is not set; refusing to run (no sidecar can be written)"}))
        return 0
    job_dir = Path(job)
    job_dir.mkdir(parents=True, exist_ok=True)
    side_path = job_dir / "guard.json"
    attempt = uuid.uuid4().hex
    started = _dt.datetime.now(_dt.timezone.utc).isoformat()
    side = {"schema": SCHEMA, "job_id": os.environ.get(JOB_ID_ENV), "attempt": attempt, "argv": argv,
            "started": started, "guard_sha256": _sha(Path(__file__)), "cwd": os.getcwd(), "python": sys.executable}

    def finish(status, code=0, **extra):
        side.update(extra, status=status, exit_code=code,
                    finished=_dt.datetime.now(_dt.timezone.utc).isoformat())
        side_path.write_text(json.dumps(side, indent=1, sort_keys=True), encoding="utf-8")
        print(f"cr_guard: attempt={attempt} exit={code} status={status} sidecar={side_path}")   # attempt first (R1-N3)
        return code

    if side_path.exists():                       # one guard run per job dir; never overwrite earlier evidence
        print(json.dumps({"schema": SCHEMA, "status": "error:job_dir_not_fresh", "exit_code": 0}))
        return 0
    # I1: every artifact of THIS run lives in a fresh per-attempt dir; nothing already in job_dir is ever read.
    att = job_dir / f"attempt-{attempt}"
    att.mkdir()
    side["attempt_dir"] = str(att)
    try:
        opts, tests = _parse(argv)
        deadline = float(opts["deadline"]) if opts["deadline"] else float(BUDGETS["guard_inner_deadline_s"])
        if deadline <= 0:
            raise ValueError("deadline must be positive")
    except ValueError as exc:
        return finish(f"error:usage:{exc}")
    side["deadline_s"] = int(deadline) if deadline == int(deadline) else deadline
    control = None
    if opts["control"]:
        try:
            control = json.loads(Path(opts["control"]).read_text(encoding="utf-8"))["nodes"]
            side["control_sha256"] = _sha(Path(opts["control"]))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return finish(f"error:control_unreadable:{type(exc).__name__}")
    if not tests:
        return finish("error:no_targets")

    junit, nodes_out = att / "junit.xml", att / "nodes.json"
    hyp, base = att / "hypothesis", att / "basetemp"
    hyp.mkdir()
    here = str(Path(__file__).resolve().parent)
    env = dict(os.environ)
    env.update(PYTHONDONTWRITEBYTECODE="1", S1_HYPOTHESIS_ROOT=str(hyp),
               **{NODES_ENV: str(nodes_out), ATTEMPT_ENV: attempt, TARGETS_ENV: ",".join(opts["target"])})
    env["PYTHONPATH"] = os.pathsep.join([p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p] + [here])
    side["pythonpath"] = [p for p in env["PYTHONPATH"].split(os.pathsep) if p]
    cmd = [sys.executable, "-m", "pytest", "-p", "cr_guard", "-p", "no:cacheprovider", "-q", "-rA",
           f"--junitxml={junit}", f"--basetemp={base}", *tests]
    side["pytest_cmd"] = cmd
    try:
        run = run_contained(cmd, cwd=os.getcwd(), env=env, stdout_path=att / "stdout.txt",
                            stderr_path=att / "stderr.txt", deadline_s=deadline)
    except (ContainmentError, OSError) as exc:
        return finish(f"error:containment:{exc}")
    (att / "cleanup.json").write_text(json.dumps(run["cleanup"], indent=1, sort_keys=True), encoding="utf-8")
    jx = _junit(junit)
    try:
        rec = json.loads(nodes_out.read_text(encoding="utf-8")) if nodes_out.is_file() else None
    except ValueError:
        rec = None
    if rec is not None and rec.get("attempt") != attempt:
        rec = None                               # a record from another run is no record of this one
    root = os.getcwd()
    imports = {t: {"file": (rec or {}).get("imports", {}).get(t),
                   "under_root": _under((rec or {}).get("imports", {}).get(t), root)} for t in opts["target"]}
    if opts["write_control"]:
        status, detail = classify(run=run, junit=jx, rec=rec, control=None, targets=opts["target"], root=root)
        if status == "survived":
            Path(opts["write_control"]).write_text(json.dumps({"nodes": sorted(rec["selected"])}), encoding="utf-8")
            status = "control:ok"
        else:
            status = f"control:invalid:{status}"
    else:
        status, detail = classify(run=run, junit=jx, rec=rec, control=control, targets=opts["target"], root=root)
    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0} if jx is None else \
        {k: jx[k] for k in ("tests", "failures", "errors", "skipped")}
    counts["passed"] = counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"]
    return finish(status, 1 if status == "killed" else 0, rc=run["rc"], counts=counts,
                  nodes=(rec or {}).get("selected") or [], collect_errors=(rec or {}).get("collect_errors", []),
                  skipped=detail.get("skipped", []), failed=detail.get("failed", []),
                  failed_types={n: (rec or {}).get("call_exc", {}).get(n) for n in detail.get("failed", [])},
                  node_set=detail.get("node_set"), imports=imports, elapsed_s=run["elapsed_s"],
                  launcher_pid=run["launcher_pid"], holder_pids=run["holder_pids"], cleanup=run["cleanup"],
                  junit_sha256=_sha(junit), nodes_record_sha256=_sha(nodes_out), control=control)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
