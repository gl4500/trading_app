"""Run a probe script with the app runtime python and a read-only trading.db URI."""
from __future__ import annotations
import os
import subprocess
from pathlib import Path
from rnd_pod.config import PodConfig


def build_probe_cmd(runtime_python: Path, script_path: Path) -> list[str]:
    return [str(runtime_python), str(script_path)]


def probe_env(db_path: Path, base_env: dict | None = None) -> dict:
    env = dict(os.environ if base_env is None else base_env)
    env["TRADING_DB_RO_URI"] = f"file:{Path(db_path).as_posix()}?mode=ro"
    return env


def run_probe(cfg: PodConfig, script_path: Path, timeout: int = 600) -> tuple[int, str]:
    cmd = build_probe_cmd(cfg.runtime_python, script_path)
    env = probe_env(cfg.db_path)
    proc = subprocess.run(  # nosec B603 - fixed runtime python + caller-controlled probe path, no shell
        cmd, env=env, capture_output=True, text=True, timeout=timeout,
        cwd=str(cfg.repo_root),
    )
    return proc.returncode, proc.stdout + proc.stderr
