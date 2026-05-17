"""
Typed dataclasses for portfolio metrics and agent state.

These replace ad-hoc dicts returned by `Portfolio.calculate_metrics()` and
`BaseAgent.get_state()`. To keep zero behavioral drift with existing
callsites (~9 dict-style patterns across main.py / ensemble_agent.py /
summary_agent.py / cnn_reasoning_agent.py / tests), each class includes a
dict shim implementing __getitem__, __setitem__, __contains__, get,
keys, __iter__, and to_dict. This means every existing access pattern
still works:

    m = portfolio.calculate_metrics(prices)
    m["total_value"]              # dict-style read           → __getitem__
    m["rank"] = 5                 # dynamic attr add (leaderboard)→ __setitem__
    "avg_mae" in m                # membership check          → __contains__
    m.get("missing", 0.0)         # safe get                  → .get
    {**m, "extra": 1}             # spread (Portfolio.to_dict)→ keys/__getitem__
    json.dumps(m.to_dict())       # JSON serialization        → to_dict

Non-frozen dataclasses are intentional: the WebSocket broadcast loop in
main.py mutates leaderboard entries via `entry["rank"] = rank`, which
requires __setitem__ to actually mutate state. `rank` is NOT a declared
field — it's a presentation-only dynamic attribute added by main.py.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Dict, Iterator, List


class _DictShim:
    """
    Mixin providing dict-style access on top of a dataclass.

    Supports:
      - obj["key"]              → getattr
      - obj["key"] = value      → setattr (allows dynamic attrs like `rank`)
      - "key" in obj            → hasattr
      - obj.get("key", default) → getattr with default
      - obj.keys()              → declared dataclass field names + any dynamic
                                   attributes that have been set
      - iter(obj)               → iter(keys())   (enables {**obj} unpacking)
      - obj.to_dict()           → plain dict of all current attributes
                                   (declared fields + dynamic adds like `rank`)
    """

    def __getitem__(self, key: str) -> Any:
        try:
            return getattr(self, key)
        except AttributeError as e:
            raise KeyError(key) from e

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        return hasattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def keys(self) -> List[str]:
        # Declared dataclass fields first (deterministic order), then any
        # extra dynamic attributes set via __setitem__ (e.g., `rank`).
        declared = [f.name for f in fields(self)]  # type: ignore[arg-type]
        declared_set = set(declared)
        extras = [
            k for k in vars(self).keys()
            if k not in declared_set and not k.startswith("_")
        ]
        return declared + extras

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys())

    def to_dict(self) -> Dict[str, Any]:
        return {k: getattr(self, k) for k in self.keys()}


# ──────────────────────────────────────────────────────────────────────────
# Portfolio.calculate_metrics return shape (16 declared fields)
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class PortfolioMetrics(_DictShim):
    total_value: float
    cash: float
    position_value: float
    total_return_pct: float
    total_return: float
    realized_pnl: float
    win_rate: float
    sharpe_ratio: float
    max_drawdown: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    positions: List[Any]
    avg_mae: float
    avg_mfe: float
    avg_captured_pct: float


# ──────────────────────────────────────────────────────────────────────────
# One entry of metrics.positions
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class PositionSummary(_DictShim):
    symbol: str
    shares: float
    avg_cost: float
    current_price: float
    current_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    entry_confidence: float
    bayes_confidence: float


# ──────────────────────────────────────────────────────────────────────────
# BaseAgent.get_state return shape (21 declared fields; `rank` is added
# dynamically by main.py:1440 on leaderboard entries and rides through the
# JSON serialization via _DictShim.to_dict / .keys)
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class AgentState(_DictShim):
    id: Any
    name: str
    strategy: str
    is_active: bool
    cash: float
    total_value: float
    position_value: float
    total_return_pct: float
    total_return: float
    realized_pnl: float
    win_rate: float
    sharpe_ratio: float
    max_drawdown: float
    total_trades: int
    positions: List[Any]
    recent_trades: List[Any]
    last_signals: Dict[str, Any]
    picks: Dict[str, Any]
    value_history: List[Any]
    avg_mae: float
    avg_mfe: float
    avg_captured_pct: float
