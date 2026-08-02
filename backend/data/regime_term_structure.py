"""
Multi-horizon trend term-structure signal, measured on a book-matched proxy.

Collapses 5/10/20/60/90-day momentum (vol-normalized to z-scores so horizons
and indices are comparable) into a discrete trend state that acts as a
tighten-only conservatism dial on the XGB BUY confidence threshold.

DESIGN RULE: imports ONLY stdlib + numpy. No agents, no main, no database, no
config singleton. Config values are passed in as parameters. Pure classifier
(`compute_term_structure`) + a thin stateful singleton (mirrors
data/regime_detector.py).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Dict, List

logger = logging.getLogger(__name__)

_HORIZONS = (5, 10, 20, 60, 90)
_MIN_PRICES = 91            # 90-day look-back + current bar
_TRADING_DAYS = 252
_VOL_WINDOW = 20

_Z_CUTOFF_DEFAULT = 0.5
_DELTA_TOPPING_DEFAULT = 0.10
_DELTA_WEAK_DEFAULT = 0.15


@dataclass(frozen=True)
class TermStructureResult:
    state: str                 # trending_up | topping | ranging_weak | neutral
    gate_delta: float          # >= 0, add to the BUY confidence threshold
    long_z: float
    short_z: float
    detail: Dict[str, float]


def _realized_vol(closes: List[float]) -> float:
    """Annualized std of the last _VOL_WINDOW daily log returns."""
    rets = [
        math.log(closes[i] / closes[i - 1])
        for i in range(len(closes) - _VOL_WINDOW, len(closes))
        if closes[i - 1] > 0
    ]
    if not rets:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    return math.sqrt(var * _TRADING_DAYS)


def compute_term_structure(
    closes: List[float],
    cutoff: float = _Z_CUTOFF_DEFAULT,
    delta_topping: float = _DELTA_TOPPING_DEFAULT,
    delta_weak: float = _DELTA_WEAK_DEFAULT,
) -> TermStructureResult:
    """Classify the trend term-structure of a proxy price series. Pure."""
    if len(closes) < _MIN_PRICES:
        return TermStructureResult("neutral", 0.0, 0.0, 0.0,
                                   {"reason_insufficient_data": 1.0, "n": float(len(closes))})
    vol20 = _realized_vol(closes)
    if not (vol20 > 0.0):
        return TermStructureResult("neutral", 0.0, 0.0, 0.0, {"reason_zero_vol": 1.0})

    last = closes[-1]
    mom: Dict[int, float] = {}
    z: Dict[int, float] = {}
    for h in _HORIZONS:
        m = last / closes[-1 - h] - 1.0
        mom[h] = m
        z[h] = m / (vol20 * math.sqrt(h / _TRADING_DAYS))

    long_z = (z[60] + z[90]) / 2.0
    short_z = (z[5] + z[10] + z[20]) / 3.0

    if long_z > cutoff and short_z >= 0.0:
        state, delta = "trending_up", 0.0
    elif long_z > cutoff and short_z < 0.0:
        state, delta = "topping", delta_topping
    else:
        state, delta = "ranging_weak", delta_weak

    detail: Dict[str, float] = {f"mom_{h}d": mom[h] for h in _HORIZONS}
    detail["vol20d"] = vol20
    return TermStructureResult(state, delta, long_z, short_z, detail)


class TermStructureDetector:
    """Thin stateful wrapper (mirrors data/regime_detector.RegimeDetector).

    Holds the latest classification. All logic lives in compute_term_structure;
    this only caches the last result so consumers can read it cheaply.
    """

    def __init__(self) -> None:
        self._result = TermStructureResult("neutral", 0.0, 0.0, 0.0, {"reason_uninitialized": 1.0})

    def update(
        self,
        closes: List[float],
        cutoff: float = _Z_CUTOFF_DEFAULT,
        delta_topping: float = _DELTA_TOPPING_DEFAULT,
        delta_weak: float = _DELTA_WEAK_DEFAULT,
    ) -> None:
        try:
            clean = [float(c) for c in closes if c and c > 0]
            self._result = compute_term_structure(clean, cutoff, delta_topping, delta_weak)
        except Exception as exc:  # never let a data glitch break the trading loop
            logger.debug(f"TermStructureDetector.update error: {exc}")

    def get_gate_delta(self) -> float:
        return self._result.gate_delta

    def get_state(self) -> str:
        return self._result.state

    def summary(self) -> dict:
        d = {"state": self._result.state, "gate_delta": self._result.gate_delta,
             "long_z": self._result.long_z, "short_z": self._result.short_z}
        d.update(self._result.detail)
        return d


term_structure_detector = TermStructureDetector()
