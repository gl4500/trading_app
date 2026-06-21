# Model Improvement Ledger

Persistent fail-fast ledger for trading_app model R&D (per the "fail fast, cheap probe
before infrastructure, log every verdict" discipline). Newest iteration on top.
Companion to `docs/equity_feature_engineering_audit.md` (feature-level) and the
`trading_app_sprint_log` memory (chronological retrain metrics).

## The core problem (as of 2026-06-14)

Live model (`signal_xgb.json`, retrained 2026-06-08): **`mean_ic = +0.103` but `mean_wfe = -0.035` (POOR)**.
W3 companion: `mean_ic = +0.019`, `mean_wfe = -0.125`. WFE gate uses `max(...) = -0.035 < 0`,
so the XGBReasoningAgent's BUYs are gated off — it can only sell/hold.

**Signature:** positive rank-IC, negative magnitude-WFE, with the *most-recent* walk-forward
fold's IC collapsing to ≈0 (documented repeatedly in the sprint log: 16-ch run fold-2 IC = -0.0085;
W3 week-1 WFE -0.068). The model ranks names okay but has no stable magnitude edge in the
*current* regime. This is the thing to attack — not raw IC, which forward-selection already maxes
by over-fitting older folds.

## Hypothesis backlog (prioritized; cheap probes first)

| # | Hypothesis | Cheapest test | Status |
|---|---|---|---|
| H1 | Walk-forward embargo (1 bar) << 10-day label → train/val leakage inflates IC, hides true magnitude failure | Count train rows whose label window overlaps val | **FALSIFIED as root cause** (iter 1) — leakage only 0.5–1.6%. Real bug, minor effect. |
| H2 | Regime non-stationarity: edge exists on old folds, absent in current regime | Re-rank existing experiment metas by *last-fold* WFE, not mean_IC | **REFRAMED (iter 2)** — opposite is true: recent fold is the *best* (+0.015 WFE, +0.16 IC); mean_wfe is dragged down by *oldest* fold. Edge is present NOW. |
| H3 | Magnitude miscalibration (rank fine, scale wrong) → fix WFE with post-hoc isotonic/linear map on pred→realized, no retrain | Fit rolling calibration on saved preds vs realized, recompute WFE | open |
| H4 | Recency-weighted / time-decay training would fit the live regime (current sample_weights only up-weight top-agent-correct, not recency) | Add exp time-decay to sample_weights in a sidecar fit, compare last-fold WFE | open |
| H5 | Target transform: predict vol-scaled or rank-normalized return instead of raw 10d return → stabler magnitude across regimes | Sidecar fit with y' = y / rv_20d, invert, compare WFE | open |
| H6 | Select features/configs on last-fold WFE instead of mean_IC (every prior sweep optimized mean_IC, which rewards dead old folds) | Re-score forward-selection log by last_WFE | open |
| H7 | The edge is rank (IC), not magnitude (WFE) — gate on rank/direction instead | Recent-fold direction hit-rate from calibration buckets | **FALSIFIED (iter 3)** — current-regime (June) IC is −0.07 and calibration is *inverted*. No rank edge to gate on right now either. |
| H8 | **W3 blend is net-harmful in the current regime** | Backtest blended vs XGB-only on most-recent fold | open — directionally supported; recheck under iter-3 correction |
| H9 | **Edge is regime-dependent.** Model works in clean bull (May, IC +0.15..+0.28) and breaks when momentum fades to neutral (June, IC −0.07). It's a long-momentum model. | Reconstruct SPY regime over the 3 fold windows | **SUPPORTED, weakly (iter 4)** — good folds = bull, bad fold = bull→neutral. But n=1 transition; needs multi-window validation (H10). |
| H10 | The bull↔+edge / neutral↔−edge relationship holds across *history* — strong enough to gate participation | 10-yr daily cross-sectional IC(20d mom → fwd 10d) bucketed by regime | **REFRAMED (iter 5)** — only robust effect is **bear → −0.064 IC (t≈−4.6)**; bull weakly +, neutral ≈ 0. Iter-4 neutral-gate NOT justified. Bear is already gated (+0.15). |
| H11 | XGB trades still *leak through* in bear despite the +0.15 penalty | Join trades (trading.db) to regime; PnL/win-rate by regime | **FALSIFIED for XGB (iter 6)** — 94% of XGB BUYs are in bull; gate works. XGB system net **+$12.5K realized**. But non-gated rule-based agents bleed **−$19.3K in bear**. |
| H12 | Extending the bear/high_vol participation gate to the **non-gated rule-based agents** (Momentum, MeanRev, Tech, HistTrends) would recover much of the −$19.3K bear bleed | Design a shared `BaseAgent` regime-entry gate; the XGB agent's 94%-bull / +$12.5K record is the proof-of-concept | open — **highest-EV finding; operator decision + TDD** |

## Iterations

### Iteration 1 — 2026-06-14 — H1 embargo-leakage probe

**Setup:** `data/cnn_evaluation.walkforward_folds(embargo_bars=1)` drops exactly 1 row between
train and val; fold boundaries are time-based (`min_val_days=14`), label is `return_10d`. A train
row at time `t` carries a label from price at `t+10d`; if `t` is within 10 days before `val_start`,
its label window overlaps the validation period. Dropping 1 row out of ~234 symbols/bar ≈ zero
embargo.

**Probe (offline, timestamps only, no retrain, production untouched):** counted train rows within
10 days of each fold's `val_start` across all 234 per-symbol parquets (557,977 rows, 3,683-day span).

**Result:** leakage = 0.51% / 1.17% / 1.60% of train rows (folds 0/1/2). Real but small.

**Verdict:** H1 is a genuine correctness bug but **NOT the cause of negative WFE** — 1% contaminated
rows can't flip the WFE sign. Reframes priority toward H2 (regime non-stationarity). Fixing the
embargo is still worthwhile (free metric-honesty win, TDD-able: make embargo time-based ≥
`LABEL_HORIZON_DAYS` rather than a row count), but it's a cleanup, not the lever.

**Next:** H2 — re-rank the existing experiment `.meta.json` files and `forward_selection.log` by
*last-fold* WFE rather than mean_IC, to see whether any already-tried config is robust in the
current-regime fold. Pure offline re-scoring of artifacts already on disk.

### Iteration 2 — 2026-06-14 — H2 last-fold re-ranking

**Setup:** `fold_metrics` in each `*.meta.json` records per-fold {wfe, ic, n_train, n_val}.
Established the fold-ordering convention empirically: `n_train` telescopes (fold N+1 train =
fold N train + fold N val), proving **expanding-window folds ordered oldest→newest — fold 0 =
oldest, highest fold index = most recent**. So "last fold" = current-regime proxy. Re-scored all
8 on-disk configs by most-recent-fold wfe/ic (offline, no retrain).

**Result (most-recent fold):**

| config | mean_wfe | recent_wfe | recent_ic |
|---|---|---|---|
| production `signal_xgb` | −0.035 | **+0.0149** | **+0.164** |
| xgb_exp_12ch | −0.134 | +0.0156 | +0.158 |
| xgb_exp_11ch_noanalyst | −0.127 | +0.0132 | +0.158 |
| xgb_exp_9ch_histseasonal | −0.140 | +0.0089 | +0.119 |
| w2b_regimegated | −0.213 | −0.0399 | +0.085 |
| w2_gated | −0.294 | −0.0549 | +0.089 |
| w1_linear | −1.17 | −0.0625 | +0.006 |
| **w3_pergroup** | −0.098 | **−0.130** | +0.013 |

**Verdict (H2 reframed):** the negative `mean_wfe` that gates the agent off is an artifact of
averaging in *ancient* regimes (oldest fold WFE −0.34). Every XGB config has **positive
most-recent-fold WFE** and robust recent IC (+0.12..+0.16). The model has a real edge in the
*current* regime — the gate just can't see it because it uses the fold-mean.

**Two live-config consequences surfaced (operator decisions — not auto-applied):**

1. **WFE gate metric (→ H7).** `_apply_wfe_gate` blocks BUY when `mean_wfe < 0`. Live-relevant
   recent-fold WFE is +0.015. Candidate change: gate on the most-recent-fold WFE (or a
   recency-weighted WFE), **guarded** by a minimum n_val and a "positive over last K folds"
   requirement so a single noisy 14-day window can't unblock trading. Caveat / honest falsifier:
   recent WFE is small (+0.015, one 14-day window, high variance) — this is *suggestive*, not
   proof of magnitude edge. Recent **IC** (+0.16) is the stronger, better-powered signal → favors
   a rank/direction gate (H7) over a looser magnitude gate.

2. **W3 blend (→ H8).** W3's most-recent-fold WFE is −0.13 (worst measured) and IC +0.01. At
   weight 0.2 it still drags XGB's recent IC +0.16 toward noise. Candidate: set
   `W3_BLEND_WEIGHT=0` (disable) pending a positive recent-fold W3, or gate W3 into the blend only
   in regimes where its recent fold is positive.

**Next:** H7 — compute most-recent-fold *direction hit-rate* (sign agreement) from saved fold
preds to quantify the directional edge directly, and sketch a rank/direction gate as an
alternative to the magnitude-WFE gate. Still offline.

### Iteration 3 — 2026-06-20 — H7 calibration probe → CORRECTS iteration 2

**Setup:** read the `calibration` (5-bucket predicted-vs-realized) + full `fold_metrics` from the
production `signal_xgb.json.meta.json`. First nailed fold ordering by running `walkforward_folds`
on live timestamps: **fold 0 = oldest, highest index = most recent** (fold 2 val = 2026-06-03..17).
`calibration` and `last_WFE` are computed on `folds[-1]` = the most-recent fold. Confirmed.

**Result — production model (retrained 2026-06-17 by the live 24h cycle, between iter 2 and now):**

| fold | val window | WFE | IC |
|---|---|---|---|
| 0 | early–mid May | +0.046 | +0.151 |
| 1 | late May | +0.092 | +0.281 |
| 2 — **current (June)** | 06-03..06-17 | **−0.259** | **−0.070** |

Calibration on the current fold is **inverted**: every bucket's actual return is negative
(−0.006..−0.017) while every prediction is positive, and the highest-prediction bucket has the
*worst* actual (−0.017). Long-biased model, down regime.

**CORRECTION to iteration 2:** iter 2's "recent fold is positive (+0.015 WFE / +0.16 IC), agent is
gated off a live edge" was an **artifact of stale artifacts**. The *experiment* `.meta.json` files
are frozen at May-2026 training, so their "most-recent fold" was early-May — a regime where the
model genuinely worked. The continuously-retrained production model exposes the **truly current
regime (June), which is negative**. The re-rank in iter 2 compared May-vintage "recent" folds
against each other, not the live regime.

**Verdict:**
- **H2/H7 reversed.** There is no positive recent-fold edge to unblock right now — current-regime
  IC is −0.07 and calibration is inverted. The WFE gate suppressing BUYs is **correct**, and
  `mean_wfe` (−0.04) is if anything *generous* (it averages in May's good folds; the live fold is
  −0.26). Loosening the gate, as iter 2 floated, would have been actively harmful. (Honest-falsifier
  discipline held: don't loosen the gate to chase a number that wasn't the live regime.)
- **Real problem (H9): the edge is regime-dependent and currently absent.** Model has real skill in
  some regimes (May: IC up to +0.28) and anti-skill in others (June: inverted). The lever is
  **regime-conditional participation** — trade when the model's recent-fold metric is positive, sit
  out / go defensive when negative — not feature tweaks that lift a fold-averaged score.

**Next:** H9 — line up each fold's date range against `regime_detector` state to test whether a
cheap, available regime signal separates the model's good folds from its bad ones (i.e. could gate
participation on regime). Offline: re-derive SPY-based regime over the three fold windows.

### Iteration 4 — 2026-06-20 — H9 regime-vs-edge alignment

**Setup:** replicated `regime_detector` logic (20d SPY momentum: ≥+2% bull / ≤−2% bear; ann vol
≥20% → high_vol dominates) on daily-resampled SPY closes (`data/history/SPY.parquet`, through
06-17), then tallied the daily regime over each production fold's date window.

**Result:**

| fold | model edge | SPY regime | mean 20d-mom | mean ann-vol |
|---|---|---|---|---|
| 0 (early May) | WFE +0.046 / IC +0.151 | **bull** (11/11 d) | +0.075 | 0.10 |
| 1 (late May) | WFE +0.092 / IC +0.281 | **bull** (12/12 d) | +0.049 | 0.10 |
| 2 (June) | WFE −0.259 / IC −0.070 | bull→**neutral** (4n/3b) | +0.015 | 0.12 |

**Verdict (H9 supported, weakly):** the model's edge tracks the momentum regime — strong in clean
bull, gone when momentum fades to neutral (June mom +0.015, dipping under the +0.02 bull line). It's
a long-momentum model; mechanistically it should die when momentum flattens. Vol never hit the 0.20
high_vol threshold (peaked 0.14), so a vol-based gate wouldn't have helped.

**Key gap found:** `regime_detector._CONFIDENCE_GATE` adds **+0.00 for neutral** (same as bull) and
only raises the BUY bar for bear (+0.15) / high_vol (+0.20). June was *neutral*, so the existing
regime gate gave **zero** defense in exactly the regime where the model failed. The minimal candidate
fix is a neutral-regime confidence penalty (or gate XGB BUY participation to `regime==bull`).

**Caveat (do not ship yet):** n=1 regime transition (3 folds, 2 regimes). Mechanistically clean but
statistically thin. A single bull→neutral coincidence isn't enough to justify a live gate change.

**Next:** H10 — validate across history before any code change. Sidecar computes per-14-day-window
IC over the full 10-yr backfill, buckets each window's IC by that window's SPY regime, and checks
whether bull windows are reliably positive-IC and neutral/bear windows reliably ≤0. Only if that
holds does a `regime==bull` participation gate (or neutral penalty) earn a TDD'd implementation.
Heavier than prior probes (needs model preds over history) but still offline; will keep it CPU-bounded
and off the live booster files.

### Iteration 5 — 2026-06-21 — H10 cross-history regime×IC validation

**Setup (lighter than planned — fail-fast):** rather than run the booster over 557K windows, tested
the *mechanism* directly. Iter 4 established the model is a long-momentum model, so measured whether
**trailing-20d-momentum's own** cross-sectional IC vs forward `return_10d` is regime-dependent.
Parquet columns only (price → mom20, `return_10d` = label), 234 symbols, daily cross-sectional
Spearman IC per day, bucketed by SPY regime. 511K symbol-days / 2,517 IC-days / 2016-06..2026-06.

**Result (mean daily IC by regime):**

| regime | mean IC | std | days | ~t |
|---|---|---|---|---|
| bear | **−0.0639** | 0.199 | 206 | **−4.6** |
| neutral | −0.0064 | 0.171 | 815 | −1.1 |
| high_vol | +0.0010 | 0.230 | 489 | ~0 |
| bull | +0.0074 | 0.162 | 1007 | +1.5 |

**Verdict (H10 reframed; corrects iter 4):**
- Robust effect = **momentum reverses in bear** (IC −0.064, t≈−4.6). Bull only weakly positive (ns),
  **neutral ≈ 0** (ns), high_vol ≈ 0.
- **Iter-4's "neutral-regime penalty / gate to bull-only" is NOT supported** — neutral doesn't
  systematically hurt momentum. The June fold's −0.07 IC coinciding with neutral was almost certainly
  noise (single ~10-day fold, SE ≈ 0.05). This also tempers iter 3's "current regime is negative" —
  one short fold is within noise of zero.
- The one strong, real regime effect (bear reversal) is **already handled**: `regime_detector`
  confidence gate adds +0.15 (bear) / +0.20 (high_vol) to the BUY threshold.

**Implication — convergence:** regime-gating beyond the existing bear/high_vol penalty offers little
*robust* edge. The model's marginal WFE is general weak-edge + magnitude calibration, not a clean
regime switch we can gate our way out of. Two honest remaining directions: (a) verify the existing
bear gate is actually *strong enough* (do BUYs still leak through in bear given IC −0.064?) — H11;
(b) accept marginal long-side edge and look at a mean-reversion/short overlay for bear (big change).

**Next:** H11 — cheap. Join historical trades (`trading.db`) to the SPY regime on each trade date and
compare realized PnL / win-rate by regime. Tests whether trades leak through in bear despite the
penalty, which would justify *tightening* the existing gate (participation-off in bear) rather than
adding new gates.

### Iteration 6 — 2026-06-21 — H11 trades × regime → reframes the whole investigation

**Setup:** joined every trade in `trading.db` to the SPY regime on its date; broke down XGB BUY
counts and realized SELL PnL by regime (XGB alone + all agents).

**Result:**

XGB BUYs by regime: **bull 194 / bear 8 / neutral 3 / high_vol 2** — 94% bull. The +0.15/+0.20 gate
works; XGB barely trades outside bull.

Realized PnL by regime:

| regime | XGB net | all-agents net | all win% | all closes |
|---|---|---|---|---|
| bull | +$12,066 (win 64%) | +$71,887 | 58% | 1,501 |
| neutral | −$1,268 (n=6) | +$327 | 49% | 138 |
| bear | +$352 (n=2) | **−$19,344** | **37%** | 244 |
| high_vol | +$1,431 (n=2) | +$3,424 | 52% | 23 |

**Verdict — the investigation's framing flips positive:**
1. **H11 falsified for XGB** — the gate isn't leaking; 94% of BUYs are in bull.
2. **The XGB model + gates is NET PROFITABLE: +$12.5K realized, 64% bull win-rate** — despite
   `mean_wfe = −0.035`. The negative WFE was a *magnitude-metric artifact*; direction-based trading +
   the regime gate work around it. **The alarm that started this 6-iteration loop ("is the model
   broken?") resolves to: no — the metric was misleading; the gated system makes money.**
3. **Bear is robustly the loss regime** (all-agents −$19.3K / 244 closes / 37% win — large sample,
   confirms H10 with real PnL). But that bleed is in the **non-gated rule-based agents**
   (Momentum/MeanRev/Tech/HistTrends); the XGB agent's bear gate already protects it.

**The one genuine, high-EV opportunity left (H12):** port the regime participation gate the XGB agent
already proves out (94% bull, +$12.5K) to the rule-based agents that currently have no bear protection
and bleed −$19.3K. That's a `BaseAgent`-level shared entry gate — operator decision (changes live
behavior for several agents) + TDD. NOT a model change per se; an agent-risk change validated by the
model agent's own track record.

## Status after 6 iterations
The "negative-WFE = broken model" thread is **resolved**: the gated XGB system is profitable; WFE
mis-measured a marginal-but-real long-momentum edge that the gates monetize in bull and protect in
bear. Regime-gating the model further is exhausted. The remaining lever (H12) is about the *other*
agents, not the model. Recommend pausing model-metric R&D and deciding on H12.
