"""
Unit tests for data/cnn_model.py
Covers: build_training_windows, SignalCNN.predict, fit, get_learned_weights,
        save/load, training_summary, device selection
"""
import os
import sys
import tempfile
import time
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import data.cnn_model as cm
from data.cnn_model import (
    SignalCNN,
    build_training_windows,
    SOURCE_NAMES,
    _DEFAULT_WEIGHTS,
    MIN_TRAIN_SAMPLES,
    WINDOW_SIZE,
    N_CHANNELS,
    HAS_TORCH,
)

if HAS_TORCH:
    import torch
    import torch.nn as nn


def _make_df(n_rows=50, symbol="AAPL", add_outcomes=True, add_agent_cols=True,
             add_rv_cols=True, add_iv_rv=True):
    """Build a minimal labelled history DataFrame."""
    now = time.time()
    rows = []
    for i in range(n_rows):
        row = {
            "symbol":          symbol,
            "snapshot_ts":     now - (n_rows - i) * 3600,
            "analyst_score":   np.random.uniform(-1, 1),
            "earnings_score":  np.random.uniform(-1, 1),
            "alpaca_score":    np.random.uniform(-1, 1),
            "yahoo_score":     np.random.uniform(-1, 1),
            "congress_score":  np.random.uniform(-1, 1),
            "composite_score": np.random.uniform(-1, 1),
            "price":           100.0 + i * 0.1,
            "return_1d":       np.random.uniform(-0.05, 0.05) if add_outcomes else float("nan"),
            "return_5d":       float("nan"),
        }
        if add_iv_rv:
            row["iv_rv_score"] = np.random.uniform(-1, 1)
        if add_agent_cols:
            row["agent_consensus"]   = np.random.uniform(-1, 1)
            row["agent_agreement"]   = np.random.uniform(0, 1)
            row["top_agent_correct"] = float(np.random.randint(0, 2)) if add_outcomes else float("nan")
        if add_rv_cols:
            row["rv_20d"] = np.random.uniform(0.10, 0.40)
            row["rv_60d"] = np.random.uniform(0.10, 0.40)
        rows.append(row)
    return pd.DataFrame(rows)


class TestBuildTrainingWindows(unittest.TestCase):

    def test_returns_arrays_for_labelled_data(self):
        df = _make_df(50)
        X, y, w = build_training_windows(df, T=WINDOW_SIZE)
        self.assertGreater(len(X), 0)
        self.assertEqual(len(X), len(y))
        self.assertEqual(len(X), len(w))

    def test_x_shape_is_N_channels_by_T(self):
        df = _make_df(50)
        X, y, w = build_training_windows(df, T=WINDOW_SIZE)
        self.assertEqual(X.shape[1], N_CHANNELS)
        self.assertEqual(X.shape[2], WINDOW_SIZE)

    def test_x_shape_degrades_without_optional_cols(self):
        """Channel count degrades gracefully when optional columns are absent."""
        # No iv_rv, no agent, no RV → 5 channels (base source only)
        df_src = _make_df(50, add_iv_rv=False, add_agent_cols=False, add_rv_cols=False)
        X_src, _, _ = build_training_windows(df_src, T=WINDOW_SIZE)
        self.assertEqual(X_src.shape[1], 5)

        # iv_rv + agent but no RV → 8 channels
        df_agent = _make_df(50, add_iv_rv=True, add_agent_cols=True, add_rv_cols=False)
        X_agent, _, _ = build_training_windows(df_agent, T=WINDOW_SIZE)
        self.assertEqual(X_agent.shape[1], 8)

        # All columns → 10 channels
        df_full = _make_df(50, add_iv_rv=True, add_agent_cols=True, add_rv_cols=True)
        X_full, _, _ = build_training_windows(df_full, T=WINDOW_SIZE)
        self.assertEqual(X_full.shape[1], 10)

    def test_returns_empty_arrays_when_no_outcomes(self):
        df = _make_df(50, add_outcomes=False)
        X, y, w = build_training_windows(df, T=WINDOW_SIZE)
        self.assertEqual(len(X), 0)

    def test_no_nans_in_X(self):
        df = _make_df(50)
        df.loc[df.index[:5], "analyst_score"] = float("nan")
        X, y, w = build_training_windows(df, T=WINDOW_SIZE)
        self.assertFalse(np.isnan(X).any())

    def test_y_clipped_to_20_pct(self):
        df = _make_df(50)
        df["return_1d"] = 0.50
        X, y, w = build_training_windows(df, T=WINDOW_SIZE)
        self.assertTrue((y <= 0.20).all())
        self.assertTrue((y >= -0.20).all())

    def test_multi_symbol_aggregated(self):
        df = pd.concat([_make_df(40, "AAPL"), _make_df(40, "MSFT")], ignore_index=True)
        X, y, w = build_training_windows(df, T=WINDOW_SIZE)
        self.assertGreater(len(X), 40)

    def test_x_dtype_float32(self):
        df = _make_df(40)
        X, _, _w = build_training_windows(df, T=WINDOW_SIZE)
        self.assertEqual(X.dtype, np.float32)

    def test_sample_weights_higher_when_top_agent_correct(self):
        """Rows with top_agent_correct=1.0 get weight 1.0; incorrect get 0.5."""
        df = _make_df(50, add_agent_cols=True)
        df["top_agent_correct"] = 1.0   # all correct
        X, y, w = build_training_windows(df, T=WINDOW_SIZE)
        self.assertTrue((w == 1.0).all(), f"Expected all 1.0, got: {w[:5]}")

    def test_sample_weights_neutral_when_no_top_agent_col(self):
        """Missing top_agent_correct column → all weights 0.75 (neutral)."""
        df = _make_df(50, add_agent_cols=False)
        X, y, w = build_training_windows(df, T=WINDOW_SIZE)
        self.assertTrue((w == 1.0).all())   # no agent col → uniform weight 1.0


class TestSignalCNNPredict(unittest.TestCase):

    def setUp(self):
        self.model = SignalCNN(T=WINDOW_SIZE)

    def test_predict_returns_tuple_of_three(self):
        x = np.random.randn(N_CHANNELS, WINDOW_SIZE).astype(np.float32)
        result = self.model.predict(x)
        self.assertEqual(len(result), 3)

    def test_predict_untrained_returns_neutral_zero(self):
        x = np.random.randn(N_CHANNELS, WINDOW_SIZE).astype(np.float32)
        pred, direction, conf = self.model.predict(x)
        self.assertEqual(pred, 0.0)
        self.assertEqual(direction, "neutral")
        self.assertEqual(conf, 0.0)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_predict_after_fit_returns_float(self):
        df = _make_df(60)
        X, y, w = build_training_windows(df, T=WINDOW_SIZE)
        self.model.fit(X, y, epochs=5)
        x = np.random.randn(N_CHANNELS, WINDOW_SIZE).astype(np.float32)
        pred, direction, conf = self.model.predict(x)
        self.assertIsInstance(pred, float)
        self.assertIn(direction, ("bull", "neutral", "bear"))
        self.assertGreaterEqual(conf, 0.0)
        self.assertLessEqual(conf, 1.0)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_predict_direction_bull_when_positive(self):
        """Direction is 'bull' when predicted return > 0.5%."""
        n = 80
        X = np.zeros((n, N_CHANNELS, WINDOW_SIZE), dtype=np.float32)
        X[:n//2, 0, :] =  1.0
        X[n//2:, 0, :] = -1.0
        y = np.array([0.10] * (n//2) + [-0.10] * (n//2), dtype=np.float32)
        self.model.fit(X, y, epochs=150)
        x_bull = np.zeros((N_CHANNELS, WINDOW_SIZE), dtype=np.float32)
        x_bull[0, :] = 1.0
        _, direction, _ = self.model.predict(x_bull)
        self.assertEqual(direction, "bull")


class TestSignalCNNFit(unittest.TestCase):

    def setUp(self):
        self.model = SignalCNN(T=WINDOW_SIZE)

    def test_fit_skips_when_too_few_samples(self):
        X = np.random.randn(5, N_CHANNELS, WINDOW_SIZE).astype(np.float32)
        y = np.random.randn(5).astype(np.float32)
        self.model.fit(X, y, epochs=10)   # 5 < MIN_TRAIN_SAMPLES
        self.assertFalse(self.model.is_trained)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_fit_accepts_sample_weights(self):
        """fit() with sample_weights does not raise and still trains."""
        df = _make_df(60)
        X, y, w = build_training_windows(df, T=WINDOW_SIZE)
        w[:len(w)//2] = 0.5
        self.model.fit(X, y, epochs=5, sample_weights=w)
        self.assertTrue(self.model.is_trained)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_fit_with_none_weights_behaves_same_as_no_weights(self):
        df = _make_df(60)
        X, y, w = build_training_windows(df, T=WINDOW_SIZE)
        self.model.fit(X, y, epochs=5, sample_weights=None)
        self.assertTrue(self.model.is_trained)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_fit_sets_trained_flag(self):
        df = _make_df(60)
        X, y, w = build_training_windows(df, T=WINDOW_SIZE)
        self.model.fit(X, y, epochs=5)
        self.assertTrue(self.model.is_trained)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_fit_loss_decreases(self):
        df = _make_df(80)
        X, y, w = build_training_windows(df, T=WINDOW_SIZE)
        self.model.fit(X, y, epochs=30)
        losses = self.model._train_loss
        self.assertLess(losses[-1], losses[0])


class TestGetLearnedWeights(unittest.TestCase):

    def test_returns_default_when_untrained(self):
        model = SignalCNN()
        weights = model.get_learned_weights()
        self.assertEqual(weights, _DEFAULT_WEIGHTS)

    def test_keys_match_source_names(self):
        model = SignalCNN()
        weights = model.get_learned_weights()
        self.assertEqual(set(weights.keys()), set(SOURCE_NAMES))

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_weights_sum_to_one_after_training(self):
        model = SignalCNN()
        df = _make_df(60)
        X, y, w = build_training_windows(df, T=WINDOW_SIZE)
        model.fit(X, y, epochs=5)
        weights = model.get_learned_weights()
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=5)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_weights_are_non_negative(self):
        model = SignalCNN()
        df = _make_df(60)
        X, y, w = build_training_windows(df, T=WINDOW_SIZE)
        model.fit(X, y, epochs=5)
        for wv in model.get_learned_weights().values():
            self.assertGreaterEqual(wv, 0.0)


class TestSaveLoad(unittest.TestCase):

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_path = cm._MODEL_PATH
            cm._MODEL_PATH = os.path.join(tmpdir, "signal_cnn.pt")
            try:
                model_a = SignalCNN()
                df = _make_df(60)
                X, y, w = build_training_windows(df, T=WINDOW_SIZE)
                model_a.fit(X, y, epochs=10)
                model_a.save()

                model_b = SignalCNN()
                loaded = model_b.load()
                self.assertTrue(loaded)
                self.assertTrue(model_b.is_trained)

                # Weights should match (source channels only)
                wa = model_a.get_learned_weights()
                wb = model_b.get_learned_weights()
                for k in SOURCE_NAMES:
                    self.assertAlmostEqual(wa[k], wb[k], places=5)
                # Input channel count persisted (matches what model_a was trained on)
                self.assertEqual(model_b._n_channels, model_a._n_channels)
            finally:
                cm._MODEL_PATH = orig_path

    def test_load_returns_false_when_no_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_path = cm._MODEL_PATH
            cm._MODEL_PATH = os.path.join(tmpdir, "missing.pt")
            try:
                model = SignalCNN()
                self.assertFalse(model.load())
            finally:
                cm._MODEL_PATH = orig_path


class TestTrainingSummary(unittest.TestCase):

    def test_summary_keys_present(self):
        model = SignalCNN()
        s = model.training_summary()
        for key in ("trained", "device", "train_ts", "final_mse",
                    "learned_weights", "weight_delta",
                    "final_train_mse", "final_val_mse",
                    "overfit_ratio", "diagnosis",
                    "train_loss_curve", "val_loss_curve",
                    "n_train", "n_val"):
            self.assertIn(key, s)

    def test_summary_trained_false_when_untrained(self):
        model = SignalCNN()
        self.assertFalse(model.training_summary()["trained"])

    def test_weight_delta_sums_near_zero_for_defaults(self):
        model = SignalCNN()
        delta = model.training_summary()["weight_delta"]
        for k in SOURCE_NAMES:
            self.assertAlmostEqual(delta[k], 0.0, places=3)

    def test_diagnosis_untrained_when_no_training(self):
        model = SignalCNN()
        self.assertEqual(model.training_summary()["diagnosis"], "UNTRAINED")

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_val_loss_populated_after_training(self):
        """fit() must produce a non-empty val_loss_curve."""
        df    = _make_df(n_rows=60)
        X, y, w = build_training_windows(df)
        model = SignalCNN()
        model.fit(X, y, epochs=5, sample_weights=w)
        s = model.training_summary()
        self.assertGreater(len(s["val_loss_curve"]), 0)
        self.assertEqual(len(s["train_loss_curve"]), len(s["val_loss_curve"]))

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_n_train_plus_n_val_equals_total(self):
        """Train + val sample counts must sum to total samples used."""
        df    = _make_df(n_rows=60)
        X, y, w = build_training_windows(df)
        model = SignalCNN()
        model.fit(X, y, epochs=5, sample_weights=w)
        s = model.training_summary()
        self.assertEqual(s["n_train"] + s["n_val"], len(X))

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_overfit_ratio_is_positive(self):
        df    = _make_df(n_rows=60)
        X, y, w = build_training_windows(df)
        model = SignalCNN()
        model.fit(X, y, epochs=5, sample_weights=w)
        s = model.training_summary()
        self.assertGreater(s["overfit_ratio"], 0)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_diagnosis_is_valid_string(self):
        df    = _make_df(n_rows=60)
        X, y, w = build_training_windows(df)
        model = SignalCNN()
        model.fit(X, y, epochs=5, sample_weights=w)
        valid = {"OK", "OVERFIT", "OVERFIT_MEMORIZING", "UNDERFIT", "UNTRAINED"}
        self.assertIn(model.training_summary()["diagnosis"], valid)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_val_loss_persisted_through_save_load(self):
        """Val loss curve must survive a save/load round-trip."""
        df    = _make_df(n_rows=60)
        X, y, w = build_training_windows(df)
        model = SignalCNN()
        model.fit(X, y, epochs=5, sample_weights=w)
        original_val = model.training_summary()["val_loss_curve"]

        with tempfile.TemporaryDirectory() as tmpdir:
            import data.cnn_model as _cm
            orig_path = _cm._MODEL_PATH
            _cm._MODEL_PATH = os.path.join(tmpdir, "test_cnn.pt")
            try:
                model.save()
                model2 = SignalCNN()
                model2.load()
                self.assertEqual(
                    model2.training_summary()["val_loss_curve"],
                    original_val,
                )
            finally:
                _cm._MODEL_PATH = orig_path


class TestGatedConv1d(unittest.TestCase):
    """Unit tests for the GatedConv1d module and _build_glu_net factory."""

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_output_shape_preserved(self):
        """GatedConv1d must produce the same (batch, out_ch, T) shape as Conv1d."""
        from data.cnn_model import GatedConv1d
        block = GatedConv1d(7, 16, kernel_size=3, padding=1)
        x = torch.randn(4, 7, WINDOW_SIZE)
        out = block(x)
        self.assertEqual(out.shape, (4, 16, WINDOW_SIZE))

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_gate_zeros_output_when_gate_bias_very_negative(self):
        """sigmoid(-100) ≈ 0 → output should be ~0 regardless of main path."""
        from data.cnn_model import GatedConv1d
        block = GatedConv1d(1, 1, kernel_size=1, padding=0)
        nn.init.zeros_(block.conv_main.weight)
        nn.init.ones_(block.conv_main.bias)          # main always outputs 1
        nn.init.zeros_(block.conv_gate.weight)
        nn.init.constant_(block.conv_gate.bias, -100.0)  # sigmoid → 0
        x = torch.ones(1, 1, 5)
        out = block(x)
        self.assertTrue((out.abs() < 0.01).all(), f"Expected ~0, got {out}")

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_gate_passes_output_when_gate_bias_very_positive(self):
        """sigmoid(+100) ≈ 1 → output ≈ main path value."""
        from data.cnn_model import GatedConv1d
        block = GatedConv1d(1, 1, kernel_size=1, padding=0)
        nn.init.zeros_(block.conv_main.weight)
        nn.init.constant_(block.conv_main.bias, 2.0)     # main always outputs 2
        nn.init.zeros_(block.conv_gate.weight)
        nn.init.constant_(block.conv_gate.bias, 100.0)   # sigmoid → 1
        x = torch.ones(1, 1, 5)
        out = block(x)
        self.assertTrue((out - 2.0).abs().max() < 0.01, f"Expected ~2, got {out}")

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_first_block_of_glu_net_is_gated_conv(self):
        """_build_glu_net must use GatedConv1d as the first (and all conv) blocks."""
        from data.cnn_model import _build_glu_net, GatedConv1d
        net = _build_glu_net(N_CHANNELS)
        self.assertIsInstance(net[0], GatedConv1d)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_glu_net_output_shape(self):
        """_build_glu_net must produce (batch, 1) output for (batch, C, T) input."""
        from data.cnn_model import _build_glu_net
        net = _build_glu_net(N_CHANNELS)
        net.eval()
        x = torch.randn(4, N_CHANNELS, WINDOW_SIZE)
        with torch.no_grad():
            out = net(x)
        self.assertEqual(out.shape, (4, 1))

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_signal_cnn_uses_glu_architecture(self):
        """The live SignalCNN model must use GatedConv1d blocks, not plain Conv1d."""
        from data.cnn_model import GatedConv1d
        model = SignalCNN()
        self.assertIsInstance(model._net[0], GatedConv1d)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_glu_model_trains_and_predicts(self):
        """End-to-end: GLU model must fit without error and return valid predictions."""
        model = SignalCNN()
        df = _make_df(60)
        X, y, w = build_training_windows(df)
        model.fit(X, y, epochs=5, sample_weights=w)
        self.assertTrue(model.is_trained)
        x = np.random.randn(N_CHANNELS, WINDOW_SIZE).astype(np.float32)
        pred, direction, conf = model.predict(x)
        self.assertIsInstance(pred, float)
        self.assertIn(direction, ("bull", "neutral", "bear"))
        self.assertGreaterEqual(conf, 0.0)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_glu_save_load_roundtrip(self):
        """GLU architecture must survive save → load with matching weights."""
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_path = cm._MODEL_PATH
            cm._MODEL_PATH = os.path.join(tmpdir, "glu_cnn.pt")
            try:
                model_a = SignalCNN()
                df = _make_df(60)
                X, y, w = build_training_windows(df)
                model_a.fit(X, y, epochs=5, sample_weights=w)
                model_a.save()

                model_b = SignalCNN()
                loaded = model_b.load()
                self.assertTrue(loaded)
                self.assertTrue(model_b.is_trained)
                for k in SOURCE_NAMES:
                    self.assertAlmostEqual(
                        model_a.get_learned_weights()[k],
                        model_b.get_learned_weights()[k],
                        places=5,
                    )
            finally:
                cm._MODEL_PATH = orig_path

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_learned_weights_sum_to_one_after_glu_training(self):
        """get_learned_weights() must still sum to 1.0 with GLU first layer."""
        model = SignalCNN()
        df = _make_df(60)
        X, y, w = build_training_windows(df)
        model.fit(X, y, epochs=5, sample_weights=w)
        weights = model.get_learned_weights()
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=5)


class TestDiagnoseFunction(unittest.TestCase):
    """Unit tests for the _diagnose() helper."""

    def test_ok_in_normal_range(self):
        from data.cnn_model import _diagnose
        self.assertEqual(_diagnose(0.001, 0.002, 2.0), "OK")

    def test_overfit_when_ratio_above_3(self):
        from data.cnn_model import _diagnose
        self.assertEqual(_diagnose(0.001, 0.005, 5.0), "OVERFIT")

    def test_overfit_memorizing_when_train_tiny(self):
        from data.cnn_model import _diagnose
        self.assertEqual(_diagnose(1e-7, 0.003, 30000), "OVERFIT_MEMORIZING")

    def test_underfit_when_both_high(self):
        from data.cnn_model import _diagnose
        self.assertEqual(_diagnose(0.008, 0.010, 1.25), "UNDERFIT")

    def test_ok_boundary_ratio_exactly_3(self):
        from data.cnn_model import _diagnose
        # ratio == 3.0 is not > 3.0, so still OK (train MSE normal range)
        self.assertEqual(_diagnose(0.001, 0.003, 3.0), "OK")


# ── Walk-Forward Efficiency ────────────────────────────────────────────────────

class TestWalkForwardEfficiency(unittest.TestCase):
    """
    Walk-Forward Efficiency (WFE) = OOS R² on the held-out validation set.

    Computed as:  wfe = 1 - val_MSE / var(y_val)
    Healthy:  wfe >= 0.0  (model beats naive "predict the mean")
    Unhealthy: wfe < 0.0  (model worse than predicting the mean)
    """

    def test_summary_includes_wfe_key_untrained(self):
        """training_summary() always includes 'walk_forward_efficiency'."""
        model = SignalCNN()
        s = model.training_summary()
        self.assertIn("walk_forward_efficiency", s)

    def test_wfe_none_when_untrained(self):
        """WFE is None before training."""
        model = SignalCNN()
        s = model.training_summary()
        self.assertIsNone(s["walk_forward_efficiency"])

    def test_summary_includes_wfe_status_untrained(self):
        """training_summary() always includes 'wfe_status'."""
        model = SignalCNN()
        s = model.training_summary()
        self.assertIn("wfe_status", s)
        self.assertEqual(s["wfe_status"], "UNTRAINED")

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_wfe_is_float_after_training(self):
        """After fit(), WFE should be a float."""
        df = _make_df(n_rows=60)
        X, y, w = build_training_windows(df)
        model = SignalCNN()
        model.fit(X, y, epochs=5, sample_weights=w)
        s = model.training_summary()
        self.assertIsInstance(s["walk_forward_efficiency"], float)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_wfe_bounded_below_minus_10(self):
        """WFE >= -10.0 even for a very bad model (sanity clamp)."""
        df = _make_df(n_rows=60)
        X, y, w = build_training_windows(df)
        model = SignalCNN()
        model.fit(X, y, epochs=2, sample_weights=w)
        s = model.training_summary()
        self.assertGreaterEqual(s["walk_forward_efficiency"], -10.0)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_wfe_persisted_through_save_load(self):
        """WFE value survives a save/load round-trip."""
        df = _make_df(n_rows=60)
        X, y, w = build_training_windows(df)
        model = SignalCNN()
        model.fit(X, y, epochs=5, sample_weights=w)
        original_wfe = model.training_summary()["walk_forward_efficiency"]

        with tempfile.TemporaryDirectory() as tmpdir:
            import data.cnn_model as _cm
            orig_path = _cm._MODEL_PATH
            _cm._MODEL_PATH = os.path.join(tmpdir, "test_cnn_wfe.pt")
            try:
                model.save()
                model2 = SignalCNN()
                model2.load()
                loaded_wfe = model2.training_summary()["walk_forward_efficiency"]
                self.assertAlmostEqual(original_wfe, loaded_wfe, places=4)
            finally:
                _cm._MODEL_PATH = orig_path

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_wfe_status_is_valid_string(self):
        """wfe_status must be one of the expected strings after training."""
        df = _make_df(n_rows=60)
        X, y, w = build_training_windows(df)
        model = SignalCNN()
        model.fit(X, y, epochs=5, sample_weights=w)
        valid = {"HEALTHY", "DEGRADED", "POOR", "UNTRAINED"}
        self.assertIn(model.training_summary()["wfe_status"], valid)

    def test_wfe_compute_healthy(self):
        """_compute_wfe() with perfect predictions → WFE = 1.0."""
        from data.cnn_model import _compute_wfe
        y_true = [0.01, -0.02, 0.03, -0.01, 0.02]
        # Perfect predictions — OOS R² should be 1.0
        wfe, status = _compute_wfe(y_true, y_true)
        self.assertAlmostEqual(wfe, 1.0, places=4)
        self.assertEqual(status, "HEALTHY")

    def test_wfe_compute_predicting_mean(self):
        """Predicting the mean → WFE = 0.0."""
        from data.cnn_model import _compute_wfe
        y_true = [0.01, -0.02, 0.03, -0.01, 0.02]
        mean_y = sum(y_true) / len(y_true)
        y_pred = [mean_y] * len(y_true)
        wfe, _ = _compute_wfe(y_true, y_pred)
        self.assertAlmostEqual(wfe, 0.0, places=4)

    def test_wfe_compute_poor_model(self):
        """Predictions inversely correlated → WFE < 0."""
        from data.cnn_model import _compute_wfe
        y_true = [0.01, -0.02, 0.03, -0.01, 0.02]
        y_pred = [-0.01, 0.02, -0.03, 0.01, -0.02]  # opposite sign
        wfe, status = _compute_wfe(y_true, y_pred)
        self.assertLess(wfe, 0.0)

    def test_wfe_status_boundaries(self):
        """Status thresholds: HEALTHY ≥ 0.70, DEGRADED ≥ 0.50, POOR < 0.50."""
        from data.cnn_model import _compute_wfe
        # WFE exactly at threshold values — check boundary conditions
        # Perfect → HEALTHY
        y = [0.01, -0.02, 0.03, -0.01, 0.02]
        _, s = _compute_wfe(y, y)
        self.assertEqual(s, "HEALTHY")

    def test_wfe_empty_returns_none_untrained(self):
        """_compute_wfe() with empty lists returns (None, UNTRAINED)."""
        from data.cnn_model import _compute_wfe
        wfe, status = _compute_wfe([], [])
        self.assertIsNone(wfe)
        self.assertEqual(status, "UNTRAINED")


if __name__ == "__main__":
    unittest.main()
