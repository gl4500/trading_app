"""S1-EPOCH (§12): semantic receipt (compared at every seal), process identity and the app's own crash.log
[PROCESS START] restart record (observed minimum; gaps reported). Read-only: git, files, the OS process table.
Limitation: the backend process's own environment overrides are not observable offline; config hashes come
from the .env file only."""
import ast
import json
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


def _imported_modules(backend: Path, f: Path, tree) -> list:
    """Files of every in-repo module (and `from pkg import mod` submodule) that tree imports."""
    pkg = list(f.parent.relative_to(backend).parts)
    found = []
    for node in ast.walk(tree):
        cands = []
        if isinstance(node, ast.Import):
            cands = [a.name.split(".") for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if node.level - 1 > len(pkg):
                    raise ValueError(f"relative import above backend/ in {f.relative_to(backend).as_posix()}")
                base = pkg[:len(pkg) - (node.level - 1)]
            else:
                base = []
            mod = base + (node.module.split(".") if node.module else [])
            cands = [mod] + [mod + [a.name] for a in node.names if a.name != "*"]
        for parts in cands:
            m = _module_file(backend, parts)
            if m is not None:
                found.append(m)
    return found


def _parse(f: Path):
    return ast.parse(f.read_text(encoding="utf-8"))


def closure(backend: Path, roots) -> list:
    missing = [r for r in roots if not (backend / r).exists()]
    if missing:
        raise ValueError(f"closure root(s) do not exist: {missing}")
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


def _mr_config_keys(backend: Path, files) -> list:
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
    return sorted(k for k in keys if not SECRET.search(k))


def _env(env_file: Path) -> dict:
    out = {}
    if env_file and Path(env_file).exists():
        for line in Path(env_file).read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _dirty_backend(repo: Path) -> list:
    out = subprocess.run(["git", "-C", str(repo), "status", "--porcelain=v1", "-z", "--no-renames", "-uall"],
                         capture_output=True, text=True, check=True).stdout
    paths = (e[3:] for e in out.split("\0") if len(e) > 3)
    return sorted(p for p in paths if p.startswith("backend/"))


def semantic_receipt(repo: Path, env_file: Path, runtime_python, roots=None) -> dict:
    backend = Path(repo) / "backend"
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()
    rels = closure(backend, roots or MR_ROOTS)
    files = {p: c.sha256_file(backend / p) for p in rels}
    env = _env(env_file)
    config = {k: c.sha256_bytes(env.get(k, UNSET).encode()) for k in _mr_config_keys(backend, rels)}
    versions = {"skipped": True}
    if runtime_python:
        versions = json.loads(subprocess.run(
            [str(runtime_python), "-I", "-c", "import sys,json,importlib.metadata as m;"
             "print(json.dumps({'python':sys.version.split()[0],"
             "'packages':{d.metadata['Name'].lower():d.version for d in m.distributions() if d.metadata['Name']}}))"],
            capture_output=True, text=True, check=True).stdout)
    return {"head": head, "dirty": _dirty_backend(repo), "files": files, "config": config, "versions": versions}


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
    if obs["pid"] != prev["pid"] and obs["pid"] not in new_pids:
        gaps.append(f"pid {prev['pid']} -> {obs['pid']} without a PROCESS START line")
    return gaps


def process_identity(port: int = 8000) -> dict:
    ps = ("$c = Get-NetTCPConnection -LocalPort %d -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1;"
          " if ($c) { $p = Get-Process -Id $c.OwningProcess; "
          "'{\"pid\":' + $p.Id + ',\"process_start\":\"' + $p.StartTime.ToString('s') + '\"}' } else { '{}' }") % port
    try:
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
        if res.returncode != 0:
            return {"error": f"exit {res.returncode}"}
        return json.loads(res.stdout.strip() or "{}")
    except Exception as e:                                   # never report a failure as "nothing listening"
        return {"error": type(e).__name__}
