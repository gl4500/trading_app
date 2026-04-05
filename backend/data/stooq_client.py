"""
Stooq.com free historical data client.

Provides daily OHLCV going back to year 2000 (or earlier) for US equities
with no API key required.

URL format:  https://stooq.com/q/d/l/?s={symbol}.us&i=d
Response:    CSV — Date,Open,High,Low,Close,Volume

Design notes:
  - Long TTL cache (4 hours) — historical bars change once per day at most
  - Graceful degradation — returns empty DataFrame on any error
  - No rate limiter needed for typical usage (one fetch per symbol per session)
  - Works as a fallback when Alpaca/Massive don't cover the requested depth
"""
import asyncio
import io
import logging
import time
from typing import Dict, List

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

_BASE_URL = "https://stooq.com/q/d/l/"
_CACHE_TTL = 4 * 3600  # 4 hours — historical data only updates end-of-day

_NET_ERRORS = (
    httpx.ConnectError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.PoolTimeout,
    OSError,
)


class StooqClient:
    """Async client for Stooq.com free historical daily OHLCV data."""

    def __init__(self):
        self._cache: Dict[str, tuple] = {}   # key → (timestamp, DataFrame)

    # ── URL helper ────────────────────────────────────────────────────────────

    def _symbol_url(self, symbol: str) -> str:
        """Build the Stooq daily CSV URL for a US equity symbol."""
        return f"{_BASE_URL}?s={symbol.lower()}.us&i=d"

    # ── Cache helpers ─────────────────────────────────────────────────────────

    def _cached(self, key: str):
        if key in self._cache:
            ts, df = self._cache[key]
            if time.time() - ts < _CACHE_TTL:
                return df.copy()
        return None

    def _store(self, key: str, df: pd.DataFrame) -> None:
        self._cache[key] = (time.time(), df)

    # ── CSV parsing ───────────────────────────────────────────────────────────

    @staticmethod
    def _parse_csv(text: str) -> pd.DataFrame:
        """
        Parse Stooq CSV response into a normalised DataFrame.
        Returns empty DataFrame if the response is HTML (symbol not found)
        or otherwise unparseable.
        """
        if not text or text.lstrip().startswith("<"):
            return pd.DataFrame()

        try:
            df = pd.read_csv(io.StringIO(text))
        except Exception:
            return pd.DataFrame()

        # Normalise column names to lowercase
        df.columns = [c.strip().lower() for c in df.columns]

        # Require at minimum open/high/low/close
        required = {"open", "high", "low", "close"}
        if not required.issubset(df.columns):
            return pd.DataFrame()

        # Rename 'date' column if present (Stooq uses 'date')
        if "date" in df.columns:
            df["date"] = df["date"].astype(str)
            df = df.sort_values("date").reset_index(drop=True)

        # Coerce OHLCV to float
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Drop rows where close is NaN
        df = df.dropna(subset=["close"]).reset_index(drop=True)

        return df

    # ── Public API ────────────────────────────────────────────────────────────

    async def get_bars(self, symbol: str, days: int = 1250) -> pd.DataFrame:
        """
        Fetch daily OHLCV for a US equity symbol from Stooq.

        symbol: ticker (e.g. 'AAPL', 'SPY')
        days:   maximum number of trading days to return (tail of full history)

        Returns a DataFrame with columns: date, open, high, low, close, volume
        Sorted ascending by date.  Returns empty DataFrame on any error.
        """
        cache_key = f"{symbol.upper()}|{days}"
        cached = self._cached(cache_key)
        if cached is not None:
            return cached

        url = self._symbol_url(symbol)
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(url)

            if resp.status_code != 200:
                logger.debug(f"StooqClient: HTTP {resp.status_code} for {symbol}")
                return pd.DataFrame()

            df = self._parse_csv(resp.text)
            if df.empty:
                logger.debug(f"StooqClient: no data parsed for {symbol}")
                return pd.DataFrame()

            # Truncate to requested days (tail = most recent)
            if len(df) > days:
                df = df.tail(days).reset_index(drop=True)

            self._store(cache_key, df)
            logger.debug(f"StooqClient: {symbol} — {len(df)} bars fetched")
            return df.copy()

        except _NET_ERRORS as e:
            logger.debug(f"StooqClient: network error for {symbol}: {type(e).__name__}")
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"StooqClient: unexpected error for {symbol}: {e}")
            return pd.DataFrame()

    async def get_bars_multi(
        self,
        symbols: List[str],
        days: int = 1250,
    ) -> Dict[str, pd.DataFrame]:
        """
        Fetch daily OHLCV for multiple symbols concurrently.
        Returns {symbol: DataFrame} — always has an entry for every symbol.
        """
        if not symbols:
            return {}

        tasks = [self.get_bars(sym, days) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        return {
            sym: (res if isinstance(res, pd.DataFrame) else pd.DataFrame())
            for sym, res in zip(symbols, results)
        }


    async def get_macro_indicators(self) -> Dict:
        """
        Fetch key macro indicators from Stooq (no API key required).

        Returns a dict shaped::

            {
                "VIX":       {"price": 18.5, "pct_1d": 2.3},
                "10Y_Yield": {"price": 4.52, "pct_1d": 0.7},
                "Gold":      {"price": 2345.0, "pct_1d": 0.8},
                "DXY":       {"price": 104.2, "pct_1d": -0.2},
            }
        """
        symbols = {
            "VIX":       "^vix",
            "10Y_Yield": "ust10y.b",
            "Gold":      "gc.f",
            "DXY":       "usdx.f",
        }
        result: Dict = {}
        for label, sym in symbols.items():
            cache_key = f"macro|{sym}"
            cached = self._cached(cache_key)
            if cached is not None and not cached.empty:
                df = cached
            else:
                url = f"{_BASE_URL}?s={sym.lower()}&i=d"
                try:
                    async with httpx.AsyncClient(timeout=15) as client:
                        resp = await client.get(url)
                    if resp.status_code != 200:
                        continue
                    df = self._parse_csv(resp.text)
                    if df.empty:
                        continue
                    df = df.tail(5).reset_index(drop=True)
                    self._store(cache_key, df)
                except _NET_ERRORS as e:
                    logger.debug(f"StooqClient macro {label}: network error: {type(e).__name__}")
                    continue
                except Exception as e:
                    logger.debug(f"StooqClient macro {label}: error: {e}")
                    continue

            if df.empty or "close" not in df.columns:
                continue
            close = df["close"].values
            price = float(close[-1]) if len(close) >= 1 else None
            pct_1d = float((close[-1] - close[-2]) / close[-2] * 100) \
                if len(close) >= 2 and close[-2] != 0 else None
            if price is not None:
                result[label] = {
                    "price":  round(price, 4),
                    "pct_1d": round(pct_1d, 2) if pct_1d is not None else None,
                }
        return result


def format_macro_for_prompt(macro: Dict) -> str:
    """
    Format macro indicator dict into a compact prompt string.

    Example::

        VIX: 18.5 (+2.3%)  10Y Yield: 4.52% (+0.07%)  Gold: $2,345 (+0.8%)  DXY: 104.2 (-0.2%)
    """
    if not macro:
        return ""

    parts = []
    vix = macro.get("VIX", {})
    if vix.get("price") is not None:
        p = vix["price"]
        d = vix.get("pct_1d")
        chg = f" ({'+' if d >= 0 else ''}{d:.1f}%)" if d is not None else ""
        level = "elevated" if p > 25 else ("low" if p < 15 else "moderate")
        parts.append(f"VIX: {p:.1f}{chg} [{level} vol]")

    y10 = macro.get("10Y_Yield", {})
    if y10.get("price") is not None:
        p = y10["price"]
        d = y10.get("pct_1d")
        chg = f" ({'+' if d >= 0 else ''}{d:.2f}%)" if d is not None else ""
        parts.append(f"10Y Yield: {p:.2f}%{chg}")

    gold = macro.get("Gold", {})
    if gold.get("price") is not None:
        p = gold["price"]
        d = gold.get("pct_1d")
        chg = f" ({'+' if d >= 0 else ''}{d:.1f}%)" if d is not None else ""
        parts.append(f"Gold: ${p:,.0f}{chg}")

    dxy = macro.get("DXY", {})
    if dxy.get("price") is not None:
        p = dxy["price"]
        d = dxy.get("pct_1d")
        chg = f" ({'+' if d >= 0 else ''}{d:.1f}%)" if d is not None else ""
        parts.append(f"DXY: {p:.1f}{chg}")

    return "  ".join(parts)


# Module-level singleton
stooq_client = StooqClient()
