"""
SignalW3 — per-group + regime-conditional softmax-blend backprop model.

Derived from the session 2026-05-23 W3 sidecar (see backlog memory
backlog_trading_app_w3_ensemble). Three groups (Catalyst, Momentum, Regime)
each get a small linear head; a regime-conditional softmax blends them.
Used as a second vote alongside SignalXGBoost inside xgb_reasoning_agent.

Public surface mirrors data.xgboost_model.SignalXGBoost where the agent
touches it — predict(window)->(pred, direction, conf), is_trained,
last_train_time, mean_wfe, T, fit(), save(), load() — so the agent code
treats it as an interchangeable backend.
"""
from __future__ import annotations

import logging
import math
import os
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# torch is optional at import-time so the module can be imported even when
# torch isn't installed (load() / fit() will then no-op with a warning).
try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False
    logger.warning("w3_model: torch not available — install pytorch to enable W3 inference")


# ── Channel groups (frozen — must match training-time channel layout) ─────
# Derived from data.feature_catalog. Hard-coded indices to keep this module
# importable without any other backend code; tests would catch a drift.
CATALYST_IDX: List[int] = [0, 1, 2, 3, 4]
MOMENTUM_IDX: List[int] = [7, 8, 9, 10, 11, 12, 13, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32]
REGIME_IDX:   List[int] = [14, 15, 16, 17, 18, 19, 33, 34, 35, 36, 37]
GROUP_NAMES = ("Catalyst", "Momentum", "Regime")

_DEFAULT_T = 10  # window depth; W3 only consumes last timestep but T kept for compat with signal_history

_MODEL_DIR  = os.path.join(os.path.dirname(__file__), "models")
_MODEL_PATH = os.path.join(_MODEL_DIR, "signal_w3_pergroup.pt")

# Training hyperparams (env-overridable for ops tuning)
_W3_EPOCHS       = int(os.getenv("W3_EPOCHS",       "80"))
_W3_BATCH_SIZE   = int(os.getenv("W3_BATCH_SIZE",   "8192"))
_W3_LR           = float(os.getenv("W3_LR",         "5e-3"))
_W3_WEIGHT_DECAY = float(os.getenv("W3_WEIGHT_DECAY","1e-4"))
_W3_PATIENCE     = int(os.getenv("W3_PATIENCE",     "8"))
_W3_SEED         = int(os.getenv("W3_SEED",         "42"))


def _resolve_train_device():
    """Pick the device for W3 training.

    Default CPU — keeps the GPU free for Ollama inference inside the live
    backend, and sidesteps CUDA state-leak cascades in the test suite.
    Set ``W3_DEVICE=cuda`` to opt into GPU for sidecar / probe scripts
    where iteration speed matters and Ollama isn't competing.

    Returns ``torch.device("cpu")`` when torch is unavailable so callers
    don't need to guard.
    """
    if not HAS_TORCH:
        class _CpuOnly:
            type = "cpu"
        return _CpuOnly()
    requested = os.getenv("W3_DEVICE", "cpu").lower()
    if requested == "cuda" and torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


if HAS_TORCH:
    class _W3PerGroupBlend(nn.Module):
        """Per-group linear head + regime-conditional softmax blend.

        forward(x): x is (B, C) standardized features. Returns (B, 1) prediction.
        """
        def __init__(self, group_idx_list: List[List[int]], regime_idx: List[int]):
            super().__init__()
            self.group_idx = [torch.tensor(g, dtype=torch.long) for g in group_idx_list]
            self.regime_idx = torch.tensor(regime_idx, dtype=torch.long)
            self.heads = nn.ModuleList([nn.Linear(len(g), 1, bias=True) for g in group_idx_list])
            for h in self.heads:
                nn.init.zeros_(h.weight); nn.init.zeros_(h.bias)
            self.blend = nn.Linear(len(regime_idx), len(group_idx_list), bias=True)
            nn.init.zeros_(self.blend.weight); nn.init.zeros_(self.blend.bias)
            self.bias = nn.Parameter(torch.zeros(1))

        def forward(self, x):  # x: (B, C)
            regime = x.index_select(1, self.regime_idx.to(x.device))
            blend  = torch.softmax(self.blend(regime), dim=-1)        # (B, G)
            preds = [h(x.index_select(1, g.to(x.device))) for g, h in zip(self.group_idx, self.heads)]
            preds = torch.cat(preds, dim=-1)                           # (B, G)
            return (blend * preds).sum(dim=-1, keepdim=True) + self.bias


class SignalW3:
    """
    W3 backprop model — per-group linear sub-models with regime-conditional
    softmax blend. Same public surface as data.xgboost_model.SignalXGBoost
    on the methods the agent calls, so the blend code in xgb_reasoning_agent
    can treat XGB and W3 uniformly.

    Inputs at predict-time: window of shape (C, T). Only the last timestep is
    consumed (matches data.xgboost_model.last_timestep_features behavior).
    """

    T = _DEFAULT_T

    def __init__(self, model_path: str = _MODEL_PATH):
        self._model_path: str = model_path
        self._model:    Optional["_W3PerGroupBlend"] = None
        self._mu:       Optional[np.ndarray] = None
        self._std:      Optional[np.ndarray] = None
        self._trained:  bool = False
        self._train_ts: float = 0.0
        self._mean_wfe: Optional[float] = None
        self._mean_ic:  Optional[float] = None
        self._ir:       Optional[float] = None
        self._fold_metrics: List[Dict] = []
        self._final_val_mse:   Optional[float] = None
        self._final_train_mse: Optional[float] = None

    # ── Public attributes the agent reads ────────────────────────────────
    @property
    def is_trained(self) -> bool: return self._trained

    @property
    def last_train_time(self) -> float: return self._train_ts

    @property
    def mean_wfe(self) -> Optional[float]: return self._mean_wfe

    @property
    def device(self) -> str:
        if HAS_TORCH and torch.cuda.is_available(): return "cuda"
        return "cpu"

    # ── Standardize a single window's last timestep ───────────────────────
    def _last_timestep(self, window: np.ndarray) -> np.ndarray:
        a = np.asarray(window, dtype=np.float32)
        if a.ndim == 1: return a
        if a.ndim == 2: return a[:, -1]                 # (C, T) -> (C,)
        if a.ndim == 3: return a[:, :, -1]              # (N, C, T) -> (N, C)
        raise ValueError(f"SignalW3: expected 1D/2D/3D window, got shape {a.shape}")

    def _standardize(self, x_last: np.ndarray) -> np.ndarray:
        if self._mu is None or self._std is None:
            return x_last
        return (x_last - self._mu) / self._std

    # ── load / save ───────────────────────────────────────────────────────
    def load(self) -> bool:
        if not HAS_TORCH: return False
        if not os.path.exists(self._model_path): return False
        try:
            blob = torch.load(self._model_path, map_location="cpu", weights_only=False)  # nosec B614 - file is written by our own SignalW3.save() to data/models/; pickle deserialization risk applies only to externally-supplied .pt files
        except Exception as exc:
            logger.warning(f"SignalW3.load: failed to read {self._model_path}: {exc}")
            return False
        try:
            self._mu  = np.asarray(blob["mu"],  dtype=np.float32)
            self._std = np.asarray(blob["std"], dtype=np.float32)
            self._std = np.where(self._std == 0, 1.0, self._std).astype(np.float32)
            groups = blob.get("groups", {"Catalyst": CATALYST_IDX, "Momentum": MOMENTUM_IDX, "Regime": REGIME_IDX})
            regime_idx = blob.get("regime_idx", REGIME_IDX)
            self._model = _W3PerGroupBlend([groups["Catalyst"], groups["Momentum"], groups["Regime"]], regime_idx)
            self._model.load_state_dict(blob["state_dict"])
            self._model.eval()
            self._trained  = True
            self._train_ts = float(blob.get("train_ts", time.time()))
            self._mean_wfe = blob.get("mean_wfe")
            self._mean_ic  = blob.get("mean_ic")
            self._ir       = blob.get("ir")
            self._fold_metrics    = blob.get("fold_metrics", [])
            self._final_val_mse   = blob.get("final_val_mse")
            self._final_train_mse = blob.get("final_train_mse")
            return True
        except Exception as exc:
            logger.warning(f"SignalW3.load: state_dict load failed: {exc}")
            self._trained = False
            self._model = None
            return False

    def save(self) -> None:
        if not (HAS_TORCH and self._trained and self._model is not None):
            logger.warning("SignalW3.save: nothing to save (untrained)")
            return
        os.makedirs(os.path.dirname(self._model_path), exist_ok=True)
        blob = {
            "state_dict": self._model.state_dict(),
            "mu":         self._mu,
            "std":        self._std,
            "groups":     {"Catalyst": CATALYST_IDX, "Momentum": MOMENTUM_IDX, "Regime": REGIME_IDX},
            "regime_idx": REGIME_IDX,
            "train_ts":        self._train_ts,
            "mean_wfe":        self._mean_wfe,
            "mean_ic":         self._mean_ic,
            "ir":              self._ir,
            "fold_metrics":    self._fold_metrics,
            "final_val_mse":   self._final_val_mse,
            "final_train_mse": self._final_train_mse,
        }
        torch.save(blob, self._model_path)
        logger.info(f"SignalW3.save: wrote {self._model_path}")

    # ── predict ───────────────────────────────────────────────────────────
    def predict(self, window: np.ndarray) -> Tuple[float, str, float]:
        """
        Return (pred_return, direction, conf) for a single (C, T) window.
        When not trained, returns a neutral fallback so callers don't crash.
        """
        if not (HAS_TORCH and self._trained and self._model is not None):
            return 0.0, "neutral", 0.3
        x_last = self._last_timestep(window)             # (C,) or (N, C)
        x_std  = self._standardize(x_last)
        if x_std.ndim == 1:
            x_std = x_std[None, :]                        # -> (1, C)
        x_t = torch.from_numpy(x_std.astype(np.float32))
        with torch.no_grad():
            pred = self._model(x_t).cpu().numpy().ravel()
        pred_return = float(pred[0])
        # Direction: same thresholds the agent uses for the surrogate path
        direction = ("bull"    if pred_return >  0.003
                     else "bear"    if pred_return < -0.003
                     else "neutral")
        # Confidence proxy: bounded sigmoid of magnitude, capped [0.3, 0.95]
        conf = float(max(0.3, min(0.95, 0.3 + 6.0 * abs(pred_return))))
        return pred_return, direction, conf

    # ── fit (called from xgb_reasoning_agent retrain cycle) ───────────────
    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        t: np.ndarray,
        sample_weights: Optional[np.ndarray] = None,
        **_ignored,
    ) -> None:
        """Walk-forward CV fit. Last fold becomes the saved model."""
        if not HAS_TORCH:
            logger.warning("SignalW3.fit: torch not available — skipping training")
            return
        if len(X) < 200:
            logger.info(f"SignalW3.fit: only {len(X)} samples — skipping")
            return

        from data.cnn_model import _compute_wfe
        from data.cnn_evaluation import (
            compute_ic, compute_ir, walkforward_folds,
        )

        torch.manual_seed(_W3_SEED); np.random.seed(_W3_SEED)
        device = _resolve_train_device()

        # Reduce (N, C, T) -> (N, C) last-timestep features
        X_arr = np.asarray(X, dtype=np.float32)
        if X_arr.ndim == 3:
            X_arr = X_arr[:, :, -1]
        y_arr = np.asarray(y, dtype=np.float32)
        t_arr = np.asarray(t, dtype=np.float64)
        w_arr = (np.asarray(sample_weights, dtype=np.float32)
                 if sample_weights is not None
                 else np.ones(len(y_arr), dtype=np.float32))

        # Standardize per channel using FULL dataset stats — same as sidecar
        mu  = X_arr.mean(axis=0)
        std = X_arr.std(axis=0)
        std = np.where(std == 0, 1.0, std).astype(np.float32)
        Xz  = ((X_arr - mu) / std).astype(np.float32)
        self._mu, self._std = mu.astype(np.float32), std

        folds = walkforward_folds(t_arr, n_folds=3, min_val_days=14, embargo_bars=1)
        if not folds:
            logger.warning("SignalW3.fit: dataset too short for 3 folds — skipping")
            return

        fold_metrics: List[Dict] = []
        ics: List[float] = []
        wfes: List[float] = []
        last_model = None
        last_train_mse = last_val_mse = None

        for fi, (tr_idx, va_idx) in enumerate(folds):
            Xz_tr, y_tr, w_tr = Xz[tr_idx], y_arr[tr_idx], w_arr[tr_idx]
            Xz_va, y_va, w_va = Xz[va_idx], y_arr[va_idx], w_arr[va_idx]

            model = _W3PerGroupBlend([CATALYST_IDX, MOMENTUM_IDX, REGIME_IDX], REGIME_IDX).to(device)
            opt = optim.Adam(model.parameters(), lr=_W3_LR, weight_decay=_W3_WEIGHT_DECAY)
            X_tr_t = torch.from_numpy(Xz_tr).to(device); y_tr_t = torch.from_numpy(y_tr).to(device).view(-1, 1); w_tr_t = torch.from_numpy(w_tr).to(device).view(-1, 1)
            X_va_t = torch.from_numpy(Xz_va).to(device); y_va_t = torch.from_numpy(y_va).to(device).view(-1, 1); w_va_t = torch.from_numpy(w_va).to(device).view(-1, 1)

            n = Xz_tr.shape[0]
            best_val = math.inf; best_state = None; patience = 0
            train_mse_last = 0.0
            for ep in range(_W3_EPOCHS):
                model.train()
                perm = torch.randperm(n, device=device)
                eps_loss = 0.0; eps_w = 0.0
                for i in range(0, n, _W3_BATCH_SIZE):
                    idx = perm[i:i+_W3_BATCH_SIZE]
                    xb, yb, wb = X_tr_t[idx], y_tr_t[idx], w_tr_t[idx]
                    opt.zero_grad()
                    loss = (wb * (model(xb) - yb) ** 2).sum() / wb.sum().clamp_min(1e-8)
                    loss.backward(); opt.step()
                    eps_loss += loss.item() * wb.sum().item(); eps_w += wb.sum().item()
                train_mse_last = eps_loss / max(eps_w, 1e-8)
                model.eval()
                with torch.no_grad():
                    vp_t = model(X_va_t)
                    vmse = ((w_va_t * (vp_t - y_va_t) ** 2).sum() / w_va_t.sum().clamp_min(1e-8)).item()
                if vmse < best_val - 1e-7:
                    best_val = vmse
                    best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
                    patience = 0
                else:
                    patience += 1
                    if patience >= _W3_PATIENCE: break

            model.load_state_dict(best_state); model.eval()
            with torch.no_grad():
                vp = model(X_va_t).cpu().numpy().ravel().astype(np.float32)
            wfe_val, _ = _compute_wfe(y_va.tolist(), vp.tolist())
            ic_val = compute_ic(vp, y_va)
            fold_metrics.append({
                "fold": fi, "n_train": int(len(tr_idx)), "n_val": int(len(va_idx)),
                "train_mse": train_mse_last, "val_mse": best_val,
                "wfe": wfe_val, "ic": ic_val,
            })
            if wfe_val is not None: wfes.append(wfe_val)
            ics.append(ic_val)
            if fi == len(folds) - 1:
                last_model = model
                last_train_mse = train_mse_last
                last_val_mse = best_val

        self._model = last_model.to(torch.device("cpu")) if last_model is not None else None
        if self._model is not None:
            self._model.eval()
        self._fold_metrics = fold_metrics
        self._mean_ic   = float(np.mean(ics)) if ics else 0.0
        self._ir        = compute_ir(ics)
        self._mean_wfe  = float(np.mean(wfes)) if wfes else None
        self._final_train_mse = last_train_mse
        self._final_val_mse   = last_val_mse
        self._trained  = self._model is not None
        self._train_ts = time.time()


# Module-level singleton — xgb_reasoning_agent imports this directly.
signal_w3 = SignalW3()
