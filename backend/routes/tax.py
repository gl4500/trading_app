"""Tax estimate endpoint: /api/tax/estimate."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

tax_router = APIRouter()


@tax_router.get("/api/tax/estimate")
async def get_tax_estimate(year: Optional[int] = Query(None)):
    """Estimate realized capital gains and losses for the given calendar year.

    Returns short-term and long-term gain/loss figures, wash-sale count,
    and quarterly net breakdown. Federal only — caller applies their own rate.
    """
    import main
    from data.tax_estimator import TaxEstimator
    from trading.alpaca_client import alpaca_client

    _logger = main.logger
    if year is None:
        year = main.datetime.utcnow().year

    try:
        orders = await alpaca_client.get_filled_orders(year)
    except Exception as exc:
        _logger.error("Tax estimate: Alpaca unavailable: %s", exc)
        raise HTTPException(status_code=503, detail={"error": "alpaca_unavailable"})

    estimator = TaxEstimator(orders)
    return estimator.summarize(year)
