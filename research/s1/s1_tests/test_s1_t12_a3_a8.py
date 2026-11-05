"""Task 12 (controller-added): Addendum 1 rev 3 (sha256 6cb89e36...) sections A3 (registered S1 bundle) and A8
(authorization and bootstrap). Written BEFORE the implementation (RED: s1_evidence/t12_A3_red.txt,
t12_A8_red.txt). All synthetic: tmp_path ledgers and mailbox, fixed clocks; no live DB, network, real mailbox or
scheduler."""
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import s1_checkpoint as ck
import s1_collect as k
import s1_common as c
import s1_run as r
import s1_seal as z
import s1_snapshot
import s1_trial as t
from conftest import s1_prereg_ack  # A3 Task 6
from conftest import (Ledger, S1_PROCESS, S1_RECEIPT, _Clock, s1_mailbox, s1_opening_checkpoint, s1_plan_audit,
                      s1_reack, s1_register, s1_state, s1_unattest)

UTC = timezone.utc
HERE = Path(__file__).resolve().parent.parent
START = "2026-10-26T13:30:00+00:00"                     # Mon 09:30 EDT; opening close Fri 2026-10-23 16:00 EDT
START_DT = datetime(2026, 10, 26, 13, 30, tzinfo=UTC)
OPEN_DAY = "2026-10-23"
OPEN_CLOSE = datetime(2026, 10, 23, 20, 0, tzinfo=UTC)
ADDENDUM_SHA = "6cb89e36840975b8d949ec85debf9d2cedbe45bbeb9dcb374d91343dddc5e590"
BUNDLE = ("e1_fetch.py", "e1_sim.py", "s1_books.py", "s1_checkpoint.py", "s1_collect.py", "s1_common.py",
          "s1_gates.py", "s1_journal.py", "s1_locks.py", "s1_receipt.py", "s1_run.py", "s1_seal.py",
          "s1_slot.py", "s1_snapshot.py", "s1_stage.py", "s1_trial.py")


def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


class Calls:
    """Live-callback spy: receipt, process and snapshot calls (A8: zero on a refusal)."""

    def __init__(self, monkeypatch):
        self.n = {"receipt": 0, "process": 0, "snapshot": 0}
        real = s1_snapshot.take_snapshot

        def snap(*a, **kw):
            self.n["snapshot"] += 1
            return real(*a, **kw)
        monkeypatch.setattr(s1_snapshot, "take_snapshot", snap)

    def receipt(self, rec=S1_RECEIPT):
        def f():
            self.n["receipt"] += 1
            return json.loads(json.dumps(rec))
        return f

    def process(self):
        def f():
            self.n["process"] += 1
            return dict(S1_PROCESS)
        return f

    def zero(self):
        return self.n == {"receipt": 0, "process": 0, "snapshot": 0}


def slot(day, minutes=45, cal=None):
    return z.close_of(day, cal) + timedelta(minutes=minutes)


def checkpoint(root, ledger, cal, day, calls, *, minutes=45, delay=30, receipt=S1_RECEIPT):
    sch = slot(day, minutes, cal)
    act = sch + timedelta(seconds=delay)
    with _Clock(act):
        return ck.run_checkpoint(root, ledger.path, sch, calls.receipt(receipt), calls.process(),
                                 Path(root) / "crash.log", now=lambda: act)


def registered(tmp_path):
    st_ = s1_state(tmp_path, START)
    with _Clock(START_DT - timedelta(days=1)):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    s1_prereg_ack(tmp_path)                    # A3 Task 6 (F7.4): the PREREG-ACK before captures
    return st_


def break_bundle(monkeypatch, sha="f" * 64):
    monkeypatch.setattr(c, "bundle_sha256", lambda *a, **kw: sha)


# ====================================================================== A3.1 the bundle definition
def test_a3_bundle_is_the_explicit_file_list_plus_the_three_document_hashes():
    """A3.1: the bundle = every research/s1 s1_*.py plus the pinned e1_sim.py/e1_fetch.py as an EXPLICIT expected
    file list with sha256, plus the pinned document hashes (the v5 design, the spec, this addendum with its own hash,
    and every later pinned addendum and erratum). Tests are not part of it."""
    assert tuple(sorted(c.BUNDLE_CODE)) == BUNDLE
    assert sorted(p.name for p in HERE.glob("s1_*.py")) == sorted(x for x in BUNDLE if x.startswith("s1_"))
    assert c.DOC_PINS["docs/s1_design_v5_addendum1.md"] == ADDENDUM_SHA
    assert c.DOC_PINS["docs/s1_design_v5.md"].startswith("33c32840")
    assert c.DOC_PINS["docs/s1_spec.md"].startswith("4b882f52")
    assert c.sha256_file(HERE / "docs" / "s1_design_v5_addendum1.md") == ADDENDUM_SHA      # the byte copy
    m = c.bundle_manifest()
    assert set(m["code"]) == set(BUNDLE) and all(m["code"][n] == c.sha256_file(HERE / n) for n in BUNDLE)
    assert m["docs"] == {k_: c.sha256_file(HERE / k_) for k_ in c.DOC_PINS} and m["unexpected"] == {}
    assert c.bundle_problems(m) == [] and c.bundle_sha256() == c.sha256_bytes(c.canonical(m))
    assert not any("s1_tests" in x for x in json.dumps(m).split('"'))


def _copy_tree(tmp_path):
    d = tmp_path / "copy"
    (d / "docs").mkdir(parents=True)
    for n in BUNDLE:
        shutil.copy2(HERE / n, d / n)
    for n in c.DOC_PINS:
        shutil.copy2(HERE / n, d / n)
    (d / "s1_tests").mkdir()
    return d


def test_a3_any_changed_missing_or_extra_bundle_file_or_document_changes_the_bundle(tmp_path, monkeypatch):
    """A3.1: one byte of any listed file or document changes the hash; an extra s1_*.py is an unexpected member (a
    problem and a different hash); a missing member is a problem; a test file or other non-bundle file does not."""
    d = _copy_tree(tmp_path)
    monkeypatch.setattr(c, "HERE", d)
    base = c.bundle_sha256()
    assert base == c.sha256_bytes(c.canonical(c.bundle_manifest())) and c.bundle_problems(c.bundle_manifest()) == []
    (d / "s1_tests" / "test_new.py").write_text("x = 1\n")
    (d / "notes.py").write_text("x = 1\n")
    assert c.bundle_sha256() == base
    for name in list(BUNDLE) + list(c.DOC_PINS):
        p = d / name
        old = p.read_bytes()
        p.write_bytes(old + b"\n")
        assert c.bundle_sha256() != base, name
        p.write_bytes(old)
    assert c.bundle_sha256() == base
    (d / "s1_extra.py").write_text("x = 1\n")
    assert c.bundle_sha256() != base and any("s1_extra.py" in x for x in c.bundle_problems(c.bundle_manifest()))
    (d / "s1_extra.py").unlink()
    (d / "s1_seal.py").rename(d / "gone.txt")
    assert c.bundle_sha256() != base and any("s1_seal.py" in x for x in c.bundle_problems(c.bundle_manifest()))


def test_a3_pinned_core_cache_is_keyed_by_resolved_path_and_approved_hash(tmp_path):
    """A3.1: caches are keyed by resolved path + approved hash: the same module name loaded from another approved
    file is that file's module, never the first one loaded."""
    a, b_ = tmp_path / "a.py", tmp_path / "b.py"
    a.write_text("X = 1\n")
    b_.write_text("X = 2\n")
    ma = c.load_pinned("t12_same_name", a, c.sha256_file(a))
    mb = c.load_pinned("t12_same_name", b_, c.sha256_file(b_))
    assert (ma.X, mb.X) == (1, 2)
    assert c.load_pinned("t12_same_name", a, c.sha256_file(a)) is ma


# ====================================================================== A3.1 binding by every stage
def test_a3_run_acquire_score_tokens_prereg_and_every_seal_bind_the_bundle(tmp_path, monkeypatch):
    """A3.1: RUN-ACK, prereg, the opening and every trial seal, ACQUIRE-ACK, SCORE-ACK (and the final snapshot and
    final manifest, A3.4) bind the bundle hash."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    b_ = c.bundle_sha256()
    assert f" bundle_sha256={b_} " in r.run_token(tmp_path) + " "
    assert read(out / "prereg.json")["bundle_sha256"] == b_
    assert f"bundle_sha256={b_}" in r.score_token(tmp_path) and f"bundle_sha256={b_}" in k.acquire_token(tmp_path)
    assert f"bundle_sha256={b_}" in k.audit_token(tmp_path)
    assert all(read(p)["bundle_sha256"] == b_ for p in (out / "seals").glob("*.json"))
    assert read(out / "final_snapshot" / "report.json")["bundle_sha256"] == b_
    assert "toolchain_sha256" not in json.dumps(read(out / "prereg.json"))


# ====================================================================== A3.2 / A3.3 verified first, persistent
def test_a3_checkpoint_bundle_mismatch_is_a_persistent_abort_before_any_helper_or_capture(tmp_path, monkeypatch):
    """A3.2/A3.3: the scheduled checkpoint compares the bundle FIRST (before protocol state, a stop helper or any
    live capture); a mismatch against the valid registered bundle writes aborted.json reason "bundle"; restoring
    the files does not resume the trial (the next checkpoint is post_stop, never seals)."""
    st_ = registered(tmp_path)
    out = tmp_path / "s1_out"
    calls = Calls(monkeypatch)
    for name in ("stop_decision", "count_sold", "check_fences"):
        monkeypatch.setattr(z, name, lambda *a, **kw: pytest.fail("protocol helper ran before the bundle check"))
    with monkeypatch.context() as m:
        m.setattr(c, "bundle_sha256", lambda *a, **kw: "f" * 64)
        with pytest.raises(SystemExit, match="bundle"):
            checkpoint(tmp_path, st_["ledger"], st_["calendar"], "2026-10-26", calls)
    assert calls.zero() and not list(out.glob("captures/2026-10-26/*"))
    ab = read(out / "aborted.json")
    assert ab["reason"] == "bundle" and ab["expected_bundle_sha256"] == c.bundle_sha256()
    assert ab["observed_bundle_sha256"] == "f" * 64
    monkeypatch.undo()                                                   # files "restored"
    calls = Calls(monkeypatch)
    with pytest.raises(t.Refusal, match=r"trial INVALID \(reason/bundle\)"):      # A3 F6.4/F0.6: no work at all
        checkpoint(tmp_path, st_["ledger"], st_["calendar"], "2026-10-26", calls, minutes=47)
    assert calls.zero() and read(out / "aborted.json") == ab


def test_a3_opening_checkpoint_bundle_mismatch_refuses_with_zero_callbacks_and_no_abort(tmp_path, ledger,
                                                                                        monkeypatch):
    """A3.2 + A8.2: the opening mode's expected bundle is the externally approved one (the AUDIT-ACK's). A3 F6.4
    (intended change): the audit stage's journal rows exist before the opening, so a mismatch is INVALID (bundle)
    plus the local abort, still with zero live callbacks and no capture (the no-row refusal: test_s1_a3_gate)."""
    s1_plan_audit(tmp_path, START)
    calls = Calls(monkeypatch)
    break_bundle(monkeypatch)
    sch = OPEN_CLOSE + timedelta(minutes=45)
    with _Clock(sch + timedelta(seconds=30)):
        with pytest.raises(t.Refusal, match=r"INVALID \(bundle\)"):
            ck.run_opening_checkpoint(tmp_path, ledger.path, sch, calls.receipt(), calls.process(),
                                      tmp_path / "crash.log", now=lambda: sch + timedelta(seconds=30))
    assert calls.zero() and read(tmp_path / "s1_out" / "aborted.json")["reason"] == "bundle"
    assert not (tmp_path / "s1_out" / "captures").exists()


@pytest.mark.parametrize("gate", ["attest_start", "do_prereg"])
def test_a3_r1_attest_start_and_prereg_refuse_a_bundle_differing_from_the_opening_seal(tmp_path, monkeypatch, gate):
    """A3.3 / final-review R-1: from the opening seal on, a bundle that differs from the registered one (the opening
    seal's = the AUDIT-ACK's) is a persistent "bundle" abort at the START attestation and at prereg."""
    st_ = s1_state(tmp_path, START)
    out = tmp_path / "s1_out"
    if gate == "attest_start":
        (out / "attest_start.json").unlink()
        (out / "opening_books.json").unlink()
    break_bundle(monkeypatch)
    with _Clock(START_DT - timedelta(days=1)):
        with pytest.raises(SystemExit, match="bundle"):
            if gate == "attest_start":
                r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
            else:
                r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    assert read(out / "aborted.json")["reason"] == "bundle" and not (out / "prereg.json").exists()
    monkeypatch.undo()
    with _Clock(START_DT - timedelta(days=1)):
        with pytest.raises(SystemExit, match=r"trial INVALID \(reason/bundle\)"):
            r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)            # never resumes after restoration
    assert not (out / "prereg.json").exists()


def test_a3_score_bundle_mismatch_aborts_reserves_nothing_and_restoration_scores_aborted_invalid(tmp_path,
                                                                                                 monkeypatch):
    """A3.3/A3.4: a score under another bundle writes the persistent "bundle" abort and reserves no score; after the
    files are restored, the one score is ABORTED-INVALID with that reason (no valid score, no re-clock)."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    with monkeypatch.context() as m:
        m.setattr(c, "bundle_sha256", lambda *a, **kw: "e" * 64)
        with pytest.raises(SystemExit, match="bundle"):
            r.score(tmp_path, "score-ack")
    assert not (out / "score").exists() and read(out / "aborted.json")["reason"] == "bundle"
    later = st_["now"] + timedelta(hours=2)          # the SCORE-ACK must follow the trial's end (here: the abort)
    monkeypatch.setattr(c, "now_utc", lambda: later)
    s1_reack(tmp_path, "score-ack-2", "S1-SCORE-ACK", later - timedelta(minutes=30))
    with pytest.raises(t.Refusal, match=r"trial INVALID \(reason/bundle\)"):      # A3 F0.6/F1: INVALID, no score
        r.score(tmp_path, "score-ack-2")
    assert not (out / "score").exists()


@pytest.mark.parametrize("where", ["seal", "final_snapshot", "final_manifest", "prereg"])
def test_a3_score_checks_bundle_consistency_across_every_artifact(tmp_path, monkeypatch, where):
    """A3.4: score checks bundle consistency across prereg, every seal, the final snapshot, the final manifest and
    itself; current-hash equality alone is not sufficient."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    p = {"seal": out / "seals" / "2026-10-26.json", "final_snapshot": out / "final_snapshot" / "report.json",
         "final_manifest": out / "final" / "manifest.json", "prereg": out / "prereg.json"}[where]
    obj = read(p)
    obj["bundle_sha256"] = "0" * 64
    p.write_text(json.dumps(obj), encoding="utf-8")
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    s1_reack(tmp_path, "score-ack-2", "S1-SCORE-ACK", st_["now"] - timedelta(minutes=30))
    try:
        rep = r.score(tmp_path, "score-ack-2")
    except SystemExit as e:                                  # prereg: the registration itself no longer verifies
        assert not (out / "score").exists()
        if where == "seal":                                  # A3 Task 7 (E2.6 r3): an edited seal is a CREATED
            assert "seals/2026-10-26.json missing or changed" in str(e) and "INVALID (stage-replaced)" in str(e), e
            rep = json.loads(r._serialise(r._score(out)))    # seal stage's changed member: refused; the unit record
        else:
            assert where == "prereg" and ("bundle" in str(e) or "RUN-ACK" in str(e)), e
            return
    assert rep["verdict"] == "ABORTED-INVALID" and any("bundle" in x for x in rep["reasons"]), rep["reasons"]


@pytest.mark.parametrize("command", ["attest_stop", "write_final_plan", "final_snapshot"])
def test_a3_post_stop_commands_verify_the_bundle_first(tmp_path, monkeypatch, command):
    """A3.2: every S1 command - including the post-stop ones - compares the bundle first; a mismatch is the
    persistent "bundle" abort (Q2: post-stop changes to the S1 bundle cannot silently alter the protocol)."""
    st_ = s1_state(tmp_path, START, score_ready=True, stop_attest=False, final_snapshot=False)
    out = tmp_path / "s1_out"
    for p in (out / "final_plan.json",):
        if p.exists() and command == "write_final_plan":
            p.unlink()
    break_bundle(monkeypatch)
    with _Clock(st_["now"]):
        with pytest.raises(SystemExit, match="bundle"):
            if command == "attest_stop":
                r.attest_stop(tmp_path, r.STOP_STATEMENT)
            elif command == "write_final_plan":
                k.write_final_plan(tmp_path)
            else:
                ck.run_final_snapshot(tmp_path, st_["ledger"].path, now=lambda: st_["now"])
    assert read(out / "aborted.json")["reason"] == "bundle"
    assert not (out / "attest_stop.json").exists() and not (out / "final_snapshot").exists()


def test_a3_final_acquisition_verifies_the_bundle_before_any_request(tmp_path, monkeypatch):
    """A3.2/A7.1: do_final compares the bundle before reserving or requesting."""
    import httpx
    st_ = s1_state(tmp_path, START, score_ready=True, final_snapshot=False)
    out = tmp_path / "s1_out"
    shutil.rmtree(out / "final")
    seen = []
    cl = httpx.Client(transport=httpx.MockTransport(lambda req: seen.append(req) or httpx.Response(500)),
                      follow_redirects=False)
    break_bundle(monkeypatch)                        # (A3: the fixture's one ACQUIRE-ACK "acq-ack", F7.1)
    with _Clock(st_["now"]):
        with pytest.raises(t.Refusal, match=r"INVALID \(bundle\)"):
            k.do_final(tmp_path, "acq-ack", cl, ("K", "S"))
    assert seen == [] and not (out / "final").exists() and read(out / "aborted.json")["reason"] == "bundle"


# ====================================================================== A8.1 bootstrap order and bindings
def test_a8_audit_manifest_binds_the_plan_and_the_audit_ack_binds_the_bundle(tmp_path):
    """A8.1: the audit manifest binds plan_sha256 (no silent reuse of an audit after a plan change); the
    AUDIT-ACK token carries the bundle (the opening mode's externally approved expected bundle)."""
    s1_plan_audit(tmp_path, START)
    out = tmp_path / "s1_out"
    tok = k.audit_token(tmp_path)
    assert tok.startswith("S1-AUDIT-ACK ") and f"bundle_sha256={c.bundle_sha256()}" in tok
    assert f"plan_sha256={c.sha256_file(out / 'plan.json')}" in tok
    assert read(out / "audit" / "manifest.json")["plan_sha256"] == c.sha256_file(out / "plan.json")


def test_a8_run_ack_binds_opening_seal_frozen_opening_books_audit_attestation_and_bundle(tmp_path):
    """A8.1: RUN-ACK binds the opening seal, the frozen opening books (s1_out/opening_books.json, written by the
    START attestation from the opening seal's rows and bound by it), the audit, the attestation and the bundle."""
    s1_state(tmp_path, START, carry_in=(("CI", 10, 50.0, "2026-10-01T15:00:00+00:00"),))
    out = tmp_path / "s1_out"
    books = read(out / "opening_books.json")
    assert books["opening_seal_sha256"] == c.sha256_file(out / "seals" / f"{OPEN_DAY}.json")
    assert [l_["symbol"] for l_ in books["economic_lots"]] == ["CI"] and books["operational"]["qty"] == {"CI": 10.0}
    att = read(out / "attest_start.json")
    assert att["opening_books_sha256"] == c.sha256_file(out / "opening_books.json")
    tok = r.run_token(tmp_path)
    for key, p in (("opening_seal_sha256", out / "seals" / f"{OPEN_DAY}.json"),
                   ("opening_books_sha256", out / "opening_books.json"),
                   ("audit_manifest_sha256", out / "audit" / "manifest.json"),
                   ("attest_start_sha256", out / "attest_start.json"), ("plan_sha256", out / "plan.json")):
        assert f"{key}={c.sha256_file(p)}" in tok, key
    assert f"bundle_sha256={c.bundle_sha256()}" in tok
    with _Clock(START_DT - timedelta(days=1)):
        pr = r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    assert pr["opening_books_sha256"] == c.sha256_file(out / "opening_books.json")
    assert pr["opening_seal_sha256"] == c.sha256_file(out / "seals" / f"{OPEN_DAY}.json")


def test_a8_attest_start_refuses_before_the_opening_seal_capture(tmp_path):
    """A8.1 causal order: the START attestation comes after the opening capture and seal."""
    st_ = s1_state(tmp_path, START)
    out = tmp_path / "s1_out"
    s1_unattest(tmp_path)                                 # (fix round 2 migration, B3: the pre-attestation state)
    with _Clock(OPEN_CLOSE + timedelta(minutes=40)):
        with pytest.raises(SystemExit, match="opening seal"):
            r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)


# ====================================================================== A8.2 stage-specific causal ACK verification
def test_a8_hand_made_prereg_reaches_no_live_callback(tmp_path, ledger, monkeypatch):
    """A8.2 / Codex 0a58b934 probe e: a hand-made prereg (start/calendar/receipt/bundle, no verified RUN-ACK) refuses
    with ZERO live callbacks (no snapshot, process or receipt call) and writes nothing."""
    import test_s1_seal as ts
    out = tmp_path / "s1_out"
    out.mkdir()
    (out / "prereg.json").write_text(json.dumps({"start": "2026-10-14T13:30:00+00:00", "calendar": ts.CAL,
                                                 "receipt": S1_RECEIPT, "bundle_sha256": c.bundle_sha256(),
                                                 "ack": {"ack_id": "nope", "created_utc": "2026-10-13T00:00:00+00:00"}}),
                                     encoding="utf-8")
    calls = Calls(monkeypatch)
    sch = datetime(2026, 10, 15, 20, 45, tzinfo=UTC)
    with _Clock(sch + timedelta(seconds=30)):
        with pytest.raises((SystemExit, sqlite3.Error)):
            ck.run_checkpoint(tmp_path, ledger.path, sch, calls.receipt(), calls.process(), tmp_path / "crash.log",
                              now=lambda: sch + timedelta(seconds=30))
    # (fix round 2, B3.2: the refusal is preserved - refusals.jsonl - and nothing else is written)
    assert calls.zero() and sorted(p.name for p in out.iterdir()) == ["prereg.json", "refusals.jsonl"]


# Task 5 fix round 1 (review I-3): the intended refusal of each breakage (B3: no bare SystemExit)
_REG = r"registration artifact\(s\) missing or changed"
WHY420 = {"plan_edited": _REG, "attest_edited": _REG, "books_edited": _REG, "prereg_binding": _REG,
          "ack_deleted": "RUN-ACK not verified", "ack_after_start": "registration not verified",
          "ack_before_attestation": "registration not verified"}
WHY478 = {"no_ack_recorded": "the audit manifest names no AUDIT-ACK",
          "ack_missing_from_mailbox": "zero open trials",                       # A3 F6.3: no AUDIT-ACK = no trial
          "plan_edited_after_audit": "audit is not bound to the current plan",
          "ack_before_plan": "the audit manifest's ACK time differs from the mailbox",          # (see report: the
          "ack_after_reservation": "the audit manifest's ACK time differs from the mailbox",    # causal order is
          "manifest_plan_sha": "audit is not bound to the current plan",                          # tested in
          "raw_page_tampered": "raw page audit/pages/calendar.json missing or differs",          # mutant_survivors)
          "calendar_source_tampered": "calendar_source.json missing or differs from its manifest hash"}


@pytest.mark.parametrize("breakage", ["plan_edited", "attest_edited", "books_edited", "ack_deleted",
                                      "ack_after_start", "ack_before_attestation", "prereg_binding"])
def test_a8_checkpoint_verifies_the_run_ack_identity_bindings_and_timing_before_capture(tmp_path, monkeypatch,
                                                                                         breakage):
    """A8.2: a normal checkpoint requires a verified prereg + RUN-ACK: identity (codex->claude experiments-prereg
    message carrying the exact RUN token rebuilt from the current artifacts), artifact bindings and causal timing
    (after the START attestation, before planned START); otherwise it refuses with zero live callbacks."""
    st_ = registered(tmp_path)
    out = tmp_path / "s1_out"
    if breakage == "plan_edited":
        p = out / "plan.json"
        p.write_text(json.dumps(dict(read(p), note="edited")), encoding="utf-8")
    elif breakage == "attest_edited":
        p = out / "attest_start.json"
        p.write_text(json.dumps(dict(read(p), note="edited")), encoding="utf-8")
    elif breakage == "books_edited":
        p = out / "opening_books.json"
        p.write_text(json.dumps(dict(read(p), note="edited")), encoding="utf-8")
    elif breakage == "ack_deleted":
        con = sqlite3.connect(c.MAILBOX)
        con.execute("DELETE FROM messages WHERE id='run-ack'")
        con.execute("DELETE FROM messages WHERE id='prereg-ack'")    # A3 Task 6: (its PREREG-ACK chains to it)
        con.commit()
        con.close()
    elif breakage in ("ack_after_start", "ack_before_attestation"):
        t = (START_DT + timedelta(minutes=1) if breakage == "ack_after_start"
             else c.aware(read(out / "attest_start.json")["recorded_utc"]) - timedelta(minutes=1))
        con = sqlite3.connect(c.MAILBOX)
        con.execute("UPDATE messages SET created=? WHERE id='run-ack'", (t.timestamp(),))
        con.execute("DELETE FROM messages WHERE id='prereg-ack'")    # A3 Task 6: (its PREREG-ACK chains to it)
        con.commit()
        con.close()
    else:
        p = out / "prereg.json"
        p.write_text(json.dumps(dict(read(p), plan_sha256="0" * 64)), encoding="utf-8")
    calls = Calls(monkeypatch)
    with pytest.raises(SystemExit, match=WHY420[breakage]):
        checkpoint(tmp_path, st_["ledger"], st_["calendar"], "2026-10-26", calls)
    assert calls.zero() and not (out / "captures" / "2026-10-26").exists()
    if breakage in ("plan_edited", "attest_edited", "books_edited", "prereg_binding"):
        # (fix round 2, B3.3: a registered artifact edited after registration is the persistent abort)
        assert read(out / "aborted.json")["reason"] == "registration artifact"
    else:
        assert not (out / "aborted.json").exists()                    # an authorization refusal, not an abort


def test_a8_valid_registration_reaches_the_capture(tmp_path, monkeypatch):
    """A8.2 control: the same checkpoint with the genuine registration captures and seals."""
    st_ = registered(tmp_path)
    calls = Calls(monkeypatch)
    rep = checkpoint(tmp_path, st_["ledger"], st_["calendar"], "2026-10-26", calls)
    assert calls.n == {"receipt": 1, "process": 1, "snapshot": 1} and rep["seal"]["written"] is True


@pytest.mark.parametrize("breakage", ["no_ack_recorded", "ack_missing_from_mailbox", "plan_edited_after_audit",
                                      "ack_before_plan", "ack_after_reservation", "manifest_plan_sha",
                                      "raw_page_tampered", "calendar_source_tampered"])
def test_a8_opening_mode_verifies_the_audit_ack_plan_calendar_and_source_bindings_before_capture(
        tmp_path, ledger, monkeypatch, breakage):
    """A8.2: the opening mode verifies the AUDIT-ACK (identity, token from the current plan/collector/bundle, after
    the plan and before the audit reservation), the audit manifest's plan_sha256, and the calendar and its pinned
    source (A6/A7.4 raw page), with no prereg prerequisite; any failure refuses with zero live callbacks."""
    s1_plan_audit(tmp_path, START)
    out = tmp_path / "s1_out"
    mp = out / "audit" / "manifest.json"
    if breakage == "no_ack_recorded":
        mp.write_text(json.dumps(dict(read(mp), ack={})), encoding="utf-8")
    elif breakage == "ack_missing_from_mailbox":
        con = sqlite3.connect(c.MAILBOX)
        con.execute("DELETE FROM messages WHERE id='audit-ack'")
        con.commit()
        con.close()
    elif breakage == "plan_edited_after_audit":
        p = out / "plan.json"
        p.write_text(json.dumps(dict(read(p), note="edited")), encoding="utf-8")
    elif breakage in ("ack_before_plan", "ack_after_reservation"):
        plan = read(out / "plan.json")
        t = (c.aware(plan["created_utc"]) - timedelta(minutes=1) if breakage == "ack_before_plan"
             else c.aware(read(out / "audit" / "attempt.json")["reserved_utc"]) + timedelta(minutes=1))
        con = sqlite3.connect(c.MAILBOX)
        con.execute("UPDATE messages SET created=? WHERE id='audit-ack'", (t.timestamp(),))
        con.commit()
        con.close()
    elif breakage == "manifest_plan_sha":
        mp.write_text(json.dumps(dict(read(mp), plan_sha256="0" * 64)), encoding="utf-8")
    elif breakage == "raw_page_tampered":
        pg = out / "audit" / "pages" / "calendar.json"
        pg.write_bytes(pg.read_bytes() + b" ")
    else:
        src = out / "audit" / "calendar_source.json"
        src.write_text(json.dumps(dict(read(src), retrieved_utc="2020-01-01T00:00:00+00:00")), encoding="utf-8")
    calls = Calls(monkeypatch)
    sch = OPEN_CLOSE + timedelta(minutes=45)
    with _Clock(sch + timedelta(seconds=30)):
        # A3 Task 9 (intended, F4 table CREATED row + F4.9 consistency): a changed member or bound input of the
        # CREATED audit stage is INVALID (stage-replaced) at the gate, before the A8.2 checks run; those checks'
        # own reasons are kept at unit level below (the same tampered files)
        with pytest.raises(SystemExit, match=(r"stage audit: .*INVALID \(stage-replaced\)" if breakage in A3_T9_STAGE
                                              else WHY478[breakage])):
            ck.run_opening_checkpoint(tmp_path, ledger.path, sch, calls.receipt(), calls.process(),
                                      tmp_path / "crash.log", now=lambda: sch + timedelta(seconds=30))
        if breakage == "no_ack_recorded":
            with pytest.raises(SystemExit, match=WHY478[breakage]):
                c.registration(out, c.MAILBOX)
        elif breakage in A3_T9_STAGE:
            import s1_gates as g
            with pytest.raises(g.Invalid, match=WHY478[breakage]):
                g.verified_audit(out, c.MAILBOX)
    assert calls.zero() and not (out / "captures").exists()


# A3 Task 9: the breakages that change a CREATED audit member (manifest, raw page, calendar_source) or its bound input
# (plan.json) - the gate's stage table (F4) sees them first
A3_T9_STAGE = ("no_ack_recorded", "plan_edited_after_audit", "manifest_plan_sha", "raw_page_tampered",
               "calendar_source_tampered")


def test_a8_do_audit_checks_the_ack_is_after_the_plan(tmp_path, monkeypatch):
    """A8.2: the AUDIT-ACK must be created after the plan it binds (and before planned START); an earlier one
    refuses before any request or reservation."""
    import httpx
    fixed = datetime(2026, 10, 21, 12, tzinfo=UTC)
    monkeypatch.setattr(c, "now_utc", lambda: fixed)
    k.write_plan(tmp_path, datetime(2026, 11, 2, 14, 30, tzinfo=UTC), "2026-10-30", ["A"], "2026-10-01")
    s1_mailbox(tmp_path, "a1", k.audit_token(tmp_path), fixed - timedelta(minutes=5))
    monkeypatch.setattr(c, "now_utc", lambda: fixed + timedelta(hours=1))
    seen = []
    cl = httpx.Client(transport=httpx.MockTransport(lambda req: seen.append(req) or httpx.Response(500)),
                      follow_redirects=False)
    with pytest.raises(SystemExit, match="plan"):
        k.do_audit(tmp_path, "a1", cl, ("K", "S"))
    assert seen == [] and not (tmp_path / "s1_out" / "audit").exists()


def test_a8_score_reverifies_the_run_ack_before_reserving(tmp_path, monkeypatch):
    """A8.2 / mapping 2.1: the score re-verifies the registration's RUN-ACK in the mailbox; an unverifiable one
    refuses before the reservation (no output)."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    con = sqlite3.connect(c.MAILBOX)
    con.execute("DELETE FROM messages WHERE id='run-ack'")
    con.commit()
    con.close()
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    with pytest.raises(SystemExit, match="RUN-ACK"):
        r.score(tmp_path, "score-ack")
    assert not (tmp_path / "s1_out" / "score").exists()


def test_a8_genuine_bootstrap_through_s1_register_then_checkpoint(tmp_path, monkeypatch):
    """A8.1: the causal bootstrap (plan -> AUDIT-ACK -> audit -> opening seal -> START attestation -> RUN-ACK ->
    prereg) with no hand-made artifact; a scheduled checkpoint on another START weekday then verifies and seals."""
    import test_s1_seal as ts
    reg = s1_register(tmp_path, "2026-10-14T13:30:00+00:00", calendar=ts.CAL)
    calls = Calls(monkeypatch)
    lg = Ledger(tmp_path / "trading.db")
    rep = checkpoint(tmp_path, lg, ts.CAL, "2026-10-15", calls)
    assert rep["seal"]["written"] is True and reg["prereg"]["bundle_sha256"] == c.bundle_sha256()
