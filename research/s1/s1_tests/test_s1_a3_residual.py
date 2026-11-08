"""Addendum 3 rev 5 F8.1 / F10 CH4: the accepted uncommitted-detection residual (labelled lost detection, not
equivalence) and its limit (a committed INVALID keeps the same restoration invalid)."""
import shutil
from datetime import timedelta  # noqa: F401 (brief literal)

import pytest
import s1_common as c  # noqa: F401 (brief literal)
import s1_journal as j
import s1_trial as t
from conftest import Spies, s1_state

START = "2026-10-26T13:30:00+00:00"


def _invalid_rows(root):
    trs = t.trials(t.scan(root / "mailbox.sqlite3"))
    return [x for tid, tr in trs.items() for x in j.read_trial(tid, tr.genesis, root / "mailbox.sqlite3")
            if x.kind == "TRIAL-INVALID"]


def test_uncommitted_detection_may_resume_and_is_labelled_lost_detection(tmp_path, monkeypatch):
    """The violation is observed while the journal cannot be written; the INVALID never commits; committed bytes are
    restored and the local witnesses deleted; the restart may resume. This is the F8.1 residual - LOST DETECTION, NOT
    EQUIVALENCE - recorded in s1_evidence/a3/t14_residual.txt; no guarantee is claimed for it."""
    s1_state(tmp_path, START)
    out = tmp_path / "s1_out"
    p = out / "attest_start.json"
    keep = p.read_bytes()
    p.write_bytes(keep + b" ")
    real = j.append
    monkeypatch.setattr(j, "append", lambda *a, **kw: (_ for _ in ()).throw(j.Outage("journal down")))
    # A3 H1 (intended, Erratum 2 r4 G6.3): the refusal now states truthfully that the local abort was published
    with pytest.raises(SystemExit, match=r"violation \(stage-replaced\) observed but the journal could not be written "
                                         r"\(Outage\): refused; local abort published; F8\.1 residual \(lost detection "
                                         r"if it never commits\)"):
        t.gate(tmp_path, "observer during an outage")
    assert _invalid_rows(tmp_path) == []                           # the INVALID never committed (the residual)
    assert (out / "aborted.json").is_file()                        # (the local witness the refusal reports)
    monkeypatch.setattr(j, "append", real)
    p.write_bytes(keep)
    for w in ("aborted.json", "refusals.jsonl"):
        (out / w).unlink(missing_ok=True)
    shutil.rmtree(out / "invalid", ignore_errors=True)
    gv = t.gate(tmp_path, "restart")
    assert gv.state == "ACTIVE"                                    # resumed: lost detection, not equivalence


def test_invalid_committed_before_the_crash_keeps_restoration_invalid(tmp_path, monkeypatch):
    s1_state(tmp_path, START)
    out = tmp_path / "s1_out"
    p = out / "attest_start.json"
    keep = p.read_bytes()
    p.write_bytes(keep + b" ")
    with pytest.raises(SystemExit, match=r"stage start_attest: .*INVALID \(stage-replaced\)"):
        t.gate(tmp_path, "observer")
    assert [x.subject for x in _invalid_rows(tmp_path)] == ["reason/stage-replaced"]
    p.write_bytes(keep)
    for w in ("aborted.json", "refusals.jsonl"):
        (out / w).unlink(missing_ok=True)
    shutil.rmtree(out / "invalid", ignore_errors=True)
    sp = Spies(monkeypatch)
    with pytest.raises(SystemExit, match=r"trial INVALID \(reason/stage-replaced\): no work"):
        t.gate(tmp_path, "restart")
    sp.assert_zero()
