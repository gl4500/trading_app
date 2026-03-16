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


def _load() -> Dict:
    if os.path.exists(LEARNING_FILE):
        try:
            with open(LEARNING_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"LearningManager: could not read learning file: {e}")
    return {"profitable_trades": [], "loss_trades": []}


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


def get_learning_summary() -> str:
    """Return a formatted string of past learnings for injection into Claude's prompt."""
    data = _load()
    profitable = data.get("profitable_trades", [])
    losses = data.get("loss_trades", [])

    if not profitable and not losses:
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

    return "\n".join(lines)
