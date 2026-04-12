"""
FRED (Federal Reserve Economic Data) Client
--------------------------------------------
Fetches key US macroeconomic statistics from the St. Louis Fed REST API.

Why FRED vs. ETF proxies:
  - ETF proxies (TLT, GLD, ^TNX) reflect *market expectations*.
  - FRED series reflect *actual reported data* — CPI, unemployment, GDP.
  - Together they give AI agents both the market's view AND the hard numbers.

Data update cadence (all cached appropriately):
  Daily   : DFF, T10Y2Y, T10YIE, VIXCLS
  Monthly : CPIAUCSL, CPILFESL, UNRATE, UMCSENT, RECPROUSM156N
  Quarterly: GDP, GDPC1

Cache TTL: 4 hours — FRED data updates at most once per day.

Setup: add FRED_API_KEY to .env (free key at https://fred.stlouisfed.org/docs/api/api_key.html)
"""
import asyncio
import json
import logging
import time
from typing import Dict, List, Optional, Tuple

import httpx

from config import config

logger = logging.getLogger(__name__)

_BASE_URL   = "https://api.stlouisfed.org/fred/series/observations"
_CACHE_TTL  = 4 * 3600   # 4 hours — data updates at most once per day
_TIMEOUT    = 15.0        # seconds per request
_SORT       = "desc"
_LIMIT      = 3           # last 3 observations per series (to detect recent changes)

# ── Series definitions ────────────────────────────────────────────────────────
# Each entry: (series_id, label, unit, frequency, interpretation)
FRED_SERIES: List[Tuple[str, str, str, str]] = [
    # --- Monetary policy ---
    ("DFF",            "Fed Funds Rate (effective, daily)",  "%",        "daily"),
    # --- Inflation ---
    ("CPIAUCSL",       "CPI All-Urban (YoY headline)",       "index",    "monthly"),
    ("CPILFESL",       "Core CPI ex food/energy (YoY)",      "index",    "monthly"),
    ("T10YIE",         "10Y Breakeven Inflation",            "%",        "daily"),
    # --- Growth / labour ---
    ("UNRATE",         "Unemployment Rate",                  "%",        "monthly"),
    ("GDP",            "GDP (nominal, seasonally adj.)",     "billions", "quarterly"),
    # --- Yield curve ---
    ("T10Y2Y",         "10Y minus 2Y Treasury spread",       "%",        "daily"),
    # --- Sentiment / risk ---
    ("UMCSENT",        "U of Michigan Consumer Sentiment",   "index",    "monthly"),
    ("VIXCLS",         "VIX (CBOE, daily close)",            "index",    "daily"),
    # --- Recession indicator ---
    ("RECPROUSM156N",  "Recession Probability (smoothed)",   "%",        "monthly"),
]

# ── Cache ─────────────────────────────────────────────────────────────────────
_cache: Dict[str, Tuple[float, dict]] = {}  # series_id -> (timestamp, data)
_fetch_lock = asyncio.Lock()


class FREDClient:
    """Async client for the FRED REST API."""

    def __init__(self):
        self._api_key: str = getattr(config, "FRED_API_KEY", "") or ""

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    async def _fetch_series(
        self,
        client: httpx.AsyncClient,
        series_id: str,
    ) -> Optional[dict]:
        """Fetch the latest N observations for a single series."""
        now = time.time()
        if series_id in _cache:
            ts, data = _cache[series_id]
            if now - ts < _CACHE_TTL:
                return data

        try:
            resp = await client.get(
                _BASE_URL,
                params={
                    "series_id":  series_id,
                    "api_key":    self._api_key,
                    "file_type":  "json",
                    "sort_order": _SORT,
                    "limit":      _LIMIT,
                },
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            payload = resp.json()
            obs = [
                o for o in payload.get("observations", [])
                if o.get("value") not in (".", "")
            ]
            if not obs:
                return None
            result = {
                "series_id":  series_id,
                "latest":     obs[0],          # most recent non-null obs
                "previous":   obs[1] if len(obs) > 1 else None,
                "count":      len(obs),
            }
            _cache[series_id] = (now, result)
            return result
        except httpx.TimeoutException:
            logger.warning(f"FRED: timeout fetching {series_id}")
            return _cache.get(series_id, (0, None))[1]   # return stale if available
        except Exception as exc:
            logger.warning(f"FRED: error fetching {series_id}: {exc}")
            return _cache.get(series_id, (0, None))[1]

    async def fetch_all(self) -> Dict[str, dict]:
        """Fetch all configured series concurrently. Returns series_id -> data dict."""
        if not self.available:
            return {}

        async with _fetch_lock:
            async with httpx.AsyncClient() as client:
                tasks = {
                    sid: self._fetch_series(client, sid)
                    for sid, *_ in FRED_SERIES
                }
                results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        out = {}
        for (sid, *_), result in zip(FRED_SERIES, results):
            if isinstance(result, Exception):
                logger.warning(f"FRED: {sid} raised {result}")
            elif result is not None:
                out[sid] = result
        return out

    def format_for_prompt(self, data: Dict[str, dict]) -> str:
        """
        Format FRED data as a concise text block for AI agent prompts.
        Highlights direction (↑↓) vs previous observation when available.
        """
        if not data:
            return ""

        lines = ["## FRED Economic Data (St. Louis Fed)"]

        sections = [
            ("Monetary Policy",  ["DFF"]),
            ("Inflation",        ["CPIAUCSL", "CPILFESL", "T10YIE"]),
            ("Growth / Labour",  ["UNRATE", "GDP"]),
            ("Yield Curve",      ["T10Y2Y"]),
            ("Sentiment / Risk", ["UMCSENT", "VIXCLS", "RECPROUSM156N"]),
        ]

        meta = {sid: (label, unit, freq) for sid, label, unit, freq in FRED_SERIES}

        for section_name, series_ids in sections:
            section_lines = []
            for sid in series_ids:
                if sid not in data:
                    continue
                d = data[sid]
                label, unit, freq = meta[sid]
                latest   = d["latest"]
                previous = d.get("previous")

                try:
                    val = float(latest["value"])
                except (ValueError, TypeError):
                    continue

                # Direction arrow vs previous value
                arrow = ""
                if previous:
                    try:
                        prev_val = float(previous["value"])
                        diff = val - prev_val
                        if abs(diff) >= 0.01:
                            arrow = f" ({'↑' if diff > 0 else '↓'}{abs(diff):.2f})"
                    except (ValueError, TypeError):
                        pass

                # Format value
                if unit == "%":
                    val_str = f"{val:.2f}%"
                elif unit == "billions":
                    val_str = f"${val:,.0f}B"
                else:
                    val_str = f"{val:.2f}"

                date_str = latest.get("date", "")
                section_lines.append(
                    f"  {label:<42} {val_str}{arrow}  [{date_str}]"
                )

            if section_lines:
                lines.append(f"\n  {section_name}:")
                lines.extend(section_lines)

        if len(lines) == 1:
            return ""   # only header, no data

        # Append yield-curve interpretation
        if "T10Y2Y" in data:
            try:
                spread = float(data["T10Y2Y"]["latest"]["value"])
                if spread < 0:
                    lines.append(
                        f"\n  ⚠ Yield curve inverted ({spread:.2f}%): historically precedes recession"
                    )
                elif spread < 0.25:
                    lines.append(
                        f"\n  ⚠ Yield curve flat ({spread:.2f}%): elevated recession risk"
                    )
                else:
                    lines.append(
                        f"\n  Yield curve positive ({spread:.2f}%): normal growth signal"
                    )
            except (ValueError, TypeError):
                pass

        # Append recession probability callout
        if "RECPROUSM156N" in data:
            try:
                rec_prob = float(data["RECPROUSM156N"]["latest"]["value"])
                if rec_prob >= 30:
                    lines.append(
                        f"\n  ⚠ Recession probability elevated: {rec_prob:.1f}%"
                    )
            except (ValueError, TypeError):
                pass

        return "\n".join(lines)


# ── Module-level singleton ────────────────────────────────────────────────────
fred_client = FREDClient()


async def get_fred_macro_text() -> str:
    """
    Top-level coroutine called by main.py / macro_context.py.
    Returns an empty string if FRED_API_KEY is not configured.
    """
    if not fred_client.available:
        return ""
    try:
        data = await fred_client.fetch_all()
        return fred_client.format_for_prompt(data)
    except Exception as exc:
        logger.warning(f"FRED: get_fred_macro_text failed: {exc}")
        return ""
