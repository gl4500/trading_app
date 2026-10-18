"""S1-EPOCH (§12): semantic receipt (compared at every seal), process identity and the app's own crash.log
[PROCESS START] restart record (observed minimum; gaps reported). Read-only: git, files, the OS process table.

Task 12 (controller-added), Addendum 1 A1: the receipt is {"fingerprint": ..., "provenance": ...}.
- FINGERPRINT (compared for equality at every pre-stop seal): the complete MR dependency closure (membership +
  sha256; a missing root or in-repo member is a ReceiptError, never a shorter list); the registered resources of any
  file type (presence/absence + sha256, independent of git); the effective-config evidence under the registered
  EVIDENCE_CONTRACT (.env values of the MR-relevant keys hashed, code defaults bound through config.py in the
  closure, secret-named fields by name + presence + keyed HMAC-SHA256, the HMAC key's identity); the backend's
  registered runtime (Python version and package versions, including the launcher's site-packages); the contract's
  own hash.
- PROVENANCE (recorded, never compared): live checkout HEAD, the dirty list, transient files (SQLite sidecars, logs,
  caches) and transport/observation-only settings (HOST/PORT).
Disclosed limitations: a parsed .env subset and the launcher files do not prove the backend process's effective
configuration; the AST closure is a file list, not proof of runtime loading (dynamic imports); the operator's
binding/continuity attestations stay explicit. A missing REQUIRED input fails explicitly (no silent empty values)."""
import ast
import copy
import hashlib
import hmac
import json
import os
import re
import subprocess
from pathlib import Path

import s1_common as c

MR_ROOTS = ["agents/mean_reversion_agent.py", "agents/base_agent.py", "trading/portfolio.py",
            "trading/risk_manager.py", "loops/trading_loop.py", "lifespan.py", "database.py", "config.py",
            "logging_setup.py"]
SECRET = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD)", re.I)
START_LINE = re.compile(r"^(\S+ \S+) \[PROCESS START\] pid=(\d+)")
UNSET = "<unset>"
UNSET_MARK = "<unset: code default>"   # A1.1: the key is absent from .env, so config.py's default (closure) applies
ABSENT = "absent"
# A1.1: the HMAC key lives outside s1_out and the repo; created once (os.urandom) when absent; never rotated by S1.
HMAC_KEY = Path("C:/Users/gl450/.coordination/trading_app/s1_receipt_hmac.key")
GIT_TIMEOUT_S = 120

# A1.1: the registered resource list and evidence contract - ONE named, reviewable structure (its sha256 is in every
# fingerprint). Paths are relative to the live checkout. Resources are bound by presence/absence and sha256, of any
# file type, independent of git tracking. The launchers are the files that start the backend process (and set its
# environment, e.g. PYTHONPATH=site-packages); which one the operator uses is attested, all are bound.
EVIDENCE_CONTRACT = {
    "version": 1,
    "closure_roots": MR_ROOTS,
    "resources": [
        {"path": "start_backend.ps1", "role": "launcher", "required": False},
        {"path": "scripts/start_backend.bat", "role": "launcher", "required": False},
        {"path": "scripts/start.bat", "role": "launcher", "required": False},
        {"path": "scripts/launcher.py", "role": "launcher", "required": False},
        {"path": "launcher_gui.pyw", "role": "launcher", "required": False},
        {"path": "scripts/install_services.bat", "role": "launcher", "required": False},
    ],
    "config": {"env_file": ".env", "env_required": True,
               "code_defaults": "backend/config.py, bound as a closure member"},
    "runtime": {"python": "runtime/python/python.exe", "site_packages": "site-packages", "required": True},
    "secret_pattern": SECRET.pattern,
    "transport_only_keys": ["HOST", "PORT"],
    "transient_suffixes": ["-journal", "-wal", "-shm", ".log", ".pyc", ".tmp"],
}


def contract(*, env_required=None, runtime_required=None, resources=None) -> dict:
    """A copy of EVIDENCE_CONTRACT; the overrides are the reviewed alternate arrangements a test or a re-registration
    may declare explicitly (never applied silently)."""
    ct = copy.deepcopy(EVIDENCE_CONTRACT)
    if env_required is not None:
        ct["config"]["env_required"] = env_required
    if runtime_required is not None:
        ct["runtime"]["required"] = runtime_required
    if resources is not None:
        ct["resources"] = copy.deepcopy(resources)
    return ct


def key_id(key: bytes) -> str:
    """A1.1: the HMAC key's identity (bound, so that key loss or rotation shows as a change)."""
    return hashlib.sha256(b"s1-receipt-hmac-key-id\0" + key).hexdigest()


def load_or_create_key(path=None) -> bytes:
    """The HMAC key at `path` (default HMAC_KEY), created once with os.urandom(32) when absent (exclusive create)."""
    p = Path(HMAC_KEY if path is None else path)
    if not p.exists():
        try:                                               # fix round 3 (C-1): atomic, never a partial key
            c.publish_exclusive(p, os.urandom(32))
        except FileExistsError:
            pass
    try:
        key = p.read_bytes()
    except OSError as e:
        raise ReceiptError(f"HMAC key unreadable ({type(e).__name__})", terminal=False) from None
    if len(key) < 32:
        raise ReceiptError("HMAC key file shorter than 32 bytes", terminal=False)
    return key


class ReceiptError(Exception):
    """Task 12 (A1/A9): the receipt could not be produced. `terminal` = an established violation (a registered
    required input or closure member is missing: a semantic change once registered, A9.2) vs a transient
    unavailable observation (a failed attempt). Messages name inputs only, never values."""

    def __init__(self, msg: str, terminal: bool = True):
        super().__init__(msg)
        self.terminal = terminal


def _module_file(backend: Path, parts):
    if not parts:
        return None
    p = backend.joinpath(*parts)
    for cand in (p.with_suffix(".py"), p / "__init__.py"):
        if cand.exists():
            return cand
    if parts[0] == "backend":
        return _module_file(backend, parts[1:])
    return None


def _ancestor_inits(backend: Path, f: Path) -> list:
    out, d = [], f.parent
    while d != backend and backend in d.parents:
        if (d / "__init__.py").exists():
            out.append(d / "__init__.py")
        d = d.parent
    return out


def _in_repo(backend: Path, parts) -> bool:
    """The import names an in-repo module or package (backend/<first>.py, or a backend/<first>/ directory)."""
    if parts and parts[0] == "backend":
        parts = parts[1:]
    return bool(parts) and ((backend / f"{parts[0]}.py").exists() or (backend / parts[0]).is_dir())


def _namespace_dir(backend: Path, parts) -> bool:
    if parts and parts[0] == "backend":
        parts = parts[1:]
    d = backend.joinpath(*parts) if parts else None
    return d is not None and d.is_dir() and not (d / "__init__.py").exists()


def _imported_modules(backend: Path, f: Path, tree) -> list:
    """Files of every in-repo module (and `from pkg import mod` submodule) that tree imports. Task 12 (A1.1): an
    in-repo import that resolves to no file (a deleted member, a name missing from a namespace package) raises
    ReceiptError (terminal): the closure is never silently shorter."""
    pkg = list(f.parent.relative_to(backend).parts)
    rel = f.relative_to(backend).as_posix()
    found, missing = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                parts = a.name.split(".")
                m = _module_file(backend, parts)
                if m is not None:
                    found.append(m)
                elif _in_repo(backend, parts) and not _namespace_dir(backend, parts):
                    missing.append(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if node.level - 1 > len(pkg):
                    raise ValueError(f"relative import above backend/ in {rel}")
                base = pkg[:len(pkg) - (node.level - 1)]
            else:
                base = []
            mod = base + (node.module.split(".") if node.module else [])
            in_repo = bool(node.level) or _in_repo(backend, mod)
            m = _module_file(backend, mod)
            if m is not None:
                found.append(m)
            namespace = _namespace_dir(backend, mod) or (not mod and bool(node.level))
            if in_repo and m is None and not namespace:
                missing.append(".".join(mod) or ".")
            for a in node.names:
                if a.name == "*":
                    continue
                sm = _module_file(backend, mod + [a.name])
                if sm is not None:
                    found.append(sm)
                elif in_repo and namespace:                # a namespace package has only submodules
                    missing.append(".".join(mod + [a.name]))
    if missing:
        raise ReceiptError(f"closure member(s) {sorted(set(missing))} imported by {rel} missing", terminal=True)
    return found


def _parse(f: Path):
    """Task 12 fix round 1 (I-1): a registered closure member that cannot be read or parsed (a merge conflict, a
    half-written save, a non-UTF-8 file) is an established change of a fingerprint item - a TERMINAL ReceiptError,
    never a transient foreign exception that restoring the file would erase."""
    parts = Path(f).parts
    rel = "/".join(parts[parts.index("backend") + 1:]) if "backend" in parts else Path(f).name
    try:
        return ast.parse(Path(f).read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, ValueError) as e:
        raise ReceiptError(f"closure member {rel} unparseable ({type(e).__name__}): a registered member changed",
                           terminal=True) from None


def closure(backend: Path, roots) -> list:
    missing = [r for r in roots if not (backend / r).exists()]
    if missing:
        raise ValueError(f"closure root(s) do not exist: {missing}")          # a ReceiptError in semantic_receipt
    seen, todo = set(), [backend / r for r in roots]
    while todo:
        f = todo.pop()
        rel = f.relative_to(backend).as_posix()
        if rel in seen:
            continue
        seen.add(rel)
        todo.extend(_ancestor_inits(backend, f))
        todo.extend(_imported_modules(backend, f, _parse(f)))
    return sorted(seen)


def _is_environ(n) -> bool:
    return (isinstance(n, ast.Attribute) and n.attr == "environ") or (isinstance(n, ast.Name) and n.id == "environ")


def _env_keys(tree) -> set:
    """Literal env keys read via os.getenv(K), os.environ.get(K) or os.environ[K] anywhere under tree."""
    keys = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) \
                and isinstance(node.args[0].value, str):
            fn = node.func
            if (isinstance(fn, ast.Attribute) and fn.attr == "getenv") \
                    or (isinstance(fn, ast.Name) and fn.id == "getenv") \
                    or (isinstance(fn, ast.Attribute) and fn.attr == "get" and _is_environ(fn.value)):
                keys.add(node.args[0].value)
        elif isinstance(node, ast.Subscript) and _is_environ(node.value) \
                and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            keys.add(node.slice.value)
    return keys


def _config_names_used(tree) -> set:
    """Config attribute names read as config.NAME, config.config.NAME or through an alias of the config object."""
    aliases = {"config"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module in ("config", "backend.config"):
            aliases.update(a.asname or a.name for a in node.names if a.name == "config")
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            v = node.value
            if (isinstance(v, ast.Name) and v.id in aliases) or (isinstance(v, ast.Attribute) and v.attr == "config"):
                names.add(node.attr)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module in ("config", "backend.config"):
            names.update(a.name for a in node.names)
    return names


def _config_name_keys(config_py: Path) -> dict:
    """config.py assignment target -> env keys read in its right-hand side (module level and class bodies)."""
    out = {}

    def scan(body):
        for node in body:
            if isinstance(node, ast.ClassDef):
                scan(node.body)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)) and getattr(node, "value", None) is not None:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                ks = _env_keys(node.value)
                for t in targets:
                    if isinstance(t, ast.Name):
                        out.setdefault(t.id, set()).update(ks)

    scan(_parse(config_py).body)
    return out


def _mr_config_keys(backend: Path, files, *, include_secrets: bool = False) -> list:
    """MR-relevant env keys (read by a closure file, or by config.py for a name a closure file uses). Task 12 (A1.1):
    with include_secrets the secret-named keys are included too (they are bound by HMAC, not omitted)."""
    keys, used = set(), set()
    for rel in files:
        tree = _parse(backend / rel)
        used |= _config_names_used(tree)
        if rel != "config.py":
            keys |= _env_keys(tree)
    if (backend / "config.py").exists():
        mapping = _config_name_keys(backend / "config.py")
        for n in used:
            keys |= mapping.get(n, set())
    return sorted(k for k in keys if include_secrets or not SECRET.search(k))


def _env(env_file: Path) -> dict:
    out = {}
    if env_file and Path(env_file).exists():
        for line in Path(env_file).read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


GIT = ("git", "--no-optional-locks")      # Task 11 (controller-added), m-3: never take index.lock / refresh the index


def _git_status(repo: Path) -> list:
    out = subprocess.run([*GIT, "-C", str(repo), "status", "--porcelain=v1", "-z", "--no-renames", "-uall"],
                         capture_output=True, text=True, check=True, timeout=GIT_TIMEOUT_S).stdout
    return [(e[:2], e[3:]) for e in out.split("\0") if len(e) > 3]


def _dirty_backend(repo: Path) -> list:
    """Tracked modifications of any type under backend/, plus UNTRACKED .py files there. Task 11 (controller-added),
    I-2: untracked non-.py files (SQLite -journal/-wal/-shm sidecars, logs, caches the app writes while running) are
    not semantic: closure .py files and config values are bound separately, and any new untracked .py still counts.
    Task 12 (A1.2): the dirty list is PROVENANCE only (recorded, never compared)."""
    return sorted(p for code, p in _git_status(repo) if p.startswith("backend/") and (code != "??" or p.endswith(".py")))


def _transient(repo: Path) -> list:
    """A1.2: untracked non-.py files under backend/ (SQLite sidecars, logs, runtime caches) - provenance only."""
    return sorted(p for code, p in _git_status(repo) if p.startswith("backend/") and code == "??"
                  and not p.endswith(".py"))


_RUNTIME_CODE = ("import sys,json,importlib.metadata as m\n"
                 "sys.path[:0]=[p for p in sys.argv[1:] if p]\n"
                 "d={}\n"
                 "for x in m.distributions():\n"
                 "    n=x.metadata['Name']\n"
                 "    if n: d.setdefault(n.lower(), x.version)\n"
                 "print(json.dumps({'python':sys.version.split()[0],'packages':d}))")


def _runtime(repo: Path, runtime_python, ct: dict):
    """A1.1: the backend's registered runtime - Python version and package versions, with the launcher's
    site-packages on the path first (the backend's effective packages). REQUIRED by the registered contract."""
    rt = ct["runtime"]
    py = Path(runtime_python) if runtime_python else None
    if py is None or not py.exists():
        if rt["required"]:
            raise ReceiptError(f"required runtime {rt['python']} missing", terminal=True)
        return "not registered"
    sp = Path(repo) / rt["site_packages"] if rt.get("site_packages") else None
    try:
        res = subprocess.run([str(py), "-I", "-c", _RUNTIME_CODE, str(sp) if sp and sp.is_dir() else ""],
                             capture_output=True, text=True, check=True, timeout=GIT_TIMEOUT_S)
        got = json.loads(res.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        raise ReceiptError(f"runtime query failed ({type(e).__name__})", terminal=False) from None
    got["site_packages"] = "present" if sp and sp.is_dir() else ABSENT
    return got


def _hmac(key: bytes, value: str) -> str:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def closure_raw_problems(backend: Path, reference) -> list:
    """Task 12 fix round 2 (I-1 completion, A1.1 "membership AND sha256 of every file"): every member of the bound
    reference's closure must still exist with its raw sha256 - checked from the bytes, BEFORE any parse."""
    fp = reference.get("fingerprint") if isinstance(reference, dict) and "fingerprint" in reference else reference
    members = fp.get("closure") if isinstance(fp, dict) else None
    if not isinstance(members, dict):
        return ["the bound reference has no closure (membership + sha256)"]
    probs = []
    for rel, h in sorted(members.items()):
        p = Path(backend) / rel
        if not p.is_file():
            probs.append(f"closure member {rel} missing")
        elif c.sha256_file(p) != h:
            probs.append(f"closure member {rel} changed (raw sha256 differs from the bound receipt)")
    return probs


def semantic_receipt(repo: Path, env_file: Path, runtime_python, roots=None, *, contract=None,
                     hmac_key=None, reference=None) -> dict:
    """A1: {"fingerprint": compared, "provenance": recorded}. Raises ReceiptError when the receipt cannot be
    produced: terminal for a missing registered root/member/required input (an established violation once
    registered), transient for an unavailable observation (git/runtime query failure, unreadable key).
    Task 12 fix round 2 (I-1 completion): with `reference` (the bound receipt or fingerprint) the closure's
    membership + raw sha256 are compared FIRST, before any file is parsed; a difference is a terminal change."""
    ct = EVIDENCE_CONTRACT if contract is None else contract
    repo = Path(repo)
    backend = repo / "backend"
    if reference is not None:
        raw = closure_raw_problems(backend, reference)
        if raw:
            raise ReceiptError(f"semantic change: {raw}", terminal=True)
    try:
        head = subprocess.run([*GIT, "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True, timeout=GIT_TIMEOUT_S).stdout.strip()
        dirty, transient = _dirty_backend(repo), _transient(repo)
    except (OSError, subprocess.SubprocessError) as e:
        raise ReceiptError(f"git unavailable ({type(e).__name__})", terminal=False) from None
    try:
        rels = closure(backend, roots or ct["closure_roots"])
    except ValueError as e:
        raise ReceiptError(f"closure root missing or invalid: {e}", terminal=True) from None
    files = {p: c.sha256_file(backend / p) for p in rels}
    resources = {}
    for res in ct["resources"]:
        p = repo / res["path"]
        if p.is_file():
            resources[res["path"]] = c.sha256_file(p)
        elif res.get("required"):
            raise ReceiptError(f"required resource {res['path']} missing", terminal=True)
        else:
            resources[res["path"]] = ABSENT
    cfg = ct["config"]
    if env_file is None or not Path(env_file).is_file():
        if cfg["env_required"]:
            raise ReceiptError(f"required config source {cfg['env_file']} (.env) missing", terminal=True)
        env, env_state = {}, ABSENT
    else:
        try:
            env, env_state = _env(env_file), "present"
        except OSError as e:
            raise ReceiptError(f".env unreadable ({type(e).__name__})", terminal=False) from None
    key = load_or_create_key(HMAC_KEY if hmac_key is None else hmac_key)
    transport_keys, secret = set(ct["transport_only_keys"]), re.compile(ct["secret_pattern"], re.I)
    keys = _mr_config_keys(backend, rels, include_secrets=True)
    values = {k: (c.sha256_bytes(env[k].encode()) if k in env else UNSET_MARK) for k in keys
              if k not in transport_keys and not secret.search(k)}
    secrets = {k: {"present": k in env, "hmac": _hmac(key, env[k]) if k in env else None} for k in keys
               if k not in transport_keys and secret.search(k)}
    transport = {k: (c.sha256_bytes(env[k].encode()) if k in env else UNSET_MARK) for k in keys if k in transport_keys}
    kid = key_id(key)
    fingerprint = {"contract_sha256": c.sha256_bytes(c.canonical(ct)), "closure": files, "resources": resources,
                   "config": {"env": env_state, "values": values, "secrets": secrets, "key_id": kid},
                   "runtime": _runtime(repo, runtime_python, ct), "key_id": kid}
    provenance = {"head": head, "dirty": dirty, "transient": transient, "transport": transport}
    return {"fingerprint": fingerprint, "provenance": provenance}


def restart_record(crash_log: Path, prev_size=None) -> dict:
    p = Path(crash_log)
    if not p.exists():
        return {"starts": [], "size": None, "sha256": None, "prefix_sha256": None}
    data = p.read_bytes()
    starts = []
    for line in data.decode("utf-8", errors="replace").splitlines():
        m = START_LINE.match(line)
        if m:
            starts.append({"ts": m.group(1), "pid": int(m.group(2))})
    uniq = [s for i, s in enumerate(starts) if s not in starts[:i]]        # the app writes the line twice
    rec = {"starts": uniq, "size": len(data), "sha256": c.sha256_bytes(data)}
    if prev_size is not None:
        rec["prefix_sha256"] = c.sha256_bytes(data[:prev_size])
    return rec


def restart_gaps(prev, obs) -> list:
    gaps = []
    pr, nr = prev["record"], obs["record"]
    if pr["size"] is not None and (nr["size"] is None or nr["size"] < pr["size"]):
        gaps.append("crash.log truncated, rotated or deleted")
    elif pr["sha256"] is not None and nr.get("prefix_sha256") is not None and nr["prefix_sha256"] != pr["sha256"]:
        gaps.append("crash.log rewritten (earlier bytes changed)")
    new_pids = {s["pid"] for s in nr["starts"]} - {s["pid"] for s in pr["starts"]}
    opid, ppid = obs.get("pid"), prev.get("pid")
    if opid is None:                       # a failed or empty lookup is a gap, never a restart or "no change"
        gaps.append(f"process not observed ({obs.get('error') or 'nothing listening'})")
    elif ppid is not None and opid != ppid and opid not in new_pids:
        gaps.append(f"pid {ppid} -> {opid} without a PROCESS START line")
    return gaps


_TOKEN = re.compile(r'"[^"]*"|\S+')
REDACTED = "<redacted>"


def sanitize_cmdline(cmdline: str) -> str:
    """A1.1: a command line with every value of a secret-named option masked (`--api-key=v`, `KEY=v`, `--token v`);
    everything else kept."""
    toks, out, mask_next = _TOKEN.findall(cmdline or ""), [], False
    for t in toks:
        if mask_next:
            out.append(REDACTED)
            mask_next = False
            continue
        name, eq, _ = t.partition("=")
        if eq and SECRET.search(name.strip('"').lstrip("-/")):
            out.append(f"{name}={REDACTED}")
        elif t.startswith(("-", "/")) and SECRET.search(t.lstrip("-/")):
            out.append(t)
            mask_next = True
        else:
            out.append(t)
    return " ".join(out)


BINDING_FIELDS = ("exe", "cmdline", "cmdline_sha256")
GAP_FIELD = "unavailable"
# Addendum 2 B2.4: the registered observation contract. A process observation is a dict: {"error": ...} = the
# observation FAILED (A9.1: preserved, never sealed); "binding" = {exe, cmdline (sanitized), cmdline_sha256} an
# OBSERVED binding (compared with the opening reference: MATCH or a change); "binding" = {"unavailable": reason} an
# explicitly represented GAP (never MATCH, never by itself a change). Anything else is MALFORMED (not equality).
PROCESS_OBSERVATION = {"failure": "error", "binding_fields": list(BINDING_FIELDS), "gap": GAP_FIELD}


def binding_problem(b) -> str:
    """Addendum 2 B2.3: why `b` is not a usable observed binding ("" when it is): exactly the binding fields, string
    executable and sanitized command line, and the command line's sha256."""
    if not isinstance(b, dict):
        return "no binding recorded"
    if set(b) != set(BINDING_FIELDS):
        return f"binding fields {sorted(b)} are not {list(BINDING_FIELDS)}"
    if not isinstance(b["exe"], str) or not isinstance(b["cmdline"], str):
        return "binding executable / command line is not text"
    if b["cmdline_sha256"] != c.sha256_bytes(b["cmdline"].encode("utf-8")):
        return "binding command-line hash does not match its command line"
    return ""


def process_identity(port: int = 8000) -> dict:
    """PID and start time of the process listening on `port` and (Task 12, A1.1) its binding evidence: executable
    path and SANITIZED command line (+ sha256). A failure is reported as an error, never as "nothing listening".
    Addendum 2 B2.4: an unavailable binding is represented explicitly ({"unavailable": reason})."""
    ps = ("$c = Get-NetTCPConnection -LocalPort %d -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1;"
          " if ($c) { $q = Get-Process -Id $c.OwningProcess;"
          " $w = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $c.OwningProcess);"
          " [pscustomobject]@{pid=$q.Id; process_start=$q.StartTime.ToString('s'); exe=$w.ExecutablePath;"
          " cmdline=$w.CommandLine} | ConvertTo-Json -Compress } else { '{}' }") % port
    try:
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                             timeout=GIT_TIMEOUT_S)
        if res.returncode != 0:
            return {"error": f"exit {res.returncode}"}
        got = json.loads(res.stdout.strip() or "{}")
    except Exception as e:                                   # never report a failure as "nothing listening"
        return {"error": type(e).__name__}
    exe, cmd = got.pop("exe", None), got.pop("cmdline", None)
    if exe and cmd:
        clean = sanitize_cmdline(cmd)
        got["binding"] = {"exe": exe, "cmdline": clean, "cmdline_sha256": c.sha256_bytes(clean.encode("utf-8"))}
    elif got.get("pid") is None:
        got["binding"] = {GAP_FIELD: "nothing listening"}
    else:
        got["binding"] = {GAP_FIELD: "executable or command line not readable"}
    return got
