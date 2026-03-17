"""
WatchlistManager — fluid watchlist ranked by projected rate of return.

The pool of candidate symbols is built from:
  1. Scanner recommendations (AI-scored: confidence × price-target upside)
  2. Scanner pre-screen candidates (momentum-scored)
  3. Config seed symbols (WATCHLIST) — fallback when no scanner data
  4. Anchor symbols (WATCHLIST_ANCHORS) — always included (e.g. SPY)

Ranking metric (projected_return_score):
  BUY  with target : confidence × (1 + max(0, price_target_upside))  → [0, ~2]
  BUY  no target   : confidence × 1.0                                → [0, 1]
  SELL             : −confidence                                      → [−1, 0]
  WATCH            : 0.3 × confidence                                 → [0, 0.3]
  Candidate only   : normalised_momentum × 0.5                       → [0, 0.5]
  Anchor / seed    : 0.0 (included by policy, not by score)

Active watchlist = anchors ∪ top-N from scored pool, seeds fill remaining slots.
  where N = WATCHLIST_SIZE − len(anchors already used)
"""
import logging
import time
from typing import Dict, List, Set

from config import config

logger = logging.getLogger(__name__)


class WatchlistManager:
    """Maintains a fluid watchlist ranked by projected rate of return."""

    def __init__(self) -> None:
        self._scored_pool: List[Dict] = []
        self._prices: Dict[str, float] = {}
        self._updated_at: float = 0.0

    # ── Public API ─────────────────────────────────────────────────────────────

    def update_from_scan(self, scan_result: Dict) -> None:
        """
        Rebuild the scored pool from a completed scanner result.
        Safe to call with None or error-status results — no-ops gracefully.
        """
        if not scan_result or scan_result.get("status") != "ok":
            return

        recs = scan_result.get("recommendations", [])
        candidates = scan_result.get("candidates", [])

        # Cache prices from candidates so we can compute upside later
        for c in candidates:
            sym = c.get("symbol")
            price = c.get("price", 0)
            if sym and price > 0:
                self._prices[sym] = price

        # Build lookup maps
        rec_map: Dict[str, Dict] = {r["symbol"]: r for r in recs if r.get("symbol")}
        cand_map: Dict[str, Dict] = {c["symbol"]: c for c in candidates if c.get("symbol")}

        # Normalise momentum scores across candidates
        all_momentum = [c.get("momentum_score", 0) for c in candidates if c.get("momentum_score")]
        max_momentum = max(all_momentum) if all_momentum else 1.0

        pool: List[Dict] = []
        for sym in set(rec_map) | set(cand_map):
            rec = rec_map.get(sym)
            cand = cand_map.get(sym)
            price = self._prices.get(sym, 0.0)

            if rec:
                score = self._score_rec(rec, price)
                pool.append({
                    "symbol": sym,
                    "score": round(score, 4),
                    "action": rec.get("action", "WATCH"),
                    "confidence": rec.get("confidence", 0.0),
                    "reasoning": rec.get("reasoning", ""),
                })
            else:
                # Candidate-only — no AI rec, use normalised momentum
                momentum = cand.get("momentum_score", 0) if cand else 0
                norm = (momentum / max_momentum) if max_momentum > 0 else 0
                score = round(norm * 0.5, 4)
                pool.append({
                    "symbol": sym,
                    "score": score,
                    "action": "WATCH",
                    "confidence": round(norm * 0.5, 4),
                    "reasoning": (
                        f"Pre-screen: {cand.get('pct_change', 0):.1f}% move, "
                        f"{cand.get('vol_ratio', 1):.1f}× volume"
                    ) if cand else "Pre-screen candidate",
                })

        pool.sort(key=lambda x: x["score"], reverse=True)
        self._scored_pool = pool
        self._updated_at = time.time()

        top5 = [f"{e['symbol']}({e['score']:.2f})" for e in pool[:5]]
        logger.info(f"WatchlistManager: pool updated — {len(pool)} symbols. Top 5: {top5}")

    def get_active_watchlist(self) -> List[str]:
        """
        Return the fluid watchlist.

        Order: anchors → top-scored pool symbols → seed fallbacks.
        Total length is capped at config.WATCHLIST_SIZE.
        """
        anchors = config.WATCHLIST_ANCHORS
        size = config.WATCHLIST_SIZE

        result: List[str] = []
        seen: Set[str] = set()

        # 1. Anchor symbols — always first regardless of score
        for sym in anchors:
            if sym not in seen:
                result.append(sym)
                seen.add(sym)

        # 2. Top-scored symbols from the pool
        for entry in self._scored_pool:
            if len(result) >= size:
                break
            sym = entry["symbol"]
            if sym not in seen:
                result.append(sym)
                seen.add(sym)

        # 3. Seed fallbacks — fill any remaining slots when pool is small
        for sym in config.WATCHLIST:
            if len(result) >= size:
                break
            if sym not in seen:
                result.append(sym)
                seen.add(sym)

        return result

    @property
    def scored_pool(self) -> List[Dict]:
        """The current scored pool — for API exposure."""
        return list(self._scored_pool)

    @property
    def is_initialized(self) -> bool:
        """True once update_from_scan has run at least once successfully."""
        return self._updated_at > 0

    # ── Internals ──────────────────────────────────────────────────────────────

    def _score_rec(self, rec: Dict, current_price: float) -> float:
        """
        Compute projected_return_score for a scanner recommendation.

        BUY  with price target: confidence × (1 + max(0, upside_fraction))
        BUY  without target:    confidence × 1.0
        SELL:                   −confidence
        WATCH:                  0.3 × confidence
        """
        action = str(rec.get("action", "WATCH")).upper()
        confidence = float(rec.get("confidence") or 0.0)
        price_target = float(rec.get("price_target") or 0.0)

        upside = 0.0
        if action == "BUY" and price_target > 0 and current_price > 0:
            upside = max(0.0, (price_target - current_price) / current_price)

        if action == "BUY":
            return confidence * (1.0 + upside)
        if action == "SELL":
            return -confidence
        return 0.3 * confidence  # WATCH


# Module-level singleton — imported by main.py and anywhere else that needs it
watchlist_manager = WatchlistManager()
