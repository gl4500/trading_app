"""
Unit tests for data/macro_context.py
Covers: inter-market rules, regime classification, text formatting.
All tests are purely logic-based — no yfinance calls, no network I/O.
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))

from data.macro_context import _apply_intermarket_rules, _build_macro_text, SECTOR_ETFS


def _make_data(
    gold_5d=0.0, tlt_5d=0.0, usd_5d=0.0, oil_5d=0.0,
    vix=18.0, yield10y=4.5,
):
    """Build a minimal macro data dict for testing rules."""
    data = {
        "GLD":  {"price": 200.0, "1d": 0.0, "5d": gold_5d, "20d": gold_5d * 2},
        "TLT":  {"price": 90.0,  "1d": 0.0, "5d": tlt_5d,  "20d": tlt_5d  * 2},
        "UUP":  {"price": 28.0,  "1d": 0.0, "5d": usd_5d,  "20d": usd_5d  * 2},
        "USO":  {"price": 75.0,  "1d": 0.0, "5d": oil_5d,  "20d": oil_5d  * 2},
        "^VIX": {"price": vix,   "1d": 0.0, "5d": 0.0,     "20d": 0.0},
        "^TNX": {"price": yield10y, "1d": 0.0, "5d": 0.0,  "20d": 0.0},
    }
    for sym in SECTOR_ETFS:
        data[sym] = {"price": 100.0, "1d": 0.0, "5d": 0.0, "20d": 0.0}
    return data


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
        # Gold down, bonds down (yields rising), low VIX
        regime, signals, _ = _apply_intermarket_rules(
            {sym: d for sym, d in _make_data(gold_5d=-1.0, tlt_5d=-1.0).items()},
            vix_price=14.0, yield_10y=4.5,
        )
        self.assertIn("GROWTH", regime)

    def test_stagflation_signal(self):
        # Gold up + oil up + bonds down
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


class TestMacroTextFormatting(unittest.TestCase):

    def test_output_contains_regime(self):
        data = _make_data(gold_5d=3.0)
        text = _build_macro_text(data)
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


if __name__ == "__main__":
    unittest.main()
