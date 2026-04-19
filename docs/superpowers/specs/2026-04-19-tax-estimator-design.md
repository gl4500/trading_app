# Tax Estimator — Design Spec
**Date:** 2026-04-19  
**Status:** Approved  
**Scope:** Federal capital gains tax estimation for real Alpaca trades

---

## Overview

A backend API endpoint (`GET /api/tax/estimate`) that fetches real trade history from Alpaca, pairs buys and sells using FIFO cost basis, classifies each gain/loss as short-term or long-term, detects potential wash sales, and returns a structured JSON summary bucketed by quarter. No UI, no local storage, no bracket computation — raw figures only.

---

## Architecture

### New files
| File | Purpose |
|---|---|
| `backend/data/tax_estimator.py` | Core logic: fetch, FIFO pair, classify, summarize |
| `backend/tests/test_tax_estimator.py` | Unit tests (no live Alpaca calls) |

### Modified files
| File | Change |
|---|---|
| `backend/main.py` | Add `GET /api/tax/estimate` endpoint |

### No new dependencies
Uses `backend/trading/alpaca_client.py` (already exists) and stdlib `datetime`.

---

## Data Flow

```
GET /api/tax/estimate?year=2025
       │
       ▼
 TaxEstimator.estimate(year)
       │
       ├─ fetch_filled_orders(year)  ← Alpaca API (live pull)
       │
       ├─ pair_trades_fifo()         ← match BUYs → SELLs per symbol
       │
       ├─ classify_holding_period()  ← > 365 days = long-term, else short-term
       │
       └─ summarize()               ← returns structured JSON
```

---

## API Contract

**Endpoint:** `GET /api/tax/estimate`  
**Auth:** Required — same JWT the app already uses  
**Query params:**
- `year` (optional, int) — defaults to current calendar year

**Success response (200):**
```json
{
  "year": 2025,
  "short_term": {
    "gains": 4200.00,
    "losses": 800.00,
    "net": 3400.00
  },
  "long_term": {
    "gains": 1500.00,
    "losses": 0.00,
    "net": 1500.00
  },
  "total_net": 4900.00,
  "wash_sale_count": 2,
  "trades_analyzed": 47,
  "quarterly": {
    "Q1": { "net": 1200.00 },
    "Q2": { "net": 900.00 },
    "Q3": { "net": 1800.00 },
    "Q4": { "net": 1000.00 }
  }
}
```

**Error responses:**
- `503 {"error": "alpaca_unavailable"}` — Alpaca API unreachable
- `200` with all zeros — valid year, no trades found

---

## Core Logic

### FIFO Pairing
For each symbol, buys are queued in chronological order. Each sell consumes the oldest buy lots first. If a sell partially consumes a lot, the remainder stays in the queue. Matches IRS default cost basis method (FIFO).

### Holding Period Classification
Calculated from the buy date of each consumed lot to the sell date:
- `> 365 days` → long-term
- `≤ 365 days` → short-term

If a sell spans multiple lots with different holding periods, each lot's gain/loss is classified independently.

### Wash Sale Detection
After pairing, scan for any SELL at a loss where the same symbol has a BUY within 30 days before or after the sale date. Increment `wash_sale_count` only — no automatic disallowance. The broker's 1099-B handles the actual adjustment.

### Quarterly Bucketing
Each closed trade is assigned to Q1/Q2/Q3/Q4 by **sell date**:
- Q1: Jan 1 – Mar 31 (estimated tax due Apr 15)
- Q2: Apr 1 – Jun 30 (estimated tax due Jun 15)
- Q3: Jul 1 – Sep 30 (estimated tax due Sep 15)
- Q4: Oct 1 – Dec 31 (estimated tax due Jan 15 following year)

---

## Testing Plan

All tests in `backend/tests/test_tax_estimator.py`. No live Alpaca calls — all order data is hardcoded fixtures.

| Test | Verifies |
|---|---|
| `test_short_term_gain` | Sell within 365 days → short-term |
| `test_long_term_gain` | Sell after 365 days → long-term |
| `test_fifo_partial_lot` | Sell spanning two buy lots → each lot classified independently |
| `test_loss_offset` | Loss reduces net correctly |
| `test_wash_sale_detected` | Loss + rebuy within 30 days → `wash_sale_count` incremented |
| `test_no_wash_sale_outside_window` | Rebuy at 31+ days → not flagged |
| `test_quarterly_bucketing` | Sell dates in Q1/Q2/Q3/Q4 → correct quarterly net |
| `test_empty_year_returns_zeros` | No trades → all zeros, no crash |
| `test_year_filter` | Trades from other years excluded |
| `test_mixed_symbols` | AAPL and TSLA tracked independently |

---

## Out of Scope
- State taxes
- Bracket computation (user applies their own rate)
- Wash sale loss disallowance (broker handles via 1099-B)
- Frontend UI
- Local DB caching / background sync
