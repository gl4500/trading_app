"""
Historical Trends Agent: Analyzes seasonal calendar patterns, multi-period
momentum persistence, and long-term channel positioning to generate signals.

Three pillars:
  1. Seasonal bias  — month-of-year and quarter-position effects
  2. Channel analysis — price position within the historical high-low range
  3. Multi-period momentum — trend alignment across 5/10/20/40-day windows
"""
import logging
import math
from datetime import datetime
from typing import Dict, List, Tuple

import pandas as pd

from agents.base_agent import BaseAgent, Signal
from config import config

logger = logging.getLogger(__name__)


# Month-of-year seasonal bias scores (−1.0 to +1.0).
# Based on long-run S&P 500 seasonality research.
MONTHLY_SEASONAL_BIAS: Dict[int, float] = {
    1:  +0.40,  # January: January effect, fresh fund positioning
    2:  +0.10,  # February: mild positive after Jan surge
    3:  +0.10,  # March: end-of-Q1 window dressing
    4:  +0.20,  # April: historically strong, tax-refund buying
    5:  -0.20,  # May: "Sell in May" begins
    6:  -0.15,  # June: summer doldrums start
    7:  +0.05,  # July: mild mid-summer recovery
    8:  -0.15,  # August: low volume, elevated volatility
    9:  -0.30,  # September: historically the weakest month
    10: +0.10,  # October: post-Sept recovery, pre-holiday build-up
    11: +0.35,  # November: Q4 rally, pre-holiday buying
    12: +0.40,  # December: Santa Claus rally, year-end positioning
}


def _quarter_position_bias(today) -> float:
    """
    Returns a small bias based on where we are within the current quarter.
    Fund managers tend to window-dress near quarter-end.
    """
    month_in_quarter = ((today.month - 1) % 3) + 1  # 1, 2, or 3
    day = today.day

    if month_in_quarter == 3 and day >= 15:
        return +0.15   # last ~6 weeks of quarter: window dressing boosts prices
    elif month_in_quarter == 1 and day <= 15:
        return +0.10   # first two weeks of new quarter: fresh positioning
    return 0.0


class HistoricalTrendsAgent(BaseAgent):
    """
    Combines seasonal calendar patterns, long-term channel positioning,
    and multi-period momentum persistence into a single trading signal.
    """

    def __init__(self):
        super().__init__(
            name="HistoricalTrendsAgent",
            strategy_description=(
                "Seasonal patterns (month/quarter), multi-period momentum persistence, "
                "and long-term channel positioning"
            ),
        )
        self.min_bars = 30  # minimum bars required for meaningful analysis

    # ── Sub-analysis methods ──────────────────────────────────────────────────

    def _seasonal_score(self, today) -> Tuple[float, str]:
        """
        Compute a seasonal bias score for the current calendar date.
        Combines month-of-year effect (70%) and quarter-position effect (30%).
        Returns (score, reason_string) where score is in [-1, +1].
        """
        month_bias = MONTHLY_SEASONAL_BIAS.get(today.month, 0.0)
        quarter_bias = _quarter_position_bias(today)

        combined = month_bias * 0.70 + quarter_bias * 0.30
        combined = max(-1.0, min(1.0, combined))

        month_name = today.strftime("%B")
        bias_label = "bullish" if combined > 0.10 else ("bearish" if combined < -0.10 else "neutral")
        reason = f"{month_name} seasonal bias={combined:+.2f} ({bias_label})"
        return combined, reason

    def _channel_analysis(self, df: pd.DataFrame, current_price: float) -> Tuple[float, str]:
        """
        Assess where the current price sits within the historical high-low channel.
        Near the period low  → bullish (+1).
        Near the period high → bearish (−1).
        Adjusted for SMA-20 slope so a strong uptrend moderates the penalty for
        being near the high.
        Returns (score, reason_string) where score is in [-1, +1].
        """
        close = df["close"].astype(float)

        period_high = float(close.max())
        period_low  = float(close.min())
        channel_range = period_high - period_low

        if channel_range <= 0:
            return 0.0, "Channel range too narrow for analysis"

        # Position within channel: 0 = at low, 1 = at high
        position = (current_price - period_low) / channel_range

        # SMA-20 slope: normalised by price to get a % per bar
        sma_slope = 0.0
        if len(close) >= 30:
            sma20 = close.rolling(20).mean()
            sma_slope = (float(sma20.iloc[-1]) - float(sma20.iloc[-10])) / float(sma20.iloc[-10]) \
                if float(sma20.iloc[-10]) > 0 else 0.0

        # Raw signal: near bottom=+1, near top=−1
        raw = (0.5 - position) * 2.0

        # Trend adjustment: uptrend moderates bearish reading near highs
        adjusted = raw + sma_slope * 5.0
        score = max(-1.0, min(1.0, adjusted))

        n_days = len(close)
        desc = (
            "near period low" if position < 0.25 else
            "near period high" if position > 0.75 else
            "mid-channel"
        )
        reason = (
            f"{n_days}d channel: position={position:.0%}, {desc}, "
            f"SMA slope={sma_slope * 100:+.2f}%"
        )
        return score, reason

    def _multi_period_momentum(self, df: pd.DataFrame) -> Tuple[float, str]:
        """
        Measure trend persistence by comparing rate-of-change across
        5 / 10 / 20 / 40-day windows.  Full alignment adds an alignment bonus.
        Returns (score, reason_string) where score is in [-1, +1].
        """
        close = df["close"].astype(float)
        n = len(close)

        period_weights = [(5, 0.15), (10, 0.20), (20, 0.30), (40, 0.35)]
        readings: List[Tuple[int, float, float]] = []

        for period, weight in period_weights:
            if n > period:
                roc = (float(close.iloc[-1]) - float(close.iloc[-(period + 1)])) \
                      / float(close.iloc[-(period + 1)])
                readings.append((period, roc, weight))

        if not readings:
            return 0.0, "Insufficient data for multi-period momentum"

        total_w = sum(w for _, _, w in readings)
        weighted_roc = sum(roc * w for _, roc, w in readings) / total_w

        # Alignment bonus: reward when all timeframes agree
        positive = sum(1 for _, roc, _ in readings if roc > 0)
        alignment = positive / len(readings)  # 0 = all bearish, 1 = all bullish

        score = weighted_roc * 5.0  # scale to approx ±1
        if alignment > 0.75:
            score = min(1.0, score + 0.20)
        elif alignment < 0.25:
            score = max(-1.0, score - 0.20)

        score = max(-1.0, min(1.0, score))

        period_strs = [f"{p}d={roc * 100:+.1f}%" for p, roc, _ in readings]
        direction = "bullish" if score > 0.10 else ("bearish" if score < -0.10 else "flat")
        reason = (
            f"Multi-period momentum ({', '.join(period_strs)}): "
            f"{direction}, alignment={alignment:.0%}"
        )
        return score, reason

    def _long_term_volume_trend(self, df: pd.DataFrame) -> Tuple[float, str]:
        """
        Small confirmation signal: checks whether recent volume is heavier
        on up-days or down-days over the last 10 bars.
        Returns (score, reason_string) where |score| ≤ 0.15.
        """
        if "volume" not in df.columns or len(df) < 20:
            return 0.0, ""

        volume = df["volume"].astype(float)
        close  = df["close"].astype(float)
        returns = close.pct_change().dropna()

        recent_ret = returns.tail(10)
        recent_vol = volume.tail(len(recent_ret))

        up_mask   = recent_ret > 0
        down_mask = recent_ret < 0

        up_vol   = float(recent_vol[up_mask.values].mean())   if up_mask.any()   else 0.0
        down_vol = float(recent_vol[down_mask.values].mean()) if down_mask.any() else 0.0

        denom = up_vol + down_vol
        if denom == 0:
            return 0.0, ""

        vol_ratio = (up_vol - down_vol) / denom  # −1 to +1
        score = vol_ratio * 0.15                  # scale to small confirmation weight

        if abs(score) < 0.01:
            return 0.0, ""

        trend_desc = "more volume on up days" if vol_ratio > 0 else "more volume on down days"
        return score, f"Volume pattern: {trend_desc} (ratio={vol_ratio:+.2f})"

    # ── Signal generation ─────────────────────────────────────────────────────

    def _generate_signal(
        self,
        symbol: str,
        seasonal_score: float,
        channel_score: float,
        momentum_score: float,
        volume_score: float,
        reasons: List[str],
        prices: Dict[str, float],
        df: pd.DataFrame,
    ) -> Signal:
        """
        Combine sub-scores into a final BUY / SELL / HOLD signal.
        Weights: seasonal=20%, channel=30%, momentum=40%, volume=10%.
        BUY threshold:  composite > +0.25 (and no position)
        SELL threshold: composite < −0.25 (and has position)
        """
        current_price = prices.get(symbol, 0.0)
        if current_price <= 0 and df is not None and not df.empty:
            current_price = float(df["close"].iloc[-1])
        if current_price <= 0:
            return Signal(action="HOLD", symbol=symbol, confidence=0, shares=0,
                          reasoning="No price data available")

        composite = (
            seasonal_score  * 0.20 +
            channel_score   * 0.30 +
            momentum_score  * 0.40 +
            volume_score    * 0.10
        )

        confidence = min(0.95, max(0.05, abs(composite)))
        has_position = symbol in self.portfolio.positions
        all_reasons = " | ".join(r for r in reasons if r)

        if composite > 0.25 and not has_position:
            portfolio_value = self.portfolio.get_total_value(prices)
            target_alloc = portfolio_value * config.MAX_POSITION_SIZE * confidence
            target_alloc = min(target_alloc, self.portfolio.cash * 0.95)
            shares = math.floor(target_alloc / current_price * 100) / 100

            if shares < 0.01:
                return Signal(action="HOLD", symbol=symbol, confidence=confidence, shares=0,
                              reasoning=f"HIST TRENDS BUY signal but insufficient funds. {all_reasons}")

            return Signal(
                action="BUY",
                symbol=symbol,
                confidence=confidence,
                shares=shares,
                reasoning=f"HIST TRENDS BUY: composite={composite:+.2f} | {all_reasons}",
            )

        if composite < -0.25 and has_position:
            pos = self.portfolio.positions[symbol]
            return Signal(
                action="SELL",
                symbol=symbol,
                confidence=confidence,
                shares=pos.shares,
                reasoning=f"HIST TRENDS SELL: composite={composite:+.2f} | {all_reasons}",
            )

        direction = "bullish" if composite > 0.05 else ("bearish" if composite < -0.05 else "neutral")
        return Signal(
            action="HOLD",
            symbol=symbol,
            confidence=confidence,
            shares=0,
            reasoning=f"HIST TRENDS HOLD: composite={composite:+.2f} ({direction}) | {all_reasons}",
        )

    # ── Main entry point ──────────────────────────────────────────────────────

    async def analyze(self, market_context: Dict) -> List[Signal]:
        """Analyze all symbols using historical trend patterns."""
        signals = []
        today = datetime.now().date()
        prices = {
            s: ctx.get("price", 0)
            for s, ctx in market_context.items()
            if isinstance(ctx, dict)
        }

        for symbol, ctx in market_context.items():
            if not isinstance(ctx, dict):
                continue
            try:
                # Prefer long-term Stooq bars (up to 5 years) when available,
                # fall back to the standard 60-day Alpaca bars.
                lt_bars = ctx.get("long_term_bars")
                bars    = ctx.get("bars")

                if lt_bars is not None and not (hasattr(lt_bars, "empty") and lt_bars.empty) and len(lt_bars) >= self.min_bars:
                    analysis_bars = lt_bars
                    data_source   = f"Stooq {len(lt_bars)}d"
                elif bars is not None and not (hasattr(bars, "empty") and bars.empty) and len(bars) >= self.min_bars:
                    analysis_bars = bars
                    data_source   = f"Alpaca {len(bars)}d"
                else:
                    signals.append(Signal(
                        action="HOLD", symbol=symbol, confidence=0, shares=0,
                        reasoning=f"Insufficient historical data (need {self.min_bars}+ bars)",
                    ))
                    continue

                current_price = prices.get(symbol, 0.0)
                if current_price <= 0:
                    current_price = float(analysis_bars["close"].iloc[-1])

                seasonal_score,  seasonal_reason  = self._seasonal_score(today)
                channel_score,   channel_reason   = self._channel_analysis(analysis_bars, current_price)
                momentum_score,  momentum_reason  = self._multi_period_momentum(analysis_bars)
                volume_score,    volume_reason    = self._long_term_volume_trend(analysis_bars)
                _ = data_source  # used in reasoning below

                reasons = [f"[{data_source}]", seasonal_reason, channel_reason, momentum_reason]
                if volume_reason:
                    reasons.append(volume_reason)

                signal = self._generate_signal(
                    symbol,
                    seasonal_score, channel_score, momentum_score, volume_score,
                    reasons, prices, analysis_bars,
                )
                signals.append(signal)

            except Exception as e:
                logger.error(f"HistoricalTrendsAgent: Error analyzing {symbol}: {e}")
                signals.append(Signal(
                    action="HOLD", symbol=symbol, confidence=0, shares=0,
                    reasoning=f"Analysis error: {str(e)[:100]}",
                ))

        return signals
