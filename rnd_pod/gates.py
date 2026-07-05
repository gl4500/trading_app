"""Pure safety-gate predicates. The Lead calls these pre-merge; they never touch the API."""
from __future__ import annotations
import hashlib
from pathlib import Path

DEFAULT_FORBIDDEN = ("polymarket_app",)


def scope_violations(changed_paths: list[str], forbidden: tuple[str, ...] = DEFAULT_FORBIDDEN) -> list[str]:
    """Return paths that touch a forbidden project or escape the repo root via '..'."""
    bad: list[str] = []
    for raw in changed_paths:
        p = raw.replace("\\", "/")
        lowered = p.lower()
        if any(tok.lower() in lowered for tok in forbidden) or p.startswith(".."):
            bad.append(raw)
    return bad


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def db_unchanged(before_sha: str, after_sha: str) -> bool:
    return before_sha == after_sha
