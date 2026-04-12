"""
FRED API validation script.
Run after adding FRED_API_KEY to .env:

    runtime\python\python.exe scripts\test_fred.py
"""
import sys
import os
import asyncio

# Resolve paths so this works when run from scripts/ or repo root
_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
_site = os.path.join(_root, "site-packages")
_backend = os.path.join(_root, "backend")

for p in (_site, _backend):
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

# Load .env
from dotenv import load_dotenv
load_dotenv(os.path.join(_root, ".env"))

from data.fred_client import fred_client, FRED_SERIES


async def main():
    print()
    print("=" * 65)
    print("  FRED API — Validation Test")
    print("=" * 65)

    if not fred_client.available:
        print()
        print("  [ERROR] FRED_API_KEY not set in .env")
        print()
        print("  Get a free key at:")
        print("    https://fred.stlouisfed.org/docs/api/api_key.html")
        print()
        print("  Then add to .env:")
        print("    FRED_API_KEY=your_key_here")
        print()
        return

    print(f"\n  API key found. Fetching {len(FRED_SERIES)} series...\n")

    data = await fred_client.fetch_all()

    passed = 0
    failed = []

    for sid, label, unit, freq in FRED_SERIES:
        if sid in data:
            d       = data[sid]
            latest  = d["latest"]
            val     = latest.get("value", "?")
            date    = latest.get("date", "?")
            prev    = d.get("previous")
            prev_v  = prev["value"] if prev else "n/a"

            # Direction indicator
            arrow = ""
            try:
                diff = float(val) - float(prev_v)
                arrow = f"  ({'↑' if diff > 0 else '↓'}{abs(diff):.3f} vs prev)"
            except (ValueError, TypeError):
                pass

            print(f"  [OK]  {sid:<18} {val:>12}  [{date}]  ({freq}){arrow}")
            passed += 1
        else:
            print(f"  [ERR] {sid:<18} no data returned")
            failed.append(sid)

    print()
    print(f"  Result: {passed}/{len(FRED_SERIES)} series fetched successfully")
    if failed:
        print(f"  Failed: {', '.join(failed)}")

    if passed > 0:
        print()
        print("  Formatted macro text (as AI agents will see it):")
        print("  " + "-" * 60)
        text = fred_client.format_for_prompt(data)
        for line in text.splitlines():
            print("  " + line)
        print("  " + "-" * 60)

    print()


if __name__ == "__main__":
    asyncio.run(main())
