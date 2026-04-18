"""
Portfolio management: tracks cash, positions, and performance metrics.
"""
import math
import logging
from datetime import datetime, date, timezone
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from config import config

logger = logging.getLogger(__name__)


@dataclass
class Position:
    symbol: str
    shares: float
    avg_cost: float  # average cost basis per share
    entry_confidence: float = 0.5   # agent confidence at entry (0–1)
    bayes_confidence: float = 0.5   # live Bayesian posterior (updated each candle)

    @property
    def total_cost(self) -> float:
        return self.shares * self.avg_cost

    def current_value(self, price: float) -> float:
        return self.shares * price

    def unrealized_pnl(self, price: float) -> float:
        return self.current_value(price) - self.total_cost

    def unrealized_pnl_pct(self, price: float) -> float:
        if self.avg_cost == 0:
            return 0.0
        return (price - self.avg_cost) / self.avg_cost * 100


@dataclass
class TradeRecord:
    symbol: str
    action: str  # BUY or SELL
    shares: float
    price: float
    timestamp: datetime
    reasoning: str = ""
    pnl: float = 0.0    # realized P&L for SELL trades
    mae_pct: float = 0.0  # Maximum Adverse Excursion: deepest drawdown % from entry before close
    mfe_pct: float = 0.0  # Maximum Favorable Excursion: highest gain % from entry before close


class Portfolio:
    """Tracks a single agent's virtual portfolio."""

    def __init__(self, starting_capital: float = None):
        self.starting_capital = starting_capital or config.STARTING_CAPITAL
        self.cash: float = self.starting_capital
        self.positions: Dict[str, Position] = {}
        self.trade_history: List[TradeRecord] = []
        self.daily_starting_value: float = self.starting_capital
        self.daily_start_date: date = date.today()
        self._value_history: List[Tuple[datetime, float]] = [
            (datetime.now(timezone.utc), self.starting_capital)
        ]
        self._recent_exits: Dict[str, datetime] = {}
        self._position_high: Dict[str, float] = {}       # MFE tracker: highest price seen since entry
        self._position_low: Dict[str, float] = {}        # MAE tracker: lowest price seen since entry
        self._position_last_price: Dict[str, float] = {} # Bayesian update: last seen price per position

    def get_total_value(self, prices: Dict[str, float]) -> float:
        """Calculate total portfolio value (cash + positions)."""
        position_value = sum(
            pos.current_value(prices.get(sym, pos.avg_cost))
            for sym, pos in self.positions.items()
        )
        return self.cash + position_value

    def get_position_value(self, symbol: str, price: float) -> float:
        """Get value of a specific position."""
        if symbol not in self.positions:
            return 0.0
        return self.positions[symbol].current_value(price)

    def can_buy(self, symbol: str, shares: float, price: float) -> Tuple[bool, str]:
        """Check if we can execute a buy order."""
        cost = shares * price
        if cost > self.cash:
            return False, f"Insufficient cash: need ${cost:.2f}, have ${self.cash:.2f}"
        return True, ""

    def execute_buy(self, symbol: str, shares: float, price: float, reasoning: str = "",
                    entry_confidence: float = 0.5) -> bool:
        """Execute a buy order, return True if successful."""
        cost = shares * price
        if cost > self.cash:
            logger.warning(f"Buy failed: insufficient cash for {shares} {symbol} @ ${price}")
            return False

        self.cash -= cost

        if symbol in self.positions:
            # Averaging into existing position — preserve original entry_confidence/bayes_confidence
            pos = self.positions[symbol]
            new_shares = pos.shares + shares
            new_avg_cost = (pos.total_cost + cost) / new_shares
            pos.shares = new_shares
            pos.avg_cost = new_avg_cost
        else:
            confidence = max(0.01, min(0.99, entry_confidence))
            self.positions[symbol] = Position(
                symbol=symbol, shares=shares, avg_cost=price,
                entry_confidence=entry_confidence,
                bayes_confidence=confidence,
            )
            # Initialise excursion trackers for new position
            self._position_high[symbol] = price
            self._position_low[symbol] = price
            self._position_last_price[symbol] = price

        record = TradeRecord(
            symbol=symbol,
            action="BUY",
            shares=shares,
            price=price,
            timestamp=datetime.now(timezone.utc),
            reasoning=reasoning,
        )
        self.trade_history.append(record)
        self._value_history.append((datetime.now(timezone.utc), self.cash))  # snapshot
        return True

    def execute_sell(self, symbol: str, shares: float, price: float, reasoning: str = "") -> bool:
        """Execute a sell order, return True if successful."""
        if symbol not in self.positions:
            logger.warning(f"Sell failed: no position in {symbol}")
            return False

        pos = self.positions[symbol]
        shares_to_sell = min(shares, pos.shares)

        if shares_to_sell <= 0:
            return False

        proceeds = shares_to_sell * price
        cost_basis = shares_to_sell * pos.avg_cost
        realized_pnl = proceeds - cost_basis

        # Calculate MAE/MFE before clearing position
        entry_price = pos.avg_cost
        high = self._position_high.get(symbol, price)
        low  = self._position_low.get(symbol, price)
        mfe_pct = (high - entry_price) / entry_price * 100 if entry_price > 0 else 0.0
        mae_pct = (entry_price - low)  / entry_price * 100 if entry_price > 0 else 0.0

        self.cash += proceeds
        pos.shares -= shares_to_sell

        if pos.shares < 0.001:
            del self.positions[symbol]
            self._position_high.pop(symbol, None)
            self._position_low.pop(symbol, None)
            self._position_last_price.pop(symbol, None)

        record = TradeRecord(
            symbol=symbol,
            action="SELL",
            shares=shares_to_sell,
            price=price,
            timestamp=datetime.now(timezone.utc),
            reasoning=reasoning,
            pnl=realized_pnl,
            mae_pct=max(0.0, mae_pct),
            mfe_pct=max(0.0, mfe_pct),
        )
        self.trade_history.append(record)
        self._value_history.append((datetime.now(timezone.utc), self.cash))
        self._recent_exits[symbol] = datetime.now(timezone.utc)
        return True

    def record_value(self, prices: Dict[str, float]) -> float:
        """Record current portfolio value and update MAE/MFE trackers for open positions."""
        total_value = self.get_total_value(prices)
        self._value_history.append((datetime.now(timezone.utc), total_value))
        if len(self._value_history) > 2000:
            self._value_history = self._value_history[-2000:]

        # Update excursion trackers and Bayesian confidence for all open positions
        _K = 10.0  # logit sensitivity: k × log_return per candle
        for sym in self.positions:
            price = prices.get(sym)
            if price and price > 0:
                if sym not in self._position_high or price > self._position_high[sym]:
                    self._position_high[sym] = price
                if sym not in self._position_low or price < self._position_low[sym]:
                    self._position_low[sym] = price

                # Bayesian confidence update (logit-linear, long-only so direction = +1)
                last = self._position_last_price.get(sym)
                if last and last > 0 and price != last:
                    log_ret = math.log(price / last)
                    pos = self.positions[sym]
                    prior = max(0.01, min(0.99, pos.bayes_confidence))
                    prior_logit = math.log(prior / (1.0 - prior))
                    posterior_logit = prior_logit + _K * log_ret   # direction=+1 (long only)
                    pos.bayes_confidence = max(0.01, min(0.99, 1.0 / (1.0 + math.exp(-posterior_logit))))
                self._position_last_price[sym] = price

        return total_value

    def reset_daily_tracking(self, prices: Dict[str, float]) -> None:
        """Reset daily tracking at market open."""
        today = date.today()
        if today != self.daily_start_date:
            self.daily_starting_value = self.get_total_value(prices)
            self.daily_start_date = today

    def get_daily_return(self, prices: Dict[str, float]) -> float:
        """Get today's return percentage."""
        current = self.get_total_value(prices)
        if self.daily_starting_value == 0:
            return 0.0
        return (current - self.daily_starting_value) / self.daily_starting_value

    def calculate_metrics(self, prices: Dict[str, float]) -> Dict:
        """Calculate comprehensive performance metrics."""
        total_value = self.get_total_value(prices)
        total_return_pct = (total_value - self.starting_capital) / self.starting_capital * 100

        # Win rate from closed trades
        sell_trades = [t for t in self.trade_history if t.action == "SELL"]
        winning_trades = [t for t in sell_trades if t.pnl > 0]
        win_rate = (len(winning_trades) / len(sell_trades) * 100) if sell_trades else 0.0

        # Sharpe ratio from value history
        sharpe = self._calculate_sharpe()

        # Max drawdown
        max_drawdown = self._calculate_max_drawdown()

        # Positions summary
        positions_summary = []
        for sym, pos in self.positions.items():
            price = prices.get(sym, pos.avg_cost)
            positions_summary.append({
                "symbol": sym,
                "shares": pos.shares,
                "avg_cost": pos.avg_cost,
                "current_price": price,
                "current_value": pos.current_value(price),
                "unrealized_pnl": pos.unrealized_pnl(price),
                "unrealized_pnl_pct": pos.unrealized_pnl_pct(price),
                "entry_confidence": pos.entry_confidence,
                "bayes_confidence": pos.bayes_confidence,
            })

        # MAE / MFE analysis — only trades that have excursion data (post-feature trades)
        excursion_trades = [t for t in sell_trades if t.mfe_pct > 0 or t.mae_pct > 0]
        avg_mae = sum(t.mae_pct for t in excursion_trades) / len(excursion_trades) if excursion_trades else 0.0
        avg_mfe = sum(t.mfe_pct for t in excursion_trades) / len(excursion_trades) if excursion_trades else 0.0

        # Captured %: of the maximum favorable move, how much did we actually keep at exit?
        # exit_gain_pct = pnl / cost_basis; cost_basis = proceeds - pnl = price*shares - pnl
        captured_pcts = []
        for t in excursion_trades:
            if t.mfe_pct > 0:
                cost_basis = t.price * t.shares - t.pnl
                if cost_basis > 0:
                    exit_gain_pct = t.pnl / cost_basis * 100
                    captured_pcts.append(exit_gain_pct / t.mfe_pct * 100)
        avg_captured_pct = sum(captured_pcts) / len(captured_pcts) if captured_pcts else 0.0

        return {
            "total_value": total_value,
            "cash": self.cash,
            "position_value": total_value - self.cash,
            "total_return_pct": total_return_pct,
            "total_return": total_value - self.starting_capital,
            "win_rate": win_rate,
            "sharpe_ratio": sharpe,
            "max_drawdown": max_drawdown,
            "total_trades": len(self.trade_history),
            "winning_trades": len(winning_trades),
            "losing_trades": len(sell_trades) - len(winning_trades),
            "positions": positions_summary,
            "avg_mae": avg_mae,
            "avg_mfe": avg_mfe,
            "avg_captured_pct": avg_captured_pct,
        }

    def _calculate_sharpe(self, risk_free_rate: float = 0.04) -> float:
        """Calculate annualized Sharpe ratio from value history."""
        if len(self._value_history) < 10:
            return 0.0

        values = [v for _, v in self._value_history]
        returns = []
        for i in range(1, len(values)):
            if values[i - 1] > 0 and values[i] > 0:
                ret = math.log(values[i] / values[i - 1])  # log returns: additive, symmetric, correct for large swings
                returns.append(ret)

        if not returns:
            return 0.0

        mean_return = sum(returns) / len(returns)
        if len(returns) < 2:
            return 0.0

        variance = sum((r - mean_return) ** 2 for r in returns) / (len(returns) - 1)
        std_dev = math.sqrt(variance)

        if std_dev == 0:
            return 0.0

        # Annualize based on actual elapsed time so the factor is correct
        # regardless of cycle interval (60s production, faster in tests, etc.)
        timestamps = [ts for ts, _ in self._value_history]
        elapsed_secs = (timestamps[-1] - timestamps[0]).total_seconds()
        if elapsed_secs > 60 and len(returns) > 0:
            # periods per year = periods recorded / fraction of year elapsed
            periods_per_year = len(returns) * (365.25 * 24 * 3600) / elapsed_secs
        else:
            periods_per_year = 252 * 78  # fallback: ~5-min bars in a trading year

        annualized_return = mean_return * periods_per_year
        annualized_std = std_dev * math.sqrt(periods_per_year)

        return (annualized_return - risk_free_rate) / annualized_std if annualized_std > 0 else 0.0

    def _calculate_max_drawdown(self) -> float:
        """Calculate maximum drawdown percentage."""
        if len(self._value_history) < 2:
            return 0.0

        values = [v for _, v in self._value_history]
        peak = values[0]
        max_dd = 0.0

        for v in values:
            if v > peak:
                peak = v
            drawdown = (peak - v) / peak if peak > 0 else 0
            max_dd = max(max_dd, drawdown)

        return max_dd * 100

    def to_dict(self, prices: Dict[str, float]) -> Dict:
        """Serialize portfolio to dictionary."""
        metrics = self.calculate_metrics(prices)
        recent_trades = [
            {
                "symbol": t.symbol,
                "action": t.action,
                "shares": t.shares,
                "price": t.price,
                "timestamp": t.timestamp.isoformat(),
                "reasoning": t.reasoning,
                "pnl": t.pnl,
            }
            for t in self.trade_history[-20:]
        ]
        return {**metrics, "recent_trades": recent_trades}

    def kelly_fraction(self, half_kelly: float = 0.25) -> float:
        """
        Compute the fractional Kelly position size from realized trade history.

        Formula:  full_Kelly = (win_rate × avg_win − loss_rate × avg_loss) / avg_win
                  result     = full_Kelly × half_kelly   (default: quarter-Kelly)

        Result is clamped to [0.02, MAX_POSITION_SIZE].
        Returns the default 10 % when fewer than 10 closed trades are available.

        Parameters
        ----------
        half_kelly : float, default 0.25
            Fraction of the full Kelly to use.  0.25 = quarter-Kelly (production
            standard used by Renaissance, AQR, and Ed Thorp).
        """
        sell_trades = [t for t in self.trade_history if t.action == "SELL"]
        if len(sell_trades) < 10:
            return 0.10

        wins   = [t for t in sell_trades if t.pnl > 0]
        losses = [t for t in sell_trades if t.pnl <= 0]

        win_rate  = len(wins)   / len(sell_trades)
        loss_rate = len(losses) / len(sell_trades)

        avg_win  = (sum(t.pnl for t in wins)          / len(wins))   if wins   else 0.0
        avg_loss = (abs(sum(t.pnl for t in losses))   / len(losses)) if losses else 0.0

        if avg_win <= 0.0:
            return 0.10

        # Full Kelly: fraction of bankroll that maximises log-wealth growth
        full_kelly = (win_rate * avg_win - loss_rate * avg_loss) / avg_win

        # Apply fractional-Kelly multiplier and clamp to safe range
        result = full_kelly * half_kelly
        return float(min(config.MAX_POSITION_SIZE, max(0.02, result)))

    def get_value_history(self) -> List[Dict]:
        """Get value history for charting."""
        return [
            {"timestamp": ts.isoformat(), "value": val}
            for ts, val in self._value_history[-500:]
        ]
