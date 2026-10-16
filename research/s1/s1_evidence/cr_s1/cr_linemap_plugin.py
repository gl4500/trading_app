"""pytest plugin (Task 9 round 2): records which TESTS (pytest node ids) execute each line of the S1 modules (sys.monitoring LINE
events, Python 3.12; no third-party coverage package). Loaded with `-p cr_linemap_plugin` from a temp copy of the
sources; writes the map to the path in env S1_LINEMAP_OUT as {module: {line: [node ids]}}."""
import json
import os
import sys
from pathlib import Path

import pytest

TOOL = sys.monitoring.COVERAGE_ID
MODULES = ("s1_books.py", "s1_seal.py", "s1_checkpoint.py", "s1_run.py")
_hits = {}                  # (module, line) -> set(node id)
_current = [None]


def _line(code, line):
    name = os.path.basename(code.co_filename)
    if name in MODULES and _current[0] is not None:
        _hits.setdefault((name, line), set()).add(_current[0])
    return sys.monitoring.DISABLE           # once per (code, line) until restart_events() at the next test file


def pytest_configure(config):
    sys.monitoring.use_tool_id(TOOL, "s1_linemap")
    sys.monitoring.register_callback(TOOL, sys.monitoring.events.LINE, _line)
    sys.monitoring.set_events(TOOL, sys.monitoring.events.LINE)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    _current[0] = item.nodeid                   # set before fixtures run, so fixture code counts for this test
    sys.monitoring.restart_events()         # every test re-records (DISABLE is per test)


def pytest_unconfigure(config):
    sys.monitoring.set_events(TOOL, 0)
    out = {}
    for (m, ln), files in _hits.items():
        out.setdefault(m, {})[str(ln)] = sorted(files)
    Path(os.environ["S1_LINEMAP_OUT"]).write_text(json.dumps(out, indent=0, sort_keys=True), encoding="utf-8")
