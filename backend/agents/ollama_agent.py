"""
Ollama Agent: Uses local Ollama (llama3.1:8b by default) for trading decisions.

Standalone ensemble member — does NOT depend on ClaudeAgent or any cloud API.
Designed to vote independently; if Claude is unreachable / rate-limited /
crashes, this agent keeps producing decisions, and vice versa.

Prompt-building helpers are intentionally duplicated from ClaudeAgent rather
than imported. Reasons:
  1. True runtime isolation — a refactor or breakage in ClaudeAgent cannot
     propagate into OllamaAgent's analyze() path.
  2. Different system prompt — local models benefit from shorter, more
     directive instructions; cloud models can handle verbose framing.
  3. Each agent's prompt can evolve based on its own model's strengths
     without coordinating across two agents.

If the duplication ever becomes painful, extract to a mixin or shared
prompt-builder module; until then, copy-paste-and-customize is the right
trade-off for the explicit-independence design goal.
"""
import asyncio
import logging
import time
from typing import Dict, List, Optional

from agents.base_agent import BaseAgent, Signal
from agents.agent_utils import (
    extract_json,
    format_bars_for_prompt,
    build_portfolio_context,
    parse_ai_decisions,
    fill_missing_symbols,
    get_fallback_signals,
    _is_market_hours,
)
from config import config
from data.learning_manager import get_learning_summary, get_few_shot_examples
from data.sector_analysis import format_sector_summary
from data.news_service import news_service
from data.technicals import format_for_prompt as format_technicals
from data.signal_aggregator import format_for_prompt as format_composite
from data.agent_performance_tracker import agent_performance_tracker
from database import save_token_log, get_daily_token_total

logger = logging.getLogger(__name__)

try:
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None  # type: ignore[assignment,misc]


class OllamaAgent(BaseAgent):
    """Local Ollama trading agent — independent ensemble member.

    Calls the OpenAI-compatible Ollama endpoint at config.OLLAMA_BASE_URL with
    config.RESEARCH_MODEL. No cloud fallback, no Claude validation. If Ollama
    is unreachable or returns malformed JSON, returns fallback HOLD signals
    rather than crashing the ensemble.
    """

    # Smaller / more directive prompt than ClaudeAgent — local models follow
    # short imperatives better than long framings, and the JSON format
    # requirement needs to be hammered repeatedly to survive truncation /
    # creative drift.
    _SYSTEM_TEXT: str = (
        "You are a quantitative trader making BUY / SELL / HOLD decisions for stocks.\n\n"
        "## Decision Framework\n"
        "- BUY: bullish news + RSI <65 + MACD positive + price above SMA20\n"
        "- SELL: negative news + RSI >65 + MACD negative + price below SMA20\n"
        "- HOLD: signals diverge or evidence is weak\n\n"
        "Manage risk: don't over-concentrate, preserve capital, prefer technical timing.\n\n"
        "## Response Format — RAW JSON ONLY\n"
        'Output exactly this structure, no other text:\n'
        "{\n"
        '  "market_analysis": "<2-3 sentences>",\n'
        '  "decisions": [\n'
        '    {"symbol": "<TICKER>", "action": "BUY|SELL|HOLD", "shares": <int>, '
        '"confidence": <0.0-1.0>, "reasoning": "<1-2 sentences>"}\n'
        "  ]\n"
        "}\n\n"
        "First character must be '{'. Last character must be '}'. No prose, no markdown, "
        "no code fences. Include every requested symbol in decisions[]."
    )

    def __init__(self):
        super().__init__(
            name="OllamaAgent",
            strategy_description=(
                "Local Ollama (llama3.1:8b by default) — fast, free, "
                "independent of cloud API availability"
            ),
        )
        # Throttle: API call every N cycles. Local Ollama is "free" but the
        # per-call latency on commodity GPUs (~50s) means hitting it every
        # cycle backs up the trading loop. Match ClaudeAgent's cadence.
        self._open_interval = 5    # market hours
        self._closed_interval = 25  # off-hours
        self._cycle_count = 0
        self._analysis_interval = self._closed_interval
        self._last_decisions: Dict = {}
        # Concurrent-call guard — if a previous analyze() is still waiting
        # on Ollama, subsequent callers wait for its result rather than
        # piling on more concurrent requests against a serial GPU.
        self._api_lock = asyncio.Lock()

    async def seed_from_history(self) -> None:
        """Restore rolling 24h token window from DB after a restart."""
        try:
            prior = await get_daily_token_total("OllamaAgent", hours=24)
            if prior > 0:
                self._token_window.append((time.time(), prior))
        except Exception:
            pass

    # ── Prompt construction (copy of ClaudeAgent's helpers — see module
    #    docstring for why these are intentionally duplicated). ──────────

    def _build_stable_context(self, market_context: Dict) -> str:
        """Portfolio state + learning summary + macro context. Changes only
        when a trade executes, learning updates, or macro refreshes."""
        portfolio_ctx = build_portfolio_context(self.portfolio)
        learning_ctx = get_learning_summary()
        macro_ctx = market_context.get("__macro_context__", "")
        macro_section = f"\n\n{macro_ctx}" if macro_ctx else ""
        return (
            f"## Current Portfolio State\n{portfolio_ctx}\n"
            f"{learning_ctx}{macro_section}"
        )

    def _build_dynamic_context(self, market_context: Dict, watchlist: List[str]) -> str:
        """Market data, prices, news, macro, sector context — never cached."""
        market_sections = []
        for symbol in watchlist:
            ctx = market_context.get(symbol, {})
            bars = ctx.get("bars")
            stats = ctx.get("stats", {})
            price = ctx.get("price", 0)

            bars_text = format_bars_for_prompt(bars, limit=5) if bars is not None else "No data"
            news_items = ctx.get("news", [])
            news_text = news_service.format_for_prompt(symbol, news_items)
            ind = ctx.get("indicators")
            tech_text = format_technicals(symbol, ind, price)
            composite_sig = ctx.get("composite_signal", {})
            composite_text = format_composite(composite_sig)
            sector_ctx_text = ctx.get("sector_context_text", "")
            sector_line = f"\n### Sector Context\n{sector_ctx_text}\n" if sector_ctx_text else ""

            section = f"""
## {symbol} - Current Price: ${price:.2f}
Stats: 1D: {stats.get('price_change_1d', 0):+.1f}%, 5D: {stats.get('price_change_5d', 0):+.1f}%, 20D: {stats.get('price_change_20d', 0):+.1f}%
52W High: ${stats.get('high_52w', 0):.2f} | 52W Low: ${stats.get('low_52w', 0):.2f}
{sector_line}
### Multi-Source Composite Signal
{composite_text}

### Technical Indicators
{tech_text}

### News (last 24h)
{news_text}

### OHLCV Data (last 5 bars)
{bars_text}
"""
            market_sections.append(section)

        market_data = "\n".join(market_sections)

        sector_perf = market_context.get("__sector_context__", {})
        sector_summary = format_sector_summary(sector_perf)
        sector_section = (
            f"\n## Macro → Sector Context\n{sector_summary}\n" if sector_summary else ""
        )

        return (
            f"{sector_section}\n## Market Data\n{market_data}\n"
            f"\nInclude an entry for each symbol: {', '.join(watchlist)}"
        )

    # ── Ollama call ──────────────────────────────────────────────────────

    async def _get_decisions(
        self, market_context: Dict, watchlist: List[str]
    ) -> Optional[Dict]:
        """Call local Ollama and parse the response. Returns None on any
        failure — caller handles fallback."""
        if AsyncOpenAI is None:
            logger.warning("OllamaAgent: openai package not available")
            return None
        if not config.RESEARCH_MODEL:
            return None

        try:
            client = AsyncOpenAI(base_url=config.OLLAMA_BASE_URL, api_key="ollama")
            stable = self._build_stable_context(market_context)
            dynamic = self._build_dynamic_context(market_context, watchlist)
            few_shot = get_few_shot_examples(n=5)

            # Build agent signal section from other agents' last-cycle signals
            agent_signal_section = ""
            raw_agent_sigs = market_context.get("__agent_signals__", {})
            if isinstance(raw_agent_sigs, dict) and raw_agent_sigs:
                try:
                    metrics = agent_performance_tracker.get_metrics_summary()
                    lines = [
                        "## Other Agent Signals This Cycle",
                        "(Performance-weighted — informs your decisions)\n",
                    ]
                    for sym in watchlist:
                        sigs = raw_agent_sigs.get(sym)
                        if not sigs:
                            continue
                        consensus = agent_performance_tracker.consensus_score(sigs)
                        direction = (
                            "BULLISH" if consensus > 0.1
                            else ("BEARISH" if consensus < -0.1 else "NEUTRAL")
                        )
                        parts = []
                        for agent_name, (action, conf) in sorted(sigs.items()):
                            score = metrics.get(agent_name, {}).get("score", 0.5)
                            parts.append(
                                f"{agent_name}→{action}({conf:.2f},score={score:.2f})"
                            )
                        lines.append(
                            f"  {sym}: {' | '.join(parts)} → consensus={direction}({consensus:+.2f})"
                        )
                    agent_signal_section = "\n".join(lines) + "\n"
                except Exception:
                    pass  # Never block over signal formatting

            sections = [s for s in [few_shot, agent_signal_section, stable, dynamic] if s]
            user_content = "\n\n".join(sections)

            _t0 = time.perf_counter()
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=config.RESEARCH_MODEL,
                    messages=[
                        {"role": "system", "content": self._SYSTEM_TEXT},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=0.2,
                    max_tokens=4096,
                ),
                timeout=120.0,
            )
            _elapsed = time.perf_counter() - _t0
            if _elapsed > 15:
                logger.warning(
                    f"[OLLAMA_LATENCY] app=trading_app caller=OllamaAgent "
                    f"model={config.RESEARCH_MODEL} elapsed={_elapsed:.2f}s (SLOW)"
                )
            else:
                logger.info(
                    f"[OLLAMA_LATENCY] app=trading_app caller=OllamaAgent "
                    f"model={config.RESEARCH_MODEL} elapsed={_elapsed:.2f}s"
                )

            text = (response.choices[0].message.content or "").strip()
            if not text:
                logger.warning("OllamaAgent: empty response")
                return None

            self._call_timestamps.append(time.time())
            logger.info(f"OllamaAgent: received response from '{config.RESEARCH_MODEL}'")

            # Token bookkeeping (Ollama-OpenAI API exposes usage)
            try:
                usage = getattr(response, "usage", None)
                if usage is not None:
                    in_tok = getattr(usage, "prompt_tokens", 0) or 0
                    out_tok = getattr(usage, "completion_tokens", 0) or 0
                    self._token_window.append((time.time(), in_tok + out_tok))
                    self._session_tokens += in_tok + out_tok
                    await save_token_log(
                        agent="OllamaAgent",
                        model=config.RESEARCH_MODEL,
                        prompt_tokens=in_tok,
                        completion_tokens=out_tok,
                        total_tokens=in_tok + out_tok,
                        daily_total=self._daily_tokens,
                        limit_hit=False,
                    )
            except Exception as exc:
                logger.debug(f"OllamaAgent: token log save failed: {exc}")

            # Strip markdown fences that smaller models emit despite instructions
            import re
            text = re.sub(r'```(?:json)?\s*', '', text).strip()
            result = extract_json(text)
            if result is None:
                logger.error(f"OllamaAgent: JSON parse failed: {text[:200]}")
            return result

        except asyncio.TimeoutError:
            logger.warning(
                f"OllamaAgent: request timed out (model='{config.RESEARCH_MODEL}')"
            )
            return None
        except Exception as exc:
            logger.error(f"OllamaAgent: error: {exc}")
            return None

    # ── Public entry ─────────────────────────────────────────────────────

    async def analyze(self, market_context: Dict) -> List[Signal]:
        """Analyze the market and produce signals using local Ollama only."""
        prices = {
            s: ctx.get("price", 0)
            for s, ctx in market_context.items()
            if isinstance(ctx, dict)
        }

        # Build watchlist: same priority order as ClaudeAgent
        MAX_SYMBOLS = 12
        held = set(self.portfolio.positions.keys())
        picks = set(self.get_pick_symbols())
        core = [s for s in config.WATCHLIST if s in market_context]
        extras = [s for s in market_context if s not in core]
        prioritised_extras = (
            [s for s in extras if s in held]
            + [s for s in extras if s in picks and s not in held]
            + [s for s in extras if s not in held and s not in picks]
        )
        watchlist = (core + prioritised_extras)[:MAX_SYMBOLS]

        # Concurrent-call guard
        if self._api_lock.locked():
            async with self._api_lock:
                pass
            if self._last_decisions:
                return parse_ai_decisions(
                    self._last_decisions, market_context, prices,
                    self.portfolio, config.MAX_POSITION_SIZE, "OLLAMA ANALYSIS",
                )
            return get_fallback_signals(market_context, "OllamaAgent")

        async with self._api_lock:
            self._analysis_interval = (
                self._open_interval if _is_market_hours() else self._closed_interval
            )
            self._cycle_count += 1

            # Cycle throttle: replay cached decisions between API calls
            if self._cycle_count % self._analysis_interval != 1 and self._last_decisions:
                logger.debug(
                    f"OllamaAgent: replaying cached decisions (cycle {self._cycle_count})"
                )
                signals = parse_ai_decisions(
                    self._last_decisions, market_context, prices,
                    self.portfolio, config.MAX_POSITION_SIZE, "OLLAMA ANALYSIS",
                )
                return fill_missing_symbols(
                    signals, market_context, prices,
                    self.portfolio, self._picks, config.MAX_POSITION_SIZE, "OllamaAgent",
                )

            logger.info(
                f"OllamaAgent: requesting analysis from '{config.RESEARCH_MODEL}' "
                f"(cycle {self._cycle_count})"
            )
            response = await self._get_decisions(market_context, watchlist)

            try:
                if response is None:
                    if self._last_decisions:
                        logger.debug("OllamaAgent: no response — replaying last decisions")
                        signals = parse_ai_decisions(
                            self._last_decisions, market_context, prices,
                            self.portfolio, config.MAX_POSITION_SIZE, "OLLAMA ANALYSIS",
                        )
                        return fill_missing_symbols(
                            signals, market_context, prices,
                            self.portfolio, self._picks, config.MAX_POSITION_SIZE, "OllamaAgent",
                        )
                    logger.warning("OllamaAgent: no response and no cache — using fallback")
                    return get_fallback_signals(market_context, "OllamaAgent")

                response["_watchlist"] = watchlist
                self._last_decisions = response

                signals = parse_ai_decisions(
                    response, market_context, prices,
                    self.portfolio, config.MAX_POSITION_SIZE, "OLLAMA ANALYSIS",
                )
                signals = fill_missing_symbols(
                    signals, market_context, prices,
                    self.portfolio, self._picks, config.MAX_POSITION_SIZE, "OllamaAgent",
                )

                logger.info(f"OllamaAgent: got {len(signals)} signals")
                return signals

            except Exception as e:
                logger.error(f"OllamaAgent: error in analyze: {e}", exc_info=True)
                return get_fallback_signals(market_context, "OllamaAgent")
