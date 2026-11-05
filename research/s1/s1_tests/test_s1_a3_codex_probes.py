"""Addendum 3 rev 5 F10 'Codex probes': the new tests for the frozen historical probes (copies and hashes in
s1_evidence/a3/codex_probes_historical/, never collected). Old -> new map: plan 'Codex probe old -> new map' and
s1_evidence/a3/codex_probes_old_new.md. Synthetic journal fixtures; tmp mailboxes; spies."""
import json
import os
import shutil
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
import s1_checkpoint as ck
import s1_common as c
import s1_journal as j
import s1_run as r
import s1_seal as z
import s1_slot as sl  # noqa: F401 (the slot worker under test, Task 6)
import s1_trial as t
from conftest import S1_PROCESS, S1_RECEIPT, Spies, _Clock, s1_ack, s1_jappend, s1_state  # noqa: F401 (s1_jappend: Task 7 appends, P41)

START = "2026-10-26T13:30:00+00:00"
HIST = Path(__file__).resolve().parent.parent / "s1_evidence" / "a3" / "codex_probes_historical"
FROZEN = {"test_codex_publication.py": "3c81f41fc08ff171881e62c5bddc1dc27e16aaa9b23c033a95a2f172c240b2b9",
          "test_codex_registration.py": "98ec8af58edd8d7535f4cc9689c3cff99e35e15f356d8500457c2d155f0b055e",
          "test_codex_combined_damage.py": "418a9594f2b9c7a3716a2f8e663c20a9494f268e43bae7220fbfce0645fd53c1"}


def test_historical_probe_copies_are_frozen():
    for name, sha in FROZEN.items():
        assert c.sha256_file(HIST / name) == sha
    sums = dict(reversed(line.split(" *", 1)) if " *" in line else reversed(line.split("  ", 1))
                for line in (HIST / "SHA256SUMS").read_text(encoding="utf-8").splitlines() if line.strip())
    assert all(c.sha256_file(HIST / n) == h for n, h in sums.items()) and len(sums) >= 12
    assert set(sums) == {p.name for p in HIST.iterdir() if p.name != "SHA256SUMS"}       # nothing unlisted
    assert json.loads((HIST / "bundle-bootstrap-missing.json").read_text(encoding="utf-8"))["restoration_resumes"]


def test_historical_probe_copies_are_never_collected(tmp_path):
    """The frozen copies are evidence: a pytest run over their folder (with the suite's `-p conftest`) collects
    nothing. The child only collects (no fixture or test body runs, so it opens no mailbox, ledger or network)."""
    here = Path(__file__).resolve().parent
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(here.parent), str(here)]))
    p = subprocess.run([sys.executable, "-m", "pytest", "-p", "conftest", "-p", "no:cacheprovider", "--collect-only",
                        "-q", str(HIST)], capture_output=True, text=True, env=env, cwd=str(tmp_path), timeout=120)
    assert p.returncode == 5 and "no tests collected" in p.stdout, (p.returncode, p.stdout[-800:], p.stderr[-800:])


@pytest.mark.parametrize("auth_damage", ["missing", "unparseable"])
def test_combined_damage_is_invalid_bundle_after_any_journal_row(tmp_path, monkeypatch, auth_damage):
    state = s1_state(tmp_path, START)
    with _Clock(state["prereg_at"]):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    out = tmp_path / "s1_out"
    copy = tmp_path / "bundle-copy"
    for rel in (*c.BUNDLE_CODE, *c.DOC_PINS):
        (copy / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(c.HERE / rel, copy / rel)
    monkeypatch.setattr(c, "HERE", copy)
    code = copy / "s1_checkpoint.py"
    saved_code = code.read_bytes()
    code.write_bytes(saved_code + b"\n# synthetic observed bundle change\n")
    damaged = [out / "prereg.json", out / "audit" / "manifest.json"]
    saved = {p: p.read_bytes() for p in damaged}
    for p in damaged:
        if auth_damage == "missing":
            p.unlink()
        else:
            p.write_text("{not JSON", encoding="utf-8")
    sp = Spies(monkeypatch)
    at = state["start"] - timedelta(hours=1)
    with _Clock(at), pytest.raises(t.Refusal, match=r"INVALID \(bundle\)"):
        t.gate(tmp_path, "Codex combined-damage probe")
    assert c.load_abort(out)["reason"] == "bundle"
    for p, b in saved.items():
        p.write_bytes(b)
    code.write_bytes(saved_code)
    (out / "aborted.json").unlink()
    with _Clock(at + timedelta(minutes=1)), pytest.raises(t.Refusal, match=r"trial INVALID \(reason/bundle\)"):
        t.gate(tmp_path, "Codex restored probe")
    sp.assert_zero()


def _publication(tmp_path, monkeypatch, offset_us):
    """Old: test_codex_publication.exercise (frozen copy). New: the clock is moved to D + offset just before the
    report - the last file of P - is published, so R = D + offset."""
    st_ = s1_state(tmp_path, START)
    with _Clock(st_["prereg_at"]):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    s1_ack(tmp_path, "prereg-ack", "S1-PREREG-ACK", st_["prereg_at"] + timedelta(minutes=1))
    day = next(d for d in st_["calendar"] if d["date"] == "2026-10-26")
    sch = z.close_of(day["date"], st_["calendar"]) + timedelta(minutes=45)
    dl = z.resolution_deadline(sch, day, st_["calendar"])
    clock = [sch + timedelta(seconds=30)]
    target = f"{sch:%Y%m%dT%H%M%SZ}.report.json"
    real = c.publish_exclusive

    def delayed(path, data, **kw):
        if offset_us is not None and Path(path).name == target:
            clock[0] = dl + timedelta(microseconds=offset_us)
        return real(path, data, **kw)
    monkeypatch.setattr(c, "publish_exclusive", delayed)
    with _Clock(clock[0]):
        rep = ck.run_checkpoint(tmp_path, st_["ledger"].path, sch, lambda reference=None: S1_RECEIPT,
                                lambda: dict(S1_PROCESS), tmp_path / "crash.log", now=lambda: clock[0])
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    got = [x.kind for x in j.subject_rows(j.read_trial(tr.trial_id, tr.genesis, tmp_path / "mailbox.sqlite3"),
                                          j.slot_subject(sch))]
    return rep, got, (tmp_path / "s1_out" / "seals" / f"{day['date']}.json").exists()


def test_publication_d_minus_1us_qualifies_when_no_timeout_committed_first(tmp_path, monkeypatch):
    rep, got, sealed = _publication(tmp_path, monkeypatch, -1)
    assert got == ["SLOT-INTENT", "SLOT-QUALIFIED"] and sealed


@pytest.mark.parametrize("offset_us", [0, 1])
def test_publication_at_d_and_d_plus_1us_does_not_seal(tmp_path, monkeypatch, offset_us):
    rep, got, sealed = _publication(tmp_path, monkeypatch, offset_us)
    assert got == ["SLOT-INTENT"] and not sealed and rep["journal"]["outcome"] == "REFUSE"


def test_publication_well_before_d_seals(tmp_path, monkeypatch):
    rep, got, sealed = _publication(tmp_path, monkeypatch, None)
    assert got == ["SLOT-INTENT", "SLOT-QUALIFIED"] and sealed


# ---------------------------------------------------------------- A3 Task 7: the P/R/J/T races (F10 CH2, Erratum 1 E1)
from test_s1_a3_slots import first_slot, registered, rows as journal_rows, run as run_slot, slot_rows  # noqa: E402


def _fin(tmp_path, st_, day, at):
    gv = t.gate(tmp_path, "probe finalizer", defer_pending=True)
    with _Clock(at):
        return sl.finalize_close(gv, day, st_["calendar"], lambda: at, mailbox=tmp_path / "mailbox.sqlite3")


def test_race_t_commits_then_j_is_lost_race(tmp_path, monkeypatch):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    d = z.resolution_deadline(sch, day, st_["calendar"])
    real = sl.Worker._append

    def t_first(self, req):
        if req.kind == "SLOT-QUALIFIED":
            intent = j.first(j.subject_rows(journal_rows(tmp_path), self.subject), "SLOT-INTENT")
            s1_jappend(tmp_path, "SLOT-TIMEOUT", self.subject, op=intent.op, at=d, due=True)
        return real(self, req)
    monkeypatch.setattr(sl.Worker, "_append", t_first)
    res = run_slot(tmp_path, st_, sch, sch + timedelta(seconds=30))
    assert res["journal"]["outcome"] == "LOST-RACE"
    assert [k_ for k_, *_ in slot_rows(tmp_path, sch)] == ["SLOT-INTENT", "SLOT-TIMEOUT"]
    assert not (tmp_path / "s1_out" / "seals" / f"{day['date']}.json").exists()
    assert all(x.kind != "TRIAL-INVALID" for x in journal_rows(tmp_path))


def test_race_j_commits_then_stale_t_is_lost_race(tmp_path):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    run_slot(tmp_path, st_, sch, sch + timedelta(seconds=30))
    _fin(tmp_path, st_, day, z.resolution_deadline(sch, day, st_["calendar"]))
    assert [k_ for k_, *_ in slot_rows(tmp_path, sch)] == ["SLOT-INTENT", "SLOT-QUALIFIED"]


FINALIZE = r'''
import sys
sys.path.insert(0, sys.argv[1])
import s1_common as c, s1_slot as sl, s1_trial as t
c.MAILBOX = sys.argv[2] + "/mailbox.sqlite3"
at = c.aware(sys.argv[3]); c.now_utc = lambda: at
import json
cal = json.loads(open(sys.argv[4], encoding="utf-8").read())
day = next(d for d in cal if d["date"] == sys.argv[5])
gv = t.gate(sys.argv[2], "child finalizer", defer_pending=True)
import os, time                                       # fix round 1 (review M5): a file barrier - both children have
from pathlib import Path                              # passed their gate before either finalizer appends
bar = Path(sys.argv[6])
(bar / f"ready-{os.getpid()}").write_text("1")
deadline = time.monotonic() + 60
while len(list(bar.glob("ready-*"))) < 2:
    if time.monotonic() > deadline:
        sys.exit("barrier timeout")
    time.sleep(0.01)
print(json.dumps(sl.finalize_close(gv, day, cal, lambda: at, mailbox=c.MAILBOX), default=str), flush=True)
'''


def test_race_two_finalizers_one_terminal(tmp_path):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    d = z.resolution_deadline(sch, day, st_["calendar"])
    s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(sch), at=sch + timedelta(seconds=1))
    cal_p = tmp_path / "cal.json"
    cal_p.write_text(json.dumps(st_["calendar"]), encoding="utf-8")
    bar = tmp_path / "barrier"
    bar.mkdir()
    args = [sys.executable, "-I", "-c", FINALIZE, str(Path(c.HERE)), str(tmp_path), d.isoformat(), str(cal_p),
            day["date"], str(bar)]
    procs = [subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    outs = [p.communicate(timeout=120) for p in procs]
    assert all(p.returncode == 0 for p in procs), outs
    assert len(list(bar.glob("ready-*"))) == 2                       # both reached the barrier (they overlapped)
    got = [json.loads(o.strip().splitlines()[-1]) for o, _ in outs]
    assert all(g["refused"] is None for g in got), got
    kinds_ = [k_ for k_, *_ in slot_rows(tmp_path, sch)]
    assert kinds_.count("SLOT-TIMEOUT") == 1 and kinds_[0] == "SLOT-INTENT"
    assert all(x.kind != "TRIAL-INVALID" for x in journal_rows(tmp_path))


CRASH = r'''
import os, sys
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[1] + "/s1_tests")
import s1_common as c, s1_checkpoint as ck, s1_journal as j
c.MAILBOX = sys.argv[2] + "/mailbox.sqlite3"
at = c.aware(sys.argv[4]); c.now_utc = lambda: at
real = j.append
def crash(trial_id, gen, req, ctx_fn, **kw):
    if req.kind == "SLOT-QUALIFIED":
        os._exit(9)
    return real(trial_id, gen, req, ctx_fn, **kw)
j.append = crash
from conftest import S1_RECEIPT, S1_PROCESS
ck.run_checkpoint(sys.argv[2], sys.argv[3], c.aware(sys.argv[5]), lambda reference=None: S1_RECEIPT,
                  lambda: dict(S1_PROCESS), sys.argv[2] + "/crash.log", now=lambda: at)
'''


def test_race_p_without_j_restart_ends_in_timeout(tmp_path):
    st_ = registered(tmp_path)
    day, sch = first_slot(st_)
    at = sch + timedelta(seconds=30)
    p = subprocess.run([sys.executable, "-I", "-c", CRASH, str(Path(c.HERE)), str(tmp_path), str(st_["ledger"].path),
                        at.isoformat(), sch.isoformat()], capture_output=True, text=True, timeout=120)
    assert p.returncode == 9, p.stderr
    with pytest.raises(SystemExit, match="never re-intents"):
        run_slot(tmp_path, st_, sch, at + timedelta(seconds=30))
    _fin(tmp_path, st_, day, z.resolution_deadline(sch, day, st_["calendar"]))
    assert [k_ for k_, *_ in slot_rows(tmp_path, sch)] == ["SLOT-INTENT", "SLOT-TIMEOUT"]


# ---------------------------------------------------------------- A3 Task 10: V1, "A fully deleted then B", prereg
import shutil as _sh  # noqa: E402
import s1_checkpoint as ck_  # noqa: E402
from conftest import Ledger, S1_PROCESS as P_, s1_opening_checkpoint, s1_plan_audit  # noqa: E402,F401


def _opened(tmp_path):
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    lg = Ledger(tmp_path / "ledger.sqlite3")
    s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT)
    return start, cal, oc, lg


def test_v1_selective_deletion_is_invalid(tmp_path, monkeypatch):                      # row 177 (B-old)
    start, cal, oc, lg = _opened(tmp_path)
    out = tmp_path / "s1_out"
    first = z.schedule(next(d for d in cal if d["date"] == oc), cal)[0]
    name = f"{first:%Y%m%dT%H%M%SZ}"
    for p in [out / "seals" / f"{oc}.json", *c.stage_records(out, "opening"), out / "opening_receipt.json",
              out / "captures" / oc / f"{name}.resolution.json", out / "captures" / oc / f"{name}.report.json"]:
        p.unlink()                                            # the historical V1 deletion set (frozen copy)
    later = z.close_of(oc, cal) + timedelta(hours=4)
    sp = Spies(monkeypatch)
    changed = json.loads(json.dumps(S1_RECEIPT))
    changed["fingerprint"]["config"] = {"synthetic_changed_setting": "different"}
    with _Clock(later), pytest.raises(SystemExit, match=r"stage opening: .*INVALID \(stage-replaced\)"):
        ck_.run_opening_checkpoint(tmp_path, lg.path, later, sp.receipt(changed), sp.process(), tmp_path / "c.log",
                                   now=lambda: later)
    with _Clock(c.aware(START) - timedelta(days=1)), pytest.raises(SystemExit,
                                                                  match=r"trial INVALID \(reason/stage-replaced\)"):
        r.attest_start(tmp_path, r.START_STATEMENT, changed)
    sp.assert_zero()


def test_a_fully_deleted_then_b_is_invalid_or_never_ack_eligible(tmp_path, monkeypatch):   # row 178 (B-old)
    import s1_collect as k_
    start, cal, oc, lg = _opened(tmp_path)
    _sh.rmtree(tmp_path / "s1_out")
    with _Clock(c.aware(START) - timedelta(days=3)), pytest.raises(SystemExit, match="open"):
        k_.write_plan(tmp_path, c.aware(START) + timedelta(days=7), "2026-10-30", [], "2026-10-01")    # B
    sp = Spies(monkeypatch)
    later = z.close_of(oc, cal) + timedelta(hours=4)
    with _Clock(later), pytest.raises(SystemExit, match=r"INVALID \(LOST\)"):
        ck_.run_opening_checkpoint(tmp_path, lg.path, later, sp.receipt(), sp.process(), tmp_path / "c.log",
                                   now=lambda: later)
    sp.assert_zero()
    with pytest.raises(SystemExit, match=r"trial INVALID \(reason/LOST\)"):
        t.opening_issuance(tmp_path, tmp_path / "mailbox.sqlite3")


def test_prereg_restoration_is_invalid_once_created(tmp_path, monkeypatch):            # row 180 (B-old)
    st_ = s1_state(tmp_path, START)
    with _Clock(st_["prereg_at"]):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    out = tmp_path / "s1_out"
    files = [out / "prereg.json", *c.stage_records(out, "prereg")]
    saved = {p: p.read_bytes() for p in files}
    for p in files:
        p.unlink()
    with _Clock(st_["prereg_at"] + timedelta(minutes=1)), pytest.raises(SystemExit,
                                                                       match=r"stage prereg: .*INVALID \(stage-replaced\)"):
        t.gate(tmp_path, "Codex synthetic probe")
    for p, b in saved.items():
        p.write_bytes(b)
    (out / "aborted.json").unlink(missing_ok=True)
    sp = Spies(monkeypatch)
    with _Clock(st_["prereg_at"] + timedelta(minutes=2)), pytest.raises(SystemExit,
                                                                       match=r"trial INVALID \(reason/stage-replaced\)"):
        t.gate(tmp_path, "Codex synthetic probe")
    sp.assert_zero()


@pytest.mark.parametrize("crash", ["intent-only-free", "prepared-free"])
def test_prereg_before_created_follows_the_stage_table(tmp_path, monkeypatch, crash):    # row 180
    st_ = s1_state(tmp_path, START)
    real = j.append
    stop_after = "STAGE-INTENT" if crash == "intent-only-free" else "STAGE-PREPARED"
    crashed = []

    def crashing(trial_id, gen, req, ctx_fn, **kw):
        res = real(trial_id, gen, req, ctx_fn, **kw)
        if req.kind == stop_after and req.subject == "stage/prereg":
            crashed.append(req.kind)
            raise KeyboardInterrupt                               # a crash (the lock is released on unwind)
        return res
    monkeypatch.setattr(j, "append", crashing)
    try:
        with _Clock(st_["prereg_at"]):
            r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    except KeyboardInterrupt:
        pass
    monkeypatch.setattr(j, "append", real)
    assert crashed == [stop_after]                                # (A3 Task 10: the crash happened, by assertion)
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    if crash == "intent-only-free":
        with pytest.raises(SystemExit, match=r"INVALID \(stage-incomplete\)"):
            t.gate(tmp_path, "probe")
    else:
        t.gate(tmp_path, "probe")
        rows = j.read_trial(tr.trial_id, tr.genesis, tmp_path / "mailbox.sqlite3")
        assert [x.kind for x in j.subject_rows(rows, "stage/prereg")][-1:] == ["STAGE-CREATED"]
