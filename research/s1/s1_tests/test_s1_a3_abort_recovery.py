"""Erratum 2 r4 G6 (O12 items 1-7, O16, O17, O18): a surviving local abort is recorded by the common trial gate
(established-violation / local-abort, bound to the witness bytes, at = the transaction clock), through a
request-scoped ANY-INVALID conditional append, before any requested work; I/O errors refuse; the helper chain never
recreates s1_out. Map rows 460-466, 468, 469 (H1); row 467 is added by H2. Plus the OP-16 bundle pin of the two
frozen documents. Behavioural RED against the H1 stub (s1_evidence/a3/tH1_red.txt); semantic mutants m1-m4 in
s1_evidence/a3/tH1_mutants.txt."""
import json
import shutil
import sqlite3
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
import s1_common as c
import s1_journal as j
import s1_run as r
import s1_trial as t
from conftest import Spies, _Clock, s1_ack, s1_jappend, s1_state

START = "2026-10-26T13:30:00+00:00"
HERE = Path(__file__).resolve().parent.parent
EV = r"INVALID \(established-violation\)"
LOTS20 = [{"symbol": f"S{i % 5}", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (1, 120.0)} for i in range(20)]
BRANCH = {"stopped": {}, "timeout": {"lots": LOTS20}, "nvs": {"lots": [], "seal_days": []}}
WITNESS = {"reason": "semantic receipt changed", "observed_utc": "2026-10-27T21:00:00+00:00", "actual": None,
           "close": None, "scheduled": None, "projection_sha256": None, "receipt_sha256": None}
ERRATUM2 = "883f09be8471b9da7ee2c01c026ea90f9cec37515d79f3863e8c72085caa6d87"
CLARIFICATION1 = "2ccb8a287de533f08dcbf1e919afb04add8d5a60a0088dfd370649689009e10d"


def mb(root):
    return Path(root) / "mailbox.sqlite3"


def jrows(root):
    trs = t.trials(t.scan(mb(root)))
    (tid,) = [x for x, tr_ in trs.items() if tr_.closed is None]
    return j.read_trial(tid, trs[tid].genesis, mb(root))


def invalids(root):
    return [x for x in jrows(root) if x.kind == "TRIAL-INVALID"]


def put_witness(root, data: bytes):
    (Path(root) / "s1_out" / "aborted.json").write_bytes(data)
    return data


def evidence_of(root, row):
    return json.loads((Path(root) / "s1_out" / "invalid" / f"{row.seq}.json").read_bytes())


def score_calls(monkeypatch):
    calls, real = [], r._score
    monkeypatch.setattr(r, "_score", lambda *a, **kw: calls.append(1) or real(*a, **kw))
    return calls


def no_score_work(root, sp, calls):
    assert j.subject_rows(jrows(root), j.stage_subject("score")) == [] and calls == []
    assert not (Path(root) / "s1_out" / "score").exists()
    sp.assert_zero()


def damage_qualified(root):
    """A post-START QUALIFIED capture's backup.sqlite3 changed (F3: registration-artifact once confirmed)."""
    p = next(p for p in sorted((Path(root) / "s1_out" / "captures").glob("2026-10-2[6-9]/*/backup.sqlite3")))
    p.write_bytes(p.read_bytes() + b"x")
    return p


# ---------------------------------------------------------------- OP-16: the frozen documents join the bundle
def test_bundle_pins_the_adopted_erratum2_and_clarification1():                                    # OP-16
    assert c.DOC_PINS.get("docs/s1_design_v5_addendum3_erratum2.md") == ERRATUM2
    assert c.DOC_PINS.get("docs/s1_design_v5_addendum3_erratum2_clarification1.md") == CLARIFICATION1
    assert c.sha256_file(HERE / "docs" / "s1_design_v5_addendum3_erratum2.md") == ERRATUM2
    assert c.sha256_file(HERE / "docs" / "s1_design_v5_addendum3_erratum2_clarification1.md") == CLARIFICATION1
    m = c.bundle_manifest()
    assert m["docs"]["docs/s1_design_v5_addendum3_erratum2.md"] == ERRATUM2 and c.bundle_problems(m) == []


# ---------------------------------------------------------------- row 460 (AB-A1)
@pytest.mark.parametrize("branch", ["nvs", "stopped", "timeout"])
def test_surviving_abort_recorded_once_then_refused(tmp_path, monkeypatch, branch):            # row 460 (AB-A1)
    st_ = s1_state(tmp_path, START, score_ready=True, **BRANCH[branch])
    data = put_witness(tmp_path, json.dumps(WITNESS, indent=1).encode("utf-8"))
    sp, calls = Spies(monkeypatch), score_calls(monkeypatch)
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=EV):
        r.score(tmp_path, "score-ack")
    (inv,) = invalids(tmp_path)
    rec = evidence_of(tmp_path, inv)
    assert inv.subject == "reason/established-violation" and inv.detail == j.detail_of(rec)
    assert rec["subtype"] == t.LOCAL_ABORT and rec["abort_sha256"] == c.sha256_bytes(data)
    assert rec["original_reason"] == WITNESS["reason"] and rec["original_observed_utc"] == WITNESS["observed_utc"]
    assert rec["trial_id"] == inv.trial_id and "recovery_observed_utc" in rec
    assert inv.at == j.fmt_at(st_["now"])                         # the transaction clock, never the witness time
    assert (tmp_path / "s1_out" / "aborted.json").read_bytes() == data          # first-wins bytes untouched
    assert t.close_evidence("INVALID", rows=jrows(tmp_path)) == inv.sha        # CLOSE INVALID binds this line
    no_score_work(tmp_path, sp, calls)


# ---------------------------------------------------------------- row 461 (AB-A2)
def test_already_invalid_reentry_no_recovery_row(tmp_path, monkeypatch):                        # row 461 (AB-A2)
    st_ = s1_state(tmp_path, START, score_ready=True)
    first = s1_jappend(tmp_path, "TRIAL-INVALID", "reason/stage-replaced", at=st_["now"], detail="a" * 64)
    put_witness(tmp_path, json.dumps(WITNESS).encode("utf-8"))
    sp, calls = Spies(monkeypatch), score_calls(monkeypatch)
    for _ in range(2):
        with _Clock(st_["now"] + timedelta(minutes=1)), pytest.raises(SystemExit, match=r"trial INVALID"):
            r.score(tmp_path, "score-ack")
    assert [x.sha for x in invalids(tmp_path)] == [first.sha]          # no recovery row; first reason preserved
    no_score_work(tmp_path, sp, calls)


# ---------------------------------------------------------------- row 462 (AB-A3): real processes, real arbitration
RECOVERER = r'''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import s1_common as c, s1_journal as j, s1_receipt, s1_trial as t
root = sys.argv[2]
c.MAILBOX = Path(root) / "mailbox.sqlite3"
s1_receipt.HMAC_KEY = Path(root) / "s1_receipt_hmac.key"
at = c.aware(sys.argv[3])
c.now_utc = lambda: at
real = j.append
def held(trial_id, gen, req, ctx_fn, **kw):
    if req.kind == "TRIAL-INVALID":            # barrier: after both witness reads, before BEGIN IMMEDIATE
        print("held", flush=True)
        sys.stdin.readline()
    return real(trial_id, gen, req, ctx_fn, **kw)
j.append = held
try:
    t.gate(root, "child recoverer")
    print("PASSED", flush=True)
except SystemExit as e:
    print("REFUSED " + " ".join(str(e).split()), flush=True)
'''


def recoverer(root, at):
    p = subprocess.Popen([sys.executable, "-I", "-c", RECOVERER, str(HERE), str(root), at.isoformat()],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    first = p.stdout.readline().strip()
    if first != "held":
        p.stdin.close()
        p.wait(timeout=60)
    assert first == "held", first
    return p


def release(p):
    p.stdin.write("\n")
    p.stdin.flush()
    out = p.stdout.readline().strip()
    p.wait(timeout=60)
    return out


@pytest.mark.parametrize("case", ["same-witness", "different-reason-invalid"])
def test_concurrent_recovery_arbitration(tmp_path, case):                                     # row 462 (AB-A3)
    """Real processes, real BEGIN IMMEDIATE arbitration (no mocked pre-read). Kills m1 (pre-read-only idempotence)
    and m2 (same-subtype/same-witness-only condition)."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    put_witness(tmp_path, json.dumps(WITNESS).encode("utf-8"))
    if case == "same-witness":
        a = recoverer(tmp_path, st_["now"])
        b = recoverer(tmp_path, st_["now"])                         # both have read the witness twice, neither row
        outs = [release(a), release(b)]
        inv = invalids(tmp_path)
        assert [x.subject for x in inv] == ["reason/established-violation"]          # exactly one recovery row
        assert sorted(o.split()[0] for o in outs) == ["REFUSED", "REFUSED"]          # both refuse their command
        assert sum("established-violation" in o for o in outs) == 1                  # the loser recorded nothing
    else:
        a = recoverer(tmp_path, st_["now"])
        other = s1_jappend(tmp_path, "TRIAL-INVALID", "reason/bundle", at=st_["now"], detail="b" * 64)
        out = release(a)
        assert out.startswith("REFUSED") and "established-violation" not in out
        assert [x.sha for x in invalids(tmp_path)] == [other.sha]                    # zero recovery rows
    assert not (tmp_path / "s1_out" / "score").exists()


# ---------------------------------------------------------------- row 463 (AB-A4)
CRASHER = r'''
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import s1_common as c, s1_journal as j, s1_receipt, s1_trial as t
root = sys.argv[2]
c.MAILBOX = Path(root) / "mailbox.sqlite3"
s1_receipt.HMAC_KEY = Path(root) / "s1_receipt_hmac.key"
at = c.aware(sys.argv[3])
c.now_utc = lambda: at
real = j.append
def crash_after_commit(trial_id, gen, req, ctx_fn, **kw):
    res = real(trial_id, gen, req, ctx_fn, **kw)
    if req.kind == "TRIAL-INVALID":
        os._exit(9)                            # crash: the INVALID committed, aborted.json not yet published
    return res
j.append = crash_after_commit
t.gate(root, "child detector")
'''


def test_crash_after_invalid_before_abort_publication(tmp_path, monkeypatch):                 # row 463 (AB-A4)
    st_ = s1_state(tmp_path, START, score_ready=True)
    bad = damage_qualified(tmp_path)
    good = bad.read_bytes()[:-1]
    rc = subprocess.run([sys.executable, "-I", "-c", CRASHER, str(HERE), str(tmp_path), st_["now"].isoformat()],
                        timeout=120).returncode
    assert rc == 9 and not (tmp_path / "s1_out" / "aborted.json").exists()
    (inv,) = invalids(tmp_path)
    sp, calls = Spies(monkeypatch), score_calls(monkeypatch)
    bad.write_bytes(good)                                          # restoring the file never resumes the trial
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=r"trial INVALID"):
        r.score(tmp_path, "score-ack")
    assert [x.sha for x in invalids(tmp_path)] == [inv.sha]
    no_score_work(tmp_path, sp, calls)


# ---------------------------------------------------------------- row 464 (AB-A5)
@pytest.mark.parametrize("case", ["local-witness-kept", "local-publish-fails"])
def test_journal_outage_keeps_witness_then_commits_once(tmp_path, monkeypatch, case):         # row 464 (AB-A5)
    st_ = s1_state(tmp_path, START, score_ready=True)
    damage_qualified(tmp_path)
    real_append, real_pub = j.append, c.publish_exclusive

    def down(trial_id, gen, req, ctx_fn, **kw):
        if req.kind == "TRIAL-INVALID":
            raise j.Outage("mailbox not writable (simulated): no row")
        return real_append(trial_id, gen, req, ctx_fn, **kw)
    monkeypatch.setattr(j, "append", down)
    if case == "local-publish-fails":
        def no_abort(path, data, **kw):
            if Path(path).name == "aborted.json":
                raise PermissionError(13, "denied (simulated)")
            return real_pub(path, data, **kw)
        monkeypatch.setattr(c, "publish_exclusive", no_abort)
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=r"journal could not be written") as e:
        t.gate(tmp_path, "probe")
    assert invalids(tmp_path) == []                                 # no external claim
    abort_p = tmp_path / "s1_out" / "aborted.json"
    if case == "local-publish-fails":
        assert not abort_p.exists() and "local abort not published" in str(e.value)     # truthful (G6.3)
        return
    assert "local abort published" in str(e.value)
    data = abort_p.read_bytes()
    assert json.loads(data)["reason"] == "uncommitted registration-artifact"
    monkeypatch.setattr(j, "append", real_append)                   # the journal recovers
    with _Clock(st_["now"] + timedelta(minutes=1)), pytest.raises(SystemExit, match=EV):
        t.gate(tmp_path, "probe")
    with _Clock(st_["now"] + timedelta(minutes=2)), pytest.raises(SystemExit, match=r"trial INVALID"):
        t.gate(tmp_path, "probe")
    (inv,) = invalids(tmp_path)                                     # exactly one commit
    rec = evidence_of(tmp_path, inv)
    assert inv.subject == "reason/established-violation"
    assert rec["abort_sha256"] == c.sha256_bytes(data)
    assert rec["original_reason"] == "uncommitted registration-artifact"     # provenance only, never the row reason


# ---------------------------------------------------------------- row 465 (AB-A6)
def _fork(root):
    """A second journal row with the last row's seq and prev but a different op (a fork: duplicate seq, another line
    sha), inserted raw into the TEST's tmp mailbox (never through j.append, which would refuse it). The line keeps
    the frozen F0.2 grammar (op is 32 lower-case hex)."""
    con = sqlite3.connect(mb(root))
    body, created = con.execute("SELECT body, created FROM messages WHERE request_key='experiments-s1-journal' "
                                "ORDER BY created DESC LIMIT 1").fetchone()
    head, rest = body.split(" op=", 1)
    assert rest[:32] != "e" * 32
    forked = f"{head} op={'e' * 32}{rest[32:]}"                       # same seq/prev, another op -> another line sha
    j.parse_line(forked)                                              # well-formed (the fork is the only defect)
    con.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,NULL)",
                ("fork-row", "s1", "codex", "experiments-s1-journal", forked, created + 1))
    con.commit()
    con.close()


def _foreign_root(root):
    """Another trial's root: a copy of s1_out whose plan names another trial_id, with no s1_staging (none of THIS
    trial's journal-bound audit artifacts, ruling T14b I-1), and the witness inside it."""
    theirs = Path(root) / "theirs"
    shutil.copytree(Path(root) / "s1_out", theirs / "s1_out")
    plan = json.loads((theirs / "s1_out" / "plan.json").read_text(encoding="utf-8"))
    (theirs / "s1_out" / "plan.json").write_text(
        json.dumps(dict(plan, trial_id="0" * 8 + "-0000-4000-8000-" + "0" * 12)), encoding="utf-8")
    return theirs


IDENTITY = {"foreign-root": r"differs from the AUDIT-ACK's .*\(F6\.2\)", "no-trial": r"zero open trials",
            "forked-chain": r"duplicate seq \(a fork\)", "closed": r"zero open trials",
            "bundle-mismatch": r"INVALID \(bundle\)", "missing-s1-out": r"INVALID \(LOST\)"}


@pytest.mark.parametrize("case", list(IDENTITY))
def test_no_guessed_invalid_on_identity_failures(tmp_path, monkeypatch, case):              # row 465 (AB-A6)
    st_ = s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    put_witness(tmp_path, json.dumps(WITNESS).encode("utf-8"))
    before = [x.sha for x in invalids(tmp_path)]
    gated = tmp_path
    if case == "foreign-root":
        gated = _foreign_root(tmp_path)
    elif case == "no-trial":
        con = sqlite3.connect(mb(tmp_path))
        con.execute("DELETE FROM messages WHERE body LIKE 'S1-AUDIT-ACK %'")
        con.commit()
        con.close()
    elif case == "forked-chain":
        _fork(tmp_path)
    elif case == "closed":
        s1_ack(tmp_path, "close", "S1-CLOSE-ACK", st_["now"], reason="WITHDRAWN", evidence_sha256="0" * 64)
    elif case == "bundle-mismatch":
        monkeypatch.setattr(c, "bundle_sha256", lambda: "f" * 64)
    else:
        shutil.rmtree(out)
    with _Clock(st_["now"] + timedelta(minutes=1)), pytest.raises(SystemExit, match=IDENTITY[case]) as e:
        t.gate(gated, "probe")
    assert "established-violation" not in str(e.value)
    if case in ("no-trial", "closed"):
        return                                                       # (no open trial: no row can be read or added)
    after = [x for x in j.read_trial(*_tid_gen(tmp_path), mb(tmp_path)) if x.kind == "TRIAL-INVALID"] \
        if case != "forked-chain" else []
    assert all(x.subject != "reason/established-violation" for x in after)       # never a fabricated local-abort
    new = [x.subject for x in after if x.sha not in before]
    if case == "foreign-root":
        assert new == [] and (gated / "s1_out" / "aborted.json").exists()
    if case == "bundle-mismatch":
        assert new == ["reason/bundle"]
    if case == "missing-s1-out":
        assert new == ["reason/LOST"] and not out.exists()


def _tid_gen(root):
    trs = t.trials(t.scan(mb(root)))
    (tid,) = list(trs)
    return tid, trs[tid].genesis


# ---------------------------------------------------------------- row 466 (AB-A7)
def _reads(monkeypatch, steps):
    """Path.read_bytes of s1_out/aborted.json follows `steps` (one callable per read; the last one repeats)."""
    real, n = Path.read_bytes, [0]

    def rb(self):
        if self.name == "aborted.json" and self.parent.name == "s1_out":
            f = steps[min(n[0], len(steps) - 1)]
            n[0] += 1
            return f(self, real)
        return real(self)
    monkeypatch.setattr(Path, "read_bytes", rb)
    return n


def _raise(exc):
    def f(p, real):
        raise exc
    return f


def _then(action):
    def f(p, real):
        b = real(p)
        action(p, b)
        return b
    return f


INTEGRITY = {"permission-error-persistent": r"aborted\.json unreadable \(PermissionError\)",
             "read-error-persistent": r"aborted\.json unreadable \(OSError\)",
             "malformed-confirmed": EV,
             "changed-between-reads": r"aborted\.json unconfirmed \(changed or deleted between reads\)",
             "deleted-between-reads": r"aborted\.json unconfirmed \(changed or deleted between reads\)",
             "valid-residual-once": EV,
             "healthy-absence": None}


@pytest.mark.parametrize("case", list(INTEGRITY))
def test_witness_integrity(tmp_path, monkeypatch, case):                                      # row 466 (AB-A7)
    st_ = s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    good = json.dumps(WITNESS).encode("utf-8")
    if case != "healthy-absence":
        put_witness(tmp_path, b'{"reason": "x"' if case == "malformed-confirmed" else good)
    steps = {"permission-error-persistent": [_raise(PermissionError(13, "sharing violation (simulated)"))],
             "read-error-persistent": [_raise(OSError(5, "I/O error (simulated)"))],
             "changed-between-reads": [_then(lambda p, b: p.write_bytes(b + b" ")), lambda p, real: real(p)],
             "deleted-between-reads": [_then(lambda p, b: p.unlink()), lambda p, real: real(p)]}.get(case)
    n = _reads(monkeypatch, steps) if steps else None
    sp, calls = Spies(monkeypatch), score_calls(monkeypatch)
    if case == "healthy-absence":
        with _Clock(st_["now"]):
            assert t.gate(tmp_path, "probe").state == "STOPPED"     # proceeds through its normal gates
        assert invalids(tmp_path) == [] and not (out / "aborted.json").exists()
        return
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=INTEGRITY[case]) as e:
        r.score(tmp_path, "score-ack")
    inv = invalids(tmp_path)
    if case in ("permission-error-persistent", "read-error-persistent", "changed-between-reads",
                "deleted-between-reads"):
        assert inv == [] and "established-violation" not in str(e.value)          # refusal, no row, no guess
        if case in ("permission-error-persistent", "read-error-persistent"):
            with open(out / "aborted.json", "rb") as f:                            # (past the read_bytes patch)
                assert n[0] >= 1 and f.read() == good                             # untouched, never repaired
    else:
        assert [x.subject for x in inv] == ["reason/established-violation"]
        rec = evidence_of(tmp_path, inv[0])
        assert rec["subtype"] == t.LOCAL_ABORT and rec["abort_sha256"] == c.sha256_file(out / "aborted.json")
        if case == "malformed-confirmed":
            assert rec["malformation"] == "unparseable JSON" and "original_reason" not in rec
        else:                                                         # valid residual: recorded once, never again
            with _Clock(st_["now"] + timedelta(minutes=1)), pytest.raises(SystemExit, match=r"trial INVALID"):
                r.score(tmp_path, "score-ack")
            assert len(invalids(tmp_path)) == 1
    assert out.is_dir()                                               # never recreated / never removed
    no_score_work(tmp_path, sp, calls)


# ---------------------------------------------------------------- row 468 (AB-A9)
@pytest.mark.parametrize("case", ["root-missing-at-entry", "root-vanishes-before-publish",
                                  "root-vanishes-before-evidence-copy", "existing-root-first-wins"])
def test_no_s1_out_recreation(tmp_path, monkeypatch, case):                                  # row 468 (AB-A9)
    """The actual helper chain (write_abort -> publish_text_exclusive -> publish_exclusive, and invalidate's
    invalid/<seq>.json copy); the barriers wrap the REAL helpers and forward every keyword (no mkdir spy alone)."""
    out = tmp_path / "s1_out"
    rec = dict(WITNESS, reason="probe")
    if case == "root-missing-at-entry":
        with pytest.raises(c.OutputRootGone, match=r"s1_out is gone"):
            c.write_abort(out, rec)
        assert not out.exists()
        return
    if case == "root-vanishes-before-publish":
        out.mkdir()
        real = c.publish_exclusive

        def vanish(path, data, **kw):
            shutil.rmtree(out)                                       # the root disappears after any caller check
            return real(path, data, **kw)
        monkeypatch.setattr(c, "publish_exclusive", vanish)
        with pytest.raises(c.OutputRootGone, match=r"s1_out is gone"):
            c.write_abort(out, rec)
        assert not out.exists()
        return
    s1_state(tmp_path, START, score_ready=True)
    if case == "root-vanishes-before-evidence-copy":
        real = c.publish_exclusive

        def vanish_copy(path, data, **kw):
            if Path(path).parent.name == "invalid":                  # after invalidate's is_dir() caller guard
                shutil.rmtree(out)
            return real(path, data, **kw)
        monkeypatch.setattr(c, "publish_exclusive", vanish_copy)
        tr = t.open_trial(mb(tmp_path))
        res = t.invalidate(tr, "stage-replaced", {"where": "probe"}, root=tmp_path, mailbox=mb(tmp_path))
        assert res.outcome == "APPEND" and not out.exists()          # the copy is not published; the row stands
        assert [x.sha for x in invalids(tmp_path)] == [res.row.sha]
        return
    assert not (out / "aborted.json").exists() and not (out / "invalid").exists()
    stored = c.write_abort(out, rec)
    again = c.write_abort(out, dict(rec, reason="later writer"))
    assert stored == rec and again == rec                            # later writers preserve the first witness
    assert json.loads((out / "aborted.json").read_text(encoding="utf-8")) == rec
    tr = t.open_trial(mb(tmp_path))
    res = t.invalidate(tr, "stage-replaced", {"where": "probe"}, root=tmp_path, mailbox=mb(tmp_path))
    assert (out / "invalid" / f"{res.row.seq}.json").read_bytes() == c.canonical({"where": "probe"})


# ---------------------------------------------------------------- row 469 (AB-A10)
def test_default_extra_invalid_observation_still_appends(tmp_path):                         # row 469 (AB-A10)
    st_ = s1_state(tmp_path, START, score_ready=True)
    first = s1_jappend(tmp_path, "TRIAL-INVALID", "reason/bundle", at=st_["now"], detail="a" * 64)
    tr = t.open_trial(mb(tmp_path))
    extra = t.invalidate(tr, "stage-replaced", {"where": "extra"}, root=tmp_path, mailbox=mb(tmp_path))
    assert extra.outcome == "APPEND" and extra.row.subject == "reason/stage-replaced"     # unchanged F0.5 step 3
    rec = t.invalidate(tr, "established-violation", {"subtype": t.LOCAL_ABORT}, root=tmp_path,
                       mailbox=mb(tmp_path), recovery=True)
    assert rec.outcome == "REFUSE" and rec.row is None                                    # the recovery-only rule
    assert [x.sha for x in invalids(tmp_path)] == [first.sha, extra.row.sha]
    rows, now = jrows(tmp_path), c.aware(START)
    req = j.Request("TRIAL-INVALID", "reason/established-violation", "1" * 32, "2" * 32, detail="c" * 64)
    assert j.decide(rows, req, j.Context(), now).outcome == "APPEND"
    assert j.decide(rows, req, j.Context(recovery=True), now).outcome == "REFUSE"
    assert j.decide(rows, req, j.Context(closed=True, recovery=True), now).reason.startswith("trial CLOSED")
