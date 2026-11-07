"""Task 12 (controller-added): final-review R-6 and Addendum A1.2/A9.3 reporting. Written BEFORE the code (RED:
s1_evidence/t12_R6_red.txt). Report-only: none of this changes a verdict."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import s1_checkpoint as ck
import s1_common as c
import s1_journal as j
import s1_run as r
import s1_trial as t
from conftest import S1_PROCESS, S1_RECEIPT, _Clock, s1_finish, s1_mailbox, s1_reack, s1_receipt_with, s1_state

UTC = timezone.utc
START = "2026-10-26T13:30:00+00:00"


def test_r6_refused_captures_provenance_changes_and_observation_gaps_are_listed_in_the_score(tmp_path, monkeypatch):
    """R-6: captures refused (here a clock refusal) are listed explicitly in the score report; A1.2: the receipt
    PROVENANCE observed at each seal (HEAD changes) is reported; A9.3: process-observation gaps (here an unobserved
    binding) are reported as observation gaps - never a verdict change.
    A3 Task 11 (un-held; F1/OQ-25, F2): both captures are committed BEFORE the real TRIAL-STOP. The trial is built
    with the post-START seal of 2026-10-26 only (s1_state(stop=False)); on the 2026-10-27 close an early invocation
    of slot 20:45 at 20:44 is refused by the clock (t < s: SLOT-FAILED, OQ-33), and slot 20:47 captures with an
    unavailable binding (SLOT-QUALIFIED) - that checkpoint's decide_stop commits the lots STOP at 2026-10-27; the
    post-stop chain (stop attestation, final plan and attempt, ACKs, snapshot) then follows (conftest.s1_finish).
    (The old flow - checkpoints after the fixture's synthetic STOP - is LOST-RACE with no capture since A3 Task 6.)"""
    st_ = s1_state(tmp_path, START, score_ready=True, stop=False, seal_days=[0])
    out = tmp_path / "s1_out"
    sch = datetime(2026, 10, 27, 20, 45, tzinfo=UTC)
    early = sch - timedelta(minutes=1)
    with _Clock(early):
        ck.run_checkpoint(tmp_path, st_["ledger"].path, sch, lambda: S1_RECEIPT, lambda: dict(S1_PROCESS),
                          tmp_path / "crash.log", now=lambda: early)
    # (fix round 2 migration, Addendum 2 B2.4: S1_PROCESS now observes the binding; the gap is an explicitly
    # unavailable binding)
    sch2 = datetime(2026, 10, 27, 20, 47, tzinfo=UTC)
    with _Clock(sch2 + timedelta(seconds=30)):
        ck.run_checkpoint(tmp_path, st_["ledger"].path, sch2, lambda: S1_RECEIPT,
                          lambda: {"pid": None, "binding": {"unavailable": "nothing listening"}},
                          tmp_path / "crash.log", now=lambda: sch2 + timedelta(seconds=30))
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    rows = j.read_trial(tr.trial_id, tr.genesis, tmp_path / "mailbox.sqlite3")
    stop = j.first(rows, "TRIAL-STOP")
    assert stop is not None and stop.seq > max(x.seq for x in rows if x.subject in
                                               (j.slot_subject(sch), j.slot_subject(sch2)))
    info = s1_finish(tmp_path, st_, sch2 + timedelta(hours=1))
    monkeypatch.setattr(c, "now_utc", lambda: info["now"])
    rep = r.score(tmp_path, "score-ack")
    assert rep["verdict"] == "SHADOW PASS"
    assert any(x["scheduled"] == sch.isoformat() and "clock" in x["refused"] for x in rep["refused_captures"])
    assert rep["receipt_provenance"]["heads"] == ["h"]
    # (corrected before the final run: binding gaps are reported as rep["binding_gaps"], keeping rep["restarts"]
    # exactly as test_s1_connected pins it)
    assert any("binding not observed" in g["gap"] for g in rep["binding_gaps"])
