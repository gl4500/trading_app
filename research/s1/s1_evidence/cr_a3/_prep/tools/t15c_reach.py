"""T15c-prep coverage-free reach recorder (pytest plugin, ``-p t15c_reach``): which functions of ONE module each
selected test reaches (setup + call + teardown), via Python 3.12 ``sys.monitoring`` PY_START events (no coverage
package, no sys.settrace). Inert unless T15C_REACH_MODULE and T15C_REACH_OUT are set.

Per test: events are re-armed (restart_events) at the start of the test; the first PY_START of a code object whose
co_filename is the target module's file records its qualname (``a.<locals>.b`` -> ``a.b``) and DISABLEs that
location; any other code object is DISABLEd at its first start. Limitation (recorded in the output): code run in a
CHILD process (subprocess / multiprocessing) is not observed, and module-level statements run at import, not per test.
"""
import json
import os
import sys
from pathlib import Path

import pytest

_MOD, _OUT = os.environ.get("T15C_REACH_MODULE"), os.environ.get("T15C_REACH_OUT")
_S = {"tool": None, "file": None, "current": None, "hits": None, "per_test": {}, "collection_hits": None}


def _norm(q: str) -> str:
    return ".".join(p for p in q.split(".") if p != "<locals>")


def _on_start(code, offset):
    mon = sys.monitoring
    if _S["file"] is not None and os.path.normcase(code.co_filename) == _S["file"]:
        if _S["hits"] is not None:
            _S["hits"].add(_norm(code.co_qualname))
        if _S["current"] is not None:
            return mon.DISABLE           # recorded for this test; re-armed by restart_events at the next test
        return None
    return mon.DISABLE


def pytest_collection_finish(session):
    if not (_MOD and _OUT):
        return
    import importlib
    mod = sys.modules.get(_MOD) or importlib.import_module(_MOD)
    _S["file"] = os.path.normcase(os.path.abspath(mod.__file__))
    _S["mod_file"] = mod.__file__
    mon = sys.monitoring
    for tid in (3, 4, 5, 2, 1):
        try:
            mon.use_tool_id(tid, "t15c_reach")
        except ValueError:
            continue
        _S["tool"] = tid
        break
    if _S["tool"] is None:
        raise RuntimeError("t15c_reach: no free sys.monitoring tool id")
    mon.register_callback(_S["tool"], mon.events.PY_START, _on_start)
    mon.set_events(_S["tool"], mon.events.PY_START)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    if _S["tool"] is None:
        yield
        return
    _S["hits"], _S["current"] = set(), item.nodeid
    sys.monitoring.restart_events()
    try:
        yield
    finally:
        _S["per_test"][item.nodeid] = sorted(_S["hits"])
        _S["hits"], _S["current"] = None, None


def pytest_sessionfinish(session, exitstatus):
    if _S["tool"] is None:
        return
    sys.monitoring.set_events(_S["tool"], 0)
    sys.monitoring.free_tool_id(_S["tool"])
    Path(_OUT).write_text(json.dumps({"module": _MOD, "module_file": _S.get("mod_file"), "exitstatus": int(exitstatus),
                                      "per_test": _S["per_test"],
                                      "limitations": ["child-process execution is not observed",
                                                      "module-level statements run at import, not per test"]},
                                     indent=1, sort_keys=True), encoding="utf-8")
