"""
Pure decision helpers for the CNN reasoning strategy.

Extracted from CNNReasoningAgent so production AND the MC backtester call
the same logic via a documented function signature.

DESIGN RULE: This module imports ONLY dataclasses and typing. No agents.
No portfolio. No DB. No LLM. No config (passed in for testability). Pure
functions.
"""
from dataclasses import dataclass
from typing import Literal, Optional


@dataclass(frozen=True)
class BuyContext:
    """Snapshot of state needed to make ONE CNN BUY/HOLD decision."""
    symbol: str
    # Model output
    cnn_pred_return: float
    cnn_pred_direction: Literal["up", "down", "neutral"]
    cnn_confidence: float                   # 0..1
    # Market / portfolio state
    regime: Literal["bull", "neutral", "bear", "high_vol"]
    portfolio_unpnl_frac: Optional[float]   # uPnL / total_value; None when no positions
    n_corroborators: int                    # # OTHER agents agreeing on this symbol
    in_trail_cooldown: bool
    current_price: float
    cash_available: float
    portfolio_value: float
    kelly_fraction: float                   # quarter-Kelly from caller


@dataclass(frozen=True)
class BuyDecision:
    """Output of decide_buy()."""
    action: Literal["BUY", "HOLD"]
    shares: int                             # 0 when HOLD
    sized_confidence: float                 # cnn_conf after lone-wolf shrink
    reason: str                             # gate name or sizing summary, for logs


# Confidence add-ons per regime (mirrors RegimeDetector.get_confidence_gate)
_REGIME_CONF_ADJ = {
    "bull": 0.0,
    "neutral": 0.0,
    "bear": 0.15,
    "high_vol": 0.20,
}


def decide_buy(ctx: BuyContext, config) -> BuyDecision:
    """Full CNN BUY decision chain. Pure function.

    Five gates evaluated in order — first failure returns HOLD with reason.
    Then sizing: kelly × maybe-lonewolf, clamped to [2%, MAX_POSITION_SIZE].

    `config` is the app-wide backend.config.Config singleton.
    Passed in (not imported) for testability — overridable in tests.
    """
    # Gate 1: direction
    if ctx.cnn_pred_direction != "up":
        return BuyDecision("HOLD", 0, ctx.cnn_confidence, "not bullish")

    # Gate 2: minimum confidence floor (CNN_BUY_THRESHOLD_BASE — bull/neutral)
    if ctx.cnn_confidence < config.CNN_BUY_THRESHOLD_BASE:
        return BuyDecision("HOLD", 0, ctx.cnn_confidence,
                           f"conf {ctx.cnn_confidence:.2f} < {config.CNN_BUY_THRESHOLD_BASE:.2f}")

    # Gate 3: regime-adjusted floor (adds 0.15 in bear, 0.20 in high_vol)
    regime_add = _REGIME_CONF_ADJ.get(ctx.regime, 0.0)
    needed = config.CNN_BUY_THRESHOLD_BASE + regime_add
    if ctx.cnn_confidence < needed:
        return BuyDecision("HOLD", 0, ctx.cnn_confidence,
                           f"regime gate ({ctx.regime}): conf {ctx.cnn_confidence:.2f} < {needed:.2f}")

    # Gate 4: portfolio uPnL drawdown
    if (ctx.portfolio_unpnl_frac is not None
            and ctx.portfolio_unpnl_frac <= config.CNN_PAUSE_UPNL_DRAWDOWN_PCT):
        return BuyDecision("HOLD", 0, ctx.cnn_confidence,
                           f"uPnL {ctx.portfolio_unpnl_frac:.2%} <= {config.CNN_PAUSE_UPNL_DRAWDOWN_PCT:.2%}")

    # Gate 5: trail-stop cool-down
    if ctx.in_trail_cooldown:
        return BuyDecision("HOLD", 0, ctx.cnn_confidence, "trail cool-down active")

    # Sizing
    base_pct = ctx.kelly_fraction
    sized_conf = ctx.cnn_confidence
    if ctx.n_corroborators < config.LONEWOLF_MIN_CORROBORATORS:
        base_pct *= config.LONEWOLF_MULTIPLIER
        sized_conf *= config.LONEWOLF_MULTIPLIER

    size_pct = max(0.02, min(config.MAX_POSITION_SIZE, base_pct))
    target_value = size_pct * ctx.portfolio_value
    shares = int(target_value / ctx.current_price) if ctx.current_price > 0 else 0

    if shares < 1:
        return BuyDecision("HOLD", 0, ctx.cnn_confidence,
                           f"under-funded: {size_pct:.2%} of ${ctx.portfolio_value:.0f} < 1 share @ ${ctx.current_price:.2f}")

    return BuyDecision("BUY", shares, sized_conf,
                       f"BUY {shares}@${ctx.current_price:.2f} (size {size_pct:.2%}, conf {sized_conf:.2f})")
