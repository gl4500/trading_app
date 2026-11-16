
# ---- Task 15b fix round 3: structural crash provenance, recorded by the child itself (crash.json) ----
import json as _t15_json
import os as _t15_os
import pytest as _t15_pytest
_T15_CRASH = _t15_os.path.join(_t15_os.path.dirname(_t15_os.path.abspath(__file__)), "crash.json")
_T15_REC = {}


def _t15_loc(e):
    return None if e is None else {"path": e.frame.code.raw.co_filename, "line": e.lineno + 1}


@_t15_pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    yield
    ei = call.excinfo
    if ei is None:
        return
    tb = list(ei.traceback)
    # pytest's own visible crash (pytest 8.3.3 _pytest/_code/code.py:607-616 ExceptionInfo._getreprcrash: the last
    # entry with no __tracebackhide__, code.py:274 TracebackEntry.ishidden), so pytest.raises/pytest.fail land on
    # the visible oracle line (their helpers hide themselves: python_api.py:1009, outcomes.py:177)
    crash = ei._getreprcrash()
    term_loc = None if crash is None else {"path": crash.path, "line": crash.lineno}
    raw_type = f"{ei.type.__module__}.{ei.type.__qualname__}"
    # pytest's Failed sets __module__ = "builtins"; it is named by IDENTITY (never by a look-alike class's name)
    typ = "_pytest.outcomes.Failed" if ei.type is _t15_pytest.fail.Exception else raw_type
    _T15_REC.setdefault(item.nodeid, {})[call.when] = {
        "type": typ, "type_raw": raw_type, "terminal": term_loc,
        "innermost": _t15_loc(tb[-1] if tb else None)}
    with open(_T15_CRASH, "w", encoding="utf-8") as f:
        _t15_json.dump(_T15_REC, f, indent=1, sort_keys=True)
# ---- end of the recorder; the mutation text (if any) follows ----

import hashlib, importlib, inspect, json, os, textwrap
TARGET, OLD, NEW, EXTRA, RECORD = 's1_books._sold_events', '    s1_seal._live(px)\n    rs, events', '    rs, events', '', 'C:\\Users\\gl450\\AppData\\Local\\Temp\\claude\\4a6d95c7011f8258\\c661c7e7-0401-4122-9c4b-9345620dbebb\\scratchpad\\t15b\\bt_green5\\t15w0\\m21\\mutant\\installed.json'
mod_name, _, attr = TARGET.rpartition(".")
mod = importlib.import_module(mod_name)
obj = getattr(mod, attr)
rec = {"target": TARGET, "module_file": mod.__file__, "anchor_found": False, "installed": False}
if isinstance(obj, tuple):
    before = repr(obj)
    setattr(mod, attr, eval(NEW))
    after = repr(getattr(mod, attr))
    rec.update(anchor_found=(before == repr(eval(OLD))), installed=(before != after),
               original_sha256=hashlib.sha256(before.encode()).hexdigest(),
               mutated_sha256=hashlib.sha256(after.encode()).hexdigest())
else:
    lines, first = inspect.getsourcelines(obj)
    src = textwrap.dedent("".join(lines))
    rec["anchor_count"] = src.count(OLD)
    rec["anchor_found"] = rec["anchor_count"] == 1
    if rec["anchor_found"]:
        new_src = src.replace(OLD, NEW, 1)
        ns = vars(mod)                               # the module namespace itself: callers see the mutant
        exec(EXTRA, ns)
        exec(compile("\n" * (first - 1) + new_src, mod.__file__, "exec"), ns)
        rec.update(original_sha256=hashlib.sha256(src.encode()).hexdigest(),
                   mutated_sha256=hashlib.sha256(new_src.encode()).hexdigest(), first_line=first)
        rec["installed"] = rec["original_sha256"] != rec["mutated_sha256"] and getattr(mod, attr) is not obj
with open(RECORD, "w", encoding="utf-8") as f:
    json.dump(rec, f)
