"""Erratum 2 r4 G1 (NVS-REQ1..5; O1-O5, E2-C1..C4): the NO-VALID-SEAL terminal score - STOP -> stop_attest -> final
snapshot -> SCORE-ACK (prev = PREREG-ACK, final_manifest_sha256=absent, final_snapshot_sha256 = the report hash)
-> score (exactly four inputs; verdict NO-VALID-SEAL, classification INCONCLUSIVE, nomination false). Map rows
400-407, 450-453, and Erratum 2 Clarification 1 r2 C3 rows 488-490 (the report's written_utc is a LOWER BOUND only;
the issuer reads the published report before issuing the SCORE-ACK). Behavioural RED against the H2 stub
(s1_evidence/a3/tH2_red.txt). t11 fixture: W_last = 2027-04-26T12:00:00Z. Every mailbox is the test's tmp mailbox."""
import json
import sqlite3
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
import s1_checkpoint as ck
import s1_collect as k
import s1_common as c
import s1_journal as j
import s1_run as r
import s1_seal as z
import s1_snapshot
import s1_stage as sg
import s1_trial as t
from conftest import Spies, _Clock, s1_ack, s1_jappend, s1_reack, s1_state, s1_synthetic_stop

START = "2026-10-26T13:30:00+00:00"
W_LAST = c.aware("2027-04-26T12:00:00+00:00")
LOTS20 = [{"symbol": f"S{i % 5}", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (1, 120.0)} for i in range(20)]
FOUR = {"stop.json", "trial_stop_line", "attest_stop.json", "sampled_history"}
ATTEST_KEYS = ["statement", "trial_id", "attest_start_sha256", "start", "stop_close", "stop_status",
               "sealed_final_ledger_sha256", "stop_sha256", "stop_line_sha256", "recorded_utc", "intent_at"]


def mb(root):
    return Path(root) / "mailbox.sqlite3"


def jrows(root):
    trs = t.trials(t.scan(mb(root)))
    (tid,) = [x for x, tr_ in trs.items() if tr_.closed is None]
    return j.read_trial(tid, trs[tid].genesis, mb(root))


def ok(fn, *a, **kw):
    """A refusal of a step the NVS branch must permit is a behavioural failure (B3), never a traceback."""
    try:
        return fn(*a, **kw)
    except SystemExit as e:
        pytest.fail(f"{getattr(fn, '__name__', fn)} refused on the NVS branch: {e}")


def created(rows, stage):
    return j.first(j.subject_rows(rows, f"stage/{stage}"), "STAGE-CREATED")


def forbidden(monkeypatch):
    """Spies beyond conftest.Spies: final plan / final / snapshot / provider entry points (G1.8)."""
    calls = []
    for mod, name in ((k, "write_final_plan"), (k, "do_final"), (k, "final_plan_record"), (k, "_get"),
                      (k, "_paged"), (s1_snapshot, "take_snapshot")):
        real = getattr(mod, name)
        monkeypatch.setattr(mod, name, lambda *a, _n=name, _r=real, **kw: calls.append(_n) or _r(*a, **kw))
    return calls


def nvs_chain(tmp_path, *, attest=True, snapshot=True, ack=True, ack_at=None, **given):
    """The G1.2 NVS graph through the real commands: the NVS TRIAL-STOP (s1_state, lots=[], seal_days=[], final=False,
    stop_attest=False: this helper attests itself), stop_attest, the final snapshot, then the SCORE-ACK built by
    s1_trial.token (prev = PREREG-ACK). info["t0"] = the stop instant (W_last + 1 day); "now" = a score instant after
    every step."""
    st_ = s1_state(tmp_path, START, score_ready=True, lots=[], seal_days=[], final=False, stop_attest=False)
    t0 = st_["stop_attested_at"]
    st_["t0"] = t0
    if attest:
        with _Clock(t0):
            ok(r.attest_stop, tmp_path, r.STOP_STATEMENT)
    if snapshot:
        at = t0 + timedelta(days=2)
        with _Clock(at):
            ok(ck.run_final_snapshot, tmp_path, st_["ledger"].path, now=lambda: at)
    if ack:
        st_["ack_line"] = ok(s1_ack, tmp_path, "score-ack", "S1-SCORE-ACK", ack_at or t0 + timedelta(days=3), **given)
    st_["now"] = t0 + timedelta(days=4)
    return st_


def test_nvs_branch_commits_inconclusive_score(tmp_path, monkeypatch):                        # row 400 (NVS-A1)
    st_ = nvs_chain(tmp_path)
    out, tr = tmp_path / "s1_out", t.open_trial(mb(tmp_path))
    rep_bytes = (out / "final_snapshot" / "report.json").read_bytes()
    assert json.loads(rep_bytes)["trial_status"] == "NO-VALID-SEAL"
    f = tr.acks["S1-SCORE-ACK"].fields
    assert f["prev"] == tr.acks["S1-PREREG-ACK"].mailbox_id and "S1-ACQUIRE-ACK" not in tr.acks
    assert f["final_manifest_sha256"] == "absent" and f["final_snapshot_sha256"] == c.sha256_bytes(rep_bytes)
    sp, calls = Spies(monkeypatch), forbidden(monkeypatch)
    with _Clock(st_["now"]):
        rep = ok(r.score, tmp_path, "score-ack")
    rows = jrows(tmp_path)
    assert [x.kind for x in j.subject_rows(rows, "stage/score")] == ["STAGE-INTENT", "STAGE-PREPARED",
                                                                      "STAGE-CREATED"]
    d = sg.staging_dir(tmp_path, tr.trial_id, "score")
    env, com = json.loads((d / "intent.json").read_bytes()), json.loads((d / "prepared.json").read_bytes())
    assert set(env["inputs"]) == FOUR and env["request_policy"] is None
    assert env["acks"] == {"S1-SCORE-ACK": tr.acks["S1-SCORE-ACK"].sha}
    assert set(com["members"]) == {"score/attempt.json", "score/s1.json"} and com["provenance"] == []
    assert (rep["verdict"], rep["classification"], rep["nomination"]) == ("NO-VALID-SEAL", "INCONCLUSIVE", False)
    assert not any(isinstance(rep.get(x), (int, float)) for x in ("return", "baseline_return", "n"))
    sp.assert_zero()
    assert calls == []
    assert not (out / "final_plan.json").exists() and not (out / "final").exists()


DEFECTS = ("no-ack", "before-stop-attest", "seq-before-stop-attest", "before-w-last", "before-snapshot", "wrong-trial",
           "ack-bundle-chain", "wrong-stop-line", "wrong-attest-sha", "wrong-stop-sha", "prev-run", "prev-audit",
           "prev-missing-acquire", "nvs-with-acquire-prev")
_LATE = r"created not after the journal row it references \(F6\.1\)"       # (the gate's F6.1/F7.1 ACK binding)
_PREV = r"is not the S1-PREREG-ACK"                                            # (G1.4 mailbox-level NVS shape)
DEFECT_REFUSAL = {"no-ack": r"no S1-SCORE-ACK", "before-stop-attest": _LATE,
                  "seq-before-stop-attest": r"journal_seq \d+ precedes the stop_attest CREATED row",
                  "before-w-last": _LATE, "before-snapshot": r"lower bound", "wrong-trial": r"no S1-SCORE-ACK",
                  "ack-bundle-chain": r"bundle chain broken",
                  "wrong-stop-line": r"stop_line_sha256 is not the TRIAL-STOP line",
                  "wrong-attest-sha": r"\['stop_attest_sha256'\] differ", "wrong-stop-sha": r"\['stop_sha256'\] differ",
                  "prev-run": _PREV, "prev-audit": _PREV, "prev-missing-acquire": _PREV,
                  "nvs-with-acquire-prev": r"mistaken S1-ACQUIRE-ACK.*escalate"}


@pytest.mark.parametrize("case", DEFECTS)
def test_nvs_score_ack_defects_refuse(tmp_path, monkeypatch, case):                         # row 401 (NVS-A2)
    st_ = nvs_chain(tmp_path, ack=False)
    t0, tr = st_["t0"], t.open_trial(mb(tmp_path))
    rows = jrows(tmp_path)
    att = created(rows, "stop_attest")
    snap_at = t0 + timedelta(days=2)
    when, over = t0 + timedelta(days=3), {}
    if case == "before-stop-attest":
        when = c.aware(att.at)                                         # created <= the stop_attest CREATED row
    elif case == "seq-before-stop-attest":
        prior = [x for x in rows if x.seq < att.seq][-1]
        over = {"journal_seq": str(prior.seq), "journal_head_sha256": prior.sha}
    elif case == "before-w-last":
        when = W_LAST
    elif case == "before-snapshot":
        when = snap_at - timedelta(minutes=1)
    elif case == "wrong-trial":
        over = {"trial_id": str(uuid.uuid4())}
    elif case == "ack-bundle-chain":
        over = {"bundle_sha256": "0" * 64}
    elif case in ("wrong-stop-line", "wrong-attest-sha", "wrong-stop-sha"):
        over = {{"wrong-stop-line": "stop_line_sha256", "wrong-attest-sha": "stop_attest_sha256",
                 "wrong-stop-sha": "stop_sha256"}[case]: "0" * 64}
    elif case == "prev-run":
        over = {"prev": tr.acks["S1-RUN-ACK"].mailbox_id}
    elif case == "prev-audit":
        over = {"prev": tr.audit.mailbox_id}
    elif case == "prev-missing-acquire":
        over = {"prev": "no-such-acquire-ack"}
    elif case == "nvs-with-acquire-prev":                              # wrong-branch direction 1 (mistaken ACK)
        s1_ack(tmp_path, "acq-ack", "S1-ACQUIRE-ACK", t0 + timedelta(days=2, hours=1))
    if case != "no-ack":
        s1_ack(tmp_path, "score-ack", "S1-SCORE-ACK", when, **over)
    if case == "nvs-with-acquire-prev":
        assert t.open_trial(mb(tmp_path)).acks["S1-SCORE-ACK"].fields["prev"] == "acq-ack"
    sp, calls = Spies(monkeypatch), forbidden(monkeypatch)
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=DEFECT_REFUSAL[case]):
        r.score(tmp_path, "score-ack")
    assert j.subject_rows(jrows(tmp_path), "stage/score") == []
    assert not (tmp_path / "s1_out" / "score").exists()
    assert not sg.staging_dir(tmp_path, tr.trial_id, "score").exists()
    sp.assert_zero()
    assert calls == []


@pytest.mark.parametrize("status", ["stopped", "timeout"])
def test_normal_stop_cannot_take_nvs_path(tmp_path, monkeypatch, status):                   # row 402 (NVS-A3)
    st_ = s1_state(tmp_path, START, score_ready=True, final=False, **({} if status == "stopped" else
                                                                      {"lots": LOTS20}))
    assert json.loads((tmp_path / "s1_out" / "stop.json").read_text(encoding="utf-8"))["status"] == \
        {"stopped": "STOPPED", "timeout": "TIMEOUT"}[status]
    tr = t.open_trial(mb(tmp_path))
    s1_ack(tmp_path, "score-ack", "S1-SCORE-ACK", st_["stop_attested_at"] + timedelta(days=3),
           prev=tr.acks["S1-PREREG-ACK"].mailbox_id, final_manifest_sha256="absent")
    with _Clock(st_["stop_attested_at"] + timedelta(days=4)), \
            pytest.raises(SystemExit, match=r"score refused: no final acquisition manifest yet \(COMPLETE or "
                                            r"ABORTED\)"):
        r.score(tmp_path, "score-ack")
    assert j.subject_rows(jrows(tmp_path), "stage/score") == []
    gv = t.gate(tmp_path, "nvs envelope probe")                        # an NVS-envelope INTENT on a normal trial
    with pytest.raises(SystemExit, match=r"predecessor final is not CREATED"):
        sg.run(gv, "score", inputs={n: "0" * 64 for n in FOUR},
               acks={"S1-SCORE-ACK": "1" * 64}, work=lambda sw: pytest.fail("score work ran"),
               mailbox=mb(tmp_path))
    assert j.subject_rows(jrows(tmp_path), "stage/score") == []


def test_wrong_branch_score_ack_names_the_branch(tmp_path, monkeypatch):                     # row 402 (NVS-A3, unit)
    """NVS-A3 at the score command itself (the `_pre_reserve_gate` final-manifest refusal of the normal branch is
    bypassed, as at unit level): a normal STOPPED trial with a PREREG-prev / absent-final SCORE-ACK is refused as the
    wrong branch before any score INTENT."""
    st_ = s1_state(tmp_path, START, score_ready=True, final=False)
    tr = t.open_trial(mb(tmp_path))
    s1_ack(tmp_path, "score-ack", "S1-SCORE-ACK", st_["stop_attested_at"] + timedelta(days=3),
           prev=tr.acks["S1-PREREG-ACK"].mailbox_id, final_manifest_sha256="absent")
    monkeypatch.setattr(r, "_pre_reserve_gate", lambda *a, **kw: None)
    with _Clock(st_["stop_attested_at"] + timedelta(days=4)), \
            pytest.raises(SystemExit, match=r"wrong branch \(NVS-A3\)"):
        r.score(tmp_path, "score-ack")
    assert j.subject_rows(jrows(tmp_path), "stage/score") == []


def _bad_stop_detail(tmp_path, monkeypatch, gap):
    """Row 403 bad-stop-detail (H2 fix round 1, review I-2; G1.1 condition (2)): a genuinely TERMINAL no-seal history -
    every eligible close has no QUALIFIED and the last eligible close's W slot is terminal (s1_close_out), so the
    record recomputed from the rows before the STOP is an NVS-shaped candidate - whose TRIAL-STOP detail is NOT that
    record (here a forged synthetic record with a consistent stop.json, NVS status, no seal). Only a hand-written
    journal row (s1_synthetic_stop) can make such a STOP: decide_stop always commits the recomputed record. Clause (2)
    is thus defence in depth against a forged STOP row, and this case is its killer. Consistent stop.json: never NVS -
    attest_stop refuses, the snapshot is taken, the SCORE-ACK is issued and the score is the wrong branch (NVS-A3),
    no row, never INCONCLUSIVE. Publication gap (stop.json absent): the gate recomputes the record and commits
    INVALID (stop-conflict) (F2.3)."""
    from conftest import s1_close_out
    st_ = s1_state(tmp_path, START, score_ready=True, lots=[], seal_days=[], stop=False)
    s1_close_out(tmp_path, st_["calendar"], "2027-04-23")              # the last eligible close's W slot is terminal
    pr = json.loads((tmp_path / "s1_out" / "prereg.json").read_bytes())
    t0 = st_["now"]
    rows = jrows(tmp_path)
    bundle = t.open_trial(mb(tmp_path)).bundle
    rec = z.stop_record(tmp_path / "s1_out", rows, c.aware(pr["start"]), pr["calendar"], bundle)
    assert rec is not None and rec["status"] == "NO-VALID-SEAL"         # a terminal NVS candidate exists
    stop = s1_synthetic_stop(tmp_path, t0)                             # ... but the STOP commits another record
    assert stop.detail != j.detail_of(rec)
    out = tmp_path / "s1_out"
    if gap:
        (out / "stop.json").unlink()
        with _Clock(t0 + timedelta(days=1)), pytest.raises(SystemExit, match=r"INVALID \(stop-conflict\)"):
            r.attest_stop(tmp_path, r.STOP_STATEMENT)
        rows = jrows(tmp_path)
        assert [x.subject for x in rows if x.kind == "TRIAL-INVALID"] == ["reason/stop-conflict"]
        assert j.subject_rows(rows, "stage/stop_attest") == [] and j.subject_rows(rows, "stage/score") == []
        return
    with _Clock(t0 + timedelta(days=1)), \
            pytest.raises(SystemExit, match=r"stop attestation refused: no stop recorded \(status NO-VALID-SEAL\)"):
        r.attest_stop(tmp_path, r.STOP_STATEMENT)
    at = t0 + timedelta(days=2)
    with _Clock(at):
        ok(ck.run_final_snapshot, tmp_path, st_["ledger"].path, now=lambda: at)
    s1_ack(tmp_path, "score-ack", "S1-SCORE-ACK", t0 + timedelta(days=3))
    sp = Spies(monkeypatch)
    with _Clock(t0 + timedelta(days=4)), pytest.raises(SystemExit, match=r"wrong branch \(NVS-A3\)"):
        r.score(tmp_path, "score-ack")
    rows = jrows(tmp_path)
    assert j.subject_rows(rows, "stage/stop_attest") == [] and j.subject_rows(rows, "stage/score") == []
    assert [x for x in rows if x.kind == "TRIAL-INVALID"] == [] and not (out / "score").exists()
    sp.assert_zero()


@pytest.mark.parametrize("case", ["forged-stop-json", "bad-stop-detail", "bad-stop-detail-publication-gap",
                                  "damaged-qualified", "damaged-ineligible-seal", "damaged-opening",
                                  "registered-bundle-changed"])
def test_forged_or_damaged_nvs_never_inconclusive(tmp_path, monkeypatch, case):            # row 403 (NVS-A4)
    out = tmp_path / "s1_out"
    if case.startswith("bad-stop-detail"):
        _bad_stop_detail(tmp_path, monkeypatch, gap=case.endswith("publication-gap"))
        return
    if case == "forged-stop-json":                     # a TIMEOUT trial; stop.json replaced by an NVS-shaped record
        st_ = s1_state(tmp_path, START, score_ready=True, lots=LOTS20)
        rec = json.loads((out / "stop.json").read_text(encoding="utf-8"))
        (out / "stop.json").write_text(json.dumps(dict(rec, status="NO-VALID-SEAL", stop_close=None, stop_seal=None,
                                                       stop_seal_sha256=None, cohort_row_ids=[], lots=None,
                                                       seals={})), encoding="utf-8")
        want = r"INVALID \(registration-artifact\)"                    # after a finalization INTENT (F2.4)
    else:
        st_ = (nvs_ineligible_chain(tmp_path) if case == "damaged-ineligible-seal" else nvs_chain(tmp_path))
        if case == "damaged-qualified":                # the opening QUALIFIED capture tree (F3)
            p = next((out / "captures").glob("*/*/backup.sqlite3"))
            p.write_bytes(p.read_bytes() + b"x")
            want = r"INVALID \(registration-artifact\)"
        elif case == "damaged-ineligible-seal":        # a CREATED seal stage of the ineligible d130 close
            p = out / "seals" / "2027-04-26.json"
            p.write_bytes(p.read_bytes() + b" ")
            want = r"INVALID \(stage-replaced\)"
        elif case == "damaged-opening":
            p = out / "seals" / f"{st_['opening_close']}.json"
            p.write_bytes(p.read_bytes() + b" ")
            want = r"INVALID \(stage-replaced\)"
        else:
            monkeypatch.setattr(c, "bundle_sha256", lambda: "f" * 64)
            want = r"INVALID \(bundle\)"
    sp = Spies(monkeypatch)
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=want):
        r.score(tmp_path, "score-ack")
    rows = jrows(tmp_path)
    assert j.first(j.subject_rows(rows, "stage/score"), "STAGE-CREATED") is None
    assert not (out / "score").exists()
    if case == "registered-bundle-changed":
        assert [x.subject for x in rows if x.kind == "TRIAL-INVALID"] == ["reason/bundle"]
    sp.assert_zero()


def nvs_ineligible_chain(tmp_path):
    """r1 case (v) (a3_helpers.stop_history 'no-valid-seal-ineligible-seal': a CREATED seal stage of the ineligible
    d130 close selling 100) finished as an NVS chain: decide_stop at W_last + 1 day, stop_attest, the final snapshot
    (the fixture ledger root/s1_ledger.sqlite3), then the SCORE-ACK."""
    import a3_helpers as h
    h.stop_history(tmp_path, START, "no-valid-seal-ineligible-seal")
    pr = json.loads((tmp_path / "s1_out" / "prereg.json").read_text(encoding="utf-8"))
    t0 = W_LAST + timedelta(days=1)
    with _Clock(t0):
        z.decide_stop(t.gate(tmp_path, "fixture stop"), pr["calendar"], c.aware(pr["start"]), lambda: t0,
                      mailbox=mb(tmp_path))
        ok(r.attest_stop, tmp_path, r.STOP_STATEMENT)
    at = t0 + timedelta(days=2)
    with _Clock(at):
        ok(ck.run_final_snapshot, tmp_path, tmp_path / "s1_ledger.sqlite3", now=lambda: at)
    ok(s1_ack, tmp_path, "score-ack", "S1-SCORE-ACK", t0 + timedelta(days=3))
    return {"t0": t0, "now": t0 + timedelta(days=4), "opening_close": None}


@pytest.mark.parametrize("branch", ["nvs", "normal-control"])
def test_nvs_exact_schemas(tmp_path, monkeypatch, branch):                                    # row 404 (NVS-A5)
    out = tmp_path / "s1_out"
    if branch == "nvs":
        st_ = nvs_chain(tmp_path)
        stop = json.loads((out / "stop.json").read_text(encoding="utf-8"))
        assert all(stop[x] is None for x in ("stop_close", "stop_seal", "stop_seal_sha256", "lots"))
        assert stop["cohort_row_ids"] == [] and stop["seals"] == {}
    else:
        st_ = s1_state(tmp_path, START, score_ready=True)
    att = json.loads((out / "attest_stop.json").read_text(encoding="utf-8"))
    assert sorted(att) == sorted(ATTEST_KEYS) and len(att) == len(ATTEST_KEYS)      # (the member is key-sorted JSON)
    nulls = {x for x in ATTEST_KEYS if att[x] is None}
    assert nulls == ({"stop_close", "sealed_final_ledger_sha256"} if branch == "nvs" else set())
    if branch == "normal-control":                                     # a normal-branch null is flagged, never valid
        a2 = dict(att, stop_close=None)
        pr = json.loads((out / "prereg.json").read_text(encoding="utf-8"))
        (out / "attest_stop.json").write_text(json.dumps(a2), encoding="utf-8")
        stop = json.loads((out / "stop.json").read_text(encoding="utf-8"))
        got = r._stop_attestation(out, pr, stop, out / stop["stop_seal"], None)
        assert got["ok"] is False and "stop close differs" in got["problems"]
        return
    pr = json.loads((out / "prereg.json").read_text(encoding="utf-8"))
    stop = json.loads((out / "stop.json").read_text(encoding="utf-8"))
    got = r._stop_attestation(out, pr, stop, None, None, nvs=False)  # the two nulls are accepted ONLY under NVS
    assert got["ok"] is False and "stop close differs" in got["problems"]
    assert r._stop_attestation(out, pr, stop, None, None, nvs=True)["ok"] is True
    f = t.open_trial(mb(tmp_path)).acks["S1-SCORE-ACK"].fields
    assert f["final_manifest_sha256"] == "absent" and len(f["final_snapshot_sha256"]) == 64
    s1_reack(tmp_path, "score-ack-absent", "S1-SCORE-ACK", st_["t0"] + timedelta(days=3),
             final_snapshot_sha256="absent")                           # an NVS SCORE-ACK binding no report
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=r"final_snapshot_sha256"):
        r.score(tmp_path, "score-ack-absent")
    assert j.subject_rows(jrows(tmp_path), "stage/score") == []
    s1_reack(tmp_path, "score-ack", "S1-SCORE-ACK", st_["t0"] + timedelta(days=3))
    with _Clock(st_["now"]):
        ok(r.score, tmp_path, "score-ack")
    names = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    assert "final_plan.json" not in names and not any(x.startswith("final/") for x in names)
    assert "None" not in names and not any(x.endswith("/None") for x in names)      # no Path(None)


@pytest.mark.parametrize("case", ["before-w-last", "pending-w-no-lots", "unresolved"])
def test_not_terminal_nvs_cannot_attest_or_score(tmp_path, monkeypatch, case):              # row 405 (NVS-A6)
    import a3_helpers as h
    from conftest import s1_close_out
    if case == "unresolved":
        h.stop_history(tmp_path, START, "unresolved-blocks")
        at = W_LAST + timedelta(days=1)
    else:
        st_ = s1_state(tmp_path, START, score_ready=True, lots=[], seal_days=[], stop=False)
        at = W_LAST - timedelta(seconds=1)
        if case == "pending-w-no-lots":                                # W_L INTENT before D(W_L), no lots candidate
            s1_jappend(tmp_path, "SLOT-INTENT", "slot/20270426T120000Z", at=W_LAST - timedelta(seconds=10))
            s1_close_out(tmp_path, st_["calendar"], "2027-04-23")      # the other d129 slots MISSED at W
            at = W_LAST + timedelta(minutes=29, seconds=59)
    pr = json.loads((tmp_path / "s1_out" / "prereg.json").read_text(encoding="utf-8"))
    with _Clock(at):
        z.decide_stop(t.gate(tmp_path, "probe", defer_pending=True), pr["calendar"], c.aware(pr["start"]),
                      lambda: at, mailbox=mb(tmp_path))
        stop = j.first(jrows(tmp_path), "TRIAL-STOP")
        assert stop is None or json.loads((tmp_path / "s1_out" / "stop.json").read_bytes())["status"] == "STOPPED"
        with pytest.raises(SystemExit, match=r"stop attestation refused: no stop recorded \(status RUNNING\)"):
            r.attest_stop(tmp_path, r.STOP_STATEMENT)
    rows = jrows(tmp_path)
    assert j.subject_rows(rows, "stage/stop_attest") == [] and j.subject_rows(rows, "stage/score") == []


@pytest.mark.parametrize("case", ["publication-gap", "same-ack-replay", "conflicting-intent", "computation-error"])
def test_nvs_score_failure_and_recovery_rules(tmp_path, monkeypatch, case):                 # row 406 (NVS-A7)
    st_ = nvs_chain(tmp_path)
    n, real = [0], r._score
    monkeypatch.setattr(r, "_score", lambda *a, **kw: n.__setitem__(0, n[0] + 1) or real(*a, **kw))
    if case == "publication-gap":                                      # crash after PREPARED, before publication
        real_pub, hit = sg._publish_one, []

        def crash_once(out, rel, data, sha):
            if not hit:
                hit.append(1)
                raise KeyboardInterrupt("crash (simulated)")
            return real_pub(out, rel, data, sha)
        monkeypatch.setattr(sg, "_publish_one", crash_once)
        with _Clock(st_["now"]), pytest.raises(KeyboardInterrupt, match=r"crash \(simulated\)"):
            r.score(tmp_path, "score-ack")
        monkeypatch.setattr(sg, "_publish_one", real_pub)
        assert created(jrows(tmp_path), "score") is None
        with _Clock(st_["now"] + timedelta(minutes=1)):
            t.gate(tmp_path, "recover")                                 # F4.7: same-byte recovery
        assert created(jrows(tmp_path), "score") is not None and n[0] == 1
        assert (tmp_path / "s1_out" / "score" / "s1.json").is_file()
    elif case == "same-ack-replay":                                    # F1 "each stage once": no second run
        with _Clock(st_["now"]):
            ok(r.score, tmp_path, "score-ack")
            first = (tmp_path / "s1_out" / "score" / "s1.json").read_bytes()
            with pytest.raises(SystemExit, match=r"stage score is already CREATED: re-entry refused \(F1\)"):
                r.score(tmp_path, "score-ack")
        assert (tmp_path / "s1_out" / "score" / "s1.json").read_bytes() == first and n[0] == 1
        assert [x.kind for x in j.subject_rows(jrows(tmp_path), "stage/score")].count("STAGE-INTENT") == 1
    elif case == "conflicting-intent":                                 # a second, conflicting score INTENT row
        with _Clock(st_["now"]):
            ok(r.score, tmp_path, "score-ack")
        gv = t.gate(tmp_path, "probe")
        stage_gate, check = sg._gates(gv, "score", None, None)
        res = j.append(gv.trial.trial_id, gv.trial.genesis,
                       j.Request("STAGE-INTENT", "stage/score", j.new_nonce(), j.new_nonce(), detail="d" * 64),
                       t.product_context(gv.trial, stage_gate=stage_gate, stage_check=check),
                       mailbox=mb(tmp_path), clock=lambda: st_["now"] + timedelta(minutes=1))
        assert res.outcome == "INVALIDATE" and res.reason == "repeat-stage"
        rows = jrows(tmp_path)
        assert [x.subject for x in rows if x.kind == "TRIAL-INVALID"] == ["reason/repeat-stage"]
        assert n[0] == 1
    else:
        monkeypatch.setattr(r, "_score", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
        with _Clock(st_["now"]), pytest.raises(SystemExit, match=r"INVALID \(score-aborted\)"):
            r.score(tmp_path, "score-ack")
        (tid,) = t.trials(t.scan(mb(tmp_path)))                         # (read without the gate: the trial is INVALID)
        assert (sg.staging_dir(tmp_path, tid, "score") / "score" / "s1.json").is_file()
        assert not (tmp_path / "s1_out" / "score").exists()


def test_nvs_close_scored_evidence(tmp_path):                                               # row 407 (NVS-A8)
    """NVS-A8 as amended by Clarification 1 C2.1: only the kept sentences - CLOSE SCORED on sha256(score/s1.json)
    closes the trial; S1 writes no CLOSE; no new trial appears. The superseded 'wrong evidence hash leaves it open' is
    rows 485 (issuer no-send, procedural model) and 487 (trusted-issuer residual), never a runtime refusal here."""
    st_ = nvs_chain(tmp_path)
    with _Clock(st_["now"]):
        ok(r.score, tmp_path, "score-ack")
    s1 = (tmp_path / "s1_out" / "score" / "s1.json").read_bytes()
    h = t.close_evidence("SCORED", score_record=s1)
    assert h == c.sha256_bytes(s1)                                        # the evidence the issuer binds (C2.1)
    before = {x.mailbox_id for x in t.scan(mb(tmp_path))}
    s1_ack(tmp_path, "close", "S1-CLOSE-ACK", st_["now"] + timedelta(hours=1), reason="SCORED", evidence_sha256=h)
    with pytest.raises(SystemExit, match=r"zero open trials"):
        t.open_trial(mb(tmp_path))
    new = [a for a in t.scan(mb(tmp_path)) if a.mailbox_id not in before]
    assert [a.kind for a in new] == ["S1-CLOSE-ACK"] and new[0].sender == "codex"     # S1 writes no CLOSE
    assert len(t.trials(t.scan(mb(tmp_path)))) == 1                                    # no new trial


@pytest.mark.parametrize("case", ["committed-invalid", "local-abort-after-stop-attest"])
def test_known_invalidity_never_enters_score(tmp_path, monkeypatch, case):                 # row 450 (NVS-A9)
    st_ = nvs_chain(tmp_path)
    before = [x.sha for x in jrows(tmp_path) if x.kind == "TRIAL-INVALID"]
    if case == "committed-invalid":
        s1_jappend(tmp_path, "TRIAL-INVALID", "reason/stage-replaced", at=st_["now"], detail="a" * 64)
        want = r"trial INVALID"
    else:
        (tmp_path / "s1_out" / "aborted.json").write_text(json.dumps({"reason": "x"}), encoding="utf-8")
        want = r"INVALID \(established-violation\)"
    sp, calls = Spies(monkeypatch), forbidden(monkeypatch)
    n, real = [0], r._score
    monkeypatch.setattr(r, "_score", lambda *a, **kw: n.__setitem__(0, n[0] + 1) or real(*a, **kw))
    with _Clock(st_["now"] + timedelta(minutes=1)), pytest.raises(SystemExit, match=want):
        r.score(tmp_path, "score-ack")
    inv = [x for x in jrows(tmp_path) if x.kind == "TRIAL-INVALID" and x.sha not in before]
    assert len(inv) == 1 and (case == "committed-invalid" or inv[0].subject == "reason/established-violation")
    assert j.subject_rows(jrows(tmp_path), "stage/score") == [] and n[0] == 0
    sp.assert_zero()
    assert calls == []


def test_failure_discovered_during_authorized_score(tmp_path, monkeypatch):                # row 451 (NVS-A10)
    st_ = nvs_chain(tmp_path)
    real = r._seal_chain_problems
    monkeypatch.setattr(r, "_seal_chain_problems", lambda *a, **kw: real(*a, **kw) + ["injected integrity failure"])
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=r"stage score: INVALID \(registration-artifact\)"):
        r.score(tmp_path, "score-ack")
    trs = t.trials(t.scan(mb(tmp_path)))
    (tid,) = trs
    d = sg.staging_dir(tmp_path, tid, "score")
    assert (d / "score" / "s1.json").is_file() and not (d / "prepared.json").exists()
    assert [x.subject for x in jrows(tmp_path) if x.kind == "TRIAL-INVALID"] == ["reason/registration-artifact"]


def test_score_helper_unit_aborted_invalid(tmp_path, monkeypatch):                        # row 451 (unit-only)
    """UNIT-LEVEL ONLY (NVS-A10 label): the private _score helper may return ABORTED-INVALID; this is not proof that
    a known-invalid trial may enter the score stage."""
    st_ = nvs_chain(tmp_path)
    (tmp_path / "s1_out" / "aborted.json").write_text(json.dumps({"reason": "x"}), encoding="utf-8")
    with _Clock(st_["now"]):
        assert r._score(tmp_path / "s1_out", mb(tmp_path))["verdict"] == "ABORTED-INVALID"


@pytest.mark.parametrize("case", ["missing-before-issuance", "deleted-after-binding", "changed-after-binding",
                                  "unconfirmed-read", "fence-violation"])
def test_nvs_snapshot_cases(tmp_path, monkeypatch, case):                                    # row 452 (NVS-A11)
    out = tmp_path / "s1_out"
    if case == "missing-before-issuance":
        st_ = nvs_chain(tmp_path, snapshot=False)                      # the token binds final_snapshot_sha256=absent
        assert t.open_trial(mb(tmp_path)).acks["S1-SCORE-ACK"].fields["final_snapshot_sha256"] == "absent"
        with _Clock(st_["now"]), pytest.raises(SystemExit, match=r"score refused: no final snapshot \(run "
                                                              r"s1_checkpoint\.py --final-snapshot"):
            r.score(tmp_path, "score-ack")
        with pytest.raises(SystemExit, match=r"no final snapshot"):
            r._pre_reserve_gate(out, {"ack_id": "x", "created_utc": st_["now"].isoformat()}, mailbox=mb(tmp_path))
        assert j.subject_rows(jrows(tmp_path), "stage/score") == []
        return
    st_ = nvs_chain(tmp_path)
    rp = out / "final_snapshot" / "report.json"
    if case == "deleted-after-binding":
        rp.unlink()
        want = r"INVALID \(registration-artifact\)"
    elif case == "changed-after-binding":
        rp.write_bytes(rp.read_bytes() + b" ")
        want = r"INVALID \(registration-artifact\)"
    elif case == "unconfirmed-read":
        real, n = c.sha256_file, [0]

        def flaky(p):
            if Path(p) == rp:
                n[0] += 1
                return "0" * 64 if n[0] == 1 else real(p)              # a differing read that does not confirm
            return real(p)
        monkeypatch.setattr(c, "sha256_file", flaky)
        want = r"read differently on a second read"
    else:
        rep = json.loads(rp.read_bytes())
        monkeypatch.setattr(r, "_final_snapshot_problems", lambda *a, **kw: ["final snapshot: fence violated"])
        want = r"stage score: INVALID \(registration-artifact\)"         # ABORTED-INVALID via OQ-28 (NVS-A10 path)
        assert rep["trial_status"] == "NO-VALID-SEAL"
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=want):
        r.score(tmp_path, "score-ack")
    if case == "unconfirmed-read":
        assert [x for x in jrows(tmp_path) if x.kind == "TRIAL-INVALID"] == []
        assert j.subject_rows(jrows(tmp_path), "stage/score") == []


@pytest.mark.parametrize("case", ["refuse-escalate", "no-blocked-json", "close-skipping-acquire", "withdrawn-fixture"])
def test_mistaken_acquire_ack_on_nvs(tmp_path, monkeypatch, case):                          # row 453 (NVS-A12)
    st_ = nvs_chain(tmp_path, ack=False)
    s1_ack(tmp_path, "acq-ack", "S1-ACQUIRE-ACK", st_["t0"] + timedelta(days=2, hours=1))
    tr = t.open_trial(mb(tmp_path))
    if case in ("refuse-escalate", "no-blocked-json"):
        s1_ack(tmp_path, "score-ack", "S1-SCORE-ACK", st_["t0"] + timedelta(days=3))
        sp = Spies(monkeypatch)
        for fn in (lambda: k.write_final_plan(tmp_path),
                   lambda: k.do_final(tmp_path, "acq-ack", sp.client(), ("K", "S")),
                   lambda: r.score(tmp_path, "score-ack")):
            with _Clock(st_["now"]), pytest.raises(SystemExit, match=r"mistaken S1-ACQUIRE-ACK.*escalate"):
                fn()
        rows = jrows(tmp_path)
        assert all(j.subject_rows(rows, f"stage/{s}") == [] for s in ("final_plan", "final", "score"))
        sp.assert_zero()
        assert not (tmp_path / "s1_out" / "blocked.json").exists()
        assert [x for x in rows if x.kind == "TRIAL-INVALID"] == []
        return
    prev = tr.acks["S1-PREREG-ACK"].mailbox_id if case == "close-skipping-acquire" else "acq-ack"
    s1_ack(tmp_path, "close", "S1-CLOSE-ACK", st_["now"], prev=prev, reason="WITHDRAWN",
           evidence_sha256=c.sha256_bytes("operator withdrawal (fixture only)".encode("utf-8")))
    if case == "close-skipping-acquire":
        with pytest.raises(SystemExit, match=r"prev is not the latest ACK"):
            t.open_trial(mb(tmp_path))
    else:
        with pytest.raises(SystemExit, match=r"zero open trials"):
            t.open_trial(mb(tmp_path))


def test_mistaken_acquire_ack_after_the_gate_refuses_in_the_intent_transaction(tmp_path, monkeypatch):
    """Row 453 (O3) with ruling OP-25 (Codex 6bfdc5cc): the NVS predecessor rule is decided on the official ACKs
    parsed inside the score INTENT's own transaction, not on the gate snapshot - a mistaken S1-ACQUIRE-ACK issued
    after the command's pre-INTENT checks (here: while the sampled history is computed) still refuses and escalates,
    with no score row and no score work."""
    st_ = nvs_chain(tmp_path)
    real, posted = z.sampled_history, []

    def late_ack(*a, **kw):
        if not posted:
            posted.append(s1_ack(tmp_path, "acq-late", "S1-ACQUIRE-ACK", st_["t0"] + timedelta(days=3, hours=1)))
        return real(*a, **kw)
    monkeypatch.setattr(z, "sampled_history", late_ack)
    n, real_score = [0], r._score
    monkeypatch.setattr(r, "_score", lambda *a, **kw: n.__setitem__(0, n[0] + 1) or real_score(*a, **kw))
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=r"mistaken S1-ACQUIRE-ACK.*refuse and escalate"):
        r.score(tmp_path, "score-ack")
    assert posted and n[0] == 0
    assert j.subject_rows(jrows(tmp_path), "stage/score") == []


def test_nvs_final_plan_and_final_refuse_nothing_to_acquire(tmp_path, monkeypatch):        # row 453 (G1.6 control)
    """G1.6 without a mistaken ACK: write_final_plan and do_final refuse "NO-VALID-SEAL: nothing to acquire" after the
    gate, with no stage row, no request and no escalation text."""
    st_ = nvs_chain(tmp_path, ack=False)
    sp = Spies(monkeypatch)
    for fn in (lambda: k.write_final_plan(tmp_path), lambda: k.do_final(tmp_path, "acq-ack", sp.client(), ("K", "S"))):
        with _Clock(st_["now"]), pytest.raises(SystemExit, match=r"NO-VALID-SEAL: nothing to acquire") as ei:
            fn()
        assert "escalate" not in str(ei.value)
    rows = jrows(tmp_path)
    assert all(j.subject_rows(rows, f"stage/{s}") == [] for s in ("final_plan", "final"))
    sp.assert_zero()


def test_nvs_predicate_error_in_the_intent_transaction_refuses(tmp_path, monkeypatch):    # row 401 (fix 1, M-5)
    """H2 fix round 1 (review M-5; F0.7, I-2/I-4): the NVS predicate raising inside the score INTENT's own
    transaction (its second evaluation; the command's own evaluation passed) is a refusal with a reason and no row -
    never a raw traceback, never INVALID, never the normal branch."""
    st_ = nvs_chain(tmp_path)
    real, n = z.nvs, [0]

    def flaky(*a, **kw):
        n[0] += 1
        if n[0] == 2:                                               # (1 = the command, 2 = inside BEGIN IMMEDIATE)
            raise OSError(5, "injected read error")
        return real(*a, **kw)
    monkeypatch.setattr(z, "nvs", flaky)
    with _Clock(st_["now"]), pytest.raises((SystemExit, OSError)) as ei:
        r.score(tmp_path, "score-ack")
    assert isinstance(ei.value, SystemExit), repr(ei.value)
    assert "NO-VALID-SEAL predicate cannot be evaluated" in str(ei.value) and n[0] == 2
    rows = jrows(tmp_path)
    assert j.subject_rows(rows, "stage/score") == [] and [x for x in rows if x.kind == "TRIAL-INVALID"] == []


def test_nvs_predicate_file_not_found_is_no_missing_prereg(tmp_path, monkeypatch):          # row 453 (fix 1, M-6)
    """H2 fix round 1 (review M-6): a FileNotFoundError raised INSIDE the NVS predicate of write_final_plan /
    do_final is a predicate that cannot be evaluated (a refusal naming it), never read as "no prereg" (only the
    prereg load itself may mean that)."""
    st_ = nvs_chain(tmp_path, ack=False)
    monkeypatch.setattr(z, "nvs", lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError(2, "gone")))
    sp = Spies(monkeypatch)
    for fn in (lambda: k.write_final_plan(tmp_path), lambda: k.do_final(tmp_path, "acq-ack", sp.client(), ("K", "S"))):
        with _Clock(st_["now"]), pytest.raises(SystemExit, match=r"refused: the NO-VALID-SEAL predicate cannot be "
                                                                  r"evaluated \(FileNotFoundError"):
            fn()
    rows = jrows(tmp_path)
    assert all(j.subject_rows(rows, f"stage/{s}") == [] for s in ("final_plan", "final"))
    sp.assert_zero()


# ---------------------------------------------------------------- Clarification 1 r2 C3 (rows 488-490)
REAL_COORDINATION_MAILBOX = Path("C:/Users/gl450/.coordination/trading_app/mailbox.sqlite3")


def no_coordination_writes(monkeypatch):
    """Spy: any sqlite3.connect to the coordination mailbox fails the test (zero live mailbox writes, C2.2/C3). The
    path is only compared, never opened."""
    real = sqlite3.connect

    def guarded(db, *a, **kw):
        name = str(db)
        if name.startswith("file:"):
            name = name[len("file:"):].split("?")[0]
        if Path(name).resolve() == REAL_COORDINATION_MAILBOX.resolve():
            pytest.fail("a test touched the coordination mailbox")
        return real(db, *a, **kw)
    monkeypatch.setattr(sqlite3, "connect", guarded)


def issue_score_ack(root, at, bind_sha):
    """PROCEDURAL-MODEL issuer (O-C2; test-side only, never product): before issuing the SCORE-ACK the issuer reads
    the FINAL, PUBLISHED final_snapshot/report.json and issues only if its sha256 equals the hash the ACK binds
    (C3.2). Absent or different -> None, nothing sent. Not a production issuer guard."""
    p = Path(root) / "s1_out" / "final_snapshot" / "report.json"
    try:
        data = p.read_bytes()
    except OSError:
        return None
    if c.sha256_bytes(data) != bind_sha:
        return None
    return s1_ack(root, "score-ack", "S1-SCORE-ACK", at, final_snapshot_sha256=bind_sha)


@pytest.mark.parametrize("case", ["report-absent", "report-hash-differs", "report-same-hash"])
def test_score_ack_issuer_reads_published_report(tmp_path, monkeypatch, case):            # row 488 (CL-A9)
    no_coordination_writes(monkeypatch)
    st_ = nvs_chain(tmp_path, snapshot=(case != "report-absent"), ack=False)
    rp = tmp_path / "s1_out" / "final_snapshot" / "report.json"
    bind = c.sha256_file(rp) if rp.is_file() else "e" * 64
    if case == "report-hash-differs":
        bind = "d" * 64                                                 # the hash the issuer meant to bind
    n0 = len(t.scan(mb(tmp_path)))
    sent = issue_score_ack(tmp_path, st_["t0"] + timedelta(days=3), bind)
    acks = t.open_trial(mb(tmp_path)).acks
    if case == "report-same-hash":
        assert sent is not None and acks["S1-SCORE-ACK"].fields["final_snapshot_sha256"] == bind
        assert len(t.scan(mb(tmp_path))) == n0 + 1
    else:
        assert sent is None and "S1-SCORE-ACK" not in acks              # no SCORE-ACK issued, nothing sent
        assert len(t.scan(mb(tmp_path))) == n0


@pytest.mark.parametrize("case", ["created-le-written", "created-gt-written"])
def test_score_ack_written_utc_lower_bound(tmp_path, monkeypatch, case):                    # row 489 (CL-A10)
    """C3.3: the S1 in-report check is a LOWER BOUND (SCORE-ACK.created > written_utc); it does not prove
    publication-before-ACK causality and is never named so."""
    st_ = nvs_chain(tmp_path, ack=False)
    rep = json.loads((tmp_path / "s1_out" / "final_snapshot" / "report.json").read_bytes())
    assert isinstance(rep.get("written_utc"), str), "the final-snapshot report has no written_utc (C3.1)"
    written = c.aware(rep["written_utc"])
    at = written if case == "created-le-written" else written + timedelta(microseconds=1)
    s1_ack(tmp_path, "score-ack", "S1-SCORE-ACK", at)
    ack = t.open_trial(mb(tmp_path)).acks["S1-SCORE-ACK"]
    with _Clock(st_["now"]):
        if case == "created-le-written":
            why = r._snapshot_lower_bound(ack, written)
            assert why is not None and "lower bound" in why and "causality" not in why
            with pytest.raises(SystemExit, match=r"lower bound") as ei:
                r.score(tmp_path, "score-ack")
            assert "causality" not in str(ei.value)
            assert j.subject_rows(jrows(tmp_path), "stage/score") == []
        else:
            assert r._snapshot_lower_bound(ack, written) is None
            rep = ok(r.score, tmp_path, "score-ack")                   # (fix round 1, M-7: it commits)
            assert (rep["verdict"], rep["classification"]) == ("NO-VALID-SEAL", "INCONCLUSIVE")
            assert j.first(j.subject_rows(jrows(tmp_path), "stage/score"), "STAGE-CREATED") is not None


def test_lower_bound_does_not_prove_publication_order(tmp_path, monkeypatch):            # row 490 (CL-A11)
    """CHARACTERIZATION (C3.1, C0 OP-2 counterexample): written_utc = 10, ACK created = 11, publication = 12. The
    lower-bound check passes, and the publication-before-ACK property is NOT proven by it."""
    st_ = nvs_chain(tmp_path, snapshot=False, ack=False)
    t10 = st_["t0"] + timedelta(days=2)
    seen = {}
    real = c.publish_text_exclusive

    def ack_between(path, text, **kw):                                  # barrier: after written_utc, before publication
        if Path(path).name == "report.json" and Path(path).parent.name == "final_snapshot":
            w = json.loads(text).get("written_utc")
            seen["has_written"] = isinstance(w, str)
            seen["written"] = c.aware(w) if seen["has_written"] else t10
            seen["ack_line"] = s1_ack(tmp_path, "score-ack", "S1-SCORE-ACK", seen["written"] + timedelta(seconds=1),
                                      final_snapshot_sha256=c.sha256_bytes(c.text_bytes(text)))
            seen["published_after_ack"] = not Path(path).exists()
        return real(path, text, **kw)
    monkeypatch.setattr(c, "publish_text_exclusive", ack_between)
    with _Clock(t10):
        ok(ck.run_final_snapshot, tmp_path, st_["ledger"].path, now=lambda: t10)
    assert seen.get("has_written") is True, "the published report carries no written_utc (C3.1)"
    ack = t.open_trial(mb(tmp_path)).acks["S1-SCORE-ACK"]
    assert r._snapshot_lower_bound(ack, seen["written"]) is None           # the lower bound passes
    assert seen["published_after_ack"] is True                              # yet the report did not exist at the ACK
