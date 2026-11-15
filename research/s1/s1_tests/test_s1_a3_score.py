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


# ---------------------------------------------------------------- A3 H5c item 1 (T13 N-1): pre-INTENT QualifiedEvidence
QE_MISSING, QE_DIFFERS = "missing-or-unreadable", "differs-from-detail"    # H5c-FIX: the F3 kinds (pinned values)
QE_ABSENT, QE_UNPARSEABLE, QE_SHAPE = "typed-absence", "unparseable", "required-shape"   # A1 categories (pinned)
COMMIT = "c" * 64                                                          # a synthetic committed tree detail


def _qe(msg, subject="slot/x", kind=QE_DIFFERS, category=None, member=None, commitment=COMMIT):
    """H5c-FIX (X-16; A1/A2): a QualifiedEvidence carrying a VALID structured identity as the s1_slot raise sites set
    it (QE_DIFFERS: subject + commitment; QE_MISSING: subject + category + member). The attributes are set after
    construction (so this helper builds the same object on the base); the product's identity validation still
    applies to them (A2: no positive control bypasses it)."""
    import s1_slot
    e = s1_slot.QualifiedEvidence(msg)
    e.subject, e.kind, e.category, e.member = subject, kind, category, member
    e.commitment = commitment if kind == QE_DIFFERS else None
    return e


def _label(e) -> str:
    """The refusal text's rendering of an identity (the oracle's own copy: '<subject> [<kind>, ...]')."""
    rest = [e.kind, e.category, e.member] if e.kind == QE_MISSING else [e.kind, e.commitment]
    return f"{e.subject} [{', '.join(rest)}]"


def test_pre_intent_qualified_evidence_is_invalid_when_confirmed(tmp_path, monkeypatch):     # T13 N-1
    """A QualifiedEvidence raised by the score's pre-INTENT sampled-history computation (a race past the gate's F3
    table) is the F3 signal: confirmed on a recomputation over re-read rows, it is TRIAL-INVALID
    (registration-artifact) - never 'sampled history unreadable'."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    calls = []

    def bad(*a, **kw):
        calls.append(a[1])
        raise _qe("slot/x: QUALIFIED tree differs from the committed detail (F3)")
    monkeypatch.setattr(z, "sampled_seals", bad)
    n = len(jrows(tmp_path))
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=r"^score: slot evidence violation \['slot/x: QUALIFIED "
                                                             r"tree differs from the committed detail \(F3\)'\]: "
                                                             r"INVALID \(registration-artifact\)$"):
        r.score(tmp_path, "score-ack")
    rows = jrows(tmp_path)
    assert len(calls) == 2 and calls[0] is not calls[1]                   # the recomputation is over RE-READ rows
    assert [x.subject for x in rows[n:]] == ["reason/registration-artifact"]
    assert j.subject_rows(rows, "stage/score") == [] and _stage_kinds(tmp_path) == []
    assert not (tmp_path / "s1_out" / "score").exists()
    ab = json.loads((tmp_path / "s1_out" / "aborted.json").read_text(encoding="utf-8"))    # H5d (H5c verdict f7): the
    assert ab["reason"] == c.REGISTRATION_ARTIFACT and ab["where"] == "score", ab           # local abort is published
    assert ab["problems"] == ["slot/x: QUALIFIED tree differs from the committed detail (F3)"], ab


def test_pre_intent_qualified_evidence_unconfirmed_refuses_with_no_row(tmp_path, monkeypatch):   # T13 N-1
    st_ = s1_state(tmp_path, START, score_ready=True)
    real, n = z.sampled_seals, [0]

    def once(*a, **kw):
        n[0] += 1
        if n[0] == 1:
            raise _qe("transient (simulated)")
        return real(*a, **kw)
    monkeypatch.setattr(z, "sampled_seals", once)
    before = len(jrows(tmp_path))
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=r"^score refused: a QUALIFIED tree problem was not "
                                                             r"confirmed on a re-read: refused with no row$"):
        r.score(tmp_path, "score-ack")
    assert n[0] == 2 and len(jrows(tmp_path)) == before and _stage_kinds(tmp_path) == []


@pytest.mark.parametrize("err", ["oserror-recompute", "journal-reread"])
def test_pre_intent_qualified_evidence_reread_failure_refuses_with_no_row(tmp_path, monkeypatch, err):   # T13 N-1
    """I-4: an OSError (or a journal read failure) on the confirming re-read refuses with no row - never INVALID."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    n = [0]

    def seals(*a, **kw):
        n[0] += 1
        if n[0] == 1:
            raise _qe("slot/x: a file of its QUALIFIED tree is missing")
        raise PermissionError("locked")
    monkeypatch.setattr(z, "sampled_seals", seals)
    before = len(jrows(tmp_path))
    if err == "journal-reread":
        real_read, fired = j.read_trial, []

        def read(*a, **kw):
            if n[0] == 1 and not fired:                                   # the confirming re-read only
                fired.append(1)
                raise j.Outage("mailbox locked (simulated)")
            return real_read(*a, **kw)
        monkeypatch.setattr(j, "read_trial", read)
    want = {"oserror-recompute": r"PermissionError", "journal-reread": r"Outage"}[err]
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=rf"^score refused: a QUALIFIED tree problem could not be "
                                                             rf"re-read \({want}\): refused with no row \(I-4\)$"):
        r.score(tmp_path, "score-ack")
    assert n[0] == (2 if err == "oserror-recompute" else 1)
    assert len(jrows(tmp_path)) == before and _stage_kinds(tmp_path) == []


# ---------------------------------------------------------------- A3 H5c-FIX (Codex X-16 / H5C-CX-1; A1-A3): observations
NOT_SAME = (r"^score refused: a QUALIFIED tree problem was not confirmed on a re-read \(first {a}; re-read {b}\): "
            r"refused with no row$")
CAL_REFUSAL = (r"^score refused: the registered calendar is unreadable or differs from the command's in the confirming "
               r"pass: refused with no row \(G3\.1, fail closed\)$")
BUNDLE_REFUSAL = (r"^score refused: the S1 bundle differs from the trial's AUDIT-ACK bundle in the confirming pass: "
                  r"refused with no row \(ruling OP-14\)$")
INVALID_RE = r"^score: slot evidence violation \[.*\]: INVALID \(registration-artifact\)$"
D1, D2 = "slot/20261026T204500Z", "slot/20261027T204500Z"
DIFF_TEXT = "{}: QUALIFIED tree differs from the committed detail (F3)"
MISS_TEXT = "{}: a file of its QUALIFIED tree is missing or unreadable ({})"
M1 = "captures/2026-10-26/20261026T204500Z.resolution.json"


def _not_same(e1, e2) -> str:
    import re
    lab = (lambda e: "unidentified" if e is None else re.escape(_label(e)))
    return NOT_SAME.format(a=lab(e1), b=lab(e2))


def _diff(subject, commitment=COMMIT):
    return _qe(DIFF_TEXT.format(subject), subject, QE_DIFFERS, commitment=commitment)


def _miss(subject, category=QE_ABSENT, member=M1, err="FileNotFoundError"):
    return _qe(MISS_TEXT.format(subject, err), subject, QE_MISSING, category=category, member=member)


def _two_observations(monkeypatch, first, second, after_first=None):
    """sampled_seals raises `first` then `second` (each a QualifiedEvidence or None = clean); `after_first` runs
    after the first observation (it flips the confirming-pass environment)."""
    calls = []

    def seals(*a, **kw):
        calls.append(a[1])
        e = first if len(calls) == 1 else second
        if len(calls) == 1 and after_first is not None:
            after_first()
        if e is not None:
            raise e
        return {}
    monkeypatch.setattr(z, "sampled_seals", seals)
    return calls


def _score_refused_no_row(tmp_path, st_, match):
    before = len(jrows(tmp_path))
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=match):
        r.score(tmp_path, "score-ack")
    new = [(x.kind, x.subject) for x in jrows(tmp_path)[before:]]
    assert new == [], new
    assert _stage_kinds(tmp_path) == [] and not (tmp_path / "s1_out" / "aborted.json").exists()


def _score_invalid(tmp_path, st_, problems=None):
    before = len(jrows(tmp_path))
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=INVALID_RE):
        r.score(tmp_path, "score-ack")
    assert [x.subject for x in jrows(tmp_path)[before:]] == ["reason/registration-artifact"]
    ab = json.loads((tmp_path / "s1_out" / "aborted.json").read_text(encoding="utf-8"))
    assert ab["reason"] == c.REGISTRATION_ARTIFACT and ab["where"] == "score", ab
    if problems is not None:
        assert ab["problems"] == problems, ab


def test_h5cfix_different_slots_do_not_confirm_each_other(tmp_path, monkeypatch):       # X-16 (Codex's regression)
    st_ = s1_state(tmp_path, START, score_ready=True)
    a, b = _diff(D1), _diff(D2)
    calls = _two_observations(monkeypatch, a, b)
    _score_refused_no_row(tmp_path, st_, _not_same(a, b))
    assert len(calls) == 2


@pytest.mark.parametrize("order", ["missing-then-differs", "differs-then-missing"])
def test_h5cfix_same_slot_changed_kind_does_not_confirm(tmp_path, monkeypatch, order):  # X-16 (changed problem)
    st_ = s1_state(tmp_path, START, score_ready=True)
    a, b = _miss(D1), _diff(D1)
    if order == "differs-then-missing":
        a, b = b, a
    calls = _two_observations(monkeypatch, a, b)
    _score_refused_no_row(tmp_path, st_, _not_same(a, b))
    assert len(calls) == 2


@pytest.mark.parametrize("change", ["category", "member", "commitment"])
def test_h5cfix_same_slot_changed_evidence_does_not_confirm(tmp_path, monkeypatch, change):   # A1 (synthetic)
    """Same slot and kind, another category / expected member / committed tree: not the same observation."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    a, b = {"category": (_miss(D1), _miss(D1, QE_UNPARSEABLE, err="JSONDecodeError")),
            "member": (_miss(D1), _miss(D1, member="captures/2026-10-26/20261026T204500Z/meta.json")),
            "commitment": (_diff(D1), _diff(D1, "d" * 64))}[change]
    _two_observations(monkeypatch, a, b)
    _score_refused_no_row(tmp_path, st_, _not_same(a, b))


@pytest.mark.parametrize("kind", [QE_MISSING, QE_DIFFERS])
def test_h5cfix_same_identity_twice_is_invalid(tmp_path, monkeypatch, kind):              # control (passes on base)
    st_ = s1_state(tmp_path, START, score_ready=True)
    mk = {QE_MISSING: _miss, QE_DIFFERS: _diff}[kind]
    calls = _two_observations(monkeypatch, mk(D1), mk(D1))
    _score_invalid(tmp_path, st_, [str(mk(D1))])
    assert len(calls) == 2 and calls[0] is not calls[1]


@pytest.mark.parametrize("bad", ["untagged", "no-subject", "empty-subject", "unknown-kind", "missing-no-category",
                                 "missing-unknown-category", "missing-no-member", "differs-no-commitment"])
def test_h5cfix_a_missing_or_invalid_identity_never_confirms(tmp_path, monkeypatch, bad):    # A2
    """A QualifiedEvidence without a valid structured identity is no confirmable observation: twice the same object
    (the same text, the same attributes) is refused with no row - never None == None."""
    import s1_slot
    st_ = s1_state(tmp_path, START, score_ready=True)
    text = DIFF_TEXT.format(D1)

    def make():
        if bad == "untagged":
            return s1_slot.QualifiedEvidence(text)
        e = _miss(D1) if bad.startswith("missing") else _diff(D1)
        if bad == "no-subject":
            e.subject = None
        elif bad == "empty-subject":
            e.subject = ""
        elif bad == "unknown-kind":
            e.kind = "something-else"
        elif bad == "missing-no-category":
            e.category = None
        elif bad == "missing-unknown-category":
            e.category = "unreadable"
        elif bad == "missing-no-member":
            e.member = ""
        else:
            e.commitment = None
        return e
    calls = _two_observations(monkeypatch, make(), make())
    _score_refused_no_row(tmp_path, st_, _not_same(None, None))
    assert len(calls) == 2


@pytest.mark.parametrize("fresh", ["unreadable", "differs"])
def test_h5cfix_confirming_pass_calendar_is_fresh(tmp_path, monkeypatch, fresh):         # G3.1 (fresh calendar)
    import s1_slot
    st_ = s1_state(tmp_path, START, score_ready=True)
    real, flipped = s1_slot._calendar, []

    def cal(gv):
        got = real(gv)
        if not flipped:
            return got
        return None if fresh == "unreadable" else [dict(d, close="12:00") for d in got]
    monkeypatch.setattr(s1_slot, "_calendar", cal)
    calls = _two_observations(monkeypatch, _diff(D1), _diff(D1), after_first=lambda: flipped.append(1))
    _score_refused_no_row(tmp_path, st_, CAL_REFUSAL)
    assert len(calls) == 1                                                # refused before the confirming recompute


def test_h5cfix_confirming_pass_checks_the_bundle(tmp_path, monkeypatch):                # OP-14 (fresh bundle)
    st_ = s1_state(tmp_path, START, score_ready=True)
    real, flipped = c.bundle_sha256, []
    monkeypatch.setattr(c, "bundle_sha256", lambda *a, **kw: "0" * 64 if flipped else real(*a, **kw))
    calls = _two_observations(monkeypatch, _diff(D1), _diff(D1), after_first=lambda: flipped.append(1))
    _score_refused_no_row(tmp_path, st_, BUNDLE_REFUSAL)
    assert len(calls) == 1


def test_h5cfix_confirming_pass_verifies_the_pin_again(tmp_path, monkeypatch):           # A3 / G3.2 control
    """The pin failing in the confirming pass (after a first observation) refuses with no row (its SystemExit)."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    real, flipped = c.sim, []

    def sim():
        if flipped:
            raise SystemExit("e1_sim.py: missing or hash differs from the pinned (simulated)")
        return real()
    monkeypatch.setattr(c, "sim", sim)
    calls = _two_observations(monkeypatch, _diff(D1), _diff(D1), after_first=lambda: flipped.append(1))
    _score_refused_no_row(tmp_path, st_, r"^e1_sim\.py: missing or hash differs from the pinned \(simulated\)$")
    assert len(calls) == 1


def _sealed(tmp_path):
    """The real sampled seals of the score_ready fixture: [(day, first QUALIFIED row)] in date order."""
    out = tmp_path / "s1_out"
    pr = json.loads((out / "prereg.json").read_text(encoding="utf-8"))
    seals = z.sampled_seals(out, jrows(tmp_path), pr["calendar"], c.aware(pr["start"]))
    return [(d, q) for d, (q, _b) in sorted(seals.items())]


def _paths(out, q, day):
    import s1_slot
    n = s1_slot.names(out, s1_slot.slot_of(q.subject), day)
    return {"resolution": n["resolution"], "report": n["report"], "backup": n["capture"] / "backup.sqlite3",
            "meta": n["capture"] / "meta.json"}


def _rel(out, p) -> str:
    return p.relative_to(out).as_posix()


def _ident(e):
    return tuple(getattr(e, k, None) for k in ("subject", "kind", "category", "member", "commitment"))


def test_h5cfix_raise_site_texts_and_identity_are_pinned(tmp_path, monkeypatch):          # str(e) byte-identical, A1
    import dataclasses
    import s1_slot
    s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    day, q = _sealed(tmp_path)[0]
    p = _paths(out, q, day)
    keep = p["resolution"].read_bytes()
    with pytest.raises(s1_slot.QualifiedEvidence, match=r"QUALIFIED tree differs") as ei:     # differs: the commitment
        s1_slot._resolution_evidence(out, dataclasses.replace(q, detail="0" * 64), day)
    assert str(ei.value) == f"{q.subject}: QUALIFIED tree differs from the committed detail (F3)"
    assert _ident(ei.value) == (q.subject, QE_DIFFERS, None, None, "0" * 64)
    cases = [("backup", None, "FileNotFoundError", QE_ABSENT), ("resolution", None, "FileNotFoundError", QE_ABSENT),
             ("resolution", b"{not json", "JSONDecodeError", QE_UNPARSEABLE),
             ("resolution", b"\xff\xfe", "UnicodeDecodeError", QE_UNPARSEABLE),
             ("resolution", b"{}", "KeyError", QE_SHAPE), ("resolution", b"[]", "TypeError", QE_SHAPE)]
    for member, data, err, cat in cases:
        keep_m = p[member].read_bytes()
        if data is None:
            p[member].unlink()
        else:
            p[member].write_bytes(data)
        with pytest.raises(s1_slot.QualifiedEvidence, match=r"missing or unreadable") as ei:
            s1_slot._resolution_evidence(out, q, day)
        p[member].write_bytes(keep_m)
        assert str(ei.value) == f"{q.subject}: a file of its QUALIFIED tree is missing or unreadable ({err})"
        assert _ident(ei.value) == (q.subject, QE_MISSING, cat, _rel(out, p[member]), None), (member, err)
    assert p["resolution"].read_bytes() == keep
    real = c.sha256_file                                       # C5.1 control: a generic I/O fault stays unreadable

    def locked(path, *a, **kw):
        if Path(path) == p["backup"]:
            raise PermissionError("locked (simulated)")
        return real(path, *a, **kw)
    monkeypatch.setattr(c, "sha256_file", locked)
    with pytest.raises(s1_slot.QualifiedUnreadable, match=r"QUALIFIED member .*backup\.sqlite3 unreadable "
                                                          r"\(PermissionError\)"):
        s1_slot._resolution_evidence(out, q, day)


SCENARIOS = {                          # name: (pass-1 damage, pass-2 damage, confirmed?)
    "same-differs": ([("d1", "resolution", "append")], [], True),
    "moved-differs": ([("d1", "resolution", "append")], [("d1", "resolution", "restore"), ("d2", "resolution",
                                                                                            "append")], False),
    "same-absent-member": ([("d1", "backup", "delete")], [], True),
    "different-absent-members": ([("d1", "backup", "delete")], [("d1", "backup", "restore"),
                                                                 ("d1", "meta", "delete")], False),
    "absent-then-malformed": ([("d1", "resolution", "delete")], [("d1", "resolution", "malformed")], False),
    "same-malformed": ([("d1", "resolution", "malformed")], [], True),
}


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_h5cfix_real_raise_sites_confirm_only_the_same_observation(tmp_path, monkeypatch, name):   # end to end, A1/A3
    """Through the real sampled_seals and _resolution_evidence (the files damaged after the gate, a race): the same
    observation on the fresh confirming pass is INVALID; a moved, changed or differently classified one is refused
    with no row. A3: the confirming pass hashes the trees again with no pass memo (ps None in both passes), and the
    pin is verified again on the executed path: the helper's own c.sim() (after pass 1), then s1_seal._close's c.sim()
    inside the recompute (pass 2)."""
    import sys
    import s1_slot
    st_ = s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    (dd1, q1), (dd2, q2) = _sealed(tmp_path)[:2]
    p = {"d1": _paths(out, q1, dd1), "d2": _paths(out, q2, dd2)}
    keep = {(d, m): p[d][m].read_bytes() for d in p for m in p[d]}
    phase, sims, manifests = ["before"], [], []

    def damage(steps):
        for d, m, how in steps:
            if how == "append":
                p[d][m].write_bytes(keep[(d, m)] + b" ")
            elif how == "delete":
                p[d][m].unlink()
            elif how == "malformed":
                p[d][m].write_bytes(b"{not json")
            else:
                p[d][m].write_bytes(keep[(d, m)])
    first, second, confirmed = SCENARIOS[name]
    real_seals, real_sim, real_man = z.sampled_seals, c.sim, s1_slot._qualified_manifest
    n = [0]

    def seals(*a, **kw):
        n[0] += 1
        damage(first if n[0] == 1 else second)
        phase[0] = n[0]
        try:
            return real_seals(*a, **kw)
        finally:
            phase[0] = f"after{n[0]}"

    def sim():
        sims.append((phase[0], sys._getframe(1).f_code.co_name))
        return real_sim()

    def man(o, s, d, subject, ps):
        manifests.append((phase[0], subject, ps))
        return real_man(o, s, d, subject, ps)
    monkeypatch.setattr(z, "sampled_seals", seals)
    monkeypatch.setattr(c, "sim", sim)
    monkeypatch.setattr(s1_slot, "_qualified_manifest", man)
    if confirmed:
        _score_invalid(tmp_path, st_)
    else:
        with _Clock(st_["now"]), pytest.raises(SystemExit, match=r"^score refused: a QUALIFIED tree problem was not "
                                                                 r"confirmed on a re-read \(first "):
            r.score(tmp_path, "score-ack")
        assert all(x.kind != "TRIAL-INVALID" for x in jrows(tmp_path)) and _stage_kinds(tmp_path) == []
        assert not (out / "aborted.json").exists()
    assert n[0] == 2
    assert ("after1", "_pre_intent_qualified") in sims and (2, "_close") in sims, sims     # A3: executed pin path
    for k in (1, 2):                                                                       # A3: no memo crosses
        assert any(ph == k and subj == q1.subject for ph, subj, _ in manifests), (k, manifests)
    assert all(ps is None for ph, _, ps in manifests if ph in (1, 2)), manifests
