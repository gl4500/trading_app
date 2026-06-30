import hashlib
import tempfile
import unittest
from pathlib import Path
from rnd_pod.gates import scope_violations, sha256_file, db_unchanged


class TestGates(unittest.TestCase):
    def test_scope_violations_flags_polymarket_paths(self):
        changed = [
            "backend/agents/base_agent.py",
            "../polymarket_app/backend/main.py",
            "docs/model_improvement_ledger.md",
        ]
        self.assertEqual(
            scope_violations(changed),
            ["../polymarket_app/backend/main.py"],
        )

    def test_scope_violations_flags_parent_escape(self):
        self.assertEqual(scope_violations(["../secrets.env"]), ["../secrets.env"])

    def test_scope_violations_clean(self):
        self.assertEqual(scope_violations(["backend/agents/base_agent.py"]), [])

    def test_db_unchanged(self):
        self.assertTrue(db_unchanged("abc", "abc"))
        self.assertFalse(db_unchanged("abc", "def"))

    def test_sha256_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello")
            p = Path(f.name)
        try:
            self.assertEqual(sha256_file(p), hashlib.sha256(b"hello").hexdigest())
        finally:
            p.unlink()


if __name__ == "__main__":
    unittest.main()
