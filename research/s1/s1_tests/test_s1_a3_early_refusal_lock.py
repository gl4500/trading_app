"""A3 H5a-FIX (Codex exact-head review of ce4a53b, H5A-CX-1; H5a M-1): Erratum 2 Clarification 4 C4.3 - an early
refusal's diagnostic either preserves its record or the refusal discloses the gap (C4.3.4). The reviewed path
s1_out/early_refusals.jsonl is appended by separate slot workers (separate slot locks), so the append is serialized
across processes by an OS byte-range lock (msvcrt.locking) on a fixed 1-byte region of the jsonl file itself (no new
file, no directory), held across seek-to-end, the write of the encoded line and the fsync, and acquired within a fixed
small bound or not at all ("LockTimeout": nothing recorded, the gap disclosed, the worker never blocked or raised).
M-1: the C4 reason is matched against the slot's registered UTC instant (j.slot_instant of the subject), so a direct
caller passing an aware non-UTC slot (-04:00) still gets its diagnostic or its gap disclosure.
RED against base 0eaadae (s1_evidence/a3/h5afix_red.txt); GREEN s1_evidence/a3/h5afix_green.txt."""
import errno
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import timedelta, timezone
from pathlib import Path

import pytest
import a3_h5a_helpers as h
import s1_journal as j
import s1_slot as sl

DIAG = "early_refusals.jsonl"
CHILD = str(Path(__file__).resolve().parent / "a3_h5afix_child.py")
S1DIR = str(Path(sl.__file__).resolve().parent)           # the product directory under test (a scratch copy included)
N_PROC, N_REC = 4, 100
LOCK_OFFSET = 0x7FFFFFF0     # the fixed lock region of the contract (a test literal; the product constant must equal it)
SEC = timedelta(seconds=1)
GAP = re.escape("early-refusal diagnostic NOT recorded (LockTimeout): recording gap (Clarification 4 C4.3.4)")


def _env():
    return dict(os.environ, PYTHONDONTWRITEBYTECODE="1")


def _wait(p: Path, limit: float) -> bool:
    end = time.monotonic() + limit
    while not p.exists():
        if time.monotonic() > end:
            return False
        time.sleep(0.01)
    return True


def _lines(path: Path):
    """(parsed records, unparseable line count) of the jsonl bytes (CRLF or LF terminated lines)."""
    good, bad = [], 0
    data = path.read_bytes() if path.is_file() else b""
    for raw in data.split(b"\n"):
        raw = raw.rstrip(b"\r")
        if not raw:
            continue
        try:
            good.append(json.loads(raw.decode("utf-8")))
        except (UnicodeDecodeError, ValueError):
            bad += 1
    return good, bad


class Holder:
    """Another process holding the diagnostic lock region of s1_out/early_refusals.jsonl until released."""

    def __init__(self, tmp_path, out):
        self.held, self.release = tmp_path / "held.flag", tmp_path / "release.flag"
        self.p = subprocess.Popen([sys.executable, "-I", CHILD, "hold", str(out), str(LOCK_OFFSET), str(self.held),
                                   str(self.release)], env=_env())

    def __enter__(self):
        if not _wait(self.held, 60.0):
            self.p.kill()
            raise AssertionError(f"the holder never locked the region (rc={self.p.poll()})")
        return self

    def __exit__(self, *exc):
        self.release.touch()
        try:
            self.p.wait(timeout=60)
        except subprocess.TimeoutExpired:
            self.p.kill()
        return False


def _rec(i=0):
    """A real-format C4.3 record for the registered 20:45Z slot of the 2026-10-26 close (sample i us before s - 1 s)."""
    sch = sl.slot_of("slot/20261026T204500Z")
    return {"subject": "slot/20261026T204500Z", "scheduled": sch.isoformat(),
            "sample": (sch - timedelta(seconds=1, microseconds=i + 1)).isoformat(),
            "reason": j.C4_REASON.format(slot=sch.isoformat())}


# ---------------------------------------------------------------- outcomes 1 + 2: no silent loss, cross-process
def test_concurrent_writers_lose_no_record(tmp_path):
    """4 real processes x 100 calls on one s1_out/early_refusals.jsonl, released together: every call that returned
    None (recorded) has its record present exactly once as one valid JSON line, no other record is present, and no
    line is unparseable. (Base ce4a53b / 0eaadae: ~340-355 valid unique of 400 claimed, plus torn lines.)"""
    out = tmp_path / "s1_out"
    out.mkdir()
    go = tmp_path / "go.flag"
    ready = [tmp_path / f"ready{k}.flag" for k in range(N_PROC)]
    ps = [subprocess.Popen([sys.executable, "-I", CHILD, "append", S1DIR, str(out), str(k), str(N_REC), str(ready[k]),
                            str(go)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=_env())
          for k in range(N_PROC)]
    try:
        assert all(_wait(r, 120.0) for r in ready), "a writer never became ready"
        go.touch()
        res = [p.communicate(timeout=300) for p in ps]
    finally:
        for p in ps:
            if p.poll() is None:
                p.kill()
    assert [p.returncode for p in ps] == [0] * N_PROC, [r[1][-2000:] for r in res]
    claimed, failed = set(), {}
    for k, (so, _) in enumerate(res):
        d = json.loads(so.strip().splitlines()[-1])
        s = sl.slot_of("slot/20261026T204500Z") + timedelta(minutes=2 * k)
        for i in d["ok"]:
            claimed.add((j.slot_subject(s), (s - timedelta(seconds=1, microseconds=i + 1)).isoformat()))
        failed.update({(k, i): v for i, v in d["fail"].items()})
    recs, bad = _lines(out / DIAG)
    keys = [(r["subject"], r["sample"]) for r in recs]
    summary = (f"claimed={len(claimed)} failed={len(failed)} lines={len(recs)} valid_unique={len(set(keys))} "
               f"unparseable={bad}")
    print(summary)
    assert bad == 0, summary
    assert len(keys) == len(set(keys)), summary                 # exactly once
    assert set(keys) == claimed, summary                        # every recorded call present, nothing else
    assert len(claimed) + len(failed) == N_PROC * N_REC, summary
    assert set(failed.values()) <= {"LockTimeout"}, failed
    assert claimed, summary                                     # not vacuous
    for r in recs:
        assert r["reason"] == j.C4_REASON.format(slot=r["scheduled"]) and r["subject"] == j.slot_subject(
            sl.slot_of(r["subject"])), r


def test_lock_held_across_write_and_fsync(tmp_path, monkeypatch):
    """The lock region is held (a second handle cannot lock it) while the encoded line is written - in ONE write of
    the whole line - and while it is fsynced; afterwards it is free again."""
    out = tmp_path / "s1_out"
    out.mkdir()
    import msvcrt
    path = out / DIAG
    seen = {"write": [], "fsync": []}

    def held() -> bool:
        with open(path, "ab", buffering=0) as g:
            fd = g.fileno()
            os.lseek(fd, LOCK_OFFSET, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError as e:
                assert e.errno in (errno.EACCES, errno.EDEADLOCK), e
                return True
            os.lseek(fd, LOCK_OFFSET, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            return False

    class Proxy:
        def __init__(self, f):
            self.f = f

        def __enter__(self):
            self.f.__enter__()
            return self

        def __exit__(self, *exc):
            return self.f.__exit__(*exc)

        def write(self, b):
            seen["write"].append((bytes(b) if not isinstance(b, str) else b.encode(), held()))
            return self.f.write(b)

        def __getattr__(self, name):
            return getattr(self.f, name)

    real_open, real_fsync = open, os.fsync

    def spy_open(*a, **kw):
        return Proxy(real_open(*a, **kw))

    def spy_fsync(fd):
        seen["fsync"].append(held())
        return real_fsync(fd)
    monkeypatch.setattr(sl, "open", spy_open, raising=False)
    monkeypatch.setattr(os, "fsync", spy_fsync)
    assert sl.record_early_refusal(out, _rec()) is None
    monkeypatch.undo()
    line = json.dumps(_rec(), sort_keys=True)
    assert [held_ for _, held_ in seen["write"]] == [True], seen
    assert seen["write"][0][0].rstrip(b"\r\n") == line.encode(), seen
    assert seen["fsync"] == [True], seen
    assert not held()
    assert _lines(path) == ([_rec()], 0)


# ---------------------------------------------------------------- fix round 1 (review I-1, m-1)
def _region_free(path: Path) -> bool:
    """True when a fresh handle can lock (and then unlocks) the diagnostic region of `path` at once (LK_NBLCK)."""
    import msvcrt
    with open(path, "ab", buffering=0) as g:
        fd = g.fileno()
        os.lseek(fd, LOCK_OFFSET, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as e:
            assert e.errno in (errno.EACCES, errno.EDEADLOCK), e
            return False
        os.lseek(fd, LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        return True


class _FailingFile:
    """The product's file object with its write replaced: `partial` writes 7 bytes of the line then raises ENOSPC
    (a torn line on disk unless rolled back); `short` writes at most 7 bytes per call (a legal short write)."""

    def __init__(self, f, mode):
        self.f, self.mode, self.calls = f, mode, 0

    def __enter__(self):
        self.f.__enter__()
        return self

    def __exit__(self, *exc):
        return self.f.__exit__(*exc)

    def write(self, b):
        self.calls += 1
        if self.mode == "partial":
            self.f.write(bytes(b)[:7])
            raise OSError(errno.ENOSPC, "simulated mid-line write failure (disk full)")
        return self.f.write(bytes(b)[:7])

    def __getattr__(self, name):
        return getattr(self.f, name)


@pytest.mark.parametrize("case", ["partial-write-failure", "fsync-failure"])
def test_write_or_fsync_failure_rolls_back(tmp_path, monkeypatch, case):
    """Review I-1 (Codex: 'write failure' control): after a recorded line, a call whose write fails mid-line (7 bytes
    already on disk) or whose fsync fails returns the failure class, leaves the file BYTE-IDENTICAL (no torn bytes:
    the truncate-back under the lock), and leaves the region free; the next successful call then yields a parseable
    line - so no later record is swallowed into a torn one."""
    out = tmp_path / "s1_out"
    out.mkdir()
    path = out / DIAG
    assert sl.record_early_refusal(out, _rec(0)) is None
    before = path.read_bytes()
    if case == "partial-write-failure":
        real_open = open
        monkeypatch.setattr(sl, "open", lambda *a, **kw: _FailingFile(real_open(*a, **kw), "partial"), raising=False)
    else:
        def bad_fsync(fd):
            raise OSError(errno.EIO, "simulated fsync failure")
        monkeypatch.setattr(os, "fsync", bad_fsync)
    got = sl.record_early_refusal(out, _rec(1))
    monkeypatch.undo()
    assert got == "OSError", got
    assert path.read_bytes() == before                           # byte-identical: nothing of the failed call remains
    assert _region_free(path)
    assert sl.record_early_refusal(out, _rec(2)) is None
    assert _lines(path) == ([_rec(0), _rec(2)], 0)


def test_short_writes_complete_one_line(tmp_path, monkeypatch):
    """A legal short write (at most 7 bytes per call) is completed under the same lock: one whole, parseable line."""
    out = tmp_path / "s1_out"
    out.mkdir()
    real_open = open
    made = []

    def spy_open(*a, **kw):
        made.append(_FailingFile(real_open(*a, **kw), "short"))
        return made[-1]
    monkeypatch.setattr(sl, "open", spy_open, raising=False)
    assert sl.record_early_refusal(out, _rec(3)) is None
    monkeypatch.undo()
    assert made[0].calls > 1
    assert _lines(out / DIAG) == ([_rec(3)], 0)


def test_region_unlocked_before_the_handle_closes(tmp_path, monkeypatch):
    """Review m-1: the unlock releases the SAME region the lock took, before the writer's handle is closed (a close
    may release it only later). Deterministic: at the product's `with` exit - the writer's fd still open, the line
    already written - a fresh handle must lock the region at once with LK_NBLCK."""
    out = tmp_path / "s1_out"
    out.mkdir()
    path = out / DIAG
    at_exit = []

    class AtExit:
        def __init__(self, f):
            self.f = f

        def __enter__(self):
            self.f.__enter__()
            return self

        def __exit__(self, *exc):
            assert not self.f.closed
            at_exit.append(_region_free(path))
            return self.f.__exit__(*exc)

        def __getattr__(self, name):
            return getattr(self.f, name)
    real_open = open
    monkeypatch.setattr(sl, "open", lambda *a, **kw: AtExit(real_open(*a, **kw)), raising=False)
    assert sl.record_early_refusal(out, _rec(4)) is None
    monkeypatch.undo()
    assert at_exit == [True], at_exit
    assert _lines(path) == ([_rec(4)], 0)


# ---------------------------------------------------------------- outcome 3: bounded waiting
def test_lock_timeout_records_nothing_and_returns_the_class(tmp_path):
    """Another process holds the region: the call returns "LockTimeout" within the fixed small bound (never None,
    never blocking indefinitely, never raising) and the file is unchanged; once released, the next call records."""
    out = tmp_path / "s1_out"
    out.mkdir()
    with Holder(tmp_path, out):
        before = hashlib.sha256((out / DIAG).read_bytes()).hexdigest()
        t0 = time.monotonic()
        got = sl.record_early_refusal(out, _rec())
        el = time.monotonic() - t0
        assert got == "LockTimeout", got
        assert hashlib.sha256((out / DIAG).read_bytes()).hexdigest() == before
    assert sl.EARLY_LOCK_OFFSET == LOCK_OFFSET
    assert 0 < sl.EARLY_LOCK_WAIT_S <= 5.0
    assert sl.EARLY_LOCK_WAIT_S * 0.9 <= el < sl.EARLY_LOCK_WAIT_S + 3.0, el
    assert sl.record_early_refusal(out, _rec(1)) is None
    assert _lines(out / DIAG) == ([_rec(1)], 0)


def test_lock_timeout_worker_refuses_and_discloses_the_gap(tmp_path, monkeypatch):
    """End to end (run_checkpoint, an early sample): with the region held by another process, the worker still
    refuses with the pinned C4 reason, no journal row, no claim/capture/work, and its refusal text states the
    LockTimeout recording gap (Clarification 4 C4.3.4)."""
    st_ = h.registered(tmp_path)
    s45 = h.slot(st_, h.D0)
    out = tmp_path / "s1_out"
    w = h.Watch(monkeypatch)
    before = h.shas(tmp_path)
    with Holder(tmp_path, out):
        with pytest.raises(SystemExit, match=h.refused(s45, h.c4_text(s45))) as ex:
            h.run(tmp_path, st_, s45, s45 - SEC, receipt=w.receipt(), process=w.process())
    assert re.search(GAP, str(ex.value)), str(ex.value)
    assert _lines(out / DIAG) == ([], 0)
    assert h.shas(tmp_path) == before and h.no_files(tmp_path, st_, s45)
    w.assert_no_work()


# ---------------------------------------------------------------- outcome 4: I-3 controls
@pytest.mark.parametrize("case", ["root-missing", "ancestor-missing"])
def test_missing_root_is_never_created(tmp_path, case):
    """No s1_out (or no ancestor): a failure class, nothing created - no directory, no jsonl, no lock file."""
    out = tmp_path / "s1_out" if case == "root-missing" else tmp_path / "gone" / "s1_out"
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    got = sl.record_early_refusal(out, _rec())
    assert got == "FileNotFoundError", got
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")) == before


def test_no_new_file_in_s1_out(tmp_path):
    """The lock is a region of the jsonl itself: after a record (and after a timeout) s1_out holds exactly the
    jsonl - no lock file that an s1_out inventory could pick up."""
    out = tmp_path / "s1_out"
    out.mkdir()
    assert sl.record_early_refusal(out, _rec()) is None
    with Holder(tmp_path, out):
        assert sl.record_early_refusal(out, _rec(1)) == "LockTimeout"
    assert sorted(p.name for p in out.iterdir()) == [DIAG]


# ---------------------------------------------------------------- outcome 6: H5a M-1 (non-UTC slot)
NY4 = timezone(timedelta(hours=-4))


@pytest.mark.parametrize("case", ["diagnostic-recorded", "gap-disclosed"])
def test_non_utc_slot_diagnostic(tmp_path, monkeypatch, case):
    """A direct caller passes the registered slot as an aware -04:00 instant: the early refusal is the pinned C4
    reason (UTC instant), and the C4.3 diagnostic line is written (keyed on the UTC registered instant) - or, on a
    write failure, the refusal discloses the gap. (Base: '' - nothing recorded and no gap stated.)"""
    st_ = h.registered(tmp_path)
    s45 = h.slot(st_, h.D0)
    local = s45.astimezone(NY4)
    assert local.isoformat().endswith("-04:00") and local == s45
    at = s45 - SEC
    w = h.Watch(monkeypatch)
    if case == "gap-disclosed":
        def denied(*a, **kw):
            raise PermissionError(13, "diagnostic write denied (simulated)")
        monkeypatch.setattr(sl, "open", denied, raising=False)
    with pytest.raises(SystemExit, match=h.refused(s45, h.c4_text(s45))) as ex:
        h.run(tmp_path, st_, local, at, receipt=w.receipt(), process=w.process())
    msg = str(ex.value)
    w.assert_no_work()
    if case == "diagnostic-recorded":
        assert f"early-refusal diagnostic recorded in s1_out/{DIAG}" in msg, msg
        assert _lines(tmp_path / "s1_out" / DIAG) == ([{"subject": j.slot_subject(s45), "scheduled": s45.isoformat(),
                                                         "sample": at.isoformat(), "reason": h.c4_text(s45)}], 0)
    else:
        assert re.search(r"early-refusal diagnostic NOT recorded \(PermissionError\): recording gap "
                         r"\(Clarification 4 C4\.3\.4\)", msg), msg
        assert _lines(tmp_path / "s1_out" / DIAG) == ([], 0)
