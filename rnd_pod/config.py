"""Configuration for the R&D pod. Parameterized on repo_root so the same pod
pattern can later be pointed at the Coinbase/polymarket_app repo + its ledger."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_NORTH_STAR = "realized PnL by regime (bull/neutral/bear/high_vol)"


@dataclass(frozen=True)
class PodConfig:
    repo_root: Path
    db_path: Path
    ledger_path: Path
    runtime_python: Path
    model: str = DEFAULT_MODEL
    north_star: str = DEFAULT_NORTH_STAR


def default_config(repo_root: Path) -> PodConfig:
    repo_root = Path(repo_root)
    return PodConfig(
        repo_root=repo_root,
        db_path=repo_root / "backend" / "trading.db",
        ledger_path=repo_root / "docs" / "model_improvement_ledger.md",
        runtime_python=repo_root / "runtime" / "python" / "python.exe",
    )
