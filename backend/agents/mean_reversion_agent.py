"""
Mean Reversion Agent: Uses z-score of price vs rolling mean to trade.
Buys when oversold (z < -1.5), sells when overbought (z > 1.5).
"""
import logging
import math
from typing import Dict, List, Optional
import pandas as pd
import numpy as np

from agents.base_agent import BaseAgent, Signal
from config import config

logger = logging.getLogger(__name__)


class MeanReversionAgent(BaseAgent):
    """Mean reversion agent using z-score analysis."""

    def __init__(self):
        super().__init__(
            name="MeanReversionAgent",
            strategy_description="Mean reversion with z-score (buy oversold, sell overbought)",
        )
        self.period = config.MR_PERIOD         # 20-day rolling window
        self.buy_z = config.MR_BUY_ZSCORE     # -1.5
        self.sell_z = config.MR_SELL_ZSCORE   # +1.5

    def _calculate_zscore(self, df: pd.DataFrame) -> Optional[Dict]:
        """Calculate z-score and related statistics."""
        if df is None or len(df) < self.period + 5:
            return None

        close = df["close"].copy()

        # Rolling z-score
        rolling_mean = close.rolling(window=self.period).mean()
        rolling_std = close.rolling(window=self.period).std()

        latest_close = float(close.iloc[-1])
        latest_mean = float(rolling_mean.iloc[-1])
        latest_std = float(rolling_std.iloc[-1])

        if latest_std == 0 or math.isnan(latest_std):
            return None

        z_score = (latest_close - latest_mean) / latest_std

        # Trend of z-score (is it reverting?)
        recent_z = []
        for i in range(-5, 0):
            if abs(i) < len(close):
                if float(rolling_std.iloc[i]) == 0:
                    continue
                z = (float(close.iloc[i]) - float(rolling_mean.iloc[i])) / float(rolling_std.iloc[i])
                if not math.isnan(z):
                    recent_z.append(z)

        z_trend = 0.0
        if len(recent_z) >= 2:
            z_trend = recent_z[-1] - recent_z[0]  # direction of z-score change

        # Half-life of mean reversion (Ornstein-Uhlenbeck style)
        # Simpler: look at how often price crosses mean
        above_mean = (close > rolling_mean).astype(int)
        crossings = (above_mean.diff().abs()).sum()
        reversion_frequency = float(crossings / len(close)) if len(close) > 0 else 0

        # Bollinger band position (normalized 0-1)
        bb_upper = rolling_mean + (rolling_std * 2)
        bb_lower = rolling_mean - (rolling_std * 2)
        bb_range = float(bb_upper.iloc[-1]) - float(bb_lower.iloc[-1])
        bb_position = (latest_close - float(bb_lower.iloc[-1])) / bb_range if bb_range > 0 else 0.5

        # ATR for volatility
        if all(col in df.columns for col in ["high", "low", "close"]):
            high_low = df["high"] - df["low"]
            high_close = abs(df["high"] - df["close"].shift())
            low_close = abs(df["low"] - df["close"].shift())
            tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            atr = float(tr.rolling(14).mean().iloc[-1])
            atr_pct = atr / latest_close if latest_close > 0 else 0
        else:
            atr_pct = float(rolling_std.iloc[-1]) / latest_close if latest_close > 0 else 0

        return {
            "z_score": float(z_score),
            "rolling_mean": latest_mean,
            "rolling_std": latest_std,
            "current_price": latest_close,
            "z_trend": z_trend,
            "reversion_frequency": reversion_frequency,
            "bb_position": bb_position,
            "atr_pct": atr_pct,
            "recent_z_scores": recent_z,
        }

    def _generate_signal(self, symbol: str, stats: Dict, prices: Dict[str, float]) -> Signal:
        """Generate mean reversion signal based on z-score."""
        current_price = prices.get(symbol, stats.get("current_price", 0))
        if current_price <= 0:
            return Signal(action="HOLD", symbol=symbol, confidence=0, shares=0,
                          reasoning="No price data")

        z = stats["z_score"]
        z_trend = stats["z_trend"]
        mean_price = stats["rolling_mean"]
        reversion_freq = stats["reversion_frequency"]
        atr_pct = stats["atr_pct"]
        has_position = symbol in self.portfolio.positions

        # BUY: price is significantly below mean (oversold)
        if z <= self.buy_z and not has_position:
            # Confidence based on z-score magnitude
            confidence = min(0.95, abs(z) / 3.0)

            # Is z-score trending back toward mean (good timing)?
            if z_trend > 0:
                confidence = min(0.95, confidence + 0.10)
                timing = "already reverting"
            else:
                timing = "not yet reverting"

            # Position size proportional to z-score magnitude
            portfolio_value = self.portfolio.get_total_value(prices)
            z_factor = min(1.0, abs(z) / 3.0)  # scale by z magnitude, max at z=-3
            target_alloc = portfolio_value * config.MAX_POSITION_SIZE * z_factor
            target_alloc = min(target_alloc, self.portfolio.cash * 0.95)
            shares = math.floor(target_alloc / current_price * 100) / 100

            if shares < 0.01:
                return Signal(action="HOLD", symbol=symbol, confidence=confidence, shares=0,
                              reasoning=f"Z={z:.2f} (oversold) but insufficient funds")

            return Signal(
                action="BUY",
                symbol=symbol,
                confidence=confidence,
                shares=shares,
                reasoning=(
                    f"MR BUY: z={z:.2f} (oversold, target z=0). "
                    f"Price ${current_price:.2f} vs mean ${mean_price:.2f} "
                    f"({(current_price/mean_price-1)*100:.1f}%). {timing}. "
                    f"Reversion freq={reversion_freq:.2f}"
                ),
            )

        # SELL: price is significantly above mean (overbought)
        elif z >= self.sell_z and has_position:
            pos = self.portfolio.positions[symbol]
            confidence = min(0.95, abs(z) / 3.0)

            if z_trend < 0:
                confidence = min(0.95, confidence + 0.10)
                timing = "already reverting"
            else:
                timing = "not yet reverting"

            return Signal(
                action="SELL",
                symbol=symbol,
                confidence=confidence,
                shares=pos.shares,
                reasoning=(
                    f"MR SELL: z={z:.2f} (overbought, target z=0). "
                    f"Price ${current_price:.2f} vs mean ${mean_price:.2f} "
                    f"({(current_price/mean_price-1)*100:.1f}%). {timing}."
                ),
            )

        # SELL to exit: z has returned to near mean (take profit on long position)
        elif has_position and -0.3 <= z <= 0.5:
            pos = self.portfolio.positions[symbol]
            avg_cost = pos.avg_cost
            pnl_pct = (current_price - avg_cost) / avg_cost

            # Only take profit if we have a decent gain
            if pnl_pct > 0.01:  # 1% gain
                return Signal(
                    action="SELL",
                    symbol=symbol,
                    confidence=0.70,
                    shares=pos.shares,
                    reasoning=(
                        f"MR PROFIT TAKE: z={z:.2f} (mean reversion complete). "
                        f"PnL={pnl_pct*100:.1f}% from ${avg_cost:.2f} to ${current_price:.2f}"
                    ),
                )

        return Signal(
            action="HOLD",
            symbol=symbol,
            confidence=0.5,
            shares=0,
            reasoning=(
                f"MR HOLD: z={z:.2f} (buy<{self.buy_z}, sell>{self.sell_z}). "
                f"Price ${current_price:.2f}, mean ${mean_price:.2f}, ATR={atr_pct*100:.1f}%"
            ),
        )

    async def analyze(self, market_context: Dict) -> List[Signal]:
        """Analyze all symbols using mean reversion."""
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

                stats = self._calculate_zscore(bars)
                if stats is None:
                    signals.append(Signal(
                        action="HOLD", symbol=symbol, confidence=0, shares=0,
                        reasoning="Insufficient data for z-score calculation"
                    ))
                    continue

                signal = self._generate_signal(symbol, stats, prices)
                signals.append(signal)

            except Exception as e:
                logger.error(f"MeanReversionAgent: Error analyzing {symbol}: {e}")
                signals.append(Signal(
                    action="HOLD", symbol=symbol, confidence=0, shares=0,
                    reasoning=f"Analysis error: {str(e)[:100]}"
                ))

        return signals
