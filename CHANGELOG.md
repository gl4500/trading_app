# Changelog

All notable changes to the AI Trading Competition app are recorded here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

---

## [2026-04-07] — Phase 1 Ollama Learning, Dual Error Logs, NSSM Services, Decision Diagram

### Added

- **Phase 1 Ollama learning — few-shot examples** (`data/learning_manager.py`, `agents/claude_agent.py`)
  - New `get_few_shot_examples(n=5)` in `learning_manager.py`:
    - Reads the top N profitable trades from `learning.json` and formats them as explicit few-shot reasoning examples: symbol, buy reasoning, sell reasoning, and outcome %
    - Top 3 loss trades formatted as "AVOID PATTERN" blocks showing which reasoning patterns failed and why
    - Closes with an instruction line directing the model to apply the successful patterns
  - In `_get_ollama_decisions()` (`claude_agent.py`): `get_few_shot_examples()` is called before building the prompt; the few-shot block is prepended to the user message ahead of the stable/dynamic context so the smaller `llama3.1:8b` model sees proven reasoning patterns first
  - When `learning.json` is empty (no trades yet) the function returns an empty string and no block is injected — zero overhead at startup
  - Phase 2 (fine-tuning via JSONL + Unsloth LoRA) is tracked for a future release

- **Dual error log files** (`backend/main.py`)
  - Refactored log handler setup into `_add_log_handler(path, level)` helper — avoids duplicating handler code
  - `error.log` — WARNING+ as before
  - `errors_only.log` — ERROR and CRITICAL only (separate rotating file, never polluted by warnings)
  - `_parse_error_log(errors_only=True)` now accepts a flag to switch between the two files
  - `/api/errors` defaults to `errors_only=True`; pass `?errors_only=false` to include warnings
  - `/api/errors/analyze` reads from `errors_only.log` (limit 50)

- **Error Log dashboard tab** (`frontend/src/components/ErrorLogPanel.tsx`, `frontend/src/components/Dashboard.tsx`)
  - New `⚠ Errors` tab surfacing the error log in the dashboard
  - Summary bar: error count, warning count, mode label ("Errors only" vs "All logs")
  - Warnings toggle button (OFF by default) — fetches `?errors_only=false` when ON
  - Level filter dropdown (All / WARNING / ERROR / CRITICAL)
  - Manual refresh button + 60-second auto-refresh interval
  - "Analyze with AI" button — calls `/api/errors/analyze` and renders AI narrative in an inline card
  - Entries styled by severity: yellow for WARNING, red for ERROR, bright red for CRITICAL
  - Tab bar made horizontally scrollable (`overflow-x-auto` + `shrink-0` on all buttons) to prevent compression on smaller screens

- **NSSM Windows service scripts** (root)
  - `install_services.bat` — installs `TradingAppBackend` and `TradingAppFrontend` as NSSM-managed Windows services:
    - Auto-elevates to administrator via UAC (no manual `runas` needed)
    - Sets `PYTHONPATH=%ROOT%\site-packages` in the service environment so uvicorn resolves without an external launcher
    - Log rotation at 10 MB per log file; restart delay 5 seconds; auto-start on boot
    - Locates `nssm.exe` from PATH or from the root directory automatically
    - Validates Python/Node paths before installing; warns if `.env` is missing
  - `uninstall_services.bat` — stops and removes both services; same UAC auto-elevation

- **Printable decision diagram** (`decision_diagram.html`)
  - Self-contained HTML file — open in any browser, print with Ctrl+P (or File → Print)
  - Renders all 7 decision layers as styled boxes with directional arrows:
    Layer 1 (Data Sources) → Layer 2 (Overnight Sentinel) → Layer 3 (Gemini Pre-Pass) → Layer 4 (Individual Agents) → Layer 5 (Ensemble Voting) → Layer 6 (Risk Manager Gate) → Layer 7 (Scanner Agent)
  - Includes base weights table, regime multiplier table, and full cycle summary

### Changed

- **`main.py` — sys.path bootstrap** — added at the very top (before any imports) to insert `site-packages/` into `sys.path`; ensures uvicorn resolves correctly when the backend is started as a Windows service without an external PYTHONPATH
- **Dashboard tab bar** — all tab buttons given `shrink-0`; container set to `overflow-x-auto` so all 10 tabs remain accessible on narrower displays

---

## [2026-04-05b] — DB Auto-Pruning, Ollama Scanner Crash Retry

### Added

- **`prune_performance_table(days=3)`** (`database.py`)
  - Deletes `performance` rows older than 3 days; returns row count deleted
  - Safe: all read paths (startup chart restore, frontend history chart, cash restore) consume at most 2000 / 200 / 1 rows respectively — 3 days of data covers all of them with margin
  - Called at startup and every 1440 trading cycles (~24 h) in the trading loop

- **`prune_news_price_snapshots(days=14)`** (`database.py`)
  - Deletes completed `news_price_snapshots` rows older than 14 days
  - Pending rows (`price_1h IS NULL`) are never deleted — in-flight price tracking is never interrupted
  - Very old unresolved rows (>42 days) are also cleaned up to prevent indefinite accumulation

### Changed

- **`main.py` — startup + daily DB pruning**
  - Both prune functions imported and called at startup alongside `cleanup_token_log`
  - Daily prune scheduled via `cycle_count % 1440` guard in the main trading loop
  - Expected steady-state DB size: <1 MB (down from ~7 MB after days of accumulation)

- **Scanner/Ollama — retry on HTTP 500 crash** (`agents/scanner_agent.py`)
  - HTTP 500 / "llama runner terminated" errors now retry up to 3 times per round with 5 s / 10 s backoff
  - Root cause: Ollama's llama.cpp runner is killed by the OS when VRAM is exhausted on the RTX 2060 (6 GB); retrying gives Ollama time to restart the process automatically
  - Non-500 errors still break immediately to avoid infinite loops on permanent failures

---

## [2026-04-05] — GPU Telemetry, CNNReasoningAgent Fix, Tier 2 Ollama Swap

### Added

- **GPU telemetry in `/api/telemetry`** (`main.py`)
  - New `nvidia-smi` subprocess call at each telemetry poll: queries `name,utilization.gpu,memory.used,memory.total,temperature.gpu`
  - Returns `gpu[]` array in telemetry response; supports multi-GPU; gracefully returns empty array when no NVIDIA GPU is present or `nvidia-smi` is unavailable
  - No additional Python packages required — `nvidia-smi` ships with NVIDIA drivers

- **GPU section in Telemetry dashboard tab** (`frontend/src/components/TelemetryPanel.tsx`)
  - Per-GPU card: name, temperature, three stat cards (Utilisation %, VRAM Used MB, VRAM Free MB), two gauge bars (utilisation + VRAM %)
  - Color thresholds: utilisation ≥90% → red, ≥60% → yellow, <60% → green; VRAM ≥90% → red, ≥75% → yellow; temp ≥85°C → red, ≥70°C → yellow
  - "No NVIDIA GPU detected" graceful state when `gpu[]` is empty

- **`RESEARCH_MODEL` config variable** (`config.py`)
  - New env var: `RESEARCH_MODEL` — the model name used by ClaudeAgent and GeminiAgent when running in `OLLAMA_ONLY_MODE=1`
  - Defaults to `OLLAMA_MODEL` so both agents share the single loaded model — critical for RTX 2060 (6 GB VRAM), which can only hold one Q4 model at a time
  - Upgrade example: `RESEARCH_MODEL=deepseek-r1:14b` on RTX 3080+ (16 GB+ VRAM)

- **`_get_ollama_decisions()` in ClaudeAgent** (`agents/claude_agent.py`)
  - Local Ollama inference path using `AsyncOpenAI(base_url=config.OLLAMA_BASE_URL, api_key="ollama")`
  - Uses `config.RESEARCH_MODEL` as the model name
  - Builds the same structured prompt as the cloud path via `_build_stable_context()` + `_build_dynamic_context()`
  - 120-second `asyncio.wait_for` timeout; returns `None` on timeout or any error
  - Token logging skipped (zero cost, no quota)

- **`_get_ollama_decisions()` in GeminiAgent** (`agents/gemini_agent.py`)
  - Same pattern as ClaudeAgent but uses `_build_prompt()` (Gemini's existing method)
  - Uses `config.OLLAMA_MODEL` (lighter news synthesis — no need for a larger research model)
  - 120-second timeout; returns `None` on failure

- **`test_cnn_reasoning_agent.py`** — new test file (`backend/tests/`)
  - 8 tests: buy signal, sell signal, hold, `get_position()` regression test, Ollama fallback, empty context, non-dict entries, low confidence → hold
  - Key regression: `test_sell_signal_reads_portfolio_positions_not_get_position` — ensures sell path uses `portfolio.positions[sym].shares` not the nonexistent `get_position()` method

### Changed

- **ClaudeAgent `analyze()` — Tier 2 Ollama swap** (`agents/claude_agent.py`)
  - When `OLLAMA_ONLY_MODE=1`: routes to `_get_ollama_decisions()` instead of Anthropic API; cloud path (backoff, SDK guard) still intact for non-Ollama mode
  - Cycle-throttle (every 5 cycles) and cache-replay logic are preserved for both paths — Ollama is not called every 5 seconds
  - Fallback to `get_fallback_signals()` if Ollama returns `None`

- **GeminiAgent `get_market_view()` and `analyze()` — Tier 2 Ollama swap** (`agents/gemini_agent.py`)
  - Same dispatcher pattern as ClaudeAgent: `OLLAMA_ONLY_MODE=1` routes to `_get_ollama_decisions()`; cycle-throttle (every 10 cycles) preserved

- **SentimentAgent `_get_sentiment()` — Ollama model routing** (`agents/sentiment_agent.py`)
  - When `OLLAMA_ONLY_MODE=1`: uses `config.OLLAMA_MODEL` instead of hardcoded `"gpt-4o-mini"`
  - OpenAI API key guard and daily token budget check both skipped in Ollama mode
  - Token logging (save_token_log, token window update) skipped in Ollama mode (zero cost)

### Added (CNN + Agent Intelligence Loop)

- **`data/agent_performance_tracker.py`** (new module)
  - Queries `trading.db` every 5 minutes for per-agent `win_rate`, `sharpe_ratio`, and `trade_count`
  - Computes normalized 0–1 performance score: `0.5 × win_rate_norm + 0.3 × sharpe_norm + 0.2 × log_trade_norm`
  - Agents with fewer than 5 trades fall back to neutral score (0.5) — prevents noise from early data
  - `consensus_score(agent_signals)` — performance-weighted directional vote (−1 to +1); high-scoring agents have more influence
  - `agreement_fraction(agent_signals)` — fraction of agents voting for the plurality direction (0 to 1)
  - `top_agent(agent_signals)` — highest-scoring agent with a non-HOLD signal
  - `get_metrics_summary()` — raw metrics + score for injection into Ollama prompts
  - Module-level singleton `agent_performance_tracker` imported by `main.py` and `cnn_reasoning_agent.py`

- **Agent signal columns in `signal_history` Parquet files**
  - Three new columns added to `_DTYPE_MAP` (backward-compatible — old files load without them):
    - `agent_consensus` (−1 to +1) — performance-weighted directional vote recorded each cycle
    - `agent_agreement` (0 to 1) — fraction of agents that agreed on the plurality direction
    - `top_agent_correct` (NaN → 0.0/1.0) — filled 24h later: 1 if consensus direction matched actual price return
  - `record_agent_signals(symbol, consensus, agreement)` — patches the most recent snapshot (within 120s) with agent signal data; called from `main.py` after all agents run
  - `update_top_agent_correct(symbol, price)` — fills `top_agent_correct` for snapshots whose 1-day outcome is now known
  - `get_recent_window()` now returns **(7, T)** instead of (5, T): channels 0–4 are source scores, channels 5–6 are `agent_consensus` and `agent_agreement`; old Parquet files without agent columns return zeros for channels 5–6

- **Extended CNN architecture** (`data/cnn_model.py`)
  - Input channels expanded from 5 to **`N_CHANNELS = 7`** — `_build_net(n_channels)` is now parameterized
  - `AGENT_CHANNEL_NAMES = ["agent_consensus", "agent_agreement"]` documents the new channels
  - `build_training_windows()` now returns a **3-tuple `(X, y, w)`** — sample weights `w` derived from `top_agent_correct`:
    - Weight 1.0 — top agent was confirmed correct (strong training signal)
    - Weight 0.5 — top agent was wrong (down-weighted, not discarded)
    - Weight 0.75 — outcome not yet known (neutral)
    - Weight 1.0 — no agent columns present (uniform, backward compat)
  - `fit()` gains `sample_weights` parameter — uses weighted MSE loss via `nn.MSELoss(reduction="none")`
  - Auto-rebuilds net when loaded checkpoint has a different channel count than the current default (safe upgrade from 5-ch → 7-ch models)
  - `get_learned_weights()` normalizes importance over the **5 source channels only** — agent channels excluded from the source-weight display table
  - `n_channels` persisted in `.pt` checkpoint for safe reload after architecture changes

- **Enriched Ollama prompt in CNNReasoningAgent** (`agents/cnn_reasoning_agent.py`)
  - New `## Agent Performance Rankings` section in every prompt:
    ```
    ClaudeAgent    score=0.71  win=62%  sharpe=1.42  trades=87   → BUY  conf=0.82
    TechAgent      score=0.64  win=58%  sharpe=1.18  trades=74   → BUY  conf=0.71
    MomentumAgent  score=0.50  win=50%  sharpe=0.80  trades=61   → HOLD conf=0.55
    SentimentAgent score=0.43  win=44%  sharpe=0.55  trades=55   → SELL conf=0.49
    Weighted consensus : +0.52  |  Agreement : 75%
    ```
  - Ollama now reasons with full context: CNN prediction + source weights + which agents are performing well and what they currently recommend
  - Training call updated to pass sample weights: `signal_cnn.fit(X, y, epochs=80, sample_weights=w)`
  - `analyze()` reads `market_context["__agent_signals__"]` to get other agents' current calls for the prompt

- **Agent signal collection in trading loop** (`main.py`)
  - After `asyncio.gather(*agent_tasks)`, collects `_last_signals` from all non-ensemble agents
  - Calls `agent_performance_tracker.get_scores()` (rate-limited to DB every 5 min)
  - Fires `signal_history.record_agent_signals()` and `update_top_agent_correct()` as background tasks per symbol
  - Sets `market_context["__agent_signals__"]` so CNNReasoningAgent's Ollama prompt includes live agent calls next cycle

### Fixed

- **CNNReasoningAgent halted after 5 cycles** (`agents/cnn_reasoning_agent.py`)
  - Root cause: `self.portfolio.get_position(symbol)` on line 275 — `Portfolio` has no `get_position()` method
  - This raised `AttributeError` every time the agent attempted a SELL, which accumulated to the 5-error halt threshold
  - Fixed: SELL guard changed to `symbol in self.portfolio.positions` (check) and `self.portfolio.positions[symbol].shares` (read)

- **SentimentAgent 404 errors for `gpt-4o-mini`** (`agents/sentiment_agent.py`)
  - When `OLLAMA_ONLY_MODE=1`, `_get_client()` correctly pointed to Ollama, but `_get_sentiment()` still hardcoded `model="gpt-4o-mini"` — a model that doesn't exist in Ollama's registry
  - Fixed: `model_name` variable set to `config.OLLAMA_MODEL` in Ollama mode, `"gpt-4o-mini"` only in cloud mode

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
