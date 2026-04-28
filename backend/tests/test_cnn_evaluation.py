"""Tests for the CNN evaluation harness — IC, IR, calibration, walk-forward folds."""
import math
import unittest

import numpy as np

from data.cnn_evaluation import compute_ic, compute_ir


class TestComputeIC(unittest.TestCase):
    """Spearman rank correlation between predicted and realized returns."""

    def test_perfect_rank_correlation(self):
        # Same rank order → IC = 1.0
        y_pred = np.array([0.01, 0.02, 0.03, 0.04, 0.05], dtype=np.float32)
        y_true = np.array([0.10, 0.20, 0.30, 0.40, 0.50], dtype=np.float32)
        self.assertAlmostEqual(compute_ic(y_pred, y_true), 1.0, places=4)

    def test_inverse_rank_correlation(self):
        # Reversed rank order → IC = -1.0
        y_pred = np.array([0.05, 0.04, 0.03, 0.02, 0.01], dtype=np.float32)
        y_true = np.array([0.10, 0.20, 0.30, 0.40, 0.50], dtype=np.float32)
        self.assertAlmostEqual(compute_ic(y_pred, y_true), -1.0, places=4)

    def test_zero_correlation_returns_finite(self):
        # Random orderings → IC near 0 but always finite
        rng = np.random.default_rng(42)
        y_pred = rng.standard_normal(1000).astype(np.float32)
        y_true = rng.standard_normal(1000).astype(np.float32)
        ic = compute_ic(y_pred, y_true)
        self.assertTrue(math.isfinite(ic))
        self.assertLess(abs(ic), 0.10)

    def test_handles_constant_predictions(self):
        # Constant pred → undefined corr → returns 0.0 (safe default)
        y_pred = np.zeros(10, dtype=np.float32)
        y_true = np.arange(10, dtype=np.float32)
        self.assertEqual(compute_ic(y_pred, y_true), 0.0)

    def test_empty_input_returns_zero(self):
        self.assertEqual(compute_ic(np.array([]), np.array([])), 0.0)


class TestComputeIR(unittest.TestCase):
    """Information Ratio = mean(IC) / std(IC) across folds."""

    def test_stable_positive_ic(self):
        # IC stable around 0.05 → high IR
        ics = [0.04, 0.05, 0.06]
        ir = compute_ir(ics)
        # mean=0.05, std≈0.00816 (ddof=0); IR ≈ 6.12
        self.assertGreater(ir, 5.0)

    def test_zero_std_returns_zero(self):
        # All identical → std=0 → IR returns 0.0 (safe)
        ir = compute_ir([0.05, 0.05, 0.05])
        self.assertEqual(ir, 0.0)

    def test_empty_returns_zero(self):
        self.assertEqual(compute_ir([]), 0.0)

    def test_single_value_returns_zero(self):
        # Cannot compute std from 1 sample
        self.assertEqual(compute_ir([0.05]), 0.0)


if __name__ == "__main__":
    unittest.main()
