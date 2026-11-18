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
 3. calibration: batch_plan.json must stay bound to inventory.json; the calibration ids are the EXTERNAL plan v2's
    (15c-P2 below), not batch_plan.json's first 24;
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
writes the record only (cap > 24 is never used here). 15c-P2: and only with at least one clean killed / survived
measurement (no cap from import errors alone). Fix round 2 (review M6): import-invalid candidates are NOT calibration
measurements - the cap comes from a write-once <C>/cap_measurements.json (the state minus those ids, bound to the
state's sha256) that records each excluded id with its item and diagnostic cost. Fix round 3: an id is excluded only
when its dg/disposition.json is present with the sha256 the session recorded (N4); the measurement set is re-checked
against the state sha it records (N5); and derive-cap REFUSES below the plan bound cap_min_measurements (24 =
batch_max, R1, pending a peer ruling; validate_plan accepts any int in 1..24 there, so a ruling changes the plan only).

15c-P2 (Codex PROVENANCE_P_RULING, design P; Claude amendments A1-A4; policy POLICY_VERSION, report schema SCHEMA):
 * The calibration ids come from the EXTERNAL sampling plan v2 (plans/sampling_v2.json, built by build_sampling_v2.py,
   default PLAN_PATH; the CLI cannot choose another). validate_plan refuses on any binding mismatch: schema /
   version / algorithm revision, this driver's and the probe's raw-byte sha256 and the policy version, the AST
   classifier version + source sha256, the bounds, the src_root manifest sha256 + entry count, every pre-flight
   record hash + the record-list sha256, the config's inventory raw + filtered sha256, its source, its kept count and
   order (== cr_coord.order_items), its strata counts / allocations, its calibration batch and eligible ids
   (RECOMPUTED with the pure functions below), the universe total and eligible total, and the predecessor halt
   root's file hashes; the work root must be the plan's planned root and never the predecessor root (no reuse).
 * Eligibility: only the plan's exact eligible ids of THIS config (import / definition-time stratum, screening).
   Runtime-stratum ids and every completion-stage error halt exactly as before.
 * P2 admission: before an eligible item's original CR execution starts, the parent session clock (session.json, the
   same clock run_batch uses) must leave admission_reservation_s() = 405 + 2 * (60 + 45 + 15) = 645 s, else a
   durable fence stop (policy_result.json, no CR call, no next candidate). Non-eligible items keep run_batch's 405 s.
 * Qualifying (qualify): the canonical error / error:collection result with exec ok, cleanup verified, no raw
   timeout, AND the trusted guard records bound to this job / attempt / sidecar (guard.json by the reviewed guard,
   one attempt dir, nodes.json by sha256, classification.json) showing selected == [] and phases == {} (no call, no
   internal error, the target never finished importing) with one consistent collection-error class. Else: halt as
   before (the reason says why it did not qualify).
 * The diagnosis pair (A3), each child through cr_guard.run_contained with the bound _env, a 60 s deadline and
   verified cleanup, on a fresh copy made with the original copy semantics (make_copy; the tree must be the original
   attempt's): child 1 imports the UNMUTATED target (cr_import_probe.py control) and must import clean with the
   pinned source identity - else HALT and child 2 never starts; child 2 (mutated) applies the exact MutationSpec
   through Cosmic Ray's pinned operator API inside the child, VALIDATES the pinned source identity and exactly one
   localized change inside the item's span BEFORE importing (fix round 1, A3 as amended: on failure it writes a
   structured refusal and never imports), persists that pre-import record, then imports. The parent independently
   re-verifies the persisted bytes / hashes / diff / span (localize, _check_preimport) and the structural gate
   (gate: innermost frame in the target at the mutation's actual AST context, exact column overlap, fail closed).
   Both children get the pinned sha256 and the protected paths (PROTECTED_PATHS, checked against the src_root's S1
   constants by AST) and run under the identical barrier - a cooperative child-local audit hook, NOT an OS sandbox;
   any refusal HALTS on its own recorded reason. The probe context matches the selected import path / env facts, not
   identical pytest initialization (PROBE_SCOPE). Pass: the item continues with write-once
   dg/disposition.json and driver_disposition import-invalid-candidate (NONKILL); label, guard_status and the raw CR
   outcome are unchanged. Any failure: HALT before the next candidate (policy_halt:diagnosis:<why>), records kept.
 * The report adds the plan summary, the probe sha256, the bounds and per-item / per-stratum accounting (screening
   CR seconds, diagnostic seconds, probe / no probe, the import-invalid candidates listed on their own).

CLI (by path, with the testenv interpreter and -B; no PYTHONPATH needed - the harness comes from --src-root, which
must not be inside a git tree; use a short --work-root, see the path budget):
    cr_calibrate.py session --src-root R --work-root W --config <module>[/<shard>] [--review-ref REF]
    cr_calibrate.py derive-cap --session-root S --config <module>[/<shard>]
"""
import argparse
import ast
import datetime as _dt
import hashlib
import importlib
import inspect
import json
import re
import sys
import time
import tokenize
from pathlib import Path

LONG_PATHS_KEY = r"SYSTEM\CurrentControlSet\Control\FileSystem"
LONG_PATHS_VALUE = "LongPathsEnabled"

SCHEMA = "a3-t15ce-session/3"                 # 15c-P2: the external plan v2 + the import-invalid diagnosis
EVID_REL = "research/s1/s1_evidence/cr_a3"
MANIFEST_REL = "research/s1/s1_evidence/a3/t15c_prep_hashes.txt"
HARNESS_REL = "research/s1/s1_tests"
HARNESS_MODULES = ("cr_guard", "cr_reconcile", "cr_coord", "cr_launch", "cr_preflight")

# ---- 15c-P2 (Codex PROVENANCE_P_RULING + Claude amendments A1-A4) -----------------------------------------------
POLICY_VERSION = "a3-t15cp2-policy/1"
PLAN_SCHEMA = "a3-t15cp2-sampling/2"
ALGORITHM_REVISION = "two-strata-midpoint/1"
CLASSIFIER_VERSION = "body-position/1"
PROBE_SCHEMA = "a3-t15cp2-probe/2"           # fix round 1: pre-import validation + amended A2 barrier
# fix round 1 (A2 as amended): protected data the probe may not even READ - (path, source rel, constant name). The
# paths restate the S1 constants; protected_paths() checks them against the src_root source by AST (never imports).
PROTECTED_PATHS = (
    ("C:/Users/gl450/.coordination/trading_app/mailbox.sqlite3", "research/s1/s1_common.py", "MAILBOX"),
    ("C:/Users/gl450/.coordination/trading_app/s1_receipt_hmac.key", "research/s1/s1_receipt.py", "HMAC_KEY"),
    ("C:/Users/gl450/trading_app/backend/trading.db", "research/s1/s1_checkpoint.py", "LIVE_DB"),
)
PROBE_SCOPE = ("probe context matches the selected import path / environment facts of the guard's pytest child "
               "(conftest sys.path prefix order, cwd, bound env); NOT identical pytest initialization (no pytest, "
               "plugins, conftest pytest_configure, fixtures or original test-module import order); the probe loads "
               "sqlite3, ctypes and ctypes.wintypes (and Cosmic Ray) before the target in both modes, so the set of "
               "modules present before the import differs from collection (fix round 4, m4)")
TOOLS_DIR = Path(__file__).resolve().parent
PLAN_PATH = TOOLS_DIR / "plans" / "sampling_v2.json"
PROBE_PATH = TOOLS_DIR / "cr_import_probe.py"
DISPOSITION = "import-invalid-candidate"
CANON_ERROR = "label:error/error:collection"
SAMPLE_SIZE = 24
# The reviewed harness's budgets, restated so the plan builder never imports the harness; session() refuses unless
# the bound harness has exactly these values (cr_coord.fence_s(), BUDGETS).
SESSION_LENGTH_S = 10800
ORIGINAL_FENCE_S = 405.0                      # cr_coord.fence_s(): 300 + 45 + 45 + 15
CLEANUP_RESERVE_S = 45
PROBE_DEADLINE_S = 60                         # each diagnosis child (cr_guard.run_contained deadline)
DIAG_IO_MARGIN_S = 15                         # per child: fresh copy, hashing, record I/O
MAX_DIAG_CHILDREN = 2                         # 1 unmutated control + 1 mutated import, no retries
CAP_MIN_MEASUREMENTS = 24                     # fix round 3 (R1): = BUDGETS["batch_max"], pending a peer ruling
PROBE_PREFIX = ("research/s1/s1_tests", "research/s1", ".")     # A1: conftest inserts + the child's cwd


def diagnosis_child_s() -> float:
    return float(PROBE_DEADLINE_S + CLEANUP_RESERVE_S + DIAG_IO_MARGIN_S)


def diagnosis_reserve_s() -> float:
    """P2: what both diagnosis children may cost at most (2 * (60 + 45 + 15) = 240 s)."""
    return MAX_DIAG_CHILDREN * diagnosis_child_s()


def admission_reservation_s() -> float:
    """P2: an ELIGIBLE item starts only with at least the original fence plus both children left (645 s)."""
    return ORIGINAL_FENCE_S + diagnosis_reserve_s()


def expected_bounds() -> dict:
    return {"session_length_s": SESSION_LENGTH_S, "original_fence_s": ORIGINAL_FENCE_S,
            "probe_child_deadline_s": PROBE_DEADLINE_S, "cleanup_reserve_s": CLEANUP_RESERVE_S,
            "diag_io_margin_s": DIAG_IO_MARGIN_S, "max_children_per_item": MAX_DIAG_CHILDREN,
            "diagnosis_reserve_s": diagnosis_reserve_s(), "admission_reservation_s": admission_reservation_s(),
            "non_eligible_fence_s": ORIGINAL_FENCE_S,
            # fix round 3 (R1): derive-cap refuses below this many clean killed / survived measurements; the one
            # bound a later peer ruling may change in the plan alone (validate_plan: an int in 1..SAMPLE_SIZE)
            "cap_min_measurements": CAP_MIN_MEASUREMENTS,
            "rule": "admission = original fence + max_children * (child deadline + cleanup reserve + IO margin); "
                    "same parent session clock; a proposed reservation, not a measured timing guarantee"}

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
    """The config's inventory (bound to its batch_plan.json, which stays unchanged at 30e72bb). 15c-P2: the
    calibration ids are NOT batch_plan.json's first 24 any more - they come from the external sampling plan v2
    (validate_plan), which session() checks against these same files."""
    d = conf["dir"]
    inv_p, plan = d / "inventory.json", json.loads((d / "batch_plan.json").read_text(encoding="utf-8"))
    inv = json.loads(inv_p.read_text(encoding="utf-8"))
    if plan.get("inventory_sha256") != _sha(inv_p):
        _refuse(f"{conf['rel']}: batch_plan.json is not bound to its inventory.json: refused")
    return inv_p, inv


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


# ------------------------------------------------------------------- 15c-P2: strata, selection (sampling plan v2)
# Pure functions (no harness): the plan builder (build_sampling_v2.py) uses exactly these, and validate_plan
# recomputes the plan with them. Their source sha256 is bound into the plan (classifier.source_sha256).
def runtime_ranges(src: str) -> list:
    """Body-position classifier: every def's BODY (its first body statement's start to the def's end) and every
    lambda's body, as ((line, col), (end_line, end_col)) - inclusive."""
    out = []
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            b = n.body[0]
            out.append(((b.lineno, b.col_offset), (n.end_lineno, n.end_col_offset)))
        elif isinstance(n, ast.Lambda):
            b = n.body
            out.append(((b.lineno, b.col_offset), (b.end_lineno, b.end_col_offset)))
    return out


def stratum(start, ranges) -> str:
    """"runtime" iff the mutation START lies inside a def or lambda body; else "import" (import / definition time:
    module scope, class bodies, def headers, defaults, decorators, annotations)."""
    pos = (int(start[0]), int(start[1]))
    return "runtime" if any(a <= pos <= b for a, b in ranges) else "import"


def allocate(n_imp: int, n_tot: int, size: int = SAMPLE_SIZE) -> tuple:
    """(import, runtime) sample sizes: proportional nearest integer (size*N_import + N//2) // N, at least 1 per
    non-empty stratum (so at most size-1 for either when both are non-empty), bounded by stratum capacity; a pool of
    at most ``size`` is taken whole."""
    n_run = n_tot - n_imp
    if n_imp == 0:
        return 0, min(size, n_tot)
    if n_run == 0:
        return min(size, n_tot), 0
    k = (size * n_imp + n_tot // 2) // n_tot
    k = max(1, min(k, size - 1, n_imp))
    r = min(size - k, n_run)
    return min(n_imp, size - r), r


def midpoints(seq: list, n: int) -> list:
    """Midpoint quantiles: seq[floor((2j+1) N / (2n))] for j = 0..n-1 (integer floor, no randomness)."""
    big_n = len(seq)
    return [seq[(2 * j + 1) * big_n // (2 * n)] for j in range(n)] if n else []


def select_calibration(kept_ids: list, strata: dict, size: int = SAMPLE_SIZE) -> tuple:
    """(calibration batch in original kept order, eligible = its import-stratum ids, allocation)."""
    imp = [j for j in kept_ids if strata[j] == "import"]
    run = [j for j in kept_ids if strata[j] == "runtime"]
    ki, kr = allocate(len(imp), len(kept_ids), size)
    chosen = set(midpoints(imp, ki)) | set(midpoints(run, kr))
    batch = [j for j in kept_ids if j in chosen]
    return batch, [j for j in batch if strata[j] == "import"], {"import": ki, "runtime": kr}


def kept_order_key(item: dict) -> tuple:
    """cr_coord.order_items' key without a priority (restated for the builder; session() cross-checks it)."""
    return (str(item["module_path"]).replace("\\", "/"), tuple(item["start"]), tuple(item["end"]), item["operator"],
            item["occurrence"], item["job_id"])


def classifier_source_sha256() -> str:
    src = "".join(inspect.getsource(f) for f in (runtime_ranges, stratum, allocate, midpoints, select_calibration,
                                                 kept_order_key))
    return hashlib.sha256(src.encode("utf-8")).hexdigest()


def read_source(path) -> str:
    """Decoded like Cosmic Ray's read_python_source (tokenize.open: PEP 263 encoding, universal newlines)."""
    with tokenize.open(str(path)) as fh:
        return fh.read()


def render_record_list(records: dict) -> bytes:
    """The a3/t15c_preflight_records_sha256.txt format ('<sha256> *<rel>' per line, LF), in the plan's order."""
    return "".join(f"{h} *{rel}\n" for rel, h in records.items()).encode("utf-8")


def _json_sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj).encode("utf-8")).hexdigest()


def config_strata(src_root: Path, conf_rel: str) -> dict:
    """Recompute one config's plan entry from its files (AST parse only)."""
    d = Path(src_root) / EVID_REL / conf_rel
    inv_p, filt_p = d / "inventory.json", d / "inventory_filtered.json"
    inv = json.loads(inv_p.read_text(encoding="utf-8"))
    kept = json.loads(filt_p.read_text(encoding="utf-8"))["kept"]
    ids = [i["job_id"] for i in kept]
    src_p = Path(src_root) / inv["module_rel"]
    ranges = runtime_ranges(read_source(src_p))
    strata = {i["job_id"]: stratum(i["start"], ranges) for i in kept}
    batch, eligible, alloc = select_calibration(ids, strata)
    return {"config": conf_rel, "inventory_sha256": _sha(inv_p), "filtered_sha256": _sha(filt_p),
            "module_rel": inv["module_rel"], "source_sha256": _sha(src_p), "kept_count": len(ids),
            "kept_order_sha256": _json_sha(ids),
            "kept_sorted_like_order_items": ids == [i["job_id"] for i in sorted(kept, key=kept_order_key)],
            "strata": {s: {"count": sum(1 for j in ids if strata[j] == s), "allocation": alloc[s]}
                       for s in ("import", "runtime")},
            "calibration_batch": batch, "eligible": eligible,
            "preflight": {p.relative_to(src_root).as_posix(): _sha(p) for p in sorted((d / "preflight").glob("*.json"))}}


def _plan_refuse(path, what: str):
    _refuse(f"sampling plan {path}: {what}: refused")


def validate_plan(plan_path, src_root, config_id: str) -> tuple:
    """15c-P2: load the EXTERNAL sampling plan v2 and refuse on any hash / binding mismatch (Codex ruling, plan-v2
    binding fields). Returns (plan, its config entry, summary)."""
    p = Path(plan_path)
    if not p.is_file():
        _plan_refuse(p, "missing")
    raw = p.read_bytes()
    try:
        plan = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        _plan_refuse(p, f"unreadable ({exc})")
    if not isinstance(plan, dict) or plan.get("schema") != PLAN_SCHEMA or plan.get("plan_version") != 2:
        _plan_refuse(p, f"schema is not {PLAN_SCHEMA} version 2")
    if plan.get("algorithm_revision") != ALGORITHM_REVISION:
        _plan_refuse(p, f"algorithm revision is not {ALGORITHM_REVISION} (schema)")
    drv = plan.get("driver") or {}
    if drv.get("sha256") != _sha(__file__):
        _plan_refuse(p, "it binds another driver (driver sha256)")
    if drv.get("policy_version") != POLICY_VERSION or drv.get("schema") != SCHEMA:
        _plan_refuse(p, f"driver policy version / report schema is not {POLICY_VERSION} / {SCHEMA}")
    prb = plan.get("probe") or {}
    if not PROBE_PATH.is_file() or prb.get("sha256") != _sha(PROBE_PATH) or prb.get("schema") != PROBE_SCHEMA:
        _plan_refuse(p, "it binds another import probe (probe sha256 / schema)")
    cls = plan.get("classifier") or {}
    if cls.get("version") != CLASSIFIER_VERSION or cls.get("source_sha256") != classifier_source_sha256():
        _plan_refuse(p, "the AST classifier version / source sha256 differs")
    bounds = dict(plan.get("bounds") or {})
    cmin = bounds.pop("cap_min_measurements", None)
    if type(cmin) is not int or not 1 <= cmin <= SAMPLE_SIZE:
        _plan_refuse(p, f"bounds: cap_min_measurements {cmin!r} is not an int in 1..{SAMPLE_SIZE}")
    if bounds != {k: v for k, v in expected_bounds().items() if k != "cap_min_measurements"}:
        _plan_refuse(p, f"bounds differ from the driver's {expected_bounds()}")
    src = plan.get("source") or {}
    man = src.get("manifest") or {}
    mp = Path(src_root) / MANIFEST_REL
    if man.get("sha256") != _sha(mp) or man.get("entries") != len(_manifest_entries(src_root)):
        _plan_refuse(p, "the source manifest sha256 / entry count differs from the src_root's")
    pre = src.get("preflight_records") or {}
    recs = pre.get("records")
    if not isinstance(recs, dict) or not recs or pre.get("count") != len(recs):
        _plan_refuse(p, "no pre-flight record set")
    bad = [r for r, h in recs.items() if not (Path(src_root) / r).is_file() or _sha(Path(src_root) / r) != h]
    if bad:
        _plan_refuse(p, f"pre-flight record(s) {bad[:3]} differ from the src_root's")
    if hashlib.sha256(render_record_list(recs)).hexdigest() != pre.get("list_sha256"):
        _plan_refuse(p, "the pre-flight record list sha256 does not match its records")
    pred = plan.get("predecessor") or {}
    files = pred.get("files")
    if (not pred.get("root") or not isinstance(files, dict) or not files or not pred.get("first_job")
            or not str(pred.get("disposition") or "").strip()):
        _plan_refuse(p, "no predecessor halt root / files / first job / no-reuse disposition")
    for rel, h in files.items():
        f = Path(pred["root"]) / rel
        if not f.is_file() or _sha(f) != h:
            _plan_refuse(p, f"predecessor file {rel} is not the recorded bytes")
    if not str(plan.get("planned_root") or "").strip():
        _plan_refuse(p, "no planned (fresh) root")
    configs = plan.get("configs")
    entries = [c for c in (configs or []) if isinstance(c, dict) and c.get("config") == config_id]
    if len(entries) != 1:
        _plan_refuse(p, f"config {config_id} is not in it exactly once")
    scope = plan.get("scope") or {}
    if (scope.get("all_in_scope") is not True or scope.get("configs") != len(configs)
            or scope.get("universe_kept_total") != sum(int(c.get("kept_count") or 0) for c in configs)):
        _plan_refuse(p, "the universe (all kept candidates in scope) does not add up")
    if plan.get("eligible_total") != sum(len(c.get("eligible") or []) for c in configs) or \
            plan.get("diagnostic_children_ceiling") != MAX_DIAG_CHILDREN * plan.get("eligible_total", -1):
        _plan_refuse(p, "the eligible total / diagnostic children ceiling does not add up")
    entry = entries[0]
    cur = config_strata(src_root, config_id)
    for k, what in (("inventory_sha256", "inventory.json"), ("filtered_sha256", "inventory_filtered.json"),
                    ("module_rel", "inventory module"), ("source_sha256", "source module"),
                    ("kept_count", "kept universe"), ("kept_order_sha256", "kept order")):
        if entry.get(k) != cur[k]:
            _plan_refuse(p, f"{config_id}: {what} ({k}) differs from the src_root's")
    order_ids = [i["job_id"] for i in cr_coord.order_items(json.loads(
        (Path(src_root) / EVID_REL / config_id / "inventory_filtered.json").read_text(encoding="utf-8"))["kept"])]
    if _json_sha(order_ids) != entry["kept_order_sha256"] or not cur["kept_sorted_like_order_items"]:
        _plan_refuse(p, f"{config_id}: the kept order is not cr_coord.order_items'")
    if entry.get("strata") != cur["strata"]:
        _plan_refuse(p, f"{config_id}: strata counts / allocations differ from the recomputed {cur['strata']}")
    if entry.get("calibration_batch") != cur["calibration_batch"]:
        _plan_refuse(p, f"{config_id}: the calibration batch is not the two-strata midpoint selection")
    if entry.get("eligible") != cur["eligible"]:
        _plan_refuse(p, f"{config_id}: the eligible ids are not the batch's import-stratum ids")
    if entry.get("preflight") != cur["preflight"] or any(recs.get(r) != h for r, h in cur["preflight"].items()):
        _plan_refuse(p, f"{config_id}: its pre-flight records are not the plan's pre-flight record set")
    summary = {"path": str(p.resolve()), "sha256": hashlib.sha256(raw).hexdigest(), "schema": PLAN_SCHEMA,
               "config": config_id, "calibration_batch": entry["calibration_batch"], "eligible": entry["eligible"],
               "strata": entry["strata"], "planned_root": plan["planned_root"],
               "predecessor_root": pred["root"], "eligible_total": plan["eligible_total"]}
    return plan, entry, summary


def _check_roots(plan: dict, summary: dict, work_root: Path) -> None:
    """The planned fresh root only; never the predecessor halt root, its campaign root, or anything around them."""
    wr = Path(work_root).resolve()
    pr = Path(plan["predecessor"]["root"]).resolve()
    if wr == pr or wr == pr.parent or pr.is_relative_to(wr) or wr.is_relative_to(pr):
        _plan_refuse(summary["path"], f"work root {wr} would reuse the predecessor halt root {pr} (no-reuse "
                                      f"disposition)")
    if wr != Path(plan["planned_root"]).resolve():
        _plan_refuse(summary["path"], f"work root {wr} is not the plan's planned root {plan['planned_root']}")


def _check_harness_budgets() -> None:
    b = cr_coord.BUDGETS
    if (cr_coord.fence_s() != ORIGINAL_FENCE_S or b["cleanup_reserve_s"] != CLEANUP_RESERVE_S
            or b["session_length_s"] != SESSION_LENGTH_S):
        _refuse(f"the harness budgets (fence {cr_coord.fence_s()}, cleanup {b['cleanup_reserve_s']}, session "
                f"{b['session_length_s']}) are not the ones this driver's P2 reservation was computed from: refused")


def protected_paths(src_root) -> dict:
    """Fix round 1 (A2): the protected paths handed to every probe child. Where the src_root holds the S1 module that
    defines a constant, its module-level ``NAME = Path("...")`` (AST only) must equal the restated path, else
    refused."""
    verified = {}
    for path, rel, name in PROTECTED_PATHS:
        f = Path(src_root) / rel
        if not f.is_file():
            continue
        found = []
        for n in ast.parse(f.read_text(encoding="utf-8")).body:
            if (isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
                    and n.targets[0].id == name):
                v = n.value
                if (isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id == "Path"
                        and len(v.args) == 1 and isinstance(v.args[0], ast.Constant)):
                    found.append(str(v.args[0].value))
                else:
                    found.append(None)
        if found != [path]:
            _refuse(f"protected path {name} in {rel} is {found}, not the driver's {path}: refused")
        verified[name] = True
    return {"paths": [p for p, _, _ in PROTECTED_PATHS], "verified_from_source": verified}


def cap_measurement_check(state: dict) -> str | None:
    """P5: no cap is derived from import errors alone. Import-invalid candidates are NOT measurements (fix round 2,
    review M6); every other item must be a clean killed / survived measurement, and there must be at least one."""
    labels = (state or {}).get("labels") or {}
    excluded = set(import_invalid_ids(state))
    measured = {j: v for j, v in labels.items() if j not in excluded}
    if not any(v in ("killed", "survived") for v in measured.values()):
        return "no clean killed / survived measurement: a cap is never derived from import errors alone"
    bad = sorted(j for j, v in measured.items() if v not in ("killed", "survived"))
    if bad:
        return f"non-clean measurement(s) {bad[:3]}"
    return None


def import_invalid_ids(state: dict) -> list:
    """The batch ids the session recorded as driver_disposition import-invalid-candidate (NONKILL)."""
    res = (state or {}).get("results") or {}
    return [j for j in ((state or {}).get("batch") or list(res)) if
            isinstance(res.get(j), dict) and res[j].get("driver_disposition") == DISPOSITION]


# ------------------------------------------------------------------- 15c-P2: lexical context, localization, gate
def _contains(n, pos) -> bool | None:
    if getattr(n, "lineno", None) is None or getattr(n, "end_lineno", None) is None:
        return None                                       # no position (arguments, comprehension ...): transparent
    return (n.lineno, n.col_offset) <= pos <= (n.end_lineno, n.end_col_offset)


def _search(node, pos, scope):
    for ch in ast.iter_child_nodes(node):
        for d in getattr(ch, "decorator_list", None) or ():
            if _contains(d, pos):                           # decorators sit before the def / class line
                return _in(d, pos, scope)
        c = _contains(ch, pos)
        if c is True:
            return _in(ch, pos, scope)
        if c is None:
            r = _search(ch, pos, scope)
            if r is not None:
                return r
    return None


def _in(n, pos, scope):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if (n.body[0].lineno, n.body[0].col_offset) <= pos:
            return {"kind": "runtime"}
        return _search(n, pos, scope) or scope             # header: defaults / annotations in the ENCLOSING scope
    if isinstance(n, ast.Lambda):
        if _contains(n.body, pos):
            return {"kind": "runtime"}
        return _search(n, pos, scope) or scope
    if isinstance(n, ast.ClassDef):
        if (n.body[0].lineno, n.body[0].col_offset) <= pos:
            q = n.name if scope["kind"] == "module" else f"{scope['qualname']}.{n.name}"
            new = {"kind": "class", "qualname": q,
                   "firstlineno": min([d.lineno for d in n.decorator_list] + [n.lineno])}
            return _search(n, pos, new) or new
        return _search(n, pos, scope) or scope             # bases / keywords / decorators: the enclosing scope
    if isinstance(n, ast.GeneratorExp):
        first = n.generators[0].iter
        if _contains(first, pos):
            return _in(first, pos, scope)
        return {"kind": "generator"}                       # its own <genexpr> frame: never a passing context
    return _search(n, pos, scope) or scope


def mutation_context(src: str, start) -> dict:
    """The scope that EXECUTES the mutation site, from the actual AST: module, an exact class body (qualname and the
    class code's first line, decorators included), runtime (a def / lambda body) or generator. A def default,
    decorator or annotation executes in the ENCLOSING scope."""
    pos = (int(start[0]), int(start[1]))
    module = {"kind": "module", "qualname": "<module>", "firstlineno": 1}
    return _search(ast.parse(src), pos, module) or module


_LINE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+$")


def split_lines(text: str) -> list:
    """Lines with their endings, split ONLY on \\r\\n, \\r and \\n - Python's tokenizer / co_positions line model
    (review M3: str.splitlines also splits on \\x0b \\x0c \\x1c-\\x1e \\x85 \\u2028 \\u2029)."""
    return _LINE.findall(text)


def localize(pre: str, post: str, start, end) -> tuple:
    """One mutation, localized: the only change between the decoded pre and post sources lies inside the item's
    span [start, end) (single line) and adds no line. Returns (ok, info) - info["post_span"] is the span in the
    mutated source."""
    if pre == post:
        return False, {"why": "unchanged: no mutation installed"}
    lines = split_lines(pre)                                  # review M3: Python's line model
    (sl, sc), (el, ec) = (int(start[0]), int(start[1])), (int(end[0]), int(end[1]))
    if sl != el or not 1 <= sl <= len(lines) or not 0 <= sc < ec <= len(lines[sl - 1].rstrip("\r\n")):
        return False, {"why": f"span_invalid: {start}-{end}"}
    base = sum(len(x) for x in lines[:sl - 1])
    a, b = base + sc, base + ec
    n = min(len(pre), len(post))
    p = 0
    while p < n and pre[p] == post[p]:
        p += 1
    s = 0
    while s < n - p and pre[-1 - s] == post[-1 - s]:
        s += 1
    pre_end, post_end = len(pre) - s, len(post) - s
    info = {"pre_change": [p, pre_end], "pre_text": pre[p:pre_end], "post_text": post[p:post_end],
            "allowed": [a, b]}
    if not (a <= p and pre_end <= b):
        return False, dict(info, why="not_localized: the change is not inside the item's span (multiple, "
                                     "reformatted or unexplained change)")
    if any(c in info["post_text"] + info["pre_text"] for c in "\r\n"):
        return False, dict(info, why="newline: the change adds or removes a line")
    delta = len(post) - len(pre)
    if ec + delta <= sc:
        return False, dict(info, why="span_invalid: empty mutated span")
    return True, dict(info, post_span=[[sl, sc], [el, ec + delta]])


def _char_col(line_text: str, byte_col) -> int | None:
    """co_positions columns are UTF-8 byte offsets; spans are character columns."""
    if type(byte_col) is not int or byte_col < 0:
        return None
    raw = line_text.encode("utf-8")
    if byte_col > len(raw):
        return None
    try:
        return len(raw[:byte_col].decode("utf-8"))
    except UnicodeDecodeError:
        return None


_SYNTAX = ("SyntaxError", "IndentationError", "TabError")


def exception_name(exc: dict) -> str:
    return exc.get("qualname") if exc.get("module") == "builtins" else f"{exc.get('module')}.{exc.get('qualname')}"


def gate(rec, *, module_rel: str, pre_text: str, post_text: str, post_sha: str, start, end,
         collect_names) -> tuple:
    """P3: the structural gate on the mutated probe record. (True, info) only when the INNERMOST frame is the
    target file at the mutation site's actual lexical context, its instruction span overlaps the mutated span, every
    frame from the first target frame on is the target, no barrier refused anything and the original collection
    errors name the same exception class. Fail closed everywhere."""
    info: dict = {}

    def no(code, detail=""):
        info["why"] = f"{code}: {detail}" if detail else code
        return False, info
    if not isinstance(rec, dict):
        return no("record_malformed")
    fr = (rec.get("exception") or {}).get("frames") if isinstance(rec.get("exception"), dict) else None
    info["frames_tail"] = fr[-3:] if isinstance(fr, list) else None
    bar = rec.get("barrier") or {}
    if bar.get("installed") is not True:
        return no("barrier_not_installed")
    if bar.get("refusals"):
        return no("barrier_refusal", json.dumps(bar["refusals"])[:300])
    exc = rec.get("exception")
    if rec.get("imported") is not False or not isinstance(exc, dict):
        return no("imported_clean", "the re-applied mutant raised nothing at import")
    frames = exc.get("frames")
    if not isinstance(frames, list) or not frames or not all(isinstance(f, dict) for f in frames):
        return no("frames_missing")
    info["exception"] = exception_name(exc)
    info["frames_tail"] = frames[-3:]
    if exc.get("module") == "builtins" and exc.get("qualname") in _SYNTAX:
        return no("syntax_error", "no executed target frame; no reviewed location rule")
    inner = frames[-1]
    info["innermost"] = {k: inner.get(k) for k in ("rel", "co_name", "co_qualname", "co_firstlineno", "co_flags",
                                                   "position", "positions_agree")}
    if inner.get("rel") != module_rel:
        return no("innermost_not_target", f"{inner.get('rel') or inner.get('filename')} {inner.get('co_qualname')}")
    first = next(i for i, f in enumerate(frames) if f.get("rel") == module_rel)
    if any(f.get("rel") != module_rel for f in frames[first:]):
        return no("dependency_frame", "a non-target frame between the target and the innermost frame")
    if inner.get("file_sha256") != post_sha:
        return no("file_sha_mismatch", "the innermost frame's file is not the mutated source")
    ctx = mutation_context(pre_text, start)
    info["context"] = ctx
    flags = inner.get("co_flags")
    if type(flags) is not int or flags & 0x3:
        return no("context_mismatch", "an optimized / new-locals (function) frame is never module or class code")
    if ctx["kind"] == "module":
        ok = inner.get("co_name") == "<module>" and inner.get("co_qualname") == "<module>"
    elif ctx["kind"] == "class":
        ok = (inner.get("co_qualname") == ctx["qualname"] and inner.get("co_name") == ctx["qualname"].split(".")[-1]
              and inner.get("co_firstlineno") == ctx["firstlineno"])
    else:
        ok = False
    if not ok:
        return no("context_mismatch", f"site context {ctx}, frame {inner.get('co_qualname')}")
    pos = inner.get("position")
    if (not isinstance(pos, list) or len(pos) != 4 or any(type(v) is not int for v in pos)
            or inner.get("positions_agree") is not True):
        return no("position_invalid", f"{pos} (agree={inner.get('positions_agree')})")
    lines = [x.rstrip("\r\n") for x in split_lines(post_text)]       # review M3: Python's line model
    ln, eln, bc, ebc = pos
    if not (1 <= ln <= eln <= len(lines)):
        return no("position_invalid", f"lines {ln}-{eln} out of range")
    c0, c1 = _char_col(lines[ln - 1], bc), _char_col(lines[eln - 1], ebc)
    if c0 is None or c1 is None or (ln, c0) >= (eln, c1):
        return no("position_invalid", f"columns {bc}-{ebc} out of range")
    ok_loc, loc = localize(pre_text, post_text, start, end)
    if not ok_loc:
        return no(loc["why"].split(":")[0], loc["why"])
    (ml, mc0), (_, mc1) = loc["post_span"]
    info["frame_span"], info["mutation_span"] = [[ln, c0], [eln, c1]], loc["post_span"]
    info["overlap"] = (ln, c0) < (ml, mc1) and (ml, mc0) < (eln, c1)
    if not info["overlap"]:
        return no("no_overlap", f"frame {info['frame_span']} vs mutation {loc['post_span']}")
    names = list(collect_names or [])
    if not names or any(n != info["exception"] for n in names):
        return no("collection_errors_inconsistent", f"original {names} vs probe {info['exception']}")
    info["reasons"] = ["barriers installed, no refusal", "imported: False (exception at import)",
                       f"innermost frame is the target ({module_rel})", "no dependency frame after the target",
                       "innermost file sha256 == mutated source", f"lexical context {ctx} matches the frame code",
                       "positions valid (positions_agree is a consistency re-read of co_positions, not an "
                       "independent check; the tb_lasti // 2 mapping is verified by the toy tests)",
                       "frame span overlaps the mutated span",
                       f"original collection errors all name {info['exception']} (secondary text consistency)"]
    return True, info


# ------------------------------------------------------------------- 15c-P2: qualification from TRUSTED records
_NODES_KEYS = {"attempt", "selected", "phases", "xfail", "collect_errors", "internal_error", "exitstatus",
               "call_exc", "imports"}
_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_ELINE = re.compile(r"^E +([A-Za-z_][\w.]*)(?::|$)")


def _e_name(longrepr: str) -> str | None:
    """The exception name of the LAST 'E   Name: ...' line (rendered text: SECONDARY consistency evidence only)."""
    names = [m.group(1) for m in (_ELINE.match(ln) for ln in str(longrepr).splitlines()) if m]
    return names[-1] if names else None


def qualify(item: dict, result: dict, job_dir: Path, target: str) -> tuple:
    """(None, facts) when the item's collection error is a QUALIFYING one (P5 / RULING A2): the canonical
    error/error:collection result with exec ok, cleanup verified, no raw timeout, AND the trusted guard records
    bound to this job / attempt / sidecar show zero executed tests (nodes.json selected == [] and phases == {}, no
    call, no internal error, the target never finished importing) with consistent collection errors. Else
    (why, facts): the item halts exactly as today."""
    facts: dict = {}

    def no(why):
        return why, facts
    if policy_check(result) != CANON_ERROR:
        return no(f"reason {policy_check(result)} is not {CANON_ERROR}")
    raw = result.get("raw")
    if not isinstance(raw, dict) or raw.get("cr_timeout") is not False:
        return no("raw: no raw CR record or a raw timeout")
    gp = Path(job_dir) / "guard.json"
    try:
        side = json.loads(gp.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return no(f"guard.json: missing or malformed ({type(exc).__name__})")
    if not isinstance(side, dict) or side.get("schema") != "a3-t15a-guard/1":
        return no("guard.json: not a guard sidecar")
    facts["guard_sha256"] = _sha(gp)
    if side.get("job_id") != item.get("job_id"):
        return no(f"job_id: sidecar {side.get('job_id')!r} is not {item.get('job_id')!r}")
    if side.get("status") != "error:collection" or side.get("status") != result.get("guard_status"):
        return no(f"status: sidecar {side.get('status')!r}")
    if (side.get("cleanup") or {}).get("verified") is not True:
        return no("cleanup: the guard's own cleanup is not verified")
    if side.get("guard_sha256") != _sha(cr_guard.__file__):
        return no("guard_sha256: the sidecar was not written by the reviewed guard")
    att = side.get("attempt")
    if raw.get("guard_attempt") != att:
        return no(f"guard_attempt: raw {raw.get('guard_attempt')!r} is not the sidecar's attempt {att!r}")
    attempts = sorted(Path(job_dir).glob("attempt-*"))
    if (not isinstance(att, str) or not _HEX32.match(att) or [a.name for a in attempts] != [f"attempt-{att}"]
            or Path(str(side.get("attempt_dir") or "")).resolve() != (Path(job_dir) / f"attempt-{att}").resolve()):
        return no("attempt: not exactly one attempt dir bound to the sidecar's attempt")
    np_ = Path(job_dir) / f"attempt-{att}" / "nodes.json"
    if not np_.is_file():
        return no("nodes: no nodes.json record")
    if side.get("nodes_record_sha256") != _sha(np_):
        return no("nodes_record_sha256: nodes.json is not the record the sidecar bound")
    try:
        nodes = json.loads(np_.read_text(encoding="utf-8"))
    except ValueError:
        return no("nodes: nodes.json malformed")
    if not isinstance(nodes, dict) or set(nodes) != _NODES_KEYS:
        return no(f"keys: nodes.json keys {sorted(nodes) if isinstance(nodes, dict) else type(nodes).__name__}")
    if nodes["attempt"] != att:
        return no("attempt: nodes.json is from another attempt")
    if nodes["selected"] != [] or not isinstance(nodes["selected"], list):
        return no("selected: tests were selected")
    if nodes["phases"] != {} or not isinstance(nodes["phases"], dict):
        return no("phases: a runtest event exists (collection plus an actual call)")
    if nodes["call_exc"] != {} or not isinstance(nodes["call_exc"], dict):
        return no("call_exc: a call exception was recorded")
    if nodes["xfail"] != [] or not isinstance(nodes["xfail"], list):
        return no("xfail: not empty")
    if nodes["internal_error"] is not False:
        return no("internal_error: pytest internal error")
    if type(nodes["exitstatus"]) is not int or nodes["exitstatus"] != 2 or side.get("rc") != 2:
        return no(f"exitstatus: {nodes['exitstatus']!r} / rc {side.get('rc')!r} is not the collection-error 2")
    if not isinstance(nodes["imports"], dict) or nodes["imports"].get(target, "absent") is not None:
        return no("imports: the target finished importing (or was not tracked)")
    errs = nodes["collect_errors"]
    if (not isinstance(errs, list) or not errs
            or not all(isinstance(e, dict) and isinstance(e.get("nodeid"), str) and isinstance(e.get("longrepr"), str)
                       for e in errs)):
        return no("collect_errors: none or malformed")
    if side.get("collect_errors") != errs:
        return no("collect_errors: the sidecar's differ from nodes.json")
    cp = Path(job_dir) / "classification.json"
    try:
        cls = json.loads(cp.read_text(encoding="utf-8"))
        (row,) = cls["items"]
    except (OSError, ValueError, KeyError, TypeError):
        return no("classification: missing or malformed")
    if (row.get("job_id") != item.get("job_id") or row.get("sidecar_sha256") != facts["guard_sha256"]
            or row.get("sidecar_status") != "error:collection" or row.get("label") != "error"):
        return no("classification: not bound to this sidecar / job")
    names = [_e_name(e["longrepr"]) for e in errs]
    if any(n is None for n in names):
        return no("E-line: a collection error has no exception line")
    if len(set(names)) != 1:
        return no(f"mixed collection errors: {sorted(set(names))}")
    facts.update(attempt=att, nodes_sha256=_sha(np_), collect_names=names, classification_sha256=_sha(cp),
                 collect_errors=len(errs))
    return None, facts


# ------------------------------------------------------------------- 15c-P2: the diagnosis pair (A3)
class DiagnosisHalt(Exception):
    """A diagnostic failure: the item HALTS before the next original candidate."""

    def __init__(self, why: str, **facts):
        super().__init__(why)
        self.why, self.facts = why, facts


class Diagnoser:
    """Per screening session: eligibility (the plan's exact eligible ids), the P2 admission fence on the parent
    session clock, and the 2-child diagnosis (control, then mutated) through the reviewed cr_guard.run_contained."""

    def __init__(self, *, eligible, clock, session_root: Path, src_root: Path, copy_paths, cfg, pin: dict,
                 plan_summary: dict, probe_sha: str, runner=None, protected=None):
        self.eligible, self.clock, self.sroot = frozenset(eligible), clock, Path(session_root)
        self.src_root, self.copy_paths, self.cfg, self.pin = Path(src_root), list(copy_paths), cfg, dict(pin)
        self.plan, self.probe_sha = plan_summary, probe_sha
        self.protected = [str(p) for p in (protected if protected is not None
                                           else [p for p, _, _ in PROTECTED_PATHS])]
        self.runner = runner if runner is not None else cr_guard.run_contained
        self.log: dict = {}

    # -- the parent session clock (session.json, written by run_batch from the SAME clock): no fresh clock
    def remaining(self) -> float:
        started = float(json.loads((self.sroot / "session.json").read_text(encoding="utf-8"))["started"])
        now = float(self.clock())
        if now < started:
            return float("-inf")
        return float(SESSION_LENGTH_S) - (now - started)

    def _need(self, what: str, need: float):
        left = self.remaining()
        if left < need:
            raise DiagnosisHalt(f"budget:{what}", remaining_s=left, needed_s=need)
        return left

    # -- the pair
    def diagnose(self, item: dict, job_dir: Path, facts: dict) -> dict:
        job, mod_rel = item["job_id"], cr_coord._posix(item["module_path"])
        if mod_rel != cr_coord._posix(self.cfg.module_rel):
            raise DiagnosisHalt("target:not_config_module")
        dg = Path(job_dir) / "dg"
        dg.mkdir()                                              # never reused
        spec = dg / "spec.json"
        _write_once(spec, {k: item[k] for k in ("job_id", "module_path", "operator", "operator_args", "occurrence",
                                                "start", "end")})
        pin = self.pin[mod_rel]
        pre_text = read_source(self.src_root / mod_rel)
        if _sha(self.src_root / mod_rel) != pin:
            raise DiagnosisHalt("source:src_root_not_pinned")
        tree_sha = self._tree_sha(job)
        times = {}
        self._need("control", diagnosis_reserve_s())
        t = time.monotonic()
        ctl, ctl_path = self._child("control", item, dg, spec, tree_sha, pin)
        times["control_s"] = round(time.monotonic() - t, 3)
        self._check_control(ctl, mod_rel, pin)
        ctl_sha = _sha(ctl_path)
        self._need("mutated", diagnosis_child_s())
        t = time.monotonic()
        mut, mut_path = self._child("mutated", item, dg, spec, tree_sha, pin)
        times["mutated_s"] = round(time.monotonic() - t, 3)
        post_file = dg / "m" / mod_rel
        post_sha = _sha(post_file)
        self._check_mutated(mut, ctl, mod_rel, pin, post_sha)
        post_text = read_source(post_file)
        if hashlib.sha256(post_text.encode("utf-8")).hexdigest() != (mut.get("mutation") or {}).get("post_text_sha256"):
            raise DiagnosisHalt("mutated:record_post_text", record=str(mut_path))
        ok, loc = localize(pre_text, post_text, item["start"], item["end"])          # independent parent re-check
        if not ok:
            raise DiagnosisHalt(f"not_localized:{loc['why'].split(':')[0]}", localize=loc, record=str(mut_path))
        pre_path = self._check_preimport(mut, mut_path, loc)
        passed, info = gate(mut, module_rel=mod_rel, pre_text=pre_text, post_text=post_text, post_sha=post_sha,
                            start=item["start"], end=item["end"], collect_names=facts.get("collect_names"))
        if not passed:
            raise DiagnosisHalt(info["why"].split(":")[0], gate=info, frames_tail=info.get("frames_tail"),
                                record=str(mut_path))
        if _sha(ctl_path) != ctl_sha:
            raise DiagnosisHalt("control:record_changed")
        disp = {"driver_disposition": DISPOSITION, "policy_version": POLICY_VERSION, "job_id": job,
                "plan": {"path": self.plan["path"], "sha256": self.plan["sha256"]},
                "probe": {"path": str(PROBE_PATH), "sha256": self.probe_sha},
                "spec": {"path": str(spec), "sha256": _sha(spec)},
                "records": {"control": {"path": str(ctl_path), "sha256": ctl_sha},
                            "mutated_preimport": {"path": str(pre_path), "sha256": _sha(pre_path)},
                            "mutated": {"path": str(mut_path), "sha256": _sha(mut_path)}},
                "scope": PROBE_SCOPE,
                "barrier": {k: (mut.get("barrier") or {}).get(k) for k in ("claim", "protected", "installed_at")},
                "bootstrap": mut.get("bootstrap"),
                "qualification": facts, "context": info["context"], "gate": info,
                "localize": {k: loc[k] for k in ("post_span", "pre_text", "post_text")},
                "source": {"pre_sha256": pin, "post_sha256": post_sha},
                "canonical": {"label": "error", "guard_status": "error:collection", "raw_unchanged": True},
                "nonkill": True,
                "accounting": "NONKILL: not killed, not survived, not equivalent, never CR 'incompetent'; stays in "
                              "the full candidate universe; no new positive assertion coverage is claimed",
                "note": "probe-confirmed import-invalid candidate under the probe context - re-applied under probe "
                        "context (A4): Cosmic Ray never persisted the original attempt's mutated bytes, so the "
                        "probe's mutated sha256 is not compared byte-for-byte with the original attempt; not a proof "
                        "that every original collection failure has this one cause",
                "costs": times, "at": _now()}
        _write_once(dg / "disposition.json", disp)
        return disp

    def _tree_sha(self, job: str) -> str:
        for sp in sorted(self.sroot.glob("batch_*_state.json")):
            st = json.loads(sp.read_text(encoding="utf-8"))
            if job in (st.get("batch") or []):
                h = (st.get("copied_tree_sha256") or {}).get(job)
                if h:
                    return h
        raise DiagnosisHalt("source:no_recorded_tree")

    def _child(self, mode: str, item: dict, dg: Path, spec: Path, tree_sha: str, pin: str) -> tuple:
        copy = dg / ("c" if mode == "control" else "m")
        copied = cr_coord.make_copy(self.src_root, self.copy_paths, copy)        # the original copy semantics
        mod_rel = cr_coord._posix(item["module_path"])
        if copied.get(mod_rel) != pin or cr_coord.map_sha256(copied) != tree_sha:
            raise DiagnosisHalt(f"{mode}:copy_source")
        if _sha(PROBE_PATH) != self.probe_sha:
            raise DiagnosisHalt(f"{mode}:probe_changed")
        out = dg / f"{mode}.json"
        env = cr_coord._env(copy, self.cfg)                     # the bound child env (A1), no guard variables
        env["S1_HYPOTHESIS_ROOT"] = str(dg / f"{mode}_hypothesis")
        cmd = [str(self.cfg.python), "-B", str(PROBE_PATH), "--mode", mode, "--copy-root", str(copy),
               "--module-rel", mod_rel, "--target", self.cfg.target_module, "--spec", str(spec), "--scratch",
               str(dg), "--out", str(out), "--pin", pin]
        for rel in PROBE_PREFIX:
            cmd += ["--prefix", rel]
        for p in self.protected:                                # identical barrier in both modes (A2)
            cmd += ["--protected", p]
        try:
            run = self.runner(cmd, cwd=copy, env=env, stdout_path=dg / f"{mode}_stdout.txt",
                              stderr_path=dg / f"{mode}_stderr.txt", deadline_s=float(PROBE_DEADLINE_S),
                              cleanup_s=float(CLEANUP_RESERVE_S))
        except Exception as exc:                                # noqa: BLE001 - containment failure: halt
            raise DiagnosisHalt(f"{mode}:containment", error=f"{type(exc).__name__}: {exc}") from None
        _write_once(dg / f"{mode}_run.json", dict(run, cmd=cmd) if isinstance(run, dict) else {"run": repr(run)})
        if not isinstance(run, dict):
            raise DiagnosisHalt(f"{mode}:run_malformed")
        if run.get("timed_out") is not False:
            raise DiagnosisHalt(f"{mode}:timed_out")
        if (run.get("cleanup") or {}).get("verified") is not True:
            raise DiagnosisHalt(f"{mode}:cleanup_unverified")
        if run.get("rc") != 0:
            raise DiagnosisHalt(f"{mode}:rc_{run.get('rc')}")
        try:
            rec = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise DiagnosisHalt(f"{mode}:record_unreadable", error=type(exc).__name__) from None
        want_prefix = [str((copy / r).resolve()) for r in PROBE_PREFIX]
        if (not isinstance(rec, dict) or rec.get("schema") != PROBE_SCHEMA or rec.get("mode") != mode
                or rec.get("probe_sha256") != self.probe_sha or rec.get("module_rel") != mod_rel
                or rec.get("target") != self.cfg.target_module or rec.get("spec_sha256") != _sha(spec)):
            raise DiagnosisHalt(f"{mode}:record_identity", record=str(out))
        bar, boot = rec.get("barrier") or {}, rec.get("bootstrap") or {}
        if (bar.get("installed") is not True or bar.get("installed_at") != "before_mutation_and_import"
                or sorted(bar.get("protected") or []) != sorted(self.protected)
                or boot.get("copy_modules_before_hook") != [] or boot.get("hook_installed_before_target") is not True):
            raise DiagnosisHalt(f"{mode}:barrier_context", record=str(out))
        if bar.get("refusals"):                                 # its own trusted reason, never a target origin
            raise DiagnosisHalt(f"{mode}:barrier_refusal", record=str(out),
                                refusals=[{k: r.get(k) for k in ("event", "reason")} for r in bar["refusals"]])
        if rec.get("stage") == "refused":                       # A3: refused BEFORE the target import
            reason = str((rec.get("refusal") or {}).get("reason") or "unknown")
            raise DiagnosisHalt(f"{mode}:refused:{reason}", record=str(out), refusal=rec.get("refusal"))
        if rec.get("stage_error") is not None:
            raise DiagnosisHalt(f"{mode}:probe_setup_error", record=str(out), error=rec.get("stage_error"))
        if (rec.get("stage") != "done" or rec.get("copy_modules_before_import") != []
                or rec.get("sys_path_prefix") != want_prefix or rec.get("pin") != pin):
            raise DiagnosisHalt(f"{mode}:record_context", record=str(out))
        return rec, out

    def _check_preimport(self, mut: dict, mut_path: Path, loc: dict) -> Path:
        """A3: the mutated child's persisted pre-import validation, re-verified by the parent: it exists, it
        validated ok, its hashes / diff / span are the final record's and the parent's own localize result."""
        p = mut_path.with_name(mut_path.stem + ".preimport.json")
        try:
            pre = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise DiagnosisHalt("mutated:preimport_unreadable", record=str(p)) from None
        v = pre.get("validation") or {}
        if (v.get("ok") is not True or pre.get("mutation") != mut.get("mutation")
                or pre.get("source") != {k: (mut.get("source") or {}).get(k) for k in ("pre_sha256", "pre_text_sha256")}
                or pre.get("spec_sha256") != mut.get("spec_sha256") or pre.get("pin") != mut.get("pin")
                or v != mut.get("validation") or v.get("post_span") != loc.get("post_span")):
            raise DiagnosisHalt("mutated:preimport_mismatch", record=str(p))
        return p

    def _check_control(self, rec: dict, mod_rel: str, pin: str) -> None:
        f = rec.get("imported_file") or {}
        src = rec.get("source") or {}
        if (rec.get("barrier") or {}).get("refusals"):
            raise DiagnosisHalt("control:barrier_refusal")
        if rec.get("imported") is not True:
            raise DiagnosisHalt("control:not_imported", exception=(rec.get("exception") or {}).get("qualname"))
        if f.get("rel") != mod_rel or f.get("sha256") != pin or src.get("pre_sha256") != pin \
                or src.get("unchanged") is not True:
            raise DiagnosisHalt("control:source_identity")

    def _check_mutated(self, rec: dict, ctl: dict, mod_rel: str, pin: str, post_sha: str) -> None:
        m = rec.get("mutation") or {}
        if (m.get("applied") is not True or m.get("cr_original_equals_pre") is not True
                or m.get("post_text_equals_cr_mutated") is not True):
            raise DiagnosisHalt("mutated:mutation_not_installed")
        if (rec.get("source") or {}).get("pre_sha256") != pin or m.get("post_sha256") != post_sha:
            raise DiagnosisHalt("mutated:source_identity")
        if (rec.get("modules_before_import") != ctl.get("modules_before_import")
                or sorted(rec.get("env_bound") or {}) != sorted(ctl.get("env_bound") or {})):
            raise DiagnosisHalt("mutated:context_differs_from_control")
        keys = ("events", "protected", "claim", "installed_at")
        if {k: (rec.get("barrier") or {}).get(k) for k in keys} != {k: (ctl.get("barrier") or {}).get(k) for k in keys}:
            raise DiagnosisHalt("mutated:barrier_differs_from_control")


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
    "p2_import_invalid": "15c-P2 (" + POLICY_VERSION + "): the ONE narrow exception - an eligible screening id of the "
                         "external plan whose canonical error/error:collection result qualifies on trusted records "
                         "(zero selected nodes, no runtest event) continues only after a passing diagnosis pair "
                         "(unmutated control, then the mutated import, both contained, 60 s each) and the "
                         "structural gate, as driver_disposition import-invalid-candidate (NONKILL; canonical label, "
                         "guard and raw CR outcome unchanged). Every diagnostic failure, a runtime-stratum id and any "
                         "completion-stage error halt. Eligible items need 645 s left before CR starts.",
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


def _halt_result(reason: str, original=None) -> dict:
    """A halting result for an item whose original CR execution never started (P2 admission fence)."""
    return {"label": None, "reason": f"policy: {reason}", "guard_status": None, "raw": None, "raw_timeout": False,
            "exec_status": f"policy_halt:{reason}", "cleanup_verified": True,       # nothing ran: nothing to clean
            "policy": {"halt": True, "reason": reason, "original_exec_status": original}}


def policy_seam(inner, diag: "Diagnoser | None" = None):
    """Codex X26: wrap an exec seam (real_exec(cfg) on the real path) so that any result the policy does not accept
    halts the batch BEFORE the next candidate (POLICY_DOC). The raw result is persisted write-once BEFORE the result
    is handed back. The wrapper keeps the inner seam's command tag (run_batch's seam/cfg check still applies), is
    never synthetic, and says what it is (cr_policy_wrapper, .inner) - it does not masquerade as a plain real_exec.

    15c-P2 (screening seams only, ``diag``): for an item among the plan's ELIGIBLE ids, (1) the admission fence -
    BEFORE the original CR execution starts, the parent session clock must leave admission_reservation_s() (645 s),
    else a durable fence stop with no CR call; (2) after CR, a canonical error/error:collection result that QUALIFIES
    (qualify) gets the diagnosis pair; it continues only when the gate passes, with write-once driver_disposition
    import-invalid-candidate (label, guard_status, raw CR outcome unchanged). Every other outcome halts as before."""
    def seam(item, copy_root, job_dir):
        rec = Path(job_dir) / "policy_result.json"
        job = item.get("job_id")
        eligible = diag is not None and job in diag.eligible
        entry = {"eligible": eligible, "probe": False, "cr_s": None, "diagnostic_s": 0.0} if diag else None
        if diag is not None:
            diag.log[job] = entry
        if eligible:
            left = diag.remaining()
            if left < admission_reservation_s():              # P2: before the original CR item can start
                reason = f"admission_fence:remaining={left}<{admission_reservation_s()}"
                _write_once(rec, {"job_id": job, "halt": True, "reason": reason, "remaining_s": left,
                                  "reservation_s": admission_reservation_s(), "cr_started": False,
                                  "policy_version": POLICY_VERSION})
                entry["halt"] = reason
                return _halt_result(reason)
        t_cr = time.monotonic()
        try:
            result = inner(item, copy_root, job_dir)
        except BaseException as exc:          # run_batch records exec_exception + quarantine; we keep the fact
            _write_once(rec, {"job_id": item.get("job_id"), "exception": f"{type(exc).__name__}: {exc}",
                              "halt": True, "reason": "inner_exception"})
            raise
        if entry is not None:
            entry["cr_s"] = round(time.monotonic() - t_cr, 3)
        try:
            out, reason = _decide(result)
        except BaseException as exc:          # the policy itself failed: the raw result is still kept, then halt
            _write_once(rec, {"job_id": item.get("job_id"),
                              "raw": result if isinstance(result, dict) else _safe_repr(result), "halt": True,
                              "reason": "policy_error", "policy_error": f"{type(exc).__name__}: {exc}"})
            raise
        extra = {}
        if diag is not None and reason == CANON_ERROR:
            out, reason, extra = _diagnosis_step(diag, item, result, out, reason, job_dir, rec, entry)
        _write_once(rec, {"job_id": item.get("job_id"), "raw": result if isinstance(result, dict) else repr(result),
                          "halt": reason is not None, "reason": reason, "returned_exec_status": out["exec_status"],
                          **extra})
        return out
    seam.inner, seam.cr_policy_wrapper, seam.synthetic = inner, True, False
    seam.cr_real_exec = bool(getattr(inner, "cr_real_exec", False))
    if getattr(inner, "test_command_sha256", None) is not None:
        seam.test_command_sha256 = inner.test_command_sha256
    return seam


def _diagnosis_step(diag: Diagnoser, item: dict, result: dict, out: dict, reason: str, job_dir, rec: Path,
                    entry: dict) -> tuple:
    """(out, reason, extra policy-record fields). Non-eligible / non-qualifying: unchanged (halts as today). A
    diagnostic failure: halt with exec_status policy_halt:diagnosis:<why> (labels untouched). An interrupt: the
    record is written, then re-raised."""
    job = item["job_id"]
    if job not in diag.eligible:
        return out, reason, {"diagnosis": {"qualifying": False, "why": "not an eligible screening id of the plan"}}
    why, facts = qualify(item, result, Path(job_dir), diag.cfg.target_module)
    if why is not None:
        return out, reason, {"diagnosis": {"qualifying": False, "why": why}}
    entry["probe"] = True
    t = time.monotonic()
    try:
        diag.diagnose(item, Path(job_dir), facts)
    except BaseException as exc:              # noqa: BLE001 - every outcome but a pass is a halt or a re-raise
        if not isinstance(exc, Exception):    # interrupt: keep the fact write-once, then re-raise
            disp_p = Path(job_dir) / "dg" / "disposition.json"
            sup = ({"path": str(disp_p), "sha256": _sha(disp_p),
                    "note": "SUPERSEDED: the diagnosis was interrupted after this disposition was written; the item "
                            "halted and the disposition does not apply (review M8)"} if disp_p.is_file() else None)
            _write_once(rec, {"job_id": job, "raw": result, "halt": True, "reason": "diagnosis_interrupted",
                              "interrupt": f"{type(exc).__name__}: {exc}", "diagnosis": {"qualifying": True},
                              "superseded_disposition": sup})
            raise
        h = exc if isinstance(exc, DiagnosisHalt) else DiagnosisHalt(      # review M7: one structured halt record
            f"error:{type(exc).__name__}", error=f"{type(exc).__name__}: {exc}")
        entry["diagnostic_s"] = round(time.monotonic() - t, 3)
        new = f"diagnosis:{h.why}"
        _write_once(Path(job_dir) / "dg" / "diagnosis_halt.json" if (Path(job_dir) / "dg").is_dir()
                    else Path(job_dir) / "diagnosis_halt.json",
                    {"job_id": job, "why": h.why, "facts": h.facts, "frames_tail": h.facts.get("frames_tail"),
                     "qualification": facts, "policy_version": POLICY_VERSION, "at": _now()})
        entry["halt"] = new
        o = dict(out)
        o["policy"] = dict(out["policy"], reason=new, canonical_reason=reason)
        o["exec_status"] = f"policy_halt:{new}"
        return o, new, {"diagnosis": {"qualifying": True, "halt": h.why, **({"error": h.facts["error"]}
                                                                           if "error" in h.facts else {})}}
    entry["diagnostic_s"] = round(time.monotonic() - t, 3)
    entry["disposition"] = DISPOSITION
    o = dict(result)                          # every canonical field, label / guard_status / raw included, unchanged
    o["driver_disposition"] = DISPOSITION
    o["diagnosis"] = {"disposition": str(Path(job_dir) / "dg" / "disposition.json"),
                      "disposition_sha256": _sha(Path(job_dir) / "dg" / "disposition.json"),
                      "policy_version": POLICY_VERSION}
    o["policy"] = {"halt": False, "reason": None, "original_exec_status": result.get("exec_status"),
                   "canonical_reason": reason, "disposition": DISPOSITION}
    return o, None, {"diagnosis": {"qualifying": True, "disposition": DISPOSITION,
                                   "record": o["diagnosis"]["disposition"],
                                   "sha256": o["diagnosis"]["disposition_sha256"]}}


PROTOCOL = {
    "C1": "exact calibration ids: the EXTERNAL sampling plan v2's calibration_batch (two-strata midpoint rule, "
          "recomputed and verified against the inventories; 15c-P2), in order; one config per session; an earlier "
          "config (discover order) must have a clean report under the work root unless a --review-ref names the "
          "review that allows the next config",
    "C2": "the CLI imports the harness from --src-root (not in a git tree; manifest-verified bytes, its path) and runs "
          "real_exec wrapped only by the explicit policy seam (command tag kept, never synthetic); the driver's own "
          "sha256 is in every report",
    "C3": "one session root per config (session-000), completion on the same session clock (run_completion "
          "session_root), run_batch's HARD fence (405 s) per candidate, and for a plan-eligible candidate the "
          "driver's earlier 645 s admission fence on the same clock (15c-P2); a fence refusal is reported, never "
          "resumed",
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
    if r.startswith(("session_budget", "session_clock_invalid", "policy_halt:admission_fence",
                     "policy_halt:diagnosis:budget")):
        return "fence"                        # 15c-P2: the admission fence and the diagnosis budget are fences too
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


def _accounting(rep: dict, entry: dict, diag) -> dict:
    """P5: costs reported separately per stratum (import / runtime), probe or no probe, screening (CR) and
    diagnostic seconds; the import-invalid candidates listed on their own (NONKILL). Never raises."""
    try:
        scr = rep.get("screening") or {}
        item_s, labels = scr.get("item_s") or {}, scr.get("labels") or {}
        elig = set(entry.get("eligible") or [])
        items = {}
        for j in rep.get("calibration_batch") or []:
            e = (diag.log if diag is not None else {}).get(j) or {}
            items[j] = {"stratum": "import" if j in elig else "runtime", "eligible": j in elig,
                        "probe": bool(e.get("probe")), "item_s": item_s.get(j), "cr_s": e.get("cr_s"),
                        "diagnostic_s": float(e.get("diagnostic_s") or 0.0), "label": labels.get(j),
                        "disposition": e.get("disposition"), "halt": e.get("halt")}
        by = {}
        for s in ("import", "runtime"):
            xs = [v for v in items.values() if v["stratum"] == s]
            by[s] = {"ids": len(xs), "executed": sum(1 for v in xs if v["item_s"] is not None),
                     "probed": sum(1 for v in xs if v["probe"]),
                     "item_s_total": round(sum(v["item_s"] or 0.0 for v in xs), 3),
                     "item_s_max": max([v["item_s"] for v in xs if v["item_s"] is not None], default=None),
                     "diagnostic_s_total": round(sum(v["diagnostic_s"] for v in xs), 3)}
        return {"items": items, "by_stratum": by,
                "import_invalid_candidates": [j for j, v in items.items() if v["disposition"] == DISPOSITION],
                "nonkill": True,
                "note": "import-invalid candidates are NONKILL: not killed, not survived, not equivalent, never CR "
                        "'incompetent', never removed from the kept universe; item_s includes the diagnosis pair "
                        "(whole cost); no cap is derived from import errors alone"}
    except Exception as exc:                  # noqa: BLE001 - the report must still be written
        return {"error": f"{type(exc).__name__}: {exc}"}


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
            plan=PLAN_PATH, _test_exec_factory=None, _test_harness_anywhere: bool = False,
            _test_allow_git_src_root: bool = False, _test_long_paths_reader=None, _test_diag_runner=None,
            _test_protected=None) -> dict:
    """One calibration session. See the module docstring. ``_test_exec_factory``, ``_test_harness_anywhere`` and
    ``_test_diag_runner`` are TEST-ONLY (the CLI cannot pass them); the real path is real_exec with the --src-root
    harness and the diagnosis children through cr_guard.run_contained. ``plan`` is the external sampling plan v2
    (the CLI always uses the reviewed PLAN_PATH); whatever file is given must pass validate_plan."""
    t0 = time.monotonic()
    src_root, work_root = Path(src_root), Path(work_root)
    harness = load_harness(src_root, fresh=False, _test_harness_anywhere=_test_harness_anywhere,
                           _test_allow_git_src_root=_test_allow_git_src_root)
    base_factory = _test_exec_factory or cr_coord.real_exec
    diag_box: dict = {}

    def factory(c):                          # X26: every seam is the policy seam over real_exec(c) (completion)
        return policy_seam(base_factory(c))

    def screen_factory(c):                   # 15c-P2: the screening seam also carries the diagnosis
        return policy_seam(base_factory(c), diag=diag_box["diag"])
    conf = _conf(src_root, config)
    cfg = cr_preflight.config_from_toml(conf["dir"] / "cr.toml")
    cfg_id = conf["rel"][len(EVID_REL) + 1:]
    identity = cr_coord.config_identity(cfg, conf["dir"] / "cr.toml", config_id=cfg_id)
    cp = cr_preflight.copy_paths_for(src_root, cfg)
    inv_p, inv = _calibration(conf)
    items_by_id = {i["job_id"]: i for i in inv["items"]}
    pin = {inv["module_rel"]: inv["source_sha256"]}
    shards, pool = _shards(src_root, conf["module"])
    croot = work_root / cfg_id.replace("/", "__")
    budget = _path_budget(src_root, work_root, croot, items_by_id, cp, shards)
    host = _host_check(_test_long_paths_reader or _read_long_paths)
    order = _check_order(src_root, work_root, conf, review_ref)
    _check_harness_budgets()
    plan_doc, entry, plan_sum = validate_plan(plan, src_root, cfg_id)              # 15c-P2: refuse on any mismatch
    protected = protected_paths(src_root)                                          # fix round 1 (A2)
    if _test_protected is not None:                                                # TEST-ONLY synthetic fixtures
        protected = {"paths": [str(p) for p in _test_protected], "verified_from_source": {}, "test_fixtures": True}
    _check_roots(plan_doc, plan_sum, work_root)
    cal = list(entry["calibration_batch"])
    if not cal or len(cal) > SAMPLE_SIZE or any(j not in items_by_id for j in cal):
        _plan_refuse(plan_sum["path"], f"{cfg_id}: the calibration batch is empty, too long or not in the inventory")
    if croot.exists():
        _refuse(f"config root {croot} already exists: one fresh session root per session (no rerun, no retry, no "
                f"resume, no new root)")
    croot.mkdir(parents=True)
    sroot = croot / "session-000"
    probe_sha = _sha(PROBE_PATH)
    diag_box["diag"] = Diagnoser(eligible=entry["eligible"], clock=clock, session_root=sroot, src_root=src_root,
                                 copy_paths=cp, cfg=cfg, pin=pin, plan_summary=plan_sum, probe_sha=probe_sha,
                                 runner=_test_diag_runner, protected=protected["paths"])
    rep = {"schema": SCHEMA, "kind": "calibration", "config_id": cfg_id, "src_root": str(src_root),
           "work_root": str(work_root), "config_root": str(croot), "session_root": str(sroot),
           "manifest": harness["manifest"], "src_root_verified": harness["src_root_verified"],
           "harness": {k: harness[k] for k in ("dir", "modules", "pinned_to_src_root")},
           "driver_sha256": _sha(__file__), "probe_sha256": probe_sha, "policy_version": POLICY_VERSION,
           "plan": plan_sum, "bounds": expected_bounds(), "protected": protected, "probe_scope": PROBE_SCOPE,
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
                                       exec_seam=screen_factory(cfg), clock=clock, config=identity, cfg=cfg,
                                       preflight_dir=conf["dir"] / "preflight")
        finally:
            sp = sroot / "batch_000_state.json"
            if sp.is_file():
                rep["screening"] = _state_view(json.loads(sp.read_text(encoding="utf-8")), sp)
            rep["accounting"] = _accounting(rep, entry, diag_box["diag"])
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
    why = cap_measurement_check(s)                                                         # 15c-P2 (P5)
    if why is not None:
        _refuse(f"derive-cap refused for {sroot}: {why}")
    cr_toml = Path(s["config"]["cr_toml"])
    cfg = cr_preflight.config_from_toml(cr_toml)
    identity = cr_coord.config_identity(cfg, cr_toml, config_id=cid)
    cmin = _cap_floor(rep)                                                                 # fix round 3 (R1)
    excluded = import_invalid_ids(s)
    results = s.get("results") or {}
    for j in excluded:                                                  # fix round 3 (N4): never on unverified records
        dp = sroot / "jobs" / j / "dg" / "disposition.json"
        want = ((results.get(j) or {}).get("diagnosis") or {}).get("disposition_sha256")
        if not dp.is_file() or not want or _sha(dp) != want:
            _refuse(f"derive-cap refused for {sroot}: the disposition record of excluded item {j} is missing or is not "
                    f"the bytes the session recorded")
    n_clean = len(s["batch"]) - len(excluded)
    if n_clean < cmin:
        _refuse(f"derive-cap refused for {sroot}: {n_clean} clean killed / survived measurements, fewer than the "
                f"plan's cap_min_measurements {cmin} (import-invalid candidates are not measurements)")
    if not excluded:
        return cr_coord.derive_cap(state, out=sroot.parent / "derived_cap.json", identity=identity, min_items=cmin)
    # fix round 2 (review M6, ruling P5): the import-invalid candidates are not calibration measurements. The cap is
    # derived from a write-once measurement set - the state minus those ids, bound to the state's bytes - that also
    # records each excluded id with its whole item cost and its diagnostic cost.
    measured = [j for j in s["batch"] if j not in excluded]
    ex = {}
    for j in excluded:
        dp = sroot / "jobs" / j / "dg" / "disposition.json"
        d = json.loads(dp.read_text(encoding="utf-8")) if dp.is_file() else {}
        costs = d.get("costs") or {}
        ex[j] = {"item_s": (s.get("item_s") or {}).get(j), "diagnostic_s": round(sum(costs.values()), 3),
                 "costs": costs, "disposition": str(dp), "disposition_sha256": _sha(dp) if dp.is_file() else None,
                 "label": (s.get("labels") or {}).get(j)}
    meas = dict(s, batch=measured, done=[j for j in (s.get("done") or []) if j not in excluded],
                item_s={j: v for j, v in (s.get("item_s") or {}).items() if j not in excluded},
                labels={j: v for j, v in (s.get("labels") or {}).items() if j not in excluded},
                results={j: v for j, v in (s.get("results") or {}).items() if j not in excluded},
                derived_from={"path": str(state), "sha256": _sha(state)}, excluded_import_invalid=ex,
                measurement_rule="import-invalid candidates (NONKILL) are excluded from the calibration measurements; "
                                 "the cap is floor((session - fence) / max measured item) over the rest")
    mp = sroot.parent / "cap_measurements.json"
    _write_once(mp, meas)
    check_cap_measurements(mp)                                                             # fix round 3 (N5)
    return cr_coord.derive_cap(mp, out=sroot.parent / "derived_cap.json", identity=identity, min_items=cmin)


def _cap_floor(rep: dict) -> int:
    """R1: the plan's cap_min_measurements, from the exact plan file the session recorded (path + sha256)."""
    pl = rep.get("plan") or {}
    p = Path(str(pl.get("path") or ""))
    if not p.is_file() or _sha(p) != pl.get("sha256"):
        _refuse(f"derive-cap refused: the session's sampling plan {p} is missing or not the recorded bytes")
    cmin = (json.loads(p.read_text(encoding="utf-8")).get("bounds") or {}).get("cap_min_measurements")
    if type(cmin) is not int or not 1 <= cmin <= SAMPLE_SIZE:
        _refuse(f"derive-cap refused: plan cap_min_measurements {cmin!r} is not an int in 1..{SAMPLE_SIZE}")
    return cmin


def check_cap_measurements(path) -> dict:
    """N5: a cap measurement set must still match the state bytes it records (derived_from path + sha256)."""
    m = json.loads(Path(path).read_text(encoding="utf-8"))
    src = m.get("derived_from") or {}
    sp = Path(str(src.get("path") or ""))
    if not sp.is_file() or _sha(sp) != src.get("sha256"):
        _refuse(f"{Path(path).name} does not match the calibration state it records ({sp}): refused")
    return m


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
