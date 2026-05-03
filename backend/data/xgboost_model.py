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
        import xgboost as xgb
        if not self._trained or self._booster is None:
            return 0.0, "neutral", 0.0
        if x.shape[0] != self._n_channels:
            return 0.0, "neutral", 0.0
        feat = flatten_window(x).reshape(1, -1)
        pred = float(self._booster.predict(xgb.DMatrix(feat))[0])
        if pred > LABEL_HORIZON_DIR_THRESHOLD:
            direction = "bull"
        elif pred < -LABEL_HORIZON_DIR_THRESHOLD:
            direction = "bear"
        else:
            direction = "neutral"
        confidence = float(min(1.0, abs(pred) / LABEL_HORIZON_FULL_CONF_RET))
        return pred, direction, confidence

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        t: np.ndarray,
        sample_weights: Optional[np.ndarray] = None,
        n_folds: int = WALKFORWARD_FOLDS,
        min_val_days: int = WALKFORWARD_MIN_VAL_DAYS,
        embargo_bars: int = WALKFORWARD_EMBARGO_BARS,
        **kwargs,   # silently ignore CNN-specific kwargs (epochs, batch_size, patience)
    ) -> None:
        """Train via walk-forward CV. Last fold's booster becomes production."""
        import xgboost as xgb
        from data.cnn_evaluation import (
            compute_ic, compute_ir, compute_calibration, walkforward_folds,
        )

        if len(X) < 100:
            logger.info(f"SignalXGBoost.fit: only {len(X)} samples — skipping")
            return

        self._n_channels = X.shape[1]
        folds = walkforward_folds(
            t, n_folds=n_folds, min_val_days=min_val_days, embargo_bars=embargo_bars,
        )
        if not folds:
            logger.warning(
                f"SignalXGBoost.fit: dataset too short for {n_folds} folds × "
                f"{min_val_days}d val — skipping"
            )
            return

        fold_metrics: List[Dict] = []
        ics:  List[float] = []
        wfes: List[float] = []
        last_val_pred: List[float] = []
        last_val_true: List[float] = []
        last_train_mse = None
        last_val_mse   = None
        last_n_train   = 0
        last_n_val     = 0
        last_booster   = None

        X_flat = flatten_window(X)            # (N, C*T)
        _params = {
            "max_depth":        XGB_MAX_DEPTH,
            "eta":              XGB_LEARNING_RATE,
            "subsample":        XGB_SUBSAMPLE,
            "colsample_bytree": XGB_COLSAMPLE_BYTREE,
            "alpha":            XGB_REG_ALPHA,
            "lambda":           XGB_REG_LAMBDA,
            "objective":        "reg:squarederror",
            "eval_metric":      "rmse",
            "tree_method":      "hist",
            "seed":             42,
            "verbosity":        0,
        }
        for fold_i, (tr_idx, va_idx) in enumerate(folds):
            X_tr, y_tr = X_flat[tr_idx], y[tr_idx]
            X_va, y_va = X_flat[va_idx], y[va_idx]
            w_tr = sample_weights[tr_idx] if sample_weights is not None else None

            dtrain = xgb.DMatrix(X_tr, label=y_tr, weight=w_tr)
            dval   = xgb.DMatrix(X_va, label=y_va)

            booster = xgb.train(
                _params,
                dtrain,
                num_boost_round=XGB_N_ESTIMATORS,
                evals=[(dval, "val")],
                early_stopping_rounds=XGB_EARLY_STOPPING,
                verbose_eval=False,
            )

            vp = booster.predict(dval).astype(np.float32)
            vt = y_va.astype(np.float32)
            train_pred = booster.predict(dtrain)
            train_mse  = float(np.mean((train_pred - y_tr) ** 2))
            val_mse    = float(np.mean((vp - vt) ** 2))
            wfe_val, _ = _compute_wfe(vt.tolist(), vp.tolist())
            ic_val = compute_ic(vp, vt)
            val_window_days = float((t[va_idx].max() - t[va_idx].min()) / _SECS_PER_DAY)

            fold_metrics.append({
                "fold":            fold_i,
                "n_train":         int(len(tr_idx)),
                "n_val":           int(len(va_idx)),
                "val_window_days": round(val_window_days, 2),
                "val_mse":         val_mse,
                "wfe":             wfe_val,
                "ic":              ic_val,
                "best_iteration":  int(getattr(booster, "best_iteration", -1) or -1),
            })
            if wfe_val is not None:
                wfes.append(wfe_val)
            ics.append(ic_val)

            if fold_i == len(folds) - 1:
                last_booster   = booster
                last_train_mse = train_mse
                last_val_mse   = val_mse
                last_n_train   = int(len(tr_idx))
                last_n_val     = int(len(va_idx))
                last_val_pred  = vp.tolist()
                last_val_true  = vt.tolist()

        # Aggregate + last-fold persistence
        self._booster      = last_booster
        self._fold_metrics = fold_metrics
        self._mean_ic      = float(np.mean(ics)) if ics else 0.0
        self._ir           = compute_ir(ics)
        self._mean_wfe     = float(np.mean(wfes)) if wfes else None
        self._calibration  = compute_calibration(
            np.asarray(last_val_pred), np.asarray(last_val_true), n_buckets=5
        )
        self._n_train          = last_n_train
        self._n_val            = last_n_val
        self._final_train_mse  = last_train_mse
        self._final_val_mse    = last_val_mse
        self._wfe, self._wfe_status = _compute_wfe(last_val_true, last_val_pred)
        self._trained          = True
        self._train_ts         = time.time()

        mean_ic_str = f"{self._mean_ic:.4f}" if self._mean_ic is not None else "n/a"
        ir_str      = f"{self._ir:.2f}"      if self._ir      is not None else "n/a"
        logger.info(
            f"SignalXGBoost: walk-forward fit complete | folds={len(folds)} | "
            f"mean_WFE={self._mean_wfe} mean_IC={mean_ic_str} IR={ir_str} | "
            f"last_fold WFE={self._wfe} [{self._wfe_status}]"
        )

    def get_learned_weights(self) -> Dict[str, float]:
        """Per-source feature importance, aggregated over the T timesteps
        for each of the 5 source channels and normalised to sum 1.

        Mirrors SignalCNN.get_learned_weights — same dict shape so the
        LLM prompt that displays learned-vs-hardcoded weights doesn't
        care which backend it came from.

        Native xgboost.Booster doesn't expose `feature_importances_` (that's
        XGBRegressor). We use Booster.get_score(importance_type='gain'),
        which returns a sparse dict {f-name: importance} keyed by features
        that actually had splits. Map those back to (channel, timestep)
        positions and aggregate.
        """
        from data.cnn_model import _DEFAULT_WEIGHTS
        if not self._trained or self._booster is None:
            return _DEFAULT_WEIGHTS.copy()

        n_feat = self._n_channels * self.T
        importances = np.zeros(n_feat, dtype=np.float64)
        # get_score returns {'f0': 12.3, 'f5': 7.8, ...} — only features
        # that participated in any split. Missing features → importance 0.
        scores = self._booster.get_score(importance_type="gain")
        for fname, imp in scores.items():
            # Default DMatrix feature names are 'f0', 'f1', ...
            try:
                idx = int(fname.lstrip("f"))
            except ValueError:
                continue
            if 0 <= idx < n_feat:
                importances[idx] = float(imp)

        importances = importances.reshape(self._n_channels, self.T)
        # Sum across timesteps → per-channel importance
        per_channel = importances.sum(axis=1)
        # Restrict to the 5 source channels (first 5)
        source_imp = per_channel[: len(SOURCE_NAMES)]
        total = float(source_imp.sum())
        if total < 1e-12:
            return _DEFAULT_WEIGHTS.copy()
        normed = source_imp / total
        return dict(zip(SOURCE_NAMES, normed.tolist()))

    def save(self) -> None:
        """Persist the booster to _MODEL_PATH alongside training metadata.
        Uses the native Booster's save_model (JSON or UBJ format)."""
        if self._booster is None or not self._trained:
            return
        os.makedirs(_MODEL_DIR, exist_ok=True)
        # Native Booster.save_model — file extension determines format.
        # .json gives a human-readable model (preferred for diffing).
        self._booster.save_model(_MODEL_PATH)
        # Sidecar JSON with our wrapper's metadata.
        meta_path = _MODEL_PATH + ".meta.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({
                "trained":         self._trained,
                "train_ts":        self._train_ts,
                "T":               self.T,
                "n_channels":      self._n_channels,
                "n_train":         self._n_train,
                "n_val":           self._n_val,
                "wfe":             self._wfe,
                "wfe_status":      self._wfe_status,
                "mean_ic":         self._mean_ic,
                "ir":              self._ir,
                "mean_wfe":        self._mean_wfe,
                "calibration":     self._calibration,
                "fold_metrics":    self._fold_metrics,
                "final_train_mse": self._final_train_mse,
                "final_val_mse":   self._final_val_mse,
            }, f)
        logger.info(f"SignalXGBoost: saved → {_MODEL_PATH}")

    def load(self) -> bool:
        """Load the booster + metadata from _MODEL_PATH. Returns True on success.
        Uses the native Booster's load_model (we never have sklearn here)."""
        if not os.path.exists(_MODEL_PATH):
            return False
        try:
            import xgboost as xgb
            self._booster = xgb.Booster()
            self._booster.load_model(_MODEL_PATH)
            meta_path = _MODEL_PATH + ".meta.json"
            if os.path.exists(meta_path):
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                self._trained         = meta.get("trained", True)
                self._train_ts        = float(meta.get("train_ts", 0.0))
                self.T                = int(meta.get("T", self.T))
                self._n_channels      = int(meta.get("n_channels", self._n_channels))
                self._n_train         = int(meta.get("n_train", 0))
                self._n_val           = int(meta.get("n_val", 0))
                self._wfe             = meta.get("wfe")
                self._wfe_status      = meta.get("wfe_status", "UNTRAINED")
                self._mean_ic         = meta.get("mean_ic")
                self._ir              = meta.get("ir")
                self._mean_wfe        = meta.get("mean_wfe")
                self._calibration     = meta.get("calibration", [])
                self._fold_metrics    = meta.get("fold_metrics", [])
                self._final_train_mse = meta.get("final_train_mse")
                self._final_val_mse   = meta.get("final_val_mse")
            else:
                # No sidecar — assume trained but lose the aggregate metrics.
                self._trained = True
            logger.info(f"SignalXGBoost: loaded ← {_MODEL_PATH}")
            return True
        except Exception as exc:
            logger.warning(f"SignalXGBoost: load failed: {exc}")
            return False

    def training_summary(self) -> Dict:
        return {
            "trained":         self._trained,
            "device":          self.device,
            "train_ts":        self._train_ts,
            "n_channels":      self._n_channels,
            "n_train":         self._n_train,
            "n_val":           self._n_val,
            "final_train_mse": self._final_train_mse,
            "final_val_mse":   self._final_val_mse,
            # Aliases for parity with SignalCNN.training_summary so the
            # agent's _train_blocking log line works backend-agnostically.
            "final_mse":       self._final_train_mse,
            "learned_weights": self.get_learned_weights(),
            "walk_forward_efficiency": self._wfe,
            "wfe_status":      self._wfe_status,
            # Walk-forward CV aggregate
            "fold_metrics":    self._fold_metrics,
            "mean_ic":         self._mean_ic if self._mean_ic is not None else 0.0,
            "ir":              self._ir if self._ir is not None else 0.0,
            "mean_wfe":        self._mean_wfe,
            "calibration":     self._calibration,
            # Hyperparameters used (for run-to-run comparability)
            "hyperparams": {
                "n_estimators":     XGB_N_ESTIMATORS,
                "max_depth":        XGB_MAX_DEPTH,
                "learning_rate":    XGB_LEARNING_RATE,
                "subsample":        XGB_SUBSAMPLE,
                "colsample_bytree": XGB_COLSAMPLE_BYTREE,
                "reg_alpha":        XGB_REG_ALPHA,
                "reg_lambda":       XGB_REG_LAMBDA,
                "early_stopping":   XGB_EARLY_STOPPING,
            },
        }


# ── Module-level singleton ────────────────────────────────────────────────
signal_xgb = SignalXGBoost()
