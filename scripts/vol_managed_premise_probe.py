"""
H15 premise probe — does VOL-MANAGED exposure beat constant exposure?

H14 (iter 12) showed no macro signal *leads* regime stress at 5-20d, but the
coincident stress signal (VIX level / realized vol) is strong. The unexplored
fork: use that coincident signal for RISK CONTROL, not prediction — scale
exposure down when vol is already high (Moreira-Muir "volatility-managed
portfolios"). The production basket is ~94% long-beta, so if vol-targeting
doesn't improve risk-adjusted return on SPY itself, it won't help the basket.

Cheapest test BEFORE touching trade history or the position sizer: backtest a
vol-managed SPY long vs buy-and-hold on daily data.

  constant:      100% SPY every day
  vol_managed:   weight_t = clip(target_vol / realized_vol_{t-1}, 0, cap) * SPY
                 realized_vol from trailing 20d daily returns, annualized;
                 weight uses PRIOR-day vol (no look-ahead).
  vix_managed:   weight_t = clip(target_vixvol / VIX_{t-1}, 0, cap)

Compares annualized return, vol, Sharpe, max drawdown, and — the operator's
north star — behaviour in the worst periods. Also reports a turnover/cost line
since vol-targeting trades size daily.

Falsifier (pre-registered): vol-managed LEADS to a build only if it improves
Sharpe AND cuts max drawdown materially (>=15% relative) vs constant, net of a
1 bp/turnover cost. If Sharpe doesn't beat constant after costs -> discard.

Read-only, public yfinance data. No trading.db / model. Run:
    PYTHONPATH='site-packages;backend' runtime/python/python.exe \
        scripts/vol_managed_premise_probe.py
"""
from __future__ import annotations

import sys
from typing import Dict

import numpy as np
import pandas as pd

TARGET_ANN_VOL = 0.12    # 12% annualized target for the vol-managed sleeve
WEIGHT_CAP = 2.0         # max leverage (avoid infinite size at ~0 vol)
COST_PER_TURN = 0.0001   # 1 bp on |Δweight| per day
TRADING_DAYS = 252


def _load() -> pd.DataFrame:
    import yfinance as yf
    spy = yf.download("SPY", period="max", interval="1d",
                      auto_adjust=True, progress=False)["Close"]
    vix = yf.download("^VIX", period="max", interval="1d",
                      auto_adjust=True, progress=False)["Close"]
    if isinstance(spy, pd.DataFrame):
        spy = spy.iloc[:, 0]
    if isinstance(vix, pd.DataFrame):
        vix = vix.iloc[:, 0]
    df = pd.DataFrame({"spy": spy, "vix": vix}).dropna(how="all").ffill().dropna()
    df.index = pd.to_datetime(df.index)
    return df


def _stats(ret: pd.Series, weight: pd.Series, label: str) -> Dict:
    """ret = daily strategy return (already weighted, pre-cost)."""
    turn = weight.diff().abs().fillna(0.0)
    net = ret - turn * COST_PER_TURN
    ann_ret = net.mean() * TRADING_DAYS
    ann_vol = net.std() * np.sqrt(TRADING_DAYS)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else float("nan")
    curve = (1.0 + net).cumprod()
    dd = (curve / curve.cummax() - 1.0).min()
    return {"label": label, "ann_ret": ann_ret, "ann_vol": ann_vol,
            "sharpe": sharpe, "max_dd": dd, "avg_turn": turn.mean(),
            "curve": curve}


def main() -> int:
    print("Downloading SPY + VIX (yfinance)...")
    df = _load()
    print(f"  rows={len(df)}  span={df.index.min().date()}..{df.index.max().date()}")

    r = df["spy"].pct_change().fillna(0.0)               # SPY daily return
    rv = r.rolling(20).std() * np.sqrt(TRADING_DAYS)      # trailing annualized vol
    rv_prior = rv.shift(1)                                # no look-ahead
    vix_prior = (df["vix"] / 100.0).shift(1)             # VIX as annualized vol

    w_const = pd.Series(1.0, index=df.index)
    w_rv = (TARGET_ANN_VOL / rv_prior).clip(0.0, WEIGHT_CAP).fillna(0.0)
    w_vix = (TARGET_ANN_VOL / vix_prior).clip(0.0, WEIGHT_CAP).fillna(0.0)

    # restrict to the common window where weights are defined
    valid = rv_prior.notna() & vix_prior.notna()
    r, w_const, w_rv, w_vix = r[valid], w_const[valid], w_rv[valid], w_vix[valid]

    results = [
        _stats(w_const * r, w_const, "constant (buy&hold)"),
        _stats(w_rv * r, w_rv, "vol_managed (20d RV target)"),
        _stats(w_vix * r, w_vix, "vix_managed (VIX target)"),
    ]

    print("\n" + "=" * 78)
    print(f"VOL-MANAGED vs CONSTANT  (target={TARGET_ANN_VOL:.0%} ann, cap={WEIGHT_CAP}x, "
          f"cost={COST_PER_TURN*1e4:.0f}bp/turn)")
    print("=" * 78)
    print(f"{'strategy':<30}{'annRet':>9}{'annVol':>9}{'Sharpe':>8}{'maxDD':>9}{'turn/d':>8}")
    print("-" * 78)
    base = results[0]
    for s in results:
        print(f"{s['label']:<30}{s['ann_ret']:>+8.2%}{s['ann_vol']:>8.2%}"
              f"{s['sharpe']:>8.2f}{s['max_dd']:>+8.2%}{s['avg_turn']:>8.3f}")
    print(f"\n  avg weight - vol_managed={w_rv.mean():.2f}  vix_managed={w_vix.mean():.2f}")

    # recent-window check (the live regime, 2024+)
    recent = df.index[valid] >= pd.Timestamp("2024-01-01")
    if recent.any():
        print("\n  --- 2024+ subsample (recent regime) ---")
        for w, lbl in [(w_const, "constant"), (w_rv, "vol_managed"), (w_vix, "vix_managed")]:
            rr = (w * r)[recent]
            tt = w[recent].diff().abs().fillna(0.0)
            net = rr - tt * COST_PER_TURN
            av = net.std() * np.sqrt(TRADING_DAYS)
            sh = (net.mean() * TRADING_DAYS) / av if av > 0 else float("nan")
            cv = (1 + net).cumprod()
            dd = (cv / cv.cummax() - 1).min()
            print(f"    {lbl:<14} Sharpe={sh:>5.2f}  maxDD={dd:>+7.2%}  annRet={net.mean()*TRADING_DAYS:>+7.2%}")

    print("\n" + "=" * 78)
    print("VERDICT (falsifier: net Sharpe must beat constant AND cut maxDD >=15% rel.)")
    print("=" * 78)
    for s in results[1:]:
        d_sharpe = s["sharpe"] - base["sharpe"]
        dd_rel = (s["max_dd"] - base["max_dd"]) / abs(base["max_dd"]) if base["max_dd"] else float("nan")
        go = (s["sharpe"] > base["sharpe"]) and (dd_rel >= 0.15)
        print(f"  {s['label']:<30} dSharpe={d_sharpe:>+5.2f}  DD improve={dd_rel:>+6.1%}"
              f"  -> {'GO' if go else 'NO-GO'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
