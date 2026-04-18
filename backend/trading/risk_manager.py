"""
Risk management: enforces position limits, concentration limits, and daily loss limits.
"""
import logging
import math
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

import numpy as np

from config import config
from data.stock_universe import get_sector

CHURN_COOLOFF_MINUTES = 30
SECTOR_CONCENTRATION_LIMIT = 0.35
CORRELATION_LIMIT = 0.65   # max avg pairwise Pearson correlation across proposed holdings
_MIN_CORR_BARS    = 20     # minimum return bars required for a reliable correlation

logger = logging.getLogger(__name__)


def _avg_pairwise_correlation(returns_dict: Dict[str, np.ndarray]) -> float:
    """
    Compute the mean pairwise Pearson correlation across all return series.

    Uses the shortest series length so all series are aligned.
    Returns 0.0 when fewer than 2 series or insufficient bars.
    """
    symbols = list(returns_dict.keys())
    if len(symbols) < 2:
        return 0.0
    min_len = min(len(returns_dict[s]) for s in symbols)
    if min_len < _MIN_CORR_BARS:
        return 0.0
    matrix = np.array([returns_dict[s][-min_len:] for s in symbols])  # (n, min_len)
    corr = np.corrcoef(matrix)                                          # (n, n)
    upper = corr[np.triu_indices(len(symbols), k=1)]
    return float(np.mean(upper))


class RiskManager:
    """Enforces risk rules for a trading agent's portfolio."""

    def __init__(self, max_position_size: float = None, daily_loss_limit: float = None):
        self.max_position_size = max_position_size or config.MAX_POSITION_SIZE
        self.daily_loss_limit = daily_loss_limit or config.DAILY_LOSS_LIMIT
        self._trading_halted: bool = False
        self._halt_reason: str = ""

    def is_trading_allowed(self) -> Tuple[bool, str]:
        """Check if trading is currently allowed."""
        if self._trading_halted:
            return False, self._halt_reason
        return True, ""

    def check_daily_loss(self, portfolio, prices: Dict[str, float]) -> bool:
        """
        Check daily loss limit. Halts trading if exceeded.
        Returns True if trading should continue.
        """
        daily_return = portfolio.get_daily_return(prices)
        if daily_return < -self.daily_loss_limit:
            self._trading_halted = True
            self._halt_reason = (
                f"Daily loss limit reached: {daily_return*100:.2f}% "
                f"(limit: -{self.daily_loss_limit*100:.0f}%)"
            )
            logger.warning(f"RiskManager: {self._halt_reason}")
            return False
        return True

    def reset_daily_halt(self) -> None:
        """Reset halt at start of new trading day."""
        self._trading_halted = False
        self._halt_reason = ""

    def check_buy_allowed(
        self,
        symbol: str,
        shares: float,
        price: float,
        portfolio,
        prices: Dict[str, float],
        portfolio_returns: Optional[Dict[str, np.ndarray]] = None,
    ) -> Tuple[bool, str]:
        """
        Validate a potential buy order against all risk rules.
        Returns (allowed, reason_if_denied).
        """
        # Check if trading is halted
        allowed, reason = self.is_trading_allowed()
        if not allowed:
            return False, reason

        # Churn prevention: block re-entry within 30 minutes of selling
        recent_exits = getattr(portfolio, '_recent_exits', {})
        last_exit = recent_exits.get(symbol)
        if last_exit is not None:
            elapsed_seconds = (datetime.now(timezone.utc) - last_exit).total_seconds()
            elapsed_minutes = elapsed_seconds / 60
            if elapsed_minutes < CHURN_COOLOFF_MINUTES:
                remaining = int(CHURN_COOLOFF_MINUTES - elapsed_minutes)
                return (
                    False,
                    f"Churn prevention: {symbol} sold {elapsed_minutes:.0f}min ago, "
                    f"cooloff {remaining}min remaining",
                )

        total_value = portfolio.get_total_value(prices)
        if total_value == 0:
            return False, "Portfolio has no value"

        trade_value = shares * price

        # Check max position size (as fraction of total portfolio)
        existing_position_value = portfolio.get_position_value(symbol, price)
        new_position_value = existing_position_value + trade_value
        position_fraction = new_position_value / total_value

        if position_fraction > self.max_position_size:
            allowed_value = total_value * self.max_position_size - existing_position_value
            allowed_shares = max(0, allowed_value / price)
            return (
                False,
                f"Position size limit: {symbol} would be {position_fraction*100:.1f}% of portfolio "
                f"(max {self.max_position_size*100:.0f}%). Max allowed: {allowed_shares:.2f} shares",
            )

        # No shorting (paper trading, long only)
        if shares < 0:
            return False, "Short selling not allowed"

        # Check sufficient cash
        if trade_value > portfolio.cash:
            return False, f"Insufficient cash: need ${trade_value:.2f}, have ${portfolio.cash:.2f}"

        # Check concentration: no single stock > 15% of portfolio
        concentration = new_position_value / total_value
        if concentration > 0.15:
            return False, f"Concentration limit: {symbol} would be {concentration*100:.1f}% of portfolio"

        # Check sector concentration: no single sector > 35% of portfolio
        sector = get_sector(symbol)
        if sector != "Unknown":
            sector_value = trade_value
            for sym, pos in portfolio.positions.items():
                if get_sector(sym) == sector:
                    sector_value += portfolio.get_position_value(sym, prices.get(sym, 0))
            sector_pct = sector_value / total_value
            if sector_pct > SECTOR_CONCENTRATION_LIMIT:
                return (
                    False,
                    f"Sector concentration limit: {sector} would be {sector_pct*100:.1f}% of portfolio "
                    f"(max {SECTOR_CONCENTRATION_LIMIT*100:.0f}%)",
                )

        # Markowitz correlation gate: block when adding this position raises average
        # pairwise correlation of the portfolio above CORRELATION_LIMIT.
        # Only fires when caller provides return series (optional — skipped when None).
        if portfolio_returns is not None and symbol in portfolio_returns:
            held_with_returns = {
                s: portfolio_returns[s]
                for s in portfolio.positions
                if s in portfolio_returns
            }
            if held_with_returns:
                proposed = {**held_with_returns, symbol: portfolio_returns[symbol]}
                avg_corr = _avg_pairwise_correlation(proposed)
                if avg_corr > CORRELATION_LIMIT:
                    return (
                        False,
                        f"Correlation gate: adding {symbol} raises avg pairwise "
                        f"correlation to {avg_corr:.2f} (limit {CORRELATION_LIMIT:.2f}) — "
                        f"portfolio already highly correlated",
                    )

        return True, ""

    def get_max_buy_shares(
        self,
        symbol: str,
        price: float,
        confidence: float,
        portfolio,
        prices: Dict[str, float],
    ) -> float:
        """
        Calculate maximum shares we can buy given risk constraints and confidence.
        Returns the recommended number of shares.
        """
        if price <= 0:
            return 0

        total_value = portfolio.get_total_value(prices)
        existing_position_value = portfolio.get_position_value(symbol, price)

        # Max allocation based on position limit
        max_allocation = total_value * self.max_position_size
        available_allocation = max_allocation - existing_position_value

        # Scale by confidence
        target_allocation = available_allocation * confidence

        # Can't spend more than we have
        target_allocation = min(target_allocation, portfolio.cash)
        target_allocation = max(0, target_allocation)

        shares = target_allocation / price
        return math.floor(shares * 100) / 100  # round down to 2 decimal places

    def check_sell_allowed(
        self,
        symbol: str,
        shares: float,
        portfolio,
    ) -> Tuple[bool, str]:
        """Validate a sell order."""
        if symbol not in portfolio.positions:
            return False, f"No position in {symbol}"

        pos = portfolio.positions[symbol]
        if shares > pos.shares:
            return False, f"Cannot sell {shares} shares, only have {pos.shares}"

        if shares <= 0:
            return False, "Invalid share count"

        return True, ""
