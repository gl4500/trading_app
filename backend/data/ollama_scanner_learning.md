# Ollama Scanner Learning Journal

## Role
Ollama is the **local free-tier scanner** — third in the pipeline after Claude (top candidates)
and Gemini (middle tier). It processes the lower-ranked pre-screened candidates using a local
open-source model with zero API token cost.

**Model:** Configured via `OLLAMA_MODEL` in config (default: `llama3.1:8b`)

## Signal Calibration Guidelines
- Use a **higher confidence threshold (>0.75)** compared to Claude — local models are less
  calibrated; only flag picks you are very sure about
- **Rely on composite_score and volume first** — RSI and MACD are secondary confirmation
- When signals conflict, default to **WATCH** rather than BUY/SELL
- Reject setups where `vol_ratio < 1.2` — insufficient volume confirmation for local model

## Decision Thresholds
| Signal | composite_score | confidence | RSI range |
|--------|----------------|------------|-----------|
| BUY    | > +0.20        | > 0.75     | 35–65     |
| SELL   | < -0.20        | > 0.75     | 35–65     |
| WATCH  | ±0.10 to ±0.20 | 0.55–0.74  | any       |
| SKIP   | < ±0.10        | any        | any       |

## Known Weaknesses
- Struggles with nuanced macro/geopolitical context — defer those to Claude
- May over-recommend on high-momentum names already covered by Claude/Gemini
- Avoid recommending within 2 days of known earnings dates unless composite_score > +0.40

## Observed Patterns
<!-- Add entries as you observe consistent patterns from Ollama scan results -->
<!-- Format: YYYY-MM-DD: [Symbol/Sector] — [Pattern description] — [Outcome] -->

<!-- Example:
2026-04-04: NVDA — High vol_ratio (>3×) + composite_score >0.30 → reliable BUY setup
2026-04-04: Energy sector — Ollama over-recommends on oil price news; require score >0.35
-->

## Performance Log
<!-- Track Ollama recommendation accuracy here to calibrate future thresholds -->
<!-- Format: YYYY-MM-DD: N recs made, N correct (>1% gain in 5 days), N wrong -->
