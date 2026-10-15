import subprocess
from pathlib import Path

import s1_receipt as r


def repo(tmp_path):
    be = tmp_path / "backend"
    (be / "agents").mkdir(parents=True)
    (be / "agents" / "mean_reversion_agent.py").write_text("from agents.base_agent import B\nimport config\nZ = config.MR_SELL_ZSCORE\n")
    (be / "agents" / "base_agent.py").write_text("from trading.portfolio import P\nimport numpy\n")
    (be / "trading").mkdir()
    (be / "trading" / "portfolio.py").write_text("X = 1\n")
    (be / "config.py").write_text("import os\nMR_SELL_ZSCORE = float(os.getenv('MR_SELL_ZSCORE', '1.5'))\n"
                                  "API = os.getenv('FRED_API_KEY')\n")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"],
                   check=True)
    return tmp_path


def test_closure_follows_in_repo_imports_only(tmp_path):
    root = repo(tmp_path)
    got = r.closure(root / "backend", ["agents/mean_reversion_agent.py"])
    assert got == ["agents/base_agent.py", "agents/mean_reversion_agent.py", "config.py", "trading/portfolio.py"]


def test_receipt_changes_with_code_or_mr_config_but_not_secrets(tmp_path):
    root = repo(tmp_path)
    env = tmp_path / ".env"
    env.write_text("MR_SELL_ZSCORE=1.5\nFRED_API_KEY=abc12345\n")
    a = r.semantic_receipt(root, env, None, roots=["agents/mean_reversion_agent.py"])
    env.write_text("MR_SELL_ZSCORE=1.5\nFRED_API_KEY=zzz99999\n")
    assert r.semantic_receipt(root, env, None, roots=["agents/mean_reversion_agent.py"]) == a
    env.write_text("MR_SELL_ZSCORE=2.0\nFRED_API_KEY=zzz99999\n")
    assert r.semantic_receipt(root, env, None, roots=["agents/mean_reversion_agent.py"]) != a
    assert "abc12345" not in str(a) and "FRED_API_KEY" not in a["config"]


def test_restart_record_parses_process_start_lines(tmp_path):
    log = tmp_path / "crash.log"
    log.write_text("2026-10-12 23:17:37 [PROCESS START] pid=38508\nnoise\n2026-10-20 08:00:01 [PROCESS START] pid=11\n")
    rec = r.restart_record(log)
    assert [s["pid"] for s in rec["starts"]] == [38508, 11] and rec["size"] == log.stat().st_size


def test_pid_change_without_process_start_line_is_gap(tmp_path):                         # example 11
    log = tmp_path / "crash.log"
    log.write_text("2026-10-12 23:17:37 [PROCESS START] pid=1\n")
    o1 = {"pid": 1, "process_start": "2026-10-12T23:17:25", "record": r.restart_record(log)}
    o2 = {"pid": 2, "process_start": "2026-10-21T09:00:00", "record": r.restart_record(log)}
    assert any("without a PROCESS START" in g for g in r.restart_gaps(o1, o2))
    log.write_text("")                                                                    # truncated
    o3 = {"pid": 2, "process_start": "2026-10-21T09:00:00", "record": r.restart_record(log)}
    assert any("truncated" in g for g in r.restart_gaps(o2, o3))


# ---------------- fix round 1 ----------------
import pytest


def _git_commit(root):
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "y"],
                   check=True)


def test_closure_includes_package_init(tmp_path):
    """Retrospective (Task 4 review fix round 1)."""
    root = repo(tmp_path)
    be = root / "backend"
    (be / "agents" / "__init__.py").write_text("from agents import helper\n")
    (be / "agents" / "helper.py").write_text("H = 1\n")
    (be / "trading" / "__init__.py").write_text("")
    got = r.closure(be, ["agents/mean_reversion_agent.py"])
    assert "agents/__init__.py" in got and "trading/__init__.py" in got and "agents/helper.py" in got
    a = r.semantic_receipt(root, None, None, roots=["agents/mean_reversion_agent.py"])
    (be / "agents" / "__init__.py").write_text("from agents import helper\nCHANGED = 1\n")
    assert r.semantic_receipt(root, None, None, roots=["agents/mean_reversion_agent.py"]) != a


def test_from_package_import_module(tmp_path):
    """Retrospective (Task 4 review fix round 1)."""
    root = repo(tmp_path)
    be = root / "backend"
    (be / "data").mkdir()
    (be / "data" / "technicals.py").write_text("T = 1\n")
    (be / "agents" / "mean_reversion_agent.py").write_text("from data import technicals\n")
    assert "data/technicals.py" in r.closure(be, ["agents/mean_reversion_agent.py"])


def test_relative_import_followed_and_escape_raises(tmp_path):
    """Retrospective (Task 4 review fix round 1)."""
    root = repo(tmp_path)
    be = root / "backend"
    (be / "agents" / "mean_reversion_agent.py").write_text("from . import base_agent\nfrom .base_agent import B\n")
    got = r.closure(be, ["agents/mean_reversion_agent.py"])
    assert "agents/base_agent.py" in got and "trading/portfolio.py" in got
    (be / "agents" / "mean_reversion_agent.py").write_text("from ... import x\n")
    with pytest.raises(ValueError):
        r.closure(be, ["agents/mean_reversion_agent.py"])
    (be / "agents" / "mean_reversion_agent.py").write_text("from ..x import y\n")
    got = r.closure(be, ["agents/mean_reversion_agent.py"])  # one level up = backend/, allowed
    assert got == ["agents/mean_reversion_agent.py"]


def test_missing_root_raises(tmp_path):
    """Retrospective (Task 4 review fix round 1)."""
    root = repo(tmp_path)
    with pytest.raises(ValueError):
        r.closure(root / "backend", ["agents/nope.py"])


def _cfg_repo(tmp_path, agent_src, config_src):
    root = repo(tmp_path)
    be = root / "backend"
    (be / "agents" / "mean_reversion_agent.py").write_text(agent_src)
    (be / "config.py").write_text(config_src)
    return root


CFG = ("import os\nUSED = float(os.getenv('MR_USED', '1'))\nUNUSED = os.getenv('MR_UNUSED', '1')\n"
       "SEC = os.getenv('SOME_API_KEY')\nSUB = os.environ['MR_SUB']\n")


def test_config_only_mr_used_names_and_unset_marker(tmp_path):
    """Retrospective (Task 4 review fix round 1)."""
    root = _cfg_repo(tmp_path, "import config\nx = config.USED\ny = config.SEC\nimport os\n"
                     "z = os.environ.get('MR_DIRECT')\nfrom config import SUB\n", CFG)
    env = tmp_path / ".env"
    env.write_text("MR_USED=3\nMR_UNUSED=9\nSOME_API_KEY=topsecret1\nMR_SUB=s\n")
    a = r.semantic_receipt(root, env, None, roots=["agents/mean_reversion_agent.py"])
    assert set(a["config"]) == {"MR_USED", "MR_SUB", "MR_DIRECT"}
    assert a["config"]["MR_DIRECT"] == r.c.sha256_bytes(b"<unset>")
    assert "topsecret1" not in str(a)
    env.write_text("MR_USED=3\nMR_UNUSED=10\nSOME_API_KEY=other\nMR_SUB=s\n")
    assert r.semantic_receipt(root, env, None, roots=["agents/mean_reversion_agent.py"]) == a
    env.write_text("MR_USED=3\nMR_SUB=s\nMR_DIRECT=now\n")
    assert r.semantic_receipt(root, env, None, roots=["agents/mean_reversion_agent.py"]) != a


def test_dirty_lists_any_extension_and_renames(tmp_path):
    """Retrospective (Task 4 review fix round 1)."""
    root = repo(tmp_path)
    be = root / "backend"
    (be / "data").mkdir()
    (be / "data" / "x.json").write_text("{}")
    _git_commit(root)
    (be / "data" / "x.json").write_text('{"a":1}')
    subprocess.run(["git", "-C", str(root), "mv", "backend/trading/portfolio.py", "backend/trading/pf2.py"],
                   check=True)
    (tmp_path / "outside.txt").write_text("o")
    d = r.semantic_receipt(root, None, None, roots=["agents/mean_reversion_agent.py"])["dirty"]
    assert "backend/data/x.json" in d and "backend/trading/pf2.py" in d and "backend/trading/portfolio.py" in d
    assert "outside.txt" not in d


def test_versions_skipped_when_no_runtime(tmp_path):
    """Retrospective (Task 4 review fix round 1)."""
    root = repo(tmp_path)
    assert r.semantic_receipt(root, None, None, roots=["agents/mean_reversion_agent.py"])["versions"] == {
        "skipped": True}


def test_process_identity_errors_never_empty(monkeypatch):
    """Retrospective (Task 4 review fix round 1)."""
    class P:
        def __init__(self, rc, out):
            self.returncode, self.stdout = rc, out

    monkeypatch.setattr(r.subprocess, "run", lambda *a, **k: P(1, ""))
    assert r.process_identity() == {"error": "exit 1"}
    def boom(*a, **k):
        raise FileNotFoundError()
    monkeypatch.setattr(r.subprocess, "run", boom)
    assert r.process_identity() == {"error": "FileNotFoundError"}
    monkeypatch.setattr(r.subprocess, "run", lambda *a, **k: P(0, "{}"))
    assert r.process_identity() == {}
    monkeypatch.setattr(r.subprocess, "run", lambda *a, **k: P(0, '{"pid":5,"process_start":"t"}'))
    assert r.process_identity() == {"pid": 5, "process_start": "t"}


def test_crash_log_rewrite_detected(tmp_path):
    """Retrospective (Task 4 review fix round 1)."""
    log = tmp_path / "crash.log"
    log.write_text("2026-10-12 23:17:37 [PROCESS START] pid=1\n")
    o1 = {"pid": 1, "process_start": "s", "record": r.restart_record(log)}
    size = o1["record"]["size"]
    log.write_text("2026-10-12 23:17:37 [PROCESS START] pid=7\n")           # same size, different bytes
    o2 = {"pid": 1, "process_start": "s", "record": r.restart_record(log, prev_size=size)}
    assert any("rewritten" in g for g in r.restart_gaps(o1, o2))
    log.write_text("garbage garbage garbage garbage garbage garbage garbage\n" * 3)   # rewrite ending larger
    o3 = {"pid": 1, "process_start": "s", "record": r.restart_record(log, prev_size=size)}
    assert any("rewritten" in g for g in r.restart_gaps(o1, o3))
    log.write_text("2026-10-12 23:17:37 [PROCESS START] pid=1\nmore\n")     # append: no gap
    o4 = {"pid": 1, "process_start": "s", "record": r.restart_record(log, prev_size=size)}
    assert r.restart_gaps(o1, o4) == []


# ---------------- fix round 2 ----------------
CLASS_CFG = ("import os\nclass Config:\n    USED: float = float(os.getenv('MR_CLS_USED', '1'))\n"
             "    UNUSED = os.getenv('MR_CLS_UNUSED', '1')\n    SECRETISH = os.getenv('X_API_KEY')\n"
             "config = Config()\n")


def test_class_style_config_keys(tmp_path):
    """Retrospective (Task 4 review fix round 2)."""
    root = _cfg_repo(tmp_path, "import config\nx = config.config.USED\nfrom config import config as cfg\ny = cfg.USED\n",
                     CLASS_CFG)
    env = tmp_path / ".env"
    env.write_text("MR_CLS_USED=1\nMR_CLS_UNUSED=1\nX_API_KEY=sekrit77\n")
    a = r.semantic_receipt(root, env, None, roots=["agents/mean_reversion_agent.py"])
    assert set(a["config"]) == {"MR_CLS_USED"} and "sekrit77" not in str(a)
    env.write_text("MR_CLS_USED=2\nMR_CLS_UNUSED=1\n")
    assert r.semantic_receipt(root, env, None, roots=["agents/mean_reversion_agent.py"]) != a
    env.write_text("MR_CLS_USED=1\nMR_CLS_UNUSED=5\n")
    assert r.semantic_receipt(root, env, None, roots=["agents/mean_reversion_agent.py"]) == a


def test_real_backend_mr_keys_include_max_position_size():
    """Retrospective (Task 4 review fix round 2). Read-only; key names only, no .env read, no values."""
    be = Path("C:/Users/gl450/trading_app-s1/backend")
    if not (be / "config.py").exists():
        pytest.skip("real backend worktree not present (trading_app-s1/backend)")
    rels = r.closure(be, r.MR_ROOTS)
    assert "MAX_POSITION_SIZE" in r._mr_config_keys(be, rels)
