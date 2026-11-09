"""Task 12 fix round 2 - RETROSPECTIVE tests (written after the code they test), for the A10.2 meaningful-kill rule:
(a) the 8 fix-round-1 mutants killed only by an earlier exception/refusal now have a test whose INTENDED assertion
fails on them; (b) Addendum 2 behaviours that had no direct assertion (an arbitrary or forged resolution, an earlier
close resolved by a later one, run_ack_problems' binding check, binding_problem's field set). Synthetic only."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

import s1_checkpoint as ck
import s1_collect as k
import s1_common as c
import s1_gates as g
import s1_receipt as rc
import s1_run as r
from conftest import s1_prereg_at  # A3 Task 10 (fixture instant)
from conftest import s1_prereg_ack  # A3 Task 6
from conftest import S1_BINDING, S1_PROCESS, S1_RECEIPT, s1_finalize_close, s1_receipt_with, s1_state
from test_s1_t12_a5_a6 import S45, S47, SEAL_P, Snap, _registered
from test_s1_t12_fix2_b1 import Clock, Killed, res_path, run

UTC = timezone.utc
START = "2026-10-26T13:30:00+00:00"


def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


# ====================================================================== (a) the 8 exception-only kills, tightened
def test_mt_token_fields_parses_every_field():
    """Mutant "token_fields keeps only the first field" (fix round 1: killed only by a later refusal)."""
    line = "S1-RUN-ACK runner_sha256=a plan_sha256=b bundle_sha256=c start=2026-10-26T13:30:00+00:00"
    assert c.token_fields(line) == {"runner_sha256": "a", "plan_sha256": "b", "bundle_sha256": "c",
                                    "start": "2026-10-26T13:30:00+00:00"}


def test_mt_load_json_returns_the_files_json(tmp_path):
    """Mutant "load_json reads nothing (empty dict)"."""
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"a": [1, 2]}), encoding="utf-8")
    assert c.load_json(p) == {"a": [1, 2]}


@pytest.mark.parametrize("client", [lambda: httpx.Client(follow_redirects=True), lambda: object()],
                         ids=["follows", "unknown"])
def test_mt_a_client_that_may_follow_redirects_is_refused_by_name(client):
    """Mutant "_require_no_redirects accepts any client"."""
    with pytest.raises(SystemExit, match="follow_redirects must be False"):
        k._require_no_redirects(client())
    k._require_no_redirects(httpx.Client(follow_redirects=False))


def test_mt_the_collectors_loader_returns_the_files_json(tmp_path):
    """Mutant "collect _load reads nothing"."""
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"start": "s"}), encoding="utf-8")
    assert k._load(p) == {"start": "s"}


def test_mt_namespace_dir_is_a_package_directory_without_init(tmp_path):
    """Mutant "_namespace_dir always true"."""
    be = tmp_path / "backend"
    (be / "ns").mkdir(parents=True)
    (be / "pkg").mkdir()
    (be / "pkg" / "__init__.py").write_text("")
    (be / "mod.py").write_text("")
    assert rc._namespace_dir(be, ["ns"]) is True
    assert rc._namespace_dir(be, ["pkg"]) is False and rc._namespace_dir(be, ["mod"]) is False
    assert rc._namespace_dir(be, ["missing"]) is False and rc._namespace_dir(be, []) is False


def test_mt_the_runner_works_under_root_s1_out(tmp_path):
    """Mutant "_out points elsewhere"."""
    assert r._out(tmp_path) == tmp_path / "s1_out"


def test_mt_the_stop_attestation_binds_stop_json(tmp_path):
    """Mutant "attest_stop: binds no stop.json" (fix round 1: killed only by the final plan's later refusal)."""
    s1_state(tmp_path, START, score_ready=True, final=False, final_snapshot=False)
    out = tmp_path / "s1_out"
    assert read(out / "attest_stop.json")["stop_sha256"] == c.sha256_file(out / "stop.json")


def test_mt_the_runners_receipt_hash_is_the_fingerprints():
    """Mutant "_receipt_sha over the whole receipt": provenance never enters the validity hash."""
    other = s1_receipt_with(S1_RECEIPT, head="another-head")
    assert r._receipt_sha(other) == r._receipt_sha(S1_RECEIPT) == c.receipt_sha256(S1_RECEIPT)


# ====================================================================== (b) Addendum 2 behaviours, direct assertions
def test_mt_an_arbitrary_report_file_does_not_resolve_a_slot(tmp_path, monkeypatch):
    """B1.2: a report file dropped for slot 45 (never claimed, no resolution record) resolves nothing: after E45 the
    slot is MISSED and slot 47's capture is the seal."""
    st_ = _registered(tmp_path)
    clock = Clock(S47 + timedelta(seconds=30))
    monkeypatch.setattr(c, "now_utc", clock)
    Snap(monkeypatch)
    run(tmp_path, st_, S47, clock)
    rep47 = read(sorted((tmp_path / "s1_out" / "captures" / "2026-10-26").glob("*.report.json"))[0])
    fake = dict(rep47, scheduled=S45.isoformat())
    (tmp_path / "s1_out" / "captures" / "2026-10-26" / "20261026T204500Z.report.json").write_text(
        json.dumps(fake), encoding="utf-8")
    out, day = tmp_path / "s1_out", next(d for d in st_["calendar"] if d["date"] == "2026-10-26")
    # A3 Task 7 (F3 table, "no row: any claim, capture, report or resolution"): the dropped report resolves nothing
    # and is itself the registration-artifact violation at the finalizer's gate - no MISSED file, no seal from it
    with pytest.raises(SystemExit, match=r"report exists with no journal row .*INVALID \(registration-artifact\)"):
        s1_finalize_close(tmp_path, day, st_["calendar"], lambda: S45 + timedelta(minutes=11))   # (H3, O8)
    assert not res_path(tmp_path, S45).exists() and not SEAL_P(tmp_path).exists()
    assert c.load_abort(out)["reason"] == c.REGISTRATION_ARTIFACT


def test_mt_a_forged_success_without_complete_evidence_never_seals(tmp_path, monkeypatch):
    """B1.2: a resolution claiming SUCCESS without complete evidence is corrupt evidence: the next checkpoint aborts
    ("bad resolution record") and nothing is sealed from it."""
    st_ = _registered(tmp_path)
    clock = Clock(S47 + timedelta(seconds=30))
    monkeypatch.setattr(c, "now_utc", clock)
    Snap(monkeypatch)
    c.publish_exclusive(res_path(tmp_path, S45), json.dumps({"outcome": "SUCCESS", "evidence": {"candidate": {}}})
                        .encode("utf-8"))
    # A3 Task 7 (F3 table): slot 45 has no row, so its forged SUCCESS file is never read or selected - it is the "no
    # row" violation at the next gate (TRIAL-INVALID registration-artifact; the detection half is
    # test_mt_a_forged_success_of_a_no_row_slot_is_invalid): nothing is ever sealed from it
    with pytest.raises(SystemExit, match=r"resolution exists with no journal row .*INVALID \(registration-artifact\)"):
        run(tmp_path, st_, S47, clock)
    assert not SEAL_P(tmp_path).exists()


def test_mt_a_forged_success_of_a_no_row_slot_is_invalid(tmp_path, monkeypatch):
    """The detection half of test_mt_a_forged_success_without_complete_evidence_never_seals (B1.2's "corrupt
    evidence" abort): a SUCCESS resolution forged into a slot with no journal row is the F3 "no row" violation -
    TRIAL-INVALID (registration-artifact) and the abort, with zero live callbacks (Task 7)."""
    st_ = _registered(tmp_path)
    clock = Clock(S47 + timedelta(seconds=30))
    monkeypatch.setattr(c, "now_utc", clock)
    spy = Snap(monkeypatch)
    c.publish_exclusive(res_path(tmp_path, S45), json.dumps({"outcome": "SUCCESS", "evidence": {"candidate": {}}})
                        .encode("utf-8"))
    with pytest.raises(SystemExit, match="registration-artifact"):
        run(tmp_path, st_, S47, clock)
    assert spy.calls == 0 and not SEAL_P(tmp_path).exists()
    assert c.load_abort(tmp_path / "s1_out")["reason"] == c.REGISTRATION_ARTIFACT


def test_mt_a_later_close_resolves_an_earlier_close_left_pending(tmp_path, monkeypatch):
    """B1.4/B1.5: the 10-26 slot-45 worker died and no later slot of that close ran: the next close's checkpoint
    resolves the 10-26 close (RESOLUTION-TIMEOUT, then slot 47's capture is its seal)."""
    st_ = _registered(tmp_path)
    clock = Clock(S45 + timedelta(seconds=30))
    monkeypatch.setattr(c, "now_utc", clock)
    Snap(monkeypatch)

    def die():
        raise Killed()
    with pytest.raises(Killed):
        run(tmp_path, st_, S45, clock, process_fn=die)
    clock.t = S47 + timedelta(seconds=30)
    assert run(tmp_path, st_, S47, clock)["seal"]["written"] is False
    nxt = datetime(2026, 10, 27, 20, 45, tzinfo=UTC)
    clock.t = nxt + timedelta(seconds=30)
    # fix round 1 (review C2): slot 45 is INTENT-only, not terminal: the finalizer's SLOT-TIMEOUT (Task 7's row; the
    # B1 test helper) commits first
    from test_s1_t12_fix2_b1 import D45, timeout_row
    assert timeout_row(tmp_path, st_, S45, D45).outcome == "APPEND"
    run(tmp_path, st_, nxt, clock)
    # A3 Task 6 (B1.3 -> F3, E1.4): the earlier close is resolved from the journal (slot 45: SLOT-TIMEOUT, slot 47
    # QUALIFIED); no RESOLUTION-TIMEOUT file is written into its slot
    assert not res_path(tmp_path, S45).exists()
    assert read(SEAL_P(tmp_path))["capture"]["scheduled"] == S47.isoformat(), "the earlier close was not resolved"


def test_mt_run_ack_problems_names_a_prereg_binding_that_is_not_the_opening_reference(tmp_path):
    """B2.1: prereg's process binding must be the opening seal's REFERENCE (checked by the RUN-ACK verification
    itself, not only by the registration gate)."""
    st_ = _registered(tmp_path)
    out = tmp_path / "s1_out"
    pr = read(out / "prereg.json")
    assert g.run_ack_problems(out, pr) == []
    other = dict(S1_BINDING, exe="D:/x.exe")
    probs = g.run_ack_problems(out, dict(pr, process_binding=other))
    assert "prereg process binding is not the opening seal's registered reference" in probs


def test_mt_binding_problem_requires_exactly_the_binding_fields():
    """B2.3: a binding with an extra or missing field is malformed (never equality)."""
    assert rc.binding_problem(S1_BINDING) == ""
    assert rc.binding_problem(dict(S1_BINDING, extra=1))
    assert rc.binding_problem({k_: v for k_, v in S1_BINDING.items() if k_ != "exe"})
    assert rc.binding_problem(dict(S1_BINDING, exe=7))


# ====================================================================== (c) fix round 2 mutant run: survivors tightened
import sqlite3                                                                            # noqa: E402

import s1_seal as z                                                                       # noqa: E402
from conftest import Ledger, _Clock, _write_seal, s1_opening_checkpoint, s1_plan_audit    # noqa: E402

START_DT = datetime(2026, 10, 26, 13, 30, tzinfo=UTC)
MON = datetime(2026, 10, 26, 20, 0, tzinfo=UTC)


def _reg_prereg(tmp_path):
    st_ = s1_state(tmp_path, START)
    with _Clock(s1_prereg_at(tmp_path)):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    s1_prereg_ack(tmp_path)                    # A3 Task 6 (F7.4): the PREREG-ACK before captures
    st_["ledger"].trade("A", "BUY", 10, 50.0, "2026-10-26T15:00:00+00:00")
    st_["ledger"].set_portfolio("A", 10)
    return st_


def _cp(tmp_path, st_, sch, at, process_fn=None):
    with _Clock(at):
        return ck.run_checkpoint(tmp_path, st_["ledger"].path, sch, lambda: S1_RECEIPT,
                                 process_fn or (lambda: dict(S1_PROCESS)), tmp_path / "crash.log", now=lambda: at)


def test_mt_a_registered_prereg_calendar_not_the_pinned_listing_is_refused_by_the_run_ack_check(tmp_path):
    """Mutant "run_ack_problems: prereg calendar not bound": defence in depth behind the B3 gate - a prereg REGISTERED
    with a calendar that is not the audit's pinned listing (its registry record agrees, so the gate passes) is still
    refused by the RUN-ACK verification."""
    _reg_prereg(tmp_path)
    out = tmp_path / "s1_out"
    pr = read(out / "prereg.json")
    pr["calendar"] = [d for d in pr["calendar"] if d["date"] != "2026-10-28"]
    (out / "prereg.json").write_text(json.dumps(pr), encoding="utf-8")
    for rp in (out / "registry" / "prereg.json", out / "witnesses" / "prereg.json"):   # (fix round 3 migration, C-2:
        rp.write_text(json.dumps(dict(read(rp), artifacts={"prereg.json": c.sha256_file(out / "prereg.json")})),
                      encoding="utf-8")                   # both stage records describe the registered prereg)
    assert c.registration_problems(out) == []
    assert "prereg calendar is not the audit's pinned calendar" in g.run_ack_problems(out, pr)


def test_mt_a_duplicate_slot_execution_is_refused_before_any_capture(tmp_path, monkeypatch):
    """Mutant "_claim_slot allows a duplicate execution": the second execution of a slot is a SystemExit refusal,
    recorded in reruns.jsonl, with no second capture (not a crash later on)."""
    st_ = _reg_prereg(tmp_path)
    spy = Snap(monkeypatch)
    sch = MON + timedelta(minutes=45)
    _cp(tmp_path, st_, sch, sch + timedelta(seconds=30))
    import s1_journal as j
    import s1_trial as t
    mb = tmp_path / "mailbox.sqlite3"
    before = j.read_all(mb)
    with pytest.raises(BaseException) as e:
        _cp(tmp_path, st_, sch, sch + timedelta(seconds=40))
    assert e.type is SystemExit and "a restart never re-intents" in str(e.value)    # A3 Task 6 (F3 pre-check)
    assert spy.calls == 1 and j.read_all(mb) == before                   # no second capture and no row
    assert t.open_trial(mb) is not None


@pytest.mark.parametrize("why", ["late", "failed-observation"])
def test_mt_a_late_or_failed_capture_is_never_a_candidate(tmp_path, monkeypatch, why):
    """Mutants "run_checkpoint: a late capture may seal" / "a failed observation may seal": such a capture is never a
    seal CANDIDATE (not merely refused later by the resolution's completeness check) and its resolution is FAILURE."""
    st_ = _reg_prereg(tmp_path)
    sch = MON + timedelta(minutes=45)
    if why == "late":
        Snap(monkeypatch, dur=timedelta(seconds=61))
        rep = _cp(tmp_path, st_, sch, sch + timedelta(minutes=9))
    else:
        Snap(monkeypatch)
        rep = _cp(tmp_path, st_, sch, sch + timedelta(seconds=30), process_fn=lambda: {"error": "exit 1"})
    assert "candidate" not in rep and rep["seal"]["written"] is False
    assert read(res_path(tmp_path, sch))["outcome"] == "FAILURE"


def test_mt_a_late_opening_capture_is_never_a_candidate(tmp_path, monkeypatch):
    """Mutant "run_opening_checkpoint: a late capture may seal"."""
    s1_plan_audit(tmp_path, START)
    Snap(monkeypatch, dur=timedelta(seconds=61))
    sch = datetime(2026, 10, 23, 20, 45, tzinfo=UTC)
    act = sch + timedelta(minutes=9)
    with _Clock(act):
        rep = ck.run_opening_checkpoint(tmp_path, Ledger(tmp_path / "l.sqlite3").path, sch, lambda: S1_RECEIPT,
                                        lambda: dict(S1_PROCESS), tmp_path / "crash.log", now=lambda: act)
    assert rep["late"] is True and "candidate" not in rep


def test_mt_a_second_persist_never_overwrites_stop_json(tmp_path):
    """Mutant "persist_stop overwrites": a second persist is refused (FileExistsError) and stop.json is unchanged."""
    from test_s1_t12_a2 import _live_stop
    _live_stop(tmp_path)
    out = tmp_path / "s1_out"
    before = (out / "stop.json").read_bytes()
    with pytest.raises(BaseException) as e:
        z.persist_stop(out, dict(read(out / "stop.json"), decided_by="second"))
    assert e.type is FileExistsError and (out / "stop.json").read_bytes() == before


def test_mt_an_unbound_corrupt_seal_is_a_preserved_abort_not_a_crash(tmp_path, monkeypatch):
    """Mutant "_read_seals: a corrupt seal crashes" (I-4b): a corrupt seal that no capture report binds (so the B3
    gate cannot see it) is still a preserved terminal integrity failure at the next checkpoint: its report and the
    abort are written - no exception escapes."""
    st_ = _reg_prereg(tmp_path)
    out = tmp_path / "s1_out"
    _write_seal(out, "2026-10-26", MON, st_["rows"], S1_RECEIPT, start=st_["start"],
                opening_close=z.close_of("2026-10-23", st_["calendar"]))
    (out / "seals" / "2026-10-26.json").write_text("{not json", encoding="utf-8")
    sch = MON + timedelta(days=1, minutes=45)
    # A3 Task 7 (E2.6 r3): the seal is a CREATED seal/<close> stage, so the next command's gate observes its changed,
    # unparseable member: TRIAL-INVALID (stage-replaced) committed before any capture - a preserved refusal with an
    # external record and its evidence copy, never a crash (no other exception escapes)
    try:
        with pytest.raises(SystemExit, match=r"seals/2026-10-26\.json missing or changed.*INVALID \(stage-replaced\)"):
            _cp(tmp_path, st_, sch, sch + timedelta(seconds=30))
    except Exception as e:                                       # noqa: BLE001 - the property under test
        pytest.fail(f"a corrupt seal crashed the checkpoint: {type(e).__name__}")
    assert read(next((out / "invalid").glob("*.json")))["stage"] == "seal/2026-10-26"
    assert not (out / "seals" / "2026-10-27.json").exists()


@pytest.mark.parametrize("attested", [False, True], ids=["publication-gap", "after-stop-attest"])
def test_mt_a_deleted_stop_and_its_registry_record_is_never_recomputed_or_sealed_past(tmp_path, attested):
    """Mutants "stop_was_persisted always false" / "run_checkpoint: a corrupt seal is not an abort" (m-4): stop.json
    AND both stop records deleted.
    A3 Task 11 (un-held; intended F2.3/F2.4 - the journal's TRIAL-STOP detail is the stop's authority, never the
    files): before any finalization INTENT this is the publication gap - the next command's gate recomputes the record
    from the rows before the STOP and publishes bytes whose canonical hash IS the STOP detail (never a different stop),
    and the STOPPED trial seals no later close (its checkpoint is LOST-RACE, no capture, no abort). After the stop
    attestation's INTENT the same deletion is INVALID (registration-artifact): nothing is recomputed, and no later
    close is sealed. (The old oracle - an abort and NO recompute - was the pre-A3 file authority.)"""
    import s1_journal as j
    import s1_trial as t
    from test_s1_t12_a2 import _live_stop
    st_, lg, rows = _live_stop(tmp_path)
    out = tmp_path / "s1_out"
    mbx = tmp_path / "mailbox.sqlite3"
    tr = t.open_trial(mbx)
    stop = j.first(j.read_trial(tr.trial_id, tr.genesis, mbx), "TRIAL-STOP")
    assert stop is not None
    before = (out / "stop.json").read_bytes()
    if attested:
        with _Clock(stop.instant + timedelta(hours=1)):
            r.attest_stop(tmp_path, r.STOP_STATEMENT)
    (out / "stop.json").unlink()
    (out / "registry" / "stop.json").unlink()
    (out / "witnesses" / "stop.json").unlink()
    sch = datetime(2026, 10, 28, 20, 45, tzinfo=UTC)
    with _Clock(sch + timedelta(seconds=30)):
        if attested:
            with pytest.raises(SystemExit, match=r"stop\.json missing: INVALID \(registration-artifact\)"):
                ck.run_checkpoint(tmp_path, lg.path, sch, lambda: S1_RECEIPT, lambda: dict(S1_PROCESS),
                                  tmp_path / "crash.log", now=lambda: sch + timedelta(seconds=30))
            assert not (out / "stop.json").exists(), "a stop was recomputed after a finalization INTENT"
        else:
            rep = ck.run_checkpoint(tmp_path, lg.path, sch, lambda: S1_RECEIPT, lambda: dict(S1_PROCESS),
                                    tmp_path / "crash.log", now=lambda: sch + timedelta(seconds=30))
            assert rep["outcome"] == "LOST-RACE", rep
            assert (out / "stop.json").read_bytes() == before                  # the same record, from the journal
            assert j.detail_of(json.loads(before.decode("utf-8"))) == stop.detail
            assert c.load_abort(out) is None
    assert not (out / "seals" / "2026-10-28.json").exists()


def test_mt_attest_stop_reverifies_the_run_ack(tmp_path):
    """Mutant "attest_stop: registration not verified": a RUN-ACK whose recorded time is after planned START (a
    timing problem the bundle bootstrap does not check) makes the stop attestation refuse."""
    st_ = s1_state(tmp_path, START, score_ready=True, stop_attest=False, final=False, final_snapshot=False)
    con = sqlite3.connect(c.MAILBOX)
    con.execute("UPDATE messages SET created=? WHERE id=?", ((START_DT + timedelta(minutes=1)).timestamp(), "run-ack"))
    con.execute("UPDATE messages SET created=? WHERE id=?",          # A3 (F6.1): its successor stays after it, so
                ((START_DT + timedelta(minutes=2)).timestamp(), "prereg-ack"))   # the ACK chain itself is intact
    con.commit()
    con.close()
    with _Clock(st_["stop_attested_at"]), pytest.raises(SystemExit, match="registration not verified"):
        r.attest_stop(tmp_path, r.STOP_STATEMENT)


def test_mt_a_resolution_claiming_success_for_a_late_capture_never_seals(tmp_path, monkeypatch):
    """Mutant "_complete_success accepts any candidate": a SUCCESS resolution whose evidence is complete in form but
    records a LATE capture is corrupt evidence (ValueError), never a seal."""
    st_ = _registered(tmp_path)
    clock = Clock(S47 + timedelta(seconds=30))
    monkeypatch.setattr(c, "now_utc", clock)
    Snap(monkeypatch)
    run(tmp_path, st_, S47, clock)
    ev = read(res_path(tmp_path, S47))["evidence"]
    forged = {"outcome": "SUCCESS", "slot": S45.isoformat(), "deadline_utc": "x", "published_utc": "x",
              "evidence": dict(ev, scheduled=S45.isoformat(), late=True)}
    c.publish_exclusive(res_path(tmp_path, S45), json.dumps(forged).encode("utf-8"))
    out, day = tmp_path / "s1_out", next(d for d in st_["calendar"] if d["date"] == "2026-10-26")
    # A3 Task 7 (F3): a forged resolution of a slot with no journal row is never selected - the finalizer's gate
    # finds it (the "no row" violation): TRIAL-INVALID (registration-artifact), never a seal
    with pytest.raises(SystemExit, match=r"resolution exists with no journal row .*INVALID \(registration-artifact\)"):
        s1_finalize_close(tmp_path, day, st_["calendar"], lambda: S47 + timedelta(minutes=9))    # (H3, O8)
    assert not SEAL_P(tmp_path).exists()


def test_mt_the_attestation_records_the_opening_binding_hash(tmp_path):
    """Mutant "attest_start binds no process binding": checked on the attestation itself (before any prereg)."""
    s1_state(tmp_path, START)
    att = read(tmp_path / "s1_out" / "attest_start.json")
    assert att["process_binding_sha256"] == c.sha256_bytes(c.canonical(S1_BINDING))


def test_mt_the_opening_is_registered_with_its_seal_hash(tmp_path):
    """Mutant "the opening registration is not recorded": checked right after the opening (before any attestation)."""
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    assert s1_opening_checkpoint(tmp_path, Ledger(tmp_path / "l.sqlite3"), oc, cal, S1_RECEIPT)["seal"]["written"]
    out = tmp_path / "s1_out"
    rec = out / "registry" / "opening.json"
    assert rec.exists(), "the opening was not registered"
    assert read(rec)["artifacts"][f"seals/{oc}.json"] == c.sha256_file(out / "seals" / f"{oc}.json")
    assert read(rec)["process_binding"] == S1_BINDING
