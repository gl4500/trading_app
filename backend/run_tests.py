"""
Test runner for the trading app backend.
Run from the backend/ directory:
  python run_tests.py
  python run_tests.py -v
"""
import sys
import os

# ── Path setup ────────────────────────────────────────────────────────────────
# 1. backend/ itself (for config, database, trading, agents, data)
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
# 2. site-packages/ two levels up from backend/ (self-contained runtime)
SITE_PACKAGES = os.path.join(BACKEND_DIR, "..", "site-packages")
SITE_PACKAGES = os.path.normpath(SITE_PACKAGES)

for p in (BACKEND_DIR, SITE_PACKAGES):
    if p not in sys.path:
        sys.path.insert(0, p)

import unittest

verbosity = 2 if "-v" in sys.argv or "--verbose" in sys.argv else 1

loader = unittest.TestLoader()
suite = loader.discover(
    start_dir=os.path.join(BACKEND_DIR, "tests"),
    pattern="test_*.py",
    top_level_dir=BACKEND_DIR,
)

runner = unittest.TextTestRunner(verbosity=verbosity, buffer=True)
result = runner.run(suite)

total   = result.testsRun
failed  = len(result.failures)
errors  = len(result.errors)
skipped = len(result.skipped)
passed  = total - failed - errors - skipped

print()
print("=" * 60)
print(f"RESULT: {total} tests | {passed} passed | "
      f"{failed} failed | {errors} errors | {skipped} skipped")
print("=" * 60)

sys.exit(0 if result.wasSuccessful() else 1)
