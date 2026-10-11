"""
Codex review of PR #106 (X-7 exceptions/crash hook, X-8 malformed records, X-9 value grammar), written BEFORE
the fixes. Requirement IDs:
  RED-2 exception tracebacks (caught, cached exc_text, stack_info) are redacted in every sink
  RED-3 the unhandled-exception hook writes only redacted text to crash.log and stderr
  RED-4 a malformed record carrying a credential is kept, redacted, and never raises or leaks via diagnostics
  RED-5 a secret query value is redacted through its full URL grammar (incl. sub-delimiters such as ')
Dummy credentials only; temp sinks; httpx.MockTransport (no network).
"""
import io
import logging
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

CANARY = "DUMMYcanary0123456789abcdef"


class _Sinks:
    """install_logging() into a temp dir with an extra captured console handler; collects every sink's text."""

    def __enter__(self):
        import logging_setup
        self.ls = logging_setup
        self.tmp = tempfile.mkdtemp()
        self.stream = io.StringIO()
        self.sh = logging.StreamHandler(self.stream)
        logging.root.addHandler(self.sh)
        self.old_level = logging.root.level
        logging.root.setLevel(logging.INFO)
        self.patches = [patch.object(logging_setup, "_ERROR_LOG_PATH", os.path.join(self.tmp, "error.log")),
                        patch.object(logging_setup, "_ERRORS_ONLY_LOG_PATH", os.path.join(self.tmp, "eo.log")),
                        patch.object(logging_setup, "_LIVE_LOG_PATH", os.path.join(self.tmp, "live.log")),
                        patch.object(logging_setup, "_LOG_DIR", self.tmp),
                        patch.object(logging_setup, "_CRASH_LOG_PATH", os.path.join(self.tmp, "crash.log"))]
        for p in self.patches:
            p.start()
        self.old_hook = sys.excepthook
        logging_setup.install_logging()
        return self

    def text(self):
        for h in logging.root.handlers:
            h.flush()
        out = {"console": self.stream.getvalue()}
        for n in ("error.log", "live.log", "crash.log"):
            path = os.path.join(self.tmp, n)
            out[n] = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
        return out

    def __exit__(self, *a):
        sys.excepthook = self.old_hook
        logging.root.removeHandler(self.sh)
        for h in list(logging.root.handlers):
            if os.path.dirname(os.path.abspath(getattr(h, "baseFilename", "") or os.sep)) == os.path.abspath(self.tmp):
                logging.root.removeHandler(h)
                h.close()
        for p in self.patches:
            p.stop()
        logging.root.setLevel(self.old_level)
        return False


class TestExceptionRedaction(unittest.TestCase):          # RED-2 (X-7)
    def test_caught_exception_traceback_redacted_in_all_sinks(self):
        with _Sinks() as s:
            try:
                raise RuntimeError(f"fetch failed for https://example.invalid/?api_key={CANARY}&x=1")
            except RuntimeError:
                logging.getLogger("data.fred_client").exception("request failed")
            out = s.text()
        for sink in ("console", "error.log", "live.log"):
            self.assertIn("request failed", out[sink], sink)
            self.assertIn("RuntimeError", out[sink], sink)          # useful context kept
            self.assertNotIn(CANARY, out[sink], sink)

    def test_cached_exc_text_and_stack_info_redacted(self):
        with _Sinks() as s:
            lg = logging.getLogger("x")
            rec = lg.makeRecord("x", logging.ERROR, __file__, 1, "boom", (), None,
                                sinfo=f"Stack (most recent call last):\n  url?token={CANARY}")
            rec.exc_text = f"Traceback ...\nValueError: secret={CANARY}"
            lg.handle(rec)
            out = s.text()
        for sink in ("console", "error.log", "live.log"):
            self.assertNotIn(CANARY, out[sink], sink)


class TestCrashHookRedaction(unittest.TestCase):          # RED-3 (X-7)
    def test_unhandled_exception_hook_redacts_crash_log_and_stderr(self):
        with _Sinks() as s:
            err = io.StringIO()
            try:
                raise KeyError(f"https://example.invalid/?apiKey={CANARY}")
            except KeyError:
                et, ev, tb = sys.exc_info()
            with redirect_stderr(err):
                sys.excepthook(et, ev, tb)
            out = s.text()
        self.assertIn("UNHANDLED EXCEPTION", out["crash.log"])
        self.assertIn("KeyError", out["crash.log"])
        for sink in ("crash.log", "console", "error.log"):
            self.assertNotIn(CANARY, out[sink], sink)
        self.assertIn("KeyError", err.getvalue())
        self.assertNotIn(CANARY, err.getvalue())


class TestMalformedRecord(unittest.TestCase):             # RED-4 (X-8)
    def test_malformed_record_kept_redacted_and_quiet(self):
        with _Sinks() as s:
            diag = io.StringIO()
            with redirect_stderr(diag):
                logging.getLogger("httpx").info("bad url %s %s", f"https://example.invalid/?apiKey={CANARY}")
                logging.getLogger("other.module").warning("bad %d", f"token={CANARY}")
            out = s.text()
        for sink in ("console", "live.log"):
            self.assertIn("bad url", out[sink], sink)                # event retained
            self.assertNotIn(CANARY, out[sink], sink)
        self.assertIn("bad", out["error.log"])
        self.assertNotIn(CANARY, out["error.log"])
        self.assertNotIn(CANARY, diag.getvalue())                    # no raw diagnostic
        self.assertNotIn("Traceback", diag.getvalue())               # nothing escaped logging


class TestValueGrammar(unittest.TestCase):                # RED-5 (X-9)
    def test_real_httpx_literal_apostrophe_in_value(self):
        import httpx
        with _Sinks() as s:
            with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as c:
                c.get(f"https://example.invalid/?api_key=prefix'{CANARY}&page=2")
            out = s.text()
        self.assertIn("api_key=***", out["console"])
        self.assertIn("page=2", out["console"])
        self.assertNotIn(CANARY, out["console"])
        self.assertNotIn(CANARY, out["live.log"])

    def test_quoted_and_encoded_values(self):
        from logging_setup import _RedactSecrets
        f = _RedactSecrets()
        for v in (f"%27{CANARY}", f"a!$()*+,;={CANARY}", f"{CANARY}%26x", f"'{CANARY}'"):
            rec = logging.LogRecord("httpx", logging.INFO, __file__, 1, f"GET u?apiKey={v}&next=ok", (), None)
            f.filter(rec)
            self.assertNotIn(CANARY, rec.getMessage(), v)
            self.assertIn("next=ok", rec.getMessage(), v)


if __name__ == "__main__":
    unittest.main()


class TestFilterOrdering(unittest.TestCase):              # RED-4 ordering: redaction runs before Win10054
    def test_malformed_record_on_root_logger_itself(self):
        with _Sinks() as s:
            diag = io.StringIO()
            with redirect_stderr(diag):
                logging.getLogger().warning("root bad %d", f"token={CANARY}")
            out = s.text()
        self.assertIn("root bad", out["error.log"])
        self.assertNotIn(CANARY, out["error.log"] + out["console"] + diag.getvalue())

    def test_file_handlers_alone_handle_malformed_record(self):
        import logging_setup
        saved = list(logging.root.handlers)
        for h in saved:
            logging.root.removeHandler(h)
        tmp = tempfile.mkdtemp()
        try:
            with patch.object(logging_setup, "_ERROR_LOG_PATH", os.path.join(tmp, "error.log")), \
                 patch.object(logging_setup, "_ERRORS_ONLY_LOG_PATH", os.path.join(tmp, "eo.log")), \
                 patch.object(logging_setup, "_LIVE_LOG_PATH", os.path.join(tmp, "live.log")), \
                 patch.object(logging_setup, "_LOG_DIR", tmp), \
                 patch.object(logging_setup, "_write_crash"):
                old_hook = sys.excepthook
                logging_setup.install_logging()
                sys.excepthook = old_hook
                diag = io.StringIO()
                with redirect_stderr(diag):
                    logging.getLogger("some.module").warning("bad %d", f"apiKey={CANARY}")
                for h in logging.root.handlers:
                    h.flush()
            text = open(os.path.join(tmp, "error.log"), encoding="utf-8").read()
            self.assertIn("bad", text)
            self.assertNotIn(CANARY, text + diag.getvalue())
        finally:
            for h in list(logging.root.handlers):
                logging.root.removeHandler(h)
                h.close()
            for h in saved:
                logging.root.addHandler(h)


class TestInstallFirstAndHookRobustness(unittest.TestCase):
    def test_redaction_goes_ahead_of_several_existing_filters(self):
        from logging_setup import _RedactSecrets, _install_first
        lg = logging.getLogger("multi.filter.test")
        a, b = logging.Filter("x"), logging.Filter("y")
        lg.filters[:] = [a, b]
        try:
            f = _RedactSecrets()
            _install_first(lg, f)
            _install_first(lg, _RedactSecrets())                   # second call is a no-op
            self.assertIs(lg.filters[0], f)
            self.assertEqual(len(lg.filters), 3)
        finally:
            lg.filters[:] = []

    def test_crash_hook_never_raises_when_stderr_write_fails(self):
        import logging_setup

        class Broken(io.StringIO):
            def write(self, *_):
                raise OSError("stderr closed")
        tmp = tempfile.mkdtemp()
        with patch.object(logging_setup, "_CRASH_LOG_PATH", os.path.join(tmp, "crash.log")):
            try:
                raise ValueError(f"token={CANARY}")
            except ValueError:
                et, ev, tb = sys.exc_info()
            with redirect_stderr(Broken()):
                logging_setup._crash_excepthook(et, ev, tb)       # must not raise
            text = open(os.path.join(tmp, "crash.log"), encoding="utf-8").read()
        self.assertIn("ValueError", text)
        self.assertNotIn(CANARY, text)

    def test_write_crash_never_raises_on_unwritable_path(self):
        import logging_setup
        with patch.object(logging_setup, "_CRASH_LOG_PATH", os.path.join(tempfile.mkdtemp(), "nodir", "\0bad")):
            logging_setup._write_crash(f"apiKey={CANARY}")         # must not raise
