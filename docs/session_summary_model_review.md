# Session Summary — Model Review & Improvement Loop (2026-06-14 → 06-21)

Handoff doc for multi-agent work. Scope: **trading_app only** (NOT polymarket_app). Self-paced
`/loop` R&D investigating whether the XGBReasoningAgent's AI/model edge is real and improvable.

## TL;DR

The investigation that started as "is the model broken? (negative WFE)" **resolved benign**:
- The **XGB model + its gates is net profitable: +$12.5K realized, 64% bull win-rate**, despite
  `mean_wfe = −0.035`. WFE was a *magnitude-metric artifact* mis-measuring a marginal-but-real
  long-momentum edge that the gates monetize in bull and avoid in bear. **Model not broken.**
- **Regime-gating the model further is exhausted.** The one robust regime effect (momentum reverses
  in bear) is already gated (+0.15 bear / +0.20 high_vol on the BUY confidence threshold).
- **One genuine high-EV lever remains (H12, operator decision):** the *non-gated* rule-based agents
  (Momentum, MeanReversion, Tech, HistTrends) bleed **−$19.3K in bear** with no regime protection.
  Port the XGB agent's proven bear gate to them via a shared `BaseAgent` entry gate.

## Starting question (operator)
"trading app — is the AI analysis really impacting the trading?" → led into a model-edge audit.
Answer: AI/LLM agents (Claude, Sentiment, Ollama, XGB) trade their own books on real LLM calls
(`OLLAMA_ONLY_MODE=0`), but are ~17% of trade volume; rule-based agents dominate count. The XGB
agent's LLM decisions are heavily gated (WFE + regime + Kelly + decide_buy).

## Iteration log (full detail in the ledger)
| # | Hypothesis | Verdict |
|---|---|---|
| H1 | Walk-forward embargo (1 bar) ≪ 10-day label → leakage causes negative WFE | **Falsified as root cause** — leakage only 0.5–1.6% of train rows. Real but minor bug. |
| H2/H7 | `mean_wfe` gate is over-conservative; recent fold is positive; gate on rank not magnitude | **Falsified / self-corrected** — read stale May-vintage experiment artifacts as "live regime." Production June fold is genuinely −0.07 IC. Gate is appropriate. |
| H9 | Edge is regime-dependent (bull good, neutral bad) | Supported weakly (n=1 transition). |
| H10 | bull↔+edge / neutral↔−edge holds across history | **Reframed** — 10-yr data: only robust effect is **bear → −0.064 IC (t≈−4.6)**; bull weak+, neutral≈0. Neutral-gate idea dropped. |
| H11 | Trades leak through in bear despite the +0.15 penalty | **Falsified for XGB** (94% of BUYs in bull). Surfaced the −$19.3K bleed in **non-gated** agents. |
| H12 | Port bear gate to rule-based agents recovers much of −$19.3K | **Open — highest-EV; operator decision + TDD.** |

## Key evidence (reproducible offline, no live-backend contention)
- Realized PnL by regime (trading.db × SPY regime): bull +$71.9K (58% win) · neutral +$0.3K · **bear
  −$19.3K (37% win, 244 closes)** · high_vol +$3.4K.
- XGB BUYs by regime: bull 194 / bear 8 / neutral 3 / high_vol 2.
- 10-yr cross-sectional IC(20d momentum → fwd 10d) by regime: bear −0.064 / neutral −0.006 /
  high_vol +0.001 / bull +0.007.
- Live model `signal_xgb.json` (retrained 06-17): fold0 (May) WFE+0.046/IC+0.151, fold1 (late May)
  +0.092/+0.281, fold2 (June) −0.259/−0.070, inverted calibration.

## Open items for the operator / next agent
1. **H12 (recommended next):** shared `BaseAgent` regime entry gate for the non-gated agents.
   Design choices: confidence-penalty (mirror +0.15/+0.20) vs hard participation-off in bear. Needs
   TDD + a backend restart. Changes live behavior for several agents → operator approval first.
2. **httpx log noise (minor):** stooq 404s in logs are transient throttling on a *fallback* source,
   handled gracefully. Optional one-line fix in `main.py` after `logging.basicConfig`:
   `logging.getLogger("httpx").setLevel(logging.WARNING)` (+ `httpcore`). Needs a test + restart.
3. The embargo bug (H1) is real but minor — a time-based embargo ≥ `LABEL_HORIZON_DAYS` would make
   walk-forward metrics honest. Low priority.

## Guardrails honored this session
- Live backend running on :8000 — all R&D was **offline/read-only** against parquet + db + saved
  model files. No production model files touched, no restart, no live-config change.
- No code changes made (all findings are analysis); any H12/httpx change needs TDD per the repo
  contract + operator greenlight.

## Pointers
- **Full ledger (newest on top):** `trading_app/docs/model_improvement_ledger.md`
- **Memory atom:** `~/.claude/projects/C--Users-gl450/memory/trading_app_model_improvement_ledger.md`
- Architecture: `trading_app_architecture` memory · XGB agent: `backend/agents/xgb_reasoning_agent.py`
  · gate: `backend/agents/xgb_decision.py` + `data/regime_detector.py` · eval harness:
  `data/cnn_evaluation.py` (`walkforward_folds`, `embargo_bars`).
