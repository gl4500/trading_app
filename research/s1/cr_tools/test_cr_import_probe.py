"""A3 Task 15c-P2: the import probe (research/s1/cr_tools/cr_import_probe.py), run BY PATH in REAL contained children
(cr_guard.run_contained) on SYNTHETIC toy packages under pytest tmp_path only. No S1 module is ever imported, mutated
or executed here: every target is a toy ``s1_x`` written by the test.
"""
import hashlib
import json
import os
from pathlib import Path

import pytest

import cr_coord
import cr_guard

PY = Path(os.sys.executable)
PROBE = Path(__file__).resolve().parent / "cr_import_probe.py"
MOD_REL = "research/s1/s1_x.py"
GENUINE = ("SLOT_KINDS = ('a', 'b')\nSTAGE_KINDS = ('c',)\nTRIAL_KINDS = ('d',)\n"
           "KINDS = SLOT_KINDS + STAGE_KINDS + TRIAL_KINDS                # F0.3\n")
GENUINE_SPEC = {"job_id": "c03580c0toy", "module_path": MOD_REL, "operator": "core/ReplaceBinaryOperator_Add_BitAnd",
                "operator_args": {}, "occurrence": 0, "start": [4, 19], "end": [4, 20]}


def sha(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def toy_copy(tmp_path, src: str, name="copy") -> Path:
    root = tmp_path / name
    (root / "research/s1/s1_tests").mkdir(parents=True)
    (root / MOD_REL).write_text(src, encoding="utf-8")
    return root


def cfg():
    return cr_coord.CRConfig(python=PY, module_rel=MOD_REL, target_module="s1_x",
                             pythonpath_rel=["research/s1", "research/s1/s1_tests"], guard_args=["x"])


def run_probe(tmp_path, copy_root: Path, mode: str, spec=None, *, tag=None, deadline_s=60.0, pin=None,
              protected=()):
    """Fix round 1: the parent hands the child the pinned source sha256 (--pin) and the protected paths
    (--protected; SYNTHETIC fixtures in every test - never the real mailbox, key or live DB)."""
    assert PROBE.is_file(), "the probe script cr_import_probe.py exists"
    tag = tag or mode
    d = tmp_path / f"dg_{tag}"
    d.mkdir()
    sp = d / "spec.json"
    sp.write_text(json.dumps(spec or GENUINE_SPEC), encoding="utf-8")
    out = d / "record.json"
    env = cr_coord._env(copy_root, cfg())
    env["S1_HYPOTHESIS_ROOT"] = str(d / "hypothesis")
    cmd = [str(PY), "-B", str(PROBE), "--mode", mode, "--copy-root", str(copy_root), "--module-rel", MOD_REL,
           "--target", "s1_x", "--spec", str(sp), "--scratch", str(d), "--out", str(out),
           "--pin", pin or sha(copy_root / MOD_REL)]
    for p in protected:
        cmd += ["--protected", str(p)]
    run = cr_guard.run_contained(cmd, cwd=copy_root, env=env, stdout_path=d / "stdout.txt",
                                 stderr_path=d / "stderr.txt", deadline_s=deadline_s)
    rec = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else None
    return run, rec, d


def innermost(rec):
    return rec["exception"]["frames"][-1]


# ------------------------------------------------------------------------------------- control and mutated modes
def test_P1_control_imports_the_unmutated_target_and_confirms_its_identity(tmp_path):
    root = toy_copy(tmp_path, GENUINE)
    run, rec, _ = run_probe(tmp_path, root, "control")
    assert run["rc"] == 0 and run["cleanup"]["verified"] is True and not run["timed_out"], run
    assert rec["mode"] == "control" and rec["imported"] is True, rec
    assert rec["imported_file"]["rel"] == MOD_REL and rec["imported_file"]["sha256"] == sha(root / MOD_REL)
    assert rec["source"]["pre_sha256"] == sha(root / MOD_REL) and rec["source"]["unchanged"] is True
    assert "mutation" not in rec, "control never applies the mutation"


def test_P3_the_genuine_shape_mutated_through_the_cr_api_fails_at_the_module_frame(tmp_path):
    """The c03580c0 shape on synthetic data: KINDS = A + B + C with tuples, first + -> &."""
    root = toy_copy(tmp_path, GENUINE)
    pre = sha(root / MOD_REL)
    run, rec, _ = run_probe(tmp_path, root, "mutated")
    assert run["rc"] == 0 and run["cleanup"]["verified"] is True, run
    m = rec["mutation"]
    assert m["applied"] is True and m["cr_original_equals_pre"] is True and m["post_text_equals_cr_mutated"] is True
    assert rec["source"]["pre_sha256"] == pre and m["post_sha256"] == sha(root / MOD_REL) != pre
    assert "-KINDS = SLOT_KINDS + STAGE_KINDS" in m["diff"] and "+KINDS = SLOT_KINDS & STAGE_KINDS" in m["diff"]
    assert rec["operator"]["name"] == "core/ReplaceBinaryOperator_Add_BitAnd", rec["operator"]
    assert rec["operator"]["class"].startswith("cosmic_ray.operators."), "the installed CR operator, not hand-written"
    assert rec["imported"] is False and rec["exception"]["qualname"] == "TypeError"
    assert rec["exception"]["module"] == "builtins"
    f = innermost(rec)
    assert f["rel"] == MOD_REL and f["co_name"] == "<module>" and f["co_qualname"] == "<module>", f
    assert f["file_sha256"] == m["post_sha256"] and f["co_flags"] & 0x3 == 0
    assert f["position"] == [4, 4, 8, 46] and f["positions_agree"] is True, f   # A & (B + C): & binds looser
    assert f["position_index"] == f["tb_lasti"] // 2


def test_P3_the_position_index_is_tb_lasti_over_two_including_inline_caches(tmp_path):
    """BINARY_SUBSCR and CALL carry inline CACHE entries in 3.12: the index tb_lasti // 2 must still name the
    failing instruction (cross-checked against dis)."""
    src = "def helper(x):\n    return x\n\n\nY = helper(1)\nZ = [1, 2][helper(5)]\n"
    root = toy_copy(tmp_path, src)
    _, rec, _ = run_probe(tmp_path, root, "control")
    f = innermost(rec)
    assert rec["exception"]["qualname"] == "IndexError"
    assert f["co_qualname"] == "<module>" and f["position"] == [6, 6, 4, 21] and f["positions_agree"] is True, f
    assert f["positions_count"] > f["position_index"] > 0


def test_P3_every_frame_is_recorded_with_structured_facts(tmp_path):
    src = "import os\nX = os.path.join(1)\n"
    root = toy_copy(tmp_path, src)
    _, rec, _ = run_probe(tmp_path, root, "control")
    frames = rec["exception"]["frames"]
    assert [fr["rel"] for fr in frames].count(MOD_REL) == 1, frames
    assert frames[-1]["rel"] is None and frames[-1]["co_name"] == "join", "a dependency frame is innermost"
    for fr in frames:
        assert set(fr) >= {"filename", "realpath", "rel", "file_sha256", "co_name", "co_qualname", "co_firstlineno",
                           "co_flags", "tb_lineno", "tb_lasti", "position", "dis_position", "positions_agree"}
    assert "rendered_secondary" in rec["exception"]


def test_P3_a_class_body_frame_and_a_runtime_method_frame_are_told_apart(tmp_path):
    src = ("A = (1,)\nB = (2,)\n\n\nclass K:\n    X = A + B\n\n    def m(self):\n        return A + B\n\n\n"
           "K().m()\n")
    spec = dict(GENUINE_SPEC, start=[6, 10], end=[6, 11])
    root = toy_copy(tmp_path, src)
    _, rec, _ = run_probe(tmp_path, root, "mutated", spec)
    f = innermost(rec)
    assert f["co_name"] == "K" and f["co_qualname"] == "K" and f["co_flags"] & 0x3 == 0, f
    root2 = toy_copy(tmp_path, src, "copy2")
    spec2 = dict(GENUINE_SPEC, occurrence=1, start=[9, 17], end=[9, 18])
    _, rec2, _ = run_probe(tmp_path, root2, "mutated", spec2, tag="m2")
    f2 = innermost(rec2)
    assert f2["co_qualname"] == "K.m" and f2["co_flags"] & 0x3 == 0x3, f2


def test_P3_mutation_not_installed_is_recorded_and_nothing_is_imported(tmp_path):
    root = toy_copy(tmp_path, GENUINE)
    _, rec, _ = run_probe(tmp_path, root, "mutated", dict(GENUINE_SPEC, occurrence=99))
    # fix round 1 (A3): a structured refusal before import, reason mutation_not_installed
    assert rec["stage"] == "refused" and rec["refusal"]["reason"] == "mutation_not_installed"
    assert rec["mutation"]["applied"] is False
    assert "imported" not in rec and "exception" not in rec


def test_P3_a_syntax_error_has_no_executed_target_frame(tmp_path):
    root = toy_copy(tmp_path, "X = (1,\n")
    _, rec, _ = run_probe(tmp_path, root, "control")
    assert rec["exception"]["qualname"] == "SyntaxError" and rec["exception"]["syntax"]["lineno"] == 1
    assert all(fr["rel"] != MOD_REL for fr in rec["exception"]["frames"]), rec["exception"]["frames"]


# -------------------------------------------------------------------------------------------- A1 context, A2 barriers
def test_A1_no_s1_module_is_pre_imported_and_the_conftest_prefix_order_is_reproduced(tmp_path):
    root = toy_copy(tmp_path, "X = 1\n")
    (root / "research/s1/s1_other.py").write_text("Y = 2\n", encoding="utf-8")
    _, rec, d = run_probe(tmp_path, root, "control")
    assert rec["copy_modules_before_import"] == [], rec["copy_modules_before_import"]
    want = [str((root / r).resolve()) for r in ("research/s1/s1_tests", "research/s1", ".")]
    assert rec["sys_path_prefix"] == want, rec["sys_path_prefix"]
    assert rec["env_bound"]["S1_HYPOTHESIS_ROOT"] == str(d / "hypothesis")
    assert str(PROBE.parent) not in rec["sys_path_prefix"]


def test_A2_barriers_are_installed_identically_in_both_modes(tmp_path):
    root = toy_copy(tmp_path, GENUINE)
    _, ctl, _ = run_probe(tmp_path, root, "control")
    root2 = toy_copy(tmp_path, GENUINE, "copy2")
    _, mut, _ = run_probe(tmp_path, root2, "mutated")
    for r in (ctl, mut):
        assert r["barrier"]["installed"] is True and r["barrier"]["refusals"] == []
    assert ctl["modules_before_import"] == mut["modules_before_import"], "same import context in both modes"
    assert ctl["probe_sha256"] == mut["probe_sha256"] == sha(PROBE)


@pytest.mark.parametrize("body,event", [
    ("open(r'{outside}', 'w').write('x')", "open"),
    ("open(r'{outside}', 'a')", "open"),
    ("import os\nos.open(r'{outside}', os.O_CREAT | os.O_WRONLY)", "open"),
    ("import socket\nsocket.getaddrinfo('example.invalid', 80)", "socket.getaddrinfo"),
    ("import socket\ns = socket.socket()\ns.bind(('127.0.0.1', 0))", "socket.bind"),
    ("import sqlite3\nsqlite3.connect(r'{outside}')", "sqlite3.connect"),
    ("import subprocess\nsubprocess.Popen(['cmd', '/c', 'exit'])", "subprocess.Popen"),
    ("import os\nos.system('exit')", "os.system"),
])
def test_A2_a_barrier_refusal_is_raised_from_the_probe_hook_never_the_target(tmp_path, body, event):
    outside = tmp_path / "outside" / "f.db"
    outside.parent.mkdir()
    root = toy_copy(tmp_path, body.format(outside=outside) + "\n")
    _, rec, _ = run_probe(tmp_path, root, "control")
    assert rec["barrier"]["refusals"] and rec["barrier"]["refusals"][0]["event"] == event, rec["barrier"]
    assert rec["exception"]["qualname"] == "BarrierRefusal"
    assert innermost(rec)["is_probe"] is True and innermost(rec)["rel"] is None
    assert not outside.exists(), "nothing was written outside the scratch roots"


def test_A2_writes_and_databases_inside_the_scratch_roots_are_allowed(tmp_path):
    src = ("import sqlite3\nfrom pathlib import Path\nP = Path(__file__).parent / 'scratch.db'\n"
           "sqlite3.connect(str(P)).close()\nsqlite3.connect(':memory:').close()\n")
    root = toy_copy(tmp_path, src)
    _, rec, _ = run_probe(tmp_path, root, "control")
    assert rec["imported"] is True and rec["barrier"]["refusals"] == [], rec.get("exception")


def test_P5_the_record_is_write_once(tmp_path):
    assert PROBE.is_file(), "the probe script cr_import_probe.py exists"
    root = toy_copy(tmp_path, "X = 1\n")
    d = tmp_path / "dg_control"
    d.mkdir()
    (d / "record.json").write_text("EARLIER", encoding="utf-8")
    sp = d / "spec.json"
    sp.write_text(json.dumps(GENUINE_SPEC), encoding="utf-8")
    env = cr_coord._env(root, cfg())
    cmd = [str(PY), "-B", str(PROBE), "--mode", "control", "--copy-root", str(root), "--module-rel", MOD_REL,
           "--target", "s1_x", "--spec", str(sp), "--scratch", str(d), "--out", str(d / "record.json")]
    run = cr_guard.run_contained(cmd, cwd=root, env=env, stdout_path=d / "o.txt", stderr_path=d / "e.txt",
                                 deadline_s=60)
    assert run["rc"] != 0 and (d / "record.json").read_text(encoding="utf-8") == "EARLIER"


def test_P4_the_probe_is_never_imported_by_the_driver_and_never_runs_code_strings():
    src = PROBE.read_text(encoding="utf-8")
    assert "exec(" not in src and "eval(" not in src, "no ad-hoc source evaluation"
    assert "cosmic_ray.mutating" in src and "get_operator" in src, "the pinned Cosmic Ray operator API"


# ===================================================================================== fix round 1 (Codex amendments)
# A3: the mutated child validates source identity and ONE localized change BEFORE importing; on failure it writes a
# structured refusal and exits without importing. A2: protected READS denied, full filesystem-mutation coverage,
# paths resolved before descendant checks, unknown access fails closed; a cooperative child-local barrier, not an OS
# sandbox. Synthetic protected fixtures only.
SENTINEL_SRC = ("from pathlib import Path\nA = 1 + 1\nB = 2 + 2\n"
                "if A != 2:\n    (Path(__file__).parent / 'SENTINEL').write_text('imported', encoding='utf-8')\n")
SUB_SPEC = dict(GENUINE_SPEC, operator="core/ReplaceBinaryOperator_Add_Sub", occurrence=0)


def _probe_mod():
    import importlib.util
    assert PROBE.is_file(), "the probe script cr_import_probe.py exists"
    spec = importlib.util.spec_from_file_location("cr_import_probe_under_test", PROBE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _attr(m, name):
    assert hasattr(m, name), f"cr_import_probe.{name} exists"
    return getattr(m, name)


def test_A3_the_sentinel_toy_imports_when_the_change_is_inside_the_span(tmp_path):
    """Positive control for the sentinel: occurrence 0 mutates line 2 and the span says line 2 - validated, then
    imported, and the target's import side effect happens."""
    root = toy_copy(tmp_path, SENTINEL_SRC)
    _, rec, _ = run_probe(tmp_path, root, "mutated", dict(SUB_SPEC, start=[2, 6], end=[2, 7]))
    assert (rec.get("validation") or {}).get("ok") is True and rec.get("imported") is True, rec
    assert (root / "research/s1/SENTINEL").is_file()


def test_A3_a_change_outside_the_span_is_refused_before_import_and_the_sentinel_stays_absent(tmp_path):
    root = toy_copy(tmp_path, SENTINEL_SRC)
    _, rec, d = run_probe(tmp_path, root, "mutated", dict(SUB_SPEC, start=[3, 6], end=[3, 7]))
    assert not (root / "research/s1/SENTINEL").exists(), "the target was never imported"
    assert rec["stage"] == "refused" and rec["refusal"]["reason"].startswith("not_localized"), rec
    assert "imported" not in rec and "exception" not in rec
    pre = json.loads((d / "record.preimport.json").read_text(encoding="utf-8"))
    assert pre["validation"]["ok"] is False and pre["mutation"]["post_sha256"] == sha(root / MOD_REL)


def test_A3_a_pre_source_mismatch_is_refused_before_any_mutation_or_import(tmp_path):
    root = toy_copy(tmp_path, SENTINEL_SRC)
    before = sha(root / MOD_REL)
    _, rec, _ = run_probe(tmp_path, root, "mutated", dict(SUB_SPEC, start=[2, 6], end=[2, 7]), pin="0" * 64)
    assert rec.get("stage") == "refused" and rec["refusal"]["reason"] == "pre_source_mismatch", rec
    assert sha(root / MOD_REL) == before and not (root / "research/s1/SENTINEL").exists()
    _, ctl, _ = run_probe(tmp_path, toy_copy(tmp_path, SENTINEL_SRC, "c2"), "control", pin="0" * 64, tag="c")
    assert ctl.get("stage") == "refused" and ctl["refusal"]["reason"] == "pre_source_mismatch" and "imported" not in ctl


@pytest.mark.parametrize("spec,reason", [
    (dict(SUB_SPEC, operator="core/NoSuchOperator"), "mutation_api_exception"),
    (dict(SUB_SPEC, operator_args={"bogus": 1}), "mutation_api_exception"),
    (dict(SUB_SPEC, occurrence=99), "mutation_not_installed"),
])
def test_A3_mutation_api_failures_and_no_ops_are_refused_without_import(tmp_path, spec, reason):
    root = toy_copy(tmp_path, SENTINEL_SRC)
    _, rec, _ = run_probe(tmp_path, root, "mutated", dict(spec, start=[2, 6], end=[2, 7]))
    assert rec.get("stage") == "refused" and rec["refusal"]["reason"] == reason, rec
    assert "imported" not in rec and not (root / "research/s1/SENTINEL").exists()


def test_A3_the_preimport_record_holds_the_validated_hashes_and_diff(tmp_path):
    root = toy_copy(tmp_path, GENUINE)
    _, rec, d = run_probe(tmp_path, root, "mutated")
    p = d / "record.preimport.json"
    assert p.is_file(), "a pre-import validation record is written before the import"
    pre = json.loads(p.read_text(encoding="utf-8"))
    assert pre["validation"]["ok"] is True and pre["validation"]["post_span"] == [[4, 19], [4, 20]]
    assert pre["mutation"] == rec["mutation"] and pre["source"]["pre_sha256"] == rec["source"]["pre_sha256"]
    assert rec["validation"] == pre["validation"] and rec["imported"] is False
    assert not list(d.glob("*.tmp")), "records are written atomically (temp then rename)"


@pytest.mark.parametrize("post,ok,why", [
    ("POST", True, None), ("PRE", False, "unchanged"), ("TWO", False, "not_localized"),
    ("REFORMAT", False, "not_localized"), ("NEWLINE", False, "newline")])
def test_A3_the_child_validator_agrees_with_the_parent_localize(post, ok, why):
    from test_cr_calibrate import _drv
    posts = {"POST": GENUINE.replace("SLOT_KINDS + STAGE", "SLOT_KINDS & STAGE"), "PRE": GENUINE,
             "TWO": GENUINE.replace("SLOT_KINDS + STAGE_KINDS + TRIAL", "SLOT_KINDS & STAGE_KINDS & TRIAL"),
             "REFORMAT": GENUINE.replace("SLOT_KINDS + STAGE", "SLOT_KINDS & STAGE").replace("('a', 'b')",
                                                                                         "('a',  'b')"),
             "NEWLINE": GENUINE.replace("+ STAGE", "&\n STAGE")}
    child = _attr(_probe_mod(), "validate_mutation")(GENUINE, posts[post], [4, 19], [4, 20])
    parent = _drv().localize(GENUINE, posts[post], [4, 19], [4, 20])
    assert child[0] is parent[0] is ok, (child, parent)
    if why:
        assert why in child[1]["why"] and why in parent[1]["why"]
    else:
        assert child[1]["post_span"] == parent[1]["post_span"]


# --------------------------------------------------------------------------------------------- A2 (amended)
def _barrier(tmp_path, protected=()):
    m = _probe_mod()
    refusals = []
    scratch = tmp_path / "scratch"
    scratch.mkdir(exist_ok=True)
    try:
        hook = m.make_barrier([str(scratch)], refusals, protected=[str(p) for p in protected])
    except TypeError:
        hook = None
    assert hook is not None, "make_barrier takes the protected paths"
    return m, hook, refusals, scratch


def _refused(m, hook, event, args):
    with pytest.raises(m.BarrierRefusal):
        hook(event, args)


TWO_PATH = ("os.rename", "os.link", "os.symlink", "shutil.copyfile", "shutil.move")


@pytest.mark.parametrize("event,args_fn", [
    ("os.remove", lambda s, o: (o, -1)), ("os.rmdir", lambda s, o: (o, -1)),
    ("os.rename", lambda s, o: (s / "a", o, -1, -1)), ("os.rename", lambda s, o: (o, s / "a", -1, -1)),
    ("os.link", lambda s, o: (s / "a", o, -1, -1)), ("os.link", lambda s, o: (o, s / "a", -1, -1)),
    ("os.symlink", lambda s, o: (s / "a", o, -1)), ("os.mkdir", lambda s, o: (o, 0o777, -1)),
    ("os.chmod", lambda s, o: (o, 0o777, -1)), ("os.utime", lambda s, o: (o, None, None, -1)),
    ("os.truncate", lambda s, o: (o, 0)), ("shutil.rmtree", lambda s, o: (o, None)),
    ("shutil.copyfile", lambda s, o: (s / "a", o)), ("shutil.move", lambda s, o: (s / "a", o)),
    ("open", lambda s, o: (o, "w", 0)), ("open", lambda s, o: (str(o).encode(), "a", 0)),
    ("open", lambda s, o: (o, None, 0x0100 | 0x0001)), ("sqlite3.connect", lambda s, o: (o,)),
    ("sqlite3.connect", lambda s, o: (f"file:{o}?mode=rwc",)),
])
def test_A2_every_filesystem_mutation_outside_the_scratch_root_is_refused(tmp_path, event, args_fn):
    m, hook, refusals, scratch = _barrier(tmp_path)
    outside = tmp_path / "outside" / "x"
    _refused(m, hook, event, args_fn(scratch, outside))
    assert refusals and refusals[-1]["event"] == event and refusals[-1]["reason"]
    hook(event, args_fn(scratch, scratch / "b"))                      # inside the scratch root: allowed


@pytest.mark.parametrize("trick", ["dotdot", "relative", "case", "extended", "extended_dotdot", "forward"])
def test_A2_paths_are_resolved_before_the_descendant_check(tmp_path, monkeypatch, trick):
    m, hook, _, scratch = _barrier(tmp_path)
    outside = tmp_path / "outside.txt"
    monkeypatch.chdir(scratch)
    bad = {"dotdot": str(scratch / ".." / "outside.txt"), "relative": "..\\outside.txt",
           "case": str(outside).upper(), "extended": "\\\\?\\" + str(outside),
           "extended_dotdot": "\\\\?\\" + str(scratch) + "\\..\\outside.txt",
           "forward": str(outside).replace("\\", "/")}[trick]
    _refused(m, hook, "open", (bad, "w", 0))
    ok = {"dotdot": str(scratch / "sub" / ".." / "in.txt"), "relative": "in.txt",
          "case": str(scratch / "in.txt").upper(), "extended": "\\\\?\\" + str(scratch / "in.txt"),
          "extended_dotdot": "\\\\?\\" + str(scratch / "sub") + "\\..\\in.txt",
          "forward": str(scratch / "in.txt").replace("\\", "/")}[trick]
    hook("open", (ok, "w", 0))


@pytest.mark.parametrize("args", [(1, "w", 0), (object(), "w", 0), (None, "w", 0), (b"\xff\xfe\x00bad", "w", 0)])
def test_A2_unknown_or_unparseable_writes_fail_closed(tmp_path, args):
    m, hook, refusals, _ = _barrier(tmp_path)
    _refused(m, hook, "open", args)
    assert refusals[-1]["reason"].startswith(("unparseable", "fd_write", "outside_scratch"))


def test_A2_protected_reads_are_refused_and_never_dumped(tmp_path):
    prot = tmp_path / "prot" / "mailbox.sqlite3"
    prot.parent.mkdir()
    prot.write_text("SYNTHETIC-SECRET-71", encoding="utf-8")
    m, hook, refusals, scratch = _barrier(tmp_path, protected=[prot])
    for event, args in (("open", (prot, "r", 0)), ("open", (str(prot).upper(), "rb", 0)),
                        ("open", (str(prot) + "-wal", "r", 0)), ("open", ("\\\\?\\" + str(prot), "r", 0)),
                        ("sqlite3.connect", (str(prot),)), ("sqlite3.connect", (f"file:{prot}?mode=ro",)),
                        ("sqlite3.connect", ("file:" + str(prot).replace("\\", "/") + "?mode=ro&cache=shared",)),
                        ("shutil.copyfile", (prot, scratch / "copy"))):
        _refused(m, hook, event, args)
    assert all(r["reason"].startswith("protected") for r in refusals), refusals
    assert "SYNTHETIC-SECRET-71" not in json.dumps(refusals)
    hook("open", (tmp_path / "prot" / "other.txt", "r", 0))                 # ordinary reads stay allowed
    hook("sqlite3.connect", (":memory:",))
    hook("sqlite3.connect", ("file::memory:?cache=shared",))
    hook("sqlite3.connect", (str(scratch / "ok.db"),))


def test_A2_protected_reads_in_a_real_child_are_refused_without_contents(tmp_path):
    prot = tmp_path / "prot" / "s1_receipt_hmac.key"
    prot.parent.mkdir()
    prot.write_text("SYNTHETIC-KEY-0042", encoding="utf-8")
    root = toy_copy(tmp_path, f"K = open(r'{prot}').read()\n")
    _, rec, d = run_probe(tmp_path, root, "control", protected=[prot])
    assert rec["barrier"]["refusals"] and rec["barrier"]["refusals"][0]["reason"].startswith("protected"), rec
    assert rec["exception"]["qualname"] == "BarrierRefusal" and innermost(rec)["is_probe"] is True
    assert "SYNTHETIC-KEY-0042" not in (d / "record.json").read_text(encoding="utf-8")
    assert "cooperative" in rec["barrier"]["claim"] and "not an OS sandbox" in rec["barrier"]["claim"]


@pytest.mark.parametrize("body", [
    "import os\nos.remove(r'{o}')", "import os\nos.rename(r'{o}', r'{o}.moved')",
    "import os\nos.replace(r'{o}', r'{o}.moved')", "import shutil\nshutil.rmtree(r'{od}')",
    "import os\nos.mkdir(r'{od}\\new')", "import os\nos.truncate(r'{o}', 0)",
])
def test_A2_destructive_operations_in_a_real_child_leave_outside_files_untouched(tmp_path, body):
    od = tmp_path / "outside"
    od.mkdir()
    o = od / "keep.txt"
    o.write_text("keep", encoding="utf-8")
    root = toy_copy(tmp_path, body.format(o=o, od=od) + "\n")
    _, rec, _ = run_probe(tmp_path, root, "control")
    assert o.read_text(encoding="utf-8") == "keep" and sorted(p.name for p in od.iterdir()) == ["keep.txt"]
    assert rec["barrier"]["refusals"], rec


def test_A2_the_hook_precedes_any_s1_code_and_the_bootstrap_window_imports_no_copy_module(tmp_path):
    """A copy module shadowing a stdlib name the probe loads during bootstrap must NOT be imported there."""
    root = toy_copy(tmp_path, "X = 1\n")
    for name in ("difflib", "dis", "tokenize", "argparse"):
        (root / "research/s1" / f"{name}.py").write_text(
            "from pathlib import Path\n(Path(__file__).parent / 'SHADOW').write_text('x')\n", encoding="utf-8")
    run, rec, _ = run_probe(tmp_path, root, "control")
    assert not (root / "research/s1/SHADOW").exists(), "no copy module ran in the bootstrap window"
    assert rec is not None and rec["imported"] is True, run
    b = rec["bootstrap"]
    assert b["copy_modules_before_hook"] == [] and b["hook_installed_before_target"] is True
    assert b["copy_paths_hidden_during_bootstrap"], b


def test_A2_control_and_mutated_run_under_identical_barriers(tmp_path):
    prot = tmp_path / "p.key"
    root = toy_copy(tmp_path, GENUINE)
    _, ctl, _ = run_probe(tmp_path, root, "control", protected=[prot])
    _, mut, _ = run_probe(tmp_path, toy_copy(tmp_path, GENUINE, "c2"), "mutated", protected=[prot])
    keys = ("events", "protected", "claim", "installed_at")
    assert {k: ctl["barrier"].get(k) for k in keys} == {k: mut["barrier"].get(k) for k in keys}
    assert ctl["barrier"]["installed_at"] == "before_mutation_and_import"


# ===================================================================================== fix round 2 (task review)
# I1: a SQLite URI is in-memory ONLY with an exact mode=memory parameter (or the plain :memory:). I2: the barrier
# fails closed - every audit event is either reviewed (handled / allowlisted) or its path-like arguments must all
# resolve inside the scratch roots; _winapi.CreateFile / CreateJunction / CreateNamedPipe, ctypes, msvcrt, winreg
# writes, mmap, thread creation and network families are handled explicitly. M2: a per-thread re-entrancy flag.
# Synthetic protected fixtures only.
GENERIC_READ, GENERIC_WRITE, DELETE = 0x80000000, 0x40000000, 0x00010000
OPEN_EXISTING, CREATE_ALWAYS, OPEN_ALWAYS = 3, 2, 4
DELETE_ON_CLOSE = 0x04000000


def _prot(tmp_path):
    prot = tmp_path / "prot" / "trading.db"
    prot.parent.mkdir(exist_ok=True)
    prot.write_text("SYNTHETIC-ROW-55", encoding="utf-8")
    return prot


@pytest.mark.parametrize("query", ["?xmode=memory", "?cache=shared&nomode=memory", "?mode=memoryx",
                                   "?mode=memory&mode=rw", "?MODE=memory", "?mode=mem%6Fry2", "?mode=ro",
                                   "?vfs=memory", "#mode=memory", "?mode=%20memory"])
def test_fix2_I1_a_uri_look_alike_of_mode_memory_is_not_memory(tmp_path, query):
    prot = _prot(tmp_path)
    m, hook, refusals, _ = _barrier(tmp_path, protected=[prot])
    for base in (f"file:{prot}", "file:" + str(prot).replace("\\", "/"), "file:/" + str(prot).replace("\\", "/")):
        _refused(m, hook, "sqlite3.connect", (base + query,))
    assert all(r["reason"] in ("protected_read", "unparseable_path") for r in refusals), refusals


@pytest.mark.parametrize("db", [":memory:", "file::memory:", "file::memory:?cache=shared", "file:x?mode=memory",
                                "file:whatever?cache=shared&mode=memory"])
def test_fix2_I1_only_exact_memory_forms_are_memory(tmp_path, db):
    m, hook, refusals, _ = _barrier(tmp_path, protected=[_prot(tmp_path)])
    hook("sqlite3.connect", (db,))
    assert refusals == []


@pytest.mark.parametrize("db", ["", "file:", "file:?mode=ro", "file:?cache=shared"])
def test_fix2_I1_an_anonymous_temporary_database_fails_closed(tmp_path, db):
    m, hook, _, _ = _barrier(tmp_path)
    _refused(m, hook, "sqlite3.connect", (db,))


def test_fix2_I1_a_real_child_cannot_read_a_protected_db_through_a_look_alike_uri(tmp_path):
    import sqlite3
    prot = tmp_path / "prot" / "trading.db"
    prot.parent.mkdir()
    con = sqlite3.connect(prot)
    con.execute("create table t (x)")
    con.execute("insert into t values ('SYNTHETIC-ROW-77')")
    con.commit()
    con.close()
    uri = "file:" + str(prot).replace("\\", "/") + "?xmode=memory"
    root = toy_copy(tmp_path, f"import sqlite3\nROWS = sqlite3.connect({uri!r}, uri=True).execute("
                              f"'select x from t').fetchall()\n")
    _, rec, d = run_probe(tmp_path, root, "control", protected=[prot])
    assert rec["barrier"]["refusals"] and rec["barrier"]["refusals"][0]["reason"] == "protected_read", rec
    assert "SYNTHETIC-ROW-77" not in (d / "record.json").read_text(encoding="utf-8")


@pytest.mark.parametrize("args,refused", [
    (lambda s, o, p: (str(o), GENERIC_WRITE, 0, CREATE_ALWAYS, 0), "outside_scratch"),
    (lambda s, o, p: (str(o), GENERIC_READ, 0, OPEN_ALWAYS, 0), "outside_scratch"),
    (lambda s, o, p: (str(o), DELETE, 0, OPEN_EXISTING, 0), "outside_scratch"),
    (lambda s, o, p: (str(o), GENERIC_READ, 0, OPEN_EXISTING, DELETE_ON_CLOSE), "outside_scratch"),
    (lambda s, o, p: (str(p), GENERIC_READ, 0, OPEN_EXISTING, 0), "protected_read"),
    (lambda s, o, p: ("\\\\?\\" + str(p), GENERIC_READ, 0, OPEN_EXISTING, 0), "protected_read"),
    (lambda s, o, p: (str(o), GENERIC_READ, 0, OPEN_EXISTING, 0), None),
    (lambda s, o, p: (str(s / "in.txt"), GENERIC_WRITE, 0, CREATE_ALWAYS, 0), None),
    (lambda s, o, p: (str(o), "bogus", 0, OPEN_EXISTING, 0), "unparseable"),
])
def test_fix2_I2_winapi_createfile_is_checked_by_access_and_disposition(tmp_path, args, refused):
    prot = _prot(tmp_path)
    m, hook, refusals, scratch = _barrier(tmp_path, protected=[prot])
    a = args(scratch, tmp_path / "outside.txt", prot)
    if refused is None:
        hook("_winapi.CreateFile", a)
        assert refusals == []
    else:
        _refused(m, hook, "_winapi.CreateFile", a)
        assert refusals[-1]["reason"].startswith(refused), refusals


@pytest.mark.parametrize("event,args_fn", [
    ("_winapi.CreateJunction", lambda s, o: (str(s / "j"), str(o))),
    ("_winapi.CreateJunction", lambda s, o: (str(o), str(s / "j"))),
    ("_winapi.CreateNamedPipe", lambda s, o: ("\\\\.\\pipe\\x", 3, 0)),
    ("_winapi.CreatePipe", lambda s, o: (None, 0)),
    ("_winapi.OpenProcess", lambda s, o: (0x1F0FFF, False, 4)),
    ("ctypes.dlopen", lambda s, o: ("user32",)), ("ctypes.call_function", lambda s, o: (0, ())),
    ("msvcrt.open_osfhandle", lambda s, o: (4, 0)), ("msvcrt.get_osfhandle", lambda s, o: (3,)),
    ("winreg.SetValue", lambda s, o: (0, "k", 1, "v")), ("winreg.CreateKey", lambda s, o: (0, "k", 0)),
    ("winreg.SaveKey", lambda s, o: (0, str(o))), ("winreg.ConnectRegistry", lambda s, o: ("host", 0)),
    ("mmap.__new__", lambda s, o: (3, 10, 2, 0)), ("_thread.start_new_thread", lambda s, o: (print, (), {})),
    ("sqlite3.load_extension", lambda s, o: (None, str(o))), ("sqlite3.enable_load_extension", lambda s, o: (None, True)),
    ("socket.gethostbyname", lambda s, o: ("example.invalid",)), ("urllib.Request", lambda s, o: ("http://x", None, {}, "GET")),
    ("http.client.connect", lambda s, o: (None, "x", 80)), ("webbrowser.open", lambda s, o: ("http://x",)),
    ("os.kill", lambda s, o: (4, 9)), ("tempfile.mkstemp", lambda s, o: (str(o),)), ("tempfile.mkdtemp", lambda s, o: (str(o),)),
    ("os.add_dll_directory", lambda s, o: ("PROT",)),
    ("some.unlisted_event", lambda s, o: (str(o),)), ("some.unlisted_event", lambda s, o: (7,)),
    ("some.unlisted_event", lambda s, o: (str(s / "a"), str(o))),
])
def test_fix2_I2_filesystem_and_process_families_and_unlisted_events_fail_closed(tmp_path, event, args_fn):
    prot = _prot(tmp_path)
    m, hook, refusals, scratch = _barrier(tmp_path, protected=[prot])
    a = tuple(str(prot) if x == "PROT" else x for x in args_fn(scratch, tmp_path / "outside"))
    _refused(m, hook, event, a)
    assert refusals[-1]["event"] == event and refusals[-1]["reason"]


@pytest.mark.parametrize("event,args_fn", [
    ("import", lambda s, o: ("json", None, [], [], [])), ("compile", lambda s, o: (b"x = 1", str(o))),
    ("exec", lambda s, o: (compile("x = 1", "<t>", "exec"),)), ("os.listdir", lambda s, o: (str(o),)),
    ("os.scandir", lambda s, o: (str(o),)), ("os.chdir", lambda s, o: (str(s),)), ("glob.glob", lambda s, o: ("*.py", False)),
    ("winreg.OpenKey", lambda s, o: (0, "Software", 0)), ("mmap.__new__", lambda s, o: (-1, 10, 1, 0)),
    ("socket.__new__", lambda s, o: (None, 2, 1, 0)), ("os.add_dll_directory", lambda s, o: (str(o),)),
    ("some.unlisted_event", lambda s, o: (str(s / "a"), "name_inside")), ("some.unlisted_event", lambda s, o: (None,)),
    ("tempfile.mkstemp", lambda s, o: (str(s / "t"),)), ("object.__setattr__", lambda s, o: (object, "x", 1)),
])
def test_fix2_I2_reviewed_reads_and_inside_scratch_events_stay_allowed(tmp_path, monkeypatch, event, args_fn):
    m, hook, refusals, scratch = _barrier(tmp_path, protected=[_prot(tmp_path)])
    monkeypatch.chdir(scratch)
    hook(event, args_fn(scratch, tmp_path / "outside"))
    assert refusals == []


def test_fix2_I2_a_real_child_cannot_create_a_file_through_winapi(tmp_path):
    outside = tmp_path / "outside" / "created_via_winapi.txt"
    outside.parent.mkdir()
    root = toy_copy(tmp_path, f"import _winapi\nH = _winapi.CreateFile({str(outside)!r}, 0x40000000, 0, 0, 2, 0, 0)\n")
    _, rec, _ = run_probe(tmp_path, root, "control")
    assert not outside.exists(), "nothing was created outside the scratch roots"
    assert rec["barrier"]["refusals"][0]["event"] == "_winapi.CreateFile", rec["barrier"]


def test_fix2_M2_a_thread_started_by_the_target_is_refused(tmp_path):
    outside = tmp_path / "outside.txt"
    root = toy_copy(tmp_path, f"import threading\nT = threading.Thread(target=lambda: open({str(outside)!r}, 'w'))\n"
                              f"T.start()\nT.join()\n")
    _, rec, _ = run_probe(tmp_path, root, "control")
    assert rec["barrier"]["refusals"][0]["event"] == "_thread.start_new_thread", rec["barrier"]
    assert not outside.exists()


def test_fix2_M2_the_reentrancy_flag_is_per_thread(tmp_path):
    """While one thread is inside the hook, another thread's events are still checked."""
    import threading
    m, hook, refusals, scratch = _barrier(tmp_path)
    started, release, seen = threading.Event(), threading.Event(), []
    orig = m.resolve

    def slow_resolve(p):
        if threading.current_thread().name == "slow":
            started.set()
            release.wait(5)
        return orig(p)
    m.resolve = slow_resolve
    try:
        t = threading.Thread(target=lambda: hook("open", (str(scratch / "a"), "w", 0)), name="slow")
        t.start()
        assert started.wait(5)
        try:
            hook("open", (str(tmp_path / "outside.txt"), "w", 0))
        except m.BarrierRefusal:
            seen.append("refused")
        release.set()
        t.join(5)
    finally:
        m.resolve = orig
    assert seen == ["refused"], "a concurrent event was skipped by a shared re-entrancy flag"


def test_fix2_M3_lines_split_only_on_python_newlines():
    pre = "# c\x0cd\x1ce f\nX = 1 + 2\n"
    post = pre.replace("1 + 2", "1 & 2")
    ok, info = _attr(_probe_mod(), "validate_mutation")(pre, post, [2, 6], [2, 7])
    assert ok is True and info["post_span"] == [[2, 6], [2, 7]], info


def test_fix2_M1_the_probe_does_not_claim_an_independent_dis_cross_check():
    src = PROBE.read_text(encoding="utf-8")
    assert "cross-checked against dis" not in src
    assert "not an independent check" in src


# ===================================================================================== fix round 3 (re-review)
# N1: SQL-level file access (ATTACH, VACUUM INTO) through an allowed connection is checked by a SQLite authorizer the
# barrier installs on every new connection (sqlite3.connect/handle). N3: unlisted events are checked inside tuple /
# list arguments. N2 (narrow; accepted as amended in Codex's 3e80738 review): exactly the ctypes events of `import ctypes`,
# `from ctypes import wintypes`, `import msvcrt` and a kernel32 WinDLL with the CreateFileW / CloseHandle prototypes
# (recorded from a SYNTHETIC toy of that shape) are allowed; every other ctypes / msvcrt / _winapi event is refused.
def _sqlite_fixtures(tmp_path):
    import sqlite3
    prot = tmp_path / "prot" / "trading.db"
    prot.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(prot)
    con.execute("create table t (x)")
    con.execute("insert into t values ('SYNTHETIC-ROW-91')")
    con.commit()
    con.close()
    return prot


SQL_TOY = ("import sqlite3\nfrom pathlib import Path\nHERE = Path(__file__).parent\n"
           "con = sqlite3.connect({db})\ncon.execute('create table if not exists q (y)')\n{stmt}\n")


@pytest.mark.parametrize("db,stmt,refused", [
    ("':memory:'", "ROWS = con.execute(\"ATTACH DATABASE '{prot}' AS x\").fetchall()", True),
    ("':memory:'", "con.execute(\"ATTACH DATABASE '{outside}' AS x\")", True),
    ("':memory:'", "con.execute(\"VACUUM INTO '{outside}'\")", True),
    ("str(HERE / 'in.db')", "con.execute(\"VACUUM INTO '{prot}'\")", True),
    ("':memory:'", "con.execute(\"ATTACH DATABASE 'file:{prot_uri}?xmode=memory' AS x\")", True),
    ("':memory:'", "con.execute(\"ATTACH DATABASE '' AS x\")", True),
    ("':memory:'", "con.execute(\"ATTACH DATABASE ':memory:' AS x\")", False),
    ("':memory:'", "con.execute(\"ATTACH DATABASE '\" + str(HERE / 'att.db') + \"' AS x\")", False),
    ("str(HERE / 'in.db')", "con.execute(\"VACUUM INTO '\" + str(HERE / 'vac.db') + \"'\")", False),
])
def test_fix3_N1_attach_and_vacuum_into_are_checked_by_the_authorizer(tmp_path, db, stmt, refused):
    prot = _sqlite_fixtures(tmp_path)
    outside = tmp_path / "outside" / "made.db"
    outside.parent.mkdir()
    s = stmt.format(prot=str(prot).replace("\\", "/"), outside=str(outside).replace("\\", "/"),
                    prot_uri=str(prot).replace("\\", "/"))
    root = toy_copy(tmp_path, SQL_TOY.format(db=db, stmt=s))
    _, rec, d = run_probe(tmp_path, root, "control", protected=[prot])
    assert "SYNTHETIC-ROW-91" not in (d / "record.json").read_text(encoding="utf-8")
    assert not outside.exists(), "nothing created outside the scratch roots"
    if refused:
        assert rec["barrier"]["refusals"] and rec["barrier"]["refusals"][0]["event"] == "sqlite3.authorizer", rec
        assert rec.get("imported") is not True
    else:
        assert rec["barrier"]["refusals"] == [] and rec["imported"] is True, rec.get("exception")


def test_fix3_N1_the_handle_event_is_no_longer_safe_and_an_uninstallable_authorizer_refuses(tmp_path):
    m, hook, refusals, _ = _barrier(tmp_path)
    assert "sqlite3.connect/handle" not in m.SAFE

    class NoAuth:
        def set_authorizer(self, fn):
            raise RuntimeError("cannot")
    _refused(m, hook, "sqlite3.connect/handle", (NoAuth(),))
    _refused(m, hook, "sqlite3.connect/handle", (object(),))
    assert refusals[-1]["reason"] == "authorizer_not_installed"


@pytest.mark.parametrize("args", [
    lambda s, o, p: ((str(o),),), lambda s, o, p: ([str(p)],), lambda s, o, p: (("a", [str(o)]),),
    lambda s, o, p: ([(1,)],), lambda s, o, p: ((((((str(o),),),),),),),
])
def test_fix3_N3_unlisted_events_are_checked_inside_sequences(tmp_path, args):
    prot = _prot(tmp_path)
    m, hook, refusals, scratch = _barrier(tmp_path, protected=[prot])
    _refused(m, hook, "custom.event", args(scratch, tmp_path / "outside", prot))


def test_fix3_N3_inside_scratch_sequences_stay_allowed(tmp_path, monkeypatch):
    m, hook, refusals, scratch = _barrier(tmp_path)
    monkeypatch.chdir(scratch)
    hook("custom.event", ((str(scratch / "a"), [str(scratch / "b"), None]),))
    assert refusals == []


LOCKS_SHAPE = ('"""SYNTHETIC toy with the import-time shape of a Windows lock helper (never the real module)."""\n'
               "import ctypes\nimport sys\n\n"
               "if sys.platform == 'win32':\n"
               "    import msvcrt\n    from ctypes import wintypes\n"
               "    _k32 = ctypes.WinDLL('kernel32', use_last_error=True)\n"
               "    _k32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,\n"
               "                                 wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)\n"
               "    _k32.CreateFileW.restype = wintypes.HANDLE\n"
               "    _k32.CloseHandle.argtypes = (wintypes.HANDLE,)\n"
               "    _k32.CloseHandle.restype = wintypes.BOOL\n"
               "    _INVALID = wintypes.HANDLE(-1).value\n")


def test_fix3_N2_the_lock_helper_shaped_toy_imports_clean_under_the_barrier(tmp_path):
    root = toy_copy(tmp_path, LOCKS_SHAPE)
    _, rec, _ = run_probe(tmp_path, root, "control")
    assert rec["barrier"]["refusals"] == [] and rec["imported"] is True, (rec["barrier"], rec.get("exception"))


@pytest.mark.parametrize("tail,event", [
    ("_k32.CreateFileW('x', 0, 0, None, 3, 0, None)\n", "ctypes.call_function"),
    ("_k32.CloseHandle(_INVALID)\n", "ctypes.call_function"),
    ("ctypes.WinDLL('user32')\n", "ctypes.dlopen"),
    ("ctypes.CDLL('msvcrt')\n", "ctypes.dlopen"),
    ("_k32.DeleteFileW\n", "ctypes.dlsym"),
    ("_k32.WriteFile\n", "ctypes.dlsym"),
    # fix round 5 (R-N2): ctypes._string_at is a pre-hook module-level pointer, now a refusing wrapper - the call is
    # refused by the wrapper before the native function's own audit event (was "ctypes.string_at")
    ("ctypes.string_at(id(1), 1)\n", "ctypes.call_function"),
    ("ctypes.set_last_error(0)\n", "ctypes.set_last_error"),
    ("ctypes.c_int.from_address(id(1))\n", "ctypes.cdata"),
    ("ctypes.addressof(ctypes.c_int(1))\n", "ctypes.addressof"),
    ("msvcrt.get_osfhandle(0)\n", "msvcrt.get_osfhandle"),
])
def test_fix3_N2_everything_beyond_the_recorded_import_events_is_refused(tmp_path, tail, event):
    root = toy_copy(tmp_path, LOCKS_SHAPE + "    " + tail if not tail.startswith("ctypes.CDLL") else
                    LOCKS_SHAPE + tail)
    _, rec, _ = run_probe(tmp_path, root, "control")
    ev = [r["event"] for r in rec["barrier"]["refusals"]]
    assert ev and ev[0] == event, (ev, rec.get("exception"))


@pytest.mark.parametrize("event,args,ok", [
    ("ctypes.dlopen", ("kernel32",), True), ("ctypes.dlopen", ("KERNEL32.DLL",), False),
    ("ctypes.dlopen", ("C:/Windows/System32/kernel32.dll",), False), ("ctypes.dlopen", (None,), False),
    ("ctypes.dlsym", ("K32", "CreateFileW"), True), ("ctypes.dlsym", ("K32", "CloseHandle"), True),
    ("ctypes.dlsym", ("K32", "GetLastError"), True), ("ctypes.dlsym", ("K32", "WriteFile"), False),
    ("ctypes.dlsym", ("OTHER", "CreateFileW"), False), ("ctypes.dlsym/handle", (0, "CreateFileW"), False),
    ("ctypes.call_function", (0, ()), False), ("msvcrt.locking", (0, 0, 0), False),
    ("_winapi.CreateNamedPipe", ("x", 0, 0), False),
])
def test_fix3_N2_the_allowlist_is_exactly_the_recorded_set(tmp_path, event, args, ok):
    import ctypes
    m, hook, refusals, _ = _barrier(tmp_path)
    # fix round 6 (finding 3): the hook accepts only ctypes' own loader classes, so the libraries are real kernel32
    # WinDLL instances (loaded, never called); "OTHER" is one whose instance _name says user32
    other = ctypes.WinDLL("kernel32")
    other._name = "user32"
    a = tuple(ctypes.WinDLL("kernel32") if x == "K32" else other if x == "OTHER" else x for x in args)
    m._CT.active, m._CT.allowed = True, []     # as on the guarded CDLL.__getitem__ path
    try:
        if ok:
            hook(event, a)
            assert refusals == []
        else:
            _refused(m, hook, event, a)
    finally:
        m._CT.active, m._CT.allowed = False, []
    if ok and event == "ctypes.dlsym":        # off the guarded path an allowed symbol is still refused
        _refused(m, hook, event, a)
    assert set(m.CTYPES_ALLOWED) == {("ctypes.dlopen", "kernel32"), ("ctypes.dlsym", "kernel32", "GetLastError"),
                                     ("ctypes.dlsym", "kernel32", "CreateFileW"),
                                     ("ctypes.dlsym", "kernel32", "CloseHandle")}


# ===================================================================================== fix round 4 (re-review 2)
@pytest.mark.parametrize("stmt", [
    "ROWS = cx.execute(\"ATTACH DATABASE '{prot}' AS x\").fetchall()",
    "cx.execute(\"VACUUM INTO '{outside}'\")",
])
def test_fix4_m1_re_initialising_a_connection_cannot_drop_the_authorizer(tmp_path, stmt):
    prot = _sqlite_fixtures(tmp_path)
    outside = tmp_path / "outside" / "made.db"
    outside.parent.mkdir()
    s = stmt.format(prot=str(prot).replace("\\", "/"), outside=str(outside).replace("\\", "/"))
    src = ("import sqlite3\ncx = sqlite3.connect(':memory:')\ncx.execute('create table q (y)')\n"
           "try:\n    sqlite3.Connection.__init__(cx, ':memory:')\nexcept Exception:\n    pass\n"
           f"try:\n    {s}\nexcept Exception:\n    pass\n")
    root = toy_copy(tmp_path, src)
    _, rec, d = run_probe(tmp_path, root, "control", protected=[prot])
    assert not outside.exists(), "VACUUM INTO after a re-init created a file outside scratch"
    assert "SYNTHETIC-ROW-91" not in (d / "record.json").read_text(encoding="utf-8")
    ev = [(r["event"], r["reason"]) for r in rec["barrier"]["refusals"]]
    assert ("sqlite3.connect", "unguarded_connection") in ev, ev


def test_fix4_m1_a_guarded_re_init_keeps_the_authorizer(tmp_path):
    prot = _sqlite_fixtures(tmp_path)
    src = ("import sqlite3\ncx = sqlite3.connect(':memory:')\ntype(cx).__init__(cx, ':memory:')\n"
           f"try:\n    cx.execute(\"ATTACH DATABASE '{str(prot).replace(chr(92), '/')}' AS x\")\n"
           "except Exception:\n    pass\n")
    root = toy_copy(tmp_path, src)
    _, rec, _ = run_probe(tmp_path, root, "control", protected=[prot])
    ev = [(r["event"], r["reason"]) for r in rec["barrier"]["refusals"]]
    assert ("sqlite3.authorizer", "protected_read") in ev, ev


def test_fix4_m2_the_raw_function_pointer_is_not_an_attribute_of_the_wrapper(tmp_path):
    import ctypes
    m = _probe_mod()
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    raw = k32["CloseHandle"]
    w = _attr(m, "refusing_foreign_function")(raw, "CloseHandle", lambda n: None)
    for name in ("_f", "_func", "f", "func", "_n", "_r", "__wrapped__", "_objects", "_b_base_",
                 "_RefusingForeignFunction__f"):
        try:
            v = getattr(w, name)
        except AttributeError:
            continue
        assert not isinstance(v, ctypes._CFuncPtr), f"wrapper.{name} yields the raw pointer"
    with pytest.raises(TypeError):
        vars(w)
    w.restype = ctypes.c_int                           # declaring still works (forwarded)
    assert raw.restype is ctypes.c_int


@pytest.mark.parametrize("arg", [
    lambda o, p: {"p": str(o)}, lambda o, p: {str(o): 1 if False else None}, lambda o, p: {str(p)},
    lambda o, p: frozenset({str(o)}), lambda o, p: ({"a": [{"b": (str(o),)}]},), lambda o, p: {"n": 3},
])
def test_fix4_m3_unlisted_events_are_checked_inside_dicts_and_sets(tmp_path, arg):
    prot = _prot(tmp_path)
    m, hook, refusals, _ = _barrier(tmp_path, protected=[prot])
    _refused(m, hook, "custom.event", (arg(tmp_path / "outside", prot),))


def test_fix4_m3_inside_scratch_dicts_and_sets_stay_allowed(tmp_path, monkeypatch):
    m, hook, refusals, scratch = _barrier(tmp_path)
    monkeypatch.chdir(scratch)
    hook("custom.event", ({"k": str(scratch / "a"), str(scratch / "b"): {str(scratch / "c")}},))
    assert refusals == []


def test_fix4_m4_the_scope_discloses_the_bootstrap_preloads(tmp_path):
    root = toy_copy(tmp_path, "X = 1\n")
    _, rec, _ = run_probe(tmp_path, root, "control")
    for text in (rec["scope"], PROBE.read_text(encoding="utf-8")):
        assert "sqlite3, ctypes and ctypes.wintypes" in text and "differs from collection" in text


# ===================================================================================== fix round 5 (Codex 3e80738)
# R-N2 (Claude's ruling): every allowed kernel32 callable is wrapped on the resolution path (CTYPES_WRAPPED == the
# dlsym allowlist), and the known pre-hook raw aliases - ctypes.GetLastError, everything cached on the loaded loader /
# CDLL instances, and every module-level _CFuncPtr in sys.modules - are replaced by refusing wrappers at guard install.
# The ONLY native call any of these tests can reach is the harmless GetLastError query (refused once fixed).
def _refusal_events(rec):
    return [(r["event"], r["reason"]) for r in (rec.get("barrier") or {}).get("refusals") or []]


@pytest.mark.parametrize("src", [
    'import ctypes\nDLL = ctypes.WinDLL("kernel32", use_last_error=True)\nRESULT = DLL.GetLastError()\n',   # Codex
    "import ctypes\nRESULT = ctypes.GetLastError()\n",
    "import ctypes\nRESULT = ctypes.windll.kernel32.GetLastError()\n",
])
def test_fix5_RN2_a_get_last_error_call_is_refused(tmp_path, src):
    root = toy_copy(tmp_path, src)
    run, rec, _ = run_probe(tmp_path, root, "control")
    assert run["rc"] == 0, run
    assert ("ctypes.call_function", "foreign_call_refused") in _refusal_events(rec), (rec.get("imported"),
                                                                                    _refusal_events(rec))
    assert rec.get("imported") is not True


@pytest.mark.parametrize("mode", ["control", "mutated"])
def test_fix5_RN2_the_lock_helper_declarations_still_import_clean_in_both_modes(tmp_path, mode):
    root = toy_copy(tmp_path, LOCKS_SHAPE + "Z = 1 + 2\n")              # line 15: the mutated child's site
    spec = dict(SUB_SPEC, start=[15, 6], end=[15, 7])
    _, rec, _ = run_probe(tmp_path, root, mode, spec)
    assert rec["barrier"]["refusals"] == [] and rec["imported"] is True, (rec["barrier"], rec.get("exception"))


def test_fix5_RN2_no_raw_foreign_function_alias_survives_guard_install(tmp_path):
    src = ("import ctypes\n"
           "RAW = sorted(k for k, v in vars(ctypes).items() if isinstance(v, ctypes._CFuncPtr))\n"
           "RAWK = sorted(k for k, v in vars(ctypes.windll.kernel32).items() if isinstance(v, ctypes._CFuncPtr))\n"
           "assert RAW == [] and RAWK == [], (RAW, RAWK)\n")
    root = toy_copy(tmp_path, src)
    _, rec, _ = run_probe(tmp_path, root, "control")
    assert rec["barrier"]["refusals"] == [] and rec.get("imported") is True, rec.get("exception")
    found = set((rec["barrier"].get("guards") or {}).get("ctypes_preexisting_wrapped") or [])
    want = {"ctypes.GetLastError", "ctypes.memmove", "ctypes.memset", "ctypes._cast", "ctypes._string_at",
            "ctypes._wstring_at", "ctypes.windll.kernel32.GetLastError"}
    assert want <= found, sorted(found)


def test_fix5_RN2_the_sys_modules_scan_wraps_module_level_pointers_and_loader_caches():
    """Unit level, in-process: synthetic modules hold a raw kernel32 pointer (looked up, NEVER called), a CDLL with a
    cached pointer and a LibraryLoader with a cached CDLL; every raw pointer is replaced and recorded."""
    import ctypes
    import types
    m = _probe_mod()
    scan = _attr(m, "wrap_preexisting_foreign_functions")
    lib = ctypes.WinDLL("kernel32")
    raw = lib["GetLastError"]
    cached = ctypes.WinDLL("kernel32")
    _ = cached.GetLastError                                    # attribute access caches the pointer (no call)
    loader = ctypes.LibraryLoader(ctypes.WinDLL)
    _ = loader.kernel32.GetLastError
    mod = types.ModuleType("synthetic_fix5")
    mod.RAW, mod.ALIAS, mod.LIB, mod.LOADER, mod.OTHER = raw, raw, cached, loader, 7
    wrapped = []

    def wrap(func, label):
        wrapped.append(label)
        return ("W", label)
    found = scan({"synthetic_fix5": mod, "not_a_module": None}, wrap)
    assert set(found) == {"synthetic_fix5.RAW", "synthetic_fix5.ALIAS", "synthetic_fix5.LIB.GetLastError",
                          "synthetic_fix5.LOADER.kernel32.GetLastError"}, found
    assert mod.RAW == mod.ALIAS == ("W", "synthetic_fix5.RAW"), "one wrapper per raw pointer"
    assert vars(cached)["GetLastError"][0] == "W" and vars(vars(loader)["kernel32"])["GetLastError"][0] == "W"
    assert mod.OTHER == 7


def test_fix5_RN2_the_wrapped_set_is_derived_from_the_dlsym_allowlist():
    m = _probe_mod()
    want = {(k[1], k[2]) for k in m.CTYPES_ALLOWED if k[0] == "ctypes.dlsym"}
    assert set(_attr(m, "CTYPES_WRAPPED")) == want and ("kernel32", "GetLastError") in want, m.CTYPES_WRAPPED
    src = PROBE.read_text(encoding="utf-8")
    for name in ("GetLastError", "CreateFileW", "CloseHandle"):
        assert src.count(f'"{name}"') == 1, f"{name} is named once (CTYPES_ALLOWED), never duplicated"


def test_fix5_RN2_the_barrier_claim_is_accurate():
    m = _probe_mod()
    src = PROBE.read_text(encoding="utf-8")
    for text in (m.CLAIM, src):
        assert "resolution path" in text and "enumerated pre-hook aliases" in text, text[:400]
        assert "disclosed limit" in text and "not an OS sandbox" in text
    assert "any foreign call" not in src.lower() and "PENDING Codex" not in src


# ===================================================================================== fix round 6 (re-review 4)
# R-N2 TOCTOU: the guarded __getitem__ wraps EVERY pointer resolved while the guard is active, labelled from the names
# the hook validated. Finding 3: the hook never runs target code - a ctypes-own CDLL class by exact type, `_name` from
# the instance __dict__ as an exact str, an exact-str symbol, exact-typed path arguments (str, bytes, a stdlib path
# type), and a re-entrant event while the hook is busy is REFUSED. Ported from the re-reviewer's rr4 toys; the only
# native call any of them can reach is kernel32 GetLastError (refused once fixed).
NAME_PROPERTY_TOCTOU = (
    "import ctypes\n"
    "class D(ctypes.WinDLL):\n"
    "    _n = 0\n"
    "    @property\n"
    "    def _name(self):\n"
    "        type(self)._n += 1\n"
    "        return 'kernel32' if type(self)._n <= 1 else 'other'\n"
    "    @_name.setter\n"
    "    def _name(self, v):\n"
    "        pass\n"
    "D._n = -10\n"
    "DLL = D('kernel32')\n"
    "D._n = 0\n"
    "F = DLL['GetLastError']\n"
    "RESULT = F()\n")
NAME_EQ_TOCTOU = (
    "import ctypes\n"
    "class N(str):\n"
    "    n = 0\n"
    "    def __eq__(self, o):\n"
    "        N.n += 1\n"
    "        return str.__eq__(self, o) if N.n <= 1 else False\n"
    "    __hash__ = str.__hash__\n"
    "DLL = ctypes.WinDLL('kernel32')\n"
    "F = DLL[N('GetLastError')]\n"
    "RESULT = F()\n")


@pytest.mark.parametrize("src", [NAME_PROPERTY_TOCTOU, NAME_EQ_TOCTOU], ids=["name_property", "name_eq"])
def test_fix6_RN2_a_toctou_on_the_resolution_path_is_refused(tmp_path, src):
    root = toy_copy(tmp_path, src)
    run, rec, _ = run_probe(tmp_path, root, "control")
    assert run["rc"] == 0, run
    ev = _refusal_events(rec)
    assert ev and rec.get("imported") is not True, (rec.get("imported"), ev)


def _marker_toy(tmp_path):
    marker = tmp_path / "outside" / "escape.txt"
    marker.parent.mkdir()
    return marker


def test_fix6_F3_a_name_property_never_runs_inside_the_hook(tmp_path):
    """The re-reviewer's reentry toy: a WinDLL subclass whose _name property writes a file outside the scratch
    roots when the hook reads it. The pointer is never called."""
    marker = _marker_toy(tmp_path)
    src = ("import ctypes\n"
           "class D(ctypes.WinDLL):\n"
           "    armed = False\n"
           "    @property\n"
           "    def _name(self):\n"
           "        if D.armed:\n"
           "            D.armed = False\n"
           f"            open({str(marker)!r}, 'w').write('written from inside the audit hook')\n"
           "        return 'kernel32'\n"
           "    @_name.setter\n"
           "    def _name(self, v):\n"
           "        pass\n"
           "DLL = D('kernel32')\n"
           "D.armed = True\n"
           "F = DLL['GetLastError']\n"
           "ESCAPED = True\n")
    root = toy_copy(tmp_path, src)
    _, rec, _ = run_probe(tmp_path, root, "control")
    assert not marker.exists(), "target code ran inside the audit hook and escaped the write barrier"
    assert _refusal_events(rec) and rec.get("imported") is not True, _refusal_events(rec)


def test_fix6_F3_a_fspath_side_effect_never_runs_inside_the_hook(tmp_path):
    """A target PathLike whose FIRST __fspath__ call writes outside scratch. shutil.copyfile audits the ORIGINAL
    object before converting it (fact-checked in 3.12: shutil.copyfile and sqlite3.connect carry it; open and os.*
    carry the converted str), so the old hook's resolve() made call 1 while busy. The paths are inside scratch."""
    marker = _marker_toy(tmp_path)
    src = ("import shutil\nfrom pathlib import Path\n"
           "SRC = Path(__file__).parent / 'in.txt'\n"
           "SRC.write_text('x', encoding='utf-8')\n"
           "class P:\n"
           "    n = 0\n"
           "    def __fspath__(self):\n"
           "        P.n += 1\n"
           "        if P.n == 1:\n"
           f"            open({str(marker)!r}, 'w').write('fspath inside the hook')\n"
           "        return str(SRC)\n"
           "shutil.copyfile(P(), str(SRC) + '.copy')\n")
    root = toy_copy(tmp_path, src)
    _, rec, _ = run_probe(tmp_path, root, "control")
    assert not marker.exists(), "a target __fspath__ ran inside the audit hook"
    assert _refusal_events(rec), rec.get("exception")


@pytest.mark.parametrize("make", [
    lambda s: type("S", (str,), {})(str(s / "a")),                      # a str subclass
    lambda s: type("B", (bytes,), {})(str(s / "a").encode()),           # a bytes subclass
    lambda s: type("P", (), {"__fspath__": lambda self: str(s / "a")})(),   # a non-stdlib PathLike
])
def test_fix6_F3_non_exact_path_arguments_are_refused_without_running_their_code(tmp_path, make, monkeypatch):
    m, hook, refusals, scratch = _barrier(tmp_path)
    monkeypatch.chdir(scratch)
    v = make(scratch)
    for event, args in (("open", (v, "r", 0)), ("os.remove", (v, -1)), ("custom.event", ((v,),))):
        _refused(m, hook, event, args)
    hook("open", (str(scratch / "a"), "r", 0))                          # exact str: still allowed
    hook("open", (scratch / "a", "r", 0))                               # a stdlib Path: still allowed
    hook("open", (str(scratch / "a").encode(), "r", 0))                 # exact bytes: still allowed


def test_fix6_F3_a_re_entrant_event_while_the_hook_is_busy_is_refused(tmp_path):
    m, hook, refusals, scratch = _barrier(tmp_path)
    local = getattr(hook, "_local", None)
    assert local is not None, "the hook exposes its per-thread busy flag (hook._local)"
    local.busy = True
    try:
        _refused(m, hook, "open", (str(scratch / "a"), "r", 0))
    finally:
        local.busy = False
    assert refusals[-1]["reason"] == "reentrant_event", refusals


def test_fix6_F3_the_dlsym_branch_requires_ctypes_own_classes_and_exact_strings(tmp_path):
    import ctypes
    m, hook, refusals, _ = _barrier(tmp_path)
    k32 = ctypes.WinDLL("kernel32")                                     # loaded, never called
    sub = type("D", (ctypes.WinDLL,), {})("kernel32")
    s = type("N", (str,), {})("GetLastError")
    m._CT.active, m._CT.allowed = True, []
    try:
        hook("ctypes.dlsym", (k32, "GetLastError"))                     # the genuine shape is allowed once
        assert refusals == [] and len(m._CT.allowed) == 1
        m._CT.allowed = []
        for args in ((sub, "GetLastError"), (k32, s)):
            _refused(m, hook, "ctypes.dlsym", args)
        m._CT.allowed = []
        hook("ctypes.dlsym", (k32, "GetLastError"))
        _refused(m, hook, "ctypes.dlsym", (k32, "GetLastError"))      # a second dlsym in one window
    finally:
        m._CT.active, m._CT.allowed = False, []
    _refused(m, hook, "ctypes.dlopen", (type("N", (str,), {})("kernel32"),))
    assert refusals[-1]["event"] == "ctypes.dlopen"
