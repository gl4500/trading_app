# AI Trading Competition

A multi-agent paper trading system where AI agents compete to maximize returns using real-time market data, technical indicators, news, and AI-powered analysis.

---

## Architecture Overview

```
trading_app/
├── backend/                  # FastAPI Python backend
│   ├── main.py               # App entry point, REST API, WebSocket, trading loop
│   ├── config.py             # Environment variable loading (.env)
│   ├── database.py           # SQLite persistence (trades, performance, agents)
│   ├── requirements.txt      # Python dependencies
│   ├── agents/               # Trading agents
│   │   ├── base_agent.py               # Abstract base: portfolio, risk, picks persistence
│   │   ├── claude_agent.py             # Claude Opus 4.6 / Ollama (Tier 2 swap) with adaptive thinking
│   │   ├── gemini_agent.py             # Gemini 2.0 Flash / Ollama (Tier 2 swap) — market view context provider
│   │   ├── tech_agent.py               # RSI / MACD / Bollinger Bands technical agent
│   │   ├── momentum_agent.py           # Price momentum / trailing stop agent
│   │   ├── mean_reversion_agent.py     # Z-score mean reversion agent
│   │   ├── sentiment_agent.py          # GPT-4o-mini / Ollama sentiment agent (time-throttled)
│   │   ├── ensemble_agent.py           # Adaptive performance-weighted voting + regime detection
│   │   ├── scanner_agent.py            # Agentic Claude scanner — discovers opportunities
│   │   ├── scanner_portfolio_agent.py  # Executes on cached scanner picks
│   │   ├── historical_trends_agent.py  # Seasonal patterns, channel, multi-period momentum
│   │   ├── cnn_reasoning_agent.py      # CNN-based pattern recognition + Ollama reasoning
│   │   └── summary_agent.py            # Daily roll-up narrative via Claude
│   ├── trading/
│   │   ├── alpaca_client.py  # Alpaca Markets async wrapper
│   │   ├── portfolio.py      # Position tracking, P&L, metrics, churn cooloff tracking
│   │   └── risk_manager.py   # Daily loss limits, position size, churn & sector concentration
│   └── data/
│       ├── market_data.py          # Central market context builder
│       ├── news_service.py         # Alpaca News API — 90s cache, semaphore-limited
│       ├── sentinel_sources.py     # Multi-source sentinel: RSS, EDGAR, Yahoo, Finnhub, Unusual Whales
│       ├── policy_monitor.py       # Congressional & executive order catalyst scorer
│       ├── technicals.py           # RSI/MACD/BB/ATR/SMA/Stochastic/OBV calculator
│       ├── signal_aggregator.py    # Multi-source composite signal
│       ├── congressional_trading.py # SEC EDGAR Form 4 signals
│       ├── stock_universe.py       # ~160 curated S&P 500 stocks across 10 sectors
│       ├── drift_detector.py       # Performance drift detection
│       ├── learning_manager.py     # Persistent trade learning (learning.json)
│       ├── risk_assessor.py        # Churn / regime / sector assessments → AI prompt injection
│       ├── stooq_client.py         # Free 5-year historical OHLCV from stooq.com (no key needed)
│       ├── agent_picks.json        # Per-agent conviction picks (auto-managed)
│       └── scan_cache.json         # Scanner results cache (auto-managed)
├── frontend/                 # React + Vite + Tailwind dashboard
│   └── src/components/
│       ├── Dashboard.tsx       # Main layout, tab controller
│       ├── Leaderboard.tsx     # Agent ranking strip
│       ├── AgentCard.tsx       # Per-agent detail view
│       ├── PortfolioChart.tsx  # Value history chart
│       ├── TradeLog.tsx        # Real-time trade feed
│       ├── MarketOverview.tsx  # Price ticker bar
│       ├── SignalsPanel.tsx    # Multi-source composite signals
│       ├── ScannerPanel.tsx    # Agentic scanner results
│       ├── SentinelPanel.tsx   # Overnight catalyst feed + news→price impact
│       ├── SummaryPanel.tsx    # Daily roll-up narrative
│       └── TokensPanel.tsx     # Live token usage stats + 24h searchable log
├── runtime/                  # Self-contained Python + Node runtimes
├── site-packages/            # All installed Python packages
├── .env                      # API keys (never commit)
├── .env.example              # Template for .env
├── Start Trading App.exe     # Double-click launcher
├── start_backend.ps1 / .bat  # Start backend only
├── start_frontend.ps1 / .bat # Start frontend only
├── setup_offline.ps1 / .bat  # Install all deps without internet
└── README.md                 # This file
```

---

## Agents

| Agent | Strategy | AI Model | Ensemble Weight |
|---|---|---|---|
| **ClaudeAgent** | Deep market analysis with adaptive thinking | Claude Opus 4.6 (or Ollama in `OLLAMA_ONLY_MODE`) | 29% |
| **TechAgent** | RSI, MACD, Bollinger Bands, Stochastic, OBV, volume | Rule-based | 23% |
| **SentimentAgent** | Price action + news sentiment | GPT-4o-mini (or Ollama in `OLLAMA_ONLY_MODE`) | 17% |
| **MomentumAgent** | Short/mid/long momentum + trailing stop | Rule-based | 14% |
| **MeanReversionAgent** | Z-score deviation from 20-day mean | Rule-based | 9% |
| **HistoricalTrendsAgent** | Seasonal calendar patterns, channel positioning, multi-period momentum | Rule-based | 8% |
| **ScannerPortfolioAgent** | Executes on cached agentic scanner picks | Rule-based | — |
| **CNNReasoningAgent** | CNN price-pattern recognition + local Ollama reasoning | Ollama (llama3.1:8b) | — |
| **EnsembleAgent** | Adaptive performance-weighted voting + regime detection | Combines all | — |
| **GeminiAgent** | Market-view context provider (not an ensemble voter) | Gemini 2.0 Flash (or Ollama in `OLLAMA_ONLY_MODE`) | — |

**EnsembleAgent** weights shift automatically based on each agent's recent Sharpe ratio and win rate. Market regime (Trending / Ranging / Volatile) is detected every 5 cycles using a **2-of-3 signal requirement**: SMA-20 slope + trend consistency (% positive days) + volume expansion. All three must align for a TRENDING call — single-signal false positives are suppressed.

**GeminiAgent** runs alongside Claude as a second AI perspective. It does not vote in the ensemble — instead it contributes a `market_analysis` string (2-3 sentence market overview) that is injected into Claude's prompt under `## Gemini Market View` before Claude makes its own decisions.

**CNNReasoningAgent** uses a convolutional neural network to identify price patterns in OHLCV data, then routes its reasoning through a local Ollama model. It runs independently of the cloud AI agents — useful when operating fully offline or in `OLLAMA_ONLY_MODE`.

**Ollama / Zero-cost mode:** Set `OLLAMA_ONLY_MODE=1` in `.env` to route ClaudeAgent, GeminiAgent, and SentimentAgent through local Ollama inference instead of cloud APIs. No Anthropic, OpenAI, or Gemini API calls are made — zero token cost. See Environment Variables for the required Ollama config vars.

**HistoricalTrendsAgent** is a pure rule-based agent with three analytical pillars: (1) **seasonal bias** — month-of-year and quarter-position effects based on long-run S&P 500 seasonality research; (2) **channel analysis** — where the current price sits in its historical high-low range, SMA-slope adjusted; (3) **multi-period momentum** — trend persistence across 5/10/20/40-day windows with an alignment bonus when all timeframes agree. It uses up to 5 years of free daily OHLCV data from Stooq.com, falling back to Alpaca bars when Stooq is unavailable. Regime multipliers: boosted in trending (×1.20) and ranging (×1.30) regimes, reduced in volatile markets (×0.80).

**Agent picks persistence** — each agent retains its own high-conviction BUY symbols across cycles and restarts (`data/agent_picks.json`). When a pick symbol falls outside the analysis window, stored conviction is replayed instead of defaulting to HOLD.

---

## Trading Schedule

| Session | Hours (ET) | Behavior |
|---|---|---|
| **Market open** | 9:30 AM – 4:00 PM | Trading loop runs every 60s, scanner every 30 min |
| **Pre-open warmup** | 9:20 AM | Scanner fires a warmup run before the bell |
| **Market closed** | All other times | Trading loop sleeps; sentinel polls news every 15 min |

**Force-trading mode** (`POST /api/force-trading?enabled=true`) bypasses the market hours gate for testing. Market status shows `open (test)` when active.

---

## Overnight Sentinel

A background loop that monitors news 24/7, polling more frequently during market hours (every 5 min) and every 15 min overnight.

### Data Sources

| Source | What it provides | API Key |
|---|---|---|
| **Alpaca News API** | Company headlines for all watchlist symbols | existing |
| **CNBC + Reuters RSS** | Breaking market/business news | free |
| **Yahoo Finance RSS** | Per-symbol headline feeds | free |
| **yfinance news** | Richer per-symbol article coverage | free |
| **SEC EDGAR 8-K** | Material event disclosures (earnings, M&A, bankruptcies) | free |
| **Finnhub** | Company + general market news | `FINNHUB_API_KEY` |
| **Unusual Whales** | Congressional trades + unusual options flow alerts | `UNUSUAL_WHALES_API_KEY` |
| **Policy Monitor** | Congressional laws, executive orders, Fed decisions, tariffs | free (keyword scoring) |

### Catalyst Categories

- `POLICY` — executive orders, legislation signed into law, vetos
- `MACRO` — Fed rate decisions, inflation reports, jobs reports, GDP
- `GEOPOLITICAL` — sanctions, conflicts, NATO, OPEC
- `REGULATORY` — SEC charges, DOJ investigations, FTC rulings, antitrust
- `CATALYST` — earnings beat/miss, M&A, CEO changes, analyst upgrades/downgrades, FDA

### News → Price Correlation

When a catalyst is detected, the sentinel records the last known price. As trading runs, it tracks:
- **At-open change** — price move at first trading cycle after detection
- **Sustained change** — ongoing price tracking through the session

Viewable in the **⚡ Sentinel** tab → **News → Price Impact** view.

---

## AI Agent Decision Context

ClaudeAgent receives per symbol each cycle:

- **Multi-source composite signal** — weighted validity score + verdict + confidence %
- **Technical indicators** — RSI, MACD, BB position, SMA trend, ATR, Stochastic %K/%D, OBV trend, volume ratio
- **Alpaca news** — top 5 headlines + summaries (last 24h)
- **OHLCV data** — last 15 daily bars
- **Overnight catalysts** — all sentinel-detected events injected at market open
- **Portfolio state** — current cash, positions, cost basis
- **Past trade learnings** — top profitable/loss patterns
- **Gemini market view** — Gemini's 2-3 sentence overall market assessment
- **Risk assessor findings** — churn alerts, false regime warnings, sector overweight flags (every 30 cycles)

**Signal Correlation Framework:**
- **STRONG BUY**: Bullish composite + RSI < 65 + MACD positive + price > SMA20
- **STRONG SELL**: Bearish composite + RSI > 65 + MACD negative + price < SMA20
- **CONFLICTED**: Sources disagree → reduced position size

---

## Decision Architecture

### How signals flow — bottom to top

```
Sentinel (24/7 news feed)
    ↓  catalysts injected into market_context at each cycle
Individual Agents  (each runs independently, in parallel)
    ↓  each returns BUY / SELL / HOLD signals with confidence scores
EnsembleAgent  (the coordinator — votes, weights, and executes)
    ↓  issues final trades
```

### What each agent sees

Every agent receives the same `market_context` dict each cycle:

| Data | Agents that use it |
|---|---|
| Price + OHLCV bars (30 days) | All |
| RSI, MACD, Bollinger Bands, SMA, ATR, Stochastic, OBV | All |
| Multi-source composite signal | ClaudeAgent, GeminiAgent, SentimentAgent |
| Alpaca news headlines (last 24h) | ClaudeAgent, GeminiAgent, SentimentAgent |
| **Overnight sentinel catalysts** | ClaudeAgent, GeminiAgent |
| Past trade learnings | ClaudeAgent only |
| Portfolio state (cash, positions) | All |

The three rule-based agents (TechAgent, MomentumAgent, MeanReversionAgent) are **pure technical/statistical** — they do not read news or sentinel data.

### EnsembleAgent — the overarching coordinator

The EnsembleAgent is the final decision-maker. It does not trade on its own analysis — it **aggregates all agent signals** and applies three layers of weighting before acting:

**1. Base weights** (from `config.py`)

| Agent | Base Weight |
|---|---|
| ClaudeAgent | 29% |
| TechAgent | 23% |
| SentimentAgent | 17% |
| MomentumAgent | 14% |
| MeanReversionAgent | 9% |
| HistoricalTrendsAgent | 8% |

**2. Adaptive performance adjustment** — every 5 cycles, each agent's weight is scaled by its recent Sharpe ratio and win rate. Underperforming agents are reduced (minimum 30% of base weight preserved). Outperforming agents gain more influence automatically.

**3. Regime multipliers** — market regime is detected using a 2-of-3 signal requirement (SMA-20 slope, trend consistency, volume expansion). Single-signal false TRENDING calls are suppressed:

| Regime | Who gets boosted | Who gets reduced |
|---|---|---|
| **Trending** | MomentumAgent (1.5×), TechAgent (1.2×), HistoricalTrendsAgent (1.2×) | MeanReversionAgent (0.4×) |
| **Ranging** | MeanReversionAgent (1.6×), HistoricalTrendsAgent (1.3×), SentimentAgent (1.2×) | MomentumAgent (0.55×) |
| **Volatile** | ClaudeAgent (1.4×), SentimentAgent (1.2×) | TechAgent (0.8×), MomentumAgent (0.65×), HistoricalTrendsAgent (0.8×) |

**Consensus threshold:** 35% weighted agreement required to execute a BUY or SELL. If no combination of agents clears that bar, the Ensemble HOLDs. Trade reasoning records which agents voted and the regime, e.g.:

> `ENSEMBLE BUY [VOLATILE]: 42% consensus | Agents: ClaudeAgent, GeminiAgent | CLAUDE ANALYSIS: ...`

### News & sentinel correlation

In volatile or news-driven markets, Claude and Gemini receive the most weight (via the volatile regime multiplier). Their prompts include a dedicated **Overnight / After-Hours Catalysts** section sourced from the sentinel, alongside the per-symbol Alpaca news feed. Claude is instructed to use news for direction and technicals for timing — and to flag conflicts rather than blindly follow either signal.

In calm trending markets, momentum and technical signals can outvote the AI agents even when Claude identifies a news catalyst, because the regime multipliers shift weight to TechAgent and MomentumAgent.

---

## Dashboard Tabs

| Tab | Description |
|---|---|
| **Portfolio Chart** | Value history for all agents + recent trades with date and time |
| **Agent Detail** | Full breakdown of selected agent — positions, signals, trades |
| **Signals ✦** | Multi-source composite signal board (analyst, earnings, news, congress) |
| **⟁ Scanner** | Agentic Claude scanner recommendations with confidence and catalysts |
| **◈ Daily Roll-Up** | Claude-authored narrative summary of all agent decisions |
| **⚡ Sentinel** | Overnight catalyst feed grouped by category + news→price impact tracker |
| **🔢 Tokens** | Live token usage per agent (daily total, calls/hr) + searchable 24h log with limit-hit alerts |
| **📊 Telemetry** | System resource monitor: CPU, RAM, disk, GPU utilisation + VRAM + temperature (NVIDIA only) |

---

## Agentic Stock Scanner

Discovers high-conviction opportunities outside the core watchlist.

**Schedule:** startup warmup → every 30 min during market hours → 10 min pre-open warmup → sleeps overnight

**Process:**
1. Pre-screens ~160 universe stocks for momentum (price change, volume ratio)
2. Deep-dives top candidates with Claude (tool-use agentic loop)
3. Returns ranked BUY/SELL/WATCH recommendations with confidence, reasoning, catalysts, price targets
4. Scanner symbols injected into every agent's market context

---

## Daily Roll-Up Summary

`DailySummaryService` (`agents/summary_agent.py`) aggregates all agent decisions and generates a Claude-authored narrative covering:

1. Session overview — what agents collectively did
2. Key decisions — most significant BUY/SELL calls and agent agreement/disagreement
3. Standout agents — clearest conviction or best reasoning
4. Watchlist for tomorrow — strongest consensus + upcoming catalysts
5. Risk note — concentration risk, conflicting signals

**Cache:** 5 min during market hours, 1 hour when closed.

---

## REST API

| Endpoint | Description |
|---|---|
| `GET /api/agents` | All agents with current state |
| `GET /api/leaderboard` | Agents ranked by return % |
| `GET /api/trades` | Recent trades (optional `?agent_id=`) |
| `GET /api/market` | Current prices for watchlist |
| `GET /api/signals` | Multi-source composite signals per symbol |
| `GET /api/picks` | Per-agent retained conviction picks |
| `GET /api/scanner` | Latest cached scanner recommendations |
| `POST /api/scanner/run` | Trigger a new Claude-powered scan (rate limited) |
| `GET /api/sentinel` | Catalyst feed + market status + minutes until open |
| `GET /api/news-impact` | News→price correlation snapshots |
| `GET /api/summary` | Daily roll-up narrative (`?force=true` to regenerate) |
| `GET /api/drift` | Performance drift report per agent |
| `GET /api/performance/{agent_name}` | Full performance history |
| `GET /api/tokens` | Live token usage stats per agent + session/daily totals |
| `GET /api/token-log` | 24h token log (`?agent=`, `?hours=`, `?limit_hit=true`) |
| `GET /api/telemetry` | CPU%, RAM%, disk%, GPU utilisation/VRAM/temp (per device), Ollama status |
| `GET /api/status` | App status (running, market_status, cycle count) |
| `POST /api/start` | Start trading |
| `POST /api/stop` | Stop trading |
| `POST /api/reset` | Reset all portfolios and trade history |
| `POST /api/force-trading` | Bypass market hours gate (`?enabled=true/false`) |
| `WS /ws` | Real-time WebSocket updates (5s interval) |
| `GET /docs` | Interactive API docs (Swagger UI) |

---

## Setup & Running

### Quickstart

**Double-click `Start Trading App.exe`** — launches backend, frontend, and opens the browser.

Or manually in two terminals:

```powershell
# Terminal 1 — Backend
cd C:\Users\gl450\trading_app
.\start_backend.ps1

# Terminal 2 — Frontend
cd C:\Users\gl450\trading_app
.\start_frontend.ps1
```

> If PowerShell blocks scripts: `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

### URLs
- **Dashboard:** https://localhost:5173
- **Backend API:** https://localhost:8000
- **API Docs:** https://localhost:8000/docs

> On first visit your browser will show a self-signed cert warning. Click **Advanced → Proceed** to trust it. You only need to do this once per browser.

### Remote Access via Tailscale

The app supports remote access over [Tailscale](https://tailscale.com) with no port-forwarding or VPN config required.

**One-time setup:**
1. Install Tailscale on the Windows machine and connect it to your tailnet
2. Delete old certs if they exist: `certs\cert.pem` and `certs\key.pem`
3. Regenerate the cert (auto-detects your Tailscale IP):
   ```powershell
   cd C:\Users\gl450\trading_app
   runtime\python\python.exe gen_certs.py
   ```
4. Restart the trading app

**Access from any Tailscale-connected device:**
```
https://<your-tailscale-ip>:5173
```
The Tailscale IP is printed at the end of `gen_certs.py` output. Accept the cert warning once and it persists.

The cert is valid for 825 days. Tailscale IPs are stable — you only need to redo this if you reinstall Tailscale or the machine's Tailscale IP changes.

---

## Environment Variables (`.env`)

```ini
# Alpaca Markets (paper trading) — https://app.alpaca.markets
ALPACA_API_KEY=your_key
ALPACA_SECRET_KEY=your_secret
ALPACA_BASE_URL=https://paper-api.alpaca.markets

# Anthropic — https://console.anthropic.com
ANTHROPIC_API_KEY=your_key

# OpenAI — https://platform.openai.com/api-keys
OPENAI_API_KEY=your_key

# Google Gemini — https://aistudio.google.com/app/apikey
GEMINI_API_KEY=your_key

# Additional data sources (optional — sentinel works without these)
FINNHUB_API_KEY=your_key        # https://finnhub.io
UNUSUAL_WHALES_API_KEY=your_key # https://unusualwhales.com

# Ollama local inference (zero API cost)
# Install Ollama: https://ollama.com  →  ollama pull llama3.1:8b
OLLAMA_ONLY_MODE=0              # Set to 1 to route ALL AI agents through local Ollama (no cloud calls)
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=llama3.1:8b        # Model for SentimentAgent, GeminiAgent, CNNReasoningAgent
RESEARCH_MODEL=llama3.1:8b      # Model for ClaudeAgent in Ollama mode (defaults to OLLAMA_MODEL)
                                # RTX 2060 (6 GB): keep as llama3.1:8b — only one Q4 model fits
                                # RTX 3080+ (16 GB+): upgrade to deepseek-r1:14b for richer reasoning

# Trading parameters
STARTING_CAPITAL=100000
MAX_POSITION_SIZE=0.15
TRADE_INTERVAL_SECONDS=60
DAILY_LOSS_LIMIT=0.05

# Watchlist (comma-separated)
WATCHLIST=AAPL,MSFT,GOOGL,TSLA,AMZN,NVDA,META,SPY
```

---

## Key Files to Edit

| File | What to change |
|---|---|
| `.env` | API keys, watchlist, trading parameters, `OLLAMA_ONLY_MODE` |
| `backend/config.py` | Add config variables, adjust ensemble weights, `RESEARCH_MODEL` |
| `backend/agents/claude_agent.py` | Claude's prompt, decision logic, or Ollama model routing |
| `backend/agents/gemini_agent.py` | Gemini's prompt, model settings, or Ollama routing |
| `backend/agents/sentiment_agent.py` | Sentiment scoring, Ollama vs GPT-4o-mini routing |
| `backend/agents/cnn_reasoning_agent.py` | CNN architecture, pattern features, reasoning prompt |
| `backend/data/sentinel_sources.py` | Add/remove sentinel data sources |
| `backend/data/policy_monitor.py` | Keyword tables, sector mappings |
| `backend/data/signal_aggregator.py` | Signal source weights |
| `backend/agents/scanner_agent.py` | Scanner tool definitions, cache TTL |
| `backend/data/stock_universe.py` | Scanner symbol universe |
| `backend/data/news_service.py` | News cache TTL, lookback window |

---

## Agent Formulas Reference

See [`agent_formulas.txt`](agent_formulas.txt) for a complete printout of every buy/sell formula, scoring weight, threshold, and position-sizing calculation used by each agent.

See [`decision_tree.txt`](decision_tree.txt) for a full ASCII diagram of how data flows from market sources through each agent layer to final trade execution.

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for full history.

| Date | Change |
|---|---|
| 2026-04-05 | **GPU telemetry** — `nvidia-smi` subprocess in `/api/telemetry`; GPU utilisation, VRAM, and temperature displayed in 📊 Telemetry dashboard tab; multi-GPU support; graceful "no GPU" state |
| 2026-04-05 | **CNNReasoningAgent halt fix** — `get_position()` method does not exist on `Portfolio`; fixed to `portfolio.positions[sym].shares`; was causing `AttributeError` every SELL cycle → 5-error halt |
| 2026-04-05 | **Tier 2 Ollama swap** — `OLLAMA_ONLY_MODE=1` routes ClaudeAgent, GeminiAgent, and SentimentAgent through local Ollama; `RESEARCH_MODEL` config var selects model for ClaudeAgent (defaults to `OLLAMA_MODEL` to share single loaded model — critical for RTX 2060 6 GB VRAM); cycle-throttle and cache-replay logic preserved on Ollama path |
| 2026-04-05 | **SentimentAgent Ollama fix** — hardcoded `model="gpt-4o-mini"` and OpenAI key guard now bypassed in Ollama mode; token logging skipped (zero cost) |
| 2026-03-31 | **Stochastic + OBV indicators** — added Stochastic %K/%D (14/3) and On-Balance Volume to `data/technicals.py` and `TechAgent`; Stochastic scores entry timing (oversold/overbought zones + %K crossover); OBV detects confirmation vs divergence (distribution/accumulation); both injected into AI agent prompts via `format_for_prompt()` |
| 2026-03-31 | **Tailscale remote access** — `gen_certs.py` now auto-detects Tailscale IP (`tailscale ip -4`) and includes it in the cert's SANs; Vite updated to bind on `0.0.0.0` and serve HTTPS; access dashboard remotely at `https://<tailscale-ip>:5173` |
| 2026-03-31 | **HTTPS on frontend** — Vite now serves HTTPS (was plain HTTP); use `https://localhost:5173` |
| 2026-03-29 | **HistoricalTrendsAgent** — replaced OpenClawAgent with a pure rule-based seasonal/channel/momentum agent; added free 5-year Stooq historical data (`data/stooq_client.py`); Stooq added as bar fallback in `market_data.py`; ensemble weights rebalanced |
| 2026-03-21 | **Decision flow diagram** — added `decision_tree.txt` with full ASCII diagram showing all 7 layers from data sources through ensemble voting to trade execution |
| 2026-03-21 | **Agent formulas reference** — added `agent_formulas.txt` documenting every buy/sell formula, scoring weight, threshold, and position-sizing calculation for all agents |
| 2026-03-20 | **Trade date display** — recent trades in Portfolio Chart tab now show date (e.g. "20 Mar") above the time |
| 2026-03-20 | **SentimentAgent token throttling** — switched from cycle-based to time-based throttling (90 min market / 4 h off-hours); caps each batch to 5 symbols (held positions first); spreads 10,000-token daily budget evenly across 24 h |
| 2026-03-19 | **Risk assessor learning loop** — new `data/risk_assessor.py` persists trade/regime logs; detects churn, false TRENDING calls, sector overweight; injects findings into Claude and Gemini prompts every 30 cycles |
| 2026-03-19 | **Churn prevention** — 30-minute cooloff after selling a symbol; `Portfolio._recent_exits` tracks last sell time; `RiskManager.check_buy_allowed()` enforces the gate |
| 2026-03-19 | **Sector concentration limit** — `RiskManager` blocks buys that would put any single sector above 35% of portfolio value; sector lookup via `stock_universe.get_sector()` |
| 2026-03-19 | **Multi-signal regime detection** — `EnsembleAgent._detect_regime()` now requires 2-of-3 signals (SMA slope + trend consistency + volume expansion) to call TRENDING; single-signal false positives suppressed |
| 2026-03-19 | **24h token usage log** — `token_log` SQLite table; `save_token_log()` called after every AI API call; `GET /api/token-log` REST endpoint; 🔢 Tokens dashboard tab with live stats cards, alert banner on limit events, filterable log table |
| 2026-03-19 | **GeminiAgent repurposed** — removed from ensemble voting; now runs as a market-view context provider, injecting a 2-3 sentence `market_analysis` into Claude's prompt |
| 2026-03-16 | **Multi-source sentinel** — added RSS (CNBC, Reuters), Yahoo Finance, SEC EDGAR 8-K, Finnhub, Unusual Whales (congress trades + options flow) |
| 2026-03-16 | **Sentinel tab** — new ⚡ Sentinel dashboard tab with catalyst feed grouped by category and news→price correlation tracker |
| 2026-03-16 | **Sentinel runs during market hours** — polls every 5 min intraday (was closed-only) |
| 2026-03-16 | **Overnight catalysts wired to agents** — sentinel data injected into ClaudeAgent and GeminiAgent prompts at market open |
| 2026-03-16 | **Force-trading mode** — `POST /api/force-trading` bypasses market hours gate for testing |
| 2026-03-16 | **Daily Roll-Up tab** — Claude-authored narrative summary of all agent decisions |
| 2026-03-16 | **Pre-market/after-hours removed** — trading only during regular NYSE hours (9:30–16:00 ET) |
| 2026-03-16 | **Reset fix** — reset button now correctly zeros leaderboard, agent cards, portfolio chart without removing agents |
| 2026-03-16 | **Git versioning** — trading_app now tracked in its own git repo, pushed to github.com/gl4500/trading_app |
| 2026-03-16 | **Connection pool fix** — added semaphore(8) to news service to prevent urllib3 pool overflow |
| 2026-03-16 | **WinError 10054 suppression** — filter extended to cover all asyncio/uvicorn loggers and outbound connection resets |
| 2026-03-15 | After-hours sentinel, policy monitor, market hours suspension, adaptive ensemble, scanner persistence |
| 2026-03-15 | GeminiAgent added, security hardening, self-contained runtime, agent picks persistence |
