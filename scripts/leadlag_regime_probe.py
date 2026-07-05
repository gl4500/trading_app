"""
H14 lead-lag probe — do candidate market signals LEAD regime change, or only
coincide with it?

The production feature set is entirely trailing/coincident (every macro channel
is `_back`; the regime label itself is VIX-level + SPY-trailing-5d). Iters 12/13
showed reacting to regime at entry/exit is too late. This probe tests whether any
of four classic "leading" signals actually anticipates market stress on history,
BEFORE we spend effort backfilling one as a feature.

Targets (price-only, so VIX/credit/breadth candidates can't be circular):
  T1  down-trend STATE:  SPY < SPY.rolling(50).mean()   (regime persistence/lead)
  T2  forward STRESS:    SPY forward k-day return < -3%  (regime-change-ahead)

Candidates, oriented so higher = more stress-predictive:
  vix_ts_slope   = VIX / VIX3M           (backwardation > 1 = stress)
  credit_stress  = -(HYG/LQD).pct(20)    (credit deteriorating)
  breadth_stress = -(RSP/SPY).pct(20)    (equal-wt lagging cap-wt = narrowing)
  curve_stress   = -(TNX - IRX)          (10y-3m inversion)
Lagging baselines (for contrast):
  spy_trail5     = -SPY.pct(5)           (trailing drawdown)
  vix_level      = VIX

Metric: rank-AUC of indicator(t) -> target(t+k), k in {0,5,10,20}.
Falsifier: a candidate LEADS only if AUC on T2 at k>=10 is >= 0.55 AND does not
decay below its own k=0 value. Otherwise it is coincident, not leading -> discard.

Read-only, public data (yfinance). No trading.db / model access. Run:
    PYTHONPATH='site-packages;backend' runtime/python/python.exe \
        scripts/leadlag_regime_probe.py
"""
from __future__ import annotations

import sys
from typing import Dict, List

import numpy as np
import pandas as pd

TICKERS = {
    "spy": "SPY", "vix": "^VIX", "vix3m": "^VIX3M",
    "hyg": "HYG", "lqd": "LQD", "rsp": "RSP",
    "tnx": "^TNX", "irx": "^IRX",
}
KS = [0, 5, 10, 20]        # for T1 (a state exists at every k, incl. coincident)
KS_T2 = [5, 10, 20]        # for T2 (a *forward* event needs k>0; no coincident col)
DROP_THRESH = -0.03  # T2: forward k-day SPY return below this = "stress ahead"


def _load_closes() -> pd.DataFrame:
    import yfinance as yf
    cols: Dict[str, pd.Series] = {}
    for name, tk in TICKERS.items():
        df = yf.download(tk, period="max", interval="1d",
                         auto_adjust=True, progress=False)
        if df is None or df.empty:
            print(f"  WARN: no data for {tk}")
            continue
        close = df["Close"]
        if isinstance(close, pd.DataFrame):   # yfinance sometimes returns a frame
            close = close.iloc[:, 0]
        cols[name] = close
    out = pd.DataFrame(cols).sort_index()
    out.index = pd.to_datetime(out.index)
    return out


def _auc(score: pd.Series, label: pd.Series) -> float:
    """Rank-AUC (Mann-Whitney) of a continuous score vs a binary label."""
    d = pd.DataFrame({"s": score, "y": label}).dropna()
    if d.empty:
        return float("nan")
    n_pos = int((d.y == 1).sum())
    n_neg = int((d.y == 0).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    r = d.s.rank(method="average")
    return float((r[d.y == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def main() -> int:
    print("Downloading daily history (yfinance)...")
    px = _load_closes()
    missing = [k for k in TICKERS if k not in px.columns]
    if missing:
        print(f"  missing series: {missing} — probe continues on available ones")
    px = px.dropna(how="all").ffill()
    print(f"  aligned rows={len(px)}  span={px.index.min().date()}..{px.index.max().date()}")

    spy = px["spy"]
    spy50 = spy.rolling(50).mean()

    # ---- targets (price-only) ----
    T1 = (spy < spy50).astype(float)                          # down-trend state
    fwd = {k: spy.shift(-k) / spy - 1.0 for k in KS if k > 0}  # forward returns

    # ---- candidate + baseline signals (oriented: higher = more stress) ----
    sig: Dict[str, pd.Series] = {}
    if {"vix", "vix3m"} <= set(px.columns):
        sig["vix_ts_slope"] = px["vix"] / px["vix3m"]
    if {"hyg", "lqd"} <= set(px.columns):
        sig["credit_stress"] = -(px["hyg"] / px["lqd"]).pct_change(20)
    if {"rsp", "spy"} <= set(px.columns):
        sig["breadth_stress"] = -(px["rsp"] / spy).pct_change(20)
    if {"tnx", "irx"} <= set(px.columns):
        sig["curve_stress"] = -(px["tnx"] - px["irx"])
    # lagging baselines
    sig["spy_trail5_LAG"] = -spy.pct_change(5)
    if "vix" in px.columns:
        sig["vix_level_LAG"] = px["vix"]

    def table(target_at_k, title: str, ks: List[int]) -> Dict[str, Dict[int, float]]:
        print("\n" + "=" * 74)
        print(title)
        print("=" * 74)
        hdr = "signal".ljust(18) + "".join(f"k={k:<7}" for k in ks)
        print(hdr)
        print("-" * 74)
        res: Dict[str, Dict[int, float]] = {}
        for name, s in sig.items():
            row = {}
            line = name.ljust(18)
            for k in ks:
                a = _auc(s, target_at_k(k))
                row[k] = a
                line += f"{a:<9.3f}" if not np.isnan(a) else f"{'nan':<9}"
            res[name] = row
            print(line)
        return res

    # T1: down-trend STATE at t+k (coincident state exists at k=0)
    table(lambda k: T1.shift(-k),
          "T1  AUC: signal(t) -> down-trend STATE at t+k", KS)

    # T2: forward STRESS event (SPY fwd k-day return < -3%) — inherently forward,
    # so the nearest column is k=5 (no coincident k=0).
    t2 = table(lambda k: (fwd[k] < DROP_THRESH).astype(float),
               f"T2  AUC: signal(t) -> forward {abs(DROP_THRESH)*100:.0f}% SPY drop within k days",
               KS_T2)

    # ---- verdict on T2 (the actionable 'stress ahead' target) ----
    print("\n" + "=" * 74)
    print("VERDICT (falsifier: LEADS only if T2 AUC at k>=10 is >=0.55 AND does not")
    print("         decay below the nearest-horizon k=5 value)")
    print("=" * 74)
    for name, row in t2.items():
        a5, a10, a20 = row.get(5, np.nan), row.get(10, np.nan), row.get(20, np.nan)
        lead = (a10 >= 0.55) and (a10 >= a5 - 0.01)
        tag = "LEADS" if lead else "coincident/no-lead"
        base = " [LAGGING baseline]" if name.endswith("_LAG") else ""
        print(f"  {name:<18} k5={a5:.3f} k10={a10:.3f} k20={a20:.3f}  -> {tag}{base}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
