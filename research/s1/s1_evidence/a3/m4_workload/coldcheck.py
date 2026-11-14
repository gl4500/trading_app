"""Sanity check of the declared cold-cache method (test tooling): write a 3 GB file set, copy it with robocopy /J
(unbuffered real copies) and time the first and second full reads of the copy. If the first read is markedly slower
than the second, the /J copy did not leave the copy in the file cache. Usage: python coldcheck.py <scratch dir>"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

d = Path(sys.argv[1]) / "m4_coldcheck"
shutil.rmtree(d, ignore_errors=True)
src, dst = d / "src", d / "dst"
src.mkdir(parents=True)
for i in range(400):                                       # 400 x 7.6 MB ~ 3 GB, the backup file size
    (src / f"f{i:03d}.bin").write_bytes(os.urandom(7_600_000))


def read_all(p):
    t = time.perf_counter()
    n = 0
    for f in sorted(p.iterdir()):
        n += len(hashlib.sha256(f.read_bytes()).digest())
    return time.perf_counter() - t


def read_only(p):
    t = time.perf_counter()
    for f in sorted(p.iterdir()):
        f.read_bytes()
    return time.perf_counter() - t


t0 = time.perf_counter()
r = subprocess.run(["robocopy", str(src), str(dst), "/E", "/J", "/NFL", "/NDL", "/NJH", "/NJS", "/NP"],
                   capture_output=True, text=True)
copy_s = time.perf_counter() - t0
res = {"robocopy_rc": r.returncode, "copy_s": copy_s, "first_read_s_copy": read_only(dst),
       "second_read_s_copy": read_only(dst), "hash_pass_warm_s": read_all(dst), "bytes": 400 * 7_600_000}
res["first_read_GBps"] = res["bytes"] / res["first_read_s_copy"] / 1e9
res["second_read_GBps"] = res["bytes"] / res["second_read_s_copy"] / 1e9
res["sha256_GBps_warm"] = res["bytes"] / res["hash_pass_warm_s"] / 1e9
print(json.dumps(res, indent=1))
shutil.rmtree(d, ignore_errors=True)
