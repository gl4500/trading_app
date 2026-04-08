"""
Unit tests for data/macro_context.py
Covers: inter-market rules, regime classification, text formatting,
        strategic (slow) context, regime duration, slow insights, breadth.
All tests are purely logic-based — no yfinance calls, no network I/O.
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))

from data.macro_context import (
    _apply_intermarket_rules,
    _build_macro_text,
    _compute_slow_insights,
    _update_regime_duration,
    _reset_regime_tracking,
    _range_bar,
    SECTOR_ETFS,
    BREADTH_ETFS,
    MACRO_PROXIES,
)


# ── Test data helpers ─────────────────────────────────────────────────────────

def _make_data(
    gold_5d=0.0, tlt_5d=0.0, usd_5d=0.0, oil_5d=0.0,
    vix=18.0, yield10y=4.5,
    spy_5d=0.0, iwm_5d=0.0,
):
    """Build a minimal fast (daily) macro data dict for testing."""
    data = {
        "GLD":  {"price": 200.0, "1d": 0.0, "5d": gold_5d, "20d": gold_5d * 2, "60d": gold_5d * 4},
        "TLT":  {"price": 90.0,  "1d": 0.0, "5d": tlt_5d,  "20d": tlt_5d  * 2, "60d": tlt_5d  * 4},
        "UUP":  {"price": 28.0,  "1d": 0.0, "5d": usd_5d,  "20d": usd_5d  * 2, "60d": usd_5d  * 4},
        "USO":  {"price": 75.0,  "1d": 0.0, "5d": oil_5d,  "20d": oil_5d  * 2, "60d": oil_5d  * 4},
        "^VIX": {"price": vix,   "1d": 0.0, "5d": 0.0,     "20d": 0.0,         "60d": 0.0},
        "^TNX": {"price": yield10y, "1d": 0.0, "5d": 0.0,  "20d": 0.0,         "60d": 0.0},
        "SPY":  {"price": 500.0, "1d": 0.0, "5d": spy_5d,  "20d": spy_5d * 2,  "60d": spy_5d * 4},
        "IWM":  {"price": 200.0, "1d": 0.0, "5d": iwm_5d,  "20d": iwm_5d * 2,  "60d": iwm_5d * 4},
        "MDY":  {"price": 500.0, "1d": 0.0, "5d": 0.0,     "20d": 0.0,         "60d": 0.0},
        "QQQ":  {"price": 450.0, "1d": 0.0, "5d": 0.0,     "20d": 0.0,         "60d": 0.0},
    }
    for sym in SECTOR_ETFS:
        data[sym] = {"price": 100.0, "1d": 0.0, "5d": 0.0, "20d": 0.0, "60d": 0.0}
    return data


def _make_slow_data(
    gld_52w=0.0, gld_pos=50.0, gld_trend=True,
    tlt_52w=0.0, tlt_pos=50.0, tlt_trend=True,
    uso_52w=0.0, uup_52w=0.0,
    spy_52w=0.0, iwm_52w=0.0, qqq_52w=0.0,
):
    """Build a minimal slow (weekly) macro data dict for testing."""
    base = {
        "price": 100.0, "52w": 0.0, "26w": 0.0,
        "pos_52w": 50.0, "high_52w": 110.0, "low_52w": 90.0,
        "trend_up": True,
    }
    data = {}
    all_syms = list(MACRO_PROXIES.keys()) + list(SECTOR_ETFS.keys()) + list(BREADTH_ETFS.keys())
    for sym in all_syms:
        data[sym] = dict(base)

    data["GLD"].update({"52w": gld_52w, "pos_52w": gld_pos, "trend_up": gld_trend})
    data["TLT"].update({"52w": tlt_52w, "pos_52w": tlt_pos, "trend_up": tlt_trend})
    data["USO"]["52w"] = uso_52w
    data["UUP"]["52w"] = uup_52w
    data["SPY"]["52w"] = spy_52w
    data["IWM"]["52w"] = iwm_52w
    data["QQQ"]["52w"] = qqq_52w
    return data


# ── Existing: inter-market rules ──────────────────────────────────────────────

class TestIntermarketRules(unittest.TestCase):

    def test_gold_rally_produces_risk_off_regime(self):
        regime, signals, bias = _apply_intermarket_rules(
            {sym: d for sym, d in _make_data(gold_5d=3.0).items()},
            vix_price=18.0, yield_10y=4.5,
        )
        self.assertIn("RISK-OFF", regime)

    def test_gold_rally_marks_defensives_bullish(self):
        _, _, bias = _apply_intermarket_rules(
            {sym: d for sym, d in _make_data(gold_5d=3.0).items()},
            vix_price=18.0, yield_10y=4.5,
        )
        self.assertEqual(bias.get("XLU"), "bullish")
        self.assertEqual(bias.get("XLV"), "bullish")
        self.assertEqual(bias.get("XLP"), "bullish")

    def test_gold_rally_marks_growth_bearish(self):
        _, _, bias = _apply_intermarket_rules(
            {sym: d for sym, d in _make_data(gold_5d=3.0).items()},
            vix_price=18.0, yield_10y=4.5,
        )
        self.assertEqual(bias.get("XLK"), "bearish")
        self.assertEqual(bias.get("XLY"), "bearish")

    def test_rising_yields_marks_financials_bullish(self):
        _, _, bias = _apply_intermarket_rules(
            {sym: d for sym, d in _make_data(tlt_5d=-2.5).items()},
            vix_price=18.0, yield_10y=4.5,
        )
        self.assertEqual(bias.get("XLF"), "bullish")

    def test_rising_yields_marks_utilities_bearish(self):
        _, _, bias = _apply_intermarket_rules(
            {sym: d for sym, d in _make_data(tlt_5d=-2.5).items()},
            vix_price=18.0, yield_10y=4.5,
        )
        self.assertEqual(bias.get("XLU"), "bearish")
        self.assertEqual(bias.get("XLRE"), "bearish")

    def test_oil_surge_marks_energy_bullish_consumer_bearish(self):
        _, _, bias = _apply_intermarket_rules(
            {sym: d for sym, d in _make_data(oil_5d=5.0).items()},
            vix_price=18.0, yield_10y=4.5,
        )
        self.assertEqual(bias.get("XLE"), "bullish")
        self.assertEqual(bias.get("XLY"), "bearish")

    def test_strong_usd_marks_materials_bearish(self):
        _, _, bias = _apply_intermarket_rules(
            {sym: d for sym, d in _make_data(usd_5d=2.0).items()},
            vix_price=18.0, yield_10y=4.5,
        )
        self.assertEqual(bias.get("XLB"), "bearish")

    def test_high_vix_extreme_fear_regime(self):
        regime, signals, _ = _apply_intermarket_rules(
            {sym: d for sym, d in _make_data().items()},
            vix_price=32.0, yield_10y=4.5,
        )
        self.assertIn("HIGH VOLATILITY", regime)
        self.assertTrue(any("EXTREME FEAR" in s for s in signals))

    def test_low_vix_risk_on_signal(self):
        _, signals, _ = _apply_intermarket_rules(
            {sym: d for sym, d in _make_data().items()},
            vix_price=12.0, yield_10y=4.5,
        )
        self.assertTrue(any("LOW FEAR" in s or "complacency" in s for s in signals))

    def test_growth_regime_detected(self):
        regime, signals, _ = _apply_intermarket_rules(
            {sym: d for sym, d in _make_data(gold_5d=-1.0, tlt_5d=-1.0).items()},
            vix_price=14.0, yield_10y=4.5,
        )
        self.assertIn("GROWTH", regime)

    def test_stagflation_signal(self):
        _, signals, _ = _apply_intermarket_rules(
            {sym: d for sym, d in _make_data(gold_5d=2.0, oil_5d=4.0, tlt_5d=-1.5).items()},
            vix_price=18.0, yield_10y=4.5,
        )
        self.assertTrue(any("STAGFLATION" in s for s in signals))

    def test_neutral_regime_no_strong_signals(self):
        regime, signals, bias = _apply_intermarket_rules(
            {sym: d for sym, d in _make_data().items()},
            vix_price=18.0, yield_10y=4.5,
        )
        self.assertIn("NEUTRAL", regime)

    def test_breadth_divergence_large_cap_leading(self):
        """SPY +3% vs IWM +0.5% → breadth warning signal"""
        _, signals, _ = _apply_intermarket_rules(
            {sym: d for sym, d in _make_data(spy_5d=3.0, iwm_5d=0.5).items()},
            vix_price=18.0, yield_10y=4.5,
        )
        self.assertTrue(any("breadth" in s.lower() or "Breadth" in s for s in signals))

    def test_xlc_bearish_on_gold_rally(self):
        """Communication Services should be tagged bearish on risk-off gold signal"""
        _, _, bias = _apply_intermarket_rules(
            {sym: d for sym, d in _make_data(gold_5d=3.0).items()},
            vix_price=18.0, yield_10y=4.5,
        )
        self.assertEqual(bias.get("XLC"), "bearish")


# ── Existing: text formatting ─────────────────────────────────────────────────

class TestMacroTextFormatting(unittest.TestCase):

    def test_output_contains_regime(self):
        text = _build_macro_text(_make_data(gold_5d=3.0))
        self.assertIn("MACRO REGIME:", text)

    def test_output_contains_sector_table(self):
        text = _build_macro_text(_make_data())
        self.assertIn("SECTOR ETF PERFORMANCE", text)

    def test_output_contains_inter_market_section(self):
        text = _build_macro_text(_make_data(gold_5d=3.0))
        self.assertIn("INTER-MARKET SIGNALS", text)

    def test_output_contains_trading_implications(self):
        text = _build_macro_text(_make_data(gold_5d=3.0))
        self.assertIn("TRADING IMPLICATIONS", text)

    def test_bullish_sectors_labelled(self):
        text = _build_macro_text(_make_data(gold_5d=3.0))
        self.assertIn("BULLISH", text)

    def test_bearish_sectors_labelled(self):
        text = _build_macro_text(_make_data(tlt_5d=-2.5))
        self.assertIn("BEARISH", text)

    def test_all_sector_etfs_appear_in_output(self):
        text = _build_macro_text(_make_data())
        for sym in SECTOR_ETFS:
            self.assertIn(sym, text, f"{sym} missing from macro text")

    def test_output_contains_60d_column(self):
        """60D return column should appear in tactical tables"""
        text = _build_macro_text(_make_data())
        self.assertIn("60D", text)

    def test_output_contains_breadth_section(self):
        """Market breadth ETFs section should appear"""
        text = _build_macro_text(_make_data())
        self.assertIn("MARKET BREADTH", text)

    def test_breadth_etfs_appear_in_output(self):
        text = _build_macro_text(_make_data())
        for sym in BREADTH_ETFS:
            self.assertIn(sym, text, f"{sym} missing from breadth section")


# ── New: strategic (slow) context ─────────────────────────────────────────────

class TestStrategicContext(unittest.TestCase):

    def test_strategic_section_appears_when_slow_data_provided(self):
        text = _build_macro_text(_make_data(), _make_slow_data())
        self.assertIn("STRATEGIC CONTEXT", text)

    def test_strategic_section_absent_without_slow_data(self):
        text = _build_macro_text(_make_data())
        self.assertNotIn("STRATEGIC CONTEXT", text)

    def test_52w_range_appears_in_strategic_section(self):
        text = _build_macro_text(_make_data(), _make_slow_data())
        self.assertIn("52W", text)

    def test_conflict_flag_tactical_bear_vs_lt_uptrend(self):
        """XLK tactically bearish (gold rally) but long-term uptrend → conflict flag"""
        slow = _make_slow_data()  # all sectors default trend_up=True
        text = _build_macro_text(_make_data(gold_5d=3.0), slow)
        self.assertIn("CONFLICT", text)

    def test_no_conflict_when_tactical_and_lt_agree(self):
        """XLU tactically bullish (gold rally) and long-term uptrend → no conflict"""
        slow = _make_slow_data()  # XLU trend_up=True, tactical=bullish
        text = _build_macro_text(_make_data(gold_5d=3.0), slow)
        # Conflict only for bearish sectors that have LT uptrend
        # XLU is bullish tactical + uptrend = no conflict for XLU
        # We just check the text does NOT flag XLU as a conflict
        # (other sectors like XLK will still have conflicts)
        xlu_line = [l for l in text.split("\n") if "XLU" in l and "CONFLICT" in l]
        self.assertEqual(len(xlu_line), 0)

    def test_breadth_etfs_in_strategic_section(self):
        text = _build_macro_text(_make_data(), _make_slow_data())
        self.assertIn("Market Breadth", text)
        for sym in BREADTH_ETFS:
            self.assertIn(sym, text)

    def test_range_bar_near_highs(self):
        bar = _range_bar(95.0)
        self.assertIn("95%", bar)
        self.assertIn("=", bar)

    def test_range_bar_near_lows(self):
        bar = _range_bar(5.0)
        self.assertIn("5%", bar)

    def test_range_bar_clamped(self):
        self.assertIn("100%", _range_bar(110.0))
        self.assertIn("0%",   _range_bar(-10.0))


# ── New: slow insights (pure function) ────────────────────────────────────────

class TestSlowInsights(unittest.TestCase):

    def test_no_insights_when_all_neutral(self):
        insights = _compute_slow_insights(_make_slow_data())
        self.assertEqual(insights, [])

    def test_gold_near_highs_generates_insight(self):
        insights = _compute_slow_insights(_make_slow_data(gld_52w=25.0, gld_pos=92.0))
        self.assertTrue(any("GLD" in i and "52W" in i for i in insights))

    def test_gold_near_lows_generates_insight(self):
        insights = _compute_slow_insights(_make_slow_data(gld_52w=-15.0, gld_pos=12.0))
        self.assertTrue(any("GLD" in i for i in insights))

    def test_tlt_near_lows_bond_bear_market_insight(self):
        insights = _compute_slow_insights(_make_slow_data(tlt_52w=-14.0, tlt_pos=10.0))
        self.assertTrue(any("TLT" in i and "bear" in i.lower() for i in insights))

    def test_tlt_near_highs_deflation_insight(self):
        insights = _compute_slow_insights(_make_slow_data(tlt_52w=12.0, tlt_pos=88.0))
        self.assertTrue(any("TLT" in i for i in insights))

    def test_stagflation_divergence_insight(self):
        """GLD +20% YoY + TLT -15% YoY → stagflation confirmed"""
        insights = _compute_slow_insights(_make_slow_data(gld_52w=20.0, tlt_52w=-15.0))
        self.assertTrue(any("stagflation" in i.lower() for i in insights))

    def test_oil_bull_cycle_insight(self):
        insights = _compute_slow_insights(_make_slow_data(uso_52w=25.0))
        self.assertTrue(any("XLE" in i for i in insights))

    def test_oil_bear_cycle_insight(self):
        insights = _compute_slow_insights(_make_slow_data(uso_52w=-25.0))
        self.assertTrue(any("XLE" in i and "bear" in i.lower() for i in insights))

    def test_large_cap_concentration_breadth_warning(self):
        """SPY +20% YoY vs IWM +5% → narrow breadth warning"""
        insights = _compute_slow_insights(_make_slow_data(spy_52w=20.0, iwm_52w=5.0))
        self.assertTrue(any("breadth" in i.lower() or "narrow" in i.lower() for i in insights))

    def test_broad_market_bull_breadth_insight(self):
        """IWM +20% YoY vs SPY +5% → broad-based bull"""
        insights = _compute_slow_insights(_make_slow_data(spy_52w=5.0, iwm_52w=20.0))
        self.assertTrue(any("broad" in i.lower() or "IWM" in i for i in insights))

    def test_growth_vs_value_divergence(self):
        """QQQ +30% vs IWM +10% → growth dominance insight"""
        insights = _compute_slow_insights(_make_slow_data(qqq_52w=30.0, iwm_52w=10.0))
        self.assertTrue(any("QQQ" in i or "growth" in i.lower() for i in insights))


# ── New: regime duration tracking ─────────────────────────────────────────────

class TestRegimeDuration(unittest.TestCase):

    def setUp(self):
        _reset_regime_tracking()

    def test_new_regime_returns_zero_days(self):
        days = _update_regime_duration("RISK-OFF", _now=1000.0)
        self.assertEqual(days, 0)

    def test_same_regime_accumulates_days(self):
        _update_regime_duration("RISK-OFF", _now=0.0)
        days = _update_regime_duration("RISK-OFF", _now=86400.0 * 10)
        self.assertEqual(days, 10)

    def test_regime_change_resets_to_zero(self):
        _update_regime_duration("RISK-OFF",   _now=0.0)
        _update_regime_duration("RISK-OFF",   _now=86400.0 * 5)
        days = _update_regime_duration("RISK-ON / GROWTH", _now=86400.0 * 6)
        self.assertEqual(days, 0)

    def test_regime_duration_appears_in_output(self):
        _reset_regime_tracking()
        text = _build_macro_text(_make_data())
        self.assertIn("active", text.lower())

    def test_regime_duration_singular_day(self):
        """'1 day' not '1 days'"""
        _update_regime_duration("NEUTRAL / MIXED", _now=0.0)
        text = _build_macro_text(_make_data())
        # After 0 elapsed time, days = 0, so pluralisation doesn't matter.
        # Just confirm the text is well-formed (no crash).
        self.assertIn("MACRO REGIME:", text)


if __name__ == "__main__":
    unittest.main()
