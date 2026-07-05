"""
Real-basket re-validation of H14 (lead-lag) and H15 (vol-managed) probes.

Both prior probes used SPY as a proxy for "the book." But the actual traded
universe (reconstructed read-only from backend/trading.db `trades`) is 237
names, dollar-volume weighted, and heavily tilted to high-beta tech / semis /
biotech (MU, WOLF, FATE, AMD, DDOG, MRVL, QCOM, PLTR, COIN, MSTR, RIVN, MARA...)
— NOT the broad market. A vol-managed / lead-lag conclusion that only holds on
SPY may not transfer to a book with ~1.3-1.5x market beta.

This script:
  1. Loads dollar-volume weights per symbol from trading.db (READ-ONLY).
  2. Batch-downloads daily adjusted closes (yfinance, public data).
  3. Builds a dollar-vol-weighted daily basket return, renormalizing each day
     to the constituents that have data (composition drifts backward in time
     as young names drop out — reported explicitly).
  4. Characterizes the basket vs SPY (beta, vol, correlation).
  5. Re-runs H15 vol-managed sizing on the BASKET return series.
  6. Re-runs H14 lead-lag AUC with the BASKET as the drop target.

Falsifiers are the SAME pre-registered bars as the SPY probes — not loosened:
  H15 GO iff vol-managed beats constant Sharpe AND cuts maxDD >=15% rel, net cost.
  H14 lead iff a macro signal's AUC for a forward k-day basket drop stays >=0.60
       at k=5..20 (coincident-only if it decays to ~random by then).

Read-only. Run from repo root:
    PYTHONPATH='site-packages;backend' runtime/python/python.exe \
        scripts/real_basket_probe.py
"""
from __future__ import annotations

import sqlite3
import sys
from typing import Dict, List

import numpy as np
import pandas as pd

DB = "file:backend/trading.db?mode=ro"

# H15 knobs (identical to vol_managed_premise_probe.py)
TARGET_ANN_VOL = 0.12
WEIGHT_CAP = 2.0
COST_PER_TURN = 0.0001
TRADING_DAYS = 252

# H14 knobs (identical to leadlag_regime_probe.py)
DROP_THRESH = -0.03
KS_COINC = [0, 5, 10, 20]
KS_FWD = [5, 10, 20]

MACRO = ["SPY", "^VIX", "^VIX3M", "HYG", "LQD", "RSP", "^TNX", "^IRX"]


def load_weights() -> pd.Series:
    con = sqlite3.connect(DB, uri=True)
    df = pd.read_sql_query(
        "SELECT symbol, SUM(shares*price) dv FROM trades "
        "GROUP BY symbol HAVING dv > 0", con)
    con.close()
    w = df.set_index("symbol")["dv"]
    return w / w.sum()


def batch_close(tickers: List[str]) -> pd.DataFrame:
    import yfinance as yf
    raw = yf.download(tickers, period="max", interval="1d",
                      auto_adjust=True, progress=False, threads=True)
    close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw
    if isinstance(close, pd.Series):
        close = close.to_frame(tickers[0])
    close.index = pd.to_datetime(close.index)
    return close


def build_basket(weights: pd.Series, closes: pd.DataFrame) -> pd.Series:
    """Dollar-vol-weighted daily return, renormalized per-day to names w/ data."""
    have = [s for s in weights.index if s in closes.columns]
    px = closes[have].sort_index()
    rets = px.pct_change()
    w = weights[have].to_numpy()
    # per-day: weighted mean over available (non-NaN) returns, renormalized
    mask = rets.notna().to_numpy()
    wmat = mask * w
    denom = wmat.sum(axis=1)
    r = rets.to_numpy()
    r[~mask] = 0.0
    basket = (r * wmat).sum(axis=1) / np.where(denom > 0, denom, np.nan)
    out = pd.Series(basket, index=rets.index).dropna()
    n_names = pd.Series(mask.sum(axis=1), index=rets.index)
    out.attrs["n_names"] = n_names.reindex(out.index)
    out.attrs["coverage"] = len(have) / len(weights)
    out.attrs["dropped"] = [s for s in weights.index if s not in closes.columns]
    return out


def _stats(ret: pd.Series, weight: pd.Series, label: str) -> Dict:
    turn = weight.diff().abs().fillna(0.0)
    net = ret - turn * COST_PER_TURN
    ann_ret = net.mean() * TRADING_DAYS
    ann_vol = net.std() * np.sqrt(TRADING_DAYS)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else float("nan")
    curve = (1.0 + net).cumprod()
    dd = (curve / curve.cummax() - 1.0).min()
    return {"label": label, "ann_ret": ann_ret, "ann_vol": ann_vol,
            "sharpe": sharpe, "max_dd": dd, "avg_turn": turn.mean()}


def _auc(score: pd.Series, label: pd.Series) -> float:
    """Rank-AUC (Mann-Whitney): P(score|pos > score|neg). Higher score=stress."""
    m = score.notna() & label.notna()
    s, y = score[m], label[m].astype(bool)
    n1, n0 = int(y.sum()), int((~y).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    ranks = s.rank()
    r1 = ranks[y.values].sum()
    return (r1 - n1 * (n1 + 1) / 2.0) / (n1 * n0)


def run_h15(basket: pd.Series, vix: pd.Series) -> None:
    r = basket
    rv = r.rolling(20).std() * np.sqrt(TRADING_DAYS)
    rv_prior = rv.shift(1)
    vix_prior = (vix.reindex(r.index).ffill() / 100.0).shift(1)

    w_const = pd.Series(1.0, index=r.index)
    w_rv = (TARGET_ANN_VOL / rv_prior).clip(0.0, WEIGHT_CAP).fillna(0.0)
    w_vix = (TARGET_ANN_VOL / vix_prior).clip(0.0, WEIGHT_CAP).fillna(0.0)

    valid = rv_prior.notna() & vix_prior.notna()
    r2, wc, wr, wv = r[valid], w_const[valid], w_rv[valid], w_vix[valid]
    res = [
        _stats(wc * r2, wc, "constant (buy&hold basket)"),
        _stats(wr * r2, wr, "vol_managed (20d RV target)"),
        _stats(wv * r2, wv, "vix_managed (VIX target)"),
    ]
    print("\n" + "=" * 80)
    print(f"H15  VOL-MANAGED vs CONSTANT on REAL BASKET  "
          f"(target={TARGET_ANN_VOL:.0%}, cap={WEIGHT_CAP}x, cost={COST_PER_TURN*1e4:.0f}bp)")
    print("=" * 80)
    print(f"{'strategy':<30}{'annRet':>9}{'annVol':>9}{'Sharpe':>8}{'maxDD':>9}{'turn/d':>8}")
    print("-" * 80)
    for s in res:
        print(f"{s['label']:<30}{s['ann_ret']:>+8.2%}{s['ann_vol']:>8.2%}"
              f"{s['sharpe']:>8.2f}{s['max_dd']:>+8.2%}{s['avg_turn']:>8.3f}")
    print(f"\n  avg weight — vol_managed={wr.mean():.2f}  vix_managed={wv.mean():.2f}")

    for tag, since in [("2020+", "2020-01-01"), ("2024+", "2024-01-01")]:
        sub = r.index[valid] >= pd.Timestamp(since)
        if sub.any():
            print(f"\n  --- {tag} subsample ---")
            for w, lbl in [(wc, "constant"), (wr, "vol_managed"), (wv, "vix_managed")]:
                rr = (w * r2)[sub]
                tt = w[sub].diff().abs().fillna(0.0)
                net = rr - tt * COST_PER_TURN
                av = net.std() * np.sqrt(TRADING_DAYS)
                sh = (net.mean() * TRADING_DAYS) / av if av > 0 else float("nan")
                cv = (1 + net).cumprod()
                dd = (cv / cv.cummax() - 1).min()
                print(f"    {lbl:<14} Sharpe={sh:>5.2f}  maxDD={dd:>+7.2%}  "
                      f"annRet={net.mean()*TRADING_DAYS:>+7.2%}")

    print("\n  VERDICT (falsifier: net Sharpe beats constant AND maxDD >=15% rel better)")
    base = res[0]
    for s in res[1:]:
        d_sh = s["sharpe"] - base["sharpe"]
        dd_rel = (s["max_dd"] - base["max_dd"]) / abs(base["max_dd"]) if base["max_dd"] else float("nan")
        go = (s["sharpe"] > base["sharpe"]) and (dd_rel >= 0.15)
        print(f"    {s['label']:<30} dSharpe={d_sh:>+5.2f}  DD improve={dd_rel:>+6.1%}"
              f"  -> {'GO' if go else 'NO-GO'}")


def run_h14(basket: pd.Series, m: pd.DataFrame) -> None:
    px = (1.0 + basket).cumprod()
    idx = px.index
    spy = m["SPY"].reindex(idx).ffill()

    # candidates, oriented higher = more stress
    vix_ts = (m["^VIX"] / m["^VIX3M"]).reindex(idx).ffill()
    credit = -(m["HYG"] / m["LQD"]).pct_change(20).reindex(idx).ffill()
    breadth = -(m["RSP"] / m["SPY"]).pct_change(20).reindex(idx).ffill()
    curve = -(m["^TNX"] - m["^IRX"]).reindex(idx).ffill()
    vix_lvl = m["^VIX"].reindex(idx).ffill()
    cands = {"vix_ts_slope": vix_ts, "credit_stress": credit,
             "breadth_stress": breadth, "curve_stress": curve,
             "vix_level(ref)": vix_lvl}

    ma50 = px.rolling(50).mean()
    downtrend = (px < ma50).astype(float)  # T1 coincident state
    fwd_drop = {k: (px.shift(-k) / px - 1.0 < DROP_THRESH).astype(float)
                for k in KS_FWD}  # T2 forward drop

    print("\n" + "=" * 80)
    print("H14  LEAD-LAG on REAL BASKET — rank-AUC of signal(t) vs basket stress")
    print("=" * 80)
    print(f"basket down-trend base rate (px<50dMA) = {downtrend.mean():.2%}")
    for k in KS_FWD:
        print(f"forward {k}d drop<{DROP_THRESH:.0%} base rate = {fwd_drop[k].mean():.2%}")

    print("\n-- T1: coincident + shifted down-trend state  (AUC of signal(t) -> px<50dMA at t+k)")
    hdr = "signal".ljust(18) + "".join(f"k={k:<6}" for k in KS_COINC)
    print(hdr)
    for name, s in cands.items():
        row = name.ljust(18)
        for k in KS_COINC:
            row += f"{_auc(s, downtrend.shift(-k)):<8.3f}"
        print(row)

    print(f"\n-- T2: forward {DROP_THRESH:.0%} basket drop  (AUC of signal(t) -> drop within t+k)")
    hdr = "signal".ljust(18) + "".join(f"k={k:<6}" for k in KS_FWD)
    print(hdr)
    for name, s in cands.items():
        row = name.ljust(18)
        for k in KS_FWD:
            row += f"{_auc(s, fwd_drop[k]):<8.3f}"
        print(row)
    print("\n  (lead iff AUC stays >=0.60 at k=5..20; coincident-only if it decays to ~0.5)")


def main() -> int:
    print("Loading dollar-volume weights from trading.db (read-only)...")
    weights = load_weights()
    print(f"  {len(weights)} symbols, sum(weight)={weights.sum():.3f}, "
          f"top5={list(weights.sort_values(ascending=False).head(5).index)}")

    print("\nDownloading constituent closes (yfinance batch)...")
    closes = batch_close(list(weights.index))
    print(f"  got {closes.shape[1]} tickers, "
          f"span {closes.index.min().date()}..{closes.index.max().date()}")

    print("Downloading macro series...")
    m = batch_close(MACRO)

    basket = build_basket(weights, closes)
    cov = basket.attrs["coverage"]
    dropped = basket.attrs["dropped"]
    nn = basket.attrs["n_names"]
    print(f"\nBasket: {len(basket)} days {basket.index.min().date()}.."
          f"{basket.index.max().date()}  coverage={cov:.1%} of weight-names")
    print(f"  constituents/day: min={int(nn.min())} median={int(nn.median())} "
          f"max={int(nn.max())}   dropped(no yf data)={dropped}")

    # basket vs SPY character
    spy_ret = m["SPY"].pct_change().reindex(basket.index)
    common = basket.notna() & spy_ret.notna()
    b, s = basket[common], spy_ret[common]
    beta = np.cov(b, s)[0, 1] / np.var(s)
    corr = np.corrcoef(b, s)[0, 1]
    print(f"\n  basket vs SPY:  beta={beta:.2f}  corr={corr:.2f}  "
          f"annVol basket={b.std()*np.sqrt(TRADING_DAYS):.1%} vs SPY "
          f"{s.std()*np.sqrt(TRADING_DAYS):.1%}")
    for tag, since in [("2024+", "2024-01-01")]:
        sub = (b.index >= pd.Timestamp(since))
        if sub.sum() > 20:
            bb, ss = b[sub], s[sub]
            be = np.cov(bb, ss)[0, 1] / np.var(ss)
            print(f"  {tag}: beta={be:.2f}  annVol basket={bb.std()*np.sqrt(TRADING_DAYS):.1%} "
                  f"vs SPY {ss.std()*np.sqrt(TRADING_DAYS):.1%}")

    run_h15(basket, m["^VIX"])
    run_h14(basket, m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
