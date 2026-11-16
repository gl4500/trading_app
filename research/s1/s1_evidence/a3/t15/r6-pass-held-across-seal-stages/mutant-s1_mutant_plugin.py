
import hashlib, importlib, inspect, json, os, textwrap
TARGET, OLD, NEW, EXTRA, RECORD = 's1_seal._decide_locked', '        for d in eligible_sessions(start, cal):                    # E2.5: the pending seal stages first\n            with seal_pass() as px:                                # A3 H5b: a fresh pass per close, never held\n                sealed = _close_state(px, index, d, cal)[0] == "sealed"     # across a seal-stage transaction\n            if sealed and s1_stage.stage_rows(rows, s1_slot.seal_stage_name(d["date"]))["created"] is None:\n                s1_slot.run_seal_stage(gv, d, cal, mailbox=mailbox, clock=now)', '        with seal_pass() as px:                                    # MUTANT (H5b review R-1): one pass held\n            for d in eligible_sessions(start, cal):                    # across every seal-stage transaction\n                sealed = _close_state(px, index, d, cal)[0] == "sealed"\n                if sealed and s1_stage.stage_rows(rows, s1_slot.seal_stage_name(d["date"]))["created"] is None:\n                    s1_slot.run_seal_stage(gv, d, cal, mailbox=mailbox, clock=now)', '', 'C:\\Users\\gl450\\AppData\\Local\\Temp\\claude\\4a6d95c7011f8258\\c661c7e7-0401-4122-9c4b-9345620dbebb\\scratchpad\\t15b\\bt_green3\\t15w0\\m27\\mutant\\installed.json'
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
