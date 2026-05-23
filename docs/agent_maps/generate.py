"""Generate per-agent data/model maps as HTML + a comparison page.

Run:  python docs/agent_maps/generate.py
Output:  docs/agent_maps/<agent>.html, docs/agent_maps/_summary.html, style.css
"""
from __future__ import annotations
import os, html
from pathlib import Path

OUT = Path(__file__).parent

# ── Data source registry (provider, category) ────────────────────────────────
SOURCES = {
    "price":          ("Alpaca Markets",                  "market"),
    "long_term_bars": ("Alpaca Markets (50-day)",         "market"),
    "alpaca_news":    ("Alpaca news API → news_service",  "news"),
    "yahoo_news":     ("yfinance → news_service",         "news"),
    "analyst":        ("yfinance.recommendations",        "fund"),
    "earnings":       ("yfinance.earnings_history",       "fund"),
    "iv_rv":          ("yfinance options",                "fund"),
    "vix":            ("VIX index (macro feed)",          "macro"),
    "spy":            ("SPY daily close (macro)",         "macro"),
    "iwm":            ("IWM daily close (macro)",         "macro"),
    "gld":            ("GLD daily close (macro)",         "macro"),
    "tlt":            ("TLT daily close (macro)",         "macro"),
    "dia":            ("DIA daily close (macro)",         "macro"),
    "calendar":       ("snapshot_ts (system clock)",      "calendar"),
    "claude_api":     ("Anthropic Claude Opus 4.6",       "llm"),
    "gemini_api":     ("Google Gemini 2.0 Flash",         "llm"),
    "openai_api":     ("OpenAI GPT-4o-mini",              "llm"),
    "ollama_api":     ("Local Ollama (llama3.1:8b)",      "llm"),
    "signal_history": ("38-channel feature pool (signal_history)", "derived"),
    "technicals_fmt": ("data.technicals.format_for_prompt", "derived"),
    "composite_sig":  ("Composite signal from signal_aggregator", "derived"),
    "regime_det":     ("data.regime_detector (HMM)",      "derived"),
    "agent_signals":  ("Other agents' signals",           "derived"),
    "portfolio":      ("Portfolio state (positions/cash)", "internal"),
    "scanner_recs":   ("Scanner AI candidate list",       "derived"),
}

CATEGORY_LABELS = {
    "market":   "Market data",
    "news":     "News / sentiment",
    "fund":     "Fundamentals",
    "macro":    "Macro / ETFs",
    "calendar": "Calendar",
    "llm":      "LLM APIs",
    "derived":  "Internal / derived",
    "internal": "Internal state",
}

# ── Agent definitions ────────────────────────────────────────────────────────
AGENTS = {
    "TechAgent": {
        "file": "agents/tech_agent.py",
        "desc": "Pure technical analysis (RSI + MACD) on hourly bars.",
        "sources": {
            "price":     "ctx['bars'] → manual RSI & MACD",
            "portfolio": "self.portfolio.positions for SELL eval",
        },
        "models": [],
        "ensemble": {"in": True, "base": 0.23, "trending": 1.20, "ranging": 1.10, "volatile": 0.80},
        "perf":     {"roi": "+0.91%", "realized": "-$41",   "trades": 20, "wl": "4 / 4"},
        "outputs":  "Signal(BUY/SELL/HOLD, confidence, shares) per symbol",
        "notes":    "Highest ensemble base weight (0.23) but flat realized P&L this window.",
    },
    "MomentumAgent": {
        "file": "agents/momentum_agent.py",
        "desc": "Volume-weighted momentum across short/mid/long horizons.",
        "sources": {
            "price":     "ctx['bars'] + ctx['price'] for sizing",
            "portfolio": "Trailing-stop state from positions",
        },
        "models": [],
        "ensemble": {"in": True, "base": 0.14, "trending": 1.50, "ranging": 0.55, "volatile": 0.65},
        "perf":     {"roi": "+1.25%", "realized": "-$263",  "trades": 143, "wl": "34 / 42"},
        "outputs":  "Signal per symbol; highest trade volume of any agent (1,842 all-time).",
        "notes":    "Biggest regime tilt: 1.50 in trending. Over-trades — low win rate (44.7%).",
    },
    "MeanReversionAgent": {
        "file": "agents/mean_reversion_agent.py",
        "desc": "Z-score-based mean reversion on price.",
        "sources": {
            "price":     "ctx['bars'] for z-score window",
            "portfolio": "Position lookup",
        },
        "models": [],
        "ensemble": {"in": True, "base": 0.09, "trending": 0.40, "ranging": 1.60, "volatile": 0.60},
        "perf":     {"roi": "+2.15%", "realized": "+$159",  "trades": 68, "wl": "25 / 12 (67.6% win)"},
        "outputs":  "Signal per symbol; highest win rate but tiny W:L (0.53) → small total P&L.",
        "notes":    "Strongest regime-multiplier specialist: 1.60 in ranging, 0.40 in trending.",
    },
    "HistoricalTrendsAgent": {
        "file": "agents/historical_trends_agent.py",
        "desc": "Composite of seasonal (20%) + channel position (30%) + momentum alignment (40%) + volume (10%).",
        "sources": {
            "price":          "ctx['bars'] + ctx['long_term_bars'] (50-day window)",
            "long_term_bars": "Multi-period momentum & channel-position computation",
            "calendar":       "Month-of-year + quarter-position seasonality",
            "portfolio":      "Position lookup",
        },
        "models": [],
        "ensemble": {"in": True, "base": 0.08, "trending": 1.20, "ranging": 1.30, "volatile": 0.80},
        "perf":     {"roi": "+3.97%", "realized": "+$5,449", "trades": 49, "wl": "15 / 13"},
        "outputs":  "Composite-score-driven BUY/SELL with reasoning citing seasonal/channel/momentum.",
        "notes":    "Lowest base ensemble weight (0.08) but best window performer. 4 hist_* sub-scores are also XGB channels (29–32).",
    },
    "XGBReasoningAgent": {
        "file": "agents/xgb_reasoning_agent.py",
        "desc": "Learned signal model (XGBoost via selector) + Ollama LLM active reasoning.",
        "sources": {
            "signal_history": "Full 38-channel pool → SignalXGBoost.predict",
            "ollama_api":     "Post-model LLM reasoning over model output + scores",
            "portfolio":      "Stop/trailing/cooldown enforcement",
        },
        "models": [("SignalXGBoost", "signal_xgb.json", "Currently mean_wfe = -0.10 (POOR) — WFE gate blocking all BUYs")],
        "ensemble": {"in": True, "base": "0.10 (default — not in ENSEMBLE_WEIGHTS dict)", "trending": 1.20, "ranging": 0.90, "volatile": 1.10},
        "perf":     {"roi": "+0.36%", "realized": "-$666", "trades": 8, "wl": "1 / 7 (gated)"},
        "outputs":  "BUY/SELL/HOLD; gated to HOLD when mean_wfe < 0 (active).",
        "notes":    "Only agent reading the 38-channel pool. WFE gate added 2026-05-17 has silenced new BUYs ever since.",
    },
    "ClaudeAgent": {
        "file": "agents/claude_agent.py",
        "desc": "Claude Opus reasoning over technical & news context.",
        "sources": {
            "price":          "ctx['bars']",
            "alpaca_news":    "news_service",
            "yahoo_news":     "news_service",
            "technicals_fmt": "data.technicals.format_for_prompt",
            "claude_api":     "Anthropic API (or Ollama route when OLLAMA_ONLY_MODE)",
            "portfolio":      "Position context for prompt",
        },
        "models": [],
        "ensemble": {"in": True, "base": 0.20, "trending": 1.10, "ranging": 1.00, "volatile": 1.40},
        "perf":     {"roi": "+0.44%", "realized": "-$1,042", "trades": 18, "wl": "1 / 1"},
        "outputs":  "JSON BUY/SELL/HOLD + structured reasoning from LLM.",
        "notes":    "2nd-highest base ensemble weight (0.20). Strongest volatile-regime tilt (1.40). Biggest realized loser among LLM cohort in window.",
    },
    "GeminiAgent": {
        "file": "agents/gemini_agent.py",
        "desc": "Gemini Flash reasoning — news-only / scanner-only role.",
        "sources": {
            "price":          "ctx['bars']",
            "alpaca_news":    "news_service",
            "yahoo_news":     "news_service",
            "gemini_api":     "Google Gemini API",
            "portfolio":      "Position context",
        },
        "models": [],
        "ensemble": {"in": False, "base": "—", "trending": "—", "ranging": "—", "volatile": "—",
                     "note": "Excluded from ENSEMBLE_WEIGHTS — 'news-only' per ensemble init comment."},
        "perf":     {"roi": "—", "realized": "$0", "trades": 1, "wl": "0 / 0"},
        "outputs":  "Reasoning only — does not influence ensemble vote.",
        "notes":    "Effectively inactive as a trader. Used by ScannerAgent's _run_gemini_scanner candidate-ranking tool.",
    },
    "SentimentAgent": {
        "file": "agents/sentiment_agent.py",
        "desc": "GPT-4o-mini sentiment scoring + news-driven BUY/SELL.",
        "sources": {
            "price":       "ctx['bars']",
            "alpaca_news": "news_service",
            "yahoo_news":  "news_service",
            "openai_api":  "GPT-4o-mini sentiment classification (or Ollama route)",
            "portfolio":   "Position context",
        },
        "models": [],
        "ensemble": {"in": True, "base": 0.17, "trending": 0.80, "ranging": 1.20, "volatile": 1.20},
        "perf":     {"roi": "+0.46%", "realized": "+$158", "trades": 4, "wl": "1 / 0 (small sample)"},
        "outputs":  "BUY/SELL/HOLD weighted by sentiment confidence.",
        "notes":    "3rd-highest base weight (0.17), but only 4 trades in window — under-firing.",
    },
    "OllamaAgent": {
        "file": "agents/ollama_agent.py",
        "desc": "Local-LLM (llama3.1:8b) reasoning over technicals + news + composite signal.",
        "sources": {
            "price":          "ctx['bars']",
            "alpaca_news":    "news_service",
            "yahoo_news":     "news_service",
            "technicals_fmt": "data.technicals.format_for_prompt",
            "composite_sig":  "ctx['composite_signal'] from signal_aggregator",
            "ollama_api":     "Local Ollama via OpenAI-compatible client",
            "portfolio":      "Held set",
        },
        "models": [],
        "ensemble": {"in": True, "base": 0.09, "trending": "(no explicit multiplier — defaults to 1.0)", "ranging": "1.0", "volatile": "1.0"},
        "perf":     {"roi": "0.00%", "realized": "$0", "trades": 0, "wl": "0 / 0"},
        "outputs":  "BUY/SELL/HOLD JSON from local LLM.",
        "notes":    "Inactive in window (0 trades). When OLLAMA_ONLY_MODE=1, all LLM agents route here.",
    },
    "ScannerAgent": {
        "file": "agents/scanner_portfolio_agent.py (registers as 'ScannerAgent')",
        "desc": "Trades the scanner pipeline's AI-ranked recommendations directly. Standalone (not in ensemble).",
        "sources": {
            "price":        "trading.alpaca_client.get_bars_multi (own fetch, not via ctx)",
            "scanner_recs": "Scanner pipeline's recommendations (separate run)",
            "portfolio":    "Position + cash management",
        },
        "models": [],
        "ensemble": {"in": False, "base": "—", "note": "Standalone agent — its own portfolio, not aggregated."},
        "perf":     {"roi": "+1.24%", "realized": "$0 (5 BUYs, 0 SELLs)", "trades": 5, "wl": "0 / 0"},
        "outputs":  "Direct portfolio actions on scanner picks.",
        "notes":    "Window ROI is pure unrealized (no closed trades). Source pipeline uses Gemini/OpenAI/Ollama scanners (scanner_agent.py).",
    },
    "EnsembleAgent": {
        "file": "agents/ensemble_agent.py",
        "desc": "Adaptive performance-weighted vote across component agents, modulated by regime.",
        "sources": {
            "agent_signals": "All component agents' Signal(action, confidence, shares)",
            "regime_det":    "regime_detector.get_ensemble_regime() — HMM regime",
            "price":         "ctx['bars'] for SPY update to regime_detector",
            "portfolio":     "Position lookup",
        },
        "models": [],
        "ensemble": {"in": False, "base": "—", "note": "IS the aggregator."},
        "perf":     {"roi": "+0.33%", "realized": "$0 (0 trades)", "trades": 0, "wl": "—"},
        "outputs":  "Single consensus Signal per symbol when threshold (0.60) met.",
        "notes":    "0 trades in window — likely failing the 0.60 conviction threshold. Component agents combined: 7 of 12.",
    },
}

# ── Helpers ──────────────────────────────────────────────────────────────────
def cat_chip(cat: str) -> str:
    label = CATEGORY_LABELS.get(cat, cat)
    return f'<span class="chip chip-{cat}">{label}</span>'

def render_sources_table(sources: dict) -> str:
    rows = []
    for sid, how in sources.items():
        provider, cat = SOURCES.get(sid, ("(unknown)", "derived"))
        rows.append(
            f'<tr><td>{html.escape(sid)}</td>'
            f'<td>{cat_chip(cat)}</td>'
            f'<td>{html.escape(provider)}</td>'
            f'<td><code>{html.escape(how)}</code></td></tr>'
        )
    return "\n".join(rows)

def render_models_table(models: list) -> str:
    if not models:
        return '<p class="muted">No model artifact consumed — this agent computes signals directly from its inputs.</p>'
    rows = [f'<tr><td><b>{html.escape(n)}</b></td><td><code>{html.escape(f)}</code></td><td>{html.escape(d)}</td></tr>' for n, f, d in models]
    return ('<table><thead><tr><th>Model</th><th>Artifact</th><th>Status / notes</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')

def render_ensemble(ens: dict) -> str:
    if not ens.get("in"):
        note = ens.get("note", "Not in ensemble.")
        return f'<p class="muted">{html.escape(note)}</p>'
    return (
        f'<table><thead><tr><th>Base weight</th><th>Trending ×</th><th>Ranging ×</th><th>Volatile ×</th></tr></thead>'
        f'<tbody><tr>'
        f'<td><b>{ens["base"]}</b></td>'
        f'<td>{ens["trending"]}</td>'
        f'<td>{ens["ranging"]}</td>'
        f'<td>{ens["volatile"]}</td>'
        f'</tr></tbody></table>'
    )

def render_perf(p: dict) -> str:
    return (
        f'<table><thead><tr><th>Window ROI</th><th>Realized P&amp;L</th><th>Trades</th><th>Win / Loss</th></tr></thead>'
        f'<tbody><tr><td>{p["roi"]}</td><td>{p["realized"]}</td><td>{p["trades"]}</td><td>{p["wl"]}</td></tr></tbody></table>'
    )

AGENT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{name} — Agent map</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<header>
  <p class="back"><a href="_summary.html">← all agents (comparison)</a></p>
  <h1>{name}</h1>
  <p class="meta">{desc}</p>
  <p class="meta">Class file: <code>{file}</code></p>
</header>

<section>
  <h2>Data sources</h2>
  <table>
    <thead><tr><th>Source key</th><th>Category</th><th>Provider</th><th>Accessed via</th></tr></thead>
    <tbody>{sources_table}</tbody>
  </table>
</section>

<section>
  <h2>Models</h2>
  {models_block}
</section>

<section>
  <h2>Ensemble integration</h2>
  {ensemble_block}
</section>

<section>
  <h2>Recent performance — post-2026-05-17 window (~4 days)</h2>
  {perf_block}
</section>

<section>
  <h2>Outputs</h2>
  <p>{outputs}</p>
</section>

<section>
  <h2>Notes</h2>
  <p>{notes}</p>
</section>
</body></html>
"""

# ── Per-agent files ──────────────────────────────────────────────────────────
for name, a in AGENTS.items():
    out = AGENT_TEMPLATE.format(
        name=name,
        desc=html.escape(a["desc"]),
        file=html.escape(a["file"]),
        sources_table=render_sources_table(a["sources"]),
        models_block=render_models_table(a["models"]),
        ensemble_block=render_ensemble(a["ensemble"]),
        perf_block=render_perf(a["perf"]),
        outputs=html.escape(a["outputs"]),
        notes=html.escape(a["notes"]),
    )
    (OUT / f"{name}.html").write_text(out, encoding="utf-8")

# ── Comparison page ──────────────────────────────────────────────────────────
# Build matrix: rows = source keys, columns = agents, cells = ✓ or blank
all_sources = sorted(SOURCES.keys(), key=lambda s: (list(CATEGORY_LABELS).index(SOURCES[s][1]), s))
agent_names = list(AGENTS.keys())

def matrix_cell(src: str, agent: str) -> str:
    if src in AGENTS[agent]["sources"]:
        return '<td class="hit">✓</td>'
    return '<td class="miss"></td>'

matrix_rows = []
for src in all_sources:
    provider, cat = SOURCES[src]
    cells = "".join(matrix_cell(src, a) for a in agent_names)
    matrix_rows.append(
        f'<tr><td class="src">{html.escape(src)}<br><span class="muted">{html.escape(provider)}</span></td>'
        f'<td>{cat_chip(cat)}</td>'
        f'{cells}</tr>'
    )

# Common / unique analysis
src_to_agents = {s: [a for a in agent_names if s in AGENTS[a]["sources"]] for s in all_sources}
common_all = [s for s, ags in src_to_agents.items() if len(ags) == len(agent_names)]
unique = {s: ags[0] for s, ags in src_to_agents.items() if len(ags) == 1}
shared = {s: ags for s, ags in src_to_agents.items() if 1 < len(ags) < len(agent_names)}

# Ensemble weight summary
ensemble_rows = []
for name in agent_names:
    e = AGENTS[name]["ensemble"]
    if e.get("in"):
        ensemble_rows.append(
            f'<tr><td><a href="{name}.html">{name}</a></td>'
            f'<td><b>{e["base"]}</b></td>'
            f'<td>{e["trending"]}</td><td>{e["ranging"]}</td><td>{e["volatile"]}</td>'
            f'<td>{html.escape(AGENTS[name]["perf"]["roi"])}</td>'
            f'<td>{html.escape(AGENTS[name]["perf"]["realized"])}</td></tr>'
        )
    else:
        ensemble_rows.append(
            f'<tr class="non-ensemble"><td><a href="{name}.html">{name}</a></td>'
            f'<td colspan="4">{html.escape(e.get("note", "Not in ensemble"))}</td>'
            f'<td>{html.escape(AGENTS[name]["perf"]["roi"])}</td>'
            f'<td>{html.escape(AGENTS[name]["perf"]["realized"])}</td></tr>'
        )

SUMMARY = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Agent map — comparison</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<header>
  <h1>All agents — what's shared, what's unique</h1>
  <p class="meta">trading_app · post-2026-05-17 window · click any agent name for its full source/model map</p>
</header>

<section>
  <h2>Source × agent matrix</h2>
  <p class="muted">Row = data source. Column = agent. ✓ = agent consumes that source directly.</p>
  <table class="matrix">
    <thead><tr><th>Source</th><th>Category</th>{agent_headers}</tr></thead>
    <tbody>{matrix_body}</tbody>
  </table>
</section>

<section>
  <h2>Common to <em>every</em> agent</h2>
  {common_block}
</section>

<section>
  <h2>Unique to one agent</h2>
  {unique_block}
</section>

<section>
  <h2>Shared by a subset</h2>
  {shared_block}
</section>

<section>
  <h2>Ensemble weighting + window performance</h2>
  <table>
    <thead><tr><th>Agent</th><th>Base</th><th>Trending ×</th><th>Ranging ×</th><th>Volatile ×</th><th>Window ROI</th><th>Realized</th></tr></thead>
    <tbody>{ensemble_body}</tbody>
  </table>
</section>

<section>
  <h2>Key observations</h2>
  <ul>
    <li><b>HistoricalTrendsAgent has the lowest base ensemble weight (0.08) but the best window performance (+3.97% / +$5,449).</b> Base weights are nearly inverted from realized performance.</li>
    <li><b>TechAgent has the highest base weight (0.23) but is near-flat</b> (+0.91% / −$41).</li>
    <li><b>Only XGBReasoningAgent consumes the 38-channel signal pool.</b> Every other agent reads price/bars + optionally news directly — they bypass the model entirely.</li>
    <li><b>The LLM cohort (Claude / Sentiment / Ollama) all share the same upstream pipeline:</b> price + alpaca_news + yahoo_news + technicals_fmt. The differentiator is which LLM endpoint they hit.</li>
    <li><b>Three agents are effectively inactive this window:</b> GeminiAgent (0 trades, not in ensemble), OllamaAgent (0), EnsembleAgent (0 — failing 0.60 conviction threshold).</li>
    <li><b>HistoricalTrendsAgent is the only consumer of the calendar source.</b> Its hist_seasonal sub-score has +0.20 IC in the newest fold — strongest current-regime signal in the audit.</li>
  </ul>
</section>
</body></html>
"""

agent_headers = "".join(f'<th><a href="{n}.html">{n}</a></th>' for n in agent_names)

def lst(items):
    return '<ul>' + ''.join(f'<li><code>{html.escape(i)}</code></li>' for i in items) + '</ul>' if items else '<p class="muted">(none)</p>'

common_block = lst(common_all) if common_all else '<p class="muted">No source is consumed by literally every agent. Closest universals: <code>portfolio</code> (every agent), <code>price</code> (every agent except EnsembleAgent uses it directly).</p>'

unique_block = '<table><thead><tr><th>Source</th><th>Only used by</th></tr></thead><tbody>'
for s, a in sorted(unique.items()):
    provider, cat = SOURCES[s]
    unique_block += f'<tr><td>{html.escape(s)} <span class="muted">({html.escape(provider)})</span></td><td><a href="{a}.html">{a}</a></td></tr>'
unique_block += '</tbody></table>'

shared_block = '<table><thead><tr><th>Source</th><th>Shared by</th></tr></thead><tbody>'
for s in sorted(shared, key=lambda x: (-len(shared[x]), x)):
    provider, cat = SOURCES[s]
    ags = shared[s]
    links = ', '.join(f'<a href="{a}.html">{a}</a>' for a in ags)
    shared_block += f'<tr><td>{html.escape(s)} <span class="muted">({html.escape(provider)})</span></td><td>{links} <span class="muted">({len(ags)})</span></td></tr>'
shared_block += '</tbody></table>'

(OUT / "_summary.html").write_text(
    SUMMARY.format(
        agent_headers=agent_headers,
        matrix_body="\n".join(matrix_rows),
        common_block=common_block,
        unique_block=unique_block,
        shared_block=shared_block,
        ensemble_body="\n".join(ensemble_rows),
    ),
    encoding="utf-8",
)

# ── Shared CSS ───────────────────────────────────────────────────────────────
CSS = """
:root {
  --bg: #fafbfc;
  --panel: #ffffff;
  --ink: #1f2328;
  --muted: #57606a;
  --border: #d1d9e0;
  --hit: #1f883d;
  --miss: #f6f8fa;
  --chip-market: #0969da;
  --chip-news:   #bf3989;
  --chip-fund:   #6f42c1;
  --chip-macro:  #cf222e;
  --chip-calendar: #9a6700;
  --chip-llm:    #8250df;
  --chip-derived:#57606a;
  --chip-internal:#1f883d;
}
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  background: var(--bg); color: var(--ink); margin: 0; padding: 24px 32px;
  line-height: 1.5;
}
header { border-bottom: 1px solid var(--border); padding-bottom: 12px; margin-bottom: 24px; }
header h1 { margin: 4px 0; font-size: 28px; }
.meta { color: var(--muted); margin: 4px 0; font-size: 14px; }
.back { font-size: 13px; }
.back a { color: var(--muted); text-decoration: none; }
.back a:hover { color: var(--chip-market); text-decoration: underline; }
section { background: var(--panel); border: 1px solid var(--border); border-radius: 6px; padding: 16px 20px; margin-bottom: 16px; }
section h2 { margin-top: 0; font-size: 18px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); vertical-align: top; }
th { background: var(--miss); font-weight: 600; }
code { background: var(--miss); padding: 1px 6px; border-radius: 3px; font-family: ui-monospace, "Cascadia Code", Menlo, monospace; font-size: 12.5px; }
.muted { color: var(--muted); font-size: 13px; }
.chip {
  display: inline-block; padding: 1px 8px; border-radius: 10px;
  font-size: 11px; font-weight: 600; color: white; white-space: nowrap;
}
.chip-market { background: var(--chip-market); }
.chip-news   { background: var(--chip-news);   }
.chip-fund   { background: var(--chip-fund);   }
.chip-macro  { background: var(--chip-macro);  }
.chip-calendar { background: var(--chip-calendar); }
.chip-llm    { background: var(--chip-llm);    }
.chip-derived{ background: var(--chip-derived);}
.chip-internal{background: var(--chip-internal);}

.matrix th, .matrix td { text-align: center; padding: 6px 8px; font-size: 12.5px; }
.matrix th:first-child, .matrix td.src { text-align: left; }
.matrix td.hit  { background: #d4f0dd; color: var(--hit); font-weight: 700; }
.matrix td.miss { color: #d1d9e0; }
.matrix th a { color: inherit; text-decoration: none; writing-mode: vertical-rl; transform: rotate(180deg); }

tr.non-ensemble td { color: var(--muted); font-style: italic; }
a { color: var(--chip-market); }
ul { padding-left: 24px; margin: 8px 0; }
li { margin: 2px 0; }
"""
(OUT / "style.css").write_text(CSS, encoding="utf-8")

# ── Report ──────────────────────────────────────────────────────────────────
files = sorted(OUT.glob("*"))
print(f"wrote {len(files)} files in {OUT}:")
for f in files:
    print(f"  {f.name}")
