"""A3 H5a-FIX2 (Codex exact-head review of a42ea8b, X-15 / H5AFIX-CX-1): an inherited incomplete tail of
s1_out/early_refusals.jsonl (a torn fragment left by a failed write whose best-effort rollback also failed, or by a
killed writer) must never swallow a later record that returns None (recorded). Controller ruling: handle it, do not
refuse - under the lock, before appending, a non-empty file whose last byte is not the line feed gets the minimal
terminator completion prepended to THIS call's bytes (b"\\r\\n" after any other byte, b"\\n" after a lone b"\\r"), so the
fragment becomes its own line - usually unparseable; a fragment missing only its terminator becomes a valid record
whose call still reported the gap (over-disclosure, never loss) - and this record is one intact line. A fragment's gap
was disclosed only when it came from one of our failed returns (a killed process or other corruption may never have
disclosed it). Existing bytes are
never deleted or rewritten. A failure while reading the tail, or while writing the completion, returns its class.
Codex addendum (CONSENSUS on the design): same lock and same read-capable handle; failure during the completion itself;
inherited tail + failed rollback + healthy success; exact lone-LF bytes; a healthy CRLF file unchanged but the line.
RED against base 655fc89 (s1_evidence/a3/h5afix2_red.txt); GREEN s1_evidence/a3/h5afix2_green.txt."""
import errno
import json
import os
from datetime import timedelta
from pathlib import Path

import pytest
import s1_journal as j
import s1_slot as sl

DIAG = "early_refusals.jsonl"


def _rec(i=0):
    """A real-format C4.3 record for the registered 20:45Z slot of the 2026-10-26 close (sample i us before s - 1 s)."""
    sch = sl.slot_of("slot/20261026T204500Z")
    return {"subject": "slot/20261026T204500Z", "scheduled": sch.isoformat(),
            "sample": (sch - timedelta(seconds=1, microseconds=i + 1)).isoformat(),
            "reason": j.C4_REASON.format(slot=sch.isoformat())}


def _line(rec) -> bytes:
    return (json.dumps(rec, sort_keys=True) + "\r\n").encode("utf-8")


def _strict(data: bytes):
    """A strict JSONL reader (str.splitlines - which also splits on a lone CR - and json.loads on EVERY line, an empty
    line included): (parsed records, unparseable line count)."""
    good, bad = [], 0
    for x in data.decode("utf-8", "replace").splitlines():
        try:
            good.append(json.loads(x))
        except ValueError:
            bad += 1
    return good, bad


def _lf(data: bytes):
    """An LF reader (split on b"\\n", strip one trailing CR, skip empty lines): (parsed records, unparseable count)."""
    good, bad = [], 0
    for x in data.split(b"\n"):
        x = x[:-1] if x.endswith(b"\r") else x
        if not x:
            continue
        try:
            good.append(json.loads(x.decode("utf-8")))
        except (UnicodeDecodeError, ValueError):
            bad += 1
    return good, bad


class _Torn:
    """The product's file object whose write puts 7 bytes of the data on disk and then fails (EIO)."""

    def __init__(self, f):
        self.f = f

    def __enter__(self):
        self.f.__enter__()
        return self

    def __exit__(self, *exc):
        return self.f.__exit__(*exc)

    def write(self, b):
        self.f.write(bytes(b)[:7])
        raise OSError(errno.EIO, "injected partial write")

    def __getattr__(self, name):
        return getattr(self.f, name)


# ---------------------------------------------------------------- Codex's two-call fault/recovery regression
def test_fault_then_recovery_keeps_every_claimed_record(tmp_path, monkeypatch):
    """1: recorded. 2: a 7-byte partial write AND a failed rollback ftruncate -> its failure class (its own gap,
    disclosed), a torn fragment left on disk. 3: healthy -> None, and its record IS one valid line; record 1 still
    parses; the fragment is the only unparseable line (both readers); record 1's bytes are untouched."""
    out = tmp_path / "s1_out"
    out.mkdir()
    path = out / DIAG
    assert sl.record_early_refusal(out, _rec(1)) is None
    first = path.read_bytes()
    real_open = open

    def bad_truncate(fd, n):
        raise OSError(errno.EIO, "injected rollback failure")
    monkeypatch.setattr(sl, "open", lambda *a, **kw: _Torn(real_open(*a, **kw)), raising=False)
    monkeypatch.setattr(os, "ftruncate", bad_truncate)
    assert sl.record_early_refusal(out, _rec(2)) == "OSError"
    monkeypatch.undo()
    torn = path.read_bytes()
    assert torn.startswith(first) and len(torn) == len(first) + 7           # the inherited incomplete tail
    assert sl.record_early_refusal(out, _rec(3)) is None
    data = path.read_bytes()
    assert data.startswith(torn)                                           # nothing deleted or rewritten
    for reader in (_strict, _lf):
        assert reader(data) == ([_rec(1), _rec(3)], 1), reader.__name__


# ---------------------------------------------------------------- tail variants (the decided completion rule)
HEALTHY = _line(_rec(10))
TAILS = {                       # case: (existing bytes, the bytes this call must append before its own line)
    "absent-file": (None, b""),
    "empty-file": (b"", b""),
    "healthy-file": (HEALTHY, b""),
    "no-terminator": (HEALTHY + b'{"reason": "slot 20', b"\r\n"),
    "lone-cr": (HEALTHY + b'{"reason": "slot 20\r', b"\n"),
    "lone-lf": (HEALTHY + b'{"reason": "slot 20\n', b""),
    "bare-cr": (b"\r", b"\n"),
    "bare-lf": (b"\n", b""),
}


@pytest.mark.parametrize("case", list(TAILS))
def test_tail_completion(tmp_path, case):
    """Whatever the inherited tail, the call returns None and the file is EXACTLY the existing bytes (never deleted or
    rewritten) + the minimal completion + this record's line; this record is one intact line for both readers, every
    earlier valid record still parses, and an incomplete tail is at most one unparseable line. A healthy (or empty, or
    absent) file gets nothing but the line, byte for byte."""
    out = tmp_path / "s1_out"
    out.mkdir()
    path = out / DIAG
    existing, completion = TAILS[case]
    if existing is not None:
        path.write_bytes(existing)
    assert sl.record_early_refusal(out, _rec(11)) is None
    data = path.read_bytes()
    assert data == (existing or b"") + completion + _line(_rec(11)), data
    want = [_rec(10)] if existing and existing.startswith(HEALTHY) else []
    for reader in (_strict, _lf):
        good, bad = reader(data)
        assert good == want + [_rec(11)], (reader.__name__, good)
        clean = case in ("absent-file", "empty-file", "healthy-file")
        assert bad == 0 if clean else bad <= 1, (reader.__name__, bad)   # the inherited fragment (or blank) only
    assert sl.record_early_refusal(out, _rec(12)) is None                  # and the next call adds no completion
    assert path.read_bytes() == data + _line(_rec(12))


def test_tail_read_failure_returns_the_class(tmp_path, monkeypatch):
    """Reading the inherited tail fails (EIO): nothing is recorded, the failure class is returned (the caller
    discloses the gap), and the file is byte-identical."""
    out = tmp_path / "s1_out"
    out.mkdir()
    path = out / DIAG
    path.write_bytes(HEALTHY + b'{"torn')
    before = path.read_bytes()

    def bad_read(fd, n):
        raise OSError(errno.EIO, "injected tail read failure")
    monkeypatch.setattr(os, "read", bad_read)
    got = sl.record_early_refusal(out, _rec(13))
    monkeypatch.undo()
    assert got == "OSError", got
    assert path.read_bytes() == before
    assert sl.record_early_refusal(out, _rec(14)) is None
    assert _lf(path.read_bytes()) == ([_rec(10), _rec(14)], 1)


# ---------------------------------------------------------------- Codex addendum: failures inside the completion
TORN = HEALTHY + b'{"reason": "slot 20'                  # an inherited incomplete tail: this call's completion is CRLF


class _Writer:
    """The product's file object with a scripted write: `fail` puts the first `k` bytes of the data on disk and then
    raises EIO; `drip` writes one byte per call (a legal short write)."""

    def __init__(self, f, mode, k=0):
        self.f, self.mode, self.k, self.calls = f, mode, k, 0

    def __enter__(self):
        self.f.__enter__()
        return self

    def __exit__(self, *exc):
        return self.f.__exit__(*exc)

    def write(self, b):
        self.calls += 1
        if self.mode == "fail":
            self.f.write(bytes(b)[:self.k])
            raise OSError(errno.EIO, "injected write failure")
        return self.f.write(bytes(b)[:1])

    def __getattr__(self, name):
        return getattr(self.f, name)


def _script(monkeypatch, mode, k=0, made=None):
    real_open = open

    def spy(*a, **kw):
        w = _Writer(real_open(*a, **kw), mode, k)
        if made is not None:
            made.append(w)
        return w
    monkeypatch.setattr(sl, "open", spy, raising=False)


@pytest.mark.parametrize("k", [0, 1], ids=["before-any-byte", "inside-the-completion"])
def test_failure_during_the_completion_rolls_back(tmp_path, monkeypatch, k):
    """The write fails before any byte, or after ONE byte of the CRLF completion: the failure class, the file
    byte-identical (the completion rolled back with the line), and the next call completes the tail and records."""
    out = tmp_path / "s1_out"
    out.mkdir()
    path = out / DIAG
    path.write_bytes(TORN)
    _script(monkeypatch, "fail", k)
    got = sl.record_early_refusal(out, _rec(20))
    monkeypatch.undo()
    assert got == "OSError", got
    assert path.read_bytes() == TORN
    assert sl.record_early_refusal(out, _rec(21)) is None
    assert path.read_bytes() == TORN + b"\r\n" + _line(_rec(21))


def test_short_writes_through_the_completion(tmp_path, monkeypatch):
    """One byte per write call, starting inside the completion: completed under the same lock - exactly the old bytes,
    the CRLF completion and one intact line."""
    out = tmp_path / "s1_out"
    out.mkdir()
    path = out / DIAG
    path.write_bytes(TORN)
    made = []
    _script(monkeypatch, "drip", made=made)
    assert sl.record_early_refusal(out, _rec(22)) is None
    monkeypatch.undo()
    assert made[0].calls == len(b"\r\n" + _line(_rec(22)))
    assert path.read_bytes() == TORN + b"\r\n" + _line(_rec(22))


@pytest.mark.parametrize("k", [1, 5], ids=["torn-inside-the-completion", "torn-after-the-completion"])
def test_inherited_tail_failed_rollback_then_success(tmp_path, monkeypatch, k):
    """Codex addendum: an inherited torn tail; a call whose write fails after k bytes (1: only the CR of its
    completion; 5: the completion and 3 bytes of its line) AND whose rollback fails -> its failure class; then a
    healthy call -> None. Every prior byte is preserved (each file is a prefix of the next), and the new record parses
    as its own line with both readers, with the earlier valid record."""
    out = tmp_path / "s1_out"
    out.mkdir()
    path = out / DIAG
    path.write_bytes(TORN)
    _script(monkeypatch, "fail", k)

    def bad_truncate(fd, n):
        raise OSError(errno.EIO, "injected rollback failure")
    monkeypatch.setattr(os, "ftruncate", bad_truncate)
    assert sl.record_early_refusal(out, _rec(23)) == "OSError"
    monkeypatch.undo()
    after = path.read_bytes()
    assert after == TORN + (b"\r\n" + _line(_rec(23)))[:k]
    assert sl.record_early_refusal(out, _rec(24)) is None
    data = path.read_bytes()
    assert data == after + (b"\n" if after.endswith(b"\r") else b"\r\n") + _line(_rec(24))
    assert data.endswith(b"\r\n" + _line(_rec(24)))                   # its own line
    for reader in (_strict, _lf):
        good, bad = reader(data)
        assert good == [_rec(10), _rec(24)], (reader.__name__, good)
        assert 1 <= bad <= 2, (reader.__name__, bad)


# ---------------------------------------------------------------- fix round 1 (review verdict findings 1-3)
LOCK_OFFSET = 0x7FFFFFF0     # the fixed lock region of the contract (as in test_s1_a3_early_refusal_lock.py)


def _region_held(path: Path) -> bool:
    """True when a SECOND handle cannot lock the diagnostic region of `path` (LK_NBLCK: EACCES / EDEADLOCK), i.e. a
    lock is held on it. Windows byte-range locks conflict across handles even within one process (the probe
    test_s1_a3_early_refusal_lock.py::test_lock_held_across_write_and_fsync already relies on)."""
    import msvcrt
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


def test_tail_read_happens_under_the_lock_on_the_products_fd(tmp_path, monkeypatch):
    """Review finding 1 (Codex addendum 1): the tail byte is read ONCE, on the product's own (locked) fd, while the
    diagnostic region is held - a read before the lock would let another writer tear the tail between the read and
    the append (X-15 again under concurrency). os.read is spied during a real call; at that moment a second handle
    must fail to lock the region."""
    out = tmp_path / "s1_out"
    out.mkdir()
    path = out / DIAG
    path.write_bytes(TORN)
    fds, reads = [], []
    real_open, real_read = open, os.read

    def spy_open(*a, **kw):
        f = real_open(*a, **kw)
        fds.append(f.fileno())
        return f

    def spy_read(fd, n):
        reads.append((fd, n, _region_held(path)))
        return real_read(fd, n)
    monkeypatch.setattr(sl, "open", spy_open, raising=False)
    monkeypatch.setattr(os, "read", spy_read)
    assert sl.record_early_refusal(out, _rec(30)) is None
    monkeypatch.undo()
    assert len(fds) == 1, fds
    assert reads == [(fds[0], 1, True)], reads
    assert path.read_bytes() == TORN + b"\r\n" + _line(_rec(30))


def test_tail_short_read_returns_the_class(tmp_path, monkeypatch):
    """Review finding 3: the tail read returns no byte (b"", e.g. the file shrank under a non-cooperating actor): the
    failure class, nothing written (byte-identical) - never a guessed completion."""
    out = tmp_path / "s1_out"
    out.mkdir()
    path = out / DIAG
    path.write_bytes(TORN)
    monkeypatch.setattr(os, "read", lambda fd, n: b"")
    got = sl.record_early_refusal(out, _rec(31))
    monkeypatch.undo()
    assert got == "OSError", got
    assert path.read_bytes() == TORN


@pytest.mark.parametrize("cut", [1, 2], ids=["all-but-lf", "all-but-crlf"])
def test_terminator_only_fragment_becomes_a_valid_over_disclosed_record(tmp_path, monkeypatch, cut):
    """Review finding 2 (documented behaviour): a failed call that wrote all but the last 1-2 bytes of its line, with a
    failed rollback, returned its failure class (gap disclosed); the next call's completion turns that fragment into
    a VALID record - over-disclosure (a reported gap whose record nevertheless exists), never loss. The next record
    is intact too."""
    out = tmp_path / "s1_out"
    out.mkdir()
    path = out / DIAG
    assert sl.record_early_refusal(out, _rec(32)) is None
    _script(monkeypatch, "fail", len(_line(_rec(33))) - cut)

    def bad_truncate(fd, n):
        raise OSError(errno.EIO, "injected rollback failure")
    monkeypatch.setattr(os, "ftruncate", bad_truncate)
    assert sl.record_early_refusal(out, _rec(33)) == "OSError"
    monkeypatch.undo()
    assert sl.record_early_refusal(out, _rec(34)) is None
    for reader in (_strict, _lf):
        assert reader(path.read_bytes()) == ([_rec(32), _rec(33), _rec(34)], 0), reader.__name__
