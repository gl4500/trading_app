"""
XGBoost regressor backend — drop-in alternative to SignalCNN.

Same public surface as data.cnn_model.SignalCNN so data.signal_model can
swap them via env. Walk-forward CV reuses data.cnn_evaluation primitives
unchanged — folds are model-agnostic.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

from data.cnn_model import (
    LABEL_HORIZON_DIR_THRESHOLD,
    LABEL_HORIZON_FULL_CONF_RET,
    SOURCE_NAMES,
    WALKFORWARD_FOLDS,
    WALKFORWARD_MIN_VAL_DAYS,
    WALKFORWARD_EMBARGO_BARS,
    WINDOW_SIZE,
    _SECS_PER_DAY,
    _compute_wfe,
)

logger = logging.getLogger(__name__)

# ── Hyperparameters (env-overridable) ─────────────────────────────────────
XGB_N_ESTIMATORS     = int(os.getenv("XGB_N_ESTIMATORS",   "500"))
XGB_MAX_DEPTH        = int(os.getenv("XGB_MAX_DEPTH",      "6"))
XGB_LEARNING_RATE    = float(os.getenv("XGB_LEARNING_RATE", "0.05"))
XGB_SUBSAMPLE        = float(os.getenv("XGB_SUBSAMPLE",     "0.8"))
XGB_COLSAMPLE_BYTREE = float(os.getenv("XGB_COLSAMPLE_BYTREE", "0.8"))
XGB_REG_ALPHA        = float(os.getenv("XGB_REG_ALPHA",     "0.1"))
XGB_REG_LAMBDA       = float(os.getenv("XGB_REG_LAMBDA",    "1.0"))
XGB_EARLY_STOPPING   = int(os.getenv("XGB_EARLY_STOPPING",  "30"))

_MODEL_DIR        = os.path.join(os.path.dirname(__file__), "models")
_MODEL_PATH       = os.path.join(_MODEL_DIR, "signal_xgb.json")
_HISTORY_FILENAME = "training_history_xgb.jsonl"


def flatten_window(x: np.ndarray) -> np.ndarray:
    """Flatten a (C, T) window or a (N, C, T) batch into (C*T,) / (N, C*T).
    Row-major: each channel's full timeseries laid out contiguously.
    XGBoost requires tabular features, so this is how we hand it the
    same data the CNN sees as a 2-D tensor."""
    a = np.asarray(x)
    if a.ndim == 2:
        return a.ravel().astype(np.float32, copy=False)
    if a.ndim == 3:
        return a.reshape(a.shape[0], -1).astype(np.float32, copy=False)
    raise ValueError(f"flatten_window: expected 2D or 3D, got shape {a.shape}")


class SignalXGBoost:
    """XGBRegressor wrapper with the same public surface as SignalCNN.

    Trained via walk-forward CV (3 folds × ≥ 14d val window) — last fold's
    booster is kept as the production model.
    """

    def __init__(self, T: int = WINDOW_SIZE, n_channels: int = 14):
        self.T = T
        self._n_channels = n_channels
        self._booster = None                  # xgboost.XGBRegressor instance
        self._trained = False
        self._train_ts = 0.0
        self._fold_metrics: List[Dict] = []
        self._mean_ic:  Optional[float] = None
        self._ir:       Optional[float] = None
        self._mean_wfe: Optional[float] = None
        self._calibration: List[Dict] = []
        # last-fold legacy fields for /api/cnn-diagnostics parity
        self._n_train = 0
        self._n_val   = 0
        self._wfe:        Optional[float] = None
        self._wfe_status: str = "UNTRAINED"
        self._final_train_mse: Optional[float] = None
        self._final_val_mse:   Optional[float] = None

    # ── properties (mirror SignalCNN) ───────────────────────────────
    @property
    def is_trained(self) -> bool:
        return self._trained

    @property
    def last_train_time(self) -> float:
        return self._train_ts

    @property
    def device(self) -> str:
        return "cpu"   # we run XGBoost on CPU to avoid GPU contention

    @property
    def mean_wfe(self) -> Optional[float]:
        return self._mean_wfe

    @property
    def wfe_status(self) -> str:
        return self._wfe_status

    def predict(self, x: np.ndarray) -> Tuple[float, str, float]:
        """Single-window inference. Mirrors SignalCNN.predict's contract."""
        if not self._trained or self._booster is None:
            return 0.0, "neutral", 0.0
        if x.shape[0] != self._n_channels:
            return 0.0, "neutral", 0.0
        feat = flatten_window(x).reshape(1, -1)
        pred = float(self._booster.predict(feat)[0])
        if pred > LABEL_HORIZON_DIR_THRESHOLD:
            direction = "bull"
        elif pred < -LABEL_HORIZON_DIR_THRESHOLD:
            direction = "bear"
        else:
            direction = "neutral"
        confidence = float(min(1.0, abs(pred) / LABEL_HORIZON_FULL_CONF_RET))
        return pred, direction, confidence


# ── Module-level singleton ────────────────────────────────────────────────
signal_xgb = SignalXGBoost()
