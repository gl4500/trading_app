"""
regime_lead_probe.py — read-only sidecar that prints the leading-regime score.

Background
----------
The in-process [REGIME_LEAD] line emits only when macro_context's 15-min fast
cache REFRESHES, which is driven by AI agent prompt usage and can be sparse
(observed: 1 emit per 4 days when agents are throttled by Ollama latency).
This sidecar pulls macro data on demand and prints the score with the same
component breakdown, so the operator can see the leading signal regardless of
backend cadence.

Read-only — does NOT touch the backend, .env, or any model file.

Usage
-----
    runtime/python/python.exe scripts/regime_lead_probe.py
    runtime/python/python.exe scripts/regime_lead_probe.py --append-log scripts/logs/regime_lead.log
    runtime/python/python.exe scripts/regime_lead_probe.py --watch 15m

Options
-------
    --watch DURATION   loop forever, printing every DURATION (e.g. 5m, 30s, 1h)
    --append-log PATH  TSV-append each reading to PATH (creates header if new)
    --quiet            print only the single [REGIME_LEAD] line (machine-friendly)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import datetime, timezone

# ── Path bootstrap (mirror scripts/w3_review.py convention) ──────────────────
ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND  = os.path.join(ROOT, "backend")
SITE_PKG = os.path.join(ROOT, "site-packages")
for p in (BACKEND, SITE_PKG):
    if p not in sys.path:
        sys.path.insert(0, p)

# Force UTF-8 stdout so the formatted line never crashes on cp1252 consoles
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

import warnings
warnings.filterwarnings("ignore")

from data.regime_leading import compute_leading_score  # noqa: E402
from data.macro_context import _fetch_macro_data       # noqa: E402


# ── Time parsing ─────────────────────────────────────────────────────────────

_DURATION_RE = re.compile(r"^(\d+)([smhd])$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _parse_duration(s: str) -> int:
    m = _DURATION_RE.match(s.strip().lower())
    if not m:
        raise argparse.ArgumentTypeError(f"bad duration {s!r} (expected like 5m, 30s, 1h)")
    return int(m.group(1)) * _UNIT_SECONDS[m.group(2)]


# ── Core probe ───────────────────────────────────────────────────────────────

def probe_once() -> tuple[float, dict, dict]:
    """Fetch live macro + compute score. Returns (score, components, raw_components_for_log)."""
    data = _fetch_macro_data()
    if data is None:
        raise RuntimeError("_fetch_macro_data returned None — yfinance fetch failed")

    # macro_context returns 5d as percent (×100); compute_leading_score expects fractions.
    fractional = {
        sym: {k: (v / 100.0 if v is not None else None)
              for k, v in periods.items() if k != "price"}
        for sym, periods in data.items()
    }
    vix_p   = data.get("^VIX",   {}).get("price")
    vix3m_p = data.get("^VIX3M", {}).get("price")

    score, components = compute_leading_score(
        fast_returns=fractional, vix_price=vix_p, vix3m_price=vix3m_p,
    )

    # Side-data the human-readable summary uses
    raw = {
        "vix":       vix_p,
        "vix3m":     vix3m_p,
        "vix_ratio": (vix_p / vix3m_p) if (vix_p and vix3m_p) else None,
        "hyg_5d":    (data.get("HYG", {}).get("5d")),
        "spy_5d":    (data.get("SPY", {}).get("5d")),
        "iwm_5d":    (data.get("IWM", {}).get("5d")),
    }
    return score, components, raw


# ── Formatting ───────────────────────────────────────────────────────────────

def _fmt_component(v):
    return f"{v:+.3f}" if v is not None else "n/a"


def _format_log_line(score: float, comps: dict) -> str:
    return (
        f"[REGIME_LEAD] score={score:+.3f} "
        f"vix_ts={_fmt_component(comps['vix_ts'])} "
        f"credit={_fmt_component(comps['credit'])} "
        f"def_cyc={_fmt_component(comps['def_cyc'])} "
        f"breadth={_fmt_component(comps['breadth'])}"
    )


def _print_summary(score: float, comps: dict, raw: dict) -> None:
    ts = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    print(f"\n── Leading-regime score @ {ts} ──")
    print(_format_log_line(score, comps))
    print()
    # Interpretation
    if score >= 0.5:
        verdict = "STRONG BULL LEAD"
    elif score >= 0.15:
        verdict = "mild bull lead"
    elif score > -0.15:
        verdict = "neutral / mixed"
    elif score > -0.5:
        verdict = "mild bear lead"
    else:
        verdict = "STRONG BEAR LEAD"
    print(f"  Verdict: {verdict}")
    print()
    print("  Components")
    print(f"    vix_ts  = {_fmt_component(comps['vix_ts'])}  "
          f"(VIX/^VIX3M = {raw['vix']:.2f}/{raw['vix3m']:.2f} = "
          f"{raw['vix_ratio']:.3f}; {'contango' if raw['vix_ratio'] and raw['vix_ratio'] < 1.0 else 'backwardation'})"
          if raw["vix_ratio"] is not None else
          f"    vix_ts  = {_fmt_component(comps['vix_ts'])}  (n/a)")
    if raw["hyg_5d"] is not None:
        print(f"    credit  = {_fmt_component(comps['credit'])}  (HYG 5d = {raw['hyg_5d']:+.2f}%)")
    else:
        print(f"    credit  = {_fmt_component(comps['credit'])}  (HYG missing)")
    print(f"    def_cyc = {_fmt_component(comps['def_cyc'])}  "
          f"(cyclical-vs-defensive 5d spread; <0 = defensives leading)")
    if raw["iwm_5d"] is not None and raw["spy_5d"] is not None:
        print(f"    breadth = {_fmt_component(comps['breadth'])}  "
              f"(IWM {raw['iwm_5d']:+.2f}% vs SPY {raw['spy_5d']:+.2f}%)")
    else:
        print(f"    breadth = {_fmt_component(comps['breadth'])}  (IWM or SPY missing)")
    print()


# ── TSV append ───────────────────────────────────────────────────────────────

_TSV_HEADER = "ts_utc\tscore\tvix_ts\tcredit\tdef_cyc\tbreadth\tvix\tvix3m\tvix_ratio\thyg_5d\tspy_5d\tiwm_5d\n"


def _append_tsv(path: str, score: float, comps: dict, raw: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    new_file = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as f:
        if new_file:
            f.write(_TSV_HEADER)
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        def _c(v): return f"{v:.4f}" if v is not None else ""
        f.write(
            f"{ts}\t{score:.4f}\t"
            f"{_c(comps['vix_ts'])}\t{_c(comps['credit'])}\t"
            f"{_c(comps['def_cyc'])}\t{_c(comps['breadth'])}\t"
            f"{_c(raw['vix'])}\t{_c(raw['vix3m'])}\t{_c(raw['vix_ratio'])}\t"
            f"{_c(raw['hyg_5d'])}\t{_c(raw['spy_5d'])}\t{_c(raw['iwm_5d'])}\n"
        )


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--watch", type=_parse_duration, default=None,
                        help="loop forever, sleeping this duration between samples (e.g. 5m, 30s, 1h)")
    parser.add_argument("--append-log", default=None,
                        help="TSV append file path (creates with header on first write)")
    parser.add_argument("--quiet", action="store_true",
                        help="print only the single [REGIME_LEAD] line per sample")
    args = parser.parse_args()

    def _one():
        try:
            score, comps, raw = probe_once()
        except Exception as e:
            print(f"regime_lead_probe: fetch error: {e}", file=sys.stderr)
            return None
        if args.quiet:
            print(_format_log_line(score, comps))
        else:
            _print_summary(score, comps, raw)
        if args.append_log:
            try:
                _append_tsv(args.append_log, score, comps, raw)
            except Exception as e:
                print(f"regime_lead_probe: log append failed: {e}", file=sys.stderr)
        return score

    if args.watch is None:
        return 0 if _one() is not None else 1

    # --watch mode
    while True:
        _one()
        try:
            time.sleep(args.watch)
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    sys.exit(main())
