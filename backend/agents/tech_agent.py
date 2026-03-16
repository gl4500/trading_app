"""
Technical Analysis Agent: Uses RSI, MACD, Bollinger Bands, and Volume analysis
to generate buy/sell signals.
"""
import logging
import math
from typing import Dict, List, Optional
import pandas as pd
import numpy as np

from agents.base_agent import BaseAgent, Signal
from config import config

logger = logging.getLogger(__name__)

try:
    import pandas_ta as ta
    HAS_PANDAS_TA = True
except ImportError:
    HAS_PANDAS_TA = False
    logger.warning("pandas-ta not available, using manual calculations")


def manual_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Calculate RSI manually as fallback."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def manual_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Calculate MACD manually."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def manual_bollinger(close: pd.Series, period: int = 20, std: float = 2.0):
    """Calculate Bollinger Bands manually."""
    sma = close.rolling(window=period).mean()
    std_dev = close.rolling(window=period).std()
    upper = sma + (std_dev * std)
    lower = sma - (std_dev * std)
    return upper, sma, lower


class TechAgent(BaseAgent):
    """Technical analysis agent using RSI, MACD, Bollinger Bands, and volume."""

    def __init__(self):
        super().__init__(
            name="TechAgent",
            strategy_description="Technical analysis: RSI, MACD, Bollinger Bands, Volume SMA",
        )
        self.rsi_period = config.RSI_PERIOD
        self.rsi_oversold = config.RSI_OVERSOLD
        self.rsi_overbought = config.RSI_OVERBOUGHT
        self.bb_period = config.BB_PERIOD
        self.bb_std = config.BB_STD
        self.macd_fast = config.MACD_FAST
        self.macd_slow = config.MACD_SLOW
        self.macd_signal = config.MACD_SIGNAL

    def _calculate_indicators(self, df: pd.DataFrame) -> Optional[pd.DataFrame]:
        """Calculate technical indicators for a price series."""
        if df is None or len(df) < max(self.rsi_period, self.bb_period, self.macd_slow) + 5:
            return None

        df = df.copy()

        try:
            if HAS_PANDAS_TA:
                df.ta.rsi(length=self.rsi_period, append=True)
                df.ta.macd(fast=self.macd_fast, slow=self.macd_slow,
                           signal=self.macd_signal, append=True)
                df.ta.bbands(length=self.bb_period, std=self.bb_std, append=True)

                rsi_col = f"RSI_{self.rsi_period}"
                macd_col = f"MACD_{self.macd_fast}_{self.macd_slow}_{self.macd_signal}"
                macd_sig_col = f"MACDs_{self.macd_fast}_{self.macd_slow}_{self.macd_signal}"
                macd_hist_col = f"MACDh_{self.macd_fast}_{self.macd_slow}_{self.macd_signal}"
                bb_upper_col = f"BBU_{self.bb_period}_{self.bb_std}"
                bb_mid_col = f"BBM_{self.bb_period}_{self.bb_std}"
                bb_lower_col = f"BBL_{self.bb_period}_{self.bb_std}"

                df["rsi"] = df.get(rsi_col, manual_rsi(df["close"], self.rsi_period))
                df["macd"] = df.get(macd_col, manual_macd(df["close"])[0])
                df["macd_signal"] = df.get(macd_sig_col, manual_macd(df["close"])[1])
                df["macd_hist"] = df.get(macd_hist_col, manual_macd(df["close"])[2])
                df["bb_upper"] = df.get(bb_upper_col, manual_bollinger(df["close"])[0])
                df["bb_mid"] = df.get(bb_mid_col, manual_bollinger(df["close"])[1])
                df["bb_lower"] = df.get(bb_lower_col, manual_bollinger(df["close"])[2])
            else:
                df["rsi"] = manual_rsi(df["close"], self.rsi_period)
                macd_line, signal_line, histogram = manual_macd(df["close"])
                df["macd"] = macd_line
                df["macd_signal"] = signal_line
                df["macd_hist"] = histogram
                bb_upper, bb_mid, bb_lower = manual_bollinger(df["close"])
                df["bb_upper"] = bb_upper
                df["bb_mid"] = bb_mid
                df["bb_lower"] = bb_lower

            # Volume SMA
            df["vol_sma"] = df["volume"].rolling(window=20).mean() if "volume" in df.columns else pd.Series(1, index=df.index)

            return df

        except Exception as e:
            logger.error(f"TechAgent: Error calculating indicators: {e}")
            return None

    def _generate_signal(self, symbol: str, df: pd.DataFrame, prices: Dict[str, float]) -> Signal:
        """Generate a trading signal for a symbol based on technical indicators."""
        current_price = prices.get(symbol, 0)
        if current_price <= 0:
            return Signal(action="HOLD", symbol=symbol, confidence=0, shares=0,
                          reasoning="No price data available")

        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest

        rsi = latest.get("rsi", 50)
        macd = latest.get("macd", 0)
        macd_sig = latest.get("macd_signal", 0)
        macd_hist = latest.get("macd_hist", 0)
        prev_macd_hist = prev.get("macd_hist", 0)
        bb_upper = latest.get("bb_upper", current_price * 1.02)
        bb_lower = latest.get("bb_lower", current_price * 0.98)
        bb_mid = latest.get("bb_mid", current_price)
        volume = latest.get("volume", 0)
        vol_sma = latest.get("vol_sma", volume)

        # Guard against NaN
        if any(math.isnan(v) if isinstance(v, float) else False
               for v in [rsi, macd, macd_sig, bb_upper, bb_lower]):
            return Signal(action="HOLD", symbol=symbol, confidence=0, shares=0,
                          reasoning="Insufficient data for indicators")

        # MACD crossover detection
        macd_bullish_cross = macd_hist > 0 and prev_macd_hist <= 0
        macd_bearish_cross = macd_hist < 0 and prev_macd_hist >= 0
        volume_spike = volume > vol_sma * 1.2 if vol_sma > 0 else False

        # Composite scoring for BUY
        buy_score = 0.0
        buy_reasons = []

        if rsi < self.rsi_oversold:
            buy_score += 0.35
            buy_reasons.append(f"RSI={rsi:.1f} (oversold)")

        if current_price <= bb_lower:
            buy_score += 0.30
            buy_reasons.append(f"Price at lower BB (${bb_lower:.2f})")

        if macd_bullish_cross or macd_hist > 0:
            weight = 0.25 if macd_bullish_cross else 0.10
            buy_score += weight
            buy_reasons.append(f"MACD {'bullish cross' if macd_bullish_cross else 'positive'}")

        if volume_spike:
            buy_score += 0.10
            buy_reasons.append(f"Volume spike ({volume/vol_sma:.1f}x avg)")

        # Composite scoring for SELL
        sell_score = 0.0
        sell_reasons = []

        if rsi > self.rsi_overbought:
            sell_score += 0.35
            sell_reasons.append(f"RSI={rsi:.1f} (overbought)")

        if current_price >= bb_upper:
            sell_score += 0.30
            sell_reasons.append(f"Price at upper BB (${bb_upper:.2f})")

        if macd_bearish_cross or macd_hist < 0:
            weight = 0.25 if macd_bearish_cross else 0.10
            sell_score += weight
            sell_reasons.append(f"MACD {'bearish cross' if macd_bearish_cross else 'negative'}")

        if volume_spike and sell_score > 0:
            sell_score += 0.10
            sell_reasons.append("Volume confirmation")

        # Check existing position for sell
        has_position = symbol in self.portfolio.positions

        # Decision
        if buy_score >= 0.55 and not has_position:
            # Calculate shares
            portfolio_value = self.portfolio.get_total_value(prices)
            target_allocation = portfolio_value * config.MAX_POSITION_SIZE * buy_score
            target_allocation = min(target_allocation, self.portfolio.cash * 0.95)
            shares = math.floor(target_allocation / current_price * 100) / 100

            if shares < 0.01:
                return Signal(action="HOLD", symbol=symbol, confidence=buy_score, shares=0,
                              reasoning=f"Insufficient funds. Score={buy_score:.2f}")

            return Signal(
                action="BUY",
                symbol=symbol,
                confidence=buy_score,
                shares=shares,
                reasoning=f"TECH BUY: {', '.join(buy_reasons)}. Score={buy_score:.2f}",
            )

        elif sell_score >= 0.55 and has_position:
            pos = self.portfolio.positions[symbol]
            shares = pos.shares  # sell entire position

            return Signal(
                action="SELL",
                symbol=symbol,
                confidence=sell_score,
                shares=shares,
                reasoning=f"TECH SELL: {', '.join(sell_reasons)}. Score={sell_score:.2f}",
            )

        # Hold
        best_score = max(buy_score, sell_score)
        context = f"RSI={rsi:.1f}, MACD={macd_hist:.3f}, BB_pos={(current_price-bb_lower)/(bb_upper-bb_lower):.2f}"
        return Signal(
            action="HOLD",
            symbol=symbol,
            confidence=best_score,
            shares=0,
            reasoning=f"TECH HOLD: No clear signal. {context}",
        )

    async def analyze(self, market_context: Dict) -> List[Signal]:
        """Analyze all watchlist symbols and return signals."""
        signals = []

        for symbol, ctx in market_context.items():
            try:
                bars = ctx.get("bars")
                prices = {s: c.get("price", 0) for s, c in market_context.items()}

                if bars is None or (hasattr(bars, "empty") and bars.empty):
                    signals.append(Signal(
                        action="HOLD", symbol=symbol, confidence=0, shares=0,
                        reasoning="No historical data available"
                    ))
                    continue

                df_with_indicators = self._calculate_indicators(bars)
                if df_with_indicators is None:
                    signals.append(Signal(
                        action="HOLD", symbol=symbol, confidence=0, shares=0,
                        reasoning="Insufficient data for indicators"
                    ))
                    continue

                signal = self._generate_signal(symbol, df_with_indicators, prices)
                signals.append(signal)

            except Exception as e:
                logger.error(f"TechAgent: Error analyzing {symbol}: {e}")
                signals.append(Signal(
                    action="HOLD", symbol=symbol, confidence=0, shares=0,
                    reasoning=f"Analysis error: {str(e)[:100]}"
                ))

        return signals
