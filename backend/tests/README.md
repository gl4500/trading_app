# Backend Test Suite

## How to Run Tests

From the `backend/` directory (use the self-contained runtime — pytest is not on PATH):

```bash
# Full suite — summary only
C:\Users\gl450\trading_app\runtime\python\python.exe run_tests.py

# Full suite — verbose
C:\Users\gl450\trading_app\runtime\python\python.exe run_tests.py -v

# Security tests only
C:\Users\gl450\trading_app\runtime\python\python.exe -m unittest tests.test_security -v

# Single test class
C:\Users\gl450\trading_app\runtime\python\python.exe -m unittest tests.test_portfolio.TestPortfolioBuy -v
```

> **Note:** The pre-commit hook runs `test_security.py` automatically before every `git commit`.

---

## What Each Test File Covers

| File | Module(s) Tested | Key Areas |
|------|-----------------|-----------|
| `test_agent_utils.py` | `agents/agent_utils.py` | `format_bars_for_prompt`, `build_portfolio_context`, `parse_ai_decisions`, `fill_missing_symbols`, `get_fallback_signals` |
| `test_agent_performance_tracker.py` | `data/agent_performance_tracker.py` | Trade outcome recording, win-rate, avg-pnl, adaptive weight calculation |
| `test_claude_agent.py` | `agents/claude_agent.py` | Prompt construction, Ollama fallback routing, token logging |
| `test_xgb_reasoning_agent.py` | `agents/xgb_reasoning_agent.py` | Signal-model extraction, Ollama reasoning loop, rule-based fallback |
| `test_database.py` | `database.py` | `init_db`, `upsert_agent`, `save_trade`, `get_agent_trades`, `save_performance`, `reset_database`, `upsert_portfolio_position` |
| `test_ensemble_voting.py` | `agents/ensemble_agent.py` | `_vote`, `_detect_regime`, `_compute_adaptive_weights`, regime multipliers |
| `test_gemini_agent.py` | `agents/gemini_agent.py` | Prompt construction, Ollama fallback routing, token logging |
| `test_historical_trends_agent.py` | `agents/historical_trends_agent.py` | Seasonal scoring, channel analysis, multi-period momentum, Stooq bar preference |
| `test_learning_manager.py` | `data/learning_manager.py` | `record_trade`, `get_learning_summary`, trade sorting/capping |
| `test_main_endpoints.py` | `main.py` | All FastAPI REST endpoints, WebSocket handshake, lifespan startup patches |
| `test_market_data_cache.py` | `data/market_data.py` | `MarketDataCache` get/set/clear/TTL expiry |
| `test_mean_reversion_agent.py` | `agents/mean_reversion_agent.py` | Z-score calculation, buy/sell signal generation |
| `test_momentum_agent.py` | `agents/momentum_agent.py` | `_calculate_momentum`, `_check_trailing_stop`, `_generate_signal`, `analyze` |
| `test_policy_monitor.py` | `data/policy_monitor.py` | `score_headline` — policy triggers, categories, sector detection |
| `test_portfolio.py` | `trading/portfolio.py` | Buy/sell execution, cash tracking, avg cost, metrics, Sharpe, max drawdown |
| `test_risk_manager.py` | `trading/risk_manager.py` | Buy/sell validation, daily loss halt, position size limits, concentration check |
| `test_scanner_agent.py` | `agents/scanner_agent.py` | Pre-screen scoring, candidate splitting, merge logic, Ollama-only routing |
| `test_scanner_portfolio_agent.py` | `agents/scanner_portfolio_agent.py` | Recommendation ingestion, position sizing |
| `test_security.py` | Security surface (cross-cutting) | See detail below |
| `test_sentiment_agent.py` | `agents/sentiment_agent.py` | News scoring, Ollama fallback, signal generation |
| `test_sentinel_sources.py` | `data/sentinel_sources.py` | `_parse_rss`, `_make_catalyst`, `_score` — offline parsing helpers |
| `test_signal_aggregator.py` | `data/signal_aggregator.py` | `_score_headlines`, `_aggregate_scores`, `format_for_prompt`, `SOURCE_WEIGHTS` |
| `test_signals_and_drift.py` | `agents/base_agent.py`, `data/drift_detector.py` | `Signal.is_actionable`, `_win_rate`, `_avg_pnl_pct`, `check_drift` |
| `test_stooq_client.py` | `data/stooq_client.py` | CSV parsing, caching, multi-symbol fetch, macro indicators |
| `test_summary_agent.py` | `agents/summary_agent.py` | Report generation, portfolio summary formatting |
| `test_tech_agent.py` | `agents/tech_agent.py` | RSI/MACD/BB signal generation, indicator thresholds |
| `test_technicals.py` | `data/technicals.py` | `compute`, `format_for_prompt`, `_manual_rsi`, `_manual_macd`, `_manual_bb`, `_manual_atr` |

---

## test_security.py — Detail

25 tests across 6 classes. Runs automatically via the pre-commit hook.

| Class | Tests | What It Checks |
|---|---|---|
| `TestSecurityHeaders` | 8 | `X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`, `Referrer-Policy`, CSP present on API routes, CSP absent on `/docs`/`/openapi.json`, headers on 404 |
| `TestCORSEnforcement` | 5 | Allowed origins echoed, disallowed origin not echoed, credentials not allowed, disallowed methods rejected |
| `TestErrorSanitization` | 5 | No traceback on 404, no internal path leak, generic agent 404, no API key patterns in `/api/status`, no traceback on malformed JSON POST |
| `TestSQLHardening` | 3 | Unknown filter fields rejected, valid fields pass with parameterised values, no raw SQL in function signature |
| `TestRateLimiting` | 2 | 429 when limit exceeded, 200 when under limit |
| `TestSecretPatterns` | 2 | No hardcoded secrets in source files, `.env` covered by `.gitignore` |

**Helper — `_start_lifespan_patches()`:** patches all async lifespan functions
(`init_db`, `init_agents`, `cleanup_token_log`, `prune_news_price_snapshots`,
`_ensure_ollama_running`, task-creating functions) to prevent the test client
from starting real background tasks.

---

## TDD Workflow

```
1. Write test  →  tests/test_<module>.py        (RED)
2. Implement   →  write/fix code in the module
3. Run tests   →  run_tests.py -v               (GREEN)
4. Commit      →  pre-commit hook runs Bandit + test_security.py automatically
```

### Key conventions

- All test classes use `unittest.TestCase` (or `unittest.IsolatedAsyncioTestCase` for async)
- Tests never make live HTTP/API calls — use `unittest.mock.patch` or `AsyncMock`
- Tests never write to the real database — use `tempfile.mkstemp()`
- Tests never write to real files — mock `learning.json`, `agent_picks.json`, `scan_cache.json`
- One test file per module: `agents/foo.py` → `tests/test_foo.py`
