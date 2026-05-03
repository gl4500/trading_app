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


class TestFitProducesWalkforwardMetrics(unittest.TestCase):
    def _make_synthetic(self, n=600, c=14, T=10, seed=0):
        rng = np.random.default_rng(seed)
        # X with weak signal in channel 0
        X = rng.standard_normal((n, c, T)).astype(np.float32) * 0.5
        y = (X[:, 0, :].mean(axis=1) * 0.05
             + rng.standard_normal(n) * 0.01).astype(np.float32)
        t = np.linspace(0, 90 * 86400.0, n, dtype=np.float64)
        return X, y, t

    def test_fit_records_per_fold_metrics(self):
        from data.xgboost_model import SignalXGBoost
        X, y, t = self._make_synthetic()
        m = SignalXGBoost(T=10, n_channels=14)
        m.fit(X, y, t, n_folds=3, min_val_days=14)
        s = m.training_summary()
        self.assertEqual(len(s["fold_metrics"]), 3)
        for fm in s["fold_metrics"]:
            for k in ("wfe", "ic", "val_mse", "n_train", "n_val", "val_window_days"):
                self.assertIn(k, fm)

    def test_fit_records_aggregate_metrics(self):
        from data.xgboost_model import SignalXGBoost
        X, y, t = self._make_synthetic()
        m = SignalXGBoost(T=10, n_channels=14)
        m.fit(X, y, t, n_folds=3, min_val_days=14)
        s = m.training_summary()
        for k in ("mean_ic", "ir", "mean_wfe", "calibration"):
            self.assertIn(k, s)
        self.assertTrue(math.isfinite(s["mean_ic"]))

    def test_fit_marks_trained(self):
        from data.xgboost_model import SignalXGBoost
        X, y, t = self._make_synthetic()
        m = SignalXGBoost(T=10, n_channels=14)
        self.assertFalse(m.is_trained)
        m.fit(X, y, t, n_folds=3, min_val_days=14)
        self.assertTrue(m.is_trained)
        self.assertGreater(m.last_train_time, 0)

    def test_predict_after_fit_returns_floats(self):
        from data.xgboost_model import SignalXGBoost
        X, y, t = self._make_synthetic()
        m = SignalXGBoost(T=10, n_channels=14)
        m.fit(X, y, t, n_folds=3, min_val_days=14)
        x = X[0]   # single window
        pred, direction, conf = m.predict(x)
        self.assertIsInstance(pred, float)
        self.assertIn(direction, ("bull", "bear", "neutral"))
        self.assertIsInstance(conf, float)
        self.assertGreaterEqual(conf, 0.0)
        self.assertLessEqual(conf, 1.0)


if __name__ == "__main__":
    unittest.main()
