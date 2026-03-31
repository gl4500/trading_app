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


def manual_stoch(df: pd.DataFrame, k_period: int = 14, d_period: int = 3):
    """Calculate Stochastic %K and %D manually. Returns (k_series, d_series)."""
    low_min = df["low"].rolling(k_period).min()
    high_max = df["high"].rolling(k_period).max()
    k = 100.0 * (df["close"] - low_min) / (high_max - low_min).replace(0, np.nan)
    d = k.rolling(d_period).mean()
    return k, d


class TechAgent(BaseAgent):
    """Technical analysis agent using RSI, MACD, Bollinger Bands, and volume."""

    def __init__(self):
        super().__init__(
            name="TechAgent",
            strategy_description="Technical analysis: RSI, MACD, Bollinger Bands, Stochastic, OBV, Volume",
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

            # Stochastic oscillator
            if "high" in df.columns and "low" in df.columns:
                if HAS_PANDAS_TA:
                    df.ta.stoch(k=14, d=3, smooth_k=1, append=True)
                    sk_col, sd_col = "STOCHk_14_3_1", "STOCHd_14_3_1"
                    if sk_col in df.columns and sd_col in df.columns:
                        df["stoch_k"] = df[sk_col]
                        df["stoch_d"] = df[sd_col]
                    else:
                        df["stoch_k"], df["stoch_d"] = manual_stoch(df)
                else:
                    df["stoch_k"], df["stoch_d"] = manual_stoch(df)
            else:
                df["stoch_k"] = np.nan
                df["stoch_d"] = np.nan

            # OBV (On-Balance Volume)
            if "volume" in df.columns:
                direction = np.sign(df["close"].diff()).fillna(0)
                df["obv"] = (direction * df["volume"]).cumsum()
            else:
                df["obv"] = 0.0

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

        # Stochastic values
        stoch_k = latest.get("stoch_k", 50)
        stoch_d = latest.get("stoch_d", 50)
        prev_stoch_k = prev.get("stoch_k", 50)
        if isinstance(stoch_k, float) and math.isnan(stoch_k):
            stoch_k = 50
        if isinstance(stoch_d, float) and math.isnan(stoch_d):
            stoch_d = 50
        if isinstance(prev_stoch_k, float) and math.isnan(prev_stoch_k):
            prev_stoch_k = 50

        # OBV direction vs price direction over last 5 bars
        obv_col = df["obv"] if "obv" in df.columns else None
        obv_rising = False
        obv_falling = False
        price_rising_5bars = False
        if obv_col is not None and len(df) >= 6:
            price_5ago = float(df["close"].iloc[-6])
            obv_rising = float(obv_col.iloc[-1]) > float(obv_col.iloc[-6])
            obv_falling = not obv_rising
            price_rising_5bars = current_price > price_5ago

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

        # Stochastic: oversold zone entry timing
        if stoch_k < 20 and stoch_k > prev_stoch_k:
            buy_score += 0.15
            buy_reasons.append(f"Stoch %K={stoch_k:.1f} oversold+rising (entry trigger)")
        elif stoch_k < 20:
            buy_score += 0.08
            buy_reasons.append(f"Stoch %K={stoch_k:.1f} oversold")

        # OBV confirmation / divergence
        if obv_col is not None and len(df) >= 6:
            if price_rising_5bars and obv_rising:
                buy_score += 0.10
                buy_reasons.append("OBV confirming upward pressure")
            elif not price_rising_5bars and obv_rising:
                buy_score += 0.08
                buy_reasons.append("OBV divergence: accumulation despite price weakness")

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

        # Stochastic: overbought zone exit timing
        if stoch_k > 80 and stoch_k < prev_stoch_k:
            sell_score += 0.15
            sell_reasons.append(f"Stoch %K={stoch_k:.1f} overbought+falling (exit trigger)")
        elif stoch_k > 80:
            sell_score += 0.08
            sell_reasons.append(f"Stoch %K={stoch_k:.1f} overbought")

        # OBV divergence: smart money distributing into strength
        if obv_col is not None and len(df) >= 6:
            if price_rising_5bars and obv_falling:
                sell_score += 0.12
                sell_reasons.append("OBV divergence: distribution (price up, volume leaving)")
            elif not price_rising_5bars and obv_falling:
                sell_score += 0.08
                sell_reasons.append("OBV confirming downward pressure")

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
        bb_pos = (current_price - bb_lower) / (bb_upper - bb_lower) if (bb_upper - bb_lower) > 0 else 0.5
        context = f"RSI={rsi:.1f}, MACD={macd_hist:.3f}, Stoch%K={stoch_k:.1f}, BB_pos={bb_pos:.2f}"
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
            if not isinstance(ctx, dict):
                continue
            try:
                bars = ctx.get("bars")
                prices = {s: c.get("price", 0) for s, c in market_context.items() if isinstance(c, dict)}

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
