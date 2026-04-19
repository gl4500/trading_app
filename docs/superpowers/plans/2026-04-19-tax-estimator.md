# Tax Estimator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `GET /api/tax/estimate?year=YYYY` endpoint that fetches real Alpaca order history, applies FIFO cost basis, classifies short/long-term gains, detects wash sales, and returns a structured quarterly summary.

**Architecture:** A `TaxEstimator` class in `backend/data/tax_estimator.py` owns all pure logic (pairing, classification, wash sale detection, bucketing). `AlpacaClient` gains a single new async method `get_filled_orders(year)`. `main.py` wires them together in a thin endpoint.

**Tech Stack:** Python stdlib `datetime`, `collections.deque`/`defaultdict`; alpaca-py `TradingClient.get_orders`; existing FastAPI app; `unittest.TestCase` for tests.

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Create | `backend/data/tax_estimator.py` | FIFO pairing, holding period, wash sale, quarterly bucketing, `summarize()` |
| Create | `backend/tests/test_tax_estimator.py` | All unit tests (no live Alpaca calls) |
| Modify | `backend/trading/alpaca_client.py` | Add `get_filled_orders(year)` method |
| Modify | `backend/main.py` | Add `GET /api/tax/estimate` endpoint |

---

## Task 1: Add `get_filled_orders(year)` to `AlpacaClient`

**Files:**
- Modify: `backend/trading/alpaca_client.py` (after line 313, before `alpaca_client = AlpacaClient()`)
- Create: `backend/tests/test_tax_estimator.py` (first test class)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_tax_estimator.py` with the following content:

```python
"""
Unit tests for data/tax_estimator.py and the get_filled_orders()
method on AlpacaClient. No live Alpaca API calls — all SDK calls mocked.
"""
import sys
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock
import asyncio

_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_SITE    = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "site-packages"))
for _p in (_BACKEND, _SITE):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ── helpers ──────────────────────────────────────────────────────────────────

def _dt(year, month, day, hour=12):
    return datetime(year, month, day, hour, 0, 0, tzinfo=timezone.utc)


def _order(symbol, side, shares, price, filled_at):
    """Build a plain order dict as returned by get_filled_orders()."""
    return {
        "symbol": symbol,
        "side": side,      # "buy" or "sell"
        "shares": float(shares),
        "price": float(price),
        "filled_at": filled_at,
    }


# ── AlpacaClient.get_filled_orders() ─────────────────────────────────────────

class TestGetFilledOrders(unittest.IsolatedAsyncioTestCase):

    async def test_returns_filled_orders_for_year(self):
        """get_filled_orders(2025) returns one dict per filled buy/sell order."""
        # Build a mock Order object matching alpaca-py's Order model
        mock_order = MagicMock()
        mock_order.symbol = "AAPL"
        mock_order.side.value = "buy"
        mock_order.filled_qty = "10"
        mock_order.filled_avg_price = "150.00"
        mock_order.filled_at = _dt(2025, 3, 1)

        with patch("trading.alpaca_client.TradingClient") as MockTC:
            instance = MockTC.return_value
            instance.get_orders = MagicMock(return_value=[mock_order])

            from trading.alpaca_client import AlpacaClient
            client = AlpacaClient()
            client._trading = instance

            result = await client.get_filled_orders(2025)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["symbol"], "AAPL")
        self.assertEqual(result[0]["side"], "buy")
        self.assertAlmostEqual(result[0]["shares"], 10.0)
        self.assertAlmostEqual(result[0]["price"], 150.0)

    async def test_empty_year_returns_empty_list(self):
        """get_filled_orders returns [] when no orders exist."""
        with patch("trading.alpaca_client.TradingClient") as MockTC:
            instance = MockTC.return_value
            instance.get_orders = MagicMock(return_value=[])

            from trading.alpaca_client import AlpacaClient
            client = AlpacaClient()
            client._trading = instance

            result = await client.get_filled_orders(2025)

        self.assertEqual(result, [])

    async def test_alpaca_error_raises(self):
        """get_filled_orders propagates exceptions so the endpoint can return 503."""
        with patch("trading.alpaca_client.TradingClient") as MockTC:
            instance = MockTC.return_value
            instance.get_orders = MagicMock(side_effect=Exception("API down"))

            from trading.alpaca_client import AlpacaClient
            client = AlpacaClient()
            client._trading = instance

            with self.assertRaises(Exception):
                await client.get_filled_orders(2025)
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
cd C:\Users\gl450\trading_app\backend
C:\Users\gl450\trading_app\runtime\python\python.exe -m unittest tests.test_tax_estimator.TestGetFilledOrders -v
```

Expected: `AttributeError: 'AlpacaClient' object has no attribute 'get_filled_orders'`

- [ ] **Step 3: Implement `get_filled_orders()` in `alpaca_client.py`**

Add the following method to the `AlpacaClient` class, immediately before the `close()` method (around line 313):

```python
async def get_filled_orders(self, year: int) -> List[Dict]:
    """
    Fetch all filled (closed) orders for the given calendar year.

    Returns a list of dicts:
        [{"symbol": str, "side": "buy"|"sell",
          "shares": float, "price": float, "filled_at": datetime}, ...]

    Raises the underlying exception on API failure so the caller
    can return HTTP 503.
    """
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus

    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    end   = datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

    request = GetOrdersRequest(
        status=QueryOrderStatus.CLOSED,
        after=start,
        until=end,
        limit=500,          # max per call; typical annual trade count is well below
    )

    batch = await asyncio.to_thread(self._trading.get_orders, request)

    result: List[Dict] = []
    for order in batch:
        if not order.filled_qty or not order.filled_avg_price:
            continue
        filled_qty = float(order.filled_qty)
        if filled_qty <= 0:
            continue
        result.append({
            "symbol":    order.symbol,
            "side":      order.side.value,   # "buy" or "sell"
            "shares":    filled_qty,
            "price":     float(order.filled_avg_price),
            "filled_at": order.filled_at,
        })

    return result
```

Also add this import at the top of `alpaca_client.py` if not already present (it already is):
```python
from datetime import datetime, timedelta, timezone
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
cd C:\Users\gl450\trading_app\backend
C:\Users\gl450\trading_app\runtime\python\python.exe -m unittest tests.test_tax_estimator.TestGetFilledOrders -v
```

Expected: `OK` — 3 tests pass.

- [ ] **Step 5: Commit**

```bash
cd C:\Users\gl450\trading_app
git add backend/trading/alpaca_client.py backend/tests/test_tax_estimator.py
git commit -m "feat: add get_filled_orders() to AlpacaClient with tests"
```

---

## Task 2: Create `tax_estimator.py` — FIFO pairing and holding period

**Files:**
- Create: `backend/data/tax_estimator.py`
- Modify: `backend/tests/test_tax_estimator.py` (add `TestFifoPairing` class)

- [ ] **Step 1: Write the failing tests**

Append the following to `backend/tests/test_tax_estimator.py`:

```python
# ── TaxEstimator — FIFO pairing and holding period ───────────────────────────

from data.tax_estimator import TaxEstimator


class TestFifoPairing(unittest.TestCase):

    def test_short_term_gain(self):
        """Sell within 365 days → classified short-term, gain correct."""
        orders = [
            _order("AAPL", "buy",  10, 100.0, _dt(2025, 1, 10)),
            _order("AAPL", "sell", 10, 120.0, _dt(2025, 6, 10)),  # 150 days
        ]
        est = TaxEstimator(orders)
        result = est.summarize(2025)
        self.assertAlmostEqual(result["short_term"]["gains"], 200.0)
        self.assertAlmostEqual(result["short_term"]["net"],   200.0)
        self.assertAlmostEqual(result["long_term"]["gains"],    0.0)
        self.assertAlmostEqual(result["total_net"],           200.0)

    def test_long_term_gain(self):
        """Sell after 365 days → classified long-term."""
        orders = [
            _order("AAPL", "buy",  10, 100.0, _dt(2023, 1, 1)),
            _order("AAPL", "sell", 10, 150.0, _dt(2025, 3, 1)),  # ~2 years
        ]
        est = TaxEstimator(orders)
        result = est.summarize(2025)
        self.assertAlmostEqual(result["long_term"]["gains"],  500.0)
        self.assertAlmostEqual(result["short_term"]["gains"],   0.0)

    def test_loss_offset(self):
        """Net is gains minus losses."""
        orders = [
            _order("AAPL", "buy",  10, 100.0, _dt(2025, 1, 1)),
            _order("AAPL", "sell", 10,  80.0, _dt(2025, 3, 1)),   # -$200 loss
        ]
        est = TaxEstimator(orders)
        result = est.summarize(2025)
        self.assertAlmostEqual(result["short_term"]["losses"], 200.0)
        self.assertAlmostEqual(result["short_term"]["net"],   -200.0)
        self.assertAlmostEqual(result["total_net"],           -200.0)

    def test_fifo_partial_lot(self):
        """Sell spans two buy lots — each classified independently."""
        orders = [
            _order("AAPL", "buy",  5, 100.0, _dt(2023, 1, 1)),   # lot 1: long-term after 2025-01-01
            _order("AAPL", "buy",  5, 110.0, _dt(2025, 1, 15)),  # lot 2: short-term in 2025
            _order("AAPL", "sell", 10, 130.0, _dt(2025, 6, 1)),
        ]
        est = TaxEstimator(orders)
        result = est.summarize(2025)
        # lot 1: (130-100)*5 = 150 long-term
        # lot 2: (130-110)*5 = 100 short-term
        self.assertAlmostEqual(result["long_term"]["gains"],  150.0)
        self.assertAlmostEqual(result["short_term"]["gains"], 100.0)
        self.assertAlmostEqual(result["total_net"],           250.0)

    def test_mixed_symbols(self):
        """AAPL and TSLA lots are tracked independently."""
        orders = [
            _order("AAPL", "buy",  10, 100.0, _dt(2025, 1, 1)),
            _order("TSLA", "buy",  10, 200.0, _dt(2025, 1, 1)),
            _order("AAPL", "sell", 10, 120.0, _dt(2025, 4, 1)),  # +200
            _order("TSLA", "sell", 10, 180.0, _dt(2025, 4, 1)),  # -200
        ]
        est = TaxEstimator(orders)
        result = est.summarize(2025)
        self.assertAlmostEqual(result["short_term"]["gains"],  200.0)
        self.assertAlmostEqual(result["short_term"]["losses"], 200.0)
        self.assertAlmostEqual(result["short_term"]["net"],      0.0)

    def test_empty_year_returns_zeros(self):
        """No trades for the requested year → all zeros, no crash."""
        orders = [
            _order("AAPL", "buy",  10, 100.0, _dt(2024, 1, 1)),
            _order("AAPL", "sell", 10, 120.0, _dt(2024, 6, 1)),
        ]
        est = TaxEstimator(orders)
        result = est.summarize(2025)
        self.assertEqual(result["total_net"], 0.0)
        self.assertEqual(result["trades_analyzed"], 0)

    def test_year_filter(self):
        """Trades from other years are excluded from the summary."""
        orders = [
            _order("AAPL", "buy",  10, 100.0, _dt(2024, 1, 1)),
            _order("AAPL", "sell", 10, 150.0, _dt(2024, 6, 1)),  # 2024 — excluded
            _order("AAPL", "buy",  10, 110.0, _dt(2024, 12, 1)),
            _order("AAPL", "sell", 10, 130.0, _dt(2025, 3, 1)),  # 2025 — included
        ]
        est = TaxEstimator(orders)
        result = est.summarize(2025)
        self.assertEqual(result["trades_analyzed"], 1)
        self.assertAlmostEqual(result["short_term"]["gains"], 200.0)  # (130-110)*10
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
cd C:\Users\gl450\trading_app\backend
C:\Users\gl450\trading_app\runtime\python\python.exe -m unittest tests.test_tax_estimator.TestFifoPairing -v
```

Expected: `ModuleNotFoundError: No module named 'data.tax_estimator'`

- [ ] **Step 3: Create `backend/data/tax_estimator.py`**

```python
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
        filled_at (datetime, timezone-aware or naive)
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

        wash_count = self._detect_wash_sales(closed)

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
            symbol    = order["symbol"]
            shares    = order["shares"]
            price     = order["price"]
            date      = order["filled_at"]

            if order["side"] == "buy":
                lots[symbol].append(_Lot(symbol, shares, price, date))
                continue

            # SELL — consume oldest lots first
            remaining = shares
            while remaining > 0 and lots[symbol]:
                lot = lots[symbol][0]
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
        # Collect all buy timestamps per symbol from the original order list
        buy_dates: Dict[str, List[datetime]] = defaultdict(list)
        for o in self._orders:
            if o["side"] == "buy":
                buy_dates[o["symbol"]].append(o["filled_at"])

        count = 0
        for trade in closed_trades:
            if trade.gain >= 0:
                continue  # only losses trigger wash-sale scrutiny
            sell_dt = trade.sell_date
            for buy_dt in buy_dates[trade.symbol]:
                if buy_dt == trade.buy_date:
                    continue  # skip the original buy that opened this lot
                if abs((buy_dt - sell_dt).days) <= 30:
                    count += 1
                    break   # one flag per loss trade is sufficient

        return count
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
cd C:\Users\gl450\trading_app\backend
C:\Users\gl450\trading_app\runtime\python\python.exe -m unittest tests.test_tax_estimator.TestFifoPairing -v
```

Expected: `OK` — 7 tests pass.

- [ ] **Step 5: Commit**

```bash
cd C:\Users\gl450\trading_app
git add backend/data/tax_estimator.py backend/tests/test_tax_estimator.py
git commit -m "feat: add TaxEstimator with FIFO pairing and holding period classification"
```

---

## Task 3: Wash sale detection and quarterly bucketing tests

**Files:**
- Modify: `backend/tests/test_tax_estimator.py` (add `TestWashSales` and `TestQuarterly` classes)

- [ ] **Step 1: Write the failing tests**

Append the following to `backend/tests/test_tax_estimator.py`:

```python
# ── Wash sale detection ───────────────────────────────────────────────────────

class TestWashSales(unittest.TestCase):

    def test_wash_sale_detected(self):
        """Loss sale + rebuy within 30 days → wash_sale_count = 1."""
        orders = [
            _order("AAPL", "buy",  10, 100.0, _dt(2025, 1, 1)),
            _order("AAPL", "sell", 10,  80.0, _dt(2025, 3, 1)),   # -$200 loss
            _order("AAPL", "buy",  10, 82.0,  _dt(2025, 3, 15)),  # rebuy 14 days later
        ]
        est = TaxEstimator(orders)
        result = est.summarize(2025)
        self.assertEqual(result["wash_sale_count"], 1)

    def test_no_wash_sale_outside_window(self):
        """Loss sale + rebuy 31 days later → not flagged."""
        orders = [
            _order("AAPL", "buy",  10, 100.0, _dt(2025, 1, 1)),
            _order("AAPL", "sell", 10,  80.0, _dt(2025, 3, 1)),
            _order("AAPL", "buy",  10, 82.0,  _dt(2025, 4, 2)),   # 32 days after sell
        ]
        est = TaxEstimator(orders)
        result = est.summarize(2025)
        self.assertEqual(result["wash_sale_count"], 0)

    def test_gain_not_flagged_as_wash_sale(self):
        """Profitable sale with rebuy within 30 days is NOT a wash sale."""
        orders = [
            _order("AAPL", "buy",  10, 100.0, _dt(2025, 1, 1)),
            _order("AAPL", "sell", 10, 120.0, _dt(2025, 3, 1)),   # +$200 gain
            _order("AAPL", "buy",  10, 115.0, _dt(2025, 3, 10)),
        ]
        est = TaxEstimator(orders)
        result = est.summarize(2025)
        self.assertEqual(result["wash_sale_count"], 0)


# ── Quarterly bucketing ───────────────────────────────────────────────────────

class TestQuarterly(unittest.TestCase):

    def test_quarterly_bucketing(self):
        """Trades in each quarter land in the correct bucket."""
        orders = [
            # Q1 sell: +100
            _order("AAPL", "buy",  1, 100.0, _dt(2025, 1, 1)),
            _order("AAPL", "sell", 1, 200.0, _dt(2025, 2, 1)),
            # Q2 sell: +50
            _order("TSLA", "buy",  1, 100.0, _dt(2025, 1, 1)),
            _order("TSLA", "sell", 1, 150.0, _dt(2025, 5, 1)),
            # Q3 sell: -30
            _order("MSFT", "buy",  1, 100.0, _dt(2025, 1, 1)),
            _order("MSFT", "sell", 1,  70.0, _dt(2025, 8, 1)),
            # Q4 sell: +80
            _order("AMZN", "buy",  1, 100.0, _dt(2025, 1, 1)),
            _order("AMZN", "sell", 1, 180.0, _dt(2025, 11, 1)),
        ]
        est = TaxEstimator(orders)
        result = est.summarize(2025)
        self.assertAlmostEqual(result["quarterly"]["Q1"]["net"],  100.0)
        self.assertAlmostEqual(result["quarterly"]["Q2"]["net"],   50.0)
        self.assertAlmostEqual(result["quarterly"]["Q3"]["net"],  -30.0)
        self.assertAlmostEqual(result["quarterly"]["Q4"]["net"],   80.0)
        self.assertAlmostEqual(result["total_net"], 200.0)
```

- [ ] **Step 2: Run the tests to confirm they pass** (logic is already implemented)

```bash
cd C:\Users\gl450\trading_app\backend
C:\Users\gl450\trading_app\runtime\python\python.exe -m unittest tests.test_tax_estimator.TestWashSales tests.test_tax_estimator.TestQuarterly -v
```

Expected: `OK` — 6 tests pass.

- [ ] **Step 3: Commit**

```bash
cd C:\Users\gl450\trading_app
git add backend/tests/test_tax_estimator.py
git commit -m "test: add wash sale and quarterly bucketing tests for TaxEstimator"
```

---

## Task 4: Add `GET /api/tax/estimate` endpoint

**Files:**
- Modify: `backend/main.py` (add endpoint after existing `@app.get` routes)
- Modify: `backend/tests/test_tax_estimator.py` (add `TestTaxEndpoint` class)

- [ ] **Step 1: Write the failing endpoint test**

Append the following to `backend/tests/test_tax_estimator.py`:

```python
# ── /api/tax/estimate endpoint ────────────────────────────────────────────────

from unittest.mock import AsyncMock


class TestTaxEndpoint(unittest.IsolatedAsyncioTestCase):

    async def test_endpoint_returns_summary(self):
        """GET /api/tax/estimate?year=2025 returns correct JSON structure."""
        from httpx import AsyncClient, ASGITransport
        from main import app

        mock_orders = [
            _order("AAPL", "buy",  10, 100.0, _dt(2025, 1, 1)),
            _order("AAPL", "sell", 10, 120.0, _dt(2025, 6, 1)),
        ]

        with patch("main.alpaca_client.get_filled_orders", new=AsyncMock(return_value=mock_orders)):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # Bypass auth middleware
                response = await client.get(
                    "/api/tax/estimate?year=2025",
                    cookies={"session": "test"},
                )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["year"], 2025)
        self.assertIn("short_term", data)
        self.assertIn("long_term", data)
        self.assertIn("total_net", data)
        self.assertIn("quarterly", data)
        self.assertAlmostEqual(data["short_term"]["gains"], 200.0)

    async def test_endpoint_returns_503_on_alpaca_error(self):
        """GET /api/tax/estimate returns 503 when Alpaca is unreachable."""
        from httpx import AsyncClient, ASGITransport
        from main import app

        with patch("main.alpaca_client.get_filled_orders",
                   new=AsyncMock(side_effect=Exception("API down"))):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/api/tax/estimate?year=2025",
                    cookies={"session": "test"},
                )

        self.assertEqual(response.status_code, 503)
        self.assertIn("alpaca_unavailable", response.json()["error"])

    async def test_endpoint_defaults_to_current_year(self):
        """Omitting ?year defaults to the current calendar year."""
        from httpx import AsyncClient, ASGITransport
        from main import app
        import datetime as _dt_mod

        with patch("main.alpaca_client.get_filled_orders", new=AsyncMock(return_value=[])):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/api/tax/estimate",
                    cookies={"session": "test"},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["year"], _dt_mod.datetime.now().year)
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
cd C:\Users\gl450\trading_app\backend
C:\Users\gl450\trading_app\runtime\python\python.exe -m unittest tests.test_tax_estimator.TestTaxEndpoint -v
```

Expected: `AssertionError: 404 != 200` (endpoint not yet defined)

- [ ] **Step 3: Add the endpoint to `main.py`**

Find the imports block at the top of `main.py` and add:

```python
from data.tax_estimator import TaxEstimator
```

Then add the following endpoint. A good location is immediately after the `@app.get("/api/scanner")` block (search for `async def get_scanner_results`):

```python
@app.get("/api/tax/estimate")
async def get_tax_estimate(year: Optional[int] = Query(None)):
    """
    Estimate realized capital gains and losses for the given calendar year.

    Returns short-term and long-term gain/loss figures, wash-sale count,
    and quarterly net breakdown. Federal only — caller applies their own rate.
    """
    if year is None:
        year = datetime.utcnow().year

    try:
        orders = await alpaca_client.get_filled_orders(year)
    except Exception as exc:
        logger.error("Tax estimate: Alpaca unavailable: %s", exc)
        raise HTTPException(status_code=503, detail={"error": "alpaca_unavailable"})

    estimator = TaxEstimator(orders)
    return estimator.summarize(year)
```

- [ ] **Step 4: Run all tax tests to confirm they pass**

```bash
cd C:\Users\gl450\trading_app\backend
C:\Users\gl450\trading_app\runtime\python\python.exe -m unittest tests.test_tax_estimator -v
```

Expected: `OK` — all tests pass.

- [ ] **Step 5: Run the full test suite to confirm no regressions**

```bash
cd C:\Users\gl450\trading_app\backend
C:\Users\gl450\trading_app\runtime\python\python.exe run_tests.py
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
cd C:\Users\gl450\trading_app
git add backend/main.py backend/tests/test_tax_estimator.py
git commit -m "feat: add GET /api/tax/estimate endpoint"
```

---

## Post-Implementation Checklist

- [ ] All 16 tests in `test_tax_estimator.py` pass
- [ ] Full test suite passes with no regressions
- [ ] `CLAUDE.md` updated: add `data/tax_estimator.py` to Key Backend Files and `test_tax_estimator.py` to Current Test Coverage
- [ ] Memory updated: `trading_app_architecture.md` — new file, new endpoint

---

## IRS Quarterly Due Dates (reference)

| Quarter | Tax Period | Estimated Tax Due |
|---|---|---|
| Q1 | Jan 1 – Mar 31 | April 15 |
| Q2 | Apr 1 – Jun 30 | June 15 |
| Q3 | Jul 1 – Sep 30 | September 15 |
| Q4 | Oct 1 – Dec 31 | January 15 (following year) |
