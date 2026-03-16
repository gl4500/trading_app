# AI Trading Competition

A multi-agent paper trading system where AI agents compete to maximize returns using real-time market data, technical indicators, news, and analyst signals.

---

## Architecture Overview

```
trading_app/
├── backend/                  # FastAPI Python backend
│   ├── main.py               # App entry point, REST API, WebSocket, trading loop
│   ├── config.py             # Environment variable loading (.env)
│   ├── database.py           # SQLite persistence (trades, performance, agents)
│   ├── requirements.txt      # Python dependencies
│   ├── packages/             # Offline wheel files for all dependencies
│   ├── agents/               # Trading agents
│   │   ├── base_agent.py     # Abstract base: portfolio, risk, signal execution
│   │   ├── claude_agent.py   # Claude Opus 4.6 with adaptive thinking
│   │   ├── gemini_agent.py   # Google Gemini 2.0 Flash market analysis
│   │   ├── tech_agent.py     # RSI / MACD / Bollinger Bands technical agent
│   │   ├── momentum_agent.py # Price momentum / trailing stop agent
│   │   ├── mean_reversion_agent.py  # Z-score mean reversion agent
│   │   ├── sentiment_agent.py       # OpenAI GPT-4o-mini sentiment agent
│   │   ├── ensemble_agent.py        # Weighted voting across all agents
│   │   └── scanner_agent.py         # Agentic Claude scanner — discovers new opportunities
│   ├── trading/
│   │   ├── alpaca_client.py  # Alpaca Markets async wrapper (bars, quotes, orders)
│   │   ├── portfolio.py      # Position tracking, P&L, metrics
│   │   └── risk_manager.py   # Daily loss limits, position size checks
│   └── data/
│       ├── market_data.py    # Central market context builder (prices + bars + news + signals)
│       ├── news_service.py   # Alpaca News API — 90s cache, last 24h headlines
│       ├── technicals.py     # Shared RSI/MACD/BB/ATR/SMA calculator
│       ├── signal_aggregator.py      # Multi-source composite signal with validity weighting
│       ├── congressional_trading.py  # SEC EDGAR Form 4 congressional/insider trade signals
│       ├── stock_universe.py         # ~160 curated S&P 500 stocks across 10 sectors
│       ├── drift_detector.py         # Performance drift detection vs historical baseline
│       ├── learning_manager.py       # Persistent trade learning file (learning.json)
│       └── policy_monitor.py         # Congressional laws & executive order catalyst scorer
├── frontend/                 # React + Vite + Tailwind dashboard
│   └── src/                  # Live leaderboard, agent cards, trade feed
├── runtime/                  # Self-contained Python + Node runtimes (no external deps)
│   ├── python/               # Python 3.12 interpreter + stdlib + DLLs
│   └── node/                 # Node.js + npm
├── site-packages/            # All installed Python packages (importable directly)
├── .env                      # API keys (never commit — in .gitignore)
├── .env.example              # Template for .env (no real keys)
├── .gitignore                # Excludes .env, site-packages, runtime, db, etc.
├── Start Trading App.exe     # Double-click launcher — starts backend + frontend + browser
├── start_backend.ps1         # PowerShell: start backend only
├── start_frontend.ps1        # PowerShell: start frontend only
├── setup_offline.ps1         # PowerShell: install all deps without internet
└── README.md                 # This file
```

---

## Agents

| Agent | Strategy | AI Model | Base Ensemble Weight |
|---|---|---|---|
| **ClaudeAgent** | Deep market analysis with adaptive thinking | Claude Opus 4.6 (Anthropic) | 25% |
| **GeminiAgent** | Fast, broad market analysis | Gemini 2.0 Flash (Google) | 20% |
| **TechAgent** | RSI, MACD, Bollinger Bands, volume signals | Rule-based | 20% |
| **SentimentAgent** | News sentiment scoring | GPT-4o-mini (OpenAI) | 15% |
| **MomentumAgent** | Short/mid/long-term price momentum + trailing stop | Rule-based | 12% |
| **MeanReversionAgent** | Z-score deviation from 20-day mean | Rule-based | 8% |
| **ScannerPortfolioAgent** | Executes on cached agentic scanner picks | Rule-based | — |
| **EnsembleAgent** | Adaptive performance-weighted voting with regime detection | Combines all | — |

**EnsembleAgent is adaptive** — weights shift automatically based on each agent's recent Sharpe ratio and win rate. The market regime (Trending / Ranging / Volatile) is detected every 5 cycles using SMA-20 slope and ATR, and regime-specific multipliers are applied on top of performance weights. No agent ever drops below 30% of its base weight.

**Signal source weights:** Analyst consensus 35% · Earnings surprise 22% · Congressional trades 13% · Alpaca news 18% · Yahoo news 12%

> Note: Analyst and earnings signals are skipped for ETFs (e.g. SPY) as fundamentals data is unavailable.

---

## Data Pipeline (per trading cycle)

Each cycle fetches the following **in parallel** for every watchlist symbol:

```
1. Latest prices         ← Alpaca Markets (IEX feed)
2. OHLCV bars (60 days)  ← Alpaca Markets (IEX feed)
3. News headlines        ← Alpaca News API (last 24h, 90s cache)
4. Composite signal      ← Multi-source aggregator (15min cache):
   ├── Analyst consensus     weight=35%  ← Yahoo Finance (yfinance) [stocks only]
   ├── Earnings surprise     weight=22%  ← Yahoo Finance (yfinance) [stocks only]
   ├── Alpaca news score     weight=18%  ← keyword-scored Alpaca headlines
   ├── Yahoo Finance news    weight=12%  ← Yahoo Finance news (yfinance)
   └── Congressional trades  weight=13%  ← SEC EDGAR Form 4 (4h cache, 90d window)
5. Technical indicators  ← Computed from bars:
   ├── RSI(14)
   ├── MACD(12,26,9)
   ├── Bollinger Bands(20,2)
   ├── SMA20 / SMA50
   ├── ATR(14)
   └── Volume ratio (vs 20-day avg)
```

---

## AI Agent Decision Context

Both ClaudeAgent and GeminiAgent receive the following per symbol each analysis cycle:

- **Multi-source composite signal** — weighted validity score + verdict + confidence %
- **Technical indicators** — RSI, MACD, BB position, SMA trend, ATR, volume
- **Alpaca news** — top 5 headlines + summaries (last 24h)
- **OHLCV data** — last 15 daily bars (reduced from 30 to lower token cost)
- **Past trade learnings** — top 5 profitable patterns + top 5 loss patterns (ClaudeAgent only, `learning.json`)
- **Portfolio state** — current cash, positions, cost basis

**Signal Correlation Framework** (applied internally by both AI agents):
- **STRONG BUY**: Bullish composite + RSI not overbought (<65) + MACD positive + price > SMA20
- **STRONG SELL**: Bearish composite + RSI overbought (>65) + MACD negative + price < SMA20
- **CONFLICTED**: Sources disagree → reduced position size, flagged in reasoning

**Cost management:**
- ClaudeAgent calls the API every 5th cycle; caches decisions in between
- GeminiAgent calls the API every 10th cycle (free-tier friendly)
- Both detect new scanner symbols and force a fresh API call when new opportunities appear
- Exponential backoff (60s → 600s cap) on rate-limit / overload errors

---

## Agentic Stock Scanner

The scanner runs autonomously in the background and discovers high-conviction opportunities outside the core watchlist.

**Schedule:**
- Fires once at startup if no fresh cache exists
- Repeats every 30 minutes during market hours
- Pre-market warm-up: runs 10 minutes before the opening bell
- Suspends between sessions — wakes 5 min before next open
- Results persist to `backend/data/scan_cache.json` and survive restarts

**Process:**
1. Pre-screens ~160 universe stocks for momentum (price change, volume ratio)
2. Deep-dives the top candidates with Claude (tool-use agentic loop)
3. Returns ranked BUY/SELL/WATCH recommendations with confidence, reasoning, catalysts, price targets
4. Scanner symbols are injected into every agent's market context so all agents independently analyze them

---

## After-Hours Sentinel

A background loop that monitors news during non-market hours so major catalysts are caught before the next open.

**Triggers a scanner run when:**
- Earnings beat/miss, raised/lowered guidance
- M&A announcements, buyouts, bankruptcies
- FDA approvals/rejections, clinical trial results
- Executive orders, congressional legislation signed into law
- Fed rate decisions, tariffs, trade deals, sanctions
- Analyst upgrades/downgrades above threshold score

**Policy Monitor** (`data/policy_monitor.py`): scores headlines for 7 sectors (technology, energy, healthcare, defense, financials, consumer, infrastructure) against a 60+ keyword table covering congressional and executive policy actions.

**API:** `GET /api/sentinel` — returns current market status, minutes until open, and all detected catalysts with scores, categories, and affected sectors.

---

## Learning System

File: `backend/learning.json` (auto-created, persists across restarts)

- On every **ClaudeAgent SELL**, the trade is recorded with buy/sell reasoning and PnL%
- Top 20 profitable trades and top 10 loss trades are kept
- Injected into Claude's prompt at the start of each analysis cycle
- Claude uses past wins/losses to refine future decisions

---

## Drift Detection

Endpoint: `GET /api/drift`

Compares each agent's **last 10 closed trades** vs their **all-time baseline**:
- **Win rate drop ≥ 20pp** → drift alert
- **Avg PnL/trade drop ≥ 2%** → drift alert
- Checked automatically every 10 trading cycles
- Logged as `DRIFT DETECTED [AgentName]` warnings in the backend console

---

## Security

The following security measures are implemented:

- **CORS** locked to explicit origins, methods (`GET`, `POST`), and headers
- **Security headers** on all responses: CSP, X-Frame-Options, X-Content-Type-Options, X-XSS-Protection
- **Rate limiting** on `/api/scanner/run` — 10 requests per 60s per IP
- **Error sanitization** — internal exceptions never exposed to HTTP responses
- **`.gitignore`** — blocks `.env`, `site-packages/`, `runtime/`, `trading.db`, `learning.json`
- **WebSocket** uses `wss://` automatically when served over HTTPS

---

## REST API

| Endpoint | Description |
|---|---|
| `GET /api/agents` | All agents with current state |
| `GET /api/leaderboard` | Agents ranked by return % |
| `GET /api/trades` | Recent trades (optional `?agent_id=`) |
| `GET /api/market` | Current prices for watchlist |
| `GET /api/signals` | Multi-source composite signals per symbol |
| `GET /api/scanner` | Latest cached agentic scanner recommendations |
| `POST /api/scanner/run` | Trigger a new Claude-powered market scan (rate limited) |
| `GET /api/sentinel` | After-hours catalyst feed + market open status |
| `GET /api/drift` | Performance drift report per agent |
| `GET /api/performance/{agent_name}` | Full performance history |
| `GET /api/status` | App status (running, market_status, cycle count, watchlist) |
| `POST /api/start` | Start trading competition |
| `POST /api/stop` | Stop trading competition |
| `POST /api/reset` | Reset all portfolios and trade history |
| `WS /ws` | Real-time WebSocket updates (5s interval) |
| `GET /docs` | Interactive API docs (Swagger UI) |

---

## Setup & Running

### Quickstart (self-contained — no internet required)

The `trading_app` folder is fully self-contained. All runtimes and dependencies are bundled.

**Double-click `Start Trading App.exe`** — launches backend, frontend, and opens the browser automatically.

Or run manually in two PowerShell windows:

```powershell
# Terminal 1 — Backend
cd C:\Users\gl450\trading_app
.\start_backend.ps1

# Terminal 2 — Frontend
cd C:\Users\gl450\trading_app
.\start_frontend.ps1
```

> If PowerShell blocks scripts, run once as Administrator:
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

### URLs
- **Dashboard:** http://localhost:5173
- **Backend API:** http://localhost:8000
- **API Docs:** http://localhost:8000/docs

### Offline Setup (new machine)

```powershell
.\setup_offline.ps1
```

Installs all Python packages from `backend/packages/` (no internet needed). Requires Python 3.12 (wheels are built for `cp312-win_amd64`).

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
# Key format: AIzaSy... (not gen-lang-client-...)
GEMINI_API_KEY=your_key

# Trading parameters
STARTING_CAPITAL=100000
MAX_POSITION_SIZE=0.15
TRADE_INTERVAL_SECONDS=60
DAILY_LOSS_LIMIT=0.05

# Watchlist (comma-separated)
WATCHLIST=AAPL,MSFT,GOOGL,TSLA,AMZN,NVDA,META,SPY
```

---

## Python Dependencies (backend)

| Package | Version | Purpose |
|---|---|---|
| `fastapi` | 0.115.0 | REST API framework |
| `uvicorn` | 0.30.0 | ASGI server |
| `alpaca-py` | 0.31.0 | Alpaca Markets SDK (prices, bars, news) |
| `anthropic` | ≥0.50.0 | Claude API client |
| `openai` | 1.84.0 | GPT-4o-mini for sentiment |
| `google-genai` | 1.67.0 | Gemini 2.0 Flash API client |
| `yfinance` | ≥1.2.0 | Analyst ratings, earnings, Yahoo news |
| `pandas` / `numpy` | latest | Data processing |
| `pandas-ta` / `numba` | latest | Technical indicator calculations |
| `aiosqlite` | 0.20.0 | Async SQLite for trade persistence |
| `python-dotenv` | 1.0.0 | `.env` file loading |
| `httpx` | 0.28.1 | HTTP client (compatible with all AI SDKs) |

---

## Key Files to Know

| File | What to edit |
|---|---|
| `.env` | API keys, watchlist, trading parameters |
| `backend/config.py` | Add new config variables or adjust ensemble weights |
| `backend/agents/claude_agent.py` | Modify Claude's prompt or decision logic |
| `backend/agents/gemini_agent.py` | Modify Gemini's prompt or model settings |
| `backend/data/signal_aggregator.py` | Add/adjust external signal sources or weights |
| `backend/data/congressional_trading.py` | SEC EDGAR Form 4 query logic, cache TTL |
| `backend/agents/scanner_agent.py` | Claude tool definitions, agentic loop, cache TTL |
| `backend/data/stock_universe.py` | Add/remove symbols or sectors from the scanner universe |
| `backend/data/news_service.py` | Change news freshness (cache TTL) or lookback window |
| `backend/data/drift_detector.py` | Adjust drift thresholds or window size |
| `backend/data/policy_monitor.py` | Add/adjust congressional/executive order keywords and sector mappings |
| `backend/learning.json` | Auto-managed; delete to reset Claude's learned patterns |
| `backend/data/scan_cache.json` | Auto-managed; delete to force a fresh scanner run on next start |

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for the full history.

| Date | Change |
|---|---|
| 2026-03-15 | **After-hours news & policy sentinel** — background loop monitors news every 15 min when market is closed; triggers scanner on earnings, M&A, FDA, Fed, executive orders, congressional legislation |
| 2026-03-15 | **Policy Monitor** (`data/policy_monitor.py`) — scores headlines for 7 sectors against 60+ congressional/executive keyword table; integrated into sentinel loop |
| 2026-03-15 | **Market hours suspension** — trading loop sleeps until 5 min before next open when market is closed; `market_status` field added to `AppState` and `/api/status` |
| 2026-03-15 | **`GET /api/sentinel`** — new endpoint exposing after-hours catalyst feed, market open status, and minutes until open |
| 2026-03-15 | **Adaptive EnsembleAgent** — replaced fixed weights with performance-weighted voting; regime detection (Trending/Ranging/Volatile) via SMA-20 slope + ATR; regime-specific multipliers applied automatically |
| 2026-03-15 | **Auto-start & auto-scan** — app starts trading and scanning immediately on launch; scan repeats every 30 min during market hours with pre-market warm-up |
| 2026-03-15 | **Scanner disk persistence** — scan results saved to `data/scan_cache.json`; survive application restarts |
| 2026-03-15 | **Scanner symbol injection** — fresh scanner picks added to `market_context` each cycle so all agents independently analyze them |
| 2026-03-15 | **ScannerPortfolioAgent** added — dedicated agent that acts on cached scanner recommendations using its own strategy |
| 2026-03-15 | Fixed TradeLog blank screen crash (`trade.pnl` undefined on open positions) |
| 2026-03-15 | Replaced 7 delisted/renamed tickers in stock universe (ABC→COR, DFS→USB, SQ→XYZ, PXD→WMB, K→CPB, PARA→FOXA, X→CLF) |
| 2026-03-15 | Suppressed Windows `WinError 10054` asyncio noise from browser tab disconnects |
| 2026-03-15 | Fixed Claude deprecation warning — `thinking.type=enabled` → `adaptive`; reduced max_tokens 8000→5000, OHLCV bars 30→15 |
| 2026-03-15 | Added `_fill_missing()` to ClaudeAgent and GeminiAgent — all market context symbols always receive a signal |
| 2026-03-15 | New-symbol detection in AI agents — forces fresh API call when scanner adds symbols not in last analysis window |
| 2026-03-15 | Scanner "still thinking" UX — frontend polls every 3s during scan; stale cache banner shown after restart |
| 2026-03-15 | Added **GeminiAgent** (Gemini 2.0 Flash) as 7th agent; rebalanced ensemble weights |
| 2026-03-15 | Upgraded `openai` 1.55.0 → 1.84.0 to resolve `httpx` version conflict with `google-genai` |
| 2026-03-15 | Fixed `google.protobuf` namespace collision caused by `google-genai` install |
| 2026-03-15 | ETF symbols (SPY, QQQ, etc.) now skip analyst/earnings fetch to avoid yfinance 404 errors |
| 2026-03-15 | Security hardening: CORS lockdown, security headers, rate limiting, error sanitization |
| 2026-03-15 | App made fully self-contained: `runtime/python/`, `runtime/node/`, `site-packages/` bundled |
| 2026-03-15 | Added `Start Trading App.exe` launcher and PowerShell startup scripts |
| 2026-03-15 | Added `.gitignore` to prevent API keys and large folders from being committed |
