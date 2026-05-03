"""
Stock split adjuster (Backlog 0.2).

Detects stock splits from Alpaca's corporate-actions API and applies
proportional shares/avg_cost adjustments to held positions whose basis
hasn't been adjusted yet.

Idempotency without new schema
------------------------------
Splits are RARE (a given symbol gets one every few years). Instead of
tracking applied splits in a separate table, we use a price-anchor
heuristic: a split has NOT been applied to a position when

    avg_cost / ratio   matches a recent bar close (within ANCHOR_TOL)
    avg_cost           does NOT match a recent bar close

…because the live Alpaca price feed is already split-adjusted, but the
position's avg_cost is not. Applying the split is then safe; on the
next startup the same heuristic will say "already applied" and skip.

This is a defensive heuristic, not a correctness proof. It cannot
recover positions whose post-split avg_cost happens to coincidentally
match the live price (extremely rare). For those edge cases the user
can use the manual correction path (Portfolio.apply_split directly).
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# How close the rescaled avg_cost must be to the recent close to consider
# the position pre-split (i.e., needs adjustment). 30% tolerance is loose
# enough to handle drift between the position's BUY price and current price
# while tight enough to distinguish from the unscaled avg_cost case.
ANCHOR_TOL = 0.30


def _within(a: float, b: float, tol: float) -> bool:
    """True when |a-b|/b <= tol. Both a and b assumed > 0."""
    if b <= 0:
        return False
    return abs(a - b) / b <= tol


def needs_split_adjustment(avg_cost: float, current_price: float, ratio: float) -> bool:
    """Heuristic: True when applying a `ratio`-for-1 split to avg_cost would
    bring it in line with the current (already-split-adjusted) price.

    Returns False when:
      - avg_cost already matches current_price (split already applied or never split)
      - rescaled avg_cost still doesn't match (price drift is more than ANCHOR_TOL,
        so we can't safely conclude this is a stale-split case)
    """
    if avg_cost <= 0 or current_price <= 0 or ratio <= 0:
        return False
    rescaled = avg_cost / ratio
    return (
        _within(rescaled, current_price, ANCHOR_TOL)
        and not _within(avg_cost, current_price, ANCHOR_TOL)
    )


async def detect_and_apply_splits(
    portfolios: List,                # List of Portfolio objects (one per agent)
    agent_names: List[str],          # parallel list of agent names for logging
    alpaca_client,                   # AlpacaClient for fetching splits + prices
    since_days: int = 90,
) -> int:
    """For each held position across all portfolios, fetch recent splits and
    apply any that haven't been applied yet (per the price-anchor heuristic).

    Returns the total number of (agent, symbol) split adjustments applied.
    Safe to call repeatedly — idempotent via the heuristic.
    """
    if not portfolios:
        return 0
    held_symbols = set()
    for p in portfolios:
        held_symbols.update(p.positions.keys())
    if not held_symbols:
        return 0

    splits = await alpaca_client.get_recent_splits(
        symbols=list(held_symbols), since_days=since_days
    )
    if not splits:
        return 0

    # Latest current prices for the affected symbols (single batched call)
    affected = list({s["symbol"] for s in splits})
    try:
        current_prices = await alpaca_client.get_latest_prices(affected)
    except Exception as exc:
        logger.warning(f"split_adjuster: could not fetch current prices: {exc}")
        current_prices = {}

    applied_total = 0
    for split in splits:
        sym = split["symbol"]
        ratio = split["ratio"]
        cur = current_prices.get(sym)
        if not cur or cur <= 0:
            logger.info(
                f"split_adjuster: skipping {sym} {ratio:g}-for-1 — "
                f"no current price to anchor against"
            )
            continue

        for portfolio, agent_name in zip(portfolios, agent_names):
            if sym not in portfolio.positions:
                continue
            pos = portfolio.positions[sym]
            if not needs_split_adjustment(pos.avg_cost, cur, ratio):
                logger.debug(
                    f"split_adjuster: {agent_name} {sym} appears already-adjusted "
                    f"(avg_cost ${pos.avg_cost:.2f}, current ${cur:.2f}, ratio {ratio:g})"
                )
                continue
            ok = portfolio.apply_split(sym, ratio)
            if ok:
                applied_total += 1
                logger.info(
                    f"split_adjuster: applied {ratio:g}-for-1 split on {sym} "
                    f"for {agent_name} (avg_cost was ${pos.avg_cost * ratio:.2f}, "
                    f"now ${pos.avg_cost:.2f})"
                )

    return applied_total
