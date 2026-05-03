"""
Signal-model backend selector. The active model is one of:

    cnn      → data.cnn_model.signal_cnn       (default)
    xgboost  → data.xgboost_model.signal_xgb

Switch via the MODEL_BACKEND env var (also surfaced as config.MODEL_BACKEND).
Any other value falls back to cnn with a warning so the app stays operable.

The agent imports `signal_model` from here instead of either backend
directly so swapping is one env var, not a code change.
"""
from __future__ import annotations

import logging

from config import config

logger = logging.getLogger(__name__)


def _select_backend():
    backend = (config.MODEL_BACKEND or "cnn").lower().strip()
    if backend == "xgboost":
        from data.xgboost_model import signal_xgb
        logger.info("signal_model: using XGBoost backend")
        return signal_xgb
    if backend not in ("cnn", ""):
        logger.warning(
            f"signal_model: unknown MODEL_BACKEND={backend!r}; falling back to cnn"
        )
    from data.cnn_model import signal_cnn
    logger.info("signal_model: using CNN backend")
    return signal_cnn


# Module-level singleton — agent imports this directly.
signal_model = _select_backend()
