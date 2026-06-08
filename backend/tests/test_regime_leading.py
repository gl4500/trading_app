"""
Tests for data/regime_leading.py

compute_leading_score combines four leading-indicator components into a single
score in [-1, +1]:
  - VIX term structure (VIX / VIX3M)   — backwardation > 1.0 = stress incoming
  - Credit (HYG 5d return)             — credit deteriorates before equities
  - Defensive vs cyclical sector ratio — defensives leading = bear regime lead
  - Breadth (IWM_5d - SPY_5d)          — small-cap lag = narrowing rally

A positive score = bullish lead; negative = bearish lead. Missing components are
skipped (not zeroed) so partial data still yields a meaningful score.
"""
import unittest

from data.regime_leading import compute_leading_score


class TestLeadingScoreCleanBull(unittest.TestCase):
    def test_clean_bull_lead_returns_positive_score(self):
        # Contango VIX (0.85), HYG +1.5% / 5d, cyclical leadership, IWM ahead of SPY
        score, comps = compute_leading_score(
            fast_returns={
                "HYG": {"5d":  0.015},
                "XLU": {"5d": -0.005}, "XLP": {"5d": -0.003}, "XLV": {"5d":  0.000},
                "XLY": {"5d":  0.020}, "XLK": {"5d":  0.025}, "XLF": {"5d":  0.018},
                "IWM": {"5d":  0.030}, "SPY": {"5d":  0.015},
            },
            vix_price=14.0,
            vix3m_price=16.5,
        )
        self.assertGreater(score, 0.4, f"clean bull should give clearly +score, got {score} with {comps}")
        self.assertGreater(comps["vix_ts"], 0)
        self.assertGreater(comps["credit"], 0)
        self.assertGreater(comps["def_cyc"], 0)
        self.assertGreater(comps["breadth"], 0)


class TestLeadingScoreCleanBear(unittest.TestCase):
    def test_clean_bear_lead_returns_negative_score(self):
        # Backwardated VIX (1.10), HYG -2% / 5d, defensives leading, IWM lagging
        score, comps = compute_leading_score(
            fast_returns={
                "HYG": {"5d": -0.020},
                "XLU": {"5d":  0.015}, "XLP": {"5d":  0.012}, "XLV": {"5d":  0.010},
                "XLY": {"5d": -0.025}, "XLK": {"5d": -0.030}, "XLF": {"5d": -0.020},
                "IWM": {"5d": -0.020}, "SPY": {"5d":  0.000},
            },
            vix_price=22.0,
            vix3m_price=20.0,
        )
        self.assertLess(score, -0.4, f"clean bear should give clearly -score, got {score} with {comps}")
        self.assertLess(comps["vix_ts"], 0)
        self.assertLess(comps["credit"], 0)
        self.assertLess(comps["def_cyc"], 0)
        self.assertLess(comps["breadth"], 0)


class TestLeadingScoreNeutral(unittest.TestCase):
    def test_balanced_inputs_near_zero(self):
        # Mild contango, flat credit, no sector skew, balanced breadth
        score, _ = compute_leading_score(
            fast_returns={
                "HYG": {"5d":  0.000},
                "XLU": {"5d":  0.005}, "XLP": {"5d":  0.005}, "XLV": {"5d":  0.005},
                "XLY": {"5d":  0.005}, "XLK": {"5d":  0.005}, "XLF": {"5d":  0.005},
                "IWM": {"5d":  0.005}, "SPY": {"5d":  0.005},
            },
            vix_price=15.0,
            vix3m_price=15.8,
        )
        self.assertLess(abs(score), 0.2, f"balanced inputs should be near 0, got {score}")


class TestLeadingScoreMissingComponents(unittest.TestCase):
    def test_missing_vix3m_skips_term_structure(self):
        # No VIX3M → vix_ts is None and excluded from the mean
        score, comps = compute_leading_score(
            fast_returns={
                "HYG": {"5d": -0.020},
                "XLU": {"5d":  0.015}, "XLP": {"5d":  0.012}, "XLV": {"5d":  0.010},
                "XLY": {"5d": -0.025}, "XLK": {"5d": -0.030}, "XLF": {"5d": -0.020},
                "IWM": {"5d": -0.020}, "SPY": {"5d":  0.000},
            },
            vix_price=22.0,
            vix3m_price=None,
        )
        self.assertIsNone(comps["vix_ts"])
        self.assertLess(score, 0, "credit + def_cyc + breadth alone should still be bearish")

    def test_missing_credit_symbol_skips_component(self):
        score, comps = compute_leading_score(
            fast_returns={
                # HYG absent
                "XLU": {"5d":  0.015}, "XLP": {"5d":  0.012}, "XLV": {"5d":  0.010},
                "XLY": {"5d": -0.025}, "XLK": {"5d": -0.030}, "XLF": {"5d": -0.020},
                "IWM": {"5d": -0.020}, "SPY": {"5d":  0.000},
            },
            vix_price=22.0,
            vix3m_price=20.0,
        )
        self.assertIsNone(comps["credit"])
        self.assertLess(score, 0)

    def test_all_components_missing_returns_zero(self):
        score, comps = compute_leading_score(
            fast_returns={},
            vix_price=None,
            vix3m_price=None,
        )
        self.assertEqual(score, 0.0)
        self.assertIsNone(comps["vix_ts"])
        self.assertIsNone(comps["credit"])
        self.assertIsNone(comps["def_cyc"])
        self.assertIsNone(comps["breadth"])


class TestLeadingScoreClamping(unittest.TestCase):
    def test_extreme_inputs_clamp_to_minus_one(self):
        # Extreme stress — every component should saturate
        score, comps = compute_leading_score(
            fast_returns={
                "HYG": {"5d": -0.10},  # -10% credit blowout
                "XLU": {"5d":  0.05}, "XLP": {"5d":  0.05}, "XLV": {"5d":  0.05},
                "XLY": {"5d": -0.10}, "XLK": {"5d": -0.10}, "XLF": {"5d": -0.10},
                "IWM": {"5d": -0.10}, "SPY": {"5d":  0.00},
            },
            vix_price=50.0,
            vix3m_price=30.0,  # severe backwardation
        )
        self.assertGreaterEqual(score, -1.0)
        self.assertLessEqual(score, 1.0)
        # Each component should hit the floor
        self.assertEqual(comps["vix_ts"], -1.0)
        self.assertEqual(comps["credit"], -1.0)
        self.assertEqual(comps["def_cyc"], -1.0)
        self.assertEqual(comps["breadth"], -1.0)
        self.assertEqual(score, -1.0)

    def test_extreme_inputs_clamp_to_plus_one(self):
        score, _ = compute_leading_score(
            fast_returns={
                "HYG": {"5d":  0.10},
                "XLU": {"5d": -0.05}, "XLP": {"5d": -0.05}, "XLV": {"5d": -0.05},
                "XLY": {"5d":  0.10}, "XLK": {"5d":  0.10}, "XLF": {"5d":  0.10},
                "IWM": {"5d":  0.10}, "SPY": {"5d":  0.00},
            },
            vix_price=10.0,
            vix3m_price=18.0,  # steep contango
        )
        self.assertEqual(score, 1.0)


class TestLeadingScoreReturnShape(unittest.TestCase):
    def test_components_dict_always_has_four_keys(self):
        # Even with no input, the components dict carries all four keys
        # (None when unavailable) — caller can rely on the schema.
        _, comps = compute_leading_score(fast_returns={}, vix_price=None, vix3m_price=None)
        self.assertEqual(set(comps.keys()), {"vix_ts", "credit", "def_cyc", "breadth"})


if __name__ == "__main__":
    unittest.main()
