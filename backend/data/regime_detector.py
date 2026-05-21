"""
HMM-Inspired Regime Detector — pure numpy, no hmmlearn required.

Classifies the market into 4 states using SPY 20-day momentum and realized
annualized volatility.  The approach mirrors the Man Group AHL regime layer
(documented Sharpe 1.9 in trending regimes) and similar work at Two Sigma.

States
------
  bull      — positive momentum (≥ +2 %), low/moderate volatility (< 20 %)
  neutral   — flat momentum, moderate volatility
  bear      — negative momentum (≤ −2 %), any volatility below threshold
  high_vol  — high volatility (≥ 20 % ann.) — dominates regardless of direction

The key insight: position sizing and confidence thresholds should adapt to the
regime so that aggressive sizing is reserved for periods of clear opportunity,
and defensive sizing kicks in during high-vol and bear markets.

EnsembleAgent mapping
---------------------
  bull     → "trending"   (momentum strategies dominate)
  neutral  → "ranging"    (mean reversion strategies dominate)
  bear     → "volatile"   (Claude + Sentiment weighted up; defensive)
  high_vol → "volatile"   (same as bear — protect capital)

XGBReasoningAgent buy-gate adjustments (applied in xgb_reasoning_agent.py)
---------------------------------------------------------------------------
  bull / neutral : +0.00  (no change to base confidence threshold)
  bear           : +0.15  (needs ≥ 0.65 confidence to trigger BUY)
  high_vol       : +0.20  (needs ≥ 0.70 confidence to trigger BUY)

Usage
-----
    from data.regime_detector import regime_detector

    # Called once per cycle after market data is refreshed
    spy_prices = [p["close"] for p in spy_bar_history]
    regime_detector.update(spy_prices)
    regime, confidence = regime_detector.get_regime()
"""
import logging
import math
from typing import List, Tuple

logger = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────

# Annualized realized volatility above this → high_vol state
_VOL_HIGH_THRESHOLD: float = 0.20       # 20 % annualized

# 20-day momentum thresholds
_MOMENTUM_BULL: float   =  0.02         # ≥ +2 % 20-day return → bull
_MOMENTUM_BEAR: float   = -0.02         # ≤ −2 % 20-day return → bear

# Minimum price history to produce a non-trivial classification
_MIN_PRICES: int = 21                   # 20 log-returns need 21 prices

# Confidence scaling denominators (return at which confidence reaches ~1.0)
_BULL_SCALE: float   = 0.05            # 5 % momentum → full bull confidence
_BEAR_SCALE: float   = 0.05            # 5 % drop     → full bear confidence
_VOL_SCALE:  float   = 0.10            # 10 pp above threshold → full vol confidence

# BUY-gate additions by regime (used by XGBReasoningAgent)
REGIME_CONFIDENCE_GATE: dict = {
    "bull":     0.00,
    "neutral":  0.00,
    "bear":     0.15,
    "high_vol": 0.20,
}


class RegimeDetector:
    """
    Lightweight HMM-inspired market regime classifier.

    Feed SPY (or any broad-market index) price history via ``update()``.
    Query the current state via ``get_regime()`` or ``get_ensemble_regime()``.
    """

    # Maps the 4 internal states to EnsembleAgent's 3 REGIME_MULTIPLIERS keys
    REGIME_TO_ENSEMBLE: dict = {
        "bull":     "trending",
        "neutral":  "ranging",
        "bear":     "volatile",
        "high_vol": "volatile",
    }

    def __init__(self) -> None:
        self._prices: List[float] = []
        self._regime: str         = "neutral"
        self._confidence: float   = 0.0

    # ── Public API ────────────────────────────────────────────────────────────

    def update(self, spy_prices: List[float]) -> None:
        """
        Refresh the detector with an updated SPY price series.

        Parameters
        ----------
        spy_prices : list[float]
            Closing prices for SPY, most-recent-last.  Zero / negative prices
            are filtered out automatically.
            At least 21 prices are required for a non-trivial result.
        """
        self._prices = [p for p in spy_prices if p and p > 0]
        self._regime, self._confidence = self._classify()

    def get_regime(self) -> Tuple[str, float]:
        """
        Return current regime and confidence score.

        Returns
        -------
        (regime, confidence) where
            regime     : "bull" | "neutral" | "bear" | "high_vol"
            confidence : float in [0.0, 1.0]
        """
        return self._regime, self._confidence

    def get_ensemble_regime(self) -> str:
        """
        Map the 4-state regime to the 3-state key expected by EnsembleAgent's
        REGIME_MULTIPLIERS dict ("trending" | "ranging" | "volatile").
        """
        return self.REGIME_TO_ENSEMBLE.get(self._regime, "ranging")

    def get_confidence_gate(self) -> float:
        """
        Return the additional confidence required for a BUY signal to fire
        in the current regime (used by XGBReasoningAgent).
        """
        return REGIME_CONFIDENCE_GATE.get(self._regime, 0.0)

    def summary(self) -> dict:
        """Serialize detector state for API responses / logging."""
        return {
            "regime":          self._regime,
            "confidence":      self._confidence,
            "ensemble_regime": self.get_ensemble_regime(),
            "n_prices":        len(self._prices),
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _classify(self) -> Tuple[str, float]:
        """
        Classify regime from the stored price history.

        Returns (state_string, confidence_float).
        Returns ("neutral", 0.0) when insufficient data.
        """
        if len(self._prices) < _MIN_PRICES:
            return "neutral", 0.0

        # Use the most recent 21 prices (20 log-returns)
        prices = self._prices[-_MIN_PRICES:]

        # ── 20-day momentum ───────────────────────────────────────────────────
        momentum = (prices[-1] / prices[0]) - 1.0

        # ── 20-day realized volatility (annualized) ───────────────────────────
        daily_rets: List[float] = []
        for i in range(1, len(prices)):
            if prices[i - 1] > 0:
                daily_rets.append(math.log(prices[i] / prices[i - 1]))

        if not daily_rets:
            return "neutral", 0.0

        mean_r = sum(daily_rets) / len(daily_rets)
        var_r  = sum((r - mean_r) ** 2 for r in daily_rets) / len(daily_rets)
        realized_vol = math.sqrt(var_r * 252)  # annualize with √252 trading days

        # ── Classification (order matters: high_vol checked first) ────────────

        if realized_vol >= _VOL_HIGH_THRESHOLD:
            excess   = realized_vol - _VOL_HIGH_THRESHOLD
            conf     = min(1.0, 0.50 + excess / _VOL_SCALE * 0.50)
            return "high_vol", round(conf, 3)

        if momentum >= _MOMENTUM_BULL:
            conf = min(1.0, 0.50 + momentum / _BULL_SCALE * 0.50)
            return "bull", round(conf, 3)

        if momentum <= _MOMENTUM_BEAR:
            conf = min(1.0, 0.50 + abs(momentum) / _BEAR_SCALE * 0.50)
            return "bear", round(conf, 3)

        # Neutral: momentum between thresholds, vol below high threshold
        # Confidence rises as momentum approaches zero (very flat)
        flatness = 1.0 - abs(momentum) / max(_MOMENTUM_BULL, abs(_MOMENTUM_BEAR))
        conf     = round(max(0.30, min(1.0, flatness)), 3)
        return "neutral", conf


# ── Module-level singleton ────────────────────────────────────────────────────

regime_detector = RegimeDetector()
