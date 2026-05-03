"""Tests for data/signal_model.py — MODEL_BACKEND selector."""
import importlib
import unittest
from unittest.mock import patch


class TestSignalModelSelector(unittest.TestCase):
    def test_default_backend_is_cnn(self):
        with patch("config.config.MODEL_BACKEND", "cnn"):
            import data.signal_model as sm
            importlib.reload(sm)
            from data.cnn_model import signal_cnn
            self.assertIs(sm.signal_model, signal_cnn)

    def test_xgboost_backend_returns_signal_xgb(self):
        with patch("config.config.MODEL_BACKEND", "xgboost"):
            import data.signal_model as sm
            importlib.reload(sm)
            from data.xgboost_model import signal_xgb
            self.assertIs(sm.signal_model, signal_xgb)

    def test_unknown_backend_falls_back_to_cnn(self):
        with patch("config.config.MODEL_BACKEND", "lstm-attention-9000"):
            import data.signal_model as sm
            importlib.reload(sm)
            from data.cnn_model import signal_cnn
            self.assertIs(sm.signal_model, signal_cnn)


if __name__ == "__main__":
    unittest.main()
