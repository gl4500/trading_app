"""Tests for data/xgboost_model.py — XGBoost backend mirror of SignalCNN."""
import math
import unittest

import numpy as np
import pandas as pd


class TestLastTimestepFeatures(unittest.TestCase):
    """XGB-native: feed XGBoost the last timestep of each (C, T) window
    rather than flattening all T into C*T features. Lagged-return channels
    (r_1..r_120) at the last timestep already encode temporal lookback,
    so the other T-1 timesteps are redundant for trees and dilute splits.
    A/B on production parquets: flatten 190 → mean_IC +0.136 / WFE −0.059;
    last-t 19 → mean_IC +0.154 / WFE +0.003. See scripts/xgb_native_vs_flatten.py."""

    def test_2d_window_returns_last_column(self):
        from data.xgboost_model import last_timestep_features
        x = np.arange(12, dtype=np.float32).reshape(3, 4)  # 3 channels × 4 timesteps
        feats = last_timestep_features(x)
        self.assertEqual(feats.shape, (3,))
        # Each channel's LAST timestep value
        np.testing.assert_array_equal(feats, np.array([3, 7, 11], dtype=np.float32))

    def test_3d_batch_returns_last_timestep(self):
        from data.xgboost_model import last_timestep_features
        x = np.arange(60, dtype=np.float32).reshape(5, 3, 4)  # batch=5, 3 channels, T=4
        feats = last_timestep_features(x)
        self.assertEqual(feats.shape, (5, 3))
        # Sample 0, channel 0 last value = index 3; channel 1 = 7; channel 2 = 11
        np.testing.assert_array_equal(feats[0], np.array([3, 7, 11], dtype=np.float32))

    def test_invalid_shape_raises(self):
        from data.xgboost_model import last_timestep_features
        with self.assertRaises(ValueError):
            last_timestep_features(np.zeros(5))    # 1-D

    def test_flatten_window_deprecated_alias_removed(self):
        """The old flatten_window helper produced 190-feature CNN-shaped input.
        It should no longer exist — using it would silently revive the
        WFE-negative production behaviour."""
        import data.xgboost_model as xm
        self.assertFalse(hasattr(xm, "flatten_window"),
                         "flatten_window must be removed; use last_timestep_features")


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


class TestSaveLoadRoundtrip(unittest.TestCase):
    def test_save_then_load_preserves_predictions(self):
        import tempfile, os
        from unittest.mock import patch
        from data.xgboost_model import SignalXGBoost
        rng = np.random.default_rng(0)
        X = rng.standard_normal((600, 14, 10)).astype(np.float32) * 0.5
        y = (X[:, 0, :].mean(axis=1) * 0.05).astype(np.float32)
        t = np.linspace(0, 90 * 86400.0, 600, dtype=np.float64)

        with tempfile.TemporaryDirectory() as td:
            mp = os.path.join(td, "signal_xgb.json")
            with patch("data.xgboost_model._MODEL_PATH", mp):
                m = SignalXGBoost(T=10, n_channels=14)
                m.fit(X, y, t, n_folds=3, min_val_days=14)
                pre_pred, _, _ = m.predict(X[0])
                m.save()
                self.assertTrue(os.path.exists(mp))

                m2 = SignalXGBoost(T=10, n_channels=14)
                ok = m2.load()
                self.assertTrue(ok)
                post_pred, _, _ = m2.predict(X[0])
                self.assertAlmostEqual(pre_pred, post_pred, places=5)


class TestLearnedWeights(unittest.TestCase):
    def test_returns_dict_with_all_source_keys(self):
        from data.xgboost_model import SignalXGBoost
        from data.cnn_model import SOURCE_NAMES
        rng = np.random.default_rng(1)
        X = rng.standard_normal((600, 14, 10)).astype(np.float32) * 0.5
        # Inject signal in channel 0 (analyst_consensus) so importance is non-zero
        y = (X[:, 0, :].mean(axis=1) * 0.05
             + rng.standard_normal(600) * 0.01).astype(np.float32)
        t = np.linspace(0, 90 * 86400.0, 600, dtype=np.float64)

        m = SignalXGBoost(T=10, n_channels=14)
        m.fit(X, y, t, n_folds=3, min_val_days=14)
        w = m.get_learned_weights()
        self.assertIsInstance(w, dict)
        for name in SOURCE_NAMES:
            self.assertIn(name, w)
        # Importances must be non-negative and sum to 1.0 (within FP slack)
        total = sum(w.values())
        for v in w.values():
            self.assertGreaterEqual(v, 0.0)
        self.assertAlmostEqual(total, 1.0, places=4)

    def test_returns_default_weights_when_untrained(self):
        from data.xgboost_model import SignalXGBoost
        from data.cnn_model import _DEFAULT_WEIGHTS
        m = SignalXGBoost(T=10, n_channels=14)
        w = m.get_learned_weights()
        self.assertEqual(set(w.keys()), set(_DEFAULT_WEIGHTS.keys()))


class TestTrainBlockingPathUnderXGBoost(unittest.IsolatedAsyncioTestCase):
    """When MODEL_BACKEND='xgboost', _train_blocking must call signal_xgb.fit
    and signal_xgb.save without raising on CNN-specific kwargs or missing
    summary keys. Pins the contract that swapping backends doesn't break the
    agent's training entry point."""

    async def test_train_blocking_calls_xgb_fit_and_save(self):
        import importlib
        from unittest.mock import patch

        with patch("config.config.MODEL_BACKEND", "xgboost"):
            import data.signal_model as sm
            importlib.reload(sm)

            import agents.xgb_reasoning_agent as cra
            importlib.reload(cra)

            agent = cra.XGBReasoningAgent()

            # Synthesise a minimal training df (200 rows × 1 symbol) with
            # all the columns build_training_windows expects.
            import pandas as pd
            n = 200
            df = pd.DataFrame({
                "symbol":          ["AAPL"] * n,
                "snapshot_ts":     np.arange(n, dtype=np.float64) * 86400.0,
                "analyst_score":   np.zeros(n),
                "earnings_score":  np.zeros(n),
                "alpaca_score":    np.zeros(n),
                "yahoo_score":     np.zeros(n),
                "iv_rv_score":     np.zeros(n),
                "return_1d":       np.full(n, 0.001),
                "return_5d":       np.full(n, 0.005),
            })

            with patch("data.signal_history.signal_history.get_training_data",
                       return_value=df), \
                 patch.object(cra.signal_cnn, "fit") as mock_fit, \
                 patch.object(cra.signal_cnn, "save") as mock_save, \
                 patch.object(cra.signal_cnn, "training_summary",
                              return_value={
                                  "final_mse": 0.001,
                                  "device": "cpu",
                                  "learned_weights": {},
                              }):
                # _train_blocking is sync; run it in a thread executor so the
                # asyncio test infrastructure doesn't complain.
                import asyncio
                await asyncio.to_thread(agent._train_blocking)

            # cra.signal_cnn here resolves to signal_xgb because the selector
            # was reloaded under MODEL_BACKEND=xgboost. Patching .fit on it
            # patches signal_xgb.fit; _train_blocking must have hit it.
            self.assertTrue(
                mock_fit.called,
                "_train_blocking must call signal_model.fit() under MODEL_BACKEND=xgboost",
            )
            self.assertTrue(
                mock_save.called,
                "_train_blocking must persist after a successful fit",
            )

            # Real (unpatched) signal_xgb.fit must accept the kwargs the agent
            # actually passes (epochs, batch_size, sample_weights) without
            # raising. We don't actually run training; we check the call site
            # would work by inspecting the signature acceptance.
            import inspect
            from data.xgboost_model import signal_xgb
            sig = inspect.signature(signal_xgb.fit)
            # Either the kwargs are explicit parameters, or the signature
            # accepts **kwargs. Check both.
            has_var_kw = any(
                p.kind == inspect.Parameter.VAR_KEYWORD
                for p in sig.parameters.values()
            )
            params = sig.parameters
            self.assertTrue(
                has_var_kw or "epochs" in params,
                "SignalXGBoost.fit must accept 'epochs' kwarg "
                "(either explicit or via **kwargs) — agent passes epochs=80",
            )
            self.assertTrue(
                has_var_kw or "batch_size" in params,
                "SignalXGBoost.fit must accept 'batch_size' kwarg",
            )

        # Restore CNN backend by reloading modules with default config
        importlib.reload(sm)
        importlib.reload(cra)

    def test_xgb_training_summary_has_legacy_keys(self):
        """The agent's _train_blocking reads summary['final_mse'] and
        summary['learned_weights']. SignalXGBoost.training_summary must
        include both for log compatibility with the CNN backend."""
        from data.xgboost_model import signal_xgb
        s = signal_xgb.training_summary()
        self.assertIn("final_mse", s,
                      "training_summary must include 'final_mse' for agent log compatibility")
        self.assertIn("learned_weights", s,
                      "training_summary must include 'learned_weights' for agent log compatibility")
        self.assertIn("device", s)


class TestXGBoostFitsWith19Channels(unittest.TestCase):
    """Integration: SignalXGBoost.fit succeeds on 19-channel input
    (5 src + 2 agent + 2 rv + 5 returns + 5 macro)."""

    def test_fit_accepts_19_channels(self):
        from data.xgboost_model import SignalXGBoost
        rng = np.random.default_rng(0)
        n, c, T = 600, 19, 10
        X = rng.standard_normal((n, c, T)).astype(np.float32) * 0.5
        y = (X[:, 0, :].mean(axis=1) * 0.05).astype(np.float32)
        t = np.linspace(0, 90 * 86400.0, n, dtype=np.float64)

        m = SignalXGBoost(T=T, n_channels=c)
        m.fit(X, y, t, n_folds=3, min_val_days=14)
        self.assertTrue(m.is_trained)
        # Predict on a single 19-channel window must work
        pred, direction, conf = m.predict(X[0])
        self.assertIsInstance(pred, float)
        self.assertIn(direction, ("bull", "bear", "neutral"))

    def test_booster_sees_19_features_not_190(self):
        """XGB-native: booster should be trained on C features, not C*T.
        With 19 channels the booster's num_features() must equal 19, not 190."""
        from data.xgboost_model import SignalXGBoost
        rng = np.random.default_rng(0)
        n, c, T = 600, 19, 10
        X = rng.standard_normal((n, c, T)).astype(np.float32) * 0.5
        y = (X[:, 0, :].mean(axis=1) * 0.05).astype(np.float32)
        t = np.linspace(0, 90 * 86400.0, n, dtype=np.float64)

        m = SignalXGBoost(T=T, n_channels=c)
        m.fit(X, y, t, n_folds=3, min_val_days=14)
        self.assertEqual(
            m._booster.num_features(), c,
            f"Booster must see {c} features (one per channel), not {c*T} flattened",
        )


class TestXGBFeatureFilter(unittest.TestCase):
    """XGB_FEATURE_FILTER env: comma-separated channel names that signal_xgb
    must slice the 19-channel input down to. Production setting (10d):
        analyst_score,earnings_score,alpaca_score,iv_rv_score,
        r_120,macro_vix_norm,macro_spy_5d_back,macro_breadth_back
    Reduces booster input from 19 → 8 features per sample.
    """

    WINNING_8 = [
        "analyst_score", "earnings_score", "alpaca_score", "iv_rv_score",
        "r_120", "macro_vix_norm", "macro_spy_5d_back", "macro_breadth_back",
    ]
    WINNING_8_INDICES = [0, 1, 2, 4, 13, 14, 17, 18]   # against ALL_CHANNEL_COLUMNS

    def test_parse_filter_resolves_names_to_indices(self):
        """Helper that parses 'a,b,c' -> [0,1,2] using ALL_CHANNEL_COLUMNS."""
        from data.xgboost_model import _parse_feature_filter
        from unittest.mock import patch
        with patch.dict("os.environ", {"XGB_FEATURE_FILTER": ",".join(self.WINNING_8)}):
            idx = _parse_feature_filter()
        self.assertEqual(idx, self.WINNING_8_INDICES)

    def test_parse_filter_empty_returns_none(self):
        """Default (empty env var) returns None — use all 19 channels."""
        from data.xgboost_model import _parse_feature_filter
        from unittest.mock import patch
        with patch.dict("os.environ", {"XGB_FEATURE_FILTER": ""}):
            self.assertIsNone(_parse_feature_filter())

    def test_parse_filter_unknown_name_raises(self):
        """Typos in the env should fail loudly, not silently degrade."""
        from data.xgboost_model import _parse_feature_filter
        from unittest.mock import patch
        with patch.dict("os.environ", {"XGB_FEATURE_FILTER": "rv_20d,not_a_real_channel"}):
            with self.assertRaises(ValueError):
                _parse_feature_filter()

    def test_fit_with_filter_reduces_booster_features(self):
        """When feature_filter is set, the trained booster should see
        len(filter) features per sample, not the full 19."""
        from data.xgboost_model import SignalXGBoost
        rng = np.random.default_rng(0)
        n, c, T = 600, 19, 10
        X = rng.standard_normal((n, c, T)).astype(np.float32) * 0.5
        y = (X[:, 0, :].mean(axis=1) * 0.05).astype(np.float32)
        t = np.linspace(0, 90 * 86400.0, n, dtype=np.float64)

        m = SignalXGBoost(T=T, n_channels=c, feature_filter=self.WINNING_8_INDICES)
        m.fit(X, y, t, n_folds=3, min_val_days=14)
        self.assertEqual(
            m._booster.num_features(), len(self.WINNING_8_INDICES),
            "Booster must see 8 features when feature_filter has 8 entries",
        )

    def test_predict_with_filter_accepts_full_window_input(self):
        """predict() input is the FULL (19, T) window from get_recent_window;
        the filter is applied internally before passing to the booster."""
        from data.xgboost_model import SignalXGBoost
        rng = np.random.default_rng(0)
        n, c, T = 600, 19, 10
        X = rng.standard_normal((n, c, T)).astype(np.float32) * 0.5
        y = (X[:, 0, :].mean(axis=1) * 0.05).astype(np.float32)
        t = np.linspace(0, 90 * 86400.0, n, dtype=np.float64)
        m = SignalXGBoost(T=T, n_channels=c, feature_filter=self.WINNING_8_INDICES)
        m.fit(X, y, t, n_folds=3, min_val_days=14)
        # Caller passes the FULL 19-channel window
        x_full = X[0]                      # (19, 10)
        pred, direction, conf = m.predict(x_full)
        self.assertIsInstance(pred, float)
        self.assertIn(direction, ("bull", "bear", "neutral"))

    def test_filter_persisted_through_save_load(self):
        """save/load must round-trip the feature_filter so a reloaded
        booster slices predict input identically."""
        import tempfile, os
        from unittest.mock import patch
        from data.xgboost_model import SignalXGBoost
        rng = np.random.default_rng(0)
        n, c, T = 600, 19, 10
        X = rng.standard_normal((n, c, T)).astype(np.float32) * 0.5
        y = (X[:, 0, :].mean(axis=1) * 0.05).astype(np.float32)
        t = np.linspace(0, 90 * 86400.0, n, dtype=np.float64)

        with tempfile.TemporaryDirectory() as td:
            mp = os.path.join(td, "signal_xgb.json")
            with patch("data.xgboost_model._MODEL_PATH", mp):
                m = SignalXGBoost(T=T, n_channels=c, feature_filter=self.WINNING_8_INDICES)
                m.fit(X, y, t, n_folds=3, min_val_days=14)
                pred_pre, _, _ = m.predict(X[0])
                m.save()

                m2 = SignalXGBoost(T=T, n_channels=c)   # fresh, no env, no filter
                ok = m2.load()
                self.assertTrue(ok)
                self.assertEqual(m2._feature_filter, self.WINNING_8_INDICES,
                                 "load() must restore the saved feature_filter")
                pred_post, _, _ = m2.predict(X[0])
                self.assertAlmostEqual(pred_pre, pred_post, places=5)


class TestEndToEnd10dWith8ChFilter(unittest.TestCase):
    """End-to-end: 10d label + 8-channel filter going through the real
    build_training_windows pipeline. Pins the production data flow."""

    def test_full_pipeline_10d_label_8ch_filter(self):
        from data.cnn_model import (
            build_training_windows, WINDOW_SIZE, LABEL_HORIZON_COL,
        )
        from data.xgboost_model import SignalXGBoost
        # Sanity: T3 shipped, label is 10d
        self.assertEqual(LABEL_HORIZON_COL, "return_10d")

        n = 600
        rng = np.random.default_rng(0)
        # Synthesize a df with all 20 channel columns + 10d label populated
        # (5 src + 2 agent + 2 rv + 5 ret + 6 macro post-#84 = 20).
        # Use 2 symbols × 300 rows so build_training_windows has per-symbol scope.
        rows = []
        for sym in ("AAPL", "MSFT"):
            base = rng.standard_normal((n // 2, 20)).astype(np.float64) * 0.1
            df_sym = {
                "symbol":          [sym] * (n // 2),
                "snapshot_ts":     np.arange(n // 2, dtype=np.float64) * 86_400.0,
                "price":           np.linspace(100.0, 200.0, n // 2),
                # 20 raw channel columns
                "analyst_score":     base[:, 0],
                "earnings_score":    base[:, 1],
                "alpaca_score":      base[:, 2],
                "yahoo_score":       base[:, 3],
                "iv_rv_score":       base[:, 4],
                "agent_consensus":   base[:, 5],
                "agent_agreement":   np.abs(base[:, 6]),
                "rv_20d":            np.abs(base[:, 7]) + 0.10,
                "rv_60d":            np.abs(base[:, 8]) + 0.10,
                # The lagged-return columns will be recomputed by
                # _compute_return_features at read time, but we provide them
                # directly here for the synthetic test.
                "r_1":   base[:, 9],
                "r_5":   base[:, 10],
                "r_20":  base[:, 11],
                "r_60":  base[:, 12],
                "r_120": base[:, 13],
                "macro_vix_norm":     np.abs(base[:, 14]),
                "macro_gld_5d_back":  base[:, 15],
                "macro_tlt_5d_back":  base[:, 16],
                "macro_spy_5d_back":  base[:, 17],
                "macro_breadth_back": base[:, 18],
                "macro_dji_5d_back":  base[:, 19],   # 2026-05-09 (#84)
                # 10d label — small noise around channel 0 for learnable signal
                "return_10d":  base[:, 0] * 0.05 + rng.standard_normal(n // 2) * 0.01,
                "return_1d":   np.full(n // 2, 0.001),  # fallback if 10d missing
            }
            rows.append(pd.DataFrame(df_sym))
        df = pd.concat(rows, ignore_index=True)

        X, y, w, t = build_training_windows(df, T=WINDOW_SIZE)
        self.assertEqual(X.shape[1], 20, "build_training_windows should emit 20 channels post-#84")

        # Production 8-channel 10d winner — same indices, all ≤ 18 so DJI
        # appending at index 19 doesn't shift them.
        WINNING_8_INDICES = [0, 1, 2, 4, 13, 14, 17, 18]
        m = SignalXGBoost(T=WINDOW_SIZE, n_channels=20, feature_filter=WINNING_8_INDICES)
        m.fit(X, y, t, n_folds=3, min_val_days=14)
        self.assertTrue(m.is_trained)
        self.assertEqual(m._booster.num_features(), 8)

        # predict on a full 20-channel window (matches get_recent_window output)
        x_full = X[0]
        self.assertEqual(x_full.shape, (20, WINDOW_SIZE))
        pred, direction, conf = m.predict(x_full)
        self.assertIsInstance(pred, float)
        self.assertIn(direction, ("bull", "bear", "neutral"))


class TestEnsemblePredict(unittest.TestCase):
    """ensemble_predict() — the K=10 bootstrapped boosters from
    scripts/train_xgb_ensemble.py. Returns (mean, std, n_used) where:
      - mean: averaged prediction across loaded boosters
      - std: cross-booster prediction std, used for confidence gating
      - n_used: how many ensemble boosters were actually loaded (0 → fallback)

    When ensemble files are missing, the model falls back gracefully to its
    base predict() output: returns (pred, NaN, 0) so callers can detect
    the "no ensemble available" state and skip uncertainty-based sizing."""

    def _make_trained_model(self):
        from data.cnn_model import N_CHANNELS, WINDOW_SIZE
        from data.xgboost_model import SignalXGBoost
        rng = np.random.default_rng(0)
        n = 200
        X = rng.standard_normal((n, N_CHANNELS, WINDOW_SIZE)).astype(np.float32)
        y = rng.standard_normal(n).astype(np.float32) * 0.05
        ts = np.arange(n, dtype=np.float64) * 86_400.0
        m = SignalXGBoost()
        m.fit(X, y, ts)
        return m

    def test_ensemble_predict_returns_tuple_with_n_used(self):
        """ensemble_predict must return (mean, std, n_used) — three fields,
        not the (pred, direction, confidence) of base predict()."""
        import tempfile
        from unittest.mock import patch
        from data.cnn_model import N_CHANNELS, WINDOW_SIZE
        m = self._make_trained_model()
        x = np.random.randn(N_CHANNELS, WINDOW_SIZE).astype(np.float32)
        # Patch _MODEL_DIR to an empty dir so we don't pick up real production
        # ensemble files (which were trained with a different feature_filter
        # and would 38-vs-16-cols mismatch this test's freshly-trained model).
        with tempfile.TemporaryDirectory() as empty_dir, \
             patch("data.xgboost_model._MODEL_DIR", empty_dir):
            result = m.ensemble_predict(x)
        self.assertEqual(len(result), 3)

    def test_ensemble_falls_back_when_files_missing(self):
        """With no signal_xgb_b{k}.json files on disk, ensemble_predict must
        return (base_pred, NaN, 0) — same prediction as predict(), zero
        boosters used, NaN std signaling 'no uncertainty estimate available'."""
        import tempfile
        from unittest.mock import patch
        from data.cnn_model import N_CHANNELS, WINDOW_SIZE
        m = self._make_trained_model()
        x = np.random.randn(N_CHANNELS, WINDOW_SIZE).astype(np.float32)

        with tempfile.TemporaryDirectory() as empty_dir, \
             patch("data.xgboost_model._MODEL_DIR", empty_dir):
            mean, std, n_used = m.ensemble_predict(x)

        self.assertEqual(n_used, 0)
        self.assertTrue(math.isnan(std))
        # Mean equals base predict()'s pred field
        base_pred, _, _ = m.predict(x)
        self.assertAlmostEqual(mean, base_pred, places=5)

    def test_ensemble_uses_loaded_boosters_when_present(self):
        """With K boosters saved to disk, ensemble_predict must:
          - load them (lazy-cached after first call),
          - report n_used == K,
          - report a non-NaN std,
          - return mean ≈ average of per-booster predictions."""
        import tempfile
        from unittest.mock import patch
        from data.cnn_model import N_CHANNELS, WINDOW_SIZE
        m = self._make_trained_model()
        x = np.random.randn(N_CHANNELS, WINDOW_SIZE).astype(np.float32)

        with tempfile.TemporaryDirectory() as tmp:
            # Save the same booster K times (real ensemble would have
            # bootstrap-different boosters; here we just need the load
            # path to succeed)
            K = 3
            for k in range(K):
                m._booster.save_model(__import__("os").path.join(
                    tmp, f"signal_xgb_b{k}.json"))
            with patch("data.xgboost_model._MODEL_DIR", tmp):
                # Clear any cached boosters from prior tests
                if hasattr(m, "_ensemble_boosters"):
                    m._ensemble_boosters = None
                mean, std, n_used = m.ensemble_predict(x)

        self.assertEqual(n_used, K)
        self.assertFalse(math.isnan(std))
        # All K boosters identical → std is exactly 0
        self.assertEqual(std, 0.0)
        base_pred, _, _ = m.predict(x)
        self.assertAlmostEqual(mean, base_pred, places=5)

    def test_ensemble_predict_caches_boosters(self):
        """Loading 10 boosters from disk takes time; subsequent calls
        must reuse the cached boosters list, not re-load every time."""
        import tempfile
        from unittest.mock import patch
        from data.cnn_model import N_CHANNELS, WINDOW_SIZE
        m = self._make_trained_model()
        x = np.random.randn(N_CHANNELS, WINDOW_SIZE).astype(np.float32)

        with tempfile.TemporaryDirectory() as tmp:
            for k in range(2):
                m._booster.save_model(__import__("os").path.join(
                    tmp, f"signal_xgb_b{k}.json"))
            with patch("data.xgboost_model._MODEL_DIR", tmp):
                if hasattr(m, "_ensemble_boosters"):
                    m._ensemble_boosters = None
                _ = m.ensemble_predict(x)
                # After first call, _ensemble_boosters must be cached as a list
                self.assertIsNotNone(getattr(m, "_ensemble_boosters", None))
                self.assertEqual(len(m._ensemble_boosters), 2)


if __name__ == "__main__":
    unittest.main()
