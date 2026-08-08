import unittest

from data.regime_term_structure import (
    compute_term_structure,
    TermStructureResult,
    term_structure_detector,
)


def _series(n=120, drift=0.0, start=100.0):
    """Deterministic price path: constant per-bar drift plus a small alternating
    wobble so realized vol is non-zero (a perfectly smooth path has zero return
    variance, which the classifier correctly treats as no-signal)."""
    px = [start]
    for i in range(n - 1):
        wobble = 0.003 if (i % 2 == 0) else -0.003
        px.append(px[-1] * (1.0 + drift + wobble))
    return px


class TestComputeTermStructure(unittest.TestCase):
    def test_sustained_uptrend_is_trending_up_zero_delta(self):
        # steady +0.2%/day for 120 bars -> long & short both strongly up
        r = compute_term_structure(_series(drift=0.002))
        self.assertIsInstance(r, TermStructureResult)
        self.assertEqual(r.state, "trending_up")
        self.assertEqual(r.gate_delta, 0.0)

    def test_long_up_short_down_is_topping(self):
        # 95 up bars then 20 down bars: long-horizon up, recent short-horizon down
        px = _series(n=95, drift=0.004)
        for _ in range(20):
            px.append(px[-1] * (1.0 - 0.004))
        r = compute_term_structure(px)
        self.assertEqual(r.state, "topping")
        self.assertAlmostEqual(r.gate_delta, 0.10, places=6)

    def test_flat_series_is_ranging_weak(self):
        # near-flat drift -> long_z below cutoff -> ranging_weak
        r = compute_term_structure(_series(drift=0.00005))
        self.assertEqual(r.state, "ranging_weak")
        self.assertAlmostEqual(r.gate_delta, 0.15, places=6)

    def test_insufficient_data_is_neutral_zero_delta(self):
        r = compute_term_structure(_series(n=40, drift=0.002))
        self.assertEqual(r.state, "neutral")
        self.assertEqual(r.gate_delta, 0.0)

    def test_custom_thresholds_are_honored(self):
        px = _series(n=95, drift=0.004)
        for _ in range(20):
            px.append(px[-1] * (1.0 - 0.004))
        r = compute_term_structure(px, delta_topping=0.07)
        self.assertEqual(r.state, "topping")
        self.assertAlmostEqual(r.gate_delta, 0.07, places=6)


class TestTermStructureDetectorSingleton(unittest.TestCase):
    def test_update_then_get_reflects_classification(self):
        px = _series(drift=0.002)   # sustained uptrend (with wobble → non-zero vol)
        term_structure_detector.update(px)
        self.assertEqual(term_structure_detector.get_state(), "trending_up")
        self.assertEqual(term_structure_detector.get_gate_delta(), 0.0)

    def test_empty_update_is_neutral_zero_delta(self):
        term_structure_detector.update([])
        self.assertEqual(term_structure_detector.get_state(), "neutral")
        self.assertEqual(term_structure_detector.get_gate_delta(), 0.0)

    def test_summary_carries_zscores(self):
        px = _series(drift=0.002)
        term_structure_detector.update(px)
        s = term_structure_detector.summary()
        self.assertIn("long_z", s)
        self.assertIn("short_z", s)
        self.assertIn("vol20d", s)


if __name__ == "__main__":
    unittest.main()
