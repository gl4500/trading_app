"""
Momentum Agent: Price momentum and trend following with trailing stops.
"""
import logging
import math
from typing import Dict, List, Optional
import pandas as pd

from agents.base_agent import BaseAgent, Signal
from config import config

logger = logging.getLogger(__name__)


class MomentumAgent(BaseAgent):
    """Momentum-based trading agent with volume-weighted momentum and trailing stops."""

    def __init__(self):
        super().__init__(
            name="MomentumAgent",
            strategy_description="Price momentum & trend following with trailing stops",
        )
        self.short_period = config.MOMENTUM_SHORT      # 5 days
        self.mid_period = config.MOMENTUM_MID          # 10 days
        self.long_period = config.MOMENTUM_LONG        # 20 days
        self.momentum_threshold = config.MOMENTUM_THRESHOLD  # 2%
        self.trailing_stop = config.TRAILING_STOP      # 3%

        # Track highest prices for trailing stop
        self._high_water_marks: Dict[str, float] = {}

    def _calculate_momentum(self, df: pd.DataFrame) -> Optional[Dict]:
        """Calculate momentum indicators from price data."""
        if df is None or len(df) < self.long_period + 5:
            return None

        close = df["close"]
        volume = df["volume"] if "volume" in df.columns else pd.Series(1, index=df.index)

        # Rate of change (momentum) for different periods
        mom_short = float(close.pct_change(self.short_period).iloc[-1]) if len(close) > self.short_period else 0
        mom_mid = float(close.pct_change(self.mid_period).iloc[-1]) if len(close) > self.mid_period else 0
        mom_long = float(close.pct_change(self.long_period).iloc[-1]) if len(close) > self.long_period else 0

        # Volume-weighted momentum: average volume-weighted price change
        vol_weights = volume / volume.sum() if volume.sum() > 0 else pd.Series(1/len(volume), index=volume.index)
        recent_returns = close.pct_change().tail(self.short_period)
        recent_vols = vol_weights.tail(self.short_period)
        vw_momentum = float((recent_returns * recent_vols).sum()) if len(recent_returns) > 0 else 0

        # Trend consistency: how many of the last N days were positive
        daily_returns = close.pct_change().tail(self.long_period).dropna()
        trend_consistency = float((daily_returns > 0).mean()) if len(daily_returns) > 0 else 0.5

        # Acceleration: is momentum increasing?
        if len(close) > self.mid_period + self.short_period:
            prev_mom_short = float(close.iloc[-(self.short_period+1):-(1)].pct_change(self.short_period).iloc[-1])
        else:
            prev_mom_short = mom_short
        momentum_acceleration = mom_short - prev_mom_short

        # Average volume ratio (recent vs historical)
        avg_vol_recent = float(volume.tail(5).mean())
        avg_vol_hist = float(volume.mean())
        volume_ratio = avg_vol_recent / avg_vol_hist if avg_vol_hist > 0 else 1.0

        # Moving average trend
        sma_short = float(close.rolling(self.short_period).mean().iloc[-1])
        sma_long = float(close.rolling(self.long_period).mean().iloc[-1])
        ma_trend = (sma_short - sma_long) / sma_long if sma_long > 0 else 0

        return {
            "mom_short": mom_short,
            "mom_mid": mom_mid,
            "mom_long": mom_long,
            "vw_momentum": vw_momentum,
            "trend_consistency": trend_consistency,
            "momentum_acceleration": momentum_acceleration,
            "volume_ratio": volume_ratio,
            "ma_trend": ma_trend,
            "current_price": float(close.iloc[-1]),
        }

    def _check_trailing_stop(self, symbol: str, current_price: float) -> bool:
        """Check if trailing stop is triggered. Returns True if stop triggered."""
        if symbol not in self.portfolio.positions:
            return False

        # Update high water mark
        if symbol not in self._high_water_marks or current_price > self._high_water_marks[symbol]:
            self._high_water_marks[symbol] = current_price
            return False

        high_water = self._high_water_marks[symbol]
        drawdown = (high_water - current_price) / high_water

        if drawdown > self.trailing_stop:
            logger.info(f"MomentumAgent: Trailing stop triggered for {symbol} "
                       f"(fell {drawdown*100:.1f}% from ${high_water:.2f})")
            return True

        return False

    def _generate_signal(self, symbol: str, indicators: Dict, prices: Dict[str, float]) -> Signal:
        """Generate momentum-based trading signal."""
        current_price = prices.get(symbol, indicators.get("current_price", 0))
        if current_price <= 0:
            return Signal(action="HOLD", symbol=symbol, confidence=0, shares=0,
                          reasoning="No price data")

        mom_short = indicators["mom_short"]
        mom_mid = indicators["mom_mid"]
        mom_long = indicators["mom_long"]
        vw_momentum = indicators["vw_momentum"]
        trend_consistency = indicators["trend_consistency"]
        acceleration = indicators["momentum_acceleration"]
        volume_ratio = indicators["volume_ratio"]
        ma_trend = indicators["ma_trend"]

        has_position = symbol in self.portfolio.positions

        # Check trailing stop first (for existing positions)
        if has_position and self._check_trailing_stop(symbol, current_price):
            pos = self.portfolio.positions[symbol]
            return Signal(
                action="SELL",
                symbol=symbol,
                confidence=0.90,
                shares=pos.shares,
                reasoning=(f"MOMENTUM TRAILING STOP: Price fell from ${self._high_water_marks.get(symbol, current_price):.2f} "
                           f"to ${current_price:.2f} ({(1-current_price/self._high_water_marks.get(symbol, current_price))*100:.1f}% drop)"),
            )

        # Compute composite momentum score
        buy_score = 0.0
        buy_reasons = []

        # Short-term momentum (highest weight for momentum strategy)
        if mom_short > self.momentum_threshold:
            weight = min(0.30, mom_short * 5)
            buy_score += weight
            buy_reasons.append(f"5d momentum={mom_short*100:.1f}%")

        if mom_mid > self.momentum_threshold * 0.5:
            weight = min(0.25, mom_mid * 3)
            buy_score += weight
            buy_reasons.append(f"10d momentum={mom_mid*100:.1f}%")

        if mom_long > 0:
            weight = min(0.15, mom_long * 2)
            buy_score += weight
            buy_reasons.append(f"20d momentum={mom_long*100:.1f}%")

        if trend_consistency > 0.6:
            buy_score += 0.15
            buy_reasons.append(f"Trend consistency={trend_consistency*100:.0f}%")

        if acceleration > 0 and mom_short > 0:
            buy_score += 0.10
            buy_reasons.append("Accelerating momentum")

        if volume_ratio > 1.2:
            buy_score += 0.05
            buy_reasons.append(f"High volume ({volume_ratio:.1f}x)")

        # Sell conditions
        sell_score = 0.0
        sell_reasons = []

        if mom_short < -self.momentum_threshold:
            sell_score += min(0.40, abs(mom_short) * 5)
            sell_reasons.append(f"5d momentum={mom_short*100:.1f}%")

        if mom_mid < -self.momentum_threshold * 0.5:
            sell_score += min(0.30, abs(mom_mid) * 3)
            sell_reasons.append(f"10d momentum reversal")

        if acceleration < -0.01 and has_position:
            sell_score += 0.15
            sell_reasons.append("Decelerating momentum")

        if trend_consistency < 0.4 and has_position:
            sell_score += 0.15
            sell_reasons.append(f"Weak trend consistency={trend_consistency*100:.0f}%")

        # Decision
        portfolio_value = self.portfolio.get_total_value(prices)

        if buy_score >= 0.30 and not has_position and vw_momentum > 0:
            # Position size: confidence * max position size
            target_alloc = portfolio_value * config.MAX_POSITION_SIZE * buy_score
            target_alloc = min(target_alloc, self.portfolio.cash * 0.95)
            shares = math.floor(target_alloc / current_price * 100) / 100

            if shares < 0.01:
                return Signal(action="HOLD", symbol=symbol, confidence=buy_score, shares=0,
                              reasoning=f"Insufficient funds for momentum entry")

            # Update high water mark
            self._high_water_marks[symbol] = current_price

            return Signal(
                action="BUY",
                symbol=symbol,
                confidence=buy_score,
                shares=shares,
                reasoning=f"MOMENTUM BUY: {', '.join(buy_reasons)}. Score={buy_score:.2f}",
            )

        elif (sell_score >= 0.30 or mom_short < -self.momentum_threshold) and has_position:
            pos = self.portfolio.positions[symbol]
            # Clear high water mark
            self._high_water_marks.pop(symbol, None)

            return Signal(
                action="SELL",
                symbol=symbol,
                confidence=sell_score,
                shares=pos.shares,
                reasoning=f"MOMENTUM SELL: {', '.join(sell_reasons)}. Score={sell_score:.2f}",
            )

        context = f"mom5d={mom_short*100:.1f}%, mom10d={mom_mid*100:.1f}%, trend={trend_consistency*100:.0f}%"
        return Signal(
            action="HOLD",
            symbol=symbol,
            confidence=max(buy_score, sell_score),
            shares=0,
            reasoning=f"MOMENTUM HOLD: {context}",
        )

    async def analyze(self, market_context: Dict) -> List[Signal]:
        """Analyze all symbols and return momentum signals."""
        signals = []
        prices = {s: ctx.get("price", 0) for s, ctx in market_context.items() if isinstance(ctx, dict)}

        for symbol, ctx in market_context.items():
            if not isinstance(ctx, dict):
                continue
            try:
                bars = ctx.get("bars")

                if bars is None or (hasattr(bars, "empty") and bars.empty):
                    signals.append(Signal(
                        action="HOLD", symbol=symbol, confidence=0, shares=0,
                        reasoning="No historical data available"
                    ))
                    continue

                indicators = self._calculate_momentum(bars)
                if indicators is None:
                    signals.append(Signal(
                        action="HOLD", symbol=symbol, confidence=0, shares=0,
                        reasoning="Insufficient data for momentum calculation"
                    ))
                    continue

                signal = self._generate_signal(symbol, indicators, prices)
                signals.append(signal)

            except Exception as e:
                logger.error(f"MomentumAgent: Error analyzing {symbol}: {e}")
                signals.append(Signal(
                    action="HOLD", symbol=symbol, confidence=0, shares=0,
                    reasoning=f"Analysis error: {str(e)[:100]}"
                ))

        return signals
