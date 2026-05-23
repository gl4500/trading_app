"""Generate xgb_channels.html — full 38-channel inventory with model usage,
weighting (booster gain), audit IC, and per-channel implications.

Read sources:
  - backend/data/feature_catalog.py (channel metadata)
  - C:/Users/gl450/AppData/Local/Temp/channel_audit.json (IC, coverage)
  - C:/Users/gl450/AppData/Local/Temp/xgb_gain.json (production 8ch booster gain)
  - C:/Users/gl450/AppData/Local/Temp/xgb_gain_12ch.json (sidecar 12ch booster gain)
  - backend/data/models/signal_xgb.json.meta.json (headline metrics)

Output:
  - docs/agent_maps/xgb_channels.html  (self-contained except style.css already in dir)
"""
from __future__ import annotations
import json, os, sys, html, datetime
from pathlib import Path

ROOT     = Path(__file__).resolve().parents[2]   # trading_app/
BACKEND  = ROOT / "backend"
DOCS_OUT = ROOT / "docs" / "agent_maps"
sys.path.insert(0, str(BACKEND))

from data.feature_catalog import CATALOG, PRODUCTION_XGB_FILTER  # noqa: E402

PROD_FILTER_NAMES = set(PRODUCTION_XGB_FILTER)
EXP_12CH_NAMES = set(PRODUCTION_XGB_FILTER) | {
    "hist_seasonal", "hist_channel_position", "hist_momentum_alignment", "hist_volume_pattern"
}

TMP = Path(r"C:/Users/gl450/AppData/Local/Temp")
audit = json.loads((TMP / "channel_audit.json").read_text())
gain  = json.loads((TMP / "xgb_gain.json").read_text())
gain12 = json.loads((TMP / "xgb_gain_12ch.json").read_text())
prod_meta = json.loads((BACKEND / "data/models/signal_xgb.json.meta.json").read_text())
exp_meta  = json.loads((BACKEND / "data/models/signal_xgb_exp_12ch.json.meta.json").read_text())

# index audit by channel name
audit_by = {r["name"]: r for r in audit["ranking_by_abs_ic_win"]}

# Implications — what the audit + booster gain tell us about each channel
def implication(ch_name, in_prod, in_exp, ic_win, stab, gain_pct, gain_pct_12, cov) -> str:
    abs_ic = abs(ic_win)
    if in_prod and gain_pct >= 50:
        return ("DOMINATES the model. " +
                ("Single-feature collapse — only channel the booster uses." if gain_pct >= 95
                 else f"Carries {gain_pct:.0f}% of all tree gain."))
    if in_prod and gain_pct == 0:
        return ("DEAD WEIGHT in trained booster. "
                + (f"Decent IC ({ic_win:+.3f}) but never split — probably masked by analyst_score." if abs_ic > 0.02
                   else f"Low IC ({ic_win:+.3f}) and unused — consistent: drop or replace."))
    if in_prod and 0 < gain_pct < 5:
        return f"Minor contributor ({gain_pct:.1f}% gain). Marginal lift, easily lost in retrain noise."
    if (not in_prod) and abs_ic >= 0.04 and stab >= 0.03:
        return f"PROMOTE CANDIDATE — pool-only with IC {ic_win:+.3f}, stability {stab:.3f}. Stronger than several in-filter channels."
    if (not in_prod) and abs_ic >= 0.03:
        return f"Pool-only. IC {ic_win:+.3f} is competitive with weakest in-filter channels."
    if cov < 0.05:
        return f"Coverage {cov*100:.1f}% — too sparse to be reliable, regardless of IC."
    if abs_ic < 0.01:
        return f"IC ≈ 0 — noise channel. Excluding has no expected effect."
    return f"Marginal signal (IC {ic_win:+.3f}, stab {stab:.3f}). Low-priority promote."

rows = []
for i, c in enumerate(CATALOG):
    a = audit_by.get(c.name)
    if a is None:
        continue
    in_prod = c.name in PROD_FILTER_NAMES
    in_exp  = c.name in EXP_12CH_NAMES
    gain_p = gain["per_channel"].get(c.name, {}).get("gain_pct", 0.0) if in_prod else 0.0
    gain_p12 = gain12["per_channel"].get(c.name, {}).get("gain_pct", 0.0) if in_exp else 0.0
    rows.append({
        "i": i,
        "name": c.name,
        "category": c.category,
        "inputs": ", ".join(c.inputs),
        "computation": c.computation,
        "horizon": c.horizon,
        "added": c.added,
        "in_prod": in_prod,
        "in_exp": in_exp,
        "cov":    a["cov"],
        "ic_win": a["ic_win"],
        "ic_last": a["ic_last"],
        "stab":   a["stab"],
        "per_fold": a["per_fold"],
        "gain_pct":    gain_p,
        "gain_pct_12": gain_p12,
        "implication": implication(c.name, in_prod, in_exp, a["ic_win"], a["stab"], gain_p, gain_p12, a["cov"]),
        "notes": c.notes,
    })

# Sort: in-filter first (by gain desc), then by |IC_win| desc
rows.sort(key=lambda r: (
    0 if r["in_prod"] else (1 if r["in_exp"] else 2),
    -r["gain_pct"],
    -abs(r["ic_win"]),
))

# ── HTML rendering ────────────────────────────────────────────────────────

CAT_COLORS = {
    "SOURCE":            "#3b82f6",
    "AGENT":             "#a855f7",
    "RV":                "#f59e0b",
    "RETURN":            "#ef4444",
    "RETURN_DAILY":      "#dc2626",
    "MACRO":             "#10b981",
    "MACRO_10D":         "#059669",
    "MOMENTUM":          "#f97316",
    "SECTOR_RELATIVE":   "#8b5cf6",
    "SPY_CORRELATION":   "#ec4899",
    "HISTORICAL":        "#6366f1",
}

def chip(text, color, dark=False):
    fg = "#fff" if dark else "#fff"
    return f'<span class="chip" style="background:{color};color:{fg}">{html.escape(text)}</span>'

def cov_bar(p):
    pct = p * 100
    return f'<div class="bar"><div class="bar-fill" style="width:{pct:.1f}%"></div><span>{pct:.1f}%</span></div>'

def gain_bar(pct, peak):
    if pct == 0:
        return '<span class="muted">—</span>'
    width = min(100, pct / max(peak, 1) * 100)
    return f'<div class="bar bar-gain"><div class="bar-fill" style="width:{width:.1f}%"></div><span>{pct:.1f}%</span></div>'

def ic_cell(v):
    cls = "ic-pos" if v > 0.02 else ("ic-neg" if v < -0.02 else "ic-mid")
    return f'<span class="{cls}">{v:+.4f}</span>'

def per_fold_cell(vals):
    out = []
    for v in vals:
        cls = "ic-pos" if v > 0.05 else ("ic-neg" if v < -0.05 else "ic-mid")
        out.append(f'<span class="{cls} mini">{v:+.3f}</span>')
    return " ".join(out)

peak_gain = max(r["gain_pct"] for r in rows) or 1.0

# Section: production filter rows
prod_rows = [r for r in rows if r["in_prod"]]
exp_only_rows = [r for r in rows if (r["in_exp"] and not r["in_prod"])]
pool_rows = [r for r in rows if not r["in_exp"]]

def render_row(r):
    flags = []
    if r["in_prod"]: flags.append('<span class="flag flag-prod">PROD</span>')
    elif r["in_exp"]: flags.append('<span class="flag flag-exp">EXP12</span>')
    else: flags.append('<span class="flag flag-pool">POOL</span>')

    return f"""
    <tr>
      <td class="idx">{r['i']}</td>
      <td class="name">
        <div class="name-line">{html.escape(r['name'])}</div>
        <div class="sub">{html.escape(r['inputs'])} · {html.escape(r['computation'])}</div>
      </td>
      <td>{chip(r['category'], CAT_COLORS.get(r['category'], '#6b7280'))}</td>
      <td>{' '.join(flags)}</td>
      <td>{cov_bar(r['cov'])}</td>
      <td>{ic_cell(r['ic_win'])}</td>
      <td class="per-fold">{per_fold_cell(r['per_fold'])}<div class="sub">stab {r['stab']:.4f}</div></td>
      <td>{gain_bar(r['gain_pct'], peak_gain)}</td>
      <td>{gain_bar(r['gain_pct_12'], peak_gain) if r['in_exp'] else '<span class="muted">n/a</span>'}</td>
      <td class="impl">{html.escape(r['implication'])}</td>
    </tr>"""

def section(title, header_note, rows_sub):
    if not rows_sub:
        return ""
    return f"""
    <section>
      <h2>{html.escape(title)} <span class="count">({len(rows_sub)})</span></h2>
      <p class="note">{header_note}</p>
      <table class="data">
        <thead>
          <tr>
            <th>#</th><th>Channel · raw inputs · computation</th><th>Category</th>
            <th>In filter</th><th>Coverage</th><th>IC (window)</th>
            <th>Per-fold IC<br><span class="sub">old · mid · new</span></th>
            <th>Gain (prod 8ch)</th><th>Gain (exp 12ch)</th><th>Implication</th>
          </tr>
        </thead>
        <tbody>
          {''.join(render_row(r) for r in rows_sub)}
        </tbody>
      </table>
    </section>"""

# Headline summary numbers
prod_gain_used = gain["n_features_used"]
prod_gain_total = gain["n_features_total"]
analyst_gain_pct = next((r['gain_pct'] for r in prod_rows if r['name'] == 'analyst_score'), 0.0)
dead_in_prod    = [r for r in prod_rows if r['gain_pct'] == 0]
strong_in_pool  = [r for r in pool_rows if abs(r['ic_win']) >= 0.04 and r['stab'] >= 0.03]

now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>XGB Channels — Sources, Model Usage, Weighting, Implications</title>
<link rel="stylesheet" href="style.css">
<style>
  /* Light theme — text colors picked for 4.5:1+ contrast against the #fafbfc body */
  body {{ font-size: 14px; padding: 0 24px 80px; }}
  h1 {{ margin: 24px 0 4px; color: #0d1117; }}
  .stamp {{ color: #424a53; font-size: 12px; margin-bottom: 24px; }}
  .verdict {{ background: #fff8f1; border-left: 4px solid #cf222e; padding: 14px 18px; margin: 18px 0 8px; border-radius: 4px; color: #1f2328; }}
  .verdict h2 {{ margin: 0 0 8px; color: #82071e; border: none; padding: 0; }}
  .verdict ul {{ margin: 6px 0 0 18px; }}
  .verdict code {{ background: #ffeef0; padding: 1px 6px; border-radius: 3px; color: #82071e; }}
  .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 16px 0 24px; }}
  .kpi {{ background: #ffffff; padding: 12px 14px; border-radius: 6px; border: 1px solid #d1d9e0; }}
  .kpi .label {{ color: #424a53; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }}
  .kpi .val {{ font-size: 24px; font-weight: 700; margin-top: 4px; color: #1f2328; }}
  .kpi .good {{ color: #1a7f37; }}
  .kpi .bad  {{ color: #cf222e; }}
  .kpi .meh  {{ color: #9a6700; }}
  .kpi .sub  {{ color: #424a53; }}
  section {{ margin: 28px 0; }}
  h2 .count {{ color: #424a53; font-weight: 400; font-size: 0.7em; margin-left: 6px; }}
  table.data {{ width: 100%; border-collapse: collapse; font-size: 13px; background: #ffffff; }}
  table.data th {{ background: #f6f8fa; padding: 10px 8px; text-align: left; border-bottom: 1px solid #d1d9e0; vertical-align: top; color: #1f2328; font-weight: 600; }}
  table.data td {{ padding: 10px 8px; border-bottom: 1px solid #eaeef2; vertical-align: top; color: #1f2328; }}
  table.data tr:hover td {{ background: #f6f8fa; }}
  .idx {{ color: #424a53; font-variant-numeric: tabular-nums; text-align: right; }}
  .name-line {{ font-weight: 600; color: #0d1117; }}
  .sub {{ color: #424a53; font-size: 11px; margin-top: 2px; }}
  .chip {{ display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; color: #ffffff; }}
  .flag {{ display: inline-block; padding: 2px 6px; border-radius: 3px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; }}
  .flag-prod {{ background: #dafbe1; color: #116329; }}
  .flag-exp  {{ background: #fff1e5; color: #7d4e00; }}
  .flag-pool {{ background: #eaeef2; color: #424a53; }}
  .bar {{ position: relative; height: 16px; background: #eaeef2; border-radius: 3px; overflow: hidden; min-width: 100px; }}
  .bar-fill {{ position: absolute; left: 0; top: 0; bottom: 0; background: #0969da; }}
  .bar-gain .bar-fill {{ background: #bf8700; }}
  .bar span {{ position: relative; z-index: 1; padding: 0 6px; line-height: 16px; font-size: 11px; color: #0d1117; font-variant-numeric: tabular-nums; font-weight: 600; }}
  .ic-pos {{ color: #1a7f37; font-variant-numeric: tabular-nums; font-weight: 600; }}
  .ic-neg {{ color: #cf222e; font-variant-numeric: tabular-nums; font-weight: 600; }}
  .ic-mid {{ color: #424a53; font-variant-numeric: tabular-nums; }}
  .per-fold .mini {{ font-size: 11px; }}
  .impl {{ max-width: 360px; color: #1f2328; }}
  .muted {{ color: #6e7781; }}
  .note {{ color: #424a53; font-size: 12px; margin: 4px 0 12px; }}
  .nav {{ margin: 6px 0 14px; }}
  .nav a {{ color: #0969da; text-decoration: none; margin-right: 14px; font-size: 13px; }}
  .nav a:hover {{ text-decoration: underline; }}
  ul {{ color: #1f2328; }}
</style>
</head>
<body>
  <h1>XGB Channels — model inventory, weighting & implications</h1>
  <div class="stamp">generated {now} · model file <code>backend/data/models/signal_xgb.json</code> · audit window n={audit['n_samples']:,} samples</div>

  <div class="nav">
    <a href="_summary.html">← all agents</a>
    <a href="XGBReasoningAgent.html">XGBReasoningAgent map</a>
  </div>

  <div class="verdict">
    <h2>Verdict: the production booster has collapsed to a single feature.</h2>
    <ul>
      <li><b>{prod_gain_used} of {prod_gain_total} input features ever split</b> in the trained 8-channel booster — and <b>{int(analyst_gain_pct)}% of all gain</b> sits on <code>analyst_score</code> alone.</li>
      <li><b>Dead in production</b> ({len(dead_in_prod)} of {len(prod_rows)} filter channels never split): {", ".join(f"<code>{r['name']}</code>" for r in dead_in_prod)}.</li>
      <li>The 12-channel sidecar (current 8 + 4 HistoricalTrends channels) shows the same collapse — 97% analyst_score, 3% earnings_score, all other 10 channels dead.</li>
      <li>Headline: <code>mean_wfe = {prod_meta['mean_wfe']:.4f}</code> ({prod_meta['wfe_status']}) · <code>mean_ic = {prod_meta['mean_ic']:.4f}</code> · the WFE gate then SILENCES the agent in production because mean_wfe < 0 — see <code>xgb_reasoning_agent._apply_wfe_gate</code>.</li>
      <li><b>Your hypothesis is right, but the direction is the opposite:</b> the 38-channel POOL is fine — only 8 are even seen at training time, and within those 8 the model is overweighting one channel to the exclusion of all others. The fix isn't fewer channels — it's a better filter and possibly per-channel monotone constraints, OR a non-linear two-stage model where analyst_score is one input among several uncorrelated heads.</li>
    </ul>
  </div>

  <div class="kpis">
    <div class="kpi"><div class="label">mean_wfe (prod)</div><div class="val bad">{prod_meta['mean_wfe']:+.4f}</div><div class="sub">{prod_meta['wfe_status']} — silences agent</div></div>
    <div class="kpi"><div class="label">mean_ic (prod)</div><div class="val meh">{prod_meta['mean_ic']:+.4f}</div><div class="sub">predictive but tiny</div></div>
    <div class="kpi"><div class="label">IR (prod)</div><div class="val meh">{prod_meta['ir']:.2f}</div></div>
    <div class="kpi"><div class="label">features active</div><div class="val bad">{prod_gain_used}/{prod_gain_total}</div><div class="sub">10% utilization</div></div>
    <div class="kpi"><div class="label">analyst_score gain%</div><div class="val bad">{analyst_gain_pct:.0f}%</div><div class="sub">single-feature collapse</div></div>
    <div class="kpi"><div class="label">strong pool candidates</div><div class="val good">{len(strong_in_pool)}</div><div class="sub">|IC|≥0.04, stab≥0.03</div></div>
    <div class="kpi"><div class="label">mean_wfe (12ch sidecar)</div><div class="val bad">{exp_meta['mean_wfe']:+.4f}</div><div class="sub">{exp_meta['wfe_status']}</div></div>
    <div class="kpi"><div class="label">mean_ic (12ch sidecar)</div><div class="val meh">{exp_meta['mean_ic']:+.4f}</div></div>
  </div>

  {section("Production 8-channel filter (XGB_FEATURE_FILTER)",
           "These eight channels are what SignalXGBoost actually trains on. The 'Gain (prod 8ch)' column shows total tree gain — analyst_score eats the entire budget; the rest are passengers.",
           prod_rows)}

  {section("12-channel experimental sidecar (HistoricalTrends-borrowed)",
           "Sidecar model only — NOT promoted to production. Adds the 4 HistoricalTrendsAgent sub-scores. Booster still collapses to analyst_score (97%) + earnings_score (3%). The other 10 channels never split even when present at training time.",
           exp_only_rows)}

  {section("Pool-only channels (in the 38-ch catalog but NOT in any filter)",
           "Available in build_training_windows but never fed to the booster. Look at the 'Implication' column for promote candidates — any pool channel with |IC|≥0.04 and stab≥0.03 is stronger than the weakest in-filter channels and worth promoting.",
           pool_rows)}

  <section>
    <h2>How to read this page</h2>
    <ul style="line-height:1.7;color:#cbd5e1">
      <li><b>IC (window):</b> Pearson correlation between the channel's window-mean value and the forward return label, over all {audit['n_samples']:,} training samples. Positive = bullish-when-high. Magnitudes &gt; 0.03 are notable in equity-prediction land.</li>
      <li><b>Per-fold IC:</b> the same correlation computed on each of the three walk-forward validation folds (oldest / middle / newest). A channel whose IC flips sign between folds is non-stationary and unsafe to weight heavily.</li>
      <li><b>stab:</b> min(|per-fold IC|) — higher means the channel keeps its sign across regimes.</li>
      <li><b>Gain (prod / exp):</b> total XGBoost split gain summed across the channel's lag features. <code>0.0%</code> means the booster never chose to split on any lag of this channel — pure dead weight in that model, regardless of its raw IC.</li>
      <li><b>Coverage:</b> fraction of (sample, lag) cells with a non-zero value. Macro channels show ~55% because they're sparse before backfill caught up; SOURCE channels show ~5% because most rows are blanks (analyst recos don't change every cycle).</li>
    </ul>
  </section>

</body>
</html>
"""

out_path = DOCS_OUT / "xgb_channels.html"
out_path.write_text(doc, encoding="utf-8")
print(f"wrote {out_path}  ({len(doc):,} bytes)")
print(f"  prod rows:     {len(prod_rows)}")
print(f"  exp-only rows: {len(exp_only_rows)}")
print(f"  pool rows:     {len(pool_rows)}")
print(f"  strong pool candidates (|IC|>=0.04, stab>=0.03): {len(strong_in_pool)}")
for r in strong_in_pool:
    print(f"    [{r['i']:>2}] {r['name']:30s}  IC={r['ic_win']:+.4f}  stab={r['stab']:.4f}")
