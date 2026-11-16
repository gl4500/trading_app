"""A3 Task H5b (Codex Q2 ruling, REVIEW.txt ef7cfe61; Erratum 2 r4 G3.1-G3.2): ONE verified pinned module per evidence
pass of the stop_record -> sampled_seals -> NVS helper chain (s1_seal.seal_pass / s1_seal.pinned), never across a
boundary. Boundaries (Q2 "Boundaries", brief B1-B5) and required evidence (Q2 "Required evidence"):
- per-boundary verification counters: exactly one fresh verification per pass, a fresh one at every boundary (the
  pre-transaction NVS / sampled seals, the score transaction's NVS, the confirming pass, the per-close passes of the
  stop decision between seal-stage transactions);
- a pin change between passes, gates or transaction boundaries refuses; the pinned module mutated between two passes
  refuses (no cross-pass memo, no global flag);
- every direct / standalone helper fails closed: a missing, foreign, forged or ended (stale) pass context refuses;
- damage controls stay (same-size/same-mtime damage, unsampled-tree damage);
- no tree hash is shared by the chain (file-validity conclusions are never shared: every read stays live).
Byte-exact results against the base commit are the golden comparison (s1_evidence/a3/h5b_golden.txt); the four named
mutants are in s1_evidence/a3/h5b_mutants.txt. RED against the base: s1_evidence/a3/h5b_red.txt."""
import json
import os
import types
from pathlib import Path

import pytest
import s1_books as b
import s1_common as c
import s1_journal as j
import s1_run as r
import s1_seal as z
import s1_slot as sl
import s1_trial as t
from conftest import _Clock, s1_jappend, s1_state

START = "2026-10-26T13:30:00+00:00"
PIN = r"e1_sim\.py: missing or hash differs from the pinned"
PIN_EXACT = "e1_sim.py: missing or hash differs from the pinned 000000000000"   # (E1_SIM_SHA flipped to "0" * 64)
NO_PASS = r"^s1_seal evidence pass: no live evidence pass of this module \(missing, foreign or ended\): refused"
REG = r"INVALID \(registration-artifact\)"
OWNERS = ("stop_record", "sampled_seals", "nvs", "stop_ready", "eligible_sessions")
CAL = [{"date": d, "open": "09:30", "close": "16:00"} for d in ("2026-10-23", "2026-10-26", "2026-10-27",
                                                                 "2026-10-28")]


def mb(root):
    return Path(root) / "mailbox.sqlite3"


def jrows(root):
    trs = t.trials(t.scan(mb(root)))
    (tid,) = [x for x, tr_ in trs.items() if tr_.closed is None]
    return j.read_trial(tid, trs[tid].genesis, mb(root))


def pin_loads(monkeypatch):
    """Every c.load_pinned call (the pinned-module verification: hash, then the cached module), by name."""
    loads, real = [], c.load_pinned
    monkeypatch.setattr(c, "load_pinned", lambda name, *a, **kw: loads.append(name) or real(name, *a, **kw))
    return loads


def sims(loads, n0=0) -> int:
    return sum(1 for x in loads[n0:] if x == "e1_sim_pinned")


def flip_pin(monkeypatch):
    monkeypatch.setattr(c, "E1_SIM_SHA", "0" * 64)


def ctx(tmp_path, **kw):
    """The connected lots-STOPPED fixture (score_ready) and the chain's inputs."""
    st_ = s1_state(tmp_path, START, score_ready=True, **kw)
    out, rows = tmp_path / "s1_out", jrows(tmp_path)
    pr = json.loads((out / "prereg.json").read_text(encoding="utf-8"))
    stop = j.first(rows, "TRIAL-STOP")
    return types.SimpleNamespace(st=st_, out=out, rows=rows, start=c.aware(pr["start"]), cal=pr["calendar"],
                                 bundle=t.open_trial(mb(tmp_path)).bundle, stop=stop,
                                 pre=[x for x in rows if stop is None or x.seq < stop.seq])


def call(owner, x):
    return {"stop_record": lambda: z.stop_record(x.out, x.pre, x.start, x.cal, x.bundle),
            "sampled_seals": lambda: z.sampled_seals(x.out, x.rows, x.cal, x.start, upto_seq=x.stop.seq),
            "nvs": lambda: z.nvs(x.out, x.rows, x.start, x.cal, x.bundle),
            "stop_ready": lambda: z.stop_ready(x.out, x.pre, x.start, x.cal, x.bundle, x.st["now"]),
            "eligible_sessions": lambda: z.eligible_sessions(x.start, x.cal)}[owner]()


def helper(name):
    """A pass-scoped s1_seal helper (B3: required context). Absent -> an assertion (the RED is never a NameError)."""
    fn = getattr(z, name, None)
    assert fn is not None, f"s1_seal has no pass-scoped helper {name} (H5b)"
    return fn


# ---------------------------------------------------------------- counters: one fresh verification per pass
@pytest.mark.parametrize("owner", OWNERS)
def test_h5b_one_verification_per_standalone_pass(tmp_path, monkeypatch, owner):
    """Each standalone entry point is its own pass: exactly one pinned-module verification, and the NEXT call verifies
    again (no global flag, no cross-pass memo). The results are the same both times. No tree manifest is memoized
    by the chain (ps None: file-validity conclusions are never shared)."""
    x = ctx(tmp_path)
    loads = pin_loads(monkeypatch)
    real_man, manifests = sl._qualified_manifest, []
    monkeypatch.setattr(sl, "_qualified_manifest", lambda o, s, d, sub, ps: manifests.append(ps) or
                        real_man(o, s, d, sub, ps))
    got = []
    for _ in range(2):
        n0 = len(loads)
        got.append(call(owner, x))
        assert sims(loads, n0) == 1, f"{owner}: {sims(loads, n0)} pinned-module verifications in one pass (want 1)"
    assert got[0] == got[1]
    assert all(ps is None for ps in manifests)


def test_h5b_no_module_use_no_verification(tmp_path, monkeypatch):
    """The verification point is the pass's first module use (as before H5b): a predicate decided before any close
    instant (rows not STOPPED, NVS-REQ1 step 1) verifies nothing, as before."""
    x = ctx(tmp_path, stop=False)
    loads = pin_loads(monkeypatch)
    assert z.nvs(x.out, x.rows, x.start, x.cal, x.bundle) is False
    assert sims(loads) == 0


def test_h5b_score_boundaries_each_verify_afresh(tmp_path, monkeypatch):
    """B1/B2: the score's pre-transaction NVS and sampled seals and the NVS check inside the score INTENT transaction
    are separate passes: each verifies exactly once, afresh."""
    x = ctx(tmp_path)
    loads = pin_loads(monkeypatch)
    inside, seen = [False], []
    real_append, real_nvs, real_seals = j.append, z.nvs, z.sampled_seals

    def append(*a, **kw):
        inside[0] = True
        try:
            return real_append(*a, **kw)
        finally:
            inside[0] = False

    def counted(name, real):
        def f(*a, **kw):
            n0 = len(loads)
            try:
                return real(*a, **kw)
            finally:
                seen.append((name, inside[0], sims(loads, n0)))
        return f
    monkeypatch.setattr(j, "append", append)
    monkeypatch.setattr(z, "nvs", counted("nvs", real_nvs))
    monkeypatch.setattr(z, "sampled_seals", counted("sampled_seals", real_seals))
    with _Clock(x.st["now"]):
        r.score(tmp_path, "score-ack")
    assert ("nvs", False, 1) in seen and ("nvs", True, 1) in seen and ("sampled_seals", False, 1) in seen, seen
    assert all(n == 1 for _, _, n in seen), seen


def test_h5b_confirming_pass_verifies_once_and_shares_nothing(tmp_path, monkeypatch):
    """B1 (confirming reads): the score's confirming pass (s1_run._pre_intent_qualified) owns its pass - exactly one
    verification, by its owner, before the recompute; the recompute uses that pass's module (no second verification
    inside it); the first pass's module never reaches it (its own verification is separate)."""
    x = ctx(tmp_path)
    loads = pin_loads(monkeypatch)
    real_seals, phase, per = z.sampled_seals, ["before"], {}
    q = sorted(z.sampled_seals(x.out, x.rows, x.cal, x.start).items())[0]
    res = sl.names(x.out, sl.slot_of(q[1][0].subject), q[0])["resolution"]
    keep = res.read_bytes()

    def seals(*a, **kw):
        n = len(per) // 2 + 1
        if n == 1:
            res.write_bytes(keep + b" ")                                  # pass 1 sees a changed tree (a race)
        per[f"before{n}"] = sims(loads)
        try:
            return real_seals(*a, **kw)
        finally:
            per[f"after{n}"] = sims(loads)
    monkeypatch.setattr(z, "sampled_seals", seals)
    real_piq, owner = r._pre_intent_qualified, []

    def piq(*a, **kw):
        n0 = len(loads)
        try:
            return real_piq(*a, **kw)
        finally:
            owner.append(sims(loads, n0))
    monkeypatch.setattr(r, "_pre_intent_qualified", piq)
    with _Clock(x.st["now"]), pytest.raises(SystemExit, match=REG):
        r.score(tmp_path, "score-ack")
    assert per["after1"] - per["before1"] == 1, per                       # pass 1: its own one verification
    assert owner == [1], owner                                            # the confirming pass: exactly one
    assert per["after2"] - per["before2"] == 0, per                       # ... by its owner, not inside the recompute


def test_h5b_stop_decision_close_passes_verify_between_seal_stages(tmp_path, monkeypatch):
    """B1 (transactions): decide_stop's per-close state passes are never held across a seal-stage transaction - after
    each seal stage, the next close's pass verifies afresh (exactly one)."""
    lots = [{"symbol": f"S{i % 5}", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (1, 80.0)} for i in range(100)]
    st_ = s1_state(tmp_path, START, score_ready=True, stop=False, seal_stage=False, lots=lots, seal_days=[0, 1, 2])
    loads = pin_loads(monkeypatch)
    real_rss, marks = sl.run_seal_stage, []

    def rss(*a, **kw):
        marks.append(("start", len(loads)))
        try:
            return real_rss(*a, **kw)
        finally:
            marks.append(("end", len(loads)))
    monkeypatch.setattr(sl, "run_seal_stage", rss)
    gv = t.Gate(tmp_path, tmp_path / "s1_out", t.open_trial(mb(tmp_path)), jrows(tmp_path), "ACTIVE", mb(tmp_path))
    pr = json.loads((tmp_path / "s1_out" / "prereg.json").read_text(encoding="utf-8"))
    z.decide_stop(gv, pr["calendar"], c.aware(pr["start"]), lambda: st_["now"], mailbox=mb(tmp_path))
    ends = [n for k, n in marks if k == "end"]
    starts = [n for k, n in marks if k == "start"]
    assert len(starts) >= 2, marks
    for e_, s_ in zip(ends, starts[1:]):                               # between a stage's end and the next stage
        assert sims(loads[:s_], e_) == 1, (e_, s_, loads[e_:s_])      # exactly one fresh per-close verification


# ---------------------------------------------------------------- a pin change at a boundary refuses
@pytest.mark.parametrize("owner", OWNERS)
@pytest.mark.parametrize("how", ["pin-constant", "module-file-mutated"])
def test_h5b_pin_change_between_passes_refuses(tmp_path, monkeypatch, owner, how):
    """No cross-pass memo (Q2 required evidence): the pin changes (or the pinned module file is mutated) between two
    passes of the same entry point -> the second pass refuses (the pin's SystemExit)."""
    x = ctx(tmp_path)
    call(owner, x)
    if how == "pin-constant":
        flip_pin(monkeypatch)
    else:
        d = tmp_path / "pinned_copy"
        d.mkdir()
        (d / "e1_sim.py").write_bytes((Path(c.HERE) / "e1_sim.py").read_bytes() + b"\n# mutated\n")
        monkeypatch.setattr(c, "HERE", d)
    with pytest.raises(SystemExit, match=PIN):
        call(owner, x)


def _appends_by_kind(monkeypatch):
    """Wrap j.append: record (request kind, subject, exception raised inside it or None) per call; the current
    request kind is on `inside` while the transaction runs."""
    real, calls, inside = j.append, [], [None]

    def append(trial_id, gen, req, *a, **kw):
        inside[0] = req.kind
        try:
            got = real(trial_id, gen, req, *a, **kw)
        except BaseException as e:
            calls.append((req.kind, req.subject, e))
            raise
        finally:
            inside[0] = None
        calls.append((req.kind, req.subject, None))
        return got
    monkeypatch.setattr(j, "append", append)
    return calls, inside


def _outcome(fn):
    """The SystemExit fn raises (or None): the outcome is asserted by the caller BEFORE its text (fix round 1 M-2)."""
    try:
        fn()
    except SystemExit as e:
        return e
    return None


@pytest.mark.parametrize("branch", ["lots", "nvs-ack-in-transaction"])
def test_h5b_pin_change_before_score_transaction_refuses_with_no_row(tmp_path, monkeypatch, branch):
    """B2 + B1 (authorization): the pin changes after the pre-transaction NVS and sampled seals and before the score
    INTENT transaction -> the transaction's own NVS pass refuses (rolled back: no row, no work).
    `nvs-ack-in-transaction` is the NO-VALID-SEAL branch, where the SCORE-ACK authorization (the predecessor and ACK
    rules) is decided on the transaction's own rows and ACKs (OP-25) by that same NVS pass. Fix round 1 (M-2): the
    OUTCOME is asserted first (no row, no score work), then the exact refusal and its origin - the pin failure raised
    INSIDE the STAGE-INTENT append."""
    if branch == "lots":
        x = ctx(tmp_path)
        now = x.st["now"]
    else:
        from test_s1_a3_nvs import nvs_chain
        now = nvs_chain(tmp_path)["now"]
    out = tmp_path / "s1_out"
    real = z.sampled_history

    def hist(*a, **kw):
        got = real(*a, **kw)
        flip_pin(monkeypatch)                                     # after every pre-transaction pass, before the INTENT
        return got
    monkeypatch.setattr(z, "sampled_history", hist)
    calls, _ = _appends_by_kind(monkeypatch)
    before = [y.sha for y in jrows(tmp_path)]
    with _Clock(now):
        e = _outcome(lambda: r.score(tmp_path, "score-ack"))
    assert [y.sha for y in jrows(tmp_path)] == before                          # outcome: no row
    assert not (out / "score").exists()                                        # outcome: no score work
    assert e is not None and str(e) == PIN_EXACT, e                            # the exact refusal
    assert [(k, s) for k, s, ex in calls if ex is e] == [("STAGE-INTENT", "stage/score")], calls   # its origin


def test_h5b_nvs_score_ack_transaction_verifies_afresh(tmp_path, monkeypatch):
    """M-1 (authorization boundary): on the NO-VALID-SEAL branch the score's pre-transaction NVS and the NVS deciding
    the SCORE-ACK authorization inside the INTENT transaction (OP-25) are separate passes, each verifying once."""
    from test_s1_a3_nvs import nvs_chain
    st_ = nvs_chain(tmp_path)
    loads = pin_loads(monkeypatch)
    _, inside = _appends_by_kind(monkeypatch)
    real_nvs, seen = z.nvs, []

    def nvs(*a, **kw):
        n0 = len(loads)
        try:
            return real_nvs(*a, **kw)
        finally:
            seen.append((inside[0], sims(loads, n0)))
    monkeypatch.setattr(z, "nvs", nvs)
    with _Clock(st_["now"]):
        rep = r.score(tmp_path, "score-ack")
    assert rep["verdict"] == "NO-VALID-SEAL"
    assert (None, 1) in seen and ("STAGE-INTENT", 1) in seen and all(n == 1 for _, n in seen), seen


def test_h5b_trial_stop_transaction_passes_verify_afresh(tmp_path, monkeypatch):
    """M-1 (callbacks / transactions): decide_stop's pre-transaction stop_record and the TRIAL-STOP transaction's
    callbacks (Context.stop_detail -> stop_record, Context.stop_ready -> stop_ready, inside j.append) are separate
    passes, each verifying exactly once - no pass is handed from decide_stop into the transaction's callbacks."""
    lots = [{"symbol": f"S{i % 5}", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (1, 80.0)} for i in range(100)]
    st_ = s1_state(tmp_path, START, score_ready=True, stop=False, lots=lots, seal_days=[0, 1, 2])
    loads = pin_loads(monkeypatch)
    _, inside = _appends_by_kind(monkeypatch)
    seen = []
    for name in ("stop_record", "stop_ready"):
        real = getattr(z, name)

        def f(*a, _real=real, _name=name, **kw):
            n0 = len(loads)
            try:
                return _real(*a, **kw)
            finally:
                seen.append((_name, inside[0], sims(loads, n0)))
        monkeypatch.setattr(z, name, f)
    gv = t.Gate(tmp_path, tmp_path / "s1_out", t.open_trial(mb(tmp_path)), jrows(tmp_path), "ACTIVE", mb(tmp_path))
    pr = json.loads((tmp_path / "s1_out" / "prereg.json").read_text(encoding="utf-8"))
    rec = z.decide_stop(gv, pr["calendar"], c.aware(pr["start"]), lambda: st_["now"], mailbox=mb(tmp_path))
    assert rec is not None and j.first(jrows(tmp_path), "TRIAL-STOP") is not None
    assert ("stop_record", None, 1) in seen, seen                              # the pre-transaction pass
    assert ("stop_record", "TRIAL-STOP", 1) in seen, seen                      # the transaction's detail callback
    assert ("stop_ready", "TRIAL-STOP", 1) in seen, seen                       # the transaction's readiness callback
    assert all(n == 1 for _, _, n in seen), seen


def test_h5b_pin_change_before_trial_stop_transaction_refuses_with_no_row(tmp_path, monkeypatch):
    """M-1: the pin changes between decide_stop's pre-transaction stop_record and the TRIAL-STOP transaction -> the
    transaction's own callback pass refuses: outcome first (no TRIAL-STOP row, no stop.json), then the exact refusal,
    raised INSIDE the TRIAL-STOP append."""
    lots = [{"symbol": f"S{i % 5}", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (1, 80.0)} for i in range(100)]
    st_ = s1_state(tmp_path, START, score_ready=True, stop=False, lots=lots, seal_days=[0, 1, 2])
    real, calls = j.append, []

    def append(trial_id, gen, req, *a, **kw):
        if req.kind == "TRIAL-STOP":
            flip_pin(monkeypatch)                                 # after the pre-transaction pass, before the txn
        try:
            got = real(trial_id, gen, req, *a, **kw)
        except BaseException as e:
            calls.append((req.kind, e))
            raise
        calls.append((req.kind, None))
        return got
    monkeypatch.setattr(j, "append", append)
    gv = t.Gate(tmp_path, tmp_path / "s1_out", t.open_trial(mb(tmp_path)), jrows(tmp_path), "ACTIVE", mb(tmp_path))
    pr = json.loads((tmp_path / "s1_out" / "prereg.json").read_text(encoding="utf-8"))
    e = _outcome(lambda: z.decide_stop(gv, pr["calendar"], c.aware(pr["start"]), lambda: st_["now"],
                                       mailbox=mb(tmp_path)))
    assert j.first(jrows(tmp_path), "TRIAL-STOP") is None                      # outcome: no row
    assert not (tmp_path / "s1_out" / "stop.json").exists()                    # outcome: nothing published
    assert e is not None and str(e) == PIN_EXACT, e                            # the exact refusal
    assert [k for k, ex in calls if ex is e] == ["TRIAL-STOP"], calls          # raised inside the TRIAL-STOP append


def test_h5b_pin_change_before_confirming_pass_refuses_with_no_row(tmp_path, monkeypatch):
    """B1 (confirming reads): a QUALIFIED tree damaged after the score's gates (a race past the F3 table) makes the
    pre-INTENT pass raise; the pin changes after that first observation -> the confirming pass refuses (its owner's
    verification), with no row, no INVALID and no recompute."""
    x = ctx(tmp_path)
    q = sorted(z.sampled_seals(x.out, x.rows, x.cal, x.start).items())[0]
    res = sl.names(x.out, sl.slot_of(q[1][0].subject), q[0])["resolution"]
    real_nvs, real_seals, n = r._nvs, z.sampled_seals, [0]

    def nvs(*a, **kw):
        got = real_nvs(*a, **kw)
        res.write_bytes(res.read_bytes() + b" ")                      # damaged after the gates, before the seals
        return got

    def seals(*a, **kw):
        n[0] += 1
        try:
            return real_seals(*a, **kw)
        finally:
            if n[0] == 1:
                flip_pin(monkeypatch)                                 # between the first pass and the confirming one
    monkeypatch.setattr(r, "_nvs", nvs)
    monkeypatch.setattr(z, "sampled_seals", seals)
    before = [y.sha for y in jrows(tmp_path)]
    with _Clock(x.st["now"]), pytest.raises(SystemExit, match=PIN):
        r.score(tmp_path, "score-ack")
    assert n[0] == 1 and [y.sha for y in jrows(tmp_path)] == before
    assert not (x.out / "aborted.json").exists()


def test_h5b_pin_change_between_gates_refuses(tmp_path, monkeypatch):
    """B1 (gates): a gate's chain passes never serve the next gate - the pin changes between two gates -> the second
    gate refuses with the pin's SystemExit."""
    ctx(tmp_path)
    t.gate(tmp_path, "gate 1")
    flip_pin(monkeypatch)
    with pytest.raises(SystemExit, match=PIN):
        t.gate(tmp_path, "gate 2")
    assert all(y.kind != "TRIAL-INVALID" for y in jrows(tmp_path))


def test_h5b_pin_change_between_stop_decision_seal_stages_refuses(tmp_path, monkeypatch):
    """B1 (transactions): the pin changes after decide_stop's first seal-stage transaction -> refused, no TRIAL-STOP.
    Fix round 1 (M-2): the refusal comes from the NEXT close's own pass, before the next seal-stage command is entered
    (exactly one run_seal_stage entry, no row after the first stage's); a pass held across the stages (the reviewer's
    hoist mutant R-1) would enter the second stage and fail only on run_seal_stage's own downstream pin check."""
    lots = [{"symbol": f"S{i % 5}", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (1, 80.0)} for i in range(100)]
    st_ = s1_state(tmp_path, START, score_ready=True, stop=False, seal_stage=False, lots=lots, seal_days=[0, 1, 2])
    real_rss, entered, after_first = sl.run_seal_stage, [], []

    def rss(*a, **kw):
        entered.append(a[1]["date"])
        got = real_rss(*a, **kw)
        after_first.append([y.sha for y in jrows(tmp_path)])
        flip_pin(monkeypatch)
        return got
    monkeypatch.setattr(sl, "run_seal_stage", rss)
    gv = t.Gate(tmp_path, tmp_path / "s1_out", t.open_trial(mb(tmp_path)), jrows(tmp_path), "ACTIVE", mb(tmp_path))
    pr = json.loads((tmp_path / "s1_out" / "prereg.json").read_text(encoding="utf-8"))
    e = _outcome(lambda: z.decide_stop(gv, pr["calendar"], c.aware(pr["start"]), lambda: st_["now"],
                                       mailbox=mb(tmp_path)))
    assert j.first(jrows(tmp_path), "TRIAL-STOP") is None                      # outcome: no TRIAL-STOP
    assert len(entered) == 1, entered                                         # no second seal stage was started
    assert [y.sha for y in jrows(tmp_path)] == after_first[0]                  # no row after the first stage's
    assert e is not None and str(e) == PIN_EXACT, e


# ---------------------------------------------------------------- B3: every helper fails closed
def _ended_pass():
    with helper("seal_pass")() as px:
        helper("pinned")(px)
    return px


CONTEXTS = {
    "missing": lambda: None,
    "foreign-evidence-pass": lambda: sl.EvidencePass(rows=[], index={}, cal=CAL, sim=c.sim()),
    "foreign-namespace": lambda: types.SimpleNamespace(_sim=c.sim(), _live=True, sim=c.sim()),
    "forged-uninitialised": lambda: object.__new__(helper("SealPass")),
    "ended": _ended_pass,
}
HELPERS = {
    "pinned": lambda px: z.pinned(px),
    "_eligible": lambda px: z._eligible(px, c.aware(START), CAL),
    "_close_state": lambda px: z._close_state(px, {}, CAL[1], CAL),
    "_sampled_seals": lambda px: z._sampled_seals(px, Path("."), [], CAL, c.aware(START), None),
    "_stop_record": lambda px: z._stop_record(px, Path("."), [types.SimpleNamespace(trial_id="t", subject="x",
                                                                                     kind="X", seq=1)],
                                              c.aware(START), CAL, "b"),
    "_nvs": lambda px: z._nvs(px, Path("."), [], c.aware(START), CAL, "b"),
    "sampled_seals(px=)": lambda px: z.sampled_seals(Path("."), [], CAL, c.aware(START), px=px),
    "books._sold_events": lambda px: b._sold_events([], px),                 # fix round 1 (I-1): s1_books takes the
    "books._economic_in": lambda px: b._economic_in(px, [], c.aware(START), []),     # pass, never a bare module
}


@pytest.mark.parametrize("context,name", [(k, h) for k in CONTEXTS for h in HELPERS
                                         if (k, h) != ("missing", "sampled_seals(px=)")])
def test_h5b_helpers_fail_closed_without_a_live_pass(context, name):
    """B3: a missing, foreign, forged or ended (stale) pass context refuses - no helper falls back to an unverified
    module, a global flag or the last pass's module (Q2: no unguarded optional-module argument)."""
    for n in ("seal_pass", "pinned", "SealPass", name.split("(")[0]):
        if n.startswith("books."):
            assert getattr(b, n[len("books."):], None) is not None, f"s1_books has no pass-scoped helper {n} (H5b)"
        else:
            helper(n)
    px = CONTEXTS[context]()                    # (sampled_seals(px=None) is the standalone entry point: its own pass)
    with pytest.raises(SystemExit, match=NO_PASS):
        HELPERS[name](px)


def test_h5b_pass_created_only_by_its_owner():
    """B3: a pass context is created only by s1_seal.seal_pass (after which its owner verifies at first use)."""
    with pytest.raises(TypeError, match=r"created only by s1_seal\.seal_pass"):
        helper("SealPass")(object())


def test_h5b_stale_pass_with_a_changed_pin_refuses(tmp_path, monkeypatch):
    """B3 (stale): a pass that ended (its module verified) is never accepted again - after a pin change it cannot
    serve the old module."""
    px = _ended_pass()
    flip_pin(monkeypatch)
    with pytest.raises(SystemExit, match=NO_PASS):
        z.sampled_seals(Path("."), [], CAL, c.aware(START), px=px)
    with pytest.raises(SystemExit, match=NO_PASS):
        z.pinned(px)


# ------------------------------------------------- fix round 1 (I-1): the FIFO replay uses THIS pass's module
class _Proxy:
    """An identity-recording stand-in for the pinned module: every attribute read is logged with this proxy's tag."""

    def __init__(self, real, tag, log):
        self._real, self._tag, self._log = real, tag, log

    def __getattr__(self, name):
        self._log.append((self._tag, name))
        return getattr(self._real, name)


@pytest.mark.parametrize("owner", ["stop_record", "nvs", "stop_ready"])
def test_h5b_fifo_replay_uses_this_pass_module(tmp_path, monkeypatch, owner):
    """I-1: each pass's verification yields a distinct identity-recording module object; the economic FIFO replay
    (count_sold -> s1_books._sold_events -> baseline_lots / x) of pass k touches pass k's object and no other - no
    cross-pass module memo in s1_books or s1_seal (the reviewer's R-2). Results equal the unproxied ones."""
    x = ctx(tmp_path)
    want = call(owner, x)
    real_sim, log, made = c.sim, [], []

    def sim():
        p = _Proxy(real_sim(), len(made), log)
        made.append(p)
        return p
    monkeypatch.setattr(c, "sim", sim)
    for k in range(2):
        n0 = len(log)
        got = call(owner, x)
        assert len(made) == k + 1, f"pass {k}: {len(made) - k} verifications (want exactly 1, fresh)"
        fifo = [(tag, name) for tag, name in log[n0:] if name in ("baseline_lots", "x")]
        assert ("baseline_lots" in {n for _, n in fifo}) and {tag for tag, _ in fifo} == {k}, fifo[:5]
        assert got == want


def test_h5b_pass_fifo_replay_equals_public_sold_events(tmp_path):
    """I-1: the pass-scoped replay (s1_books._sold_events) gives exactly the public sold_events result on every
    sampled seal's trades, and the same BookError for an oversell (the engine's ValueError mapped to BookError inside
    the try, N-2)."""
    fn = getattr(b, "_sold_events", None)
    assert fn is not None, "s1_books has no pass-scoped _sold_events (H5b)"
    x = ctx(tmp_path)
    seals = z.sampled_seals(x.out, x.rows, x.cal, x.start)
    assert seals
    for _day, (_q, data) in sorted(seals.items()):
        trades = json.loads(data)["trades"]
        with z.seal_pass() as px:
            assert fn(trades, px) == b.sold_events(trades)
    orphan = [{"id": 1, "symbol": "A", "action": "SELL", "shares": 1.0, "price": 1.0, "ts": START}]
    with pytest.raises(b.BookError, match=r"^INVALID oversell 1$") as e1:
        b.sold_events(orphan)
    with z.seal_pass() as px, pytest.raises(b.BookError, match=r"^INVALID oversell 1$") as e2:
        fn(orphan, px)
    assert str(e1.value) == str(e2.value)


# ---------------------------------------------------------------- damage controls stay
def _same_size_same_mtime(p: Path):
    st = p.stat()
    b = bytearray(p.read_bytes())
    b[-1] ^= 0x01
    p.write_bytes(bytes(b))
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert p.stat().st_size == st.st_size and p.stat().st_mtime_ns == st.st_mtime_ns


@pytest.mark.parametrize("owner", ["stop_record", "sampled_seals"])
def test_h5b_same_size_same_mtime_damage_detected_by_the_next_pass(tmp_path, owner):
    """A healthy pass, then same-size/same-mtime damage to a sampled QUALIFIED member -> the next pass detects it
    (every member read is live in every pass: the shared module never shares a file-validity conclusion)."""
    x = ctx(tmp_path)
    healthy = call(owner, x)
    assert healthy
    q = sorted(z.sampled_seals(x.out, x.rows, x.cal, x.start).items())[0]
    _same_size_same_mtime(sl.names(x.out, sl.slot_of(q[1][0].subject), q[0])["capture"] / "backup.sqlite3")
    with pytest.raises(sl.QualifiedEvidence, match=r"QUALIFIED tree differs from the committed detail \(F3\)"):
        call(owner, x)


def test_h5b_unsampled_tree_damage_still_detected(tmp_path):
    """A later QUALIFIED slot of a close (selected by nothing: no seal, no stop input) - healthy passes of the chain,
    then damage to its tree -> the gate's F3 table still sees it (INVALID registration-artifact)."""
    from conftest import S1_RECEIPT, _write_seal
    lots = [{"symbol": f"S{i % 5}", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (1, 80.0) if i < 99 else None}
            for i in range(100)]
    st_ = s1_state(tmp_path, START, score_ready=True, stop=False, lots=lots, seal_days=[0, 1, 2])
    out, d2 = tmp_path / "s1_out", "2026-10-28"
    _write_seal(out, d2, z.close_of(d2, st_["calendar"]), [], S1_RECEIPT, minutes=47, with_stage=False)
    t.gate(tmp_path, "healthy")
    rows = jrows(tmp_path)
    tr = t.open_trial(mb(tmp_path))
    start = c.aware(START)
    z.sampled_seals(out, rows, st_["calendar"], start)
    z.stop_record(out, rows, start, st_["calendar"], tr.bundle)
    z.nvs(out, rows, start, st_["calendar"], tr.bundle)
    later = [y for y in rows if y.kind == "SLOT-QUALIFIED"][-1]
    p = sl.names(out, sl.slot_of(later.subject), d2)["capture"] / "projection.json"
    _same_size_same_mtime(p)
    with pytest.raises(SystemExit, match=REG):
        t.gate(tmp_path, "probe")


def test_h5b_pending_slot_still_blocks_the_record(tmp_path):
    """Row-prefix ordering unchanged (B4): an INTENT with no terminal on an eligible close before the first qualifying
    close leaves no stop candidate (None), with one verification."""
    lots = [{"symbol": f"S{i % 5}", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (1, 80.0)} for i in range(100)]
    st_ = s1_state(tmp_path, START, score_ready=True, stop=False, lots=lots, seal_days=[1, 2])
    cal = st_["calendar"]
    d0 = next(d for d in z.eligible_sessions(c.aware(START), cal))
    s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(z.schedule(d0, cal)[0]), at=z.schedule(d0, cal)[0],
               op="1" * 32, actor="2" * 32)
    rows = jrows(tmp_path)
    assert z.stop_record(tmp_path / "s1_out", rows, c.aware(START), cal, t.open_trial(mb(tmp_path)).bundle) is None
