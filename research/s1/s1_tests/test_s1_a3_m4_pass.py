"""Erratum 2 r4 G3 (M4(1)-(3) with pass scope; O9 confirming pass = new pass): one verified pin load and one hash
per QUALIFIED tree per pass; per-pass subject index; no cross-gate memo; listing/read errors never OK. Map rows
430-438 (row 439 is the measurement gate). REDs: rows 436 and 435[between-passes] are behavioural against the stub;
the others are semantic-mutant REDs (s1_evidence/a3/tH4_mutants.txt).
Erratum 2 Clarification 1 r2 C5 (OP-9; rows 496-497): the classification of QUALIFIED-tree read failures - a disclosed
exception to G3.3/M4-A9 baseline equivalence, with its own RED (s1_evidence/a3/h4_c5_red.txt).
A3 H4 deviations from the brief's draft (R-G: literal defects fixed, no row outcome changed) are listed in
task-H4-report.md; each is marked "H4 D-n" where it applies."""
import json
import os
import shutil
from datetime import timedelta
from pathlib import Path

import pytest
import s1_common as c
import s1_journal as j
import s1_seal as z
import s1_slot as sl
import s1_trial as t
from conftest import s1_state

START = "2026-10-26T13:30:00+00:00"
REG = r"INVALID \(registration-artifact\)"


def mb(root):
    return Path(root) / "mailbox.sqlite3"


def jrows(root):
    tr = t.open_trial(mb(root))
    return j.read_trial(tr.trial_id, tr.genesis, mb(root))


def trees(root):
    return sorted((Path(root) / "s1_out" / "captures").glob("2026-10-2[6-9]/*/backup.sqlite3"))


def all_trees(root):
    """Every QUALIFIED capture's backup, the opening close's included (H4 D-1)."""
    return sorted((Path(root) / "s1_out" / "captures").glob("*/*/backup.sqlite3"))


def three_qualified(tmp_path, **kw):
    """Seals on d0, d1, d2 (row-302 shape: no lots stop) - three QUALIFIED trees, the last one never selected as a
    stop seal (M4-A8)."""
    return s1_state(tmp_path, START, score_ready=True, stop=False,
                    lots=[{"symbol": f"S{i % 5}", "qty": 10, "px": 100.0, "buy_day": 0,
                           "sell": (1, 80.0) if i < 99 else None} for i in range(100)], seal_days=[0, 1, 2], **kw)


def gate_outcome(root, where):
    """The gate's outcome: None (passed) or its SystemExit. A raw OSError escaping the gate is neither a refusal nor a
    verdict (G3.4: never OK, never silent): pytest.fail at this line (B3: the RED is an assertion here, H4 D-2)."""
    try:
        t.gate(root, where)
    except SystemExit as e:
        return e
    except OSError as e:
        pytest.fail(f"a raw {type(e).__name__} escaped the gate ({e}): neither a refusal nor a verdict")
    return None


def test_same_size_same_mtime_change_detected_next_gate(tmp_path):                         # row 430 (M4-A1)
    three_qualified(tmp_path)
    t.gate(tmp_path, "gate 1")
    p = trees(tmp_path)[0]
    st = p.stat()
    b = bytearray(p.read_bytes())
    b[-1] ^= 0x01                                                           # same size
    p.write_bytes(bytes(b))
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))                        # same mtime
    assert p.stat().st_size == st.st_size and p.stat().st_mtime_ns == st.st_mtime_ns
    with pytest.raises(SystemExit, match=REG):
        t.gate(tmp_path, "gate 2")


@pytest.mark.parametrize("case", ["missing", "added"])
def test_tree_file_missing_or_added(tmp_path, case):                                         # row 431 (M4-A2)
    three_qualified(tmp_path)
    p = trees(tmp_path)[1]
    if case == "missing":
        p.unlink()                                                          # F3 QUALIFIED: a required file missing
    else:
        stray = p.parent.parent / "20991231T000000Z.attempt.json"           # a file with no journal row (F3)
        stray.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match=REG):
        t.gate(tmp_path, "probe")


@pytest.mark.parametrize("case", ["new-row", "lock-reread-head-change"])
def test_confirming_pass_rereads_journal(tmp_path, monkeypatch, case):                     # row 432 (M4-A3)
    """A file legitimized by a row committed between the passes is no violation: the confirming pass reads fresh
    rows and rebuilds its index (kills index/rows reuse). new-row: the gate's evidence_check; lock-reread-head-change:
    confirmed_close_problems (the seal stage's re-read after a head change; H4 D-3: called directly - the gate never
    reaches it)."""
    st_ = three_qualified(tmp_path)
    cal = st_["calendar"]
    out = tmp_path / "s1_out"
    day = next(d for d in cal if d["date"] == "2026-10-29")
    s = z.schedule(day, cal)[0]
    n = sl.names(out, s, day["date"])
    n["claim"].parent.mkdir(parents=True, exist_ok=True)
    n["claim"].write_text(json.dumps({"op": "1" * 32, "actor": "2" * 32}), encoding="utf-8")
    real = sl.evidence_problems if case == "new-row" else sl.close_problems
    calls = []

    def between(*a, **kw):
        got = real(*a, **kw)
        if not calls:                                                        # after the first pass only
            calls.append(1)
            assert got, "the first pass must observe the claim with no row"
            row = s1_jappend_slot(tmp_path, s)
            n["claim"].write_text(json.dumps({"op": row.op, "actor": row.actor,
                                              "capture_dir": n["capture"].relative_to(out).as_posix()}),
                                  encoding="utf-8")
        return got
    monkeypatch.setattr(sl, "evidence_problems" if case == "new-row" else "close_problems", between)
    if case == "new-row":
        e = gate_outcome(tmp_path, "probe")
        assert e is None, f"no violation expected: {e}"                      # (B3: an assertion, not an escape)
    else:
        gv = t.Gate(tmp_path, out, t.open_trial(mb(tmp_path)), jrows(tmp_path), "ACTIVE", mb(tmp_path))
        assert sl.confirmed_close_problems(gv, out, jrows(tmp_path), day, cal, mb(tmp_path)) == []
    assert calls == [1]
    assert all(x.kind != "TRIAL-INVALID" for x in jrows(tmp_path))


def s1_jappend_slot(root, s):
    from conftest import s1_jappend
    return s1_jappend(root, "SLOT-INTENT", j.slot_subject(s), at=s, op="1" * 32, actor="2" * 32)


@pytest.mark.parametrize("case", ["scandir", "read", "permission"])
def test_listing_error_refuses(tmp_path, monkeypatch, case):                                # row 433 (M4-A4)
    three_qualified(tmp_path)
    target = trees(tmp_path)[0]
    before = [x.sha for x in jrows(tmp_path)]
    if case == "scandir":
        real = Path.glob

        def bad_glob(self, pattern, *a, **kw):
            if self.name == "captures":
                raise PermissionError(13, "listing denied (simulated)")
            return real(self, pattern, *a, **kw)
        monkeypatch.setattr(Path, "glob", bad_glob)
    else:
        real = Path.open
        exc = OSError(5, "read error (simulated)") if case == "read" else PermissionError(13, "denied (simulated)")

        def bad_open(self, *a, **kw):
            if self == target:
                raise exc
            return real(self, *a, **kw)
        monkeypatch.setattr(Path, "open", bad_open)
    e = gate_outcome(tmp_path, "probe")
    assert isinstance(e, SystemExit), "a listing/read/permission error is never OK"         # never OK
    if case in ("read", "permission"):                                      # C5.1 on a QUALIFIED member: a refusal,
        assert no_new_invalid(tmp_path, before)                             # never a new INVALID (OP-9 resolved)
    monkeypatch.undo()
    assert (tmp_path / "s1_out").is_dir()


@pytest.mark.parametrize("when", ["between-gates", "between-passes"])
def test_changed_pin_fails_closed(tmp_path, monkeypatch, when):                             # row 434 (M4-A5)
    three_qualified(tmp_path)
    if when == "between-gates":
        t.gate(tmp_path, "gate 1")
        monkeypatch.setattr(c, "E1_SIM_SHA", "0" * 64)
        with pytest.raises(SystemExit, match=r"hash differs from the pinned"):
            t.gate(tmp_path, "gate 2")
        return
    p = trees(tmp_path)[0]
    p.write_bytes(p.read_bytes() + b"x")                                      # a problem forces a confirming pass
    real = sl.evidence_problems
    seen = []

    def flip(*a, **kw):
        got = real(*a, **kw)
        if not seen:
            seen.append(1)
            monkeypatch.setattr(c, "E1_SIM_SHA", "0" * 64)                   # the pin changes between the passes
        return got
    monkeypatch.setattr(sl, "evidence_problems", flip)
    with pytest.raises(SystemExit, match=r"hash differs from the pinned"):
        t.gate(tmp_path, "probe")
    assert all(x.kind != "TRIAL-INVALID" for x in jrows(tmp_path))          # failed closed, no INVALID from it


@pytest.mark.parametrize("case", ["between-gates", "between-passes", "unknown-slot"])
def test_changed_calendar_fresh_pass(tmp_path, monkeypatch, case):                          # row 435 (M4-A6)
    """H4 D-7: between-gates - gate 1 is healthy (a gate that commits INVALID leaves no later gate to judge), then the
    registered calendar loses d2 and gate 2 must see it (its slots unknown: the existing classification)."""
    three_qualified(tmp_path)
    reads, drop = [], [case == "unknown-slot"]
    real = sl._calendar

    def counted(gv):
        cal = real(gv)
        reads.append(cal)
        if drop[0] or (case == "between-passes" and len(reads) >= 2):
            return [d for d in cal if d["date"] != "2026-10-28"]               # d2 vanishes: its slots unknown
        return cal
    monkeypatch.setattr(sl, "_calendar", counted)
    if case == "between-gates":
        t.gate(tmp_path, "gate 1")                                           # healthy
        t_reads = len(reads)
        drop[0] = True                                                       # the calendar changes between gates
        with pytest.raises(SystemExit, match=REG):
            t.gate(tmp_path, "gate 2")
        assert len(reads) > t_reads                                          # no global or earlier calendar cache
        return
    p = trees(tmp_path)[2]
    p.write_bytes(p.read_bytes() + b"x")                                      # forces the confirming pass
    with pytest.raises(SystemExit, match=REG):
        t.gate(tmp_path, "probe")
    assert len(reads) >= 2                                                   # a fresh calendar read per pass (O9)


def test_pass_counters(tmp_path, monkeypatch):                                              # row 436 (M4-A7)
    three_qualified(tmp_path)
    loads, hashed = [], []
    real_lp, real_sha = c.load_pinned, c.sha256_file
    monkeypatch.setattr(c, "load_pinned", lambda name, *a, **kw: loads.append(name) or real_lp(name, *a, **kw))
    monkeypatch.setattr(c, "sha256_file", lambda p: hashed.append(Path(p)) or real_sha(p))
    real_ep = sl.evidence_problems
    per_pass = []

    def ep(*a, **kw):
        n0, h0 = len(loads), len(hashed)
        got = real_ep(*a, **kw)
        per_pass.append(([x for x in loads[n0:] if x == "e1_sim_pinned"],
                         [x for x in hashed[h0:] if x.name == "backup.sqlite3"]))
        return got
    monkeypatch.setattr(sl, "evidence_problems", ep)
    for _ in range(2):                                                       # the next gate repeats the counts
        t.gate(tmp_path, "probe")
    want = all_trees(tmp_path)                                               # H4 D-1: the opening tree is QUALIFIED too
    assert len(want) == 4
    assert len(per_pass) == 2
    for sims, backups in per_pass:
        assert len(sims) == 1                                                # exactly one verified pin load
        assert sorted(backups) == want                                       # each tree once, every tree


def test_non_selected_qualified_damage_invalid(tmp_path):                                  # row 437 (M4-A8)
    """H4 D-8: three_qualified has one QUALIFIED per close, each its close's selected (first) one; a LATER QUALIFIED
    slot of d2 (close + 47 min, no seal stage of its own) is added, so the damaged tree is selected by nothing - no
    seal, no stop - and only the F3 table's every-tree check can see it (kills p7)."""
    from conftest import S1_RECEIPT, _write_seal
    st_ = three_qualified(tmp_path)
    out = tmp_path / "s1_out"
    d2 = "2026-10-28"
    _write_seal(out, d2, z.close_of(d2, st_["calendar"]), [], S1_RECEIPT, minutes=47, with_stage=False)
    t.gate(tmp_path, "healthy")                                              # the later QUALIFIED tree is healthy
    rows = jrows(tmp_path)
    q = [x for x in rows if x.kind == "SLOT-QUALIFIED"]
    assert sl.first_qualified(rows, next(d for d in st_["calendar"] if d["date"] == d2), st_["calendar"]).sha \
        != q[-1].sha                                                         # q[-1] is not its close's selected one
    later = sl.names(out, sl.slot_of(q[-1].subject), d2)["capture"] / "projection.json"
    later.write_bytes(later.read_bytes() + b" ")
    with pytest.raises(SystemExit, match=REG):
        t.gate(tmp_path, "probe")


def test_problem_lists_exact(tmp_path):                                                      # row 438 (M4-A9)
    st_ = three_qualified(tmp_path)
    out, cal = tmp_path / "s1_out", st_["calendar"]
    day = next(d for d in cal if d["date"] == "2026-10-29")
    s0, s1_ = z.schedule(day, cal)[:2]
    for s in (s0, s1_):
        n = sl.names(out, s, day["date"])
        n["claim"].parent.mkdir(parents=True, exist_ok=True)
        n["claim"].write_text("{}", encoding="utf-8")
    sub0, sub1 = j.slot_subject(s0), j.slot_subject(s1_)
    want = [f"{sub0}: claim exists with no journal row (F3)", f"{sub1}: claim exists with no journal row (F3)"]
    gv = t.Gate(tmp_path, out, t.open_trial(mb(tmp_path)), jrows(tmp_path), "ACTIVE", mb(tmp_path))
    assert sl.evidence_problems(out, jrows(tmp_path), cal) == want             # hand-written text and order
    assert sl.evidence_problems(out, jrows(tmp_path), cal, ps=sl.new_pass(gv)) == want


# ---------------------------------------------------------------- Clarification 1 C5 (rows 496-497; OP-9)
# A disclosed exception to G3.3/M4-A9 baseline equivalence, with its own RED (a3/h4_c5_red.txt).
def _member_reads(monkeypatch, target, steps):
    """Path.read_bytes of `target` (a QUALIFIED member) follows `steps`, one callable per read, the last repeating.
    The fault is injected at the DIRECT member read (O-C5a: the RED shows which call raises)."""
    real, n = Path.read_bytes, [0]

    def rb(self):
        if self == target:
            f = steps[min(n[0], len(steps) - 1)]
            n[0] += 1
            return f(self, real)
        return real(self)
    monkeypatch.setattr(Path, "read_bytes", rb)
    return n


def _err(exc):
    def f(p, real):
        raise exc
    return f


def _ok(p, real):
    return real(p)


def no_new_invalid(root, before):
    return [x for x in jrows(root) if x.kind == "TRIAL-INVALID" and x.sha not in before] == []


@pytest.mark.parametrize("case", ["transient-permission", "persistent-permission", "first-bad-confirm-generic-io",
                                  "direct-missing-member-both-passes", "confirmed-missing-parent-path",
                                  "failed-listing-or-lookup-as-filenotfound-both-passes", "changed-confirmed",
                                  "malformed-confirmed", "unrelated-mandatory-invalid-precedence",
                                  "unrelated-mandatory-invalid-precedence-e55", "later-healthy-reevaluates"])
def test_qualified_member_read_classification(tmp_path, monkeypatch, case):               # row 496 (CL-A17)
    three_qualified(tmp_path)
    member = trees(tmp_path)[0]                                              # capture/backup.sqlite3 of a QUALIFIED
    before = [x.sha for x in jrows(tmp_path)]
    perm = PermissionError(13, "sharing violation (simulated)")
    want_invalid = False
    if case == "transient-permission":                                       # H4 D-4: an outage is never permission to
        _member_reads(monkeypatch, member, [_err(perm), _ok])               # continue (OP-9): a refusal, no INVALID
    elif case == "persistent-permission":
        _member_reads(monkeypatch, member, [_err(perm)])
    elif case == "first-bad-confirm-generic-io":                            # pass 1 sees changed bytes, pass 2 I/O
        member.write_bytes(member.read_bytes() + b"x")
        _member_reads(monkeypatch, member, [_ok, _err(OSError(5, "I/O error (simulated)"))])
    elif case == "direct-missing-member-both-passes":
        member.unlink()
        want_invalid = True                                                 # typed absence, both passes: F3
    elif case == "confirmed-missing-parent-path":
        shutil.rmtree(member.parent)                                        # the capture dir itself is gone
        want_invalid = True
    elif case == "failed-listing-or-lookup-as-filenotfound-both-passes":
        real_glob = Path.glob

        def lost_listing(self, pattern, *a, **kw):                          # an enumeration failure, raised as FNF
            if self.name == "captures":
                raise FileNotFoundError(2, "listing failed (simulated)")
            return real_glob(self, pattern, *a, **kw)
        monkeypatch.setattr(Path, "glob", lost_listing)
    elif case == "changed-confirmed":
        member.write_bytes(member.read_bytes() + b"x")
        want_invalid = True
    elif case == "malformed-confirmed":
        rp = next(member.parent.parent.glob(f"{member.parent.name}.resolution.json"))
        rp.write_bytes(b'{"not json"')
        want_invalid = True
    elif case == "unrelated-mandatory-invalid-precedence":                  # a changed bundle after rows still wins
        _member_reads(monkeypatch, member, [_err(perm)])
        monkeypatch.setattr(c, "bundle_sha256", lambda: "f" * 64)
    elif case == "unrelated-mandatory-invalid-precedence-e55":              # H4 fix round 1 (review I-1): an INVALID
        _member_reads(monkeypatch, member, [_err(perm)])                    # decided AFTER the F3 table (E5.5) wins
        monkeypatch.setattr(t, "_manifest_sha", lambda root, rows, seq: "0" * 64)    # over the unreadable member
    if case == "later-healthy-reevaluates":
        n = _member_reads(monkeypatch, member, [_err(perm), _err(perm), _ok])
        e = gate_outcome(tmp_path, "probe 1")
        assert isinstance(e, SystemExit) and "unreadable" in str(e), e
        assert no_new_invalid(tmp_path, before) and n[0] >= 1
        n[0] = 2                                                             # the member is healthy from now on
        assert gate_outcome(tmp_path, "probe 2") is None                     # judged normally: healthy, no INVALID
        assert no_new_invalid(tmp_path, before)
        return
    e = gate_outcome(tmp_path, "probe")
    assert isinstance(e, SystemExit), e
    new = [x for x in jrows(tmp_path) if x.kind == "TRIAL-INVALID" and x.sha not in before]
    if case == "unrelated-mandatory-invalid-precedence":
        assert [x.subject for x in new] == ["reason/bundle"]                # the I/O refusal never masks it
    elif case == "unrelated-mandatory-invalid-precedence-e55":
        assert [x.subject for x in new] == ["reason/registration-artifact"], new     # the E5.5 INVALID, committed
        assert "E5.5" in str(e), e                                           # by opening_manifest_check
    elif want_invalid:
        assert [x.subject for x in new] == ["reason/registration-artifact"]
    else:
        assert new == [] and "INVALID" not in str(e)                         # refusal, no new INVALID, no work
    assert (tmp_path / "s1_out").is_dir()


def _opening_consumer(tmp_path):
    """H4 D-5 (the brief's R-G note): the opening close with slot 45 crashed after its INTENT and slot 47 QUALIFIED;
    slot 45 TIMEOUT at D through s1_slot.finalize_close, so _opening_stage reaches its _resolution_evidence call."""
    import s1_checkpoint as ck
    from test_s1_a3_prestart import crashed_opening
    o = crashed_opening(tmp_path)
    out = tmp_path / "s1_out"
    gv = t.Gate(tmp_path, out, t.open_trial(mb(tmp_path)), jrows(tmp_path), "ACTIVE", mb(tmp_path))
    sl.finalize_close(gv, o["day"], o["cal"], lambda: o["d45"], mailbox=mb(tmp_path))
    q = [x for x in jrows(tmp_path) if x.kind == "SLOT-QUALIFIED"][0]
    member = sl.names(out, sl.slot_of(q.subject), o["oc"])["capture"] / "backup.sqlite3"
    now = o["d45"] + timedelta(seconds=1)

    def call():
        gv_ = t.Gate(tmp_path, out, t.open_trial(mb(tmp_path)), jrows(tmp_path), "ACTIVE", mb(tmp_path))
        return ck._opening_stage(gv_, out, o["day"], o["cal"], lambda: now, mb(tmp_path))
    return member, call


@pytest.mark.parametrize("consumer", ["slot-problems", "seal-recompute", "run-seal-stage", "sampled-seals",
                                      "opening-stage", "decide-stop"])
def test_read_classification_all_consumers(tmp_path, monkeypatch, consumer):              # row 497 (CL-A18)
    """C5.2: the same rule at every QUALIFIED-tree consumer - a PermissionError on a member refuses with no INVALID;
    a confirmed changed member is the violation. Each consumer is called directly, below the gate (H4 D-5: the
    fixture of each parameter reaches that consumer's member read)."""
    root = tmp_path
    out = root / "s1_out"
    if consumer == "opening-stage":
        member, call = _opening_consumer(tmp_path)
    else:
        st_ = three_qualified(tmp_path, seal_stage=(consumer != "run-seal-stage"))
        cal = st_["calendar"]
        member = trees(tmp_path)[0]                                          # d0's QUALIFIED tree (H4 D-5: its own
        sub = "slot/" + member.parent.name                                   # QUALIFIED row, not the opening's q[0])
        day = sl.day_for(sl.slot_of(sub), cal)
        if consumer == "seal-recompute":                                     # only the OQ-14 recomputation reads it
            monkeypatch.setattr(sl, "slot_problems", lambda *a, **kw: [])
        call = {"slot-problems": lambda: sl.slot_problems(out, jrows(root), sub, cal),
                "seal-recompute": lambda: sl.evidence_problems(out, jrows(root), cal),
                "run-seal-stage": lambda: sl.run_seal_stage(
                    t.Gate(root, out, t.open_trial(mb(root)), jrows(root), "ACTIVE", mb(root)), day, cal,
                    mailbox=mb(root), clock=lambda: st_["now"]),
                "sampled-seals": lambda: z.sampled_seals(out, jrows(root), cal, c.aware(START)),
                "decide-stop": lambda: z.decide_stop(
                    t.Gate(root, out, t.open_trial(mb(root)), jrows(root), "ACTIVE", mb(root)), cal,
                    c.aware(START), lambda: st_["now"], mailbox=mb(root))}[consumer]
    for variant in ("permission", "changed"):
        before = [x.sha for x in jrows(root)]
        with monkeypatch.context() as m:
            if variant == "permission":
                n = _member_reads(m, member, [_err(PermissionError(13, "denied (simulated)"))])
            else:
                saved = member.read_bytes()
                member.write_bytes(saved + b"x")
            try:
                got = call()
            except (SystemExit, sl.QualifiedEvidence) as ex:                 # H4 D-6: caught here, so the RED is
                got = ex                                                     # an assertion below (B3)
            if variant == "permission":
                assert n[0] >= 1, "the consumer never read the member"
                assert isinstance(got, SystemExit) or (isinstance(got, dict) and got.get("refused")), got
                assert no_new_invalid(root, before)
            else:
                flagged = (isinstance(got, sl.QualifiedEvidence) or
                           (isinstance(got, list) and got) or
                           [x for x in jrows(root) if x.kind == "TRIAL-INVALID" and x.sha not in before])
                if consumer == "decide-stop":                                # C5.2: already a refusal there; the
                    assert isinstance(got, SystemExit), got                  # violation is the gate's (F3 table)
                else:
                    assert flagged, (consumer, got)                          # the integrity violation path
                member.write_bytes(saved)


# ---------------------------------------------------------------- supplementary (no map row; H4 D-9)
# C5.2 names "all consumers": two callers of stop_record catch SystemExit and would turn QualifiedUnreadable into a
# value (a stop problem, a score abort). They re-raise it: an unreadable QUALIFIED member is a refusal there too.
def test_c5_stop_problems_reraises_unreadable(tmp_path, monkeypatch):
    s1_state(tmp_path, START, upto="after-stop")
    out = tmp_path / "s1_out"
    pr = c.load_json(out / "prereg.json")
    assert z.stop_problems(out, c.aware(pr["start"]), pr["calendar"], mailbox=mb(tmp_path)) == []     # healthy
    _member_reads(monkeypatch, trees(tmp_path)[0], [_err(PermissionError(13, "denied (simulated)"))])
    with pytest.raises(sl.QualifiedUnreadable, match=r"unreadable \(PermissionError\)"):
        z.stop_problems(out, c.aware(pr["start"]), pr["calendar"], mailbox=mb(tmp_path))


def test_c5_score_attempt_reraises_unreadable(monkeypatch):
    import s1_run as r

    class Sw:
        trial_id, mailbox = "t", None
        gv = type("G", (), {"out": Path("unused")})()

        def put(self, *a):
            raise AssertionError("no ABORTED s1.json may be staged for an unreadable member")

    def unreadable(out, mailbox):
        raise sl.QualifiedUnreadable("QUALIFIED member x unreadable (PermissionError)")
    monkeypatch.setattr(r, "_score", unreadable)
    with pytest.raises(sl.QualifiedUnreadable, match=r"unreadable"):
        r._score_attempt(Sw())


# ---------------------------------------------------------------- H4 fix round 1 (review I-1, M-1, M-2, M-6)
# Clarification 1 C5.1: "an unrelated mandatory INVALID keeps its precedence: an I/O refusal never masks it" and
# "a confirming-pass I/O error cannot confirm"; Task 7 I1: confirm on re-read before any registration-artifact INVALID.
def _gv(root):
    return t.Gate(root, root / "s1_out", t.open_trial(mb(root)), jrows(root), "ACTIVE", mb(root))


def _new_invalids(root, before):
    return [x.subject for x in jrows(root) if x.kind == "TRIAL-INVALID" and x.sha not in before]


def test_fix1_gate_unreadable_refusal_after_e55(tmp_path, monkeypatch):
    """review I-1: evidence_check returns the gate's unreadable observations (a local value, never raised there and
    never stored on the gate); the gate raises the C5 refusal only after opening_manifest_check (E5.5) has run."""
    three_qualified(tmp_path)
    before = [x.sha for x in jrows(tmp_path)]
    _member_reads(monkeypatch, trees(tmp_path)[0], [_err(PermissionError(13, "denied (simulated)"))])
    gv = _gv(tmp_path)
    try:
        got = sl.evidence_check(gv)
    except SystemExit as e:                                               # B3: the RED is an assertion here
        pytest.fail(f"evidence_check raised the C5 refusal itself ({e}) instead of returning it")
    assert isinstance(got, list) and got and all("unreadable (PermissionError)" in u for u in got), got   # (the
    # member is read by slot_problems and by the OQ-14 recomputation: one observation each)
    assert not any(v is got for v in vars(gv).values())
    calls = []
    real = t.opening_manifest_check
    monkeypatch.setattr(t, "opening_manifest_check", lambda gv_, *a: calls.append(1) or real(gv_, *a))
    e = gate_outcome(tmp_path, "probe")
    assert calls == [1], calls                                            # E5.5 ran before the C5 refusal
    assert isinstance(e, t.Refusal) and "unreadable" in str(e) and "INVALID" not in str(e), e
    assert _new_invalids(tmp_path, before) == []


@pytest.mark.parametrize("e55", ["e55-mismatch", "e55-healthy"])
def test_fix1_stop_gap_unreadable_never_masks_e55(tmp_path, monkeypatch, e55):
    """review I-1, the same clause for the other hook between the F3 table and E5.5: a QualifiedUnreadable from the
    F2.3 publication-gap recompute is held until opening_manifest_check has run. E5.5 mismatch: its INVALID commits;
    E5.5 healthy: the held C5 refusal, no INVALID."""
    import s1_seal
    three_qualified(tmp_path)
    before = [x.sha for x in jrows(tmp_path)]

    def gap(gv, **kw):                                                    # (fix round 2: the gate passes publish=)
        raise sl.QualifiedUnreadable("QUALIFIED member x unreadable (PermissionError) (simulated)")
    monkeypatch.setattr(s1_seal, "stop_gap_recover", gap)
    if e55 == "e55-mismatch":
        monkeypatch.setattr(t, "_manifest_sha", lambda root, rows, seq: "0" * 64)
    e = gate_outcome(tmp_path, "probe")
    new = _new_invalids(tmp_path, before)
    if e55 == "e55-mismatch":
        assert new == ["reason/registration-artifact"] and "E5.5" in str(e), (new, e)
    else:
        assert new == [] and isinstance(e, sl.QualifiedUnreadable), (new, e)


@pytest.mark.parametrize("other", ["confirmed-violation", "no-other-damage"])
def test_fix1_qualified_probe_error_never_masks(tmp_path, monkeypatch, other):
    """review M-1 (the reviewer's A8 scenario): the existence probe of a QUALIFIED slot - whose decision never uses
    it - is not run, so its I/O error cannot refuse ahead of an unrelated confirmed violation (C5.1 precedence).
    Control: with no other damage the gate is not turned into an INVALID and no raw exception escapes."""
    three_qualified(tmp_path)
    a, b = trees(tmp_path)[0], trees(tmp_path)[2]
    if other == "confirmed-violation":
        b.write_bytes(b.read_bytes() + b"x")                              # a confirmable violation on slot B
    a_report = a.parent.parent / f"{a.parent.name}.report.json"
    assert a_report.exists()
    before = [x.sha for x in jrows(tmp_path)]
    real = Path.exists

    def ex(self, *aa, **kw):
        if self == a_report:
            raise PermissionError(13, "probe denied (simulated)")
        return real(self, *aa, **kw)
    monkeypatch.setattr(Path, "exists", ex)
    e = gate_outcome(tmp_path, "probe")
    new = _new_invalids(tmp_path, before)
    if other == "confirmed-violation":
        assert new == ["reason/registration-artifact"], (new, e)
        assert isinstance(e, SystemExit) and "INVALID (registration-artifact)" in str(e), e
    else:
        assert new == [] and (e is None or "INVALID" not in str(e)), (new, e)


@pytest.mark.parametrize("second", ["permission", "readable"])
def test_fix1_confirming_pass_unreadable_refuses(tmp_path, monkeypatch, second):
    """review M-2 (kills mutant R3): in confirmed_close_problems a problem seen in pass 1 whose member is unreadable in
    the confirming pass is not confirmed and refuses (QualifiedUnreadable), never []. Control: readable in both
    passes, the changed member is confirmed."""
    st_ = three_qualified(tmp_path)
    cal, out = st_["calendar"], tmp_path / "s1_out"
    member = trees(tmp_path)[0]
    member.write_bytes(member.read_bytes() + b"x")                        # pass 1: changed (a problem)
    day = sl.day_for(sl.slot_of("slot/" + member.parent.name), cal)
    before = [x.sha for x in jrows(tmp_path)]
    steps = [_ok, _err(PermissionError(13, "denied (simulated)"))] if second == "permission" else [_ok]
    gv = _gv(tmp_path)
    n = _member_reads(monkeypatch, member, steps)
    if second == "permission":
        with pytest.raises(sl.QualifiedUnreadable, match=r"unreadable \(PermissionError\)"):
            sl.confirmed_close_problems(gv, out, jrows(tmp_path), day, cal, mb(tmp_path))
        assert n[0] == 2, n                                               # one read per pass
    else:
        got = sl.confirmed_close_problems(gv, out, jrows(tmp_path), day, cal, mb(tmp_path))
        assert len(got) == 1 and "QUALIFIED tree differs" in got[0], got
    assert _new_invalids(tmp_path, before) == []


@pytest.mark.parametrize("case", ["missing-once", "changed-once", "missing-twice"])
def test_fix1_opening_stage_confirms_on_reread(tmp_path, monkeypatch, case):
    """review M-6: the opening consumer's _resolution_evidence observation is confirmed on a re-read before any
    TRIAL-INVALID. One observation (missing or changed once, healthy on the re-read) refuses with no row and no
    opening seal; the same violation on both reads is the F3 violation (QualifiedEvidence for the callers, which
    commit the INVALID)."""
    member, call = _opening_consumer(tmp_path)
    out = tmp_path / "s1_out"
    before = [x.sha for x in jrows(tmp_path)]
    real_re, seen = sl._resolution_evidence, []

    def faulty(p, real):
        if case.startswith("missing"):
            raise FileNotFoundError(2, "gone (simulated)")
        return real(p) + b"x"

    def re_(*a, **kw):                                                    # the member is faulted on the first
        seen.append(1)                                                    # _resolution_evidence read (and on the
        if len(seen) == 1 or case == "missing-twice":                     # second, for missing-twice) only
            with monkeypatch.context() as m:
                _member_reads(m, member, [faulty])
                return real_re(*a, **kw)
        return real_re(*a, **kw)
    monkeypatch.setattr(sl, "_resolution_evidence", re_)
    try:
        got = call()
    except (SystemExit, sl.QualifiedEvidence) as ex:
        got = ex
    if case == "missing-twice":
        assert isinstance(got, sl.QualifiedEvidence), got                 # confirmed: the callers' F3 INVALID
    else:
        assert not isinstance(got, sl.QualifiedEvidence), got             # one observation never invalidates
        assert len(seen) == 2, seen                                       # re-read before deciding
        assert isinstance(got, dict) and "refused" in got, got            # refused with no row
        import s1_stage
        assert s1_stage.stage_rows(jrows(tmp_path), "opening")["intent"] is None
    assert _new_invalids(tmp_path, before) == []


# ---------------------------------------------------------------- H4 fix round 2 (re-review F-1; controller ruling)
# A refusal path does no work: no row and no file publication. With a C5 unreadable refusal pending, the F2.3
# publication-gap recovery still recomputes (a stop-conflict INVALID keeps its precedence) but never persists stop.json.
def _gap_state(tmp_path):
    st_ = s1_state(tmp_path, START, score_ready=True, stop_attest=False, final=False)
    (tmp_path / "s1_out" / "stop.json").unlink()                         # the recoverable publication gap (F2.3)
    return st_


def _unreadable_during_f3(monkeypatch, member):
    """The member is unreadable only while the gate's F3 table (evidence_check) runs: the C5 refusal is pending, and
    the later F2.3 recompute can read every tree (so only the pending refusal can stop the publication)."""
    real = sl.evidence_check

    def ec(gv):
        with monkeypatch.context() as m:
            _member_reads(m, member, [_err(PermissionError(13, "denied (simulated)"))])
            return real(gv)
    monkeypatch.setattr(sl, "evidence_check", ec)


@pytest.mark.parametrize("case", ["pending-refusal-no-publish", "pending-refusal-conflict-invalid-wins",
                                  "no-refusal-publishes"])
def test_fix2_stop_gap_publication_never_on_a_refusal_path(tmp_path, monkeypatch, case):
    _gap_state(tmp_path)
    out = tmp_path / "s1_out"
    stop = j.first(jrows(tmp_path), "TRIAL-STOP")
    assert stop is not None and not (out / "stop.json").exists()
    before = [x.sha for x in jrows(tmp_path)]
    if case != "no-refusal-publishes":
        _unreadable_during_f3(monkeypatch, trees(tmp_path)[0])
    if case == "pending-refusal-conflict-invalid-wins":
        monkeypatch.setattr(z, "stop_record", lambda *a, **kw: None)     # the recompute differs: stop-conflict
    if case == "pending-refusal-no-publish":
        with pytest.raises(t.Refusal, match=r"QUALIFIED member read\(s\) unreadable .*Clarification 1 C5\.1"):
            t.gate(tmp_path, "gap")
        assert not (out / "stop.json").exists()                          # no publication on the refusal path
        assert _new_invalids(tmp_path, before) == []
    elif case == "pending-refusal-conflict-invalid-wins":
        with pytest.raises(SystemExit, match=r"publication gap: the recomputed stop record differs: INVALID "
                                             r"\(stop-conflict\)"):
            t.gate(tmp_path, "gap")
        assert _new_invalids(tmp_path, before) == ["reason/stop-conflict"]
        assert not (out / "stop.json").exists()
    else:
        t.gate(tmp_path, "gap")                                          # healthy: the gap is recovered
        assert j.detail_of(json.loads((out / "stop.json").read_text(encoding="utf-8"))) == stop.detail
        assert _new_invalids(tmp_path, before) == []
