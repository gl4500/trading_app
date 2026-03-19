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

    # Additional data source keys
    FINNHUB_API_KEY: str = os.getenv("FINNHUB_API_KEY", "")
    UNUSUAL_WHALES_API_KEY: str = os.getenv("UNUSUAL_WHALES_API_KEY", "")

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

    # Server
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))

    # WebSocket update interval
    WS_UPDATE_INTERVAL: int = int(os.getenv("WS_UPDATE_INTERVAL", "5"))

    # Ensemble voting weights
    ENSEMBLE_WEIGHTS = {
        "ClaudeAgent":        0.32,
        "TechAgent":          0.25,
        "SentimentAgent":     0.18,
        "MomentumAgent":      0.15,
        "MeanReversionAgent": 0.10,
    }
    ENSEMBLE_THRESHOLD: float = 0.35  # 35% weighted agreement required

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


config = Config()
