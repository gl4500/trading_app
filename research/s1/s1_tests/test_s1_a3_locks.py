"""Addendum 3 rev 5 F5 (ownership locks): isolated processes, real crashes (killed children), concurrent acquisition;
no mocked live flag (F5.4). Behavioural RED against the Task 3 stub (s1_evidence/a3/t3_red.txt). Windows only (F5.2:
share mode + msvcrt.locking); tmp_path only. Every child is `python -I -c <script>` with tmp_path arguments only: it
never touches the real mailbox, trading.db or the network, and it is killed in a finally block if still running."""
import os
import subprocess
import sys
from pathlib import Path

import pytest
import s1_locks as L

HERE = Path(__file__).resolve().parent.parent
TRIAL = "3f2b8c1e-5d4a-4b6c-9e7f-0a1b2c3d4e5f"
HOLD = r'''
import sys
sys.path.insert(0, sys.argv[1])
import s1_locks
try:
    s1_locks.OwnershipLock(sys.argv[2], sys.argv[3], sys.argv[4]).acquire()
    print("acquired", flush=True)
except s1_locks.LockHeld:
    print("held", flush=True)
    sys.exit(0)
sys.stdin.readline()
'''
OPEN_PLAIN = r'''
import sys
f = open(sys.argv[1], "r+b")
print("opened", flush=True)
sys.stdin.readline()
'''


def spawn(script, *args):
    return subprocess.Popen([sys.executable, "-I", "-c", script, *map(str, args)], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True)


def child(script, *args):
    p = spawn(script, *args)
    return p, p.stdout.readline().strip()


def reap(p):
    """Never leave a child running: kill it if it is still alive, then wait and close its pipes."""
    try:
        if p.poll() is None:
            p.kill()
        p.wait(timeout=30)
    finally:
        for f in (p.stdin, p.stdout):
            try:
                f.close()
            except OSError:
                pass


def stop(p, kill=False):
    """kill=True is a real crash (TerminateProcess); otherwise a clean exit on stdin EOF. Either way it is reaped."""
    try:
        if kill:
            p.kill()
        else:
            p.stdin.close()
        p.wait(timeout=30)
    finally:
        reap(p)


def test_lock_lives_outside_s1_out(tmp_path):                                          # row 132
    p = L.lock_path(tmp_path, TRIAL, L.stage_lock_name("audit"))
    assert p == tmp_path / "s1_locks" / TRIAL / "stage-audit.lock"
    assert (tmp_path / "s1_out") not in p.parents
    assert L.slot_lock_name("slot/20261102T214500Z") == "slot-20261102T214500Z" and L.STOP_LOCK == "stop"
    assert L.lock_path(tmp_path, TRIAL, L.stage_lock_name("seal/2026-10-27")).name == "stage-seal-2026-10-27.lock"


@pytest.mark.parametrize("stage", ["audit", "opening", "start_attest", "prereg", "stop_attest", "final_plan", "final",
                                   "score", "seal/2026-10-27", "seal/2028-02-29"])
def test_every_journal_stage_has_a_valid_lock_name(tmp_path, stage):                   # OQ-23 positive control
    assert L.lock_path(tmp_path, TRIAL, L.stage_lock_name(stage)).parent == tmp_path / "s1_locks" / TRIAL


def test_acquire_release_and_reacquire_in_one_process(tmp_path):
    a = L.OwnershipLock(tmp_path, TRIAL, "stage-audit").acquire()
    try:
        with pytest.raises(L.LockHeld):
            L.OwnershipLock(tmp_path, TRIAL, "stage-audit").acquire()
    finally:
        a.release()
    with L.OwnershipLock(tmp_path, TRIAL, "stage-audit"):
        pass


def test_held_by_another_process_is_held_not_dead(tmp_path):
    p, said = child(HOLD, HERE, tmp_path, TRIAL, "slot-20261102T214500Z")
    try:
        assert said == "acquired"
        with pytest.raises(L.LockHeld):
            L.OwnershipLock(tmp_path, TRIAL, "slot-20261102T214500Z").acquire()
    finally:
        stop(p)


def test_held_lock_cannot_be_deleted_renamed_or_replaced(tmp_path):                    # rows 133, 232
    p, said = child(HOLD, HERE, tmp_path, TRIAL, "stop")
    path = L.lock_path(tmp_path, TRIAL, "stop")
    other = tmp_path / "other.txt"
    other.write_text("x")
    try:
        assert said == "acquired"
        with pytest.raises(PermissionError):
            os.remove(path)
        with pytest.raises(PermissionError):
            os.rename(path, tmp_path / "moved.lock")
        with pytest.raises(PermissionError):
            os.replace(other, path)
        assert path.exists()
    finally:
        stop(p)


def test_killed_owner_frees_the_lock(tmp_path):                                        # rows 134, 231
    p, said = child(HOLD, HERE, tmp_path, TRIAL, "stage-final")
    try:
        assert said == "acquired"
        with pytest.raises(L.LockHeld):                                # live owner: not acquirable
            L.OwnershipLock(tmp_path, TRIAL, "stage-final").acquire()
    finally:
        stop(p, kill=True)                                            # a real crash: the OS releases the handle
    with L.OwnershipLock(tmp_path, TRIAL, "stage-final"):
        pass


def test_leftover_acquirable_lock_file_is_no_liveness(tmp_path):                       # row 233
    path = L.lock_path(tmp_path, TRIAL, "stage-score")
    path.parent.mkdir(parents=True)
    path.write_text("pid 4242 started yesterday")                 # no PID inference
    with L.OwnershipLock(tmp_path, TRIAL, "stage-score"):
        with pytest.raises(L.LockHeld):                                # the acquisition is a real ownership
            L.OwnershipLock(tmp_path, TRIAL, "stage-score").acquire()


def test_deleted_lock_file_is_recreated_and_is_not_evidence(tmp_path):                 # row 135
    with L.OwnershipLock(tmp_path, TRIAL, "stage-prereg") as lk:
        path = lk.path
    path.unlink()
    with L.OwnershipLock(tmp_path, TRIAL, "stage-prereg"):
        assert path.exists()
        with pytest.raises(L.LockHeld):                                # the recreated file is a real lock
            L.OwnershipLock(tmp_path, TRIAL, "stage-prereg").acquire()


def test_concurrent_recovery_exactly_one_acquires(tmp_path):                           # row 136
    procs = []
    try:
        for _ in range(2):
            procs.append(spawn(HOLD, HERE, tmp_path, TRIAL, "stage-opening"))
        said = sorted(p.stdout.readline().strip() for p in procs)
        assert said == ["acquired", "held"]
    finally:
        for p in procs:
            stop(p)


def test_sharing_violation_from_any_holder_is_held(tmp_path):                          # row 137
    """Review Focus 5: a third program (AV, indexer) holding the file is 'held' (pending), never 'free'."""
    path = L.lock_path(tmp_path, TRIAL, "slot-20261102T214700Z")
    path.parent.mkdir(parents=True)
    path.write_bytes(b"")
    p, said = child(OPEN_PLAIN, path)
    try:
        assert said == "opened"
        with pytest.raises(L.LockHeld):
            L.OwnershipLock(tmp_path, TRIAL, "slot-20261102T214700Z").acquire()
    finally:
        stop(p)


def test_held_and_error_are_distinct_results():                                        # F5.5: exactly three
    assert not issubclass(L.LockError, L.LockHeld) and not issubclass(L.LockHeld, L.LockError)


@pytest.mark.parametrize("damage", ["directory-at-lock-path", "file-at-locks-dir"])
def test_io_error_is_error_not_held_or_free(tmp_path, damage):                         # row 137
    if damage == "directory-at-lock-path":
        L.lock_path(tmp_path, TRIAL, "slot-20261102T214900Z").mkdir(parents=True)
    else:
        (tmp_path / "s1_locks").write_text("not a directory")
    with pytest.raises(L.LockError):
        L.OwnershipLock(tmp_path, TRIAL, "slot-20261102T214900Z").acquire()
    with pytest.raises(L.LockError):                                   # the cleanup probe fails closed too (E1.4)
        L.lock_acquirable(tmp_path, TRIAL, "slot-20261102T214900Z")


BAD_NAMES = [
    (TRIAL, "../stage-audit"), (TRIAL, "slot-a/b"), (TRIAL, "stage-other"), ("S1", "stage-audit"),
    (TRIAL, "stage-seal-x"), (TRIAL, "stage-seal-2026-13-45"), (TRIAL, "stage-seal-2026-02-30"), (TRIAL, ".."),
    (TRIAL, "slot-a\\b"), (TRIAL, "stop/../stop"), (TRIAL, "stop\n"), (TRIAL, "STOP"), (TRIAL, ""),
    (TRIAL, "slot-２０２６１１０２T214500Z"), (TRIAL, None),
    ("../" + TRIAL, "stage-audit"), (TRIAL.upper(), "stage-audit"), (TRIAL + "\n", "stage-audit"),
    ("3f2b8c1e-5d4a-1b6c-9e7f-0a1b2c3d4e5f", "stage-audit"),
]
BAD_IDS = ["dotdot-name", "slash-name", "unknown-stage", "bad-trial", "seal-not-a-date", "seal-month-13",
           "seal-feb-30", "bare-dotdot", "backslash-name", "embedded-traversal", "trailing-newline", "upper-case",
           "empty", "fullwidth-digits", "non-str-name", "trial-traversal", "trial-upper", "trial-trailing-newline",
           "trial-uuid1"]


@pytest.mark.parametrize("trial,name", BAD_NAMES, ids=BAD_IDS)
def test_lock_names_and_trial_ids_are_validated(tmp_path, trial, name):             # row 309 (OQ-23)
    root = tmp_path / "root"                       # tmp_path itself holds the autouse conftest mailbox
    root.mkdir()
    before = sorted(tmp_path.rglob("*"))
    with pytest.raises(L.LockError):
        L.OwnershipLock(root, trial, name).acquire()
    with pytest.raises(L.LockError):
        L.lock_acquirable(root, trial, name)
    assert list(root.rglob("*")) == []                         # validation precedes any mkdir or open
    assert sorted(tmp_path.rglob("*")) == before               # and nothing escaped the root either


@pytest.mark.parametrize("subject", ["stage/audit", "slot", "slot/", "slot/../x", "slot/20261102T214500Z/x"])
def test_slot_lock_name_rejects_a_non_slot_subject(subject):                           # OQ-23
    with pytest.raises(L.LockError):
        L.slot_lock_name(subject)


def test_lock_acquirable_probe(tmp_path):                                              # E1.4 seam (rows 257, 259)
    name = "slot-20261102T214500Z"
    assert L.lock_acquirable(tmp_path, TRIAL, name) is True
    p, said = child(HOLD, HERE, tmp_path, TRIAL, name)
    try:
        assert said == "acquired" and L.lock_acquirable(tmp_path, TRIAL, name) is False
    finally:
        stop(p)
    assert L.lock_acquirable(tmp_path, TRIAL, name) is True
