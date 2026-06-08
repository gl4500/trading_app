"""
Leading-regime score — combines four indicators that historically lead equity
regime change by 1-10 days into a single bounded number in [-1, +1].

Positive = bullish lead; negative = bearish lead; zero = neutral or no data.

The function is pure — no module state, no I/O, no imports from agents/main.
It consumes the same shape of fast-return dict that macro_context produces, so
the trading loop can compute the score immediately after the macro fetch with
no extra plumbing.

Components
----------
1. VIX term structure (VIX / VIX3M)
   - Contango (ratio < 1.0)  : normal — vol curve sloping up, no stress
   - Backwardation (ratio > 1.0) : stress, vol curve inverted, leads regime shift
   - Saturates at 0.15 deviation from the 0.95 neutral point

2. Credit (HYG 5d return)
   - High-yield rolls over before equities in a top
   - Saturates at +/-2% 5d move

3. Defensive vs cyclical sector ratio (5d returns)
   - (XLY + XLK + XLF)/3 minus (XLU + XLP + XLV)/3
   - Positive = cyclicals leading = healthy bull
   - Negative = defensives leading = bear regime onset
   - Saturates at +/-2% spread

4. Breadth (IWM_5d - SPY_5d)
   - Small-caps lagging large-caps = narrowing rally = top signal
   - Small-caps leading = broad risk-on
   - Saturates at +/-2% spread

Missing components are skipped (not zeroed) so the score reflects only the
information actually available. If nothing is computable, returns (0.0, all None).
"""
from typing import Dict, Optional, Tuple


_VIX_TS_NEUTRAL: float = 0.95   # typical VIX/VIX3M contango ratio
_VIX_TS_SCALE:   float = 0.15   # ratio swing that saturates the component
_CREDIT_SCALE:   float = 0.02   # 2% HYG 5d move saturates
_SECTOR_SCALE:   float = 0.02   # 2% cyclical-vs-defensive spread saturates
_BREADTH_SCALE:  float = 0.02   # 2% IWM-vs-SPY spread saturates

_DEFENSIVE_SECTORS = ("XLU", "XLP", "XLV")
_CYCLICAL_SECTORS  = ("XLY", "XLK", "XLF")


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _safe_mean(values) -> Optional[float]:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _vix_term_structure(vix_price: Optional[float], vix3m_price: Optional[float]) -> Optional[float]:
    if not vix_price or not vix3m_price or vix3m_price <= 0:
        return None
    ratio = vix_price / vix3m_price
    return _clip((_VIX_TS_NEUTRAL - ratio) / _VIX_TS_SCALE)


def _credit_momentum(fast_returns: Dict[str, Dict[str, float]]) -> Optional[float]:
    hyg = fast_returns.get("HYG")
    if not hyg or "5d" not in hyg or hyg["5d"] is None:
        return None
    return _clip(hyg["5d"] / _CREDIT_SCALE)


def _defensive_vs_cyclical(fast_returns: Dict[str, Dict[str, float]]) -> Optional[float]:
    def_avg = _safe_mean(
        fast_returns.get(s, {}).get("5d") for s in _DEFENSIVE_SECTORS
    )
    cyc_avg = _safe_mean(
        fast_returns.get(s, {}).get("5d") for s in _CYCLICAL_SECTORS
    )
    if def_avg is None or cyc_avg is None:
        return None
    return _clip((cyc_avg - def_avg) / _SECTOR_SCALE)


def _breadth(fast_returns: Dict[str, Dict[str, float]]) -> Optional[float]:
    iwm = fast_returns.get("IWM", {}).get("5d")
    spy = fast_returns.get("SPY", {}).get("5d")
    if iwm is None or spy is None:
        return None
    return _clip((iwm - spy) / _BREADTH_SCALE)


def compute_leading_score(
    fast_returns: Dict[str, Dict[str, float]],
    vix_price: Optional[float] = None,
    vix3m_price: Optional[float] = None,
) -> Tuple[float, Dict[str, Optional[float]]]:
    """
    Compute the leading-regime score and return both the score and a per-component
    breakdown so callers can log / inspect contributions.

    Returns
    -------
    (score, components)
      score      : float in [-1.0, +1.0]; 0.0 when no components computable
      components : {"vix_ts": ..., "credit": ..., "def_cyc": ..., "breadth": ...}
                   Each value is float in [-1.0, +1.0] or None when missing.
    """
    components: Dict[str, Optional[float]] = {
        "vix_ts":  _vix_term_structure(vix_price, vix3m_price),
        "credit":  _credit_momentum(fast_returns),
        "def_cyc": _defensive_vs_cyclical(fast_returns),
        "breadth": _breadth(fast_returns),
    }
    avg = _safe_mean(components.values())
    score = 0.0 if avg is None else _clip(avg)
    return score, components
