"""
Federal capital gains tax estimator.

Consumes a flat list of filled order dicts (as returned by
AlpacaClient.get_filled_orders) and produces a structured summary of
realized short-term and long-term gains/losses, wash sale flags, and
quarterly net figures.

No external dependencies — stdlib only.
"""
from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List

logger = logging.getLogger(__name__)


@dataclass
class _Lot:
    """A single open buy lot held for FIFO matching."""
    symbol: str
    shares: float
    price: float
    date: datetime


@dataclass
class _ClosedTrade:
    """A fully matched buy-lot / sell-order pair."""
    symbol: str
    shares: float
    buy_price: float
    sell_price: float
    buy_date: datetime
    sell_date: datetime

    @property
    def gain(self) -> float:
        # Round to 10 dp as an intermediate precision anchor; summarize() rounds output to 2 dp.
        return round((self.sell_price - self.buy_price) * self.shares, 10)

    @property
    def is_long_term(self) -> bool:
        """True when the holding period exceeds 365 calendar days."""
        return (self.sell_date - self.buy_date).days > 365


def _quarter(month: int) -> str:
    if month <= 3:
        return "Q1"
    if month <= 6:
        return "Q2"
    if month <= 9:
        return "Q3"
    return "Q4"


class TaxEstimator:
    """
    Estimates realized capital gains tax figures from a list of filled orders.

    Parameters
    ----------
    orders : list of dicts, each with keys:
        symbol    (str)
        side      ("buy" | "sell")
        shares    (float)
        price     (float)
        filled_at (datetime, timezone-aware UTC — matches AlpacaClient.get_filled_orders output)
    """

    def __init__(self, orders: List[Dict]) -> None:
        self._orders = sorted(orders, key=lambda o: o["filled_at"])

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def summarize(self, year: int) -> Dict:
        """
        Return the full tax estimate for *year*.

        All monetary values are rounded to 2 decimal places.
        """
        closed = self._pair_trades_fifo()
        year_trades = [t for t in closed if t.sell_date.year == year]

        st_gains  = sum(t.gain for t in year_trades if not t.is_long_term and t.gain > 0)
        st_losses = abs(sum(t.gain for t in year_trades if not t.is_long_term and t.gain < 0))
        lt_gains  = sum(t.gain for t in year_trades if t.is_long_term  and t.gain > 0)
        lt_losses = abs(sum(t.gain for t in year_trades if t.is_long_term  and t.gain < 0))

        quarterly: Dict[str, float] = {"Q1": 0.0, "Q2": 0.0, "Q3": 0.0, "Q4": 0.0}
        for t in year_trades:
            quarterly[_quarter(t.sell_date.month)] += t.gain

        wash_count = self._detect_wash_sales(year_trades)

        return {
            "year": year,
            "short_term": {
                "gains":  round(st_gains,  2),
                "losses": round(st_losses, 2),
                "net":    round(st_gains - st_losses, 2),
            },
            "long_term": {
                "gains":  round(lt_gains,  2),
                "losses": round(lt_losses, 2),
                "net":    round(lt_gains - lt_losses, 2),
            },
            "total_net":       round(st_gains - st_losses + lt_gains - lt_losses, 2),
            "wash_sale_count": wash_count,
            "trades_analyzed": len(year_trades),
            "quarterly": {q: {"net": round(v, 2)} for q, v in quarterly.items()},
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _pair_trades_fifo(self) -> List[_ClosedTrade]:
        """Match buy lots to sell orders using FIFO cost basis per symbol."""
        lots: Dict[str, deque] = defaultdict(deque)
        closed: List[_ClosedTrade] = []

        for order in self._orders:
            symbol = order["symbol"]
            shares = order["shares"]
            price  = order["price"]
            date   = order["filled_at"]

            if order["side"] == "buy":
                lots[symbol].append(_Lot(symbol, shares, price, date))
                continue

            # SELL — consume oldest lots first
            remaining = shares
            while remaining > 0 and lots[symbol]:
                lot      = lots[symbol][0]
                consumed = min(lot.shares, remaining)
                closed.append(_ClosedTrade(
                    symbol=symbol,
                    shares=consumed,
                    buy_price=lot.price,
                    sell_price=price,
                    buy_date=lot.date,
                    sell_date=date,
                ))
                lot.shares -= consumed
                remaining  -= consumed
                if lot.shares <= 0:
                    lots[symbol].popleft()

            if remaining > 0:
                logger.warning(
                    "tax_estimator: sold %.4f shares of %s with no matching buy lot",
                    remaining, symbol,
                )

        return closed

    def _detect_wash_sales(self, closed_trades: List[_ClosedTrade]) -> int:
        """
        Count loss trades where the same symbol was purchased within
        the 30-day window before or after the sale date (IRS wash-sale rule).

        Returns the number of affected trades (not the number of rebuys).
        """
        buy_dates: Dict[str, List[datetime]] = defaultdict(list)
        for o in self._orders:
            if o["side"] == "buy":
                buy_dates[o["symbol"]].append(o["filled_at"])

        count = 0
        for trade in closed_trades:
            if trade.gain >= 0:
                continue
            sell_dt = trade.sell_date
            for buy_dt in buy_dates[trade.symbol]:
                if buy_dt == trade.buy_date:
                    continue
                if abs((buy_dt - sell_dt).days) <= 30:
                    count += 1
                    break

        return count
