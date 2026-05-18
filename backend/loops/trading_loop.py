"""Main trading loop + per-agent cycle helper + performance-snapshot saver.

Extracted from main.py for issue #67.

Test-compatibility note: every DB function (save_trade, save_performance,
upsert_portfolio_position, prune_news_price_snapshots, dump_trades_to_parquet),
shared helper (_update_news_price_snapshots, _refresh_summary, run_agent_cycle,
_get_market_status, _detect_close_transition, _minutes_until_open), the
`logger`, the `app_state` singleton, and the `config` reference are all looked
up through the `main` module so existing `patch("main.X", ...)` tests intercept
them correctly.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Dict

logger = logging.getLogger(__name__)


# Off-hours scan interval in Ollama mode — scanner runs even when market is closed
# because local inference is free. Cloud mode skips off-hours to avoid token cost.
OLLAMA_CLOSED_SCAN_MIN: int = 30


async def _refresh_summary(prices: Dict[str, float], market_status: str) -> None:
    """Background task: regenerate the daily summary without blocking the trading loop."""
    import main
    try:
        from agents.scanner_agent import get_cached_scan
        from agents.summary_agent import daily_summary
        scan = get_cached_scan()
        scanner_recs = (scan.get("recommendations", []) if scan else [])
        await daily_summary.generate(
            agents=main.app_state.agents,
            prices=prices,
            market_status=market_status,
            scanner_recs=scanner_recs,
            sentinel_catalysts=main.app_state.after_hours_catalysts,
        )
    except Exception as e:
        logger.warning(f"Summary refresh failed: {e}")


async def run_agent_cycle(agent, market_context: Dict, prices: Dict[str, float]) -> None:
    """Run one trading cycle for a single agent."""
    import main  # late import for test patches against main.save_trade, main.upsert_portfolio_position
    from data.risk_assessor import record_trade as record_risk_trade

    if not agent._is_active:
        return

    try:
        # Record trade history before cycle
        trades_before = set(id(t) for t in agent.portfolio.trade_history)
        positions_before = set(agent.portfolio.positions.keys())

        signals = await agent.run_cycle(market_context, prices)  # noqa: F841 (kept for parity)

        # Persist new trades
        new_trades = [t for t in agent.portfolio.trade_history if id(t) not in trades_before]
        for trade in new_trades:
            await main.save_trade(
                agent_id=agent.agent_id,
                symbol=trade.symbol,
                action=trade.action,
                shares=trade.shares,
                price=trade.price,
                reasoning=trade.reasoning[:500],
                pnl=trade.pnl,
            )
            try:
                record_risk_trade(agent.name, trade.symbol, trade.action)
            except Exception:
                pass

        # Delete positions that were fully closed this cycle
        positions_after = set(agent.portfolio.positions.keys())
        for sym in positions_before - positions_after:
            await main.upsert_portfolio_position(
                agent_id=agent.agent_id,
                symbol=sym,
                shares=0,
                avg_cost=0,
                current_value=0,
                unrealized_pnl=0,
            )

        # Update remaining open positions in DB
        for sym, pos in agent.portfolio.positions.items():
            price = prices.get(sym, pos.avg_cost)
            await main.upsert_portfolio_position(
                agent_id=agent.agent_id,
                symbol=sym,
                shares=pos.shares,
                avg_cost=pos.avg_cost,
                current_value=pos.current_value(price),
                unrealized_pnl=pos.unrealized_pnl(price),
                last_price=price if sym in prices else 0.0,
                entry_confidence=pos.entry_confidence,
            )

    except Exception as e:
        main.logger.error(f"Error in agent cycle for {agent.name}: {e}", exc_info=True)


async def save_performance_snapshots(prices: Dict[str, float]) -> None:
    """Save performance snapshot for all agents.

    Aggregates per-agent outcomes so a silent total failure becomes loud:
    - all-agent failure → CRITICAL (e.g., DB unreachable for an entire cycle)
    - partial failure   → WARNING summary
    - all success       → silent (default debug only)
    """
    import main  # late import for test patches against main.save_performance, main.logger
    _logger = main.logger
    successes = 0
    failures = 0
    for agent in main.app_state.agents.values():
        try:
            metrics = agent.get_performance_metrics(prices)
            await main.save_performance(
                agent_id=agent.agent_id,
                total_value=metrics["total_value"],
                cash=metrics["cash"],
                total_return_pct=metrics["total_return_pct"],
                sharpe_ratio=metrics["sharpe_ratio"],
                win_rate=metrics["win_rate"],
            )
            successes += 1
        except Exception as e:
            _logger.error(f"Error saving performance for {agent.name}: {e}")
            failures += 1

    if failures and successes == 0:
        _logger.critical(
            f"Performance snapshot save FAILED for ALL {failures} agents this cycle. "
            f"No DB rows persisted — leaderboard/history will go stale until fixed."
        )
    elif failures:
        _logger.warning(
            f"Performance snapshot: {successes} saved, {failures} failed"
        )


async def trading_loop() -> None:
    """Main trading loop that runs every TRADE_INTERVAL_SECONDS."""
    import main  # late import — required for test patches
    from data.signal_history import signal_history
    from data.agent_performance_tracker import agent_performance_tracker
    from data.risk_assessor import run_periodic_assessment
    from data.drift_detector import check_all_agents
    from data.macro_context import get_macro_context_text
    from data.market_data import market_data_service
    from data.watchlist_manager import watchlist_manager

    _logger = main.logger
    app_state = main.app_state
    _config = main.config

    _logger.info("Trading loop started")

    while app_state.is_running:
        try:
            # ── Session gate ─────────────────────────────────────────────────
            status = main._get_market_status()
            just_closed = main._detect_close_transition(app_state._prev_market_status, status)
            app_state._prev_market_status = status
            app_state.market_status = status

            if status == "closed" and not app_state.force_trading:
                mins = main._minutes_until_open()
                # Wake up 5 min before open; minimum 60s poll
                sleep_secs = max(60, (mins - 5) * 60)
                _logger.info(
                    f"Market closed (next open in {mins:.0f} min). "
                    f"Trading loop sleeping {sleep_secs/60:.0f} min."
                )
                # Sleep in 10-second chunks so force_trading toggle takes effect quickly
                slept = 0
                try:
                    while slept < sleep_secs and app_state.is_running and not app_state.force_trading:
                        await asyncio.sleep(min(10, sleep_secs - slept))
                        slept += 10
                except asyncio.CancelledError:
                    break
                if not app_state.is_running:
                    break
                if just_closed:
                    _logger.info("Market closed — triggering end-of-day roll-up")
                    asyncio.create_task(
                        main._refresh_summary(app_state.last_prices or {}, status)
                    )
                continue  # re-check status (may now be force_trading=True or market open)

            if app_state.force_trading and status == "closed":
                app_state.market_status = "open (test)"
                _logger.debug("Trading session: FORCED (test mode)")
            else:
                _logger.debug(f"Trading session: {status.upper()}")
            # ── End session gate ─────────────────────────────────────────────

            cycle_start = time.time()
            app_state.cycle_count += 1
            _logger.info(f"=== Trading Cycle {app_state.cycle_count} ===")
            if app_state.cycle_count % 30 == 0:
                try:
                    run_periodic_assessment(app_state.agents, app_state.last_prices or {})
                except Exception as e:
                    _logger.debug(f"Risk assessment error: {e}")

            # Daily DB prune — every 1440 cycles (~24 h at 60 s intervals).
            # Performance table is intentionally NOT pruned (user policy
            # 2026-05-16: continuity for all trades, not just days).
            if app_state.cycle_count % 1440 == 0:
                try:
                    await main.prune_news_price_snapshots(days=14)
                except Exception as e:
                    _logger.warning(f"DB prune error: {e}")
                # Daily trades parquet snapshot for disaster recovery + analytics
                # (added 2026-05-17). Idempotent within the same UTC day.
                try:
                    _trade_dump_dir = os.path.join(
                        os.path.dirname(os.path.abspath(main.__file__)),
                        "data", "trade_history",
                    )
                    n, p = await main.dump_trades_to_parquet(_trade_dump_dir)
                    _logger.info(f"Daily trades parquet: {n} rows -> {p}")
                except Exception as e:
                    _logger.warning(f"Trades parquet dump error: {e}")

            # Fetch market data once for all agents (fluid watchlist ranked by projected return)
            market_context = await market_data_service.get_market_context(
                watchlist_manager.get_active_watchlist()
            )
            prices = {sym: ctx.get("price", 0) for sym, ctx in market_context.items() if isinstance(ctx, dict)}

            # Augment context with fresh scanner recommendations so every agent
            # can apply its own strategy to scanner-identified symbols
            try:
                from agents.scanner_agent import get_cached_scan
                scan = get_cached_scan(require_fresh=True)
                if scan and scan.get("status") == "ok":
                    scanner_syms = [
                        r["symbol"] for r in scan.get("recommendations", [])
                        if r["symbol"] not in market_context
                    ]
                    if scanner_syms:
                        scanner_ctx = await market_data_service.get_market_context(scanner_syms)
                        market_context.update(scanner_ctx)
                        prices.update({s: c.get("price", 0) for s, c in scanner_ctx.items() if isinstance(c, dict)})
                        _logger.info(f"Scanner: added {len(scanner_syms)} symbols to market context: {scanner_syms}")
            except Exception as e:
                _logger.warning(f"Could not augment market context with scanner symbols: {e}")

            # Inject each agent's retained picks so they always get fresh data
            # for symbols they have conviction on, even after scanner cache expires.
            try:
                pick_syms = set()
                for agent in app_state.agents.values():
                    for sym in agent.get_pick_symbols():
                        if sym not in market_context:
                            pick_syms.add(sym)
                if pick_syms:
                    picks_ctx = await market_data_service.get_market_context(list(pick_syms))
                    market_context.update(picks_ctx)
                    prices.update({s: c.get("price", 0) for s, c in picks_ctx.items() if isinstance(c, dict)})
                    _logger.info(f"Agent picks: added {len(pick_syms)} retained symbols to context: {sorted(pick_syms)}")
            except Exception as e:
                _logger.warning(f"Could not augment market context with agent picks: {e}")

            # Inject overnight sentinel catalysts so agents see what happened after hours
            if app_state.after_hours_catalysts:
                market_context["__overnight_catalysts__"] = app_state.after_hours_catalysts

            # Inject macro sector rotation context (15-min cache; Murphy + Bridgewater framework)
            # Refresh every 15 cycles (~15 min at 60s interval); also on first cycle
            if app_state.cycle_count % 15 == 1:
                try:
                    macro_text = await get_macro_context_text()
                    if macro_text:
                        market_context["__macro_context__"] = macro_text
                        _logger.debug("MacroContext: injected into market_context")
                except Exception as _me:
                    _logger.warning(f"MacroContext injection failed: {_me}")
            elif "__macro_context__" not in market_context and app_state.last_market_context:
                # Carry forward cached macro context from previous cycle
                prev = app_state.last_market_context.get("__macro_context__", "")
                if prev:
                    market_context["__macro_context__"] = prev

            # Fetch Gemini market view (rate-limited 2/hr) and inject as context
            if app_state.gemini_news_agent:
                try:
                    watchlist = [s for s in market_context if isinstance(market_context[s], dict)]
                    gemini_view = await app_state.gemini_news_agent.get_market_view(
                        market_context, watchlist
                    )
                    if gemini_view:
                        market_context["__gemini_market_view__"] = gemini_view
                        _logger.debug(f"Gemini market view injected: {gemini_view[:80]}")
                except Exception as e:
                    _logger.warning(f"Gemini news fetch failed: {e}")

            app_state.last_prices = prices
            app_state.last_market_context = market_context

            # Update news-price correlation snapshots with live prices
            await main._update_news_price_snapshots(prices)

            # Filter out agents that are ensemble (it runs sub-agents internally)
            # Run all agents concurrently (excluding ensemble's sub-agents which it runs itself)
            non_ensemble_agents = [
                agent for name, agent in app_state.agents.items()
                if name != "EnsembleAgent"
            ]
            ensemble_agent = app_state.agents.get("EnsembleAgent")

            # Run non-ensemble agents first (ensemble uses them internally)
            agent_tasks = [
                main.run_agent_cycle(agent, market_context, prices)
                for agent in non_ensemble_agents
            ]

            # Also run ensemble
            if ensemble_agent:
                agent_tasks.append(main.run_agent_cycle(ensemble_agent, market_context, prices))

            await asyncio.gather(*agent_tasks, return_exceptions=True)

            # Collect per-symbol agent signals and inject into signal_history
            # (enables CNN training with agent consensus features)
            try:
                # Build {symbol: {agent_name: (action, confidence)}} from all non-ensemble agents
                sym_agent_sigs: Dict[str, Dict[str, tuple]] = {}
                for agent in non_ensemble_agents:
                    if agent.name in ("EnsembleAgent", "GeminiAgent"):
                        continue
                    for sym, sig in (agent._last_signals or {}).items():
                        if not isinstance(market_context.get(sym), dict):
                            continue
                        if sym not in sym_agent_sigs:
                            sym_agent_sigs[sym] = {}
                        sym_agent_sigs[sym][agent.name] = (sig.action, sig.confidence)

                if sym_agent_sigs:
                    # Refresh agent performance scores from DB (rate-limited to every 5 min)
                    await agent_performance_tracker.get_scores()

                    for sym, sigs in sym_agent_sigs.items():
                        consensus = agent_performance_tracker.consensus_score(sigs)
                        agreement = agent_performance_tracker.agreement_fraction(sigs)
                        asyncio.create_task(
                            signal_history.record_agent_signals(sym, consensus, agreement)
                        )
                        asyncio.create_task(
                            signal_history.update_top_agent_correct(sym, prices.get(sym, 0))
                        )

                    # Make current agent signals available to CNNReasoningAgent next cycle
                    market_context["__agent_signals__"] = sym_agent_sigs
            except Exception as _exc:
                _logger.warning(f"Agent signal recording failed: {_exc}")

            # Save performance snapshots
            await main.save_performance_snapshots(prices)

            # Check for performance drift every 10 cycles
            if app_state.cycle_count % 10 == 0:
                drift_reports = check_all_agents(app_state.agents)
                drifting = [r for r in drift_reports if r["is_drifting"]]
                if drifting:
                    for r in drifting:
                        _logger.warning(f"DRIFT [{r['agent_name']}]: {' | '.join(r['alerts'])}")
                else:
                    _logger.info("Drift check passed — all agents performing within baseline")

            cycle_time = time.time() - cycle_start
            _logger.info(f"Cycle {app_state.cycle_count} completed in {cycle_time:.2f}s")

            # Wait for next interval
            wait_time = max(0, _config.TRADE_INTERVAL_SECONDS - cycle_time)
            await asyncio.sleep(wait_time)

        except asyncio.CancelledError:
            _logger.info("Trading loop cancelled")
            break
        except Exception as e:
            _logger.error(f"Trading loop error: {e}", exc_info=True)
            await asyncio.sleep(10)  # backoff on error

    _logger.info("Trading loop stopped")
    main._write_crash("[trading_loop] exited normally")
