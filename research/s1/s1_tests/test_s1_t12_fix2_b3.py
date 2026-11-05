"""Task 12 fix round 2: Addendum 2 B3 (registration starts at the opening seal and is identified independently of
the artifact checked; a missing / changed / unparseable REQUIRED artifact after registration is a persistent
first-wins "registration artifact" abort; a corrupt aborted.json fails closed). Every B3.5 acceptance example,
written BEFORE the fix (RED: s1_evidence/t12_fix2_B3_red.txt). Synthetic only: tmp_path ledgers, mailbox, HMAC key;
callbacks and pricing proven with spies."""
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

import s1_checkpoint as ck
import s1_collect as k
import s1_common as c
import s1_journal as j
import s1_run as r
import s1_seal as z
import s1_snapshot
import s1_trial as t
from conftest import s1_first_invalid, s1_prereg_at, s1_replaced  # A3 Task 10 (fixture instant, F4 CREATED)
from conftest import s1_prereg_ack  # A3 Task 6
from conftest import S1_PROCESS, S1_RECEIPT, Ledger, _Clock, s1_mailbox, s1_opening_checkpoint, s1_plan_audit, \
    s1_reack, s1_state

UTC = timezone.utc
START = "2026-10-26T13:30:00+00:00"
START_DT = datetime(2026, 10, 26, 13, 30, tzinfo=UTC)
OPEN_CLOSE = datetime(2026, 10, 23, 20, 0, tzinfo=UTC)
MON = datetime(2026, 10, 26, 20, 0, tzinfo=UTC)
OPENING = "seals/2026-10-23.json"


def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


class Spies:
    """Every live callback of a checkpoint (snapshot, receipt, process) counted."""

    def __init__(self, monkeypatch):
        self.n = {"snapshot": 0, "receipt": 0, "process": 0}
        real = s1_snapshot.take_snapshot

        def snap(*a, **kw):
            self.n["snapshot"] += 1
            return real(*a, **kw)
        monkeypatch.setattr(s1_snapshot, "take_snapshot", snap)

    def receipt(self, *a, **kw):
        self.n["receipt"] += 1
        return S1_RECEIPT

    def process(self):
        self.n["process"] += 1
        return dict(S1_PROCESS)

    def zero(self):
        return all(v == 0 for v in self.n.values())


def _cp(tmp_path, ledger_path, spies=None, minutes=45, day=0):
    sch = MON + timedelta(days=day, minutes=minutes)
    act = sch + timedelta(seconds=30)
    with _Clock(act):
        return ck.run_checkpoint(tmp_path, ledger_path, sch, spies.receipt if spies else (lambda: S1_RECEIPT),
                                 spies.process if spies else (lambda: dict(S1_PROCESS)), tmp_path / "crash.log",
                                 now=lambda: act)


def _registered(tmp_path):
    st_ = s1_state(tmp_path, START)
    with _Clock(s1_prereg_at(tmp_path)):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    s1_prereg_ack(tmp_path)                    # A3 Task 6 (F7.4): the PREREG-ACK before captures
    st_["ledger"].trade("A", "BUY", 10, 50.0, "2026-10-26T15:00:00+00:00")
    st_["ledger"].set_portfolio("A", 10)
    return st_


def _aborted(tmp_path):
    p = tmp_path / "s1_out" / "aborted.json"
    assert p.exists(), "no persistent abort recorded"     # (strengthened after GREEN: an assertion, not a read error)
    return read(p)


def _refusals(tmp_path):
    p = tmp_path / "s1_out" / "refusals.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


# ====================================================================== B3.1 identified independently
def test_b3_registration_is_recorded_independently_of_the_artifacts_it_binds(tmp_path):
    """B3.1: from the opening seal on, a registry (s1_out/registry/) records the registered stage and the expected
    hash of every artifact bound at that stage - the opening (plan, audit manifest, opening receipt, opening seal),
    the START attestation (+ opening books) and prereg."""
    _registered(tmp_path)
    out = tmp_path / "s1_out"
    assert all((out / "registry" / f"{s}.json").exists() for s in ("opening", "attest_start", "prereg"))
    op = read(out / "registry" / "opening.json")
    for rel in ("plan.json", "audit/manifest.json", "opening_receipt.json", OPENING):
        assert op["artifacts"][rel] == c.sha256_file(out / rel), rel
    assert read(out / "registry" / "attest_start.json")["artifacts"]["attest_start.json"] == \
        c.sha256_file(out / "attest_start.json")
    assert read(out / "registry" / "prereg.json")["artifacts"]["prereg.json"] == c.sha256_file(out / "prereg.json")


# ====================================================================== B3.2 before the opening
def test_b3_an_invalid_handmade_prereg_before_the_opening_is_a_preserved_refusal_with_no_callback(tmp_path,
                                                                                                  monkeypatch):
    """B3.2: no opening seal yet; a hand-made prereg cannot manufacture a registration: the checkpoint refuses, the
    refusal is preserved (refusals.jsonl), no live callback, no slot claim, no abort."""
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    out = tmp_path / "s1_out"
    (out / "prereg.json").write_text(json.dumps({"start": START, "calendar": cal, "receipt": S1_RECEIPT,
                                                 "bundle_sha256": c.bundle_sha256(),
                                                 "ack": {"ack_id": "forged", "created_utc": START}}),
                                     encoding="utf-8")
    spies = Spies(monkeypatch)
    # A3 Task 10 (intended, F4 table 'no INTENT: any artifact for g is a violation after the AUDIT-ACK', with prereg in
    # s1_stage.ENFORCED; the Task 7 concern-2 ruling: A3 supersedes A2 B3.2 after the AUDIT-ACK): the hand-made
    # prereg.json is TRIAL-INVALID (registration-artifact) at the gate, still with no callback, no claim and no
    # registration manufactured (old: a preserved B3.2 refusal)
    with pytest.raises(SystemExit, match=r"stage prereg: artifacts \['prereg.json'\] with no INTENT: INVALID "
                                         r"\(registration-artifact\)"):
        _cp(tmp_path, Ledger(tmp_path / "l.sqlite3").path, spies)
    assert spies.zero() and not (out / "captures").exists() and not (out / "aborted.json").exists()
    assert s1_first_invalid(tmp_path) == "reason/registration-artifact"


# ====================================================================== B3.3 after the opening, before RUN-ACK
def test_b3_the_opening_changed_after_the_opening_but_before_the_run_ack_is_a_persistent_abort(tmp_path):
    """B3.3: registration exists from the opening seal: the opening seal changed before the START attestation /
    RUN-ACK -> the attestation records the persistent "registration artifact" abort; restoring does not resume."""
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    lg = Ledger(tmp_path / "l.sqlite3")
    assert s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT)["seal"]["written"]
    p = tmp_path / "s1_out" / OPENING
    good = p.read_bytes()
    p.write_bytes(good + b" ")
    at = OPEN_CLOSE + timedelta(hours=2)
    # A3 Task 10 (intended, F4 table CREATED): the opening seal is the `opening` stage's committed member: changed ->
    # INVALID (stage-replaced) at the gate, before the B3.3 detector (whose finding stays the unit-level oracle)
    assert any(OPENING in x for x in c.registration_problems(tmp_path / "s1_out"))
    with _Clock(at), pytest.raises(SystemExit, match=s1_replaced(OPENING)):
        r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    assert s1_first_invalid(tmp_path) == "reason/stage-replaced"
    p.write_bytes(good)
    with _Clock(at), pytest.raises(t.Refusal, match=r"trial INVALID \(reason/stage-replaced\)"):   # A3 F0.6
        r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    assert "reason/stage-replaced" in _aborted(tmp_path)["reason"]


def test_b3_a_prereg_not_yet_due_is_not_corruption(tmp_path):
    """B3.3: after the opening and the START attestation, a prereg that does not exist yet is a future-stage artifact:
    a scheduled checkpoint refuses (no verified prereg) but records NO abort; prereg then still works."""
    st_ = s1_state(tmp_path, START)
    with pytest.raises(SystemExit, match="prereg"):
        _cp(tmp_path, st_["ledger"].path)
    assert not (tmp_path / "s1_out" / "aborted.json").exists()
    with _Clock(s1_prereg_at(tmp_path)):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    s1_prereg_ack(tmp_path)                    # A3 Task 6 (F7.4): the PREREG-ACK before captures
    assert (tmp_path / "s1_out" / "prereg.json").exists()


ARTIFACTS = ["plan.json", "audit/manifest.json", "audit/calendar.json", "attest_start.json", "opening_books.json",
             "prereg.json", OPENING, "opening_receipt.json"]


@pytest.mark.parametrize("mode", ["changed", "deleted"])
@pytest.mark.parametrize("rel", ARTIFACTS)
def test_b3_a_registered_artifact_changed_or_deleted_then_restored_stays_invalid(tmp_path, rel, mode):
    """B3.3/B3.5: after registration every bound artifact is REQUIRED: changed or deleted -> the next command records
    first-wins aborted.json (reason "registration artifact"); restoring the bytes does not resume (no seal)."""
    st_ = _registered(tmp_path)
    p = tmp_path / "s1_out" / rel
    good = p.read_bytes()
    if mode == "changed":
        p.write_bytes(good + b"\n")
    else:
        p.unlink()
    if rel != "plan.json":
        # A3 Task 9 (intended, F4 table CREATED row, F4.9 consistency): a member of the CREATED audit stage changed or
        # deleted is INVALID (stage-replaced) at the gate, before the B3.3 detector; restoring the bytes does not
        # resume (the next command refuses: trial INVALID, and records the journal's INVALID as the local abort).
        # A3 Task 10 (intended, same rule): likewise a member or bound input of the CREATED opening, start_attest and
        # prereg stages (the opening seal, opening_receipt.json, attest_start.json, opening_books.json, prereg.json);
        # the B3.3 detector's finding is kept as the unit-level oracle
        assert any(rel in x for x in c.registration_problems(tmp_path / "s1_out")), rel
        with pytest.raises(SystemExit, match=s1_replaced(rel)):
            _cp(tmp_path, st_["ledger"].path)
        p.write_bytes(good)
        with pytest.raises(t.Refusal, match=r"trial INVALID \(reason/stage-replaced\)"):
            _cp(tmp_path, st_["ledger"].path, minutes=47)
        assert "reason/stage-replaced" in _aborted(tmp_path)["reason"]
        return
    with pytest.raises(SystemExit, match=r"registration artifact\(s\) missing or changed"):
        _cp(tmp_path, st_["ledger"].path)
    ab = _aborted(tmp_path)
    assert ab["reason"] == "registration artifact" and any(rel in x for x in ab["problems"]), ab
    p.write_bytes(good)
    with pytest.raises(t.Refusal, match=r"trial INVALID \(reason/registration-artifact\)"):   # A3 F0.6/F1
        _cp(tmp_path, st_["ledger"].path, minutes=47)


@pytest.mark.parametrize("also_registry", [False, True])
def test_b3_deleting_prereg_and_the_opening_together_cannot_erase_the_registration(tmp_path, also_registry):
    """B3.1/B3.5: deleting prereg AND the opening seal (and even the registry record) does not move the trial back
    to pre-registration: the opening capture report still witnesses the registration -> persistent abort."""
    st_ = _registered(tmp_path)
    out = tmp_path / "s1_out"
    (out / "prereg.json").unlink()
    (out / OPENING).unlink()
    if also_registry:
        shutil.rmtree(out / "registry")
    # A3 Task 10 (intended, F4 table CREATED): both are CREATED stage members (opening is checked first); the B3.3
    # detector's finding stays the unit-level oracle (fix round 1, M8: naming both deleted files)
    probs = c.registration_problems(out)
    assert any("prereg.json" in x for x in probs) and any(OPENING in x for x in probs), probs
    with pytest.raises(SystemExit, match=s1_replaced(OPENING)):
        _cp(tmp_path, st_["ledger"].path)
    assert s1_first_invalid(tmp_path) == "reason/stage-replaced"
    with pytest.raises(t.Refusal, match=r"trial INVALID \(reason/stage-replaced\)"):
        _cp(tmp_path, st_["ledger"].path, minutes=47)
    assert "reason/stage-replaced" in _aborted(tmp_path)["reason"]


# ====================================================================== B3.3 re-entry / post-stop cannot bypass
def test_b3_audit_re_entry_cannot_bypass_persistence(tmp_path):
    """B3.3: an audit re-run after registration with a changed plan records the persistent abort before any
    request (the injected client is never called)."""
    _registered(tmp_path)
    calls = []
    client = httpx.Client(transport=httpx.MockTransport(lambda req: calls.append(req) or httpx.Response(500)),
                          follow_redirects=False)
    p = tmp_path / "s1_out" / "plan.json"
    p.write_bytes(p.read_bytes() + b"\n")
    with (_Clock(START_DT - timedelta(hours=3)),
          pytest.raises(SystemExit, match=r"registration artifact\(s\) missing or changed")):
        k.do_audit(tmp_path, "audit-ack", client, {"key": "k", "secret": "s"})
    assert calls == [] and _aborted(tmp_path)["reason"] == "registration artifact"


def test_b3_opening_re_entry_cannot_bypass_persistence(tmp_path):
    """B3.3: an opening re-entry after registration observing a changed prereg records the persistent abort."""
    st_ = _registered(tmp_path)
    p = tmp_path / "s1_out" / "prereg.json"
    p.write_bytes(p.read_bytes() + b"\n")
    sch = OPEN_CLOSE + timedelta(minutes=47)
    # A3 Task 10 (intended; plan Task 10 Step 6 names this test: N-2/R-3 -> F3 + F4): prereg.json is the prereg
    # stage's committed member: INVALID (stage-replaced) at the opening re-entry's gate; persistent
    assert any("prereg.json" in x for x in c.registration_problems(tmp_path / "s1_out"))
    with (_Clock(sch + timedelta(seconds=30)), pytest.raises(SystemExit, match=s1_replaced("prereg.json"))):
        ck.run_opening_checkpoint(tmp_path, st_["ledger"].path, sch, lambda: S1_RECEIPT, lambda: dict(S1_PROCESS),
                                  tmp_path / "crash.log", now=lambda: sch + timedelta(seconds=30))
    assert s1_first_invalid(tmp_path) == "reason/stage-replaced"
    with (_Clock(sch + timedelta(minutes=1)), pytest.raises(t.Refusal, match=r"trial INVALID \(reason/stage-replaced\)")):
        ck.run_opening_checkpoint(tmp_path, st_["ledger"].path, sch, lambda: S1_RECEIPT, lambda: dict(S1_PROCESS),
                                  tmp_path / "crash.log", now=lambda: sch + timedelta(minutes=1))
    assert "reason/stage-replaced" in _aborted(tmp_path)["reason"]


def test_b3_post_stop_integrity_of_frozen_artifacts_is_persistent(tmp_path):
    """B3.3: after the persisted stop, a frozen slice that changed is observed by the next checkpoint -> persistent
    "registration artifact" abort (not merely reported)."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    sl = out / "seals" / f"{st_['sessions'][0]}.json"
    sl.write_bytes(sl.read_bytes() + b" ")
    sch = z.close_of(st_["sessions"][5], st_["calendar"]) + timedelta(minutes=45)
    # A3 Task 7 (E2.6 r3): the frozen slice is a CREATED seal/<close> stage member - its change is TRIAL-INVALID
    # (stage-replaced) at the next gate, persistent: every later command refuses "trial INVALID" and records the abort
    with (_Clock(sch + timedelta(seconds=30)),
          pytest.raises(SystemExit, match=r"member seals/.* missing or changed.*INVALID \(stage-replaced\)")):
        ck.run_checkpoint(tmp_path, st_["ledger"].path, sch, lambda: S1_RECEIPT, lambda: dict(S1_PROCESS),
                          tmp_path / "crash.log", now=lambda: sch + timedelta(seconds=30))
    with (_Clock(sch + timedelta(minutes=1)),
          pytest.raises(SystemExit, match=r"trial INVALID \(reason/stage-replaced\)")):
        ck.run_checkpoint(tmp_path, st_["ledger"].path, sch, lambda: S1_RECEIPT, lambda: dict(S1_PROCESS),
                          tmp_path / "crash.log", now=lambda: sch + timedelta(minutes=1))
    assert "stage-replaced" in str(_aborted(tmp_path)["reason"])


# ====================================================================== B3.4 mailbox outage vs corruption
def test_b3_a_mailbox_outage_is_a_refusal_not_proof_of_tampering(tmp_path, monkeypatch):
    """B3.4: the mailbox unreadable with no artifact violation: a refusal (preserved), zero callbacks, NO abort."""
    st_ = _registered(tmp_path)
    (tmp_path / "mailbox.sqlite3").rename(tmp_path / "mailbox.away")
    spies = Spies(monkeypatch)
    with pytest.raises(SystemExit, match="mailbox unreadable"):
        _cp(tmp_path, st_["ledger"].path, spies)
    assert spies.zero() and not (tmp_path / "s1_out" / "aborted.json").exists()
    assert _refusals(tmp_path)


def test_b3_a_mailbox_outage_cannot_downgrade_an_established_violation(tmp_path, monkeypatch):
    """B3.4: prereg deleted while the mailbox is unavailable: the violation is still recorded (persistent abort);
    the outage never downgrades it, and no callback runs."""
    st_ = _registered(tmp_path)
    (tmp_path / "mailbox.sqlite3").rename(tmp_path / "mailbox.away")
    (tmp_path / "s1_out" / "prereg.json").unlink()
    spies = Spies(monkeypatch)
    with pytest.raises(SystemExit, match=r"registration artifact\(s\) missing or changed"):
        _cp(tmp_path, st_["ledger"].path, spies)
    assert spies.zero() and _aborted(tmp_path)["reason"] == "registration artifact"


def test_b3_an_earlier_bundle_abort_stays_first(tmp_path, monkeypatch):
    """B3.4: an earlier terminal reason (bundle) remains first-wins over a later registration-artifact violation."""
    st_ = _registered(tmp_path)
    c.write_abort(tmp_path / "s1_out", {"reason": "bundle", "actual": START})
    (tmp_path / "s1_out" / "attest_start.json").unlink()
    probs = c.registration_problems(tmp_path / "s1_out")             # (the B3.3 finding: unit level, fix round 1 M8)
    assert any("attest_start.json" in x for x in probs), probs
    with pytest.raises(SystemExit, match=s1_replaced("attest_start.json")):     # A3 Task 10 (intended, F4 CREATED)
        _cp(tmp_path, st_["ledger"].path)
    with pytest.raises(t.Refusal, match=r"trial INVALID \(reason/stage-replaced\)"):     # (its abort: first-wins)
        _cp(tmp_path, st_["ledger"].path, minutes=47)
    assert _aborted(tmp_path)["reason"] == "bundle"


# ====================================================================== spies on the priced path
VALUATION = ("simulate_lot", "lot_economics", "baseline_economics", "compare", "paired_bootstrap")


def test_b3_a_registration_artifact_violation_at_the_score_is_persisted_and_prices_nothing(tmp_path, monkeypatch):
    """B3.3/B3.5: the score observing a changed START attestation records the persistent abort and is the preserved
    ABORTED-INVALID record (corrected after RED, before GREEN: the score - like the final snapshot - is a recording
    command, A2.3: it does not refuse, it records). No valuation call (spies); restoring changes nothing.
    A3 Task 5 (intended, F0.6/F1 + OQ-19): old = "ABORTED-INVALID report, zero prices"; new = "TRIAL-INVALID
    committed, score refused, zero prices" (the detector commits the violation first; the score then re-reads the
    trial state and does no work: no reservation, no record)."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    sim = c.sim()
    called = []
    for name in VALUATION:
        monkeypatch.setattr(sim, name, lambda *a, _n=name, **kw: called.append(_n) or pytest.fail(_n))
    p = tmp_path / "s1_out" / "attest_start.json"
    good = p.read_bytes()
    p.write_bytes(good + b"\n")
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"] + timedelta(days=1))
    s1_reack(tmp_path, "score-ack-b3", "S1-SCORE-ACK", st_["now"] + timedelta(hours=20))
    # A3 Task 10 (intended, F4 table CREATED): attest_start.json is the start_attest stage's committed member - the
    # gate's stage table invalidates (stage-replaced) before the B3.3 detector; the score is refused with no work
    assert any("attest_start.json" in x for x in c.registration_problems(tmp_path / "s1_out"))
    with pytest.raises(SystemExit, match=s1_replaced("attest_start.json")):
        r.score(tmp_path, "score-ack-b3")
    assert called == [] and not (tmp_path / "s1_out" / "score").exists()
    assert any(x.kind == "TRIAL-INVALID" and x.subject == "reason/stage-replaced"
               for x in j.read_all(tmp_path / "mailbox.sqlite3"))
    p.write_bytes(good)
    with pytest.raises(t.Refusal, match=r"trial INVALID \(reason/stage-replaced\)"):    # restoring resumes nothing
        r.score(tmp_path, "score-ack-b3")
    assert "reason/stage-replaced" in c.load_abort(tmp_path / "s1_out")["reason"] and called == []


# ====================================================================== corrupt aborted.json fails closed
def test_b3_a_corrupt_aborted_json_fails_closed(tmp_path, monkeypatch):
    """B3.4: an unparseable aborted.json never means "no abort": the checkpoint writes its report and reports
    ABORTED-INVALID (never seals, never crashes). (Fix round 3, M-5: docstring corrected - this test does not run
    the score; the score's fail-closed reading of a corrupt aborted.json is s1_common.load_abort, used by _score.)"""
    st_ = _registered(tmp_path)
    (tmp_path / "s1_out" / "aborted.json").write_text("{corrupt", encoding="utf-8")
    # A3 Task 6 (F8.1): a local aborted.json - corrupt included (it fails closed: it IS an abort) - refuses any new
    # capture before the SLOT-INTENT: no row, no capture, no seal, never a crash
    with pytest.raises(SystemExit, match=r"aborted\.json exists .*no new capture"):
        _cp(tmp_path, st_["ledger"].path)
    assert not (tmp_path / "s1_out" / "captures" / "2026-10-26").exists()
    assert not (tmp_path / "s1_out" / "seals" / "2026-10-26.json").exists()


def test_b3_a_corrupt_aborted_json_fails_closed_at_prereg(tmp_path):
    """B3.4: prereg refuses with a corrupt aborted.json (it is an abort)."""
    s1_state(tmp_path, START)
    (tmp_path / "s1_out" / "aborted.json").write_text("{corrupt", encoding="utf-8")
    with _Clock(s1_prereg_at(tmp_path)), pytest.raises(SystemExit, match="ABORTED"):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    assert not (tmp_path / "s1_out" / "prereg.json").exists()
