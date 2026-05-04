"""
Temporal 1-D CNN for learning optimal composite signal source weights.

Architecture (GLU-gated)
------------------------
  Input       : (batch, 19, T) — 19 channels (5 source + 2 agent + 2 RV + 5 returns + 5 macro) × T time-steps
  GatedConv1d : 7  → 16, k=3  — conv_main(x) * sigmoid(conv_gate(x))
  BatchNorm1d(16) + Dropout(0.2)
  GatedConv1d : 16 → 32, k=3  — higher-order cross-source patterns
  BatchNorm1d(32) + Dropout(0.2)
  GatedConv1d : 32 → 16, k=3  — compression
  AdaptiveAvgPool1d(1)          — global temporal pooling → (batch, 16)
  Linear  : 16 → 8
  ReLU
  Linear  : 8  → 1             — predicted 1-day forward return

Total parameters ≈ 6 800 — 2× first-gen due to dual-path gating.

GLU gating
----------
  Each GatedConv1d block runs two parallel Conv1d layers (main + gate).
  The sigmoid gate outputs 0–1 per channel per timestep, multiplied
  element-wise against the main path:
      output = conv_main(x) ⊗ σ(conv_gate(x))
  This lets the network suppress noisy indicators (e.g., RSI in trending
  markets, MACD in range-bound markets) on each forward pass without
  any manual feature engineering.

Learned source importance
-------------------------
  After training, sum |weight| magnitudes in the first GatedConv1d's
  conv_main layer across output channels and kernel positions to get a
  per-source importance vector, then normalise to [0, 1] → these replace
  the hardcoded SOURCE_WEIGHTS.

Device selection
----------------
  CUDA  → if torch.cuda.is_available()
  MPS   → elif torch.backends.mps.is_available()  (Apple Silicon)
  CPU   → otherwise
"""
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── optional torch import ─────────────────────────────────────────────────────

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import DataLoader, TensorDataset
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False
    logger.warning("cnn_model: torch not available — install pytorch to enable GPU training")

# ── constants ─────────────────────────────────────────────────────────────────

_MODEL_DIR             = os.path.join(os.path.dirname(__file__), "models")
_MODEL_PATH            = os.path.join(_MODEL_DIR, "signal_cnn.pt")
_HISTORY_FILENAME      = "training_history.jsonl"


def _training_history_path() -> str:
    """Path to the append-only training-history JSONL, sibling to the model checkpoint.
    Derived from _MODEL_PATH at call time so test patches of _MODEL_PATH alone reroute
    both files together."""
    return os.path.join(os.path.dirname(_MODEL_PATH), _HISTORY_FILENAME)

SOURCE_NAMES: List[str] = [
    "analyst_consensus",
    "earnings_magnitude",  # channel 1: |earnings_score| — Task #22, see _apply_cnn_feature_transforms
    "alpaca_news",
    "yahoo_news",
    "iv_rv_spread",        # channel 4: IV − RV_20d spread scored to [-1, +1]
]
# Note: congressional_trades was demoted from CNN input → LLM context-only
# (Task #20). 3% coverage with corr -0.001 means it carried no usable signal
# for the CNN. signal_aggregator still scores it; signal_history still records
# congress_score; the LLM still receives it for catalyst-style reasoning.

# Agent channels appended after the 5 source channels
AGENT_CHANNEL_NAMES: List[str] = [
    "agent_consensus",   # channel 5: performance-weighted directional vote  (-1 to +1)
    "agent_agreement",   # channel 6: fraction of agents that agree (0 to 1)
]

# Realized volatility channels — annualized from daily close prices (252-day basis)
# The GLU gates learn to suppress these in trending markets where RV is uninformative
# and amplify them in high-vol regimes where BSM-style vol signals add edge.
RV_CHANNEL_NAMES: List[str] = [
    "rv_20d",   # channel 7: 20-day rolling realized vol (short-term vol regime)
    "rv_60d",   # channel 8: 60-day rolling realized vol (medium-term vol regime)
]

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

# Macro environment channels — joined from __MACRO__.parquet by date
# Absent in old Parquet files; build_training_windows degrades to 9ch without them.
MACRO_CHANNEL_NAMES: List[str] = [
    "macro_vix_norm",       # channel 9:  VIX / 30 clipped to [0, 3]
    # Task #24: trailing (was forward — leaked future direction into training,
    # collapsed val WFE from -0.034 to -0.346). `_back` suffix is permanent
    # to make the semantics unambiguous in code review and force re-backfill.
    "macro_gld_5d_back",    # channel 10: GLD 5-day TRAILING return
    "macro_tlt_5d_back",    # channel 11: TLT 5-day trailing return
    "macro_spy_5d_back",    # channel 12: SPY 5-day trailing return
    "macro_breadth_back",   # channel 13: (IWM - SPY) trailing 5d, clipped [-1, 1]
]

# Total full input channels: 5 source + 2 agent + 2 RV + 5 returns + 5 macro = 19
# build_training_windows degrades gracefully (drops 5 returns or 5 macro) when those cols absent.
# Old checkpoints (15ch from before Task #20) load fine — predict() guards against
# shape mismatch and the net auto-rebuilds to the correct channel count on the
# next 24h retrain cycle.
N_CHANNELS = (
    len(SOURCE_NAMES)
    + len(AGENT_CHANNEL_NAMES)
    + len(RV_CHANNEL_NAMES)
    + len(RETURN_CHANNEL_NAMES)
    + len(MACRO_CHANNEL_NAMES)
)  # 19

# Fixed-order list of the 19 channel COLUMN names (df column keys, not the
# pretty *_NAMES used for the LLM display). Used by XGB_FEATURE_FILTER to
# resolve channel names → indices. Order MUST match build_training_windows.
#
# Derived from data.feature_catalog.CATALOG, the registered single source
# of truth for channel definitions. Adding a channel = one CATALOG entry,
# not a hand-edit here.
from data.feature_catalog import channel_names as _catalog_channel_names
ALL_CHANNEL_COLUMNS: List[str] = _catalog_channel_names()
assert len(ALL_CHANNEL_COLUMNS) == N_CHANNELS

# Renormalized after dropping congressional_trades (was 0.11; remaining sum 0.89).
# Each weight = old_weight / 0.89.
_DEFAULT_WEIGHTS: Dict[str, float] = {
    "analyst_consensus":    0.337,
    "earnings_magnitude":   0.213,   # Task #22: was "earnings_surprise" (signed); now |earnings_score|
    "alpaca_news":          0.169,
    "yahoo_news":           0.112,
    "iv_rv_spread":         0.169,
}


def _append_training_history(record: Dict) -> None:
    """Append a single JSON record (one line) to the training-history log."""
    path = _training_history_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception as exc:
        logger.warning("SignalCNN: failed to append training history: %s", exc)


def load_training_history(limit: Optional[int] = None) -> List[Dict]:
    """
    Read training-history records (oldest first, newest last).

    Parameters
    ----------
    limit : int, optional — return only the most recent `limit` records.

    Returns
    -------
    List of dicts. Empty list if the file does not yet exist.
    Malformed lines are skipped silently.
    """
    path = _training_history_path()
    if not os.path.exists(path):
        return []
    records: List[Dict] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception as exc:
        logger.warning("SignalCNN: failed to read training history: %s", exc)
        return []
    if limit is not None and limit > 0:
        return records[-limit:]
    return records

MIN_TRAIN_SAMPLES             = 100  # minimum labelled rows before training starts
WINDOW_SIZE                   = 10   # T: rolling window length fed to the CNN
WALKFORWARD_FOLDS             = 3
WALKFORWARD_MIN_VAL_DAYS      = 14
WALKFORWARD_EMBARGO_BARS      = 1
_SECS_PER_DAY                 = 86_400.0

# Label horizon — production switched 2026-05-03 from 5d to 10d.
# XGBoost ablation (docs/equity_feature_engineering_audit.md follow-up):
#   5d, 6-channel:  mean_IC=+0.21, last_WFE=+0.07,  $5,232/yr/$10k
#  10d, 8-channel:  mean_IC=+0.40, last_WFE=+0.25,  $5,640/yr/$10k
# 10d wins on every metric (last_WFE 5x better) and halves turnover.
#
# A horizon switch invalidates any currently-saved booster's predictions
# until the next walk-forward retrain rebuilds with the new targets.
# predict() loads fine but its outputs are old-scale until then.
LABEL_HORIZON_COL             = "return_10d"
# Days in the horizon, parsed from LABEL_HORIZON_COL ("return_<N>d"). Single
# source of truth so changing LABEL_HORIZON_COL automatically rescales the
# direction/confidence thresholds below.
LABEL_HORIZON_DAYS            = int(LABEL_HORIZON_COL.removeprefix("return_").removesuffix("d"))
# Confidence + direction thresholds scale with sqrt(time) since cross-sectional
# return vol scales the same way. Anchored to the 5d production values:
#   5d  → FULL_CONF_RET = 0.10,   DIR_THRESHOLD = 0.010
#   10d → FULL_CONF_RET ≈ 0.141,  DIR_THRESHOLD ≈ 0.0141
import math as _math   # local import — keep module-level imports clean
_HORIZON_SCALE                = _math.sqrt(LABEL_HORIZON_DAYS / 5.0)
LABEL_HORIZON_FULL_CONF_RET   = 0.10  * _HORIZON_SCALE
LABEL_HORIZON_DIR_THRESHOLD   = 0.010 * _HORIZON_SCALE


def _compute_wfe(
    y_true: list,
    y_pred: list,
) -> tuple:
    """
    Compute Walk-Forward Efficiency (WFE) as the OOS R² on the validation set.

        WFE = 1 − SS_res / SS_tot
            = 1 − Σ(y_pred − y_true)² / Σ(y_true − ȳ)²

    This is analogous to the standard Walk-Forward Efficiency metric used in
    quantitative research (healthy ≥ 0.70, degraded 0.50–0.70, poor < 0.50).

    Parameters
    ----------
    y_true : list[float]   actual validation labels
    y_pred : list[float]   model predictions on the same samples

    Returns
    -------
    (wfe: float | None, status: str)
        status ∈ {"HEALTHY", "DEGRADED", "POOR", "UNTRAINED"}
    """
    n = len(y_true)
    if n == 0 or len(y_pred) == 0 or n != len(y_pred):
        return None, "UNTRAINED"

    mean_y   = sum(y_true) / n
    ss_tot   = sum((v - mean_y) ** 2 for v in y_true)
    ss_res   = sum((p - t) ** 2 for p, t in zip(y_pred, y_true))

    if ss_tot < 1e-12:
        # All labels identical (degenerate fold) — WFE undefined
        return None, "UNTRAINED"

    wfe = 1.0 - ss_res / ss_tot
    wfe = max(-10.0, wfe)  # sanity clamp — can't be worse than −10

    if wfe >= 0.70:
        status = "HEALTHY"
    elif wfe >= 0.50:
        status = "DEGRADED"
    else:
        status = "POOR"

    return round(wfe, 4), status


def _diagnose(train_mse: float, val_mse: float, ratio: float) -> str:
    """
    Return a plain-English diagnosis based on final train and val MSE.

    Thresholds are tuned for 1-day returns clipped at ±20%:
      Typical 1-day move  0.5–2%  → squared → 0.000025–0.0004
      Healthy train MSE   0.0002–0.002
      Healthy val/train ratio  1.0–2.5x

    Returns one of:
      OVERFIT_MEMORIZING  — train MSE suspiciously low (model memorised data)
      OVERFIT             — val MSE >> train MSE (not generalising)
      UNDERFIT            — both MSEs high (model isn't learning signal)
      OK                  — within normal bounds
    """
    if train_mse < 1e-5:
        return "OVERFIT_MEMORIZING"
    if ratio > 3.0:
        return "OVERFIT"
    if train_mse > 0.005 and val_mse > 0.005:
        return "UNDERFIT"
    return "OK"


def _device() -> "torch.device":
    if not HAS_TORCH:
        return None
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


# ── model definition ──────────────────────────────────────────────────────────

if HAS_TORCH:
    class GatedConv1d(nn.Module):
        """
        Gated Linear Unit (GLU) convolution block.

        Runs two parallel Conv1d layers over the same input:
            output = conv_main(x) ⊗ σ(conv_gate(x))

        The sigmoid gate produces per-channel values in [0, 1] that multiply
        the main path element-wise.  This lets the network learn to suppress
        noisy indicators on each forward pass — no separate ReLU needed; the
        gate IS the nonlinearity.
        """

        def __init__(
            self,
            in_channels: int,
            out_channels: int,
            kernel_size: int,
            padding: int = 0,
        ) -> None:
            super().__init__()
            self.conv_main = nn.Conv1d(in_channels, out_channels, kernel_size, padding=padding)
            self.conv_gate = nn.Conv1d(in_channels, out_channels, kernel_size, padding=padding)

        def forward(self, x: "torch.Tensor") -> "torch.Tensor":
            return self.conv_main(x) * torch.sigmoid(self.conv_gate(x))


def _build_glu_net(n_channels: int = N_CHANNELS) -> "nn.Module":
    """Construct the GLU-gated CNN as an nn.Sequential."""
    return nn.Sequential(
        # Block 1 — GLU gate replaces ReLU as the nonlinearity
        GatedConv1d(n_channels, 16, kernel_size=3, padding=1),
        nn.BatchNorm1d(16),
        nn.Dropout(0.3),
        # Block 2
        GatedConv1d(16, 32, kernel_size=3, padding=1),
        nn.BatchNorm1d(32),
        nn.Dropout(0.3),
        # Block 3 — compress
        GatedConv1d(32, 16, kernel_size=3, padding=1),
        # Global pool
        nn.AdaptiveAvgPool1d(1),   # → (batch, 16, 1)
        nn.Flatten(),              # → (batch, 16)
        # Head
        nn.Linear(16, 8),
        nn.ReLU(),
        nn.Linear(8, 1),
    )


def _build_net(n_channels: int = N_CHANNELS) -> "nn.Module":
    """Legacy non-gated architecture — kept for loading old checkpoints only."""
    return nn.Sequential(
        # Block 1
        nn.Conv1d(n_channels, 16, kernel_size=3, padding=1),
        nn.BatchNorm1d(16),
        nn.ReLU(),
        nn.Dropout(0.2),
        # Block 2
        nn.Conv1d(16, 32, kernel_size=3, padding=1),
        nn.BatchNorm1d(32),
        nn.ReLU(),
        nn.Dropout(0.2),
        # Block 3 — compress
        nn.Conv1d(32, 16, kernel_size=3, padding=1),
        nn.ReLU(),
        # Global pool
        nn.AdaptiveAvgPool1d(1),   # → (batch, 16, 1)
        nn.Flatten(),              # → (batch, 16)
        # Head
        nn.Linear(16, 8),
        nn.ReLU(),
        nn.Linear(8, 1),
    )


# ── training data builder ─────────────────────────────────────────────────────

def build_training_windows(
    df: pd.DataFrame,
    T: int = WINDOW_SIZE,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Convert a labelled history DataFrame into (X, y, w, t) numpy arrays.

    Parameters
    ----------
    df : pd.DataFrame
        Output of SignalHistoryStore.get_training_data() — must contain
        SOURCE_COLUMNS and 'return_1d'.  Optionally contains agent columns
        ('agent_consensus', 'agent_agreement', 'top_agent_correct') and RV
        columns ('rv_20d', 'rv_60d').
    T  : int
        Rolling window size.

    Returns
    -------
    X : (N, C, T)  float32  — feature windows
    y : (N,)       float32  — forward returns at LABEL_HORIZON_COL horizon,
                              clipped to ±20%
    w : (N,)       float32  — sample weights (1.0 default; higher when top
                              agent was confirmed correct)
    t : (N,)       float64  — snapshot_ts of each window's last row,
                              for walk-forward CV
    """
    from data.signal_history import (  # avoid circular
        SOURCE_COLUMNS, AGENT_COLUMNS, RV_COLUMNS, RETURN_COLUMNS,
        _apply_cnn_feature_transforms,
    )

    # Task #22: feed |earnings_score| to the CNN. Direction has corr -0.029 with
    # 1d return (noise); magnitude has corr +0.143 with realized vol (signal).
    # Returns a copy — caller's df keeps signed values.
    df = _apply_cnn_feature_transforms(df)

    has_agent   = all(c in df.columns for c in AGENT_COLUMNS)
    has_rv      = all(c in df.columns for c in RV_COLUMNS)
    has_returns = all(c in df.columns for c in RETURN_COLUMNS)
    has_macro   = all(c in df.columns for c in MACRO_CHANNEL_NAMES)
    feat_cols = [c for c in SOURCE_COLUMNS if c in df.columns]
    if has_agent:
        feat_cols = feat_cols + AGENT_COLUMNS
    if has_rv:
        feat_cols = feat_cols + RV_COLUMNS
    if has_returns:
        feat_cols = feat_cols + RETURN_COLUMNS
    if has_macro:
        feat_cols = feat_cols + MACRO_CHANNEL_NAMES
    n_feat    = len(feat_cols)
    if n_feat == 0:
        logger.warning("build_training_windows: no recognised feature columns in df — returning empty")
        return (
            np.empty((0, 0, T), dtype=np.float32),
            np.empty(0, dtype=np.float32),
            np.empty(0, dtype=np.float32),
            np.empty(0, dtype=np.float64),
        )
    # Layer 2.4: label horizon is configurable via LABEL_HORIZON_COL (default
    # "return_5d"). Falls back to "return_1d" if the configured column isn't
    # present (e.g. very early signal_history rows written before backfill).
    label_col = LABEL_HORIZON_COL if LABEL_HORIZON_COL in df.columns else "return_1d"
    if label_col != LABEL_HORIZON_COL:
        logger.warning(
            f"build_training_windows: {LABEL_HORIZON_COL} missing from df — "
            f"falling back to return_1d (model will train on shorter horizon)"
        )

    X_list: List[np.ndarray] = []
    y_list: List[float]      = []
    w_list: List[float]      = []
    t_list: List[float]      = []

    for symbol, grp in df.groupby("symbol"):
        grp    = grp.sort_values("snapshot_ts").reset_index(drop=True)
        feats  = grp[feat_cols].values.astype(np.float32)
        rets   = grp[label_col].values.astype(np.float32)
        ts     = grp["snapshot_ts"].values.astype(np.float64)

        if "top_agent_correct" in grp.columns:
            correct = grp["top_agent_correct"].values.astype(float)
            weights = np.where(np.isnan(correct), 0.75,
                               np.where(correct == 1.0, 1.0, 0.5))
        else:
            weights = np.ones(len(grp), dtype=np.float32)

        for i in range(len(grp)):
            if np.isnan(rets[i]):
                continue
            start  = max(0, i - T + 1)
            window = feats[start : i + 1]
            if len(window) < T:
                pad    = np.zeros((T - len(window), n_feat), dtype=np.float32)
                window = np.vstack([pad, window])
            window = np.nan_to_num(window, nan=0.0)
            X_list.append(window.T)
            y_list.append(float(np.clip(rets[i], -0.20, 0.20)))
            w_list.append(float(weights[i]))
            t_list.append(float(ts[i]))

    if not X_list:
        return (
            np.empty((0, n_feat, T), dtype=np.float32),
            np.empty(0, dtype=np.float32),
            np.empty(0, dtype=np.float32),
            np.empty(0, dtype=np.float64),
        )

    return (
        np.stack(X_list).astype(np.float32),
        np.array(y_list, dtype=np.float32),
        np.array(w_list, dtype=np.float32),
        np.array(t_list, dtype=np.float64),
    )


# ── main model wrapper ────────────────────────────────────────────────────────

class SignalCNN:
    """
    Wrapper around the PyTorch CNN with training, inference, persistence,
    and learned-weight extraction.

    Falls back gracefully to default SOURCE_WEIGHTS when torch is unavailable
    or the model has not yet been trained.
    """

    def __init__(self, T: int = WINDOW_SIZE, lr: float = 3e-4,
                 n_channels: int = N_CHANNELS):
        self.T                  = T
        self._n_channels        = n_channels
        self._trained           = False
        self._train_ts          = 0.0
        self._train_loss:       List[float] = []
        self._val_loss:         List[float] = []   # validation MSE per epoch
        self._n_train:          int = 0            # samples used for training
        self._n_val:            int = 0            # samples held out for validation
        self._split_idx:        int = 0            # index where val set begins (chronological split)
        self._early_stop_epoch: Optional[int] = None  # epoch training stopped at (early stop)
        self._wfe:              Optional[float] = None   # Walk-Forward Efficiency (OOS R²)
        self._wfe_status:       str = "UNTRAINED"        # HEALTHY / DEGRADED / POOR / UNTRAINED
        self._scheduler                        = None    # ReduceLROnPlateau instance
        self._dev                              = _device()
        self._fold_metrics:     List[Dict] = []
        self._mean_ic:          Optional[float] = None
        self._ir:               Optional[float] = None
        self._mean_wfe:         Optional[float] = None
        self._calibration:      List[Dict] = []

        if HAS_TORCH:
            self._net = _build_glu_net(n_channels).to(self._dev)
            # AdamW: correct weight decay for adaptive optimizers (unlike plain Adam)
            self._opt = optim.AdamW(self._net.parameters(), lr=lr, weight_decay=1e-4)
        else:
            self._net = None
            self._opt = None

    # ── training ─────────────────────────────────────────────────────────────

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        t: np.ndarray,
        epochs: int = 80,
        batch_size: int = 32,
        sample_weights: Optional[np.ndarray] = None,
        patience: int = 15,
        n_folds: int = WALKFORWARD_FOLDS,
        min_val_days: int = WALKFORWARD_MIN_VAL_DAYS,
        embargo_bars: int = WALKFORWARD_EMBARGO_BARS,
    ) -> None:
        """
        Train using walk-forward cross-validation.

        For each of `n_folds` folds, train a fresh net on the fold's train set
        and evaluate on its val set. The FINAL fold's trained net is the one
        kept on `self._net` (it has the most data + most recent training).

        Aggregate metrics across folds:
          mean_wfe : average OOS R² across folds (more stable than single split)
          mean_ic  : average Spearman rank corr across folds
          ir       : mean(IC) / std(IC) — edge stability
          calibration : quintile buckets from the last fold's val predictions
        """
        from data.cnn_evaluation import (
            compute_ic, compute_ir, compute_calibration, walkforward_folds,
        )

        if not HAS_TORCH or self._net is None:
            logger.warning("SignalCNN.fit: torch not available, skipping training")
            return
        if len(X) < MIN_TRAIN_SAMPLES:
            logger.info(f"SignalCNN.fit: only {len(X)} samples (need {MIN_TRAIN_SAMPLES}), skipping")
            return

        actual_channels = X.shape[1]
        if actual_channels != self._n_channels:
            logger.info(
                f"SignalCNN: rebuilding GLU net for {actual_channels} input channels "
                f"(was {self._n_channels})"
            )
            self._n_channels = actual_channels
            lr = self._opt.param_groups[0]["lr"] if self._opt else 3e-4
            self._net = _build_glu_net(actual_channels).to(self._dev)
            self._opt = optim.AdamW(self._net.parameters(), lr=lr, weight_decay=1e-4)

        folds = walkforward_folds(
            t, n_folds=n_folds,
            min_val_days=min_val_days,
            embargo_bars=embargo_bars,
        )
        if not folds:
            logger.warning(
                f"SignalCNN.fit: dataset too short for {n_folds} folds × "
                f"{min_val_days}d val — skipping training"
            )
            return

        fold_metrics: List[Dict] = []
        ics: List[float] = []
        wfes: List[float] = []
        last_val_pred: List[float] = []
        last_val_true: List[float] = []
        last_train_loss: List[float] = []
        last_val_loss:   List[float] = []
        last_n_train = 0
        last_n_val   = 0
        last_actual_epochs = 0

        for fold_i, (tr_idx, va_idx) in enumerate(folds):
            net = _build_glu_net(actual_channels).to(self._dev)
            opt = optim.AdamW(net.parameters(), lr=3e-4, weight_decay=1e-4)
            scheduler = optim.lr_scheduler.ReduceLROnPlateau(
                opt, mode="min", factor=0.5, patience=5, min_lr=1e-6
            )

            X_train = torch.from_numpy(X[tr_idx]).to(self._dev)
            y_train = torch.from_numpy(y[tr_idx]).unsqueeze(1).to(self._dev)
            X_val   = torch.from_numpy(X[va_idx]).to(self._dev)
            y_val   = torch.from_numpy(y[va_idx]).unsqueeze(1).to(self._dev)
            w_train = (
                torch.from_numpy(sample_weights[tr_idx].astype(np.float32))
                     .unsqueeze(1).to(self._dev)
                if sample_weights is not None else None
            )

            ds = (TensorDataset(X_train, y_train) if w_train is None
                  else TensorDataset(X_train, y_train, w_train))
            loader  = DataLoader(ds, batch_size=batch_size, shuffle=True, drop_last=False)
            loss_fn = nn.MSELoss(reduction="none")

            train_losses: List[float] = []
            val_losses:   List[float] = []
            best_val   = float("inf")
            no_improve = 0
            actual_epochs = 0

            net.train()
            for epoch in range(epochs):
                total, n_seen = 0.0, 0
                for batch in loader:
                    xb, yb = batch[0], batch[1]
                    wb = batch[2] if len(batch) == 3 else None
                    opt.zero_grad()
                    pred     = net(xb)
                    per_loss = loss_fn(pred, yb)
                    loss     = (per_loss * wb).mean() if wb is not None else per_loss.mean()
                    loss.backward()
                    nn.utils.clip_grad_norm_(net.parameters(), max_norm=1.0)
                    opt.step()
                    total  += loss.item() * len(xb)
                    n_seen += len(xb)
                train_losses.append(total / max(1, n_seen))

                net.eval()
                with torch.no_grad():
                    val_pred = net(X_val)
                    val_mse  = float(loss_fn(val_pred, y_val).mean().item())
                val_losses.append(val_mse)
                net.train()
                scheduler.step(val_mse)

                actual_epochs = epoch + 1
                if val_mse < best_val - 1e-6:
                    best_val   = val_mse
                    no_improve = 0
                else:
                    no_improve += 1
                if no_improve >= patience:
                    break

            net.eval()
            with torch.no_grad():
                vp = net(X_val).squeeze().cpu().numpy().reshape(-1)
            vt = y_val.squeeze().cpu().numpy().reshape(-1)
            wfe_val, _ = _compute_wfe(vt.tolist(), vp.tolist())
            ic_val = compute_ic(vp, vt)
            val_window_days = float((t[va_idx].max() - t[va_idx].min()) / _SECS_PER_DAY)

            fold_metrics.append({
                "fold":            fold_i,
                "n_train":         int(len(tr_idx)),
                "n_val":           int(len(va_idx)),
                "val_window_days": round(val_window_days, 2),
                "val_mse":         float(val_losses[-1]) if val_losses else None,
                "wfe":             wfe_val,
                "ic":              ic_val,
                "epochs":          actual_epochs,
            })
            if wfe_val is not None:
                wfes.append(wfe_val)
            ics.append(ic_val)

            if fold_i == len(folds) - 1:
                self._net = net
                self._opt = opt
                self._scheduler = scheduler
                last_train_loss   = train_losses
                last_val_loss     = val_losses
                last_n_train      = int(len(tr_idx))
                last_n_val        = int(len(va_idx))
                last_actual_epochs = actual_epochs
                last_val_pred = vp.tolist()
                last_val_true = vt.tolist()
            else:
                # Release per-fold tensors + net before the next fold builds new
                # ones. Critical on the RTX 2060 (6 GB VRAM) where llama3.1:8b
                # already occupies ~4.7 GB; without this, three fold trainings
                # can OOM mid-retrain.
                del net, opt, scheduler, ds, loader
                del X_train, y_train, X_val, y_val
                if w_train is not None:
                    del w_train
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

        # Aggregate metrics
        self._fold_metrics = fold_metrics
        self._mean_ic      = float(np.mean(ics)) if ics else 0.0
        self._ir           = compute_ir(ics)
        self._mean_wfe     = float(np.mean(wfes)) if wfes else None
        self._calibration  = compute_calibration(
            np.asarray(last_val_pred), np.asarray(last_val_true), n_buckets=5
        )

        # Last-fold legacy fields (used by /api/cnn-diagnostics + checkpoint)
        self._train_loss        = last_train_loss
        self._val_loss          = last_val_loss
        self._n_train           = last_n_train
        self._n_val             = last_n_val
        self._trained           = True
        self._train_ts          = time.time()
        self._early_stop_epoch  = last_actual_epochs
        self._wfe, self._wfe_status = _compute_wfe(last_val_true, last_val_pred)
        self._split_idx         = last_n_train

        mean_ic_str = f"{self._mean_ic:.4f}" if self._mean_ic is not None else "n/a"
        ir_str      = f"{self._ir:.2f}"      if self._ir      is not None else "n/a"
        logger.info(
            f"SignalCNN: walk-forward fit complete | folds={len(folds)} | "
            f"mean_WFE={self._mean_wfe} mean_IC={mean_ic_str} IR={ir_str} | "
            f"last_fold WFE={self._wfe} [{self._wfe_status}]"
        )

    # ── inference ─────────────────────────────────────────────────────────────

    def predict(self, x: np.ndarray) -> Tuple[float, str, float]:
        """
        Single-window inference.

        Parameters
        ----------
        x : (C, T) float array — from SignalHistoryStore.get_recent_window()

        Returns
        -------
        pred_return : float       predicted forward return at LABEL_HORIZON_COL
                                  (default 5-day; e.g. 0.04 = +4%)
        direction   : str         'bull' | 'neutral' | 'bear'
        confidence  : float 0–1   magnitude-scaled
                                  (LABEL_HORIZON_FULL_CONF_RET → 1.0)
        """
        if not HAS_TORCH or self._net is None or not self._trained:
            return 0.0, "neutral", 0.0

        # Guard against channel mismatch during the transition period when old
        # checkpoints are loaded but get_recent_window now returns more channels.
        # The net rebuilds automatically on the next walk-forward retrain.
        if x.shape[0] != self._n_channels:
            return 0.0, "neutral", 0.0

        self._net.eval()
        with torch.no_grad():
            x_t    = torch.from_numpy(x.astype(np.float32)).unsqueeze(0).to(self._dev)
            pred   = float(self._net(x_t).squeeze().cpu().item())

        # Direction + confidence calibration scales with the label horizon
        # (Layer 2.4): 5d returns are ~sqrt(5) wider than 1d. The constants
        # LABEL_HORIZON_DIR_THRESHOLD and LABEL_HORIZON_FULL_CONF_RET capture
        # the per-horizon scale so callers don't need to know which horizon
        # the model was trained on.
        if pred > LABEL_HORIZON_DIR_THRESHOLD:
            direction = "bull"
        elif pred < -LABEL_HORIZON_DIR_THRESHOLD:
            direction = "bear"
        else:
            direction = "neutral"
        confidence = float(min(1.0, abs(pred) / LABEL_HORIZON_FULL_CONF_RET))
        return pred, direction, confidence

    # ── learned weights ───────────────────────────────────────────────────────

    def get_learned_weights(self) -> Dict[str, float]:
        """
        Extract per-source importance from the first Conv1d layer.

        Importance[c_in] = Σ_{c_out, k} |W[c_out, c_in, k]|
        Normalised to sum to 1.0.

        Returns the hardcoded defaults if the model is untrained.
        """
        if not HAS_TORCH or self._net is None or not self._trained:
            return _DEFAULT_WEIGHTS.copy()

        # First layer in the Sequential is GatedConv1d (GLU) or Conv1d (legacy).
        # Read weights from the main path only — the gate path is a control signal,
        # not a feature extractor.
        first_block = self._net[0]
        if hasattr(first_block, "conv_main"):
            W = first_block.conv_main.weight.detach().cpu().numpy()   # (16, C, 3)
        else:
            W = first_block.weight.detach().cpu().numpy()             # legacy
        importance = np.abs(W).sum(axis=(0, 2))        # (C,) — sum over C_out and K

        # Only report importance for the SOURCE channels (first 5).
        # Agent channels (5, 6) are deliberately excluded so the
        # learned weights table always covers the 5 data sources.
        source_importance = importance[:len(SOURCE_NAMES)]   # (5,)
        total = source_importance.sum()
        if total < 1e-10:
            return _DEFAULT_WEIGHTS.copy()
        source_importance /= total
        return dict(zip(SOURCE_NAMES, source_importance.tolist()))

    # ── persistence ───────────────────────────────────────────────────────────

    def save(self) -> None:
        if not HAS_TORCH or self._net is None:
            return
        os.makedirs(_MODEL_DIR, exist_ok=True)
        torch.save(
            {
                "arch":              "glu",   # identifies the GLU architecture
                "state_dict":        self._net.state_dict(),
                "opt_state":         self._opt.state_dict(),
                "trained":           self._trained,
                "train_ts":          self._train_ts,
                "train_loss":        self._train_loss,
                "val_loss":          self._val_loss,
                "n_train":           self._n_train,
                "n_val":             self._n_val,
                "split_idx":         self._split_idx,
                "early_stop_epoch":  self._early_stop_epoch,
                "T":                 self.T,
                "n_channels":        self._n_channels,
                "wfe":               self._wfe,
                "wfe_status":        self._wfe_status,
            },
            _MODEL_PATH,
        )
        logger.info(f"SignalCNN: saved → {_MODEL_PATH}")

        # Append to the training-history log (per-retrain JSONL) for trajectory analysis.
        # signal_cnn.pt is overwritten each run; this log is append-only.
        if self._trained:
            final_train = self._train_loss[-1] if self._train_loss else None
            final_val   = self._val_loss[-1]   if self._val_loss   else None
            overfit_ratio = (
                round(final_val / final_train, 4)
                if final_train is not None and final_val is not None and final_train > 1e-10
                else None
            )
            weights = self.get_learned_weights()
            delta   = {k: round(weights[k] - _DEFAULT_WEIGHTS[k], 4) for k in SOURCE_NAMES}
            ts_iso  = (
                datetime.fromtimestamp(self._train_ts, tz=timezone.utc).isoformat()
                if self._train_ts else None
            )
            _append_training_history({
                "train_ts":         self._train_ts,
                "train_ts_iso":     ts_iso,
                "n_train":          self._n_train,
                "n_val":            self._n_val,
                "n_channels":       self._n_channels,
                "epochs_completed": self._early_stop_epoch,
                "final_train_mse":  final_train,
                "final_val_mse":    final_val,
                "overfit_ratio":    overfit_ratio,
                "wfe":              self._wfe,
                "wfe_status":       self._wfe_status,
                "learned_weights":  weights,
                "weight_delta":     delta,
                # Walk-forward CV metrics (added 2026-04-27)
                "fold_metrics":     self._fold_metrics,
                "mean_ic":          self._mean_ic,
                "ir":               self._ir,
                "mean_wfe":         self._mean_wfe,
                "calibration":      self._calibration,
            })

    def load(self) -> bool:
        if not HAS_TORCH or self._net is None:
            return False
        if not os.path.exists(_MODEL_PATH):
            return False
        try:
            ckpt        = torch.load(_MODEL_PATH, map_location=self._dev, weights_only=True)
            saved_ch    = ckpt.get("n_channels", 5)   # default 5 for pre-agent-column models
            saved_arch  = ckpt.get("arch", "legacy")  # "glu" or "legacy"
            if saved_ch != self._n_channels or saved_arch != "glu":
                # Rebuild net to match saved channel count and architecture
                logger.info(
                    f"SignalCNN: loading saved model — arch={saved_arch} ch={saved_ch} "
                    f"(current arch=glu ch={self._n_channels}) — rebuilding net"
                )
                self._n_channels = saved_ch
                lr = self._opt.param_groups[0]["lr"] if self._opt else 3e-4
                builder = _build_glu_net if saved_arch == "glu" else _build_net
                self._net = builder(saved_ch).to(self._dev)
                self._opt = optim.Adam(self._net.parameters(), lr=lr)
            self._net.load_state_dict(ckpt["state_dict"])
            self._opt.load_state_dict(ckpt["opt_state"])
            self._trained           = ckpt.get("trained", False)
            self._train_ts          = ckpt.get("train_ts", 0.0)
            self._train_loss        = ckpt.get("train_loss", [])
            self._val_loss          = ckpt.get("val_loss", [])
            self._n_train           = ckpt.get("n_train", 0)
            self._n_val             = ckpt.get("n_val", 0)
            self._split_idx         = ckpt.get("split_idx", 0)
            self._early_stop_epoch  = ckpt.get("early_stop_epoch", None)
            self._wfe               = ckpt.get("wfe", None)
            self._wfe_status        = ckpt.get("wfe_status", "UNTRAINED")
            logger.info(f"SignalCNN: loaded ← {_MODEL_PATH} ({saved_ch}ch)")
            return True
        except Exception as exc:
            logger.warning(f"SignalCNN: load failed: {exc}")
            return False

    # ── properties ────────────────────────────────────────────────────────────

    @property
    def is_trained(self) -> bool:
        return self._trained

    @property
    def last_train_time(self) -> float:
        return self._train_ts

    @property
    def device(self) -> str:
        return str(self._dev) if self._dev else "unavailable"

    @property
    def mean_wfe(self) -> Optional[float]:
        """Mean walk-forward WFE across folds — None until first fit() completes."""
        return self._mean_wfe

    @property
    def wfe_status(self) -> str:
        """Last-fold WFE status: HEALTHY | DEGRADED | POOR | UNTRAINED."""
        return self._wfe_status

    def training_summary(self) -> Dict:
        weights   = self.get_learned_weights()
        hardcoded = _DEFAULT_WEIGHTS
        delta     = {k: round(weights[k] - hardcoded[k], 4) for k in SOURCE_NAMES}

        final_train = self._train_loss[-1] if self._train_loss else None
        final_val   = self._val_loss[-1]   if self._val_loss   else None

        overfit_ratio = None
        diagnosis     = "UNTRAINED"
        if final_train is not None and final_val is not None and final_train > 1e-10:
            overfit_ratio = round(final_val / final_train, 3)
            diagnosis     = _diagnose(final_train, final_val, overfit_ratio)

        return {
            # Identity
            "trained":         self._trained,
            "device":          self.device,
            "train_ts":        self._train_ts,
            "n_channels":      self._n_channels,
            # Sample counts
            "n_train":         self._n_train,
            "n_val":           self._n_val,
            "split_idx":       self._split_idx,
            # Final MSE values
            "final_train_mse": final_train,
            "final_val_mse":   final_val,
            # Overfitting diagnosis
            "overfit_ratio":   overfit_ratio,  # val/train — ideally 1.0–2.5
            "diagnosis":       diagnosis,       # OK | OVERFIT | OVERFIT_MEMORIZING | UNDERFIT
            # Walk-Forward Efficiency (OOS R²)
            "walk_forward_efficiency": self._wfe,        # None before training
            "wfe_status":              self._wfe_status,  # HEALTHY | DEGRADED | POOR | UNTRAINED
            # Training controls
            "early_stop_epoch": self._early_stop_epoch,  # epoch training stopped at
            # Full loss curves (one float per epoch) for plotting
            "train_loss_curve": self._train_loss,
            "val_loss_curve":   self._val_loss,
            # Learned source weights
            "learned_weights": weights,
            "weight_delta":    delta,
            # Legacy key kept for backward compatibility
            "final_mse":       final_train,
            # Walk-forward CV metrics (added 2026-04-27)
            "fold_metrics":  self._fold_metrics,
            "mean_ic":       self._mean_ic if self._mean_ic is not None else 0.0,
            "ir":            self._ir if self._ir is not None else 0.0,
            "mean_wfe":      self._mean_wfe,
            "calibration":   self._calibration,
        }


# Module-level singleton — imported by cnn_reasoning_agent and market_data
signal_cnn = SignalCNN()
