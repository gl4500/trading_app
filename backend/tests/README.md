# Backend Test Suite

## How to Run Tests

From the `backend/` directory:

```bash
# Run all tests with verbose output
python -m pytest tests/ -v

# Run a single test file
python -m pytest tests/test_portfolio.py -v

# Run a specific test class
python -m pytest tests/test_risk_manager.py::TestRiskManagerBuy -v

# Run with short tracebacks (default via pytest.ini)
python -m pytest tests/

# Run and stop on first failure
python -m pytest tests/ -x
```

> **Note:** pytest and pytest-asyncio are listed in `requirements.txt`.
> Install them with `pip install pytest pytest-asyncio` if needed.

---

## What Each Test File Covers

| File | Module(s) Tested | Key Areas |
|------|-----------------|-----------|
| `test_agent_utils.py` | `agents/agent_utils.py` | `format_bars_for_prompt`, `build_portfolio_context`, `parse_ai_decisions`, `fill_missing_symbols`, `get_fallback_signals` |
| `test_database.py` | `database.py` | `init_db`, `upsert_agent`, `save_trade`, `get_agent_trades`, `save_performance`, `reset_database`, `upsert_portfolio_position` |
| `test_ensemble_voting.py` | `agents/ensemble_agent.py` | `_vote`, `_detect_regime`, `_compute_adaptive_weights`, regime multipliers |
| `test_learning_manager.py` | `data/learning_manager.py` | `record_trade`, `get_learning_summary`, trade sorting/capping |
| `test_market_data_cache.py` | `data/market_data.py` | `MarketDataCache` get/set/clear/TTL expiry |
| `test_momentum_agent.py` | `agents/momentum_agent.py` | `_calculate_momentum`, `_check_trailing_stop`, `_generate_signal`, `analyze` |
| `test_policy_monitor.py` | `data/policy_monitor.py` | `score_headline` — policy triggers, categories, sector detection |
| `test_portfolio.py` | `trading/portfolio.py` | Buy/sell execution, cash tracking, avg cost, metrics, Sharpe, max drawdown |
| `test_risk_manager.py` | `trading/risk_manager.py` | Buy/sell validation, daily loss halt, position size limits, concentration check |
| `test_sentinel_sources.py` | `data/sentinel_sources.py` | `_parse_rss`, `_make_catalyst`, `_score` — offline parsing helpers |
| `test_signal_aggregator.py` | `data/signal_aggregator.py` | `_score_headlines`, `_aggregate_scores`, `format_for_prompt`, `SOURCE_WEIGHTS` |
| `test_signals_and_drift.py` | `agents/base_agent.py`, `data/drift_detector.py` | `Signal.is_actionable`, `_win_rate`, `_avg_pnl_pct`, `check_drift` |
| `test_technicals.py` | `data/technicals.py` | `compute`, `format_for_prompt`, `_manual_rsi`, `_manual_macd`, `_manual_bb`, `_manual_atr` |

---

## Remaining Gaps (not yet unit-tested)

These modules interact heavily with external services (Alpaca API, Claude/Gemini AI, live market data) and require integration tests or deeper mocking:

| Module | Why Not Unit-Tested |
|--------|---------------------|
| `main.py` | FastAPI app startup — test endpoints with `TestClient` (see below) |
| `data/market_data.py` `MarketDataService` | Depends on `alpaca_client` + `news_service` |
| `data/market_data.py` `build_market_context` | Chains multiple live-data calls |
| `agents/claude_agent.py` | Calls Anthropic API — mock `anthropic.Anthropic` |
| `agents/gemini_agent.py` | Calls Google Gemini API — mock `google.generativeai` |
| `agents/tech_agent.py` | Thin wrapper around `agent_utils`; covered indirectly |
| `agents/sentiment_agent.py` | Calls news service + AI |
| `agents/mean_reversion_agent.py` | Logic similar to momentum_agent; candidate for next test file |
| `agents/scanner_agent.py` | Depends on `market_data` and AI calls |
| `trading/alpaca_client.py` | All methods hit the Alpaca REST API |
| `data/news_service.py` | Calls Alpaca News API |
| `data/congressional_trading.py` | Calls SEC EDGAR |

### Suggested next test file: `test_main_endpoints.py`

```python
from fastapi.testclient import TestClient
# Patch alpaca_client, news_service, and AI clients before importing main
from main import app
client = TestClient(app)
```

---

## TDD Workflow

```
1. Write test  →  tests/test_<module>.py
2. Run tests   →  python -m pytest tests/ -v   (see RED)
3. Implement   →  write/fix code in the module
4. Run tests   →  python -m pytest tests/ -v   (see GREEN)
5. Refactor    →  clean up, keep tests green
6. Commit      →  git add tests/ <module.py> && git commit -m "feat: ..."
```

### Key conventions

- All test classes use `unittest.TestCase` (or `unittest.IsolatedAsyncioTestCase` for async)
- Async helpers that must run in a sync test use `asyncio.get_event_loop().run_until_complete(coro)`
- Tests never make live HTTP/API calls — use `unittest.mock.patch` or `AsyncMock`
- Tests never write to the real database or `learning.json` — use `tempfile.mkstemp`
- Shared fixtures live in `conftest.py` (pytest-style) for pytest consumers
