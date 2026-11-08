"""Addendum 3 rev 5 F10 'Other': the damage matrix - every non-empty subset of the nine elements x {bundle same,
changed} x {deleted, changed, unparseable}, at each commitment point. Exhaustive when S1_MATRIX_FULL=1 (evidence
a3/t14_matrix_full.txt); otherwise singletons, pairs, complements and the full set. Each case runs on a copy of the
commitment point's snapshot; the expected outcome comes from `oracle`; every refusal or INVALID has zero callbacks,
captures, provider requests and valuation calls."""
import itertools
import os
import re
import shutil
from datetime import timedelta
from pathlib import Path  # noqa: F401 (brief literal)

import pytest
import s1_checkpoint as ck
import s1_common as c
import s1_journal as j
import s1_run as r  # noqa: F401 (brief literal)
import s1_seal as z
import s1_trial as t
from conftest import Ledger, S1_RECEIPT, Spies, _Clock, s1_ack, s1_opening_checkpoint, s1_plan_audit, s1_state

START = "2026-10-26T13:30:00+00:00"
ELEMENTS = ("plan", "audit tree", "opening record (registry)", "opening record (witnesses)", "attestation",
            "prereg", "seal", "receipt", "stop")
# PLAN-6 / map 255: the 9 commitment points (every CREATED stage, with TRIAL-STOP + stop.json as one) plus the
# OPENING-ACK point = 10. INTENT/PREPARED boundaries are NOT matrix points: the per-stage state-table tests cover
# them (rows 122-129, 180, 228-229), and the matrix claims no more than this list.
POINTS = ("after-audit", "after-opening", "after-opening-ack", "after-start-attest", "after-prereg", "after-stop",
          "after-stop-attest", "after-final-plan", "after-final", "after-score")
EXISTS_FROM = {"plan": 0, "audit tree": 0, "opening record (registry)": 1, "opening record (witnesses)": 1,
               "seal": 1, "receipt": 1, "attestation": 3, "prereg": 4, "stop": 5}
FIRST_FINALIZATION_INTENT = POINTS.index("after-stop-attest")
JOURNAL_MEMBERS = {"seal", "attestation", "prereg"}          # F4 table: a stage artifact with no INTENT is a violation
FULL = os.environ.get("S1_MATRIX_FULL") == "1"


def paths(out, oc):
    """Element -> file(s). 'audit tree' is EVERY file under s1_out/audit/ (map 255 wording; PLAN-6), at least the
    fixed members when the tree does not exist yet."""
    audit = sorted(p for p in (out / "audit").rglob("*") if p.is_file()) or \
        [out / rel for rel in ("audit/calendar.json", "audit/manifest.json")]
    return {"plan": out / "plan.json", "audit tree": audit,
            "opening record (registry)": out / "registry" / "opening.json",
            "opening record (witnesses)": out / "witnesses" / "opening.json",
            "attestation": out / "attest_start.json", "prereg": out / "prereg.json",
            "seal": out / "seals" / f"{oc}.json", "receipt": out / "opening_receipt.json", "stop": out / "stop.json"}


def subsets():
    if FULL:
        return [s for n in range(1, len(ELEMENTS) + 1) for s in itertools.combinations(ELEMENTS, n)]
    small = [s for n in (1, 2) for s in itertools.combinations(ELEMENTS, n)]
    return small + [tuple(e for e in ELEMENTS if e != x) for x in ELEMENTS] + [ELEMENTS]


LEGACY_RECORDS = {"opening record (registry)", "opening record (witnesses)"}   # OQ-24: not journal substitutes


def oracle(point, subset, bundle, damage) -> str:
    """'invalid' | 'ok' | 'refuse-or-invalid'.
    - Every commitment point has journal rows, so a changed bundle is INVALID (bundle) (F6.4).
    - Damage to an element that exists at the point is INVALID (F3/F4 committed evidence; legacy records through
      OQ-19), except that deleting only stop.json before any finalization INTENT is the recoverable publication gap
      (F2.3): 'ok'.
    - Deleting elements that do not exist yet is a no-op: 'ok'.
    - A fabricated stage artifact (seal, attestation, prereg) with no INTENT is INVALID (F4 table).
    - A fabricated legacy-only file (registry/witness record, opening receipt, stop.json) before its time is outside
      every F-rule: the spec fixes no single outcome; both outcomes stop all work: 'refuse-or-invalid' (OQ-19/OQ-24).
    A3 Task 14 oracle check (singletons at every point; each resolution is in a3/t14_old_new.md, "Oracle"):
    - O-1 (OQ-24, OQ-19, E5.5): the two legacy opening records are bound by no journal row and are no member of the
      E5.5 evidence manifest; the OQ-19 detector reads them as parsed records. The matrix's "changed" (one trailing
      space) leaves the parsed record identical, so it damages no committed evidence and no recorded content: it is
      no damage ('ok' unless another element decides).
    - O-2 (OQ-19, A2 B3.1 kept by OQ-19): a registry/witness record that exists before the opening is the legacy
      "opening in progress" witness, which the trial gate's legacy detector accepts by design, and no F-rule (no stage
      artifact, F4) judges it: at the trial gate a fabricated legacy record adds nothing ('ok' unless another element
      decides). Downstream it is NOT harmless (fix round 1, review M-1): the real opening checkpoint then commits the
      opening INTENT and PREPARED and refuses "registry/opening.json already records different artifacts", and every
      later gate refuses the same way with no row (F4.7 recovery re-runs the same before_publish) until the file is
      deleted - fail-closed, availability only; disclosed to Codex at Stage-1 (no matrix point reaches it).
    - O-3 is NOT an oracle change (fix round 1, review I-2): the brief's INVALID stands. Task 14b fixed the product
      (s1_trial._plan_after_rows: after any row a damaged plan.json is INVALID) and removed the 26 default / 286
      exhaustive strict-xfail holds (`o3_held`) that Task 14 fix round 1 placed on those cases."""
    if bundle == "changed":
        return "invalid"
    idx = POINTS.index(point)
    live = [e for e in subset if EXISTS_FROM[e] <= idx and not (damage == "changed" and e in LEGACY_RECORDS)]  # O-1
    if live == ["stop"] and damage == "deleted" and idx < FIRST_FINALIZATION_INTENT:
        return "ok"                                                # F2.3 publication gap (only before stop_attest)
    if live:
        return "invalid"
    if damage == "deleted":
        return "ok"
    made = [e for e in subset if EXISTS_FROM[e] > idx and e not in LEGACY_RECORDS]              # O-2
    if not made:
        return "ok"
    if any(e in JOURNAL_MEMBERS for e in made):
        return "invalid"
    return "refuse-or-invalid"


def _build(root, point):
    """The real lifecycle up to `point` (synthetic ledgers; tmp mailbox)."""
    if point in ("after-audit", "after-opening", "after-opening-ack"):
        start, cal, oc, _ = s1_plan_audit(root, START)
        if point == "after-audit":
            return {"oc": oc, "now": z.close_of(oc, cal) + timedelta(hours=1)}
        s1_opening_checkpoint(root, Ledger(root / "ledger.sqlite3"), oc, cal, S1_RECEIPT)
        if point == "after-opening":
            return {"oc": oc, "now": z.close_of(oc, cal) + timedelta(hours=1)}
        from test_s1_a3_prestart import close_out
        w = close_out(root, cal, oc)
        s1_ack(root, "opening-ack", "S1-OPENING-ACK", w + timedelta(minutes=1))
        return {"oc": oc, "now": w + timedelta(minutes=2)}
    # conftest.s1_state(upto=...) (added in this task) stops the real lifecycle right after the named CREATED point
    st_ = s1_state(root, START, upto=point)
    return {"oc": st_["opening_close"], "now": st_["now"]}


@pytest.fixture(scope="module")
def snapshots(tmp_path_factory):
    """Each point's real lifecycle, built once per module run. A module-scoped fixture is set up before the
    function-scoped autouse guards of the first test, so it applies the same guards itself, by hand (ruling B4/C14:
    module-scoped builds run inside the guards): its own tmp mailbox (s1_common.MAILBOX), its own tmp receipt HMAC key
    (s1_receipt.HMAC_KEY) and the network guard (httpx transports and socket.create_connection refuse, as
    conftest.s1_no_network; fix round 1, review M-5)."""
    import socket
    import httpx
    import s1_receipt
    from conftest import s1_mailbox_init
    got = {}
    base = tmp_path_factory.mktemp("matrix")

    def refuse(*a, **kw):
        raise AssertionError("A3 network guard: a real network call was attempted")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(httpx.HTTPTransport, "handle_request", refuse)
        mp.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse)
        mp.setattr(socket, "create_connection", refuse)
        for p in POINTS:
            root = base / p
            root.mkdir()
            mp.setattr(c, "MAILBOX", root / "mailbox.sqlite3")             # module-scoped build: its own tmp mailbox
            mp.setattr(s1_receipt, "HMAC_KEY", root / "s1_receipt_hmac.key")
            s1_mailbox_init(root)
            got[p] = dict(_build(root, p), root=root)
    return got


def _invalid_rows(root) -> int:
    trials = t.trials(t.scan(root / "mailbox.sqlite3"))
    return sum(1 for tid, x in trials.items() for row in j.read_trial(tid, x.genesis, root / "mailbox.sqlite3")
               if row.kind == "TRIAL-INVALID")


CASES = [(p, s, b, d) for p in POINTS for s in subsets() for b in ("same", "changed")
         for d in ("deleted", "changed", "unparseable")]
PARAMS = [pytest.param(*case, id=f"{case[0]}|{'+'.join(case[1])}|{case[2]}|{case[3]}") for case in CASES]


@pytest.mark.parametrize("point,subset,bundle,damage", PARAMS)
def test_matrix(tmp_path, monkeypatch, snapshots, point, subset, bundle, damage):
    snap = snapshots[point]
    root = tmp_path / "root"
    shutil.copytree(snap["root"], root)
    monkeypatch.setattr(c, "MAILBOX", root / "mailbox.sqlite3")
    out = root / "s1_out"
    for e in subset:
        targets = paths(out, snap["oc"])[e]
        for p in (targets if isinstance(targets, list) else [targets]):
            if damage == "deleted":
                p.unlink(missing_ok=True)
            elif damage == "changed":
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes((p.read_bytes() if p.is_file() else b"{}") + b" ")
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"{not JSON")
    if bundle == "changed":
        monkeypatch.setattr(c, "bundle_sha256", lambda *a, **kw: "f" * 64)
    want = oracle(point, subset, bundle, damage)
    before = _invalid_rows(root)
    sp = Spies(monkeypatch)
    if want == "ok":
        with _Clock(snap["now"]):
            t.gate(root, "matrix probe")
        assert _invalid_rows(root) == before
        return
    stops = _stop_spies(monkeypatch)
    sch = c.aware(START) + timedelta(hours=7, minutes=15)
    with _Clock(snap["now"]), pytest.raises(SystemExit, match=MATRIX_STOP) as ei:
        ck.run_checkpoint(root, root / "ledger.sqlite3", sch, sp.receipt(), sp.process(), root / "c.log",
                          now=lambda: snap["now"])
    sp.assert_zero()
    # A3 Task 14: the stop must be the damage's - the trial gate's refusal/INVALID, or the OQ-19 legacy detector's
    # (run by the command's registration check before any callback) - never the checkpoint's own later refusal for
    # an unrelated reason (a slot time, a missing PREREG-ACK), which would pass any case vacuously.
    assert any(e is ei.value for e in stops["gate"]) or (
        any(e is ei.value for e in stops["registration"]) and LEGACY_STOP.search(str(ei.value))), str(ei.value)
    if want == "invalid":
        assert _invalid_rows(root) > before


# match= (inherited rule): every stop names a refusal or an INVALID; which code raised it is asserted separately.
MATRIX_STOP = r"refused|INVALID"
LEGACY_STOP = re.compile(r"registration artifact\(s\) missing or changed|inconsistent pre-registration state|"
                         r"bundle differs")


def _stop_spies(monkeypatch) -> dict:
    """Record every SystemExit raised by the trial gate and by the checkpoint's registration check (the A3.2/B3.3
    legacy detectors, run before any callback)."""
    got = {"gate": [], "registration": []}

    def spy(key, fn):
        def f(*a, **kw):
            try:
                return fn(*a, **kw)
            except SystemExit as e:
                got[key].append(e)
                raise
        return f
    monkeypatch.setattr(t, "gate", spy("gate", t.gate))
    monkeypatch.setattr(ck.g, "verified_registration", spy("registration", ck.g.verified_registration))
    return got


def test_matrix_scope_is_the_declared_scope(tmp_path):
    assert len(POINTS) == 10 and POINTS[2] == "after-opening-ack"
    import s1_stage
    assert {p.split("after-", 1)[1].replace("-", "_") for p in POINTS} - {"opening_ack", "stop"} == \
        set(s1_stage.TABLE) - set()                                # every CREATED stage is a point
    out = tmp_path / "s1_out"
    for rel in ("audit/calendar.json", "audit/pages/calendar.json", "audit/manifest.json"):
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        (out / rel).write_text("{}", encoding="utf-8")
    assert {p.relative_to(out).as_posix() for p in paths(out, "2026-10-23")["audit tree"]} == {
        "audit/calendar.json", "audit/pages/calendar.json", "audit/manifest.json"}
