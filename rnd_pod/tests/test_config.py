import unittest
from pathlib import Path
from rnd_pod.config import PodConfig, default_config


class TestConfig(unittest.TestCase):
    def test_default_config_derives_paths_from_repo_root(self):
        cfg = default_config(Path("/c/Users/gl450/trading_app"))
        self.assertEqual(cfg.db_path, Path("/c/Users/gl450/trading_app/backend/trading.db"))
        self.assertEqual(cfg.ledger_path, Path("/c/Users/gl450/trading_app/docs/model_improvement_ledger.md"))
        self.assertEqual(cfg.runtime_python, Path("/c/Users/gl450/trading_app/runtime/python/python.exe"))
        self.assertEqual(cfg.model, "claude-opus-4-8")
        self.assertIn("PnL", cfg.north_star)

    def test_config_is_frozen(self):
        cfg = default_config(Path("/tmp/x"))
        with self.assertRaises(Exception):
            cfg.model = "other"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
