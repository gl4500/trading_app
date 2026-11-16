"""Prospective isolated pending-branch oracle; dependency-slot substitution is explicit."""
from datetime import timedelta

import s1_journal as j
import s1_seal as z
import s1_slot as sl
import s1_trial as t
from conftest import s1_state, s1_jappend

START = "2026-10-26T13:30:00+00:00"


def test_t15d_f11_pending_branch_precedes_dependency_consumption(tmp_path, monkeypatch):
    state = s1_state(tmp_path, START, score_ready=True, seal_days=[1], stop_attest=False, final=False, stop=False)
    day = state["sessions"][0]
    slot = z.close_of(day, state["calendar"]) + timedelta(minutes=45)
    s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(slot), at=slot + timedelta(seconds=1))
    gv = t.gate(tmp_path, "t15d pending branch")
    real_close_state, real_resolution = z._close_state, sl._resolution_evidence
    pending, resolutions = [], []

    def isolate_pending_dependencies(*args, **kwargs):
        result = real_close_state(*args, **kwargs)
        if result[0] == "pending":
            pending.append(result)
            return result[0], [], result[2]
        return result

    def committed_qualified_only(out, q, day_iso, *, ps=None):
        resolutions.append(q)
        assert q is not None and q.kind == "SLOT-QUALIFIED", "pending branch consumed as QUALIFIED"  # ORACLE:F11-UNIT
        return real_resolution(out, q, day_iso, ps=ps)

    monkeypatch.setattr(z, "_close_state", isolate_pending_dependencies)
    monkeypatch.setattr(sl, "_resolution_evidence", committed_qualified_only)
    observed = z.stop_record(gv.out, gv.rows, state["start"], state["calendar"], gv.trial.bundle)
    assert pending and all(result == ("pending", None, None) for result in pending)
    assert observed is None and resolutions == []
    fresh = j.read_trial(gv.trial.trial_id, gv.trial.genesis, tmp_path / "mailbox.sqlite3")
    assert j.first(fresh, "TRIAL-STOP") is None
