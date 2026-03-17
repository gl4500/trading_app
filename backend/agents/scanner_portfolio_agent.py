"""
ScannerPortfolioAgent — Portfolio driven entirely by scanner recommendations.

Each trading cycle it:
  1. Reads the latest cached scan (no new API calls).
  2. Sells any held position that is an explicit SELL recommendation.
  3. Sells any held position that:
       - is NOT in the current BUY set, AND
       - has breached its stop-loss (scanner-supplied or default 5%).
  4. Buys high-confidence BUY recommendations it doesn't already hold,
     sized by confidence via the existing RiskManager rules.

Prices for scanner stocks outside the main watchlist are fetched from
Alpaca on demand. All risk rules (15 % position cap, daily loss halt) are
inherited from BaseAgent / RiskManager unchanged.
"""
import logging
from typing import Dict, List, Optional

from agents.base_agent import BaseAgent, Signal

logger = logging.getLogger(__name__)

# ── Tunable constants ──────────────────────────────────────────────────────────

MIN_BUY_CONFIDENCE    = 0.60   # ignore BUY recs below this threshold
DEFAULT_STOP_LOSS_PCT = 5.0    # % drop below cost basis → exit if not in BUY set


class ScannerPortfolioAgent(BaseAgent):
    """Trades the scanner's AI recommendations directly."""

    def __init__(self):
        super().__init__(
            name="ScannerAgent",
            strategy_description=(
                "Buys high-conviction scanner picks, exits underperformers & SELL signals"
            ),
        )
        # Track which scan we last acted on (avoid re-trading same scan)
        self._last_acted_scan_ts: Optional[str] = None

    # ── Main analysis ──────────────────────────────────────────────────────────

    async def analyze(self, market_context: Dict) -> List[Signal]:
        from agents.scanner_agent import get_cached_scan
        from trading.alpaca_client import alpaca_client

        scan = get_cached_scan(require_fresh=True)
        if not scan or scan.get("status") != "ok":
            return []

        recs = scan.get("recommendations", [])
        if not recs:
            return []

        # Build recommendation lookup: symbol → rec dict
        rec_by_sym: Dict[str, Dict] = {r["symbol"]: r for r in recs}
        buy_syms = {sym for sym, r in rec_by_sym.items() if r.get("action") == "BUY"}

        # ── Gather prices ──────────────────────────────────────────────────────
        # Start with whatever the trading loop already fetched for the watchlist
        prices: Dict[str, float] = {
            sym: ctx.get("price", 0)
            for sym, ctx in market_context.items()
            if isinstance(ctx, dict) and ctx.get("price", 0) > 0
        }

        # Fetch prices for scanner symbols and held positions not yet in prices
        need = (
            {sym for sym in rec_by_sym if sym not in prices}
            | {sym for sym in self.portfolio.positions if sym not in prices}
        )
        if need:
            try:
                bars_dict = await alpaca_client.get_bars_multi(list(need), limit=1)
                for sym, bars in (bars_dict or {}).items():
                    if bars is not None and not bars.empty:
                        prices[sym] = float(bars["close"].iloc[-1])
            except Exception as e:
                logger.warning(f"ScannerPortfolioAgent: price fetch error: {e}")

        signals: List[Signal] = []

        # ── 1. Sell explicit SELL recommendations ──────────────────────────────
        for sym, rec in rec_by_sym.items():
            if rec.get("action") != "SELL":
                continue
            if sym not in self.portfolio.positions:
                continue
            price = prices.get(sym, 0)
            if price <= 0:
                continue
            pos = self.portfolio.positions[sym]
            signals.append(Signal(
                action="SELL",
                symbol=sym,
                confidence=float(rec.get("confidence") or 0.7),
                shares=pos.shares,
                reasoning=(
                    f"Scanner SELL signal (conf={rec.get('confidence', 0):.0%}): "
                    f"{str(rec.get('reasoning', ''))[:180]}"
                ),
            ))

        # ── 2. Exit underperformers not in current BUY set ────────────────────
        already_selling = {s.symbol for s in signals if s.action == "SELL"}
        for sym, pos in list(self.portfolio.positions.items()):
            if sym in already_selling:
                continue
            if sym in buy_syms:
                continue   # still a BUY recommendation — hold

            price = prices.get(sym, 0)
            if price <= 0:
                continue

            pnl_pct = pos.unrealized_pnl_pct(price)

            # Use the stop_loss_pct from the original BUY rec if we stored it,
            # otherwise fall back to the default.
            stop = DEFAULT_STOP_LOSS_PCT
            if -pnl_pct >= stop:
                signals.append(Signal(
                    action="SELL",
                    symbol=sym,
                    confidence=0.8,
                    shares=pos.shares,
                    reasoning=(
                        f"Underperformer exit: {sym} down {pnl_pct:.1f}% vs cost basis "
                        f"(stop {-stop:.0f}%) and not in current BUY set"
                    ),
                ))

        # ── 3. Buy high-confidence recommendations ─────────────────────────────
        # Sort highest confidence first so best picks get capital priority
        buy_recs = sorted(
            [r for r in recs if r.get("action") == "BUY"],
            key=lambda r: float(r.get("confidence") or 0),
            reverse=True,
        )

        scan_ts = scan.get("scanned_at")
        new_scan = (scan_ts != self._last_acted_scan_ts)

        for rec in buy_recs:
            sym = rec["symbol"]
            confidence = float(rec.get("confidence") or 0)

            if confidence < MIN_BUY_CONFIDENCE:
                continue

            price = prices.get(sym, 0)
            if price <= 0:
                continue

            # Only enter a new position on a fresh scan to avoid churning
            already_held = sym in self.portfolio.positions
            if already_held and not new_scan:
                continue

            shares = self.risk_manager.get_max_buy_shares(
                sym, price, confidence, self.portfolio, prices
            )
            if shares <= 0:
                continue

            catalysts = rec.get("catalysts") or []
            catalyst_str = "; ".join(catalysts[:3]) if catalysts else ""
            reasoning = (
                f"Scanner BUY (conf={confidence:.0%}): "
                f"{str(rec.get('reasoning', ''))[:150]}"
                + (f" | Catalysts: {catalyst_str}" if catalyst_str else "")
            )

            signals.append(Signal(
                action="BUY",
                symbol=sym,
                confidence=confidence,
                shares=shares,
                reasoning=reasoning,
            ))

        # Mark this scan as acted-on
        if new_scan and signals:
            self._last_acted_scan_ts = scan_ts

        if signals:
            buys  = sum(1 for s in signals if s.action == "BUY")
            sells = sum(1 for s in signals if s.action == "SELL")
            logger.info(f"ScannerPortfolioAgent: {buys} BUY, {sells} SELL signals generated")

        return signals
