"""
Unit tests for data/w3_model.py — the W3 per-group + regime-blend backprop model
used as an ensemble vote alongside XGBoost in xgb_reasoning_agent.

W3 = per-group linear sub-models (Catalyst/Momentum/Regime) blended by a
regime-conditional softmax. See session 2026-05-23 for the model derivation
and the backlog memory backlog_trading_app_w3_ensemble.

Conventions:
  - unittest.TestCase (CLAUDE.md: pytest not in runtime; use run_tests.py)
  - No real model file — every test generates a synthetic .pt in tempfile.
  - Tests must not require torch CUDA — exercise the CPU path.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages")))

import numpy as np

# Defer torch import to a try/except so the test file can be discovered even if
# torch is missing in CI sub-environments; individual tests skip explicitly.
try:
    import torch  # noqa: F401
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False


class TestSignalW3LoadSave(unittest.TestCase):
    """Construction, load(), save() round-trip semantics."""

    @unittest.skipUnless(HAS_TORCH, "torch not available")
    def test_load_returns_false_when_file_missing(self):
        from data.w3_model import SignalW3
        with tempfile.TemporaryDirectory() as td:
            m = SignalW3(model_path=os.path.join(td, "nope.pt"))
            self.assertFalse(m.load())
            self.assertFalse(m.is_trained)

    @unittest.skipUnless(HAS_TORCH, "torch not available")
    def test_train_save_load_round_trip(self):
        from data.w3_model import SignalW3
        with tempfile.TemporaryDirectory() as td:
            # Synthetic windowed dataset: (N=400, C=38, T=10)
            N, C, T = 400, 38, 10
            rng = np.random.default_rng(7)
            X = rng.standard_normal((N, C, T)).astype(np.float32)
            # Make the label loosely depend on channel 0 (analyst_score) at last lag
            y = (0.05 * X[:, 0, -1] + 0.001 * rng.standard_normal(N)).astype(np.float32)
            t = np.linspace(0, 90 * 86400, N).astype(np.float64)
            w = np.ones(N, dtype=np.float32)

            m = SignalW3(model_path=os.path.join(td, "w3.pt"))
            m.fit(X, y, t, sample_weights=w)
            self.assertTrue(m.is_trained)
            self.assertIsNotNone(m.mean_wfe)
            m.save()

            m2 = SignalW3(model_path=os.path.join(td, "w3.pt"))
            self.assertTrue(m2.load())
            self.assertTrue(m2.is_trained)
            # Same prediction on a fresh window (within float tolerance)
            window = rng.standard_normal((C, T)).astype(np.float32)
            p1 = m.predict(window)[0]
            p2 = m2.predict(window)[0]
            self.assertAlmostEqual(p1, p2, places=5)


class TestSignalW3Predict(unittest.TestCase):
    """predict() shape and behavior."""

    @unittest.skipUnless(HAS_TORCH, "torch not available")
    def setUp(self):
        from data.w3_model import SignalW3
        self.SignalW3 = SignalW3
        N, C, T = 300, 38, 10
        rng = np.random.default_rng(11)
        X = rng.standard_normal((N, C, T)).astype(np.float32)
        # Make analyst_score (chan 0, lag -1) predictive of forward return
        y = (0.10 * X[:, 0, -1] + 0.005 * rng.standard_normal(N)).astype(np.float32)
        t = np.linspace(0, 90 * 86400, N).astype(np.float64)
        self.tmp = tempfile.TemporaryDirectory()
        self.m = SignalW3(model_path=os.path.join(self.tmp.name, "w3.pt"))
        self.m.fit(X, y, t)
        self.C, self.T = C, T

    def tearDown(self):
        self.tmp.cleanup()

    def test_predict_returns_three_tuple(self):
        window = np.zeros((self.C, self.T), dtype=np.float32)
        out = self.m.predict(window)
        self.assertEqual(len(out), 3)
        pred, direction, conf = out
        self.assertIsInstance(pred, float)
        self.assertIsInstance(direction, str)
        self.assertIsInstance(conf, float)
        self.assertIn(direction, ("bull", "bear", "neutral"))
        self.assertGreaterEqual(conf, 0.0)
        self.assertLessEqual(conf, 1.0)

    def test_predict_direction_responds_to_input(self):
        """Strongly-positive analyst signal should not predict bearish."""
        window = np.zeros((self.C, self.T), dtype=np.float32)
        window[0, -1] = 5.0   # large positive analyst signal
        pred_pos, dir_pos, _ = self.m.predict(window)
        window[0, -1] = -5.0
        pred_neg, dir_neg, _ = self.m.predict(window)
        # Prediction should move in the same direction as the input nudge
        self.assertGreater(pred_pos, pred_neg)

    def test_predict_handles_window_with_fewer_lags_gracefully(self):
        """W3 only consumes the last timestep — narrower window OK as long as it has at least one lag."""
        window = np.zeros((self.C, 1), dtype=np.float32)
        out = self.m.predict(window)
        self.assertEqual(len(out), 3)


class TestSignalW3CompatSurface(unittest.TestCase):
    """Attributes the xgb_reasoning_agent expects to find on SignalW3 (parity with SignalXGBoost)."""

    @unittest.skipUnless(HAS_TORCH, "torch not available")
    def test_attributes_present(self):
        from data.w3_model import SignalW3
        m = SignalW3()
        # Before training
        self.assertFalse(m.is_trained)
        self.assertEqual(m.last_train_time, 0.0)
        self.assertIsNone(m.mean_wfe)
        self.assertEqual(m.T, 10)  # window size for compat with signal_history.get_recent_window

    @unittest.skipUnless(HAS_TORCH, "torch not available")
    def test_module_level_singleton_exists(self):
        from data import w3_model
        self.assertTrue(hasattr(w3_model, "signal_w3"))
        self.assertIsInstance(w3_model.signal_w3, w3_model.SignalW3)


class TestSignalW3DeviceSelection(unittest.TestCase):
    """W3_DEVICE env governs training device; inference is always CPU."""

    @unittest.skipUnless(HAS_TORCH, "torch not available")
    def test_default_train_device_is_cpu(self):
        """No env override -> CPU even on a CUDA-capable machine."""
        from data import w3_model
        # Force the env to be unset for this test
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("W3_DEVICE", None)
            dev = w3_model._resolve_train_device()
        self.assertEqual(dev.type, "cpu",
                         "default must be CPU to avoid Ollama GPU contention")

    @unittest.skipUnless(HAS_TORCH, "torch not available")
    def test_env_cuda_picks_cuda_when_available(self):
        """Sidecar scripts can opt into GPU with W3_DEVICE=cuda."""
        from data import w3_model
        with unittest.mock.patch.dict(os.environ, {"W3_DEVICE": "cuda"}):
            dev = w3_model._resolve_train_device()
        expected = "cuda" if torch.cuda.is_available() else "cpu"
        self.assertEqual(dev.type, expected,
                         "W3_DEVICE=cuda should pick cuda when available, "
                         "fall back to cpu when not")

    @unittest.skipUnless(HAS_TORCH, "torch not available")
    def test_loaded_model_lives_on_cpu(self):
        """After fit + load, the model's parameters must be on CPU
        so inference never touches the GPU."""
        from data.w3_model import SignalW3
        with tempfile.TemporaryDirectory() as td, \
             unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("W3_DEVICE", None)
            N, C, T = 400, 38, 10
            rng = np.random.default_rng(13)
            X = rng.standard_normal((N, C, T)).astype(np.float32)
            y = (0.05 * X[:, 0, -1] + 0.001 * rng.standard_normal(N)).astype(np.float32)
            t = np.linspace(0, 90 * 86400, N).astype(np.float64)
            m = SignalW3(model_path=os.path.join(td, "w3_cpu.pt"))
            m.fit(X, y, t)
            self.assertTrue(m.is_trained)
            # Inspect a parameter device
            for p in m._model.parameters():
                self.assertEqual(p.device.type, "cpu",
                                 "trained model must live on CPU after fit()")
                break


if __name__ == "__main__":
    unittest.main()
