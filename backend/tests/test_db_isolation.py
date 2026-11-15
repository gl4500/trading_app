"""Tests must never touch the live database (backend/trading.db).

Agent tests call database.save_token_log / update_price_snapshot through
real code paths; in the main checkout those wrote into the live trading.db.
tests/_isolation.py (imported first by tests/__init__.py and by every test_*.py)
points DATABASE_URL at a temp file before anything imports config.
"""
import tests._isolation  # noqa: F401 - must precede any backend import
import ast
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from config import config
import database

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIVE_DB = os.path.normcase(os.path.realpath(os.path.join(_BACKEND, "trading.db")))
_TEMP = os.path.normcase(os.path.realpath(tempfile.gettempdir()))


class TestDatabaseIsolation(unittest.TestCase):
    def test_db_path_is_not_the_live_database(self):
        self.assertNotEqual(os.path.normcase(os.path.realpath(database.DB_PATH)), _LIVE_DB)

    def test_db_path_lives_in_the_per_run_test_dir(self):
        path = os.path.normcase(os.path.realpath(database.DB_PATH))
        self.assertTrue(path.startswith(_TEMP))
        self.assertTrue(os.path.basename(os.path.dirname(path)).startswith("trading_app_tests_"))

    def test_config_and_database_agree(self):
        self.assertEqual(config.DATABASE_URL, database.DB_PATH)


# ---------------------------------------------------------------------------
# X-14: the bootstrap must hold for every ordinary unittest entry point.
# ---------------------------------------------------------------------------
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_BOOTSTRAP = "tests._isolation"


def _prefix_violation(path):
    """Return None if the module-body prefix is [docstring] [__future__]* bootstrap-import."""
    with open(path, "r", encoding="utf-8-sig") as fh:
        tree = ast.parse(fh.read(), filename=path)
    body = list(tree.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body.pop(0)
    while (
        body
        and isinstance(body[0], ast.ImportFrom)
        and body[0].module == "__future__"
        and body[0].level == 0
    ):
        body.pop(0)
    if not body:
        return "no executable statement after the docstring/__future__ prefix"
    first = body[0]
    if (
        isinstance(first, ast.Import)
        and len(first.names) == 1
        and first.names[0].name == _BOOTSTRAP
        and first.names[0].asname is None
    ):
        return None
    return "first executable statement is not `import %s` (line %d)" % (
        _BOOTSTRAP,
        first.lineno,
    )


class TestEveryTestModuleBootstrapsFirst(unittest.TestCase):
    """AST guard over the module-body prefix of every tests/test_*.py.

    This is DETECTIVE regression coverage, not a pre-execution barrier:
    unittest discovery imports a module before any test method runs, so a
    future module that lacks the bootstrap can import backend code before this
    guard fails under top-level discovery. The guarantee covers (a) the package
    entry (run_tests.py / CI), protected by tests/__init__.py, and (b) every
    module this gate checks.
    """

    def test_every_test_module_imports_bootstrap_first(self):
        files = sorted(glob.glob(os.path.join(_TESTS_DIR, "test_*.py")))
        self.assertGreater(len(files), 0)
        bad = {}
        for path in files:
            why = _prefix_violation(path)
            if why:
                bad[os.path.basename(path)] = why
        self.assertEqual(bad, {})

    _BAD_SHAPES = {
        "late bootstrap after docstring+future": '"""d"""\nfrom __future__ import annotations\nimport os\nimport tests._isolation\n',
        "no docstring/future, bad first stmt": "import os\nimport tests._isolation\n",
        "second future then bad stmt": "from __future__ import annotations\nfrom __future__ import division\nimport os\nimport tests._isolation\n",
        "import os is the sole statement": "import os\n",
        "aliased bootstrap": "import tests._isolation as x\n",
        "multi-name bootstrap": "import tests._isolation, os\n",
        "empty file": "",
        "docstring only": '"""d"""\n',
        "call before bootstrap": "print(1)\nimport tests._isolation\n",
    }
    _GOOD_SHAPES = {
        "bare": "import tests._isolation\n",
        "docstring": '"""d"""\nimport tests._isolation  # noqa: F401\nimport os\n',
        "docstring+two futures": '"""d"""\nfrom __future__ import annotations\nfrom __future__ import division\nimport tests._isolation\n',
        "future only": "from __future__ import annotations\nimport tests._isolation\nimport os\n",
    }

    def _write(self, text):
        d = tempfile.mkdtemp(prefix="x14_guard_")
        self.addCleanup(shutil.rmtree, d, True)
        p = os.path.join(d, "test_shape.py")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        return p

    def test_guard_rejects_every_bad_shape(self):
        for name, text in self._BAD_SHAPES.items():
            with self.subTest(shape=name):
                self.assertIsNotNone(_prefix_violation(self._write(text)))

    def test_guard_accepts_valid_shapes(self):
        for name, text in self._GOOD_SHAPES.items():
            with self.subTest(shape=name):
                self.assertIsNone(_prefix_violation(self._write(text)))


_RESULT_TAG = "X14RESULT:"

_CHILD_DISCOVERY = """
import builtins, json, sys, unittest
sys.path.insert(0, sys.argv[1])
out = {"error": None, "probe": None, "found": None}
try:
    suite = unittest.TestLoader().discover(start_dir=sys.argv[2], pattern="test_probe.py")
    out["found"] = suite.countTestCases()
    out["probe"] = getattr(builtins, "_X14_PROBE", None)
except BaseException as exc:
    out["error"] = type(exc).__name__ + ": " + str(exc)
print("X14RESULT:" + json.dumps(out))
"""

# Directory the "real module" discovery regression targets. Overridable only so the
# behavioural RED can be re-run against an exported BASE copy of backend/tests.
_REAL_TESTS_DIR = _TESTS_DIR

_CHILD_REAL_DISCOVERY = """
import json, sys, unittest
sys.path.insert(0, sys.argv[1])
out = {"error": None, "imported_top_level": False, "db_path": None, "config_url": None}
try:
    unittest.TestLoader().discover(start_dir=sys.argv[2], pattern="test_db_isolation.py")
    out["imported_top_level"] = "test_db_isolation" in sys.modules
    if out["imported_top_level"]:
        import config, database
        out["db_path"] = database.DB_PATH
        out["config_url"] = config.config.DATABASE_URL
except BaseException as exc:
    out["error"] = type(exc).__name__ + ": " + str(exc)
print("X14RESULT:" + json.dumps(out))
"""

_PROBE_MODULE ="""import tests._isolation  # noqa: F401
import builtins
import unittest
import config as _config
import database

builtins._X14_PROBE = {"db_path": database.DB_PATH, "config_url": _config.config.DATABASE_URL}


class T(unittest.TestCase):
    def test_ok(self):
        pass
"""

_CHILD_DIRECT = """
import tests._isolation  # noqa: F401
print("imported")
"""

_CHILD_IDEMPOTENT = """
import glob, importlib, json, os, sys, tempfile
sys.path.insert(0, sys.argv[1])
out = {"error": None}
try:
    import tests._isolation as first
    second = importlib.import_module("tests._isolation")
    import tests._isolation as third
    out["same_object"] = first is second is third is sys.modules["tests._isolation"]
    out["bare_alias"] = "_isolation" in sys.modules
    dirs = glob.glob(os.path.join(tempfile.gettempdir(), "trading_app_tests_*"))
    out["dirs"] = len(dirs)
    out["env_dir_matches"] = os.path.dirname(os.environ["DATABASE_URL"]) in dirs
    out["boot_dir"] = os.path.dirname(os.environ["DATABASE_URL"])
except BaseException as exc:
    out["error"] = type(exc).__name__ + ": " + str(exc)
print("X14RESULT:" + json.dumps(out))
"""

_CHILD_PREIMPORT = """
import json, sys
sys.path.insert(0, sys.argv[1])
out = {"error_type": None, "message": None, "bound": None}
import config  # binds the inherited sentinel DATABASE_URL
out["bound"] = config.config.DATABASE_URL
try:
    import tests._isolation  # noqa: F401
except BaseException as exc:
    out["error_type"] = type(exc).__name__
    out["message"] = str(exc)
print("X14RESULT:" + json.dumps(out))
"""


class TestBootstrapFreshInterpreter(unittest.TestCase):
    """Fresh-interpreter regressions; children never run this module."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="x14_child_")
        self.addCleanup(shutil.rmtree, self.work, True)
        self.sentinel = os.path.join(self.work, "sentinel_inherited", "trading.db")
        self.env = dict(os.environ)
        self.env["DATABASE_URL"] = self.sentinel
        # Children inherit the environment, not the parent's in-memory sys.path
        # (run_tests.py puts backend/ and the repo site-packages on sys.path only),
        # so hand dependency-needing children the parent's existing sys.path dirs
        # followed by any ambient PYTHONPATH. Case (b) drops this entirely.
        entries = [p for p in sys.path if p and os.path.isdir(p)]
        entries += [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
        self.env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(entries))
        # Private temp root so child bootstrap dirs are countable and cleaned up.
        self.child_tmp = os.path.join(self.work, "tmproot")
        os.makedirs(self.child_tmp)
        for key in ("TMP", "TEMP", "TMPDIR"):
            self.env[key] = self.child_tmp
        self._n = 0

    def _run(self, script_text, *args, drop_pythonpath=False):
        self._n += 1
        env = dict(self.env)
        if drop_pythonpath:
            env.pop("PYTHONPATH", None)
        script = os.path.join(self.work, "child_%d.py" % self._n)
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(script_text)
        return subprocess.run(
            [sys.executable, script, *args],
            cwd=self.work,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )

    def _result(self, proc):
        for line in proc.stdout.splitlines():
            if line.startswith(_RESULT_TAG):
                return json.loads(line[len(_RESULT_TAG):])
        self.fail(
            "no result line; rc=%s stdout=%r stderr=%r"
            % (proc.returncode, proc.stdout[-400:], proc.stderr[-400:])
        )

    def test_top_level_discovery_overrides_inherited_database_url(self):
        probe_dir = os.path.join(self.work, "probe_tests")
        os.makedirs(probe_dir)
        with open(os.path.join(probe_dir, "test_probe.py"), "w", encoding="utf-8") as fh:
            fh.write(_PROBE_MODULE)
        res = self._result(self._run(_CHILD_DISCOVERY, os.path.dirname(_TESTS_DIR), probe_dir))
        self.assertIsNone(res["error"])
        self.assertIsNotNone(res["probe"], "probe module was not imported by discovery")
        bound = os.path.normcase(os.path.realpath(res["probe"]["db_path"]))
        self.assertNotEqual(bound, os.path.normcase(os.path.realpath(self.sentinel)))
        self.assertTrue(os.path.basename(os.path.dirname(bound)).startswith("trading_app_tests_"))
        self.assertEqual(res["probe"]["config_url"], res["probe"]["db_path"])

    def test_real_test_module_under_top_level_discovery_is_isolated(self):
        """X-14 itself: discover the real test_db_isolation.py as a top-level module
        (no top_level_dir) with an inherited sentinel. Discovery only imports and
        loads it; nothing runs, so nothing recurses."""
        res = self._result(
            self._run(_CHILD_REAL_DISCOVERY, os.path.dirname(_REAL_TESTS_DIR), _REAL_TESTS_DIR)
        )
        self.assertIsNone(res["error"])
        self.assertTrue(res["imported_top_level"], "test_db_isolation was not imported by discovery")
        bound = os.path.normcase(os.path.realpath(res["db_path"]))
        self.assertNotEqual(bound, os.path.normcase(os.path.realpath(self.sentinel)))
        self.assertTrue(os.path.basename(os.path.dirname(bound)).startswith("trading_app_tests_"))
        self.assertEqual(res["config_url"], res["db_path"])

    def test_direct_script_without_importable_tests_fails_closed(self):
        # No PYTHONPATH: an ambient one must not be able to make `tests` importable.
        proc = self._run(_CHILD_DIRECT, drop_pythonpath=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("ModuleNotFoundError", proc.stderr)

    def test_bootstrap_is_idempotent(self):
        res = self._result(self._run(_CHILD_IDEMPOTENT, os.path.dirname(_TESTS_DIR)))
        self.assertIsNone(res["error"])
        self.assertTrue(res["same_object"])
        self.assertFalse(res["bare_alias"])
        self.assertEqual(res["dirs"], 1)
        self.assertTrue(res["env_dir_matches"])
        # atexit cleanup: the child has exited, so its bootstrap dir must be gone.
        self.assertFalse(os.path.exists(res["boot_dir"]), "bootstrap temp dir leaked after child exit")

    def test_preimported_config_with_unsafe_binding_is_refused(self):
        res = self._result(self._run(_CHILD_PREIMPORT, os.path.dirname(_TESTS_DIR)))
        self.assertEqual(
            os.path.normcase(os.path.realpath(res["bound"])),
            os.path.normcase(os.path.realpath(self.sentinel)),
        )
        self.assertEqual(res["error_type"], "RuntimeError")
        self.assertRegex(res["message"] or "", r"imported before tests\._isolation")
