"""
FRED (Federal Reserve Economic Data) Client
--------------------------------------------
Fetches non-redundant US macroeconomic statistics from the St. Louis Fed REST API.

Why FRED vs. ETF proxies (GLD, TLT, ^VIX, ^TNX already in macro_context.py):
  - ETF proxies reflect *market expectations* in real time.
  - FRED series reflect *actual reported data* — CPI, unemployment, GDP.
  - The two complement each other: market view vs. hard numbers.

Staleness contract — CRITICAL for CNN confidence adjustment:
  DAILY series   : data is <= 1 business day old — safe to use for confidence
                   adjustment in the CNN agent.
  MONTHLY series : data can be up to 31 days old — used for narrative context
                   ONLY. Never used to mechanically shift confidence, because a
                   tariff shock or Fed pivot last week renders month-old CPI
                   misleading in the wrong direction.

Redundant series intentionally excluded (already in macro_context.py via yfinance):
  VIXCLS  — duplicate of ^VIX
  T10Y2Y  — duplicate of ^TNX spread calculation

Series kept:
  Daily  : DFF (Fed funds), T10YIE (breakeven inflation) — confidence-eligible
  Monthly: CPIAUCSL, CPILFESL, UNRATE, UMCSENT, RECPROUSM156N — context only
  Quarterly: GDP — context only

Cache TTL: 4 hours — FRED data updates at most once per day.
"""
import asyncio
import logging
import time
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import httpx

from config import config

logger = logging.getLogger(__name__)

_BASE_URL  = "https://api.stlouisfed.org/fred/series/observations"
_CACHE_TTL = 4 * 3600   # 4 hours
_TIMEOUT   = 15.0
_LIMIT     = 3           # last 3 observations — enough to detect direction

# ── Series definitions ────────────────────────────────────────────────────────
# (series_id, label, unit, frequency)
# frequency drives the staleness rule — "daily" series may adjust CNN confidence;
# "monthly"/"quarterly" series are context-only regardless of their value.
FRED_SERIES: List[Tuple[str, str, str, str]] = [
    # Daily — confidence-eligible
    ("DFF",           "Fed Funds Rate (effective)",    "%",        "daily"),
    ("T10YIE",        "10Y Breakeven Inflation Rate",  "%",        "daily"),
    # Monthly — context only
    ("CPIAUCSL",      "CPI All-Urban (headline)",      "index",    "monthly"),
    ("CPILFESL",      "Core CPI ex food/energy",       "index",    "monthly"),
    ("UNRATE",        "Unemployment Rate",              "%",        "monthly"),
    ("UMCSENT",       "UMich Consumer Sentiment",       "index",    "monthly"),
    ("RECPROUSM156N", "Recession Probability",          "%",        "monthly"),
    # Quarterly — context only
    ("GDP",           "GDP (nominal, seas. adj.)",      "billions", "quarterly"),
]

# Maximum age (days) for a series to be eligible for confidence adjustment.
# Daily series published on weekdays — allow up to 4 days to cover weekends/holidays.
_DAILY_STALE_THRESHOLD = 4

# ── In-memory cache ───────────────────────────────────────────────────────────
_cache: Dict[str, Tuple[float, dict]] = {}   # series_id -> (fetch_ts, data)
_fetch_lock = asyncio.Lock()


def _data_age_days(obs_date_str: str) -> Optional[int]:
    """Return calendar days since the observation date, or None if unparseable."""
    try:
        obs = datetime.strptime(obs_date_str, "%Y-%m-%d").date()
        return (date.today() - obs).days
    except (ValueError, TypeError):
        return None


def _is_confidence_eligible(sid: str, data: dict) -> bool:
    """
    Return True only if:
      - The series is tagged 'daily' in FRED_SERIES, AND
      - The latest observation is within _DAILY_STALE_THRESHOLD calendar days.

    Monthly series are NEVER confidence-eligible regardless of their values,
    because they may be up to 31 days old and misleading after recent events.
    """
    meta = {s: freq for s, _, _, freq in FRED_SERIES}
    if meta.get(sid) != "daily":
        return False
    age = _data_age_days(data.get("latest", {}).get("date", ""))
    if age is None:
        return False
    return age <= _DAILY_STALE_THRESHOLD


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
        """Fetch the latest N observations for one series. Returns cached data on error."""
        now = time.time()
        if series_id in _cache:
            ts, cached = _cache[series_id]
            if now - ts < _CACHE_TTL:
                return cached

        try:
            resp = await client.get(
                _BASE_URL,
                params={
                    "series_id":  series_id,
                    "api_key":    self._api_key,
                    "file_type":  "json",
                    "sort_order": "desc",
                    "limit":      _LIMIT,
                },
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            obs = [
                o for o in resp.json().get("observations", [])
                if o.get("value") not in (".", "")
            ]
            if not obs:
                return None
            result = {
                "series_id": series_id,
                "latest":    obs[0],
                "previous":  obs[1] if len(obs) > 1 else None,
            }
            _cache[series_id] = (now, result)
            return result
        except httpx.TimeoutException:
            logger.warning("FRED: timeout fetching %s — using stale cache", series_id)
        except Exception as exc:
            logger.warning("FRED: error fetching %s: %s", series_id, exc)
        # Return stale cache rather than nothing
        return _cache.get(series_id, (0, None))[1]

    async def fetch_all(self) -> Dict[str, dict]:
        """Fetch all configured series concurrently."""
        if not self.available:
            return {}

        async with _fetch_lock:
            async with httpx.AsyncClient() as client:
                results = await asyncio.gather(
                    *[self._fetch_series(client, sid) for sid, *_ in FRED_SERIES],
                    return_exceptions=True,
                )

        out = {}
        for (sid, *_), result in zip(FRED_SERIES, results):
            if isinstance(result, Exception):
                logger.warning("FRED: %s raised %s", sid, result)
            elif result is not None:
                out[sid] = result
        return out

    def format_for_prompt(self, data: Dict[str, dict]) -> str:
        """
        Format FRED data as a text block for AI prompts.

        Each line is tagged [FRESH] or [STALE:Nd] so the LLM can judge
        how much weight to give each number. Monthly series also carry a
        note that they are context-only and must not drive confidence changes.
        """
        if not data:
            return ""

        meta = {sid: (label, unit, freq) for sid, label, unit, freq in FRED_SERIES}

        sections = [
            ("Monetary policy (daily — confidence-eligible)",
             ["DFF", "T10YIE"]),
            ("Inflation / growth (monthly — CONTEXT ONLY, may be up to 31 days old)",
             ["CPIAUCSL", "CPILFESL", "UNRATE", "GDP"]),
            ("Sentiment / recession risk (monthly — CONTEXT ONLY)",
             ["UMCSENT", "RECPROUSM156N"]),
        ]

        lines = ["## FRED Economic Data (St. Louis Fed)"]

        for section_name, series_ids in sections:
            section_lines = []
            for sid in series_ids:
                if sid not in data:
                    continue
                d               = data[sid]
                label, unit, freq = meta[sid]
                latest          = d["latest"]
                previous        = d.get("previous")

                try:
                    val = float(latest["value"])
                except (ValueError, TypeError):
                    continue

                # Direction vs previous
                arrow = ""
                if previous:
                    try:
                        diff = val - float(previous["value"])
                        if abs(diff) >= 0.01:
                            arrow = f" ({'(+)' if diff > 0 else '(-)'}{abs(diff):.2f})"
                    except (ValueError, TypeError):
                        pass

                # Value formatting
                if unit == "%":
                    val_str = f"{val:.2f}%"
                elif unit == "billions":
                    val_str = f"${val:,.0f}B"
                else:
                    val_str = f"{val:.2f}"

                # Staleness tag — critical so LLM knows how fresh the number is
                obs_date = latest.get("date", "")
                age      = _data_age_days(obs_date)
                if age is None:
                    freshness = "[date unknown]"
                elif age <= _DAILY_STALE_THRESHOLD:
                    freshness = f"[FRESH: {obs_date}]"
                else:
                    freshness = f"[STALE: {age}d old, as of {obs_date}]"

                section_lines.append(
                    f"  {label:<35} {val_str}{arrow}  {freshness}"
                )

            if section_lines:
                lines.append(f"\n  {section_name}:")
                lines.extend(section_lines)

        if len(lines) == 1:
            return ""

        return "\n".join(lines)

    def get_confidence_signals(self, data: Dict[str, dict]) -> dict:
        """
        Return only the DAILY, FRESH series as structured signals for
        mechanical confidence adjustment in the CNN agent.

        Monthly/quarterly series are intentionally excluded — they are
        too stale after market-moving events to safely shift a confidence score.

        Returns: {
            "dff":    float | None,   # Fed Funds Rate
            "t10yie": float | None,   # 10Y Breakeven Inflation
        }
        """
        signals = {"dff": None, "t10yie": None}

        for sid, key in [("DFF", "dff"), ("T10YIE", "t10yie")]:
            d = data.get(sid)
            if d and _is_confidence_eligible(sid, d):
                try:
                    signals[key] = float(d["latest"]["value"])
                except (ValueError, TypeError):
                    pass
            elif d:
                age = _data_age_days(d.get("latest", {}).get("date", ""))
                logger.debug(
                    "FRED: %s excluded from confidence signals — %s days old (threshold %d)",
                    sid, age, _DAILY_STALE_THRESHOLD,
                )

        return signals


# ── Module-level singleton ────────────────────────────────────────────────────
fred_client = FREDClient()


async def get_fred_macro_text() -> str:
    """
    Top-level coroutine called by macro_context.py.
    Returns empty string if FRED_API_KEY is not configured.
    """
    if not fred_client.available:
        return ""
    try:
        data = await fred_client.fetch_all()
        return fred_client.format_for_prompt(data)
    except Exception as exc:
        logger.warning("FRED: get_fred_macro_text failed: %s", exc)
        return ""
