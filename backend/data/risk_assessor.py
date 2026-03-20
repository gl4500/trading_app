"""
Risk Assessor: tracks regime calls, churn, and sector concentration.
Provides periodic assessments and learning feedback for AI agents.
Persists to risk_assessment.json.
"""
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

ASSESSMENT_FILE = os.path.join(os.path.dirname(__file__), '..', 'risk_assessment.json')
CHURN_WINDOW_MINUTES = 60
CHURN_TRADE_THRESHOLD = 3


def _get_data() -> Dict:
    if os.path.exists(ASSESSMENT_FILE):
        try:
            with open(ASSESSMENT_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.debug(f"RiskAssessor: read error: {e}")
    return {}


def _save(d: Dict) -> None:
    try:
        with open(ASSESSMENT_FILE, 'w') as f:
            json.dump(d, f, indent=2)
    except Exception as e:
        logger.error(f"RiskAssessor: write error: {e}")


def record_trade(agent: str, symbol: str, action: str) -> None:
    """Record a trade for churn detection."""
    d = _get_data()
    key = f"{agent}:{symbol}"
    d.setdefault("trade_log", {}).setdefault(key, [])
    d["trade_log"][key].append({
        "action": action,
        "timestamp": datetime.utcnow().isoformat(),
    })
    d["trade_log"][key] = d["trade_log"][key][-30:]
    _save(d)


def record_regime(regime: str, market_prices: Dict[str, float]) -> None:
    """Record a regime detection call."""
    d = _get_data()
    entry = {
        "regime": regime,
        "timestamp": datetime.utcnow().isoformat(),
        "prices": {k: round(v, 2) for k, v in list(market_prices.items())[:5]},
        "outcome_pct": None,
    }
    d.setdefault("regime_log", []).append(entry)
    d["regime_log"] = d["regime_log"][-200:]
    _save(d)


def update_regime_outcomes(current_prices: Dict[str, float]) -> None:
    """Fill outcome_pct for regime calls that are 1-24h old."""
    d = _get_data()
    changed = False
    now = datetime.utcnow()
    for entry in d.get("regime_log", []):
        if entry.get("outcome_pct") is not None:
            continue
        try:
            ts = datetime.fromisoformat(entry["timestamp"])
        except (ValueError, KeyError):
            continue
        age_hours = (now - ts).total_seconds() / 3600
        if age_hours < 1 or age_hours > 24:
            continue
        then_prices = entry.get("prices", {})
        common = [s for s in then_prices if s in current_prices and then_prices[s] > 0]
        if common:
            changes = [(current_prices[s] - then_prices[s]) / then_prices[s] for s in common]
            entry["outcome_pct"] = round(sum(changes) / len(changes) * 100, 2)
            changed = True
    if changed:
        _save(d)


def assess_churn(window_minutes: int = CHURN_WINDOW_MINUTES) -> List[Dict]:
    """Return agent:symbol pairs with excessive trade frequency."""
    d = _get_data()
    cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)
    issues = []
    for key, trades in d.get("trade_log", {}).items():
        recent = []
        for t in trades:
            try:
                if datetime.fromisoformat(t["timestamp"]) > cutoff:
                    recent.append(t)
            except (ValueError, KeyError):
                pass
        if len(recent) >= CHURN_TRADE_THRESHOLD:
            agent, symbol = key.split(":", 1)
            issues.append({
                "type": "churn",
                "agent": agent,
                "symbol": symbol,
                "trades_in_window": len(recent),
                "window_minutes": window_minutes,
            })
    return issues


def assess_regime_accuracy() -> List[Dict]:
    """Return recent TRENDING calls that were followed by market declines."""
    d = _get_data()
    issues = []
    for entry in d.get("regime_log", []):
        if entry.get("outcome_pct") is None:
            continue
        if entry["regime"] == "trending" and entry["outcome_pct"] < -1.5:
            issues.append({
                "type": "false_trending",
                "timestamp": entry["timestamp"],
                "outcome_pct": entry["outcome_pct"],
            })
    return issues[-10:]


def run_periodic_assessment(agents: Dict, prices: Dict[str, float]) -> List[Dict]:
    """Run full assessment: churn + sector concentration + regime accuracy."""
    from data.stock_universe import get_sector
    issues = []
    update_regime_outcomes(prices)
    issues.extend(assess_churn())
    issues.extend(assess_regime_accuracy())
    for agent_name, agent in agents.items():
        try:
            sector_totals: Dict[str, float] = defaultdict(float)
            total = agent.portfolio.get_total_value(prices)
            if total <= 0:
                continue
            for sym, pos in agent.portfolio.positions.items():
                price = prices.get(sym, pos.avg_cost)
                sector = get_sector(sym)
                sector_totals[sector] += pos.current_value(price)
            for sector, val in sector_totals.items():
                pct = val / total * 100
                if pct > 30:
                    issues.append({
                        "type": "sector_concentration",
                        "agent": agent_name,
                        "sector": sector,
                        "pct": round(pct, 1),
                    })
        except Exception as e:
            logger.debug(f"RiskAssessor: assessment error for {agent_name}: {e}")
    if issues:
        logger.warning(
            f"RiskAssessor: {len(issues)} risk issue(s): "
            + ", ".join(
                f"{i['type']}({i.get('agent','')}/"
                f"{i.get('symbol', i.get('sector',''))})"
                for i in issues
            )
        )
    return issues


def get_assessment_context() -> str:
    """Return formatted risk alert string for injection into AI prompts."""
    churn = assess_churn()
    regime_issues = assess_regime_accuracy()
    if not churn and not regime_issues:
        return ""
    lines = ["\n## Risk Assessment Alerts"]
    if churn:
        lines.append("### Churn Detected — Hyperactive Trading")
        for c in churn[:3]:
            lines.append(
                f"- {c['agent']} on {c['symbol']}: {c['trades_in_window']} trades "
                f"in last {c['window_minutes']}min — broken signal loop, "
                f"do not chase momentum on this name"
            )
    if regime_issues:
        lines.append("### Regime Errors — Past TRENDING Calls Were Wrong")
        for r in regime_issues[:3]:
            lines.append(
                f"- TRENDING called {r['timestamp'][:16]} but market moved "
                f"{r['outcome_pct']:+.1f}% — be cautious about momentum signals"
            )
    return "\n".join(lines)
