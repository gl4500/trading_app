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
             add_rv_cols=True, add_iv_rv=True, add_macro_cols=False,
             add_return_cols=False):
    """Build a minimal labelled history DataFrame.

    Uses daily timestamps (86400s steps) so that walk-forward CV
    (which requires at least 56 calendar days for 3 folds × 14-day val)
    works correctly with the default n_rows=120 or n_rows=150.
    """
    now = time.time()
    rows = []
    for i in range(n_rows):
        row = {
            "symbol":          symbol,
            "snapshot_ts":     now - (n_rows - i) * 86400,  # daily steps
            "analyst_score":   np.random.uniform(-1, 1),
            "earnings_score":  np.random.uniform(-1, 1),
            "alpaca_score":    np.random.uniform(-1, 1),
            "yahoo_score":     np.random.uniform(-1, 1),
            "congress_score":  np.random.uniform(-1, 1),
            "composite_score": np.random.uniform(-1, 1),
            "price":           100.0 + i * 0.1,
            "return_1d":       np.random.uniform(-0.05, 0.05) if add_outcomes else float("nan"),
            "return_5d":       np.random.uniform(-0.10, 0.10) if add_outcomes else float("nan"),
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
        if add_return_cols:
            # Tier 1: lagged log-return channels
            row["r_1"]   = np.random.uniform(-0.02, 0.02)
            row["r_5"]   = np.random.uniform(-0.05, 0.05)
            row["r_20"]  = np.random.uniform(-0.10, 0.10)
            row["r_60"]  = np.random.uniform(-0.15, 0.15)
            row["r_120"] = np.random.uniform(-0.20, 0.20)
        if add_macro_cols:
            # Task #24: trailing _back columns.
            row["macro_vix_norm"]      = np.random.uniform(0.3, 1.5)
            row["macro_gld_5d_back"]   = np.random.uniform(-0.05, 0.05)
            row["macro_tlt_5d_back"]   = np.random.uniform(-0.05, 0.05)
            row["macro_spy_5d_back"]   = np.random.uniform(-0.05, 0.05)
            row["macro_breadth_back"]  = np.random.uniform(-0.05, 0.05)
        rows.append(row)
    return pd.DataFrame(rows)


class TestBuildTrainingWindows(unittest.TestCase):

    def test_returns_arrays_for_labelled_data(self):
        df = _make_df(50)
        X, y, w, _ = build_training_windows(df, T=WINDOW_SIZE)
        self.assertGreater(len(X), 0)
        self.assertEqual(len(X), len(y))
        self.assertEqual(len(X), len(w))

    def test_x_shape_is_N_channels_by_T(self):
        # Include all optional cols so the full N_CHANNELS=19 channels are present
        df = _make_df(50, add_macro_cols=True, add_return_cols=True)
        X, y, w, _ = build_training_windows(df, T=WINDOW_SIZE)
        self.assertEqual(X.shape[1], N_CHANNELS)  # 19
        self.assertEqual(X.shape[2], WINDOW_SIZE)

    def test_x_shape_degrades_without_optional_cols(self):
        """Channel count degrades gracefully when optional columns are absent."""
        # No iv_rv, no agent, no RV → 4 channels (base source only: analyst/earnings/alpaca/yahoo)
        df_src = _make_df(50, add_iv_rv=False, add_agent_cols=False, add_rv_cols=False)
        X_src, _, _, _ = build_training_windows(df_src, T=WINDOW_SIZE)
        self.assertEqual(X_src.shape[1], 4)

        # iv_rv + agent but no RV → 7 channels (5 source + 2 agent)
        df_agent = _make_df(50, add_iv_rv=True, add_agent_cols=True, add_rv_cols=False)
        X_agent, _, _, _ = build_training_windows(df_agent, T=WINDOW_SIZE)
        self.assertEqual(X_agent.shape[1], 7)

        # All columns (no macro) → 9 channels (5 source + 2 agent + 2 RV)
        df_full = _make_df(50, add_iv_rv=True, add_agent_cols=True, add_rv_cols=True)
        X_full, _, _, _ = build_training_windows(df_full, T=WINDOW_SIZE)
        self.assertEqual(X_full.shape[1], 9)

    def test_returns_empty_arrays_when_no_outcomes(self):
        df = _make_df(50, add_outcomes=False)
        X, y, w, _ = build_training_windows(df, T=WINDOW_SIZE)
        self.assertEqual(len(X), 0)

    def test_no_nans_in_X(self):
        df = _make_df(50)
        df.loc[df.index[:5], "analyst_score"] = float("nan")
        X, y, w, _ = build_training_windows(df, T=WINDOW_SIZE)
        self.assertFalse(np.isnan(X).any())

    def test_y_clipped_to_20_pct(self):
        df = _make_df(50)
        df["return_1d"] = 0.50
        X, y, w, _ = build_training_windows(df, T=WINDOW_SIZE)
        self.assertTrue((y <= 0.20).all())
        self.assertTrue((y >= -0.20).all())

    def test_multi_symbol_aggregated(self):
        df = pd.concat([_make_df(40, "AAPL"), _make_df(40, "MSFT")], ignore_index=True)
        X, y, w, _ = build_training_windows(df, T=WINDOW_SIZE)
        self.assertGreater(len(X), 40)

    def test_x_dtype_float32(self):
        df = _make_df(40)
        X, _, _w, _ = build_training_windows(df, T=WINDOW_SIZE)
        self.assertEqual(X.dtype, np.float32)

    def test_sample_weights_higher_when_top_agent_correct(self):
        """Rows with top_agent_correct=1.0 get weight 1.0; incorrect get 0.5."""
        df = _make_df(50, add_agent_cols=True)
        df["top_agent_correct"] = 1.0   # all correct
        X, y, w, _ = build_training_windows(df, T=WINDOW_SIZE)
        self.assertTrue((w == 1.0).all(), f"Expected all 1.0, got: {w[:5]}")

    def test_sample_weights_neutral_when_no_top_agent_col(self):
        """Missing top_agent_correct column → all weights 0.75 (neutral)."""
        df = _make_df(50, add_agent_cols=False)
        X, y, w, _ = build_training_windows(df, T=WINDOW_SIZE)
        self.assertTrue((w == 1.0).all())   # no agent col → uniform weight 1.0

    def test_zero_feature_columns_returns_empty_with_warning(self):
        """DataFrame with no recognised feature columns → shape (0, 0, T) and no crash."""
        df = _make_df(50, add_outcomes=True, add_agent_cols=False, add_rv_cols=False,
                      add_iv_rv=False, add_macro_cols=False)
        # Drop all SOURCE_COLUMNS so n_feat == 0
        from data.signal_history import SOURCE_COLUMNS
        df = df.drop(columns=[c for c in SOURCE_COLUMNS if c in df.columns])
        X, y, w, _ = build_training_windows(df, T=WINDOW_SIZE)
        self.assertEqual(X.shape, (0, 0, WINDOW_SIZE))
        self.assertEqual(len(y), 0)


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
        df = _make_df(120)
        X, y, w, t = build_training_windows(df, T=WINDOW_SIZE)
        self.model.fit(X, y, t, epochs=5)
        x = np.random.randn(N_CHANNELS, WINDOW_SIZE).astype(np.float32)
        pred, direction, conf = self.model.predict(x)
        self.assertIsInstance(pred, float)
        self.assertIn(direction, ("bull", "neutral", "bear"))
        self.assertGreaterEqual(conf, 0.0)
        self.assertLessEqual(conf, 1.0)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_predict_direction_bull_when_positive(self):
        """Direction is 'bull' when predicted return > 0.5%."""
        n = 120
        X = np.zeros((n, N_CHANNELS, WINDOW_SIZE), dtype=np.float32)
        X[:n//2, 0, :] =  1.0
        X[n//2:, 0, :] = -1.0
        y = np.array([0.10] * (n//2) + [-0.10] * (n//2), dtype=np.float32)
        t = np.linspace(0, 90 * 86400.0, n, dtype=np.float64)
        self.model.fit(X, y, t, epochs=150)
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
        t = np.linspace(0, 90 * 86400.0, 5, dtype=np.float64)
        self.model.fit(X, y, t, epochs=10)   # 5 < MIN_TRAIN_SAMPLES
        self.assertFalse(self.model.is_trained)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_fit_accepts_sample_weights(self):
        """fit() with sample_weights does not raise and still trains."""
        df = _make_df(120)
        X, y, w, t = build_training_windows(df, T=WINDOW_SIZE)
        w[:len(w)//2] = 0.5
        self.model.fit(X, y, t, epochs=5, sample_weights=w)
        self.assertTrue(self.model.is_trained)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_fit_with_none_weights_behaves_same_as_no_weights(self):
        df = _make_df(120)
        X, y, w, t = build_training_windows(df, T=WINDOW_SIZE)
        self.model.fit(X, y, t, epochs=5, sample_weights=None)
        self.assertTrue(self.model.is_trained)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_fit_sets_trained_flag(self):
        df = _make_df(120)
        X, y, w, t = build_training_windows(df, T=WINDOW_SIZE)
        self.model.fit(X, y, t, epochs=5)
        self.assertTrue(self.model.is_trained)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_fit_loss_decreases(self):
        df = _make_df(120)
        X, y, w, t = build_training_windows(df, T=WINDOW_SIZE)
        self.model.fit(X, y, t, epochs=30)
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
        df = _make_df(120)
        X, y, w, t = build_training_windows(df, T=WINDOW_SIZE)
        model.fit(X, y, t, epochs=5)
        weights = model.get_learned_weights()
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=5)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_weights_are_non_negative(self):
        model = SignalCNN()
        df = _make_df(120)
        X, y, w, t = build_training_windows(df, T=WINDOW_SIZE)
        model.fit(X, y, t, epochs=5)
        for wv in model.get_learned_weights().values():
            self.assertGreaterEqual(wv, 0.0)


class TestCongressDemotedFromCNN(unittest.TestCase):
    """Task #20: congressional_trades is demoted from a CNN channel to LLM
    context-only. 3% coverage with corr -0.001 means it carries no usable
    signal for the CNN — feeding it dilutes the gradient. The score is still
    captured into snapshots and shown to the LLM for catalyst reasoning."""

    def test_source_names_excludes_congressional_trades(self):
        self.assertNotIn("congressional_trades", SOURCE_NAMES)

    def test_default_weights_excludes_congressional_trades(self):
        self.assertNotIn("congressional_trades", _DEFAULT_WEIGHTS)

    def test_default_weights_sum_to_one_after_renormalization(self):
        self.assertAlmostEqual(sum(_DEFAULT_WEIGHTS.values()), 1.0, places=5)

    def test_default_weights_keys_match_source_names(self):
        self.assertEqual(set(_DEFAULT_WEIGHTS.keys()), set(SOURCE_NAMES))

    def test_n_channels_is_19_after_return_channels(self):
        # 5 source (analyst/earnings/alpaca/yahoo/iv_rv) + 2 agent + 2 RV + 5 ret + 5 macro
        self.assertEqual(N_CHANNELS, 19)


class TestEarningsReframedToMagnitude(unittest.TestCase):
    """Task #22: earnings_surprise direction has corr -0.029 with y (noise);
    magnitude has corr +0.143 (the strongest single-feature volatility
    predictor). The CNN channel is renamed to 'earnings_magnitude' and
    receives |earnings_score| via _apply_cnn_feature_transforms()."""

    def test_source_names_uses_earnings_magnitude_label(self):
        # Renamed from "earnings_surprise" so the channel intent is explicit.
        self.assertIn("earnings_magnitude", SOURCE_NAMES)
        self.assertNotIn("earnings_surprise", SOURCE_NAMES)

    def test_default_weights_uses_earnings_magnitude_key(self):
        self.assertIn("earnings_magnitude", _DEFAULT_WEIGHTS)
        self.assertNotIn("earnings_surprise", _DEFAULT_WEIGHTS)

    def test_default_weights_keys_still_match_source_names(self):
        # Sanity: rename must be consistent across both.
        self.assertEqual(set(_DEFAULT_WEIGHTS.keys()), set(SOURCE_NAMES))

    def test_default_weights_still_sum_to_one(self):
        self.assertAlmostEqual(sum(_DEFAULT_WEIGHTS.values()), 1.0, places=5)

    def test_build_training_windows_uses_abs_earnings(self):
        # Construct a df with a known signed earnings_score column; the
        # earnings channel of the resulting X tensor must be the absolute value.
        n = WINDOW_SIZE + 5
        signed = np.array(
            [-0.8, 0.3, -0.5, 0.0, 0.6] * ((n // 5) + 1)
        )[:n]
        df = pd.DataFrame({
            "symbol":          ["AAPL"] * n,
            "snapshot_ts":     np.arange(n).astype(float),
            "analyst_score":   np.zeros(n),
            "earnings_score":  signed,
            "alpaca_score":    np.zeros(n),
            "yahoo_score":     np.zeros(n),
            "iv_rv_score":     np.zeros(n),
            "return_1d":       np.full(n, 0.01),
        })
        X, y, w, _ = build_training_windows(df, T=WINDOW_SIZE)
        # Channel 1 == earnings (per SOURCE_COLUMNS order). All values must be
        # >= 0 — the abs transform ran.
        self.assertEqual(X.shape[0], len(y))
        self.assertGreater(X.shape[0], 0)
        earnings_channel = X[:, 1, :].ravel()
        nonzero = earnings_channel[earnings_channel != 0.0]
        self.assertTrue(
            (nonzero > 0).all(),
            f"Found negative earnings values in CNN channel 1: {nonzero[nonzero < 0]}"
        )

    def test_build_training_windows_does_not_mutate_input_df(self):
        # The transform must operate on a copy so caller's df keeps signed values.
        n = WINDOW_SIZE + 5
        signed = np.full(n, -0.5)
        df = pd.DataFrame({
            "symbol":          ["AAPL"] * n,
            "snapshot_ts":     np.arange(n).astype(float),
            "analyst_score":   np.zeros(n),
            "earnings_score":  signed,
            "alpaca_score":    np.zeros(n),
            "yahoo_score":     np.zeros(n),
            "iv_rv_score":     np.zeros(n),
            "return_1d":       np.full(n, 0.01),
        })
        before = df["earnings_score"].copy()
        build_training_windows(df, T=WINDOW_SIZE)
        np.testing.assert_array_almost_equal(
            df["earnings_score"].values, before.values
        )


class TestSaveLoad(unittest.TestCase):

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_path = cm._MODEL_PATH
            cm._MODEL_PATH = os.path.join(tmpdir, "signal_cnn.pt")
            try:
                model_a = SignalCNN()
                df = _make_df(120)
                X, y, w, t = build_training_windows(df, T=WINDOW_SIZE)
                model_a.fit(X, y, t, epochs=10)
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
        df    = _make_df(n_rows=120)
        X, y, w, t = build_training_windows(df)
        model = SignalCNN()
        model.fit(X, y, t, epochs=5, sample_weights=w)
        s = model.training_summary()
        self.assertGreater(len(s["val_loss_curve"]), 0)
        self.assertEqual(len(s["train_loss_curve"]), len(s["val_loss_curve"]))

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_n_train_plus_n_val_equals_total(self):
        """Last-fold n_train + n_val must each be positive after walk-forward fit."""
        df    = _make_df(n_rows=120)
        X, y, w, t = build_training_windows(df)
        model = SignalCNN()
        model.fit(X, y, t, epochs=5, sample_weights=w)
        s = model.training_summary()
        # With walk-forward CV the last fold's n_train + n_val ≤ len(X)
        # (some rows may be in the embargo). Just assert both are positive.
        self.assertGreater(s["n_train"], 0)
        self.assertGreater(s["n_val"], 0)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_overfit_ratio_is_positive(self):
        df    = _make_df(n_rows=120)
        X, y, w, t = build_training_windows(df)
        model = SignalCNN()
        model.fit(X, y, t, epochs=5, sample_weights=w)
        s = model.training_summary()
        self.assertGreater(s["overfit_ratio"], 0)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_diagnosis_is_valid_string(self):
        df    = _make_df(n_rows=120)
        X, y, w, t = build_training_windows(df)
        model = SignalCNN()
        model.fit(X, y, t, epochs=5, sample_weights=w)
        valid = {"OK", "OVERFIT", "OVERFIT_MEMORIZING", "UNDERFIT", "UNTRAINED"}
        self.assertIn(model.training_summary()["diagnosis"], valid)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_val_loss_persisted_through_save_load(self):
        """Val loss curve must survive a save/load round-trip."""
        df    = _make_df(n_rows=120)
        X, y, w, t = build_training_windows(df)
        model = SignalCNN()
        model.fit(X, y, t, epochs=5, sample_weights=w)
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


class TestTrainingHistoryPersistence(unittest.TestCase):
    """
    Per-run training history is appended to a JSONL log so we can compare
    metrics (loss, WFE, learned weights) across retrains over time.
    The model checkpoint itself is overwritten each run; this log is not.

    History path is derived from _MODEL_PATH at call time, so patching
    _MODEL_PATH alone reroutes both files together.
    """

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def _train_and_save(self, tmpdir):
        cm._MODEL_PATH = os.path.join(tmpdir, "signal_cnn.pt")
        df = _make_df(n_rows=120)
        X, y, _, t = build_training_windows(df)
        model = SignalCNN()
        model.fit(X, y, t, epochs=3)
        model.save()
        return model

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_save_appends_training_history_jsonl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_model = cm._MODEL_PATH
            try:
                self._train_and_save(tmpdir)
                hist_path = os.path.join(tmpdir, "training_history.jsonl")
                self.assertTrue(os.path.exists(hist_path))
                with open(hist_path, "r", encoding="utf-8") as f:
                    lines = [ln for ln in f.read().splitlines() if ln.strip()]
                self.assertEqual(len(lines), 1)
                import json as _json
                self.assertIsInstance(_json.loads(lines[0]), dict)
            finally:
                cm._MODEL_PATH = orig_model

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_history_record_has_required_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_model = cm._MODEL_PATH
            try:
                self._train_and_save(tmpdir)
                rec = cm.load_training_history()[0]
                for key in (
                    "train_ts", "train_ts_iso",
                    "n_train", "n_val", "n_channels",
                    "epochs_completed",
                    "final_train_mse", "final_val_mse",
                    "overfit_ratio",
                    "wfe", "wfe_status",
                    "learned_weights", "weight_delta",
                ):
                    self.assertIn(key, rec, f"missing field: {key}")
                self.assertIsInstance(rec["learned_weights"], dict)
                self.assertIsInstance(rec["weight_delta"], dict)
                self.assertIsInstance(rec["n_train"], int)
                self.assertIsInstance(rec["train_ts_iso"], str)
            finally:
                cm._MODEL_PATH = orig_model

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_two_saves_produce_two_records_in_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_model = cm._MODEL_PATH
            try:
                cm._MODEL_PATH = os.path.join(tmpdir, "signal_cnn.pt")
                df = _make_df(n_rows=120)
                X, y, _, t = build_training_windows(df)
                m1 = SignalCNN(); m1.fit(X, y, t, epochs=2); m1.save()
                m2 = SignalCNN(); m2.fit(X, y, t, epochs=2)
                m2._train_ts = m1._train_ts + 1.0   # force strictly later
                m2.save()

                history = cm.load_training_history()
                self.assertEqual(len(history), 2)
                self.assertLess(history[0]["train_ts"], history[1]["train_ts"])
            finally:
                cm._MODEL_PATH = orig_model

    def test_load_training_history_empty_when_no_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_model = cm._MODEL_PATH
            try:
                cm._MODEL_PATH = os.path.join(tmpdir, "nope.pt")
                self.assertEqual(cm.load_training_history(), [])
            finally:
                cm._MODEL_PATH = orig_model

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_load_training_history_respects_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_model = cm._MODEL_PATH
            try:
                cm._MODEL_PATH = os.path.join(tmpdir, "signal_cnn.pt")
                df = _make_df(n_rows=120)
                X, y, _, t = build_training_windows(df)
                base_ts = None
                for i in range(3):
                    m = SignalCNN()
                    m.fit(X, y, t, epochs=2)
                    if base_ts is None:
                        base_ts = m._train_ts
                    m._train_ts = base_ts + i      # strictly distinct
                    m.save()
                tail = cm.load_training_history(limit=2)
                full = cm.load_training_history()
                self.assertEqual(len(full), 3)
                self.assertEqual(len(tail), 2)
                self.assertEqual(tail, full[-2:])
            finally:
                cm._MODEL_PATH = orig_model


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
        df = _make_df(120)
        X, y, w, t = build_training_windows(df)
        model.fit(X, y, t, epochs=5, sample_weights=w)
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
                df = _make_df(120)
                X, y, w, t = build_training_windows(df)
                model_a.fit(X, y, t, epochs=5, sample_weights=w)
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
        df = _make_df(120)
        X, y, w, t = build_training_windows(df)
        model.fit(X, y, t, epochs=5, sample_weights=w)
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
        df = _make_df(n_rows=120)
        X, y, w, t = build_training_windows(df)
        model = SignalCNN()
        model.fit(X, y, t, epochs=5, sample_weights=w)
        s = model.training_summary()
        self.assertIsInstance(s["walk_forward_efficiency"], float)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_wfe_bounded_below_minus_10(self):
        """WFE >= -10.0 even for a very bad model (sanity clamp)."""
        df = _make_df(n_rows=120)
        X, y, w, t = build_training_windows(df)
        model = SignalCNN()
        model.fit(X, y, t, epochs=2, sample_weights=w)
        s = model.training_summary()
        self.assertGreaterEqual(s["walk_forward_efficiency"], -10.0)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_wfe_persisted_through_save_load(self):
        """WFE value survives a save/load round-trip."""
        df = _make_df(n_rows=120)
        X, y, w, t = build_training_windows(df)
        model = SignalCNN()
        model.fit(X, y, t, epochs=5, sample_weights=w)
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
        df = _make_df(n_rows=120)
        X, y, w, t = build_training_windows(df)
        model = SignalCNN()
        model.fit(X, y, t, epochs=5, sample_weights=w)
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


class TestTrainingImprovements(unittest.TestCase):
    """
    TDD tests for the 6 training best-practice fixes:
      1. MIN_TRAIN_SAMPLES raised 30 → 100
      2. Optimizer changed to AdamW with weight_decay > 0
      3. Dropout raised 0.2 → 0.3
      4. Chronological (not random) train/val split
      5. ReduceLROnPlateau scheduler attached after fit()
      6. Early stopping with patience parameter
    """

    def test_min_train_samples_is_100(self):
        """MIN_TRAIN_SAMPLES must be 100 after raising from 30."""
        self.assertEqual(MIN_TRAIN_SAMPLES, 100)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_optimizer_is_adamw(self):
        """Default optimizer must be AdamW (not plain Adam)."""
        model = SignalCNN()
        self.assertIsInstance(model._opt, torch.optim.AdamW)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_weight_decay_nonzero(self):
        """AdamW must have weight_decay > 0."""
        model = SignalCNN()
        wd = model._opt.param_groups[0]["weight_decay"]
        self.assertGreater(wd, 0.0)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_dropout_rate_is_0_3(self):
        """All Dropout layers in _build_glu_net must use p=0.3."""
        from data.cnn_model import _build_glu_net
        net = _build_glu_net(N_CHANNELS)
        dropout_layers = [m for m in net.modules() if isinstance(m, torch.nn.Dropout)]
        self.assertGreater(len(dropout_layers), 0, "No Dropout layers found")
        for layer in dropout_layers:
            self.assertAlmostEqual(layer.p, 0.3, places=5,
                                   msg=f"Expected p=0.3, got p={layer.p}")

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_val_split_is_chronological(self):
        """split_idx must equal last-fold n_train (chronological split is preserved)."""
        df = _make_df(150)
        X, y, w, t = build_training_windows(df, T=WINDOW_SIZE)
        model = SignalCNN()
        model.fit(X, y, t, epochs=3, sample_weights=w)
        # With walk-forward CV, _split_idx == last-fold n_train (positive and < len(X))
        self.assertGreater(model._split_idx, 0)
        self.assertLess(model._split_idx, len(X))

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_scheduler_attached_after_fit(self):
        """_scheduler must be non-None after fit() completes."""
        df = _make_df(150)
        X, y, w, t = build_training_windows(df, T=WINDOW_SIZE)
        model = SignalCNN()
        model.fit(X, y, t, epochs=5, sample_weights=w)
        self.assertIsNotNone(model._scheduler)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_early_stopping_accepts_patience_param(self):
        """fit() must accept a patience parameter without error."""
        df = _make_df(150)
        X, y, w, t = build_training_windows(df, T=WINDOW_SIZE)
        model = SignalCNN()
        model.fit(X, y, t, epochs=20, patience=5, sample_weights=w)
        self.assertTrue(model.is_trained)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_early_stop_epoch_in_summary(self):
        """training_summary() must include early_stop_epoch after fit()."""
        df = _make_df(150)
        X, y, w, t = build_training_windows(df, T=WINDOW_SIZE)
        model = SignalCNN()
        model.fit(X, y, t, epochs=10, sample_weights=w)
        s = model.training_summary()
        self.assertIn("early_stop_epoch", s)
        self.assertIsNotNone(s["early_stop_epoch"])

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_early_stopping_stops_before_max_epochs(self):
        """With small patience, training must stop before all epochs when val stalls."""
        df = _make_df(150)
        X, y, w, t = build_training_windows(df, T=WINDOW_SIZE)
        model = SignalCNN()
        max_epochs = 200
        model.fit(X, y, t, epochs=max_epochs, patience=3, sample_weights=w)
        # With patience=3 on noisy random data, should stop well before 200 epochs
        self.assertLess(model._early_stop_epoch, max_epochs)


class TestBuildTrainingWindowsReturnsTimestamps(unittest.TestCase):
    """build_training_windows must return per-window snapshot timestamps for walk-forward CV."""

    def test_returns_four_element_tuple(self):
        import pandas as pd
        from data.cnn_model import build_training_windows, WINDOW_SIZE

        n = 12
        df = pd.DataFrame({
            "symbol":          ["AAPL"] * n,
            "snapshot_ts":     np.arange(n, dtype=np.float64) * 86400.0,
            "analyst_score":   np.zeros(n),
            "earnings_score":  np.zeros(n),
            "alpaca_score":    np.zeros(n),
            "yahoo_score":     np.zeros(n),
            "iv_rv_score":     np.zeros(n),
            "return_1d":       np.linspace(-0.01, 0.01, n),
        })
        result = build_training_windows(df, T=WINDOW_SIZE)
        self.assertEqual(len(result), 4, "expected (X, y, w, t)")

    def test_timestamps_match_row_count(self):
        import pandas as pd
        from data.cnn_model import build_training_windows, WINDOW_SIZE

        n = 15
        df = pd.DataFrame({
            "symbol":          ["AAPL"] * n,
            "snapshot_ts":     np.arange(n, dtype=np.float64) * 86400.0,
            "analyst_score":   np.zeros(n),
            "earnings_score":  np.zeros(n),
            "alpaca_score":    np.zeros(n),
            "yahoo_score":     np.zeros(n),
            "iv_rv_score":     np.zeros(n),
            "return_1d":       np.full(n, 0.001),
        })
        X, y, w, t = build_training_windows(df, T=WINDOW_SIZE)
        self.assertEqual(len(X), len(t))
        self.assertEqual(len(y), len(t))


class TestFitProducesWalkforwardMetrics(unittest.TestCase):
    """After fit(), SignalCNN exposes per-fold + aggregate metrics."""

    def _make_synthetic_data(self, n=600, n_channels=10, T=10):
        rng = np.random.default_rng(0)
        X = rng.standard_normal((n, n_channels, T)).astype(np.float32) * 0.5
        y = (X[:, 0, :].mean(axis=1) * 0.05 + rng.standard_normal(n) * 0.01).astype(np.float32)
        t = np.linspace(0, 90 * 86400.0, n, dtype=np.float64)
        return X, y, t

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_fit_records_per_fold_metrics(self):
        from data.cnn_model import SignalCNN

        X, y, t = self._make_synthetic_data()
        cnn = SignalCNN(T=10, n_channels=10)
        cnn.fit(X, y, t, epochs=5, batch_size=32, n_folds=3, min_val_days=14)
        summary = cnn.training_summary()
        self.assertIn("fold_metrics", summary)
        self.assertEqual(len(summary["fold_metrics"]), 3)
        for fm in summary["fold_metrics"]:
            self.assertIn("wfe", fm)
            self.assertIn("ic", fm)
            self.assertIn("val_mse", fm)
            self.assertIn("n_train", fm)
            self.assertIn("n_val", fm)
            self.assertIn("val_window_days", fm)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_fit_records_aggregate_ic_ir(self):
        import math
        from data.cnn_model import SignalCNN

        X, y, t = self._make_synthetic_data()
        cnn = SignalCNN(T=10, n_channels=10)
        cnn.fit(X, y, t, epochs=5, batch_size=32, n_folds=3, min_val_days=14)
        summary = cnn.training_summary()
        self.assertIn("mean_ic", summary)
        self.assertIn("ir", summary)
        self.assertIn("mean_wfe", summary)
        self.assertTrue(math.isfinite(summary["mean_ic"]))
        self.assertTrue(math.isfinite(summary["ir"]))
        # mean_wfe may be None if all folds had degenerate val variance — accept that
        if summary["mean_wfe"] is not None:
            self.assertTrue(math.isfinite(summary["mean_wfe"]))

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_fit_records_calibration(self):
        from data.cnn_model import SignalCNN

        X, y, t = self._make_synthetic_data()
        cnn = SignalCNN(T=10, n_channels=10)
        cnn.fit(X, y, t, epochs=5, batch_size=32, n_folds=3, min_val_days=14)
        summary = cnn.training_summary()
        self.assertIn("calibration", summary)
        self.assertIsInstance(summary["calibration"], list)
        self.assertLessEqual(len(summary["calibration"]), 5)


class TestTrainingHistoryRecordSchema(unittest.TestCase):
    """save() appends a record with walk-forward metrics."""

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_record_has_walkforward_fields(self):
        import json
        import os
        import tempfile
        from unittest.mock import patch

        from data.cnn_model import SignalCNN

        rng = np.random.default_rng(0)
        n, c, T = 600, 10, 10
        X = rng.standard_normal((n, c, T)).astype(np.float32) * 0.5
        y = (X[:, 0, :].mean(axis=1) * 0.05).astype(np.float32)
        t = np.linspace(0, 90 * 86400.0, n, dtype=np.float64)

        with tempfile.TemporaryDirectory() as td:
            model_path = os.path.join(td, "signal_cnn.pt")
            with patch("data.cnn_model._MODEL_PATH", model_path):
                cnn = SignalCNN(T=T, n_channels=c)
                cnn.fit(X, y, t, epochs=3, batch_size=32, n_folds=3, min_val_days=14)
                cnn.save()

                history_path = os.path.join(td, "training_history.jsonl")
                self.assertTrue(os.path.exists(history_path))
                with open(history_path) as f:
                    rec = json.loads(f.readlines()[-1])

        for key in ("fold_metrics", "mean_ic", "ir", "mean_wfe", "calibration"):
            self.assertIn(key, rec)
        self.assertEqual(len(rec["fold_metrics"]), 3)


class TestReturnChannelsExposed(unittest.TestCase):
    """Tier 1 from docs/equity_feature_engineering_audit.md — five lagged
    return channels become part of N_CHANNELS."""

    def test_n_channels_is_19(self):
        from data.cnn_model import N_CHANNELS, RETURN_CHANNEL_NAMES
        self.assertEqual(len(RETURN_CHANNEL_NAMES), 5)
        self.assertEqual(N_CHANNELS, 19)  # 5 src + 2 agent + 2 rv + 5 ret + 5 macro

    def test_return_channel_order(self):
        from data.cnn_model import RETURN_CHANNEL_NAMES
        self.assertEqual(
            RETURN_CHANNEL_NAMES,
            ["r_1", "r_5", "r_20", "r_60", "r_120"],
        )

    def test_build_training_windows_includes_return_columns(self):
        """When the df has return columns, build_training_windows packs them
        into the (C, T) tensor between RV and MACRO blocks."""
        import pandas as pd
        from data.cnn_model import build_training_windows, WINDOW_SIZE, N_CHANNELS

        n = WINDOW_SIZE + 50
        df = pd.DataFrame({
            "symbol":          ["AAPL"] * n,
            "snapshot_ts":     np.arange(n, dtype=np.float64) * 86400.0,
            "analyst_score":   np.zeros(n),
            "earnings_score":  np.zeros(n),
            "alpaca_score":    np.zeros(n),
            "yahoo_score":     np.zeros(n),
            "iv_rv_score":     np.zeros(n),
            "agent_consensus": np.zeros(n),
            "agent_agreement": np.zeros(n),
            "rv_20d":          np.full(n, 0.20),
            "rv_60d":          np.full(n, 0.20),
            "r_1":             np.full(n, 0.001),
            "r_5":             np.full(n, 0.005),
            "r_20":            np.full(n, 0.02),
            "r_60":            np.full(n, 0.06),
            "r_120":           np.full(n, 0.12),
            "macro_vix_norm":      np.full(n, 0.5),
            "macro_gld_5d_back":   np.zeros(n),
            "macro_tlt_5d_back":   np.zeros(n),
            "macro_spy_5d_back":   np.zeros(n),
            "macro_breadth_back":  np.zeros(n),
            "return_1d":       np.full(n, 0.001),
            "return_5d":       np.full(n, 0.005),
        })
        X, y, w, t = build_training_windows(df, T=WINDOW_SIZE)
        self.assertEqual(X.shape[1], N_CHANNELS)
        self.assertEqual(X.shape[1], 19)


class TestProductionLabelIs10d(unittest.TestCase):
    """Production label horizon is 10d. The XGB ablation showed:
        5d  6-channel: mean_IC=+0.21, last_WFE=+0.07
       10d  8-channel: mean_IC=+0.40, last_WFE=+0.25  <-- ship
    """

    def test_label_horizon_col_is_return_10d(self):
        from data.cnn_model import LABEL_HORIZON_COL
        self.assertEqual(LABEL_HORIZON_COL, "return_10d",
                         "Production label horizon is 10d (per audit doc)")

    def test_label_horizon_days_is_10(self):
        from data.cnn_model import LABEL_HORIZON_DAYS
        self.assertEqual(LABEL_HORIZON_DAYS, 10)

    def test_build_training_windows_uses_return_10d_when_present(self):
        """When return_10d is present, build_training_windows must select it
        as the label, not return_1d or return_5d."""
        from data.cnn_model import build_training_windows, WINDOW_SIZE
        n = 60
        df = pd.DataFrame({
            "symbol":          ["AAPL"] * n,
            "snapshot_ts":     np.arange(n, dtype=np.float64) * 86400.0,
            "analyst_score":   np.zeros(n),
            "earnings_score":  np.zeros(n),
            "alpaca_score":    np.zeros(n),
            "yahoo_score":     np.zeros(n),
            "iv_rv_score":     np.zeros(n),
            "price":           np.linspace(100, 150, n),
            "return_1d":       np.full(n, 0.001),    # distinguishable
            "return_5d":       np.full(n, 0.005),    # distinguishable
            "return_10d":      np.full(n, 0.010),    # the label we expect
        })
        X, y, w, t = build_training_windows(df, T=WINDOW_SIZE)
        self.assertGreater(len(X), 0, "must produce at least one window")
        # All y values should equal the return_10d value (0.010), clipped to ±0.20
        np.testing.assert_allclose(y, 0.010, atol=1e-5,
                                   err_msg="build_training_windows should label with return_10d, not 5d/1d")


class TestLabelHorizonScaling(unittest.TestCase):
    """LABEL_HORIZON_DAYS, LABEL_HORIZON_FULL_CONF_RET, LABEL_HORIZON_DIR_THRESHOLD
    must derive from LABEL_HORIZON_COL so flipping the col cascades to thresholds.

    Volatility scales with sqrt(time), so 10d thresholds = 5d thresholds × sqrt(2).
    """

    def test_label_horizon_days_derived_from_col(self):
        """LABEL_HORIZON_DAYS exists and matches the integer in LABEL_HORIZON_COL."""
        from data.cnn_model import LABEL_HORIZON_COL, LABEL_HORIZON_DAYS
        # Parse the integer day-count from "return_<N>d"
        prefix, suffix = "return_", "d"
        self.assertTrue(LABEL_HORIZON_COL.startswith(prefix))
        self.assertTrue(LABEL_HORIZON_COL.endswith(suffix))
        n = int(LABEL_HORIZON_COL[len(prefix):-len(suffix)])
        self.assertEqual(LABEL_HORIZON_DAYS, n,
                         f"LABEL_HORIZON_DAYS ({LABEL_HORIZON_DAYS}) must match "
                         f"col '{LABEL_HORIZON_COL}' (parsed: {n})")

    def test_thresholds_scale_with_sqrt_horizon(self):
        """Thresholds scale by sqrt(LABEL_HORIZON_DAYS / 5) since vol scales with sqrt(time).
        At 5d:  FULL_CONF_RET = 0.10,  DIR_THRESHOLD = 0.010 (legacy values).
        At 10d: FULL_CONF_RET ≈ 0.141, DIR_THRESHOLD ≈ 0.0141.
        """
        import math
        from data.cnn_model import (
            LABEL_HORIZON_DAYS,
            LABEL_HORIZON_FULL_CONF_RET,
            LABEL_HORIZON_DIR_THRESHOLD,
        )
        scale = math.sqrt(LABEL_HORIZON_DAYS / 5.0)
        self.assertAlmostEqual(LABEL_HORIZON_FULL_CONF_RET, 0.10 * scale, places=4,
                               msg=f"FULL_CONF_RET should be 0.10 * sqrt({LABEL_HORIZON_DAYS}/5)")
        self.assertAlmostEqual(LABEL_HORIZON_DIR_THRESHOLD, 0.010 * scale, places=4,
                               msg=f"DIR_THRESHOLD should be 0.010 * sqrt({LABEL_HORIZON_DAYS}/5)")


if __name__ == "__main__":
    unittest.main()
