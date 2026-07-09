"""
Pure decision helpers for the XGB reasoning strategy.

Extracted from XGBReasoningAgent so production AND the MC backtester call
the same logic via a documented function signature.

The "model_pred_*" fields are intentionally model-agnostic — both the
production XGBoost backend and the legacy CNN backend feed the same
gate/sizing chain via this dataclass.

DESIGN RULE: This module imports ONLY dataclasses and typing. No agents.
No portfolio. No DB. No LLM. No config (passed in for testability). Pure
functions.
"""
from dataclasses import dataclass
from typing import Literal, Optional


@dataclass(frozen=True)
class BuyContext:
    """Snapshot of state needed to make ONE XGB BUY/HOLD decision.

    ``model_pred_*`` fields are model-agnostic: the production XGBoost
    backend writes them, and the legacy CNN backend would write the same
    shape. Renamed from ``cnn_pred_*`` (issue #75) so the field name no
    longer implies a specific architecture.
    """
    symbol: str
    # Model output
    model_pred_return: float
    model_pred_direction: Literal["up", "down", "neutral"]
    model_confidence: float                 # 0..1
    # Market / portfolio state
    regime: Literal["bull", "neutral", "bear", "high_vol"]
    portfolio_unpnl_frac: Optional[float]   # uPnL / total_value; None when no positions
    n_corroborators: int                    # # OTHER agents agreeing on this symbol
    in_trail_cooldown: bool
    current_price: float
    cash_available: float
    portfolio_value: float
    kelly_fraction: float                   # quarter-Kelly from caller
    realized_vol: Optional[float] = None    # symbol's annualized trailing rv_20d;
                                            # None when unavailable (H15 sizing)


@dataclass(frozen=True)
class BuyDecision:
    """Output of decide_buy()."""
    action: Literal["BUY", "HOLD"]
    shares: int                             # 0 when HOLD
    sized_confidence: float                 # model_confidence after lone-wolf shrink
    reason: str                             # gate name or sizing summary, for logs


# Confidence add-ons per regime (mirrors RegimeDetector.get_confidence_gate)
_REGIME_CONF_ADJ = {
    "bull": 0.0,
    "neutral": 0.0,
    "bear": 0.15,
    "high_vol": 0.20,
}


def _vol_target_multiplier(realized_vol: Optional[float], config) -> Optional[float]:
    """H15 vol-managed sizing scalar (Moreira-Muir), pure.

    Returns ``clip(VOL_TARGET_ANN_VOL / realized_vol, 0, VOL_TARGET_CAP)`` — a
    factor to scale the Kelly base size by, shrinking high-vol names and
    (capped) levering calm ones. Returns ``None`` when there is no usable vol
    signal (missing / non-positive / non-finite), meaning "leave size as is".

    Independent of the enabled/disabled flag: the caller decides whether to
    apply the factor or merely shadow-log it, but the number is computed the
    same way either way.
    """
    if realized_vol is None:
        return None
    rv = float(realized_vol)
    if not (rv > 0.0) or rv != rv or rv in (float("inf"), float("-inf")):
        return None
    w = config.VOL_TARGET_ANN_VOL / rv
    cap = config.VOL_TARGET_CAP
    if w < 0.0:
        w = 0.0
    elif w > cap:
        w = cap
    return w


def decide_buy(ctx: BuyContext, config) -> BuyDecision:
    """Full XGB BUY decision chain. Pure function.

    Five gates evaluated in order — first failure returns HOLD with reason.
    Then sizing: kelly × maybe-lonewolf, clamped to [2%, MAX_POSITION_SIZE].

    `config` is the app-wide backend.config.Config singleton.
    Passed in (not imported) for testability — overridable in tests.
    """
    # Gate 1: direction
    if ctx.model_pred_direction != "up":
        return BuyDecision("HOLD", 0, ctx.model_confidence, "not bullish")

    # Gate 2: minimum confidence floor (CNN_BUY_THRESHOLD_BASE — bull/neutral).
    # Config knob name kept (CNN_BUY_THRESHOLD_BASE) because changing it would
    # break .env files in deployed environments; the value is backend-agnostic.
    if ctx.model_confidence < config.CNN_BUY_THRESHOLD_BASE:
        return BuyDecision("HOLD", 0, ctx.model_confidence,
                           f"conf {ctx.model_confidence:.2f} < {config.CNN_BUY_THRESHOLD_BASE:.2f}")

    # Gate 3: regime-adjusted floor (adds 0.15 in bear, 0.20 in high_vol)
    regime_add = _REGIME_CONF_ADJ.get(ctx.regime, 0.0)
    needed = config.CNN_BUY_THRESHOLD_BASE + regime_add
    if ctx.model_confidence < needed:
        return BuyDecision("HOLD", 0, ctx.model_confidence,
                           f"regime gate ({ctx.regime}): conf {ctx.model_confidence:.2f} < {needed:.2f}")

    # Gate 4: portfolio uPnL drawdown
    if (ctx.portfolio_unpnl_frac is not None
            and ctx.portfolio_unpnl_frac <= config.CNN_PAUSE_UPNL_DRAWDOWN_PCT):
        return BuyDecision("HOLD", 0, ctx.model_confidence,
                           f"uPnL {ctx.portfolio_unpnl_frac:.2%} <= {config.CNN_PAUSE_UPNL_DRAWDOWN_PCT:.2%}")

    # Gate 5: trail-stop cool-down
    if ctx.in_trail_cooldown:
        return BuyDecision("HOLD", 0, ctx.model_confidence, "trail cool-down active")

    # Sizing
    base_pct = ctx.kelly_fraction
    sized_conf = ctx.model_confidence
    if ctx.n_corroborators < config.LONEWOLF_MIN_CORROBORATORS:
        base_pct *= config.LONEWOLF_MULTIPLIER
        sized_conf *= config.LONEWOLF_MULTIPLIER

    # H15 vol-managed sizing: scale the Kelly base by the vol-target multiplier
    # BEFORE the [2%, MAX] clamp, so per-position bounds are preserved. The
    # multiplier is computed whenever a vol signal exists; it is only APPLIED
    # when VOL_TARGET_SIZING_ENABLED — otherwise it is shadow-only and surfaced
    # in the reason string for logging (no live sizing change).
    w = _vol_target_multiplier(ctx.realized_vol, config)
    vol_note = ""
    if w is not None:
        if config.VOL_TARGET_SIZING_ENABLED:
            base_pct *= w
            vol_note = f" [volx{w:.2f}]"
        else:
            vol_note = f" [volx{w:.2f} shadow]"

    size_pct = max(0.02, min(config.MAX_POSITION_SIZE, base_pct))
    target_value = size_pct * ctx.portfolio_value
    shares = int(target_value / ctx.current_price) if ctx.current_price > 0 else 0

    if shares < 1:
        return BuyDecision("HOLD", 0, ctx.model_confidence,
                           f"under-funded: {size_pct:.2%} of ${ctx.portfolio_value:.0f} < 1 share @ ${ctx.current_price:.2f}{vol_note}")

    return BuyDecision("BUY", shares, sized_conf,
                       f"BUY {shares}@${ctx.current_price:.2f} (size {size_pct:.2%}, conf {sized_conf:.2f}){vol_note}")
