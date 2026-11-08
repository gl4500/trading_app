"""Addendum 3 rev 5 F1 (finalization graph to the score; INVALID never numeric; post-stop prices usable), F4.8 score
row, F4.9 score members and abort, C-a (score bound by PREPARED, no collector manifest), C-e (positive and abort paths
isolated), F7.4/F7.5. Behavioural RED against the Task 13 stub (s1_evidence/a3/t13_red.txt). Synthetic connected
lifecycles through the real commands; spies."""
import json
from datetime import timedelta
from pathlib import Path

import pytest
import s1_common as c
import s1_journal as j
import s1_run as r
import s1_seal as z
import s1_stage as sg
import s1_trial as t
from conftest import Spies, _Clock, s1_ack, s1_jappend, s1_state

START = "2026-10-26T13:30:00+00:00"
SNAP = r"the SCORE-ACK-bound final snapshot is missing or changed: INVALID \(registration-artifact\)"   # (OQ-16)
RECEIPT_RE = (r"stage opening: .*bound input opening_receipt\.json missing or changed since the INTENT.*INVALID "
              r"\(stage-replaced\)")                                    # (row 281 [receipt]: the gate's F4 table)


def mb(root):
    return Path(root) / "mailbox.sqlite3"


def jrows(root):
    """(Deviation, as test_s1_a3_final.jrows: read without the open-trial refusal - a malformed ACK chain makes
    open_trial refuse, and the oracle must still read the rows.)"""
    trs = t.trials(t.scan(mb(root)))
    (tid,) = [x for x, tr_ in trs.items() if tr_.closed is None]
    return j.read_trial(tid, trs[tid].genesis, mb(root))


def staged(root, name):
    """The score stage's staging file `name` (Deviation: asserted present, not a FileNotFoundError)."""
    p = sg.staging_dir(root, t.open_trial(mb(root)).trial_id, "score") / name
    assert p.is_file(), f"no score staging {name}"
    return json.loads(p.read_bytes())


def scored(tmp_path, **kw):
    st_ = s1_state(tmp_path, START, score_ready=True, **kw)
    with _Clock(st_["now"]):
        rep = r.score(tmp_path, "score-ack")
    return st_, rep


def test_lot_count_stop_reaches_a_numeric_score_with_no_invalid_row(tmp_path):
    st_, rep = scored(tmp_path)
    rows = jrows(tmp_path)
    assert json.loads((tmp_path / "s1_out" / "stop.json").read_text(encoding="utf-8"))["rule"] == "lots"
    assert rep["verdict"] in ("SHADOW PASS", "FAIL") and all(x.kind != "TRIAL-INVALID" for x in rows)
    stages = [x.subject for x in rows if x.kind == "STAGE-CREATED" and not x.subject.startswith("stage/seal/")]
    assert any(x.kind == "STAGE-CREATED" and x.subject.startswith("stage/seal/") for x in rows)   # (E2.1 r3 seals)
    assert stages == ["stage/audit", "stage/opening", "stage/start_attest", "stage/prereg", "stage/stop_attest",
                      "stage/final_plan", "stage/final", "stage/score"]
    tr = t.open_trial(mb(tmp_path))
    assert not t.check_journal(tr, rows) and set(tr.acks) == {"S1-OPENING-ACK", "S1-RUN-ACK", "S1-PREREG-ACK",
                                                              "S1-ACQUIRE-ACK", "S1-SCORE-ACK"}


def test_six_month_stop_reaches_a_numeric_score_with_no_invalid_row(tmp_path):
    lots = [{"symbol": f"S{i % 5}", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (1, 80.0)} for i in range(40)]
    st_, rep = scored(tmp_path, lots=lots)
    assert json.loads((tmp_path / "s1_out" / "stop.json").read_text(encoding="utf-8"))["rule"] == "timeout"
    assert rep["verdict"] in ("SHADOW PASS", "FAIL", "INSUFFICIENT", "INCONCLUSIVE")
    assert rep["verdict"] != "ABORTED-INVALID" and all(x.kind != "TRIAL-INVALID" for x in jrows(tmp_path))


def test_score_positive_path_isolated(tmp_path):
    """C-e positive: evidence s1_evidence/a3/t13_score_positive.txt (run alone)."""
    st_, rep = scored(tmp_path)
    cm = staged(tmp_path, "prepared.json")
    assert set(cm["members"]) == {"score/attempt.json", "score/s1.json"} and cm["provenance"] == []
    assert cm["members"]["score/s1.json"] == c.sha256_file(tmp_path / "s1_out" / "score" / "s1.json")
    assert not (tmp_path / "s1_out" / "score" / "manifest.json").exists()             # C-a: no collector manifest


def test_score_computation_error_is_invalid_score_aborted_with_no_numeric_score(tmp_path, monkeypatch):
    """C-e failure: evidence s1_evidence/a3/t13_score_aborted.txt (run alone)."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    monkeypatch.setattr(r, "_score", lambda out, mailbox=None: (_ for _ in ()).throw(RuntimeError("boom")))
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=r"INVALID \(score-aborted\)"):
        r.score(tmp_path, "score-ack")
    tr = t.open_trial(mb(tmp_path))
    staging = sg.staging_dir(tmp_path, tr.trial_id, "score")
    aborted = json.loads((staging / "score" / "s1.json").read_text(encoding="utf-8"))
    assert aborted["verdict"] == "ABORTED-INVALID" and not (staging / "prepared.json").exists()
    assert not (tmp_path / "s1_out" / "score").exists()
    assert jrows(tmp_path)[-1].subject == "reason/score-aborted"


def test_invalid_never_reaches_a_numeric_score(tmp_path, monkeypatch):
    st_ = s1_state(tmp_path, START, score_ready=True)
    s1_jappend(tmp_path, "TRIAL-INVALID", "reason/registration-artifact", at=st_["now"] - timedelta(hours=1),
               detail=j.detail_of({"synthetic": "violation"}))
    sp = Spies(monkeypatch)
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=r"trial INVALID \(reason/registration-artifact\): no "
                                                             r"work"):                    # (fix round 1, M-3)
        r.score(tmp_path, "score-ack")
    assert sp.n["valuation"] == 0 and not (tmp_path / "s1_out" / "score").exists()


def test_score_envelope_inputs_and_members(tmp_path):
    st_, rep = scored(tmp_path)
    tr = t.open_trial(mb(tmp_path))
    e = staged(tmp_path, "intent.json")
    assert set(e["inputs"]) == {"final/manifest.json", "attest_stop.json", "sampled_history"}
    assert e["acks"] == {"S1-SCORE-ACK": tr.acks["S1-SCORE-ACK"].sha}
    out, rows = tmp_path / "s1_out", jrows(tmp_path)                     # (fix round 1, M-4: the values)
    stop = j.first(rows, "TRIAL-STOP")
    pr = c.load_json(out / "prereg.json")
    want = j.detail_of(z.sampled_history(rows, stop, z.sampled_seals(out, rows, pr["calendar"], c.aware(pr["start"]),
                                                                      upto_seq=stop.seq)))
    assert e["inputs"]["sampled_history"] == want
    assert e["inputs"]["final/manifest.json"] == c.sha256_file(out / "final" / "manifest.json")
    assert e["inputs"]["attest_stop.json"] == c.sha256_file(out / "attest_stop.json")


@pytest.mark.parametrize("case", ["ok", "wrong-final", "wrong-prev", "wrong-stop-line", "head-forked"])
def test_score_ack_fields_are_verified(tmp_path, case):
    st_ = s1_state(tmp_path, START, score_ready=True, score_ack=False)
    over = {"wrong-final": {"final_manifest_sha256": "0" * 64},
            "wrong-prev": {"prev": t.open_trial(mb(tmp_path)).audit.mailbox_id},
            "wrong-stop-line": {"stop_line_sha256": "0" * 64}, "head-forked": {"journal_head_sha256": "f" * 64}
            }.get(case, {})
    s1_ack(tmp_path, "score-ack", "S1-SCORE-ACK", st_["now"] - timedelta(hours=1), **over)
    with _Clock(st_["now"]):
        if case == "ok":
            assert r.score(tmp_path, "score-ack")["verdict"]
            return
        with pytest.raises(SystemExit, match=ACK_REFUSAL[case]):
            r.score(tmp_path, "score-ack")
    assert j.subject_rows(jrows(tmp_path), "stage/score") == []


ACK_REFUSAL = {"wrong-final": r"S1-SCORE-ACK score-ack: \['final_manifest_sha256'\] differ from the current artifacts",
               "wrong-prev": r"S1-SCORE-ACK score-ack: prev '[^']+' is not the S1-ACQUIRE-ACK 'acq-ack' \(F7\.1\)",
               "wrong-stop-line": r"stop_line_sha256 is not the TRIAL-STOP line",
               "head-forked": r"journal head at seq \d+ differs \(fork\)"}


def test_score_member_changed_is_invalid(tmp_path, monkeypatch):
    st_, rep = scored(tmp_path)
    p = tmp_path / "s1_out" / "score" / "s1.json"
    p.write_bytes(p.read_bytes() + b" ")
    sp = Spies(monkeypatch)
    with pytest.raises(SystemExit, match=r"INVALID \(stage-replaced\)"):
        t.gate(tmp_path, "after the score")
    sp.assert_zero()


@pytest.mark.parametrize("victim", ["receipt", "snapshot-report"])
def test_damaged_receipt_or_final_snapshot_is_invalid_before_scoring(tmp_path, monkeypatch, victim):   # row 281
    st_ = s1_state(tmp_path, START, score_ready=True)
    p = tmp_path / "s1_out" / ("opening_receipt.json" if victim == "receipt" else "final_snapshot/report.json")
    p.write_bytes(p.read_bytes() + b" ")                                  # the TEST damages its tmp file
    sp = Spies(monkeypatch)
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=ROW_281[victim]):           # (fix round 1, M-3)
        r.score(tmp_path, "score-ack")
    sp.assert_zero()
    assert not (tmp_path / "s1_out" / "score").exists()


ROW_281 = {"receipt": RECEIPT_RE,
           "snapshot-report": SNAP}


def test_damaged_capture_backup_is_invalid_before_scoring(tmp_path, monkeypatch):     # row 282 (E5.6)
    st_ = s1_state(tmp_path, START, score_ready=True)
    backup = sorted((tmp_path / "s1_out" / "captures").glob("*/*/backup.sqlite3"))[-1]
    with open(backup, "ab") as f:
        f.write(b"\0")
    sp = Spies(monkeypatch)
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=r"INVALID \(registration-artifact\)"):
        r.score(tmp_path, "score-ack")
    sp.assert_zero()


def test_score_integrity_violation_persists_trial_invalid(tmp_path, monkeypatch):     # row 306 (OQ-28)
    st_ = s1_state(tmp_path, START, score_ready=True)
    monkeypatch.setattr(r, "_score", lambda out, mailbox=None: {"trial_id": "x", "outcome": "ABORTED",
                                                                "verdict": "ABORTED-INVALID",
                                                                "reasons": ["fence violation in seal X"]})
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=r"stage score: INVALID \(registration-artifact\)"):
        r.score(tmp_path, "score-ack")
    inv = [x for x in jrows(tmp_path) if x.kind == "TRIAL-INVALID"]
    assert len(inv) == 1 and inv[0].subject == "reason/registration-artifact"
    rec = json.loads((tmp_path / "s1_out" / "invalid" / f"{inv[0].seq}.json").read_bytes())   # (fix round 1, I-1:
    assert rec == {"where": "score", "score_reasons": ["fence violation in seal X"], "stage": "score",   # OQ-28 "with
                   "reason": "registration-artifact"} and inv[0].detail == j.detail_of(rec)          # the reasons")
    staging = sg.staging_dir(tmp_path, t.open_trial(mb(tmp_path)).trial_id, "score")
    assert (staging / "score" / "s1.json").exists() and not (staging / "prepared.json").exists()
    assert not (tmp_path / "s1_out" / "score").exists()


@pytest.mark.parametrize("verdict", ["INSUFFICIENT", "INCONCLUSIVE"])
def test_non_integrity_dispositions_stay_valid(tmp_path, monkeypatch, verdict):        # row 307 (ctrl)
    st_ = s1_state(tmp_path, START, score_ready=True)
    real = r._score
    monkeypatch.setattr(r, "_score", lambda out, mailbox=None: dict(real(out, mailbox), verdict=verdict))
    with _Clock(st_["now"]):
        rep = r.score(tmp_path, "score-ack")
    assert rep["verdict"] == verdict and all(x.kind != "TRIAL-INVALID" for x in jrows(tmp_path))


@pytest.mark.parametrize("case", ["missing", "changed"])
def test_final_snapshot_missing_or_changed_is_invalid_not_a_fallback(tmp_path, monkeypatch, case):   # row 314
    st_ = s1_state(tmp_path, START, score_ready=True)
    p = tmp_path / "s1_out" / "final_snapshot" / "report.json"
    if case == "missing":
        p.unlink()
    else:
        p.write_bytes(p.read_bytes() + b" ")
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=SNAP):                     # (fix round 1, M-3)
        r.score(tmp_path, "score-ack")
    assert [x.subject for x in jrows(tmp_path) if x.kind == "TRIAL-INVALID"] == ["reason/registration-artifact"]
    assert not (tmp_path / "s1_out" / "score" / "s1.json").exists()


def test_final_snapshot_only_in_stopped(tmp_path, monkeypatch):                       # row 314 (OQ-16)
    import s1_checkpoint as ck
    st_ = s1_state(tmp_path, START)                                     # ACTIVE: registered, no STOP
    sp = Spies(monkeypatch)
    n = len(jrows(tmp_path))
    with _Clock(st_["prereg_at"]), pytest.raises(SystemExit, match=r"final snapshot refused: the trial is not "
                                                                   r"STOPPED \(OQ-16\)"):   # (fix round 1, M-3)
        ck.run_final_snapshot(tmp_path, st_["ledger"].path, now=lambda: st_["prereg_at"],
                              mailbox=tmp_path / "mailbox.sqlite3")
    sp.assert_zero()
    assert len(jrows(tmp_path)) == n and not (tmp_path / "s1_out" / "final_snapshot").exists()


def test_sampled_history_is_canonical_and_fixed_at_the_stop(tmp_path, monkeypatch):   # row 315 (OQ-29)
    st_ = s1_state(tmp_path, START, score_ready=True, final=False)
    out = tmp_path / "s1_out"
    rows0 = jrows(tmp_path)
    stop = j.first(rows0, "TRIAL-STOP")
    pr = c.load_json(out / "prereg.json")
    seals = z.sampled_seals(out, rows0, pr["calendar"], c.aware(pr["start"]), upto_seq=stop.seq)
    before = z.sampled_history(rows0, stop, seals)
    import s1_collect as k                  # (Deviation: a real post-stop row - the final plan stage; F1 refuses a
    with _Clock(st_["stop_attested_at"] + timedelta(hours=1)):   # post-STOP SLOT-INTENT, LOST-RACE)
        k.write_final_plan(tmp_path)
    rows1 = jrows(tmp_path)
    assert len(rows1) > len(rows0) and all(x.seq > stop.seq for x in rows1[len(rows0):])
    after = z.sampled_history(rows1, stop, z.sampled_seals(out, rows1, pr["calendar"], c.aware(pr["start"]),
                                                            upto_seq=stop.seq))
    assert set(before) == {"rows", "seals"}, before                     # (Deviation: assert, not KeyError)
    assert before == after and list(before["seals"]) == sorted(before["seals"])
    assert before["rows"] == [x.sha for x in rows0 if x.seq <= stop.seq]


def test_authorized_post_stop_prices_are_used_for_valuation(tmp_path):
    seen = []
    st_, rep = scored(tmp_path, bar_fn=lambda sym, d: seen.append(d) or {"date": d, "o": 100, "h": 101, "l": 99,
                                                                          "c": 100})
    stop_day = c.aware(json.loads((tmp_path / "s1_out" / "stop.json").read_text(encoding="utf-8"))["stop_close"]
                       ).astimezone(c.NY).date().isoformat()
    assert stop_day in seen and rep["verdict"] in ("SHADOW PASS", "FAIL")


# ---------------------------------------------------------------- A3 Task 13 carry-forwards (implementer's own tests)
def _stage_kinds(root):
    return [x.kind for x in j.subject_rows(jrows(root), "stage/score")]


def test_local_oserror_in_the_score_refuses_with_no_row_never_score_aborted(tmp_path, monkeypatch):
    """Carry-forward 2 (Task 12 ruling): a local OSError during the score computation is no score anomaly: refused
    with no row (no ABORTED record, no TRIAL-INVALID); the F4 stage table decides on re-entry (stage-incomplete)."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    monkeypatch.setattr(r, "_score", lambda out, mailbox=None: (_ for _ in ()).throw(PermissionError("locked")))
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=r"stage score: local I/O error after the INTENT "
                                                             r"\(PermissionError\): refused with no row"):
        r.score(tmp_path, "score-ack")
    staging = sg.staging_dir(tmp_path, t.open_trial(mb(tmp_path)).trial_id, "score")
    assert _stage_kinds(tmp_path) == ["STAGE-INTENT"]
    assert all(x.kind != "TRIAL-INVALID" for x in jrows(tmp_path))
    assert not (staging / "ABORTED.json").exists() and not (staging / "score" / "s1.json").exists()
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=r"INVALID \(stage-incomplete\)"):
        r.score(tmp_path, "score-ack")


def test_journal_outage_in_the_score_refuses_with_no_row_never_score_aborted(tmp_path, monkeypatch):
    """Carry-forward 2: a journal read failure inside the computation is a local fault too, not score-aborted."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    monkeypatch.setattr(r, "_score", lambda out, mailbox=None: (_ for _ in ()).throw(j.Outage("busy")))
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=r"score: journal or mailbox unreadable during the "
                                                             r"computation \(Outage\): refused with no PREPARED"):
        r.score(tmp_path, "score-ack")
    staging = sg.staging_dir(tmp_path, t.open_trial(mb(tmp_path)).trial_id, "score")
    assert _stage_kinds(tmp_path) == ["STAGE-INTENT"] and all(x.kind != "TRIAL-INVALID" for x in jrows(tmp_path))
    assert not (staging / "ABORTED.json").exists()


def test_unconfirmed_integrity_verdict_refuses_with_no_invalid(tmp_path, monkeypatch):
    """N1 confirm-on-re-read before an INVALID: an ABORTED-INVALID verdict that does not repeat on a second
    computation (a transient read) commits no TRIAL-INVALID and no score."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    real, calls = r._score, []

    def flaky(out, mailbox=None):
        calls.append(1)
        if len(calls) == 1:
            return {"trial_id": "x", "outcome": "ABORTED", "verdict": "ABORTED-INVALID", "reasons": ["transient"]}
        return real(out, mailbox)
    monkeypatch.setattr(r, "_score", flaky)
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=r"did not repeat on a second computation .*the first "
                                                             r"computation's report is kept in the score staging "
                                                             r"\(first_computation_s1\.json\)"):
        r.score(tmp_path, "score-ack")
    assert len(calls) == 2 and all(x.kind != "TRIAL-INVALID" for x in jrows(tmp_path))
    assert _stage_kinds(tmp_path) == ["STAGE-INTENT"] and not (tmp_path / "s1_out" / "score").exists()
    first = json.loads((sg.staging_dir(tmp_path, t.open_trial(mb(tmp_path)).trial_id, "score")      # (fix round 1,
                        / "first_computation_s1.json").read_bytes())                                # M-1: evidence)
    assert first["verdict"] == "ABORTED-INVALID" and first["reasons"] == ["transient"]


def test_second_computation_error_after_an_integrity_verdict_keeps_the_first_reasons(tmp_path, monkeypatch):
    """Fix round 1, M-1: an ABORTED-INVALID verdict whose confirming computation raises ends INVALID (score-aborted);
    the first computation's integrity reasons are kept in the observation and in the score staging."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    calls = []

    def first_then_boom(out, mailbox=None):
        calls.append(1)
        if len(calls) == 1:
            return {"trial_id": "x", "outcome": "ABORTED", "verdict": "ABORTED-INVALID", "reasons": ["seal fence"]}
        raise RuntimeError("boom")
    monkeypatch.setattr(r, "_score", first_then_boom)
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=r"stage score: INVALID \(score-aborted\)"):
        r.score(tmp_path, "score-ack")
    inv = [x for x in jrows(tmp_path) if x.kind == "TRIAL-INVALID"]
    assert [x.subject for x in inv] == ["reason/score-aborted"]
    rec = json.loads((tmp_path / "s1_out" / "invalid" / f"{inv[0].seq}.json").read_bytes())
    assert rec == {"error_type": "RuntimeError", "first_verdict_reasons": ["seal fence"], "stage": "score",
                   "reason": "score-aborted"} and inv[0].detail == j.detail_of(rec)
    d = sg.staging_dir(tmp_path, t.open_trial(mb(tmp_path)).trial_id, "score")
    assert json.loads((d / "first_computation_s1.json").read_bytes())["reasons"] == ["seal fence"]
    assert json.loads((d / "score" / "s1.json").read_bytes())["verdict"] == "ABORTED-INVALID"
    assert not (d / "prepared.json").exists() and not (tmp_path / "s1_out" / "score").exists()


@pytest.mark.parametrize("err", [ValueError("bad seal"), PermissionError("locked"), KeyError("calendar")],
                         ids=["ValueError", "PermissionError", "KeyError"])
def test_pre_intent_sampled_history_error_is_a_refusal_not_a_traceback(tmp_path, monkeypatch, err):
    """Fix round 1, M-7 (F0.7): an error building the envelope inputs (before the score INTENT) refuses with a reason;
    no row, no staging, nothing written."""
    st_ = s1_state(tmp_path, START, score_ready=True)

    def bad(*a, **kw):
        raise err
    monkeypatch.setattr(z, "sampled_seals", bad)
    n = len(jrows(tmp_path))
    with _Clock(st_["now"]), pytest.raises(BaseException, match=rf"score refused: sampled history unreadable "
                                                                rf"\({type(err).__name__}\): nothing written") as ei:
        r.score(tmp_path, "score-ack")
    assert type(ei.value) is SystemExit
    assert len(jrows(tmp_path)) == n and _stage_kinds(tmp_path) == []
    assert not sg.staging_dir(tmp_path, t.open_trial(mb(tmp_path)).trial_id, "score").exists()
    assert not (tmp_path / "s1_out" / "score").exists()


def test_aborted_record_write_error_still_records_the_anomaly_reason(tmp_path, monkeypatch):
    """Carry-forward 3 (Task 12 N-1): a local OSError writing ABORTED.json in the StageAbort branch never loses the
    anomaly's reason: TRIAL-INVALID (score-aborted) is still appended, its observation saying the record is
    unwritten."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    monkeypatch.setattr(r, "_score", lambda out, mailbox=None: (_ for _ in ()).throw(RuntimeError("boom")))
    real_put = sg._Staging.put

    def put(self, rel, data):
        if rel == "ABORTED.json":
            raise PermissionError("staging locked")
        return real_put(self, rel, data)
    monkeypatch.setattr(sg._Staging, "put", put)
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=r"stage score: INVALID \(score-aborted\)"):
        r.score(tmp_path, "score-ack")
    inv = [x for x in jrows(tmp_path) if x.kind == "TRIAL-INVALID"]
    assert len(inv) == 1 and inv[0].subject == "reason/score-aborted"
    rec = json.loads((tmp_path / "s1_out" / "invalid" / f"{inv[0].seq}.json").read_bytes())
    assert rec == {"error_type": "RuntimeError", "stage": "score", "reason": "score-aborted",
                   "aborted_record": "unwritten (PermissionError)"} and inv[0].detail == j.detail_of(rec)
    staging = sg.staging_dir(tmp_path, t.open_trial(mb(tmp_path)).trial_id, "score")
    assert not (staging / "ABORTED.json").exists() and not (tmp_path / "s1_out" / "score").exists()


@pytest.mark.parametrize("case", ["differs-once", "unreadable"])
def test_bound_snapshot_is_confirmed_on_a_second_read_before_any_invalid(tmp_path, monkeypatch, case):
    """N1 (OQ-16 check): a final-snapshot hash that differs from the SCORE-ACK on the first read only (differs-once)
    or cannot be read again (unreadable) refuses with no row - never INVALID."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    real_af, real_sha, armed = t.artifact_fields, c.sha256_file, []

    def af(kind, out):
        got = real_af(kind, out)
        if kind == "S1-SCORE-ACK":
            armed.append(1)
            got = dict(got, final_snapshot_sha256="0" * 64)          # the first read differs
        return got

    def sha(p):
        if armed and case == "unreadable" and Path(p).name == "report.json":
            raise PermissionError("locked")
        return real_sha(p)
    monkeypatch.setattr(t, "artifact_fields", af)
    monkeypatch.setattr(c, "sha256_file", sha)
    want = (r"read differently on a second read \(transient\?\): refused with no row" if case == "differs-once" else
            r"the final-snapshot report is unreadable \(PermissionError\): refused with no row")
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=want):
        r.score(tmp_path, "score-ack")
    assert armed and all(x.kind != "TRIAL-INVALID" for x in jrows(tmp_path)) and _stage_kinds(tmp_path) == []


def test_score_ack_binding_no_snapshot_with_a_report_on_disk_is_a_refusal(tmp_path, monkeypatch):
    """OQ-16 scope: only a BOUND report is evidence. A SCORE-ACK issued with final_snapshot_sha256 "absent" while a
    report now exists differs from the current artifacts: refused (as any other ACK field), never INVALID."""
    st_ = s1_state(tmp_path, START, score_ready=True, score_ack=False)
    s1_ack(tmp_path, "score-ack", "S1-SCORE-ACK", st_["now"] - timedelta(hours=1), final_snapshot_sha256="absent")
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=r"\['final_snapshot_sha256'\] differ from the current "
                                                             r"artifacts"):
        r.score(tmp_path, "score-ack")
    assert all(x.kind != "TRIAL-INVALID" for x in jrows(tmp_path)) and _stage_kinds(tmp_path) == []
