"""A3 H5a-FIX child process for test_s1_a3_early_refusal_lock.py (never a test module itself; run as a script by the
tests with the test interpreter, `-I`, the product directory passed explicitly so a scratch copy tests its own code).

  append <s1dir> <out> <k> <n> <ready> <go>  - import s1_slot, announce (write os.getpid() into) <ready>, wait for <go>, then call
      s1_slot.record_early_refusal(out, rec) n times with real-format C4 records (registered slot k of the
      2026-10-26 close, a unique pre-slot sample per call, the exact product C4 reason); prints one JSON line
      {"ok": [i, ...], "fail": {"i": "<class>", ...}} (None = recorded, else the returned failure class).
  hold <out> <offset> <held> <release>      - open <out>/early_refusals.jsonl for binary append (no directory is
      created), lock the 1-byte region at <offset> with msvcrt.locking (non-blocking), announce (os.getpid()) <held>, then hold it
      until <release> exists (or 120 s), exit 0. Exit 3 if the region could not be locked."""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _wait_for(p: Path, limit: float) -> bool:
    end = time.monotonic() + limit
    while not p.exists():
        if time.monotonic() > end:
            return False
        time.sleep(0.002)
    return True


def _announce(flag) -> None:
    """Create <flag> atomically holding this process's os.getpid() (A3 H5d PS-1: the test asserts it equals Popen.pid
    before it relies on kill/wait, so no launcher sits between the test and this process)."""
    tmp = Path(str(flag) + ".tmp")
    tmp.write_text(str(os.getpid()), encoding="ascii")
    os.replace(tmp, flag)


def append(s1dir, out, k, n, ready, go) -> int:
    sys.path.insert(0, s1dir)
    import s1_journal as j
    import s1_slot as sl
    s = datetime(2026, 10, 26, 20, 45, tzinfo=timezone.utc) + timedelta(minutes=2 * int(k))
    _announce(ready)
    if not _wait_for(Path(go), 60.0):
        print(json.dumps({"error": "no go"}))
        return 2
    ok, fail = [], {}
    for i in range(int(n)):
        sample = s - timedelta(seconds=1, microseconds=i + 1)
        rec = {"subject": j.slot_subject(s), "scheduled": s.isoformat(), "sample": sample.isoformat(),
               "reason": j.C4_REASON.format(slot=s.isoformat())}
        got = sl.record_early_refusal(out, rec)
        if got is None:
            ok.append(i)
        else:
            fail[str(i)] = got
    print(json.dumps({"ok": ok, "fail": fail}))
    return 0


def hold(out, offset, held, release) -> int:
    import msvcrt
    with open(Path(out) / "early_refusals.jsonl", "ab", buffering=0) as f:
        fd = f.fileno()
        os.lseek(fd, int(offset), os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return 3
        _announce(held)
        _wait_for(Path(release), 120.0)
        os.lseek(fd, int(offset), os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    return 0


if __name__ == "__main__":
    mode, args = sys.argv[1], sys.argv[2:]
    sys.exit(append(*args) if mode == "append" else hold(*args))
