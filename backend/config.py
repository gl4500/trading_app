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
    OLLAMA_BASE_URL: str  = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    OLLAMA_MODEL: str     = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    # Research model used by ClaudeAgent and GeminiAgent in Ollama-only mode.
    # Defaults to OLLAMA_MODEL so both share the same loaded model (saves VRAM).
    # Upgrade example for RTX 3080+: RESEARCH_MODEL=deepseek-r1:14b
    # RTX 2060 (6 GB): qwen2.5:7b (~4.5 GB Q4) fits with headroom; llama3.1:8b (~5.0 GB) also fits.
    RESEARCH_MODEL: str   = os.getenv("RESEARCH_MODEL", os.getenv("OLLAMA_MODEL", "qwen2.5:7b"))
    # Optional: override the Ollama binary directory added to PATH on startup.
    # Defaults to %LOCALAPPDATA%\Programs\Ollama on Windows (auto-detected).
    OLLAMA_PATH: str      = os.getenv("OLLAMA_PATH", "")
    # Hybrid mode: Ollama pre-screens all symbols each cycle; only symbols where
    # Ollama confidence >= HYBRID_ESCALATION_THRESHOLD are escalated to Claude Opus.
    # Set OLLAMA_ONLY_MODE=0 and OLLAMA_HYBRID_MODE=1 to enable.
    # Incompatible with OLLAMA_ONLY_MODE=1 (pure Ollama takes precedence).
    OLLAMA_HYBRID_MODE: bool          = os.getenv("OLLAMA_HYBRID_MODE", "0") == "1"
    HYBRID_ESCALATION_THRESHOLD: float = float(os.getenv("HYBRID_ESCALATION_THRESHOLD", "0.65"))

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

    # Watchlist — static seed symbols used as fallback when the scanner pool is small.
    # Set WATCHLIST=* to disable static seeds entirely — the watchlist is then built
    # solely from scanner recommendations and momentum candidates (agent-driven).
    WATCHLIST_STR: str = os.getenv("WATCHLIST", "AAPL,MSFT,GOOGL,TSLA,AMZN,NVDA,META,SPY")
    # Fluid watchlist settings
    WATCHLIST_SIZE: int = int(os.getenv("WATCHLIST_SIZE", "15"))
    WATCHLIST_ANCHORS_STR: str = os.getenv("WATCHLIST_ANCHORS", "SPY")

    @property
    def WATCHLIST(self) -> List[str]:
        raw = self.WATCHLIST_STR.strip()
        # "*" means no static seeds — let agents drive the watchlist entirely
        if not raw or raw == "*":
            return []
        # Only keep values that look like valid tickers (letters, digits, dots, hyphens)
        import re as _re
        return [s for s in (t.strip().upper() for t in raw.split(","))
                if s and _re.match(r'^[A-Z0-9][A-Z0-9.\-]{0,9}$', s)]

    @property
    def WATCHLIST_ANCHORS(self) -> List[str]:
        return [s.strip() for s in self.WATCHLIST_ANCHORS_STR.split(",") if s.strip()]

    # Authentication
    # Set APP_PASSWORD and SESSION_SECRET in .env to enable login protection.
    # Leave APP_PASSWORD empty for open access (local-only use, no auth required).
    # SESSION_SECRET must be a stable random string — changing it invalidates all sessions.
    APP_PASSWORD: str = os.getenv("APP_PASSWORD", "")
    SESSION_SECRET: str = os.getenv("SESSION_SECRET", "")

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "trading.db")
    TOKEN_LOG_RETENTION_DAYS: int = int(os.getenv("TOKEN_LOG_RETENTION_DAYS", "365"))

    # Server — default to localhost only; set HOST=0.0.0.0 in .env only if
    # you intentionally want the API reachable from other devices on the network.
    HOST: str = os.getenv("HOST", "127.0.0.1")
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
