"""
Unit tests for logging_setup — focused on the live.log INFO handler
added 2026-05-23 for the W3 blend 2-week observability watch.

The existing file handlers (error.log WARNING+, errors_only.log ERROR+)
are exercised indirectly via test_main_endpoints; this file just guards
the new INFO-level handler so a future refactor doesn't silently regress it.
"""
import logging
import os
import sys
import tempfile
import unittest
from logging.handlers import RotatingFileHandler
from unittest.mock import patch

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))


class TestLiveLogHandler(unittest.TestCase):
    """install_logging() must register a RotatingFileHandler at INFO for live.log.

    No class-level setUp/tearDown that touches root.handlers — that strips
    main's production handlers when other tests import main, breaking
    test_main_endpoints.TestFileHandlerDeduplication. Each test instead
    self-cleans any handler IT registered (see the finally: blocks).
    """

    def test_live_log_path_is_exported(self):
        from logging_setup import _LIVE_LOG_PATH
        self.assertTrue(_LIVE_LOG_PATH.endswith("live.log"),
                        f"_LIVE_LOG_PATH should target live.log, got {_LIVE_LOG_PATH}")

    def test_live_log_path_reexported_through_main(self):
        """test_main_endpoints-style tests patch `main._ERROR_LOG_PATH`; the
        new constant must be re-exported the same way."""
        import main
        self.assertTrue(hasattr(main, "_LIVE_LOG_PATH"))

    def test_add_log_handler_at_info_writes_info_messages(self):
        """_add_log_handler(path, INFO) registers a RotatingFileHandler at
        INFO that actually captures INFO records — confirms live.log will
        receive [W3_BLEND] entries.

        Calls _add_log_handler directly (not install_logging) so the test
        doesn't reach into production error.log / errors_only.log paths.
        """
        from logging_setup import _add_log_handler
        with tempfile.TemporaryDirectory() as td:
            tmp_path = os.path.join(td, "live.log")
            try:
                _add_log_handler(tmp_path, logging.INFO)
                target = os.path.abspath(tmp_path)
                matching = [
                    h for h in logging.root.handlers
                    if isinstance(h, RotatingFileHandler)
                    and os.path.abspath(getattr(h, "baseFilename", "")) == target
                ]
                self.assertEqual(len(matching), 1,
                    f"expected 1 RotatingFileHandler at {target}, got {len(matching)}")
                self.assertLessEqual(matching[0].level, logging.INFO)

                # Emit a representative INFO log and confirm it lands
                test_logger = logging.getLogger("test.live.handler")
                test_logger.setLevel(logging.INFO)
                test_logger.info("[W3_BLEND] AAPL xgb=+0.01 w3=+0.02 blend=+0.014 dir=bull flip=False")
                matching[0].flush()

                with open(tmp_path, "r", encoding="utf-8") as f:
                    contents = f.read()
                self.assertIn("[W3_BLEND]", contents,
                    "INFO-level [W3_BLEND] log must appear in live.log")
            finally:
                target = os.path.abspath(tmp_path)
                for h in list(logging.root.handlers):
                    if (isinstance(h, RotatingFileHandler)
                        and os.path.abspath(getattr(h, "baseFilename", "")) == target):
                        logging.root.removeHandler(h)
                        try: h.close()
                        except Exception: pass


if __name__ == "__main__":
    unittest.main()
