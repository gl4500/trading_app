"""S1 ownership locks (Addendum 3 rev 5 F5; Erratum 1 E1). One lock file per slot, stage or stop operation at
<root>/s1_locks/<trial_id>/<name>.lock, outside s1_out (F5.2). It is opened with CreateFileW sharing READ only (never
FILE_SHARE_WRITE or FILE_SHARE_DELETE) and byte-range locked with msvcrt.locking, so while it is held it cannot be
deleted, renamed or replaced; the OS releases it when the process ends. Exactly three results (F5.5): acquired;
LockHeld (Windows sharing or lock violation - the only liveness evidence); LockError (any other I/O or permission
error: fail closed, never 'live' or 'dead'). No PID inference; a leftover acquirable file is no liveness.

Names and trial ids are validated before any filesystem call (OQ-23): a uuid4 trial_id and a name from the closed
grammar, a seal-stage lock carrying a real calendar date. The finalizer never takes, waits for or tests the slot work
lock for a decision (Erratum 1 E1); lock_acquirable exists only for deferred leftover cleanup (E1.4).
Imports nothing from the S1 modules (loose coupling)."""
import ctypes
import errno
import os
import re
import sys
from datetime import date
from pathlib import Path

GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
FILE_SHARE_READ = 0x00000001
OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL = 4, 0x80
ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION = 32, 33
STOP_LOCK = "stop"                                                                 # OQ-23


class LockHeld(Exception):
    """Held by another process (a Windows sharing or lock violation)."""


class LockError(Exception):
    """Any other I/O or permission error: the caller refuses with no row (F5.5)."""


if sys.platform == "win32":
    import msvcrt
    from ctypes import wintypes
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                 wintypes.DWORD, wintypes.HANDLE)
    _k32.CreateFileW.restype = wintypes.HANDLE
    _k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _k32.CloseHandle.restype = wintypes.BOOL
    _INVALID = wintypes.HANDLE(-1).value


# OQ-23 ruling (revision 2 adds the seal-<close> stage locks of E2.1 r3). fullmatch + ASCII: no trailing newline and
# no non-ASCII digits; the seal date is further checked to be a real calendar date.
NAME_RE = re.compile(r"(slot-\d{8}T\d{6}Z|stage-(audit|opening|start_attest|prereg|stop_attest|final_plan|final"
                     r"|score|seal-(\d{4}-\d{2}-\d{2}))|stop)", re.ASCII)
UUID4_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", re.ASCII)
_SLOT_SUBJECT = re.compile(r"slot/(\d{8}T\d{6}Z)", re.ASCII)


def _name_ok(name) -> bool:
    m = NAME_RE.fullmatch(name) if isinstance(name, str) else None
    if m is None:
        return False
    if m.group(3) is not None:                                   # stage-seal-<YYYY-MM-DD>: a real date only
        try:
            date.fromisoformat(m.group(3))
        except ValueError:
            return False
    return True


def lock_path(root, trial_id: str, name: str) -> Path:
    """Validated: a uuid4 trial_id and a name from the closed grammar; anything else is LockError (no traversal, no
    cross-trial aliasing). Pure: no filesystem call."""
    if not isinstance(trial_id, str) or not UUID4_RE.fullmatch(trial_id):
        raise LockError("lock trial_id is not a uuid4")
    if not _name_ok(name):
        raise LockError(f"lock name {name!r} is outside the OQ-23 grammar")
    return Path(root) / "s1_locks" / trial_id / f"{name}.lock"


def slot_lock_name(subject: str) -> str:
    """`slot/<YYYYMMDDTHHMMSSZ>` -> `slot-<YYYYMMDDTHHMMSSZ>`; any other subject is LockError."""
    m = _SLOT_SUBJECT.fullmatch(subject) if isinstance(subject, str) else None
    if m is None:
        raise LockError(f"not a slot subject: {subject!r}")
    return "slot-" + m.group(1)


def stage_lock_name(stage: str) -> str:
    """`stage-<name>`; a seal stage `seal/<close>` becomes `stage-seal-<close>` (revision 2, E2.1 r3). The result is
    validated by lock_path."""
    if not isinstance(stage, str):
        raise LockError(f"not a stage name: {stage!r}")
    return "stage-" + stage.replace("/", "-")


def lock_acquirable(root, trial_id: str, name: str) -> bool:
    """E1.4: the cleanup probe. True only when this process could acquire the lock (it is then released at once);
    False when LockHeld. LockError propagates (fail closed). It never decides a terminal row."""
    try:
        OwnershipLock(root, trial_id, name).acquire().release()
        return True
    except LockHeld:
        return False


def _open_exclusive(path: Path) -> int:
    if sys.platform != "win32":
        raise LockError("ownership locks require Windows share modes (F5.2): fail closed")
    h = _k32.CreateFileW(str(path), GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ, None, OPEN_ALWAYS,
                         FILE_ATTRIBUTE_NORMAL, None)
    if h is None or h == _INVALID:
        err = ctypes.get_last_error()
        if err in (ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION):
            raise LockHeld(f"{path.name}: held by another process (Windows error {err})")
        raise LockError(f"{path.name}: lock I/O error (Windows error {err})")
    try:
        return msvcrt.open_osfhandle(h, os.O_RDWR)
    except OSError as e:
        _k32.CloseHandle(h)
        raise LockError(f"{path.name}: handle conversion failed ({type(e).__name__})") from None


class OwnershipLock:
    def __init__(self, root, trial_id: str, name: str):
        self.path = lock_path(root, trial_id, name)
        self.fd = None

    def acquire(self) -> "OwnershipLock":
        if self.fd is not None:
            raise LockError(f"{self.path.name}: already acquired by this object")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise LockError(f"lock directory unavailable ({type(e).__name__})") from None
        fd = _open_exclusive(self.path)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as e:
            os.close(fd)
            if e.errno in (errno.EACCES, errno.EDEADLOCK):
                raise LockHeld(f"{self.path.name}: byte range locked by another process") from None
            raise LockError(f"{self.path.name}: lock I/O error ({type(e).__name__})") from None
        self.fd = fd
        return self

    def release(self) -> None:
        if self.fd is None:
            return
        fd, self.fd = self.fd, None
        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass                                                 # closing the handle releases the range anyway
        finally:
            os.close(fd)

    def __enter__(self) -> "OwnershipLock":
        return self.acquire()

    def __exit__(self, *exc) -> bool:
        self.release()
        return False
