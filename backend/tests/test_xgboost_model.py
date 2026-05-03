"""Tests for data/xgboost_model.py — XGBoost backend mirror of SignalCNN."""
import math
import unittest

import numpy as np


class TestFlattenWindow(unittest.TestCase):
    def test_2d_window_flattens_to_row_major(self):
        from data.xgboost_model import flatten_window
        x = np.arange(12, dtype=np.float32).reshape(3, 4)  # 3 channels × 4 timesteps
        flat = flatten_window(x)
        self.assertEqual(flat.shape, (12,))
        # Row-major: channel 0's 4 values first, then channel 1, etc.
        np.testing.assert_array_equal(flat, np.arange(12, dtype=np.float32))

    def test_3d_batch_flattens_to_2d(self):
        from data.xgboost_model import flatten_window
        x = np.zeros((5, 3, 4), dtype=np.float32)  # batch of 5 windows
        flat = flatten_window(x)
        self.assertEqual(flat.shape, (5, 12))


class TestSignalXGBoostInit(unittest.TestCase):
    def test_default_init_is_untrained(self):
        from data.xgboost_model import SignalXGBoost
        m = SignalXGBoost(T=10, n_channels=14)
        self.assertFalse(m.is_trained)
        self.assertEqual(m.T, 10)
        self.assertEqual(m._n_channels, 14)

    def test_predict_on_untrained_returns_neutral(self):
        from data.xgboost_model import SignalXGBoost
        m = SignalXGBoost(T=10, n_channels=14)
        x = np.zeros((14, 10), dtype=np.float32)
        pred, direction, conf = m.predict(x)
        self.assertEqual(pred, 0.0)
        self.assertEqual(direction, "neutral")
        self.assertEqual(conf, 0.0)

    def test_mean_wfe_is_none_before_fit(self):
        from data.xgboost_model import SignalXGBoost
        m = SignalXGBoost(T=10, n_channels=14)
        self.assertIsNone(m.mean_wfe)
        self.assertEqual(m.wfe_status, "UNTRAINED")


if __name__ == "__main__":
    unittest.main()
