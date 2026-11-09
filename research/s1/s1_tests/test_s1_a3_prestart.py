"""Addendum 3 rev 5 F3 (the opening seal is a stage, opened only after the first QUALIFIED opening slot with every
earlier slot terminal), F4.8 rows opening/start_attest/prereg, F7.2 (OPENING-ACK verified against the journal;
issuance helper; (b) literal), F7.3 (live-file check), F7.4 (deadlines; RUN-ACK fields), E3 (BLOCKED record; accepted
in the adopted Erratum 1, de008b1), E5.3, E5.5 (evidence manifest; INVALIDATE on mismatch), E5.6 (opening window).
Behavioural RED against the Task 10 stub (s1_evidence/a3/t10_red.txt). Synthetic ledgers; tmp mailbox; spies.
A3 Task 10 additions after the plan's list (the controller's carry-forwards): the second-opening-seal guard (Task 6
M6), the opening close on the journal finalizer (Task 7 concern 7: no file into a live slot, a crashed opening worker's
TIMEOUT at D determines the close, N2), the gate hook order and a foreign root (opening_manifest_check), the E5.5
format."""
import json
import re
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
import s1_checkpoint as ck
import s1_common as c
import s1_journal as j
import s1_locks as L
import s1_run as r
import s1_seal as z
import s1_slot as sl
import s1_stage as sg
import s1_trial as t
from conftest import (Ledger, S1_LOCAL_ABORT, S1_PROCESS, S1_RECEIPT, Spies, _Clock, s1_ack, s1_jappend,  # noqa: F401
                      s1_mailbox, s1_mailbox_init, s1_opening_checkpoint, s1_plan_audit, s1_state)

START = "2026-10-26T13:30:00+00:00"
HELPERS = Path(__file__).resolve().parent / "a3_helpers.py"


def mb(root):
    return Path(root) / "mailbox.sqlite3"


def jrows(root):
    tr = t.open_trial(mb(root))
    return j.read_trial(tr.trial_id, tr.genesis, mb(root))


def stage_kinds(root, stage):
    return [x.kind for x in j.subject_rows(jrows(root), j.stage_subject(stage))]


def opened(root, minutes=45):
    start, cal, oc, _ = s1_plan_audit(root, START)
    lg = Ledger(Path(root) / "opening_ledger.sqlite3")
    rep = s1_opening_checkpoint(root, lg, oc, cal, S1_RECEIPT, minutes=minutes)
    return start, cal, oc, lg, rep


def opening_slot(cal, oc, minutes):
    return z.close_of(oc, cal) + timedelta(minutes=minutes)


def _staged(root, stage, name):
    """(A3 Task 10, as Task 9 D3) the staging file, asserted present first (so a RED is an assertion)."""
    tr = t.open_trial(mb(root))
    p = sg.staging_dir(root, tr.trial_id, stage) / name
    assert p.is_file(), f"no staged {stage}/{name}"
    return json.loads(p.read_bytes())


def env(root, stage):
    return _staged(root, stage, "intent.json")


def com(root, stage):
    return _staged(root, stage, "prepared.json")


@pytest.mark.parametrize("case", ["pending-earlier", "failed-earlier", "first-qualified"])
def test_opening_intent_only_after_the_first_qualified_slot_and_earlier_slots_terminal(tmp_path, case):   # row 81
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    lg = Ledger(tmp_path / "opening_ledger.sqlite3")
    s45, s47 = opening_slot(cal, oc, 45), opening_slot(cal, oc, 47)
    if case == "pending-earlier":
        s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(s45), at=s45 + timedelta(seconds=1))
    elif case == "failed-earlier":
        with _Clock(s45 - timedelta(seconds=5)):
            ck.run_opening_checkpoint(tmp_path, lg.path, s45, lambda reference=None: S1_RECEIPT,
                                      lambda: dict(S1_PROCESS), tmp_path / "c.log",
                                      now=lambda: s45 - timedelta(seconds=5))
    if case == "first-qualified":
        s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT, minutes=45)
    else:
        s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT, minutes=47)
    want = [] if case == "pending-earlier" else ["STAGE-INTENT", "STAGE-PREPARED", "STAGE-CREATED"]
    assert stage_kinds(tmp_path, "opening") == want
    assert (tmp_path / "s1_out" / "seals" / f"{oc}.json").exists() == bool(want)


def test_opening_stage_envelope_and_single_member(tmp_path):                           # row 103
    start, cal, oc, lg, rep = opened(tmp_path)
    e, cm = env(tmp_path, "opening"), com(tmp_path, "opening")
    assert set(e["inputs"]) == {"plan.json", "audit/manifest.json", "opening_receipt.json", "qualified_line",
                                "tree_manifest"}
    q = j.first(j.subject_rows(jrows(tmp_path), j.slot_subject(opening_slot(cal, oc, 45))), "SLOT-QUALIFIED")
    assert (e["inputs"]["qualified_line"], e["inputs"]["tree_manifest"]) == (q.sha, q.detail)
    assert cm["kind"] == "single" and list(cm["members"]) == [f"seals/{oc}.json"] and e["acks"] == {}


def close_out(root, cal, oc):
    """F7.2(b) literal (OQ-37 ruling): run the finalizer to the W slot's E so that EVERY scheduled opening-close
    slot is terminal (later opening slots were refused with no row by the opening gate and end MISSED)."""
    day = next(d for d in cal if d["date"] == oc)
    last = z.schedule(day, cal)[-1]
    e_w = z.eligible_until(last, day, cal)
    gv = t.gate(root, "close out the opening close")
    with _Clock(e_w):
        sl.finalize_close(gv, day, cal, lambda: e_w, mailbox=mb(root))
    return e_w


def _open_and_ack(root, **override):
    start, cal, oc, lg, rep = opened(root)
    w = close_out(root, cal, oc)
    s1_ack(root, "opening-ack", "S1-OPENING-ACK", w + timedelta(minutes=1), **override)
    return start, cal, oc, w


def test_start_attest_envelope_and_single_member(tmp_path):                           # rows 104, 268 (OQ-15)
    start, cal, oc, w = _open_and_ack(tmp_path)
    with _Clock(w + timedelta(minutes=2)):
        r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    e, cm = env(tmp_path, "start_attest"), com(tmp_path, "start_attest")
    books = tmp_path / "s1_out" / "opening_books.json"
    assert set(e["inputs"]) == {"plan.json", "audit/manifest.json", f"seals/{oc}.json", "opening_receipt.json",
                                "opening_books.json"}
    assert e["inputs"]["opening_books.json"] == c.sha256_file(books)
    assert e["acks"] == {"S1-OPENING-ACK": t.open_trial(mb(tmp_path)).acks["S1-OPENING-ACK"].sha}
    assert cm["kind"] == "single" and list(cm["members"]) == ["attest_start.json"]
    rec = json.loads((tmp_path / "s1_out" / "attest_start.json").read_bytes())
    assert rec["opening_books_sha256"] == c.sha256_file(books)


@pytest.mark.parametrize("case", ["changed", "deleted"])
def test_opening_books_is_a_hash_bound_derived_input(tmp_path, monkeypatch, case):    # row 268 (OQ-15)
    start, cal, oc, w = _open_and_ack(tmp_path)
    books = tmp_path / "s1_out" / "opening_books.json"
    with _Clock(w + timedelta(minutes=2)):
        r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    if case == "changed":
        books.write_bytes(books.read_bytes() + b" ")                  # the TEST changes its tmp opening books
    else:
        books.unlink()
    sp = Spies(monkeypatch)
    with pytest.raises(SystemExit, match=r"INVALID \(stage-replaced\)"):
        t.gate(tmp_path, "opening books bound")
    sp.assert_zero()


def test_opening_books_preexisting_different_refuses_the_attestation(tmp_path):      # row 268 (before INTENT)
    start, cal, oc, w = _open_and_ack(tmp_path)
    (tmp_path / "s1_out" / "opening_books.json").write_text("{}", encoding="utf-8")
    with _Clock(w + timedelta(minutes=2)), pytest.raises(SystemExit, match="opening_books"):
        r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    assert stage_kinds(tmp_path, "start_attest") == []


VERIFY_REFUSAL = {"not-first-qualified": "first QUALIFIED",
                  "seal-differs": r"\['opening_seal_sha256'\] differ from the current artifacts",
                  "receipt-differs": r"\['opening_receipt_sha256'\] differ from the current artifacts",
                  "head-forked": r"journal head at seq \d+ differs \(fork\)",
                  "a-slot-not-terminal": r"F7\.2 \(b\)"}


@pytest.mark.parametrize("case", ["ok", "not-first-qualified", "seal-differs", "receipt-differs", "head-forked",
                                  "a-slot-not-terminal"])
def test_start_attest_verifies_the_opening_ack_against_the_journal(tmp_path, monkeypatch, case):   # row 151
    start, cal, oc, lg, rep = opened(tmp_path)
    over = {"not-first-qualified": {"opening_slot": j.slot_subject(opening_slot(cal, oc, 47))},
            "seal-differs": {"opening_seal_sha256": "0" * 64}, "receipt-differs": {"opening_receipt_sha256": "0" * 64},
            "head-forked": {"journal_head_sha256": "f" * 64}}.get(case, {})
    w = close_out(tmp_path, cal, oc) if case != "a-slot-not-terminal" else z.close_of(oc, cal) + timedelta(hours=1)
    s1_ack(tmp_path, "opening-ack", "S1-OPENING-ACK", w + timedelta(minutes=1), **over)
    if case == "a-slot-not-terminal":                               # rows 269: ACK prefix lacks terminal rows
        w = close_out(tmp_path, cal, oc)                            # (later rows do not repair the ACK's prefix)
    sp = Spies(monkeypatch)
    with _Clock(w + timedelta(minutes=2)):
        if case == "ok":
            r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
            assert stage_kinds(tmp_path, "start_attest")[-1:] == ["STAGE-CREATED"]
            return
        with pytest.raises(SystemExit, match=VERIFY_REFUSAL[case]):
            r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    sp.assert_zero()
    assert stage_kinds(tmp_path, "start_attest") == [] and not (tmp_path / "s1_out" / "attest_start.json").exists()


def test_start_attest_requires_every_opening_close_slot_terminal_in_the_ack_prefix(tmp_path):   # row 269
    start, cal, oc, lg, rep = opened(tmp_path)
    s1_ack(tmp_path, "opening-ack", "S1-OPENING-ACK", z.close_of(oc, cal) + timedelta(hours=1))
    w = close_out(tmp_path, cal, oc)
    with _Clock(w + timedelta(minutes=2)), pytest.raises(SystemExit, match=r"F7\.2.*\(b\)"):
        r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    assert stage_kinds(tmp_path, "start_attest") == []


def test_opening_slot_is_the_earliest_qualified_independent_of_issuance(tmp_path):    # row 270 (F3, OQ-37)
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    lg = Ledger(tmp_path / "opening_ledger.sqlite3")
    s45, s47 = opening_slot(cal, oc, 45), opening_slot(cal, oc, 47)
    s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT, minutes=45)
    w = close_out(tmp_path, cal, oc)
    s1_ack(tmp_path, "opening-ack", "S1-OPENING-ACK", w + timedelta(minutes=1),
           opening_slot=j.slot_subject(s47))                        # a later slot named: refused
    with _Clock(w + timedelta(minutes=2)), pytest.raises(SystemExit, match="first QUALIFIED"):
        r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    assert t.opening_issuance(tmp_path, mb(tmp_path))["opening_slot"] == j.slot_subject(s45)


@pytest.mark.parametrize("case", ["all-terminal-eligible", "early-failed-then-qualified-all-terminal",
                                  "later-slot-unfinalized-blocks", "pending-blocks",
                                  "missed-then-qualified-all-terminal"])
def test_opening_issuance_helper(tmp_path, case):                                       # row 152 (F7.2 b literal)
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    lg = Ledger(tmp_path / "opening_ledger.sqlite3")
    s45, s47 = opening_slot(cal, oc, 45), opening_slot(cal, oc, 47)
    day = next(d for d in cal if d["date"] == oc)
    if case == "early-failed-then-qualified-all-terminal":
        with _Clock(s45 - timedelta(seconds=5)):
            ck.run_opening_checkpoint(tmp_path, lg.path, s45, lambda reference=None: S1_RECEIPT,
                                      lambda: dict(S1_PROCESS), tmp_path / "c.log",
                                      now=lambda: s45 - timedelta(seconds=5))
        s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT, minutes=47)
        close_out(tmp_path, cal, oc)
    elif case == "pending-blocks":
        s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(s45), at=s45 + timedelta(seconds=1))
        s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT, minutes=47)
    elif case == "missed-then-qualified-all-terminal":
        s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT, minutes=47)
        e45 = z.eligible_until(s45, day, cal)
        gv = t.gate(tmp_path, "finalizer")
        with _Clock(e45):
            sl.finalize_close(gv, day, cal, lambda: e45, mailbox=mb(tmp_path))
            ck._opening_stage(t.gate(tmp_path, "opening"), tmp_path / "s1_out", day, cal, lambda: e45, mb(tmp_path))
        close_out(tmp_path, cal, oc)
    else:
        s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT, minutes=45)
        if case == "all-terminal-eligible":
            close_out(tmp_path, cal, oc)                            # later-slot-unfinalized: not closed out
    got = t.opening_issuance(tmp_path, mb(tmp_path))
    want = case not in ("pending-blocks", "later-slot-unfinalized-blocks")
    assert got["eligible"] == want, got
    if got["eligible"]:
        assert got["opening_slot"] == j.slot_subject(s45 if case == "all-terminal-eligible" else s47)


@pytest.mark.parametrize("case", ["ok", "wrong-hash", "wrong-membership-receipt", "wrong-membership-staging"])
def test_opening_ack_evidence_manifest_is_reconstructed(tmp_path, monkeypatch, case):  # rows 279, 280 (E5.5 r1)
    start, cal, oc, lg, rep = opened(tmp_path)
    w = close_out(tmp_path, cal, oc)
    rows_ = jrows(tmp_path)
    man = t.evidence_manifest(tmp_path, rows_, rows_[-1].seq)
    assert {"plan.json", "opening_receipt.json", "staging/audit/intent.json", "staging/audit/prepared.json",
            "staging/opening/intent.json", "staging/opening/prepared.json"} <= set(man["files"])   # E5.5 membership
    assert man["files"]["staging/opening/prepared.json"] == c.sha256_file(
        sg.staging_dir(tmp_path, t.open_trial(mb(tmp_path)).trial_id, "opening") / "prepared.json")
    if case == "wrong-membership-receipt":
        bad = dict(man, files={k_: v for k_, v in man["files"].items() if k_ != "opening_receipt.json"})
        value = c.sha256_bytes(c.canonical(bad))
    elif case == "wrong-membership-staging":                         # rev-0 membership (no staging files)
        bad = dict(man, files={k_: v for k_, v in man["files"].items() if not k_.startswith("staging/")})
        value = c.sha256_bytes(c.canonical(bad))
    else:
        value = c.sha256_bytes(c.canonical(man)) if case == "ok" else "a" * 64
    s1_ack(tmp_path, "opening-ack", "S1-OPENING-ACK", w + timedelta(minutes=1), evidence_manifest_sha256=value)
    sp = Spies(monkeypatch)
    with _Clock(w + timedelta(minutes=2)):                           # journal and files are otherwise valid
        if case == "ok":
            r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
            assert stage_kinds(tmp_path, "start_attest")[-1:] == ["STAGE-CREATED"]
            return
        with pytest.raises(SystemExit, match=r"evidence manifest.*INVALID \(registration-artifact\)"):
            r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    sp.assert_zero()
    assert stage_kinds(tmp_path, "start_attest") == []
    assert jrows(tmp_path)[-1].subject == "reason/registration-artifact"            # INVALIDATE, not REFUSE


def test_opening_window_later_slots_refused_then_missed(tmp_path):                   # row 333 (E5.6 r1)
    """E5.6: once the opening STAGE-INTENT exists, a later opening-close SLOT-INTENT is refused with no row by the
    opening gate; that slot ends MISSED at its E; the OPENING-ACK cannot be issued before the E of the last
    scheduled opening-close slot."""
    start, cal, oc, lg, rep = opened(tmp_path)                    # slot :45 QUALIFIED -> opening INTENT..CREATED
    assert stage_kinds(tmp_path, "opening")[:1] == ["STAGE-INTENT"]
    day = next(d for d in cal if d["date"] == oc)
    s47 = opening_slot(cal, oc, 47)
    at = s47 + timedelta(seconds=30)
    with _Clock(at), pytest.raises(SystemExit, match="opening is already decided"):
        ck.run_opening_checkpoint(tmp_path, lg.path, s47, lambda reference=None: S1_RECEIPT,
                                  lambda: dict(S1_PROCESS), tmp_path / "c.log", now=lambda: at)
    assert j.subject_rows(jrows(tmp_path), j.slot_subject(s47)) == []          # no row
    last = z.schedule(day, cal)[-1]
    e_last = z.eligible_until(last, day, cal)
    gv = t.gate(tmp_path, "before the last E")
    with _Clock(e_last - timedelta(microseconds=1)):
        sl.finalize_close(gv, day, cal, lambda: e_last - timedelta(microseconds=1), mailbox=mb(tmp_path))
    assert t.opening_issuance(tmp_path, mb(tmp_path))["eligible"] is False         # last slot not yet terminal
    close_out(tmp_path, cal, oc)
    assert [x.kind for x in j.subject_rows(jrows(tmp_path), j.slot_subject(s47))] == ["SLOT-MISSED"]
    assert t.opening_issuance(tmp_path, mb(tmp_path))["eligible"] is True


@pytest.mark.parametrize("case", ["ack-after-attest", "attest-at-start"])
def test_opening_ack_must_precede_the_attestation_and_the_attestation_start(tmp_path, case):   # row 316 (E5.3)
    start, cal, oc, lg, rep = opened(tmp_path)
    w = close_out(tmp_path, cal, oc)
    if case == "ack-after-attest":
        s1_ack(tmp_path, "opening-ack", "S1-OPENING-ACK", w + timedelta(minutes=5))
        at, why = w + timedelta(minutes=2), "ack is in the future"   # the attestation INTENT would precede the ACK
    else:
        s1_ack(tmp_path, "opening-ack", "S1-OPENING-ACK", w + timedelta(minutes=1))
        at, why = c.aware(START), "planned START has passed"
    with _Clock(at), pytest.raises(SystemExit, match=why):
        r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    assert stage_kinds(tmp_path, "start_attest") == []


def test_a_change_after_the_opening_ack_is_caught_by_the_live_file_check(tmp_path, monkeypatch):   # row 154
    start, cal, oc, w = _open_and_ack(tmp_path)
    rp = tmp_path / "s1_out" / "opening_receipt.json"
    rp.write_bytes(rp.read_bytes() + b" ")                       # the TEST changes its tmp opening receipt
    sp = Spies(monkeypatch)
    with _Clock(w + timedelta(minutes=2)), pytest.raises(SystemExit, match=r"INVALID \(stage-replaced\)"):
        r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    sp.assert_zero()


def test_missed_opening_ack_deadline_gives_no_start(tmp_path):                        # rows 155, 252
    start, cal, oc, lg, rep = opened(tmp_path)
    w = close_out(tmp_path, cal, oc)
    with _Clock(w + timedelta(minutes=2)), pytest.raises(SystemExit, match="OPENING-ACK"):
        r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    with _Clock(c.aware(START) - timedelta(hours=1)), pytest.raises(SystemExit, match="no START attestation"):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    assert stage_kinds(tmp_path, "start_attest") == [] and stage_kinds(tmp_path, "prereg") == []


PREREG_REFUSAL = {"old-format": "unattributable malformed official ACK", "wrong-prev": r"S1-RUN-ACK .*prev .* is not"}


@pytest.mark.parametrize("case", ["ok", "old-format", "wrong-prev"])
def test_prereg_requires_the_run_ack_with_trial_prev_and_journal_fields(tmp_path, case):   # row 156
    st_ = s1_state(tmp_path, START)                       # opening, OPENING-ACK, start_attest and RUN-ACK
    con_line = t.open_trial(mb(tmp_path)).acks["S1-RUN-ACK"].line
    if case != "ok":
        import sqlite3
        con = sqlite3.connect(mb(tmp_path))
        if case == "old-format":
            old = " ".join(["S1-RUN-ACK"] + [p for p in con_line.split(" ")[1:]
                                             if p.split("=")[0] not in ("trial_id", "prev", "journal_seq",
                                                                        "journal_head_sha256")])
            con.execute("UPDATE messages SET body=? WHERE id='run-ack'", (old,))    # the TEST edits its tmp mailbox
        else:
            tr = t.open_trial(mb(tmp_path))
            con.execute("UPDATE messages SET body=? WHERE id='run-ack'",
                        (con_line.replace(f"prev={tr.acks['S1-OPENING-ACK'].mailbox_id}",
                                          f"prev={tr.audit.mailbox_id}"),))
        con.commit()
        con.close()
    with _Clock(st_["prereg_at"]):
        if case == "ok":
            r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
            assert stage_kinds(tmp_path, "prereg")[-1:] == ["STAGE-CREATED"]
            return
        with pytest.raises(SystemExit, match=PREREG_REFUSAL[case]):
            r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)


def test_prereg_envelope_and_member(tmp_path):                                         # row 105
    st_ = s1_state(tmp_path, START)
    with _Clock(st_["prereg_at"]):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    e, cm = env(tmp_path, "prereg"), com(tmp_path, "prereg")
    assert set(e["inputs"]) == {"attest_start.json", "receipt"} and e["inputs"]["receipt"] == c.receipt_sha256(
        S1_RECEIPT)
    assert e["acks"] == {"S1-RUN-ACK": t.open_trial(mb(tmp_path)).acks["S1-RUN-ACK"].sha}
    assert list(cm["members"]) == ["prereg.json"] and cm["kind"] == "single"


SPLIT = {"id": "ca-split-1", "type": "forward_splits", "symbol": "CI", "ex_date": "2026-10-05",
         "effective_date": "2026-10-05", "classification": "complete"}


def test_blocked_prereg_is_a_pre_intent_refusal_record(tmp_path, monkeypatch):     # rows 121, 271, 326 (E3)
    """E3 (accepted in the adopted Erratum 1, de008b1): BLOCKED is a pre-INTENT refusal record - blocked.json, no
    journal row, ACTIVE, never INVALID - with zero captures, provider requests and valuation calls."""
    st_ = s1_state(tmp_path, START, audit_actions=[SPLIT])
    n_rows = len(jrows(tmp_path))
    sp = Spies(monkeypatch)
    with _Clock(st_["prereg_at"]), pytest.raises(SystemExit, match=r"S1 BLOCKED \(pre-START units\)"):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    sp.assert_zero()
    blocked = json.loads((tmp_path / "s1_out" / "blocked.json").read_text(encoding="utf-8"))
    assert blocked["status"] == "BLOCKED" and blocked.get("trial_id") == t.open_trial(mb(tmp_path)).trial_id   # E5.4
    assert len(jrows(tmp_path)) == n_rows and stage_kinds(tmp_path, "prereg") == []
    assert j.trial_state(jrows(tmp_path)) == "ACTIVE"
    t.gate(tmp_path, "blocked.json is a declared pre-INTENT record, not a stage member")


def test_blocked_rerun_after_deletion_recomputes_identically(tmp_path):              # rows 272, 327 (E3.2)
    st_ = s1_state(tmp_path, START, audit_actions=[SPLIT])
    out = tmp_path / "s1_out"
    with _Clock(st_["prereg_at"]), pytest.raises(SystemExit, match="S1 BLOCKED") as first:
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    rec1 = r.blocked_reasons_record(out, c.load_json(out / "audit" / "calendar.json"))
    (out / "blocked.json").unlink()
    with _Clock(st_["prereg_at"] + timedelta(minutes=1)), pytest.raises(SystemExit, match="S1 BLOCKED") as second:
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    rec2 = r.blocked_reasons_record(out, c.load_json(out / "audit" / "calendar.json"))
    assert str(first.value) == str(second.value) and rec1 == rec2
    assert json.loads((out / "blocked.json").read_bytes())["reasons"] == rec2["reasons"]
    assert stage_kinds(tmp_path, "prereg") == [] and j.trial_state(jrows(tmp_path)) == "ACTIVE"


def _blocked_and_closed(tmp_path, st_):
    with _Clock(st_["prereg_at"]), pytest.raises(SystemExit, match="S1 BLOCKED"):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    h = r.blocked_close_evidence(tmp_path / "s1_out")             # what Codex issues after its own check
    s1_ack(tmp_path, "close", "S1-CLOSE-ACK", st_["prereg_at"] + timedelta(minutes=5), reason="BLOCKED",
           evidence_sha256=h)
    return h


def test_blocked_close_evidence_helper_end_to_end(tmp_path):                          # row 273 (E3.4 r3)
    """The h Codex issues is sha256(canonical({trial_id, reasons})) of this trial's own recomputation, not the file
    bytes; with a valid CLOSE the trial is closed (S1 does not re-derive h when reading the CLOSE)."""
    st_ = s1_state(tmp_path, START, audit_actions=[SPLIT])
    _blocked_and_closed(tmp_path, st_)
    out = tmp_path / "s1_out"
    rec = r.blocked_reasons_record(out, c.load_json(out / "audit" / "calendar.json"))
    assert r.blocked_close_evidence(out) == c.sha256_bytes(c.canonical({"trial_id": rec["trial_id"],
                                                                         "reasons": rec["reasons"]}))
    assert rec["reasons"] and rec["trial_id"]                        # (A3 Task 10: a real recomputation)
    assert r.blocked_close_evidence(out) != c.sha256_file(out / "blocked.json")      # not the file bytes
    with pytest.raises(SystemExit, match="zero open"):
        t.gate(tmp_path, "closed BLOCKED")


@pytest.mark.parametrize("case", ["deleted", "deleted-and-recreated"])
def test_blocked_close_survives_delete_and_recreate(tmp_path, case):                   # row 332 (E3.4 r3)
    """Closure is unaffected by any local file state: S1 never reads blocked.json to decide closure."""
    st_ = s1_state(tmp_path, START, audit_actions=[SPLIT])
    h = _blocked_and_closed(tmp_path, st_)
    out = tmp_path / "s1_out"
    blk = json.loads((out / "blocked.json").read_bytes())             # (A3 Task 10: h is the recomputation, E3.4)
    assert h == c.sha256_bytes(c.canonical({"trial_id": blk.get("trial_id"), "reasons": blk["reasons"]}))
    (out / "blocked.json").unlink()
    if case == "deleted-and-recreated":                              # new recorded_utc => different file bytes
        rec = r.blocked_reasons_record(out, c.load_json(out / "audit" / "calendar.json"))
        (out / "blocked.json").write_text(json.dumps(dict(rec, status="BLOCKED",
                                                          recorded_utc="2026-12-01T00:00:00+00:00")),
                                          encoding="utf-8")
    assert r.blocked_close_evidence(out) == h                       # h unchanged (the recomputation)
    tr = t.trials(t.scan(mb(tmp_path)))
    assert all(x.closed is not None for x in tr.values())            # the closed trial never re-opens
    with pytest.raises(SystemExit, match="zero open"):
        t.gate(tmp_path, "still closed")


def test_non_blocked_prereg_is_unaffected(tmp_path):                                  # rows 274, 329 (ctrl)
    st_ = s1_state(tmp_path, START)
    with _Clock(st_["prereg_at"]):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    assert stage_kinds(tmp_path, "prereg")[-1:] == ["STAGE-CREATED"]
    assert not (tmp_path / "s1_out" / "blocked.json").exists()


# ---------------------------------------------------------------- A3 Task 10 carry-forwards (controller rulings)
def test_a_second_opening_seal_is_caught_beyond_the_opening_gate(tmp_path):            # Task 6 M6
    """Task 6 M6: with the opening stage CREATED, the required seals (s1_slot.required_seals, so
    s1_common._report_seals) carry the opening entry, so the R-3 guard _before_opening_seal refuses a second,
    different opening seal; the opening stage is never re-entered (F1) and a later opening stage call is 'already
    decided'; a replaced opening seal is INVALID (stage-replaced) at the gate and a legacy registration problem."""
    start, cal, oc, lg, rep = opened(tmp_path)
    out = tmp_path / "s1_out"
    rel, seal = f"seals/{oc}.json", out / "seals" / f"{oc}.json"
    h, rows_ = c.sha256_file(seal), jrows(tmp_path)
    assert sl.required_seals(out, rows_).get(rel) == h
    assert (rel, seal, h) in c._report_seals(out, rows_)
    with pytest.raises(SystemExit, match="a second, different opening seal"):
        ck._before_opening_seal(out, oc, "0" * 64, c.aware(START), rows_)
    ck._before_opening_seal(out, oc, h, c.aware(START), rows_)       # the same seal: no conflict
    # A3 H1 (Erratum 2 r4 G6.4; setup order only): the guard's own local abort (above) is removed BEFORE the next
    # trial gate - left in place, that gate now records it as the surviving local abort (G6.4, rows 460/466) and the
    # stage-table checks below would never run (moved up from just before the seal replacement)
    (out / "aborted.json").unlink()
    day = next(d for d in cal if d["date"] == oc)
    gv = t.gate(tmp_path, "second opening seal")
    assert ck._opening_stage(gv, out, day, cal, lambda: c.aware(START), mb(tmp_path)) == {"opening": "already decided"}
    with pytest.raises(SystemExit, match=r"stage opening is already CREATED: re-entry refused \(F1\)"):
        sg.run(gv, "opening", inputs={}, acks={}, work=lambda sw: [], mailbox=mb(tmp_path))
    assert not (out / "aborted.json").exists()                       # (the guard's own local abort, removed above)
    seal.write_bytes(seal.read_bytes() + b" ")                       # the TEST replaces its tmp opening seal
    assert any(f"{rel} missing or changed (a CREATED seal stage's committed member" in p
               for p in c.registration_problems(out, mb(tmp_path)))
    with pytest.raises(SystemExit, match=r"stage opening: .*INVALID \(stage-replaced\)"):
        t.gate(tmp_path, "replaced opening seal")


def _files_under(p: Path) -> set:
    return {x.relative_to(p).as_posix() for x in p.rglob("*") if x.is_file()} if p.is_dir() else set()


def test_the_opening_close_finalizer_never_writes_into_a_live_or_no_row_slot(tmp_path):   # Task 7 concern 7
    """Task 7 concern 7 / E1.4: the opening close runs on s1_slot.finalize_close (journal rows only): with slot 45
    in flight (its INTENT and its own claim), slot 47's opening checkpoint and the finalizer at D45 write no file into
    slot 45 or into any slot with no row (no RESOLUTION-TIMEOUT / MISSED record); the TIMEOUT and MISSED are rows."""
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    lg = Ledger(tmp_path / "opening_ledger.sqlite3")
    day = next(d for d in cal if d["date"] == oc)
    s45, s47 = opening_slot(cal, oc, 45), opening_slot(cal, oc, 47)
    out = tmp_path / "s1_out"
    row = s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(s45), at=s45 + timedelta(seconds=1))
    n45 = sl.names(out, s45, oc)
    n45["claim"].parent.mkdir(parents=True, exist_ok=True)
    n45["claim"].write_text(json.dumps({"op": row.op, "actor": row.actor,
                                        "capture_dir": n45["capture"].relative_to(out).as_posix()}), encoding="utf-8")
    s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT, minutes=47)
    caps = out / "captures" / oc
    stem45, stem47 = f"{s45:%Y%m%dT%H%M%SZ}", f"{s47:%Y%m%dT%H%M%SZ}"
    assert {p.split("/")[0].split(".")[0] for p in _files_under(caps)} == {stem45, stem47}
    assert {p for p in _files_under(caps) if p.startswith(stem45)} == {f"{stem45}.attempt.json"}   # untouched
    d45 = z.resolution_deadline(s45, day, cal)
    with _Clock(d45):
        ck.finalize_opening(tmp_path, now=lambda: d45, mailbox=mb(tmp_path))      # H3 (C4): the clock-callable helper
    assert [x.kind for x in j.subject_rows(jrows(tmp_path), j.slot_subject(s45))] == ["SLOT-INTENT", "SLOT-TIMEOUT"]
    assert not any(p.endswith(".resolution.json") and not p.startswith(stem47) for p in _files_under(caps))
    missed = [x.subject for x in jrows(tmp_path) if x.kind == "SLOT-MISSED"]
    assert missed and all(not list(caps.glob(f"{s[len('slot/'):]}*")) for s in missed)


@pytest.mark.parametrize("via", ["finalizer-command", "later-worker"])
def test_a_crashed_opening_worker_times_out_at_d_and_the_opening_is_sealed(tmp_path, via):   # Task 7 concern 7
    """Task 7 concern 7 (sealing liveness on the opening close): slot 45's worker crashed after its SLOT-INTENT;
    slot 47 QUALIFIED leaves the opening undecided (slot 45 in flight). At D45 the journal finalizer - the finalizer
    command on the opening close, or a later opening slot's own checkpoint - appends SLOT-TIMEOUT for slot 45, and the
    close is determined: the opening stage is CREATED from slot 47. No INVALID."""
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    lg = Ledger(tmp_path / "opening_ledger.sqlite3")
    day = next(d for d in cal if d["date"] == oc)
    s45, s47 = opening_slot(cal, oc, 45), opening_slot(cal, oc, 47)
    s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(s45), at=s45 + timedelta(seconds=1))   # the crashed worker
    s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT, minutes=47)
    assert stage_kinds(tmp_path, "opening") == []                   # undecided: slot 45 is in flight
    d45 = z.resolution_deadline(s45, day, cal)
    if via == "finalizer-command":
        with _Clock(d45):
            got = ck.finalize_opening(tmp_path, now=lambda: d45, mailbox=mb(tmp_path))   # H3 (C4)
    else:
        later = next(s for s in z.schedule(day, cal) if s >= d45)
        minutes = int((later - z.close_of(oc, cal)).total_seconds() // 60)
        got = s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT, minutes=minutes)
    assert [x.kind for x in j.subject_rows(jrows(tmp_path), j.slot_subject(s45))] == ["SLOT-INTENT", "SLOT-TIMEOUT"]
    assert stage_kinds(tmp_path, "opening") == ["STAGE-INTENT", "STAGE-PREPARED", "STAGE-CREATED"]
    seal = json.loads((tmp_path / "s1_out" / "seals" / f"{oc}.json").read_bytes())
    assert seal["capture"]["scheduled"] == s47.isoformat(), got
    assert all(x.kind != "TRIAL-INVALID" for x in jrows(tmp_path))


def test_a_held_stage_lock_never_delays_the_opening_finalizers_deadline_rows(tmp_path):   # N2 (Erratum 1 E1.2)
    """Ruling N2 on the opening close: while a stalled owner holds an unrelated stage lock after its INTENT (a plain
    gate is "pending"), slot 47's opening checkpoint still commits, and at D45 the finalizer command on the opening
    close (a deadline path: evaluate(defer_pending=True)) appends slot 45's SLOT-TIMEOUT and the opening stage is
    CREATED. The held lock stays held; no INVALID."""
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    lg = Ledger(tmp_path / "opening_ledger.sqlite3")
    day = next(d for d in cal if d["date"] == oc)
    s45 = opening_slot(cal, oc, 45)
    s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(s45), at=s45 + timedelta(seconds=1))
    stage = "seal/2026-10-27"                                       # an unrelated stage, held after its INTENT
    p = subprocess.Popen([sys.executable, "-I", str(HELPERS), str(tmp_path), stage, "hold-after-intent",
                          (s45 - timedelta(minutes=5)).isoformat()],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline().strip() == "held", p.stderr.read()
        with _Clock(s45), pytest.raises(SystemExit, match="pending"):
            t.gate(tmp_path, "a plain gate")
        try:
            s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT, minutes=47)
            d45 = z.resolution_deadline(s45, day, cal)
            with _Clock(d45):
                ck.finalize_opening(tmp_path, now=lambda: d45, mailbox=mb(tmp_path))   # H3 (C4)
        except SystemExit as e:
            pytest.fail(f"a deadline path was refused while an unrelated stage lock is held: {e}")
        assert [x.kind for x in j.subject_rows(jrows(tmp_path), j.slot_subject(s45))] == ["SLOT-INTENT",
                                                                                         "SLOT-TIMEOUT"]
        assert stage_kinds(tmp_path, "opening")[-1:] == ["STAGE-CREATED"]
        assert not L.lock_acquirable(tmp_path, t.open_trial(mb(tmp_path)).trial_id, L.stage_lock_name(stage))
        assert all(x.kind != "TRIAL-INVALID" for x in jrows(tmp_path))
    finally:
        p.stdin.write("\n")
        p.stdin.flush()
        p.communicate(timeout=60)


def test_the_gate_hook_order_plan_check_evaluate_evidence_check_then_the_manifest_check(tmp_path, monkeypatch):
    """Carry-forward 7: the new gate hook opening_manifest_check runs after s1_slot.evidence_check, both after the
    stage table (and so after the plan check: a plan-check refusal reaches none of them - the foreign-root test)."""
    start, cal, oc, w = _open_and_ack(tmp_path)
    calls = []
    for mod, name in ((sg, "evaluate"), (sl, "evidence_check"), (t, "opening_manifest_check")):
        real = getattr(mod, name)
        monkeypatch.setattr(mod, name, lambda *a, _r=real, _n=name, **k: calls.append(_n) or _r(*a, **k))
    t.gate(tmp_path, "hook order")
    assert calls == ["evaluate", "evidence_check", "opening_manifest_check"]


def test_a_foreign_root_cannot_invalidate_the_open_trial_through_the_manifest_hook(tmp_path, monkeypatch):
    """Carry-forward 7: a gate on a foreign root (another plan's trial_id, nothing else) against this trial's
    mailbox is refused by the plan check, so opening_manifest_check (which would see no evidence manifest there)
    never runs on it and appends no TRIAL-INVALID for the open trial; the trial's own gate still passes."""
    start, cal, oc, w = _open_and_ack(tmp_path)
    foreign = tmp_path / "foreign"
    (foreign / "s1_out").mkdir(parents=True)
    plan = json.loads((tmp_path / "s1_out" / "plan.json").read_bytes())
    (foreign / "s1_out" / "plan.json").write_text(json.dumps(dict(plan, trial_id="00000000-0000-4000-8000-"
                                                                                 "000000000000")), encoding="utf-8")
    seen = []
    real = t.opening_manifest_check
    monkeypatch.setattr(t, "opening_manifest_check", lambda gv, a=None: seen.append(gv.root) or real(gv, a))
    n = len(jrows(tmp_path))
    with pytest.raises(SystemExit, match="plan.json trial_id"):
        t.gate(foreign, "foreign root", mailbox=mb(tmp_path))
    assert seen == [] and len(jrows(tmp_path)) == n
    t.gate(tmp_path, "own root")
    assert seen == [tmp_path]


def test_the_evidence_manifest_is_the_exact_e55_format(tmp_path):                     # E5.5 r1/r2/r4
    """E5.5: exactly {trial_id, journal_seq, journal_head_sha256, files}; files keyed by s1_out relpaths and by
    `staging/<stage>/<name>` labels of the real files <root>/s1_staging/<trial_id>/<stage>/<name> (outside s1_out:
    no s1_out/staging exists); every hash is of the live bytes; the QUALIFIED tree and every CREATED member are in;
    the sha256 the OPENING-ACK carries is sha256(c.canonical(manifest)) (sorted keys)."""
    start, cal, oc, w = _open_and_ack(tmp_path)
    out, tr = tmp_path / "s1_out", t.open_trial(mb(tmp_path))
    a = tr.acks["S1-OPENING-ACK"]
    rows_ = jrows(tmp_path)
    seq = int(a.fields["journal_seq"])
    man = t.evidence_manifest(tmp_path, rows_, seq)
    assert list(man) == ["trial_id", "journal_seq", "journal_head_sha256", "files"]
    assert (man["trial_id"], man["journal_seq"], man["journal_head_sha256"]) == (tr.trial_id, seq, rows_[seq - 1].sha)
    assert c.sha256_bytes(c.canonical(man)) == a.fields["evidence_manifest_sha256"]
    assert not (out / "staging").exists()
    for k_, v in man["files"].items():
        p = (tmp_path / "s1_staging" / tr.trial_id / k_[len("staging/"):]) if k_.startswith("staging/") else out / k_
        assert p.is_file() and c.sha256_file(p) == v, k_
    tree = sl.qualified_tree(out, opening_slot(cal, oc, 45), oc)
    assert set(tree) <= set(man["files"]) and f"seals/{oc}.json" in man["files"]
    assert set(sg.FIXED_TREE["audit"]) <= set(man["files"])
    assert not any(k_.startswith("staging/start_attest") for k_ in man["files"])   # (rows after journal_seq: none)


# ---------------------------------------------------------------- A3 Task 10 fix round 1 (review I1, M1-M5)
def _crash_after_prepared(monkeypatch, stage):
    """A crash right after the stage's STAGE-PREPARED row commits (before publication): the row-180 crash point."""
    real, crashed = j.append, []

    def crashing(trial_id, gen, req, ctx_fn, **kw):
        res = real(trial_id, gen, req, ctx_fn, **kw)
        if req.kind == "STAGE-PREPARED" and req.subject == j.stage_subject(stage):
            crashed.append(stage)
            raise KeyboardInterrupt
        return res
    monkeypatch.setattr(j, "append", crashing)
    return real, crashed


LEGACY_RECORDS = {"opening": "opening", "start_attest": "attest_start", "prereg": "prereg"}


@pytest.mark.parametrize("stage", ["opening", "start_attest", "prereg"])
def test_a_recovered_pre_start_stage_never_invalidates_the_next_command(tmp_path, monkeypatch, stage):
    """Review I1 (ruling: fixed in Task 10): a crash right after STAGE-PREPARED of `opening` / `start_attest` /
    `prereg`; the next gate recovers the stage to CREATED (F4.7); the recovery publishes the legacy registry and
    witness records through the same before_publish path as the stage run, so the NEXT REAL command (the START
    attestation / prereg / a post-START checkpoint) passes the legacy registration detector: no TRIAL-INVALID, no
    aborted.json."""
    out = tmp_path / "s1_out"
    if stage == "opening":
        start, cal, oc, _ = s1_plan_audit(tmp_path, START)
        lg = Ledger(tmp_path / "opening_ledger.sqlite3")
        real, crashed = _crash_after_prepared(monkeypatch, stage)
        try:
            s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT)
        except KeyboardInterrupt:
            pass
        at = opening_slot(cal, oc, 45) + timedelta(minutes=1)
    else:
        st_ = s1_state(tmp_path, START, attest=(stage == "prereg"))
        at = st_["attest_at" if stage == "start_attest" else "prereg_at"]
        real, crashed = _crash_after_prepared(monkeypatch, stage)
        try:
            with _Clock(at):
                if stage == "start_attest":
                    r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
                else:
                    r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
        except KeyboardInterrupt:
            pass
        at += timedelta(seconds=30)
    monkeypatch.setattr(j, "append", real)
    assert crashed == [stage] and stage_kinds(tmp_path, stage) == ["STAGE-INTENT", "STAGE-PREPARED"]
    with _Clock(at):
        t.gate(tmp_path, "the F4.7 recovery")
    assert stage_kinds(tmp_path, stage) == ["STAGE-INTENT", "STAGE-PREPARED", "STAGE-CREATED"]
    box = {}
    if stage == "opening":                                              # next: close-out, ACK, START attestation
        w = close_out(tmp_path, cal, oc)
        s1_ack(tmp_path, "opening-ack", "S1-OPENING-ACK", w + timedelta(minutes=1))
        with _Clock(w + timedelta(minutes=2)):
            got = _outcome(lambda: r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT))
        nxt = "start_attest"
    elif stage == "start_attest":                                       # next: the RUN-ACK, then prereg
        s1_ack(tmp_path, "run-ack", "S1-RUN-ACK", at + timedelta(minutes=1))
        with _Clock(at + timedelta(minutes=2)):
            got = _outcome(lambda: r.do_prereg(tmp_path, "run-ack", S1_RECEIPT))
        nxt = "prereg"
    else:                                                               # next: the PREREG-ACK, a post-START slot
        s1_ack(tmp_path, "prereg-ack", "S1-PREREG-ACK", at + timedelta(minutes=1))
        cal = st_["calendar"]
        sch = z.close_of("2026-10-26", cal) + timedelta(minutes=45)
        with _Clock(sch + timedelta(seconds=30)):
            got = _outcome(lambda: box.update(rep=ck.run_checkpoint(
                tmp_path, st_["ledger"].path, sch, lambda reference=None: S1_RECEIPT, lambda: dict(S1_PROCESS),
                tmp_path / "c.log", now=lambda: sch + timedelta(seconds=30))))
        nxt = None
    assert got is None, repr(got)                                       # the next real command is not refused
    assert [x.subject for x in jrows(tmp_path) if x.kind == "TRIAL-INVALID"] == []
    assert c.load_abort(out) is None
    assert all(p.is_file() for p in c.stage_records(out, LEGACY_RECORDS[stage]))      # (written by the recovery)
    if nxt is not None:
        assert stage_kinds(tmp_path, nxt)[-1:] == ["STAGE-CREATED"]
    else:
        assert box["rep"]["journal"]["kind"] == "SLOT-QUALIFIED" and box["rep"]["journal"]["outcome"] == "APPEND"


def test_the_evidence_manifest_membership_is_exactly_e55_with_failed_and_qualified_trees(tmp_path):
    """Review M1: E5.5 membership pinned by a literal set (an earlier FAILED opening slot, then a QUALIFIED one), and
    the OPENING-ACK's evidence_manifest_sha256 / the issuance value equal a hash built independently here from the
    live files (not from s1_trial.evidence_manifest)."""
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    lg = Ledger(tmp_path / "opening_ledger.sqlite3")
    s45 = opening_slot(cal, oc, 45)
    with _Clock(s45 - timedelta(seconds=5)):                       # A5.2: t < s - the :45 slot is FAILED
        ck.run_opening_checkpoint(tmp_path, lg.path, s45, lambda reference=None: S1_RECEIPT,
                                  lambda: dict(S1_PROCESS), tmp_path / "c.log", now=lambda: s45 - timedelta(seconds=5))
    s1_opening_checkpoint(tmp_path, lg, oc, cal, S1_RECEIPT, minutes=47)
    w = close_out(tmp_path, cal, oc)
    s1_ack(tmp_path, "opening-ack", "S1-OPENING-ACK", w + timedelta(minutes=1))
    out, tr = tmp_path / "s1_out", t.open_trial(mb(tmp_path))
    a, rows_ = tr.acks["S1-OPENING-ACK"], jrows(tmp_path)
    seq = int(a.fields["journal_seq"])
    cap = "captures/2026-10-23/"
    expected = {"plan.json", "opening_receipt.json",
                "audit/attempt.json", "audit/calendar_source.json", "audit/calendar.json",
                "audit/corporate_actions.json", "audit/ca_problems.json", "audit/manifest.json",
                "audit/pages/calendar.json",
                cap + "20261023T204500Z.attempt.json", cap + "20261023T204500Z.report.json",          # FAILED tree
                cap + "20261023T204700Z.report.json", cap + "20261023T204700Z.resolution.json",       # QUALIFIED
                cap + "20261023T204700Z/backup.sqlite3", cap + "20261023T204700Z/meta.json",
                cap + "20261023T204700Z/projection.json",
                "seals/2026-10-23.json",
                "staging/audit/intent.json", "staging/audit/prepared.json",
                "staging/opening/intent.json", "staging/opening/prepared.json"}
    man = t.evidence_manifest(tmp_path, rows_, seq)
    assert set(man["files"]) == expected
    staging = tmp_path / "s1_staging" / tr.trial_id
    files = {k_: c.sha256_file(staging / k_[len("staging/"):] if k_.startswith("staging/") else out / k_)
             for k_ in expected}
    doc = {"trial_id": tr.trial_id, "journal_seq": seq, "journal_head_sha256": rows_[seq - 1].sha, "files": files}
    want = c.sha256_bytes(c.canonical(doc))
    assert a.fields["evidence_manifest_sha256"] == want
    assert t.opening_issuance(tmp_path, mb(tmp_path))["evidence_manifest_sha256"] == want


MANIFEST_READ = {"sharing-violation": PermissionError(13, "The process cannot access the file because it is being "
                                                          "used by another process"),
                 "io-error": OSError(5, "Input/output error"),
                 "gone": FileNotFoundError(2, "No such file or directory")}


@pytest.mark.parametrize("err", sorted(MANIFEST_READ))
def test_only_definite_absence_or_corruption_makes_the_manifest_check_invalidate(tmp_path, monkeypatch, err):
    """Review M2 (F0.7, F5.5 / ERROR_ACCESS_DENIED rule): a transient read error while reconstructing the E5.5 manifest
    refuses fail-closed with no row; only a member definitely gone (or unparseable) is INVALIDATE
    (registration-artifact)."""
    start, cal, oc, w = _open_and_ack(tmp_path)

    def failing(*a, **k):
        raise MANIFEST_READ[err]
    monkeypatch.setattr(t, "evidence_manifest", failing)
    n = len(jrows(tmp_path))
    if err == "gone":
        with pytest.raises(SystemExit, match=r"evidence manifest.*INVALID \(registration-artifact\)"):
            t.gate(tmp_path, "manifest member gone")
        assert jrows(tmp_path)[-1].subject == "reason/registration-artifact"
        return
    with pytest.raises(SystemExit, match=r"E5\.5 evidence manifest check: .*refused with no row"):
        t.gate(tmp_path, "manifest member transiently unreadable")
    assert len(jrows(tmp_path)) == n and all(x.kind != "TRIAL-INVALID" for x in jrows(tmp_path))


@pytest.mark.parametrize("err", ["journal-outage", "os-error"])
def test_the_finalizer_command_turns_an_opening_stage_error_into_a_refusal(tmp_path, monkeypatch, err):
    """Review M3 (F0.7): an unexpected error from the opening stage step of the finalizer command is a refusal with
    no row, never an escaping exception."""
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    day = next(d for d in cal if d["date"] == oc)
    exc = j.Outage("mailbox unreadable (OperationalError)") if err == "journal-outage" else OSError(5, "I/O error")

    def failing(*a, **k):
        raise exc
    monkeypatch.setattr(ck, "_opening_stage", failing)
    e45 = z.eligible_until(opening_slot(cal, oc, 45), day, cal)
    try:
        with _Clock(e45):
            ck.finalize_opening(tmp_path, now=lambda: e45, mailbox=mb(tmp_path))   # H3 (C4)
        got = None
    except BaseException as e:                                       # noqa: BLE001 - the outcome under test
        got = e
    assert isinstance(got, SystemExit) and "refused with no row" in str(got) and "F0.7" in str(got), repr(got)


def test_the_opening_registration_reads_the_journal_through_the_given_mailbox(tmp_path, monkeypatch):
    """Review M4: the opening stage's before_publish (the R-3 / M6 second-seal guard) reads the trial's rows through
    the mailbox the command was given, never the default coordination mailbox."""
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    lg = Ledger(tmp_path / "opening_ledger.sqlite3")
    monkeypatch.setattr(c, "MAILBOX", tmp_path / "absent" / "mailbox.sqlite3")
    s45 = opening_slot(cal, oc, 45)
    at = s45 + timedelta(seconds=30)
    with _Clock(at):
        rep = ck.run_opening_checkpoint(tmp_path, lg.path, s45, lambda reference=None: S1_RECEIPT,
                                        lambda: dict(S1_PROCESS), tmp_path / "c.log", now=lambda: at,
                                        mailbox=mb(tmp_path))
    assert rep.get("seal", {}).get("written") is True, rep
    assert stage_kinds(tmp_path, "opening") == ["STAGE-INTENT", "STAGE-PREPARED", "STAGE-CREATED"]
    assert not (tmp_path / "absent").exists()


def _outcome(fn):
    try:
        fn()
    except BaseException as e:                                       # noqa: BLE001 - the outcome under test
        return e
    return None


@pytest.mark.parametrize("write", ["opening_receipt", "opening_books", "blocked"])
def test_a_pre_intent_write_never_recreates_a_vanished_s1_out(tmp_path, monkeypatch, write):
    """Review M5 (F6.6): s1_out disappears after the gate and before a pre-INTENT write (opening_receipt.json in the
    opening stage, opening_books.json before the start_attest INTENT, blocked.json before the prereg INTENT): the
    write refuses with no row and s1_out is not recreated (its absence is the total-loss evidence)."""
    import shutil
    out = tmp_path / "s1_out"

    def vanish_after(mod, name):
        real = getattr(mod, name)

        def f(*a, **k):
            res = real(*a, **k)
            shutil.rmtree(out)
            return res
        monkeypatch.setattr(mod, name, f)
    if write == "opening_receipt":
        start, cal, oc, _ = s1_plan_audit(tmp_path, START)
        vanish_after(sl, "_resolution_evidence")
        got = _outcome(lambda: s1_opening_checkpoint(tmp_path, Ledger(tmp_path / "opening_ledger.sqlite3"), oc, cal,
                                                     S1_RECEIPT))
    elif write == "opening_books":
        start, cal, oc, w = _open_and_ack(tmp_path)
        vanish_after(r, "_books_record")
        with _Clock(w + timedelta(minutes=2)):
            got = _outcome(lambda: r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT))
    else:
        st_ = s1_state(tmp_path, START, audit_actions=[SPLIT])
        vanish_after(r, "blocked_reasons_record")
        with _Clock(st_["prereg_at"]):
            got = _outcome(lambda: r.do_prereg(tmp_path, "run-ack", S1_RECEIPT))
    assert isinstance(got, SystemExit) and re.search(r"s1_out is gone.*refused with no row \(F6\.6\)", str(got)), \
        repr(got)
    assert not out.exists()


# ---------------------------------------------------------------- Clarification 1 C4: the opening-finalizer helper
# (direct call only, O-C4: these tests establish preserved callable behaviour, not operational reachability)
class _Adv:
    def __init__(self, t0):
        self.t = t0

    def __call__(self):
        self.t = self.t + timedelta(milliseconds=3)
        return self.t


def crashed_opening(tmp_path, *, qualify=True):
    """Slot 45's worker crashed after its SLOT-INTENT; with `qualify`, slot 47's opening checkpoint QUALIFIED."""
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    day = next(d for d in cal if d["date"] == oc)
    s45, s47 = opening_slot(cal, oc, 45), opening_slot(cal, oc, 47)
    s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(s45), at=s45 + timedelta(seconds=1))
    if qualify:
        s1_opening_checkpoint(tmp_path, Ledger(tmp_path / "opening_ledger.sqlite3"), oc, cal, S1_RECEIPT, minutes=47)
    return {"cal": cal, "oc": oc, "day": day, "s45": s45, "s47": s47,
            "d45": z.resolution_deadline(s45, day, cal)}


def test_opening_finalizer_helper_same_clock_callable(tmp_path, monkeypatch):            # row 491 (CL-A12)
    o = crashed_opening(tmp_path)
    clk = _Adv(o["d45"])
    seen = []
    real_gate, real_append, real_stage = t.gate, j.append, ck._opening_stage
    monkeypatch.setattr(t, "gate", lambda *a, **kw: seen.append(("gate", kw.get("now"))) or real_gate(*a, **kw))
    monkeypatch.setattr(j, "append", lambda *a, **kw: seen.append(("append", kw.get("clock"))) or real_append(*a, **kw))
    monkeypatch.setattr(ck, "_opening_stage", lambda gv, out, day, cal, now, mb_: seen.append(("stage", now))
                        or real_stage(gv, out, day, cal, now, mb_))
    ck.finalize_opening(tmp_path, now=clk, mailbox=mb(tmp_path))
    assert {n for n, _ in seen} >= {"gate", "append", "stage"}
    assert all(x is clk for n, x in seen if n in ("gate", "stage"))            # by identity, no wrapper
    assert all(x is clk for n, x in seen if n == "append" and x is not None)  # every journal transaction
    ats = [c.aware(x.at) for x in jrows(tmp_path) if x.kind in ("SLOT-TIMEOUT", "STAGE-INTENT", "STAGE-CREATED")]
    assert len(ats) >= 3 and ats == sorted(ats) and len(set(ats)) == len(ats)   # an advancing clock observed


@pytest.mark.parametrize("case", ["local-abort", "invalid", "closed", "no-open-trial", "integrity-violation"])
def test_opening_finalizer_helper_precedence(tmp_path, monkeypatch, case):              # row 492 (CL-A13)
    """C4.2/C4.3: every refusal precedes any finalizer work. local-abort: (a) a witness present before the command is
    recorded and refused by H1's gate (G6.4); (b) a witness appearing after the gate is refused by the helper's own
    _no_local_abort (F8.1) - zero finalizer work in both (H3 deviation: sub-case (b) added, as row 425)."""
    subs = ("before", "after-gate") if case == "local-abort" else ("",)
    for sub in subs:
        root = tmp_path / sub if sub else tmp_path
        if sub:
            root.mkdir()
            monkeypatch.setattr(c, "MAILBOX", s1_mailbox_init(root))
        o = crashed_opening(root)
        out = root / "s1_out"
        want = PRECEDENCE[case]
        if case == "local-abort":
            w = out / "aborted.json"
            if sub == "before":
                w.write_text(json.dumps({"reason": "x"}), encoding="utf-8")
                want = S1_LOCAL_ABORT
            else:
                real_gate = t.gate

                def gate_then_witness(*a, _g=real_gate, _w=w, **kw):
                    gv = _g(*a, **kw)
                    _w.write_text(json.dumps({"reason": "x"}), encoding="utf-8")
                    return gv
                monkeypatch.setattr(t, "gate", gate_then_witness)
        elif case == "invalid":
            s1_jappend(root, "TRIAL-INVALID", "reason/stage-replaced", at=o["d45"], detail="a" * 64)
        elif case == "closed":
            s1_ack(root, "close", "S1-CLOSE-ACK", o["d45"], reason="WITHDRAWN", evidence_sha256="0" * 64)
        elif case == "no-open-trial":
            import sqlite3
            con = sqlite3.connect(mb(root))
            con.execute("DELETE FROM messages WHERE body LIKE 'S1-AUDIT-ACK %'")
            con.commit()
            con.close()
        else:                                                           # slot 47's committed capture damaged
            p = next((out / "captures" / o["oc"]).glob("*/backup.sqlite3"))
            p.write_bytes(p.read_bytes() + b"x")
        calls = []
        monkeypatch.setattr(sl, "finalize_close", lambda *a, **kw: calls.append("finalize_close"))
        monkeypatch.setattr(ck, "_opening_stage", lambda *a, **kw: calls.append("_opening_stage"))
        with _Clock(o["d45"]), pytest.raises(SystemExit, match=want):
            ck.finalize_opening(root, now=lambda: o["d45"], mailbox=mb(root))
        assert calls == []                                               # zero finalizer work
        if case == "integrity-violation":
            assert [x.subject for x in jrows(root) if x.kind == "TRIAL-INVALID"] == ["reason/registration-artifact"]
        for mod, name, real in ((t, "gate", REAL_GATE), (sl, "finalize_close", REAL_SL_FINALIZE),
                                (ck, "_opening_stage", REAL_OPENING_STAGE)):
            monkeypatch.setattr(mod, name, real)                         # the next sub-case's fixture is real


REAL_GATE, REAL_SL_FINALIZE, REAL_OPENING_STAGE = t.gate, sl.finalize_close, ck._opening_stage
PRECEDENCE = {"local-abort": r"opening finalizer refused: s1_out/aborted\.json exists \(an observed violation, F8\.1\)",
              "invalid": r"trial INVALID \(reason/stage-replaced\)",
              "closed": r"zero open trials",                    # a CLOSED trial is no open trial (E3.4)
              "no-open-trial": r"zero open trials",
              "integrity-violation": r"INVALID \(registration-artifact\)"}


@pytest.mark.parametrize("case", ["no-worker", "no-slot-intent", "no-process-callback", "no-receipt-callback",
                                  "no-snapshot", "no-provider", "no-capture", "no-synthetic-seal",
                                  "no-qualifying-capture-no-opening"])
def test_opening_finalizer_helper_no_new_work(tmp_path, monkeypatch, case):              # row 493 (CL-A14)
    o = crashed_opening(tmp_path, qualify=(case != "no-qualifying-capture-no-opening"))
    sp = Spies(monkeypatch)
    workers = []
    monkeypatch.setattr(sl, "Worker", lambda *a, **kw: workers.append(1) or pytest.fail("a Worker was built"))
    before = [x.sha for x in jrows(tmp_path)]
    seals_before = sorted(p.name for p in (tmp_path / "s1_out" / "seals").glob("*.json"))
    with _Clock(o["d45"]):
        ck.finalize_opening(tmp_path, now=lambda: o["d45"], mailbox=mb(tmp_path))
    new = [x for x in jrows(tmp_path) if x.sha not in before]
    assert all(x.kind != "SLOT-INTENT" for x in new) and workers == []
    sp.assert_zero()                                                      # receipt/process/capture/provider/valuation
    seals = sorted(p.name for p in (tmp_path / "s1_out" / "seals").glob("*.json"))
    if case == "no-qualifying-capture-no-opening":
        assert stage_kinds(tmp_path, "opening") == [] and seals == seals_before   # no opening, no START
        assert not (tmp_path / "s1_out" / "attest_start.json").exists()
    else:
        assert stage_kinds(tmp_path, "opening") == ["STAGE-INTENT", "STAGE-PREPARED", "STAGE-CREATED"]
        seal = json.loads((tmp_path / "s1_out" / "seals" / f"{o['oc']}.json").read_bytes())
        assert seal["capture"]["scheduled"] == o["s47"].isoformat()      # from the committed capture, not synthetic


@pytest.mark.parametrize("case", ["crashed-last-opening-worker", "idempotent-repeat", "first-qualified-order",
                                  "d-minus-1us", "stage-error-to-refusal"])
def test_opening_finalizer_helper_preserves_recovery(tmp_path, monkeypatch, case):       # row 494 (CL-A15)
    """Migrates test_a_crashed_opening_worker_times_out_at_d_and_the_opening_is_sealed[finalizer-command] (:534) and
    test_the_finalizer_command_turns_an_opening_stage_error_into_a_refusal (:805). C4.4 governs: a TIMEOUT at D never
    by itself authorizes or fabricates a seal (O-C4)."""
    if case == "crashed-last-opening-worker":                           # the final opening slot's worker crashed
        start, cal, oc, _ = s1_plan_audit(tmp_path, START)
        day = next(d for d in cal if d["date"] == oc)
        last = z.schedule(day, cal)[-1]
        s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(last), at=last - timedelta(seconds=30))
        dl = z.resolution_deadline(last, day, cal)
        with _Clock(dl):
            ck.finalize_opening(tmp_path, now=lambda: dl, mailbox=mb(tmp_path))
        assert [x.kind for x in j.subject_rows(jrows(tmp_path), j.slot_subject(last))][-1] == "SLOT-TIMEOUT"
        assert stage_kinds(tmp_path, "opening") == []                   # no qualifying capture: no seal, no opening
        return
    o = crashed_opening(tmp_path)
    if case == "stage-error-to-refusal":
        monkeypatch.setattr(ck, "_opening_stage", lambda *a, **k: (_ for _ in ()).throw(OSError(5, "I/O error")))
        with _Clock(o["d45"]), pytest.raises(SystemExit, match=r"refused with no row.*F0\.7"):
            ck.finalize_opening(tmp_path, now=lambda: o["d45"], mailbox=mb(tmp_path))
        return
    at = o["d45"] - timedelta(microseconds=1) if case == "d-minus-1us" else o["d45"]
    with _Clock(at):
        ck.finalize_opening(tmp_path, now=lambda: at, mailbox=mb(tmp_path))
    k45 = [x.kind for x in j.subject_rows(jrows(tmp_path), j.slot_subject(o["s45"]))]
    if case == "d-minus-1us":
        assert k45 == ["SLOT-INTENT"] and stage_kinds(tmp_path, "opening") == []   # boundary kept
        return
    assert k45 == ["SLOT-INTENT", "SLOT-TIMEOUT"]
    assert stage_kinds(tmp_path, "opening") == ["STAGE-INTENT", "STAGE-PREPARED", "STAGE-CREATED"]
    seal = json.loads((tmp_path / "s1_out" / "seals" / f"{o['oc']}.json").read_bytes())
    assert seal["capture"]["scheduled"] == o["s47"].isoformat()          # first QUALIFIED in slot order
    if case == "idempotent-repeat":
        n = len(jrows(tmp_path))
        with _Clock(o["d45"] + timedelta(minutes=5)):
            ck.finalize_opening(tmp_path, now=lambda: o["d45"] + timedelta(minutes=5), mailbox=mb(tmp_path))
        assert len(jrows(tmp_path)) == n                                  # no row on repeat
