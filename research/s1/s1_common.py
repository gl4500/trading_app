"""S1 shared constants and helpers (design s1_design_v5.md 33c32840; spec s1_spec.md 4b882f52)."""
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
NY = ZoneInfo("America/New_York")
AGENT = "MeanReversionAgent"
POLICY_ID = "P13"
SOLD_LT = 0.001                 # app close rule: backend/trading/portfolio.py `pos.shares < 0.001`
CONSIST_TOL = 1e-9
E1_SIM_SHA = "68f21ab19d74be27fc855f826a78b667990c2a37b5d75dd12e1a7be1f5a740fb"
E1_FETCH_SHA = "401f17deb3551b0a585be64eb49294f50bc0396272ecd48c9f9049acc86984d6"
# Task 11 (controller-added), I-5: the coordination mailbox every ACK is read from (read-only), never <root>.
MAILBOX = Path("C:/Users/gl450/.coordination/trading_app/mailbox.sqlite3")
_CACHE = {}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p) -> str:
    return sha256_bytes(Path(p).read_bytes())


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def aware(ts: str) -> datetime:
    """Stored ledger time -> aware UTC. `Z` accepted; naive read as UTC (E1 convention); anything else raises."""
    if not isinstance(ts, str) or not ts:
        raise ValueError(f"not a timestamp: {ts!r}")
    t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def toolchain_files() -> list:
    """Task 11 (controller-added), I-1: the registered protocol code = every research/s1 s1_*.py plus the pinned
    e1_sim.py and e1_fetch.py."""
    return sorted(HERE.glob("s1_*.py")) + [HERE / "e1_sim.py", HERE / "e1_fetch.py"]


def toolchain_sha256() -> str:
    """Task 11 (controller-added), I-1: sha256 over the sorted (name, sha256) pairs of toolchain_files()."""
    return sha256_bytes(canonical(sorted([p.name, sha256_file(p)] for p in toolchain_files())))


def load_pinned(name: str, path, sha: str):
    path = Path(path)
    if not path.exists() or sha256_file(path) != sha:
        raise SystemExit(f"{path.name}: missing or hash differs from the pinned {sha[:12]}")
    if name not in _CACHE:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _CACHE[name] = mod
    return _CACHE[name]


def sim():
    return load_pinned("e1_sim_pinned", HERE / "e1_sim.py", E1_SIM_SHA)


def fetch():
    return load_pinned("e1_fetch_pinned", HERE / "e1_fetch.py", E1_FETCH_SHA)


def p13() -> dict:
    p = next(p for p in sim().policy_family() if p["id"] == POLICY_ID)
    if (p["hard"], p["trail"], p.get("target"), p.get("time")) != (0.08, 0.12, None, None):
        raise SystemExit(f"P13 in the pinned core is not the registered rule: {p}")
    return p
