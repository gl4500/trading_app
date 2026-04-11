"""
CNN Reasoning Agent
-------------------
Combines a trained temporal CNN (data/cnn_model.py) with active LLM reasoning
to produce trading signals.

Data flow per cycle
-------------------
  1. Ensure model is loaded / retrain if 24 h have elapsed and data is ready
  2. For each symbol pull the recent (5, T) rolling window from signal_history
  3. CNN forward pass → (predicted_return, direction, cnn_confidence)
  4. Build a concise prompt that includes:
       • CNN prediction + learned vs hardcoded weight comparison
       • Current source scores + composite score
  5. Send prompt to Ollama (primary, local, free)
  6. If Ollama is unavailable → simple rule-based fallback
  7. Parse action/confidence/reasoning → emit Signal

Training schedule
-----------------
  • Triggered at most once per 24 h (RETRAIN_INTERVAL)
  • Requires ≥ MIN_TRAIN_SAMPLES rows with known 1-day outcomes
  • Runs in a background thread via asyncio.to_thread so the trading loop
    is never blocked
"""
import asyncio
import json
import logging
import re
import time
from typing import Dict, List, Optional

from agents.base_agent import BaseAgent, Signal
from agents.agent_utils import get_fallback_signals
from config import config
from data.signal_history import signal_history
from data.cnn_model import signal_cnn, build_training_windows, MIN_TRAIN_SAMPLES
from data.agent_performance_tracker import agent_performance_tracker

logger = logging.getLogger(__name__)

RETRAIN_INTERVAL = 86_400        # seconds between retraining runs (24 h)
_OLLAMA_BASE     = "http://localhost:11434/v1"

_HARDCODED = {
    "analyst_consensus":    35,
    "earnings_surprise":    22,
    "alpaca_news":          18,
    "yahoo_news":           12,
    "congressional_trades": 13,
}


class CNNReasoningAgent(BaseAgent):
    """
    Trading agent driven by a learned temporal CNN + Ollama active reasoning.

    Primary  : Ollama (local, free, zero API cost)
    Secondary: simple rule-based fallback (direction → action)
    """

    def __init__(self):
        super().__init__(
            name="CNNReasoningAgent",
            strategy_description=(
                "Temporal CNN signal weighting with Ollama active reasoning"
            ),
        )
        self._model_loaded    = False
        self._last_train_check = 0.0
        self._training_lock   = asyncio.Lock()

    # ── model lifecycle ───────────────────────────────────────────────────────

    async def _ensure_model(self) -> None:
        """Load saved weights on first call; trigger retrain when due."""
        if not self._model_loaded:
            self._model_loaded = signal_cnn.load()

        now = time.time()
        if now - self._last_train_check < 3_600:   # check at most every hour
            return
        self._last_train_check = now

        # Skip if a recent trained model already exists
        if signal_cnn.is_trained and (now - signal_cnn.last_train_time) < RETRAIN_INTERVAL:
            return

        # Run training in a background thread to avoid blocking the event loop
        async with self._training_lock:
            await asyncio.to_thread(self._train_blocking)

    def _train_blocking(self) -> None:
        """Blocking training call — executed via asyncio.to_thread."""
        try:
            df = signal_history.get_training_data()
            if df.empty or len(df) < MIN_TRAIN_SAMPLES:
                logger.info(
                    f"CNNReasoningAgent: {len(df)} labelled samples available "
                    f"(need {MIN_TRAIN_SAMPLES}) — skipping training"
                )
                return
            X, y, w = build_training_windows(df)
            if len(X) < MIN_TRAIN_SAMPLES:
                return
            # Use sample weights so rows where top-performing agents were
            # confirmed correct have higher training influence
            signal_cnn.fit(X, y, epochs=80, batch_size=32, sample_weights=w)
            signal_cnn.save()
            summary = signal_cnn.training_summary()
            logger.info(
                f"CNNReasoningAgent: training complete on {len(X)} samples | "
                f"channels={X.shape[1]} | MSE={summary['final_mse']:.6f} | "
                f"device={summary['device']} | learned weights: {summary['learned_weights']}"
            )
        except Exception as exc:
            logger.error(f"CNNReasoningAgent: training failed: {exc}", exc_info=True)

    # ── Ollama prompt + call ──────────────────────────────────────────────────

    def _build_prompt(
        self,
        symbol:          str,
        price:           float,
        pred_return:     float,
        direction:       str,
        cnn_conf:        float,
        learned_weights: Dict[str, float],
        current_scores:  Dict[str, Optional[float]],
        composite_score: float,
        agent_signals:   Optional[Dict[str, tuple]] = None,
    ) -> str:
        weight_lines = "\n".join(
            f"  • {name:<25} learned={w*100:5.1f}%  hardcoded={_HARDCODED[name]}%  "
            f"{'▲ elevated' if w*100 > _HARDCODED[name]+2 else ('▼ reduced' if w*100 < _HARDCODED[name]-2 else '≈ same')}"
            for name, w in learned_weights.items()
        )
        score_lines = "\n".join(
            f"  • {name:<25} {f'{v:+.3f}' if v is not None else 'n/a'}"
            for name, v in current_scores.items()
        )

        # Agent performance section — injected when signals are available
        agent_section = ""
        if agent_signals:
            metrics  = agent_performance_tracker.get_metrics_summary()
            consensus = agent_performance_tracker.consensus_score(agent_signals)
            agreement = agent_performance_tracker.agreement_fraction(agent_signals)
            agent_rows = []
            for name, (action, conf) in sorted(
                agent_signals.items(),
                key=lambda kv: metrics.get(kv[0], {}).get("score", 0),
                reverse=True,
            ):
                m      = metrics.get(name, {})
                score  = m.get("score", 0.5)
                wr     = m.get("win_rate", 0.0)
                sharpe = m.get("sharpe_ratio", 0.0)
                trades = m.get("trade_count", 0)
                agent_rows.append(
                    f"  • {name:<26} score={score:.2f}  win={wr:.0f}%  "
                    f"sharpe={sharpe:.2f}  trades={trades:<4}  → {action:<4} conf={conf:.2f}"
                )
            agent_section = (
                f"\n## Agent Performance Rankings (last 30 days)\n"
                + "\n".join(agent_rows)
                + f"\n  Weighted consensus : {consensus:+.3f}  |  "
                f"Agreement : {agreement:.0%}\n"
            )

        return (
            f"You are an expert quantitative trader. "
            f"A trained temporal CNN has produced the following signal for {symbol}.\n\n"
            f"## CNN Prediction\n"
            f"  Predicted 1-day return : {pred_return*100:+.2f}%\n"
            f"  Direction              : {direction.upper()}\n"
            f"  CNN confidence         : {cnn_conf:.0%}  "
            f"(this is the model's certainty in the predicted direction — do NOT invert it)\n\n"
            f"## Learned Source Weights  (trained from historical price outcomes)\n"
            f"{weight_lines}\n\n"
            f"## Current Source Scores\n"
            f"{score_lines}\n"
            f"  Composite score        : {composite_score:+.3f}\n"
            f"{agent_section}\n"
            f"## Stock\n"
            f"  Symbol: {symbol}   Price: ${price:.2f}\n\n"
            f"## Task\n"
            f"Follow these steps and then output JSON:\n"
            f"Step 1 — Agreement: Does the CNN direction agree with the composite score sign? "
            f"State yes or no and why.\n"
            f"Step 2 — Agents: Name the top-2 agents by performance score and their actions. "
            f"Do they support or contradict the CNN?\n"
            f"Step 3 — Decision: Choose BUY, SELL, or HOLD. "
            f"If CNN and composite conflict, prefer HOLD unless agent consensus is strong. "
            f"Set confidence to the CNN confidence value; only adjust it if agents strongly disagree.\n\n"
            f"Respond with ONLY valid JSON (no markdown, no extra text):\n"
            f'{{"action":"BUY"|"SELL"|"HOLD","confidence":<0.0-1.0>,"reasoning":"<2 sentences max>"}}'
        )

    async def _ollama_decision(self, prompt: str) -> Optional[Dict]:
        """Call local Ollama and parse JSON response. Returns None on any failure."""
        if not config.OLLAMA_MODEL:
            return None
        try:
            from openai import AsyncOpenAI
            client   = AsyncOpenAI(base_url=_OLLAMA_BASE, api_key="ollama")
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=config.OLLAMA_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=350,
                ),
                timeout=50.0,
            )
            text = (response.choices[0].message.content or "").strip()
            m    = re.search(r'\{[\s\S]*\}', text)
            if m:
                return json.loads(m.group())
        except asyncio.TimeoutError:
            logger.warning("CNNReasoningAgent: Ollama timed out (50s) — using rule-based fallback")
        except Exception as exc:
            logger.warning(f"CNNReasoningAgent: Ollama error — using rule-based fallback: {exc}")
        return None

    # ── main analysis loop ────────────────────────────────────────────────────

    async def analyze(self, market_context: Dict) -> List[Signal]:
        await self._ensure_model()

        prices  = {
            s: ctx.get("price", 0)
            for s, ctx in market_context.items()
            if isinstance(ctx, dict)
        }
        signals: List[Signal] = []

        for symbol, ctx in market_context.items():
            if not isinstance(ctx, dict):
                continue

            price     = ctx.get("price", 0) or 0
            composite = ctx.get("composite_signal", {}) or {}
            c_score   = composite.get("composite_score", 0.0) or 0.0
            sources   = composite.get("sources", {}) or {}

            current_scores = {
                name: (sources.get(key) or {}).get("score")
                for name, key in [
                    ("analyst_consensus",    "analyst_consensus"),
                    ("earnings_surprise",    "earnings_surprise"),
                    ("alpaca_news",          "alpaca_news"),
                    ("yahoo_news",           "yahoo_news"),
                    ("congressional_trades", "congressional_trades"),
                ]
            }

            # CNN inference from rolling window
            window = signal_history.get_recent_window(symbol, T=signal_cnn.T)
            if window is not None and signal_cnn.is_trained:
                try:
                    pred_return, direction, cnn_conf = signal_cnn.predict(window)
                except Exception as exc:
                    logger.debug(f"CNNReasoningAgent: predict error for {symbol}: {exc}")
                    pred_return, direction, cnn_conf = 0.0, "neutral", 0.3
            else:
                # Pre-training: derive a surrogate from composite score
                pred_return = c_score * 0.02
                direction   = (
                    "bull"    if c_score >  0.15
                    else "bear"    if c_score < -0.15
                    else "neutral"
                )
                cnn_conf = 0.3

            learned_weights = signal_cnn.get_learned_weights()

            # Collect other agents' current signals for this symbol (from market_context)
            other_agent_signals: Dict[str, tuple] = {}
            raw_agent_sigs = market_context.get("__agent_signals__", {})
            if isinstance(raw_agent_sigs, dict) and symbol in raw_agent_sigs:
                other_agent_signals = raw_agent_sigs[symbol]

            prompt   = self._build_prompt(
                symbol, price, pred_return, direction, cnn_conf,
                learned_weights, current_scores, c_score,
                agent_signals=other_agent_signals or None,
            )
            decision = await self._ollama_decision(prompt)

            # Fallback: rule-based when Ollama is unavailable
            if decision is None:
                action = (
                    "BUY"  if direction == "bull"
                    else "SELL" if direction == "bear"
                    else "HOLD"
                )
                decision = {
                    "action":     action,
                    "confidence": cnn_conf,
                    "reasoning":  (
                        f"CNN-only ({signal_cnn.device}): "
                        f"predicted {pred_return*100:+.1f}% 1D return ({direction})"
                    ),
                }

            action     = decision.get("action", "HOLD")
            confidence = float(decision.get("confidence") or cnn_conf)
            reasoning  = str(decision.get("reasoning", ""))

            portfolio_val = self.portfolio.get_total_value(prices)

            if action == "BUY" and confidence >= 0.50 and price > 0:
                max_alloc = portfolio_val * config.MAX_POSITION_SIZE
                shares    = max(1, int(max_alloc / price))
                signals.append(Signal(
                    symbol    = symbol,
                    action    = "BUY",
                    shares    = shares,
                    confidence = confidence,
                    reasoning  = f"CNN+Ollama: {reasoning}",
                    agent_name = self.name,
                ))
            elif action == "SELL" and symbol in self.portfolio.positions:
                shares = self.portfolio.positions[symbol].shares
                signals.append(Signal(
                    symbol    = symbol,
                    action    = "SELL",
                    shares    = shares,
                    confidence = confidence,
                    reasoning  = f"CNN+Ollama: {reasoning}",
                    agent_name = self.name,
                ))
            else:
                signals.append(Signal(
                    symbol    = symbol,
                    action    = "HOLD",
                    shares    = 0,
                    confidence = confidence,
                    reasoning  = f"CNN+Ollama HOLD: {reasoning}",
                    agent_name = self.name,
                ))

        return signals
