"""Background-loop modules.

Each module owns one long-running asyncio task that the lifespan launches:
- trading_loop.py        — main trading cycle (every TRADE_INTERVAL_SECONDS)
- auto_scan_loop.py      — scheduled scanner runs
- news_sentinel_loop.py  — after-hours news / policy monitor
- ws_broadcast_loop.py   — WebSocket broadcast tick

Shared helpers:
- market_calendar.py — NYSE open/close, holidays, EST/EDT
- news_snapshots.py  — catalyst dedupe + news-price correlation tracking
"""
