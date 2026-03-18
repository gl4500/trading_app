"""
Sentiment Agent: Uses OpenAI GPT-4o-mini to analyze market sentiment
from price patterns and volume data.
"""
import asyncio
import json
import logging
import math
from datetime import date
from typing import Dict, List, Optional
import pandas as pd

from agents.base_agent import BaseAgent, Signal
from agents.agent_utils import _is_market_hours
from config import config

logger = logging.getLogger(__name__)

try:
    from openai import AsyncOpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    logger.warning("OpenAI package not available")


def _describe_price_action(bars: pd.DataFrame, symbol: str, current_price: float) -> str:
    """Create a textual description of price action for sentiment analysis."""
    if bars is None or bars.empty or len(bars) < 5:
        return f"{symbol}: No sufficient price history available."

    close = bars["close"].values
    volume = bars["volume"].values if "volume" in bars.columns else None
    high = bars["high"].values if "high" in bars.columns else close
    low = bars["low"].values if "low" in bars.columns else close

    # Recent returns
    ret_1d = (close[-1] - close[-2]) / close[-2] * 100 if len(close) > 1 else 0
    ret_5d = (close[-1] - close[-6]) / close[-6] * 100 if len(close) > 5 else 0
    ret_20d = (close[-1] - close[-21]) / close[-21] * 100 if len(close) > 20 else 0

    # Volume analysis
    vol_desc = ""
    if volume is not None and len(volume) > 5:
        avg_vol = volume[-20:].mean() if len(volume) >= 20 else volume.mean()
        recent_vol = volume[-3:].mean()
        vol_ratio = recent_vol / avg_vol if avg_vol > 0 else 1
        if vol_ratio > 1.5:
            vol_desc = f"Trading on {vol_ratio:.1f}x above average volume (unusual activity). "
        elif vol_ratio > 1.2:
            vol_desc = f"Trading on slightly elevated volume ({vol_ratio:.1f}x average). "
        elif vol_ratio < 0.7:
            vol_desc = f"Trading on low volume ({vol_ratio:.1f}x average). "
        else:
            vol_desc = f"Trading on normal volume ({vol_ratio:.1f}x average). "

    # Volatility
    if len(close) >= 10:
        daily_returns = [(close[i] - close[i-1]) / close[i-1] for i in range(-10, 0) if close[i-1] > 0]
        if daily_returns:
            import numpy as np
            volatility = float(np.std(daily_returns) * 100)
            vol_level = "high" if volatility > 3 else "moderate" if volatility > 1.5 else "low"
        else:
            vol_level = "normal"
            volatility = 0
    else:
        vol_level = "normal"
        volatility = 0

    # Recent high/low
    recent_high = max(high[-20:]) if len(high) >= 20 else max(high)
    recent_low = min(low[-20:]) if len(low) >= 20 else min(low)
    pct_from_high = (current_price - recent_high) / recent_high * 100
    pct_from_low = (current_price - recent_low) / recent_low * 100

    # Trend description
    if ret_20d > 10:
        trend = "strong uptrend"
    elif ret_20d > 3:
        trend = "modest uptrend"
    elif ret_20d < -10:
        trend = "significant downtrend"
    elif ret_20d < -3:
        trend = "modest downtrend"
    else:
        trend = "sideways range"

    # Consecutive days direction
    last_5_returns = [(close[i] - close[i-1]) / close[i-1] for i in range(-5, 0) if close[i-1] > 0]
    consecutive_up = sum(1 for r in last_5_returns if r > 0)
    consecutive_desc = f"{consecutive_up}/5 recent days positive"

    description = (
        f"{symbol} is currently priced at ${current_price:.2f}, showing {trend} over 20 days. "
        f"Performance: 1D={ret_1d:+.1f}%, 5D={ret_5d:+.1f}%, 20D={ret_20d:+.1f}%. "
        f"{vol_desc}"
        f"Price is {abs(pct_from_high):.1f}% below 20-day high (${recent_high:.2f}) "
        f"and {pct_from_low:.1f}% above 20-day low (${recent_low:.2f}). "
        f"Volatility is {vol_level} at {volatility:.1f}% daily std. "
        f"Momentum: {consecutive_desc}."
    )

    return description


class SentimentAgent(BaseAgent):
    """Sentiment analysis agent using OpenAI GPT-4o-mini."""

    def __init__(self):
        super().__init__(
            name="SentimentAgent",
            strategy_description="Market sentiment analysis via OpenAI GPT-4o-mini",
        )
        self._openai_client: Optional["AsyncOpenAI"] = None
        self._sentiment_cache: Dict[str, Dict] = {}  # symbol -> last sentiment_data from API
        self._cycle_count: int = 0
        self._open_interval: int = 5    # API call every N cycles during market hours (80% budget)
        self._closed_interval: int = 25  # API call every N cycles during off hours  (20% budget)
        self._daily_tokens: int = 0
        self._token_reset_day: Optional[date] = None
        self._daily_token_limit: int = 10_000

    def _get_client(self):
        if not HAS_OPENAI:
            return None
        if self._openai_client is None:
            self._openai_client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        return self._openai_client

    async def _get_sentiment(self, symbol: str, description: str) -> Dict:
        """Query OpenAI for sentiment analysis."""
        client = self._get_client()
        if client is None:
            return {"sentiment": "neutral", "confidence": 0.5, "reasoning": "OpenAI not available"}

        if not config.OPENAI_API_KEY:
            return {"sentiment": "neutral", "confidence": 0.5, "reasoning": "No OpenAI API key configured"}

        # Reset daily counter on a new calendar day
        today = date.today()
        if self._token_reset_day is None:
            self._token_reset_day = today  # first call: record the day, keep existing counter
        elif self._token_reset_day != today:
            self._daily_tokens = 0
            self._token_reset_day = today

        # Enforce daily token budget
        if self._daily_tokens >= self._daily_token_limit:
            logger.warning(
                f"SentimentAgent: Daily token limit ({self._daily_token_limit}) reached — "
                f"skipping API call for {symbol}"
            )
            return {"sentiment": "neutral", "confidence": 0.5, "reasoning": "Daily token limit reached"}

        prompt = f"""You are a quantitative analyst. Analyze the following price action data and provide a market sentiment assessment.

Price Action Data:
{description}

Based ONLY on this price and volume data (no external knowledge), provide your assessment.

Respond with ONLY valid JSON in this exact format:
{{
  "sentiment": "bullish" | "bearish" | "neutral",
  "confidence": <float 0.0-1.0>,
  "strength": "strong" | "moderate" | "weak",
  "reasoning": "<brief 1-2 sentence explanation>",
  "key_signals": ["<signal1>", "<signal2>"]
}}"""

        try:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a quantitative market analyst. Respond only with valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=300,
                temperature=0.3,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            result = json.loads(content)

            # Log and accumulate token usage
            usage = response.usage
            prompt_tok = usage.prompt_tokens
            completion_tok = usage.completion_tokens
            self._daily_tokens += prompt_tok + completion_tok
            logger.info(
                f"SentimentAgent: {symbol} tokens — "
                f"in={prompt_tok} out={completion_tok} "
                f"daily_total={self._daily_tokens}/{self._daily_token_limit}"
            )

            return result

        except json.JSONDecodeError as e:
            logger.error(f"SentimentAgent: JSON parse error for {symbol}: {e}")
            return {"sentiment": "neutral", "confidence": 0.5, "reasoning": "JSON parse error"}
        except Exception as e:
            logger.error(f"SentimentAgent: OpenAI error for {symbol}: {e}")
            return {"sentiment": "neutral", "confidence": 0.5, "reasoning": f"API error: {str(e)[:100]}"}

    def _generate_signal(self, symbol: str, sentiment_data: Dict, prices: Dict[str, float]) -> Signal:
        """Convert sentiment analysis into a trading signal."""
        current_price = prices.get(symbol, 0)
        if current_price <= 0:
            return Signal(action="HOLD", symbol=symbol, confidence=0, shares=0,
                          reasoning="No price data")

        sentiment = sentiment_data.get("sentiment", "neutral")
        confidence = float(sentiment_data.get("confidence", 0.5))
        strength = sentiment_data.get("strength", "weak")
        reasoning = sentiment_data.get("reasoning", "")
        key_signals = sentiment_data.get("key_signals", [])

        has_position = symbol in self.portfolio.positions

        # Adjust confidence by strength
        strength_multiplier = {"strong": 1.0, "moderate": 0.8, "weak": 0.6}.get(strength, 0.7)
        adjusted_confidence = confidence * strength_multiplier

        signals_text = "; ".join(key_signals[:3]) if key_signals else ""

        if sentiment == "bullish" and adjusted_confidence >= 0.45 and not has_position:
            portfolio_value = self.portfolio.get_total_value(prices)
            target_alloc = portfolio_value * config.MAX_POSITION_SIZE * adjusted_confidence
            target_alloc = min(target_alloc, self.portfolio.cash * 0.95)
            shares = math.floor(target_alloc / current_price * 100) / 100

            if shares < 0.01:
                return Signal(action="HOLD", symbol=symbol, confidence=adjusted_confidence,
                              shares=0, reasoning=f"Bullish sentiment but insufficient funds")

            return Signal(
                action="BUY",
                symbol=symbol,
                confidence=adjusted_confidence,
                shares=shares,
                reasoning=(
                    f"SENTIMENT BUY ({strength}): {reasoning}. "
                    f"Signals: {signals_text}. Confidence={adjusted_confidence:.2f}"
                ),
            )

        elif sentiment == "bearish" and adjusted_confidence >= 0.45 and has_position:
            pos = self.portfolio.positions[symbol]
            return Signal(
                action="SELL",
                symbol=symbol,
                confidence=adjusted_confidence,
                shares=pos.shares,
                reasoning=(
                    f"SENTIMENT SELL ({strength}): {reasoning}. "
                    f"Signals: {signals_text}. Confidence={adjusted_confidence:.2f}"
                ),
            )

        return Signal(
            action="HOLD",
            symbol=symbol,
            confidence=adjusted_confidence,
            shares=0,
            reasoning=(
                f"SENTIMENT HOLD: {sentiment} ({strength}). {reasoning}. "
                f"Confidence={adjusted_confidence:.2f}"
            ),
        )

    async def analyze(self, market_context: Dict) -> List[Signal]:
        """Analyze sentiment for all symbols using OpenAI."""
        interval = self._open_interval if _is_market_hours() else self._closed_interval
        self._cycle_count += 1
        use_cache = (self._cycle_count % interval != 1) and bool(self._sentiment_cache)

        prices = {s: ctx.get("price", 0) for s, ctx in market_context.items() if isinstance(ctx, dict)}
        items = [(s, ctx) for s, ctx in market_context.items() if isinstance(ctx, dict)]

        # Replay cached sentiment on non-API cycles
        if use_cache:
            logger.debug(f"SentimentAgent: Replaying cached sentiment (cycle {self._cycle_count})")
            return [
                self._generate_signal(sym, self._sentiment_cache[sym], prices)
                for sym, _ in items
                if sym in self._sentiment_cache
            ]

        # API cycle — fetch fresh sentiment for each symbol
        signals = []

        async def analyze_symbol(symbol: str, ctx: Dict) -> Signal:
            try:
                bars = ctx.get("bars")
                current_price = prices.get(symbol, 0)
                news_items = ctx.get("news", [])

                description = _describe_price_action(bars, symbol, current_price)

                if news_items:
                    headlines = " | ".join(a["headline"] for a in news_items[:3])
                    description += f" Recent news: {headlines}"

                sentiment_data = await self._get_sentiment(symbol, description)
                self._sentiment_cache[symbol] = sentiment_data
                return self._generate_signal(symbol, sentiment_data, prices)

            except Exception as e:
                logger.error(f"SentimentAgent: Error analyzing {symbol}: {e}")
                return Signal(
                    action="HOLD", symbol=symbol, confidence=0, shares=0,
                    reasoning=f"Analysis error: {str(e)[:100]}"
                )

        batch_size = 3
        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            batch_signals = await asyncio.gather(
                *[analyze_symbol(sym, ctx) for sym, ctx in batch],
                return_exceptions=True
            )
            for result in batch_signals:
                if isinstance(result, Exception):
                    logger.error(f"SentimentAgent batch error: {result}")
                else:
                    signals.append(result)

            if i + batch_size < len(items):
                await asyncio.sleep(0.5)

        return signals
