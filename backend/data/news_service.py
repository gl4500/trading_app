"""
News Service: fetches recent news headlines from Alpaca's News API
and caches them to avoid hammering the API every cycle.

Returns per-symbol news summaries ready for injection into agent prompts.
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


class NewsService:
    def __init__(self):
        self._client = None
        self._cache: Dict[str, tuple] = {}  # symbol -> (timestamp, [articles])
        self._sem = asyncio.Semaphore(8)    # cap concurrent Alpaca connections below pool size

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

    async def get_news(self, symbol: str) -> List[Dict]:
        """Return cached news for a symbol, refreshing if stale."""
        now = time.time()
        if symbol in self._cache:
            ts, articles = self._cache[symbol]
            if now - ts < NEWS_CACHE_TTL:
                return articles

        try:
            async with self._sem:
                articles = await asyncio.to_thread(self._fetch_news_sync, symbol)
            self._cache[symbol] = (now, articles)
            return articles
        except Exception as e:
            logger.error(f"NewsService: failed to fetch news for {symbol}: {e}")
            # Return stale cache if available
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
