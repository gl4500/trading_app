"""Tests for data/xgboost_model.py — XGBoost backend mirror of SignalCNN."""
import math
import unittest

import numpy as np


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

            import agents.cnn_reasoning_agent as cra
            importlib.reload(cra)

            agent = cra.CNNReasoningAgent()

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
                 patch("data.gpu_coord.acquire_training_mutex", return_value=True), \
                 patch("data.gpu_coord.release_training_mutex"), \
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


if __name__ == "__main__":
    unittest.main()
