"""
Tests for data/regime_detector.py

Covers:
  - Regime classification (bull / bear / neutral / high_vol)
  - Confidence bounds
  - EnsembleAgent mapping
  - summary() keys
  - Edge cases (insufficient data, empty list)
"""
import math
import unittest


class TestRegimeClassification(unittest.TestCase):

    def _rising_prices(self, n: int = 25, start: float = 150.0, drift: float = 0.003):
        p = start
        prices = [p]
        for _ in range(n - 1):
            p *= (1 + drift)
            prices.append(p)
        return prices

    def _falling_prices(self, n: int = 25, start: float = 150.0, drift: float = -0.004):
        p = start
        prices = [p]
        for _ in range(n - 1):
            p *= (1 + drift)
            prices.append(p)
        return prices

    def _choppy_prices(self, n: int = 30, start: float = 150.0, swing: float = 0.05):
        """Alternating +swing/-swing to generate very high volatility."""
        p = start
        prices = [p]
        for i in range(n - 1):
            p *= (1 + swing if i % 2 == 0 else 1 - swing)
            prices.append(max(1.0, p))
        return prices

    # ── Bull ──────────────────────────────────────────────────────────────────

    def test_steady_uptrend_is_bull(self):
        from data.regime_detector import RegimeDetector
        det = RegimeDetector()
        det.update(self._rising_prices(25, drift=0.003))
        regime, _ = det.get_regime()
        self.assertEqual(regime, "bull")

    def test_strong_uptrend_is_bull_not_high_vol(self):
        """A clean 0.3 %/day uptrend should be bull, vol is low."""
        from data.regime_detector import RegimeDetector
        det = RegimeDetector()
        det.update(self._rising_prices(30, drift=0.003))
        regime, conf = det.get_regime()
        self.assertEqual(regime, "bull")
        self.assertGreater(conf, 0.0)

    # ── Bear ──────────────────────────────────────────────────────────────────

    def test_steady_downtrend_is_bear(self):
        from data.regime_detector import RegimeDetector
        det = RegimeDetector()
        det.update(self._falling_prices(25, drift=-0.004))
        regime, _ = det.get_regime()
        self.assertEqual(regime, "bear")

    def test_bear_confidence_positive(self):
        from data.regime_detector import RegimeDetector
        det = RegimeDetector()
        det.update(self._falling_prices(25, drift=-0.005))
        _, conf = det.get_regime()
        self.assertGreater(conf, 0.0)

    # ── High-vol ──────────────────────────────────────────────────────────────

    def test_choppy_prices_are_high_vol(self):
        """±5 % daily swings → high_vol."""
        from data.regime_detector import RegimeDetector
        det = RegimeDetector()
        det.update(self._choppy_prices(30, swing=0.05))
        regime, _ = det.get_regime()
        self.assertEqual(regime, "high_vol")

    def test_extreme_vol_is_high_vol(self):
        """±10 % daily → definitely high_vol."""
        from data.regime_detector import RegimeDetector
        det = RegimeDetector()
        det.update(self._choppy_prices(30, swing=0.10))
        regime, _ = det.get_regime()
        self.assertEqual(regime, "high_vol")

    # ── Neutral ───────────────────────────────────────────────────────────────

    def test_flat_prices_neutral(self):
        """Zero change → neutral."""
        from data.regime_detector import RegimeDetector
        det = RegimeDetector()
        det.update([150.0] * 25)
        regime, _ = det.get_regime()
        self.assertEqual(regime, "neutral")

    def test_near_flat_prices_neutral(self):
        """Tiny drift (0.05 %/day) → neutral (below 2 % threshold)."""
        from data.regime_detector import RegimeDetector
        det = RegimeDetector()
        det.update(self._rising_prices(25, drift=0.0005))
        regime, _ = det.get_regime()
        self.assertEqual(regime, "neutral")

    # ── Edge cases ────────────────────────────────────────────────────────────

    def test_insufficient_data_returns_neutral_zero_conf(self):
        from data.regime_detector import RegimeDetector
        det = RegimeDetector()
        det.update([150.0] * 10)
        regime, conf = det.get_regime()
        self.assertEqual(regime, "neutral")
        self.assertEqual(conf, 0.0)

    def test_empty_list_returns_neutral_zero_conf(self):
        from data.regime_detector import RegimeDetector
        det = RegimeDetector()
        det.update([])
        regime, conf = det.get_regime()
        self.assertEqual(regime, "neutral")
        self.assertEqual(conf, 0.0)

    def test_exactly_21_prices_classified(self):
        """Exactly the minimum required prices should produce a valid classification."""
        from data.regime_detector import RegimeDetector
        det = RegimeDetector()
        det.update(self._rising_prices(21, drift=0.003))
        regime, _ = det.get_regime()
        self.assertIn(regime, {"bull", "bear", "neutral", "high_vol"})

    def test_initial_state_neutral(self):
        """Before any update, regime is neutral, confidence is 0."""
        from data.regime_detector import RegimeDetector
        det = RegimeDetector()
        regime, conf = det.get_regime()
        self.assertEqual(regime, "neutral")
        self.assertEqual(conf, 0.0)

    def test_zero_prices_filtered(self):
        """Zero or negative prices in feed do not crash."""
        from data.regime_detector import RegimeDetector
        det = RegimeDetector()
        prices = [0.0, -1.0] + [150.0] * 25
        det.update(prices)
        regime, _ = det.get_regime()
        self.assertIn(regime, {"bull", "bear", "neutral", "high_vol"})


class TestRegimeConfidenceBounds(unittest.TestCase):

    def _all_regimes(self):
        from data.regime_detector import RegimeDetector
        det = RegimeDetector()
        cases = []

        # bull
        p = 150.0
        prices = [p]
        for _ in range(29):
            p *= 1.003
            prices.append(p)
        det.update(prices)
        cases.append(det.get_regime())

        # bear
        p = 150.0
        prices = [p]
        for _ in range(29):
            p *= 0.996
            prices.append(p)
        det.update(prices)
        cases.append(det.get_regime())

        # high_vol
        p = 150.0
        prices = [p]
        for i in range(29):
            p *= (1.05 if i % 2 == 0 else 0.95)
            prices.append(max(1.0, p))
        det.update(prices)
        cases.append(det.get_regime())

        # neutral
        det.update([150.0] * 25)
        cases.append(det.get_regime())

        return cases

    def test_confidence_in_0_1_for_all_regimes(self):
        for regime, conf in self._all_regimes():
            with self.subTest(regime=regime):
                self.assertGreaterEqual(conf, 0.0, f"{regime}: conf < 0")
                self.assertLessEqual(conf, 1.0, f"{regime}: conf > 1")


class TestRegimeEnsembleMapping(unittest.TestCase):

    def _det_with_regime(self, regime: str):
        from data.regime_detector import RegimeDetector
        det = RegimeDetector()
        det._regime = regime
        return det

    def test_bull_maps_to_trending(self):
        det = self._det_with_regime("bull")
        self.assertEqual(det.get_ensemble_regime(), "trending")

    def test_neutral_maps_to_ranging(self):
        det = self._det_with_regime("neutral")
        self.assertEqual(det.get_ensemble_regime(), "ranging")

    def test_bear_maps_to_volatile(self):
        det = self._det_with_regime("bear")
        self.assertEqual(det.get_ensemble_regime(), "volatile")

    def test_high_vol_maps_to_volatile(self):
        det = self._det_with_regime("high_vol")
        self.assertEqual(det.get_ensemble_regime(), "volatile")

    def test_unknown_regime_maps_to_ranging(self):
        det = self._det_with_regime("unknown_state")
        self.assertEqual(det.get_ensemble_regime(), "ranging")


class TestRegimeSummary(unittest.TestCase):

    def test_summary_required_keys(self):
        from data.regime_detector import RegimeDetector
        det = RegimeDetector()
        det.update([150.0] * 25)
        s = det.summary()
        for key in ("regime", "confidence", "ensemble_regime", "n_prices"):
            self.assertIn(key, s)

    def test_summary_n_prices_matches_input(self):
        from data.regime_detector import RegimeDetector
        det = RegimeDetector()
        det.update([150.0] * 30)
        self.assertEqual(det.summary()["n_prices"], 30)

    def test_summary_regime_valid_string(self):
        from data.regime_detector import RegimeDetector
        det = RegimeDetector()
        det.update([150.0] * 25)
        self.assertIn(det.summary()["regime"], {"bull", "bear", "neutral", "high_vol"})

    def test_summary_ensemble_regime_valid(self):
        from data.regime_detector import RegimeDetector
        det = RegimeDetector()
        det.update([150.0] * 25)
        self.assertIn(det.summary()["ensemble_regime"], {"trending", "ranging", "volatile"})


class TestRegimeModuleLevel(unittest.TestCase):

    def test_singleton_importable(self):
        """Module-level singleton is accessible."""
        from data.regime_detector import regime_detector, RegimeDetector
        self.assertIsInstance(regime_detector, RegimeDetector)


if __name__ == "__main__":
    unittest.main()
