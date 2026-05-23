"""Generate xgb_w3_blend.html — visual demo of the W3 ensemble vote.

Shows on five plausible market scenarios (synthetic, illustrative):
  - XGB-alone prediction
  - W3-alone prediction (with per-group contribution breakdown)
  - Blended prediction with the production W3_BLEND_WEIGHT=0.4
  - Whether the action would flip vs XGB-alone

Reads from:
  - backend/data/models/signal_xgb.json + .meta.json   (production XGB)
  - backend/data/models/signal_w3_pergroup.pt + meta   (W3 sidecar)
  - backend/data/feature_catalog.py                    (channel layout)
  - backend/config.py                                  (W3_BLEND_WEIGHT default)

Outputs: docs/agent_maps/xgb_w3_blend.html (light-theme, matches sibling pages).
"""
from __future__ import annotations

import datetime
import html
import json
import os
import sys
from pathlib import Path

import numpy as np
import torch

ROOT     = Path(__file__).resolve().parents[2]
BACKEND  = ROOT / "backend"
DOCS_OUT = ROOT / "docs" / "agent_maps"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "site-packages"))

from data.cnn_model import ALL_CHANNEL_COLUMNS                      # noqa: E402
from data.feature_catalog import CATALOG                            # noqa: E402
from data.w3_model import SignalW3, CATALYST_IDX, MOMENTUM_IDX, REGIME_IDX, GROUP_NAMES  # noqa: E402

# Load production XGB + W3
import xgboost as xgb                                               # noqa: E402

XGB_PATH  = BACKEND / "data/models/signal_xgb.json"
XGB_META  = BACKEND / "data/models/signal_xgb.json.meta.json"
W3_PATH   = BACKEND / "data/models/signal_w3_pergroup.pt"

xgb_meta = json.loads(XGB_META.read_text())
xgb_bst  = xgb.Booster(); xgb_bst.load_model(str(XGB_PATH))
xgb_filter = xgb_meta["feature_filter"]
xgb_filter_names = [ALL_CHANNEL_COLUMNS[i] for i in xgb_filter]

w3 = SignalW3(model_path=str(W3_PATH))
loaded_w3 = w3.load()

# Pull config default for W3_BLEND_WEIGHT
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("W3_BLEND_WEIGHT", "0.4")
os.environ.setdefault("W3_BLEND_ENABLED", "1")
from config import config                                           # noqa: E402
W = float(config.W3_BLEND_WEIGHT)

# ── Build five illustrative scenarios ──────────────────────────────────────
# Each scenario is a (38,) feature vector reflecting a plausible market state.
# Values are roughly z-scored — the actual standardization is applied by W3
# internally and XGB binning is scale-insensitive.

CHANNEL_NAMES = ALL_CHANNEL_COLUMNS

def make_scenario(**overrides) -> np.ndarray:
    x = np.zeros(38, dtype=np.float32)
    for name, value in overrides.items():
        idx = ALL_CHANNEL_COLUMNS.index(name)
        x[idx] = value
    return x

SCENARIOS = [
    {
        "label": "Strong catalyst, neutral macro",
        "summary": "Earnings beat + analyst upgrade. Macro flat. Momentum mild.",
        "x": make_scenario(
            analyst_score=+0.80, earnings_score=+0.60, alpaca_score=+0.40,
            r_120=+0.02, r_20d=+0.03,
            macro_spy_5d_back=0.005, macro_breadth_back=+0.10, macro_vix_norm=0.50,
            hist_seasonal=+0.20,
        ),
    },
    {
        "label": "Hot momentum, fading regime",
        "summary": "Stock has been rallying hard but SPY rolling over; VIX spiking. Classic late-cycle setup.",
        "x": make_scenario(
            analyst_score=+0.10, earnings_score=+0.05,
            r_120=+0.18, r_20d=+0.12, mom_12_1=+0.30, r_252d=+0.40,
            macro_spy_5d_back=-0.025, macro_breadth_back=-0.30, macro_vix_norm=1.5,
            hist_seasonal=-0.20,
        ),
    },
    {
        "label": "Risk-off macro shock",
        "summary": "VIX > 30, SPY -3% in 5 days, breadth collapsing. No symbol catalyst.",
        "x": make_scenario(
            analyst_score=+0.00, earnings_score=0.0,
            macro_spy_5d_back=-0.035, macro_dji_5d_back=-0.030,
            macro_breadth_back=-0.50, macro_vix_norm=2.0,
            macro_spy_10d_back=-0.05, macro_tlt_10d_back=+0.02,
            hist_seasonal=-0.30,
        ),
    },
    {
        "label": "Earnings miss + sector tailwind",
        "summary": "Bad earnings for this name but its sector is ripping. Conflicted signal.",
        "x": make_scenario(
            analyst_score=-0.40, earnings_score=-0.70, alpaca_score=-0.20,
            r_20d=-0.05, r_20d_sector_rel=-0.04, corr_spy_20d=+0.60,
            macro_spy_5d_back=+0.020, macro_breadth_back=+0.20, macro_vix_norm=0.55,
            hist_seasonal=+0.30,
        ),
    },
    {
        "label": "Quiet market, mild positive catalyst",
        "summary": "Low VIX, gentle SPY drift up, modest analyst score. The 'should we even trade' edge case.",
        "x": make_scenario(
            analyst_score=+0.30, earnings_score=+0.10, alpaca_score=+0.10,
            r_20=+0.01, r_120=+0.01,
            macro_spy_5d_back=+0.008, macro_breadth_back=+0.05, macro_vix_norm=0.45,
            hist_seasonal=+0.05,
        ),
    },
]

# ── Compute predictions ────────────────────────────────────────────────────

def xgb_predict(x_38: np.ndarray) -> float:
    """Apply XGB filter (8ch), wrap in DMatrix, predict."""
    sub = x_38[xgb_filter].reshape(1, -1)
    d = xgb.DMatrix(sub)
    return float(xgb_bst.predict(d)[0])

def w3_predict_with_breakdown(x_38: np.ndarray):
    """Return (pred, direction, conf, group_preds, blend_weights, gate_threshold_thr)."""
    if not loaded_w3:
        return 0.0, "neutral", 0.0, [0.0, 0.0, 0.0], [1/3]*3
    # Predict via SignalW3 (uses last-timestep + standardize internally)
    window = x_38.reshape(38, 1)
    pred, direction, conf = w3.predict(window)
    # Also pull per-group preds + blend weights from internal model
    x_t = torch.from_numpy(((x_38 - w3._mu) / w3._std).astype(np.float32)).unsqueeze(0)
    with torch.no_grad():
        regime = x_t.index_select(1, w3._model.regime_idx)
        blend = torch.softmax(w3._model.blend(regime), dim=-1).cpu().numpy().ravel().tolist()
        gpreds = []
        for g_idx, head in zip(w3._model.group_idx, w3._model.heads):
            xg = x_t.index_select(1, g_idx)
            gpreds.append(float(head(xg).cpu().item()))
    return pred, direction, conf, gpreds, blend

# Direction thresholds match xgb_reasoning_agent surrogate path + W3 internal
def direction_label(pred: float) -> str:
    if pred >  0.003: return "BULL"
    if pred < -0.003: return "BEAR"
    return "NEUTRAL"

def action_label(pred: float) -> str:
    # Simplified: bull -> BUY, bear -> SELL, neutral -> HOLD
    d = direction_label(pred)
    return {"BULL": "BUY", "BEAR": "SELL", "NEUTRAL": "HOLD"}[d]

rows = []
for s in SCENARIOS:
    xpred  = xgb_predict(s["x"])
    wpred, wdir, wconf, gpreds, blend = w3_predict_with_breakdown(s["x"])
    bpred  = (1 - W) * xpred + W * wpred
    flips  = action_label(bpred) != action_label(xpred)
    rows.append({
        "scenario": s["label"], "summary": s["summary"],
        "x": s["x"],
        "xgb_pred": xpred,    "xgb_action":   action_label(xpred),
        "w3_pred":  wpred,    "w3_action":    action_label(wpred),
        "blend_pred": bpred,  "blend_action": action_label(bpred),
        "group_preds": gpreds, "group_blends": blend,
        "flips": flips,
    })

# ── HTML rendering ─────────────────────────────────────────────────────────

def color_for(pred: float) -> str:
    if pred >  0.003: return "#1a7f37"   # green
    if pred < -0.003: return "#cf222e"   # red
    return "#6e7781"                      # gray

def fmt_pred(pred: float) -> str:
    return f"{pred*100:+.2f}%"

def render_active_inputs(x: np.ndarray) -> str:
    """Show the channels that were set in this scenario (non-zero)."""
    items = []
    for i in range(38):
        if abs(x[i]) > 1e-6:
            items.append((CHANNEL_NAMES[i], float(x[i])))
    items.sort(key=lambda kv: -abs(kv[1]))
    return ", ".join(f"<code>{html.escape(n)}={v:+.2f}</code>" for n, v in items[:10])

def render_group_breakdown(gpreds, blends):
    """Show per-group contribution: blend_weight × group_pred."""
    contrib = [b * p for b, p in zip(blends, gpreds)]
    total = sum(contrib)
    cells = []
    for gname, b, p, c in zip(GROUP_NAMES, blends, gpreds, contrib):
        share = abs(c) / max(1e-9, sum(abs(x) for x in contrib))
        bar = max(2, int(share * 100))
        cells.append(
            f"<div class='group-row'>"
            f"  <span class='gname'>{html.escape(gname)}</span>"
            f"  <span class='gblend'>blend {b*100:.0f}%</span>"
            f"  <span class='gpred' style='color:{color_for(p)}'>pred {fmt_pred(p)}</span>"
            f"  <span class='gcontrib' style='color:{color_for(c)}'>contrib {fmt_pred(c)}</span>"
            f"  <div class='cbar'><div class='cbar-fill' style='width:{bar}%;background:{color_for(c)}'></div></div>"
            f"</div>"
        )
    return "<div class='groups'>" + "".join(cells) + "</div>"

now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
w3_status = "loaded" if loaded_w3 else "NOT loaded — using zero-fallback (run agent retrain first)"
w3_wfe = w3._mean_wfe if loaded_w3 else None
xgb_wfe = xgb_meta.get("mean_wfe")
w3_wfe_str = f"{w3_wfe:+.4f}" if w3_wfe is not None else "not yet measured"

scenario_rows_html = ""
for r in rows:
    flip_tag = "<span class='flip-tag'>action FLIPS vs XGB</span>" if r["flips"] else ""
    scenario_rows_html += f"""
    <section class='scenario'>
      <header>
        <h2>{html.escape(r['scenario'])}  {flip_tag}</h2>
        <p class='summary'>{html.escape(r['summary'])}</p>
        <p class='inputs'>Active channels: {render_active_inputs(r['x'])}</p>
      </header>
      <div class='preds'>
        <div class='pred-card xgb'>
          <div class='label'>XGB alone</div>
          <div class='val' style='color:{color_for(r['xgb_pred'])}'>{fmt_pred(r['xgb_pred'])}</div>
          <div class='action' style='color:{color_for(r['xgb_pred'])}'>{r['xgb_action']}</div>
        </div>
        <div class='pred-card w3'>
          <div class='label'>W3 alone</div>
          <div class='val' style='color:{color_for(r['w3_pred'])}'>{fmt_pred(r['w3_pred'])}</div>
          <div class='action' style='color:{color_for(r['w3_pred'])}'>{r['w3_action']}</div>
        </div>
        <div class='pred-card blend'>
          <div class='label'>Blended  (60%/40%)</div>
          <div class='val' style='color:{color_for(r['blend_pred'])}'>{fmt_pred(r['blend_pred'])}</div>
          <div class='action' style='color:{color_for(r['blend_pred'])}'>{r['blend_action']}</div>
          <div class='formula'>{(1-W):.1f} × {r['xgb_pred']*100:+.2f}%  +  {W:.1f} × {r['w3_pred']*100:+.2f}%</div>
        </div>
      </div>
      <details class='w3-detail'>
        <summary>W3 per-group breakdown</summary>
        {render_group_breakdown(r['group_preds'], r['group_blends'])}
      </details>
    </section>"""

doc = f"""<!doctype html>
<html lang='en'>
<head>
<meta charset='utf-8'>
<title>XGB + W3 ensemble blend — illustrative example</title>
<link rel='stylesheet' href='style.css'>
<style>
  body {{ font-size: 14px; padding: 0 24px 60px; }}
  h1 {{ margin: 24px 0 4px; color: #0d1117; }}
  .stamp {{ color: #424a53; font-size: 12px; margin-bottom: 18px; }}
  .nav {{ margin: 6px 0 18px; }}
  .nav a {{ color: #0969da; text-decoration: none; margin-right: 14px; font-size: 13px; }}
  .nav a:hover {{ text-decoration: underline; }}
  .verdict {{ background: #ddf4ff; border-left: 4px solid #0969da; padding: 12px 16px; margin: 12px 0 24px; border-radius: 4px; color: #1f2328; }}
  .verdict h2 {{ margin: 0 0 6px; color: #0a3069; border: none; padding: 0; font-size: 16px; }}
  .verdict code {{ background: #cbe7ff; color: #0a3069; padding: 1px 5px; border-radius: 3px; }}
  .scenario {{ background: #ffffff; border: 1px solid #d1d9e0; border-radius: 6px; padding: 14px 18px; margin: 14px 0; }}
  .scenario header h2 {{ margin: 0 0 4px; font-size: 16px; color: #0d1117; }}
  .summary {{ color: #424a53; margin: 4px 0 6px; }}
  .inputs {{ color: #424a53; font-size: 12px; margin: 4px 0 12px; }}
  .inputs code {{ background: #eaeef2; color: #1f2328; padding: 1px 5px; margin-right: 4px; border-radius: 3px; font-size: 11px; }}
  .flip-tag {{ display: inline-block; background: #fff1e5; color: #7d4e00; padding: 1px 8px; border-radius: 3px; font-size: 11px; font-weight: 700; margin-left: 8px; vertical-align: middle; }}
  .preds {{ display: grid; grid-template-columns: 1fr 1fr 1.4fr; gap: 12px; margin: 12px 0; }}
  .pred-card {{ background: #f6f8fa; border: 1px solid #d1d9e0; border-radius: 6px; padding: 10px 12px; text-align: center; }}
  .pred-card.blend {{ background: #ddf4ff; border-color: #0969da; }}
  .pred-card .label {{ font-size: 11px; color: #424a53; text-transform: uppercase; letter-spacing: 0.05em; }}
  .pred-card .val {{ font-size: 24px; font-weight: 700; margin: 4px 0; font-variant-numeric: tabular-nums; }}
  .pred-card .action {{ font-size: 13px; font-weight: 600; }}
  .pred-card .formula {{ font-size: 11px; color: #424a53; margin-top: 4px; font-variant-numeric: tabular-nums; }}
  .w3-detail {{ background: #f6f8fa; border-radius: 4px; padding: 8px 12px; margin-top: 6px; }}
  .w3-detail summary {{ cursor: pointer; color: #0969da; font-size: 12px; }}
  .groups {{ margin-top: 8px; }}
  .group-row {{ display: grid; grid-template-columns: 100px 90px 110px 110px 1fr; gap: 8px; align-items: center; padding: 4px 0; font-size: 12px; font-variant-numeric: tabular-nums; }}
  .gname {{ font-weight: 600; color: #1f2328; }}
  .gblend, .gpred, .gcontrib {{ color: #424a53; }}
  .cbar {{ height: 8px; background: #eaeef2; border-radius: 2px; overflow: hidden; }}
  .cbar-fill {{ height: 100%; }}
</style>
</head>
<body>
  <h1>XGB + W3 ensemble blend — illustrative example</h1>
  <div class='stamp'>generated {now} · XGB <code>backend/data/models/signal_xgb.json</code> · W3 {w3_status}</div>

  <div class='nav'>
    <a href='_summary.html'>← all agents</a>
    <a href='xgb_channels.html'>XGB channels</a>
    <a href='XGBReasoningAgent.html'>XGBReasoningAgent</a>
  </div>

  <div class='verdict'>
    <h2>How to read this page</h2>
    <p>Each scenario below is a synthetic market state (catalyst + macro + momentum profile). For each, we show what the production XGB model would predict, what the W3 per-group blend model would predict, and what the ensemble agent <em>actually emits</em> after blending them at <code>W3_BLEND_WEIGHT={W:.2f}</code> (the live default).</p>
    <p>The blend formula is <code>final_pred = (1 - {W:.1f}) × xgb_pred + {W:.1f} × w3_pred</code>. WFE gate uses <code>max(xgb.mean_wfe={xgb_wfe:+.4f}, w3.mean_wfe={w3_wfe_str})</code> — either model healthy → BUYs allowed.</p>
    <p>Watch for the <span class='flip-tag'>action FLIPS vs XGB</span> tag — those are the scenarios where the W3 vote changes the agent's decision. The <strong>W3 per-group breakdown</strong> dropdown shows how each of the three groups (Catalyst / Momentum / Regime) contributed to the W3 prediction.</p>
  </div>

  {scenario_rows_html}

</body>
</html>
"""

out_path = DOCS_OUT / "xgb_w3_blend.html"
out_path.write_text(doc, encoding="utf-8")
print(f"wrote {out_path}  ({len(doc):,} bytes)")
print(f"  W3 loaded: {loaded_w3}")
print(f"  W3 mean_wfe: {w3_wfe}")
print(f"  XGB mean_wfe: {xgb_wfe}")
print(f"  W3_BLEND_WEIGHT: {W}")
print(f"  scenarios: {len(rows)}")
flips = sum(1 for r in rows if r['flips'])
print(f"  action flips: {flips}/{len(rows)}")
