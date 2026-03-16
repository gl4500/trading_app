"""
Drift Detector: monitors agent performance over rolling windows and flags
degradation vs the agent's own historical baseline.

Metrics tracked per agent:
  - win_rate        : % of SELL trades with positive PnL
  - avg_pnl_pct     : average PnL % per closed trade
  - sharpe_proxy    : mean/std of per-trade PnL (sign of risk-adj return)

A drift alert is raised when the RECENT window (last N trades) is
significantly worse than the agent's ALL-TIME baseline.
"""
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

RECENT_WINDOW = 10        # trades to consider "recent"
MIN_TRADES_BASELINE = 5   # minimum total trades before drift can be assessed
WIN_RATE_DROP_THRESHOLD = 20.0    # percentage points drop triggers alert
AVG_PNL_DROP_THRESHOLD  = 2.0    # percentage points drop triggers alert


@dataclass
class DriftReport:
    agent_name: str
    is_drifting: bool
    alerts: List[str]
    baseline_win_rate: float
    recent_win_rate: float
    baseline_avg_pnl_pct: float
    recent_avg_pnl_pct: float
    total_trades: int
    recent_trades: int

    def to_dict(self) -> Dict:
        return {
            "agent_name": self.agent_name,
            "is_drifting": self.is_drifting,
            "alerts": self.alerts,
            "baseline_win_rate": round(self.baseline_win_rate, 1),
            "recent_win_rate": round(self.recent_win_rate, 1),
            "win_rate_change": round(self.recent_win_rate - self.baseline_win_rate, 1),
            "baseline_avg_pnl_pct": round(self.baseline_avg_pnl_pct, 2),
            "recent_avg_pnl_pct": round(self.recent_avg_pnl_pct, 2),
            "avg_pnl_change": round(self.recent_avg_pnl_pct - self.baseline_avg_pnl_pct, 2),
            "total_trades": self.total_trades,
            "recent_window": self.recent_trades,
        }


def _win_rate(sell_trades: list) -> float:
    if not sell_trades:
        return 0.0
    wins = sum(1 for t in sell_trades if t.pnl > 0)
    return wins / len(sell_trades) * 100


def _avg_pnl_pct(sell_trades: list) -> float:
    if not sell_trades:
        return 0.0
    pnl_pcts = []
    for t in sell_trades:
        cost = t.price - (t.pnl / t.shares) if t.shares > 0 else t.price
        if cost > 0:
            pnl_pcts.append(t.pnl / (cost * t.shares) * 100)
    return sum(pnl_pcts) / len(pnl_pcts) if pnl_pcts else 0.0


def check_drift(agent) -> DriftReport:
    """
    Analyse an agent's trade history and return a DriftReport.
    Pass any agent that has a .portfolio.trade_history list of TradeRecord.
    """
    all_sells = [t for t in agent.portfolio.trade_history if t.action == "SELL"]
    total = len(all_sells)

    if total < MIN_TRADES_BASELINE:
        return DriftReport(
            agent_name=agent.name,
            is_drifting=False,
            alerts=[f"Not enough trades yet ({total}/{MIN_TRADES_BASELINE} minimum)"],
            baseline_win_rate=0, recent_win_rate=0,
            baseline_avg_pnl_pct=0, recent_avg_pnl_pct=0,
            total_trades=total, recent_trades=0,
        )

    recent_sells = all_sells[-RECENT_WINDOW:]
    baseline_sells = all_sells  # all-time

    base_wr  = _win_rate(baseline_sells)
    rec_wr   = _win_rate(recent_sells)
    base_pnl = _avg_pnl_pct(baseline_sells)
    rec_pnl  = _avg_pnl_pct(recent_sells)

    alerts = []

    if base_wr - rec_wr >= WIN_RATE_DROP_THRESHOLD:
        alerts.append(
            f"Win rate dropped {base_wr - rec_wr:.1f}pp "
            f"(all-time {base_wr:.1f}% → recent {rec_wr:.1f}%)"
        )

    if base_pnl - rec_pnl >= AVG_PNL_DROP_THRESHOLD:
        alerts.append(
            f"Avg PnL/trade dropped {base_pnl - rec_pnl:.2f}pp "
            f"(all-time {base_pnl:.2f}% → recent {rec_pnl:.2f}%)"
        )

    if alerts:
        logger.warning(f"DRIFT DETECTED [{agent.name}]: {' | '.join(alerts)}")

    return DriftReport(
        agent_name=agent.name,
        is_drifting=bool(alerts),
        alerts=alerts,
        baseline_win_rate=base_wr,
        recent_win_rate=rec_wr,
        baseline_avg_pnl_pct=base_pnl,
        recent_avg_pnl_pct=rec_pnl,
        total_trades=total,
        recent_trades=len(recent_sells),
    )


def check_all_agents(agents: Dict) -> List[Dict]:
    """Run drift check on all agents and return list of report dicts."""
    reports = []
    for agent in agents.values():
        try:
            report = check_drift(agent)
            reports.append(report.to_dict())
        except Exception as e:
            logger.error(f"Drift check failed for {agent.name}: {e}")
    return reports
