"""A3 Task 15a (controller ruling R2): reconcile raw Cosmic Ray outcomes with the cr_guard sidecars.

Raw Cosmic Ray 8.3.15 labels are NOT evidence: cosmic_ray/testing.py maps any nonzero exit AND a TimeoutExpired
(output "timeout") to KILLED. So the raw label is recorded side by side with a reconciled label:

* raw CR timeout (test_outcome killed, output == "timeout")         -> timeout, ALWAYS (whatever any sidecar says)
* raw killed, sidecar status "killed" whose job_id AND attempt match -> killed (the attempt is read from the
  guard stdout line Cosmic Ray stored as the result output; retries reuse job ids, so job_id alone is not enough)
* raw killed, sidecar status "timeout"                               -> timeout
* raw killed, anything else (other status, missing/foreign sidecar)  -> error   (never killed)
* raw survived -> the sidecar decides: survived->survived, timeout->timeout, crash->crash,
  empty/skip/node_set_mismatch->untested, anything else (error:*, cleanup_uncertain, missing, killed) -> error
* raw incompetent (CR could not launch the command)                  -> crash
* worker outcome exception -> error; abnormal -> crash; no-test (no mutation possible) -> not-installed;
  skipped (scope filter) -> skipped-by-scope; no result row -> deferred.

"failed-elsewhere" belongs to the Task 15b semantic classifier and "equivalent" only to a later peer-reviewed
disposition; neither is ever produced here. The session DB is opened READ-ONLY with sqlite3 (the WorkDB constructor
would run CREATE TABLE on it). Part of the mutation harness: excluded from inventories, hashed separately.
"""
import hashlib
import json
import re
import sqlite3
from pathlib import Path

from cr_guard import BUDGETS  # noqa: F401  (the single budget table; re-exported for the harness)

LABELS = ("killed", "survived", "error", "untested", "timeout", "crash", "not-installed", "failed-elsewhere",
          "equivalent", "skipped-by-scope", "deferred")
SCHEMA = "a3-t15a-classification/1"
# cr_guard prints this line; Cosmic Ray stores the guard's stdout as the result output (testing.py:48,51), so it binds
# a raw result to exactly one guard attempt (fix round 1, M3: retries reuse job ids). The attempt id is the FIRST field
# (fix round 2, R1-N3), so a status containing spaces (e.g. "error:usage:duplicate --deadline") cannot break it.
_ATTEMPT_RE = re.compile(r"^cr_guard: attempt=([0-9A-Za-z_-]+) exit=-?\d+ status=", re.MULTILINE)


def guard_attempt(output):
    found = _ATTEMPT_RE.findall(output or "")
    return found[-1] if len(found) == 1 else None          # zero or several guard runs: unbound

# SQLAlchemy's Enum column stores the enum NAME (e.g. "NO_TEST"); accept the value spelling too.
_WORKER = {"NORMAL": "normal", "EXCEPTION": "exception", "ABNORMAL": "abnormal", "NO_TEST": "no-test",
           "SKIPPED": "skipped"}
_TEST = {"SURVIVED": "survived", "KILLED": "killed", "INCOMPETENT": "incompetent"}
_SURVIVED_SIDECAR = {"survived": "survived", "timeout": "timeout", "crash": "crash", "empty": "untested",
                     "skip": "untested", "node_set_mismatch": "untested"}


def _args(stored):
    """WorkDB stores json.dumps(args) in a JSON column, i.e. JSON-encoded twice; decode until a dict."""
    v = json.loads(stored) if stored else {}
    return json.loads(v) if isinstance(v, str) else v


def _norm(v, table):
    if v is None:
        return None
    return table.get(v, v if v in table.values() else str(v).lower())


def read_session(session_db: Path) -> list[dict]:
    """Every WorkItem with its (possibly absent) result, from the CR session, opened read-only."""
    uri = Path(session_db).resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        specs = {}
        for row in con.execute("SELECT job_id, module_path, operator_name, operator_args, occurrence, start_pos_row,"
                               " start_pos_col, end_pos_row, end_pos_col FROM mutation_specs"):
            specs.setdefault(row[0], []).append({"module_path": row[1], "operator": row[2],
                                                 "operator_args": _args(row[3]), "occurrence": row[4],
                                                 "start": [row[5], row[6]], "end": [row[7], row[8]]})
        results = {r[0]: r[1:] for r in con.execute(
            "SELECT job_id, worker_outcome, test_outcome, output FROM work_results")}
        jobs = [r[0] for r in con.execute("SELECT job_id FROM work_items ORDER BY job_id")]
    finally:
        con.close()
    out = []
    for job in jobs:
        res = results.get(job)
        raw = None if res is None else {"worker_outcome": _norm(res[0], _WORKER), "test_outcome": _norm(res[1], _TEST),
                                        "cr_timeout": _norm(res[1], _TEST) == "killed" and res[2] == "timeout",
                                        "guard_attempt": guard_attempt(res[2])}
        out.append({"job_id": job, "mutations": specs.get(job, []), "raw": raw})
    return out


def _sidecar(jobs_root: Path, job: str):
    p = Path(jobs_root) / job / "guard.json"
    if not p.is_file():
        return None, None
    try:
        return json.loads(p.read_text(encoding="utf-8")), hashlib.sha256(p.read_bytes()).hexdigest()
    except ValueError:
        return {"status": "error:sidecar_unparsable"}, hashlib.sha256(p.read_bytes()).hexdigest()


def label_for(raw: dict | None, side: dict | None, job: str) -> tuple[str, str]:
    """(reconciled label, reason). Pure; the whole override table lives here."""
    if raw is None:
        return "deferred", "no result in the session (pending)"
    wo, to = raw["worker_outcome"], raw["test_outcome"]
    if wo == "skipped":
        return "skipped-by-scope", "worker outcome skipped (scope filter)"
    if wo == "no-test":
        return "not-installed", "Cosmic Ray found no mutation to apply"
    if wo == "exception":
        return "error", "Cosmic Ray worker exception"
    if wo == "abnormal":
        return "crash", "Cosmic Ray worker ended abnormally"
    if to == "incompetent":
        return "crash", "Cosmic Ray could not run the test command"
    if raw["cr_timeout"]:
        return "timeout", "raw Cosmic Ray timeout (never a kill)"
    status = None if side is None else side.get("status")
    own = (side is not None and side.get("job_id") == job and raw.get("guard_attempt") is not None
           and side.get("attempt") == raw["guard_attempt"])
    if to == "killed":
        if own and status == "killed":
            return "killed", "guard sidecar killed"
        if own and status == "timeout":
            return "timeout", "guard sidecar timeout"
        return "error", f"raw killed without a matching guard 'killed' sidecar (status={status}, own={own})"
    if to == "survived":
        if own and status in _SURVIVED_SIDECAR:
            return _SURVIVED_SIDECAR[status], f"guard sidecar {status}"
        return "error", f"raw survived with guard status {status} (own={own})"
    return "error", f"unrecognised raw outcome {raw}"


def reconcile(session_db: Path, jobs_root: Path, out: Path) -> dict:
    """Write ``out`` (classification.json) with raw and reconciled labels side by side; return the same dict."""
    items = []
    for row in read_session(session_db):
        side, side_sha = _sidecar(jobs_root, row["job_id"])
        label, reason = label_for(row["raw"], side, row["job_id"])
        if label not in LABELS or label in ("equivalent", "failed-elsewhere"):
            raise RuntimeError(f"reconciler produced a forbidden label {label!r}")
        items.append(dict(row, sidecar_status=None if side is None else side.get("status"),
                          sidecar_sha256=side_sha, label=label, reason=reason))
    counts = {lab: sum(1 for i in items if i["label"] == lab) for lab in LABELS}
    res = {"schema": SCHEMA, "session": str(session_db),
           "session_sha256": hashlib.sha256(Path(session_db).read_bytes()).hexdigest(),
           "items": items, "counts": counts}
    Path(out).write_text(json.dumps(res, indent=1, sort_keys=True), encoding="utf-8")
    return res
