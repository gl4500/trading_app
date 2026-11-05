"""Task 12 (controller-added): Addendum 1 rev 3 section A1 (semantic receipt scope: validity fingerprint vs
informational provenance; registered resource list and evidence contract; keyed HMAC secret fingerprints; missing
REQUIRED input fails explicitly). Written BEFORE the implementation (RED: s1_evidence/t12_A1_red.txt).
Synthetic git repos under tmp_path only; the HMAC key file is a tmp file (conftest redirect); no live checkout."""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import s1_checkpoint as ck
import s1_common as c
import s1_receipt as rc
import s1_run as r
from conftest import s1_prereg_ack  # A3 Task 6
from conftest import S1_PROCESS, S1_RECEIPT, _Clock, s1_receipt_with, s1_state

UTC = timezone.utc
START = "2026-10-26T13:30:00+00:00"
START_DT = datetime(2026, 10, 26, 13, 30, tzinfo=UTC)
ROOTS = ["agents/mean_reversion_agent.py"]


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def commit(root, msg="x"):
    git(root, "add", "-A")
    git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", msg)


def repo(tmp_path):
    root = tmp_path / "repo"
    be = root / "backend"
    (be / "agents").mkdir(parents=True)
    (be / "agents" / "mean_reversion_agent.py").write_text(
        "from agents.base_agent import B\nimport config\nZ = config.MR_SELL_ZSCORE\nK = config.ALPACA_API_KEY\n"
        "H = config.HOST\n")
    (be / "agents" / "base_agent.py").write_text("from trading.portfolio import P\nimport numpy\n")
    (be / "trading").mkdir()
    (be / "trading" / "portfolio.py").write_text("X = 1\n")
    (be / "config.py").write_text("import os\nMR_SELL_ZSCORE = float(os.getenv('MR_SELL_ZSCORE', '1.5'))\n"
                                  "ALPACA_API_KEY = os.getenv('ALPACA_API_KEY')\nHOST = os.getenv('HOST', 'x')\n"
                                  "OTHER = os.getenv('FRED_API_KEY')\n")
    (root / "start_backend.ps1").write_text("$env:PYTHONPATH = 'site-packages'\n")
    (root / "frontend").mkdir()
    (root / "frontend" / "app.js").write_text("1\n")
    (root / ".gitignore").write_text(".env\n")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    commit(root)
    (root / ".env").write_text("MR_SELL_ZSCORE=1.5\nALPACA_API_KEY=AKSECRET123\nHOST=127.0.0.1\n"
                               "FRED_API_KEY=fred999\n")
    return root


def contract(**kw):
    """A reviewed test contract: the registered runtime is not part of these synthetic repos."""
    return rc.contract(runtime_required=False, **kw)


def rec(root, **kw):
    kw.setdefault("contract", contract())
    return rc.semantic_receipt(root, root / ".env", None, roots=ROOTS, **kw)


# ====================================================================== A1.1 / A1.2 fingerprint vs provenance
def test_a1_receipt_separates_the_compared_fingerprint_from_informational_provenance(tmp_path):
    """A1.1/A1.2: {"fingerprint": closure (membership + sha256), registered resources, effective-config evidence,
    runtime, the evidence contract's hash and the HMAC key id} vs {"provenance": HEAD, dirty list, transient files,
    transport-only settings}."""
    root = repo(tmp_path)
    a = rec(root)
    assert set(a) == {"fingerprint", "provenance"}
    fp, pv = a["fingerprint"], a["provenance"]
    assert set(fp) >= {"closure", "resources", "config", "runtime", "contract_sha256", "key_id"}
    assert set(fp["closure"]) == {"agents/base_agent.py", "agents/mean_reversion_agent.py", "config.py",
                                  "trading/portfolio.py"}
    assert set(pv) >= {"head", "dirty", "transient", "transport"} and len(pv["head"]) == 40
    assert "HOST" in pv["transport"] and "HOST" not in json.dumps(fp)          # transport/observation only


def test_a1_the_evidence_contract_is_one_named_reviewable_structure():
    """A1.1: the registered resource list and evidence contract are explicit data in code (one named structure),
    its hash bound in every fingerprint."""
    ec = rc.EVIDENCE_CONTRACT
    assert set(ec) >= {"closure_roots", "resources", "config", "runtime", "secret_pattern", "transport_only_keys"}
    assert ec["closure_roots"] == rc.MR_ROOTS and ec["config"]["env_required"] is True
    assert ec["runtime"]["required"] is True and ec["runtime"]["python"] == "runtime/python/python.exe"
    assert {x["path"] for x in ec["resources"]} >= {"start_backend.ps1"}
    assert ec["transport_only_keys"] == ["HOST", "PORT"]
    assert rc.contract() == ec and rc.contract(runtime_required=False)["runtime"]["required"] is False


def test_a1_an_unrelated_commit_or_checkout_does_not_change_the_fingerprint(tmp_path):
    """A1.3 / Q0: an unrelated commit (frontend) or a branch checkout changes HEAD (provenance), never validity."""
    root = repo(tmp_path)
    a = rec(root)
    (root / "frontend" / "app.js").write_text("2\n")
    commit(root, "unrelated")
    git(root, "checkout", "-q", "-b", "other-branch")
    b = rec(root)
    assert b["fingerprint"] == a["fingerprint"] and b["provenance"]["head"] != a["provenance"]["head"]


def test_a1_sqlite_sidecars_logs_and_caches_appearing_or_disappearing_are_provenance_only(tmp_path):
    """A1.2 / Q3: SQLite -journal/-wal/-shm, logs and runtime caches are transient: recorded, never compared."""
    root = repo(tmp_path)
    a = rec(root)
    be = root / "backend"
    for n in ("trading.db-journal", "trading.db-wal", "trading.db-shm", "app.log"):
        (be / n).write_text("t")
    (be / "__pycache__").mkdir()
    (be / "__pycache__" / "x.cpython-312.pyc").write_bytes(b"\0")
    b = rec(root)
    assert b["fingerprint"] == a["fingerprint"]
    assert "backend/trading.db-journal" in b["provenance"]["transient"]
    for n in ("trading.db-journal", "trading.db-wal", "trading.db-shm", "app.log"):
        (be / n).unlink()
    assert rec(root)["fingerprint"] == a["fingerprint"]


def test_a1_a_relevant_non_python_resource_is_bound_by_presence_and_hash_independent_of_git(tmp_path):
    """A1.1 / Q3: a registered MR-relevant resource of any file type (here the launcher) is bound by
    presence/absence and sha256, tracked or not; a change, removal or (re)appearance changes the fingerprint."""
    root = repo(tmp_path)
    a = rec(root)
    assert a["fingerprint"]["resources"]["start_backend.ps1"] == c.sha256_file(root / "start_backend.ps1")
    (root / "start_backend.ps1").write_text("$env:PYTHONPATH = 'elsewhere'\n")
    assert rec(root)["fingerprint"] != a["fingerprint"]
    (root / "start_backend.ps1").unlink()
    b = rec(root)
    assert b["fingerprint"]["resources"]["start_backend.ps1"] == "absent" and b["fingerprint"] != a["fingerprint"]
    git(root, "rm", "-q", "--cached", "start_backend.ps1")                      # untracked from now on
    (root / "start_backend.ps1").write_text("$env:PYTHONPATH = 'site-packages'\n")
    assert rec(root)["fingerprint"] == a["fingerprint"]                        # same bytes, untracked: same


def test_a1_a_registered_required_resource_that_is_missing_fails_explicitly(tmp_path):
    """A1.1: a resource the contract marks REQUIRED that is missing fails explicitly (never a silent fallback)."""
    root = repo(tmp_path)
    ct = contract(resources=[{"path": "start_backend.ps1", "role": "launcher", "required": True}])
    assert rec(root, contract=ct)["fingerprint"]["resources"]["start_backend.ps1"] != "absent"
    (root / "start_backend.ps1").unlink()
    with pytest.raises(rc.ReceiptError, match="start_backend.ps1"):
        rec(root, contract=ct)


def test_a1_a_new_closure_member_changes_the_fingerprint_and_a_missing_member_fails(tmp_path):
    """A1.1: the complete closure - membership AND sha256; a new member is a different fingerprint (a mismatch),
    a missing in-repo member or root is a receipt FAILURE, never a silently shorter list."""
    root = repo(tmp_path)
    a = rec(root)
    be = root / "backend"
    (be / "trading" / "risk.py").write_text("R = 1\n")
    (be / "trading" / "portfolio.py").write_text("from trading import risk\nX = 1\n")
    b = rec(root)
    assert "trading/risk.py" in b["fingerprint"]["closure"] and b["fingerprint"] != a["fingerprint"]
    (be / "trading" / "risk.py").unlink()
    with pytest.raises(rc.ReceiptError, match="risk"):
        rec(root)
    with pytest.raises((rc.ReceiptError, ValueError), match="root"):
        rc.semantic_receipt(root, root / ".env", None, roots=["agents/missing_agent.py"], contract=contract())


# ====================================================================== A1.1 effective config, secrets, HMAC key
def test_a1_secret_named_fields_are_bound_by_name_presence_and_keyed_hmac_never_raw(tmp_path):
    """A1.1: an MR-relevant secret-named field is bound by field name, presence and an HMAC-SHA256 under the key
    file stored outside s1_out and the repo; a changed secret value changes the fingerprint; the raw value never
    appears; a non-MR secret (FRED_API_KEY) is not bound at all."""
    root = repo(tmp_path)
    a = rec(root)
    sec = a["fingerprint"]["config"]["secrets"]
    assert set(sec) == {"ALPACA_API_KEY"} and sec["ALPACA_API_KEY"]["present"] is True
    assert len(sec["ALPACA_API_KEY"]["hmac"]) == 64
    assert "AKSECRET123" not in json.dumps(a) and "fred999" not in json.dumps(a) and "FRED_API_KEY" not in json.dumps(a)
    (root / ".env").write_text("MR_SELL_ZSCORE=1.5\nALPACA_API_KEY=AKSECRET999\nHOST=127.0.0.1\n")
    b = rec(root)
    assert b["fingerprint"] != a["fingerprint"] and "AKSECRET999" not in json.dumps(b)
    (root / ".env").write_text("MR_SELL_ZSCORE=1.5\nHOST=127.0.0.1\n")
    assert rec(root)["fingerprint"]["config"]["secrets"]["ALPACA_API_KEY"] == {"present": False, "hmac": None}


def test_a1_the_hmac_key_is_created_once_outside_s1_out_and_its_identity_is_bound(tmp_path):
    """A1.1: the key file is created once (os.urandom) when absent; its identity (key-id hash) is in the
    fingerprint, so key loss or rotation shows as a change, never as unchanged values. The registered location
    is the coordination folder, outside s1_out and the repo."""
    key = rc.HMAC_KEY                                                  # conftest: <tmp_path>/s1_receipt_hmac.key
    assert not key.exists()
    root = repo(tmp_path)
    a = rec(root)
    assert key.exists() and len(key.read_bytes()) >= 32
    first = key.read_bytes()
    assert rec(root)["fingerprint"] == a["fingerprint"] and key.read_bytes() == first      # created once
    assert a["fingerprint"]["config"]["key_id"] == rc.key_id(first)
    key.unlink()                                                       # loss -> a new key: a visible change
    b = rec(root)
    assert b["fingerprint"]["config"]["key_id"] != a["fingerprint"]["config"]["key_id"] and b["fingerprint"] != \
        a["fingerprint"]
    import ast
    tree = ast.parse((Path(rc.__file__)).read_text(encoding="utf-8"))
    vals = [ast.unparse(n.value) for n in ast.walk(tree) if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "HMAC_KEY" for t in n.targets)]
    assert vals == ["Path('C:/Users/gl450/.coordination/trading_app/s1_receipt_hmac.key')"]


def test_a1_a_missing_required_env_fails_explicitly_and_an_optional_one_is_recorded_absent(tmp_path):
    """A1.1 / mapping probe j: the registered contract marks .env REQUIRED, so a missing .env fails explicitly - no
    silent fallback to an empty value set. A reviewed alternate arrangement (env not required) records it as
    absent; values then come from the code defaults (config.py, a closure member)."""
    root = repo(tmp_path)
    (root / ".env").unlink()
    with pytest.raises(rc.ReceiptError, match=r"\.env"):
        rec(root)
    alt = rec(root, contract=contract(env_required=False))
    assert alt["fingerprint"]["config"]["env"] == "absent"
    assert alt["fingerprint"]["config"]["values"]["MR_SELL_ZSCORE"] == rc.UNSET_MARK


def test_a1_a_missing_required_runtime_fails_explicitly(tmp_path):
    """A1.1: the backend's registered runtime is REQUIRED by the registered contract: no runtime -> failure, never
    {"skipped": true}."""
    root = repo(tmp_path)
    with pytest.raises(rc.ReceiptError, match="runtime"):
        rc.semantic_receipt(root, root / ".env", None, roots=ROOTS)
    with pytest.raises(rc.ReceiptError, match="runtime"):
        rc.semantic_receipt(root, root / ".env", root / "runtime" / "python" / "python.exe", roots=ROOTS)


def test_a1_the_runtime_binds_python_and_the_backends_site_packages(tmp_path):
    """A1.1: the registered runtime = Python version and the installed package versions OF THE BACKEND RUNTIME,
    including the launcher's PYTHONPATH site-packages (the backend's effective packages)."""
    root = repo(tmp_path)
    sp = root / "site-packages" / "fakepkg-1.2.3.dist-info"
    sp.mkdir(parents=True)
    (sp / "METADATA").write_text("Metadata-Version: 2.1\nName: fakepkg\nVersion: 1.2.3\n")
    a = rc.semantic_receipt(root, root / ".env", Path(sys.executable), roots=ROOTS, contract=rc.contract())
    rt = a["fingerprint"]["runtime"]
    assert rt["python"] == sys.version.split()[0] and rt["packages"].get("fakepkg") == "1.2.3"
    (sp / "METADATA").write_text("Metadata-Version: 2.1\nName: fakepkg\nVersion: 1.2.4\n")
    b = rc.semantic_receipt(root, root / ".env", Path(sys.executable), roots=ROOTS, contract=rc.contract())
    assert b["fingerprint"] != a["fingerprint"]


def test_a1_receipt_errors_carry_no_secret_text(tmp_path):
    """A1.1/A9.1: a receipt failure names the missing input, never a secret value."""
    root = repo(tmp_path)
    (root / "start_backend.ps1").unlink()
    ct = contract(resources=[{"path": "start_backend.ps1", "role": "launcher", "required": True}])
    with pytest.raises(rc.ReceiptError) as e:
        rec(root, contract=ct)
    assert "AKSECRET123" not in str(e.value)


# ====================================================================== A1.3 consequences at the checkpoint
def _reg(tmp_path):
    st_ = s1_state(tmp_path, START)
    with _Clock(START_DT - timedelta(days=1)):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    s1_prereg_ack(tmp_path)                    # A3 Task 6 (F7.4): the PREREG-ACK before captures
    st_["ledger"].trade("A", "BUY", 10, 50.0, "2026-10-26T15:00:00+00:00")
    st_["ledger"].set_portfolio("A", 10)
    return st_


def _cp(tmp_path, st_, receipt, minutes=45):
    sch = datetime(2026, 10, 26, 20, 0, tzinfo=UTC) + timedelta(minutes=minutes)
    act = sch + timedelta(seconds=30)
    with _Clock(act):
        return ck.run_checkpoint(tmp_path, st_["ledger"].path, sch, lambda: receipt, lambda: dict(S1_PROCESS),
                                 tmp_path / "crash.log", now=lambda: act)


def test_a1_a_head_or_dirty_change_alone_seals_and_is_recorded_as_provenance(tmp_path):
    """A1.2/A1.3: a receipt whose provenance differs (an unrelated commit) but whose fingerprint is the registered
    one matches: the seal is written and records the observed provenance."""
    st_ = _reg(tmp_path)
    moved = s1_receipt_with(S1_RECEIPT, head="unrelated-commit")
    rep = _cp(tmp_path, st_, moved)
    assert rep["receipt_match"] is True and rep["seal"]["written"] is True
    seal = json.loads((tmp_path / "s1_out" / "seals" / "2026-10-26.json").read_text())
    assert seal["receipt_provenance"]["head"] == "unrelated-commit"
    assert seal["receipt_sha256"] == c.receipt_sha256(S1_RECEIPT)
    assert not (tmp_path / "s1_out" / "aborted.json").exists()


def test_a1_a_fingerprint_change_between_the_opening_seal_and_the_stop_is_aborted_invalid(tmp_path):
    """A1.3: any fingerprint change before the stop -> ABORTED-INVALID (persistent)."""
    st_ = _reg(tmp_path)
    rep = _cp(tmp_path, st_, s1_receipt_with(S1_RECEIPT, files={"agents/mean_reversion_agent.py": "2"}))
    assert rep["receipt_match"] is False and rep["stop"]["status"] == "ABORTED-INVALID"
    assert json.loads((tmp_path / "s1_out" / "aborted.json").read_text())["reason"] == "semantic receipt changed"


def test_a1_a_receipt_without_a_fingerprint_never_matches(tmp_path):
    """A1.1 / A9.2: missing required evidence never becomes a plausible match (no fingerprint -> no seal)."""
    st_ = _reg(tmp_path)
    rep = _cp(tmp_path, st_, {"provenance": {"head": "h"}})
    assert rep["receipt_match"] is not True and rep["seal"]["written"] is False
