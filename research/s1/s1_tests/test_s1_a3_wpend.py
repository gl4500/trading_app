"""Erratum 2 r4 G2 (R3-WPEND-1; O6, O7, O8; E2-C1, E2-C2): the exact W_L invocation routes to the provider-free
finalizer + stop decision at any clock, with the command's clock callable; the --finalize catch-up at/after every
outstanding D; the frozen s1_checkpoint wrappers are retired. t11 fixture: L = 2027-04-23 (d129), W_L =
slot/20270426T120000Z, D(W_L) = 2027-04-26T12:30:00Z. Map rows 410-426; T11 N1. Behavioural RED against the H3 stub
(s1_evidence/a3/h3_red.txt)."""
import ast
import json
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
import a3_helpers as h
import s1_checkpoint as ck
import s1_common as c
import s1_journal as j
import s1_seal as z
import s1_slot as sl
import s1_trial as t
from conftest import (S1_PROCESS, S1_RECEIPT, Spies, _Clock, s1_ack, s1_close_out, s1_jappend,  # noqa: F401
                      s1_mailbox_init, s1_state)

START = "2026-10-26T13:30:00+00:00"
HERE = Path(__file__).resolve().parent.parent
W_L = c.aware("2027-04-26T12:00:00+00:00")
D_L = W_L + timedelta(minutes=30)
W_SUB = "slot/20270426T120000Z"
D129 = "2027-04-23"


def mb(root):
    return Path(root) / "mailbox.sqlite3"


def jrows(root):
    trs = t.trials(t.scan(mb(root)))
    (tid,) = [x for x, tr_ in trs.items() if tr_.closed is None]
    return j.read_trial(tid, trs[tid].genesis, mb(root))


def kinds(root, subject):
    return [x.kind for x in j.subject_rows(jrows(root), subject)]


def stops(root):
    return [x for x in jrows(root) if x.kind == "TRIAL-STOP"]


def ok(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except SystemExit as e:
        pytest.fail(f"{getattr(fn, '__name__', fn)} refused: {e}")


def history(tmp_path, case="no-valid-seal", *, early_intent=False):
    """G2.4 histories. case 'no-valid-seal' (no seals) or 'timeout-last-sealed' (row-302 seals) or 'lots-earliest'
    (row 300). No d129 slot row unless `early_intent` (a W_L INTENT at 11:59:50Z; its worker is gone)."""
    st_ = s1_state(tmp_path, START, score_ready=True, stop=False,
                   **{"no-valid-seal": dict(lots=[], seal_days=[]),
                      "timeout-last-sealed": dict(lots=h._lots(100, lambda i: (1, 80.0) if i < 99 else None),
                                                  seal_days=[0, 1, 2]),
                      "lots-earliest": dict(seal_days=[0, 1])}[case])
    if early_intent:
        s1_jappend(tmp_path, "SLOT-INTENT", W_SUB, at=W_L - timedelta(seconds=10))
    return st_


def route(tmp_path, st_, at, *, sp=None, clock=None):
    sp = sp or Spies.__new__(Spies)
    return ck.run_checkpoint(tmp_path, st_["ledger"].path, W_L, lambda reference=None: S1_RECEIPT,
                             lambda: dict(S1_PROCESS), tmp_path / "c.log", now=clock or (lambda: at),
                             mailbox=mb(tmp_path))


def catchup(tmp_path, at, clock=None):
    return ck.run_finalizer(tmp_path, now=clock or (lambda: at), mailbox=mb(tmp_path))


def test_w_last_route_pins_clock_and_no_live_callback(tmp_path, monkeypatch):               # row 410 (R3-A1)
    st_ = history(tmp_path, early_intent=True)
    sp = Spies(monkeypatch)
    seen = []
    for name in ("_finalize_others", "_finalize_last_if_due"):
        real = getattr(ck, name)
        monkeypatch.setattr(ck, name, lambda *a, _r=real, _n=name, **kw: seen.append((_n, a[4] if _n ==
                            "_finalize_others" else a[3])) or _r(*a, **kw))
    real_ds = z.decide_stop
    monkeypatch.setattr(z, "decide_stop", lambda gv, cal, start, now, **kw: seen.append(("decide_stop", now))
                        or real_ds(gv, cal, start, now, **kw))
    clk = lambda: D_L                                                         # noqa: E731 - identity is the oracle
    with _Clock(D_L):
        ok(ck.run_checkpoint, tmp_path, st_["ledger"].path, W_L, sp.receipt(), sp.process(), tmp_path / "c.log",
           now=clk, mailbox=mb(tmp_path))
    assert [n for n, _ in seen] == ["_finalize_others", "_finalize_last_if_due", "decide_stop"]
    assert all(x is clk for _, x in seen)                                      # no wrapper, no fixed lambda
    sp.assert_zero()                                                           # no receipt/process/capture/HTTP


IDENTITY = {"no-trial": r"zero open trials", "forged-auth": r"RUN-ACK does not verify \(forged\)",
            "registered-bundle-changed": r"bundle", "invalid": r"trial INVALID \(reason/stage-replaced\)",
            "closed": r"zero open trials", "registration-artifact": r"registration artifact",
            "unregistered-slot": r"is not a registered seal slot"}


@pytest.mark.parametrize("case", ["no-trial", "forged-auth", "registered-bundle-changed", "invalid", "closed",
                                  "registration-artifact", "unregistered-slot"])
def test_w_last_route_identity_first(tmp_path, monkeypatch, case):                          # row 411 (R3-A2)
    st_ = history(tmp_path, early_intent=True)
    sch, before = W_L, [x.sha for x in jrows(tmp_path)]
    if case == "no-trial":
        import sqlite3
        con = sqlite3.connect(mb(tmp_path))
        con.execute("DELETE FROM messages WHERE body LIKE 'S1-AUDIT-ACK %'")
        con.commit()
        con.close()
    elif case == "forged-auth":
        monkeypatch.setattr(ck.g, "verified_registration", lambda *a, **kw: (_ for _ in ()).throw(
            SystemExit("checkpoint refused: RUN-ACK does not verify (forged)")))
    elif case == "registered-bundle-changed":
        monkeypatch.setattr(c, "bundle_sha256", lambda: "f" * 64)
    elif case == "invalid":
        s1_jappend(tmp_path, "TRIAL-INVALID", "reason/stage-replaced", at=W_L, detail="a" * 64)
        before = [x.sha for x in jrows(tmp_path)]
    elif case == "closed":
        s1_ack(tmp_path, "close", "S1-CLOSE-ACK", W_L, reason="WITHDRAWN", evidence_sha256="0" * 64)
    elif case == "registration-artifact":                                  # (H3 deviation 2: attest_start.json is a
        (tmp_path / "s1_out" / "registry" / "prereg.json").unlink()        # stage member since Task 10 -> F4 stage-
        #                         replaced; the legacy-only registration record is decided by the legacy detector)
    else:
        sch = W_L + timedelta(minutes=7)                                       # not a registered seal slot
    calls = []
    for name in ("_finalize_others", "_finalize_last_if_due"):
        monkeypatch.setattr(ck, name, lambda *a, _n=name, **kw: calls.append(_n))
    monkeypatch.setattr(z, "decide_stop", lambda *a, **kw: calls.append("decide_stop"))
    sp = Spies(monkeypatch)
    with _Clock(D_L), pytest.raises(SystemExit, match=IDENTITY[case]):
        ck.run_checkpoint(tmp_path, st_["ledger"].path, sch, sp.receipt(), sp.process(), tmp_path / "c.log",
                          now=lambda: D_L, mailbox=mb(tmp_path))
    assert calls == []
    sp.assert_zero()
    if case in ("no-trial", "closed"):
        return
    new = [x for x in jrows(tmp_path) if x.sha not in before]
    want = {"registered-bundle-changed": ["reason/bundle"],
            "registration-artifact": ["reason/registration-artifact"]}.get(case, [])
    assert [x.subject for x in new] == want                                  # required INVALID, else no row
    assert all(x.kind == "TRIAL-INVALID" for x in new)                         # never a SLOT/STOP/stage row


@pytest.mark.parametrize("case", ["non-w-after-e", "injected-systemexit"])
def test_refusals_never_become_finalization(tmp_path, monkeypatch, case):                    # row 412 (R3-A3)
    st_ = history(tmp_path, early_intent=True)
    calls = []
    for name in ("_finalize_others", "_finalize_last_if_due"):
        monkeypatch.setattr(ck, name, lambda *a, _n=name, **kw: calls.append(_n))
    monkeypatch.setattr(z, "decide_stop", lambda *a, **kw: calls.append("decide_stop"))
    sch = W_L - timedelta(hours=1)                                             # d129's previous slot (07:00 NY)
    if case == "injected-systemexit":
        sch = W_L
        monkeypatch.setattr(ck, "_close_for", lambda *a, **kw: (_ for _ in ()).throw(SystemExit("injected")))
    before = len(jrows(tmp_path))
    with _Clock(D_L), pytest.raises(SystemExit, match={"non-w-after-e": r"now >= E",
                                                       "injected-systemexit": r"^injected$"}[case]):
        ck.run_checkpoint(tmp_path, st_["ledger"].path, sch, lambda reference=None: S1_RECEIPT,
                          lambda: dict(S1_PROCESS), tmp_path / "c.log", now=lambda: D_L, mailbox=mb(tmp_path))
    assert calls == [] and len(jrows(tmp_path)) == before


@pytest.mark.parametrize("case", ["route-at-w", "catchup-at-d-minus-1us"])
def test_before_d_no_timeout(tmp_path, case):                                               # row 413 (R3-A4)
    st_ = history(tmp_path, early_intent=True)
    with _Clock(W_L):
        ok(route, tmp_path, st_, W_L)
    if case == "catchup-at-d-minus-1us":
        at = D_L - timedelta(microseconds=1)
        with _Clock(at):
            ok(catchup, tmp_path, at)
    assert kinds(tmp_path, W_SUB) == ["SLOT-INTENT"] and stops(tmp_path) == []
    others = [s for s in z.schedule(next(d for d in st_["calendar"] if d["date"] == D129), st_["calendar"])
              if j.slot_subject(s) != W_SUB]
    assert len(others) == 69 and all(kinds(tmp_path, j.slot_subject(s)) == ["SLOT-MISSED"] for s in others)


@pytest.mark.parametrize("variant", ["nvs", "timeout"])
def test_at_d_timeout_then_stop(tmp_path, variant):                                          # row 414 (R3-A5)
    st_ = history(tmp_path, "no-valid-seal" if variant == "nvs" else "timeout-last-sealed", early_intent=True)
    with _Clock(D_L):
        ok(catchup, tmp_path, D_L)
    rows = jrows(tmp_path)
    w = j.subject_rows(rows, W_SUB)
    assert [x.kind for x in w] == ["SLOT-INTENT", "SLOT-TIMEOUT"] and w[1].op == w[0].op and w[1].actor != w[0].actor
    (stop,) = stops(tmp_path)
    rec = json.loads((tmp_path / "s1_out" / "stop.json").read_bytes())
    assert rec["status"] == {"nvs": "NO-VALID-SEAL", "timeout": "TIMEOUT"}[variant]
    assert c.aware(stop.at) >= W_L and stop.seq > w[1].seq


HOLDER = r'''
import sys
sys.path.insert(0, sys.argv[1])
import s1_locks as L, s1_trial as t, s1_common as c
from pathlib import Path
c.MAILBOX = Path(sys.argv[2]) / "mailbox.sqlite3"
tr = t.open_trial()
lk = L.OwnershipLock(sys.argv[2], tr.trial_id, L.slot_lock_name(sys.argv[3])).acquire()
print("held", flush=True)
sys.stdin.readline()
'''


def test_held_worker_cannot_block_timeout(tmp_path):                                         # row 415 (R3-A6)
    """A real child process holds slot-<W_L> past D (E1.2): TIMEOUT and STOP still commit; cleanup is deferred
    (E1.4); the child's later completion is LOST-RACE (E1.3), no INVALID, none of its files moved while it lives."""
    st_ = history(tmp_path, early_intent=True)
    p = subprocess.Popen([sys.executable, "-I", "-c", HOLDER, str(HERE), str(tmp_path), W_SUB],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline().strip() == "held"
        at = D_L + timedelta(minutes=1)
        with _Clock(at):
            got = ok(catchup, tmp_path, at)
        assert kinds(tmp_path, W_SUB) == ["SLOT-INTENT", "SLOT-TIMEOUT"] and len(stops(tmp_path)) == 1
        assert not (tmp_path / "s1_out" / "late").exists()                    # cleanup deferred while held
        intent = j.first(j.subject_rows(jrows(tmp_path), W_SUB), "SLOT-INTENT")
        tr = t.open_trial(mb(tmp_path))
        late = j.append(tr.trial_id, tr.genesis, j.Request("SLOT-FAILED", W_SUB, intent.op, intent.actor,
                                                           detail="1" * 64),
                        t.product_context(tr, st_["calendar"], slot_gate=lambda rows, s: None),
                        mailbox=mb(tmp_path), clock=lambda: at + timedelta(minutes=1))
        assert late.outcome == "LOST-RACE"
        assert all(x.kind != "TRIAL-INVALID" for x in jrows(tmp_path)) and got["mode"] == "finalize"
    finally:
        p.stdin.close()
        p.wait(timeout=60)


@pytest.mark.parametrize("case", ["no-due-rows", "post-stop-timeout"])
def test_repeat_invocations_idempotent(tmp_path, case):                                      # row 416 (R3-A7)
    if case == "no-due-rows":
        st_ = history(tmp_path, early_intent=True)
        at = D_L
    else:                                                                  # history G2.4(b)
        st_ = history(tmp_path, "lots-earliest", early_intent=True)
        with _Clock(W_L):
            ok(route, tmp_path, st_, W_L)                                   # the d1 lots STOP commits here
        assert len(stops(tmp_path)) == 1
        at = D_L
    first_stop = None
    for i, fn in enumerate([route, catchup, route, catchup]):               # two routes, two catch-ups, interleaved
        when = at + timedelta(seconds=i)
        with _Clock(when):
            ok(fn, tmp_path, st_, when) if fn is route else ok(fn, tmp_path, when)
        if first_stop is None and stops(tmp_path):
            first_stop = (len(jrows(tmp_path)), (tmp_path / "s1_out" / "stop.json").read_bytes())
    assert len(stops(tmp_path)) == 1
    assert kinds(tmp_path, W_SUB).count("SLOT-TIMEOUT") == 1
    assert (tmp_path / "s1_out" / "stop.json").read_bytes() == first_stop[1]
    if case == "no-due-rows":
        assert len(jrows(tmp_path)) == first_stop[0]                        # no row after the first STOP


@pytest.mark.parametrize("case", ["no-intent", "early-intent"])
def test_missed_w_dispatch_catchup(tmp_path, case):                                          # row 417 (R3-A8)
    st_ = history(tmp_path, early_intent=(case == "early-intent"))
    at = W_L + timedelta(hours=3)
    with _Clock(at):
        ok(catchup, tmp_path, at)
    want = ["SLOT-MISSED"] if case == "no-intent" else ["SLOT-INTENT", "SLOT-TIMEOUT"]
    assert kinds(tmp_path, W_SUB) == want and len(stops(tmp_path)) == 1


def test_early_claim_restart_refusal(tmp_path, monkeypatch):                               # row 418 (R3-A9)
    st_ = history(tmp_path, early_intent=True)
    with _Clock(W_L):
        ok(route, tmp_path, st_, W_L)
    assert kinds(tmp_path, W_SUB) == ["SLOT-INTENT"]                       # no second INTENT, no repeat-attempt
    assert all(x.kind != "TRIAL-INVALID" for x in jrows(tmp_path))
    gv = t.gate(tmp_path, "restart", defer_pending=True)                    # UNIT: a restarted W_L worker (OP-11)
    day = next(d for d in st_["calendar"] if d["date"] == D129)
    with _Clock(W_L - timedelta(seconds=5)), pytest.raises(SystemExit, match=r"a restart never re-intents"):
        with sl.Worker(gv, W_L, day, st_["calendar"], slot_gate=sl.post_start_gate(gv.trial), mailbox=mb(tmp_path),
                       now=lambda: W_L - timedelta(seconds=5)) as w:
            w.intent()


class _Advancing:
    def __init__(self, t0):
        self.t = t0

    def __call__(self):
        self.t = self.t + timedelta(milliseconds=7)
        return self.t


def test_late_scheduler_invocation(tmp_path):                                               # row 419 (R3-A10)
    st_ = history(tmp_path, early_intent=True)
    clk = _Advancing(W_L + timedelta(minutes=40))
    ok(route, tmp_path, st_, None, clock=clk)
    rows = jrows(tmp_path)
    w = j.subject_rows(rows, W_SUB)
    (stop,) = stops(tmp_path)
    assert [x.kind for x in w] == ["SLOT-INTENT", "SLOT-TIMEOUT"]
    ats = [c.aware(x.at) for x in rows if x.seq >= w[1].seq]
    assert ats == sorted(ats) and len(set(ats)) == len(ats)                  # each `at` = its transaction's sample
    assert c.aware(stop.at) > c.aware(w[1].at)


def test_no_window_extension(tmp_path, monkeypatch):                                         # row 420 (R3-A11)
    st_ = history(tmp_path)
    day = next(d for d in st_["calendar"] if d["date"] == D129)
    ordinary = z.schedule(day, st_["calendar"])[-2]                        # an L slot that is not W_L
    e = z.eligible_until(ordinary, day, st_["calendar"])
    sp = Spies(monkeypatch)
    with _Clock(e), pytest.raises(SystemExit, match=r"now >= E"):
        ck.run_checkpoint(tmp_path, st_["ledger"].path, ordinary, sp.receipt(), sp.process(), tmp_path / "c.log",
                          now=lambda: e, mailbox=mb(tmp_path))
    assert kinds(tmp_path, j.slot_subject(ordinary)) == [] and sp.n["capture"] == 0
    with _Clock(W_L):
        ok(ck.run_checkpoint, tmp_path, st_["ledger"].path, W_L, sp.receipt(), sp.process(), tmp_path / "c.log",
           now=lambda: W_L, mailbox=mb(tmp_path))                          # exempt: due rows only, never a capture
    assert sp.n["capture"] == 0 and kinds(tmp_path, W_SUB) in (["SLOT-MISSED"], [])
    assert [d["date"] for d in z.eligible_sessions(c.aware(START), st_["calendar"])][-1] == D129   # d130 never


def test_early_w_last_route_no_attempt(tmp_path, monkeypatch):                              # row 421 (R3-A12)
    st_ = history(tmp_path)
    sp = Spies(monkeypatch)
    at = W_L - timedelta(seconds=10)
    with _Clock(at):
        ok(ck.run_checkpoint, tmp_path, st_["ledger"].path, W_L, sp.receipt(), sp.process(), tmp_path / "c.log",
           now=lambda: at, mailbox=mb(tmp_path))
    assert kinds(tmp_path, W_SUB) == [] and stops(tmp_path) == []
    n = sl.names(tmp_path / "s1_out", W_L, D129)
    assert not n["claim"].exists() and not n["capture"].exists()
    sp.assert_zero()


def test_ordinary_early_slot_oq33_unchanged(tmp_path, monkeypatch):                         # row 422 (R3-A13)
    st_ = history(tmp_path)
    day = next(d for d in st_["calendar"] if d["date"] == "2026-10-26")
    s = z.schedule(day, st_["calendar"])[0]
    at = s - timedelta(seconds=10)
    with _Clock(at):
        got = ck.run_checkpoint(tmp_path, st_["ledger"].path, s, lambda reference=None: S1_RECEIPT,
                                lambda: dict(S1_PROCESS), tmp_path / "c.log", now=lambda: at, mailbox=mb(tmp_path))
    assert kinds(tmp_path, j.slot_subject(s)) == ["SLOT-INTENT", "SLOT-FAILED"] and got.get("refused")


def test_earlier_lots_stop_with_pending_w_last(tmp_path):                                   # row 423 (R3-A14)
    st_ = history(tmp_path, "lots-earliest", early_intent=True)
    at0 = c.aware("2026-10-28T13:00:00+00:00")                              # the d1 lots stop is ready (row 300)
    with _Clock(at0):
        ok(catchup, tmp_path, at0)
    (stop,) = stops(tmp_path)
    rec0 = (tmp_path / "s1_out" / "stop.json").read_bytes()
    assert json.loads(rec0)["status"] == "STOPPED" and kinds(tmp_path, W_SUB) == ["SLOT-INTENT"]
    with _Clock(D_L):
        ok(catchup, tmp_path, D_L)
    w = j.subject_rows(jrows(tmp_path), W_SUB)
    assert [x.kind for x in w] == ["SLOT-INTENT", "SLOT-TIMEOUT"] and w[1].seq > stop.seq   # one post-STOP TIMEOUT
    assert len(stops(tmp_path)) == 1 and (tmp_path / "s1_out" / "stop.json").read_bytes() == rec0
    hist = z.sampled_history(jrows(tmp_path), stop, z.sampled_seals(tmp_path / "s1_out", jrows(tmp_path),
                             st_["calendar"], c.aware(START), upto_seq=stop.seq))
    assert w[1].sha not in hist["rows"]                                    # never sampled history (F1)


def test_pre_stop_intent_late_completion(tmp_path):                                         # row 424 (R3-A15)
    st_ = history(tmp_path, "lots-earliest", early_intent=True)
    at0 = c.aware("2026-10-28T13:00:00+00:00")
    with _Clock(at0):
        ok(catchup, tmp_path, at0)
    (stop,) = stops(tmp_path)
    intent = j.first(j.subject_rows(jrows(tmp_path), W_SUB), "SLOT-INTENT")
    tr = t.open_trial(mb(tmp_path))
    ctx = t.product_context(tr, st_["calendar"], slot_gate=lambda rows, s: None)
    done = j.append(tr.trial_id, tr.genesis, j.Request("SLOT-FAILED", W_SUB, intent.op, intent.actor,
                                                       detail="1" * 64), ctx, mailbox=mb(tmp_path),
                    clock=lambda: D_L - timedelta(minutes=1))
    assert done.outcome == "APPEND" and done.row.seq > stop.seq            # a pre-STOP INTENT completes (F1)
    other = j.slot_subject(z.schedule(next(d for d in st_["calendar"] if d["date"] == "2026-10-29"),
                                      st_["calendar"])[0])
    new = j.append(tr.trial_id, tr.genesis, j.Request("SLOT-INTENT", other, j.new_nonce(), j.new_nonce()), ctx,
                   mailbox=mb(tmp_path), clock=lambda: D_L - timedelta(minutes=1))
    assert new.outcome == "LOST-RACE"
    assert (tmp_path / "s1_out" / "stop.json").read_bytes() and len(stops(tmp_path)) == 1


@pytest.mark.parametrize("cmd", ["route", "finalizer"])
def test_local_abort_refuses_route_and_finalizer(tmp_path, monkeypatch, cmd):              # row 425 (R3-A16)
    """(a) a witness present before the command: the gate's G6 recording refuses (H1); (b) a witness appearing after
    the gate (injected): the command's own _no_local_abort refuses (OP-12). Zero finalizer/stop work in both."""
    for sub in ("before", "after-gate"):
        root = tmp_path / sub
        root.mkdir()
        monkeypatch.setattr(c, "MAILBOX", s1_mailbox_init(root))   # (H3 deviation 3: c.MAILBOX per sub-root)
        st_ = history(root, early_intent=True)
        calls = []
        for name in ("_finalize_others", "_finalize_last_if_due"):
            monkeypatch.setattr(ck, name, lambda *a, _n=name, **kw: calls.append(_n))
        monkeypatch.setattr(z, "decide_stop", lambda *a, **kw: calls.append("decide_stop"))
        w = root / "s1_out" / "aborted.json"
        if sub == "before":
            w.write_text(json.dumps({"reason": "x"}), encoding="utf-8")
        else:
            real_gate = t.gate
            def gate_then_witness(*a, **kw):
                gv = real_gate(*a, **kw)
                w.write_text(json.dumps({"reason": "x"}), encoding="utf-8")
                return gv
            monkeypatch.setattr(t, "gate", gate_then_witness)
        with _Clock(D_L), pytest.raises(SystemExit, match=r"aborted\.json|established-violation"):
            route(root, st_, D_L) if cmd == "route" else catchup(root, D_L)
        monkeypatch.setattr(t, "gate", t.gate if sub == "before" else real_gate)
        assert calls == []
        assert all(x.kind not in ("SLOT-TIMEOUT", "SLOT-MISSED", "TRIAL-STOP") for x in jrows(root)
                   if x.subject in (W_SUB, "trial"))


def test_frozen_wrappers_retired(tmp_path):                                                 # row 426 (R3-A17)
    assert not hasattr(ck, "finalize_close") and not hasattr(ck, "finalize_pending")
    assert callable(sl.finalize_close)
    for p in sorted(HERE.glob("*.py")) + sorted((HERE / "s1_tests").glob("*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        names = {(ast.unparse(n.value), n.attr) for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert not names & {("ck", "finalize_close"), ("ck", "finalize_pending"), ("k", "finalize_pending"),
                            ("s1_checkpoint", "finalize_close"), ("s1_checkpoint", "finalize_pending")}, p.name
    st_ = history(tmp_path, early_intent=True)
    clk = _Advancing(D_L)
    ck.run_finalizer(tmp_path, now=clk, mailbox=mb(tmp_path))                 # the clock-callable path
    ats = [c.aware(x.at) for x in jrows(tmp_path) if x.kind in ("SLOT-TIMEOUT", "TRIAL-STOP")]
    assert len(ats) == 2 and ats[0] < ats[1]                                  # an advancing transaction clock


def test_finalize_cli_dispatch_pins_the_clock_callable(monkeypatch, capsys):              # T11 N1 (no G4 row)
    seen = {}
    sentinel = lambda: c.aware("2027-04-26T12:30:00+00:00")                   # noqa: E731
    monkeypatch.setattr(c, "now_utc", sentinel)
    monkeypatch.setattr(ck, "run_finalizer", lambda root, *a, **kw: seen.update(kw) or {"mode": "finalize"})
    ck.main(["--finalize"])
    assert seen.get("now") is sentinel                                         # the command's clock, by identity


def test_no_new_cli_mode(tmp_path):                                                         # row 495 (CL-A16)
    """C4: no new CLI mode; --finalize is not extended to the pre-START opening close (O-C4: the opening finalizer
    helper is reachable by direct call only)."""
    t0 = "2026-10-23T20:45:00+00:00"
    assert ck.parse_mode(["--scheduled", t0]) == ("scheduled", c.aware(t0))
    assert ck.parse_mode(["--opening", "--scheduled", t0]) == ("opening", c.aware(t0))
    assert ck.parse_mode(["--final-snapshot"]) == ("final-snapshot", None)
    assert ck.parse_mode(["--finalize"]) == ("finalize", None)
    for bad in (["--finalize-opening"], ["--opening", "--finalize"], ["--opening"]):
        with pytest.raises(SystemExit, match=r"^2$"):
            ck.parse_mode(bad)
    from conftest import s1_plan_audit
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)                     # a pre-START trial: no prereg / RUN-ACK
    day = next(d for d in cal if d["date"] == oc)
    s45 = next(s for s in z.schedule(day, cal))
    s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(s45), at=s45 + timedelta(seconds=1))
    d45 = z.resolution_deadline(s45, day, cal)
    with _Clock(d45), pytest.raises(SystemExit, match=r"no verified prereg"):
        ck.run_finalizer(tmp_path, now=lambda: d45, mailbox=mb(tmp_path))   # refuses (no registration)
    assert kinds(tmp_path, j.slot_subject(s45)) == ["SLOT-INTENT"]           # no opening-close TIMEOUT from it
