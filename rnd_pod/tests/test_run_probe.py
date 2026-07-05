import sys
import tempfile
import unittest
from pathlib import Path
from rnd_pod.config import default_config
from rnd_pod.run_probe import build_probe_cmd, probe_env, run_probe


class TestRunProbe(unittest.TestCase):
    def test_build_probe_cmd(self):
        # Expected paths are rendered with str(Path(...)) so the assertion is
        # correct on Windows (native separators) as well as POSIX — the command
        # must carry OS-native paths for subprocess to launch the interpreter.
        cmd = build_probe_cmd(Path("/runtime/python.exe"), Path("/x/probe.py"))
        self.assertEqual(cmd, [str(Path("/runtime/python.exe")), str(Path("/x/probe.py"))])

    def test_probe_env_sets_readonly_uri(self):
        env = probe_env(Path("/c/Users/gl450/trading_app/backend/trading.db"), base_env={"PATH": "/x"})
        self.assertEqual(env["PATH"], "/x")
        self.assertEqual(
            env["TRADING_DB_RO_URI"],
            "file:/c/Users/gl450/trading_app/backend/trading.db?mode=ro",
        )

    def test_run_probe_executes_script(self):
        # Use the current interpreter as a stand-in "runtime python" for the test.
        with tempfile.TemporaryDirectory() as d:
            script = Path(d) / "probe.py"
            script.write_text("print('probe-ran')\n", encoding="utf-8")
            cfg = default_config(Path(d))
            object.__setattr__(cfg, "runtime_python", Path(sys.executable))
            code, out = run_probe(cfg, script)
            self.assertEqual(code, 0)
            self.assertIn("probe-ran", out)


if __name__ == "__main__":
    unittest.main()
