"""
Generated properties for secret redaction (C-2). Hypothesis is not part of the app runtime, so these skip there
and run in the isolated review environment (pip: hypothesis). Requirement IDs as in test_log_redaction_review1.
"""
import logging
import os
import string
import sys
import unittest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from hypothesis import given, settings, strategies as st
    HAVE_HYPOTHESIS = True
except ImportError:                                    # app runtime: skip
    HAVE_HYPOTHESIS = False

SECRET_NAMES = ["apiKey", "api_key", "APIKEY", "ApiKey", "api_KEY", "access_token", "token", "secret",
                "client_secret", "x_api_key", "refresh_token"]
# legal query-value characters (unreserved, sub-delims, ':' '@' '/' '?' and percent-escapes) except & and #
VALUE_CHARS = string.ascii_letters + string.digits + "-._~!$'()*+,;=:@/?%"


def _filtered(msg, *args):
    from logging_setup import _RedactSecrets
    rec = logging.LogRecord("httpx", logging.INFO, __file__, 1, msg, args, None)
    assert _RedactSecrets().filter(rec) is True
    return rec.getMessage()


@unittest.skipUnless(HAVE_HYPOTHESIS, "hypothesis not installed in this runtime")
class TestRedactionProperties(unittest.TestCase):
    def test_properties_require_hypothesis(self):
        """Placeholder so the app runtime reports this module as skipped rather than empty."""
        self.assertTrue(HAVE_HYPOTHESIS)

    if HAVE_HYPOTHESIS:
        @settings(max_examples=400, deadline=None)
        @given(st.sampled_from(SECRET_NAMES), st.text(VALUE_CHARS, min_size=12, max_size=40),
               st.lists(st.tuples(st.text("bcdfg", min_size=1, max_size=6), st.text("0123456789", min_size=1,
                                                                                   max_size=6)), max_size=4),
               st.integers(0, 4))
        def test_secret_value_never_survives_any_position(self, name, value, others, pos):
            params = [f"{k}={v}" for k, v in others]
            params.insert(min(pos, len(params)), f"{name}={value}")
            out = _filtered("HTTP Request: %s %s", "GET", "https://example.invalid/p?" + "&".join(params))
            self.assertNotIn(value, out)
            self.assertIn(f"{name}=***", out)
            for k, v in others:                            # benign params intact
                self.assertIn(f"{k}={v}", out)

        @settings(max_examples=300, deadline=None)
        @given(st.lists(st.tuples(st.sampled_from(SECRET_NAMES), st.text(VALUE_CHARS, min_size=12, max_size=30)),
                        min_size=1, max_size=4))
        def test_duplicates_and_multiple_secrets_all_redacted(self, pairs):
            out = _filtered("u?" + "&".join(f"{n}={v}" for n, v in pairs) + " tail")
            for _, v in pairs:
                self.assertNotIn(v, out)
            self.assertTrue(out.endswith(" tail"))

        @settings(max_examples=300, deadline=None)
        @given(st.text(max_size=200))
        def test_idempotent(self, text):
            from logging_setup import _redact
            once = _redact(text)
            self.assertEqual(_redact(once), once)

        @settings(max_examples=300, deadline=None)
        @given(st.text(alphabet="bcdfghjlmnopqruvwxyz0123456789 =&?/.,:-", max_size=120))
        def test_text_without_secret_names_unchanged(self, text):
            self.assertEqual(_filtered(text.replace("%", "")), text.replace("%", ""))

        @settings(max_examples=200, deadline=None)
        @given(st.integers(0, 4), st.integers(0, 4), st.text(VALUE_CHARS, min_size=12, max_size=30))
        def test_malformed_records_kept_and_redacted(self, n_fmt, n_args, value):
            fmt = "event " + " ".join(["%s"] * n_fmt)
            args = tuple([f"apiKey={value}"] * n_args)
            out = _filtered(fmt, *args)
            self.assertTrue(out.startswith("event") or out.startswith("<unformattable"))
            self.assertNotIn(value, out)


if __name__ == "__main__":
    unittest.main()
