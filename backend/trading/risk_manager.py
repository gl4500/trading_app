"""
Risk management: enforces position limits, concentration limits, and daily loss limits.
"""
import logging
import math
from datetime import datetime
from typing import Dict, Tuple

from config import config
from data.stock_universe import get_sector

CHURN_COOLOFF_MINUTES = 30
SECTOR_CONCENTRATION_LIMIT = 0.35

logger = logging.getLogger(__name__)


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
            elapsed_seconds = (datetime.utcnow() - last_exit).total_seconds()
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
