# Multi-Horizon Lagged Returns Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add five lagged log-return features (`r_1`, `r_5`, `r_20`, `r_60`, `r_120`) as new CNN/XGBoost input channels, computed per-symbol from the existing `price` column. The XGBoost ablation in `docs/equity_feature_engineering_audit.md` showed adding these lifts mean_IC +62% and IR +35% on real data.

**Architecture:** Read-time augmentation — like the existing `_attach_macro_features` pattern. A new `_attach_return_features(df)` helper in `data/signal_history.py` computes the five columns per symbol; called from `get_training_data` (training) and a sibling helper used by `get_recent_window` (inference). No parquet schema change — features are derived at read time, so no backfill is needed and old parquets keep working. `cnn_model.RETURN_CHANNEL_NAMES` exposes them as new channels; `N_CHANNELS` goes 14 → 19. `build_training_windows` includes them in the existing channel-stacking flow.

**Tech Stack:** Python 3.12, pandas, numpy, the existing walk-forward CV harness in `data/cnn_evaluation.py`, unittest via `runtime/python/python.exe -m unittest`.

---

## File Structure

**Create:** none.

**Modify:**
- `backend/data/signal_history.py`
  - Add `RETURN_COLUMNS = ["r_1", "r_5", "r_20", "r_60", "r_120"]` constant.
  - Add `_compute_return_features(df: pd.DataFrame) -> pd.DataFrame` pure function.
  - Wire into `get_training_data` (after the existing `_attach_macro_features` call).
  - Wire into `get_recent_window` so inference produces the same 19 channels.
- `backend/data/cnn_model.py`
  - Add `RETURN_CHANNEL_NAMES` constant (5 entries matching `RETURN_COLUMNS`).
  - Update `N_CHANNELS` arithmetic to include them (`+ len(RETURN_CHANNEL_NAMES)`).
  - Update `build_training_windows` to extend `feat_cols` with `RETURN_COLUMNS` when present.
- `backend/tests/test_signal_history.py` — append unit tests for `_compute_return_features`.
- `backend/tests/test_cnn_model.py` — extend `_make_df` so it includes the new columns; add a test asserting `N_CHANNELS == 19`.
- `CLAUDE.md` — bump architecture comment about the channel count if any.
- `C:\Users\gl450\.claude\projects\C--Users-gl450\memory\trading_app_architecture.md` — update CNN channel breakdown.

**Reused as-is:**
- `data/cnn_evaluation.py` — model-agnostic harness; no edits.
- `data/xgboost_model.py` — flatten over `(C, T)` already; new C just means more features at training time.

**Channel layout (post-change):**
| Block | Count | Channels |
|---|---:|---|
| SOURCE | 5 | analyst_consensus, earnings_magnitude, alpaca_news, yahoo_news, iv_rv_spread |
| AGENT | 2 | agent_consensus, agent_agreement |
| RV | 2 | rv_20d, rv_60d |
| **RETURNS (new)** | **5** | **r_1, r_5, r_20, r_60, r_120** |
| MACRO | 5 | macro_vix_norm, macro_gld_5d_back, macro_tlt_5d_back, macro_spy_5d_back, macro_breadth_back |
| **Total** | **19** | |

The new block is inserted between RV and MACRO so the 5 source channels remain channels 0–4 (anything that depends on the source-channel offset, e.g. `get_learned_weights`, keeps working unchanged).

---

## Task 1: pure-function `_compute_return_features` helper

**Files:**
- Modify: `backend/data/signal_history.py`
- Modify: `backend/tests/test_signal_history.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_signal_history.py` (BEFORE the `if __name__ == "__main__":` line, or create the file if it doesn't exist with a basic header):

```python
class TestComputeReturnFeatures(unittest.TestCase):
    """Lagged log-return feature builder — Tier 1 from
    docs/equity_feature_engineering_audit.md."""

    def _make_df(self, prices, symbol="AAPL"):
        import pandas as pd
        return pd.DataFrame({
            "symbol":      [symbol] * len(prices),
            "snapshot_ts": np.arange(len(prices), dtype=np.float64) * 86400.0,
            "price":       np.asarray(prices, dtype=np.float64),
        })

    def test_adds_five_return_columns(self):
        from data.signal_history import _compute_return_features, RETURN_COLUMNS
        df = self._make_df([100.0] * 200)  # flat prices
        out = _compute_return_features(df)
        for col in RETURN_COLUMNS:
            self.assertIn(col, out.columns)

    def test_log_return_math_correct(self):
        """r_5 at row N = log(price[N] / price[N-5])."""
        from data.signal_history import _compute_return_features
        prices = np.linspace(100.0, 200.0, 200)
        df = self._make_df(prices)
        out = _compute_return_features(df)
        # Pick row 50 — five rows back is row 45
        expected = float(np.log(prices[50] / prices[45]))
        self.assertAlmostEqual(float(out["r_5"].iloc[50]), expected, places=6)

    def test_first_n_rows_have_nan(self):
        """For r_5, the first 5 rows can't compute a 5-row lookback."""
        from data.signal_history import _compute_return_features
        prices = np.linspace(100.0, 200.0, 200)
        df = self._make_df(prices)
        out = _compute_return_features(df)
        self.assertTrue(out["r_5"].iloc[:5].isna().all())
        self.assertFalse(out["r_5"].iloc[5:].isna().any())

    def test_per_symbol_isolation(self):
        """Returns for AAPL must not leak into MSFT and vice versa."""
        from data.signal_history import _compute_return_features
        import pandas as pd
        df = pd.concat([
            self._make_df(np.linspace(100, 200, 100), symbol="AAPL"),
            self._make_df(np.linspace(300, 400, 100), symbol="MSFT"),
        ], ignore_index=True)
        out = _compute_return_features(df)
        # MSFT row 0 must be NaN for r_1 — there's no prior MSFT row, even though
        # the AAPL block above it has prices.
        msft = out[out["symbol"] == "MSFT"].reset_index(drop=True)
        self.assertTrue(np.isnan(msft["r_1"].iloc[0]))

    def test_returns_copy_not_inplace(self):
        """The helper must not mutate the caller's df."""
        from data.signal_history import _compute_return_features, RETURN_COLUMNS
        df = self._make_df([100.0] * 50)
        before_cols = set(df.columns)
        _compute_return_features(df)
        self.assertEqual(set(df.columns), before_cols,
                         "caller's df must keep its original columns")

    def test_handles_zero_or_negative_prices_safely(self):
        """log(price/0) is undefined — must not crash."""
        from data.signal_history import _compute_return_features
        df = self._make_df([100.0, 110.0, 0.0, 120.0, 130.0, 140.0, 150.0])
        out = _compute_return_features(df)
        # No exception raised. Resulting NaN/inf is fine — downstream zero-fills.
        self.assertEqual(len(out), 7)
```

If `test_signal_history.py` doesn't exist, create it with this header above the new test class:

```python
"""Tests for data/signal_history.py — return feature augmentation."""
import unittest

import numpy as np
```

- [ ] **Step 2: Run, expect failure**

```bash
cd /c/Users/gl450/trading_app/backend
PYTHONPATH=../site-packages ../runtime/python/python.exe -m unittest tests.test_signal_history.TestComputeReturnFeatures -v
```

Expected: ImportError on `from data.signal_history import _compute_return_features` (and `RETURN_COLUMNS`).

- [ ] **Step 3: Implement helper**

Open `backend/data/signal_history.py`. Find the `RV_COLUMNS` definition (around line 80) and add immediately after it:

```python
# Lagged log-return columns — augmented at read time by _compute_return_features
# from the per-symbol `price` column. Order matters: must match
# cnn_model.RETURN_CHANNEL_NAMES.
RETURN_COLUMNS = ["r_1", "r_5", "r_20", "r_60", "r_120"]
```

Then find an empty area below `_attach_macro_features` (or `_load_macro_features`) and add this pure function:

```python
def _compute_return_features(df: pd.DataFrame) -> pd.DataFrame:
    """Augment df with per-symbol multi-horizon lagged log returns.

    Adds columns RETURN_COLUMNS = ['r_1', 'r_5', 'r_20', 'r_60', 'r_120'].
    Each row's r_N is `log(price / price.shift(N))` within the symbol's
    own chronological history. Zero-or-negative prices produce NaN/inf,
    which the downstream `np.nan_to_num` zero-fills in build_training_windows.

    Returns a copy — caller's df is unchanged.
    """
    if "price" not in df.columns or "symbol" not in df.columns:
        return df
    out = df.copy()
    for n in (1, 5, 20, 60, 120):
        col = f"r_{n}"
        out[col] = (
            out.groupby("symbol", sort=False)["price"]
               .transform(lambda s: np.log(s / s.shift(n)))
        )
    return out
```

- [ ] **Step 4: Run tests, expect pass**

```bash
PYTHONPATH=../site-packages ../runtime/python/python.exe -m unittest tests.test_signal_history.TestComputeReturnFeatures -v
```

Expected: 6 tests pass.

- [ ] **Step 5: Pre-commit safety check + commit**

```bash
cd /c/Users/gl450/trading_app
git status --porcelain | grep '^[MADRC ][MADRC ]'
```

Must show ONLY:
```
 M backend/data/signal_history.py
 M backend/tests/test_signal_history.py
```
(or `A` / `??` for new test file).

If anything else, STOP.

```bash
git add backend/data/signal_history.py backend/tests/test_signal_history.py
git commit -m "$(cat <<'EOF'
feat(features): add _compute_return_features helper (Tier 1)

Per-symbol multi-horizon lagged log returns: r_1, r_5, r_20, r_60, r_120.
Pure function — operates on a copy of the caller's df. Zero-or-negative
prices produce NaN/inf which the downstream np.nan_to_num zero-fills.

Backed by the XGBoost ablation in docs/equity_feature_engineering_audit.md
which showed adding these lifts mean_IC +62% and IR +35% on the same
walk-forward folds production uses.

Tests: 6 unit tests covering column presence, log-return math, first-N-rows
NaN behaviour, per-symbol isolation, copy-not-inplace, zero-price safety.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: wire into `get_training_data` and `get_recent_window`

**Files:**
- Modify: `backend/data/signal_history.py`
- Modify: `backend/tests/test_signal_history.py`

The helper is callable now but not called. This task wires it in so training and inference both pick up the new columns.

- [ ] **Step 1: Locate the call sites**

```bash
grep -n "_attach_macro_features\|def get_training_data\|def get_recent_window" /c/Users/gl450/trading_app/backend/data/signal_history.py
```

You'll see `_attach_macro_features` is called from `get_training_data`, and `get_recent_window` builds the inference-time window separately. Both need the return-feature augmentation.

- [ ] **Step 2: Write failing integration test**

Append to `backend/tests/test_signal_history.py` (after `TestComputeReturnFeatures`):

```python
class TestGetTrainingDataIncludesReturns(unittest.TestCase):
    """get_training_data must yield the 5 lagged-return columns alongside
    the existing source/agent/rv/macro columns."""

    def test_returns_columns_present(self):
        from data.signal_history import (
            signal_history, RETURN_COLUMNS,
        )
        from unittest.mock import patch
        import pandas as pd

        # Synthesise a small per-symbol df with enough rows for r_5
        rows = 50
        synthetic = pd.DataFrame({
            "symbol":          ["AAPL"] * rows,
            "snapshot_ts":     np.arange(rows, dtype=np.float64) * 86400.0,
            "analyst_score":   np.zeros(rows),
            "earnings_score":  np.zeros(rows),
            "alpaca_score":    np.zeros(rows),
            "yahoo_score":     np.zeros(rows),
            "iv_rv_score":     np.zeros(rows),
            "price":           np.linspace(100, 150, rows),
            "return_1d":       np.full(rows, 0.001),
            "return_5d":       np.full(rows, 0.005),
        })

        # Patch symbols_with_data + _load to return our synthetic frame
        with patch.object(signal_history, "symbols_with_data",
                          return_value=["AAPL"]), \
             patch("data.signal_history._load", return_value=synthetic):
            df = signal_history.get_training_data()

        for col in RETURN_COLUMNS:
            self.assertIn(col, df.columns,
                          f"get_training_data must include {col}")
```

- [ ] **Step 3: Run, expect failure**

```bash
PYTHONPATH=../site-packages ../runtime/python/python.exe -m unittest tests.test_signal_history.TestGetTrainingDataIncludesReturns -v
```

Expected: AssertionError on the column-presence check.

- [ ] **Step 4: Wire helper into `get_training_data`**

Find `def get_training_data` in `backend/data/signal_history.py`. The body calls `_attach_macro_features(df)` somewhere near the end. Right after that call, add:

```python
        df = _compute_return_features(df)
```

The full block should look like (with the surrounding context):

```python
        # ... existing concat / outcome-fill logic ...
        df = _attach_macro_features(df)
        df = _compute_return_features(df)
        return df
```

Match the existing indentation.

- [ ] **Step 5: Wire into `get_recent_window` (and fix pre-existing macro gap)**

Find `def get_recent_window` in `backend/data/signal_history.py` (around line 422). The current function returns a (9, T) array — SOURCE(5) + AGENT(2) + RV(2). It does NOT include macro, even though training_data does.

That's a pre-existing inconsistency: training trains on 14 channels (with macro), but `predict()` receives 9-channel windows from inference. The shape-guard at `cnn_model.predict()` lines 760-761 silently returns `(0.0, "neutral", 0.0)` whenever the channel counts mismatch — which is every cycle in production. We're fixing both gaps here so inference channel order exactly matches training.

Locate the function body. The current structure builds three blocks (`src_parts`, `agent_parts`, `rv_parts`), then `combined = np.hstack([source_data, agent_data, rv_data])`. Replace that construction with:

```python
        df = _apply_cnn_feature_transforms(df)
        # Augment with multi-horizon lagged returns so inference matches the
        # 19-channel training shape (Tier 1 — docs/equity_feature_engineering_audit.md).
        df = _compute_return_features(df)
        recent = df.tail(T)

        # Source channels — zero-fill when a column is absent (old Parquet files)
        src_parts = []
        for col in SOURCE_COLUMNS:
            if col in df.columns:
                src_parts.append(recent[col].values.astype(float).reshape(-1, 1))
            else:
                src_parts.append(np.zeros((len(recent), 1)))
        source_data = np.hstack(src_parts)

        # Agent channels — zero-fill when columns are absent
        agent_parts = []
        for col in AGENT_COLUMNS:
            if col in df.columns:
                agent_parts.append(recent[col].values.astype(float).reshape(-1, 1))
            else:
                agent_parts.append(np.zeros((len(recent), 1)))
        agent_data = np.hstack(agent_parts)

        # RV channels — zero-fill when columns are absent
        rv_parts = []
        for col in RV_COLUMNS:
            if col in df.columns:
                rv_parts.append(recent[col].values.astype(float).reshape(-1, 1))
            else:
                rv_parts.append(np.zeros((len(recent), 1)))
        rv_data = np.hstack(rv_parts)

        # NEW: return channels — zero-fill when columns are absent
        return_parts = []
        for col in RETURN_COLUMNS:
            if col in df.columns:
                return_parts.append(recent[col].values.astype(float).reshape(-1, 1))
            else:
                return_parts.append(np.zeros((len(recent), 1)))
        return_data = np.hstack(return_parts)

        # NEW: macro channels — join the latest macro row per snapshot from
        # __MACRO__.parquet so inference matches training. Reuses
        # _attach_macro_features (which does the merge_asof under the hood).
        # Subset on the same recent window so the join is bounded.
        macro_df = _attach_macro_features(recent[["snapshot_ts"]].copy())
        macro_parts = []
        for col in _MACRO_COLUMN_MAP.values():   # the 5 macro_ channel names
            if col in macro_df.columns:
                macro_parts.append(macro_df[col].values.astype(float).reshape(-1, 1))
            else:
                macro_parts.append(np.zeros((len(recent), 1)))
        macro_data = np.hstack(macro_parts)

        combined = np.hstack([source_data, agent_data, rv_data, return_data, macro_data])  # (≤T, 19)
```

Also update the docstring to reflect the new shape (search for `9 channels` or `9 = 5 source` and replace with `19 channels (5 src + 2 agent + 2 rv + 5 returns + 5 macro)`).

- [ ] **Step 6: Run integration test**

```bash
PYTHONPATH=../site-packages ../runtime/python/python.exe -m unittest tests.test_signal_history -v
```

Expected: all 7 tests pass.

- [ ] **Step 7: Pre-commit + commit**

```bash
cd /c/Users/gl450/trading_app
git status --porcelain | grep '^[MADRC ][MADRC ]'
```

Must show only:
```
 M backend/data/signal_history.py
 M backend/tests/test_signal_history.py
```

```bash
git add backend/data/signal_history.py backend/tests/test_signal_history.py
git commit -m "$(cat <<'EOF'
feat(features): wire _compute_return_features into get_training_data + get_recent_window

Both training and inference paths now produce the 5 lagged-return columns
alongside the existing source/agent/rv/macro channels. No parquet schema
change — features are derived at read time so old parquets keep working.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: expose new channels in `cnn_model.py`

**Files:**
- Modify: `backend/data/cnn_model.py`
- Modify: `backend/tests/test_cnn_model.py`

The window builder needs to know about the new channels. Right now `build_training_windows` only iterates SOURCE / AGENT / RV / MACRO; we add RETURN between RV and MACRO.

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_cnn_model.py` (BEFORE `if __name__ == "__main__":`):

```python
class TestReturnChannelsExposed(unittest.TestCase):
    """Tier 1 from docs/equity_feature_engineering_audit.md — five lagged
    return channels become part of N_CHANNELS."""

    def test_n_channels_is_19(self):
        from data.cnn_model import N_CHANNELS, RETURN_CHANNEL_NAMES
        self.assertEqual(len(RETURN_CHANNEL_NAMES), 5)
        self.assertEqual(N_CHANNELS, 19)  # 5 src + 2 agent + 2 rv + 5 ret + 5 macro

    def test_return_channel_order(self):
        from data.cnn_model import RETURN_CHANNEL_NAMES
        self.assertEqual(
            RETURN_CHANNEL_NAMES,
            ["r_1", "r_5", "r_20", "r_60", "r_120"],
        )

    def test_build_training_windows_includes_return_columns(self):
        """When the df has return columns, build_training_windows packs them
        into the (C, T) tensor between RV and MACRO blocks."""
        import pandas as pd
        from data.cnn_model import build_training_windows, WINDOW_SIZE, N_CHANNELS

        n = WINDOW_SIZE + 50
        df = pd.DataFrame({
            "symbol":          ["AAPL"] * n,
            "snapshot_ts":     np.arange(n, dtype=np.float64) * 86400.0,
            "analyst_score":   np.zeros(n),
            "earnings_score":  np.zeros(n),
            "alpaca_score":    np.zeros(n),
            "yahoo_score":     np.zeros(n),
            "iv_rv_score":     np.zeros(n),
            "agent_consensus": np.zeros(n),
            "agent_agreement": np.zeros(n),
            "rv_20d":          np.full(n, 0.20),
            "rv_60d":          np.full(n, 0.20),
            "r_1":             np.full(n, 0.001),
            "r_5":             np.full(n, 0.005),
            "r_20":            np.full(n, 0.02),
            "r_60":            np.full(n, 0.06),
            "r_120":           np.full(n, 0.12),
            "macro_vix_norm":      np.full(n, 0.5),
            "macro_gld_5d_back":   np.zeros(n),
            "macro_tlt_5d_back":   np.zeros(n),
            "macro_spy_5d_back":   np.zeros(n),
            "macro_breadth_back":  np.zeros(n),
            "return_1d":       np.full(n, 0.001),
            "return_5d":       np.full(n, 0.005),
        })
        X, y, w, t = build_training_windows(df, T=WINDOW_SIZE)
        # Channel count includes the new returns
        self.assertEqual(X.shape[1], N_CHANNELS)
        self.assertEqual(X.shape[1], 19)
```

- [ ] **Step 2: Run, expect failure**

```bash
PYTHONPATH=../site-packages ../runtime/python/python.exe -m unittest tests.test_cnn_model.TestReturnChannelsExposed -v
```

Expected: ImportError on `RETURN_CHANNEL_NAMES`, or `N_CHANNELS == 14` (the existing value).

- [ ] **Step 3: Add `RETURN_CHANNEL_NAMES` and bump `N_CHANNELS`**

In `backend/data/cnn_model.py`, find the `MACRO_CHANNEL_NAMES` definition (around line 107). Add this BEFORE the `MACRO_CHANNEL_NAMES = [...]` block:

```python
# Per-symbol lagged log-return channels — Tier 1 from
# docs/equity_feature_engineering_audit.md. Order must match
# data.signal_history.RETURN_COLUMNS.
RETURN_CHANNEL_NAMES: List[str] = [
    "r_1",    # 1-row lagged log return
    "r_5",    # 5-row
    "r_20",   # 20-row
    "r_60",   # 60-row
    "r_120",  # 120-row
]
```

Then find the `N_CHANNELS = (...)` block (around line 123). Update to:

```python
N_CHANNELS = (
    len(SOURCE_NAMES)
    + len(AGENT_CHANNEL_NAMES)
    + len(RV_CHANNEL_NAMES)
    + len(RETURN_CHANNEL_NAMES)
    + len(MACRO_CHANNEL_NAMES)
)  # 19
```

- [ ] **Step 4: Update `build_training_windows` to include the return columns**

In the same file, find the `feat_cols = ...` construction inside `build_training_windows` (around line 414). The current code looks like:

```python
    feat_cols = [c for c in SOURCE_COLUMNS if c in df.columns]
    if has_agent:
        feat_cols = feat_cols + AGENT_COLUMNS
    if has_rv:
        feat_cols = feat_cols + RV_COLUMNS
    if has_macro:
        feat_cols = feat_cols + MACRO_CHANNEL_NAMES
```

Add a `has_returns` check and insert RETURN_COLUMNS between RV and MACRO so the channel order is `SOURCE → AGENT → RV → RETURNS → MACRO`. Replace the block above with:

```python
    has_agent = all(c in df.columns for c in AGENT_COLUMNS)
    has_rv    = all(c in df.columns for c in RV_COLUMNS)
    has_returns = all(c in df.columns for c in RETURN_COLUMNS)
    has_macro = all(c in df.columns for c in MACRO_CHANNEL_NAMES)
    feat_cols = [c for c in SOURCE_COLUMNS if c in df.columns]
    if has_agent:
        feat_cols = feat_cols + AGENT_COLUMNS
    if has_rv:
        feat_cols = feat_cols + RV_COLUMNS
    if has_returns:
        feat_cols = feat_cols + RETURN_COLUMNS
    if has_macro:
        feat_cols = feat_cols + MACRO_CHANNEL_NAMES
```

Update the import at the top of `build_training_windows` (the `from data.signal_history import` block) to include `RETURN_COLUMNS`:

```python
    from data.signal_history import (  # avoid circular
        SOURCE_COLUMNS, AGENT_COLUMNS, RV_COLUMNS, RETURN_COLUMNS,
        _apply_cnn_feature_transforms,
    )
```

- [ ] **Step 5: Run tests**

```bash
PYTHONPATH=../site-packages ../runtime/python/python.exe -m unittest tests.test_cnn_model -v
```

Expected: all `test_cnn_model` tests pass, including the 3 new ones. Some pre-existing tests may now fail because they constructed dfs without the new return columns AND expected `X.shape[1] == 14`. For each such failing test:

- If it just asserts `X.shape[1] == N_CHANNELS` (or whatever), it should still pass since we updated N_CHANNELS.
- If it hardcodes `14` literally, change it to `N_CHANNELS` (or 19).
- If it passes a synthetic df without the return columns, that's fine — `has_returns` falls back to False and the channel count drops to 14 (graceful degrade).

Read failures one at a time and fix minimally.

- [ ] **Step 6: Run cnn_reasoning_agent + xgboost_model regression**

```bash
PYTHONPATH=../site-packages ../runtime/python/python.exe -m unittest tests.test_cnn_reasoning_agent tests.test_xgboost_model -v
```

Expected: all green. Both backends adapt to the new channel count via `X.shape[1]` (CNN rebuilds its first conv layer; XGBoost's flatten just sees more features).

- [ ] **Step 7: Pre-commit + commit**

```bash
cd /c/Users/gl450/trading_app
git status --porcelain | grep '^[MADRC ][MADRC ]'
```

Must show only:
```
 M backend/data/cnn_model.py
 M backend/tests/test_cnn_model.py
```

```bash
git add backend/data/cnn_model.py backend/tests/test_cnn_model.py
git commit -m "$(cat <<'EOF'
feat(features): expose 5 lagged-return channels (N_CHANNELS 14→19)

RETURN_CHANNEL_NAMES inserted between RV and MACRO so source channels
remain at indices 0-4 (preserving get_learned_weights and the LLM
prompt's source-display logic).

build_training_windows includes them when present in the df; falls back
to the prior 14-channel layout when get_training_data hasn't been
augmented yet, so old parquets and tests keep working.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: end-to-end XGBoost re-run on real data

**Files:**
- Modify: `backend/tests/test_xgboost_model.py` (one new integration test)

This task confirms that after the production pipeline (`signal_history.get_training_data → build_training_windows → SignalXGBoost.fit`) is wired end-to-end, the model trains with 19 channels and metrics improve.

- [ ] **Step 1: Append integration test**

Add this to `backend/tests/test_xgboost_model.py` (before `if __name__ == "__main__":`):

```python
class TestXGBoostFitsWith19Channels(unittest.TestCase):
    """Integration: SignalXGBoost.fit succeeds on 19-channel input
    (5 src + 2 agent + 2 rv + 5 returns + 5 macro)."""

    def test_fit_accepts_19_channels(self):
        from data.xgboost_model import SignalXGBoost
        rng = np.random.default_rng(0)
        n, c, T = 600, 19, 10
        X = rng.standard_normal((n, c, T)).astype(np.float32) * 0.5
        y = (X[:, 0, :].mean(axis=1) * 0.05).astype(np.float32)
        t = np.linspace(0, 90 * 86400.0, n, dtype=np.float64)

        m = SignalXGBoost(T=T, n_channels=c)
        m.fit(X, y, t, n_folds=3, min_val_days=14)
        self.assertTrue(m.is_trained)
        # Predict on a single 19-channel window must work
        pred, direction, conf = m.predict(X[0])
        self.assertIsInstance(pred, float)
        self.assertIn(direction, ("bull", "bear", "neutral"))
```

- [ ] **Step 2: Run**

```bash
PYTHONPATH=../site-packages ../runtime/python/python.exe -m unittest tests.test_xgboost_model.TestXGBoostFitsWith19Channels -v
```

Expected: pass on first run — SignalXGBoost.fit doesn't hardcode channel count; it trains on whatever shape it's given.

- [ ] **Step 3: Sanity-check with real data via the experiment script**

Re-run the existing ablation:

```bash
cd /c/Users/gl450/trading_app
PYTHONPATH='site-packages;backend' runtime/python/python.exe scripts/xgb_feature_experiment.py 2>&1 | tail -15
```

Confirm Variant B (`B_plus_returns`) still scores ~mean_IC=+0.128, IR=+1.45 — the script directly mirrors what `_compute_return_features` does, so it serves as a separate confirmation that the production pipeline will see the same lift.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_xgboost_model.py
git commit -m "test(xgb): pin 19-channel fit/predict path

After the lagged-return channels were added, SignalXGBoost must train
and predict against (N, 19, T) input cleanly. This test fixes the new
channel count so a future feature-set change either updates the test
or surfaces a regression.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: docs + memory update

**Files:**
- Modify: `CLAUDE.md`
- Modify: `C:\Users\gl450\.claude\projects\C--Users-gl450\memory\trading_app_architecture.md`

- [ ] **Step 1: Update CLAUDE.md (if it has a channel count anywhere)**

```bash
grep -n "14 channels\|N_CHANNELS\|14ch\|14-channel" /c/Users/gl450/trading_app/CLAUDE.md
```

If any line references the count (e.g. `14 channels` or `N_CHANNELS=14`), update to `19 channels` / `N_CHANNELS=19`. Add a note explaining the change references `docs/equity_feature_engineering_audit.md`. If grep returns nothing, skip this step.

- [ ] **Step 2: Update memory architecture doc**

Append to `C:\Users\gl450\.claude\projects\C--Users-gl450\memory\trading_app_architecture.md`:

```markdown

## Multi-Horizon Lagged Returns (Tier 1 — added 2026-05-02)
- 5 new CNN/XGBoost channels: `r_1`, `r_5`, `r_20`, `r_60`, `r_120` per-symbol log returns from the existing `price` column.
- Computed at read time by `data.signal_history._compute_return_features` (no parquet schema change). Wired into `get_training_data` and `get_recent_window` so training and inference produce the same 19 channels.
- Channel order (post-change): SOURCE(5) + AGENT(2) + RV(2) + RETURNS(5) + MACRO(5) = 19. Source channels stay at indices 0–4 so `get_learned_weights` and the LLM-prompt source display work unchanged.
- Backed by the XGBoost ablation in `docs/equity_feature_engineering_audit.md`: variant B (baseline + returns) lifted mean_IC from +0.079 to **+0.128 (+62%)** and IR from +1.08 to **+1.45 (+35%)** on 33k samples × 212 symbols. This was the single highest-value feature-set addition tested.
```

- [ ] **Step 3: Commit (in-repo files only)**

If CLAUDE.md was modified:

```bash
cd /c/Users/gl450/trading_app
git add CLAUDE.md
git commit -m "docs: bump channel count to 19 (lagged returns added)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

If only memory files were touched, no commit needed (memory lives outside git).

---

## Task 6: open PR for review

**This is a non-code task.**

- [ ] **Step 1: Push branch + open PR**

```bash
cd /c/Users/gl450/trading_app
git push -u origin feat/multi-horizon-lagged-returns 2>&1 | tail -5
```

Then open the PR. Use `gh pr create --base feat/xgboost-model-backend --head feat/multi-horizon-lagged-returns --title "Add multi-horizon lagged return features (Tier 1)"` with a body summarising:
- The five new channels (r_1, r_5, r_20, r_60, r_120) computed per-symbol from `price`.
- Read-time augmentation (no parquet schema change).
- Channel layout (SOURCE / AGENT / RV / RETURNS / MACRO = 19).
- Ablation result from `docs/equity_feature_engineering_audit.md` — +62% IC, +35% IR.
- Test counts (6 helper unit tests + 1 integration test + 3 channel-exposure tests + 1 fit-with-19-channels test).
- Stacking note: targets `feat/xgboost-model-backend` (PR #8) so the XGBoost backend automatically picks up the new features when both PRs land.

---

## What's intentionally NOT in this plan

- **Sector classification + sector-relative momentum (Tier 2 from the audit).** Needs a yfinance sector lookup + caching layer; deferred until Tier 1 is shipped and measured on the next walk-forward retrain.
- **Cross-sectional ranks "done right".** v1 regressed performance; needs a redesigned trading-day bucketing. Separate plan when we have a design.
- **Calendar features.** Empirically hurt IC on this dataset.
- **Fundamentals.** Needs a fundamental data feed; out of scope for this Tier 1 ship.
