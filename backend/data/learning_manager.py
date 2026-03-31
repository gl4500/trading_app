"""
Learning Manager: records profitable and losing trades so ClaudeAgent
can learn from past decisions and improve over time.

The learning file (learning.json) persists across restarts and stores:
- profitable_trades: top 20 winning SELL trades with reasoning
- loss_trades:       top 10 worst losing trades with reasoning
"""
import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

LEARNING_FILE = os.path.join(os.path.dirname(__file__), '..', 'learning.json')
MAX_PROFITABLE = 20
MAX_LOSSES = 10
MAX_CATALYST_OUTCOMES = 50


def _load() -> Dict:
    if os.path.exists(LEARNING_FILE):
        try:
            with open(LEARNING_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"LearningManager: could not read learning file: {e}")
    return {"profitable_trades": [], "loss_trades": [], "catalyst_outcomes": []}


def _save(data: Dict) -> None:
    try:
        with open(LEARNING_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"LearningManager: could not write learning file: {e}")


def record_trade(
    symbol: str,
    buy_price: float,
    sell_price: float,
    pnl: float,
    pnl_pct: float,
    buy_reasoning: str,
    sell_reasoning: str,
    agent_name: str,
) -> None:
    """Record a completed trade (buy→sell pair) to the learning file."""
    data = _load()

    entry = {
        "symbol": symbol,
        "buy_price": round(buy_price, 2),
        "sell_price": round(sell_price, 2),
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "buy_reasoning": buy_reasoning[:300],
        "sell_reasoning": sell_reasoning[:300],
        "agent": agent_name,
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
    }

    if pnl > 0:
        data["profitable_trades"].append(entry)
        # Keep only top MAX_PROFITABLE by pnl_pct
        data["profitable_trades"] = sorted(
            data["profitable_trades"], key=lambda x: x["pnl_pct"], reverse=True
        )[:MAX_PROFITABLE]
    else:
        data["loss_trades"].append(entry)
        # Keep only worst MAX_LOSSES by pnl_pct (most negative first)
        data["loss_trades"] = sorted(
            data["loss_trades"], key=lambda x: x["pnl_pct"]
        )[:MAX_LOSSES]

    _save(data)
    logger.info(f"LearningManager: recorded {'profit' if pnl > 0 else 'loss'} trade "
                f"{symbol} pnl={pnl:+.2f} ({pnl_pct:+.1f}%)")


def record_catalyst_outcome(
    symbol: str,
    category: str,
    score: int,
    headline: str,
    change_open: float,
    change_1h: float,
    during_session: bool,
    confirmed: bool,
) -> None:
    """Record a confirmed news catalyst → price outcome to the learning file.

    Called once per snapshot when price_1h is frozen (1 hour after the initial
    reaction).  Builds a rolling history the AI agents can learn from — e.g.
    'macro catalysts with score >= 3 confirmed moves 70% of the time'.
    """
    data = _load()
    data.setdefault("catalyst_outcomes", [])

    entry = {
        "symbol":         symbol,
        "category":       category,
        "score":          score,
        "headline":       headline[:150],
        "change_open":    round(change_open, 2) if change_open is not None else None,
        "change_1h":      round(change_1h, 2)   if change_1h   is not None else None,
        "during_session": during_session,
        "confirmed":      confirmed,
        "date":           datetime.utcnow().strftime("%Y-%m-%d"),
    }

    data["catalyst_outcomes"].append(entry)
    # Keep only the most recent MAX_CATALYST_OUTCOMES entries
    data["catalyst_outcomes"] = data["catalyst_outcomes"][-MAX_CATALYST_OUTCOMES:]

    _save(data)
    logger.info(
        f"LearningManager: catalyst outcome recorded — {symbol} {category} "
        f"score={score} change_1h={change_1h:+.2f}% confirmed={confirmed}"
    )


def get_catalyst_summary() -> str:
    """Return a formatted string of catalyst→price outcome patterns for AI prompts.

    Groups by category, shows confirmation rate and average move size so agents
    can calibrate how much weight to give different catalyst types.
    """
    data = _load()
    outcomes = data.get("catalyst_outcomes", [])
    if not outcomes:
        return ""

    # Group by category
    from collections import defaultdict
    by_cat: Dict[str, list] = defaultdict(list)
    for o in outcomes:
        by_cat[o["category"]].append(o)

    lines = ["## Catalyst → Price Outcome History (last 50 catalysts)\n"]
    for cat, items in sorted(by_cat.items()):
        total = len(items)
        confirmed = sum(1 for o in items if o["confirmed"])
        conf_rate = confirmed / total * 100
        confirmed_items = [o for o in items if o["confirmed"] and o["change_1h"] is not None]
        avg_move = (sum(o["change_1h"] for o in confirmed_items) / len(confirmed_items)) if confirmed_items else 0.0
        recent = items[-2:]  # two most recent examples

        lines.append(
            f"### {cat.upper()} ({total} events, {conf_rate:.0f}% confirmed moves, avg +{avg_move:.1f}% when confirmed)"
        )
        for o in recent:
            tag = "intraday" if o.get("during_session") else "overnight"
            lines.append(
                f"  - [{tag}] {o['symbol']} score={o['score']}: "
                f"\"{o['headline'][:80]}\" → open={o['change_open']:+.2f}% 1h={o['change_1h']:+.2f}%"
                if o["change_1h"] is not None else
                f"  - [{tag}] {o['symbol']} score={o['score']}: \"{o['headline'][:80]}\""
            )

    return "\n".join(lines)


def get_learning_summary() -> str:
    """Return a formatted string of past learnings for injection into Claude's prompt."""
    data = _load()
    profitable = data.get("profitable_trades", [])
    losses = data.get("loss_trades", [])
    catalyst_section = get_catalyst_summary()

    if not profitable and not losses and not catalyst_section:
        return ""

    lines = ["## Past Trade Learnings (use these to inform your decisions)\n"]

    if profitable:
        lines.append("### What Worked (Profitable Trades)")
        for t in profitable[:5]:  # top 5 in prompt to keep it concise
            lines.append(
                f"- {t['symbol']} +{t['pnl_pct']:.1f}% (${t['pnl']:+.0f}): "
                f"BUY reason: {t['buy_reasoning'][:120]} | "
                f"SELL reason: {t['sell_reasoning'][:120]}"
            )

    if losses:
        lines.append("\n### What to Avoid (Loss Trades)")
        for t in losses[:5]:
            lines.append(
                f"- {t['symbol']} {t['pnl_pct']:.1f}% (${t['pnl']:+.0f}): "
                f"BUY reason: {t['buy_reasoning'][:120]} | "
                f"SELL reason: {t['sell_reasoning'][:120]}"
            )

    catalyst_section = get_catalyst_summary()
    if catalyst_section:
        lines.append("\n" + catalyst_section)

    return "\n".join(lines)
