"""Diagnostic endpoints: /api/status, /api/model-diagnostics, /api/telemetry.

The model diagnostics endpoint was renamed from /api/cnn-diagnostics to
/api/model-diagnostics in issue #75 — the underlying selector resolves to
XGBoost in production, so the "cnn" prefix had become misleading. The old
URL still works as a 308 (permanent) redirect for one release so any
existing frontend bookmarks / dashboards keep functioning while the
frontend PR catches up.
"""
from __future__ import annotations

import os
import subprocess

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

diagnostics_router = APIRouter()


@diagnostics_router.get("/api/status")
async def get_status():
    """Get application status."""
    import main
    app_state = main.app_state
    _config = main.config
    return {
        "is_running": app_state.is_running,
        "market_status": app_state.market_status,
        "cycle_count": app_state.cycle_count,
        "start_time": (app_state.start_time.isoformat() + "Z") if app_state.start_time else None,
        "agent_count": len(app_state.agents),
        "ws_connections": len(app_state.ws_connections),
        "watchlist": main.watchlist_manager.get_active_watchlist(),
        "starting_capital": _config.STARTING_CAPITAL,
        "trade_interval_seconds": _config.TRADE_INTERVAL_SECONDS,
    }


@diagnostics_router.get("/api/cnn-diagnostics", include_in_schema=False)
async def get_cnn_diagnostics_legacy():
    """Permanent (308) redirect from the legacy ``/api/cnn-diagnostics`` URL
    to the renamed ``/api/model-diagnostics`` (issue #75).

    Kept for one release so any existing frontend bookmarks / dashboards
    keep working while the frontend PR catches up. ``include_in_schema=False``
    hides it from the OpenAPI docs so new clients don't pick up the old name.
    """
    return RedirectResponse(url="/api/model-diagnostics", status_code=308)


@diagnostics_router.get("/api/model-diagnostics")
async def get_model_diagnostics():
    """Model training diagnostics — overfitting / underfitting detection
    and Walk-Forward Efficiency (WFE) reporting.

    Diagnosis values:
      OK                  — healthy generalisation (ratio 1.0–2.5x)
      OVERFIT             — val MSE >> train MSE (ratio > 3x)
      OVERFIT_MEMORIZING  — train MSE < 1e-5 (memorised training data)
      UNDERFIT            — both MSEs > 0.005 (not learning signal)
      UNTRAINED           — model has not been trained yet

    Walk-Forward Efficiency (OOS R²):
      HEALTHY  — WFE >= 0.70 (model explains ≥ 70 % of OOS variance)
      DEGRADED — WFE 0.50–0.70 (partially predictive)
      POOR     — WFE < 0.50  (barely better than predicting the mean)
      UNTRAINED — not yet computed
    """
    # Use the selector so this endpoint reflects the *active* backend
    # (CNN or XGBoost) instead of always reading signal_cnn directly.
    import data.signal_model as _sm   # late import to pick up env-driven selector
    from data.cnn_model import load_training_history
    from data.regime_detector import regime_detector
    model = _sm.signal_model
    summary = model.training_summary()

    # backend_type: "cnn" | "xgboost". Derived from the selector's class name
    # so the frontend can label the diagnostics panel correctly.
    cls_name = type(model).__name__
    backend_type = "xgboost" if "XGBoost" in cls_name else "cnn"

    # Downsample loss curves to at most 40 points for the frontend.
    def _downsample(curve, n=40):
        if not curve or len(curve) <= n:
            return curve
        step = len(curve) / n
        return [curve[int(i * step)] for i in range(n)]

    return {
        "backend_type":     backend_type,
        "trained":          summary.get("trained", False),
        "device":           summary.get("device", "unknown"),
        "n_channels":       summary.get("n_channels", 0),
        "n_train":          summary.get("n_train", 0),
        "n_val":            summary.get("n_val", 0),
        "final_train_mse":  summary.get("final_train_mse"),
        "final_val_mse":    summary.get("final_val_mse"),
        # CNN-only fields — XGBoost summary doesn't carry them.
        "overfit_ratio":    summary.get("overfit_ratio"),
        "diagnosis":        summary.get("diagnosis"),
        # Walk-Forward Efficiency (both backends)
        "walk_forward_efficiency": summary.get("walk_forward_efficiency"),
        "wfe_status":              summary.get("wfe_status", "UNTRAINED"),
        # CNN-only loss curves
        "train_loss_curve": _downsample(summary.get("train_loss_curve", [])),
        "val_loss_curve":   _downsample(summary.get("val_loss_curve", [])),
        # Both backends
        "learned_weights":  summary.get("learned_weights", {}),
        # CNN-only delta-vs-prior-train; XGBoost recomputes from scratch each fit.
        "weight_delta":     summary.get("weight_delta", {}),
        "last_trained":     (
            __import__("datetime").datetime.fromtimestamp(
                summary["train_ts"],
                tz=__import__("datetime").timezone.utc,
            ).isoformat() if summary.get("train_ts") else None
        ),
        # Regime detector state
        "regime": regime_detector.summary(),
        # Last 30 retrains (oldest → newest) for day-over-day trajectory
        "training_history": load_training_history(limit=30),
        # Walk-forward CV metrics (added 2026-04-27)
        "fold_metrics":   summary.get("fold_metrics", []),
        "mean_ic":        summary.get("mean_ic", 0.0),
        "ir":             summary.get("ir", 0.0),
        "mean_wfe":       summary.get("mean_wfe"),
        "calibration":    summary.get("calibration", []),
    }


@diagnostics_router.get("/api/telemetry")
async def get_telemetry():
    """Return system resource usage, Ollama model status, and scanner timing history."""
    import main
    from agents.scanner_agent import _scan_history, _ollama_is_available  # noqa: F401

    _config = main.config
    psutil = main.psutil
    httpx = main.httpx  # route via main so patch("main.httpx", ...) works

    # ── System metrics ────────────────────────────────────────────────────────
    cpu_pct = 0.0
    mem_total_gb = 0.0
    mem_available_gb = 0.0
    mem_pct = 0.0
    process_memory_mb = 0.0

    if psutil is not None:
        try:
            cpu_pct = float(psutil.cpu_percent(interval=0.2))
            vm = psutil.virtual_memory()
            mem_total_gb    = round(vm.total    / 1024**3, 1)
            mem_available_gb = round(vm.available / 1024**3, 1)
            mem_pct          = float(vm.percent)
            proc = psutil.Process()
            process_memory_mb = round(proc.memory_info().rss / 1024**2, 1)
        except Exception as e:
            main.logger.debug(f"Telemetry: psutil error: {e}")

    # ── GPU metrics (nvidia-smi) ──────────────────────────────────────────────
    gpu_list: list = []
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) == 5:
                    name, util, mem_used, mem_total, temp = parts
                    gpu_list.append({
                        "name":          name,
                        "util_pct":      float(util),
                        "vram_used_mb":  float(mem_used),
                        "vram_total_mb": float(mem_total),
                        "temp_c":        float(temp),
                    })
    except Exception:
        pass  # No NVIDIA GPU or nvidia-smi not on PATH — degrade gracefully

    # ── Ollama model info ─────────────────────────────────────────────────────
    ollama_models = []
    ollama_online = False
    try:
        base = _config.OLLAMA_BASE_URL.rstrip("/")
        ps_url = (base[:-3] if base.endswith("/v1") else base) + "/api/ps"
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(ps_url)
            if r.status_code == 200:
                ollama_online = True
                for m in r.json().get("models", []):
                    size_gb = round(m.get("size", 0) / 1024**3, 2)
                    vram    = m.get("size_vram", 0)
                    processor = "GPU" if vram and vram > 0 else "CPU"
                    ollama_models.append({
                        "name":       m.get("name", ""),
                        "size_gb":    size_gb,
                        "processor":  processor,
                        "expires_at": m.get("expires_at", ""),
                    })
    except Exception:
        pass

    # ── Scan history ──────────────────────────────────────────────────────────
    scan_durations = list(_scan_history)
    avg_scan_sec   = round(sum(scan_durations) / len(scan_durations), 1) if scan_durations else 0.0

    return {
        "cpu_pct":           cpu_pct,
        "memory": {
            "total_gb":     mem_total_gb,
            "available_gb": mem_available_gb,
            "used_pct":     mem_pct,
        },
        "process_memory_mb": process_memory_mb,
        "gpu":               gpu_list,
        "ollama": {
            "online":  ollama_online,
            "mode":    "local" if os.environ.get("OLLAMA_ONLY_MODE") == "1" else "off",
            "models":  ollama_models,
        },
        "scan_history": {
            "durations_sec": scan_durations,
            "avg_sec":       avg_scan_sec,
            "count":         len(scan_durations),
        },
    }
