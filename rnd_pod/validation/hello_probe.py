"""Throwaway probe: prove the worker can run app-runtime python and read trading.db read-only.
Run with: runtime/python/python.exe rnd_pod/validation/hello_probe.py
"""
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DB = REPO / "backend" / "trading.db"


def main() -> int:
    uri = f"file:{DB.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        tables = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    finally:
        con.close()
    print(f"trading.db opened read-only; {len(tables)} tables")
    # Prove read-only: a write must fail.
    con = sqlite3.connect(uri, uri=True)
    try:
        con.execute("CREATE TABLE _probe_should_fail (x INTEGER)")
        print("ERROR: write succeeded on a read-only handle")
        return 1
    except sqlite3.OperationalError:
        print("OK: write correctly rejected on read-only handle")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
