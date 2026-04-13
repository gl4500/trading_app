# CNN Decision Tree & Learning Cycle

**File:** `backend/data/cnn_model.py` + `backend/agents/cnn_reasoning_agent.py`
**Last updated:** 2026-04-13

---

## Architecture at a Glance

```
Signal History (Parquet) ──► CNN Training (24h cycle) ──► Saved Weights (.pt)
        │                                                          │
        │                                                          ▼
        └─────────────────────────────────────────► CNN Inference (every cycle)
                                                              │
                                                              ▼
                                                    Ollama 5-Step Reasoning
                                                              │
                                                              ▼
                                                     BUY / SELL / HOLD Signal
                                                              │
                                                              ▼
                                                   Trade Outcome → Labeled Row
                                                              │
                                                              └──► back to Training
```

---

## Part 1 — Learning Cycle (continuous background)

### Step A — Snapshot Recording (every ~60 seconds)

```
signal_aggregator.py computes 5 source scores per symbol:
  analyst_consensus    earnings_surprise*   alpaca_news
  yahoo_news           congressional_trades*

  * CONTEXT_ONLY_SOURCES — passed to LLM as background but excluded from composite
  → composite_score = weighted sum of FRESH sources only
    (analyst_consensus + alpaca_news + yahoo_news, renormalised to 1.0)

signal_history.record_snapshot()
  Appends one row to  data/history/{SYMBOL}.parquet

  ┌────────────────────────────────────────────────────────────────────┐
  │ symbol │ timestamp │ 5 scores │ composite │ price │ return_1d=NaN  │
  └────────────────────────────────────────────────────────────────────┘

After all agents run:
signal_history.record_agent_signals()
  Updates that row with:
    agent_consensus  — performance-weighted directional vote  (-1.0 to +1.0)
    agent_agreement  — fraction of agents that agree          ( 0.0 to  1.0)
```

### Step B — Outcome Labeling (fills in ground truth as time passes)

```
signal_history.update_outcomes()

  Rows >= 24h old:
    return_1d = (current_price - snapshot_price) / snapshot_price

  Rows >= 5d old:
    return_5d = same formula

signal_history.update_top_agent_correct()

  Rows >= 24h old where agent_consensus is set:
    top_agent_correct = 1.0   if consensus direction == actual return direction
    top_agent_correct = 0.0   if they disagreed
```

### Step C — CNN Retraining (every 24 hours)

```
CNNReasoningAgent._ensure_model()
  Checks: has it been 24h since last train? Are there >= 30 labeled rows?
  If yes → asyncio.to_thread(_train_blocking)   [non-blocking background thread]

_train_blocking():

  1. signal_history.get_training_data()
       Loads ALL .parquet files from data/history/
       Keeps only rows where return_1d is NOT NaN

  2. build_training_windows(df, T=10)

       For each symbol, for each labeled row i:
         window = rows[max(0, i-9) : i+1]    shape: up to (10, 7)
         if fewer than 10 rows → zero-pad the front

       OUTPUT ARRAYS:
         X  shape (N, 7, 10)  float32   7 channels × 10 timesteps
         y  shape (N,)        float32   1-day return, clipped to ±20%
         w  shape (N,)        float32   sample weights (see below)

       7 INPUT CHANNELS:
         0  analyst_score       (analyst consensus)
         1  earnings_score      (earnings surprise)
         2  alpaca_score        (Alpaca news sentiment)
         3  yahoo_score         (Yahoo Finance news)
         4  congress_score      (congressional trades)
         5  agent_consensus     (performance-weighted agent vote)
         6  agent_agreement     (fraction of agents agreeing)

       SAMPLE WEIGHTS:
         top_agent_correct = 1.0  →  weight = 1.0  (reward correct calls)
         top_agent_correct = 0.0  →  weight = 0.5  (penalise wrong calls)
         unknown / NaN           →  weight = 0.75 (neutral)

  3. 80/20 Train / Validation Split
       n_val   = max(5, int(N × 0.20))
       n_train = N - n_val
       Split is random (torch.randperm) to avoid time-ordering bias

  4. signal_cnn.fit()
       Optimizer : Adam  lr=3e-4
       Epochs    : 80
       Batch     : 32
       Loss      : weighted MSE (per-sample weights applied)
       Grad clip : max_norm=1.0

       Each epoch:
         TRAIN pass  → forward → weighted MSE → backward → optimizer step
         VAL pass    → forward → MSE  (no gradient, no weight)
         Both losses recorded for every epoch

  5. _diagnose(train_mse, val_mse, ratio=val/train)
       train_mse < 1e-5          → OVERFIT_MEMORIZING  (memorised training data)
       ratio > 3.0               → OVERFIT             (not generalising)
       both > 0.005              → UNDERFIT            (not learning signal)
       otherwise                 → OK

  6. signal_cnn.save()
       Writes data/models/signal_cnn.pt
       Saved fields: arch="glu"  state_dict  opt_state
                     train_loss[]  val_loss[]  n_train  n_val
                     n_channels  trained  train_ts
```

---

## Part 2 — CNN Architecture (GLU-Gated)

```
INPUT  (batch, 7, 10)    7 channels × 10 timesteps

┌─────────────────────────────────────────────────────────────────┐
│  GatedConv1d  (7 → 16, kernel=3, padding=1)                     │
│                                                                 │
│    Two parallel Conv1d layers run on the same input:            │
│      main path:  Conv1d(7, 16, k=3)                             │
│      gate path:  Conv1d(7, 16, k=3) → sigmoid                  │
│                                                                 │
│    output = main(x)  ×  sigmoid(gate(x))                        │
│                                                                 │
│    The gate outputs 0–1 per channel per timestep.               │
│    Gate near 0 = suppress this channel this timestep            │
│    Gate near 1 = pass this channel through at full strength     │
│                                                                 │
│    Example: RSI-like signal (analyst_score) during a strong     │
│    trend → gate learns to suppress it (overbought is irrelevant │
│    in trending markets). No manual feature engineering needed.  │
│                                                                 │
│  BatchNorm1d(16)  +  Dropout(0.2)                               │
├─────────────────────────────────────────────────────────────────┤
│  GatedConv1d  (16 → 32, kernel=3, padding=1)                    │
│    Same dual-path mechanism — learns cross-channel interactions │
│  BatchNorm1d(32)  +  Dropout(0.2)                               │
├─────────────────────────────────────────────────────────────────┤
│  GatedConv1d  (32 → 16, kernel=3, padding=1)                    │
│    Compression layer — reduces feature map back to 16 channels  │
├─────────────────────────────────────────────────────────────────┤
│  AdaptiveAvgPool1d(1)                                           │
│    Collapses the time axis → shape (batch, 16)                  │
│    Equivalent to averaging each channel across all 10 timesteps │
├─────────────────────────────────────────────────────────────────┤
│  Linear(16 → 8)  +  ReLU                                        │
│  Linear(8  → 1)                                                  │
│    Output: predicted 1-day return  (e.g. +0.018 = +1.8%)        │
└─────────────────────────────────────────────────────────────────┘

Total parameters: ~6,800   (2× old Conv1d-only model due to dual-path gating)
Training time   : < 5s on CPU,  < 1s on GPU
Device          : CUDA if available → MPS (Apple) → CPU
```

---

## Part 3 — Inference Cycle (every symbol, every trading cycle)

```
signal_history.get_recent_window(symbol, T=10)
  Loads last 10 rows from data/history/{SYMBOL}.parquet
  Returns shape (7, 10)  ← direct CNN input

signal_cnn.predict(window)
  Runs one forward pass through the GLU-gated CNN
  Raw output: pred_return  (float, e.g. +0.018)

  Direction:
    pred_return > +0.005  →  "bull"
    pred_return < -0.005  →  "bear"
    else                  →  "neutral"

  Confidence:
    confidence = min(1.0,  |pred_return| / 0.05)
    A 5% predicted return maps to confidence = 1.0
    A 1% predicted return maps to confidence = 0.20

  Pre-training fallback (no trained model yet):
    pred_return = composite_score × 0.02
    direction   = bull if composite > 0.15
                  bear if composite < -0.15
                  neutral otherwise
    confidence  = 0.30
```

---

## Part 4 — Ollama Reasoning Prompt (5-Step Chain of Thought)

```
The CNN prediction is NOT the final signal.
It feeds into a 5-step reasoning prompt sent to the local Ollama LLM.

PROMPT SECTIONS:
  1. CNN Prediction
       Predicted return  direction  confidence
       (confidence label clarifies: do NOT invert it)

  2. Learned Source Weights  (from first GatedConv1d conv_main layer)
       For each of the 5 sources:
         learned %   hardcoded %   delta (elevated / reduced / same)
       These update every 24h as the CNN retrains.

  3. Current Source Scores
       Live scores for all 5 sources + composite score
       earnings_surprise and congressional_trades labeled [CONTEXT ONLY]

  4. Agent Performance Rankings
       All other agents sorted by 30-day performance score
       Per agent: score  win_rate  sharpe  trade_count  → action  confidence
       Weighted consensus score + agreement fraction

  5. Overnight / Sentinel Catalysts  (if any)
       Direct catalysts for this symbol first (up to 3)
       Broad market catalysts second   (up to 3)
       Format: [DIRECT] or [SYMBOL] headline (score, category, date)

  6. Macro Context
       FRED + ETF-proxy macro text
       Each line tagged [FRESH: date] or [STALE: Nd old]

TASK — 5 reasoning steps:

  Step 1 — Agreement
    Does CNN direction agree with composite score sign?
    (composite = fresh sources only: analyst + alpaca_news + yahoo_news)

  Step 2 — Agents
    Name top-2 agents by performance score.
    Do their actions support or contradict the CNN?

  Step 3 — Catalysts
    Any direct catalysts for this symbol?
    Factor into confidence.

  Step 4 — Macro  (staleness rule strictly enforced)
    FRESH data (<=4 days old)  → MAY adjust confidence
    STALE data                 → context only, DO NOT adjust confidence
    Headwinds: Fed funds > 5% = tight money = headwind for growth stocks
               Breakeven inflation > 3% = rate-hike risk

  Step 5 — Decision
    Choose BUY / SELL / HOLD
    If CNN and composite conflict → prefer HOLD unless agent consensus strong
    Confidence adjustments:
      Reduce by up to 0.15 if FRESH macro is clear headwind
      Increase by up to 0.10 if FRESH macro is clearly supportive
      Stale data = zero adjustment

OLLAMA RESPONSE (JSON only):
  {"action": "BUY"|"SELL"|"HOLD", "confidence": 0.0–1.0, "reasoning": "..."}

FALLBACK (if Ollama unavailable or times out at 50s):
  action     = direction → BUY / SELL / HOLD
  confidence = CNN confidence
  reasoning  = "CNN-only: predicted +X.X% 1D return (bull/bear/neutral)"
```

---

## Part 5 — Signal Gate (BUY/SELL/HOLD decision)

```
action = BUY
  AND  confidence >= 0.50
  AND  price > 0
  ──► Signal BUY
        shares = floor( portfolio_value × MAX_POSITION_SIZE / price )
        MAX_POSITION_SIZE = 10% (config)

action = SELL
  AND  symbol in portfolio.positions
  ──► Signal SELL
        shares = portfolio.positions[symbol].shares

else
  ──► Signal HOLD
        shares = 0
```

---

## Part 6 — Feedback Loop (closes the circle)

```
                 ┌─────────────────────────────────────────────┐
                 │                                             │
    Market data  │  Every 60s                                  │
    cycle        │                                             │
        │        ▼                                             │
        │  record_snapshot()                                   │
        │  5 source scores + composite + price                 │
        │                                                      │
        │  After agents run:                                   │
        │  record_agent_signals()                              │
        │  agent_consensus + agent_agreement                   │
        │                                                      │
        │  24h later:                                          │
        │  update_outcomes()  → return_1d filled               │
        │  update_top_agent_correct() → 1.0 or 0.0            │
        │                                                      │
        │  24h retrain:                                        │
        │  Rows where top agent was right  → weight 1.0        │
        │  Rows where top agent was wrong  → weight 0.5        │
        │  CNN trains harder on correct-agent rows             │
        │                                                      │
        │  get_learned_weights() extracts importance from      │
        │  GatedConv1d.conv_main.weight  (main path only)      │
        │  → fed back into next Ollama prompt                  │
        │                                                      │
        └─────────────────────────────────────────────────────┘

KEY INVARIANT:
  The CNN does not just learn from price — it learns from which agents
  were right. Rows confirmed correct by the top performers carry 2×
  the gradient influence of rows where agents were wrong. Over time
  the model up-weights sources that consistently preceded correct calls
  and down-weights sources associated with losing trades.
```

---

## Part 7 — Diagnostics Endpoint

```
GET /api/cnn-diagnostics

Returns:
  trained          bool    — has the model been trained at least once?
  device           str     — "cuda" | "mps" | "cpu"
  n_channels       int     — 7 (5 source + 2 agent)
  n_train          int     — training samples in last run
  n_val            int     — validation samples in last run
  final_train_mse  float   — last epoch train MSE
  final_val_mse    float   — last epoch val MSE
  overfit_ratio    float   — val_mse / train_mse  (healthy: 1.0–2.5)
  diagnosis        str     — OK | OVERFIT | OVERFIT_MEMORIZING | UNDERFIT
  train_loss_curve list    — per-epoch train MSE  (downsampled to 40 pts)
  val_loss_curve   list    — per-epoch val MSE    (downsampled to 40 pts)
  learned_weights  dict    — per-source importance (sums to 1.0)
  weight_delta     dict    — learned minus hardcoded per source
  last_trained     str     — ISO timestamp of last training run

DIAGNOSIS THRESHOLDS (tuned for 1-day returns clipped ±20%):
  Typical 1-day move: 0.5–2%   → squared → MSE 0.000025–0.0004
  Healthy train MSE : 0.0002–0.002
  Healthy ratio     : 1.0–2.5×

  OVERFIT_MEMORIZING  train_mse < 0.00001       model memorised data
  OVERFIT             ratio > 3.0               not generalising
  UNDERFIT            both > 0.005              not learning signal
  OK                  everything else
```

---

## Quick Reference — Key Files

| File | Role |
|------|------|
| `backend/data/cnn_model.py` | GatedConv1d, _build_glu_net, SignalCNN, fit, predict, save/load |
| `backend/data/signal_history.py` | Parquet store, snapshot recording, outcome labeling, training data export |
| `backend/agents/cnn_reasoning_agent.py` | Model lifecycle, Ollama prompt, 5-step reasoning, signal gate |
| `backend/data/macro_context.py` | Macro context text injected into prompt (FRESH/STALE tagged) |
| `backend/data/agent_performance_tracker.py` | Agent scores/win rates used in ranking section of prompt |
| `backend/data/models/signal_cnn.pt` | Saved model checkpoint (excluded from git) |
| `backend/data/history/*.parquet` | Per-symbol snapshot history (excluded from git) |
| `backend/tests/test_cnn_model.py` | 48 unit tests covering all of the above |

---

*Updated 2026-04-12 — stale-source isolation: earnings_surprise and congressional_trades excluded from composite; labeled CONTEXT ONLY in all LLM prompts.*
