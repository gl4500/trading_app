"""Task 12 fix round 3 (re-review 1 of fix round 2: C-1, C-2, I-1, I-2 and the minor findings M-1, M-2, M-3).
Written BEFORE the fix; behavioural RED per item in s1_evidence/t12_fix3_<id>_red.txt. Every reviewer probe
(scratchpad/probe/test_probe*.py) is a permanent test here. Races are made deterministic with an injected pause
inside the write (threading.Event, no sleeps); time is an injected aware clock. Synthetic only: tmp_path ledgers,
mailbox and HMAC key; no live DB, network, real mailbox or scheduler."""
import ast
import json
import shutil
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import s1_checkpoint as ck
import s1_collect as k
import s1_common as c
import s1_run as r
import s1_seal as z
import s1_slot as sl
import s1_trial as t
from conftest import s1_prereg_ack  # A3 Task 6
from conftest import S1_PROCESS, S1_RECEIPT, Ledger, _Clock, s1_mailbox, s1_opening_checkpoint, s1_plan_audit, \
    s1_finalize, s1_reack, s1_state
from test_s1_t12_a5_a6 import S45, S47, SEAL_P, Snap
from test_s1_t12_a5_a6 import _registered as _registered_mon
from test_s1_t12_fix2_b1 import Clock, Killed, _day, _setup, bg, res_path, run
from test_s1_t12_fix2_b3 import OPENING, Spies, _aborted, _cp, _refusals
from test_s1_t12_fix2_b3 import _registered as _registered_b3

UTC = timezone.utc
HERE = Path(__file__).resolve().parent.parent
START = "2026-10-26T13:30:00+00:00"
START_DT = datetime(2026, 10, 26, 13, 30, tzinfo=UTC)
WAIT = 20                                            # seconds a synchronization wait may block (never a sleep)
D45 = S45 + timedelta(minutes=40)                    # E45 = S45 + 10 min, D45 = E45 + 30 min

# A3 Task 7: the legacy registration detector's abort OR the F3 evidence table's registration-artifact INVALID
# (the same disposition; the F3 table reads the journal-bound QUALIFIED tree first)
REG_OR_F3 = (r"(registration artifact\(s\) missing or changed|QUALIFIED tree differs from the committed detail.*"
             r"INVALID \(registration-artifact\))")


def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


# ====================================================================== C-1 deterministic publication races
class _Paused:
    """A file object whose FIRST write stops halfway (a writer preempted mid-write: the first half is flushed to the
    OS, so any reader of that path can see it) until the test releases it."""

    def __init__(self, f, paused, resume):
        self._f, self._paused, self._resume, self._done = f, paused, resume, False

    def write(self, data):
        if self._done:
            return self._f.write(data)
        self._done = True
        half = max(1, len(data) // 2)
        n = self._f.write(data[:half])
        self._f.flush()
        self._paused.set()
        assert self._resume.wait(WAIT), "writer never released"
        return n + self._f.write(data[half:])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return self._f.__exit__(*exc)

    def __getattr__(self, name):
        return getattr(self._f, name)


def pause_first_exclusive_write(monkeypatch, where):
    """Hook Path.open: the first exclusive-create ("x") open of a path matching `where` returns a _Paused file.
    Returns (paused, resume) events. Works for a direct exclusive create of the target and for a temporary file of
    an atomic publication alike (the temporary file is named after the target)."""
    paused, resume = threading.Event(), threading.Event()
    real, armed, lock = Path.open, [True], threading.Lock()

    def hooked(self, mode="r", *a, **kw):
        f = real(self, mode, *a, **kw)
        with lock:
            hit = armed[0] and "x" in mode and where(Path(self))
            if hit:
                armed[0] = False
        return _Paused(f, paused, resume) if hit else f
    monkeypatch.setattr(Path, "open", hooked)
    return paused, resume


def _two_successes_no_seal(tmp_path, monkeypatch):
    """Slots 45 and 47 resolved SUCCESS, the slot-45 worker killed before its finalize: no seal yet."""
    st_, clock = _setup(tmp_path, monkeypatch, S47 + timedelta(seconds=30))
    Snap(monkeypatch)
    run(tmp_path, st_, S47, clock)
    real, real_journal = ck.finalize_close, sl.finalize_close

    def crash(*a, **kw):
        raise Killed()
    monkeypatch.setattr(sl, "finalize_close", crash)       # A3 Task 7: the worker path's journal finalizer
    clock.t = S45 + timedelta(minutes=4)
    with pytest.raises(Killed):
        run(tmp_path, st_, S45, clock)
    monkeypatch.setattr(sl, "finalize_close", real_journal)
    assert read(res_path(tmp_path, S45))["outcome"] == "SUCCESS" and not SEAL_P(tmp_path).exists()
    return st_, real


def test_c1_a_concurrent_finalizer_and_a_reader_never_observe_a_partial_seal(tmp_path, monkeypatch):
    """C-1 (B1.4/B1.6): finalizer A is preempted halfway through writing the seal. A seal reader and a second
    finalizer B running in that window must not see a partial seal: no "seal differs" ValueError (which the
    checkpoint turns into a persistent abort) and no unreadable-seal failure; exactly one finalizer writes the seal,
    both report its sha256, and it is slot 45's."""
    st_, real = _two_successes_no_seal(tmp_path, monkeypatch)
    out, day, cal = tmp_path / "s1_out", _day(st_), st_["calendar"]
    paused, resume = pause_first_exclusive_write(monkeypatch, lambda p: p.parent.name == "seals")
    t = S45 + timedelta(minutes=5)
    th, box = bg(lambda: real(out, day, cal, t))
    assert paused.wait(WAIT), "finalizer A never wrote the seal"
    seals, why = ck._read_seals(out, {})
    try:
        mine, err = real(out, day, cal, t), None
    except Exception as e:                                    # noqa: BLE001 - the outcome under test
        mine, err = None, e
    resume.set()
    th.join(WAIT)
    assert why is None, f"a seal reader observed a partial seal: {why}"
    assert err is None, f"finalizer B observed a partial seal: {err!r}"
    assert "err" not in box, box
    assert sum(1 for x in (mine, box["rep"]) if x["written"]) == 1, (mine, box["rep"])
    # A3 Task 7 (E2.1 r3, F5.1): the seal is the seal/<close> stage - finalizer B, inside A's publication window,
    # finds the stage lock held and is refused "pending" (no partial seal observed, no second seal); A reports it
    assert box["rep"]["sha256"] == c.sha256_file(SEAL_P(tmp_path))
    assert mine["sha256"] is None and "pending" in str(mine["refused"]), mine
    assert read(SEAL_P(tmp_path))["capture"]["scheduled"] == S45.isoformat()


def test_c1_a_concurrent_stop_decision_never_observes_a_partial_stop_json(tmp_path, monkeypatch):
    """C-1 (A2.1): the trial has ended; command A is preempted halfway through persisting stop.json. Command B's
    stop decision in that window must not read a partial stop.json (a JSONDecodeError = ValueError, which callers
    turn into an abort): it returns the same terminal stop, and the stored stop is registered consistently."""
    st_ = s1_state(tmp_path, START, score_ready=True, stop_attest=False, final=False)
    out, t = tmp_path / "s1_out", st_["stop_attested_at"]
    assert not (out / "stop.json").exists()
    paused, resume = pause_first_exclusive_write(monkeypatch, lambda p: "stop.json" in p.name
                                                 and p.parent.name == "s1_out")
    th, box = bg(lambda: z.current_stop(out, st_["start"], st_["calendar"], t, "command A"))
    assert paused.wait(WAIT), "command A never wrote stop.json"
    try:
        mine, err = z.current_stop(out, st_["start"], st_["calendar"], t, "command B"), None
    except Exception as e:                                    # noqa: BLE001 - the outcome under test
        mine, err = None, e
    resume.set()
    th.join(WAIT)
    assert err is None, f"command B observed a partial stop.json: {err!r}"
    assert "err" not in box, box
    assert mine["status"] == box["rep"]["status"] == st_["stop"]["status"] == z.load_stop(out)["status"]
    assert c.registration_problems(out) == []


def test_c1_a_concurrent_abort_writer_never_loses_the_real_reason(tmp_path, monkeypatch):
    """C-1 (B3.4): writer A is preempted halfway through aborted.json; writer B in that window must not read the
    partial file as the CORRUPT marker (losing the real reason): both writers return one stored, readable abort."""
    out = tmp_path / "s1_out"
    out.mkdir()
    paused, resume = pause_first_exclusive_write(monkeypatch, lambda p: "aborted.json" in p.name)
    th, box = bg(lambda: c.write_abort(out, {"reason": "first", "actual": None}))
    assert paused.wait(WAIT), "writer A never wrote aborted.json"
    mine = c.write_abort(out, {"reason": "second", "actual": None})
    resume.set()
    th.join(WAIT)
    assert "err" not in box, box
    assert not mine.get("corrupt"), f"writer B read a partial aborted.json: {mine}"
    stored = c.load_abort(out)
    assert not stored.get("corrupt") and stored["reason"] in ("first", "second")
    assert box["rep"] == mine == stored


PRODUCT = ("s1_books.py", "s1_checkpoint.py", "s1_collect.py", "s1_common.py", "s1_gates.py", "s1_receipt.py",
           "s1_run.py", "s1_seal.py", "s1_snapshot.py")


def test_c1_every_immutable_artifact_is_published_atomically():
    """C-1: no product code creates an immutable artifact by an exclusive open followed by writes (a partial file is
    then visible): every exclusive create goes through s1_common.publish_exclusive (temporary file + fsync +
    exclusive link), whose own temporary-file open is the only allowed one."""
    bad = []
    for name in PRODUCT:
        tree = ast.parse((HERE / name).read_text(encoding="utf-8"))
        for fn in (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
            if (name, fn.name) == ("s1_common.py", "publish_exclusive"):
                continue
            for n in ast.walk(fn):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "open":
                    mode = n.args[0] if n.args else next((kw.value for kw in n.keywords if kw.arg == "mode"), None)
                    if isinstance(mode, ast.Constant) and isinstance(mode.value, str) and "x" in mode.value:
                        bad.append(f"{name}::{fn.name} line {n.lineno}")
    assert not bad, bad


# ====================================================================== C-2 redundant registration witnesses
REPORTS, RESOLUTIONS = "captures/*/*.report.json", "captures/*/*.resolution.json"
COMBOS = {
    "prereg+registry": ["prereg.json", "registry/prereg.json"],
    "attest+registry": ["attest_start.json", "registry/attest_start.json"],
    "attest+registry+books": ["attest_start.json", "registry/attest_start.json", "opening_books.json"],
    "opening seal+registry": [OPENING, "registry/opening.json"],
    "receipt+registry": ["opening_receipt.json", "registry/opening.json"],
    "plan+registry": ["plan.json", "registry/opening.json"],
    "seals+registry+reports": ["seals", "registry", REPORTS],
    "seals+registry+reports+resolutions": ["seals", "registry", REPORTS, RESOLUTIONS],
    "seals+registry+witnesses+reports+resolutions": ["seals", "registry", "witnesses", REPORTS, RESOLUTIONS],
}


def _delete(out: Path, items) -> list:
    """Delete `items` (files, directories or globs relative to s1_out); returns the deleted relative paths."""
    gone = []
    for it in items:
        for p in (sorted(out.glob(it)) if "*" in it else [out / it]):
            if p.is_dir():
                shutil.rmtree(p)
            elif p.exists():
                p.unlink()
            else:
                continue
            gone.append(p.relative_to(out).as_posix())
    return gone


def _restore(out: Path, backup: Path, gone) -> None:
    for rel in gone:
        src, dst = backup / rel, out / rel
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


@pytest.mark.parametrize("combo", sorted(COMBOS))
def test_c2_deleting_an_artifact_with_its_registry_record_is_a_persistent_abort(tmp_path, combo):
    """C-2 (B3.1/B3.3/B3.5): after registration (opening, START attestation, prereg; the RUN-ACK in the mailbox),
    deleting an artifact TOGETHER WITH its registry record - or whole groups (seals, registry, reports, resolutions,
    the second registration record) - cannot move the trial back to a refusal: the registration is witnessed
    redundantly, the next command records the persistent "registration artifact" abort, and restoring every deleted
    file does not resume the trial (no seal)."""
    st_ = _registered_b3(tmp_path)
    out = tmp_path / "s1_out"
    backup = tmp_path / "backup"
    shutil.copytree(out, backup)
    gone = _delete(out, COMBOS[combo])
    assert gone
    # A3 Task 7 (F3 table): the deleted reports/resolutions are the opening slot's QUALIFIED tree - the gate's F3
    # table commits the same registration-artifact INVALID (and abort) before the legacy detector runs
    with pytest.raises(SystemExit, match=REG_OR_F3):
        _cp(tmp_path, st_["ledger"].path)
    ab = _aborted(tmp_path)
    assert ab["reason"] == "registration artifact", ab
    _restore(out, backup, gone)
    with pytest.raises(t.Refusal, match=r"trial INVALID \(reason/registration-artifact\)"):   # A3 F0.6/F1
        _cp(tmp_path, st_["ledger"].path, minutes=47)


def test_c2_probe_deleting_prereg_and_its_registry_record_then_restoring_never_resumes(tmp_path):
    """C-2 reviewer probe test_delete_prereg_and_its_registry_record: prereg.json and registry/prereg.json deleted ->
    the next checkpoint records the persistent abort (not "no verified prereg"); both restored -> the trial stays
    ABORTED-INVALID and never seals."""
    st_ = s1_state(tmp_path, START)
    with _Clock(START_DT - timedelta(days=1)):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    s1_prereg_ack(tmp_path)                    # A3 Task 6 (F7.4): the PREREG-ACK before captures
    out = tmp_path / "s1_out"
    good, goodreg = (out / "prereg.json").read_bytes(), (out / "registry" / "prereg.json").read_bytes()
    (out / "prereg.json").unlink()
    (out / "registry" / "prereg.json").unlink()
    with pytest.raises(SystemExit, match=r"registration artifact\(s\) missing or changed"):
        _cp(tmp_path, st_["ledger"].path)
    assert _aborted(tmp_path)["reason"] == "registration artifact"
    (out / "prereg.json").write_bytes(good)
    (out / "registry" / "prereg.json").write_bytes(goodreg)
    with pytest.raises(t.Refusal, match=r"trial INVALID \(reason/registration-artifact\)"):   # A3 F0.6/F1
        _cp(tmp_path, st_["ledger"].path, minutes=47)


def test_c2_probe_seals_registry_and_reports_deleted_with_prereg_present_is_an_abort(tmp_path):
    """C-2 reviewer probe test_partial_deletion_with_prereg_present: seals/, registry/ and the capture reports
    deleted while prereg, the START attestation and the resolution records stay -> persistent abort, not the
    RUN-ACK refusal."""
    st_ = s1_state(tmp_path, START)
    with _Clock(START_DT - timedelta(days=1)):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    s1_prereg_ack(tmp_path)                    # A3 Task 6 (F7.4): the PREREG-ACK before captures
    out = tmp_path / "s1_out"
    _delete(out, ["seals", "registry", REPORTS])
    # A3 Task 7 (F3 table): the deleted reports/resolutions are the opening slot's QUALIFIED tree - the gate's F3
    # table commits the same registration-artifact INVALID (and abort) before the legacy detector runs
    with pytest.raises(SystemExit, match=REG_OR_F3):
        _cp(tmp_path, st_["ledger"].path)
    assert _aborted(tmp_path)["reason"] == "registration artifact"


def _only_prereg_left(out: Path) -> None:
    keep = {"plan.json", "prereg.json", "audit"}
    for p in list(out.iterdir()):
        if p.name not in keep:
            shutil.rmtree(p) if p.is_dir() else p.unlink()


def test_c2_the_external_run_ack_witnesses_the_registration_when_every_other_local_witness_is_gone(tmp_path):
    """C-2: every local registration artifact deleted except plan, audit and prereg.json: the externally recorded
    RUN-ACK (codex mailbox, binding this plan) still witnesses the registration -> persistent abort."""
    st_ = _registered_b3(tmp_path)
    _only_prereg_left(tmp_path / "s1_out")
    # A3 Task 7 (F3 table): the deleted reports/resolutions are the opening slot's QUALIFIED tree - the gate's F3
    # table commits the same registration-artifact INVALID (and abort) before the legacy detector runs
    with pytest.raises(SystemExit, match=REG_OR_F3):
        _cp(tmp_path, st_["ledger"].path)
    assert _aborted(tmp_path)["reason"] == "registration artifact"


def test_c2_residual_every_local_witness_gone_and_the_mailbox_unreadable_is_a_refusal(tmp_path, monkeypatch):
    """C-2 DISCLOSED RESIDUAL (documents behaviour; not a closure): the same deletion while the mailbox is
    unreadable leaves one local file (prereg.json) and no readable external ACK - indistinguishable, file-only, from a
    hand-made prereg before the opening (B3.2): a preserved refusal with zero callbacks and no abort. Once the mailbox
    is readable again the RUN-ACK witnesses the registration and the abort is recorded (unless the files were
    restored first - the residual stated in S1_BUILD_EVIDENCE §16)."""
    st_ = _registered_b3(tmp_path)
    _only_prereg_left(tmp_path / "s1_out")
    (tmp_path / "mailbox.sqlite3").rename(tmp_path / "mailbox.away")
    spies = Spies(monkeypatch)
    with pytest.raises(SystemExit, match="inconsistent pre-registration state"):
        _cp(tmp_path, st_["ledger"].path, spies)
    assert spies.zero() and c.load_abort(tmp_path / "s1_out") is None and _refusals(tmp_path)
    (tmp_path / "mailbox.away").rename(tmp_path / "mailbox.sqlite3")
    with pytest.raises(SystemExit, match=REG_OR_F3):            # A3 Task 7: or the F3 table first (same INVALID)
        _cp(tmp_path, st_["ledger"].path, minutes=47)
    assert _aborted(tmp_path)["reason"] == "registration artifact"


def test_c2_deleting_the_persisted_stop_and_its_registry_record_is_a_gate_abort(tmp_path):
    """C-2 (B3.3, post-stop): stop.json and registry/stop.json deleted -> the registration gate itself (before any
    capture) records the persistent "registration artifact" abort; stop.json is never recomputed."""
    from test_s1_t12_a2 import _live_stop
    st_, lg, rows = _live_stop(tmp_path)
    out = tmp_path / "s1_out"
    (out / "stop.json").unlink()
    (out / "registry" / "stop.json").unlink()
    sch = datetime(2026, 10, 28, 20, 45, tzinfo=UTC)
    with (_Clock(sch + timedelta(seconds=30)),
          pytest.raises(SystemExit, match=r"registration artifact\(s\) missing or changed")):
        ck.run_checkpoint(tmp_path, lg.path, sch, lambda: S1_RECEIPT, lambda: dict(S1_PROCESS),
                          tmp_path / "crash.log", now=lambda: sch + timedelta(seconds=30))
    assert _aborted(tmp_path)["reason"] == "registration artifact"
    assert not (out / "stop.json").exists() and not (out / "captures" / "2026-10-28").exists()


def test_c2_a_registered_stage_whose_registry_record_alone_is_deleted_is_detected(tmp_path):
    """C-2 / M-2: the registry record of a stage that is reached (the attestation and prereg exist) deleted alone,
    the artifact intact: missing REQUIRED evidence -> persistent abort (a registry record is never silently absent)."""
    st_ = _registered_b3(tmp_path)
    (tmp_path / "s1_out" / "registry" / "attest_start.json").unlink()
    with pytest.raises(SystemExit, match=r"registration artifact\(s\) missing or changed"):
        _cp(tmp_path, st_["ledger"].path)
    ab = _aborted(tmp_path)
    assert ab["reason"] == "registration artifact" and any("registry/attest_start.json" in x for x in ab["problems"])


# ====================================================================== I-1 SUCCESS without its seal is pending
def _success_without_seal(tmp_path, monkeypatch):
    """Reviewer probe test_probe2: the last eligible close's 08:00 slot publishes SUCCESS and its worker dies before
    the seal (the crash window between _publish and finalize_close)."""
    st_ = _registered_mon(tmp_path)
    cal, start = st_["calendar"], st_["start"]
    last = z.eligible_sessions(start, cal)[-1]
    s8 = z.schedule(last, cal)[-1]
    # A3 Task 6 (F0.5 step 6 with A5.3's E = W = s): the 08:00 slot can never be opened (its SLOT-INTENT at s = E is
    # refused), so the crash-window SUCCESS is the last capturable slot's, 07:00 (E = 07:10); every stop decision
    # below is still taken after W (08:00), as before
    s7 = z.schedule(last, cal)[-2]
    assert z.eligible_until(s8, last, cal) == s8 and s7 == s8 - timedelta(hours=1)
    clock = Clock(s7)
    monkeypatch.setattr(c, "now_utc", clock)
    Snap(monkeypatch, dur=timedelta(0))
    real, real_journal = ck.finalize_close, sl.finalize_close

    def boom(*a, **kw):
        raise Killed()
    monkeypatch.setattr(sl, "finalize_close", boom)        # A3 Task 7: the worker path's journal finalizer
    with pytest.raises(Killed):
        run(tmp_path, st_, s7, clock)
    monkeypatch.setattr(sl, "finalize_close", real_journal)
    out = tmp_path / "s1_out"
    res = out / "captures" / last["date"] / f"{s7.strftime('%Y%m%dT%H%M%SZ')}.resolution.json"
    assert read(res)["outcome"] == "SUCCESS"
    assert not (out / "seals" / f"{last['date']}.json").exists()
    clock.t = s8 + timedelta(minutes=5)
    return st_, last, s8, clock, real


def test_i1_probe_a_success_without_its_seal_is_pending_so_no_stop_is_frozen(tmp_path, monkeypatch):
    """I-1 (B1.4/B1.5) reviewer probe: a stop decision in the crash window must not freeze NO-VALID-SEAL (the SUCCESS
    is not yet applied: the close is PENDING); the finalization afterwards writes the seal and the frozen stop is
    TIMEOUT at that close."""
    st_, last, s8, clock, real = _success_without_seal(tmp_path, monkeypatch)
    out, cal, start = tmp_path / "s1_out", st_["calendar"], st_["start"]
    assert last["date"] in z.pending_closes(out)
    st = z.current_stop(out, start, cal, clock.t, "attest-like")
    assert st["status"] == "RUNNING" and not (out / "stop.json").exists(), st
    fin = real(out, last, cal, s8 + timedelta(minutes=6))
    assert fin["written"] is True, fin
    st = z.current_stop(out, start, cal, s8 + timedelta(minutes=7), "later")
    assert st["status"] == "TIMEOUT" and c.aware(st["stop_close"]) == z.close_of(last["date"], cal), st


def test_i1_the_stop_attestation_finalizes_before_it_freezes_the_stop(tmp_path, monkeypatch):
    """I-1: the stop attestation in the crash window finalizes the serialized selection first: the close is sealed
    and the attested, persisted stop is TIMEOUT at that close (never NO-VALID-SEAL with the seal lost)."""
    st_, last, s8, clock, real = _success_without_seal(tmp_path, monkeypatch)
    out = tmp_path / "s1_out"
    try:                                                  # (strengthened after GREEN: a refusal is the failure)
        rec = r.attest_stop(tmp_path, r.STOP_STATEMENT)
    except SystemExit as e:
        pytest.fail(f"the stop attestation refused instead of finalizing first: {e}")
    assert rec["stop_status"] == "TIMEOUT" and c.aware(rec["stop_close"]) == z.close_of(last["date"],
                                                                                        st_["calendar"])
    assert (out / "seals" / f"{last['date']}.json").exists() and read(out / "stop.json")["status"] == "TIMEOUT"


def test_i1_the_final_plan_finalizes_before_it_freezes_the_stop(tmp_path, monkeypatch):
    """I-1: the final plan in the crash window finalizes first: its stop is the TIMEOUT at the sealed close."""
    st_, last, s8, clock, real = _success_without_seal(tmp_path, monkeypatch)
    try:                                                  # (strengthened after GREEN: a refusal is the failure)
        rec = k.final_plan_record(tmp_path)
    except SystemExit as e:
        pytest.fail(f"the final plan refused instead of finalizing first: {e}")
    assert rec["stop_status"] == "TIMEOUT" and rec["stop_date"] == last["date"], rec


def test_i1_the_score_refuses_while_a_success_lacks_its_seal(tmp_path, monkeypatch):
    """I-1: the score (which does not finalize) refuses in the crash window - the trial is still RUNNING at the close
    level - and freezes nothing (no stop.json, no score reservation)."""
    st_, last, s8, clock, real = _success_without_seal(tmp_path, monkeypatch)
    out = tmp_path / "s1_out"
    s1_finalize(tmp_path, s8)                        # A3 (F7.1): the chain a SCORE-ACK needs (synthetic, test-only)
    s1_reack(tmp_path, "score-early", "S1-SCORE-ACK", s8 + timedelta(minutes=1))
    with pytest.raises(SystemExit, match="RUNNING"):
        r.score(tmp_path, "score-early")
    assert not (out / "stop.json").exists() and not (out / "score").exists()


# ====================================================================== I-2 a stray seal before the opening
@pytest.mark.parametrize("name", ["2026-01-01.json", "2026-10-23.json"])
def test_i2_a_stray_seal_before_the_opening_is_a_preserved_refusal_never_an_abort(tmp_path, monkeypatch, name):
    """I-2 (B3.1/B3.2) reviewer probe test_fabricated_seal_before_opening: with only plan + audit, a stray seal file
    (another date, or the opening close's own date) is not a valid plan/audit-authorized opening seal and witnesses
    no registration: the opening checkpoint refuses (preserved in refusals.jsonl) with zero live callbacks and no
    slot claim, records NO abort, and the legitimate opening runs once the stray file is removed."""
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    out = tmp_path / "s1_out"
    (out / "seals").mkdir(parents=True, exist_ok=True)
    (out / "seals" / name).write_text("{}", encoding="utf-8")
    spies = Spies(monkeypatch)
    lg = Ledger(tmp_path / "l.sqlite3")
    sch = z.close_of(oc, cal) + timedelta(minutes=45)
    with _Clock(sch + timedelta(seconds=30)), pytest.raises(BaseException) as e:
        ck.run_opening_checkpoint(tmp_path, lg.path, sch, spies.receipt, spies.process, tmp_path / "crash.log",
                                  now=lambda: sch + timedelta(seconds=30))
    if name != f"{oc}.json":
        # A3 Task 7 (E2.4 r3, "in every state"): a seal file of a non-opening close with no seal-stage row is a
        # registration artifact once the trial exists: TRIAL-INVALID at the gate, zero callbacks, no claim
        assert isinstance(e.value, SystemExit) and "INVALID (registration-artifact)" in str(e.value), repr(e.value)
        assert f"seal/{name[:-5]}" in str(e.value) and spies.zero() and not (out / "captures").exists()
        return
    # (strengthened after GREEN, for the A10.2 meaningful-kill rule: the refusal itself, not any escaping exception)
    assert isinstance(e.value, SystemExit) and "pre-registration" in str(e.value), repr(e.value)
    assert c.load_abort(out) is None, c.load_abort(out)
    assert spies.zero() and not (out / "captures").exists()
    assert any(x["where"] == "opening checkpoint" for x in _refusals(tmp_path)), _refusals(tmp_path)
    (out / "seals" / name).unlink()
    assert s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT)["seal"]["written"]


def test_i2_a_lone_later_stage_registry_record_before_the_opening_is_a_refusal(tmp_path):
    """I-2 (B3.2): a lone stray registry record of a later stage before any opening is not a registration: refusal,
    no abort."""
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    out = tmp_path / "s1_out"
    (out / "registry").mkdir(parents=True)
    (out / "registry" / "prereg.json").write_text(json.dumps({"stage": "prereg", "artifacts": {}}), encoding="utf-8")
    with pytest.raises(SystemExit, match="inconsistent pre-registration state"):
        s1_opening_checkpoint(tmp_path, Ledger(tmp_path / "l.sqlite3"), oc, cal, S1_RECEIPT)
    assert c.load_abort(out) is None


# ====================================================================== M-1 publication time after the link
def test_m1_a_publication_whose_link_lands_at_or_after_D_records_the_overrun(tmp_path, monkeypatch):
    """M-1 (B1.3): the resolution's timestamp is read before its bytes are published; when the durable link itself
    lands at/after D (a slow fsync), the overrun is recorded (s1_out/captures/<day>/<slot>.overrun.json and the
    report) - it cannot replace the winner (the SUCCESS stays and seals).
    A3 Task 6 (B1.3 -> F3; Codex probe rows 172-174): R is the same-process clock read AFTER P is durable, so a link
    that lands at/after D gives R >= D: the SLOT-QUALIFIED is refused with no row (the finalizer later appends
    TIMEOUT, Task 7) and nothing seals; no .overrun.json record exists any more (the journal decides)."""
    st_, clock = _setup(tmp_path, monkeypatch, S45 + timedelta(seconds=30))
    Snap(monkeypatch)
    real = c.publish_exclusive

    def slow(path, data):
        real(path, data)
        if Path(path).name.endswith(".resolution.json") and S45.strftime("%Y%m%dT%H%M%SZ") in Path(path).name:
            clock.t = D45 + timedelta(seconds=1)              # the link landed after D
    monkeypatch.setattr(c, "publish_exclusive", slow)
    rep = run(tmp_path, st_, S45, clock)
    res = read(res_path(tmp_path, S45))
    assert res["outcome"] == "SUCCESS" and c.aware(res["published_utc"]) < D45
    assert rep["journal"]["outcome"] == "REFUSE" and c.aware(rep["journal"]["R"]) >= D45, rep["journal"]
    assert not res_path(tmp_path, S45).with_name(f"{S45.strftime('%Y%m%dT%H%M%SZ')}.overrun.json").exists()
    assert rep["seal"]["written"] is False and not SEAL_P(tmp_path).exists()


# ====================================================================== M-2 register before the artifact
def test_m2_the_attestation_and_prereg_are_registered_before_their_artifacts_are_published(tmp_path, monkeypatch):
    """M-2 (B3.1): the registry record (and the second registration record) of the START attestation and of prereg
    are published BEFORE the artifact itself (their bytes are known first), so the artifact never exists
    unregistered."""
    order = []
    real = c.publish_exclusive

    def rec(path, data):
        p = Path(path)
        order.append(f"{p.parent.name}/{p.name}")
        return real(path, data)
    monkeypatch.setattr(c, "publish_exclusive", rec)
    s1_state(tmp_path, START)
    with _Clock(START_DT - timedelta(days=1)):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    s1_prereg_ack(tmp_path)                    # A3 Task 6 (F7.4): the PREREG-ACK before captures
    for stage in ("attest_start", "prereg"):
        art = f"s1_out/{stage}.json"
        assert art in order, (stage, order)
        assert order.index(f"registry/{stage}.json") < order.index(art), order
        assert order.index(f"witnesses/{stage}.json") < order.index(art), order


# ====================================================================== M-3 abort -> recorded score
VALUATION = ("simulate_lot", "lot_economics", "baseline_economics", "compare", "paired_bootstrap")


def test_m3_a_registration_abort_before_the_final_snapshot_still_yields_a_recorded_score(tmp_path, monkeypatch):
    """M-3 (A2.3/A9/B3) reviewer probe test_final_snapshot_after_registration_abort: a registration-artifact abort
    observed by the final snapshot (which then refuses: no snapshot) still lets the one score RECORD the trial as
    ABORTED-INVALID - after a SCORE-ACK strictly later than the abort's observation - with zero valuation calls.
    A3 Task 5 (intended, F0.6/F1 + OQ-19): the detection now commits TRIAL-INVALID first, so the score refuses with
    no work and no record (still zero valuation calls)."""
    st_ = s1_state(tmp_path, START, score_ready=True, final_snapshot=False)
    out = tmp_path / "s1_out"
    sim = c.sim()
    called = []
    for name in VALUATION:
        monkeypatch.setattr(sim, name, lambda *a, _n=name, **kw: called.append(_n) or pytest.fail(_n))
    p = out / "attest_start.json"
    p.write_bytes(p.read_bytes() + b"\n")
    t_obs = st_["now"] + timedelta(hours=1)
    monkeypatch.setattr(c, "now_utc", lambda: t_obs)
    with pytest.raises(SystemExit, match="registration not verified"):
        ck.run_final_snapshot(tmp_path, st_["ledger"].path, now=lambda: t_obs)
    assert _aborted(tmp_path)["reason"] == "registration artifact"
    s1_reack(tmp_path, "score-x", "S1-SCORE-ACK", st_["now"] + timedelta(hours=20))
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"] + timedelta(days=1))
    with pytest.raises(t.Refusal, match=r"trial INVALID \(reason/registration-artifact\)"):   # A3 F0.6/F1:
        r.score(tmp_path, "score-x")                    # the committed TRIAL-INVALID refuses the score, no work
    assert called == [] and not (out / "score").exists()


# ====================================================================== RETROSPECTIVE (written after the fix-round-3
# code, for the A10.2 meaningful-kill rule: each isolates one fix-round-3 witness / rule that the tests above reach only
# together with an overlapping one)
def test_c2_retro_the_run_ack_witnesses_the_attestation(tmp_path):
    """RETROSPECTIVE. C-2: before prereg, the attestation AND both its records deleted: the RUN-ACK (it binds an
    attestation) still witnesses the attestation stage -> persistent abort at prereg."""
    s1_state(tmp_path, START)
    out = tmp_path / "s1_out"
    _delete(out, ["attest_start.json", "registry/attest_start.json", "witnesses/attest_start.json"])
    with _Clock(START_DT - timedelta(days=1)), pytest.raises(SystemExit, match="registration artifact"):   # (Task 5)
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    assert _aborted(tmp_path)["reason"] == "registration artifact"


@pytest.mark.skip(reason="HELD with Task 10 (A3 Task 6, OQ-11/E5.2): the opening capture report is final before J and "
                         "no longer records the written seal, so after the seal and both opening records are deleted "
                         "only in-progress witnesses remain; Task 10 makes the opening seal the `opening` stage (a "
                         "deleted CREATED member is stage-replaced)")
def test_c2_retro_the_opening_report_and_resolution_witness_the_registration(tmp_path):
    """RETROSPECTIVE. C-2: after the opening (before the attestation) the opening seal AND both opening records
    deleted: the opening capture report and the opening resolution still witness the registration -> persistent
    abort at the START attestation."""
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    assert s1_opening_checkpoint(tmp_path, Ledger(tmp_path / "l.sqlite3"), oc, cal, S1_RECEIPT)["seal"]["written"]
    out = tmp_path / "s1_out"
    _delete(out, [OPENING, "registry/opening.json", "witnesses/opening.json"])
    with (_Clock(z.close_of(oc, cal) + timedelta(hours=2)),
          pytest.raises(SystemExit, match=r"registration artifact\(s\) missing or changed")):
        r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    assert _aborted(tmp_path)["reason"] == "registration artifact"


def test_c2_retro_prereg_binds_the_attestation_even_when_its_records_are_rewritten(tmp_path):
    """RETROSPECTIVE. C-2: the START attestation changed and BOTH its records rewritten to the new hash: prereg's own
    binding (attest_start_sha256) is a second expected source -> persistent abort naming it."""
    st_ = _registered_b3(tmp_path)
    out = tmp_path / "s1_out"
    p = out / "attest_start.json"
    p.write_bytes(p.read_bytes() + b"\n")
    for rp in (out / "registry" / "attest_start.json", out / "witnesses" / "attest_start.json"):
        rec = read(rp)
        rec["artifacts"]["attest_start.json"] = c.sha256_file(p)
        rp.write_text(json.dumps(rec), encoding="utf-8")
    with pytest.raises(SystemExit, match=r"registration artifact\(s\) missing or changed"):
        _cp(tmp_path, st_["ledger"].path)
    ab = _aborted(tmp_path)
    assert any("bound by prereg.json attest_start_sha256" in x for x in ab["problems"]), ab["problems"]


def test_c2_retro_a_stage_publication_in_progress_is_a_refusal_not_an_abort(tmp_path):
    """RETROSPECTIVE. C-2/M-2: while s1_out/stage.lock exists (a stage's records published, its artifact not yet) the
    gate refuses - preserved, no abort - so a concurrent command never mistakes the in-flight stage for a deletion;
    once the lock is gone the same state is the persistent abort."""
    st_ = _registered_b3(tmp_path)
    out = tmp_path / "s1_out"
    (out / "prereg.json").unlink()
    (out / "stage.lock").write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match="stage publication"):
        _cp(tmp_path, st_["ledger"].path)
    assert c.load_abort(out) is None and _refusals(tmp_path)
    (out / "stage.lock").unlink()
    with pytest.raises(SystemExit, match=r"registration artifact\(s\) missing or changed"):
        _cp(tmp_path, st_["ledger"].path, minutes=47)
    assert _aborted(tmp_path)["reason"] == "registration artifact"


def test_m2_retro_a_concurrent_command_during_the_prereg_publication_refuses(tmp_path, monkeypatch):
    """RETROSPECTIVE. M-2: a command whose gate runs between prereg's records and prereg.json (a concurrent
    checkpoint, simulated inside the publication) refuses ("stage publication") and records no abort; prereg then
    completes."""
    s1_state(tmp_path, START)
    out = tmp_path / "s1_out"
    real = c.publish_exclusive
    seen = []

    def concurrent(path, data):
        if Path(path) == out / "prereg.json":
            try:
                c.registration_gate(out, "concurrent command")
                seen.append("passed")
            except SystemExit as e:
                seen.append(str(e))
        return real(path, data)
    monkeypatch.setattr(c, "publish_exclusive", concurrent)
    with _Clock(START_DT - timedelta(days=1)):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    s1_prereg_ack(tmp_path)                    # A3 Task 6 (F7.4): the PREREG-ACK before captures
    assert len(seen) == 1 and "stage publication" in seen[0], seen
    assert c.load_abort(out) is None and (out / "prereg.json").exists() and not (out / "stage.lock").exists()


def test_c2_retro_the_run_ack_alone_witnesses_the_registration(tmp_path):
    """RETROSPECTIVE. C-2: every local file except plan + audit deleted (prereg too): the external RUN-ACK alone
    witnesses the registration -> persistent abort (not "no verified prereg")."""
    st_ = _registered_b3(tmp_path)
    out = tmp_path / "s1_out"
    _only_prereg_left(out)
    (out / "prereg.json").unlink()
    # A3 Task 7 (F3 table): the deleted reports/resolutions are the opening slot's QUALIFIED tree - the gate's F3
    # table commits the same registration-artifact INVALID (and abort) before the legacy detector runs
    with pytest.raises(SystemExit, match=REG_OR_F3):
        _cp(tmp_path, st_["ledger"].path)
    assert _aborted(tmp_path)["reason"] == "registration artifact"


def test_c2_retro_a_post_start_capture_witnesses_prereg(tmp_path):
    """RETROSPECTIVE. C-2: after a post-START slot was claimed, prereg.json AND both its records deleted: the claim
    (only a verified prereg lets a checkpoint claim one) still reaches the prereg stage -> persistent abort."""
    st_ = _registered_b3(tmp_path)
    out = tmp_path / "s1_out"
    _cp(tmp_path, st_["ledger"].path)
    _delete(out, ["prereg.json", "registry/prereg.json", "witnesses/prereg.json"])
    with pytest.raises(SystemExit, match=r"registration artifact\(s\) missing or changed"):
        _cp(tmp_path, st_["ledger"].path, minutes=47)
    assert _aborted(tmp_path)["reason"] == "registration artifact"


def test_c2_retro_every_stage_is_recorded_twice(tmp_path):
    """RETROSPECTIVE. C-2: every registered stage has both records, identical, binding the artifact's sha256."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    for stage, art in (("opening", OPENING), ("attest_start", "attest_start.json"), ("prereg", "prereg.json"),
                       ("stop", "stop.json")):
        a, b = (out / "registry" / f"{stage}.json"), (out / "witnesses" / f"{stage}.json")
        assert a.exists() and b.exists(), stage
        assert read(a) == read(b) and read(a)["artifacts"][art] == c.sha256_file(out / art), stage


def test_c2_retro_the_stop_records_witness_a_stop_no_report_recorded(tmp_path):
    """RETROSPECTIVE. C-2: a stop persisted by a command that writes no capture report (here the stop decision
    itself), then stop.json deleted: its two records still witness it -> the stop attestation records the persistent
    abort and stop.json is never silently recomputed."""
    st_ = s1_state(tmp_path, START, score_ready=True, stop_attest=False, final=False)
    out, t = tmp_path / "s1_out", st_["stop_attested_at"]
    z.current_stop(out, st_["start"], st_["calendar"], t, "decision")
    (out / "stop.json").unlink()
    with _Clock(t), pytest.raises(SystemExit, match=r"registration artifact\(s\) missing or changed"):
        r.attest_stop(tmp_path, r.STOP_STATEMENT)
    assert _aborted(tmp_path)["reason"] == "registration artifact" and not (out / "stop.json").exists()


def test_c1_retro_an_unreadable_seal_stops_the_checkpoint_before_any_seal(tmp_path, monkeypatch):
    """RETROSPECTIVE. I-4b/C-1: an unreadable seal record that no capture report binds (the gate cannot see it): the
    checkpoint aborts on the corrupt record BEFORE its own close can be sealed (no fence check was possible)."""
    from conftest import _write_seal
    st_ = _registered_b3(tmp_path)
    out = tmp_path / "s1_out"
    mon = datetime(2026, 10, 26, 20, 0, tzinfo=UTC)
    _write_seal(out, "2026-10-26", mon, st_["rows"], S1_RECEIPT, start=st_["start"],
                opening_close=z.close_of("2026-10-23", st_["calendar"]))
    (out / "seals" / "2026-10-26.json").write_text("{not json", encoding="utf-8")
    # A3 Task 7 (E2.6 r3): the seal is a CREATED seal/<close> stage, so the checkpoint's gate observes its changed,
    # unparseable member first: TRIAL-INVALID (stage-replaced) before any capture, so before its own close is sealed
    with pytest.raises(SystemExit, match=r"seals/2026-10-26\.json missing or changed.*INVALID \(stage-replaced\)"):
        _cp(tmp_path, st_["ledger"].path, day=1)
    assert not (out / "seals" / "2026-10-27.json").exists() and not (out / "captures" / "2026-10-27").exists()


def test_c1_retro_a_bad_seal_record_stops_the_checkpoint_before_any_seal(tmp_path):
    """RETROSPECTIVE. I-4b/m-4: a readable but bad seal record no report binds (a seal for a close after the
    capture instant: the stop decision refuses it) - the checkpoint aborts on it BEFORE its own close is sealed."""
    from conftest import _write_seal
    st_ = _registered_b3(tmp_path)
    out = tmp_path / "s1_out"
    wed = datetime(2026, 10, 28, 20, 0, tzinfo=UTC)
    _write_seal(out, "2026-10-28", wed, st_["rows"], S1_RECEIPT, start=st_["start"],
                opening_close=z.close_of("2026-10-23", st_["calendar"]))
    rep = _cp(tmp_path, st_["ledger"].path, day=1)
    assert rep["stop"]["status"] == "ABORTED-INVALID" and rep["seal"]["written"] is False
    assert not (out / "seals" / "2026-10-27.json").exists()
    assert "bad seal record" in str(_aborted(tmp_path)["reason"])


def test_c2_retro_the_opening_is_recorded_twice(tmp_path):
    """RETROSPECTIVE. C-2: right after the opening (before any attestation) both opening records exist, identical."""
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    assert s1_opening_checkpoint(tmp_path, Ledger(tmp_path / "l.sqlite3"), oc, cal, S1_RECEIPT)["seal"]["written"]
    out = tmp_path / "s1_out"
    a, b = out / "registry" / "opening.json", out / "witnesses" / "opening.json"
    assert a.exists() and b.exists(), "the opening is not recorded twice"
    assert read(a) == read(b)
