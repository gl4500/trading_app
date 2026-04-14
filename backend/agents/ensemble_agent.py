"""
Ensemble Agent: Combines signals from all other agents using adaptive weighted voting.

Improvements over fixed-weight voting:
  1. Adaptive weights   — agents that have been performing better (higher Sharpe + win
                          rate over recent trades) receive more vote weight automatically.
  2. Regime detection   — classifies the market as Trending / Ranging / Volatile using
                          SMA slope and ATR, then applies regime-specific multipliers so
                          the right strategy dominates in each environment.
  3. Performance floor  — no agent is ever zeroed out; minimum 30 % of its base weight
                          is always preserved so recovering agents can still contribute.

Weights are recomputed every WEIGHT_UPDATE_INTERVAL cycles.
"""
import asyncio
import logging
import math
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

from agents.base_agent import BaseAgent, Signal
from config import config

logger = logging.getLogger(__name__)

# How often (in cycles) to recompute adaptive weights
WEIGHT_UPDATE_INTERVAL = 5

# Minimum fraction of base weight an agent can fall to
WEIGHT_FLOOR = 0.30

# Regime-specific multipliers applied on top of performance weights
REGIME_MULTIPLIERS: Dict[str, Dict[str, float]] = {
    "trending": {
        "MomentumAgent":          1.50,
        "TechAgent":              1.20,
        "HistoricalTrendsAgent":  1.20,  # seasonal + multi-period momentum shines in trends
        "ClaudeAgent":            1.10,
        "CNNReasoningAgent":      1.20,  # CNN temporal patterns shine in trending markets
        "SentimentAgent":         0.80,
        "MeanReversionAgent":     0.40,
    },
    "ranging": {
        "MeanReversionAgent":     1.60,
        "HistoricalTrendsAgent":  1.30,  # channel analysis works well in range-bound markets
        "SentimentAgent":         1.20,
        "TechAgent":              1.10,
        "ClaudeAgent":            1.00,
        "CNNReasoningAgent":      0.90,
        "MomentumAgent":          0.55,
    },
    "volatile": {
        "ClaudeAgent":            1.40,
        "SentimentAgent":         1.20,
        "CNNReasoningAgent":      1.10,  # CNN adapts weights dynamically in volatility
        "TechAgent":              0.80,
        "MomentumAgent":          0.65,
        "MeanReversionAgent":     0.60,
        "HistoricalTrendsAgent":  0.80,  # seasonal patterns less reliable in volatile regimes
    },
}


class EnsembleAgent(BaseAgent):
    """
    Ensemble agent that aggregates signals from all component agents
    using adaptive performance-weighted voting with regime awareness.
    """

    def __init__(
        self,
        tech_agent: "BaseAgent" = None,
        momentum_agent: "BaseAgent" = None,
        mean_reversion_agent: "BaseAgent" = None,
        sentiment_agent: "BaseAgent" = None,
        claude_agent: "BaseAgent" = None,
        cnn_reasoning_agent: "BaseAgent" = None,
    ):
        super().__init__(
            name="EnsembleAgent",
            strategy_description=(
                "Adaptive ensemble: performance-weighted voting with regime detection "
                "(Trending / Ranging / Volatile)"
            ),
        )
        self.component_agents: Dict[str, BaseAgent] = {}
        self.base_weights: Dict[str, float] = dict(config.ENSEMBLE_WEIGHTS)
        self.consensus_threshold = config.ENSEMBLE_THRESHOLD

        # State
        self._adaptive_weights: Dict[str, float] = dict(self.base_weights)
        self._regime: str = "ranging"          # current detected regime
        self._cycle_count: int = 0
        self._last_weight_log: Dict[str, float] = {}  # for logging changes only

        for name, agent in [
            ("TechAgent", tech_agent),
            ("MomentumAgent", momentum_agent),
            ("MeanReversionAgent", mean_reversion_agent),
            ("SentimentAgent", sentiment_agent),
            ("ClaudeAgent", claude_agent),
            ("CNNReasoningAgent", cnn_reasoning_agent),
        ]:
            if agent is not None:
                self.component_agents[name] = agent

    def set_agents(self, agents: Dict[str, "BaseAgent"]) -> None:
        """Set component agents after initialization (GeminiAgent excluded — news-only)."""
        for name, agent in agents.items():
            if name not in ("EnsembleAgent", "GeminiAgent", "ScannerPortfolioAgent"):
                self.component_agents[name] = agent

    # ── Regime detection ───────────────────────────────────────────────────────

    def _detect_regime(self, market_context: Dict) -> str:
        """
        Classify market regime using two complementary methods:

        1. SMA-slope + ATR (intraday, fast signals) — existing logic
        2. HMM-inspired RegimeDetector (20-day momentum + realized vol)

        The two signals are combined with a conservative consensus rule:
          - If both agree → use the agreed regime
          - "volatile" beats "ranging" beats "trending" when they conflict
            (prefer the more defensive classification)
        """
        # ── Feed SPY close prices to the HMM regime detector ─────────────────
        hmm_regime = "ranging"   # default if no SPY history
        try:
            from data.regime_detector import regime_detector
            spy_ctx = market_context.get("SPY", {})
            spy_bars = spy_ctx.get("bars") if isinstance(spy_ctx, dict) else None
            if spy_bars is not None and not spy_bars.empty and len(spy_bars) >= 21:
                spy_close = spy_bars["close"].astype(float).tolist()
                regime_detector.update(spy_close)
            hmm_regime = regime_detector.get_ensemble_regime()
        except Exception as _e:
            logger.debug(f"EnsembleAgent: HMM regime update error: {_e}")

        # Prefer a broad market proxy, fall back to any symbol with enough bars
        bars = None
        for sym in ["SPY", "QQQ"] + list(market_context.keys()):
            ctx = market_context.get(sym, {})
            b = ctx.get("bars")
            if b is not None and not b.empty and len(b) >= 20:
                bars = b
                break

        if bars is None:
            return hmm_regime   # fall back to HMM-only result

        try:
            close = bars["close"].astype(float)
            price = float(close.iloc[-1])
            if price <= 0:
                return hmm_regime

            # SMA-20 slope: change over last 10 bars, normalised by price
            sma20 = close.rolling(20).mean().dropna()
            if len(sma20) < 10:
                return hmm_regime
            sma_slope = (float(sma20.iloc[-1]) - float(sma20.iloc[-10])) / price

            # ATR over 14 bars
            if "high" in bars.columns and "low" in bars.columns:
                atr = float((bars["high"].astype(float) - bars["low"].astype(float)).tail(14).mean())
                atr_pct = atr / price
            else:
                atr_pct = 0.015  # assume ~1.5 %

            if atr_pct > 0.025:          # intraday swings > 2.5 % → volatile
                sma_regime = "volatile"
            else:
                # 2-of-3 multi-signal check for trending
                trending_signals = 0

                # Signal 1: SMA slope
                if abs(sma_slope) > 0.004:
                    trending_signals += 1

                # Signal 2: trend consistency (pct of returns in same direction as slope)
                if len(close) >= 11:
                    returns = close.pct_change().dropna().tail(10)
                    pct_positive = (returns > 0).sum() / len(returns)
                    if (sma_slope > 0 and pct_positive > 0.60) or (sma_slope < 0 and pct_positive < 0.40):
                        trending_signals += 1

                # Signal 3: volume expansion (recent 5-bar avg > 20-bar avg * 1.10)
                if "volume" in bars.columns and len(bars) >= 20:
                    vol = bars["volume"].astype(float)
                    if vol.tail(5).mean() > vol.tail(20).mean() * 1.10:
                        trending_signals += 1

                sma_regime = "trending" if trending_signals >= 2 else "ranging"

            # ── Combine SMA and HMM regimes (conservative consensus) ──────────
            # Priority: volatile > ranging > trending (most defensive wins on conflict)
            _priority = {"volatile": 2, "ranging": 1, "trending": 0}
            if _priority.get(hmm_regime, 0) > _priority.get(sma_regime, 0):
                return hmm_regime
            return sma_regime

        except Exception as e:
            logger.debug(f"EnsembleAgent: regime detection error: {e}")
            return hmm_regime

    # ── Adaptive weight computation ────────────────────────────────────────────

    def _compute_adaptive_weights(
        self, prices: Dict[str, float], regime: str
    ) -> Dict[str, float]:
        """
        Build performance-adjusted, regime-modified weights.

        Steps:
          1. Score each agent by (win_rate + normalised_sharpe) / 2
          2. Apply WEIGHT_FLOOR so no agent drops below 30 % of its base weight
          3. Apply regime multipliers
          4. Normalise to sum = 1
        """
        perf_scores: Dict[str, float] = {}

        for name, agent in self.component_agents.items():
            try:
                metrics = agent.portfolio.calculate_metrics(prices)
                total_trades = metrics.get("total_trades", 0)

                if total_trades < 5:
                    # Not enough history — use neutral score
                    perf_scores[name] = 1.0
                    continue

                win_rate = float(metrics.get("win_rate", 0.5))
                sharpe   = float(metrics.get("sharpe_ratio", 0.0))

                # Normalise Sharpe: clamp [-2, +3] → [0, 1]
                sharpe_norm = max(0.0, min(1.0, (sharpe + 2.0) / 5.0))

                perf_scores[name] = 0.5 * win_rate + 0.5 * sharpe_norm

            except Exception:
                perf_scores[name] = 1.0

        # Build raw weights: base × max(floor, performance_score) × regime multiplier
        regime_mods = REGIME_MULTIPLIERS.get(regime, {})
        raw: Dict[str, float] = {}

        for name in self.component_agents:
            base        = self.base_weights.get(name, 0.10)
            perf        = max(WEIGHT_FLOOR, perf_scores.get(name, 1.0))
            regime_mod  = regime_mods.get(name, 1.0)
            raw[name]   = base * perf * regime_mod

        # Normalise
        total = sum(raw.values())
        if total <= 0:
            return dict(self.base_weights)

        return {name: w / total for name, w in raw.items()}

    def _log_weight_changes(self, new_weights: Dict[str, float], regime: str) -> None:
        """Log weight shifts that exceed 3 percentage points."""
        changes = []
        for name, w in new_weights.items():
            prev = self._last_weight_log.get(name, self.base_weights.get(name, 0))
            if abs(w - prev) > 0.03:
                direction = "▲" if w > prev else "▼"
                changes.append(f"{name} {direction}{w:.0%}")

        if changes or regime != self._regime:
            logger.info(
                f"EnsembleAgent: regime={regime.upper()} | weights: "
                + ", ".join(
                    f"{n}={w:.0%}" for n, w in sorted(new_weights.items(), key=lambda x: -x[1])
                )
                + (f" | shifts: {', '.join(changes)}" if changes else "")
            )
        self._last_weight_log = dict(new_weights)

    # ── Signal collection ──────────────────────────────────────────────────────

    async def _collect_signals(self, market_context: Dict) -> Dict[str, List]:
        """Run all component agents' analyze() concurrently, return by symbol."""
        if not self.component_agents:
            return {}

        agent_names = list(self.component_agents.keys())
        tasks = [self.component_agents[n].analyze(market_context) for n in agent_names]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        signals_by_symbol: Dict[str, List[Tuple]] = defaultdict(list)
        for agent_name, result in zip(agent_names, results):
            if isinstance(result, Exception):
                logger.error(f"EnsembleAgent: error from {agent_name}: {result}")
                continue
            weight = self._adaptive_weights.get(agent_name, 0.10)
            for signal in result:
                signal.agent_name = agent_name
                signals_by_symbol[signal.symbol].append((agent_name, weight, signal))

        return dict(signals_by_symbol)

    # ── Voting ─────────────────────────────────────────────────────────────────

    def _vote(
        self,
        symbol: str,
        agent_signals: List[Tuple],
        current_price: float = 0.0,
    ) -> Signal:
        """Weighted-vote across agent signals. Returns consensus Signal or HOLD."""
        if not agent_signals:
            return Signal(action="HOLD", symbol=symbol, confidence=0, shares=0,
                          reasoning="No agent signals available")

        buy_weight = sell_weight = total_weight = 0.0
        buy_signals: List[Tuple] = []
        sell_signals: List[Tuple] = []
        all_reasonings: List[str] = []

        for agent_name, weight, signal in agent_signals:
            total_weight += weight
            wconf = signal.confidence * weight

            if signal.action == "BUY":
                buy_weight += wconf
                buy_signals.append((agent_name, signal))
            elif signal.action == "SELL":
                sell_weight += wconf
                sell_signals.append((agent_name, signal))

            if signal.action in ("BUY", "SELL") and signal.reasoning:
                all_reasonings.append(f"{agent_name}: {signal.reasoning[:80]}")

        buy_score  = buy_weight  / total_weight if total_weight > 0 else 0
        sell_score = sell_weight / total_weight if total_weight > 0 else 0

        has_position = symbol in self.portfolio.positions

        logger.debug(
            f"EnsembleAgent [{self._regime}]: {symbol} "
            f"buy={buy_score:.2f} sell={sell_score:.2f} threshold={self.consensus_threshold}"
        )

        # BUY consensus — requires threshold AND 2x margin of safety over sell signal
        if buy_score >= self.consensus_threshold and not has_position:
            # 2x margin of safety: buy must be at least 2x the opposing sell signal
            if buy_score < sell_score * config.MARGIN_OF_SAFETY:
                return Signal(action="HOLD", symbol=symbol, confidence=buy_score, shares=0,
                              reasoning=(
                                  f"ENSEMBLE HOLD [{self._regime.upper()}]: buy={buy_score:.0%} passes threshold "
                                  f"but sell={sell_score:.0%} is too close — 2x margin of safety requires "
                                  f"buy >= {sell_score * config.MARGIN_OF_SAFETY:.0%}. Conflicted signal."
                              ))

            if current_price <= 0:
                return Signal(action="HOLD", symbol=symbol, confidence=buy_score, shares=0,
                              reasoning="Cannot determine price")

            portfolio_value = self.portfolio.get_total_value({symbol: current_price})
            target_alloc = portfolio_value * config.MAX_POSITION_SIZE * buy_score
            target_alloc = min(target_alloc, self.portfolio.cash * 0.95)
            shares = math.floor(target_alloc / current_price * 100) / 100

            if shares < 0.01:
                return Signal(action="HOLD", symbol=symbol, confidence=buy_score, shares=0,
                              reasoning=f"Consensus BUY ({buy_score:.0%}) but insufficient funds")

            return Signal(
                action="BUY",
                symbol=symbol,
                confidence=buy_score,
                shares=shares,
                reasoning=(
                    f"ENSEMBLE BUY [{self._regime.upper()}]: {buy_score:.0%} consensus | "
                    f"2x margin of safety: buy={buy_score:.0%} >= sell={sell_score:.0%}×2 | "
                    f"Agents: {', '.join(a for a, _ in buy_signals)} | "
                    + " | ".join(all_reasonings[:2])
                ),
            )

        # SELL consensus
        if sell_score >= self.consensus_threshold and has_position:
            pos = self.portfolio.positions[symbol]
            return Signal(
                action="SELL",
                symbol=symbol,
                confidence=sell_score,
                shares=pos.shares,
                reasoning=(
                    f"ENSEMBLE SELL [{self._regime.upper()}]: {sell_score:.0%} consensus | "
                    f"Agents: {', '.join(a for a, _ in sell_signals)} | "
                    + " | ".join(all_reasonings[:2])
                ),
            )

        # No consensus
        dominant = "BUY" if buy_score > sell_score else "SELL" if sell_score > buy_score else "NEUTRAL"
        return Signal(
            action="HOLD",
            symbol=symbol,
            confidence=max(buy_score, sell_score),
            shares=0,
            reasoning=(
                f"ENSEMBLE HOLD [{self._regime.upper()}]: no consensus "
                f"(buy={buy_score:.0%}, sell={sell_score:.0%}, "
                f"threshold={self.consensus_threshold:.0%}). Leaning {dominant}."
            ),
        )

    # ── Main cycle ─────────────────────────────────────────────────────────────

    async def analyze(self, market_context: Dict) -> List[Signal]:
        """Collect agent signals and generate regime-aware ensemble signals."""
        if not self.component_agents:
            return [
                Signal(action="HOLD", symbol=sym, confidence=0, shares=0,
                       reasoning="No component agents configured")
                for sym in market_context.keys()
            ]

        prices = {s: ctx.get("price", 0) for s, ctx in market_context.items() if isinstance(ctx, dict)}
        self._cycle_count += 1

        # Recompute regime + weights periodically
        if self._cycle_count % WEIGHT_UPDATE_INTERVAL == 1:
            new_regime  = self._detect_regime(market_context)
            new_weights = self._compute_adaptive_weights(prices, new_regime)
            self._log_weight_changes(new_weights, new_regime)
            self._regime          = new_regime
            self._adaptive_weights = new_weights
            try:
                from data.risk_assessor import record_regime
                record_regime(new_regime, prices)
            except Exception:
                pass

        signals_by_symbol = await self._collect_signals(market_context)

        ensemble_signals = []
        for symbol, ctx in market_context.items():
            if not isinstance(ctx, dict):
                continue
            try:
                agent_signals = signals_by_symbol.get(symbol, [])
                if not agent_signals:
                    ensemble_signals.append(Signal(
                        action="HOLD", symbol=symbol, confidence=0, shares=0,
                        reasoning="No signals from component agents",
                    ))
                    continue

                signal = self._vote(symbol, agent_signals, prices.get(symbol, 0))
                ensemble_signals.append(signal)

            except Exception as e:
                logger.error(f"EnsembleAgent: error voting for {symbol}: {e}")
                ensemble_signals.append(Signal(
                    action="HOLD", symbol=symbol, confidence=0, shares=0,
                    reasoning=f"Voting error: {str(e)[:100]}",
                ))

        return ensemble_signals

    def get_component_summary(self) -> Dict:
        """Get summary of component agent states including current weights."""
        return {
            name: {
                "active":          agent._is_active,
                "base_weight":     self.base_weights.get(name, 0),
                "adaptive_weight": self._adaptive_weights.get(name, 0),
                "regime":          self._regime,
                "trades":          len(agent.portfolio.trade_history),
            }
            for name, agent in self.component_agents.items()
        }
