
import hashlib, importlib, inspect, json, os, textwrap
TARGET, OLD, NEW, EXTRA, RECORD = 's1_trial.verify_ack', 'if probs:', 'if False:', '', 'C:\\Users\\gl450\\AppData\\Local\\Temp\\claude\\4a6d95c7011f8258\\c661c7e7-0401-4122-9c4b-9345620dbebb\\scratchpad\\t15b\\bt_green3\\t15w0\\m11\\mutant\\installed.json'
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
