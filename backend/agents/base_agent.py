"""
Abstract base class for all trading agents.
"""
import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime

from config import config
from trading.portfolio import Portfolio
from trading.risk_manager import RiskManager

logger = logging.getLogger(__name__)

# Shared picks persistence file — one file, one section per agent
_PICKS_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "agent_picks.json")


@dataclass
class Signal:
    """Trading signal produced by an agent's analysis."""
    action: str          # "BUY", "SELL", or "HOLD"
    symbol: str
    confidence: float    # 0.0 to 1.0
    shares: float        # number of shares to trade
    reasoning: str       # explanation of the decision
    agent_name: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def is_actionable(self) -> bool:
        return self.action in ("BUY", "SELL") and self.shares > 0 and self.confidence > 0


class BaseAgent(ABC):
    """Abstract base class for all AI trading agents."""

    def __init__(self, name: str, strategy_description: str):
        self.name = name
        self.strategy_description = strategy_description
        self.agent_id: Optional[int] = None  # set after DB registration
        self.portfolio = Portfolio(starting_capital=config.STARTING_CAPITAL)
        self.risk_manager = RiskManager()
        self._last_reasoning: Dict[str, str] = {}
        self._last_signals: Dict[str, Signal] = {}
        self._error_count: int = 0
        self._max_errors: int = 5
        self._is_active: bool = True
        self._lock = asyncio.Lock()
        # Persistent picks: symbol → {action, confidence, reasoning, added_at, last_updated}
        # Survives scanner cache expiry and app restarts — each agent owns its own conviction.
        self._picks: Dict[str, Dict] = {}
        self._load_picks()

    # ── Picks persistence ────────────────────────────────────────────────────

    def _load_picks(self) -> None:
        """Load this agent's persisted picks from the shared picks file."""
        try:
            if not os.path.exists(_PICKS_FILE):
                return
            with open(_PICKS_FILE) as f:
                all_picks = json.load(f)
            self._picks = all_picks.get(self.name, {})
            if self._picks:
                logger.info(f"{self.name}: loaded {len(self._picks)} persisted picks: {list(self._picks)}")
        except Exception as e:
            logger.warning(f"{self.name}: could not load picks: {e}")

    def _save_picks(self) -> None:
        """Merge this agent's picks into the shared file and write to disk."""
        try:
            all_picks: Dict = {}
            if os.path.exists(_PICKS_FILE):
                with open(_PICKS_FILE) as f:
                    all_picks = json.load(f)
            all_picks[self.name] = self._picks
            os.makedirs(os.path.dirname(_PICKS_FILE), exist_ok=True)
            with open(_PICKS_FILE, "w") as f:
                json.dump(all_picks, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"{self.name}: could not save picks: {e}")

    def get_pick_symbols(self) -> List[str]:
        """Return symbols this agent currently has BUY conviction on."""
        return [sym for sym, p in self._picks.items() if p.get("action") == "BUY"]

    def _update_picks(self, signals: List["Signal"]) -> None:
        """
        Reconcile the agent's pick memory with the latest signals.

        Rules:
          BUY signal  → add or refresh pick (agent has conviction)
          SELL signal → remove pick (agent is exiting)
          HOLD signal → keep existing pick if present (agent hasn't changed mind)
          No signal   → picks for symbols not analysed this cycle are left unchanged
        """
        changed = False
        now = datetime.utcnow().isoformat()

        for signal in signals:
            sym = signal.symbol
            if signal.action == "BUY":
                existing = self._picks.get(sym, {})
                self._picks[sym] = {
                    "action":       "BUY",
                    "confidence":   signal.confidence,
                    "reasoning":    signal.reasoning[:200],
                    "added_at":     existing.get("added_at", now),
                    "last_updated": now,
                }
                changed = True
            elif signal.action == "SELL" and sym in self._picks:
                del self._picks[sym]
                changed = True

        if changed:
            self._save_picks()

    # ── Abstract interface ───────────────────────────────────────────────────

    @abstractmethod
    async def analyze(self, market_context: Dict) -> List[Signal]:
        """
        Analyze market data and generate trading signals.

        Args:
            market_context: Dict of {symbol: {bars: DataFrame, stats: dict, price: float}}

        Returns:
            List of Signal objects (one per symbol considered)
        """
        ...

    async def run_cycle(self, market_context: Dict, prices: Dict[str, float]) -> List[Signal]:
        """
        Run one full trading cycle: analyze + execute signals.
        Returns the list of signals generated.
        """
        if not self._is_active:
            return []

        async with self._lock:
            try:
                # Reset daily tracking
                self.portfolio.reset_daily_tracking(prices)

                # Check daily loss limit
                if not self.risk_manager.check_daily_loss(self.portfolio, prices):
                    logger.info(f"{self.name}: Trading halted due to daily loss limit")
                    return []

                # Generate signals
                signals = await self.analyze(market_context)
                self._error_count = 0  # reset on success

                # Update persistent pick memory before executing
                self._update_picks(signals)

                # Prune stale symbols from _last_signals
                current_symbols = {s for s, v in market_context.items() if isinstance(v, dict)}
                for stale in [k for k in self._last_signals if k not in current_symbols]:
                    del self._last_signals[stale]

                # Execute actionable signals
                executed = []
                for signal in signals:
                    signal.agent_name = self.name
                    self._last_signals[signal.symbol] = signal

                    if signal.is_actionable():
                        success = await self._execute_signal(signal, prices)
                        if success:
                            executed.append(signal)

                # Record portfolio value
                self.portfolio.record_value(prices)

                return signals

            except Exception as e:
                self._error_count += 1
                logger.error(f"{self.name} error in run_cycle: {e}", exc_info=True)
                if self._error_count >= self._max_errors:
                    logger.error(f"{self.name}: Too many errors, deactivating")
                    self._is_active = False
                return []

    async def _execute_signal(self, signal: Signal, prices: Dict[str, float]) -> bool:
        """Execute a trading signal after risk checks."""
        price = prices.get(signal.symbol)
        if not price or price <= 0:
            logger.warning(f"{self.name}: No price for {signal.symbol}")
            return False

        if signal.action == "BUY":
            allowed, reason = self.risk_manager.check_buy_allowed(
                signal.symbol, signal.shares, price, self.portfolio, prices
            )
            if not allowed:
                logger.debug(f"{self.name}: Buy rejected for {signal.symbol}: {reason}")
                return False

            success = self.portfolio.execute_buy(
                signal.symbol, signal.shares, price, signal.reasoning
            )
            if success:
                logger.info(f"{self.name}: BUY {signal.shares:.2f} {signal.symbol} @ ${price:.2f} | {signal.reasoning[:80]}")
            return success

        elif signal.action == "SELL":
            allowed, reason = self.risk_manager.check_sell_allowed(
                signal.symbol, signal.shares, self.portfolio
            )
            if not allowed:
                logger.debug(f"{self.name}: Sell rejected for {signal.symbol}: {reason}")
                return False

            success = self.portfolio.execute_sell(
                signal.symbol, signal.shares, price, signal.reasoning
            )
            if success:
                logger.info(f"{self.name}: SELL {signal.shares:.2f} {signal.symbol} @ ${price:.2f} | {signal.reasoning[:80]}")
            return success

        return False

    def get_portfolio_value(self, prices: Dict[str, float]) -> float:
        """Get current total portfolio value."""
        return self.portfolio.get_total_value(prices)

    def get_performance_metrics(self, prices: Dict[str, float]) -> Dict:
        """Get performance metrics for the agent."""
        return self.portfolio.calculate_metrics(prices)

    def get_state(self, prices: Dict[str, float]) -> Dict:
        """Get complete agent state for API responses."""
        metrics = self.portfolio.calculate_metrics(prices)

        # Recent trades
        recent_trades = [
            {
                "symbol": t.symbol,
                "action": t.action,
                "shares": t.shares,
                "price": t.price,
                "timestamp": t.timestamp.isoformat(),
                "reasoning": t.reasoning[:200],
                "pnl": t.pnl,
            }
            for t in self.portfolio.trade_history[-10:]
        ]

        # Last signals
        last_signals = {
            sym: {
                "action": sig.action,
                "confidence": sig.confidence,
                "reasoning": sig.reasoning[:200],
                "timestamp": sig.timestamp.isoformat(),
            }
            for sym, sig in self._last_signals.items()
        }

        return {
            "id": self.agent_id,
            "name": self.name,
            "strategy": self.strategy_description,
            "is_active": self._is_active,
            "cash": self.portfolio.cash,
            "total_value": metrics["total_value"],
            "position_value": metrics["position_value"],
            "total_return_pct": metrics["total_return_pct"],
            "total_return": metrics["total_return"],
            "win_rate": metrics["win_rate"],
            "sharpe_ratio": metrics["sharpe_ratio"],
            "max_drawdown": metrics["max_drawdown"],
            "total_trades": metrics["total_trades"],
            "positions": metrics["positions"],
            "recent_trades": recent_trades,
            "last_signals": last_signals,
            "picks": dict(self._picks),
            "value_history": self.portfolio.get_value_history(),
            "avg_mae": metrics.get("avg_mae", 0.0),
            "avg_mfe": metrics.get("avg_mfe", 0.0),
            "avg_captured_pct": metrics.get("avg_captured_pct", 0.0),
        }

    def reset(self) -> None:
        """Reset agent to initial state."""
        self.portfolio = Portfolio(starting_capital=config.STARTING_CAPITAL)
        self.risk_manager = RiskManager()
        self._last_reasoning = {}
        self._last_signals = {}
        self._picks = {}
        self._save_picks()
        self._error_count = 0
        self._is_active = True
        self.agent_id = None
        logger.info(f"{self.name}: Reset complete")
