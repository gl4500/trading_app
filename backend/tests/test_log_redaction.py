"""
Secret redaction in logs (finding C-2, 2026-10-11).

httpx logs every request URL at INFO ("HTTP Request: GET <url> ..."). Massive (apiKey=) and FRED (api_key=)
authenticate with query parameters, so their keys were written to live.log and backend_stderr.log in plain
text. install_logging() must redact secret query values for every record that reaches any handler.
"""
import io
import logging
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

SECRET = "SuperSecretValue1234567890abcdef"


def _record(msg, *args, name="httpx"):
    return logging.LogRecord(name, logging.INFO, __file__, 1, msg, args, None)


class TestRedactFilter(unittest.TestCase):
    def setUp(self):
        from logging_setup import _RedactSecrets
        self.f = _RedactSecrets()

    def _out(self, rec):
        self.assertTrue(self.f.filter(rec))            # never drops a record
        return rec.getMessage()

    def test_redacts_massive_apikey_in_args(self):
        rec = _record('HTTP Request: %s %s "%s %d %s"', "GET",
                      f"https://api.massive.com/v2/reference/news?ticker=AAPL&apiKey={SECRET}", "HTTP/1.1", 200, "OK")
        out = self._out(rec)
        self.assertNotIn(SECRET, out)
        self.assertIn("apiKey=***", out)
        self.assertIn("ticker=AAPL", out)
        self.assertIn('"HTTP/1.1 200 OK"', out)

    def test_redacts_fred_api_key_mid_query(self):
        out = self._out(_record(f"GET https://api.stlouisfed.org/fred/series/observations?series_id=GDP&api_key={SECRET}"
                                "&file_type=json"))
        self.assertNotIn(SECRET, out)
        self.assertIn("api_key=***&file_type=json", out)

    def test_redacts_case_and_other_secret_params(self):
        for name in ("APIKEY", "apikey", "ApiKey", "API_KEY", "access_token", "token", "secret"):
            out = self._out(_record(f"u?a=1&{name}={SECRET}"))
            self.assertNotIn(SECRET, out, name)
            self.assertIn(f"{name}=***", out)

    def test_clean_message_untouched(self):
        rec = _record("cycle %d done in %.1fs", 3, 2.5)
        self.assertEqual(self._out(rec), "cycle 3 done in 2.5s")
        self.assertEqual(rec.args, (3, 2.5))          # args left intact when nothing to redact

    def test_does_not_redact_lookalike_words(self):
        out = self._out(_record("monkey=banana&keyboard=1&tokens_used=5"))
        self.assertEqual(out, "monkey=banana&keyboard=1&tokens_used=5")

    def test_redacts_prefixed_secret_names(self):
        # over-redaction is the safe direction: prefixed names must not slip through
        for name in ("client_secret", "x_api_key", "refresh_token", "xapikey"):
            out = self._out(_record(f"u?{name}={SECRET}&a=1"))
            self.assertNotIn(SECRET, out, name)
            self.assertIn("=***&a=1", out)

    def test_bad_format_args_never_raise(self):
        rec = _record("%s %s", "only-one")
        self.assertTrue(self.f.filter(rec))            # logging's own error path handles the bad record


class TestInstallLoggingRedacts(unittest.TestCase):
    """End to end: after install_logging(), an httpx request logged at INFO reaches handlers redacted."""

    def test_httpx_request_line_is_redacted_on_root_handlers(self):
        import httpx
        import logging_setup
        stream = io.StringIO()
        sh = logging.StreamHandler(stream)
        sh.setLevel(logging.INFO)
        logging.root.addHandler(sh)
        old_level = logging.root.level
        logging.root.setLevel(logging.INFO)
        tmp = tempfile.mkdtemp()
        try:
            with patch.object(logging_setup, "_ERROR_LOG_PATH", os.path.join(tmp, "e.log")), \
                 patch.object(logging_setup, "_ERRORS_ONLY_LOG_PATH", os.path.join(tmp, "eo.log")), \
                 patch.object(logging_setup, "_LIVE_LOG_PATH", os.path.join(tmp, "live.log")), \
                 patch.object(logging_setup, "_LOG_DIR", tmp), \
                 patch.object(logging_setup, "_write_crash"):
                logging_setup.install_logging()
                transport = httpx.MockTransport(lambda req: httpx.Response(200, json={}))
                with httpx.Client(transport=transport) as c:
                    c.get("https://api.massive.com/fed/v1/inflation", params={"limit": 1, "apiKey": SECRET})
                    c.get("https://api.stlouisfed.org/fred/series/observations", params={"api_key": SECRET})
                for h in logging.root.handlers:
                    h.flush()
            console = stream.getvalue()
            with open(os.path.join(tmp, "live.log"), encoding="utf-8") as f:
                live = f.read()
            for text in (console, live):
                self.assertIn("HTTP Request", text)
                self.assertNotIn(SECRET, text)
                self.assertIn("apiKey=***", text)
                self.assertIn("api_key=***", text)
        finally:
            logging.root.removeHandler(sh)
            for h in list(logging.root.handlers):
                if os.path.dirname(os.path.abspath(getattr(h, "baseFilename", "") or os.sep)) == os.path.abspath(tmp):
                    logging.root.removeHandler(h)
                    h.close()
            logging.root.setLevel(old_level)


if __name__ == "__main__":
    unittest.main()


class TestRedactionLayersInstalled(unittest.TestCase):
    """Both layers must be present: the source loggers AND every root handler (the console stream included)."""

    def test_filter_on_httpx_loggers_and_every_root_handler(self):
        import logging_setup
        from logging_setup import _RedactSecrets
        sh = logging.StreamHandler(io.StringIO())
        logging.root.addHandler(sh)
        tmp = tempfile.mkdtemp()
        try:
            with patch.object(logging_setup, "_ERROR_LOG_PATH", os.path.join(tmp, "e.log")), \
                 patch.object(logging_setup, "_ERRORS_ONLY_LOG_PATH", os.path.join(tmp, "eo.log")), \
                 patch.object(logging_setup, "_LIVE_LOG_PATH", os.path.join(tmp, "live.log")), \
                 patch.object(logging_setup, "_LOG_DIR", tmp), \
                 patch.object(logging_setup, "_write_crash"):
                logging_setup.install_logging()
                logging_setup.install_logging()                     # idempotent: no duplicate filters
            for name in ("httpx", "httpcore"):
                n = sum(isinstance(f, _RedactSecrets) for f in logging.getLogger(name).filters)
                self.assertEqual(n, 1, name)
            for h in logging.root.handlers:
                self.assertEqual(sum(isinstance(f, _RedactSecrets) for f in h.filters), 1, repr(h))
        finally:
            logging.root.removeHandler(sh)
            for h in list(logging.root.handlers):
                if os.path.dirname(os.path.abspath(getattr(h, "baseFilename", "") or os.sep)) == os.path.abspath(tmp):
                    logging.root.removeHandler(h)
                    h.close()
