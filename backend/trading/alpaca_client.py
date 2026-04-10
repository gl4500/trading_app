"""
Alpaca Markets client using the official alpaca-py SDK.
Wraps sync SDK calls in asyncio.to_thread() to stay non-blocking.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import (
    StockBarsRequest,
    StockLatestQuoteRequest,
    StockLatestTradeRequest,
    StockSnapshotRequest,
)
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import AssetClass, OrderSide, TimeInForce
from alpaca.trading.requests import GetAssetsRequest, MarketOrderRequest

from config import config

logger = logging.getLogger(__name__)

# Map string timeframe names to alpaca-py TimeFrame objects
TIMEFRAME_MAP: Dict[str, TimeFrame] = {
    "1Min":  TimeFrame(1,  TimeFrameUnit.Minute),
    "5Min":  TimeFrame(5,  TimeFrameUnit.Minute),
    "15Min": TimeFrame(15, TimeFrameUnit.Minute),
    "1Hour": TimeFrame(1,  TimeFrameUnit.Hour),
    "1Day":  TimeFrame(1,  TimeFrameUnit.Day),
}


class AlpacaClient:
    """
    Async-friendly wrapper around the alpaca-py SDK.

    The SDK is synchronous, so every SDK call is dispatched to a thread
    via asyncio.to_thread() to avoid blocking the event loop.
    """

    def __init__(self) -> None:
        self._trading = TradingClient(
            api_key=config.ALPACA_API_KEY,
            secret_key=config.ALPACA_SECRET_KEY,
            paper=True,          # always paper trading
        )
        self._data = StockHistoricalDataClient(
            api_key=config.ALPACA_API_KEY,
            secret_key=config.ALPACA_SECRET_KEY,
        )

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    async def get_account(self) -> Dict:
        """Return paper account details as a plain dict."""
        try:
            account = await asyncio.to_thread(self._trading.get_account)
            return account.model_dump()
        except Exception as exc:
            logger.error("Error fetching account: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # Market data — bars
    # ------------------------------------------------------------------

    async def get_bars(
        self,
        symbol: str,
        timeframe: str = "1Day",
        limit: int = 60,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV bars for a single symbol.

        Parameters
        ----------
        symbol    : ticker, e.g. "AAPL"
        timeframe : "1Min" | "5Min" | "15Min" | "1Hour" | "1Day"
        limit     : number of bars to return (most recent)

        Returns a DataFrame with columns:
            timestamp, open, high, low, close, volume, vwap, trade_count
        """
        tf = TIMEFRAME_MAP.get(timeframe, TimeFrame(1, TimeFrameUnit.Day))
        end = datetime.now(timezone.utc)
        # Fetch extra calendar days so we get at least `limit` trading bars
        start = end - timedelta(days=limit + 14)

        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=tf,
            start=start,
            end=end,
            feed="iex",
        )

        try:
            bar_set = await asyncio.to_thread(self._data.get_stock_bars, request)
            df = bar_set.df  # MultiIndex: (symbol, timestamp)

            if df.empty:
                logger.warning("No bars returned for %s", symbol)
                return pd.DataFrame()

            # Flatten the MultiIndex if present
            if isinstance(df.index, pd.MultiIndex):
                df = df.xs(symbol, level="symbol")

            df = df.reset_index()  # brings 'timestamp' back as a column
            df = df.rename(columns={
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "volume": "volume",
                "vwap": "vwap",
                "trade_count": "trade_count",
            })
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            df = df.sort_values("timestamp").reset_index(drop=True)
            return df.tail(limit)

        except Exception as exc:
            logger.error("Error fetching bars for %s: %s", symbol, exc)
            return pd.DataFrame()

    async def get_bars_multi(
        self,
        symbols: List[str],
        timeframe: str = "1Day",
        limit: int = 60,
    ) -> Dict[str, pd.DataFrame]:
        """
        Fetch bars for multiple symbols in a single API call (more efficient).
        Returns {symbol: DataFrame}.
        """
        tf = TIMEFRAME_MAP.get(timeframe, TimeFrame(1, TimeFrameUnit.Day))
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=limit + 14)

        request = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=tf,
            start=start,
            end=end,
            feed="iex",
        )

        try:
            bar_set = await asyncio.to_thread(self._data.get_stock_bars, request)
            df_all = bar_set.df  # Normally MultiIndex (symbol, timestamp)

            # When only one symbol returns data the SDK may give a plain Index.
            # Wrap it into a MultiIndex so xs(level="symbol") works uniformly.
            if not df_all.empty and not isinstance(df_all.index, pd.MultiIndex):
                returned_sym = symbols[0] if len(symbols) == 1 else symbols[0]
                df_all = pd.concat({returned_sym: df_all}, names=["symbol", "timestamp"])

            result: Dict[str, pd.DataFrame] = {}
            for sym in symbols:
                try:
                    df = df_all.xs(sym, level="symbol").reset_index()
                    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
                    df = df.sort_values("timestamp").reset_index(drop=True)
                    result[sym] = df.tail(limit)
                except KeyError:
                    logger.warning("No bars in batch response for %s", sym)
                    result[sym] = pd.DataFrame()

            return result

        except Exception as exc:
            logger.error("Error fetching multi-symbol bars: %s", exc)
            return {sym: pd.DataFrame() for sym in symbols}

    # ------------------------------------------------------------------
    # Market data — quotes & trades
    # ------------------------------------------------------------------

    async def get_latest_quote(self, symbol: str) -> Dict:
        """Return the latest NBBO quote for a symbol."""
        try:
            request = StockLatestQuoteRequest(
                symbol_or_symbols=symbol,
                feed="iex",
            )
            quotes = await asyncio.to_thread(self._data.get_stock_latest_quote, request)
            quote = quotes.get(symbol)
            return quote.model_dump() if quote else {}
        except Exception as exc:
            logger.error("Error fetching quote for %s: %s", symbol, exc)
            return {}

    async def get_latest_trade(self, symbol: str) -> Dict:
        """Return the latest trade for a symbol."""
        try:
            request = StockLatestTradeRequest(
                symbol_or_symbols=symbol,
                feed="iex",
            )
            trades = await asyncio.to_thread(self._data.get_stock_latest_trade, request)
            trade = trades.get(symbol)
            return trade.model_dump() if trade else {}
        except Exception as exc:
            logger.error("Error fetching latest trade for %s: %s", symbol, exc)
            return {}

    async def get_latest_prices(self, symbols: List[str]) -> Dict[str, float]:
        """
        Return {symbol: latest_price} for a list of symbols.
        Uses the snapshot endpoint (most data in one call).
        """
        try:
            request = StockSnapshotRequest(
                symbol_or_symbols=symbols,
                feed="iex",
            )
            snapshots = await asyncio.to_thread(
                self._data.get_stock_snapshot, request
            )
            prices: Dict[str, float] = {}
            for sym, snap in snapshots.items():
                if snap.latest_trade:
                    prices[sym] = float(snap.latest_trade.price)
                elif snap.latest_quote:
                    # mid-point of bid/ask as fallback
                    prices[sym] = float(
                        (snap.latest_quote.ask_price + snap.latest_quote.bid_price) / 2
                    )
            return prices
        except Exception as exc:
            logger.error("Error fetching latest prices: %s", exc)
            return {}

    async def get_snapshot(self, symbols: List[str]) -> Dict:
        """
        Return full snapshot data (latest bar, quote, trade, daily bar)
        for a list of symbols as plain dicts.
        """
        try:
            request = StockSnapshotRequest(
                symbol_or_symbols=symbols,
                feed="iex",
            )
            snapshots = await asyncio.to_thread(
                self._data.get_stock_snapshot, request
            )
            return {sym: snap.model_dump() for sym, snap in snapshots.items()}
        except Exception as exc:
            logger.error("Error fetching snapshots: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # Trading — orders (optional: submit a real paper trade)
    # ------------------------------------------------------------------

    async def submit_market_order(
        self,
        symbol: str,
        qty: float,
        side: str,              # "buy" or "sell"
        time_in_force: str = "day",
    ) -> Optional[Dict]:
        """
        Submit a market order to the Alpaca paper account.
        Returns the order object as a dict, or None on failure.
        """
        try:
            order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
            tif = TimeInForce(time_in_force.lower())

            request = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=order_side,
                time_in_force=tif,
            )
            order = await asyncio.to_thread(self._trading.submit_order, request)
            logger.info("Order submitted: %s %s %s qty=%s", side, symbol, order.id, qty)
            return order.model_dump()
        except Exception as exc:
            logger.error("Error submitting order %s %s: %s", side, symbol, exc)
            return None

    async def get_positions(self) -> List[Dict]:
        """Return all open positions in the paper account."""
        try:
            positions = await asyncio.to_thread(self._trading.get_all_positions)
            return [p.model_dump() for p in positions]
        except Exception as exc:
            logger.error("Error fetching positions: %s", exc)
            return []

    async def get_tradable_assets(self) -> List[Dict]:
        """Return list of tradable US equity assets."""
        try:
            request = GetAssetsRequest(asset_class=AssetClass.US_EQUITY)
            assets = await asyncio.to_thread(self._trading.get_all_assets, request)
            return [a.model_dump() for a in assets if a.tradable]
        except Exception as exc:
            logger.error("Error fetching assets: %s", exc)
            return []

    async def close(self) -> None:
        """No persistent connections to close for the alpaca-py SDK."""
        pass


# Singleton instance used by agents and market data module
alpaca_client = AlpacaClient()
