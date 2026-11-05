"""Addendum 3 rev 5 F10 'Codex probes': the new tests for the frozen historical probes (copies and hashes in
s1_evidence/a3/codex_probes_historical/, never collected). Old -> new map: plan 'Codex probe old -> new map' and
s1_evidence/a3/codex_probes_old_new.md. Synthetic journal fixtures; tmp mailboxes; spies."""
import json
import os
import shutil
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
import s1_common as c
import s1_run as r
import s1_trial as t
from conftest import S1_RECEIPT, Spies, _Clock, s1_jappend, s1_state  # noqa: F401 (s1_jappend: Task 7 appends, P41)

START = "2026-10-26T13:30:00+00:00"
HIST = Path(__file__).resolve().parent.parent / "s1_evidence" / "a3" / "codex_probes_historical"
FROZEN = {"test_codex_publication.py": "3c81f41fc08ff171881e62c5bddc1dc27e16aaa9b23c033a95a2f172c240b2b9",
          "test_codex_registration.py": "98ec8af58edd8d7535f4cc9689c3cff99e35e15f356d8500457c2d155f0b055e",
          "test_codex_combined_damage.py": "418a9594f2b9c7a3716a2f8e663c20a9494f268e43bae7220fbfce0645fd53c1"}


def test_historical_probe_copies_are_frozen():
    for name, sha in FROZEN.items():
        assert c.sha256_file(HIST / name) == sha
    sums = dict(reversed(line.split(" *", 1)) if " *" in line else reversed(line.split("  ", 1))
                for line in (HIST / "SHA256SUMS").read_text(encoding="utf-8").splitlines() if line.strip())
    assert all(c.sha256_file(HIST / n) == h for n, h in sums.items()) and len(sums) >= 12
    assert set(sums) == {p.name for p in HIST.iterdir() if p.name != "SHA256SUMS"}       # nothing unlisted
    assert json.loads((HIST / "bundle-bootstrap-missing.json").read_text(encoding="utf-8"))["restoration_resumes"]


def test_historical_probe_copies_are_never_collected(tmp_path):
    """The frozen copies are evidence: a pytest run over their folder (with the suite's `-p conftest`) collects
    nothing. The child only collects (no fixture or test body runs, so it opens no mailbox, ledger or network)."""
    here = Path(__file__).resolve().parent
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(here.parent), str(here)]))
    p = subprocess.run([sys.executable, "-m", "pytest", "-p", "conftest", "-p", "no:cacheprovider", "--collect-only",
                        "-q", str(HIST)], capture_output=True, text=True, env=env, cwd=str(tmp_path), timeout=120)
    assert p.returncode == 5 and "no tests collected" in p.stdout, (p.returncode, p.stdout[-800:], p.stderr[-800:])


@pytest.mark.parametrize("auth_damage", ["missing", "unparseable"])
def test_combined_damage_is_invalid_bundle_after_any_journal_row(tmp_path, monkeypatch, auth_damage):
    state = s1_state(tmp_path, START)
    with _Clock(state["prereg_at"]):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    out = tmp_path / "s1_out"
    copy = tmp_path / "bundle-copy"
    for rel in (*c.BUNDLE_CODE, *c.DOC_PINS):
        (copy / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(c.HERE / rel, copy / rel)
    monkeypatch.setattr(c, "HERE", copy)
    code = copy / "s1_checkpoint.py"
    saved_code = code.read_bytes()
    code.write_bytes(saved_code + b"\n# synthetic observed bundle change\n")
    damaged = [out / "prereg.json", out / "audit" / "manifest.json"]
    saved = {p: p.read_bytes() for p in damaged}
    for p in damaged:
        if auth_damage == "missing":
            p.unlink()
        else:
            p.write_text("{not JSON", encoding="utf-8")
    sp = Spies(monkeypatch)
    at = state["start"] - timedelta(hours=1)
    with _Clock(at), pytest.raises(t.Refusal, match=r"INVALID \(bundle\)"):
        t.gate(tmp_path, "Codex combined-damage probe")
    assert c.load_abort(out)["reason"] == "bundle"
    for p, b in saved.items():
        p.write_bytes(b)
    code.write_bytes(saved_code)
    (out / "aborted.json").unlink()
    with _Clock(at + timedelta(minutes=1)), pytest.raises(t.Refusal, match=r"trial INVALID \(reason/bundle\)"):
        t.gate(tmp_path, "Codex restored probe")
    sp.assert_zero()
