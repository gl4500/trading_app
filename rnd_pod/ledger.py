"""Format and persist iteration verdicts to docs/model_improvement_ledger.md (newest on top)."""
from __future__ import annotations
from pathlib import Path


def format_verdict(*, hypothesis_id: str, claim: str, probe: str, numbers: str,
                   verdict: str, rationale: str, date: str) -> str:
    return (
        f"## {hypothesis_id} verdict: {verdict} ({date})\n\n"
        f"- **Claim:** {claim}\n"
        f"- **Probe:** {probe}\n"
        f"- **Numbers:** {numbers}\n"
        f"- **Verdict:** {verdict} — {rationale}\n"
    )


def append_verdict(ledger_path: Path, entry: str) -> None:
    text = Path(ledger_path).read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    insert_at = 0
    for i, line in enumerate(lines):
        if line.startswith("# "):
            insert_at = i + 1
            break
    block = f"\n{entry.rstrip()}\n"
    lines.insert(insert_at, block)
    Path(ledger_path).write_text("".join(lines), encoding="utf-8")
