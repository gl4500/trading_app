# trading_app — current test coverage

Mandatory reference for `AGENTS.md` (moved verbatim from `CLAUDE.md`, 2026-11-15). Update this
table in the same change that adds or retires a test module.

## Current Test Coverage

| Module | Test File | Status |
|---|---|---|
| `trading/portfolio.py` | `test_portfolio.py` | ✅ covered |
| `trading/risk_manager.py` | `test_risk_manager.py` | ✅ covered |
| `data/technicals.py` | `test_technicals.py` | ✅ covered |
| `data/policy_monitor.py` | `test_policy_monitor.py` | ✅ covered |
| `data/signal_aggregator.py` | `test_signal_aggregator.py` | ✅ covered |
| `data/sentinel_sources.py` | `test_sentinel_sources.py` | ✅ covered |
| `data/learning_manager.py` | `test_learning_manager.py` | ✅ covered |
| `data/market_data.py` (cache) | `test_market_data_cache.py` | ✅ covered |
| `agents/ensemble_agent.py` | `test_ensemble_voting.py` | ✅ covered |
| `agents/momentum_agent.py` | `test_momentum_agent.py` | ✅ covered |
| `agents/agent_utils.py` | `test_agent_utils.py` | ✅ covered |
| `agents/base_agent.py` | `test_signals_and_drift.py` | ✅ covered |
| `database.py` | `test_database.py` | ✅ covered |
| `agents/mean_reversion_agent.py` | `test_mean_reversion_agent.py` | ✅ covered |
| `agents/tech_agent.py` | `test_tech_agent.py` | ✅ covered |
| `agents/claude_agent.py` | `test_claude_agent.py` | ✅ covered |
| `agents/gemini_agent.py` | `test_gemini_agent.py` | ✅ covered |
| `agents/sentiment_agent.py` | `test_sentiment_agent.py` | ✅ covered |
| `agents/scanner_agent.py` | `test_scanner_agent.py` | ✅ covered |
| `agents/scanner_portfolio_agent.py` | `test_scanner_portfolio_agent.py` | ✅ covered |
| `agents/xgb_reasoning_agent.py` | `test_xgb_reasoning_agent.py` | ✅ covered |
| `data/agent_performance_tracker.py` | `test_agent_performance_tracker.py` | ✅ covered |
| `agents/summary_agent.py` | `test_summary_agent.py` | ✅ covered |
| `agents/historical_trends_agent.py` | `test_historical_trends_agent.py` | ✅ covered |
| `data/stooq_client.py` | `test_stooq_client.py` | ✅ covered |
| `main.py` endpoints | `test_main_endpoints.py` | ✅ covered |
| security surface (headers, CORS, SQL, secrets) | `test_security.py` | ✅ covered |
| `data/regime_detector.py` | `test_regime_detector.py` | ✅ covered |
| `trading/portfolio.py` (Kelly sizing) | `test_portfolio.py::TestKellyFraction` | ✅ covered |
| `trading/portfolio.py` (Bayesian confidence) | `test_portfolio.py::TestBayesianConfidence` | ✅ covered |
| `data/cnn_model.py` (WFE) | `test_cnn_model.py::TestWalkForwardEfficiency` | ✅ covered |
| `data/cnn_model.py` (walk-forward CV) | `test_cnn_model.py::TestFitProducesWalkforwardMetrics`, `TestBuildTrainingWindowsReturnsTimestamps`, `TestTrainingHistoryRecordSchema` | ✅ covered |
| `data/xgboost_model.py` | `test_xgboost_model.py` | ✅ covered |
| `data/w3_model.py` | `test_w3_model.py` | ✅ covered |
| `data/signal_model.py` | `test_signal_model_selector.py` | ✅ covered |
| `data/cnn_evaluation.py` | `test_cnn_evaluation.py` | ✅ covered |
| CNN random-feature sanity (one-off) | `test_cnn_random_feature.py` | ⚠️ expected-failure diagnostic |
| `data/macro_history.py` + `data/history_backfill.py` (macro) | `test_macro_history.py` | ✅ covered |
| `data/tax_estimator.py` | `test_tax_estimator.py` | ✅ covered |
| `trading/alpaca_client.py` (get_filled_orders) | `test_tax_estimator.py` | ✅ covered |
| `data/news_service.py` (retry, circuit breaker, timeout) | `test_news_service.py` | ✅ covered |
