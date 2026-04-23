"""
News Service: fetches recent news headlines from Alpaca's News API
and caches them to avoid hammering the API every cycle.

Returns per-symbol news summaries ready for injection into agent prompts.

Resilience:
  * 15 s per-attempt timeout ceiling (asyncio.wait_for)
  * One automatic retry on transient failures (5xx, ConnectTimeout, ReadTimeout)
  * Circuit breaker: after BREAKER_THRESHOLD consecutive failures the service
    stops calling upstream for BREAKER_COOLDOWN_SEC and serves stale cache
    or empty lists. Resets on the next successful fetch.
  * Failures log at WARNING (not ERROR) since callers receive a graceful
    fallback (stale cache or empty list).
"""
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from alpaca.data.historical.news import NewsClient
from alpaca.data.requests import NewsRequest

from config import config

logger = logging.getLogger(__name__)

# Cache news for 90 seconds — near real-time without hammering the API
NEWS_CACHE_TTL = 90
# How many days back to look for news
NEWS_LOOKBACK_DAYS = 1
# Max articles per symbol to include in prompt (reduced from 5 to cut token count)
MAX_ARTICLES_PER_SYMBOL = 3

# Resilience knobs
FETCH_TIMEOUT_SEC    = 15.0   # per-attempt ceiling (asyncio.wait_for)
RETRY_DELAY_SEC      = 0.5    # backoff between attempt 1 and attempt 2
BREAKER_THRESHOLD    = 5      # consecutive failures before opening
BREAKER_COOLDOWN_SEC = 60.0   # how long the breaker stays open

# Substrings that mark an exception as transient and worth retrying once
_RETRYABLE_MARKERS = (
    "502", "503", "504",
    "bad gateway", "service unavailable", "gateway timeout",
    "connecttimeout", "readtimeout", "timed out", "timeout",
)


def _is_retryable(exc: BaseException) -> bool:
    """Return True if `exc` looks like a transient upstream failure."""
    msg = str(exc).lower()
    return any(marker in msg for marker in _RETRYABLE_MARKERS)


class NewsService:
    def __init__(self):
        self._client = None
        self._cache: Dict[str, tuple] = {}  # symbol -> (timestamp, [articles])
        self._sem = asyncio.Semaphore(8)    # cap concurrent Alpaca connections below pool size
        # Circuit-breaker state
        self._consecutive_failures = 0
        self._breaker_open_until = 0.0      # epoch seconds; 0 = closed

    def _get_client(self):
        if self._client is None:
            self._client = NewsClient(
                api_key=config.ALPACA_API_KEY,
                secret_key=config.ALPACA_SECRET_KEY,
            )
        return self._client

    def _fetch_news_sync(self, symbol: str) -> List[Dict]:
        """Synchronous fetch — called via asyncio.to_thread."""
        client = self._get_client()
        start = datetime.now(timezone.utc) - timedelta(days=NEWS_LOOKBACK_DAYS)
        request = NewsRequest(
            symbols=symbol,
            limit=MAX_ARTICLES_PER_SYMBOL,
            start=start,
        )
        result = client.get_news(request)
        articles = result.data.get("news", [])
        return [
            {
                "headline": a.headline,
                "summary": (a.summary or "").strip()[:150],
                "source": a.source,
                "date": a.created_at.strftime("%Y-%m-%d %H:%M") if a.created_at else "",
            }
            for a in articles
        ]

    # ── Circuit breaker ─────────────────────────────────────────────────────

    def _breaker_is_open(self) -> bool:
        return time.time() < self._breaker_open_until

    def _record_success(self):
        self._consecutive_failures = 0
        self._breaker_open_until = 0.0

    def _record_failure(self):
        self._consecutive_failures += 1
        if self._consecutive_failures >= BREAKER_THRESHOLD and not self._breaker_is_open():
            self._breaker_open_until = time.time() + BREAKER_COOLDOWN_SEC
            logger.warning(
                "NewsService: circuit OPEN after %d consecutive failures (cooldown %ds)",
                self._consecutive_failures, int(BREAKER_COOLDOWN_SEC),
            )

    # ── Fetch with retry + timeout ─────────────────────────────────────────

    async def _fetch_with_retry(self, symbol: str) -> List[Dict]:
        last_exc: BaseException | None = None
        for attempt in (1, 2):
            try:
                async with self._sem:
                    return await asyncio.wait_for(
                        asyncio.to_thread(self._fetch_news_sync, symbol),
                        timeout=FETCH_TIMEOUT_SEC,
                    )
            except asyncio.TimeoutError as e:
                last_exc = e
                if attempt == 1:
                    await asyncio.sleep(RETRY_DELAY_SEC)
                    continue
                raise TimeoutError(f"fetch timed out after {FETCH_TIMEOUT_SEC}s") from e
            except Exception as e:
                last_exc = e
                if attempt == 1 and _is_retryable(e):
                    await asyncio.sleep(RETRY_DELAY_SEC)
                    continue
                raise
        # Defensive — loop above always returns or raises
        raise last_exc  # type: ignore[misc]  # pragma: no cover

    # ── Public API ─────────────────────────────────────────────────────────

    async def get_news(self, symbol: str) -> List[Dict]:
        """Return cached news for a symbol, refreshing if stale.

        Falls back to stale cache (then empty list) on upstream failure or
        when the circuit breaker is open.
        """
        now = time.time()
        if symbol in self._cache:
            ts, articles = self._cache[symbol]
            if now - ts < NEWS_CACHE_TTL:
                return articles

        # Breaker open — skip upstream entirely
        if self._breaker_is_open():
            if symbol in self._cache:
                return self._cache[symbol][1]
            return []

        try:
            articles = await self._fetch_with_retry(symbol)
            self._cache[symbol] = (now, articles)
            self._record_success()
            return articles
        except Exception as e:
            logger.warning("NewsService: failed to fetch news for %s: %s", symbol, e)
            self._record_failure()
            if symbol in self._cache:
                return self._cache[symbol][1]
            return []

    async def get_news_multi(self, symbols: List[str]) -> Dict[str, List[Dict]]:
        """Fetch news for multiple symbols concurrently."""
        tasks = [self.get_news(sym) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {
            sym: (res if not isinstance(res, Exception) else [])
            for sym, res in zip(symbols, results)
        }

    def format_for_prompt(self, symbol: str, articles: List[Dict]) -> str:
        """Format news articles as a concise text block for prompt injection."""
        if not articles:
            return f"{symbol}: No recent news."

        lines = [f"{symbol} Recent News ({len(articles)} articles):"]
        for a in articles:
            headline = a.get("headline", "")
            summary = a.get("summary", "")
            source = a.get("source", "")
            date = a.get("date") or a.get("published_at", "")
            if summary:
                lines.append(f"  [{date}] {headline} (via {source})\n    → {summary}")
            else:
                lines.append(f"  [{date}] {headline} (via {source})")
        return "\n".join(lines)


news_service = NewsService()
