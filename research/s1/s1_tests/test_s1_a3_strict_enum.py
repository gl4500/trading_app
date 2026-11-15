"""A3 H4-CX (Codex exact-head review of 5370bce, finding H4-CX-2 / P1): strict directory enumeration.

Runtime CPython 3.12 `pathlib._WildcardSelector._select_from` wraps `os.scandir` in `except OSError: pass`, so every
`Path.glob` / `Path.rglob` turned a real enumeration failure into "no entries", under the H4 `except OSError` handlers
(Erratum 2 r4 G3.4: a listing error never means empty, absent or OK; Clarification 1 r2 C5.1 / O-C5: a failed
directory enumeration, even raised as FileNotFoundError, is never confirmed absence - it refuses with no new INVALID).

Every product glob now goes through `s1_common.strict_glob` (os.scandir per `/`-segment, fnmatch matching): a missing
ROOT is the typed absence of an optional directory ([]); every other enumeration error raises - a nested directory's
FileNotFoundError included. Each product site turns that error into a refusal with no row (h4cx_sites.md).

The behavioural tests inject the failure at the `os.scandir` layer for one specific directory (never `Path.glob`),
with real files present, and always run a control on the same fixture without the injection. REDs are assertions (B3):
on the H5a base (ce4a53b) the injected cases pass the gate or return an empty inventory."""
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import s1_checkpoint as ck
import s1_common as c
import s1_journal as j
import s1_run as r
import s1_seal as z
import s1_slot as sl
import s1_stage as stg
import s1_trial as t
from test_s1_a3_m4_pass import gate_outcome, jrows, no_new_invalid, three_qualified

REG = r"INVALID \(registration-artifact\)"
LISTED = "could not be listed"
FAILURES = {"permission": lambda: PermissionError(13, "listing denied (simulated)"),
            "generic-oserror": lambda: OSError(5, "I/O error (simulated)"),
            "enumeration-filenotfound": lambda: FileNotFoundError(2, "ambiguous listing failure (simulated)")}


def fail_scandir(monkeypatch, target, exc):
    """os.scandir raises `exc` for the directory `target` only (the layer pathlib's glob swallows); returns the list
    of injected calls, so a test can assert that the injection was actually reached."""
    real, hits, target = os.scandir, [], Path(target)

    def scandir(path="."):
        if isinstance(path, (str, os.PathLike)) and Path(path) == target:
            hits.append(str(path))
            raise exc
        return real(path)
    monkeypatch.setattr(os, "scandir", scandir)
    return hits


def outcome(fn, *a, **kw):
    """fn's return value, or the SystemExit it raised (B3: callers assert on it). A raw OSError is a failure."""
    try:
        return fn(*a, **kw)
    except SystemExit as e:
        return e
    except OSError as e:
        pytest.fail(f"a raw {type(e).__name__} escaped ({e}): neither a refusal nor a result")


def helper():
    got = getattr(c, "strict_glob", None)
    assert got is not None, "s1_common.strict_glob is missing (H4-CX-2)"
    return got


def build_tree(root: Path) -> Path:
    """A healthy tree with every shape the product patterns enumerate."""
    files = ["seals/2026-10-26.json", "seals/2026-10-27.json", "seals/notes.txt",
             "captures/2026-10-26/20261026T204500Z.attempt.json",
             "captures/2026-10-26/20261026T204500Z.resolution.json",
             "captures/2026-10-26/20261026T204500Z.report.json",
             "captures/2026-10-26/20261026T204500Z/backup.sqlite3",
             "captures/2026-10-27/20261027T204500Z.attempt.json", "captures/.hidden.json",
             "final_snapshot/attempt-01/meta.json", "final_snapshot/attempt-02/meta.json",
             "final_snapshot/report.json", "audit/manifest.json", "audit/pages/a/b.json", "audit/pages/c.json",
             "code/s1_common.py", "code/s1_extra.py", "code/e1_sim.py"]
    for f in files:
        p = root / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}", encoding="utf-8")
    (root / "captures" / "2026-10-28").mkdir()                          # an empty day directory
    return root


# ------------------------------------------------------------------------------------------- unit: strict_glob
def test_missing_root_is_empty(tmp_path):
    g = helper()
    assert g(tmp_path / "absent", "*.json") == []
    assert g(tmp_path / "absent", "*/*") == []
    assert g(tmp_path / "absent" / "deeper", "**/*") == []


@pytest.mark.parametrize("kind", ["permission", "generic-oserror"])
def test_root_enumeration_error_raises(tmp_path, monkeypatch, kind):
    g = helper()
    build_tree(tmp_path)
    hits = fail_scandir(monkeypatch, tmp_path / "seals", FAILURES[kind]())
    with pytest.raises(OSError, match=r"simulated"):
        g(tmp_path / "seals", "*.json")
    assert hits


@pytest.mark.parametrize("kind", list(FAILURES))
def test_nested_enumeration_error_raises(tmp_path, monkeypatch, kind):
    """A nested directory listed a moment earlier: any OSError - FileNotFoundError included (O-C5) - raises."""
    g = helper()
    build_tree(tmp_path)
    for target, root, pattern in ((tmp_path / "captures" / "2026-10-27", tmp_path / "captures", "*/*"),
                                  (tmp_path / "captures", tmp_path, "captures/*/*.attempt.json"),
                                  (tmp_path / "audit" / "pages" / "a", tmp_path, "audit/**/*")):
        with pytest.MonkeyPatch.context() as m:              # (never monkeypatch.undo(): the network guard stays)
            hits = fail_scandir(m, target, FAILURES[kind]())
            with pytest.raises(OSError, match=r"simulated"):
                g(root, pattern)
        assert hits, target


@pytest.mark.parametrize("root,pattern", [("seals", "*.json"), ("captures", "*"), ("captures", "*/*"),
                                          ("captures", "*/*.report.json"), ("captures/2026-10-26", "*.attempt.json"),
                                          ("captures/2026-10-26", "*.resolution.json"),
                                          ("final_snapshot", "attempt-*"), ("code", "s1_*.py"),
                                          (".", "captures/*/*"), (".", "captures/*/*.attempt.json"),
                                          (".", "seals/*.json"), (".", "final_snapshot/attempt-*"),
                                          (".", "audit/**/*"), ("audit", "**/*")])
def test_matches_path_glob_on_a_healthy_tree(tmp_path, root, pattern):
    g = helper()
    build_tree(tmp_path)
    base = tmp_path / root
    assert g(base, pattern) == sorted(base.glob(pattern)), pattern


def test_recursive_matches_path_rglob(tmp_path):
    g = helper()
    build_tree(tmp_path)
    d = tmp_path / "audit"
    assert g(d, "**/*") == sorted(d.rglob("*"))
    assert [p for p in g(tmp_path, "audit/**/*") if p.is_file()] == sorted(p for p in d.rglob("*") if p.is_file())


# ----------------------------------------------------------------- behavioural: the gate (evidence_check, inventories)
def stray_claim(root):
    """A slot claim with no journal row on a post-START close with no other evidence (F3: a violation)."""
    out = Path(root) / "s1_out"
    cal = c.load_json(out / "prereg.json")["calendar"]
    day = next(d for d in cal if d["date"] == "2026-10-29")
    s = z.schedule(day, cal)[0]
    n = sl.names(out, s, day["date"])
    n["claim"].parent.mkdir(parents=True, exist_ok=True)
    n["claim"].write_text("{}", encoding="utf-8")
    return n["claim"]


@pytest.mark.parametrize("kind", list(FAILURES))
@pytest.mark.parametrize("inject", ["control", "captures-root", "captures-day"])
def test_gate_stray_capture_enumeration_failure_refuses(tmp_path, monkeypatch, inject, kind):
    """A stray claim is present. Control: INVALID (registration-artifact). The captures directory (or the stray's day
    directory) cannot be listed: a refusal with no new INVALID, no aborted.json - never the empty inventory."""
    three_qualified(tmp_path)
    claim = stray_claim(tmp_path)
    out = tmp_path / "s1_out"
    before = [x.sha for x in jrows(tmp_path)]
    if inject == "control":
        with pytest.raises(SystemExit, match=REG):
            t.gate(tmp_path, "probe")
        return
    target = out / "captures" if inject == "captures-root" else claim.parent
    hits = fail_scandir(monkeypatch, target, FAILURES[kind]())
    e = gate_outcome(tmp_path, "probe")
    assert hits, "the injection was never reached"
    assert isinstance(e, SystemExit), "an enumeration failure passed the gate (the stray was not seen)"
    assert LISTED in str(e), str(e)
    assert no_new_invalid(tmp_path, before), "an enumeration failure became an INVALID"
    assert not (out / "aborted.json").exists()


@pytest.mark.parametrize("kind", list(FAILURES))
def test_evidence_check_never_takes_the_no_evidence_branch(tmp_path, monkeypatch, kind):
    """Codex's probe shape: rows=[] and a stray claim. Healthy: the stray is a subject; captures unlistable: the early
    no-files/no-rows branch must not accept the empty listing (evidence_check never returns [])."""
    three_qualified(tmp_path)
    stray_claim(tmp_path)
    out = tmp_path / "s1_out"
    healthy = sl._file_subjects(out)
    assert healthy
    hits = fail_scandir(monkeypatch, out / "captures", FAILURES[kind]())
    got = outcome(sl._file_subjects, out)
    assert isinstance(got, SystemExit) and LISTED in str(got), got
    got = outcome(sl.evidence_check, SimpleNamespace(out=out, rows=[]))
    assert got != [], "the early no-evidence branch accepted an unlistable captures/"
    assert isinstance(got, SystemExit) and LISTED in str(got), got
    assert hits


def stray_seal(root):
    """A seal file of a post-START close with no seal stage row (E2.4 r3: registration-artifact)."""
    p = Path(root) / "s1_out" / "seals" / "2026-10-30.json"
    p.write_text("{}", encoding="utf-8")
    return p


@pytest.mark.parametrize("kind", list(FAILURES))
@pytest.mark.parametrize("inject", ["control", "seals"])
def test_gate_seals_inventory_failure_refuses(tmp_path, monkeypatch, inject, kind):
    three_qualified(tmp_path)
    stray_seal(tmp_path)
    out = tmp_path / "s1_out"
    before = [x.sha for x in jrows(tmp_path)]
    if inject == "control":
        with pytest.raises(SystemExit, match=REG):
            t.gate(tmp_path, "probe")
        return
    hits = fail_scandir(monkeypatch, out / "seals", FAILURES[kind]())
    e = gate_outcome(tmp_path, "probe")
    assert hits and isinstance(e, SystemExit), "a seals/ enumeration failure passed the gate"
    assert LISTED in str(e), str(e)
    assert no_new_invalid(tmp_path, before) and not (out / "aborted.json").exists()


@pytest.mark.parametrize("inject", ["control", "captures"])
def test_gate_listing_refusal_held_until_e55(tmp_path, monkeypatch, inject):
    """H4 ordering (Clarification 1 C5.1; H4 fix rounds 1-2): an evidence-table listing refusal is held like a C5
    refusal - the E5.5 check still runs, and the stop-gap recovery runs with publish=False (a refusal does no work)."""
    three_qualified(tmp_path)
    stray_claim(tmp_path)
    out = tmp_path / "s1_out"
    calls = []
    real_e55, real_gap = t.opening_manifest_check, z.stop_gap_recover
    monkeypatch.setattr(t, "opening_manifest_check", lambda gv, a=None: (calls.append("E5.5"), real_e55(gv, a))[1])
    monkeypatch.setattr(z, "stop_gap_recover", lambda gv, *, publish=True: (calls.append(("gap", publish)),
                                                                            real_gap(gv, publish=publish))[1])
    if inject == "control":
        with pytest.raises(SystemExit, match=REG):
            t.gate(tmp_path, "probe")
        assert calls == []                                    # the F3 violation is committed before E5.5
        return
    fail_scandir(monkeypatch, out / "captures", PermissionError(13, "listing denied (simulated)"))
    e = gate_outcome(tmp_path, "probe")
    assert isinstance(e, SystemExit) and LISTED in str(e), e
    assert calls == [("gap", False), "E5.5"], calls


# ------------------------------------------------------------------------------- behavioural: every other product site
def _seed(root):
    st = three_qualified(root)
    stray_claim(root)
    out = Path(root) / "s1_out"
    (out / "stop.json").write_text("{}", encoding="utf-8")            # (stop_problems enumerates only with a stop)
    (out / "final_snapshot" / "attempt-01").mkdir(parents=True, exist_ok=True)
    bare = Path(root) / "bare" / "s1_out"                             # an unregistered root (preregistration_problems
    (bare / "seals").mkdir(parents=True)                              # enumerates seals/ only before a registration)
    (bare / "seals" / "2026-10-26.json").write_text("{}", encoding="utf-8")
    return st, out


def _sites(out):
    """(site id, call, the directory whose enumeration fails) for every product glob site outside the gate tests."""
    cap, seals, fs = out / "captures", out / "seals", out / "final_snapshot"
    bare = out.parent / "bare" / "s1_out"
    day = "2026-10-26"
    return [
        ("s1_common.bundle_manifest", lambda: c.bundle_manifest(), c.HERE),
        ("s1_common._day_success", lambda: c._day_success(out, day), cap / day),
        ("s1_common._post_start_capture[captures]", lambda: c._post_start_capture(out, None), cap),
        ("s1_common._post_start_capture[seals]", lambda: c._post_start_capture(out, None), seals),
        ("s1_common._local_opening_evidence[seals]", lambda: c._local_opening_evidence(out), seals),
        ("s1_common._local_opening_evidence[captures]", lambda: c._local_opening_evidence(out), cap),
        ("s1_common.opening_orphans", lambda: c.opening_orphans(out, "2026-10-23"), cap),
        ("s1_common.preregistration_problems", lambda: c.preregistration_problems(bare), bare / "seals"),
        ("s1_checkpoint._seal_files", lambda: ck._seal_files(out), seals),
        ("s1_checkpoint._read_seals", lambda: ck._read_seals(out, {}), seals),
        ("s1_checkpoint._next_attempt", lambda: ck._next_attempt(fs), fs),
        ("s1_checkpoint.ok_attempts", lambda: ck.ok_attempts(fs), fs),
        ("s1_run._seals", lambda: r._seals(out), seals),
        ("s1_run._ok_attempts", lambda: r._ok_attempts(fs), fs),
        ("s1_run._restarts", lambda: r._restarts({}, {}, out), cap),
        ("s1_run._capture_notes", lambda: r._capture_notes(out, []), cap),
        ("s1_seal.pending_closes", lambda: z.pending_closes(out), cap),
        ("s1_seal._seal_index", lambda: z._seal_index(out), seals),
        ("s1_seal.stop_was_persisted", lambda: z.stop_was_persisted(out), cap),
        ("s1_seal.stop_problems", lambda: z.stop_problems(out, None, None, recheck=False), cap),
        ("s1_slot._stray_files", lambda: sl._stray_files(out), cap),
        ("s1_stage._artifacts_present", lambda: stg._artifacts_present(out, "audit"), out / "audit"),
        ("s1_stage._seals_on_disk", lambda: stg._seals_on_disk(out), seals),
    ]


SITE_IDS = [s for s, _, _ in _sites(Path("."))]


@pytest.mark.parametrize("site", SITE_IDS)
def test_site_refuses_on_enumeration_failure(tmp_path, monkeypatch, site):
    """Every product enumeration site: the control returns normally on the same fixture; with the directory
    unlistable the site refuses (a SystemExit naming the listing) - never an empty inventory and never a raw OSError
    for a caller's `except OSError` to turn into "absent", a problem or an INVALID."""
    _, out = _seed(tmp_path)
    _, call, target = next(x for x in _sites(out) if x[0] == site)
    ctrl = outcome(call)
    assert not isinstance(ctrl, SystemExit), f"control refused: {ctrl}"
    hits = fail_scandir(monkeypatch, target, PermissionError(13, "listing denied (simulated)"))
    got = outcome(call)
    assert hits, f"{site}: the injection at {target} was never reached"
    assert isinstance(got, SystemExit) and LISTED in str(got), f"{site}: {got!r}"


def test_bundle_hash_refuses_when_the_code_directory_is_unlistable(monkeypatch):
    """A3.1: an unlistable code directory never hides an unexpected s1_*.py (an empty `unexpected` would hash as the
    approved bundle)."""
    ok = c.bundle_sha256()
    fail_scandir(monkeypatch, c.HERE, OSError(5, "I/O error (simulated)"))
    got = outcome(c.bundle_sha256)
    assert got != ok and isinstance(got, SystemExit) and LISTED in str(got), got


def test_score_attempt_listing_refusal_is_no_score_abort(tmp_path, monkeypatch):
    """F4.9: a listing refusal inside the score computation is a local fault - it propagates (refused, no PREPARED),
    never the ABORTED s1.json / StageAbort(score-aborted) of a computation error."""
    lr = getattr(c, "ListingRefusal", None)
    assert lr is not None, "s1_common.ListingRefusal is missing"
    put = []
    sw = SimpleNamespace(gv=SimpleNamespace(out=tmp_path), mailbox=None, trial_id="t",
                         put=lambda rel, data: put.append(rel))

    def boom(out, mailbox):
        raise lr("seals/*.json could not be listed (simulated)")
    monkeypatch.setattr(r, "_score", boom)
    got = None
    try:
        r._score_attempt(sw)
    except BaseException as e:                                 # noqa: BLE001 - the outcome is asserted below
        got = e
    assert isinstance(got, lr) and not isinstance(got, stg.StageAbort), repr(got)
    assert put == [], "an ABORTED s1.json was staged for a listing refusal"


def test_opening_ack_fields_never_swallow_a_listing_refusal(tmp_path, monkeypatch):
    """E5.5 / F7.2 issuer fields: a listing refusal while deriving opening_slot propagates - it never leaves the field
    'not derivable' (absent)."""
    lr = getattr(c, "ListingRefusal", None)
    assert lr is not None, "s1_common.ListingRefusal is missing"
    import s1_gates

    def boom(out, mailbox=None):
        raise lr("the S1 code directory could not be listed (simulated)")
    monkeypatch.setattr(s1_gates, "verified_audit", boom)
    got = outcome(t._opening_derived, tmp_path, tmp_path / "s1_out", [], {"evidence_manifest_sha256": "x"}, None)
    assert isinstance(got, lr), repr(got)


def test_no_product_module_calls_path_glob():
    """Every `.glob(` / `.rglob(` of the product modules is replaced (H4-CX-2 2: every product glob)."""
    bad = []
    for p in sorted(c.HERE.glob("s1_*.py")):
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if ".glob(" in line or ".rglob(" in line:
                bad.append(f"{p.name}:{i}")
    assert bad == [], bad


def test_journal_rows_untouched_by_site_refusals(tmp_path):
    """The site refusals do no work: no journal row is appended by any of them."""
    _, out = _seed(tmp_path)
    before = [x.sha for x in jrows(tmp_path)]
    for site, call, target in _sites(out):
        with pytest.MonkeyPatch.context() as m:
            fail_scandir(m, target, OSError(5, "I/O error (simulated)"))
            outcome(call)
    assert [x.sha for x in jrows(tmp_path)] == before
    assert j.first(jrows(tmp_path), "TRIAL-INVALID") is None


# ================================================================== A3 H4-CX fix round 1 (task review 2026-11-14)
def _activate_on_call(monkeypatch, module, name, target, exc):
    """Wrap module.name so that the os.scandir failure at `target` is active ONLY while that call runs (the earlier
    listings of the same directory in the invocation succeed: the transient fault of the review's I-1 scenario)."""
    real_fn, real_scandir, hits = getattr(module, name), os.scandir, []

    def wrapped(*a, **kw):
        def scandir(path="."):
            if isinstance(path, (str, os.PathLike)) and Path(path) == Path(target):
                hits.append(str(path))
                raise exc
            return real_scandir(path)
        with pytest.MonkeyPatch.context() as m:
            m.setattr(os, "scandir", scandir)
            return real_fn(*a, **kw)
    monkeypatch.setattr(module, name, wrapped)
    return hits


def test_run_ack_problems_never_turns_a_listing_refusal_into_a_problem(tmp_path, monkeypatch):
    """Review I-1: s1_gates.run_ack_problems enclosed bundle_sha256 (site #1) in `except SystemExit` -> "RUN-ACK
    unverifiable", which the score turns into ABORTED-INVALID. Control: [] on the same fixture."""
    import s1_gates
    three_qualified(tmp_path)
    out = tmp_path / "s1_out"
    pr = c.load_json(out / "prereg.json")
    assert s1_gates.run_ack_problems(out, pr, tmp_path / "mailbox.sqlite3") == []
    hits = _activate_on_call(monkeypatch, s1_gates, "run_ack_problems", c.HERE, OSError(5, "I/O error (simulated)"))
    got = outcome(s1_gates.run_ack_problems, out, pr, tmp_path / "mailbox.sqlite3")
    assert hits, "the injection was never reached"
    assert isinstance(got, SystemExit) and LISTED in str(got), f"converted into a registration problem: {got!r}"


@pytest.mark.parametrize("inject", ["control", "code-directory-in-run-ack-problems"])
def test_score_listing_refusal_in_registration_check_is_no_invalid(tmp_path, monkeypatch, inject):
    """Review I-1, through the score path: the code directory becomes unlistable only inside the RUN-ACK check of
    the score computation (its own earlier bundle listings succeed). The score attempt refuses (the ListingRefusal
    propagates): no ABORTED-INVALID report, no staged s1.json, no journal row, no aborted.json."""
    import s1_gates
    three_qualified(tmp_path)
    out = tmp_path / "s1_out"
    before = [x.sha for x in jrows(tmp_path)]
    put = []
    sw = SimpleNamespace(gv=SimpleNamespace(out=out), mailbox=tmp_path / "mailbox.sqlite3", trial_id="t",
                         put=lambda rel, data: put.append(rel))
    if inject == "control":
        rep = r._score_attempt(sw)
        assert not any("RUN-ACK unverifiable" in x for x in rep.get("reasons", [])), rep.get("reasons")
        return
    hits = _activate_on_call(monkeypatch, s1_gates, "run_ack_problems", c.HERE,
                             PermissionError(13, "sharing violation (simulated)"))
    try:
        got = r._score_attempt(sw)
    except BaseException as e:                                 # noqa: BLE001 - the outcome is asserted below
        got = e
    assert hits, "the injection was never reached"
    assert isinstance(got, c.ListingRefusal) and not isinstance(got, stg.StageAbort), \
        f"a listing failure in the RUN-ACK check became a score result: {got!r}"
    assert put == [], "an s1.json was staged"
    assert [x.sha for x in jrows(tmp_path)] == before and not (out / "aborted.json").exists()


@pytest.mark.parametrize("field", ["T", "L", "B", "cap"])
@pytest.mark.parametrize("sign", [1, -1], ids=["huge", "huge-negative"])
def test_verdict_huge_int_is_not_ready_never_raises(field, sign):
    """Review M-1: an int beyond the float range (math.isfinite raises OverflowError) is an invalid value: NOT READY
    with a reason, in both routes, never an exception."""
    import importlib.util as iu
    p = Path(__file__).resolve().parents[1] / "s1_evidence" / "a3" / "m4_workload" / "verdict_rule.py"
    spec = iu.spec_from_file_location("m4_verdict_rule_fr1", p)
    v = iu.module_from_spec(spec)
    spec.loader.exec_module(v)
    huge = sign * 10 ** 400
    run_ = {"id": "bad", "L": 0.0, "T": 1.0, "control_ok": True}
    kw, b = {}, 0.0
    if field in ("T", "L"):
        run_[field] = huge
    elif field == "B":
        b = huge
    else:
        kw["cap"] = huge
    calls = [("b_conditional", lambda: v.b_conditional([run_], b, workloads_resolved=True, injected_resolved=True,
                                                       **kw))]
    if field != "B":
        calls.insert(0, ("verdict", lambda: v.verdict([run_], **kw)))
    for label, fn in calls:
        try:
            got = fn()
        except Exception as e:                                 # noqa: BLE001 - asserted absent
            pytest.fail(f"{label} raised {type(e).__name__} for a huge {field}: {e}")
        if label == "b_conditional" and field == "L":           # L is ignored in B-CONDITIONAL mode
            assert got["label"] == "B-CONDITIONAL READY", got
            continue
        assert got.get("verdict", got.get("label")) in ("NOT READY", "B-CONDITIONAL NOT READY"), (label, got)
        assert any(("cap" if field == "cap" else f"{field} ") in x for x in got["reasons"]), (label, got["reasons"])


class _Listed:
    """An os.scandir result replayed from already-read entries (a context manager and an iterator, as os.scandir)."""

    def __init__(self, entries):
        self.entries = entries

    def __enter__(self):
        return iter(self.entries)

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self.entries)


def test_pending_closes_day_vanishing_between_listings_refuses(tmp_path, monkeypatch):
    """Review M-3: a captures/<day> directory returned by the captures/ listing that disappears before its own
    listing is an ambiguous enumeration (O-C5): a refusal, never "no pending claim". Control: the day is pending."""
    import shutil
    out = tmp_path / "s1_out"
    day = out / "captures" / "2026-10-29"
    day.mkdir(parents=True)
    (out / "seals").mkdir()
    (day / "20261029T204500Z.attempt.json").write_text("{}", encoding="utf-8")
    assert z.pending_closes(out) == {"2026-10-29"}
    real, done = os.scandir, []

    def scandir(path="."):
        if isinstance(path, (str, os.PathLike)) and Path(path) == out / "captures" and not done:
            with real(path) as it:
                entries = list(it)
            shutil.rmtree(day)                                 # vanishes between the two listings
            done.append(1)
            return _Listed(entries)
        return real(path)
    monkeypatch.setattr(os, "scandir", scandir)
    got = outcome(z.pending_closes, out)
    assert done, "the captures/ listing was never reached"
    assert isinstance(got, SystemExit) and LISTED in str(got), f"a vanished day read as no pending claim: {got!r}"


@pytest.mark.parametrize("inject", ["control", "seals-at-capture"])
def test_checkpoint_capture_with_unlistable_seals_refuses(tmp_path, monkeypatch, inject):
    """Review M-4: a real post-START checkpoint capture; seals/ becomes unlistable when the capture reads the seals
    (inside the Worker, after the SLOT-INTENT). The command refuses: no SLOT-QUALIFIED / SLOT-FAILED / TRIAL-INVALID
    row from that observation, no aborted.json, no seal; the Worker released the slot lock. Control: INTENT +
    QUALIFIED on the same fixture."""
    from datetime import timedelta

    import s1_locks as L
    from conftest import S1_PROCESS, S1_RECEIPT, _Clock, s1_ack, s1_state
    st_ = s1_state(tmp_path, "2026-10-26T13:30:00+00:00")
    with _Clock(st_["prereg_at"]):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    s1_ack(tmp_path, "prereg-ack", "S1-PREREG-ACK", st_["prereg_at"] + timedelta(minutes=1))
    out = tmp_path / "s1_out"
    day = next(d for d in st_["calendar"] if d["date"] == "2026-10-26")
    sch = z.close_of(day["date"], st_["calendar"]) + timedelta(minutes=45)
    at = sch + timedelta(seconds=30)
    before = [x.sha for x in jrows(tmp_path)]
    hits = []
    if inject != "control":
        hits = _activate_on_call(monkeypatch, ck, "_read_seals", out / "seals",
                                 PermissionError(13, "listing denied (simulated)"))

    def go():
        with _Clock(at):
            return ck.run_checkpoint(tmp_path, st_["ledger"].path, sch, lambda reference=None: dict(S1_RECEIPT),
                                     lambda: dict(S1_PROCESS), tmp_path / "crash.log", now=lambda: at)
    got = outcome(go)
    new = [x for x in jrows(tmp_path) if x.sha not in before]
    kinds = [x.kind for x in new if x.subject == j.slot_subject(sch)]
    if inject == "control":
        assert not isinstance(got, SystemExit), got
        assert kinds == ["SLOT-INTENT", "SLOT-QUALIFIED"], kinds
        return
    assert hits, "the capture never read the seals"
    assert isinstance(got, SystemExit) and LISTED in str(got), f"the capture did not refuse: {got!r}"
    assert kinds == ["SLOT-INTENT"], f"a row was based on the failed listing: {kinds}"
    assert all(x.kind != "TRIAL-INVALID" for x in new) and not (out / "aborted.json").exists()
    assert not (out / "seals" / f"{day['date']}.json").exists()
    lk = L.OwnershipLock(tmp_path, t.open_trial(tmp_path / "mailbox.sqlite3").trial_id,
                         L.slot_lock_name(j.slot_subject(sch)))
    lk.acquire()                                               # the Worker released it (no stale lock)
    lk.release()
