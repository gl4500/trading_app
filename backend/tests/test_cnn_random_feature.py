"""
Random-feature sanity test: when an extra channel of pure noise is appended
to the training data, the model's first-conv importance for that channel
should be in the bottom half of all channels.

This is a one-off harness test — running it on real signal_history data
tells us whether the model is correctly identifying noise vs signal.

Usage:
    cd backend
    PYTHONPATH=../site-packages ../runtime/python/python.exe \
      -m unittest tests.test_cnn_random_feature -v
"""
import unittest

import numpy as np


class TestRandomFeatureRanksLow(unittest.TestCase):
    # KNOWN FAILURE as of 2026-04-27: the GLU-gated CNN ranks the appended
    # pure-noise channel as the MOST important feature on this synthetic
    # signal+noise dataset (rank 0/6). This corroborates the production
    # observation that WFE has been negative across 5 retrains — the model
    # is fitting noise rather than the underlying signal channel.
    #
    # Marked expectedFailure so:
    #   1. The CI suite stays green during normal runs.
    #   2. When the model architecture / regularization is fixed and noise
    #      correctly ranks last, this test will UNEXPECTEDLY PASS and the
    #      failure marker can be removed — that's the success signal.
    # See docs/superpowers/plans/2026-04-27-cnn-evaluation-harness.md (Task 7).
    @unittest.expectedFailure
    def test_synthetic_signal_plus_noise(self):
        """Channel 0 has signal; appended channel C is pure noise.
        After training, channel C's importance must rank in the bottom half."""
        from data.cnn_model import SignalCNN

        rng = np.random.default_rng(0)
        n, base_c, T = 1500, 5, 10
        # Signal channel (channel 0) drives y
        X = rng.standard_normal((n, base_c, T)).astype(np.float32) * 0.5
        y = (X[:, 0, :].mean(axis=1) * 0.05).astype(np.float32)
        # Append a pure-noise channel
        noise = rng.standard_normal((n, 1, T)).astype(np.float32)
        X_aug = np.concatenate([X, noise], axis=1)
        t = np.linspace(0, 90 * 86400.0, n, dtype=np.float64)

        cnn = SignalCNN(T=T, n_channels=base_c + 1)
        cnn.fit(X_aug, y, t, epochs=15, batch_size=32, n_folds=3, min_val_days=14)

        # Importance from first conv layer's main path
        first_block = cnn._net[0]
        W = first_block.conv_main.weight.detach().cpu().numpy()  # (16, C, 3)
        importance = np.abs(W).sum(axis=(0, 2))  # (C,)
        rank = (-importance).argsort().argsort()  # 0 = most important
        noise_rank = int(rank[-1])  # appended noise channel is index C
        n_chan = base_c + 1
        msg = (f"Random feature ranked {noise_rank}/{n_chan} "
               f"(should be in bottom half ≥ {n_chan // 2})")
        self.assertGreaterEqual(noise_rank, n_chan // 2, msg)


if __name__ == "__main__":
    unittest.main()
