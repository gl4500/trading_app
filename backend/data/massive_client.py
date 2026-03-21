"""
Massive.com financial data client.

Provides three access methods:
  1. REST API  — real-time + recent historical data
  2. WebSocket — live streaming (optional, not used in main loop)
  3. S3 Flat Files — bulk historical downloads via boto3

REST coverage:
  Stocks    : bars (OHLCV), snapshot (latest), news, technicals, fundamentals
  Options   : flow alerts, snapshots
  Indices   : bars, snapshots
  Forex     : bars, quotes
  Economy   : treasury yields, inflation, labor market (macro context for AI)

All methods degrade gracefully — if Massive is unavailable or the key is
missing, they return empty results so the rest of the pipeline is unaffected.

──────────────────────────────────────────────────────────────────────────────
TODO (verify against your Massive dashboard before first run):
  1. Confirm BASE_URL  — check API > Getting Started in your dashboard
  2. Confirm auth header — likely "Authorization: Bearer {key}" or "X-Api-Key"
  3. Confirm endpoint paths — e.g. /v1/stocks/{ticker}/aggregates vs /stocks/...
  4. Set MASSIVE_S3_BUCKET to your assigned bucket name
──────────────────────────────────────────────────────────────────────────────
"""
import asyncio
import io
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import httpx
import pandas as pd

from config import config

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

# TODO: confirm base URL from your Massive dashboard → API > Getting Started
_BASE_URL = "https://api.massive.com/v1"

# Cache TTLs (seconds)
_TTL_PRICE   = 10
_TTL_BARS    = 60
_TTL_NEWS    = 90
_TTL_OPTIONS = 60
_TTL_ECONOMY = 3600   # macro data changes rarely

_NET_ERRORS = (
    httpx.ConnectError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.PoolTimeout,
    OSError,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _auth_headers() -> Dict[str, str]:
    """Return auth headers for Massive REST API.

    TODO: if your dashboard shows a different header (e.g. 'X-Api-Key'),
    change the key name below.
    """
    return {
        "Authorization": f"Bearer {config.MASSIVE_API_KEY}",
        "Accept": "application/json",
        "User-Agent": "TradingApp/1.0",
    }


def _date_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


# ── Main client class ─────────────────────────────────────────────────────────

class MassiveClient:
    """Async client for Massive.com — REST, WebSocket, and S3 flat files."""

    def __init__(self):
        self._bars_cache:    Dict[str, tuple] = {}  # key → (ts, DataFrame)
        self._price_cache:   Dict[str, tuple] = {}  # symbol → (ts, float)
        self._news_cache:    Dict[str, tuple] = {}  # symbol → (ts, list)
        self._options_cache: Dict[str, tuple] = {}  # "flow" → (ts, list)
        self._economy_cache: Dict[str, tuple] = {}  # indicator → (ts, dict)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _is_available(self) -> bool:
        return bool(config.MASSIVE_API_KEY)

    def _cached(self, store: Dict, key: str, ttl: int):
        if key in store:
            ts, data = store[key]
            if time.time() - ts < ttl:
                return data
        return None

    def _store(self, store: Dict, key: str, data) -> None:
        store[key] = (time.time(), data)

    # ── REST: Stocks — Bars (OHLCV) ───────────────────────────────────────────

    async def get_bars(
        self,
        symbol: str,
        days: int = 60,
        timespan: str = "day",
    ) -> pd.DataFrame:
        """Fetch OHLCV bars for a single symbol.

        TODO: adjust endpoint path to match your Massive plan:
          /v1/stocks/{ticker}/aggregates?timespan=day&from=...&to=...
        """
        if not self._is_available():
            return pd.DataFrame()

        key = f"{symbol}|{timespan}|{days}"
        cached = self._cached(self._bars_cache, key, _TTL_BARS)
        if cached is not None:
            return cached.copy()

        from_date = _date_str(datetime.utcnow() - timedelta(days=days))
        to_date   = _date_str(datetime.utcnow())

        # TODO: verify exact endpoint path from docs
        url = f"{_BASE_URL}/stocks/{symbol.upper()}/aggregates"
        params = {
            "timespan":  timespan,
            "from":      from_date,
            "to":        to_date,
            "limit":     min(days, 500),
            "adjusted":  "true",
        }

        try:
            async with httpx.AsyncClient(timeout=15, headers=_auth_headers()) as client:
                resp = await client.get(url, params=params)
                if resp.status_code == 401:
                    logger.warning("MassiveClient: invalid API key (401)")
                    return pd.DataFrame()
                if resp.status_code != 200:
                    logger.debug(f"MassiveClient bars {symbol}: HTTP {resp.status_code}")
                    return pd.DataFrame()

                data = resp.json()
                # TODO: adjust key names if Massive uses different field names
                results = data.get("results", data.get("bars", data.get("data", [])))
                if not results:
                    return pd.DataFrame()

                df = pd.DataFrame(results)
                # Normalise column names — Massive likely uses standard OHLCV names
                col_map = {
                    "t": "timestamp", "o": "open", "h": "high",
                    "l": "low",        "c": "close", "v": "volume",
                    "vw": "vwap",
                }
                df.rename(columns={k: v for k, v in col_map.items() if k in df.columns}, inplace=True)

                required = {"open", "high", "low", "close"}
                if not required.issubset(df.columns):
                    logger.debug(f"MassiveClient: unexpected bars schema for {symbol}: {list(df.columns)}")
                    return pd.DataFrame()

                df = df.sort_values("timestamp").reset_index(drop=True) if "timestamp" in df.columns else df
                self._store(self._bars_cache, key, df)
                return df.copy()

        except _NET_ERRORS as e:
            logger.debug(f"MassiveClient bars {symbol}: {type(e).__name__}")
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"MassiveClient bars {symbol}: {e}")
            return pd.DataFrame()

    async def get_bars_multi(
        self,
        symbols: List[str],
        days: int = 60,
        timespan: str = "day",
    ) -> Dict[str, pd.DataFrame]:
        """Fetch OHLCV bars for multiple symbols concurrently."""
        tasks = [self.get_bars(sym, days, timespan) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {
            sym: (res if isinstance(res, pd.DataFrame) else pd.DataFrame())
            for sym, res in zip(symbols, results)
        }

    # ── REST: Stocks — Snapshot (latest price) ────────────────────────────────

    async def get_snapshot(self, symbol: str) -> Dict:
        """Get latest price snapshot for a symbol.

        TODO: verify endpoint — likely /v1/stocks/{ticker}/snapshot
        """
        if not self._is_available():
            return {}

        cached = self._cached(self._price_cache, symbol, _TTL_PRICE)
        if cached is not None:
            return cached

        url = f"{_BASE_URL}/stocks/{symbol.upper()}/snapshot"
        try:
            async with httpx.AsyncClient(timeout=10, headers=_auth_headers()) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return {}
                data = resp.json()
                snap = data.get("results", data.get("snapshot", data))
                self._store(self._price_cache, symbol, snap)
                return snap
        except Exception as e:
            logger.debug(f"MassiveClient snapshot {symbol}: {e}")
            return {}

    async def get_snapshots(self, symbols: List[str]) -> Dict[str, float]:
        """Get latest prices for multiple symbols.

        Returns {symbol: price} dict — same format as alpaca_client.
        TODO: Massive may offer a batch snapshot endpoint — check docs.
        """
        if not self._is_available():
            return {}

        # Try batch endpoint first
        url = f"{_BASE_URL}/stocks/snapshots"
        params = {"tickers": ",".join(s.upper() for s in symbols)}
        try:
            async with httpx.AsyncClient(timeout=15, headers=_auth_headers()) as client:
                resp = await client.get(url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    results = data.get("results", data.get("tickers", {}))
                    prices: Dict[str, float] = {}
                    if isinstance(results, dict):
                        for sym, snap in results.items():
                            # TODO: adjust price field name if needed
                            price = (
                                snap.get("last_trade", {}).get("price")
                                or snap.get("day", {}).get("close")
                                or snap.get("close")
                                or snap.get("price")
                                or 0
                            )
                            if price:
                                prices[sym.upper()] = float(price)
                    elif isinstance(results, list):
                        for snap in results:
                            sym = (snap.get("ticker") or snap.get("symbol") or "").upper()
                            price = snap.get("close") or snap.get("price") or 0
                            if sym and price:
                                prices[sym] = float(price)
                    return prices
        except Exception as e:
            logger.debug(f"MassiveClient batch snapshot: {e}")

        # Fallback: per-symbol
        tasks = [self.get_snapshot(sym) for sym in symbols]
        snaps = await asyncio.gather(*tasks, return_exceptions=True)
        prices = {}
        for sym, snap in zip(symbols, snaps):
            if isinstance(snap, dict):
                price = snap.get("close") or snap.get("price") or 0
                if price:
                    prices[sym.upper()] = float(price)
        return prices

    # ── REST: Stocks — News ───────────────────────────────────────────────────

    async def get_news(self, symbol: str, limit: int = 10) -> List[Dict]:
        """Get recent news articles for a symbol.

        TODO: verify endpoint — likely /v1/stocks/{ticker}/news
        Returns list of {headline, summary, source, url, published_at}.
        """
        if not self._is_available():
            return []

        cached = self._cached(self._news_cache, symbol, _TTL_NEWS)
        if cached is not None:
            return cached

        url = f"{_BASE_URL}/stocks/{symbol.upper()}/news"
        params = {"limit": limit}
        try:
            async with httpx.AsyncClient(timeout=10, headers=_auth_headers()) as client:
                resp = await client.get(url, params=params)
                if resp.status_code != 200:
                    return []
                data = resp.json()
                articles = data.get("results", data.get("news", data.get("articles", [])))
                news = []
                for a in articles:
                    news.append({
                        "headline":     a.get("title") or a.get("headline") or "",
                        "summary":      a.get("description") or a.get("summary") or "",
                        "source":       a.get("publisher", {}).get("name") if isinstance(a.get("publisher"), dict) else a.get("source") or "Massive News",
                        "url":          a.get("article_url") or a.get("url") or "",
                        "published_at": a.get("published_utc") or a.get("published_at") or "",
                    })
                self._store(self._news_cache, symbol, news)
                return news
        except Exception as e:
            logger.debug(f"MassiveClient news {symbol}: {e}")
            return []

    async def get_news_multi(self, symbols: List[str], limit: int = 5) -> Dict[str, List[Dict]]:
        """Get news for multiple symbols concurrently."""
        tasks = [self.get_news(sym, limit) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {
            sym: (res if isinstance(res, list) else [])
            for sym, res in zip(symbols, results)
        }

    # ── REST: Options — Flow Alerts ───────────────────────────────────────────

    async def get_options_flow(
        self,
        symbols: List[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """Fetch unusual options flow / large block trades.

        TODO: verify endpoint — check Options > Trades & Quotes in docs.
        Returns list of catalyst-compatible dicts.
        """
        if not self._is_available():
            return []

        key = f"flow|{','.join(sorted(symbols)) if symbols else 'all'}"
        cached = self._cached(self._options_cache, key, _TTL_OPTIONS)
        if cached is not None:
            return cached

        # TODO: verify endpoint path
        url = f"{_BASE_URL}/options/flow"
        params = {"limit": limit}
        if symbols:
            params["tickers"] = ",".join(s.upper() for s in symbols)

        results = []
        try:
            async with httpx.AsyncClient(timeout=15, headers=_auth_headers()) as client:
                resp = await client.get(url, params=params)
                if resp.status_code != 200:
                    return []
                data = resp.json()
                flows = data.get("results", data.get("flow", data.get("data", [])))
                sym_set = {s.upper() for s in symbols} if symbols else None

                for f in flows:
                    ticker = (f.get("ticker") or f.get("symbol") or "").upper()
                    if sym_set and ticker not in sym_set:
                        continue

                    side    = (f.get("side") or f.get("sentiment") or "").upper()
                    premium = f.get("premium") or f.get("total_premium") or f.get("value") or 0
                    expiry  = f.get("expiry") or f.get("expiration_date") or ""
                    strike  = f.get("strike_price") or f.get("strike") or ""
                    oi_flag = f.get("open_interest_flag") or ""

                    sentiment = "bullish" if "CALL" in side else "bearish" if "PUT" in side else "unusual"
                    headline  = (
                        f"Massive Options Flow: {ticker} {side} ${premium:,.0f} premium"
                        if isinstance(premium, (int, float)) else
                        f"Massive Options Flow: {ticker} {side} large block"
                    )
                    summary = (
                        f"{ticker} {side} sweep — strike ${strike}, expiry {expiry}. "
                        f"Premium: ${premium:,.0f}. {oi_flag}".strip()
                    )

                    try:
                        from data.policy_monitor import score_headline
                        scored = score_headline(headline, summary)
                    except Exception:
                        scored = {"score": 2, "category": "catalyst", "sectors": [], "reason": ""}

                    results.append({
                        "headline":    headline,
                        "summary":     summary,
                        "source":      "Massive / Options Flow",
                        "date":        datetime.utcnow().isoformat(),
                        "symbol":      ticker,
                        "score":       max(scored.get("score", 0), 2),
                        "category":    "catalyst",
                        "sectors":     scored.get("sectors", []),
                        "reason":      f"{sentiment} options flow",
                        "detected_at": datetime.utcnow().isoformat(),
                        "premium":     premium,
                        "side":        side,
                    })

            self._store(self._options_cache, key, results)
            return results

        except Exception as e:
            logger.debug(f"MassiveClient options flow: {e}")
            return []

    # ── REST: Economy — Macro Context ─────────────────────────────────────────

    async def get_economy(self, indicator: str) -> Dict:
        """Fetch a single economy indicator.

        indicator: 'treasury_yields' | 'inflation' | 'labor'
        TODO: verify exact endpoint paths from Economy section in docs.
        """
        if not self._is_available():
            return {}

        cached = self._cached(self._economy_cache, indicator, _TTL_ECONOMY)
        if cached is not None:
            return cached

        # TODO: verify paths
        endpoint_map = {
            "treasury_yields": "/economy/treasury-yields",
            "inflation":       "/economy/inflation",
            "labor":           "/economy/labor",
        }
        path = endpoint_map.get(indicator)
        if not path:
            return {}

        url = f"{_BASE_URL}{path}"
        try:
            async with httpx.AsyncClient(timeout=15, headers=_auth_headers()) as client:
                resp = await client.get(url, params={"limit": 1})
                if resp.status_code != 200:
                    return {}
                data = resp.json()
                result = data.get("results", data.get("data", data))
                if isinstance(result, list) and result:
                    result = result[0]
                self._store(self._economy_cache, indicator, result)
                return result
        except Exception as e:
            logger.debug(f"MassiveClient economy {indicator}: {e}")
            return {}

    async def get_macro_context(self) -> str:
        """Fetch all economy indicators and return a formatted string for AI prompts."""
        if not self._is_available():
            return ""

        yields_task   = self.get_economy("treasury_yields")
        inflation_task = self.get_economy("inflation")
        labor_task    = self.get_economy("labor")

        yields, inflation, labor = await asyncio.gather(
            yields_task, inflation_task, labor_task, return_exceptions=True
        )

        lines = ["## Macro Context (Massive.com)"]

        # Treasury yields
        if isinstance(yields, dict) and yields:
            y2  = yields.get("year_2")  or yields.get("2y")  or yields.get("2_year")
            y10 = yields.get("year_10") or yields.get("10y") or yields.get("10_year")
            y30 = yields.get("year_30") or yields.get("30y") or yields.get("30_year")
            parts = []
            if y2:  parts.append(f"2Y={float(y2):.2f}%")
            if y10: parts.append(f"10Y={float(y10):.2f}%")
            if y30: parts.append(f"30Y={float(y30):.2f}%")
            if parts:
                lines.append(f"Treasury Yields: {', '.join(parts)}")

        # Inflation
        if isinstance(inflation, dict) and inflation:
            rate = inflation.get("value") or inflation.get("rate") or inflation.get("cpi")
            date = inflation.get("date") or inflation.get("period") or ""
            if rate:
                lines.append(f"Inflation (CPI): {float(rate):.1f}%  [{date}]")

        # Labor
        if isinstance(labor, dict) and labor:
            ue   = labor.get("unemployment_rate") or labor.get("value") or labor.get("rate")
            date = labor.get("date") or labor.get("period") or ""
            if ue:
                lines.append(f"Unemployment: {float(ue):.1f}%  [{date}]")

        if len(lines) == 1:
            return ""  # no data fetched
        return "\n".join(lines)

    # ── S3 Flat File Access ───────────────────────────────────────────────────

    def _get_s3_client(self):
        """Return a boto3 S3 client using Massive credentials.

        Requires boto3: pip install boto3
        Install in the self-contained runtime:
          runtime/python/python.exe -m pip install boto3 --target site-packages/

        TODO: set in .env:
          MASSIVE_S3_BUCKET      — your assigned bucket name (ask Massive support)
          MASSIVE_S3_ACCESS_KEY  — AWS access key ID
          MASSIVE_S3_SECRET_KEY  — AWS secret access key
          MASSIVE_S3_REGION      — bucket region (default: us-east-1)
        """
        try:
            import boto3
        except ImportError:
            logger.warning(
                "MassiveClient S3: boto3 not installed. "
                "Run: runtime/python/python.exe -m pip install boto3 --target site-packages/"
            )
            return None

        if not all([config.MASSIVE_S3_ACCESS_KEY, config.MASSIVE_S3_SECRET_KEY, config.MASSIVE_S3_BUCKET]):
            logger.debug("MassiveClient S3: credentials not configured (MASSIVE_S3_* vars)")
            return None

        return boto3.client(
            "s3",
            region_name=config.MASSIVE_S3_REGION or "us-east-1",
            aws_access_key_id=config.MASSIVE_S3_ACCESS_KEY,
            aws_secret_access_key=config.MASSIVE_S3_SECRET_KEY,
        )

    async def list_flat_files(
        self,
        asset_class: str = "stocks",
        symbol: str = None,
        prefix: str = None,
    ) -> List[str]:
        """List available flat files in the Massive S3 bucket.

        asset_class: 'stocks' | 'options' | 'futures' | 'indices' | 'forex' | 'crypto'
        symbol:      optional ticker to filter by (e.g. 'AAPL')
        prefix:      override auto-built prefix entirely

        TODO: confirm S3 path format from Massive docs / support.
        Assumed: {bucket}/{asset_class}/daily/{symbol}/
        """
        s3 = await asyncio.to_thread(self._get_s3_client)
        if not s3:
            return []

        if prefix is None:
            prefix = f"{asset_class}/daily/"
            if symbol:
                prefix += f"{symbol.upper()}/"

        try:
            paginator = s3.get_paginator("list_objects_v2")
            keys = []
            async for page in asyncio.to_thread(
                lambda: list(paginator.paginate(Bucket=config.MASSIVE_S3_BUCKET, Prefix=prefix))
            ):
                for obj in page.get("Contents", []):
                    keys.append(obj["Key"])
            return keys
        except Exception as e:
            logger.error(f"MassiveClient S3 list ({prefix}): {e}")
            return []

    async def download_flat_file(
        self,
        s3_key: str,
        file_format: str = "csv",
    ) -> pd.DataFrame:
        """Download a single flat file from S3 and return as DataFrame.

        s3_key:      full S3 object key, e.g. 'stocks/daily/AAPL/2024-01-15.csv'
        file_format: 'csv' | 'parquet'

        TODO: confirm file format from Massive docs (CSV or Parquet).
        """
        s3 = await asyncio.to_thread(self._get_s3_client)
        if not s3:
            return pd.DataFrame()

        try:
            def _download():
                obj = s3.get_object(Bucket=config.MASSIVE_S3_BUCKET, Key=s3_key)
                body = obj["Body"].read()
                if file_format == "parquet":
                    return pd.read_parquet(io.BytesIO(body))
                else:
                    return pd.read_csv(io.BytesIO(body))

            df = await asyncio.to_thread(_download)
            logger.info(f"MassiveClient S3: downloaded {s3_key} → {len(df)} rows")
            return df

        except Exception as e:
            logger.error(f"MassiveClient S3 download ({s3_key}): {e}")
            return pd.DataFrame()

    async def download_history(
        self,
        symbol: str,
        asset_class: str = "stocks",
        from_date: str = None,
        to_date: str = None,
        file_format: str = "csv",
    ) -> pd.DataFrame:
        """Download and concatenate multiple daily flat files for a symbol.

        from_date / to_date: 'YYYY-MM-DD' strings. Defaults to last 60 days.
        Returns combined DataFrame sorted by date ascending.
        """
        if from_date is None:
            from_date = _date_str(datetime.utcnow() - timedelta(days=60))
        if to_date is None:
            to_date = _date_str(datetime.utcnow())

        all_keys = await self.list_flat_files(asset_class, symbol)
        if not all_keys:
            logger.debug(f"MassiveClient S3: no files found for {symbol}")
            return pd.DataFrame()

        # Filter by date range — assumes key contains YYYY-MM-DD somewhere
        filtered = []
        for key in all_keys:
            for part in key.replace("/", "_").replace(".", "_").split("_"):
                if len(part) == 10 and part.count("-") == 2:
                    if from_date <= part <= to_date:
                        filtered.append(key)
                    break

        if not filtered:
            # Fall back to all keys if date parsing failed
            filtered = all_keys

        tasks = [self.download_flat_file(key, file_format) for key in filtered]
        frames = await asyncio.gather(*tasks, return_exceptions=True)
        valid = [f for f in frames if isinstance(f, pd.DataFrame) and not f.empty]

        if not valid:
            return pd.DataFrame()

        combined = pd.concat(valid, ignore_index=True)

        # Normalise and sort
        for col in ("date", "timestamp", "t"):
            if col in combined.columns:
                combined = combined.sort_values(col).reset_index(drop=True)
                break

        logger.info(f"MassiveClient S3: {symbol} — {len(combined)} rows from {len(valid)} files")
        return combined


# ── Module-level singleton ────────────────────────────────────────────────────

massive_client = MassiveClient()
