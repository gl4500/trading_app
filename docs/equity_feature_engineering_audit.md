# XGBoost Feature-Set Audit: Doc vs. Reality

**Goal:** review `docs/equity_feature_engineering.md` against the current trading_app feature set, then run an XGBoost ablation on the existing `signal_history` parquets to see which doc-recommended additions actually move the needle.

**Date:** 2026-05-02
**Data:** 33,075 rows × 212 symbols, 2025-01-27 → 2026-05-01.
**Harness:** the same 3-fold walk-forward CV (`data/cnn_evaluation.walkforward_folds`, ≥14-day val, 1-bar embargo) the production XGBoost backend uses.

---

## Gap analysis: doc vs. current feature set

The CNN/XGBoost backend currently consumes these 14 channels per (C, T=10) window:

| # | Channel | Source |
|---|---|---|
| 0 | analyst_consensus | yfinance recommendations |
| 1 | earnings_magnitude | abs(earnings surprise) |
| 2 | alpaca_news | Alpaca News API + keyword scoring |
| 3 | yahoo_news | Yahoo + FinBERT |
| 4 | iv_rv_spread | yfinance options ATM IV − rv_20d |
| 5 | agent_consensus | other agents' performance-weighted vote |
| 6 | agent_agreement | fraction of agents agreeing |
| 7 | rv_20d | 20-day annualized realized vol |
| 8 | rv_60d | 60-day annualized realized vol |
| 9 | macro_vix_norm | VIX / 30 |
| 10 | macro_gld_5d_back | GLD 5d trailing return |
| 11 | macro_tlt_5d_back | TLT 5d trailing return |
| 12 | macro_spy_5d_back | SPY 5d trailing return |
| 13 | macro_breadth_back | (IWM − SPY) trailing 5d |

Mapping each section of the doc against the above:

### Section 1 — Price/return-based features ❌ Mostly missing
| Doc says | Have? | Notes |
|---|---|---|
| Multi-horizon log returns (1d, 5d, 20d, 60d, 252d) | ❌ | `return_1d` and `return_5d` exist but as **labels**, not features. Lagged returns are absent. |
| 12-1 month momentum (skip-1) | ❌ | Not computed. |
| Realized vol (multi-horizon) | ✅ | `rv_20d`, `rv_60d`. |
| Vol-of-vol | ❌ | |
| Downside/upside vol asymmetry | ❌ | |
| Beta to market | ❌ | |
| Idiosyncratic volatility | ❌ | |
| 1-week return as reversal feature | ❌ | |
| Cross-sectional rank of technicals (RSI within sector) | ❌ | Technicals computed but not ranked. |

**This is the biggest gap.** The CNN/XGBoost is essentially blind to recent price action — it sees vol but not direction.

### Section 2 — Fundamentals ❌ Entirely missing
- Value (P/E, P/B, FCF yield) ❌
- Quality (ROE, ROIC, gross profitability) ❌
- Growth (earnings growth, revenue growth) ❌
- Earnings surprise: ⚠️ have `earnings_magnitude` (absolute, not signed SUE)
- Capital structure (buybacks, insider trading) ⚠️ have `congressional_trades` (CONTEXT_ONLY for the model)

Adding these requires a fundamental data feed. yfinance has some (`ticker.info["trailingPE"]`, `forwardPE`, `priceToBook`, `returnOnEquity`, `freeCashflow`) but they're not point-in-time.

### Section 3 — Cross-sectional / relative ❌ Entirely missing
- Sector-relative features ❌
- Market-relative momentum ❌
- Z-scores within universe ❌
- Sector classification ❌

### Section 4 — Microstructure ⚠️ Partial
- Liquidity (Amihud, dollar volume) ❌
- Order flow imbalance ❌
- Short interest ❌
- Options-derived ✅ (`iv_rv_spread`)

### Section 5 — Macro ⚠️ Partial
- 10y yield ⚠️ via `macro_tlt_5d_back` (TLT proxy)
- VIX ✅ (`macro_vix_norm`)
- Credit spreads ❌
- Dollar index (DXY) ❌
- Oil/copper ⚠️ (`macro_gld_5d_back` — gold only)

### Section 6 — Sentiment ✅ Mostly covered
- News sentiment ✅ (alpaca_news + yahoo_news with FinBERT)
- Analyst features ✅ (analyst_consensus)
- Alternative data ❌
- Social media sentiment ❌

### Section 7 — Time/event features ❌ Entirely missing
- Day-of-week, day-of-month ❌
- Days since/to earnings ❌
- Index inclusion ❌

### Section 8 — Alpha101 formulas ❌ Entirely missing

---

## Ablation experiment

Five XGBoost variants on the same walk-forward folds. Hyperparameters identical to production: `max_depth=6, eta=0.05, subsample=0.8, n_estimators=500, early_stopping=30`.

| Variant | # features | folds | mean_IC | IR | mean_WFE | val MSE |
|---|---:|---:|---:|---:|---:|---:|
| A — baseline (current 9 cols at last timestep) | 10 | 3 | **+0.079** | +1.08 | −0.097 | 0.00476 |
| **B — A + multi-horizon returns** (r_1, r_5, r_20, r_60, r_120) | **15** | **3** | **+0.128** | **+1.45** | **−0.077** | **0.00471** |
| C — B + mom_120_20 + vol_ratio + vol_diff | 18 | 3 | +0.082 | +1.31 | −0.116 | 0.00489 |
| D — C + cross-sectional ranks | 22 | 3 | +0.039 | +0.63 | −0.114 | 0.00485 |
| E — D + calendar (dow / dom / month) | 25 | 3 | +0.072 | +0.86 | −0.082 | 0.00469 |

**Winner: variant B.** Adding five lagged log returns (`r_1`, `r_5`, `r_20`, `r_60`, `r_120`) — which is two grep-and-add lines in `signal_history.record_snapshot` plus reading them from the parquet at training time — moves mean IC from +0.079 to **+0.128 (62% lift)** and IR from 1.08 to **1.45 (35% lift)**.

---

## What's surprising

1. **Just adding lagged returns is the single biggest win.** This matches the doc's claim that "price/return-based features" are the foundation, but the magnitude of the lift on actual production data is striking.

2. **Cross-sectional ranks regressed performance** (variant D, IC −69% vs B). Counterintuitive given the doc's emphasis. Plausible explanations:
   - Bucketing by hour gave too few peers per bucket on this dataset.
   - 212 symbols is small for stable rank features.
   - The naïve `groupby("hour-bucket").rank(pct=True)` doesn't survive when timestamps within a "snapshot" aren't synchronized — different symbols get scanned at slightly different times.

   These are fixable, but on the v1 implementation cross-sectional ranks make things worse.

3. **`mom_120_20` (12-1 momentum proxy) didn't help.** Probable cause: only ~15 months of data and snapshots aren't strictly daily, so a 120-row lookback is noisier than the doc's true 12-month version on calendar dailies.

4. **Calendar features (dow/dom/month) didn't help and added a touch of noise.** With only 15 months of data the calendar effects (turn-of-month, January effect) don't have enough exemplars to fit.

5. **All variants still have negative WFE.** mean_IC > 0 means rank correlation is positive — the model is sorting stocks correctly on average — but val MSE is still slightly above the variance of `y_val` (which gives WFE < 0). The model has directional edge but slight magnitude miscalibration. **Both metrics improving together is the goal**; B is closest to that.

6. **The current 10-feature baseline already has IC = +0.079 and IR = +1.08.** That's a non-trivial starting point. The "WFE = −0.43" we saw on the CNN was largely a CNN-specific noise-fitting issue + the broken val split — XGBoost on the same 9 features straight-out delivers a measurable edge.

---

## Recommended changes (priority order)

### Tier 1 — ship this now (cheap, big lift)

**1. Add multi-horizon lagged returns to the feature set.** Five new columns: `r_1`, `r_5`, `r_20`, `r_60`, `r_120` computed from the `price` column.

   - **Where:** new helper in `data/signal_history.py` that augments the training df with these, called from `_attach_macro_features` (or a parallel `_attach_return_features`).
   - **Cost:** ~30 lines, no new data fetches.
   - **Expected impact (from this experiment):** +62% IC, +35% IR on the XGBoost backend.

### Tier 2 — needs new data (medium lift, more work)

**2. Sector classification + sector-relative momentum.** yfinance's `Ticker.info["sector"]` works (free). Add a per-symbol sector lookup, cache it, then compute `r_{horizon} − sector_avg_r_{horizon}`.

**3. Beta to market.** Already computable: regress per-symbol returns on SPY returns over a rolling window.

**4. Days to / since earnings.** yfinance's `Ticker.calendar` gives next earnings date. Add as two features.

### Tier 3 — needs broader data feeds (likely big lift, big work)

**5. Fundamentals (P/E, ROE, gross profitability).** yfinance has snapshots; for backtest integrity you'd want a point-in-time provider eventually.

**6. Idiosyncratic volatility.** Residual from `rolling_regress(stock_ret ~ market_ret)`. Computable from existing data, but adds ~50 lines.

**7. Cross-sectional ranks done right.** Build proper snapshot buckets (group by trading day, not hour) and ensure all 212 symbols get a rank every bucket. The naïve version regressed performance; the right version should help.

### Tier 4 — defer

**8. WorldQuant Alpha101 formulas.** Mining literature; questionable whether they still produce edge in 2026.

**9. Calendar features.** Don't add — empirically hurts on this dataset.

**10. Alternative data (satellite, foot traffic).** Out of scope for hobbyist.

---

## What to NOT do

- **Don't add cross-sectional ranks naïvely.** The v1 (group by `snapshot_ts // 3600`) regressed performance. Either redesign the bucketing (group by trading day) or skip until we have a good design.

- **Don't add the calendar features.** Empirically hurts; not enough data for these effects to surface.

- **Don't tune XGBoost hyperparameters before fixing the feature set.** Feature engineering buys orders of magnitude more than hyperparameter search at this scale.

---

## Reproduce / extend

```bash
PYTHONPATH='site-packages;backend' runtime/python/python.exe scripts/xgb_feature_experiment.py
```

To add a variant: append to `assemble_variants()` in `scripts/xgb_feature_experiment.py` and re-run.

---

## Implementation plan for Tier 1 (lagged returns)

1. **Pure-function helper** in `data/signal_history.py`:
   ```python
   def _attach_return_features(df: pd.DataFrame) -> pd.DataFrame:
       """Add r_1, r_5, r_20, r_60, r_120 lagged log returns per symbol."""
   ```
2. **Wire into `get_training_data`** alongside `_attach_macro_features`.
3. **Update `cnn_model.SOURCE_NAMES`** and `RETURN_CHANNEL_NAMES` to expose the new channels to the existing window builder.
4. **Tests:** unit-test the helper on synthetic per-symbol data; integration-test that `build_training_windows` returns the new columns.
5. **Memory + CLAUDE.md sync** as usual.
6. **A/B before/after on production retrain** to confirm the +62% IC lift carries over.

This is a self-contained ~150-line change and doesn't require any data fetches the app doesn't already do.
