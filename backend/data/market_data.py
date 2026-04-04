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
from data.massive_client import massive_client, format_greeks_for_prompt
from data.stooq_client import stooq_client
from data import sector_analysis

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
        """Get latest prices with caching. Alpaca is primary; Massive is fallback."""
        syms = symbols or self.watchlist
        now = time.time()

        if now - self._last_price_fetch < self._price_cache_ttl and self._price_cache:
            # Return cached subset
            return {s: self._price_cache[s] for s in syms if s in self._price_cache}

        # Primary: Alpaca
        try:
            prices = await alpaca_client.get_latest_prices(syms)
            if prices:
                self._price_cache.update(prices)
                self._last_price_fetch = now
                return prices
        except Exception as e:
            logger.debug(f"Alpaca prices failed, falling back to Massive: {e}")

        # Fallback: Massive.com snapshots
        try:
            prices = await massive_client.get_snapshots(syms)
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

        # Primary: Alpaca
        try:
            df = await alpaca_client.get_bars(symbol, timeframe=timeframe, limit=days)
            if df is not None and not df.empty:
                self._bars_cache[cache_key] = df
                self._last_bars_fetch[cache_key] = now
                return df
        except Exception as e:
            logger.debug(f"Alpaca bars failed for {symbol}: {e}")

        # Fallback 1: Stooq free historical data
        try:
            df_stooq = await stooq_client.get_bars(symbol, days=days)
            if df_stooq is not None and not df_stooq.empty:
                logger.debug(f"MarketData: using Stooq bars for {symbol}")
                self._bars_cache[cache_key] = df_stooq
                self._last_bars_fetch[cache_key] = now
                return df_stooq
        except Exception as e:
            logger.debug(f"Stooq bars fallback {symbol}: {e}")

        # Fallback 2: Massive.com (last resort — rate-limited on free tier)
        try:
            df_massive = await massive_client.get_bars(symbol, days=days)
            if df_massive is not None and not df_massive.empty:
                logger.debug(f"MarketData: using Massive bars for {symbol}")
                self._bars_cache[cache_key] = df_massive
                self._last_bars_fetch[cache_key] = now
                return df_massive
        except Exception as e:
            logger.debug(f"Massive bars fallback failed for {symbol}: {e}")

        return self._bars_cache.get(cache_key, pd.DataFrame()).copy()

    async def get_long_term_bars(
        self,
        symbols: List[str] = None,
        days: int = None,
    ) -> Dict[str, pd.DataFrame]:
        """
        Fetch multi-year OHLCV from Stooq for extended historical analysis.
        Uses a separate long-TTL cache key so it doesn't evict short-term bars.
        Primarily used by HistoricalTrendsAgent.
        """
        from config import config as _config
        syms = symbols or self.watchlist
        days = days or _config.STOOQ_LONG_TERM_DAYS

        now = time.time()
        stooq_ttl = 4 * 3600  # 4-hour cache for long-term bars
        fresh: Dict[str, pd.DataFrame] = {}
        stale: List[str] = []

        for sym in syms:
            key = f"{sym}|lt|{days}"
            last_fetch = self._last_bars_fetch.get(key, 0)
            if now - last_fetch < stooq_ttl and key in self._bars_cache:
                fresh[sym] = self._bars_cache[key].copy()
            else:
                stale.append(sym)

        if stale:
            fetched = await stooq_client.get_bars_multi(stale, days=days)
            for sym, df in fetched.items():
                key = f"{sym}|lt|{days}"
                if df is not None and not df.empty:
                    self._bars_cache[key] = df
                    self._last_bars_fetch[key] = now
                fresh[sym] = df if df is not None else pd.DataFrame()

        return fresh

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
            remaining = list(stale)

            # Primary: Alpaca batch
            try:
                fetched = await alpaca_client.get_bars_multi(remaining, timeframe=timeframe, limit=days)
                still_missing = []
                for sym in remaining:
                    df = fetched.get(sym)
                    if df is not None and not df.empty:
                        key = f"{sym}|{timeframe}|{days}"
                        self._bars_cache[key] = df
                        self._last_bars_fetch[key] = now
                        fresh[sym] = df
                    else:
                        still_missing.append(sym)
                remaining = still_missing
            except Exception as exc:
                logger.debug("Alpaca batch bars failed, falling back to Stooq: %s", exc)

            # Fallback 1: Stooq batch for symbols Alpaca didn't cover
            if remaining:
                try:
                    fetched = await stooq_client.get_bars_multi(remaining, days=days)
                    still_missing = []
                    for sym in remaining:
                        df = fetched.get(sym)
                        if df is not None and not df.empty:
                            key = f"{sym}|{timeframe}|{days}"
                            self._bars_cache[key] = df
                            self._last_bars_fetch[key] = now
                            fresh[sym] = df
                        else:
                            still_missing.append(sym)
                    remaining = still_missing
                except Exception as exc:
                    logger.debug("Stooq batch bars failed, falling back to Massive: %s", exc)

            # Fallback 2: Massive batch (last resort — rate-limited on free tier)
            if remaining:
                try:
                    fetched = await massive_client.get_bars_multi(remaining, days=days)
                    still_missing = []
                    for sym in remaining:
                        df = fetched.get(sym)
                        if df is not None and not df.empty:
                            key = f"{sym}|{timeframe}|{days}"
                            self._bars_cache[key] = df
                            self._last_bars_fetch[key] = now
                            fresh[sym] = df
                        else:
                            still_missing.append(sym)
                    remaining = still_missing
                except Exception as exc:
                    logger.debug("Massive batch bars failed: %s", exc)

            # Last resort: per-symbol fetch for anything still missing
            if remaining:
                tasks = [self.get_historical_bars(sym, days, timeframe) for sym in remaining]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for sym, result in zip(remaining, results):
                    fresh[sym] = result if not isinstance(result, Exception) else pd.DataFrame()

        return fresh

    async def get_market_context(self, symbols: List[str] = None) -> Dict:
        """
        Get comprehensive market context for AI agents.
        Returns prices, recent bars, and basic stats.
        """
        syms = symbols or self.watchlist

        # Fetch in parallel — Massive macro + news + Greeks alongside Alpaca + Stooq long-term
        prices_task         = self.get_latest_prices(syms)
        bars_task           = self.get_all_bars(syms)
        news_task           = news_service.get_news_multi(syms)
        macro_task          = massive_client.get_macro_context()
        massive_news_task   = massive_client.get_news_multi(syms, limit=5)
        long_term_bars_task = self.get_long_term_bars(syms)
        greeks_task         = massive_client.get_greeks_summary(syms)
        sector_task         = sector_analysis.get_sector_performance()

        prices, all_bars, all_news, macro_ctx, massive_news, all_long_term_bars, all_greeks, sector_perf = await asyncio.gather(
            prices_task, bars_task, news_task, macro_task, massive_news_task, long_term_bars_task, greeks_task, sector_task,
            return_exceptions=True,
        )
        if isinstance(all_long_term_bars, Exception):
            all_long_term_bars = {}
        if isinstance(macro_ctx, Exception):
            macro_ctx = ""
        if isinstance(massive_news, Exception):
            massive_news = {}
        if isinstance(all_greeks, Exception):
            all_greeks = {}
        if isinstance(sector_perf, Exception):
            sector_perf = {}

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
                alpaca_news_empty = all_news.get(sym, [])
                massive_news_empty = massive_news.get(sym, []) if isinstance(massive_news, dict) else []
                existing_hl = {n.get("headline", "") for n in alpaca_news_empty}
                lt_bars_empty = all_long_term_bars.get(sym, pd.DataFrame()) \
                    if isinstance(all_long_term_bars, dict) else pd.DataFrame()
                greeks_sym = all_greeks.get(sym, {}) if isinstance(all_greeks, dict) else {}
                svs = sector_analysis.get_stock_vs_sector(sym, None, sector_perf)
                context[sym] = {
                    "symbol":          sym,
                    "price":           price or 0,
                    "bars":            pd.DataFrame(),
                    "long_term_bars":  lt_bars_empty,
                    "stats":           {},
                    "news":            alpaca_news_empty + [n for n in massive_news_empty if n.get("headline", "") not in existing_hl],
                    "indicators":      None,
                    "composite_signal": all_composite.get(sym, {}),
                    "greeks":          greeks_sym,
                    "greeks_text":     format_greeks_for_prompt(sym, greeks_sym),
                    "sector_vs_market": svs,
                    "sector_context_text": sector_analysis.format_stock_sector_context(sym, svs),
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

            # Merge Alpaca news + Massive news (deduplicate by headline)
            alpaca_news   = all_news.get(sym, [])
            massive_sym_news = massive_news.get(sym, []) if isinstance(massive_news, dict) else []
            existing_headlines = {n.get("headline", "") for n in alpaca_news}
            merged_news = alpaca_news + [
                n for n in massive_sym_news
                if n.get("headline", "") not in existing_headlines
            ]

            lt_bars = all_long_term_bars.get(sym, pd.DataFrame()) \
                if isinstance(all_long_term_bars, dict) else pd.DataFrame()
            greeks_sym = all_greeks.get(sym, {}) if isinstance(all_greeks, dict) else {}
            stock_1d = stats.get("price_change_1d")
            svs = sector_analysis.get_stock_vs_sector(sym, stock_1d, sector_perf)

            context[sym] = {
                "symbol":           sym,
                "bars":             all_bars.get(sym, pd.DataFrame()),
                "long_term_bars":   lt_bars,
                "recent_bars":      recent_bars,
                "stats":            stats,
                "price":            stats["current_price"],
                "news":             merged_news,
                "indicators":       ind,
                "composite_signal": all_composite.get(sym, {}),
                "greeks":           greeks_sym,
                "greeks_text":      format_greeks_for_prompt(sym, greeks_sym),
                "sector_vs_market": svs,
                "sector_context_text": sector_analysis.format_stock_sector_context(sym, svs),
            }

        # Attach macro and sector context at the top level
        if macro_ctx:
            context["__massive_macro__"] = macro_ctx
        if sector_perf:
            context["__sector_context__"] = sector_perf

        return context

    async def clear_cache(self) -> None:
        """Clear all cached data."""
        self._price_cache.clear()
        self._bars_cache.clear()
        self._last_price_fetch = 0
        self._last_bars_fetch.clear()


# Singleton
market_data_service = MarketDataService()
