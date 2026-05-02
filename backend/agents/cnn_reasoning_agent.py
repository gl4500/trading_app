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
  • Requires ≥ MIN_TRAIN_SAMPLES rows with known forward outcomes
    (horizon configured by data.cnn_model.LABEL_HORIZON_COL — 5-day default)
  • Runs in a background thread via asyncio.to_thread so the trading loop
    is never blocked
"""
import asyncio
import json
import logging
import math
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
    "analyst_consensus":    30,
    "earnings_magnitude":   19,   # Task #22: was "earnings_surprise" (CNN channel renamed; |value|)
    "alpaca_news":          15,
    "yahoo_news":           10,
    "congressional_trades": 11,
    "iv_rv_spread":         15,
}

# Entropy pre-filter thresholds
# Skip Ollama when signal magnitude is below MIN_SIGNAL_MAGNITUDE AND CNN
# confidence is below MIN_CNN_CONF.  This avoids ~50s Ollama calls on cycles
# where all source scores are near zero (no information in the market context).
_MIN_SIGNAL_MAGNITUDE = 0.08   # mean absolute value of fresh source scores
_MIN_CNN_CONF         = 0.35   # CNN confidence below which we also require signal


def _signal_magnitude(scores: Dict[str, Optional[float]]) -> float:
    """
    Mean absolute value of available (non-None) source scores.
    Returns 0.0 when no scores are present.
    Used as a proxy for information content — low magnitude = low-entropy setup.
    """
    vals = [abs(v) for v in scores.values() if v is not None and not math.isnan(v)]
    return sum(vals) / len(vals) if vals else 0.0


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
        """Blocking training call — executed via asyncio.to_thread.

        Wrapped in the cross-app training mutex (Backlog 0.7, Option F).
        Only one app trains at a time across trading_app + polymarket_app
        because a single retrain consumes the GPU for 10–30 minutes; two
        concurrent retrains would either OOM or thrash. Mutex stale-PID
        reclaim handles a peer crashing mid-train.
        """
        from data.gpu_coord import acquire_training_mutex, release_training_mutex
        try:
            df = signal_history.get_training_data()
            if df.empty or len(df) < MIN_TRAIN_SAMPLES:
                logger.info(
                    f"CNNReasoningAgent: {len(df)} labelled samples available "
                    f"(need {MIN_TRAIN_SAMPLES}) — skipping training"
                )
                return
            X, y, w, t = build_training_windows(df)
            if len(X) < MIN_TRAIN_SAMPLES:
                return

            # Block until we hold the cross-app training mutex (or timeout
            # after 1h waiting on a live peer). Skip training if the mutex
            # is contended for too long — better to defer than fight.
            if not acquire_training_mutex(app_name="trading_app"):
                logger.warning(
                    "CNNReasoningAgent: could not acquire training mutex within timeout "
                    "— another app is training. Skipping this retrain."
                )
                return

            try:
                # Use sample weights so rows where top-performing agents were
                # confirmed correct have higher training influence
                signal_cnn.fit(X, y, t, epochs=80, batch_size=32, sample_weights=w)
                signal_cnn.save()
                summary = signal_cnn.training_summary()
                logger.info(
                    f"CNNReasoningAgent: training complete on {len(X)} samples | "
                    f"channels={X.shape[1]} | MSE={summary['final_mse']:.6f} | "
                    f"device={summary['device']} | learned weights: {summary['learned_weights']}"
                )
            finally:
                release_training_mutex(app_name="trading_app")
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
        catalysts:       Optional[List[Dict]] = None,
        macro_text:      str = "",
        portfolio_context: Optional[Dict] = None,
        horizon_label:   str = "5-day",
        risk_alert:      Optional[Dict] = None,
    ) -> str:
        # The display loop iterates two dicts with different naming conventions:
        #   • learned_weights uses CNN channel names — "earnings_magnitude" (Task #22)
        #   • current_scores uses LLM-source names    — "earnings_surprise" (signed value)
        # Both names refer to the same underlying source; tag both for consistency.
        _CONTEXT_ONLY_KEYS = {"earnings_surprise", "earnings_magnitude", "congressional_trades"}
        weight_lines = "\n".join(
            f"  • {name:<25} learned={w*100:5.1f}%  hardcoded={_HARDCODED[name]}%  "
            f"{'▲ elevated' if w*100 > _HARDCODED[name]+2 else ('▼ reduced' if w*100 < _HARDCODED[name]-2 else '≈ same')}"
            + (" [CONTEXT ONLY]" if name in _CONTEXT_ONLY_KEYS else "")
            for name, w in learned_weights.items()
        )
        score_lines = "\n".join(
            f"  • {name:<25} {f'{v:+.3f}' if v is not None else 'n/a'}"
            + (" [CONTEXT ONLY — stale data]" if name in _CONTEXT_ONLY_KEYS else "")
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

        # ── Catalyst section (symbol-specific first, then broad market) ──────────
        catalyst_section = ""
        if catalysts:
            sym_cats    = [c for c in catalysts if c.get("symbol") == symbol][:3]
            market_cats = [c for c in catalysts if not c.get("symbol") or c.get("symbol") != symbol][:3]
            lines = []
            for c in sym_cats:
                lines.append(
                    f"  [DIRECT] {c['headline']} "
                    f"(score={c.get('score', 0)}, {c.get('category', 'news')}, {c.get('date', '')})"
                )
            for c in market_cats:
                tag = f"[{c['symbol']}] " if c.get("symbol") else "[MARKET] "
                lines.append(
                    f"  {tag}{c['headline']} "
                    f"(score={c.get('score', 0)}, {c.get('category', 'news')}, {c.get('date', '')})"
                )
            if lines:
                catalyst_section = "\n## Overnight / Sentinel Catalysts\n" + "\n".join(lines) + "\n"

        macro_section = f"\n## Macro Context\n{macro_text}\n" if macro_text else ""

        # ── Risk alert (Backlog 0.5) ──────────────────────────────────────────
        # Forces the LLM to explicitly reconsider an open position when it has
        # dropped more than DAILY_REVIEW_PCT today. Defends against catalysts
        # arriving after market close (the agent might still see stale-positive
        # source scores while the price tells a different story).
        risk_alert_section = ""
        if risk_alert:
            today_open = risk_alert.get("today_open", 0.0)
            current    = risk_alert.get("current_price", 0.0)
            drop_pct   = risk_alert.get("drop_pct", 0.0)
            risk_alert_section = (
                f"\n## RISK ALERT\n"
                f"  This position has dropped {drop_pct*100:.1f}% TODAY "
                f"(open ${today_open:.2f} -> current ${current:.2f}).\n"
                f"  RE-EVALUATE EXPLICITLY: does the original BUY thesis still hold?\n"
                f"  If you decide to SELL, justify the action based on what changed today\n"
                f"  (catalysts, broader sector move, or the price action itself).\n"
                f"  The drop alone is not automatic grounds for SELL — but the position\n"
                f"  must clear a higher bar to remain HOLD when down this much in one day.\n"
            )

        # ── Portfolio & goal context ──────────────────────────────────────────
        portfolio_section = ""
        if portfolio_context:
            total      = portfolio_context.get("total_value", 0.0)
            cash       = portfolio_context.get("cash", 0.0)
            deployed   = portfolio_context.get("deployed_pct", 0.0)
            idle       = 100.0 - deployed
            ytd_pnl    = portfolio_context.get("ytd_pnl", 0.0)
            annual_goal = portfolio_context.get("annual_goal", 0.0)
            pace_diff  = portfolio_context.get("pace_diff", 0.0)
            pace_label = (
                f"ahead by ${pace_diff:,.0f}"
                if pace_diff >= 0
                else f"behind by ${abs(pace_diff):,.0f}"
            )
            portfolio_section = (
                f"\n## Portfolio Context\n"
                f"  Total value    : ${total:,.0f}\n"
                f"  Cash available : ${cash:,.0f}  ({deployed:.0f}% deployed, {idle:.0f}% idle)\n"
                f"  Annual goal    : ${annual_goal:,.0f}\n"
                f"  YTD P&L        : {'+' if ytd_pnl >= 0 else ''}${ytd_pnl:,.0f}  "
                f"(pace: {pace_label})\n"
            )

        return (
            f"You are an expert quantitative trader. "
            f"A trained temporal CNN has produced the following signal for {symbol}.\n\n"
            f"## CNN Prediction\n"
            f"  Predicted {horizon_label} return : {pred_return*100:+.2f}%\n"
            f"  Direction              : {direction.upper()}\n"
            f"  CNN confidence         : {cnn_conf:.0%}  "
            f"(this is the model's certainty in the predicted direction — do NOT invert it)\n\n"
            f"## Learned Source Weights  (trained from historical price outcomes)\n"
            f"{weight_lines}\n\n"
            f"## Current Source Scores\n"
            f"{score_lines}\n"
            f"  Composite score        : {composite_score:+.3f}\n"
            f"{agent_section}"
            f"{catalyst_section}"
            f"{macro_section}"
            f"{portfolio_section}"
            f"{risk_alert_section}\n"
            f"## Stock\n"
            f"  Symbol: {symbol}   Price: ${price:.2f}\n\n"
            f"## Task\n"
            f"Follow these steps and then output JSON:\n"
            f"Step 1 — Agreement: Does the CNN direction agree with the composite score sign? "
            f"Note: composite reflects fresh sources only (analyst_consensus + alpaca_news + yahoo_news) — "
            f"stale sources (earnings_surprise, congressional_trades) are context only and not included. "
            f"State yes or no and why.\n"
            f"Step 2 — Agents: Name the top-2 agents by performance score and their actions. "
            f"Do they support or contradict the CNN?\n"
            f"Step 3 — Catalysts: If any direct catalysts exist for {symbol}, do they support "
            f"or contradict the CNN direction? Factor this into your confidence.\n"
            f"Step 4 — Macro: Review the Macro Context above. "
            f"IMPORTANT: lines tagged [FRESH] are current (<=4 days old) and may inform confidence. "
            f"Lines tagged [STALE] are context only — do NOT use stale numbers to adjust confidence "
            f"because a rate decision or tariff shock last week makes them unreliable. "
            f"Using only FRESH data: does the Fed rate or breakeven inflation support or oppose "
            f"the CNN direction for {symbol}? "
            f"Flag headwinds only if backed by FRESH data (e.g. Fed funds above 5% = tight money = "
            f"headwind for growth stocks; breakeven inflation above 3% = rate-hike risk).\n"
            f"Step 5 — Decision: Choose BUY, SELL, or HOLD. "
            f"If CNN and composite conflict, prefer HOLD unless agent consensus is strong. "
            f"Set your OWN confidence (0.0–1.0) based on the AGREEMENT of evidence above: "
            f"CNN direction, composite score sign, agent consensus, FRESH catalysts and "
            f"FRESH macro. Strong agreement across all of these → high confidence (0.7–0.9). "
            f"Mixed or contradictory evidence → low confidence (0.3–0.5). "
            f"Treat the CNN confidence value as ONE input among many, NOT as a default — "
            f"a high CNN confidence with weak/contradictory agent and macro evidence should "
            f"NOT translate to a high final confidence. Stale macro data must not move the "
            f"confidence number in either direction. "
            f"For BUY signals, also set size_pct: the fraction of total portfolio value to deploy (0.0–1.0). "
            f"Consider signal strength, goal pace, and idle cash together — "
            f"strong signal + behind pace + ample idle cash → higher size_pct (0.10–0.15); "
            f"weak signal + ahead of pace → lower size_pct (0.02–0.05) or HOLD.\n\n"
            f"Respond with ONLY valid JSON (no markdown, no extra text):\n"
            f'{{"action":"BUY"|"SELL"|"HOLD","confidence":<0.0-1.0>,"size_pct":<0.0-1.0>,"reasoning":"<2 sentences max>"}}'
        )

    async def _ollama_decision(self, prompt: str) -> Optional[Dict]:
        """Call local Ollama and parse JSON response. Returns None on any failure.

        Wrapped in `gpu_coord.ollama_coord.acquire()` so:
          - At most one Ollama call from trading_app is in-flight at a time
            (per-app asyncio.Lock).
          - Cross-app priority: yields to polymarket_app when polymarket has
            higher exposure (Backlog 0.7 — only effective once polymarket is
            also wired into the same coord file).
        """
        if not config.OLLAMA_MODEL:
            return None
        try:
            from data.gpu_coord import ollama_coord
            from openai import AsyncOpenAI
            client   = AsyncOpenAI(base_url=_OLLAMA_BASE, api_key="ollama")
            _t0 = time.perf_counter()
            async with ollama_coord.acquire(expected_ms=50_000):
                response = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=config.OLLAMA_MODEL,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.3,
                        max_tokens=350,
                    ),
                    timeout=50.0,
                )
            _elapsed = time.perf_counter() - _t0
            if _elapsed > 15:
                logger.warning(f"[OLLAMA_LATENCY] app=trading_app caller=CNNReasoningAgent model={config.OLLAMA_MODEL} elapsed={_elapsed:.2f}s (SLOW)")
            else:
                logger.info(f"[OLLAMA_LATENCY] app=trading_app caller=CNNReasoningAgent model={config.OLLAMA_MODEL} elapsed={_elapsed:.2f}s")
            text = (response.choices[0].message.content or "").strip()
            m    = re.search(r'\{[\s\S]*\}', text)
            if m:
                return json.loads(m.group())
        except asyncio.TimeoutError:
            logger.warning("CNNReasoningAgent: Ollama timed out (50s) — using rule-based fallback")
        except Exception as exc:
            logger.warning(f"CNNReasoningAgent: Ollama error — using rule-based fallback: {exc}")
        return None

    # ── portfolio + goal context ──────────────────────────────────────────────

    def _build_portfolio_context(self, prices: Dict[str, float]) -> Dict:
        """
        Snapshot of current portfolio state and annual goal pace.
        Passed into _build_prompt so Ollama can reason about position sizing.
        """
        from datetime import date
        total_value  = self.portfolio.get_total_value(prices)
        cash         = self.portfolio.cash
        deployed     = max(0.0, total_value - cash)
        deployed_pct = (deployed / total_value * 100) if total_value > 0 else 0.0

        ytd_pnl = total_value - config.STARTING_CAPITAL

        # Estimate trading days elapsed this calendar year (252 trading days / 365 calendar days)
        year_start       = date(date.today().year, 1, 1)
        calendar_elapsed = (date.today() - year_start).days + 1
        trading_elapsed  = max(1, int(calendar_elapsed * 252 / 365))
        ytd_target       = config.ANNUAL_GOAL * trading_elapsed / 252
        pace_diff        = ytd_pnl - ytd_target

        return {
            "total_value":  total_value,
            "cash":         cash,
            "deployed_pct": deployed_pct,
            "ytd_pnl":      ytd_pnl,
            "annual_goal":  config.ANNUAL_GOAL,
            "pace_diff":    pace_diff,
        }

    # ── main analysis loop ────────────────────────────────────────────────────

    async def analyze(self, market_context: Dict) -> List[Signal]:
        await self._ensure_model()

        prices  = {
            s: ctx.get("price", 0)
            for s, ctx in market_context.items()
            if isinstance(ctx, dict)
        }
        signals: List[Signal] = []

        # Build portfolio + goal context once per cycle (shared across all symbols)
        portfolio_context = self._build_portfolio_context(prices)

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

            # Sentinel catalysts — symbol-specific first, then broad market (cap at 6)
            raw_catalysts = market_context.get("__overnight_catalysts__", [])
            catalysts: Optional[List[Dict]] = None
            if isinstance(raw_catalysts, list) and raw_catalysts:
                valid = [c for c in raw_catalysts if isinstance(c, dict)]
                catalysts = valid[:6] if valid else None

            # Macro context text (tactical + strategic summary)
            macro_text: str = market_context.get("__macro_context__", "") or ""

            # Daily-move risk gate (Backlog 0.5): if this is a held position
            # and it's down >= DAILY_REVIEW_PCT today, build a risk_alert dict
            # to inject into the Ollama prompt. Only fires for positions we
            # actually hold (no signal to alert about for unowned symbols).
            risk_alert: Optional[Dict] = None
            if symbol in self.portfolio.positions and price > 0:
                drop = self.portfolio.daily_drawdown_pct(symbol, price)
                if drop is not None and drop >= config.DAILY_REVIEW_PCT > 0:
                    risk_alert = {
                        "today_open":    self.portfolio.get_today_open(symbol) or 0.0,
                        "current_price": price,
                        "drop_pct":      drop,
                    }
                    logger.info(
                        f"CNNReasoningAgent [{symbol}]: daily-move risk alert "
                        f"(down {drop*100:.1f}% today, threshold {config.DAILY_REVIEW_PCT*100:.0f}%)"
                    )

            # ── Entropy pre-filter ────────────────────────────────────────────
            # Skip Ollama when signal magnitude is too low AND CNN is uncertain.
            # Saves ~50s Ollama calls on flat/noisy cycles with no real signal.
            # BUT: never skip when a risk alert is active — that's exactly the
            # moment the LLM safety net matters most.
            _magnitude = _signal_magnitude(current_scores)
            if (
                risk_alert is None
                and _magnitude < _MIN_SIGNAL_MAGNITUDE
                and cnn_conf < _MIN_CNN_CONF
            ):
                logger.debug(
                    f"CNNReasoningAgent [{symbol}]: entropy pre-filter — "
                    f"magnitude={_magnitude:.3f} conf={cnn_conf:.2f} → HOLD (skip Ollama)"
                )
                signals.append(Signal(
                    symbol     = symbol,
                    action     = "HOLD",
                    shares     = 0,
                    confidence = cnn_conf,
                    reasoning  = (
                        f"Entropy filter: signal magnitude {_magnitude:.2f} < "
                        f"{_MIN_SIGNAL_MAGNITUDE} — no actionable information"
                    ),
                    agent_name = self.name,
                ))
                continue

            prompt   = self._build_prompt(
                symbol, price, pred_return, direction, cnn_conf,
                learned_weights, current_scores, c_score,
                agent_signals=other_agent_signals or None,
                catalysts=catalysts,
                macro_text=macro_text,
                portfolio_context=portfolio_context,
                risk_alert=risk_alert,
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
                    "size_pct":   0.10,
                    "reasoning":  (
                        f"CNN-only ({signal_cnn.device}): "
                        f"predicted {pred_return*100:+.1f}% 5D return ({direction})"
                    ),
                }

            action     = decision.get("action", "HOLD")
            confidence = float(decision.get("confidence") or cnn_conf)
            reasoning  = str(decision.get("reasoning", ""))

            # WFE safety gate: block BUYs when the walk-forward CV reports a
            # negative mean_wfe (model is worse than predicting the mean).
            # mean_wfe is None when the model hasn't completed a walk-forward
            # fit yet — in that case we let the regime/confidence gates below
            # decide, preserving pre-walk-forward behavior. Once the first
            # walk-forward retrain runs, mean_wfe is populated and the gate
            # becomes active.
            mean_wfe_val = signal_cnn.mean_wfe
            if action == "BUY" and mean_wfe_val is not None and mean_wfe_val < 0.0:
                logger.info(
                    f"CNNReasoningAgent [{symbol}]: WFE gate blocked BUY "
                    f"(mean_wfe={mean_wfe_val:.4f} < 0)"
                )
                reasoning = (
                    f"WFE gate: original BUY blocked because mean_wfe="
                    f"{mean_wfe_val:.4f} < 0 (model has no measurable edge). "
                    f"Original reasoning: {reasoning}"
                )
                action = "HOLD"

            # Regime-aware buy gate: bear/high_vol markets require higher confidence
            from data.regime_detector import regime_detector
            _buy_threshold = 0.50 + regime_detector.get_confidence_gate()

            if action == "BUY" and confidence >= _buy_threshold and price > 0:
                # Use Ollama's size_pct (fraction of total portfolio value to deploy).
                # Clamp: floor at 2% (minimum meaningful), ceiling at MAX_POSITION_SIZE.
                # Final alloc also capped at 95% of available cash so we never overspend.
                portfolio_val = self.portfolio.get_total_value(prices)
                raw_pct  = decision.get("size_pct")
                size_pct = float(raw_pct) if raw_pct is not None else 0.10
                size_pct = max(0.02, min(config.MAX_POSITION_SIZE, size_pct))

                # Lone-wolf discount (Backlog 0.6): if fewer than
                # LONEWOLF_MIN_CORROBORATORS other agents are also signaling BUY
                # on this symbol, scale size by LONEWOLF_MULTIPLIER. Caps damage
                # when the CNN's noise-fitting tendency produces false positives
                # that the rest of the ensemble doesn't see.
                corroborators = sum(
                    1 for (a, c) in (other_agent_signals or {}).values()
                    if a == "BUY"
                )
                lonewolf_marker = ""
                if corroborators < config.LONEWOLF_MIN_CORROBORATORS:
                    pre_size = size_pct
                    size_pct = max(0.02, size_pct * config.LONEWOLF_MULTIPLIER)
                    lonewolf_marker = (
                        f" [LONE-WOLF: {corroborators} BUY corroborator(s) "
                        f"< {config.LONEWOLF_MIN_CORROBORATORS}, "
                        f"size_pct {pre_size:.0%} → {size_pct:.0%}]"
                    )
                    logger.info(
                        f"CNNReasoningAgent [{symbol}]: lone-wolf discount "
                        f"({corroborators} BUY corroborators) {pre_size:.0%} → {size_pct:.0%}"
                    )

                alloc    = min(portfolio_val * size_pct, self.portfolio.cash * 0.95)
                shares   = max(1, int(alloc / price))
                signals.append(Signal(
                    symbol    = symbol,
                    action    = "BUY",
                    shares    = shares,
                    confidence = confidence,
                    reasoning  = f"CNN+Ollama: {reasoning}{lonewolf_marker}",
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
