"""
Shared pytest fixtures for the trading_app backend test suite.

Provides reusable mock objects so individual test files don't repeat
boilerplate setup. All fixtures use plain values (no live API calls).
"""
import sys
import os
import pytest

# Ensure backend root is on the path for all tests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from trading.portfolio import Portfolio, Position


# ── Portfolio fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def empty_portfolio():
    """A fresh portfolio with $100,000 cash and no positions."""
    return Portfolio(starting_capital=100_000)


@pytest.fixture
def portfolio_with_positions():
    """Portfolio with $50,000 cash and positions in AAPL and MSFT."""
    p = Portfolio(starting_capital=100_000)
    p.execute_buy("AAPL", 100, 100.0)   # cost $10,000
    p.execute_buy("MSFT", 50, 300.0)    # cost $15,000
    return p


# ── Market context fixtures ───────────────────────────────────────────────────

@pytest.fixture
def mock_prices():
    """Standard test prices dict."""
    return {
        "AAPL": 150.0,
        "MSFT": 300.0,
        "GOOGL": 2800.0,
        "TSLA": 200.0,
        "SPY": 450.0,
    }


@pytest.fixture
def mock_market_context():
    """
    Minimal market_context dict for two symbols.
    Matches the shape used by agent analyze() methods:
      { symbol: { price, bars, stats, news, indicators, composite_signal } }
    """
    return {
        "AAPL": {
            "price": 150.0,
            "bars": None,
            "stats": {},
            "news": [],
            "indicators": None,
            "composite_signal": {},
        },
        "MSFT": {
            "price": 300.0,
            "bars": None,
            "stats": {},
            "news": [],
            "indicators": None,
            "composite_signal": {},
        },
    }


# ── Config fixture ────────────────────────────────────────────────────────────

@pytest.fixture
def mock_config():
    """
    Returns a plain dict of config defaults so tests don't need the real
    Config object (which reads .env).
    """
    return {
        "STARTING_CAPITAL": 100_000,
        "MAX_POSITION_SIZE": 0.15,
        "DAILY_LOSS_LIMIT": 0.05,
        "TRADE_INTERVAL_SECONDS": 60,
        "WATCHLIST": ["AAPL", "MSFT", "GOOGL", "TSLA", "SPY"],
        "ENSEMBLE_THRESHOLD": 0.35,
        "RSI_OVERSOLD": 35.0,
        "RSI_OVERBOUGHT": 65.0,
        "MOMENTUM_THRESHOLD": 0.01,
        "TRAILING_STOP": 0.03,
        "MR_BUY_ZSCORE": -1.5,
        "MR_SELL_ZSCORE": 1.5,
    }
