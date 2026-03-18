"""
Daily Summary Agent: aggregates decisions made by every trading agent during
the current session and generates a human-readable narrative roll-up using Claude.

The summary covers:
  • Per-agent signal breakdown (BUY / SELL / HOLD counts + top picks)
  • Trades executed today per agent
  • Symbol consensus map — where agents agreed and disagreed
  • Portfolio performance snapshot
  • Claude-authored narrative: what happened, why, and what to watch

Call generate(agents, prices, market_context) at any time; results are cached
for CACHE_TTL seconds so the API can serve it without re-calling Claude every request.
"""
import json
import logging
import time
from datetime import datetime, date, timezone
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

CACHE_TTL_MARKET_OPEN   = 5 * 60    # refresh every 5 min during active sessions
CACHE_TTL_MARKET_CLOSED = 60 * 60   # cache for 1 hour after close (day is done)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _today_trades(agent) -> List[Dict]:
    """Return trades executed today (UTC date) for an agent."""
    today = date.today()
    out = []
    for t in agent.portfolio.trade_history:
        if t.timestamp.date() == today:
            out.append({
                "symbol":    t.symbol,
                "action":    t.action,
                "shares":    round(t.shares, 4),
                "price":     round(t.price, 2),
                "pnl":       round(t.pnl, 2) if t.pnl else None,
                "timestamp": t.timestamp.strftime("%H:%M"),
                "reasoning": t.reasoning[:150],
            })
    return out


def _agent_signal_summary(agent, prices: Dict[str, float]) -> Dict:
    """Summarise one agent's current signals, picks, and today's trades."""
    signals = agent._last_signals   # symbol → Signal
    buys  = [s for s in signals.values() if s.action == "BUY"]
    sells = [s for s in signals.values() if s.action == "SELL"]
    holds = [s for s in signals.values() if s.action == "HOLD"]

    top_picks = sorted(buys, key=lambda s: s.confidence, reverse=True)[:5]

    metrics = agent.portfolio.calculate_metrics(prices)

    return {
        "buy_count":    len(buys),
        "sell_count":   len(sells),
        "hold_count":   len(holds),
        "top_buys": [
            {
                "symbol":     s.symbol,
                "confidence": round(s.confidence, 2),
                "reasoning":  s.reasoning[:120],
            }
            for s in top_picks
        ],
        "top_sells": [
            {
                "symbol":     s.symbol,
                "confidence": round(s.confidence, 2),
                "reasoning":  s.reasoning[:120],
            }
            for s in sorted(sells, key=lambda s: s.confidence, reverse=True)[:3]
        ],
        "active_picks":   agent.get_pick_symbols(),
        "trades_today":   _today_trades(agent),
        "total_return_pct": round(metrics.get("total_return_pct", 0), 2),
        "win_rate":         round(metrics.get("win_rate", 0), 2),
        "positions":        list(agent.portfolio.positions.keys()),
    }


def _build_consensus_map(agents: Dict, exclude: set = None) -> Dict[str, Dict]:
    """
    For every symbol that at least one agent has a non-HOLD opinion on,
    compute the vote tally and overall consensus label.
    """
    exclude = exclude or {"EnsembleAgent", "SummaryAgent"}
    tally: Dict[str, Dict] = {}

    for name, agent in agents.items():
        if name in exclude:
            continue
        for sym, sig in agent._last_signals.items():
            if sig.action not in ("BUY", "SELL"):
                continue
            if sym not in tally:
                tally[sym] = {"BUY": [], "SELL": []}
            tally[sym][sig.action].append(
                {"agent": name, "confidence": round(sig.confidence, 2)}
            )

    consensus = {}
    for sym, votes in tally.items():
        buys  = votes["BUY"]
        sells = votes["SELL"]
        total = len(buys) + len(sells)
        if total == 0:
            continue
        buy_pct  = len(buys)  / total
        sell_pct = len(sells) / total

        if buy_pct >= 0.67:
            label = "STRONG BUY"
        elif buy_pct >= 0.50:
            label = "BUY"
        elif sell_pct >= 0.67:
            label = "STRONG SELL"
        elif sell_pct >= 0.50:
            label = "SELL"
        else:
            label = "SPLIT"

        consensus[sym] = {
            "consensus":  label,
            "buy_votes":  buys,
            "sell_votes": sells,
            "agreement":  round(max(buy_pct, sell_pct), 2),
        }

    return dict(sorted(consensus.items(), key=lambda x: x[1]["agreement"], reverse=True))


def _build_claude_prompt(
    agent_summaries: Dict,
    consensus_map: Dict,
    ensemble_summary: Optional[Dict],
    scanner_recs: List[Dict],
    sentinel_catalysts: List[Dict],
    prices: Dict[str, float],
    market_status: str,
) -> str:
    """Build the prompt sent to Claude for narrative generation."""

    # Agent section
    agent_lines = []
    for name, s in agent_summaries.items():
        trades_str = (
            ", ".join(
                f"{t['action']} {t['symbol']} @{t['price']}" for t in s["trades_today"]
            ) or "none"
        )
        picks_str = ", ".join(s["active_picks"]) or "none"
        agent_lines.append(
            f"  {name}: {s['buy_count']} BUY / {s['sell_count']} SELL / {s['hold_count']} HOLD  "
            f"| return {s['total_return_pct']:+.2f}%  win_rate {s['win_rate']:.0%}  "
            f"| trades today: {trades_str}  | picks: {picks_str}"
        )

    # Consensus section
    consensus_lines = []
    for sym, c in list(consensus_map.items())[:12]:
        buy_agents  = ", ".join(v["agent"] for v in c["buy_votes"])  or "—"
        sell_agents = ", ".join(v["agent"] for v in c["sell_votes"]) or "—"
        consensus_lines.append(
            f"  {sym}: {c['consensus']} (agreement {c['agreement']:.0%}) "
            f"| BUY: {buy_agents}  SELL: {sell_agents}"
        )

    # Scanner
    scanner_str = "\n".join(
        f"  {r.get('symbol')} {r.get('action')} conf={r.get('confidence', 0):.2f} — {r.get('reasoning', '')[:80]}"
        for r in scanner_recs[:6]
    ) or "  No scanner results."

    # Sentinel catalysts
    catalyst_str = "\n".join(
        f"  [{c.get('category','?').upper()}] {c.get('headline','')[:80]} (score={c.get('score')})"
        for c in sentinel_catalysts[:5]
    ) or "  No notable catalysts."

    # Ensemble stats
    ens_str = ""
    if ensemble_summary:
        ens_str = (
            f"Ensemble regime: {ensemble_summary.get('regime','?').upper()}  "
            f"| return {ensemble_summary.get('total_return_pct', 0):+.2f}%  "
            f"| win_rate {ensemble_summary.get('win_rate', 0):.0%}"
        )

    return f"""You are a senior portfolio manager. Write a concise daily roll-up for the AI trading competition.

## Market Status: {market_status.upper()}
## Date: {datetime.utcnow().strftime('%Y-%m-%d')}

## Agent Decisions Today
{chr(10).join(agent_lines)}

{ens_str}

## Symbol Consensus (top symbols with cross-agent opinions)
{chr(10).join(consensus_lines) or '  No consensus data.'}

## Scanner Recommendations
{scanner_str}

## After-Hours / Policy Catalysts
{catalyst_str}

## Your Task
Write a **daily roll-up summary** covering:
1. **Session overview** — what the agents collectively did today (2-3 sentences)
2. **Key decisions** — the most significant BUY/SELL calls and why agents agreed or disagreed (2-3 sentences)
3. **Standout agents** — which agent(s) showed the clearest conviction or best reasoning today (1-2 sentences)
4. **Watchlist for tomorrow** — symbols with the strongest consensus or upcoming catalysts to monitor (1-2 sentences)
5. **Risk note** — any concentration risk, conflicting signals, or caution flags (1-2 sentences)

Be direct and specific — name actual symbols and agents. No generic filler. Respond in plain prose (no bullet points).
"""


# ── Summary Service ───────────────────────────────────────────────────────────

class DailySummaryService:
    """
    Generates and caches a daily roll-up summary across all trading agents.
    Not a trading agent itself — read-only observer.
    """

    def __init__(self):
        self._cache: Optional[Dict] = None
        self._cache_ts: float = 0.0
        self._generating: bool = False
        self._generated_for_date: Optional[date] = None

    def _is_fresh(self, market_status: str) -> bool:
        """Cache is fresh only when it was generated today (EOD roll-up already done)."""
        if not self._cache:
            return False
        return self._generated_for_date == date.today()

    async def generate(
        self,
        agents: Dict,
        prices: Dict[str, float],
        market_status: str,
        scanner_recs: Optional[List[Dict]] = None,
        sentinel_catalysts: Optional[List[Dict]] = None,
        force: bool = False,
    ) -> Dict:
        """
        Generate (or return cached) daily summary.

        force=True bypasses the cache TTL — used when triggered by the user.
        """
        if not force and self._is_fresh(market_status):
            logger.debug("DailySummary: returning cached summary")
            return self._cache

        if self._generating:
            logger.debug("DailySummary: generation already in progress — returning cache or empty")
            return self._cache or {"status": "generating", "narrative": "Summary is being generated…"}

        self._generating = True
        try:
            result = await self._build_summary(
                agents, prices, market_status,
                scanner_recs or [],
                sentinel_catalysts or [],
            )
            self._cache              = result
            self._cache_ts           = time.time()
            self._generated_for_date = date.today()
            return result
        except Exception as e:
            logger.error(f"DailySummary: generation failed: {e}", exc_info=True)
            return self._cache or {
                "status": "error",
                "error":  str(e),
                "narrative": "Summary generation failed. Check logs.",
            }
        finally:
            self._generating = False

    async def _build_summary(
        self,
        agents: Dict,
        prices: Dict[str, float],
        market_status: str,
        scanner_recs: List[Dict],
        sentinel_catalysts: List[Dict],
    ) -> Dict:
        # ── 1. Collect per-agent summaries (skip Ensemble for consensus calc)
        SKIP = {"EnsembleAgent", "ScannerPortfolioAgent"}
        agent_summaries: Dict[str, Dict] = {}
        ensemble_summary: Optional[Dict] = None

        for name, agent in agents.items():
            if name == "EnsembleAgent":
                m = agent.portfolio.calculate_metrics(prices)
                ensemble_summary = {
                    "total_return_pct": round(m.get("total_return_pct", 0), 2),
                    "win_rate":         round(m.get("win_rate", 0), 2),
                    "regime":           getattr(agent, "_regime", "unknown"),
                }
                continue
            if name in SKIP:
                continue
            agent_summaries[name] = _agent_signal_summary(agent, prices)

        # ── 2. Consensus map
        consensus_map = _build_consensus_map(agents)

        # ── 3. Overall portfolio stats (best agent by return)
        ranked = sorted(
            [
                (name, s["total_return_pct"])
                for name, s in agent_summaries.items()
            ],
            key=lambda x: x[1],
            reverse=True,
        )

        # ── 4. All trades today across all agents
        all_trades_today: List[Dict] = []
        for name, agent in agents.items():
            for t in _today_trades(agent):
                t["agent"] = name
                all_trades_today.append(t)
        all_trades_today.sort(key=lambda t: t["timestamp"])

        # ── 5. Narrative via Claude
        narrative = await self._get_narrative(
            agent_summaries, consensus_map, ensemble_summary,
            scanner_recs, sentinel_catalysts, prices, market_status,
        )

        return {
            "status":            "ok",
            "generated_at":      datetime.utcnow().isoformat(),
            "date":              datetime.utcnow().strftime("%Y-%m-%d"),
            "market_status":     market_status,
            "agent_summaries":   agent_summaries,
            "consensus":         consensus_map,
            "leaderboard":       ranked,
            "trades_today":      all_trades_today,
            "ensemble":          ensemble_summary,
            "scanner_recs":      scanner_recs[:6],
            "sentinel_catalysts": sentinel_catalysts[:5],
            "narrative":         narrative,
        }

    def get_live_data(
        self,
        agents: Dict,
        prices: Dict[str, float],
        market_status: str,
        scanner_recs: Optional[List[Dict]] = None,
        sentinel_catalysts: Optional[List[Dict]] = None,
    ) -> Dict:
        """
        Instantly compute structured summary data from current agent state.
        No Claude API call — suitable for inclusion in every WebSocket broadcast.
        Returns the same shape as generate() except there is no 'narrative' field.
        """
        SKIP = {"EnsembleAgent", "ScannerPortfolioAgent"}
        agent_summaries: Dict[str, Dict] = {}
        ensemble_summary = None

        for name, agent in agents.items():
            if name == "EnsembleAgent":
                try:
                    m = agent.portfolio.calculate_metrics(prices)
                    ensemble_summary = {
                        "total_return_pct": round(m.get("total_return_pct", 0), 2),
                        "win_rate":         round(m.get("win_rate", 0), 2),
                        "regime":           getattr(agent, "_regime", "unknown"),
                    }
                except Exception:
                    pass
                continue
            if name in SKIP:
                continue
            try:
                agent_summaries[name] = _agent_signal_summary(agent, prices)
            except Exception:
                pass

        consensus_map = _build_consensus_map(agents)

        ranked = sorted(
            [(name, s["total_return_pct"]) for name, s in agent_summaries.items()],
            key=lambda x: x[1],
            reverse=True,
        )

        all_trades_today: List[Dict] = []
        for name, agent in agents.items():
            try:
                for t in _today_trades(agent):
                    t["agent"] = name
                    all_trades_today.append(t)
            except Exception:
                pass
        all_trades_today.sort(key=lambda t: t["timestamp"])

        return {
            "status":             "ok",
            "generated_at":       datetime.utcnow().isoformat(),
            "date":               datetime.utcnow().strftime("%Y-%m-%d"),
            "market_status":      market_status,
            "agent_summaries":    agent_summaries,
            "consensus":          consensus_map,
            "leaderboard":        ranked,
            "trades_today":       all_trades_today,
            "ensemble":           ensemble_summary,
            "scanner_recs":       (scanner_recs or [])[:6],
            "sentinel_catalysts": (sentinel_catalysts or [])[:5],
        }

    async def _get_narrative(
        self,
        agent_summaries: Dict,
        consensus_map: Dict,
        ensemble_summary: Optional[Dict],
        scanner_recs: List[Dict],
        sentinel_catalysts: List[Dict],
        prices: Dict[str, float],
        market_status: str,
    ) -> str:
        """Call Claude to write the narrative roll-up. Falls back to a structured text if unavailable."""
        try:
            from config import config
            import anthropic

            if not config.ANTHROPIC_API_KEY:
                raise RuntimeError("No ANTHROPIC_API_KEY")

            client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
            prompt = _build_claude_prompt(
                agent_summaries, consensus_map, ensemble_summary,
                scanner_recs, sentinel_catalysts, prices, market_status,
            )

            response = await client.messages.create(
                model="claude-opus-4-6",
                max_tokens=1200,
                messages=[{"role": "user", "content": prompt}],
            )
            for block in response.content:
                if block.type == "text":
                    return block.text.strip()

        except Exception as e:
            logger.warning(f"DailySummary: Claude narrative failed ({e}), using fallback")

        # ── Fallback: structured text summary without Claude
        lines = [
            f"Daily Roll-Up — {datetime.utcnow().strftime('%Y-%m-%d')} ({market_status.upper()})",
            "",
        ]
        for name, s in agent_summaries.items():
            lines.append(
                f"{name}: {s['buy_count']} BUY, {s['sell_count']} SELL, {s['hold_count']} HOLD "
                f"| return {s['total_return_pct']:+.2f}%"
            )
        if consensus_map:
            top = list(consensus_map.items())[:5]
            lines.append("")
            lines.append("Top consensus symbols: " + ", ".join(f"{s} ({d['consensus']})" for s, d in top))
        return "\n".join(lines)


# ── Module-level singleton ─────────────────────────────────────────────────────

daily_summary = DailySummaryService()
