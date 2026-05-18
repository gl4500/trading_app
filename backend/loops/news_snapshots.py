"""News-price correlation tracking.

Extracted from main.py for issue #67. Used by news_sentinel_loop (to add new
catalyst snapshots) and trading_loop (to fill in price_open / price_1h fields
as trading progresses).

Test-compatibility note: `datetime`, `update_price_snapshot`,
`save_price_snapshot`, `record_catalyst_outcome` are looked up through the
`main` module so that existing `patch("main.<name>", ...)` tests intercept
them correctly. `app_state` and `_market_is_open` are likewise routed through
main so patches against those names work.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Set

logger = logging.getLogger(__name__)


_REACTION_WINDOW_SECS = 300   # 5 min initial reaction window for intraday catalysts
_SUSTAINED_WINDOW_SECS = 3600  # 60 min for the sustained (price_1h) reading


async def _record_catalysts(new_catalysts: List[Dict]) -> None:
    """Deduplicate and persist new sentinel catalysts into app_state.

    Deduplicates against BOTH after_hours_catalysts (in-memory) AND
    news_price_snapshots (DB-restored on startup) so that post-restart
    re-detection of already-seen headlines does not create duplicate entries.
    """
    import main  # late import for test patches against main.datetime / main.save_price_snapshot
    _datetime = main.datetime
    app_state = main.app_state

    # Build the full set of known headlines from both sources
    all_headlines: Set[str] = (
        {c["headline"] for c in app_state.after_hours_catalysts} |
        {s["headline"] for s in app_state.news_price_snapshots}
    )
    for cat in new_catalysts:
        headline = cat["headline"]
        if headline in all_headlines:
            continue
        app_state.after_hours_catalysts.append(cat)
        all_headlines.add(headline)
        # Record price snapshot for news-price correlation tracking
        sym = cat.get("symbol")
        if sym and sym in app_state.last_prices:
            app_state.news_price_snapshots.append({
                "symbol":         sym,
                "headline":       headline[:120],
                "score":          cat.get("score", 0),
                "category":       cat.get("category", "news"),
                "price_at":       app_state.last_prices[sym],
                "detected_at":    cat.get("detected_at", _datetime.utcnow().isoformat() + "Z"),
                "during_session": main._market_is_open(),
                "price_open":     None,
                "price_1h":       None,
                "change_open":    None,
                "change_1h":      None,
                "open_recorded_at": None,
            })
            try:
                new_snap = app_state.news_price_snapshots[-1]
                db_id = await main.save_price_snapshot(new_snap)
                new_snap["_db_id"] = db_id
            except Exception as _e:
                logger.debug(f"save_price_snapshot failed: {_e}")

    # Trim to top 50 by score
    app_state.after_hours_catalysts = sorted(
        app_state.after_hours_catalysts,
        key=lambda c: c.get("score", 0),
        reverse=True,
    )[:50]


async def _update_news_price_snapshots(prices: Dict[str, float]) -> None:
    """Fill price_open / price_1h fields on correlation snapshots as trading progresses.

    After-hours catalysts (during_session=False):
      price_open  — captured immediately on the first trading-cycle price read
                    (i.e. at market open the next morning).

    Intraday catalysts (during_session=True):
      price_open  — captured once >= 5 min have elapsed since detection
                    (gives the market time to react before we record).

    Both types:
      price_1h    — captured once, >= 60 min after price_open was recorded, then
                    frozen permanently so the UI shows a stable 1-hour outcome.
    """
    import main  # late import for test patches against main.datetime / main.update_price_snapshot / main.record_catalyst_outcome
    _datetime = main.datetime
    app_state = main.app_state

    now = _datetime.utcnow()
    for snap in app_state.news_price_snapshots:
        sym = snap["symbol"]
        if sym not in prices:
            continue
        current = prices[sym]
        base = snap["price_at"]
        if not base or base <= 0:
            continue
        pct = (current - base) / base * 100

        if snap["price_open"] is None:
            ready = True
            if snap.get("during_session"):
                # Intraday: wait for the 5-min reaction window to elapse
                try:
                    det = _datetime.fromisoformat(snap["detected_at"].replace("Z", ""))
                    ready = (now - det).total_seconds() >= _REACTION_WINDOW_SECS
                except Exception:
                    ready = True
            if ready:
                snap["price_open"] = current
                snap["change_open"] = round(pct, 2)
                snap["open_recorded_at"] = now
                if snap.get("_db_id"):
                    try:
                        await main.update_price_snapshot(
                            snap["_db_id"],
                            price_open=current,
                            change_open=snap["change_open"],
                            open_recorded_at=now,
                        )
                    except Exception as _e:
                        logger.debug(f"DB update price_open failed: {_e}")

        elif snap["price_1h"] is None:
            # Wait until >= 60 min have elapsed since price_open was recorded
            recorded_at = snap.get("open_recorded_at")
            if recorded_at and (now - recorded_at).total_seconds() >= _SUSTAINED_WINDOW_SECS:
                change_1h = round(pct, 2)
                snap["price_1h"] = current
                snap["change_1h"] = change_1h
                if snap.get("_db_id"):
                    try:
                        await main.update_price_snapshot(
                            snap["_db_id"],
                            price_1h=current,
                            change_1h=change_1h,
                        )
                    except Exception as _e:
                        logger.debug(f"DB update price_1h failed: {_e}")
                # Record the confirmed outcome to learning.json so agents can
                # learn which catalyst types actually move prices
                try:
                    confirmed = abs(change_1h) >= 0.05
                    main.record_catalyst_outcome(
                        symbol=sym,
                        category=snap.get("category", "catalyst"),
                        score=snap.get("score", 0),
                        headline=snap.get("headline", ""),
                        change_open=snap.get("change_open") or 0.0,
                        change_1h=change_1h,
                        during_session=snap.get("during_session", False),
                        confirmed=confirmed,
                    )
                except Exception as _e:
                    logger.debug(f"catalyst outcome record failed: {_e}")
        # price_1h already set — leave it frozen, no further updates

    # Keep only the 100 most recent
    app_state.news_price_snapshots = app_state.news_price_snapshots[-100:]
