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
| H1 | Walk-forward embargo (1 bar) << 10-day label → train/val leakage inflates IC, hides true magnitude failure | Count train rows whose label window overlaps val | **FALSIFIED as root cause** (iter 1) — leakage only 0.5–1.6%. Real bug, minor effect. **FIXED 2026-06-25** — see Iteration 9. |
| H2 | Regime non-stationarity: edge exists on old folds, absent in current regime | Re-rank existing experiment metas by *last-fold* WFE, not mean_IC | **REFRAMED (iter 2)** — opposite is true: recent fold is the *best* (+0.015 WFE, +0.16 IC); mean_wfe is dragged down by *oldest* fold. Edge is present NOW. |
| H3 | Magnitude miscalibration (rank fine, scale wrong) → fix WFE with post-hoc isotonic/linear map on pred→realized, no retrain | Fit rolling calibration on saved preds vs realized, recompute WFE | open |
| H4 | Recency-weighted / time-decay training would fit the live regime (current sample_weights only up-weight top-agent-correct, not recency) | Add exp time-decay to sample_weights in a sidecar fit, compare last-fold WFE | **FALSIFIED (iter 11)** — recency weights (halflife 90/180/365d) all make last_WFE *worse* (−0.80 best vs −0.61 baseline), IC stays ~0. |
| H5 | Target transform: predict vol-scaled or rank-normalized return instead of raw 10d return → stabler magnitude across regimes | Sidecar fit with y' = y / rv_20d, invert, compare WFE | **FALSIFIED (iter 11)** — vol-scaled target (data-driven rv floor) gives last_WFE −1.80 vs −0.61 baseline, IC ~0. Worse, not stabler. |
| H6 | Select features/configs on last-fold WFE instead of mean_IC (every prior sweep optimized mean_IC, which rewards dead old folds) | Re-score forward-selection log by last_WFE | **FALSIFIED (iter 10)** — 0/38 sweep configs have positive last_WFE; best is `corr_spy_20d` alone at −0.0313. No hidden edge. Honest side-signal: mean_IC selection overfits (16-feat peak generalizes worse than 1-feat), but WFE stays negative → reduces overfit, doesn't create edge. |
| H7 | The edge is rank (IC), not magnitude (WFE) — gate on rank/direction instead | Recent-fold direction hit-rate from calibration buckets | **FALSIFIED (iter 3)** — current-regime (June) IC is −0.07 and calibration is *inverted*. No rank edge to gate on right now either. |
| H8 | **W3 blend is net-harmful in the current regime** | Backtest blended vs XGB-only on most-recent fold | open — directionally supported; recheck under iter-3 correction |
| H9 | **Edge is regime-dependent.** Model works in clean bull (May, IC +0.15..+0.28) and breaks when momentum fades to neutral (June, IC −0.07). It's a long-momentum model. | Reconstruct SPY regime over the 3 fold windows | **SUPPORTED, weakly (iter 4)** — good folds = bull, bad fold = bull→neutral. But n=1 transition; needs multi-window validation (H10). |
| H10 | The bull↔+edge / neutral↔−edge relationship holds across *history* — strong enough to gate participation | 10-yr daily cross-sectional IC(20d mom → fwd 10d) bucketed by regime | **REFRAMED (iter 5)** — only robust effect is **bear → −0.064 IC (t≈−4.6)**; bull weakly +, neutral ≈ 0. Iter-4 neutral-gate NOT justified. Bear is already gated (+0.15). |
| H11 | XGB trades still *leak through* in bear despite the +0.15 penalty | Join trades (trading.db) to regime; PnL/win-rate by regime | **FALSIFIED for XGB (iter 6)** — 94% of XGB BUYs are in bull; gate works. XGB system net **+$12.5K realized**. But non-gated rule-based agents bleed **−$19.3K in bear**. |
| H12 | Extending the bear/high_vol participation gate to the **non-gated rule-based agents** (Momentum, MeanRev, Tech, HistTrends) would recover much of the −$19.3K bear bleed | Design a shared `BaseAgent` regime-entry gate; the XGB agent's 94%-bull / +$12.5K record is the proof-of-concept | open — **highest-EV finding; operator decision + TDD** |
| H14 | A classic macro signal (VIX term structure, credit spreads, breadth, yield curve) *leads* regime change → add it as an anticipatory feature | Lead-lag rank-AUC: does signal(t) predict forward SPY stress at t+k, non-decaying? | **FALSIFIED (iter 12)** — at the 5–20d horizon none leads: all coincident/decaying, best is VIX *level* (already a feature). Curve inversion 0.47 (leads by quarters, not weeks). |
| H16 | **The binding constraint on the best live agent is exit mechanics, not entry signal.** Positions that never reach `TRAIL_ARM_USD` (+$100 peak uPnL) have *no* protection between entry and the −8% hard stop; that unprotected gap is 100% of the loss column | Attribute every SELL to its exit branch, split W/L and PnL (read-only `trading.db`) | **SUPPORTED (iter 15)** — HistoricalTrendsAgent: trail-stop 223 exits / 90.6% W / **+$70,425**; hard stop 108 exits / **0% W** / **−$56,474**. Next test = time-stop or pre-arm stop, backtest-only. |
| H17 | Inside a rule-based agent, individual pillars can be *net-negative* yet keep their weight because the composite is never decomposed against outcomes | Bucket realized PnL by each pillar's value at entry | **SUPPORTED (iter 15)** — HistTrends seasonal pillar (w=0.20) is sign-inverted on live sample; channel pillar (w=0.30) is overridden on 69% of entries; composite >+0.60 is the *only* net-negative entry bucket yet is sized largest (size ∝ confidence = \|composite\|). |

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

### Iteration 7 — 2026-06-21 — H12 entry-regime attribution → FALSIFIES the bear entry-gate

**Setup:** H12 proposed porting the XGB bear *entry*-gate to the rule agents to recover the iter-6
"−$19.3K bear bleed." But that −$19.3K is attributed by **close-date** regime; an entry gate fires at
**BUY** time. Offline FIFO-matched every SELL back to its BUY lot (`trading.db`), tagged each realized
chunk by both entry and close regime (SPY regime via the real `RegimeDetector`). Cross-check:
FIFO-reconstructed PnL = authoritative SELL-row PnL **exactly** ($40,942 for the 4 rule agents;
$54,488 all agents). Close-regime bear total reproduced iter-6 (−$21.1K vs −$19.3K — method sound).

**Result (all agents):** bear by **CLOSE** regime −$21,119; bear by **ENTRY** regime **+$34,760**.
Per-agent bear ENTRY: Scanner +$15.9K, HistTrends +$15.1K, Momentum +$7.1K, XGB +$5.1K, MeanRev −$6.4K.
Two facts also surfaced: (a) the iter-6 −$19.3K was *all-agents* (Scanner −$12.0K close drives it),
not the 4 rule agents — those 4 net **+$40.9K** and only −$2.9K bear-CLOSE; (b) bull-entered positions
are essentially absent from the bear-close losers (bear episodes here followed neutral, not bull).

**Verdict — H12 FALSIFIED.** A bear entry-gate's exact counterfactual is the entry-regime-bear bucket
= **+$34.8K of realized PnL it would remove.** Bear entries are *profitable* (53% win) — buying weakness
and selling the recovery. The −$21K is an exit/holding phenomenon (positions opened earlier, closed
during bear), not an entry-participation one. Porting the gate is contraindicated. (Caveat: ~3-month
bull-dominated sample, so "bear entries profitable" is partly regime luck — but "a bear entry-gate would
have hurt in the only data we have" is robust.)

**Next:** H13 — if the bleed is exit-side, would de-risking on the neutral→bear *flip* help? Characterize
the bear-CLOSE losers, then simulate exit-at-flip.

### Iteration 8 — 2026-06-21 — H13 exit-on-bear-flip simulation → FALSIFIES the exit-side lever

**Setup:** Characterized the −$28.3K of bear-CLOSE *losers*: −$11.1K entered+closed in bear (n=113,
median hold 0d — quick stop-outs, already dwarfed by the +$34.8K bear-entry winners) and **−$17.3K
entered in neutral, held a median 4d into a bear flip** (the only regime-addressable bucket). Then
ran the decisive test: for every position open when SPY flips to bear (52 flip dates over the
backfill), force-exit at that day's per-symbol price (`data/history/<SYM>.parquet`, 224/226 symbols
available) and compare total realized PnL vs actual — applied symmetrically to winners and losers.

**Result:** 63 chunks held through a bear flip. Force-exit at the flip = **−$3,053 WORSE**
(affected chunks: actual −$18,009 vs flip-exit −$21,062; portfolio-wide $54,488 → $51,435).

**Verdict — H13 FALSIFIED.** Exiting at the bear flip realizes a *worse* price than holding to the
actual exit — positions were already underwater at the flip and partially recovered, and the existing
trailing/hard/Bayes stops already exit better than a blunt regime trigger would. No exit-side regime
lever beats current behavior.

## Status after 8 iterations (SUPERSEDES "after 6 iterations" above)
Thread **fully closed.** The gated XGB system is profitable (+$12.5K); the rule agents net positive
(+$40.9K for the 4; +$54.5K all agents). The "bear bleed" is a close-regime accounting artifact, not
an addressable inefficiency. **No regime-timing lever — entry-side (H12) or exit-side (H13) — improves
on current behavior.** Recommend pausing model/agent-risk R&D on the regime axis. No code change made
(all analysis was offline/read-only against `trading.db` + parquet; live backend on :8000 untouched).

### Iteration 9 — 2026-06-25 — H1 embargo cleanup SHIPPED (the one honest win)

With the regime axis exhausted (iters 6–8), the cheapest remaining honest improvement was the H1
metric-honesty fix flagged back in iter 1. **Implemented via TDD** (RED→GREEN per affected module):

**Change:** added `embargo_days: float = 0.0` to `data/cnn_evaluation.walkforward_folds`. The
effective embargo is now the LARGER of the two rules —
`train_end_idx = max(0, min(train_cutoff_idx - embargo_bars, searchsorted(ts, val_start - embargo_days*86400)))`
— so a multi-day forward label can't leak into validation regardless of bar density (a row-count
embargo silently fails under intraday bars). Wired `embargo_days=LABEL_HORIZON_DAYS` (=10) through all
three model `fit()` methods: `SignalCNN`, `SignalXGBoost` (the production WFE-gated model), `SignalW3`.

**Backward compatibility:** default `0.0` means every existing call/test that doesn't opt in behaves
exactly as before. The 90-day / 300–600-pt synthetic test fixtures still yield 3 non-empty folds after
a 10-day embargo, so no existing assertion changed.

**Tests:** 9 new (3 at the `walkforward_folds` level incl. a dense-bar case that defeats `embargo_bars`
but not `embargo_days`, + 1 `fit()`-wiring mock-assert per model). Full regression GREEN: 178 tests
across cnn_evaluation / cnn_model / xgboost_model / w3_model. Bandit clean on all 4 production files.

**Effect:** walk-forward WFE/IC are now leak-free. Magnitude impact is small (iter 1: ~0.5–1.6% of train
rows) so the live WFE gate's behavior is essentially unchanged — this is honesty, not a new edge. The
next production retrain will recompute metrics under the correct embargo. Thread H1 → **CLOSED, fixed.**

**Real-data verification (offline, timestamps-only, no retrain):** replayed `walkforward_folds` over all
243 production per-symbol parquets (564,454 rows, 3,704-day span). Pre-fix (`embargo_bars=1`) left
**3,673 / 3,185 / 1,565** train rows per fold (0.67% / 0.57% / 0.28%) whose 10-day label window reached
into validation — same order as iter-1's 0.5–1.6%. Post-fix (`embargo_days=10`): **0 leaking rows in
all three folds.** Confirms the shipped fix excludes exactly the rows iter-1 flagged.

### Iteration 10 — 2026-07-05 — H6 re-score sweep by last_WFE → FALSIFIED

**Setup (cheapest test, zero-compute):** the live backend was serving (port 8000), so instead of a
retrain-based probe I re-scored the *existing* greedy forward-selection sweep
(`scripts/forward_selection.log`, 38 nested subsets, ranked by mean_IC) on its recorded `last_WFE`
column — pure parse of a 90-line log, no parquet load / DB / GPU. **Pre-registered falsifier:** if the
best config by last-fold WFE still has `last_WFE ≤ 0`, there is no hidden current-regime edge in the
swept space → H6 falsified.

**Result:**
- **0 of 38** configs have positive `last_WFE` (range −0.1811 … −0.0313).
- Best by `last_WFE` = step 1, `corr_spy_20d` alone (1 feature), `last_WFE=-0.0313`, `mean_IC=+0.1308`.
- The mean_IC "PEAK" (step 16, 16 features, `mean_IC=+0.2691`) has `last_WFE=-0.0822` — **worse**
  recent-fold generalization than the 1-feature model.

**Verdict — H6 FALSIFIED.** Re-ranking the sweep by last-fold WFE surfaces no positive-WFE config;
the global best is still negative. Consistent with iters 3–8 (current-regime magnitude edge is absent).
**Honest side-signal (not a GO):** the least-negative WFE configs are the *smallest* (1–2 features)
while mean_IC keeps climbing to 16 — i.e. mean_IC selection mildly **overfits to old folds** (adds
features that help mean_IC but hurt recent-fold WFE). But since absolute WFE stays negative, a
parsimonious re-selection only *reduces overfit*; it doesn't create edge or unblock the WFE gate.

**Caveat / what a full test would need:** this re-scores the mean_IC-greedy *nested path*, not a fresh
greedy-by-WFE re-optimization. A clean H6+ would re-run greedy adding the channel that best improves
`last_WFE` at each step (expected outcome: a much smaller feature set, still negative WFE). That is the
compute-heavy "infrastructure" step (parquet load + per-fold IC) — gated behind backend-idle and only
justified on a GO, which this is not.

**Next:** open magnitude-axis hypotheses remaining are H3 (post-hoc calibration map), H4 (recency-
weighted training), H5 (vol-scaled target). All three need a sidecar *fit* → run only when the live
backend is idle. H3 is weakest given iter-3 found current-regime calibration is *inverted* (a monotone
map can't fix an inverted rank); H4/H5 are the better next probes.

### Iteration 11 — 2026-07-05 — H4 (recency weights) + H5 (vol-scaled target) → BOTH FALSIFIED

**Setup:** one sidecar probe (`scripts/xgb_recency_voltarget_probe.py`, low CPU priority alongside the
live backend). Same harness as the feature sweep — `signal_history.get_training_data()` (565,516 rows /
240 symbols), 10d forward-return label, `build_training_windows` → last-timestep 38ch, 3-fold
walk-forward — but with the **leak-free embargo** (`embargo_days=LABEL_HORIZON_DAYS=10`, the H1 fix), so
all configs are honest. WFE = OOS R² (`_compute_wfe`). **Pre-registered falsifier (non-loosenable, = the
production WFE gate's bar):** a GO requires the most-recent-fold WFE to rise **above 0**.

| config | mean_IC | mean_WFE | last_WFE | verdict |
|---|---|---|---|---|
| Baseline (uniform, raw y) | +0.0001 | −0.2295 | **−0.6086** | — |
| H4 recency, halflife 90d | −0.0079 | −0.3510 | −0.8526 | worse |
| H4 recency, halflife 180d | −0.0008 | −0.3201 | −0.8086 | worse |
| H4 recency, halflife 365d | +0.0005 | −0.3059 | −0.8045 | worse |
| H5 vol-scaled (rv floor p05=0.1304) | +0.0027 | −0.7871 | −1.8018 | worse |

**Verdict — H4 and H5 both FALSIFIED.** Neither lifts recent-fold WFE above 0; both push it *further
negative* and leave IC at ~0. Recency-weighting the loss and vol-normalizing the target were the two
remaining "stabilize magnitude across regimes" levers — neither helps. The comparison is internally
consistent (identical baseline + harness; only the treatment changes), so the deltas are robust.

**Probe-integrity notes (kept for honesty):**
- **H5 first run was a probe bug, not a real result:** `rv_20d` is *annualized* vol (median 0.30), so a
  fixed `RV_FLOOR=0.01` let low-/zero-rv rows (3.9% have rv≤0) blow up `y/rv` to ±30, spiking predicted
  magnitude → WFE hit the −10 clamp while IC spuriously read +0.034. Re-ran with a data-driven floor
  (5th-pctile of positive rv = 0.1304); IC collapsed to +0.003 and WFE resolved to −1.80. Only the
  corrected run is the verdict. Lesson: check a transform's units before trusting its metric.
- **Baseline degraded vs the 05-09 sweep** (mean_IC +0.073 → +0.0001; last_WFE −0.118 → −0.609). Not a
  harness artifact — it's the regime story continuing: data now runs through July with deeper
  negative-edge recent folds, and the stricter leak-free embargo trims near-boundary train rows. The
  model's aggregate walk-forward rank skill has decayed to ~0 in the current sample.

**Next:** only H3 (post-hoc calibration map) remains open on the magnitude axis, and it is the weakest —
iter-3 found current-regime calibration is *inverted*, so a monotone map cannot manufacture rank edge
that isn't there. The honest read after iters 3–11: **the magnitude axis is now as exhausted as the
regime axis (iters 6–8).** No cheap model-side lever creates current-regime edge; the system's realized
edge remains its *gating* (bull participation, bear avoidance), not its point predictions. Recommend
pausing model-metric R&D pending genuinely new inputs (a new feature/data source or a regime shift).

### Iteration 12 — 2026-07-05 — H14 leading-indicator lead-lag study → FALSIFIED (new axis)

**Motive (operator reframe):** every production feature is trailing/coincident (all macro channels are
`_back`; the regime label = VIX level + SPY trailing-5d), and iters 12/13 showed *reacting* to regime
at entry/exit is too late. So the question shifted from "improve the model on trailing features" to "is
there a signal that *leads* regime change we could add?" Cheap validation *before* building: does a
classic macro signal actually anticipate stress on history?

**Setup:** `scripts/leadlag_regime_probe.py` (read-only, public yfinance data, no trading.db/model).
16,641 daily rows; candidate signals evaluated on their modern overlap (~2007–2026, covers 2008/2011/
2015-16/2018/2020/2022). Rank-AUC of signal(t) → target(t+k), k ∈ {5,10,20}. Two price-only targets so
VIX/credit/breadth candidates can't be circular: T1 = down-trend state (SPY<50dMA) at t+k; T2 = forward
k-day SPY drop < −3%. Candidates oriented so higher = more stress. **Pre-registered falsifier:** a signal
LEADS only if its T2 AUC at k≥10 is ≥0.55 **and** does not decay below its k=5 value.

**T2 result (forward-stress AUC):**

| signal | k=5 | k=10 | k=20 | verdict |
|---|---|---|---|---|
| vix_ts_slope (VIX/VIX3M) | 0.679 | 0.622 | 0.573 | decays → coincident |
| credit_stress (−Δ HYG/LQD) | 0.549 | 0.521 | 0.519 | ~random |
| breadth_stress (−Δ RSP/SPY) | 0.529 | 0.533 | 0.477 | ~random |
| curve_stress (−(10y−3m)) | 0.472 | 0.471 | 0.470 | <0.5 (inversion leads by quarters, not weeks) |
| vix_level [LAG baseline] | 0.715 | 0.660 | 0.610 | strongest, but decays; **already a feature** |
| spy_trail5 [LAG baseline] | 0.522 | 0.548 | 0.526 | weak |

**Verdict — H14 FALSIFIED at this system's horizon.** No candidate leads: every signal's forward-stress
AUC decays with horizon (vix_ts_slope, vix_level) or is near-random (credit, breadth, curve). The
predictive content of regime stress is **coincident**, and the single strongest coincident signal is
plain **VIX level — which the model already has** (`macro_vix_norm`). The fancier candidates (term
structure, credit, breadth, curve) add no *leading* power at 5–20 days. Yield-curve inversion at 0.47
confirms the textbook: it leads at quarters, useless at the trading horizon.

**What this settles:** the "we're missing a leading indicator" intuition doesn't hold for the 5–20d
horizon this system trades — among the classic candidates there simply isn't one; short-horizon regime
stress is not anticipable, it is contemporaneous. This *generalizes* the H12/H13 falsification (reacting
to regime is "too late" because stress genuinely can't be foreseen 10–20d out from these signals) and
closes the newly-opened leading-indicator axis with the usual suspects.

**Where a real edge could still live (not yet tested — these are the honest next forks):**
1. **Use the coincident signal for risk control, not prediction** — vol-targeted position sizing that
   scales exposure down when VIX level/slope is *already* elevated. Doesn't need a leading signal; turns
   the strong coincident AUC into faster de-risking than the current discrete regime gate.
2. **Longer horizon strategy** — at 1–6 month horizons credit spreads and the yield curve *do* lead;
   but that is a different product than the 10d cross-sectional system.
3. **Non-classic leading data** — options-flow/dealer-gamma, positioning (COT), fund flows, short
   interest. Not free/clean; would need a data source before any probe.

Recommend option 1 (vol-targeted sizing off the coincident VIX signal) as the next cheap probe if the
operator wants to keep going; otherwise the model-metric R&D program is exhausted across all three axes
(regime timing, magnitude, leading indicators).

### Iteration 13 — 2026-07-05 — H15 vol-managed sizing premise → GO (SPY premise + REAL-BASKET validation)

**Motive:** iter-12 fork #1 — turn the strong *coincident* VIX/realized-vol signal into risk control
(Moreira-Muir volatility-managed portfolios) instead of prediction. Before touching the position sizer,
two cheap read-only backtests: (a) does vol-targeting beat constant exposure on SPY at all, and (b) —
after the operator correctly flagged SPY is not the book — does it hold on the **actual traded basket**?

**Pre-registered falsifier (non-loosenable, same bar both runs):** vol-managed LEADS to a build only if
net-of-cost (1 bp/turn) it improves Sharpe **AND** cuts max drawdown ≥15% relative to constant. If
Sharpe doesn't beat constant after costs → discard.

**(a) SPY premise** — `scripts/vol_managed_premise_probe.py` (yfinance SPY+VIX, full history):

| strategy | annRet | Sharpe | maxDD | verdict |
|---|---|---|---|---|
| constant (buy&hold) | +12.0% | 0.65 | −55.2% | — |
| vol_managed (20d RV target 12%) | +10.0% | **0.75** | **−39.8%** | GO (+27.9% rel DD) |
| vix_managed (VIX target) | +6.9% | 0.72 | −30.5% | GO (+44.7% rel DD) |

**(b) REAL basket** — `scripts/real_basket_probe.py`. Reconstructed the traded universe READ-ONLY from
`trading.db` (`SELECT symbol, SUM(shares*price) FROM trades GROUP BY symbol`): **237 names, dollar-volume
weighted**, top5 MU/WOLF/FATE/AMD/DDOG — heavily high-beta tech/semis/biotech, **not** the broad market.
Dollar-vol-weighted daily return, renormalized per-day to constituents with yfinance data (100% name
coverage; composition thins backward in time as young names drop out — min 14 / median 107 / max 237
names/day). **Basket vs SPY: beta 1.13 full-history, 1.33 in 2024+; annVol 23.7% vs SPY 15.9% (2024+);
corr 0.89.** So: directionally SPY-like but ~1.3× the amplitude.

| strategy (full history) | annRet | Sharpe | maxDD | verdict |
|---|---|---|---|---|
| constant (buy&hold basket) | +24.1% | 1.03 | −57.5% | — |
| vol_managed (20d RV target 12%) | +15.0% | **1.15** | **−26.6%** | GO (+53.7% rel DD) |
| vix_managed (VIX target) | +14.7% | 1.13 | −26.5% | GO (+53.8% rel DD) |

2024+ (live regime): constant Sharpe 1.41 / DD −25.9%  →  vol_managed **1.44 / −16.4%**.

**Verdict — H15 GO on both, and STRONGER on the real book.** The vol-managed sizing rule clears the
pre-registered bar on SPY (Sharpe +0.11, DD −28% rel) and clears it *by more* on the actual basket
(Sharpe +0.12, DD **−54% rel**) — because the book is ~1.3× beta, so cutting exposure when realized vol
spikes removes a bigger tail. It de-levers (avg weight 0.69, annRet 24%→15%): this trades raw return for
a much better risk-adjusted profile — a portfolio-policy choice, but on the falsifier's terms it is a
clean GO. Target vol is a dial (12% here); raising it recovers return at the cost of some DD reduction.

**H14 re-validated on the real basket (not just SPY):** re-ran the lead-lag AUC with the *basket* as the
drop target. Same conclusion — **no macro signal leads.** Forward −3% basket-drop AUC: vix_ts_slope
0.588→0.549→0.530 (k=5/10/20, decays to random), vix_level 0.633→0.584→0.562 (decays), credit/breadth/
curve ≈0.50. The strongest forward signal is again plain VIX *level* at k=5 (already a feature). The
iter-12 finding is not a SPY artifact; it holds on the book the system actually trades.

**Status:** H15 is the **first GO** in the R&D program — but it is a *risk-control / sizing* lever, not a
model-metric lever (consistent with "the system's edge is its gating, not its point predictions"). Next
step if pursued = TDD a vol-target multiplier into position sizing (`trading/portfolio.py` sizing path or
a `BaseAgent` exposure scalar), keyed off trailing realized vol and/or VIX level, capped at 2×, with the
12% target as an env dial. Not built yet — this iteration only establishes the premise on real data.

**BUILT 2026-07-05 (XGB-only, OFF by default + shadow) — TDD, branch `feat/vol-target-sizing-xgb`.**
Operator scoped it to the XGBReasoningAgent path. Landed in the pure `xgb_decision.decide_buy` (shared
prod + MC backtester, invariant #10): a new `_vol_target_multiplier(realized_vol, config)` computes
`w = clip(VOL_TARGET_ANN_VOL / rv_20d, 0, VOL_TARGET_CAP)` and scales the Kelly base size **before** the
existing `[2%, MAX_POSITION_SIZE]` clamp, so per-position bounds are untouched — it only reallocates
within the band. `rv_20d` (annualized) is threaded into `BuyContext.realized_vol` via a new
`signal_history.get_latest_rv_20d(symbol)` accessor. Config knobs `VOL_TARGET_SIZING_ENABLED=0` (default
OFF), `VOL_TARGET_ANN_VOL=0.12`, `VOL_TARGET_CAP=2.0`. **Shadow mode:** while disabled, `w` is still
computed and surfaced in the decision reason (`[volx0.25 shadow]`) + logged `[VOL_TARGET]` at INFO, so
the operator can watch the would-be sizing effect before flipping the flag on — no live sizing change
until `=1`. 16 new tests (8 sizing + 6 accessor + 2 wiring), full suite green. Falsifier note: the probe
was a whole-book vol-managed sleeve; this XGB-only per-position implementation is the contained first
step, not the full-book policy — promote to other agents / raise target vol only after live shadow data
confirms the effect on the XGB sleeve.

### Iteration 15 — 2026-08-02 — H16/H17 decision-tree attribution on HistoricalTrendsAgent → both SUPPORTED

> **Numbering note:** Iteration 14 (2026-08-01, H15 re-validation on the current `trading.db` + the
> live-shadow dead-end) is recorded on branch `docs/ledger-iter14-v1.0.1` and is deliberately **not**
> part of this change, which is scoped to the HistoricalTrendsAgent audit alone. The gap is expected.

**Why:** every prior iteration attacked the *XGB/W3* model metrics, and all three axes came back
exhausted. This iteration changes target: audit the **best-performing live agent** —
`HistoricalTrendsAgent`, +15.55% and #1 of 10 — end-to-end, and ask which branch of its decision tree
actually earns the money. Read-only `trading.db` attribution, no retrain, no code change.

**Code-history note:** `backend/agents/historical_trends_agent.py` has exactly **one** commit in its life
(`c3d9710`, 2026-03-29, "replace OpenClawAgent with HistoricalTrendsAgent + Stooq free historical data")
and has never been edited since. Every behavioral change in 4 months came from the shared chassis, not
the agent — most importantly the 2026-05-16 trail tightening (`TRAIL_GIVEBACK_PCT` 0.20→0.10,
`TRAIL_ARM_USD` $25→$100, 4h cooldown) and the 2026-05-17 cash-replay reconciliation (issue #64), which
found **$18,720.78 of phantom cash on this specific agent** (visible as the −$11,271 equity step on
05-18; not a trading loss).

**Sample:** 694 trades (356 BUY / 338 SELL), 2026-03-30 → 2026-07-31, agent_id 82. Realized
**+$15,590.55**; equity **$115,548 (+15.55%)**, rank **1/10**; win rate 60.7% (205W/133L); avg win $362
vs avg loss $440; profit factor 1.27; **Sharpe −0.11**; peak $133,477 (Jul 1) → trough $113,791 (Jul 27)
= **−14.7% drawdown**.

**H16 — exit-branch attribution (the headline):**

| exit branch | n | W | L | win% | total PnL | avg |
|---|---|---|---|---|---|---|
| TRAIL-STOP (BaseAgent) | 223 | 202 | 21 | **90.6%** | **+$70,425** | +$316 |
| BAYES early exit | 3 | 2 | 1 | 66.7% | +$1,665 | +$555 |
| agent's own SELL (`composite < −0.25`) | **4** | 1 | 3 | 25.0% | −$26 | −$6 |
| HARD STOP −8% (risk manager) | 108 | 0 | 108 | **0.0%** | **−$56,474** | −$523 |

The agent's *own* sell rule fired **4 times out of 338 exits (1.2%)** in four months. In a long-only book
where every entry requires momentum ≥ +0.25, a symmetric −0.25 exit essentially never triggers before
the risk manager gets there. **HistoricalTrendsAgent is functionally an entry-only signal wrapped in the
shared risk chassis.** All the P&L — both signs of it — is made by branches that live in `BaseAgent` /
the risk manager. The trail is near-100% win *by construction* (it arms only after +$100 peak uPnL, then
exits on a 10% giveback), and the −8% hard stop is 0% win by construction. The whole loss column is the
**unprotected gap**: positions that never reach +$100 uPnL have nothing between entry and −8%.

Monthly, by branch — the stop side scaled faster than the trail side every single month:

| month | trail | hard stop | net realized |
|---|---|---|---|
| 2026-04 | +$1,028 | −$3,703 | −$999 |
| 2026-05 | +$33,077 | −$12,123 | **+$20,943** |
| 2026-06 | +$24,849 | −$14,370 | +$10,453 |
| 2026-07 | +$11,471 | −$26,278 | **−$14,807** |

May is where the 2026-05-16 trail tightening lands — trail capture jumps 32× month-over-month. July is
the same machine in chop: trail capture collapses to a third while stop losses double, and the quarter's
gain comes back. That is the shape behind **positive return with a negative Sharpe**.

**H17 — pillar and sizing decomposition** (FIFO-paired round trips; entry-side buckets are approximate
where a symbol held overlapping lots — exit-branch and monthly figures above are exact):

*Entry composite vs outcome — conviction inverts above +0.45, and size scales with conviction:*

| composite band | n | win% | total PnL | avg |
|---|---|---|---|---|
| +0.25 … +0.35 | 199 | 60.8% | +$7,652 | +$38 |
| +0.35 … +0.45 | 74 | 62.2% | +$7,786 | **+$105** |
| +0.45 … +0.60 | 43 | 65.1% | +$844 | +$20 |
| +0.60 and up | 22 | 45.5% | **−$691** | −$31 |

`_generate_signal` sizes `portfolio × MAX_POSITION_SIZE × confidence` with `confidence = |composite|`, so
the **only net-negative bucket gets the largest positions**.

*Channel pillar (w=0.30) — works where it's allowed to speak, but it usually isn't:*

| entry position in channel | n | win% | total PnL | avg |
|---|---|---|---|---|
| <25% (near period low) | 7 | 85.7% | +$5,678 | +$811 |
| 25–50% | 18 | 77.8% | +$5,752 | +$320 |
| 50–75% | 80 | 56.2% | +$4,216 | +$53 |
| >75% (near period **high**) | 233 | 60.1% | **−$55** | ≈$0 |

**69% of all entries fire where the channel pillar scores ≈ −1.** The `sma_slope * 5.0` adjustment plus
momentum's larger weight (0.40 vs 0.30) routinely override it. The 25 trades where channel actually
agreed produced $11.4K of the $15.6K total.

*Momentum pillar (w=0.40) — the only pillar earning its weight:* alignment 100% → 213 trades, 60.6% W,
**+$15,561**; 75% → 78, 64.1% W, +$2,828; **50% (split tape) → 40, 50.0% W, −$4,325**; 25% → 7 (n too
small).

*Seasonal pillar (w=0.20) — sign-inverted on the live sample.* Realized-by-month: May (agent bias
**−0.14**, i.e. bearish) = **+$20,943**, the best month; July (bias **+0.07**, bullish) = **−$14,807**,
the worst. It is long-run S&P *index* seasonality applied to single names at 20% of the score.

**Symbols:** semis carried it — AMD +$5,569, ARM +$4,977, QCOM +$3,431, HUM +$3,051, MU +$2,165. Worst:
FATE −$2,137 over 16 round trips (repeatedly re-bought), SRPT −$1,619, AMAT −$1,465, FSLY −$1,227.

**Verdict — H16 and H17 both SUPPORTED, and they relocate the R&D frontier.** After fourteen iterations
of failing to improve the *predictive* layer, the top live agent turns out to make 100% of its money in
the *exit* layer, from a rule with no model in it at all. This is the same conclusion as iter 6/13 stated
from the other direction ("the system's edge is its gating and risk control, not its point predictions") —
now measured on the agent that actually leads the book.

**Next (cheapest first, all backtest-only, no live change):**
1. **Close the trail-arm gap** — time-stop, or a tighter provisional stop that applies only while
   `peak_uPnL < TRAIL_ARM_USD`. This targets the entire −$56,474 column. Operator has scoped the first
   build to **HistoricalTrendsAgent only, env-gated OFF by default** (same containment pattern as H15's
   XGB-only rollout); generalize to the other rule agents only after it proves out.
2. **Zero the seasonal weight** and redistribute to momentum/channel — 20% of the score with an inverted
   live sign is a free correction.
3. **Cap sizing above composite +0.45** — stop putting the biggest bets in the only losing bucket.

Caveat throughout: paper trading, single 4-month sample spanning one bull leg and one chop leg; the
trail's 90.6% win rate is mechanical, not predictive, and must not be read as signal quality.
