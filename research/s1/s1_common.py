"""S1 shared constants and helpers (design s1_design_v5.md 33c32840; spec s1_spec.md 4b882f52; Addendum 1 rev 3
s1_design_v5_addendum1.md 6cb89e36; Addendum 2 rev 1 s1_design_v5_addendum2.md c7f0c3ff, which governs where they
differ).

Task 12 fix round 2 (Addendum 2 B3): the registration registry (s1_out/registry/), the file-only registration
artifact gate with its persistent first-wins "registration artifact" abort, the fail-closed abort reader, preserved
refusals (s1_out/refusals.jsonl) and the atomic exclusive publication used by the slot resolution records (B1).

Task 12 fix round 3 (re-review 1): C-1 every immutable artifact is published atomically and exclusively
(publish_exclusive / publish_text_exclusive; mutable caches by replace_atomic); C-2 the registration and every
registered stage are witnessed redundantly (both stage records - registry/ and witnesses/ -, the stage artifacts,
later-stage files, post-START claims and the external RUN-ACK), so deleting an artifact together with its registry
record is still the persistent abort; I-2 a lone stray file before any registration is a preserved refusal; M-2 the
attestation and prereg are registered before their artifacts, under s1_out/stage.lock.

Task 12 fix round 4 (re-review 2): N-1 the registration gate confirms a violation (stage.lock re-checked, a second
scan) before it aborts; N-2 opening-close evidence left without its records (an earlier opening attempt) is the
persistent abort and never a second opening seal; N-3 a registration witness must be tied to the opening close, and
before the opening close's first slot nothing is registered (clock anchor); m-1 stage.lock is kept when a stage's
records exist without its artifact after an error.

Task 12 (controller-added): the registered S1 bundle (A3), the ACK token texts and their read-only mailbox reader
(A8, shared so that s1_checkpoint can verify an ACK without importing s1_run/s1_collect), and the persistent
first-wins abort record."""
import hashlib
import importlib.util
import json
import os
import sqlite3
import uuid
from datetime import date, datetime, time, timezone
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
CAL_URL = "https://paper-api.alpaca.markets/v2/calendar"      # A6: the pinned provider session calendar
_CACHE = {}

# ---------------------------------------------------------------- A3: the registered S1 bundle
# A3.1: the EXPLICIT expected file list (every research/s1 s1_*.py plus the pinned E1 core and collector) and the
# sha256 of every pinned document (the v5 design, the spec, Addenda 1-3 and Erratum 1). Tests are evidence, not
# runtime dependencies: never listed.
BUNDLE_CODE = ("e1_fetch.py", "e1_sim.py", "s1_books.py", "s1_checkpoint.py", "s1_collect.py", "s1_common.py",
               "s1_gates.py", "s1_journal.py", "s1_locks.py", "s1_receipt.py", "s1_run.py", "s1_seal.py",
               "s1_snapshot.py", "s1_trial.py")
DOC_PINS = {"docs/s1_design_v5.md": "33c3284072dc51392476f7cae596eab05f1fcbaccd622abbe05c6e6a198cbb9b",
            "docs/s1_spec.md": "4b882f52a448dbf2d30583828c5085a636009f6c8db7b18307bc6e9991529c98",
            "docs/s1_design_v5_addendum1.md": "6cb89e36840975b8d949ec85debf9d2cedbe45bbeb9dcb374d91343dddc5e590",
            "docs/s1_design_v5_addendum2.md": "c7f0c3ffcd886b0f308c5f09bc0bfaca9977f8edae596bf51b30e28cb9ae3266",
            "docs/s1_design_v5_addendum3.md": "d9dd37595f0e0e73098ade1b8548e8cda2dc47fe49243f4d44735508029b9fb2",
            "docs/s1_design_v5_addendum3_erratum1.md":
                "b03464669673927fdb057acad9b0dc3258b1f08692d55ec3b0cffd4550f6ca2f"}    # adopted copy (de008b1)
MISSING = "missing"
ABSENT = "absent"                     # token placeholder for an artifact that does not exist

# ---------------------------------------------------------------- A8: ACK token texts (one source)
# Addendum 3 F6.1/F6.2 (OQ-5): the AUDIT-ACK carries the plan's trial_id first, in the s1_trial.ACK_FIELDS order.
# The RUN/ACQUIRE/SCORE texts are s1_trial.ACK_FIELDS; their tokens come from s1_trial.token.
AUDIT_ACK = ("S1-AUDIT-ACK trial_id={trial} bundle_sha256={bundle} collector_sha256={collector} plan_sha256={plan} "
             "start={start}")


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


def _sha_or_missing(p: Path) -> str:
    return sha256_file(p) if p.is_file() else MISSING


def bundle_manifest() -> dict:
    """A3.1 (replaces Task 11's toolchain_sha256): {"code": {listed file: sha256 | "missing"}, "unexpected":
    {s1_*.py present but not listed: sha256}, "docs": {pinned document: sha256 | "missing"}} of the files on disk."""
    listed = set(BUNDLE_CODE)
    return {"code": {n: _sha_or_missing(HERE / n) for n in BUNDLE_CODE},
            "unexpected": {p.name: sha256_file(p) for p in sorted(HERE.glob("s1_*.py")) if p.name not in listed},
            "docs": {d: _sha_or_missing(HERE / d) for d in DOC_PINS}}


def bundle_problems(manifest: dict) -> list:
    """Every difference of `manifest` from the explicit expected list: a missing member, an unexpected s1_*.py, a
    document differing from its pin, an E1 file differing from its pin. (Any of them also changes the hash.)"""
    out = [f"bundle member {n} missing" for n, v in manifest["code"].items() if v == MISSING]
    out += [f"unexpected bundle member {n}" for n in manifest["unexpected"]]
    out += [f"document {d} differs from its pin {DOC_PINS[d][:12]}" for d, v in manifest["docs"].items()
            if v != DOC_PINS[d]]
    for n, pin in (("e1_sim.py", E1_SIM_SHA), ("e1_fetch.py", E1_FETCH_SHA)):
        if manifest["code"].get(n) not in (pin, MISSING):
            out.append(f"{n} differs from its pin {pin[:12]}")
    return out


def bundle_sha256() -> str:
    """A3.1: sha256 of the canonical bundle manifest (explicit list + unexpected members + document hashes)."""
    return sha256_bytes(canonical(bundle_manifest()))


def load_pinned(name: str, path, sha: str):
    """A3.1: a module loaded by approved hash; the cache is keyed by (name, resolved path, approved hash), so another
    file or another approved hash is never served the module loaded first."""
    path = Path(path)
    if not path.exists() or sha256_file(path) != sha:
        raise SystemExit(f"{path.name}: missing or hash differs from the pinned {sha[:12]}")
    key = (name, str(path.resolve()), sha)
    if key not in _CACHE:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _CACHE[key] = mod
    return _CACHE[key]


def sim():
    return load_pinned("e1_sim_pinned", HERE / "e1_sim.py", E1_SIM_SHA)


def fetch():
    return load_pinned("e1_fetch_pinned", HERE / "e1_fetch.py", E1_FETCH_SHA)


def p13() -> dict:
    p = next(p for p in sim().policy_family() if p["id"] == POLICY_ID)
    if (p["hard"], p["trail"], p.get("target"), p.get("time")) != (0.08, 0.12, None, None):
        raise SystemExit(f"P13 in the pinned core is not the registered rule: {p}")
    return p


# ---------------------------------------------------------------- A3/A8: persistent abort, mailbox, ACK tokens
CORRUPT_ABORT = "aborted.json unreadable (corrupt): fails closed as ABORTED-INVALID"


def load_abort(out: Path):
    """Task 12 fix round 2 (B3.4): the persistent abort record, or None when there is none. A corrupt aborted.json
    FAILS CLOSED: it is an abort (never "no abort"), returned as a marker record."""
    p = Path(out) / "aborted.json"
    if not p.exists():
        return None
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(rec, dict):
            return rec
    except (OSError, ValueError):
        pass
    return {"reason": CORRUPT_ABORT, "corrupt": True, "actual": None, "close": None, "scheduled": None}


def write_abort(out: Path, rec: dict) -> dict:
    """First abort wins (exclusive create): ABORTED-INVALID is permanent from that instant (v5 §6/§12, A3.3, A9.2).
    Returns the stored record (this one, or the earlier one that won; a corrupt one fails closed, B3.4).
    Fix round 3 (C-1): published atomically (publish_text_exclusive), so a concurrent writer or reader never sees a
    partial aborted.json (which would read as the CORRUPT marker and lose the real reason)."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        publish_text_exclusive(out / "aborted.json", json.dumps(rec, indent=1, default=str))
    except FileExistsError:
        return load_abort(out)
    return rec


def publish_exclusive(path: Path, data: bytes) -> None:
    """Task 12 fix round 2 (B1.2/B1.3): publish `data` at `path` atomically and exclusively: written and flushed to a
    unique temporary file first, then hard-linked into place (the link fails with FileExistsError when `path`
    exists), so a record is either absent or complete - never partial - and never replaced. Fix round 3 (C-1): the
    ONLY exclusive create in the bundle; every immutable artifact is published through it (or the text form)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        with tmp.open("xb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.link(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def text_bytes(text: str) -> bytes:
    """The bytes a text-mode write of `text` produces (platform newline translation, UTF-8)."""
    return text.replace("\n", os.linesep).encode("utf-8")


def publish_text_exclusive(path: Path, text: str) -> None:
    """Fix round 3 (C-1): publish_exclusive of `text` with the platform newline translation of a text-mode write,
    so an artifact keeps exactly the bytes its former exclusive text-mode write produced."""
    publish_exclusive(path, text_bytes(text))


def replace_atomic(path: Path, text: str) -> None:
    """Fix round 3 (C-1): a MUTABLE cache file (e.g. last_process.json) replaced atomically (temporary file + fsync
    + os.replace), so a concurrent reader sees the old or the new content, never a partial one."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        with tmp.open("wb") as f:
            f.write(text.replace("\n", os.linesep).encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def bundle_gate(out: Path, expected, *, registered: bool, where: str, now=None) -> str:
    """A3.2/A3.3: compare the bundle on disk with the externally approved `expected` hash, FIRST. A mismatch against a
    valid registered bundle (`registered`: from the opening seal to the score) is a persistent protocol failure:
    aborted.json reason "bundle" (first abort wins; restoring files never resumes the trial). Before any
    registration it is a refusal only. Either way the command stops (SystemExit). Returns the observed hash."""
    observed = bundle_sha256()
    if observed == expected:
        return observed
    if registered:
        t = (now or now_utc)()
        manifest = bundle_manifest()
        write_abort(out, {"reason": "bundle", "where": where, "expected_bundle_sha256": expected,
                          "observed_bundle_sha256": observed, "problems": bundle_problems(manifest),
                          "observed_manifest": manifest, "actual": t.isoformat(), "close": None,
                          "scheduled": None, "projection_sha256": None, "receipt_sha256": None})
        raise SystemExit(f"{where} refused: S1 bundle {str(observed)[:12]} differs from the registered "
                         f"{str(expected)[:12]}: persistent ABORTED-INVALID (reason bundle)")
    raise SystemExit(f"{where} refused: S1 bundle {str(observed)[:12]} differs from the approved "
                     f"{str(expected)[:12]} (nothing registered yet)")


def mailbox_message(ack_id: str, mailbox=None) -> dict:
    """The codex->claude experiments-prereg message `ack_id` from the coordination mailbox (default MAILBOX), opened
    read-only (mode=ro URI: never created or written): {ack_id, created_utc, lines}. Any other message refuses;
    an unreadable mailbox raises sqlite3.Error."""
    rows = _mailbox_rows("SELECT sender, recipient, request_key, body, created FROM messages WHERE id=?", (ack_id,),
                         mailbox)
    row = rows[0] if rows else None
    if row is None or row[:3] != ("codex", "claude", "experiments-prereg"):
        raise SystemExit(f"{ack_id!r} is not a codex->claude experiments-prereg message")
    return {"ack_id": ack_id, "created_utc": datetime.fromtimestamp(row[4], tz=timezone.utc).isoformat(),
            "lines": [ln.rstrip("\r") for ln in (row[3] or "").split("\n")]}


def _mailbox_rows(sql: str, params, mailbox=None) -> list:
    """The ONE reader of the coordination mailbox (default MAILBOX), opened read-only (mode=ro URI: never created or
    written); an unreadable mailbox raises sqlite3.Error."""
    path = Path(MAILBOX if mailbox is None else mailbox)
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def ack(ack_id: str, token: str, mailbox=None) -> dict:
    """The message `ack_id` must carry `token` as a standalone line and not be in the future (s1_collect._ack)."""
    m = mailbox_message(ack_id, mailbox)
    if token not in m["lines"]:
        raise SystemExit(f"ack lacks the standalone line: {token}")
    if aware(m["created_utc"]) > now_utc():
        raise SystemExit("ack is in the future")
    return {"ack_id": ack_id, "created_utc": m["created_utc"]}


def token_fields(line: str) -> dict:
    """`key=value` fields of a token line."""
    return dict(x.split("=", 1) for x in line.split(" ") if "=" in x)


def ack_line(msg: dict, prefix: str) -> str:
    """The one standalone line of `msg` starting with `prefix` (e.g. "S1-RUN-ACK"); none or several refuse."""
    got = [ln for ln in msg["lines"] if ln.startswith(prefix + " ")]
    if len(got) != 1:
        raise SystemExit(f"{msg['ack_id']!r}: expected exactly one {prefix} line, found {len(got)}")
    return got[0]


def load_json(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def sha_or_absent(p: Path) -> str:
    return sha256_file(p) if Path(p).exists() else ABSENT


def receipt_sha256(receipt) -> str:
    """A1: the receipt's VALIDITY hash = sha256 of its fingerprint only (provenance is recorded, never compared). A
    receipt without a fingerprint is missing required evidence."""
    if not isinstance(receipt, dict) or not isinstance(receipt.get("fingerprint"), dict):
        raise ValueError("receipt has no fingerprint (missing required evidence)")
    return sha256_bytes(canonical(receipt["fingerprint"]))


def opening_seal_path(out: Path, plan: dict) -> Path:
    return Path(out) / "seals" / f"{plan.get('opening_close')}.json"


def audit_token(out: Path) -> str:
    out = Path(out)
    plan = load_json(out / "plan.json")
    return AUDIT_ACK.format(trial=plan["trial_id"], collector=sha256_file(HERE / "s1_collect.py"),
                            plan=sha256_file(out / "plan.json"), bundle=bundle_sha256(), start=plan["planned_start"])


def _trial_token(kind: str, out: Path, mailbox=None) -> str:
    import s1_trial                                    # late import: s1_trial imports this module
    return s1_trial.token(kind, Path(out).parent, mailbox=mailbox)


def run_token(out: Path, mailbox=None) -> str:
    return _trial_token("S1-RUN-ACK", out, mailbox)


def acquire_token(out: Path, mailbox=None) -> str:
    return _trial_token("S1-ACQUIRE-ACK", out, mailbox)


def score_token(out: Path, mailbox=None) -> str:
    return _trial_token("S1-SCORE-ACK", out, mailbox)


def registration(out: Path, mailbox=None) -> dict:
    """A3.2 minimal bootstrap reads: the externally approved expected bundle and whether a registration exists.
    - prereg.json present: its RUN-ACK (prereg ack_id -> mailbox) S1-RUN-ACK line's bundle, which prereg must
      repeat; registered (fix round 4, N-3: never before the opening close's first slot).
    - else an audit manifest: its S1-AUDIT-ACK line's bundle; registered once the opening seal exists.
    - else nothing: {"stage": None}.
    The expected hash always comes from a codex mailbox ACK, never from prereg/plan state alone. A missing or
    malformed ACK refuses (SystemExit: invalid authorization, zero live callbacks)."""
    out = Path(out)
    if (out / "prereg.json").exists():
        try:
            pr = load_json(out / "prereg.json")
            ack_id = pr["ack"]["ack_id"]
        except (OSError, ValueError, KeyError, TypeError):
            raise SystemExit("registration refused: prereg.json names no RUN-ACK") from None
        try:
            line = ack_line(mailbox_message(ack_id, mailbox), "S1-RUN-ACK")
        except sqlite3.Error as e:
            raise SystemExit(f"registration refused: RUN-ACK mailbox unreadable ({type(e).__name__})") from None
        except SystemExit as e:
            raise SystemExit(f"registration refused: RUN-ACK not verified ({e})") from None
        b = token_fields(line).get("bundle_sha256")
        if not b or pr.get("bundle_sha256") != b:
            raise SystemExit("registration refused: prereg bundle differs from its RUN-ACK")
        return {"stage": "prereg", "bundle": b, "registered": is_registered(out, mailbox, bundle=b),   # fix round 8
                "ack_id": ack_id}
    return _audit_registration(out, mailbox)


def _audit_registration(out: Path, mailbox=None) -> dict:
    """The audit stage of registration(): the AUDIT-ACK's approved bundle; registered once the opening seal exists."""
    out = Path(out)
    mp = out / "audit" / "manifest.json"
    if mp.exists():
        try:
            m, plan = load_json(mp), load_json(out / "plan.json")
            ack_id = m["ack"]["ack_id"]
        except (OSError, ValueError, KeyError, TypeError):
            raise SystemExit("registration refused: the audit manifest names no AUDIT-ACK") from None
        try:
            line = ack_line(mailbox_message(ack_id, mailbox), "S1-AUDIT-ACK")
        except sqlite3.Error as e:
            raise SystemExit(f"registration refused: AUDIT-ACK mailbox unreadable ({type(e).__name__})") from None
        except SystemExit as e:
            raise SystemExit(f"registration refused: AUDIT-ACK not verified ({e})") from None
        b = token_fields(line).get("bundle_sha256")
        if not b:
            raise SystemExit("registration refused: the AUDIT-ACK carries no bundle")
        return {"stage": "audit", "bundle": b, "registered": is_registered(out, mailbox, bundle=b), "ack_id": ack_id}
    return {"stage": None, "bundle": None, "registered": False, "ack_id": None}


def verify_bundle_first(out: Path, where: str, *, mailbox=None, now=None, need=None, gate_refuses=True) -> dict:
    """A3.2: the first step of every S1 command after the bootstrap reads: the registration's approved bundle must
    equal the one on disk (a mismatch is persistent once registered, A3.3). `need` = the stage required ("prereg"
    or "audit"); a command without it refuses. Task 12 fix round 2 (B3): then the file-only registration-artifact
    gate (registration_gate) - also when the authorization could not be read (a mailbox outage cannot downgrade an
    established violation, B3.4); every refusal is preserved in s1_out/refusals.jsonl (B3.2)."""
    out = Path(out)
    try:
        err = None
        try:
            reg = registration(out, mailbox)
        except SystemExit as e:                 # fix round 1 (m-1): compare against the AUDIT-ACK bundle first
            err = e
            try:
                reg = _audit_registration(out, mailbox)
            except SystemExit:
                reg = {"stage": None}
        if reg["stage"] is not None:
            bundle_gate(out, reg["bundle"], registered=reg["registered"], where=where, now=now)
        registration_gate(out, where, now, refuse=gate_refuses, mailbox=mailbox)       # B3.3
        if err is not None:
            raise err
        if need == "prereg" and reg["stage"] != "prereg":
            raise SystemExit(f"{where} refused: no verified prereg (RUN-ACK registration)")
        if need == "audit" and reg["stage"] is None:
            raise SystemExit(f"{where} refused: no AUDIT-ACK'd audit")
        return reg
    except SystemExit as e:
        record_refusal(out, where, e, now)
        raise


# ---------------------------------------------------------------- B3: registry, witnesses, registration gate
REGISTRY_STAGES = ("opening", "attest_start", "prereg", "stop")
REGISTRATION_ARTIFACT = "registration artifact"
WITNESSES = "witnesses"            # fix round 3 (C-2): the second, independent registration record of every stage
STAGE_LOCK = "stage.lock"          # fix round 3 (C-2/M-2): a stage publication (records, then artifact) in progress
STAGE_ARTIFACT = {"attest_start": "attest_start.json", "prereg": "prereg.json", "stop": "stop.json"}
# Witnesses of an opening that is IN PROGRESS (published before the opening seal): alone they are no registration.
IN_PROGRESS = ("registry/opening.json", f"{WITNESSES}/opening.json", "opening resolution", "opening capture")
# Fix round 4 (N-3, controller ruling on A1/B3.1): the witnesses TIED TO THE OPENING CLOSE; a registration needs one
# (later-stage files count only once one exists).
OPENING_TIED = ("opening seal", "opening capture report", "opening resolution", "opening capture", "RUN-ACK")
# Later-stage files (each only ever written after a registration): witnesses of the registration and of their stage.
LATER_FILES = ("opening_books.json", "attest_stop.json", "final_plan.json", "final/manifest.json",
               "final_snapshot/report.json")
# File-only bindings recorded INSIDE the attestation / prereg (fix round 3, C-2: a second source of expected hashes;
# None = the opening seal).
ATTEST_BINDS = (("plan_sha256", "plan.json"), ("audit_manifest_sha256", "audit/manifest.json"),
                ("opening_seal_sha256", None), ("opening_books_sha256", "opening_books.json"))
PREREG_BINDS = ATTEST_BINDS + (("attest_start_sha256", "attest_start.json"),)


def record_refusal(out: Path, where: str, e, now=None) -> None:
    """B3.2: a refused invocation is preserved (one JSON line: where, the refusal text - S1's own messages, built
    without secret values - and the time)."""
    try:
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        with (out / "refusals.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"where": where, "refused": str(e), "utc": (now or now_utc)().isoformat()}) + "\n")
    except OSError:
        pass                                    # the refusal itself still stands (SystemExit is re-raised)


def stage_records(out: Path, stage: str) -> list:
    """Fix round 3 (C-2): the two independent registration records of `stage`: registry/<stage>.json and
    witnesses/<stage>.json (identical content, published one after the other)."""
    return [Path(out) / "registry" / f"{stage}.json", Path(out) / WITNESSES / f"{stage}.json"]


def register_stage(out: Path, stage: str, artifacts: dict, **extra) -> dict:
    """B3.1: the expected sha256 of every artifact bound at `stage` (relative paths), recorded once (exclusive) in
    BOTH stage records (fix round 3, C-2: deleting an artifact together with one record leaves the other). An
    existing record with the same artifacts is kept (a concurrent writer of the same registration, or the
    completion of an interrupted one); a different one refuses. Callers whose artifact bytes are known first
    register BEFORE publishing the artifact (fix round 3, M-2)."""
    rec = {"stage": stage, "artifacts": dict(sorted(artifacts.items())), **extra}
    data = json.dumps(rec, indent=1, sort_keys=True, default=str).encode("utf-8")
    kept = None
    for p in stage_records(out, stage):
        try:
            publish_exclusive(p, data)
        except FileExistsError:
            old = _registry_record(p)
            if not isinstance(old, dict) or old.get("artifacts") != rec["artifacts"]:
                raise SystemExit(f"{p.parent.name}/{stage}.json already records different artifacts: refusing") \
                    from None
            kept = kept or old
    return kept or rec


class stage_publication:
    """Fix round 3 (C-2/M-2): `with stage_publication(out, stage):` around a stage's record + artifact publications
    (the START attestation, prereg). While s1_out/stage.lock exists the registration gate REFUSES (a preserved
    refusal, never an abort), so a concurrent command never mistakes the instant between the records and the
    artifact for a deletion. A crash inside (any BaseException other than SystemExit / Exception) leaves the lock:
    every command then refuses until the operator inspects and removes it; a stage left with records but no artifact
    is then the persistent abort (disclosed crash window). Fix round 4 (m-1): an ordinary error (an OSError such as
    a full disk, a SystemExit) after the stage's records exist but before its artifact is published does NOT release
    the lock as clean either: the lock is kept (rewritten to name the interrupted stage and the error), so the next
    command refuses instead of recording a false abort; the operator recovers by removing the lock together with the
    stage's two records (the pre-stage state), never the lock alone."""

    def __init__(self, out: Path, stage: str = None):
        self.out, self.stage = Path(out), stage
        self.p = self.out / STAGE_LOCK

    def _half_published(self) -> bool:
        """The stage's records (either) exist but its artifact does not (m-1)."""
        if self.stage is None:
            return False
        return (any(p.exists() for p in stage_records(self.out, self.stage))
                and not (self.out / STAGE_ARTIFACT[self.stage]).exists())

    def __enter__(self):
        try:
            publish_text_exclusive(self.p, json.dumps({"pid": os.getpid(), "utc": now_utc().isoformat()}))
        except FileExistsError:
            raise SystemExit(f"refused: a stage publication is in progress or was interrupted ({self.p.name})") \
                from None
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None and issubclass(exc_type, (Exception, SystemExit)) and self._half_published():
            try:                                      # m-1: kept; records exist without the artifact
                replace_atomic(self.p, json.dumps({"interrupted": self.stage, "error": exc_type.__name__,
                                                   "utc": now_utc().isoformat()}))
            except OSError:
                pass                                  # (the lock file itself is still there)
            return False
        if exc_type is None or issubclass(exc_type, (Exception, SystemExit)):
            try:
                self.p.unlink()
            except FileNotFoundError:
                pass
        return False


def _registry_record(p: Path):
    try:
        rec = load_json(p)
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) and isinstance(rec.get("artifacts"), dict) else None


def _report_seals(out: Path) -> list:
    """(report path, seal path, sha256) of every capture report that records a written seal - or (fix round 5, R-3)
    of every capture report or slot claim that records an existing opening seal it found (the "after_seal" record of
    an opening slot that ran after the seal)."""
    got = []
    out = Path(out)
    for p in sorted(out.glob("captures/*/*.report.json")) + sorted(out.glob("captures/*/*.attempt.json")):
        try:
            rep = load_json(p)
            seal, after = rep.get("seal") or {}, rep.get("after_seal") or {}
            if seal.get("written") is True or after.get("sha256"):
                day = datetime.fromisoformat(rep["close"].replace("Z", "+00:00")).astimezone(NY).date().isoformat()
                got.append((p, Path(out) / "seals" / f"{day}.json",
                            seal.get("sha256") if seal.get("written") is True else after.get("sha256")))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    return got


def _opening_seal_rel(out: Path):
    """The opening seal's path relative to s1_out ("seals/<plan opening_close>.json"); from the opening's stage
    records when plan.json is unreadable; None when nothing names it."""
    out = Path(out)
    try:
        oc = load_json(out / "plan.json").get("opening_close")
        if isinstance(oc, str) and oc:
            return f"seals/{oc}.json"
    except (OSError, ValueError, AttributeError):
        pass
    for p in stage_records(out, "opening"):
        rec = _registry_record(p) if p.exists() else None
        for rel in sorted((rec or {}).get("artifacts", {})):
            if rel.startswith("seals/"):
                return rel
    return None


def _start_day(out: Path):
    """planned START's New York date (plan, else prereg), or None."""
    for name, key in (("plan.json", "planned_start"), ("prereg.json", "start")):
        try:
            return aware(load_json(Path(out) / name)[key]).astimezone(NY).date().isoformat()
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    return None


def _day_success(out: Path, day: str) -> bool:
    for p in sorted((Path(out) / "captures" / day).glob("*.resolution.json")):
        try:
            if load_json(p).get("outcome") == "SUCCESS":
                return True
        except (OSError, ValueError, AttributeError):
            continue
    return False


def _post_start_capture(out: Path, opening_day) -> bool:
    """A slot claim or seal of a close on/after START (only a verified prereg lets a checkpoint claim one)."""
    out = Path(out)
    sd = _start_day(out)
    for d in sorted((out / "captures").glob("*")):
        if d.is_dir() and d.name != opening_day and (sd is None or d.name >= sd) and any(d.glob("*.attempt.json")):
            return True
    return any(p.stem != opening_day and (sd is None or p.stem >= sd) for p in (out / "seals").glob("*.json"))


def _opening_day_of(out: Path):
    """The opening close's New York date (from _opening_seal_rel), or None."""
    rel = _opening_seal_rel(out)
    return rel[len("seals/"):-len(".json")] if rel else None


EARLIEST_CLOSE_NY = time(13, 0)    # fix round 9 (H-3): the earliest scheduled (early) close of a session, 13:00 New York


def _earliest_first_slot(day):
    """Fix round 9 (H-3, controller decision): the EARLIEST possible first registered slot of the close on `day` - the
    first seal offset after the earliest early close (EARLIEST_CLOSE_NY) on that date - computed without any calendar
    file, so no local calendar edit can move it. None for a value that is no date."""
    import s1_seal                                          # (late import: s1_seal imports this module)
    try:
        close = datetime.combine(date.fromisoformat(day), EARLIEST_CLOSE_NY, tzinfo=NY).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None
    return s1_seal.first_slot_after(close)


LATER_ACKS = ("S1-RUN-ACK", "S1-ACQUIRE-ACK", "S1-SCORE-ACK")    # the AUDIT-ACK-dependent stages (B3.1)


def bundle_acks(bundle=None, mailbox=None) -> dict:
    """Fix round 8 (H-2): {prefix: [token fields, ...]} of every S1-* ACK line in the codex->claude
    experiments-prereg messages of the coordination mailbox (opened read-only) whose bundle_sha256 equals `bundle`
    (default: the bundle on disk; the bundle check runs first and is itself first-wins, A3.2/A3.3). ACKs are found by
    this key only - never through hashes read from editable local files. An unreadable mailbox raises sqlite3.Error."""
    b = bundle or bundle_sha256()
    rows = _mailbox_rows("SELECT body FROM messages WHERE sender='codex' AND recipient='claude' AND "
                         "request_key='experiments-prereg'", (), mailbox)
    got = {}
    for (body,) in rows:
        for ln in (body or "").split("\n"):
            ln = ln.rstrip("\r")
            if ln.startswith("S1-") and " " in ln:
                f = token_fields(ln)
                if f.get("bundle_sha256") == b:
                    got.setdefault(ln.split(" ", 1)[0], []).append(f)
    return got


def _local_opening_evidence(out: Path) -> list:
    """Fix round 8 (rule 3): every local file only an opening produces (seals, opening records, capture entries, the
    stored opening receipt, last_process.json)."""
    out = Path(out)
    got = [p.relative_to(out).as_posix() for p in sorted((out / "seals").glob("*.json"))]
    got += [p.relative_to(out).as_posix() for p in stage_records(out, "opening") if p.exists()]
    got += [p.relative_to(out).as_posix() for p in sorted(out.glob("captures/*/*"))]
    return got + [n for n in ("opening_receipt.json", "last_process.json") if (out / n).exists()]


def registration_state(out: Path, mailbox=None, now=None, bundle=None) -> dict:
    """Fix round 8 (operator-approved structural rule, B3.1/B3.3/B3.4) - the ONE decision of whether a registration
    exists. Supersedes the plan/manifest/record-derived anchors of fix rounds 4-7.
    - The opening close DATE is plan.json's opening_close, used ONLY while plan.json's sha256 equals the plan_sha256
      of an S1-AUDIT-ACK found by bundle_sha256 (fix round 9, H-3: the AUDIT-ACK fixes the date externally). The
      anchor is that date's EARLIEST possible first slot (_earliest_first_slot: as if the close were the earliest
      early close) - no calendar file is read. A plan differing from every such AUDIT-ACK names nothing
      ("plan_bound" False): with local opening evidence that is the abort, otherwise a refusal.
    - registered = (a) a RUN-, ACQUIRE- or SCORE-ACK carrying the bundle (with an AUDIT-ACK carrying it) - never
      cancelled by the anchor; or (b) the local witnesses (registration_witnesses named by that opening close, the
      N-3 rule _registered) once the clock is at/after the anchor. The anchor's ONLY role: local files present
      before it are discounted (B3.2 fabrication before the opening -> refusal).
    - Mailbox readable but no AUDIT-ACK carries the bundle: not past audit - the trial cannot be registered: always a
      preserved refusal, never an abort, whatever local files exist (fix round 9: controller correction of the fix-8
      brief rule 3, B3.2 / I-2).
    - Mailbox unreadable (sqlite3.Error, "outage"): nothing external can be read; every command refuses at
      registration() (B3.4). The local witnesses (named by plan.json, else the opening records) still decide a
      registration WITHOUT the anchor, so an artifact violation observed during an outage is not downgraded (B3.4)."""
    out = Path(out)
    try:
        acks, outage = bundle_acks(bundle, mailbox), False
    except sqlite3.Error:
        acks, outage = {}, True
    audits = acks.get("S1-AUDIT-ACK", [])
    plan_sha = sha256_file(out / "plan.json") if (out / "plan.json").is_file() else None
    plan_bound = plan_sha is not None and any(f.get("plan_sha256") == plan_sha for f in audits)
    oday = None
    if plan_bound:
        try:
            oday = load_json(out / "plan.json").get("opening_close")
        except (OSError, ValueError, AttributeError):
            oday = None
    oday = oday if isinstance(oday, str) and oday else None
    anchor = _earliest_first_slot(oday) if oday else None
    later = [f for x in LATER_ACKS for f in acks.get(x, [])] if audits else []
    run_acks = acks.get("S1-RUN-ACK", []) if audits else []
    if outage:
        oday, local = _opening_day_of(out), True
    else:
        local = anchor is not None and (now or now_utc)() >= anchor
    w = registration_witnesses(out, oday, bool(later)) if (local or later) else []
    return {"outage": outage, "audited": bool(audits), "plan_bound": plan_bound, "audit_acks": audits,
            "run_acks": run_acks,
            "oday": oday, "anchor": anchor, "local": local, "external": bool(later), "witnesses": w,
            "registered": bool(later) or (local and _registered(w))}


def opening_anchor(out: Path, mailbox=None):
    """Fix round 8: the first slot of the opening close named by the AUDIT-ACK(s) carrying the bundle (None without
    one; registration_state)."""
    return registration_state(out, mailbox)["anchor"]


def _valid_opening_seal(out: Path, rel) -> bool:
    """N-3: the opening seal file is a seal OF the opening close (a JSON seal record whose close is on the opening
    date, with its capture record) - not merely a file at that path."""
    try:
        rec = load_json(Path(out) / rel)
        return (isinstance(rec, dict) and isinstance(rec.get("capture"), dict)
                and aware(rec["close"]).astimezone(NY).date().isoformat() == rel[len("seals/"):-len(".json")])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


CAPTURE_RECORDS = (".resolution.json", ".report.json", ".late.json", ".overrun.json")


def _finalizer_missed(q: Path, slot: str) -> bool:
    """Fix round 5 (R-1, B1.2): `q` is a MISSED resolution a finalizer can have written for the never-claimed slot
    `slot` - outcome MISSED, for this slot, decided strictly after the slot's eligibility end E, without capture
    evidence. Such a record legitimately has no claim; every other claimless record is opening orphan evidence."""
    if not q.name.endswith(".resolution.json"):
        return False
    try:
        rec = load_json(q)
        return (isinstance(rec, dict) and rec.get("outcome") == "MISSED" and "evidence" not in rec
                and aware(rec["slot"]).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ") == slot
                and aware(rec["eligible_until"]) < aware(rec["decided_utc"]))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def opening_orphans(out: Path, oday=None) -> list:
    """Fix round 4 (N-2): opening-close evidence that only an earlier opening attempt produces, left WITHOUT the
    record that is always published before it - so its presence means records were deleted (an opening happened):
    a slot capture directory or a slot resolution/report/late/overrun record without its slot claim (the claim is
    published first, A5.2) - except (fix round 5, R-1) a finalizer's MISSED record of a never-claimed slot
    (_finalizer_missed, B1.2), which never has a claim; a capture report without its resolution (published before the report, B1.3);
    last_process.json (written only after a slot claim)
    without any slot claim; the stored opening receipt (written only after an opening SUCCESS resolution was read,
    controller ruling 3) without an opening SUCCESS resolution. A legitimate opening in progress - a FAILURE, a
    crash before a resolution, a SUCCESS awaiting its seal - leaves none of these. (A report recording a written
    opening seal is itself a registration witness: its missing seal is a registration problem.)"""
    out = Path(out)
    oday = oday or _opening_day_of(out)                    # (fix round 8: the caller's AUDIT-ACK-named close)
    if oday is None:
        return []
    d, probs = out / "captures" / oday, []
    if d.is_dir():
        for q in sorted(d.iterdir()):
            slot = q.name if q.is_dir() else next((q.name[:-len(x)] for x in CAPTURE_RECORDS if q.name.endswith(x)),
                                                  None)
            if slot is None:
                continue
            if not (d / f"{slot}.attempt.json").exists() and not _finalizer_missed(q, slot):     # fix5 (R-1)
                probs.append(f"captures/{oday}/{q.name} exists without its slot claim (an earlier opening attempt)")
            if q.name.endswith(".report.json") and not (d / f"{slot}.resolution.json").exists():
                probs.append(f"captures/{oday}/{q.name} exists without its resolution (an earlier opening attempt)")
    if (out / "last_process.json").exists() and not any(out.glob("captures/*/*.attempt.json")):
        probs.append("last_process.json exists without any slot claim (an earlier opening attempt)")
    if (out / "opening_receipt.json").exists() and not _day_success(out, oday):
        probs.append("opening_receipt.json exists without an opening SUCCESS resolution (an earlier opening attempt)")
    return probs


def run_ack_witness(out: Path, mailbox=None):
    """Fix round 3 (C-2) / 8 (H-2): the EXTERNAL witness - the first S1-RUN-ACK line carrying the registered bundle
    (found by bundle_sha256 only, with an AUDIT-ACK carrying it; registration_state). Returns its fields, or None (no
    such ACK, or the mailbox unreadable: the absence of this witness is never evidence of anything)."""
    acks = registration_state(out, mailbox)["run_acks"]
    return acks[0] if acks else None


def registration_witnesses(out: Path, oday, external: bool) -> list:
    """Fix round 3 (C-2, I-2) / 8: the names of the registration witnesses present. Witnesses: the opening seal of
    `oday` (the opening close named by registration_state), an opening-close capture report recording a written or
    after-seal opening seal, an opening-close SUCCESS resolution, both records of every stage, the START attestation /
    prereg / stop.json, the later-stage files (opening books, stop attestation, final plan, final manifest, final
    snapshot report), any post-START slot claim or seal, and ("RUN-ACK") an external ACK carrying the bundle. Fix
    round 4 (N-3): the opening seal counts only as a valid seal of the opening close; any opening-close capture
    evidence (a claim, capture directory or slot record) is the "opening capture" witness (in progress alone)."""
    out = Path(out)
    rel = f"seals/{oday}.json" if oday else None
    got = []
    if rel and (out / rel).is_file() and _valid_opening_seal(out, rel):          # fix round 4 (N-3): a valid one
        got.append("opening seal")
    if oday and any(sp.stem == oday for _, sp, _ in _report_seals(out)):
        got.append("opening capture report")
    if oday and _day_success(out, oday):
        got.append("opening resolution")
    if oday and (out / "captures" / oday).is_dir() and any((out / "captures" / oday).iterdir()):
        got.append("opening capture")                       # fix round 4 (N-3): claims, captures, records
    for stage in REGISTRY_STAGES:
        got += [p.relative_to(out).as_posix() for p in stage_records(out, stage) if p.exists()]
        if stage in STAGE_ARTIFACT and (out / STAGE_ARTIFACT[stage]).exists():
            got.append(STAGE_ARTIFACT[stage])
    got += [f for f in LATER_FILES if (out / f).exists()]
    if _post_start_capture(out, oday):
        got.append("post-START capture")
    if external:
        got.append("RUN-ACK")
    return got


def _registered(witnesses) -> bool:
    """B3.1 (fix round 3, C-2/I-2): a registration exists when the external RUN-ACK witnesses it, or when at least
    TWO witnesses exist, one of them beyond an opening in progress. A lone stray file (a fabricated seal, a hand-made
    prereg or registry record) is no registration (B3.2: a refusal); the redundancy means deleting an artifact
    together with its registry record still leaves witnesses. Fix round 4 (N-3, controller ruling on A1/B3.1): one
    of the witnesses must be TIED TO THE OPENING CLOSE (OPENING_TIED: a valid opening seal, opening capture
    evidence, or the RUN-ACK); later-stage files alone (e.g. a hand-made prereg + attest_start pair) are a refusal."""
    w = list(witnesses)
    return "RUN-ACK" in w or (len(w) >= 2 and any(x not in IN_PROGRESS for x in w)
                              and any(x in OPENING_TIED for x in w))


def is_registered(out: Path, mailbox=None, now=None, bundle=None) -> bool:
    """B3.1: whether a registration exists (fix round 8: registration_state - an ACK carrying the bundle, or the
    local witnesses at/after the AUDIT-ACK-derived anchor)."""
    return registration_state(out, mailbox, now, bundle)["registered"]


def _reached(out: Path, w, ack) -> dict:
    """Fix round 3 (C-2): the registered stages reached, each witnessed redundantly: its artifact, either of its two
    records, any later stage, and (attestation) a RUN-ACK binding an attestation, (prereg) a post-START slot claim or
    seal and the later-stage files, (stop) any artifact recording stop.json's hash."""
    import s1_seal                                          # (late import: s1_seal imports this module)
    out = Path(out)

    def has(stage):
        return any(x in w for x in [STAGE_ARTIFACT[stage]] + [p.relative_to(out).as_posix()
                                                              for p in stage_records(out, stage)])
    stop = has("stop") or s1_seal.stop_was_persisted(out)
    prereg = stop or has("prereg") or any(x in w for x in ("post-START capture",) + LATER_FILES[1:])
    attest = prereg or has("attest_start") or (ack is not None and
                                               ack.get("attest_start_sha256") not in (None, ABSENT))
    return {"opening": True, "attest_start": attest, "prereg": prereg, "stop": stop}


def _bound_problems(out: Path, name: str, binds, seal_rel) -> list:
    """The hashes the attestation / prereg record of the artifacts bound before them (a second expected source)."""
    try:
        rec = load_json(Path(out) / name)
    except (OSError, ValueError):
        return [f"{name} unparseable"]
    if not isinstance(rec, dict):
        return [f"{name} unparseable"]
    probs = []
    for key, rel in binds:
        rel = rel or seal_rel
        v = rec.get(key)
        if v in (None, ABSENT) or rel is None:
            continue
        t = Path(out) / rel
        if not t.is_file() or sha256_file(t) != v:
            probs.append(f"{rel} missing or changed (bound by {name} {key})")
    return probs


RUN_ACK_BINDS = (("plan_sha256", "plan.json"), ("audit_manifest_sha256", "audit/manifest.json"),
                 ("attest_start_sha256", "attest_start.json"), ("opening_seal_sha256", None),
                 ("opening_books_sha256", "opening_books.json"))


def _ack_bound_problems(out: Path, st: dict, seal_rel) -> list:
    """Fix round 8 (H-2): the hashes the EXTERNAL ACKs carrying the bundle bound (an expected source no local edit
    reaches): the AUDIT-ACK's plan_sha256 and the RUN-ACK's plan / audit manifest / START attestation / opening seal /
    opening books. A bound artifact matching none of the ACKs naming it (several with the same bundle: any) is a
    problem."""
    out, probs = Path(out), []
    for key, rel, acks in [("plan_sha256", "plan.json", st["audit_acks"])] + [
            (k, r, st["run_acks"]) for k, r in RUN_ACK_BINDS]:
        rel = rel or seal_rel
        want = {f.get(key) for f in acks} - {None, ABSENT}
        if not want or rel is None:
            continue
        if not (out / rel).is_file() or sha256_file(out / rel) not in want:
            probs.append(f"{rel} missing or changed (bound by the external ACK {key})")
    return probs


def registration_problems(out: Path, mailbox=None, now=None) -> list:
    """B3.3: every REQUIRED/BOUND artifact of the registered stages that is missing, changed or unparseable. Fix
    round 3 (C-2): REQUIRED is decided by the redundantly witnessed stage (_reached), not by the presence of that
    stage's own registry record: the opening (plan, audit manifest + its derived files and raw pages, opening receipt,
    opening seal, both opening records), the START attestation (+ opening books, both records), prereg (both
    records), stop.json (its records are optional - stop.json is published first by concurrent deciders - but must
    agree); expected hashes come from either record and from the attestation's / prereg's own bindings; every seal a
    capture report records; and (post-stop) the frozen slices of the persisted stop. Empty before registration.
    Fix round 4: empty before the opening close's first slot (N-3); opening-close evidence left without its records
    (opening_orphans, N-2) is a problem whether or not other witnesses remain - its presence presumes the
    registration happened, so a second opening seal can never be written."""
    out = Path(out)
    st = registration_state(out, mailbox, now)
    if not st["outage"] and not st["audited"]:              # fix round 9 (rule 3 corrected): cannot be registered
        return []
    unbound = []
    if not st["outage"] and not st["plan_bound"]:            # fix round 9 (H-3): the plan names no AUDIT-ACK'd date
        unbound = [f"{x} exists but plan.json differs from every AUDIT-ACK's plan_sha256 (the opening date is unbound)"
                   for x in _local_opening_evidence(out)]
        if not st["registered"]:
            return unbound
    orphans = opening_orphans(out, st["oday"]) if st["local"] else []
    if not st["registered"]:
        return orphans
    w, ack = st["witnesses"], (st["run_acks"] or [None])[0]
    reached = _reached(out, w, ack)
    seal_rel = f"seals/{st['oday']}.json" if st["oday"] else None
    need = {"opening": ["plan.json", "audit/manifest.json", "opening_receipt.json"] + ([seal_rel] if seal_rel else []),
            "attest_start": ["attest_start.json", "opening_books.json"], "prereg": ["prereg.json"],
            "stop": ["stop.json"]}
    probs, opening_recs = [], []
    for stage in REGISTRY_STAGES:
        if not reached[stage]:
            continue
        probs += [f"{rel} missing (required at {stage})" for rel in need[stage] if not (out / rel).is_file()]
        recs = []
        for p in stage_records(out, stage):
            rel = p.relative_to(out).as_posix()
            if not p.exists():
                if stage != "stop":
                    probs.append(f"{rel} missing (stage {stage} is registered)")
                continue
            rec = _registry_record(p)
            if rec is None:
                probs.append(f"{rel} unreadable")
            else:
                recs.append((rel, rec))
        if len(recs) == 2 and recs[0][1]["artifacts"] != recs[1][1]["artifacts"]:
            probs.append(f"{recs[0][0]} and {recs[1][0]} disagree")
        for _, rec in recs:                                  # (a missing one is reported by the REQUIRED list)
            for rel, h in sorted(rec["artifacts"].items()):
                p = out / rel
                if p.is_file() and sha256_file(p) != h:
                    probs.append(f"{rel} changed since {stage}")
        if stage == "opening":
            opening_recs = [rec for _, rec in recs]
            probs += [f"{rel} names {x}, not the opening seal {seal_rel} (fix round 8)" for rel, rec in recs
                      for x in sorted(rec["artifacts"]) if x.startswith("seals/") and x != seal_rel]
    mp = out / "audit" / "manifest.json"
    if opening_recs and mp.is_file() and sha256_file(mp) == opening_recs[0]["artifacts"].get("audit/manifest.json"):
        try:
            m = load_json(mp)
            for n, h in sorted((m.get("files") or {}).items()):
                if not (out / "audit" / n).is_file() or sha256_file(out / "audit" / n) != h:
                    probs.append(f"audit/{n} missing or changed (bound by the audit manifest)")
            for rel, h in sorted((m.get("pages") or {}).items()):
                if not (out / rel).is_file() or sha256_file(out / rel) != h:
                    probs.append(f"{rel} missing or changed (bound by the audit manifest)")
        except (OSError, ValueError, AttributeError) as e:
            probs.append(f"audit/manifest.json unparseable ({type(e).__name__})")
    if reached["attest_start"] and (out / "attest_start.json").is_file():
        probs += _bound_problems(out, "attest_start.json", ATTEST_BINDS, seal_rel)
    if reached["prereg"] and (out / "prereg.json").is_file():
        probs += _bound_problems(out, "prereg.json", PREREG_BINDS, seal_rel)
    for rp, sp, h in _report_seals(out):
        if not sp.is_file() or sha256_file(sp) != h:
            probs.append(f"seals/{sp.name} missing or changed (recorded by capture report {rp.parent.name}/{rp.name})")
    probs += _ack_bound_problems(out, st, seal_rel)
    if reached["stop"]:
        import s1_seal                                       # (late import: s1_seal imports this module)
        try:
            probs += [f"post-stop: {x}" for x in s1_seal.stop_problems(out, None, None, recheck=False)]
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            probs.append(f"post-stop: persisted stop unreadable ({type(e).__name__})")
    return list(dict.fromkeys(probs + orphans + unbound))    # each problem once, in order


def preregistration_problems(out: Path, mailbox=None, now=None) -> list:
    """Fix round 3 (I-2, B3.2): before any registration, files that only a registration produces (a seal file, a
    later-stage artifact or record) are an inconsistent pre-registration state - never a registration: the command
    refuses (preserved), it records no abort. An opening in progress (its two records and its resolution) is
    consistent. Fix round 8: before the AUDIT-ACK-derived anchor (registration_state) EVERY local file - opening
    evidence included - is this inconsistent state."""
    out = Path(out)
    st = registration_state(out, mailbox, now)
    if st["registered"]:
        return []
    w = registration_witnesses(out, st["oday"], False)
    seals = [f"seals/{p.name}" for p in sorted((out / "seals").glob("*.json"))]
    if not st["local"]:
        return w + seals + opening_orphans(out, st["oday"])
    return [x for x in w if x not in IN_PROGRESS] + seals


def _refuse_if_locked(out: Path, where: str) -> None:
    """Fix round 4 (N-1): a stage publication in progress or interrupted (stage.lock) is a preserved refusal."""
    if (Path(out) / STAGE_LOCK).exists():
        raise SystemExit(f"{where} refused: a stage publication is in progress or was interrupted "
                         f"(s1_out/{STAGE_LOCK}): nothing is evaluated until it completes or is inspected")


def registration_gate(out: Path, where: str, now=None, *, refuse: bool = True, mailbox=None) -> list:
    """B3.3: once a registration exists, an observed missing / changed / unparseable REQUIRED artifact records
    sanitized immutable failure evidence and the first-wins aborted.json (reason "registration artifact"; an earlier
    abort keeps its reason); restoration never resumes (aborted.json persists). The command then stops (SystemExit),
    except the two recording commands - the score and the final snapshot (`refuse=False`) - which go on and record the
    trial as ABORTED-INVALID with their own integrity findings (A2.3). The abort records its observation time
    (observed_utc) and no trial end (`actual` None: no capture ended the trial). Fix round 3: a stage
    publication in progress (stage.lock) and an inconsistent pre-registration state (I-2) are preserved refusals,
    never an abort. Fix round 4 (N-1): a violation is CONFIRMED before the abort - stage.lock is re-checked after the
    scan, the state scanned again and the lock checked once more; only the problems seen on both scans with no lock
    at any check are recorded. A lock that appeared, or a violation that vanished, is a preserved refusal (a
    concurrent legitimate stage publication), never an abort. Before the opening close's first slot (N-3) nothing
    is evaluated as a registration: any registration file is a refusal. Returns the problems."""
    out = Path(out)
    _refuse_if_locked(out, where)
    probs = registration_problems(out, mailbox, now=now)           # (empty before the opening, N-3)
    if not probs:
        stray = preregistration_problems(out, mailbox, now)
        if stray and refuse:
            raise SystemExit(f"{where} refused: inconsistent pre-registration state {stray[:4]}: files only a "
                             f"registration produces exist, but no registration is witnessed (B3.2: nothing is "
                             f"registered, nothing is aborted)")
        return []
    _refuse_if_locked(out, where)                            # N-1: a publication began during the scan
    again = registration_problems(out, mailbox, now=now)
    _refuse_if_locked(out, where)
    probs = [x for x in again if x in probs]
    if not probs:
        raise SystemExit(f"{where} refused: the registration state changed during the gate's scan (a concurrent "
                         f"stage publication): the violation was not confirmed - nothing is aborted")
    t = (now or now_utc)()
    write_abort(out, {"reason": REGISTRATION_ARTIFACT, "where": where, "problems": probs, "observed_utc": t.isoformat(),
                      "actual": None, "close": None, "scheduled": None, "projection_sha256": None,
                      "receipt_sha256": None})
    if not refuse:
        return probs
    raise SystemExit(f"{where} refused: registration artifact(s) missing or changed: {probs[:3]}: persistent "
                     f"ABORTED-INVALID (reason {REGISTRATION_ARTIFACT})")
