"""Task 12 (controller-added): final-review R-6 and Addendum A1.2/A9.3 reporting. Written BEFORE the code (RED:
s1_evidence/t12_R6_red.txt). Report-only: none of this changes a verdict."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import s1_checkpoint as ck
import s1_common as c
import s1_run as r
from conftest import S1_PROCESS, S1_RECEIPT, _Clock, s1_mailbox, s1_reack, s1_receipt_with, s1_state

UTC = timezone.utc
START = "2026-10-26T13:30:00+00:00"


import pytest  # noqa: E402  (A3 Task 6: the held marker)


@pytest.mark.skip(reason="HELD with Task 11 (A3 Task 6, F1/OQ-25): the fixture's synthetic TRIAL-STOP precedes these "
                         "checkpoints, so they are LOST-RACE with no capture (and a late invocation is now refused with "
                         "no row, F0.5 step 6); the R-6/A9.3 listings need a refused capture and a binding gap "
                         "committed BEFORE the STOP - Task 11's real TRIAL-STOP flow")
def test_r6_refused_captures_provenance_changes_and_observation_gaps_are_listed_in_the_score(tmp_path, monkeypatch):
    """R-6: captures refused (here a late clock refusal) are listed explicitly in the score report; A1.2: the
    receipt PROVENANCE observed at each seal (HEAD changes) is reported; A9.3: process-observation gaps (here an
    unobserved binding) are reported as observation gaps - never a verdict change."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    sch = datetime(2026, 10, 28, 20, 45, tzinfo=UTC)
    with _Clock(sch + timedelta(minutes=30)):
        ck.run_checkpoint(tmp_path, st_["ledger"].path, sch, lambda: S1_RECEIPT, lambda: dict(S1_PROCESS),
                          tmp_path / "crash.log", now=lambda: sch + timedelta(minutes=30))
    # (fix round 2 migration, Addendum 2 B2.4: S1_PROCESS now observes the binding; the gap is an explicitly
    # unavailable binding, observed by a later checkpoint)
    sch2 = datetime(2026, 10, 29, 20, 45, tzinfo=UTC)
    with _Clock(sch2 + timedelta(seconds=30)):
        ck.run_checkpoint(tmp_path, st_["ledger"].path, sch2, lambda: S1_RECEIPT,
                          lambda: {"pid": None, "binding": {"unavailable": "nothing listening"}},
                          tmp_path / "crash.log", now=lambda: sch2 + timedelta(seconds=30))
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    s1_reack(tmp_path, "score-ack-2", "S1-SCORE-ACK", st_["now"] - timedelta(minutes=30))
    rep = r.score(tmp_path, "score-ack-2")
    assert rep["verdict"] == "SHADOW PASS"
    assert any(x["scheduled"] == sch.isoformat() and "clock" in x["refused"] for x in rep["refused_captures"])
    assert rep["receipt_provenance"]["heads"] == ["h"]
    # (corrected before the final run: binding gaps are reported as rep["binding_gaps"], keeping rep["restarts"]
    # exactly as test_s1_connected pins it)
    assert any("binding not observed" in g["gap"] for g in rep["binding_gaps"])
