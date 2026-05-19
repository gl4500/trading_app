"""
XGB Reasoning Agent
-------------------
Combines a trained signal model (XGBoost in production via MODEL_BACKEND
selector; CNN when MODEL_BACKEND=cnn) with active LLM reasoning to produce
trading signals.

Renamed from CNNReasoningAgent in issue #75 — the agent has historically
used XGBoost via the ``data.signal_model.signal_model`` selector. The
``signal_cnn`` local alias below is intentional: it points at whichever
backend the selector resolves to, so naming the alias after the backend
would be just as misleading as the old class name.

Data flow per cycle
-------------------
  1. Ensure model is loaded / retrain if 24 h have elapsed and data is ready
  2. For each symbol pull the recent (5, T) rolling window from signal_history
  3. Model forward pass → (predicted_return, direction, model_confidence)
  4. Build a concise prompt that includes:
       • Model prediction + learned vs hardcoded weight comparison
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
from agents.xgb_decision import BuyContext, decide_buy
from config import config
from data.signal_history import signal_history
from data.cnn_model import build_training_windows, MIN_TRAIN_SAMPLES
from data.signal_model import signal_model as signal_cnn
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
# Skip Ollama when signal magnitude is below MIN_SIGNAL_MAGNITUDE AND model
# confidence is below MIN_MODEL_CONF.  This avoids ~50s Ollama calls on cycles
# where all source scores are near zero (no information in the market context).
_MIN_SIGNAL_MAGNITUDE = 0.08   # mean absolute value of fresh source scores
_MIN_MODEL_CONF       = 0.35   # model confidence below which we also require signal


def _signal_magnitude(scores: Dict[str, Optional[float]]) -> float:
    """
    Mean absolute value of available (non-None) source scores.
    Returns 0.0 when no scores are present.
    Used as a proxy for information content — low magnitude = low-entropy setup.
    """
    vals = [abs(v) for v in scores.values() if v is not None and not math.isnan(v)]
    return sum(vals) / len(vals) if vals else 0.0


class XGBReasoningAgent(BaseAgent):
    """
    Trading agent driven by a learned signal model (XGBoost/CNN selector) +
    Ollama active reasoning.

    Primary  : Ollama (local, free, zero API cost)
    Secondary: simple rule-based fallback (direction → action)
    """

    def __init__(self):
        super().__init__(
            name="XGBReasoningAgent",
            strategy_description=(
                "Learned signal model (XGBoost/CNN selector) + Ollama active reasoning"
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
                    f"XGBReasoningAgent: {len(df)} labelled samples available "
                    f"(need {MIN_TRAIN_SAMPLES}) — skipping training"
                )
                return
            X, y, w, t = build_training_windows(df)
            if len(X) < MIN_TRAIN_SAMPLES:
                return

            # Use sample weights so rows where top-performing agents were
            # confirmed correct have higher training influence
            signal_cnn.fit(X, y, t, epochs=80, batch_size=32, sample_weights=w)
            signal_cnn.save()
            summary = signal_cnn.training_summary()
            logger.info(
                f"XGBReasoningAgent: training complete on {len(X)} samples | "
                f"channels={X.shape[1]} | MSE={summary['final_mse']:.6f} | "
                f"device={summary['device']} | learned weights: {summary['learned_weights']}"
            )
        except Exception as exc:
            logger.error(f"XGBReasoningAgent: training failed: {exc}", exc_info=True)

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
        """Call local Ollama and parse JSON response. Returns None on any failure."""
        if not config.OLLAMA_MODEL:
            return None
        try:
            from openai import AsyncOpenAI
            client   = AsyncOpenAI(base_url=_OLLAMA_BASE, api_key="ollama")
            _t0 = time.perf_counter()
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
                logger.warning(f"[OLLAMA_LATENCY] app=trading_app caller=XGBReasoningAgent model={config.OLLAMA_MODEL} elapsed={_elapsed:.2f}s (SLOW)")
            else:
                logger.info(f"[OLLAMA_LATENCY] app=trading_app caller=XGBReasoningAgent model={config.OLLAMA_MODEL} elapsed={_elapsed:.2f}s")
            text = (response.choices[0].message.content or "").strip()
            m    = re.search(r'\{[\s\S]*\}', text)
            if m:
                return json.loads(m.group())
        except asyncio.TimeoutError:
            logger.warning("XGBReasoningAgent: Ollama timed out (50s) — using rule-based fallback")
        except Exception as exc:
            logger.warning(f"XGBReasoningAgent: Ollama error — using rule-based fallback: {exc}")
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

    # ── per-symbol context parsing ───────────────────────────────────────────

    def _extract_symbol_context(
        self,
        symbol: str,
        ctx: Dict,
        market_context: Dict,
    ) -> Dict:
        """
        Parse the per-symbol slice of ``market_context`` into the bundle of
        primitives ``analyze()`` needs to drive the rest of the pipeline:

          • price, composite score, sources → current_scores dict
          • other agents' signals for this symbol
          • catalysts (capped at 6, symbol-specific first)
          • macro context text

        Pure dict-in/dict-out so the inner loop in ``analyze()`` stays a
        thin orchestrator.
        """
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

        # Other agents' current signals for this symbol
        other_agent_signals: Dict[str, tuple] = {}
        raw_agent_sigs = market_context.get("__agent_signals__", {})
        if isinstance(raw_agent_sigs, dict) and symbol in raw_agent_sigs:
            other_agent_signals = raw_agent_sigs[symbol]

        # Sentinel catalysts — symbol-specific first, then broad market (cap 6)
        raw_catalysts = market_context.get("__overnight_catalysts__", [])
        catalysts: Optional[List[Dict]] = None
        if isinstance(raw_catalysts, list) and raw_catalysts:
            valid = [c for c in raw_catalysts if isinstance(c, dict)]
            catalysts = valid[:6] if valid else None

        # Macro context text (tactical + strategic summary)
        macro_text: str = market_context.get("__macro_context__", "") or ""

        return {
            "price":               price,
            "c_score":             c_score,
            "current_scores":      current_scores,
            "other_agent_signals": other_agent_signals,
            "catalysts":           catalysts,
            "macro_text":          macro_text,
        }

    # ── Model inference + Ollama fallback ────────────────────────────────────

    def _run_cnn_inference(self, symbol: str, c_score: float) -> tuple:
        """
        Single-symbol model forward pass with the Stage-3b ensemble-uncertainty
        downscale on top. When the model is not yet trained or no recent window
        is available, derives a surrogate (pred_return, direction, model_conf)
        from the composite score so analyze() always has a usable estimate.

        Method name kept as ``_run_cnn_inference`` for test backwards-compat —
        the underlying call goes through the ``signal_cnn`` selector alias
        which resolves to whichever backend MODEL_BACKEND points at.

        Returns ``(pred_return, direction, model_conf)``.
        """
        window = signal_history.get_recent_window(symbol, T=signal_cnn.T)
        if window is None or not signal_cnn.is_trained:
            # Pre-training: derive a surrogate from composite score
            pred_return = c_score * 0.02
            direction = (
                "bull"    if c_score >  0.15
                else "bear"    if c_score < -0.15
                else "neutral"
            )
            return pred_return, direction, 0.3

        try:
            pred_return, direction, cnn_conf = signal_cnn.predict(window)
        except Exception as exc:
            logger.debug(f"XGBReasoningAgent: predict error for {symbol}: {exc}")
            pred_return, direction, cnn_conf = 0.0, "neutral", 0.3

        # Ensemble-uncertainty downscale (Stage 3b). When the XGBoost backend
        # has K bootstrapped boosters on disk (signal_xgb_b{0..K-1}.json),
        # discount cnn_conf by cross-booster disagreement. Calibration check
        # showed rho(std, |residual|) = +0.215 — high std reliably predicts
        # low accuracy. No-op when ensemble files absent.
        if hasattr(signal_cnn, "ensemble_predict"):
            try:
                ens_mean, ens_std, ens_n = signal_cnn.ensemble_predict(window)
                if ens_n > 0 and ens_std > 0 and abs(ens_mean) > 1e-6:
                    # Relative uncertainty: std / |mean|. At
                    # std == 0.5 * |mean| the multiplier is 0 (system says
                    # "I don't know"). Linear scale in between.
                    rel_uncert = ens_std / abs(ens_mean)
                    uncert_mult = max(0.0, 1.0 - 2.0 * rel_uncert)
                    cnn_conf *= uncert_mult
            except Exception as exc:
                logger.debug(
                    f"XGBReasoningAgent: ensemble_predict error for "
                    f"{symbol}: {exc}"
                )

        return pred_return, direction, cnn_conf

    def _rule_based_fallback(
        self,
        direction: str,
        cnn_conf: float,
        pred_return: float,
    ) -> Dict:
        """
        Model-only rule-based fallback used when Ollama is unavailable
        (``_ollama_decision`` returned ``None``). Maps model direction to a
        BUY/SELL/HOLD action and packages it in the same dict shape Ollama
        would return so the rest of analyze() stays uniform.
        """
        action = (
            "BUY"  if direction == "bull"
            else "SELL" if direction == "bear"
            else "HOLD"
        )
        return {
            "action":     action,
            "confidence": cnn_conf,
            "size_pct":   0.10,
            "reasoning":  (
                f"CNN-only ({signal_cnn.device}): "
                f"predicted {pred_return*100:+.1f}% 5D return ({direction})"
            ),
        }

    def _build_risk_alert(self, symbol: str, price: float) -> Optional[Dict]:
        """
        Daily-move risk gate (Backlog 0.5): when ``symbol`` is currently held
        and the position is down at least ``config.DAILY_REVIEW_PCT`` today,
        return an alert dict the Ollama prompt builder can splice in. Returns
        ``None`` (no alert) when the position isn't held, price is invalid,
        or today's drop is under threshold (or DAILY_REVIEW_PCT == 0, which
        disables the feature).
        """
        if symbol not in self.portfolio.positions or price <= 0:
            return None
        drop = self.portfolio.daily_drawdown_pct(symbol, price)
        if drop is None or not (drop >= config.DAILY_REVIEW_PCT > 0):
            return None
        logger.info(
            f"XGBReasoningAgent [{symbol}]: daily-move risk alert "
            f"(down {drop*100:.1f}% today, threshold {config.DAILY_REVIEW_PCT*100:.0f}%)"
        )
        return {
            "today_open":    self.portfolio.get_today_open(symbol) or 0.0,
            "current_price": price,
            "drop_pct":      drop,
        }

    # ── post-Ollama safety gates ─────────────────────────────────────────────

    def _apply_wfe_gate(
        self,
        symbol: str,
        action: str,
        reasoning: str,
    ) -> tuple:
        """
        Walk-forward efficiency gate. Demotes BUY → HOLD when the model's
        ``mean_wfe`` is populated and negative (model is worse than
        predicting the mean). When ``mean_wfe`` is ``None`` (no walk-forward
        fit yet), the gate is a no-op and lower-level gates decide.

        Returns ``(possibly-new-action, possibly-updated-reasoning)``.
        """
        if action != "BUY":
            return action, reasoning
        mean_wfe_val = signal_cnn.mean_wfe
        if mean_wfe_val is None or mean_wfe_val >= 0.0:
            return action, reasoning
        logger.info(
            f"XGBReasoningAgent [{symbol}]: WFE gate blocked BUY "
            f"(mean_wfe={mean_wfe_val:.4f} < 0)"
        )
        new_reasoning = (
            f"WFE gate: original BUY blocked because mean_wfe="
            f"{mean_wfe_val:.4f} < 0 (model has no measurable edge). "
            f"Original reasoning: {reasoning}"
        )
        return "HOLD", new_reasoning

    def _apply_max_positions_gate(
        self,
        symbol: str,
        action: str,
        reasoning: str,
    ) -> tuple:
        """
        Max-open-positions cap (PR #76). Demotes BUY → HOLD when we already
        hold ``CNN_MAX_OPEN_POSITIONS`` distinct symbols and ``symbol`` is
        not already among them. Asymmetric: SELLs always pass, and averaging
        into already-held symbols still passes.

        Returns ``(possibly-new-action, possibly-updated-reasoning)``.
        """
        if action != "BUY":
            return action, reasoning
        held_symbols = {
            sym for sym, pos in self.portfolio.positions.items()
            if pos.shares > 0
        }
        if (
            len(held_symbols) < config.CNN_MAX_OPEN_POSITIONS
            or symbol in held_symbols
        ):
            return action, reasoning
        logger.info(
            f"XGBReasoningAgent [{symbol}]: max-open-positions gate "
            f"blocked BUY ({len(held_symbols)} held >= cap "
            f"{config.CNN_MAX_OPEN_POSITIONS}, and {symbol} is new)"
        )
        new_reasoning = (
            f"max-open-positions gate: BUY blocked on new symbol — "
            f"{len(held_symbols)} positions already held vs cap "
            f"{config.CNN_MAX_OPEN_POSITIONS}. Existing holdings "
            f"must resolve (or merge) before opening new ones. "
            f"Original reasoning: {reasoning}"
        )
        return "HOLD", new_reasoning

    # ── pre-Ollama filter ────────────────────────────────────────────────────

    def _entropy_prefilter_signal(
        self,
        symbol: str,
        current_scores: Dict[str, Optional[float]],
        cnn_conf: float,
        risk_alert: Optional[Dict],
    ) -> Optional[Signal]:
        """
        Shannon-style entropy pre-filter. Returns a HOLD ``Signal`` (which the
        caller should ``append`` then ``continue``) when:

          • no risk_alert is active (risk_alert always wins — see Backlog 0.5),
          • mean |source score| < _MIN_SIGNAL_MAGNITUDE, AND
          • cnn_conf < _MIN_MODEL_CONF

        Returns ``None`` when the symbol passes the filter and should proceed
        to the Ollama call. Wrapped in a method so the threshold logic is
        unit-testable in isolation and so ``analyze()`` reads as a thin
        orchestrator.
        """
        if risk_alert is not None:
            return None
        magnitude = _signal_magnitude(current_scores)
        if magnitude >= _MIN_SIGNAL_MAGNITUDE or cnn_conf >= _MIN_MODEL_CONF:
            return None
        logger.debug(
            f"XGBReasoningAgent [{symbol}]: entropy pre-filter — "
            f"magnitude={magnitude:.3f} conf={cnn_conf:.2f} → HOLD (skip Ollama)"
        )
        return Signal(
            symbol     = symbol,
            action     = "HOLD",
            shares     = 0,
            confidence = cnn_conf,
            reasoning  = (
                f"Entropy filter: signal magnitude {magnitude:.2f} < "
                f"{_MIN_SIGNAL_MAGNITUDE} — no actionable information"
            ),
            agent_name = self.name,
        )

    # ── per-symbol branch helpers ────────────────────────────────────────────

    def _handle_buy(
        self,
        symbol: str,
        price: float,
        pred_return: float,
        confidence: float,
        reasoning: str,
        other_agent_signals: Dict[str, tuple],
        prices: Dict[str, float],
    ) -> Signal:
        """
        BUY branch: build a ``BuyContext`` and delegate to ``decide_buy`` —
        the single source of truth for confidence/regime/uPnL/trail/Kelly
        gating + sizing (shared with the MC backtester). Returns either:

          • a BUY ``Signal`` when ``decide_buy`` approves, with shares capped
            to 95% of cash and a LONE-WOLF marker appended to the reasoning
            when ``n_corroborators < LONEWOLF_MIN_CORROBORATORS``, OR
          • a HOLD ``Signal`` with a gate-labelled reason when ``decide_buy``
            blocks (gate label substrings preserve existing test/log
            assertions).
        """
        from data.regime_detector import regime_detector
        corroborators = sum(
            1 for (a, _c) in (other_agent_signals or {}).values()
            if a == "BUY"
        )
        portfolio_val = self.portfolio.get_total_value(prices)
        ctx = BuyContext(
            symbol=symbol,
            model_pred_return=float(pred_return),
            model_pred_direction="up",                 # Ollama already returned BUY
            model_confidence=float(confidence),        # Ollama's confidence
            regime=regime_detector.get_regime()[0],
            portfolio_unpnl_frac=self.portfolio.unpnl_frac(prices),
            n_corroborators=int(corroborators),
            in_trail_cooldown=self._in_trail_cooldown(),
            current_price=float(price),
            cash_available=float(self.portfolio.cash),
            portfolio_value=float(portfolio_val),
            kelly_fraction=float(self.portfolio.kelly_fraction()),
        )
        buy_decision = decide_buy(ctx, config)

        if buy_decision.action == "HOLD":
            # Preserve the historical gate-name substrings so existing
            # log/test assertions still match the HOLD reasoning.
            reason_lower = buy_decision.reason.lower()
            if reason_lower.startswith("upnl"):
                gate_label = "uPnL drawdown gate"
            elif "regime" in reason_lower:
                gate_label = "regime gate"
            elif reason_lower.startswith("conf"):
                gate_label = "confidence gate"
            elif "trail" in reason_lower:
                gate_label = "trail cool-down gate"
            elif "under-funded" in reason_lower:
                gate_label = "under-funded gate"
            else:
                gate_label = "decide_buy"
            logger.info(
                f"XGBReasoningAgent [{symbol}]: {gate_label} blocked BUY "
                f"({buy_decision.reason})"
            )
            return Signal(
                symbol     = symbol,
                action     = "HOLD",
                shares     = 0,
                confidence = confidence,
                reasoning  = (
                    f"{gate_label}: BUY blocked — {buy_decision.reason}. "
                    f"Original reasoning: {reasoning}"
                ),
                agent_name = self.name,
            )

        # BUY passed: cap shares so we never overspend 95% of cash.
        shares = buy_decision.shares
        max_cash_shares = int((self.portfolio.cash * 0.95) / price) if price > 0 else 0
        if max_cash_shares >= 1:
            shares = max(1, min(shares, max_cash_shares))

        # Preserve the LONE-WOLF marker substring (existing tests assert
        # on it). decide_buy applies the lone-wolf size shrink internally;
        # we just surface that fact in the reasoning text.
        lonewolf_marker = ""
        if corroborators < config.LONEWOLF_MIN_CORROBORATORS:
            lonewolf_marker = (
                f" [LONE-WOLF: {corroborators} BUY corroborator(s) "
                f"< {config.LONEWOLF_MIN_CORROBORATORS}]"
            )
            logger.info(
                f"XGBReasoningAgent [{symbol}]: lone-wolf discount "
                f"({corroborators} BUY corroborators)"
            )

        return Signal(
            symbol     = symbol,
            action     = "BUY",
            shares     = shares,
            confidence = buy_decision.sized_confidence,
            reasoning  = (
                f"CNN+Ollama: {reasoning}; {buy_decision.reason}"
                f"{lonewolf_marker}"
            ),
            agent_name = self.name,
        )

    def _handle_sell(
        self,
        symbol: str,
        confidence: float,
        reasoning: str,
    ) -> Optional[Signal]:
        """
        SELL branch: emit a SELL Signal for the full position when held.
        Returns None when no position exists for ``symbol`` — caller should
        fall through to HOLD (preserves prior behavior where SELL on an
        unowned symbol degenerated to the else-HOLD branch).
        """
        if symbol not in self.portfolio.positions:
            return None
        shares = self.portfolio.positions[symbol].shares
        return Signal(
            symbol     = symbol,
            action     = "SELL",
            shares     = shares,
            confidence = confidence,
            reasoning  = f"CNN+Ollama: {reasoning}",
            agent_name = self.name,
        )

    def _handle_hold(
        self,
        symbol: str,
        confidence: float,
        reasoning: str,
    ) -> Signal:
        """
        HOLD branch: emit a HOLD Signal (zero shares) for downstream visibility.
        Used both for an explicit Ollama HOLD and as the catch-all for SELL on
        unowned symbols / BUY with non-positive price.
        """
        return Signal(
            symbol     = symbol,
            action     = "HOLD",
            shares     = 0,
            confidence = confidence,
            reasoning  = f"CNN+Ollama HOLD: {reasoning}",
            agent_name = self.name,
        )

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

            sym_ctx = self._extract_symbol_context(symbol, ctx, market_context)
            price               = sym_ctx["price"]
            c_score             = sym_ctx["c_score"]
            current_scores      = sym_ctx["current_scores"]
            other_agent_signals = sym_ctx["other_agent_signals"]
            catalysts           = sym_ctx["catalysts"]
            macro_text          = sym_ctx["macro_text"]

            # Model forward pass + ensemble-uncertainty downscale (Stage 3b).
            pred_return, direction, cnn_conf = self._run_cnn_inference(symbol, c_score)
            learned_weights = signal_cnn.get_learned_weights()

            # Daily-move risk gate (Backlog 0.5) — see _build_risk_alert.
            risk_alert: Optional[Dict] = self._build_risk_alert(symbol, price)

            # ── Entropy pre-filter ────────────────────────────────────────────
            # Skip Ollama when signal magnitude is too low AND model is uncertain.
            # Saves ~50s Ollama calls on flat/noisy cycles with no real signal.
            # risk_alert always bypasses the filter — see _entropy_prefilter_signal.
            entropy_signal = self._entropy_prefilter_signal(
                symbol, current_scores, cnn_conf, risk_alert
            )
            if entropy_signal is not None:
                signals.append(entropy_signal)
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
                decision = self._rule_based_fallback(direction, cnn_conf, pred_return)

            action     = decision.get("action", "HOLD")
            confidence = float(decision.get("confidence") or cnn_conf)
            reasoning  = str(decision.get("reasoning", ""))

            # Safety gates: WFE then max-open-positions. Each demotes a
            # would-be BUY to HOLD with an augmented reasoning string, but
            # leaves SELL/HOLD untouched. See _apply_*_gate methods.
            action, reasoning = self._apply_wfe_gate(symbol, action, reasoning)
            action, reasoning = self._apply_max_positions_gate(symbol, action, reasoning)

            if action == "BUY" and price > 0:
                signals.append(self._handle_buy(
                    symbol, price, pred_return, confidence, reasoning,
                    other_agent_signals, prices,
                ))
            elif action == "SELL":
                sell_sig = self._handle_sell(symbol, confidence, reasoning)
                if sell_sig is not None:
                    signals.append(sell_sig)
                else:
                    # SELL on unowned symbol degrades to HOLD (preserves
                    # historical behavior of the prior catch-all else branch).
                    signals.append(self._handle_hold(symbol, confidence, reasoning))
            else:
                signals.append(self._handle_hold(symbol, confidence, reasoning))

        return signals
