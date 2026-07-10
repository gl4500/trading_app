"""Unit tests for xgb_decision — pure BUY decision helpers."""
import sys
import os
import unittest
from unittest import mock

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agents.xgb_decision import BuyContext, BuyDecision, decide_buy
from config import config


def _ctx(**overrides):
    """Helper — build a BuyContext that passes every gate by default;
    individual tests override one field at a time to exercise each gate."""
    defaults = dict(
        symbol="AAPL",
        model_pred_return=0.03,
        model_pred_direction="up",
        model_confidence=0.80,          # comfortably above CNN_BUY_THRESHOLD_BASE=0.65
        regime="neutral",               # no regime add-on
        portfolio_unpnl_frac=0.0,       # not in drawdown
        n_corroborators=config.LONEWOLF_MIN_CORROBORATORS,  # not lone wolf
        in_trail_cooldown=False,
        current_price=200.0,
        cash_available=20000.0,
        portfolio_value=100000.0,
        kelly_fraction=0.10,
    )
    defaults.update(overrides)
    return BuyContext(**defaults)


class TestBuyContextDataclass(unittest.TestCase):
    def test_frozen_immutable(self):
        ctx = _ctx()
        with self.assertRaises(Exception):       # frozen dataclass blocks assignment
            ctx.model_confidence = 0.5           # type: ignore[misc]


class TestBuyDecisionDataclass(unittest.TestCase):
    def test_hold_decision_constructed_with_zero_shares(self):
        d = BuyDecision(action="HOLD", shares=0, sized_confidence=0.5, reason="test")
        self.assertEqual(d.action, "HOLD")
        self.assertEqual(d.shares, 0)


class TestDecideBuyGates(unittest.TestCase):
    """Five gates evaluated in order. Any one failing → HOLD."""

    def test_holds_when_direction_not_up(self):
        d = decide_buy(_ctx(model_pred_direction="down"), config)
        self.assertEqual(d.action, "HOLD")
        self.assertIn("bullish", d.reason.lower())

    def test_holds_when_direction_neutral(self):
        d = decide_buy(_ctx(model_pred_direction="neutral"), config)
        self.assertEqual(d.action, "HOLD")

    def test_holds_when_confidence_below_buy_threshold_base(self):
        # config.CNN_BUY_THRESHOLD_BASE = 0.65 (default per .env)
        d = decide_buy(_ctx(model_confidence=0.50), config)
        self.assertEqual(d.action, "HOLD")
        self.assertIn("conf", d.reason.lower())

    def test_passes_confidence_gate_when_at_or_above_threshold(self):
        d = decide_buy(_ctx(model_confidence=0.65, regime="neutral"), config)
        self.assertEqual(d.action, "BUY")

    def test_holds_in_bear_regime_when_below_adjusted_threshold(self):
        # bear adds 0.15 → needs 0.80; we give 0.70
        d = decide_buy(_ctx(model_confidence=0.70, regime="bear"), config)
        self.assertEqual(d.action, "HOLD")
        self.assertIn("regime", d.reason.lower())

    def test_holds_in_high_vol_regime_when_below_adjusted_threshold(self):
        # high_vol adds 0.20 → needs 0.85; we give 0.75
        d = decide_buy(_ctx(model_confidence=0.75, regime="high_vol"), config)
        self.assertEqual(d.action, "HOLD")

    def test_passes_bull_regime_with_base_threshold(self):
        d = decide_buy(_ctx(model_confidence=0.65, regime="bull"), config)
        self.assertEqual(d.action, "BUY")

    def test_holds_when_portfolio_in_drawdown(self):
        # config.CNN_PAUSE_UPNL_DRAWDOWN_PCT = -0.02 default
        d = decide_buy(_ctx(portfolio_unpnl_frac=-0.05), config)
        self.assertEqual(d.action, "HOLD")
        self.assertIn("upnl", d.reason.lower())

    def test_passes_drawdown_gate_at_threshold(self):
        # Exactly at -0.02 → boundary; spec says ≤ blocks, so > passes
        d = decide_buy(_ctx(portfolio_unpnl_frac=-0.019), config)
        self.assertEqual(d.action, "BUY")

    def test_passes_drawdown_gate_when_no_positions(self):
        d = decide_buy(_ctx(portfolio_unpnl_frac=None), config)
        self.assertEqual(d.action, "BUY")

    def test_holds_when_in_trail_cooldown(self):
        d = decide_buy(_ctx(in_trail_cooldown=True), config)
        self.assertEqual(d.action, "HOLD")
        self.assertIn("cool", d.reason.lower())


class TestDecideBuySizing(unittest.TestCase):
    """Sizing chain — runs only when all 5 gates pass."""

    def test_kelly_sized_buy_with_full_corroborators(self):
        # kelly=0.10, value=$100k → $10k → 50 shares @ $200
        d = decide_buy(
            _ctx(kelly_fraction=0.10, portfolio_value=100000.0,
                 current_price=200.0,
                 n_corroborators=config.LONEWOLF_MIN_CORROBORATORS),
            config,
        )
        self.assertEqual(d.action, "BUY")
        self.assertEqual(d.shares, 50)

    def test_lonewolf_multiplier_applied_when_alone(self):
        # 0 corroborators → kelly × 0.5 → 0.05 → $5k → 25 shares
        d = decide_buy(
            _ctx(kelly_fraction=0.10, portfolio_value=100000.0,
                 current_price=200.0, n_corroborators=0),
            config,
        )
        self.assertEqual(d.action, "BUY")
        self.assertEqual(d.shares, 25)

    def test_max_position_size_clamps_huge_kelly(self):
        # MAX_POSITION_SIZE = 0.15 default → cap at $15k → 75 shares @ $200
        d = decide_buy(
            _ctx(kelly_fraction=0.50, portfolio_value=100000.0,
                 current_price=200.0,
                 n_corroborators=config.LONEWOLF_MIN_CORROBORATORS),
            config,
        )
        self.assertEqual(d.shares, int(0.15 * 100000.0 / 200.0))

    def test_floor_at_2pct_when_kelly_tiny(self):
        # kelly=0.005 → below floor → use 2% → $2k → 10 shares
        d = decide_buy(
            _ctx(kelly_fraction=0.005, portfolio_value=100000.0,
                 current_price=200.0,
                 n_corroborators=config.LONEWOLF_MIN_CORROBORATORS),
            config,
        )
        self.assertEqual(d.shares, 10)

    def test_holds_when_computed_shares_below_one(self):
        # Tiny portfolio + expensive stock → 0 shares → HOLD
        d = decide_buy(
            _ctx(kelly_fraction=0.02, portfolio_value=100.0,
                 current_price=200.0,
                 n_corroborators=config.LONEWOLF_MIN_CORROBORATORS),
            config,
        )
        self.assertEqual(d.action, "HOLD")
        self.assertIn("under-funded", d.reason.lower())

    def test_sized_confidence_shrinks_with_lonewolf(self):
        d = decide_buy(_ctx(model_confidence=0.80, n_corroborators=0), config)
        self.assertLess(d.sized_confidence, 0.80)

    def test_sized_confidence_unchanged_when_corroborated(self):
        d = decide_buy(
            _ctx(model_confidence=0.80,
                 n_corroborators=config.LONEWOLF_MIN_CORROBORATORS),
            config,
        )
        self.assertAlmostEqual(d.sized_confidence, 0.80)


class TestVolTargetSizing(unittest.TestCase):
    """H15 — vol-managed position sizing (Moreira-Muir). Scales base_pct by
    w = clip(VOL_TARGET_ANN_VOL / realized_vol, 0, VOL_TARGET_CAP) BEFORE the
    existing [2%, MAX_POSITION_SIZE] clamp. OFF by default (shadow-only):
    when disabled, realized_vol must NOT change sizing but the would-be
    multiplier is surfaced in the reason string for shadow-logging.

    Defaults asserted here: target=0.12, cap=2.0. Tests pin them so a changed
    .env doesn't silently break the math.
    """

    def _on(self, **cfg):
        pins = dict(VOL_TARGET_SIZING_ENABLED=True,
                    VOL_TARGET_ANN_VOL=0.12, VOL_TARGET_CAP=2.0)
        pins.update(cfg)
        return mock.patch.multiple(config, **pins)

    def _off(self):
        return mock.patch.multiple(
            config, VOL_TARGET_SIZING_ENABLED=False,
            VOL_TARGET_ANN_VOL=0.12, VOL_TARGET_CAP=2.0)

    def test_disabled_by_default_realized_vol_does_not_change_size(self):
        # Baseline: kelly 0.10, $100k, $200 -> 50 shares. High realized_vol
        # must NOT shrink it while the feature is OFF.
        with self._off():
            d = decide_buy(_ctx(kelly_fraction=0.10, portfolio_value=100000.0,
                                current_price=200.0, realized_vol=0.48), config)
        self.assertEqual(d.action, "BUY")
        self.assertEqual(d.shares, 50)

    def test_disabled_reason_reports_shadow_multiplier(self):
        # Shadow visibility: reason shows the would-be multiplier + "shadow".
        with self._off():
            d = decide_buy(_ctx(kelly_fraction=0.10, portfolio_value=100000.0,
                                current_price=200.0, realized_vol=0.48), config)
        self.assertIn("shadow", d.reason.lower())
        self.assertIn("0.25", d.reason)   # 0.12 / 0.48 = 0.25

    def test_enabled_high_vol_shrinks_size(self):
        # w = 0.12/0.48 = 0.25 -> base 0.10*0.25 = 0.025 -> $2.5k -> 12 shares
        with self._on():
            d = decide_buy(_ctx(kelly_fraction=0.10, portfolio_value=100000.0,
                                current_price=200.0, realized_vol=0.48), config)
        self.assertEqual(d.action, "BUY")
        self.assertEqual(d.shares, 12)

    def test_enabled_low_vol_levers_up_but_capped_at_2x(self):
        # w = 0.12/0.02 = 6 -> CAPPED at 2.0. kelly 0.03 -> 0.03*2 = 0.06 ->
        # $6k -> 30 shares. (Without the cap it would clamp to MAX 0.15 = 75.)
        with self._on():
            d = decide_buy(_ctx(kelly_fraction=0.03, portfolio_value=100000.0,
                                current_price=200.0, realized_vol=0.02), config)
        self.assertEqual(d.shares, 30)

    def test_enabled_none_realized_vol_is_noop(self):
        # Missing vol -> multiplier 1.0 -> unchanged 50 shares, no crash.
        with self._on():
            d = decide_buy(_ctx(kelly_fraction=0.10, portfolio_value=100000.0,
                                current_price=200.0, realized_vol=None), config)
        self.assertEqual(d.shares, 50)

    def test_enabled_zero_or_negative_vol_is_noop(self):
        with self._on():
            d = decide_buy(_ctx(kelly_fraction=0.10, portfolio_value=100000.0,
                                current_price=200.0, realized_vol=0.0), config)
        self.assertEqual(d.shares, 50)

    def test_enabled_still_respects_2pct_floor(self):
        # Extreme vol shrinks below the floor; sizing stays clamped to 2%.
        # w = 0.12/2.0 = 0.06 -> base 0.10*0.06 = 0.006 -> floored to 0.02 ->
        # $2k -> 10 shares.
        with self._on():
            d = decide_buy(_ctx(kelly_fraction=0.10, portfolio_value=100000.0,
                                current_price=200.0, realized_vol=2.0), config)
        self.assertEqual(d.shares, 10)

    def test_enabled_reason_reports_applied_multiplier(self):
        with self._on():
            d = decide_buy(_ctx(kelly_fraction=0.10, portfolio_value=100000.0,
                                current_price=200.0, realized_vol=0.48), config)
        self.assertIn("0.25", d.reason)
        self.assertNotIn("shadow", d.reason.lower())


if __name__ == "__main__":
    unittest.main()
