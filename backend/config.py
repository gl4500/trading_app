"""
Configuration management for the AI Trading Competition app.
Loads settings from environment variables with sensible defaults.
"""
import os
from dotenv import load_dotenv
from typing import List

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))


class Config:
    # Alpaca Markets (paper trading)
    ALPACA_API_KEY: str = os.getenv("ALPACA_API_KEY", "")
    ALPACA_SECRET_KEY: str = os.getenv("ALPACA_SECRET_KEY", "")
    ALPACA_BASE_URL: str = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    # AI API Keys
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

    # OpenClaw local model gateway (OpenAI-compatible)
    OPENCLAW_BASE_URL: str = os.getenv("OPENCLAW_BASE_URL", "http://127.0.0.1:18789/v1")
    OPENCLAW_TOKEN: str    = os.getenv("OPENCLAW_TOKEN", "")
    OPENCLAW_MODEL: str    = os.getenv("OPENCLAW_MODEL", "llama3.2")

    # Ollama local model (OpenAI-compatible, zero token cost)
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    OLLAMA_MODEL: str    = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
    # Optional: override the Ollama binary directory added to PATH on startup.
    # Defaults to %LOCALAPPDATA%\Programs\Ollama on Windows (auto-detected).
    OLLAMA_PATH: str     = os.getenv("OLLAMA_PATH", "")

    # Additional data source keys
    FINNHUB_API_KEY: str = os.getenv("FINNHUB_API_KEY", "")
    UNUSUAL_WHALES_API_KEY: str = os.getenv("UNUSUAL_WHALES_API_KEY", "")

    # Massive.com financial data
    MASSIVE_API_KEY: str = os.getenv("MASSIVE_API_KEY", "")
    MASSIVE_S3_BUCKET: str = os.getenv("MASSIVE_S3_BUCKET", "")
    MASSIVE_S3_ACCESS_KEY: str = os.getenv("MASSIVE_S3_ACCESS_KEY", "")
    MASSIVE_S3_SECRET_KEY: str = os.getenv("MASSIVE_S3_SECRET_KEY", "")
    MASSIVE_S3_REGION: str = os.getenv("MASSIVE_S3_REGION", "us-east-1")

    # Trading parameters
    STARTING_CAPITAL: float = float(os.getenv("STARTING_CAPITAL", "100000"))
    MAX_POSITION_SIZE: float = float(os.getenv("MAX_POSITION_SIZE", "0.15"))  # 15% max per position
    TRADE_INTERVAL_SECONDS: int = int(os.getenv("TRADE_INTERVAL_SECONDS", "60"))
    DAILY_LOSS_LIMIT: float = float(os.getenv("DAILY_LOSS_LIMIT", "0.05"))  # 5% daily loss stops trading

    # Watchlist — seeds used as fallback when scanner pool is small
    WATCHLIST_STR: str = os.getenv("WATCHLIST", "AAPL,MSFT,GOOGL,TSLA,AMZN,NVDA,META,SPY")
    # Fluid watchlist settings
    WATCHLIST_SIZE: int = int(os.getenv("WATCHLIST_SIZE", "15"))
    WATCHLIST_ANCHORS_STR: str = os.getenv("WATCHLIST_ANCHORS", "SPY")

    @property
    def WATCHLIST(self) -> List[str]:
        return [s.strip() for s in self.WATCHLIST_STR.split(",") if s.strip()]

    @property
    def WATCHLIST_ANCHORS(self) -> List[str]:
        return [s.strip() for s in self.WATCHLIST_ANCHORS_STR.split(",") if s.strip()]

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "trading.db")
    TOKEN_LOG_RETENTION_DAYS: int = int(os.getenv("TOKEN_LOG_RETENTION_DAYS", "365"))

    # Server
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))

    # WebSocket update interval
    WS_UPDATE_INTERVAL: int = int(os.getenv("WS_UPDATE_INTERVAL", "5"))

    # Ensemble voting weights
    ENSEMBLE_WEIGHTS = {
        "ClaudeAgent":            0.29,
        "TechAgent":              0.23,
        "SentimentAgent":         0.17,
        "MomentumAgent":          0.14,
        "MeanReversionAgent":     0.09,
        "HistoricalTrendsAgent":  0.08,
    }
    ENSEMBLE_THRESHOLD: float = 0.60  # raised from 0.35 — only enter on high conviction (post: 72% for Polymarket, 0.60 calibrated for 5-agent stock ensemble)
    MARGIN_OF_SAFETY: float = 2.0    # buy_score must be >= sell_score * this — blocks entry when opposing signal is too strong

    # Technical analysis parameters
    RSI_PERIOD: int = 14
    RSI_OVERSOLD: float = 35.0
    RSI_OVERBOUGHT: float = 65.0
    BB_PERIOD: int = 20
    BB_STD: float = 2.0
    MACD_FAST: int = 12
    MACD_SLOW: int = 26
    MACD_SIGNAL: int = 9

    # Momentum parameters
    MOMENTUM_SHORT: int = 5
    MOMENTUM_MID: int = 10
    MOMENTUM_LONG: int = 20
    MOMENTUM_THRESHOLD: float = 0.01  # 1% momentum threshold (2% was too high for large-cap stocks)
    TRAILING_STOP: float = 0.03  # 3% trailing stop

    # Mean reversion parameters
    MR_PERIOD: int = 20
    MR_BUY_ZSCORE: float = -1.5
    MR_SELL_ZSCORE: float = 1.5

    # Historical data
    HISTORICAL_DAYS: int = 60
    DATA_CACHE_SECONDS: int = 60  # cache market data for 60 seconds

    # Stooq long-term historical data (used by HistoricalTrendsAgent)
    STOOQ_LONG_TERM_DAYS: int = 1250  # ~5 years of trading days


config = Config()
