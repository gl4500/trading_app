"""
Agent performance tracker — queries trading.db for per-agent metrics and
exposes normalized 0-1 scores used to weight agent signals in:
  1. Signal-model training sample weighting
  2. Ollama reasoning prompt enrichment (XGBReasoningAgent)

Refreshes at most every REFRESH_INTERVAL seconds so the DB is not hit
on every 60-second trading cycle.
"""
import asyncio
import logging
import math
import time
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

REFRESH_INTERVAL = 300   # seconds between DB queries (5 min)

# Ensemble voters tracked for performance scoring.
# GeminiAgent is context-only (not a voter) — excluded.
_VOTER_AGENTS = [
    "ClaudeAgent",
    "TechAgent",
    "SentimentAgent",
    "MomentumAgent",
    "MeanReversionAgent",
    "HistoricalTrendsAgent",
    "XGBReasoningAgent",
    "ScannerPortfolioAgent",
]

_DEFAULT_SCORE = 0.5   # neutral score used when data is insufficient

try:
    import aiosqlite
except ImportError:
    aiosqlite = None   # type: ignore


class AgentPerformanceTracker:
    """
    Tracks and normalises per-agent performance from trading.db.

    Provides:
      get_scores()         — async; returns Dict[name, 0-1 score]
      get_cached_scores()  — sync;  returns last cached scores (no DB hit)
      consensus_score()    — performance-weighted directional vote  (-1 to +1)
      agreement_fraction() — fraction of agents that agree on plurality direction
      top_agent()          — highest-scoring agent with a non-HOLD signal
      get_metrics_summary()— raw metrics + score for display in prompts
    """

    def __init__(self):
        self._scores:       Dict[str, float] = {}
        self._metrics:      Dict[str, Dict]  = {}
        self._last_refresh: float            = 0.0
        self._lock                           = asyncio.Lock()

    # ── DB refresh ────────────────────────────────────────────────────────────

    async def refresh(self) -> None:
        """Query trading.db and recompute per-agent scores. Idempotent."""
        if aiosqlite is None:
            logger.warning("AgentPerformanceTracker: aiosqlite not available")
            return

        try:
            from database import DB_PATH

            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row

                # Most recent performance row per agent (win_rate, sharpe_ratio)
                cursor = await db.execute("""
                    SELECT a.name,
                           p.win_rate,
                           p.sharpe_ratio,
                           p.total_return_pct
                    FROM agents a
                    JOIN performance p ON p.agent_id = a.id
                    WHERE p.id IN (
                        SELECT MAX(p2.id) FROM performance p2
                        GROUP BY p2.agent_id
                    )
                """)
                perf_rows = await cursor.fetchall()

                # Trade counts per agent
                cursor = await db.execute("""
                    SELECT a.name, COUNT(t.id) AS trade_count
                    FROM agents a
                    LEFT JOIN trades t ON t.agent_id = a.id
                    GROUP BY a.id, a.name
                """)
                trade_rows = await cursor.fetchall()

            trade_counts = {r["name"]: int(r["trade_count"] or 0) for r in trade_rows}

            metrics: Dict[str, Dict] = {}
            for row in perf_rows:
                name = row["name"]
                metrics[name] = {
                    "win_rate":         float(row["win_rate"] or 0.0),
                    "sharpe_ratio":     float(row["sharpe_ratio"] or 0.0),
                    "total_return_pct": float(row["total_return_pct"] or 0.0),
                    "trade_count":      trade_counts.get(name, 0),
                }

            self._metrics = metrics
            self._scores  = self._compute_scores(metrics)
            self._last_refresh = time.time()

        except Exception as exc:
            logger.warning(f"AgentPerformanceTracker.refresh failed: {exc}")

    def _compute_scores(self, metrics: Dict[str, Dict]) -> Dict[str, float]:
        """Normalize DB metrics to 0-1 performance scores per agent."""
        scores: Dict[str, float] = {}

        for name, m in metrics.items():
            trade_count = int(m.get("trade_count", 0))
            if trade_count < 5:
                # Not enough history — use neutral score
                scores[name] = _DEFAULT_SCORE
                continue

            # win_rate stored as 0-100 in DB
            win_rate_norm = min(1.0, max(0.0, m["win_rate"] / 100.0))

            # Sharpe: clamp [-2, +3] → [0, 1]
            sharpe_norm = min(1.0, max(0.0, (m["sharpe_ratio"] + 2.0) / 5.0))

            # Log-scale trade count: log10(10)=1, log10(100)=2; clamp to [0, 1] by /2
            trade_norm = min(1.0, math.log10(max(1, trade_count)) / 2.0)

            score = 0.5 * win_rate_norm + 0.3 * sharpe_norm + 0.2 * trade_norm
            scores[name] = round(min(1.0, max(0.0, score)), 4)

        return scores

    # ── public accessors ──────────────────────────────────────────────────────

    async def get_scores(self) -> Dict[str, float]:
        """Return normalized 0-1 performance scores, refreshing DB if stale."""
        async with self._lock:
            if time.time() - self._last_refresh >= REFRESH_INTERVAL:
                await self.refresh()
        if self._scores:
            return dict(self._scores)
        return {n: _DEFAULT_SCORE for n in _VOTER_AGENTS}

    def get_cached_scores(self) -> Dict[str, float]:
        """Synchronous access to last cached scores — no DB query."""
        if self._scores:
            return dict(self._scores)
        return {n: _DEFAULT_SCORE for n in _VOTER_AGENTS}

    # ── signal aggregation helpers ────────────────────────────────────────────

    def consensus_score(
        self,
        agent_signals: Dict[str, Tuple[str, float]],
    ) -> float:
        """
        Performance-weighted directional consensus.

        BUY = +1, SELL = -1, HOLD = 0
        Returns -1.0 to +1.0.

        Parameters
        ----------
        agent_signals : {agent_name: (action, confidence)}
        """
        scores        = self.get_cached_scores()
        total_weight  = 0.0
        weighted_vote = 0.0

        for name, (action, confidence) in agent_signals.items():
            w         = scores.get(name, _DEFAULT_SCORE)
            direction = 1.0 if action == "BUY" else (-1.0 if action == "SELL" else 0.0)
            weighted_vote += direction * float(confidence) * w
            total_weight  += w

        if total_weight < 1e-9:
            return 0.0
        return float(max(-1.0, min(1.0, weighted_vote / total_weight)))

    def agreement_fraction(
        self,
        agent_signals: Dict[str, Tuple[str, float]],
    ) -> float:
        """
        Fraction of agents that vote for the plurality direction.
        Returns 0.0 to 1.0.
        """
        if not agent_signals:
            return 0.0
        counts: Dict[str, int] = {}
        for _, (action, _) in agent_signals.items():
            counts[action] = counts.get(action, 0) + 1
        plurality = max(counts.values())
        return float(plurality / len(agent_signals))

    def top_agent(
        self,
        agent_signals: Dict[str, Tuple[str, float]],
    ) -> Optional[Tuple[str, str, float]]:
        """
        Return (agent_name, action, confidence) for the highest-scoring
        agent with a non-HOLD signal.  Returns None if all agents HOLD.
        """
        scores     = self.get_cached_scores()
        best_score = -1.0
        best: Optional[Tuple[str, str, float]] = None

        for name, (action, confidence) in agent_signals.items():
            if action == "HOLD":
                continue
            s = scores.get(name, _DEFAULT_SCORE)
            if s > best_score:
                best_score = s
                best       = (name, action, float(confidence))
        return best

    def get_metrics_summary(self) -> Dict[str, Dict]:
        """Return raw metrics + normalized score — used in Ollama prompts."""
        scores = self.get_cached_scores()
        result: Dict[str, Dict] = {}
        for name in _VOTER_AGENTS:
            m = self._metrics.get(name, {})
            result[name] = {
                "win_rate":     m.get("win_rate",     0.0),
                "sharpe_ratio": m.get("sharpe_ratio", 0.0),
                "trade_count":  m.get("trade_count",  0),
                "score":        scores.get(name, _DEFAULT_SCORE),
            }
        return result


# Module-level singleton imported by xgb_reasoning_agent and main.py
agent_performance_tracker = AgentPerformanceTracker()
