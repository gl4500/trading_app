# Changelog

All notable changes to the AI Trading Competition app are recorded here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

---

## [2026-03-29] — HistoricalTrendsAgent + Stooq Free Historical Data

### Added

- **HistoricalTrendsAgent** (`agents/historical_trends_agent.py`)
  - Pure rule-based agent with three analytical pillars:
    1. **Seasonal bias** — month-of-year calendar effect (January effect, Sell-in-May, September weakness, Santa rally, etc.) combined with quarter-position bias for window-dressing effects; scores −1 to +1
    2. **Channel analysis** — price position within the full historical high-low range, SMA-20 slope adjusted so a strong uptrend moderates the bearish penalty for being near the high
    3. **Multi-period momentum** — weighted rate-of-change across 5/10/20/40-day windows; alignment bonus applied when all timeframes agree on direction
    4. **Volume confirmation** — small (≤0.15) confirmation score based on whether recent volume is heavier on up-days vs down-days
  - Composite weights: seasonal 20%, channel 30%, momentum 40%, volume 10%
  - BUY threshold: composite > +0.25; SELL threshold: composite < −0.25
  - Prefers Stooq long-term bars (up to 5 years) for richer seasonality analysis; falls back to Alpaca short-term bars
  - Replaces OpenClawAgent as the 6th ensemble voter

- **StooqClient** (`data/stooq_client.py`)
  - Free daily OHLCV data from stooq.com — no API key required
  - Returns up to 5 years (1250 trading days) of history per symbol
  - 4-hour in-memory cache — historical bars update once per day at most
  - Graceful degradation: returns empty DataFrame on any network/parse error
  - `get_bars(symbol, days)` — single symbol async fetch
  - `get_bars_multi(symbols, days)` — concurrent multi-symbol fetch via `asyncio.gather`

- **`get_long_term_bars()` in `market_data.py`**
  - New `MarketData` method that fetches multi-year OHLCV from Stooq for the whole watchlist
  - Uses a separate 4-hour cache key (`{sym}|lt|{days}`) so long-term data doesn't evict short-term bars
  - Called in the main market context build loop; injects `long_term_bars` into each symbol's context dict
  - Used by `HistoricalTrendsAgent.analyze()` — falls back to standard bars when Stooq returns no data

- **Stooq as bar fallback in `market_data.get_all_bars()`**
  - Alpaca → Massive (Fallback 1) → Stooq (Fallback 2)
  - Stooq fallback fires silently when Alpaca and Massive both fail to return bars for a symbol

- **`STOOQ_LONG_TERM_DAYS = 1250`** in `config.py` — controls default depth for long-term historical fetches

### Changed

- **Ensemble base weights** (`config.py`) — rebalanced after removing OpenClawAgent:
  - ClaudeAgent: 28% → 29%
  - HistoricalTrendsAgent: 8% (replaces OpenClawAgent's 9%)
  - All other agents unchanged

- **Regime multipliers** (`ensemble_agent.py`) — updated for HistoricalTrendsAgent:
  - `trending`: HistoricalTrendsAgent ×1.20 (seasonal + multi-period momentum shine in trends)
  - `ranging`: HistoricalTrendsAgent ×1.30 (channel analysis works well range-bound)
  - `volatile`: HistoricalTrendsAgent ×0.80 (seasonal patterns less reliable when volatility spikes)

### Removed

- **OpenClawAgent** (`agents/openclaw_agent.py`) — local-model processing agent removed; replaced by HistoricalTrendsAgent
- **`test_openclaw_agent.py`** — test file removed alongside its agent

---

## [2026-03-15] — Sentinel, Policy Monitor, Adaptive Ensemble, Market Hours

### Added

- **After-hours news & policy sentinel** (`main.py: news_sentinel_loop`)
  - Background asyncio task that runs while the market is closed
  - Polls Alpaca news every 15 minutes for watchlist + current scanner symbols
  - Two-engine scoring: standard catalyst keywords (earnings, M&A, FDA, upgrades) and the new policy monitor
  - Triggers a fresh scanner run when combined catalyst score ≥ 2
  - Stores up to 50 recent catalysts in `app_state.after_hours_catalysts` (sorted by score)
  - Fully integrated with `/api/stop`, `/api/start`, and lifespan shutdown

- **Policy Monitor** (`data/policy_monitor.py`)
  - New module for scoring news headlines on congressional and executive policy impact
  - Covers: executive orders, bills signed into law, tariffs, trade deals, sanctions, Fed rate decisions, debt ceiling, government shutdowns, geopolitical events, antitrust actions, SEC/DOJ/FTC rulings
  - Sector-aware: maps keywords to technology, energy, healthcare, defense, financials, consumer, and infrastructure sectors
  - `score_headline(headline, summary)` — returns score, category, sectors, matched keywords
  - `scan_policy_news(symbols, lookback_hours)` — async batch scan across broad-market ETF proxies + supplied symbols

- **`GET /api/sentinel`** — new REST endpoint
  - Returns: `market_status`, `market_is_open`, `minutes_until_open`, `catalyst_count`, `catalysts[]`
  - Each catalyst includes: headline, summary, source, date, symbol, score, category, sectors, reason, detected_at

- **Market hours suspension in trading loop** (`main.py: trading_loop`)
  - Checks `_market_is_open()` at the start of each cycle
  - When closed: updates `app_state.market_status = "closed"`, sleeps until 5 minutes before next open
  - When open: sets `app_state.market_status = "open"` and proceeds normally
  - Handles `asyncio.CancelledError` cleanly during sleep

- **`market_status` field** in `AppState` and `GET /api/status`
  - Values: `"open"`, `"closed"`, `"unknown"`

- **`after_hours_catalysts` field** in `AppState`
  - List of catalyst dicts populated by the sentinel loop

- **`sentinel_task` field** in `AppState`
  - Tracked alongside `trading_task` and `scan_task`; cancelled on stop/shutdown

- **Adaptive EnsembleAgent** (`agents/ensemble_agent.py`) — complete rewrite
  - Performance-weighted voting: each agent scored by `0.5 × win_rate + 0.5 × normalised_sharpe`
  - Sharpe normalised from `[-2, +3]` to `[0, 1]`
  - Weight floor: no agent drops below 30% of its base weight (`WEIGHT_FLOOR = 0.30`)
  - Regime detection every 5 cycles using SMA-20 slope and ATR:
    - `volatile`: ATR/price > 2.5%
    - `trending`: SMA-20 moved > 0.4% over 10 bars
    - `ranging`: default
  - Regime-specific multipliers applied per agent (e.g. ClaudeAgent ×1.40 in volatile markets)
  - Weights normalised to sum = 1 after floor and regime adjustments
  - Regime and weight changes logged when shift exceeds 3 percentage points
  - Signal reasoning tagged with regime: `ENSEMBLE BUY [TRENDING]`

- **Auto-scan loop** (`main.py: auto_scan_loop`)
  - Scans every 30 minutes during market hours
  - Pre-market warm-up: runs 10 minutes before next open
  - Outside hours: sleeps; does not waste API calls
  - Fires once at startup if no fresh cache exists

- **Auto-start on launch** (`main.py: lifespan`)
  - Trading loop, scan loop, and sentinel loop all start automatically — no manual `/api/start` needed

- **Scanner disk persistence** (`agents/scanner_agent.py`)
  - Results saved to `data/scan_cache.json` on every completed scan
  - Cache loaded from disk at module import — picks survive backend restarts
  - `is_stale` flag set when cache age exceeds TTL

- **ScannerPortfolioAgent** (`agents/scanner_portfolio_agent.py`)
  - Dedicated agent that reads cached scanner recommendations and applies its own buy/sell strategy
  - Does not trigger new API calls per cycle; uses fresh cache only

- **Scanner symbol injection** in trading loop
  - Fresh scanner recommendations are fetched each cycle and merged into `market_context`
  - All agents independently analyze scanner-identified symbols using their own strategies

- **`_fill_missing()` in ClaudeAgent and GeminiAgent**
  - Ensures every symbol in `market_context` receives a signal (HOLD if not covered by the analysis window)
  - Prevents EnsembleAgent from missing symbols

- **New-symbol detection in AI agents**
  - ClaudeAgent and GeminiAgent track `_watchlist` across cycles
  - When scanner adds symbols not seen in the last prompt, the cycle count is reset to force a fresh API call

- **Scanner "still thinking" UX** (`frontend/src/components/ScannerPanel.tsx`)
  - Frontend polls `/api/scanner` every 3 seconds while `is_scanning` is true
  - Navigating away and back still shows the in-progress spinner
  - Stale cache banner (yellow warning) shown when viewing results from a previous session
  - "No scan results yet" message updated to mention the 30-minute auto-scan schedule

- **`is_scan_in_progress()` public function** in `agents/scanner_agent.py`
  - Thread-safe boolean flag; exposed on the `/api/scanner` GET response as `is_scanning`

- **Windows `WinError 10054` log suppression** (`main.py: _SuppressWin10054`)
  - Filters asyncio logger to hide the harmless "connection forcibly closed" noise from browser tab closes

### Changed

- **Ensemble weights** — base weights rebalanced to accommodate ScannerPortfolioAgent; adaptive system adjusts from these bases automatically
- **ClaudeAgent** — `thinking.type` changed from deprecated `enabled` (with `budget_tokens`) to `adaptive`; `max_tokens` reduced 8000→5000; OHLCV bars reduced 30→15; `MAX_SYMBOLS` cap of 12 added
- **GeminiAgent** — OHLCV bars reduced 30→15; `_fill_missing()` and new-symbol detection added
- **`/api/status`** — now includes `market_status` field
- **`/api/stop`** — now cancels sentinel task in addition to trading and scan tasks
- **`AppState`** — added `sentinel_task`, `market_status`, `after_hours_catalysts` fields
- **Stock universe** (`data/stock_universe.py`) — replaced 7 delisted/renamed tickers:
  - ABC → COR (Cencora)
  - DFS → USB (U.S. Bancorp)
  - SQ → XYZ (placeholder; Block delisted from original watchlist)
  - PXD → WMB (Williams Companies)
  - K → CPB (Campbell Soup)
  - PARA → FOXA (Fox Corp)
  - X → CLF (Cleveland-Cliffs)

### Fixed

- **TradeLog blank screen crash** (`frontend/src/components/TradeLog.tsx`)
  - `trade.pnl.toFixed()` threw on open positions where `pnl` is undefined
  - Fixed: `(trade.pnl ?? 0).toFixed(2)` and `(trade.pnl ?? 0) >= 0`

- **EnsembleAgent variable shadowing bug**
  - Loop variable `regime` was shadowing the function parameter `regime`
  - Renamed loop variable to `regime_mod`

- **EnsembleAgent unused method removed**
  - `_get_price_from_signals` referenced `sig.price` which does not exist on the `Signal` dataclass
  - Method removed entirely

- **Claude deprecation warning**
  - `thinking.type=enabled` is deprecated in claude-opus-4-6
  - Changed to `thinking.type=adaptive` (no `budget_tokens` needed)

- **No-bars warnings for delisted tickers**
  - ABC, DFS, K, PARA, PXD, SQ, X were causing repeated "No bars" warnings
  - All replaced with active tickers in the stock universe

---

## [2026-03-14] — Initial Multi-Agent Build

### Added

- **Core agents**: TechAgent, MomentumAgent, MeanReversionAgent, SentimentAgent, ClaudeAgent, GeminiAgent, EnsembleAgent
- **FastAPI backend** with SQLite persistence (`database.py`)
- **WebSocket broadcast loop** — real-time updates every 5 seconds
- **Market data pipeline**: Alpaca prices + bars, Alpaca news, multi-source composite signal (analyst ratings, earnings surprise, congressional trades, news scoring)
- **Technical indicators**: RSI(14), MACD(12,26,9), Bollinger Bands(20,2), SMA20/50, ATR(14), volume ratio
- **Congressional/insider trade signal** via SEC EDGAR Form 4 (`data/congressional_trading.py`)
- **Learning system** — ClaudeAgent records sell trades to `learning.json`; injected into future prompts
- **Drift detection** (`data/drift_detector.py`) — win rate and avg PnL compared vs all-time baseline; checked every 10 cycles
- **Agentic scanner** (`agents/scanner_agent.py`) — pre-screens ~160 stocks, deep-dives candidates with Claude tool-use loop
- **React + Vite frontend** with live leaderboard, agent cards, trade log, portfolio chart, scanner panel
- **Security**: CORS lockdown, security headers (CSP, X-Frame-Options, etc.), rate limiting, error sanitization
- **Self-contained distribution**: bundled Python 3.12 + Node.js runtimes, all packages offline-installable
- **Launcher**: `Start Trading App.exe`, PowerShell scripts, `gen_certs.py` for HTTPS
- GeminiAgent added as 7th agent (Gemini 2.0 Flash); ensemble weights rebalanced
- ETF symbols skip analyst/earnings fetch (yfinance 404 fix)
- `openai` upgraded 1.55.0 → 1.84.0 to resolve `httpx` conflict with `google-genai`
