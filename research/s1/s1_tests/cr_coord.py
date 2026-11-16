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
* 15c-H (controller rulings on Codex t15c_prep_review_20261116): run_completion re-runs a screening survivor against
  every completion shard (merged by cr_reconcile.merge_attempts); check_pool_union pins completion shards to the frozen
  full node pool; run_batch enforces a HARD monotonic session fence (fence_s: outer item path + nested cleanup +
  measured I/O margin) on a session clock shared by nested retry/completion runs, records per-item costs, and accepts
  more than 24 items only with a calibration-derived cap record (derive_cap / read_cap_record). Sequential only.
* 15c-H fix round 1: only GUARD-CLEAN attempts count (cr_reconcile.attempt_clean; anything else -> "unresolved");
  run_completion verifies the declared shards against the frozen pool.json, resumes fence-refused shards after
  resolve_stop, and binds each attempt's executable/env/helpers/nodes/control; cap records are bound to one config
  (config_identity) and re-verified on every use; run_retry refuses completion-shard directories.
* 15c-H fix round 3 (Codex X23/X24 on 192e47c): a completion attempt's binding is computed at EXECUTION time from
  its copy and the child env _env builds, persisted in the state before the exec seam runs, and the merge reads only
  that; every cached/refused completion state is compared field by field with the current context before anything
  runs (drift raises; nothing is relabelled); the screening label is reused only if the screening item ran on the
  current source (run_batch records copied_source_sha256 per item) under the current harness.
* 15c-H fix round 4 (re-review 3): _env drops every inherited PYTHON*/PYTEST*/HYPOTHESIS*/COV* variable except a
  deliberate pass list, and the binding records every such variable the child receives (child env == bound env);
  drift errors name recoveries the API has; a direct run_batch(config=...) verifies the identity against its
  inventory like run_manifest.

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


def _copy_harness(copy_root: Path, cfg: CRConfig, create: bool = True) -> list[str]:
    """I4: the copy is self-sufficient. If a pythonpath dir of the copy already carries cr_guard.py (a real S1 copy
    has research/s1/s1_tests/cr_guard.py; run_batch has checked it is byte-identical) nothing is added. Otherwise
    the reviewed cr_guard.py ALONE is copied to <copy>/.cr_harness. The worktree s1_tests dir (conftest, helpers,
    unmutated sources reachable through them) is never put on the child's path."""
    if any((Path(copy_root) / r / "cr_guard.py").is_file() for r in cfg.pythonpath_rel):
        return []
    h = Path(copy_root) / ".cr_harness"
    if not create:                                 # fix round 3: predict the entry (binding), copy nothing
        return [str(h.resolve())]
    h.mkdir(exist_ok=True)
    shutil.copy2(HARNESS_DIR / "cr_guard.py", h / "cr_guard.py")
    return [str(h.resolve())]


# fix round 4 (R3-I1): inherited variables with these name prefixes can change a test outcome (PYTHONOPTIMIZE strips
# asserts, PYTEST_PLUGINS / PYTEST_ADDOPTS / PYTHONWARNINGS change the run, HYPOTHESIS_* / COV* change plugins or
# storage). _env drops every inherited one (names compared upper-case: Windows env names are case-insensitive) except
# _ENV_PASS, which is passed deliberately; _env then sets its own PYTHONDONTWRITEBYTECODE and PYTHONPATH. Every
# prefixed variable the child receives is bound (_child_env_binding), so the child env == the bound env for this set.
_ENV_PREFIXES = ("PYTHON", "PYTEST", "HYPOTHESIS", "COV")
_ENV_PASS = ("PYTHONHASHSEED", "PYTHONUTF8", "PYTHONIOENCODING")


def _outcome_var(name: str) -> bool:
    return name.upper().startswith(_ENV_PREFIXES)


def _env(copy_root: Path, cfg: CRConfig, job_dir: Path | None = None, job_id: str | None = None) -> dict:
    env = {k: v for k, v in os.environ.items() if not _outcome_var(k) or k.upper() in _ENV_PASS}
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


def pool_sha256(nodes) -> str:
    """sha256 of the canonical node list (sorted, compact JSON) - the frozen completion pool's identity."""
    return hashlib.sha256(json.dumps(sorted(nodes), separators=(",", ":")).encode("utf-8")).hexdigest()


def load_pool(pool_path: Path) -> list:
    """fix round 1 (ruling 2 / review I1): the frozen full node pool (pool.json), refused unless its node list is
    non-empty, duplicate-free and matches its recorded nodes_sha256."""
    pool_path = Path(pool_path)
    doc = json.loads(pool_path.read_text(encoding="utf-8"))
    nodes = list(doc.get("nodes") or [])
    if not nodes or len(set(nodes)) != len(nodes) or doc.get("nodes_sha256") != pool_sha256(nodes):
        raise CoordError(f"{pool_path.name} does not match its nodes_sha256 (or is empty / has duplicates)")
    return nodes


def shard_nodes(cfg: CRConfig, src_root: Path, name: str = "?") -> list:
    """The exact node list a completion shard's test-command runs: its single ``@argfile`` (relative to the copy
    root, read here from ``src_root``). One source of truth for what the pool check and the run see."""
    files = [str(a)[1:] for a in cfg.guard_args if str(a).startswith("@")]
    if len(files) != 1:
        raise CoordError(f"completion shard {name} has no single @nodes argfile in its test-command")
    return [ln for ln in (Path(src_root) / files[0]).read_text(encoding="utf-8").splitlines() if ln.strip()]


def config_identity(cfg: CRConfig, cr_toml: Path, config_id: str) -> dict:
    """fix round 1 (ruling 4 / review I3): the identity a calibration cap is bound to - config id, module, the
    test-command sha256, the cr.toml path + sha256 (which must render exactly this config) and the harness hashes."""
    import tomllib
    cr_toml = Path(cr_toml)
    doc = tomllib.loads(cr_toml.read_text(encoding="utf-8")).get("cosmic-ray", {})
    if (doc.get("test-command") != test_command(cfg) or doc.get("module-path") != _posix(cfg.module_rel)
            or float(doc.get("timeout", -1)) != float(cfg.timeout_s)):
        raise CoordError(f"{cr_toml.name}: cr.toml does not match the config {config_id}")
    return {"config_id": config_id, "module_rel": _posix(cfg.module_rel),
            "test_command_sha256": hashlib.sha256(test_command(cfg).encode("utf-8")).hexdigest(),
            "cr_toml": str(cr_toml.resolve()), "cr_toml_sha256": _sha(cr_toml), "harness_sha256": harness_hashes()}


def batch_cap(cap_record=None, identity: dict | None = None) -> int:
    """15c-H (ruling 2) + fix round 1 (ruling 4): the batch cap is BUDGETS["batch_max"] (24) unless a calibration
    cap record FILE is given; it is re-verified on every use (read_cap_record: sha256 sidecar, calibration state bytes,
    the bound cr.toml + harness on disk, and the caller's current config identity). A bare dict is refused. The
    derived cap is an efficiency estimate; the HARD session fence in run_batch stays the safety bound either way."""
    if cap_record is None:
        return BUDGETS["batch_max"]
    if not isinstance(cap_record, (str, Path)):
        raise CoordError("cap record must be a recorded file path (derive_cap output), not a bare dict")
    if not identity:
        raise CoordError("a cap record is only usable with the current config identity (config_identity)")
    return int(read_cap_record(cap_record, identity=identity)["derived_cap"])


def plan_batches(ids, size: int = BUDGETS["batch_max"], cap_record=None,
                 identity: dict | None = None) -> list[list[str]]:
    cap = batch_cap(cap_record, identity)
    if not 1 <= size <= cap:
        raise PartitionError(f"batch size {size} exceeds the {cap} cap (or is < 1)")
    ids = list(ids)
    if len(set(ids)) != len(ids):
        raise PartitionError("duplicated ids in the ordered inventory")
    batches = [ids[i:i + size] for i in range(0, len(ids), size)]
    check_partition(ids, batches, cap=cap)
    return batches


def check_partition(ids, batches, cap: int | None = None) -> None:
    flat = [j for b in batches for j in b]
    lost = sorted(set(ids) - set(flat))
    dup = sorted({j for j in flat if flat.count(j) > 1})
    unknown = sorted(set(flat) - set(ids))
    over = [len(b) for b in batches if len(b) > (cap or BUDGETS["batch_max"])]
    if lost or dup or unknown or over:
        raise PartitionError(f"batch partition invalid: lost: {lost}, duplicated: {dup}, unknown: {unknown}, "
                             f"oversized: {over}")


def check_pool_union(pool, shards) -> None:
    """15c-H (ruling 1): completion shards must cover the frozen full intended node pool EXACTLY - no node missing,
    none unknown, none in two shards."""
    flat = [n for s in shards for n in s]
    missing = sorted(set(pool) - set(flat))
    unknown = sorted(set(flat) - set(pool))
    dup = sorted({n for n in flat if flat.count(n) > 1})
    if missing or unknown or dup or len(set(pool)) != len(list(pool)):
        raise PartitionError(f"completion pool union != frozen pool: missing: {missing}, unknown: {unknown}, "
                             f"duplicated: {dup}")


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
    artifact next to its state: the batches in ``work_root``, every completion run under ``work_root``/completion/
    AND every retry session under ``work_root``/retries/
    (R2-M1: a retry's own stop, e.g. cleanup_uncertain, gates the parent work_root too). Each returned state carries
    its directory as ``_root`` (in memory only), which is where resolve_stop must record the resolution."""
    root = Path(work_root)
    paths = (sorted(root.glob("batch_*_state.json")) + sorted(root.glob("retries/*/batch_*_state.json"))
             + sorted(root.glob("completion/*/*/batch_*_state.json")))   # 15c-H: completion attempts gate too
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
    p.parent.mkdir(parents=True, exist_ok=True)              # a fresh session root of a later session (fix round 1)
    _dump(p, {"schema": SCHEMA, "started": now, "session_length_s": BUDGETS["session_length_s"]})
    return now


# 15c-H (ruling 2): measured per-item coordinator I/O outside the Cosmic Ray process (fresh S1 copy, source + harness
# hashing, job dir, state dumps, rmtree, cr.toml + one-item WorkDB + reconcile): max 0.5 s, median 0.16 s over 12 S1
# items (prep tool measure_io.py, 2026-11-16, evidence cr_a3/_prep/measure_io.json). The margin is 30x the measured
# max, for cold caches / AV scanning; it is recorded in every batch state.
IO_MARGIN_S = 15.0


def fence_s(item_outer_s: float | None = None, io_margin_s: float = IO_MARGIN_S) -> float:
    """15c-H (ruling 2) HARD session fence: the REAL maximum remaining one-item path. real_exec's outer
    run_contained deadline (CR timeout + cleanup reserve = 345 s, or the retry 600 + 45) PLUS run_contained's own
    nested cleanup verification (cleanup reserve, 45 s) PLUS the measured I/O margin. A candidate starts only if at
    least this much of the session remains."""
    outer = BUDGETS["cr_timeout_s"] + BUDGETS["cleanup_reserve_s"] if item_outer_s is None else item_outer_s
    return float(outer + BUDGETS["cleanup_reserve_s"] + io_margin_s)


def derive_cap(calibration_state: Path, *, out: Path, identity: dict, min_items: int | None = None,
               item_outer_s: float | None = None, io_margin_s: float = IO_MARGIN_S) -> dict:
    """15c-H (ruling 2) + fix round 1 (ruling 4): from ONE calibration batch state of ONE config (its recorded
    ``config`` must equal ``identity``) with >= BUDGETS["batch_max"] measured items, derive and RECORD the batch cap
    floor((session length - fence) / max measured item). The record binds the config identity and the calibration
    state's path + sha256, gets a sha256 sidecar and is never overwritten. An efficiency estimate only: the fence stays
    the safety bound."""
    out, calibration_state = Path(out), Path(calibration_state)
    if out.exists():
        raise CoordError(f"{out.name} already exists: a cap record is never overwritten")
    s = json.loads(calibration_state.read_text(encoding="utf-8"))
    if not identity or s.get("config") != identity:
        raise CoordError(f"calibration state is from a different config ({(s.get('config') or {}).get('config_id')}"
                         f", not {(identity or {}).get('config_id')})")
    need = BUDGETS["batch_max"] if min_items is None else int(min_items)
    costs = {job: float(sec) for job, sec in (s.get("item_s") or {}).items() if job in s.get("batch", [])}
    if len(costs) < need:
        raise CoordError(f"calibration needs at least {need} measured items, got {len(costs)}")
    fence = fence_s(item_outer_s, io_margin_s)
    worst = max(costs.values())
    cap = max(1, int((BUDGETS["session_length_s"] - fence) // worst)) if worst > 0 else BUDGETS["batch_max"]
    rec = {"schema": SCHEMA, "config": identity,
           "calibration_state": {"path": str(calibration_state.resolve()), "sha256": _sha(calibration_state),
                                 "batch_id": s.get("batch_id")},
           "measured_items": len(costs), "max_item_s": worst,
           "median_item_s": sorted(costs.values())[len(costs) // 2], "fence_s": fence, "io_margin_s": io_margin_s,
           "session_length_s": BUDGETS["session_length_s"], "derived_cap": cap,
           "rule": "floor((session_length_s - fence_s) / max_item_s) from one calibration state of this config; "
                   "efficiency estimate, the fence is the bound"}
    _dump(out, rec)
    out.with_name(out.name + ".sha256").write_bytes(f"{_sha(out)} *{out.name}\n".encode("utf-8"))
    return rec


def read_cap_record(path: Path, identity: dict | None = None) -> dict:
    """A cap record, re-verified: its sha256 sidecar, the calibration state bytes it was derived from, the bound
    cr.toml and harness files as they are on disk now, and (when given) the caller's current config identity."""
    path = Path(path)
    side = path.with_name(path.name + ".sha256")
    if not side.is_file() or side.read_text(encoding="utf-8").split()[0] != _sha(path):
        raise CoordError(f"{path.name} does not match its sha256 sidecar")
    rec = json.loads(path.read_text(encoding="utf-8"))
    cal = rec.get("calibration_state") or {}
    if not cal.get("path") or not Path(cal["path"]).is_file() or _sha(Path(cal["path"])) != cal.get("sha256"):
        raise CoordError(f"calibration state {cal.get('path')} changed since the cap was derived")
    cfg = rec.get("config") or {}
    if (not cfg.get("cr_toml") or not Path(cfg["cr_toml"]).is_file()
            or _sha(Path(cfg["cr_toml"])) != cfg.get("cr_toml_sha256")
            or cfg.get("harness_sha256") != harness_hashes()):
        raise CoordError(f"config files of {cfg.get('config_id')} changed since the cap was derived")
    if identity is not None and cfg != identity:
        raise CoordError(f"cap record is bound to config {cfg.get('config_id')}, not {identity.get('config_id')}")
    return rec


def _screen_labels(job: str, work_root: Path) -> list:
    out = []
    for p in sorted(Path(work_root).glob("batch_*_state.json")):
        labels = json.loads(p.read_text(encoding="utf-8")).get("labels", {})
        if job in labels:
            out.append(labels[job])
    return out


def _rel_entry(path: str, root: Path) -> str:
    try:
        rel = Path(path).resolve().relative_to(Path(root).resolve())
    except ValueError:
        return _posix(path)
    return "." if str(rel) in ("", ".") else _posix(rel)


def _child_env_binding(root: Path, cfg: CRConfig) -> dict:
    """fix round 3 (X24) + fix round 4 (R3-I1): EVERY PYTHON*/PYTEST*/HYPOTHESIS*/COV* variable the CR child of a
    copy at ``root`` actually gets from _env (after its scrub, including its overrides PYTHONDONTWRITEBYTECODE=1 and
    PYTHONPATH), plus TZ - not the parent's os.environ. PYTHONPATH is recorded relative to the copy root, with the
    .cr_harness entry real_exec's _env would add predicted rather than created.

    Deliberately NOT bound (fix round 4 ruling 1): the per-attempt variables _env sets from the job dir
    (CR_GUARD_JOB_DIR, CR_GUARD_JOB_ID, S1_HYPOTHESIS_ROOT = <job dir>/hypothesis) and the ones cr_guard sets for its
    pytest child (CR_GUARD_NODES_OUT / _ATTEMPT / _TARGETS, its own per-attempt S1_HYPOTHESIS_ROOT). _env always pops
    or overwrites them, so no parent value reaches the child; their values are absolute per-attempt paths whose only
    content is the attempt layout, which cr_coord.py / cr_guard.py (both hash-bound) fix. Path-relative they would
    be constants that bind nothing the harness hashes do not already bind."""
    env = _env(root, cfg)
    paths = [x for x in env.get("PYTHONPATH", "").split(os.pathsep) if x] + _copy_harness(root, cfg, create=False)
    out = {k: v for k, v in env.items() if _outcome_var(k) and k.upper() != "PYTHONPATH"}
    out["TZ"] = env.get("TZ")
    out["PYTHONPATH"] = [_rel_entry(x, root) for x in paths]
    return out


def _in_copy(rel: str, copy_paths) -> bool:
    rel = _posix(rel)
    return any(rel == c or rel.startswith(c.rstrip("/") + "/") for c in map(_posix, copy_paths))


def _attempt_binding(cfg: CRConfig, root: Path, nodes: list, copy_paths) -> dict:
    """Codex early number check (e) + fix round 3 (X23/X24): the identity of what a completion attempt runs - the
    executable, test-command, exact node set, control file, target source, harness + helper hashes (conftest.py /
    *helpers*.py on the pythonpath dirs) and the child's allowlisted env (_child_env_binding). Computed from ``root``
    restricted to ``copy_paths``: at EXECUTION time ``root`` is the attempt's disposable copy (what the child sees;
    run_batch persists it before the exec seam runs); for a reuse/resume check ``root`` is the source tree the next
    copy would be made from, so an unchanged context reproduces the persisted binding exactly."""
    root = Path(root)
    args = [str(a) for a in cfg.guard_args]
    ctl = args[args.index("--control") + 1] if "--control" in args[:-1] else None
    helpers = {}
    for rel in cfg.pythonpath_rel:
        d = root / rel
        for p in sorted(list(d.glob("conftest.py")) + list(d.glob("*helpers*.py"))):
            r = _posix(p.relative_to(root))
            if _in_copy(r, copy_paths):
                helpers[r] = _sha(p)
    src_rel = _posix(cfg.module_rel)
    src = root / src_rel
    return {"python": str(cfg.python),
            "test_command_sha256": hashlib.sha256(test_command(cfg).encode("utf-8")).hexdigest(),
            "node_set_sha256": pool_sha256(nodes), "nodes": len(nodes),
            "control_sha256": (_sha(root / ctl) if ctl and _in_copy(ctl, copy_paths) and (root / ctl).is_file()
                               else None),
            "source_sha256": _sha(src) if _in_copy(src_rel, copy_paths) and src.is_file() else None,
            "harness_sha256": harness_hashes(), "helpers_sha256": helpers, "pythonpath_rel": list(cfg.pythonpath_rel),
            "env": _child_env_binding(root, cfg)}


def _binding_drift(old: dict, new: dict) -> list:
    """Field-by-field differences of two bindings (env compared per variable, as env.<NAME>)."""
    out = []
    for k in sorted(set(old) | set(new)):
        if k == "env":
            oe, ne = old.get("env") or {}, new.get("env") or {}
            out += [f"env.{v}" for v in sorted(set(oe) | set(ne)) if oe.get(v) != ne.get(v)]
        elif old.get(k) != new.get(k):
            out.append(k)
    return out


def _check_screening_context(job: str, item: dict, work_root: Path, src_root: Path, source_sha256) -> None:
    """fix round 3 (X23, screening path): the screening label is consumed only if the screening attempt ran on the
    module source the completion will run on (and on the explicit ``source_sha256``, when given), under the current
    harness. run_batch records the copied source sha per executed item; batch states are write-once."""
    mod_rel = _posix(item["module_path"])
    cur = _sha(Path(src_root) / mod_rel)
    want = (source_sha256 or {}).get(mod_rel)
    for p in sorted(Path(work_root).glob("batch_*_state.json")):
        s = json.loads(p.read_text(encoding="utf-8"))
        if job not in s.get("labels", {}):
            continue
        ran = (s.get("copied_source_sha256") or {}).get(job)
        if ran is None or ran != cur or (want is not None and ran != want):
            raise CoordError(f"screening of {job} ({p.name}) ran on source_sha256 {ran}; the current source is {cur}"
                             + (f" and the expected source_sha256 is {want}" if want else "")
                             + ": the screening label is not reused")
        if s.get("harness_sha256") != harness_hashes():
            raise CoordError(f"screening of {job} ({p.name}) ran under another harness than the current one: the "
                             f"screening label is not reused")


def _check_cached_attempts(job: str, name: str, sroot: Path, planned: dict, want_source) -> None:
    """fix round 3 (X23): every existing attempt state of a completion shard is compared, field by field, with the
    binding the current context would give - an executed attempt's persisted execution-time binding, a refused
    attempt's persisted planned binding - and with the explicit expected source. Any drift raises (naming the fields):
    the cached result is not merged and nothing is relabelled. fix round 4 (R3-N2): the errors name the recoveries the
    API has - restore the bound inputs (the attempt is then reused), or screen the job again in a fresh work_root
    (run_batch / run_manifest) and complete it there; run_completion's completion root is fixed per work_root."""
    for st in _attempt_states(sroot, name):
        s = json.loads(st.read_text(encoding="utf-8"))
        executed = job in s.get("labels", {})
        persisted = (s.get("bindings") or {}).get(job) if executed else s.get("planned_binding")
        what = "executed" if executed else "planned"
        if not persisted:
            raise CoordError(f"completion attempt {name} ({s.get('batch_id')}) has no persisted {what} binding: "
                             f"it is not reused - {_fresh_screen(job)}")
        drift = _binding_drift(persisted, planned)
        if want_source is not None and persisted.get("source_sha256") != want_source:
            drift.append("source_sha256(expected)")
        if drift:
            raise CoordError(f"completion attempt {name} ({s.get('batch_id')}) {what} binding drift in {drift}: the "
                             f"cached result is not merged and nothing is relabelled - restore the bound inputs, or "
                             f"{_fresh_screen(job)}")


def _fresh_screen(job: str) -> str:
    return f"screen {job} again in a fresh work_root and complete it there"


def _attempt_states(sroot: Path, name: str) -> list:
    """Every attempt state of one completion shard, in order: batch ids <name>, <name>-a1, <name>-a2, ..."""
    out, k = [], 0
    while True:
        p = _state_path(sroot, name if k == 0 else f"{name}-a{k}")
        if not p.is_file():
            return out
        out.append(p)
        k += 1


def run_completion(job: str, items_by_id: dict, shards, *, pool_path: Path, src_root: Path, work_root: Path,
                   exec_factory=None, session_root: Path | None = None, source_sha256: dict | None = None,
                   clock=time.monotonic, io_margin_s: float = IO_MARGIN_S) -> dict:
    """15c-H (ruling 1) + fix round 1 (rulings 1-3): re-run a screening SURVIVOR against every completion shard, in
    order, each as its own one-item guard-verified attempt (run_batch) under ``work_root``/completion/<job>/<shard>/,
    on the PARENT session clock (``session_root``, default ``work_root``) and the same HARD fence.

    * The declared shards' node sets (each config's single @argfile, read from ``src_root``) must cover the frozen
      ``pool_path`` (pool.json, sha-verified) EXACTLY; zero shards or a subset is refused before anything runs.
    * Only a GUARD-CLEAN kill (cr_reconcile.attempt_clean) stops the remaining shards.
    * Any stop leaves the remaining shards pending and blocks every batch until resolve_stop.
    * A shard the fence refused (state without the job started) is pending; once that stop is resolved it is re-run
      in a later session as a new attempt (<shard>-a<k>), the refused state is kept. A shard that did run is never
      re-run.
    * The merge (cr_reconcile.merge_attempts: killed / unresolved / deferred / survived), every attempt with its
      binding, and the pool sha256 are written to a new completion_record*.json.

    ``shards``: [{"name", "cfg": CRConfig, "copy_paths"}]."""
    exec_factory = exec_factory or real_exec
    if job not in items_by_id:
        raise CoordError(f"unknown job {job} (not in the inventory)")
    labels = _screen_labels(job, work_root)
    if labels != ["survived"]:
        raise CoordError(f"{job} is not a screening survivor: labels {labels}")
    pool = load_pool(pool_path)
    names = [s["name"] for s in shards]
    if len(set(names)) != len(names):
        raise CoordError(f"duplicate completion shard names {names}")
    node_sets = [shard_nodes(s["cfg"], src_root, s["name"]) for s in shards]
    for spec, nodes in zip(shards, node_sets):
        args = [str(a) for a in spec["cfg"].guard_args]
        ctl = Path(src_root) / args[args.index("--control") + 1] if "--control" in args[:-1] else None
        try:
            control = set(json.loads(ctl.read_text(encoding="utf-8"))["nodes"]) if ctl else None
        except (OSError, ValueError, KeyError, TypeError):
            control = None
        if control != set(nodes):
            raise CoordError(f"completion shard {spec['name']}: control node set != its @argfile node set "
                             f"({ctl}); the guard would run the control, not the pool-checked list")
    try:
        if not shards:
            raise PartitionError("no completion shards declared")
        check_pool_union(pool, node_sets)
    except PartitionError as exc:
        raise CoordError(f"completion shards do not cover the frozen pool {Path(pool_path).name}: {exc}") from None
    blocked = unresolved_stops(work_root)
    if blocked:
        b = blocked[0]
        raise CoordError(f"{describe_stop(b)} and is unresolved; record a resolution with "
                         f"resolve_stop({b['_root']!r}, {b['batch_id']!r}, ...) before completing {job}")
    _check_screening_context(job, items_by_id[job], work_root, src_root, source_sha256)
    croot = Path(work_root) / "completion" / job
    planned = {spec["name"]: _attempt_binding(spec["cfg"], src_root, nodes, spec["copy_paths"])
               for spec, nodes in zip(shards, node_sets)}
    mod_rel = _posix(items_by_id[job]["module_path"])
    for spec in shards:                                     # fix round 3 (X23): never reuse under drifted inputs
        _check_cached_attempts(job, spec["name"], croot / spec["name"], planned[spec["name"]],
                               (source_sha256 or {}).get(mod_rel))
    attempts, refused, pending, not_run = [], [], [], []
    for n, (spec, nodes) in enumerate(zip(shards, node_sets)):
        name, cfg = spec["name"], spec["cfg"]
        if attempts and attempts[-1]["label"] == "killed" and cr_reconcile.attempt_clean(attempts[-1]):
            not_run = names[n:]
            break
        sroot = croot / name                                # one work dir per shard (jobs/<job> is per root)
        states = _attempt_states(sroot, name)
        latest = json.loads(states[-1].read_text(encoding="utf-8")) if states else None
        if latest is None or (job not in latest.get("labels", {})
                              and _resolution_path(sroot, latest["batch_id"]).exists()):
            bid = name if not states else f"{name}-a{len(states)}"
            run_batch([job], items_by_id, batch_id=bid, src_root=src_root, copy_paths=spec["copy_paths"],
                      work_root=sroot, exec_seam=exec_factory(cfg), source_sha256=source_sha256, clock=clock,
                      session_root=Path(session_root or work_root), io_margin_s=io_margin_s,
                      item_outer_s=cfg.timeout_s + BUDGETS["cleanup_reserve_s"],
                      binding_fn=lambda item, copy_root, job_dir, _c=cfg, _n=nodes, _p=spec["copy_paths"]:
                      _attempt_binding(_c, copy_root, _n, _p),
                      extra={"completion_of": job, "shard": name, "test_command": test_command(cfg),
                             "planned_binding": planned[name]})
            states = _attempt_states(sroot, name)
            ran = json.loads(states[-1].read_text(encoding="utf-8"))
            if job in ran.get("labels", {}):
                drift = _binding_drift(planned[name], (ran.get("bindings") or {}).get(job) or {})
                if drift:
                    raise CoordError(f"completion attempt {name} ({ran['batch_id']}): the executed binding differs "
                                     f"from the planned one in {drift}; it is not merged - {_fresh_screen(job)}")
        state = states[-1]
        s = json.loads(state.read_text(encoding="utf-8"))
        if job not in s.get("labels", {}):                  # refused before starting (fence / clock): pending
            refused.append({"shard": name, "attempt_batch": s["batch_id"], "stop_reason": s.get("stop_reason"),
                            "state_sha256": _sha(state)})
            pending = names[n:]
            break
        res = s["results"].get(job, {})
        bound = (s.get("bindings") or {}).get(job) or {}      # the persisted execution-time binding, never recomputed
        attempts.append({"shard": name, "attempt_batch": s["batch_id"], "label": s["labels"][job],
                         "guard_status": res.get("guard_status"), "exec_status": res.get("exec_status"),
                         "cleanup_verified": res.get("cleanup_verified"), "stopped": bool(s.get("stopped")),
                         "stop_reason": s.get("stop_reason"), "state_sha256": _sha(state),
                         "test_command_sha256": bound.get("test_command_sha256"), "binding": bound,
                         "containment": {"exec_status": res.get("exec_status"),
                                         "cleanup_verified": res.get("cleanup_verified")}})
        if s.get("stopped") and not _resolution_path(sroot, s["batch_id"]).exists():
            pending = names[n + 1:]
            break
    merged = cr_reconcile.merge_attempts("survived", attempts, names)
    rec = {"schema": SCHEMA, "job_id": job, "screening_label": "survived", "required": names,
           "pool": str(Path(pool_path)), "pool_sha256": pool_sha256(pool), "attempts": attempts, "refused": refused,
           "not_run": not_run, "pending_shards": pending, **merged}
    croot.mkdir(parents=True, exist_ok=True)
    out, k = croot / "completion_record.json", 1
    while out.exists():
        out, k = croot / f"completion_record_{k}.json", k + 1
    _dump(out, rec)
    return rec


def run_batch(batch, items_by_id: dict, *, batch_id: str, src_root: Path, copy_paths, work_root: Path, exec_seam,
              source_sha256: dict | None = None, clock=time.monotonic, extra: dict | None = None,
              session_root: Path | None = None, io_margin_s: float = IO_MARGIN_S, item_outer_s: float | None = None,
              cap_record=None, config: dict | None = None, binding_fn=None,
              inventory_path: Path | None = None) -> dict:
    """Execute a batch strictly sequentially, one WorkItem per fresh disposable copy. Stops (quarantining the copy)
    on the first timeout / cleanup uncertainty / drift / unrestored source / exec exception; pending IDs are kept.

    Fix round 1 (I2): the state lives in ``batch_<batch_id>_state.json`` and is never overwritten; a batch refuses
    to start while any earlier batch in the same work_root is STOPPED without a recorded resolution (resolve_stop).
    ``source_sha256`` ({module_rel: sha256}, normally from inventory.json) is what each copy must match.

    15c-H (ruling 2): ``clock`` is MONOTONIC and the session clock lives in ``session_root`` (default ``work_root``),
    so nested retry/completion runs share their parent session's clock. HARD fence: a candidate starts only if the
    remaining session time is >= fence_s(item_outer_s, io_margin_s); a clock reading before the session start
    (e.g. after a reboot) refuses with session_clock_invalid. Each item's measured duration is kept in
    ``item_s`` (calibration input). More than BUDGETS["batch_max"] items needs a calibration ``cap_record``.

    fix round 4 (R3-N3): a ``config`` identity is accepted only with the ``inventory_path`` it is verified against,
    exactly as run_manifest verifies it (_check_identity: the inventory's test-command sha256)."""
    batch = list(batch)
    if not _BATCH_ID.match(str(batch_id)):
        raise CoordError(f"invalid batch id {batch_id!r}")
    if config is not None:
        if inventory_path is None:
            raise CoordError(f"identity {config.get('config_id')} is only accepted with the inventory it is verified "
                             f"against (inventory_path)")
        _check_identity(config, json.loads(Path(inventory_path).read_text(encoding="utf-8")))
    cap = batch_cap(cap_record, config)
    if len(batch) > cap or len(set(batch)) != len(batch):
        raise PartitionError(f"batch of {len(batch)} items is over the {cap} cap or has duplicates")
    fence = fence_s(item_outer_s, io_margin_s)
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
    session_root = Path(session_root) if session_root is not None else work_root
    started = _session_start(session_root, clock)
    copies, jobs, quarantine = work_root / "copies", work_root / "jobs", work_root / "quarantine"
    for d in (copies, jobs, quarantine):
        d.mkdir(parents=True, exist_ok=True)
    st = {"schema": SCHEMA, "batch_id": batch_id, "batch": batch, "done": [], "quarantined": [],
          "pending": list(batch), "stopped": False, "stop_reason": None, "labels": {}, "results": {},
          "session_started": started, "session_root": str(session_root), "fence_s": fence,
          "io_margin_s": io_margin_s, "batch_cap": cap, "item_s": {}, "config": config,
          "copied_source_sha256": {}, "bindings": {},
          "harness_sha256": harness_hashes(),
          **(extra or {})}

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
        t_item = clock()
        if t_item < started:
            st.update(stopped=True, stop_reason=f"session_clock_invalid: {job}")
            _dump(state_path, st)
            break
        if BUDGETS["session_length_s"] - (t_item - started) < fence:
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
        st["copied_source_sha256"][job] = copied[mod_rel]          # fix round 3: what this item actually ran on
        try:
            if binding_fn is not None:                              # fix round 3: bound at execution time, persisted
                st["bindings"][job] = binding_fn(item, copy_root, job_dir)
            _dump(state_path, st)
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
            st["item_s"][job] = round(clock() - t_item, 3)
            stop(job, reason, copy_root)
            break
        shutil.rmtree(copy_root)                        # disposable: evidence lives in jobs/<id>/, not in the copy
        st["item_s"][job] = round(clock() - t_item, 3)  # measured whole-item cost (calibration input)
        st["done"].append(job)
        st["pending"].remove(job)
        _dump(state_path, st)
    return st


def run_manifest(manifest: Path, inventory_path: Path, *, src_root: Path, copy_paths, work_root: Path, exec_seam,
                 clock=time.monotonic, session_root: Path | None = None, cap_record=None,
                 config: dict | None = None) -> dict:
    """Run one batch manifest against the EXACT inventory bytes it was written for (I5). 15c-H: a manifest of more
    than BUDGETS["batch_max"] items needs the calibration ``cap_record`` (read_cap_record)."""
    man = json.loads(Path(manifest).read_text(encoding="utf-8"))
    inv_sha = _sha(inventory_path)
    if inv_sha != man["inventory_sha256"]:
        raise CoordError(f"inventory sha256 {inv_sha} does not match the manifest ({man['inventory_sha256']})")
    inv = json.loads(Path(inventory_path).read_text(encoding="utf-8"))
    items_by_id = {i["job_id"]: i for i in inv["items"]}
    unknown = sorted(set(man["items"]) - set(items_by_id))
    if unknown:
        raise CoordError(f"manifest items not in the inventory: {unknown}")
    if config is not None:
        _check_identity(config, inv)
    return run_batch(man["items"], items_by_id, batch_id=f"{int(man['batch_index']):03d}", src_root=src_root,
                     copy_paths=copy_paths, work_root=work_root, exec_seam=exec_seam,
                     source_sha256={inv["module_rel"]: inv["source_sha256"]}, clock=clock,
                     session_root=session_root, cap_record=cap_record, config=config,
                     inventory_path=inventory_path,
                     extra={"manifest": str(manifest), "manifest_sha256": _sha(manifest),
                            "inventory_sha256": inv_sha})


def _check_identity(config: dict, inv: dict) -> None:
    """R1-N3 / fix round 4 (R3-N3): a config identity is used only for the inventory whose test-command it hashes."""
    tc = inv.get("test_command")
    if not tc or hashlib.sha256(tc.encode("utf-8")).hexdigest() != config.get("test_command_sha256"):
        raise CoordError(f"identity {config.get('config_id')}: not this inventory's test_command")


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


def _in_completion_area(work_root: Path) -> bool:
    """True for <root>/completion, <root>/completion/<job> and <root>/completion/<job>/<shard> where <root> is a
    coordinator work root (it has session.json or batch_*_state.json), or for any dir whose batch states record
    ``completion_of``. A screening root that merely sits under a directory named "completion" is not one."""
    p = Path(work_root).resolve()
    for s in p.glob("batch_*_state.json"):
        try:
            if json.loads(s.read_text(encoding="utf-8")).get("completion_of"):
                return True
        except ValueError:
            return True
    for up in (p, p.parent, p.parent.parent):
        if up.name == "completion":
            root = up.parent
            if (root / "session.json").is_file() or any(root.glob("batch_*_state.json")):
                return True
    return False


def run_retry(job: str, items_by_id: dict, cfg: CRConfig, *, src_root: Path, copy_paths, work_root: Path,
              exec_factory=real_exec, source_sha256: dict | None = None, clock=time.monotonic,
              session_root: Path | None = None) -> dict:
    """The ONE retry (R4/R5): a separately recorded one-item session under ``work_root``/retries/<job> with the
    retry budgets (CR 600 s, inner 540 s), only for an eligible timeout (retry_eligibility; the basis is recorded).
    The initial labels are copied from every batch state that holds the job (never modified); a second retry of the
    same job is refused. 15c-H: the retry runs on the PARENT session clock (``session_root``, default
    ``work_root``) with the retry item path (600 + 45 s) in its HARD fence."""
    if _in_completion_area(work_root):
        raise CoordError(f"run_retry refuses a completion-shard directory ({work_root}): a completion timeout stays "
                         f"unresolved (retry allowance for completion attempts is not agreed)")
    rroot = Path(work_root) / "retries" / job
    if rroot.exists():
        raise CoordError(f"{job} was already retried ({rroot}); one retry only")
    initial, basis = retry_eligibility(job, items_by_id, work_root)
    rcfg = retry_config(cfg)
    return run_batch([job], items_by_id, batch_id="retry", src_root=src_root, copy_paths=copy_paths,
                     work_root=rroot, exec_seam=exec_factory(rcfg), source_sha256=source_sha256, clock=clock,
                     session_root=Path(session_root or work_root),
                     item_outer_s=rcfg.timeout_s + BUDGETS["cleanup_reserve_s"],
                     extra={"retry_of": job, "initial_labels": initial, "eligibility": basis,
                            "retry_budgets": {"cr_timeout_s": rcfg.timeout_s,
                                              "guard_deadline_s": rcfg.guard_deadline_s}})
