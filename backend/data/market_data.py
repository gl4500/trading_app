"""
Market data service: fetches and caches OHLCV data from Alpaca.
Shared across all agents to minimize API calls.
"""
import asyncio
import logging
import time
from typing import Dict, List, Optional
import pandas as pd
import numpy as np

from config import config
from trading.alpaca_client import alpaca_client
from data.news_service import news_service
from data import technicals
from data.signal_aggregator import get_composite_signal

logger = logging.getLogger(__name__)


class MarketDataCache:
    """Thread-safe in-memory cache for market data."""

    def __init__(self, ttl_seconds: int = None):
        self.ttl = ttl_seconds if ttl_seconds is not None else config.DATA_CACHE_SECONDS
        self._cache: Dict[str, tuple] = {}  # key -> (timestamp, data)
        self._lock = asyncio.Lock()

    def _make_key(self, *args) -> str:
        return "|".join(str(a) for a in args)

    async def get(self, key: str):
        async with self._lock:
            if key in self._cache:
                ts, data = self._cache[key]
                if time.time() - ts < self.ttl:
                    return data
        return None

    async def set(self, key: str, data) -> None:
        async with self._lock:
            self._cache[key] = (time.time(), data)

    async def clear(self) -> None:
        async with self._lock:
            self._cache.clear()


_cache = MarketDataCache()


class MarketDataService:
    """Centralized market data provider with caching."""

    def __init__(self):
        self.watchlist = config.WATCHLIST
        self._price_cache: Dict[str, float] = {}
        self._bars_cache: Dict[str, pd.DataFrame] = {}
        self._last_price_fetch: float = 0
        self._price_cache_ttl: float = 10.0  # 10 seconds for prices
        self._bars_cache_ttl: float = 60.0   # 60 seconds for bars
        self._last_bars_fetch: Dict[str, float] = {}

    async def get_latest_prices(self, symbols: List[str] = None) -> Dict[str, float]:
        """Get latest prices with caching."""
        syms = symbols or self.watchlist
        now = time.time()

        if now - self._last_price_fetch < self._price_cache_ttl and self._price_cache:
            # Return cached subset
            return {s: self._price_cache[s] for s in syms if s in self._price_cache}

        try:
            prices = await alpaca_client.get_latest_prices(syms)
            if prices:
                self._price_cache.update(prices)
                self._last_price_fetch = now
            return prices
        except Exception as e:
            logger.error(f"Error fetching prices: {e}")
            return self._price_cache.copy()

    async def get_historical_bars(
        self,
        symbol: str,
        days: int = None,
        timeframe: str = "1Day",
    ) -> pd.DataFrame:
        """Get historical OHLCV bars with caching."""
        days = days or config.HISTORICAL_DAYS
        cache_key = f"{symbol}|{timeframe}|{days}"
        now = time.time()

        last_fetch = self._last_bars_fetch.get(cache_key, 0)
        if now - last_fetch < self._bars_cache_ttl and cache_key in self._bars_cache:
            return self._bars_cache[cache_key].copy()

        try:
            df = await alpaca_client.get_bars(symbol, timeframe=timeframe, limit=days)
            if df is not None and not df.empty:
                self._bars_cache[cache_key] = df
                self._last_bars_fetch[cache_key] = now
            return df if df is not None else pd.DataFrame()
        except Exception as e:
            logger.error(f"Error fetching bars for {symbol}: {e}")
            return self._bars_cache.get(cache_key, pd.DataFrame()).copy()

    async def get_all_bars(
        self,
        symbols: List[str] = None,
        days: int = None,
        timeframe: str = "1Day",
    ) -> Dict[str, pd.DataFrame]:
        """
        Get bars for all watchlist symbols in a single Alpaca API call.
        Falls back to per-symbol calls if the batch request fails.
        """
        syms = symbols or self.watchlist
        days = days or config.HISTORICAL_DAYS

        # Check which symbols need a fresh fetch
        now = time.time()
        stale = []
        fresh: Dict[str, pd.DataFrame] = {}
        for sym in syms:
            key = f"{sym}|{timeframe}|{days}"
            last_fetch = self._last_bars_fetch.get(key, 0)
            if now - last_fetch < self._bars_cache_ttl and key in self._bars_cache:
                fresh[sym] = self._bars_cache[key].copy()
            else:
                stale.append(sym)

        if stale:
            try:
                # Single API call for all stale symbols
                fetched = await alpaca_client.get_bars_multi(stale, timeframe=timeframe, limit=days)
                for sym, df in fetched.items():
                    key = f"{sym}|{timeframe}|{days}"
                    if df is not None and not df.empty:
                        self._bars_cache[key] = df
                        self._last_bars_fetch[key] = now
                    fresh[sym] = df if df is not None else pd.DataFrame()
            except Exception as exc:
                logger.error("Batch bars fetch failed, falling back to per-symbol: %s", exc)
                tasks = [self.get_historical_bars(sym, days, timeframe) for sym in stale]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for sym, result in zip(stale, results):
                    fresh[sym] = result if not isinstance(result, Exception) else pd.DataFrame()

        return fresh

    async def get_market_context(self, symbols: List[str] = None) -> Dict:
        """
        Get comprehensive market context for AI agents.
        Returns prices, recent bars, and basic stats.
        """
        syms = symbols or self.watchlist

        # Fetch in parallel
        prices_task = self.get_latest_prices(syms)
        bars_task   = self.get_all_bars(syms)
        news_task   = news_service.get_news_multi(syms)

        prices, all_bars, all_news = await asyncio.gather(prices_task, bars_task, news_task)

        # Composite signals (yfinance is slow — run concurrently per symbol)
        composite_tasks = [get_composite_signal(sym, all_news.get(sym, [])) for sym in syms]
        composite_results = await asyncio.gather(*composite_tasks, return_exceptions=True)
        all_composite = {
            sym: (res if not isinstance(res, Exception) else {})
            for sym, res in zip(syms, composite_results)
        }

        context = {}
        for sym in syms:
            bars = all_bars.get(sym, pd.DataFrame())
            price = prices.get(sym)

            if bars.empty:
                context[sym] = {
                    "symbol": sym,
                    "price":  price or 0,
                    "bars":   pd.DataFrame(),
                    "stats":  {},
                    "news":   all_news.get(sym, []),
                    "indicators": None,
                    "composite_signal": all_composite.get(sym, {}),
                }
                continue

            # Calculate basic stats
            close = bars["close"].values
            volume = bars["volume"].values if "volume" in bars.columns else np.zeros(len(close))

            stats = {
                "current_price": price or (float(close[-1]) if len(close) > 0 else 0),
                "price_change_1d": float((close[-1] - close[-2]) / close[-2] * 100) if len(close) > 1 else 0,
                "price_change_5d": float((close[-1] - close[-5]) / close[-5] * 100) if len(close) > 5 else 0,
                "price_change_20d": float((close[-1] - close[-20]) / close[-20] * 100) if len(close) > 20 else 0,
                "high_52w": float(close.max()),
                "low_52w": float(close.min()),
                "avg_volume_20d": float(volume[-20:].mean()) if len(volume) >= 20 else float(volume.mean()),
                "volume_today": float(volume[-1]) if len(volume) > 0 else 0,
            }

            # Recent bars for context
            recent_bars = []
            for _, row in bars.tail(10).iterrows():
                bar_dict = {
                    "date": str(row.get("timestamp", "")),
                    "open": float(row.get("open", 0)),
                    "high": float(row.get("high", 0)),
                    "low": float(row.get("low", 0)),
                    "close": float(row.get("close", 0)),
                    "volume": float(row.get("volume", 0)),
                }
                recent_bars.append(bar_dict)

            ind = technicals.compute(bars)
            context[sym] = {
                "symbol":    sym,
                "bars":      all_bars.get(sym, pd.DataFrame()),
                "recent_bars": recent_bars,
                "stats":     stats,
                "price":     stats["current_price"],
                "news":      all_news.get(sym, []),
                "indicators": ind,
                "composite_signal": all_composite.get(sym, {}),
            }

        return context

    async def clear_cache(self) -> None:
        """Clear all cached data."""
        self._price_cache.clear()
        self._bars_cache.clear()
        self._last_price_fetch = 0
        self._last_bars_fetch.clear()


# Singleton
market_data_service = MarketDataService()
