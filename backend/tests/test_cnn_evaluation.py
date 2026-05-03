"""Tests for the CNN evaluation harness — IC, IR, calibration, walk-forward folds."""
import math
import unittest

import numpy as np

from data.cnn_evaluation import compute_ic, compute_ir, compute_calibration, walkforward_folds


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


class TestComputeICTieHandling(unittest.TestCase):
    """Spearman correlation must use average ranks for ties (not order-dependent)."""

    def test_ties_are_handled_with_average_ranks(self):
        # With ties, naive argsort assigns arbitrary ranks. Pandas Spearman
        # uses average ranks. The IC should be order-independent.
        y_pred_a = np.array([1.0, 1.0, 2.0, 3.0], dtype=np.float32)
        y_pred_b = np.array([1.0, 1.0, 2.0, 3.0], dtype=np.float32)
        y_true_a = np.array([0.0, 1.0, 2.0, 3.0], dtype=np.float32)
        y_true_b = np.array([1.0, 0.0, 2.0, 3.0], dtype=np.float32)
        # The two y_true vectors only differ in the order of values that
        # tie in y_pred — so the IC should be identical.
        self.assertAlmostEqual(
            compute_ic(y_pred_a, y_true_a),
            compute_ic(y_pred_b, y_true_b),
            places=6,
        )


class TestComputeCalibration(unittest.TestCase):
    """Quintile calibration: bucket predictions, compare mean pred vs mean realized per bucket."""

    def test_perfect_calibration(self):
        # If pred == true exactly, every bucket has mean_pred ≈ mean_actual
        rng = np.random.default_rng(7)
        y = rng.standard_normal(1000).astype(np.float32) * 0.02
        buckets = compute_calibration(y, y, n_buckets=5)
        self.assertEqual(len(buckets), 5)
        for b in buckets:
            self.assertAlmostEqual(b["mean_pred"], b["mean_actual"], places=4)
            self.assertGreater(b["count"], 0)

    def test_bucket_count_matches_request(self):
        rng = np.random.default_rng(0)
        pred = rng.standard_normal(500)
        true = rng.standard_normal(500)
        buckets = compute_calibration(pred, true, n_buckets=5)
        self.assertEqual(len(buckets), 5)
        self.assertEqual(sum(b["count"] for b in buckets), 500)

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(compute_calibration(np.array([]), np.array([])), [])

    def test_buckets_ordered_by_predicted_quantile(self):
        # Bucket 0 should have lowest mean_pred, bucket -1 highest
        rng = np.random.default_rng(1)
        pred = rng.standard_normal(1000)
        true = rng.standard_normal(1000)
        buckets = compute_calibration(pred, true, n_buckets=5)
        means = [b["mean_pred"] for b in buckets]
        self.assertEqual(means, sorted(means))


ONE_DAY = 86400.0


class TestWalkforwardFolds(unittest.TestCase):
    """Time-ordered fold generator: each fold's val window ≥ min_val_days, 1-bar embargo."""

    def test_fold_count_matches_request(self):
        # 60 days of daily timestamps
        ts = np.arange(0, 60 * ONE_DAY, ONE_DAY, dtype=np.float64)
        folds = walkforward_folds(ts, n_folds=3, min_val_days=14, embargo_bars=1)
        self.assertEqual(len(folds), 3)

    def test_train_always_precedes_val(self):
        ts = np.arange(0, 90 * ONE_DAY, ONE_DAY, dtype=np.float64)
        for tr, va in walkforward_folds(ts, n_folds=3, min_val_days=14, embargo_bars=1):
            self.assertGreater(ts[va].min(), ts[tr].max(),
                               "validation must start strictly after training ends")

    def test_embargo_gap_enforced(self):
        ts = np.arange(0, 90 * ONE_DAY, ONE_DAY, dtype=np.float64)
        for tr, va in walkforward_folds(ts, n_folds=3, min_val_days=14, embargo_bars=2):
            gap = ts[va].min() - ts[tr].max()
            self.assertGreaterEqual(gap, 2 * ONE_DAY - 1e-3)

    def test_min_val_days_respected(self):
        ts = np.arange(0, 90 * ONE_DAY, ONE_DAY, dtype=np.float64)
        for tr, va in walkforward_folds(ts, n_folds=3, min_val_days=14, embargo_bars=1):
            val_window = ts[va].max() - ts[va].min()
            self.assertGreaterEqual(val_window, 13 * ONE_DAY,
                                    "val window must span at least min_val_days")

    def test_too_short_dataset_returns_empty(self):
        # 10 days with min_val_days=14 → impossible
        ts = np.arange(0, 10 * ONE_DAY, ONE_DAY, dtype=np.float64)
        folds = walkforward_folds(ts, n_folds=3, min_val_days=14, embargo_bars=1)
        self.assertEqual(folds, [])

    def test_unsorted_timestamps_are_handled(self):
        # Pass deliberately scrambled timestamps; fold generator must sort first
        ts = np.array([5, 3, 1, 8, 2, 6, 9, 4, 7, 0], dtype=np.float64) * ONE_DAY
        folds = walkforward_folds(ts, n_folds=3, min_val_days=1, embargo_bars=0)
        for tr, va in folds:
            self.assertGreater(ts[va].min(), ts[tr].max())

    def test_val_sets_are_disjoint_at_fold_boundaries(self):
        # Place a sample exactly on a fold boundary. Previously both fold 0
        # and fold 1 would include it (closed-closed intervals). Now fold 0
        # claims it (closed upper bound) and fold 1 excludes it (half-open).
        ts = np.arange(0, 90 * ONE_DAY, ONE_DAY, dtype=np.float64)
        folds = walkforward_folds(ts, n_folds=3, min_val_days=14, embargo_bars=1)
        all_val_idx: set = set()
        for _tr, va in folds:
            for idx in va.tolist():
                self.assertNotIn(idx, all_val_idx,
                                 f"sample idx {idx} appeared in multiple val folds")
                all_val_idx.add(idx)


if __name__ == "__main__":
    unittest.main()
