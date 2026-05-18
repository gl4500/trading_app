"""After-hours news + policy sentinel.

Extracted from main.py for issue #67. Monitors news for major market catalysts
(earnings, M&A, FDA, Fed decisions, congressional laws, executive orders) and
triggers fresh scanner runs when actionable catalysts are detected.

Test-compatibility note: `app_state`, `config`, `datetime`, `logger`,
`_get_market_status`, `_record_catalysts`, and `watchlist_manager` are looked
up through `main` so existing patch-based tests intercept them correctly.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, List

logger = logging.getLogger(__name__)


def _sentinel_log_catalysts(
    catalysts: list,
    max_standard: int,
    max_policy: int,
    trigger: int,
) -> None:
    """Log sentinel detection results at the appropriate level.

    - WARNING: at least one score meets or exceeds the trigger threshold (actionable).
    - INFO:    catalysts found but none scored high enough to trigger a scan (noise).
    - Silent:  no catalysts detected.
    """
    import main
    _logger = main.logger
    if not catalysts:
        return
    combined_max = max(max_standard, max_policy)
    if combined_max >= trigger:
        _logger.warning(
            f"Sentinel: {len(catalysts)} catalyst(s) detected — "
            f"score={combined_max} meets trigger ({trigger}). "
            f"Top: {catalysts[0]['headline'][:100]}"
        )
    else:
        _logger.info(
            f"Sentinel: {len(catalysts)} low-score item(s) found "
            f"(max standard={max_standard}, policy={max_policy}) — "
            f"below trigger threshold ({trigger}), no scan triggered."
        )


async def news_sentinel_loop() -> None:
    """After-hours sentinel that monitors news for major market catalysts.

    Behaviour:
      • Sleeps while the market is open (trading loop handles intraday analysis).
      • Every SENTINEL_POLL_MIN minutes after hours, fetches news for the watchlist
        and broad-market proxies.
      • Scores headlines using two engines:
          1. Standard catalyst scoring (earnings, M&A, FDA, upgrades…)
          2. Policy monitor (congressional laws, executive orders, tariffs, Fed…)
      • If combined score ≥ TRIGGER_SCORE, triggers a fresh scanner run so agents
        have up-to-date picks ready at the next open.
      • Stores detected catalysts in app_state.after_hours_catalysts for the API.
    """
    import main
    from agents.scanner_agent import run_scan, is_scan_in_progress
    from data.policy_monitor import scan_policy_news

    _logger = main.logger
    app_state = main.app_state
    _config = main.config

    SENTINEL_POLL_MIN    = 15   # poll every 15 min after hours
    TRIGGER_SCORE        = 3   # combined keyword score to trigger a scan (raised from 2 — prevents
                               # single low-weight headlines like RSS policy items from repeatedly
                               # triggering expensive Ollama scans every 15 min after restarts)
    SCAN_COOLDOWN_SECS   = 3600  # sentinel-triggered scans at most once per hour

    # Standard catalyst keyword scores (non-policy)
    _CATALYST_KEYWORDS = [
        ("earnings beat", 3), ("earnings miss", 3), ("eps beat", 3), ("eps miss", 3),
        ("raised guidance", 3), ("lowered guidance", 3), ("merger", 3), ("acquisition", 3),
        ("buyout", 3), ("takeover", 3), ("fda approval", 4), ("fda rejection", 4),
        ("clinical trial", 2), ("phase 3", 2), ("bankruptcy", 4), ("chapter 11", 4),
        ("dividend cut", 3), ("dividend increase", 2), ("stock split", 2),
        ("buyback", 2), ("layoffs", 2), ("ceo resign", 3), ("ceo fired", 3),
        ("upgrade", 2), ("downgrade", 2), ("price target raised", 2), ("price target cut", 2),
        ("revenue beat", 2), ("revenue miss", 2), ("profit warning", 3),
        ("data breach", 2), ("lawsuit", 1), ("recall", 2),
    ]

    def _score_standard(headline: str, summary: str = "") -> int:
        text = (headline + " " + summary).lower()
        return sum(pts for kw, pts in _CATALYST_KEYWORDS if kw in text)

    _logger.info("News sentinel loop started")
    last_poll: float = 0.0
    last_sentinel_scan: float = 0.0   # timestamp of last sentinel-triggered scan

    while app_state.is_running:
        try:
            await asyncio.sleep(60)   # check every minute whether to poll

            if not app_state.is_running:
                break

            # Poll interval: every 15 min when closed, every 5 min during market hours
            market_open = main._get_market_status() == "open" or app_state.force_trading
            SENTINEL_POLL_MIN = 5 if market_open else 15

            now_ts = time.time()
            elapsed_min = (now_ts - last_poll) / 60
            if elapsed_min < SENTINEL_POLL_MIN:
                continue

            last_poll = now_ts
            app_state.last_sentinel_poll = main.datetime.utcnow().isoformat() + "Z"
            _logger.info("Sentinel: polling news for after-hours catalysts")

            # Gather watchlist + current scanner symbols
            watchlist_syms = list(_config.WATCHLIST)
            try:
                from agents.scanner_agent import get_cached_scan
                scan = get_cached_scan()
                if scan and scan.get("status") == "ok":
                    for rec in scan.get("recommendations", []):
                        sym = rec.get("symbol")
                        if sym and sym not in watchlist_syms:
                            watchlist_syms.append(sym)
            except Exception:
                pass

            # Run standard catalyst scan (Alpaca news)
            from data.news_service import news_service
            from data.sentinel_sources import fetch_all_sources
            try:
                news_map = await news_service.get_news_multi(watchlist_syms)
            except Exception as e:
                _logger.warning(f"Sentinel: news fetch failed: {e}")
                continue

            new_catalysts: List[Dict] = []
            seen = set()
            max_standard_score = 0

            for sym, articles in news_map.items():
                for art in articles:
                    headline = art.get("headline", "")
                    if not headline or headline in seen:
                        continue
                    seen.add(headline)
                    score = _score_standard(headline, art.get("summary", ""))
                    if score >= TRIGGER_SCORE:
                        max_standard_score = max(max_standard_score, score)
                        new_catalysts.append({
                            "headline":    headline,
                            "summary":     art.get("summary", "")[:200],
                            "source":      art.get("source", ""),
                            "date":        art.get("date", ""),
                            "symbol":      sym,
                            "score":       score,
                            "category":    "catalyst",
                            "sectors":     [],
                            "reason":      "earnings/M&A/FDA/upgrade keyword match",
                            "detected_at": main.datetime.utcnow().isoformat() + "Z",
                        })

            # Run policy / congressional / executive order scan
            try:
                policy_catalysts = await scan_policy_news(watchlist_syms, lookback_hours=12)
                new_catalysts.extend(policy_catalysts)
                max_policy_score = max((c["score"] for c in policy_catalysts), default=0)
            except Exception as e:
                _logger.warning(f"Sentinel: policy monitor failed: {e}")
                max_policy_score = 0

            # Run additional sources: RSS, Yahoo Finance, EDGAR 8-K, Finnhub, Unusual Whales
            try:
                extra_catalysts = await fetch_all_sources(watchlist_syms)
                # Merge — deduplicate against headlines already collected
                existing_headlines = {c["headline"] for c in new_catalysts}
                added = 0
                for cat in extra_catalysts:
                    if cat["headline"] not in existing_headlines:
                        new_catalysts.append(cat)
                        existing_headlines.add(cat["headline"])
                        added += 1
                if added:
                    _logger.info(f"Sentinel: +{added} catalysts from additional sources")
            except Exception as e:
                _logger.warning(f"Sentinel: additional sources failed: {e}")

            # Deduplicate and persist — also checks news_price_snapshots (DB-restored)
            # to prevent re-adding catalysts seen in prior sessions after a restart
            await main._record_catalysts(new_catalysts)

            # Log notable finds
            main._sentinel_log_catalysts(
                new_catalysts, max_standard_score, max_policy_score, TRIGGER_SCORE
            )

            # Trigger scanner if any catalyst exceeds threshold — but at most once per hour.
            # Cooldown prevents a single persistent RSS headline from triggering a full
            # Ollama scan every 15 minutes and causing memory pressure / process crashes.
            combined_max = max(max_standard_score, max_policy_score)
            secs_since_last = now_ts - last_sentinel_scan
            if (combined_max >= TRIGGER_SCORE
                    and not is_scan_in_progress()
                    and secs_since_last >= SCAN_COOLDOWN_SECS):
                _logger.warning(
                    f"Sentinel: triggering scanner — catalyst score={combined_max} "
                    f"(threshold={TRIGGER_SCORE})"
                )
                last_sentinel_scan = now_ts
                try:
                    result = await run_scan()
                    if result:
                        main.watchlist_manager.update_from_scan(result)
                except Exception as e:
                    _logger.error(f"Sentinel: scanner run failed: {e}")
            elif combined_max >= TRIGGER_SCORE and secs_since_last < SCAN_COOLDOWN_SECS:
                mins_remaining = int((SCAN_COOLDOWN_SECS - secs_since_last) / 60)
                _logger.info(
                    f"Sentinel: catalyst score={combined_max} meets threshold but scan "
                    f"cooldown active — next scan in {mins_remaining} min"
                )

        except asyncio.CancelledError:
            break
        except Exception as e:
            _logger.error(f"Sentinel loop error: {e}", exc_info=True)
            await asyncio.sleep(60)

    _logger.info("News sentinel loop stopped")
