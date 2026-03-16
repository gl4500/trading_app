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
│   │   ├── claude_agent.py             # Claude Opus 4.6 with adaptive thinking
│   │   ├── gemini_agent.py             # Google Gemini 2.0 Flash market analysis
│   │   ├── tech_agent.py               # RSI / MACD / Bollinger Bands technical agent
│   │   ├── momentum_agent.py           # Price momentum / trailing stop agent
│   │   ├── mean_reversion_agent.py     # Z-score mean reversion agent
│   │   ├── sentiment_agent.py          # OpenAI GPT-4o-mini sentiment agent
│   │   ├── ensemble_agent.py           # Adaptive performance-weighted voting
│   │   ├── scanner_agent.py            # Agentic Claude scanner — discovers opportunities
│   │   ├── scanner_portfolio_agent.py  # Executes on cached scanner picks
│   │   └── summary_agent.py            # Daily roll-up narrative via Claude
│   ├── trading/
│   │   ├── alpaca_client.py  # Alpaca Markets async wrapper
│   │   ├── portfolio.py      # Position tracking, P&L, metrics
│   │   └── risk_manager.py   # Daily loss limits, position size checks
│   └── data/
│       ├── market_data.py          # Central market context builder
│       ├── news_service.py         # Alpaca News API — 90s cache, semaphore-limited
│       ├── sentinel_sources.py     # Multi-source sentinel: RSS, EDGAR, Yahoo, Finnhub, Unusual Whales
│       ├── policy_monitor.py       # Congressional & executive order catalyst scorer
│       ├── technicals.py           # RSI/MACD/BB/ATR/SMA calculator
│       ├── signal_aggregator.py    # Multi-source composite signal
│       ├── congressional_trading.py # SEC EDGAR Form 4 signals
│       ├── stock_universe.py       # ~160 curated S&P 500 stocks across 10 sectors
│       ├── drift_detector.py       # Performance drift detection
│       ├── learning_manager.py     # Persistent trade learning (learning.json)
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
│       └── SummaryPanel.tsx    # Daily roll-up narrative
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
| **ClaudeAgent** | Deep market analysis with adaptive thinking | Claude Opus 4.6 | 25% |
| **GeminiAgent** | Fast, broad market analysis | Gemini 2.0 Flash | 20% |
| **TechAgent** | RSI, MACD, Bollinger Bands, volume | Rule-based | 20% |
| **SentimentAgent** | News sentiment scoring | GPT-4o-mini | 15% |
| **MomentumAgent** | Short/mid/long momentum + trailing stop | Rule-based | 12% |
| **MeanReversionAgent** | Z-score deviation from 20-day mean | Rule-based | 8% |
| **ScannerPortfolioAgent** | Executes on cached agentic scanner picks | Rule-based | — |
| **EnsembleAgent** | Adaptive performance-weighted voting + regime detection | Combines all | — |

**EnsembleAgent** weights shift automatically based on each agent's recent Sharpe ratio and win rate. Market regime (Trending / Ranging / Volatile) is detected every 5 cycles using SMA-20 slope + ATR.

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

Both ClaudeAgent and GeminiAgent receive per symbol each cycle:

- **Multi-source composite signal** — weighted validity score + verdict + confidence %
- **Technical indicators** — RSI, MACD, BB position, SMA trend, ATR, volume ratio
- **Alpaca news** — top 5 headlines + summaries (last 24h)
- **OHLCV data** — last 15 daily bars
- **Overnight catalysts** — all sentinel-detected events injected at market open
- **Portfolio state** — current cash, positions, cost basis
- **Past trade learnings** — top profitable/loss patterns (ClaudeAgent only)

**Signal Correlation Framework:**
- **STRONG BUY**: Bullish composite + RSI < 65 + MACD positive + price > SMA20
- **STRONG SELL**: Bearish composite + RSI > 65 + MACD negative + price < SMA20
- **CONFLICTED**: Sources disagree → reduced position size

---

## Dashboard Tabs

| Tab | Description |
|---|---|
| **Portfolio Chart** | Value history for all agents over time |
| **Agent Detail** | Full breakdown of selected agent — positions, signals, trades |
| **Signals ✦** | Multi-source composite signal board (analyst, earnings, news, congress) |
| **⟁ Scanner** | Agentic Claude scanner recommendations with confidence and catalysts |
| **◈ Daily Roll-Up** | Claude-authored narrative summary of all agent decisions |
| **⚡ Sentinel** | Overnight catalyst feed grouped by category + news→price impact tracker |

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
- **Dashboard:** http://localhost:5173
- **Backend API:** http://localhost:8000
- **API Docs:** http://localhost:8000/docs

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
| `.env` | API keys, watchlist, trading parameters |
| `backend/config.py` | Add config variables, adjust ensemble weights |
| `backend/agents/claude_agent.py` | Claude's prompt or decision logic |
| `backend/agents/gemini_agent.py` | Gemini's prompt or model settings |
| `backend/data/sentinel_sources.py` | Add/remove sentinel data sources |
| `backend/data/policy_monitor.py` | Keyword tables, sector mappings |
| `backend/data/signal_aggregator.py` | Signal source weights |
| `backend/agents/scanner_agent.py` | Scanner tool definitions, cache TTL |
| `backend/data/stock_universe.py` | Scanner symbol universe |
| `backend/data/news_service.py` | News cache TTL, lookback window |

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for full history.

| Date | Change |
|---|---|
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
