"""Task 12 fix round 4 (re-review 2 of fix round 3: N-1, N-2, N-3 and the minor stage.lock finding m-1).
Written BEFORE the fix; behavioural RED per item in s1_evidence/t12_fix4_<id>_red.txt. Every reviewer probe
(scratchpad/probe/test_probe3.py, test_probe4.py, test_probe5.py) is a permanent test here. Races are made
deterministic with hooks and threading.Event barriers (no sleeps); time is an injected aware clock. Synthetic only:
tmp_path ledgers, mailbox and HMAC key; no live DB, network, real mailbox or scheduler."""
import json
import shutil
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import s1_checkpoint as ck
import s1_common as c
import s1_run as r
import s1_seal as z
from conftest import s1_first_invalid, s1_prereg_at  # A3 Task 10 (fixture instant)
from conftest import S1_PROCESS, S1_RECEIPT, Ledger, _Clock, s1_mailbox, s1_opening_checkpoint, s1_plan_audit, \
    s1_state, s1_unattest
from test_s1_t12_fix2_b3 import MON, Spies, _aborted, _cp, _refusals

UTC = timezone.utc
START = "2026-10-26T13:30:00+00:00"
START_DT = datetime(2026, 10, 26, 13, 30, tzinfo=UTC)
WAIT = 20                                            # seconds a synchronization wait may block (never a sleep)


# ====================================================================== N-1 the stage.lock race
def _stage_run(tmp_path, stage):
    """The state just before `stage` ("attest_start" | "prereg"), the call that publishes it and its causal instant.
    A3 Task 10 (fixture change): the START attestation is the journal-committed start_attest stage, so the state
    before it is s1_state(attest=False) (s1_unattest's file deletion would now be stage-replaced), and the instants
    follow the fixture's OPENING-ACK / RUN-ACK (F7.2(b) literal) instead of START - 1 day."""
    st_ = s1_state(tmp_path, START, attest=(stage != "attest_start"))
    if stage == "attest_start":
        return (lambda: r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)), st_["attest_at"]
    return (lambda: r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)), s1_prereg_at(tmp_path)


def _interleave(tmp_path, monkeypatch, stage, order):
    """A gate (the opening-slot checkpoint's registration gate) that has passed its stage.lock check scans the state
    between `stage`'s two records and its artifact. order "gate-first": the gate finishes while the publication is
    still paused (lock held); order "publication-first": the publication completes (lock released) after the gate's
    first scan and before the gate continues; order "released-during-rescan" (added after GREEN, RETROSPECTIVE): the
    gate's second scan still sees the publication paused, and the publication completes (lock released) before the
    gate's last lock check. Returns (gate outcome, publication outcome)."""
    run_stage, at = _stage_run(tmp_path, stage)
    out = tmp_path / "s1_out"
    artifact = out / c.STAGE_ARTIFACT[stage]
    past_lock, records_in, scanned, release_gate = (threading.Event() for _ in range(4))
    rescanned, pub_done = threading.Event(), threading.Event()
    real_probs, first = c.registration_problems, [True]

    def probs(*a, **kw):
        if threading.current_thread().name != "gate":
            return real_probs(*a, **kw)
        if not first[0]:
            got = real_probs(*a, **kw)
            if order == "released-during-rescan" and not rescanned.is_set():
                rescanned.set()
                assert pub_done.wait(WAIT), "the publication never completed"
            return got
        first[0] = False
        past_lock.set()
        assert records_in.wait(WAIT), "the publication never reached its artifact"
        got = real_probs(*a, **kw)
        scanned.set()
        if order == "publication-first":
            assert release_gate.wait(WAIT), "the gate was never released"
        return got
    monkeypatch.setattr(c, "registration_problems", probs)
    real_pub = c.publish_exclusive                # A3 Task 10: the stage engine publishes members via publish_exclusive
    gate_finished = threading.Event()

    def pub(path, data, **kw):
        if threading.current_thread().name == "stage" and Path(path) == artifact:
            records_in.set()
            assert scanned.wait(WAIT), "the gate never scanned"
            if order == "gate-first":
                assert gate_finished.wait(WAIT), "the gate never finished"
            if order == "released-during-rescan":
                assert rescanned.wait(WAIT), "the gate never re-scanned"
        return real_pub(path, data, **kw)
    monkeypatch.setattr(c, "publish_exclusive", pub)
    monkeypatch.setattr(c, "now_utc", lambda: at)
    box = {}

    def gate():
        try:
            c.registration_gate(out, "opening checkpoint")
            box["gate"] = "passed"
        except SystemExit as e:
            box["gate"] = str(e)
        finally:
            gate_finished.set()
            rescanned.set()                              # (a gate that refused before re-scanning releases it too)

    def publish():
        try:
            box["stage"] = bool(run_stage())
        except BaseException as e:                       # noqa: BLE001 - the outcome under test
            box["stage"] = repr(e)
    tg = threading.Thread(target=gate, name="gate")
    tg.start()
    assert past_lock.wait(WAIT)
    ts = threading.Thread(target=publish, name="stage")
    ts.start()
    if order == "publication-first":
        ts.join(WAIT)
        release_gate.set()
    if order == "released-during-rescan":
        ts.join(WAIT)
        pub_done.set()
    tg.join(WAIT)
    ts.join(WAIT)
    assert not tg.is_alive() and not ts.is_alive()
    return box


@pytest.mark.parametrize("order", ["gate-first", "publication-first"])
@pytest.mark.parametrize("stage", ["attest_start", "prereg"])
def test_n1_a_gate_racing_a_legitimate_stage_publication_refuses_and_never_aborts(tmp_path, monkeypatch, stage,
                                                                                  order):
    """N-1 reviewer probe test_gate_toctou_vs_attestation, both interleavings, for the START attestation and prereg:
    a gate that passed its lock check before the publication took the lock and scanned between the stage's records
    and its artifact must not record an abort. Either the lock is still held when it re-checks (refusal) or the
    violation has vanished on its confirming re-scan (refusal); the publication succeeds and the trial is not
    ABORTED-INVALID."""
    box = _interleave(tmp_path, monkeypatch, stage, order)
    out = tmp_path / "s1_out"
    assert box["stage"] is True, box
    assert c.load_abort(out) is None, (box, c.load_abort(out))
    assert box["gate"] != "passed" and "refused" in box["gate"] and "ABORTED-INVALID" not in box["gate"], box
    assert (out / c.STAGE_ARTIFACT[stage]).exists() and not (out / c.STAGE_LOCK).exists()
    c.registration_gate(out, "after the publication")         # the completed stage is consistent: no problem


def test_n1_a_violation_present_on_both_scans_with_no_lock_is_still_the_persistent_abort(tmp_path):
    """N-1 guard: the confirming re-scan never hides a real deletion: prereg.json deleted after its publication (no
    lock at any check, the same problem on both scans) -> the gate records the persistent abort."""
    s1_state(tmp_path, START)
    with _Clock(s1_prereg_at(tmp_path)):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    out = tmp_path / "s1_out"
    (out / "prereg.json").unlink()
    with pytest.raises(SystemExit, match="ABORTED-INVALID"):
        c.registration_gate(out, "checkpoint", now=lambda: START_DT)
    assert _aborted(tmp_path)["reason"] == "registration artifact"


# ====================================================================== N-2 re-opening after the deletion
def _opening(tmp_path):
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    lg = Ledger(tmp_path / "l.sqlite3")
    rep = s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT)
    assert rep["seal"]["written"], rep
    out = tmp_path / "s1_out"
    return out, cal, oc, lg, c.sha256_file(out / "seals" / f"{oc}.json")


def _reopen(tmp_path, lg, oc, cal, slot_index, spies=None):
    day = next(d for d in cal if d["date"] == oc)
    sch = z.schedule(day, cal)[slot_index]
    act = sch + timedelta(seconds=30)
    with _Clock(act):
        return ck.run_opening_checkpoint(tmp_path, lg.path, sch, spies.receipt if spies else (lambda: S1_RECEIPT),
                                         spies.process if spies else (lambda: dict(S1_PROCESS)),
                                         tmp_path / "crash.log", now=lambda: act)


DELETIONS = {
    # the reviewer probe: seals, both registration records, every capture json and the opening receipt
    "probe": ["seals", "registry", "witnesses", "captures/*/*.json", "opening_receipt.json"],
    # the capture directories too: last_process.json (written only after a slot claim) remains
    "captures-whole": ["seals", "registry", "witnesses", "captures", "opening_receipt.json"],
    # the sealing slot's resolution and report only (its claim and capture stay): the stored opening receipt is only
    # ever written after a SUCCESS resolution was read
    "resolution+report": ["seals", "registry", "witnesses", "captures/*/*.resolution.json",
                          "captures/*/*.report.json"],
}


def _delete(out: Path, items) -> list:
    gone = []
    for it in items:
        for p in (sorted(out.glob(it)) if "*" in it else [out / it]):
            if p.is_dir():
                shutil.rmtree(p)
            elif p.exists():
                p.unlink()
            else:
                continue
            gone.append(p.relative_to(out).as_posix())
    return gone


@pytest.mark.parametrize("combo", sorted(DELETIONS))
def test_n2_reopening_after_the_local_witnesses_are_deleted_never_writes_a_second_opening_seal(tmp_path, monkeypatch,
                                                                                               combo):
    """N-2 reviewer probe test_reopen_after_total_local_deletion (and two variants): the opening sealed, then - before
    any RUN-ACK - every registration witness deleted, leaving opening-close evidence the opening run produced (capture
    directories, last_process.json, the stored opening receipt). A later slot of the same opening close must NOT
    write a new, different opening seal: the remaining evidence presumes the registration happened, so the command
    records the persistent "registration artifact" abort, with zero live callbacks, and no opening seal is ever
    written again (also at a further slot)."""
    out, cal, oc, lg, first = _opening(tmp_path)
    assert _delete(out, DELETIONS[combo])
    spies = Spies(monkeypatch)
    # A3 Task 10 (intended; plan Task 10 Step 6: N-2/R-3 -> F3 + F4): the opening seal is the CREATED `opening` stage's
    # member - its deletion is INVALID (stage-replaced) at the re-opening's gate (no second seal, zero callbacks); the
    # next opening slot refuses "trial INVALID" and records the local abort
    with pytest.raises(SystemExit, match=r"stage opening: .*member seals/2026-10-23\.json missing or changed.*"
                                         r"INVALID \(stage-replaced\)"):
        _reopen(tmp_path, lg, oc, cal, 8, spies)
    assert not (out / "seals" / f"{oc}.json").exists(), "a second, different opening seal was written"
    assert s1_first_invalid(tmp_path) == "reason/stage-replaced"
    assert spies.zero(), spies.n
    with pytest.raises(SystemExit, match=r"trial INVALID \(reason/stage-replaced\)"):
        _reopen(tmp_path, lg, oc, cal, 9)
    assert not (out / "seals" / f"{oc}.json").exists()
    assert "reason/stage-replaced" in _aborted(tmp_path)["reason"]


def test_n2_opening_seal_creation_refuses_on_earlier_opening_evidence_without_its_record(tmp_path):
    """N-2 (seal creation): opening-slot evidence that only an earlier attempt produces appears after the gate ran (a
    capture directory of an earlier opening slot without its claim, created during this run's capture): the seal is
    not written - the opening refuses - and no opening seal exists."""
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    out = tmp_path / "s1_out"
    lg = Ledger(tmp_path / "l.sqlite3")
    day = next(d for d in cal if d["date"] == oc)
    slots = z.schedule(day, cal)
    early = out / "captures" / oc / slots[0].strftime("%Y%m%dT%H%M%SZ")

    def receipt():                                       # runs after the gate, before the selection
        early.mkdir(parents=True, exist_ok=True)
        (early / "meta.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
        return S1_RECEIPT
    sch, act = slots[8], slots[8] + timedelta(seconds=30)        # (slot 0 is past its window: MISSED)
    with _Clock(act), pytest.raises(SystemExit):
        ck.run_opening_checkpoint(tmp_path, lg.path, sch, receipt, lambda: dict(S1_PROCESS), tmp_path / "crash.log",
                                  now=lambda: act)
    assert not (out / "seals" / f"{oc}.json").exists(), "the opening sealed over an earlier slot's evidence"


def test_n2_guard_a_failed_opening_slot_then_a_later_slot_still_seals(tmp_path):
    """N-2 guard (passes before and after the fix): a legitimate FAILURE at the first opening slot (its claim,
    capture and resolution all present) is consistent opening evidence, never an abort - the next slot seals."""
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    out = tmp_path / "s1_out"
    lg = Ledger(tmp_path / "l.sqlite3")

    def no_process():
        raise RuntimeError("process observation unavailable")
    day = next(d for d in cal if d["date"] == oc)
    sch = z.schedule(day, cal)[0]
    act = sch + timedelta(seconds=30)
    with _Clock(act):
        rep = ck.run_opening_checkpoint(tmp_path, lg.path, sch, lambda: S1_RECEIPT, no_process,
                                        tmp_path / "crash.log", now=lambda: act)
    assert not rep.get("seal", {}).get("written") and not (out / "seals" / f"{oc}.json").exists(), rep
    rep = s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT, minutes=47)
    assert rep["seal"]["written"] and c.load_abort(out) is None, rep


# ====================================================================== N-3 fabricated pairs, the clock anchor
def _fabricate(tmp_path, rels, cal):
    out = tmp_path / "s1_out"
    for rel in rels:
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        (out / rel).write_text(json.dumps({"start": START, "calendar": cal, "receipt": S1_RECEIPT,
                                           "bundle_sha256": c.bundle_sha256(),
                                           "ack": {"ack_id": "forged", "created_utc": START}}), encoding="utf-8")


@pytest.mark.parametrize("pair", [("prereg.json", "seals/2026-01-01.json"), ("prereg.json", "attest_start.json"),
                                  ("final_plan.json", "attest_stop.json"), ("prereg.json", "seals/2026-10-23.json")])
def test_n3_probe_two_handmade_later_stage_files_before_any_opening_are_a_refusal(tmp_path, monkeypatch, pair):
    """N-3 reviewer probe test_fabricated_pair (B3.2, controller ruling on A1/B3.1): with only plan + audit, two
    hand-made later-stage files - none tied to the opening close; a file at the opening seal's path that is not a
    seal of the opening close is not a valid opening seal - manufacture no registration: the checkpoint refuses
    (preserved), with zero live callbacks, and records NO abort."""
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    _fabricate(tmp_path, pair, cal)
    spies = Spies(monkeypatch)
    if pair[1] == "seals/2026-01-01.json":
        # A3 Task 7 (E2.4 r3, "in every state"): a seal file of a non-opening close with no seal-stage row is a
        # registration artifact once the trial exists: TRIAL-INVALID at the gate, zero live callbacks
        # A3 Task 10 (intended): prereg is ENFORCED too and the TABLE stages are evaluated before the seal stages, so
        # the hand-made prereg.json is the violation named first (the same TRIAL-INVALID registration-artifact)
        with pytest.raises(SystemExit, match=r"stage prereg: artifacts \['prereg\.json'\] .*INVALID "
                                             r"\(registration-artifact\)"):
            _cp(tmp_path, Ledger(tmp_path / "l.sqlite3").path, spies)
        assert spies.zero(), spies.n
        return
    first = {"attest_start.json": "start_attest", "seals/2026-10-23.json": "opening"}.get(pair[1])
    if first is not None:
        # A3 Task 10 (intended, F4 table 'no INTENT: any artifact for g is a violation after the AUDIT-ACK'; the
        # Task 7 concern-2 ruling - A3 supersedes A2 B3.2 after the AUDIT-ACK): start_attest / opening are ENFORCED
        # and evaluated before prereg: TRIAL-INVALID (registration-artifact), zero live callbacks, no registration
        with pytest.raises(SystemExit, match=rf"stage {first}: artifacts \['{pair[1]}'\] with no INTENT: INVALID "
                                             r"\(registration-artifact\)"):
            _cp(tmp_path, Ledger(tmp_path / "l.sqlite3").path, spies)
        assert spies.zero(), spies.n
        assert s1_first_invalid(tmp_path) == "reason/registration-artifact"
        return
    with pytest.raises(SystemExit):
        _cp(tmp_path, Ledger(tmp_path / "l.sqlite3").path, spies)
    assert c.load_abort(tmp_path / "s1_out") is None, c.load_abort(tmp_path / "s1_out")
    assert spies.zero() and _refusals(tmp_path), (spies.n, _refusals(tmp_path))


# Fix round 8: test_n3_clock_anchor_nothing_is_registered_before_the_first_opening_slot REMOVED - its premise (a
# plan-derived clock anchor cancels a codex RUN-ACK carrying the bundle) is what the fix-8 rule forbids (rule 2: the
# anchor never cancels an external ACK). Replaced by fix8::test_h_a_run_ack_carrying_the_bundle_is_a_registration_
# even_before_the_opening (S1_BUILD_EVIDENCE §21.2).


def test_n3_clock_anchor_a_forged_prereg_and_run_ack_before_the_opening_cannot_record_a_bundle_abort(tmp_path,
                                                                                                    monkeypatch):
    """N-3 clock anchor (A3.3 bundle gate): before the opening close's first slot a hand-made prereg.json naming a
    codex RUN-ACK whose bundle differs from the bundle on disk is no registration either: the bundle difference is a
    refusal (nothing registered yet), never the persistent "bundle" abort, with zero live callbacks."""
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    out = tmp_path / "s1_out"
    other = "ab" * 32
    (out / "prereg.json").write_text(json.dumps({"start": START, "bundle_sha256": other,
                                                 "ack": {"ack_id": "forged-run"}}), encoding="utf-8")
    day = next(d for d in cal if d["date"] == oc)
    slot0 = z.schedule(day, cal)[0]
    before = slot0 - timedelta(minutes=10)
    s1_mailbox(tmp_path, "forged-run", f"S1-RUN-ACK plan_sha256={c.sha256_file(out / 'plan.json')} "
                                       f"bundle_sha256={other}", before - timedelta(minutes=5))
    spies = Spies(monkeypatch)
    with _Clock(before), pytest.raises(SystemExit) as e:
        ck.run_opening_checkpoint(tmp_path, Ledger(tmp_path / "l.sqlite3").path, slot0, spies.receipt,
                                  spies.process, tmp_path / "crash.log", now=lambda: before)
    assert c.load_abort(out) is None, (c.load_abort(out) or {}).get("reason")   # (no bundle text: A10.2 harness)
    assert spies.zero() and _refusals(tmp_path)


# ====================================================================== m-1 an error inside stage.lock
@pytest.mark.parametrize("stage", ["attest_start", "prereg"])
def test_minor_an_artifact_write_error_after_the_stage_records_keeps_the_lock_and_refuses(tmp_path, monkeypatch,
                                                                                          stage):
    """m-1: an OSError (disk full) publishing the stage artifact AFTER both stage records were published must not
    release stage.lock as clean: the lock stays, the next command refuses (preserved) and records no abort - never a
    false persistent abort of a legitimate trial."""
    run_stage, t = _stage_run(tmp_path, stage)
    out = tmp_path / "s1_out"
    artifact = out / c.STAGE_ARTIFACT[stage]
    real = c.publish_exclusive                    # A3 Task 10: the stage engine publishes members via publish_exclusive

    def disk_full(path, data, **kw):
        if Path(path) == artifact:
            raise OSError(28, "No space left on device")
        return real(path, data, **kw)
    monkeypatch.setattr(c, "publish_exclusive", disk_full)
    with _Clock(t), pytest.raises(OSError, match="No space left on device"):
        run_stage()
    monkeypatch.setattr(c, "publish_exclusive", real)
    assert all(p.exists() for p in c.stage_records(out, stage)) and not artifact.exists()
    assert (out / c.STAGE_LOCK).exists(), "stage.lock was released as clean after the records were published"
    with pytest.raises(SystemExit, match="stage publication"):
        c.verify_bundle_first(out, "later command", now=lambda: t + timedelta(minutes=5))
    assert c.load_abort(out) is None, c.load_abort(out)


# ====================================================================== retrospective isolating tests (A10.2)
def test_n2_retro_a_capture_report_without_its_resolution_is_an_earlier_opening_attempt(tmp_path):
    """RETROSPECTIVE. N-2: a legitimate FAILURE at the first opening slot, then only its resolution record deleted
    (its claim, capture and report stay): a report is only ever written after its resolution, so the next opening
    slot records the persistent abort instead of treating the slot as pending or sealing."""
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    out = tmp_path / "s1_out"
    lg = Ledger(tmp_path / "l.sqlite3")

    def no_process():
        raise RuntimeError("process observation unavailable")
    day = next(d for d in cal if d["date"] == oc)
    sch = z.schedule(day, cal)[0]
    with _Clock(sch + timedelta(seconds=30)):
        ck.run_opening_checkpoint(tmp_path, lg.path, sch, lambda: S1_RECEIPT, no_process, tmp_path / "crash.log",
                                  now=lambda: sch + timedelta(seconds=30))
    (out / "captures" / oc / f"{sch.strftime('%Y%m%dT%H%M%SZ')}.resolution.json").unlink()
    with pytest.raises(SystemExit):
        s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT, minutes=47)
    assert _aborted(tmp_path)["reason"] == "registration artifact"
    assert not (out / "seals" / f"{oc}.json").exists()


def test_n3_retro_opening_slot_claims_tie_the_attestation_to_the_opening(tmp_path):
    """RETROSPECTIVE. N-3: after the START attestation and before any RUN-ACK, the opening seal, both records of
    every stage, the opening resolutions, reports and receipt deleted: the remaining opening-slot claims and capture
    directories are opening-tied witnesses, so the attestation's files still witness the registration -> the
    persistent abort (not a refusal that would let the opening be redone)."""
    s1_state(tmp_path, START)
    out = tmp_path / "s1_out"
    con = __import__("sqlite3").connect(tmp_path / "mailbox.sqlite3")
    con.execute("DELETE FROM messages WHERE id=?", ("run-ack",))
    con.commit()
    con.close()
    assert _delete(out, ["seals", "registry", "witnesses", "captures/*/*.resolution.json",
                         "captures/*/*.report.json", "opening_receipt.json"])
    assert not c.opening_orphans(out), c.opening_orphans(out)
    with pytest.raises(SystemExit):
        c.registration_gate(out, "checkpoint", now=lambda: START_DT - timedelta(hours=12))
    assert _aborted(tmp_path)["reason"] == "registration artifact"


def test_n1_retro_a_publication_released_during_the_gate_rescan_is_a_refusal(tmp_path, monkeypatch):
    """RETROSPECTIVE. N-1: the publication is still paused when the gate re-checks the lock (refusal there) - had
    the gate skipped that re-check, its second scan would see the same transient and the publication would release
    the lock before the final check: a false abort."""
    box = _interleave(tmp_path, monkeypatch, "prereg", "released-during-rescan")
    out = tmp_path / "s1_out"
    assert box["stage"] is True and c.load_abort(out) is None, (box, c.load_abort(out))
    assert "stage publication" in box["gate"], box


def test_n3_retro_a_lone_handmade_seal_of_the_opening_close_is_a_refusal(tmp_path):
    """RETROSPECTIVE. N-3/I-2: a hand-made, well-formed seal of the opening close alone (no record, claim, capture or
    RUN-ACK) is one witness - no registration: the opening checkpoint refuses, records no abort."""
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    out = tmp_path / "s1_out"
    close = z.close_of(oc, cal)
    (out / "seals").mkdir(parents=True)
    (out / "seals" / f"{oc}.json").write_text(json.dumps({"close": close.isoformat(), "capture": {}}),
                                               encoding="utf-8")
    assert c.registration_witnesses(out, oc, False) == ["opening seal"]      # (fix round 8: the interface)
    # A3 Task 10 (intended, F4 table 'no INTENT: any artifact for g is a violation after the AUDIT-ACK', `opening`
    # ENFORCED; the Task 7 concern-2 ruling): a hand-made opening seal is TRIAL-INVALID (registration-artifact) - it
    # still manufactures no registration (the witness count above) and records no local abort at the gate
    with pytest.raises(SystemExit, match=r"stage opening: artifacts \['seals/2026-10-23\.json'\] with no INTENT: "
                                         r"INVALID \(registration-artifact\)"):
        s1_opening_checkpoint(tmp_path, Ledger(tmp_path / "l.sqlite3"), oc, cal, S1_RECEIPT)
    assert c.load_abort(out) is None and s1_first_invalid(tmp_path) == "reason/registration-artifact"


def test_n3_retro_the_attestation_between_the_first_slot_and_the_capture_end_refuses(tmp_path):
    """RETROSPECTIVE. A8.1 with the clock anchor: before the opening close's first slot the gate already refuses, so
    the causal-order check is exercised in the interval it alone covers - after the first slot, at or before the
    opening seal's capture end: the attestation refuses with the causal-order reason."""
    s1_state(tmp_path, START, attest=False)      # A3 Task 10 (fixture change): before the journal-bound attestation
    out = tmp_path / "s1_out"
    seal = json.loads((out / "seals" / "2026-10-23.json").read_text(encoding="utf-8"))
    end = c.aware(seal["capture"]["capture_end"])
    assert c.opening_anchor(out) < end
    with _Clock(end), pytest.raises(SystemExit, match="must follow the opening seal's capture"):
        r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
