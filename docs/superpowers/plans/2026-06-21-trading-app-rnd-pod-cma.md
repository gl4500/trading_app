# trading_app R&D Pod (CMA) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a 4-agent Claude Managed Agents (CMA) R&D crew that runs the fail-fast model-improvement loop on a self-hosted (on-PC) sandbox, optimizing realized PnL by regime, with autonomy fenced by hard gates.

**Architecture:** A Python driver (the "data plane") creates one self-hosted Environment, three subagents (Quant Researcher, Red-Team Skeptic, Builder) and one coordinator (Research Lead) whose `multiagent` roster delegates to the three, then opens one Session per hypothesis and streams events. Tool execution happens in a worker that runs **on the operator's PC** (`EnvironmentWorker`, Git Bash), so the agents' bash/read/write tools act on the real `trading_app` repo and probes hit real local data via the app's `runtime/python/python.exe`. The CMA SDK lives in an isolated venv so the live app's pinned `anthropic==0.84.0` is never touched.

**Tech Stack:** Python 3.12; `anthropic>=0.111.0` (CMA beta `managed-agents-2026-04-01`) in an isolated venv; the app's embedded `runtime/python/python.exe` (has pandas/xgboost/sqlite) for probes; Git Bash for the worker shell; `unittest` for tests (house convention).

## Global Constraints

- **Scope isolation — `trading_app` ONLY.** No file outside the `trading_app` repo is read or written; specifically **zero** `polymarket_app` paths. (`feedback_scope_restriction`)
- **`trading.db` is READ-ONLY to every probe.** Open via SQLite URI `file:<path>?mode=ro` or copy-to-temp. Pre-merge, the Lead asserts the DB file's SHA-256 is unchanged. DB at `backend/trading.db`.
- **Isolated venv only.** All CMA-SDK code runs under `rnd_pod/.cma-venv/Scripts/python.exe` (`anthropic>=0.111.0`). NEVER `pip install anthropic` into `site-packages` or `runtime/python` — the live app pins `anthropic==0.84.0` and an upgrade there can break the running Claude agent. Probes run under `runtime/python/python.exe` (0.84.0 — fine, probes don't import the CMA SDK).
- **Model:** `claude-opus-4-8` (exact string) for all four agents. Note: per-agent reasoning-effort is **not** a field on `beta.agents.create` (verified against SDK 0.111.0) — effort/thinking is handled by the CMA orchestration layer; do not invent an `effort=` kwarg.
- **TDD required.** Tests first → run red → implement → run green → commit. (`feedback_tdd_workflow`)
- **Push on commit.** Every commit is pushed in the same step. (`feedback_push_on_commit`) Work stays on branch `docs/rnd-pod-cma-spec` (already cut from `main`); do not commit on `main`.
- **No pod runs while the live backend is trading/training.** The driver and worker are started on demand by the operator, not as a service.
- **Verified SDK signatures (anthropic 0.111.0) — use exactly these:**
  - `client.beta.agents.create(name=, model=, system=, tools=, multiagent=, description=)` → returns object with `.id`, `.version`
  - `client.beta.environments.create(name=, config={"type":"self_hosted"})` → `.id`
  - `client.beta.sessions.create(agent=<id-or-{type,id,version}>, environment_id=)` → `.id`, `.status`
  - `client.beta.sessions.events.stream(session_id=)` (context manager) / `.send(session_id=, events=[...])`
  - Toolset entry: `{"type": "agent_toolset_20260401"}`
  - Multiagent (top-level on coordinator): `{"type":"coordinator","agents":[id, {"type":"agent","id":id,"version":v}, {"type":"self"}]}`

---

### Task 1: Prove the foundation — isolated venv, SDK surface, self-hosted worker, DB-RO probe

This is the spec's mandated "validate first" step: confirm the whole worker → Git Bash → `runtime/python/python.exe` → `trading.db` (read-only) path works **before** building the roster. It is validation-by-running (not TDD) because it exercises the live CMA API and the OS shell; each step has an explicit expected result.

**Files:**
- Create: `rnd_pod/.cma-venv/` (git-ignored)
- Create: `rnd_pod/.gitignore`
- Create: `rnd_pod/requirements.txt`
- Create: `rnd_pod/validation/hello_probe.py`
- Create: `rnd_pod/validation/check_sdk.py`

**Interfaces:**
- Produces: `rnd_pod/.cma-venv/Scripts/python.exe` (the CMA-SDK interpreter used by every later task), and a confirmed `ANTHROPIC_ENVIRONMENT_KEY` workflow.

- [ ] **Step 1: Create the isolated venv from the app runtime and pin the SDK**

```bash
cd /c/Users/gl450/trading_app
./runtime/python/python.exe -m venv rnd_pod/.cma-venv
echo 'anthropic>=0.111.0' > rnd_pod/requirements.txt
./rnd_pod/.cma-venv/Scripts/python.exe -m pip install --quiet --disable-pip-version-check -r rnd_pod/requirements.txt
printf '.cma-venv/\n__pycache__/\n*.pyc\n' > rnd_pod/.gitignore
```

- [ ] **Step 2: Write the SDK-surface check**

```python
# rnd_pod/validation/check_sdk.py
"""Fail fast if the CMA surface is missing from the installed anthropic SDK."""
import sys
import anthropic

REQUIRED = ("agents", "environments", "sessions")

def main() -> int:
    client = anthropic.Anthropic(api_key="x")  # no network call; just attribute access
    missing = [name for name in REQUIRED if not hasattr(client.beta, name)]
    print(f"anthropic {anthropic.__version__}")
    if missing:
        print(f"MISSING CMA surface: {missing}")
        return 1
    print("OK: beta.agents / environments / sessions present")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Run the SDK check**

Run: `./rnd_pod/.cma-venv/Scripts/python.exe rnd_pod/validation/check_sdk.py`
Expected: prints `anthropic 0.111.0` (or newer) and `OK: beta.agents / environments / sessions present`, exit 0.

- [ ] **Step 4: Write the hello probe (reads trading.db READ-ONLY)**

```python
# rnd_pod/validation/hello_probe.py
"""Throwaway probe: prove the worker can run app-runtime python and read trading.db read-only.
Run with: runtime/python/python.exe rnd_pod/validation/hello_probe.py
"""
import os
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DB = REPO / "backend" / "trading.db"

def main() -> int:
    uri = f"file:{DB.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        tables = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    finally:
        con.close()
    print(f"trading.db opened read-only; {len(tables)} tables")
    # Prove read-only: a write must fail.
    con = sqlite3.connect(uri, uri=True)
    try:
        con.execute("CREATE TABLE _probe_should_fail (x INTEGER)")
        print("ERROR: write succeeded on a read-only handle")
        return 1
    except sqlite3.OperationalError:
        print("OK: write correctly rejected on read-only handle")
        return 0
    finally:
        con.close()

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the hello probe directly with the app runtime**

Run: `./runtime/python/python.exe rnd_pod/validation/hello_probe.py`
Expected: `trading.db opened read-only; N tables` then `OK: write correctly rejected on read-only handle`, exit 0.

- [ ] **Step 6: Create the self-hosted environment and run the worker (manual, operator-gated)**

This needs an Anthropic API key and a Console-generated environment key, so it is run by the operator. Document the exact commands in `rnd_pod/README.md` (created in Task 8); for this step, verify the handshake once:

```bash
# (operator) one-time, with ANTHROPIC_API_KEY exported:
./rnd_pod/.cma-venv/Scripts/python.exe - <<'PY'
import anthropic, os
c = anthropic.Anthropic()
env = c.beta.environments.create(name="trading-app-rnd", config={"type": "self_hosted"})
print("ENV_ID", env.id)
PY
# (operator) generate ANTHROPIC_ENVIRONMENT_KEY in the Console for that env, then:
export ANTHROPIC_ENVIRONMENT_KEY=sk-ant-oat01-...
export ANTHROPIC_ENVIRONMENT_ID=env_...
./rnd_pod/.cma-venv/Scripts/python.exe - <<'PY'
import asyncio, os
from anthropic import AsyncAnthropic
from anthropic.lib.environments import EnvironmentWorker
async def main():
    key = os.environ["ANTHROPIC_ENVIRONMENT_KEY"]
    async with AsyncAnthropic(auth_token=key) as client:
        await EnvironmentWorker(
            client,
            environment_id=os.environ["ANTHROPIC_ENVIRONMENT_ID"],
            environment_key=key,
            workdir="/c/Users/gl450/trading_app",
        ).run()
asyncio.run(main())
PY
```

Expected: the worker starts under Git Bash without a `/bin/bash not found` error and idles waiting for work. (If `/bin/bash` is missing, the validated fallback is to launch the worker from a Git Bash shell so `/bin/bash` resolves; record which shell worked.)

- [ ] **Step 7: Commit the validation harness (not the venv)**

```bash
git add rnd_pod/.gitignore rnd_pod/requirements.txt rnd_pod/validation/check_sdk.py rnd_pod/validation/hello_probe.py
git commit -m "feat(rnd_pod): foundation validation — isolated CMA venv, SDK check, read-only DB probe"
git push
```

---

### Task 2: PodConfig — paths and parameters (reusable for the Coinbase clone)

**Files:**
- Create: `rnd_pod/__init__.py`
- Create: `rnd_pod/config.py`
- Create: `rnd_pod/tests/__init__.py`
- Test: `rnd_pod/tests/test_config.py`

**Interfaces:**
- Produces: `PodConfig` (frozen dataclass: `repo_root: Path`, `db_path: Path`, `ledger_path: Path`, `runtime_python: Path`, `model: str`, `north_star: str`) and `default_config(repo_root: Path) -> PodConfig`. Later tasks import `from rnd_pod.config import PodConfig, default_config`.

- [ ] **Step 1: Write the failing test**

```python
# rnd_pod/tests/test_config.py
import unittest
from pathlib import Path
from rnd_pod.config import PodConfig, default_config

class TestConfig(unittest.TestCase):
    def test_default_config_derives_paths_from_repo_root(self):
        cfg = default_config(Path("/c/Users/gl450/trading_app"))
        self.assertEqual(cfg.db_path, Path("/c/Users/gl450/trading_app/backend/trading.db"))
        self.assertEqual(cfg.ledger_path, Path("/c/Users/gl450/trading_app/docs/model_improvement_ledger.md"))
        self.assertEqual(cfg.runtime_python, Path("/c/Users/gl450/trading_app/runtime/python/python.exe"))
        self.assertEqual(cfg.model, "claude-opus-4-8")
        self.assertIn("PnL", cfg.north_star)

    def test_config_is_frozen(self):
        cfg = default_config(Path("/tmp/x"))
        with self.assertRaises(Exception):
            cfg.model = "other"  # type: ignore[misc]

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./runtime/python/python.exe -m unittest rnd_pod.tests.test_config -v` (from repo root)
Expected: FAIL with `ModuleNotFoundError: No module named 'rnd_pod.config'`.

- [ ] **Step 3: Write the minimal implementation**

```python
# rnd_pod/__init__.py
```

```python
# rnd_pod/tests/__init__.py
```

```python
# rnd_pod/config.py
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./runtime/python/python.exe -m unittest rnd_pod.tests.test_config -v`
Expected: PASS (2 tests OK).

- [ ] **Step 5: Commit**

```bash
git add rnd_pod/__init__.py rnd_pod/config.py rnd_pod/tests/__init__.py rnd_pod/tests/test_config.py
git commit -m "feat(rnd_pod): PodConfig with repo-root-derived paths (TDD)"
git push
```

---

### Task 3: Safety gates — scope isolation + DB-untouched

**Files:**
- Create: `rnd_pod/gates.py`
- Test: `rnd_pod/tests/test_gates.py`

**Interfaces:**
- Consumes: nothing (pure functions).
- Produces:
  - `scope_violations(changed_paths: list[str], forbidden=("polymarket_app",)) -> list[str]` — returns the subset of paths that contain any forbidden token (case-insensitive) or are absolute paths escaping the repo (start with `..`).
  - `sha256_file(path: Path) -> str` — hex digest of a file.
  - `db_unchanged(before_sha: str, after_sha: str) -> bool` — equality check.

- [ ] **Step 1: Write the failing test**

```python
# rnd_pod/tests/test_gates.py
import hashlib
import tempfile
import unittest
from pathlib import Path
from rnd_pod.gates import scope_violations, sha256_file, db_unchanged

class TestGates(unittest.TestCase):
    def test_scope_violations_flags_polymarket_paths(self):
        changed = [
            "backend/agents/base_agent.py",
            "../polymarket_app/backend/main.py",
            "docs/model_improvement_ledger.md",
        ]
        self.assertEqual(
            scope_violations(changed),
            ["../polymarket_app/backend/main.py"],
        )

    def test_scope_violations_flags_parent_escape(self):
        self.assertEqual(scope_violations(["../secrets.env"]), ["../secrets.env"])

    def test_scope_violations_clean(self):
        self.assertEqual(scope_violations(["backend/agents/base_agent.py"]), [])

    def test_db_unchanged(self):
        self.assertTrue(db_unchanged("abc", "abc"))
        self.assertFalse(db_unchanged("abc", "def"))

    def test_sha256_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello")
            p = Path(f.name)
        try:
            self.assertEqual(sha256_file(p), hashlib.sha256(b"hello").hexdigest())
        finally:
            p.unlink()

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./runtime/python/python.exe -m unittest rnd_pod.tests.test_gates -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rnd_pod.gates'`.

- [ ] **Step 3: Write the minimal implementation**

```python
# rnd_pod/gates.py
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./runtime/python/python.exe -m unittest rnd_pod.tests.test_gates -v`
Expected: PASS (5 tests OK).

- [ ] **Step 5: Commit**

```bash
git add rnd_pod/gates.py rnd_pod/tests/test_gates.py
git commit -m "feat(rnd_pod): scope-isolation + DB-untouched safety gates (TDD)"
git push
```

---

### Task 4: Ledger verdict formatting + append

**Files:**
- Create: `rnd_pod/ledger.py`
- Test: `rnd_pod/tests/test_ledger.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `format_verdict(*, hypothesis_id: str, claim: str, probe: str, numbers: str, verdict: str, rationale: str, date: str) -> str` — a markdown block.
  - `append_verdict(ledger_path: Path, entry: str) -> None` — inserts `entry` immediately after the first markdown H1 line so newest is on top (matches the existing ledger's "newest on top" convention).

- [ ] **Step 1: Write the failing test**

```python
# rnd_pod/tests/test_ledger.py
import tempfile
import unittest
from pathlib import Path
from rnd_pod.ledger import format_verdict, append_verdict

class TestLedger(unittest.TestCase):
    def test_format_verdict_contains_fields(self):
        block = format_verdict(
            hypothesis_id="H12",
            claim="Porting the XGB bear gate to rule agents stops bear bleed.",
            probe="Re-score rule-agent bear closes with the gate applied.",
            numbers="bear PnL -19.3K -> -4.1K (244 closes)",
            verdict="GO",
            rationale="Survives leakage check; bear-only, no bull degradation.",
            date="2026-06-21",
        )
        self.assertIn("H12", block)
        self.assertIn("GO", block)
        self.assertIn("-19.3K", block)
        self.assertIn("2026-06-21", block)

    def test_append_verdict_puts_entry_after_h1(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "ledger.md"
            p.write_text("# Model Improvement Ledger\n\nOLD ENTRY\n", encoding="utf-8")
            append_verdict(p, "NEW ENTRY BLOCK")
            text = p.read_text(encoding="utf-8")
            self.assertLess(text.index("NEW ENTRY BLOCK"), text.index("OLD ENTRY"))
            self.assertTrue(text.startswith("# Model Improvement Ledger"))

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./runtime/python/python.exe -m unittest rnd_pod.tests.test_ledger -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rnd_pod.ledger'`.

- [ ] **Step 3: Write the minimal implementation**

```python
# rnd_pod/ledger.py
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./runtime/python/python.exe -m unittest rnd_pod.tests.test_ledger -v`
Expected: PASS (2 tests OK).

- [ ] **Step 5: Commit**

```bash
git add rnd_pod/ledger.py rnd_pod/tests/test_ledger.py
git commit -m "feat(rnd_pod): ledger verdict formatting + newest-on-top append (TDD)"
git push
```

---

### Task 5: Probe runner — command + read-only DB environment

The `run_probe` contract from the spec. Used two ways: (a) as documentation for how agents should invoke probes via bash, and (b) as a host-side helper the driver can use directly. Keep the command/env construction pure and tested; the actual subprocess call is a thin wrapper around it.

**Files:**
- Create: `rnd_pod/run_probe.py`
- Test: `rnd_pod/tests/test_run_probe.py`

**Interfaces:**
- Consumes: `PodConfig` (`from rnd_pod.config import PodConfig`).
- Produces:
  - `build_probe_cmd(runtime_python: Path, script_path: Path) -> list[str]`
  - `probe_env(db_path: Path, base_env: dict | None = None) -> dict` — returns a copy of `base_env` with `TRADING_DB_RO_URI` set to `file:<db>?mode=ro`.
  - `run_probe(cfg: PodConfig, script_path: Path, timeout: int = 600) -> tuple[int, str]` — runs the script, returns `(exit_code, combined_output)`.

- [ ] **Step 1: Write the failing test**

```python
# rnd_pod/tests/test_run_probe.py
import sys
import tempfile
import unittest
from pathlib import Path
from rnd_pod.config import default_config
from rnd_pod.run_probe import build_probe_cmd, probe_env, run_probe

class TestRunProbe(unittest.TestCase):
    def test_build_probe_cmd(self):
        cmd = build_probe_cmd(Path("/runtime/python.exe"), Path("/x/probe.py"))
        self.assertEqual(cmd, ["/runtime/python.exe", "/x/probe.py"])

    def test_probe_env_sets_readonly_uri(self):
        env = probe_env(Path("/c/Users/gl450/trading_app/backend/trading.db"), base_env={"PATH": "/x"})
        self.assertEqual(env["PATH"], "/x")
        self.assertEqual(
            env["TRADING_DB_RO_URI"],
            "file:/c/Users/gl450/trading_app/backend/trading.db?mode=ro",
        )

    def test_run_probe_executes_script(self):
        # Use the current interpreter as a stand-in "runtime python" for the test.
        with tempfile.TemporaryDirectory() as d:
            script = Path(d) / "probe.py"
            script.write_text("print('probe-ran')\n", encoding="utf-8")
            cfg = default_config(Path(d))
            object.__setattr__(cfg, "runtime_python", Path(sys.executable))
            code, out = run_probe(cfg, script)
            self.assertEqual(code, 0)
            self.assertIn("probe-ran", out)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./runtime/python/python.exe -m unittest rnd_pod.tests.test_run_probe -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rnd_pod.run_probe'`.

- [ ] **Step 3: Write the minimal implementation**

```python
# rnd_pod/run_probe.py
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
    proc = subprocess.run(
        cmd, env=env, capture_output=True, text=True, timeout=timeout,
        cwd=str(cfg.repo_root),
    )
    return proc.returncode, proc.stdout + proc.stderr
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./runtime/python/python.exe -m unittest rnd_pod.tests.test_run_probe -v`
Expected: PASS (3 tests OK).

- [ ] **Step 5: Commit**

```bash
git add rnd_pod/run_probe.py rnd_pod/tests/test_run_probe.py
git commit -m "feat(rnd_pod): probe runner with read-only DB env (TDD)"
git push
```

---

### Task 6: Agent definitions — the 4-role roster builders

**Files:**
- Create: `rnd_pod/agents.py`
- Test: `rnd_pod/tests/test_agents.py`

**Interfaces:**
- Consumes: `PodConfig`.
- Produces (each returns the kwargs dict for `client.beta.agents.create`, so they are unit-testable without the API):
  - `researcher_agent(cfg) -> dict`, `skeptic_agent(cfg) -> dict`, `builder_agent(cfg) -> dict`
  - `lead_agent(cfg, roster_ids: list[str]) -> dict` — includes `multiagent={"type":"coordinator","agents": roster_ids}`
  - `AGENT_TOOLSET = {"type": "agent_toolset_20260401"}`
  - `create_pod(client, cfg) -> dict[str,str]` — creates the 3 subagents then the coordinator, returns `{"researcher":id,"skeptic":id,"builder":id,"lead":id}`. (Thin API wrapper; exercised in Task 8, not unit-tested.)

- [ ] **Step 1: Write the failing test**

```python
# rnd_pod/tests/test_agents.py
import unittest
from pathlib import Path
from rnd_pod.config import default_config
from rnd_pod.agents import (
    researcher_agent, skeptic_agent, builder_agent, lead_agent, AGENT_TOOLSET,
)

class TestAgents(unittest.TestCase):
    def setUp(self):
        self.cfg = default_config(Path("/c/Users/gl450/trading_app"))

    def test_each_agent_uses_model_and_toolset(self):
        for build in (researcher_agent, skeptic_agent, builder_agent):
            a = build(self.cfg)
            self.assertEqual(a["model"], "claude-opus-4-8")
            self.assertIn(AGENT_TOOLSET, a["tools"])
            self.assertTrue(a["system"].strip())

    def test_skeptic_system_demands_go_nogo(self):
        a = skeptic_agent(self.cfg)
        self.assertIn("GO", a["system"])
        self.assertIn("NO-GO", a["system"])

    def test_builder_system_requires_tdd(self):
        self.assertIn("TDD", builder_agent(self.cfg)["system"].upper().replace("TEST-DRIVEN", "TDD"))

    def test_lead_has_coordinator_roster(self):
        a = lead_agent(self.cfg, roster_ids=["agent_r", "agent_s", "agent_b"])
        self.assertEqual(a["multiagent"]["type"], "coordinator")
        self.assertEqual(a["multiagent"]["agents"], ["agent_r", "agent_s", "agent_b"])

    def test_lead_system_states_scope_and_db_invariants(self):
        sys_text = lead_agent(self.cfg, roster_ids=[])["system"]
        self.assertIn("polymarket_app", sys_text)   # scope isolation called out
        self.assertIn("trading.db", sys_text)        # read-only DB called out
        self.assertIn("realized PnL", sys_text)      # north star

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./runtime/python/python.exe -m unittest rnd_pod.tests.test_agents -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rnd_pod.agents'`.

- [ ] **Step 3: Write the minimal implementation**

```python
# rnd_pod/agents.py
"""Builders for the 4-agent R&D pod. Each *_agent() returns kwargs for
client.beta.agents.create; create_pod() persists them and returns the IDs."""
from __future__ import annotations
from rnd_pod.config import PodConfig

AGENT_TOOLSET = {"type": "agent_toolset_20260401"}

_SCOPE_RULE = (
    "HARD RULES: Operate ONLY inside the trading_app repo. Never read or write any "
    "polymarket_app path. Treat trading.db as READ-ONLY — open it via the read-only "
    "SQLite URI (file:...?mode=ro) and never write to it."
)

def researcher_agent(cfg: PodConfig) -> dict:
    return {
        "name": "Quant Researcher",
        "model": cfg.model,
        "tools": [AGENT_TOOLSET],
        "system": (
            "You are the Quant Researcher. Propose ONE falsifiable hypothesis and the "
            "CHEAPEST probe that could kill it. Run the probe on real local data using "
            f"the app runtime python at {cfg.runtime_python}. Report raw numbers — "
            f"{cfg.north_star}, plus IC and sample sizes — with no spin. Probe cheaply "
            "BEFORE proposing any build. " + _SCOPE_RULE
        ),
    }

def skeptic_agent(cfg: PodConfig) -> dict:
    return {
        "name": "Red-Team Skeptic",
        "model": cfg.model,
        "tools": [AGENT_TOOLSET],
        "system": (
            "You are the Red-Team Skeptic, independent of the Builder. Attack every probe "
            "for leakage, look-ahead, overfit, selection bias, regime artifact, and "
            "insufficient sample size. Issue an explicit GO or NO-GO ruling with reasons. "
            "Never loosen an honest falsifier to manufacture a GO — a clean NO-GO that "
            "prevents shipping noise is a success. " + _SCOPE_RULE
        ),
    }

def builder_agent(cfg: PodConfig) -> dict:
    return {
        "name": "Builder",
        "model": cfg.model,
        "tools": [AGENT_TOOLSET],
        "system": (
            "You are the Builder. Engage ONLY on a GO ruling. Follow TDD strictly: write "
            "the failing test first, run it red, implement the minimal change, run the FULL "
            "test suite green, then report evidence (commands + output). Do not expand scope "
            "beyond the approved hypothesis. " + _SCOPE_RULE
        ),
    }

def lead_agent(cfg: PodConfig, roster_ids: list[str]) -> dict:
    return {
        "name": "Research Lead",
        "model": cfg.model,
        "tools": [AGENT_TOOLSET],
        "multiagent": {"type": "coordinator", "agents": list(roster_ids)},
        "system": (
            "You are the Research Lead and coordinator. Each iteration: (1) read "
            f"{cfg.ledger_path} (newest on top) and pick the next hypothesis; (2) delegate "
            "framing+probe to the Quant Researcher; (3) delegate critique to the Red-Team "
            "Skeptic; (4) referee GO/NO-GO judged on " + cfg.north_star + " — on NO-GO, "
            "append the verdict to the ledger and end the iteration; (5) on GO, delegate "
            "the build to the Builder (TDD); (6) independently verify before merge: full "
            "suite green, scope isolation held (NO polymarket_app paths in the diff), and "
            "trading.db SHA-256 unchanged; (7) merge to main only if all gates pass, then "
            "append the outcome to the ledger. Subagents do NOT share your history — pass "
            "everything they need in each delegated message. " + _SCOPE_RULE
        ),
    }

def create_pod(client, cfg: PodConfig) -> dict[str, str]:
    researcher = client.beta.agents.create(**researcher_agent(cfg))
    skeptic = client.beta.agents.create(**skeptic_agent(cfg))
    builder = client.beta.agents.create(**builder_agent(cfg))
    lead = client.beta.agents.create(
        **lead_agent(cfg, roster_ids=[researcher.id, skeptic.id, builder.id])
    )
    return {
        "researcher": researcher.id,
        "skeptic": skeptic.id,
        "builder": builder.id,
        "lead": lead.id,
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./runtime/python/python.exe -m unittest rnd_pod.tests.test_agents -v`
Expected: PASS (5 tests OK).

- [ ] **Step 5: Commit**

```bash
git add rnd_pod/agents.py rnd_pod/tests/test_agents.py
git commit -m "feat(rnd_pod): 4-role agent builders + create_pod (TDD)"
git push
```

---

### Task 7: Session runner — environment + stream-first loop with terminal gate

**Files:**
- Create: `rnd_pod/environment.py`
- Create: `rnd_pod/session_runner.py`
- Test: `rnd_pod/tests/test_session_runner.py`

**Interfaces:**
- Consumes: `PodConfig`, the pod IDs from `create_pod`.
- Produces:
  - `self_hosted_env_kwargs(name: str) -> dict` — `{"name": name, "config": {"type": "self_hosted"}}`.
  - `ensure_environment(client, name: str) -> str` — create (or reuse by name) → environment id.
  - `is_terminal(event_type: str, stop_reason_type: str | None = None) -> bool` — break gate: True on `session.status_terminated`, or `session.status_idle` whose `stop_reason_type` is not `requires_action`.
  - `run_iteration(client, cfg, lead_id, env_id, kickoff_text) -> None` — stream-first: open stream, send the kickoff `user.message`, drain until `is_terminal`, printing `agent.message` text.

- [ ] **Step 1: Write the failing test (pure break-gate logic)**

```python
# rnd_pod/tests/test_session_runner.py
import unittest
from rnd_pod.session_runner import is_terminal, self_hosted_env_kwargs

class TestSessionRunner(unittest.TestCase):
    def test_terminated_is_terminal(self):
        self.assertTrue(is_terminal("session.status_terminated"))

    def test_idle_end_turn_is_terminal(self):
        self.assertTrue(is_terminal("session.status_idle", "end_turn"))

    def test_idle_requires_action_is_not_terminal(self):
        self.assertFalse(is_terminal("session.status_idle", "requires_action"))

    def test_agent_message_is_not_terminal(self):
        self.assertFalse(is_terminal("agent.message"))

    def test_env_kwargs(self):
        self.assertEqual(
            self_hosted_env_kwargs("trading-app-rnd"),
            {"name": "trading-app-rnd", "config": {"type": "self_hosted"}},
        )

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./runtime/python/python.exe -m unittest rnd_pod.tests.test_session_runner -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rnd_pod.session_runner'`.

- [ ] **Step 3: Write the minimal implementation**

```python
# rnd_pod/environment.py
"""Self-hosted environment helpers."""
from __future__ import annotations

def self_hosted_env_kwargs(name: str) -> dict:
    return {"name": name, "config": {"type": "self_hosted"}}

def ensure_environment(client, name: str) -> str:
    for env in client.beta.environments.list():
        if env.name == name:
            return env.id
    return client.beta.environments.create(**self_hosted_env_kwargs(name)).id
```

```python
# rnd_pod/session_runner.py
"""Create a session for one hypothesis and drain its event stream (stream-first)."""
from __future__ import annotations
from rnd_pod.config import PodConfig
from rnd_pod.environment import self_hosted_env_kwargs, ensure_environment  # noqa: F401 (re-export)

def is_terminal(event_type: str, stop_reason_type: str | None = None) -> bool:
    if event_type == "session.status_terminated":
        return True
    if event_type == "session.status_idle" and stop_reason_type != "requires_action":
        return True
    return False

def _stop_reason_type(event) -> str | None:
    sr = getattr(event, "stop_reason", None)
    return getattr(sr, "type", None) if sr is not None else None

def run_iteration(client, cfg: PodConfig, lead_id: str, env_id: str, kickoff_text: str) -> None:
    session = client.beta.sessions.create(agent=lead_id, environment_id=env_id)
    print(f"session {session.id} — "
          f"https://platform.claude.com/workspaces/default/sessions/{session.id}")
    with client.beta.sessions.events.stream(session_id=session.id) as stream:
        client.beta.sessions.events.send(
            session_id=session.id,
            events=[{"type": "user.message",
                     "content": [{"type": "text", "text": kickoff_text}]}],
        )
        for event in stream:
            if event.type == "agent.message":
                for block in getattr(event, "content", []) or []:
                    if getattr(block, "type", None) == "text":
                        print(block.text, end="", flush=True)
            if is_terminal(event.type, _stop_reason_type(event)):
                break
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./runtime/python/python.exe -m unittest rnd_pod.tests.test_session_runner -v`
Expected: PASS (5 tests OK).

- [ ] **Step 5: Commit**

```bash
git add rnd_pod/environment.py rnd_pod/session_runner.py rnd_pod/tests/test_session_runner.py
git commit -m "feat(rnd_pod): self-hosted env + stream-first session runner with terminal gate (TDD)"
git push
```

---

### Task 8: Kickoff CLI (setup/runtime split) + README, and run the full suite

**Files:**
- Create: `rnd_pod/kickoff.py`
- Create: `rnd_pod/README.md`

**Interfaces:**
- Consumes: everything above. `create_pod`, `ensure_environment`, `run_iteration`, `default_config`.
- Produces: a CLI that loads pod IDs from a JSON file (setup writes them once) and runs one iteration on a given hypothesis (default: the H12 kickoff text), keeping `agents.create` out of the per-run path.

- [ ] **Step 1: Write the kickoff CLI**

```python
# rnd_pod/kickoff.py
"""On-demand kickoff for one R&D iteration.

Setup (once):   python -m rnd_pod.kickoff setup
Run (per iter): python -m rnd_pod.kickoff run [--hypothesis H12]

Run with the CMA venv: rnd_pod/.cma-venv/Scripts/python.exe
Requires ANTHROPIC_API_KEY in the environment, and a worker running on this PC
(see README). agents.create() runs only in `setup`, never in `run`.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import anthropic
from rnd_pod.config import default_config
from rnd_pod.agents import create_pod
from rnd_pod.environment import ensure_environment
from rnd_pod.session_runner import run_iteration

REPO = Path(__file__).resolve().parents[1]
IDS_FILE = REPO / "rnd_pod" / "pod_ids.json"
ENV_NAME = "trading-app-rnd"

H12_KICKOFF = (
    "Run one R&D iteration. Read docs/model_improvement_ledger.md and pursue H12: the "
    "non-gated rule agents (Momentum/MeanRev/Tech/HistTrends) bleed about -$19.3K in bear "
    "(244 closes, ~37% win). Hypothesis: porting the XGB agent's proven bear gate to them "
    "via a shared BaseAgent entry gate reduces that bleed without degrading bull. Have the "
    "Quant Researcher frame the falsifiable claim and run the cheapest probe on trading.db "
    "(read-only); have the Red-Team Skeptic rule GO/NO-GO; referee; on GO, build with TDD, "
    "verify the gates, merge, and log the verdict. On NO-GO, log the verdict and stop."
)

def cmd_setup() -> None:
    cfg = default_config(REPO)
    client = anthropic.Anthropic()
    ids = create_pod(client, cfg)
    IDS_FILE.write_text(json.dumps(ids, indent=2), encoding="utf-8")
    print(f"created pod, wrote {IDS_FILE}: {ids}")

def cmd_run(hypothesis: str) -> None:
    cfg = default_config(REPO)
    if not IDS_FILE.exists():
        raise SystemExit("pod_ids.json missing — run `setup` first")
    ids = json.loads(IDS_FILE.read_text(encoding="utf-8"))
    client = anthropic.Anthropic()
    env_id = ensure_environment(client, ENV_NAME)
    kickoff = H12_KICKOFF if hypothesis == "H12" else f"Run one R&D iteration pursuing {hypothesis}."
    run_iteration(client, cfg, lead_id=ids["lead"], env_id=env_id, kickoff_text=kickoff)

def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    run_p = sub.add_parser("run")
    run_p.add_argument("--hypothesis", default="H12")
    args = parser.parse_args()
    if args.cmd == "setup":
        cmd_setup()
    else:
        cmd_run(args.hypothesis)

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write the README (operator runbook)**

```markdown
# rnd_pod — trading_app R&D crew (Claude Managed Agents)

4-agent fail-fast R&D loop. Design spec: `docs/superpowers/specs/2026-06-21-trading-app-rnd-pod-cma-design.md`.

## One-time setup
1. `runtime/python/python.exe -m venv rnd_pod/.cma-venv`
2. `rnd_pod/.cma-venv/Scripts/python.exe -m pip install -r rnd_pod/requirements.txt`
3. `rnd_pod/.cma-venv/Scripts/python.exe rnd_pod/validation/check_sdk.py`  (expect OK)
4. `runtime/python/python.exe rnd_pod/validation/hello_probe.py`  (expect read-only OK)
5. Export `ANTHROPIC_API_KEY`. Create the env + pod:
   `rnd_pod/.cma-venv/Scripts/python.exe -m rnd_pod.kickoff setup`
6. In the Console, generate an environment key for `trading-app-rnd`; export
   `ANTHROPIC_ENVIRONMENT_KEY` and `ANTHROPIC_ENVIRONMENT_ID`.

## Each iteration
1. Confirm the live backend is NOT trading/training.
2. Start the worker **from a Git Bash shell** (needs /bin/bash), workdir = repo root:
   `rnd_pod/.cma-venv/Scripts/python.exe -m rnd_pod.worker`  (or the EnvironmentWorker
   snippet in validation Step 6 until a worker module is added).
3. Kick off: `rnd_pod/.cma-venv/Scripts/python.exe -m rnd_pod.kickoff run --hypothesis H12`
4. Watch the printed Console session URL. The Lead merges to main and logs the verdict
   to `docs/model_improvement_ledger.md` on a GO; on a NO-GO it just logs and stops.

## Safety gates (all enforced before any merge)
Skeptic GO on an honest falsifier · full suite green · no polymarket_app paths in the
diff · trading.db SHA-256 unchanged · Lead verification independent of the Builder ·
rollback = `git revert`.
```

- [ ] **Step 3: Run the FULL pod test suite (verification before completion)**

Run: `./runtime/python/python.exe -m unittest discover -s rnd_pod/tests -v`
Expected: all tests from Tasks 2–7 PASS (config, gates, ledger, run_probe, agents, session_runner), 0 failures.

- [ ] **Step 4: Commit**

```bash
git add rnd_pod/kickoff.py rnd_pod/README.md
git commit -m "feat(rnd_pod): on-demand kickoff CLI (setup/runtime split) + operator README"
git push
```

- [ ] **Step 5: Operator end-to-end dry run (manual, gated)**

With the worker running and the backend idle, run `kickoff run --hypothesis H12` and confirm: the session reaches `running`, the Researcher's probe reads `trading.db` read-only, the Skeptic issues GO/NO-GO, and the iteration ends with a ledger entry. This is the real first iteration — treat its verdict as the loop's first output.

---

## Self-Review

**Spec coverage:**
- 4-agent roster (Lead/Researcher/Skeptic/Builder) → Task 6. ✅
- Self-hosted environment + on-PC worker (Git Bash, `runtime/python/python.exe`) → Tasks 1, 7. ✅
- One session per iteration, stream-first, terminal gate → Task 7. ✅
- North-star = realized PnL by regime → encoded in agent prompts (Task 6) + kickoff (Task 8). ✅
- Full autonomy incl. auto-merge, fenced by the 6 gates → Lead prompt (Task 6) + gates module (Task 3) + README. ✅ (Honest-falsifier + green-suite + scope-isolation + DB-untouched + independent verification + git-revert rollback.)
- Windows-worker risk validated FIRST → Task 1. ✅
- `run_probe` contract + read-only DB → Task 5. ✅
- Reusable for the Coinbase clone → `PodConfig` parameterized on repo_root/paths (Task 2); agent builders take `cfg`. ✅
- CMA object creation order (subagents → coordinator → environment → per-iteration session) → `create_pod` (Task 6) + `kickoff` setup/run split (Task 8). ✅

**Corrections folded in from SDK validation (not in the original spec, now load-bearing):**
- `anthropic>=0.111.0` in an isolated venv; the live app's pinned `0.84.0` is never touched (Global Constraints, Task 1). The spec assumed the SDK was present; it is, but the wrong version, and upgrading shared `site-packages` would risk the running app.
- Per-agent reasoning effort is NOT a `beta.agents.create` field in 0.111.0 — the spec's "high reasoning effort" is dropped from the code; effort is the orchestration layer's concern.

**Placeholder scan:** none — every step has runnable code/commands and expected output.

**Type consistency:** `PodConfig` fields and `default_config` are used identically across Tasks 2/5/6/7/8; `create_pod` returns `{"researcher","skeptic","builder","lead"}` and `kickoff` reads `ids["lead"]`; `is_terminal`'s signature matches its test and its call site in `run_iteration`.

**Known follow-ups (out of scope for this plan, noted for the implementer):**
- A dedicated `rnd_pod/worker.py` module wrapping `EnvironmentWorker` (the README currently points at the validation snippet). Add it once Task 1 Step 6 confirms the worker shell.
- The Lead enforces the scope/DB gates via its own bash + the `rnd_pod.gates` helpers; if a hard pre-merge hook is wanted instead, add it after the first real iteration (spec open question #2).
