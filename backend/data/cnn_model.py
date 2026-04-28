"""
Temporal 1-D CNN for learning optimal composite signal source weights.

Architecture (GLU-gated)
------------------------
  Input       : (batch, 10, T) — 10 channels (6 source + 2 agent + 2 RV) × T time-steps
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

# Total full input channels: 5 source + 2 agent + 2 RV + 5 macro = 14
# build_training_windows degrades gracefully to 9 channels when macro cols absent.
# Old checkpoints (15ch from before Task #20) load fine — predict() guards against
# shape mismatch and the net auto-rebuilds to the correct channel count on the
# next 24h retrain cycle.
N_CHANNELS = (
    len(SOURCE_NAMES)
    + len(AGENT_CHANNEL_NAMES)
    + len(RV_CHANNEL_NAMES)
    + len(MACRO_CHANNEL_NAMES)
)  # 14

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

MIN_TRAIN_SAMPLES = 100  # minimum labelled rows before training starts
WINDOW_SIZE       = 10   # T: rolling window length fed to the CNN


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
    y : (N,)       float32  — 1-day forward returns (clipped to ±20%)
    w : (N,)       float32  — sample weights (1.0 default; higher when top
                              agent was confirmed correct)
    t : (N,)       float64  — snapshot_ts of each window's last row,
                              for walk-forward CV
    """
    from data.signal_history import (  # avoid circular
        SOURCE_COLUMNS, AGENT_COLUMNS, RV_COLUMNS,
        _apply_cnn_feature_transforms,
    )

    # Task #22: feed |earnings_score| to the CNN. Direction has corr -0.029 with
    # 1d return (noise); magnitude has corr +0.143 with realized vol (signal).
    # Returns a copy — caller's df keeps signed values.
    df = _apply_cnn_feature_transforms(df)

    has_agent = all(c in df.columns for c in AGENT_COLUMNS)
    has_rv    = all(c in df.columns for c in RV_COLUMNS)
    has_macro = all(c in df.columns for c in MACRO_CHANNEL_NAMES)
    feat_cols = [c for c in SOURCE_COLUMNS if c in df.columns]
    if has_agent:
        feat_cols = feat_cols + AGENT_COLUMNS
    if has_rv:
        feat_cols = feat_cols + RV_COLUMNS
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

    X_list: List[np.ndarray] = []
    y_list: List[float]      = []
    w_list: List[float]      = []
    t_list: List[float]      = []

    for symbol, grp in df.groupby("symbol"):
        grp    = grp.sort_values("snapshot_ts").reset_index(drop=True)
        feats  = grp[feat_cols].values.astype(np.float32)
        rets   = grp["return_1d"].values.astype(np.float32)
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
        epochs: int = 80,
        batch_size: int = 32,
        sample_weights: Optional[np.ndarray] = None,
        patience: int = 15,
    ) -> None:
        """
        Train on (X, y) arrays from build_training_windows().
        Runs entirely in the calling thread — use asyncio.to_thread() for
        non-blocking execution from async code.

        Parameters
        ----------
        X              : (N, C, T) float32
        y              : (N,)      float32
        sample_weights : (N,)      float32, optional — rows where the top
                         agent was confirmed correct get weight 1.0;
                         incorrect rows get 0.5; unknown rows get 0.75.
                         When None, all samples are weighted equally.
        patience       : int — early stopping: stop if val loss doesn't
                         improve for this many consecutive epochs.
        """
        if not HAS_TORCH or self._net is None:
            logger.warning("SignalCNN.fit: torch not available, skipping training")
            return
        if len(X) < MIN_TRAIN_SAMPLES:
            logger.info(f"SignalCNN.fit: only {len(X)} samples (need {MIN_TRAIN_SAMPLES}), skipping")
            return

        # Rebuild net if channel count changed (e.g. first run with agent cols)
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

        # ── Chronological train / validation split (80 / 20) ─────────────────
        # Val set is the LAST 20% of samples to avoid temporal data leakage.
        # Random shuffling across time would let the model train on future data,
        # inflating val metrics and producing a model that doesn't generalise.
        N       = len(X)
        n_val   = max(5, int(N * 0.2))
        n_train = N - n_val

        train_idx = torch.arange(0, n_train)
        val_idx   = torch.arange(n_train, N)
        self._split_idx = n_train   # expose for tests / diagnostics

        X_all = torch.from_numpy(X).to(self._dev)                    # (N, C, T)
        y_all = torch.from_numpy(y).unsqueeze(1).to(self._dev)        # (N, 1)
        w_all = torch.from_numpy(
            sample_weights.astype(np.float32)
        ).unsqueeze(1).to(self._dev) if sample_weights is not None else None

        X_train, y_train = X_all[train_idx], y_all[train_idx]
        X_val,   y_val   = X_all[val_idx],   y_all[val_idx]
        w_train          = w_all[train_idx] if w_all is not None else None

        dataset = (
            TensorDataset(X_train, y_train)
            if w_train is None
            else TensorDataset(X_train, y_train, w_train)
        )
        loader  = DataLoader(dataset, batch_size=batch_size, shuffle=True, drop_last=False)
        loss_fn = nn.MSELoss(reduction="none")

        # ── LR scheduler ─────────────────────────────────────────────────────
        scheduler = optim.lr_scheduler.ReduceLROnPlateau(
            self._opt, mode="min", factor=0.5, patience=5, min_lr=1e-6
        )

        train_losses: List[float] = []
        val_losses:   List[float] = []

        # ── Early stopping state ──────────────────────────────────────────────
        best_val_loss    = float("inf")
        no_improve_count = 0
        actual_epochs    = 0

        self._net.train()
        for epoch in range(epochs):
            # ── training step ──────────────────────────────────────────────
            total, n = 0.0, 0
            for batch in loader:
                xb, yb = batch[0], batch[1]
                wb     = batch[2] if len(batch) == 3 else None
                self._opt.zero_grad()
                pred     = self._net(xb)
                per_loss = loss_fn(pred, yb)
                loss     = (per_loss * wb).mean() if wb is not None else per_loss.mean()
                loss.backward()
                nn.utils.clip_grad_norm_(self._net.parameters(), max_norm=1.0)
                self._opt.step()
                total += loss.item() * len(xb)
                n     += len(xb)
            train_losses.append(total / n)

            # ── validation step (no gradient) ──────────────────────────────
            self._net.eval()
            with torch.no_grad():
                val_pred = self._net(X_val)
                val_mse  = float(loss_fn(val_pred, y_val).mean().item())
            val_losses.append(val_mse)
            self._net.train()

            # ── LR scheduler step ──────────────────────────────────────────
            scheduler.step(val_mse)

            # ── Early stopping check ────────────────────────────────────────
            actual_epochs = epoch + 1
            if val_mse < best_val_loss - 1e-6:
                best_val_loss    = val_mse
                no_improve_count = 0
            else:
                no_improve_count += 1
            if no_improve_count >= patience:
                logger.info(
                    f"SignalCNN: early stopping at epoch {actual_epochs} "
                    f"(no val improvement for {patience} consecutive epochs)"
                )
                break

        self._train_loss        = train_losses
        self._val_loss          = val_losses
        self._n_train           = n_train
        self._n_val             = n_val
        self._trained           = True
        self._train_ts          = time.time()
        self._scheduler         = scheduler
        self._early_stop_epoch  = actual_epochs

        final_train   = train_losses[-1]
        final_val     = val_losses[-1]
        overfit_ratio = final_val / final_train if final_train > 1e-10 else float("inf")
        diagnosis     = _diagnose(final_train, final_val, overfit_ratio)

        # ── Walk-Forward Efficiency (OOS R²) ──────────────────────────────────
        # Run the trained model on the held-out validation set and compute R².
        self._net.eval()
        with torch.no_grad():
            val_preds_t = self._net(X_val).squeeze().cpu().tolist()
        y_val_list = y_val.squeeze().cpu().tolist()
        if not isinstance(val_preds_t, list):
            val_preds_t = [float(val_preds_t)]
        if not isinstance(y_val_list, list):
            y_val_list = [float(y_val_list)]
        self._wfe, self._wfe_status = _compute_wfe(y_val_list, val_preds_t)

        dev_name = str(self._dev) if self._dev else "cpu"
        logger.info(
            f"SignalCNN: trained {actual_epochs}/{epochs} epochs | "
            f"train={n_train} val={n_val} ({dev_name}) | "
            f"train_MSE={final_train:.6f} val_MSE={final_val:.6f} "
            f"ratio={overfit_ratio:.2f} | {diagnosis} | "
            f"WFE={self._wfe} [{self._wfe_status}]"
        )

    # ── inference ─────────────────────────────────────────────────────────────

    def predict(self, x: np.ndarray) -> Tuple[float, str, float]:
        """
        Single-window inference.

        Parameters
        ----------
        x : (5, T) float array — from SignalHistoryStore.get_recent_window()

        Returns
        -------
        pred_return : float       predicted 1-day return (e.g. 0.023 = +2.3%)
        direction   : str         'bull' | 'neutral' | 'bear'
        confidence  : float 0–1   magnitude-scaled (5% return → 1.0)
        """
        if not HAS_TORCH or self._net is None or not self._trained:
            return 0.0, "neutral", 0.0

        # Guard against channel mismatch during the transition period when old
        # 7-channel checkpoints are loaded but get_recent_window now returns 9
        # channels.  The net rebuilds automatically on the next 24h retrain.
        if x.shape[0] != self._n_channels:
            return 0.0, "neutral", 0.0

        self._net.eval()
        with torch.no_grad():
            x_t    = torch.from_numpy(x.astype(np.float32)).unsqueeze(0).to(self._dev)
            pred   = float(self._net(x_t).squeeze().cpu().item())

        direction  = "bull" if pred > 0.005 else ("bear" if pred < -0.005 else "neutral")
        confidence = float(min(1.0, abs(pred) / 0.05))   # 5% → max confidence
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
        }


# Module-level singleton — imported by cnn_reasoning_agent and market_data
signal_cnn = SignalCNN()
