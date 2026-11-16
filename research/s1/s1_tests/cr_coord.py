"""A3 Task 15a (controller rulings R3, R4/R5, R8): the Cosmic Ray coordinator and WorkDB range filter.

* Inventory: ``cosmic-ray init`` on a SCRATCH copy (never the worktree), read back read-only and frozen as
  inventory.json (refuses to overwrite; sha256 recorded next to it).
* Range filter (R8): qualified-name ranges derived from the final AST (methods and nested scopes included, decorators
  included), recorded in ranges.json with the source sha256. A name resolving 0 or >1 times raises ScopeError; nothing
  is ever substituted. No pragma is written to any source. Items outside the ranges are dispositioned
  "skipped-by-scope" (and, in a WorkDB, marked through the installed WorkDB API exactly as cr-filter-pragma does).
* Deterministic ordering, batches of at most BUDGETS["batch_max"], and an exact-partition check (nothing lost,
  nothing duplicated, nothing unknown).
* run_batch: ONE WorkItem per fresh disposable copy, each in its own one-item CR session DB. After a timeout, cleanup
  uncertainty, source drift, an unrestored mutation or an exec exception, the copy is QUARANTINED and the batch STOPS;
  every unexecuted ID stays explicitly pending in batch_<id>_state.json (never overwritten; a later batch in the same
  work_root refuses to start until resolve_stop records a resolution; the session clock is persisted in
  session.json and spans every batch). Two CR processes never share a tree (strictly
  sequential, one copy each).
* real_exec: runs the installed CR through cr_launch.py with the explicit testenv interpreter (never
  ``python -m cosmic_ray``, never -c or stdin), contained in a Win32 Job Object (cr_guard.run_contained), then
  reconciles the one-item session with the guard sidecar (cr_reconcile).

Part of the mutation harness: excluded from every inventory and hashed separately.
"""
import ast
import hashlib
import json
import os
import re
import shlex
import shutil
import time
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path, PurePosixPath

import cr_guard
import cr_reconcile
from cr_guard import BUDGETS

HARNESS_DIR = Path(__file__).resolve().parent
LAUNCHER = HARNESS_DIR / "cr_launch.py"
HARNESS_FILES = ("cr_guard.py", "cr_reconcile.py", "cr_coord.py", "cr_launch.py")
SCHEMA = "a3-t15a-coord/1"
_COPY_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".hypothesis", ".pytest_cache")


class ScopeError(ValueError):
    """A range-filter name did not resolve exactly once, or an item belongs to another module."""


class PartitionError(ValueError):
    """Batches do not partition the inventory exactly, or a batch is over the cap."""


class CoordError(RuntimeError):
    """A coordinator precondition failed (existing inventory, reused copy/job dir, init failure...)."""


@dataclass
class CRConfig:
    python: Path                                     # the explicit testenv interpreter
    module_rel: str                                  # module-path, relative to the copy root (posix)
    guard_args: list                                 # cr_guard options + pytest targets, after the --deadline
    pythonpath_rel: list = field(default_factory=lambda: ["."])
    timeout_s: float = BUDGETS["cr_timeout_s"]
    guard_deadline_s: float = BUDGETS["guard_inner_deadline_s"]
    target_module: str | None = None                 # dotted module the copy must supply (I4); required


def retry_config(cfg: CRConfig) -> CRConfig:
    """The single retry (R4/R5): CR timeout BUDGETS["retry_cr_timeout_s"], with the inner deadline keeping the same
    margin below it as the initial run (300 - 240 = 60 s, so 600 - 60 = 540 s)."""
    margin = BUDGETS["cr_timeout_s"] - BUDGETS["guard_inner_deadline_s"]
    return CRConfig(python=cfg.python, module_rel=cfg.module_rel, guard_args=list(cfg.guard_args),
                    pythonpath_rel=list(cfg.pythonpath_rel), timeout_s=BUDGETS["retry_cr_timeout_s"],
                    guard_deadline_s=BUDGETS["retry_cr_timeout_s"] - margin, target_module=cfg.target_module)


def _sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _posix(p) -> str:
    return str(p).replace("\\", "/")


def _dump(path: Path, obj) -> None:
    Path(path).write_text(json.dumps(obj, indent=1, sort_keys=True), encoding="utf-8")


def harness_hashes() -> dict:
    return {name: _sha(HARNESS_DIR / name) for name in HARNESS_FILES}


# ------------------------------------------------------------------------------------------------ config + copies
def test_command(cfg: CRConfig) -> str:
    deadline = int(cfg.guard_deadline_s) if cfg.guard_deadline_s == int(cfg.guard_deadline_s) else cfg.guard_deadline_s
    if deadline + BUDGETS["cleanup_reserve_s"] >= cfg.timeout_s:
        raise CoordError(f"guard deadline {deadline} + cleanup reserve must stay below the CR timeout {cfg.timeout_s}")
    rel_parts = PurePosixPath(_posix(cfg.module_rel)).parts
    if ".cr_harness" in rel_parts or (rel_parts and rel_parts[-1] in HARNESS_FILES + ("conftest.py",)):
        raise CoordError(f"module_rel {cfg.module_rel!r} names a harness file; the harness is never a mutation target")
    if not cfg.target_module:
        raise CoordError("target_module is required: without it the guard cannot prove the child imported the copy")
    parts = [_posix(cfg.python), "-m", "cr_guard", "--deadline", str(deadline), "--target", cfg.target_module,
             *(_posix(a) for a in cfg.guard_args)]
    return " ".join(shlex.quote(p) for p in parts)        # CR splits it with shlex.split (posix rules)


test_command.__test__ = False                               # not a pytest test, despite the name


def write_cr_toml(path: Path, cfg: CRConfig) -> None:
    text = ("[cosmic-ray]\n"
            f"module-path = {json.dumps(_posix(cfg.module_rel))}\n"
            f"timeout = {float(cfg.timeout_s)}\n"
            "excluded-modules = []\n"
            f"test-command = {json.dumps(test_command(cfg))}\n\n"
            "[cosmic-ray.distributor]\n"
            'name = "local"\n')
    Path(path).write_text(text, encoding="utf-8")


def make_copy(src_root: Path, copy_paths, dest: Path) -> dict:
    """A fresh disposable copy of the needed source; returns {relpath: sha256} of every copied file."""
    src_root, dest = Path(src_root), Path(dest)
    if dest.exists():
        raise CoordError(f"copy destination {dest} already exists (copies are never reused)")
    dest.mkdir(parents=True)
    for rel in copy_paths:
        s, d = src_root / rel, dest / rel
        if s.is_dir():
            shutil.copytree(s, d, ignore=_COPY_IGNORE)
        elif s.is_file():
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, d)
        else:
            raise CoordError(f"copy path {rel} does not exist under {src_root}")
    return {_posix(p.relative_to(dest)): _sha(p) for p in sorted(dest.rglob("*")) if p.is_file()}


def _copy_harness(copy_root: Path, cfg: CRConfig) -> list[str]:
    """I4: the copy is self-sufficient. If a pythonpath dir of the copy already carries cr_guard.py (a real S1 copy
    has research/s1/s1_tests/cr_guard.py; run_batch has checked it is byte-identical) nothing is added. Otherwise
    the reviewed cr_guard.py ALONE is copied to <copy>/.cr_harness. The worktree s1_tests dir (conftest, helpers,
    unmutated sources reachable through them) is never put on the child's path."""
    if any((Path(copy_root) / r / "cr_guard.py").is_file() for r in cfg.pythonpath_rel):
        return []
    h = Path(copy_root) / ".cr_harness"
    h.mkdir(exist_ok=True)
    shutil.copy2(HARNESS_DIR / "cr_guard.py", h / "cr_guard.py")
    return [str(h.resolve())]


def _env(copy_root: Path, cfg: CRConfig, job_dir: Path | None = None, job_id: str | None = None) -> dict:
    env = dict(os.environ)
    paths = [str((Path(copy_root) / r).resolve()) for r in cfg.pythonpath_rel]
    if job_dir is not None:
        paths += _copy_harness(copy_root, cfg)
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=os.pathsep.join(paths))
    for k in (cr_guard.JOB_DIR_ENV, cr_guard.JOB_ID_ENV, cr_guard.NODES_ENV, cr_guard.ATTEMPT_ENV,
              cr_guard.TARGETS_ENV):
        env.pop(k, None)
    if job_dir is not None:
        env.update({cr_guard.JOB_DIR_ENV: str(job_dir), cr_guard.JOB_ID_ENV: job_id,
                    "S1_HYPOTHESIS_ROOT": str(Path(job_dir) / "hypothesis")})
    return env


def _launch(cfg: CRConfig, args, *, cwd: Path, env: dict, log_dir: Path, tag: str, deadline_s: float) -> dict:
    cmd = [str(cfg.python), str(LAUNCHER), *[str(a) for a in args]]
    run = cr_guard.run_contained(cmd, cwd=cwd, env=env, stdout_path=log_dir / f"{tag}_stdout.txt",
                                 stderr_path=log_dir / f"{tag}_stderr.txt", deadline_s=deadline_s)
    _dump(log_dir / f"{tag}_run.json", dict(run, cmd=cmd))
    return run


# ----------------------------------------------------------------------------------------------------- inventory
def _flat(row: dict) -> dict:
    if len(row["mutations"]) != 1:
        raise CoordError(f"WorkItem {row['job_id']} has {len(row['mutations'])} mutations (expected exactly 1)")
    (m,) = row["mutations"]
    return {"job_id": row["job_id"], "module_path": _posix(m["module_path"]), "operator": m["operator"],
            "operator_args": m["operator_args"], "occurrence": m["occurrence"], "start": list(m["start"]),
            "end": list(m["end"])}


def inventory(src_root: Path, copy_paths, cfg: CRConfig, work_root: Path) -> list[dict]:
    """``cosmic-ray init`` on a scratch copy; freeze every WorkItem (deterministically ordered) in inventory.json."""
    work_root = Path(work_root)
    inv = work_root / "inventory.json"
    if inv.exists():
        raise CoordError(f"{inv} already exists: an inventory is immutable")
    work_root.mkdir(parents=True, exist_ok=True)
    scratch = work_root / "inventory_copy"
    copied = make_copy(src_root, copy_paths, scratch)
    write_cr_toml(scratch / "cr.toml", cfg)
    run = _launch(cfg, ["cosmic-ray", "init", "cr.toml", "session.sqlite"], cwd=scratch, env=_env(scratch, cfg),
                  log_dir=work_root, tag="init", deadline_s=BUDGETS["cr_timeout_s"])
    if run["timed_out"] or run["rc"] != 0 or not run["cleanup"]["verified"]:
        raise CoordError(f"cosmic-ray init failed: rc={run['rc']} timed_out={run['timed_out']}")
    items = order_items([_flat(r) for r in cr_reconcile.read_session(scratch / "session.sqlite")])
    src_mod = Path(src_root) / cfg.module_rel
    if _sha(src_mod) != copied.get(_posix(cfg.module_rel)):
        raise CoordError("source drift between the worktree module and its scratch copy")
    doc = {"schema": SCHEMA, "module_rel": _posix(cfg.module_rel), "source_sha256": _sha(src_mod),
           "copied": copied, "session_sha256": _sha(scratch / "session.sqlite"), "test_command": test_command(cfg),
           "cosmic_ray_version": metadata.version("cosmic-ray"), "harness_sha256": harness_hashes(),
           "count": len(items), "items": items}
    _dump(inv, doc)
    (work_root / "inventory.json.sha256").write_text(f"{_sha(inv)} *inventory.json\n", encoding="utf-8")
    return items


# ----------------------------------------------------------------------------------------------- R8 range filter
def _scopes(tree: ast.AST) -> list[tuple]:
    """Every def/class as (qualname, kind, first line incl. decorators, last line); nested scopes dotted."""
    out = []

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                q = f"{prefix}.{child.name}" if prefix else child.name
                start = min([child.lineno] + [d.lineno for d in child.decorator_list])
                kind = "class" if isinstance(child, ast.ClassDef) else "function"
                out.append((q, kind, start, child.end_lineno))
                walk(child, q)
            else:
                walk(child, prefix)                     # defs under if/try/with stay in the enclosing scope
    walk(tree, "")
    return out


def scope_ranges(source: Path, names, out: Path | None = None, module_rel: str | None = None) -> dict:
    """Resolve each name to exactly one scope of the final AST. A bare name matches the last component of any
    qualname (so a nested duplicate is ambiguous, never guessed); a dotted name matches one qualname exactly."""
    source = Path(source)
    text = source.read_bytes()
    scopes = _scopes(ast.parse(text, filename=str(source)))
    resolved = {}
    for name in names:
        hits = [s for s in scopes if (s[0] == name if "." in name else s[0].split(".")[-1] == name)]
        if len(hits) != 1:
            listing = (": " + ", ".join(s[0] for s in hits)) if hits else ""
            raise ScopeError(f"'{name}' resolves {len(hits)} times{listing} in {source.name}")
        q, kind, start, end = hits[0]
        resolved[name] = {"qualname": q, "kind": kind, "start": start, "end": end}
    doc = {"schema": "a3-t15a-ranges/1", "source": _posix(source), "module_rel": module_rel or source.name,
           "sha256": hashlib.sha256(text).hexdigest(),
           "rule": "keep a WorkItem iff its mutation line span overlaps a named scope's [start,end] "
                   "(decorators..last body line, nested defs and methods included); others skipped-by-scope",
           "scopes": resolved}
    if out is not None:
        _dump(out, doc)
    return doc


def _span(item: dict) -> tuple[int, int]:
    (r0, _), (r1, c1) = item["start"], item["end"]
    if c1 == 0 and r1 > r0:                             # ends at the start of a line: the previous line is the last
        r1 -= 1
    return r0, r1


def filter_by_scope(items, ranges: dict) -> tuple[list, list]:
    kept, excluded = [], []
    for it in items:
        if _posix(it["module_path"]) != ranges["module_rel"]:
            raise ScopeError(f"item {it['job_id']} is in {it['module_path']}, not {ranges['module_rel']}")
        r0, r1 = _span(it)
        hit = [n for n, s in ranges["scopes"].items() if r0 <= s["end"] and s["start"] <= r1]
        if hit:
            kept.append(dict(it, scope=sorted(hit)))
        else:
            excluded.append(dict(it, disposition="skipped-by-scope", ranges_sha256=ranges["sha256"]))
    return kept, excluded


def mark_skipped_by_scope(session_db: Path, job_ids) -> None:
    """Record the exclusion in a CR WorkDB via the installed API (as cr-filter-pragma does): worker outcome SKIPPED."""
    from cosmic_ray.work_db import WorkDB, use_db
    from cosmic_ray.work_item import WorkerOutcome, WorkResult
    job_ids = list(job_ids)
    with use_db(str(session_db), WorkDB.Mode.open) as w:
        unknown = sorted(set(job_ids) - {i.job_id for i in w.work_items})
        if unknown:
            raise ScopeError(f"unknown job ids for the scope filter: {unknown}")
        w.set_multiple_results(job_ids, WorkResult(worker_outcome=WorkerOutcome.SKIPPED))


# ------------------------------------------------------------------------------------ ordering + batch partition
def order_items(items, priority: dict | None = None) -> list[dict]:
    """Deterministic: caller priority (lower first), then location, operator, occurrence, job id."""
    pr = priority or {}
    return sorted(items, key=lambda i: (pr.get(i["job_id"], 0), _posix(i["module_path"]), tuple(i["start"]),
                                        tuple(i["end"]), i["operator"], i["occurrence"], i["job_id"]))


def plan_batches(ids, size: int = BUDGETS["batch_max"]) -> list[list[str]]:
    if not 1 <= size <= BUDGETS["batch_max"]:
        raise PartitionError(f"batch size {size} exceeds the {BUDGETS['batch_max']} cap (or is < 1)")
    ids = list(ids)
    if len(set(ids)) != len(ids):
        raise PartitionError("duplicated ids in the ordered inventory")
    batches = [ids[i:i + size] for i in range(0, len(ids), size)]
    check_partition(ids, batches)
    return batches


def check_partition(ids, batches) -> None:
    flat = [j for b in batches for j in b]
    lost = sorted(set(ids) - set(flat))
    dup = sorted({j for j in flat if flat.count(j) > 1})
    unknown = sorted(set(flat) - set(ids))
    over = [len(b) for b in batches if len(b) > BUDGETS["batch_max"]]
    if lost or dup or unknown or over:
        raise PartitionError(f"batch partition invalid: lost: {lost}, duplicated: {dup}, unknown: {unknown}, "
                             f"oversized: {over}")


def write_manifests(work_root: Path, batches, inventory_sha256: str) -> list[Path]:
    paths = []
    for n, b in enumerate(batches):
        p = Path(work_root) / f"batch_{n:03d}.json"
        if p.exists():
            raise CoordError(f"{p} already exists")
        _dump(p, {"schema": SCHEMA, "batch_index": n, "inventory_sha256": inventory_sha256, "items": list(b)})
        paths.append(p)
    return paths


# ------------------------------------------------------------------------------------------- one-item execution
_BATCH_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _stop_reason(result: dict, restored: bool) -> str | None:
    if result.get("guard_status") == "cleanup_uncertain" or not result.get("cleanup_verified", False):
        return "cleanup_uncertain"
    if result.get("exec_status", "ok") != "ok":
        return str(result["exec_status"])
    if result.get("raw_timeout") or result.get("guard_status") == "timeout":
        return "timeout"
    if not restored:
        return "source_not_restored"
    return None


def _state_path(work_root: Path, batch_id: str) -> Path:
    return Path(work_root) / f"batch_{batch_id}_state.json"


def _resolution_path(work_root: Path, batch_id: str) -> Path:
    return Path(work_root) / f"batch_{batch_id}_resolution.json"


def _interrupted(s: dict) -> bool:
    """A batch that never recorded a stop but still has pending items: its coordinator died mid-item (R1-M1). Its
    cleanup is unverified, so it counts as an unresolved stop."""
    return not s.get("stopped") and bool(s.get("pending"))


def describe_stop(s: dict) -> str:
    who = f"retry of {s['retry_of']} (batch {s['batch_id']})" if s.get("retry_of") else f"batch {s['batch_id']}"
    if s.get("stopped"):
        return f"{who} STOPPED ({s['stop_reason']})"
    return f"{who} INTERRUPTED (not stopped, pending {s['pending']})"


def unresolved_stops(work_root: Path) -> list[dict]:
    """Every batch that STOPPED, or was interrupted with items pending (R1-M1), and has no recorded resolution
    artifact next to its state: the batches in ``work_root`` AND every retry session under ``work_root``/retries/
    (R2-M1: a retry's own stop, e.g. cleanup_uncertain, gates the parent work_root too). Each returned state carries
    its directory as ``_root`` (in memory only), which is where resolve_stop must record the resolution."""
    root = Path(work_root)
    paths = sorted(root.glob("batch_*_state.json")) + sorted(root.glob("retries/*/batch_*_state.json"))
    out = []
    for p in paths:
        s = json.loads(p.read_text(encoding="utf-8"))
        if (s.get("stopped") or _interrupted(s)) and not _resolution_path(p.parent, s["batch_id"]).exists():
            out.append(dict(s, _root=str(p.parent)))
    return out


def resolve_stop(work_root: Path, batch_id: str, *, by: str, note: str) -> Path:
    """Record (never imply) that a STOPPED or INTERRUPTED batch was reviewed: who, why, and the exact state bytes it
    refers to. Only after this may another batch run in the same work_root. The state itself is never modified."""
    state = _state_path(work_root, batch_id)
    if not state.is_file():
        raise CoordError(f"no state for batch {batch_id} in {work_root}")
    s = json.loads(state.read_text(encoding="utf-8"))
    if not (s.get("stopped") or _interrupted(s)):
        raise CoordError(f"batch {batch_id} neither stopped nor was interrupted; nothing to resolve")
    res = _resolution_path(work_root, batch_id)
    if res.exists():
        raise CoordError(f"{res.name} already exists")
    if not by or not note:
        raise CoordError("a resolution needs who (by) and why (note)")
    _dump(res, {"schema": SCHEMA, "batch_id": batch_id, "by": by, "note": note, "resolves": describe_stop(s),
                "stop_reason": s.get("stop_reason"), "state_sha256": _sha(state),
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    return res


def _session_start(work_root: Path, clock) -> float:
    """The session clock spans every batch in the work_root: its start is persisted on the first batch."""
    p = Path(work_root) / "session.json"
    if p.is_file():
        return float(json.loads(p.read_text(encoding="utf-8"))["started"])
    now = float(clock())
    _dump(p, {"schema": SCHEMA, "started": now, "session_length_s": BUDGETS["session_length_s"]})
    return now


def run_batch(batch, items_by_id: dict, *, batch_id: str, src_root: Path, copy_paths, work_root: Path, exec_seam,
              source_sha256: dict | None = None, clock=time.time, extra: dict | None = None) -> dict:
    """Execute a batch strictly sequentially, one WorkItem per fresh disposable copy. Stops (quarantining the copy)
    on the first timeout / cleanup uncertainty / drift / unrestored source / exec exception; pending IDs are kept.

    Fix round 1 (I2): the state lives in ``batch_<batch_id>_state.json`` and is never overwritten; a batch refuses
    to start while any earlier batch in the same work_root is STOPPED without a recorded resolution (resolve_stop).
    ``source_sha256`` ({module_rel: sha256}, normally from inventory.json) is what each copy must match."""
    batch = list(batch)
    if not _BATCH_ID.match(str(batch_id)):
        raise CoordError(f"invalid batch id {batch_id!r}")
    if len(batch) > BUDGETS["batch_max"] or len(set(batch)) != len(batch):
        raise PartitionError(f"batch of {len(batch)} items is over the {BUDGETS['batch_max']} cap or has duplicates")
    work_root, src_root = Path(work_root), Path(src_root)
    work_root.mkdir(parents=True, exist_ok=True)
    state_path = _state_path(work_root, batch_id)
    if state_path.exists():
        raise CoordError(f"{state_path.name} already exists: a batch state is never overwritten")
    blocked = unresolved_stops(work_root)
    if blocked:
        b = blocked[0]
        raise CoordError(f"{describe_stop(b)} and is unresolved; record a resolution "
                         f"with resolve_stop({b['_root']!r}, {b['batch_id']!r}, ...) before running batch {batch_id}")
    started = _session_start(work_root, clock)
    copies, jobs, quarantine = work_root / "copies", work_root / "jobs", work_root / "quarantine"
    for d in (copies, jobs, quarantine):
        d.mkdir(parents=True, exist_ok=True)
    st = {"schema": SCHEMA, "batch_id": batch_id, "batch": batch, "done": [], "quarantined": [],
          "pending": list(batch), "stopped": False, "stop_reason": None, "labels": {}, "results": {},
          "session_started": started, "harness_sha256": harness_hashes(), **(extra or {})}

    def stop(job, reason, copy_root=None):
        if copy_root is not None and copy_root.exists():
            dest, n = quarantine / job, 1
            while dest.exists():                     # never nest into an earlier quarantine of the same id
                dest, n = quarantine / f"{job}.{n}", n + 1
            shutil.move(str(copy_root), str(dest))
            st["quarantined"].append(job)
            st["pending"].remove(job)
        st.update(stopped=True, stop_reason=f"{reason}: {job}")
        _dump(state_path, st)

    _dump(state_path, st)
    for job in batch:
        needed = BUDGETS["cr_timeout_s"] + BUDGETS["cleanup_reserve_s"]
        if clock() - started + needed > BUDGETS["session_length_s"]:
            st.update(stopped=True, stop_reason=f"session_budget: {job}")
            _dump(state_path, st)
            break
        if job not in items_by_id:
            stop(job, "unknown_item")
            raise CoordError(f"unknown item {job} (not in the inventory); stop recorded in {state_path.name}")
        item = items_by_id[job]
        mod_rel = _posix(item["module_path"])
        copy_root = copies / job
        if copy_root.exists():
            stop(job, "copy_exists")                 # not ours to move: leave it where it is
            raise CoordError(f"copy destination {copy_root} already exists; stop recorded in {state_path.name}")
        copied = make_copy(src_root, copy_paths, copy_root)
        want = (source_sha256 or {}).get(mod_rel) or _sha(src_root / mod_rel)
        if copied.get(mod_rel) != want:
            stop(job, "source_drift", copy_root)
            break
        drift = [n for n in HARNESS_FILES for p in copy_root.rglob(n) if _sha(p) != _sha(HARNESS_DIR / n)]
        if drift:
            stop(job, f"harness_drift({','.join(sorted(set(drift)))})", copy_root)
            break
        job_dir = jobs / job
        if job_dir.exists():
            stop(job, "job_dir_reused", copy_root)
            break
        job_dir.mkdir()
        try:
            result = exec_seam(item, copy_root, job_dir)
        except Exception as exc:                        # noqa: BLE001 - any failure here is a stop, never a label
            st["results"][job] = {"exception": f"{type(exc).__name__}: {exc}"}
            stop(job, "exec_exception", copy_root)
            break
        st["results"][job] = result
        st["labels"][job] = result.get("label")
        restored = (copy_root / mod_rel).is_file() and _sha(copy_root / mod_rel) == copied[mod_rel]
        reason = _stop_reason(result, restored)
        if reason:
            stop(job, reason, copy_root)
            break
        shutil.rmtree(copy_root)                        # disposable: evidence lives in jobs/<id>/, not in the copy
        st["done"].append(job)
        st["pending"].remove(job)
        _dump(state_path, st)
    return st


def run_manifest(manifest: Path, inventory_path: Path, *, src_root: Path, copy_paths, work_root: Path, exec_seam,
                 clock=time.time) -> dict:
    """Run one batch manifest against the EXACT inventory bytes it was written for (I5)."""
    man = json.loads(Path(manifest).read_text(encoding="utf-8"))
    inv_sha = _sha(inventory_path)
    if inv_sha != man["inventory_sha256"]:
        raise CoordError(f"inventory sha256 {inv_sha} does not match the manifest ({man['inventory_sha256']})")
    inv = json.loads(Path(inventory_path).read_text(encoding="utf-8"))
    items_by_id = {i["job_id"]: i for i in inv["items"]}
    unknown = sorted(set(man["items"]) - set(items_by_id))
    if unknown:
        raise CoordError(f"manifest items not in the inventory: {unknown}")
    return run_batch(man["items"], items_by_id, batch_id=f"{int(man['batch_index']):03d}", src_root=src_root,
                     copy_paths=copy_paths, work_root=work_root, exec_seam=exec_seam,
                     source_sha256={inv["module_rel"]: inv["source_sha256"]}, clock=clock,
                     extra={"manifest": str(manifest), "manifest_sha256": _sha(manifest),
                            "inventory_sha256": inv_sha})


def real_exec(cfg: CRConfig):
    """The production exec seam: one-item CR session in ``job_dir`` against ``copy_root``, then reconcile."""
    from cosmic_ray.work_db import WorkDB, use_db
    from cosmic_ray.work_item import MutationSpec, WorkItem

    def seam(item: dict, copy_root: Path, job_dir: Path) -> dict:
        if _posix(item["module_path"]) != _posix(cfg.module_rel):
            raise CoordError(f"item {item['job_id']} targets {item['module_path']}, config targets {cfg.module_rel}")
        job = item["job_id"]
        toml, session = job_dir / "cr.toml", job_dir / "session.sqlite"
        write_cr_toml(toml, cfg)
        with use_db(str(session), WorkDB.Mode.create) as w:
            w.add_work_item(WorkItem.single(job, MutationSpec(
                module_path=item["module_path"], operator_name=item["operator"], occurrence=item["occurrence"],
                start_pos=tuple(item["start"]), end_pos=tuple(item["end"]), operator_args=item["operator_args"])))
        run = _launch(cfg, ["cosmic-ray", "exec", toml, session], cwd=copy_root,
                      env=_env(copy_root, cfg, job_dir, job), log_dir=job_dir, tag="cr_exec",
                      deadline_s=cfg.timeout_s + BUDGETS["cleanup_reserve_s"])
        if run["timed_out"]:
            exec_status = "timeout"
        elif not run["cleanup"]["verified"]:
            exec_status = "cleanup_uncertain"
        else:
            exec_status = "ok" if run["rc"] == 0 else f"error:cr_exit_{run['rc']}"
        cls = cr_reconcile.reconcile(session, job_dir.parent, job_dir / "classification.json")
        (row,) = cls["items"]
        side_path = job_dir / "guard.json"
        side = json.loads(side_path.read_text(encoding="utf-8")) if side_path.is_file() else {}
        guard_clean = side.get("cleanup", {}).get("verified", True) if side else True
        return {"label": row["label"], "reason": row["reason"], "guard_status": row["sidecar_status"],
                "raw": row["raw"], "raw_timeout": bool(row["raw"] and row["raw"]["cr_timeout"]),
                "exec_status": exec_status, "cleanup_verified": bool(run["cleanup"]["verified"] and guard_clean),
                "session_sha256": cls["session_sha256"]}
    return seam


def retry_eligibility(job: str, items_by_id: dict, work_root: Path) -> tuple[list, dict]:
    """R1-I1: (initial labels, eligibility basis) or CoordError. A job may be retried only if
    * it is a known inventory item,
    * at least one recorded batch labelled it ``timeout`` (a raw CR timeout or a guard timeout; never killed,
      survived, error, cleanup_uncertain...),
    * that batch's stop is either this job's own timeout stop (``timeout: <job>``) or has a recorded resolution, and
    * no OTHER batch or retry session in the work_root is stopped or interrupted without a resolution."""
    if job not in items_by_id:
        raise CoordError(f"unknown job {job} (not in the inventory)")
    states = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(work_root).glob("batch_*_state.json"))]
    initial = [{"batch": s["batch_id"], "label": s["labels"][job]} for s in states if job in s.get("labels", {})]
    labels = [i["label"] for i in initial]
    if "timeout" not in labels:
        raise CoordError(f"{job} is not retry-eligible: initial labels {labels} (only a timeout gets the one retry)")
    tb = next(s for s in states if s.get("labels", {}).get(job) == "timeout")
    res = _resolution_path(work_root, tb["batch_id"])
    if res.exists():
        basis = {"timeout_batch": tb["batch_id"], "basis": "resolved", "resolution_sha256": _sha(res)}
    elif tb.get("stopped") and tb.get("stop_reason") == f"timeout: {job}":
        basis = {"timeout_batch": tb["batch_id"], "basis": "own_timeout_stop"}
    else:
        raise CoordError(f"{job} is not retry-eligible: {describe_stop(tb)} is neither {job}'s own timeout stop nor "
                         f"resolved")
    others = [s for s in unresolved_stops(work_root) if s["batch_id"] != tb["batch_id"]]
    if others:
        raise CoordError(f"{job} is not retry-eligible: {describe_stop(others[0])} is unresolved")
    return initial, basis


def run_retry(job: str, items_by_id: dict, cfg: CRConfig, *, src_root: Path, copy_paths, work_root: Path,
              exec_factory=real_exec, source_sha256: dict | None = None, clock=time.time) -> dict:
    """The ONE retry (R4/R5): a separately recorded one-item session under ``work_root``/retries/<job> with the
    retry budgets (CR 600 s, inner 540 s), only for an eligible timeout (retry_eligibility; the basis is recorded).
    The initial labels are copied from every batch state that holds the job (never modified); a second retry of the
    same job is refused."""
    rroot = Path(work_root) / "retries" / job
    if rroot.exists():
        raise CoordError(f"{job} was already retried ({rroot}); one retry only")
    initial, basis = retry_eligibility(job, items_by_id, work_root)
    rcfg = retry_config(cfg)
    return run_batch([job], items_by_id, batch_id="retry", src_root=src_root, copy_paths=copy_paths,
                     work_root=rroot, exec_seam=exec_factory(rcfg), source_sha256=source_sha256, clock=clock,
                     extra={"retry_of": job, "initial_labels": initial, "eligibility": basis,
                            "retry_budgets": {"cr_timeout_s": rcfg.timeout_s,
                                              "guard_deadline_s": rcfg.guard_deadline_s}})
