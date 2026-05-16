# MC Strategy Backtester — Usage

Offline Monte Carlo backtester that compares candidate XGB feature-filter variants by running each through K bootstrapped alternate market histories.

## Quick start

```bash
cd /c/Users/gl450/trading_app
PYTHONPATH='site-packages;backend' runtime/python/python.exe scripts/mc_backtest_filters.py \
  --variants \
    "current=analyst_score,earnings_score,alpaca_score,iv_rv_score,r_120,macro_vix_norm,macro_spy_5d_back,macro_breadth_back" \
    "swap_both=analyst_score,earnings_score,alpaca_score,iv_rv_score,r_120,macro_vix_norm,macro_spy_10d_back,macro_breadth_10d_back" \
  --n-paths 1000 --path-days 252 --block-size 10 --seed 42
```

Output:
- `scripts/logs/mc_backtest_<timestamp>.md` — headline Markdown table
- `scripts/logs/mc_backtest_<timestamp>.jsonl` — per-(variant,sim) raw outcomes

## CLI arguments

| Flag | Default | Meaning |
|---|---|---|
| `--variants` | (required) | One or more `name=ch1,ch2,...` specs |
| `--n-paths` | 1000 | K — bootstrapped alternate histories |
| `--path-days` | 252 | Length of each path (1 trading year) |
| `--block-size` | 10 | Expected block length (~2 weeks) |
| `--seed` | 42 | RNG seed — same seed → same K paths |

## Performance notes

- Training: ~2 min per variant on 528K rows × 8 channels (full historical).
- Simulation: ~K × n_variants × path_days × n_symbols model predictions. Default 1000 × 2 × 252 × 222 ≈ 110M predict() calls. Expect ~10-30 min total on CPU.
- Memory: O(one path) thanks to lazy `simulate()`. ~200 MB peak.
- To shrink: drop `--n-paths` to 200 for a quick smoke test.

## Architecture

See `docs/superpowers/specs/2026-05-16-mc-strategy-design.md` for the full design rationale (loose-coupling boundaries, why stationary block bootstrap, why paired-sample comparison).

## Reverting if needed

The CLI doesn't modify production state — it only writes to `scripts/logs/`. The training step temporarily sets `XGB_FEATURE_FILTER` in the script's process env, which does NOT affect the running backend's `.env`. To deploy a winning variant in production, update `.env`'s `XGB_FEATURE_FILTER` line manually and restart.
