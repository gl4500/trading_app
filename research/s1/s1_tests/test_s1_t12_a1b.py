"""Task 12 (controller-added): Addendum 1 rev 3 A1.1 "sanitized launcher/process binding evidence" (second part,
written after test_s1_t12_a1.py but BEFORE its implementation; RED: s1_evidence/t12_A1b_red.txt). The launcher
files are registered resources (test_s1_t12_a1.py); this file covers the observed process binding: the listening
backend's executable and SANITIZED command line, compared whenever observed (a difference is an observed change =
ABORTED-INVALID before the stop), an unobserved binding being a reported gap only (A9.3). Synthetic only."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import s1_checkpoint as ck
import s1_receipt as rc
import s1_run as r
from conftest import s1_prereg_at  # A3 Task 10 (fixture instant)
from conftest import s1_prereg_ack  # A3 Task 6
from conftest import S1_BINDING, S1_RECEIPT, _Clock, s1_state

UTC = timezone.utc
START = "2026-10-26T13:30:00+00:00"
START_DT = datetime(2026, 10, 26, 13, 30, tzinfo=UTC)
CMD = r'"C:\app\runtime\python\python.exe" main.py --port 8000 --api-key=SECRETKEY123 --token SECRETTOK456'


def test_a1b_command_line_is_sanitized_secret_values_masked():
    """A1.1: sanitized = every value of a secret-named option masked; everything else kept."""
    s = rc.sanitize_cmdline(CMD)
    assert "SECRETKEY123" not in s and "SECRETTOK456" not in s
    assert "main.py" in s and "--port 8000" in s and "--api-key=" in s


def test_a1b_process_identity_reports_the_binding(monkeypatch):
    """A1.1: the process observation carries the binding: executable path and sanitized command line + its hash."""
    class P:
        returncode = 0
        stdout = json.dumps({"pid": 7, "process_start": "2026-10-26T09:00:00", "exe": r"C:\app\python.exe",
                             "cmdline": CMD})
    monkeypatch.setattr(rc.subprocess, "run", lambda *a, **kw: P())
    got = rc.process_identity()
    assert got["pid"] == 7 and got["binding"]["exe"] == r"C:\app\python.exe"
    assert got["binding"]["cmdline"] == rc.sanitize_cmdline(CMD) and "SECRETKEY123" not in json.dumps(got)
    assert len(got["binding"]["cmdline_sha256"]) == 64


OTHER_CMD = '"D:/other/python.exe" main.py'
OTHER_BINDING = {"exe": "D:/other/python.exe", "cmdline": OTHER_CMD,
                 "cmdline_sha256": __import__("hashlib").sha256(OTHER_CMD.encode("utf-8")).hexdigest()}


def _proc(binding):
    """(fix round 2: a binding dict, or None for an explicitly unavailable one - Addendum 2 B2.4)."""
    p = {"pid": 1, "process_start": "2026-10-01T09:00:00"}
    p["binding"] = dict(binding) if binding is not None else {"unavailable": "nothing listening"}
    return p


def _reg(tmp_path):
    st_ = s1_state(tmp_path, START)
    with _Clock(s1_prereg_at(tmp_path)):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    s1_prereg_ack(tmp_path)                    # A3 Task 6 (F7.4): the PREREG-ACK before captures
    st_["ledger"].trade("A", "BUY", 10, 50.0, "2026-10-26T15:00:00+00:00")
    st_["ledger"].set_portfolio("A", 10)
    return st_


def _cp(tmp_path, st_, proc, minutes=45):
    sch = datetime(2026, 10, 26, 20, 0, tzinfo=UTC) + timedelta(minutes=minutes)
    act = sch + timedelta(seconds=30)
    with _Clock(act):
        return ck.run_checkpoint(tmp_path, st_["ledger"].path, sch, lambda: S1_RECEIPT, lambda: dict(proc),
                                 tmp_path / "crash.log", now=lambda: act)


def test_a1b_the_first_observed_binding_is_the_reference_and_a_change_is_aborted_invalid(tmp_path):
    """A1.1/A1.3 as amended by Addendum 2 B2.1 (fix round 2 REPLACEMENT: the old body asserted the reference sidecar
    s1_out/process_binding.json, which B2.1 removes as an authority): the OPENING's observed binding is the reference
    (its seal records it, prereg binds it); an equal later binding seals; a different one is an observed change
    before the stop -> persistent ABORTED-INVALID."""
    st_ = _reg(tmp_path)
    out = tmp_path / "s1_out"
    rep = _cp(tmp_path, st_, _proc(S1_BINDING))
    assert rep["seal"]["written"] is True and not (out / "process_binding.json").exists()
    ref = json.loads((out / "prereg.json").read_text(encoding="utf-8"))["process_binding"]
    assert ref == S1_BINDING
    st_["ledger"].trade("A", "BUY", 1, 50.0, "2026-10-27T15:00:00+00:00")
    st_["ledger"].set_portfolio("A", 11)
    sch = datetime(2026, 10, 27, 20, 45, tzinfo=UTC)
    with _Clock(sch + timedelta(seconds=30)):
        rep = ck.run_checkpoint(tmp_path, st_["ledger"].path, sch, lambda: S1_RECEIPT,
                                lambda: _proc(OTHER_BINDING), tmp_path / "crash.log",
                                now=lambda: sch + timedelta(seconds=30))
    assert rep["stop"]["status"] == "ABORTED-INVALID" and rep["seal"]["written"] is False
    assert "process binding" in json.dumps(json.loads((out / "aborted.json").read_text(encoding="utf-8")))


def test_a1b_an_unobserved_binding_is_a_reported_gap_never_a_change(tmp_path):
    """A9.3 as amended by Addendum 2 B2.4 (fix round 2 REPLACEMENT: the gap must be represented explicitly - an
    observation simply lacking a binding is now MALFORMED, a lookup failure an A9.1 failure): an explicitly
    unavailable binding is a gap: reported, the capture still seals, no abort."""
    st_ = _reg(tmp_path)
    _cp(tmp_path, st_, _proc(S1_BINDING))
    st_["ledger"].trade("A", "BUY", 1, 50.0, "2026-10-27T15:00:00+00:00")
    st_["ledger"].set_portfolio("A", 11)
    sch = datetime(2026, 10, 27, 20, 45, tzinfo=UTC)
    with _Clock(sch + timedelta(seconds=30)):
        rep = ck.run_checkpoint(tmp_path, st_["ledger"].path, sch, lambda: S1_RECEIPT, lambda: _proc(None),
                                tmp_path / "crash.log", now=lambda: sch + timedelta(seconds=30))
    assert rep["seal"]["written"] is True and not (tmp_path / "s1_out" / "aborted.json").exists()
    # (corrected before GREEN: the binding gap is reported under observation_gaps, keeping restart_gaps' meaning)
    assert any("binding not observed" in g for g in rep.get("observation_gaps", [])), rep
