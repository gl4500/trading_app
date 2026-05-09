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
    # 2026-05-08: OLLAMA_HYBRID_MODE retired. Hybrid (Ollama pre-screens →
    # Claude validates) was a coupling inside ClaudeAgent that meant a
    # malformed Ollama response could crash the Claude code path. Now
    # ClaudeAgent (cloud) and OllamaAgent (local) vote independently in
    # the ensemble. The two attributes below are kept ONLY so old .env
    # files don't break — they are not consumed by any code path.
    OLLAMA_HYBRID_MODE: bool          = os.getenv("OLLAMA_HYBRID_MODE", "0") == "1"   # noqa: deprecated
    HYBRID_ESCALATION_THRESHOLD: float = float(os.getenv("HYBRID_ESCALATION_THRESHOLD", "0.65"))   # noqa: deprecated

    # Additional data source keys
    FINNHUB_API_KEY: str = os.getenv("FINNHUB_API_KEY", "")
    UNUSUAL_WHALES_API_KEY: str = os.getenv("UNUSUAL_WHALES_API_KEY", "")
    FRED_API_KEY: str = os.getenv("FRED_API_KEY", "")

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
    ANNUAL_GOAL: float = float(os.getenv("ANNUAL_GOAL", "50000"))  # annual P&L target in dollars

    # AI agent call-rate limits (cloud mode only — Ollama is uncapped)
    # Claude Opus 4.6: 10/hr lets _open_interval=5 control cadence (~12 calls/hr)
    # Gemini Flash: 20/hr — very cheap, near-free per call
    CLAUDE_HOURLY_CALL_LIMIT: int = int(os.getenv("CLAUDE_HOURLY_CALL_LIMIT", "10"))
    GEMINI_HOURLY_CALL_LIMIT: int = int(os.getenv("GEMINI_HOURLY_CALL_LIMIT", "20"))

    # Risk manager limits (tunable without code changes)
    CHURN_COOLOFF_MINUTES: int    = int(float(os.getenv("CHURN_COOLOFF_MINUTES", "30")))
    SECTOR_CONCENTRATION_LIMIT: float = float(os.getenv("SECTOR_CONCENTRATION_LIMIT", "0.35"))
    CORRELATION_LIMIT: float      = float(os.getenv("CORRELATION_LIMIT", "0.65"))

    # Bayesian early-exit threshold: sell when bayes_confidence drops this far
    # below entry_confidence (e.g. 0.30 = sell if conviction fell 30 pp since entry)
    BAYES_EXIT_DROP: float = float(os.getenv("BAYES_EXIT_DROP", "0.30"))

    # Trailing stop on UNREALIZED PnL (added 2026-04-29):
    # Sell when (peak_unrealized_pnl - current_unrealized_pnl) >=
    #          peak_unrealized_pnl × TRAIL_GIVEBACK_PCT,
    # but only after peak first reaches TRAIL_ARM_USD (avoids whipsawing
    # on tiny noise around break-even). Goal: lock in gains by selling when
    # a profitable position has given back X% of its peak unrealized profit.
    TRAIL_GIVEBACK_PCT: float = float(os.getenv("TRAIL_GIVEBACK_PCT", "0.20"))
    TRAIL_ARM_USD:      float = float(os.getenv("TRAIL_ARM_USD",      "25.0"))

    # Hard stop-loss (Backlog 0.4, 2026-04-29):
    # Defensive floor — sell when (avg_cost - current_price) / avg_cost >=
    # HARD_STOP_PCT, regardless of Bayes / trailing / LLM. Catches positions
    # that drop sharply from entry without ever being profitable (the case
    # the trailing stop CAN'T catch since trail only arms on positive PnL).
    # Set HARD_STOP_PCT=0 (or any negative) to disable.
    HARD_STOP_PCT: float = float(os.getenv("HARD_STOP_PCT", "0.08"))

    # Model backend selector (added 2026-05-02). Default keeps the legacy
    # CNN; set to "xgboost" to switch to the gradient-boosted regressor.
    MODEL_BACKEND: str = os.getenv("MODEL_BACKEND", "cnn").lower().strip()

    # Daily-move risk re-evaluation (Backlog 0.5, 2026-04-29):
    # When a held position drops more than DAILY_REVIEW_PCT from today's open,
    # the CNN agent injects a "## RISK ALERT" block into the Ollama prompt
    # telling the LLM to explicitly reconsider whether to exit. Defends
    # against catalysts that arrive after market close (the 2026-04-28
    # ASML "Semi Mania Backtracks" headline hit at 16:53 EDT, after close).
    # Set to 0 to disable the gate.
    DAILY_REVIEW_PCT: float = float(os.getenv("DAILY_REVIEW_PCT", "0.05"))

    # Lone-wolf BUY discount (Backlog 0.6, 2026-04-29):
    # When CNNReasoningAgent fires a BUY but fewer than LONEWOLF_MIN_CORROBORATORS
    # other agents agree on the same symbol, multiply the position size by
    # LONEWOLF_MULTIPLIER. CNN's WFE has been negative across retrains, so
    # uncorroborated BUYs are exactly the trades most likely to be noise-driven
    # false positives. Halving the size limits damage when the model is wrong
    # without blocking lone-wolf trades entirely.
    LONEWOLF_MIN_CORROBORATORS: int   = int(os.getenv("LONEWOLF_MIN_CORROBORATORS", "2"))
    LONEWOLF_MULTIPLIER:        float = float(os.getenv("LONEWOLF_MULTIPLIER", "0.5"))

    # CNN BUY guards (added 2026-05-04 after the WFE gate stopped firing
    # — when mean_wfe flipped positive on the XGBoost upgrade, the gate
    # which was the de-facto circuit breaker stopped suppressing BUYs and
    # the agent fired 38 BUYs in one day, taking $2.1k of unrealized loss.
    # These two are tighter, signal-independent guards.)
    #
    # CNN_PAUSE_UPNL_DRAWDOWN_PCT — pause CNN BUYs when total uPnL across
    # CNN's open positions falls below this fraction of agent portfolio
    # value. -0.02 = -2%. SELLs always pass (we always allow exits).
    CNN_PAUSE_UPNL_DRAWDOWN_PCT: float = float(os.getenv(
        "CNN_PAUSE_UPNL_DRAWDOWN_PCT", "-0.02"))
    # CNN_BUY_THRESHOLD_BASE — minimum Ollama confidence to fire a BUY in
    # bull/neutral regimes (regime_gate adds 0.15-0.20 for bear/high_vol).
    # Was a hardcoded 0.50; raised to 0.65 after the over-buying incident.
    CNN_BUY_THRESHOLD_BASE: float = float(os.getenv(
        "CNN_BUY_THRESHOLD_BASE", "0.65"))

    # Cloud-Claude model selection per call site (added 2026-05-05).
    # ScannerAgent's job is "rank symbols by interest" — Haiku 4.5 is
    # plenty for that and ~15× cheaper than Opus 4.6 ($1/M vs $15/M
    # input, $5/M vs $75/M output). Saves ~85% on the scanner's
    # token spend (~$3.40/day → ~$0.50/day at today's volume).
    # Override to claude-opus-4-6 if scanner-decision quality regresses.
    SCANNER_CLAUDE_MODEL: str = os.getenv(
        "SCANNER_CLAUDE_MODEL", "claude-haiku-4-5-20251001")
    # ClaudeAgent kept on Opus by default — fewer calls, higher-stakes
    # per-symbol decisions where Opus's reasoning depth matters.
    CLAUDE_AGENT_MODEL: str = os.getenv(
        "CLAUDE_AGENT_MODEL", "claude-opus-4-6")

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
    # Ensemble weights — adaptive vote aggregation in EnsembleAgent.
    # 2026-05-08: OllamaAgent split out from ClaudeAgent (was a hidden dispatch
    # mode inside ClaudeAgent). Re-balanced ClaudeAgent 0.29 → 0.20 and gave
    # OllamaAgent 0.09 — same total cloud/local share as before, now expressed
    # as two independent voters. Adaptive performance weighting will adjust
    # these from base values over time.
    ENSEMBLE_WEIGHTS = {
        "ClaudeAgent":            0.20,
        "OllamaAgent":            0.09,
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
