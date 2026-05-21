"""Tests for data/signal_model.py — MODEL_BACKEND selector.

These tests call ``_select_backend()`` directly instead of
``importlib.reload(data.signal_model)``. Reloading the module re-runs its
``signal_model = _select_backend()`` line, swapping the process-wide singleton;
any module that already did ``from data.signal_model import signal_model``
(e.g. agents.xgb_reasoning_agent) keeps a stale alias and silently misbehaves
in unrelated tests that run later in the suite.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages")))

import data.signal_model as sm


class TestSignalModelSelector(unittest.TestCase):
    def test_default_backend_is_cnn(self):
        with patch("config.config.MODEL_BACKEND", "cnn"):
            from data.cnn_model import signal_cnn
            self.assertIs(sm._select_backend(), signal_cnn)

    def test_xgboost_backend_returns_signal_xgb(self):
        with patch("config.config.MODEL_BACKEND", "xgboost"):
            from data.xgboost_model import signal_xgb
            self.assertIs(sm._select_backend(), signal_xgb)

    def test_unknown_backend_falls_back_to_cnn(self):
        with patch("config.config.MODEL_BACKEND", "lstm-attention-9000"):
            from data.cnn_model import signal_cnn
            self.assertIs(sm._select_backend(), signal_cnn)

    def test_module_singleton_wired_via_select_backend(self):
        """The module-level ``signal_model`` is whatever ``_select_backend()``
        resolves to under the real config — checked without reloading."""
        self.assertIs(sm.signal_model, sm._select_backend())


if __name__ == "__main__":
    unittest.main()
