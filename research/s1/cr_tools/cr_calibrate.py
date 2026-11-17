"""A3 Task 15c-E: the reviewed 15c execution driver - ONE screening config's calibration session (t15c_prep.md
runbook steps 1-4 and 6, without any retry) and, separately, step 5 (derive_cap). Nothing else: no non-calibration
session, no batch other than batch_plan.json["calibration_batch"], no run_retry, no resolve_stop, no resume, no rerun,
no new root.

Location: research/s1/cr_tools/ (this file AND its tests), deliberately OUTSIDE every copy path of every config
(research/s1/*.py - top level only, auto-discovered -, research/s1/docs, research/s1/s1_tests - copied whole -, the
control / argfile). Nothing globs research/s1/cr_tools in, so the 21 pre-flight bindings and the 12 copied maps are
the same with these files present or absent (t15c_e evidence).

Harness (Codex X26 disposition, item 3/4; review m1): the driver imports NO harness module at import time. A
``--src-root`` inside a git checkout or worktree (a .git file or directory at it or at any parent up to the drive
root) is refused first - the retained archive must live outside every git tree. The CLI then imports cr_guard,
cr_reconcile, cr_coord, cr_launch and cr_preflight from <src_root>/research/s1/s1_tests (put first on sys.path)
after its t15c_prep_hashes.txt verifies, refuses if any of them is already imported, and refuses unless every
imported module's file is the src_root's file with the manifest's sha256. What the report states is exactly that:
the src_root realpath, the manifest sha256 and is_git_checkout (it does not otherwise identify "the archive" - that
the src_root IS the retained 30e72bb archive is an operator precondition). The library entry points (session /
derive_cap) refuse the same way; only the test-only ``_test_harness_anywhere`` / ``_test_allow_git_src_root``
(unreachable from the CLI) accept byte-identical modules imported from elsewhere / a src_root inside a git tree.

session (steps 1-4, 6):
 1. src_root: its research/s1/s1_evidence/a3/t15c_prep_hashes.txt must verify (sha256sum -c semantics, in Python);
    the harness is the --src-root's (above).
 2. config = cr_preflight.discover(src_root) screening config <module>[/<shard>]; cfg = config_from_toml;
    identity = config_identity (the cr.toml must render cfg); copy paths = copy_paths_for (runbook step 2).
 3. calibration: the plan's calibration_batch must be the first min(24, kept) kept ids (bound to inventory.json);
    write_manifests(<C>, [calibration_batch]) then run_manifest(..., exec_seam=policy_seam(real_exec(cfg)),
    config=identity, cfg=cfg, preflight_dir=<E>/preflight) in the fresh session root <C>/session-000 (<C> =
    <work_root>/<tag>, which must not exist).
 4. each screening survivor, in calibration order: run_completion over ALL of the module's completion shards, each
    with its own preflight_dir, pool.json, the inventory source pin, on the same session clock. A module with no
    completion shards and no pool.json (journal / locks / trial / stage: whole-module selectors, t15c_prep.md) has
    no completion stage; shards without pool.json, or pool.json without shards, refuse.
 6. a timeout STOPS the session and is reported (Codex X26 disposition item 1): no run_retry, no resolve, no resume
    and no completion retry here - a retry needs its own scoped ruling.
 Policy (Codex X26 disposition item 2): every exec seam is policy_seam(real_exec(cfg)). An item continues ONLY when
 its result is a dict whose reconciled label and guard_status are the same and are killed or survived, exec_status is
 exactly "ok", cleanup_verified is exactly True and raw_timeout is exactly False. Anything else - a missing,
 malformed or unexpected field or value, the canonical "not-installed" (its own halt reason), an alias such as
 "not_installed" (refused, never normalized) - halts BEFORE the next candidate: the raw result is persisted write-once
 as <job_dir>/policy_result.json first; a result run_batch's own _stop_reason already stops on (cleanup, exec status,
 timeout) is returned untouched, any other has only its exec_status set to "policy_halt:<reason>", so run_batch
 records the item's real result and label, quarantines its copy, keeps the rest pending and stops (an ordinary
 unresolved stop: resolve_stop resolves it, by a human). Labels are never changed.
 Stop rules: the session ends, with no further candidate, on any stop of the screening batch (policy halt,
 cleanup_uncertain, exec error / exception, timeout, fence refusal, drift ...), on any completion stop or fence
 refusal, on any coordinator exception, and when the src_root manifest no longer verifies after the session (C6).
 Every outcome writes report_<session>.json (write-once), an interrupt (KeyboardInterrupt / SystemExit, review m3)
 included - stop kind "interrupted", then re-raised: config id, the verified src_root, the harness import, the
 manifest check before and after, labels, completion merged labels, stops, wall times, fence data, the copied-file
 path budget, the pre-flight record shas, the policy and the protocol (C1-C7) - never an environment value.
 Runbook step 6's per-job ``cr-report`` and the a3/t15_cr_<module>.txt consolidation are NOT produced here (review
 n3): they are a manual step from the persisted per-job evidence (jobs/<id>/: session.sqlite, classification, guard
 output, policy_result.json) and the batch state.
 Path budget (review m5, re-review r1-m1): the deepest file of the COPIED TREE - <work>/<tag>/session-000/
 [completion/<job>/<shard>/]quarantine/<job>.<n>/<longest copied rel path> - must not exceed 250 characters; the
 report records it and the longest --work-root it allows. It does NOT bound the files a real job writes under its
 job dir (pytest basetemp, staging output: 167-172 characters below the job dir in the retained real pre-flights,
 absolute paths up to 378), so the host must have long paths enabled: the driver reads
 HKLM\\SYSTEM\\CurrentControlSet\\Control\\FileSystem\\LongPathsEnabled READ-ONLY (never writes it), refuses unless it
 is exactly 1, and records it in the report.
 Order (C1/C7): an earlier screening config (discover order) must have a clean report under the same work root,
 unless --review-ref names the review that allows going on.

derive-cap (step 5): derive_cap on <session-000>/batch_000_state.json -> <C>/derived_cap.json, bound to the identity
the session recorded; only for a session with every calibration item done, no stop and no unresolved stop (C7); it
writes the record only (cap > 24 is never used here).

CLI (by path, with the testenv interpreter and -B; no PYTHONPATH needed - the harness comes from --src-root, which
must not be inside a git tree; use a short --work-root, see the path budget):
    cr_calibrate.py session --src-root R --work-root W --config <module>[/<shard>] [--review-ref REF]
    cr_calibrate.py derive-cap --session-root S --config <module>[/<shard>]
"""
import argparse
import datetime as _dt
import hashlib
import importlib
import json
import sys
import time
from pathlib import Path

LONG_PATHS_KEY = r"SYSTEM\CurrentControlSet\Control\FileSystem"
LONG_PATHS_VALUE = "LongPathsEnabled"

SCHEMA = "a3-t15ce-session/2"
EVID_REL = "research/s1/s1_evidence/cr_a3"
MANIFEST_REL = "research/s1/s1_evidence/a3/t15c_prep_hashes.txt"
HARNESS_REL = "research/s1/s1_tests"
HARNESS_MODULES = ("cr_guard", "cr_reconcile", "cr_coord", "cr_launch", "cr_preflight")

# bound by load_harness (never at import time)
cr_coord = cr_preflight = cr_guard = cr_reconcile = cr_launch = None


class HarnessRefused(RuntimeError):
    """A refusal before the --src-root harness (and so its CoordError) is bound."""


def _refuse(msg: str):
    raise (cr_coord.CoordError if cr_coord is not None else HarnessRefused)(msg)


def _errors() -> tuple:
    return (HarnessRefused,) + ((cr_coord.CoordError,) if cr_coord is not None else ())


def _sha(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


# ------------------------------------------------------------------------------------------------ preconditions
def _manifest_entries(src_root: Path) -> dict:
    m = Path(src_root) / MANIFEST_REL
    if not m.is_file():
        _refuse(f"{m}: no t15c_prep_hashes.txt manifest under the src_root: refused")
    out, bad = {}, []
    for ln in m.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        h, sep, rel = ln.partition("  ")
        rel = rel[1:] if rel.startswith("*") else rel
        if not sep or len(h) != 64 or not rel:
            bad.append(f"malformed line {ln[:80]!r}")
            continue
        out[rel] = h
    if bad or not out:
        _refuse(f"src_root t15c_prep_hashes.txt does not verify ({len(bad)} problems, e.g. {bad[:3]}): refused")
    return out


def verify_manifest(src_root: Path) -> dict:
    """sha256sum -c semantics on <src_root>/research/s1/s1_evidence/a3/t15c_prep_hashes.txt: every line
    '<64 hex>  <relpath>' must name an existing file with that sha256. Any malformed line, missing or differing file
    refuses."""
    entries = _manifest_entries(src_root)
    bad = []
    for rel, h in entries.items():
        p = Path(src_root) / rel
        if not p.is_file():
            bad.append(f"{rel}: missing")
        elif _sha(p) != h:
            bad.append(f"{rel}: FAILED")
    if bad:
        _refuse(f"src_root t15c_prep_hashes.txt does not verify ({len(bad)} problems, e.g. {bad[:3]}): refused")
    return {"path": MANIFEST_REL, "sha256": _sha(Path(src_root) / MANIFEST_REL), "entries": len(entries),
            "verified": True}


def git_checkout_of(path) -> Path | None:
    """The nearest directory, from ``path`` up to the drive root, that holds a .git file or directory (a git checkout
    or worktree), or None."""
    p = Path(path).resolve()
    for d in (p, *p.parents):
        if (d / ".git").exists():
            return d
    return None


def _refuse_git(src_root, marker, allow: bool) -> None:
    if marker is not None and not allow:
        _refuse(f"--src-root {src_root} is inside a git checkout or worktree ({marker / '.git'}): refused - run from "
                f"the retained archive extracted outside every git tree (review m1)")


def load_harness(src_root, *, fresh: bool, _test_harness_anywhere: bool = False,
                 _test_allow_git_src_root: bool = False) -> dict:
    """Bind cr_guard / cr_reconcile / cr_coord / cr_launch / cr_preflight. A src_root inside a git checkout or
    worktree is refused first (unless the test-only ``_test_allow_git_src_root``). ``fresh`` (the CLI): verify the
    src_root manifest, refuse if any of them is already imported, import them from <src_root>/research/s1/s1_tests
    (first on sys.path). Otherwise use the modules already imported (importing any missing one from the src_root).
    Either way, every module's file must carry the src_root manifest's sha256 for research/s1/s1_tests/<name>.py,
    and must BE the src_root's file unless ``_test_harness_anywhere`` (test-only; the CLI cannot pass it)."""
    global cr_coord, cr_preflight, cr_guard, cr_reconcile, cr_launch
    hdir = (Path(src_root) / HARNESS_REL).resolve()
    marker = git_checkout_of(src_root)
    if fresh:
        cr_coord = None                                   # refusals before the harness is bound are HarnessRefused
        _refuse_git(src_root, marker, _test_allow_git_src_root)
        verify_manifest(src_root)
        clash = sorted(m for m in HARNESS_MODULES if m in sys.modules)
        if clash:
            _refuse(f"harness module(s) {clash} are already imported; the driver imports the harness only from the "
                    f"--src-root ({hdir}): refused")
    added = str(hdir) not in sys.path and (fresh or any(m not in sys.modules for m in HARNESS_MODULES))
    if added:
        sys.path.insert(0, str(hdir))
    try:
        mods = {m: importlib.import_module(m) for m in HARNESS_MODULES}
    finally:
        if added and not fresh:                           # library use: leave sys.path as it was
            sys.path.remove(str(hdir))
    cr_coord, cr_preflight, cr_guard = mods["cr_coord"], mods["cr_preflight"], mods["cr_guard"]
    cr_reconcile, cr_launch = mods["cr_reconcile"], mods["cr_launch"]
    _refuse_git(src_root, marker, _test_allow_git_src_root)
    manifest = verify_manifest(src_root)
    entries = _manifest_entries(src_root)
    if tuple(sorted(cr_coord.HARNESS_FILES)) != tuple(sorted(f"{m}.py" for m in HARNESS_MODULES)):
        _refuse(f"the harness file set {cr_coord.HARNESS_FILES} is not the driver's {HARNESS_MODULES}: refused")
    if cr_preflight.EVID_REL != EVID_REL:
        _refuse(f"the harness evidence root {cr_preflight.EVID_REL} is not {EVID_REL}: refused")
    seen = {}
    for m, mod in mods.items():
        f = Path(mod.__file__).resolve()
        want = entries.get(f"{HARNESS_REL}/{m}.py")
        seen[m] = {"path": str(f), "sha256": _sha(f), "src_root": f.parent == hdir}
        if want is None or seen[m]["sha256"] != want:
            _refuse(f"harness module {m} ({f}) is not the bytes the --src-root's t15c_prep_hashes.txt approves: "
                    f"refused")
        if f.parent != hdir and not _test_harness_anywhere:
            _refuse(f"harness module {m} was imported from {f.parent}, not from the --src-root's {hdir}: run the "
                    f"driver by path (the CLI imports the harness from --src-root): refused")
    return {"dir": str(hdir), "modules": seen, "manifest": manifest,
            "pinned_to_src_root": all(v["src_root"] for v in seen.values()),
            "src_root_verified": {"realpath": str(Path(src_root).resolve()), "manifest_sha256": manifest["sha256"],
                                  "is_git_checkout": marker is not None,
                                  "git_marker": str(marker) if marker is not None else None}}


def _conf(src_root: Path, config: str) -> dict:
    rel = f"{EVID_REL}/{config.strip('/')}"
    module = config.strip("/").split("/")[0]
    hits = [c for c in cr_preflight.discover(src_root, modules=[module])
            if c["rel"] == rel and c["kind"] == "screening"]
    if len(hits) != 1:
        _refuse(f"{config} is not a screening config under {src_root}: only a screening config's calibration "
                f"session is driven here")
    return hits[0]


def _calibration(conf: dict) -> tuple:
    d, cap = conf["dir"], cr_coord.BUDGETS["batch_max"]
    inv_p, plan = d / "inventory.json", json.loads((d / "batch_plan.json").read_text(encoding="utf-8"))
    inv = json.loads(inv_p.read_text(encoding="utf-8"))
    kept = [i["job_id"] for i in cr_coord.order_items(
        json.loads((d / "inventory_filtered.json").read_text(encoding="utf-8"))["kept"])]
    cal = list(plan.get("calibration_batch") or [])
    if plan.get("inventory_sha256") != _sha(inv_p):
        _refuse(f"{conf['rel']}: batch_plan.json is not bound to its inventory.json: refused")
    if not cal or len(cal) > cap or cal != kept[:cap]:
        _refuse(f"{conf['rel']}: the calibration_batch is not the first {cap} kept ids: refused (no other batch is "
                f"ever run here)")
    return inv_p, inv, cal


def _shards(src_root: Path, module: str) -> tuple:
    specs = []
    for c in cr_preflight.discover(src_root, modules=[module]):
        if c["kind"] != "completion":
            continue
        cfg = cr_preflight.config_from_toml(c["dir"] / "cr.toml")
        specs.append({"name": c["dir"].name, "cfg": cfg, "copy_paths": cr_preflight.copy_paths_for(src_root, cfg),
                      "preflight_dir": c["dir"] / "preflight"})
    pool = Path(src_root) / EVID_REL / module / "completion" / "pool.json"
    if specs and not pool.is_file():
        _refuse(f"{module}: completion shards without pool.json: refused")
    if not specs and pool.exists():
        _refuse(f"{module}: pool.json without completion shards: refused")
    return specs, pool          # no specs: a whole-module selector (journal / locks / trial / stage), no completion


# ------------------------------------------------------------------------------------- X26: the policy seam
CONTINUE_PAIRS = (("killed", "killed"), ("survived", "survived"))
REQUIRED_FIELDS = ("label", "guard_status", "exec_status", "cleanup_verified", "raw_timeout")
POLICY_DOC = {
    "continues_on": "a dict result whose (label, guard_status) is (killed, killed) or (survived, survived), with "
                    "exec_status exactly 'ok', cleanup_verified exactly True and raw_timeout exactly False",
    "halts_on": "anything else, before the next candidate: missing / malformed / unexpected fields or values, "
                "error, error:*, untested, crash, timeout, the canonical not-installed (own reason), aliases such as "
                "not_installed (refused, not normalized), label/guard disagreement, a non-dict or absent result",
    "mechanism": "the raw result is persisted write-once (<job_dir>/policy_result.json) first; a result run_batch's "
                 "own _stop_reason stops on is returned untouched, any other halting result has only exec_status set "
                 "to 'policy_halt:<reason>' (original kept in result['policy']); run_batch records the real result "
                 "and label, quarantines the copy, keeps the rest pending and stops - an ordinary unresolved stop",
    "no_retry": "timeouts stop; there is no run_retry, resolve_stop, resume or completion retry in this driver",
}


def _safe_repr(o) -> str:
    try:
        return repr(o)
    except Exception as exc:                  # noqa: BLE001 - a record must still be written
        return f"<unrepresentable {type(o).__name__}: {type(exc).__name__}>"


def _encode(obj) -> str:
    """JSON with repr for odd values; if that fails (e.g. a non-str key), JSON of the repr; if even that fails, plain
    text. Never empty."""
    try:
        return json.dumps(obj, indent=1, sort_keys=True, default=repr)
    except Exception as exc:                  # noqa: BLE001
        try:                                  # keep the record's own fields; repr only what does not encode
            if isinstance(obj, dict):
                return json.dumps({(k if isinstance(k, str) else _safe_repr(k)): (v if _jsonable(v) else _safe_repr(v))
                                   for k, v in obj.items()} | {"encode_error": f"{type(exc).__name__}: {exc}"},
                                  indent=1, sort_keys=True)
            return json.dumps({"unencodable": _safe_repr(obj), "encode_error": f"{type(exc).__name__}: {exc}"},
                              indent=1, sort_keys=True)
        except Exception:                     # noqa: BLE001
            return f"UNENCODABLE {_safe_repr(obj)}\n"


def _write_once(path: Path, obj) -> None:
    text = _encode(obj)                       # encoded BEFORE the file exists: never a 0-byte record (review m2)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8") as fh:
        fh.write(text)


def policy_check(result) -> str | None:
    """None when the item may continue; else the canonical halt reason. Field-aware and fail-closed."""
    if not isinstance(result, dict):
        return "malformed_result"
    try:
        json.dumps(result)
    except (TypeError, ValueError):
        return "unserialisable_result"
    for f in REQUIRED_FIELDS:
        if f not in result:
            return f"missing_field:{f}"
    label, guard = result["label"], result["guard_status"]
    if not isinstance(label, str):
        return "malformed_field:label"
    if guard is not None and not isinstance(guard, str):
        return "malformed_field:guard_status"
    if label not in cr_reconcile.LABELS:
        return f"unexpected_label:{label}"
    if result["exec_status"] != "ok":
        return f"exec_status:{result['exec_status']}"
    if result["cleanup_verified"] is not True:
        return f"cleanup_verified:{result['cleanup_verified']!r}"
    if result["raw_timeout"] is not False:
        return f"raw_timeout:{result['raw_timeout']!r}"
    if label == "not-installed":
        return "not-installed"
    if (label, guard) not in CONTINUE_PAIRS:
        return (f"label_guard_mismatch:{label}/{guard}" if label in ("killed", "survived")
                else f"label:{label}/{guard}")
    return None


def _decide(result) -> tuple:
    """(result for run_batch, halt reason or None). Labels and every field are kept; only exec_status changes, and
    only when run_batch would not stop on the result by itself."""
    reason = policy_check(result)
    if not isinstance(result, dict):
        return ({"label": None, "reason": "policy: missing or unparseable result", "guard_status": None,
                 "raw": None, "raw_timeout": False, "exec_status": f"policy_halt:{reason}",
                 "cleanup_verified": False,                # unknown cleanup: run_batch quarantines (cleanup_uncertain)
                 "policy": {"halt": True, "reason": reason, "original_exec_status": None}}, reason)
    if reason == "unserialisable_result":                # the state must stay JSON: values that are not, as repr
        base = {(k if isinstance(k, str) else _safe_repr(k)): (v if _jsonable(v) else _safe_repr(v))
                for k, v in result.items()}
    else:
        base = result
    out = dict(base)
    out["policy"] = {"halt": reason is not None, "reason": reason,
                     "original_exec_status": result.get("exec_status", "<missing>")}
    if reason is not None and cr_coord._stop_reason(base, True) is None:
        out["exec_status"] = f"policy_halt:{reason}"
    return out, reason


def _jsonable(v) -> bool:
    try:
        json.dumps(v)
        return True
    except (TypeError, ValueError):
        return False


def policy_seam(inner):
    """Codex X26: wrap an exec seam (real_exec(cfg) on the real path) so that any result the policy does not accept
    halts the batch BEFORE the next candidate (POLICY_DOC). The raw result is persisted write-once BEFORE the result
    is handed back. The wrapper keeps the inner seam's command tag (run_batch's seam/cfg check still applies), is
    never synthetic, and says what it is (cr_policy_wrapper, .inner) - it does not masquerade as a plain real_exec."""
    def seam(item, copy_root, job_dir):
        rec = Path(job_dir) / "policy_result.json"
        try:
            result = inner(item, copy_root, job_dir)
        except BaseException as exc:          # run_batch records exec_exception + quarantine; we keep the fact
            _write_once(rec, {"job_id": item.get("job_id"), "exception": f"{type(exc).__name__}: {exc}",
                              "halt": True, "reason": "inner_exception"})
            raise
        try:
            out, reason = _decide(result)
        except BaseException as exc:          # the policy itself failed: the raw result is still kept, then halt
            _write_once(rec, {"job_id": item.get("job_id"),
                              "raw": result if isinstance(result, dict) else _safe_repr(result), "halt": True,
                              "reason": "policy_error", "policy_error": f"{type(exc).__name__}: {exc}"})
            raise
        _write_once(rec, {"job_id": item.get("job_id"), "raw": result if isinstance(result, dict) else repr(result),
                          "halt": reason is not None, "reason": reason, "returned_exec_status": out["exec_status"]})
        return out
    seam.inner, seam.cr_policy_wrapper, seam.synthetic = inner, True, False
    seam.cr_real_exec = bool(getattr(inner, "cr_real_exec", False))
    if getattr(inner, "test_command_sha256", None) is not None:
        seam.test_command_sha256 = inner.test_command_sha256
    return seam


PROTOCOL = {
    "C1": "exact calibration ids: the plan's calibration_batch (first 24 kept, bound to inventory.json), in order; one "
          "config per session; an earlier config (discover order) must have a clean report under the work root "
          "unless a --review-ref names the review that allows the next config",
    "C2": "the CLI imports the harness from --src-root (not in a git tree; manifest-verified bytes, its path) and runs "
          "real_exec wrapped only by the explicit policy seam (command tag kept, never synthetic); the driver's own "
          "sha256 is in every report",
    "C3": "one session root per config (session-000), completion on the same session clock (run_completion "
          "session_root), run_batch's HARD fence (405 s) per candidate; a fence refusal is reported, never resumed",
    "C4": "only screening survivors go to completion, over ALL the module's shards (full pool via run_completion); "
          "whole-module selectors have none; no completion retry",
    "C5": "stop on the first stop / timeout / cleanup uncertainty / drift / exception / policy halt; never "
          "run_retry, never resolve_stop, never resume, never rerun, never a new root",
    "C6": "raw results persisted (run_batch job dirs + policy_result.json, write-once, before the halt), state / "
          "binding / pre-flight refs and measured item costs in the report, the src_root manifest verified before "
          "AND after the session",
    "C7": "one report per session; derive-cap only on a session with all its calibration items done, no stop and "
          "no unresolved stop; no non-calibration batch exists in this driver",
}


# ---------------------------------------------------------------------------------------------- stop analysis
def _kind(reason: str | None) -> str:
    r = str(reason or "")
    if r.startswith(("session_budget", "session_clock_invalid")):
        return "fence"
    if r.startswith("cleanup_uncertain"):
        return "cleanup_uncertain"
    if r.startswith("timeout"):
        return "timeout"
    if r.startswith("policy_halt"):
        return "policy_halt"
    if r.startswith(("exec_exception", "error")):
        return "error"
    return "unresolved_stop"


def _completion_stop(rec: dict) -> dict | None:
    if rec.get("refused"):                    # a shard state without the job's label: a fence refusal or an exception
        reason = rec["refused"][0].get("stop_reason")
        return {"kind": _kind(reason), "detail": f"completion shard not labelled: {rec['refused']}"}
    for a in rec.get("attempts", []):
        if a.get("stopped"):
            return {"kind": _kind(a.get("stop_reason")), "detail": f"completion stop {a.get('stop_reason')}"}
    if rec.get("pending_shards"):
        return {"kind": "unresolved_stop", "detail": f"completion pending {rec['pending_shards']}"}
    return None


def _state_view(st: dict, path: Path) -> dict:
    return {"state": str(path), "state_sha256": _sha(path) if path.is_file() else None,
            "labels": st.get("labels"), "stopped": st.get("stopped"), "stop_reason": st.get("stop_reason"),
            "done": st.get("done"), "pending": st.get("pending"), "item_s": st.get("item_s"),
            "fence_s": st.get("fence_s"), "io_margin_s": st.get("io_margin_s"),
            "session_started": st.get("session_started"), "session_root": st.get("session_root"),
            "preflight": st.get("preflight")}


def _completion_view(rec: dict, croot: Path) -> dict:
    recs = sorted(croot.glob("completion_record*.json"), key=lambda p: p.stat().st_mtime_ns)
    return {"label": rec.get("label"), "resolution": rec.get("resolution"),
            "pending_shards": rec.get("pending_shards"), "not_run": rec.get("not_run"),
            "refused": rec.get("refused"), "record": str(recs[-1]) if recs else None,
            "record_sha256": _sha(recs[-1]) if recs else None, "preflights": rec.get("preflights"),
            "attempts": [{k: a.get(k) for k in ("shard", "attempt_batch", "label", "guard_status", "exec_status",
                                                "stopped", "stop_reason", "state_sha256")} for a in
                         rec.get("attempts", [])]}


# ------------------------------------------------------------------------------------------------------ session
def session(src_root, work_root, config: str, *, clock=time.monotonic, review_ref: str | None = None,
            _test_exec_factory=None, _test_harness_anywhere: bool = False,
            _test_allow_git_src_root: bool = False, _test_long_paths_reader=None) -> dict:
    """One calibration session. See the module docstring. ``_test_exec_factory`` and ``_test_harness_anywhere`` are
    TEST-ONLY (the CLI cannot pass them); the real path is real_exec with the --src-root harness."""
    t0 = time.monotonic()
    src_root, work_root = Path(src_root), Path(work_root)
    harness = load_harness(src_root, fresh=False, _test_harness_anywhere=_test_harness_anywhere,
                           _test_allow_git_src_root=_test_allow_git_src_root)
    base_factory = _test_exec_factory or cr_coord.real_exec

    def factory(c):                          # X26: every seam is the policy seam over real_exec(c)
        return policy_seam(base_factory(c))
    conf = _conf(src_root, config)
    cfg = cr_preflight.config_from_toml(conf["dir"] / "cr.toml")
    cfg_id = conf["rel"][len(EVID_REL) + 1:]
    identity = cr_coord.config_identity(cfg, conf["dir"] / "cr.toml", config_id=cfg_id)
    cp = cr_preflight.copy_paths_for(src_root, cfg)
    inv_p, inv, cal = _calibration(conf)
    items_by_id = {i["job_id"]: i for i in inv["items"]}
    pin = {inv["module_rel"]: inv["source_sha256"]}
    shards, pool = _shards(src_root, conf["module"])
    croot = work_root / cfg_id.replace("/", "__")
    budget = _path_budget(src_root, work_root, croot, items_by_id, cp, shards)
    host = _host_check(_test_long_paths_reader or _read_long_paths)
    order = _check_order(src_root, work_root, conf, review_ref)
    if croot.exists():
        _refuse(f"config root {croot} already exists: one fresh session root per session (no rerun, no retry, no "
                f"resume, no new root)")
    croot.mkdir(parents=True)
    sroot = croot / "session-000"
    rep = {"schema": SCHEMA, "kind": "calibration", "config_id": cfg_id, "src_root": str(src_root),
           "work_root": str(work_root), "config_root": str(croot), "session_root": str(sroot),
           "manifest": harness["manifest"], "src_root_verified": harness["src_root_verified"],
           "harness": {k: harness[k] for k in ("dir", "modules", "pinned_to_src_root")},
           "driver_sha256": _sha(__file__),
           "identity": {k: identity[k] for k in ("config_id", "module_rel", "test_command_sha256", "cr_toml_sha256")},
           "calibration_batch": cal, "screening": None, "completions": {}, "stop": None,
           "path_budget": budget, "host": host, "review_ref": review_ref, "order": order,
           "policy": POLICY_DOC, "protocol": PROTOCOL,
           "completion_stage": (f"{len(shards)} shards: {[s['name'] for s in shards]}" if shards
                                else "none: whole-module selector"),
           "started_at": _now()}
    try:
        (man,) = cr_coord.write_manifests(croot, [cal], _sha(inv_p))
        try:
            st = cr_coord.run_manifest(man, inv_p, src_root=src_root, copy_paths=cp, work_root=sroot,
                                       exec_seam=factory(cfg), clock=clock, config=identity, cfg=cfg,
                                       preflight_dir=conf["dir"] / "preflight")
        finally:
            sp = sroot / "batch_000_state.json"
            if sp.is_file():
                rep["screening"] = _state_view(json.loads(sp.read_text(encoding="utf-8")), sp)
        if st.get("stopped"):
            reason = st.get("stop_reason") or ""
            rep["stop"] = {"kind": _kind(reason), "detail": f"calibration batch stopped: {reason}"}
        survivors = ([j for j in cal if st["labels"].get(j) == "survived"] if shards else []) \
            if rep["stop"] is None else []
        for job in survivors:                 # a whole-module selector: the screening label is final (t15c_prep.md)
            rec = cr_coord.run_completion(job, items_by_id, shards, pool_path=pool, src_root=src_root, work_root=sroot,
                                          exec_factory=factory, session_root=sroot, source_sha256=pin, clock=clock)
            rep["completions"][job] = _completion_view(rec, sroot / "completion" / job)
            stop = _completion_stop(rec)
            if stop:
                rep["stop"] = dict(stop, job=job)
                break
    except Exception as exc:                  # noqa: BLE001 - any coordinator exception ends the session, recorded
        rep["stop"] = {"kind": "exception", "detail": f"{type(exc).__name__}: {exc}"}
    except BaseException as exc:              # review m3: KeyboardInterrupt / SystemExit - report it, then re-raise
        rep["stop"] = {"kind": "interrupted", "detail": f"{type(exc).__name__}: {exc}"}
        try:
            _finish(rep, croot, sroot, t0)
        except BaseException as fin:          # re-review r1-n1: never mask the interrupt; keep the failure as a note
            exc.add_note(f"interrupted-report write failed: {type(fin).__name__}: {fin}")
        raise
    return _finish(rep, croot, sroot, t0)


def _read_long_paths(_winreg=None):
    """HKLM\\...\\FileSystem\\LongPathsEnabled, opened READ-ONLY (KEY_READ); None when the value is absent. This
    driver never writes the registry. ``_winreg`` is for tests (a fake module); the real one is imported here."""
    w = _winreg if _winreg is not None else importlib.import_module("winreg")
    with w.OpenKey(w.HKEY_LOCAL_MACHINE, LONG_PATHS_KEY, 0, w.KEY_READ) as key:
        try:
            return w.QueryValueEx(key, LONG_PATHS_VALUE)[0]
        except FileNotFoundError:
            return None


def _host_check(reader) -> dict:
    """Re-review r1-m1: job-dir files outgrow any work-root budget, so long paths must be on. Fail closed."""
    try:
        value = reader()
    except Exception as exc:                  # noqa: BLE001 - unreadable is not 1
        value = f"unreadable ({type(exc).__name__}: {exc})"
    if type(value) is not int or value != 1:
        _refuse(f"host LongPathsEnabled is {value!r}, not 1: refused - real jobs write files far below their job "
                f"dir (absolute paths up to ~380 characters); enable long paths first")
    return {"long_paths_enabled": value, "registry": f"HKLM\\{LONG_PATHS_KEY}\\{LONG_PATHS_VALUE}"}


PATH_BUDGET = 250                             # review m5: the deepest copied FILE, not only the child's cwd


def _path_budget(src_root: Path, work_root: Path, croot: Path, job_ids, copy_paths, shards) -> dict:
    """The deepest file of the COPIED TREE (not the job dirs - see the module docstring): run_batch copies to
    <root>/copies/<job> and moves a stopped copy to <root>/quarantine/<job>[.<n>] (the deeper of the two), <root>
    being session-000 for screening and session-000/completion/<job>/<shard> for each completion shard; below it sits
    every copied file
    (cr_coord.copied_map of that config's copy paths). Refuse past PATH_BUDGET; report the longest --work-root."""
    j = "x" * max(len(str(x)) for x in job_ids)
    s0 = Path(croot).resolve() / "session-000"

    def longest(paths) -> int:
        return max(len(r) for r in cr_coord.copied_map(src_root, paths))
    deep = [len(str(s0 / "quarantine" / f"{j}.99")) + 1 + longest(copy_paths)]
    deep += [len(str(s0 / "completion" / j / s["name"] / "quarantine" / f"{j}.99")) + 1 + longest(s["copy_paths"])
             for s in shards]
    worst = max(deep)
    max_wr = PATH_BUDGET - (worst - len(str(Path(work_root).resolve())))
    if worst > PATH_BUDGET:
        _refuse(f"the work root is too long: the deepest copied file would sit at a {worst}-character path "
                f"(> {PATH_BUDGET}); use a --work-root of at most {max_wr} characters")
    return {"deepest_copied_file_chars": worst, "limit": PATH_BUDGET, "max_work_root_chars": max_wr,
            "measures": "copied tree only (quarantine/<job>.<n>/<copied rel path>); files a job writes under its "
                        "job dir go deeper and rely on LongPathsEnabled = 1 (host check)"}


def _check_order(src_root: Path, work_root: Path, conf: dict, review_ref) -> dict:
    """C1 / C7: one config at a time in discover order - every earlier screening config must have a clean latest
    report under this work root, unless review_ref names the review that allows going on."""
    mods = list(cr_preflight.MODULES) if conf["module"] in cr_preflight.MODULES else [conf["module"]]
    screens = [c for c in cr_preflight.discover(src_root, mods) if c["kind"] == "screening"]
    earlier = screens[:[c["rel"] for c in screens].index(conf["rel"])]
    status = {}
    for c in earlier:
        cid = c["rel"][len(EVID_REL) + 1:]
        reps = sorted((work_root / cid.replace("/", "__")).glob("report_session-*.json"),
                      key=lambda q: q.stat().st_mtime_ns)
        last = json.loads(reps[-1].read_text(encoding="utf-8")) if reps else None
        status[cid] = "clean" if last is not None and last.get("stop") is None else "missing or stopped"
        if status[cid] != "clean" and not (review_ref or "").strip():
            _refuse(f"earlier config {cid} has no clean calibration report under {work_root}: one config at a time "
                    f"in discover order, and a stop needs review (--review-ref) before the next config (C1/C7)")
    return {"earlier": status, "review_ref": review_ref}


def _finish(rep: dict, croot: Path, sroot: Path, t0: float) -> dict:
    try:                                      # C6: the source tree is re-verified after the session
        rep["manifest_after"] = verify_manifest(Path(rep["src_root"]))
    except _errors() as exc:
        rep["manifest_after"] = {"verified": False, "error": str(exc)}
        if rep.get("stop") is None:
            rep["stop"] = {"kind": "manifest_changed", "detail": str(exc)}
        else:
            rep["stop"]["manifest_changed"] = True
    rep["finished_at"], rep["wall_s"] = _now(), round(time.monotonic() - t0, 3)
    out = croot / f"report_{sroot.name}.json"
    with open(out, "x", encoding="utf-8") as fh:                     # write-once
        fh.write(json.dumps(rep, indent=1, sort_keys=True))
    return rep


# --------------------------------------------------------------------------------------------------- derive-cap
def derive_cap(session_root, config: str, *, _test_harness_anywhere: bool = False,
               _test_allow_git_src_root: bool = False) -> dict:
    """Runbook step 5: derive_cap on <session-000>/batch_000_state.json, bound to the identity the session recorded
    (its cr.toml must still render the config; the src_root manifest and its harness must still verify)."""
    sroot = Path(session_root)
    rep = json.loads((sroot.parent / f"report_{sroot.name}.json").read_text(encoding="utf-8"))
    load_harness(Path(rep["src_root"]), fresh=False, _test_harness_anywhere=_test_harness_anywhere,
                 _test_allow_git_src_root=_test_allow_git_src_root)
    state = sroot / "batch_000_state.json"
    s = json.loads(state.read_text(encoding="utf-8"))
    cid = (s.get("config") or {}).get("config_id")
    if cid != config.strip("/"):
        _refuse(f"session {sroot} is not a calibration session of {config} (it is {cid})")
    if (s.get("stopped") or s.get("pending") or len(s.get("done") or []) != len(s.get("batch") or [])
            or rep.get("stop") is not None or cr_coord.unresolved_stops(sroot)):        # C7
        _refuse(f"derive-cap needs a calibration session that ended without a stop, with every calibration item "
                f"done and no unresolved stop ({sroot})")
    cr_toml = Path(s["config"]["cr_toml"])
    cfg = cr_preflight.config_from_toml(cr_toml)
    identity = cr_coord.config_identity(cfg, cr_toml, config_id=cid)
    return cr_coord.derive_cap(state, out=sroot.parent / "derived_cap.json", identity=identity)


# ---------------------------------------------------------------------------------------------------------- CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="cr_calibrate.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("session", help="one screening config's calibration session (runbook steps 1-4, 6; no retry)")
    a.add_argument("--src-root", required=True, type=Path)
    a.add_argument("--work-root", required=True, type=Path)
    a.add_argument("--config", required=True)
    a.add_argument("--review-ref", default=None,
                   help="the review that allows the next config after an earlier one stopped (C1/C7)")
    d = sub.add_parser("derive-cap", help="runbook step 5 on a finished calibration session")
    d.add_argument("--session-root", required=True, type=Path)
    d.add_argument("--config", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "session":
        load_harness(args.src_root, fresh=True)                       # the --src-root's harness, pinned
        rep = session(args.src_root, args.work_root, args.config, review_ref=args.review_ref)
        print(json.dumps({"stop": rep.get("stop"), "report": rep.get("config_root")}, sort_keys=True))
        return 0 if rep.get("stop") is None else 1
    src = json.loads((args.session_root.parent / f"report_{args.session_root.name}.json")
                     .read_text(encoding="utf-8"))["src_root"]
    load_harness(Path(src), fresh=True)
    rec = derive_cap(args.session_root, args.config)
    print(json.dumps({"derived_cap": rec.get("derived_cap"), "max_item_s": rec.get("max_item_s")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
