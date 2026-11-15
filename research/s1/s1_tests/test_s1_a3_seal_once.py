"""Erratum 2 Clarification 3 (SEAL-ONCE, S1-S6; sha256 fabac171...): a NEW ordinary post-START slot attempt for
registered slot s of close C is refused at the F0.5 step-5 post-START slot gate (pinned reason, no row) when the
deciding transaction's rows hold a committed SLOT-QUALIFIED of a registered slot q of the SAME close with scheduled(q) <
scheduled(s). Map rows 520-530 (row 531 is in test_s1_a3_mutants.py). t11 fixture: C = d0 2026-10-26, close 20:00Z;
slots C+45, 47, 49, 51, 53, 55, then hourly. Behavioural RED against the H5a stub (s1_evidence/a3/h5a_red.txt). Race
cases use real child processes and BEGIN IMMEDIATE arbitration with file barriers. Evidence labels per row are in the
docstrings."""
import json
import sqlite3
import os
import subprocess
import sys
import sysconfig
import time
from datetime import timedelta
from pathlib import Path

import pytest
import a3_h5a_helpers as h
import s1_checkpoint as ck
import s1_common as c
import s1_journal as j
import s1_seal as z
import s1_slot as sl
import s1_trial as t
from conftest import S1_RECEIPT, _Clock, _write_seal, s1_jappend, s1_jstage
from test_s1_a3_eligibility import PRECEDENCE, assert_precedence

START = h.START
HERE = Path(__file__).resolve().parent.parent
SEC = timedelta(seconds=1)
EXE = getattr(sys, "_base_executable", None) or sys.executable      # never the venv launcher (PS-1)


def d0_slots(st_):
    return {m: h.slot(st_, h.D0, m) for m in (45, 47, 49, 51, 53, 55, 60, 120)}


# ---------------------------------------------------------------- row 520 (SO-A1): changed, RED/GREEN
@pytest.mark.parametrize("case", ["earlier-slot-pending", "earlier-slot-unclaimed-window-open"])
def test_earlier_qualified_not_determined_refuses_later(tmp_path, monkeypatch, case):
    """q (slot 47) QUALIFIED while an earlier slot (45) is pending (INTENT, no terminal) or unclaimed with its window
    open - the close is NOT determined: a NEW attempt for a later slot (49) is refused with the pinned reason; no row,
    no claim, no capture, no callback, no QUALIFIED, no seal."""
    st_ = h.registered(tmp_path)
    s = d0_slots(st_)
    if case == "earlier-slot-pending":
        s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(s[45]), at=s[45] + SEC)
    h.qualify(tmp_path, st_, s[47])
    assert sl.determined(h.rows(tmp_path), h.day(st_, h.D0), st_["calendar"]) is None
    assert s[49] + timedelta(seconds=30) < z.eligible_until(s[45], h.day(st_, h.D0), st_["calendar"])
    w = h.Watch(monkeypatch)
    h.refuse_no_row(tmp_path, st_, s[49], s[49] + timedelta(seconds=30), h.c3_text(h.D0, s[47]), w)


# ---------------------------------------------------------------- row 521 (SO-A2): control
@pytest.mark.parametrize("case", ["earlier-attempt-allowed", "earlier-qualified-becomes-selected-seal"])
def test_earlier_slot_still_attemptable(tmp_path, case):
    """A later QUALIFIED (47) exists; a slot earlier than it (45), still inside its window: its NEW attempt is allowed,
    can QUALIFY, and becomes the selected seal (B1.4)."""
    st_ = h.registered(tmp_path)
    s = d0_slots(st_)
    h.qualify(tmp_path, st_, s[47])
    h.qualify(tmp_path, st_, s[45], s[47] + timedelta(seconds=40))
    if case == "earlier-qualified-becomes-selected-seal":
        rows_ = h.rows(tmp_path)
        q = sl.determined(rows_, h.day(st_, h.D0), st_["calendar"])
        assert q is not None and q.subject == j.slot_subject(s[45])
        assert sg_created(rows_, f"seal/{h.D0}")
        seal = json.loads((tmp_path / "s1_out" / "seals" / f"{h.D0}.json").read_text(encoding="utf-8"))
        assert seal["capture"]["scheduled"] == s[45].isoformat()


def sg_created(rows_, stage) -> bool:
    import s1_stage as sg
    return sg.stage_rows(rows_, stage)["created"] is not None


# ---------------------------------------------------------------- row 522 (SO-A3): real processes + barrier
CHILD = r'''
import json, os, sys, time
from pathlib import Path
here, root, ledger, at_iso, sch_iso, ready, go = sys.argv[1:8]
sys.path.insert(0, here); sys.path.insert(0, here + "/s1_tests")
import s1_common as c, s1_checkpoint as ck, s1_journal as j, s1_receipt
c.MAILBOX = Path(root) / "mailbox.sqlite3"
s1_receipt.HMAC_KEY = Path(root) / "s1_receipt_hmac.key"
at = c.aware(at_iso)
c.now_utc = lambda: at
real = j.append
def paused(trial_id, gen, req, ctx_fn, **kw):
    if req.kind == "SLOT-INTENT" and go != "-":            # barrier: after the gate's read, before the INTENT txn
        Path(ready + ".tmp").write_text(str(os.getpid()), encoding="ascii")      # PS-1: the child's own pid, atomically
        os.replace(ready + ".tmp", ready)
        t0 = time.time()
        while not Path(go).exists():
            if time.time() - t0 > 120:
                raise SystemExit("barrier timeout")
            time.sleep(0.05)
    return real(trial_id, gen, req, ctx_fn, **kw)
j.append = paused
from conftest import S1_RECEIPT, S1_PROCESS
try:
    ck.run_checkpoint(root, ledger, c.aware(sch_iso), lambda reference=None: S1_RECEIPT, lambda: dict(S1_PROCESS),
                      Path(root) / "crash.log", now=lambda: at, mailbox=Path(root) / "mailbox.sqlite3")
except SystemExit as e:
    print(json.dumps({"refused": str(e)}))
    sys.exit(3)
print(json.dumps({"ok": True}))
'''


def child_env() -> dict:
    """A3 H5d (PS-1): the child runs under the BASE interpreter (no venv launcher), so it cannot see the venv's
    site-packages (pytest, which conftest imports) unless PYTHONPATH names them: the product directory, the test
    directory and this interpreter's purelib, passed explicitly (no -I: -I would ignore PYTHONPATH)."""
    paths = [str(HERE), str(HERE / "s1_tests"), sysconfig.get_paths()["purelib"]]
    return dict(os.environ, PYTHONPATH=os.pathsep.join(paths), PYTHONDONTWRITEBYTECODE="1")


def child_cmd(tmp_path, st_, sch, at, ready="-", go="-"):
    script = tmp_path / "child_slot.py"
    script.write_text(CHILD, encoding="utf-8")
    return [EXE, str(script), str(HERE), str(tmp_path), str(st_["ledger"].path), at.isoformat(),
            sch.isoformat(), str(ready), str(go)]


@pytest.mark.parametrize("case", ["intent-before-q-commit-allowed", "intent-after-q-commit-refused"])
def test_transaction_barrier_around_q_commit(tmp_path, monkeypatch, case):
    """Real processes, BEGIN IMMEDIATE arbitration, file barriers. (a) slot 49's INTENT transaction (a child process)
    runs while q's worker (slot 47, this process) is paused between P and J: it precedes q's QUALIFIED commit, so it
    is allowed (and is pre-claimed under S3) - control. (b) slot 49's child passes its gate and pauses before its
    INTENT transaction; q's QUALIFIED commits; the child's transaction reads q's committed row and is refused with the
    pinned reason, no row - changed RED/GREEN."""
    st_ = h.registered(tmp_path)
    s = d0_slots(st_)
    at49 = s[49] + timedelta(seconds=30)
    if case == "intent-before-q-commit-allowed":
        seen = {}
        real = sl.Worker._append

        def paused_before_j(self, req):
            if req.kind == "SLOT-QUALIFIED" and req.subject == j.slot_subject(s[47]) and "p" not in seen:
                seen["p"] = subprocess.run(child_cmd(tmp_path, st_, s[49], at49), capture_output=True, text=True,
                                           timeout=300, env=child_env())
            return real(self, req)
        monkeypatch.setattr(sl.Worker, "_append", paused_before_j)
        h.run(tmp_path, st_, s[47], s[47] + timedelta(seconds=30))
        assert seen["p"].returncode == 0, (seen["p"].stdout, seen["p"].stderr)
        rows_ = h.rows(tmp_path)
        i49 = j.first(j.subject_rows(rows_, j.slot_subject(s[49])), "SLOT-INTENT")
        q47 = j.first(j.subject_rows(rows_, j.slot_subject(s[47])), "SLOT-QUALIFIED")
        assert i49 is not None and q47 is not None and i49.seq < q47.seq
        return
    ready, go = tmp_path / "ready.flag", tmp_path / "go.flag"
    p = subprocess.Popen(child_cmd(tmp_path, st_, s[49], at49, ready, go), stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, env=child_env())
    try:
        t0 = time.time()
        while not ready.exists():
            assert p.poll() is None, p.communicate()
            assert time.time() - t0 < 120, "the child never reached its barrier"
            time.sleep(0.05)
        got = int(ready.read_text(encoding="ascii"))            # A3 H5d (PS-1): the pid the child reports is Popen's
        assert got == p.pid, f"child pid {got} != Popen.pid {p.pid} (a launcher between them)"
        h.qualify(tmp_path, st_, s[47])                         # q commits while the child is paused
        before = h.shas(tmp_path)
        go.write_text("go", encoding="utf-8")
        out, err = p.communicate(timeout=300)
    finally:
        if p.poll() is None:
            p.kill()
    assert p.returncode == 3, (out, err)
    assert json.loads(out.strip().splitlines()[-1])["refused"] == \
        f"{j.slot_subject(s[49])}: SLOT-INTENT refused with no row: {h.c3_text(h.D0, s[47])}"
    assert h.shas(tmp_path) == before and h.kinds(tmp_path, s[49]) == [] and h.no_files(tmp_path, st_, s[49])


# ---------------------------------------------------------------- row 523 (SO-A4): control
@pytest.mark.parametrize("case", ["qualified-r-before-d", "failed", "timeout-at-d", "lost-race-after-timeout"])
def test_preclaimed_later_completions(tmp_path, monkeypatch, case):
    """A later slot (49) pre-claimed before q's (47) QUALIFIED completes under its existing rules: QUALIFIED with
    R < D, FAILED, TIMEOUT at D, or LOST-RACE for a J after the committed TIMEOUT. No completion is refused; the
    selection is unchanged."""
    st_ = h.registered(tmp_path)
    s = d0_slots(st_)
    cal, d0 = st_["calendar"], h.day(st_, h.D0)
    sub49 = j.slot_subject(s[49])
    if case in ("qualified-r-before-d", "failed"):
        real = sl.Worker.intent

        def then_q(self):
            got = real(self)
            if self.subject == sub49:                           # 49 claimed; q (47) commits during 49's work
                at47 = s[49] + timedelta(seconds=40)
                with _Clock(at47):
                    h.qualify(tmp_path, st_, s[47], at47)
            return got
        monkeypatch.setattr(sl.Worker, "intent", then_q)
        proc = None
        if case == "failed":
            def proc():
                raise RuntimeError("fixture: the process observation fails")
        h.run(tmp_path, st_, s[49], s[49] + timedelta(seconds=30), process=proc)
        rows_ = h.rows(tmp_path)
        k49 = [x for x in j.subject_rows(rows_, sub49)]
        q47 = j.first(j.subject_rows(rows_, j.slot_subject(s[47])), "SLOT-QUALIFIED")
        want = "SLOT-QUALIFIED" if case == "qualified-r-before-d" else "SLOT-FAILED"
        assert [x.kind for x in k49] == ["SLOT-INTENT", want]
        assert k49[0].seq < q47.seq < k49[1].seq
        assert h.invalids(tmp_path) == []
        return
    intent = s1_jappend(tmp_path, "SLOT-INTENT", sub49, at=s[49] + SEC)          # 49 claimed; its worker is gone
    h.qualify(tmp_path, st_, s[47], s[49] + timedelta(seconds=20))
    d49 = z.resolution_deadline(s[49], d0, cal)
    with _Clock(d49):
        ck.run_finalizer(tmp_path, now=lambda: d49, mailbox=h.mb(tmp_path))
    assert h.kinds(tmp_path, s[49]) == ["SLOT-INTENT", "SLOT-TIMEOUT"]
    q = sl.determined(h.rows(tmp_path), d0, cal)
    assert q is not None and q.subject == j.slot_subject(s[47])                  # the selection is unchanged
    if case == "lost-race-after-timeout":
        tr = t.open_trial(h.mb(tmp_path))
        ctx = t.product_context(tr, cal, slot_gate=h.gate_of(st_, trial=tr))
        res = j.append(tr.trial_id, tr.genesis, j.Request("SLOT-QUALIFIED", sub49, intent.op, intent.actor,
                                                          detail="b" * 64, r_at=s[49] + timedelta(seconds=40)),
                       ctx, mailbox=h.mb(tmp_path), clock=lambda: d49 + SEC)
        assert (res.outcome, res.row) == ("LOST-RACE", None) and "SLOT-TIMEOUT" in res.reason
        assert h.kinds(tmp_path, s[49]) == ["SLOT-INTENT", "SLOT-TIMEOUT"]
    assert h.invalids(tmp_path) == []


# ---------------------------------------------------------------- row 524 (SO-A5): characterization
@pytest.mark.parametrize("case", ["probe1-early-intent-q8", "probe2-post-first-q-earlier-claims-q5"])
def test_counterexamples_integrated(tmp_path, case):
    """Codex b4304771's probes, integrated: committed journal rows, synthetic capture fixtures, the real F0.5
    arbitration (s1_journal.append with the product Context: post-START gate and registered slot timing), worker
    pauses emulated by ordering; every capture inside its own window with R < D. Under S1 only: Q = 8 and Q = 5.
    probe1 is a HISTORICAL (pre-C4) STAGED S1-ONLY fixture: its early INTENTs at C+40 are staged legacy rows
    (s1_jstage) - under Clarification 4 no production entry point can write them (row 548). probe2 claims through the
    production Worker. Characterization only; not a capacity claim. The procedures are a3_h5a_helpers.probe1_staged_q
    (staged: s1_jstage) and probe2_q (the production Worker)."""
    st_ = h.registered(tmp_path)
    if case == "probe1-early-intent-q8":
        assert h.probe1_staged_q(tmp_path, st_) == 8
    else:
        assert h.probe2_q(tmp_path, st_) == 5


# ---------------------------------------------------------------- row 525 (SO-A6): changed, RED/GREEN
@pytest.mark.parametrize("case", ["worker-post-start-gate-later-slot-after-q"])
def test_direct_worker_entry_cannot_bypass(tmp_path, case):
    """A Worker built directly with the post-START gate, for a later slot (49) after q (47): refused, no row."""
    st_ = h.registered(tmp_path)
    s = d0_slots(st_)
    h.qualify(tmp_path, st_, s[47])
    at = s[49] + timedelta(seconds=30)
    before = h.shas(tmp_path)
    with _Clock(at):
        gv = t.gate(tmp_path, "direct worker", defer_pending=True)
        with pytest.raises(SystemExit, match=h.refused(s[49], h.c3_text(h.D0, s[47]))):
            with sl.Worker(gv, s[49], h.day(st_, h.D0), st_["calendar"],
                           slot_gate=sl.post_start_gate(gv.trial, start=c.aware(START), cal=st_["calendar"]),
                           mailbox=h.mb(tmp_path), now=lambda: at) as wk:
                wk.intent()
    assert h.shas(tmp_path) == before and h.no_files(tmp_path, st_, s[49])


# ---------------------------------------------------------------- row 526 (SO-A7): control
@pytest.mark.parametrize("case", ["scheduled-opening-close-slot-unchanged", "opening-mode-unchanged",
                                  "exact-w-l-route-unchanged"])
def test_pre_start_paths_unchanged(tmp_path, monkeypatch, case):
    """A scheduled-mode slot of the opening close after an earlier opening-close QUALIFIED: no new refusal (O-S1) -
    DECISION-LEVEL (the product slot gate and slot timing through s1_journal.decide; the same setup incompatibility as
    row 513: no registered trial reaches an unclaimed opening-close slot after its PREREG-ACK). run_opening_checkpoint
    after an earlier opening QUALIFIED (the opening stage not yet started) still captures; the exact W_L route behaves
    as before (no attempt, the stop decision)."""
    if case == "scheduled-opening-close-slot-unchanged":
        st_ = h.registered(tmp_path)
        cal, oc = st_["calendar"], st_["opening_close"]
        s45, s47 = (z.close_of(oc, cal) + timedelta(minutes=m) for m in (45, 47))
        rows_ = h.synthetic_rows([("SLOT-INTENT", j.slot_subject(s45), s45 + SEC),
                                  ("SLOT-QUALIFIED", j.slot_subject(s45), s45 + timedelta(seconds=30))])
        req = j.Request("SLOT-INTENT", j.slot_subject(s47), j.new_nonce(), j.new_nonce())
        assert j.decide(rows_, req, h.product_ctx(cal, h.gate_of(st_)), s47 + timedelta(seconds=30)) == \
            j.Decision("APPEND")
        return
    if case == "opening-mode-unchanged":
        from test_s1_a3_prestart import opened, opening_slot
        real = ck._opening_stage
        monkeypatch.setattr(ck, "_opening_stage", lambda *a, **kw: {"deferred": "fixture: the worker crashed before "
                                                                               "the opening stage"})
        start, cal, oc, lg, rep = opened(tmp_path)
        s45, s47 = opening_slot(cal, oc, 45), opening_slot(cal, oc, 47)
        assert [x.kind for x in j.subject_rows(h.rows(tmp_path), j.slot_subject(s45))] == ["SLOT-INTENT",
                                                                                           "SLOT-QUALIFIED"]
        monkeypatch.setattr(ck, "_opening_stage", real)
        at = s47 + timedelta(seconds=30)
        with _Clock(at):
            got = ck.run_opening_checkpoint(tmp_path, lg.path, s47, lambda reference=None: S1_RECEIPT,
                                            lambda: dict(h.S1_PROCESS), tmp_path / "c.log", now=lambda: at)
        assert [x.kind for x in j.subject_rows(h.rows(tmp_path), j.slot_subject(s47))] == ["SLOT-INTENT",
                                                                                           "SLOT-QUALIFIED"]
        assert got["seal"]["written"] is True and got["seal"]["from_slot"] == s45.isoformat()
        return
    from test_s1_a3_stop import _sealed_last_close
    st_ = _sealed_last_close(tmp_path)
    w = h.Watch(monkeypatch)
    got = h.run(tmp_path, st_, h.W_L, h.W_L + timedelta(hours=1), receipt=w.receipt(), process=w.process())
    assert got["route"] == "w-last" and got["stop"]["status"] == "TIMEOUT"
    assert "SLOT-INTENT" not in h.kinds(tmp_path, h.W_L)
    w.sp.assert_zero()


# ---------------------------------------------------------------- row 527 (SO-A8)
SEAL_ONCE_PRECEDENCE = dict(PRECEDENCE, **{"prereg-missing-first": r"no S1-PREREG-ACK: no post-START capture",
                                           "c2-post-deadline-reason-first": None})


@pytest.mark.parametrize("case", list(SEAL_ONCE_PRECEDENCE))
def test_precedence_preserved(tmp_path, monkeypatch, case):
    """With q (47) QUALIFIED, an invocation of a later slot (49): every higher-precedence outcome keeps its outcome and
    row; the Clarification 3 reason never replaces it (controls). A post-deadline close (d130) with an earlier
    (legacy) QUALIFIED gets Clarification 2's reason (changed RED/GREEN)."""
    st_ = h.registered(tmp_path)
    if case == "c2-post-deadline-reason-first":
        cal = st_["calendar"]
        cl = z.close_of(h.D130, cal)
        _write_seal(tmp_path / "s1_out", h.D130, cl, [], S1_RECEIPT, start=c.aware(START),
                    opening_close=z.close_of(st_["opening_close"], cal), with_stage=False)   # legacy d130 :45 QUALIFIED
        s47 = cl + timedelta(minutes=47)
        h.refuse_no_row(tmp_path, st_, s47, s47 + timedelta(seconds=30), h.c2_text(h.D130), h.Watch(monkeypatch))
        return
    s = d0_slots(st_)
    h.qualify(tmp_path, st_, s[47])
    at = s[49] + timedelta(seconds=30)
    if case == "prereg-missing-first":
        con = sqlite3.connect(h.mb(tmp_path))
        con.execute("DELETE FROM messages WHERE id='prereg-ack'")
        con.commit()
        con.close()
        before = h.shas(tmp_path)
        with pytest.raises(SystemExit, match=h.refused(s[49], "no S1-PREREG-ACK: no post-START capture (F7.4)")):
            h.run(tmp_path, st_, s[49], at)
        assert h.shas(tmp_path) == before
        return
    assert_precedence(tmp_path, monkeypatch, st_, case, s[49], at)


# ---------------------------------------------------------------- row 528 (SO-A9): control
@pytest.mark.parametrize("case", ["multi-qualified-all-trees-hashed", "damaged-non-selected-tree-invalid",
                                  "damaged-q-tree-integrity-not-ignored", "no-new-invalid-from-legacy"])
def test_retained_evidence_verified(tmp_path, monkeypatch, case):
    """Every retained QUALIFIED tree is hashed each pass; damage to a non-selected tree, or to q, gets the existing F3
    handling (TRIAL-INVALID registration-artifact; q is never ignored to resume captures); a legacy multi-QUALIFIED
    close (synthetic history) causes no new INVALID."""
    st_ = h.registered(tmp_path)
    s = d0_slots(st_)
    out = tmp_path / "s1_out"
    if case == "no-new-invalid-from-legacy":
        cal = st_["calendar"]
        cl, oc = z.close_of(h.D0, cal), z.close_of(st_["opening_close"], cal)
        _write_seal(out, h.D0, cl, [], S1_RECEIPT, start=c.aware(START), opening_close=oc, with_stage=False)
        _write_seal(out, h.D0, cl, [], S1_RECEIPT, start=c.aware(START), opening_close=oc, minutes=47)
        assert h.qualified_count(tmp_path, h.day(st_, h.D0), cal) == 2
        before = h.shas(tmp_path)
        t.gate(tmp_path, "legacy multi-QUALIFIED")
        assert h.shas(tmp_path) == before and h.invalids(tmp_path) == []
        return
    h.qualify(tmp_path, st_, s[47])
    if case != "damaged-q-tree-integrity-not-ignored":
        h.qualify(tmp_path, st_, s[45], s[47] + timedelta(seconds=40))         # 45 is selected; 47 is not
    if case == "multi-qualified-all-trees-hashed":
        hashed = []
        real = sl._qualified_manifest
        monkeypatch.setattr(sl, "_qualified_manifest", lambda out_, s_, d_, sub, ps: hashed.append(sub) or
                            real(out_, s_, d_, sub, ps))
        t.gate(tmp_path, "every tree")
        assert {j.slot_subject(s[45]), j.slot_subject(s[47])} <= set(hashed)
        return
    rep = sl.names(out, s[47], h.D0)["report"]
    rep.write_text(rep.read_text(encoding="utf-8") + " ", encoding="utf-8")
    target = s[49] if case == "damaged-q-tree-integrity-not-ignored" else s[51]
    with pytest.raises(SystemExit, match=r"slot evidence violation .*INVALID \(registration-artifact\)"):
        h.run(tmp_path, st_, target, target + timedelta(seconds=30))
    assert h.invalids(tmp_path) == ["reason/registration-artifact"]
    assert h.kinds(tmp_path, target) == [] and rep.is_file()


# ---------------------------------------------------------------- row 529 (SO-A10)
def lots_stop_d0():
    return [{"symbol": f"S{i % 5}", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (0, 80.0)} for i in range(100)]


@pytest.mark.parametrize("case", ["refusal-runs-no-finalizer", "next-close-worker-recovers", "run-finalizer-recovers"])
def test_no_refusal_triggered_finalizer(tmp_path, monkeypatch, case):
    """A refused attempt runs zero _after_terminal / finalizer / decide_stop (changed RED/GREEN). After a determining
    worker's crash (slot 45 QUALIFIED, crashed before its post-terminal work), the next close's worker or run_finalizer
    creates seal/<C> and commits the STOP record: rule, status, stop close, stop seal and cohort are the same either
    way; its sampled-history prefix may differ (Clarification 3 S5.2, OQ-29). Dispatch is R-3, not proven (controls)."""
    if case == "refusal-runs-no-finalizer":
        st_ = h.registered(tmp_path)
        s = d0_slots(st_)
        h.qualify(tmp_path, st_, s[47])
        w = h.Watch(monkeypatch)
        got = h.attempt(h.run, tmp_path, st_, s[49], s[49] + timedelta(seconds=30))
        assert got == ("refused", f"{j.slot_subject(s[49])}: SLOT-INTENT refused with no row: "   # H5c (H5a M-2)
                                  f"{h.c3_text(h.D0, s[47])}"), got
        assert w.calls == [] and w.written() == [], (w.calls, w.appends)
        return
    st_ = h.registered(tmp_path, score_ready=True, lots=lots_stop_d0(), seal_days=[])
    s = d0_slots(st_)
    real = ck._after_terminal

    def crash(*a, **kw):
        raise SystemExit("fixture: the determining worker crashed before its post-terminal work")
    monkeypatch.setattr(ck, "_after_terminal", crash)
    with pytest.raises(SystemExit, match="fixture: the determining worker crashed"):
        h.run(tmp_path, st_, s[45], s[45] + timedelta(seconds=30))
    monkeypatch.setattr(ck, "_after_terminal", real)
    assert h.kinds(tmp_path, s[45]) == ["SLOT-INTENT", "SLOT-QUALIFIED"]
    assert j.first(h.rows(tmp_path), "TRIAL-STOP") is None and not sg_created(h.rows(tmp_path), f"seal/{h.D0}")
    s1_45 = h.slot(st_, h.D1)
    if case == "next-close-worker-recovers":
        h.run(tmp_path, st_, s1_45, s1_45 + timedelta(seconds=30))
    else:
        at = s1_45 + timedelta(seconds=30)
        with _Clock(at):
            ck.run_finalizer(tmp_path, now=lambda: at, mailbox=h.mb(tmp_path))
    rows_ = h.rows(tmp_path)
    assert sg_created(rows_, f"seal/{h.D0}")
    seal = json.loads((tmp_path / "s1_out" / "seals" / f"{h.D0}.json").read_text(encoding="utf-8"))
    assert seal["capture"]["scheduled"] == s[45].isoformat()
    stop = j.first(rows_, "TRIAL-STOP")
    assert stop is not None
    rec = json.loads((tmp_path / "s1_out" / "stop.json").read_text(encoding="utf-8"))
    assert j.detail_of(rec) == stop.detail
    assert (rec["rule"], rec["status"], rec["stop_close"], rec["stop_seal"], rec["lots"]) == (
        "lots", "STOPPED", "2026-10-26T20:00:00+00:00", "seals/2026-10-26.json", {"sold": 100, "cohort": 100})


# ---------------------------------------------------------------- row 530 (SO-A11)
@pytest.mark.parametrize("case", ["unknown-mapping-fails-closed", "registered-instant-not-commit-order",
                                  "other-close-qualified-ignored"])
def test_predicate_mapping(tmp_path, case):
    """An unknown/invalid mapping of a committed QUALIFIED being judged keeps the fail-closed classification (the
    registered-slot refusal, never "no earlier q") - GATE-LEVEL (the evidence table would already INVALIDATE such a row
    at the trial gate); the comparison uses scheduled instants (a q committed later in the journal but scheduled
    earlier still refuses s) - end-to-end; both changed RED/GREEN. A QUALIFIED of another close never refuses
    (control)."""
    st_ = h.registered(tmp_path)
    s = d0_slots(st_)
    if case == "unknown-mapping-fails-closed":
        odd = h.slot(st_, h.D0, 46)                                   # between C and s49, not a registered slot
        rows_ = h.synthetic_rows([("SLOT-INTENT", j.slot_subject(odd), odd + SEC),
                                  ("SLOT-QUALIFIED", j.slot_subject(odd), odd + timedelta(seconds=30))])
        with pytest.raises(SystemExit, match=r"is not a registered seal slot"):
            h.gate_of(st_)(rows_, j.slot_subject(s[49]))
        return
    if case == "registered-instant-not-commit-order":
        h.qualify(tmp_path, st_, s[49])
        h.qualify(tmp_path, st_, s[45], s[49] + timedelta(seconds=40))        # committed later, scheduled earlier
        q45 = j.first(j.subject_rows(h.rows(tmp_path), j.slot_subject(s[45])), "SLOT-QUALIFIED")
        q49 = j.first(j.subject_rows(h.rows(tmp_path), j.slot_subject(s[49])), "SLOT-QUALIFIED")
        assert q49.seq < q45.seq
        h.refuse_no_row(tmp_path, st_, s[47], s[49] + timedelta(seconds=50), h.c3_text(h.D0, s[45]))
        return
    h.qualify(tmp_path, st_, s[45])
    d1_45 = h.slot(st_, h.D1)
    h.qualify(tmp_path, st_, d1_45)
